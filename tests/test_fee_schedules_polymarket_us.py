"""Polymarket US fee schedule: documented arithmetic, a conservative bound, point-in-time status.

Evidence: experiments/multi_venue/polymarket_us_fees_2026-09-24.md (docs.polymarket.us/fees,
effective 2026-09-17; Polymarket US Rulebook 2026-09-14 Rule 3.8). ADR 0027.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

import pytest

from edge_lab import fee_schedules
from edge_lab.fee_schedules import (
    KALSHI_QUADRATIC_TAKER_V1, POLYMARKET_US_EXCHANGE_SCOPE, POLYMARKET_US_TAKER_V1,
    POLYMARKET_US_VERIFICATION_2026_09_24 as RECORD, ClaimBasis, ComponentState, FeeScheduleStatus,
    UnsupportedFeeSchedule, VerificationComponent, bankers_fee, claim_adjusted_net, recheck_due,
    restated_verification, schedule_for, verification_at,
)
from edge_lab.freshness import parse_utc
from edge_lab.opportunity import DepthLadder, DepthLevel, price_depth_fill, walk_ladder

D = Decimal
PM = POLYMARKET_US_TAKER_V1
TAKER, MAKER = D("0.0695"), D("0.0125")
KNOWN = parse_utc(RECORD.knowledge_time_utc)

# The fee page's "Fee Schedule by Price" table (100-lot): price, taker pays, maker receives.
PUBLISHED_100_LOT = """
0.01:0.07:0.01 0.02:0.14:0.02 0.03:0.20:0.04 0.04:0.27:0.05 0.05:0.33:0.06 0.06:0.39:0.07 0.07:0.45:0.08
0.08:0.51:0.09 0.09:0.57:0.10 0.10:0.63:0.11 0.11:0.68:0.12 0.12:0.73:0.13 0.13:0.79:0.14 0.14:0.84:0.15
0.15:0.89:0.16 0.16:0.93:0.17 0.17:0.98:0.18 0.18:1.03:0.18 0.19:1.07:0.19 0.20:1.11:0.20 0.21:1.15:0.21
0.22:1.19:0.21 0.23:1.23:0.22 0.24:1.27:0.23 0.25:1.30:0.23 0.26:1.34:0.24 0.27:1.37:0.25 0.28:1.40:0.25
0.29:1.43:0.26 0.30:1.46:0.26 0.31:1.49:0.27 0.32:1.51:0.27 0.33:1.54:0.28 0.34:1.56:0.28 0.35:1.58:0.28
0.36:1.60:0.29 0.37:1.62:0.29 0.38:1.64:0.29 0.39:1.65:0.30 0.40:1.67:0.30 0.41:1.68:0.30 0.42:1.69:0.30
0.43:1.70:0.31 0.44:1.71:0.31 0.45:1.72:0.31 0.46:1.73:0.31 0.47:1.73:0.31 0.48:1.73:0.31 0.49:1.74:0.31
0.50:1.74:0.31 0.51:1.74:0.31 0.52:1.73:0.31 0.53:1.73:0.31 0.54:1.73:0.31 0.55:1.72:0.31 0.56:1.71:0.31
0.57:1.70:0.31 0.58:1.69:0.30 0.59:1.68:0.30 0.60:1.67:0.30 0.61:1.65:0.30 0.62:1.64:0.29 0.63:1.62:0.29
0.64:1.60:0.29 0.65:1.58:0.28 0.66:1.56:0.28 0.67:1.54:0.28 0.68:1.51:0.27 0.69:1.49:0.27 0.70:1.46:0.26
0.71:1.43:0.26 0.72:1.40:0.25 0.73:1.37:0.25 0.74:1.34:0.24 0.75:1.30:0.23 0.76:1.27:0.23 0.77:1.23:0.22
0.78:1.19:0.21 0.79:1.15:0.21 0.80:1.11:0.20 0.81:1.07:0.19 0.82:1.03:0.18 0.83:0.98:0.18 0.84:0.93:0.17
0.85:0.89:0.16 0.86:0.84:0.15 0.87:0.79:0.14 0.88:0.73:0.13 0.89:0.68:0.12 0.90:0.63:0.11 0.91:0.57:0.10
0.92:0.51:0.09 0.93:0.45:0.08 0.94:0.39:0.07 0.95:0.33:0.06 0.96:0.27:0.05 0.97:0.20:0.04 0.98:0.14:0.02
0.99:0.07:0.01
"""
TABLE = [tuple(D(x) for x in cell.split(":")) for cell in PUBLISHED_100_LOT.split()]


# ---------------------------------------------------------------- documented arithmetic


def test_the_published_table_is_reproduced_by_bankers_rounding():
    assert len(TABLE) == 99
    for price, taker, maker in TABLE:
        assert bankers_fee(TAKER, 100, price) == taker, price
        assert bankers_fee(MAKER, 100, price) == maker, price


@pytest.mark.parametrize("price,taker,maker", [
    ("0.10", "6.26", "1.12"),  # Example 1: 6.255 -> 6.26 (half to even, up); 1.125 -> 1.12 (down)
    ("0.65", "15.81", "2.84"),  # Example 2
    ("0.30", "14.60", "2.62"),  # Example 3: 14.595 -> 14.60
    ("0.90", "6.26", "1.12"),  # Example 4
    ("0.50", "17.38", "3.12"),  # Example 5: 17.375 -> 17.38; 3.125 -> 3.12
])
def test_documented_1000_lot_examples(price, taker, maker):
    assert bankers_fee(TAKER, 1000, D(price)) == D(taker)
    assert bankers_fee(MAKER, 1000, D(price)) == D(maker)


def test_bankers_rounding_edge_cases_from_the_faq():
    # "$0.025 rounds to $0.02 ... $0.035 rounds to $0.04": exact halves go to the even cent.
    assert D("0.025").quantize(D("0.01"), rounding="ROUND_HALF_EVEN") == D("0.02")
    assert bankers_fee(D("0.1"), 1, D("0.5")) == D("0.02")  # exact 0.025
    assert bankers_fee(D("0.14"), 1, D("0.5")) == D("0.04")  # exact 0.035
    assert bankers_fee(TAKER, 1, D("0.01")) == D("0.00")  # "the fee can round down to $0.00"


def test_schedule_rounds_each_take_up_and_is_never_below_the_documented_fee():
    rng = random.Random(27)
    for _ in range(2000):
        contracts = rng.randint(1, 5000)
        price = D(rng.randint(1, 9999)) / 10000
        quote = PM.taker_buy(contracts, price)
        exact = TAKER * contracts * max(min(price, D("0.99")), D("0.01")) * (1 - max(min(price, D("0.99")), D("0.01")))
        assert quote.fee == exact.quantize(D("0.01"), rounding=ROUND_CEILING)
        if D("0.01") <= price <= D("0.99"):
            assert quote.fee >= bankers_fee(TAKER, contracts, price)
        assert quote.total_cost == (price * contracts + quote.fee).quantize(D("0.01"), rounding=ROUND_CEILING)
        assert quote.total_cost >= price * contracts + quote.fee
        assert quote.cost_per_contract == quote.total_cost / contracts


def test_half_cent_edge_the_bound_is_one_cent_above_bankers_rounding():
    # 1.125 exact: the venue charges 1.12, the conservative schedule 1.13.
    assert bankers_fee(MAKER, 1000, D("0.10")) == D("1.12")
    assert PM.taker_buy(1000, D("0.10")).fee == D("6.26")  # 6.255 -> ceil 6.26 = banker's here
    assert PM.taker_buy(1000, D("0.50")).fee == D("17.38")  # 17.375: both 17.38
    assert PM.taker_buy(1000, D("0.65")).fee == D("15.82")  # 15.81125: banker's 15.81, bound 15.82


def test_any_split_of_an_order_is_bounded_by_the_per_take_ceiling():
    """The venue caps an order's fee at the banker's rounding of its cumulative exact fee. The
    schedule's per-take ceilings always sum to at least that, whatever the split."""
    rng = random.Random(2027)
    for _ in range(500):
        takes = [(rng.randint(1, 300), D(rng.randint(1, 99)) / 100) for _ in range(rng.randint(1, 8))]
        cumulative_exact = sum((TAKER * c * p * (1 - p) for c, p in takes), D(0))
        venue_cap = cumulative_exact.quantize(D("0.01"), rounding="ROUND_HALF_EVEN")
        assert sum(PM.taker_buy(c, p).fee for c, p in takes) >= venue_cap


def test_a_no_buy_costs_the_same_fee_as_the_mirrored_yes_sale():
    for price in (D("0.07"), D("0.35"), D("0.5"), D("0.81")):
        assert PM.taker_buy(40, price).fee == PM.taker_buy(40, 1 - price).fee


def test_outside_the_documented_price_range_the_fee_is_bounded_by_the_range_edge():
    assert PM.taker_buy(1000, D("0.005")).fee == PM.taker_buy(1000, D("0.01")).fee == D("0.69")
    assert PM.taker_buy(1000, D("0.9995")).fee == PM.taker_buy(1000, D("0.99")).fee


@pytest.mark.parametrize("contracts,price", [(0, D("0.5")), (-1, D("0.5")), (True, D("0.5")), (1, D("0")),
                                             (1, D("1")), (1, D("0.00001")), (1, D("NaN"))])
def test_invalid_inputs_raise(contracts, price):
    with pytest.raises(ValueError):
        PM.taker_buy(contracts, price)


# ---------------------------------------------------------------- scope and routing


def test_schedule_for_polymarket_us_needs_the_exchange_scope():
    assert schedule_for("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE) is PM
    for scope in (None, "", "feeCoefficient:0.07", "KXHIGHNY", "EXCHANGE"):
        s = schedule_for("polymarket_us", scope)
        assert isinstance(s, UnsupportedFeeSchedule) and s.status is FeeScheduleStatus.UNSUPPORTED
    assert isinstance(schedule_for("polymarket_international", POLYMARKET_US_EXCHANGE_SCOPE), UnsupportedFeeSchedule)
    assert schedule_for("kalshi", "KXHIGHNY") is KALSHI_QUADRATIC_TAKER_V1


def test_the_polymarket_schedule_never_prices_another_venue_and_is_not_pinnable():
    fill = walk_ladder(DepthLadder("kalshi", "kalshi:X", "YES", (DepthLevel(D("0.4"), D("5")),), False, None, None,
                                   None), 5)
    cost, why = price_depth_fill(fill, PM)
    assert cost is None and "prices polymarket_us, not kalshi" in why
    assert PM.schedule_id not in fee_schedules.FEE_SCHEDULES  # shadow accounts pin Kalshi only


# ---------------------------------------------------------------- point-in-time verification


def test_record_components_match_the_evidence():
    states = {c.component: c.state for c in RECORD.components}
    assert states == {
        VerificationComponent.COEFFICIENT: ComponentState.VERIFIED,
        VerificationComponent.SERIES_MULTIPLIER: ComponentState.VERIFIED,
        VerificationComponent.SCHEDULED_CHANGES: ComponentState.UNVERIFIED,
        VerificationComponent.ROUNDING_FOR_ACCOUNT_TYPE: ComponentState.VERIFIED,
        VerificationComponent.ACCOUNT_TYPE: ComponentState.UNVERIFIED,
        VerificationComponent.MAKER_FEES: ComponentState.VERIFIED,
    }
    assert RECORD.scope == (POLYMARKET_US_EXCHANGE_SCOPE,) and RECORD.schedule_id == PM.schedule_id
    assert parse_utc(RECORD.applies_from_utc) == datetime(2026, 9, 17, 4, tzinfo=UTC)  # 12 AM ET
    assert "polymarket_us_fees_2026-09-24.md" in PM.evidence


def test_before_the_record_only_the_base_status_applies():
    before = verification_at(PM, KNOWN - timedelta(seconds=1), "any-slug")
    assert before.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE and before.verification_id is None
    assert not before.claimable


def test_after_the_record_the_schedule_is_partially_verified_but_supports_no_claim():
    at = verification_at(PM, KNOWN, "any-slug")
    assert at.status is FeeScheduleStatus.PARTIALLY_VERIFIED
    assert at.claim_basis is ClaimBasis.NONE and not at.claimable
    assert at.verification_id == RECORD.verification_id
    assert "SCHEDULED_CHANGES" in at.detail and "ACCOUNT_TYPE" in at.detail
    assert claim_adjusted_net(D("1"), 10, at) is None


def test_trades_before_the_effective_date_are_not_covered_and_the_record_goes_stale():
    assert restated_verification(PM, datetime(2026, 9, 17, 3, 59, tzinfo=UTC), KNOWN, "s").verification_id is None
    assert restated_verification(PM, datetime(2026, 9, 17, 4, tzinfo=UTC), KNOWN, "s").verification_id \
        == RECORD.verification_id
    recheck = parse_utc(RECORD.recheck_by_utc)
    late = verification_at(PM, recheck + timedelta(seconds=1), "s")
    assert late.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE and not late.claimable
    assert RECORD.verification_id in recheck_due(recheck + timedelta(seconds=1))
    assert RECORD.verification_id not in recheck_due(recheck)


def test_kalshi_verification_is_unchanged_by_the_new_record():
    kalshi = verification_at(KALSHI_QUADRATIC_TAKER_V1, KNOWN, "KXHIGHNY-26SEP24-B69.5")
    assert kalshi.claim_basis is ClaimBasis.CONSERVATIVE_BOUND
    assert kalshi.verification_id == "kalshi-kxhighny-fee-verification-2026-09-23"
    assert kalshi.rounding_allowance_per_contract == D("0.0101")
