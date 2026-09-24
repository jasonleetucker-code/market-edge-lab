"""Sizing v2 counterfactual runner: deterministic tests (no network, no randomness)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import pytest

from edge_lab import cli
from edge_lab import sizing_counterfactual as cf
from edge_lab import sizing_v2 as sv2
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from edge_lab.risk import RiskPolicy
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.starter_policy import StarterVerdict
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
T0 = datetime(2026, 9, 25, 22, 0, tzinfo=UTC)  # after the KXHIGHNY fee verification record (2026-09-23)
ACCT = "test-shadow"
RISK = RiskPolicy("test-cf-risk-v1", reserve_floor=Decimal("100"), max_position_risk=Decimal("50"),
                  max_event_risk=Decimal("100"), max_cluster_risk=Decimal("100"), max_portfolio_risk=Decimal("500"),
                  daily_loss_limit=Decimal("200"), weekly_loss_limit=Decimal("400"), max_drawdown=Decimal("500"))
CFG = cf.CounterfactualConfig(config_id="test-cf-v1", starting_bankroll=Decimal("1000"), risk_policy=RISK)
C = (("C", sv2.POLICY_C),)
ROOT = Path(__file__).resolve().parents[1]


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def verdict(at: datetime, eligible: bool = True) -> dict:
    return StarterVerdict("STARTER_MAX_7D_V1", eligible, () if eligible else ("HORIZON_OVER_7D",), iso(at),
                          iso(at + timedelta(days=1)), iso(at + timedelta(days=2)), iso(at + timedelta(days=2)),
                          None, None, None, "48.0000", 168, (), timing_source="decision_capture:1").to_dict()


def decision(n: int, at: datetime, *, native: str = "KXHIGHNY-26SEP26-B67.5", side: str = "YES", p: str | None = "0.60",
             cons: str | None = "0.55", price: str | None = "0.40", size: str | None = "100", qualify: bool = True,
             reasons: tuple[str, ...] = (), received: datetime | None = None, fresh: bool = True,
             starter: bool = True, day: str = "VALID", cluster: str = "cl", event: str = "ev", **extra) -> dict:
    opp = {"model_probability": p, "conservative_probability": cons, "executable_price": price,
           "displayed_size": size, "quote_received_at_utc": iso(received or at - timedelta(minutes=1)),
           "quote_evidence_id": None, "model_freshness": "fresh" if fresh else "stale", "outcome": native,
           "reasons": list(reasons)}
    payload = {"decision_id": f"dec-{n}", "slot": f"2026-09-26|kalshi:{native}|{side}", "opportunity_id": f"opp-{n}",
               "as_of_utc": iso(at), "qualification": "QUALIFY" if qualify else "REJECT",
               "reason": reasons[0] if reasons else "QUALIFY", "reasons": list(reasons), "model_version": "test v1",
               "event_id": event, "market_id": f"kalshi:{native}", "side": side, "outcome_cluster": cluster,
               "opportunity": opp, "stage_b_day_status": day}
    if starter:
        payload["starter_policy"] = verdict(at)
    payload.update(extra)
    return payload


def fill(dec: dict, *, quantity: int = 1000, known: datetime | None = None, confirmation: str | None = None) -> dict:
    price = Decimal(dec["opportunity"]["executable_price"])
    cost = KALSHI_QUADRATIC_TAKER_V1.taker_buy(quantity, price)
    return {"fill_id": f"fill-{dec['decision_id']}", "decision_id": dec["decision_id"], "venue": "kalshi",
            "market_id": dec["market_id"], "event_id": dec["event_id"], "outcome_cluster": dec["outcome_cluster"],
            "side": dec["side"], "filled_at_utc": iso(known or datetime.fromisoformat(dec["as_of_utc"])
                                                       + timedelta(minutes=10)),
            "status": "FILLED", "reason": "FILLED", "quantity": quantity, "price": str(price),
            "fee": str(cost.fee), "total_cost": str(cost.total_cost), "confirmation_evidence_id": confirmation,
            "expected_settlement_utc": iso(datetime.fromisoformat(dec["as_of_utc"]) + timedelta(days=2))}


def build_ledger(path: Path, decisions: list[dict], fills: list[dict] = (), settlements: list[tuple] = ()) -> ShadowLedger:
    """`settlements`: (decision, outcome, settled_at, known_at)."""
    led = ShadowLedger(path)
    led.open_account(ACCT, starting_bankroll=Decimal("100000"), strategy="test", opened_at_utc="2026-09-20T00:00:00+00:00",
                     sizing_policy_id="x", fill_policy_id="latency-confirmed-v1", fee_schedule_id="kalshi")
    for d in decisions:
        led.record_decision(ACCT, d)
    for f in sorted(fills, key=lambda f: f["filled_at_utc"]):
        led.record_fill(ACCT, f)
    for dec, outcome, settled, known in settlements:
        led.record_settlement(ACCT, fill_id=f"fill-{dec['decision_id']}", outcome=outcome, settled_at_utc=iso(settled),
                              evidence={"evidence_available_utc": iso(known)})
    return ShadowLedger.open_readonly(path)


def run(store, ledger, policies=C, config=CFG, **kw):
    return cf.run_counterfactual(store, ledger, config=config, policies=policies, **kw)


def events(bundle, letter="C"):
    return {e["decision_id"]: e for r in bundle["runs"] if r["policy_letter"] == letter for e in r["events"]}


def the_run(bundle, letter="C"):
    return next(r for r in bundle["runs"] if r["policy_letter"] == letter)


# --------------------------------------------------------------------------- leakage and isolation


@pytest.mark.parametrize("known_after_second", [True, False])
def test_a_settlement_known_after_a_decision_never_reaches_its_bankroll(tmp_path, known_after_second):
    d1 = decision(1, T0, native="KXHIGHNY-26SEP26-B67.5")
    d2 = decision(2, T0 + timedelta(days=1), native="KXHIGHNY-26SEP27-B67.5", event="ev2", cluster="cl2")
    known = T0 + (timedelta(days=2) if known_after_second else timedelta(hours=12))
    led = build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)],
                       [(d1, "NO", T0 + timedelta(hours=11), known)])
    ev = events(run(None, led))
    first, second = ev["dec-1"], ev["dec-2"]
    cost1 = Decimal(first["recommended_size"])
    assert first["contracts"] > 0 and first["fill_status"] == "FILLED" and first["later_outcome"] == "NO"
    assert first["hypothetical_net_pnl"] == str(-cost1)
    assert Decimal(second["cash_before"]) == Decimal("1000") - cost1  # the reservation is visible either way
    if known_after_second:  # the loss was learned later: the second decision still sees cost-basis equity 1000
        assert second["bankroll_before"] == "1000.00"
        assert first["settlement_known_utc"] > second["decision_time"]
    else:
        assert Decimal(second["bankroll_before"]) == Decimal("1000") - cost1


def test_policies_are_isolated_and_bankrolls_evolve_independently(tmp_path):
    d1 = decision(1, T0)
    d2 = decision(2, T0 + timedelta(days=1), native="KXHIGHNY-26SEP27-B67.5", event="ev2", cluster="cl2")
    led = build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)],
                       [(d1, "YES", T0 + timedelta(hours=11), T0 + timedelta(hours=12))])
    alone = run(None, led, policies=C)
    together = run(None, led, policies=(("A", sv2.POLICY_A), ("C", sv2.POLICY_C), ("E", sv2.POLICY_E)))
    assert the_run(alone) == the_run(together)  # another policy in the run changes nothing for C
    a, c, e = (the_run(together, x) for x in "ACE")
    assert len({a["ending_bankroll"], c["ending_bankroll"], e["ending_bankroll"]}) == 3
    for r in (a, c, e):  # each bankroll is the policy's own: start + its own realized P&L
        assert Decimal(r["ending_bankroll"]) == Decimal("1000") + Decimal(r["net_pnl"])
        second = next(x for x in r["events"] if x["decision_id"] == "dec-2")
        first = next(x for x in r["events"] if x["decision_id"] == "dec-1")
        assert Decimal(second["bankroll_before"]) == Decimal("1000") + Decimal(first["hypothetical_net_pnl"])


def test_the_run_is_deterministic_and_ids_are_stable(tmp_path):
    d1 = decision(1, T0)
    led = build_ledger(tmp_path / "l.sqlite3", [d1], [fill(d1)])
    a = cf.canonical_json(run(None, led, policies=cf.POLICY_SET))
    b = cf.canonical_json(run(None, led, policies=cf.POLICY_SET))
    assert a == b
    bundle = json.loads(a)
    assert len({r["run_id"] for r in bundle["runs"]}) == 8
    assert "appended_at" not in a and "generated_at" not in a  # no wall clock in the compared payload
    assert set(bundle["provenance"]["code_sha256"]) >= {"sizing_v2.py", "sizing_counterfactual.py"}


# --------------------------------------------------------------------------- rejected, fees, fills


def test_rejected_opportunities_are_kept_with_exact_zero_size_reasons(tmp_path):
    decs = [
        decision(1, T0, p="0.30", cons="0.25", price="0.40", qualify=False, reasons=("NO_EDGE",)),
        decision(2, T0, native="KXHIGHNY-26SEP26-B69.5", price=None, size=None, qualify=False,
                 reasons=("BOOK_MISSING",)),
        decision(3, T0, native="KXHIGHNY-26SEP26-B71.5", p=None, cons=None, qualify=False,
                 reasons=("MODEL_UNAVAILABLE",)),
        decision(4, T0, native="KXHIGHNY-26SEP26-B73.5", qualify=False, reasons=("RULES_UNRESOLVED",)),
        decision(5, T0, native="KXHIGHNY-26SEP26-B75.5", qualify=False, reasons=("EVIDENCE_INCOMPLETE",),
                 day="INVALID"),
        decision(6, T0, native="KXHIGHNY-26SEP26-T77", qualify=False, reasons=("PAYOFF_UNSUPPORTED",)),
    ]
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", decs), policies=cf.POLICY_SET)
    for r in bundle["runs"]:
        assert r["decision_count"] == 6 and r["sized_count"] == 0
        ev = {e["decision_id"]: e for e in r["events"]}
        assert all(e["recorded_qualification"] == "REJECT" and e["contracts"] == 0 for e in ev.values())
        assert ev["dec-1"]["zero_size_reason"] == "ZERO_EDGE:NO_EDGE"
        assert ev["dec-2"]["zero_size_reason"] == "STALE_DATA:BOOK_MISSING"
        assert ev["dec-3"]["zero_size_reason"] == "STALE_DATA:MODEL_MISSING"
        assert ev["dec-4"]["zero_size_reason"] == "UNSUPPORTED:RULES_UNRESOLVED"
        assert ev["dec-5"]["zero_size_reason"] == "STALE_DATA:EVIDENCE_INCOMPLETE"
        assert ev["dec-5"]["verdict_source"] == "runner"
        assert ev["dec-6"]["zero_size_reason"] == "UNSUPPORTED:PAYOFF_UNSUPPORTED"
        assert sum(r["metrics"]["zero_size_reasons"].values()) == 6
        assert r["metrics"]["zero_size_frequency"] == "1.0000000000"


def test_a_rejected_decision_a_policy_would_trade_has_no_execution_evidence_without_the_db(tmp_path):
    # Rejected by the frozen 0.05 threshold, but nominal Kelly (C) sees a positive net edge.
    dec = decision(1, T0, p="0.46", cons="0.40", price="0.40", qualify=False, reasons=("NO_EDGE",))
    led = build_ledger(tmp_path / "l.sqlite3", [dec])
    # At the default cutoff (the decision itself) the latency window has not closed: still reserved.
    bundle = run(None, led)
    assert events(bundle)["dec-1"]["position_status"] == "RESERVED"
    assert the_run(bundle)["metrics"]["unresolved_reservations_at_cutoff"] == 1
    ev = events(run(None, led, cutoff=T0 + timedelta(hours=1)))["dec-1"]
    assert ev["would_trade"] and ev["contracts"] > 0
    assert ev["fill_status"] == "NO_FILL" and ev["fill_reason"] == "CONFIRMATION_EVIDENCE_UNAVAILABLE"
    assert ev["hypothetical_net_pnl"] is None and ev["position_status"] == "RELEASED"
    assert ev["bankroll_after_utc"] == iso(T0 + timedelta(minutes=15))


def test_fees_come_from_the_engine_routing_and_net_pnl_includes_them(tmp_path):
    d1 = decision(1, T0)
    led = build_ledger(tmp_path / "l.sqlite3", [d1], [fill(d1)],
                       [(d1, "YES", T0 + timedelta(hours=11), T0 + timedelta(hours=12))])
    ev = events(run(None, led))["dec-1"]
    n = ev["contracts"]
    schedule, state, allowance, refused = sv2.fee_basis("kalshi", "KXHIGHNY-26SEP26-B67.5", iso(T0))
    assert refused is None
    quote = schedule.taker_buy(n, Decimal("0.40"))
    expected_total = (quote.total_cost + allowance * n).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    assert Decimal(ev["recommended_size"]) == expected_total
    assert Decimal(ev["estimated_fee"]) == (quote.fee + allowance * n).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    assert Decimal(ev["hypothetical_net_pnl"]) == Decimal(n) - expected_total
    r = the_run(run(None, led))
    assert r["metrics"]["fees_paid"] == ev["estimated_fee"] and r["turnover"] == ev["recommended_size"]


@pytest.mark.parametrize("displayed,filled", [("10", True), ("100", False)])
def test_confirmation_from_the_evidence_db_uses_the_canonical_fill_model(tmp_path, displayed, filled):
    store = SnapshotStore(tmp_path / "db.sqlite3")
    store.start_run("r")
    # YES ask 0.40 persists at the re-check with 15 contracts (YES ask = 1 - NO bid).
    sid = store.save_snapshot(run_id="r", source="kalshi", kind="orderbook", entity_id="KXHIGHNY-26SEP26-B67.5",
                              url="u", payload={"orderbook_fp": {"yes_dollars": [["0.35", "10"]],
                                                                 "no_dollars": [["0.60", "15"]]}},
                              fetched_at_utc=iso(T0 + timedelta(minutes=10)))
    store.finish_run("r", status="succeeded")
    dec = decision(1, T0, size=displayed)
    led = build_ledger(tmp_path / "l.sqlite3", [dec], [fill(dec, quantity=1, confirmation=f"snapshot:{sid}")])
    ev = events(run(store, led))["dec-1"]
    assert ev["fill_basis"] == "RECORDED_FILL_CONFIRMATION" and ev["contracts"] == int(displayed)
    if filled:  # 10 contracts still offered at <= the entry price at the re-check
        assert (ev["fill_status"], ev["position_status"]) == ("FILLED", "OPEN")
    else:  # the re-check displayed 15 contracts, fewer than the counterfactual 100
        assert (ev["fill_status"], ev["fill_reason"]) == ("NO_FILL", "CONFIRMATION_INSUFFICIENT_SIZE")
    assert ev["fill_known_utc"] == iso(T0 + timedelta(minutes=10))


def test_an_invalid_stage_b_day_never_fills(tmp_path):
    dec = decision(1, T0, day="INVALID")
    ev = events(run(None, build_ledger(tmp_path / "l.sqlite3", [dec])))["dec-1"]
    assert ev["contracts"] > 0 and (ev["fill_status"], ev["fill_reason"]) == ("NO_FILL", "STAGE_B_DAY_INVALID")


# --------------------------------------------------------------------------- settlement, drawdown, capital


def test_settled_and_unsettled_positions(tmp_path):
    d1 = decision(1, T0)
    d2 = decision(2, T0, native="KXHIGHNY-26SEP26-B69.5")
    led = build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)],
                       [(d1, "YES", T0 + timedelta(hours=11), T0 + timedelta(hours=12))])
    r = the_run(run(None, led))
    ev = {e["decision_id"]: e for e in r["events"]}
    assert ev["dec-1"]["position_status"] == "SETTLED" and ev["dec-1"]["hypothetical_net_pnl"] is not None
    assert ev["dec-2"]["position_status"] == "OPEN" and ev["dec-2"]["hypothetical_net_pnl"] is None
    assert ev["dec-2"]["later_outcome"] is None
    assert r["settled_count"] == 1 and r["fill_count"] == 2 and r["metrics"]["open_positions_at_cutoff"] == 1
    assert Decimal(r["metrics"]["committed_at_cutoff"]) == Decimal(ev["dec-2"]["recommended_size"])
    assert r["capital_lock"]["open_cost_at_cutoff"] == ev["dec-2"]["recommended_size"]


@pytest.mark.parametrize("outcome", ["YES", "NO"])
def test_drawdown_and_capital_release(tmp_path, outcome):
    d1 = decision(1, T0)
    d2 = decision(2, T0 + timedelta(days=1), native="KXHIGHNY-26SEP27-B67.5", event="ev2", cluster="cl2")
    led = build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)],
                       [(d1, outcome, T0 + timedelta(hours=11), T0 + timedelta(hours=12))])
    r = the_run(run(None, led))
    ev = {e["decision_id"]: e for e in r["events"]}
    cost, n = Decimal(ev["dec-1"]["recommended_size"]), ev["dec-1"]["contracts"]
    payout = Decimal(n) if outcome == "YES" else Decimal(0)
    # Capital is released when the settlement is known: cash returns with the payout.
    assert Decimal(ev["dec-2"]["cash_before"]) == Decimal("1000") - cost + payout
    if outcome == "NO":
        assert Decimal(r["max_drawdown"]) == cost and Decimal(r["metrics"]["worst_rolling_drawdown"]) == cost
    else:
        assert r["max_drawdown"] == "0.00" and Decimal(r["metrics"]["high_water_mark"]) == Decimal("1000") - cost + payout
    lock = r["capital_lock"]
    assert Decimal(lock["max_lock_hours"]) >= Decimal("12")  # reserved at the decision, released 12 h later


def test_cluster_exposure_is_shared_across_markets_of_one_cluster(tmp_path):
    cfg = replace(CFG, risk_policy=replace(RISK, max_cluster_risk=Decimal("30")))
    d1, d2 = decision(1, T0), decision(2, T0, native="KXHIGHNY-26SEP26-B69.5")
    ev = events(run(None, build_ledger(tmp_path / "l.sqlite3", [d1, d2], [fill(d1), fill(d2)]), config=cfg))
    first, second = ev["dec-1"], ev["dec-2"]
    assert first["contracts"] > 0 and Decimal(first["recommended_size"]) <= Decimal("30")
    assert first["binding_constraint"] == "CLUSTER_CAP"
    left = Decimal("30") - Decimal(first["recommended_size"])
    assert Decimal(second["recommended_size"]) <= left
    assert second["binding_constraint"] == "CLUSTER_CAP" or second["contracts"] == 0


def test_fractional_contracts_are_never_sized(tmp_path):
    decs = [decision(1, T0, size="0.5"), decision(2, T0, native="KXHIGHNY-26SEP26-B69.5", size="3.7")]
    ev = events(run(None, build_ledger(tmp_path / "l.sqlite3", decs, [fill(d) for d in decs])))
    assert ev["dec-1"]["contracts"] == 0 and ev["dec-1"]["zero_size_reason"] == "LIQUIDITY_LIMIT:NO_DEPTH"
    assert ev["dec-2"]["contracts"] == 3 and ev["dec-2"]["binding_constraint"] == "LIQUIDITY"
    assert all(e["top_of_book_limited"] for e in ev.values())


# --------------------------------------------------------------------------- fail closed and edge cases


def test_missing_data_fails_closed_with_the_exact_reason(tmp_path):
    decs = [
        decision(1, T0, starter=False),
        decision(2, T0, native="KXHIGHNY-26SEP26-B69.5", received=T0 - timedelta(minutes=10)),
        decision(3, T0, native="KXHIGHNY-26SEP26-B71.5", fresh=False),
        decision(4, T0, native="KXHIGHNY-26SEP26-B73.5", cons=None),
        decision(5, T0, native="KXHIGHNY-26SEP26-B75.5", opportunity="not-a-record"),
        decision(6, T0 - timedelta(days=5), native="KXHIGHNY-26SEP21-B67.5"),  # before the fee verification
    ]
    ev = events(run(None, build_ledger(tmp_path / "l.sqlite3", decs), policies=(("H", sv2.POLICY_CANDIDATE),)), "H")
    assert ev["dec-1"]["zero_size_reason"] == "CAPITAL_HORIZON:TRADABLE_CASH_RELEASE_UNKNOWN"
    assert ev["dec-2"]["zero_size_reason"] == "STALE_DATA:BOOK_STALE"
    assert ev["dec-3"]["zero_size_reason"] == "STALE_DATA:MODEL_TIME_UNKNOWN"
    assert ev["dec-4"]["zero_size_reason"] == "UNCERTAINTY_TOO_HIGH:UNCERTAINTY_UNKNOWN"
    assert ev["dec-5"]["zero_size_reason"] == "UNSUPPORTED:DECISION_PAYLOAD_UNSUPPORTED"
    assert ev["dec-6"]["zero_size_reason"] == "UNSUPPORTED:FEE_UNVERIFIED"
    assert all(e["contracts"] == 0 for e in ev.values())


def test_a_broken_ledger_fails_the_whole_run(tmp_path):
    led = build_ledger(tmp_path / "l.sqlite3", [decision(1, T0)])

    class Broken:
        def accounts(self):
            return led.accounts()

        def entries(self, acct):
            rows = [dict(r) for r in led.entries(acct)]
            rows[-1]["payload_json"] = rows[-1]["payload_json"].replace("0.60", "0.99")
            return rows

    with pytest.raises(cf.CounterfactualInputError):
        run(None, Broken())


def test_a_large_edge_is_still_bound_by_the_hard_caps(tmp_path):
    dec = decision(1, T0, p="0.95", cons="0.90", price="0.30", size="100000")
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", [dec], [fill(dec, quantity=100000)]),
                 config=cf.DEFAULT_CONFIG, policies=cf.POLICY_SET)  # the operational $1 position cap
    for r in bundle["runs"]:  # every policy wants far more; the $1 position cap binds all of them
        e = r["events"][0]
        assert (e["contracts"], e["recommended_size"], e["binding_constraint"]) == (3, "0.99", "POSITION_CAP")
        assert Decimal(e["unconstrained_size"]) > Decimal("1.00")


@pytest.mark.parametrize("p,price", [("0.41", "0.40"), ("0.30", "0.40"), ("0.40", "0.40")])
def test_tiny_or_negative_edge_sizes_nothing(tmp_path, p, price):
    dec = decision(1, T0, p=p, cons=str(Decimal(p) - Decimal("0.02")), price=price)
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", [dec]), policies=cf.POLICY_SET)
    for r in bundle["runs"]:
        e = r["events"][0]
        assert e["contracts"] == 0 and e["verdict"] == "ZERO_EDGE", (r["policy_letter"], e["zero_size_reason"])


@pytest.mark.parametrize("p,cons,price", [("0.9999", "0.999", "0.99"), ("0.02", "0.01", "0.01"),
                                          ("0.001", "0.0001", "0.99"), ("1", "0.99", "0.50"), ("0", "0", "0.01")])
def test_probabilities_and_prices_near_zero_and_one(tmp_path, p, cons, price):
    dec = decision(1, T0, p=p, cons=cons, price=price)
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", [dec], [fill(dec)]), policies=cf.POLICY_SET)
    for r in bundle["runs"]:
        e = r["events"][0]
        assert e["verdict"] in {v.value for v in sv2.Verdict}
        assert Decimal(e["recommended_size"]) <= Decimal("50") and Decimal(r["ending_bankroll"]) > 0
        assert (e["contracts"] == 0) == (e["zero_size_reason"] is not None)


@pytest.mark.parametrize("bankroll", ["100", "100.50", "101"])
def test_bankroll_near_the_reserve_floor(tmp_path, bankroll):
    cfg = replace(CFG, starting_bankroll=Decimal(bankroll))
    dec = decision(1, T0)
    bundle = run(None, build_ledger(tmp_path / "l.sqlite3", [dec], [fill(dec)]), config=cfg, policies=cf.POLICY_SET)
    for r in bundle["runs"]:
        e = r["events"][0]
        room = Decimal(bankroll) - Decimal("100")
        assert Decimal(e["recommended_size"]) <= room
        if room == 0:
            assert e["zero_size_reason"] == "RISK_LIMIT:RISK_BUDGET_EXHAUSTED"
        else:  # one all-in contract costs $0.44: the reserve floor leaves room for floor(room / 0.44)
            assert e["binding_constraint"] == "RESERVE_FLOOR" and e["contracts"] == int(room // Decimal("0.44"))


def test_precheck_agrees_with_recommend():
    import test_sizing_v2 as base

    for req in (base.binary_request(), base.binary_request(model_probabilities=None),
                base.binary_request(starter=None), base.binary_request(uncertainty=None)):
        verdict, reason = sv2.precheck(req)
        rec = sv2.recommend(req, sv2.POLICY_C)
        if verdict is None:
            assert rec.verdict not in ("STALE_DATA", "UNSUPPORTED", "CAPITAL_HORIZON") or rec.recommended_contracts
        else:
            assert rec.verdict == verdict.value and f"Reason: {reason}." in rec.explanation


# --------------------------------------------------------------------------- panel contract


PANEL_KEYS = {"panel_version", "label", "market_id", "as_of_utc", "available", "unavailable_reason",
              "unavailable_detail", "primary_policy", "sides", "limitations"}
SIDE_KEYS = {"side", "decision_id", "decision_time", "recorded_qualification", "recorded_reason", "model_version",
             "available", "unavailable_reason", "unavailable_detail", "top_of_book_limited", "primary", "comparison"}
PRIMARY_KEYS = {"policy_id", "policy_version", "verdict", "block_reason", "bankroll_basis", "model_probability",
                "conservative_probability", "expected_net_edge", "uncertainty", "entry_price", "estimated_fee",
                "unconstrained_kelly_amount", "policy_amount_before_caps", "caps", "capital_horizon", "drawdown_cap",
                "final_contracts", "final_amount", "binding_constraint", "secondary_constraints", "explanation",
                "fill_status", "fill_reason"}


def test_panel_returns_the_canonical_rows_for_the_latest_decision(tmp_path):
    y = decision(1, T0)
    n = decision(2, T0, side="NO", p="0.40", cons="0.35", price="0.62")
    later = decision(3, T0 + timedelta(days=1), native="KXHIGHNY-26SEP27-B67.5")
    led = build_ledger(tmp_path / "l.sqlite3", [y, n, later], [fill(y)])
    panel = cf.panel_for_market(None, led, "kalshi:KXHIGHNY-26SEP26-B67.5", config=CFG)
    assert set(panel) == PANEL_KEYS and panel["available"] and panel["unavailable_reason"] is None
    assert "Recommended bet" not in json.dumps(panel) and "RESEARCH SIZING" in panel["label"]
    assert [s["side"] for s in panel["sides"]] == ["YES", "NO"]
    for s in panel["sides"]:
        assert set(s) == SIDE_KEYS and set(s["primary"]) == PRIMARY_KEYS
        assert [c["letter"] for c in s["comparison"]] == list("ABCDEFGH")
        assert all(isinstance(c["final_amount"], str) for c in s["comparison"])
    # The panel shows exactly what the full run computes for that decision.
    full = run(None, led, policies=cf.POLICY_SET)
    h = events(full, "H")["dec-1"]
    yes = panel["sides"][0]["primary"]
    assert (yes["final_amount"], yes["binding_constraint"], yes["verdict"]) == (
        h["recommended_size"], h["binding_constraint"], h["verdict"])
    # The upper bound came from the NO decision, the lower from the YES decision.
    assert events(full, "H")["dec-1"]["uncertainty_basis"] == "both recorded conservative bounds"


def test_panel_names_why_it_cannot_compute(tmp_path):
    led = build_ledger(tmp_path / "l.sqlite3", [
        decision(1, T0, p=None, cons=None, reasons=("MODEL_UNAVAILABLE",), qualify=False),
        decision(2, T0, native="KXHIGHNY-26SEP26-B69.5", price=None, size=None, reasons=("BOOK_MISSING",),
                 qualify=False),
        decision(3, T0, native="KXHIGHNY-26SEP26-B71.5", cons=None),
        decision(4, T0, native="KXHIGHNY-26SEP26-B73.5", reasons=("RULES_UNRESOLVED",), qualify=False),
        decision(5, T0, native="KXHIGHNY-26SEP26-B75.5", reasons=("PAYOFF_UNSUPPORTED",), qualify=False),
        decision(6, T0 - timedelta(days=5), native="KXHIGHNY-26SEP21-B67.5"),
    ])
    expected = {"KXHIGHNY-26SEP26-B67.5": cf.UNAVAILABLE_NO_MODEL, "KXHIGHNY-26SEP26-B69.5": cf.UNAVAILABLE_STALE_QUOTE,
                "KXHIGHNY-26SEP26-B71.5": cf.UNAVAILABLE_UNCERTAINTY, "KXHIGHNY-26SEP26-B73.5": cf.UNAVAILABLE_RULES,
                "KXHIGHNY-26SEP26-B75.5": cf.UNAVAILABLE_PAYOFF, "KXHIGHNY-26SEP21-B67.5": cf.UNAVAILABLE_FEES,
                "KXHIGHNY-NONE": cf.UNAVAILABLE_NO_DECISION}
    for native, reason in expected.items():
        panel = cf.panel_for_market(None, led, f"kalshi:{native}", config=CFG)
        assert not panel["available"] and panel["unavailable_reason"] == reason, (native, panel["unavailable_detail"])
        assert reason in cf.UNAVAILABLE_REASONS
    assert cf.panel_for_market(None, None, "kalshi:X")["unavailable_reason"] == cf.UNAVAILABLE_LEDGER


def test_panel_respects_as_of(tmp_path):
    early, late = decision(1, T0), decision(2, T0 + timedelta(days=1))
    late["slot"] = "2026-09-27|kalshi:KXHIGHNY-26SEP26-B67.5|YES"
    led = build_ledger(tmp_path / "l.sqlite3", [early, late])
    panel = cf.panel_for_market(None, led, "kalshi:KXHIGHNY-26SEP26-B67.5", as_of=T0 + timedelta(hours=1), config=CFG)
    assert panel["as_of_utc"] == iso(T0) and panel["sides"][0]["decision_id"] == "dec-1"


# --------------------------------------------------------------------------- read-only inputs, CLI


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_writes_only_the_output_and_leaves_inputs_byte_unchanged(tmp_path, capsys):
    import test_sizing_v2 as base

    d1 = decision(1, T0)
    lpath = tmp_path / "ledger.sqlite3"
    build_ledger(lpath, [d1], [fill(d1)], [(d1, "YES", T0 + timedelta(hours=11), T0 + timedelta(hours=12))])
    dpath = tmp_path / "evidence.sqlite3"
    SnapshotStore(dpath)
    before = {p.name: _sha(p) for p in tmp_path.iterdir() if p.is_file()}
    out = tmp_path / "status" / "counterfactual.json"
    assert cli.main(["sizing", "counterfactual", "--db", str(dpath), "--ledger", str(lpath), "--out", str(out)]) == 0
    after = {p.name: _sha(p) for p in tmp_path.iterdir() if p.is_file()}
    # The ledger and the evidence database are byte-unchanged. The only new files are SQLite's
    # own shared-memory sidecars of the WAL-mode evidence database (an empty WAL: nothing written).
    assert {k: after[k] for k in before} == before
    assert set(after) - set(before) <= {"evidence.sqlite3-wal", "evidence.sqlite3-shm"}
    assert not (tmp_path / "evidence.sqlite3-wal").exists() or (tmp_path / "evidence.sqlite3-wal").stat().st_size == 0
    assert not any(p.name.startswith("ledger.sqlite3-") for p in tmp_path.iterdir())
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["schema"] == cf.BUNDLE_SCHEMA and len(bundle["runs"]) == 8
    assert [r["policy_id"] for r in bundle["runs"]][-1] == sv2.POLICY_CANDIDATE.policy_id
    assert "wrote" not in bundle and json.loads(capsys.readouterr().out)["decisions"] == 1
    # Refuses to overwrite an input, and the frozen modules stay byte-identical.
    assert cli.main(["sizing", "counterfactual", "--db", str(dpath), "--ledger", str(lpath), "--out", str(lpath)]) == 2
    assert _sha(lpath) == before["ledger.sqlite3"]
    for path, digest in base.FROZEN.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest


def test_sizing_help_lists_counterfactual_and_both_entry_points_dispatch(capsys):
    from edge_lab import sizing_eval

    with pytest.raises(SystemExit):
        cli.main(["sizing", "-h"])
    assert "counterfactual" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sizing_eval.main(["counterfactual", "-h"])
    assert "--ledger" in capsys.readouterr().out


def test_the_runner_never_imports_the_frozen_sizing_path_or_writes_a_ledger():
    text = (ROOT / "src" / "edge_lab" / "sizing_counterfactual.py").read_text(encoding="utf-8")
    assert "from .sizing import" not in text and "import sizing\n" not in text
    for call in ("record_decision", "record_fill", "record_settlement", "open_account(", "save_snapshot"):
        assert call not in text


def test_existing_policies_keep_their_frozen_semantics():
    from edge_lab import sizing_eval

    letters = dict(cf.POLICY_SET)
    assert list(letters) == list("ABCDEFGH")
    for letter, policy in zip("ABCDEG", (sv2.POLICY_A, sv2.POLICY_B, sv2.POLICY_C, sv2.POLICY_D, sv2.POLICY_E,
                                          sv2.POLICY_G)):
        assert letters[letter] is policy
    # F is the directive's robust FRACTIONAL Kelly: the existing versioned robust 1/2 Kelly, referenced.
    assert letters["F"] is sizing_eval.F_HALF
    assert sizing_eval.F_HALF.to_dict() == {
        "policy_id": "SV2-F-robust-half-kelly", "policy_version": "1", "rule": "KELLY",
        "description": "F variant: robust 1/2 Kelly", "unit_amount": None, "bankroll_fraction": None,
        "min_edge": "0", "kelly_fraction": "0.5", "robust": True, "drawdown_alpha": None, "drawdown_beta": None,
        "robust_constraint": False, "cvar_level": None, "cvar_max_loss": None, "joint": False}
    assert sv2.POLICY_F.kelly_fraction == Decimal(1) and sv2.POLICY_F.policy_id == "SV2-F-robust-kelly"  # unchanged
    assert letters["H"] is sv2.POLICY_CANDIDATE
    assert sv2.POLICY_CANDIDATE.to_dict() == {
        "policy_id": "SV2-H-cluster-robust-rck", "policy_version": "1", "rule": "KELLY",
        "description": "H variant: joint robust 1/2 Kelly + robust drawdown constraint (alpha 0.7, beta 0.1)",
        "unit_amount": None, "bankroll_fraction": None, "min_edge": "0", "kelly_fraction": "0.5", "robust": True,
        "drawdown_alpha": "0.7", "drawdown_beta": "0.1", "robust_constraint": True, "cvar_level": None,
        "cvar_max_loss": None, "joint": True}


# --------------------------------------------------------------------------- real pipeline evidence


def test_end_to_end_over_the_real_exp001_pipeline(tmp_path, monkeypatch):
    """Decisions recorded by `exp001_shadow.run_day` from captured evidence, settled from the
    captured Kalshi settlement page: the runner reads them all and attaches the outcomes."""
    from edge_lab import exp001_shadow as shadow
    from edge_lab import exp001_stageb as stageb
    from test_exp001_shadow import CLOSED, _result, _settled
    from test_forward import D, _full_day

    store = SnapshotStore(tmp_path / "fwd.sqlite3")
    lpath = tmp_path / "ledger.sqlite3"
    ledger = ShadowLedger(lpath)
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    _settled(store, 67, _result(67))
    shadow.settle_open_positions(store, ledger)
    digest = _sha(lpath)
    bundle = cf.run_counterfactual(store, ShadowLedger.open_readonly(lpath), policies=cf.POLICY_SET)
    assert _sha(lpath) == digest
    for r in bundle["runs"]:
        assert r["decision_count"] == 12
        assert all(e["later_outcome"] in ("YES", "NO") for e in r["events"])  # from the captured evidence
        # 2026-09-22 predates the KXHIGHNY fee verification record: every size fails closed.
        assert all(e["zero_size_reason"] == "UNSUPPORTED:FEE_UNVERIFIED" for e in r["events"])
    assert {o["source"] for o in bundle["provenance"]["outcomes"].values()} == {"evidence_db"}
    # A rejected decision has no recorded fill: its confirmation comes from the day's re-check capture.
    inputs = cf.load_inputs(store, ShadowLedger.open_readonly(lpath))
    rejected = [d for d in inputs.decisions if d.qualification == "REJECT" and not d.fills]
    assert rejected
    quote, basis = cf._confirmation(inputs, rejected[0])
    assert basis == "DAY_RECHECK_CAPTURE" and quote is not None and quote.market_id == rejected[0].market_id
    known = {o["known_utc"] for o in bundle["provenance"]["outcomes"].values()}
    assert known == {"2026-09-24T14:00:00+00:00"}  # the settlement page's receipt time
