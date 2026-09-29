"""Deterministic hold-versus-exit replay v1 (#122 §16-§18, §20). Research only, in memory.

For one frozen cohort of identical entries, three arms are replayed:

1. **HOLD**: hold to settlement;
2. **FULL_EXIT**: sell everything once the fixed target is reachable;
3. **PARTIAL_EXIT**: sell a predefined fraction of the initial quantity at the target and hold
   the remainder.

Every arm uses the same entries, timestamps, quantities, capital and evidence. Decisions come
from the canonical `position_policy.evaluate`; this module adds timing, fills and accounting.

**Two execution semantics, never mixed** (`Semantics`):

- **BOT_TRIGGERED**: the policy sees a book at its receipt time (detection), decides after
  `decision_latency`, and its marketable limit arrives `arrival_latency` later. It can fill only
  against the first usable book received at or after arrival, and only if that book arrived
  within `max_arrival_gap`. It never fills against the book it decided on. Unknown arrival
  latency means no fill (ARRIVAL_UNKNOWN), not a fill at detection.
- **PREPLACED_LIMIT**: a resting sale at the target is placed at entry (plus
  `arrival_latency`) and reserves its inventory. A displayed bid equal to the limit is a
  *touch*, not a fill: queue position is unknown. Under STRICT_THROUGH (the default) the order
  fills only when a usable book shows bids strictly above the limit, at the limit price, and
  only up to the largest such crossing size seen so far (visible liquidity is never summed
  across snapshots). TOUCH_UPPER_BOUND counts touches too and is a labelled diagnostic. The
  preplaced arm never uses later information: its limit is fixed when placed.

**No interpolation.** Books that are not usable (no valid start, gap, invalid, paused, closed)
are skipped. Nothing fills between two snapshots, so a price that jumped through the target
while no usable book was received is not a fill at the target.

**Diagnostics are not results.** FIRST_DETECTION_ZERO_LATENCY (fill at the first detecting book,
zero delay) and HINDSIGHT_UPPER_BOUND (the best single sale over the whole game, chosen after
seeing it) are reported apart from the arms and never enter a comparison (ADR 0037 labels).

**Accounting** (`ReplayLedger`) is isolated and in memory; nothing is written anywhere. It
enforces: no overselling, no double reservation, each fill once (by fill id), each fee once,
the residual settled exactly once, no payout for sold contracts, a cancel request that releases
nothing, and a full cash-flow reconciliation. Proceeds are not profit. Released cash stays idle
to the common horizon. A missing settlement value or finality makes the entry INCOMPLETE: its
terminal wealth is None, never 0. An unknown fee blocks every after-cost figure; gross figures
remain as labelled diagnostics.

Real in-play data needs an allocated experiment id and an evidence-use record, so a RECORDED
cohort is refused in v1. Synthetic cohorts are labelled synthetic.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from functools import cached_property
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any, Mapping, Sequence

from .fee_schedules import ClaimBasis, valid_price
from .freshness import parse_utc
from .inplay_evidence import BookStatus, DataKind, TradingState, depth_at_or_above, walk_bids
from .opportunity import DepthStatus
from .position_policy import (
    Action, DecisionStatus, ExecutionAssumption, FeeModel, Inventory, InventoryKind, PolicyKind, PositionPolicy,
    SaleBook, evaluate,
)

REPLAY_VERSION = "inplay-replay-v1"
TICK = Decimal("0.01")


class Arm(str, Enum):
    HOLD = "HOLD"
    FULL_EXIT = "FULL_EXIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"


class Semantics(str, Enum):
    BOT_TRIGGERED = "BOT_TRIGGERED"
    PREPLACED_LIMIT = "PREPLACED_LIMIT"


class FillRule(str, Enum):
    STRICT_THROUGH = "STRICT_THROUGH"  # bids strictly above a resting limit prove it would have traded
    TOUCH_UPPER_BOUND = "TOUCH_UPPER_BOUND"  # diagnostic: touches fill too (queue ignored)


class EntryStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"  # settlement value or finality missing: never valued at 0


DIAGNOSTIC_LABELS = ("FIRST_DETECTION_ZERO_LATENCY", "HINDSIGHT_UPPER_BOUND")


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class TimedBook:
    """One usable-or-not observation of the YES bids of a market, at its receipt time."""

    receipt_utc: str
    bids: tuple[tuple[Decimal, Decimal], ...]  # ascending (price, contracts)
    status: BookStatus = BookStatus.VALID
    trading_state: TradingState = TradingState.OPEN
    truncated: bool = False
    evidence_id: str | None = None


@dataclass(frozen=True)
class Settlement:
    """Payout per YES contract (1, 0, 0.5 on a tie, or another documented value) and whether it
    is final. None or not final: the entry is INCOMPLETE."""

    value: Decimal | None
    final: bool
    at_utc: str | None


@dataclass(frozen=True)
class CohortEntry:
    game_id: str
    cluster_id: str  # e.g. the NFL week: games of one slate are not independent
    market_id: str
    quantity: Decimal  # YES contracts bought at entry (whole contracts in v1)
    entry_price: Decimal
    entry_cost: Decimal | None  # cash out including the entry fee; None = unknown fee
    entry_at_utc: str
    books: tuple[TimedBook, ...]
    settlement: Settlement
    side: str = "YES"


@dataclass(frozen=True)
class Cohort:
    cohort_id: str
    data_kind: DataKind
    label: str  # what this cohort is, e.g. "SYNTHETIC calibrated-martingale null"
    entries: tuple[CohortEntry, ...]
    starting_capital: Decimal
    horizon_utc: str  # the common evaluation horizon: every arm is valued here
    rules_version: str

    def __post_init__(self) -> None:
        if self.data_kind is DataKind.RECORDED:
            raise ValueError("a recorded in-play cohort needs an allocated experiment id and an evidence-use "
                             "record; v1 replays only SYNTHETIC or FIXTURE cohorts")
        if not self.label.upper().startswith(self.data_kind.value):
            raise ValueError(f"the label must start with {self.data_kind.value} so it is never shown as live")
        horizon = parse_utc(self.horizon_utc)
        if horizon is None:
            raise ValueError("horizon_utc must be timezone-aware")
        for e in self.entries:
            if e.settlement.at_utc is not None and parse_utc(e.settlement.at_utc) > horizon:
                raise ValueError(f"{e.game_id} settles after the common horizon")
            if e.side != "YES":
                raise ValueError("v1 replays YES positions only")
            if not valid_price(e.entry_price) or e.quantity <= 0 or e.quantity != e.quantity.to_integral_value():
                raise ValueError(f"{e.game_id}: invalid entry price or quantity")

    @cached_property
    def sha256(self) -> str:
        """Content hash of the cohort: every arm is replayed over exactly this."""
        h = hashlib.sha256(json.dumps([self.cohort_id, self.data_kind.value, self.label, str(self.starting_capital),
                                       self.horizon_utc, self.rules_version]).encode())
        for e in self.entries:
            h.update(json.dumps([e.game_id, e.cluster_id, e.market_id, str(e.quantity), str(e.entry_price),
                                 str(e.entry_cost), e.entry_at_utc, e.side, str(e.settlement.value),
                                 e.settlement.final, e.settlement.at_utc]).encode())
            for b in e.books:
                h.update(f"{b.receipt_utc}|{b.status.value}|{b.trading_state.value}|{b.truncated}|{b.evidence_id}|"
                         f"{';'.join(f'{p}:{q}' for p, q in b.bids)}\n".encode())
        return h.hexdigest()


@dataclass(frozen=True)
class ReplayConfig:
    target_price: Decimal
    partial_fraction: Decimal
    fee_model: FeeModel
    decision_latency: timedelta = timedelta(seconds=1)
    arrival_latency: timedelta | None = timedelta(seconds=1)  # None: unknown, so nothing can fill
    max_arrival_gap: timedelta = timedelta(seconds=10)
    max_book_age: timedelta = timedelta(seconds=15)
    fill_rule: FillRule = FillRule.STRICT_THROUGH
    spread_haircut_ticks: int = 0  # sensitivity: every bid lowered by this many cents
    max_attempts: int = 3  # bot IOC attempts per entry
    settlement_fee_per_contract: Decimal | None = Decimal(0)  # None: unknown (blocks after-cost)
    cancel_on_pause: bool = False
    policy_version: str = "1"
    # A zero decision-plus-arrival latency is the FIRST_DETECTION_ZERO_LATENCY assumption: allowed only
    # when this names it, and such a report is a labelled diagnostic, never a policy result.
    diagnostic_mode: str | None = None

    @property
    def zero_latency(self) -> bool:
        return self.arrival_latency is not None and self.decision_latency + self.arrival_latency == timedelta(0)

    def problems(self) -> list[str]:
        out = []
        if self.diagnostic_mode not in (None, "FIRST_DETECTION_ZERO_LATENCY"):
            out.append(f"unknown diagnostic mode {self.diagnostic_mode!r}")
        if self.zero_latency and self.diagnostic_mode != "FIRST_DETECTION_ZERO_LATENCY":
            out.append("zero decision plus arrival latency is the FIRST_DETECTION_ZERO_LATENCY assumption: set "
                       "diagnostic_mode='FIRST_DETECTION_ZERO_LATENCY' to run it as a labelled diagnostic")
        if self.decision_latency < timedelta(0) or (self.arrival_latency is not None
                                                    and self.arrival_latency < timedelta(0)):
            out.append("latencies cannot be negative")
        return out

    def variant_id(self) -> str:
        key = {k: str(v) for k, v in self.__dict__.items() if k != "fee_model"}
        key["fee_model"] = self.fee_model.model_id
        return "cfg-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- isolated ledger


class LedgerError(ValueError):
    """An accounting invariant would break. The replay stops rather than record it."""


def _floor(value: Decimal, precision: Decimal) -> Decimal:
    return (value / precision).to_integral_value(rounding=ROUND_FLOOR) * precision


class ReplayLedger:
    """One entry's isolated research ledger. In memory only; it never touches a stored ledger."""

    def __init__(self, *, balance_precision: Decimal = Decimal("0.01")):
        self.precision = balance_precision
        self.initial_quantity = Decimal(0)
        self.inventory = Decimal(0)
        self.entry_gross = Decimal(0)
        self.entry_cost: Decimal | None = Decimal(0)
        self.reservations: dict[str, Decimal] = {}
        self.cancel_requested: set[str] = set()
        self.fill_ids: set[str] = set()
        self.duplicate_fills = 0
        self.sold = Decimal(0)
        self.gross_proceeds = Decimal(0)
        self.fees: list[Decimal | None] = []
        self.fill_log: list[tuple[Decimal, Decimal, Decimal | None]] = []  # (quantity, price, fee)
        self.net_proceeds: Decimal | None = Decimal(0)
        self.settled_quantity: Decimal | None = None
        self.settlement_cash: Decimal | None = None
        self.settlement_fee: Decimal | None = Decimal(0)
        self.acquired = False
        self.events: list[str] = []

    @property
    def reserved(self) -> Decimal:
        return sum(self.reservations.values(), Decimal(0))

    def acquire(self, quantity: Decimal, price: Decimal, cost: Decimal | None) -> None:
        if self.acquired:
            raise LedgerError("ACQUIRE_TWICE: re-entry is a new transaction, not a second acquire")
        self.acquired = True
        self.initial_quantity = self.inventory = quantity
        self.entry_gross = quantity * price
        self.entry_cost = cost
        self.events.append(f"ACQUIRE {quantity} @ {price} cost {cost}")

    def reserve(self, order_id: str, quantity: Decimal) -> None:
        if order_id in self.reservations:
            raise LedgerError(f"DOUBLE_RESERVATION: {order_id}")
        if quantity <= 0 or quantity > self.inventory - self.reserved:
            raise LedgerError(f"OVERSELL_RESERVATION: {quantity} > {self.inventory - self.reserved} unreserved")
        self.reservations[order_id] = quantity
        self.events.append(f"RESERVE {order_id} {quantity}")

    def request_cancel(self, order_id: str) -> None:
        if order_id not in self.reservations:
            raise LedgerError(f"CANCEL_UNKNOWN_ORDER: {order_id}")
        self.cancel_requested.add(order_id)  # releases nothing: a late fill is still possible
        self.events.append(f"CANCEL_REQUESTED {order_id}")

    def confirm_cancel(self, order_id: str, why: str = "CANCEL_CONFIRMED") -> Decimal:
        if order_id not in self.reservations:
            raise LedgerError(f"RELEASE_TWICE_OR_UNKNOWN: {order_id}")
        released = self.reservations.pop(order_id)
        self.cancel_requested.discard(order_id)
        self.events.append(f"{why} {order_id} released {released}")
        return released

    def fill(self, *, fill_id: str, quantity: Decimal, price: Decimal, fee: Decimal | None,
             order_id: str | None = None) -> bool:
        """Apply a sale fill once. A repeated fill id is ignored (and counted); returns False."""
        if fill_id in self.fill_ids:
            self.duplicate_fills += 1
            return False
        if quantity <= 0 or not valid_price(price):
            raise LedgerError(f"BAD_FILL: {quantity} @ {price}")
        if order_id is not None:
            left = self.reservations.get(order_id)
            if left is None or quantity > left:
                raise LedgerError(f"FILL_EXCEEDS_ORDER: {order_id} has {left} left, fill {quantity}")
            self.reservations[order_id] = left - quantity
            if self.reservations[order_id] == 0:
                del self.reservations[order_id]
                self.cancel_requested.discard(order_id)
        elif quantity > self.inventory - self.reserved:
            raise LedgerError(f"OVERSELL: {quantity} > {self.inventory - self.reserved} unreserved")
        if self.settled_quantity is not None:
            raise LedgerError("FILL_AFTER_SETTLEMENT")
        self.fill_ids.add(fill_id)
        self.inventory -= quantity
        self.sold += quantity
        gross = quantity * price
        self.gross_proceeds += gross
        self.fees.append(fee)
        self.fill_log.append((quantity, price, fee))
        if fee is None or self.net_proceeds is None:
            self.net_proceeds = None
        else:
            self.net_proceeds += _floor(gross - fee, self.precision)
        self.events.append(f"FILL {fill_id} {quantity} @ {price} fee {fee}")
        return True

    def settle(self, value: Decimal, *, fee_per_contract: Decimal | None) -> None:
        if self.settled_quantity is not None:
            raise LedgerError("SETTLE_TWICE")
        for order_id in list(self.reservations):
            self.confirm_cancel(order_id, "EXPIRED_AT_CLOSE")
        self.settled_quantity = self.inventory  # the residual only: sold contracts get no payout
        self.settlement_cash = self.inventory * value
        self.settlement_fee = None if fee_per_contract is None else fee_per_contract * self.inventory
        self.inventory = Decimal(0)
        self.events.append(f"SETTLE residual {self.settled_quantity} @ {value}")

    # ---- results

    def pnl_gross(self) -> Decimal | None:
        """Cash change over the horizon, before fees. Proceeds are not profit."""
        if self.settlement_cash is None:
            return None
        return self.gross_proceeds + self.settlement_cash - self.entry_gross

    def pnl_net(self) -> Decimal | None:
        """Cash change after every cost; None when any cost or the settlement is unknown."""
        if (self.settlement_cash is None or self.entry_cost is None or self.net_proceeds is None
                or self.settlement_fee is None):
            return None
        return self.net_proceeds + self.settlement_cash - self.settlement_fee - self.entry_cost

    def reconcile(self) -> list[str]:
        """Every broken identity; empty when the books balance."""
        out = []
        if self.initial_quantity != self.sold + self.inventory + (self.settled_quantity or Decimal(0)):
            out.append("QUANTITY: initial != sold + residual")
        if self.reserved > self.inventory:
            out.append("RESERVED_EXCEEDS_INVENTORY")
        if self.net_proceeds is not None and None not in self.fees:
            recomputed = sum((_floor(q * p - f, self.precision) for q, p, f in self.fill_log), Decimal(0))
            if recomputed != self.net_proceeds:
                out.append("NET_PROCEEDS_DO_NOT_RECONCILE")
        if sum(1 for e in self.events if e.startswith("SETTLE ")) > 1:
            out.append("SETTLED_MORE_THAN_ONCE")
        if sum(q for q, _, _ in self.fill_log) != self.sold or sum(q * p for q, p, _ in self.fill_log) != self.gross_proceeds:
            out.append("FILLS_DO_NOT_RECONCILE")
        return out


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class EntryResult:
    game_id: str
    cluster_id: str
    arm: Arm
    semantics: Semantics | None  # None for HOLD
    status: EntryStatus
    sold: Decimal
    residual: Decimal | None
    gross_proceeds: Decimal
    fees: Decimal | None  # None: at least one fee unknown
    net_proceeds: Decimal | None
    settlement_cash: Decimal | None
    pnl_gross: Decimal | None  # cash change over the common horizon; None when INCOMPLETE
    pnl_net: Decimal | None  # None when INCOMPLETE or any cost is unknown
    attempts: int
    touches_not_filled: int
    placed: bool | None  # PREPLACED_LIMIT: was the resting sale placed? None for other arms
    duplicate_receipts: int  # books sharing a receipt time with another book of this entry
    notes: tuple[str, ...]
    reconciliation: tuple[str, ...]


@dataclass(frozen=True)
class Diagnostic:
    game_id: str
    arm: Arm
    label: str  # one of DIAGNOSTIC_LABELS
    gross_proceeds: Decimal | None
    quantity: Decimal
    at_utc: str | None
    note: str


@dataclass(frozen=True)
class ArmSummary:
    arm: Arm
    semantics: Semantics | None
    entries: int
    complete: int
    incomplete: int
    pnl_gross: Decimal | None  # summed over entries; None when any entry is INCOMPLETE
    pnl_net: Decimal | None  # None when incomplete or any cost unknown
    terminal_wealth_gross: Decimal | None  # starting capital + pnl_gross, at the common horizon
    terminal_wealth_net: Decimal | None
    complete_only_pnl_gross: Decimal  # labelled subtotal over COMPLETE entries only, never the total
    change_vs_hold_gross: Decimal | None  # expected-profit change, reported apart from risk
    change_vs_hold_net: Decimal | None
    risk: Mapping[str, Any]  # dispersion and worst case of per-entry P&L, separately
    clusters: int
    not_placed: int = 0  # PREPLACED_LIMIT entries whose resting sale was never placed: held, but not HOLD


@dataclass(frozen=True)
class ReplayReport:
    version: str
    cohort_id: str
    cohort_sha256: str
    diagnostic_mode: str | None
    data_kind: str
    label: str
    config_variant: str
    fill_rule: str
    fee_model: str
    fee_claim_basis: str
    after_cost_claim: bool
    after_cost_reason: str
    arms: tuple[ArmSummary, ...]
    entries: tuple[EntryResult, ...]
    diagnostics: tuple[Diagnostic, ...]
    notes: tuple[str, ...]

    def arm(self, arm: Arm, semantics: Semantics | None) -> ArmSummary:
        return next(a for a in self.arms if a.arm is arm and a.semantics is semantics)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    if hasattr(value, "__dataclass_fields__"):
        return {k: _plain(getattr(value, k)) for k in value.__dataclass_fields__ if k != "fee_model"}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


# --------------------------------------------------------------------------- replay


def _haircut(bids: Sequence[tuple[Decimal, Decimal]], ticks: int) -> tuple[tuple[Decimal, Decimal], ...]:
    if ticks <= 0:
        return tuple(bids)
    out = [(p - TICK * ticks, s) for p, s in bids]
    return tuple((p, s) for p, s in out if valid_price(p))


def _usable(book: TimedBook) -> bool:
    return book.status is BookStatus.VALID and book.trading_state is TradingState.OPEN


def _policy(cfg: ReplayConfig, arm: Arm, semantics: Semantics) -> PositionPolicy:
    kind = PolicyKind.FIXED_TARGET_FULL_EXIT if arm is Arm.FULL_EXIT else PolicyKind.FIXED_TARGET_PARTIAL_EXIT
    execution = (ExecutionAssumption.BOT_TRIGGERED_IOC if semantics is Semantics.BOT_TRIGGERED
                 else ExecutionAssumption.PREPLACED_RESTING_LIMIT)
    return PositionPolicy(policy_id=f"inplay-{arm.value.lower()}-{semantics.value.lower()}", version=cfg.policy_version,
                          kind=kind, execution=execution, target_price=cfg.target_price,
                          exit_fraction=cfg.partial_fraction if arm is Arm.PARTIAL_EXIT else None,
                          max_book_age=cfg.max_book_age, max_inventory_age=timedelta(days=365))


def _sale_book(entry: CohortEntry, book: TimedBook, cfg: ReplayConfig, kind: DataKind) -> SaleBook:
    return SaleBook(entry.market_id, entry.side, _haircut(book.bids, cfg.spread_haircut_ticks), book.truncated,
                    book.status, book.trading_state, book.receipt_utc, book.evidence_id, kind)


def _inventory(entry: CohortEntry, ledger: ReplayLedger, as_of: str) -> Inventory:
    return Inventory(entry.market_id, entry.side, ledger.inventory, ledger.initial_quantity, InventoryKind.SIMULATED,
                     as_of, f"replay:{entry.game_id}", entry_cost=ledger.entry_cost)


def _books_until(entry: CohortEntry, start: datetime) -> list[tuple[datetime, TimedBook]]:
    """(receipt time, book) from `start` until settlement, in receipt order. A book without a
    valid receipt time is not evidence of anything and is dropped here."""
    end = parse_utc(entry.settlement.at_utc) if entry.settlement.at_utc else None
    timed = [(parse_utc(b.receipt_utc), b) for b in entry.books]
    return sorted(((at, b) for at, b in timed if at is not None and at >= start and (end is None or at < end)),
                  key=lambda x: x[0])


def _book_key(book: TimedBook, index: int) -> str:
    """A fill's book identity: its evidence id (a seq or snapshot id) plus receipt, or its position in
    receipt order when the book has no evidence id. Two distinct books at one receipt time differ."""
    return f"{book.evidence_id or f'#{index}'}@{book.receipt_utc}"


def _new_ledger(cohort: Cohort, entry: CohortEntry, cfg: ReplayConfig) -> ReplayLedger:
    ledger = ReplayLedger(balance_precision=getattr(cfg.fee_model, "balance_precision", Decimal("0.01")))
    ledger.acquire(entry.quantity, entry.entry_price, entry.entry_cost)
    return ledger


def _run_bot(cohort: Cohort, entry: CohortEntry, cfg: ReplayConfig, arm: Arm, ledger: ReplayLedger,
             notes: list[str]) -> int:
    policy = _policy(cfg, arm, Semantics.BOT_TRIGGERED)
    books = _books_until(entry, parse_utc(entry.entry_at_utc))
    attempts, cursor = 0, 0
    while cursor < len(books) and attempts < cfg.max_attempts:
        seen_at, book = books[cursor]
        cursor += 1
        d = evaluate(as_of=seen_at, inventory=_inventory(entry, ledger, book.receipt_utc),
                     orders=(), book=_sale_book(entry, book, cfg, cohort.data_kind), fee_model=cfg.fee_model,
                     policy=policy, rules_version=cohort.rules_version)
        if d.status is not DecisionStatus.PROPOSED or d.action not in (Action.REDUCE, Action.EXIT):
            continue
        attempts += 1
        if cfg.arrival_latency is None:
            notes.append(f"ARRIVAL_UNKNOWN at {book.receipt_utc}: no fill is assumed")
            break
        arrival = seen_at + cfg.decision_latency + cfg.arrival_latency
        idx = next((i for i in range(cursor - 1, len(books)) if books[i][0] >= arrival), None)
        if idx is None:
            notes.append(f"NO_BOOK_AFTER_ARRIVAL {arrival.isoformat()}")
            break
        received, fill_book = books[idx]
        cursor = idx + 1  # the bot waits for its IOC answer before deciding again
        if received - arrival > cfg.max_arrival_gap:
            notes.append(f"NO_BOOK_AT_ARRIVAL: next book {fill_book.receipt_utc} is {received - arrival} after arrival")
            continue
        if not _usable(fill_book):
            notes.append(f"BOOK_UNUSABLE_AT_ARRIVAL {fill_book.receipt_utc}: {fill_book.status.value}/"
                         f"{fill_book.trading_state.value}")
            continue
        bids = _haircut(fill_book.bids, cfg.spread_haircut_ticks)
        qty = min(d.quantity, depth_at_or_above(bids, cfg.target_price))
        qty = (qty / policy.quantity_step).to_integral_value(rounding=ROUND_FLOOR) * policy.quantity_step
        if qty <= 0:
            notes.append(f"IOC_NO_FILL at {fill_book.receipt_utc}: bids at arrival below target")
            continue
        walk = walk_bids(bids, qty, min_price=cfg.target_price, truncated=fill_book.truncated)
        if walk.status is not DepthStatus.FILLABLE:
            notes.append(f"IOC_NO_FILL: {walk.detail}")
            continue
        for n, (price, size) in enumerate(walk.levels):
            ledger.fill(fill_id=f"{entry.game_id}:bot:{_book_key(fill_book, idx)}:{n}", quantity=size, price=price,
                        fee=cfg.fee_model.sale_fee(size, price))
        if qty < d.quantity:
            notes.append(f"IOC_PARTIAL {qty} of {d.quantity} at {fill_book.receipt_utc}")
    return attempts


def _run_preplaced(cohort: Cohort, entry: CohortEntry, cfg: ReplayConfig, arm: Arm, ledger: ReplayLedger,
                   notes: list[str]) -> tuple[int, int]:
    policy = _policy(cfg, arm, Semantics.PREPLACED_LIMIT)
    entry_at = parse_utc(entry.entry_at_utc)
    if cfg.arrival_latency is None:
        notes.append("ARRIVAL_UNKNOWN: the resting sale is never known to rest; no fill is assumed")
        return 0, 0
    placed_at = entry_at + cfg.arrival_latency
    books = _books_until(entry, entry_at - cfg.max_book_age)
    # placement is a policy action: it needs an admissible book received at or before placement; a book
    # received before entry counts while it is no older than max_book_age (the policy checks its age)
    prior = [b for at, b in books if at <= placed_at]
    d = evaluate(as_of=placed_at, inventory=_inventory(entry, ledger, placed_at.isoformat()), orders=(),
                 book=_sale_book(entry, prior[-1], cfg, cohort.data_kind) if prior else None,
                 fee_model=cfg.fee_model, policy=policy, rules_version=cohort.rules_version)
    if d.status is not DecisionStatus.PROPOSED or d.action not in (Action.REDUCE, Action.EXIT):
        notes.append("NOT_PLACED: " + "; ".join(d.reasons))
        return 0, 0
    order_id = f"{entry.game_id}:rest"
    ledger.reserve(order_id, d.quantity)
    limit, filled_upto, touches, cum = d.limit_price, Decimal(0), 0, Decimal(0)
    for i, (at, book) in enumerate(books):
        if at <= placed_at or order_id not in ledger.reservations:  # only books seen after it rests
            continue
        if book.trading_state in (TradingState.TRADING_PAUSED, TradingState.EXCHANGE_PAUSED) and cfg.cancel_on_pause:
            ledger.confirm_cancel(order_id, "CANCELLED_ON_PAUSE")
            notes.append(f"CANCELLED_ON_PAUSE at {book.receipt_utc}")
            break
        if not _usable(book):
            continue  # no fills are inferred through an unusable period
        bids = _haircut(book.bids, cfg.spread_haircut_ticks)
        through = sum((s for p, s in bids if p > limit), Decimal(0))
        touch = sum((s for p, s in bids if p == limit), Decimal(0))
        if touch > 0 and through < ledger.reservations[order_id]:
            touches += 1
        crossing = through + (touch if cfg.fill_rule is FillRule.TOUCH_UPPER_BOUND else Decimal(0))
        cum = max(cum, crossing)  # visible liquidity is never summed across snapshots
        new = min(ledger.reservations[order_id], cum - filled_upto)
        new = (new / policy.quantity_step).to_integral_value(rounding=ROUND_FLOOR) * policy.quantity_step
        if new > 0:
            ledger.fill(fill_id=f"{entry.game_id}:rest:{_book_key(book, i)}", quantity=new, price=limit,
                        fee=cfg.fee_model.sale_fee(new, limit), order_id=order_id)
            filled_upto += new
    if touches:
        notes.append(f"TOUCHES_NOT_FILLS: {touches} book(s) showed bids at the limit; queue position unknown")
    notes.append("MAKER_FEE_BOUND: resting fills are charged the taker sale fee, an upper bound where the "
                 "schedule's maker fee is lower (KXNFLGAME maker fees are unverified)")
    return 1, touches


def _diagnostics(entry: CohortEntry, cfg: ReplayConfig, arm: Arm) -> list[Diagnostic]:
    """Oracle diagnostics for an exit arm. Never results, never compared as policies."""
    if arm is Arm.HOLD:
        return []
    qty = entry.quantity if arm is Arm.FULL_EXIT else (cfg.partial_fraction * entry.quantity).to_integral_value(
        rounding=ROUND_FLOOR)
    books = [b for _, b in _books_until(entry, parse_utc(entry.entry_at_utc)) if _usable(b)]
    out = []
    first = next((b for b in books if depth_at_or_above(_haircut(b.bids, cfg.spread_haircut_ticks),
                                                        cfg.target_price) > 0), None)
    if first is None:
        out.append(Diagnostic(entry.game_id, arm, "FIRST_DETECTION_ZERO_LATENCY", None, Decimal(0), None,
                              "target never displayed on a usable book"))
    else:
        bids = _haircut(first.bids, cfg.spread_haircut_ticks)
        q = min(qty, depth_at_or_above(bids, cfg.target_price)).to_integral_value(rounding=ROUND_FLOOR)
        w = walk_bids(bids, q, min_price=cfg.target_price) if q > 0 else None
        out.append(Diagnostic(entry.game_id, arm, "FIRST_DETECTION_ZERO_LATENCY",
                              None if w is None else w.gross_proceeds, q, first.receipt_utc,
                              "fill at the detecting book itself: ignores decision and arrival delay"))
    best, best_at = None, None
    for b in books:
        bids = _haircut(b.bids, cfg.spread_haircut_ticks)
        if not bids or (best is not None and bids[-1][0] * qty <= best):
            continue  # cannot beat the best so far: best bid x quantity bounds any walk
        w = walk_bids(bids, qty)
        if w.status is DepthStatus.FILLABLE and (best is None or w.gross_proceeds > best):
            best, best_at = w.gross_proceeds, b.receipt_utc
    out.append(Diagnostic(entry.game_id, arm, "HINDSIGHT_UPPER_BOUND", best, qty, best_at,
                          "best single sale over the whole game, chosen after seeing it: an oracle"))
    return out


def replay_entry(cohort: Cohort, entry: CohortEntry, cfg: ReplayConfig, arm: Arm,
                 semantics: Semantics | None) -> EntryResult:
    ledger = _new_ledger(cohort, entry, cfg)
    notes: list[str] = []
    attempts = touches = 0
    placed: bool | None = None
    receipts = [b.receipt_utc for b in entry.books]
    duplicate_receipts = len(receipts) - len(set(receipts))
    if duplicate_receipts:
        notes.append(f"DUPLICATE_RECEIPT_TIMES: {duplicate_receipts} book(s) share a receipt time; fills are keyed by "
                     "book identity, so each distinct book can fill once")
    if arm is not Arm.HOLD:
        if semantics is Semantics.BOT_TRIGGERED:
            attempts = _run_bot(cohort, entry, cfg, arm, ledger, notes)
        elif semantics is Semantics.PREPLACED_LIMIT:
            attempts, touches = _run_preplaced(cohort, entry, cfg, arm, ledger, notes)
            placed = attempts > 0
        else:
            raise ValueError("an exit arm needs exactly one execution semantics")
    s = entry.settlement
    status = EntryStatus.COMPLETE
    if s.value is None or not s.final:
        status = EntryStatus.INCOMPLETE
        notes.append("INCOMPLETE: settlement value or finality is missing; residual not valued (never 0)")
        for order_id in list(ledger.reservations):  # conservative: stays reserved in reality; closed here
            notes.append(f"RESERVATION_OPEN_AT_HORIZON {order_id}")
    else:
        ledger.settle(s.value, fee_per_contract=cfg.settlement_fee_per_contract)
    fees = None if None in ledger.fees else sum(ledger.fees, Decimal(0))
    return EntryResult(
        game_id=entry.game_id, cluster_id=entry.cluster_id, arm=arm, semantics=semantics, status=status,
        sold=ledger.sold, residual=ledger.settled_quantity if status is EntryStatus.COMPLETE else None,
        gross_proceeds=ledger.gross_proceeds, fees=fees, net_proceeds=ledger.net_proceeds,
        settlement_cash=ledger.settlement_cash, pnl_gross=ledger.pnl_gross(), pnl_net=ledger.pnl_net(),
        attempts=attempts, touches_not_filled=touches, placed=placed, duplicate_receipts=duplicate_receipts,
        notes=tuple(notes), reconciliation=tuple(ledger.reconcile()))


def _summ(results: Sequence[EntryResult], hold: Sequence[EntryResult] | None, arm: Arm,
          semantics: Semantics | None, capital: Decimal) -> ArmSummary:
    complete = [r for r in results if r.status is EntryStatus.COMPLETE]

    def total(attr: str, rows: Sequence[EntryResult]) -> Decimal | None:
        vals = [getattr(r, attr) for r in rows]
        return None if not rows or any(v is None for v in vals) else sum(vals, Decimal(0))

    pg, pn = total("pnl_gross", results), total("pnl_net", results)
    change_g = change_n = None
    if hold is not None:
        hg, hn = total("pnl_gross", hold), total("pnl_net", hold)
        change_g = None if pg is None or hg is None else pg - hg
        change_n = None if pn is None or hn is None else pn - hn
    pnl = [r.pnl_gross for r in complete if r.pnl_gross is not None]
    risk = {"per_entry_pnl_gross_min": None if not pnl else str(min(pnl)),
            "per_entry_pnl_gross_max": None if not pnl else str(max(pnl)),
            "per_entry_pnl_gross_pstdev": None if len(pnl) < 2 else str(statistics.pstdev(pnl).quantize(Decimal("1e-6"))),
            "note": "risk is reported apart from the expected-profit change; entries in one cluster are not "
                    "independent"}
    return ArmSummary(arm, semantics, len(results), len(complete), len(results) - len(complete), pg, pn,
                      None if pg is None else capital + pg, None if pn is None else capital + pn,
                      sum((r.pnl_gross for r in complete if r.pnl_gross is not None), Decimal(0)),
                      change_g, change_n, risk, len({r.cluster_id for r in results}),
                      sum(1 for r in results if r.placed is False))


def replay(cohort: Cohort, cfg: ReplayConfig) -> ReplayReport:
    """Replay every arm under both semantics over the identical cohort. Pure and in memory."""
    problems = cfg.problems()
    if problems:
        raise ValueError("; ".join(problems))
    if not valid_price(cfg.target_price):
        raise ValueError("target must be a valid dollar price")
    if not (Decimal(0) < cfg.partial_fraction < Decimal(1)):
        raise ValueError("partial fraction must be strictly between 0 and 1")
    runs: list[tuple[Arm, Semantics | None]] = [(Arm.HOLD, None)] + [
        (a, s) for a in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT) for s in Semantics]
    results: dict[tuple[Arm, Semantics | None], list[EntryResult]] = {k: [] for k in runs}
    diagnostics: list[Diagnostic] = []
    for entry in cohort.entries:
        for key in runs:
            results[key].append(replay_entry(cohort, entry, cfg, *key))
        for arm in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT):
            diagnostics.extend(_diagnostics(entry, cfg, arm))
    hold = results[(Arm.HOLD, None)]
    arms = tuple(_summ(results[k], None if k[0] is Arm.HOLD else hold, *k, cohort.starting_capital) for k in runs)
    basis = cfg.fee_model.claim_basis
    any_unknown = any(r.pnl_net is None and r.status is EntryStatus.COMPLETE for rs in results.values()
                      for r in rs)
    after_cost = (basis is not ClaimBasis.NONE and not any_unknown and cohort.data_kind is not DataKind.SYNTHETIC
                  and cfg.diagnostic_mode is None)
    reason = ("after-cost claims need a claimable fee basis, every cost known and non-synthetic evidence; "
              f"fee basis {basis.value}, unknown costs {any_unknown}, data {cohort.data_kind.value}")
    return ReplayReport(
        version=REPLAY_VERSION, cohort_id=cohort.cohort_id, cohort_sha256=cohort.sha256,
        diagnostic_mode=cfg.diagnostic_mode,
        data_kind=cohort.data_kind.value, label=cohort.label, config_variant=cfg.variant_id(),
        fill_rule=cfg.fill_rule.value, fee_model=cfg.fee_model.model_id, fee_claim_basis=basis.value,
        after_cost_claim=after_cost, after_cost_reason=reason, arms=arms,
        entries=tuple(r for k in runs for r in results[k]), diagnostics=tuple(diagnostics),
        notes=("Proceeds are not profit: P&L is terminal wealth minus starting cash over the common horizon.",
               "Released cash stays idle to the common horizon; no recycling is assumed.",
               "Diagnostics (FIRST_DETECTION_ZERO_LATENCY, HINDSIGHT_UPPER_BOUND) are not policy results.",
               "Entries within one cluster (NFL week) are not independent; do not annualize.")
        + ((f"DIAGNOSTIC_MODE {cfg.diagnostic_mode}: decision plus arrival latency is 0; every arm here is a "
            "labelled diagnostic, not a policy result and not executable evidence",)
           if cfg.diagnostic_mode else ()))


def sensitivity(cohort: Cohort, base: ReplayConfig, *, latencies: Sequence[timedelta | None] = (),
                haircuts: Sequence[int] = (), fill_rules: Sequence[FillRule] = ()) -> tuple[ReplayReport, ...]:
    """Every listed variant, all reported (none is picked as best). The count is part of the result."""
    variants = [base]
    variants += [replace(base, arrival_latency=v) for v in latencies]
    variants += [replace(base, spread_haircut_ticks=h) for h in haircuts]
    variants += [replace(base, fill_rule=r) for r in fill_rules]
    seen, out = set(), []
    for v in variants:
        if v.variant_id() not in seen:
            seen.add(v.variant_id())
            out.append(replay(cohort, v))
    return tuple(out)


# --------------------------------------------------------------------------- synthetic cohorts


def synthetic_martingale_cohort(*, seed: int, games: int, start: Decimal = Decimal("0.30"),
                                tick: Decimal = Decimal("0.10"), quantity: Decimal = Decimal(100),
                                depth: Decimal = Decimal(1000), spread_ticks: int = 0, step_seconds: int = 30,
                                games_per_cluster: int = 4, entry_cost: Decimal | None = None,
                                entry_fee_known: bool = True) -> Cohort:
    """A calibrated-price synthetic null: the YES price is a symmetric random walk on a `tick`
    grid, absorbed at 0 or 1, so it is a martingale and P(YES) equals the price by construction.
    Selling at any stopping time cannot beat holding in expectation before costs; with spread
    and fees it can only lose. The walk is continuous on its grid, so it cannot jump through a
    target on the grid. Deterministic for a seed. Labelled SYNTHETIC; never evidence of an edge.
    `entry_fee_known=False` leaves every entry cost unknown (None), so no net figure exists."""
    if not valid_price(start) or tick <= 0 or (start % tick) != 0:
        raise ValueError("start must be a valid price on the tick grid")
    rng = random.Random(seed)
    t0 = datetime(2026, 1, 4, 18, 0, tzinfo=timezone.utc)
    entries, horizon = [], t0
    for g in range(games):
        p, t, books = start, t0, []
        while Decimal(0) < p < Decimal(1):
            bid = p - TICK * spread_ticks
            books.append(TimedBook(t.isoformat(), ((bid, depth),) if valid_price(bid) else (),
                                   evidence_id=f"synthetic:{seed}:{g}:{len(books)}"))
            p = p + tick if rng.random() < 0.5 else p - tick
            t = t + timedelta(seconds=step_seconds)
        horizon = max(horizon, t)
        entries.append(CohortEntry(
            game_id=f"SYN-{seed}-{g:05d}", cluster_id=f"W{g // games_per_cluster:04d}", market_id=f"kalshi:SYN-{g}",
            quantity=quantity, entry_price=start,
            entry_cost=None if not entry_fee_known else quantity * start if entry_cost is None else entry_cost,
            entry_at_utc=t0.isoformat(), books=tuple(books),
            settlement=Settlement(Decimal(1) if p >= 1 else Decimal(0), True, t.isoformat())))
    return Cohort(cohort_id=f"synthetic-martingale-{seed}-{games}", data_kind=DataKind.SYNTHETIC,
                  label="SYNTHETIC calibrated-martingale null (P(YES) = price by construction)",
                  entries=tuple(entries), starting_capital=quantity * start * games,
                  horizon_utc=horizon.isoformat(), rules_version="synthetic-rules-v1")
