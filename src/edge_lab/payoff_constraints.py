"""Pure same-venue payoff-constraint evaluator (Family B, EXP-003; Economic Evidence v1 PR B).

The canonical owner of "does this allowlisted set of same-venue contracts have a proven payoff
relationship, and what is its worst-state full-fill surplus after costs at each size?". It is
not an optimizer and not an execution path. It reuses the opportunity contracts (`Event`,
`Market`, `DepthLadder`, `walk_ladder`, `price_depth_fill`), the fee schedules and their
point-in-time verification, and the semantic-conformance units.

**Allowlist:** verified complements, mutually exclusive and exhaustive partitions, and verified
nested thresholds. Nonnegative long legs only. Selling, shorting and collateral are refused.

**States.** Every admissible settlement state is enumerated, including tie, void, refund,
cancellation, correction and fallback states, or proven excluded with evidence
(`StateProof`). A state's payout per leg may depend on a discretionary value
(`Variable`, for example Kalshi's "last fair price" fallback). The worst case takes each
variable at its worst bound.

**Formula** (strategy record section 7, corrected), for nonnegative basket quantity q and leg
fill paths `fill_i` (levels, prices and fees):

    worst_state_surplus = min_s( sum_i( q_i*payout_i(s) - settlement_cost_i(s, fill_i)
                                        + refund_i(s, fill_i) ) - basket_settlement_cost(s, fill) )
                          - sum_i(acquisition_cost_i(fill_i)) - state_independent_costs

- Void and refund cells hold only the non-refund payout. A returned price or a reversed fee
  appears once, in `refund_i`.
- Fees enter once, inside `acquisition_cost_i`, rounded per fill (the schedule's scope).

**Outputs are kept distinct:**
- the mathematical relationship (PROVEN / INCOMPLETE / UNSUPPORTED);
- the observed quote inconsistency (top of book, pre-fee, normal states only; never a surplus);
- the conditional full-fill surplus per size;
- simulated execution: NOT MODELLED, and legs are never assumed atomic;
- the actual result: none. There are no actual fills.

Orphan-leg exposure (each leg filling alone) is always reported.

**Soundness rule.** A minimum over a subset of admissible states is an upper bound on the true
minimum. So a non-positive worst state over the known states proves "no surplus" even when the
proof is INCOMPLETE. A positive surplus is claimable only from a PROVEN, fully costed set, and
never from a partial one.

Pure, deterministic, stdlib-only and network-free. It never reads EXP-001 forecasts, outcomes
or the ledger.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from .fee_schedules import ClaimBasis, claim_adjusted_net, verification_at
from .freshness import parse_utc
from .opportunity import (
    DepthCost, DepthLadder, DepthStatus, Event, FeeSchedule, Market, UnitSemantics, price_depth_fill, walk_ladder,
)
from .provenance import canonical_json, sha256_hex

PAYOFF_VERSION = "payoff-constraints-v1"
SIMULATED_EXECUTION = "NOT_MODELLED: no leg-timing or fill-probability model; legs are never assumed atomic"
ACTUAL_RESULT = "NONE: no actual fills exist (no orders are placed or simulated against a venue)"
ONE = Decimal(1)
ZERO = Decimal(0)


class RelationKind(str, Enum):
    COMPLEMENT = "COMPLEMENT"
    PARTITION = "PARTITION"
    NESTED_THRESHOLD = "NESTED_THRESHOLD"


ALLOWLIST = frozenset(RelationKind)


class StateKind(str, Enum):
    NORMAL = "NORMAL"
    TIE = "TIE"
    VOID = "VOID"
    REFUND = "REFUND"
    CANCELLATION = "CANCELLATION"
    CORRECTION = "CORRECTION"
    FALLBACK = "FALLBACK"


# Every non-normal kind must be either enumerated as a state or excluded with evidence.
ABNORMAL_KINDS = tuple(k for k in StateKind if k is not StateKind.NORMAL)


class Relationship(str, Enum):
    PROVEN = "PROVEN"
    INCOMPLETE = "INCOMPLETE"  # structure verified, but a state kind or a state's cash flow is unknown
    UNSUPPORTED = "UNSUPPORTED"  # outside the allowlist, or the structure/units/rules do not verify


class QuoteValidity(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"  # stale, future-dated, non-overlapping, unknown receipt time or malformed book


class Claim(str, Enum):
    NO_SURPLUS_EVEN_BEFORE_FEES = "NO_SURPLUS_EVEN_BEFORE_FEES"  # robust: fees cannot rescue it
    NO_SURPLUS_AFTER_FEES = "NO_SURPLUS_AFTER_FEES"  # fees (as modelled) erase the surplus
    CONDITIONAL_FULL_FILL_SURPLUS = "CONDITIONAL_FULL_FILL_SURPLUS"  # proven, costed; still not captured arbitrage
    SURPLUS_NOT_CLAIMABLE = "SURPLUS_NOT_CLAIMABLE"  # positive but incomplete proof, unknown costs or fees
    NOT_EVALUATED = "NOT_EVALUATED"  # depth limited, unknown or unpriceable at this size


@dataclass(frozen=True)
class Variable:
    """A discretionary settlement value within [low, high] (for example a fair price)."""

    name: str
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        for bound in (self.low, self.high):
            if not isinstance(bound, Decimal) or not bound.is_finite():
                raise ValueError(f"variable {self.name}: bounds must be finite Decimals")
        if self.low > self.high:
            raise ValueError(f"variable {self.name}: low {self.low} > high {self.high}")


@dataclass(frozen=True)
class SettlementState:
    state_id: str
    kind: StateKind
    description: str
    variables: tuple[Variable, ...] = ()
    # The integer settlement value a NORMAL state stands for, set only by `integer_value_states`
    # (the verified enumerator). A NORMAL state without it cannot be checked against a contract.
    value: Decimal | None = None


@dataclass(frozen=True)
class Cell:
    """The non-refund payout of one native unit in one state, as a fraction of the full payout:
    constant + coefficient * variable."""

    constant: Decimal
    variable: str | None = None
    coefficient: Decimal = ZERO


@dataclass(frozen=True)
class StateProof:
    """Evidence that the enumerated states are all the admissible ones.

    `excluded_kinds` maps each abnormal kind that is not enumerated to the evidence that it
    cannot occur (or occurs only as one of the enumerated states). A kind neither enumerated
    nor excluded makes the proof INCOMPLETE."""

    excluded_kinds: Mapping[StateKind, str]
    evidence_hashes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()  # documented but UNVERIFIED premises; they block PROVEN
    # Evidence that the contract *guarantees* an integer settlement value. Without it, integer
    # settlement is only an observed premise (see INTEGER_SETTLEMENT_OBSERVED) and blocks PROVEN.
    integer_settlement_guarantee: str | None = None


@dataclass(frozen=True)
class NumericContract:
    """A threshold/bracket contract on one numeric settlement value, with explicit inclusivity."""

    kind: str  # "greater" | "less" | "between"
    floor: Decimal | None
    cap: Decimal | None
    low_inclusive: bool | None
    high_inclusive: bool | None

    def pays(self, value: Decimal) -> bool:
        if self.kind == "greater":
            return value > self.floor if not self.low_inclusive else value >= self.floor
        if self.kind == "less":
            return value < self.cap if not self.high_inclusive else value <= self.cap
        lo_ok = value >= self.floor if self.low_inclusive else value > self.floor
        hi_ok = value <= self.cap if self.high_inclusive else value < self.cap
        return lo_ok and hi_ok


# docs/SETTLEMENT.md section 3 (Kalshi GLOBALTEMPERATURE / NHIGH): greater is strict, less is
# strict, between is inclusive at both ends.
VERIFIED_STRIKE_SEMANTICS: dict[str, dict[str, tuple[bool | None, bool | None]]] = {
    "kalshi": {"greater": (False, None), "less": (None, False), "between": (True, True)},
}


# Series whose markets are integer-strike brackets with the Kalshi strike semantics above and whose
# settlement value has been OBSERVED to be a whole number. Integer enumeration of states is
# considered only for these; any other series is refused, not guessed. Observed is not guaranteed:
# the rules settle on "the full precision reported by the Source Agency", The Weather Company is
# named since 2026-08-14 and its precision has never been observed, and settlement.resolve treats
# a non-integer value as unverified. So the premise is an explicit assumption that blocks PROVEN
# unless a proof supplies `integer_settlement_guarantee`.
INTEGER_SETTLEMENT_OBSERVED: dict[str, str] = {
    "KXHIGHNY": "integer settlement observed, not guaranteed (TWC precision unverified): 39 of 39 TWC-era "
                "expiration values equal the whole-degree NWS CLI value (docs/SETTLEMENT.md sections 2 and 7); the "
                "rules settle on the Source Agency's full precision",
}
VERIFIED_INTEGER_SERIES = frozenset(INTEGER_SETTLEMENT_OBSERVED)


def integer_settlement_series(leg_venue: str, native_id: str) -> str | None:
    """The leg's series when it is a verified integer-settlement series, else None."""
    series = native_id.split("-", 1)[0] if native_id else ""
    return series if leg_venue == "kalshi" and series in VERIFIED_INTEGER_SERIES else None


def numeric_contract(kind: str, floor: Any, cap: Any, *, venue: str = "kalshi") -> NumericContract:
    """A contract with the venue's verified inclusivity (UNKNOWN inclusivity for other venues)."""
    lo_inc, hi_inc = VERIFIED_STRIKE_SEMANTICS.get(venue, {}).get(kind, (None, None))
    floor_d = None if floor is None else Decimal(str(floor))
    cap_d = None if cap is None else Decimal(str(cap))
    return NumericContract(kind, floor_d, cap_d, lo_inc, hi_inc)


RefundFn = Callable[[str, DepthCost], "Decimal | None"]
CostFn = Callable[[str, DepthCost], "Decimal | None"]
BasketCostFn = Callable[[str, "tuple[DepthCost, ...]"], "Decimal | None"]


def refund_none(state_id: str, fill: DepthCost) -> Decimal:
    return ZERO


def refund_purchase_price(state_id: str, fill: DepthCost) -> Decimal:
    """The gross purchase price comes back; fees do not."""
    return fill.fill.gross_cost


def refund_price_and_fees(state_id: str, fill: DepthCost) -> Decimal:
    """The full cash paid (price and fees) comes back."""
    return fill.total_cost


def zero_cost(state_id: str, fill: DepthCost) -> Decimal:
    return ZERO


@dataclass(frozen=True)
class Leg:
    event: Event
    market: Market
    side: str  # "YES" | "NO"; always bought (long)
    ladder: DepthLadder  # the captured ask ladder for `side`
    fee_schedule: FeeSchedule
    units: UnitSemantics
    payouts: Mapping[str, Cell]  # state_id -> cell
    ratio: Decimal = ONE  # native units per basket unit (> 0: long only)
    structured_contract: NumericContract | None = None  # from the venue's structured fields
    rules_contract: NumericContract | None = None  # read from the captured rules text
    refunds: Mapping[str, RefundFn] = field(default_factory=dict)  # state_id -> refund rule
    settlement_cost: CostFn | None = None  # None = UNKNOWN settlement/transfer cost


@dataclass(frozen=True)
class RelationshipSet:
    set_id: str
    kind: str
    legs: tuple[Leg, ...]
    states: tuple[SettlementState, ...]
    proof: StateProof
    basket_settlement_cost: BasketCostFn | None = None  # None = UNKNOWN (zero only with evidence)
    state_independent_costs: Decimal = ZERO


@dataclass(frozen=True)
class LegFill:
    market_id: str
    side: str
    requested: Decimal
    status: str
    available: Decimal | None
    gross_cost: Decimal | None
    fee: Decimal | None
    total_cost: Decimal | None
    limit_price: Decimal | None
    detail: str


@dataclass(frozen=True)
class SizeResult:
    basket_quantity: Decimal
    evaluated: bool
    limiting_leg: str | None  # the leg with the least captured depth per basket unit
    leg_fills: tuple[LegFill, ...]
    acquisition_cost: Decimal | None  # all legs, price + fees (cash that leaves the balance)
    acquisition_gross: Decimal | None  # price only
    fees: Decimal | None  # cash paid beyond the gross price: fees plus the venue's cash rounding
    min_full_fill_payout: Decimal | None  # before any cost, worst state
    worst_state: str | None
    worst_state_surplus: Decimal | None  # after all costs; None when a cost is UNKNOWN
    worst_state_surplus_before_fees: Decimal | None
    upper_bound_if_unknown_settlement_costs_zero: Decimal | None
    claim_adjusted_surplus: Decimal | None  # fee claim basis applied (ADR 0017); None = not claimable
    capital_lockup: Decimal | None  # cash committed until settlement
    lockup_until_expected_utc: str | None
    lockup_until_latest_utc: str | None
    orphan_exposure: dict[str, Decimal | None]  # leg -> worst-state value minus its own cost if it fills alone
    states_evaluated: tuple[str, ...]
    states_skipped: tuple[str, ...]
    claim: str
    claim_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PayoffEvaluation:
    version: str
    set_id: str
    kind: str
    as_of_utc: str
    relationship: str
    relationship_reasons: tuple[str, ...]
    assumptions: tuple[str, ...]
    quote_validity: str
    quote_reasons: tuple[str, ...]
    leg_skew_seconds: Decimal | None
    observed_quote_inconsistency: Decimal | None
    observed_quote_inconsistency_note: str
    sizes: tuple[SizeResult, ...]
    simulated_execution: str = SIMULATED_EXECUTION
    actual_result: str = ACTUAL_RESULT
    evaluation_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


# --------------------------------------------------------------------------- state helpers


def integer_value_states(contracts: Iterable[NumericContract], *, prefix: str = "v") -> tuple[SettlementState, ...]:
    """NORMAL states for an integer-valued settlement (for example whole degrees F).

    Every integer between the smallest and largest strike (plus one below and one above) is
    its own state, and the two tails are represented by those end values. That is exact for
    integer outcomes, because each contract's payout only changes at its strikes. Callers
    must prove the settlement value is an integer (KXHIGHNY: docs/SETTLEMENT.md section 3)."""
    strikes = [s for c in contracts for s in (c.floor, c.cap) if s is not None]
    if not strikes:
        raise ValueError("no strikes to enumerate")
    low = int(min(strikes).to_integral_value(rounding="ROUND_FLOOR")) - 1
    high = int(max(strikes).to_integral_value(rounding="ROUND_CEILING")) + 1
    states = []
    for v in range(low, high + 1):
        label = f"<= {v}" if v == low else (f">= {v}" if v == high else f"= {v}")
        states.append(SettlementState(f"{prefix}{v}", StateKind.NORMAL, f"settlement value {label} (integer)",
                                      value=Decimal(v)))
    return tuple(states)


def state_value(state: SettlementState) -> Decimal:
    if state.value is None:
        raise ValueError(f"state {state.state_id} has no verified settlement value (use integer_value_states)")
    return state.value


def numeric_cells(contract: NumericContract, side: str, normal_states: Sequence[SettlementState]) -> dict[str, Cell]:
    """Cells of a numeric contract over integer NORMAL states (YES pays when the contract pays)."""
    cells = {}
    for state in normal_states:
        hit = contract.pays(state_value(state))
        yes = ONE if hit else ZERO
        cells[state.state_id] = Cell(yes if side == "YES" else ONE - yes)
    return cells


def fair_price_fallback(markets: Sequence[str], *, description: str) -> SettlementState:
    """A discretionary 'last fair price' state: each market settles at its own v in [0, 1]."""
    return SettlementState("fallback_fair_price", StateKind.FALLBACK, description,
                           tuple(Variable(f"v:{m}", ZERO, ONE) for m in markets))


def fallback_cell(market_id: str, side: str) -> Cell:
    """YES receives v. NO is assumed to receive 1 - v: an assumption, recorded in the proof."""
    if side == "YES":
        return Cell(ZERO, f"v:{market_id}", ONE)
    return Cell(ONE, f"v:{market_id}", -ONE)


# --------------------------------------------------------------------------- checks


def _structure(rel: RelationshipSet) -> tuple[list[str], list[str]]:
    """(unsupported reasons, incomplete reasons)."""
    unsupported: list[str] = []
    incomplete: list[str] = []
    legs = rel.legs
    if rel.kind not in {k.value for k in ALLOWLIST}:
        unsupported.append(f"relationship kind {rel.kind!r} is not on the allowlist")
    if len(legs) < 2:
        unsupported.append("a relationship needs at least two legs")
    if not legs:
        return unsupported, incomplete
    venues = {leg.market.venue for leg in legs} | {leg.ladder.venue for leg in legs}
    if len(venues) != 1:
        unsupported.append(f"legs span venues {sorted(venues)}: same-venue only")
    for leg in legs:
        name = f"{leg.market.market_id}/{leg.side}"
        if leg.side not in ("YES", "NO"):
            unsupported.append(f"{name}: unknown side")
        if not (isinstance(leg.ratio, Decimal) and leg.ratio > 0):
            unsupported.append(f"{name}: only nonnegative long legs with a positive ratio are supported")
        if leg.ladder.market_id != leg.market.market_id or leg.ladder.side != leg.side:
            unsupported.append(f"{name}: ladder is for {leg.ladder.market_id}/{leg.ladder.side}")
        if leg.market.event_id != leg.event.event_id:
            unsupported.append(f"{name}: market settles on {leg.market.event_id}, not {leg.event.event_id}")
        if not leg.market.rules_resolved or not leg.market.rules_sha256:
            unsupported.append(f"{name}: rules not captured or not resolved ({leg.market.rules_detail})")
        if leg.market.payoff.kind != "binary":
            unsupported.append(f"{name}: payoff kind {leg.market.payoff.kind!r} is not binary")
        if leg.structured_contract is not None or leg.rules_contract is not None:
            if leg.structured_contract != leg.rules_contract:
                unsupported.append(f"{name}: structured fields {leg.structured_contract} disagree with the captured "
                                   f"rules {leg.rules_contract}")
            verified = VERIFIED_STRIKE_SEMANTICS.get(leg.market.venue, {}).get(
                leg.structured_contract.kind if leg.structured_contract else "")
            if leg.structured_contract is not None and (
                    verified is None or verified != (leg.structured_contract.low_inclusive,
                                                     leg.structured_contract.high_inclusive)):
                unsupported.append(f"{name}: inclusivity {leg.structured_contract.low_inclusive}/"
                                   f"{leg.structured_contract.high_inclusive} is not the venue's verified "
                                   f"semantics {verified}")
    first = legs[0]
    for leg in legs[1:]:
        problem = first.units.incompatibility(leg.units)
        if problem:
            unsupported.append(f"{leg.market.market_id}: {problem} (explicit conversion is not supported in v1)")
    if not first.units.known:
        unsupported.append("native units UNKNOWN")
    elif first.units.payout_per_unit != ONE or first.units.price_convention != "USD_PER_CONTRACT":
        unsupported.append(f"native units {first.units.normalization_version} are not $1 contracts priced in USD; "
                           "v1 evaluates only USD_PER_CONTRACT contracts paying 1")
    events = {leg.event.event_id for leg in legs}
    identities = {leg.event.settlement_identity for leg in legs}
    if len(events) != 1 or len(identities) != 1:
        unsupported.append(f"legs settle on different events or settlement identities ({sorted(events)}; "
                           f"{sorted(identities)}): a changed station, window or rules breaks the relationship")
    keys = [(leg.market.market_id, leg.side) for leg in legs]
    if len(keys) != len(set(keys)):
        unsupported.append("duplicate synthetic liquidity: the same market side appears twice")
    books = [(leg.ladder.evidence_id, leg.ladder.market_id, leg.ladder.side) for leg in legs]
    if len(books) != len(set(books)):
        unsupported.append("duplicate synthetic liquidity: two legs read the same captured book side")

    if not (isinstance(rel.state_independent_costs, Decimal) and rel.state_independent_costs.is_finite()
            and rel.state_independent_costs >= 0):
        unsupported.append(f"INVALID: state_independent_costs {rel.state_independent_costs!r} must be a finite, "
                           "non-negative cost")
    state_ids = [s.state_id for s in rel.states]
    if len(state_ids) != len(set(state_ids)):
        unsupported.append("duplicate state ids")
    normal = [s for s in rel.states if s.kind is StateKind.NORMAL]
    if not normal:
        unsupported.append("no NORMAL settlement states")
    # Exhaustiveness is derived, never asserted: every leg needs a verified numeric contract, and the
    # NORMAL states must be exactly the verified integer enumeration of those contracts (tails
    # included). Every NORMAL cell must then equal what the contract pays in that state.
    contracts = [leg.structured_contract for leg in legs]
    # Integer enumeration is sound only when integer settlement is a proven premise for every leg:
    # the leg's series must be a verified integer-settlement series, and every strike an integer.
    for leg in legs:
        if integer_settlement_series(leg.market.venue, leg.market.native_id) is None:
            unsupported.append(f"{leg.market.market_id}: integer settlement is not proven for this series "
                               f"(verified: {sorted(VERIFIED_INTEGER_SERIES)}); states cannot be enumerated")
        c = leg.structured_contract
        if c is not None and any(s is not None and s != s.to_integral_value() for s in (c.floor, c.cap)):
            unsupported.append(f"{leg.market.market_id}: non-integer strike under integer settlement "
                               f"({c.floor}, {c.cap})")
    if any(c is None for c in contracts):
        unsupported.append("every leg needs a verified numeric contract: the NORMAL states and cells cannot be "
                           "derived or checked otherwise")
    else:
        try:
            expected = {s.value for s in integer_value_states(contracts)}
        except ValueError as exc:
            expected = None
            unsupported.append(f"cannot enumerate the NORMAL states: {exc}")
        given = [s.value for s in normal]
        if expected is not None and (None in given or set(given) != expected or len(given) != len(set(given))):
            missing = sorted(expected - {g for g in given if g is not None})
            unsupported.append(f"NORMAL states are not the verified integer enumeration of the legs' contracts "
                               f"(missing values {missing}); exhaustiveness is derived, never asserted")
        elif expected is not None:
            for leg in legs:
                for state in normal:
                    cell = leg.payouts.get(state.state_id)
                    if cell is None:
                        continue
                    hit = leg.structured_contract.pays(state.value)
                    want = (ONE if hit else ZERO) if leg.side == "YES" else (ZERO if hit else ONE)
                    if cell.variable is not None or cell.constant != want:
                        unsupported.append(f"{leg.market.market_id}/{leg.side}: cell {cell.constant} in "
                                           f"{state.state_id} is not what its contract pays ({want})")
    for kind in ABNORMAL_KINDS:
        present = any(s.kind is kind for s in rel.states)
        if not present and kind not in rel.proof.excluded_kinds:
            incomplete.append(f"state kind {kind.value} is neither enumerated nor excluded with evidence")
    if rel.proof.integer_settlement_guarantee is None:
        for series in sorted({integer_settlement_series(leg.market.venue, leg.market.native_id) for leg in legs}
                             - {None}):
            incomplete.append(f"relies on an OBSERVED premise ({series}): {INTEGER_SETTLEMENT_OBSERVED[series]}")
    for assumption in rel.proof.assumptions:
        incomplete.append(f"relies on an UNVERIFIED assumption: {assumption}")
    for state in rel.states:
        names = {v.name for v in state.variables}
        for leg in legs:
            cell = leg.payouts.get(state.state_id)
            if cell is None:
                incomplete.append(f"{leg.market.market_id}/{leg.side}: no payout for state {state.state_id}")
                continue
            if cell.variable is not None and cell.variable not in names:
                unsupported.append(f"{state.state_id}: cell uses undeclared variable {cell.variable}")
            if state.kind is StateKind.NORMAL and cell.variable is not None:
                unsupported.append(f"{state.state_id}: a NORMAL state cell must be constant")
            if state.kind in (StateKind.VOID, StateKind.REFUND, StateKind.CANCELLATION) and \
                    state.state_id not in leg.refunds:
                incomplete.append(f"{leg.market.market_id}/{leg.side}: refund rule for {state.state_id} UNKNOWN")
            if state.state_id in leg.refunds and (cell.constant != ZERO or cell.variable is not None):
                unsupported.append(f"INVALID: {leg.market.market_id}/{leg.side} in {state.state_id} has both a "
                                   f"non-zero payout cell and a refund rule: a refund is counted once, in the "
                                   f"refund only")
    if unsupported:
        return unsupported, incomplete

    matrix = [[leg.payouts[s.state_id].constant for leg in legs] for s in normal]
    if rel.kind == RelationKind.COMPLEMENT.value:
        if len(legs) != 2 or first.market.market_id != legs[1].market.market_id \
                or {first.side, legs[1].side} != {"YES", "NO"} or first.ratio != legs[1].ratio:
            unsupported.append("a complement is YES and NO of one market in equal ratio")
        for s, row in zip(normal, matrix):
            if sum(row) != ONE or any(c not in (ZERO, ONE) for c in row):
                unsupported.append(f"{s.state_id}: complement legs do not pay exactly one unit")
    elif rel.kind == RelationKind.PARTITION.value:
        if any(leg.side != "YES" for leg in legs) or len({leg.market.market_id for leg in legs}) != len(legs):
            unsupported.append("a partition is YES of distinct markets")
        if len({leg.ratio for leg in legs}) != 1:
            unsupported.append("partition legs must share one ratio")
        for s, row in zip(normal, matrix):
            payers = sum(1 for c in row if c == ONE)
            if any(c not in (ZERO, ONE) for c in row):
                unsupported.append(f"{s.state_id}: non-binary payout in a partition")
            elif payers == 0:
                unsupported.append(f"{s.state_id}: no leg pays: the set is not exhaustive (missing tail or gap)")
            elif payers > 1:
                unsupported.append(f"{s.state_id}: {payers} legs pay: the ranges overlap (not mutually exclusive)")
    elif rel.kind == RelationKind.NESTED_THRESHOLD.value:
        if any(leg.structured_contract is None or leg.structured_contract.kind not in ("greater", "less")
               for leg in legs):
            unsupported.append("nested thresholds need verified threshold contracts (greater/less) on every leg")
        for s, row in zip(normal, matrix):
            if sum(row) < ONE:
                unsupported.append(f"{s.state_id}: no leg pays: the thresholds do not nest over this state")
    return unsupported, incomplete


def _quotes(rel: RelationshipSet, as_of: datetime, max_quote_age: timedelta,
            max_leg_skew: timedelta) -> tuple[list[str], Decimal | None]:
    problems: list[str] = []
    times: list[datetime] = []
    for leg in rel.legs:
        name = f"{leg.market.market_id}/{leg.side}"
        if leg.ladder.anomaly:
            problems.append(f"{name}: book anomaly: {leg.ladder.anomaly}")
        t = parse_utc(leg.ladder.received_at_utc)
        if t is None:
            problems.append(f"{name}: receipt time UNKNOWN")
            continue
        if t > as_of:
            problems.append(f"{name}: received {leg.ladder.received_at_utc}, after as_of (lookahead)")
        elif as_of - t > max_quote_age:
            problems.append(f"{name}: book age {as_of - t} exceeds {max_quote_age} (stale)")
        times.append(t)
    skew = None
    if times:
        skew = Decimal(str((max(times) - min(times)).total_seconds()))
        if max(times) - min(times) > max_leg_skew:
            problems.append(f"leg receipt times span {max(times) - min(times)} > {max_leg_skew}: the quotes do not "
                            "overlap in time")
    return problems, skew


# --------------------------------------------------------------------------- evaluation


def _leg_fill(leg: Leg, quantity: Decimal) -> tuple[LegFill, DepthCost | None]:
    fill = walk_ladder(leg.ladder, quantity, price_grid=leg.market.price_grid)
    cost, why = price_depth_fill(fill, leg.fee_schedule) if fill.status is DepthStatus.FILLABLE else (None, fill.detail)
    return LegFill(leg.market.market_id, leg.side, quantity, fill.status.value, fill.available,
                   fill.gross_cost, None if cost is None else cost.fee, None if cost is None else cost.total_cost,
                   fill.limit_price, why if cost is None else fill.detail), cost


class InvalidCost(ValueError):
    """A settlement or basket cost callable returned a negative or non-finite value."""


def _cost(value: Any, what: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise InvalidCost(f"INVALID: {what} {value!r} must be a finite, non-negative cost")
    return value


def _state_value(rel: RelationshipSet, state: SettlementState, legs: Sequence[Leg], costs: Sequence[DepthCost],
                 quantities: Sequence[Decimal], *, include_settlement: bool) -> tuple[Decimal | None, Decimal, str]:
    """(worst value in this state after settlement costs and refunds or None, worst payout, why)."""
    bounds = {v.name: v for v in state.variables}
    constant = ZERO
    payout_constant = ZERO
    coefficients: dict[str, Decimal] = {}
    why = ""
    unknown = False
    for leg, cost, q in zip(legs, costs, quantities):
        cell = leg.payouts[state.state_id]
        constant += q * cell.constant
        payout_constant += q * cell.constant
        if cell.variable is not None:
            coefficients[cell.variable] = coefficients.get(cell.variable, ZERO) + q * cell.coefficient
        refund_fn = leg.refunds.get(state.state_id, refund_none if state.kind not in (
            StateKind.VOID, StateKind.REFUND, StateKind.CANCELLATION) else None)
        refund = None if refund_fn is None else refund_fn(state.state_id, cost)
        if refund is not None and (not isinstance(refund, Decimal) or not refund.is_finite() or refund < 0):
            raise InvalidCost(f"INVALID: refund {refund!r} in {state.state_id} must be a finite, non-negative amount")
        if refund is None:
            return None, ZERO, f"refund UNKNOWN in {state.state_id}"
        constant += refund
        if include_settlement:
            settle = None if leg.settlement_cost is None else _cost(
                leg.settlement_cost(state.state_id, cost), f"settlement cost in {state.state_id}")
            if settle is None:
                unknown = True
                why = "settlement cost UNKNOWN"
            else:
                constant -= settle
    if include_settlement:
        basket = None if rel.basket_settlement_cost is None else _cost(
            rel.basket_settlement_cost(state.state_id, tuple(costs)), f"basket settlement cost in {state.state_id}")
        if basket is None:
            unknown = True
            why = why or "basket settlement cost UNKNOWN"
        else:
            constant -= basket
    worst_variable = ZERO
    for name, coef in coefficients.items():
        var = bounds[name]
        worst_variable += coef * (var.low if coef >= 0 else var.high)
    worst_payout = payout_constant + worst_variable
    if unknown:
        return None, worst_payout, why
    return constant + worst_variable, worst_payout, ""


def _size(rel: RelationshipSet, relationship: Relationship, basket_q: Decimal, as_of: datetime) -> SizeResult:
    legs = rel.legs
    fills: list[LegFill] = []
    costs: list[DepthCost] = []
    quantities = [basket_q * leg.ratio for leg in legs]
    depth = {f"{leg.market.market_id}/{leg.side}": (sum((lv.size for lv in leg.ladder.asks), ZERO) / leg.ratio,
                                                     leg.ladder.truncated) for leg in legs}
    limiting = min(depth, key=lambda k: (depth[k][0], k)) if depth else None
    for leg, q in zip(legs, quantities):
        leg_fill, cost = _leg_fill(leg, q)
        fills.append(leg_fill)
        if cost is not None:
            costs.append(cost)
    timing = [leg.market.timing for leg in legs if leg.market.timing is not None]
    expected = max((t.expected_resolution_utc for t in timing if t.expected_resolution_utc), default=None)
    latest = max((t.latest_resolution_utc for t in timing if t.latest_resolution_utc), default=None)
    if len(costs) != len(legs):
        bad = [f"{f.market_id}/{f.side}: {f.status} ({f.detail})" for f in fills if f.total_cost is None]
        return SizeResult(basket_q, False, limiting, tuple(fills), None, None, None, None, None, None, None, None,
                          None, None, expected, latest, {}, (), (), Claim.NOT_EVALUATED.value, tuple(bad))
    acquisition = sum((c.total_cost for c in costs), ZERO) + rel.state_independent_costs
    gross = sum((c.fill.gross_cost for c in costs), ZERO) + rel.state_independent_costs
    fees = sum((c.total_cost - c.fill.gross_cost for c in costs), ZERO)  # fees plus the venue's cash rounding
    net_values: dict[str, Decimal | None] = {}
    upper_values: dict[str, Decimal] = {}
    payouts: dict[str, Decimal] = {}
    skipped: list[str] = []
    reasons: list[str] = []
    for state in rel.states:
        try:
            value, payout, why = _state_value(rel, state, legs, costs, quantities, include_settlement=True)
            upper, _, why_upper = _state_value(rel, state, legs, costs, quantities, include_settlement=False)
        except InvalidCost as exc:
            return SizeResult(basket_q, False, limiting, tuple(fills), acquisition, gross, fees, None, None, None,
                              None, None, None, acquisition, expected, latest, {}, (), (),
                              Claim.NOT_EVALUATED.value, (str(exc),))
        if upper is None:  # refund unknown: the state cannot be valued at all
            skipped.append(state.state_id)
            reasons.append(f"state {state.state_id} skipped: {why_upper}")
            continue
        net_values[state.state_id] = value
        upper_values[state.state_id] = upper
        payouts[state.state_id] = payout
        if why and why not in reasons:
            reasons.append(why)
    if skipped and relationship is Relationship.PROVEN:
        # A state that cannot be valued makes the proof incomplete: no positive claim may rest on
        # the remaining states (a "no surplus" conclusion over them is still sound).
        relationship = Relationship.INCOMPLETE
        reasons.append(f"INCOMPLETE: state(s) {skipped} could not be valued")
    if not upper_values:
        return SizeResult(basket_q, False, limiting, tuple(fills), acquisition, gross, fees, None, None, None, None,
                          None, None, acquisition, expected, latest, {}, (), tuple(skipped),
                          Claim.NOT_EVALUATED.value, tuple(reasons))
    worst_state = min(upper_values, key=lambda s: (upper_values[s], s))
    upper_worst = upper_values[worst_state] - acquisition  # settlement costs treated as zero (costs >= 0)
    # The same basket if every fee were zero (refunds recomputed on fee-free fills), so a
    # fee-inclusive refund cannot make "before fees" look better than it is.
    fee_free = [DepthCost(c.fill, (), ZERO, c.fill.gross_cost, c.fill.average_price) for c in costs]
    free_values = []
    for state in rel.states:
        if state.state_id in skipped:
            continue
        v, _, _ = _state_value(rel, state, legs, fee_free, quantities, include_settlement=False)
        if v is not None:
            free_values.append(v)
    before_fees = min(free_values) - gross
    # A minimum over only some states is an upper bound on the true worst state, never a surplus.
    known = all(v is not None for v in net_values.values()) and not skipped
    surplus = (min(v for v in net_values.values()) - acquisition) if known else None
    if known:
        worst_state = min(net_values, key=lambda s: (net_values[s], s))

    orphan: dict[str, Decimal | None] = {}
    for i, leg in enumerate(legs):
        alone = RelationshipSet(rel.set_id, rel.kind, (leg,), rel.states, rel.proof, None, ZERO)
        values = []
        for state in rel.states:
            if state.state_id in skipped:
                continue
            v, _, _ = _state_value(alone, state, (leg,), (costs[i],), (quantities[i],), include_settlement=False)
            if v is not None:
                values.append(v)
        orphan[f"{leg.market.market_id}/{leg.side}"] = (min(values) - costs[i].total_cost) if values else None

    states = [verification_at(leg.fee_schedule, as_of, leg.market.native_id) for leg in legs]
    weakest = min(states, key=lambda s: {ClaimBasis.NONE: 0, ClaimBasis.CONSERVATIVE_BOUND: 1,
                                          ClaimBasis.EXACT: 2}[s.claim_basis])
    contracts = sum(quantities, ZERO)
    claim_adjusted = None if surplus is None else claim_adjusted_net(surplus, contracts, weakest)

    if before_fees <= 0:
        claim = Claim.NO_SURPLUS_EVEN_BEFORE_FEES
        reasons.append("the worst state pays no more than the gross purchase price")
    elif upper_worst <= 0:
        claim = Claim.NO_SURPLUS_AFTER_FEES
        reasons.append("fees (as modelled) erase the pre-fee surplus")
    elif relationship is Relationship.PROVEN and surplus is not None and surplus > 0 and \
            claim_adjusted is not None and claim_adjusted > 0:
        claim = Claim.CONDITIONAL_FULL_FILL_SURPLUS
        reasons.append("conditional on every leg filling at the captured prices; legs are not atomic; "
                       "not captured arbitrage")
    else:
        claim = Claim.SURPLUS_NOT_CLAIMABLE
        if relationship is not Relationship.PROVEN:
            reasons.append(f"relationship {relationship.value}")
        if surplus is None:
            reasons.append("a settlement cost is UNKNOWN (the upper bound treats it as zero)")
        if claim_adjusted is None:
            reasons.append(f"fee claim basis {weakest.claim_basis.value} ({weakest.status.value})")
        elif surplus is not None and claim_adjusted <= 0:
            reasons.append("the fee rounding allowance erases the surplus")
    return SizeResult(
        basket_q, True, limiting, tuple(fills), acquisition, gross, fees, min(payouts.values()), worst_state,
        surplus, before_fees, upper_worst, claim_adjusted, acquisition, expected, latest, orphan,
        tuple(s for s in upper_values), tuple(skipped), claim.value, tuple(reasons))


def evaluate(rel: RelationshipSet, *, sizes: Sequence[Decimal], as_of_utc: str, max_quote_age: timedelta,
             max_leg_skew: timedelta) -> PayoffEvaluation:
    """Evaluate one relationship set at each basket size. Deterministic; never raises for a
    data defect (it reports UNSUPPORTED / INCOMPLETE / INVALID instead)."""
    as_of = parse_utc(as_of_utc)
    if as_of is None:
        raise ValueError("as_of_utc must be timezone-aware")
    unsupported, incomplete = _structure(rel)
    relationship = (Relationship.UNSUPPORTED if unsupported else
                    Relationship.INCOMPLETE if incomplete else Relationship.PROVEN)
    quote_problems, skew = _quotes(rel, as_of, max_quote_age, max_leg_skew) if rel.legs else (["no legs"], None)
    validity = QuoteValidity.INVALID if quote_problems else QuoteValidity.VALID

    inconsistency = None
    note = "not computed"
    if relationship is not Relationship.UNSUPPORTED and validity is QuoteValidity.VALID:
        tops = [leg.ladder.asks[0].price if leg.ladder.asks else None for leg in rel.legs]
        normal = [s for s in rel.states if s.kind is StateKind.NORMAL]
        if None in tops:
            note = "a leg has no ask"
        else:
            min_normal = min(sum((leg.ratio * leg.payouts[s.state_id].constant for leg in rel.legs), ZERO)
                             for s in normal)
            inconsistency = min_normal - sum((leg.ratio * p for leg, p in zip(rel.legs, tops)), ZERO)
            note = ("OBSERVED QUOTE INCONSISTENCY: worst NORMAL-state payout minus the sum of top-of-book asks per "
                    "basket unit; pre-fee, top of book only, abnormal states ignored. Not a surplus.")
    rows: tuple[SizeResult, ...] = ()
    if relationship is not Relationship.UNSUPPORTED and validity is QuoteValidity.VALID:
        rows = tuple(_size(rel, relationship, Decimal(q), as_of) for q in sorted(set(sizes)))
    unvalued = sorted({s for row in rows for s in row.states_skipped})
    invalid = sorted({r for row in rows for r in row.claim_reasons if r.startswith("INVALID:")})
    if unvalued and relationship is Relationship.PROVEN:
        relationship = Relationship.INCOMPLETE
        incomplete.append(f"state(s) {unvalued} could not be valued (a refund or cost is UNKNOWN)")
    if invalid:
        relationship = Relationship.UNSUPPORTED
        unsupported.extend(invalid)
    result = PayoffEvaluation(
        PAYOFF_VERSION, rel.set_id, rel.kind, as_of.isoformat(), relationship.value,
        tuple(unsupported + incomplete), tuple(rel.proof.assumptions), validity.value, tuple(quote_problems), skew,
        inconsistency, note, rows)
    body = result.to_dict()
    body.pop("evaluation_sha256")
    return replace(result, evaluation_sha256=sha256_hex(canonical_json(body)))


def size_points(evaluation: PayoffEvaluation):
    """The evaluation as `research_economics.SizePoint`s (per basket unit), for the economic screen.

    A size that was not evaluated is not FILLABLE. The net edge is the claim-adjusted worst-state
    surplus per basket unit, and None when it is not claimable (unknown costs, an unproven
    relationship or an unclaimable fee basis): a conditional bound is never inflated."""
    from .research_economics import SizePoint

    points = []
    for row in evaluation.sizes:
        q = row.basket_quantity
        if not row.evaluated or row.acquisition_cost is None:
            points.append(SizePoint(q, "NOT_EVALUATED", None, None, None, "; ".join(row.claim_reasons)))
            continue
        claimable = row.claim == Claim.CONDITIONAL_FULL_FILL_SURPLUS.value
        net = (row.claim_adjusted_surplus / q) if claimable and row.claim_adjusted_surplus is not None else None
        gross = row.worst_state_surplus_before_fees / q if row.worst_state_surplus_before_fees is not None else None
        points.append(SizePoint(q, DepthStatus.FILLABLE.value, row.acquisition_cost / q, gross, net, row.claim))
    return tuple(points)


# --------------------------------------------------------------------------- Kalshi stored evidence


def rules_template_sha256(rules_primary: str | None, rules_secondary: str | None) -> str | None:
    """The rules text with every number and the strike comparison blanked: identical across the
    brackets of one event only when the source, station, window and wording agree."""
    if not rules_primary:
        return None
    text = re.sub(r"\d+(?:\.\d+)?", "#", f"{rules_primary}\n{rules_secondary or ''}")  # a sign stays as text
    text = re.sub(r"\b(between #\s*°?\s*(?:-|to|and)\s*#°|greater than #°|less than #°)", "<STRIKE>", text,
                  flags=re.I)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Settled or post-close fields that Family B may never read (EXP-003 protocol, prohibited_fields).
PROHIBITED_MARKET_FIELDS = ("result", "expiration_value", "settlement_value", "settlement_value_dollars",
                            "settlement_ts", "last_price_dollars", "previous_price_dollars")

KXHIGHNY_PROOF = StateProof(
    excluded_kinds={
        StateKind.TIE: "integer settlement value in whole degrees F: every integer lies in exactly one enumerated "
                       "NORMAL state (docs/SETTLEMENT.md section 3; the resolver refuses non-integer values)",
        StateKind.CORRECTION: "revisions after the expiration date are not included; a correction before expiration "
                              "only selects among the enumerated NORMAL states (GLOBALTEMPERATURE; docs/SETTLEMENT.md "
                              "section 4)",
    },
    evidence_hashes=(),
    assumptions=(),
)
KXHIGHNY_FALLBACK = ("missing data: 'all strikes shall resolve to the last fair price as determined in the sole "
                     "discretion of the Exchange' (GLOBALTEMPERATURE; TWC-era rules_secondary; docs/SETTLEMENT.md "
                     "section 5); each strike's value v is independent and unknown in [0, 1]")


def sanitized(raw: Mapping[str, Any], prohibited: Sequence[str] = PROHIBITED_MARKET_FIELDS) -> dict[str, Any]:
    """A Kalshi market record without the settled/post-close fields Family B must not read."""
    drop = set(prohibited) | set(PROHIBITED_MARKET_FIELDS)
    return {k: v for k, v in raw.items() if k not in drop}


def _rules_contract(raw: Mapping[str, Any]) -> NumericContract | None:
    from .settlement import read_rules

    reading = read_rules(raw.get("rules_primary"))
    if reading.comparison == "greater":
        return numeric_contract("greater", reading.low, None)
    if reading.comparison == "less":
        return numeric_contract("less", None, reading.high)
    if reading.comparison == "between":
        return numeric_contract("between", reading.low, reading.high)
    return None


def _structured_contract(raw: Mapping[str, Any]) -> NumericContract | None:
    kind = raw.get("strike_type")
    if kind == "greater":
        return numeric_contract("greater", raw.get("floor_strike"), None)
    if kind == "less":
        return numeric_contract("less", None, raw.get("cap_strike"))
    if kind == "between":
        return numeric_contract("between", raw.get("floor_strike"), raw.get("cap_strike"))
    return None


def kalshi_partition_set(event_ticker: str, raws: Sequence[Mapping[str, Any]], ladders: Mapping[str, DepthLadder], *,
                         fee_schedule: FeeSchedule, set_id: str | None = None, include_fallback: bool = True,
                         prohibited_fields: Sequence[str] = PROHIBITED_MARKET_FIELDS) -> RelationshipSet:
    """A YES partition over every bracket of one Kalshi numeric event, from sanitized market records.

    - States: every integer value between the strikes (tails included) and the discretionary
      fair-price fallback. VOID, REFUND and CANCELLATION are not excluded by captured evidence, so
      the proof stays INCOMPLETE.
    - Settlement and transfer costs are UNKNOWN (not yet verified).
    - Each leg's `Event.settlement_identity` is the hash of its rules template, so changed wording,
      source, station or window breaks the set."""
    from .kalshi_quotes import market_from_kalshi
    from .opportunity import KALSHI_BINARY_UNITS

    clean = [sanitized(r, prohibited_fields) for r in raws]
    event_id = f"kalshi:{event_ticker}"
    structured = {str(r.get("ticker")): _structured_contract(r) for r in clean}
    contracts = [c for c in structured.values() if c is not None]
    normal = integer_value_states(contracts) if contracts else ()
    markets = {str(r.get("ticker")): market_from_kalshi(r, event_id_for_ticker={event_ticker: event_id}) for r in clean}
    states = tuple(normal) + ((fair_price_fallback([m.market_id for m in markets.values()],
                                                   description=KXHIGHNY_FALLBACK),) if include_fallback else ())
    legs = []
    for raw in clean:
        ticker = str(raw.get("ticker"))
        market = markets[ticker]
        contract = structured[ticker]
        payouts = numeric_cells(contract, "YES", normal) if contract is not None else {}
        if include_fallback:
            payouts["fallback_fair_price"] = fallback_cell(market.market_id, "YES")
        event = Event("weather", event_id, str(raw.get("occurrence_datetime") or ""), None, event_ticker,
                      rules_template_sha256(raw.get("rules_primary"), raw.get("rules_secondary")) or "UNKNOWN")
        ladder = ladders.get(ticker) or DepthLadder("kalshi", market.market_id, "YES", (), False, None, None, None,
                                                    "no captured book")
        legs.append(Leg(event, market, "YES", ladder, fee_schedule, KALSHI_BINARY_UNITS, payouts,
                        structured_contract=contract, rules_contract=_rules_contract(raw)))
    return RelationshipSet(set_id or f"{event_ticker}:partition", RelationKind.PARTITION.value, tuple(legs), states,
                           KXHIGHNY_PROOF)


def _depth_limit(url: str | None) -> int | None:
    match = re.search(r"[?&]depth=(\d+)", url or "")
    return int(match.group(1)) if match else None


_EVENT_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})$")
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                       "DEC"), start=1)}


def event_date(event_ticker: str) -> str | None:
    """The event date encoded in a Kalshi event ticker (…-26SEP23 -> 2026-09-23), or None."""
    from datetime import date

    match = _EVENT_DATE.search(event_ticker)
    if not match or match.group(2) not in _MONTHS:
        return None
    try:
        return date(2000 + int(match.group(1)), _MONTHS[match.group(2)], int(match.group(3))).isoformat()
    except ValueError:
        return None


# One set per capture round (see scan_kalshi_store). Result files written before this field existed
# (EXP-003 results up to 2026-09-25) anchored a set at every book receipt, so mid-round anchors
# appear there as INVALID sets rather than as MID_ROUND skips; they stay as recorded evidence.
SET_CONSTRUCTION = "one-set-per-capture-round-v1"


def scan_kalshi_store(db_path: str, *, series: str, sizes: Sequence[Decimal], max_quote_age: timedelta,
                      max_leg_skew: timedelta, event_from: str, event_to: str,
                      prohibited_fields: Sequence[str] = PROHIBITED_MARKET_FIELDS) -> dict[str, Any]:
    """Evaluate every complete, time-overlapping YES-partition book set of `series` in an evidence
    store, which is opened read-only (SQLite mode=ro and query_only; any schema version, because
    only `snapshots` columns present since v2 are read).
    - Market-side books and rules only.
    - Settled fields (`prohibited_fields`, always including PROHIBITED_MARKET_FIELDS; the CLI passes
      EXP-003's protocol list) are dropped before any use.
    - A set is skipped when any leg's book was received at or after the market's close time.
    - Only `series` in VERIFIED_INTEGER_SERIES, and only events dated within [event_from, event_to]
      (YYYY-MM-DD, from the event ticker) are evaluated; other events are listed as skipped.
    - Set construction (SET_CONSTRUCTION): one set per capture round. Every book receipt time of the
      event is tried as an anchor; each leg takes its latest book received by the anchor. An anchor
      is evaluated only when every leg has a book (else INCOMPLETE_ROUND) and those books were all
      received within `max_leg_skew` of each other (else MID_ROUND: it mixes two rounds). Every
      tried anchor is accounted for: evaluated, or listed in `sets_skipped` with a reason code, so
      `anchors_tried == sets_evaluated + skipped anchors`."""
    if series not in VERIFIED_INTEGER_SERIES:
        raise ValueError(f"series {series!r} is not a verified integer-strike series {sorted(VERIFIED_INTEGER_SERIES)}")
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_from or "") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_to or "")
            and event_from <= event_to):
        raise ValueError("event_from and event_to must be YYYY-MM-DD with event_from <= event_to")
    import json
    import sqlite3
    from contextlib import closing

    from .fee_schedules import schedule_for
    from .kalshi_quotes import ladders_from_orderbook

    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute("PRAGMA query_only = ON")
        identity_row = con.execute("SELECT MAX(id), MAX(fetched_at_utc) FROM snapshots").fetchone()
        store_identity = {"schema_version": int(con.execute("PRAGMA user_version").fetchone()[0]),
                          "max_snapshot_id": identity_row[0], "latest_snapshot_received_utc": identity_row[1]}
        rows = con.execute(
            "SELECT id, kind, entity_id, fetched_at_utc, url, payload_json, payload_sha256 FROM snapshots "
            "WHERE source = 'kalshi' AND kind IN ('markets', 'orderbook') AND substr(entity_id, 1, ?) = ? ORDER BY id",
            (len(series), series)).fetchall()
    market_snaps = []  # (fetched, id, sha, [raw markets])
    books: dict[str, list[tuple[str, int, str, dict, str | None]]] = {}
    for sid, kind, entity, fetched, url, payload, sha in rows:
        body = json.loads(payload)
        if kind == "markets":
            market_snaps.append((fetched, sid, sha, [m for m in body.get("markets", []) if isinstance(m, dict)]))
        else:
            books.setdefault(entity, []).append((fetched, sid, sha, body, url))
    by_event: dict[str, set[str]] = {}
    for _, _, _, markets in market_snaps:
        for m in markets:
            if str(m.get("ticker", "")).startswith(series):
                by_event.setdefault(str(m.get("event_ticker")), set()).add(str(m.get("ticker")))
    evaluations = []
    skipped: list[dict[str, str]] = []
    anchors_tried = 0
    inputs: list[str] = []
    for event_ticker in sorted(by_event):
        day = event_date(event_ticker)
        if day is None or not (event_from <= day <= event_to):
            skipped.append({"event": event_ticker, "as_of": "", "code": "OUTSIDE_WINDOW",
                            "reason": f"event date {day} outside the requested window {event_from}..{event_to}"})
            continue
        tickers = sorted(by_event[event_ticker])
        anchors = sorted({b[0] for t in tickers for b in books.get(t, [])})
        anchors_tried += len(anchors)
        for anchor in anchors:
            chosen = {}
            for t in tickers:
                prior = [b for b in books.get(t, []) if b[0] <= anchor]
                if prior:
                    chosen[t] = max(prior, key=lambda b: (b[0], b[1]))
            if len(chosen) != len(tickers):
                missing = [t for t in tickers if t not in chosen]
                skipped.append({"event": event_ticker, "as_of": anchor, "code": "INCOMPLETE_ROUND",
                                "reason": f"INCOMPLETE_ROUND: no book received by as_of for {', '.join(missing)}"})
                continue
            received = [parse_utc(b[0]) for b in chosen.values()]
            if all(r is not None for r in received) and max(received) - min(received) > max_leg_skew:
                skipped.append({"event": event_ticker, "as_of": anchor, "code": "MID_ROUND",
                                "reason": f"MID_ROUND: leg books span {max(received) - min(received)} > {max_leg_skew}"
                                          "; the anchor mixes two capture rounds"})
                continue
            snaps = [s for s in market_snaps if s[0] <= anchor]
            if not snaps:
                skipped.append({"event": event_ticker, "as_of": anchor, "code": "NO_MARKET_RECORD",
                                "reason": "no market record received by as_of"})
                continue
            latest: dict[str, Mapping[str, Any]] = {}
            for _, _, _, markets in sorted(snaps, key=lambda s: (s[0], s[1])):
                for m in markets:
                    if str(m.get("ticker")) in tickers:
                        latest[str(m.get("ticker"))] = m
            if len(latest) != len(tickers):
                skipped.append({"event": event_ticker, "as_of": anchor, "code": "NO_MARKET_RECORD",
                                "reason": "a bracket has no market record"})
                continue
            closes = [parse_utc(m.get("close_time")) for m in latest.values()]
            if any(c is None or parse_utc(anchor) >= c for c in closes):
                skipped.append({"event": event_ticker, "as_of": anchor, "code": "POST_CLOSE",
                                "reason": "at or after a market's close (post-close snapshots are prohibited)"})
                continue
            ladders = {}
            for t, (fetched, sid, sha, body, url) in chosen.items():
                ladders[t] = ladders_from_orderbook(t, body, received_at_utc=fetched, evidence_id=f"snapshot:{sid}",
                                                   depth_limit=_depth_limit(url)).get("YES")
                inputs.append(sha)
            fee = schedule_for("kalshi", series, as_of=anchor)
            rel = kalshi_partition_set(event_ticker, [latest[t] for t in tickers], ladders, fee_schedule=fee,
                                       set_id=f"{event_ticker}@{anchor}", prohibited_fields=prohibited_fields)
            evaluations.append(evaluate(rel, sizes=sizes, as_of_utc=anchor, max_quote_age=max_quote_age,
                                        max_leg_skew=max_leg_skew))
    claims: dict[str, int] = {}
    relationships: dict[str, int] = {}
    validity: dict[str, int] = {}
    for e in evaluations:
        relationships[e.relationship] = relationships.get(e.relationship, 0) + 1
        validity[e.quote_validity] = validity.get(e.quote_validity, 0) + 1
        for row in e.sizes:
            claims[row.claim] = claims.get(row.claim, 0) + 1
    skip_counts: dict[str, int] = {}
    for s in skipped:
        skip_counts[s["code"]] = skip_counts.get(s["code"], 0) + 1
    inconsistencies = [e.observed_quote_inconsistency for e in evaluations if e.observed_quote_inconsistency is not None]
    report = {
        "version": PAYOFF_VERSION,
        "series": series,
        "store_identity": store_identity,
        "event_window": [event_from, event_to],
        "sizes": [str(s) for s in sorted(set(sizes))],
        "max_quote_age_seconds": max_quote_age.total_seconds(),
        "max_leg_skew_seconds": max_leg_skew.total_seconds(),
        "events": len(by_event),
        "set_construction": SET_CONSTRUCTION,
        "anchors_tried": anchors_tried,
        "sets_evaluated": len(evaluations),
        "sets_skipped": skipped,
        "skip_counts": dict(sorted(skip_counts.items())),
        "relationship_counts": dict(sorted(relationships.items())),
        "quote_validity_counts": dict(sorted(validity.items())),
        "claim_counts_by_size_row": dict(sorted(claims.items())),
        "observed_quote_inconsistency_max": str(max(inconsistencies)) if inconsistencies else None,
        "observed_quote_inconsistency_min": str(min(inconsistencies)) if inconsistencies else None,
        "input_snapshot_sha256": sha256_hex(canonical_json(sorted(inputs))),
        "prohibited_fields_never_read": sorted(set(prohibited_fields) | set(PROHIBITED_MARKET_FIELDS)),
        "evaluations": [e.to_dict() for e in evaluations],
        "simulated_execution": SIMULATED_EXECUTION,
        "actual_result": ACTUAL_RESULT,
    }
    report["report_sha256"] = sha256_hex(canonical_json(report))
    return report



# --------------------------------------------------------------------------- result files (Terminal input)

RESULT_VERSION = "payoff-scan-result-v1"
SOURCE_LABELS = ("laptop", "production", "fixture")
PROVENANCE_FIELDS = ("generated_at_utc", "source_store", "store_identity", "code_version", "event_window",
                     "evidence_use_event_id")


def result_envelope(report: Mapping[str, Any], *, generated_at_utc: str, source_store: str, code_version: str,
                    evidence_use_event_id: str) -> dict[str, Any]:
    """The committed/displayed scan result: the report (hashed by `report_sha256`) plus a provenance
    envelope, and `envelope_sha256` over both. `verify_result_file` checks it."""
    if source_store not in SOURCE_LABELS:
        raise ValueError(f"source_store must be one of {SOURCE_LABELS}")
    provenance = {
        "generated_at_utc": generated_at_utc,
        "source_store": source_store,
        "store_identity": report.get("store_identity"),
        "code_version": code_version,
        "event_window": report.get("event_window"),
        "evidence_use_event_id": evidence_use_event_id,
    }
    envelope = {"result_version": RESULT_VERSION, "payoff_version": PAYOFF_VERSION, "provenance": provenance,
                "report": dict(report)}
    envelope["envelope_sha256"] = sha256_hex(canonical_json({k: v for k, v in envelope.items()}))
    return envelope


def verify_result_file(obj: Any) -> tuple[bool, tuple[str, ...]]:
    """The one canonical check of a payoff-scan result file (the Terminal calls this, never its own).

    Checks the versions, both recomputed hashes, that every built-in prohibited field is declared
    never read, and that every provenance field is present and well formed. Pure; never raises:
    any malformed input is (False, reasons).

    The hashes detect accidental edits, not forgery: anyone can recompute them after an edit.
    `verify_result_provenance` additionally ties the file to the experiment's append-only
    evidence-use log."""
    try:
        return _verify_result_file(obj)
    except Exception as exc:  # noqa: BLE001 - a checker of untrusted files must not raise
        return False, (f"malformed result file: {type(exc).__name__}: {exc}",)


def _verify_result_file(obj: Any) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not isinstance(obj, Mapping):
        return False, ("not a JSON object",)
    if obj.get("result_version") != RESULT_VERSION:
        reasons.append(f"result_version {obj.get('result_version')!r} is not {RESULT_VERSION}")
    if obj.get("payoff_version") != PAYOFF_VERSION:
        reasons.append(f"payoff_version {obj.get('payoff_version')!r} is not {PAYOFF_VERSION}")
    report = obj.get("report")
    provenance = obj.get("provenance")
    if not isinstance(report, Mapping) or not isinstance(provenance, Mapping):
        return False, tuple(reasons + ["report or provenance missing"])
    try:
        body = {k: v for k, v in obj.items() if k != "envelope_sha256"}
        if sha256_hex(canonical_json(body)) != obj.get("envelope_sha256"):
            reasons.append("envelope_sha256 does not match (edited?)")
        report_body = {k: v for k, v in report.items() if k != "report_sha256"}
        if sha256_hex(canonical_json(report_body)) != report.get("report_sha256"):
            reasons.append("report_sha256 does not match (edited?)")
    except (TypeError, ValueError) as exc:
        reasons.append(f"cannot hash: {exc}")
    if report.get("version") != PAYOFF_VERSION:
        reasons.append(f"report version {report.get('version')!r} is not {PAYOFF_VERSION}")
    never_read = report.get("prohibited_fields_never_read")
    if not (isinstance(never_read, list) and all(isinstance(f, str) for f in never_read)
            and set(PROHIBITED_MARKET_FIELDS) <= set(never_read)):
        reasons.append("prohibited_fields_never_read does not cover every settled field")
    for key in PROVENANCE_FIELDS:
        if provenance.get(key) in (None, "", []):
            reasons.append(f"provenance.{key} is missing")
    if provenance.get("source_store") not in SOURCE_LABELS:
        reasons.append(f"provenance.source_store must be one of {SOURCE_LABELS}")
    if parse_utc(provenance.get("generated_at_utc")) is None:
        reasons.append("provenance.generated_at_utc is not a timezone-aware time")
    identity = provenance.get("store_identity")
    if not (isinstance(identity, Mapping) and all(k in identity for k in ("schema_version", "max_snapshot_id",
                                                                          "latest_snapshot_received_utc"))):
        reasons.append("provenance.store_identity needs schema_version, max_snapshot_id, latest_snapshot_received_utc")
    elif identity != report.get("store_identity"):
        reasons.append("provenance.store_identity differs from the report's")
    window = provenance.get("event_window")
    if window != report.get("event_window") or not (isinstance(window, list) and len(window) == 2):
        reasons.append("provenance.event_window differs from the report's or is malformed")
    event_id = provenance.get("evidence_use_event_id")
    if not (isinstance(event_id, str) and re.fullmatch(r"eu-[0-9a-f]{32}", event_id)):
        reasons.append("provenance.evidence_use_event_id is not an evidence-use event id")
    return not reasons, tuple(reasons)


def verify_result_provenance(obj: Any, log_path: Any) -> tuple[bool, tuple[str, ...]]:
    """`verify_result_file` plus the tie to the evidence-use log (the Terminal passes the repository's
    EXP-003 `evidence_use.jsonl`):
    - the provenance's `evidence_use_event_id` exists in that log, logged for EXP-003;
    - that event's dataset hash equals the report's `input_snapshot_sha256`;
    - its window covers exactly the report's event window, in the series' scope;
    - its note names the report's hash as the exact token `report_sha256=<sha>`, which the CLI writes
      before any output;
    - the log's header belongs to EXP-003.

    This proves that a matching event was logged, not that the event is genuine: the log is
    self-declared and accepts appends, so anyone who can append can log a matching event.

    Never raises."""
    ok, reasons = verify_result_file(obj)
    reasons = list(reasons)
    try:
        from pathlib import Path as _Path

        from .research_evidence import read_log

        log = read_log(_Path(log_path))
        if log.experiment_id != "EXP-003":
            reasons.append(f"the evidence-use log belongs to {log.experiment_id!r}, not EXP-003")
        provenance, report = obj["provenance"], obj["report"]
        event = next((u for u in log.uses if u.event_id == provenance.get("evidence_use_event_id")), None)
        if event is None:
            reasons.append("the evidence_use_event_id is not in the evidence-use log")
        else:
            if event.experiment_id != "EXP-003":
                reasons.append(f"the logged event belongs to {event.experiment_id}, not EXP-003")
            if event.dataset_sha256 != report.get("input_snapshot_sha256"):
                reasons.append("the logged dataset hash differs from the report's input_snapshot_sha256")
            named = re.findall(r"(?:^|[\s;(])report_sha256=([0-9a-f]{64})(?=$|[\s;.,)])", event.note)
            if report.get("report_sha256") not in named:
                reasons.append("the logged event does not name this report's report_sha256 as a "
                               "`report_sha256=<sha>` token (edited report?)")
            window = report.get("event_window") or [None, None]
            if (event.window.start_utc[:10], event.window.end_utc[:10]) != (window[0], window[1]) or \
                    event.window.scope.strip().lower() != f"kalshi:{str(report.get('series', '')).lower()}":
                reasons.append("the logged event window or scope differs from the report's")
    except Exception as exc:  # noqa: BLE001 - untrusted inputs: report, never raise
        reasons.append(f"cannot check the evidence-use log: {type(exc).__name__}: {exc}")
    return not reasons, tuple(reasons)
