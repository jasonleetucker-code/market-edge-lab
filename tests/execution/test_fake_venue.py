"""The deterministic fake venue (#160 package H), alone and end to end with the lifecycle reducer."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from edge_lab.execution import fake_venue as fv
from edge_lab.execution import lifecycle as lc
from edge_lab.execution.fake_venue import Fault, FakeVenue
from edge_lab.execution.lifecycle import Liquidity, Operation
from edge_lab.execution.model import Action, ExactValueError, Grid, Side, TimeInForce
from edge_lab.execution_ticket import OrderState

D = Decimal
MKT = "KXTEST-26OCT07-T50"
GTC, IOC, FOK = TimeInForce.GOOD_TILL_CANCELED, TimeInForce.IMMEDIATE_OR_CANCEL, TimeInForce.FILL_OR_KILL
YES, NO, BUY, SELL = Side.YES, Side.NO, Action.BUY, Action.SELL


def flat_fee(price: Decimal, quantity: Decimal, liquidity: Liquidity) -> Decimal:
    """A test-only fee: one cent per taker contract, nothing for makers. Not a venue schedule."""
    return D("0.01") * quantity if liquidity is Liquidity.TAKER else D(0)


def venue(**kw) -> FakeVenue:
    kw.setdefault("fee", flat_fee)
    return FakeVenue(**kw)


def place(v: FakeVenue, cid: str, *, side=YES, action=BUY, count="10", price="0.42", tif=GTC, **kw) -> fv.Reply:
    return v.new_order(ticker=MKT, side=side, action=action, count=D(count), price=D(price), time_in_force=tif,
                       client_order_id=cid, **kw)


# ---------------------------------------------------------------- matching and the NO-side mapping


def test_buying_no_takes_yes_bids_at_one_minus_the_price():
    v = venue()
    v.add_liquidity(MKT, YES, D("0.60"), D(5))  # someone bids 0.60 for YES = offers NO at 0.40
    r = place(v, "c1", side=NO, price="0.40", count="8")
    assert r.outcome == "ok" and r.body["order"]["fill_count"] == 5 and r.body["order"]["status"] == "resting"
    [f] = v.list_fills()
    assert (f["side"], f["action"], f["price"], f["count"], f["is_taker"]) == ("no", "buy", D("0.40"), D(5), True)
    assert v.book(MKT) == {"yes": [], "no": [(D("0.40"), D(3))]}  # the remainder bids NO at 0.40


def test_a_no_bid_below_the_cross_rests():
    v = venue()
    v.add_liquidity(MKT, YES, D("0.60"), D(5))
    r = place(v, "c1", side=NO, price="0.39")
    assert r.body["order"]["fill_count"] == 0 and v.book(MKT)["no"] == [(D("0.39"), D(10))]


def test_buying_yes_takes_no_bids_and_gets_price_improvement():
    v = venue()
    v.add_liquidity(MKT, NO, D("0.65"), D(4))  # YES offered at 0.35
    r = place(v, "c1", price="0.42", count="4")
    assert r.body["order"]["status"] == "executed"
    assert v.list_fills()[0]["price"] == D("0.35")  # trades at the resting price, below our limit


def test_selling_yes_hits_yes_bids_and_selling_no_hits_no_bids():
    v = venue(cash="100")
    v.add_liquidity(MKT, NO, D("0.50"), D(10))
    place(v, "buy-yes", count="5", price="0.50")
    v.add_liquidity(MKT, YES, D("0.48"), D(5))
    r = place(v, "sell-yes", action=SELL, count="5", price="0.45", reduce_only=True)
    assert r.body["order"]["status"] == "executed"
    assert v.list_fills(r.body["order"]["order_id"])[0]["price"] == D("0.48")
    assert v.positions[(MKT, YES)] == 0
    v.add_liquidity(MKT, YES, D("0.30"), D(3))
    place(v, "buy-no", side=NO, count="3", price="0.70")
    v.add_liquidity(MKT, NO, D("0.72"), D(3))
    r = place(v, "sell-no", side=NO, action=SELL, count="3", price="0.70")
    assert v.list_fills(r.body["order"]["order_id"])[0]["price"] == D("0.72")


def test_price_time_priority_across_our_resting_orders():
    v = venue()
    place(v, "first", count="3", price="0.40")
    place(v, "second", count="3", price="0.40")
    place(v, "better", count="2", price="0.41")
    v.add_liquidity(MKT, NO, D("0.60"), D(6))  # crosses the 0.41 and 0.40 YES bids
    fills = [(f["client_order_id"], f["count"], f["price"], f["is_taker"]) for f in v.list_fills()]
    assert fills == [("better", D(2), D("0.41"), False), ("first", D(3), D("0.40"), False),
                     ("second", D(1), D("0.40"), False)]


def test_a_resting_order_fills_later_as_maker_with_the_maker_fee():
    v = venue()
    r = place(v, "c1", count="5", price="0.42")
    oid = r.body["order"]["order_id"]
    assert v.add_liquidity(MKT, NO, D("0.58"), D(7)) == 5
    order = v.get_order(oid)
    assert order["status"] == "executed" and order["fill_count"] == 5
    [f] = v.list_fills(oid)
    assert f["is_taker"] is False and f["fee"] == D(0) and f["price"] == D("0.42")
    assert v.book(MKT)["no"] == [(D("0.58"), D(2))]


# ---------------------------------------------------------------- order types and checks


def test_ioc_cancels_its_unfilled_remainder():
    v = venue()
    v.add_liquidity(MKT, NO, D("0.58"), D(4))
    order = place(v, "c1", tif=IOC).body["order"]
    assert (order["status"], order["fill_count"], order["remaining_count"]) == ("canceled", D(4), D(0))
    assert v.book(MKT)["yes"] == []


def test_fok_is_all_or_nothing():
    v = venue()
    v.add_liquidity(MKT, NO, D("0.58"), D(4))
    killed = place(v, "c1", tif=FOK).body["order"]
    assert (killed["status"], killed["fill_count"]) == ("canceled", D(0)) and v.list_fills() == []
    assert v.book(MKT)["no"] == [(D("0.58"), D(4))]  # untouched
    done = place(v, "c2", tif=FOK, count="4").body["order"]
    assert (done["status"], done["fill_count"]) == ("executed", D(4))


def test_post_only_is_rejected_when_it_would_cross():
    v = venue()
    v.add_liquidity(MKT, NO, D("0.58"), D(4))
    assert place(v, "c1", post_only=True).error == "POST_ONLY_CROSS"
    assert place(v, "c2", post_only=True, price="0.41").body["order"]["status"] == "resting"
    assert place(v, "c3", post_only=True, tif=IOC, price="0.30").error == "POST_ONLY_REQUIRES_GTC"


def test_reduce_only_is_checked_against_the_position_net_of_resting_sells():
    v = venue()
    assert place(v, "s0", action=SELL, count="1", reduce_only=True).error == "REDUCE_ONLY_WOULD_INCREASE"
    assert place(v, "s0b", action=SELL, count="1").error == "INSUFFICIENT_POSITION"
    v.add_liquidity(MKT, NO, D("0.58"), D(5))
    place(v, "b1", count="5")
    assert v.positions[(MKT, YES)] == 5
    assert place(v, "s1", action=SELL, count="3", price="0.90", reduce_only=True).body["order"]["status"] == "resting"
    assert place(v, "s2", action=SELL, count="3", price="0.90", reduce_only=True).error == "REDUCE_ONLY_WOULD_INCREASE"
    assert place(v, "s3", action=SELL, count="2", price="0.90", reduce_only=True).outcome == "ok"
    assert place(v, "b2", count="1", reduce_only=True).error == "REDUCE_ONLY_BUY_UNSUPPORTED"


def test_funds_are_checked_against_cash_less_resting_buys():
    v = venue(cash="5")
    assert place(v, "c1", count="10", price="0.42").outcome == "ok"  # 4.20 reserved
    assert place(v, "c2", count="2", price="0.42").error == "INSUFFICIENT_FUNDS"
    assert v.account()["reserved"] == D("4.20")


def test_self_cross_is_rejected_before_matching():
    v = venue(cash="100")
    place(v, "yes-bid", count="5", price="0.42")
    assert place(v, "no-bid", side=NO, count="5", price="0.60").error == "SELF_CROSS"
    assert v.list_fills() == []


def test_client_order_ids_are_deduplicated_forever_with_a_distinct_error():
    v = venue()
    oid = place(v, "c1").body["order"]["order_id"]
    assert place(v, "c1").error == "DUPLICATE_CLIENT_ORDER_ID"
    v.cancel(oid)
    assert place(v, "c1", price="0.30").error == "DUPLICATE_CLIENT_ORDER_ID"
    assert len(v.list_orders()) == 1


@pytest.mark.parametrize("kw", [dict(price="0.425"), dict(price="1.00"), dict(count="2.5"), dict(count="0")])
def test_off_grid_orders_are_refused(kw):
    assert place(venue(), "c1", **kw).error.startswith("INVALID_ORDER")


def test_fractional_quantities_when_the_grid_allows_them():
    tenth = Grid(step=D("0.1"), minimum=D("0.1"), maximum=D("1000"))
    v = venue(quantity_grid=tenth)
    v.add_liquidity(MKT, NO, D("0.58"), D("1.5"))
    order = place(v, "c1", count="2.5").body["order"]
    assert (order["fill_count"], order["remaining_count"]) == (D("1.5"), D("1.0"))
    assert v.list_fills()[0]["fee"] == D("0.015")


def test_a_custom_price_grid():
    tenth_cent = Grid(step=D("0.001"), minimum=D("0.001"), maximum=D("0.999"))
    v = venue(price_grid=tenth_cent)
    v.add_liquidity(MKT, NO, D("0.575"), D(2))
    assert place(v, "c1", count="2", price="0.425").body["order"]["status"] == "executed"
    assert place(venue(), "c2", price="0.425").error.startswith("INVALID_ORDER")


def test_fees_come_only_from_the_callers_hook():
    v = FakeVenue()  # no hook: unknown, never zero
    v.add_liquidity(MKT, NO, D("0.58"), D(2))
    place(v, "c1", count="2")
    assert v.list_fills()[0]["fee"] is None and v.account()["fees_unknown"] is True
    assert v.cash == D("1000") - D("0.84")
    calls = []
    hooked = FakeVenue(fee=lambda p, q, liq: calls.append((p, q, liq)) or D("0.03"))
    hooked.add_liquidity(MKT, NO, D("0.58"), D(2))
    place(hooked, "c1", count="2")
    assert calls == [(D("0.42"), D(2), Liquidity.TAKER)] and hooked.cash == D("1000") - D("0.87")
    floaty = FakeVenue(fee=lambda p, q, liq: 0.03)
    floaty.add_liquidity(MKT, NO, D("0.58"), D(2))
    with pytest.raises(ExactValueError):
        place(floaty, "c1", count="2")


def test_the_account_tracks_cash_and_positions_per_ticker_and_side():
    v = venue()
    v.add_liquidity(MKT, NO, D("0.58"), D(3))
    place(v, "y", count="3")
    v.add_liquidity(MKT, YES, D("0.70"), D(2))  # added after: it would have crossed the NO bid
    place(v, "n", side=NO, count="2", price="0.30")
    acct = v.account()
    assert acct["positions"] == {f"{MKT}:no": D(2), f"{MKT}:yes": D(3)}
    assert acct["cash"] == D(1000) - D("1.26") - D("0.03") - D("0.60") - D("0.02")


# ---------------------------------------------------------------- cancel and amend


def test_cancel_reports_the_reduced_count_and_frees_the_book():
    v = venue()
    oid = place(v, "c1").body["order"]["order_id"]
    v.add_liquidity(MKT, NO, D("0.58"), D(4))
    r = v.cancel(oid)
    assert r.body["reduced_by"] == D(6) and r.body["order"]["status"] == "canceled"
    assert r.body["order"]["fill_count"] == D(4) and v.book(MKT)["yes"] == []
    assert v.cancel(oid).error == "NOT_CANCELABLE" and v.cancel("nope").error == "NOT_FOUND"


def test_amend_uses_total_count_semantics():
    v = venue()
    oid = place(v, "c1").body["order"]["order_id"]
    v.add_liquidity(MKT, NO, D("0.58"), D(4))
    r = v.amend(oid, total_count=D(8))
    after = r.body["order"]
    assert (after["total_count"], after["fill_count"], after["remaining_count"]) == (D(8), D(4), D(4))
    assert r.body["old_order"]["remaining_count"] == D(6) and after["initial_count"] == D(10)
    assert v.amend(oid, total_count=D(4)).error == "AMEND_BELOW_FILLED"
    assert v.amend(oid, total_count=D(3)).error == "AMEND_BELOW_FILLED"


def test_an_amended_price_can_cross_and_loses_time_priority():
    v = venue()
    a = place(v, "a", count="2", price="0.40").body["order"]["order_id"]
    place(v, "b", count="2", price="0.40")
    v.amend(a, price=D("0.40"))  # same price, but re-queued behind b
    v.add_liquidity(MKT, NO, D("0.60"), D(2))
    assert [f["client_order_id"] for f in v.list_fills()] == ["b"]
    v.add_liquidity(MKT, NO, D("0.55"), D(1))
    r = v.amend(a, price=D("0.45"))
    assert r.body["order"]["fill_count"] == D(1) and v.list_fills(a)[0]["price"] == D("0.45")


def test_amend_can_assign_a_new_order_id():
    v = venue(amend_assigns_new_order_id=True)
    old = place(v, "c1").body["order"]["order_id"]
    r = v.amend(old, total_count=D(12))
    new = r.body["order"]["order_id"]
    assert new != old and r.body["old_order"]["order_id"] == old and v.replaced_by(old) == new
    assert v.get_order(old) is None and v.get_order(new)["total_count"] == D(12)


def test_ids_and_times_are_deterministic():
    def run():
        v = venue()
        v.add_liquidity(MKT, NO, D("0.58"), D(3))
        place(v, "c1")
        place(v, "c2", side=NO, price="0.20")
        return v.list_orders(), v.list_fills(), v.drain_events()

    assert run() == run()
    orders, fills, _ = run()
    assert [o["order_id"] for o in orders] == ["fake-ord-000001", "fake-ord-000002"]
    assert fills[0]["fill_id"] == "fake-fill-000001" and fills[0]["created_time"].startswith("2026-01-01T00:00")


# ---------------------------------------------------------------- faults


def test_faults_must_be_explicit():
    v = venue()
    with pytest.raises(ValueError):
        v.inject(Fault.REJECT, operation=Operation.NEW_ORDER)  # no reason
    with pytest.raises(ValueError):
        v.inject(Fault.ACCEPT_THEN_TIMEOUT)  # no operation
    with pytest.raises(ValueError):
        v.inject(Fault.DROP_ACK, operation=Operation.CANCEL)
    with pytest.raises(ValueError):
        v.inject(Fault.DELAY_FILL, operation=Operation.NEW_ORDER)  # a feed-level fault
    with pytest.raises(TypeError):
        v.inject("PAUSE")
    assert v.fault_log == []  # nothing was armed


def test_every_fault_is_logged_when_armed_fired_and_cleared():
    v = venue()
    v.inject(Fault.REJECT, operation=Operation.NEW_ORDER, reason="MARKET_CLOSED")
    assert place(v, "c1").error == "MARKET_CLOSED" and v.list_orders() == []
    assert place(v, "c2").outcome == "ok"  # used up
    v.inject(Fault.PAUSE)
    oid = v.list_orders()[0]["order_id"]
    assert v.cancel(oid).error == "TRADING_PAUSED" and v.cancel(oid).error == "TRADING_PAUSED"
    v.clear(Fault.PAUSE)
    assert v.cancel(oid).outcome == "ok"
    log = [(e["event"], e["fault"]) for e in v.fault_log]
    assert log == [("armed", "REJECT"), ("fired", "REJECT"), ("armed", "PAUSE"), ("fired", "PAUSE"),
                   ("fired", "PAUSE"), ("cleared", "PAUSE")]
    assert [e["n"] for e in v.fault_log] == list(range(1, 7))


def test_accept_then_timeout_and_lose_request_differ_only_at_the_venue():
    v = venue()
    v.inject(Fault.ACCEPT_THEN_TIMEOUT, operation=Operation.NEW_ORDER)
    v.inject(Fault.LOSE_REQUEST, operation=Operation.NEW_ORDER)
    lost = place(v, "c1")
    assert lost.outcome == "timeout" and v.orders_by_client_id("c1")["orders"] == []
    accepted = place(v, "c2")
    assert accepted.outcome == "timeout" and accepted.ambiguous
    assert v.orders_by_client_id("c2")["orders"][0]["status"] == "resting"


def test_drop_duplicate_delay_and_reorder_the_feed():
    v = venue()
    v.inject(Fault.DROP_ACK, operation=Operation.NEW_ORDER)
    assert place(v, "c1").outcome == "lost" and v.drain_events() == []
    v.inject(Fault.DUPLICATE_ACK)
    place(v, "c2", price="0.30")
    assert [m["type"] for m in v.drain_events()] == ["order_update", "order_update"]
    v.inject(Fault.DELAY_FILL)
    v.add_liquidity(MKT, NO, D("0.58"), D(1))
    v.add_liquidity(MKT, NO, D("0.58"), D(1))
    assert [m["fill"]["fill_id"] for m in v.drain_events()] == ["fake-fill-000002"]
    assert v.release_delayed_fills() == 1 and v.drain_events()[0]["fill"]["fill_id"] == "fake-fill-000001"
    v.inject(Fault.OUT_OF_ORDER)
    v.add_liquidity(MKT, NO, D("0.58"), D(1))
    v.add_liquidity(MKT, NO, D("0.58"), D(1))
    assert [m["fill"]["fill_id"] for m in v.drain_events()] == ["fake-fill-000004", "fake-fill-000003"]
    assert {e["fault"] for e in v.fault_log if e["event"] == "fired"} == {"DROP_ACK", "DUPLICATE_ACK", "DELAY_FILL",
                                                                          "OUT_OF_ORDER"}


# ---------------------------------------------------------------- end to end with the reducer


class Harness:
    """Our side: one reducer view per client order id, fed by replies and the feed, routed by identity."""

    def __init__(self, venue_: FakeVenue) -> None:
        self.venue = venue_
        self.views: dict[str, lc.OrderView] = {}

    def apply(self, cid: str, *events) -> lc.OrderView:
        self.views[cid] = lc.reduce_all(self.views[cid], events)
        return self.views[cid]

    def place(self, cid, *, side=YES, action=BUY, count="10", price="0.42", tif=GTC, **kw) -> lc.OrderView:
        self.views[cid] = lc.open_view(client_order_id=cid, market_ticker=MKT, side=side, action=action,
                                       quantity=D(count), limit_price=D(price))
        self.apply(cid, lc.SendPrepared(self.venue.now_text()))
        assert lc.may_send_new_order(self.views[cid]) == ["ALREADY_SENT: reconcile, never resubmit blindly"]
        reply = place(self.venue, cid, side=side, action=action, count=count, price=price, tif=tif, **kw)
        return self.apply(cid, *fv.events_from_reply(Operation.NEW_ORDER, reply))

    def cancel(self, cid, *, pump_first=False) -> lc.OrderView:
        view = self.apply(cid, lc.CancelRequested())
        assert view.cancel_requested, view.refusals
        reply = self.venue.cancel(view.provider_order_id)
        if pump_first:  # the feed races ahead of the reply
            self.pump()
        return self.apply(cid, *fv.events_from_reply(Operation.CANCEL, reply))

    def amend(self, cid, total=None, price=None, *, pump_first=False) -> lc.OrderView:
        view = self.apply(cid, lc.AmendRequested(None if total is None else D(total),
                                                 None if price is None else D(price)))
        assert view.amend_pending is not None, view.refusals
        reply = self.venue.amend(view.provider_order_id, total_count=None if total is None else D(total),
                                 price=None if price is None else D(price))
        if pump_first:
            self.pump()
        return self.apply(cid, *fv.events_from_reply(Operation.AMEND, reply))

    def pump(self) -> int:
        messages = self.venue.drain_events()
        for message in messages:
            event = fv.events_from_feed(message)
            target = lc.route(self.views.values(), provider_order_id=event.provider_order_id,
                              client_order_id=event.client_order_id)
            assert target is not None, message
            self.apply(target.client_order_id, event)
        return len(messages)

    def reconcile(self, cid) -> lc.OrderView:
        return self.apply(cid, fv.reconcile_event(self.venue, cid))

    def settle(self) -> None:
        self.venue.release_delayed_fills()
        while self.pump():
            pass

    def assert_matches_venue(self) -> None:
        status_to_state = {"resting": {OrderState.RESTING}, "executed": {OrderState.FILLED},
                           "canceled": {OrderState.CANCELLED}}
        for cid, view in self.views.items():
            assert not view.quarantined, (cid, view.quarantine_reasons)
            [order] = self.venue.orders_by_client_id(cid)["orders"] or [None]
            if order is None:
                assert view.state is OrderState.REJECTED, cid
                continue
            assert view.provider_order_id == order["order_id"]
            assert (view.total_quantity, view.filled_quantity, view.remaining_quantity) == (
                order["total_count"], order["fill_count"], order["remaining_count"]), cid
            assert view.fill_quantity_applied == view.filled_quantity  # every fill receipt arrived once
            assert view.state in status_to_state[order["status"]], (cid, view.state, order["status"])
            fees = [f["fee"] for f in self.venue.list_fills() if f["client_order_id"] == cid]
            assert view.fees_known == sum(fees, D(0))
        projected = lc.project_positions(self.views.values())
        for (ticker, side), p in projected.items():
            assert p.net == self.venue.positions.get((ticker, side), D(0))


def test_e2e_gtc_partial_then_filled_later_as_maker():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))
    v = h.place("c1")
    assert v.state is OrderState.RESTING and v.filled_quantity == 4 and v.unreceived_fill_quantity == 4
    h.pump()
    assert h.views["c1"].unreceived_fill_quantity == 0
    h.venue.add_liquidity(MKT, NO, D("0.60"), D(6))
    h.pump()
    v = h.views["c1"]
    assert v.state is OrderState.FILLED and [f.liquidity for f in v.fills] == [Liquidity.TAKER, Liquidity.MAKER]
    h.assert_matches_venue()


def test_e2e_partial_ioc():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))
    v = h.place("c1", tif=IOC)
    assert v.state is OrderState.CANCELLED and (v.filled_quantity, v.canceled_quantity) == (D(4), D(6))
    h.settle()
    h.assert_matches_venue()


def test_e2e_fok_that_cannot_fill():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))
    v = h.place("c1", tif=FOK)
    assert v.state is OrderState.CANCELLED and v.filled_quantity == 0 and v.canceled_quantity == 10
    h.settle()
    h.assert_matches_venue()


def test_e2e_rejection_and_duplicate_client_id():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))
    assert h.place("c1", post_only=True).state is OrderState.REJECTED
    assert h.views["c1"].terminal_reason == "rejected: POST_ONLY_CROSS"
    h.place("c2", price="0.30")
    h.views["c2-again"] = h.views.pop("c2")  # a second view reusing the id would be refused by the venue
    reply = place(h.venue, "c2", price="0.30")
    assert reply.error == "DUPLICATE_CLIENT_ORDER_ID"


def test_e2e_accept_then_timeout_is_unknown_until_reconciled():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    h.venue.inject(Fault.ACCEPT_THEN_TIMEOUT, operation=Operation.NEW_ORDER)
    v = h.place("c1")
    assert v.state is OrderState.OUTCOME_UNKNOWN and lc.may_send_new_order(v)
    v = h.reconcile("c1")
    assert v.state is OrderState.RESTING and v.filled_quantity == 3
    h.settle()
    h.assert_matches_venue()


def test_e2e_dropped_ack_with_fills_on_the_feed():
    h = Harness(venue())
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    h.venue.inject(Fault.DROP_ACK, operation=Operation.NEW_ORDER)
    v = h.place("c1")
    assert v.state is OrderState.OUTCOME_UNKNOWN
    h.pump()  # the fill carries our client order id, but does not establish the order
    v = h.views["c1"]
    assert v.state is OrderState.OUTCOME_UNKNOWN and v.filled_quantity == 3 and not v.established
    assert h.reconcile("c1").state is OrderState.RESTING
    h.assert_matches_venue()


def test_e2e_lost_request_reconciles_to_never_accepted():
    h = Harness(venue())
    h.venue.inject(Fault.LOSE_REQUEST, operation=Operation.NEW_ORDER)
    assert h.place("c1").state is OrderState.OUTCOME_UNKNOWN
    v = h.reconcile("c1")  # too soon after the send to prove absence
    assert v.state is OrderState.OUTCOME_UNKNOWN and "NOT_FOUND_TOO_EARLY" in v.notes[-1]
    h.venue.advance(31)
    v = h.reconcile("c1")
    assert v.state is OrderState.REJECTED and "never accepted" in v.terminal_reason
    h.assert_matches_venue()


def test_e2e_cancel_timeout_then_reconcile():
    h = Harness(venue())
    h.place("c1")
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(2))
    h.venue.inject(Fault.ACCEPT_THEN_TIMEOUT, operation=Operation.CANCEL)
    v = h.cancel("c1")
    assert v.state is OrderState.OUTCOME_UNKNOWN and v.ambiguous_operation is Operation.CANCEL
    v = h.reconcile("c1")
    assert v.state is OrderState.CANCELLED and (v.filled_quantity, v.canceled_quantity) == (D(2), D(8))
    h.settle()
    h.assert_matches_venue()


def test_e2e_lost_cancel_reconciles_as_still_resting():
    h = Harness(venue())
    h.place("c1")
    h.venue.inject(Fault.LOSE_REQUEST, operation=Operation.CANCEL)
    assert h.cancel("c1").state is OrderState.OUTCOME_UNKNOWN
    v = h.reconcile("c1")
    assert v.state is OrderState.RESTING and not v.cancel_requested
    assert h.cancel("c1").state is OrderState.CANCELLED
    h.settle()
    h.assert_matches_venue()


def test_e2e_paused_venue_refuses_cancel():
    h = Harness(venue())
    h.place("c1")
    h.venue.inject(Fault.PAUSE)
    v = h.cancel("c1")
    assert v.state is OrderState.RESTING and not v.cancel_requested and "CANCEL_REJECTED: TRADING_PAUSED" in v.notes
    h.venue.clear(Fault.PAUSE)
    assert h.cancel("c1").state is OrderState.CANCELLED
    h.settle()
    h.assert_matches_venue()


def test_e2e_late_fill_after_cancel_applies_once():
    h = Harness(venue())
    h.place("c1")
    h.venue.inject(Fault.DELAY_FILL)
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))  # fills 4 before the cancel; its receipt is delayed
    v = h.cancel("c1")
    assert v.state is OrderState.CANCELLED and (v.filled_quantity, v.canceled_quantity) == (D(4), D(6))
    assert v.fills == () and v.unreceived_fill_quantity == 4
    h.settle()
    v = h.views["c1"]
    assert (v.filled_quantity, v.canceled_quantity) == (D(4), D(6)) and len(v.fills) == 1
    h.assert_matches_venue()


def test_e2e_amend_with_prior_fills_delayed():
    h = Harness(venue())
    h.place("c1")
    h.venue.inject(Fault.DELAY_FILL)
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))
    h.pump()  # nothing about the fill yet
    v = h.amend("c1", total="6")
    assert (v.total_quantity, v.filled_quantity, v.remaining_quantity) == (D(6), D(4), D(2))
    h.settle()
    h.assert_matches_venue()


def test_e2e_amend_replaces_the_order_id_and_old_fills_arrive_late():
    h = Harness(venue(amend_assigns_new_order_id=True))
    first = h.place("c1").provider_order_id
    h.venue.inject(Fault.DELAY_FILL)
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    v = h.amend("c1", total="12", price="0.43")
    assert v.provider_order_id != first and v.prior_provider_order_ids == (first,)
    h.venue.add_liquidity(MKT, NO, D("0.57"), D(2))
    h.settle()
    v = h.views["c1"]
    assert {f.provider_order_id for f in v.fills} == {first, v.provider_order_id}
    assert (v.total_quantity, v.filled_quantity, v.remaining_quantity) == (D(12), D(5), D(7))
    h.assert_matches_venue()


def test_e2e_duplicate_and_out_of_order_feed():
    h = Harness(venue())
    h.venue.inject(Fault.DUPLICATE_ACK, times=3)
    h.venue.inject(Fault.OUT_OF_ORDER, times=2)
    h.place("c1")
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    h.amend("c1", total="7")
    h.cancel("c1")
    h.settle()
    h.assert_matches_venue()
    assert h.views["c1"].state is OrderState.CANCELLED


def test_e2e_expiry():
    h = Harness(venue())
    oid = h.place("c1").provider_order_id
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    assert h.venue.expire(oid) and not h.venue.expire(oid)
    h.settle()
    v = h.views["c1"]
    assert v.state is OrderState.CANCELLED and v.terminal_reason == "expired" and v.filled_quantity == 3
    h.assert_matches_venue()


@pytest.mark.parametrize("seed", range(60))
def test_e2e_randomized_sessions_agree_with_the_venue(seed):
    """Random orders, liquidity, cancels and amendments, with non-ambiguous feed faults. After settling,
    every view agrees with the venue's read-back, nothing is quarantined, and positions match."""
    rng = random.Random(seed)
    h = Harness(venue(cash="100000", amend_assigns_new_order_id=seed % 2 == 1))
    n = 0
    for step in range(rng.randint(10, 40)):
        roll = rng.random()
        if roll < 0.15:
            h.venue.inject(rng.choice([Fault.DUPLICATE_ACK, Fault.DELAY_FILL, Fault.OUT_OF_ORDER]),
                           times=rng.randint(1, 3))
        elif roll < 0.45:
            n += 1
            h.place(f"c{n}", side=rng.choice([YES, NO]), count=str(rng.randint(1, 8)),
                    price=f"0.{rng.randint(30, 60)}", tif=rng.choice([GTC, GTC, IOC, FOK]))
        elif roll < 0.75:
            h.venue.add_liquidity(MKT, rng.choice([YES, NO]), D(f"0.{rng.randint(40, 70)}"), D(rng.randint(1, 6)))
        else:
            live = [cid for cid, v in h.views.items() if v.state is OrderState.RESTING and not v.cancel_requested
                    and v.amend_pending is None]
            if live:
                cid = rng.choice(live)
                h.pump()  # our view must know the current fill count before choosing a total
                if h.views[cid].state is OrderState.RESTING:
                    if rng.random() < 0.5:
                        h.cancel(cid)
                    else:
                        filled = int(h.views[cid].filled_quantity)
                        total = filled + rng.randint(1, 6)
                        if total == h.views[cid].total_quantity:
                            total += 1  # a no-change amendment is refused locally
                        h.amend(cid, total=str(total))
        if rng.random() < 0.4:
            h.pump()
    h.venue.clear(Fault.OUT_OF_ORDER)
    h.settle()
    h.assert_matches_venue()
    for cid in list(h.views):
        h.reconcile(cid)
    h.assert_matches_venue()


# ---------------------------------------------------------------- review regressions (REQUEST_CHANGES on 9c31ef1)


def test_e2e_finding2_a_delayed_fill_a_snapshot_and_a_later_maker_fill():
    h = Harness(venue())
    h.place("c1")
    h.venue.inject(Fault.DELAY_FILL)
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))  # fill A: delayed
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(2))  # fill B
    h.pump()
    v = h.reconcile("c1")  # the venue says 5
    assert (v.filled_quantity, v.fill_quantity_applied) == (D(5), D(2))
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(4))  # maker fill C, after the snapshot
    h.pump()
    v = h.views["c1"]
    assert v.filled_quantity == 9 == h.venue.list_orders()[0]["fill_count"] and not v.fees_complete
    h.settle()
    assert h.views["c1"].fees_complete
    h.assert_matches_venue()


@pytest.mark.parametrize("timeout", [False, True], ids=["reply-ok", "reply-timeout"])
def test_e2e_finding4_the_feed_with_the_new_order_id_arrives_before_the_amend_reply(timeout):
    h = Harness(venue(amend_assigns_new_order_id=True))
    old = h.place("c1").provider_order_id
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(2))
    if timeout:
        h.venue.inject(Fault.ACCEPT_THEN_TIMEOUT, operation=Operation.AMEND)
    h.venue.add_liquidity(MKT, NO, D("0.55"), D(3))  # rests: fills the amended price when it crosses
    v = h.amend("c1", total="12", price="0.45", pump_first=True)
    assert not v.quarantined, v.quarantine_reasons
    new = h.venue.replaced_by(old)
    assert v.provider_order_id == new and v.prior_provider_order_ids == (old,)
    assert v.limit_price == D("0.45") and v.total_quantity == 12 and v.state is OrderState.RESTING
    assert any("PROVIDER_ID_REPLACED" in n for n in v.notes)
    h.settle()
    h.assert_matches_venue()


@pytest.mark.parametrize("seed", range(60))
def test_e2e_randomized_sessions_with_ambiguous_replies_agree_after_reconciling(seed):
    """As above, plus replies that time out after the venue acted, lost requests and a feed that races
    ahead of replies. After settling and reconciling, every view agrees with the venue."""
    rng = random.Random(50_000 + seed)
    offsets = ((), (0, -1, 1), (1, 2, -2))[seed % 3]  # fill stamps skewed within the reducer's tolerance
    h = Harness(venue(cash="100000", amend_assigns_new_order_id=seed % 2 == 0, fill_time_offsets=offsets))
    n = 0
    for step in range(rng.randint(10, 40)):
        roll = rng.random()
        if roll < 0.2:
            fault = rng.choice([Fault.DUPLICATE_ACK, Fault.DELAY_FILL, Fault.OUT_OF_ORDER, Fault.ACCEPT_THEN_TIMEOUT,
                                Fault.LOSE_REQUEST])
            if fault in (Fault.ACCEPT_THEN_TIMEOUT, Fault.LOSE_REQUEST):
                h.venue.inject(fault, operation=rng.choice([Operation.CANCEL, Operation.AMEND]))
            else:
                h.venue.inject(fault, times=rng.randint(1, 3))
        elif roll < 0.45:
            n += 1
            h.place(f"c{n}", side=rng.choice([YES, NO]), count=str(rng.randint(1, 8)),
                    price=f"0.{rng.randint(30, 60)}", tif=rng.choice([GTC, GTC, IOC]))
        elif roll < 0.7:
            h.venue.add_liquidity(MKT, rng.choice([YES, NO]), D(f"0.{rng.randint(40, 70)}"), D(rng.randint(1, 6)))
        elif roll < 0.8:
            unknown = [cid for cid, v in h.views.items() if v.state is OrderState.OUTCOME_UNKNOWN]
            if unknown:
                h.reconcile(rng.choice(unknown))
        else:
            live = [cid for cid, v in h.views.items() if v.state is OrderState.RESTING and not v.cancel_requested
                    and v.amend_pending is None and not v.amend_reply_owed]
            if live:
                cid = rng.choice(live)
                h.pump()
                v = h.views[cid]
                if v.state is OrderState.RESTING and not lc.amend_problems(v, v.filled_quantity + 1, None):
                    if rng.random() < 0.5:
                        h.cancel(cid, pump_first=rng.random() < 0.5)
                    else:
                        total = int(v.filled_quantity) + rng.randint(1, 6)
                        total += 1 if total == v.total_quantity else 0  # no-change amendments are refused
                        h.amend(cid, total=str(total),
                                pump_first=rng.random() < 0.5)
        if rng.random() < 0.4:
            h.pump()
        for cid, v in h.views.items():
            assert not v.quarantined, (seed, step, cid, v.quarantine_reasons)
    h.venue.clear(Fault.OUT_OF_ORDER)
    h.settle()
    for cid in list(h.views):
        h.reconcile(cid)
    h.assert_matches_venue()


def test_e2e_n1_skewed_fill_stamps_still_agree_with_the_venue():
    h = Harness(venue(fill_time_offsets=(2, -2)))
    h.place("c1")
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(3))
    v = h.reconcile("c1")
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(2))
    h.pump()
    h.venue.add_liquidity(MKT, NO, D("0.58"), D(1))
    h.settle()
    assert [f["created_time"][-11:-6] for f in h.venue.list_fills()] == ["00:32", "00:48", "01:12"]
    for cid in list(h.views):
        h.reconcile(cid)
    h.assert_matches_venue()
    assert not v.quarantined


def test_fake_clock_options_are_checked():
    with pytest.raises(ValueError):
        FakeVenue(tick_seconds=0)
    with pytest.raises(TypeError):
        FakeVenue(fill_time_offsets=[1])
