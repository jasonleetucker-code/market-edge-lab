from decimal import Decimal

import pytest

from edge_lab.fees import cost_per_contract, model_fee, taker_buy_cost, taker_trade_fee


def test_matches_documented_worked_example():
    # docs.kalshi.com Fee Rounding: 1 contract at $0.055, model fee $0.00363825,
    # trade fee $0.003639, balance change -$0.06.
    assert model_fee(1, "0.055") == Decimal("0.00363825")
    assert taker_trade_fee(1, "0.055") == Decimal("0.003639")
    assert taker_buy_cost(1, "0.055") == Decimal("0.06")


@pytest.mark.parametrize("price, contracts, expected_cost", [
    ("0.50", 1, Decimal("0.52")),    # 0.50 + 0.0175 -> floor to cent of -(0.5175) = -0.52
    ("0.50", 100, Decimal("51.75")),  # 50 + 1.75 exactly
    ("0.01", 1, Decimal("0.02")),     # 0.01 + 0.000693 -> 0.02
    ("0.99", 10, Decimal("9.91")),    # 9.90 + 0.00693 -> 9.91
])
def test_buy_cost_rounds_against_us(price, contracts, expected_cost):
    assert taker_buy_cost(contracts, price) == expected_cost
    assert taker_buy_cost(contracts, price) >= Decimal(price) * contracts


def test_multiplier_scales_fee():
    assert model_fee(10, "0.30", 2) == 2 * model_fee(10, "0.30", 1)


@pytest.mark.parametrize("price", ["0", "1", "1.2", "-0.1", "0.12345"])
def test_invalid_prices_rejected(price):
    with pytest.raises(ValueError):
        model_fee(1, price)


def test_no_float_contamination():
    assert isinstance(cost_per_contract(3, "0.33"), Decimal)
