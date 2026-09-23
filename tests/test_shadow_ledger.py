"""Gate 6: append-only shadow ledger, account replay, deterministic fills and position sizing."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.fill_policy import LATENCY_CONFIRMED_V1, simulate_fill
from edge_lab.opportunity import ExecutableQuote
from edge_lab.shadow_ledger import LedgerConflict, LedgerError, ShadowLedger, replay
from edge_lab.sizing import SizingPolicy, suggest_position_size

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
ACC = "acct"


@pytest.fixture
def ledger(tmp_path):
    lg = ShadowLedger(tmp_path / "ledger.sqlite3")
    lg.open_account(ACC, starting_bankroll=Decimal("100.00"), strategy="test", opened_at_utc=T0.isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="kalshi-quadratic-taker-v1")
    return lg


def decide(lg, n, *, qualification="QUALIFY", event="ev1", cluster="cl1"):
    lg.record_decision(ACC, {"decision_id": f"d{n}", "opportunity_id": f"o{n}", "as_of_utc": T0.isoformat(),
                             "qualification": qualification, "reason": "QUALIFY" if qualification == "QUALIFY" else "NO_EDGE",
                             "event_id": event, "market_id": f"kalshi:M{n}", "side": "YES", "outcome_cluster": cluster})


def fill(lg, n, *, qty=1, price="0.40", status="FILLED", side="YES", event="ev1", cluster="cl1", reason=None):
    cost = FEES.taker_buy(qty, Decimal(price)) if status == "FILLED" else None
    payload = {"fill_id": f"f{n}", "decision_id": f"d{n}", "venue": "kalshi", "market_id": f"kalshi:M{n}",
               "event_id": event, "outcome_cluster": cluster, "side": side, "filled_at_utc": T0.isoformat(),
               "status": status, "reason": reason or status, "quantity": qty if status == "FILLED" else 0,
               "price": price if status == "FILLED" else None,
               "fee": str(cost.fee) if cost else None, "total_cost": str(cost.total_cost) if cost else None}
    return lg.record_fill(ACC, payload)


def settle(lg, n, outcome):
    return lg.record_settlement(ACC, fill_id=f"f{n}", outcome=outcome, evidence={"test": n},
                                settled_at_utc=(T0 + timedelta(days=1)).isoformat())


# --------------------------------------------------------------------------- lifecycle


def test_winning_position(ledger):
    decide(ledger, 1)
    fill(ledger, 1, price="0.40")  # cost 0.40 + fee 0.0168 -> cash 0.42
    s = ledger.state(ACC)
    assert s.settled_cash == Decimal("99.58") and s.committed_capital == Decimal("0.42")
    assert s.open_worst_case_risk == Decimal("0.42") and s.open_potential_payout == Decimal(1)
    assert s.equity == Decimal("100.00") and s.realized_pnl == 0  # no unrealized gain counted
    settle(ledger, 1, "YES")
    s = ledger.state(ACC)
    assert s.settled_cash == Decimal("100.58") and s.realized_pnl == Decimal("0.58")
    assert s.committed_capital == 0 and s.open_worst_case_risk == 0 and s.equity == Decimal("100.58")
    p = s.positions[0]
    assert p.status == "SETTLED" and p.payout == 1 and p.net_pnl == Decimal("0.58") and p.fees == Decimal("0.02")


def test_losing_position(ledger):
    decide(ledger, 1)
    fill(ledger, 1, price="0.40")
    settle(ledger, 1, "NO")
    s = ledger.state(ACC)
    assert s.realized_pnl == Decimal("-0.42") and s.settled_cash == Decimal("99.58") and s.equity == Decimal("99.58")


def test_no_fill_changes_no_money(ledger):
    decide(ledger, 1)
    fill(ledger, 1, status="NO_FILL", reason="PRICE_MOVED_AWAY")
    s = ledger.state(ACC)
    assert s.no_fills == 1 and s.fills == 0 and s.no_fill_reasons == {"PRICE_MOVED_AWAY": 1}
    assert s.settled_cash == Decimal("100.00") and s.positions == []
    with pytest.raises(LedgerError):
        settle(ledger, 1, "YES")


def test_fees_are_in_cost_and_pnl(ledger):
    decide(ledger, 1)
    fill(ledger, 1, qty=10, price="0.50")  # 5.00 + fee ceil6(0.07*10*0.25)=0.175 -> cash 5.18
    s = ledger.state(ACC)
    assert s.fees_paid == Decimal("0.18") and s.committed_capital == Decimal("5.18")
    settle(ledger, 1, "YES")
    assert ledger.state(ACC).realized_pnl == Decimal("4.82")


# --------------------------------------------------------------------------- idempotency


def test_duplicate_decision_fill_and_settlement_are_idempotent(ledger):
    decide(ledger, 1)
    h1, created1 = fill(ledger, 1)
    h2, created2 = fill(ledger, 1)
    assert created1 and not created2 and h1 == h2
    settle(ledger, 1, "YES")
    _, again = settle(ledger, 1, "YES")
    assert not again
    s = ledger.state(ACC)
    assert s.decisions == 1 and s.fills == 1 and s.settlements == 1 and s.realized_pnl == Decimal("0.58")
    assert len(ledger.entries(ACC)) == 4  # opened, decision, fill, settlement


def test_conflicting_duplicates_are_refused(ledger):
    decide(ledger, 1)
    with pytest.raises(LedgerConflict):
        decide(ledger, 1, qualification="REJECT")
    fill(ledger, 1)
    with pytest.raises(LedgerConflict):
        fill(ledger, 1, price="0.41")
    settle(ledger, 1, "YES")
    with pytest.raises(LedgerConflict):
        settle(ledger, 1, "NO")
    with pytest.raises(LedgerConflict):
        ledger.open_account(ACC, starting_bankroll=Decimal("5"), strategy="x", opened_at_utc=T0.isoformat(),
                            sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")


# --------------------------------------------------------------------------- invariants


def test_rejected_decision_cannot_fill(ledger):
    decide(ledger, 1, qualification="REJECT")
    with pytest.raises(LedgerError):
        fill(ledger, 1)
    fill(ledger, 1, status="NO_FILL", reason="NOT_QUALIFIED")  # recording a no-fill is fine


def test_fill_needs_a_decision_and_an_account(tmp_path, ledger):
    with pytest.raises(LedgerError):
        fill(ledger, 9)
    fresh = ShadowLedger(tmp_path / "other.sqlite3")
    with pytest.raises(LedgerError):
        fresh.record_decision("nobody", {"decision_id": "d", "opportunity_id": "o", "as_of_utc": T0.isoformat(),
                                         "qualification": "QUALIFY", "reason": "QUALIFY"})


def test_no_negative_cash(ledger):
    decide(ledger, 1)
    with pytest.raises(LedgerError, match="insufficient settled cash"):
        fill(ledger, 1, qty=250, price="0.40")  # ~104 > 100
    assert ledger.state(ACC).settled_cash == Decimal("100.00") and ledger.state(ACC).fills == 0


def test_no_phantom_profit(ledger):
    decide(ledger, 1)
    fill(ledger, 1, qty=2, price="0.30")
    with pytest.raises(LedgerError):
        ledger.record_settlement(ACC, fill_id="f1", outcome="MAYBE", evidence={}, settled_at_utc=T0.isoformat())
    settle(ledger, 1, "NO")
    s = ledger.state(ACC)
    # P&L comes from the fill, never from the caller; equity reconciles exactly.
    assert s.realized_pnl == -s.positions[0].cost_basis and s.equity == s.starting_bankroll + s.realized_pnl


def test_entries_are_immutable_and_chained(ledger):
    decide(ledger, 1)
    with sqlite3.connect(ledger.path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE ledger_entries SET payload_json = '{}' WHERE seq = 2")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM ledger_entries")
    rows = [dict(r) for r in ledger.entries(ACC)]
    rows[1]["payload_json"] = rows[1]["payload_json"].replace("QUALIFY", "REJECT")
    with pytest.raises(LedgerError, match="hash"):
        replay(rows)
    rows = [dict(r) for r in ledger.entries(ACC)]
    with pytest.raises(LedgerError, match="chain"):
        replay([rows[1]])


# --------------------------------------------------------------------------- replay


def _script(lg):
    decide(lg, 1)
    fill(lg, 1, price="0.40")
    decide(lg, 2, qualification="REJECT")
    decide(lg, 3, event="ev2", cluster="cl2")
    fill(lg, 3, qty=3, price="0.25")
    decide(lg, 4)
    fill(lg, 4, status="NO_FILL", reason="NO_CONFIRMATION")
    settle(lg, 1, "NO")


def test_complete_rebuild_from_zero_and_deterministic_replay(tmp_path):
    a, b = ShadowLedger(tmp_path / "a.sqlite3"), ShadowLedger(tmp_path / "b.sqlite3")
    for lg in (a, b):
        lg.open_account(ACC, starting_bankroll=Decimal("100.00"), strategy="test", opened_at_utc=T0.isoformat(),
                        sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")
        _script(lg)
    sa, sb = a.state(ACC), b.state(ACC)
    assert sa.to_dict() == sb.to_dict() and a.verify_chain(ACC) == b.verify_chain(ACC)
    assert (sa.decisions, sa.qualified_decisions, sa.fills, sa.no_fills, sa.settlements) == (4, 3, 2, 1, 1)
    assert sa.committed_capital == FEES.taker_buy(3, Decimal("0.25")).total_cost
    assert sa.equity == sa.starting_bankroll + sa.realized_pnl
    # Restart: a new handle on the same file replays to the same state.
    assert ShadowLedger(a.path).state(ACC).to_dict() == sa.to_dict()


def test_exposure_by_event_and_cluster(ledger):
    decide(ledger, 1, event="ev1", cluster="cl1")
    fill(ledger, 1, event="ev1", cluster="cl1", price="0.40")
    decide(ledger, 2, event="ev2", cluster="cl1")
    fill(ledger, 2, event="ev2", cluster="cl1", price="0.20")
    s = ledger.state(ACC)
    assert s.event_exposure("ev1") == Decimal("0.42") and s.event_exposure("ev2") == Decimal("0.22")
    assert s.cluster_exposure("cl1") == Decimal("0.64") and s.cluster_exposure("none") == 0


# --------------------------------------------------------------------------- fill policy


def q(ask="0.40", size="5", at=T0 - timedelta(minutes=2), side="YES", market="kalshi:M1", anomaly=None):
    return ExecutableQuote("kalshi", market, side, None, None if ask is None else Decimal(ask),
                           None if size is None else Decimal(size), None if at is None else at.isoformat(), None,
                           f"snapshot:{ask}-{size}", anomaly=anomaly)


def conf(**kw):
    kw.setdefault("at", T0 - timedelta(minutes=2) + timedelta(minutes=12))
    return q(**kw)


@pytest.mark.parametrize("entry, confirmation, qty, reason", [
    (None, None, 1, "NO_ENTRY_QUOTE"),
    (q(at=T0 - timedelta(minutes=6)), conf(), 1, "STALE_ENTRY_QUOTE"),
    (q(at=T0 + timedelta(seconds=1)), conf(), 1, "STALE_ENTRY_QUOTE"),
    (q(ask=None), conf(), 1, "NO_ENTRY_PRICE"),
    (q(anomaly="crossed"), conf(), 1, "NO_ENTRY_PRICE"),
    (q(size="0.5"), conf(), 1, "INSUFFICIENT_SIZE"),
    (q(), None, 1, "NO_CONFIRMATION"),
    (q(), conf(market="kalshi:OTHER"), 1, "CONFIRMATION_MISMATCH"),
    (q(), conf(at=T0 + timedelta(minutes=7)), 1, "CONFIRMATION_OUTSIDE_WINDOW"),
    (q(), conf(at=T0 + timedelta(minutes=14)), 1, "CONFIRMATION_OUTSIDE_WINDOW"),
    (q(), conf(ask=None), 1, "CONFIRMATION_NO_OFFER"),
    (q(), conf(ask="0.41"), 1, "PRICE_MOVED_AWAY"),
    (q(size="5"), conf(size="2"), 3, "CONFIRMATION_INSUFFICIENT_SIZE"),
    (q(), conf(), 0, "ZERO_SIZE"),
])
def test_insufficient_evidence_is_no_fill(entry, confirmation, qty, reason):
    r = simulate_fill(quantity=qty, entry=entry, confirmation=confirmation, as_of=T0)
    assert (r.status, r.reason, r.quantity, r.price) == ("NO_FILL", reason, 0, None)


def test_fill_is_at_entry_price_never_a_better_later_price():
    r = simulate_fill(quantity=2, entry=q(ask="0.40"), confirmation=conf(ask="0.35"), as_of=T0)
    assert (r.status, r.price, r.quantity) == ("FILLED", Decimal("0.40"), 2)
    assert r.policy_id == LATENCY_CONFIRMED_V1.policy_id
    edge = simulate_fill(quantity=1, entry=q(), confirmation=conf(at=T0 - timedelta(minutes=2) + timedelta(minutes=10)),
                         as_of=T0)
    assert edge.status == "FILLED"  # window bounds are inclusive


def test_fill_policy_is_deterministic():
    args = dict(quantity=1, entry=q(), confirmation=conf(), as_of=T0)
    assert simulate_fill(**args) == simulate_fill(**args)


# --------------------------------------------------------------------------- sizing


POLICY = SizingPolicy("t", fixed_contracts=None, kelly_fraction=Decimal("0.25"), max_position_contracts=1000,
                      max_position_risk=Decimal("50"), max_event_risk=Decimal("50"), max_cluster_risk=Decimal("50"),
                      max_portfolio_risk=Decimal("50"), reserve=Decimal("0"))


def size(**kw):
    args = dict(bankroll=Decimal("100"), conservative_probability=Decimal("0.60"), executable_price=Decimal("0.40"),
                fees=FEES, available_size=Decimal("1000"), event_exposure=Decimal(0), cluster_exposure=Decimal(0),
                total_open_risk=Decimal(0), policy=POLICY)
    args.update(kw)
    return suggest_position_size(**args)


def test_fractional_kelly_raw_size():
    r = size()
    c = FEES.taker_buy(1, Decimal("0.40")).cost_per_contract  # 0.42
    full = (Decimal("0.60") - c) / (1 - c)
    assert r.full_kelly_fraction == full
    assert r.raw_size == int(Decimal("0.25") * full * 100 / c)  # 18
    assert r.final_size == r.raw_size and r.binding_constraint == "SIZING_RULE"


def test_hard_caps_override_kelly():
    assert size(policy=replace(POLICY, max_position_contracts=5)).binding_constraint == "MAX_POSITION_CONTRACTS"
    r = size(policy=replace(POLICY, max_position_risk=Decimal("2.00")))
    assert r.final_size == 4 and r.binding_constraint == "MAX_POSITION_RISK" and r.total_cost <= Decimal("2.00")
    r = size(event_exposure=Decimal("49"), policy=replace(POLICY, kelly_fraction=Decimal("1")))
    assert r.binding_constraint == "MAX_EVENT_RISK" and r.final_size == 2
    r = size(cluster_exposure=Decimal("49.5"))
    assert r.binding_constraint == "MAX_CLUSTER_RISK" and r.final_size == 1
    r = size(total_open_risk=Decimal("50"))
    assert r.final_size == 0 and r.binding_constraint == "MAX_PORTFOLIO_RISK"


def test_reserve_and_liquidity_caps():
    r = size(policy=replace(POLICY, reserve=Decimal("99")))
    assert r.binding_constraint == "RESERVE" and r.final_size == 2
    r = size(available_size=Decimal("3.7"))
    assert (r.risk_adjusted_size, r.liquidity_capped_size, r.final_size, r.binding_constraint) == (18, 3, 3, "LIQUIDITY")


def test_no_edge_and_missing_inputs_give_zero():
    assert size(conservative_probability=Decimal("0.40")).binding_constraint == "NO_EDGE"
    for missing in ("conservative_probability", "executable_price", "available_size"):
        r = size(**{missing: None})
        assert r.final_size == 0 and r.binding_constraint == "INPUT_MISSING" and r.total_cost is None
    assert size(executable_price=Decimal("1.00")).binding_constraint == "INVALID_PRICE"


def test_fixed_rule_and_policy_validation():
    fixed = replace(POLICY, fixed_contracts=1, kelly_fraction=None)
    r = size(policy=fixed)
    assert (r.raw_size, r.final_size, r.binding_constraint) == (1, 1, "SIZING_RULE")
    with pytest.raises(ValueError):
        replace(POLICY, fixed_contracts=1)  # both rules
    with pytest.raises(ValueError):
        replace(POLICY, kelly_fraction=Decimal("1.5"))
    with pytest.raises(ValueError):
        replace(POLICY, reserve=Decimal("-1"))
    with pytest.raises(ValueError):
        size(total_open_risk=Decimal("-1"))


def test_sizing_records_every_stage():
    d = size(available_size=Decimal("3")).to_dict()
    assert {"raw_size", "risk_adjusted_size", "liquidity_capped_size", "final_size", "binding_constraint"} <= set(d)
