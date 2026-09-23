"""Pre-submit control chain for the future execution ticket (flumine-derived checklist, ideas only).

Execution stays disabled: the chain always ends in EXECUTION_NOT_AUTHORIZED, so no ticket
can come out of it clean.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from edge_lab import execution_ticket as et, venues
from edge_lab.execution_ticket import (
    ORDER_TRANSITIONS, TICKET_TRANSITIONS, ActionMode, Control, OrderRecord, OrderState, TicketLimits, TicketStatus,
    draft_ticket, pre_submit_checks, transition,
)
from edge_lab.opportunity import MarketStatus
from test_opportunity import AS_OF, EVENT, MARKET, quote, run
from test_venues_and_tickets import _eligible_verdict

NOW = AS_OF + timedelta(seconds=30)
LIMITS = TicketLimits(max_order_loss=Decimal(10), max_contract_loss=Decimal(10), max_event_loss=Decimal(10),
                      max_global_loss=Decimal(10), max_orders_per_window=5, order_window=timedelta(hours=1),
                      market_cooldown=timedelta(minutes=1))


def ticket(opp=None, **kw):
    opp = opp or run()
    at = datetime.fromisoformat(opp.as_of_utc)
    args = dict(venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at), action_mode=ActionMode.SIMULATION,
                now=at, ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    args.update(kw)
    return draft_ticket(opp, **args)


def order(state=OrderState.FILLED, loss="1", market_id=MARKET.market_id, event_id=EVENT.event_id, side="YES",
          created=AS_OF - timedelta(hours=2), ticket_id="tkt-other"):
    return OrderRecord(ticket_id, market_id, event_id, side, state, None if loss is None else Decimal(loss),
                       None if created is None else created.isoformat())


def check(t=None, **kw):
    args = dict(now=NOW, market=MARKET, quote=quote(), max_book_age=timedelta(minutes=5),
                order_state_as_of_utc=NOW.isoformat(), max_order_state_age=timedelta(seconds=10), orders=(),
                limits=LIMITS)
    args.update(kw)
    return [v.control for v in pre_submit_checks(t or ticket(), **args)]


def test_a_clean_ticket_still_fails_execution_not_authorized_and_nothing_else():
    t = ticket()
    assert t.status is TicketStatus.DRAFT and t.event_id == EVENT.event_id, t.reasons
    assert check(t) == [Control.EXECUTION_NOT_AUTHORIZED]


@pytest.mark.parametrize("mutate, first", [
    (lambda t, kw: (replace(t, status=TicketStatus.REJECTED), kw), Control.TICKET_NOT_DRAFT),
    (lambda t, kw: (t, {**kw, "now": NOW + timedelta(minutes=2)}), Control.TICKET_EXPIRED),
    (lambda t, kw: (replace(t, quantity=0), kw), Control.QTY_INVALID),
    (lambda t, kw: (replace(t, quantity=True), kw), Control.QTY_INVALID),
    (lambda t, kw: (replace(t, quantity=1.0), kw), Control.QTY_INVALID),
    (lambda t, kw: (replace(t, limit_price=0.48), kw), Control.PRICE_INVALID),  # float refused
    (lambda t, kw: (replace(t, limit_price=Decimal("1")), kw), Control.PRICE_INVALID),
    (lambda t, kw: (replace(t, limit_price=Decimal("0.48005")), kw), Control.PRICE_INVALID),
    (lambda t, kw: (replace(t, limit_price=None), kw), Control.PRICE_INVALID),
    (lambda t, kw: (t, {**kw, "price_grid": Decimal("0.1")}), Control.PRICE_OFF_TICK),
    (lambda t, kw: (t, {**kw, "market": None}), Control.MARKET_UNKNOWN),
    (lambda t, kw: (t, {**kw, "market": replace(MARKET, market_id="kalshi:OTHER")}), Control.MARKET_UNKNOWN),
    (lambda t, kw: (t, {**kw, "market": replace(MARKET, status=MarketStatus.CLOSED)}), Control.MARKET_NOT_OPEN),
    (lambda t, kw: (t, {**kw, "market": replace(MARKET, status=MarketStatus.UNKNOWN)}), Control.MARKET_NOT_OPEN),
    (lambda t, kw: (t, {**kw, "quote": None}), Control.BOOK_MISSING),
    (lambda t, kw: (t, {**kw, "quote": quote(side="NO")}), Control.BOOK_MISSING),
    (lambda t, kw: (t, {**kw, "quote": quote(ask=None)}), Control.BOOK_MISSING),
    (lambda t, kw: (t, {**kw, "quote": quote(anomaly="crossed")}), Control.BOOK_MISSING),
    (lambda t, kw: (t, {**kw, "quote": quote(received=None)}), Control.BOOK_STALE),
    (lambda t, kw: (t, {**kw, "quote": quote(received=NOW - timedelta(minutes=6))}), Control.BOOK_STALE),
    (lambda t, kw: (t, {**kw, "quote": quote(received=NOW + timedelta(seconds=1))}), Control.BOOK_STALE),
    (lambda t, kw: (t, {**kw, "quote": quote(ask="0.49")}), Control.QUOTE_CHANGED),
    (lambda t, kw: (t, {**kw, "quote": quote(ask="0.47")}), Control.QUOTE_CHANGED),  # any move re-prices
    (lambda t, kw: (t, {**kw, "quote": quote(size="0.5")}), Control.QUOTE_CHANGED),
    (lambda t, kw: (t, {**kw, "quote": quote(size=None)}), Control.QUOTE_CHANGED),
    (lambda t, kw: (t, {**kw, "order_state_as_of_utc": None}), Control.ORDER_STATE_UNHEALTHY),
    (lambda t, kw: (t, {**kw, "order_state_as_of_utc": (NOW - timedelta(seconds=11)).isoformat()}),
     Control.ORDER_STATE_UNHEALTHY),
    (lambda t, kw: (t, {**kw, "orders": (order(ticket_id=t.ticket_id),)}), Control.DUPLICATE_TICKET),
    (lambda t, kw: (t, {**kw, "orders": (order(OrderState.RESTING),)}), Control.DUPLICATE_OPEN_ORDER),
    (lambda t, kw: (t, {**kw, "orders": (order(loss=None),)}), Control.EXPOSURE_UNKNOWN),
    (lambda t, kw: (replace(t, max_loss=None), kw), Control.EXPOSURE_UNKNOWN),
    (lambda t, kw: (replace(t, event_id=None), kw), Control.EXPOSURE_UNKNOWN),
    (lambda t, kw: (t, {**kw, "limits": replace(LIMITS, max_order_loss=Decimal("0.01"))}), Control.EXPOSURE_PER_ORDER),
    (lambda t, kw: (t, {**kw, "orders": (order(created=None),)}), Control.TRADE_COUNT_LIMIT),
    (lambda t, kw: (t, {**kw, "orders": (order(created=NOW - timedelta(seconds=30)),)}), Control.COOLDOWN_ACTIVE),
])
def test_each_control_fails_closed_and_is_named_first(mutate, first):
    t, kw = mutate(ticket(), {})
    got = check(t, **kw)
    assert got[0] is first, got
    assert got[-1] is Control.EXECUTION_NOT_AUTHORIZED


def test_every_failure_is_listed_in_evaluation_order():
    got = check(replace(ticket(), quantity=0), market=None, quote=None, order_state_as_of_utc=None)
    assert got == [Control.QTY_INVALID, Control.MARKET_UNKNOWN, Control.BOOK_MISSING, Control.ORDER_STATE_UNHEALTHY,
                   Control.EXECUTION_NOT_AUTHORIZED]
    assert got == sorted(got, key=list(Control).index)


def test_on_tick_price_passes_a_coarser_grid():
    assert check(price_grid=Decimal("0.01")) == [Control.EXECUTION_NOT_AUTHORIZED]


@pytest.mark.parametrize("state", [OrderState.PENDING, OrderState.OUTCOME_UNKNOWN, OrderState.RESTING,
                                   OrderState.FILLED, OrderState.CANCELLED])
def test_exposure_counts_pending_resting_filled_and_unknown_outcome(state):
    t = ticket()
    cap = replace(LIMITS, max_contract_loss=t.max_loss + Decimal("0.5"))
    got = check(t, limits=cap, orders=(order(state, loss="1", side="YES"),))
    assert Control.EXPOSURE_PER_CONTRACT in got


def test_a_rejected_order_carries_no_exposure_but_counts_as_a_trade():
    t = ticket()
    tight = replace(LIMITS, max_global_loss=t.max_loss, max_orders_per_window=1)
    got = check(t, limits=tight, orders=(order(OrderState.REJECTED, loss="5", created=NOW - timedelta(minutes=5),
                                               market_id="kalshi:ELSEWHERE"),))
    assert Control.EXPOSURE_GLOBAL not in got and Control.TRADE_COUNT_LIMIT in got


def test_exposure_scopes_contract_event_and_global():
    t = ticket()
    budget = t.max_loss + Decimal("0.5")
    same_event_other_market = order(market_id="kalshi:TEST-B71.5")
    other_event = order(market_id="kalshi:OTHER", event_id="weather:other")
    other_side = order(side="NO")
    assert check(t, orders=(other_side,), limits=replace(LIMITS, max_contract_loss=budget)) == [
        Control.EXECUTION_NOT_AUTHORIZED]
    assert Control.EXPOSURE_PER_EVENT in check(t, orders=(same_event_other_market,),
                                               limits=replace(LIMITS, max_event_loss=budget))
    assert check(t, orders=(other_event,), limits=replace(LIMITS, max_event_loss=budget)) == [
        Control.EXECUTION_NOT_AUTHORIZED]
    assert Control.EXPOSURE_GLOBAL in check(t, orders=(other_event,), limits=replace(LIMITS, max_global_loss=budget))


def test_duplicate_open_order_only_for_the_same_market_and_side_while_open():
    for state in et.OPEN_ORDER_STATES:
        assert Control.DUPLICATE_OPEN_ORDER in check(orders=(order(state),))
    for o in (order(OrderState.FILLED), order(OrderState.CANCELLED), order(OrderState.RESTING, side="NO"),
              order(OrderState.RESTING, market_id="kalshi:OTHER")):
        assert Control.DUPLICATE_OPEN_ORDER not in check(orders=(o,))


def test_trade_count_window_and_per_market_cooldown():
    recent = tuple(order(market_id=f"kalshi:M{i}", created=NOW - timedelta(minutes=10)) for i in range(5))
    assert Control.TRADE_COUNT_LIMIT in check(orders=recent)
    old = tuple(order(market_id=f"kalshi:M{i}", created=NOW - timedelta(hours=2)) for i in range(5))
    assert Control.TRADE_COUNT_LIMIT not in check(orders=old)
    future = (order(market_id="kalshi:M0", created=NOW + timedelta(hours=1)),)
    assert Control.TRADE_COUNT_LIMIT in check(orders=future, limits=replace(LIMITS, max_orders_per_window=1))
    elsewhere = (order(market_id="kalshi:OTHER", created=NOW - timedelta(seconds=5)),)
    assert Control.COOLDOWN_ACTIVE not in check(orders=elsewhere)


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
    with pytest.raises(ValueError):
        transition(TicketStatus.DRAFT, OrderState.PENDING)
    with pytest.raises(TypeError):
        et.TICKET_TRANSITIONS[TicketStatus.EXPIRED] = frozenset({TicketStatus.DRAFT})


def test_draft_ticket_statuses_are_reachable_from_draft():
    stale = ticket(now=AS_OF + timedelta(minutes=30))
    rejected = ticket(action_mode=ActionMode.APP_APPROVAL_API)
    for t in (stale, rejected):
        assert transition(TicketStatus.DRAFT, t.status) is t.status


def test_no_status_means_authorized_to_submit():
    names = {s.name for s in TicketStatus} | {s.name for s in OrderState}
    assert not any(re.search(r"APPROV|AUTHORI|SUBMIT|READY|EXECUTABLE|SEND", n) for n in names), names


@pytest.mark.parametrize("fn", [pre_submit_checks, draft_ticket, transition])
def test_no_force_or_bypass_argument(fn):
    params = inspect.signature(fn).parameters
    assert not any(re.search(r"force|bypass|override|skip|ignore|unsafe", p, re.I) for p in params), list(params)


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
