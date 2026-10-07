"""The order-lifecycle reducer for ordinary Kalshi event-contract limit orders (#160 package H). Pure.

`reduce(view, event) -> view` folds one receipt into an immutable `OrderView`. Nothing here sends,
reads a clock, touches a store or decides anything: it only records what is known about one order.

Coarse state and detail
- The coarse state is always an `execution_ticket.OrderState` and moves only through
  `execution_ticket.transition`. The richer detail sits beside it: send stage, establishment, quantities,
  fills, a pending cancel or amendment, and an unresolved ambiguous operation.
- Quantities: `filled + remaining + canceled == total` after every event, and none is negative. A
  receipt that would break this is recorded but not applied, and the view is quarantined with the
  reason. Nothing is clamped.
- `filled` is the larger of the fills applied (by fill id) and the highest fill count the venue has
  reported. When the venue's count runs ahead of the fill receipts, the gap is fills still owed
  (`unreceived_fill_quantity`), and their fees are unknown, not zero.

Ambiguity and establishment
- A new order whose send returned ambiguously (timeout or connection loss after egress) is
  OUTCOME_UNKNOWN. Only an `Acknowledged` or a found `ReconcileObserved` establishes it. A fill
  carrying our client order id adds quantity but does not establish the order.
- A "not found" reconcile is NOT_FOUND evidence, never proof of absence, unless it says it is
  authoritative and complete for the scope. Only then does an unestablished, unfilled order end
  REJECTED with reason NEVER_ACCEPTED.
- A second `SendPrepared` is a blind resubmission and quarantines the view. `may_send_new_order`
  is the guard a sender checks first.

Cancellation, amendment and terminal states
- `CancelRequested` and `AmendRequested` change no quantity. Only the venue's confirmation does.
- Canceled does not mean never filled. A fill that executed before a cancel but arrives after the
  confirmation applies once and reduces the canceled quantity. It may not go below the part of the
  cancel the venue stated as an explicit count (`canceled_floor`); that would be a contradiction.
- The venue's amend count is the order's new TOTAL, already-filled contracts included, not a desired
  remainder: total 10 with 4 filled, amended to 8, leaves 4 resting. A requested total at or below the
  filled quantity is refused locally; one acknowledged below it quarantines.
- An amendment keeps the order's identity. If the venue assigns a new provider id, the old one moves to
  `prior_provider_order_ids`, and fills for either id still match. Fills from before stay attached.
- A terminal view still records every later receipt (`receipts`). If a receipt contradicts the terminal
  state, the view is quarantined; the state never moves back.

Identity: receipts match an order by provider order id or client order id, never by price, quantity or
time coincidence (`route`).

The venue field meanings assumed here (status words, `reduced_by`, the amend count, the fill fields) are
illustrative until the conformance pack confirms them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Iterable, Union

from ..execution_ticket import OrderState, transition
from .model import Action, OrderIntent, Side, exact_decimal, parse_utc_text

ZERO = Decimal(0)
ONE = Decimal(1)
TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})


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
    """Local: the new order is journaled and about to be transmitted. Recorded before egress."""


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
    client order id, including terminal ones)."""

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

    def __post_init__(self) -> None:
        _ident(self.provider_order_id, "provider_order_id")
        _ident(self.client_order_id, "client_order_id")
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
class AmendTarget:
    new_total: Decimal  # TOTAL quantity including filled
    new_price: Decimal


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
    established: bool  # an Acknowledged or a found ReconcileObserved has shown the order exists
    provider_order_id: str | None
    prior_provider_order_ids: tuple[str, ...]
    limit_price: Decimal
    limit_prices: tuple[Decimal, ...]  # every limit the order has carried, in order
    total_quantity: Decimal
    total_history: tuple[Decimal, ...]  # every total the order has had, in order
    filled_quantity: Decimal
    remaining_quantity: Decimal
    canceled_quantity: Decimal
    canceled_floor: Decimal  # the part of the cancel stated by an explicit venue count
    fills: tuple[FillRecord, ...]
    parked_fills: tuple[Fill, ...]  # fills beyond the open quantity while a larger amendment is pending
    cancel_requested: bool
    amend_pending: AmendTarget | None
    ambiguous_operation: Operation | None
    terminal_reason: str | None
    last_venue_status: str | None
    not_found_observations: int
    quarantine_reasons: tuple[str, ...]
    refusals: tuple[str, ...]  # local requests the reducer refused (nothing was sent for them)
    notes: tuple[str, ...]  # non-fatal observations: duplicates, stale snapshots, late fills
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
    def unreceived_fill_quantity(self) -> Decimal:
        """Contracts the venue counts as filled whose fill receipts have not arrived."""
        return self.filled_quantity - self.fill_quantity_applied

    @property
    def fees_known(self) -> Decimal:
        return sum((f.fee for f in self.fills if f.fee is not None), ZERO)

    @property
    def fees_complete(self) -> bool:
        """True only if every filled contract has a fill receipt with a known fee."""
        return (all(f.fee is not None for f in self.fills) and self.unreceived_fill_quantity == 0
                and not self.parked_fills)

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
        established=False, provider_order_id=None, prior_provider_order_ids=(), limit_price=price,
        limit_prices=(price,), total_quantity=qty, total_history=(qty,), filled_quantity=ZERO,
        remaining_quantity=qty, canceled_quantity=ZERO, canceled_floor=ZERO, fills=(), parked_fills=(),
        cancel_requested=False, amend_pending=None, ambiguous_operation=None, terminal_reason=None,
        last_venue_status=None, not_found_observations=0, quarantine_reasons=(), refusals=(), notes=(),
        receipts=())


def view_from_intent(intent: OrderIntent) -> OrderView:
    return open_view(client_order_id=intent.client_order_id(), market_ticker=intent.market_ticker, side=intent.side,
                     action=intent.action, quantity=intent.quantity, limit_price=intent.limit_price,
                     intent_digest=intent.digest())


# ---------------------------------------------------------------- invariants and guards


def invariant_problems(view: OrderView) -> list[str]:
    """Why `view`'s quantities or state are incoherent (empty: they hold)."""
    out = []
    names = ("total_quantity", "filled_quantity", "remaining_quantity", "canceled_quantity", "canceled_floor")
    for name in names:
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
    if view.canceled_floor > view.canceled_quantity:
        out.append(f"INVARIANT: canceled {view.canceled_quantity} is below the venue-stated {view.canceled_floor}")
    if view.state is OrderState.REJECTED and view.filled_quantity > 0:
        out.append("INVARIANT: a REJECTED order has fills")
    if view.state is OrderState.FILLED and view.filled_quantity != view.total_quantity:
        out.append("INVARIANT: a FILLED order is not fully filled")
    if view.state is OrderState.CANCELLED and view.remaining_quantity != 0:
        out.append("INVARIANT: a CANCELLED order still has a remainder")
    if view.state in (OrderState.RESTING,) and not view.established:
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
    if view.cancel_requested:
        out.append("AMEND_WHILE_CANCEL_PENDING")
    if view.ambiguous_operation is not None:
        out.append(f"RECONCILE_FIRST: {view.ambiguous_operation.value} outcome unknown")
    if new_total is None and new_price is None:
        out.append("AMEND_EMPTY")
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
            return f"IDENTITY_MISMATCH: provider order id {provider_order_id!r} is not {sorted(known)}"
        if not known and client_order_id is None:
            return f"IDENTITY_UNMATCHED: provider order id {provider_order_id!r} is not yet linked to this order"
    elif client_order_id is None and require:
        return "IDENTITY_MISSING: the receipt names no order"
    return None


def _adopt_provider_id(view: OrderView, provider_order_id: str | None) -> OrderView:
    if provider_order_id is None or view.provider_order_id is not None or provider_order_id in view.provider_ids():
        return view
    return replace(view, provider_order_id=provider_order_id)


def _counts(view: OrderView, *, total: Decimal | None = None, filled: Decimal | None = None,
            canceled: Decimal | None = None, floor: Decimal | None = None) -> OrderView:
    """`view` with new counts; remaining is derived. A negative result is left for the invariant check."""
    total = view.total_quantity if total is None else total
    filled = view.filled_quantity if filled is None else filled
    canceled = view.canceled_quantity if canceled is None else canceled
    floor = view.canceled_floor if floor is None else floor
    history = view.total_history if total == view.total_quantity else view.total_history + (total,)
    return replace(view, total_quantity=total, filled_quantity=filled, canceled_quantity=canceled,
                   canceled_floor=floor, remaining_quantity=total - filled - canceled, total_history=history)


def _raise_filled(view: OrderView, new_filled: Decimal) -> OrderView | str:
    """Raise `filled` to `new_filled`, taking the delta from the remainder first and then from the soft
    (not venue-counted) part of a cancel: a fill that executed before the cancel. Returns a reason
    string if the delta does not fit."""
    delta = new_filled - view.filled_quantity
    if delta <= 0:
        return view
    from_remaining = min(delta, view.remaining_quantity)
    from_canceled = delta - from_remaining
    soft_canceled = view.canceled_quantity - view.canceled_floor
    if from_canceled > soft_canceled:
        return (f"FILL_EXCEEDS_OPEN_QUANTITY: filled would be {new_filled} of total {view.total_quantity} "
                f"(remaining {view.remaining_quantity}, venue-stated canceled {view.canceled_floor})")
    out = _counts(view, filled=new_filled, canceled=view.canceled_quantity - from_canceled)
    if from_canceled > 0:
        out = _note(out, f"LATE_FILL_REDUCED_CANCELED: {from_canceled} executed before the cancel")
    return out


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


def _status(text: str | None) -> VenueStatus | None:
    try:
        return VenueStatus(text)
    except ValueError:
        return None


def _latest_fill_time(view: OrderView):
    times = []
    for f in view.fills:
        if f.venue_time_utc is None:
            return None
        try:
            times.append(parse_utc_text(f.venue_time_utc))
        except ValueError:
            return None
    return max(times) if times else None


def _snapshot_predates_fills(view: OrderView, as_of_utc: str | None) -> bool:
    """True only if `as_of_utc` is provably earlier than the newest applied fill."""
    if as_of_utc is None:
        return False
    try:
        as_of = parse_utc_text(as_of_utc)
    except ValueError:
        return False
    latest = _latest_fill_time(view)
    return latest is not None and as_of < latest


def _merge_venue_counts(before: OrderView, view: OrderView, status: VenueStatus, filled: Decimal | None,
                        remaining: Decimal | None, total: Decimal | None, *, authoritative: bool,
                        as_of_utc: str | None, price: Decimal | None = None) -> OrderView:
    """Fold a venue snapshot's counts into `view`. Counts only ever move forward: a lower fill count
    than already known is stale (noted), except where a final or authoritative snapshot proves a
    contradiction (quarantined)."""
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
            view = _apply_amend(view, target.new_total, target.new_price, None)
            if isinstance(view, str):
                return _quarantine(before, view)
            view = _note(view, "AMEND_APPLIED_PER_SNAPSHOT")
        elif not authoritative and venue_total in view.total_history:
            return _note(view, f"STALE_SNAPSHOT: total {venue_total} predates the current total "
                               f"{view.total_quantity}")
        else:
            return _quarantine(before, f"TOTAL_MISMATCH: venue total {venue_total} != {view.total_quantity}")
    if price is not None and price != view.limit_price:
        target = view.amend_pending
        if target is not None and price == target.new_price and target.new_total == view.total_quantity:
            view = _apply_amend(view, target.new_total, target.new_price, None)
            if isinstance(view, str):
                return _quarantine(before, view)
        elif authoritative:
            return _quarantine(before, f"PRICE_MISMATCH: venue price {price} != {view.limit_price}")

    applied = view.fill_quantity_applied
    new_filled = view.filled_quantity
    if filled is not None:
        if filled < applied:
            final = status in (VenueStatus.CANCELED, VenueStatus.EXECUTED)
            if final or (authoritative and not _snapshot_predates_fills(view, as_of_utc)):
                return _quarantine(before, f"COUNT_BELOW_APPLIED_FILLS: venue fill count {filled} < fills applied "
                                           f"{applied} (status {status.value})")
            view = _note(view, f"STALE_FILL_COUNT: {filled} < fills applied {applied}")
        new_filled = max(view.filled_quantity, filled)

    if status is VenueStatus.CANCELED:
        if filled is not None and view.filled_quantity > filled:
            return _quarantine(before, f"COUNT_BELOW_KNOWN_FILLS: canceled with fill count {filled} < known "
                                       f"{view.filled_quantity}")
        canceled = view.total_quantity - new_filled
        floor = canceled if filled is not None else view.canceled_floor
        return _counts(view, filled=new_filled, canceled=canceled, floor=floor)
    out = _raise_filled(view, new_filled)
    if isinstance(out, str):
        return _quarantine(before, out)
    return out


def _apply_amend(view: OrderView, new_total: Decimal, new_price: Decimal,
                 new_provider_order_id: str | None) -> OrderView | str:
    if new_total < view.filled_quantity:
        return f"AMEND_TOTAL_BELOW_FILLED: venue total {new_total} < filled {view.filled_quantity}"
    if not ZERO < new_price < ONE:
        return f"AMEND_PRICE_OUT_OF_RANGE: {new_price}"
    out = _counts(view, total=new_total)
    prices = out.limit_prices if new_price == out.limit_price else out.limit_prices + (new_price,)
    out = replace(out, limit_price=new_price, limit_prices=prices, amend_pending=None,
                  ambiguous_operation=None if out.ambiguous_operation is Operation.AMEND else out.ambiguous_operation)
    if new_provider_order_id is not None and new_provider_order_id != out.provider_order_id:
        prior = out.prior_provider_order_ids + ((out.provider_order_id,) if out.provider_order_id else ())
        out = replace(out, provider_order_id=new_provider_order_id, prior_provider_order_ids=prior)
    return _replay_parked(out)


def _replay_parked(view: OrderView) -> OrderView:
    """Apply fills that waited for a pending amendment's outcome, in arrival order."""
    parked, out = view.parked_fills, replace(view, parked_fills=())
    for fill in parked:
        out = _apply_fill(out, out, fill)
    return out


# ---------------------------------------------------------------- handlers


def _on_send_prepared(view: OrderView, event: SendPrepared) -> OrderView:
    problems = may_send_new_order(view)
    if problems:
        return _quarantine(view, "RESEND_REFUSED: sending now would be a blind resubmission or a send of a "
                                 "quarantined order: " + "; ".join(problems))
    return replace(view, send_stage=SendStage.PREPARED)


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
        return _quarantine(view, "AMBIGUOUS_WITHOUT_REQUEST: no amendment was requested")
    if view.is_terminal:
        return _note(view, f"AMBIGUOUS_AFTER_TERMINAL: {op.value} outcome is moot ({view.state.value})")
    out = replace(view, ambiguous_operation=op)
    if out.state is OrderState.OUTCOME_UNKNOWN:
        return out
    return _move(view, out, OrderState.OUTCOME_UNKNOWN)


def _move(before: OrderView, candidate: OrderView, state: OrderState) -> OrderView:
    try:
        return replace(candidate, state=transition(candidate.state, state))
    except ValueError as exc:
        return _quarantine(before, f"ILLEGAL_TRANSITION: {exc}")


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
    out = _adopt_provider_id(view, event.provider_order_id)
    out = replace(out, established=True, last_venue_status=status.value)
    if out.ambiguous_operation is Operation.NEW_ORDER:
        out = replace(out, ambiguous_operation=None)
    out = _merge_venue_counts(view, out, status, event.filled_quantity, event.remaining_quantity,
                              event.total_quantity, authoritative=False, as_of_utc=event.venue_time_utc)
    if out.quarantine_reasons != view.quarantine_reasons:
        return out
    if status is VenueStatus.CANCELED and out.terminal_reason is None:
        out = replace(out, terminal_reason="canceled")
    return _settle(view, out)


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
        out = replace(view, terminal_reason=f"rejected: {event.reason}", ambiguous_operation=None)
        return _move(view, out, OrderState.REJECTED)
    if op is Operation.CANCEL:
        if not view.cancel_requested:
            return _note(view, f"STRAY_CANCEL_REJECT: {event.reason}")
        out = replace(view, cancel_requested=False,
                      ambiguous_operation=None if view.ambiguous_operation is Operation.CANCEL
                      else view.ambiguous_operation)
        return _settle(view, _note(out, f"CANCEL_REJECTED: {event.reason}"))
    if view.amend_pending is None:
        return _note(view, f"STRAY_AMEND_REJECT: {event.reason}")
    out = replace(view, amend_pending=None, ambiguous_operation=None if view.ambiguous_operation is Operation.AMEND
                  else view.ambiguous_operation)
    out = _note(out, f"AMEND_REJECTED: {event.reason}")
    return _settle(view, _replay_parked(out))


def _merge_fill_record(old: FillRecord, new: FillRecord) -> FillRecord | None:
    """`old` enriched by `new` (an unknown field may become known), or None if they conflict."""
    if (old.quantity, old.price) != (new.quantity, new.price):
        return None
    merged = {}
    for name in ("fee", "liquidity", "venue_time_utc", "provider_order_id"):
        a, b = getattr(old, name), getattr(new, name)
        if a is not None and b is not None and a != b:
            return None
        merged[name] = a if a is not None else b
    return replace(old, **merged)


def _apply_fill(before: OrderView, view: OrderView, event: Fill) -> OrderView:
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
    if view.action is Action.BUY and event.price > max(view.limit_prices):
        return _quarantine(before, f"FILL_PRICE_BEYOND_LIMIT: bought at {event.price} above every limit")
    if view.action is Action.SELL and event.price < min(view.limit_prices):
        return _quarantine(before, f"FILL_PRICE_BEYOND_LIMIT: sold at {event.price} below every limit")
    record = FillRecord(event.fill_id, event.quantity, event.price, event.fee, event.liquidity, event.venue_time_utc,
                        event.provider_order_id)
    existing = view.fill(event.fill_id)
    if existing is not None:
        merged = _merge_fill_record(existing, record)
        if merged is None:
            return _quarantine(before, f"FILL_CONFLICT: fill {event.fill_id} seen with different content")
        out = replace(view, fills=tuple(merged if f.fill_id == event.fill_id else f for f in view.fills))
        return _note(out, f"DUPLICATE_FILL: {event.fill_id}")
    if any(p.fill_id == event.fill_id for p in view.parked_fills):
        return _note(view, f"DUPLICATE_FILL: {event.fill_id} (parked)")
    if view.state is OrderState.REJECTED:
        return _quarantine(before, f"TERMINAL_CONTRADICTED: fill {event.fill_id} on a REJECTED order")
    out = _adopt_provider_id(view, event.provider_order_id)
    out = replace(out, fills=out.fills + (record,))
    new_filled = max(out.filled_quantity, out.fill_quantity_applied)
    raised = _raise_filled(out, new_filled)
    if isinstance(raised, str):
        if _amend_up_pending(view) and new_filled <= view.amend_pending.new_total:
            return _note(replace(view, parked_fills=view.parked_fills + (event,)),
                         f"FILL_PARKED: {event.fill_id} waits for the pending amendment's larger total")
        return _quarantine(before, raised)
    return raised


def _on_fill(view: OrderView, event: Fill) -> OrderView:
    if view.send_stage is SendStage.UNSENT:
        return _quarantine(view, "RECEIPT_FOR_UNSENT_ORDER: no SendPrepared was recorded")
    out = _apply_fill(view, view, event)
    if out.quarantine_reasons != view.quarantine_reasons:
        return out
    return _settle(view, out)


def _on_cancel_requested(view: OrderView, event: CancelRequested) -> OrderView:
    problems = cancel_problems(view)
    return _refuse(view, problems) if problems else replace(view, cancel_requested=True)


def _end_open_quantity(view: OrderView, *, provider_order_id: str | None, client_order_id: str | None,
                       reduced_by: Decimal | None, filled: Decimal | None, remaining: Decimal | None,
                       reason: str) -> OrderView:
    """A venue cancel or expiry: everything not filled is canceled."""
    problem = _identity_problem(view, provider_order_id, client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if not view.established:
        return _quarantine(view, f"{reason.upper()}_FOR_UNESTABLISHED_ORDER: reconcile first")
    for name, value in (("reduced_by", reduced_by), ("filled", filled), ("remaining", remaining)):
        if value is not None and value < 0:
            return _quarantine(view, f"MALFORMED_CANCEL: {name} {value} is negative")
    if remaining not in (None, ZERO):
        return _quarantine(view, f"MALFORMED_CANCEL: remaining {remaining} after a full {reason}")
    new_filled = view.filled_quantity if filled is None else max(view.filled_quantity, filled)
    if filled is not None and view.filled_quantity > filled:
        return _quarantine(view, f"COUNT_BELOW_KNOWN_FILLS: {reason} with fill count {filled} < known "
                                 f"{view.filled_quantity}")
    floor = view.canceled_floor
    if reduced_by is not None:
        implied = view.total_quantity - reduced_by
        if implied < 0:
            return _quarantine(view, f"MALFORMED_CANCEL: reduced_by {reduced_by} exceeds total {view.total_quantity}")
        if filled is not None and filled != implied:
            return _quarantine(view, f"MALFORMED_CANCEL: fill count {filled} + reduced_by {reduced_by} != total")
        if new_filled > implied:
            return _quarantine(view, f"CANCEL_COUNT_CONTRADICTS_FILLS: reduced_by {reduced_by} leaves {implied} "
                                     f"filled, but {new_filled} is known")
        new_filled, floor = implied, reduced_by
    elif filled is not None:
        floor = view.total_quantity - new_filled
    if view.state is OrderState.CANCELLED and reduced_by is None and filled is None:
        return _note(view, f"DUPLICATE_{reason.upper()}")
    out = _counts(view, filled=new_filled, canceled=view.total_quantity - new_filled, floor=floor)
    out = replace(out, cancel_requested=False,
                  ambiguous_operation=None if view.ambiguous_operation is Operation.CANCEL
                  else view.ambiguous_operation)
    if not view.cancel_requested and reason == "cancel":
        out = _note(out, "UNSOLICITED_CANCEL: the venue canceled without a recorded request")
    if out.canceled_quantity > 0 and out.terminal_reason is None:
        out = replace(out, terminal_reason=reason)
    return _settle(view, out)


def _on_cancel_confirmed(view: OrderView, event: CancelConfirmed) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if view.state is OrderState.FILLED and event.reduced_by in (None, ZERO):
        return _note(replace(view, cancel_requested=False), "CANCEL_AFTER_FILLED: nothing was open")
    return _end_open_quantity(view, provider_order_id=event.provider_order_id, client_order_id=event.client_order_id,
                              reduced_by=event.reduced_by, filled=event.filled_quantity,
                              remaining=event.remaining_quantity, reason="cancel")


def _on_expired(view: OrderView, event: Expired) -> OrderView:
    problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
    if problem:
        return _quarantine(view, problem)
    if view.state is OrderState.FILLED:
        return _note(view, "EXPIRY_AFTER_FILLED: nothing was open")
    return _end_open_quantity(view, provider_order_id=event.provider_order_id, client_order_id=event.client_order_id,
                              reduced_by=None, filled=event.filled_quantity, remaining=None, reason="expired")


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
            return _note(view, "DUPLICATE_AMEND_ACK")
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
    amended = _apply_amend(view, event.new_total, event.new_price, event.new_provider_order_id)
    if isinstance(amended, str):
        return _quarantine(before, amended)
    if amended.quarantine_reasons != before.quarantine_reasons:
        return amended
    if event.filled_quantity is not None:
        raised = _raise_filled(amended, max(amended.filled_quantity, event.filled_quantity))
        if isinstance(raised, str):
            return _quarantine(before, raised)
        amended = raised
    return _settle(before, amended)


def _on_reconcile(view: OrderView, event: ReconcileObserved) -> OrderView:
    if not event.found:
        problem = _identity_problem(view, event.provider_order_id, event.client_order_id, require=True)
        if problem:
            return _quarantine(view, problem)
        out = replace(view, not_found_observations=view.not_found_observations + 1)
        out = _note(out, "NOT_FOUND" + (" (authoritative, complete)" if event.authoritative_complete
                                        else " (not proof of absence)"))
        if not event.authoritative_complete:
            return out
        if view.established or view.filled_quantity > 0:
            return _quarantine(out, "NOT_FOUND_CONTRADICTS_EVIDENCE: the order was established or filled")
        if view.is_terminal:
            return out
        if view.send_stage is SendStage.UNSENT:
            return out  # nothing was sent: absence is expected
        out = replace(out, terminal_reason="never accepted (authoritative not-found)", ambiguous_operation=None)
        return _move(view, out, OrderState.REJECTED)

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
        return _note(view, "STALE_SNAPSHOT: reconcile named a replaced provider id")
    out = _adopt_provider_id(view, event.provider_order_id)
    out = replace(out, established=True, last_venue_status=status.value)
    old_total = out.total_quantity
    out = _merge_venue_counts(view, out, status, event.filled_quantity, event.remaining_quantity,
                              event.total_quantity, authoritative=True, as_of_utc=event.as_of_utc, price=event.price)
    if out.quarantine_reasons != view.quarantine_reasons:
        return out
    ambiguity, still_unknown = out.ambiguous_operation, False
    if ambiguity is Operation.CANCEL and status is not VenueStatus.CANCELED:
        out = _note(replace(out, cancel_requested=False), "CANCEL_NOT_APPLIED_PER_RECONCILE")
    if ambiguity is Operation.AMEND and out.amend_pending is not None:
        target = out.amend_pending
        if target.new_price != out.limit_price and event.price is None:
            still_unknown = True  # a price change cannot be judged without the venue's price
            out = _note(out, "AMEND_OUTCOME_STILL_UNKNOWN: the snapshot has no price")
        elif out.total_quantity == old_total:
            out = _note(replace(out, amend_pending=None), "AMEND_NOT_APPLIED_PER_RECONCILE")
    if status is VenueStatus.CANCELED:
        out = replace(out, cancel_requested=False)
        if out.terminal_reason is None and out.canceled_quantity > 0:
            out = replace(out, terminal_reason="canceled")
    if not still_unknown:
        out = replace(out, ambiguous_operation=None)
    if out.parked_fills and out.amend_pending is None:
        out = _replay_parked(out)
    return _settle(view, out)


_HANDLERS = {
    SendPrepared: _on_send_prepared, SendReturnedAmbiguous: _on_ambiguous, Acknowledged: _on_ack,
    Rejected: _on_rejected, Fill: _on_fill, CancelRequested: _on_cancel_requested,
    CancelConfirmed: _on_cancel_confirmed, AmendRequested: _on_amend_requested, AmendAcknowledged: _on_amend_ack,
    Expired: _on_expired, ReconcileObserved: _on_reconcile,
}


def reduce(view: OrderView, event: object) -> OrderView:
    """Fold one receipt into `view`. Pure and total: venue data never raises here. Every event is
    recorded in `receipts`; one that cannot be applied coherently quarantines the view instead."""
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
