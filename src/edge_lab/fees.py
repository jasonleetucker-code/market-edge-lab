"""Kalshi trading-fee model (deterministic, Decimal-exact). Specification only: nothing
here places orders.

Evidence (experiments/EXP-001-kxhighny-nws-vs-market/gate3/evidence/):
- Series KXHIGHNY: `fee_type: "quadratic"`, `fee_multiplier: 1` (API snapshot).
- docs.kalshi.com "Fee Rounding" (captured 2026-09-22):
  - trade_fee = ceil_6dp(model_fee);
  - aligned_change = floor_precision(revenue - trade_fee), where precision is $0.01 for
    non-direct members;
  - worked example: a model fee of $0.00363825 for 1 contract at $0.055, which is
    0.07 x 1 x 0.055 x 0.945, i.e. the quadratic coefficient 0.07.
- The full fee schedule PDF (kalshi.com/docs/kalshi-fee-schedule.pdf) sits behind a
  Vercel bot checkpoint and was NOT retrieved. The 0.07 coefficient is taken from the
  documented worked example, and must be re-verified against the schedule before any
  Stage B trade.

Conservative choices: taker only (no maker fills or rebates assumed); the non-direct
member $0.01 balance precision; rounding rebates from the fee accumulator ignored (they
can only lower cost).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

QUADRATIC_TAKER_COEFFICIENT = Decimal("0.07")
SIX_DP = Decimal("0.000001")
CENT = Decimal("0.01")
FEE_MODEL_VERSION = "1"


def _price(price: Decimal | str) -> Decimal:
    p = Decimal(str(price))
    if not (Decimal("0") < p < Decimal("1")):
        raise ValueError(f"contract price must be strictly between 0 and 1 dollars, got {p}")
    if p != p.quantize(Decimal("0.0001")):
        raise ValueError(f"price {p} finer than 1/100 cent is not a Kalshi price")
    return p


def model_fee(contracts: int, price: Decimal | str, multiplier: Decimal | str | int = 1) -> Decimal:
    """Quadratic taker model fee in dollars, before rounding."""
    if contracts <= 0:
        raise ValueError("contracts must be positive")
    p = _price(price)
    return Decimal(str(multiplier)) * QUADRATIC_TAKER_COEFFICIENT * contracts * p * (1 - p)


def taker_trade_fee(contracts: int, price: Decimal | str, multiplier: Decimal | str | int = 1) -> Decimal:
    """Trade fee: model fee rounded up to $0.000001 (docs: ceil_6dp)."""
    return model_fee(contracts, price, multiplier).quantize(SIX_DP, rounding=ROUND_CEILING)


def taker_buy_cost(contracts: int, price: Decimal | str, multiplier: Decimal | str | int = 1) -> Decimal:
    """Total cash leaving a non-direct member's balance for a taker buy (conservative).

    The balance change is floor_cent(revenue - trade_fee) with revenue = -(price x qty);
    no rebate is assumed. Returned as a positive dollar amount.
    """
    p = _price(price)
    revenue = -(p * contracts)
    aligned = (revenue - taker_trade_fee(contracts, p, multiplier)).quantize(CENT, rounding=ROUND_FLOOR)
    return -aligned


def cost_per_contract(contracts: int, price: Decimal | str, multiplier: Decimal | str | int = 1) -> Decimal:
    return taker_buy_cost(contracts, price, multiplier) / contracts
