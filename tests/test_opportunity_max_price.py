"""`opportunity.break_even_probability` and `opportunity.max_acceptable_price` (ADR 0049).

Hand checks use the quadratic taker formula of `edge_lab.fees`: trade fee = ceil_6dp(0.07 * C * P * (1 - P)),
cash = floor_cent(-(P * C) - fee), so the cost per contract is the cent-rounded total over C.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_CEILING, Decimal

import pytest

from edge_lab import fees
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1, UnsupportedFeeSchedule, schedule_for
from edge_lab.opportunity import PriceGrid, PriceRange, break_even_probability, max_acceptable_price

D = Decimal
K = KALSHI_QUADRATIC_TAKER_V1
UNSUPPORTED = schedule_for("kalshi", "KXCPI")
CENT_GRID = [D(i) / 100 for i in range(1, 100)]


def hand_cost(contracts: int, price: Decimal) -> Decimal:
    trade_fee = (D("0.07") * contracts * price * (1 - price)).quantize(D("0.000001"), rounding=ROUND_CEILING)
    total = (price * contracts + trade_fee).quantize(D("0.01"), rounding=ROUND_CEILING)
    return total / contracts


def test_unsupported_fixture_is_really_unsupported():
    assert isinstance(UNSUPPORTED, UnsupportedFeeSchedule)


# --------------------------------------------------------------------------- break-even


def test_break_even_is_the_hand_computed_all_in_cost():
    # 0.07 * 0.38 * 0.62 = 0.016492; 0.38 + 0.016492 = 0.396492 -> 0.40 at the cent.
    assert break_even_probability(K, D("0.38")) == D("0.40") == hand_cost(1, D("0.38"))
    assert break_even_probability(K, D("0.38")) == fees.cost_per_contract(1, D("0.38"))
    # Ten contracts: 3.80 + 0.16492 = 3.96492 -> 3.97, i.e. 0.397 per contract.
    assert break_even_probability(K, D("0.38"), 10) == D("0.397") == hand_cost(10, D("0.38"))


@pytest.mark.parametrize("price", CENT_GRID)
def test_break_even_is_above_every_fee_bearing_price(price):
    be = break_even_probability(K, price)
    assert be == hand_cost(1, price)
    assert be > price


@pytest.mark.parametrize("price", [D("0"), D("1"), D("-0.1"), D("1.5"), D("0.00001"), D("NaN"), 0.38, "0.38", None])
def test_break_even_is_none_for_an_invalid_price(price):
    assert break_even_probability(K, price) is None


def test_break_even_is_none_for_an_unsupported_schedule():
    assert break_even_probability(UNSUPPORTED, D("0.38")) is None


@pytest.mark.parametrize("quantity", [0, -1, True, 1.0])
def test_break_even_refuses_an_invalid_quantity(quantity):
    with pytest.raises(ValueError):
        break_even_probability(K, D("0.38"), quantity)


# --------------------------------------------------------------------------- monotonicity


@pytest.mark.parametrize("quantity", [1, 2, 3, 7, 10, 100])
def test_cost_is_monotone_over_the_full_cent_grid(quantity):
    costs = [K.taker_buy(quantity, p).cost_per_contract for p in CENT_GRID]
    assert all(a <= b for a, b in zip(costs, costs[1:]))


def test_cost_is_monotone_over_the_deci_cent_grid():
    prices = [D(i) / 1000 for i in range(1, 1000)]
    costs = [K.taker_buy(1, p).cost_per_contract for p in prices]
    assert all(a <= b for a, b in zip(costs, costs[1:]))


# --------------------------------------------------------------------------- max acceptable price


def test_price_dependent_fee_makes_the_naive_limit_wrong():
    # p_cons 0.47, margin 0.03: the naive limit is 0.44, but every cent price above 0.42 costs more
    # than 0.44 all-in: 0.42 -> 0.42 + 0.017052 = 0.437052 -> 0.44; 0.43 -> 0.447157 -> 0.45.
    limit = max_acceptable_price(D("0.47"), K, margin=D("0.03"))
    assert limit == D("0.42")
    assert limit != D("0.47") - D("0.03")
    assert hand_cost(1, D("0.42")) == D("0.44") <= D("0.44") < hand_cost(1, D("0.43")) == D("0.45")


def test_the_result_is_the_highest_qualifying_price_on_the_grid():
    for threshold in (D("0.10"), D("0.33"), D("0.5"), D("0.777"), D("0.95")):
        limit = max_acceptable_price(threshold, K)
        ok = [p for p in CENT_GRID if hand_cost(1, p) <= threshold]
        assert limit == max(ok)


def test_quantity_changes_the_limit_because_rounding_is_per_order():
    # 0.05 x 1 costs 0.05 + 0.003325 -> 0.06 > 0.055; 0.05 x 10 costs 0.5 + 0.03325 = 0.53325 -> 0.54,
    # i.e. 0.054 per contract <= 0.055.
    assert hand_cost(1, D("0.05")) == D("0.06") and hand_cost(10, D("0.05")) == D("0.054")
    assert max_acceptable_price(D("0.055"), K, quantity=1) == D("0.04")
    assert max_acceptable_price(D("0.055"), K, quantity=10) == D("0.05")


def test_unsupported_schedule_gives_none():
    assert max_acceptable_price(D("0.9"), UNSUPPORTED) is None


@pytest.mark.parametrize("probability, margin", [
    (D("-0.01"), D("0")), (D("1.01"), D("0")), (D("NaN"), D("0")), (0.5, D("0")), (None, D("0")),
    (D("0.5"), D("-0.01")), (D("0.5"), D("Infinity")), (D("0.5"), 0.01),
])
def test_invalid_inputs_give_none(probability, margin):
    assert max_acceptable_price(probability, K, margin=margin) is None


def test_no_qualifying_price_gives_none_not_zero():
    assert max_acceptable_price(D("0.01"), K) is None  # 0.01 costs 0.02 all-in
    assert max_acceptable_price(D("0.05"), K, margin=D("0.05")) is None


def test_market_grid_is_used_when_given():
    tapered = PriceGrid((PriceRange(D("0"), D("0.1"), D("0.001")), PriceRange(D("0.1"), D("0.9"), D("0.01")),
                         PriceRange(D("0.9"), D("1"), D("0.001"))), source="test tapered")
    # Below 0.10 the deci-cent grid applies: 0.046 costs 0.046 + 0.003072 -> 0.05 <= 0.05; 0.047 costs
    # 0.047 + 0.003137 -> 0.06.
    assert hand_cost(1, D("0.046")) == D("0.05") < hand_cost(1, D("0.047")) == D("0.06")
    assert max_acceptable_price(D("0.05"), K, grid=tapered) == D("0.046")
    assert max_acceptable_price(D("0.05"), K) == D("0.04")  # cent step grid
    coarse = PriceGrid((PriceRange(D("0"), D("1"), D("0.05")),), source="test coarse")
    assert max_acceptable_price(D("0.47"), K, margin=D("0.03"), grid=coarse) == D("0.40")


def test_a_schedule_that_refuses_a_valid_price_fails_closed():
    class Refusing:
        schedule_id, venue, status = "refusing", "kalshi", K.status

        def taker_buy(self, contracts, price):
            raise ValueError("refused")

    assert max_acceptable_price(D("0.9"), Refusing()) is None


def test_zero_fee_schedule_limit_is_the_threshold():
    free = replace(K, schedule_id="test-free", coefficient=D("0"))
    assert max_acceptable_price(D("0.47"), free, margin=D("0.03")) == D("0.44")
