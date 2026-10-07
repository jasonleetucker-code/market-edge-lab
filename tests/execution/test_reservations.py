"""Atomic cash and inventory reservations with fencing (#160 package E). FIXTURE only; no network."""

from __future__ import annotations

import decimal
import itertools
import multiprocessing
import queue
import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import model as m
from edge_lab.execution import reservations as res
from edge_lab.execution.journal import AttemptRefused, AttemptState, ExecutionJournal, JournalUnavailable
from edge_lab.execution.reservations import (AttributedOrder, CashBasis, EndReason, ExternalOrder, ExternalOrigin,
                                             InvalidTransition, LeaseHeld, ReceiptKind as K, ReleaseReason,
                                             ReservationRefused, SnapshotRefused, StaleFence)
from edge_lab.execution_ticket import ObligationState

NOW = f.NOW
YES, NO = m.Side.YES, m.Side.NO
OTHER = "KXOTHER-26OCT07-T60"
_ids = itertools.count(1)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "exec.execution.sqlite3"


def _open(path: Path, **kw):
    return f.ready(path, **kw)


def _ev(journal, reservation_id: str, kind: K, at=NOW) -> str:
    """A fresh receipt of `kind` bound to the reservation's attempt."""
    return f.receipt(journal, f"r-{next(_ids)}", kind, reservation_id, at=at)


def _ext(ref: str, *, origin=ExternalOrigin.MANUAL, market=f.MARKET, side=YES, action=m.Action.SELL,
         qty: str | None = "1", cash: str | None = "0") -> ExternalOrder:
    return ExternalOrder(ref, origin, market, side, action, None if qty is None else Decimal(qty),
                         None if cash is None else Decimal(cash))


def _decide(journal, intent, at=NOW):
    return journal.reservations.evaluate(intent, at, snapshot_max_age=f.MAX_AGE)


def _acked(journal, intent, token, at=NOW):
    """Prepare, send and acknowledge one order. Returns its reservation id."""
    a = f.prepare(journal, intent, token, at=at)
    journal.mark_sent(a.attempt_id, now=at)
    journal.mark_acknowledged(a.attempt_id, provider_order_id=f"p-{a.attempt_no}-{intent.intent_key}",
                              receipt_id=_ev(journal, a.attempt_id, K.ORDER_ACK, at), now=at)
    return a.reservation_id


# ---------------------------------------------------------------- the canonical arithmetic owner


def test_reserve_calls_the_canonical_obligation_function_with_local_external_and_candidate(path, monkeypatch):
    journal, token = _open(path, externals=(_ext("manual-1", action=m.Action.BUY, side=NO, cash="0.25"),))
    first = f.prepare(journal, f.entry("EXP-TEST:a"), token)
    seen = []
    real = res.reserve_simultaneous_obligations

    def spy(obligations, *, available_cash, candidate=None):
        seen.append((obligations, available_cash, candidate))
        return real(obligations, available_cash=available_cash, candidate=candidate)

    monkeypatch.setattr(res, "reserve_simultaneous_obligations", spy)
    f.prepare(journal, f.entry("EXP-TEST:b", quantity="2", cost="1.00"), token)
    (obligations, cash, candidate), = seen
    assert cash == Decimal("100")
    assert {o.obligation_id: (o.state, o.worst_case_loss) for o in obligations} == {
        f"local:{first.reservation_id}": (ObligationState.OUTSTANDING, Decimal("4.6")),
        "external:0:manual-1": (ObligationState.OUTSTANDING, Decimal("0.25"))}
    assert candidate.worst_case_loss == Decimal("1.00") and candidate.state is ObligationState.OUTSTANDING
    journal.close()


def test_reservation_states_mirror_obligation_states():
    assert set(res._TRANSITIONS) == set(ObligationState)


# ---------------------------------------------------------------- cash: boundaries, double counting, double spending


def test_exactly_equal_cash_is_allowed_and_one_cent_more_is_refused(path):
    journal, token = _open(path, cash="4.60")
    assert f.prepare(journal, f.entry(cost="4.60"), token).state is AttemptState.PENDING_EGRESS
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.entry("EXP-TEST:b", quantity="1", price="0.01", cost="0.01"), token)
    journal.close()
    journal, token = _open(path.with_name("b.execution.sqlite3"), cash="4.59")
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.entry(cost="4.60"), token)
    journal.close()


def test_a_local_only_reservation_is_counted_against_venue_cash_no_double_spend(path):
    journal, token = _open(path, cash="10")
    first = f.prepare(journal, f.entry("EXP-TEST:a", quantity="10", price="0.60", cost="6.00"), token)
    assert not journal.reservations.reservation(first.reservation_id).provider_held
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.entry("EXP-TEST:b", quantity="10", price="0.60", cost="6.00"), token)
    # A newer snapshot that does not list the order still has not seen it: it stays local-only.
    f.snapshot(journal, 2, cash="10")
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.entry("EXP-TEST:b", quantity="10", price="0.60", cost="6.00"), token)
    assert f.prepare(journal, f.entry("EXP-TEST:c", quantity="8", price="0.50", cost="4.00"), token)
    journal.close()


def test_a_provider_held_reservation_is_not_counted_twice(path):
    journal, token = _open(path, cash="10")
    rid = _acked(journal, f.entry("EXP-TEST:a", quantity="10", price="0.60", cost="6.00"), token)
    view = journal.reservations.reservation(rid)
    # The venue now lists our order and holds its 6.00: spendable cash fell to 4.00.
    f.snapshot(journal, 2, cash="4", attributed=(f.attributed(view),))
    assert journal.reservations.reservation(rid).provider_held
    decision = _decide(journal, f.entry("EXP-TEST:b", quantity="8", price="0.50", cost="4.00"))
    assert decision.allowed, decision.reasons  # 4.00 fits: the held 6.00 is not subtracted again
    assert not _decide(journal, f.entry("EXP-TEST:b", quantity="9", price="0.45", cost="4.06")).allowed
    # A residual the venue does not hold (a fee) still counts.
    f.snapshot(journal, 3, cash="4", attributed=(f.attributed(view, unreflected="0.10"),))
    assert not _decide(journal, f.entry("EXP-TEST:b", quantity="8", price="0.50", cost="4.00")).allowed
    assert _decide(journal, f.entry("EXP-TEST:b", quantity="7", price="0.55", cost="3.90")).allowed
    journal.close()


def test_an_attributed_order_with_an_unknown_residual_blocks_new_risk(path):
    journal, token = _open(path, cash="10")
    rid = _acked(journal, f.entry("EXP-TEST:a", quantity="2", price="0.50", cost="1.00"), token)
    f.snapshot(journal, 2, cash="9", attributed=(f.attributed(journal.reservations.reservation(rid), unreflected=None),))
    decision = _decide(journal, f.entry("EXP-TEST:b", quantity="1", price="0.50", cost="0.50"))
    assert not decision.allowed and any("EXPOSURE_UNKNOWN" in r for r in decision.reasons)
    journal.close()


def test_a_reduction_reserves_its_fee_bound_as_cash(path):
    journal, token = _open(path, cash="0.10", positions={(f.MARKET, YES): Decimal("5")})
    assert f.prepare(journal, f.reduction(fee="0.10"), token).state is AttemptState.PENDING_EGRESS
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.reduction("EXP-TEST:exit-2", quantity="1", fee="0.01"), token)
    journal.close()


def test_decisions_do_not_depend_on_the_callers_decimal_context(path):
    """Review finding 7: under a 3-digit thread context 1000.00 + 0.02 rounds to 1.00E+3 <= 1000.01."""
    journal, token = _open(path, cash="1000.01")
    f.prepare(journal, f.entry("EXP-TEST:big", quantity="2000", price="0.50", cost="1000.00"), token)
    small = f.entry("EXP-TEST:small", quantity="1", price="0.01", cost="0.02")
    with decimal.localcontext(decimal.Context(prec=3)):
        decision = _decide(journal, small)
        assert not decision.allowed and decision.cash_required == Decimal("1000.02"), decision
        with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
            f.prepare(journal, small, token)
    assert _decide(journal, f.entry("EXP-TEST:tiny", quantity="1", price="0.01", cost="0.01")).allowed
    journal.close()


# ---------------------------------------------------------------- unknown is never zero


@pytest.mark.parametrize("kw,reason", [
    (dict(basis=CashBasis.UNKNOWN), "CASH_BASIS_UNKNOWN"),
    (dict(cash=None), "CASH_UNKNOWN"),
    (dict(externals=None), "EXTERNAL_ORDERS_UNKNOWN"),
    (dict(externals=(_ext("auto-1", origin=ExternalOrigin.UNKNOWN, cash=None),)), "EXPOSURE_UNKNOWN"),
    (dict(at=NOW - timedelta(minutes=6)), "SNAPSHOT_STALE"),
])
def test_unknown_cash_or_worst_case_or_stale_state_allows_no_new_risk(path, kw, reason):
    with ExecutionJournal.open(path) as journal:
        at = kw.pop("at", NOW)
        journal.reservations.record_account_snapshot(
            f.SCOPE, 1, at, None if kw.get("cash", "100") is None else Decimal(kw.get("cash", "100")),
            kw.get("basis", CashBasis.AVAILABLE_AFTER_VENUE_HOLDS), {}, kw.get("externals", ()), now=NOW)
        token = journal.reservations.acquire_lease(f.WORKER, f.TTL, NOW)
        before = f.counts(path)
        with pytest.raises(ReservationRefused, match=reason):
            f.prepare(journal, f.entry(quantity="1", price="0.01", cost="0.01"), token)
        assert f.counts(path) == before


def test_no_snapshot_means_no_new_risk(path):
    with ExecutionJournal.open(path) as journal:
        token = journal.reservations.acquire_lease(f.WORKER, f.TTL, NOW)
        with pytest.raises(ReservationRefused, match="NO_ACCOUNT_SNAPSHOT"):
            f.prepare(journal, f.entry(), token)


def test_a_snapshot_with_missing_fields_is_unknown_not_flat(path):
    with ExecutionJournal.open(path) as journal:
        snap = journal.reservations.record_account_snapshot(f.SCOPE, 1, NOW, None, CashBasis.UNKNOWN, None, None,
                                                            now=NOW)
        assert snap.cash is None and snap.positions is None and snap.external_orders is None
        decision = _decide(journal, f.reduction(fee="0"))
        assert not decision.allowed and decision.inventory_available is None
        assert any("POSITIONS_UNKNOWN" in r for r in decision.reasons)
        assert any("CASH_UNKNOWN" in r for r in decision.reasons)
        stored = journal._conn.execute("SELECT cash, positions_json, external_orders_json FROM account_snapshots").fetchone()
        assert stored == (None, None, None)


# ---------------------------------------------------------------- snapshot revisions, clocks and consistency


def test_revisions_must_strictly_increase(path):
    with ExecutionJournal.open(path) as journal:
        f.snapshot(journal, 5)
        for rev in (5, 4, 1):
            with pytest.raises(SnapshotRefused):
                f.snapshot(journal, rev)
        assert journal.reservations.latest_snapshot(f.SCOPE).revision == 5
        f.snapshot(journal, 6)


def test_a_snapshot_from_the_future_is_refused_beyond_the_skew(path):
    """Review finding 8."""
    with ExecutionJournal.open(path) as journal:
        rv = journal.reservations
        args = (Decimal("1"), CashBasis.AVAILABLE_AFTER_VENUE_HOLDS, {}, ())
        with pytest.raises(SnapshotRefused, match="after now"):
            rv.record_account_snapshot(f.SCOPE, 1, NOW + res.SNAPSHOT_CLOCK_SKEW + timedelta(microseconds=1), *args,
                                       now=NOW)
        assert rv.latest_snapshot(f.SCOPE) is None
        assert rv.record_account_snapshot(f.SCOPE, 1, NOW + res.SNAPSHOT_CLOCK_SKEW, *args, now=NOW).consistent


def test_inputs_must_be_exact(path):
    with ExecutionJournal.open(path) as journal:
        rv = journal.reservations
        with pytest.raises(m.ExactValueError):
            rv.record_account_snapshot(f.SCOPE, 1, NOW, 10.0, CashBasis.AVAILABLE_AFTER_VENUE_HOLDS, {}, (), now=NOW)
        with pytest.raises(m.ExactValueError):
            rv.record_account_snapshot(f.SCOPE, 1, NOW, Decimal("1"), CashBasis.AVAILABLE_AFTER_VENUE_HOLDS,
                                       {(f.MARKET, YES): 3.0}, (), now=NOW)
        with pytest.raises(ValueError):
            rv.record_account_snapshot(f.SCOPE, 1, NOW, Decimal("1"), CashBasis.AVAILABLE_AFTER_VENUE_HOLDS,
                                       {(f.MARKET, "yes"): Decimal(3)}, (), now=NOW)


@pytest.mark.parametrize("kw,problem", [
    (dict(cash="-0.01"), "NEGATIVE_CASH"),
    (dict(positions={(f.MARKET, YES): Decimal("-1")}), "NEGATIVE_POSITION"),
    (dict(externals=(_ext("x", qty="-2"),)), "NEGATIVE_EXTERNAL_REMAINING_QUANTITY"),
    (dict(externals=(_ext("x"), _ext("x"))), "DUPLICATE_EXTERNAL_ORDER"),
    (dict(attributed=(AttributedOrder("not-ours", "c", Decimal(1), Decimal("0.5"), Decimal(0)),)),
     "ATTRIBUTION_UNKNOWN"),
])
def test_an_inconsistent_balance_is_recorded_as_evidence_and_blocks_new_risk(path, kw, problem):
    journal, token = _open(path)
    snap = f.snapshot(journal, 2, **kw)
    assert not snap.consistent and any(p.startswith(problem) for p in snap.problems), snap.problems
    with pytest.raises(ReservationRefused, match="SNAPSHOT_INCONSISTENT"):
        f.prepare(journal, f.entry(quantity="1", price="0.01", cost="0.01"), token)
    f.snapshot(journal, 3)  # a consistent later revision restores capacity
    assert f.prepare(journal, f.entry(quantity="1", price="0.01", cost="0.01"), token)
    journal.close()


def test_time_going_backwards_between_revisions_is_inconsistent(path):
    with ExecutionJournal.open(path) as journal:
        f.snapshot(journal, 1)
        snap = f.snapshot(journal, 2, at=NOW - timedelta(seconds=1))
        assert not snap.consistent and snap.problems[0].startswith("OBSERVED_BEFORE_PREVIOUS_REVISION")


# ---------------------------------------------------------------- attribution is bound to one reservation (finding 4)


@pytest.mark.parametrize("change,problem", [
    (dict(remaining="9"), "ATTRIBUTION_SIZE_MISMATCH"),
    (dict(price="0.41"), "ATTRIBUTION_PRICE_MISMATCH"),
    (dict(client="someone-else"), "ATTRIBUTION_MISMATCH"),
    (dict(observed=NOW - timedelta(seconds=1)), "ATTRIBUTION_BEFORE_RESERVATION"),
])
def test_an_attribution_that_does_not_match_its_reservation_is_inconsistent(path, change, problem):
    journal, token = _open(path, cash="10")
    rid = _acked(journal, f.entry(quantity="10", price="0.42", cost="4.60"), token)
    view = journal.reservations.reservation(rid)
    a = f.attributed(view, remaining=change.get("remaining"), price=change.get("price"))
    if "client" in change:
        a = AttributedOrder(a.reservation_id, change["client"], a.remaining_quantity, a.limit_price, a.unreflected_cash)
    observed = change.get("observed", NOW)
    snap = journal.reservations.record_account_snapshot(f.SCOPE, 2, observed, Decimal("5.4"),
                                                        CashBasis.AVAILABLE_AFTER_VENUE_HOLDS, {}, (),
                                                        attributed_open_orders=(a,), now=NOW)
    assert not snap.consistent and any(p.startswith(problem) for p in snap.problems), snap.problems
    assert not _decide(journal, f.entry("EXP-TEST:b", quantity="1", price="0.01", cost="0.01")).allowed
    journal.close()


def test_attribution_names_the_attempt_not_just_the_shared_client_order_id(path):
    """Every attempt of an intent shares one client order id; a listing of the released first attempt
    must not make the live second attempt look venue-held."""
    journal, token = _open(path, cash="10")
    intent = f.entry(quantity="10", price="0.42", cost="4.60")
    first = f.prepare(journal, intent, token, nonce="n-1")
    journal.mark_sent(first.attempt_id, now=NOW)
    journal.mark_rejected(first.attempt_id, receipt_id=_ev(journal, first.attempt_id, K.ORDER_REJECT), now=NOW)
    second = f.prepare(journal, intent, token, nonce="n-2")
    assert first.client_order_id == second.client_order_id
    stale = AttributedOrder(first.reservation_id, first.client_order_id, Decimal(10), Decimal("0.42"), Decimal(0))
    snap = f.snapshot(journal, 2, cash="5.4", attributed=(stale,))
    assert not snap.consistent and any(p.startswith("ATTRIBUTION_UNKNOWN") for p in snap.problems)
    assert not journal.reservations.reservation(second.reservation_id).provider_held
    good = f.snapshot(journal, 3, cash="5.4", attributed=(f.attributed(journal.reservations.reservation(
        second.reservation_id)),))
    assert good.consistent and journal.reservations.reservation(second.reservation_id).provider_held
    journal.close()


def test_absent_is_refused_while_the_latest_snapshot_lists_the_order(path):
    journal, token = _open(path)
    a = f.prepare(journal, f.entry(), token)
    journal.mark_outcome_unknown(a.attempt_id, reason="timeout after egress", now=NOW)
    f.snapshot(journal, 2, attributed=(f.attributed(journal.reservations.reservation(a.reservation_id)),))
    lookup = _ev(journal, a.attempt_id, K.ORDER_LOOKUP)
    with pytest.raises(InvalidTransition, match="still lists"):
        journal.reconcile_attempt(a.attempt_id, AttemptState.ABSENT, receipt_id=lookup, now=NOW)
    assert journal.attempt(a.attempt_id).state is AttemptState.OUTCOME_UNKNOWN
    f.snapshot(journal, 3)  # no longer listed
    assert journal.reconcile_attempt(a.attempt_id, AttemptState.ABSENT, receipt_id=lookup,
                                     now=NOW).state is AttemptState.ABSENT
    journal.close()


# ---------------------------------------------------------------- inventory


def test_exactly_equal_inventory_is_allowed_and_no_oversell(path):
    journal, token = _open(path, positions={(f.MARKET, YES): Decimal("5")})
    f.prepare(journal, f.reduction("EXP-TEST:exit-1", quantity="3", fee="0"), token)
    decision = _decide(journal, f.reduction("EXP-TEST:exit-2", quantity="3", fee="0"))
    assert not decision.allowed and decision.inventory_available == Decimal("2")
    assert any("INSUFFICIENT_INVENTORY" in r for r in decision.reasons)
    assert f.prepare(journal, f.reduction("EXP-TEST:exit-2", quantity="2", fee="0"), token)
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_INVENTORY"):
        f.prepare(journal, f.reduction("EXP-TEST:exit-3", quantity="1", fee="0"), token)
    journal.close()


def test_fractional_inventory_boundary(path):
    tenth = m.Grid(step=Decimal("0.1"), minimum=Decimal("0.1"), maximum=Decimal("100"))
    journal, token = _open(path, positions={(f.MARKET, YES): Decimal("2.5")})
    assert not _decide(journal, f.reduction(quantity="2.6", fee="0", quantity_grid=tenth)).allowed
    assert f.prepare(journal, f.reduction(quantity="2.5", fee="0", quantity_grid=tenth), token)
    journal.close()


def test_no_cross_market_or_cross_side_netting(path):
    journal, _ = _open(path, positions={(f.MARKET, YES): Decimal("10"), (OTHER, NO): Decimal("10")})
    assert _decide(journal, f.reduction(quantity="10", fee="0")).allowed
    assert not _decide(journal, f.reduction(quantity="1", fee="0", side=NO)).allowed  # NO in this market: none held
    assert not _decide(journal, f.reduction(quantity="1", fee="0", market_ticker=OTHER)).allowed  # YES elsewhere
    assert _decide(journal, f.reduction(quantity="10", fee="0", market_ticker=OTHER, side=NO)).allowed
    journal.close()


def test_a_manual_sale_appearing_in_a_new_snapshot_shrinks_inventory(path):
    journal, _ = _open(path, positions={(f.MARKET, YES): Decimal("10")})
    assert _decide(journal, f.reduction(quantity="10", fee="0")).allowed
    f.snapshot(journal, 2, positions={(f.MARKET, YES): Decimal("4")})  # someone sold 6 by hand
    assert not _decide(journal, f.reduction(quantity="5", fee="0")).allowed
    assert _decide(journal, f.reduction(quantity="4", fee="0")).allowed
    # A resting manual sell and a native Auto Sell also consume inventory, whatever their price.
    f.snapshot(journal, 3, positions={(f.MARKET, YES): Decimal("4")},
               externals=(_ext("manual-sell", qty="1"),
                          _ext("auto-sell", origin=ExternalOrigin.NATIVE_AUTO_SELL, qty="2")))
    assert _decide(journal, f.reduction(quantity="1", fee="0")).inventory_available == Decimal("1")
    assert not _decide(journal, f.reduction(quantity="2", fee="0")).allowed
    # An external order of unknown market, side or size could sell anything.
    f.snapshot(journal, 4, positions={(f.MARKET, YES): Decimal("4")},
               externals=(ExternalOrder("mystery", ExternalOrigin.UNKNOWN, None, None, None, None, Decimal("0")),))
    decision = _decide(journal, f.reduction(quantity="1", fee="0"))
    assert not decision.allowed and any("INVENTORY_UNKNOWN" in r for r in decision.reasons)
    # An external BUY on the same key does not consume inventory.
    f.snapshot(journal, 5, positions={(f.MARKET, YES): Decimal("4")},
               externals=(_ext("manual-buy", action=m.Action.BUY, qty="9"),))
    assert _decide(journal, f.reduction(quantity="4", fee="0")).allowed
    journal.close()


def test_a_local_entry_fill_never_creates_sellable_inventory_before_a_snapshot_shows_it(path):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    journal.reservations.record_fill(rid, Decimal("10"), NOW, receipt_id=_ev(journal, rid, K.FILL))
    assert not _decide(journal, f.reduction(quantity="1", fee="0")).allowed
    journal.close()


# ---------------------------------------------------------------- release only on confirmed outcomes


def test_a_cancel_after_a_partial_fill_never_frees_spent_cash(path):
    """Review finding 1, reproduced: $5 free; a $5 entry is acked and fills 4 ($2); the cancel is confirmed.
    It used to be RELEASED, letting a second $5 entry through with only $3 truly free."""
    journal, token = _open(path, cash="5")
    rid = _acked(journal, f.entry("EXP-TEST:a", quantity="10", price="0.50", cost="5.00"), token)
    second = f.entry("EXP-TEST:b", quantity="10", price="0.50", cost="5.00")
    # The cancel confirmation reports 4 filled, though no fill message has arrived locally yet.
    done = journal.reservations.confirm_cancel(rid, NOW, receipt_id=_ev(journal, rid, K.CANCEL_CONFIRM),
                                               venue_filled=Decimal("4"))
    assert done.state is ObligationState.BOUND and done.filled_quantity == Decimal("4")
    assert done.end_reason is EndReason.CANCEL_CONFIRMED and done.release_reason is None
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, second, token)
    # The fill message arrives after the cancel confirmation: recorded, not refused.
    late = journal.reservations.record_fill(rid, Decimal("4"), NOW, receipt_id=_ev(journal, rid, K.FILL))
    assert late.state is ObligationState.BOUND
    # Release needs a snapshot observed after the end; it shows the $2 spent.
    later = NOW + timedelta(seconds=10)
    f.snapshot(journal, 2, cash="3", positions={(f.MARKET, YES): Decimal("4")}, at=later)
    released = journal.reservations.confirm_by_snapshot(rid, 2, later)
    assert released.release_reason is ReleaseReason.CONVERTED_TO_POSITION
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal, second, token, at=later)  # $3 truly free
    assert f.prepare(journal, f.entry("EXP-TEST:c", quantity="6", price="0.50", cost="3.00"), token, at=later)
    journal.close()


def test_a_cancel_after_a_partial_reduction_never_frees_sold_inventory(path):
    """Finding 1 for inventory: 10 held, a 10-lot sell fills 4 and is cancelled."""
    journal, token = _open(path, positions={(f.MARKET, YES): Decimal("10")})
    rid = _acked(journal, f.reduction("EXP-TEST:exit-1", quantity="10", fee="0"), token)
    journal.reservations.confirm_cancel(rid, NOW, receipt_id=_ev(journal, rid, K.CANCEL_CONFIRM),
                                        venue_filled=Decimal("4"))
    assert not _decide(journal, f.reduction("EXP-TEST:exit-2", quantity="7", fee="0")).allowed
    assert not _decide(journal, f.reduction("EXP-TEST:exit-2", quantity="1", fee="0")).allowed  # held in full
    later = NOW + timedelta(seconds=10)
    f.snapshot(journal, 2, positions={(f.MARKET, YES): Decimal("6")}, at=later)
    journal.reservations.confirm_by_snapshot(rid, 2, later)
    assert not _decide(journal, f.reduction("EXP-TEST:exit-2", quantity="7", fee="0"), later).allowed
    assert _decide(journal, f.reduction("EXP-TEST:exit-2", quantity="6", fee="0"), later).allowed
    journal.close()


def test_a_lost_cancel_releases_nothing(path):
    journal, token = _open(path, cash="5")
    rid = _acked(journal, f.entry("EXP-TEST:a", quantity="10", price="0.40", cost="4.00"), token)
    candidate = f.entry("EXP-TEST:b", quantity="10", price="0.40", cost="4.00")
    assert journal.reservations.request_cancel(rid, NOW).state is ObligationState.CANCEL_REQUESTED
    decision = _decide(journal, candidate)
    assert not decision.allowed and any("CANCEL_NOT_CONFIRMED" in x for x in decision.reasons)
    # The cancel's answer never comes: the state is lost, and it stays reserved.
    assert journal.reservations.mark_unknown(rid, NOW, reason="cancel response lost").state is ObligationState.UNKNOWN
    decision = _decide(journal, candidate)
    assert not decision.allowed and any("UNKNOWN_STATE_QUARANTINE" in x for x in decision.reasons)
    with pytest.raises(InvalidTransition, match="RECEIPT_NOT_RECORDED"):
        journal.reservations.confirm_cancel(rid, NOW, receipt_id="never-recorded", venue_filled=Decimal(0))
    ended = journal.reservations.confirm_cancel(rid, NOW, receipt_id=_ev(journal, rid, K.CANCEL_CONFIRM),
                                                venue_filled=Decimal(0))
    assert ended.state is ObligationState.BOUND and not _decide(journal, candidate).allowed  # until a snapshot
    with pytest.raises(InvalidTransition, match="observed before"):
        journal.reservations.confirm_by_snapshot(rid, 1, NOW)  # revision 1 predates the cancel
    later = NOW + timedelta(seconds=5)
    f.snapshot(journal, 2, cash="5", at=later)
    done = journal.reservations.confirm_by_snapshot(rid, 2, later)
    assert done.state is ObligationState.RELEASED and done.release_reason is ReleaseReason.CANCEL_CONFIRMED
    assert _decide(journal, candidate, later).allowed
    with pytest.raises(InvalidTransition):
        journal.reservations.request_cancel(rid, later)  # RELEASED is terminal for ordinary transitions
    journal.close()


def test_a_snapshot_still_listing_the_order_does_not_release_it(path):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    view = journal.reservations.reservation(rid)
    journal.reservations.mark_expired(rid, NOW, receipt_id=_ev(journal, rid, K.ORDER_EXPIRED), venue_filled=Decimal(0))
    later = NOW + timedelta(seconds=1)
    f.snapshot(journal, 2, at=later, attributed=(f.attributed(view),))
    with pytest.raises(InvalidTransition, match="still lists"):
        journal.reservations.confirm_by_snapshot(rid, 2, later)
    f.snapshot(journal, 3, at=later)
    assert journal.reservations.confirm_by_snapshot(rid, 3, later).release_reason is ReleaseReason.EXPIRED
    journal.close()


def test_a_fill_after_the_cancel_moves_the_release_point_later(path):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    journal.reservations.confirm_cancel(rid, NOW, receipt_id=_ev(journal, rid, K.CANCEL_CONFIRM),
                                        venue_filled=Decimal(0))
    t1, t2 = NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)
    f.snapshot(journal, 2, at=t1)
    late = journal.reservations.record_fill(rid, Decimal("3"), t2, receipt_id=_ev(journal, rid, K.FILL))
    assert late.state is ObligationState.BOUND and late.filled_quantity == Decimal("3")
    with pytest.raises(InvalidTransition, match="observed before"):
        journal.reservations.confirm_by_snapshot(rid, 2, t2)  # predates the late fill
    with pytest.raises(InvalidTransition, match="strictly later"):
        f.snapshot(journal, 3, at=t2, positions={(f.MARKET, YES): Decimal("3")})
        journal.reservations.confirm_by_snapshot(rid, 3, t2)  # the same instant as the fill is not after it
    t3 = t2 + timedelta(microseconds=1)
    f.snapshot(journal, 4, at=t3, positions={(f.MARKET, YES): Decimal("3")})
    assert journal.reservations.confirm_by_snapshot(rid, 4, t3).release_reason is ReleaseReason.CONVERTED_TO_POSITION
    journal.close()


@pytest.mark.parametrize("bad,reason", [("3", "FILL_SHRANK"), ("11", "FILL_EXCEEDS_ORDER")])
def test_a_contradicting_fill_is_recorded_and_quarantines(path, bad, reason):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    rv = journal.reservations
    rv.record_fill(rid, Decimal("4"), NOW, receipt_id=_ev(journal, rid, K.FILL))
    q = rv.record_fill(rid, Decimal(bad), NOW, receipt_id=_ev(journal, rid, K.FILL))
    assert q.state is ObligationState.UNKNOWN and q.quarantine_reason.startswith(reason)
    assert q.filled_quantity == Decimal("4")  # the contradiction is recorded in the event, not applied
    decision = _decide(journal, f.entry("EXP-TEST:b", quantity="1", price="0.01", cost="0.01"))
    assert not decision.allowed and any("EXPOSURE_UNKNOWN" in r for r in decision.reasons)  # blocks the scope
    assert journal.verify_chain().ok
    resolved = rv.resolve_quarantine(rid, NOW, receipt_id=_ev(journal, rid, K.ORDER_LOOKUP), venue_filled=Decimal("5"))
    assert resolved.quarantine_reason is None and resolved.filled_quantity == Decimal("5")
    assert resolved.state is ObligationState.UNKNOWN  # still held; the lifecycle continues from the venue's state
    assert _decide(journal, f.entry("EXP-TEST:b", quantity="1", price="0.01", cost="0.01")).allowed


def test_a_fill_after_release_reopens_the_reservation_instead_of_vanishing(path):
    journal, token = _open(path, cash="5")
    a = f.prepare(journal, f.entry("EXP-TEST:a", quantity="10", price="0.40", cost="4.00"), token)
    journal.mark_sent(a.attempt_id, now=NOW)
    journal.mark_rejected(a.attempt_id, receipt_id=_ev(journal, a.attempt_id, K.ORDER_REJECT), now=NOW)
    assert journal.reservations.reservation(a.reservation_id).state is ObligationState.RELEASED
    q = journal.reservations.record_fill(a.reservation_id, Decimal("2"), NOW, receipt_id=_ev(journal, a.reservation_id,
                                                                                             K.FILL))
    assert q.state is ObligationState.UNKNOWN and q.quarantine_reason.startswith("FILL_AFTER_RELEASE")
    assert not _decide(journal, f.entry("EXP-TEST:b", quantity="1", price="0.01", cost="0.01")).allowed
    assert journal.verify_chain().ok
    journal.close()


def test_a_cancel_reporting_fewer_fills_than_recorded_quarantines(path):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    journal.reservations.record_fill(rid, Decimal("4"), NOW, receipt_id=_ev(journal, rid, K.FILL))
    q = journal.reservations.confirm_cancel(rid, NOW, receipt_id=_ev(journal, rid, K.CANCEL_CONFIRM),
                                            venue_filled=Decimal("2"))
    assert q.state is ObligationState.UNKNOWN and q.quarantine_reason.startswith("END_FILL_SHRANK")
    journal.close()


def test_a_complete_fill_is_bound_until_a_snapshot_shows_the_position(path):
    journal, token = _open(path)
    rid = _acked(journal, f.entry(), token)
    full = journal.reservations.record_fill(rid, Decimal("10"), NOW, receipt_id=_ev(journal, rid, K.FILL))
    assert full.state is ObligationState.BOUND and full.end_reason is EndReason.FILLED
    with pytest.raises(InvalidTransition):
        journal.reservations.mark_open(rid, NOW, receipt_id=_ev(journal, rid, K.ORDER_LOOKUP))
    later = NOW + timedelta(seconds=1)
    f.snapshot(journal, 2, at=later, positions={(f.MARKET, YES): Decimal("10")})
    assert journal.reservations.confirm_by_snapshot(rid, 2, later).release_reason is ReleaseReason.CONVERTED_TO_POSITION
    journal.close()


def test_a_rejected_attempt_cannot_have_fills(path):
    journal, token = _open(path)
    a = f.prepare(journal, f.entry(), token)
    journal.mark_sent(a.attempt_id, now=NOW)
    journal.reservations.record_fill(a.reservation_id, Decimal("1"), NOW, receipt_id=_ev(journal, a.reservation_id,
                                                                                         K.FILL))
    with pytest.raises(InvalidTransition, match="has fills"):
        journal.mark_rejected(a.attempt_id, receipt_id=_ev(journal, a.attempt_id, K.ORDER_REJECT), now=NOW)
    assert journal.attempt(a.attempt_id).state is AttemptState.SENT  # the whole transaction rolled back
    journal.close()


def test_reservations_survive_a_database_reopen(path):
    journal, token = _open(path, cash="5")
    rid = _acked(journal, f.entry("EXP-TEST:a", quantity="10", price="0.40", cost="4.00"), token)
    journal.reservations.request_cancel(rid, NOW)
    journal.close()
    with ExecutionJournal.open(path) as reopened:
        r = reopened.reservations.reservation(rid)
        assert r.state is ObligationState.CANCEL_REQUESTED and r.cash_worst_case == Decimal("4")
        assert [x.reservation_id for x in reopened.reservations.held_reservations(f.SCOPE)] == [rid]
        with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
            f.prepare(reopened, f.entry("EXP-TEST:b", quantity="10", price="0.40", cost="4.00"), token)
        assert reopened.verify_chain().ok


# ---------------------------------------------------------------- fencing


def test_fence_tokens_strictly_increase_and_a_live_lease_is_exclusive(path):
    with ExecutionJournal.open(path) as journal:
        rv = journal.reservations
        t1 = rv.acquire_lease("w1", f.TTL, NOW)
        with pytest.raises(LeaseHeld):
            rv.acquire_lease("w2", f.TTL, NOW + timedelta(minutes=1))
        t2 = rv.acquire_lease("w1", f.TTL, NOW + timedelta(minutes=1))  # re-acquiring is a new fence
        t3 = rv.acquire_lease("w2", f.TTL, NOW + f.TTL + timedelta(minutes=2))  # after expiry: takeover
        assert t1 < t2 < t3
        with pytest.raises(StaleFence):
            rv.renew_lease("w1", t2, f.TTL, NOW)
        rv.renew_lease("w2", t3, f.TTL, NOW + f.TTL + timedelta(minutes=5))
        assert rv.lease().fence_token == t3 and rv.lease().worker_id == "w2"
        assert journal.verify_chain().ok
    with ExecutionJournal.open(path) as reopened:  # the counter survives a restart
        assert reopened.reservations.acquire_lease("w3", f.TTL, NOW + timedelta(days=1)) == t3 + 1


def test_a_stale_or_expired_fence_is_refused_before_anything_commits(path):
    journal, token = _open(path)
    before = f.counts(path)
    with pytest.raises(StaleFence):
        f.prepare(journal, f.entry(), token + 1)
    with pytest.raises(StaleFence, match="expired"):
        f.prepare(journal, f.entry(), token, at=NOW + f.TTL)
    with pytest.raises(StaleFence):
        f.prepare(journal, f.entry(), True)  # a bool is not a token
    assert f.counts(path) == before
    journal.close()


def test_a_paused_worker_whose_lease_was_taken_over_cannot_send_and_its_attempt_stays_reserved(path):
    journal_a, token_a = _open(path, cash="5")
    a = f.prepare(journal_a, f.entry("EXP-TEST:a", quantity="10", price="0.40", cost="4.00"), token_a)
    # Worker A pauses (a GC pause, a suspended laptop). Its lease expires and worker B takes over.
    later = NOW + f.TTL + timedelta(seconds=1)
    journal_b = ExecutionJournal.open(path)
    f.snapshot(journal_b, 2, cash="5", at=later)
    token_b = journal_b.reservations.acquire_lease("worker-b", f.TTL, later)
    assert token_b > token_a
    taken = journal_b.attempt(a.attempt_id)
    assert taken.state is AttemptState.OUTCOME_UNKNOWN and "FENCE_SUPERSEDED" in taken.state_reason
    assert journal_b.reservations.reservation(a.reservation_id).state is ObligationState.UNKNOWN  # still held
    # A resumes. Its next prepare is refused before anything commits, and it cannot claim it sent.
    before = f.counts(path)
    with pytest.raises(StaleFence):
        f.prepare(journal_a, f.entry("EXP-TEST:a2", quantity="1", price="0.40", cost="0.40"), token_a, at=later)
    assert f.counts(path) == before
    with pytest.raises(InvalidTransition):
        journal_a.mark_sent(a.attempt_id, now=later)
    # B may not resubmit A's intent blind, and A's reservation still consumes the cash.
    with pytest.raises(AttemptRefused, match="OUTCOME_UNKNOWN"):
        f.prepare(journal_b, f.entry("EXP-TEST:a", quantity="10", price="0.40", cost="4.00"), token_b,
                  nonce="n-b", at=later)
    with pytest.raises(ReservationRefused, match="INSUFFICIENT_CASH"):
        f.prepare(journal_b, f.entry("EXP-TEST:b", quantity="10", price="0.40", cost="4.00"), token_b, at=later)
    journal_a.close()
    journal_b.close()


# ---------------------------------------------------------------- separate processes racing (spawn)


def _race(path: Path, jobs: list[tuple[str, str, str]], token: int) -> dict[str, str]:
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(len(jobs))
    results = ctx.Queue()
    procs = [ctx.Process(target=f.race_worker, args=(str(path), kind, key, qty, token, barrier, results))
             for kind, key, qty in jobs]
    for p in procs:
        p.start()
    out = {}
    try:
        for _ in jobs:
            key, outcome = results.get(timeout=120)
            out[key] = outcome
    except queue.Empty:  # pragma: no cover - a hung racer is a failure, not a hang
        pytest.fail(f"racers did not report: {out}")
    finally:
        for p in procs:
            p.join(timeout=60)
    return out


def test_two_processes_racing_for_the_last_cash_exactly_one_wins(path):
    journal, token = _open(path, cash="5", busy_timeout_ms=20000)
    journal.close()
    out = _race(path, [("entry", "EXP-RACE:a", "10"), ("entry", "EXP-RACE:b", "10")], token)  # 5.00 each
    won = [k for k, v in out.items() if v == "WON"]
    assert len(won) == 1, out
    loser, = set(out) - set(won)
    assert "INSUFFICIENT_CASH" in out[loser], out
    with ExecutionJournal.open(path) as journal:
        held = journal.reservations.held_reservations(f.SCOPE)
        assert [r.intent_key for r in held] == won and sum(r.cash_worst_case for r in held) == Decimal("5")
        assert f.counts(path)["attempts"] == 1 and journal.verify_chain().ok


def test_two_processes_racing_for_the_last_inventory_exactly_one_wins(path):
    journal, token = _open(path, cash="5", positions={(f.MARKET, YES): Decimal("7")}, busy_timeout_ms=20000)
    journal.close()
    out = _race(path, [("reduction", "EXP-RACE:x", "7"), ("reduction", "EXP-RACE:y", "7")], token)
    won = [k for k, v in out.items() if v == "WON"]
    assert len(won) == 1, out
    loser, = set(out) - set(won)
    assert "INSUFFICIENT_INVENTORY" in out[loser], out
    with ExecutionJournal.open(path) as journal:
        assert [r.intent_key for r in journal.reservations.held_reservations(f.SCOPE)] == won


def test_two_processes_racing_for_the_lease_exactly_one_gets_it(path):
    ExecutionJournal.open(path).close()
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=f.lease_worker, args=(str(path), w, barrier, results)) for w in ("w1", "w2")]
    for p in procs:
        p.start()
    out = dict(results.get(timeout=120) for _ in procs)
    for p in procs:
        p.join(timeout=60)
    assert sorted(out.values()) == ["REFUSED:LeaseHeld", "TOKEN:1"], out


def test_a_held_write_lock_from_another_connection_does_not_corrupt_a_reservation(path):
    journal, token = _open(path, busy_timeout_ms=50)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(JournalUnavailable):
            f.prepare(journal, f.entry(), token)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert f.counts(path)["reservations"] == 0
    journal.close()
