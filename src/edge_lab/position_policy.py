"""Pure HOLD / REDUCE / EXIT position-policy evaluator v1 (#122 §15). Research only.

Given one position and what is known about it at `as_of`, a frozen policy proposes HOLD,
REDUCE or EXIT with a bounded quantity, a reason, the execution assumption the proposal
needs, and its provenance. Or it refuses: BLOCKED when a fact it needs is missing, stale or
contradictory, UNSUPPORTED when the policy itself is not defensible yet.

What it will not do:
- **Invent a probability.** No input is a win probability, and a fair-value policy is
  UNSUPPORTED until its model is independently justified. Entry cost is carried for
  accounting only; it is never the valuation anchor.
- **Liquidate through bad data.** A missing, stale or unreconstructed book, a paused or
  closed market, or unreconciled orders give BLOCKED with `no_new_risk`, never EXIT. The
  separately authorized reduce-only response to a kill state is future work (ADR 0038).
- **Oversell.** Inventory already reserved by resting sales (native Auto Sell, manual, bot
  or unknown origin) is not available; a cancel *request* releases nothing. More reservation
  than inventory is BLOCKED: a resting sale that is not reduce-only could open the opposite
  side (docs: `reduce_only` is accepted only with immediate_or_cancel).
- **Act.** It cannot sign, submit or authorize anything. `PolicyDecision.authorizes_execution`
  is always False and constructing one with True raises. Tickets and the pre-submit chain stay
  in `execution_ticket.py`, whose last control, EXECUTION_NOT_AUTHORIZED, always fails.

REENTER and ADD are named future actions and are always UNSUPPORTED here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from .execution_ticket import OPEN_ORDER_STATES, OrderState
from .fee_schedules import ClaimBasis, valid_price
from .freshness import parse_utc
from .inplay_evidence import BookStatus, DataKind, StateValidity, TradingState, depth_at_or_above, walk_bids
from .opportunity import DepthStatus

EVALUATOR_VERSION = "position-policy-v1"
CENT = Decimal("0.01")


class Action(str, Enum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    REENTER = "REENTER"  # future: a new transaction needing a new admissible edge
    ADD = "ADD"  # future: new risk; separately reviewed controls


FUTURE_ACTIONS = frozenset({Action.REENTER, Action.ADD})


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"  # a research proposal; nothing is sent
    NO_POSITION = "NO_POSITION"
    BLOCKED = "BLOCKED"  # a needed fact is missing, stale or contradictory: no new risk, no liquidation
    UNSUPPORTED = "UNSUPPORTED"  # the policy is not defensible yet


class PolicyKind(str, Enum):
    HOLD_TO_SETTLEMENT = "HOLD_TO_SETTLEMENT"
    FIXED_TARGET_FULL_EXIT = "FIXED_TARGET_FULL_EXIT"
    FIXED_TARGET_PARTIAL_EXIT = "FIXED_TARGET_PARTIAL_EXIT"
    FAIR_VALUE = "FAIR_VALUE"  # UNSUPPORTED: no defensible model
    REENTER = "REENTER"  # UNSUPPORTED (future)
    ADD = "ADD"  # UNSUPPORTED (future)


SUPPORTED_KINDS = frozenset({PolicyKind.HOLD_TO_SETTLEMENT, PolicyKind.FIXED_TARGET_FULL_EXIT,
                             PolicyKind.FIXED_TARGET_PARTIAL_EXIT})


class ExecutionAssumption(str, Enum):
    """How a proposal would have to be carried out. The two are never combined (ADR 0038)."""

    NONE = "NONE"  # HOLD
    BOT_TRIGGERED_IOC = "BOT_TRIGGERED_IOC"  # decided now on this book; a marketable limit arrives later
    PREPLACED_RESTING_LIMIT = "PREPLACED_RESTING_LIMIT"  # a resting sale at the target, placed now


class OrderOrigin(str, Enum):
    NATIVE_AUTO_SELL = "NATIVE_AUTO_SELL"  # Kalshi app take-profit: a resting limit sell
    MANUAL = "MANUAL"
    BOT = "BOT"
    UNKNOWN = "UNKNOWN"


class InventoryKind(str, Enum):
    SIMULATED = "SIMULATED"  # labelled research inventory
    ACTUAL = "ACTUAL"  # from an account read (none is authorized today)


@dataclass(frozen=True)
class Inventory:
    """One position on one side of one market, in native contracts (0.01 step)."""

    market_id: str
    side: str  # "YES" | "NO": the side held
    quantity: Decimal
    initial_quantity: Decimal  # the entry cohort's quantity, for predefined partial exits
    kind: InventoryKind
    as_of_utc: str
    evidence_id: str
    entry_cost: Decimal | None = None  # accounting only: never a valuation anchor


@dataclass(frozen=True)
class RestingOrder:
    """An order that may consume this inventory. `remaining` is unfilled quantity."""

    order_id: str
    origin: OrderOrigin
    market_id: str
    side: str  # the side it sells
    is_sale: bool
    remaining: Decimal
    limit_price: Decimal | None
    state: OrderState
    cancel_requested: bool = False  # a request is not a confirmation: still reserved
    policy_id: str | None = None  # the policy that placed it, for bot orders


@dataclass(frozen=True)
class SaleBook:
    """The admissible bids for selling `side` of `market_id`, from the evidence contract."""

    market_id: str
    side: str
    bids: tuple[tuple[Decimal, Decimal], ...]  # ascending (price, contracts), as reconstructed
    truncated: bool
    status: BookStatus
    trading_state: TradingState
    received_at_utc: str | None
    evidence_id: str | None
    data_kind: DataKind


class FeeModel(Protocol):
    """A sale-fee source. `sale_fee` returns None when the fee is unknown for that trade."""

    model_id: str
    claim_basis: ClaimBasis

    def sale_fee(self, contracts: Decimal, price: Decimal) -> Decimal | None: ...


@dataclass(frozen=True)
class ScheduleFeeModel:
    """Sale fees from a canonical `fee_schedules` schedule (no fee formula is copied here).

    The sale fee of C contracts at P is the schedule's per-trade fee `taker_buy(C, P).fee`. For
    Kalshi's quadratic schedule that fee depends on P x (1 - P), so it is the same whether the
    trade is read as selling YES at P or buying NO at 1 - P. Whether the venue charges exactly
    that on a sale is a venue fact: `claim_basis` (from `verification_at`) says what may rest on
    it. Fractional contracts have no modelled fee rule: None."""

    model_id: str
    schedule: Any
    claim_basis: ClaimBasis
    balance_precision: Decimal = CENT  # floor to the cent: conservative for a sale's cash-in
    detail: str = ""

    def sale_fee(self, contracts: Decimal, price: Decimal) -> Decimal | None:
        if not isinstance(contracts, Decimal) or contracts <= 0 or contracts != contracts.to_integral_value():
            return None
        try:
            return self.schedule.taker_buy(int(contracts), price).fee
        except (ValueError, AttributeError):
            return None


@dataclass(frozen=True)
class UnknownFeeModel:
    """No fee model applies (an unsupported or unverified scope). Every fee is None."""

    model_id: str
    reason: str
    claim_basis: ClaimBasis = ClaimBasis.NONE
    balance_precision: Decimal = CENT

    def sale_fee(self, contracts: Decimal, price: Decimal) -> Decimal | None:
        return None


def fee_model_for(venue: str, native_id: str, as_of: datetime | str) -> ScheduleFeeModel | UnknownFeeModel:
    """The point-in-time sale-fee model for a market, from `fee_schedules.schedule_for` and
    `verification_at`. KXNFLGAME is on Kalshi's non-standard list, so today this is
    UnknownFeeModel for NFL game markets: after-cost claims stay blocked (Kalshi question 7)."""
    from .fee_schedules import UnsupportedFeeSchedule, schedule_for, verification_at

    scope = native_id.split("-", 1)[0] if venue == "kalshi" and native_id else None
    schedule = schedule_for(venue, scope, as_of=as_of)
    if isinstance(schedule, UnsupportedFeeSchedule):
        return UnknownFeeModel(schedule.schedule_id, schedule.reason)
    state = verification_at(schedule, as_of, native_id)
    return ScheduleFeeModel(schedule.schedule_id, schedule, state.claim_basis, detail=state.detail)


@dataclass(frozen=True)
class PositionPolicy:
    """A frozen policy. Changing any field is a new `policy_id`/`version`, never an edit."""

    policy_id: str
    version: str
    kind: PolicyKind
    execution: ExecutionAssumption
    target_price: Decimal | None = None  # gross bid per contract a sale must reach
    exit_fraction: Decimal | None = None  # of the initial quantity, for a partial exit
    quantity_step: Decimal = Decimal("1")  # whole contracts: no fee rule for fractional fills is modelled
    max_book_age: timedelta = timedelta(seconds=15)
    max_inventory_age: timedelta = timedelta(minutes=5)
    requires_game_state: bool = False

    def problems(self) -> list[str]:
        out = []
        if self.kind in (PolicyKind.FIXED_TARGET_FULL_EXIT, PolicyKind.FIXED_TARGET_PARTIAL_EXIT):
            if not valid_price(self.target_price):
                out.append(f"target {self.target_price!r} is not a dollar price inside (0, 1)")
            if self.execution not in (ExecutionAssumption.BOT_TRIGGERED_IOC,
                                      ExecutionAssumption.PREPLACED_RESTING_LIMIT):
                out.append("an exit policy must declare exactly one execution assumption")
        if self.kind is PolicyKind.FIXED_TARGET_PARTIAL_EXIT:
            f = self.exit_fraction
            if not isinstance(f, Decimal) or not (Decimal(0) < f < Decimal(1)):
                out.append(f"exit fraction {f!r} must be strictly between 0 and 1")
        if not isinstance(self.quantity_step, Decimal) or self.quantity_step <= 0 or self.quantity_step % CENT != 0:
            out.append("quantity step must be a positive multiple of 0.01 contracts")
        return out


@dataclass(frozen=True)
class GameStateInput:
    as_of_utc: str | None
    fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    status: DecisionStatus
    action: Action | None
    quantity: Decimal  # bounded: never more than available, unreserved inventory
    limit_price: Decimal | None
    reasons: tuple[str, ...]
    execution: ExecutionAssumption
    gross_proceeds: Decimal | None  # at this book, for BOT_TRIGGERED_IOC only; None otherwise
    fee: Decimal | None
    net_proceeds: Decimal | None  # proceeds are not profit
    fee_claim_basis: str
    no_new_risk: bool
    review_required: bool
    provenance: Mapping[str, Any]
    authorizes_execution: bool = False

    def __post_init__(self) -> None:
        if self.authorizes_execution:
            raise ValueError("the position policy cannot authorize execution")
        if self.action in FUTURE_ACTIONS:
            raise ValueError(f"{self.action.value} is a future action and is never proposed in v1")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Enum):
                v = v.value
            elif isinstance(v, Decimal):
                v = str(v)
            elif isinstance(v, tuple):
                v = list(v)
            elif isinstance(v, Mapping):
                v = dict(v)
            out[k] = v
        return out


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _known_qty(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0 and value % CENT == 0


def evaluate(*, as_of: datetime, inventory: Inventory | None, orders: Sequence[RestingOrder],
             book: SaleBook | None, fee_model: FeeModel | None, policy: PositionPolicy,
             rules_version: str | None, game_state: GameStateInput | None = None,
             state_validity: StateValidity | None = None) -> PolicyDecision:
    """One decision. Pure and deterministic; every refusal lists all its reasons.

    `state_validity` (source-state-v1, ADR 0041) is `inplay_evidence.decision_validity` checked at
    `as_of` for the game-state version this recommendation depends on. When it is supplied and not
    VALID (a material new event, a correction, an unknown or out-of-order state), an exit proposal
    is BLOCKED with `review_required`: a policy state that sends, cancels and sells nothing."""
    at = parse_utc(as_of)
    if at is None:
        raise ValueError("as_of must be timezone-aware")
    reasons: list[str] = []
    prov: dict[str, Any] = {
        "evaluator": EVALUATOR_VERSION, "policy_id": policy.policy_id, "policy_version": policy.version,
        "policy_kind": policy.kind.value, "as_of_utc": at.isoformat(), "rules_version": rules_version,
        "inventory_evidence": None if inventory is None else inventory.evidence_id,
        "inventory_kind": None if inventory is None else inventory.kind.value,
        "book_evidence": None if book is None else book.evidence_id,
        "book_data_kind": None if book is None else book.data_kind.value,
        "fee_model": None if fee_model is None else fee_model.model_id,
    }

    def decide(status: DecisionStatus, action: Action | None, qty: Decimal = Decimal(0), limit: Decimal | None = None,
               *, gross: Decimal | None = None, fee: Decimal | None = None, net: Decimal | None = None,
               execution: ExecutionAssumption = ExecutionAssumption.NONE) -> PolicyDecision:
        blocked = status in (DecisionStatus.BLOCKED, DecisionStatus.UNSUPPORTED)
        basis = ClaimBasis.NONE.value if fee_model is None or net is None else fee_model.claim_basis.value
        key = repr((sorted(prov.items()), status.value, None if action is None else action.value, str(qty),
                    str(limit), str(gross), str(fee), str(net), reasons))
        return PolicyDecision(
            decision_id="pd-" + hashlib.sha256(key.encode()).hexdigest()[:24],
            status=status, action=action, quantity=qty, limit_price=limit, reasons=tuple(reasons),
            execution=execution, gross_proceeds=gross, fee=fee, net_proceeds=net, fee_claim_basis=basis,
            no_new_risk=True, review_required=blocked, provenance=prov)

    # 1. the policy itself
    if policy.kind not in SUPPORTED_KINDS:
        reasons.append(f"POLICY_UNSUPPORTED: {policy.kind.value} needs an independently justified model "
                       "or separately reviewed controls; no probability is invented")
        return decide(DecisionStatus.UNSUPPORTED, None)
    problems = policy.problems()
    if problems:
        reasons.extend(f"POLICY_INVALID: {p}" for p in problems)
        return decide(DecisionStatus.UNSUPPORTED, None)
    if rules_version is None:
        reasons.append("RULES_VERSION_UNKNOWN: the contract rules this position settles under are not pinned")

    # 2. inventory
    if inventory is None or not _known_qty(inventory.quantity) or not _known_qty(inventory.initial_quantity) \
            or inventory.side not in ("YES", "NO"):
        reasons.append("INVENTORY_UNKNOWN")
        return decide(DecisionStatus.BLOCKED, None)
    inv_at = parse_utc(inventory.as_of_utc)
    if inv_at is None or inv_at > at or at - inv_at > policy.max_inventory_age:
        reasons.append(f"INVENTORY_STALE: as of {inventory.as_of_utc}")
    if inventory.quantity > inventory.initial_quantity:
        reasons.append("INVENTORY_ABOVE_INITIAL: additions are out of scope in v1")
    if inventory.quantity == 0 and not reasons:
        reasons.append("NO_POSITION")
        return decide(DecisionStatus.NO_POSITION, None)

    # 3. orders that may consume it
    mine = [o for o in orders if o.market_id == inventory.market_id and o.side == inventory.side]
    reserved = Decimal(0)
    for o in mine:
        if not isinstance(o.state, OrderState) or not _known_qty(o.remaining):
            reasons.append(f"ORDER_UNKNOWN: {o.order_id}")
            continue
        if o.state in (OrderState.PENDING, OrderState.OUTCOME_UNKNOWN):
            reasons.append(f"ORDER_UNRECONCILED: {o.order_id} is {o.state.value}; reconcile before any new sale")
        if o.state in OPEN_ORDER_STATES and o.is_sale:
            reserved += o.remaining
    if any(r.startswith(("ORDER_", "INVENTORY_", "RULES_")) for r in reasons):
        return decide(DecisionStatus.BLOCKED, None)
    if reserved > inventory.quantity:
        reasons.append(f"OVER_RESERVED: {reserved} reserved by resting sales > {inventory.quantity} held; a sale "
                       "that is not reduce-only could open the opposite side")
        return decide(DecisionStatus.BLOCKED, None)
    available = inventory.quantity - reserved
    prov["reserved"] = str(reserved)
    prov["available"] = str(available)

    # 4. hold-to-settlement needs nothing else
    if policy.kind is PolicyKind.HOLD_TO_SETTLEMENT:
        reasons.append("HOLD_TO_SETTLEMENT")
        return decide(DecisionStatus.PROPOSED, Action.HOLD)

    # 5. how much this policy still wants to sell
    if policy.kind is PolicyKind.FIXED_TARGET_FULL_EXIT:
        wanted = available
    else:
        goal = _floor_step(policy.exit_fraction * inventory.initial_quantity, policy.quantity_step)
        already = inventory.initial_quantity - inventory.quantity
        wanted = max(Decimal(0), goal - already - reserved)
        wanted = min(wanted, available)
    wanted = _floor_step(wanted, policy.quantity_step)
    if wanted <= 0:
        reasons.append("NOTHING_LEFT_TO_SELL: the policy's quantity is already sold or reserved"
                       if reserved or inventory.quantity < inventory.initial_quantity
                       else "BELOW_QUANTITY_STEP")
        return decide(DecisionStatus.PROPOSED, Action.HOLD)

    # 6. game state, only if the policy needs it
    if policy.requires_game_state:
        gs_at = None if game_state is None else parse_utc(game_state.as_of_utc)
        if gs_at is None or gs_at > at or at - gs_at > policy.max_book_age:
            reasons.append("GAME_STATE_MISSING_OR_STALE")
            return decide(DecisionStatus.BLOCKED, None)
    if state_validity is not None:
        prov["state_version"] = state_validity.state_version
        prov["state_validity"] = state_validity.status.value
        checked = parse_utc(state_validity.checked_at_utc)
        if checked is None or checked != at:
            reasons.append(f"STATE_VALIDITY_NOT_AT_AS_OF: checked at {state_validity.checked_at_utc}, decision as of "
                           f"{at.isoformat()}; revalidate at the decision time")
            return decide(DecisionStatus.BLOCKED, None)
        if not state_validity.usable:
            reasons.extend(f"STATE_{state_validity.status.value}: {r.value}: {d}" for r, d in state_validity.reasons)
            reasons.append("RECOMPUTE_REQUIRED: a recommendation on the old state is not reused; nothing is cancelled "
                           "or sold because of this")
            return decide(DecisionStatus.BLOCKED, None)

    # 7. the book: every problem blocks; none of them triggers a sale
    if book is None or book.market_id != inventory.market_id or book.side != inventory.side:
        reasons.append("BOOK_MISSING")
    else:
        received = parse_utc(book.received_at_utc)
        if book.status is not BookStatus.VALID:
            reasons.append(f"BOOK_UNUSABLE: {book.status.value}")
        if received is None or received > at or at - received > policy.max_book_age:
            reasons.append(f"BOOK_STALE: received {book.received_at_utc}")
        if book.trading_state is not TradingState.OPEN:
            reasons.append(f"MARKET_NOT_TRADING: {book.trading_state.value}")
    if reasons:
        return decide(DecisionStatus.BLOCKED, None)
    prov["book_received_utc"] = book.received_at_utc

    target = policy.target_price
    full = wanted == inventory.quantity
    if policy.execution is ExecutionAssumption.PREPLACED_RESTING_LIMIT:
        # A resting sale is placed once; later calls see it as reserved inventory (step 5).
        reasons.append(f"PLACE_RESTING_SALE at {target}: a resting order is not a fill; queue and fill are unknown")
        reasons.append("NOT_REDUCE_ONLY: docs accept reduce_only only with immediate_or_cancel, so this inventory "
                       "must stay reserved against every other sale")
        return decide(DecisionStatus.PROPOSED, Action.EXIT if full else Action.REDUCE, wanted, target,
                      execution=ExecutionAssumption.PREPLACED_RESTING_LIMIT)

    # BOT_TRIGGERED_IOC: act only on bids at or above the target, as displayed now
    at_target = depth_at_or_above(book.bids, target)
    best = book.bids[-1][0] if book.bids else None
    if at_target <= 0:
        reasons.append(f"TARGET_NOT_EXECUTABLE: best bid {best} < target {target}" if best is not None
                       else "NO_BID: an empty bid side is not a price")
        return decide(DecisionStatus.PROPOSED, Action.HOLD)
    qty = min(wanted, _floor_step(at_target, policy.quantity_step))
    if qty <= 0:
        reasons.append(f"TARGET_DEPTH_BELOW_STEP: {at_target} at or above {target}")
        return decide(DecisionStatus.PROPOSED, Action.HOLD)
    walk = walk_bids(book.bids, qty, min_price=target, truncated=book.truncated,
                     market_id=book.market_id, side=book.side)
    if walk.status is not DepthStatus.FILLABLE:  # cannot happen after the depth check; fail closed anyway
        reasons.append(f"WALK_{walk.status.value}: {walk.detail}")
        return decide(DecisionStatus.BLOCKED, None)
    if qty < wanted:
        reasons.append(f"DEPTH_LIMITED: {at_target} displayed at or above {target} < {wanted} wanted"
                       + ("; deeper levels were not captured" if book.truncated else ""))
    # one taker fill per level taken, each with its own fee; any unknown level fee makes the total unknown
    level_fees = [None] if fee_model is None else [fee_model.sale_fee(s, p) for p, s in walk.levels]
    fee = None if any(f is None for f in level_fees) else sum(level_fees, Decimal(0))
    if fee is None:
        reasons.append("FEE_UNKNOWN: after-cost proceeds unavailable; gross is a labelled diagnostic")
    reasons.append(f"TARGET_REACHED: {at_target} contracts bid at or above {target}; a displayed bid is not a fill")
    net = None if fee is None else walk.gross_proceeds - fee
    return decide(DecisionStatus.PROPOSED, Action.EXIT if qty == inventory.quantity else Action.REDUCE, qty, target,
                  gross=walk.gross_proceeds, fee=fee, net=net, execution=ExecutionAssumption.BOT_TRIGGERED_IOC)
