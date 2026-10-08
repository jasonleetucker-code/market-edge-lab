"""Two-sided book snapshots for follower replay (W5). Reuses `opportunity.DepthLevel`.

A `Book` is what a fixture or a future approved capture says was resting at `captured_at`. There is
no midpoint and no last price: replay can only take what the book shows. A truncated side means more
depth may exist past the last captured level, which is unknown, not available.

A crossed or locked book cannot be constructed (`ValueError`): a provider that captured one has no
valid book to offer, and a judgement that needed it is INSUFFICIENT_EVIDENCE, never cleared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from ..opportunity import DepthLevel
from .exact import ZERO, add, div_floor, exact_decimal, floor_to_step, mul, sub
from .timeutil import require_aware


@dataclass(frozen=True)
class Book:
    instrument_id: str
    bids: tuple[DepthLevel, ...]  # best (highest) first
    asks: tuple[DepthLevel, ...]  # best (lowest) first
    captured_at: datetime
    bids_truncated: bool = False
    asks_truncated: bool = False
    # Amendment 2026-10-08 B: optional provenance. None is unknown. `captured_at` is on the book
    # source's clock; `received_at` is when our side received it (a different clock), so a receipt
    # before the capture is a clock problem the quality diagnostics report rather than resolve.
    source: str | None = None
    raw_ref: str | None = None
    received_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.captured_at, "captured_at")
        if self.received_at is not None:
            require_aware(self.received_at, "received_at")
        for side, levels, ascending in (("ask", self.asks, True), ("bid", self.bids, False)):
            previous = None
            for level in levels:
                price = exact_decimal(level.price, name=f"{side} price")
                size = exact_decimal(level.size, name=f"{side} size")
                if not (ZERO < price < Decimal(1)):
                    raise ValueError(f"{side} price {price} is outside (0, 1)")
                if size <= 0:
                    raise ValueError(f"{side} size must be positive")
                if previous is not None and ((price <= previous) if ascending else (price >= previous)):
                    raise ValueError(f"{side}s are not strictly ordered best first")
                previous = price
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError("crossed or locked book")

    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    def bid_depth_at_or_above(self, price: Decimal) -> Decimal:
        return add(*(lv.size for lv in self.bids if lv.price >= price))


BookProvider = Callable[[str, datetime], "Book | None"]


@dataclass(frozen=True)
class Take:
    levels: tuple[DepthLevel, ...]
    quantity: Decimal
    cash: Decimal  # sum of price x size, exact, before fees
    depth_exhausted: bool  # the captured side ran out before the request was met
    beyond_capture_unknown: bool  # ...and the side was truncated, so more may have existed


def take(levels: tuple[DepthLevel, ...], *, quantity: Decimal, limit: Decimal | None, buying: bool,
         max_cash: Decimal | None, step: Decimal, truncated: bool) -> Take:
    """Take up to `quantity` from captured levels within `limit` and `max_cash`, in whole `step`s.
    Only captured levels are used; nothing past the last level is ever assumed."""
    remaining, cash, taken = quantity, ZERO, []
    exhausted = True
    for lv in levels:
        if remaining <= 0:
            exhausted = False
            break
        if limit is not None and ((lv.price > limit) if buying else (lv.price < limit)):
            exhausted = False
            break
        size = min(remaining, lv.size)
        if max_cash is not None:
            affordable = _floor(sub(max_cash, cash), lv.price, step)
            size = min(size, affordable)
        size = _floor_qty(size, step)
        if size <= 0:
            exhausted = False
            break
        taken.append(DepthLevel(lv.price, size))
        cash = add(cash, mul(lv.price, size))
        remaining = sub(remaining, size)
    if remaining <= 0:
        exhausted = False
    filled = sub(quantity, remaining)
    return Take(tuple(taken), filled, cash, exhausted, exhausted and truncated)


def _floor_qty(q: Decimal, step: Decimal) -> Decimal:
    return floor_to_step(q, step) if q > 0 else ZERO


def _floor(cash: Decimal, price: Decimal, step: Decimal) -> Decimal:
    return div_floor(cash, price, step) if cash > 0 else ZERO
