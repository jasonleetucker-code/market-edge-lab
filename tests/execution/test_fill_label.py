"""Bug P-3 (#160 package P): a venue fill count read over an interval is true somewhere between two times, and fills
stamped between them are never added on top of it. FIXTURE only; nothing leaves the process.

The account read labels a listing's cumulative fill count with the snapshot's `observed_at` (the earlier of the read
start and the venue's user-data as_of). That is a LOWER bound: the listing was read later. Before the fix the
lifecycle added every fill stamped more than `TIMESTAMP_SKEW` after that label on top of the count, although the
count already held it, so a fill shortly before a read was counted twice whenever the user-data as_of lagged the read
by more than 2 s (account.py accepts up to `max_data_lag`) or our clock trailed the venue's by 2-5 s (account.py
accepts `CLOCK_SKEW`). The count now also carries an UPPER bound (`ReadManifest.data_true_by`, passed as
`ReconcileObserved.as_of_upper_utc`); only a fill stamped after it is on top, and one between the two is uncertain.
The upper bound covers every record the read returned, and a record stamped past our clock + CLOCK_SKEW makes the read
not COMPLETE (RECORD_STAMPED_IN_FUTURE). Lookup receipts record both bounds, so their count re-derives from them."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import account as acct
from edge_lab.execution import control as ctl
from edge_lab.execution import lifecycle as lc
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution.journal import ExecutionJournal
from edge_lab.execution.lifecycle import (Fill, Liquidity, ReconcileObserved, SendPrepared, SendReturnedAmbiguous,
                                          invariant_problems, reduce)
from edge_lab.execution_ticket import ObligationState, OrderState

D = Decimal
CID, PID = "cid-p3", "prov-p3"
SENT = "2026-10-07T15:00:00+00:00"
B72 = h.MARKETS[1]


def t(sec: int) -> str:
    return m.utc_text(datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc) + timedelta(seconds=sec))


# ---------------------------------------------------------------------------------------------- the reducer


def sent() -> lc.OrderView:
    """As the orchestrator rebuilds a view for each read: opened and prepared, then the read folded in."""
    view = lc.open_view(client_order_id=CID, market_ticker="KXTEST-26OCT07-T50", side=m.Side.YES,
                        action=m.Action.BUY, quantity=D("6"), limit_price=D("0.43"))
    return reduce(view, SendPrepared(SENT))


def listing(filled: str, *, as_of: str | None, upper: str | None, status: str = "resting",
            total: str = "6") -> ReconcileObserved:
    """An order listing row. A canceled or executed order has nothing remaining (its fill count is final)."""
    remaining = D(0) if status in ("canceled", "executed") else D(total) - D(filled)
    return ReconcileObserved(CID, PID, True, status, D(filled), remaining, D(total), None,
                             authoritative_complete=True, as_of_utc=as_of, as_of_upper_utc=upper)


def fill(fid: str, qty: str, at: str | None, fee: str | None = "0.00") -> Fill:
    return Fill(fid, D(qty), D("0.43"), None if fee is None else D(fee), Liquidity.MAKER, at, PID, CID)


def fold(view: lc.OrderView, *events) -> lc.OrderView:
    for e in events:
        view = reduce(view, e)
    assert not view.quarantined, view.quarantine_reasons
    assert not invariant_problems(view), invariant_problems(view)
    return view


def test_fills_between_the_two_bounds_are_never_added_on_top_of_the_count():
    # Read at t(10)..t(40) (lower, upper); the listing says 3 filled; its own fills (2 + 1) are stamped inside it.
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "2", t(20)), fill("f2", "1", t(25)))
    assert (view.filled_quantity, view.remaining_quantity) == (D(3), D(3))
    assert view.state is OrderState.RESTING
    assert view.count_observations[0].as_of_upper_utc == t(40)
    # Uncertain stays uncertain: every fee is known, yet which fills the count covers is not.
    assert view.fill_timing_uncertain and not view.fees_complete


def test_without_an_upper_bound_the_same_fills_are_on_top_of_the_count():
    """The P-3 mechanism itself: labelled only with the lower bound, the fills of the same read are counted twice."""
    view = fold(sent(), listing("3", as_of=t(10), upper=None), fill("f1", "2", t(20)), fill("f2", "1", t(25)))
    assert view.filled_quantity == D(6)


@pytest.mark.parametrize("stamp,expected", [(40, "3"), (41, "5")], ids=["at-the-upper-bound", "one-second-after"])
def test_a_fill_after_the_upper_bound_still_counts_on_top(stamp, expected):
    # The count (3) is above the fills received (1 + 2), so only the count decides: a fill at the upper bound may be
    # inside it; one a second later cannot be, and adds on top.
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "1", t(5)), fill("f2", "2", t(stamp)))
    assert view.filled_quantity == D(expected)
    assert view.fill_timing_uncertain is (stamp == 40)


def test_fills_received_beyond_the_count_inside_the_band_raise_the_lower_bound_only():
    """The order listing and the fill listing race: the fills read later hold 5 while the count read earlier says 3.
    Received fills are a lower bound (5); nothing in the band is added on top of the count (never 8)."""
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "3", t(15)), fill("f2", "2", t(35)))
    assert view.filled_quantity == D(5)
    assert view.fill_timing_uncertain and not view.fees_complete


def test_a_fill_before_the_lower_bound_is_covered_and_certain():
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "3", t(10)))
    assert view.filled_quantity == D(3)
    assert not view.fill_timing_uncertain and view.fees_complete


@pytest.mark.parametrize("upper", [t(9), t(11), "not a time"], ids=["before-as-of", "inside-skew", "unparseable"])
def test_an_upper_bound_never_narrows_the_skew_window(upper):
    # TIMESTAMP_SKEW is 2 s: t(12) is in the window after t(10) whatever the stated upper bound; t(13) is after it.
    in_window = fold(sent(), listing("3", as_of=t(10), upper=upper), fill("f1", "1", t(12)))
    assert in_window.filled_quantity == D(3) and in_window.fill_timing_uncertain
    after = fold(sent(), listing("3", as_of=t(10), upper=upper), fill("f1", "1", t(13)))
    assert after.filled_quantity == D(4)


def test_an_untimed_count_stays_uncertain_whatever_its_upper_bound():
    view = fold(sent(), listing("3", as_of=None, upper=t(40)), fill("f1", "2", t(50)))
    assert view.filled_quantity == D(3) and view.fill_timing_uncertain


def test_an_order_canceled_inside_the_band_keeps_its_final_count():
    """The venue canceled the order after 3 filled; the cancel and the 3 fills all fall inside the read. The final count
    (3) covers the band's fills: nothing is added on top, so it is never 6 > 3 (FILL_EXCEEDS_OPEN_QUANTITY)."""
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40), status="canceled"), fill("f1", "2", t(20)),
                fill("f2", "1", t(25)))
    assert (view.filled_quantity, view.canceled_quantity, view.remaining_quantity) == (D(3), D(3), D(0))
    assert view.state is OrderState.CANCELLED
    assert not view.fill_timing_uncertain and view.fees_complete  # a final count leaves nothing to be on top


def test_an_order_canceled_inside_the_band_without_an_upper_bound_quarantines():
    """The base behaviour the upper bound removes: the band's fills on top of a final count exceed it."""
    view = reduce(reduce(reduce(sent(), listing("3", as_of=t(10), upper=None, status="canceled")),
                         fill("f1", "2", t(20))), fill("f2", "1", t(25)))
    assert view.quarantined and any("FILL_EXCEEDS_OPEN_QUANTITY" in r for r in view.quarantine_reasons)


def test_an_order_executed_inside_the_band_is_filled_once():
    view = fold(sent(), listing("6", as_of=t(10), upper=t(40), status="executed"), fill("f1", "4", t(20)),
                fill("f2", "2", t(30)))
    assert (view.filled_quantity, view.remaining_quantity) == (D(6), D(0))
    assert view.state is OrderState.FILLED and view.fees_complete


def test_a_later_count_is_judged_against_fills_after_the_earlier_counts_upper_bound():
    """Two listings: 3 read over t(10)..t(40), then 3 again at t(50). A fill stamped t(30) is inside the first count,
    so the count implied at t(50) is 3, not 3 + 2: the second listing is not a dispute."""
    view = fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "2", t(30)),
                listing("3", as_of=t(50), upper=t(60)))
    assert view.filled_quantity == D(3)
    assert not any(n.startswith("COUNT_DISPUTED") for n in view.notes), view.notes


def test_a_later_count_still_sees_fills_after_the_earlier_upper_bound():
    """The same, with the fill stamped after the first upper bound: on top of 3, so 3 at t(50) is below 5 implied."""
    view = reduce(fold(sent(), listing("3", as_of=t(10), upper=t(40)), fill("f1", "2", t(42))),
                  listing("3", as_of=t(50), upper=t(60)))
    assert view.quarantined and any("COUNT_BELOW_IMPLIED_FILLS" in r for r in view.quarantine_reasons)


def test_the_dispute_check_uses_the_lower_bound():
    """A count of 2 read over t(20)..t(50) while 3 fills stamped t(30) are already received: judged at the upper bound
    it would quarantine (3 clearly before t(48)); judged at the lower bound it is only stale (noted)."""
    view = fold(sent(), lc.Acknowledged(PID, CID, "resting", D(0), D(6), None, t(1)), fill("f1", "3", t(30)),
                listing("2", as_of=t(20), upper=t(50)))
    assert view.filled_quantity == D(3)
    assert any(n.startswith("STALE_FILL_COUNT") for n in view.notes), view.notes


def test_the_dispute_check_still_quarantines_fills_clearly_before_the_lower_bound():
    view = reduce(fold(sent(), lc.Acknowledged(PID, CID, "resting", D(0), D(6), None, t(1)), fill("f1", "3", t(5))),
                  listing("2", as_of=t(20), upper=t(50)))
    assert view.quarantined and any("COUNT_BELOW_APPLIED_FILLS" in r for r in view.quarantine_reasons)


def test_the_not_found_delay_uses_the_lower_bound():
    """A complete not-found read whose lower bound is 10 s after the send proves nothing (NOT_FOUND_MIN_DELAY 30 s),
    even when its upper bound is a minute later."""
    view = reduce(sent(), SendReturnedAmbiguous(lc.Operation.NEW_ORDER, "timeout"))
    view = reduce(view, ReconcileObserved(CID, None, False, authoritative_complete=True, as_of_utc=t(10),
                                          as_of_upper_utc=t(60)))
    assert view.state is OrderState.OUTCOME_UNKNOWN
    assert any(n.startswith("NOT_FOUND_TOO_EARLY") for n in view.notes), view.notes


def test_the_upper_bound_must_be_text():
    with pytest.raises(TypeError):
        ReconcileObserved(CID, PID, True, "resting", D(0), D(6), as_of_utc=t(10),
                          as_of_upper_utc=datetime(2026, 10, 7, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------------------------- the account read


def manifest(finished: datetime, as_of_end: datetime | None, latest: datetime | None = None) -> acct.ReadManifest:
    return acct.ReadManifest(None, finished - timedelta(seconds=3), finished, 0, (), (), None, as_of_end, (), {}, latest)


END = datetime(2026, 10, 7, 15, 0, 30, tzinfo=timezone.utc)


def test_data_true_by_is_the_read_end_plus_the_clock_tolerance():
    assert manifest(END, None).data_true_by == END + acct.CLOCK_SKEW
    assert manifest(END, END + timedelta(seconds=2), END + timedelta(seconds=4)).data_true_by == END + acct.CLOCK_SKEW


def test_data_true_by_is_the_closing_user_data_as_of_when_that_is_later():
    late = END + acct.CLOCK_SKEW + timedelta(microseconds=1)
    assert manifest(END, late).data_true_by == late


def test_data_true_by_covers_every_record_the_read_returned():
    """A record existed when it was read: no order or fill of the read is ever after the read's own upper bound, so
    none is ever added on top of that read's counts, whatever the clocks do."""
    latest = END + acct.CLOCK_SKEW + timedelta(seconds=4)
    assert manifest(END, END, latest).data_true_by == latest


# ---------------------------------------------------------------------------------------------- the orchestrator


@dataclass
class ClockedAdapter(h.VenueAdapter):
    """The harness venue with its clocks separated from ours. `skew`: the venue's true time minus our clock (our clock
    is slow when positive). `venue_lag`: how far the venue's record stamps trail its true time (the harness uses
    10 minutes, which keeps every fill far before any read). `as_of_lag`: how far its user-data timestamp trails.
    The fake venue's own clock also ticks one second per action, so its stamps may run a little ahead of the target."""

    skew: float = 0.0
    venue_lag: float = 5.0
    as_of_lag: float = 1.0

    def true_now(self) -> datetime:
        return self.clock() + timedelta(seconds=self.skew)

    def sync(self) -> None:
        target = self.true_now() - timedelta(seconds=self.venue_lag)
        gap = int((target - self.venue_now()).total_seconds())
        if gap > 0:
            self.venue.advance(gap)
        fills = self.venue.list_fills()
        for f in fills[self.fills_seen:]:
            self._book_fill(f)
        self.fills_seen = len(fills)

    def __call__(self, request):
        if request.endpoint.name == "GET_USER_DATA_TIMESTAMP" and not self.reads_fail:
            self.sync()
            self.requests.append(request.endpoint.name)
            return h.ok({"as_of_time": m.utc_text(self.true_now() - timedelta(seconds=self.as_of_lag))})
        return super().__call__(request)


@dataclass
class Rig:
    journal: ExecutionJournal
    path: Path
    adapter: ClockedAdapter
    clock: h.Clock
    orch: o.Orchestrator
    attempt_id: str

    def order(self) -> dict:
        pid = self.journal.attempt(self.attempt_id).provider_order_id
        (order,) = [x for x in self.adapter.venue.list_orders(B72) if x["order_id"] == pid]
        return order

    def reservation(self):
        return self.journal.reservations.reservation(self.attempt_id)

    def lookups(self) -> list[dict]:
        """The lookup receipts of our order's reservation, oldest first (read straight from the store)."""
        conn = sqlite3.connect(str(self.path))
        try:
            rows = conn.execute("SELECT payload_json FROM receipts WHERE receipt_id LIKE ? ORDER BY receipt_seq",
                                (f"lookup:{self.attempt_id}:%",)).fetchall()
        finally:
            conn.close()
        return [json.loads(r[0]) for r in rows]

    def cross(self, qty: str) -> None:
        """Someone sells `qty` into our resting bid now, just before the next read."""
        self.adapter.sync()
        self.adapter.venue.add_liquidity(B72, m.Side.NO, "0.57", qty)


@contextmanager
def resting(tmp_path: Path, *, as_of_lag: float, skew: float, venue_lag: float):
    """Boot, arm, rest a GTC buy of 6 at 0.43 on B72 (the best YES bid; the book's best is 0.42), one quiet cycle."""
    clock = h.Clock()
    adapter = ClockedAdapter(clock, skew=skew, venue_lag=venue_lag, as_of_lag=as_of_lag)
    h.seed_books(adapter)
    path = tmp_path / "p3.execution.sqlite3"
    journal = ExecutionJournal.open(path)
    try:
        orch, _ = h.build(journal, adapter)
        assert orch.run_cycle().reconciliation == "COMPLETE"
        assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
        clock.advance(60)
        assert orch.submit_signal(h.signal("rest", B72, at=clock(), limit="0.43", qty="6",
                                           tif="good_till_canceled")).accepted
        (d,) = [d for d in orch.run_cycle().decisions if d.outcome is o.Outcome.SUBMITTED]
        assert d.attempt_state == "ACKNOWLEDGED", d
        clock.advance(60)
        quiet = orch.run_cycle()
        assert quiet.reconciliation == "COMPLETE", quiet  # the order's own stamps are a cycle old by now
        clock.advance(60)
        yield Rig(journal, path, adapter, clock, orch, d.attempt_id)
        assert journal.verify_chain().ok
    finally:
        journal.close()


def rederive(payload: dict, rig: Rig) -> lc.OrderView:
    """Rebuild the view from a lookup receipt alone (plus the reservation's own terms), as `_fold_order` does."""
    r, attempt = rig.reservation(), rig.journal.attempt(rig.attempt_id)
    o_ = payload["order"]
    view = lc.open_view(client_order_id=r.client_order_id, market_ticker=r.market_ticker, side=r.side,
                        action=m.Action.BUY, quantity=r.quantity, limit_price=r.limit_price)
    view = reduce(view, SendPrepared(attempt.created_at_utc))
    view = reduce(view, ReconcileObserved(o_["client_order_id"], o_["order_id"], True, o_["status"], D(o_["fill_count"]),
                                          D(o_["remaining_count"]), D(o_["initial_count"]), D(o_["yes_price"]),
                                          authoritative_complete=payload["authoritative_complete"],
                                          as_of_utc=payload["as_of_utc"], as_of_upper_utc=payload["as_of_upper_utc"]))
    for f in sorted(payload["fills"], key=lambda x: (x["created_time"], x["fill_id"])):
        view = reduce(view, Fill(f["fill_id"], D(f["count"]), D(f["yes_price"]), D(f["fee_cost"]),
                                 Liquidity.TAKER if f["is_taker"] else Liquidity.MAKER, f["created_time"],
                                 f["order_id"], o_["client_order_id"]))
    return view


# (as_of_lag, skew, venue_lag): every case stamps the fill more than TIMESTAMP_SKEW after the snapshot's observed_at
# and within the tolerances account.py accepts (asserted below), so each reproduced P-3 before the fix.
CASES = {
    "user-data-lags-5s": (5.0, 0.0, 1.0),
    "user-data-lags-20s": (20.0, 0.0, 5.0),
    "user-data-lags-55s": (55.0, 0.0, 5.0),
    "our-clock-3s-slow": (1.0, 3.0, 0.0),
    "our-clock-4s-slow": (1.0, 4.0, 1.0),
    "our-clock-5s-slow": (0.0, 5.0, 2.0),
}


@pytest.mark.parametrize("as_of_lag,skew,venue_lag", list(CASES.values()), ids=list(CASES))
def test_a_fill_just_before_a_read_is_recorded_once(tmp_path, as_of_lag, skew, venue_lag):
    with resting(tmp_path, as_of_lag=as_of_lag, skew=skew, venue_lag=venue_lag) as rig:
        rig.cross("3")
        for cycle in range(2):
            report = rig.orch.run_cycle()
            assert report.reconciliation == "COMPLETE", report
            order, r = rig.order(), rig.reservation()
            assert order["status"] == "resting" and order["fill_count"] == D(3)
            assert r.filled_quantity == order["fill_count"] == D(3), "the journal records more fills than the venue"
            assert r.state is not ObligationState.BOUND, "BOUND while the order still rests"
            assert report.mode_at_end is ctl.Mode.BOUNDED_AUTO, report
            if cycle == 0:
                # The repro hits the band: the fill is stamped past the old label's skew window.
                snap = rig.journal.reservations.latest_snapshot(h.SCOPE)
                stamp = m.parse_utc_text(rig.adapter.venue.list_fills()[-1]["created_time"])
                observed = m.parse_utc_text(snap.observed_at_utc)
                assert stamp > observed + lc.TIMESTAMP_SKEW, (stamp, observed)
                # The receipt records both bounds and the view's uncertainty, and re-derives to what it says.
                payload = rig.lookups()[-1]
                assert payload["as_of_utc"] == snap.observed_at_utc
                assert m.parse_utc_text(payload["as_of_upper_utc"]) >= stamp
                assert D(payload["filled_quantity"]) == D(3)
                assert payload["fill_timing_uncertain"] is True and payload["fees_complete"] is False
                again = rederive(payload, rig)
                assert (again.filled_quantity, again.fill_timing_uncertain, again.fees_complete) == (D(3), True, False)
            rig.clock.advance(60)


# The fake venue ticks a second per action, so a cross and a cancel stamp up to 2 s past its target: the slow-clock cases
# keep the venue a little further behind than in CASES, so its stamps stay within CLOCK_SKEW of our clock.
ENDING = {"user-data-lags-20s": (20.0, 0.0, 5.0), "our-clock-4s-slow": (1.0, 4.0, 2.0),
          "our-clock-5s-slow": (0.0, 5.0, 3.0)}


@pytest.mark.parametrize("end", ["cancel", "fill-all"])
@pytest.mark.parametrize("as_of_lag,skew,venue_lag", list(ENDING.values()), ids=list(ENDING))
def test_an_order_that_ends_inside_the_band_is_recorded_once_and_released(tmp_path, as_of_lag, skew, venue_lag, end):
    """The order's final count (canceled or executed) is read in the same band as its fills: no quarantine, no disarm,
    the journal never above the venue, and the reservation released at the venue's count."""
    with resting(tmp_path, as_of_lag=as_of_lag, skew=skew, venue_lag=venue_lag) as rig:
        if end == "cancel":
            rig.cross("3")
            rig.adapter.venue.cancel(rig.journal.attempt(rig.attempt_id).provider_order_id)
        else:
            rig.cross("6")
        for cycle in range(4):
            report = rig.orch.run_cycle()
            assert report.reconciliation == "COMPLETE", report
            assert report.mode_at_end is ctl.Mode.BOUNDED_AUTO and not report.incidents, report
            assert rig.reservation().filled_quantity <= rig.order()["fill_count"]
            if cycle == 0:  # the band read: every fill is stamped past the old label's skew window
                observed = m.parse_utc_text(rig.journal.reservations.latest_snapshot(h.SCOPE).observed_at_utc)
                assert all(m.parse_utc_text(f["created_time"]) > observed + lc.TIMESTAMP_SKEW
                           for f in rig.adapter.venue.list_fills())
            rig.clock.advance(60)
        order, r = rig.order(), rig.reservation()
        assert order["status"] == ("canceled" if end == "cancel" else "executed"), order
        assert r.state is ObligationState.RELEASED and r.filled_quantity == order["fill_count"], r
        band = rig.lookups()[0]  # the first receipt is from the band read
        assert band["order"]["status"] == order["status"] and D(band["filled_quantity"]) == order["fill_count"]
        (attribution,) = [x.body for x in rig.journal.control_records(h.SCOPE, "ATTRIBUTION")]
        assert D(attribution["filled_quantity"]) == order["fill_count"] and attribution["fees_complete"] is True


LEADS = {"venue-7s-ahead-as-of-lags-3s": (3.0, 7.0, 0.0), "venue-5s-ahead-stamps-drift": (1.0, 5.0, 0.0)}


@pytest.mark.parametrize("as_of_lag,skew,venue_lag", list(LEADS.values()), ids=list(LEADS))
def test_a_venue_clock_leading_beyond_the_tolerance_is_caught_by_the_record_stamps(tmp_path, as_of_lag, skew,
                                                                                    venue_lag):
    """The opening as_of check misses a lead hidden by the as_of's own lag (7 s ahead, as_of 3 s behind: within 5 s).
    The records cannot hide it: an order or fill stamped after the read's end plus CLOCK_SKEW makes the read not
    COMPLETE with live orders and fills unknown, so nothing of it is folded and nothing is counted twice."""
    with resting(tmp_path, as_of_lag=as_of_lag, skew=skew, venue_lag=venue_lag) as rig:
        rig.cross("3")
        report = rig.orch.run_cycle()  # the fill is stamped past our clock + CLOCK_SKEW: the read is not COMPLETE
        assert report.reconciliation == "PARTIAL" and report.mode_at_end is ctl.Mode.DISARMED, report
        assert rig.reservation().filled_quantity == D(0)  # live orders and fills unknown: nothing folded
        rig.clock.advance(60)
        report = rig.orch.run_cycle()  # a minute later the stamps are no longer ahead: recorded once
        order, r = rig.order(), rig.reservation()
        assert report.reconciliation == "COMPLETE" and report.mode_at_end is ctl.Mode.DISARMED, report
        assert order["status"] == "resting" and r.filled_quantity == order["fill_count"] == D(3)
        assert r.state is not ObligationState.BOUND
        rig.cross("1")
        clock = rig.clock
        plan = acct.AccountReadPlan(scope=h.SCOPE, subaccounts=(0,), endpoints=frozenset(acct.AccountEndpoint),
                                    page_limit=100, max_pages=50, max_requests=500,
                                    deadline=clock() + timedelta(minutes=1))
        recon = acct.reconcile_account(plan, rig.adapter, clock=clock)
        assert recon.status is acct.ReconciliationStatus.PARTIAL
        assert any(p.startswith("RECORD_STAMPED_IN_FUTURE") for p in recon.problems), recon.problems
        assert not any(p.startswith("USER_DATA_AS_OF_IN_FUTURE") for p in recon.problems), recon.problems
        sub = recon.subaccounts[0]
        assert sub.orders is None and sub.fills is None  # unknown, never folded
        latest = max(m.parse_utc_text(f["created_time"]) for f in rig.adapter.venue.list_fills())
        assert recon.manifest.latest_record_at >= latest and recon.manifest.data_true_by >= latest
