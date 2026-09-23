"""Venue-neutral depth ladders: walk-the-book cost for a requested quantity.

Pattern source (ideas only, no code copied): the unified order-book structures and
walk-the-book costing surveyed in docs/GITHUB_REUSE_AUDIT.md. The semantics here are ours:
captured levels only, all or nothing, truncated captures are unknown rather than thin.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from edge_lab.forward import BOOK_DEPTH
from edge_lab.kalshi_quotes import ladders_from_orderbook, quotes_from_orderbook
from edge_lab.opportunity import (
    DepthLadder, DepthLevel, DepthStatus, price_depth_fill, walk_ladder,
)

FIXTURE = Path(__file__).parent / "fixtures" / "forward" / "orderbook_KXHIGHNY-26SEP23-B69.5.json"
NATIVE = "KXHIGHNY-26SEP23-B69.5"
RECEIVED = "2026-09-23T21:58:00+00:00"
D = Decimal


def ladder(*levels, truncated=False, anomaly=None, side="YES"):
    return DepthLadder("test", "test:M", side, tuple(DepthLevel(D(p), D(s)) for p, s in levels),
                       truncated, RECEIVED, None, "snapshot:1", anomaly)


def fixture_ladders(depth_limit=BOOK_DEPTH):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload, ladders_from_orderbook(NATIVE, payload, received_at_utc=RECEIVED, evidence_id="snapshot:1",
                                           depth_limit=depth_limit)


# --------------------------------------------------------------------------- Kalshi adapter


def test_ladder_top_is_exactly_the_frozen_top_of_book_quote():
    payload, ladders = fixture_ladders()
    quotes = quotes_from_orderbook(NATIVE, payload, received_at_utc=RECEIVED, evidence_id="snapshot:1")
    for side in ("YES", "NO"):
        top = ladders[side].asks[0]
        assert (top.price, top.size) == (quotes[side].best_ask, quotes[side].displayed_size)
        assert ladders[side].market_id == quotes[side].market_id
        assert ladders[side].received_at_utc == RECEIVED and ladders[side].evidence_id == "snapshot:1"


def test_every_captured_level_becomes_an_ascending_ask():
    payload, ladders = fixture_ladders()
    book = payload["orderbook_fp"]
    for side, opposite in (("YES", "no_dollars"), ("NO", "yes_dollars")):
        asks = ladders[side].asks
        assert [a.price for a in asks] == sorted(D(1) - D(p) for p, _ in book[opposite])
        assert sum(a.size for a in asks) == sum(D(s) for _, s in book[opposite])
        assert all(x.price < y.price for x, y in zip(asks, asks[1:]))


def test_level_order_in_the_payload_does_not_matter():
    payload, ladders = fixture_ladders()
    shuffled = json.loads(json.dumps(payload))
    rng = random.Random(7)
    for key in ("yes_dollars", "no_dollars"):
        rng.shuffle(shuffled["orderbook_fp"][key])
    again = ladders_from_orderbook(NATIVE, shuffled, received_at_utc=RECEIVED, evidence_id="snapshot:1",
                                   depth_limit=BOOK_DEPTH)
    assert again == ladders


def test_same_price_levels_are_summed_and_empty_levels_dropped():
    payload = {"orderbook_fp": {"no_dollars": [["0.40", "3"], ["0.40", "2"], ["0.30", "0"]], "yes_dollars": []}}
    ladders = ladders_from_orderbook("T", payload, received_at_utc=RECEIVED, evidence_id=None, depth_limit=None)
    assert ladders["YES"].asks == (DepthLevel(D("0.60"), D("5")),)
    assert ladders["NO"].asks == ()


def test_no_book_is_missing_not_an_empty_ladder():
    for payload in (None, {}, {"orderbook_fp": None}):
        assert ladders_from_orderbook("T", payload, received_at_utc=RECEIVED, evidence_id=None, depth_limit=None) == {}


def test_malformed_and_crossed_books_carry_the_anomaly():
    malformed = {"orderbook_fp": {"yes_dollars": [["x", "1"]], "no_dollars": []}}
    crossed = {"orderbook_fp": {"yes_dollars": [["0.60", "1"]], "no_dollars": [["0.45", "1"]]}}
    for payload, text in ((malformed, "malformed"), (crossed, "crossed")):
        ladders = ladders_from_orderbook("T", payload, received_at_utc=RECEIVED, evidence_id=None, depth_limit=None)
        for side in ("YES", "NO"):
            assert text in ladders[side].anomaly
            assert walk_ladder(ladders[side], 1).status is DepthStatus.INVALID_BOOK


def test_a_side_at_the_requested_depth_is_truncated():
    payload = {"orderbook_fp": {"no_dollars": [["0.40", "1"], ["0.39", "1"], ["0.38", "1"]],
                                "yes_dollars": [["0.10", "1"]]}}
    ladders = ladders_from_orderbook("T", payload, received_at_utc=RECEIVED, evidence_id=None, depth_limit=3)
    assert ladders["YES"].truncated and not ladders["NO"].truncated
    unlimited = ladders_from_orderbook("T", payload, received_at_utc=RECEIVED, evidence_id=None, depth_limit=None)
    assert not unlimited["YES"].truncated
    _, fixture = fixture_ladders()
    assert not fixture["YES"].truncated and not fixture["NO"].truncated  # both sides < 100 levels


# --------------------------------------------------------------------------- walk


def test_walk_inside_the_top_level():
    fill = walk_ladder(ladder(("0.48", "10"), ("0.50", "5")), 4)
    assert fill.status is DepthStatus.FILLABLE
    assert fill.takes == (DepthLevel(D("0.48"), D(4)),)
    assert (fill.gross_cost, fill.average_price, fill.limit_price) == (D("1.92"), D("0.48"), D("0.48"))


def test_walk_across_levels_prices_each_level_and_reports_the_limit():
    fill = walk_ladder(ladder(("0.48", "2"), ("0.50", "1.5"), ("0.53", "10")), 5)
    assert fill.takes == (DepthLevel(D("0.48"), D(2)), DepthLevel(D("0.50"), D("1.5")), DepthLevel(D("0.53"), D("1.5")))
    assert fill.gross_cost == D("0.96") + D("0.75") + D("0.795")
    assert fill.limit_price == D("0.53")
    assert fill.average_price == D("0.501000000000")
    assert fill.available == D(5)


def test_average_price_never_understates_cost():
    fill = walk_ladder(ladder(("0.01", "1"), ("0.02", "2")), 3)  # 0.05 / 3 = 0.01666…
    assert fill.average_price == D("0.016666666667")
    assert fill.average_price * 3 >= fill.gross_cost


def test_complete_book_too_thin_is_insufficient_and_never_partially_priced():
    fill = walk_ladder(ladder(("0.48", "2"), ("0.50", "1")), 5)
    assert fill.status is DepthStatus.INSUFFICIENT_DEPTH
    assert fill.available == D(3)
    assert fill.takes == () and fill.gross_cost is None and fill.average_price is None and fill.limit_price is None


def test_truncated_book_running_out_is_unknown_not_insufficient():
    fill = walk_ladder(ladder(("0.48", "2"), truncated=True), 5)
    assert fill.status is DepthStatus.DEPTH_UNKNOWN
    assert fill.available == D(2) and fill.gross_cost is None
    # A truncated capture that already covers the quantity is still fillable.
    assert walk_ladder(ladder(("0.48", "5"), truncated=True), 5).status is DepthStatus.FILLABLE


def test_empty_complete_side_offers_nothing():
    fill = walk_ladder(ladder(), 1)
    assert fill.status is DepthStatus.INSUFFICIENT_DEPTH and fill.available == D(0)


@pytest.mark.parametrize("levels, text", [
    ((("0.50", "1"), ("0.48", "1")), "ascending"),
    ((("0.48", "1"), ("0.48", "1")), "ascending"),
    ((("0.48", "0"),), "invalid size"),
    ((("0.48", "-1"),), "invalid size"),
    ((("0.48", "NaN"),), "invalid size"),
    ((("0.00", "1"),), "not a valid contract price"),
    ((("1.00", "1"),), "not a valid contract price"),
    ((("0.48123", "1"),), "not a valid contract price"),
    ((("NaN", "1"),), "not a valid contract price"),
])
def test_malformed_ladders_are_invalid_books(levels, text):
    fill = walk_ladder(ladder(*levels), 1)
    assert fill.status is DepthStatus.INVALID_BOOK and text in fill.detail
    assert fill.available is None and fill.gross_cost is None


def test_anomaly_wins_even_when_levels_look_fine():
    fill = walk_ladder(ladder(("0.48", "10"), anomaly="crossed book"), 1)
    assert fill.status is DepthStatus.INVALID_BOOK and fill.detail == "crossed book"


@pytest.mark.parametrize("quantity", [0, -1, D(0), D("-0.5"), D("NaN"), D("Infinity"), 1.5, "1", True])
def test_quantity_must_be_a_positive_finite_number(quantity):
    with pytest.raises(ValueError):
        walk_ladder(ladder(("0.48", "10")), quantity)


def test_walk_properties_on_random_books():
    rng = random.Random(20260923)
    for _ in range(300):
        prices = sorted(rng.sample(range(1, 100), rng.randint(1, 8)))
        book = ladder(*((f"0.{p:02d}", str(rng.randint(1, 20))) for p in prices))
        depth = sum(level.size for level in book.asks)
        previous_cost = D(0)
        for qty in range(1, int(depth) + 3):
            fill = walk_ladder(book, qty)
            if qty > depth:
                assert fill.status is DepthStatus.INSUFFICIENT_DEPTH
                continue
            assert fill.status is DepthStatus.FILLABLE
            assert sum(t.size for t in fill.takes) == qty
            assert book.asks[0].price <= fill.average_price <= fill.limit_price
            assert fill.gross_cost > previous_cost  # buying more never costs less
            previous_cost = fill.gross_cost


# --------------------------------------------------------------------------- fees


def test_one_level_fee_equals_the_engine_fee_schedule():
    fill = walk_ladder(ladder(("0.48", "10")), 3)
    cost, why = price_depth_fill(fill, KALSHI_QUADRATIC_TAKER_V1)
    direct = KALSHI_QUADRATIC_TAKER_V1.taker_buy(3, D("0.48"))
    assert why == "priced"
    assert (cost.fee, cost.total_cost) == (direct.fee, direct.total_cost)
    assert cost.cost_per_contract == direct.cost_per_contract.quantize(D("1e-12"))


def test_each_level_is_priced_as_its_own_taker_fill():
    fill = walk_ladder(ladder(("0.48", "2"), ("0.50", "1"), ("0.53", "10")), 5)
    cost, _ = price_depth_fill(fill, KALSHI_QUADRATIC_TAKER_V1)
    expected = [KALSHI_QUADRATIC_TAKER_V1.taker_buy(q, D(p)) for p, q in (("0.48", 2), ("0.50", 1), ("0.53", 2))]
    assert cost.fee_quotes == tuple(expected)
    assert cost.total_cost == sum(q.total_cost for q in expected)
    assert cost.total_cost >= fill.gross_cost  # fees never make it cheaper
    assert cost.cost_per_contract * 5 >= cost.total_cost


def test_no_cost_for_unfillable_or_fractional_walks():
    thin = walk_ladder(ladder(("0.48", "1")), 2)
    assert price_depth_fill(thin, KALSHI_QUADRATIC_TAKER_V1) == (None, f"walk is INSUFFICIENT_DEPTH: {thin.detail}")
    fractional = walk_ladder(ladder(("0.48", "0.5"), ("0.49", "5")), 2)
    cost, why = price_depth_fill(fractional, KALSHI_QUADRATIC_TAKER_V1)
    assert cost is None and "fractional" in why


def test_fees_follow_the_schedule_passed_in():
    fill = walk_ladder(ladder(("0.48", "10")), 10)
    doubled = replace(KALSHI_QUADRATIC_TAKER_V1, schedule_id="test-doubled", multiplier=D(2))
    base, _ = price_depth_fill(fill, KALSHI_QUADRATIC_TAKER_V1)
    more, _ = price_depth_fill(fill, doubled)
    assert more.fee > base.fee and more.fee_quotes[0].schedule_id == "test-doubled"
