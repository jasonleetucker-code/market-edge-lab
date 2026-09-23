"""Versioned venue fee schedules for the opportunity engine (Gate 5).

A fee schedule is data plus a deterministic cost function. Schedules are replaced by
adding a new `schedule_id`, never by editing an existing one, so every opportunity
names the exact schedule that priced it.

`status` states whether the schedule's coefficients were verified against a primary,
current venue source. An `UNVERIFIED_CURRENT_SCHEDULE` schedule may price research
opportunities, but no net-profitability claim may rest on it (`Opportunity.claimable`).

Nothing here places orders; costs are computed for simulation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum

from . import fees

SIX_DP = Decimal("0.000001")
CENT = Decimal("0.01")
PRICE_GRID = Decimal("0.0001")


class FeeScheduleStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED_CURRENT_SCHEDULE = "UNVERIFIED_CURRENT_SCHEDULE"


@dataclass(frozen=True)
class FeeQuote:
    """The cost of buying `contracts` at `price` under one schedule (taker, no rebates)."""

    schedule_id: str
    status: FeeScheduleStatus
    contracts: int
    price: Decimal
    fee: Decimal  # trade fee for the whole quantity
    total_cost: Decimal  # cash that leaves the balance, fee included
    cost_per_contract: Decimal


def valid_price(price: Decimal) -> bool:
    """A binary-contract price strictly inside (0, 1) on the 1/100-cent grid."""
    return Decimal("0") < price < Decimal("1") and price == price.quantize(PRICE_GRID)


@dataclass(frozen=True)
class QuadraticTakerSchedule:
    """Kalshi-style quadratic taker fee.

    model fee = multiplier * coefficient * C * P * (1 - P); trade fee = ceil to $0.000001;
    cash change = floor to the cent of (-P*C - trade fee) (non-direct member). Taker only:
    no maker fills, rebates or rounding refunds are assumed (they can only lower cost).
    """

    schedule_id: str
    venue: str
    coefficient: Decimal
    multiplier: Decimal
    status: FeeScheduleStatus
    evidence: str
    checked_at_utc: str

    def taker_buy(self, contracts: int, price: Decimal) -> FeeQuote:
        if not isinstance(contracts, int) or isinstance(contracts, bool) or contracts <= 0:
            raise ValueError("contracts must be a positive integer")
        p = Decimal(str(price))
        if not valid_price(p):
            raise ValueError(f"{p} is not a valid binary-contract price")
        model_fee = self.multiplier * self.coefficient * contracts * p * (1 - p)
        trade_fee = model_fee.quantize(SIX_DP, rounding=ROUND_CEILING)
        aligned = (-(p * contracts) - trade_fee).quantize(CENT, rounding=ROUND_FLOOR)
        total = -aligned
        return FeeQuote(self.schedule_id, self.status, contracts, p, trade_fee, total, total / contracts)


# The EXP-001 frozen fee model (src/edge_lab/fees.py, hash-pinned). Re-checked 2026-09-23
# 02:20 UTC: the public API reports KXHIGHNY fee_type "quadratic", fee_multiplier 1 and no
# scheduled fee changes; docs.kalshi.com "Fee Rounding" confirms the rounding. The 0.07
# coefficient could not be read from a primary source (the fee-schedule PDF and fee pages
# answered HTTP 429 to automated requests), so the schedule stays UNVERIFIED.
KALSHI_QUADRATIC_TAKER_V1 = QuadraticTakerSchedule(
    schedule_id="kalshi-quadratic-taker-v1",
    venue="kalshi",
    coefficient=fees.QUADRATIC_TAKER_COEFFICIENT,
    multiplier=Decimal("1"),
    status=FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE,
    evidence=(
        "experiments/EXP-001-kxhighny-nws-vs-market/gate3/evidence/kalshi_docs_fee_rounding.html "
        "(0.07 worked example, captured 2026-09-22); KXHIGHNY series fee_type=quadratic, "
        "fee_multiplier=1 (API, 2026-09-23T02:20Z); /series/fee_changes empty; fee-schedule PDF "
        "not retrievable (HTTP 429)"
    ),
    checked_at_utc="2026-09-23T02:20:00Z",
)

FEE_SCHEDULES: dict[str, QuadraticTakerSchedule] = {
    KALSHI_QUADRATIC_TAKER_V1.schedule_id: KALSHI_QUADRATIC_TAKER_V1,
}


def get_fee_schedule(schedule_id: str) -> QuadraticTakerSchedule:
    try:
        return FEE_SCHEDULES[schedule_id]
    except KeyError:
        raise KeyError(f"unknown fee schedule {schedule_id!r}") from None
