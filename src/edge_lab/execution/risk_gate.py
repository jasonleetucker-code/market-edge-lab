"""The pre-send risk gate (#160 package I, ADR 0044). Pure: no I/O, no clock, no state of its own.

`evaluate(intent, ...)` decides whether one `OrderIntent` may proceed, from typed immutable inputs:
- an `AccountProjection`: the venue account snapshot plus the journal's held reservations
  (`project_account` builds one from `reservations`);
- a `MarketState`: status, grids, the book and the fee identity of one market;
- the money limits of `risk.RiskPolicy`, the order-rate and age limits of `execution_ticket.TicketLimits`,
  and a small `GateLimits` for what neither has;
- `DecisionEvidence`: the strategy and model versions, the decision time and source freshness.

It returns a `GateDecision`: `allowed`, and every failing check as a `Violation`, ordered by `Reason`
declaration order. The first is the primary reason (the `execution_ticket.pre_submit_checks` style). There is
no force or bypass argument. Only a naive `now` raises; a malformed input fails a named check.
`revalidate(intent, grant, ...)` adds the approval binding (`ApprovalGrant.problems`) for the moment just before
sending.

**One owner per formula.** Nothing here re-derives a formula another module owns:
- fees: `fee_schedules.schedule_for`, `verification_at` and the schedule's own `taker_buy`;
- cash capacity and the reserve floor: `execution_ticket.reserve_simultaneous_obligations`, with the cash above
  `RiskPolicy.reserve_floor` as the available cash;
- exposure sums per market, event, cluster and strategy: the same function's per-key sums (`by_key`), no netting;
- loss limits, drawdown and remaining capacity: `risk.assess` on a projection-backed `risk.RiskAccount`;
- inventory: `reservations.ReservationAuthority._inventory`, called by `project_account`;
- grids and direction: `conformance.MarketTradingProfile.check_yes_price` and `kalshi_wire.yes_terms`.

**Worst cases.**
- A new ENTRY can lose its whole `max_total_cost`.
- A held position can still lose at most $1 per contract (a binary's maximum value), whatever it cost. Its
  original purchase cost is never the remaining-risk measure: it says nothing about what is still at stake.
- A pending local ENTRY counts its full `max_total_cost` until the reservation is released, even after partial
  fills (which then also appear as a position): double counting is conservative.
- An external open order can add at most $1 per remaining contract, whatever its side or action.
- A REDUCTION is reduce-only (the venue refuses one that would increase a position), so it adds no exposure. It
  is not checked against exposure or loss limits: cutting risk is never blocked by them. It still needs its
  inventory, its fee bound in cash above the reserve floor, a healthy reconciliation, the book and rate checks.
- An exposure whose market, event, cluster or strategy is unknown counts toward the candidate's own key on that
  dimension: unknown is never zero, and never "elsewhere".

**No flip.** An ENTRY is refused while the account holds, or could come to hold, the opposite side of the same
market: an opposite-side position, a pending local opposite ENTRY, or any external order on the market (or on an
unknown market) other than a known buy of the candidate's side.

**Loss limits** (`risk.assess`) are measured on realized P&L only, as cumulative P&L since the account's inception
(`pnl_history_since_utc`). Deposits and withdrawals are listed for audit but are never P&L: they cannot offset a
loss or reset a limit. Unknown history (None) allows no new risk.

**Restart.** Every count (orders per window, cooldown, daily new risk) comes from the persisted inputs
(`AccountProjection.order_history`). This module keeps no process memory.

**Owner-set limits.** `PLACEHOLDER_LIMITS`, `PLACEHOLDER_POLICY` and `PLACEHOLDER_TICKET_LIMITS` block every
order: zero caps, and `owner_approval_ref` None fails LIMITS_NOT_SET_BY_OWNER. Real values are owner decisions
(the activation packet).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from .. import fee_schedules
from ..execution_ticket import Obligation, ObligationState, TicketLimits, reserve_simultaneous_obligations
from ..risk import RiskPolicy, assess, equity_curve
from . import conformance
from .kalshi_wire import yes_terms
from .model import (MAX_DIGITS, Action, ApprovalGrant, ExactValueError, Grid, IntentKind, OrderIntent, Side,
                    TimeInForce, environment_authorized, exact_decimal, exact_product, parse_utc_text, utc_text)
from .reservations import AccountSnapshot, ReservationAuthority, ReservationView

PROJECTION_SCHEMA = "edge-lab-risk-account-projection/1"
MARKET_STATE_SCHEMA = "edge-lab-risk-market-state/1"
LIMITS_SCHEMA = "edge-lab-risk-gate-limits/1"
EVIDENCE_SCHEMA = "edge-lab-decision-evidence/1"
DECISION_SCHEMA = "edge-lab-risk-gate-decision/1"

ONE_DOLLAR = Decimal(1)  # a binary contract's maximum value: the most a held contract can still lose
DAY = timedelta(days=1)
# The venue each conformance profile trades on, for fee routing (`fee_schedules.schedule_for`).
PROFILE_VENUES: Mapping[str, str] = MappingProxyType({conformance.PROFILE_VERSION: "kalshi"})
MARKET_TYPES_SUPPORTED = frozenset({"binary"})  # MKT-01/MKT-06: scalar markets are unsupported
SETTLEMENT_BOUNDS_SUPPORTED = frozenset({"default"})  # MKT-03/MKT-07: floor markets are unsupported
OPEN_MARKET_STATUS = "active"  # MKT-02: the only status that accepts new orders


def _exact_context() -> Context:
    """Exact arithmetic: a result that would need rounding raises. A fresh context per use (no shared state)."""
    return Context(prec=2 * MAX_DIGITS + 10, traps=[InvalidOperation, Inexact, Rounded])


def _fee_context() -> Context:
    """For the fee owner's own rounding (quantize to its documented units): never the caller's thread context."""
    return Context(prec=2 * MAX_DIGITS + 10, traps=[InvalidOperation])


class Reason(str, Enum):
    """Rejection codes. Declaration order is the order of `GateDecision.reasons`; the first is primary."""

    # approval binding (revalidate only)
    APPROVAL_INVALID = "APPROVAL_INVALID"
    APPROVAL_DIGEST_MISMATCH = "APPROVAL_DIGEST_MISMATCH"  # the intent changed after approval
    APPROVAL_SCOPE_MISMATCH = "APPROVAL_SCOPE_MISMATCH"
    APPROVAL_FROM_FUTURE = "APPROVAL_FROM_FUTURE"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    # limits and policy
    LIMITS_NOT_SET_BY_OWNER = "LIMITS_NOT_SET_BY_OWNER"
    POLICY_INVALID = "POLICY_INVALID"  # a reused policy holds a float, bool, NaN or negative value
    POLICY_VERSION_MISMATCH = "POLICY_VERSION_MISMATCH"  # the intent or the limits name another policy
    ARITHMETIC_NOT_EXACT = "ARITHMETIC_NOT_EXACT"
    ENVIRONMENT_NOT_AUTHORIZED = "ENVIRONMENT_NOT_AUTHORIZED"  # model.environment_authorized
    # decision evidence
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"  # another strategy or version, or evidence the intent does not cite
    DECISION_STALE = "DECISION_STALE"
    SOURCE_STALE = "SOURCE_STALE"
    # the intent against the profile
    INTENT_EXPIRED = "INTENT_EXPIRED"
    PROFILE_UNSUPPORTED = "PROFILE_UNSUPPORTED"
    TIF_UNSUPPORTED = "TIF_UNSUPPORTED"
    REDUCE_ONLY_REQUIRES_IOC = "REDUCE_ONLY_REQUIRES_IOC"  # conformance ORD-09
    QUANTITY_OFF_GRID = "QUANTITY_OFF_GRID"
    QUANTITY_LIMIT = "QUANTITY_LIMIT"  # GateLimits.max_quantity_per_order
    # the market
    MARKET_UNKNOWN = "MARKET_UNKNOWN"
    MARKET_TYPE_UNSUPPORTED = "MARKET_TYPE_UNSUPPORTED"
    MARKET_STATE_STALE = "MARKET_STATE_STALE"
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    EXCHANGE_NOT_OPEN = "EXCHANGE_NOT_OPEN"
    PRICE_OFF_GRID = "PRICE_OFF_GRID"
    BOOK_MISSING = "BOOK_MISSING"
    BOOK_STALE = "BOOK_STALE"
    BOOK_DEPTH_INSUFFICIENT = "BOOK_DEPTH_INSUFFICIENT"  # IOC/FOK: depth at or better than the limit < quantity
    SLIPPAGE_LIMIT = "SLIPPAGE_LIMIT"
    # fees
    FEE_SCHEDULE_MISMATCH = "FEE_SCHEDULE_MISMATCH"
    FEE_SCHEDULE_UNSUPPORTED = "FEE_SCHEDULE_UNSUPPORTED"
    FEE_SCHEDULE_UNVERIFIED = "FEE_SCHEDULE_UNVERIFIED"
    FEE_HEADROOM_INSUFFICIENT = "FEE_HEADROOM_INSUFFICIENT"
    # the account
    ACCOUNT_UNKNOWN = "ACCOUNT_UNKNOWN"
    ACCOUNT_SCOPE_MISMATCH = "ACCOUNT_SCOPE_MISMATCH"
    ACCOUNT_SNAPSHOT_STALE = "ACCOUNT_SNAPSHOT_STALE"
    RECONCILIATION_UNHEALTHY = "RECONCILIATION_UNHEALTHY"
    CASH_UNKNOWN = "CASH_UNKNOWN"
    POSITIONS_UNKNOWN = "POSITIONS_UNKNOWN"
    FLIP_FORBIDDEN = "FLIP_FORBIDDEN"
    INVENTORY_UNKNOWN = "INVENTORY_UNKNOWN"
    INVENTORY_INSUFFICIENT = "INVENTORY_INSUFFICIENT"
    # exposure (ENTRY only)
    EXPOSURE_UNKNOWN = "EXPOSURE_UNKNOWN"
    EXPOSURE_PER_ORDER = "EXPOSURE_PER_ORDER"  # RiskPolicy.max_position_risk
    EXPOSURE_PER_MARKET = "EXPOSURE_PER_MARKET"  # RiskPolicy.max_position_risk, both sides of the market
    EXPOSURE_PER_EVENT = "EXPOSURE_PER_EVENT"
    EXPOSURE_PER_CLUSTER = "EXPOSURE_PER_CLUSTER"
    EXPOSURE_PER_STRATEGY = "EXPOSURE_PER_STRATEGY"  # GateLimits.max_strategy_risk
    EXPOSURE_ACCOUNT = "EXPOSURE_ACCOUNT"  # RiskPolicy.max_portfolio_risk
    # cash
    RESERVE_FLOOR = "RESERVE_FLOOR"
    CASH_CAPACITY_INSUFFICIENT = "CASH_CAPACITY_INSUFFICIENT"
    # losses and new risk (ENTRY only)
    PNL_HISTORY_UNKNOWN = "PNL_HISTORY_UNKNOWN"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    RISK_CAPACITY_INSUFFICIENT = "RISK_CAPACITY_INSUFFICIENT"  # risk.assess remaining_risk_capacity
    DAILY_NEW_RISK_LIMIT = "DAILY_NEW_RISK_LIMIT"
    # order rate (TicketLimits semantics, as in execution_ticket.pre_submit_checks)
    ORDER_HISTORY_UNKNOWN = "ORDER_HISTORY_UNKNOWN"
    TRADE_COUNT_LIMIT = "TRADE_COUNT_LIMIT"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"


# `risk.assess` breach codes and the gate reason each one is.
ASSESS_BREACHES: Mapping[str, Reason] = MappingProxyType({
    "RESERVE_FLOOR": Reason.RESERVE_FLOOR, "MAX_PORTFOLIO_RISK": Reason.EXPOSURE_ACCOUNT,
    "MAX_POSITION_RISK": Reason.EXPOSURE_PER_MARKET, "MAX_EVENT_RISK": Reason.EXPOSURE_PER_EVENT,
    "MAX_CLUSTER_RISK": Reason.EXPOSURE_PER_CLUSTER, "DAILY_LOSS_LIMIT": Reason.DAILY_LOSS_LIMIT,
    "WEEKLY_LOSS_LIMIT": Reason.WEEKLY_LOSS_LIMIT, "MAX_DRAWDOWN": Reason.MAX_DRAWDOWN,
})
# `ApprovalGrant.problems` prefixes. INTENT_EXPIRED is reported by `evaluate` itself.
APPROVAL_PROBLEMS: Mapping[str, Reason] = MappingProxyType({
    "APPROVAL_DIGEST_MISMATCH": Reason.APPROVAL_DIGEST_MISMATCH,
    "APPROVAL_SCOPE_MISMATCH": Reason.APPROVAL_SCOPE_MISMATCH,
    "APPROVAL_FROM_FUTURE": Reason.APPROVAL_FROM_FUTURE, "APPROVAL_EXPIRED": Reason.APPROVAL_EXPIRED,
    "INTENT_EXPIRED": Reason.INTENT_EXPIRED,
})


# ---------------------------------------------------------------------------------------------- validation


def _label(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 200:
        raise ValueError(f"{name} must be a short non-empty label, not {value!r}")
    return value


def _amount(value: object, name: str, *, optional: bool = False, signed: bool = False,
            positive: bool = False) -> Decimal | None:
    """An exact Decimal (never float, bool, NaN or infinity), non-negative unless `signed`."""
    if value is None:
        if optional:
            return None
        raise ExactValueError(f"{name} is required; unknown is None only where the field allows it")
    d = exact_decimal(value, name=name)
    if not signed and d < 0:
        raise ExactValueError(f"{name} must not be negative: {d}")
    if positive and d <= 0:
        raise ExactValueError(f"{name} must be positive: {d}")
    return d


def _stamp(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be ISO-8601 text with a zone, not {value!r}")
    parse_utc_text(value)
    return value


def _duration(value: object, name: str) -> timedelta:
    if not isinstance(value, timedelta) or value < timedelta(0):
        raise ValueError(f"{name} must be a non-negative timedelta, not {value!r}")
    return value


def _flag(value: object, name: str, *, optional: bool = False) -> bool | None:
    if value is None and optional:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool{' or None' if optional else ''}, not {value!r}")
    return value


def _tuple_of(value: object, kind: type, name: str, *, optional: bool = False) -> tuple | None:
    if value is None and optional:
        return None
    if not isinstance(value, tuple) or not all(isinstance(v, kind) for v in value):
        raise ValueError(f"{name} must be a tuple of {kind.__name__}")
    return value


def _schema(value: object, expected: str) -> None:
    if value != expected:
        raise ValueError(f"unknown schema {value!r} (expected {expected!r})")


# ---------------------------------------------------------------------------------------------- the account


@dataclass(frozen=True)
class HeldPosition:
    """Contracts of one side of one market that the venue snapshot says are held. Strictly positive."""

    market_ticker: str
    side: Side
    quantity: Decimal
    event_key: str | None  # None: unknown; counted toward the candidate's event
    cluster_key: str | None
    strategy_id: str | None = None  # None: unattributed; counted toward every strategy

    def __post_init__(self) -> None:
        _label(self.market_ticker, "market_ticker")
        if not isinstance(self.side, Side):
            raise ValueError("side must be a Side")
        object.__setattr__(self, "quantity", _amount(self.quantity, "position quantity", positive=True))
        for name in ("event_key", "cluster_key", "strategy_id"):
            _label(getattr(self, name), name, optional=True)


class CommitmentOrigin(str, Enum):
    LOCAL = "LOCAL"  # a held reservation of our own journal
    EXTERNAL = "EXTERNAL"  # an open order the snapshot lists that no local attempt owns


@dataclass(frozen=True)
class Commitment:
    """An obligation that can still bind: a held local reservation or an external open order.

    `cash_worst_case` is the cash it can still consume that `AccountProjection.cash` does not already reflect;
    `risk_worst_case` is the loss exposure it adds if it binds (0 for a local REDUCTION). None is unknown."""

    commitment_id: str
    origin: CommitmentOrigin
    state: ObligationState
    kind: IntentKind | None  # LOCAL only; an external order has no intent kind
    market_ticker: str | None
    side: Side | None
    action: Action | None
    remaining_quantity: Decimal | None
    cash_worst_case: Decimal | None
    risk_worst_case: Decimal | None
    event_key: str | None
    cluster_key: str | None
    strategy_id: str | None
    quarantined: bool = False

    def __post_init__(self) -> None:
        _label(self.commitment_id, "commitment_id")
        if not isinstance(self.origin, CommitmentOrigin):
            raise ValueError("origin must be a CommitmentOrigin")
        if not isinstance(self.state, ObligationState) or self.state is ObligationState.RELEASED:
            raise ValueError("state must be a held ObligationState (RELEASED is not a commitment)")
        for name, enum in (("kind", IntentKind), ("side", Side), ("action", Action)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, enum):
                raise ValueError(f"{name} must be a {enum.__name__} or None")
        if self.origin is CommitmentOrigin.LOCAL and None in (self.kind, self.market_ticker, self.side, self.action):
            raise ValueError("a local commitment knows its kind, market, side and action")
        if self.origin is CommitmentOrigin.EXTERNAL and self.kind is not None:
            raise ValueError("an external order has no intent kind")
        for name in ("market_ticker", "event_key", "cluster_key", "strategy_id"):
            _label(getattr(self, name), name, optional=True)
        for name in ("remaining_quantity", "cash_worst_case", "risk_worst_case"):
            object.__setattr__(self, name, _amount(getattr(self, name), name, optional=True))
        _flag(self.quarantined, "quarantined")


class LedgerKind(str, Enum):
    REALIZED_PNL = "REALIZED_PNL"  # a settled or closed result, fees included; the only kind that is P&L
    DEPOSIT = "DEPOSIT"  # cash in: never P&L, never offsets a loss
    WITHDRAWAL = "WITHDRAWAL"  # cash out: never P&L, never a loss


@dataclass(frozen=True)
class LedgerEntry:
    entry_ref: str
    at_utc: str
    kind: LedgerKind
    amount: Decimal  # REALIZED_PNL is signed (a loss is negative); transfers are positive amounts

    def __post_init__(self) -> None:
        _label(self.entry_ref, "entry_ref")
        _stamp(self.at_utc, "at_utc")
        if not isinstance(self.kind, LedgerKind):
            raise ValueError("kind must be a LedgerKind")
        object.__setattr__(self, "amount", _amount(self.amount, "amount", signed=self.kind is LedgerKind.REALIZED_PNL,
                                                   positive=self.kind is not LedgerKind.REALIZED_PNL))


@dataclass(frozen=True)
class OrderHistoryEntry:
    """One of our own orders (a send attempt), from the persisted journal. Every attempt counts, failed ones too.
    The candidate is not in the history until it has an attempt of its own; an earlier attempt of the same intent
    is, and counts toward its cooldown."""

    order_ref: str
    market_ticker: str
    kind: IntentKind
    created_at_utc: str | None  # None: unknown, so no count can be trusted
    new_risk: Decimal  # an ENTRY's max_total_cost; 0 for a REDUCTION

    def __post_init__(self) -> None:
        _label(self.order_ref, "order_ref")
        _label(self.market_ticker, "market_ticker")
        if not isinstance(self.kind, IntentKind):
            raise ValueError("kind must be an IntentKind")
        _stamp(self.created_at_utc, "created_at_utc", optional=True)
        object.__setattr__(self, "new_risk", _amount(self.new_risk, "new_risk"))


@dataclass(frozen=True)
class InventoryLine:
    """What a REDUCTION of (market, side) may sell, from `reservations`' inventory rule. None: unknown."""

    market_ticker: str
    side: Side
    available: Decimal | None

    def __post_init__(self) -> None:
        _label(self.market_ticker, "market_ticker")
        if not isinstance(self.side, Side):
            raise ValueError("side must be a Side")
        object.__setattr__(self, "available", _amount(self.available, "available", optional=True, signed=True))


@dataclass(frozen=True)
class AccountProjection:
    """One account scope as the gate sees it. Every unknown is None (or `consistent=False`), never zero.

    `pnl_history_since_utc` is the account's inception: every realized P&L entry since then is listed, so the
    trailing loss windows and the drawdown peak are complete."""

    projection_id: str
    scope_key: str
    snapshot_revision: int | None
    observed_at_utc: str | None  # the account snapshot's venue time; None: no snapshot
    consistent: bool
    problems: tuple[str, ...]
    cash: Decimal | None  # spendable after the venue's holds; None: unknown value or basis
    positions: tuple[HeldPosition, ...] | None
    commitments: tuple[Commitment, ...]
    external_orders_known: bool
    inventory: tuple[InventoryLine, ...]
    pnl_history: tuple[LedgerEntry, ...] | None
    pnl_history_since_utc: str | None
    order_history: tuple[OrderHistoryEntry, ...] | None
    schema: str = PROJECTION_SCHEMA

    def __post_init__(self) -> None:
        _schema(self.schema, PROJECTION_SCHEMA)
        _label(self.projection_id, "projection_id")
        _label(self.scope_key, "scope_key")
        if self.snapshot_revision is not None and (isinstance(self.snapshot_revision, bool)
                                                   or not isinstance(self.snapshot_revision, int)
                                                   or self.snapshot_revision < 1):
            raise ValueError("snapshot_revision must be a positive int or None")
        _stamp(self.observed_at_utc, "observed_at_utc", optional=True)
        _flag(self.consistent, "consistent")
        _flag(self.external_orders_known, "external_orders_known")
        if not isinstance(self.problems, tuple) or not all(isinstance(p, str) for p in self.problems):
            raise ValueError("problems must be a tuple of str")
        object.__setattr__(self, "cash", _amount(self.cash, "cash", optional=True, signed=True))
        _tuple_of(self.positions, HeldPosition, "positions", optional=True)
        _tuple_of(self.commitments, Commitment, "commitments")
        _tuple_of(self.inventory, InventoryLine, "inventory")
        _tuple_of(self.pnl_history, LedgerEntry, "pnl_history", optional=True)
        _stamp(self.pnl_history_since_utc, "pnl_history_since_utc", optional=True)
        _tuple_of(self.order_history, OrderHistoryEntry, "order_history", optional=True)
        if len({c.commitment_id for c in self.commitments}) != len(self.commitments):
            raise ValueError("commitment ids must be unique")
        keys = [(p.market_ticker, p.side) for p in self.positions or ()]
        if len(set(keys)) != len(keys):
            raise ValueError("one position per (market, side)")
        lines = [(i.market_ticker, i.side) for i in self.inventory]
        if len(set(lines)) != len(lines):
            raise ValueError("one inventory line per (market, side)")
        if self.positions is None and self.inventory:
            raise ValueError("inventory cannot be known while positions are unknown")


@dataclass(frozen=True)
class MarketKeys:
    """The grouping keys of one market, from its market record."""

    event_key: str | None
    cluster_key: str | None

    def __post_init__(self) -> None:
        _label(self.event_key, "event_key", optional=True)
        _label(self.cluster_key, "cluster_key", optional=True)


def project_account(scope_key: str, snapshot: AccountSnapshot | None, held: Iterable[ReservationView], *,
                    projection_id: str, intents: Mapping[str, OrderIntent], market_keys: Mapping[str, MarketKeys],
                    pnl_history: tuple[LedgerEntry, ...] | None, pnl_history_since_utc: str | None,
                    order_history: tuple[OrderHistoryEntry, ...] | None) -> AccountProjection:
    """Build the projection from `reservations`' latest snapshot and held reservations (`held_reservations`).

    `intents` (by intent key) attributes local reservations to strategies; `market_keys` (by ticker) gives the
    event and cluster of every market involved. Anything missing from them is unknown and counts toward the
    candidate (see the module docstring). The ledger and order histories come from the persisted journal or the
    venue's account history (package G); this function does not read a store."""
    held = tuple(held)
    if snapshot is not None and snapshot.scope_key != scope_key:
        raise ValueError("the snapshot is for another scope")
    if any(r.scope_key != scope_key or r.state is ObligationState.RELEASED for r in held):
        raise ValueError("held reservations must be this scope's, and none RELEASED")

    def keys(ticker: str | None) -> tuple[str | None, str | None]:
        k = market_keys.get(ticker) if ticker is not None else None
        return (k.event_key, k.cluster_key) if isinstance(k, MarketKeys) else (None, None)

    commitments: list[Commitment] = []
    with localcontext(_exact_context()):
        for r in held:
            quarantined = r.quarantine_reason is not None
            # Cash: the same obligation `reservations` builds at reserve time (its `_evaluate`): unknown while
            # quarantined, the venue-unreflected residual while provider-held, otherwise the full worst case.
            cash: Decimal | None = r.cash_worst_case
            if quarantined:
                cash = None
            elif r.provider_held and snapshot is not None and r.reservation_id in snapshot.attributed:
                cash = snapshot.attributed[r.reservation_id].unreflected_cash
            cash = None if cash is not None and cash < 0 else cash
            risk = None if quarantined else (r.cash_worst_case if r.kind is IntentKind.ENTRY else Decimal(0))
            intent = intents.get(r.intent_key)
            event, cluster = keys(r.market_ticker)
            remaining = r.quantity - r.filled_quantity
            commitments.append(Commitment(
                f"local:{r.reservation_id}", CommitmentOrigin.LOCAL, r.state, r.kind, r.market_ticker, r.side,
                Action.BUY if r.kind is IntentKind.ENTRY else Action.SELL, remaining if remaining >= 0 else None,
                cash, risk, event, cluster, intent.strategy_id if isinstance(intent, OrderIntent) else None,
                quarantined))
        externals_known = snapshot is not None and snapshot.external_orders is not None
        for n, e in enumerate(snapshot.external_orders or () if snapshot is not None else ()):
            cash = None if e.unreflected_cash is not None and e.unreflected_cash < 0 else e.unreflected_cash
            qty = e.remaining_quantity if e.remaining_quantity is not None and e.remaining_quantity >= 0 else None
            event, cluster = keys(e.market_ticker)
            commitments.append(Commitment(
                f"external:{n}:{e.order_ref}", CommitmentOrigin.EXTERNAL, ObligationState.OUTSTANDING, None,
                e.market_ticker, e.side, e.action, qty, cash, None if qty is None else qty * ONE_DOLLAR,
                event, cluster, None))

        positions: tuple[HeldPosition, ...] | None = None
        inventory: list[InventoryLine] = []
        if snapshot is not None and snapshot.positions is not None:
            positions = tuple(HeldPosition(t, s, q, *keys(t)) for (t, s), q in sorted(
                snapshot.positions.items(), key=lambda kv: (kv[0][0], kv[0][1].value)) if q > 0)
            wanted = set(snapshot.positions) | {(r.market_ticker, r.side) for r in held
                                                if r.kind is IntentKind.REDUCTION}
            wanted |= {(e.market_ticker, e.side) for e in snapshot.external_orders or ()
                       if e.market_ticker is not None and e.side is not None}
            for ticker, side in sorted(wanted, key=lambda k: (k[0], k[1].value)):
                # The canonical inventory rule (reservations): position - held reductions - external sells.
                available, why = ReservationAuthority._inventory(snapshot, list(held), ticker, side)
                inventory.append(InventoryLine(ticker, side, None if why else available))

    return AccountProjection(
        projection_id=projection_id, scope_key=scope_key,
        snapshot_revision=None if snapshot is None else snapshot.revision,
        observed_at_utc=None if snapshot is None else snapshot.observed_at_utc,
        consistent=snapshot is not None and snapshot.consistent,
        problems=("NO_ACCOUNT_SNAPSHOT",) if snapshot is None else tuple(snapshot.problems),
        cash=None if snapshot is None else snapshot.usable_cash(), positions=positions,
        commitments=tuple(commitments), external_orders_known=externals_known, inventory=tuple(inventory),
        pnl_history=pnl_history, pnl_history_since_utc=pnl_history_since_utc, order_history=order_history)


# ---------------------------------------------------------------------------------------------- the market


@dataclass(frozen=True)
class BookLevel:
    price: Decimal  # dollars per contract of the book side's outcome, strictly inside (0, 1)
    size: Decimal  # contracts, positive

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _amount(self.price, "level price", positive=True))
        if self.price >= 1:
            raise ExactValueError(f"level price {self.price} must be below 1 dollar")
        object.__setattr__(self, "size", _amount(self.size, "level size", positive=True))


@dataclass(frozen=True)
class BookState:
    """The best levels of one market's book, per outcome side, in that side's own price.

    `*_asks` are offers to sell us that side (ascending price); `*_bids` are offers to buy it from us
    (descending). None: not observed (unknown); (): observed empty. The book adapter converts the venue's
    YES/NO bid books into this form (package J)."""

    snapshot_id: str
    as_of_utc: str
    yes_asks: tuple[BookLevel, ...] | None
    yes_bids: tuple[BookLevel, ...] | None
    no_asks: tuple[BookLevel, ...] | None
    no_bids: tuple[BookLevel, ...] | None

    def __post_init__(self) -> None:
        _label(self.snapshot_id, "snapshot_id")
        _stamp(self.as_of_utc, "as_of_utc")
        for name, ascending in (("yes_asks", True), ("yes_bids", False), ("no_asks", True), ("no_bids", False)):
            levels = _tuple_of(getattr(self, name), BookLevel, name, optional=True)
            prices = [lv.price for lv in levels or ()]
            ordered = all((a < b) if ascending else (a > b) for a, b in zip(prices, prices[1:]))
            if not ordered:
                raise ValueError(f"{name} must be strictly {'ascending' if ascending else 'descending'} by price")

    def levels(self, side: Side, action: Action) -> tuple[BookLevel, ...] | None:
        """The levels an order of `side`/`action` trades against: a buy takes asks, a sell takes bids."""
        if side is Side.YES:
            return self.yes_asks if action is Action.BUY else self.yes_bids
        return self.no_asks if action is Action.BUY else self.no_bids


@dataclass(frozen=True)
class MarketState:
    """One market as the gate needs it, from its market record (conformance profile) and book."""

    state_id: str
    ticker: str
    as_of_utc: str
    market_type: str
    settlement_bounds_type: str
    status: str
    exchange_active: bool | None  # PAU-04; None: unknown
    trading_active: bool | None
    exchange_index: int
    price_bands: tuple[Grid, ...]  # YES-price bands from `price_ranges` (PX-01)
    event_key: str | None
    cluster_key: str | None
    fee_scope: str | None  # the fee scope (a Kalshi series ticker)
    fee_schedule_id: str | None
    book: BookState | None
    schema: str = MARKET_STATE_SCHEMA

    def __post_init__(self) -> None:
        _schema(self.schema, MARKET_STATE_SCHEMA)
        for name in ("state_id", "ticker", "market_type", "settlement_bounds_type", "status"):
            _label(getattr(self, name), name)
        _stamp(self.as_of_utc, "as_of_utc")
        _flag(self.exchange_active, "exchange_active", optional=True)
        _flag(self.trading_active, "trading_active", optional=True)
        for name in ("event_key", "cluster_key", "fee_scope", "fee_schedule_id"):
            _label(getattr(self, name), name, optional=True)
        _tuple_of(self.price_bands, Grid, "price_bands")
        conformance.MarketTradingProfile(self.ticker, self.exchange_index, self.price_bands)  # validates shard, bands
        if self.book is not None and not isinstance(self.book, BookState):
            raise ValueError("book must be a BookState or None")


# ---------------------------------------------------------------------------------------------- limits, evidence


@dataclass(frozen=True)
class GateLimits:
    """Only what neither `risk.RiskPolicy` nor `execution_ticket.TicketLimits` has. Owner-set values only:
    `owner_approval_ref` names the recorded owner decision; None fails every order (LIMITS_NOT_SET_BY_OWNER)."""

    limits_id: str
    risk_policy_id: str  # the RiskPolicy these limits complete
    owner_approval_ref: str | None
    max_quantity_per_order: Decimal
    max_slippage: Decimal  # dollars per contract between the best price and the limit
    max_decision_age: timedelta
    max_source_age: timedelta
    daily_new_risk: Decimal  # new ENTRY risk over the trailing 24 h, this order included
    max_strategy_risk: Decimal
    schema: str = LIMITS_SCHEMA

    def __post_init__(self) -> None:
        _schema(self.schema, LIMITS_SCHEMA)
        _label(self.limits_id, "limits_id")
        _label(self.risk_policy_id, "risk_policy_id")
        _label(self.owner_approval_ref, "owner_approval_ref", optional=True)
        for name in ("max_quantity_per_order", "max_slippage", "daily_new_risk", "max_strategy_risk"):
            object.__setattr__(self, name, _amount(getattr(self, name), name))
        _duration(self.max_decision_age, "max_decision_age")
        _duration(self.max_source_age, "max_source_age")


@dataclass(frozen=True)
class SourceStamp:
    source_id: str
    as_of_utc: str

    def __post_init__(self) -> None:
        _label(self.source_id, "source_id")
        _stamp(self.as_of_utc, "as_of_utc")


@dataclass(frozen=True)
class DecisionEvidence:
    evidence_id: str  # must be among the intent's `evidence` references
    strategy_id: str
    strategy_version: str
    model_version: str
    decided_at_utc: str
    sources: tuple[SourceStamp, ...]
    schema: str = EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        _schema(self.schema, EVIDENCE_SCHEMA)
        for name in ("evidence_id", "strategy_id", "strategy_version", "model_version"):
            _label(getattr(self, name), name)
        _stamp(self.decided_at_utc, "decided_at_utc")
        _tuple_of(self.sources, SourceStamp, "sources")


# Ship-blocking defaults: zero caps and no owner reference. Real values are owner decisions.
PLACEHOLDER_ID = "placeholder-not-owner-set"
PLACEHOLDER_POLICY = RiskPolicy(PLACEHOLDER_ID, reserve_floor=Decimal(0), max_position_risk=Decimal(0),
                                max_event_risk=Decimal(0), max_cluster_risk=Decimal(0), max_portfolio_risk=Decimal(0),
                                daily_loss_limit=Decimal(0), weekly_loss_limit=Decimal(0), max_drawdown=Decimal(0))
PLACEHOLDER_TICKET_LIMITS = TicketLimits(max_book_age=timedelta(0), max_order_state_age=timedelta(0),
                                         max_orders_per_window=0, order_window=DAY, market_cooldown=DAY)
PLACEHOLDER_LIMITS = GateLimits(limits_id=PLACEHOLDER_ID, risk_policy_id=PLACEHOLDER_ID, owner_approval_ref=None,
                                max_quantity_per_order=Decimal(0), max_slippage=Decimal(0),
                                max_decision_age=timedelta(0), max_source_age=timedelta(0), daily_new_risk=Decimal(0),
                                max_strategy_risk=Decimal(0))


# ---------------------------------------------------------------------------------------------- the decision


@dataclass(frozen=True)
class Violation:
    code: Reason
    detail: str


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[Violation, ...]  # Reason declaration order; one entry per code
    intent_digest: str
    evaluated_at_utc: str
    inputs: tuple[tuple[str, str | None], ...]  # the version id of every input the decision used
    fee_required: Decimal | None = None  # the max_total_cost this intent needs (ENTRY: principal + fees)
    candidate_risk: Decimal | None = None
    cash_required: Decimal | None = None  # every held cash obligation plus this one, all binding at once
    risk_capacity: Decimal | None = None  # risk.assess remaining_risk_capacity
    schema: str = DECISION_SCHEMA

    def __post_init__(self) -> None:
        if self.allowed is not (not self.reasons):
            raise ValueError("a decision is allowed exactly when no check fails")

    @property
    def primary(self) -> Violation | None:
        return self.reasons[0] if self.reasons else None

    def codes(self) -> tuple[Reason, ...]:
        return tuple(v.code for v in self.reasons)


@dataclass(frozen=True)
class _RiskPosition:
    """A `risk.RiskPosition`: an open exposure, or a settled realized-P&L entry."""

    position_id: str
    opened_at_utc: str
    event_id: str
    outcome_cluster: str
    status: str
    cost_basis: Decimal
    max_downside: Decimal
    potential_payout: Decimal
    expected_settlement_utc: str | None
    net_pnl: Decimal | None
    settled_at_utc: str | None


@dataclass(frozen=True)
class _RiskView:
    """A `risk.RiskAccount` backed by the projection. Equity is cumulative realized P&L from a zero start, so the
    drawdown `risk.assess` measures is realized drawdown, untouched by deposits or withdrawals."""

    account_id: str
    starting_bankroll: Decimal
    settled_cash: Decimal
    committed_capital: Decimal
    open_worst_case_risk: Decimal
    equity: Decimal
    positions: tuple[_RiskPosition, ...]

    def open_positions(self) -> tuple[_RiskPosition, ...]:
        return tuple(p for p in self.positions if p.status == "OPEN")


def _policy_problems(policy: object, ticket_limits: object, limits: object) -> list[str]:
    """Reused policy types do not validate their own values exactly; the gate does, and refuses rather than
    compare a float, bool or NaN."""
    out = []
    if not isinstance(policy, RiskPolicy):
        return ["policy is not a risk.RiskPolicy"]
    if not isinstance(policy.policy_id, str) or not policy.policy_id:
        out.append("policy_id is not a label")
    for f in fields(policy):
        value = getattr(policy, f.name)
        if f.name != "policy_id" and (not isinstance(value, Decimal) or not value.is_finite() or value < 0):
            out.append(f"policy {f.name} {value!r} is not a finite, non-negative Decimal")
    if not isinstance(ticket_limits, TicketLimits):
        out.append("ticket_limits is not an execution_ticket.TicketLimits")
    else:
        for name in ("max_book_age", "max_order_state_age", "order_window", "market_cooldown"):
            value = getattr(ticket_limits, name)
            if not isinstance(value, timedelta) or value < timedelta(0):
                out.append(f"ticket limit {name} {value!r} is not a non-negative timedelta")
        n = ticket_limits.max_orders_per_window
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            out.append(f"max_orders_per_window {n!r} is not a non-negative int")
    if not isinstance(limits, GateLimits):
        out.append("limits is not a GateLimits")
    return out


def evaluate(intent: OrderIntent, *, account: AccountProjection | None, market: MarketState | None,
             policy: RiskPolicy, limits: GateLimits, ticket_limits: TicketLimits, evidence: DecisionEvidence | None,
             now: datetime) -> GateDecision:
    """Every failing check for `intent` at `now`, in `Reason` order; allowed only when none fails."""
    at = parse_utc_text(utc_text(now))  # a naive `now` raises: its zone is unknown
    if not isinstance(intent, OrderIntent):
        raise ValueError("intent must be an OrderIntent")
    found: dict[Reason, list[str]] = {}
    figures: dict[str, Decimal | None] = {}
    inputs: dict[str, str | None] = {"intent": intent.digest()}

    def fail(code: Reason, detail: str) -> None:
        found.setdefault(code, []).append(detail)

    def finish() -> GateDecision:
        order = tuple(Reason)
        reasons = tuple(Violation(code, "; ".join(found[code])) for code in sorted(found, key=order.index))
        return GateDecision(not reasons, reasons, intent.digest(), utc_text(at), tuple(sorted(inputs.items())),
                            figures.get("fee"), figures.get("risk"), figures.get("cash"), figures.get("capacity"))

    problems = _policy_problems(policy, ticket_limits, limits)
    if isinstance(limits, GateLimits) and limits.owner_approval_ref is None:
        fail(Reason.LIMITS_NOT_SET_BY_OWNER, f"{limits.limits_id}: no recorded owner decision set these limits")
    if problems:
        fail(Reason.POLICY_INVALID, "; ".join(problems))
        return finish()  # nothing below can be judged against a malformed policy
    inputs.update(policy=policy.policy_id, limits=limits.limits_id)
    try:
        with localcontext(_exact_context()):
            _checks(intent, account, market, policy, limits, ticket_limits, evidence, at, fail, figures, inputs)
    except (Inexact, Rounded, InvalidOperation) as exc:
        fail(Reason.ARITHMETIC_NOT_EXACT, f"{type(exc).__name__}: a result would need rounding")
    return finish()


def _age_bad(stamp: str | None, max_age: timedelta, at: datetime) -> bool:
    """Unknown, from the future, or older than `max_age` (exactly `max_age` old is still current), as in
    `execution_ticket.pre_submit_checks`: a check before sending has no reason to trust a clock that runs ahead."""
    if stamp is None:
        return True
    seen = parse_utc_text(stamp)
    return seen > at or at - seen > max_age


def _checks(intent: OrderIntent, account: AccountProjection | None, market: MarketState | None, policy: RiskPolicy,
            limits: GateLimits, tl: TicketLimits, evidence: DecisionEvidence | None, at: datetime, fail,
            figures: dict, inputs: dict) -> None:
    entry = intent.kind is IntentKind.ENTRY
    if intent.risk_policy_version != policy.policy_id or limits.risk_policy_id != policy.policy_id:
        fail(Reason.POLICY_VERSION_MISMATCH, f"intent {intent.risk_policy_version}, limits {limits.risk_policy_id}, "
                                             f"policy {policy.policy_id}")
    if not environment_authorized(intent.scope.environment):
        fail(Reason.ENVIRONMENT_NOT_AUTHORIZED, intent.scope.environment.value)

    # ---- decision evidence
    if not isinstance(evidence, DecisionEvidence):
        fail(Reason.EVIDENCE_MISSING, "no decision evidence")
    else:
        inputs["evidence"] = evidence.evidence_id
        if (evidence.strategy_id, evidence.strategy_version) != (intent.strategy_id, intent.strategy_version):
            fail(Reason.EVIDENCE_MISMATCH, f"evidence is for {evidence.strategy_id}/{evidence.strategy_version}")
        if evidence.evidence_id not in intent.evidence:
            fail(Reason.EVIDENCE_MISMATCH, f"the intent does not cite {evidence.evidence_id}")
        if _age_bad(evidence.decided_at_utc, limits.max_decision_age, at):
            fail(Reason.DECISION_STALE, f"decided {evidence.decided_at_utc}")
        stale = [s.source_id for s in evidence.sources if _age_bad(s.as_of_utc, limits.max_source_age, at)]
        if not evidence.sources or stale:
            fail(Reason.SOURCE_STALE, f"stale or future: {stale}" if stale else "no source freshness evidence")

    # ---- the intent against the profile
    if at >= intent.expires_at():
        fail(Reason.INTENT_EXPIRED, f"expired {intent.expires_at_utc}")
    venue = PROFILE_VENUES.get(intent.profile_version)
    if venue is None:
        fail(Reason.PROFILE_UNSUPPORTED, intent.profile_version)
    if intent.time_in_force not in conformance.SUPPORTED_TIME_IN_FORCE:
        fail(Reason.TIF_UNSUPPORTED, intent.time_in_force.value)
    if intent.reduce_only and intent.time_in_force not in conformance.REDUCE_ONLY_TIME_IN_FORCE:
        fail(Reason.REDUCE_ONLY_REQUIRES_IOC, f"reduce_only with {intent.time_in_force.value}")
    q = intent.quantity
    if q % conformance.QUANTITY_STEP != 0:
        fail(Reason.QUANTITY_OFF_GRID, f"{q} is not a multiple of {conformance.QUANTITY_STEP}")
    if q > limits.max_quantity_per_order:
        fail(Reason.QUANTITY_LIMIT, f"{q} > {limits.max_quantity_per_order}")

    # ---- the market and its book
    market_ok = isinstance(market, MarketState) and market.ticker == intent.market_ticker
    if not market_ok:
        fail(Reason.MARKET_UNKNOWN, f"no market state for {intent.market_ticker}")
    else:
        inputs["market"] = market.state_id
        _market_checks(intent, market, limits, tl, at, fail, inputs)
        if venue is not None:
            _fee_checks(intent, market, venue, at, fail, figures, inputs)

    # ---- the account
    if not isinstance(account, AccountProjection):
        fail(Reason.ACCOUNT_UNKNOWN, "no account projection")
        return
    if account.scope_key != intent.scope.key():
        fail(Reason.ACCOUNT_SCOPE_MISMATCH, f"projection is for {account.scope_key}, not {intent.scope.key()}")
        return
    inputs["projection"] = account.projection_id
    _account_checks(intent, account, market if market_ok else None, policy, limits, tl, at, fail, figures, entry)


def _market_checks(intent: OrderIntent, market: MarketState, limits: GateLimits, tl: TicketLimits, at: datetime,
                   fail, inputs: dict) -> None:
    if market.market_type not in MARKET_TYPES_SUPPORTED or market.settlement_bounds_type not in \
            SETTLEMENT_BOUNDS_SUPPORTED:
        fail(Reason.MARKET_TYPE_UNSUPPORTED, f"{market.market_type}/{market.settlement_bounds_type}")
    if _age_bad(market.as_of_utc, tl.max_book_age, at):
        fail(Reason.MARKET_STATE_STALE, f"market state as of {market.as_of_utc}")
    if market.status != OPEN_MARKET_STATUS:
        fail(Reason.MARKET_NOT_OPEN, market.status)
    if market.exchange_active is not True or market.trading_active is not True:
        fail(Reason.EXCHANGE_NOT_OPEN, f"exchange_active {market.exchange_active}, "
                                       f"trading_active {market.trading_active}")
    _, yes_price = yes_terms(intent.side, intent.action, intent.limit_price)
    try:
        conformance.MarketTradingProfile(market.ticker, market.exchange_index, market.price_bands) \
            .check_yes_price(yes_price)
    except (conformance.UnsupportedByProfile, ExactValueError) as exc:
        fail(Reason.PRICE_OFF_GRID, str(exc))

    book = market.book
    levels = None if book is None else book.levels(intent.side, intent.action)
    if levels is None:
        fail(Reason.BOOK_MISSING, f"no {intent.side.value} {'asks' if intent.action is Action.BUY else 'bids'}")
        return
    inputs["book"] = book.snapshot_id
    if _age_bad(book.as_of_utc, tl.max_book_age, at):
        fail(Reason.BOOK_STALE, f"book as of {book.as_of_utc}")
    buy, limit, q = intent.action is Action.BUY, intent.limit_price, intent.quantity
    if intent.time_in_force in (TimeInForce.IMMEDIATE_OR_CANCEL, TimeInForce.FILL_OR_KILL):
        reachable = [lv.size for lv in levels if (lv.price <= limit if buy else lv.price >= limit)]
        depth = sum(reachable, Decimal(0))
        if depth < q:  # exactly the quantity is enough
            fail(Reason.BOOK_DEPTH_INSUFFICIENT, f"{depth} at or better than {limit} < {q}")
    if levels:  # an empty side has no best price: a resting order there has no slippage
        best = levels[0].price
        slip = limit - best if buy else best - limit  # the worst fill is no further from the best than the limit
        if slip > limits.max_slippage:  # exactly the limit is allowed
            fail(Reason.SLIPPAGE_LIMIT, f"limit {limit} is {slip} beyond the best {best} > {limits.max_slippage}")


def _fee_checks(intent: OrderIntent, market: MarketState, venue: str, at: datetime, fail, figures: dict,
                inputs: dict) -> None:
    """`max_total_cost` must cover the most this order can cost under the versioned schedule:
    - ENTRY: the schedule's taker cost of quantity x limit (cost per contract rises with the fill price, so a
      fill at or below the limit costs no more), plus the verification's rounding allowance per contract;
    - REDUCTION: the largest fee at any sale price at or above the limit (p(1-p) peaks at 0.5) plus the
      allowance; a sale's proceeds are not cost.
    The schedule must be verified at `now` to a claim basis (CONSERVATIVE_BOUND or EXACT), and for an order that
    can rest (GTC) its maker fee must be verified too. Unverified or unsupported is rejected, never assumed."""
    if market.fee_schedule_id != intent.fee_schedule_version:
        fail(Reason.FEE_SCHEDULE_MISMATCH, f"market {market.fee_schedule_id}, intent {intent.fee_schedule_version}")
        return
    schedule = fee_schedules.schedule_for(venue, market.fee_scope, as_of=at)
    if isinstance(schedule, fee_schedules.UnsupportedFeeSchedule) or schedule.status is \
            fee_schedules.FeeScheduleStatus.UNSUPPORTED:
        fail(Reason.FEE_SCHEDULE_UNSUPPORTED, f"{schedule.schedule_id}: no fee model for {venue} {market.fee_scope}")
        return
    inputs["fee_schedule"] = schedule.schedule_id
    if schedule.schedule_id != intent.fee_schedule_version or schedule.scope_of(market.ticker) != market.fee_scope:
        fail(Reason.FEE_SCHEDULE_MISMATCH, f"{market.ticker} routes to {schedule.schedule_id} scope "
                                           f"{schedule.scope_of(market.ticker)}, not {intent.fee_schedule_version} "
                                           f"scope {market.fee_scope}")
        return
    state = fee_schedules.verification_at(schedule, at, native_id=market.ticker)
    inputs["fee_verification"] = state.verification_id
    allowance = state.rounding_allowance_per_contract
    if not state.claimable or allowance is None:
        fail(Reason.FEE_SCHEDULE_UNVERIFIED, state.detail)
        return
    if intent.time_in_force is TimeInForce.GOOD_TILL_CANCELED and not _maker_fee_verified(state):
        fail(Reason.FEE_SCHEDULE_UNVERIFIED, f"{state.verification_id}: a resting order may pay a maker fee, and the "
                                             "maker fee is not verified")
        return
    q = intent.quantity
    if q != q.to_integral_value():
        fail(Reason.FEE_SCHEDULE_UNSUPPORTED, f"quantity {q}: the schedule prices whole contracts only")
        return
    contracts = int(q)
    with localcontext(_fee_context()):
        if intent.kind is IntentKind.ENTRY:
            base = schedule.taker_buy(contracts, intent.limit_price).total_cost
        else:
            worst = max(intent.limit_price, Decimal("0.5"))
            base = schedule.taker_buy(contracts, worst).fee
    required = base + exact_product(allowance, q)
    figures["fee"] = required
    if intent.max_total_cost < required:  # exactly the requirement is enough
        fail(Reason.FEE_HEADROOM_INSUFFICIENT, f"max_total_cost {intent.max_total_cost} < {required} "
                                               f"({schedule.schedule_id}, allowance {allowance} per contract)")


def _maker_fee_verified(state: fee_schedules.FeeVerificationState) -> bool:
    if state.full_schedule_verified:
        return True
    for record in fee_schedules.FEE_VERIFICATIONS:
        if record.verification_id == state.verification_id:
            try:
                return record.component(fee_schedules.VerificationComponent.MAKER_FEES).state is \
                    fee_schedules.ComponentState.VERIFIED
            except KeyError:
                return False
    return False


def _account_checks(intent: OrderIntent, account: AccountProjection, market: MarketState | None,
                    policy: RiskPolicy, limits: GateLimits, tl: TicketLimits, at: datetime, fail, figures: dict,
                    entry: bool) -> None:
    ticker, side, q = intent.market_ticker, intent.side, intent.quantity
    if _age_bad(account.observed_at_utc, tl.max_order_state_age, at):
        fail(Reason.ACCOUNT_SNAPSHOT_STALE, f"snapshot revision {account.snapshot_revision} observed "
                                            f"{account.observed_at_utc}")
    unhealthy = list(account.problems) if not account.consistent else []
    unhealthy += [f"{c.commitment_id} quarantined" for c in account.commitments if c.quarantined]
    unhealthy += [f"{c.commitment_id} state unknown" for c in account.commitments
                  if c.state is ObligationState.UNKNOWN and not c.quarantined]
    if not account.external_orders_known:
        unhealthy.append("external open orders are not listed")
    if not account.consistent and not account.problems:
        unhealthy.append("the snapshot is inconsistent")
    if unhealthy:
        fail(Reason.RECONCILIATION_UNHEALTHY, "; ".join(unhealthy[:5]))
    if account.cash is None:
        fail(Reason.CASH_UNKNOWN, "available cash or its basis is unknown")
    if account.positions is None:
        fail(Reason.POSITIONS_UNKNOWN, "the snapshot does not list positions")

    if entry and account.positions is not None:
        opposite = Side.NO if side is Side.YES else Side.YES
        held = [p for p in account.positions if p.market_ticker == ticker and p.side is opposite]
        pending = [c.commitment_id for c in account.commitments if c.origin is CommitmentOrigin.LOCAL
                   and c.kind is IntentKind.ENTRY and c.market_ticker == ticker and c.side is opposite]
        external = [c.commitment_id for c in account.commitments if c.origin is CommitmentOrigin.EXTERNAL
                    and c.market_ticker in (ticker, None) and not (c.action is Action.BUY and c.side is side)]
        if held or pending or external:
            fail(Reason.FLIP_FORBIDDEN, f"holds {sum((p.quantity for p in held), Decimal(0))} {ticker} "
                                        f"{opposite.value}; pending opposite entries {pending}; external orders that "
                                        f"could hold the opposite side {external}")
    if not entry and account.positions is not None:
        line = next((i for i in account.inventory if i.market_ticker == ticker and i.side is side), None)
        if line is None and not account.external_orders_known:
            fail(Reason.INVENTORY_UNKNOWN, "open sells cannot be excluded")
        elif line is not None and line.available is None:
            fail(Reason.INVENTORY_UNKNOWN, f"{ticker} {side.value}: a held or external sell has an unknown size")
        else:
            available = Decimal(0) if line is None else line.available  # a complete listing without it: none held
            if q > available:  # exactly the inventory is allowed
                fail(Reason.INVENTORY_INSUFFICIENT, f"selling {q} {ticker} {side.value} > {available} held and "
                                                    "not already being sold")

    risk = intent.max_total_cost if entry else Decimal(0)
    figures["risk"] = risk
    if entry:
        _exposure_checks(intent, account, market, policy, limits, fail, risk)
    _cash_checks(intent, account, policy, fail, figures)
    if entry:
        _loss_checks(intent, account, market, policy, at, fail, figures, risk)
    _history_checks(intent, account, limits, tl, at, fail, entry, risk)


def _exposure_items(account: AccountProjection, intent: OrderIntent, market: MarketState):
    """(obligation id, state, worst case, keys) for every held exposure. An unknown dimension is the candidate's:
    an exposure that could be on the candidate's market, event, cluster or strategy is counted there."""
    cand = (intent.market_ticker, market.event_key, market.cluster_key, intent.strategy_id)

    def keys(ticker: str | None, event: str | None, cluster: str | None, strategy: str | None) -> tuple[str, ...]:
        if ticker is None:  # an unknown market could be this one, in this event and cluster
            ticker, event, cluster = cand[0], cand[1], cand[2]
        return (f"market:{ticker}", f"event:{event if event is not None else cand[1]}",
                f"cluster:{cluster if cluster is not None else cand[2]}",
                f"strategy:{strategy if strategy is not None else cand[3]}")

    items = [(f"position:{p.market_ticker}:{p.side.value}", ObligationState.BOUND, p.quantity * ONE_DOLLAR,
              keys(p.market_ticker, p.event_key, p.cluster_key, p.strategy_id)) for p in account.positions or ()]
    items += [(f"commitment:{c.commitment_id}", c.state, c.risk_worst_case,
               keys(c.market_ticker, c.event_key, c.cluster_key, c.strategy_id)) for c in account.commitments]
    return items, keys(*cand)


def _exposure_checks(intent: OrderIntent, account: AccountProjection, market: MarketState | None, policy: RiskPolicy,
                     limits: GateLimits, fail, risk: Decimal) -> None:
    if risk > policy.max_position_risk:  # the order alone; exactly at a limit is allowed
        fail(Reason.EXPOSURE_PER_ORDER, f"{risk} > {policy.max_position_risk}")
    if market is None or market.event_key is None or market.cluster_key is None:
        fail(Reason.EXPOSURE_UNKNOWN, "the candidate's event or cluster is unknown")
        return
    if account.positions is None:
        fail(Reason.EXPOSURE_UNKNOWN, "held positions are unknown")
        return
    items, cand_keys = _exposure_items(account, intent, market)
    # The canonical no-netting sum per shared key. Its cash verdict is not used here (no cash is passed): the
    # cash check is separate (`_cash_checks`).
    result = reserve_simultaneous_obligations(
        tuple(Obligation(i, s, w, k) for i, s, w, k in items), available_cash=None,
        candidate=Obligation("candidate", ObligationState.OUTSTANDING, risk, cand_keys))
    unknown = [i for i, _, w, _ in items if w is None]
    if unknown or result.required is None:
        fail(Reason.EXPOSURE_UNKNOWN, f"worst case unknown for {unknown[:3]}")
        return
    for code, key, limit in ((Reason.EXPOSURE_PER_MARKET, cand_keys[0], policy.max_position_risk),
                             (Reason.EXPOSURE_PER_EVENT, cand_keys[1], policy.max_event_risk),
                             (Reason.EXPOSURE_PER_CLUSTER, cand_keys[2], policy.max_cluster_risk),
                             (Reason.EXPOSURE_PER_STRATEGY, cand_keys[3], limits.max_strategy_risk)):
        total = result.by_key[key]
        if total is None or total > limit:
            fail(code, f"{key}: {total} with this order > {limit}")
    if result.required > policy.max_portfolio_risk:
        fail(Reason.EXPOSURE_ACCOUNT, f"{result.required} with this order > {policy.max_portfolio_risk}")


def _cash_checks(intent: OrderIntent, account: AccountProjection, policy: RiskPolicy, fail, figures: dict) -> None:
    """Every held cash obligation and this one binding at once must fit in the cash above the reserve floor."""
    if account.cash is None:
        return  # CASH_UNKNOWN already
    available = account.cash - policy.reserve_floor
    if available < 0:
        fail(Reason.RESERVE_FLOOR, f"cash {account.cash} is below the reserve floor {policy.reserve_floor}")
        return
    result = reserve_simultaneous_obligations(
        tuple(Obligation(f"commitment:{c.commitment_id}", c.state, c.cash_worst_case) for c in account.commitments),
        available_cash=available,
        candidate=Obligation("candidate", ObligationState.OUTSTANDING, intent.max_total_cost))
    figures["cash"] = result.required
    if not result.new_risk_allowed:
        blocking = [r for r in result.reasons if not r.startswith(("CANCEL_NOT_CONFIRMED", "UNKNOWN_STATE"))]
        fail(Reason.CASH_CAPACITY_INSUFFICIENT, "; ".join(blocking or result.reasons) +
             f" (cash above the reserve floor: {available})")


def _loss_checks(intent: OrderIntent, account: AccountProjection, market: MarketState | None, policy: RiskPolicy,
                 at: datetime, fail, figures: dict, risk: Decimal) -> None:
    history, since = account.pnl_history, account.pnl_history_since_utc
    if history is None or since is None:
        fail(Reason.PNL_HISTORY_UNKNOWN, "realized P&L history is unknown: no new risk")
        return
    start = parse_utc_text(since)
    times = [parse_utc_text(e.at_utc) for e in history]
    if start > at or any(t > at or t < start for t in times):
        fail(Reason.PNL_HISTORY_UNKNOWN, f"history since {since} has entries outside [{since}, now]")
        return
    if account.cash is None or account.positions is None or market is None or market.event_key is None \
            or market.cluster_key is None:
        return  # CASH_UNKNOWN, POSITIONS_UNKNOWN or EXPOSURE_UNKNOWN already: no headroom can be measured
    stamp = utc_text(at)
    realized = sorted(((t, e) for t, e in zip(times, history) if e.kind is LedgerKind.REALIZED_PNL),
                      key=lambda te: (te[0], te[1].entry_ref))
    settled = [_RiskPosition(f"pnl:{n}:{e.entry_ref}", e.at_utc, "realized", "realized", "SETTLED", Decimal(0),
                             Decimal(0), Decimal(0), None, e.amount, e.at_utc) for n, (_, e) in enumerate(realized)]
    items, _ = _exposure_items(account, intent, market)
    if any(w is None for _, _, w, _ in items):
        return  # EXPOSURE_UNKNOWN already: the open risk the loss headroom must absorb is unknown
    # Open exposures carry the same keys as in `_exposure_checks`, so an existing breach `risk.assess` finds is
    # the same one; `risk.assess` owns the loss limits, the drawdown and the remaining capacity.
    open_ = [_RiskPosition(i, stamp, k[1], k[2], "OPEN", w, w, w, None, None, None) for i, _, w, k in items]
    total = sum((p.max_downside for p in open_), Decimal(0))
    view = _RiskView(account.scope_key, Decimal(0), account.cash, total, total, Decimal(0), tuple(settled + open_))
    view = replace(view, equity=equity_curve(view)[-1][1])  # cumulative realized P&L, the canonical curve
    report = assess(view, policy, at)
    figures["capacity"] = report.remaining_risk_capacity
    for breach in report.breaches:
        code = ASSESS_BREACHES.get(breach)
        if code in (Reason.DAILY_LOSS_LIMIT, Reason.WEEKLY_LOSS_LIMIT, Reason.MAX_DRAWDOWN, Reason.RESERVE_FLOOR):
            fail(code, f"risk.assess {breach}: daily loss {report.daily_loss}, weekly loss {report.weekly_loss}, "
                       f"drawdown {report.drawdown}")
        elif code is not None:
            fail(code, f"risk.assess {breach}: the account already breaches it")
    if not report.breaches and risk > report.remaining_risk_capacity:  # exactly the capacity is allowed
        fail(Reason.RISK_CAPACITY_INSUFFICIENT, f"{risk} > remaining capacity {report.remaining_risk_capacity} "
                                                f"(policy {policy.policy_id})")


def _history_checks(intent: OrderIntent, account: AccountProjection, limits: GateLimits, tl: TicketLimits,
                    at: datetime, fail, entry: bool, risk: Decimal) -> None:
    """Counts from the persisted order history only, with `pre_submit_checks`' TicketLimits semantics: every order
    created in the window counts (failed and future-dated ones too); an order exactly `order_window` old has left
    it; exactly `market_cooldown` since the last order on the market is allowed."""
    history = account.order_history
    if history is None or any(o.created_at_utc is None for o in history):
        fail(Reason.ORDER_HISTORY_UNKNOWN, "an order has no creation time, or the history is unknown")
        return
    timed = [(parse_utc_text(o.created_at_utc), o) for o in history]
    if entry:
        recent_risk = sum((o.new_risk for c, o in timed if c > at - DAY), Decimal(0))
        if recent_risk + risk > limits.daily_new_risk:  # exactly the limit is allowed
            fail(Reason.DAILY_NEW_RISK_LIMIT, f"{recent_risk} in the trailing 24 h + {risk} > {limits.daily_new_risk}")
    recent = sum(1 for c, _ in timed if c > at - tl.order_window)
    if recent >= tl.max_orders_per_window:
        fail(Reason.TRADE_COUNT_LIMIT, f"{recent} orders in {tl.order_window} (max {tl.max_orders_per_window})")
    if any(o.market_ticker == intent.market_ticker and at - c < tl.market_cooldown for c, o in timed):
        fail(Reason.COOLDOWN_ACTIVE, f"{intent.market_ticker} within {tl.market_cooldown}")


def revalidate(intent: OrderIntent, grant: ApprovalGrant, *, account: AccountProjection | None,
               market: MarketState | None, policy: RiskPolicy, limits: GateLimits, ticket_limits: TicketLimits,
               evidence: DecisionEvidence | None, now: datetime) -> GateDecision:
    """The check just before sending: the approval must bind this exact intent (`ApprovalGrant.problems`: a changed
    quantity or price is a digest mismatch), and `evaluate` must pass on current inputs. Nonce reuse is the
    journal's check."""
    decision = evaluate(intent, account=account, market=market, policy=policy, limits=limits,
                        ticket_limits=ticket_limits, evidence=evidence, now=now)
    extra: dict[Reason, list[str]] = {}
    if not isinstance(grant, ApprovalGrant):
        extra[Reason.APPROVAL_INVALID] = ["no ApprovalGrant"]
    else:
        for problem in grant.problems(intent, now=now):
            code = APPROVAL_PROBLEMS.get(problem.split(":", 1)[0], Reason.APPROVAL_INVALID)
            if code is not Reason.INTENT_EXPIRED:  # `evaluate` reports it
                extra.setdefault(code, []).append(problem)
    if not extra:
        return decision
    merged = {v.code: v.detail for v in decision.reasons}
    for code, details in extra.items():
        merged[code] = "; ".join(details)
    order = tuple(Reason)
    reasons = tuple(Violation(c, merged[c]) for c in sorted(merged, key=order.index))
    return replace(decision, allowed=False, reasons=reasons)
