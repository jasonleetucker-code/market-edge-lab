"""Maker-fee path (Track B, #184): priced only where a primary source in the repo documents it."""

from decimal import Decimal as D

import pytest

from edge_lab.fee_schedules import POLYMARKET_US_EXCHANGE_SCOPE, MakerFeeState, maker_fee

AT = "2026-10-01T00:00:00Z"


def test_kalshi_kxhighny_maker_fee_is_verified_zero_inside_the_record():
    q = maker_fee("kalshi", "KXHIGHNY", 10, D("0.40"), as_of=AT)
    assert q.state == MakerFeeState.VERIFIED_ZERO.value
    assert (q.fee, q.rebate, q.notional, q.unsubsidized_cost, q.cost_after_rebate) == (
        D(0), D(0), D("4.00"), D("4.00"), D("4.00"))
    assert q.verification_id == "kalshi-kxhighny-fee-verification-2026-09-23"
    assert q.claim_basis == "CONSERVATIVE_BOUND"
    assert "p.2" in q.evidence


def test_polymarket_us_rebate_is_bankers_rounded_and_kept_on_its_own_line():
    # 0.0125 x 1000 x 0.5 x 0.5 = 3.125 -> banker's rounding to the cent = 3.12
    q = maker_fee("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE, 1000, D("0.50"), as_of=AT)
    assert q.state == MakerFeeState.DOCUMENTED_REBATE.value
    assert q.fee == D(0) and q.rebate == D("3.12")
    assert q.unsubsidized_cost == D("500.00")  # never netted
    assert q.cost_after_rebate == D("496.88")
    assert q.claim_basis == "NONE"  # the record supports no claim


@pytest.mark.parametrize("venue,scope", [
    ("kalshi", "KXNFLGAME"),  # non-standard series
    ("kalshi", "KXHIGHCHI"),  # general series: PDF default conflicts with the 2026-08-20 changelog
    ("kalshi", "KXNHLGAME"),  # not proven standard
    ("novig", None),
    ("polymarket_us", "SOME_OTHER_THETA"),
])
def test_every_scope_without_a_verified_maker_record_is_fee_unsupported(venue, scope):
    q = maker_fee(venue, scope, 10, D("0.40"), as_of=AT)
    assert q.state == MakerFeeState.FEE_UNSUPPORTED.value
    assert (q.fee, q.rebate, q.unsubsidized_cost, q.cost_after_rebate) == (None, None, None, None)
    assert q.claim_basis == "NONE" and q.detail


def test_maker_record_is_point_in_time_and_expires_at_its_recheck():
    before = maker_fee("kalshi", "KXHIGHNY", 10, D("0.40"), as_of="2026-09-23T13:00:00Z")  # before knowledge time
    after = maker_fee("kalshi", "KXHIGHNY", 10, D("0.40"), as_of="2026-10-23T13:39:49Z")  # past re-check
    assert before.state == after.state == MakerFeeState.FEE_UNSUPPORTED.value
    assert "re-check" in after.detail


def test_fractional_fill_and_out_of_range_price_are_unsupported():
    assert maker_fee("kalshi", "KXHIGHNY", D("2.5"), D("0.40"), as_of=AT).state == "FEE_UNSUPPORTED"
    q = maker_fee("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE, 10, D("0.995"), as_of=AT)
    assert q.state == "FEE_UNSUPPORTED" and "range" in q.detail


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        maker_fee("kalshi", "KXHIGHNY", 0, D("0.40"), as_of=AT)
    with pytest.raises(ValueError):
        maker_fee("kalshi", "KXHIGHNY", 1, D("1.00"), as_of=AT)
    with pytest.raises(ValueError):
        maker_fee("kalshi", "KXHIGHNY", 1, D("0.40"), as_of="2026-10-01")
