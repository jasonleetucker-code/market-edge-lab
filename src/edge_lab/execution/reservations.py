"""Atomic cash and inventory reservations with fencing (#160 package E, ADR 0043). Offline.

`ReservationAuthority` lives in the execution journal's SQLite store and runs inside the journal's
transactions (`BEGIN IMMEDIATE`). A reservation and the PENDING_EGRESS attempt it backs therefore
commit together or not at all, and two processes can never both spend the same capacity: the
second transaction waits for the write lock and then sees the first one's reservation.

**Arithmetic has one owner.** Cash capacity is decided by
`execution_ticket.reserve_simultaneous_obligations`. This module only builds its `Obligation`s:
- every held local reservation (any state but RELEASED);
- every external open order in the latest account snapshot;
- the candidate.

Cash worst cases:
- ENTRY and REDUCTION: `intent.max_total_cost` (for a REDUCTION that is its fee bound);
- a local order the venue lists as open in the latest snapshot (provider-held): the venue already holds its
  cash, so only the residual the snapshot reports (`AttributedOrder.unreflected_cash`) counts. A local
  reservation the snapshot does not list is local-only and counts in full, so nothing is spent twice;
- an external order: its `unreflected_cash`; None is unknown and blocks new risk.

Inventory (REDUCTION only, keyed by `(market_ticker, side)`, never netted across markets or sides):
`quantity <= position - every held local reduction - every external open sell`. An external order whose
market, side or action is unknown counts against every key it could touch. Exact equality is allowed.

**Missing is not zero.** No snapshot, a stale or inconsistent snapshot, UNKNOWN cash basis, unknown cash,
unknown positions, unknown external orders or an unknown worst case all mean no new risk.

**Release only on confirmed outcomes** (states mirror `ObligationState`):
- OUTSTANDING: prepared, sent or acknowledged;
- CANCEL_REQUESTED: still held, because a request is not a confirmation;
- UNKNOWN: still held until reconciled;
- BOUND: filled, or cancelled/expired after a partial fill, but no snapshot yet confirms the position. Still
  held: the venue cash or position in the latest snapshot may not reflect the fill;
- RELEASED: cancel confirmed, rejected, expired, absent at the venue, or converted to a position.
  Terminal. A reservation with any fill goes to BOUND, never straight to RELEASED.

**Fencing.** One egress lease per store. `acquire_lease` returns a strictly increasing fence token and
refuses while another worker's lease is unexpired. A takeover does not prove the old worker stopped, so
every PENDING_EGRESS or SENT attempt of an older fence becomes OUTCOME_UNKNOWN and keeps its reservation.
`reserve` (and so `prepare_attempt`) checks the token inside its transaction: a stale token is refused
before anything is committed. The lease clock is the caller's `now`.

Schema (part of journal schema version 1; money and quantities are canonical Decimal text, never REAL):
- `egress_lease(lease_name PK, worker_id, fence_token, acquired_at_utc, expires_at_utc)`: one row.
- `account_snapshots(scope_key, revision, observed_at_utc, recorded_at_utc, cash, cash_basis,
  positions_json, external_orders_json, attributed_json, consistent, problems_json)`: append-only,
  revisions strictly increasing per scope. NULL means unknown.
- `reservations(reservation_id PK, intent_key FK, scope_key, market_ticker, side, kind, client_order_id,
  quantity, filled_quantity, cash_worst_case, state, release_reason, fence_token, created_at_utc,
  updated_at_utc, last_fill_at_utc)`: a mutable projection; every change is a hash-chained journal event.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, ContextManager, Iterable, Mapping, Protocol

from .. import freshness
from ..execution_ticket import Obligation, ObligationState, reserve_simultaneous_obligations
from .model import (AccountScope, Action, ExactValueError, IntentKind, OrderIntent, Side, canonical_json,
                    decimal_text, exact_decimal, parse_utc_text, utc_text)

EGRESS_LEASE = "egress"

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
CREATE TRIGGER account_snapshots_no_update BEFORE UPDATE ON account_snapshots
    BEGIN SELECT RAISE(ABORT, 'account_snapshots is append-only'); END;
CREATE TRIGGER account_snapshots_no_remove BEFORE DELETE ON account_snapshots
    BEGIN SELECT RAISE(ABORT, 'account_snapshots is append-only'); END;
CREATE TABLE reservations (
    reservation_id TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL REFERENCES intents(intent_key),
    scope_key TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('yes', 'no')),
    kind TEXT NOT NULL CHECK (kind IN ('ENTRY', 'REDUCTION')),
    client_order_id TEXT NOT NULL,
    quantity TEXT NOT NULL,
    filled_quantity TEXT NOT NULL,
    cash_worst_case TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('OUTSTANDING', 'CANCEL_REQUESTED', 'UNKNOWN', 'BOUND', 'RELEASED')),
    release_reason TEXT,
    fence_token INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    last_fill_at_utc TEXT
);
CREATE INDEX reservations_held ON reservations(scope_key, state);
"""


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
    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ABSENT_AT_VENUE = "ABSENT_AT_VENUE"  # reconciliation found no such order: it never existed
    CONVERTED_TO_POSITION = "CONVERTED_TO_POSITION"


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
    """The snapshot cannot be recorded (a revision that does not increase)."""


class InvalidTransition(ReservationError):
    """A state change that the state machine or the evidence does not allow."""


class CorruptRecord(ValueError):
    """A stored value that does not decode. The journal maps it to JournalCorrupt."""


class _Store(Protocol):
    """What the authority needs from the journal that owns the store."""

    def _transaction(self) -> ContextManager[sqlite3.Connection]: ...

    def _reading(self) -> ContextManager[sqlite3.Connection]: ...

    def _audit(self, conn: sqlite3.Connection, *, at: str, kind: str, subject: str, body: dict) -> None: ...

    def _require_receipt(self, conn: sqlite3.Connection, receipt_id: str) -> None: ...

    def _quarantine_superseded_fences(self, conn: sqlite3.Connection, *, live_token: int | None,
                                      at: str) -> list[str]: ...


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
    """A local attempt's order that the venue lists as open in this snapshot (matched by client order id).
    Its cash is already held by the venue. `unreflected_cash` is any residual the venue does not hold
    (None: unknown, which blocks new risk)."""

    client_order_id: str
    unreflected_cash: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.client_order_id, str) or not self.client_order_id:
            raise ValueError("client_order_id is required")
        if self.unreflected_cash is not None:
            object.__setattr__(self, "unreflected_cash", exact_decimal(self.unreflected_cash, name="unreflected_cash"))


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
    attributed: Mapping[str, Decimal | None]
    consistent: bool
    problems: tuple[str, ...]

    def usable_cash(self) -> Decimal | None:
        """The spendable cash, or None when its basis or value is unknown."""
        return self.cash if self.cash_basis is CashBasis.AVAILABLE_AFTER_VENUE_HOLDS else None


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
    filled_quantity: Decimal
    cash_worst_case: Decimal
    state: ObligationState
    release_reason: ReleaseReason | None
    fence_token: int
    created_at_utc: str
    updated_at_utc: str
    last_fill_at_utc: str | None
    provider_held: bool  # the latest snapshot lists this order as open: the venue holds its cash


@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reasons: tuple[str, ...]
    snapshot_revision: int | None
    cash_required: Decimal | None  # every held obligation plus the candidate, if all bind at once
    cash_available: Decimal | None
    inventory_available: Decimal | None  # REDUCTION only


_TRANSITIONS: dict[ObligationState, frozenset[ObligationState]] = {
    ObligationState.OUTSTANDING: frozenset({ObligationState.CANCEL_REQUESTED, ObligationState.UNKNOWN,
                                            ObligationState.BOUND, ObligationState.RELEASED}),
    ObligationState.CANCEL_REQUESTED: frozenset({ObligationState.OUTSTANDING, ObligationState.UNKNOWN,
                                                 ObligationState.BOUND, ObligationState.RELEASED}),
    ObligationState.UNKNOWN: frozenset({ObligationState.OUTSTANDING, ObligationState.CANCEL_REQUESTED,
                                        ObligationState.BOUND, ObligationState.RELEASED}),
    ObligationState.BOUND: frozenset({ObligationState.RELEASED}),
    ObligationState.RELEASED: frozenset(),
}


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
                               body={"worker_id": worker_id, "fence_token": token, "expires_at_utc": expires,
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
                               body={"worker_id": worker_id, "fence_token": fence_token, "expires_at_utc": expires})

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

        Revisions strictly increase per scope; an older or equal one raises SnapshotRefused. None for
        cash, positions or external orders is unknown, never zero or flat. A snapshot that contradicts
        itself or the journal (negative cash or quantities, an attributed order with no held local
        reservation, time going backwards) is recorded as evidence but marked inconsistent, and an
        inconsistent latest snapshot allows no new risk."""
        if not isinstance(scope, AccountScope):
            raise ValueError("scope must be an AccountScope")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("revision must be a positive int")
        if not isinstance(cash_basis, CashBasis):
            raise ValueError("cash_basis must be a CashBasis")
        observed = utc_text(observed_at)
        at = utc_text(now)
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
            latest = self._latest_snapshot(conn, scope.key())
            if latest is not None and revision <= latest.revision:
                raise SnapshotRefused(f"revision {revision} does not increase on {latest.revision} for {scope.key()}")
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
            ids = [a.client_order_id for a in attributed]
            if len(ids) != len(set(ids)):
                problems.append("DUPLICATE_ATTRIBUTED_ORDER")
            held_ids = {r[0] for r in conn.execute(
                "SELECT client_order_id FROM reservations WHERE scope_key = ? AND state != 'RELEASED'",
                (scope.key(),))}
            for a in attributed:
                if a.client_order_id not in held_ids:
                    problems.append(f"ATTRIBUTION_UNKNOWN: {a.client_order_id} has no held local reservation")
                if a.unreflected_cash is not None and a.unreflected_cash < 0:
                    problems.append(f"NEGATIVE_ATTRIBUTED_CASH: {a.client_order_id}")
            positions_json = None if pos is None else canonical_json(
                sorted([t, s.value, decimal_text(q)] for (t, s), q in pos.items()))
            externals_json = None if externals is None else canonical_json(
                sorted((e.to_dict() for e in externals), key=lambda d: d["order_ref"]))
            attributed_json = canonical_json(sorted(
                ({"client_order_id": a.client_order_id, "unreflected_cash": a.unreflected_cash} for a in attributed),
                key=lambda d: d["client_order_id"]))
            conn.execute("INSERT INTO account_snapshots (scope_key, revision, observed_at_utc, recorded_at_utc, cash,"
                         " cash_basis, positions_json, external_orders_json, attributed_json, consistent, problems_json)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (scope.key(), revision, observed, at, _opt_text(cash), cash_basis.value, positions_json,
                          externals_json, attributed_json, 0 if problems else 1, canonical_json(problems)))
            self._store._audit(conn, at=at, kind="SNAPSHOT_RECORDED", subject=f"{scope.key()}#{revision}",
                               body={"observed_at_utc": observed, "cash": cash, "cash_basis": cash_basis,
                                     "positions_known": pos is not None, "externals_known": externals is not None,
                                     "consistent": not problems, "problems": problems})
            return self._latest_snapshot(conn, scope.key())  # type: ignore[return-value]

    def latest_snapshot(self, scope: AccountScope) -> AccountSnapshot | None:
        with self._store._reading() as conn:
            return self._latest_snapshot(conn, scope.key())

    def _latest_snapshot(self, conn: sqlite3.Connection, scope_key: str,
                         revision: int | None = None) -> AccountSnapshot | None:
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
            attributed = {d["client_order_id"]: _dec(d["unreflected_cash"], name="unreflected_cash")
                          for d in json.loads(row[8])}
            return AccountSnapshot(row[0], int(row[1]), row[2], row[3], _dec(row[4], name="cash"),
                                   CashBasis(row[5]), positions, externals, attributed, bool(row[9]),
                                   tuple(json.loads(row[10])))
        except (ValueError, KeyError, TypeError) as exc:
            raise CorruptRecord(f"account snapshot {scope_key}#{row[1]} does not decode: {exc}") from exc

    # ------------------------------------------------------------------ reserving

    def evaluate(self, intent: OrderIntent, now: datetime, *, snapshot_max_age: timedelta) -> ReservationDecision:
        """Whether `intent` would fit now. Read-only: it reserves nothing."""
        with self._store._reading() as conn:
            return self._evaluate(conn, intent, now, snapshot_max_age=snapshot_max_age, candidate_id="candidate")

    def reserve(self, intent: OrderIntent, fence_token: int, now: datetime, *, snapshot_max_age: timedelta,
                reservation_id: str | None = None) -> ReservationView:
        """Reserve `intent`'s cash worst case (and, for a REDUCTION, its inventory) under the current fence.

        Inside `prepare_attempt` this runs in the journal's transaction, so the reservation commits with
        the attempt. Raises StaleFence or ReservationRefused, and then nothing is committed."""
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        if not isinstance(snapshot_max_age, timedelta) or snapshot_max_age <= timedelta(0):
            raise ValueError("snapshot_max_age must be a positive timedelta")
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._check_fence(conn, fence_token, now)
            row = conn.execute("SELECT digest FROM intents WHERE intent_key = ?", (intent.intent_key,)).fetchone()
            if row is None or row[0] != intent.digest():
                raise ReservationRefused([f"INTENT_NOT_RECORDED: {intent.intent_key} with this digest"])
            held = conn.execute("SELECT reservation_id FROM reservations WHERE intent_key = ? AND state != 'RELEASED'",
                                (intent.intent_key,)).fetchone()
            if held is not None:
                raise ReservationRefused([f"INTENT_ALREADY_RESERVED: {held[0]} is still held"])
            if reservation_id is None:
                count = conn.execute("SELECT COUNT(*) FROM reservations WHERE intent_key = ?",
                                     (intent.intent_key,)).fetchone()[0]
                reservation_id = f"res-{intent.digest()[:16]}-{count + 1}"
            decision = self._evaluate(conn, intent, now, snapshot_max_age=snapshot_max_age,
                                      candidate_id=reservation_id)
            if not decision.allowed:
                raise ReservationRefused(decision.reasons)
            conn.execute("INSERT INTO reservations (reservation_id, intent_key, scope_key, market_ticker, side, kind,"
                         " client_order_id, quantity, filled_quantity, cash_worst_case, state, release_reason,"
                         " fence_token, created_at_utc, updated_at_utc, last_fill_at_utc)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '0', ?, 'OUTSTANDING', NULL, ?, ?, ?, NULL)",
                         (reservation_id, intent.intent_key, intent.scope.key(), intent.market_ticker,
                          intent.side.value, intent.kind.value, intent.client_order_id(),
                          decimal_text(intent.quantity), decimal_text(intent.max_total_cost), fence_token, at, at))
            self._store._audit(conn, at=at, kind="RESERVATION_CREATED", subject=reservation_id,
                               body={"intent_key": intent.intent_key, "intent_digest": intent.digest(),
                                     "fence_token": fence_token, "kind": intent.kind,
                                     "cash_worst_case": intent.max_total_cost, "quantity": intent.quantity,
                                     "snapshot_revision": decision.snapshot_revision,
                                     "cash_required": decision.cash_required,
                                     "cash_available": decision.cash_available,
                                     "inventory_available": decision.inventory_available})
            return self._view(conn, reservation_id)

    def _evaluate(self, conn: sqlite3.Connection, intent: OrderIntent, now: datetime, *,
                  snapshot_max_age: timedelta, candidate_id: str) -> ReservationDecision:
        scope_key = intent.scope.key()
        snap = self._latest_snapshot(conn, scope_key)
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
        held = self._held(conn, scope_key)

        # Cash: every held obligation binds at once (the canonical owner decides).
        obligations: list[Obligation] = []
        for r in held:
            worst = snap.attributed[r.client_order_id] if r.client_order_id in snap.attributed else r.cash_worst_case
            worst = None if worst is not None and worst < 0 else worst  # a negative residual is not a known one
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
        if snap.positions is None:
            return None, "POSITIONS_UNKNOWN: the snapshot does not list positions"
        if snap.external_orders is None:
            return None, "EXTERNAL_ORDERS_UNKNOWN: open sells cannot be excluded"
        # A complete positions listing that omits this key reports no position: that is known, not missing.
        available = snap.positions.get((market_ticker, side), Decimal(0))
        for r in held:
            if r.kind is IntentKind.REDUCTION and r.market_ticker == market_ticker and r.side is side:
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
        return self._transition(reservation_id, ObligationState.CANCEL_REQUESTED, now, event="CANCEL_REQUESTED")

    def mark_open(self, reservation_id: str, now: datetime, *, receipt_id: str) -> ReservationView:
        """The venue shows the order open (a cancel was refused, or an unknown state was reconciled)."""
        return self._transition(reservation_id, ObligationState.OUTSTANDING, now, event="OPEN_CONFIRMED",
                                receipt_id=receipt_id)

    def mark_unknown(self, reservation_id: str, now: datetime, *, reason: str) -> ReservationView:
        """The order's state was lost (a cancel answer never came, a stream gap). It stays reserved."""
        return self._transition(reservation_id, ObligationState.UNKNOWN, now, event="STATE_UNKNOWN",
                                extra={"reason": reason})

    def confirm_cancel(self, reservation_id: str, now: datetime, *, receipt_id: str) -> ReservationView:
        """The venue confirmed the cancel: RELEASED, or BOUND when anything had filled."""
        return self._finish(reservation_id, ReleaseReason.CANCEL_CONFIRMED, now, receipt_id=receipt_id)

    def mark_expired(self, reservation_id: str, now: datetime, *, receipt_id: str) -> ReservationView:
        """The venue confirmed the order expired: RELEASED, or BOUND when anything had filled."""
        return self._finish(reservation_id, ReleaseReason.EXPIRED, now, receipt_id=receipt_id)

    def record_fill(self, reservation_id: str, cumulative_filled: Decimal, now: datetime, *,
                    receipt_id: str) -> ReservationView:
        """The venue reports `cumulative_filled` contracts filled in total. Nothing is released: a fill
        becomes a position, and only a later snapshot confirms the position
        (`confirm_converted_to_position`). A complete fill moves the reservation to BOUND."""
        filled = exact_decimal(cumulative_filled, name="cumulative_filled")
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id)
            r = self._view(conn, reservation_id)
            if filled < r.filled_quantity or filled > r.quantity:
                raise InvalidTransition(f"fill {filled} of {reservation_id} is outside [{r.filled_quantity}, "
                                        f"{r.quantity}] (fills only grow and never exceed the order)")
            if filled == r.filled_quantity:
                return r  # the same report again: idempotent
            if r.state in (ObligationState.RELEASED, ObligationState.BOUND):
                raise InvalidTransition(f"{reservation_id} is {r.state.value}; a new fill contradicts it")
            new_state = ObligationState.BOUND if filled == r.quantity else r.state
            conn.execute("UPDATE reservations SET filled_quantity = ?, state = ?, last_fill_at_utc = ?,"
                         " updated_at_utc = ? WHERE reservation_id = ?",
                         (decimal_text(filled), new_state.value, at, at, reservation_id))
            self._store._audit(conn, at=at, kind="RESERVATION_FILL", subject=reservation_id,
                               body={"cumulative_filled": filled, "from": r.state, "to": new_state,
                                     "receipt_id": receipt_id})
            return self._view(conn, reservation_id)

    def confirm_converted_to_position(self, reservation_id: str, snapshot_revision: int,
                                      now: datetime) -> ReservationView:
        """BOUND → RELEASED once snapshot `snapshot_revision`, observed no earlier than the last fill and
        consistent, shows the fill as a position (the caller has checked the position itself)."""
        at = utc_text(now)
        with self._store._transaction() as conn:
            r = self._view(conn, reservation_id)
            if r.state is not ObligationState.BOUND:
                raise InvalidTransition(f"{reservation_id} is {r.state.value}, not BOUND")
            snap = self._latest_snapshot(conn, r.scope_key, revision=snapshot_revision)
            if snap is None or not snap.consistent:
                raise InvalidTransition(f"snapshot {r.scope_key}#{snapshot_revision} is missing or inconsistent")
            if r.last_fill_at_utc is None or parse_utc_text(snap.observed_at_utc) < parse_utc_text(r.last_fill_at_utc):
                raise InvalidTransition(f"snapshot {snapshot_revision} was observed before the last fill")
            self._set_state(conn, r, ObligationState.RELEASED, at, release=ReleaseReason.CONVERTED_TO_POSITION,
                            extra={"snapshot_revision": snapshot_revision})
            return self._view(conn, reservation_id)

    def reservation(self, reservation_id: str) -> ReservationView:
        with self._store._reading() as conn:
            return self._view(conn, reservation_id)

    def held_reservations(self, scope: AccountScope) -> list[ReservationView]:
        with self._store._reading() as conn:
            return self._held(conn, scope.key())

    def _transition(self, reservation_id: str, new: ObligationState, now: datetime, *, event: str,
                    receipt_id: str | None = None, extra: dict | None = None) -> ReservationView:
        at = utc_text(now)
        with self._store._transaction() as conn:
            if receipt_id is not None:
                self._store._require_receipt(conn, receipt_id)
            r = self._view(conn, reservation_id)
            self._set_state(conn, r, new, at, extra={"event": event, "receipt_id": receipt_id, **(extra or {})})
            return self._view(conn, reservation_id)

    def _finish(self, reservation_id: str, reason: ReleaseReason, now: datetime, *, receipt_id: str) -> ReservationView:
        at = utc_text(now)
        with self._store._transaction() as conn:
            self._store._require_receipt(conn, receipt_id)
            r = self._view(conn, reservation_id)
            self._finish_in(conn, r, reason, at, extra={"receipt_id": receipt_id})
            return self._view(conn, reservation_id)

    def _finish_in(self, conn: sqlite3.Connection, r: ReservationView, reason: ReleaseReason, at: str, *,
                   extra: dict | None = None) -> None:
        """The order is over at the venue. With no fill it is RELEASED; with any fill it is BOUND until a
        snapshot confirms the position. A rejected or absent order cannot have filled."""
        if r.filled_quantity > 0:
            if reason in (ReleaseReason.REJECTED, ReleaseReason.ABSENT_AT_VENUE):
                raise InvalidTransition(f"{r.reservation_id} has fills; it cannot be {reason.value}")
            self._set_state(conn, r, ObligationState.BOUND, at, extra={"ended": reason, **(extra or {})})
        else:
            self._set_state(conn, r, ObligationState.RELEASED, at, release=reason, extra=extra)

    def _set_state(self, conn: sqlite3.Connection, r: ReservationView, new: ObligationState, at: str, *,
                   release: ReleaseReason | None = None, extra: dict | None = None) -> None:
        if new not in _TRANSITIONS[r.state]:
            raise InvalidTransition(f"{r.reservation_id}: {r.state.value} -> {new.value} is not allowed")
        if (new is ObligationState.RELEASED) != (release is not None):
            raise InvalidTransition("a release, and only a release, needs a reason")
        if r.state is ObligationState.BOUND and release is not ReleaseReason.CONVERTED_TO_POSITION:
            raise InvalidTransition(f"{r.reservation_id} is BOUND: only a confirmed position releases it")
        conn.execute("UPDATE reservations SET state = ?, release_reason = ?, updated_at_utc = ? WHERE reservation_id = ?",
                     (new.value, release.value if release else None, at, r.reservation_id))
        self._store._audit(conn, at=at, kind="RESERVATION_STATE", subject=r.reservation_id,
                           body={"from": r.state, "to": new, "release_reason": release, **(extra or {})})

    # ------------------------------------------------------------------ journal-driven changes (inside its transaction)

    def _attempt_unknown(self, conn: sqlite3.Connection, reservation_id: str, at: str) -> None:
        r = self._view(conn, reservation_id)
        if r.state is ObligationState.OUTSTANDING:
            self._set_state(conn, r, ObligationState.UNKNOWN, at, extra={"event": "ATTEMPT_OUTCOME_UNKNOWN"})

    def _attempt_acknowledged(self, conn: sqlite3.Connection, reservation_id: str, at: str) -> None:
        r = self._view(conn, reservation_id)
        if r.state is ObligationState.UNKNOWN:
            self._set_state(conn, r, ObligationState.OUTSTANDING, at, extra={"event": "ATTEMPT_ACKNOWLEDGED"})

    def _attempt_never_placed(self, conn: sqlite3.Connection, reservation_id: str, reason: ReleaseReason,
                              at: str) -> None:
        self._finish_in(conn, self._view(conn, reservation_id), reason, at)

    # ------------------------------------------------------------------ reads

    _COLUMNS = ("reservation_id, intent_key, scope_key, market_ticker, side, kind, client_order_id, quantity,"
                " filled_quantity, cash_worst_case, state, release_reason, fence_token, created_at_utc,"
                " updated_at_utc, last_fill_at_utc")

    def _held(self, conn: sqlite3.Connection, scope_key: str) -> list[ReservationView]:
        attributed = self._attributed(conn, scope_key)
        rows = conn.execute(f"SELECT {self._COLUMNS} FROM reservations WHERE scope_key = ? AND state != 'RELEASED'"
                            " ORDER BY reservation_id", (scope_key,)).fetchall()
        return [self._decode(row, attributed) for row in rows]

    def _view(self, conn: sqlite3.Connection, reservation_id: str) -> ReservationView:
        row = conn.execute(f"SELECT {self._COLUMNS} FROM reservations WHERE reservation_id = ?",
                           (reservation_id,)).fetchone()
        if row is None:
            raise InvalidTransition(f"no reservation {reservation_id!r}")
        return self._decode(row, self._attributed(conn, row[2]))

    def _attributed(self, conn: sqlite3.Connection, scope_key: str) -> frozenset[str]:
        snap = self._latest_snapshot(conn, scope_key)
        return frozenset(snap.attributed) if snap is not None else frozenset()

    @staticmethod
    def _decode(row: tuple, attributed: frozenset[str]) -> ReservationView:
        try:
            state = ObligationState(row[10])
            return ReservationView(
                reservation_id=row[0], intent_key=row[1], scope_key=row[2], market_ticker=row[3], side=Side(row[4]),
                kind=IntentKind(row[5]), client_order_id=row[6], quantity=_req_dec(row[7], name="quantity"),
                filled_quantity=_req_dec(row[8], name="filled_quantity"),
                cash_worst_case=_req_dec(row[9], name="cash_worst_case"), state=state,
                release_reason=None if row[11] is None else ReleaseReason(row[11]), fence_token=int(row[12]),
                created_at_utc=row[13], updated_at_utc=row[14], last_fill_at_utc=row[15],
                provider_held=state is not ObligationState.RELEASED and row[6] in attributed)
        except (ValueError, TypeError) as exc:
            raise CorruptRecord(f"reservation {row[0]!r} does not decode: {exc}") from exc
