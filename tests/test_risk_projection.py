"""#160 package I1: `risk` reads a `RiskAccount` shape, not a `shadow_ledger` type, with byte-identical output.

The expectations below were recorded from the legacy `risk.py` (which imported `shadow_ledger.AccountState`)
before the refactor, on the same replayed shadow account. Every field must stay identical.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import risk
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.risk import RiskPolicy, assess, equity_curve, withdrawal_assessment
from edge_lab.shadow_ledger import ShadowLedger

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
ACC = "acct"
POLICY = RiskPolicy("risk-test", reserve_floor=Decimal("20"), max_position_risk=Decimal("5"),
                    max_event_risk=Decimal("10"), max_cluster_risk=Decimal("10"), max_portfolio_risk=Decimal("30"),
                    daily_loss_limit=Decimal("5"), weekly_loss_limit=Decimal("10"), max_drawdown=Decimal("15"))
LOOSE = replace(POLICY, policy_id="risk-loose", daily_loss_limit=Decimal("12"), weekly_loss_limit=Decimal("20"),
                max_event_risk=Decimal("3"), max_cluster_risk=Decimal("3"))
AT = T0 + timedelta(days=2, minutes=10)

_NOTE = ["worst case for a long binary is its full cost; committed capital settling later is not cash"]
# Recorded from the legacy module (risk.py importing shadow_ledger.AccountState), exact text.
RECORDED_TIGHT = {
    "account_id": "acct", "as_of_utc": "2026-09-25T22:10:00+00:00", "breaches": [],
    "capital_release": [
        {"best_case_payout": "0", "committed_capital": "92.48", "guaranteed_cash": "92.48",
         "horizon": "available_now", "positions": 0},
        {"best_case_payout": "3", "committed_capital": "0.79", "guaranteed_cash": "0", "horizon": "within_1_hour",
         "positions": 1},
        {"best_case_payout": "0", "committed_capital": "0", "guaranteed_cash": "0", "horizon": "within_1_day",
         "positions": 0},
        {"best_case_payout": "4", "committed_capital": "1.39", "guaranteed_cash": "0", "horizon": "within_1_week",
         "positions": 1},
        {"best_case_payout": "2", "committed_capital": "1.26", "guaranteed_cash": "0", "horizon": "locked",
         "positions": 1},
    ],
    "cluster_exposure": {"c2": "2.05", "c3": "1.39"}, "committed_capital": "3.44", "daily_loss": "4.54",
    "drawdown": "4.54", "equity": "95.92", "new_risk_allowed": False, "notes": _NOTE,
    "open_worst_case_risk": "3.44", "peak_equity": "100.46", "policy_id": "risk-test",
    "remaining_risk_capacity": "0", "reserve_floor": "20", "risk_per_event": {"e2": "0.79", "e3": "2.65"},
    "risk_per_position": {"f3": "0.79", "f4": "1.26", "f5": "1.39"}, "settled_cash": "92.48",
    "starting_bankroll": "100.00", "total_portfolio_exposure": "3.44", "weekly_loss": "4.08",
}
RECORDED_LOOSE = {
    "account_id": "acct", "as_of_utc": "2026-09-26T22:10:00+00:00", "breaches": [],
    "capital_release": [
        {"best_case_payout": "0", "committed_capital": "92.48", "guaranteed_cash": "92.48",
         "horizon": "available_now", "positions": 0},
        {"best_case_payout": "0", "committed_capital": "0", "guaranteed_cash": "0", "horizon": "within_1_hour",
         "positions": 0},
        {"best_case_payout": "0", "committed_capital": "0", "guaranteed_cash": "0", "horizon": "within_1_day",
         "positions": 0},
        {"best_case_payout": "4", "committed_capital": "1.39", "guaranteed_cash": "0", "horizon": "within_1_week",
         "positions": 1},
        {"best_case_payout": "5", "committed_capital": "2.05", "guaranteed_cash": "0", "horizon": "locked",
         "positions": 2},
    ],
    "cluster_exposure": {"c2": "2.05", "c3": "1.39"}, "committed_capital": "3.44", "daily_loss": "0",
    "drawdown": "4.54", "equity": "95.92", "new_risk_allowed": True, "notes": _NOTE,
    "open_worst_case_risk": "3.44", "peak_equity": "100.46", "policy_id": "risk-loose",
    "remaining_risk_capacity": "7.02", "reserve_floor": "20", "risk_per_event": {"e2": "0.79", "e3": "2.65"},
    "risk_per_position": {"f3": "0.79", "f4": "1.26", "f5": "1.39"}, "settled_cash": "92.48",
    "starting_bankroll": "100.00", "total_portfolio_exposure": "3.44", "weekly_loss": "4.08",
}
RECORDED_WITHDRAWAL = {
    "account_id": "acct", "as_of_utc": "2026-09-25T22:10:00+00:00", "policy_safe_withdrawable": "72.48",
    "reasons": ["SHADOW_ACCOUNT: no real money exists", "EDGE_NOT_VERIFIED", "FEE_SCHEDULE_UNVERIFIED",
                "NO_OWNER_APPROVED_WITHDRAWAL_POLICY", "DRAW_FORMULA_NOT_DEFINED"],
    "recommendation_status": "NOT_RECOMMENDED", "recommended_owner_draw": None, "technically_withdrawable": "92.48",
}
RECORDED_CURVE = [("start", "100.00"), ("2026-09-24T00:00:00+00:00", "100.46"), ("2026-09-25T22:00:00+00:00", "95.92")]


@pytest.fixture
def state(tmp_path):
    lg = ShadowLedger(tmp_path / "l.sqlite3")
    lg.open_account(ACC, starting_bankroll=Decimal("100.00"), strategy="test", opened_at_utc=T0.isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")

    def open_position(n, *, qty, price, event, cluster, settles):
        lg.record_decision(ACC, {"decision_id": f"d{n}", "opportunity_id": f"o{n}", "as_of_utc": T0.isoformat(),
                                 "qualification": "QUALIFY", "reason": "QUALIFY"})
        cost = FEES.taker_buy(qty, Decimal(price))
        lg.record_fill(ACC, {"fill_id": f"f{n}", "decision_id": f"d{n}", "venue": "kalshi", "market_id": f"kalshi:M{n}",
                             "event_id": event, "outcome_cluster": cluster, "side": "YES",
                             "filled_at_utc": T0.isoformat(), "status": "FILLED", "reason": "FILLED", "quantity": qty,
                             "price": price, "fee": str(cost.fee), "total_cost": str(cost.total_cost),
                             "expected_settlement_utc": None if settles is None else settles.isoformat()})

    def settle(n, outcome, at):
        lg.record_settlement(ACC, fill_id=f"f{n}", outcome=outcome, evidence={"evidence_available_utc": at.isoformat()},
                             settled_at_utc=at.isoformat())

    open_position(1, qty=5, price="0.90", event="e1", cluster="c1", settles=T0 + timedelta(hours=20))
    open_position(2, qty=5, price="0.90", event="e2", cluster="c1", settles=T0 + timedelta(hours=20))
    open_position(3, qty=3, price="0.25", event="e2", cluster="c2", settles=T0 + timedelta(days=2, minutes=30))
    open_position(4, qty=2, price="0.61", event="e3", cluster="c2", settles=None)
    open_position(5, qty=4, price="0.33", event="e3", cluster="c3", settles=T0 + timedelta(days=5))
    settle(1, "YES", T0 + timedelta(hours=2))
    settle(2, "NO", T0 + timedelta(days=2))
    return lg.state(ACC)


def _plain(d):
    """JSON round trip: exact text, so `Decimal("0")` and `Decimal("0.00")` stay distinguishable."""
    return json.loads(json.dumps(d))


@pytest.mark.parametrize("policy,at,recorded", [(POLICY, AT, RECORDED_TIGHT),
                                                (LOOSE, AT + timedelta(days=1), RECORDED_LOOSE)])
def test_assess_on_a_replayed_shadow_account_is_byte_identical_to_the_legacy_record(state, policy, at, recorded):
    got = _plain(assess(state, policy, at).to_dict())
    assert set(got) == set(recorded)
    for key in recorded:  # field by field, so a failure names the field
        assert got[key] == recorded[key], key


def test_withdrawal_and_equity_curve_are_unchanged(state):
    report = assess(state, POLICY, AT)
    assert _plain(withdrawal_assessment(state, report).to_dict()) == RECORDED_WITHDRAWAL
    assert [(t, str(e)) for t, e in equity_curve(state)] == RECORDED_CURVE


# ---------------------------------------------------------------- the edge is gone

RISK_PY = Path(risk.__file__)


def test_risk_does_not_import_shadow_ledger_in_any_form():
    """Not at runtime, not under TYPE_CHECKING, not lazily inside a function: no import node names it."""
    tree = ast.parse(RISK_PY.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [node.module or ""] + [a.name for a in node.names]
    assert not [n for n in names if "shadow_ledger" in n or n == "AccountState"], names
    assert "AccountState" not in vars(risk) and "shadow_ledger" not in vars(risk)


@dataclass(frozen=True)
class _Pos:
    position_id: str
    opened_at_utc: str
    event_id: str
    outcome_cluster: str
    status: str
    cost_basis: Decimal
    max_downside: Decimal
    potential_payout: Decimal
    expected_settlement_utc: str | None
    net_pnl: Decimal | None
    settled_at_utc: str | None


@dataclass(frozen=True)
class _Account:
    account_id: str
    starting_bankroll: Decimal
    settled_cash: Decimal
    committed_capital: Decimal
    open_worst_case_risk: Decimal
    equity: Decimal
    positions: tuple[_Pos, ...]

    def open_positions(self):
        return tuple(p for p in self.positions if p.status == "OPEN")


def test_a_frozen_non_shadow_account_satisfies_the_protocol_and_gives_the_same_report(state):
    """The projection path: any immutable object with the RiskAccount shape, here a copy of the replayed state."""
    copy = _Account(state.account_id, state.starting_bankroll, state.settled_cash, state.committed_capital,
                    state.open_worst_case_risk, state.equity,
                    tuple(_Pos(p.position_id, p.opened_at_utc, p.event_id, p.outcome_cluster, p.status, p.cost_basis,
                               p.max_downside, p.potential_payout, p.expected_settlement_utc, p.net_pnl,
                               p.settled_at_utc) for p in state.positions))
    assert _plain(assess(copy, POLICY, AT).to_dict()) == RECORDED_TIGHT
    assert _plain(assess(copy, LOOSE, AT + timedelta(days=1)).to_dict()) == RECORDED_LOOSE
