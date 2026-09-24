"""Sizing v2 counterfactual runner: fixes from the independent review of PR #64 (deterministic)."""

from __future__ import annotations

import copy
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest

from edge_lab import cli
from edge_lab import exp001_shadow as shadow
from edge_lab import sizing_counterfactual as cf
from edge_lab import sizing_eval
from edge_lab import sizing_v2 as sv2
from edge_lab.freshness import parse_utc
from edge_lab.kalshi import SETTLEMENT_SOURCE
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore
from test_forward import MARKETS
from test_sizing_counterfactual import CFG, T0, build_ledger, decision, events, fill, iso, run, the_run


@pytest.fixture(autouse=True)
def _fresh_panel_cache():
    cf.clear_panel_cache()
    yield
    cf.clear_panel_cache()


# --------------------------------------------------------------------------- BLOCKER: one-pass settlement index


def _reference_first_known(store, natives, cutoff):
    """The previous construction: rebuild the canonical index at every distinct capture time."""
    times = sorted({t for kind in shadow.SETTLEMENT_KINDS
                    for r in store.snapshots_of_kind(source=SETTLEMENT_SOURCE.legacy_name, kind=kind)
                    if (t := parse_utc(r["fetched_at_utc"])) is not None and t <= cutoff})
    found = {}
    for t in times:
        index = shadow.settlement_index(store, known_by=t)
        problems = shadow.event_settlement_problems(index)
        for native in sorted(set(natives) - set(found)):
            entry = index.get(native)
            if entry is None or len(entry["variants"]) > 1:
                continue
            event = entry["market"].get("event_ticker")
            if not isinstance(event, str) or not event or problems.get(event):
                continue
            outcome, _ = shadow.official_outcome(entry["market"])
            if outcome is not None:
                found[native] = (t, outcome, entry["snapshot_id"])
    return found


def _settlement_store(tmp_path):
    """Captures over time: partial pages, a late page, a same-instant pair, a contradicted
    market, and a second event that is incoherent (two YES) until a later capture fixes it."""
    from edge_lab import settlement

    store = SnapshotStore(tmp_path / "settle.sqlite3")
    store.start_run("s")
    base = [dict(m, status="settled", expiration_value="67",
                 result=settlement.resolve(m, Decimal(67)).outcome.value) for m in MARKETS["markets"]]
    other = []
    for m in base:
        o = dict(m, ticker=m["ticker"] + "-X", event_ticker="KXHIGHNY-OTHER")
        other.append(o)

    def save(markets, at, kind="settled_markets"):
        store.save_snapshot(run_id="s", source=SETTLEMENT_SOURCE.legacy_name, kind=kind, entity_id="KXHIGHNY",
                            url="u", payload={"markets": markets}, fetched_at_utc=iso(at))

    two_yes = [dict(o, result="yes") if i < 2 else o for i, o in enumerate(other)]
    save(base[:2], T0)
    save(two_yes, T0 + timedelta(hours=1))
    save(base[2:4], T0 + timedelta(hours=2))
    save(base[4:], T0 + timedelta(hours=2), kind="historical_markets")  # the same instant, another kind
    save(other, T0 + timedelta(hours=3))  # fixes the latest entries; the two-YES variants stay recorded
    flipped = dict(base[0], result="no" if base[0]["result"] == "yes" else "yes")
    save([flipped], T0 + timedelta(hours=5))  # contradicts an outcome already known
    store.finish_run("s", status="succeeded")
    natives = [m["ticker"] for m in base + other] + ["KXHIGHNY-NEVER"]
    return store, natives


@pytest.mark.parametrize("hours", [0, 1, 2, 3, 4, 5, 48])
def test_one_pass_settlement_index_equals_the_per_time_construction(tmp_path, hours):
    store, natives = _settlement_store(tmp_path)
    cutoff = T0 + timedelta(hours=hours)
    first, final, problems = cf.settlement_first_known(cf._settlement_rows(store), natives, cutoff)
    assert {k: (t, o, e["snapshot_id"]) for k, (t, e, o, _) in first.items()} == \
        _reference_first_known(store, natives, cutoff)
    canonical = shadow.settlement_index(store, known_by=cutoff)
    assert {k: (v["snapshot_id"], v["variants"]) for k, v in final.items()} == \
        {k: (v["snapshot_id"], v["variants"]) for k, v in canonical.items()}
    assert problems == shadow.event_settlement_problems(canonical)
    if hours >= 3:
        assert first and "KXHIGHNY-NEVER" not in first


def test_the_outcome_lookup_never_rebuilds_the_index_per_capture(tmp_path, monkeypatch):
    store, natives = _settlement_store(tmp_path)

    def forbidden(*a, **k):
        raise AssertionError("settlement_index must not be rebuilt per capture time")

    monkeypatch.setattr(shadow, "settlement_index", forbidden)
    outcomes, _ = cf._outcomes(cf._settlement_rows(store), [f"kalshi:{n}" for n in natives], {}, T0 + timedelta(days=1))
    known = [o for o in outcomes.values() if o.outcome]
    assert known and any("CONTRADICTED_LATER" in o.detail for o in known)


def test_many_settlement_captures_are_linear(tmp_path):
    """150 captures (about 25 days of production) resolve in one pass (1,000 take about 1 s)."""
    from edge_lab import settlement

    store = SnapshotStore(tmp_path / "many.sqlite3")
    store.start_run("s")
    base = [dict(m, status="settled", expiration_value="67", result=settlement.resolve(m, Decimal(67)).outcome.value)
            for m in MARKETS["markets"]]
    natives = []
    for day in range(150):
        markets = [dict(m, ticker=f"{m['ticker']}-{day}", event_ticker=f"EV-{day}") for m in base]
        natives += [m["ticker"] for m in markets]
        store.save_snapshot(run_id="s", source=SETTLEMENT_SOURCE.legacy_name, kind="settled_markets",
                            entity_id="KXHIGHNY", url="u", payload={"markets": markets},
                            fetched_at_utc=iso(T0 + timedelta(hours=4 * day)))
    store.finish_run("s", status="succeeded")
    first, _, _ = cf.settlement_first_known(cf._settlement_rows(store), natives + ["NEVER"], T0 + timedelta(days=400))
    assert len(first) == len(natives)


# --------------------------------------------------------------------------- 2: no fill facts past the clock


def test_fill_facts_are_pending_until_known_by_the_replay_clock(tmp_path):
    d1 = decision(1, T0)
    led = build_ledger(tmp_path / "l.sqlite3", [d1], [fill(d1, known=T0 + timedelta(minutes=10))])
    before = events(run(None, led, cutoff=T0 + timedelta(minutes=5)))["dec-1"]
    assert before["contracts"] > 0
    assert (before["fill_status"], before["fill_reason"], before["fill_known_utc"], before["fill_basis"]) == (
        "PENDING", None, None, None)
    after = events(run(None, led, cutoff=T0 + timedelta(hours=1)))["dec-1"]
    assert (after["fill_status"], after["fill_known_utc"]) == ("FILLED", iso(T0 + timedelta(minutes=10)))


def test_a_confirmation_received_after_the_cutoff_is_never_read(tmp_path):
    store = SnapshotStore(tmp_path / "db.sqlite3")
    store.start_run("r")
    sid = store.save_snapshot(run_id="r", source="kalshi", kind="orderbook", entity_id="KXHIGHNY-26SEP26-B67.5",
                              url="u", payload={"orderbook_fp": {"yes_dollars": [["0.35", "10"]],
                                                                 "no_dollars": [["0.60", "15"]]}},
                              fetched_at_utc=iso(T0 + timedelta(minutes=10)))
    store.finish_run("r", status="succeeded")
    d1 = decision(1, T0, size="10")
    led = build_ledger(tmp_path / "l.sqlite3", [d1], [fill(d1, quantity=1, confirmation=f"snapshot:{sid}")])
    for cut, expected in ((T0 + timedelta(minutes=5), "CONFIRMATION_AFTER_CUTOFF"),
                          (T0 + timedelta(hours=1), "RECORDED_FILL_CONFIRMATION")):
        inputs = cf.load_inputs(store, led, cutoff=T0 + timedelta(hours=1))
        inputs.cutoff = cut
        record = inputs.decisions[0]  # carries the recorded fill (known by the load cutoff)
        assert cf._confirmation(inputs, record)[1] == expected


def test_recheck_read_errors_are_recorded_not_swallowed(tmp_path, monkeypatch):
    from edge_lab import forward

    def broken(*a, **k):
        raise sqlite3.OperationalError("no such table: forward_captures")

    monkeypatch.setattr(forward, "day_status", broken)
    store = SnapshotStore(tmp_path / "db.sqlite3")
    dec = decision(1, T0, p="0.46", cons="0.40", qualify=False, reasons=("NO_EDGE",))
    bundle = run(store, build_ledger(tmp_path / "l.sqlite3", [dec]), cutoff=T0 + timedelta(hours=1))
    assert "OperationalError" in bundle["provenance"]["recheck_errors"]["2026-09-26"]
    assert events(bundle)["dec-1"]["fill_basis"].startswith("RECHECK_UNAVAILABLE")


def test_decisions_after_the_fee_recheck_date_fail_closed(tmp_path):
    from datetime import datetime, timezone

    late = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)  # after recheck_by 2026-10-23T13:39:48Z
    ev = events(run(None, build_ledger(tmp_path / "l.sqlite3", [decision(1, late)])))["dec-1"]
    assert ev["zero_size_reason"] == "UNSUPPORTED:FEE_UNVERIFIED"


# --------------------------------------------------------------------------- 3: rolling drawdown window


def test_worst_rolling_drawdown_respects_the_168h_window(tmp_path):
    d1 = decision(1, T0)
    d2 = decision(2, T0 + timedelta(days=10), native="KXHIGHNY-26OCT06-B67.5", event="ev2", cluster="cl2")
    led = build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)],
                       [(d1, "NO", T0 + timedelta(hours=11), T0 + timedelta(hours=12)),
                        (d2, "NO", T0 + timedelta(days=10, hours=11), T0 + timedelta(days=10, hours=12))])
    r = the_run(run(None, led))
    assert r["max_drawdown"] == "85.38" and r["metrics"]["worst_rolling_drawdown"] == "42.69"
    assert "event-averaged" in r["metrics"]["avg_drawdown_basis"]


# --------------------------------------------------------------------------- 4: H's joint component is inert


def test_h_equals_robust_half_kelly_with_drawdown_constraint_here_and_says_so(tmp_path):
    decs = [decision(1, T0), decision(2, T0, native="KXHIGHNY-26SEP26-B69.5", p="0.70", cons="0.50", price="0.45"),
            decision(3, T0, side="NO", p="0.40", cons="0.35", price="0.62")]
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", decs, [fill(d) for d in decs]),
                 policies=(("G*", sizing_eval.G_ROBUST), ("H", sv2.POLICY_CANDIDATE)))
    skip = {"policy_letter", "policy_id", "run_id", "explanation", "recommendation_output_hash"}
    g, h = (sorted(r["events"], key=lambda e: e["decision_id"]) for r in bundle["runs"])
    assert [{k: v for k, v in e.items() if k not in skip} for e in g] == \
        [{k: v for k, v in e.items() if k not in skip} for e in h]
    assert any(e["contracts"] > 0 for e in h)
    for r in bundle["runs"]:
        assert any("INERT" in line for line in r["limitations"])


# --------------------------------------------------------------------------- 5: shared panel bundle


def test_panel_bundle_is_computed_once_and_rekeyed_when_the_ledger_changes(tmp_path):
    path = tmp_path / "l.sqlite3"
    d1 = decision(1, T0)
    led = build_ledger(path, [d1])
    a = cf.build_panel_bundle(None, led, config=CFG)
    assert a["available"] and cf.build_panel_bundle(None, led, config=CFG) is a  # memoized
    same = cf.panel_for_market(None, led, "kalshi:KXHIGHNY-26SEP26-B67.5", config=CFG)
    assert same == cf.panel_for_market_from_bundle(a, "kalshi:KXHIGHNY-26SEP26-B67.5")
    same["sides"][0]["primary"]["caps"]["position"] = "tampered"  # callers get copies, never the bundle
    assert cf.panel_for_market_from_bundle(a, "kalshi:KXHIGHNY-26SEP26-B67.5")["sides"][0]["primary"]["caps"][
        "position"] != "tampered"
    ShadowLedger(path).record_decision("test-shadow", decision(2, T0 + timedelta(days=1),
                                                               native="KXHIGHNY-26SEP27-B67.5"))
    b = cf.build_panel_bundle(None, ShadowLedger.open_readonly(path), config=CFG)
    assert b is not a and b["cache_key"] != a["cache_key"]
    assert cf.panel_for_market_from_bundle(b, "kalshi:KXHIGHNY-26SEP27-B67.5")["available"]


def test_panel_never_raises(tmp_path):
    led = build_ledger(tmp_path / "l.sqlite3", [decision(1, T0)])
    assert cf.panel_for_market(None, led, "kalshi:X", policies=())["unavailable_reason"] == cf.UNAVAILABLE_NO_POLICY

    class Locked:
        def accounts(self):
            raise sqlite3.OperationalError("database is locked")

    panel = cf.panel_for_market(None, Locked(), "kalshi:X")
    assert panel["unavailable_reason"] == cf.UNAVAILABLE_LEDGER and "locked" in panel["unavailable_detail"]
    assert cf.panel_for_market(None, led, "kalshi:X", as_of="not a time")["unavailable_reason"] == \
        cf.UNAVAILABLE_EVIDENCE


# --------------------------------------------------------------------------- slot dedupe (Lane B)


def _two_accounts(path, operational, research):
    led = ShadowLedger(path)
    for acct, decs in ((shadow.ACCOUNT_ID, operational), (shadow.RESEARCH_ACCOUNT_ID, research)):
        led.open_account(acct, starting_bankroll=Decimal("1000"), strategy="t", opened_at_utc="2026-09-20T00:00:00+00:00",
                         sizing_policy_id="x", fill_policy_id="latency-confirmed-v1", fee_schedule_id="kalshi")
        for d in decs:
            led.record_decision(acct, d)
    return ShadowLedger.open_readonly(path)


def test_one_slot_decided_by_two_accounts_under_different_ids_is_one_row(tmp_path):
    op = decision(1, T0)
    rs = copy.deepcopy(op)
    rs.update(decision_id="dec-research-1", opportunity_id="opp-research-1")
    rs.pop("starter_policy")
    led = _two_accounts(tmp_path / "l.sqlite3", [op], [rs])
    ev = events(run(None, led))
    assert list(ev) == ["dec-1"]  # the operational record is kept
    assert ev["dec-1"]["recorded_in_accounts"] == sorted([shadow.ACCOUNT_ID, shadow.RESEARCH_ACCOUNT_ID])
    panel = cf.panel_for_market(None, led, "kalshi:KXHIGHNY-26SEP26-B67.5", config=CFG)
    assert [s["side"] for s in panel["sides"]] == ["YES"]
    assert panel["sides"][0]["merged_decision_ids"] == ["dec-research-1"]


def test_one_slot_with_materially_different_content_fails_closed(tmp_path):
    op = decision(1, T0)
    rs = decision(9, T0, p="0.70")  # same slot, a different model probability
    led = _two_accounts(tmp_path / "l.sqlite3", [op], [rs])
    ev = events(run(None, led))
    assert list(ev) == ["dec-1"]
    assert ev["dec-1"]["zero_size_reason"] == "UNSUPPORTED:DECISION_RECORDS_DISAGREE"
    panel = cf.panel_for_market(None, led, "kalshi:KXHIGHNY-26SEP26-B67.5", config=CFG)
    assert panel["unavailable_reason"] == cf.UNAVAILABLE_EVIDENCE


# --------------------------------------------------------------------------- 6: output path


def test_cli_refuses_an_existing_output_and_input_sidecars(tmp_path):
    d1 = decision(1, T0)
    lpath, dpath = tmp_path / "ledger.sqlite3", tmp_path / "evidence.sqlite3"
    build_ledger(lpath, [d1])
    SnapshotStore(dpath)
    out = tmp_path / "run.json"
    args = ["sizing", "counterfactual", "--db", str(dpath), "--ledger", str(lpath)]
    assert cli.main(args + ["--out", str(out)]) == 0
    first = out.read_bytes()
    assert cli.main(args + ["--out", str(out)]) == 2  # never replaced silently
    assert out.read_bytes() == first
    assert cli.main(args + ["--out", str(out), "--overwrite"]) == 0
    for sidecar in (f"{dpath}-wal", f"{dpath}-shm", f"{dpath}-journal", f"{lpath}-journal", f"{lpath}-wal"):
        assert cli.main(args + ["--out", sidecar, "--overwrite"]) == 2, sidecar
