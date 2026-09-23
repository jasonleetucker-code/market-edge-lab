"""Deterministic position sizing (Gate 6 foundation for issue #6). Simulation only.

`suggest_position_size` turns a conservative probability and an executable price into a
contract count. Explicit hard caps bound it, and every cap always overrides the sizing
rule, fractional Kelly included. The result records each stage:

    raw_size → risk_adjusted_size → liquidity_capped_size → final_size (+ binding_constraint)

so a size can always be explained from its inputs. Nothing here reads a balance from a
venue, and nothing places an order.

Money model: a long binary contract bought at all-in cost c per contract loses at most c
and pays 1. The worst-case risk of n contracts is therefore their total cash cost. The
exact cost comes from the fee schedule, cent alignment included.

`bankroll` is equity at cost basis: settled cash plus the cost of open positions. Settled
cash is therefore `bankroll - total_open_risk`, and cash spending is capped at
`bankroll - total_open_risk - reserve`.

The Kelly fraction is a policy input. Nothing here fits it to historical profitability.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from .fee_schedules import valid_price
from .opportunity import FeeSchedule

# Tie-break order for the binding constraint: the first one whose limit equals the final size.
CONSTRAINT_ORDER = (
    "SIZING_RULE", "MAX_POSITION_CONTRACTS", "MAX_POSITION_RISK", "MAX_EVENT_RISK",
    "MAX_CLUSTER_RISK", "MAX_PORTFOLIO_RISK", "RESERVE", "LIQUIDITY", "EXACT_COST",
)


@dataclass(frozen=True)
class SizingPolicy:
    policy_id: str
    fixed_contracts: int | None  # size rule A: a fixed count (EXP-001 Stage B: 1)
    kelly_fraction: Decimal | None  # size rule B: fraction of the full-Kelly stake, in (0, 1]
    max_position_contracts: int
    max_position_risk: Decimal  # $ worst-case loss of one position
    max_event_risk: Decimal  # $ across all positions on one event
    max_cluster_risk: Decimal  # $ across one outcome cluster
    max_portfolio_risk: Decimal  # $ total open worst-case risk
    reserve: Decimal  # $ of settled cash never committed

    def __post_init__(self) -> None:
        if (self.fixed_contracts is None) == (self.kelly_fraction is None):
            raise ValueError("exactly one of fixed_contracts and kelly_fraction must be set")
        if self.fixed_contracts is not None and self.fixed_contracts <= 0:
            raise ValueError("fixed_contracts must be positive")
        if self.kelly_fraction is not None and not (Decimal(0) < self.kelly_fraction <= Decimal(1)):
            raise ValueError("kelly_fraction must be in (0, 1]")
        if self.max_position_contracts < 0:
            raise ValueError("max_position_contracts must not be negative")
        for name in ("max_position_risk", "max_event_risk", "max_cluster_risk", "max_portfolio_risk", "reserve"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class SizingResult:
    raw_size: int
    risk_adjusted_size: int
    liquidity_capped_size: int
    final_size: int
    binding_constraint: str
    cost_per_contract: Decimal | None  # all-in cost of one contract
    total_cost: Decimal | None  # exact cash cost of final_size (0 contracts -> 0)
    full_kelly_fraction: Decimal | None
    limits: tuple[tuple[str, int], ...]
    policy_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_size": self.raw_size, "risk_adjusted_size": self.risk_adjusted_size,
            "liquidity_capped_size": self.liquidity_capped_size, "final_size": self.final_size,
            "binding_constraint": self.binding_constraint,
            "cost_per_contract": None if self.cost_per_contract is None else str(self.cost_per_contract),
            "total_cost": None if self.total_cost is None else str(self.total_cost),
            "full_kelly_fraction": None if self.full_kelly_fraction is None else str(self.full_kelly_fraction),
            "limits": [[n, v] for n, v in self.limits], "policy_id": self.policy_id,
        }


def _contracts(dollars: Decimal, per_contract: Decimal) -> int:
    if dollars <= 0:
        return 0
    return int((dollars / per_contract).to_integral_value(rounding=ROUND_FLOOR))


def _zero(policy: SizingPolicy, why: str) -> SizingResult:
    return SizingResult(0, 0, 0, 0, why, None, None, None, (), policy.policy_id)


def suggest_position_size(
    *,
    bankroll: Decimal,
    conservative_probability: Decimal | None,
    executable_price: Decimal | None,
    fees: FeeSchedule,
    available_size: Decimal | None,
    event_exposure: Decimal,
    cluster_exposure: Decimal,
    total_open_risk: Decimal,
    policy: SizingPolicy,
) -> SizingResult:
    """Contracts to buy at `executable_price`. Zero means no position, and says why.

    Unknown inputs (None) give zero with `binding_constraint = INPUT_MISSING`, never a
    guessed size.
    """
    if conservative_probability is None or executable_price is None or available_size is None:
        return _zero(policy, "INPUT_MISSING")
    if not valid_price(executable_price):
        return _zero(policy, "INVALID_PRICE")
    for value in (bankroll, event_exposure, cluster_exposure, total_open_risk):
        if value < 0:
            raise ValueError("bankroll and exposures must not be negative")
    if not (Decimal(0) <= conservative_probability <= Decimal(1)):
        raise ValueError("conservative_probability must be in [0, 1]")

    c = fees.taker_buy(1, executable_price).cost_per_contract
    if c >= 1:
        return _zero(policy, "COST_AT_OR_ABOVE_PAYOUT")

    # Rule: fixed count, or fractional Kelly on the conservative probability. For a binary
    # contract costing c and paying 1, full Kelly is f* = (p - c) / (1 - c) of bankroll.
    full_kelly = None
    if policy.kelly_fraction is not None:
        full_kelly = max(Decimal(0), (conservative_probability - c) / (1 - c))
        raw = _contracts(policy.kelly_fraction * full_kelly * bankroll, c)
    else:
        raw = int(policy.fixed_contracts)

    limits = [
        ("SIZING_RULE", raw),
        ("MAX_POSITION_CONTRACTS", policy.max_position_contracts),
        ("MAX_POSITION_RISK", _contracts(policy.max_position_risk, c)),
        ("MAX_EVENT_RISK", _contracts(policy.max_event_risk - event_exposure, c)),
        ("MAX_CLUSTER_RISK", _contracts(policy.max_cluster_risk - cluster_exposure, c)),
        ("MAX_PORTFOLIO_RISK", _contracts(policy.max_portfolio_risk - total_open_risk, c)),
        ("RESERVE", _contracts(bankroll - total_open_risk - policy.reserve, c)),
    ]
    risk_adjusted = min(v for _, v in limits)
    liquidity = _contracts(available_size, Decimal(1))
    limits.append(("LIQUIDITY", liquidity))
    capped = min(risk_adjusted, liquidity)

    # c is an upper bound on the per-contract cost at any size (cent alignment rounds the
    # total, not each contract), but the dollar caps are rechecked against the exact cost.
    final = capped
    while final > 0 and not _within_dollar_caps(fees.taker_buy(final, executable_price).total_cost, bankroll,
                                                event_exposure, cluster_exposure, total_open_risk, policy):
        final -= 1
    if final < capped:
        limits.append(("EXACT_COST", final))
    binding = next(name for name, value in limits if value == final) if limits else "SIZING_RULE"
    if final == 0 and raw == 0:
        # Kelly gives zero either because there is no edge or because the bankroll is too
        # small for one contract; only the first is NO_EDGE.
        no_edge = policy.kelly_fraction is not None and full_kelly == 0
        binding = "NO_EDGE" if no_edge else "SIZING_RULE"
    total = fees.taker_buy(final, executable_price).total_cost if final > 0 else Decimal(0)
    return SizingResult(raw, risk_adjusted, capped, final, binding, c, total, full_kelly, tuple(limits),
                        policy.policy_id)


def _within_dollar_caps(cost: Decimal, bankroll: Decimal, event_exposure: Decimal, cluster_exposure: Decimal,
                        total_open_risk: Decimal, policy: SizingPolicy) -> bool:
    return (cost <= policy.max_position_risk
            and event_exposure + cost <= policy.max_event_risk
            and cluster_exposure + cost <= policy.max_cluster_risk
            and total_open_risk + cost <= policy.max_portfolio_risk
            and total_open_risk + cost <= bankroll - policy.reserve)
