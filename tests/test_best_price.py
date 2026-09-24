"""One best-price-for-size comparator and its honest claim ladder (ADR 0027, issue #30).

The Kalshi / Polymarket US pairs here are constructed. No cross-venue market has been shown
rule-equivalent yet (Polymarket US `rules_resolved` is always False), so an "equivalent" pair
is built with `dataclasses.replace` to exercise the claims. Real adapters feed the same objects.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from edge_lab import best_price as bp
from edge_lab import venues
from edge_lab.best_price import ClaimKind, PositionRequest, Route
from edge_lab.fee_schedules import (
    POLYMARKET_US_EXCHANGE_SCOPE, CostModel, FeeScheduleStatus, QuadraticTakerSchedule, schedule_for,
)
from edge_lab.opportunity import (
    DepthLadder, DepthLevel, Event, Market, MarketStatus, MarketTiming, Payoff, PriceGrid, PriceRange,
)

D = Decimal
AS_OF = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
FRESH = "2026-09-24T11:59:30+00:00"
STALE = "2026-09-24T11:40:00+00:00"
MAX_AGE = timedelta(minutes=5)
SETTLES_ON = "nws:CLINYC:2026-09-25:max_temp_f"

K_EVENT = Event("weather", "kalshi:KXHIGHNY-26SEP25", "2026-09-25", None, "nyc-high-2026-09-25", SETTLES_ON)
P_EVENT = Event("weather", "polymarket_us:nyc-high-2026-09-25", "2026-09-25", None, "nyc-high-2026-09-25",
                SETTLES_ON)
PAYOFF = Payoff("binary", D(1), "value in [69, 70]")
K_MARKET = Market(
    venue="kalshi", market_id="kalshi:KXHIGHNY-26SEP25-B69.5", native_id="KXHIGHNY-26SEP25-B69.5",
    event_id=K_EVENT.event_id, outcome="69-70", payoff=PAYOFF, rules_sha256="ab" * 32, status=MarketStatus.OPEN,
    rules_resolved=True, rules_detail="ok",
    timing=MarketTiming(expected_resolution_utc="2026-09-26T14:00:00+00:00", settlement_timer_seconds=3600,
                        lifecycle_status="active"),
    price_grid=PriceGrid((PriceRange(D(0), D(1), D("0.01")),), source="kalshi price_ranges (test)"),
)
P_MARKET = replace(
    K_MARKET, venue="polymarket_us", market_id="polymarket_us:nyc-high-69-70", native_id="nyc-high-69-70",
    event_id=P_EVENT.event_id, rules_sha256="cd" * 32, timing=MarketTiming(lifecycle_status="open"),
    price_grid=PriceGrid((PriceRange(D(0), D(1), D("0.001")),), source="polymarket_us orderPriceMinTickSize"),
)
KALSHI_FEES = schedule_for("kalshi", "KXHIGHNY")
PM_FEES = schedule_for("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE)
PM_NO_FEES = schedule_for("polymarket_us", "feeCoefficient:0.08")


def ladder(market: Market, *levels, side="YES", truncated=False, received=FRESH, anomaly=None) -> DepthLadder:
    return DepthLadder(market.venue, market.market_id, side, tuple(DepthLevel(D(p), D(s)) for p, s in levels),
                       truncated, received, None, f"snap:{market.venue}", anomaly)


def k_route(*levels, **kw) -> Route:
    return Route(K_EVENT, K_MARKET, ladder(K_MARKET, *levels, **kw) if levels or kw else None, KALSHI_FEES)


def p_route(*levels, fees=PM_FEES, market=P_MARKET, **kw) -> Route:
    return Route(P_EVENT, market, ladder(market, *levels, **kw), fees)


REQUEST = PositionRequest(K_EVENT, K_MARKET, "YES", 10)


def run(*routes, request=REQUEST, as_of=AS_OF):
    return bp.compare(request, routes, as_of=as_of, max_book_age=MAX_AGE)


def claim(result, kind):
    return result.claim(kind)


# ---------------------------------------------------------------- the four claims


def test_verified_kalshi_vs_unverified_polymarket_fees():
    result = run(k_route(("0.40", "5"), ("0.41", "10")), p_route(("0.39", "20")))
    kalshi, pmus = result.routes
    assert (kalshi.venue, pmus.venue) == ("kalshi", "polymarket_us")
    assert {kalshi.equivalence, pmus.equivalence} == {"REFERENCE", "MATCHED_EQUIVALENT"}

    # Kalshi: 5 @ 0.40 + 5 @ 0.41; each take is its own taker fill (price_depth_fill).
    assert (kalshi.gross_cost, kalshi.average_price, kalshi.worst_price) == (D("4.05"), D("0.405"), D("0.41"))
    assert kalshi.fee_status == "CONSERVATIVE_BOUND" and kalshi.total_cost == D("4.23")
    assert kalshi.claim_total_cost == D("4.23") + D("0.0101") * 10  # the ADR 0017 allowance, per contract
    # Polymarket US: 10 @ 0.39; fee ceil(0.0695 x 10 x 0.39 x 0.61) = 0.17: an estimate, never a claim.
    assert (pmus.gross_cost, pmus.fee, pmus.total_cost) == (D("3.90"), D("0.17"), D("4.07"))
    assert pmus.fee_status == "UNVERIFIED" and pmus.claim_total_cost is None
    assert "FEE_UNVERIFIED" in pmus.exclusions

    observed = claim(result, ClaimKind.BEST_OBSERVED_QUOTE)
    gross = claim(result, ClaimKind.BEST_GROSS_COST_FOR_SIZE)
    verified = claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST)
    feasible = claim(result, ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE)
    assert (observed.market_id, observed.value) == (P_MARKET.market_id, D("0.39"))
    assert (gross.market_id, gross.value) == (P_MARKET.market_id, D("3.90"))
    assert (verified.market_id, verified.value) == (K_MARKET.market_id, D("4.331"))
    assert verified.candidates == (K_MARKET.market_id,)
    assert not feasible.supported and feasible.value is None and feasible.reason == "NO_ACCOUNT_CONNECTED"

    assert result.summary.splitlines()[1:6] == [
        "Kalshi (kalshi:KXHIGHNY-26SEP25-B69.5) at most $4.3310 total ($4.05 gross, fees CONSERVATIVE_BOUND)",
        "Polymarket US (polymarket_us:nyc-high-69-70) $3.90 gross, fees unverified (published-schedule estimate "
        "$0.17, not claim-grade)",
        "No cheaper-than claim: 1 of 2 route(s) have a verified total cost.",
        "No account-feasible route (NO_ACCOUNT_CONNECTED).",
        "Tradable cash release: Kalshi 2026-09-28T16:00:00+00:00; Polymarket US UNKNOWN.",
    ]
    assert "cheaper than" not in result.summary.replace("No cheaper-than claim", "")
    assert result.execution_authorized is False and all(not r.execution_authorized for r in result.routes)


def test_unsupported_polymarket_fees_are_unknown_not_zero():
    result = run(k_route(("0.40", "20")), p_route(("0.39", "20"), fees=PM_NO_FEES))
    pmus = next(r for r in result.routes if r.venue == "polymarket_us")
    assert pmus.fee_status == "UNSUPPORTED" and pmus.fee is None and pmus.total_cost is None
    assert "FEE_UNSUPPORTED" in pmus.exclusions
    assert "Polymarket US (polymarket_us:nyc-high-69-70) $3.90 gross, fees unknown" in result.summary
    assert claim(result, ClaimKind.BEST_GROSS_COST_FOR_SIZE).market_id == P_MARKET.market_id
    assert claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST).market_id == K_MARKET.market_id
    assert "cheaper than" not in result.summary.replace("No cheaper-than claim", "")


def test_cheaper_is_said_only_between_two_verified_totals():
    exact = QuadraticTakerSchedule("test-exact-pm", "polymarket_us", D("0.07"), D(1), FeeScheduleStatus.VERIFIED,
                                   "test double", "2026-09-24T00:00:00Z", cost_model=CostModel.EXACT)
    result = run(k_route(("0.40", "20")), p_route(("0.30", "20"), fees=exact))
    pmus = next(r for r in result.routes if r.venue == "polymarket_us")
    assert pmus.fee_status == "VERIFIED" and pmus.claim_total_cost == pmus.total_cost
    verified = claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST)
    assert verified.market_id == P_MARKET.market_id and len(verified.candidates) == 2
    assert ("On verified total cost, Polymarket US (polymarket_us:nyc-high-69-70) is cheaper than Kalshi "
            "(kalshi:KXHIGHNY-26SEP25-B69.5).") in result.summary


def test_equal_verified_totals_are_a_tie_not_cheaper():
    exact = QuadraticTakerSchedule("test-exact-pm", "polymarket_us", D("0.07"), D(1), FeeScheduleStatus.VERIFIED,
                                   "test double", "2026-09-24T00:00:00Z", cost_model=CostModel.EXACT)
    twin = replace(P_MARKET, market_id="polymarket_us:twin", native_id="twin")
    result = run(p_route(("0.30", "20"), fees=exact), p_route(("0.30", "20"), fees=exact, market=twin),
                 request=PositionRequest(P_EVENT, replace(P_MARKET), "YES", 10))
    assert "ties" in result.summary and "cheaper than" not in result.summary


# ---------------------------------------------------------------- depth, grid, freshness


def test_insufficient_and_unknown_depth_never_price_a_partial_fill():
    result = run(k_route(("0.40", "4")), p_route(("0.39", "6"), truncated=True))
    kalshi, pmus = result.routes
    assert kalshi.liquidity == "INSUFFICIENT_DEPTH" and kalshi.available == D(4) and kalshi.gross_cost is None
    assert pmus.liquidity == "DEPTH_UNKNOWN" and pmus.available == D(6) and pmus.gross_cost is None
    assert claim(result, ClaimKind.BEST_OBSERVED_QUOTE).market_id == P_MARKET.market_id  # a quote, not a fill
    gross = claim(result, ClaimKind.BEST_GROSS_COST_FOR_SIZE)
    assert not gross.supported and gross.reason == "DEPTH_UNKNOWN"  # the furthest gate reached
    assert "insufficient depth (4 of 10 offered)" in result.summary
    assert "depth unknown (truncated capture shows 6 of 10)" in result.summary


def test_an_off_grid_level_invalidates_the_whole_ladder():
    # 0.395 is on the universal 1/100-cent grid but off Kalshi's cent grid for this market.
    result = run(k_route(("0.395", "20")), p_route(("0.3955", "20")))
    kalshi, pmus = result.routes
    assert kalshi.liquidity == pmus.liquidity == "INVALID_BOOK"
    assert kalshi.observed_ask is None and kalshi.gross_cost is None
    assert any("off the market's price grid" in d for d in kalshi.details)
    assert not claim(result, ClaimKind.BEST_OBSERVED_QUOTE).supported
    assert claim(result, ClaimKind.BEST_OBSERVED_QUOTE).reason == "INVALID_BOOK"
    on_grid = run(k_route(("0.40", "20")), p_route(("0.395", "20")))  # 0.395 is on the 0.001 grid
    assert all(r.liquidity == "FILLABLE" for r in on_grid.routes)


def test_a_ladder_for_another_market_or_side_is_invalid():
    wrong = Route(K_EVENT, K_MARKET, ladder(K_MARKET, ("0.40", "20"), side="NO"), KALSHI_FEES)
    (r,) = run(wrong).routes
    assert r.liquidity == "INVALID_BOOK" and "INVALID_BOOK" in r.exclusions


def test_missing_book_is_reported_not_priced():
    (r,) = run(Route(K_EVENT, K_MARKET, None, KALSHI_FEES)).routes
    assert r.liquidity == "BOOK_MISSING" and r.freshness == "unknown"
    assert "no captured book" in run(Route(K_EVENT, K_MARKET, None, KALSHI_FEES)).summary


def test_a_stale_route_is_excluded_from_the_verified_claims_only():
    result = run(k_route(("0.40", "20"), received=STALE))
    (kalshi,) = result.routes
    assert kalshi.freshness == "stale" and "NOT_FRESH" in kalshi.exclusions
    assert claim(result, ClaimKind.BEST_OBSERVED_QUOTE).supported
    assert claim(result, ClaimKind.BEST_GROSS_COST_FOR_SIZE).supported
    verified = claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST)
    assert not verified.supported and verified.reason == "NOT_FRESH"
    assert "total not claimed; book stale" in result.summary


def test_a_book_timestamped_after_as_of_is_unknown_and_fails_closed():
    result = run(k_route(("0.40", "20"), received="2026-09-24T12:30:00+00:00"))
    assert result.routes[0].freshness == "unknown"
    assert not claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST).supported


# ---------------------------------------------------------------- equivalence


def test_a_non_equivalent_market_is_related_only_even_when_cheaper():
    unresolved = replace(P_MARKET, rules_resolved=False)  # the real Polymarket US state today
    result = run(k_route(("0.40", "20")), p_route(("0.01", "1000"), market=unresolved))
    assert [r.market_id for r in result.routes] == [K_MARKET.market_id]
    assert result.related == (P_MARKET.market_id,)
    for c in result.claims:
        assert c.market_id != P_MARKET.market_id and P_MARKET.market_id not in c.candidates
    assert "Related, not equivalent (never compared): polymarket_us:nyc-high-69-70." in result.summary
    assert "$0.01" not in result.summary


def test_title_similarity_never_counts():
    other_source = replace(P_EVENT, settlement_identity="nws:CLINYC:2026-09-25:max_temp_f:polymarket-wording")
    result = run(k_route(("0.40", "20")), Route(other_source, P_MARKET, ladder(P_MARKET, ("0.30", "20")), PM_FEES))
    assert result.related == (P_MARKET.market_id,) and len(result.routes) == 1


def test_no_equivalent_route_at_all():
    result = run(p_route(("0.30", "20"), market=replace(P_MARKET, rules_resolved=False)))
    assert result.routes == () and all(c.reason == "NO_EQUIVALENT_ROUTE" for c in result.claims)
    assert "No equivalent route." in result.summary


# ---------------------------------------------------------------- split-cancel refusal


SPLIT = Payoff("binary_split_on_cancel", D(1), "long side per rules; rules text states a 50-50 settlement")


def test_a_split_cancel_route_is_refused_and_never_priced():
    split_market = replace(P_MARKET, payoff=SPLIT)
    split_request = PositionRequest(P_EVENT, split_market, "YES", 10)
    result = run(Route(P_EVENT, split_market, ladder(split_market, ("0.30", "20")), PM_FEES), request=split_request)
    (r,) = result.routes
    assert r.exclusions[0] == "PAYOFF_UNSUPPORTED" and r.liquidity is None
    assert r.gross_cost is None and r.observed_ask is None and r.fee is None
    assert all(not c.supported and c.reason == "PAYOFF_UNSUPPORTED" for c in result.claims)
    assert "payoff binary_split_on_cancel is not supported; not priced" in result.summary
    assert "Refused:" in result.summary


def test_a_split_cancel_market_never_matches_a_binary_request():
    split_market = replace(P_MARKET, payoff=SPLIT)
    result = run(k_route(("0.40", "20")), Route(P_EVENT, split_market, ladder(split_market, ("0.3", "20")), PM_FEES))
    assert result.related == (P_MARKET.market_id,)  # payoff kind differs: not equivalent


def test_real_polymarket_adapter_objects_are_related_or_refused_today():
    """Through the real adapter: the documented book and the constructed event fixture. The
    50-50 market is refused; a binary variant is RELATED to a Kalshi request (rules unresolved)."""
    from pathlib import Path

    from edge_lab import polymarket_us as pm

    fixtures = Path(__file__).parent / "fixtures" / "polymarket_us"
    (raw_event,) = pm.parse_events_page(json.loads((fixtures / "events_schema_constructed.json").read_text("utf-8")))
    book = json.loads((fixtures / "book_documented_example.json").read_text("utf-8"))
    event, mapping = pm.event_from_polymarket(raw_event)
    split, meta = pm.market_from_polymarket(raw_event["markets"][0], event_id_for_market=mapping)
    ladders = pm.ladders_from_book("will-team-a-win", book, received_at_utc=FRESH, evidence_id="book:1")
    fees = schedule_for("polymarket_us", pm.fee_scope(meta))
    result = run(Route(event, split, ladders["YES"], fees), request=PositionRequest(event, split, "YES", 10))
    assert result.routes[0].exclusions[0] == "PAYOFF_UNSUPPORTED" and result.routes[0].gross_cost is None
    assert all(c.reason == "PAYOFF_UNSUPPORTED" for c in result.claims)

    binary_raw = dict(raw_event["markets"][0], category="weather", description="Resolves Yes if the high is 70F.")
    binary, _ = pm.market_from_polymarket(binary_raw, event_id_for_market=mapping)
    assert binary.payoff.kind == "binary" and not binary.rules_resolved
    result = run(k_route(("0.60", "20")), Route(event, binary, ladders["YES"], fees))
    assert result.related == (binary.market_id,) and [r.venue for r in result.routes] == ["kalshi"]
    # Alone as its own reference it is priced, with a truncated (DEPTH_UNKNOWN-safe) ladder and an estimate fee.
    alone = run(Route(event, binary, ladders["YES"], fees), request=PositionRequest(event, binary, "YES", 10))
    (r,) = alone.routes
    assert r.liquidity == "FILLABLE" and r.gross_cost == D("5.60") and r.fee_status == "UNVERIFIED"
    assert r.fee == D("0.18") and r.capital_release_eta_utc is None


# ---------------------------------------------------------------- account feasibility


def test_account_feasible_needs_a_recorded_account_read_and_starter_eligibility(monkeypatch):
    spec = venues.KALSHI
    caps = dict(spec.capabilities)
    caps[venues.Capability.ACCOUNT_READ] = venues.CapabilityState(venues.ConnectivityStage.LIVE_DATA_VERIFIED, True,
                                                                  "test double")
    monkeypatch.setattr(venues, "VENUES", {**venues.VENUES, "kalshi": replace(spec, capabilities=caps)})
    result = run(k_route(("0.40", "20")), p_route(("0.39", "20")))
    feasible = claim(result, ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE)
    kalshi = next(r for r in result.routes if r.venue == "kalshi")
    assert kalshi.account_connected and kalshi.capital_release_eligible
    assert feasible.supported and feasible.market_id == K_MARKET.market_id
    assert feasible.value == claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST).value
    far = replace(K_MARKET, timing=replace(K_MARKET.timing, expected_resolution_utc="2026-10-10T14:00:00+00:00"))
    result = run(Route(K_EVENT, far, ladder(far, ("0.40", "20")), KALSHI_FEES),
                 request=PositionRequest(K_EVENT, far, "YES", 10))
    feasible = claim(result, ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE)
    assert not feasible.supported and feasible.reason == "CAPITAL_RELEASE_INELIGIBLE"


def test_no_venue_has_a_connected_account_today():
    for spec in venues.VENUES.values():
        assert spec.stage(venues.Capability.ACCOUNT_READ) is not venues.ConnectivityStage.LIVE_DATA_VERIFIED


def test_cheaper_never_appears_without_verified_totals_on_both_sides():
    import random
    rng = random.Random(30)
    exact = QuadraticTakerSchedule("test-exact-pm", "polymarket_us", D("0.07"), D(1), FeeScheduleStatus.VERIFIED,
                                   "test double", "2026-09-24T00:00:00Z", cost_model=CostModel.EXACT)
    for _ in range(300):
        routes = []
        for maker, fees_choices in ((k_route, [KALSHI_FEES]), (p_route, [PM_FEES, PM_NO_FEES, exact])):
            price = f"0.{rng.randint(10, 90)}"
            kw = dict(received=rng.choice([FRESH, STALE]), truncated=rng.random() < 0.3)
            size = str(rng.choice([5, 10, 50]))
            if maker is p_route:
                kw["fees"] = rng.choice(fees_choices)
            routes.append(maker((price, size), **kw))
        result = run(*routes)
        verified = claim(result, ClaimKind.BEST_VERIFIED_TOTAL_COST).candidates
        if len(verified) < 2:
            assert "is cheaper than" not in result.summary and " ties " not in result.summary
        for r in result.routes:
            if r.claim_total_cost is None or r.freshness != "fresh":
                assert f"{r.market_id}) at most" not in result.summary


# ---------------------------------------------------------------- determinism and shape


def test_result_is_deterministic_and_independent_of_route_order():
    routes = [k_route(("0.40", "5"), ("0.41", "10")), p_route(("0.39", "20")),
              p_route(("0.2", "5"), market=replace(P_MARKET, market_id="polymarket_us:other", rules_resolved=False))]
    a = run(*routes)
    b = run(*reversed(routes))
    assert a == b
    assert json.loads(json.dumps(a.to_dict())) == a.to_dict()
    assert a.to_dict()["claims"][2]["value"] == "4.3310"


@pytest.mark.parametrize("side,qty", [("MAYBE", 1), ("YES", 0), ("YES", -1), ("YES", True), ("YES", D("NaN"))])
def test_bad_requests_raise(side, qty):
    with pytest.raises(ValueError):
        PositionRequest(K_EVENT, K_MARKET, side, qty)


def test_as_of_must_be_aware():
    with pytest.raises(ValueError):
        bp.compare(REQUEST, [], as_of=datetime(2026, 9, 24, 12), max_book_age=MAX_AGE)
