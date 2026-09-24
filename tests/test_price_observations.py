"""Later/closing price observations (ADR 0030): planning from recorded decisions (qualified and
rejected), backfill from the forward captures, bounded manual capture, close vs latest-pre-close
labelling, visible misses, append-only storage, protected windows. No network: every GET goes to
a fake that serves the recorded public fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import cli, exp001_shadow as shadow, exp001_stageb as stageb, forward
from edge_lab import price_observations as po
from edge_lab.http import HttpFetchError
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore
from test_forward import BOOK, BRACKETS, MARKETS, D, Clock, FakeApi, _full_day, at

UTC = timezone.utc
CLOSED = at(23, 0)  # 2026-09-22 23:00Z: D's decision (22:00Z) and re-check windows are over
EVENT = "KXHIGHNY-26SEP23"
CLOSE = datetime(2026, 9, 24, 5, 0, tzinfo=UTC)  # the fixture markets' close_time
LISTING = f"/markets?event_ticker={EVENT}"
PM_FIX = Path(__file__).parent / "fixtures" / "polymarket_us"
PM_BOOK = json.loads((PM_FIX / "book_documented_example.json").read_text(encoding="utf-8"))
PM_SLUG = "will-team-a-win"
HISTORY_KEYS = {
    "observation_id", "target_id", "phase", "label", "side", "venue", "market_id", "native_market_id", "event_id",
    "target_utc", "observed_at_utc", "deviation_s", "source_timestamp_utc", "bid", "ask", "ask_size", "depth",
    "price_grid", "freshness", "market_status", "close_time_utc", "close_label", "close_proof", "close_tolerance_s",
    "rules_sha256",
    "snapshot_id", "source_sha256", "collection_status", "miss_reason", "executable",
    "is_latest_pre_close_observation",
}


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "edge.sqlite3")


def _ledger(store, tmp_path, monkeypatch, model) -> ShadowLedger:
    _full_day(store, monkeypatch)
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    return ledger


def _planned(store, tmp_path, monkeypatch, model, now=CLOSED):
    ledger = _ledger(store, tmp_path, monkeypatch, model)
    decisions = po.decisions_from_ledger(ShadowLedger.open_readonly(ledger.path), store, since=now - timedelta(days=7))
    return decisions, po.plan(store, decisions=decisions, now=now)


def _no_network(*_a, **_k):
    raise AssertionError("no network expected")


def _api(monkeypatch, clock, routes=None) -> FakeApi:
    api = FakeApi(clock, routes if routes is not None else {"/orderbook": BOOK, LISTING: MARKETS})
    monkeypatch.setattr(po, "fetch_json_result", api)
    return api


def _states(store) -> dict[str, str | None]:
    return {r["target_id"]: r["state"] for r in store.price_targets()}


def _target(store, phase, native=BRACKETS[0]):
    return next(r for r in store.price_targets(market_id=f"kalshi:{native}") if r["phase"] == phase)


def _runs(store) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]


PROVEN_CLOSE = "close (within 60 s of trading close)"


# --------------------------------------------------------------------------- planning


def test_every_recorded_decision_qualified_or_rejected_is_planned(store, tmp_path, monkeypatch, model):
    decisions, report = _planned(store, tmp_path, monkeypatch, model)
    assert sorted(d.native_market_id for d in decisions) == BRACKETS
    quals = {q.split(":")[1] for d in decisions for q in d.qualifications}
    assert quals == {"QUALIFY", "REJECT"}  # rejected markets are observed too
    d = decisions[0]
    assert d.close_time_utc == CLOSE and d.native_event_id == EVENT and d.rules_sha256
    assert d.decision_as_of_utc == at(22, 0)
    # Per market: 5 captured phases + decision and recheck backfilled from the forward captures.
    assert report["targets_planned"] == 6 * 7 and report["backfill_rows"] == 6 * 2 * 2
    targets = {t["phase"]: t for t in store.price_targets(market_id=d.market_id)}
    assert set(targets) == {"decision", "recheck", "post_decision_1h", "post_decision_6h", "pre_close", "close",
                            "settlement_preceding"}
    assert targets["post_decision_1h"]["target_utc"] == "2026-09-22T23:00:00+00:00"
    assert targets["post_decision_6h"]["target_utc"] == "2026-09-23T04:00:00+00:00"
    assert targets["pre_close"]["target_utc"] == "2026-09-24T04:45:00+00:00"
    assert targets["close"]["target_utc"] == "2026-09-24T04:59:30+00:00"
    assert targets["close"]["deadline_utc"] == "2026-09-24T04:59:50+00:00"
    assert targets["settlement_preceding"]["target_utc"] == "2026-09-24T18:30:00+00:00"
    assert all(t["close_basis"] == "kalshi_close_time_v1" for t in targets.values())
    assert json.loads(targets["post_decision_1h"]["detail_json"])["qualifications"]


def test_plan_is_idempotent_and_makes_no_request(store, tmp_path, monkeypatch, model):
    decisions, _ = _planned(store, tmp_path, monkeypatch, model)
    monkeypatch.setattr(po, "fetch_json_result", _no_network)
    rows, runs = len(store.price_observations()), _runs(store)
    assert po.plan_work(store, decisions, CLOSED + timedelta(minutes=5)) == 0
    again = po.plan(store, decisions=decisions, now=CLOSED + timedelta(minutes=5))
    assert again["state"] == "NOTHING_TO_DO" and again["targets_planned"] == 0
    assert len(store.price_observations()) == rows and _runs(store) == runs  # an idle plan writes nothing


def test_two_decisions_on_one_market_share_their_targets(store, tmp_path, monkeypatch, model):
    from dataclasses import replace

    ledger = _ledger(store, tmp_path, monkeypatch, model)
    decisions = po.decisions_from_ledger(ledger, store)
    later = replace(decisions[0], decision_as_of_utc=decisions[0].decision_as_of_utc + timedelta(minutes=1),
                    decision_ref="another-decision")
    report = po.plan(store, decisions=[decisions[0], later], now=CLOSED)  # no attempt-id collision
    rows = [r for r in store.price_observations(market_id=decisions[0].market_id) if r["phase"] == "decision"]
    assert len(rows) == 2 and report["targets_known"] >= 3  # backfilled once; shared targets planned once
    targets = [t for t in store.price_targets(market_id=decisions[0].market_id) if t["phase"] == "post_decision_1h"]
    assert len(targets) == 2  # each decision time has its own +1 h target


def test_recheck_rows_carry_no_market_fields_they_did_not_read(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    rows = [r for r in store.price_observations() if r["phase"] == "recheck"]
    assert rows and all(r["market_status"] is None and r["close_time_utc"] is None and r["rules_sha256"] is None
                        for r in rows)
    detail = json.loads(_target(store, "recheck")["detail_json"])
    assert detail["market_fields"].startswith("not re-read at the re-check")
    decision = [r for r in store.price_observations() if r["phase"] == "decision"]
    assert all(r["market_status"] == "active" and r["close_time_utc"] == "2026-09-24T05:00:00+00:00" for r in decision)


def test_backfill_reuses_the_forward_snapshots(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    native = "KXHIGHNY-26SEP23-B69.5"
    decision = store.forward_captures(target_date=D.isoformat(), phase="decision")[-1]
    book = json.loads(decision["links_json"])["books"][native]
    rows = [r for r in store.price_observations(market_id=f"kalshi:{native}") if r["phase"] == "decision"]
    assert {r["side"] for r in rows} == {"YES", "NO"} and {r["snapshot_id"] for r in rows} == {book["snapshot_id"]}
    snap = store.snapshots_by_id([book["snapshot_id"]])[book["snapshot_id"]]
    assert {r["source_sha256"] for r in rows} == {snap["raw_sha256"] or snap["payload_sha256"]}
    yes = next(r for r in rows if r["side"] == "YES")
    best_no_bid = max(Decimal(p) for p, s in BOOK["orderbook_fp"]["no_dollars"] if Decimal(s) > 0)
    assert Decimal(yes["ask"]) == 1 - best_no_bid and yes["freshness"] == "fresh"
    assert json.loads(yes["depth_json"])["depth_limit"] == forward.BOOK_DEPTH
    assert all(r["collection_status"] == "CAPTURED" for r in store.price_observations() if r["phase"] == "recheck")


def test_close_is_planned_only_where_the_venue_defines_a_trading_close():
    record = po.DecisionRecord(
        venue="polymarket_us", market_id=f"polymarket_us:{PM_SLUG}", native_market_id=PM_SLUG, event_id="e",
        native_event_id=None, decision_as_of_utc=datetime(2026, 10, 1, 14, tzinfo=UTC), decision_ref="d",
        close_time_utc=datetime(2026, 10, 2, 14, tzinfo=UTC),  # even if given, not a documented trading close
        pre_close_reference_utc=datetime(2026, 10, 2, 14, tzinfo=UTC),
        pre_close_reference_basis="assetPriceTerms.windowEnd (measurement window end, not a trading close)")
    targets, skipped = po.targets_for(record)
    assert {t["phase"] for t in targets} == {"post_decision_1h", "post_decision_6h", "pre_close"}
    assert all(t["close_time_utc"] is None for t in targets)
    assert any(s["phase"] == "close" and s["reason"].startswith("CLOSE_NOT_DEFINABLE") for s in skipped)
    pre = next(t for t in targets if t["phase"] == "pre_close")
    assert "windowEnd" in pre["detail"]["reference_basis"]


def test_targets_are_moved_out_of_protected_windows_but_close_is_not():
    decided = datetime(2026, 10, 1, 20, 45, tzinfo=UTC)  # 16:45 ET: +1 h lands at 17:45 ET
    close = datetime(2026, 10, 1, 21, 50, tzinfo=UTC)  # 17:50 ET
    record = po.DecisionRecord(venue="kalshi", market_id="kalshi:X-1", native_market_id="X-1", event_id="e",
                               native_event_id="X", decision_as_of_utc=decided, decision_ref="d",
                               close_time_utc=close, pre_close_reference_utc=close)
    targets = {t["phase"]: t for t in po.targets_for(record)[0]}
    # +1 h would fall inside 17:40-18:50 ET; the close (17:50 ET) is too early to move it after, so it moves before.
    assert targets["post_decision_1h"]["target_utc"] == "2026-10-01T21:35:00+00:00"  # 17:35 ET
    assert targets["post_decision_1h"]["detail"]["shifted_out_of_protected_window"]
    assert targets["close"]["target_utc"] == "2026-10-01T21:49:30+00:00"  # never moved: it is the close
    assert po.protected_window_at(datetime(2026, 10, 1, 21, 49, 30, tzinfo=UTC), datetime(2026, 10, 1, 21, 51, tzinfo=UTC))


# --------------------------------------------------------------------------- capture


def test_capture_is_bounded_idempotent_and_appends(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(CLOSED)
    api = _api(monkeypatch, clock)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["state"] == "CAPTURED"
    assert report["requests"] == 1 + 6 and api.count(LISTING) == 1 and api.count("/orderbook") == 6
    assert report["by_status"] == {"CAPTURED": 12}
    rows = [r for r in store.price_observations() if r["phase"] == "post_decision_1h"]
    assert len(rows) == 12 and all(r["freshness"] == "fresh" and r["snapshot_id"] for r in rows)
    assert all(r["recorded_at_utc"].startswith("2026-09-22T23:00") for r in rows)  # the injected clock
    assert all(r["rules_sha256"] and r["close_time_utc"] == "2026-09-24T05:00:00Z" for r in rows)
    assert all(json.loads(r["price_grid_json"])["ranges"] for r in rows)
    # A second tick in the same window sends nothing and writes no observation.
    n, runs = len(store.price_observations()), _runs(store)
    code, again = po.capture(store, clock=clock, sleep=clock.sleep)
    assert (code, again["state"], again["requests"]) == (0, "NOTHING_DUE", 0) and len(api.calls) == 7
    assert len(store.price_observations()) == n and _runs(store) == runs  # idle: not even a collection run
    code, again = po.run_capture(store.path, clock=clock, sleep=clock.sleep)
    assert (code, again["state"]) == (0, "NOTHING_DUE") and _runs(store) == runs


def test_request_budget_defers_the_rest_without_losing_them(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(CLOSED)
    api = _api(monkeypatch, clock)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep, max_requests=3)
    assert report["requests"] == 3 and len(api.calls) == 3 and len(report["deferred"]) == 4
    assert all(_states(store)[t] is None for t in report["deferred"])  # still planned, not overwritten
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert report["requests"] == 1 + 4 and report["by_status"] == {"CAPTURED": 8}
    with pytest.raises(ValueError):
        po.capture(store, clock=clock, sleep=clock.sleep, max_requests=po.MAX_REQUESTS + 1)


def test_failed_attempt_is_retried_then_missed_with_its_reason(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    bad = BRACKETS[0]
    clock = Clock(CLOSED)
    routes = {f"/markets/{bad}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3), "/orderbook": BOOK,
              LISTING: MARKETS}
    _api(monkeypatch, clock, routes)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    # Retryable: the deadline is after the next scheduled tick, so the run records it and does not fail.
    assert code == 0 and report["state"] == "PARTIAL_RETRYING" and report["by_status"] == {"CAPTURED": 10, "FAILED": 1}
    assert report["failed_final"] == [] and len(report["failed_retrying"]) == 1
    t = _target(store, "post_decision_1h", bad)
    assert t["state"] == "FAILED" and t["state_reason"].startswith("BOOK_FAILED")
    clock.now = CLOSED + timedelta(minutes=20)
    api = _api(monkeypatch, clock, routes)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    # The last chance before the deadline failed too: now the run fails (and would alert).
    assert code == 1 and report["state"] == "PARTIAL" and api.count("/orderbook") == 1  # only the failed target
    assert report["failed_retrying"] == [] and len(report["failed_final"]) == 1
    clock.now = CLOSED + timedelta(minutes=31)
    api = _api(monkeypatch, clock, routes)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and api.calls == []
    t = _target(store, "post_decision_1h", bad)
    assert t["state"] == "MISSED" and "last attempt failed" in t["state_reason"]


def test_missed_targets_stay_visible(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 23, 5, 0, tzinfo=UTC))  # 01:00 ET: the +1 h and +6 h windows have passed
    api = _api(monkeypatch, clock)
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["state"] == "NOTHING_DUE" and api.calls == []
    assert len(report["missed"]) == 12
    t = _target(store, "post_decision_6h")
    assert t["state"] == "MISSED" and t["state_reason"].startswith("NOT_CAPTURED_BY_DEADLINE")
    assert "(policy ADR0030_OPTION_A)" in t["state_reason"]
    summary = po.status(SnapshotStore.open_readonly(store.path), now=clock.now, systemctl=lambda args: "enabled"
                        if args[0] == "is-enabled" else "active")
    assert summary["schedule"].startswith("ADR0030_OPTION_A (owner-approved 2026-09-24)")
    assert summary["timers"] == {"edgelab-observe.timer": "enabled/active", "edgelab-observe-close.timer": "enabled/active"}
    assert summary["by_phase"]["post_decision_1h"] == {"MISSED": 6}
    assert summary["by_phase"]["close"] == {"PLANNED": 6}
    history = po.market_history(store, f"kalshi:{BRACKETS[0]}")
    missed = [h for h in history if h["collection_status"] == "MISSED"]
    assert {h["phase"] for h in missed} == {"post_decision_1h", "post_decision_6h"}
    assert all(h["miss_reason"] and h["side"] is None and h["bid"] is None for h in missed)


def test_planning_after_the_deadline_is_recorded_as_such(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model, now=datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    t = _target(store, "post_decision_1h")
    assert t["state"] == "MISSED" and t["state_reason"].startswith("PLANNED_AFTER_DEADLINE")


def _closing_routes(clock, *, after_close_status="closed", close_time="2026-09-24T05:00:00Z"):
    def listing(_url):
        status = after_close_status if clock.now >= CLOSE else "active"
        return {"cursor": "", "markets": [dict(m, status=status, close_time=close_time) for m in MARKETS["markets"]]}
    return {"/orderbook": BOOK, LISTING: listing}


def test_close_is_labelled_close_only_with_proof(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 4, 57, 40, tzinfo=UTC))  # pre_close and close are both due
    api = _api(monkeypatch, clock, _closing_routes(clock))
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["requests"] == len(api.calls) == (1 + 6) + (1 + 6 + 1) <= po.MAX_REQUESTS
    close_rows = [r for r in store.price_observations() if r["phase"] == "close"]
    assert len(close_rows) == 12 and {r["close_label"] for r in close_rows} == {"CLOSE"}  # the stored enum
    proof = json.loads(close_rows[0]["close_proof_json"])
    assert proof["confirm_status"] == "closed" and proof["close_time_utc"] == "2026-09-24T05:00:00+00:00"
    received = datetime.fromisoformat(close_rows[0]["observed_at_utc"])
    assert CLOSE - po.CLOSE_PROOF_TOLERANCE <= received < CLOSE
    assert all(r["close_label"] is None for r in store.price_observations() if r["phase"] == "pre_close")
    history = po.market_history(store, f"kalshi:{BRACKETS[0]}")
    closes = [h for h in history if h["phase"] == "close"]
    assert {h["label"] for h in closes} == {PROVEN_CLOSE} and {h["close_tolerance_s"] for h in closes} == {60}
    assert all(h["label"] != "close" for h in history)  # never a bare "close"
    latest = [h for h in history if h["is_latest_pre_close_observation"]]
    assert {h["phase"] for h in latest} == {"close"} and {h["side"] for h in latest} == {"YES", "NO"}


@pytest.mark.parametrize("after_close_status, why", [
    ("active", "still 'active' after close_time"),  # extended or delayed: not proven
])
def test_an_unproven_close_is_the_latest_pre_close_observation(store, tmp_path, monkeypatch, model,
                                                                after_close_status, why):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 4, 59, 0, tzinfo=UTC))
    _api(monkeypatch, clock, _closing_routes(clock, after_close_status=after_close_status))
    po.capture(store, clock=clock, sleep=clock.sleep)
    rows = [r for r in store.price_observations() if r["phase"] == "close"]
    assert rows and {r["close_label"] for r in rows} == {"LATEST_PRE_CLOSE"}
    assert any(why in reason for reason in json.loads(rows[0]["close_proof_json"])["not_close_because"])
    history = po.market_history(store, rows[0]["market_id"])
    assert {h["label"] for h in history if h["phase"] == "close"} == {"latest pre-close observation"}
    assert {h["close_tolerance_s"] for h in history if h["phase"] == "close"} == {None}


def test_slow_close_books_are_labelled_by_when_they_arrived(store, tmp_path, monkeypatch, model):
    """One close book arrives in the last minute (CLOSE), one after close_time (never a pre-close
    quote: NOT_EXECUTABLE, prices dropped), and the rest would start too late to be sent."""
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 4, 59, 0, tzinfo=UTC))  # only the close is due

    class SlowApi(FakeApi):
        latencies = [5.0, 5.0, 25.0]  # listing, first book, second book; then 5 s each

        def __call__(self, url, **kwargs):
            self.latency = self.latencies.pop(0) if self.latencies else 5.0
            return super().__call__(url, **kwargs)

    api = SlowApi(clock, _closing_routes(clock))
    monkeypatch.setattr(po, "fetch_json_result", api)
    po.capture(store, clock=clock, sleep=clock.sleep)
    assert api.count("/orderbook") == 2 and api.count(LISTING) == 2  # the pre-book read and the confirmation
    rows = [r for r in store.price_observations() if r["phase"] == "close"]
    by_status = {}
    for r in rows:
        by_status.setdefault(r["collection_status"], []).append(r)
    closes = by_status["CAPTURED"]
    assert closes and {r["close_label"] for r in closes} == {"CLOSE"}
    assert all(CLOSE - po.CLOSE_PROOF_TOLERANCE <= datetime.fromisoformat(r["observed_at_utc"]) < CLOSE for r in closes)
    late = by_status["NOT_EXECUTABLE"]
    assert late and all(r["miss_reason"].startswith("BOOK_RECEIVED_AT_OR_AFTER_CLOSE") and r["ask"] is None
                        and r["close_label"] is None and r["snapshot_id"] for r in late)
    assert len(by_status["MISSED"]) == 4 and all(r["miss_reason"].startswith("TOO_LATE_FOR_CLOSE")
                                                 for r in by_status["MISSED"])
    assert len({r["target_id"] for r in rows}) == 6


def test_a_moved_close_time_misses_the_old_target(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 4, 50, tzinfo=UTC))
    _api(monkeypatch, clock, _closing_routes(clock, close_time="2026-09-24T06:00:00Z"))
    po.capture(store, clock=clock, sleep=clock.sleep)
    t = _target(store, "pre_close")
    assert t["state"] == "MISSED" and t["state_reason"].startswith("CLOSE_TIME_CHANGED")
    # The next plan re-targets the pre-close and close from the newly observed close time.
    ledger = ShadowLedger.open_readonly(tmp_path / "ledger.sqlite3")
    decisions = po.decisions_from_ledger(ledger, store, since=CLOSED - timedelta(days=7))
    assert {d.close_time_utc for d in decisions} == {CLOSE + timedelta(hours=1)}
    report = po.plan(store, decisions=decisions, now=clock.now)
    assert report["targets_planned"] == 6 * 2
    phases = [r for r in store.price_targets(market_id=f"kalshi:{BRACKETS[0]}") if r["phase"] == "close"]
    assert sorted(r["target_utc"] for r in phases) == ["2026-09-24T04:59:30+00:00", "2026-09-24T05:59:30+00:00"]


def test_a_closed_market_is_not_executable_and_carries_no_price(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 18, 30, tzinfo=UTC))  # settlement_preceding: after the close
    api = _api(monkeypatch, clock, _closing_routes(clock))
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and api.count("/orderbook") == 0 and report["requests"] == 1
    rows = [r for r in store.price_observations() if r["phase"] == "settlement_preceding"]
    assert len(rows) == 6 and {r["collection_status"] for r in rows} == {"NOT_EXECUTABLE"}
    assert all(r["market_status"] == "closed" and r["bid"] is None and r["ask"] is None and r["snapshot_id"]
               for r in rows)


# --------------------------------------------------------------------------- protected windows and locks


@pytest.mark.parametrize("when", [
    datetime(2026, 9, 22, 21, 37, tzinfo=UTC),  # 17:37 ET: a 4-minute run would reach 17:40
    datetime(2026, 9, 22, 22, 0, tzinfo=UTC),  # 18:00 ET: the decision capture
    datetime(2026, 9, 22, 22, 45, tzinfo=UTC),  # 18:45 ET: the shadow run
    datetime(2026, 9, 23, 15, 20, tzinfo=UTC),  # 11:20 ET: the settlement run
    datetime(2026, 12, 15, 22, 45, tzinfo=UTC),  # 17:45 EST
])
def test_capture_never_runs_inside_a_protected_window(store, monkeypatch, when):
    monkeypatch.setattr(po, "fetch_json_result", _no_network)
    runs = len(sqlite3.connect(store.path).execute("SELECT * FROM collection_runs").fetchall())
    clock = Clock(when)
    code, report = po.run_capture(store.path, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["state"] == "DEFERRED_PROTECTED_WINDOW" and report["requests"] == 0
    assert len(sqlite3.connect(store.path).execute("SELECT * FROM collection_runs").fetchall()) == runs


def test_plan_never_runs_inside_a_protected_window(store):
    code, report = po.run_plan(store.path, None, now=datetime(2026, 9, 22, 22, 0, tzinfo=UTC))
    assert (code, report["state"]) == (0, "DEFERRED_PROTECTED_WINDOW")
    runs = _runs(store)
    code, report = po.run_plan(store.path, None, now=CLOSED)
    assert (code, report["state"], report["ledger"]) == (0, "NOTHING_TO_DO", "NOT_GIVEN") and _runs(store) == runs
    missing = store.path.parent / "elsewhere" / "new.sqlite3"
    code, report = po.run_plan(missing, None, now=CLOSED)
    assert report["state"] == "NO_STORE" and not missing.exists() and not missing.parent.exists()


def test_capture_outside_the_windows_proceeds(store):
    assert po.protected_refusal(datetime(2026, 9, 22, 23, 0, tzinfo=UTC)) is None  # 19:00 ET
    assert po.protected_refusal(datetime(2026, 9, 22, 21, 35, tzinfo=UTC)) is None  # 17:35 ET, done by 17:39


def test_a_held_collector_lock_means_nothing_is_done(store, monkeypatch):
    monkeypatch.setattr(po, "fetch_json_result", _no_network)
    monkeypatch.setattr(po, "LOCK_TIMEOUT_S", 0.2)
    clock = Clock(CLOSED)
    with forward.exclusive_lock(store.path.with_name(store.path.name + ".forward.lock")):
        code, report = po.run_capture(store.path, clock=clock, sleep=clock.sleep)
    assert (code, report["state"]) == (0, "LOCK_BUSY")


# --------------------------------------------------------------------------- append-only storage


def test_observations_and_targets_are_append_only(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    with sqlite3.connect(store.path) as conn:
        for sql in ("UPDATE price_observations SET ask = '0.01'", "DELETE FROM price_observations",
                    "UPDATE price_observation_targets SET target_utc = 'x'", "DELETE FROM price_observation_targets"):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(sql)
    captured = next(r for r in store.price_observations() if r["collection_status"] == "CAPTURED")
    store.start_run("late")
    with pytest.raises(sqlite3.IntegrityError, match="final status"):
        store.record_price_observations([dict(captured, run_id="late", attempt_id="another", id=None)])
    t = _target(store, "close")
    assert store.plan_price_target(dict(t, planned_at_utc="2030-01-01T00:00:00+00:00")) is False
    assert _target(store, "close")["planned_at_utc"] == t["planned_at_utc"]  # the original plan is kept


def test_a_close_claim_needs_its_proof(store):
    target = po.custom_target(venue="kalshi", native_market_id="X-1", at=CLOSED)
    target = dict(target, phase="close", target_id="kalshi:X-1|close|t", close_time_utc="2026-09-23T00:00:00+00:00")
    assert store.plan_price_target({**target, "planned_at_utc": CLOSED.isoformat()})
    store.start_run("r")
    sid = store.save_snapshot(run_id="r", source="kalshi", kind="orderbook", entity_id="X-1", url="u", payload={})
    base = {"run_id": "r", "attempt_id": "a", "target_id": target["target_id"], "phase": "close", "venue": "kalshi",
            "market_id": "kalshi:X-1", "native_market_id": "X-1", "event_id": "e", "side": "YES",
            "observed_at_utc": CLOSED.isoformat(), "freshness": "fresh", "snapshot_id": sid, "ask": "0.5",
            "collection_status": "CAPTURED", "recorded_at_utc": CLOSED.isoformat(), "policy_version": "v"}
    with pytest.raises(sqlite3.IntegrityError):  # a captured close row must be labelled
        store.record_price_observations([base])
    with pytest.raises(sqlite3.IntegrityError):  # CLOSE without proof
        store.record_price_observations([dict(base, close_label="CLOSE")])
    with pytest.raises(sqlite3.IntegrityError):  # a miss carries no price
        store.record_price_observations([dict(base, collection_status="MISSED", miss_reason="x", close_label=None)])
    store.record_price_observations([dict(base, close_label="LATEST_PRE_CLOSE")])


# --------------------------------------------------------------------------- Polymarket US and custom targets


def test_a_custom_polymarket_observation(store, monkeypatch):
    clock = Clock(datetime(2026, 10, 1, 15, 0, tzinfo=UTC))
    target = po.custom_target(venue="polymarket_us", native_market_id=PM_SLUG, at=clock.now, note="manual check")
    assert po.plan(store, decisions=[], now=clock.now, custom=[target])["targets_planned"] == 1
    api = _api(monkeypatch, clock, {f"/v1/markets/{PM_SLUG}/book": PM_BOOK})
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["requests"] == 1 and api.count("/book") == 1
    rows = {r["side"]: r for r in store.price_observations(market_id=f"polymarket_us:{PM_SLUG}")}
    assert rows["YES"]["ask"] == "0.56" and rows["YES"]["bid"] == "0.55"
    assert Decimal(rows["NO"]["ask"]) == Decimal("0.45") and rows["YES"]["source_timestamp_utc"] == "2025-01-20T12:30:45.123Z"
    assert json.loads(rows["YES"]["depth_json"])["truncated"] is True  # docs do not promise a complete book
    assert rows["YES"]["close_label"] is None and rows["YES"]["market_status"] == "MARKET_STATE_OPEN"
    snap = store.snapshots_by_id([rows["YES"]["snapshot_id"]])[rows["YES"]["snapshot_id"]]
    assert snap["source"] == "polymarket_us" and snap["kind"] == "book"


def test_a_polymarket_book_that_is_not_open_is_not_executable(store, monkeypatch):
    clock = Clock(datetime(2026, 10, 1, 15, 0, tzinfo=UTC))
    po.plan(store, decisions=[], now=clock.now,
            custom=[po.custom_target(venue="polymarket_us", native_market_id=PM_SLUG, at=clock.now)])
    halted = {"marketData": dict(PM_BOOK["marketData"], state="MARKET_STATE_HALTED")}
    _api(monkeypatch, clock, {"/book": halted})
    po.capture(store, clock=clock, sleep=clock.sleep)
    (row,) = store.price_observations()
    assert row["collection_status"] == "NOT_EXECUTABLE" and row["ask"] is None and "HALTED" in row["miss_reason"]


# --------------------------------------------------------------------------- read-only history for display


def test_market_history_contract(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(CLOSED)
    _api(monkeypatch, clock)
    po.capture(store, clock=clock, sleep=clock.sleep)
    ro = SnapshotStore.open_readonly(store.path)
    history = po.market_history(ro, f"kalshi:{BRACKETS[0]}")
    assert all(set(h) == HISTORY_KEYS for h in history)
    phases = [h["phase"] for h in history]
    assert phases[:2] == ["decision", "decision"] and "recheck" in phases
    planned = [h for h in history if h["collection_status"] == "PLANNED"]
    assert {h["phase"] for h in planned} == {"post_decision_6h", "pre_close", "close", "settlement_preceding"}
    captured = [h for h in history if h["collection_status"] == "CAPTURED"]
    assert all(h["executable"] and isinstance(h["ask"], str) and h["deviation_s"] is not None for h in captured)
    latest = [h for h in history if h["is_latest_pre_close_observation"]]
    assert {h["phase"] for h in latest} == {"post_decision_1h"}  # the latest captured before the close so far
    assert po.market_history(ro, "kalshi:NOPE") == []
    assert [h["target_utc"] for h in history] == sorted(h["target_utc"] for h in history)


# --------------------------------------------------------------------------- CLI


def test_cli_plan_and_status(store, tmp_path, monkeypatch, model, capsys):
    ledger = _ledger(store, tmp_path, monkeypatch, model)
    monkeypatch.setattr(po, "fetch_json_result", _no_network)
    monkeypatch.setattr(po, "_now", lambda: CLOSED)  # deterministic: never inside a protected window
    assert cli.main(["observe", "plan", "--db", str(store.path), "--ledger", str(ledger.path),
                     "--lookback-days", "3650"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "OK" and out["ledger"] == "READ" and out["decisions"] == 6
    monkeypatch.setattr(po, "timer_states", lambda run=None: {t: "UNKNOWN (test)" for t in po.OBSERVE_TIMERS})
    assert cli.main(["observe", "status", "--db", str(store.path), "--market", f"kalshi:{BRACKETS[0]}"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["schedule"].startswith("ADR0030_OPTION_A") and status["market_history"]
    assert set(status["timers"]) == set(po.OBSERVE_TIMERS) and "close_tick_alignment" in status
    assert cli.main(["observe", "plan", "--db", str(store.path), "--custom-venue", "kalshi"]) == 2
    assert cli.main(["observe", "status", "--db", str(tmp_path / "missing.sqlite3")]) == 1
    capsys.readouterr()
    monkeypatch.setattr(po, "_now", lambda: datetime(2026, 9, 23, 2, 0, tzinfo=UTC))  # 22:00 ET: nothing due
    assert cli.main(["observe", "capture", "--db", str(store.path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "NOTHING_DUE" and out["requests"] == 0 and len(out["missed"]) == 6  # the +1 h targets


def test_timer_states_report_systemd_and_never_guess():
    said = {("is-enabled", "edgelab-observe.timer"): "enabled", ("is-active", "edgelab-observe.timer"): "active",
            ("is-enabled", "edgelab-observe-close.timer"): "disabled", ("is-active", "edgelab-observe-close.timer"): "inactive"}
    assert po.timer_states(lambda args: said[tuple(args)]) == {
        "edgelab-observe.timer": "enabled/active", "edgelab-observe-close.timer": "disabled/inactive"}

    def no_systemd(args):
        raise FileNotFoundError("systemctl")

    assert all(v.startswith("UNKNOWN (FileNotFoundError)") for v in po.timer_states(no_systemd).values())


def _close_target(close: datetime, state: str = "PLANNED") -> dict:
    aim = close - po.CLOSE_AIM
    due, deadline = po._window("close", aim, close)
    return {"target_id": f"t-{close.isoformat()}", "phase": "close", "state": state, "close_time_utc": po._iso(close),
            "due_from_utc": po._iso(due), "deadline_utc": po._iso(deadline)}


def test_close_tick_alignment_flags_a_moved_close_before_targets_are_missed():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    ok = po.close_tick_alignment([_close_target(datetime(2026, 9, 25, 5, tzinfo=timezone.utc))], now)
    assert ok["state"] == "ALIGNED" and ok["aligned"] == 1 and not ok["misaligned"]
    # 04:59Z (the old 23:59 ET convention in winter) still contains the 04:57:45Z tick; 03:59Z (the same
    # convention in summer) and an hour-later close (06:00Z) do not.
    assert po.close_tick_alignment([_close_target(datetime(2026, 11, 3, 4, 59, tzinfo=timezone.utc))], now)["state"] == "ALIGNED"
    for close in (datetime(2026, 9, 26, 3, 59, tzinfo=timezone.utc), datetime(2026, 11, 3, 6, tzinfo=timezone.utc)):
        bad = po.close_tick_alignment([_close_target(close)], now)
        assert bad["state"] == "MISALIGNED" and bad["misaligned"][0]["close_time_utc"] == po._iso(close)
    done = po.close_tick_alignment([_close_target(datetime(2026, 9, 25, 5, tzinfo=timezone.utc), "CAPTURED")], now)
    assert done["state"] == "NO_OPEN_CLOSE_TARGET"


def test_close_tick_alignment_allows_start_up_time_at_the_early_edge():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    edge = lambda close: po.close_tick_alignment([_close_target(close)], now)["state"]
    assert edge(datetime(2026, 9, 25, 4, 58, tzinfo=timezone.utc)) == "ALIGNED"
    assert edge(datetime(2026, 9, 25, 4, 57, 57, tzinfo=timezone.utc)) == "MISALIGNED"  # the tick leaves < 5 s
    assert edge(datetime(2026, 9, 25, 5, 0, 15, tzinfo=timezone.utc)) == "ALIGNED"
    assert edge(datetime(2026, 9, 25, 5, 0, 16, tzinfo=timezone.utc)) == "MISALIGNED"


def test_other_groups_never_run_into_a_pending_close(store, tmp_path, monkeypatch, model):
    _planned(store, tmp_path, monkeypatch, model)
    clock = Clock(datetime(2026, 9, 24, 4, 57, 40, tzinfo=UTC))  # pre_close and close are both due
    monkeypatch.setattr(po, "CLOSE_GUARD", timedelta(minutes=2, seconds=30))  # no budget left before the close aim
    api = _api(monkeypatch, clock, _closing_routes(clock))
    code, report = po.capture(store, clock=clock, sleep=clock.sleep)
    assert code == 0 and report["requests"] == len(api.calls) == 1 + 6 + 1  # the close group only
    pre_close = {t["target_id"] for t in store.price_targets() if t["phase"] == "pre_close"}
    assert pre_close and pre_close <= set(report["deferred"])
    close_rows = [r for r in store.price_observations() if r["phase"] == "close"]
    assert len(close_rows) == 12 and {r["close_label"] for r in close_rows} == {"CLOSE"}


def test_a_failure_before_a_protected_window_is_final_not_retrying():
    # 11:05 ET tick: the 11:20 tick is deferred by the 11:15 settlement window, so a target due until
    # 11:30 has no retry left; the same target failing at 10:35 ET would still be retried at 10:50.
    deadline = datetime(2026, 9, 24, 15, 30, tzinfo=UTC)  # 11:30 EDT
    assert not po._retry_tick_before(deadline, datetime(2026, 9, 24, 15, 5, 40, tzinfo=UTC))
    assert po._retry_tick_before(deadline, datetime(2026, 9, 24, 14, 35, 40, tzinfo=UTC))
    # 17:35 ET: every tick until 18:50 is deferred by the capture window.
    assert not po._retry_tick_before(datetime(2026, 9, 24, 22, 45, tzinfo=UTC), datetime(2026, 9, 24, 21, 35, 40, tzinfo=UTC))
    assert po._retry_tick_before(datetime(2026, 9, 24, 23, 10, tzinfo=UTC), datetime(2026, 9, 24, 22, 50, 40, tzinfo=UTC))
