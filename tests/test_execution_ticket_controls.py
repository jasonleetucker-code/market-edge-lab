"""Pre-submit control chain for the future execution ticket (flumine-derived checklist, ideas only).

Execution stays disabled: the chain always ends in EXECUTION_NOT_AUTHORIZED, so no ticket
can come out of it clean.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import fields, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from edge_lab import execution_ticket as et, venues
from edge_lab.execution_ticket import (
    ORDER_TRANSITIONS, TICKET_TRANSITIONS, ActionMode, Control as C, OrderRecord, OrderState, TicketLimits,
    TicketStatus, draft_ticket, pre_submit_checks, transition,
)
from edge_lab.opportunity import MarketStatus, PriceGrid, PriceRange
from edge_lab.risk import RiskPolicy, RiskReport
from test_opportunity import AS_OF, EVENT, MARKET, quote, run
from test_venues_and_tickets import _eligible_verdict

E = C.EXECUTION_NOT_AUTHORIZED
NOW = AS_OF + timedelta(seconds=30)
LIMITS = TicketLimits(max_book_age=timedelta(minutes=5), max_order_state_age=timedelta(seconds=10),
                      max_orders_per_window=5, order_window=timedelta(hours=1), market_cooldown=timedelta(minutes=1))
POLICY = RiskPolicy("test-risk", reserve_floor=Decimal(0), max_position_risk=Decimal(10), max_event_risk=Decimal(10),
                    max_cluster_risk=Decimal(10), max_portfolio_risk=Decimal(10), daily_loss_limit=Decimal(10),
                    weekly_loss_limit=Decimal(10), max_drawdown=Decimal(10))
CLUSTER = EVENT.outcome_cluster


def ticket(opp=None, **kw):
    opp = opp or run()
    at = datetime.fromisoformat(opp.as_of_utc)
    args = dict(venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at), action_mode=ActionMode.SIMULATION,
                now=at, ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    args.update(kw)
    return draft_ticket(opp, **args)


def fresh(received=AS_OF + timedelta(seconds=10), **kw):
    """A re-check quote captured after the ticket was created."""
    return quote(received=received, **kw)


def order(state=OrderState.FILLED, loss=Decimal(1), market_id=MARKET.market_id, event_id=EVENT.event_id,
          cluster=CLUSTER, side="YES", created=NOW - timedelta(hours=2), ticket_id="tkt-other"):
    return OrderRecord(ticket_id, market_id, event_id, cluster, side, state, loss,
                       None if created is None else created.isoformat())


def report(**kw):
    base = {f.name: Decimal(0) for f in fields(RiskReport)}
    base.update(account_id="acct", as_of_utc=NOW.isoformat(), policy_id=POLICY.policy_id, risk_per_position={},
                risk_per_event={}, cluster_exposure={}, capital_release=(), breaches=(), new_risk_allowed=True,
                remaining_risk_capacity=Decimal(5), notes=())
    base.update(kw)
    return RiskReport(**base)


def check(t=None, **kw):
    now = kw.pop("now", NOW)
    args = dict(market=MARKET, quote=fresh(), order_state_as_of_utc=now.isoformat(), orders=(), limits=LIMITS,
                risk_policy=POLICY)
    args.update(kw)
    return [v.control for v in pre_submit_checks(t or ticket(), now=now, **args)]


def test_a_clean_ticket_still_fails_execution_not_authorized_and_nothing_else():
    t = ticket()
    assert t.status is TicketStatus.DRAFT and t.event_id == EVENT.event_id and t.outcome_cluster == CLUSTER, t.reasons
    assert check(t) == [E]
    assert check(t, risk_report=report()) == [E]


GRID_TENTHS = PriceGrid((PriceRange(Decimal("0.1"), Decimal("0.9"), Decimal("0.1")),), "test tenths")
BAD_LOSSES = [None, Decimal("-1"), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), 1.0, "1"]
T = lambda **kw: (lambda t: replace(t, **kw))  # noqa: E731  ticket mutation
K = lambda **kw: (lambda t: t, kw)  # noqa: E731  context mutation (ticket unchanged)

CASES = [
    ((T(status=TicketStatus.REJECTED), {}), [C.TICKET_NOT_DRAFT]),
    (K(now=AS_OF + timedelta(minutes=2)), [C.TICKET_EXPIRED]),  # exactly at expiry is expired
    ((T(quantity=0), {}), [C.QTY_INVALID]),
    ((T(quantity=True), {}), [C.QTY_INVALID]),
    ((T(quantity=1.0), {}), [C.QTY_INVALID]),
    ((T(quantity="1"), {}), [C.QTY_INVALID]),
    ((T(limit_price=0.48), {}), [C.PRICE_INVALID, C.QUOTE_CHANGED]),  # a float is refused
    ((T(limit_price=Decimal("1")), {}), [C.PRICE_INVALID, C.QUOTE_CHANGED]),
    ((T(limit_price=Decimal("0.48005")), {}), [C.PRICE_INVALID, C.QUOTE_CHANGED]),
    ((T(limit_price=None), {}), [C.PRICE_INVALID, C.QUOTE_CHANGED]),
    (K(price_grid=GRID_TENTHS), [C.PRICE_OFF_GRID]),
    (K(market=replace(MARKET, price_grid=GRID_TENTHS)), [C.PRICE_OFF_GRID]),  # the market's own grid
    ((T(max_loss=Decimal("0.47")), {}), [C.MAX_LOSS_UNDERSTATED]),
    (K(market=None), [C.MARKET_UNKNOWN]),
    (K(market=replace(MARKET, market_id="kalshi:OTHER")), [C.MARKET_UNKNOWN]),
    (K(market=replace(MARKET, status=MarketStatus.CLOSED)), [C.MARKET_NOT_OPEN]),
    (K(market=replace(MARKET, status=MarketStatus.UNKNOWN)), [C.MARKET_NOT_OPEN]),
    (K(quote=None), [C.BOOK_MISSING]),
    (K(quote=fresh(side="NO")), [C.BOOK_MISSING]),
    (K(quote=fresh(ask=None)), [C.BOOK_MISSING]),
    (K(quote=fresh(anomaly="crossed")), [C.BOOK_MISSING]),
    (K(quote=fresh(received=None)), [C.BOOK_STALE]),
    (K(quote=fresh(received=NOW - timedelta(minutes=6))), [C.BOOK_STALE]),
    (K(quote=fresh(received=NOW + timedelta(seconds=1))), [C.BOOK_STALE]),  # future: no skew allowance
    (K(quote=quote()), [C.BOOK_STALE]),  # the pricing quote itself predates the ticket
    (K(quote=fresh(ask="0.49")), [C.QUOTE_CHANGED]),
    (K(quote=fresh(ask="0.47")), [C.QUOTE_CHANGED]),  # any move re-prices
    (K(quote=fresh(size="0.5")), [C.QUOTE_CHANGED]),
    (K(quote=fresh(size=None)), [C.QUOTE_CHANGED]),
    (K(order_state_as_of_utc=None), [C.ORDER_STATE_UNHEALTHY]),
    (K(order_state_as_of_utc=(NOW - timedelta(seconds=11)).isoformat()), [C.ORDER_STATE_UNHEALTHY]),
    (K(order_state_as_of_utc=(NOW + timedelta(seconds=1)).isoformat()), [C.ORDER_STATE_UNHEALTHY]),
    (K(orders=(order(created=None),)), [C.ORDER_TIME_UNKNOWN]),
    (K(orders=(order(created=None, market_id="kalshi:OTHER"),)), [C.ORDER_TIME_UNKNOWN]),
    (K(orders=(order(OrderState.RESTING),)), [C.DUPLICATE_OPEN_ORDER]),
    (K(risk_report=report(new_risk_allowed=False, breaches=("MAX_DRAWDOWN",))), [C.RISK_REPORT_BLOCKS]),
    (K(risk_report=report(new_risk_allowed=False, remaining_risk_capacity=Decimal(0))), [C.RISK_REPORT_BLOCKS]),
    (K(risk_report=report(remaining_risk_capacity=Decimal("0.1"))), [C.RISK_REPORT_BLOCKS]),
    (K(risk_report=report(as_of_utc=(NOW - timedelta(minutes=1)).isoformat())), [C.RISK_REPORT_BLOCKS]),
    (K(risk_report=report(policy_id="another-policy")), [C.RISK_REPORT_BLOCKS]),
    ((T(event_id=None), {}), [C.EXPOSURE_UNKNOWN]),
    ((T(outcome_cluster=None), {}), [C.EXPOSURE_UNKNOWN]),
    (K(orders=(order(event_id=None),)), [C.EXPOSURE_UNKNOWN]),  # missing is not "another event"
    (K(orders=(order(event_id=""),)), [C.EXPOSURE_UNKNOWN]),
    (K(orders=(order(cluster=None),)), [C.EXPOSURE_UNKNOWN]),
    (K(orders=(order(created=NOW - timedelta(seconds=30)),)), [C.COOLDOWN_ACTIVE]),
    *[(K(orders=(order(loss=bad),)), [C.EXPOSURE_UNKNOWN]) for bad in BAD_LOSSES],
    *[((T(max_loss=bad), {}), [C.EXPOSURE_UNKNOWN]) for bad in BAD_LOSSES],
]


@pytest.mark.parametrize("case, expected", CASES, ids=[str(i) for i in range(len(CASES))])
def test_each_control_fails_closed_with_the_full_violation_list(case, expected):
    mutate, kw = case
    t = mutate(ticket())
    assert check(t, **kw) == expected + [E]


def test_duplicate_ticket_is_named():
    t = ticket()
    assert check(t, orders=(order(ticket_id=t.ticket_id),)) == [C.DUPLICATE_TICKET, E]


def test_every_failure_is_listed_in_evaluation_order():
    got = check(replace(ticket(), quantity=0), market=None, quote=None, order_state_as_of_utc=None)
    assert got == [C.QTY_INVALID, C.MARKET_UNKNOWN, C.BOOK_MISSING, C.ORDER_STATE_UNHEALTHY, E]
    assert got == sorted(got, key=list(C).index)


def test_on_grid_price_passes():
    grid = PriceGrid((PriceRange(Decimal("0.01"), Decimal("0.99"), Decimal("0.01")),), "test cents")
    assert check(price_grid=grid) == [E]
    assert check(market=replace(MARKET, price_grid=grid)) == [E]


def test_boundaries_are_explicit():
    long = ticket(ttl=timedelta(minutes=10))
    at = AS_OF + timedelta(minutes=6)
    assert check(ticket(), now=AS_OF + timedelta(minutes=2) - timedelta(microseconds=1)) == [E]
    assert check(long, now=at, quote=fresh(received=at - timedelta(minutes=5))) == [E]  # exactly max_book_age
    assert check(long, now=at, quote=fresh(received=at - timedelta(minutes=5, microseconds=1))) == [C.BOOK_STALE, E]
    assert check(quote=fresh(received=AS_OF)) == [E]  # received exactly at creation is not "before"
    window = tuple(order(market_id=f"kalshi:M{i}", created=NOW - timedelta(hours=1)) for i in range(5))
    assert check(orders=window) == [E]  # exactly order_window old has left the window
    inside = tuple(replace(o, created_at_utc=(NOW - timedelta(minutes=59)).isoformat()) for o in window)
    assert check(orders=inside, risk_policy=replace(POLICY, max_portfolio_risk=Decimal(100))) == [
        C.TRADE_COUNT_LIMIT, E]
    assert check(orders=(order(created=NOW - timedelta(minutes=1)),)) == [E]  # exactly the cooldown
    assert check(orders=(order(created=NOW - timedelta(seconds=59)),)) == [C.COOLDOWN_ACTIVE, E]
    t = ticket()
    exact = replace(POLICY, max_position_risk=t.max_loss)
    assert check(t, risk_policy=exact) == [E]  # exactly at a risk limit is allowed
    assert check(t, risk_report=report(remaining_risk_capacity=t.max_loss)) == [E]


def test_max_loss_at_the_pre_fee_cost_floor_is_not_understated():
    t = ticket()
    assert check(replace(t, max_loss=t.limit_price * t.quantity)) == [E]


@pytest.mark.parametrize("state", [OrderState.PENDING, OrderState.OUTCOME_UNKNOWN, OrderState.RESTING,
                                   OrderState.FILLED, OrderState.CANCELLED])
def test_exposure_counts_pending_resting_filled_and_unknown_outcome(state):
    t = ticket()
    cap = replace(POLICY, max_position_risk=t.max_loss + Decimal("0.5"))
    got = check(t, risk_policy=cap, orders=(order(state),))
    assert C.EXPOSURE_PER_POSITION in got


def test_a_rejected_order_carries_no_exposure_but_counts_as_a_trade():
    t = ticket()
    got = check(t, risk_policy=replace(POLICY, max_portfolio_risk=t.max_loss),
                limits=replace(LIMITS, max_orders_per_window=1),
                orders=(order(OrderState.REJECTED, loss=None, created=NOW - timedelta(minutes=5),
                              market_id="kalshi:ELSEWHERE"),))
    assert got == [C.TRADE_COUNT_LIMIT, E]


def test_exposure_scopes_position_event_cluster_and_global():
    t = ticket()
    budget = t.max_loss + Decimal("0.5")
    same_event = order(market_id="kalshi:TEST-B71.5", cluster="another-cluster")
    same_cluster = order(market_id="kalshi:OTHER", event_id="weather:other")
    unrelated = order(market_id="kalshi:OTHER", event_id="weather:other", cluster="another-cluster")
    other_side = order(side="NO")
    assert check(t, orders=(other_side,), risk_policy=replace(POLICY, max_position_risk=budget)) == [E]
    assert check(t, orders=(same_event,), risk_policy=replace(POLICY, max_event_risk=budget)) == [
        C.EXPOSURE_PER_EVENT, E]
    assert check(t, orders=(same_cluster,), risk_policy=replace(POLICY, max_event_risk=budget)) == [E]
    assert check(t, orders=(same_cluster,), risk_policy=replace(POLICY, max_cluster_risk=budget)) == [
        C.EXPOSURE_PER_CLUSTER, E]
    assert check(t, orders=(unrelated,), risk_policy=replace(POLICY, max_cluster_risk=budget)) == [E]
    assert check(t, orders=(unrelated,), risk_policy=replace(POLICY, max_portfolio_risk=budget)) == [
        C.EXPOSURE_GLOBAL, E]


def test_duplicate_open_order_only_for_the_same_market_and_side_while_open():
    for state in et.OPEN_ORDER_STATES:
        assert C.DUPLICATE_OPEN_ORDER in check(orders=(order(state),))
    for o in (order(OrderState.FILLED), order(OrderState.CANCELLED), order(OrderState.RESTING, side="NO"),
              order(OrderState.RESTING, market_id="kalshi:OTHER")):
        assert C.DUPLICATE_OPEN_ORDER not in check(orders=(o,))


def test_trade_count_includes_future_dated_orders_and_cooldown_is_per_market():
    recent = tuple(order(market_id=f"kalshi:M{i}", created=NOW - timedelta(minutes=10)) for i in range(5))
    assert C.TRADE_COUNT_LIMIT in check(orders=recent)
    future = (order(market_id="kalshi:M0", created=NOW + timedelta(hours=1)),)
    assert check(orders=future, limits=replace(LIMITS, max_orders_per_window=1)) == [C.TRADE_COUNT_LIMIT, E]
    assert check(orders=(order(market_id="kalshi:OTHER", created=NOW - timedelta(seconds=5)),)) == [E]
    # a timed order still drives the cooldown when another order has no time
    both = (order(created=None, market_id="kalshi:OTHER"), order(created=NOW - timedelta(seconds=5)))
    assert check(orders=both) == [C.ORDER_TIME_UNKNOWN, C.COOLDOWN_ACTIVE, E]


def test_transition_tables_are_explicit_and_terminal_states_are_final():
    assert set(TICKET_TRANSITIONS) == set(TicketStatus) and set(ORDER_TRANSITIONS) == set(OrderState)
    for table in (TICKET_TRANSITIONS, ORDER_TRANSITIONS):
        for current, allowed in table.items():
            for new in type(current):
                if new in allowed:
                    assert transition(current, new) is new
                else:
                    with pytest.raises(ValueError):
                        transition(current, new)
    for terminal in (TicketStatus.EXPIRED, TicketStatus.REJECTED, OrderState.FILLED, OrderState.CANCELLED,
                     OrderState.REJECTED):
        assert not (TICKET_TRANSITIONS | ORDER_TRANSITIONS)[terminal]
    assert transition(OrderState.PENDING, OrderState.CANCELLED) is OrderState.CANCELLED  # an unfilled IOC
    assert transition(OrderState.RESTING, OrderState.OUTCOME_UNKNOWN) is OrderState.OUTCOME_UNKNOWN  # lost cancel
    with pytest.raises(ValueError):
        transition(TicketStatus.DRAFT, OrderState.PENDING)
    with pytest.raises(TypeError):
        et.TICKET_TRANSITIONS[TicketStatus.EXPIRED] = frozenset({TicketStatus.DRAFT})


def test_draft_ticket_statuses_are_reachable_from_draft():
    for t in (ticket(now=AS_OF + timedelta(minutes=30)), ticket(action_mode=ActionMode.APP_APPROVAL_API)):
        assert transition(TicketStatus.DRAFT, t.status) is t.status


def test_no_status_means_authorized_to_submit():
    names = {s.name for s in TicketStatus} | {s.name for s in OrderState}
    assert not any(re.search(r"APPROV|AUTHORI|SUBMIT|READY|EXECUTABLE|SEND", n) for n in names), names


@pytest.mark.parametrize("fn", [pre_submit_checks, draft_ticket, transition])
def test_no_force_or_bypass_argument(fn):
    params = inspect.signature(fn).parameters
    assert not any(re.search(r"force|bypass|override|skip|ignore|unsafe", p, re.I) for p in params), list(params)


def test_money_limits_come_from_risk_policy_not_ticket_limits():
    names = {f.name for f in fields(TicketLimits)}
    assert not any(re.search(r"loss|risk|exposure|reserve", n) for n in names), names


def test_ticket_id_is_the_content_derived_idempotency_key():
    """A future client order id must derive from `ticket_id`: the same terms give the same id,
    and any change of market, side, quantity or limit gives a different one."""
    opp = run()
    base = ticket(opp)
    assert ticket(opp).ticket_id == base.ticket_id
    variants = [replace(opp, side="NO"), replace(opp, quantity=2), replace(opp, executable_price=Decimal("0.47")),
                replace(opp, market_id="kalshi:TEST-B71.5")]
    ids = {ticket(v).ticket_id for v in variants}
    assert base.ticket_id not in ids and len(ids) == len(variants)
    assert ticket(opp, now=datetime.fromisoformat(opp.as_of_utc) + timedelta(seconds=1)).ticket_id != base.ticket_id
