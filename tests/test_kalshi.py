from decimal import Decimal

from edge_lab.kalshi import summarize_orderbook


def test_summarize_orderbook_derives_binary_asks():
    payload = {
        "orderbook_fp": {
            "yes_dollars": [["0.32", "10"], ["0.35", "5"]],
            "no_dollars": [["0.58", "7"], ["0.54", "12"]],
        }
    }

    summary = summarize_orderbook(payload)

    assert summary["yes_bid"] == Decimal("0.35")
    assert summary["no_bid"] == Decimal("0.58")
    assert summary["yes_ask"] == Decimal("0.42")
    assert summary["no_ask"] == Decimal("0.65")


def test_summarize_orderbook_handles_empty_side():
    payload = {"orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.60", "1"]]}}

    summary = summarize_orderbook(payload)

    assert summary["yes_bid"] is None
    assert summary["no_ask"] is None
    assert summary["yes_ask"] == Decimal("0.40")
