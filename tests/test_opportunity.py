"""Gate 5: the domain-neutral opportunity engine, fee schedules, conservative bounds, Kalshi quotes."""

from __future__ import annotations

import ast
import math
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import fees
from edge_lab.conservative import WILSON_ONE_SIDED_95, wilson_bounds
from edge_lab.fee_schedules import (
    KALSHI_QUADRATIC_TAKER_V1, FeeScheduleStatus, QuadraticTakerSchedule, get_fee_schedule,
)
from edge_lab.kalshi_quotes import market_from_kalshi, quotes_from_orderbook, rules_check
from edge_lab.opportunity import (
    Event, ExecutableQuote, Market, MarketStatus, ModelEstimate, Payoff, Policy, Reason, evaluate,
    evaluate_event, rank,
)

UTC = timezone.utc
AS_OF = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
EVENT = Event("weather", "weather:test:2026-09-24", "2026-09-24", None, "weather:test-cluster", "test source")
MARKET = Market("kalshi", "kalshi:TEST-B69.5", "TEST-B69.5", EVENT.event_id, "69-70°",
                Payoff("binary", Decimal(1), "value in [69, 70]"), "abc", MarketStatus.OPEN, True, "ok")
VERIFIED = replace(KALSHI_QUADRATIC_TAKER_V1, schedule_id="test-verified", status=FeeScheduleStatus.VERIFIED)
POLICY = Policy("test-point", "point", Decimal("0.05"), 1, timedelta(minutes=5), timedelta(hours=24), "require")


def quote(side="YES", bid="0.40", ask="0.48", size="10", received=AS_OF - timedelta(minutes=2), **kw):
    return ExecutableQuote("kalshi", MARKET.market_id, side,
                           None if bid is None else Decimal(bid), None if ask is None else Decimal(ask),
                           None if size is None else Decimal(size),
                           None if received is None else received.isoformat(), None, "snapshot:1", **kw)


def estimate(p=0.70, n=3551, observed=AS_OF - timedelta(hours=3), generated=AS_OF, **kw):
    fields = dict(model_id="TEST/V1", version="v1", event_id=EVENT.event_id, market_id=MARKET.market_id,
                  probability=p, bounds=None if p is None else wilson_bounds(p, n),
                  generated_at_utc=generated.isoformat(), input_version="sha",
                  input_observed_at_utc=None if observed is None else observed.isoformat())
    fields.update(kw)
    return ModelEstimate(**fields)


def run(side="YES", q="default", e="default", market=MARKET, schedule=VERIFIED, policy=POLICY, as_of=AS_OF):
    return evaluate(event=EVENT, market=market, side=side,
                    quote=quote(side=side) if q == "default" else q,
                    estimate=estimate() if e == "default" else e,
                    fee_schedule=schedule, policy=policy, as_of=as_of)


# --------------------------------------------------------------------------- qualification


def test_qualifying_opportunity_has_every_required_field():
    o = run()
    assert o.qualification == "QUALIFY" and o.rejection_reason == "QUALIFY" and o.reasons == ()
    # all-in cost of 1 contract at 0.48: fee 0.017472 -> cash floor(-0.497472) = 0.50
    assert o.executable_price == Decimal("0.48") and o.all_in_cost == Decimal("0.50")
    assert o.fee == fees.taker_trade_fee(1, "0.48")
    assert o.gross_edge == Decimal("0.22").quantize(Decimal("1e-12"))
    assert o.net_edge == o.net_edge_point
    assert o.model_version == "v1" and o.quote_evidence_id == "snapshot:1"
    assert o.freshness == "fresh" and o.claimable
    required = {"event_id", "market_id", "outcome", "model_probability", "conservative_probability",
                "executable_price", "displayed_size", "fee", "all_in_cost", "gross_edge", "net_edge",
                "freshness", "qualification", "rejection_reason", "model_version", "quote_evidence_id"}
    assert required <= set(o.to_dict())


def test_zero_edge_is_no_edge():
    # price 0.48 -> all-in cost exactly 0.50; p = 0.5 (exact in binary) -> net edge exactly 0.
    o = run(e=estimate(p=0.5), policy=replace(POLICY, min_net_edge=Decimal(0)))
    assert o.net_edge == 0 and o.rejection_reason == "NO_EDGE"


def test_negative_edge_is_no_edge_and_reported():
    o = run(e=estimate(p=0.40))
    assert o.rejection_reason == "NO_EDGE" and o.net_edge < 0 and o.gross_edge < 0


def test_threshold_is_inclusive_like_the_frozen_rule():
    # p - cost >= 0.05 qualifies: p = 0.5625 (exact) and cost 0.50 -> 0.0625 >= 0.05; 0.546875 -> 0.046875 < 0.05
    assert run(e=estimate(p=0.5625)).qualification == "QUALIFY"
    assert run(e=estimate(p=0.546875)).rejection_reason == "NO_EDGE"


# --------------------------------------------------------------------------- executable prices


BOOK = {"orderbook_fp": {"yes_dollars": [["0.3800", "5"], ["0.4000", "12.5"], ["0.4000", "2.5"]],
                         "no_dollars": [["0.5000", "7"], ["0.4500", "100"]]}}


def test_yes_price_crosses_the_best_no_bid():
    q = quotes_from_orderbook("TEST-B69.5", BOOK, received_at_utc="t", evidence_id="snapshot:9")
    assert q["YES"].best_ask == Decimal("0.5000")  # 1 - best NO bid 0.50
    assert q["YES"].displayed_size == Decimal("7")  # size at that NO bid only, no depth walk
    assert q["YES"].best_bid == Decimal("0.4000")


def test_no_price_crosses_the_best_yes_bid():
    q = quotes_from_orderbook("TEST-B69.5", BOOK, received_at_utc="t", evidence_id="snapshot:9")
    assert q["NO"].best_ask == Decimal("0.6000")  # 1 - best YES bid 0.40
    assert q["NO"].displayed_size == Decimal("15.0")  # both 0.40 levels
    assert q["NO"].best_bid == Decimal("0.5000")


def test_midpoint_and_last_price_are_never_used():
    q = quotes_from_orderbook("TEST-B69.5", BOOK, received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat(),
                              evidence_id="snapshot:9")
    o = run(q=q["YES"])
    mid = (q["YES"].best_bid + q["YES"].best_ask) / 2
    assert o.executable_price == Decimal("0.5000") != mid
    fields = set(ExecutableQuote.__dataclass_fields__)
    assert not any("mid" in f or "last" in f for f in fields)


def test_empty_opposite_side_means_nothing_offered():
    q = quotes_from_orderbook("TEST-B69.5", {"orderbook_fp": {"yes_dollars": [["0.40", "3"]], "no_dollars": []}},
                              received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat(), evidence_id="s")
    o = run(q=q["YES"])
    assert q["YES"].best_ask is None and o.rejection_reason == "INSUFFICIENT_SIZE"
    assert o.executable_price is None and o.net_edge is None  # missing is not zero


def test_book_without_orderbook_is_missing():
    assert quotes_from_orderbook("X", {"error": "x"}, received_at_utc="t", evidence_id="s") == {}
    assert quotes_from_orderbook("X", None, received_at_utc="t", evidence_id="s") == {}


def test_crossed_and_malformed_books_are_invalid_prices():
    crossed = quotes_from_orderbook("TEST-B69.5", {"orderbook_fp": {"yes_dollars": [["0.60", "3"]],
                                                                   "no_dollars": [["0.45", "3"]]}},
                                    received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat(), evidence_id="s")
    assert run(q=crossed["YES"]).rejection_reason == "INVALID_PRICE"
    bad = quotes_from_orderbook("TEST-B69.5", {"orderbook_fp": {"yes_dollars": [["x", "3"]]}},
                                received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat(), evidence_id="s")
    assert run(side="NO", q=bad["NO"]).rejection_reason == "INVALID_PRICE"
    assert run(q=quote(ask="1.00", bid=None)).rejection_reason == "INVALID_PRICE"
    assert run(q=quote(ask="0.12345", bid=None)).rejection_reason == "INVALID_PRICE"
    assert run(q=quote(bid="0.48", ask="0.48")).rejection_reason == "INVALID_PRICE"


# --------------------------------------------------------------------------- liquidity


def test_displayed_size_limits_quantity():
    assert run(q=quote(size="0.99")).rejection_reason == "INSUFFICIENT_SIZE"
    assert run(q=quote(size="1")).qualification == "QUALIFY"
    two = replace(POLICY, quantity=2)
    o = run(q=quote(size="1.5"), policy=two)
    assert o.rejection_reason == "INSUFFICIENT_SIZE" and o.displayed_size == Decimal("1.5")


# --------------------------------------------------------------------------- freshness


def test_stale_book_fails_closed():
    o = run(q=quote(received=AS_OF - timedelta(minutes=5, seconds=1)))
    assert o.rejection_reason == "BOOK_STALE" and o.book_freshness == "stale" and o.freshness == "stale"
    assert run(q=quote(received=AS_OF - timedelta(minutes=5))).qualification == "QUALIFY"


def test_book_after_as_of_is_lookahead_not_fresh():
    o = run(q=quote(received=AS_OF + timedelta(seconds=1)))
    assert o.rejection_reason == "BOOK_STALE" and o.book_freshness == "unknown"
    assert "lookahead" in " ".join(o.details)


def test_book_without_timestamp_is_unknown_not_fresh():
    o = run(q=quote(received=None))
    assert o.rejection_reason == "BOOK_STALE" and o.book_freshness == "unknown"


def test_stale_model_fails_closed():
    o = run(e=estimate(observed=AS_OF - timedelta(hours=24, seconds=1)))
    assert o.rejection_reason == "MODEL_STALE" and o.model_freshness == "stale"
    assert run(e=estimate(generated=AS_OF + timedelta(minutes=1))).rejection_reason == "MODEL_STALE"
    assert run(e=estimate(observed=None)).rejection_reason == "MODEL_STALE"
    gone = estimate(p=None, observed=None, unavailable_reason="stale input", unavailable_because_stale=True)
    assert run(e=gone).rejection_reason == "MODEL_STALE"


def test_model_unavailable_leaves_edges_unknown():
    o = run(e=None)
    assert o.rejection_reason == "MODEL_UNAVAILABLE"
    assert o.model_probability is None and o.net_edge is None and o.gross_edge is None
    assert o.executable_price == Decimal("0.48")  # the quote is still reported


def test_missing_book_is_not_zero():
    o = run(q=None)
    assert o.rejection_reason == "BOOK_MISSING"
    assert o.executable_price is None and o.displayed_size is None and o.fee is None
    assert o.all_in_cost is None and o.net_edge is None and o.quote_evidence_id is None


# --------------------------------------------------------------------------- identity, rules, status


def test_event_mismatch_fails_closed():
    other = replace(MARKET, event_id="weather:other")
    assert run(market=other).rejection_reason == "EVENT_MISMATCH"
    wrong_quote = replace(quote(), market_id="kalshi:OTHER")
    assert run(q=wrong_quote).rejection_reason == "EVENT_MISMATCH"
    assert run(e=estimate(event_id="weather:other")).rejection_reason == "EVENT_MISMATCH"
    assert run(side="NO", q=quote(side="YES")).rejection_reason == "EVENT_MISMATCH"


def test_unresolved_rules_fail_closed():
    o = run(market=replace(MARKET, rules_resolved=False, rules_detail="strike contradicts rules"))
    assert o.rejection_reason == "RULES_UNRESOLVED"


def test_closed_market_rejected():
    assert run(market=replace(MARKET, status=MarketStatus.CLOSED)).rejection_reason == "MARKET_CLOSED"
    assert run(market=replace(MARKET, status=MarketStatus.UNKNOWN)).rejection_reason == "MARKET_CLOSED"


def test_all_failed_checks_are_kept_in_precedence_order():
    o = run(market=replace(MARKET, status=MarketStatus.CLOSED), q=None, e=None)
    assert o.reasons == ("MODEL_UNAVAILABLE", "MARKET_CLOSED", "BOOK_MISSING")
    blocked = evaluate(event=EVENT, market=MARKET, side="YES", quote=quote(), estimate=estimate(),
                       fee_schedule=VERIFIED, policy=POLICY, as_of=AS_OF, evidence_problem="day INVALID")
    assert blocked.rejection_reason == "EVIDENCE_INCOMPLETE" and blocked.net_edge is not None
    assert blocked.opportunity_id != run().opportunity_id
    assert o.rejection_reason == "MODEL_UNAVAILABLE"
    assert list(Reason)[0] is Reason.QUALIFY


# --------------------------------------------------------------------------- fees


def test_fee_schedule_matches_the_frozen_fee_model_exactly():
    rng = random.Random(5)
    for _ in range(400):
        c = rng.randint(1, 50)
        p = Decimal(rng.randint(1, 9999)) / Decimal(10000)
        f = KALSHI_QUADRATIC_TAKER_V1.taker_buy(c, p)
        assert f.fee == fees.taker_trade_fee(c, p)
        assert f.total_cost == fees.taker_buy_cost(c, p)
        assert f.cost_per_contract == fees.cost_per_contract(c, p)


def test_fee_schedule_is_unverified_and_versioned():
    assert KALSHI_QUADRATIC_TAKER_V1.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE
    assert get_fee_schedule("kalshi-quadratic-taker-v1") is KALSHI_QUADRATIC_TAKER_V1
    with pytest.raises(KeyError):
        get_fee_schedule("nope")


def test_unverified_fees_reject_or_flag_by_policy():
    required = run(schedule=KALSHI_QUADRATIC_TAKER_V1)
    assert required.rejection_reason == "FEE_UNVERIFIED" and not required.claimable
    flagged = run(schedule=KALSHI_QUADRATIC_TAKER_V1, policy=replace(POLICY, fee_verification="flag"))
    assert flagged.qualification == "QUALIFY" and not flagged.claimable
    assert flagged.fee_status == "UNVERIFIED_CURRENT_SCHEDULE"


def test_a_replacement_schedule_changes_costs_cleanly():
    dearer = QuadraticTakerSchedule("test-dearer", "kalshi", Decimal("0.14"), Decimal(1),
                                    FeeScheduleStatus.VERIFIED, "test", "2026-09-23T00:00:00Z")
    base, alt = run(), run(schedule=dearer)
    assert alt.fee > base.fee and alt.fee_schedule_id == "test-dearer"
    assert alt.opportunity_id != base.opportunity_id


def test_fee_inputs_are_validated():
    with pytest.raises(ValueError):
        KALSHI_QUADRATIC_TAKER_V1.taker_buy(0, Decimal("0.5"))
    with pytest.raises(ValueError):
        KALSHI_QUADRATIC_TAKER_V1.taker_buy(1, Decimal("1"))


# --------------------------------------------------------------------------- conservative probability


def test_wilson_bounds_match_the_closed_form():
    b = wilson_bounds(0.3, 100)
    z = 1.6448536269514722
    centre, spread = 0.3 + z * z / 200, z * math.sqrt(0.3 * 0.7 / 100 + z * z / 40000)
    assert b.lower == pytest.approx((centre - spread) / (1 + z * z / 100), abs=1e-15)
    assert b.upper == pytest.approx((centre + spread) / (1 + z * z / 100), abs=1e-15)
    assert b.lower < 0.3 < b.upper and b.method == WILSON_ONE_SIDED_95 and b.confidence == 0.95


def test_conservative_side_probabilities():
    b = wilson_bounds(0.3, 100)
    assert b.for_side("YES") == (0.3, b.lower)
    assert b.for_side("NO") == (0.7, 1 - b.upper)
    assert wilson_bounds(0.0, 10).lower == 0.0 and wilson_bounds(1.0, 10).upper == 1.0
    with pytest.raises(ValueError):
        wilson_bounds(0.5, 0)
    with pytest.raises(ValueError):
        wilson_bounds(float("nan"), 10)


def test_conservative_basis_is_stricter_than_point():
    # p = 0.5625 with a tiny sample: the point edge qualifies, the conservative one does not.
    point = run(e=estimate(p=0.5625, n=20))
    cons = run(e=estimate(p=0.5625, n=20), policy=replace(POLICY, edge_basis="conservative"))
    assert point.qualification == "QUALIFY"
    assert cons.rejection_reason == "NO_EDGE" and cons.net_edge == cons.net_edge_conservative
    assert cons.conservative_probability < cons.model_probability


def test_more_data_narrows_the_haircut():
    assert wilson_bounds(0.6, 3551).lower > wilson_bounds(0.6, 100).lower


# --------------------------------------------------------------------------- determinism


def _book_of_opportunities():
    markets = [replace(MARKET, market_id=f"kalshi:M{i}", native_id=f"M{i}") for i in range(4)]
    quotes, estimates = {}, {}
    for i, m in enumerate(markets):
        for side in ("YES", "NO"):
            quotes[(m.market_id, side)] = replace(quote(side=side, ask=f"0.{40 + i}"), market_id=m.market_id)
        estimates[m.market_id] = estimate(p=0.5 + i * 0.05, market_id=m.market_id)
    return markets, quotes, estimates


def test_ranking_is_deterministic_and_total():
    markets, quotes, estimates = _book_of_opportunities()
    ranked = evaluate_event(event=EVENT, markets=markets, quotes=quotes, estimates=estimates,
                            fee_schedule=VERIFIED, policy=POLICY, as_of=AS_OF)
    assert len(ranked) == 8  # every (market, side), nothing dropped
    shuffled = ranked[:]
    random.Random(1).shuffle(shuffled)
    assert rank(shuffled) == ranked
    qualified = [o for o in ranked if o.qualification == "QUALIFY"]
    assert ranked[:len(qualified)] == qualified
    assert [o.net_edge for o in qualified] == sorted((o.net_edge for o in qualified), reverse=True)


def test_evaluation_is_repeatable_and_ids_are_content_addressed():
    a, b = run(), run()
    assert a == b and a.to_dict() == b.to_dict()
    assert a.opportunity_id.startswith("opp-")
    assert run(q=replace(quote(), evidence_id="snapshot:2")).opportunity_id != a.opportunity_id
    assert run(as_of=AS_OF - timedelta(seconds=1)).opportunity_id != a.opportunity_id
    # Same evidence id, different content (e.g. two partial captures): ids still differ.
    assert run(q=replace(quote(), best_ask=Decimal("0.47"))).opportunity_id != a.opportunity_id
    assert run(market=replace(MARKET, status=MarketStatus.CLOSED)).opportunity_id != a.opportunity_id
    assert run(e=estimate(p=0.71)).opportunity_id != a.opportunity_id


def test_policy_validation():
    with pytest.raises(ValueError):
        replace(POLICY, edge_basis="vibes")
    with pytest.raises(ValueError):
        replace(POLICY, fee_verification="maybe")
    with pytest.raises(ValueError):
        replace(POLICY, quantity=0)
    with pytest.raises(ValueError):
        replace(POLICY, min_net_edge=Decimal("-0.01"))
    with pytest.raises(ValueError):
        evaluate(event=EVENT, market=MARKET, side="MAYBE", quote=None, estimate=None,
                 fee_schedule=VERIFIED, policy=POLICY, as_of=AS_OF)


# --------------------------------------------------------------------------- Kalshi market adapter


RAW = {
    "ticker": "KXHIGHNY-26SEP24-B69.5", "event_ticker": "KXHIGHNY-26SEP24", "status": "active",
    "strike_type": "between", "floor_strike": 69, "cap_strike": 70, "yes_sub_title": "69° to 70°",
    "rules_primary": "If the maximum temperature recorded at New York City (CLINYC) for Sep 24, 2026, is "
                     "between 69-70° fahrenheit according to The Weather Company, then the market resolves to Yes.",
}


def test_kalshi_market_mapping_and_rules():
    m = market_from_kalshi(RAW, event_id_for_ticker={"KXHIGHNY-26SEP24": "weather:x"})
    assert m.market_id == "kalshi:KXHIGHNY-26SEP24-B69.5" and m.event_id == "weather:x"
    assert m.status is MarketStatus.OPEN and m.rules_resolved and m.rules_sha256
    assert rules_check(RAW)[0]


def test_kalshi_unmapped_event_and_contradicting_rules():
    m = market_from_kalshi(RAW, event_id_for_ticker={})
    assert m.event_id.startswith("unmapped:")
    bad = dict(RAW, floor_strike=68)
    assert not market_from_kalshi(bad, event_id_for_ticker={}).rules_resolved
    unknown_source = dict(RAW, rules_primary="between 69-70° according to someone")
    assert not rules_check(unknown_source)[0]
    assert market_from_kalshi(dict(RAW, status="settled"), event_id_for_ticker={}).status is MarketStatus.CLOSED
    assert market_from_kalshi(dict(RAW, status="weird"), event_id_for_ticker={}).status is MarketStatus.UNKNOWN


# --------------------------------------------------------------------------- no execution paths


def test_gate5_modules_have_no_network_or_order_imports():
    src = Path(__file__).resolve().parents[1] / "src" / "edge_lab"
    for name in ("opportunity", "fee_schedules", "conservative", "kalshi_quotes", "exp001_stageb"):
        tree = ast.parse((src / f"{name}.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))
        assert not {"urllib", "urllib.request", "http", "socket", ".http", ".kalshi"} & imported, name
