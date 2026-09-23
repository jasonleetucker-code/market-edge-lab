"""Polymarket US depth ladders feed the shared DepthLadder / walk_ladder / price_depth_fill.

One depth abstraction for every venue (docs/GITHUB_REUSE_AUDIT.md §7.2 follow-up). Side
semantics match `polymarket_us.quotes_from_book`: YES buys from the YES offers; NO buys by
selling YES into the YES bids at 1 − bid.
"""

from __future__ import annotations

import json
import random
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from edge_lab.opportunity import DepthLevel, DepthStatus, price_depth_fill, walk_ladder
from edge_lab.polymarket_us import (
    ladders_from_book, market_from_polymarket, price_grid_from_market, quotes_from_book,
)

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket_us"
BOOK = json.loads((FIXTURES / "book_documented_example.json").read_text(encoding="utf-8"))
SLUG = "will-team-a-win"
AT = "2026-09-23T17:00:00+00:00"
D = Decimal


def ladders(payload=BOOK, **kw):
    return ladders_from_book(SLUG, payload, received_at_utc=AT, evidence_id="snapshot:7", **kw)


def book(bids, offers, state="MARKET_STATE_OPEN", slug=SLUG):
    lv = lambda levels: [{"px": {"value": p, "currency": "USD"}, "qty": q} for p, q in levels]  # noqa: E731
    return {"marketData": {"marketSlug": slug, "bids": lv(bids), "offers": lv(offers), "state": state,
                           "transactTime": "2026-09-23T16:59:59.500Z"}}


def test_top_of_each_ladder_equals_the_quote_path():
    quotes = quotes_from_book(SLUG, BOOK, received_at_utc=AT, evidence_id="snapshot:7")
    out = ladders()
    for side in ("YES", "NO"):
        top = out[side].asks[0]
        assert (top.price, top.size) == (quotes[side].best_ask, quotes[side].displayed_size)
        assert out[side].anomaly is None and quotes[side].anomaly is None
        assert out[side].source_timestamp_utc == quotes[side].source_timestamp_utc == "2025-01-20T12:30:45.123Z"
        assert out[side].market_id == quotes[side].market_id == "polymarket_us:will-team-a-win"


def test_side_semantics_yes_from_offers_no_from_inverted_bids():
    out = ladders()
    assert out["YES"].asks == (DepthLevel(D("0.56"), D("750")), DepthLevel(D("0.57"), D("1200")))
    assert out["NO"].asks == (DepthLevel(D("0.45"), D("1000")), DepthLevel(D("0.46"), D("500")))


def test_native_precision_is_kept():
    out = ladders(book([("0.4455", "12.345")], [("0.5125", "0.5")]))
    assert out["YES"].asks == (DepthLevel(D("0.5125"), D("0.5")),)
    assert out["NO"].asks == (DepthLevel(D("0.5545"), D("12.345")),)


def test_same_price_levels_are_summed_and_zero_levels_dropped_order_independent():
    a = book([("0.40", "3"), ("0.40", "2"), ("0.30", "0")], [("0.60", "1"), ("0.61", "0"), ("0.60", "4")])
    shuffled = deepcopy(a)
    random.Random(3).shuffle(shuffled["marketData"]["bids"])
    random.Random(4).shuffle(shuffled["marketData"]["offers"])
    out = ladders(a)
    assert out["YES"].asks == (DepthLevel(D("0.60"), D("5")),)
    assert out["NO"].asks == (DepthLevel(D("0.60"), D("5")),)
    assert ladders(shuffled) == out


def test_depth_is_unknown_by_default_and_never_insufficient():
    """The docs do not say /book returns every level, so running out is unknown depth."""
    out = ladders()
    assert out["YES"].truncated and out["NO"].truncated
    fill = walk_ladder(out["YES"], 5000)
    assert fill.status is DepthStatus.DEPTH_UNKNOWN and fill.available == D("1950") and fill.gross_cost is None
    complete = ladders(complete_book=True)
    assert walk_ladder(complete["YES"], 5000).status is DepthStatus.INSUFFICIENT_DEPTH


def test_walk_across_levels_prices_each_level_no_midpoint():
    fill = walk_ladder(ladders()["YES"], 1000)
    assert fill.status is DepthStatus.FILLABLE
    assert fill.takes == (DepthLevel(D("0.56"), D("750")), DepthLevel(D("0.57"), D("250")))
    assert fill.gross_cost == D("0.56") * 750 + D("0.57") * 250
    assert fill.limit_price == D("0.57")
    mid = (D("0.55") + D("0.56")) / 2
    assert fill.average_price != mid and fill.average_price >= D("0.56")


def test_no_book_is_missing_not_empty():
    for payload in (None, {}, {"marketData": None}, {"other": 1}):
        assert ladders(payload) == {}


@pytest.mark.parametrize("payload, text", [
    (book([("0.60", "1")], [("0.55", "1")]), "crossed"),
    (book([("0.40", "1")], [("0.60", "1")], state="MARKET_STATE_SUSPENDED"), "not open"),
    (book([("0.40", "1")], [("0.60", "1")], state=None), "not open"),
    (book([("0.40", "1")], [("0.60", "1")], slug="another-market"), "not 'will-team-a-win'"),
    ({"marketData": {"marketSlug": SLUG, "bids": [{"px": {"value": "x", "currency": "USD"}, "qty": "1"}],
                     "offers": [], "state": "MARKET_STATE_OPEN"}}, "malformed"),
    ({"marketData": {"marketSlug": SLUG, "bids": [{"px": {"value": "0.4", "currency": "EUR"}, "qty": "1"}],
                     "offers": [], "state": "MARKET_STATE_OPEN"}}, "malformed"),
    ({"marketData": {"marketSlug": SLUG, "bids": [{"px": {"value": "0.4", "currency": "USD"}, "qty": "-1"}],
                     "offers": [], "state": "MARKET_STATE_OPEN"}}, "malformed"),
    ({"marketData": {"marketSlug": SLUG, "bids": "nope", "offers": [], "state": "MARKET_STATE_OPEN"}}, "malformed"),
])
def test_bad_books_fail_closed_exactly_like_the_quote_path(payload, text):
    out = ladders(payload)
    quotes = quotes_from_book(SLUG, payload, received_at_utc=AT, evidence_id="snapshot:7")
    for side in ("YES", "NO"):
        assert text in out[side].anomaly
        assert out[side].anomaly == quotes[side].anomaly
        assert walk_ladder(out[side], 1).status is DepthStatus.INVALID_BOOK


def test_empty_side_is_zero_offered_not_missing():
    out = ladders(book([], [("0.60", "3")]), complete_book=True)
    assert out["NO"].asks == ()
    fill = walk_ladder(out["NO"], 1)
    assert fill.status is DepthStatus.INSUFFICIENT_DEPTH and fill.available == D(0)


def test_price_grid_from_the_market_record_rejects_off_grid_levels():
    raw = json.loads((FIXTURES / "markets_limit5_2026-09-23T140738Z.json").read_text(encoding="utf-8"))["markets"][0]
    market, _ = market_from_polymarket(raw)
    grid = market.price_grid
    assert grid is not None and grid.ranges[0].step == D("0.001")
    on = ladders(book([("0.4", "1")], [("0.561", "2")]))
    off = ladders(book([("0.4", "1")], [("0.5615", "2")]))
    assert walk_ladder(on["YES"], 1, price_grid=grid).status is DepthStatus.FILLABLE
    bad = walk_ladder(off["YES"], 1, price_grid=grid)
    assert bad.status is DepthStatus.INVALID_BOOK and "price grid" in bad.detail


@pytest.mark.parametrize("tick", [None, "", "0", "-0.01", "abc", "NaN"])
def test_missing_or_bad_tick_gives_no_grid_never_an_assumed_one(tick):
    assert price_grid_from_market({"orderPriceMinTickSize": tick}) is None


def test_fees_are_never_borrowed_from_another_venue():
    fill = walk_ladder(ladders()["YES"], 10)
    cost, why = price_depth_fill(fill, KALSHI_QUADRATIC_TAKER_V1)
    assert cost is None and "prices kalshi, not polymarket_us" in why
