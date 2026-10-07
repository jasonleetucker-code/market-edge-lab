"""The order-lifecycle reducer (#160 package H): coarse states through `execution_ticket.transition` only,
exact quantities, ambiguity without blind resubmission, late and duplicate receipts, total-count amends."""

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from decimal import Decimal

import pytest

from edge_lab.execution import lifecycle as lc
from edge_lab.execution.lifecycle import (AmendAcknowledged, AmendRequested, Acknowledged, CancelConfirmed,
                                          CancelRequested, Expired, Fill, Liquidity, Operation, ReconcileObserved,
                                          Rejected, SendPrepared, SendReturnedAmbiguous, invariant_problems, reduce,
                                          reduce_all)
from edge_lab.execution.model import Action, ExactValueError, Side
from edge_lab.execution_ticket import ORDER_TRANSITIONS, OrderState, transition

D = Decimal
CID = "cid-0001"
PID = "prov-0001"
SENT = "2026-10-07T15:00:00+00:00"  # when the new order was journaled; t(n) below is n seconds later


def t(sec: int) -> str:
    return f"2026-10-07T15:00:{sec:02d}+00:00"


def fresh(**kw) -> lc.OrderView:
    base = dict(client_order_id=CID, market_ticker="KXTEST-26OCT07-T50", side=Side.YES, action=Action.BUY,
                quantity=D("10"), limit_price=D("0.42"), intent_digest="d" * 64)
    base.update(kw)
    return lc.open_view(**base)


def sent(**kw) -> lc.OrderView:
    return reduce(fresh(**kw), SendPrepared(SENT))


def ack(status="resting", filled="0", remaining="10", pid=PID, cid=CID, total=None, at=None) -> Acknowledged:
    return Acknowledged(pid, cid, status, None if filled is None else D(filled),
                        None if remaining is None else D(remaining), None if total is None else D(total), at)


def fill(fid, qty, price="0.42", fee="0.01", pid=PID, cid=None, at=None, liq=Liquidity.TAKER, side=None,
         action=None) -> Fill:
    return Fill(fid, D(qty), D(price), None if fee is None else D(fee), liq, at if at is not None else t(30), pid, cid,
                side, action)


def recon(status="resting", filled="0", remaining="10", *, found=True, complete=True, pid=PID, total=None, price=None,
          as_of=None) -> ReconcileObserved:
    if not found:
        return ReconcileObserved(CID, None, False, authoritative_complete=complete, as_of_utc=as_of or t(59))
    return ReconcileObserved(CID, pid, True, status, D(filled), None if remaining is None else D(remaining),
                             None if total is None else D(total), None if price is None else D(price),
                             authoritative_complete=complete, as_of_utc=as_of or t(59))


def resting(**kw) -> lc.OrderView:
    return reduce(sent(**kw), ack())


def ok(v: lc.OrderView) -> lc.OrderView:
    assert not v.quarantined, v.quarantine_reasons
    assert not invariant_problems(v), invariant_problems(v)
    return v


def quarantined(v: lc.OrderView, fragment: str) -> lc.OrderView:
    assert v.quarantined, "expected a quarantine"
    assert any(fragment in r for r in v.quarantine_reasons), v.quarantine_reasons
    assert not invariant_problems(v)
    return v


def counts(v: lc.OrderView) -> tuple:
    return (v.total_quantity, v.filled_quantity, v.remaining_quantity, v.canceled_quantity)


# ---------------------------------------------------------------- construction and purity


def test_a_new_view_is_pending_unsent_and_whole():
    v = fresh()
    assert v.state is OrderState.PENDING and v.send_stage is lc.SendStage.UNSENT and not v.established
    assert counts(v) == (D(10), D(0), D(10), D(0)) and v.provider_order_id is None
    assert lc.may_send_new_order(v) == []


def test_view_from_intent_uses_the_intent_identity():
    from datetime import datetime, timedelta, timezone

    from edge_lab.execution import model as m

    cent = m.Grid(step=D("0.01"), minimum=D("0.01"), maximum=D("0.99"))
    whole = m.Grid(step=D("1"), minimum=D("1"), maximum=D("1000"))
    expires = (datetime(2026, 10, 7, 15, 5, tzinfo=timezone.utc) + timedelta(minutes=5)).isoformat()
    i = m.OrderIntent(intent_key="EXP-TEST:ticket-0001", strategy_id="synthetic-demo", strategy_version="v1",
                      scope=m.AccountScope(m.Environment.FIXTURE, "fixture-acct"), market_ticker="KXTEST-26OCT07-T50",
                      kind=m.IntentKind.ENTRY, side=Side.YES, action=Action.BUY, quantity=D("10"),
                      limit_price=D("0.42"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                      max_total_cost=D("4.60"), expires_at_utc=expires, price_grid=cent, quantity_grid=whole,
                      profile_version="kalshi-ordinary-v0", risk_policy_version="risk-v1",
                      fee_schedule_version="test-fee-v1", reduce_only=False)
    v = lc.view_from_intent(i)
    assert v.client_order_id == i.client_order_id() and v.intent_digest == i.digest()
    assert (v.market_ticker, v.side, v.action, v.original_quantity, v.limit_price) == (
        i.market_ticker, i.side, i.action, i.quantity, i.limit_price)


@pytest.mark.parametrize("kw", [dict(quantity=10.0), dict(limit_price=0.42), dict(quantity=D(0)),
                                dict(limit_price=D(1)), dict(client_order_id=""), dict(side="yes")])
def test_open_view_refuses_inexact_or_invalid_values(kw):
    with pytest.raises((ValueError, TypeError, ExactValueError)):
        fresh(**kw)


@pytest.mark.parametrize("build", [
    lambda: Fill("f", 1.0, D("0.4"), None, None, None, PID),
    lambda: Fill("f", D(1), 0.4, None, None, None, PID),
    lambda: Fill("f", D(1), D("0.4"), 0.01, None, None, PID),
    lambda: Acknowledged(PID, CID, "resting", 0.0, D(10)),
    lambda: CancelConfirmed(PID, reduced_by=True),
    lambda: AmendRequested(new_total=8.0),
    lambda: ReconcileObserved(CID, PID, 1, "resting", D(0), D(10)),
])
def test_events_refuse_floats_and_bools(build):
    with pytest.raises((ExactValueError, TypeError)):
        build()


def test_reduce_is_pure_and_records_every_receipt():
    v = sent()
    before = (v, counts(v), v.receipts)
    out = reduce(v, ack())
    assert (v, counts(v), v.receipts) == before  # the input is untouched
    assert out.receipts == v.receipts + (ack(),)
    weird = reduce(out, object())
    quarantined(weird, "UNKNOWN_EVENT")
    assert len(weird.receipts) == len(out.receipts) + 1


def test_reduce_refuses_a_non_view():
    with pytest.raises(TypeError):
        reduce({"state": "PENDING"}, ack())


# ---------------------------------------------------------------- transitions

AMB = SendReturnedAmbiguous


# (from, to) -> events from a fresh, sent view; the last event moves `from` to `to`.
LEGAL = {
    (OrderState.PENDING, OrderState.OUTCOME_UNKNOWN): [AMB(Operation.NEW_ORDER)],
    (OrderState.PENDING, OrderState.RESTING): [ack()],
    (OrderState.PENDING, OrderState.FILLED): [ack("executed", "10", "0")],
    (OrderState.PENDING, OrderState.CANCELLED): [ack("canceled", "0", "0")],  # an unfilled IOC
    (OrderState.PENDING, OrderState.REJECTED): [Rejected(Operation.NEW_ORDER, "INSUFFICIENT_FUNDS")],
    (OrderState.OUTCOME_UNKNOWN, OrderState.RESTING): [AMB(Operation.NEW_ORDER), recon()],
    (OrderState.OUTCOME_UNKNOWN, OrderState.FILLED): [AMB(Operation.NEW_ORDER), recon("executed", "10", "0")],
    (OrderState.OUTCOME_UNKNOWN, OrderState.CANCELLED): [AMB(Operation.NEW_ORDER), recon("canceled", "3", "0")],
    (OrderState.OUTCOME_UNKNOWN, OrderState.REJECTED): [AMB(Operation.NEW_ORDER), recon(found=False)],
    (OrderState.RESTING, OrderState.FILLED): [ack(), fill("f1", "10")],
    (OrderState.RESTING, OrderState.CANCELLED): [ack(), CancelRequested(), CancelConfirmed(PID, reduced_by=D(10))],
    (OrderState.RESTING, OrderState.OUTCOME_UNKNOWN): [ack(), CancelRequested(), AMB(Operation.CANCEL)],
}


def test_the_recipes_cover_every_legal_transition():
    table = {(a, b) for a, targets in ORDER_TRANSITIONS.items() for b in targets}
    assert set(LEGAL) == table


@pytest.mark.parametrize("edge", sorted(LEGAL, key=lambda e: (e[0].value, e[1].value)),
                         ids=lambda e: f"{e[0].value}->{e[1].value}")
def test_every_legal_transition(edge):
    start, end = edge
    events = LEGAL[edge]
    v = reduce_all(sent(), events[:-1])
    assert v.state is start
    out = ok(reduce(v, events[-1]))
    assert out.state is end


def test_the_reducer_moves_only_through_the_canonical_transition(monkeypatch):
    seen = []

    def spy(current, new):
        seen.append((current, new))
        return transition(current, new)

    monkeypatch.setattr(lc, "transition", spy)
    reduce_all(sent(), [ack(), fill("f1", "4"), CancelRequested(), CancelConfirmed(PID)])
    assert seen == [(OrderState.PENDING, OrderState.RESTING), (OrderState.RESTING, OrderState.CANCELLED)]


@pytest.mark.parametrize("current,new", [(OrderState.FILLED, OrderState.RESTING),
                                         (OrderState.CANCELLED, OrderState.FILLED),
                                         (OrderState.REJECTED, OrderState.RESTING),
                                         (OrderState.RESTING, OrderState.PENDING),
                                         (OrderState.OUTCOME_UNKNOWN, OrderState.PENDING)])
def test_illegal_transitions_raise_in_the_canonical_table(current, new):
    with pytest.raises(ValueError):
        transition(current, new)


@pytest.mark.parametrize("setup,event,fragment", [
    ([ack("executed", "10", "0")], ack("canceled", "0", "0"), "COUNT_BELOW_KNOWN_FILLS"),  # FILLED, then "canceled"
    ([ack("executed", "10", "0")], recon("resting", "0", "10"), "TERMINAL_CONTRADICTED"),
    ([Rejected(Operation.NEW_ORDER, "X")], ack(), "TERMINAL_CONTRADICTED"),
    ([Rejected(Operation.NEW_ORDER, "X")], fill("f1", "1", cid=CID), "TERMINAL_CONTRADICTED"),
    ([ack("canceled", "0", "0")], recon("resting", "0", "10"), "TERMINAL_CONTRADICTED"),
    ([ack("executed", "10", "0")], AmendAcknowledged(PID, D(15), D("0.42")), "TERMINAL_CONTRADICTED"),
])
def test_a_terminal_state_never_moves_and_a_contradiction_quarantines(setup, event, fragment):
    v = reduce_all(sent(), setup)
    assert v.is_terminal and not v.quarantined
    out = reduce(v, event)
    quarantined(out, fragment)
    assert out.state is v.state and counts(out) == counts(v)
    assert out.receipts[-1] == event  # the late receipt is kept, not lost


# ---------------------------------------------------------------- send, ambiguity and reconciliation


def test_a_second_send_is_refused_as_blind_resubmission():
    v = sent()
    assert "ALREADY_SENT: reconcile, never resubmit blindly" in lc.may_send_new_order(v)
    quarantined(reduce(v, SendPrepared(SENT)), "RESEND_REFUSED")
    unknown = reduce(v, AMB(Operation.NEW_ORDER))
    assert lc.may_send_new_order(unknown)
    quarantined(reduce(unknown, SendPrepared(SENT)), "RESEND_REFUSED")


def test_timeout_of_the_new_order_is_outcome_unknown_and_a_fill_does_not_establish_it():
    v = ok(reduce(sent(), AMB(Operation.NEW_ORDER)))
    assert v.state is OrderState.OUTCOME_UNKNOWN and v.ambiguous_operation is Operation.NEW_ORDER
    v = ok(reduce(v, fill("f1", "3", pid=PID, cid=CID)))
    assert v.state is OrderState.OUTCOME_UNKNOWN and not v.established and v.filled_quantity == 3
    assert v.provider_order_id == PID  # linked by the client order id, not by price
    assert lc.cancel_problems(v)  # nothing may be canceled or amended before reconciliation
    v = ok(reduce(v, recon("resting", "3", "7")))
    assert v.state is OrderState.RESTING and v.established and v.ambiguous_operation is None
    assert counts(v) == (D(10), D(3), D(7), D(0))


def test_not_found_is_evidence_not_proof_unless_authoritative_and_complete():
    v = reduce(sent(), AMB(Operation.NEW_ORDER))
    partial = ok(reduce(v, recon(found=False, complete=False)))
    assert partial.state is OrderState.OUTCOME_UNKNOWN and partial.not_found_observations == 1
    assert any("not proof" in n for n in partial.notes)
    again = ok(reduce(partial, recon(found=False, complete=False)))
    assert again.state is OrderState.OUTCOME_UNKNOWN and again.not_found_observations == 2
    final = ok(reduce(again, recon(found=False, complete=True)))
    assert final.state is OrderState.REJECTED and "never accepted" in final.terminal_reason


def test_an_authoritative_not_found_contradicting_a_fill_quarantines():
    v = reduce_all(sent(), [AMB(Operation.NEW_ORDER), fill("f1", "2", cid=CID)])
    out = quarantined(reduce(v, recon(found=False, complete=True)), "NOT_FOUND_CONTRADICTS_EVIDENCE")
    assert out.state is OrderState.OUTCOME_UNKNOWN


def test_unknown_then_reconciled_after_the_order_was_already_filled_and_canceled():
    v = reduce_all(sent(), [AMB(Operation.NEW_ORDER), recon("canceled", "4", "0")])
    ok(v)
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(4), D(0), D(6))
    assert v.canceled_floor == 6 and v.unreceived_fill_quantity == 4 and not v.fees_complete
    v = ok(reduce_all(v, [fill("f1", "1", cid=CID), fill("f2", "3", cid=CID)]))
    assert counts(v) == (D(10), D(4), D(0), D(6)) and v.fees_complete
    quarantined(reduce(v, fill("f3", "1", cid=CID)), "FILL_EXCEEDS_OPEN_QUANTITY")


@pytest.mark.parametrize("stage", ["new_order", "cancel", "cancel_after_partial", "amend", "after_established",
                                   "after_terminal", "duplicate_timeout"])
def test_a_timeout_at_each_stage(stage):
    if stage == "new_order":
        v = ok(reduce(sent(), AMB(Operation.NEW_ORDER)))
        assert v.state is OrderState.OUTCOME_UNKNOWN
        v = ok(reduce(v, ack()))  # a late reply establishes it
        assert v.state is OrderState.RESTING and v.ambiguous_operation is None
    elif stage in ("cancel", "cancel_after_partial"):
        v = resting()
        if stage == "cancel_after_partial":
            v = reduce(v, fill("f1", "4"))
        v = ok(reduce_all(v, [CancelRequested(), AMB(Operation.CANCEL)]))
        assert v.state is OrderState.OUTCOME_UNKNOWN and v.cancel_requested
        assert lc.cancel_problems(v) and lc.amend_problems(v, D(8), None)  # reconcile first
        filled = "4" if stage == "cancel_after_partial" else "0"
        v = ok(reduce(v, recon("canceled", filled, "0")))
        assert v.state is OrderState.CANCELLED and not v.cancel_requested
        assert v.canceled_quantity == 10 - int(filled)
    elif stage == "amend":
        v = ok(reduce_all(resting(), [AmendRequested(new_total=D(6)), AMB(Operation.AMEND)]))
        assert v.state is OrderState.OUTCOME_UNKNOWN and v.amend_pending is not None
        v = ok(reduce(v, recon("resting", "0", "6", total="6")))
        assert v.state is OrderState.RESTING and v.total_quantity == 6 and v.amend_pending is None
    elif stage == "after_established":
        v = ok(reduce(resting(), AMB(Operation.NEW_ORDER)))
        assert v.state is OrderState.RESTING and "AMBIGUOUS_AFTER_ESTABLISHED" in v.notes[-1]
    elif stage == "after_terminal":
        v = reduce_all(resting(), [CancelRequested(), fill("f1", "10")])
        assert v.state is OrderState.FILLED
        v = ok(reduce(v, AMB(Operation.CANCEL)))
        assert v.state is OrderState.FILLED and "AMBIGUOUS_AFTER_TERMINAL" in v.notes[-1]
    else:
        v = ok(reduce_all(sent(), [AMB(Operation.NEW_ORDER), AMB(Operation.NEW_ORDER)]))
        assert v.state is OrderState.OUTCOME_UNKNOWN


@pytest.mark.parametrize("events,fragment", [
    ([AMB(Operation.NEW_ORDER)], "AMBIGUOUS_WITHOUT_SEND"),
    ([SendPrepared(SENT), ack(), AMB(Operation.CANCEL)], "AMBIGUOUS_WITHOUT_REQUEST"),
    ([SendPrepared(SENT), ack(), AMB(Operation.AMEND)], "AMBIGUOUS_WITHOUT_REQUEST"),
    ([ack()], "RECEIPT_FOR_UNSENT_ORDER"),
    ([fill("f1", "1")], "RECEIPT_FOR_UNSENT_ORDER"),
    ([recon()], "RECEIPT_FOR_UNSENT_ORDER"),
    ([Rejected(Operation.NEW_ORDER, "X")], "REJECT_WITHOUT_SEND"),
])
def test_receipts_without_their_request_quarantine(events, fragment):
    quarantined(reduce_all(fresh(), events), fragment)


def test_a_cancel_timeout_reconciled_as_still_resting_frees_the_cancel():
    v = reduce_all(resting(), [fill("f1", "2"), CancelRequested(), AMB(Operation.CANCEL)])
    v = ok(reduce(v, recon("resting", "2", "8")))
    assert v.state is OrderState.RESTING and not v.cancel_requested and "CANCEL_NOT_APPLIED_PER_RECONCILE" in v.notes
    assert lc.cancel_problems(v) == []


def test_an_amend_timeout_reconciled_as_not_applied_clears_the_pending_amend():
    v = reduce_all(resting(), [AmendRequested(new_total=D(12)), AMB(Operation.AMEND)])
    v = ok(reduce(v, recon("resting", "0", "10", total="10", price="0.42")))
    assert v.state is OrderState.RESTING and v.amend_pending is None and v.total_quantity == 10


def test_a_price_amend_timeout_stays_unknown_without_the_venue_price():
    v = reduce_all(resting(), [AmendRequested(new_price=D("0.45")), AMB(Operation.AMEND)])
    v = ok(reduce(v, recon("resting", "0", "10")))
    assert v.state is OrderState.OUTCOME_UNKNOWN and v.amend_pending is not None
    v = ok(reduce(v, recon("resting", "0", "10", price="0.45")))
    assert v.state is OrderState.RESTING and v.limit_price == D("0.45") and v.limit_prices == (D("0.42"), D("0.45"))


def test_a_stale_authoritative_snapshot_is_tolerated_only_when_provably_older_than_the_fills():
    v = reduce_all(resting(), [fill("f1", "4", at=t(30))])
    older = ok(reduce(v, recon("resting", "0", "10", as_of=t(10))))
    assert older.filled_quantity == 4 and any("STALE_FILL_COUNT" in n for n in older.notes)
    quarantined(reduce(v, recon("resting", "0", "10", as_of=t(40))), "COUNT_BELOW_APPLIED_FILLS")
    no_clock = reduce_all(resting(), [Fill("f1", D(4), D("0.42"), None, None, None, PID)])
    quarantined(reduce(no_clock, recon("resting", "0", "10", as_of=t(10))), "COUNT_BELOW_APPLIED_FILLS")


# ---------------------------------------------------------------- acknowledgements


@pytest.mark.parametrize("event,fragment", [
    (ack(pid=None), "MALFORMED_ACK: no provider order id"),
    (ack(pid=""), "MALFORMED_ACK: no provider order id"),
    (ack(status="open"), "unknown venue status"),
    (ack(status=None), "unknown venue status"),
    (ack(remaining="-1", total="10"), "negative"),
    (ack(filled="-2", remaining="12"), "negative"),
    (ack(filled="2", remaining="7", total="10"), "MALFORMED_COUNTS"),
    (ack("executed", "6", "0", total="10"), "MALFORMED_COUNTS"),
    (ack("canceled", "4", "6"), "MALFORMED_COUNTS"),
    (ack(cid="someone-else"), "IDENTITY_MISMATCH"),
    (ack(filled="0", remaining="12"), "TOTAL_MISMATCH"),
])
def test_a_malformed_ack_quarantines_without_applying(event, fragment):
    v = sent()
    out = quarantined(reduce(v, event), fragment)
    assert out.state is OrderState.PENDING and counts(out) == counts(v) and not out.established
    assert out.receipts[-1] is event


def test_an_ack_with_a_different_provider_id_quarantines():
    quarantined(reduce(resting(), ack(pid="prov-9999")), "IDENTITY_MISMATCH")


def test_duplicate_acks_are_idempotent():
    v = resting()
    again = ok(reduce(v, ack()))
    assert counts(again) == counts(v) and again.state is v.state and again.provider_order_id == PID


def test_an_ack_with_counts_establishes_partial_fills_owed():
    v = ok(reduce(sent(), ack("resting", "4", "6", at=t(10))))
    assert v.state is OrderState.RESTING and v.filled_quantity == 4 and v.unreceived_fill_quantity == 4
    assert v.fees_known == 0 and not v.fees_complete  # unseen fills: fees unknown, not zero
    v = ok(reduce(v, fill("f1", "4", fee="0.07", at=t(5))))  # executed before the snapshot: covered by it
    assert counts(v) == (D(10), D(4), D(6), D(0)) and v.fees_complete and v.fees_known == D("0.07")


def test_an_untimed_count_leaves_which_fills_it_covers_unknown():
    v = ok(reduce_all(sent(), [ack("resting", "4", "6"), fill("f1", "4", at=t(5))]))
    assert v.filled_quantity == 4 and v.fill_timing_uncertain and not v.fees_complete  # 4 or 8: a lower bound
    v = ok(reduce(v, recon("resting", "4", "6", as_of=t(20))))
    assert v.filled_quantity == 4 and v.fill_timing_uncertain  # still: the first count has no time
    final = ok(reduce(v, CancelConfirmed(PID, reduced_by=D(6))))
    assert not final.fill_timing_uncertain and final.fees_complete  # a final count settles it


def test_an_ack_with_missing_counts_establishes_without_inventing_zeroes():
    v = ok(reduce(sent(), Acknowledged(PID, CID, "resting", None, None)))
    assert v.state is OrderState.RESTING and counts(v) == (D(10), D(0), D(10), D(0))


# ---------------------------------------------------------------- fills


def test_duplicate_fill_is_idempotent_and_may_fill_in_unknown_fields():
    v = reduce(resting(), Fill("f1", D(3), D("0.42"), None, None, None, PID))
    again = ok(reduce(v, Fill("f1", D(3), D("0.42"), D("0.02"), Liquidity.MAKER, t(5), PID)))
    assert again.filled_quantity == 3 and len(again.fills) == 1
    assert again.fill("f1").fee == D("0.02") and again.fill("f1").liquidity is Liquidity.MAKER
    same = ok(reduce(again, fill("f1", "3", fee="0.02", liq=Liquidity.MAKER, at=t(5))))
    assert counts(same) == counts(again) and "DUPLICATE_FILL" in same.notes[-1]


@pytest.mark.parametrize("conflict", [fill("f1", "2"), fill("f1", "3", price="0.41"), fill("f1", "3", fee="0.05"),
                                      fill("f1", "3", liq=Liquidity.MAKER)])
def test_the_same_fill_id_with_different_content_quarantines(conflict):
    v = reduce(resting(), fill("f1", "3"))
    out = quarantined(reduce(v, conflict), "FILL_CONFLICT")
    assert counts(out) == counts(v)


@pytest.mark.parametrize("event,fragment", [
    (fill("", "1"), "no fill id"),
    (fill("f1", "0"), "not positive"),
    (fill("f1", "-1"), "not positive"),
    (fill("f1", "1", price="1"), "outside (0, 1)"),
    (fill("f1", "1", fee="-0.01"), "negative fee"),
    (fill("f1", "1", price="0.43"), "FILL_PRICE_BEYOND_LIMIT"),
    (fill("f1", "1", side=Side.NO), "FILL_SIDE_MISMATCH"),
    (fill("f1", "1", action=Action.SELL), "FILL_ACTION_MISMATCH"),
    (fill("f1", "11"), "FILL_EXCEEDS_OPEN_QUANTITY"),
    (fill("f1", "1", pid=None, cid=None), "IDENTITY_MISSING"),
    (fill("f1", "1", pid="prov-other"), "IDENTITY_MISMATCH"),
    (fill("f1", "1", pid=PID, cid="cid-other"), "IDENTITY_MISMATCH"),
])
def test_bad_fills_quarantine_and_are_not_applied(event, fragment):
    v = resting()
    out = quarantined(reduce(v, event), fragment)
    assert counts(out) == counts(v) and out.fills == ()


def test_a_sell_fill_below_its_limit_quarantines_and_price_improvement_is_fine():
    v = resting(action=Action.SELL)
    ok(reduce(v, fill("f1", "1", price="0.45")))
    quarantined(reduce(v, fill("f1", "1", price="0.41")), "FILL_PRICE_BEYOND_LIMIT")
    ok(reduce(resting(), fill("f1", "1", price="0.40")))


def test_a_fill_matching_only_by_price_is_never_applied():
    v = resting()
    stranger = Fill("f1", D(1), D("0.42"), None, None, None, "prov-other", None)
    assert lc.route([v], provider_order_id="prov-other") is None
    quarantined(reduce(v, stranger), "IDENTITY_MISMATCH")
    before_ack = sent()
    out = quarantined(reduce(before_ack, Fill("f1", D(1), D("0.42"), None, None, None, PID, None)), "UNMATCHED")
    assert out.provider_order_id is None


# ---------------------------------------------------------------- out-of-order receipts


def _summary(v: lc.OrderView) -> tuple:
    return (v.state, counts(v), v.canceled_floor, tuple(sorted(f.fill_id for f in v.fills)), v.provider_order_id,
            v.fees_known, v.quarantined)


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
def test_out_of_order_receipts_reach_the_same_view(order):
    events = [ack("resting", "0", "10", at=t(1)), fill("f1", "3", cid=CID, at=t(2)), fill("f2", "2", cid=CID, at=t(3)),
              ack("resting", "5", "5", at=t(3))]
    in_order = reduce_all(sent(), events)
    shuffled = reduce_all(sent(), [events[i] for i in order])
    assert _summary(ok(shuffled)) == _summary(ok(in_order))
    assert shuffled.state is OrderState.RESTING and counts(shuffled) == (D(10), D(5), D(5), D(0))


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
def test_out_of_order_receipts_around_a_cancel_are_deterministic(order):
    head = [ack("resting", "0", "10", at=t(1)), CancelRequested()]
    tail = [fill("f1", "4", at=t(2)), CancelConfirmed(PID, reduced_by=D(6), filled_quantity=D(4)),
            ack("canceled", "4", "0", at=t(4)), ack("resting", "4", "6", at=t(2))]
    v = ok(reduce_all(sent(), head + [tail[i] for i in order]))
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(4), D(0), D(6)) and v.fill("f1")


def test_a_fill_before_its_ack_is_held_on_the_pending_view():
    v = ok(reduce(sent(), fill("f1", "10", cid=CID)))
    assert v.state is OrderState.PENDING and v.filled_quantity == 10  # not established yet
    v = ok(reduce(v, ack("resting", "0", "10")))  # a stale creation snapshot
    assert v.state is OrderState.FILLED and any("STALE_FILL_COUNT" in n for n in v.notes)


# ---------------------------------------------------------------- cancellation


def test_a_cancel_request_changes_nothing_until_confirmed():
    v = reduce(resting(), fill("f1", "4"))
    asked = ok(reduce(v, CancelRequested()))
    assert asked.cancel_requested and asked.state is OrderState.RESTING and counts(asked) == counts(v)
    late = ok(reduce(asked, fill("f2", "2")))  # still fillable while the cancel is in flight
    assert counts(late) == (D(10), D(6), D(4), D(0))
    done = ok(reduce(late, CancelConfirmed(PID, reduced_by=D(4))))
    assert done.state is OrderState.CANCELLED and counts(done) == (D(10), D(6), D(0), D(4))
    assert not done.cancel_requested and done.terminal_reason == "cancel"


def test_a_late_fill_after_a_cancel_without_a_count_applies_once_and_reduces_the_canceled_quantity():
    v = reduce_all(resting(), [fill("f1", "4"), CancelRequested(), CancelConfirmed(PID)])
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(4), D(0), D(6)) and v.canceled_floor == 0
    late = ok(reduce(v, fill("f2", "2")))
    assert late.state is OrderState.CANCELLED and counts(late) == (D(10), D(6), D(0), D(4))
    assert any("LATE_FILL_REDUCED_CANCELED" in n for n in late.notes)
    again = ok(reduce(late, fill("f2", "2")))  # exactly once
    assert counts(again) == counts(late)


def test_a_late_fill_already_counted_by_the_cancel_changes_nothing():
    v = reduce_all(resting(), [CancelRequested(), CancelConfirmed(PID, reduced_by=D(6))])
    assert counts(v) == (D(10), D(4), D(0), D(6)) and v.unreceived_fill_quantity == 4  # canceled is not unfilled
    late = ok(reduce_all(v, [fill("f1", "3"), fill("f2", "1")]))
    assert counts(late) == counts(v) and late.unreceived_fill_quantity == 0 and late.fees_complete


def test_a_late_fill_beyond_the_venue_stated_cancel_quarantines():
    v = reduce_all(resting(), [CancelRequested(), CancelConfirmed(PID, reduced_by=D(6))])
    quarantined(reduce_all(v, [fill("f1", "4"), fill("f2", "1")]), "FILL_EXCEEDS_OPEN_QUANTITY")


def test_late_fills_that_erase_a_cancel_quarantine_the_terminal_state():
    v = reduce_all(resting(), [fill("f1", "4"), CancelRequested(), CancelConfirmed(PID)])
    out = quarantined(reduce(v, fill("f2", "6")), "TERMINAL_CONTRADICTED")
    assert out.state is OrderState.CANCELLED and counts(out) == counts(v)


@pytest.mark.parametrize("event,fragment", [
    (CancelConfirmed(PID, reduced_by=D(11)), "exceeds total"),
    (CancelConfirmed(PID, remaining_quantity=D(3)), "remaining 3 after a full cancel"),
    (CancelConfirmed(PID, reduced_by=D(6), filled_quantity=D(3)), "!= total"),
    (CancelConfirmed(PID, reduced_by=D(9)), "COUNT_BELOW_APPLIED_FILLS"),
    (CancelConfirmed(PID, filled_quantity=D(1)), "COUNT_BELOW_APPLIED_FILLS"),
    (CancelConfirmed("prov-other"), "IDENTITY_MISMATCH"),
    (CancelConfirmed(None), "IDENTITY_MISSING"),
])
def test_contradictory_cancel_confirmations_quarantine(event, fragment):
    v = reduce_all(resting(), [fill("f1", "2"), CancelRequested()])
    quarantined(reduce(v, event), fragment)


def test_cancel_confirmed_for_an_unestablished_order_quarantines():
    v = reduce(sent(), fill("f1", "1", cid=CID))
    quarantined(reduce(v, CancelConfirmed(PID, client_order_id=CID)), "FOR_UNESTABLISHED_ORDER")


def test_cancel_requests_are_refused_locally_when_unsafe():
    assert "CANCEL_NEEDS_ESTABLISHED_ORDER" in reduce(sent(), CancelRequested()).refusals
    twice = reduce_all(resting(), [CancelRequested(), CancelRequested()])
    assert twice.refusals == ("CANCEL_ALREADY_PENDING",) and not twice.quarantined
    done = reduce_all(resting(), [fill("f1", "10"), CancelRequested()])
    assert done.refusals and done.refusals[0].startswith("CANCEL_ON_TERMINAL")


def test_a_cancel_refused_by_the_venue_clears_the_request():
    v = reduce_all(resting(), [CancelRequested(), Rejected(Operation.CANCEL, "TRADING_PAUSED")])
    ok(v)
    assert v.state is OrderState.RESTING and not v.cancel_requested and "CANCEL_REJECTED: TRADING_PAUSED" in v.notes
    timed = reduce_all(resting(), [CancelRequested(), AMB(Operation.CANCEL), Rejected(Operation.CANCEL, "PAUSED")])
    assert ok(timed).state is OrderState.RESTING and timed.ambiguous_operation is None


def test_a_cancel_after_the_order_filled_is_harmless():
    v = reduce_all(resting(), [CancelRequested(), fill("f1", "10")])
    assert v.state is OrderState.FILLED
    out = ok(reduce(v, CancelConfirmed(PID, reduced_by=D(0))))
    assert out.state is OrderState.FILLED and not out.cancel_requested
    quarantined(reduce(v, CancelConfirmed(PID, reduced_by=D(3))), "COUNT_BELOW_APPLIED_FILLS")


def test_an_unsolicited_venue_cancel_is_recorded():
    v = ok(reduce(resting(), CancelConfirmed(PID, reduced_by=D(10))))
    assert v.state is OrderState.CANCELLED and any("UNSOLICITED_CANCEL" in n for n in v.notes)


def test_expiry_cancels_what_is_open_and_keeps_fills():
    v = ok(reduce_all(resting(), [fill("f1", "3"), Expired(PID, filled_quantity=D(3))]))
    assert v.state is OrderState.CANCELLED and v.terminal_reason == "expired"
    assert counts(v) == (D(10), D(3), D(0), D(7)) and v.canceled_floor == 7
    filled = reduce(resting(), fill("f1", "10"))
    assert ok(reduce(filled, Expired(PID))).state is OrderState.FILLED
    quarantined(reduce(sent(), Expired(PID, client_order_id=CID)), "FOR_UNESTABLISHED_ORDER")


# ---------------------------------------------------------------- partial IOC, FOK, rejection


def test_a_partial_ioc_ends_canceled_with_its_fills():
    v = ok(reduce(sent(), ack("canceled", "4", "0")))
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(4), D(0), D(6)) and v.canceled_floor == 6
    v = ok(reduce_all(v, [fill("f1", "3"), fill("f2", "1")]))
    assert counts(v) == (D(10), D(4), D(0), D(6)) and v.fees_complete
    quarantined(reduce(v, fill("f3", "1")), "FILL_EXCEEDS_OPEN_QUANTITY")


def test_a_partial_ioc_whose_fills_arrive_first():
    v = ok(reduce_all(sent(), [fill("f1", "4", cid=CID), ack("canceled", "4", "0")]))
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(4), D(0), D(6))
    quarantined(reduce_all(sent(), [fill("f1", "5", cid=CID), ack("canceled", "4", "0")]), "COUNT_BELOW_APPLIED")


def test_an_fok_that_cannot_fill_ends_canceled_with_nothing_filled():
    v = ok(reduce(sent(), ack("canceled", "0", "0")))
    assert v.state is OrderState.CANCELLED and counts(v) == (D(10), D(0), D(0), D(10))
    quarantined(reduce(v, fill("f1", "1")), "FILL_EXCEEDS_OPEN_QUANTITY")


def test_rejection_rules():
    rejected = ok(reduce(sent(), Rejected(Operation.NEW_ORDER, "POST_ONLY_CROSS")))
    assert rejected.state is OrderState.REJECTED and rejected.terminal_reason == "rejected: POST_ONLY_CROSS"
    assert "DUPLICATE_REJECT" in ok(reduce(rejected, Rejected(Operation.NEW_ORDER, "X"))).notes[-1]
    quarantined(reduce(resting(), Rejected(Operation.NEW_ORDER, "LATE")), "REJECT_CONTRADICTS_EVIDENCE")
    quarantined(reduce(reduce(sent(), fill("f1", "1", cid=CID)), Rejected(Operation.NEW_ORDER, "X")),
                "REJECT_CONTRADICTS_EVIDENCE")
    unknown = reduce(sent(), AMB(Operation.NEW_ORDER))
    named = Rejected(Operation.NEW_ORDER, "LATE_REPLY", client_order_id=CID)
    assert ok(reduce(unknown, named)).state is OrderState.REJECTED


# ---------------------------------------------------------------- amendments


def test_the_amend_count_is_a_total_including_filled_contracts():
    v = reduce_all(resting(), [fill("f1", "4"), AmendRequested(new_total=D(8))])
    assert counts(v) == (D(10), D(4), D(6), D(0)) and v.amend_pending == lc.AmendTarget(D(8), D("0.42"))
    v = ok(reduce(v, AmendAcknowledged(PID, D(8), D("0.42"))))
    assert counts(v) == (D(8), D(4), D(4), D(0))  # 4 resting, not 8
    assert v.amend_pending is None and v.total_history == (D(10), D(8)) and v.original_quantity == 10


def test_an_amend_up_and_a_price_change():
    v = reduce_all(resting(), [fill("f1", "4"), AmendRequested(new_total=D(15), new_price=D("0.44"))])
    v = ok(reduce(v, AmendAcknowledged(PID, D(15), D("0.44"))))
    assert counts(v) == (D(15), D(4), D(11), D(0)) and v.limit_price == D("0.44")
    ok(reduce(v, fill("f2", "1", price="0.44")))


@pytest.mark.parametrize("total,fragment", [(D(3), "AMEND_BELOW_FILLED"), (D(4), "AMEND_LEAVES_NOTHING")])
def test_an_amend_at_or_below_filled_is_refused_locally(total, fragment):
    v = reduce(resting(), fill("f1", "4"))
    out = ok(reduce(v, AmendRequested(new_total=total)))
    assert out.amend_pending is None and any(fragment in r for r in out.refusals)
    assert counts(out) == counts(v)


@pytest.mark.parametrize("setup,request_,fragment", [
    ([], AmendRequested(), "AMEND_EMPTY"),
    ([], AmendRequested(new_price=D(1)), "AMEND_PRICE_OUT_OF_RANGE"),
    ([AmendRequested(new_total=D(8))], AmendRequested(new_total=D(7)), "AMEND_ALREADY_PENDING"),
    ([CancelRequested()], AmendRequested(new_total=D(7)), "AMEND_WHILE_CANCEL_PENDING"),
    ([fill("f1", "10")], AmendRequested(new_total=D(12)), "AMEND_ON_TERMINAL"),
])
def test_unsafe_amend_requests_are_refused(setup, request_, fragment):
    out = reduce_all(resting(), setup + [request_])
    assert any(fragment in r for r in out.refusals), out.refusals
    assert "AMEND_NEEDS_ESTABLISHED_ORDER" in reduce(sent(), AmendRequested(new_total=D(5))).refusals


def test_an_amend_the_venue_reports_below_filled_quarantines():
    v = reduce_all(resting(), [AmendRequested(new_total=D(6)), fill("f1", "7")])
    out = quarantined(reduce(v, AmendAcknowledged(PID, D(6), D("0.42"))), "AMEND_TOTAL_BELOW_FILLED")
    assert out.total_quantity == 10


def test_an_amend_with_prior_fills_delayed():
    """The venue had filled 4 before the amendment; their fill receipts arrive afterwards."""
    v = reduce_all(resting(), [AmendRequested(new_total=D(6))])
    v = ok(reduce(v, AmendAcknowledged(PID, D(6), D("0.42"), filled_quantity=D(4), remaining_quantity=D(2),
                                       venue_time_utc=t(10))))
    assert counts(v) == (D(6), D(4), D(2), D(0)) and v.unreceived_fill_quantity == 4
    v = ok(reduce_all(v, [fill("f1", "1", at=t(1)), fill("f2", "3", at=t(2))]))
    assert counts(v) == (D(6), D(4), D(2), D(0)) and v.unreceived_fill_quantity == 0 and v.fees_complete


def test_an_amend_ack_without_counts_then_delayed_fills():
    v = reduce_all(resting(), [AmendRequested(new_total=D(6)), AmendAcknowledged(PID, D(6), D("0.42"))])
    v = ok(reduce(v, fill("f1", "4")))
    assert counts(v) == (D(6), D(4), D(2), D(0))
    quarantined(reduce(v, fill("f2", "3")), "FILL_EXCEEDS_OPEN_QUANTITY")


def test_an_amend_that_replaces_the_provider_id_keeps_old_fills_attached():
    v = reduce_all(resting(), [fill("f1", "2"), AmendRequested(new_total=D(12))])
    v = ok(reduce(v, AmendAcknowledged(PID, D(12), D("0.42"), new_provider_order_id="prov-0002")))
    assert v.provider_order_id == "prov-0002" and v.prior_provider_order_ids == (PID,)
    v = ok(reduce_all(v, [fill("f0", "1", pid=PID), fill("f3", "1", pid="prov-0002")]))  # an old fill, delayed
    assert counts(v) == (D(12), D(4), D(8), D(0)) and {f.fill_id for f in v.fills} == {"f0", "f1", "f3"}
    assert lc.route([v], provider_order_id=PID) is v and lc.route([v], provider_order_id="prov-0002") is v
    stale = ok(reduce(v, ack("resting", "0", "10", pid=PID)))
    assert counts(stale) == counts(v) and "STALE_SNAPSHOT" in stale.notes[-1]


def test_a_stale_snapshot_from_before_an_amendment_is_noted_not_applied():
    v = reduce_all(resting(), [AmendRequested(new_total=D(6)), AmendAcknowledged(PID, D(6), D("0.42"))])
    out = ok(reduce(v, ack("resting", "0", "10")))
    assert counts(out) == counts(v) and "STALE_SNAPSHOT" in out.notes[-1]
    quarantined(reduce(v, ack("resting", "0", "9")), "TOTAL_MISMATCH")


def test_a_snapshot_showing_the_amended_total_applies_the_pending_amend():
    v = reduce(resting(), AmendRequested(new_total=D(6)))
    out = ok(reduce(v, ack("resting", "0", "6")))
    assert out.total_quantity == 6 and out.amend_pending is None and "AMEND_APPLIED_PER_SNAPSHOT" in out.notes


def test_fills_beyond_the_old_total_wait_for_a_pending_larger_amendment():
    v = reduce_all(resting(), [fill("f1", "10", at=t(1))])
    assert v.state is OrderState.FILLED
    up = reduce_all(resting(), [AmendRequested(new_total=D(15)), fill("f1", "10", at=t(1))])
    assert up.state is OrderState.RESTING and up.remaining_quantity == 0  # not FILLED: the total may grow
    parked = ok(reduce(up, fill("f2", "3", at=t(2))))
    assert parked.parked_fills and parked.filled_quantity == 10 and not parked.fees_complete
    done = ok(reduce(parked, AmendAcknowledged(PID, D(15), D("0.42"))))
    assert counts(done) == (D(15), D(13), D(2), D(0)) and not done.parked_fills and done.fill("f2")
    refused = reduce(parked, Rejected(Operation.AMEND, "NOT_AMENDABLE"))
    quarantined(refused, "FILL_EXCEEDS_OPEN_QUANTITY")


def test_a_rejected_amend_returns_to_the_unamended_order():
    v = reduce_all(resting(), [AmendRequested(new_total=D(15)), fill("f1", "10")])
    out = ok(reduce(v, Rejected(Operation.AMEND, "NOT_AMENDABLE")))
    assert out.state is OrderState.FILLED and out.amend_pending is None


def test_duplicate_and_unsolicited_amend_acks():
    v = reduce_all(resting(), [AmendRequested(new_total=D(6)), AmendAcknowledged(PID, D(6), D("0.42"))])
    assert "DUPLICATE_AMEND_ACK" in ok(reduce(v, AmendAcknowledged(PID, D(6), D("0.42")))).notes[-1]
    out = ok(reduce(resting(), AmendAcknowledged(PID, D(7), D("0.42"))))
    assert out.total_quantity == 7 and any("UNSOLICITED_AMEND" in n for n in out.notes)
    quarantined(reduce(sent(), AmendAcknowledged(PID, D(7), D("0.42"), client_order_id=CID)), "UNESTABLISHED")


# ---------------------------------------------------------------- invariants are checked, never clamped


@pytest.mark.parametrize("corrupt", [dict(remaining_quantity=D(11)),
                                     dict(canceled_quantity=D(-1), remaining_quantity=D(11)),
                                     dict(filled_quantity=D(-1), remaining_quantity=D(11)),
                                     dict(canceled_floor=D(1))])
def test_a_corrupted_view_is_quarantined_not_clamped(corrupt):
    bad = replace(resting(), **corrupt)
    assert invariant_problems(bad)
    out = reduce(bad, CancelRequested())
    assert out.quarantined and any(r.startswith("INVARIANT") for r in out.quarantine_reasons)
    assert counts(out) == counts(bad)  # nothing was silently repaired


def test_quarantine_is_sticky():
    v = quarantined(reduce(resting(), fill("f1", "11")), "FILL_EXCEEDS")
    later = reduce_all(v, [fill("f2", "1"), ack()])
    assert later.quarantined and later.quarantine_reasons[0] == v.quarantine_reasons[0]
    assert lc.may_send_new_order(later) and lc.cancel_problems(later)


# ---------------------------------------------------------------- routing and projection


def test_route_matches_by_identity_only():
    a = reduce(resting(), fill("f1", "1"))
    b = reduce(reduce(sent(client_order_id="cid-0002"), ack(pid="prov-0002", cid="cid-0002")), fill("g1", "1",
                                                                                                    pid="prov-0002"))
    views = [a, b]
    assert lc.route(views, client_order_id="cid-0002") is b
    assert lc.route(views, provider_order_id=PID) is a
    assert lc.route(views, provider_order_id="prov-9999") is None  # same price, same size: still no match
    assert lc.route(views) is None
    with pytest.raises(LookupError):
        lc.route(views, provider_order_id=PID, client_order_id="cid-0002")


def test_project_positions_groups_by_market_and_side():
    buy = ok(reduce_all(resting(), [fill("f1", "4", fee="0.03"), fill("f2", "2", fee="0.01")]))
    sell = ok(reduce_all(sent(client_order_id="cid-0002", action=Action.SELL),
                         [ack(pid="p2", cid="cid-0002"), Fill("s1", D(1), D("0.50"), None, None, t(9), "p2", None)]))
    other = ok(reduce(reduce(sent(client_order_id="cid-0003", side=Side.NO), ack(pid="p3", cid="cid-0003")),
                      fill("n1", "5", pid="p3", fee="0.02")))
    out = lc.project_positions([buy, sell, other])
    yes = out[("KXTEST-26OCT07-T50", Side.YES)]
    assert (yes.bought, yes.sold, yes.net, yes.fees_known, yes.fees_complete, yes.order_count) == (
        D(6), D(1), D(5), D("0.04"), False, 2)
    no = out[("KXTEST-26OCT07-T50", Side.NO)]
    assert (no.bought, no.net, no.fees_complete, no.contains_quarantined) == (D(5), D(5), True, False)
    flagged = lc.project_positions([quarantined(reduce(buy, fill("f9", "11")), "FILL_EXCEEDS")])
    assert flagged[("KXTEST-26OCT07-T50", Side.YES)].contains_quarantined
    with pytest.raises(ValueError):
        lc.project_positions([buy, buy])
    assert all(isinstance(x, Decimal) for x in (yes.bought, yes.sold, yes.fees_known))


# ---------------------------------------------------------------- property-style randomized sequences


def _random_event(rng: random.Random, view: lc.OrderView, n: int):
    pid = rng.choice([PID, PID, PID, "prov-0002", None])
    cid = rng.choice([CID, CID, None, "cid-other"])
    qty = D(rng.choice(["1", "2", "3", "4", "10", "0", "-1"]))
    status = rng.choice(["resting", "resting", "canceled", "executed", "pending", "weird"])
    filled = D(rng.randint(0, 11))
    remaining = D(rng.randint(-1, 10))
    choice = rng.randrange(14)
    if choice == 0:
        return SendPrepared(SENT)
    if choice == 1:
        return AMB(rng.choice(list(Operation)))
    if choice in (2, 3):
        return Acknowledged(pid, cid, status, filled, remaining, rng.choice([None, filled + remaining]), t(n % 60))
    if choice == 4:
        return Rejected(rng.choice(list(Operation)), "R", pid if rng.random() < 0.3 else None)
    if choice in (5, 6, 7):
        fid = f"f{rng.randint(1, 6)}"
        return Fill(fid, qty, D(rng.choice(["0.40", "0.42", "0.43", "0.99"])), rng.choice([None, D("0.01")]),
                    rng.choice([None, Liquidity.TAKER]), t(n % 60), pid, cid)
    if choice == 8:
        return CancelRequested()
    if choice == 9:
        return CancelConfirmed(pid, cid, rng.choice([None, D(rng.randint(0, 10))]),
                               rng.choice([None, filled]), rng.choice([None, D(0)]))
    if choice == 10:
        return AmendRequested(rng.choice([None, D(rng.randint(1, 15))]), rng.choice([None, D("0.44")]))
    if choice == 11:
        return AmendAcknowledged(pid, D(rng.randint(1, 15)), D(rng.choice(["0.42", "0.44"])), cid,
                                 rng.choice([None, None, "prov-0003"]), rng.choice([None, filled]))
    if choice == 12:
        return Expired(pid, cid, rng.choice([None, filled]))
    return ReconcileObserved(CID, pid, rng.random() < 0.8, status, filled, remaining,
                             rng.choice([None, filled + remaining]), rng.choice([None, D("0.42"), D("0.44")]),
                             rng.random() < 0.5, t(n % 60))


@pytest.mark.parametrize("seed", range(300))
def test_randomized_sequences_hold_the_invariants_or_quarantine(seed):
    rng = random.Random(seed)
    v = fresh() if seed % 3 == 0 else sent()
    events = []
    for n in range(rng.randint(5, 40)):
        event = _random_event(rng, v, n)
        events.append(event)
        prev = v
        v = reduce(v, event)
        assert not invariant_problems(v), (seed, n, invariant_problems(v))
        for q in (v.total_quantity, v.filled_quantity, v.remaining_quantity, v.canceled_quantity):
            assert isinstance(q, Decimal) and q >= 0
        assert v.receipts == prev.receipts + (event,)
        assert set(prev.quarantine_reasons) <= set(v.quarantine_reasons)  # sticky
        if prev.state is not v.state:
            assert v.state in ORDER_TRANSITIONS[prev.state], (prev.state, v.state)
        if prev.is_terminal:
            assert v.state is prev.state
        assert v.fill_quantity_applied <= v.filled_quantity
        assert v.filled_quantity >= prev.filled_quantity  # fills are never undone
        _assert_monotonic(prev, v)
    assert reduce_all(fresh() if seed % 3 == 0 else sent(), events) == v  # deterministic replay


def _plausible_event(rng: random.Random, view: lc.OrderView, n: int):
    """Mostly well-formed receipts with the right identities, so sequences reach deep states."""
    total, filled = view.total_quantity, view.filled_quantity
    k = rng.randint(1, 8)
    fill_event = fill(f"f{k}", str(k % 3 + 1), price="0.42" if k % 2 else "0.41", fee=None if k == 5 else "0.01",
                      cid=CID, at=t(k))  # the same id always carries the same content
    venue_filled = D(rng.randint(int(filled), int(total))) if total >= filled else filled
    choice = rng.randrange(13)
    if choice == 0:
        pending = [op for op, live in ((Operation.CANCEL, view.cancel_requested),
                                       (Operation.AMEND, view.amend_pending is not None)) if live]
        return AMB(rng.choice(pending)) if pending else CancelRequested()
    if choice in (1, 2):
        return ack("resting", str(venue_filled), str(total - venue_filled), total=str(total), at=t(n % 60))
    if choice in (3, 4, 5, 6):
        return fill_event
    if choice == 7:
        return CancelRequested()
    if choice == 8:
        return CancelConfirmed(PID, reduced_by=rng.choice([None, total - venue_filled]))
    if choice == 9:
        return AmendRequested(new_total=D(rng.randint(int(filled) + 1, int(filled) + 8)))
    if choice == 10:
        target = view.amend_pending or lc.AmendTarget(total, view.limit_price)
        return AmendAcknowledged(PID, target.new_total, target.new_price)
    if choice == 11:
        return rng.choice([Rejected(Operation.CANCEL, "R"), Rejected(Operation.AMEND, "R"), Expired(PID)])
    status = rng.choice(["resting", "canceled"])
    return recon(status, str(venue_filled), str(total - venue_filled) if status == "resting" else "0",
                 total=str(total), price=str(view.limit_price), as_of=t(59))


@pytest.mark.parametrize("seed", range(300))
def test_plausible_randomized_sequences_hold_the_invariants(seed):
    rng = random.Random(10_000 + seed)
    v = reduce(sent(), ack())
    for n in range(rng.randint(5, 40)):
        prev = v
        v = reduce(v, _plausible_event(rng, v, n))
        assert not invariant_problems(v), (seed, n, invariant_problems(v))
        if prev.state is not v.state:
            assert v.state in ORDER_TRANSITIONS[prev.state]
        if prev.is_terminal:
            assert v.state is prev.state
        assert v.filled_quantity >= prev.filled_quantity
        _assert_monotonic(prev, v)


def _assert_monotonic(prev: lc.OrderView, v: lc.OrderView) -> None:
    """Properties every step keeps, quarantined or not."""
    assert v.canceled_floor >= prev.canceled_floor  # a venue-stated cancel count never shrinks
    if prev.cancel_basis is lc.CancelBasis.VENUE_COUNT:
        assert v.cancel_basis is lc.CancelBasis.VENUE_COUNT and v.canceled_floor == prev.canceled_floor
    assert set(prev.count_observations) <= set(v.count_observations)  # venue evidence is never dropped
    assert v.filled_quantity <= v.venue_filled_reported + v.fill_quantity_applied
    assert v.filled_quantity >= max(v.venue_filled_reported, v.fill_quantity_applied)
    fields = ("total_quantity", "filled_quantity", "remaining_quantity", "canceled_quantity", "canceled_floor")
    changed = any(getattr(prev, f) != getattr(v, f) for f in fields)
    assert len(v.count_log) == len(prev.count_log) + (1 if changed else 0)  # no count change goes unlogged
    if changed:
        assert type(v.receipts[-1]).__name__ in v.count_log[-1]


# ---------------------------------------------------------------- review regressions (REQUEST_CHANGES on 9c31ef1)


@pytest.mark.parametrize("first,second", [
    (CancelConfirmed(PID, reduced_by=D(6)), CancelConfirmed(PID, reduced_by=D(4))),
    (CancelConfirmed(PID, reduced_by=D(10)), ack("canceled", "3", "0")),
    (CancelConfirmed(PID, reduced_by=D(10)), Expired(PID, filled_quantity=D(3))),
    (CancelConfirmed(PID, reduced_by=D(10)), recon("canceled", "3", "0")),
    (Expired(PID, filled_quantity=D(3)), CancelConfirmed(PID, reduced_by=D(5))),
], ids=["reduced-6-then-4", "reduced-10-then-ack-3", "reduced-10-then-expired-3", "reduced-10-then-reconcile-3",
        "expired-3-then-reduced-5"])
def test_finding1_a_venue_stated_cancel_count_is_never_overwritten(first, second):
    v = ok(reduce_all(resting(), [CancelRequested(), first]))
    floor, filled = v.canceled_floor, v.filled_quantity
    out = reduce(v, second)
    assert out.quarantined and any(r.startswith(("CANCEL_COUNT_CONFLICT", "COUNT_BELOW", "FINAL_COUNTS"))
                                   for r in out.quarantine_reasons), out.quarantine_reasons
    assert (out.canceled_floor, out.filled_quantity) == (floor, filled)  # nothing filled without a receipt


def test_finding1_the_same_venue_cancel_count_again_is_idempotent():
    v = reduce_all(resting(), [CancelRequested(), CancelConfirmed(PID, reduced_by=D(6))])
    again = ok(reduce_all(v, [CancelConfirmed(PID, reduced_by=D(6)), ack("canceled", "4", "0"),
                              recon("canceled", "4", "0")]))
    assert counts(again) == counts(v) == (D(10), D(4), D(0), D(6)) and again.canceled_floor == 6


def test_finding2_counts_and_fills_that_interleave_are_not_undercounted():
    """Fill A (3) is delayed, B (2) arrives, a snapshot says 5, then maker fill C (4): the venue has 9."""
    v = reduce_all(resting(), [fill("B", "2", at=t(2)), recon("resting", "5", "5", as_of=t(3))])
    assert v.filled_quantity == 5 and v.unreceived_fill_quantity == 3 and not v.fees_complete
    v = ok(reduce(v, fill("C", "4", at=t(4), liq=Liquidity.MAKER)))
    assert v.filled_quantity == 9 and v.fill_quantity_applied == 6 and not v.fees_complete
    v = ok(reduce(v, fill("A", "3", at=t(1))))
    assert counts(v) == (D(10), D(9), D(1), D(0)) and v.fees_complete and not v.fill_timing_uncertain


def test_finding2_received_and_reported_are_kept_apart():
    v = ok(reduce_all(resting(), [ack("resting", "4", "6", at=t(10)), fill("f1", "1", at=t(20))]))
    assert (v.venue_filled_reported, v.fill_quantity_applied, v.filled_quantity) == (D(4), D(1), D(5))
    assert [o.count for o in v.count_observations] == [D(0), D(4)]


def test_finding3_a_fill_at_the_pending_amend_price_is_within_the_limit():
    v = reduce(resting(), AmendRequested(new_price=D("0.45")))
    out = ok(reduce(v, fill("f1", "2", price="0.45")))
    assert out.filled_quantity == 2
    quarantined(reduce(v, fill("f1", "2", price="0.46")), "FILL_PRICE_BEYOND_LIMIT")
    quarantined(reduce(resting(), fill("f1", "2", price="0.45")), "FILL_PRICE_BEYOND_LIMIT")  # no amend pending


def test_finding4_a_replacement_id_seen_before_the_amend_reply_joins_the_lineage():
    v = reduce(resting(), AmendRequested(new_total=D(12)))
    v = ok(reduce(v, ack("resting", "0", "12", pid="prov-0002", cid=CID)))
    assert v.provider_order_id == "prov-0002" and v.prior_provider_order_ids == (PID,)
    assert v.total_quantity == 12 and v.amend_pending is None and v.amend_reply_owed
    assert lc.amend_problems(v, D(13), None)  # the reply is still owed
    v = ok(reduce(v, fill("f1", "1", pid="prov-0002", cid=CID)))
    v = ok(reduce(v, AmendAcknowledged(PID, D(12), D("0.42"), new_provider_order_id="prov-0002")))
    assert not v.amend_reply_owed and "DUPLICATE_AMEND_ACK" in v.notes[-1] and v.filled_quantity == 1


def test_finding4_a_replacement_id_after_an_ambiguous_amend():
    v = reduce_all(resting(), [AmendRequested(new_total=D(12)), AMB(Operation.AMEND)])
    v = ok(reduce(v, fill("f1", "11", pid="prov-0002", cid=CID)))  # beyond the old total: waits for the amend
    assert v.parked_fills and v.provider_order_id == "prov-0002"
    v = ok(reduce(v, recon("resting", "11", "1", pid="prov-0002", total="12", price="0.42")))
    assert v.state is OrderState.RESTING and counts(v) == (D(12), D(11), D(1), D(0)) and not v.parked_fills
    assert v.prior_provider_order_ids == (PID,)


def test_finding4_an_unknown_provider_id_still_mismatches_without_a_pending_amend():
    quarantined(reduce(resting(), fill("f1", "1", pid="prov-0002", cid=CID)), "IDENTITY_MISMATCH")
    pending = reduce(resting(), AmendRequested(new_total=D(12)))
    quarantined(reduce(pending, fill("f1", "1", pid="prov-0002")), "IDENTITY_MISMATCH")  # no client id
    quarantined(reduce(pending, fill("f1", "1", pid="prov-0002", cid="cid-other")), "IDENTITY_MISMATCH")


def test_finding4_nit_the_same_fill_id_under_the_new_provider_id_matches_the_lineage():
    v = reduce_all(resting(), [fill("f1", "2", pid=PID), AmendRequested(new_total=D(12)),
                               AmendAcknowledged(PID, D(12), D("0.42"), new_provider_order_id="prov-0002")])
    again = ok(reduce(v, fill("f1", "2", pid="prov-0002")))
    assert len(again.fills) == 1 and again.filled_quantity == 2 and "DUPLICATE_FILL" in again.notes[-1]
    quarantined(reduce(v, fill("f1", "2", pid="prov-9999", cid=CID)), "IDENTITY_MISMATCH")


def test_finding5_a_bare_reject_does_not_settle_a_lost_send():
    v = reduce(sent(), AMB(Operation.NEW_ORDER))
    out = ok(reduce(v, Rejected(Operation.NEW_ORDER, "SOMETHING")))
    assert out.state is OrderState.OUTCOME_UNKNOWN and "BARE_REJECT_WHILE_UNKNOWN" in out.notes[-1]
    assert ok(reduce(out, recon(found=False, as_of=t(59)))).state is OrderState.REJECTED
    assert ok(reduce(out, Rejected(Operation.NEW_ORDER, "X", client_order_id=CID))).state is OrderState.REJECTED
    direct = ok(reduce(sent(), Rejected(Operation.NEW_ORDER, "INSUFFICIENT_FUNDS")))  # the send's own reply
    assert direct.state is OrderState.REJECTED


def test_finding6_absence_needs_a_timed_snapshot_taken_after_the_send():
    v = reduce(sent(), AMB(Operation.NEW_ORDER))
    assert v.sent_at_utc == SENT
    untimed = ok(reduce(v, ReconcileObserved(CID, None, False, authoritative_complete=True, as_of_utc=None)))
    assert untimed.state is OrderState.OUTCOME_UNKNOWN and "no usable time" in untimed.notes[-1]
    before = ok(reduce(v, recon(found=False, as_of="2026-10-07T14:59:00+00:00")))
    assert before.state is OrderState.OUTCOME_UNKNOWN and "NOT_FOUND_TOO_EARLY" in before.notes[-1]
    soon = ok(reduce(v, recon(found=False, as_of=t(29))))
    assert soon.state is OrderState.OUTCOME_UNKNOWN  # within NOT_FOUND_MIN_DELAY of the send
    assert ok(reduce(v, recon(found=False, as_of=t(30)))).state is OrderState.REJECTED
    for bad in (None, "2026-10-07T15:00:00", "yesterday"):
        with pytest.raises((TypeError, ValueError)):
            SendPrepared(bad)


@pytest.mark.parametrize("complete,fragment", [(True, None), (False, "COUNT_BELOW_EARLIER_VENUE_COUNT")])
def test_finding8_a_reconcile_below_an_earlier_venue_count(complete, fragment):
    v = reduce(resting(), ack("resting", "5", "5", at=t(10)))
    out = reduce(v, recon("resting", "3", "7", as_of=t(20), complete=complete))
    if fragment is None:
        quarantined(out, "COUNT_BELOW_KNOWN_FILLS")
    else:
        assert not out.quarantined and fragment in out.notes[-1] and out.filled_quantity == 5
    older = ok(reduce(v, recon("resting", "3", "7", as_of=t(5))))
    assert older.filled_quantity == 5 and "COUNT_BELOW_EARLIER_VENUE_COUNT" in older.notes[-1]


def test_nit_executed_without_counts_is_noted():
    out = ok(reduce(sent(), Acknowledged(PID, CID, "executed", None, None)))
    assert "EXECUTED_WITHOUT_COUNTS" in out.notes[-1] and out.filled_quantity == 0


def test_every_count_change_is_logged():
    v = reduce_all(resting(), [fill("f1", "4"), CancelRequested(), CancelConfirmed(PID)])
    assert len(v.count_log) == 2 and "Fill" in v.count_log[0] and "CancelConfirmed" in v.count_log[1]
