"""Stream and account recovery (#160 package J): the pure model. FIXTURE and SYNTHETIC only; no network.

Proofs use a real `account.reconcile_account` read of the FakeVenue-backed fixture adapter
(`test_orchestrator_harness`)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import account as acct
from edge_lab.execution import model as m
from edge_lab.execution import recovery as rc

B70, B72, B74 = h.MARKETS
CFG = rc.RecoveryConfig(max_items_per_window=50, rate_window=timedelta(seconds=1), max_opens_per_window=4,
                        reconnect_window=timedelta(minutes=5), max_clock_skew=timedelta(seconds=5),
                        book_jump=Decimal("0.02"), dedupe_window=64, max_tracked=20)
ORDERS, FILLS = rc.Channel.ORDERS, rc.Channel.FILLS


def at(s: float) -> str:
    return m.utc_text(h.T0 + timedelta(seconds=s))


def fill(sid, seq, s, *, fill_id="f1", order_id="o1", market=B70, count="1", price="0.44", corrects=None, **clk):
    return rc.StreamMessage(sid, seq, FILLS, rc.FillEvent(fill_id, order_id, market, Decimal(count), Decimal(price)),
                            rc.Clocks(at(s), **clk), corrects)


def update(sid, seq, s, *, order_id="o1", market=B70, status="resting", filled="0", remaining="2", **clk):
    return rc.StreamMessage(sid, seq, ORDERS, rc.OrderUpdate(order_id, market, status, Decimal(filled),
                                                             Decimal(remaining)), rc.Clocks(at(s), **clk))


def run(state, *items):
    steps = []
    for item in items:
        step = rc.apply(state, item)
        steps.append(step)
        state = step.state
    return state, steps


def opened(cfg=CFG, s=0, orders_sid=1, fills_sid=2):
    """Both subscriptions opened at T0+s. The baseline used by most tests opens them at T0-10s, so the fixture's
    first read (started at T0, venue data as of T0-1s) post-dates them."""
    state, _ = run(rc.initial(cfg), rc.SubscriptionOpened(orders_sid, ORDERS, at(s)),
                   rc.SubscriptionOpened(fills_sid, FILLS, at(s)))
    return state


def reasons(state, market=None):
    return sorted(q.reason.value for q in state.quarantines if q.market_ticker == market)


@pytest.fixture
def venue():
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    return adapter, clock


def read(adapter, clock, scope=h.SCOPE):
    adapter.sync()
    plan = acct.AccountReadPlan(scope=scope, subaccounts=(0,), endpoints=frozenset(acct.AccountEndpoint),
                                page_limit=100, max_pages=20, max_requests=80, deadline=clock() + timedelta(seconds=30),
                                max_resamples=3, max_data_lag=timedelta(minutes=1))
    recon = acct.reconcile_account(plan, adapter, clock=clock, local_orders=(),
                                   external_cash_policy=acct.ExternalCashPolicy.FULL_NOTIONAL)
    assert recon.status is acct.ReconciliationStatus.COMPLETE, recon.problems
    return recon


def buy(adapter, client_id, ticker=B70, count="2", price="0.45"):
    reply = adapter.venue.new_order(ticker=ticker, side=m.Side.YES, action=m.Action.BUY, count=count, price=price,
                                    time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL, client_order_id=client_id)
    adapter.sync()
    order = reply.body["order"]
    return order["order_id"], [f["fill_id"] for f in adapter.venue.list_fills(order["order_id"])]


def proven(state, adapter, clock):
    proof = rc.prove(state, read(adapter, clock), scope=h.SCOPE)
    assert proof.proven, proof.reason
    return proof


# ---------------------------------------------------------------- baseline, proof and point in time


def test_nothing_is_usable_before_a_subscription_and_a_rest_baseline(venue):
    adapter, clock = venue
    state = rc.initial(CFG)
    marks = rc.marks(state)
    assert not state.connected and rc.decision_problems(state, B70, marks)[0].startswith("STREAM_DOWN")
    state = opened(s=0)
    assert state.connected and reasons(state) == ["BASELINE_REQUIRED"] and state.reconciliation_required
    assert any(p.startswith("STREAM_QUARANTINE: BASELINE_REQUIRED") for p in rc.decision_problems(state, B70, marks))
    early = proven(state, adapter, clock)  # started at T0, when they opened, but the venue data is as of T0-1s
    assert early.proof_time_utc == at(-1) and early.cleared == () and reasons(early.state) == ["BASELINE_REQUIRED"]
    clock.advance(2)
    proof = proven(state, adapter, clock)  # venue data as of T0+1s: after the subscriptions opened
    assert [q.reason for q in proof.cleared] == [rc.Reason.BASELINE_REQUIRED] and not proof.state.quarantines
    assert rc.decision_problems(proof.state, B70, rc.marks(proof.state)) == ()


def test_a_read_that_started_before_the_anomaly_proves_nothing_about_it(venue):
    adapter, clock = venue
    state = opened(s=30)  # the subscriptions open 30 s after the read below starts
    proof = proven(state, adapter, clock)
    assert proof.cleared == () and reasons(proof.state) == ["BASELINE_REQUIRED"]
    clock.advance(30)  # a read started at T0+30s, but its venue data is as of T0+29s: still before the anomaly
    assert reasons(proven(proof.state, adapter, clock).state) == ["BASELINE_REQUIRED"]
    clock.advance(1)
    assert not proven(proof.state, adapter, clock).state.quarantines


def shifted(recon, *, started, as_of, finished=None):
    """The same COMPLETE read with its manifest's clocks set (seconds after T0; as_of None: no venue data time)."""
    manifest = dataclasses.replace(
        recon.manifest, started_at=h.T0 + timedelta(seconds=started),
        finished_at=h.T0 + timedelta(seconds=started if finished is None else finished),
        as_of_start=None if as_of is None else h.T0 + timedelta(seconds=as_of))
    return dataclasses.replace(recon, manifest=manifest)


def test_a_lagging_venue_data_time_does_not_prove_an_anomaly_after_it(venue):
    """The review's reproduction: a gap at T0+60s, a COMPLETE read started at T0+61s whose venue data is as of
    T0+11s (within max_data_lag). The data predates the gap, so the gap stays quarantined."""
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, update(1, 1, 59), update(1, 3, 60))
    recon = read(adapter, clock)
    lagging = rc.prove(state, shifted(recon, started=61, as_of=11), scope=h.SCOPE)
    assert lagging.proven and lagging.proof_time_utc == at(11)
    assert lagging.cleared == () and reasons(lagging.state) == ["SEQUENCE_GAP"]
    current = rc.prove(state, shifted(recon, started=61, as_of=61), scope=h.SCOPE)
    assert [q.reason for q in current.cleared] == [rc.Reason.SEQUENCE_GAP] and current.proof_time_utc == at(61)


def test_stream_fills_between_the_venue_data_time_and_the_read_start_are_not_judged(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, fill(2, 1, 30, fill_id="mid", order_id="o-mid"))  # after as_of, before the start
    proof = rc.prove(state, shifted(read(adapter, clock), started=61, as_of=11), scope=h.SCOPE)
    assert proof.findings == () and [o.order_id for o in proof.state.orders] == ["o-mid"]  # no false disagreement


def test_an_anomaly_inside_the_read_window_is_not_proven_by_that_read(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, update(1, 1, 99), update(1, 3, 101))  # a gap after the start, before the finish
    recon = shifted(read(adapter, clock), started=100, as_of=102, finished=110)
    proof = rc.prove(state, recon, scope=h.SCOPE)
    assert proof.proof_time_utc == at(100) and reasons(proof.state) == ["SEQUENCE_GAP"]
    state, _ = run(proof.state, update(1, 4, 105, order_id="o-in"))
    assert reasons(rc.prove(state, recon, scope=h.SCOPE).state) == ["SEQUENCE_GAP"]


def test_a_read_without_a_venue_data_time_or_without_the_streams_subaccounts_proves_nothing(venue):
    adapter, clock = venue
    state = opened(s=-10)
    recon = read(adapter, clock)
    refused = rc.prove(state, shifted(recon, started=0, as_of=None), scope=h.SCOPE)
    assert not refused.proven and "no venue user-data time" in refused.reason and refused.state is state
    wide = opened(dataclasses.replace(CFG, subaccounts=frozenset({0, 1})), s=-10)
    partial = rc.prove(wide, recon, scope=h.SCOPE)  # the fixture read covers subaccount 0 only
    assert not partial.proven and "covers subaccounts [0]" in partial.reason


def test_only_a_complete_reconciliation_of_the_same_scope_proves(venue):
    adapter, clock = venue
    state = opened()
    recon = read(adapter, clock)
    assert rc.prove(state, "COMPLETE", scope=h.SCOPE).reason == "not an account reconciliation"
    other = m.AccountScope(m.Environment.FIXTURE, "another-acct")
    assert rc.prove(state, recon, scope=other).reason == "the reconciliation is of another account scope"
    partial = dataclasses.replace(recon, status=acct.ReconciliationStatus.PARTIAL)
    refused = rc.prove(state, partial, scope=h.SCOPE)
    assert not refused.proven and refused.state is state and "only COMPLETE proves" in refused.reason
    unknown = dataclasses.replace(recon, subaccounts=(dataclasses.replace(recon.subaccounts[0], fills=None),))
    assert not rc.prove(state, unknown, scope=h.SCOPE).proven


# ---------------------------------------------------------------- sequence: dropped delta, duplicates, new SID


def test_a_dropped_delta_quarantines_the_whole_account_until_a_later_read(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, steps = run(state, update(1, 1, 1), update(1, 2, 2, status="resting", filled="1", remaining="1"),
                       update(1, 4, 3, status="executed", filled="2", remaining="0"))  # seq 3 never arrived
    assert steps[-1].raised == (rc.Reason.SEQUENCE_GAP,) and reasons(state) == ["SEQUENCE_GAP"]
    for market in (B70, B72):  # any market: the lost message could have been about either
        assert any("SEQUENCE_GAP" in p for p in rc.decision_problems(state, market, rc.marks(state)))
    state, _ = run(state, update(1, 5, 4, order_id="o2", market=B72))  # contiguous again: still not proven
    assert reasons(state) == ["SEQUENCE_GAP"]
    assert reasons(proven(state, adapter, clock).state) == ["SEQUENCE_GAP"]  # the read started before the gap
    clock.advance(5)
    assert reasons(proven(state, adapter, clock).state) == []


def test_duplicates_conflicting_duplicates_and_late_arrivals(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, steps = run(state, update(1, 1, 1), update(1, 1, 2))
    assert steps[1].applied is rc.Applied.DUPLICATE and not state.quarantines
    first = rc.epoch(state, B70)
    assert first > 0 and dict(state.counts)["DUPLICATE"] == 1
    assert rc.epoch(rc.apply(state, update(1, 1, 2.5)).state, B70) == first  # the duplicate is not a second change
    state, steps = run(state, update(1, 1, 3, status="canceled", remaining="0"))
    assert steps[0].applied is rc.Applied.QUARANTINED and reasons(state) == ["CONFLICTING_DUPLICATE"]
    state, steps = run(state, update(1, 2, 4), update(1, 4, 5), update(1, 3, 6))  # 3 arrives after 4
    assert [s.raised for s in steps[1:]] == [(rc.Reason.SEQUENCE_GAP,), (rc.Reason.OUT_OF_ORDER,)]


def test_a_new_sid_starts_a_new_sequence_scope_and_the_old_sid_is_stale(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, update(1, 1, 1), update(1, 2, 2, filled="1", remaining="1"))
    state, steps = run(state, rc.SubscriptionOpened(7, ORDERS, at(3)), update(7, 1, 4, filled="1", remaining="1"))
    assert steps[0].raised == (rc.Reason.RECONNECTED,) and steps[1].raised == ()  # seq 1 on sid 7: no gap
    assert {s.sid: s.last_seq for s in state.subscriptions} == {2: None, 7: 1} and 1 in state.retired
    before = rc.epoch(state, B72)
    state, steps = run(state, update(1, 3, 5, order_id="o9", market=B72))  # a late message on the retired sid
    assert steps[0].applied is rc.Applied.STALE_SUBSCRIPTION
    assert "o9" not in {o.order_id for o in state.orders} and rc.epoch(state, B72) > before
    state, steps = run(state, rc.SubscriptionOpened(1, ORDERS, at(6)))
    assert steps[0].raised == (rc.Reason.SID_REUSED,) and {s.sid for s in state.subscriptions} == {2, 7}
    state, steps = run(state, update(99, 1, 7))
    assert steps[0].raised == (rc.Reason.UNKNOWN_SUBSCRIPTION,)
    state, steps = run(state, fill(7, 2, 8))  # a FILLS message on the ORDERS subscription
    assert steps[0].raised == (rc.Reason.CHANNEL_MISMATCH,)
    clock.advance(10)
    assert reasons(proven(state, adapter, clock).state) == []


def test_a_first_seq_other_than_the_configured_start_is_a_gap_and_none_accepts_any():
    state, steps = run(opened(), update(1, 5, 1))
    assert steps[0].raised == (rc.Reason.SEQUENCE_GAP,)
    state, steps = run(opened(dataclasses.replace(CFG, first_seq=None)), update(1, 5, 1), update(1, 6, 2))
    assert [s.raised for s in steps] == [(), ()]


# ---------------------------------------------------------------- reconnects


def test_a_reconnect_is_not_an_order_cancellation(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, update(1, 1, 1, status="resting", filled="0", remaining="2"))
    state, steps = run(state, rc.ConnectionLost(at(2), "socket closed"))
    assert steps[0].applied is rc.Applied.DISCONNECTED and not state.connected and state.subscriptions == ()
    (o,) = state.orders
    assert (o.status, o.filled, o.remaining) == ("resting", Decimal("0"), Decimal("2"))  # nothing was cancelled
    assert rc.decision_problems(state, B70, rc.marks(state))[0].startswith("STREAM_DOWN")
    state = run(state, rc.SubscriptionOpened(3, ORDERS, at(3)), rc.SubscriptionOpened(4, FILLS, at(3)))[0]
    assert state.connected and reasons(state) == ["BASELINE_REQUIRED", "CONNECTION_LOST"]
    assert state.reconciliation_required  # missing private messages: only REST can say what happened meanwhile


def test_a_reconnect_storm_stays_quarantined_until_the_storm_has_passed(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    sid = 10
    for i in range(3):  # three more reconnects of both channels within a minute: 6 + 2 opens
        state, _ = run(state, rc.ConnectionLost(at(10 * i + 1), "flap"),
                       rc.SubscriptionOpened(sid, ORDERS, at(10 * i + 2)),
                       rc.SubscriptionOpened(sid + 1, FILLS, at(10 * i + 2)))
        sid += 2
    assert "RECONNECT_STORM" in reasons(state)
    clock.advance(60)
    state = proven(state, adapter, clock).state
    assert reasons(state) == ["RECONNECT_STORM"]  # the connection losses are proven; the storm is not over
    clock.advance(300)
    assert reasons(proven(state, adapter, clock).state) == []


# ---------------------------------------------------------------- invalidation and concurrent markets


def test_concurrent_markets_on_one_subscription_invalidate_only_the_market_that_changed(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    marks = rc.marks(state)
    state, _ = run(state, fill(2, 1, 1, fill_id="fa", order_id="oa", market=B70))
    (problem,) = rc.decision_problems(state, B70, marks)
    assert problem.startswith(f"STREAM_INVALIDATED: {B70} changed") and "fill fa" in problem
    assert rc.decision_problems(state, B72, marks) == ()
    state, _ = run(state, fill(2, 2, 2, fill_id="fb", order_id="ob", market=B72), fill(2, 4, 3, fill_id="fc",
                                                                                         order_id="oc", market=B74))
    later = rc.marks(state)
    assert all(any("SEQUENCE_GAP" in p for p in rc.decision_problems(state, t, later)) for t in h.MARKETS)


def test_an_order_update_invalidates_only_when_it_changes_something():
    state = opened()
    state, _ = run(state, update(1, 1, 1))
    marks = rc.marks(state)
    state, _ = run(state, update(1, 2, 2))  # the same state again under a new seq
    assert rc.epoch(state, B70) == marks.epochs[B70]
    state, _ = run(state, update(1, 3, 3, filled="1", remaining="1"))
    assert rc.epoch(state, B70) > marks.epochs[B70]


def test_a_book_jump_beyond_the_threshold_invalidates_its_market():
    def book(s, bid, ask, market=B70):
        return rc.BookObservation(market, None if bid is None else Decimal(bid), None if ask is None else Decimal(ask),
                                  rc.Clocks(at(s)))

    state, _ = run(opened(), book(1, "0.42", "0.44"))
    marks = rc.marks(state)
    state, _ = run(state, book(2, "0.43", "0.45"))  # within 0.02: not a relevant change
    assert rc.decision_problems(state, B70, marks) == tuple(
        p for p in rc.decision_problems(state, B70, marks) if p.startswith("STREAM_QUARANTINE"))
    state, steps = run(state, book(3, "0.43", "0.48"))
    jumped = rc.epoch(state, B70)
    assert "ask 0.45 -> 0.48" in steps[0].detail and jumped > marks.epochs.get(B70, 0)
    state, steps = run(state, book(4, None, "0.48"))  # a side emptied
    assert rc.epoch(state, B70) > jumped
    assert rc.epoch(state, B72) == 0


# ---------------------------------------------------------------- corrections and conflicts


def test_a_corrected_fill_quarantines_its_market_and_is_kept_as_a_new_observation(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, fill(2, 1, 1, fill_id="f1", order_id="oa"), fill(2, 2, 2, fill_id="f2", order_id="ob",
                                                                         market=B72))
    state, steps = run(state, fill(2, 3, 3, fill_id="f1", order_id="oa", count="0.5", corrects="f1"))
    assert steps[0].applied is rc.Applied.CORRECTION and reasons(state, B70) == ["CORRECTED_EVENT"]
    assert reasons(state) == [] and reasons(state, B72) == []
    assert [k for k, _ in state.events].count("f1") == 2  # both observations kept
    assert {o.order_id for o in state.orders} == {"ob"}  # B70's stream expectations dropped: REST decides
    marks = rc.marks(state)
    assert rc.decision_problems(state, B72, marks) == ()
    assert any("CORRECTED_EVENT" in p for p in rc.decision_problems(state, B70, marks))


def test_a_fill_redelivered_identically_is_a_duplicate_event_and_with_new_content_a_conflict():
    state, _ = run(opened(), fill(2, 1, 1))
    epoch = rc.epoch(state, B70)
    state, steps = run(state, fill(2, 2, 2))  # the same fill under the next seq
    assert steps[0].applied is rc.Applied.DUPLICATE_EVENT and rc.epoch(state, B70) == epoch
    assert state.orders[0].fill_ids == ("f1",)
    state, steps = run(state, fill(2, 3, 3, count="2"))  # the same fill id, another count, no correction declared
    assert steps[0].raised == (rc.Reason.EVENT_CONFLICT,) and reasons(state, B70) == ["EVENT_CONFLICT"]


def test_an_order_count_that_goes_backwards_keeps_the_higher_count_and_quarantines_the_market():
    state, _ = run(opened(), update(1, 1, 1, filled="2", remaining="0", status="executed"))
    state, steps = run(state, update(1, 2, 2, filled="1", remaining="1"))
    assert steps[0].raised == (rc.Reason.REGRESSION,) and state.orders[0].filled == Decimal("2")
    assert reasons(state, B70) == ["REGRESSION"]


# ---------------------------------------------------------------- clocks and receipt order


def test_receipt_order_anomalies_quarantine_and_nothing_is_redated():
    state, steps = run(opened(), update(1, 1, 10), update(1, 2, 5, order_id="o2"))  # our receipt clock went back
    assert steps[1].raised == (rc.Reason.RECEIPT_ORDER,) and state.last_receipt_utc == at(10)
    (q,) = [q for q in state.quarantines if q.reason is rc.Reason.RECEIPT_ORDER]
    assert q.not_before_utc == at(10)  # a read must start after the latest receipt we saw

    state, steps = run(opened(), update(1, 1, 1, source_at_utc=at(0.5), sent_at_utc=at(0.6)),
                       update(1, 2, 2, order_id="o2", source_at_utc=at(0.2)))  # the source stamp went back
    assert steps[1].raised == (rc.Reason.SOURCE_ORDER,)
    assert {s.sid: s.last_source_utc for s in state.subscriptions}[1] == at(0.5)  # not corrected backwards

    state, steps = run(opened(), update(1, 1, 1, sent_at_utc=at(30)))  # sent 29 s after we received it
    assert steps[0].raised == (rc.Reason.CLOCK_SKEW,)
    state, steps = run(opened(), update(1, 1, 1, event_at_utc=at(60)))  # an event after we heard of it
    assert steps[0].raised == (rc.Reason.CLOCK_SKEW,)
    state, steps = run(opened(), update(1, 1, 1, event_at_utc=at(-3600)))  # an old event: allowed, not re-dated
    assert steps[0].raised == () and steps[0].state.last_receipt_utc == at(1)

    message = update(1, 1, 1)
    assert (message.clocks.event_at_utc, message.clocks.source_at_utc, message.clocks.sent_at_utc) == (None,) * 3


# ---------------------------------------------------------------- rate bounds count incoming traffic


def test_the_rate_bound_counts_every_incoming_item_not_retained_rows(venue):
    adapter, clock = venue
    state, _ = run(proven(opened(s=-10), adapter, clock).state, update(1, 1, 1))
    retained = (len(state.recent), len(state.orders))
    copies = [update(1, 1, 1 + i / 100) for i in range(CFG.max_items_per_window)]  # duplicates within one second
    state, steps = run(state, *copies)
    assert (len(state.recent), len(state.orders)) == retained  # duplicates are not retained
    assert steps[-1].raised == (rc.Reason.RATE_EXCEEDED,) and reasons(state) == ["RATE_EXCEEDED"]
    assert state.incoming == 2 + 1 + CFG.max_items_per_window and len(state.receipts) <= CFG.max_items_per_window
    assert dict(state.counts)["DUPLICATE"] == CFG.max_items_per_window
    (q,) = state.quarantines
    assert q.not_before_utc == m.utc_text(m.parse_utc_text(q.since_utc) + CFG.rate_window)


def test_marks_are_pruned_at_a_proof_and_an_older_decision_still_sees_its_market_changed(venue):
    adapter, clock = venue
    book = rc.BookObservation  # unsequenced, untracked by proofs: only its epoch moves
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, book(B70, Decimal("0.40"), Decimal("0.45"), rc.Clocks(at(1))),
                   book(B70, Decimal("0.40"), Decimal("0.50"), rc.Clocks(at(2))))
    old_marks = rc.marks(state)  # taken before the next proof
    assert old_marks.epochs[B70] > 0
    clock.advance(5)
    state = proven(state, adapter, clock).state
    assert state.marks == () and not state.quarantines  # pruned: bounded between proofs
    assert rc.decision_problems(state, B70, old_marks)[0].startswith("STREAM_INVALIDATED")  # never "unchanged"
    state, _ = run(state, book(B70, Decimal("0.40"), Decimal("0.60"), rc.Clocks(at(6))))
    assert rc.epoch(state, B70) > old_marks.epochs[B70]  # a counter value is never reused
    assert rc.decision_problems(state, B70, rc.marks(state)) == ()


def test_a_market_unmarked_when_marks_were_taken_is_not_presumed_unchanged_after_a_pruning_proof(venue):
    """The review's M1 reproduction: marks taken while B70 has no mark; B70 then changes; a proof prunes the marks.
    B70 must still read as changed against the old marks (missing is not zero)."""
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    old_marks = rc.marks(state)
    assert B70 not in old_marks.epochs
    state, _ = run(state, rc.BookObservation(B70, Decimal("0.40"), Decimal("0.45"), rc.Clocks(at(1))))
    assert rc.decision_problems(state, B70, old_marks)[0].startswith("STREAM_INVALIDATED")
    clock.advance(5)
    state = proven(state, adapter, clock).state
    assert state.marks == ()
    assert rc.decision_problems(state, B70, old_marks)[0].startswith("STREAM_INVALIDATED: account-wide")
    assert rc.decision_problems(state, B70, rc.marks(state)) == ()
    # a proof with no marks to prune changes nothing for marks taken after the previous one
    fresh = rc.marks(state)
    clock.advance(5)
    assert rc.decision_problems(proven(state, adapter, clock).state, B70, fresh) == ()


def test_empty_and_unknown_book_sides_are_different_and_either_change_invalidates():
    def book(s, bid=None, ask=None, *, bid_empty=False, ask_empty=False):
        return rc.BookObservation(B70, None if bid is None else Decimal(bid), None if ask is None else Decimal(ask),
                                  rc.Clocks(at(s)), bid_empty=bid_empty, ask_empty=ask_empty)

    state, _ = run(opened(), book(1, "0.40", "0.45"))
    assert state.books[0].bid == ("PRICE", Decimal("0.40"))
    epoch = rc.epoch(state, B70)
    state, steps = run(state, book(2, ask="0.45", bid_empty=True))
    assert "bid PRICE -> EMPTY" in steps[0].detail and rc.epoch(state, B70) > epoch
    epoch = rc.epoch(state, B70)
    state, steps = run(state, book(3, ask="0.45"))  # the bid is now unknown, which is not empty
    assert "bid EMPTY -> UNKNOWN" in steps[0].detail and rc.epoch(state, B70) > epoch
    with pytest.raises(ValueError):
        book(4, bid="0.40", bid_empty=True)


def test_books_are_bounded_by_forgetting_the_oldest_baseline():
    state = opened()
    books = [rc.BookObservation(f"M{i}", Decimal("0.40"), Decimal("0.45"), rc.Clocks(at(1 + i / 1000)))
             for i in range(CFG.max_tracked + 3)]
    state, steps = run(state, *books)
    assert len(state.books) == CFG.max_tracked and "M0" not in {b.market_ticker for b in state.books}
    assert all(step.detail == "baseline" for step in steps)  # a first sighting counts as a change
    before = rc.epoch(state, "M0")
    state, steps = run(state, rc.BookObservation("M0", Decimal("0.40"), Decimal("0.45"), rc.Clocks(at(2))))
    assert steps[0].detail == "baseline" and rc.epoch(state, "M0") > before  # re-baselined after eviction: a change


def test_fill_ids_per_order_are_bounded_and_overflow_quarantines():
    fills = [fill(2, i + 1, 1 + i / 1000, fill_id=f"f{i}", order_id="busy") for i in range(CFG.max_tracked + 2)]
    state, _ = run(opened(), *fills)
    (busy,) = state.orders
    assert len(busy.fill_ids) == CFG.max_tracked and "TOO_MANY_TRACKED" in reasons(state)


def test_retained_state_is_bounded_and_overflow_quarantines():
    state = opened()
    items = [fill(2, i + 1, 1 + i / 1000, fill_id=f"f{i}", order_id=f"o{i}", market=f"M{i}")
             for i in range(CFG.max_tracked + 5)]
    state, _ = run(state, *items)
    assert len(state.orders) <= CFG.max_tracked and len(state.marks) <= CFG.max_tracked
    assert len(state.recent) <= CFG.dedupe_window and len(state.events) <= CFG.dedupe_window
    assert "TOO_MANY_TRACKED" in reasons(state)
    corrections = [fill(2, CFG.max_tracked + 6 + i, 2 + i / 1000, fill_id=f"c{i}", order_id=f"o{i}", market=f"N{i}",
                        corrects=f"f{i}") for i in range(CFG.max_tracked + 5)]
    state, _ = run(state, *corrections)
    assert len({q.market_ticker for q in state.quarantines if q.market_ticker}) <= CFG.max_tracked
    assert "CORRECTED_EVENT" in reasons(state)  # past the bound, a market quarantine covers the whole account


# ---------------------------------------------------------------- REST/stream disagreement


def test_rest_and_stream_disagreement_keeps_the_market_quarantined(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    order_id, fill_ids = buy(adapter, "c1")
    clock.advance(1)
    state, _ = run(state, update(1, 1, 1, order_id=order_id, status="executed", filled="2", remaining="0"),
                   fill(2, 1, 1, fill_id=fill_ids[0], order_id=order_id, count="2"),
                   fill(2, 2, 1, fill_id="ghost-fill", order_id="ghost", market=B72))  # REST never heard of it
    clock.advance(1)
    proof = proven(state, adapter, clock)
    (finding,) = proof.findings
    assert (finding.kind, finding.market_ticker, finding.order_id) == ("DISAGREEMENT", B72, "ghost")
    assert reasons(proof.state, B72) == ["DISAGREEMENT"] and reasons(proof.state, B70) == []
    assert [o.order_id for o in proof.state.orders] == ["ghost"]  # the agreeing order was rebased away
    assert any("DISAGREEMENT" in p for p in rc.decision_problems(proof.state, B72, rc.marks(proof.state)))
    clock.advance(5)
    again = proven(proof.state, adapter, clock)  # still disagrees: still quarantined, reported again
    assert [f.kind for f in again.findings] == ["DISAGREEMENT"] and reasons(again.state, B72) == ["DISAGREEMENT"]


def test_stream_ahead_of_rest_is_a_disagreement_and_rest_ahead_is_reported_and_rest_wins(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    order_id, _ = buy(adapter, "c1")
    clock.advance(1)
    state, _ = run(state, update(1, 1, 1, order_id=order_id, status="executed", filled="3", remaining="0"))
    clock.advance(1)
    (ahead,) = proven(state, adapter, clock).findings
    assert ahead.kind == "DISAGREEMENT" and "the stream reported 3 filled, REST 2" in ahead.detail

    state = proven(opened(s=3), adapter, clock).state
    state, _ = run(state, update(1, 1, 3, order_id=order_id, status="resting", filled="1", remaining="1"))
    clock.advance(2)
    proof = proven(state, adapter, clock)
    (behind,) = proof.findings
    assert behind.kind == "REST_AHEAD_OF_STREAM" and not proof.state.quarantines and proof.state.orders == ()


def test_stream_observations_newer_than_the_read_are_not_judged_by_it(venue):
    adapter, clock = venue
    state = proven(opened(s=-10), adapter, clock).state
    state, _ = run(state, fill(2, 1, 30, fill_id="later", order_id="o-later"))  # received after the read starts
    proof = proven(state, adapter, clock)
    assert proof.findings == () and [o.order_id for o in proof.state.orders] == ["o-later"]


# ---------------------------------------------------------------- the contract itself


def test_apply_is_pure_and_states_are_immutable():
    state = opened()
    before = state
    step = rc.apply(state, update(1, 1, 1))
    assert state is before and state.orders == () and step.state.orders != ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.state.incoming = 0  # type: ignore[misc]
    with pytest.raises(ValueError):
        rc.apply(state, "not an item")  # type: ignore[arg-type]
    noted = rc.note_problem(state, rc.Reason.SOURCE_FAILED, at=h.T0, detail="the source raised")
    assert reasons(noted) == ["BASELINE_REQUIRED", "SOURCE_FAILED"]


def test_items_validate_their_fields():
    with pytest.raises(ValueError):
        rc.StreamMessage(1, 1, ORDERS, rc.FillEvent("f", "o", B70, Decimal(1), Decimal("0.4")), rc.Clocks(at(0)))
    with pytest.raises(ValueError):
        rc.Clocks("2026-10-07T15:00:00")  # no zone
    with pytest.raises(ValueError):
        rc.StreamMessage(0, 1, ORDERS, update(1, 1, 0).event, rc.Clocks(at(0)))
    with pytest.raises(m.ExactValueError):
        rc.FillEvent("f", "o", B70, 1.0, Decimal("0.4"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rc.RecoveryConfig(required_channels=frozenset())
    with pytest.raises(ValueError):
        rc.FillEvent("f", "o", B70, Decimal(0), Decimal("0.4"))


def test_every_stream_venue_fact_is_unknown_and_none_is_relied_on():
    assert rc.STREAM_FACTS and {f.support for f in rc.STREAM_FACTS} == {"UNKNOWN"}
    assert len({f.id for f in rc.STREAM_FACTS}) == len(rc.STREAM_FACTS)
