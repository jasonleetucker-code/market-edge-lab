"""Venue capability registry (ADR 0019) and the execution-ticket contract (data only)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import starter_policy as sp, venues
from edge_lab.execution_ticket import ActionMode, ExecutionTicket, TicketStatus, draft_ticket
from edge_lab.opportunity import MarketTiming
from edge_lab.venues import Capability, ConnectivityStage, VenueKind, VenueSpec

UTC = timezone.utc


def test_execution_is_authorized_for_no_venue_and_cannot_be_constructed():
    assert all(v.execution_authorized is False for v in venues.VENUES.values())
    with pytest.raises(ValueError):
        replace(venues.KALSHI, execution_authorized=True)


def test_order_write_is_never_beyond_needs_access():
    for v in venues.VENUES.values():
        assert v.stage(Capability.ORDER_WRITE) in (ConnectivityStage.PLANNED, ConnectivityStage.NEEDS_ACCESS,
                                                  ConnectivityStage.UNSUPPORTED), v.venue_id


def test_every_capability_is_stated_and_the_registry_is_immutable():
    for v in venues.VENUES.values():
        assert set(v.capabilities) == set(Capability)
    with pytest.raises(TypeError):
        venues.KALSHI.capabilities[Capability.ORDER_WRITE] = None
    with pytest.raises(ValueError):
        VenueSpec("x", VenueKind.EXCHANGE, "x", "x", {Capability.CATALOG_READ: venues.KALSHI.capabilities[
            Capability.CATALOG_READ]}, None, None, "")


def test_only_recorded_reads_are_live_data_verified():
    live = {(v.venue_id, c.value) for v in venues.VENUES.values() for c in Capability
            if v.stage(c) is ConnectivityStage.LIVE_DATA_VERIFIED}
    assert {venue for venue, _ in live} == {"kalshi"}
    assert ("kalshi", "account_read") not in live and ("kalshi", "order_write") not in live


def test_polymarket_us_and_international_are_distinct_and_international_is_unsupported():
    us, intl = venues.get_venue("polymarket_us"), venues.get_venue("polymarket_international")
    assert us.liquidity_pool_id != intl.liquidity_pool_id
    assert all(intl.stage(c) is ConnectivityStage.UNSUPPORTED for c in Capability)


def test_the_odds_api_is_an_aggregator_not_a_venue_you_trade_on():
    odds = venues.get_venue("the_odds_api")
    assert odds.kind is VenueKind.AGGREGATOR
    assert odds.stage(Capability.ORDER_WRITE) is ConnectivityStage.UNSUPPORTED
    assert odds.stage(Capability.DEPTH_READ) is ConnectivityStage.UNSUPPORTED


def test_coverage_rows_list_every_venue_capability():
    rows = venues.coverage_rows()
    assert len(rows) == len(venues.VENUES) * len(Capability)
    assert not any(r["execution_authorized"] for r in rows)


# ---------------------------------------------------------------- tickets

def _opportunity(**kw):
    from test_opportunity import run
    return run(**kw)


def _eligible_verdict(at: datetime):
    lag = sp.lag_evidence("kalshi", "KXHIGHNY")
    expected = at + timedelta(hours=40)
    return sp.assess(commitment=at, timing=MarketTiming(expected_resolution_utc=expected.isoformat(),
                                                        settlement_timer_seconds=300, lifecycle_status="active"),
                     lag=lag, cash=venues.cash_timing("kalshi"))


def test_ticket_can_never_be_marked_executable():
    opp = _opportunity()
    at = datetime.fromisoformat(opp.as_of_utc)
    ticket = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at),
                          action_mode=ActionMode.SIMULATION, now=at, ttl=timedelta(minutes=2),
                          max_quote_age=timedelta(minutes=5))
    assert ticket.execution_enabled is False and ticket.status is TicketStatus.DRAFT, ticket.reasons
    with pytest.raises(ValueError):
        replace(ticket, execution_enabled=True)
    d = ticket.to_dict()
    assert d["starter_policy"]["eligible"] and d["max_total_cost"] == str(opp.all_in_cost * opp.quantity)


@pytest.mark.parametrize("mode", [ActionMode.APP_APPROVAL_API, ActionMode.BOUNDED_AUTO_API])
def test_api_action_modes_are_refused(mode):
    opp = _opportunity()
    at = datetime.fromisoformat(opp.as_of_utc)
    ticket = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at), action_mode=mode,
                          now=at, ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    assert ticket.status is TicketStatus.REJECTED and any("NOT_AUTHORIZED" in r for r in ticket.reasons)


def test_stale_quote_expires_and_ineligible_starter_rejects():
    opp = _opportunity()
    at = datetime.fromisoformat(opp.as_of_utc)
    stale = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at),
                         action_mode=ActionMode.ALERT_AND_DEEPLINK, now=at + timedelta(minutes=30),
                         ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    assert stale.status is TicketStatus.EXPIRED
    long = sp.assess(commitment=at, timing=None, lag=None, cash=None)
    rejected = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=long, action_mode=ActionMode.SIMULATION,
                            now=at, ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    assert rejected.status is TicketStatus.REJECTED and any("STARTER_POLICY_INELIGIBLE" in r for r in rejected.reasons)


def test_ticket_id_is_deterministic_and_venue_mismatch_rejects():
    opp = _opportunity()
    at = datetime.fromisoformat(opp.as_of_utc)
    kw = dict(route_id=None, verdict=_eligible_verdict(at), action_mode=ActionMode.SIMULATION, now=at,
              ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    assert draft_ticket(opp, venue=venues.KALSHI, **kw).ticket_id == draft_ticket(opp, venue=venues.KALSHI, **kw).ticket_id
    other = draft_ticket(opp, venue=venues.POLYMARKET_US, **kw)
    assert other.status is TicketStatus.REJECTED and any("VENUE_MISMATCH" in r for r in other.reasons)


def test_stale_verdict_and_future_quote_are_refused():
    opp = _opportunity()
    at = datetime.fromisoformat(opp.as_of_utc)
    old_verdict = _eligible_verdict(at - timedelta(hours=6))
    t = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=old_verdict, action_mode=ActionMode.SIMULATION,
                     now=at, ttl=timedelta(minutes=2), max_quote_age=timedelta(minutes=5))
    assert t.status is TicketStatus.REJECTED and any("STARTER_VERDICT_NOT_CURRENT" in r for r in t.reasons)
    early = draft_ticket(opp, venue=venues.KALSHI, route_id=None, verdict=_eligible_verdict(at - timedelta(minutes=5)),
                         action_mode=ActionMode.SIMULATION, now=at - timedelta(minutes=5), ttl=timedelta(minutes=2),
                         max_quote_age=timedelta(minutes=5))
    assert early.status is TicketStatus.EXPIRED  # the quote is dated after the ticket: not current
