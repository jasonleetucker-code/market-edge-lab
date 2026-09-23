"""Append-only shadow ledger and account replay (Gate 6). Simulation only: no real orders.

The ledger is a journal of four entry kinds per shadow account:

    account_opened → decision → fill (FILLED | NO_FILL) → settlement

Every balance, position and P&L figure is **derived by replaying the journal**. Nothing
stores a mutable balance.

- Entries are immutable: SQLite triggers reject UPDATE and DELETE.
- Entries are idempotent: (account, kind, key) is unique. Re-appending identical content
  returns the existing entry; different content under the same key raises
  `LedgerConflict`.
- Entries are hash-chained per account, and `verify_chain` detects tampering.
- The ledger checks invariants before it appends anything:
  - a fill needs a qualified decision;
  - a FILLED entry may never make settled cash negative;
  - a settlement needs an open FILLED position;
  - P&L is computed here from the fill, never taken from the caller, so a settlement cannot
    create phantom profit.

The ledger lives in its own SQLite file, separate from the raw-evidence database. It is
derived research data: rebuild it from evidence plus versioned code at any time.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

LEDGER_SCHEMA_VERSION = 1
KINDS = ("account_opened", "decision", "fill", "settlement")
GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('account_opened', 'decision', 'fill', 'settlement')),
    entry_key TEXT NOT NULL,
    effective_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE,
    appended_at_utc TEXT NOT NULL,
    UNIQUE (account_id, kind, entry_key)
);
CREATE INDEX IF NOT EXISTS ledger_entries_account ON ledger_entries (account_id, seq);
CREATE TRIGGER IF NOT EXISTS ledger_entries_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS ledger_entries_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger entries are immutable'); END;
"""


class LedgerError(RuntimeError):
    """An entry would violate a ledger invariant; nothing was written."""


class LedgerConflict(LedgerError):
    """The same (account, kind, key) was appended before with different content."""


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry_hash(prev: str, account: str, kind: str, key: str, effective: str, payload_sha: str) -> str:
    return _sha("|".join((prev, account, kind, key, effective, payload_sha)))


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _utc(value: Any) -> datetime | None:
    from .freshness import parse_utc
    return parse_utc(value)


# --------------------------------------------------------------------------- replayed state


@dataclass
class Position:
    position_id: str  # = fill_id
    decision_id: str
    account_id: str
    opened_at_utc: str
    venue: str
    market_id: str
    event_id: str
    outcome_cluster: str
    side: str
    quantity: int
    price: Decimal
    cost_basis: Decimal  # total cash paid, fees and cent alignment included
    fees: Decimal  # cost_basis - quantity * price
    max_downside: Decimal  # = cost_basis for a long binary
    potential_payout: Decimal  # quantity * 1
    strategy: str
    expected_settlement_utc: str | None
    status: str = "OPEN"  # OPEN | SETTLED
    outcome: str | None = None
    payout: Decimal | None = None
    net_pnl: Decimal | None = None
    settled_at_utc: str | None = None


@dataclass
class AccountState:
    account_id: str
    strategy: str
    starting_bankroll: Decimal
    settled_cash: Decimal
    committed_capital: Decimal
    open_worst_case_risk: Decimal
    open_potential_payout: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    equity: Decimal  # settled cash + cost of open positions (no unrealized gains)
    decisions: int
    qualified_decisions: int
    fills: int
    no_fills: int
    settlements: int
    positions: list[Position] = field(default_factory=list)
    no_fill_reasons: dict[str, int] = field(default_factory=dict)
    decision_slots: dict[str, str] = field(default_factory=dict)  # slot -> decision_id
    last_entry_hash: str = GENESIS

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "OPEN"]

    def event_exposure(self, event_id: str) -> Decimal:
        return sum((p.max_downside for p in self.open_positions() if p.event_id == event_id), Decimal(0))

    def cluster_exposure(self, cluster: str) -> Decimal:
        return sum((p.max_downside for p in self.open_positions() if p.outcome_cluster == cluster), Decimal(0))

    def to_dict(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:
            return str(v) if isinstance(v, Decimal) else v
        out = {k: plain(v) for k, v in self.__dict__.items() if k not in ("positions", "decision_slots")}
        out["positions"] = [{k: plain(v) for k, v in p.__dict__.items()} for p in self.positions]
        return out


def knowledge_time(row: sqlite3.Row | dict[str, Any]) -> datetime | None:
    """When the fact an entry records was known (modeled time, not processing time).

    - account/decision/fill: the entry's effective time (decision as-of, fill confirmation).
    - settlement: when its settlement evidence became available (`evidence_available_utc`
      in the evidence). Entries written before that field existed fall back to the later
      of the settlement time and the append (processing) time, which is never earlier than
      the truth."""
    if row["kind"] != "settlement":
        return _utc(row["effective_at_utc"])
    evidence = json.loads(row["payload_json"]).get("evidence") or {}
    known = _utc(evidence.get("evidence_available_utc"))
    if known is not None:
        return known
    candidates = [t for t in (_utc(row["effective_at_utc"]), _utc(row["appended_at_utc"])) if t is not None]
    return max(candidates) if candidates else None


def replay(entries: Iterable[sqlite3.Row | dict[str, Any]], *, as_of: datetime | None = None) -> AccountState:
    """Rebuild one account from its journal, from zero. Raises if an invariant is broken.

    With `as_of`, only entries whose `knowledge_time` is at or before `as_of` count: the
    account as it could have been known then (a settlement learned later never funds an
    earlier fill). Hash-chain checks still cover every row."""
    state: AccountState | None = None
    decisions: dict[str, dict[str, Any]] = {}
    positions: dict[str, Position] = {}
    prev = GENESIS
    for row in entries:
        kind, payload = row["kind"], json.loads(row["payload_json"])
        if row["prev_hash"] != prev:
            raise LedgerError(f"hash chain broken at seq {row['seq']}")
        if _sha(row["payload_json"]) != row["payload_sha256"] or _entry_hash(
                prev, row["account_id"], kind, row["entry_key"], row["effective_at_utc"],
                row["payload_sha256"]) != row["entry_hash"]:
            raise LedgerError(f"entry {row['seq']} does not match its hash")
        prev = row["entry_hash"]
        if as_of is not None and kind != "account_opened":
            known = knowledge_time(row)
            if known is None or known > as_of:
                continue
        if kind == "account_opened":
            if state is not None:
                raise LedgerError("account opened twice")
            bankroll = _d(payload["starting_bankroll"])
            state = AccountState(payload["account_id"], payload["strategy"], bankroll, bankroll, Decimal(0),
                                 Decimal(0), Decimal(0), Decimal(0), Decimal(0), bankroll, 0, 0, 0, 0, 0)
            continue
        if state is None:
            raise LedgerError(f"{kind} before account_opened")
        if kind == "decision":
            if payload.get("qualification") not in ("QUALIFY", "REJECT"):
                raise LedgerError(f"decision {payload.get('decision_id')} has an invalid qualification")
            slot = payload.get("slot")
            if slot is not None:
                if slot in state.decision_slots:
                    raise LedgerError(f"slot {slot} already decided by {state.decision_slots[slot]}")
                state.decision_slots[slot] = payload["decision_id"]
            decisions[payload["decision_id"]] = payload
            state.decisions += 1
            state.qualified_decisions += payload["qualification"] == "QUALIFY"
        elif kind == "fill":
            decision = decisions.get(payload["decision_id"])
            if decision is None:
                raise LedgerError(f"fill {payload['fill_id']} for unknown decision")
            if payload["status"] not in ("FILLED", "NO_FILL"):
                raise LedgerError(f"fill {payload['fill_id']} has invalid status {payload['status']!r}")
            if payload["status"] == "NO_FILL":
                state.no_fills += 1
                state.no_fill_reasons[payload["reason"]] = state.no_fill_reasons.get(payload["reason"], 0) + 1
                continue
            if decision["qualification"] != "QUALIFY":
                raise LedgerError(f"fill {payload['fill_id']} fills a rejected decision")
            if payload["fill_id"] in positions:
                raise LedgerError(f"fill id {payload['fill_id']} used twice")
            if payload.get("side") not in ("YES", "NO"):
                raise LedgerError(f"fill {payload['fill_id']} has invalid side {payload.get('side')!r}")
            for name in ("market_id", "side", "event_id"):
                if name in decision and decision[name] != payload.get(name):
                    raise LedgerError(f"fill {payload['fill_id']} {name} differs from its decision")
            cost, qty, price = _d(payload["total_cost"]), int(payload["quantity"]), _d(payload["price"])
            if qty <= 0 or not (Decimal(0) < price < Decimal(1)) or cost < qty * price:
                raise LedgerError(f"fill {payload['fill_id']} has an invalid quantity, price or cost")
            state.settled_cash -= cost
            if state.settled_cash < 0:
                raise LedgerError(f"fill {payload['fill_id']} makes settled cash negative")
            positions[payload["fill_id"]] = Position(
                position_id=payload["fill_id"], decision_id=payload["decision_id"], account_id=state.account_id,
                opened_at_utc=payload["filled_at_utc"], venue=payload["venue"], market_id=payload["market_id"],
                event_id=payload["event_id"], outcome_cluster=payload["outcome_cluster"], side=payload["side"],
                quantity=qty, price=price, cost_basis=cost, fees=cost - qty * price, max_downside=cost,
                potential_payout=Decimal(qty), strategy=state.strategy,
                expected_settlement_utc=payload.get("expected_settlement_utc"),
            )
            state.fills += 1
            state.fees_paid += cost - qty * price
        elif kind == "settlement":
            position = positions.get(payload["fill_id"])
            if position is None or position.status != "OPEN":
                raise LedgerError(f"settlement {payload['settlement_id']} has no open position")
            if payload.get("outcome") not in ("YES", "NO") or payload.get("market_id") != position.market_id:
                raise LedgerError(f"settlement {payload['settlement_id']} has an invalid outcome or market")
            settled_at, opened_at = _utc(payload.get("settled_at_utc")), _utc(position.opened_at_utc)
            if settled_at is None or opened_at is None or settled_at < opened_at:
                raise LedgerError(f"settlement {payload['settlement_id']} time is missing or before the fill")
            payout = _d(payload["payout"])
            if payout != (Decimal(position.quantity) if payload["outcome"] == position.side else Decimal(0)):
                raise LedgerError(f"settlement {payload['settlement_id']} payout inconsistent with its position")
            position.status, position.outcome, position.payout = "SETTLED", payload["outcome"], payout
            position.net_pnl, position.settled_at_utc = payout - position.cost_basis, payload["settled_at_utc"]
            state.settled_cash += payout
            state.realized_pnl += position.net_pnl
            state.settlements += 1
    if state is None:
        raise LedgerError("no account_opened entry")
    state.positions = list(positions.values())
    open_ = state.open_positions()
    state.committed_capital = sum((p.cost_basis for p in open_), Decimal(0))
    state.open_worst_case_risk = sum((p.max_downside for p in open_), Decimal(0))
    state.open_potential_payout = sum((p.potential_payout for p in open_), Decimal(0))
    state.equity = state.settled_cash + state.committed_capital
    state.last_entry_hash = prev
    if state.equity != state.starting_bankroll + state.realized_pnl:
        raise LedgerError("equity does not reconcile with starting bankroll + realized P&L")
    return state


# --------------------------------------------------------------------------- store


LOCK_TIMEOUT_S = 5.0  # a held lock fails an append fast and explicitly, never hangs


def _reference_triggers() -> frozenset[str]:
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(_SCHEMA)
        return frozenset(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'"))


REFERENCE_TRIGGERS = _reference_triggers()


class _locked:
    """Turn SQLite's lock/busy errors into an explicit LedgerError."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if isinstance(exc, sqlite3.OperationalError) and any(w in str(exc).lower() for w in ("locked", "busy")):
            raise LedgerError(f"ledger {self.path.name} is locked or busy (waited {LOCK_TIMEOUT_S:.0f}s): {exc}") from exc
        return False


class ShadowLedger:
    """A shadow-account journal in its own SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(self.path), closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, LEDGER_SCHEMA_VERSION):
                raise LedgerError(f"unsupported ledger schema {version}")
            conn.execute(f"PRAGMA user_version = {LEDGER_SCHEMA_VERSION}")

    _read_only = False

    @classmethod
    def open_readonly(cls, path: str | Path) -> "ShadowLedger":
        """Open an existing ledger for reporting: no file or schema creation, SQLite
        `mode=ro` + `query_only`. Appends fail. Refuses a missing file or another schema."""
        p = Path(path)
        if p.is_symlink() or not p.is_file():
            raise LedgerError(f"shadow ledger {p} is missing or not a regular file")
        ledger = cls.__new__(cls)
        ledger.path = p
        ledger._read_only = True
        with closing(ledger._connect()) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != LEDGER_SCHEMA_VERSION:
            raise LedgerError(f"unsupported ledger schema {version}")
        return ledger

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _connect(self) -> sqlite3.Connection:
        if self._read_only:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True,
                                   timeout=LOCK_TIMEOUT_S, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {int(LOCK_TIMEOUT_S * 1000)}")
            conn.execute("PRAGMA query_only = ON")
            return conn
        conn = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_S, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(LOCK_TIMEOUT_S * 1000)}")
        return conn

    def entries(self, account_id: str) -> list[sqlite3.Row]:
        with _locked(self.path), closing(self._connect()) as conn:
            return conn.execute("SELECT * FROM ledger_entries WHERE account_id = ? ORDER BY seq",
                                (account_id,)).fetchall()

    def accounts(self) -> list[str]:
        with closing(self._connect()) as conn:
            return [r[0] for r in conn.execute(
                "SELECT account_id FROM ledger_entries WHERE kind = 'account_opened' ORDER BY seq")]

    def state(self, account_id: str) -> AccountState:
        return replay(self.entries(account_id))

    def state_as_of(self, account_id: str, as_of: datetime) -> AccountState:
        """The account as it could have been known at `as_of` (see `knowledge_time`)."""
        return replay(self.entries(account_id), as_of=as_of)

    def verify_schema(self) -> None:
        """The append-only triggers must all be present (a dropped trigger is tampering)."""
        with closing(self._connect()) as conn:
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        missing = sorted(REFERENCE_TRIGGERS - present)
        if missing:
            raise LedgerError(f"append-only triggers missing: {missing}")

    def verify_chain(self, account_id: str) -> str:
        """Replays the account (which checks every hash), then checks the append-only
        triggers are all present; returns the head hash."""
        head = self.state(account_id).last_entry_hash
        self.verify_schema()
        return head

    def find(self, account_id: str, kind: str, key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT payload_json FROM ledger_entries WHERE account_id = ? AND kind = ? "
                               "AND entry_key = ?", (account_id, kind, key)).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    # ------------------------------------------------------------------ appends

    def _append(self, account_id: str, kind: str, key: str, effective_at: str, payload: dict[str, Any],
                check=None) -> tuple[str, bool]:
        """Append one entry atomically. Returns (entry_hash, created)."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        text = canonical(payload)
        payload_sha = _sha(text)
        with _locked(self.path), closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT entry_hash, payload_sha256, effective_at_utc FROM ledger_entries "
                    "WHERE account_id = ? AND kind = ? AND entry_key = ?", (account_id, kind, key)).fetchone()
                if existing is not None:
                    conn.execute("ROLLBACK")
                    if existing["payload_sha256"] != payload_sha or existing["effective_at_utc"] != effective_at:
                        raise LedgerConflict(f"{kind} {key} already recorded with different content")
                    return existing["entry_hash"], False
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM ledger_entries WHERE account_id = ? ORDER BY seq", (account_id,))]
                if check is not None:
                    check(replay(rows) if rows else None, rows)
                prev = rows[-1]["entry_hash"] if rows else GENESIS
                entry_hash = _entry_hash(prev, account_id, kind, key, effective_at, payload_sha)
                candidate = {"seq": "candidate", "account_id": account_id, "kind": kind, "entry_key": key,
                             "effective_at_utc": effective_at, "payload_json": text, "payload_sha256": payload_sha,
                             "prev_hash": prev, "entry_hash": entry_hash,
                             "appended_at_utc": datetime.now(timezone.utc).isoformat()}
                replay(rows + [candidate])  # the account must stay readable after this entry
                conn.execute(
                    "INSERT INTO ledger_entries (account_id, kind, entry_key, effective_at_utc, payload_json, "
                    "payload_sha256, prev_hash, entry_hash, appended_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (account_id, kind, key, effective_at, text, payload_sha, prev, entry_hash,
                     datetime.now(timezone.utc).isoformat()))
                conn.execute("COMMIT")
                return entry_hash, True
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def open_account(self, account_id: str, *, starting_bankroll: Decimal, strategy: str, opened_at_utc: str,
                     sizing_policy_id: str, fill_policy_id: str, fee_schedule_id: str) -> tuple[str, bool]:
        if starting_bankroll <= 0:
            raise LedgerError("starting bankroll must be positive")
        payload = {"account_id": account_id, "starting_bankroll": str(starting_bankroll), "currency": "USD",
                   "strategy": strategy, "sizing_policy_id": sizing_policy_id, "fill_policy_id": fill_policy_id,
                   "fee_schedule_id": fee_schedule_id, "opened_at_utc": opened_at_utc, "simulation_only": True}

        def check(state: AccountState | None, rows: list[dict[str, Any]]) -> None:
            if state is not None:
                raise LedgerConflict(f"account {account_id} already opened")
        return self._append(account_id, "account_opened", account_id, opened_at_utc, payload, check)

    def record_decision(self, account_id: str, payload: dict[str, Any]) -> tuple[str, bool]:
        """`payload` must hold decision_id, opportunity_id, as_of_utc and qualification."""
        for name in ("decision_id", "opportunity_id", "as_of_utc", "qualification", "reason"):
            if name not in payload:
                raise LedgerError(f"decision payload lacks {name}")
        if payload["qualification"] not in ("QUALIFY", "REJECT"):
            raise LedgerError("qualification must be QUALIFY or REJECT")

        def check(state: AccountState | None, rows: list[dict[str, Any]]) -> None:
            if state is None:
                raise LedgerError("account not opened")
        return self._append(account_id, "decision", payload["decision_id"], payload["as_of_utc"], payload, check)

    def record_fill(self, account_id: str, payload: dict[str, Any]) -> tuple[str, bool]:
        """One fill entry per decision. FILLED needs a qualified decision and enough settled cash."""
        for name in ("fill_id", "decision_id", "status", "reason", "filled_at_utc"):
            if name not in payload:
                raise LedgerError(f"fill payload lacks {name}")
        if payload["status"] not in ("FILLED", "NO_FILL"):
            raise LedgerError("status must be FILLED or NO_FILL")
        decision = self.find(account_id, "decision", payload["decision_id"])
        if decision is None:
            raise LedgerError(f"fill for unknown decision {payload['decision_id']}")
        if payload["status"] == "FILLED":
            if decision["qualification"] != "QUALIFY":
                raise LedgerError("a rejected decision cannot fill")
            if payload.get("side") not in ("YES", "NO"):
                raise LedgerError("side must be YES or NO")
            quantity, price, cost = int(payload["quantity"]), _d(payload["price"]), _d(payload["total_cost"])
            if quantity <= 0 or not (Decimal(0) < price < Decimal(1)) or cost < quantity * price:
                raise LedgerError("FILLED needs quantity > 0, a price in (0, 1) and total_cost >= quantity * price")

        def check(state: AccountState | None, rows: list[dict[str, Any]]) -> None:
            if state is None:
                raise LedgerError("account not opened")
            if payload["status"] == "FILLED":
                if _d(payload["total_cost"]) > state.settled_cash:
                    raise LedgerError("insufficient settled cash: record NO_FILL INSUFFICIENT_CASH instead")
                known_at = _utc(payload["filled_at_utc"])
                # Cash-moving entries must arrive in knowledge-time order: a fill known earlier
                # than an already-recorded fill or settlement could otherwise be funded, at
                # some instant, by cash learned after it (out-of-order catch-up or a retried
                # older day). Such a fill is refused; the day needs attention, not a quiet pass.
                latest = max((knowledge_time(r) for r in rows if r["kind"] == "settlement" or (
                    r["kind"] == "fill" and json.loads(r["payload_json"]).get("status") == "FILLED")),
                    default=None, key=lambda t: t or datetime.min.replace(tzinfo=timezone.utc))
                if known_at is not None and latest is not None and known_at < latest:
                    raise LedgerError(f"out-of-order fill: known at {known_at.isoformat()} but the account already "
                                      f"records cash movements known at {latest.isoformat()}")
                if known_at is None or _d(payload["total_cost"]) > replay(rows, as_of=known_at).settled_cash:
                    raise LedgerError("cash known at the fill time does not cover it (a later settlement cannot "
                                      "fund an earlier fill): record NO_FILL INSUFFICIENT_CASH instead")
        return self._append(account_id, "fill", payload["decision_id"], payload["filled_at_utc"], payload, check)

    def record_settlement(self, account_id: str, *, fill_id: str, outcome: str, evidence: dict[str, Any],
                          settled_at_utc: str, fee: dict[str, Any] | None = None) -> tuple[str, bool]:
        """Settle one open position on an official outcome. P&L is computed here, from the fill."""
        if outcome not in ("YES", "NO"):
            raise LedgerError("outcome must be YES or NO (an unknown outcome is not settled)")
        fill = self.find(account_id, "fill", self._decision_of(account_id, fill_id))
        if fill is None or fill["status"] != "FILLED":
            raise LedgerError(f"no FILLED position {fill_id}")
        quantity, price, cost = int(fill["quantity"]), _d(fill["price"]), _d(fill["total_cost"])
        payout = Decimal(quantity) if outcome == fill["side"] else Decimal(0)
        payload = {
            "settlement_id": f"set-{fill_id}", "fill_id": fill_id, "market_id": fill["market_id"],
            "side": fill["side"], "outcome": outcome, "quantity": quantity, "payout": str(payout),
            "gross_pnl": str(payout - quantity * price), "fees": str(cost - quantity * price),
            "net_pnl": str(payout - cost), "evidence": evidence, "settled_at_utc": settled_at_utc,
            **(fee or {}),
        }

        known = _utc(evidence.get("evidence_available_utc")) if isinstance(evidence, dict) else None
        if known is not None:
            settled, filled = _utc(settled_at_utc), _utc(fill["filled_at_utc"])
            if settled is None or settled > known or (filled is not None and known < filled):
                raise LedgerError("settlement evidence must be received at or after both the settlement time "
                                  "and the fill")

        def check(state: AccountState | None, rows: list[dict[str, Any]]) -> None:
            position = next((p for p in state.positions if p.position_id == fill_id), None) if state else None
            if position is None or position.status != "OPEN":
                raise LedgerError(f"position {fill_id} is not open")
        return self._append(account_id, "settlement", fill_id, settled_at_utc, payload, check)

    def _decision_of(self, account_id: str, fill_id: str) -> str:
        with closing(self._connect()) as conn:
            for row in conn.execute("SELECT entry_key, payload_json FROM ledger_entries WHERE account_id = ? "
                                    "AND kind = 'fill'", (account_id,)):
                if json.loads(row["payload_json"])["fill_id"] == fill_id:
                    return row["entry_key"]
        return ""
