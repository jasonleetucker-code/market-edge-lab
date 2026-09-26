"""Manual, WAL-aware SQLite backup and isolated restore rehearsal.

Adapted from Brisket's online-backup pattern; no scheduling, remote upload, source migration,
or restoration over an existing database.
`retention-plan` is a dry-run report only (it cannot delete). `retention-apply` is the only
deletion path: manual, reviewed, owner-approved policy proposed-v1 (2026-09-26), never on a timer.
`newest-verified` and `offhost-verify` support the O1 weekly off-host pull (read-only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
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
# docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md, section B. The owner approved policy proposed-v1 on
# 2026-09-26 (docs/owner/2026-09-26-owner-decisions-economics-backup.md). This planner still only reads
# bundle directories and manifests and reports KEEP / DELETE-CANDIDATE / QUARANTINE per bundle with its
# reasons: it has no deletion code path (tests/test_backup_retention.py checks every function reachable
# from its CLI entry point, and makes every deletion API fail while it runs). Deletion is only the
# separate, manual `retention-apply` below. A backup copy is never the original evidence (the live store
# is), and a DELETE-CANDIDATE is only ever a bundle whose rows a newer kept, restore-verified copy of the
# same store also holds.

KEEP, DELETE_CANDIDATE, QUARANTINE = "KEEP", "DELETE-CANDIDATE", "QUARANTINE"
# The owner's approval is the record (docs/owner/2026-09-26-...); code never grants one.
RETENTION_STATUS = "APPROVED 2026-09-26 (owner; manual, reviewed apply only)"
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
    # Known-good baselines this policy always keeps, whatever --pin says (committed, reviewed).
    pins: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": RETENTION_STATUS,
                "keep_all_younger_than_hours": self.keep_all_younger_than.total_seconds() / 3600,
                "newest_good": self.newest_good, "daily_days": self.daily_days, "weekly_weeks": self.weekly_weeks,
                "monthly_months": self.monthly_months,
                "active_grace_minutes": self.active_grace.total_seconds() / 60,
                "max_newest_good_age_hours": self.max_newest_good_age.total_seconds() / 3600,
                "candidate_kinds": list(self.candidate_kinds), "pins": list(self.pins),
                "never_candidates": ["QUARANTINE", "ACTIVE", "no recorded restore verification",
                                     "newest good", "first bundle", "schema boundary",
                                     "checkpoint-linked", "pinned baseline", "forensic ledger state",
                                     "not covered by a newer kept bundle", "any bundle of a store not in candidate_kinds"]}


# The known-good baselines of CAPTURE_AND_BACKUP_APPROVAL_PLAN.md B4 ("Proposed initial pins"), always kept:
# - edge-backup-eqfiomf5: the first production activation (2026-09-23 17:29Z);
# - lqs5j63_ and sdi31qqw: the ledger bundles copied to the laptop and checked at F09 (ledger bundles are never
#   candidates anyway; pinned so the baseline set is explicit);
# - "the bundles around the first real settlement (2026-09-25)": the settlement ran at 11:15 ET (15:15Z), so
#   the last evidence bundles before it (08:02Z iu9x5w73, 08:03Z gci308lm) and the first after it
#   (20:16Z lgw9jmww, 20:17Z wu3982g7).
RETENTION_PINS_PROPOSED_V1 = ("edge-backup-eqfiomf5", "edge-backup-lqs5j63_", "edge-backup-sdi31qqw",
                              "edge-backup-iu9x5w73", "edge-backup-gci308lm", "edge-backup-lgw9jmww",
                              "edge-backup-wu3982g7")

RETENTION_POLICIES = {
    "proposed-v1": RetentionPolicy(
        name="proposed-v1", keep_all_younger_than=timedelta(hours=48), newest_good=3, daily_days=7,
        weekly_weeks=8, monthly_months=12, active_grace=timedelta(minutes=30),
        max_newest_good_age=timedelta(hours=36), candidate_kinds=("evidence",), pins=RETENTION_PINS_PROPOSED_V1),
}

# The canonical F09 checkpoint directory: the running code's own committed set (in production
# /opt/market-edge-lab/app/docs/engineering/ledger_checkpoints, the root-owned checkout at REVISION).
CANONICAL_CHECKPOINTS = Path(__file__).resolve().parents[2] / "docs" / "engineering" / "ledger_checkpoints"


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
    pinned = set(pins) | set(policy.pins)  # the policy's committed pins apply with or without --pin
    covered_by: dict[tuple[str, str], str] = {}
    newest_good: dict[str, str] = {}
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
            coverers = [k for k in kept if k.completed > b.completed and _covers(k, b)]
            if not coverers:
                reasons[key].append("NOT_COVERED: no newer kept valid bundle holds at least its row counts")
                decision[key] = KEEP
                kept.append(b)
                continue
            # The newest covering bundle is the one a deletion relies on (the apply step restore-verifies it).
            covered_by[key] = max(coverers, key=lambda k: (k.completed, k.name)).name
            reasons[key].append(f"SUPERSEDED: outside every {policy.name} keep rule; a newer kept valid bundle "
                                "holds all of its rows")
            decision[key] = DELETE_CANDIDATE
        newest_good[kind] = good[-1].name
    if any(b.status == QUARANTINE for b in bundles):
        flags.append("QUARANTINE_PRESENT")
    rows, summary = [], {}
    for b in sorted(bundles, key=lambda b: (b.kind, b.completed or datetime.max.replace(tzinfo=timezone.utc), b.name)):
        d = decision[(b.kind, b.name)]
        rows.append({"kind": b.kind, "name": b.name, "path": b.path, "decision": d,
                     "reasons": sorted(reasons[(b.kind, b.name)]),
                     "completed_at_utc": b.completed.isoformat() if b.completed else None,
                     "database_bytes": b.database_bytes,
                     "database_sha256": (b.manifest or {}).get("database_sha256"),
                     "covered_by": covered_by.get((b.kind, b.name)),
                     "schema_version": (b.manifest or {}).get("schema_version")})
        s = summary.setdefault(b.kind, {KEEP: 0, DELETE_CANDIDATE: 0, QUARANTINE: 0,
                                        "bytes_keep": 0, "bytes_delete_candidate": 0, "bytes_quarantine": 0})
        s[d] += 1
        s["bytes_" + d.lower().replace("-", "_")] += b.database_bytes or 0
    return {"command": "backup retention-plan", "mode": "DRY_RUN_ONLY", "deletes_performed": 0,
            "policy": policy.to_dict(), "now_utc": now.isoformat(), "state": "REVIEW" if flags else "OK",
            "flags": sorted(flags), "summary": dict(sorted(summary.items())), "bundles": rows,
            "newest_good": dict(sorted(newest_good.items())),
            "checkpoints": linked, "pins_not_found": sorted(set(pins) - found_pins),
            "policy_pins_found": sorted(set(policy.pins) & found_pins),
            "limitations": [
                "a backup copy is not original evidence: the live store is the original, and no candidate is the "
                "only copy of its rows (a newer kept bundle covers it)",
                "a checkpoint hash is not a restorable backup; no verified off-host backup exists",
                "a bundle is good only with a recorded VERIFIED_BACKUP_AND_RESTORE report (--verify-reports); the "
                "planner does not restore anything itself. Any future apply step must restore-verify every bundle "
                "it relies on (for coverage and for freshness) immediately before deleting anything",
                "hashes are checked only with --verify-hashes",
                "nothing is deleted: this planner has no deletion code path; deletion is only the separate, manual "
                "`retention-apply` of a reviewed report of this plan"]}


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
                                                  "deletes nothing (deletion is the separate retention-apply)")
    plan.add_argument("--root", type=Path, required=True, help="the backups directory (ledger bundles in root/ledger)")
    plan.add_argument("--policy", choices=sorted(RETENTION_POLICIES), default="proposed-v1")
    plan.add_argument("--now", help="ISO-8601 time with zone (default: now)")
    plan.add_argument("--checkpoints", type=Path, help="directory of F09 ledger checkpoint JSON files; an apply "
                                                       f"requires the canonical {CANONICAL_CHECKPOINTS}")
    plan.add_argument("--pin", action="append", default=[], help="bundle name kept as a known-good baseline")
    plan.add_argument("--verify-hashes", action="store_true", help="also check every database's SHA-256 (reads it)")
    plan.add_argument("--verify-reports", type=Path,
                      help="text holding the recorded backup create/verify JSON reports (e.g. `journalctl -u "
                           "edgelab-backup.service -o cat` saved to a file); only bundles with a recorded "
                           "VERIFIED_BACKUP_AND_RESTORE report are good, all others are kept")
    apply = subs.add_parser("retention-apply",
                            help="MANUAL, REVIEWED deletion of exactly the DELETE-CANDIDATE bundles of a fresh "
                                 "retention-plan report (owner-approved proposed-v1); refuses on any doubt")
    apply.add_argument("--root", type=Path, required=True, help="the backups directory the report was made for")
    apply.add_argument("--report", type=Path, required=True, help="the reviewed retention-plan JSON report (file)")
    apply.add_argument("--confirm", required=True, help="the SHA-256 of the report file (sha256sum REPORT)")
    apply.add_argument("--max-report-age-min", type=float, default=APPLY_MAX_REPORT_AGE.total_seconds() / 60,
                       help="at most 30 (larger values are refused)")
    apply.add_argument("--timeout", type=float, default=APPLY_VERIFY_TIMEOUT_S,
                       help="per-bundle budget for the restore verification of the bundles relied on")
    newest = subs.add_parser("newest-verified", help="read-only: the newest restore-verified evidence and ledger "
                                                     "bundle (the O1 pull's source)")
    newest.add_argument("--root", type=Path, required=True)
    newest.add_argument("--verify-reports", type=Path, required=True)
    offhost = subs.add_parser("offhost-verify", help="O1, on the laptop: verify every bundle copied under --dir "
                                                     "(bytes against the manifest, then a restore check)")
    offhost.add_argument("--dir", type=Path, required=True)
    offhost.add_argument("--timeout", type=float, default=120)
    prune = subs.add_parser("offhost-prune", help="O1, on the laptop: keep the newest --keep VERIFIED pulls (dated "
                                                  "dirs with VERIFIED.json); lists only unless --apply")
    prune.add_argument("--base", type=Path, required=True)
    prune.add_argument("--keep", type=int, default=4)
    prune.add_argument("--apply", action="store_true", help="remove the older verified pulls listed")
    args = parser.parse_args(argv)
    if args.command == "retention-plan":
        return _retention_main(args)
    if args.command == "retention-apply":
        return _apply_main(args)
    if args.command == "newest-verified":
        return _newest_verified_main(args)
    if args.command == "offhost-prune":
        return _offhost_prune_main(args)
    if args.command == "offhost-verify":
        return _offhost_verify_main(args)
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


def _checkpoint_files(directory: Path) -> list[dict[str, str]]:
    return [{"name": p.name, "sha256": file_hash(p)} for p in sorted(directory.glob("*.json"))]


def build_plan(root: Path, *, now: datetime, policy: RetentionPolicy, checkpoints_dir: Path | None = None,
               verify_reports: Path | None = None, pins: Sequence[str] = (), verify_hashes: bool = False) -> dict[str, Any]:
    """The `retention-plan` report, with the inputs it used recorded (paths and content hashes), so the apply
    step can re-run exactly the same plan. Read-only."""
    verified, n_reports = load_verify_reports(verify_reports) if verify_reports else ({}, 0)
    bundles, ignored = scan_bundles(root, now=now, policy=policy, verify_hashes=verify_hashes, verified=verified)
    checkpoints, problems = load_checkpoints(checkpoints_dir) if checkpoints_dir else ([], [])
    report = retention_plan(bundles, now=now, policy=policy, checkpoints=checkpoints, pins=pins)
    report.update(
        root=str(root.resolve()), ignored_entries=ignored, checkpoint_problems=problems,
        hashes_verified=bool(verify_hashes),
        verify_reports={"file": str(verify_reports) if verify_reports else None, "reports_read": n_reports,
                        "verified_database_sha256s": len(verified)},
        inputs={"policy": policy.name, "pins": sorted(set(pins) | set(policy.pins)), "verify_hashes": bool(verify_hashes),
                "checkpoints_dir": str(checkpoints_dir.resolve()) if checkpoints_dir else None,
                "checkpoint_files": _checkpoint_files(checkpoints_dir) if checkpoints_dir else [],
                "verify_reports_file": str(verify_reports.resolve()) if verify_reports else None,
                "verify_reports_sha256": file_hash(verify_reports) if verify_reports else None})
    return report


def _retention_main(args: argparse.Namespace) -> int:
    now = _aware(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(json.dumps({"status": "FAILED", "error": "--now needs a zone"}))
        return 2
    if not args.root.is_dir():
        print(json.dumps({"status": "FAILED", "error": f"{args.root} is not a directory"}))
        return 1
    report = build_plan(args.root, now=now, policy=RETENTION_POLICIES[args.policy], checkpoints_dir=args.checkpoints,
                        verify_reports=args.verify_reports, pins=args.pin, verify_hashes=args.verify_hashes)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def newest_verified(root: Path, *, verify_reports: Path, now: datetime) -> dict[str, Any]:
    """The newest restore-verified bundle per store (the O1 weekly pull's source). Read-only."""
    verified, n = load_verify_reports(verify_reports)
    bundles, _ = scan_bundles(root, now=now, policy=RETENTION_POLICIES["proposed-v1"], verified=verified)
    out: dict[str, Any] = {"command": "backup newest-verified", "root": str(root.resolve()), "reports_read": n}
    for kind in KINDS:
        good = sorted((b for b in bundles if b.kind == kind and b.status == "GOOD" and b.restore_verified),
                      key=lambda b: (b.completed, b.name))
        out[kind] = None if not good else {
            "name": good[-1].name, "path": good[-1].path, "completed_at_utc": good[-1].completed.isoformat(),
            "database_bytes": good[-1].database_bytes,
            "database_sha256": (good[-1].manifest or {}).get("database_sha256")}
    out["state"] = "OK" if out["evidence"] and out["ledger"] else "MISSING_VERIFIED_BUNDLE"
    return out


def _newest_verified_main(args: argparse.Namespace) -> int:
    report = newest_verified(args.root, verify_reports=args.verify_reports, now=datetime.now(timezone.utc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "OK" else 1


def offhost_verify(directory: Path, *, timeout: float = 120) -> dict[str, Any]:
    """O1: verify every bundle copied off-host under `directory` (bundles directly in it or one level down,
    e.g. <date>/edge-backup-… and <date>/ledger/edge-backup-…). For each: the database bytes against the
    manifest's length and SHA-256, then `verify_backup` (a restore into a disposable database). Read-only
    for the bundles. On VERIFIED (every bundle passes, at least one evidence and one ledger bundle) it writes
    `VERIFIED.json` in `directory`; otherwise it removes a stale one, so only verified pulls count for
    `offhost-prune`."""
    found = sorted({p for p in list(directory.glob(f"{BUNDLE_PREFIX}*")) + list(directory.glob(f"*/{BUNDLE_PREFIX}*"))
                    if p.is_dir()})
    results = []
    for bundle in found:
        entry: dict[str, Any] = {"bundle": bundle.relative_to(directory).as_posix()}
        try:
            report = verify_backup(bundle, timeout=timeout)
            entry.update(status=report["status"], store_kind=report.get("store_kind", "evidence"),
                         database_sha256=report.get("database_sha256"))
        except (BackupError, sqlite3.Error, OSError, ValueError) as exc:
            entry.update(status="FAILED", error=str(exc))
        results.append(entry)
    ok = bool(results) and all(r["status"] == "VERIFIED_BACKUP_AND_RESTORE" for r in results)
    kinds = {r.get("store_kind") for r in results if r["status"] == "VERIFIED_BACKUP_AND_RESTORE"}
    state = "VERIFIED" if ok and {"evidence", "ledger"} <= kinds else "INCOMPLETE" if ok else "FAILED"
    report = {"command": "backup offhost-verify", "directory": str(directory), "bundles": results, "state": state,
              "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    marker = directory / OFFHOST_MARKER
    if state == "VERIFIED":
        # The marker is what makes a pull count toward "keep the last 4" (offhost-prune).
        with marker.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    elif marker.is_file() and not marker.is_symlink():
        marker.unlink()  # our own marker, never a backup: a pull that no longer verifies no longer counts
    return report


OFFHOST_MARKER = "VERIFIED.json"
_PULL_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _verified_pull(directory: Path) -> bool:
    marker = directory / OFFHOST_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    return isinstance(data, dict) and data.get("state") == "VERIFIED" and bool(data.get("bundles"))


def offhost_prune(base: Path, *, keep: int = 4, apply: bool = False) -> dict[str, Any]:
    """O1 "keep the last 4": among the dated pull directories (YYYY-MM-DD) under `base`, keep the `keep`
    newest VERIFIED ones (with a valid VERIFIED.json from offhost-verify) and remove older VERIFIED ones.
    A pull that is not VERIFIED is never counted toward the 4 and never removed here (inspect it by hand),
    so a failed pull can never displace a verified one. Lists only, unless `apply`."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    dated = sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and _PULL_NAME.match(p.name)),
                   key=lambda p: p.name, reverse=True) if base.is_dir() else []
    verified = [p for p in dated if _verified_pull(p)]
    remove = verified[keep:]
    report = {"command": "backup offhost-prune", "base": str(base), "keep": keep, "applied": apply,
              "kept_verified": [p.name for p in verified[:keep]], "remove": [p.name for p in remove],
              "not_verified_left_alone": [p.name for p in dated if p not in verified]}
    if apply:
        for p in remove:
            shutil.rmtree(p)
    return report


def _offhost_prune_main(args: argparse.Namespace) -> int:
    print(json.dumps(offhost_prune(args.base, keep=args.keep, apply=args.apply), indent=2, sort_keys=True))
    return 0


def _offhost_verify_main(args: argparse.Namespace) -> int:
    report = offhost_verify(args.dir, timeout=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "VERIFIED" else 1


# --------------------------------------------------------------------------- retention APPLY (manual, reviewed)
#
# Owner approval 2026-09-26 (docs/owner/2026-09-26-owner-decisions-economics-backup.md, item 3): policy
# proposed-v1 for evidence-store local backups; deletion stays manual and reviewed (no timer, no unit);
# only eligible restore-verified copies; every protected class preserved; a reviewed dry run immediately
# before any apply, its candidate list attached to the record. This is the ONLY deletion path, a separate
# command that refuses unless every check below holds.

APPLY_LOG_NAME = "retention-apply-log.jsonl"
APPLY_MAX_REPORT_AGE = timedelta(minutes=30)
APPLY_VERIFY_TIMEOUT_S = 120.0
_PROTECTED_REASON_PREFIXES = ("NEWEST_GOOD", "FIRST_BUNDLE_BASELINE", "RECENT", "PINNED_BASELINE", "FORENSIC",
                              "NOT_ELIGIBLE_KIND", "DAILY", "WEEKLY", "MONTHLY", "SCHEMA_BOUNDARY", "CHECKPOINT",
                              "NOT_COVERED", "UNVERIFIED_RESTORE", "ACTIVE", "NEWEST_GOOD_STALE")


class ApplyRefused(BackupError):
    """The apply step found a reason not to delete anything."""


def _candidates(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {r["name"]: r for r in report.get("bundles") or [] if r.get("decision") == DELETE_CANDIDATE}


def _log(root: Path, event: dict[str, Any]) -> None:
    """Append one line to the apply log in the backups directory (append-only, flushed to disk)."""
    with (root / APPLY_LOG_NAME).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _check_backups_root(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ApplyRefused(f"NOT_A_BACKUPS_DIRECTORY: {root} is not a real directory")
    bundles = [p for p in root.iterdir() if p.name.startswith(BUNDLE_PREFIX) and (p / MANIFEST_NAME).is_file()]
    if not bundles:
        raise ApplyRefused(f"NOT_A_BACKUPS_DIRECTORY: {root} holds no backup bundle")
    live = [p.name for p in root.iterdir() if p.is_file() and p.name.endswith((".sqlite3", "-wal", "-shm", ".db"))]
    if live:
        raise ApplyRefused(f"NOT_A_BACKUPS_DIRECTORY: {root} holds database files {sorted(live)}; a live store "
                           "is never inside the backups directory")


def retention_apply(root: Path, report_path: Path, confirm: str, *, now: datetime | None = None,
                    max_age: timedelta = APPLY_MAX_REPORT_AGE, timeout: float = APPLY_VERIFY_TIMEOUT_S,
                    canonical_checkpoints: Path = CANONICAL_CHECKPOINTS) -> dict[str, Any]:
    """Delete exactly the DELETE-CANDIDATE bundles of a reviewed `retention-plan` report, or nothing.

    Refuses (ApplyRefused, nothing deleted) unless all of these hold:
    - `confirm` is the SHA-256 of the report file's bytes (the operator confirms the exact report reviewed);
    - the report is a `retention-plan` report of an approved policy, for this root, at most `max_age` old;
    - the report used the canonical F09 checkpoint directory (the running code's committed set, non-empty)
      and every pin of the policy; the recorded inputs (verify-reports file, checkpoint files) are unchanged,
      and re-running the plan now with them gives exactly the same DELETE-CANDIDATE set (names and hashes);
    - the root is a backups directory; no stale freeze; every candidate is an evidence bundle directly in the
      root, directory without symlinks, with only SUPERSEDED as its reason (so never ledger, ACTIVE,
      QUARANTINE, unverified, pinned, checkpoint-linked, schema-boundary or otherwise kept) and a covering bundle;
    - every bundle the deletions rely on (each covering bundle and the newest-good bundle) passes `verify_backup`
      (a restore into a disposable database) now.
    Then it deletes the candidate directories one at a time, logging each (name, hash, bytes, reason) to
    `APPLY_LOG_NAME` in the root. It never touches anything else."""
    now = now or datetime.now(timezone.utc)
    if not timedelta(0) < max_age <= APPLY_MAX_REPORT_AGE:
        raise ApplyRefused(f"MAX_AGE_INVALID: the report age limit must be > 0 and at most "
                           f"{int(APPLY_MAX_REPORT_AGE.total_seconds() // 60)} min")
    root = root.resolve()
    raw = report_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if confirm != digest:
        raise ApplyRefused(f"CONFIRM_MISMATCH: --confirm must be the SHA-256 of the reviewed report ({report_path})")
    try:
        report = json.loads(raw)
    except ValueError as exc:
        raise ApplyRefused("REPORT_INVALID: not JSON") from exc
    if not isinstance(report, dict) or report.get("command") != "backup retention-plan" \
            or report.get("mode") != "DRY_RUN_ONLY":
        raise ApplyRefused("REPORT_INVALID: not a retention-plan report")
    inputs = report.get("inputs") or {}
    policy = RETENTION_POLICIES.get(str(inputs.get("policy")))
    if policy is None or (report.get("policy") or {}).get("name") != policy.name:
        raise ApplyRefused(f"REPORT_INVALID: unknown policy {inputs.get('policy')!r}")
    if Path(str(report.get("root"))).resolve() != root:
        raise ApplyRefused(f"ROOT_MISMATCH: the report is for {report.get('root')}, not {root}")
    made = _aware(report.get("now_utc"))
    if made is None or made > now + timedelta(minutes=1) or now - made > max_age:
        raise ApplyRefused(f"STALE_REPORT: made {report.get('now_utc')}, now {now.isoformat()}; the dry run must be "
                           f"at most {int(max_age.total_seconds() // 60)} min old (re-run it)")
    _check_backups_root(root)
    reports_file = Path(inputs["verify_reports_file"]) if inputs.get("verify_reports_file") else None
    if reports_file is None:
        raise ApplyRefused("INPUTS_CHANGED: the report was made without --verify-reports")
    if not reports_file.is_file() or file_hash(reports_file) != inputs.get("verify_reports_sha256"):
        raise ApplyRefused(f"INPUTS_CHANGED: {reports_file} is missing or differs from the reviewed dry run")
    # F09-linked bundles are protected only if the plan saw the F09 checkpoints: the canonical, committed set.
    cp_dir = Path(inputs["checkpoints_dir"]) if inputs.get("checkpoints_dir") else None
    canonical = canonical_checkpoints.resolve()
    if cp_dir is None or cp_dir.resolve() != canonical:
        raise ApplyRefused(f"CHECKPOINTS_NOT_CANONICAL: the dry run must use --checkpoints {canonical} "
                           f"(it used {inputs.get('checkpoints_dir')!r})")
    committed = _checkpoint_files(canonical) if canonical.is_dir() else []
    if not committed:
        raise ApplyRefused(f"CHECKPOINTS_NOT_CANONICAL: {canonical} holds no F09 checkpoint; deploy them first")
    if committed != inputs.get("checkpoint_files"):
        raise ApplyRefused(f"INPUTS_CHANGED: the checkpoint files in {canonical} differ from the reviewed dry run")
    missing_pins = sorted(set(policy.pins) - set(inputs.get("pins") or ()))
    if missing_pins:
        raise ApplyRefused(f"PINS_MISSING: the dry run did not keep the policy's baselines {missing_pins}")
    fresh = build_plan(root, now=now, policy=policy, checkpoints_dir=cp_dir, verify_reports=reports_file,
                       pins=inputs.get("pins") or (), verify_hashes=bool(inputs.get("verify_hashes")))
    reviewed, current = _candidates(report), _candidates(fresh)
    if {n: r.get("database_sha256") for n, r in reviewed.items()} != \
            {n: r.get("database_sha256") for n, r in current.items()}:
        raise ApplyRefused(f"CANDIDATES_CHANGED: reviewed {sorted(reviewed)}, now {sorted(current)}; re-run the dry run")
    frozen = [f for f in fresh.get("flags") or [] if f.startswith(("NEWEST_GOOD_STALE", "NO_GOOD_BUNDLE:evidence"))]
    if frozen:
        raise ApplyRefused(f"STALE_FREEZE: {frozen}")
    linked = {b for c in fresh.get("checkpoints") or [] for b in c.get("bundles") or []}
    pins = set(inputs.get("pins") or ()) | set(policy.pins)
    for name, row in sorted(current.items()):
        reasons = row.get("reasons") or []
        bundle = root / name
        if row.get("kind") != "evidence" or row.get("path") != name or not name.startswith(BUNDLE_PREFIX):
            raise ApplyRefused(f"PROTECTED: {name} is not an evidence bundle directly in the backups directory")
        if name in pins or name in linked or not reasons or any(
                not r.startswith("SUPERSEDED") or r.startswith(_PROTECTED_REASON_PREFIXES) for r in reasons):
            raise ApplyRefused(f"PROTECTED: {name} carries a keep reason or is pinned or checkpoint-linked: {reasons}")
        if not row.get("covered_by"):
            raise ApplyRefused(f"PROTECTED: {name} names no covering bundle")
        if bundle.is_symlink() or not bundle.is_dir() or bundle.resolve().parent != root \
                or any(p.is_symlink() or not p.is_file() for p in bundle.iterdir()):
            raise ApplyRefused(f"PROTECTED: {name} is not a plain bundle directory of regular files")
    if not current:
        _log(root, {"event": "apply_nothing", "at_utc": now.isoformat(), "report_sha256": digest})
        return {"command": "backup retention-apply", "state": "NOTHING_TO_DELETE", "deleted": [], "report_sha256": digest}
    relied = sorted({str(r["covered_by"]) for r in current.values()} | {str((fresh.get("newest_good") or {})["evidence"])})
    verification = {}
    for name in relied:
        try:
            result = verify_backup(root / name, timeout=timeout)
        except (BackupError, sqlite3.Error, OSError, ValueError) as exc:
            raise ApplyRefused(f"RELIED_BUNDLE_NOT_VERIFIED: {name}: {exc}") from exc
        if result.get("status") != "VERIFIED_BACKUP_AND_RESTORE":
            raise ApplyRefused(f"RELIED_BUNDLE_NOT_VERIFIED: {name}: {result.get('status')}")
        verification[name] = result.get("database_sha256")
    _log(root, {"event": "apply_start", "at_utc": now.isoformat(), "report_sha256": digest, "policy": policy.name,
                "candidates": [{"name": n, "database_sha256": r.get("database_sha256"),
                                "database_bytes": r.get("database_bytes"), "covered_by": r.get("covered_by")}
                               for n, r in sorted(current.items())],
                "restore_verified_now": verification})
    deleted = []
    try:
        for name, row in sorted(current.items()):
            manifest = json.loads((root / name / MANIFEST_NAME).read_text(encoding="utf-8"))
            if manifest.get("database_sha256") != row.get("database_sha256"):
                raise ApplyRefused(f"CANDIDATES_CHANGED: {name}'s manifest changed during the apply")
            shutil.rmtree(root / name)
            entry = {"event": "deleted", "at_utc": datetime.now(timezone.utc).isoformat(), "name": name,
                     "database_sha256": row.get("database_sha256"), "database_bytes": row.get("database_bytes"),
                     "covered_by": row.get("covered_by"), "reason": "; ".join(row.get("reasons") or []),
                     "report_sha256": digest}
            _log(root, entry)
            deleted.append(entry)
    except BaseException as exc:
        _log(root, {"event": "apply_aborted", "at_utc": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}", "deleted": [d["name"] for d in deleted]})
        raise
    _log(root, {"event": "apply_end", "at_utc": datetime.now(timezone.utc).isoformat(), "report_sha256": digest,
                "deleted": len(deleted), "bytes": sum(d["database_bytes"] or 0 for d in deleted)})
    return {"command": "backup retention-apply", "state": "DELETED", "report_sha256": digest, "deleted": deleted,
            "restore_verified_now": verification, "log": str(root / APPLY_LOG_NAME)}


def _apply_main(args: argparse.Namespace) -> int:
    try:
        result = retention_apply(args.root, args.report, args.confirm,
                                 max_age=timedelta(minutes=args.max_report_age_min), timeout=args.timeout)
    except ApplyRefused as exc:
        print(json.dumps({"command": "backup retention-apply", "state": "REFUSED", "deleted": [], "reason": str(exc)}))
        return 2
    except (BackupError, sqlite3.Error, OSError, ValueError) as exc:
        print(json.dumps({"command": "backup retention-apply", "state": "FAILED", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
