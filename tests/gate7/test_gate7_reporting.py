"""Gate 7 D — reporting: cost-basis equity, no hypothetical cash, locked horizons, and
outcome-board bounds that are labelled as upper bounds, not attainable scenarios.

Behaviour pinned by this regression test (written as a strict xfail before the fix) (coordinator fix 4): fill and settlement payloads
carry `fee_schedule_id`, `fee_status` and `claimable` (false while the schedule is
UNVERIFIED_CURRENT_SCHEDULE).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import exp001_shadow as shadow
from edge_lab import settlement
from edge_lab.outcome_board import BEST_CASE_METHOD, WORST_CASE_METHOD, build_board
from edge_lab.risk import HORIZONS, assess, withdrawal_assessment

from test_forward import D, MARKETS

from gate7.gate7_support import CLOSED, D_CLUSTER, OPS, day_fills, seed, settled_copy, store_settled_markets

UTC = timezone.utc


@pytest.fixture
def traded(full_day, ledger, model):
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    return full_day, ledger


def test_equity_is_cost_basis_with_no_liquidation_mark(traded):
    _, ledger = traded
    state = ledger.state(OPS)
    assert state.fills == 3
    cost = sum(p.cost_basis for p in state.positions)
    # The re-check books offered the same prices; no mark-to-market moves equity before settlement.
    assert state.equity == shadow.STARTING_BANKROLL and state.realized_pnl == 0
    assert state.settled_cash == shadow.STARTING_BANKROLL - cost and state.committed_capital == cost
    assert "unrealized" not in json.dumps(state.to_dict()).lower()


def test_hypothetical_winnings_are_never_cash_before_settlement(traded):
    _, ledger = traded
    state = ledger.state(OPS)
    r = assess(state, shadow.RISK_POLICY, CLOSED)
    buckets = {b.horizon: b for b in r.capital_release}
    assert [b.horizon for b in r.capital_release] == list(HORIZONS)
    assert buckets["available_now"].guaranteed_cash == state.settled_cash
    assert all(buckets[h].guaranteed_cash == 0 for h in HORIZONS[1:])
    assert sum(b.best_case_payout for b in r.capital_release) == state.open_potential_payout == 3
    w = withdrawal_assessment(state, r)
    assert w.technically_withdrawable == state.settled_cash  # the 3.00 best case is not withdrawable
    assert w.recommended_owner_draw is None and w.recommendation_status == "NOT_RECOMMENDED"
    assert r.settled_cash + r.committed_capital == r.equity  # never settled cash + potential payout


def test_unknown_and_overdue_settlement_horizons_stay_locked(traded):
    _, ledger = traded
    state = ledger.state(OPS)
    expected = datetime(2026, 9, 24, 22, 0, tzinfo=UTC)  # decision + 2 days
    horizons = {}
    for as_of in (CLOSED, expected - timedelta(hours=1), expected, expected + timedelta(microseconds=1)):
        buckets = {b.horizon: b.positions for b in assess(state, shadow.RISK_POLICY, as_of).capital_release}
        horizons[as_of] = next(h for h in HORIZONS[1:] if buckets[h])
        board = build_board(state, as_of)
        assert len(board) == 1 and board[0].outcome_cluster == D_CLUSTER
    assert list(horizons.values()) == ["within_1_week", "within_1_hour", "within_1_hour", "locked"]
    assert build_board(state, expected + timedelta(hours=1))[0].horizon == "overdue"
    # A position with no expected settlement time is locked and 'unknown', never 'soon'.
    seed(ledger, OPS, "nodate", price="0.40", filled_at=CLOSED, event="weather:seed-nodate",
         cluster="weather:seed-nodate", expected_settlement=None)
    later = ledger.state(OPS)
    buckets = {b.horizon: b for b in assess(later, shadow.RISK_POLICY, CLOSED).capital_release}
    assert buckets["locked"].positions == 1 and buckets["locked"].guaranteed_cash == 0
    nodate = next(g for g in build_board(later, CLOSED) if g.outcome_cluster == "weather:seed-nodate")
    assert nodate.horizon == "unknown" and nodate.unknown_settlement_positions == 1


def test_board_bounds_are_upper_bounds_and_labelled(traded):
    _, ledger = traded
    state = ledger.state(OPS)
    [group] = build_board(state, CLOSED)
    assert "upper bound" in group.worst_case_method and "upper bound" in group.best_case_method
    assert group.worst_case_method == WORST_CASE_METHOD and group.best_case_method == BEST_CASE_METHOD
    # Enumerate every integer outcome: B67.5 YES and B65.5 YES are mutually exclusive, so the
    # summed best case (both win) is not attainable; the board must not be read as a scenario.
    raw = {f"kalshi:{m['ticker']}": m for m in MARKETS["markets"]}
    scenarios = []
    for y in range(30, 111):
        pnl = Decimal(0)
        for p in state.positions:
            yes = settlement.resolve(raw[p.market_id], y).outcome is settlement.Outcome.YES
            pnl += (Decimal(p.quantity) if yes == (p.side == "YES") else Decimal(0)) - p.cost_basis
        scenarios.append(pnl)
    assert group.max_account_gain >= max(scenarios) and group.max_account_loss >= -min(scenarios)
    assert group.max_account_gain > max(scenarios)  # strictly loose here: not an attainable outcome


def test_fill_and_settlement_payloads_carry_fee_status(traded):
    store, ledger = traded
    store_settled_markets(store, settled_copy(MARKETS["markets"], 67), run_id="settle",
                          fetched_at="2026-09-24T14:00:00+00:00")
    shadow.settle_open_positions(store, ledger)
    rows = [json.loads(r["payload_json"]) for r in ledger.entries(OPS) if r["kind"] in ("fill", "settlement")]
    assert len(rows) == 6
    for payload in rows:
        assert payload["fee_schedule_id"] == "kalshi-quadratic-taker-v1"
        assert payload["fee_status"] == "UNVERIFIED_CURRENT_SCHEDULE"
        assert payload["claimable"] is False


def test_settlement_pnl_comes_from_the_fill_not_the_evidence(traded):
    store, ledger = traded
    store_settled_markets(store, settled_copy(MARKETS["markets"], 67), run_id="settle",
                          fetched_at="2026-09-24T14:00:00+00:00")
    shadow.settle_open_positions(store, ledger)
    state = ledger.state(OPS)
    fills = {f["fill_id"]: f for f in day_fills(ledger)}
    for p in state.positions:
        assert p.net_pnl == (p.payout or 0) - Decimal(fills[p.position_id]["total_cost"])
    assert state.equity == state.settled_cash == shadow.STARTING_BANKROLL + state.realized_pnl
