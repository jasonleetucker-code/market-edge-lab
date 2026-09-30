"""RFQ research lifecycle (R4, ADR 0042): synthetic fixtures only. No network, no credentials."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import rfq_research as rr, venues
from edge_lab.rfq_research import (
    HypotheticalQuote, Kind, Observer, QuoteState, SizeMode, TimingClass, Visibility, derive_contracts,
    hypothetical_check, obligations, observe, quote_is_current, reserve_simultaneous,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
ME, MAKER_B, MAKER_C, REQ_X = "comm_me", "comm_b", "comm_c", "comm_x"
BOUND = 1_000


def ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def rfq_created(rid, creator, *, market="KXNFLGAME-26OCT04BUFNE-BUF", contracts="100.00", target=None,
                legs=None, t=0, seq=1):
    msg = {"id": rid, "creator_id": creator, "market_ticker": market, "created_ts": ts(t)}
    if target is None:
        msg["contracts_fp"] = contracts
    else:
        msg["target_cost_dollars"] = target
    if legs:
        msg["mve_selected_legs"] = [{"event_ticker": e, "market_ticker": m, "side": s} for e, m, s in legs]
    return {"type": "rfq_created", "sid": 1, "seq": seq, "msg": msg}


def rfq_deleted(rid, creator, *, market="KXNFLGAME-26OCT04BUFNE-BUF", t=20, seq=2):
    return {"type": "rfq_deleted", "sid": 1, "seq": seq,
            "msg": {"id": rid, "creator_id": creator, "market_ticker": market, "deleted_ts": ts(t)}}


def quote_created(qid, rid, maker, rfq_creator, *, yes="0.40", no="0.55", size="100.00", t=1, seq=3,
                  market="KXNFLGAME-26OCT04BUFNE-BUF"):
    return {"type": "quote_created", "sid": 1, "seq": seq, "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "market_ticker": market, "yes_bid_dollars": yes, "no_bid_dollars": no,
        "yes_contracts_offered_fp": size, "no_contracts_offered_fp": size, "created_ts": ts(t)}}


def quote_accepted(qid, rid, maker, rfq_creator, *, side="yes", accepted="100.00", yes="0.40", no="0.55",
                   t=2, seq=4):
    return {"type": "quote_accepted", "sid": 1, "seq": seq, "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "market_ticker": "KXNFLGAME-26OCT04BUFNE-BUF", "yes_bid_dollars": yes, "no_bid_dollars": no,
        "accepted_side": side, "contracts_accepted_fp": accepted, "accepted_ts": ts(t)}}


def quote_status(kind, qid, rid, maker, rfq_creator, *, t=3):
    field = {"quote_confirmed": "confirmed_ts", "quote_cancelled": "cancelled_ts"}[kind]
    return {"type": kind, "msg": {"quote_id": qid, "rfq_id": rid, "quote_creator_id": maker,
                                  "rfq_creator_id": rfq_creator, field: ts(t)}}


def quote_executed(qid, rid, maker, rfq_creator, *, order="ord-1", t=20, seq=5):
    return {"type": "quote_executed", "sid": 1, "seq": seq, "msg": {
        "quote_id": qid, "rfq_id": rid, "quote_creator_id": maker, "rfq_creator_id": rfq_creator,
        "order_id": order, "client_order_id": "c-" + order, "market_ticker": "KXNFLGAME-26OCT04BUFNE-BUF",
        "executed_ts": ts(t)}}


def fill(fid, order, count, *, t=21):
    return {"type": "fill", "msg": {"fill_id": fid, "order_id": order, "count_fp": count, "created_time": ts(t)}}


def run(msgs, who=ME, **kw):
    return observe(msgs, Observer(who), max_messages=kw.pop("max_messages", BOUND), **kw)


# ------------------------------------------------------------------ privacy and observability


def test_outside_observer_cannot_report_private_quote_prices():
    msgs = [rfq_created("r1", REQ_X), rfq_created("r2", REQ_X, seq=2, market="KXNFLGAME-26OCT04BUFNE-NE")]
    rep = run(msgs)
    assert rep.status == "OK" and len(rep.rfqs) == 2
    assert rep.competitor_quote_prices is Visibility.UNAVAILABLE
    assert all(r.competitor_quote_prices is Visibility.UNAVAILABLE for r in rep.rfqs.values())
    assert rep.quotes == {}  # no price is invented, and none is 0
    assert rep.other_parties_fills is Visibility.UNAVAILABLE
    assert rep.queue_rank is Visibility.UNSUPPORTED


def test_a_quote_event_between_other_parties_is_never_used():
    """The docs say it is never delivered to a non-party. If a fixture contains one, it is counted
    as contradicting the docs and its prices are not surfaced."""
    msgs = [rfq_created("r1", REQ_X), quote_created("q1", "r1", MAKER_B, REQ_X, yes="0.10", no="0.20")]
    rep = run(msgs)
    assert rep.not_addressed_to_observer == 1 and "q1" not in rep.quotes
    assert rep.rfqs["r1"].competitor_quote_prices is Visibility.UNAVAILABLE


def test_our_own_quote_is_visible_but_competing_quotes_on_that_rfq_are_not():
    msgs = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
            quote_created("q2", "r1", MAKER_B, REQ_X, yes="0.45", seq=4)]
    rep = run(msgs)
    assert set(rep.quotes) == {"q1"} and rep.quotes["q1"].yes_bid == Decimal("0.40")
    assert rep.rfqs["r1"].competitor_quote_prices is Visibility.UNAVAILABLE


def test_requester_sees_every_quote_on_its_own_rfq():
    msgs = [rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME),
            quote_created("q2", "r1", MAKER_C, ME, yes="0.42", seq=4)]
    rep = run(msgs)
    assert set(rep.quotes) == {"q1", "q2"} and rep.rfqs["r1"].competitor_quote_prices is Visibility.VISIBLE


def test_unauthenticated_observer_sees_nothing():
    rep = observe([rfq_created("r1", REQ_X)], Observer(None), max_messages=BOUND)
    assert rep.status == "REFUSED_NOT_AUTHENTICATED" and rep.rfqs == {}
    assert rep.requested_contracts_upper_bound is None


# ------------------------------------------------------------------ volume layers


def test_request_volume_is_not_executed_volume():
    msgs = [rfq_created(f"r{i}", REQ_X, seq=i) for i in range(5)]
    rep = run(msgs)
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


# ------------------------------------------------------------------ hypothetical price and reuse


def test_a_state_change_invalidates_a_hypothetical_pending_price():
    rep = run([rfq_created("r1", REQ_X)])
    h = HypotheticalQuote("r1", Decimal("0.40"), Decimal("0.55"), "state-v7", ts(0))
    same = hypothetical_check(h, rep, current_state_version="state-v7", now=T0 + timedelta(seconds=1),
                              max_age=timedelta(seconds=5))
    assert same == ("PARTICIPATION_NOT_AUTHORIZED",)  # never clean: participation is not authorized
    moved = hypothetical_check(h, rep, current_state_version="state-v8", now=T0 + timedelta(seconds=1),
                               max_age=timedelta(seconds=5))
    assert moved[0] == "STATE_CHANGED" and moved[-1] == "PARTICIPATION_NOT_AUTHORIZED"
    unknown = hypothetical_check(h, rep, current_state_version=None, now=T0 + timedelta(seconds=1),
                                 max_age=timedelta(seconds=5))
    assert unknown[0] == "STATE_VERSION_UNKNOWN"
    closed = run([rfq_created("r1", REQ_X), rfq_deleted("r1", REQ_X)])
    assert "RFQ_NOT_KNOWN_OPEN" in hypothetical_check(h, closed, current_state_version="state-v7",
                                                      now=T0 + timedelta(seconds=1), max_age=timedelta(seconds=5))


def test_hypothetical_price_rules_follow_the_documented_quote_rules():
    rep = run([rfq_created("r1", REQ_X)])
    now = T0 + timedelta(seconds=1)
    over = HypotheticalQuote("r1", Decimal("0.60"), Decimal("0.45"), "v", ts(0))
    assert "YES_PLUS_NO_ABOVE_ONE" in hypothetical_check(over, rep, current_state_version="v", now=now,
                                                         max_age=timedelta(seconds=5))
    both_zero = HypotheticalQuote("r1", Decimal("0"), Decimal("0"), "v", ts(0))
    assert "PRICE_INVALID" in hypothetical_check(both_zero, rep, current_state_version="v", now=now,
                                                 max_age=timedelta(seconds=5))
    stale = hypothetical_check(HypotheticalQuote("r1", Decimal("0.4"), Decimal("0.5"), "v", ts(0)), rep,
                               current_state_version="v", now=T0 + timedelta(minutes=5), max_age=timedelta(seconds=5))
    assert "PRICE_STALE" in stale


def test_expired_or_replaced_quotes_cannot_be_reused():
    now = T0 + timedelta(seconds=5)
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X, t=1),
               quote_created("q2", "r1", ME, REQ_X, yes="0.41", t=2, seq=4)])
    assert rep.quotes["q1"].state is QuoteState.REPLACED
    assert quote_is_current("q1", rep, now=now) == (False, "REPLACED")
    assert quote_is_current("q2", rep, now=now) == (True, "OPEN")

    closed = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X), rfq_deleted("r1", REQ_X)])
    assert quote_is_current("q1", closed, now=now) == (False, "RFQ_CLOSED")

    # Accepted but never confirmed: past the window the quote is not current, but nothing is released.
    acc = run([rfq_created("r1", ME, market="KXNFLGAME-26OCT04BUFNE-BUF"), quote_created("q1", "r1", MAKER_B, ME),
               quote_accepted("q1", "r1", MAKER_B, ME, t=2)],
              timing_class={"KXNFLGAME-26OCT04BUFNE-BUF": TimingClass.STANDARD})
    assert quote_is_current("q1", acc, now=T0 + timedelta(seconds=10)) == (False, "ACCEPTED_AWAITING_CONFIRMATION")
    assert quote_is_current("q1", acc, now=T0 + timedelta(seconds=40)) == (False, "CONFIRMATION_WINDOW_ELAPSED")
    assert any(o.state is QuoteState.ACCEPTED and o.principal is not None for o in obligations(acc))


def test_combo_rfqs_use_the_hvm_confirmation_window():
    legs = [("KXNFLGAME-26OCT04BUFNE", "KXNFLGAME-26OCT04BUFNE-BUF", "yes"),
            ("KXNFLGAME-26OCT04KCLV", "KXNFLGAME-26OCT04KCLV-KC", "yes")]
    rep = run([rfq_created("r1", ME, market="KXMVECOMBO-X", legs=legs), quote_created("q1", "r1", MAKER_B, ME),
               quote_accepted("q1", "r1", MAKER_B, ME, t=2)])
    assert rep.rfqs["r1"].timing_class is TimingClass.HVM
    assert quote_is_current("q1", rep, now=T0 + timedelta(seconds=6))[1] == "CONFIRMATION_WINDOW_ELAPSED"


def test_equal_timestamps_make_replacement_ambiguous_and_keep_both_reserved():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X, t=1),
               quote_created("q2", "r1", ME, REQ_X, yes="0.41", t=1, seq=4)])
    assert {q.state for q in rep.quotes.values()} == {QuoteState.OPEN}
    assert quote_is_current("q1", rep, now=T0 + timedelta(seconds=2)) == (False, "REPLACEMENT_ORDER_AMBIGUOUS")
    assert len(obligations(rep)) == 2


# ------------------------------------------------------------------ idempotency and unknown state


def _lifecycle():
    return [rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME), quote_created("q2", "r1", MAKER_C, ME,
                                                                                         yes="0.42", seq=4),
            quote_accepted("q1", "r1", MAKER_B, ME, seq=5), quote_status("quote_confirmed", "q1", "r1", MAKER_B, ME),
            quote_executed("q1", "r1", MAKER_B, ME, seq=6), fill("f1", "ord-1", "100.00"),
            rfq_deleted("r1", ME, seq=7)]


def _summary(rep):
    return (rep.requested_contracts_upper_bound, rep.accepted_contracts_notified, rep.filled_contracts,
            {k: (v.state, v.filled_contracts) for k, v in rep.quotes.items()},
            {k: v.open for k, v in rep.rfqs.items()},
            tuple((o.source_id, o.state, o.principal) for o in obligations(rep)))


def test_duplicate_and_out_of_order_events_are_idempotent():
    msgs = _lifecycle()
    expected = _summary(run(msgs))
    assert expected[3]["q1"] == (QuoteState.ORDERS_PLACED, Decimal("100.00"))
    assert expected[3]["q2"][0] is QuoteState.RFQ_CLOSED
    rng = random.Random(145)
    for _ in range(25):
        shuffled = msgs + [dict(m, seq=m.get("seq", 0) + 100) for m in rng.sample(msgs, 3)]  # redelivered
        rng.shuffle(shuffled)
        rep = run(shuffled)
        assert _summary(rep) == expected and rep.duplicate_messages == 3


def test_contradictory_terminal_evidence_is_unknown_and_keeps_exposure():
    msgs = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X),
            quote_accepted("q1", "r1", ME, REQ_X), quote_status("quote_confirmed", "q1", "r1", ME, REQ_X),
            quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)]
    rep = run(msgs)
    assert rep.quotes["q1"].state is QuoteState.UNKNOWN
    (ob,) = obligations(rep, exchange_index={"KXNFLGAME-26OCT04BUFNE-BUF": 0})
    assert ob.principal == Decimal("55.0000")  # worst side: NO at 0.55 x 100, not released


def test_undocumented_and_malformed_messages_are_counted_not_used():
    msgs = [rfq_created("r1", REQ_X), {"type": "quote_repriced", "msg": {"quote_id": "q9"}},
            {"type": "quote_created", "msg": {"rfq_id": "r1"}}, "not-a-mapping"]
    rep = run(msgs)
    assert rep.undocumented_messages == ("quote_repriced",) and rep.malformed_messages == 2
    assert rep.quotes == {}


def test_missing_fields_stay_unknown_not_zero():
    msgs = [rfq_created("r1", REQ_X),
            {"type": "quote_created", "msg": {"quote_id": "q1", "rfq_id": "r1", "quote_creator_id": ME,
                                              "rfq_creator_id": REQ_X, "yes_bid_dollars": "0.40",
                                              "no_bid_dollars": "bad", "created_ts": ts(1)}}]
    rep = run(msgs)
    q = rep.quotes["q1"]
    assert q.no_bid is None and q.yes_contracts is None
    (ob,) = obligations(rep, exchange_index={"KXNFLGAME-26OCT04BUFNE-BUF": 0})
    assert ob.principal is None  # the NO side could be accepted at an unknown price: unknown, not 40
    ok = dict(msgs[1], msg=dict(msgs[1]["msg"], no_bid_dollars="0"))  # NO side explicitly declined
    (ob1,) = obligations(run([msgs[0], ok]), exchange_index={"KXNFLGAME-26OCT04BUFNE-BUF": 0})
    assert ob1.principal == Decimal("40.0000")  # sized from the RFQ's 100 contracts
    rep2 = run([rfq_created("r1", REQ_X, target="30.00"), ok])
    (ob2,) = obligations(rep2, exchange_index={"KXNFLGAME-26OCT04BUFNE-BUF": 0})
    assert ob2.principal is None  # a target-cost RFQ with no offered size: unknown


# ------------------------------------------------------------------ collateral


LEG_SHARED = ("KXNFLGAME-26OCT04BUFNE", "KXNFLGAME-26OCT04BUFNE-BUF", "yes")


def test_requests_sharing_legs_cannot_reuse_the_same_collateral():
    a = rfq_created("rA", REQ_X, market="KXMVE-A", legs=[LEG_SHARED, ("E2", "E2-M", "yes")])
    b = rfq_created("rB", REQ_X, market="KXMVE-B", legs=[LEG_SHARED, ("E3", "E3-M", "no")], seq=2)
    msgs = [a, b, quote_created("qA", "rA", ME, REQ_X, yes="0.60", no="0", market="KXMVE-A"),
            quote_created("qB", "rB", ME, REQ_X, yes="0.60", no="0", seq=4, market="KXMVE-B")]
    rep = run(msgs)
    obs = obligations(rep, exchange_index={"KXMVE-A": 1, "KXMVE-B": 1})
    assert [o.principal for o in obs] == [Decimal("60.0000"), Decimal("60.0000")]
    res = reserve_simultaneous(obs, {1: Decimal("100")}, fee_allowance=lambda o: Decimal("0"))
    assert res.status == "INSUFFICIENT_COLLATERAL" and res.required_by_index[1] == Decimal("120.0000")
    assert res.common_legs[(LEG_SHARED[1], "yes")] == ("qA", "qB")
    # Cash on another exchange index does not help: collateral is preallocated per shard.
    assert reserve_simultaneous(obs, {0: Decimal("1000"), 1: Decimal("100")},
                                fee_allowance=lambda o: Decimal("0")).status == "INSUFFICIENT_COLLATERAL"
    assert reserve_simultaneous(obs, {1: Decimal("120")}, fee_allowance=lambda o: Decimal("0")).status == "OK"
    assert reserve_simultaneous(obs, {1: Decimal("120")}).status == "FEE_UNSUPPORTED"


def test_unknown_exchange_index_or_principal_fails_closed():
    rep = run([rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)])
    res = reserve_simultaneous(obligations(rep), {0: Decimal("1000")}, fee_allowance=lambda o: Decimal("0"))
    assert res.status == "EXPOSURE_UNKNOWN" and res.unknown == ("q1",)


def test_released_only_in_documented_terminal_states():
    base = [rfq_created("r1", REQ_X), quote_created("q1", "r1", ME, REQ_X)]
    assert len(obligations(run(base))) == 1
    assert obligations(run(base + [quote_status("quote_cancelled", "q1", "r1", ME, REQ_X)])) == ()
    assert obligations(run(base + [rfq_deleted("r1", REQ_X)])) == ()
    # Accepted, then the RFQ closed with no confirmation seen: still reserved (unknown outcome).
    acc = base + [quote_accepted("q1", "r1", ME, REQ_X), rfq_deleted("r1", REQ_X)]
    (ob,) = obligations(run(acc))
    assert ob.state is QuoteState.ACCEPTED


def test_requester_obligation_reserves_the_worse_reading_of_the_accepted_side():
    rep = run([rfq_created("r1", ME), quote_created("q1", "r1", MAKER_B, ME, yes="0.30", no="0.65"),
               quote_accepted("q1", "r1", MAKER_B, ME, side="yes", yes="0.30", no="0.65")])
    (ob,) = obligations(rep, exchange_index={"KXNFLGAME-26OCT04BUFNE-BUF": 0})
    assert ob.role == "REQUESTER" and ob.principal == Decimal("70.00")  # max(0.30, 0.70) x 100


# ------------------------------------------------------------------ input bound


def test_input_above_the_bound_is_refused_not_truncated():
    msgs = [rfq_created(f"r{i}", REQ_X, seq=i) for i in range(11)]
    rep = run(msgs, max_messages=10)
    assert rep.status == "REFUSED_INPUT_BOUND" and rep.received_messages == 11
    assert rep.rfqs == {} and rep.requested_contracts_upper_bound is None
    assert run(msgs, max_messages=11).status == "OK"


def test_the_bound_counts_every_received_message_before_local_filtering():
    msgs = [rfq_created(f"r{i}", REQ_X, seq=i, market=("KXNHLGAME-X" if i % 2 else "KXFED-Y")) for i in range(6)]
    nhl_only = lambda e: (e.market_ticker or "").startswith("KXNHLGAME")  # noqa: E731
    rep = run(msgs, keep=nhl_only, max_messages=6)
    assert rep.received_messages == 6 and rep.kept_messages == 3 and len(rep.rfqs) == 3
    assert run(msgs, keep=nhl_only, max_messages=5).status == "REFUSED_INPUT_BOUND"


def test_bound_must_be_a_whole_number():
    with pytest.raises(rr.RfqResearchError):
        observe([], Observer(ME), max_messages=True)


# ------------------------------------------------------------------ sizing modes


def synthetic_fee(contracts: Decimal, price: Decimal) -> Decimal:
    """SYNTHETIC test fee (7% x C x p x (1-p), rounded up to the cent). Not a verified Kalshi fee."""
    from decimal import ROUND_CEILING
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
