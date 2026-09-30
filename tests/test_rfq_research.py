"""RFQ research lifecycle (R4, ADR 0042): synthetic fixtures only. No network, no credentials."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

import pytest

from edge_lab import rfq_research as rr, venues
from edge_lab.execution_ticket import HELD_OBLIGATION_STATES, ObligationState
from edge_lab.rfq_research import (
    HypotheticalQuote, Kind, Observer, QuoteState, SizeMode, TimingClass, Visibility, derive_contracts,
    hypothetical_check, obligations, observe, quote_is_current, reserve_simultaneous,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
ME, MAKER_B, MAKER_C, REQ_X = "comm_me", "comm_b", "comm_c", "comm_x"
BOUND = 1_000
MKT = "KXNFLGAME-26OCT04BUFNE-BUF"
IDX = {MKT: 0}


def ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def rfq_created(rid, creator, *, market=MKT, contracts="100.00", target=None, legs=None, t=0, seq=1):
    msg = {"id": rid, "creator_id": creator, "market_ticker": market, "created_ts": ts(t)}
    if target is None:
        msg["contracts_fp"] = contracts
    else:
        msg["target_cost_dollars"] = target
    if legs:
        msg["mve_selected_legs"] = [{"event_ticker": e, "market_ticker": m, "side": s} for e, m, s in legs]
    return {"type": "rfq_created", "sid": 1, "seq": seq, "msg": msg}


def rfq_deleted(rid, creator, *, market=MKT, t=20, seq=2):
    return {"type": "rfq_deleted", "sid": 1, "seq": seq,
            "msg": {"id": rid, "creator_id": creator, "market_ticker": market, "deleted_ts": ts(t)}}


def quote_created(qid, rid, maker, rfq_creator, *, yes="0.40", no="0.55", size="100.00", t=1, seq=3, market=MKT):
    return {"type": "quote_created", "sid": 1, "seq": seq, "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "market_ticker": market, "yes_bid_dollars": yes, "no_bid_dollars": no,
        "yes_contracts_offered_fp": size, "no_contracts_offered_fp": size, "created_ts": ts(t)}}


def quote_accepted(qid, rid, maker, rfq_creator, *, side="yes", accepted="100.00", yes="0.40", no="0.55",
                   received=2, seq=4):
    """The documented message has no acceptance timestamp; `received_at_utc` is our own receipt stamp."""
    return {"type": "quote_accepted", "sid": 1, "seq": seq, "received_at_utc": ts(received), "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "market_ticker": MKT, "yes_bid_dollars": yes, "no_bid_dollars": no,
        "accepted_side": side, "contracts_accepted_fp": accepted}}


def quote_status(kind, qid, rid, maker, rfq_creator, *, t=3):
    stamp = {"quote_confirmed": "confirmed_ts", "quote_cancelled": "cancelled_ts"}[kind]
    return {"type": kind, "msg": {"quote_id": qid, "rfq_id": rid, "quote_creator_id": maker,
                                  "rfq_creator_id": rfq_creator, stamp: ts(t)}}


def quote_executed(qid, rid, maker, rfq_creator, *, order="ord-1", t=20, seq=5):
    return {"type": "quote_executed", "sid": 1, "seq": seq, "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "order_id": order, "client_order_id": "c-" + order, "market_ticker": MKT, "executed_ts": ts(t)}}


def fill(fid, order, count, *, t=21, **extra):
    return {"type": "fill", "msg": {"fill_id": fid, "order_id": order, "count_fp": count, "created_time": ts(t),
                                    **extra}}


def sequenced(msgs):
    """Give every channel message (those with a sid) contiguous sequence numbers, in list order."""
    n, out = 0, []
    for m in msgs:
        if "sid" in m:
            n += 1
            m = dict(m, seq=n)
        out.append(m)
    return out


def run(msgs, who=ME, **kw):
    return observe(msgs, Observer(who), max_messages=kw.pop("max_messages", BOUND), **kw)


def fresh(**kw):
    """Arguments stating the stream was received through `now` (gap-freeness comes from seq)."""
    now = kw.pop("now", T0 + timedelta(seconds=5))
    return dict(now=now, observed_through_utc=kw.pop("through", now), max_age=kw.pop("max_age", timedelta(seconds=5)))


# ------------------------------------------------------------------ privacy and observability


def test_outside_observer_cannot_report_private_quote_prices():
    rep = run([rfq_created("r1", REQ_X), rfq_created("r2", REQ_X, seq=2, market="KXNFLGAME-26OCT04BUFNE-NE")])
    assert rep.status == "OK" and len(rep.rfqs) == 2
    assert rep.competitor_quote_prices is Visibility.UNAVAILABLE
    assert all(r.competitor_quote_prices is Visibility.UNAVAILABLE for r in rep.rfqs.values())
    assert rep.quotes == {}  # no price is invented, and none is 0
    assert rep.other_parties_fills is Visibility.UNAVAILABLE
    assert rep.queue_rank is Visibility.UNSUPPORTED


def test_a_quote_event_between_other_parties_is_never_used():
    """The docs say it is never delivered to a non-party. If a fixture contains one, it is counted
    as contradicting the docs and its prices are not surfaced."""
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", MAKER_B, REQ_X, yes="0.10", no="0.20")])
    assert rep.not_addressed_to_observer == 1 and "q1" not in rep.quotes
    assert rep.rfqs["r1"].competitor_quote_prices is Visibility.UNAVAILABLE


def test_our_own_quote_is_visible_but_competing_quotes_on_that_rfq_are_not():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
               quote_created("q2", "r1", MAKER_B, REQ_X, yes="0.45", seq=4)])
    assert set(rep.quotes) == {"q1"} and rep.quotes["q1"].yes_bid == Decimal("0.40")
    assert rep.rfqs["r1"].competitor_quote_prices is Visibility.UNAVAILABLE


def test_requester_sees_every_quote_on_its_own_rfq():
    rep = run([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
               quote_created("q2", "r1", MAKER_C, ME, yes="0.42", seq=4)])
    assert set(rep.quotes) == {"q1", "q2"} and rep.rfqs["r1"].competitor_quote_prices is Visibility.VISIBLE


def test_unauthenticated_observer_sees_nothing():
    rep = observe([rfq_created("r1", REQ_X)], Observer(None), max_messages=BOUND)
    assert rep.status == "REFUSED_NOT_AUTHENTICATED" and rep.rfqs == {}
    assert rep.requested_contracts_upper_bound is None


# ------------------------------------------------------------------ volume layers


def test_request_volume_is_not_executed_volume():
    rep = run([rfq_created(f"r{i}", REQ_X, seq=i) for i in range(5)])
    assert rep.requested_contracts_upper_bound == Decimal("500.00")
    assert rep.accepted_contracts_notified is None and rep.filled_contracts is None


def test_target_cost_rfqs_are_not_converted_to_contracts_and_their_fee_mode_is_unknown():
    rep = run([rfq_created("r1", REQ_X, target="250.00"), rfq_created("r2", REQ_X, seq=2)])
    assert rep.requested_contracts_upper_bound == Decimal("100.00")  # only the contracts-sized one
    assert rep.requested_target_cost_dollars == Decimal("250.00")
    r1 = rep.rfqs["r1"]
    assert r1.requested_contracts is None and r1.size_mode is None  # the channel omits the fee mode


def test_accepted_or_confirmed_is_never_a_fill():
    base = [rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
            quote_accepted("q1", "r1", MAKER_B, ME), quote_status("quote_confirmed", "q1", "r1", MAKER_B, ME)]
    rep = run(base)
    assert rep.quotes["q1"].state is QuoteState.CONFIRMED
    assert rep.accepted_contracts_notified == Decimal("100.00") and rep.filled_contracts is None

    rep = run(base + [quote_executed("q1", "r1", MAKER_B, ME)])
    assert rep.quotes["q1"].state is QuoteState.ORDERS_PLACED and rep.filled_contracts is None

    rep = run(base + [quote_executed("q1", "r1", MAKER_B, ME), fill("f1", "ord-1", "60.00")])
    assert rep.filled_contracts == Decimal("60.00")  # the fill record, not the 100 accepted
    assert rep.quotes["q1"].contracts_accepted_notified == Decimal("100.00")


def test_a_fill_for_an_unknown_order_is_not_attributed_to_a_quote():
    rep = run([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME), fill("f9", "ord-other", "5.00")])
    assert rep.filled_contracts is None and rep.unattributed_fills == 1


def test_the_same_fill_in_two_shapes_is_not_double_counted():
    base = [rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME), quote_executed("q1", "r1", MAKER_B, ME)]
    same = run(base + [fill("f1", "ord-1", "60.00"), fill("f1", "ord-1", "60.00")])
    assert same.filled_contracts == Decimal("60.00") and same.duplicate_messages == 1
    two_shapes = run(base + [fill("f1", "ord-1", "60.00"), fill("f1", "ord-1", "60.00", fee_cost="0.84")])
    assert two_shapes.conflicting_fills == ("f1",) and two_shapes.filled_contracts is None  # not 120
    assert two_shapes.quotes["q1"].state is QuoteState.UNKNOWN
    assert two_shapes.quotes["q1"].reasons == ("FILL_RECORD_CONFLICT",)


# ------------------------------------------------------------------ hypothetical price and reuse


def test_a_state_change_invalidates_a_hypothetical_pending_price():
    rep = run(sequenced([rfq_created("r1", REQ_X)]))
    h = HypotheticalQuote("r1", Decimal("0.40"), Decimal("0.55"), "state-v7", ts(0))
    now = T0 + timedelta(seconds=1)
    args = dict(now=now, max_age=timedelta(seconds=5), observed_through_utc=now)
    assert hypothetical_check(h, rep, current_state_version="state-v7", **args) == ("PARTICIPATION_NOT_AUTHORIZED",)
    moved = hypothetical_check(h, rep, current_state_version="state-v8", **args)
    assert moved[0] == "STATE_CHANGED" and moved[-1] == "PARTICIPATION_NOT_AUTHORIZED"
    assert hypothetical_check(h, rep, current_state_version=None, **args)[0] == "STATE_VERSION_UNKNOWN"
    closed = run(sequenced([rfq_created("r1", REQ_X), rfq_deleted("r1", REQ_X)]))
    assert "RFQ_NOT_KNOWN_OPEN" in hypothetical_check(h, closed, current_state_version="state-v7", **args)
    stale_view = dict(args, observed_through_utc=T0 - timedelta(minutes=1))
    assert "OBSERVATION_STALE_OR_GAPPED" in hypothetical_check(h, rep, current_state_version="state-v7",
                                                               **stale_view)


def test_hypothetical_price_rules_follow_the_documented_quote_rules():
    rep = run(sequenced([rfq_created("r1", REQ_X)]))
    now = T0 + timedelta(seconds=1)
    args = dict(current_state_version="v", now=now, max_age=timedelta(seconds=5), observed_through_utc=now)
    over = HypotheticalQuote("r1", Decimal("0.60"), Decimal("0.45"), "v", ts(0))
    assert "YES_PLUS_NO_ABOVE_ONE" in hypothetical_check(over, rep, **args)
    both_zero = HypotheticalQuote("r1", Decimal("0"), Decimal("0"), "v", ts(0))
    assert "PRICE_INVALID" in hypothetical_check(both_zero, rep, **args)
    later = T0 + timedelta(minutes=5)
    stale = hypothetical_check(HypotheticalQuote("r1", Decimal("0.4"), Decimal("0.5"), "v", ts(0)), rep,
                               **dict(args, now=later, observed_through_utc=later))
    assert "PRICE_STALE" in stale


def test_expired_or_replaced_quotes_cannot_be_reused():
    rep = run(sequenced([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X, t=1),
                         quote_created("q2", "r1", ME, REQ_X, yes="0.41", t=2)]))
    assert rep.quotes["q1"].state is QuoteState.REPLACED
    assert quote_is_current("q1", rep, **fresh()) == (False, "REPLACED")
    assert quote_is_current("q2", rep, **fresh()) == (True, "OPEN")

    closed = run(sequenced([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
                            rfq_deleted("r1", REQ_X)]))
    assert quote_is_current("q1", closed, **fresh()) == (False, "RFQ_CLOSED_REASON_UNKNOWN")

    # Accepted but never confirmed: past the window the quote is not current, but nothing is released.
    acc = run(sequenced([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
                         quote_accepted("q1", "r1", MAKER_B, ME, received=2)]),
              timing_class={MKT: TimingClass.STANDARD})
    assert quote_is_current("q1", acc, **fresh(now=T0 + timedelta(seconds=10))) == \
        (False, "ACCEPTED_AWAITING_CONFIRMATION")
    assert quote_is_current("q1", acc, **fresh(now=T0 + timedelta(seconds=40))) == \
        (False, "CONFIRMATION_WINDOW_ELAPSED")
    assert any(o.state is QuoteState.ACCEPTED and o.principal is not None for o in obligations(acc))


def test_acceptance_time_comes_only_from_our_receipt_stamp():
    msgs = sequenced([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
                      quote_accepted("q1", "r1", MAKER_B, ME, received=2)])
    rep = run(msgs, timing_class={MKT: TimingClass.STANDARD})
    assert rep.quotes["q1"].accepted_received_at_utc == T0 + timedelta(seconds=2)
    no_receipt = [dict(m) for m in msgs]
    del no_receipt[2]["received_at_utc"]
    rep2 = run(no_receipt, timing_class={MKT: TimingClass.STANDARD})
    assert rep2.quotes["q1"].accepted_received_at_utc is None
    assert quote_is_current("q1", rep2, **fresh()) == (False, "ACCEPTED_CONFIRMATION_WINDOW_UNKNOWN")


def test_currency_needs_a_recent_gap_free_observation():
    msgs = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)]
    ok = run(sequenced(msgs))
    assert quote_is_current("q1", ok, **fresh()) == (True, "OPEN")
    assert quote_is_current("q1", ok, **fresh(through=T0 - timedelta(minutes=1))) == \
        (False, "OBSERVATION_STALE_OR_GAPPED")
    assert quote_is_current("q1", ok, **fresh(through=None)) == (False, "OBSERVATION_STALE_OR_GAPPED")
    gapped = run([rfq_created("r1", REQ_X, seq=1), quote_created("q1", "r1", ME, REQ_X, seq=3)])
    assert gapped.seq_gaps == 1
    assert quote_is_current("q1", gapped, **fresh()) == (False, "OBSERVATION_STALE_OR_GAPPED")
    no_seq = run([{k: v for k, v in m.items() if k != "seq"} for m in msgs])
    assert no_seq.seq_gaps is None
    assert quote_is_current("q1", no_seq, **fresh()) == (False, "OBSERVATION_STALE_OR_GAPPED")


def test_combo_rfqs_use_the_hvm_confirmation_window():
    legs = [("KXNFLGAME-26OCT04BUFNE", MKT, "yes"), ("KXNFLGAME-26OCT04KCLV", "KXNFLGAME-26OCT04KCLV-KC", "yes")]
    rep = run(sequenced([rfq_created("r1", ME, market="KXMVECOMBO-X", legs=legs),
                         quote_created("q1", "r1", MAKER_B, ME), quote_accepted("q1", "r1", MAKER_B, ME, received=2)]))
    assert rep.rfqs["r1"].timing_class is TimingClass.HVM
    assert quote_is_current("q1", rep, **fresh(now=T0 + timedelta(seconds=6)))[1] == "CONFIRMATION_WINDOW_ELAPSED"


def test_equal_timestamps_make_replacement_ambiguous_and_keep_both_reserved():
    rep = run(sequenced([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X, t=1),
                         quote_created("q2", "r1", ME, REQ_X, yes="0.41", t=1)]))
    assert {q.state for q in rep.quotes.values()} == {QuoteState.OPEN}
    assert quote_is_current("q1", rep, **fresh()) == (False, "REPLACEMENT_ORDER_AMBIGUOUS")
    assert len(obligations(rep)) == 2


# ------------------------------------------------------------------ idempotency and unknown state


def _lifecycle():
    return [rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
            quote_created("q2", "r1", MAKER_C, ME, yes="0.42", seq=4),
            quote_accepted("q1", "r1", MAKER_B, ME, seq=5), quote_status("quote_confirmed", "q1", "r1", MAKER_B, ME),
            quote_executed("q1", "r1", MAKER_B, ME, seq=6), fill("f1", "ord-1", "100.00"),
            rfq_deleted("r1", ME, seq=7)]


def _summary(rep):
    return (rep.requested_contracts_upper_bound, rep.accepted_contracts_notified, rep.filled_contracts,
            {k: (v.state, v.filled_contracts) for k, v in rep.quotes.items()},
            {k: v.open for k, v in rep.rfqs.items()},
            tuple((o.source_id, o.state, o.principal) for o in obligations(rep, exchange_index=IDX)))


def test_duplicate_and_out_of_order_events_are_idempotent():
    msgs = _lifecycle()
    expected = _summary(run(msgs))
    assert expected[3]["q1"] == (QuoteState.ORDERS_PLACED, Decimal("100.00"))
    assert expected[3]["q2"][0] is QuoteState.RFQ_CLOSED_REASON_UNKNOWN
    rng = random.Random(145)
    for _ in range(25):
        redelivered = [dict(m, seq=m["seq"] + 100) if "seq" in m else dict(m) for m in rng.sample(msgs, 3)]
        shuffled = msgs + redelivered
        rng.shuffle(shuffled)
        rep = run(shuffled)
        assert _summary(rep) == expected and rep.duplicate_messages == 3


def test_contradictory_terminal_evidence_is_unknown_and_keeps_exposure():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
               quote_accepted("q1", "r1", ME, REQ_X), quote_status("quote_confirmed", "q1", "r1", ME, REQ_X),
               quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)])
    assert rep.quotes["q1"].state is QuoteState.UNKNOWN
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.principal == Decimal("55.0000")  # worst side: NO at 0.55 x 100, not released


def test_undocumented_and_malformed_messages_are_counted_not_used():
    msgs = [rfq_created("r1", REQ_X), {"type": "quote_repriced", "msg": {"quote_id": "q9"}},
            {"type": "quote_created", "msg": {"rfq_id": "r1"}}, "not-a-mapping"]
    rep = run(msgs)
    assert rep.undocumented_messages == ("quote_repriced",) and rep.malformed_messages == 2
    assert rep.quotes == {}


def test_out_of_range_bids_and_negative_sizes_are_malformed():
    bad = [quote_created("q1", "r1", ME, REQ_X, yes="-0.40"), quote_created("q2", "r1", ME, REQ_X, no="1.20"),
           quote_created("q3", "r1", ME, REQ_X, size="-100.00"), rfq_created("r2", REQ_X, contracts="-5", seq=9),
           fill("f1", "ord-1", "-3.00")]
    rep = run([rfq_created("r1", REQ_X)] + bad)
    assert rep.malformed_messages == 5 and rep.quotes == {} and set(rep.rfqs) == {"r1"}


def test_missing_fields_stay_unknown_not_zero():
    msgs = [rfq_created("r1", REQ_X),
            {"type": "quote_created", "msg": {"quote_id": "q1", "rfq_id": "r1", "quote_creator_id": ME,
                                              "rfq_creator_id": REQ_X, "yes_bid_dollars": "0.40",
                                              "no_bid_dollars": "bad", "created_ts": ts(1)}}]
    rep = run(msgs)
    q = rep.quotes["q1"]
    assert q.no_bid is None and q.yes_contracts is None
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.principal is None  # the NO side could be accepted at an unknown price: unknown, not 40
    ok = dict(msgs[1], msg=dict(msgs[1]["msg"], no_bid_dollars="0"))  # NO side explicitly declined
    (ob1,) = obligations(run([msgs[0], ok]), exchange_index=IDX)
    assert ob1.principal == Decimal("40.0000")  # sized from the RFQ's 100 contracts
    (ob2,) = obligations(run([rfq_created("r1", REQ_X, target="30.00"), ok]), exchange_index=IDX)
    assert ob2.principal is None  # a target-cost RFQ with no offered size: unknown


# ------------------------------------------------------------------ release rules


def test_released_only_by_the_quotes_own_cancelled_status():
    base = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)]
    assert len(obligations(run(base))) == 1
    assert obligations(run(base + [quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)])) == ()
    # An RFQ closure is not the quote's terminal status: the reservation stays.
    (closed,) = obligations(run(base + [rfq_deleted("r1", REQ_X)]))
    assert closed.state is QuoteState.RFQ_CLOSED_REASON_UNKNOWN and closed.principal == Decimal("55.0000")
    # A replacement keeps the old quote reserved until its own cancellation is seen.
    replaced = run(base + [quote_created("q2", "r1", ME, REQ_X, t=5, seq=4)])
    assert {o.source_id for o in obligations(replaced)} == {"q1", "q2"}
    # Accepted, then the RFQ closed with no confirmation seen: still reserved.
    (acc,) = obligations(run(base + [quote_accepted("q1", "r1", ME, REQ_X), rfq_deleted("r1", REQ_X)]))
    assert acc.state is QuoteState.ACCEPTED


def test_lost_acceptance_then_rfq_close_with_an_own_fill_keeps_exposure():
    """The reviewer's scenario: accept/execute lost in a gap, rfq_deleted arrives, an own fill exists."""
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X), rfq_deleted("r1", REQ_X),
               fill("f1", "ord-lost", "100.00")])
    assert rep.unattributed_fills == 1
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.principal == Decimal("55.0000")


def test_an_unattributed_own_fill_blocks_every_release():
    base = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
            quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)]
    assert obligations(run(base)) == ()
    (ob,) = obligations(run(base + [fill("f1", "ord-lost", "10.00")]), exchange_index=IDX)
    assert ob.state is QuoteState.CANCELLED and "release blocked" in ob.reason
    assert ob.obligation_state is ObligationState.UNKNOWN


# ------------------------------------------------------------------ requester obligations


def test_requester_obligation_reserves_the_worse_reading_of_the_accepted_side():
    rep = run([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME, yes="0.30", no="0.65"),
               quote_accepted("q1", "r1", MAKER_B, ME, side="yes", yes="0.30", no="0.65")])
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.role == "REQUESTER" and ob.principal == Decimal("70.00")  # max(0.30, 0.70) x 100


@pytest.mark.parametrize("evidence", ["confirmed", "executed"])
def test_requester_obligation_exists_without_an_acceptance_notice(evidence):
    later = (quote_status("quote_confirmed", "q1", "r1", MAKER_B, ME) if evidence == "confirmed"
             else quote_executed("q1", "r1", MAKER_B, ME))
    rep = run([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME, yes="0.30", no="0.65"), later])
    (ob,) = obligations(rep, exchange_index=IDX)
    # Side unknown: max(max(0.30, 0.70) x 100, max(0.65, 0.35) x 100)
    assert ob.role == "REQUESTER" and ob.principal == Decimal("70.00")


def test_requester_side_unknown_with_a_missing_input_is_exposure_unknown():
    rep = run([rfq_created("r1", ME),
               {"type": "quote_created", "msg": {"quote_id": "q1", "rfq_id": "r1", "quote_creator_id": MAKER_B,
                                                 "rfq_creator_id": ME, "yes_bid_dollars": "0.30",
                                                 "created_ts": ts(1)}},
               quote_status("quote_confirmed", "q1", "r1", MAKER_B, ME)])
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.principal is None
    assert reserve_simultaneous([ob], {0: Decimal("1000")}, fee_allowance=lambda o: Decimal(0)).status == \
        "EXPOSURE_UNKNOWN"


def test_contradictory_acceptances_reserve_the_worst_over_both_sides():
    rep = run([rfq_created("r1", ME),
               {"type": "quote_created", "msg": {
                   "quote_id": "q1", "rfq_id": "r1", "quote_creator_id": MAKER_B, "rfq_creator_id": ME,
                   "yes_bid_dollars": "0.10", "no_bid_dollars": "0.85", "yes_contracts_offered_fp": "10.00",
                   "no_contracts_offered_fp": "1000.00", "created_ts": ts(1)}},
               quote_accepted("q1", "r1", MAKER_B, ME, side="yes", yes="0.10", no="0.85"),
               quote_accepted("q1", "r1", MAKER_B, ME, side="no", yes="0.10", no="0.85", seq=5)])
    assert rep.quotes["q1"].state is QuoteState.UNKNOWN
    (ob,) = obligations(rep, exchange_index=IDX)
    assert ob.principal == Decimal("850.0000")  # not the $9 of the YES reading


# ------------------------------------------------------------------ collateral


LEG_SHARED = ("KXNFLGAME-26OCT04BUFNE", MKT, "yes")


def test_requests_sharing_legs_cannot_reuse_the_same_collateral():
    a = rfq_created("rA", REQ_X, market="KXMVE-A", legs=[LEG_SHARED, ("E2", "E2-M", "yes")])
    b = rfq_created("rB", REQ_X, market="KXMVE-B", legs=[LEG_SHARED, ("E3", "E3-M", "no")], seq=2)
    msgs = [a, b, quote_created("qA", "rA", ME, REQ_X, yes="0.60", no="0", market="KXMVE-A"),
            quote_created("qB", "rB", ME, REQ_X, yes="0.60", no="0", seq=4, market="KXMVE-B")]
    obs = obligations(run(msgs), exchange_index={"KXMVE-A": 1, "KXMVE-B": 1})
    assert [o.principal for o in obs] == [Decimal("60.0000"), Decimal("60.0000")]
    zero_fee = dict(fee_allowance=lambda o: Decimal("0"))
    res = reserve_simultaneous(obs, {1: Decimal("100")}, **zero_fee)
    assert res.status == "INSUFFICIENT_COLLATERAL" and res.by_index[1].required == Decimal("120.0000")
    assert res.by_index[1].by_key[f"leg:{LEG_SHARED[1]}:yes"] == Decimal("120.0000")  # never netted
    assert any(r.startswith("INSUFFICIENT_CASH") for r in res.by_index[1].reasons)
    # Cash on another exchange index does not help: collateral is preallocated per shard.
    assert reserve_simultaneous(obs, {0: Decimal("1000"), 1: Decimal("100")}, **zero_fee).status == \
        "INSUFFICIENT_COLLATERAL"
    assert reserve_simultaneous(obs, {1: Decimal("120")}, **zero_fee).status == "OK"
    assert reserve_simultaneous(obs, {1: Decimal("120")}).status == "FEE_UNSUPPORTED"


def test_negative_principal_or_fee_allowance_is_unknown_not_a_credit():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)])
    (ob,) = obligations(rep, exchange_index=IDX)
    with pytest.raises(rr.RfqResearchError):  # refused, as the canonical primitive refuses it
        rr.Obligation("neg", "r1", "QUOTER", QuoteState.OPEN, ObligationState.OUTSTANDING, Decimal("-500"), 0, (),
                      MKT, "synthetic")
    assert reserve_simultaneous([ob], {0: Decimal("1000")},
                                fee_allowance=lambda o: Decimal("-100")).status == "EXPOSURE_UNKNOWN"


def test_unknown_exchange_index_or_principal_fails_closed():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)])
    res = reserve_simultaneous(obligations(rep), {0: Decimal("1000")}, fee_allowance=lambda o: Decimal("0"))
    assert res.status == "EXPOSURE_UNKNOWN" and res.unknown_shard == ("q1",)
    unknown_principal = obligations(run([rfq_created("r1", REQ_X, target="30.00"),
                                         quote_created("q1", "r1", ME, REQ_X, size=None)]), exchange_index=IDX)
    res2 = reserve_simultaneous(unknown_principal, {0: Decimal("1000")}, fee_allowance=lambda o: Decimal("0"))
    assert res2.status == "EXPOSURE_UNKNOWN" and res2.by_index[0].required is None
    assert res2.by_index[0].by_key[f"market:{MKT}"] is None  # unknown stays unknown per key, never 0
    assert reserve_simultaneous(obligations(run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)]),
                                            exchange_index=IDX), {}, fee_allowance=lambda o: Decimal("0")
                                ).status == "CASH_UNKNOWN"


def test_an_unknown_shard_obligation_makes_every_shard_and_shared_key_unknown():
    a = rfq_created("rA", REQ_X, market="KXMVE-A", legs=[LEG_SHARED, ("E2", "E2-M", "yes")])
    b = rfq_created("rB", REQ_X, market="KXMVE-B", legs=[LEG_SHARED, ("E3", "E3-M", "no")], seq=2)
    rep = run([a, b, quote_created("qA", "rA", ME, REQ_X, yes="0.50", no="0", market="KXMVE-A"),
               quote_created("qB", "rB", ME, REQ_X, yes="0.50", no="0", size="1000.00", seq=4, market="KXMVE-B")])
    obs = obligations(rep, exchange_index={"KXMVE-A": 1})  # rB's shard is unknown; its worst case is 500
    res = reserve_simultaneous(obs, {1: Decimal("10000")}, fee_allowance=lambda o: Decimal("0"))
    assert res.status == "EXPOSURE_UNKNOWN" and res.unknown_shard == ("qB",)
    shard1 = res.by_index[1]
    assert shard1.required is None and shard1.new_risk_allowed is False  # not 50 and allowed
    assert shard1.by_key[f"leg:{LEG_SHARED[1]}:yes"] is None


def test_released_obligations_need_no_fee_allowance():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
               quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)])
    released = obligations(rep, exchange_index=IDX, include_released=True)
    res = reserve_simultaneous(released, {0: Decimal("0")})
    assert res.status == "OK" and res.fee_unknown == ()
    held = obligations(run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)]), exchange_index=IDX)
    assert reserve_simultaneous(held, {0: Decimal("100")}).fee_unknown == ("q1",)


def test_rfq_states_map_conservatively_onto_the_canonical_obligation_states():
    m = rr.OBLIGATION_STATE
    assert m[QuoteState.CANCELLED] is ObligationState.RELEASED
    assert all(m[s] in HELD_OBLIGATION_STATES for s in QuoteState if s is not QuoteState.CANCELLED)
    assert m[QuoteState.RFQ_CLOSED_REASON_UNKNOWN] is ObligationState.UNKNOWN
    assert m[QuoteState.REPLACED] is ObligationState.CANCEL_REQUESTED
    assert m[QuoteState.CONFIRMED] is m[QuoteState.ORDERS_PLACED] is ObligationState.BOUND
    cancelled = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
                     quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)])
    (released,) = obligations(cancelled, exchange_index=IDX, include_released=True)
    assert released.obligation_state is ObligationState.RELEASED
    res = reserve_simultaneous([released], {0: Decimal("0")}, fee_allowance=lambda o: Decimal("0"))
    assert res.status == "OK" and res.by_index[0].required == Decimal("0")  # the canonical owner frees it


# ------------------------------------------------------------------ input bound and local filter


def test_input_above_the_bound_is_refused_not_truncated():
    msgs = [rfq_created(f"r{i}", REQ_X, seq=i) for i in range(11)]
    rep = run(msgs, max_messages=10)
    assert rep.status == "REFUSED_INPUT_BOUND" and rep.received_messages == ">10"
    assert rep.rfqs == {} and rep.requested_contracts_upper_bound is None
    assert run(msgs, max_messages=11).status == "OK"


def test_the_bound_is_checked_without_consuming_an_unbounded_stream():
    consumed = []

    def endless():
        i = 0
        while True:
            consumed.append(i)
            yield rfq_created(f"r{i}", REQ_X, seq=i + 1)
            i += 1

    rep = run(endless(), max_messages=50)
    assert rep.status == "REFUSED_INPUT_BOUND" and rep.received_messages == ">50" and len(consumed) == 51


def test_the_bound_counts_every_received_message_before_local_filtering():
    msgs = [rfq_created(f"r{i}", REQ_X, seq=i, market=("KXNHLGAME-X" if i % 2 else "KXFED-Y")) for i in range(6)]
    nhl_only = lambda e: (e.market_ticker or "").startswith("KXNHLGAME")  # noqa: E731
    rep = run(msgs, keep=nhl_only, max_messages=6)
    assert rep.received_messages == "6" and rep.kept_messages == 3 and len(rep.rfqs) == 3
    assert run(msgs, keep=nhl_only, max_messages=5).status == "REFUSED_INPUT_BOUND"


def test_the_local_filter_never_drops_our_own_party_events_or_fills():
    msgs = [rfq_created("r1", REQ_X, market="KXFED-Y"), quote_created("q1", "r1", ME, REQ_X, market="KXFED-Y"),
            fill("f1", "ord-x", "1.00")]
    rep = run(msgs, keep=lambda e: (e.market_ticker or "").startswith("KXNHLGAME"))
    assert "r1" not in rep.rfqs and "q1" in rep.quotes and rep.unattributed_fills == 1
    assert len(obligations(rep)) == 1  # our exposure is still counted


def test_bound_must_be_a_whole_number():
    with pytest.raises(rr.RfqResearchError):
        observe([], Observer(ME), max_messages=True)


# ------------------------------------------------------------------ sizing modes


def synthetic_fee(contracts: Decimal, price: Decimal) -> Decimal:
    """SYNTHETIC test fee (7% x C x p x (1-p), rounded up to the cent). Not a verified Kalshi fee."""
    return (Decimal("0.07") * contracts * price * (1 - price)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def test_fee_inclusive_and_principal_only_size_modes_differ():
    principal = derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.TARGET_COST_PRINCIPAL_ONLY,
                                 fee_for=synthetic_fee)
    inclusive = derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.TARGET_COST_FEE_INCLUSIVE,
                                 fee_for=synthetic_fee)
    assert principal.contracts == Decimal("250.00") and principal.total_debit > Decimal("100")
    assert inclusive.contracts < principal.contracts and inclusive.total_debit <= Decimal("100")
    nxt = inclusive.contracts + rr.CONTRACT_STEP
    assert nxt * Decimal("0.40") + synthetic_fee(nxt, Decimal("0.40")) > Decimal("100")  # the largest that fits


def test_without_a_verified_fee_the_fee_inclusive_size_is_unsupported():
    inclusive = derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.TARGET_COST_FEE_INCLUSIVE)
    assert inclusive.status == "FEE_UNSUPPORTED" and inclusive.contracts is None
    principal = derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.TARGET_COST_PRINCIPAL_ONLY)
    assert principal.contracts == Decimal("250.00") and principal.fee is None and principal.total_debit is None
    assert principal.status == "FEE_UNSUPPORTED"
    with pytest.raises(rr.RfqResearchError):
        derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.CONTRACTS)
    assert derive_contracts(Decimal("100"), Decimal("1.00"), SizeMode.TARGET_COST_PRINCIPAL_ONLY).status == "INVALID"


def test_negative_fees_are_unknown_and_tiny_targets_are_below_min_size():
    neg = derive_contracts(Decimal("100"), Decimal("0.40"), SizeMode.TARGET_COST_PRINCIPAL_ONLY,
                           fee_for=lambda c, p: Decimal("-1"))
    assert neg.status == "FEE_UNSUPPORTED" and neg.fee is None
    for mode in (SizeMode.TARGET_COST_PRINCIPAL_ONLY, SizeMode.TARGET_COST_FEE_INCLUSIVE):
        tiny = derive_contracts(Decimal("0.001"), Decimal("0.40"), mode, fee_for=synthetic_fee)
        assert tiny.status == "BELOW_MIN_SIZE" and tiny.contracts is None
    # Room for 0.01 contract of principal but not for the fee on top of it.
    fee_eats_it = derive_contracts(Decimal("0.004"), Decimal("0.40"), SizeMode.TARGET_COST_FEE_INCLUSIVE,
                                   fee_for=synthetic_fee)
    assert fee_eats_it.status == "BELOW_MIN_SIZE"


def test_large_targets_size_quickly():
    r = derive_contracts(Decimal("10000000"), Decimal("0.01"), SizeMode.TARGET_COST_FEE_INCLUSIVE,
                         fee_for=synthetic_fee)
    assert r.status == "OK" and r.contracts * Decimal("0.01") + r.fee <= Decimal("10000000")


# ------------------------------------------------------------------ authority and purity


def test_participation_is_not_authorized_and_the_module_has_no_transport():
    assert venues.KALSHI.execution_authorized is False
    text = open(rr.__file__, encoding="utf-8").read()
    for token in ("urllib", "socket", "http.client", "requests", "websocket", "subprocess", "sqlite3"):
        assert f"import {token}" not in text and f"from {token}" not in text


def test_documented_windows():
    assert rr.CONFIRMATION_WINDOW[TimingClass.STANDARD] == timedelta(seconds=30)
    assert rr.CONFIRMATION_WINDOW[TimingClass.HVM] == timedelta(seconds=3)
    assert rr.EXECUTION_TIMER[TimingClass.STANDARD] == timedelta(seconds=15)
    assert rr.EXECUTION_TIMER[TimingClass.HVM] == timedelta(seconds=1)
    assert Kind.QUOTE_EXECUTED.value == "quote_executed"
