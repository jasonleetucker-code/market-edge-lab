"""The binary engine refuses unsupported payoffs; market tick grids are metadata (ADR 0023).

EXP-001 stays byte-for-byte identical: its Kalshi markets are binary contracts paying 1, and
the engine does not enforce the market grid (a depth walk does when the caller passes it).
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.kalshi_quotes import ladders_from_orderbook, market_from_kalshi, price_grid_from_kalshi
from edge_lab.opportunity import (
    DepthStatus, Payoff, PriceGrid, PriceRange, Reason, evaluate, walk_ladder,
)

from test_opportunity import AS_OF, EVENT, MARKET, POLICY, VERIFIED, estimate, quote, run

FORWARD = Path(__file__).parent / "fixtures" / "forward"
PRE_CHANGE_ID = "opp-63700c53df301575bd45291011c32318"  # run() on main 247fe80, before this change
D = Decimal


# --------------------------------------------------------------------------- payoff guard


def test_binary_payoff_paying_one_is_unchanged():
    assert run().qualification == "QUALIFY"


@pytest.mark.parametrize("payoff", [
    Payoff("scalar", D(1), "value between 60 and 80"),
    Payoff("categorical", D(1), "one of several outcomes"),
    Payoff("binary", D("100"), "pays 100"),
    Payoff("binary", D("0.5"), "pays 0.5"),
])
def test_unsupported_payoffs_are_rejected_explicitly(payoff):
    opp = run(market=replace(MARKET, payoff=payoff))
    assert opp.qualification == "REJECT"
    assert Reason.PAYOFF_UNSUPPORTED.value in opp.reasons
    assert any("only binary contracts paying 1" in d for d in opp.details)


def test_payoff_guard_does_not_change_the_opportunity_id():
    """The id hashes identity and inputs, not the payoff or the reasons: EXP-001 ids stay
    what they were. Pinned against a value computed before this change."""
    base = run()
    rejected = run(market=replace(MARKET, payoff=Payoff("scalar", D(1), "scalar")))
    assert rejected.opportunity_id == base.opportunity_id
    assert base.opportunity_id == PRE_CHANGE_ID
    assert Reason.PAYOFF_UNSUPPORTED.value not in base.reasons


# --------------------------------------------------------------------------- price grid


def test_kalshi_price_ranges_become_the_market_grid():
    raw = json.loads((FORWARD / "markets_KXHIGHNY-26SEP23.json").read_text(encoding="utf-8"))["markets"][0]
    market = market_from_kalshi(raw, event_id_for_ticker={})
    grid = market.price_grid
    assert grid == PriceGrid((PriceRange(D("0.0000"), D("1.0000"), D("0.0100")),), grid.source)
    assert "linear_cent" in grid.source
    assert grid.contains(D("0.48")) and grid.contains(D("0.4800"))
    assert not grid.contains(D("0.485")) and not grid.contains(D("NaN")) and not grid.contains(D("1.01"))


def test_every_captured_kalshi_ask_is_on_its_markets_grid():
    raw = json.loads((FORWARD / "markets_KXHIGHNY-26SEP23.json").read_text(encoding="utf-8"))["markets"]
    grids = {m["ticker"]: price_grid_from_kalshi(m) for m in raw}
    assert grids and all(g is not None for g in grids.values())
    books = list(FORWARD.glob("orderbook_*.json"))
    assert books, "no captured order books to check"
    for path in books:
        ticker = path.stem.removeprefix("orderbook_")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for ladder in ladders_from_orderbook(ticker, payload, received_at_utc="2026-09-22T22:00:00+00:00",
                                             evidence_id=None, depth_limit=100).values():
            assert walk_ladder(ladder, 1, price_grid=grids[ticker]).status is DepthStatus.FILLABLE


def test_subpenny_structures_are_honoured():
    grid = price_grid_from_kalshi({"price_ranges": [
        {"start": "0.00", "end": "0.10", "step": "0.001"},
        {"start": "0.10", "end": "0.90", "step": "0.01"},
        {"start": "0.90", "end": "1.00", "step": "0.001"},
    ], "price_level_structure": "tapered_deci_cent"})
    assert grid.contains(D("0.005")) and grid.contains(D("0.10")) and grid.contains(D("0.955"))
    assert not grid.contains(D("0.505"))


@pytest.mark.parametrize("raw", [
    {}, {"price_ranges": None}, {"price_ranges": []}, {"price_ranges": "0.01"},
    {"price_ranges": [{"start": "0", "end": "1"}]},
    {"price_ranges": [{"start": "0", "end": "1", "step": "0"}]},
    {"price_ranges": [{"start": "0.5", "end": "0.4", "step": "0.01"}]},
    {"price_ranges": [{"start": "0", "end": "2", "step": "0.01"}]},
    {"price_ranges": [{"start": "x", "end": "1", "step": "0.01"}]},
])
def test_missing_or_malformed_grids_are_none_never_assumed(raw):
    assert price_grid_from_kalshi(raw) is None


def test_engine_does_not_enforce_the_grid_so_exp001_decisions_are_unchanged():
    """A market whose published grid excludes the ask still evaluates exactly as before:
    the grid is enforced only by depth walks given `price_grid=`, never by the frozen engine path."""
    coarse = PriceGrid((PriceRange(D(0), D(1), D("0.25")),), "test")
    with_grid = run(market=replace(MARKET, price_grid=coarse))
    assert with_grid.to_dict() == run().to_dict()


@pytest.mark.parametrize("r", [
    PriceRange(D(0), D(1), D("NaN")),
    PriceRange(D(0), D(1), D(2)),  # a step larger than the range admits only the start
    PriceRange(D(0), D(1), D("1E-30")),  # too fine for Decimal arithmetic
    PriceRange(D("0.5"), D("0.5"), D("0.01")),
])
def test_grid_rejects_invalid_ranges(r):
    with pytest.raises(ValueError):
        PriceGrid((r,), "bad")
    with pytest.raises(ValueError):
        PriceGrid((), "empty")


def test_contains_fails_closed_on_non_prices():
    grid = PriceGrid((PriceRange(D(0), D(1), D("0.001")),), "t")
    assert grid.contains(D("0.5")) and grid.contains(D("0.001"))
    assert not grid.contains(D("1E-40")) and not grid.contains(0.5) and not grid.contains(D("-0.001"))
