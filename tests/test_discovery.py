"""Broad discovery classification: no fabricated probabilities, no title equivalence, honest coverage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import discovery as d, polymarket_us as pm
from edge_lab.conservative import ProbabilityBounds
from edge_lab.discovery import CatalogCoverage, Candidate, CoverageState, DiscoveryStatus as S
from edge_lab.opportunity import Event, Market, MarketStatus, MarketTiming, ModelEstimate, Payoff

UTC = timezone.utc
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "polymarket_us"


def event(eid: str, identity: str, domain: str = "weather") -> Event:
    return Event(domain=domain, event_id=eid, target_date="2026-09-24", target_time_utc=None, outcome_cluster=eid,
                 settlement_identity=identity)


def market(venue: str, native: str, eid: str, *, resolved: bool = True, timing: MarketTiming | None = None) -> Market:
    return Market(venue=venue, market_id=f"{venue}:{native}", native_id=native, event_id=eid, outcome="75-76",
                  payoff=Payoff("binary", Decimal(1), "value in [75, 76]"), rules_sha256="ab" * 32,
                  status=MarketStatus.OPEN, rules_resolved=resolved, rules_detail="rules detail", timing=timing)


def cov(venue: str, state: CoverageState = CoverageState.COMPLETE, as_of: str | None = "2026-09-23T14:00:00+00:00"):
    return CatalogCoverage(venue, f"https://{venue}.test/markets", state, 3, 250, as_of, "test coverage")


def estimate_for(m: Market, eid: str, p: float | None = 0.4) -> ModelEstimate:
    return ModelEstimate("EXP-001/V1", "v", eid, m.market_id, p,
                         None if p is None else ProbabilityBounds(p, max(p - 0.05, 0), min(p + 0.05, 1),
                                                                  "test", 100, 0.9, 0.02),
                         NOW.isoformat(), "in", NOW.isoformat())


KALSHI_EVENT = event("weather:nyc:2026-09-24", "kalshi:KXHIGHNY:CLINYC max temp")
KALSHI = market("kalshi", "KXHIGHNY-26SEP24-B75.5", KALSHI_EVENT.event_id)


def test_no_model_means_model_unsupported_and_no_probability():
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[cov("kalshi")], candidates=[], now=NOW)
    assert S.MODEL_UNSUPPORTED.value in rec.statuses and S.CATALOG_ONLY.value in rec.statuses
    assert rec.probability is None and rec.model_id is None
    assert S.EXECUTION_DISABLED.value in rec.statuses and rec.execution_authorized is False
    unavailable = estimate_for(KALSHI, KALSHI_EVENT.event_id, None)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=unavailable, coverage=[], candidates=[], now=NOW)
    assert rec.probability is None and S.MODEL_UNSUPPORTED.value in rec.statuses


def test_a_model_estimate_is_passed_through_not_invented():
    est = estimate_for(KALSHI, KALSHI_EVENT.event_id, 0.4)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=est, coverage=[cov("kalshi")], candidates=[], now=NOW,
                     has_quote=True)
    assert rec.probability == 0.4 and rec.model_id == "EXP-001/V1"
    assert S.MODEL_UNSUPPORTED.value not in rec.statuses and S.CATALOG_ONLY.value not in rec.statuses
    other = market("kalshi", "OTHER", KALSHI_EVENT.event_id)
    rec = d.classify(other, event=KALSHI_EVENT, estimate=est, coverage=[], candidates=[], now=NOW)
    assert rec.probability is None  # an estimate for a different market is ignored


def test_title_match_alone_is_at_most_related():
    pm_event = event("polymarket_us:nyc-high-sep-24", "polymarket_us:unverified:nyc-high-sep-24:NWS")
    same_title = market("polymarket_us", "nyc-high-75-76", pm_event.event_id, resolved=False)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[cov("kalshi"), cov("polymarket_us")],
                     candidates=[Candidate(pm_event, same_title)], now=NOW)
    assert rec.related == ("polymarket_us:nyc-high-75-76",) and rec.equivalents == ()
    assert S.RELATED_NOT_EQUIVALENT.value in rec.statuses and S.MATCHED_EQUIVALENT.value not in rec.statuses
    assert S.UNIQUE_WITHIN_VERIFIED_COVERAGE.value not in rec.statuses


def test_matched_equivalent_needs_equal_settlement_identity_and_resolved_rules_on_both_sides():
    twin_event = event("venue_b:nyc", KALSHI_EVENT.settlement_identity)
    twin = market("venue_b", "nyc-75", twin_event.event_id)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[Candidate(twin_event, twin)],
                     now=NOW)
    assert rec.equivalents == ("venue_b:nyc-75",) and S.MATCHED_EQUIVALENT.value in rec.statuses
    unresolved = market("venue_b", "nyc-75", twin_event.event_id, resolved=False)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[],
                     candidates=[Candidate(twin_event, unresolved)], now=NOW)
    assert rec.equivalents == () and S.RELATED_NOT_EQUIVALENT.value in rec.statuses
    rec = d.classify(KALSHI, event=None, estimate=None, coverage=[], candidates=[Candidate(twin_event, twin)], now=NOW)
    assert rec.equivalents == ()  # without its own event, equivalence cannot be shown


def test_unique_only_within_complete_coverage_and_names_venues_and_time():
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None,
                     coverage=[cov("kalshi"), cov("polymarket_us", as_of="2026-09-23T13:00:00Z")],
                     candidates=[], now=NOW)
    assert S.UNIQUE_WITHIN_VERIFIED_COVERAGE.value in rec.statuses
    assert rec.coverage_venues == ("kalshi", "polymarket_us")
    assert rec.coverage_as_of_utc == "2026-09-23T13:00:00+00:00"
    for coverage in ([cov("kalshi"), cov("polymarket_us", CoverageState.PARTIAL)],
                     [cov("kalshi"), cov("polymarket_us", CoverageState.FAILED)],
                     [cov("kalshi", as_of=None)], []):
        rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=coverage, candidates=[], now=NOW)
        assert S.UNIQUE_WITHIN_VERIFIED_COVERAGE.value not in rec.statuses, coverage
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None,
                     coverage=[cov("polymarket_us", CoverageState.FAILED)], candidates=[], now=NOW)
    assert {S.SOURCE_COVERAGE_UNKNOWN.value, S.DATA_PARTIAL.value} <= set(rec.statuses)
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now=NOW)
    assert S.SOURCE_COVERAGE_UNKNOWN.value in rec.statuses


def test_new_venue_markets_fail_the_starter_policy_closed():
    raw = json.loads((FIXTURES / "events_schema_constructed.json").read_text())["events"][0]
    pm_event, mapping = pm.event_from_polymarket(raw)
    pm_market, _ = pm.market_from_polymarket(raw["markets"][0], event_id_for_market=mapping)
    rec = d.classify(pm_market, event=pm_event, estimate=None, coverage=[], candidates=[], now=NOW)
    assert rec.starter["eligible"] is False
    assert {"SETTLEMENT_TIMING_UNVERIFIED", "TRADABLE_CASH_RELEASE_UNKNOWN"} <= set(rec.starter["reasons"])
    assert "DELAYED_OR_DISPUTED" not in rec.starter["reasons"]  # "open" is read as open
    assert S.RULES_UNRESOLVED.value in rec.statuses and rec.probability is None


def test_kalshi_series_uses_its_registered_lag_evidence():
    timing = MarketTiming(expected_resolution_utc=(NOW + timedelta(hours=30)).isoformat(),
                          settlement_timer_seconds=300, lifecycle_status="active")
    m = market("kalshi", "KXHIGHNY-26SEP24-B75.5", KALSHI_EVENT.event_id, timing=timing)
    rec = d.classify(m, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now=NOW)
    assert rec.starter["eligible"] is True and rec.starter["policy_id"] == "STARTER_MAX_7D_V1"


def test_lifecycle_statuses_are_asserted_only_where_allowed():
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now=NOW,
                     lifecycle=[S.RESEARCHING, S.MANUAL_ONLY])
    assert {S.RESEARCHING.value, S.MANUAL_ONLY.value} <= set(rec.statuses)
    with pytest.raises(ValueError):
        d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now=NOW,
                   lifecycle=[S.VALIDATED_FOR_SCOPE])
    with pytest.raises(ValueError):
        d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now=NOW,
                   lifecycle=[S.MATCHED_EQUIVALENT])
    with pytest.raises(ValueError):
        d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[], candidates=[], now="2026-09-23T15:00:00")


def test_domain_inventory_covers_the_owner_targets_and_only_weather_has_a_model():
    domains = [t.domain for t in d.DOMAIN_INVENTORY]
    assert domains == ["weather", "nfl", "college_football", "nba", "wnba", "college_basketball", "nhl", "mlb",
                       "ufc_mma", "boxing", "soccer", "tennis", "golf", "motorsports", "cricket", "rugby", "esports",
                       "politics", "economic_releases", "other"]
    support = {t.domain: t.model_support for t in d.DOMAIN_INVENTORY}
    assert support.pop("weather") == "WEATHER_EXP001_ONLY"
    assert set(support.values()) == {"MODEL_UNSUPPORTED"}
    assert d.domain_target("NFL").domain == "nfl" and d.domain_target("curling").domain == "other"
    assert len(d.DiscoveryStatus) == 13


def test_record_serializes():
    rec = d.classify(KALSHI, event=KALSHI_EVENT, estimate=None, coverage=[cov("kalshi")], candidates=[], now=NOW)
    assert json.loads(json.dumps(rec.to_dict()))["market_id"] == "kalshi:KXHIGHNY-26SEP24-B75.5"
