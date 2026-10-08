"""The order-lifecycle reducer for ordinary Kalshi event-contract limit orders (#160 package H). Pure.

`reduce(view, event) -> view` folds one receipt into an immutable `OrderView`. Nothing here sends,
reads a clock, touches a store or decides anything: it only records what is known about one order.

Coarse state and detail
- The coarse state is always an `execution_ticket.OrderState` and moves only through
  `execution_ticket.transition`. The richer detail sits beside it: send stage and time, establishment,
  quantities, fills, venue count observations, a pending cancel or amendment, and an unresolved
  ambiguous operation.
- Quantities: `filled + remaining + canceled == total` after every event, and none is negative. A
  receipt that would break this is recorded but not applied, and the view is quarantined with the
  reason. Nothing is clamped. Every change of a count is logged in `count_log`.

How `filled` is known
- Two kinds of evidence are kept apart: the fills received (by fill id) and the venue's cumulative
  fill counts (`count_observations`, each with the venue time it was true at).
- A count observed at time t covers the fills executed at or before t. Fills received with a venue time
  clearly later (beyond `TIMESTAMP_SKEW`) are on top of it. So `filled` is the largest of: the fills
  received, and, for each observation, its count plus the received fills clearly after it. It never
  decreases.
- A count read over an interval carries two times: `as_of_utc`, the earliest time it can be true at (the
  lower bound), and optionally `as_of_upper_utc`, the latest (the upper bound; for an account read, its end
  plus the read's clock tolerance, `account.ReadManifest.data_true_by`). A fill is on top of the count only
  when stamped after the upper bound; one between the bounds may already be inside the count, so it is never
  added on top and `fill_timing_uncertain` is set. The upper bound only widens the skew window, never narrows
  it. Dispute checks and the not-found delay use the lower bound.
- Each new count is checked against the count implied at its own time: an earlier count plus the fills
  clearly between the two, or the fills clearly before it. A lower count is a dispute: it quarantines
  when authoritative or final, and is noted otherwise. Fills within the skew of a snapshot get the
  benefit of the doubt in both directions (not "clearly before" for a dispute, not "clearly after" for
  the lower bound).
- When a fill or an observation has no usable time, a fill falls within the skew window after a count,
  or a count is disputed, which fills a count covers is unknown. The lower bound is kept,
  `fill_timing_uncertain` is set, and fees are never reported complete.
- A reconcile's remaining quantity must equal its total minus its fill count (checked), so comparing its
  remaining with the view is the same comparison as its fill count with the implied count.
- A final count (a canceled or executed order) cannot be exceeded. A venue-stated cancel count
  (`canceled_floor`) never changes once known; a second, different one quarantines.
- A count below fills the snapshot must already include, or below an earlier venue count, is noted.
  It quarantines when it is final, or from an authoritative reconcile that cannot be shown to be older.

Ambiguity and establishment
- A new order whose send returned ambiguously (timeout or connection loss after egress) is
  OUTCOME_UNKNOWN. Only an `Acknowledged` or a found `ReconcileObserved` establishes it. A fill
  carrying our client order id adds quantity but does not establish the order. A bare rejection (no
  order id) cannot be tied to the lost send and is only noted.
- A "not found" reconcile is NOT_FOUND evidence, never proof of absence, unless it is authoritative and
  complete for the scope and was taken at least `NOT_FOUND_MIN_DELAY` after the recorded send time.
  Only then does an unestablished, unfilled order end REJECTED as never accepted.
- A second `SendPrepared` is a blind resubmission and quarantines the view. `may_send_new_order`
  is the guard a sender checks first.

Cancellation, amendment and terminal states
- `CancelRequested` and `AmendRequested` change no quantity. Only the venue's confirmation does.
- Canceled does not mean never filled. A fill that executed before a cancel without a stated count
  (soft) applies once and reduces the canceled quantity.
- The venue's amend count is the order's new TOTAL, already-filled contracts included, not a desired
  remainder: total 10 with 4 filled, amended to 8, leaves 4 resting. A requested total at or below the
  filled quantity is refused locally; one acknowledged below it quarantines. While an amendment is
  pending, fills at its new price are within the limit.
- An amendment keeps the order's identity. If the venue assigns a new provider id, the old one moves to
  `prior_provider_order_ids`, and fills for either id still match. A receipt with our client order id
  and an unknown provider id, while an amendment is pending or ambiguous, is taken provisionally as that
  replacement (`provisional_provider_order_id`): nothing may be canceled or amended against it, and an
  amendment reject, or a reconcile showing the amendment not applied, quarantines the view.
- A terminal view still records every later receipt (`receipts`). If a receipt contradicts the terminal
  state, the view is quarantined; the state never moves back.

Identity: receipts match an order by provider order id or client order id, never by price, quantity or
time coincidence (`route`).

The venue field meanings assumed here (status words, `reduced_by`, the amend count, the fill fields,
which time a snapshot is true at) are illustrative until the conformance pack confirms them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Union

from ..execution_ticket import OrderState, transition
from .model import Action, OrderIntent, Side, exact_decimal, parse_utc_text

ZERO = Decimal(0)
ONE = Decimal(1)
TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})
# How long after our recorded send a complete not-found snapshot must be taken to prove the order never
# arrived. Provisional: it covers transit and clock disagreement; the conformance pack should set it.
NOT_FOUND_MIN_DELAY = timedelta(seconds=30)
# How far a fill's venue time may disagree with a snapshot's `as_of` (different endpoints, different
# clocks). Provisional: the conformance pack should measure it. Within it, the reducer gives each side the
# benefit of the doubt in the safe direction (see `_relation`).
TIMESTAMP_SKEW = timedelta(seconds=2)


class Operation(str, Enum):
    """The request whose answer a receipt carries."""

    NEW_ORDER = "new_order"
    CANCEL = "cancel"
    AMEND = "amend"


class SendStage(str, Enum):
    UNSENT = "UNSENT"  # the view exists; nothing has been transmitted
    PREPARED = "PREPARED"  # journaled and handed to the transport: it may have reached the venue


class VenueStatus(str, Enum):
    """Order status words the venue reports (illustrative until the conformance pack confirms them)."""

    PENDING = "pending"
    RESTING = "resting"
    CANCELED = "canceled"
    EXECUTED = "executed"


class Liquidity(str, Enum):
    TAKER = "taker"
    MAKER = "maker"


def _dec(value: object, name: str) -> Decimal | None:
    return None if value is None else exact_decimal(value, name=name)


def _ident(value: object, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a str or None, not {type(value).__name__}")
    return value


# ---------------------------------------------------------------- events
#
# Event constructors check types only: every number must be exact (a float raises). Semantic
# problems (a negative count, an unknown status, a contradiction) are the reducer's to judge, so a
# malformed venue receipt is recorded and quarantined rather than lost.


@dataclass(frozen=True)
class SendPrepared:
    """Local: the new order is journaled and about to be transmitted. Recorded before egress, with the
    time (our clock) it was journaled: a not-found snapshot taken before it proves nothing."""

    prepared_at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.prepared_at_utc, str):
            raise TypeError("prepared_at_utc must be ISO-8601 text")
        parse_utc_text(self.prepared_at_utc)  # naive or malformed text raises


@dataclass(frozen=True)
class SendReturnedAmbiguous:
    """Local: a request left the process and its answer was lost (timeout, connection reset)."""

    operation: Operation
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.operation, Operation):
            raise TypeError("operation must be an Operation")


@dataclass(frozen=True)
class Acknowledged:
    """A non-authoritative venue snapshot of the order: the reply to a new order, or a stream update.
    It may be stale (an earlier snapshot delivered late). `total_quantity` is the venue's current total
    when reported; otherwise it is inferred from filled + remaining for a live or executed order."""

    provider_order_id: str | None
    client_order_id: str | None
    status: str | None
    filled_quantity: Decimal | None
    remaining_quantity: Decimal | None
    total_quantity: Decimal | None = None
    venue_time_utc: str | None = None

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        for f in ("filled_quantity", "remaining_quantity", "total_quantity"):
            object.__setattr__(self, f, _dec(getattr(self, f), f))


@dataclass(frozen=True)
class Rejected:
    """The venue refused a request (`operation`). Ids are optional: a synchronous error reply often has none."""

    operation: Operation
    reason: str
    provider_order_id: str | None = None
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, Operation):
            raise TypeError("operation must be an Operation")
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")


@dataclass(frozen=True)
class Fill:
    """One execution against the order. `price` is per contract of the order's own side, in dollars.
    `fee` None is unknown (never zero). `liquidity` None means the venue did not say."""

    fill_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal | None
    liquidity: Liquidity | None
    venue_time_utc: str | None
    provider_order_id: str | None = None
    client_order_id: str | None = None
    side: Side | None = None
    action: Action | None = None

    def __post_init__(self) -> None:
        _ident(self.fill_id, "fill_id")
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        object.__setattr__(self, "quantity", exact_decimal(self.quantity, name="fill quantity"))
        object.__setattr__(self, "price", exact_decimal(self.price, name="fill price"))
        object.__setattr__(self, "fee", _dec(self.fee, "fill fee"))
        if self.liquidity is not None and not isinstance(self.liquidity, Liquidity):
            raise TypeError("liquidity must be a Liquidity or None")
        if self.side is not None and not isinstance(self.side, Side):
            raise TypeError("side must be a Side or None")
        if self.action is not None and not isinstance(self.action, Action):
            raise TypeError("action must be an Action or None")


@dataclass(frozen=True)
class CancelRequested:
    """Local: a cancel is about to be sent. Changes no quantity."""


@dataclass(frozen=True)
class CancelConfirmed:
    """The venue canceled the order. `reduced_by` is the count it removed, when stated; the remainder
    after a full cancel is zero. A cancel that states no count removes whatever is open (soft)."""

    provider_order_id: str | None
    client_order_id: str | None = None
    reduced_by: Decimal | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    venue_time_utc: str | None = None

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        for f in ("reduced_by", "filled_quantity", "remaining_quantity"):
            object.__setattr__(self, f, _dec(getattr(self, f), f))


@dataclass(frozen=True)
class AmendRequested:
    """Local: an amendment is about to be sent. `new_total` is the order's new TOTAL quantity including
    contracts already filled (venue semantics), never the desired remainder. None keeps the current value."""

    new_total: Decimal | None = None
    new_price: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "new_total", _dec(self.new_total, "new_total"))
        object.__setattr__(self, "new_price", _dec(self.new_price, "new_price"))


@dataclass(frozen=True)
class AmendAcknowledged:
    """The venue applied an amendment. `new_total` is the TOTAL including filled contracts.
    `new_provider_order_id` is set only if the venue gave the amended order a new id."""

    provider_order_id: str | None
    new_total: Decimal
    new_price: Decimal
    client_order_id: str | None = None
    new_provider_order_id: str | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    venue_time_utc: str | None = None

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        _ident(self.new_provider_order_id, "new_provider_order_id")
        object.__setattr__(self, "new_total", exact_decimal(self.new_total, name="new_total"))
        object.__setattr__(self, "new_price", exact_decimal(self.new_price, name="new_price"))
        for f in ("filled_quantity", "remaining_quantity"):
            object.__setattr__(self, f, _dec(getattr(self, f), f))


@dataclass(frozen=True)
class Expired:
    """The venue ended the order at its expiry. Whatever was open is canceled (soft, like a cancel
    without a count)."""

    provider_order_id: str | None
    client_order_id: str | None = None
    filled_quantity: Decimal | None = None
    venue_time_utc: str | None = None

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        object.__setattr__(self, "filled_quantity", _dec(self.filled_quantity, "filled_quantity"))


@dataclass(frozen=True)
class ReconcileObserved:
    """An authoritative venue query for the order, as of `as_of_utc`.

    `found=False` is NOT_FOUND evidence. It ends an order as never accepted only when
    `authoritative_complete` says the query covered the whole scope (every order of the account, by
    client order id, including terminal ones).

    `as_of_utc` is the earliest time the counts can be true at; `as_of_upper_utc` (optional) the latest. A
    query read over an interval, or against a clock that may disagree with the venue's, states both: fills
    stamped between them may already be in the count (module docstring)."""

    client_order_id: str | None
    provider_order_id: str | None
    found: bool
    status: str | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    total_quantity: Decimal | None = None
    price: Decimal | None = None
    authoritative_complete: bool = False
    as_of_utc: str | None = None
    as_of_upper_utc: str | None = None

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
        _ident(self.as_of_upper_utc, "as_of_upper_utc")
        if not isinstance(self.found, bool) or not isinstance(self.authoritative_complete, bool):
            raise TypeError("found and authoritative_complete must be bools")
        for f in ("filled_quantity", "remaining_quantity", "total_quantity", "price"):
            object.__setattr__(self, f, _dec(getattr(self, f), f))


Event = Union[SendPrepared, SendReturnedAmbiguous, Acknowledged, Rejected, Fill, CancelRequested, CancelConfirmed,
              AmendRequested, AmendAcknowledged, Expired, ReconcileObserved]
LOCAL_EVENTS = (SendPrepared, SendReturnedAmbiguous, CancelRequested, AmendRequested)

# ---------------------------------------------------------------- the view


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal | None
    liquidity: Liquidity | None
    venue_time_utc: str | None
    provider_order_id: str | None


@dataclass(frozen=True)
class CountObservation:
    """The venue said `count` contracts were filled, true at `as_of_utc` (None: time unknown) or, when
    `as_of_upper_utc` is stated, at some time between the two. A final count belongs to a canceled or executed
    order: nothing can fill beyond it."""

    count: Decimal
    as_of_utc: str | None
    final: bool
    source: str
    authoritative: bool = False
    as_of_upper_utc: str | None = None


@dataclass(frozen=True)
class AmendTarget:
    new_total: Decimal  # TOTAL quantity including filled
    new_price: Decimal


class CancelBasis(str, Enum):
    SOFT = "SOFT"  # canceled "whatever was open", no count stated: late fills may reduce it
    VENUE_COUNT = "VENUE_COUNT"  # the venue stated the count (`canceled_floor`): fixed


@dataclass(frozen=True)
class OrderView:
    """Everything known about one of our orders. Build it with `open_view` or `view_from_intent`."""

    client_order_id: str
    intent_digest: str | None
    market_ticker: str
    side: Side
    action: Action
    original_quantity: Decimal
    state: OrderState
    send_stage: SendStage
    sent_at_utc: str | None  # when the new order was journaled for sending (our clock)
    established: bool  # an Acknowledged or a found ReconcileObserved has shown the order exists
    provider_order_id: str | None
    prior_provider_order_ids: tuple[str, ...]
    provisional_provider_order_id: str | None  # a replacement id seen before its amendment was confirmed
    limit_price: Decimal
    limit_prices: tuple[Decimal, ...]  # every limit the order has carried, in order
    total_quantity: Decimal
    total_history: tuple[Decimal, ...]  # every total the order has had, in order
    filled_quantity: Decimal
    remaining_quantity: Decimal
    canceled_quantity: Decimal
    cancel_basis: CancelBasis | None
    canceled_floor: Decimal  # the venue-stated cancel count (VENUE_COUNT), else 0
    fills: tuple[FillRecord, ...]
    count_observations: tuple[CountObservation, ...]
    parked_fills: tuple[Fill, ...]  # fills beyond the open quantity while a larger amendment is pending
    cancel_requested: bool
    amend_pending: AmendTarget | None
    amend_reply_owed: bool  # a snapshot showed the pending amendment applied; its own reply is still due
    ambiguous_operation: Operation | None
    terminal_reason: str | None
    last_venue_status: str | None
    not_found_observations: int
    quarantine_reasons: tuple[str, ...]
    refusals: tuple[str, ...]  # local requests the reducer refused (nothing was sent for them)
    notes: tuple[str, ...]  # non-fatal observations: duplicates, stale snapshots, late fills
    count_log: tuple[str, ...]  # one line per change of total, filled, remaining, canceled or floor
    receipts: tuple[object, ...]  # every event, in arrival order, applied or not

    @property
    def quarantined(self) -> bool:
        return bool(self.quarantine_reasons)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def fill_quantity_applied(self) -> Decimal:
        return sum((f.quantity for f in self.fills), ZERO)

    @property
    def venue_filled_reported(self) -> Decimal:
        """The highest cumulative fill count the venue has reported (0 if none)."""
        return max((o.count for o in self.count_observations), default=ZERO)

    @property
    def unreceived_fill_quantity(self) -> Decimal:
        """Contracts known to be filled whose fill receipts have not arrived."""
        return self.filled_quantity - self.fill_quantity_applied

    @property
    def fill_timing_uncertain(self) -> bool:
        """True when it is unknown which received fills a venue count already covers, so `filled` is a
        lower bound that may be short."""
        if any(o.final for o in self.count_observations):
            return False
        for o in self.count_observations:
            at = _time(o.as_of_utc)
            if at is not None and _implied_at(self, at) > o.count:
                return True  # a disputed count: noted, and `filled` may overstate as well as understate
        if not self.fills or (self.filled_quantity >= self.total_quantity and self.amend_pending is None):
            return False
        for o in self.count_observations:
            if o.count <= 0:
                continue
            if _bounds(o) is None or any(_relation(f, o) in ("unknown", "window") for f in self.fills):
                return True
        return False

    @property
    def fees_known(self) -> Decimal:
        return sum((f.fee for f in self.fills if f.fee is not None), ZERO)

    @property
    def fees_complete(self) -> bool:
        """True only if every filled contract has a fill receipt with a known fee, and no venue count
        could cover fills not yet received."""
        return (all(f.fee is not None for f in self.fills) and self.unreceived_fill_quantity == 0
                and not self.parked_fills and not self.fill_timing_uncertain)

    def fill(self, fill_id: str) -> FillRecord | None:
        return next((f for f in self.fills if f.fill_id == fill_id), None)

    def provider_ids(self) -> frozenset[str]:
        ids = set(self.prior_provider_order_ids)
        if self.provider_order_id is not None:
            ids.add(self.provider_order_id)
        return frozenset(ids)


def open_view(*, client_order_id: str, market_ticker: str, side: Side, action: Action, quantity: object,
              limit_price: object, intent_digest: str | None = None) -> OrderView:
    """A new, unsent view: PENDING, nothing filled, the whole quantity unfilled."""
    if not isinstance(client_order_id, str) or not client_order_id:
        raise ValueError("client_order_id is required")
    if not isinstance(market_ticker, str) or not market_ticker:
        raise ValueError("market_ticker is required")
    if not isinstance(side, Side) or not isinstance(action, Action):
        raise TypeError("side must be a Side and action an Action")
    qty = exact_decimal(quantity, name="quantity")
    price = exact_decimal(limit_price, name="limit_price")
    if qty <= 0:
        raise ValueError("quantity must be positive")
    if not ZERO < price < ONE:
        raise ValueError("limit_price must be strictly between 0 and 1 dollar")
    return OrderView(
        client_order_id=client_order_id, intent_digest=intent_digest, market_ticker=market_ticker, side=side,
        action=action, original_quantity=qty, state=OrderState.PENDING, send_stage=SendStage.UNSENT,
        sent_at_utc=None, established=False, provider_order_id=None, prior_provider_order_ids=(),
        provisional_provider_order_id=None,
        limit_price=price, limit_prices=(price,), total_quantity=qty, total_history=(qty,), filled_quantity=ZERO,
        remaining_quantity=qty, canceled_quantity=ZERO, cancel_basis=None, canceled_floor=ZERO, fills=(),
        count_observations=(), parked_fills=(), cancel_requested=False, amend_pending=None, amend_reply_owed=False,
        ambiguous_operation=None, terminal_reason=None, last_venue_status=None, not_found_observations=0,
        quarantine_reasons=(), refusals=(), notes=(), count_log=(), receipts=())


def view_from_intent(intent: OrderIntent) -> OrderView:
    return open_view(client_order_id=intent.client_order_id(), market_ticker=intent.market_ticker, side=intent.side,
                     action=intent.action, quantity=intent.quantity, limit_price=intent.limit_price,
                     intent_digest=intent.digest())


# ---------------------------------------------------------------- invariants and guards

_COUNT_FIELDS = ("total_quantity", "filled_quantity", "remaining_quantity", "canceled_quantity", "canceled_floor")


def invariant_problems(view: OrderView) -> list[str]:
    """Why `view`'s quantities or state are incoherent (empty: they hold)."""
    out = []
    for name in _COUNT_FIELDS:
        value = getattr(view, name)
        if not isinstance(value, Decimal) or not value.is_finite():
            return [f"INVARIANT: {name} is not a finite Decimal"]
        if value < 0:
            out.append(f"INVARIANT: {name} {value} is negative")
    if view.total_quantity <= 0:
        out.append(f"INVARIANT: total {view.total_quantity} is not positive")
    if view.filled_quantity + view.remaining_quantity + view.canceled_quantity != view.total_quantity:
        out.append(f"INVARIANT: filled {view.filled_quantity} + remaining {view.remaining_quantity} + canceled "
                   f"{view.canceled_quantity} != total {view.total_quantity}")
    if view.fill_quantity_applied > view.filled_quantity:
        out.append(f"INVARIANT: fills applied {view.fill_quantity_applied} exceed filled {view.filled_quantity}")
    if view.filled_quantity > view.venue_filled_reported + view.fill_quantity_applied:
        out.append("INVARIANT: filled exceeds every venue count plus the fills received")
    if view.cancel_basis is CancelBasis.VENUE_COUNT and view.canceled_quantity != view.canceled_floor:
        out.append(f"INVARIANT: canceled {view.canceled_quantity} is not the venue-stated {view.canceled_floor}")
    if view.cancel_basis is not CancelBasis.VENUE_COUNT and view.canceled_floor != 0:
        out.append("INVARIANT: a cancel floor without a venue-stated count")
    if view.state is OrderState.REJECTED and view.filled_quantity > 0:
        out.append("INVARIANT: a REJECTED order has fills")
    if view.state is OrderState.FILLED and view.filled_quantity != view.total_quantity:
        out.append("INVARIANT: a FILLED order is not fully filled")
    if view.state is OrderState.CANCELLED and view.remaining_quantity != 0:
        out.append("INVARIANT: a CANCELLED order still has a remainder")
    if view.state is OrderState.RESTING and not view.established:
        out.append("INVARIANT: RESTING but never established")
    return out


def may_send_new_order(view: OrderView) -> list[str]:
    """Why the new order must not be transmitted now (empty: it may be sent once)."""
    out = []
    if view.quarantined:
        out.append("QUARANTINED")
    if view.send_stage is not SendStage.UNSENT:
        out.append("ALREADY_SENT: reconcile, never resubmit blindly")
    if view.state is not OrderState.PENDING or view.established:
        out.append(f"NOT_PENDING: {view.state.value}")
    return out


def cancel_problems(view: OrderView) -> list[str]:
    out = []
    if view.quarantined:
        out.append("QUARANTINED")
    if not view.established or view.provider_order_id is None:
        out.append("CANCEL_NEEDS_ESTABLISHED_ORDER")
    if view.is_terminal:
        out.append(f"CANCEL_ON_TERMINAL: {view.state.value}")
    if view.cancel_requested:
        out.append("CANCEL_ALREADY_PENDING")
    if view.ambiguous_operation is not None:
        out.append(f"RECONCILE_FIRST: {view.ambiguous_operation.value} outcome unknown")
    if view.provisional_provider_order_id is not None:
        out.append("PROVIDER_ID_PROVISIONAL: the replacement id is not confirmed; reconcile first")
    return out


def amend_problems(view: OrderView, new_total: Decimal | None, new_price: Decimal | None) -> list[str]:
    """Why an amendment must not be sent. `new_total` is a TOTAL including filled contracts."""
    out = []
    if view.quarantined:
        out.append("QUARANTINED")
    if not view.established or view.provider_order_id is None:
        out.append("AMEND_NEEDS_ESTABLISHED_ORDER")
    if view.is_terminal:
        out.append(f"AMEND_ON_TERMINAL: {view.state.value}")
    if view.amend_pending is not None:
        out.append("AMEND_ALREADY_PENDING")
    if view.amend_reply_owed:
        out.append("AMEND_REPLY_OUTSTANDING: the last amendment's reply has not arrived")
    if view.cancel_requested:
        out.append("AMEND_WHILE_CANCEL_PENDING")
    if view.ambiguous_operation is not None:
        out.append(f"RECONCILE_FIRST: {view.ambiguous_operation.value} outcome unknown")
    if new_total is None and new_price is None:
        out.append("AMEND_EMPTY")
    elif (view.total_quantity if new_total is None else new_total) == view.total_quantity and \
            (view.limit_price if new_price is None else new_price) == view.limit_price:
        out.append("AMEND_NO_CHANGE: the amendment would change neither total nor price")
    if new_total is not None:
        if new_total < view.filled_quantity:
            out.append(f"AMEND_BELOW_FILLED: total {new_total} < filled {view.filled_quantity} (the amend count is "
                       f"a total including filled contracts)")
        elif new_total == view.filled_quantity:
            out.append(f"AMEND_LEAVES_NOTHING: total {new_total} == filled; cancel instead")
    if new_price is not None and not ZERO < new_price < ONE:
        out.append(f"AMEND_PRICE_OUT_OF_RANGE: {new_price}")
    return out


# ---------------------------------------------------------------- helpers


def _quarantine(view: OrderView, *reasons: str) -> OrderView:
    return replace(view, quarantine_reasons=view.quarantine_reasons + tuple(reasons))


def _note(view: OrderView, text: str) -> OrderView:
    return replace(view, notes=view.notes + (text,))


def _refuse(view: OrderView, reasons: list[str]) -> OrderView:
    return replace(view, refusals=view.refusals + tuple(reasons))


def _time(text: str | None) -> datetime | None:
    if text is None:
        return None
    try:
        return parse_utc_text(text)
    except ValueError:
        return None


def _replacement_expected(view: OrderView) -> bool:
    return view.amend_pending is not None or view.ambiguous_operation is Operation.AMEND


def _identity_problem(view: OrderView, provider_order_id: str | None, client_order_id: str | None, *,
                      require: bool) -> str | None:
    """Why a receipt does not belong to `view` (None: it does). Identity only: never price or size."""
    if client_order_id is not None and client_order_id != view.client_order_id:
        return f"IDENTITY_MISMATCH: client order id {client_order_id!r} is not {view.client_order_id!r}"
    known = view.provider_ids()
    if provider_order_id is not None:
        if not provider_order_id:
            return "IDENTITY_MALFORMED: empty provider order id"
        if known and provider_order_id not in known:
            if client_order_id is not None and _replacement_expected(view):
                return None  # our order, re-identified by the pending amendment (`_link_provider_id`)
            return f"IDENTITY_MISMATCH: provider order id {provider_order_id!r} is not {sorted(known)}"
        if not known and client_order_id is None:
            return f"IDENTITY_UNMATCHED: provider order id {provider_order_id!r} is not yet linked to this order"
    elif client_order_id is None and require:
        return "IDENTITY_MISSING: the receipt names no order"
    return None


def _link_provider_id(view: OrderView, provider_order_id: str | None, *, confirmed: bool = False) -> OrderView:
    """Record a provider id the identity check accepted: the first one, or a replacement id. A replacement
    seen before the venue confirmed the amendment is provisional."""
    if provider_order_id is None or provider_order_id in view.provider_ids():
        return view
    if view.provider_order_id is None:
        return replace(view, provider_order_id=provider_order_id)
    out = replace(view, provider_order_id=provider_order_id,
                  prior_provider_order_ids=view.prior_provider_order_ids + (view.provider_order_id,),
                  provisional_provider_order_id=None if confirmed else provider_order_id)
    kind = "confirmed" if confirmed else "provisional until the amendment is confirmed"
    return _note(out, f"PROVIDER_ID_REPLACED: {view.provider_order_id} -> {provider_order_id} ({kind})")


def _bounds(observation: CountObservation) -> tuple[datetime, datetime] | None:
    """The times a count can be true at: its `as_of` (lower) and the later of `as_of + TIMESTAMP_SKEW` and its
    stated upper bound (upper). None when the count has no usable time. A stated upper bound only widens the
    window: one earlier than `as_of + TIMESTAMP_SKEW`, or unparseable, leaves the skew window as it is."""
    at = _time(observation.as_of_utc)
    if at is None:
        return None
    upper = at + TIMESTAMP_SKEW
    stated = _time(observation.as_of_upper_utc)
    return at, upper if stated is None or stated <= upper else stated


def _relation(fill: FillRecord, observation: CountObservation) -> str:
    """Where a fill's venue time falls relative to a count's times (`_bounds`):
    - "before": at or before the lower bound, so the count covers it;
    - "window": after the lower bound, at or before the upper bound, so it may be covered;
    - "after": clearly after the upper bound, so it is on top of the count;
    - "unknown": the fill or the count has no usable time.
    For a dispute check only fills at least the skew before the lower bound count as before
    (`_clearly_before`)."""
    ft, bounds = _time(fill.venue_time_utc), _bounds(observation)
    if ft is None or bounds is None:
        return "unknown"
    at, upper = bounds
    if ft <= at:
        return "before"
    return "window" if ft <= upper else "after"


def _clearly_before(fill: FillRecord, at: datetime) -> bool:
    ft = _time(fill.venue_time_utc)
    return ft is not None and ft <= at - TIMESTAMP_SKEW


def _implied_filled(fills: tuple[FillRecord, ...], observations: tuple[CountObservation, ...]) -> Decimal:
    """The largest of the fills received and, per venue count, the count plus the fills received clearly
    after it. Untimed fills, untimed counts and fills in the skew window count as covered (a lower bound)."""
    best = sum((f.quantity for f in fills), ZERO)
    for o in observations:
        after = sum((f.quantity for f in fills if _relation(f, o) == "after"), ZERO)
        best = max(best, o.count + after)
    return best


def _implied_at(view: OrderView, at: datetime) -> Decimal:
    """The least the venue's count at `at` must be: the fills clearly before `at`, or an earlier timed count
    plus the fills clearly after it and clearly before `at`. Skew-window fills get the benefit of the doubt."""
    best = sum((f.quantity for f in view.fills if _clearly_before(f, at)), ZERO)
    for o in view.count_observations:
        earlier = _time(o.as_of_utc)
        if earlier is None or earlier > at:
            continue
        between = sum((f.quantity for f in view.fills if _relation(f, o) == "after" and _clearly_before(f, at)), ZERO)
        best = max(best, o.count + between)
    return best


def _recount(view: OrderView) -> OrderView | str:
    """Recompute filled, canceled and remaining from the evidence. A reason string if they do not fit."""
    filled = _implied_filled(view.fills, view.count_observations)
    finals = {o.count for o in view.count_observations if o.final}
    if len(finals) > 1:
        return f"FINAL_COUNTS_DISAGREE: the venue gave final fill counts {sorted(finals)}"
    if finals and filled > min(finals):
        return (f"FILL_EXCEEDS_OPEN_QUANTITY: filled would be {filled}, beyond the venue's final count "
                f"{min(finals)}")
    total = view.total_quantity
    if view.cancel_basis is CancelBasis.VENUE_COUNT:
        canceled = view.canceled_floor
    elif view.cancel_basis is CancelBasis.SOFT:
        canceled = max(total - filled, ZERO)
    else:
        canceled = ZERO
    if filled + canceled > total:
        return (f"FILL_EXCEEDS_OPEN_QUANTITY: filled would be {filled} of total {total} "
                f"(venue-stated canceled {view.canceled_floor})")
    return replace(view, filled_quantity=filled, canceled_quantity=canceled,
                   remaining_quantity=total - filled - canceled)


def _with_total(view: OrderView, total: Decimal) -> OrderView:
    if total == view.total_quantity:
        return view
    return replace(view, total_quantity=total, total_history=view.total_history + (total,))


def _amend_up_pending(view: OrderView) -> bool:
    return view.amend_pending is not None and view.amend_pending.new_total > view.total_quantity


def _target_state(view: OrderView) -> OrderState:
    if view.state is OrderState.REJECTED or not view.established:
        return view.state
    if view.filled_quantity == view.total_quantity and not _amend_up_pending(view):
        return OrderState.FILLED
    if view.remaining_quantity == 0 and view.canceled_quantity > 0:
        return OrderState.CANCELLED
    if view.ambiguous_operation is not None:
        return OrderState.OUTCOME_UNKNOWN
    return OrderState.RESTING


def _settle(before: OrderView, candidate: OrderView) -> OrderView:
    """Move `candidate` to the state its evidence implies, through `transition` only. An illegal move,
    or evidence contradicting a terminal state, quarantines `before` (the receipt stays recorded)."""
    target = _target_state(candidate)
    if target is candidate.state:
        out = candidate
    elif candidate.state in TERMINAL_STATES:
        return _quarantine(before, f"TERMINAL_CONTRADICTED: {candidate.state.value} but the receipt implies "
                                   f"{target.value}")
    else:
        try:
            out = replace(candidate, state=transition(candidate.state, target))
        except ValueError as exc:
            return _quarantine(before, f"ILLEGAL_TRANSITION: {exc}")
    if out.state in TERMINAL_STATES and out.ambiguous_operation is not None:
        out = replace(out, ambiguous_operation=None)  # moot: the order is over
    if out.state is OrderState.FILLED and out.terminal_reason is None:
        out = replace(out, terminal_reason="filled")
    return out


def _move(before: OrderView, candidate: OrderView, state: OrderState) -> OrderView:
    try:
        return replace(candidate, state=transition(candidate.state, state))
    except ValueError as exc:
        return _quarantine(before, f"ILLEGAL_TRANSITION: {exc}")


def _status(text: str | None) -> VenueStatus | None:
    try:
        return VenueStatus(text)
    except ValueError:
        return None


def _observe(view: OrderView, count: Decimal, as_of_utc: str | None, *, final: bool, authoritative: bool,
             complete: bool, source: str, as_of_upper_utc: str | None = None) -> OrderView | str:
    """Record a venue fill count. A reason string if it contradicts what is known; a note if it is only
    stale. Counts are cumulative at the venue, so a lower count is either older or a contradiction."""
    if count < 0:
        return f"MALFORMED_COUNTS: fill count {count} is negative"
    at = _time(as_of_utc)
    received = view.fill_quantity_applied
    implied = ZERO if at is None else _implied_at(view, at)
    clearly_before = ZERO if at is None else sum((f.quantity for f in view.fills if _clearly_before(f, at)), ZERO)
    if implied > count:
        reason = (f"{count} at {as_of_utc} < {implied} implied at that time by earlier counts and the fills "
                  f"clearly before it ({source})")
        if final or authoritative:
            if clearly_before > count:
                return f"COUNT_BELOW_APPLIED_FILLS: venue count {reason}"
            return f"COUNT_BELOW_IMPLIED_FILLS: venue count {reason}"
        view = _note(view, f"COUNT_DISPUTED: {reason}; the higher evidence is kept and fees stay incomplete")
    elif received > count:
        if final or (authoritative and clearly_before + _untimed_fills(view, at) > count):
            return (f"COUNT_BELOW_APPLIED_FILLS: venue count {count} < fills received {received} and not shown "
                    f"to be older ({source})")
        view = _note(view, f"STALE_FILL_COUNT: {count} < fills received {received} ({source})")
    higher = [o for o in view.count_observations if o.count > count]
    for o in higher:
        earlier = _time(o.as_of_utc)
        provably_older = at is not None and earlier is not None and at < earlier
        if final or (not provably_older and (o.final or (authoritative and complete))):
            return (f"COUNT_BELOW_KNOWN_FILLS: venue count {count} ({source}) < an earlier venue count {o.count} "
                    f"({o.source})")
    if higher:
        view = _note(view, f"COUNT_BELOW_EARLIER_VENUE_COUNT: {count} ({source}) < {max(o.count for o in higher)}; "
                           f"stale or not shown to be newer")
    observation = CountObservation(count, as_of_utc, final, source, authoritative or final, as_of_upper_utc)
    return replace(view, count_observations=view.count_observations + (observation,))


def _untimed_fills(view: OrderView, at: datetime | None) -> Decimal:
    """Received fills whose relation to `at` is unknown."""
    if at is None:
        return view.fill_quantity_applied
    return sum((f.quantity for f in view.fills if _time(f.venue_time_utc) is None), ZERO)


def _cancel_firm(view: OrderView, floor: Decimal, as_of_utc: str | None, source: str,
                 as_of_upper_utc: str | None = None) -> OrderView | str:
    """The venue stated how many contracts the cancel removed. Fixed once known."""
    if floor < 0 or floor > view.total_quantity:
        return f"MALFORMED_CANCEL: canceled count {floor} outside [0, {view.total_quantity}]"
    if view.cancel_basis is CancelBasis.VENUE_COUNT and floor != view.canceled_floor:
        return f"CANCEL_COUNT_CONFLICT: the venue stated {view.canceled_floor} canceled, now {floor} ({source})"
    out = _observe(view, view.total_quantity - floor, as_of_utc, final=True, authoritative=True, complete=True,
                   source=source, as_of_upper_utc=as_of_upper_utc)
    if isinstance(out, str):
        return out
    return replace(out, cancel_basis=CancelBasis.VENUE_COUNT, canceled_floor=floor)


def _cancel_soft(view: OrderView) -> OrderView:
    if view.cancel_basis is not None:
        return _note(view, "DUPLICATE_CANCEL: no count stated")
    return replace(view, cancel_basis=CancelBasis.SOFT)


def _merge_venue_counts(before: OrderView, view: OrderView, status: VenueStatus, filled: Decimal | None,
                        remaining: Decimal | None, total: Decimal | None, *, authoritative: bool, complete: bool,
                        as_of_utc: str | None, source: str, price: Decimal | None = None,
                        as_of_upper_utc: str | None = None) -> OrderView:
    """Fold a venue snapshot into `view` (not yet recounted)."""
    for name, value in (("filled", filled), ("remaining", remaining), ("total", total)):
        if value is not None and value < 0:
            return _quarantine(before, f"MALFORMED_COUNTS: {name} {value} is negative")
    if status in (VenueStatus.EXECUTED, VenueStatus.CANCELED) and remaining not in (None, ZERO):
        return _quarantine(before, f"MALFORMED_COUNTS: status {status.value} with remaining {remaining}")
    venue_total = total
    if venue_total is None and filled is not None and remaining is not None and status is not VenueStatus.CANCELED:
        venue_total = filled + remaining
    if status is VenueStatus.EXECUTED and filled is not None and venue_total is not None and filled != venue_total:
        return _quarantine(before, f"MALFORMED_COUNTS: executed with filled {filled} of total {venue_total}")
    if total is not None and filled is not None and remaining is not None and status is not VenueStatus.CANCELED \
            and filled + remaining != total:
        return _quarantine(before, f"MALFORMED_COUNTS: filled {filled} + remaining {remaining} != total {total}")

    if venue_total is not None and venue_total != view.total_quantity:
        target = view.amend_pending
        if target is not None and venue_total == target.new_total and (price is None or price == target.new_price):
            amended = _apply_amend(view, target.new_total, target.new_price, None)
            if isinstance(amended, str):
                return _quarantine(before, amended)
            view = _note(replace(amended, amend_reply_owed=True), "AMEND_APPLIED_PER_SNAPSHOT")
        elif not authoritative and venue_total in view.total_history:
            return _note(view, f"STALE_SNAPSHOT: total {venue_total} predates the current total "
                               f"{view.total_quantity}")
        else:
            return _quarantine(before, f"TOTAL_MISMATCH: venue total {venue_total} != {view.total_quantity}")
    if price is not None and price != view.limit_price:
        target = view.amend_pending
        if target is not None and price == target.new_price and target.new_total == view.total_quantity:
            amended = _apply_amend(view, target.new_total, target.new_price, None)
            if isinstance(amended, str):
                return _quarantine(before, amended)
            view = replace(amended, amend_reply_owed=True)
        elif authoritative:
            return _quarantine(before, f"PRICE_MISMATCH: venue price {price} != {view.limit_price}")

    if status is VenueStatus.EXECUTED and filled is None:
        view = _note(view, f"EXECUTED_WITHOUT_COUNTS: {source} says executed but gives no fill count")
    if filled is not None:
        final = status in (VenueStatus.CANCELED, VenueStatus.EXECUTED)
        if status is VenueStatus.CANCELED:
            observed = _cancel_firm(view, view.total_quantity - filled, as_of_utc, source, as_of_upper_utc)
        else:
            observed = _observe(view, filled, as_of_utc, final=final, authoritative=authoritative, complete=complete,
                                source=source, as_of_upper_utc=as_of_upper_utc)
        if isinstance(observed, str):
            return _quarantine(before, observed)
        view = observed
    elif status is VenueStatus.CANCELED:
        view = _cancel_soft(view)
    return view


def _apply_amend(view: OrderView, new_total: Decimal, new_price: Decimal,
                 new_provider_order_id: str | None) -> OrderView | str:
    """The order now has `new_total` (TOTAL including filled) at `new_price`. Not yet recounted."""
    if view.is_terminal and (new_total != view.total_quantity or new_price != view.limit_price):
        return f"TERMINAL_CONTRADICTED: an amendment of a {view.state.value} order"
    if new_total < view.filled_quantity:
        return f"AMEND_TOTAL_BELOW_FILLED: venue total {new_total} < filled {view.filled_quantity}"
    if not ZERO < new_price < ONE:
        return f"AMEND_PRICE_OUT_OF_RANGE: {new_price}"
    out = _with_total(view, new_total)
    prices = out.limit_prices if new_price == out.limit_price else out.limit_prices + (new_price,)
    out = replace(out, limit_price=new_price, limit_prices=prices, amend_pending=None,
                  ambiguous_operation=None if out.ambiguous_operation is Operation.AMEND else out.ambiguous_operation)
    if new_provider_order_id is not None and new_provider_order_id not in out.provider_ids():
        out = _link_provider_id(out, new_provider_order_id, confirmed=True)
    if out.provisional_provider_order_id is not None:
        out = _note(replace(out, provisional_provider_order_id=None),
                    f"PROVIDER_ID_CONFIRMED: {out.provisional_provider_order_id} (the amendment applied)")
    return out


def _replay_parked(view: OrderView) -> OrderView:
    """Apply fills that waited for a pending amendment's outcome, in arrival order."""
    parked, out = view.parked_fills, replace(view, parked_fills=())
    for fill in parked:
        out = _apply_fill(out, out, fill)
    return out


def _finish(before: OrderView, candidate: OrderView) -> OrderView:
    """Recount `candidate`, replay parked fills if their amendment resolved, then settle the state."""
    counted = _recount(candidate)
    if isinstance(counted, str):
        return _quarantine(before, counted)
    if counted.parked_fills and counted.amend_pending is None:
        counted = _replay_parked(counted)
        if counted.quarantine_reasons != before.quarantine_reasons:
            return counted
    return _settle(before, counted)


def _changed(before: OrderView, out: OrderView) -> bool:
    return out.quarantine_reasons != before.quarantine_reasons


# ---------------------------------------------------------------- handlers


def _on_send_prepared(view: OrderView, event: SendPrepared) -> OrderView:
    problems = may_send_new_order(view)
    if problems:
        return _quarantine(view, "RESEND_REFUSED: sending now would be a blind resubmission or a send of a "
                                 "quarantined order: " + "; ".join(problems))
    return replace(view, send_stage=SendStage.PREPARED, sent_at_utc=event.prepared_at_utc)


def _on_ambiguous(view: OrderView, event: SendReturnedAmbiguous) -> OrderView:
    op = event.operation
    if op is Operation.NEW_ORDER:
        if view.send_stage is SendStage.UNSENT:
            return _quarantine(view, "AMBIGUOUS_WITHOUT_SEND: no SendPrepared was recorded")
        if view.established or view.is_terminal:
            return _note(view, "AMBIGUOUS_AFTER_ESTABLISHED: the order is already known; nothing is unknown")
    elif op is Operation.CANCEL and not view.cancel_requested:
        return _quarantine(view, "AMBIGUOUS_WITHOUT_REQUEST: no cancel was requested")
    elif op is Operation.AMEND and view.amend_pending is None:
        if view.amend_reply_owed:
            return _note(replace(view, amend_reply_owed=False),
                         "AMBIGUOUS_AFTER_RESOLVED: a snapshot already showed the amendment applied")
        return _quarantine(view, "AMBIGUOUS_WITHOUT_REQUEST: no amendment was requested")
    if view.is_terminal:
        return _note(view, f"AMBIGUOUS_AFTER_TERMINAL: {op.value} outcome is moot ({view.state.value})")
    out = replace(view, ambiguous_operation=op)
    if out.state is OrderState.OUTCOME_UNKNOWN:
        return out
    return _move(view, out, OrderState.OUTCOME_UNKNOWN)


def _on_ack(view: OrderView, event: Acknowledged) -> OrderView:
    if not event.provider_order_id:
        return _quarantine(view, "MALFORMED_ACK: no provider order id")
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    status = _status(event.status)
    if status is None:
        return _quarantine(view, f"MALFORMED_ACK: unknown venue status {event.status!r}")
    if view.send_stage is SendStage.UNSENT:
        return _quarantine(view, "RECEIPT_FOR_UNSENT_ORDER: no SendPrepared was recorded")
    if view.state is OrderState.REJECTED:
        return _quarantine(view, "TERMINAL_CONTRADICTED: an acknowledgement for a REJECTED order")
    if event.provider_order_id in view.prior_provider_order_ids:
        return _note(replace(view, last_venue_status=status.value), "STALE_SNAPSHOT: for a replaced provider id")
    out = _link_provider_id(view, event.provider_order_id)
    out = replace(out, established=True, last_venue_status=status.value)
    if out.ambiguous_operation is Operation.NEW_ORDER:
        out = replace(out, ambiguous_operation=None)
    out = _merge_venue_counts(view, out, status, event.filled_quantity, event.remaining_quantity,
                              event.total_quantity, authoritative=False, complete=False,
                              as_of_utc=event.venue_time_utc, source="acknowledgement")
    if _changed(view, out):
        return out
    if status is VenueStatus.CANCELED and out.terminal_reason is None:
        out = replace(out, terminal_reason="canceled")
    return _finish(view, out)


def _on_rejected(view: OrderView, event: Rejected) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=False)
    if problem:
        return _quarantine(view, problem)
    op = event.operation
    if op is Operation.NEW_ORDER:
        if view.state is OrderState.REJECTED:
            return _note(view, f"DUPLICATE_REJECT: {event.reason}")
        if view.send_stage is SendStage.UNSENT:
            return _quarantine(view, "REJECT_WITHOUT_SEND: no SendPrepared was recorded")
        if view.established or view.filled_quantity > 0:
            return _quarantine(view, f"REJECT_CONTRADICTS_EVIDENCE: the order exists ({event.reason})")
        bare = event.provider_order_id is None and event.client_order_id is None
        if bare and view.ambiguous_operation is Operation.NEW_ORDER:
            return _note(view, f"BARE_REJECT_WHILE_UNKNOWN: {event.reason!r} names no order and cannot settle the "
                               f"lost send; reconcile")
        out = replace(view, terminal_reason=f"rejected: {event.reason}", ambiguous_operation=None)
        return _move(view, out, OrderState.REJECTED)
    if op is Operation.CANCEL:
        if not view.cancel_requested:
            return _note(view, f"STRAY_CANCEL_REJECT: {event.reason}")
        out = replace(view, cancel_requested=False,
                      ambiguous_operation=None if view.ambiguous_operation is Operation.CANCEL
                      else view.ambiguous_operation)
        return _finish(view, _note(out, f"CANCEL_REJECTED: {event.reason}"))
    if view.amend_pending is None:
        if view.amend_reply_owed:
            return _quarantine(replace(view, amend_reply_owed=False),
                               f"AMEND_REJECT_CONTRADICTS_SNAPSHOT: {event.reason!r}, but a snapshot showed it applied")
        return _note(view, f"STRAY_AMEND_REJECT: {event.reason}")
    if view.provisional_provider_order_id is not None:
        return _quarantine(view, f"PROVISIONAL_ID_UNCONFIRMED: the amendment was rejected ({event.reason!r}), but "
                                 f"receipts named {view.provisional_provider_order_id} as its replacement")
    out = replace(view, amend_pending=None, ambiguous_operation=None if view.ambiguous_operation is Operation.AMEND
                  else view.ambiguous_operation)
    return _finish(view, _note(out, f"AMEND_REJECTED: {event.reason}"))


def _merge_fill_record(view: OrderView, old: FillRecord, new: FillRecord) -> FillRecord | None:
    """`old` enriched by `new` (an unknown field may become known), or None if they conflict. Two provider
    ids of the same amendment lineage are the same order."""
    if (old.quantity, old.price) != (new.quantity, new.price):
        return None
    merged = {}
    for name in ("fee", "liquidity", "venue_time_utc", "provider_order_id"):
        a, b = getattr(old, name), getattr(new, name)
        if a is not None and b is not None and a != b:
            if name == "provider_order_id" and {a, b} <= view.provider_ids():
                merged[name] = a
                continue
            return None
        merged[name] = a if a is not None else b
    return replace(old, **merged)


def _limits(view: OrderView) -> list[Decimal]:
    out = list(view.limit_prices)
    if view.amend_pending is not None:
        out.append(view.amend_pending.new_price)  # the venue may fill at it before the ack arrives
    return out


def _apply_fill(before: OrderView, view: OrderView, event: Fill) -> OrderView:
    """Validate and apply one fill (recounted, not settled)."""
    if not event.fill_id:
        return _quarantine(before, "MALFORMED_FILL: no fill id")
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(before, problem)
    if event.quantity <= 0:
        return _quarantine(before, f"MALFORMED_FILL: quantity {event.quantity} is not positive")
    if not ZERO < event.price < ONE:
        return _quarantine(before, f"MALFORMED_FILL: price {event.price} is outside (0, 1)")
    if event.fee is not None and event.fee < 0:
        return _quarantine(before, f"MALFORMED_FILL: negative fee {event.fee}")
    if event.side is not None and event.side is not view.side:
        return _quarantine(before, f"FILL_SIDE_MISMATCH: {event.side.value} fill on a {view.side.value} order")
    if event.action is not None and event.action is not view.action:
        return _quarantine(before, f"FILL_ACTION_MISMATCH: {event.action.value} fill on a {view.action.value} order")
    if view.action is Action.BUY and event.price > max(_limits(view)):
        return _quarantine(before, f"FILL_PRICE_BEYOND_LIMIT: bought at {event.price} above every limit")
    if view.action is Action.SELL and event.price < min(_limits(view)):
        return _quarantine(before, f"FILL_PRICE_BEYOND_LIMIT: sold at {event.price} below every limit")
    linked = _link_provider_id(view, event.provider_order_id)
    record = FillRecord(event.fill_id, event.quantity, event.price, event.fee, event.liquidity, event.venue_time_utc,
                        event.provider_order_id)
    existing = view.fill(event.fill_id)
    if existing is not None:
        merged = _merge_fill_record(linked, existing, record)
        if merged is None:
            return _quarantine(before, f"FILL_CONFLICT: fill {event.fill_id} seen with different content")
        out = replace(linked, fills=tuple(merged if f.fill_id == event.fill_id else f for f in view.fills))
        counted = _recount(out)  # a newly known time may change what a venue count covers
        if isinstance(counted, str):
            return _quarantine(before, counted)
        return _note(counted, f"DUPLICATE_FILL: {event.fill_id}")
    if any(p.fill_id == event.fill_id for p in view.parked_fills):
        return _note(view, f"DUPLICATE_FILL: {event.fill_id} (parked)")
    if view.state is OrderState.REJECTED:
        return _quarantine(before, f"TERMINAL_CONTRADICTED: fill {event.fill_id} on a REJECTED order")
    out = replace(linked, fills=linked.fills + (record,))
    counted = _recount(out)
    if isinstance(counted, str):
        if _amend_up_pending(view) and _implied_filled(out.fills, out.count_observations) <= \
                view.amend_pending.new_total:
            return _note(replace(linked, parked_fills=view.parked_fills + (event,)),
                         f"FILL_PARKED: {event.fill_id} waits for the pending amendment's larger total")
        return _quarantine(before, counted)
    if counted.cancel_basis is CancelBasis.SOFT and counted.canceled_quantity < view.canceled_quantity:
        counted = _note(counted, f"LATE_FILL_REDUCED_CANCELED: {view.canceled_quantity - counted.canceled_quantity} "
                                 f"executed before the cancel")
    return counted


def _on_fill(view: OrderView, event: Fill) -> OrderView:
    if view.send_stage is SendStage.UNSENT:
        return _quarantine(view, "RECEIPT_FOR_UNSENT_ORDER: no SendPrepared was recorded")
    out = _apply_fill(view, view, event)
    if _changed(view, out):
        return out
    return _settle(view, out)


def _on_cancel_requested(view: OrderView, event: CancelRequested) -> OrderView:
    problems = cancel_problems(view)
    return _refuse(view, problems) if problems else replace(view, cancel_requested=True)


def _end_open_quantity(view: OrderView, *, reduced_by: Decimal | None, filled: Decimal | None,
                       remaining: Decimal | None, as_of_utc: str | None, reason: str) -> OrderView:
    """A venue cancel or expiry: everything not filled is canceled. Identity is already checked."""
    if not view.established:
        return _quarantine(view, f"{reason.upper()}_FOR_UNESTABLISHED_ORDER: reconcile first")
    for name, value in (("reduced_by", reduced_by), ("filled", filled), ("remaining", remaining)):
        if value is not None and value < 0:
            return _quarantine(view, f"MALFORMED_CANCEL: {name} {value} is negative")
    if remaining not in (None, ZERO):
        return _quarantine(view, f"MALFORMED_CANCEL: remaining {remaining} after a full {reason}")
    if reduced_by is not None and reduced_by > view.total_quantity:
        return _quarantine(view, f"MALFORMED_CANCEL: reduced_by {reduced_by} exceeds total {view.total_quantity}")
    if reduced_by is not None and filled is not None and filled + reduced_by != view.total_quantity:
        return _quarantine(view, f"MALFORMED_CANCEL: fill count {filled} + reduced_by {reduced_by} != total")
    if reduced_by is not None or filled is not None:
        floor = reduced_by if reduced_by is not None else view.total_quantity - filled
        out = _cancel_firm(view, floor, as_of_utc, reason)
        if isinstance(out, str):
            return _quarantine(view, out)
    else:
        out = _cancel_soft(view)
    out = replace(out, cancel_requested=False,
                  ambiguous_operation=None if view.ambiguous_operation is Operation.CANCEL
                  else view.ambiguous_operation)
    if not view.cancel_requested and reason == "cancel":
        out = _note(out, "UNSOLICITED_CANCEL: the venue canceled without a recorded request")
    if out.terminal_reason is None:
        out = replace(out, terminal_reason=reason)
    return _finish(view, out)


def _on_cancel_confirmed(view: OrderView, event: CancelConfirmed) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if view.state is OrderState.FILLED and event.reduced_by in (None, ZERO):
        return _note(replace(view, cancel_requested=False), "CANCEL_AFTER_FILLED: nothing was open")
    return _end_open_quantity(_link_provider_id(view, event.provider_order_id), reduced_by=event.reduced_by,
                              filled=event.filled_quantity, remaining=event.remaining_quantity,
                              as_of_utc=event.venue_time_utc, reason="cancel")


def _on_expired(view: OrderView, event: Expired) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if view.state is OrderState.FILLED:
        return _note(view, "EXPIRY_AFTER_FILLED: nothing was open")
    return _end_open_quantity(_link_provider_id(view, event.provider_order_id), reduced_by=None,
                              filled=event.filled_quantity, remaining=None, as_of_utc=event.venue_time_utc,
                              reason="expired")


def _on_amend_requested(view: OrderView, event: AmendRequested) -> OrderView:
    problems = amend_problems(view, event.new_total, event.new_price)
    if problems:
        return _refuse(view, problems)
    target = AmendTarget(view.total_quantity if event.new_total is None else event.new_total,
                         view.limit_price if event.new_price is None else event.new_price)
    return replace(view, amend_pending=target)


def _on_amend_ack(view: OrderView, event: AmendAcknowledged) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if not view.established:
        return _quarantine(view, "AMEND_FOR_UNESTABLISHED_ORDER: reconcile first")
    target = view.amend_pending
    if target is None:
        if event.new_total == view.total_quantity and event.new_price == view.limit_price:
            out = replace(view, amend_reply_owed=False)
            if event.new_provider_order_id is not None and event.new_provider_order_id not in view.provider_ids():
                return _quarantine(view, "IDENTITY_MISMATCH: the amend reply names a provider id never seen")
            return _note(out, "DUPLICATE_AMEND_ACK")
        view = _note(view, "UNSOLICITED_AMEND: the venue amended without a recorded request")
    elif (target.new_total, target.new_price) != (event.new_total, event.new_price):
        view = _note(view, f"AMEND_DIFFERS_FROM_REQUEST: asked {target.new_total}@{target.new_price}, venue "
                           f"{event.new_total}@{event.new_price}")
    before = view
    if event.filled_quantity is not None:
        if event.filled_quantity < 0 or (event.remaining_quantity is not None and event.remaining_quantity < 0):
            return _quarantine(before, "MALFORMED_AMEND_ACK: negative count")
        if event.remaining_quantity is not None and event.filled_quantity + event.remaining_quantity != event.new_total:
            return _quarantine(before, f"MALFORMED_AMEND_ACK: filled {event.filled_quantity} + remaining "
                                       f"{event.remaining_quantity} != total {event.new_total}")
    provisional = view.provisional_provider_order_id
    if provisional is not None and event.new_provider_order_id != provisional:
        return _quarantine(before, f"PROVISIONAL_ID_UNCONFIRMED: receipts named {provisional} as the replacement, "
                                   f"the amend reply names {event.new_provider_order_id}")
    amended = _apply_amend(view, event.new_total, event.new_price, event.new_provider_order_id)
    if isinstance(amended, str):
        return _quarantine(before, amended)
    amended = replace(amended, amend_reply_owed=False)
    if event.filled_quantity is not None:
        observed = _observe(amended, event.filled_quantity, event.venue_time_utc, final=False, authoritative=False,
                            complete=False, source="amend reply")
        if isinstance(observed, str):
            return _quarantine(before, observed)
        amended = observed
    return _finish(before, amended)


def _on_reconcile(view: OrderView, event: ReconcileObserved) -> OrderView:
    if not event.found:
        return _on_not_found(view, event)
    if not event.provider_order_id:
        return _quarantine(view, "MALFORMED_RECONCILE: found without a provider order id")
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    status = _status(event.status)
    if status is None:
        return _quarantine(view, f"MALFORMED_RECONCILE: unknown venue status {event.status!r}")
    if event.filled_quantity is None or (event.remaining_quantity is None and status is not VenueStatus.CANCELED):
        return _quarantine(view, "MALFORMED_RECONCILE: an authoritative snapshot is missing counts")
    if view.send_stage is SendStage.UNSENT:
        return _quarantine(view, "RECEIPT_FOR_UNSENT_ORDER: the venue holds an order this view never sent")
    if view.state is OrderState.REJECTED:
        return _quarantine(view, "TERMINAL_CONTRADICTED: the venue holds an order recorded as REJECTED")
    if status in (VenueStatus.RESTING, VenueStatus.PENDING) and view.is_terminal:
        return _quarantine(view, f"TERMINAL_CONTRADICTED: venue says {status.value}, view is {view.state.value}")
    if event.provider_order_id in view.prior_provider_order_ids:
        if view.provisional_provider_order_id is not None:
            return _quarantine(view, f"PROVISIONAL_ID_UNCONFIRMED: the venue still holds {event.provider_order_id}, "
                                     f"not the provisional {view.provisional_provider_order_id}")
        return _note(view, "STALE_SNAPSHOT: reconcile named a replaced provider id")
    out = _link_provider_id(view, event.provider_order_id)
    out = replace(out, established=True, last_venue_status=status.value)
    old_total = out.total_quantity
    out = _merge_venue_counts(view, out, status, event.filled_quantity, event.remaining_quantity,
                              event.total_quantity, authoritative=True, complete=event.authoritative_complete,
                              as_of_utc=event.as_of_utc, source="reconcile", price=event.price,
                              as_of_upper_utc=event.as_of_upper_utc)
    if _changed(view, out):
        return out
    if out.provisional_provider_order_id is not None and event.provider_order_id == out.provisional_provider_order_id:
        # The venue holds the replacement order: the amendment that created it applied.
        target = out.amend_pending or AmendTarget(out.total_quantity, out.limit_price)
        if (target.new_total, target.new_price) != (out.total_quantity, out.limit_price) and \
                (event.total_quantity is not None or event.price is not None):
            return _quarantine(view, "PROVISIONAL_ID_UNCONFIRMED: the replacement order does not carry the requested "
                                     "total and price")
        amended = _apply_amend(out, out.total_quantity, out.limit_price, None)
        if isinstance(amended, str):
            return _quarantine(view, amended)
        out = replace(amended, amend_reply_owed=True)
    ambiguity, still_unknown = out.ambiguous_operation, False
    if ambiguity is Operation.CANCEL and status is not VenueStatus.CANCELED:
        out = _note(replace(out, cancel_requested=False), "CANCEL_NOT_APPLIED_PER_RECONCILE")
    if ambiguity is Operation.AMEND and out.amend_pending is not None:
        target = out.amend_pending
        if target.new_price != out.limit_price and event.price is None:
            still_unknown = True  # a price change cannot be judged without the venue's price
            out = _note(out, "AMEND_OUTCOME_STILL_UNKNOWN: the snapshot has no price")
        elif out.total_quantity == old_total:
            if out.provisional_provider_order_id is not None:
                return _quarantine(view, "PROVISIONAL_ID_UNCONFIRMED: the reconcile shows the amendment not applied, "
                                         f"but receipts named {out.provisional_provider_order_id} as its replacement")
            out = _note(replace(out, amend_pending=None), "AMEND_NOT_APPLIED_PER_RECONCILE")
    if status is VenueStatus.CANCELED:
        out = replace(out, cancel_requested=False)
        if out.terminal_reason is None:
            out = replace(out, terminal_reason="canceled")
    if not still_unknown:
        out = replace(out, ambiguous_operation=None)
    return _finish(view, out)


def _on_not_found(view: OrderView, event: ReconcileObserved) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    out = replace(view, not_found_observations=view.not_found_observations + 1)
    if not event.authoritative_complete:
        return _note(out, "NOT_FOUND (not proof of absence: the query was not complete)")
    as_of, sent = _time(event.as_of_utc), _time(view.sent_at_utc)
    if as_of is None:
        return _note(out, "NOT_FOUND (not proof of absence: the snapshot has no usable time)")
    if view.send_stage is SendStage.UNSENT or view.is_terminal:
        return _note(out, "NOT_FOUND (authoritative, complete)")
    if sent is None or as_of < sent + NOT_FOUND_MIN_DELAY:
        return _note(out, f"NOT_FOUND_TOO_EARLY: snapshot {event.as_of_utc} is not {NOT_FOUND_MIN_DELAY} after the "
                          f"send at {view.sent_at_utc}; not proof of absence")
    out = _note(out, "NOT_FOUND (authoritative, complete)")
    if view.established or view.filled_quantity > 0:
        return _quarantine(out, "NOT_FOUND_CONTRADICTS_EVIDENCE: the order was established or filled")
    out = replace(out, terminal_reason="never accepted (authoritative not-found)", ambiguous_operation=None)
    return _move(view, out, OrderState.REJECTED)


_HANDLERS = MappingProxyType({
    SendPrepared: _on_send_prepared, SendReturnedAmbiguous: _on_ambiguous, Acknowledged: _on_ack,
    Rejected: _on_rejected, Fill: _on_fill, CancelRequested: _on_cancel_requested,
    CancelConfirmed: _on_cancel_confirmed, AmendRequested: _on_amend_requested, AmendAcknowledged: _on_amend_ack,
    Expired: _on_expired, ReconcileObserved: _on_reconcile,
})


def _counts_text(view: OrderView) -> str:
    return (f"total {view.total_quantity} filled {view.filled_quantity} remaining {view.remaining_quantity} "
            f"canceled {view.canceled_quantity} floor {view.canceled_floor}")


def reduce(view: OrderView, event: object) -> OrderView:
    """Fold one receipt into `view`. Pure and total: venue data never raises here. Every event is
    recorded in `receipts`; one that cannot be applied coherently quarantines the view instead. Every
    change of a count is logged in `count_log`."""
    if not isinstance(view, OrderView):
        raise TypeError("view must be an OrderView")
    recorded = replace(view, receipts=view.receipts + (event,))
    handler = _HANDLERS.get(type(event))
    if handler is None:
        return _quarantine(recorded, f"UNKNOWN_EVENT: {type(event).__name__}")
    out = handler(recorded, event)
    problems = invariant_problems(out)
    if problems:
        return _quarantine(recorded, *problems)
    if any(getattr(out, f) != getattr(view, f) for f in _COUNT_FIELDS):
        line = (f"#{len(out.receipts)} {type(event).__name__}: {_counts_text(view)} -> {_counts_text(out)}")
        out = replace(out, count_log=out.count_log + (line,))
    return out


def reduce_all(view: OrderView, events: Iterable[object]) -> OrderView:
    for event in events:
        view = reduce(view, event)
    return view


# ---------------------------------------------------------------- routing and projection


def route(views: Iterable[OrderView], *, provider_order_id: str | None = None,
          client_order_id: str | None = None) -> OrderView | None:
    """The one view a receipt belongs to, by identity only: client order id, or a current or prior
    provider order id. Never by price, size or time. None if nothing matches; two different matches
    raise, since a receipt cannot belong to two orders."""
    matches = []
    for v in views:
        if (client_order_id is not None and v.client_order_id == client_order_id) or \
                (provider_order_id is not None and provider_order_id in v.provider_ids()):
            matches.append(v)
    distinct = {v.client_order_id for v in matches}
    if len(distinct) > 1:
        raise LookupError(f"receipt matches several orders: {sorted(distinct)}")
    return matches[0] if matches else None


@dataclass(frozen=True)
class PositionProjection:
    """Held-position deltas and fees implied by our own orders' fills, per (market, side). A
    projection for display and cross-checks, NOT a P&L or position authority."""

    market_ticker: str
    side: Side
    bought: Decimal
    sold: Decimal
    fees_known: Decimal
    fees_complete: bool  # every filled contract has a fill receipt with a known fee
    contains_quarantined: bool  # at least one view is quarantined: do not rely on this entry
    order_count: int

    @property
    def net(self) -> Decimal:
        return self.bought - self.sold


def project_positions(views: Iterable[OrderView]) -> dict[tuple[str, Side], PositionProjection]:
    """Group filled quantity and known fees by (market, side). A repeated client order id raises
    (it would double count)."""
    seen: set[str] = set()
    acc: dict[tuple[str, Side], dict] = {}
    for v in views:
        if v.client_order_id in seen:
            raise ValueError(f"duplicate view for {v.client_order_id}")
        seen.add(v.client_order_id)
        a = acc.setdefault((v.market_ticker, v.side), {"bought": ZERO, "sold": ZERO, "fees": ZERO, "complete": True,
                                                        "quarantined": False, "count": 0})
        a["bought" if v.action is Action.BUY else "sold"] += v.filled_quantity
        a["fees"] += v.fees_known
        a["complete"] = a["complete"] and v.fees_complete
        a["quarantined"] = a["quarantined"] or v.quarantined
        a["count"] += 1
    ordered = sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1].value))
    return {key: PositionProjection(key[0], key[1], a["bought"], a["sold"], a["fees"], a["complete"], a["quarantined"],
                                    a["count"]) for key, a in ordered}
