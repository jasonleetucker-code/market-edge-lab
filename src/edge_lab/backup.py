"""Manual, WAL-aware SQLite backup and isolated restore rehearsal.

Adapted from Brisket's online-backup pattern; no scheduling, remote upload,
retention deletion, source migration, or restoration over an existing database.
`retention-plan` is a dry-run report only (PROPOSED policy; it cannot delete).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .storage import SCHEMA_VERSION as CURRENT_SCHEMA_VERSION, SnapshotStore

KINDS = ("evidence", "ledger")

DB_NAME = "database.sqlite3"
MANIFEST_NAME = "manifest.json"
REQUIRED_TABLES = {"collection_runs", "snapshots"}
# Schema v2 introduced the immutability triggers; a database without them (v1) is
# never evidence-grade, so it is never reported VERIFIED.
MIN_SCHEMA_VERSION = 2
V2_IMMUTABILITY_TRIGGERS = frozenset({
    "snapshots_no_replace", "snapshots_no_update", "snapshots_no_delete",
    "source_health_no_update", "source_health_no_delete",
    "collection_runs_finish_once", "collection_runs_no_delete",
})
_reference_triggers_cache: frozenset[str] | None = None


def reference_triggers() -> frozenset[str]:
    """Every trigger a database created by the current code has (built, not hardcoded,
    so a future schema's triggers are required automatically)."""
    global _reference_triggers_cache
    if _reference_triggers_cache is None:
        with tempfile.TemporaryDirectory(prefix="edge-schema-ref-", ignore_cleanup_errors=True) as temp:
            path = Path(temp) / "reference.sqlite3"
            SnapshotStore(path)
            with closing(sqlite3.connect(path)) as conn:
                _reference_triggers_cache = frozenset(
                    row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                )
    return _reference_triggers_cache


_ledger_triggers_cache: frozenset[str] | None = None


def ledger_reference_triggers() -> frozenset[str]:
    """Every trigger a shadow ledger created by the current code has."""
    global _ledger_triggers_cache
    if _ledger_triggers_cache is None:
        from .shadow_ledger import ShadowLedger

        with tempfile.TemporaryDirectory(prefix="edge-ledger-ref-", ignore_cleanup_errors=True) as temp:
            path = Path(temp) / "reference.sqlite3"
            ShadowLedger(path)
            with closing(sqlite3.connect(path)) as conn:
                _ledger_triggers_cache = frozenset(
                    row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                )
    return _ledger_triggers_cache


def _ledger_chain_heads(conn: sqlite3.Connection) -> dict[str, str]:
    """Replay every account (checks every hash and invariant); the head hash per account."""
    from .shadow_ledger import LedgerError, replay

    conn.row_factory = sqlite3.Row
    try:
        accounts = [r[0] for r in conn.execute("SELECT DISTINCT account_id FROM ledger_entries ORDER BY account_id")]
        heads = {}
        for account in accounts:
            rows = conn.execute("SELECT * FROM ledger_entries WHERE account_id = ? ORDER BY seq", (account,)).fetchall()
            try:
                heads[account] = replay(rows).last_entry_hash
            except LedgerError as exc:
                # Recorded, not raised: a ledger with a broken chain must still be copied
                # (it is the forensic evidence). The report is never VERIFIED then.
                heads[account] = f"REPLAY_FAILED: {exc}"
        return heads
    finally:
        conn.row_factory = None


class BackupError(RuntimeError):
    """Backup or restore verification could not be established."""


def file_hash(path: Path, deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if deadline is not None and time.monotonic() >= deadline:
                raise BackupError("backup hashing exceeded its time budget")
            digest.update(chunk)
    return digest.hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"not an existing regular database file: {path}")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)


def deadline_after(seconds: float) -> float:
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be finite and positive")
    return time.monotonic() + seconds


def copy_online(source: sqlite3.Connection, destination: sqlite3.Connection, deadline: float) -> None:
    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() >= deadline:
            raise BackupError("online backup exceeded its time budget")
    source.backup(destination, pages=128, progress=progress, sleep=0.01)


def inspect_database(conn: sqlite3.Connection, deadline: float, *, require_current_schema: bool = True,
                     kind: str = "evidence") -> dict:
    """Integrity-check a database and fingerprint its schema, triggers and row counts.

    Fail-closed schema semantics when ``require_current_schema`` is true (the
    default, used everywhere in create/verify). The database is never reported
    VERIFIED if either of these holds:

    - ``PRAGMA user_version`` is newer than this code, or older than v2 (the first
      schema with immutability triggers);
    - it lacks any immutability trigger its version must have. At the current
      version, that is every trigger a freshly created ``SnapshotStore`` has
      (``reference_triggers``). At an older supported version, it is the v2 set.

    Older supported versions stay backup-able, so a pre-migration backup is always
    possible. Row counts and the trigger set are derived from ``sqlite_master``, so
    a future schema's tables and triggers are covered automatically.
    """
    if time.monotonic() >= deadline:
        raise BackupError("database verification exceeded its time budget")
    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity_check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign_key_check failed")
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = {name for type_, name, _, _ in schema if type_ == "table"}
        triggers = sorted(name for type_, name, _, _ in schema if type_ == "trigger")
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if kind == "ledger":
            from .shadow_ledger import LEDGER_SCHEMA_VERSION

            if "ledger_entries" not in tables:
                raise BackupError("not a Market Edge shadow ledger: ledger_entries missing")
            if schema_version != LEDGER_SCHEMA_VERSION:
                raise BackupError(f"ledger schema v{schema_version} != v{LEDGER_SCHEMA_VERSION}; refusing to report VERIFIED")
            # Missing triggers are recorded, not raised: a tampered ledger must still be copied
            # as forensic evidence. The report is then never VERIFIED.
            missing = sorted(ledger_reference_triggers() - set(triggers))
            counts = {"ledger_entries": conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]}
            return {"missing_triggers": missing,
                "store_kind": "ledger", "schema_version": schema_version,
                "schema_sha256": hashlib.sha256(json.dumps(schema, separators=(",", ":")).encode()).hexdigest(),
                "trigger_names": triggers, "row_counts": counts, "chain_heads": _ledger_chain_heads(conn),
            }
        if not REQUIRED_TABLES.issubset(tables):
            raise BackupError("not a Market Edge evidence database: required tables missing")
        if require_current_schema:
            if not MIN_SCHEMA_VERSION <= schema_version <= CURRENT_SCHEMA_VERSION:
                raise BackupError(
                    f"database schema v{schema_version} is outside the supported range "
                    f"v{MIN_SCHEMA_VERSION}..v{CURRENT_SCHEMA_VERSION}; refusing to report VERIFIED"
                )
            expected = (
                reference_triggers() if schema_version == CURRENT_SCHEMA_VERSION
                else V2_IMMUTABILITY_TRIGGERS
            )
            missing = sorted(expected - set(triggers))
            if missing:
                raise BackupError(
                    f"immutability triggers missing for schema v{schema_version}: {missing}; "
                    "refusing to report VERIFIED"
                )
        counts = {}
        for name in sorted(tables):
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        return {
            "schema_version": schema_version,
            "schema_sha256": hashlib.sha256(json.dumps(schema, separators=(",", ":")).encode()).hexdigest(),
            "trigger_names": triggers,
            "row_counts": counts,
        }
    finally:
        conn.set_progress_handler(None, 0)


def create_backup(source: Path, output: Path, *, timeout: float = 30, kind: str = "evidence") -> Path:
    """Create a unique bundle; manifest is published last. Never overwrite a backup."""
    deadline = deadline_after(timeout)
    started = datetime.now(timezone.utc).isoformat()
    # Verify source before creating output; a typo must never create an empty DB.
    with closing(read_only(source)) as src:
        output.mkdir(parents=True, exist_ok=True)
        bundle = Path(tempfile.mkdtemp(prefix="edge-backup-", dir=output))
        try:
            db = bundle / DB_NAME
            with closing(sqlite3.connect(db)) as dst:
                copy_online(src, dst, deadline)
                dst.execute("PRAGMA journal_mode = DELETE")
                summary = inspect_database(dst, deadline, kind=kind)
            source_summary = inspect_database(src, deadline, kind=kind)
            if summary != source_summary:
                # Covers the immutability triggers too: schema_sha256 hashes every
                # sqlite_master row (tables, triggers, indexes, views), not just
                # table names, so a trigger dropped or altered in transit is caught.
                raise BackupError(
                    "backup schema, triggers or row counts do not match the source database"
                )
            os.chmod(db, 0o600)
            # Open read-write (not "rb") to fsync: on Windows, os.fsync requires a
            # handle opened for writing — fsync on a read-only handle raises
            # OSError(EBADF) there, even though POSIX allows it.
            with db.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            manifest = {
                "format_version": 1, "database": DB_NAME, "store_kind": kind,
                "started_at_utc": started,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "database_sha256": file_hash(db, deadline), "database_bytes": db.stat().st_size,
                **summary,
            }
            temporary = bundle / ".manifest.tmp"
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(manifest, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(bundle / MANIFEST_NAME)
            return bundle
        except BaseException:
            # Only the unique directory created by this call is removed.
            shutil.rmtree(bundle)
            raise


def verify_backup(bundle: Path, *, timeout: float = 30) -> dict:
    """Validate bytes and restore into a disposable DB; never replace live state."""
    deadline = deadline_after(timeout)
    db, manifest_path = bundle / DB_NAME, bundle / MANIFEST_NAME
    if bundle.is_symlink() or manifest_path.is_symlink() or db.is_symlink():
        raise BackupError("symlinked backup bundles are not supported")
    if not manifest_path.is_file():
        raise BackupError("missing completion manifest; bundle is incomplete")
    if manifest_path.stat().st_size > 1024 * 1024:
        raise BackupError("manifest exceeds size limit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BackupError("invalid backup manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("database") != DB_NAME:
        raise BackupError("unsupported backup manifest")
    if not db.is_file() or db.stat().st_size != manifest.get("database_bytes") or file_hash(db, deadline) != manifest.get("database_sha256"):
        raise BackupError("backup byte hash or length mismatch")
    kind = manifest.get("store_kind", "evidence")
    if kind not in KINDS:
        raise BackupError(f"unknown store kind {kind!r}")
    with closing(read_only(db)) as src:
        original = inspect_database(src, deadline, kind=kind)
        for key, value in original.items():
            if manifest.get(key) != value:
                raise BackupError(f"backup manifest disagrees with {key}")
        with tempfile.TemporaryDirectory(prefix="edge-restore-check-") as temp:
            with closing(sqlite3.connect(Path(temp) / DB_NAME)) as restored:
                copy_online(src, restored, deadline)
                replay = inspect_database(restored, deadline, kind=kind)
                if replay != original:
                    raise BackupError("restored schema or row counts differ")
    chain_failures = sorted(a for a, h in (original.get("chain_heads") or {}).items() if str(h).startswith("REPLAY_FAILED"))
    status = ("BACKED_UP_LEDGER_TAMPERED_TRIGGERS" if original.get("missing_triggers")
              else "BACKED_UP_LEDGER_CHAIN_INVALID" if chain_failures else "VERIFIED_BACKUP_AND_RESTORE")
    return {"status": status, **original, "database_sha256": manifest["database_sha256"]}


# --------------------------------------------------------------------------- retention (DRY RUN ONLY)
#
# docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md, section B. No retention policy is approved. This
# planner only reads bundle directories and manifests and reports KEEP / DELETE-CANDIDATE / QUARANTINE
# per bundle with its reasons. It has no deletion code path at all: no --apply, no unlink, no rmtree
# (tests/test_backup_retention.py makes every deletion API fail while it runs). A backup copy is never
# the original evidence (the live store is), and a DELETE-CANDIDATE is only ever a bundle whose rows a
# newer kept, valid bundle of the same store also holds.

KEEP, DELETE_CANDIDATE, QUARANTINE = "KEEP", "DELETE-CANDIDATE", "QUARANTINE"
RETENTION_STATUS = "PROPOSED"  # never APPROVED in code: an approval is recorded in docs/EXECUTION_PLAN.md
BUNDLE_PREFIX = "edge-backup-"
MANIFEST_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RetentionPolicy:
    name: str
    keep_all_younger_than: timedelta  # every valid bundle this young is kept (deploy pairs, quick rollback)
    newest_good: int  # the newest N valid bundles per store are always kept
    daily_days: int  # the newest valid bundle of each UTC day, for this many days
    weekly_weeks: int  # ... of each ISO week, for this many weeks
    monthly_months: int  # ... of each calendar month, for this many months
    active_grace: timedelta  # a bundle without a manifest this young may still be being written
    max_newest_good_age: timedelta  # older newest-good bundle: nothing may become a candidate
    candidate_kinds: tuple[str, ...]  # stores whose bundles may become candidates at all
    future_tolerance: timedelta = timedelta(minutes=5)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": RETENTION_STATUS,
                "keep_all_younger_than_hours": self.keep_all_younger_than.total_seconds() / 3600,
                "newest_good": self.newest_good, "daily_days": self.daily_days, "weekly_weeks": self.weekly_weeks,
                "monthly_months": self.monthly_months,
                "active_grace_minutes": self.active_grace.total_seconds() / 60,
                "max_newest_good_age_hours": self.max_newest_good_age.total_seconds() / 3600,
                "candidate_kinds": list(self.candidate_kinds),
                "never_candidates": ["QUARANTINE", "ACTIVE", "no recorded restore verification",
                                     "newest good", "first bundle", "schema boundary",
                                     "checkpoint-linked", "pinned baseline", "forensic ledger state",
                                     "not covered by a newer kept bundle", "any bundle of a store not in candidate_kinds"]}


RETENTION_POLICIES = {
    "proposed-v1": RetentionPolicy(
        name="proposed-v1", keep_all_younger_than=timedelta(hours=48), newest_good=3, daily_days=7,
        weekly_weeks=8, monthly_months=12, active_grace=timedelta(minutes=30),
        max_newest_good_age=timedelta(hours=36), candidate_kinds=("evidence",)),
}


@dataclass
class BundleInfo:
    """What a read-only scan found for one bundle directory."""

    kind: str  # the store its location says (evidence: <root>, ledger: <root>/ledger)
    name: str
    path: str  # relative to the scanned root
    status: str  # GOOD | ACTIVE | QUARANTINE
    problems: list[str] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    completed: datetime | None = None
    database_bytes: int | None = None
    forensic: bool = False
    # A recorded VERIFIED_BACKUP_AND_RESTORE report exists for this bundle's database_sha256. A valid
    # manifest and size only prove the copy completed; only a recorded restore check makes a bundle
    # "good" (it may count as newest-good, keep the freshness check satisfied or cover older bundles).
    restore_verified: bool = False


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _newest_mtime(path: Path) -> datetime:
    times = [path.lstat().st_mtime]
    for child in path.iterdir():
        times.append(child.lstat().st_mtime)
    return datetime.fromtimestamp(max(times), timezone.utc)


def inspect_bundle(path: Path, *, kind: str, root: Path, now: datetime, policy: RetentionPolicy,
                   verify_hashes: bool = False) -> BundleInfo:
    """Classify one bundle directory from its manifest and file sizes (optionally its hash). Read-only."""
    info = BundleInfo(kind=kind, name=path.name, path=path.relative_to(root).as_posix(), status="GOOD")

    def bad(problem: str) -> BundleInfo:
        info.status = QUARANTINE
        info.problems.append(problem)
        return info

    if path.is_symlink():
        return bad("SYMLINK: symlinked bundles are never trusted")
    if not path.is_dir():
        return bad("NOT_A_DIRECTORY")
    manifest_path, db = path / MANIFEST_NAME, path / DB_NAME
    if manifest_path.is_symlink():
        return bad("SYMLINK: the manifest is a symlink")
    if not manifest_path.is_file():
        age = now - _newest_mtime(path)
        if age <= policy.active_grace:
            info.status = "ACTIVE"
            info.problems.append(f"ACTIVE_OR_IN_PROGRESS: no manifest yet, last written {int(age.total_seconds())} s ago")
            return info
        return bad("INCOMPLETE_NO_MANIFEST: no completion manifest and not written recently (an interrupted backup)")
    if manifest_path.stat().st_size > MANIFEST_MAX_BYTES:
        return bad("MANIFEST_INVALID: exceeds the size limit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        return bad(f"MANIFEST_INVALID: {type(exc).__name__}")
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("database") != DB_NAME:
        return bad("MANIFEST_INVALID: unsupported format")
    info.manifest = manifest
    store_kind = manifest.get("store_kind", "evidence")
    if store_kind not in KINDS:
        return bad(f"MANIFEST_INVALID: unknown store kind {store_kind!r}")
    if store_kind != kind:
        return bad(f"KIND_LOCATION_MISMATCH: a {store_kind} manifest in the {kind} directory")
    completed, started = _aware(manifest.get("completed_at_utc")), _aware(manifest.get("started_at_utc"))
    if completed is None or started is None:
        return bad("MANIFEST_INVALID: started/completed time missing or without a zone")
    if completed > now + policy.future_tolerance:
        return bad(f"FUTURE_TIMESTAMP: completed {completed.isoformat()} is after now")
    info.completed = completed
    size = manifest.get("database_bytes")
    info.database_bytes = size if isinstance(size, int) else None
    if db.is_symlink() or not db.is_file():
        return bad("DATABASE_MISSING")
    if db.stat().st_size != size:
        return bad(f"SIZE_MISMATCH: {db.stat().st_size} bytes, manifest says {size}")
    if verify_hashes and file_hash(db) != manifest.get("database_sha256"):
        return bad("HASH_MISMATCH: database bytes differ from the manifest")
    heads = manifest.get("chain_heads") or {}
    if kind == "ledger" and (manifest.get("missing_triggers")
                             or any(str(h).startswith("REPLAY_FAILED") for h in heads.values())):
        info.forensic = True
    return info


def load_verify_reports(path: Path) -> tuple[dict[str, str], int]:
    """Recorded `backup create` / `backup verify` reports: {database_sha256: bundle name or ""} for every
    VERIFIED_BACKUP_AND_RESTORE report, and the number of JSON reports read.

    Read-only. The input is text that contains the JSON reports the backup CLI prints (one per store and
    run), for example `journalctl -u edgelab-backup.service -o cat` saved to a file: pretty-printed
    reports and unrelated journal lines may be interleaved; every JSON object found is considered. A
    `create` report names its bundle; a `verify` report is identified by its database_sha256 only."""
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    verified: dict[str, str] = {}
    reports, i = 0, text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "status" in obj:
            reports += 1
            sha = obj.get("database_sha256")
            if obj.get("status") == "VERIFIED_BACKUP_AND_RESTORE" and isinstance(sha, str) and len(sha) == 64:
                verified[sha] = Path(str(obj.get("bundle") or "")).name
        i = text.find("{", end)
    return verified, reports


def scan_bundles(root: Path, *, now: datetime, policy: RetentionPolicy, verify_hashes: bool = False,
                 verified: Mapping[str, str] | None = None) -> tuple[list[BundleInfo], list[str]]:
    """Every bundle under `root` (evidence) and `root/ledger` (ledger). Returns (bundles, ignored entries).
    `verified` ({database_sha256: bundle name or ""}, from `load_verify_reports`) marks the bundles whose
    restore check is on record; a named report must name this bundle."""
    bundles: list[BundleInfo] = []
    ignored: list[str] = []
    for kind, directory in (("evidence", root), ("ledger", root / "ledger")):
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            if kind == "evidence" and entry.name == "ledger":
                continue
            if not entry.name.startswith(BUNDLE_PREFIX):
                ignored.append(entry.relative_to(root).as_posix())
                continue
            info = inspect_bundle(entry, kind=kind, root=root, now=now, policy=policy, verify_hashes=verify_hashes)
            sha = (info.manifest or {}).get("database_sha256")
            if info.status == "GOOD" and verified and sha in verified and verified[sha] in ("", info.name):
                info.restore_verified = True
            bundles.append(info)
    return bundles, ignored


def load_checkpoints(directory: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """F09 ledger checkpoints (ledger_anchor.export_checkpoint JSON files). Returns (checkpoints, problems)."""
    out, problems = [], []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError) as exc:
            problems.append(f"{path.name}: {type(exc).__name__}")
            continue
        created = _aware(data.get("created_at_utc")) if isinstance(data, dict) else None
        if created is None or not isinstance(data.get("accounts"), dict):
            problems.append(f"{path.name}: not a ledger checkpoint")
            continue
        out.append({"name": path.name, "created_at_utc": created,
                    "heads": {a: v.get("head_entry_hash") for a, v in data["accounts"].items() if isinstance(v, dict)}})
    return out, problems


def _covers(newer: BundleInfo, older: BundleInfo) -> bool:
    """Whether `newer` is a restore-verified copy of the same store that holds at least every table row count
    `older` holds (append-only stores). Same store identity: the same store kind and database name, a schema
    no older than the older bundle's, and, at the same schema version, the same schema fingerprint. A
    foreign bundle (another store, another schema lineage) never covers one of ours."""
    m_new, m_old = newer.manifest or {}, older.manifest or {}
    if not newer.restore_verified or newer.kind != older.kind:
        return False
    if m_new.get("store_kind", "evidence") != m_old.get("store_kind", "evidence") or m_new.get("database") != m_old.get("database"):
        return False
    v_new, v_old = m_new.get("schema_version"), m_old.get("schema_version")
    if not isinstance(v_new, int) or not isinstance(v_old, int) or v_new < v_old:
        return False
    if v_new == v_old and m_new.get("schema_sha256") != m_old.get("schema_sha256"):
        return False
    a, b = m_new.get("row_counts") or {}, m_old.get("row_counts") or {}
    if not isinstance(a, dict) or not isinstance(b, dict) or not b:
        return False
    return all(isinstance(a.get(t), int) and isinstance(n, int) and a[t] >= n for t, n in b.items())


def retention_plan(bundles: Sequence[BundleInfo], *, now: datetime, policy: RetentionPolicy,
                   checkpoints: Sequence[Mapping[str, Any]] = (), pins: Sequence[str] = ()) -> dict[str, Any]:
    """KEEP / DELETE-CANDIDATE / QUARANTINE per bundle, with reasons. Pure and deterministic."""
    reasons: dict[tuple[str, str], list[str]] = {}
    decision: dict[tuple[str, str], str] = {}
    flags: list[str] = []
    linked: list[dict[str, Any]] = []
    pinned = set(pins)
    found_pins: set[str] = set()
    for b in bundles:
        key = (b.kind, b.name)
        reasons[key] = list(b.problems)
        if b.status == QUARANTINE:
            decision[key] = QUARANTINE
        elif b.status == "ACTIVE":
            decision[key] = KEEP
        elif not b.restore_verified:
            # A valid manifest and size prove only that the copy completed. Without a recorded restore check
            # the bundle is kept, and never counts as newest-good, as fresh or as covering another bundle.
            decision[key] = KEEP
            reasons[key].append("UNVERIFIED_RESTORE: no recorded VERIFIED_BACKUP_AND_RESTORE report for its "
                                "database_sha256 (pass --verify-reports; or run `backup verify --bundle` and add it)")
    good_by_kind: dict[str, list[BundleInfo]] = {}
    for b in bundles:
        if b.status == "GOOD" and b.restore_verified:
            good_by_kind.setdefault(b.kind, []).append(b)
    for kind in KINDS:
        if any(b.kind == kind and b.status == "GOOD" and not b.restore_verified for b in bundles):
            flags.append(f"UNVERIFIED_PRESENT:{kind}")
        good = sorted(good_by_kind.get(kind, []), key=lambda b: (b.completed, b.name))
        if not good:
            if any(b.kind == kind for b in bundles):
                flags.append(f"NO_GOOD_BUNDLE:{kind}")
            continue

        def keep(b: BundleInfo, why: str) -> None:
            reasons[(b.kind, b.name)].append(why)

        for b in good[-policy.newest_good:]:
            keep(b, f"NEWEST_GOOD: one of the newest {policy.newest_good} valid bundles")
        keep(good[0], "FIRST_BUNDLE_BASELINE: the oldest valid bundle of this store")
        for b in good:
            if now - b.completed < policy.keep_all_younger_than:
                keep(b, f"RECENT: younger than {policy.keep_all_younger_than.total_seconds() / 3600:g} h")
            if b.name in pinned:
                keep(b, "PINNED_BASELINE: a known-good recovery baseline")
                found_pins.add(b.name)
            if b.forensic:
                keep(b, "FORENSIC_LEDGER_STATE: tampered triggers or a broken chain were recorded")
            if kind not in policy.candidate_kinds:
                keep(b, f"NOT_ELIGIBLE_KIND: {kind} bundles are never candidates under {policy.name}")
        today = now.date()
        daily: dict[Any, BundleInfo] = {}
        weekly: dict[Any, BundleInfo] = {}
        monthly: dict[Any, BundleInfo] = {}
        this_monday = today - timedelta(days=today.weekday())
        for b in good:  # sorted oldest first: the last assignment per bucket is the newest
            d = b.completed.date()
            if (today - d).days < policy.daily_days:
                daily[d] = b
            monday = d - timedelta(days=d.weekday())
            if (this_monday - monday).days // 7 < policy.weekly_weeks:
                weekly[monday] = b
            if (today.year - d.year) * 12 + today.month - d.month < policy.monthly_months:
                monthly[(d.year, d.month)] = b
        for d, b in daily.items():
            keep(b, f"DAILY: newest valid bundle of {d.isoformat()}")
        for monday, b in weekly.items():
            keep(b, f"WEEKLY: newest valid bundle of the week of {monday.isoformat()}")
        for (y, m), b in monthly.items():
            keep(b, f"MONTHLY: newest valid bundle of {y:04d}-{m:02d}")
        for older, newer in zip(good, good[1:]):
            s0 = ((older.manifest or {}).get("schema_version"), (older.manifest or {}).get("schema_sha256"))
            s1 = ((newer.manifest or {}).get("schema_version"), (newer.manifest or {}).get("schema_sha256"))
            if s0 != s1:
                keep(older, f"SCHEMA_BOUNDARY: the last bundle before schema v{s1[0]} ({newer.name})")
                keep(newer, f"SCHEMA_BOUNDARY: the first bundle at schema v{s1[0]} (after {older.name})")
        for cp in checkpoints:
            created, heads = cp["created_at_utc"], cp["heads"]
            before = [b for b in good if b.completed <= created]
            after = [b for b in good if b.completed >= created]
            bracket = ([before[-1]] if before else []) + ([after[0]] if after else [])
            if kind == "ledger":
                exact = [b for b in good if (b.manifest or {}).get("chain_heads") == heads]
                chosen, how = (exact, "EXACT") if exact else (bracket, "BRACKET")
            else:
                chosen, how = bracket, "EVIDENCE_BRACKET"
            for b in chosen:
                keep(b, f"CHECKPOINT_{how}: F09 checkpoint {cp['name']}")
            linked.append({"checkpoint": cp["name"], "kind": kind, "match": how if chosen else "NONE",
                           "bundles": sorted(b.name for b in chosen)})
        kept = [b for b in good if reasons[(b.kind, b.name)]]
        stale = now - good[-1].completed > policy.max_newest_good_age
        if stale:
            flags.append(f"NEWEST_GOOD_STALE:{kind}")
        for b in good:
            key = (b.kind, b.name)
            if reasons[key]:
                decision[key] = KEEP
                continue
            if stale:
                reasons[key].append(f"NEWEST_GOOD_STALE: the newest valid {kind} bundle completed "
                                    f"{good[-1].completed.isoformat()}; no candidate until a fresh verified backup")
                decision[key] = KEEP
                continue
            if not any(k.completed > b.completed and _covers(k, b) for k in kept):
                reasons[key].append("NOT_COVERED: no newer kept valid bundle holds at least its row counts")
                decision[key] = KEEP
                kept.append(b)
                continue
            reasons[key].append(f"SUPERSEDED: outside every {policy.name} keep rule; a newer kept valid bundle "
                                "holds all of its rows")
            decision[key] = DELETE_CANDIDATE
    if any(b.status == QUARANTINE for b in bundles):
        flags.append("QUARANTINE_PRESENT")
    rows, summary = [], {}
    for b in sorted(bundles, key=lambda b: (b.kind, b.completed or datetime.max.replace(tzinfo=timezone.utc), b.name)):
        d = decision[(b.kind, b.name)]
        rows.append({"kind": b.kind, "name": b.name, "path": b.path, "decision": d,
                     "reasons": sorted(reasons[(b.kind, b.name)]),
                     "completed_at_utc": b.completed.isoformat() if b.completed else None,
                     "database_bytes": b.database_bytes,
                     "schema_version": (b.manifest or {}).get("schema_version")})
        s = summary.setdefault(b.kind, {KEEP: 0, DELETE_CANDIDATE: 0, QUARANTINE: 0,
                                        "bytes_keep": 0, "bytes_delete_candidate": 0, "bytes_quarantine": 0})
        s[d] += 1
        s["bytes_" + d.lower().replace("-", "_")] += b.database_bytes or 0
    return {"command": "backup retention-plan", "mode": "DRY_RUN_ONLY", "deletes_performed": 0,
            "policy": policy.to_dict(), "now_utc": now.isoformat(), "state": "REVIEW" if flags else "OK",
            "flags": sorted(flags), "summary": dict(sorted(summary.items())), "bundles": rows,
            "checkpoints": linked, "pins_not_found": sorted(pinned - found_pins),
            "limitations": [
                "a backup copy is not original evidence: the live store is the original, and no candidate is the "
                "only copy of its rows (a newer kept bundle covers it)",
                "a checkpoint hash is not a restorable backup; no verified off-host backup exists",
                "a bundle is good only with a recorded VERIFIED_BACKUP_AND_RESTORE report (--verify-reports); the "
                "planner does not restore anything itself. Any future apply step must restore-verify every bundle "
                "it relies on (for coverage and for freshness) immediately before deleting anything",
                "hashes are checked only with --verify-hashes",
                "nothing is deleted: this planner has no deletion code path; any deletion needs an approved policy"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    create = subs.add_parser("create")
    create.add_argument("--db", type=Path, required=True)
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--timeout", type=float, default=30)
    create.add_argument("--kind", choices=KINDS, default="evidence")
    create.add_argument("--if-exists", action="store_true",
                        help="exit 0 with SKIPPED_NO_SOURCE when the source does not exist yet (ledger before its first run)")
    create.add_argument("--lock-file", type=Path, help="hold this flock while copying (shared with ledger writers)")
    verify = subs.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--timeout", type=float, default=30)
    plan = subs.add_parser("retention-plan", help="DRY RUN ONLY: KEEP / DELETE-CANDIDATE / QUARANTINE per bundle; "
                                                  "deletes nothing (there is no apply option)")
    plan.add_argument("--root", type=Path, required=True, help="the backups directory (ledger bundles in root/ledger)")
    plan.add_argument("--policy", choices=sorted(RETENTION_POLICIES), default="proposed-v1")
    plan.add_argument("--now", help="ISO-8601 time with zone (default: now)")
    plan.add_argument("--checkpoints", type=Path, help="directory of F09 ledger checkpoint JSON files")
    plan.add_argument("--pin", action="append", default=[], help="bundle name kept as a known-good baseline")
    plan.add_argument("--verify-hashes", action="store_true", help="also check every database's SHA-256 (reads it)")
    plan.add_argument("--verify-reports", type=Path,
                      help="text holding the recorded backup create/verify JSON reports (e.g. `journalctl -u "
                           "edgelab-backup.service -o cat` saved to a file); only bundles with a recorded "
                           "VERIFIED_BACKUP_AND_RESTORE report are good, all others are kept")
    args = parser.parse_args(argv)
    if args.command == "retention-plan":
        return _retention_main(args)
    try:
        if args.command == "create":
            if args.if_exists and not args.db.exists():
                print(json.dumps({"status": "SKIPPED_NO_SOURCE", "kind": args.kind, "db": str(args.db)}))
                return 0
            if args.lock_file is not None:
                from .forward import LockBusy, exclusive_lock

                try:
                    with exclusive_lock(args.lock_file, timeout_s=args.timeout):
                        bundle = create_backup(args.db, args.out, timeout=args.timeout, kind=args.kind)
                except LockBusy as exc:
                    raise BackupError(str(exc)) from exc
            else:
                bundle = create_backup(args.db, args.out, timeout=args.timeout, kind=args.kind)
            report = verify_backup(bundle, timeout=args.timeout)
            report["bundle"] = str(bundle)
        else:
            report = verify_backup(args.bundle, timeout=args.timeout)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "VERIFIED_BACKUP_AND_RESTORE" else 1
    except (BackupError, sqlite3.Error, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 1


def _retention_main(args: argparse.Namespace) -> int:
    now = _aware(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(json.dumps({"status": "FAILED", "error": "--now needs a zone"}))
        return 2
    if not args.root.is_dir():
        print(json.dumps({"status": "FAILED", "error": f"{args.root} is not a directory"}))
        return 1
    policy = RETENTION_POLICIES[args.policy]
    verified, n_reports = load_verify_reports(args.verify_reports) if args.verify_reports else ({}, 0)
    bundles, ignored = scan_bundles(args.root, now=now, policy=policy, verify_hashes=args.verify_hashes,
                                    verified=verified)
    checkpoints, problems = load_checkpoints(args.checkpoints) if args.checkpoints else ([], [])
    report = retention_plan(bundles, now=now, policy=policy, checkpoints=checkpoints, pins=args.pin)
    report.update(root=str(args.root), ignored_entries=ignored, checkpoint_problems=problems,
                  hashes_verified=bool(args.verify_hashes),
                  verify_reports={"file": str(args.verify_reports) if args.verify_reports else None,
                                  "reports_read": n_reports, "verified_database_sha256s": len(verified)})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
