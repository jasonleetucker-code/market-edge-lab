"""Pure HOLD / REDUCE / EXIT evaluator (#122 §15, §23 in-play cases)."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from edge_lab import position_policy as pp
from edge_lab.execution_ticket import OrderState
from edge_lab.fee_schedules import ClaimBasis, FeeScheduleStatus, QuadraticTakerSchedule
from edge_lab.inplay_evidence import BookStatus, DataKind, TradingState
from edge_lab.position_policy import Action, DecisionStatus, ExecutionAssumption, PolicyKind

NOW = datetime(2026, 10, 4, 18, 30, tzinfo=timezone.utc)
MKT = "kalshi:KXNFLGAME-FIXTURE-HOME"

# A FIXTURE fee model built on the canonical schedule class (no fee formula copied): the 0.07
# quadratic shape of the general Kalshi schedule. KXNFLGAME's own fee is unverified (Kalshi Q7),
# so this model's claim basis is NONE: numbers are computable, no after-cost claim rests on them.
FIXTURE_SCHEDULE = QuadraticTakerSchedule(
    schedule_id="fixture-quadratic-0.07", venue="kalshi", coefficient=D("0.07"), multiplier=D("1"),
    status=FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE, evidence="FIXTURE: test double",
    checked_at_utc="2026-09-28T00:00:00Z")
FIXTURE_FEES = pp.ScheduleFeeModel("fixture-quadratic-0.07", FIXTURE_SCHEDULE, ClaimBasis.NONE)


def inv(qty="100", initial="100", *, age=timedelta(0), kind=pp.InventoryKind.SIMULATED):
    return pp.Inventory(MKT, "YES", D(qty), D(initial), kind, (NOW - age).isoformat(), "fixture:inv",
                        entry_cost=D("31.47"))


def book(bids, *, age=timedelta(seconds=1), status=BookStatus.VALID, state=TradingState.OPEN, truncated=False):
    return pp.SaleBook(MKT, "YES", tuple((D(p), D(s)) for p, s in bids), truncated, status, state,
                       (NOW - age).isoformat(), "fixture:book", DataKind.FIXTURE)


def policy(kind=PolicyKind.FIXED_TARGET_FULL_EXIT, execution=ExecutionAssumption.BOT_TRIGGERED_IOC, target="0.70",
           fraction=None, **kw):
    return pp.PositionPolicy("fixture-policy", "1", kind, execution,
                             target_price=None if target is None else D(target),
                             exit_fraction=None if fraction is None else D(fraction), **kw)


def order(remaining, *, origin=pp.OrderOrigin.NATIVE_AUTO_SELL, state=OrderState.RESTING, cancel=False, oid="o1"):
    return pp.RestingOrder(oid, origin, MKT, "YES", True, D(remaining), D("0.80"), state, cancel_requested=cancel)


def run(**kw):
    args = dict(as_of=NOW, inventory=inv(), orders=(), book=book([("0.70", "100")]), fee_model=FIXTURE_FEES,
                policy=policy(), rules_version="rules-sha-fixture")
    args.update(kw)
    return pp.evaluate(**args)


# ------------------------------------------------------------------ arithmetic


def test_30c_entry_70c_filled_exit_arithmetic_with_fees():
    d = run()
    assert d.status is DecisionStatus.PROPOSED and d.action is Action.EXIT and d.quantity == D("100")
    assert d.gross_proceeds == D("70.00")
    assert d.fee == D("1.470000")  # ceil_6dp(0.07 x 100 x 0.70 x 0.30)
    assert d.net_proceeds == D("68.530000")  # proceeds, not profit: entry cost stays in accounting
    assert d.fee_claim_basis == "NONE"  # fixture fee: computable, not claimable
    assert d.execution is ExecutionAssumption.BOT_TRIGGERED_IOC and d.limit_price == D("0.70")
    assert not d.authorizes_execution and d.no_new_risk


def test_sale_walk_prices_each_level_with_its_own_fee():
    d = run(book=book([("0.70", "60"), ("0.75", "40")]))
    assert d.gross_proceeds == D("0.75") * 40 + D("0.70") * 60
    assert d.fee == FIXTURE_SCHEDULE.taker_buy(40, D("0.75")).fee + FIXTURE_SCHEDULE.taker_buy(60, D("0.70")).fee


# ------------------------------------------------------------------ target not reached / not executable


def test_target_never_reached_holds():
    d = run(book=book([("0.65", "500")]))
    assert d.status is DecisionStatus.PROPOSED and d.action is Action.HOLD and d.quantity == 0
    assert d.reasons[0].startswith("TARGET_NOT_EXECUTABLE")


def test_displayed_target_without_an_executable_bid_holds():
    # a chart or last trade at 0.70 is not a bid: an empty bid side is not a price
    d = run(book=book([]))
    assert d.action is Action.HOLD and d.reasons[0].startswith("NO_BID")


def test_truncated_depth_bounds_the_quantity_and_says_so():
    d = run(book=book([("0.60", "500"), ("0.70", "30")], truncated=True))
    assert d.action is Action.REDUCE and d.quantity == D("30")
    assert any(r.startswith("DEPTH_LIMITED") and "not captured" in r for r in d.reasons)


# ------------------------------------------------------------------ bad data blocks and never liquidates


@pytest.mark.parametrize("bk,reason", [
    (None, "BOOK_MISSING"),
    ("stale", "BOOK_STALE"),
    ("gap", "BOOK_UNUSABLE: GAP_AWAITING_RESYNC"),
    ("nostart", "BOOK_UNUSABLE: NO_VALID_START"),
    ("paused", "MARKET_NOT_TRADING: TRADING_PAUSED"),
    ("exchange", "MARKET_NOT_TRADING: EXCHANGE_PAUSED"),
    ("future", "BOOK_STALE"),
])
def test_stale_gapped_or_paused_books_block_and_never_exit(bk, reason):
    b = {None: None,
         "stale": book([("0.90", "500")], age=timedelta(minutes=5)),
         "gap": book([("0.90", "500")], status=BookStatus.GAP_AWAITING_RESYNC),
         "nostart": book([], status=BookStatus.NO_VALID_START),
         "paused": book([("0.90", "500")], state=TradingState.TRADING_PAUSED),
         "exchange": book([("0.90", "500")], state=TradingState.EXCHANGE_PAUSED),
         "future": book([("0.90", "500")], age=-timedelta(seconds=5))}[bk]
    d = run(book=b)
    assert d.status is DecisionStatus.BLOCKED and d.action is None and d.quantity == 0
    assert d.no_new_risk and d.review_required
    assert any(r.startswith(reason) for r in d.reasons), d.reasons


def test_inventory_unknown_or_stale_blocks():
    assert run(inventory=None).status is DecisionStatus.BLOCKED
    d = run(inventory=inv(age=timedelta(hours=1)))
    assert d.status is DecisionStatus.BLOCKED and d.reasons[0].startswith("INVENTORY_STALE")
    bad = pp.Inventory(MKT, "YES", D("100.005"), D("100"), pp.InventoryKind.SIMULATED, NOW.isoformat(), "x")
    assert run(inventory=bad).reasons == ("INVENTORY_UNKNOWN",)


def test_unpinned_rules_block():
    d = run(rules_version=None)
    assert d.status is DecisionStatus.BLOCKED and d.reasons[0].startswith("RULES_VERSION_UNKNOWN")


def test_required_game_state_missing_or_stale_blocks():
    p = policy(requires_game_state=True)
    assert run(policy=p).reasons == ("GAME_STATE_MISSING_OR_STALE",)
    old = pp.GameStateInput((NOW - timedelta(minutes=2)).isoformat())
    assert run(policy=p, game_state=old).status is DecisionStatus.BLOCKED
    fresh = pp.GameStateInput(NOW.isoformat())
    assert run(policy=p, game_state=fresh).action is Action.EXIT


# ------------------------------------------------------------------ inventory reservation and competing exits


def test_native_auto_sell_reserves_inventory_so_the_bot_sells_only_the_rest():
    d = run(orders=(order("60"),))
    assert d.action is Action.REDUCE and d.quantity == D("40")
    assert d.provenance["reserved"] == "60" and d.provenance["available"] == "40"


def test_fully_reserved_inventory_holds():
    d = run(orders=(order("100"),))
    assert d.action is Action.HOLD and d.reasons[0].startswith("NOTHING_LEFT_TO_SELL")


def test_manual_sale_under_a_resting_auto_sell_is_over_reserved_and_blocks():
    # the owner sold 50 by hand; the app's Auto Sell for 60 still rests: selling more could open NO exposure
    d = run(inventory=inv("50"), orders=(order("60"),))
    assert d.status is DecisionStatus.BLOCKED and d.reasons[0].startswith("OVER_RESERVED")


def test_cancel_request_releases_nothing():
    d = run(orders=(order("100", cancel=True),))
    assert d.action is Action.HOLD and d.provenance["reserved"] == "100"


@pytest.mark.parametrize("state", [OrderState.PENDING, OrderState.OUTCOME_UNKNOWN])
def test_unreconciled_orders_block_new_sales(state):
    d = run(orders=(order("10", origin=pp.OrderOrigin.BOT, state=state),))
    assert d.status is DecisionStatus.BLOCKED and d.reasons[0].startswith("ORDER_UNRECONCILED")


def test_filled_and_cancelled_orders_reserve_nothing():
    d = run(orders=(order("0", state=OrderState.FILLED), order("50", state=OrderState.CANCELLED, oid="o2")))
    assert d.action is Action.EXIT and d.quantity == D("100")


def test_repeated_calls_do_not_duplicate_a_preplaced_sale():
    p = policy(execution=ExecutionAssumption.PREPLACED_RESTING_LIMIT)
    first = run(policy=p, book=book([("0.50", "100")]))
    assert first.action is Action.EXIT and first.quantity == D("100") and first.gross_proceeds is None
    assert any(r.startswith("NOT_REDUCE_ONLY") for r in first.reasons)
    placed = order("100", origin=pp.OrderOrigin.BOT)
    again = run(policy=p, book=book([("0.50", "100")]), orders=(placed,))
    assert again.action is Action.HOLD and again.quantity == 0


def test_same_inputs_same_decision_id():
    assert run().decision_id == run().decision_id
    assert run().decision_id != run(book=book([("0.71", "100")])).decision_id


# ------------------------------------------------------------------ partial exits


def test_partial_exit_sells_the_predefined_fraction_once():
    p = policy(PolicyKind.FIXED_TARGET_PARTIAL_EXIT, fraction="0.5")
    first = run(policy=p)
    assert first.action is Action.REDUCE and first.quantity == D("50")
    after = run(policy=p, inventory=inv("50"))
    assert after.action is Action.HOLD and after.quantity == 0
    odd = run(policy=p, inventory=inv("33", "33"))
    assert odd.quantity == D("16")  # floored to whole contracts, never rounded up


# ------------------------------------------------------------------ fees


def test_missing_fees_leave_gross_as_a_labelled_diagnostic():
    unknown = pp.UnknownFeeModel("unsupported:kalshi:KXNFLGAME", "non-standard series")
    d = run(fee_model=unknown)
    assert d.action is Action.EXIT and d.gross_proceeds == D("70.00")
    assert d.fee is None and d.net_proceeds is None and d.fee_claim_basis == "NONE"
    assert any(r.startswith("FEE_UNKNOWN") for r in d.reasons)
    assert run(fee_model=None).net_proceeds is None


def test_fractional_contracts_have_no_modelled_fee():
    assert FIXTURE_FEES.sale_fee(D("1.5"), D("0.70")) is None


def test_nfl_game_fees_are_unknown_today_and_weather_fees_route_to_the_schedule():
    nfl = pp.fee_model_for("kalshi", "KXNFLGAME-26OCT04BUFNYJ-BUF", "2026-10-04T18:00:00Z")
    assert isinstance(nfl, pp.UnknownFeeModel) and nfl.claim_basis is ClaimBasis.NONE
    weather = pp.fee_model_for("kalshi", "KXHIGHNY-26OCT04-B70.5", "2026-10-04T18:00:00Z")
    assert isinstance(weather, pp.ScheduleFeeModel) and weather.sale_fee(D("100"), D("0.70")) == D("1.470000")


# ------------------------------------------------------------------ what it will not do


@pytest.mark.parametrize("kind", [PolicyKind.FAIR_VALUE, PolicyKind.REENTER, PolicyKind.ADD])
def test_fair_value_reentry_and_add_are_unsupported(kind):
    d = run(policy=policy(kind))
    assert d.status is DecisionStatus.UNSUPPORTED and d.action is None and d.quantity == 0


@pytest.mark.parametrize("target", ["70", "0", "1", "0.70001"])
def test_target_in_the_wrong_unit_is_refused(target):
    d = run(policy=policy(target=target))
    assert d.status is DecisionStatus.UNSUPPORTED and d.reasons[0].startswith("POLICY_INVALID")


def test_no_probability_input_and_no_way_to_authorize():
    params = set(inspect.signature(pp.evaluate).parameters)
    assert not {p for p in params if "prob" in p or "fair" in p or "model" in p and p != "fee_model"}
    with pytest.raises(ValueError):
        pp.PolicyDecision("x", DecisionStatus.PROPOSED, Action.HOLD, D(0), None, (), ExecutionAssumption.NONE,
                          None, None, None, "NONE", True, False, {}, authorizes_execution=True)
    with pytest.raises(ValueError):
        pp.PolicyDecision("x", DecisionStatus.PROPOSED, Action.ADD, D(0), None, (), ExecutionAssumption.NONE,
                          None, None, None, "NONE", True, False, {})


def test_hold_to_settlement_needs_no_book_and_zero_inventory_is_no_position():
    d = run(policy=policy(PolicyKind.HOLD_TO_SETTLEMENT, ExecutionAssumption.NONE, target=None), book=None)
    assert d.action is Action.HOLD and d.status is DecisionStatus.PROPOSED
    assert run(inventory=inv("0")).status is DecisionStatus.NO_POSITION
