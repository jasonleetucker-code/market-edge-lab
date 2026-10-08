"""Amendment 2026-10-08 B: liquidity role and role-aware price consistency (ADR 0045).

Every account and book here is SYNTHETIC. A verdict is a heuristic diagnostic about a print, never a
finding about a person. The central regression: bid 0.45 / ask 0.55, a valid maker BUY at 0.45.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from wallet_support import D, Books, InvalidBooks, acct, at, book, obs, with_role

from edge_lab.wallet_intel.events import Action, LiquidityRole, combined_role
from edge_lab.wallet_intel.threats import (FillJudgement, PriceConsistency, liquidity_role, off_market_fills,
                                           price_consistency)

M, T, X, U = LiquidityRole.MAKER, LiquidityRole.TAKER, LiquidityRole.MIXED, LiquidityRole.UNKNOWN
C, I, N = PriceConsistency.CONSISTENT, PriceConsistency.INCONSISTENT, PriceConsistency.INSUFFICIENT_EVIDENCE
TOL, AGE, SKEW = D("0.005"), timedelta(minutes=5), timedelta(seconds=2)
SPREAD = Books(book(bid="0.45", ask="0.55", captured=at(-1)))  # bids 0.45, 0.44; asks 0.55, 0.56


def judge(o, books=SPREAD, **kw):  # type: ignore[no-untyped-def]
    params = dict(tolerance=TOL, max_book_age=AGE, max_clock_skew=SKEW)
    params.update(kw)
    rows = price_consistency([o], books, **params)
    assert len(rows) == 1
    return rows[0]


def trade(action: Action, price: str, role: LiquidityRole | None = None, **kw):  # type: ignore[no-untyped-def]
    o = obs(acct(1), action, "m1-yes", 10, price, at(0), **kw)
    return o if role in (None, LiquidityRole.UNKNOWN) else with_role(o, role)


# --- The regression ---------------------------------------------------------------------------------

def test_maker_buy_at_the_bid_is_consistent_and_v1_mislabels_it():
    maker = trade(Action.TRADE_BUY, "0.45", M)
    row = judge(maker)
    assert row.verdict is C and row.consistent_roles == (M,) and row.role is M
    assert row.best_bid == D("0.45") and row.best_ask == D("0.55")
    # The legacy role-unaware screen still calls it OFF_MARKET: that is the documented v1 defect.
    v1 = off_market_fills([maker], SPREAD, tolerance=TOL, max_book_age=AGE)
    assert v1[0].judgement is FillJudgement.OFF_MARKET


def test_the_same_print_as_a_stated_taker_is_inconsistent():
    assert judge(trade(Action.TRADE_BUY, "0.45", T)).verdict is I


def test_unknown_role_is_never_inferred_from_the_spread_side():
    o = trade(Action.TRADE_BUY, "0.45")
    assert liquidity_role(o).role is U and liquidity_role(o).source is None
    row = judge(o)
    # Consistent because SOME role explains it, and the row says which; the role itself stays UNKNOWN.
    assert row.role is U and row.verdict is C and row.consistent_roles == (M,)
    assert any(r.startswith("CONSISTENT_ONLY_AS_MAKER") for r in row.reasons)


# --- Maker / taker, buy / sell -----------------------------------------------------------------------

@pytest.mark.parametrize("action,price,role,verdict", [
    (Action.TRADE_BUY, "0.55", T, C),  # taker lifts the ask
    (Action.TRADE_BUY, "0.56", T, C),  # walks to the second captured level
    (Action.TRADE_BUY, "0.60", T, I),  # above every ask, side complete
    (Action.TRADE_BUY, "0.50", T, I),  # inside the spread: no ask there to take
    (Action.TRADE_BUY, "0.50", M, C),  # a new best bid, filled by an arriving seller
    (Action.TRADE_BUY, "0.60", M, I),  # a resting bid above the ask would have crossed
    (Action.TRADE_BUY, "0.30", M, N),  # below the bid: only an unseen sweep reaches it
    (Action.TRADE_SELL, "0.45", T, C),  # taker hits the bid
    (Action.TRADE_SELL, "0.44", T, C),
    (Action.TRADE_SELL, "0.40", T, I),  # below every bid, side complete
    (Action.TRADE_SELL, "0.55", T, I),  # taker sale at the ask: no bid there
    (Action.TRADE_SELL, "0.55", M, C),  # maker offer at the ask, lifted
    (Action.TRADE_SELL, "0.40", M, I),  # a resting offer below the bid would have crossed
    (Action.TRADE_SELL, "0.70", M, N),  # above the ask: needs an unseen sweep
    (Action.TRADE_BUY, "0.50", X, C),  # MIXED: explained by some role
    (Action.TRADE_SELL, "0.20", U, I),  # no role explains it
    (Action.TRADE_BUY, "0.30", U, N),  # taker impossible, maker unprovable
])
def test_role_and_side_matrix(action, price, role, verdict):
    assert judge(trade(action, price, role)).verdict is verdict


def test_tolerance_is_respected_both_ways():
    assert judge(trade(Action.TRADE_BUY, "0.546", T)).verdict is C  # within 0.005 of the ask
    assert judge(trade(Action.TRADE_BUY, "0.544", T)).verdict is I


def test_mixed_role_from_fills_of_one_order():
    assert combined_role([M, M]) is M and combined_role([T]) is T
    assert combined_role([M, T]) is X and combined_role([X, M]) is X
    assert combined_role([M, U]) is U and combined_role([]) is U


def test_a_role_needs_its_source_and_only_trades_have_one():
    from dataclasses import replace
    o = trade(Action.TRADE_BUY, "0.45")
    with pytest.raises(ValueError, match="source field"):
        replace(o, liquidity_role=M)
    with pytest.raises(ValueError, match="source field"):
        replace(o, liquidity_role_source="fixture:x")
    transfer = obs(acct(1), Action.TRANSFER_IN, "m1-yes", 10)
    with pytest.raises(ValueError, match="only a trade"):
        with_role(transfer, M)


# --- Book validity: stale, crossed, truncated, missing -------------------------------------------------

def test_stale_book_is_insufficient_evidence():
    row = judge(trade(Action.TRADE_BUY, "0.45", M), Books(book(bid="0.45", ask="0.55", captured=at(-30))))
    assert row.verdict is N and row.reasons[0].startswith("STALE_BOOK")


def test_skew_counts_against_age():
    # 4m59s old is fresh with no skew, stale once a 2s clock disagreement is allowed for.
    b = Books(book(bid="0.45", ask="0.55", captured=at(0) - timedelta(minutes=4, seconds=59)))
    assert judge(trade(Action.TRADE_BUY, "0.45", M), b, max_clock_skew=timedelta(0)).verdict is C
    assert judge(trade(Action.TRADE_BUY, "0.45", M), b).verdict is N


def test_crossed_or_locked_capture_is_insufficient_never_cleared():
    for bid, ask in (("0.56", "0.55"), ("0.55", "0.55")):
        row = judge(trade(Action.TRADE_BUY, "0.55", T), InvalidBooks(bid, ask))
        assert row.verdict is N and row.reasons[0].startswith("BOOK_INVALID")


def test_no_book_and_book_after_the_trade():
    none = judge(trade(Action.TRADE_BUY, "0.45", M), Books())
    assert none.verdict is N and none.reasons == ("NO_BOOK",) and none.best_bid is None

    def future(token, when):  # type: ignore[no-untyped-def]
        return book(token, bid="0.45", ask="0.55", captured=when + timedelta(seconds=1))
    after = judge(trade(Action.TRADE_BUY, "0.45", M), future)
    assert after.verdict is N and after.reasons == ("BOOK_AFTER_TRADE",)


def test_truncated_side_makes_beyond_depth_insufficient_not_inconsistent():
    full = Books(book(bid="0.45", ask="0.55", captured=at(-1)))
    cut = Books(book(bid="0.45", ask="0.55", captured=at(-1), truncated=True))
    assert judge(trade(Action.TRADE_BUY, "0.60", T), full).verdict is I
    assert judge(trade(Action.TRADE_BUY, "0.60", T), cut).verdict is N
    assert judge(trade(Action.TRADE_SELL, "0.40", T), cut).verdict is N
    # Truncation is at the deep end: the inside quote still judges.
    assert judge(trade(Action.TRADE_BUY, "0.50", T), cut).verdict is I


def test_missing_depth_on_a_side():
    no_asks = Books(book(bid="0.45", ask=None, captured=at(-1)))
    no_bids = Books(book(bid=None, ask="0.55", captured=at(-1)))
    assert judge(trade(Action.TRADE_BUY, "0.55", T), no_asks).verdict is N
    assert judge(trade(Action.TRADE_SELL, "0.45", T), no_bids).verdict is N
    assert judge(trade(Action.TRADE_BUY, "0.45", M), no_asks).verdict is N  # a maker needs the full inside quote
    assert judge(trade(Action.TRADE_BUY, "0.55", T), no_bids).verdict is C  # a taker buy needs only asks


def test_missing_price_and_wrong_units():
    from dataclasses import replace
    o = trade(Action.TRADE_BUY, "0.45", M)
    assert judge(replace(o, price=None)).reasons == ("MISSING_PRICE",)
    assert judge(replace(o, price_basis=None)).reasons[0].startswith("UNKNOWN_PRICE_UNIT")
    assert judge(replace(o, price_basis="CENTS")).reasons[0].startswith("UNKNOWN_PRICE_UNIT")
    cents = obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "45", at(0), cash="450")
    assert judge(with_role(cents, M)).reasons[0].startswith("PRICE_OUTSIDE_UNIT_INTERVAL")
    disagree = obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "0.45", at(0), cash="5.5")
    assert judge(with_role(disagree, M)).reasons[0].startswith("PRICE_AND_CASH_LEG_DISAGREE")


# --- Clocks, fees, transfers ----------------------------------------------------------------------------

def test_source_clock_skew():
    # The observation source says it was received 10s before the trade happened: its clock is off.
    early = trade(Action.TRADE_BUY, "0.45", M, receipt_delay=timedelta(seconds=-10))
    assert judge(early).reasons[0].startswith("SOURCE_CLOCK_INCONSISTENT")
    # Within the stated skew it is tolerated.
    assert judge(trade(Action.TRADE_BUY, "0.45", M, receipt_delay=timedelta(seconds=-1))).verdict is C
    # A book captured 1s before the trade, under a 2s skew bound, may postdate it.
    close = Books(book(bid="0.45", ask="0.55", captured=at(0) - timedelta(seconds=1)))
    assert judge(trade(Action.TRADE_BUY, "0.45", M), close).reasons[0].startswith("BOOK_TIME_AMBIGUOUS")
    # A book whose receipt precedes its own capture time by more than the skew: clocks disagree.
    from dataclasses import replace
    bad = replace(book(bid="0.45", ask="0.55", captured=at(-1)), received_at=at(-2))
    assert judge(trade(Action.TRADE_BUY, "0.45", M), Books(bad)).reasons[0].startswith("BOOK_CLOCK_INCONSISTENT")
    ok = replace(book(bid="0.45", ask="0.55", captured=at(-1)), received_at=at(-1) + timedelta(seconds=1),
                 source="synthetic-book", raw_ref="synthetic:book:1")
    row = judge(trade(Action.TRADE_BUY, "0.45", M), Books(ok))
    assert row.verdict is C
    prov = dict(row.provenance)
    assert prov["book_source"] == "synthetic-book" and prov["book_raw_ref"] == "synthetic:book:1"
    assert prov["role_source"] == "fixture:explicit-role" and prov["observation_raw_ref"].startswith("synthetic:")


def test_unknown_fee_does_not_change_price_consistency():
    known = trade(Action.TRADE_BUY, "0.45", M)
    unknown = trade(Action.TRADE_BUY, "0.45", M, fee=None)
    assert not unknown.fee.known
    assert judge(known).verdict is judge(unknown).verdict is C


def test_transfers_carry_no_price_and_get_no_row():
    rows = price_consistency([obs(acct(1), Action.TRANSFER_IN, "m1-yes", 10),
                              obs(acct(1), Action.TRANSFER_OUT, "m1-yes", 10)], SPREAD, tolerance=TOL,
                             max_book_age=AGE, max_clock_skew=SKEW)
    assert rows == ()


def test_bad_bounds_are_refused():
    with pytest.raises(ValueError):
        price_consistency([], SPREAD, tolerance=D("-0.01"), max_book_age=AGE, max_clock_skew=SKEW)
    with pytest.raises(ValueError):
        price_consistency([], SPREAD, tolerance=TOL, max_book_age=AGE, max_clock_skew=timedelta(seconds=-1))
