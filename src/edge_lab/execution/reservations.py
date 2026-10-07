"""Atomic cash and inventory reservations with fencing (#160 package E, ADR 0043). Offline.

`ReservationAuthority` lives in the execution journal's SQLite store and runs inside the journal's
transactions (`BEGIN IMMEDIATE`). A reservation is created only inside `ExecutionJournal.prepare_attempt`,
so it and the PENDING_EGRESS attempt it backs commit together or not at all. Two processes can never both
spend the same capacity: the second transaction waits for the write lock and then sees the first one's
reservation. A reservation's id is its attempt's id.

**Account identity.** An `AccountScope` (environment, `account_ref`, subaccount) must map 1:1 to one venue
account and subaccount: every snapshot, reservation and capacity check is per `scope.key()`. Two refs for
one venue account would split its cash in two. Package G (account reconciliation) enforces that binding.

**Arithmetic has one owner.** Cash capacity is decided by
`execution_ticket.reserve_simultaneous_obligations`. This module only builds its `Obligation`s:
- every held local reservation (any state but RELEASED);
- every external open order in the latest account snapshot;
- the candidate.

Every Decimal operation here, the owner's sum included, runs in an exact local context that traps
rounding (`_exact_context()`), so the caller's thread-wide `decimal` precision can never change a decision.

Cash worst cases:
- ENTRY and REDUCTION: `intent.max_total_cost` (for a REDUCTION that is its fee bound);
- a local order the latest snapshot lists as open, bound to its reservation id with a matching price and
  exactly the local remaining quantity (`AttributedOrder`), is provider-held: the venue already holds its
  cash, so only the residual the snapshot reports (`unreflected_cash`) counts. Every other held reservation
  is local-only and counts in full, so nothing is spent twice. A venue remainder below the local one (fills
  not yet recorded here) is consistent but counts in full; one above it makes the snapshot inconsistent;
- an external order: its `unreflected_cash`; None is unknown and blocks new risk;
- a quarantined reservation (below): unknown, which blocks all new risk in its scope.

Inventory (REDUCTION only, keyed by `(market_ticker, side)`, never netted across markets or sides):
`quantity <= position - every held local reduction - every external open sell`. An external order whose
market, side or action is unknown counts against every key it could touch. Exact equality is allowed.

**Missing is not zero.** No snapshot, a stale or inconsistent snapshot, UNKNOWN cash basis, unknown cash,
unknown positions, unknown external orders or an unknown worst case all mean no new risk.

**Release only on confirmed outcomes** (states mirror `ObligationState`):
- OUTSTANDING: prepared, sent or acknowledged;
- CANCEL_REQUESTED: still held, because a request is not a confirmation;
- UNKNOWN: still held until reconciled;
- BOUND: the order is over at the venue (cancel confirmed, expired, or completely filled) but no snapshot
  observed strictly after its end and its last fill has confirmed the result. Still held in full: a fill can arrive
  after the cancel confirmation, and the latest snapshot may not reflect either;
- RELEASED: rejected or absent at the venue (it never existed), or `confirm_by_snapshot` after BOUND.

A confirmed cancel or expiry carries the venue's cumulative filled quantity. A fill is always recorded,
in any state. A fill that contradicts the journal (it shrinks, exceeds the order, or arrives after
release) quarantines the reservation: it goes back to UNKNOWN, held, with `quarantine_reason` set, and its
worst case becomes unknown until `resolve_quarantine` records the venue's answer.

**Fencing.** One egress lease per store. `acquire_lease` returns a strictly increasing fence token and
refuses while another worker's lease is unexpired. A takeover does not prove the old worker stopped, so
every PENDING_EGRESS or SENT attempt of an older fence becomes OUTCOME_UNKNOWN and keeps its reservation.
Reserving checks the token inside the prepare transaction: a stale token is refused before anything is
committed. The lease clock is the caller's `now`.

Schema (part of journal schema version 1; money and quantities are canonical Decimal text, never REAL):
- `egress_lease(lease_name PK, worker_id, fence_token, acquired_at_utc, expires_at_utc)`: one row.
- `account_snapshots(scope_key, revision, observed_at_utc, recorded_at_utc, cash, cash_basis,
  positions_json, external_orders_json, attributed_json, consistent, problems_json)`: append-only,
  revisions strictly increasing per scope. NULL means unknown.
- `reservations(reservation_id PK, intent_key FK, scope_key, market_ticker, side, kind, client_order_id,
  quantity, limit_price, filled_quantity, cash_worst_case, state, release_reason, end_reason, ended_at_utc,
  quarantine_reason, fence_token, created_at_utc, updated_at_utc, last_fill_at_utc)`: a mutable projection;
  every change is a hash-chained journal event.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Any, ContextManager, Iterable, Iterator, Mapping, Protocol

from .. import freshness
from ..execution_ticket import Obligation, ObligationState, reserve_simultaneous_obligations
from .model import (MAX_DIGITS, AccountScope, Action, ExactValueError, IntentKind, OrderIntent, Side, canonical_json,
                    decimal_text, exact_decimal, parse_utc_text, utc_text)

EGRESS_LEASE = "egress"
# How far a snapshot's observed_at may be ahead of the recorder's clock. Beyond it the clocks disagree.
SNAPSHOT_CLOCK_SKEW = timedelta(seconds=5)


def _exact_context() -> Context:
    """Exact arithmetic: a result that would need rounding raises instead of being rounded. A fresh context
    per use, because a shared module-level Context would be mutable state."""
    return Context(prec=2 * MAX_DIGITS + 10, traps=[InvalidOperation, Inexact, Rounded])


SCHEMA_SQL = """
CREATE TABLE egress_lease (
    lease_name TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
    acquired_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL
);
CREATE TABLE account_snapshots (
    scope_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    observed_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    cash TEXT,
    cash_basis TEXT NOT NULL CHECK (cash_basis IN ('AVAILABLE_AFTER_VENUE_HOLDS', 'UNKNOWN')),
    positions_json TEXT,
    external_orders_json TEXT,
    attributed_json TEXT NOT NULL,
    consistent INTEGER NOT NULL CHECK (consistent IN (0, 1)),
    problems_json TEXT NOT NULL,
    PRIMARY KEY (scope_key, revision)
);
CREATE TABLE reservations (
    reservation_id TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL REFERENCES intents(intent_key),
    scope_key TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('yes', 'no')),
    kind TEXT NOT NULL CHECK (kind IN ('ENTRY', 'REDUCTION')),
    client_order_id TEXT NOT NULL,
    quantity TEXT NOT NULL,
    limit_price TEXT NOT NULL,
    filled_quantity TEXT NOT NULL,
    cash_worst_case TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('OUTSTANDING', 'CANCEL_REQUESTED', 'UNKNOWN', 'BOUND', 'RELEASED')),
    release_reason TEXT,
    end_reason TEXT CHECK (end_reason IS NULL OR end_reason IN ('CANCEL_CONFIRMED', 'EXPIRED', 'FILLED')),
    ended_at_utc TEXT,
    quarantine_reason TEXT,
    fence_token INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    last_fill_at_utc TEXT
);
CREATE INDEX reservations_held ON reservations(scope_key, state);
"""
# Append-only tables owned here, with the key columns an INSERT OR REPLACE would collide on.
APPEND_ONLY_KEYS = MappingProxyType({"account_snapshots": ("scope_key", "revision")})


class CashBasis(str, Enum):
    """What the snapshot's cash number means. Only an explicit basis is usable."""

    # Spendable cash after the venue's holds for every open order the snapshot lists.
    AVAILABLE_AFTER_VENUE_HOLDS = "AVAILABLE_AFTER_VENUE_HOLDS"
    UNKNOWN = "UNKNOWN"  # no new risk


class ExternalOrigin(str, Enum):
    """An open order not attributed to a local attempt."""

    MANUAL = "MANUAL"  # placed by a person in the venue's own interface
    NATIVE_AUTO_SELL = "NATIVE_AUTO_SELL"  # the venue's own automatic sell
    UNKNOWN = "UNKNOWN"


class ReleaseReason(str, Enum):
    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"  # cancelled with nothing filled, confirmed by a later snapshot
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"  # expired with nothing filled, confirmed by a later snapshot
    ABSENT_AT_VENUE = "ABSENT_AT_VENUE"  # reconciliation found no such order: it never existed
    CONVERTED_TO_POSITION = "CONVERTED_TO_POSITION"  # its fills are in a later snapshot's position


class EndReason(str, Enum):
    """Why the order is over at the venue (BOUND until a snapshot confirms the result)."""

    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
    EXPIRED = "EXPIRED"
    FILLED = "FILLED"


class ReceiptKind(str, Enum):
    """Receipt kinds that can justify a state change. The journal accepts other labels as evidence, but
    only these kinds, bound to the same attempt, move an attempt or a reservation."""

    ORDER_ACK = "ORDER_ACK"  # the venue accepted the order
    ORDER_REJECT = "ORDER_REJECT"  # the venue refused it: no order exists
    ORDER_LOOKUP = "ORDER_LOOKUP"  # a read of the order's current state by id or client order id
    CANCEL_CONFIRM = "CANCEL_CONFIRM"  # the venue confirmed a cancel (with its cumulative filled quantity)
    CANCEL_REJECT = "CANCEL_REJECT"  # the venue refused a cancel: the order is still open
    ORDER_EXPIRED = "ORDER_EXPIRED"  # the venue reports the order expired
    FILL = "FILL"  # a fill report with the cumulative filled quantity


class ReservationError(Exception):
    """A reservation-domain refusal. Nothing was committed."""


class ReservationRefused(ReservationError):
    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons) or "refused")


class StaleFence(ReservationError):
    """The fence token is not the current, unexpired egress lease."""


class LeaseHeld(ReservationError):
    """Another worker holds an unexpired egress lease."""


class SnapshotRefused(ReservationError):
    """The snapshot cannot be recorded (a revision that does not increase, or a time from the future)."""


class InvalidTransition(ReservationError):
    """A state change that the state machine or the evidence does not allow."""


class CorruptRecord(ValueError):
    """A stored value that does not decode. The journal maps it to JournalCorrupt."""


class _Store(Protocol):
    """What the authority needs from the journal that owns the store."""

    def _transaction(self) -> ContextManager[sqlite3.Connection]: ...

    def _reading(self) -> ContextManager[sqlite3.Connection]: ...

    def _in_transaction(self) -> bool: ...

    def _audit(self, conn: sqlite3.Connection, *, at: str, kind: str, subject: str, body: dict) -> None: ...

    def _row_sha(self, conn: sqlite3.Connection, table: str, where: Mapping[str, Any]) -> str: ...

    def _require_receipt(self, conn: sqlite3.Connection, receipt_id: str, *, kinds: Iterable[ReceiptKind],
                         attempt_id: str) -> None: ...

    def _quarantine_superseded_fences(self, conn: sqlite3.Connection, *, live_token: int | None,
                                      at: str) -> list[str]: ...


@contextmanager
def _exact(refusal: type[ReservationError] = ReservationRefused) -> Iterator[None]:
    """Run Decimal arithmetic exactly; a result that would need rounding refuses instead."""
    try:
        with localcontext(_exact_context()):
            yield
    except (Inexact, Rounded, InvalidOperation) as exc:
        if refusal is ReservationRefused:
            raise ReservationRefused([f"ARITHMETIC_NOT_EXACT: {type(exc).__name__}"]) from exc
        raise refusal(f"ARITHMETIC_NOT_EXACT: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class ExternalOrder:
    """An open order the venue lists that no local attempt owns. Every unknown field is None.

    `unreflected_cash` is the most cash this order can still consume that the snapshot's cash does not
    already reflect (a sell's fee, for instance). None is unknown and blocks new risk."""

    order_ref: str
    origin: ExternalOrigin
    market_ticker: str | None
    side: Side | None
    action: Action | None
    remaining_quantity: Decimal | None
    unreflected_cash: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.order_ref, str) or not self.order_ref:
            raise ValueError("order_ref is required")
        if not isinstance(self.origin, ExternalOrigin):
            raise ValueError("origin must be an ExternalOrigin")
        if self.market_ticker is not None and (not isinstance(self.market_ticker, str) or not self.market_ticker):
            raise ValueError("market_ticker must be a non-empty str or None")
        if self.side is not None and not isinstance(self.side, Side):
            raise ValueError("side must be a Side or None")
        if self.action is not None and not isinstance(self.action, Action):
            raise ValueError("action must be an Action or None")
        for name in ("remaining_quantity", "unreflected_cash"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, exact_decimal(value, name=name))

    def could_sell(self, market_ticker: str, side: Side) -> bool:
        """Whether this order could consume inventory of (market_ticker, side). Unknown counts as yes."""
        return (self.action in (Action.SELL, None) and self.market_ticker in (market_ticker, None)
                and self.side in (side, None))

    def to_dict(self) -> dict[str, Any]:
        return {"order_ref": self.order_ref, "origin": self.origin, "market_ticker": self.market_ticker,
                "side": self.side, "action": self.action, "remaining_quantity": self.remaining_quantity,
                "unreflected_cash": self.unreflected_cash}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ExternalOrder":
        return cls(d["order_ref"], ExternalOrigin(d["origin"]), d["market_ticker"],
                   None if d["side"] is None else Side(d["side"]),
                   None if d["action"] is None else Action(d["action"]),
                   d["remaining_quantity"], d["unreflected_cash"])  # stored text; exact_decimal re-checks it


@dataclass(frozen=True)
class AttributedOrder:
    """A local order the venue lists as open in this snapshot. It is bound to one reservation (its attempt
    id), never to the client order id alone, which every attempt of an intent shares. The venue's
    `remaining_quantity` and `limit_price` must match the reservation (quantity minus recorded fills, and
    the intent's limit), or the snapshot is inconsistent. Its cash is held by the venue; `unreflected_cash`
    is any residual it does not hold (None: unknown, which blocks new risk)."""

    reservation_id: str
    client_order_id: str
    remaining_quantity: Decimal
    limit_price: Decimal
    unreflected_cash: Decimal | None

    def __post_init__(self) -> None:
        for name in ("reservation_id", "client_order_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in ("remaining_quantity", "limit_price"):
            object.__setattr__(self, name, exact_decimal(getattr(self, name), name=name))
        if self.unreflected_cash is not None:
            object.__setattr__(self, "unreflected_cash", exact_decimal(self.unreflected_cash, name="unreflected_cash"))

    def to_dict(self) -> dict[str, Any]:
        return {"reservation_id": self.reservation_id, "client_order_id": self.client_order_id,
                "remaining_quantity": self.remaining_quantity, "limit_price": self.limit_price,
                "unreflected_cash": self.unreflected_cash}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "AttributedOrder":
        return cls(d["reservation_id"], d["client_order_id"], d["remaining_quantity"], d["limit_price"],
                   d["unreflected_cash"])


@dataclass(frozen=True)
class AccountSnapshot:
    scope_key: str
    revision: int
    observed_at_utc: str
    recorded_at_utc: str
    cash: Decimal | None
    cash_basis: CashBasis
    positions: Mapping[tuple[str, Side], Decimal] | None
    external_orders: tuple[ExternalOrder, ...] | None
    attributed: Mapping[str, AttributedOrder]  # by reservation id
    consistent: bool
    problems: tuple[str, ...]

    def usable_cash(self) -> Decimal | None:
        """The spendable cash, or None when its basis or value is unknown."""
        return self.cash if self.cash_basis is CashBasis.AVAILABLE_AFTER_VENUE_HOLDS else None

    def lists_client_order(self, client_order_id: str) -> bool:
        return any(a.client_order_id == client_order_id for a in self.attributed.values())


@dataclass(frozen=True)
class Lease:
    worker_id: str
    fence_token: int
    acquired_at_utc: str
    expires_at_utc: str

    def live_at(self, now: datetime) -> bool:
        return parse_utc_text(self.expires_at_utc) > now


@dataclass(frozen=True)
class ReservationView:
    reservation_id: str
    intent_key: str
    scope_key: str
    market_ticker: str
    side: Side
    kind: IntentKind
    client_order_id: str
    quantity: Decimal
    limit_price: Decimal
    filled_quantity: Decimal
    cash_worst_case: Decimal
    state: ObligationState
    release_reason: ReleaseReason | None
    end_reason: EndReason | None
    ended_at_utc: str | None
    quarantine_reason: str | None
    fence_token: int
    created_at_utc: str
    updated_at_utc: str
    last_fill_at_utc: str | None
    # The latest snapshot lists this order as open with exactly its local remainder: the venue holds its cash.
    provider_held: bool


@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reasons: tuple[str, ...]
    snapshot_revision: int | None
    cash_required: Decimal | None  # every held obligation plus the candidate, if all bind at once
    cash_available: Decimal | None
    inventory_available: Decimal | None  # REDUCTION only


_TRANSITIONS: Mapping[ObligationState, frozenset[ObligationState]] = MappingProxyType({
    ObligationState.OUTSTANDING: frozenset({ObligationState.CANCEL_REQUESTED, ObligationState.UNKNOWN,
                                            ObligationState.BOUND, ObligationState.RELEASED}),
    ObligationState.CANCEL_REQUESTED: frozenset({ObligationState.OUTSTANDING, ObligationState.UNKNOWN,
                                                 ObligationState.BOUND}),
    ObligationState.UNKNOWN: frozenset({ObligationState.OUTSTANDING, ObligationState.CANCEL_REQUESTED,
                                        ObligationState.BOUND, ObligationState.RELEASED}),
    ObligationState.BOUND: frozenset({ObligationState.RELEASED}),
    ObligationState.RELEASED: frozenset(),
})
# Only a quarantine moves a reservation outside this table (to UNKNOWN, from any state, RELEASED included).


def _dec(text: str | None, *, name: str) -> Decimal | None:
    if text is None:
        return None
    try:
        return exact_decimal(text, name=name)
    except ExactValueError as exc:
        raise CorruptRecord(f"stored {name} is not exact decimal text: {text!r}") from exc


def _req_dec(text: str, *, name: str) -> Decimal:
    value = _dec(text, name=name)
    if value is None:
        raise CorruptRecord(f"stored {name} is missing")
    return value


def _opt_text(value: Decimal | None) -> str | None:
    return None if value is None else decimal_text(value)


def _positive_ttl(ttl: timedelta) -> None:
    if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
        raise ValueError("ttl must be a positive timedelta")


def _later(*times: str | None) -> datetime | None:
    parsed = [parse_utc_text(t) for t in times if t is not None]
    return max(parsed) if parsed else None


class ReservationAuthority:
    """The one transactional cash and inventory authority. Built by `ExecutionJournal`; never alone."""

    def __init__(self, store: _Store):
        self._store = store

    # ------------------------------------------------------------------ fencing

    def acquire_lease(self, worker_id: str, ttl: timedelta, now: datetime) -> int:
        """A new, strictly larger fence token for `worker_id`. Refused while another worker's lease is
        unexpired. Every in-flight attempt of an older fence becomes OUTCOME_UNKNOWN (still reserved)."""
        if not isinstance(worker_id, str) or not worker_id:
            raise ValueError("worker_id is required")
        _positive_ttl(ttl)
        at = utc_text(now)
        with self._store._transaction() as conn:
            current = self._lease(conn)
            if current is not None and current.worker_id != worker_id and current.live_at(now):
                raise LeaseHeld(f"worker {current.worker_id!r} holds fence {current.fence_token} until "
                                f"{current.expires_at_utc}")
            token = (current.fence_token if current else 0) + 1
            expires = utc_text(now + ttl)
            conn.execute("INSERT INTO egress_lease (lease_name, worker_id, fence_token, acquired_at_utc, expires_at_utc)"
                         " VALUES (?, ?, ?, ?, ?) ON CONFLICT (lease_name) DO UPDATE SET worker_id = excluded.worker_id,"
                         " fence_token = excluded.fence_token, acquired_at_utc = excluded.acquired_at_utc,"
                         " expires_at_utc = excluded.expires_at_utc", (EGRESS_LEASE, worker_id, token, at, expires))
            self._store._audit(conn, at=at, kind="LEASE_ACQUIRED", subject=EGRESS_LEASE,
                               body={"worker_id": worker_id, "fence_token": token, "acquired_at_utc": at,
                                     "expires_at_utc": expires,
                                     "previous_worker_id": current.worker_id if current else None,
                                     "previous_fence_token": current.fence_token if current else None})
            self._store._quarantine_superseded_fences(conn, live_token=token, at=at)
        return token

    def renew_lease(self, worker_id: str, fence_token: int, ttl: timedelta, now: datetime) -> None:
        """Extend the current lease. Refused unless `fence_token` is still the current token of `worker_id`."""
        _positive_ttl(ttl)
        at = utc_text(now)
        with self._store._transaction() as conn:
            current = self._lease(conn)
            if current is None or current.fence_token != fence_token or current.worker_id != worker_id:
                raise StaleFence(f"fence {fence_token} of {worker_id!r} is not the current lease")
            expires = utc_text(now + ttl)
            conn.execute("UPDATE egress_lease SET expires_at_utc = ? WHERE lease_name = ?", (expires, EGRESS_LEASE))
            self._store._audit(conn, at=at, kind="LEASE_RENEWED", subject=EGRESS_LEASE,
                               body={"worker_id": worker_id, "fence_token": fence_token,
                                     "acquired_at_utc": current.acquired_at_utc, "expires_at_utc": expires})

    def lease(self) -> Lease | None:
        with self._store._reading() as conn:
            return self._lease(conn)

    def _lease(self, conn: sqlite3.Connection) -> Lease | None:
        row = conn.execute("SELECT worker_id, fence_token, acquired_at_utc, expires_at_utc FROM egress_lease"
                           " WHERE lease_name = ?", (EGRESS_LEASE,)).fetchone()
        return None if row is None else Lease(row[0], int(row[1]), row[2], row[3])

    def _check_fence(self, conn: sqlite3.Connection, fence_token: int, now: datetime) -> Lease:
        if isinstance(fence_token, bool) or not isinstance(fence_token, int):
            raise StaleFence(f"fence token must be an int, not {fence_token!r}")
        current = self._lease(conn)
        if current is None or current.fence_token != fence_token:
            raise StaleFence(f"fence {fence_token} is not the current egress lease "
                             f"({current.fence_token if current else 'none'})")
        if not current.live_at(now):
            raise StaleFence(f"fence {fence_token} expired at {current.expires_at_utc}")
        return current

    # ------------------------------------------------------------------ account snapshots

    def record_account_snapshot(self, scope: AccountScope, revision: int, observed_at: datetime,
                                cash: Decimal | None, cash_basis: CashBasis,
                                positions: Mapping[tuple[str, Side], Decimal] | None,
                                external_open_orders: Iterable[ExternalOrder] | None, *,
                                attributed_open_orders: Iterable[AttributedOrder] = (),
                                now: datetime) -> AccountSnapshot:
        """Record what the venue reported for `scope` at `observed_at`, as revision `revision`.

        Refused (SnapshotRefused): a revision that does not strictly increase, or an `observed_at` more
        than SNAPSHOT_CLOCK_SKEW after `now`. None for cash, positions or external orders is unknown, never
        zero or flat. A snapshot that contradicts itself or the journal (negative cash or quantities, an
        attributed order that does not match a held reservation, time going backwards) is recorded as
        evidence but marked inconsistent, and an inconsistent latest snapshot allows no new risk."""
        if not isinstance(scope, AccountScope):
            raise ValueError("scope must be an AccountScope")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("revision must be a positive int")
        if not isinstance(cash_basis, CashBasis):
            raise ValueError("cash_basis must be a CashBasis")
        observed = utc_text(observed_at)
        at = utc_text(now)
        if observed_at > now + SNAPSHOT_CLOCK_SKEW:
            raise SnapshotRefused(f"observed_at {observed} is more than {SNAPSHOT_CLOCK_SKEW} after now {at}")
        cash = None if cash is None else exact_decimal(cash, name="cash")
        pos: dict[tuple[str, Side], Decimal] | None = None
        if positions is not None:
            pos = {}
            for key, qty in positions.items():
                if (not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str) or not key[0]
                        or not isinstance(key[1], Side)):
                    raise ValueError(f"a position key is (market_ticker, Side), not {key!r}")
                pos[key] = exact_decimal(qty, name=f"position {key[0]} {key[1].value}")
        externals = None if external_open_orders is None else tuple(external_open_orders)
        if externals is not None and not all(isinstance(e, ExternalOrder) for e in externals):
            raise ValueError("external_open_orders must be ExternalOrder values")
        attributed = tuple(attributed_open_orders)
        if not all(isinstance(a, AttributedOrder) for a in attributed):
            raise ValueError("attributed_open_orders must be AttributedOrder values")

        with self._store._transaction() as conn:
            latest = self._snapshot(conn, scope.key())
            if latest is not None and revision <= latest.revision:
                raise SnapshotRefused(f"revision {revision} does not increase on {latest.revision} for {scope.key()}")
            with _exact(SnapshotRefused):
                problems = self._snapshot_problems(conn, scope.key(), latest, observed, cash, pos, externals,
                                                   attributed)
            positions_json = None if pos is None else canonical_json(
                sorted([t, s.value, decimal_text(q)] for (t, s), q in pos.items()))
            externals_json = None if externals is None else canonical_json(
                sorted((e.to_dict() for e in externals), key=lambda d: d["order_ref"]))
            attributed_json = canonical_json(sorted((a.to_dict() for a in attributed),
                                                    key=lambda d: d["reservation_id"]))
            conn.execute("INSERT INTO account_snapshots (scope_key, revision, observed_at_utc, recorded_at_utc, cash,"
                         " cash_basis, positions_json, external_orders_json, attributed_json, consistent, problems_json)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (scope.key(), revision, observed, at, _opt_text(cash), cash_basis.value, positions_json,
                          externals_json, attributed_json, 0 if problems else 1, canonical_json(problems)))
            subject = f"{scope.key()}#{revision}"
            self._store._audit(conn, at=at, kind="SNAPSHOT_RECORDED", subject=subject,
                               body={"row_sha256": self._store._row_sha(conn, "account_snapshots",
                                                                        {"scope_key": scope.key(), "revision": revision}),
                                     "consistent": not problems, "problems": problems})
            return self._snapshot(conn, scope.key())  # type: ignore[return-value]

    @staticmethod
    def _snapshot_problems(conn: sqlite3.Connection, scope_key: str, latest: AccountSnapshot | None, observed: str,
                           cash: Decimal | None, pos: Mapping[tuple[str, Side], Decimal] | None,
                           externals: tuple[ExternalOrder, ...] | None,
                           attributed: tuple[AttributedOrder, ...]) -> list[str]:
        problems: list[str] = []
        if latest is not None and parse_utc_text(observed) < parse_utc_text(latest.observed_at_utc):
            problems.append(f"OBSERVED_BEFORE_PREVIOUS_REVISION: {observed} < {latest.observed_at_utc}")
        if cash is not None and cash < 0:
            problems.append(f"NEGATIVE_CASH: {cash}")
        for (ticker, side), qty in (pos or {}).items():
            if qty < 0:
                problems.append(f"NEGATIVE_POSITION: {ticker} {side.value} {qty}")
        refs = [e.order_ref for e in externals or ()]
        if len(refs) != len(set(refs)):
            problems.append("DUPLICATE_EXTERNAL_ORDER")
        for e in externals or ():
            for name in ("remaining_quantity", "unreflected_cash"):
                value = getattr(e, name)
                if value is not None and value < 0:
                    problems.append(f"NEGATIVE_EXTERNAL_{name.upper()}: {e.order_ref}")
        ids = [a.reservation_id for a in attributed]
        if len(ids) != len(set(ids)) or len({a.client_order_id for a in attributed}) != len(attributed):
            problems.append("DUPLICATE_ATTRIBUTED_ORDER")
        for a in attributed:
            row = conn.execute("SELECT client_order_id, quantity, filled_quantity, limit_price, created_at_utc, state"
                               " FROM reservations WHERE reservation_id = ? AND scope_key = ?",
                               (a.reservation_id, scope_key)).fetchone()
            if row is None or row[5] == ObligationState.RELEASED.value:
                problems.append(f"ATTRIBUTION_UNKNOWN: {a.reservation_id} is not a held local reservation")
                continue
            remaining = _req_dec(row[1], name="quantity") - _req_dec(row[2], name="filled_quantity")
            if row[0] != a.client_order_id:
                problems.append(f"ATTRIBUTION_MISMATCH: {a.reservation_id} client order id differs")
            if parse_utc_text(observed) < parse_utc_text(row[4]):
                problems.append(f"ATTRIBUTION_BEFORE_RESERVATION: {a.reservation_id} was created after {observed}")
            # Below the local remainder is fills not yet recorded here: consistent, but the reservation is
            # then counted in full (`_decode`). Above it, or negative, the venue shows more open than can be.
            if a.remaining_quantity > remaining or a.remaining_quantity < 0:
                problems.append(f"ATTRIBUTION_SIZE_MISMATCH: {a.reservation_id} venue remaining "
                                f"{a.remaining_quantity} > local {remaining}")
            if a.limit_price != _req_dec(row[3], name="limit_price"):
                problems.append(f"ATTRIBUTION_PRICE_MISMATCH: {a.reservation_id} venue price {a.limit_price}")
            if a.unreflected_cash is not None and a.unreflected_cash < 0:
                problems.append(f"NEGATIVE_ATTRIBUTED_CASH: {a.reservation_id}")
        return problems

    def latest_snapshot(self, scope: AccountScope) -> AccountSnapshot | None:
        with self._store._reading() as conn:
            return self._snapshot(conn, scope.key())

    def _snapshot(self, conn: sqlite3.Connection, scope_key: str, revision: int | None = None) -> AccountSnapshot | None:
        """The latest snapshot for `scope_key`, or the given revision."""
        sql = ("SELECT scope_key, revision, observed_at_utc, recorded_at_utc, cash, cash_basis, positions_json,"
               " external_orders_json, attributed_json, consistent, problems_json FROM account_snapshots"
               " WHERE scope_key = ?")
        row = (conn.execute(sql + " ORDER BY revision DESC LIMIT 1", (scope_key,)).fetchone() if revision is None
               else conn.execute(sql + " AND revision = ?", (scope_key, revision)).fetchone())
        if row is None:
            return None
        try:
            positions = None if row[6] is None else {
                (t, Side(s)): _req_dec(q, name="position") for t, s, q in json.loads(row[6])}
            externals = None if row[7] is None else tuple(ExternalOrder.from_dict(d) for d in json.loads(row[7]))
            attributed = {a.reservation_id: a for a in (AttributedOrder.from_dict(d) for d in json.loads(row[8]))}
            return AccountSnapshot(row[0], int(row[1]), row[2], row[3], _dec(row[4], name="cash"),
                                   CashBasis(row[5]), positions, externals, attributed, bool(row[9]),
                                   tuple(json.loads(row[10])))
        except (ValueError, KeyError, TypeError) as exc:
            raise CorruptRecord(f"account snapshot {scope_key}#{row[1]} does not decode: {exc}") from exc

    # ------------------------------------------------------------------ reserving (only inside prepare_attempt)

    def evaluate(self, intent: OrderIntent, now: datetime, *, snapshot_max_age: timedelta) -> ReservationDecision:
        """Whether `intent` would fit now. Read-only: it reserves nothing."""
        with self._store._reading() as conn:
            return self._evaluate(conn, intent, now, snapshot_max_age=snapshot_max_age, candidate_id="candidate")

    def _reserve(self, conn: sqlite3.Connection, intent: OrderIntent, fence_token: int, now: datetime, *,
                 snapshot_max_age: timedelta, reservation_id: str) -> ReservationView:
        """Reserve `intent`'s cash worst case (and, for a REDUCTION, its inventory) under the current fence.
        Private: only `prepare_attempt` calls it, inside its transaction, so a reservation never exists
        without the attempt it backs. Raises StaleFence or ReservationRefused, and then nothing commits."""
        if not self._store._in_transaction():
            raise ReservationError("a reservation is made only inside prepare_attempt's transaction")
        if not isinstance(snapshot_max_age, timedelta) or snapshot_max_age <= timedelta(0):
            raise ValueError("snapshot_max_age must be a positive timedelta")
        at = utc_text(now)
        self._check_fence(conn, fence_token, now)
        row = conn.execute("SELECT digest FROM intents WHERE intent_key = ?", (intent.intent_key,)).fetchone()
        if row is None or row[0] != intent.digest():
            raise ReservationRefused([f"INTENT_NOT_RECORDED: {intent.intent_key} with this digest"])
        held = conn.execute("SELECT reservation_id FROM reservations WHERE intent_key = ? AND state != 'RELEASED'",
                            (intent.intent_key,)).fetchone()
        if held is not None:
            raise ReservationRefused([f"INTENT_ALREADY_RESERVED: {held[0]} is still held"])
        decision = self._evaluate(conn, intent, now, snapshot_max_age=snapshot_max_age, candidate_id=reservation_id)
        if not decision.allowed:
            raise ReservationRefused(decision.reasons)
        conn.execute("INSERT INTO reservations (reservation_id, intent_key, scope_key, market_ticker, side, kind,"
                     " client_order_id, quantity, limit_price, filled_quantity, cash_worst_case, state, release_reason,"
                     " end_reason, ended_at_utc, quarantine_reason, fence_token, created_at_utc, updated_at_utc,"
                     " last_fill_at_utc)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '0', ?, 'OUTSTANDING', NULL, NULL, NULL, NULL, ?, ?, ?, NULL)",
                     (reservation_id, intent.intent_key, intent.scope.key(), intent.market_ticker, intent.side.value,
                      intent.kind.value, intent.client_order_id(), decimal_text(intent.quantity),
                      decimal_text(intent.limit_price), decimal_text(intent.max_total_cost), fence_token, at, at))
        self._store._audit(conn, at=at, kind="RESERVATION_CREATED", subject=reservation_id,
                           body={"intent_key": intent.intent_key, "intent_digest": intent.digest(),
                                 "fence_token": fence_token, "kind": intent.kind,
                                 "cash_worst_case": intent.max_total_cost, "quantity": intent.quantity,
                                 "snapshot_revision": decision.snapshot_revision,
                                 "cash_required": decision.cash_required, "cash_available": decision.cash_available,
                                 "inventory_available": decision.inventory_available})
        return self._view(conn, reservation_id)

    def _evaluate(self, conn: sqlite3.Connection, intent: OrderIntent, now: datetime, *,
                  snapshot_max_age: timedelta, candidate_id: str) -> ReservationDecision:
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        scope_key = intent.scope.key()
        snap = self._snapshot(conn, scope_key)
        if snap is None:
            return ReservationDecision(False, ("NO_ACCOUNT_SNAPSHOT: account state is unknown; no new risk",),
                                       None, None, None, None)
        reasons: list[str] = []
        state = freshness.assess(snap.observed_at_utc, max_age=snapshot_max_age, now=now)
        if state is not freshness.Freshness.FRESH:
            reasons.append(f"SNAPSHOT_{state.value.upper()}: revision {snap.revision} observed {snap.observed_at_utc}")
        if not snap.consistent:
            reasons.append(f"SNAPSHOT_INCONSISTENT: revision {snap.revision}: {list(snap.problems)}")
        if snap.cash_basis is CashBasis.UNKNOWN:
            reasons.append("CASH_BASIS_UNKNOWN: the snapshot does not say what its cash means")
        held = self._held(conn, scope_key, snap)

        with _exact():
            # Cash: every held obligation binds at once (the canonical owner decides).
            obligations: list[Obligation] = []
            for r in held:
                worst: Decimal | None = r.cash_worst_case
                if r.quarantine_reason is not None:
                    worst = None  # its exposure is in question: unknown, never the old number
                elif r.provider_held:
                    worst = snap.attributed[r.reservation_id].unreflected_cash
                worst = None if worst is not None and worst < 0 else worst  # a negative residual is not known
                obligations.append(Obligation(f"local:{r.reservation_id}", r.state, worst,
                                              (f"{r.market_ticker}:{r.side.value}",)))
            if snap.external_orders is None:
                obligations.append(Obligation("external:unlisted", ObligationState.UNKNOWN, None))
                reasons.append("EXTERNAL_ORDERS_UNKNOWN: the snapshot does not list open orders")
            else:
                for n, e in enumerate(snap.external_orders):  # the index keeps ids unique even if a ref repeats
                    keys = (f"{e.market_ticker}:{e.side.value}",) if e.market_ticker and e.side else ()
                    worst = None if e.unreflected_cash is not None and e.unreflected_cash < 0 else e.unreflected_cash
                    obligations.append(Obligation(f"external:{n}:{e.order_ref}", ObligationState.OUTSTANDING, worst,
                                                  keys))
            candidate = Obligation(f"candidate:{candidate_id}", ObligationState.OUTSTANDING, intent.max_total_cost,
                                   (f"{intent.market_ticker}:{intent.side.value}",))
            cash = snap.usable_cash()
            result = reserve_simultaneous_obligations(tuple(obligations), available_cash=cash, candidate=candidate)
            if not result.new_risk_allowed:
                reasons.extend(result.reasons)
                if not result.reasons:
                    reasons.append("NEW_RISK_NOT_ALLOWED")

            # Inventory: a REDUCTION sells only what the snapshot shows is held and not already being sold.
            inventory: Decimal | None = None
            if intent.kind is IntentKind.REDUCTION:
                inventory, why = self._inventory(snap, held, intent.market_ticker, intent.side)
                if why:
                    reasons.append(why)
                elif intent.quantity > inventory:  # type: ignore[operator]
                    reasons.append(f"INSUFFICIENT_INVENTORY: selling {intent.quantity} {intent.market_ticker} "
                                   f"{intent.side.value} > {inventory} held and not already reserved")
        return ReservationDecision(not reasons, tuple(reasons), snap.revision, result.required, cash, inventory)

    @staticmethod
    def _inventory(snap: AccountSnapshot, held: list[ReservationView], market_ticker: str,
                   side: Side) -> tuple[Decimal | None, str | None]:
        """Call inside `_exact()`."""
        if snap.positions is None:
            return None, "POSITIONS_UNKNOWN: the snapshot does not list positions"
        if snap.external_orders is None:
            return None, "EXTERNAL_ORDERS_UNKNOWN: open sells cannot be excluded"
        # A complete positions listing that omits this key reports no position: that is known, not missing.
        available = snap.positions.get((market_ticker, side), Decimal(0))
        for r in held:
            if r.kind is IntentKind.REDUCTION and r.market_ticker == market_ticker and r.side is side:
                if r.quarantine_reason is not None:
                    return None, f"INVENTORY_UNKNOWN: local reduction {r.reservation_id} is quarantined"
                available -= r.quantity  # full size: unfilled remainder plus fills no snapshot confirms yet
        for e in snap.external_orders:
            if e.could_sell(market_ticker, side):
                if e.remaining_quantity is None or e.remaining_quantity < 0:
                    return None, f"INVENTORY_UNKNOWN: external order {e.order_ref} may sell an unknown quantity"
                available -= e.remaining_quantity
        return available, None

    # ------------------------------------------------------------------ lifecycle (release only on confirmed outcomes)

    def request_cancel(self, reservation_id: str, now: datetime) -> ReservationView:
        """A cancel was requested. Nothing is released: a request is not a confirmation."""
        at = utc_text(now)
        with self._store._transaction() as conn:
            r = self._view(conn, reservation_id)
            self._set_state(conn, r, ObligationState.CANCEL_REQUESTED, at, extra={"event": "CANCEL_REQUESTED"})
            return self._view(conn, reservation_id)

    def mark_open(self, reservation_id: str, now: datetime, *, receipt_id: str) -> ReservationView:
        """The venue shows the order open (a cancel was refused, or an unknown state was reconciled)."""
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id, kinds=(ReceiptKind.ORDER_LOOKUP, ReceiptKind.CANCEL_REJECT),
                                         attempt_id=reservation_id)
            r = self._view(conn, reservation_id)
            self._set_state(conn, r, ObligationState.OUTSTANDING, at,
                            extra={"event": "OPEN_CONFIRMED", "receipt_id": receipt_id})
            return self._view(conn, reservation_id)

    def mark_unknown(self, reservation_id: str, now: datetime, *, reason: str) -> ReservationView:
        """The order's state was lost (a cancel answer never came, a stream gap). It stays reserved."""
        at = utc_text(now)
        with self._store._transaction() as conn:
            r = self._view(conn, reservation_id)
            self._set_state(conn, r, ObligationState.UNKNOWN, at, extra={"event": "STATE_UNKNOWN", "reason": reason})
            return self._view(conn, reservation_id)

    def confirm_cancel(self, reservation_id: str, now: datetime, *, receipt_id: str,
                       venue_filled: Decimal) -> ReservationView:
        """The venue confirmed the cancel, reporting `venue_filled` contracts filled in total. The order is
        over, but nothing is released yet: it is BOUND, held in full, until `confirm_by_snapshot` (a fill
        may still arrive). A `venue_filled` below the recorded fills, or above the order, quarantines it."""
        return self._end(reservation_id, EndReason.CANCEL_CONFIRMED, now, receipt_id=receipt_id,
                         venue_filled=venue_filled,
                         kinds=(ReceiptKind.CANCEL_CONFIRM, ReceiptKind.ORDER_LOOKUP))

    def mark_expired(self, reservation_id: str, now: datetime, *, receipt_id: str,
                     venue_filled: Decimal) -> ReservationView:
        """The venue reports the order expired, with `venue_filled` contracts filled in total. As
        `confirm_cancel`: BOUND until a later snapshot confirms it."""
        return self._end(reservation_id, EndReason.EXPIRED, now, receipt_id=receipt_id, venue_filled=venue_filled,
                         kinds=(ReceiptKind.ORDER_EXPIRED, ReceiptKind.ORDER_LOOKUP))

    def record_fill(self, reservation_id: str, cumulative_filled: Decimal, now: datetime, *,
                    receipt_id: str) -> ReservationView:
        """The venue reports `cumulative_filled` contracts filled in total. Always recorded, in any state:
        - a larger total updates the reservation (a complete fill makes it BOUND); a late fill on a BOUND
          reservation moves its release point later;
        - the same total again is idempotent;
        - a total that shrinks, exceeds the order, or arrives after release quarantines it.
        Nothing is released by a fill."""
        filled = exact_decimal(cumulative_filled, name="cumulative_filled")
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id, kinds=(ReceiptKind.FILL, ReceiptKind.ORDER_LOOKUP),
                                         attempt_id=reservation_id)
            r = self._view(conn, reservation_id)
            with _exact(InvalidTransition):
                if filled == r.filled_quantity:
                    return r
                contradiction = None
                if filled < r.filled_quantity or filled < 0:
                    contradiction = f"FILL_SHRANK: venue total {filled} < recorded {r.filled_quantity}"
                elif filled > r.quantity:
                    contradiction = f"FILL_EXCEEDS_ORDER: venue total {filled} > order {r.quantity}"
                elif r.state is ObligationState.RELEASED:
                    contradiction = f"FILL_AFTER_RELEASE: venue total {filled} after {r.release_reason}"
                if contradiction is not None or r.quarantine_reason is not None:
                    self._quarantine(conn, r, contradiction or r.quarantine_reason, at,  # type: ignore[arg-type]
                                     extra={"reported_filled": filled, "receipt_id": receipt_id})
                    return self._view(conn, reservation_id)
                complete = filled == r.quantity
            ended = r.state is ObligationState.BOUND
            new_state = ObligationState.BOUND if complete or ended else r.state
            end_reason = r.end_reason if ended else (EndReason.FILLED if complete else None)
            conn.execute("UPDATE reservations SET filled_quantity = ?, state = ?, end_reason = ?, ended_at_utc = ?,"
                         " last_fill_at_utc = ?, updated_at_utc = ? WHERE reservation_id = ?",
                         (decimal_text(filled), new_state.value, end_reason.value if end_reason else None,
                          r.ended_at_utc if ended else (at if complete else None), at, at, reservation_id))
            self._store._audit(conn, at=at, kind="RESERVATION_FILL", subject=reservation_id,
                               body={"cumulative_filled": filled, "from": r.state, "to": new_state,
                                     "late": ended, "receipt_id": receipt_id})
            return self._view(conn, reservation_id)

    def confirm_by_snapshot(self, reservation_id: str, snapshot_revision: int, now: datetime) -> ReservationView:
        """BOUND → RELEASED once snapshot `snapshot_revision` shows the result: consistent, observed strictly
        after the order's end and its last fill, and no longer listing the order as open. The caller
        has checked that its position reflects the fills. Released as CONVERTED_TO_POSITION when anything
        filled, otherwise as the cancel or expiry it was."""
        at = utc_text(now)
        with self._store._transaction() as conn:
            r = self._view(conn, reservation_id)
            if r.state is not ObligationState.BOUND or r.quarantine_reason is not None:
                raise InvalidTransition(f"{reservation_id} is {r.state.value}"
                                        f"{' (quarantined)' if r.quarantine_reason else ''}, not BOUND")
            snap = self._snapshot(conn, r.scope_key, revision=snapshot_revision)
            if snap is None or not snap.consistent:
                raise InvalidTransition(f"snapshot {r.scope_key}#{snapshot_revision} is missing or inconsistent")
            point = _later(r.ended_at_utc, r.last_fill_at_utc)
            if point is None or parse_utc_text(snap.observed_at_utc) <= point:  # strictly after: the same instant
                raise InvalidTransition(f"snapshot {snapshot_revision} was observed before the order's end or last "
                                        "fill (it must be strictly later)")
            if reservation_id in snap.attributed or snap.lists_client_order(r.client_order_id):
                raise InvalidTransition(f"snapshot {snapshot_revision} still lists {reservation_id} as open")
            if r.filled_quantity > 0:
                reason = ReleaseReason.CONVERTED_TO_POSITION
            else:
                reason = ReleaseReason(r.end_reason.value)  # type: ignore[union-attr]
            self._set_state(conn, r, ObligationState.RELEASED, at, release=reason,
                            extra={"snapshot_revision": snapshot_revision})
            return self._view(conn, reservation_id)

    def resolve_quarantine(self, reservation_id: str, now: datetime, *, receipt_id: str,
                           venue_filled: Decimal) -> ReservationView:
        """Record the venue's answer to a quarantine (an order lookup): its cumulative filled quantity. The
        reservation stays UNKNOWN and held; the normal lifecycle then continues from what the venue shows.

        The venue's answer is authoritative even when it is below the recorded fills (a busted trade). It is
        accepted, never silently: the event records `fills_reduced_from`. Nothing is released by it, and the
        reservation's worst case stays the full `max_total_cost`."""
        filled = exact_decimal(venue_filled, name="venue_filled")
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id, kinds=(ReceiptKind.ORDER_LOOKUP,), attempt_id=reservation_id)
            r = self._view(conn, reservation_id)
            if r.quarantine_reason is None:
                raise InvalidTransition(f"{reservation_id} is not quarantined")
            if filled < 0 or filled > r.quantity:
                raise InvalidTransition(f"venue_filled {filled} is outside [0, {r.quantity}]")
            conn.execute("UPDATE reservations SET quarantine_reason = NULL, filled_quantity = ?, last_fill_at_utc = ?,"
                         " updated_at_utc = ? WHERE reservation_id = ?",
                         (decimal_text(filled), at if filled != r.filled_quantity else r.last_fill_at_utc, at,
                          reservation_id))
            with localcontext(_exact_context()):
                reduced = filled < r.filled_quantity
            self._store._audit(conn, at=at, kind="RESERVATION_RESOLVED", subject=reservation_id,
                               body={"from": r.state, "to": r.state, "venue_filled": filled, "receipt_id": receipt_id,
                                     "was": r.quarantine_reason,
                                     "fills_reduced_from": r.filled_quantity if reduced else None})
            return self._view(conn, reservation_id)

    def reservation(self, reservation_id: str) -> ReservationView:
        with self._store._reading() as conn:
            return self._view(conn, reservation_id)

    def held_reservations(self, scope: AccountScope) -> list[ReservationView]:
        with self._store._reading() as conn:
            return self._held(conn, scope.key(), self._snapshot(conn, scope.key()))

    def _end(self, reservation_id: str, reason: EndReason, now: datetime, *, receipt_id: str, venue_filled: Decimal,
             kinds: tuple[ReceiptKind, ...]) -> ReservationView:
        filled = exact_decimal(venue_filled, name="venue_filled")
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id, kinds=kinds, attempt_id=reservation_id)
            r = self._view(conn, reservation_id)
            with _exact(InvalidTransition):
                contradiction = None
                if filled < r.filled_quantity or filled < 0:
                    contradiction = f"END_FILL_SHRANK: venue total {filled} < recorded {r.filled_quantity}"
                elif filled > r.quantity:
                    contradiction = f"END_FILL_EXCEEDS_ORDER: venue total {filled} > order {r.quantity}"
                elif r.state is ObligationState.RELEASED and filled > 0:
                    contradiction = f"END_FILL_AFTER_RELEASE: venue total {filled} after {r.release_reason}"
            if contradiction is not None:
                self._quarantine(conn, r, contradiction, at, extra={"reported_filled": filled, "receipt_id": receipt_id,
                                                                    "ended": reason})
                return self._view(conn, reservation_id)
            grew = filled != r.filled_quantity
            if r.state is ObligationState.BOUND:  # already over: a repeat, or a later report with more fills
                if not grew:
                    return r
                conn.execute("UPDATE reservations SET filled_quantity = ?, last_fill_at_utc = ?, updated_at_utc = ?"
                             " WHERE reservation_id = ?", (decimal_text(filled), at, at, reservation_id))
                self._store._audit(conn, at=at, kind="RESERVATION_FILL", subject=reservation_id,
                                   body={"cumulative_filled": filled, "from": r.state, "to": r.state, "late": True,
                                         "receipt_id": receipt_id})
                return self._view(conn, reservation_id)
            if ObligationState.BOUND not in _TRANSITIONS[r.state]:
                raise InvalidTransition(f"{reservation_id}: {r.state.value} cannot end ({reason.value})")
            conn.execute("UPDATE reservations SET state = 'BOUND', end_reason = ?, ended_at_utc = ?, filled_quantity = ?,"
                         " last_fill_at_utc = ?, updated_at_utc = ? WHERE reservation_id = ?",
                         (reason.value, at, decimal_text(filled), at if grew else r.last_fill_at_utc, at,
                          reservation_id))
            self._store._audit(conn, at=at, kind="RESERVATION_STATE", subject=reservation_id,
                               body={"from": r.state, "to": ObligationState.BOUND, "ended": reason,
                                     "venue_filled": filled, "receipt_id": receipt_id})
            return self._view(conn, reservation_id)

    def _set_state(self, conn: sqlite3.Connection, r: ReservationView, new: ObligationState, at: str, *,
                   release: ReleaseReason | None = None, extra: dict | None = None) -> None:
        if new not in _TRANSITIONS[r.state]:
            raise InvalidTransition(f"{r.reservation_id}: {r.state.value} -> {new.value} is not allowed")
        if (new is ObligationState.RELEASED) != (release is not None):
            raise InvalidTransition("a release, and only a release, needs a reason")
        if new is ObligationState.RELEASED and (r.quarantine_reason is not None or r.filled_quantity > 0) \
                and release is not ReleaseReason.CONVERTED_TO_POSITION:
            raise InvalidTransition(f"{r.reservation_id} has fills or is quarantined; it cannot be {release.value}")
        conn.execute("UPDATE reservations SET state = ?, release_reason = ?, updated_at_utc = ? WHERE reservation_id = ?",
                     (new.value, release.value if release else None, at, r.reservation_id))
        self._store._audit(conn, at=at, kind="RESERVATION_STATE", subject=r.reservation_id,
                           body={"from": r.state, "to": new, "release_reason": release, **(extra or {})})

    def _quarantine(self, conn: sqlite3.Connection, r: ReservationView, reason: str, at: str, *,
                    extra: dict | None = None) -> None:
        """A contradiction: back to UNKNOWN (held, RELEASED included), worst case unknown until resolved."""
        conn.execute("UPDATE reservations SET state = 'UNKNOWN', release_reason = NULL, quarantine_reason = ?,"
                     " updated_at_utc = ? WHERE reservation_id = ?", (reason, at, r.reservation_id))
        self._store._audit(conn, at=at, kind="RESERVATION_QUARANTINED", subject=r.reservation_id,
                           body={"from": r.state, "to": ObligationState.UNKNOWN, "reason": reason, **(extra or {})})

    # ------------------------------------------------------------------ journal-driven changes (inside its transaction)

    def _attempt_unknown(self, conn: sqlite3.Connection, reservation_id: str, at: str) -> None:
        r = self._view(conn, reservation_id)
        if r.state is ObligationState.OUTSTANDING:
            self._set_state(conn, r, ObligationState.UNKNOWN, at, extra={"event": "ATTEMPT_OUTCOME_UNKNOWN"})

    def _attempt_acknowledged(self, conn: sqlite3.Connection, reservation_id: str, at: str) -> None:
        r = self._view(conn, reservation_id)
        if r.state is ObligationState.UNKNOWN and r.quarantine_reason is None:
            self._set_state(conn, r, ObligationState.OUTSTANDING, at, extra={"event": "ATTEMPT_ACKNOWLEDGED"})

    def _contradicts_never_placed(self, conn: sqlite3.Connection, reservation_id: str) -> str | None:
        """Why a REJECTED or ABSENT outcome contradicts what is recorded (fills, a quarantine), or None."""
        r = self._view(conn, reservation_id)
        if r.quarantine_reason is not None:
            return f"already quarantined: {r.quarantine_reason}"
        if r.filled_quantity > 0:
            return f"{r.filled_quantity} contracts were recorded as filled"
        return None

    def _quarantine_for_attempt(self, conn: sqlite3.Connection, reservation_id: str, reason: str, at: str, *,
                                receipt_id: str | None) -> None:
        self._quarantine(conn, self._view(conn, reservation_id), reason, at, extra={"receipt_id": receipt_id})

    def _attempt_never_placed(self, conn: sqlite3.Connection, reservation_id: str, reason: ReleaseReason,
                              at: str) -> None:
        """REJECTED or ABSENT: no order ever existed, so nothing can have filled. Released at once. The journal
        checks `_contradicts_never_placed` first and quarantines instead; this guard is a backstop."""
        r = self._view(conn, reservation_id)
        if r.filled_quantity > 0 or r.quarantine_reason is not None:
            raise InvalidTransition(f"{reservation_id} has fills or is quarantined; it cannot be {reason.value}")
        self._set_state(conn, r, ObligationState.RELEASED, at, release=reason)

    def _listed_open(self, conn: sqlite3.Connection, reservation_id: str) -> bool:
        """Whether the latest snapshot lists this reservation's order (or its client order id) as open."""
        r = self._view(conn, reservation_id)
        snap = self._snapshot(conn, r.scope_key)
        return snap is not None and (reservation_id in snap.attributed or snap.lists_client_order(r.client_order_id))

    # ------------------------------------------------------------------ reads

    _COLUMNS = ("reservation_id, intent_key, scope_key, market_ticker, side, kind, client_order_id, quantity,"
                " limit_price, filled_quantity, cash_worst_case, state, release_reason, end_reason, ended_at_utc,"
                " quarantine_reason, fence_token, created_at_utc, updated_at_utc, last_fill_at_utc")

    def _held(self, conn: sqlite3.Connection, scope_key: str, snap: AccountSnapshot | None) -> list[ReservationView]:
        attributed = snap.attributed if snap is not None else {}
        rows = conn.execute(f"SELECT {self._COLUMNS} FROM reservations WHERE scope_key = ? AND state != 'RELEASED'"
                            " ORDER BY reservation_id", (scope_key,)).fetchall()
        return [self._decode(row, attributed) for row in rows]

    def _view(self, conn: sqlite3.Connection, reservation_id: str) -> ReservationView:
        row = conn.execute(f"SELECT {self._COLUMNS} FROM reservations WHERE reservation_id = ?",
                           (reservation_id,)).fetchone()
        if row is None:
            raise InvalidTransition(f"no reservation {reservation_id!r}")
        snap = self._snapshot(conn, row[2])
        return self._decode(row, snap.attributed if snap is not None else {})

    @staticmethod
    def _decode(row: tuple, attributed: Mapping[str, AttributedOrder]) -> ReservationView:
        try:
            state = ObligationState(row[11])
            quantity, filled = _req_dec(row[7], name="quantity"), _req_dec(row[9], name="filled_quantity")
            listing = attributed.get(row[0])
            with localcontext(_exact_context()):
                held = (state is not ObligationState.RELEASED and listing is not None
                        and listing.remaining_quantity == quantity - filled)
            return ReservationView(
                reservation_id=row[0], intent_key=row[1], scope_key=row[2], market_ticker=row[3], side=Side(row[4]),
                kind=IntentKind(row[5]), client_order_id=row[6], quantity=quantity,
                limit_price=_req_dec(row[8], name="limit_price"), filled_quantity=filled,
                cash_worst_case=_req_dec(row[10], name="cash_worst_case"), state=state,
                release_reason=None if row[12] is None else ReleaseReason(row[12]),
                end_reason=None if row[13] is None else EndReason(row[13]), ended_at_utc=row[14],
                quarantine_reason=row[15], fence_token=int(row[16]), created_at_utc=row[17], updated_at_utc=row[18],
                last_fill_at_utc=row[19],
                provider_held=held)
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise CorruptRecord(f"reservation {row[0]!r} does not decode: {exc}") from exc
