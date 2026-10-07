"""The private, durable execution journal (#160 package D, ADR 0043). Offline: nothing here sends anything.

One SQLite file per executor, named `*.execution.sqlite3` so the research store can never be opened by
mistake. It is opened with WAL, `synchronous=FULL`, foreign keys on and a short `busy_timeout`, and it
refuses a store whose schema version is unknown or newer than this code.

**Write path.** Every write is one `BEGIN IMMEDIATE` transaction, so the read-check-write of a decision is
serialized across processes.
1. `prepare_attempt` commits all of the following together, before any network:
   - the fence check;
   - the intent (idempotent);
   - the check that no earlier attempt for the intent could still be live;
   - the consumed approval;
   - the reservation (`reservations.ReservationAuthority.reserve`);
   - a PENDING_EGRESS attempt row;
   - their audit events.

   If any part fails, nothing is committed and the caller must not send.
2. After the network call returns, or fails ambiguously, the caller records `mark_sent`, then one of
   `mark_acknowledged`, `mark_rejected` or `mark_outcome_unknown`.
3. `reconcile_attempt` resolves OUTCOME_UNKNOWN from a recorded receipt: ACKNOWLEDGED, REJECTED or ABSENT.

**Attempt states.**
- PENDING_EGRESS → SENT or OUTCOME_UNKNOWN.
- SENT → ACKNOWLEDGED, REJECTED or OUTCOME_UNKNOWN.
- OUTCOME_UNKNOWN → ACKNOWLEDGED, REJECTED or ABSENT, only through `reconcile_attempt`.

ACKNOWLEDGED, REJECTED and ABSENT are terminal. A new attempt for an intent is refused unless every
earlier attempt is REJECTED or ABSENT, meaning no order from it can exist. OUTCOME_UNKNOWN keeps its
reservation and blocks the intent until it is reconciled: there is no blind resubmission. On `recover`,
or when a lease is taken over, the PENDING_EGRESS and SENT attempts of every fence that is no longer
the live lease become OUTCOME_UNKNOWN, because nobody can know whether they were sent.

**Identity.**
- `intent_key` is the business identity and `digest` the content identity. The same key with a
  different digest raises IntentConflict and changes nothing.
- Creation time never deduplicates anything.
- `client_order_id` is derived from the intent and is the same on every attempt.

**Failures are loud.** A SQLite error raises:
- JournalBusy for a lock timeout;
- JournalCorrupt for a record that does not decode or a damaged file;
- UnknownSchema for a wrong store or version;
- JournalUnavailable for anything else, such as a full disk.

Nothing is swallowed and a failed transaction is rolled back whole.

Schema version 1. Money and quantities are canonical Decimal text, and times are ISO-8601 UTC text.
- `schema_meta(key PK, value)`: `store_kind`, `schema_version`.
- `intents(intent_key PK, digest, scope_key, canonical_json, recorded_at_utc)`: append-only.
- `approvals(nonce PK, intent_key FK, intent_digest, scope_key, method, grant_json, attempt_id,
  consumed_at_utc)`: append-only; a nonce is used once.
- `attempts(attempt_id PK, intent_key FK, attempt_no, client_order_id, request_digest, fence_token,
  worker_id, approval_nonce FK UNIQUE, reservation_id FK UNIQUE, state, state_reason, provider_order_id,
  created_at_utc, updated_at_utc)`: a projection. UNIQUE(intent_key, attempt_no).
- `receipts(receipt_seq PK, receipt_id, status, kind, source, provider_id, attempt_id FK, payload_json,
  payload_sha256, received_at_utc)`: append-only. One ORIGINAL per receipt_id. A different payload under the
  same id is kept as CONFLICTING_DUPLICATE and never overwrites the original.
- `events(seq PK, at_utc, kind, subject, body_json, prev_hash, row_hash)`: append-only. Each row hashes
  its content and its predecessor's hash. Every change to any table above has an event.
- The reservation tables are documented in `reservations.py`.

Append-only tables are enforced by triggers, and a store missing one is refused. `verify_chain` re-checks
the event chain, checks that every intent and receipt still matches both its own hash and the hash its
event recorded, and checks that every attempt and reservation state matches its last event.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator

from .model import ApprovalGrant, OrderIntent, canonical_json, environment_authorized, sha256_text, utc_text
from .reservations import (SCHEMA_SQL as _RESERVATION_SCHEMA_SQL, CorruptRecord, InvalidTransition,
                           ReleaseReason, ReservationAuthority)

SCHEMA_VERSION = 1
STORE_KIND = "edge-lab-execution-journal"
FILENAME_SUFFIX = ".execution.sqlite3"
GENESIS_HASH = "0" * 64
DEFAULT_BUSY_TIMEOUT_MS = 250

_DIGEST = re.compile(r"[0-9a-f]{64}")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/#-]{0,199}")


class JournalError(Exception):
    """Base of every journal refusal or failure."""


class JournalUnavailable(JournalError):
    """An essential write or read failed (SQLite error, disk full, damaged store). Fail closed."""


class JournalBusy(JournalUnavailable):
    """The store stayed locked past the busy timeout. Nothing was written."""


class JournalCorrupt(JournalUnavailable):
    """A stored record does not decode, or the file is not a readable database."""


class UnknownSchema(JournalUnavailable):
    """The file is not an execution journal, or its schema version is unknown or newer."""


class IntentConflict(JournalError):
    """The same intent_key was recorded with a different digest. Nothing changed."""


class ApprovalRefused(JournalError):
    def __init__(self, problems: list[str]):
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class AttemptRefused(JournalError):
    """A new attempt is not allowed (an earlier one may be live, or the environment is not authorized)."""


class AttemptState(str, Enum):
    PENDING_EGRESS = "PENDING_EGRESS"  # committed before the network; not known to be sent
    SENT = "SENT"  # the network call returned, or failed after egress may have happened
    ACKNOWLEDGED = "ACKNOWLEDGED"  # the venue accepted the order (a receipt proves it)
    REJECTED = "REJECTED"  # the venue refused it (a receipt proves it): no order exists
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"  # it may or may not exist: reserved and blocking until reconciled
    ABSENT = "ABSENT"  # reconciliation found no order with this client order id: none exists


TERMINAL_ATTEMPT_STATES = frozenset({AttemptState.ACKNOWLEDGED, AttemptState.REJECTED, AttemptState.ABSENT})
NO_ORDER_STATES = frozenset({AttemptState.REJECTED, AttemptState.ABSENT})  # only these allow a new attempt
IN_FLIGHT_STATES = frozenset({AttemptState.PENDING_EGRESS, AttemptState.SENT})

_TRANSITIONS = {
    AttemptState.PENDING_EGRESS: frozenset({AttemptState.SENT, AttemptState.OUTCOME_UNKNOWN}),
    AttemptState.SENT: frozenset({AttemptState.ACKNOWLEDGED, AttemptState.REJECTED, AttemptState.OUTCOME_UNKNOWN}),
    AttemptState.OUTCOME_UNKNOWN: frozenset({AttemptState.ACKNOWLEDGED, AttemptState.REJECTED, AttemptState.ABSENT}),
}


class ReceiptOutcome(str, Enum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"  # same id, same payload hash: nothing new was written
    CONFLICTING_DUPLICATE = "CONFLICTING_DUPLICATE"  # same id, different payload: kept beside the original


@dataclass(frozen=True)
class IntentRecord:
    intent_key: str
    digest: str
    created: bool  # False: it was already recorded with the same digest (idempotent)


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    intent_key: str
    attempt_no: int
    client_order_id: str
    request_digest: str
    fence_token: int
    worker_id: str
    approval_nonce: str
    reservation_id: str
    state: AttemptState
    state_reason: str | None
    provider_order_id: str | None
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class ReceiptResult:
    outcome: ReceiptOutcome
    receipt_seq: int
    payload_sha256: str


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    events: int
    problems: tuple[str, ...]


def _event_hash(seq: int, at: str, kind: str, subject: str, body_json: str, prev_hash: str) -> str:
    return sha256_text(canonical_json([seq, at, kind, subject, body_json, prev_hash]))


def _map_error(exc: BaseException) -> JournalError:
    msg = str(exc).lower()
    if isinstance(exc, CorruptRecord):
        return JournalCorrupt(str(exc))
    if isinstance(exc, sqlite3.OperationalError) and ("locked" in msg or "busy" in msg):
        return JournalBusy(f"execution journal is locked: {exc}")
    if isinstance(exc, sqlite3.DatabaseError) and ("malformed" in msg or "not a database" in msg
                                                    or "corrupt" in msg):
        return JournalCorrupt(f"execution journal is damaged: {exc}")
    return JournalUnavailable(f"execution journal write or read failed: {type(exc).__name__}: {exc}")


_JOURNAL_SCHEMA_SQL = """
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE intents (
    intent_key TEXT PRIMARY KEY,
    digest TEXT NOT NULL CHECK (length(digest) = 64),
    scope_key TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL
);
CREATE TABLE approvals (
    nonce TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL REFERENCES intents(intent_key),
    intent_digest TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    method TEXT NOT NULL,
    grant_json TEXT NOT NULL,
    attempt_id TEXT,
    consumed_at_utc TEXT NOT NULL
);
CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL REFERENCES intents(intent_key),
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    client_order_id TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    fence_token INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    approval_nonce TEXT NOT NULL UNIQUE REFERENCES approvals(nonce),
    reservation_id TEXT NOT NULL UNIQUE REFERENCES reservations(reservation_id),
    state TEXT NOT NULL CHECK (state IN ('PENDING_EGRESS', 'SENT', 'ACKNOWLEDGED', 'REJECTED', 'OUTCOME_UNKNOWN',
                                         'ABSENT')),
    state_reason TEXT,
    provider_order_id TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE (intent_key, attempt_no)
);
CREATE INDEX attempts_by_state ON attempts(state);
CREATE TABLE receipts (
    receipt_seq INTEGER PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ORIGINAL', 'CONFLICTING_DUPLICATE')),
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    provider_id TEXT,
    attempt_id TEXT REFERENCES attempts(attempt_id),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    received_at_utc TEXT NOT NULL
);
CREATE UNIQUE INDEX receipts_one_original ON receipts(receipt_id) WHERE status = 'ORIGINAL';
CREATE INDEX receipts_by_id ON receipts(receipt_id);
CREATE TABLE events (
    seq INTEGER PRIMARY KEY,
    at_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL UNIQUE
);
"""
_APPEND_ONLY = ("intents", "approvals", "receipts", "events", "schema_meta")
_EXPECTED_TABLES = frozenset({"schema_meta", "intents", "approvals", "attempts", "receipts", "events",
                              "egress_lease", "account_snapshots", "reservations"})
_EXPECTED_TRIGGERS = frozenset({f"{t}_no_{op}" for t in _APPEND_ONLY + ("account_snapshots",)
                                for op in ("update", "remove")})


def _append_only_triggers() -> str:
    return "\n".join(
        f"CREATE TRIGGER {t}_no_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;\n"
        f"CREATE TRIGGER {t}_no_remove BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;"
        for t in _APPEND_ONLY)


class ExecutionJournal:
    """The durable intent, approval, attempt, receipt and audit store. Use `ExecutionJournal.open`."""

    def __init__(self, conn: sqlite3.Connection, path: Path):
        self._conn = conn
        self.path = path
        self._depth = 0
        # A test seam: called with "before_commit" just before the outermost COMMIT. Production never sets it.
        self._fault_hook: Callable[[str], None] | None = None
        self.reservations = ReservationAuthority(self)

    # ------------------------------------------------------------------ opening

    @classmethod
    def open(cls, path: str | Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> "ExecutionJournal":
        p = Path(path)
        if not p.name.endswith(FILENAME_SUFFIX) or p.name == FILENAME_SUFFIX:
            raise UnknownSchema(f"an execution journal file name ends in {FILENAME_SUFFIX!r}: {p.name!r}")
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int) or not 0 < busy_timeout_ms <= 60000:
            raise ValueError("busy_timeout_ms must be an int in (0, 60000]")
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(p), timeout=busy_timeout_ms / 1000, isolation_level=None)
            conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise JournalUnavailable(f"WAL journaling could not be enabled (got {mode!r})")
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA foreign_keys = ON")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise JournalUnavailable("foreign keys could not be enabled")
            journal = cls(conn, p)
            journal._ensure_schema()
            return journal
        except JournalError:
            if conn is not None:
                conn.close()
            raise
        except (sqlite3.Error, CorruptRecord) as exc:
            if conn is not None:
                conn.close()
            raise _map_error(exc) from exc

    def _ensure_schema(self) -> None:
        with self._reading() as conn:
            empty = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        if empty:
            with self._transaction() as conn:  # re-checked under the write lock: two openers may race
                if conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0:
                    for statement in _split_sql(_JOURNAL_SCHEMA_SQL + _RESERVATION_SCHEMA_SQL
                                                + _append_only_triggers()):
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('store_kind', ?), ('schema_version', ?)",
                                 (STORE_KIND, str(SCHEMA_VERSION)))
        with self._reading() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            if "schema_meta" not in tables:
                raise UnknownSchema(f"{self.path.name} has tables but no schema_meta: not an execution journal")
            meta = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
        if meta.get("store_kind") != STORE_KIND:
            raise UnknownSchema(f"{self.path.name} is a {meta.get('store_kind')!r} store, not {STORE_KIND!r}")
        version = meta.get("schema_version")
        if version is None or not version.isdigit():
            raise UnknownSchema(f"{self.path.name} has an unreadable schema version {version!r}")
        if int(version) > SCHEMA_VERSION:
            raise UnknownSchema(f"{self.path.name} has schema version {version}, newer than this code's "
                                f"{SCHEMA_VERSION}; refusing to touch it")
        if int(version) != SCHEMA_VERSION:
            raise UnknownSchema(f"{self.path.name} has unknown schema version {version}")
        missing = sorted((_EXPECTED_TABLES - tables) | (_EXPECTED_TRIGGERS - triggers))
        if missing:
            raise UnknownSchema(f"{self.path.name} is missing tables or append-only triggers {missing}")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ExecutionJournal":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ transactions (also used by reservations)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """One BEGIN IMMEDIATE ... COMMIT. Nested use joins the outer transaction, so a failure anywhere
        rolls back everything. SQLite errors are mapped to JournalBusy / JournalUnavailable."""
        if self._depth:
            self._depth += 1
            try:
                yield self._conn
            finally:
                self._depth -= 1
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise _map_error(exc) from exc
        self._depth = 1
        try:
            yield self._conn
            if self._fault_hook is not None:
                self._fault_hook("before_commit")
            self._conn.execute("COMMIT")
        except BaseException as exc:
            try:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
            except sqlite3.Error as rollback_exc:  # the connection is unusable: say so, never continue quietly
                raise JournalUnavailable(f"rollback failed after {exc!r}: {rollback_exc}") from exc
            if isinstance(exc, (sqlite3.Error, CorruptRecord)):
                raise _map_error(exc) from exc
            raise
        finally:
            self._depth = 0

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        """A consistent read (one deferred transaction), or the caller's transaction when nested."""
        if self._depth:
            yield self._conn
            return
        try:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            finally:
                if self._conn.in_transaction:
                    self._conn.execute("COMMIT")
        except (sqlite3.Error, CorruptRecord) as exc:
            raise _map_error(exc) from exc

    def _audit(self, conn: sqlite3.Connection, *, at: str, kind: str, subject: str, body: dict) -> None:
        """Append one hash-chained event. Only inside a write transaction."""
        if not self._depth:
            raise JournalUnavailable("an audit event must be written inside a transaction")
        last = conn.execute("SELECT seq, row_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (1, GENESIS_HASH) if last is None else (last[0] + 1, last[1])
        body_json = canonical_json(body)
        conn.execute("INSERT INTO events (seq, at_utc, kind, subject, body_json, prev_hash, row_hash)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (seq, at, kind, subject, body_json, prev, _event_hash(seq, at, kind, subject, body_json, prev)))

    # ------------------------------------------------------------------ intents and approvals

    def record_intent(self, intent: OrderIntent, now: datetime) -> IntentRecord:
        """Record the business intent. Same key and digest: idempotent. Same key, different digest:
        IntentConflict, and nothing changes. `now` is stored on first record only; it is never identity."""
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        at = utc_text(now)
        digest = intent.digest()
        with self._transaction() as conn:
            row = conn.execute("SELECT digest FROM intents WHERE intent_key = ?", (intent.intent_key,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise IntentConflict(f"intent {intent.intent_key!r} is recorded with digest {row[0][:12]}…, "
                                         f"not {digest[:12]}…; a changed intent needs a new key")
                return IntentRecord(intent.intent_key, digest, created=False)
            conn.execute("INSERT INTO intents (intent_key, digest, scope_key, canonical_json, recorded_at_utc)"
                         " VALUES (?, ?, ?, ?, ?)", (intent.intent_key, digest, intent.scope.key(),
                                                      intent.canonical(), at))
            self._audit(conn, at=at, kind="INTENT_RECORDED", subject=intent.intent_key,
                        body={"digest": digest, "scope_key": intent.scope.key()})
            return IntentRecord(intent.intent_key, digest, created=True)

    def consume_approval(self, grant: ApprovalGrant, intent: OrderIntent, now: datetime, *,
                         attempt_id: str | None = None) -> None:
        """Use `grant` for `intent`, once. Refused (ApprovalRefused) if it does not bind the intent at `now`
        (digest, scope, expiry) or its nonce was already used. Inside `prepare_attempt` this is part of the
        one prepare transaction."""
        if not isinstance(grant, ApprovalGrant):
            raise ValueError("grant must be an ApprovalGrant")
        problems = grant.problems(intent, now=now)
        at = utc_text(now)
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM approvals WHERE nonce = ?", (grant.nonce,)).fetchone() is not None:
                problems.append("APPROVAL_NONCE_REUSED: this approval was already used")
            if problems:
                raise ApprovalRefused(problems)
            self.record_intent(intent, now)
            grant_json = canonical_json({k: getattr(grant, k) for k in grant.__dataclass_fields__})
            conn.execute("INSERT INTO approvals (nonce, intent_key, intent_digest, scope_key, method, grant_json,"
                         " attempt_id, consumed_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (grant.nonce, intent.intent_key, grant.intent_digest, grant.scope_key, grant.method.value,
                          grant_json, attempt_id, at))
            self._audit(conn, at=at, kind="APPROVAL_CONSUMED", subject=grant.nonce,
                        body={"intent_key": intent.intent_key, "intent_digest": grant.intent_digest,
                              "grant_sha256": sha256_text(grant_json), "attempt_id": attempt_id})

    # ------------------------------------------------------------------ attempts

    def prepare_attempt(self, intent: OrderIntent, grant: ApprovalGrant, *, fence_token: int, request_digest: str,
                        snapshot_max_age: timedelta, now: datetime) -> Attempt:
        """Commit everything a send needs, in ONE transaction, before any network. On any exception nothing
        was committed and the caller must not send."""
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        if not isinstance(request_digest, str) or not _DIGEST.fullmatch(request_digest):
            raise ValueError("request_digest must be a SHA-256 hex digest of the exact request")
        at = utc_text(now)
        with self._transaction() as conn:
            lease = self.reservations._check_fence(conn, fence_token, now)  # stale workers stop here
            if not environment_authorized(intent.scope.environment):
                raise AttemptRefused(f"ENVIRONMENT_NOT_AUTHORIZED: {intent.scope.environment.value}")
            self.record_intent(intent, now)
            earlier = [self._decode_attempt(r) for r in conn.execute(
                f"SELECT {self._ATTEMPT_COLUMNS} FROM attempts WHERE intent_key = ? ORDER BY attempt_no",
                (intent.intent_key,))]
            live = [a for a in earlier if a.state not in NO_ORDER_STATES]
            if live:
                raise AttemptRefused(f"ATTEMPT_BLOCKED: {live[-1].attempt_id} is {live[-1].state.value}; an order may "
                                     "exist, so a new attempt would be a blind resubmission")
            attempt_no = len(earlier) + 1
            attempt_id = f"{intent.client_order_id()}#{attempt_no}"
            self.consume_approval(grant, intent, now, attempt_id=attempt_id)
            self.reservations.reserve(intent, fence_token, now, snapshot_max_age=snapshot_max_age,
                                      reservation_id=attempt_id)
            conn.execute("INSERT INTO attempts (attempt_id, intent_key, attempt_no, client_order_id, request_digest,"
                         " fence_token, worker_id, approval_nonce, reservation_id, state, state_reason,"
                         " provider_order_id, created_at_utc, updated_at_utc)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_EGRESS', NULL, NULL, ?, ?)",
                         (attempt_id, intent.intent_key, attempt_no, intent.client_order_id(), request_digest,
                          fence_token, lease.worker_id, grant.nonce, attempt_id, at, at))
            self._audit(conn, at=at, kind="ATTEMPT_PREPARED", subject=attempt_id,
                        body={"intent_key": intent.intent_key, "intent_digest": intent.digest(),
                              "attempt_no": attempt_no, "client_order_id": intent.client_order_id(),
                              "request_digest": request_digest, "fence_token": fence_token,
                              "worker_id": lease.worker_id, "approval_nonce": grant.nonce})
            return self._attempt(conn, attempt_id)

    def mark_sent(self, attempt_id: str, *, now: datetime) -> Attempt:
        """The network call returned, or failed after the request may have left: SENT."""
        return self._move(attempt_id, AttemptState.SENT, now, reason=None)

    def mark_acknowledged(self, attempt_id: str, *, provider_order_id: str, receipt_id: str, now: datetime) -> Attempt:
        if not isinstance(provider_order_id, str) or not provider_order_id:
            raise ValueError("provider_order_id is required")
        return self._move(attempt_id, AttemptState.ACKNOWLEDGED, now, reason=None, receipt_id=receipt_id,
                          provider_order_id=provider_order_id)

    def mark_rejected(self, attempt_id: str, *, receipt_id: str, now: datetime) -> Attempt:
        """The venue refused the order (a recorded receipt says so). Its reservation is released."""
        return self._move(attempt_id, AttemptState.REJECTED, now, reason=None, receipt_id=receipt_id)

    def mark_outcome_unknown(self, attempt_id: str, *, reason: str, now: datetime) -> Attempt:
        """An ambiguous result (a timeout after egress, a lost response). The reservation stays held and the
        intent is blocked until `reconcile_attempt`."""
        if not isinstance(reason, str) or not reason:
            raise ValueError("a reason is required")
        return self._move(attempt_id, AttemptState.OUTCOME_UNKNOWN, now, reason=reason)

    def reconcile_attempt(self, attempt_id: str, resolution: AttemptState, *, receipt_id: str, now: datetime,
                          provider_order_id: str | None = None) -> Attempt:
        """Resolve an OUTCOME_UNKNOWN attempt from a recorded receipt (an order lookup by client order id):
        ACKNOWLEDGED (it exists; needs provider_order_id), REJECTED, or ABSENT (no such order exists)."""
        current = self.attempt(attempt_id)
        if current.state is not AttemptState.OUTCOME_UNKNOWN:
            raise InvalidTransition(f"{attempt_id} is {current.state.value}; only OUTCOME_UNKNOWN is reconciled")
        if resolution is AttemptState.ACKNOWLEDGED and not provider_order_id:
            raise ValueError("an ACKNOWLEDGED resolution needs the provider_order_id")
        return self._move(attempt_id, resolution, now, reason="RECONCILED", receipt_id=receipt_id,
                          provider_order_id=provider_order_id, expect=AttemptState.OUTCOME_UNKNOWN)

    def _move(self, attempt_id: str, new: AttemptState, now: datetime, *, reason: str | None,
              receipt_id: str | None = None, provider_order_id: str | None = None,
              expect: AttemptState | None = None) -> Attempt:
        if not isinstance(new, AttemptState):
            raise ValueError("new state must be an AttemptState")
        at = utc_text(now)
        with self._transaction() as conn:
            a = self._attempt(conn, attempt_id)
            if expect is not None and a.state is not expect:
                raise InvalidTransition(f"{attempt_id} is {a.state.value}, not {expect.value}")
            if a.state is AttemptState.OUTCOME_UNKNOWN and expect is None:
                raise InvalidTransition(f"{attempt_id} is OUTCOME_UNKNOWN: only reconcile_attempt resolves it")
            if new not in _TRANSITIONS.get(a.state, frozenset()):
                raise InvalidTransition(f"{attempt_id}: {a.state.value} -> {new.value} is not allowed")
            if receipt_id is not None:
                self._require_receipt(conn, receipt_id)
            conn.execute("UPDATE attempts SET state = ?, state_reason = ?, provider_order_id = COALESCE(?, provider_order_id),"
                         " updated_at_utc = ? WHERE attempt_id = ?",
                         (new.value, reason, provider_order_id, at, attempt_id))
            self._audit(conn, at=at, kind="ATTEMPT_STATE", subject=attempt_id,
                        body={"from": a.state, "to": new, "reason": reason, "receipt_id": receipt_id,
                              "provider_order_id": provider_order_id})
            if new is AttemptState.OUTCOME_UNKNOWN:
                self.reservations._attempt_unknown(conn, a.reservation_id, at)
            elif new is AttemptState.ACKNOWLEDGED:
                self.reservations._attempt_acknowledged(conn, a.reservation_id, at)
            elif new is AttemptState.REJECTED:
                self.reservations._attempt_never_placed(conn, a.reservation_id, ReleaseReason.REJECTED, at)
            elif new is AttemptState.ABSENT:
                self.reservations._attempt_never_placed(conn, a.reservation_id, ReleaseReason.ABSENT_AT_VENUE, at)
            return self._attempt(conn, attempt_id)

    def _quarantine_superseded_fences(self, conn: sqlite3.Connection, *, live_token: int | None,
                                      at: str) -> list[str]:
        """Every PENDING_EGRESS or SENT attempt whose fence is not `live_token` becomes OUTCOME_UNKNOWN: its
        worker is dead or fenced out, and it may or may not have sent. Reservations stay held."""
        rows = conn.execute("SELECT attempt_id, state, reservation_id, fence_token FROM attempts"
                            " WHERE state IN ('PENDING_EGRESS', 'SENT') ORDER BY attempt_id").fetchall()
        moved = []
        for attempt_id, state, reservation_id, token in rows:
            if live_token is not None and token == live_token:
                continue
            conn.execute("UPDATE attempts SET state = 'OUTCOME_UNKNOWN', state_reason = ?, updated_at_utc = ?"
                         " WHERE attempt_id = ?", (f"FENCE_SUPERSEDED: fence {token} is not live", at, attempt_id))
            self._audit(conn, at=at, kind="ATTEMPT_STATE", subject=attempt_id,
                        body={"from": state, "to": AttemptState.OUTCOME_UNKNOWN, "reason": "FENCE_SUPERSEDED",
                              "fence_token": token, "live_token": live_token})
            self.reservations._attempt_unknown(conn, reservation_id, at)
            moved.append(attempt_id)
        return moved

    def recover(self, now: datetime) -> list[Attempt]:
        """After a restart: in-flight attempts whose fence is not the live, unexpired lease become
        OUTCOME_UNKNOWN. Returns every attempt that is not terminal, for reconciliation."""
        at = utc_text(now)
        with self._transaction() as conn:
            lease = self.reservations._lease(conn)
            live = lease.fence_token if lease is not None and lease.live_at(now) else None
            self._quarantine_superseded_fences(conn, live_token=live, at=at)
            return self._non_terminal(conn)

    def non_terminal_attempts(self) -> list[Attempt]:
        with self._reading() as conn:
            return self._non_terminal(conn)

    def _non_terminal(self, conn: sqlite3.Connection) -> list[Attempt]:
        rows = conn.execute(f"SELECT {self._ATTEMPT_COLUMNS} FROM attempts WHERE state NOT IN"
                            " ('ACKNOWLEDGED', 'REJECTED', 'ABSENT') ORDER BY attempt_id").fetchall()
        return [self._decode_attempt(r) for r in rows]

    def attempt(self, attempt_id: str) -> Attempt:
        with self._reading() as conn:
            return self._attempt(conn, attempt_id)

    def attempts_for(self, intent_key: str) -> list[Attempt]:
        with self._reading() as conn:
            rows = conn.execute(f"SELECT {self._ATTEMPT_COLUMNS} FROM attempts WHERE intent_key = ?"
                                " ORDER BY attempt_no", (intent_key,)).fetchall()
            return [self._decode_attempt(r) for r in rows]

    _ATTEMPT_COLUMNS = ("attempt_id, intent_key, attempt_no, client_order_id, request_digest, fence_token, worker_id,"
                        " approval_nonce, reservation_id, state, state_reason, provider_order_id, created_at_utc,"
                        " updated_at_utc")

    def _attempt(self, conn: sqlite3.Connection, attempt_id: str) -> Attempt:
        row = conn.execute(f"SELECT {self._ATTEMPT_COLUMNS} FROM attempts WHERE attempt_id = ?",
                           (attempt_id,)).fetchone()
        if row is None:
            raise InvalidTransition(f"no attempt {attempt_id!r}")
        return self._decode_attempt(row)

    @staticmethod
    def _decode_attempt(row: tuple) -> Attempt:
        try:
            return Attempt(row[0], row[1], int(row[2]), row[3], row[4], int(row[5]), row[6], row[7], row[8],
                           AttemptState(row[9]), row[10], row[11], row[12], row[13])
        except (ValueError, TypeError) as exc:
            raise CorruptRecord(f"attempt {row[0]!r} does not decode: {exc}") from exc

    # ------------------------------------------------------------------ receipts

    def record_receipt(self, *, receipt_id: str, kind: str, source: str, payload_json: str, received_at: datetime,
                       provider_id: str | None = None, attempt_id: str | None = None) -> ReceiptResult:
        """Append a raw provider payload, exactly as received. Same id and hash: DUPLICATE (nothing written).
        Same id, different hash: kept as CONFLICTING_DUPLICATE beside the original, which is never changed."""
        for name, value in (("receipt_id", receipt_id), ("kind", kind), ("source", source)):
            if not isinstance(value, str) or not _LABEL.fullmatch(value):
                raise ValueError(f"{name} must be a short label, not {value!r}")
        if not isinstance(payload_json, str):
            raise ValueError("payload_json must be the raw JSON text")
        try:
            json.loads(payload_json)
        except ValueError as exc:
            raise ValueError(f"payload_json is not JSON: {exc}") from exc
        at = utc_text(received_at)
        sha = sha256_text(payload_json)
        with self._transaction() as conn:
            rows = conn.execute("SELECT receipt_seq, payload_sha256 FROM receipts WHERE receipt_id = ?"
                                " ORDER BY receipt_seq", (receipt_id,)).fetchall()
            for seq, existing in rows:
                if existing == sha:
                    return ReceiptResult(ReceiptOutcome.DUPLICATE, seq, sha)
            outcome = ReceiptOutcome.CONFLICTING_DUPLICATE if rows else ReceiptOutcome.RECORDED
            status = "CONFLICTING_DUPLICATE" if rows else "ORIGINAL"
            cur = conn.execute("INSERT INTO receipts (receipt_id, status, kind, source, provider_id, attempt_id,"
                               " payload_json, payload_sha256, received_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (receipt_id, status, kind, source, provider_id, attempt_id, payload_json, sha, at))
            seq = int(cur.lastrowid)
            self._audit(conn, at=at, kind="RECEIPT_RECORDED", subject=str(seq),
                        body={"receipt_id": receipt_id, "status": status, "kind": kind, "source": source,
                              "provider_id": provider_id, "attempt_id": attempt_id, "payload_sha256": sha})
            return ReceiptResult(outcome, seq, sha)

    def receipts(self, receipt_id: str) -> list[dict[str, Any]]:
        with self._reading() as conn:
            rows = conn.execute("SELECT receipt_seq, status, kind, source, provider_id, attempt_id, payload_json,"
                                " payload_sha256, received_at_utc FROM receipts WHERE receipt_id = ?"
                                " ORDER BY receipt_seq", (receipt_id,)).fetchall()
        keys = ("receipt_seq", "status", "kind", "source", "provider_id", "attempt_id", "payload_json",
                "payload_sha256", "received_at_utc")
        return [dict(zip(keys, r)) for r in rows]

    def _require_receipt(self, conn: sqlite3.Connection, receipt_id: str) -> None:
        """A state change backed by evidence: the receipt must exist and must not be in conflict."""
        statuses = {r[0] for r in conn.execute("SELECT status FROM receipts WHERE receipt_id = ?", (receipt_id,))}
        if not statuses:
            raise InvalidTransition(f"RECEIPT_NOT_RECORDED: {receipt_id!r}")
        if "CONFLICTING_DUPLICATE" in statuses:
            raise InvalidTransition(f"RECEIPT_CONFLICTED: {receipt_id!r} has conflicting payloads; reconcile first")

    # ------------------------------------------------------------------ verification

    def verify_chain(self) -> ChainVerification:
        """Recompute the event chain; check every intent and receipt against its own hash and the hash its
        event recorded; check every attempt and reservation state against the last state its events record.
        Read-only. Problems are reported, never repaired. A truncated tail of the chain is not detectable
        without an external anchor."""
        problems: list[str] = []
        with self._reading() as conn:
            prev, expected_seq, count = GENESIS_HASH, 1, 0
            recorded: dict[tuple[str, str], str] = {}
            last_state: dict[tuple[str, str], str] = {}  # the projections must equal what their events say
            for seq, at, kind, subject, body_json, prev_hash, row_hash in conn.execute(
                    "SELECT seq, at_utc, kind, subject, body_json, prev_hash, row_hash FROM events ORDER BY seq"):
                count += 1
                if seq != expected_seq:
                    problems.append(f"EVENT_GAP: expected seq {expected_seq}, found {seq}")
                if prev_hash != prev:
                    problems.append(f"EVENT_LINK_BROKEN: seq {seq} does not follow its predecessor")
                if _event_hash(seq, at, kind, subject, body_json, prev_hash) != row_hash:
                    problems.append(f"EVENT_ALTERED: seq {seq} does not match its hash")
                try:
                    body = json.loads(body_json)
                except ValueError:
                    problems.append(f"EVENT_BODY_UNREADABLE: seq {seq}")
                    body = {}
                if kind == "INTENT_RECORDED":
                    recorded[("intent", subject)] = body.get("digest")
                elif kind == "RECEIPT_RECORDED":
                    recorded[("receipt", subject)] = body.get("payload_sha256")
                elif kind == "ATTEMPT_PREPARED":
                    last_state[("attempt", subject)] = AttemptState.PENDING_EGRESS.value
                elif kind == "ATTEMPT_STATE":
                    last_state[("attempt", subject)] = body.get("to")
                elif kind == "RESERVATION_CREATED":
                    last_state[("reservation", subject)] = "OUTSTANDING"
                elif kind in ("RESERVATION_STATE", "RESERVATION_FILL"):
                    last_state[("reservation", subject)] = body.get("to")
                prev, expected_seq = row_hash, seq + 1
            for key, digest, canonical in conn.execute("SELECT intent_key, digest, canonical_json FROM intents"):
                if sha256_text(canonical) != digest:
                    problems.append(f"INTENT_ALTERED: {key} content does not match its digest")
                if recorded.get(("intent", key)) != digest:
                    problems.append(f"INTENT_UNAUDITED: {key} digest differs from its recorded event")
            for attempt_id, state in conn.execute("SELECT attempt_id, state FROM attempts"):
                if last_state.get(("attempt", attempt_id)) != state:
                    problems.append(f"PROJECTION_DIVERGED: attempt {attempt_id} is {state}, its events say "
                                    f"{last_state.get(('attempt', attempt_id))}")
            for reservation_id, state in conn.execute("SELECT reservation_id, state FROM reservations"):
                if last_state.get(("reservation", reservation_id)) != state:
                    problems.append(f"PROJECTION_DIVERGED: reservation {reservation_id} is {state}, its events say "
                                    f"{last_state.get(('reservation', reservation_id))}")
            for seq, payload, sha in conn.execute("SELECT receipt_seq, payload_json, payload_sha256 FROM receipts"):
                if sha256_text(payload) != sha:
                    problems.append(f"RECEIPT_ALTERED: receipt {seq} payload does not match its hash")
                if recorded.get(("receipt", str(seq))) != sha:
                    problems.append(f"RECEIPT_UNAUDITED: receipt {seq} hash differs from its recorded event")
        return ChainVerification(not problems, count, tuple(problems))


def _split_sql(script: str) -> list[str]:
    """Split the schema script into statements (triggers keep their inner `;`). `executescript` is not used
    because it commits outside our transaction."""
    out, current = [], []
    for line in script.splitlines():
        if not line.strip():
            continue
        current.append(line)
        text = "\n".join(current).strip()
        if text.endswith(";") and (not text.upper().startswith("CREATE TRIGGER") or text.upper().endswith("END;")):
            out.append(text)
            current = []
    if current:
        out.append("\n".join(current))
    return out
