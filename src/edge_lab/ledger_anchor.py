"""Ledger head checkpoints (GATE7-F09, ADR 0021). Read-only; no scheduling, no network.

The shadow ledger's per-account hash chain exposes any edit, reordering or middle deletion.
It cannot expose removal of the *newest* entries: what is left is a valid, shorter chain.
Only a record of the head, kept somewhere the ledger's writer cannot change, closes that gap.

This module produces and checks such a record:

- `export_checkpoint` reads a ledger and returns a small JSON-able checkpoint. It holds each
  account's entry count and head (seq, entry hash, effective time).
- `verify_checkpoint` compares a ledger with an earlier checkpoint and returns an
  `AnchorVerdict`: VERIFIED, EXTENDED (appended since, history intact), TRUNCATED,
  REWRITTEN, ACCOUNT_MISSING, CHAIN_INVALID or INVALID_CHECKPOINT.

A checkpoint is independent evidence **only** when it is stored outside the ledger writer's
authority (ADR 0021 compares the options by attacker). `checkpoint_sha256` is a plain digest
that catches a damaged or hand-edited file; it is not a keyed signature, and anyone can
recompute it. Nothing here writes to the ledger: both functions accept a ledger opened with
`ShadowLedger.open_readonly`.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .shadow_ledger import LEDGER_SCHEMA_VERSION, LedgerError, ShadowLedger, canonical, replay

CHECKPOINT_SCHEMA = "edge-lab-ledger-checkpoint/1"

# Worst status wins. A broken checkpoint says nothing about the ledger, so it outranks all;
# a broken chain means the ledger cannot be trusted at all; a rewritten head is deliberate
# forgery; a missing account is a whole-account truncation.
STATUS_ORDER = ("VERIFIED", "EXTENDED", "TRUNCATED", "ACCOUNT_MISSING", "REWRITTEN", "CHAIN_INVALID",
                "INVALID_CHECKPOINT")
PASSING = frozenset({"VERIFIED", "EXTENDED"})

_HEX64 = re.compile(r"[0-9a-f]{64}")
_CHAIN_ERRORS = (LedgerError, ValueError, KeyError, TypeError, ArithmeticError)

LIMITATION = ("A checkpoint is independent evidence only if it was stored where the ledger's writer "
              "cannot change it (ADR 0021). Verifying against a copy kept beside the ledger proves nothing.")


def _digest(checkpoint: dict[str, Any]) -> str:
    body = {k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _worst(statuses) -> str:
    return max(statuses, key=STATUS_ORDER.index, default="VERIFIED")


def _snapshot(ledger: ShadowLedger) -> dict[str, list[dict[str, Any]]]:
    """Every account's rows from one read transaction, so a checkpoint is one instant."""
    with closing(ledger._connect()) as conn:
        conn.execute("BEGIN")
        try:
            rows = [dict(r) for r in conn.execute("SELECT * FROM ledger_entries ORDER BY seq")]
        finally:
            conn.execute("ROLLBACK")
    accounts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        accounts.setdefault(row["account_id"], []).append(row)
    return accounts


def _chain_problem(rows: list[dict[str, Any]]) -> str | None:
    """The replay half of `ShadowLedger.verify_chain` (every hash, every invariant), applied to
    the snapshot rows. Returns the problem, or None."""
    try:
        replay(rows)
    except _CHAIN_ERRORS as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _schema_problem(ledger: ShadowLedger) -> str | None:
    """The trigger half of `ShadowLedger.verify_chain`: a dropped append-only trigger is tampering."""
    try:
        ledger.verify_schema()
    except LedgerError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


# --------------------------------------------------------------------------- export


def export_checkpoint(ledger: ShadowLedger, *, now: datetime) -> dict[str, Any]:
    """A checkpoint of every account's head. Refuses (LedgerError) an empty ledger or one whose
    chain does not verify: anchoring a broken ledger would bless it."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    snapshot = _snapshot(ledger)
    if not snapshot:
        raise LedgerError(f"ledger {ledger.path.name} has no entries: nothing to anchor")
    schema_problem = _schema_problem(ledger)
    if schema_problem is not None:
        raise LedgerError(f"ledger {ledger.path.name} does not verify, refusing to anchor it: {schema_problem}")
    accounts: dict[str, dict[str, Any]] = {}
    for account_id, rows in sorted(snapshot.items()):
        problem = _chain_problem(rows)
        if problem is not None:
            raise LedgerError(f"account {account_id!r} does not verify, refusing to anchor it: {problem}")
        head = rows[-1]
        accounts[account_id] = {"entries": len(rows), "head_seq": head["seq"], "head_entry_hash": head["entry_hash"],
                                "head_effective_at_utc": head["effective_at_utc"]}
    checkpoint: dict[str, Any] = {
        "schema": CHECKPOINT_SCHEMA,
        "created_at_utc": now.isoformat(),
        "ledger_file": ledger.path.name,
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "accounts": accounts,
    }
    checkpoint["checkpoint_sha256"] = _digest(checkpoint)
    return checkpoint


# --------------------------------------------------------------------------- verify


@dataclass(frozen=True)
class AccountVerdict:
    account_id: str
    status: str
    checkpoint_entries: int | None
    current_entries: int | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class AnchorVerdict:
    status: str
    accounts: tuple[AccountVerdict, ...] = ()
    new_accounts: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    checkpoint_sha256: str | None = None
    checkpoint_created_at_utc: str | None = None
    checkpoint_ledger_file: str | None = None
    ledger_file: str | None = None
    notes: tuple[str, ...] = field(default=(LIMITATION,))

    @property
    def ok(self) -> bool:
        return self.status in PASSING

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "accounts": [a.to_dict() for a in self.accounts],
            "new_accounts": list(self.new_accounts),
            "problems": list(self.problems),
            "checkpoint_sha256": self.checkpoint_sha256,
            "checkpoint_created_at_utc": self.checkpoint_created_at_utc,
            "checkpoint_ledger_file": self.checkpoint_ledger_file,
            "ledger_file": self.ledger_file,
            "notes": list(self.notes),
        }


def checkpoint_problems(checkpoint: Any) -> list[str]:
    """Why a checkpoint is unusable (schema, shape, digest); empty when it is well formed."""
    if not isinstance(checkpoint, dict):
        return ["checkpoint is not a JSON object"]
    problems = []
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        problems.append(f"schema is {checkpoint.get('schema')!r}, expected {CHECKPOINT_SCHEMA!r}")
    version = checkpoint.get("ledger_schema_version")
    if isinstance(version, bool) or version != LEDGER_SCHEMA_VERSION:
        problems.append(f"ledger_schema_version is {checkpoint.get('ledger_schema_version')!r}, "
                        f"this code reads {LEDGER_SCHEMA_VERSION}")
    from .freshness import parse_utc
    if parse_utc(checkpoint.get("created_at_utc")) is None:
        problems.append("created_at_utc is missing or not an ISO-8601 instant with a zone")
    accounts = checkpoint.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        problems.append("accounts is missing or empty")
    else:
        for account_id, head in accounts.items():
            if not isinstance(head, dict):
                problems.append(f"account {account_id!r}: head is not an object")
                continue
            count, seq = head.get("entries"), head.get("head_seq")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                problems.append(f"account {account_id!r}: entries must be a positive integer")
            if isinstance(seq, bool) or not isinstance(seq, int):
                problems.append(f"account {account_id!r}: head_seq must be an integer")
            if not isinstance(head.get("head_entry_hash"), str) or not _HEX64.fullmatch(head["head_entry_hash"]):
                problems.append(f"account {account_id!r}: head_entry_hash must be 64 lowercase hex characters")
            if not isinstance(head.get("head_effective_at_utc"), str):
                problems.append(f"account {account_id!r}: head_effective_at_utc must be a string")
    stated = checkpoint.get("checkpoint_sha256")
    if not isinstance(stated, str) or stated != _digest(checkpoint):
        problems.append("checkpoint_sha256 does not match the checkpoint content")
    return problems


def _verify_account(account_id: str, head: dict[str, Any], rows: list[dict[str, Any]] | None) -> AccountVerdict:
    expected = head["entries"]
    if rows is None:
        return AccountVerdict(account_id, "ACCOUNT_MISSING", expected, None,
                              "the account was in the checkpoint and has no entries now")
    current = len(rows)
    if current < expected:
        return AccountVerdict(account_id, "TRUNCATED", expected, current,
                              f"{expected - current} entr{'y' if expected - current == 1 else 'ies'} "
                              f"missing from the head since the checkpoint")
    # Chain verified: an equal hash at the checkpoint head position means the whole prefix is
    # unchanged, because every entry hash covers the one before it.
    at_head = rows[expected - 1]
    if at_head["entry_hash"] != head["head_entry_hash"]:
        return AccountVerdict(account_id, "REWRITTEN", expected, current,
                              f"entry {expected} of the account has hash {at_head['entry_hash']}, the checkpoint "
                              f"recorded {head['head_entry_hash']}")
    seq_note = "" if at_head["seq"] == head["head_seq"] else (
        f"; head seq is now {at_head['seq']} (checkpoint {head['head_seq']}): seq is not hashed, content is identical")
    if current == expected:
        return AccountVerdict(account_id, "VERIFIED", expected, current, "head unchanged" + seq_note)
    return AccountVerdict(account_id, "EXTENDED", expected, current,
                          f"history intact; {current - expected} entr{'y' if current - expected == 1 else 'ies'} "
                          f"appended since the checkpoint" + seq_note)


def verify_checkpoint(ledger: ShadowLedger, checkpoint: Any) -> AnchorVerdict:
    """Compare the ledger with an earlier checkpoint. Reads only.

    Order: the checkpoint's own schema and digest (INVALID_CHECKPOINT), then every current
    account's chain (CHAIN_INVALID), then each checkpointed account's head. Accounts opened
    after the checkpoint are listed in `new_accounts`; that is not a failure."""
    problems = checkpoint_problems(checkpoint)
    ledger_file = ledger.path.name
    if problems:
        sha = checkpoint.get("checkpoint_sha256") if isinstance(checkpoint, dict) else None
        return AnchorVerdict("INVALID_CHECKPOINT", problems=tuple(problems),
                             checkpoint_sha256=sha if isinstance(sha, str) else None, ledger_file=ledger_file)
    snapshot = _snapshot(ledger)
    schema_problem = _schema_problem(ledger)
    verdicts: list[AccountVerdict] = []
    broken: set[str] = set()
    for account_id, rows in sorted(snapshot.items()):
        problem = _chain_problem(rows) or schema_problem
        if problem is not None:
            broken.add(account_id)
            verdicts.append(AccountVerdict(account_id, "CHAIN_INVALID", checkpoint["accounts"].get(account_id, {}).get(
                "entries"), len(rows), problem))
    for account_id, head in sorted(checkpoint["accounts"].items()):
        if account_id not in broken:
            verdicts.append(_verify_account(account_id, head, snapshot.get(account_id)))
    new = tuple(sorted(set(snapshot) - set(checkpoint["accounts"])))
    statuses = [v.status for v in verdicts] + (["CHAIN_INVALID"] if schema_problem else [])
    return AnchorVerdict(
        _worst(statuses), accounts=tuple(sorted(verdicts, key=lambda v: v.account_id)),
        new_accounts=new, problems=(schema_problem,) if schema_problem else (), checkpoint_sha256=checkpoint["checkpoint_sha256"],
        checkpoint_created_at_utc=checkpoint["created_at_utc"], checkpoint_ledger_file=checkpoint.get("ledger_file"),
        ledger_file=ledger_file)


__all__ = ["CHECKPOINT_SCHEMA", "STATUS_ORDER", "AccountVerdict", "AnchorVerdict", "checkpoint_problems",
           "export_checkpoint", "verify_checkpoint"]
