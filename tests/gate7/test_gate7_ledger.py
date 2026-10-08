"""Gate 7 B — ledger and timing: crashes, duplicates, concurrency, tampering, locks, replay,
delayed and out-of-order settlement. Every destructive test runs on a tmp_path ledger.

Behaviour pinned by these regression tests (written as strict xfails before the fixes) (coordinator fixes 3, 5, 6):
- `ShadowLedger.state_as_of(t)` replays excluding settlements whose
  `evidence["evidence_available_utc"]` is after t; pre-fill checks use the state as of the
  decision time, so a settlement learned later can never finance an earlier fill;
- an append against a held write lock fails within a bounded time (the lock wait, measured in the child, is at
  most 2x the ledger's busy timeout: see LOCK_WAIT_BUDGET_S) with an explicit ledger error, never an indefinite hang.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import subprocess
import sys
import textwrap
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import exp001_shadow as shadow
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.outcome_board import build_board
from edge_lab.risk import assess
from edge_lab.shadow_ledger import (
    LOCK_TIMEOUT_S, LedgerConflict, LedgerError, ShadowLedger, _entry_hash, _sha, canonical,
)

from test_forward import D, MARKETS

from gate7.gate7_support import (
    CLOSED, DECISION, OPS, concurrent_worker, day_fills, seed, settle_seed, settled_copy,
    store_settled_markets,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
ACC = "ledger-acct"
SRC = str(Path(__file__).resolve().parents[2] / "src")


def acct(path, bankroll="100.00") -> ShadowLedger:
    lg = ShadowLedger(path)
    lg.open_account(ACC, starting_bankroll=Decimal(bankroll), strategy="gate7", opened_at_utc=T0.isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id=FEES.schedule_id)
    return lg


def raw(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def drop_triggers(path) -> None:
    with closing(raw(path)) as conn:
        conn.execute("DROP TRIGGER ledger_entries_no_update")
        conn.execute("DROP TRIGGER ledger_entries_no_delete")


def triggers(path) -> set[str]:
    with closing(raw(path)) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


# --------------------------------------------------------------------------- crash between writes


class SimulatedCrash(BaseException):
    """Stands in for a process dying mid-day (not an ordinary Exception, so nothing swallows it)."""


def _crash_on(ledger, method, nth):
    real = getattr(ledger, method)
    calls = {"n": 0}

    def wrapper(*a, **kw):
        calls["n"] += 1
        if calls["n"] == nth:
            raise SimulatedCrash(f"{method} call {nth}")
        return real(*a, **kw)
    setattr(ledger, method, wrapper)


@pytest.mark.parametrize("method, nth", [("record_fill", 1), ("record_fill", 2), ("record_decision", 5)])
def test_crash_mid_day_then_rerun_equals_a_clean_run(full_day, tmp_path, model, method, nth):
    clean = ShadowLedger(tmp_path / "clean.sqlite3")
    shadow.run_day(full_day, clean, D, model=model, now=CLOSED)

    crashed = ShadowLedger(tmp_path / "crashed.sqlite3")
    _crash_on(crashed, method, nth)
    with pytest.raises(SimulatedCrash):
        shadow.run_day(full_day, crashed, D, model=model, now=CLOSED)
    restarted = ShadowLedger(crashed.path)
    for account in restarted.accounts():  # a restart sees a readable, consistent partial day
        restarted.verify_chain(account)
    assert _entry_count(restarted) < _entry_count(clean)
    shadow.run_day(full_day, restarted, D, model=model, now=CLOSED)  # restart
    _assert_same_ledger(restarted, clean)


def _entry_count(lg):
    return sum(len(lg.entries(a)) for a in lg.accounts())


def _assert_same_ledger(a, b):
    assert a.accounts() == b.accounts()
    for account in b.accounts():
        assert a.verify_chain(account) == b.verify_chain(account)
        assert a.state(account).to_dict() == b.state(account).to_dict()


def test_process_killed_inside_an_append_transaction_leaves_no_row(tmp_path):
    path = tmp_path / "killed.sqlite3"
    lg = acct(path)
    head = lg.verify_chain(ACC)
    script = textwrap.dedent(f"""
        import os, sqlite3
        conn = sqlite3.connect({str(path)!r}, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO ledger_entries (account_id, kind, entry_key, effective_at_utc, payload_json, "
                     "payload_sha256, prev_hash, entry_hash, appended_at_utc) VALUES "
                     "('{ACC}', 'decision', 'half', 't', '{{}}', 'x', 'y', 'z', 't')")
        os._exit(9)  # die before COMMIT
    """)
    assert subprocess.run([sys.executable, "-c", script], timeout=20).returncode == 9
    after = ShadowLedger(path)
    assert after.verify_chain(ACC) == head and len(after.entries(ACC)) == 1


def test_failed_invariant_inside_append_rolls_back(tmp_path):
    lg = acct(tmp_path / "l.sqlite3")
    seed(lg, ACC, "a", price="0.40", filled_at=T0, event="e", cluster="c")
    n = len(lg.entries(ACC))
    with pytest.raises(LedgerError):  # settlement before the fill: refused by the candidate replay
        lg.record_settlement(ACC, fill_id="seed-f-a", outcome="YES", evidence={},
                             settled_at_utc=(T0 - timedelta(hours=1)).isoformat())
    assert len(lg.entries(ACC)) == n
    lg.verify_chain(ACC)


def _fail_on_second_fill(ledger):
    real = ledger.record_fill
    calls = {"n": 0}

    def wrapper(account, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            raise LedgerConflict("injected conflict on the second fill")
        return real(account, payload)
    ledger.record_fill = wrapper


def test_ledger_conflict_mid_day_is_surfaced_and_recoverable(full_day, tmp_path, model):
    """Coordinator fix 6: a conflict inside a day is never hidden behind a success summary, and
    the partial day is explainable: a clean re-run completes it to exactly the clean state."""
    clean = ShadowLedger(tmp_path / "clean.sqlite3")
    shadow.run_day(full_day, clean, D, model=model, now=CLOSED)
    lg = ShadowLedger(tmp_path / "conflicted.sqlite3")
    _fail_on_second_fill(lg)
    try:
        summary = shadow.run_day(full_day, lg, D, model=model, now=CLOSED)
    except LedgerConflict:
        pass
    else:  # an orchestrator that catches it must say FAILED, not a normal day
        assert "FAILED" in {summary.get("status"), summary.get("run_status"), summary.get("stage_b_day_status")}
    for account in ShadowLedger(lg.path).accounts():
        ShadowLedger(lg.path).verify_chain(account)  # the partial day is readable and consistent
    shadow.run_day(full_day, ShadowLedger(lg.path), D, model=model, now=CLOSED)
    _assert_same_ledger(ShadowLedger(lg.path), clean)


# --------------------------------------------------------------------------- duplicates and conflicts


def test_duplicate_and_conflicting_entries(tmp_path):
    lg = acct(tmp_path / "l.sqlite3")
    seed(lg, ACC, "a", price="0.40", filled_at=T0, event="e", cluster="c")
    settle_seed(lg, ACC, "a", "YES", settled_at=T0 + timedelta(days=1))
    settle_seed(lg, ACC, "a", "YES", settled_at=T0 + timedelta(days=1))  # identical: no-op
    with pytest.raises(LedgerConflict):  # same outcome, different effective time
        settle_seed(lg, ACC, "a", "YES", settled_at=T0 + timedelta(days=2))
    with pytest.raises(LedgerConflict):  # same outcome, different evidence
        settle_seed(lg, ACC, "a", "YES", settled_at=T0 + timedelta(days=1), available_at=T0 + timedelta(days=3))
    s = lg.state(ACC)
    assert s.settlements == 1 and s.realized_pnl == Decimal("0.58")


def test_no_fill_then_filled_for_same_decision_conflicts(tmp_path):
    lg = acct(tmp_path / "l.sqlite3")
    lg.record_decision(ACC, {"decision_id": "d", "opportunity_id": "o", "as_of_utc": T0.isoformat(),
                             "qualification": "QUALIFY", "reason": "QUALIFY"})
    base = {"fill_id": "f", "decision_id": "d", "filled_at_utc": T0.isoformat(), "venue": "kalshi",
            "market_id": "kalshi:M", "event_id": "e", "outcome_cluster": "c", "side": "YES"}
    lg.record_fill(ACC, {**base, "status": "NO_FILL", "reason": "PRICE_MOVED_AWAY", "quantity": 0})
    cost = FEES.taker_buy(1, Decimal("0.40"))
    with pytest.raises(LedgerConflict):
        lg.record_fill(ACC, {**base, "status": "FILLED", "reason": "FILLED", "quantity": 1, "price": "0.40",
                             "total_cost": str(cost.total_cost)})
    assert lg.state(ACC).fills == 0


def test_same_fill_id_under_two_decisions_is_refused(tmp_path):
    lg = acct(tmp_path / "l.sqlite3")
    seed(lg, ACC, "a", price="0.40", filled_at=T0, event="e", cluster="c")
    lg.record_decision(ACC, {"decision_id": "d2", "opportunity_id": "o2", "as_of_utc": T0.isoformat(),
                             "qualification": "QUALIFY", "reason": "QUALIFY"})
    cost = FEES.taker_buy(1, Decimal("0.40"))
    with pytest.raises(LedgerError, match="used twice"):
        lg.record_fill(ACC, {"fill_id": "seed-f-a", "decision_id": "d2", "filled_at_utc": T0.isoformat(),
                             "status": "FILLED", "reason": "FILLED", "venue": "kalshi", "market_id": "kalshi:X",
                             "event_id": "e", "outcome_cluster": "c", "side": "YES", "quantity": 1,
                             "price": "0.40", "total_cost": str(cost.total_cost)})
    lg.verify_chain(ACC)


# --------------------------------------------------------------------------- concurrency


def test_concurrent_appends_from_processes_lose_nothing_and_duplicate_nothing(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    acct(path)
    # fork where available (Linux CI); spawn elsewhere (Windows has no fork). The worker lives in
    # an importable module, so spawn children can unpickle it.
    ctx = multiprocessing.get_context("fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn")
    queue = ctx.Queue()
    workers, per = 4, 12
    procs = [ctx.Process(target=concurrent_worker, args=(str(path), ACC, w, per, T0.isoformat(), queue))
             for w in range(workers)]
    for p in procs:
        p.start()
    results = [queue.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    assert all(r["errors"] == [] and r["created"] == per for r in results)
    outcomes = sorted(r["contested"] for r in results)
    assert outcomes.count("won") == 1 and outcomes.count("conflict") == workers - 1
    lg = ShadowLedger(path)
    rows = lg.entries(ACC)
    keys = [(r["kind"], r["entry_key"]) for r in rows]
    assert len(keys) == len(set(keys)) == 1 + workers * per + 2  # opened + own + shared + contested
    assert lg.state(ACC).decisions == workers * per + 2
    lg.verify_chain(ACC)
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs) and [r["prev_hash"] for r in rows[1:]] == [r["entry_hash"] for r in rows[:-1]]


# --------------------------------------------------------------------------- tampering and triggers


def _tampered(tmp_path):
    path = tmp_path / "t.sqlite3"
    lg = acct(path)
    seed(lg, ACC, "a", price="0.40", filled_at=T0, event="e", cluster="c")
    seed(lg, ACC, "b", price="0.40", filled_at=T0, event="e", cluster="c")
    drop_triggers(path)
    return path, lg


def test_triggers_block_raw_update_and_delete(tmp_path):
    path = tmp_path / "t.sqlite3"
    acct(path)
    with closing(raw(path)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE ledger_entries SET payload_json = '{}'")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM ledger_entries")


def test_payload_edit_is_detected(tmp_path):
    path, lg = _tampered(tmp_path)
    with closing(raw(path)) as conn:
        conn.execute("UPDATE ledger_entries SET payload_json = replace(payload_json, '\"0.40\"', '\"0.01\"') "
                     "WHERE kind = 'fill' AND entry_key = 'seed-d-a'")
    with pytest.raises(LedgerError, match="does not match its hash"):
        lg.verify_chain(ACC)


def test_consistently_rehashed_middle_entry_breaks_the_chain(tmp_path):
    path, lg = _tampered(tmp_path)
    with closing(raw(path)) as conn:
        row = conn.execute("SELECT * FROM ledger_entries WHERE kind = 'fill' AND entry_key = 'seed-d-a'").fetchone()
        payload = json.loads(row["payload_json"])
        payload["price"] = "0.39"
        text = canonical(payload)
        new_hash = _entry_hash(row["prev_hash"], row["account_id"], row["kind"], row["entry_key"],
                               row["effective_at_utc"], _sha(text))
        conn.execute("UPDATE ledger_entries SET payload_json = ?, payload_sha256 = ?, entry_hash = ? WHERE seq = ?",
                     (text, _sha(text), new_hash, row["seq"]))
    with pytest.raises(LedgerError, match="hash chain broken"):
        lg.verify_chain(ACC)


@pytest.mark.parametrize("sql", [
    "DELETE FROM ledger_entries WHERE kind = 'decision' AND entry_key = 'seed-d-b'",  # middle row
    "UPDATE ledger_entries SET effective_at_utc = '2026-01-01T00:00:00+00:00' WHERE entry_key = 'seed-d-a'",
    "UPDATE ledger_entries SET seq = seq + 1000 WHERE kind = 'decision' AND entry_key = 'seed-d-a'",  # reorder
])
def test_deletion_backdating_and_reordering_are_detected(tmp_path, sql):
    path, lg = _tampered(tmp_path)
    with closing(raw(path)) as conn:
        conn.execute(sql)
    with pytest.raises(LedgerError):
        lg.verify_chain(ACC)


def test_known_limit_head_truncation_and_appended_at_are_not_detected(tmp_path):
    """Documented limitation (ADR 0014: tamper-evident, not a MAC). Without an external anchor of
    the head hash, removing the newest entries leaves a valid shorter chain; appended_at_utc is
    outside the hash by design. GATE7-F09 tracks the missing anchor."""
    path, lg = _tampered(tmp_path)
    full_head = lg.state(ACC).last_entry_hash
    with closing(raw(path)) as conn:
        conn.execute("UPDATE ledger_entries SET appended_at_utc = 'forged'")
        last = conn.execute("SELECT max(seq) FROM ledger_entries").fetchone()[0]
        conn.execute("DELETE FROM ledger_entries WHERE seq = ?", (last,))
    head = lg.state(ACC).last_entry_hash  # the hash chain alone still replays
    assert head != full_head and lg.state(ACC).fills == 1
    # ...but the tampering needed to do it (dropping the append-only triggers) is detected.
    with pytest.raises(LedgerError, match="triggers missing"):
        lg.verify_chain(ACC)


def test_reopening_for_write_restores_dropped_triggers(tmp_path):
    path, _ = _tampered(tmp_path)
    assert not triggers(path) & {"ledger_entries_no_update", "ledger_entries_no_delete"}
    ShadowLedger(path)
    assert {"ledger_entries_no_update", "ledger_entries_no_delete"} <= triggers(path)


def test_readonly_verification_reports_missing_triggers(tmp_path):
    path, _ = _tampered(tmp_path)
    with pytest.raises(LedgerError, match="trigger"):
        ShadowLedger.open_readonly(path).verify_chain(ACC)


# --------------------------------------------------------------------------- locked database


def test_short_lock_waits_then_appends(tmp_path):
    path = tmp_path / "l.sqlite3"
    lg = acct(path)
    holder = raw(path)
    holder.execute("BEGIN IMMEDIATE")
    released = threading.Timer(0.3, lambda: holder.execute("COMMIT"))
    released.start()
    try:
        lg.record_decision(ACC, {"decision_id": "d", "opportunity_id": "o", "as_of_utc": T0.isoformat(),
                                 "qualification": "REJECT", "reason": "NO_EDGE"})
    finally:
        released.join()
        holder.close()
    assert lg.state(ACC).decisions == 1


def test_readers_are_not_blocked_by_a_pending_writer(tmp_path):
    path = tmp_path / "l.sqlite3"
    lg = acct(path)
    with closing(raw(path)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        assert ShadowLedger.open_readonly(path).state(ACC).decisions == 0
        holder.execute("ROLLBACK")


# "Fast" is measured inside the child, from opening the ledger to the LedgerError, so interpreter startup and
# imports (about 0.5 s on the owner's laptop, more under load) are not charged to it. The child opens the ledger,
# then appends; with an EXCLUSIVE lock held, the open (its schema check) already waits and fails, so the error
# comes from the open, and the append is reached only if the open wrongly succeeds.
# The budget is the ledger's own SQLite busy timeout (LOCK_TIMEOUT_S, 5 s) times 2. Measured on Windows (SQLite
# 3.49.1): a 5000 ms busy_timeout fails after 7.47 s and a 1000 ms one after 1.81 s. SQLite's busy handler counts
# only its nominal sleeps (1, 2, 5, ... then 100 ms; about 59 retries for 5 s), and on Windows each retry costs
# about 42 ms more than its nominal sleep ((7.47 - 5.0) / 59; the reviewer measured the same). shadow_ledger's
# message still says "waited 5s" (src, left as is). The child's wait was 7.66 s alone; the old 8 s bound on the
# whole child process (startup included) sat at that limit and timed out under load. 2x leaves load headroom over
# the measured 1.5x and still fails a second busy wait or a retry loop on Windows (about 15 s for two). On Linux,
# where the overhead is small, the wait is about 5 s, so the budget there proves a bounded failure, not one wait.
LOCK_WAIT_BUDGET_S = 2 * LOCK_TIMEOUT_S
HANG_GUARD_S = 60  # the child process as a whole: only a hang reaches this, never the speed claim


def test_append_against_held_lock_fails_fast_with_ledger_error(tmp_path):
    path = tmp_path / "locked.sqlite3"
    acct(path)
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {SRC!r})
        from edge_lab.shadow_ledger import LedgerError, ShadowLedger
        started = time.perf_counter()
        try:
            lg = ShadowLedger({str(path)!r})  # a fresh process: open, then append
            lg.record_decision({ACC!r}, {{"decision_id": "d", "opportunity_id": "o", "as_of_utc": "x",
                                          "qualification": "REJECT", "reason": "NO_EDGE"}})
        except LedgerError as exc:
            print("WAITED", time.perf_counter() - started)
            print("LEDGER_ERROR", exc)
            sys.exit(3)
        except Exception as exc:
            print("OTHER", type(exc).__name__, exc)
            sys.exit(4)
        print("APPENDED")
    """)
    holder = raw(path)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=HANG_GUARD_S)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert done.returncode == 3, done.stdout + done.stderr
    assert any(w in done.stdout.lower() for w in ("lock", "busy"))
    waited = float(next(line.split()[1] for line in done.stdout.splitlines() if line.startswith("WAITED")))
    assert waited <= LOCK_WAIT_BUDGET_S, f"the ledger failed after {waited:.2f}s, over {LOCK_WAIT_BUDGET_S}s"
    assert ShadowLedger(path).state(ACC).decisions == 0


# --------------------------------------------------------------------------- restart / replay determinism


def test_rebuild_from_evidence_after_settlement_is_identical(full_day, tmp_path, model):
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="settle",
                          fetched_at="2026-09-24T14:00:00+00:00")
    heads, states = [], []
    for name in ("a", "b"):
        lg = ShadowLedger(tmp_path / f"{name}.sqlite3")
        shadow.run_day(full_day, lg, D, model=model, now=CLOSED)
        shadow.settle_open_positions(full_day, lg)
        shadow.run_day(full_day, ShadowLedger(lg.path), D, model=model, now=CLOSED)  # replay after settling
        heads.append(lg.verify_chain(OPS))
        states.append(lg.state(OPS).to_dict())
    assert heads[0] == heads[1] and states[0] == states[1]
    assert states[0]["settlements"] == 3 and states[0]["committed_capital"] == "0"


# --------------------------------------------------------------------------- delayed settlement evidence


def test_delayed_settlement_stays_open_locked_and_uncredited(full_day, ledger, model):
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    state = ledger.state(OPS)
    late = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)  # past the expected settlement (2026-09-24 22:00Z)
    assert shadow.settle_open_positions(full_day, ledger)["settled"] == []
    r = assess(ledger.state(OPS), shadow.RISK_POLICY, late)
    buckets = {b.horizon: b for b in r.capital_release}
    assert buckets["locked"].positions == 3 and buckets["locked"].guaranteed_cash == 0
    assert buckets["available_now"].committed_capital == state.settled_cash  # no winnings counted
    assert {g.horizon for g in build_board(ledger.state(OPS), late)} == {"overdue"}
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="late-settle",
                          fetched_at="2026-09-25T04:00:00+00:00")
    settled = shadow.settle_open_positions(full_day, ledger)["settled"]
    assert len([s for s in settled if s["account_id"] == OPS]) == 3


def test_settlement_evidence_records_when_it_became_available(full_day, ledger, model):
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="settle",
                          fetched_at="2026-09-24T14:00:00+00:00")
    shadow.settle_open_positions(full_day, ledger)
    rows = [json.loads(r["payload_json"]) for r in ledger.entries(OPS) if r["kind"] == "settlement"]
    assert rows
    for s in rows:
        snap = full_day.snapshots_by_id([s["evidence"]["snapshot_id"]])[s["evidence"]["snapshot_id"]]
        assert s["evidence"]["evidence_available_utc"] == snap["fetched_at_utc"]


def test_contradicting_later_settlement_capture_is_reported(full_day, ledger, model):
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="s1",
                          fetched_at="2026-09-24T14:00:00+00:00")
    shadow.settle_open_positions(full_day, ledger)
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 70), run_id="s2",
                          fetched_at="2026-09-24T15:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    flagged = {e["position_id"] for e in report.get("conflicts", []) + report.get("pending", [])}
    # 67 -> 70 flips B67.5 YES (won -> lost); a rebuild would silently book a different P&L.
    b675 = next(p for p in ledger.state(OPS).positions if p.market_id.endswith("B67.5"))
    assert b675.position_id in flagged


# --------------------------------------------------------------------------- out-of-order / point-in-time cash


def _pit_ledger(tmp_path):
    """Bankroll 1.00; A costs 0.99 at T0 and wins; settled at T0+1d, evidence known at T0+2d."""
    lg = acct(tmp_path / "pit.sqlite3", bankroll="1.00")
    seed(lg, ACC, "a", price="0.98", filled_at=T0, event="e", cluster="c",
         expected_settlement=T0 + timedelta(days=1))
    settle_seed(lg, ACC, "a", "YES", settled_at=T0 + timedelta(days=1), available_at=T0 + timedelta(days=2))
    return lg


def test_state_as_of_excludes_settlements_not_yet_known(tmp_path):
    lg = _pit_ledger(tmp_path)
    between = lg.state_as_of(ACC, T0 + timedelta(days=1, hours=12))  # settled, but evidence not yet available
    assert between.settled_cash == Decimal("0.01") and between.open_positions()[0].position_id == "seed-f-a"
    known = lg.state_as_of(ACC, T0 + timedelta(days=2))
    assert known.settled_cash == Decimal("1.01") and known.open_positions() == []
    assert lg.state_as_of(ACC, T0 + timedelta(days=30)).settled_cash == lg.state(ACC).settled_cash


def test_ledger_refuses_fill_financed_by_a_later_settlement(tmp_path):
    lg = _pit_ledger(tmp_path)
    with pytest.raises(LedgerError):  # at T0+1h settled cash was 0.01 < 0.42
        seed(lg, ACC, "b", price="0.40", filled_at=T0 + timedelta(hours=1), event="e2", cluster="c2")


def test_catch_up_settlement_cannot_finance_an_earlier_day(full_day, ledger, model):
    shadow.ensure_account(ledger)
    # Before D's decision: one position spends all but 0.02 of the notional bankroll.
    seed(ledger, OPS, "big", price="0.93", qty=1070, filled_at=DECISION - timedelta(hours=20),
         event="weather:seed-big", cluster="weather:seed-big", expected_settlement=DECISION + timedelta(hours=1))
    assert ledger.state(OPS).settled_cash == Decimal("0.02")
    # Catch-up: it settled (won) before D is processed, but the evidence arrived after D's decision.
    settle_seed(ledger, OPS, "big", "YES", settled_at=DECISION + timedelta(hours=1),
                available_at=DECISION + timedelta(hours=2))
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    got = day_fills(ledger)
    assert len(got) == 3 and all(f["status"] == "NO_FILL" for f in got)
    # Sizing already sees only the cash known at D's decision (0.02), so it sizes to zero;
    # a pre-fill risk veto or cash refusal would be equally correct.
    assert {f["reason"] for f in got} <= {"ZERO_SIZE", "RISK_VETO", "INSUFFICIENT_CASH"}


def test_settlement_is_never_stamped_after_its_evidence_was_captured(full_day, ledger, model):
    from edge_lab.freshness import parse_utc
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    fetched = "2026-09-24T14:00:00+00:00"  # captured page lacks settlement_ts, like the fixture markets
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="settle", fetched_at=fetched)
    shadow.settle_open_positions(full_day, ledger)
    for row in ledger.entries(OPS):
        if row["kind"] == "settlement":
            assert parse_utc(json.loads(row["payload_json"])["settled_at_utc"]) <= parse_utc(fetched)
    assess(ledger.state(OPS), shadow.RISK_POLICY, parse_utc(fetched) + timedelta(hours=1))  # must not raise
