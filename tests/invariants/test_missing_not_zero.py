"""Missing values stay missing: never coerced to zero or to an empty result."""

from edge_lab.kalshi import summarize_orderbook


def test_empty_or_missing_book_sides_are_none_not_zero():
    for payload in ({}, {"orderbook_fp": None}, {"orderbook_fp": {"yes_dollars": [], "no_dollars": None}}):
        summary = summarize_orderbook(payload)
        assert all(value is None for value in summary.values()), summary


def test_one_sided_book_leaves_other_side_unknown():
    summary = summarize_orderbook({"orderbook_fp": {"yes_dollars": [["0.30", "5"]]}})
    assert summary["yes_bid"] is not None and summary["no_ask"] is not None
    assert summary["no_bid"] is None and summary["yes_ask"] is None
