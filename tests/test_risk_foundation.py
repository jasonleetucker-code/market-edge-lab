"""Issue #6 risk/capital foundation and issue #3 Outcome Board backend, over replayed shadow accounts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.outcome_board import WORST_CASE_METHOD, build_board
from edge_lab.risk import HORIZONS, RiskPolicy, assess, equity_curve, withdrawal_assessment
from edge_lab.shadow_ledger import ShadowLedger, knowledge_time

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
ACC = "acct"
POLICY = RiskPolicy("risk-test", reserve_floor=Decimal("20"), max_position_risk=Decimal("5"),
                    max_event_risk=Decimal("10"), max_cluster_risk=Decimal("10"), max_portfolio_risk=Decimal("30"),
                    daily_loss_limit=Decimal("5"), weekly_loss_limit=Decimal("10"), max_drawdown=Decimal("15"))


@pytest.fixture
def ledger(tmp_path):
    lg = ShadowLedger(tmp_path / "l.sqlite3")
    lg.open_account(ACC, starting_bankroll=Decimal("100.00"), strategy="test", opened_at_utc=T0.isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")
    return lg


def open_position(lg, n, *, qty=1, price="0.40", side="YES", event="ev1", cluster="cl1", settles=T0 + timedelta(hours=20),
                  at=T0):
    lg.record_decision(ACC, {"decision_id": f"d{n}", "opportunity_id": f"o{n}", "as_of_utc": T0.isoformat(),
                             "qualification": "QUALIFY", "reason": "QUALIFY"})
    cost = FEES.taker_buy(qty, Decimal(price))
    lg.record_fill(ACC, {"fill_id": f"f{n}", "decision_id": f"d{n}", "venue": "kalshi", "market_id": f"kalshi:M{n}",
                         "event_id": event, "outcome_cluster": cluster, "side": side, "filled_at_utc": at.isoformat(),
                         "status": "FILLED", "reason": "FILLED", "quantity": qty, "price": price,
                         "fee": str(cost.fee), "total_cost": str(cost.total_cost),
                         "expected_settlement_utc": None if settles is None else settles.isoformat()})
    return cost.total_cost


def settle(lg, n, outcome, at):
    # Evidence available at `at`, so the settlement's knowledge time is modeled, not the wall
    # clock: without it the ledger falls back to the later of `at` and the append time.
    lg.record_settlement(ACC, fill_id=f"f{n}", outcome=outcome, evidence={"evidence_available_utc": at.isoformat()},
                         settled_at_utc=at.isoformat())


# --------------------------------------------------------------------------- risk report


def test_fresh_account_has_full_capacity(ledger):
    r = assess(ledger.state(ACC), POLICY, T0)
    assert r.equity == r.settled_cash == Decimal("100.00") and r.committed_capital == 0
    # Tightest headroom: the 5.00 daily loss limit (portfolio 30, cash above reserve 80, weekly 10, drawdown 15).
    assert r.remaining_risk_capacity == Decimal("5") and r.new_risk_allowed and r.breaches == ()
    assert [b.horizon for b in r.capital_release] == list(HORIZONS)


def test_open_risk_per_position_event_and_cluster(ledger):
    a = open_position(ledger, 1, event="ev1", cluster="nyc")
    b = open_position(ledger, 2, qty=3, price="0.25", event="ev1", cluster="nyc")
    c = open_position(ledger, 3, event="ev2", cluster="btc")
    r = assess(ledger.state(ACC), POLICY, T0)
    assert r.risk_per_position == {"f1": a, "f2": b, "f3": c}
    assert r.risk_per_event == {"ev1": a + b, "ev2": c}
    assert r.cluster_exposure == {"btc": c, "nyc": a + b}
    assert r.open_worst_case_risk == r.total_portfolio_exposure == a + b + c == r.committed_capital
    assert r.remaining_risk_capacity == POLICY.daily_loss_limit - (a + b + c)


def test_capital_release_never_counts_winnings_as_cash(ledger):
    open_position(ledger, 1, settles=T0 + timedelta(minutes=30))
    open_position(ledger, 2, settles=T0 + timedelta(hours=10))
    open_position(ledger, 3, settles=T0 + timedelta(days=3))
    open_position(ledger, 4, settles=T0 + timedelta(days=30))
    open_position(ledger, 5, settles=None)  # unknown settlement time: locked, never "soon"
    r = assess(ledger.state(ACC), POLICY, T0)
    buckets = {b.horizon: b for b in r.capital_release}
    assert buckets["available_now"].committed_capital == buckets["available_now"].guaranteed_cash == r.settled_cash
    assert (buckets["within_1_hour"].positions, buckets["within_1_day"].positions,
            buckets["within_1_week"].positions, buckets["locked"].positions) == (1, 1, 1, 2)
    for name in HORIZONS[1:]:
        assert buckets[name].guaranteed_cash == 0  # a losing binary returns nothing
    assert buckets["within_1_hour"].best_case_payout == 1
    assert sum(b.committed_capital for b in r.capital_release[1:]) == r.committed_capital


def test_drawdown_daily_and_weekly_loss(ledger):
    for n in range(1, 4):
        open_position(ledger, n, qty=5, price="0.90", event=f"e{n}", cluster=f"c{n}")
    settle(ledger, 1, "YES", T0 + timedelta(days=1))       # win
    settle(ledger, 2, "NO", T0 + timedelta(days=5))        # loss (-4.xx)
    settle(ledger, 3, "NO", T0 + timedelta(days=6))        # loss
    state = ledger.state(ACC)
    curve = equity_curve(state)
    assert curve[0] == ("start", Decimal("100.00")) and len(curve) == 4
    r = assess(state, replace(POLICY, max_position_risk=Decimal("100"), max_event_risk=Decimal("100"),
                              max_cluster_risk=Decimal("100")), T0 + timedelta(days=6))
    p = {x.position_id: x for x in state.positions}
    assert r.peak_equity == Decimal("100.00") + p["f1"].net_pnl
    assert r.drawdown == r.peak_equity - r.equity
    assert r.daily_loss == -p["f3"].net_pnl
    assert r.weekly_loss == -(p["f1"].net_pnl + p["f2"].net_pnl + p["f3"].net_pnl)


def test_breaches_halt_new_risk(ledger):
    for n in range(1, 4):
        open_position(ledger, n, qty=5, price="0.90", event=f"e{n}", cluster=f"c{n}")
    settle(ledger, 2, "NO", T0 + timedelta(hours=2))
    settle(ledger, 3, "NO", T0 + timedelta(hours=3))
    r = assess(ledger.state(ACC), POLICY, T0 + timedelta(hours=4))
    assert "DAILY_LOSS_LIMIT" in r.breaches and not r.new_risk_allowed and r.remaining_risk_capacity == 0
    tight = replace(POLICY, max_position_risk=Decimal("1"), reserve_floor=Decimal("99"),
                    max_portfolio_risk=Decimal("1"), max_event_risk=Decimal("1"), max_cluster_risk=Decimal("1"))
    r = assess(ledger.state(ACC), tight, T0 + timedelta(hours=4))
    assert {"RESERVE_FLOOR", "MAX_POSITION_RISK", "MAX_EVENT_RISK", "MAX_CLUSTER_RISK",
            "MAX_PORTFOLIO_RISK"} <= set(r.breaches)


def test_reserve_floor_limits_capacity(ledger):
    r = assess(ledger.state(ACC), replace(POLICY, reserve_floor=Decimal("97")), T0)
    assert r.remaining_risk_capacity == Decimal("3.00")  # cash above the reserve binds


def test_report_is_deterministic_and_serializable(ledger):
    open_position(ledger, 1)
    a = assess(ledger.state(ACC), POLICY, T0).to_dict()
    b = assess(ShadowLedger(ledger.path).state(ACC), POLICY, T0).to_dict()
    assert a == b and a["capital_release"][0]["horizon"] == "available_now"
    with pytest.raises(ValueError):
        assess(ledger.state(ACC), POLICY, datetime(2026, 9, 23))
    with pytest.raises(ValueError):
        replace(POLICY, reserve_floor=Decimal("-1"))


# --------------------------------------------------------------------------- withdrawal contract


def test_withdrawal_contract_never_recommends_a_draw_yet(ledger):
    open_position(ledger, 1)
    state = ledger.state(ACC)
    w = withdrawal_assessment(state, assess(state, POLICY, T0))
    assert w.technically_withdrawable == state.settled_cash
    assert w.policy_safe_withdrawable == state.settled_cash - Decimal("20")
    assert w.recommended_owner_draw is None and w.recommendation_status == "NOT_RECOMMENDED"
    assert {"SHADOW_ACCOUNT: no real money exists", "EDGE_NOT_VERIFIED", "FEE_SCHEDULE_UNVERIFIED",
            "NO_OWNER_APPROVED_WITHDRAWAL_POLICY"} <= set(w.reasons)
    everything = withdrawal_assessment(state, assess(state, POLICY, T0), simulation=False, edge_verified=True,
                                       fee_claim_basis="EXACT", owner_policy_approved=True)
    assert everything.recommended_owner_draw is None and everything.reasons == ("DRAW_FORMULA_NOT_DEFINED",)


def test_policy_safe_withdrawal_is_zero_during_a_breach(ledger):
    state = ledger.state(ACC)
    report = assess(state, replace(POLICY, reserve_floor=Decimal("150")), T0)
    w = withdrawal_assessment(state, report)
    assert "RESERVE_FLOOR" in report.breaches and w.policy_safe_withdrawable == 0
    assert w.technically_withdrawable == Decimal("100.00")


# --------------------------------------------------------------------------- Outcome Board


def test_board_groups_by_outcome_and_ranks_by_account_impact(ledger):
    open_position(ledger, 1, qty=2, price="0.40", event="nyc-hi", cluster="weather:nyc:2026-09-24")
    open_position(ledger, 2, qty=1, price="0.30", side="NO", event="nyc-hi", cluster="weather:nyc:2026-09-24")
    open_position(ledger, 3, qty=10, price="0.10", event="btc", cluster="crypto:btc:2026-09-24",
                  settles=T0 + timedelta(minutes=30))
    board = build_board(ledger.state(ACC), T0)
    assert [g.outcome_cluster for g in board] == ["crypto:btc:2026-09-24", "weather:nyc:2026-09-24"]
    btc, nyc = board
    assert btc.max_account_gain == 10 - btc.current_exposure and btc.account_impact == btc.max_account_gain
    assert btc.horizon == "within_1_hour" and btc.status == "OPEN"
    assert len(nyc.positions) == 2 and nyc.event_ids == ("nyc-hi",)
    assert nyc.max_account_loss == nyc.current_exposure and nyc.worst_case_method == WORST_CASE_METHOD
    assert nyc.horizon == "within_1_day"


def test_board_status_and_settled_groups(ledger):
    open_position(ledger, 1, cluster="c1")
    open_position(ledger, 2, cluster="c1")
    open_position(ledger, 3, cluster="c2")
    settle(ledger, 1, "YES", T0 + timedelta(hours=1))
    settle(ledger, 3, "NO", T0 + timedelta(hours=1))
    state = ledger.state(ACC)
    board = build_board(state, T0 + timedelta(hours=2))
    assert [g.outcome_cluster for g in board] == ["c1"] and board[0].status == "PARTIALLY_SETTLED"
    assert board[0].realized_pnl == next(p.net_pnl for p in state.positions if p.position_id == "f1")
    full = {g.outcome_cluster: g for g in build_board(state, T0 + timedelta(hours=2), include_settled=True)}
    assert full["c2"].status == "SETTLED" and full["c2"].horizon == "settled" and full["c2"].account_impact == 0


def test_board_unknown_settlement_time_and_determinism(ledger):
    open_position(ledger, 1, cluster="c1", settles=None)
    board = build_board(ledger.state(ACC), T0)
    assert board[0].settles_by_utc is None and board[0].horizon == "unknown"
    assert [g.to_dict() for g in board] == [g.to_dict() for g in build_board(ShadowLedger(ledger.path).state(ACC), T0)]


def test_cli_shadow_risk(ledger, tmp_path, capsys, monkeypatch):
    import json
    from edge_lab import cli, exp001_shadow
    lg = ShadowLedger(tmp_path / "exp.sqlite3")
    exp001_shadow.ensure_account(lg)
    assert cli.main(["shadow", "risk", "--ledger", str(lg.path), "--as-of", T0.isoformat()]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["risk"]["policy_id"] == "EXP-001-shadow-risk-v1" and out["risk"]["new_risk_allowed"] is True
    assert out["withdrawal"]["recommended_owner_draw"] is None and out["outcome_board"] == []
    assert cli.main(["shadow", "risk", "--ledger", str(lg.path), "--as-of", "yesterday"]) == 2
    assert cli.main(["shadow", "risk", "--ledger", str(tmp_path / "none.sqlite3")]) == 2


# --------------------------------------------------------------------------- review hardening


def test_capacity_respects_loss_and_drawdown_headroom(ledger):
    open_position(ledger, 1, qty=5, price="0.80", event="e1", cluster="c1")  # cost 4.07
    settle(ledger, 1, "NO", T0 + timedelta(hours=1))  # realized loss 4.07 of a 5.00 daily limit
    # Filled after the loss was known: fills must follow cash movements in knowledge time.
    open_position(ledger, 2, qty=1, price="0.20", event="e2", cluster="c2", at=T0 + timedelta(minutes=90))
    r = assess(ledger.state(ACC), POLICY, T0 + timedelta(hours=2))
    assert r.breaches == () and r.new_risk_allowed
    daily_headroom = POLICY.daily_loss_limit - r.daily_loss - r.open_worst_case_risk
    assert r.remaining_risk_capacity == daily_headroom < Decimal("1")


def test_overdue_positions_are_locked_not_releasing(ledger):
    open_position(ledger, 1, settles=T0 - timedelta(days=2))
    r = assess(ledger.state(ACC), POLICY, T0)
    buckets = {b.horizon: b for b in r.capital_release}
    assert buckets["locked"].positions == 1 and buckets["within_1_hour"].positions == 0
    assert build_board(ledger.state(ACC), T0)[0].horizon == "overdue"


def test_settle_helper_knowledge_time_is_modeled_not_the_wall_clock(ledger):
    # Guard for the fixture: fixed-T0 tests must not depend on when the suite runs.
    open_position(ledger, 1)
    settle(ledger, 1, "YES", T0 + timedelta(hours=1))
    row = next(r for r in ledger.entries(ACC) if r["kind"] == "settlement")
    assert knowledge_time(row) == T0 + timedelta(hours=1)


def test_as_of_before_ledger_activity_is_refused(ledger, tmp_path, capsys):
    open_position(ledger, 1)
    settle(ledger, 1, "YES", T0 + timedelta(hours=5))
    with pytest.raises(ValueError, match="point-in-time"):
        assess(ledger.state(ACC), POLICY, T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="point-in-time"):
        build_board(ledger.state(ACC), T0)
    from edge_lab.risk import capital_release
    with pytest.raises(ValueError):
        capital_release(ledger.state(ACC), datetime(2026, 9, 23))


def test_board_keeps_known_times_with_unknown_ones_and_labels_gain(ledger):
    open_position(ledger, 1, cluster="c1", settles=None)
    open_position(ledger, 2, cluster="c1", settles=T0 + timedelta(hours=3))
    g = build_board(ledger.state(ACC), T0)[0]
    assert g.settles_by_utc == (T0 + timedelta(hours=3)).isoformat() and g.unknown_settlement_positions == 1
    assert "upper bound" in g.best_case_method
