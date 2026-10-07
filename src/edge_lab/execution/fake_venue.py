"""A deterministic, in-memory fake exchange for scenario tests (#160 package H). Tests only; no network.

It is not a model of Kalshi. It is a small, predictable engine that produces venue-shaped receipts
(replies, a stream feed, read-back snapshots) so the lifecycle reducer and later integration tests
can be exercised against partial fills, cancels, amendments, ambiguity and faults.

Book and price mapping
- Each market has two bid ladders, YES bids and NO bids, as on Kalshi. There are no asks: a YES ask at
  p is a NO bid at 1 - p.
- An order joins the book as a bid on one ladder:
  - BUY YES at p is a YES bid at p;
  - SELL YES at p is a NO bid at 1 - p;
  - BUY NO at p is a NO bid at p (it takes YES bids at 1 - p or higher);
  - SELL NO at p is a YES bid at 1 - p.
- A YES bid y and a NO bid n cross when y + n >= 1. Trades print at the resting (maker) bid. For our
  order, the price per contract of its own side is (1 - maker bid) for a BUY and the maker bid for a SELL.
- Matching is price-time: best price first, then arrival sequence. Test-configured liquidity
  (`add_liquidity`) and our own resting orders share the book. Liquidity added later that crosses our
  resting order fills it as maker.

Order handling
- GTC rests its remainder. IOC cancels its unfilled remainder (status canceled). FOK fills completely
  or not at all (status canceled, nothing filled).
- Post-only is rejected when it would cross. An order of ours that would cross our own resting order is
  rejected (SELF_CROSS) before any matching: a deliberately simple self-trade rule.
- Reduce-only is checked against the fake account's position net of resting sells. Short selling is
  not supported (INSUFFICIENT_POSITION).
- Amend takes the new TOTAL count, filled contracts included, and/or a new price. An amended order
  loses time priority. `amend_assigns_new_order_id=True` gives the amended order a new id.
- Client order ids are deduplicated forever: a repeat is refused with DUPLICATE_CLIENT_ORDER_ID.
- Fees come only from the caller's hook `fee(price, quantity, liquidity) -> Decimal`. Without a hook,
  every fee is None (unknown). The fake never invents a schedule.

Faults (`inject`): DROP_ACK, DUPLICATE_ACK, DELAY_FILL, ACCEPT_THEN_TIMEOUT, LOSE_REQUEST, REJECT,
PAUSE, OUT_OF_ORDER. Each is explicit, and every arming, firing and clearing is in `fault_log`.

Deliberately absent: fee schedules, settlement, market status or close times, cash netting of
YES/NO pairs, order groups, decrease-by, self-trade modes, rate limits, websocket sequence numbers,
subaccounts and anything network-shaped.

The dict field names mimic Kalshi's for readability. They are ILLUSTRATIVE until the conformance
pack (another lane) confirms the real names and meanings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

from . import lifecycle as lc
from .model import Action, ExactValueError, Grid, Side, TimeInForce, exact_decimal, utc_text

ONE = Decimal(1)
ZERO = Decimal(0)
CENT_GRID = Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE_CONTRACTS = Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("1000000"))
DEFAULT_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

FeeHook = Callable[[Decimal, Decimal, lc.Liquidity], Decimal]


class Fault(str, Enum):
    DROP_ACK = "DROP_ACK"  # new order accepted; the reply is lost and the feed's order message never comes
    DUPLICATE_ACK = "DUPLICATE_ACK"  # the feed carries the order message twice
    DELAY_FILL = "DELAY_FILL"  # fill messages are held until `release_delayed_fills`
    ACCEPT_THEN_TIMEOUT = "ACCEPT_THEN_TIMEOUT"  # the operation happens; the caller sees a timeout
    LOSE_REQUEST = "LOSE_REQUEST"  # the request never arrives; the caller sees a timeout
    REJECT = "REJECT"  # the operation is refused with the injected reason
    PAUSE = "PAUSE"  # cancels are refused (TRADING_PAUSED) until cleared
    OUT_OF_ORDER = "OUT_OF_ORDER"  # the next drain returns the feed reversed


# Faults that apply per operation; the others are feed-level.
_OPERATION_FAULTS = frozenset({Fault.DROP_ACK, Fault.ACCEPT_THEN_TIMEOUT, Fault.LOSE_REQUEST, Fault.REJECT})


@dataclass(frozen=True)
class Reply:
    """The synchronous answer the caller sees. `timeout` and `lost` are ambiguous: the request may or may
    not have taken effect."""

    outcome: str  # "ok" | "error" | "timeout" | "lost"
    body: dict | None = None
    error: str | None = None

    @property
    def ambiguous(self) -> bool:
        return self.outcome in ("timeout", "lost")


@dataclass
class _Armed:
    fault: Fault
    operation: lc.Operation | None
    remaining: int | None  # None: until cleared
    reason: str | None


@dataclass
class _Order:
    order_id: str
    client_order_id: str
    ticker: str
    side: Side
    action: Action
    price: Decimal
    time_in_force: TimeInForce
    post_only: bool
    reduce_only: bool
    initial_count: Decimal
    total_count: Decimal
    fill_count: Decimal
    remaining_count: Decimal
    status: str
    created_time: str
    last_update_time: str
    end_reason: str | None = None


@dataclass
class _Entry:
    seq: int
    price: Decimal  # the bid on this ladder
    quantity: Decimal
    order_id: str | None  # None: anonymous test liquidity


class FakeVenue:
    def __init__(self, *, fee: FeeHook | None = None, price_grid: Grid = CENT_GRID,
                 quantity_grid: Grid = WHOLE_CONTRACTS, cash: object = "1000", start: datetime = DEFAULT_START,
                 amend_assigns_new_order_id: bool = False) -> None:
        if not isinstance(price_grid, Grid) or not isinstance(quantity_grid, Grid):
            raise TypeError("grids must be model.Grid values")
        self.price_grid, self.quantity_grid = price_grid, quantity_grid
        self._fee = fee
        self._start = start
        self._seq = 0
        self._order_counter = 0
        self._fill_counter = 0
        self.amend_assigns_new_order_id = amend_assigns_new_order_id
        self.cash = exact_decimal(cash, name="cash")
        self.positions: dict[tuple[str, Side], Decimal] = {}
        self.fees_unknown = False
        self._orders: dict[str, _Order] = {}
        self._replaced: dict[str, str] = {}  # old order id -> new order id
        self._client_ids: set[str] = set()
        self._book: dict[tuple[str, Side], list[_Entry]] = {}
        self._fills: list[dict] = []
        self._feed: list[dict] = []
        self._delayed: list[dict] = []
        self._armed: list[_Armed] = []
        self.fault_log: list[dict] = []

    # ---------------------------------------------------------------- clock and ids

    def _tick(self) -> str:
        self._seq += 1
        return utc_text(self._start + timedelta(seconds=self._seq))

    def now_text(self) -> str:
        return utc_text(self._start + timedelta(seconds=self._seq))

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"fake-ord-{self._order_counter:06d}"

    def _next_fill_id(self) -> str:
        self._fill_counter += 1
        return f"fake-fill-{self._fill_counter:06d}"

    # ---------------------------------------------------------------- faults

    def inject(self, fault: Fault, *, operation: lc.Operation | None = None, times: int | None = 1,
               reason: str | None = None) -> None:
        """Arm a fault. Operation faults need an `operation` (DROP_ACK is for new orders only). PAUSE
        stays armed until `clear`. REJECT needs a `reason` code."""
        if not isinstance(fault, Fault):
            raise TypeError("fault must be a Fault")
        if fault in _OPERATION_FAULTS and not isinstance(operation, lc.Operation):
            raise ValueError(f"{fault.value} needs an operation")
        if fault not in _OPERATION_FAULTS and operation is not None:
            raise ValueError(f"{fault.value} takes no operation")
        if fault is Fault.DROP_ACK and operation is not lc.Operation.NEW_ORDER:
            raise ValueError("DROP_ACK applies to new orders only")
        if fault is Fault.REJECT and not reason:
            raise ValueError("REJECT needs a reason code")
        if fault is Fault.PAUSE:
            times = None
        elif times is None or times < 1:
            raise ValueError("times must be a positive int")
        self._armed.append(_Armed(fault, operation, times, reason))
        self._log("armed", fault, operation, detail=reason)

    def clear(self, fault: Fault) -> None:
        self._armed = [a for a in self._armed if a.fault is not fault]
        self._log("cleared", fault, None)

    def _log(self, what: str, fault: Fault, operation: lc.Operation | None, *, order_id: str | None = None,
             detail: str | None = None) -> None:
        self.fault_log.append({"n": len(self.fault_log) + 1, "event": what, "fault": fault.value,
                               "operation": operation.value if operation else None, "order_id": order_id,
                               "detail": detail})

    def _take(self, fault: Fault, operation: lc.Operation | None = None, *,
              order_id: str | None = None) -> _Armed | None:
        for armed in self._armed:
            if armed.fault is fault and (armed.operation is None or armed.operation is operation):
                if armed.remaining is not None:
                    armed.remaining -= 1
                    if armed.remaining == 0:
                        self._armed.remove(armed)
                self._log("fired", fault, operation, order_id=order_id, detail=armed.reason)
                return armed
        return None

    def _active(self, fault: Fault) -> bool:
        return any(a.fault is fault for a in self._armed)

    # ---------------------------------------------------------------- feed

    def _emit(self, message: dict) -> None:
        if message["type"] == "fill" and self._take(Fault.DELAY_FILL, order_id=message["fill"]["order_id"]):
            self._delayed.append(message)
            return
        self._feed.append(message)

    def _emit_order(self, order: _Order, *, reason: str | None = None, drop: bool = False) -> None:
        if drop:
            return
        message = {"type": "order_update", "order": self._snapshot(order), "reason": reason}
        self._feed.append(message)
        if self._take(Fault.DUPLICATE_ACK, order_id=order.order_id):
            self._feed.append({"type": "order_update", "order": self._snapshot(order), "reason": reason})

    def drain_events(self) -> list[dict]:
        """Every feed message since the last drain, in emission order (reversed if OUT_OF_ORDER fires)."""
        out, self._feed = self._feed, []
        if out and self._take(Fault.OUT_OF_ORDER):
            out.reverse()
        return out

    def release_delayed_fills(self) -> int:
        count = len(self._delayed)
        self._feed.extend(self._delayed)
        self._delayed = []
        return count

    # ---------------------------------------------------------------- liquidity and matching

    def add_liquidity(self, ticker: str, side: Side, price: object, quantity: object) -> Decimal:
        """Anonymous resting bid for `side` at `price`. If it crosses, it trades first (our resting
        orders fill as maker). Returns the quantity that traded."""
        if not isinstance(side, Side):
            raise TypeError("side must be a Side")
        bid = self.price_grid.check(price, name="liquidity price")
        qty = self.quantity_grid.check(quantity, name="liquidity quantity")
        self._tick()
        left = self._match(ticker, side, bid, qty, taker=None)
        if left > 0:
            self._rest(ticker, side, bid, left, None)
        return qty - left

    def book(self, ticker: str) -> dict[str, list[tuple[Decimal, Decimal]]]:
        """Each ladder as (bid, total quantity) levels, best first."""
        out = {}
        for side in Side:
            levels: dict[Decimal, Decimal] = {}
            for e in self._ladder(ticker, side):
                levels[e.price] = levels.get(e.price, ZERO) + e.quantity
            out[side.value] = sorted(levels.items(), key=lambda kv: -kv[0])
        return out

    def _ladder(self, ticker: str, side: Side) -> list[_Entry]:
        ladder = self._book.setdefault((ticker, side), [])
        ladder.sort(key=lambda e: (-e.price, e.seq))
        return ladder

    def _rest(self, ticker: str, side: Side, bid: Decimal, quantity: Decimal, order_id: str | None) -> None:
        self._book.setdefault((ticker, side), []).append(_Entry(self._seq, bid, quantity, order_id))

    def _unrest(self, order: _Order) -> None:
        side, _ = _book_position(order.side, order.action, order.price)
        ladder = self._book.get((order.ticker, side), [])
        self._book[(order.ticker, side)] = [e for e in ladder if e.order_id != order.order_id]

    def _crossing(self, ticker: str, side: Side, bid: Decimal) -> list[_Entry]:
        return [e for e in self._ladder(ticker, _other(side)) if e.price + bid >= ONE]

    def _match(self, ticker: str, side: Side, bid: Decimal, quantity: Decimal, taker: _Order | None) -> Decimal:
        """Trade `quantity` of a `side` bid at `bid` against the opposite ladder; return what is left."""
        left = quantity
        for entry in list(self._crossing(ticker, side, bid)):
            if left <= 0:
                break
            traded = min(left, entry.quantity)
            entry.quantity -= traded
            left -= traded
            if entry.order_id is not None:
                maker = self._orders[entry.order_id]
                self._record_fill(maker, traded, _order_price(maker.action, entry.price), lc.Liquidity.MAKER)
            if taker is not None:
                self._record_fill(taker, traded, _order_price(taker.action, ONE - entry.price), lc.Liquidity.TAKER)
        ladder = self._book.get((ticker, _other(side)), [])
        self._book[(ticker, _other(side))] = [e for e in ladder if e.quantity > 0]
        return left

    def _record_fill(self, order: _Order, quantity: Decimal, price: Decimal, liquidity: lc.Liquidity) -> None:
        fee = None
        if self._fee is not None:
            fee = exact_decimal(self._fee(price, quantity, liquidity), name="fee from hook")
        else:
            self.fees_unknown = True
        order.fill_count += quantity
        order.remaining_count -= quantity
        at = self._tick()
        order.last_update_time = at
        if order.remaining_count == 0 and order.status == "resting":
            order.status = "executed"
        key = (order.ticker, order.side)
        principal = price * quantity
        if order.action is Action.BUY:
            self.cash -= principal + (fee or ZERO)
            self.positions[key] = self.positions.get(key, ZERO) + quantity
        else:
            self.cash += principal - (fee or ZERO)
            self.positions[key] = self.positions.get(key, ZERO) - quantity
        fill = {"fill_id": self._next_fill_id(), "order_id": order.order_id, "client_order_id": order.client_order_id,
                "ticker": order.ticker, "side": order.side.value, "action": order.action.value, "count": quantity,
                "price": price, "is_taker": liquidity is lc.Liquidity.TAKER, "fee": fee, "created_time": at}
        self._fills.append(fill)
        self._emit({"type": "fill", "fill": dict(fill)})

    # ---------------------------------------------------------------- account checks

    def _resting_sells(self, ticker: str, side: Side) -> Decimal:
        return sum((o.remaining_count for o in self._orders.values() if o.status == "resting" and o.ticker == ticker
                    and o.side is side and o.action is Action.SELL), ZERO)

    def _reserved_cash(self) -> Decimal:
        return sum((o.remaining_count * o.price for o in self._orders.values()
                    if o.status == "resting" and o.action is Action.BUY), ZERO)

    def _account_problem(self, ticker: str, side: Side, action: Action, price: Decimal, quantity: Decimal,
                         reduce_only: bool, *, exclude: _Order | None = None) -> str | None:
        if action is Action.BUY:
            if reduce_only:
                return "REDUCE_ONLY_BUY_UNSUPPORTED"
            reserved = self._reserved_cash() - (exclude.remaining_count * exclude.price if exclude else ZERO)
            if self.cash - reserved < price * quantity:
                return "INSUFFICIENT_FUNDS"
            return None
        held = self.positions.get((ticker, side), ZERO)
        available = held - self._resting_sells(ticker, side) + (exclude.remaining_count if exclude else ZERO)
        if quantity > available:
            return "REDUCE_ONLY_WOULD_INCREASE" if reduce_only else "INSUFFICIENT_POSITION"
        return None

    def _self_cross(self, ticker: str, side: Side, bid: Decimal, *, exclude: str | None = None) -> bool:
        return any(e.order_id is not None and e.order_id != exclude for e in self._crossing(ticker, side, bid))

    # ---------------------------------------------------------------- operations

    def new_order(self, *, ticker: str, side: Side, action: Action, count: object, price: object,
                  time_in_force: TimeInForce, client_order_id: str, post_only: bool = False,
                  reduce_only: bool = False) -> Reply:
        """Place one limit order (in the fake). `price` is per contract of `side`."""
        if not isinstance(side, Side) or not isinstance(action, Action) or not isinstance(time_in_force, TimeInForce):
            raise TypeError("side, action and time_in_force must be model enums")
        if not isinstance(client_order_id, str) or not client_order_id or not isinstance(ticker, str) or not ticker:
            raise ValueError("ticker and client_order_id are required")
        try:
            limit = self.price_grid.check(price, name="price")
            qty = self.quantity_grid.check(count, name="count")
        except ExactValueError as exc:
            return Reply("error", error=f"INVALID_ORDER: {exc}")
        if not ZERO < limit < ONE:
            return Reply("error", error=f"INVALID_ORDER: price {limit} is not strictly between 0 and 1")
        op = lc.Operation.NEW_ORDER
        if self._take(Fault.LOSE_REQUEST, op):
            return Reply("timeout")
        injected = self._take(Fault.REJECT, op)
        if injected:
            return Reply("error", error=injected.reason)
        if client_order_id in self._client_ids:
            return Reply("error", error="DUPLICATE_CLIENT_ORDER_ID")
        if post_only and time_in_force is not TimeInForce.GOOD_TILL_CANCELED:
            return Reply("error", error="POST_ONLY_REQUIRES_GTC")
        problem = self._account_problem(ticker, side, action, limit, qty, reduce_only)
        if problem:
            return Reply("error", error=problem)
        book_side, bid = _book_position(side, action, limit)
        if self._self_cross(ticker, book_side, bid):
            return Reply("error", error="SELF_CROSS")
        crossing = self._crossing(ticker, book_side, bid)
        if post_only and crossing:
            return Reply("error", error="POST_ONLY_CROSS")
        at = self._tick()
        order = _Order(self._next_order_id(), client_order_id, ticker, side, action, limit, time_in_force, post_only,
                       reduce_only, qty, qty, ZERO, qty, "resting", at, at)
        self._orders[order.order_id] = order
        self._client_ids.add(client_order_id)
        if time_in_force is TimeInForce.FILL_OR_KILL and sum((e.quantity for e in crossing), ZERO) < qty:
            order.status, order.remaining_count, order.end_reason = "canceled", ZERO, "fok_not_fillable"
        else:
            left = self._match(ticker, book_side, bid, qty, taker=order)
            if left > 0 and time_in_force is TimeInForce.GOOD_TILL_CANCELED:
                self._rest(ticker, book_side, bid, left, order.order_id)
            elif left > 0:
                order.status, order.remaining_count, order.end_reason = "canceled", ZERO, "ioc_remainder"
        dropped = self._take(Fault.DROP_ACK, op, order_id=order.order_id) is not None
        self._emit_order(order, reason=order.end_reason, drop=dropped)
        if dropped:
            return Reply("lost")
        if self._take(Fault.ACCEPT_THEN_TIMEOUT, op, order_id=order.order_id):
            return Reply("timeout")
        return Reply("ok", {"order": self._snapshot(order)})

    def cancel(self, order_id: str) -> Reply:
        op = lc.Operation.CANCEL
        if self._take(Fault.LOSE_REQUEST, op, order_id=order_id):
            return Reply("timeout")
        if self._active(Fault.PAUSE):
            self._take(Fault.PAUSE, order_id=order_id)
            return Reply("error", error="TRADING_PAUSED")
        injected = self._take(Fault.REJECT, op, order_id=order_id)
        if injected:
            return Reply("error", error=injected.reason)
        order = self._orders.get(order_id)
        if order is None:
            return Reply("error", error="NOT_FOUND")
        if order.status != "resting":
            return Reply("error", error="NOT_CANCELABLE")
        reduced_by = order.remaining_count
        self._unrest(order)
        order.status, order.remaining_count, order.end_reason = "canceled", ZERO, "canceled"
        order.last_update_time = self._tick()
        self._emit_order(order, reason="canceled")
        if self._take(Fault.ACCEPT_THEN_TIMEOUT, op, order_id=order_id):
            return Reply("timeout")
        return Reply("ok", {"order": self._snapshot(order), "reduced_by": reduced_by})

    def amend(self, order_id: str, *, total_count: object = None, price: object = None) -> Reply:
        """Change a resting order's TOTAL count (filled contracts included) and/or its price."""
        op = lc.Operation.AMEND
        if self._take(Fault.LOSE_REQUEST, op, order_id=order_id):
            return Reply("timeout")
        injected = self._take(Fault.REJECT, op, order_id=order_id)
        if injected:
            return Reply("error", error=injected.reason)
        order = self._orders.get(order_id)
        if order is None:
            return Reply("error", error="NOT_FOUND")
        if order.status != "resting":
            return Reply("error", error="NOT_AMENDABLE")
        try:
            total = order.total_count if total_count is None else self.quantity_grid.check(total_count, name="count")
            limit = order.price if price is None else self.price_grid.check(price, name="price")
        except ExactValueError as exc:
            return Reply("error", error=f"INVALID_AMEND: {exc}")
        if not ZERO < limit < ONE:
            return Reply("error", error=f"INVALID_AMEND: price {limit} is not strictly between 0 and 1")
        if total <= order.fill_count:
            return Reply("error", error="AMEND_BELOW_FILLED")
        new_remaining = total - order.fill_count
        problem = self._account_problem(order.ticker, order.side, order.action, limit, new_remaining,
                                        order.reduce_only, exclude=order)
        if problem:
            return Reply("error", error=problem)
        book_side, bid = _book_position(order.side, order.action, limit)
        if self._self_cross(order.ticker, book_side, bid, exclude=order.order_id):
            return Reply("error", error="SELF_CROSS")
        if order.post_only and self._crossing(order.ticker, book_side, bid):
            return Reply("error", error="POST_ONLY_CROSS")
        before = self._snapshot(order)
        self._unrest(order)
        at = self._tick()
        if self.amend_assigns_new_order_id:
            old_id = order.order_id
            del self._orders[old_id]
            order.order_id = self._next_order_id()
            self._orders[order.order_id] = order
            self._replaced[old_id] = order.order_id
        order.total_count, order.price, order.remaining_count, order.last_update_time = total, limit, new_remaining, at
        left = self._match(order.ticker, book_side, bid, new_remaining, taker=order)
        if left > 0:
            self._rest(order.ticker, book_side, bid, left, order.order_id)
        self._emit_order(order, reason="amended")
        if self._take(Fault.ACCEPT_THEN_TIMEOUT, op, order_id=order.order_id):
            return Reply("timeout")
        return Reply("ok", {"old_order": before, "order": self._snapshot(order)})

    def expire(self, order_id: str) -> bool:
        """End a resting order at its expiry (a test hook). False if it was not resting."""
        order = self._orders.get(order_id)
        if order is None or order.status != "resting":
            return False
        self._unrest(order)
        order.status, order.remaining_count, order.end_reason = "canceled", ZERO, "expired"
        order.last_update_time = self._tick()
        self._emit_order(order, reason="expired")
        return True

    # ---------------------------------------------------------------- read-back

    def _snapshot(self, order: _Order) -> dict[str, Any]:
        return {"order_id": order.order_id, "client_order_id": order.client_order_id, "ticker": order.ticker,
                "side": order.side.value, "action": order.action.value, "type": "limit", "price": order.price,
                "time_in_force": order.time_in_force.value, "post_only": order.post_only,
                "reduce_only": order.reduce_only, "status": order.status, "initial_count": order.initial_count,
                "total_count": order.total_count, "fill_count": order.fill_count,
                "remaining_count": order.remaining_count, "created_time": order.created_time,
                "last_update_time": order.last_update_time}

    def get_order(self, order_id: str) -> dict | None:
        order = self._orders.get(order_id)
        return None if order is None else self._snapshot(order)

    def orders_by_client_id(self, client_order_id: str) -> dict:
        """Every order with this client order id, terminal ones included. The fake sees everything, so
        the answer is complete for the account."""
        found = [self._snapshot(o) for o in self._orders.values() if o.client_order_id == client_order_id]
        return {"orders": found, "complete": True, "as_of": self.now_text()}

    def list_orders(self, ticker: str | None = None) -> list[dict]:
        return [self._snapshot(o) for o in self._orders.values() if ticker is None or o.ticker == ticker]

    def list_fills(self, order_id: str | None = None) -> list[dict]:
        return [dict(f) for f in self._fills if order_id is None or f["order_id"] == order_id]

    def replaced_by(self, order_id: str) -> str | None:
        return self._replaced.get(order_id)

    def account(self) -> dict:
        return {"cash": self.cash, "reserved": self._reserved_cash(), "fees_unknown": self.fees_unknown,
                "positions": {f"{t}:{s.value}": q for (t, s), q in sorted(self.positions.items(),
                                                                           key=lambda kv: (kv[0][0], kv[0][1].value))}}


def _other(side: Side) -> Side:
    return Side.NO if side is Side.YES else Side.YES


def _book_position(side: Side, action: Action, price: Decimal) -> tuple[Side, Decimal]:
    """The ladder and bid an order joins: a BUY bids its own side at its price; a SELL of one side is
    a bid for the other side at 1 - price."""
    return (side, price) if action is Action.BUY else (_other(side), ONE - price)


def _order_price(action: Action, bid: Decimal) -> Decimal:
    """An order's own-side price from the bid it trades at on its ladder."""
    return bid if action is Action.BUY else ONE - bid


# ---------------------------------------------------------------- fake receipts -> lifecycle events
#
# Translators for the FAKE's shapes only. The real wire translation belongs to the wire lane and the
# conformance pack; nothing here asserts what Kalshi actually sends.


def ack_from_snapshot(order: dict) -> lc.Acknowledged:
    return lc.Acknowledged(provider_order_id=order.get("order_id"), client_order_id=order.get("client_order_id"),
                           status=order.get("status"), filled_quantity=order.get("fill_count"),
                           remaining_quantity=order.get("remaining_count"), total_quantity=order.get("total_count"),
                           venue_time_utc=order.get("last_update_time"))


def fill_from_message(fill: dict) -> lc.Fill:
    taker = fill.get("is_taker")
    return lc.Fill(fill_id=fill["fill_id"], quantity=fill["count"], price=fill["price"], fee=fill.get("fee"),
                   liquidity=None if taker is None else (lc.Liquidity.TAKER if taker else lc.Liquidity.MAKER),
                   venue_time_utc=fill.get("created_time"), provider_order_id=fill.get("order_id"),
                   client_order_id=fill.get("client_order_id"), side=Side(fill["side"]), action=Action(fill["action"]))


def events_from_feed(message: dict) -> lc.Event:
    if message["type"] == "fill":
        return fill_from_message(message["fill"])
    order = message["order"]
    if message.get("reason") == "expired":
        return lc.Expired(provider_order_id=order["order_id"], client_order_id=order["client_order_id"],
                          filled_quantity=order["fill_count"], venue_time_utc=order["last_update_time"])
    return ack_from_snapshot(order)


def events_from_reply(operation: lc.Operation, reply: Reply) -> tuple[lc.Event, ...]:
    if reply.ambiguous:
        return (lc.SendReturnedAmbiguous(operation, reply.outcome),)
    if reply.outcome == "error":
        return (lc.Rejected(operation, reply.error or "UNSPECIFIED"),)
    body = reply.body or {}
    order = body.get("order") or {}
    if operation is lc.Operation.NEW_ORDER:
        return (ack_from_snapshot(order),)
    if operation is lc.Operation.CANCEL:
        return (lc.CancelConfirmed(provider_order_id=order.get("order_id"),
                                   client_order_id=order.get("client_order_id"),
                                   reduced_by=body.get("reduced_by"), filled_quantity=order.get("fill_count"),
                                   remaining_quantity=order.get("remaining_count"),
                                   venue_time_utc=order.get("last_update_time")),)
    old = body.get("old_order") or {}
    new_id = order.get("order_id")
    return (lc.AmendAcknowledged(provider_order_id=old.get("order_id"), new_total=order["total_count"],
                                 new_price=order["price"], client_order_id=order.get("client_order_id"),
                                 new_provider_order_id=new_id if new_id != old.get("order_id") else None,
                                 filled_quantity=order.get("fill_count"),
                                 remaining_quantity=order.get("remaining_count"),
                                 venue_time_utc=order.get("last_update_time")),)


def reconcile_event(venue: FakeVenue, client_order_id: str) -> lc.ReconcileObserved:
    """An authoritative, complete query of the fake by client order id."""
    answer = venue.orders_by_client_id(client_order_id)
    if not answer["orders"]:
        return lc.ReconcileObserved(client_order_id=client_order_id, provider_order_id=None, found=False,
                                    authoritative_complete=answer["complete"], as_of_utc=answer["as_of"])
    order = answer["orders"][-1]
    return lc.ReconcileObserved(client_order_id=client_order_id, provider_order_id=order["order_id"], found=True,
                                status=order["status"], filled_quantity=order["fill_count"],
                                remaining_quantity=order["remaining_count"], total_quantity=order["total_count"],
                                price=order["price"], authoritative_complete=answer["complete"],
                                as_of_utc=answer["as_of"])
