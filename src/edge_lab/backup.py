"""Manual, WAL-aware SQLite backup and isolated restore rehearsal.

Adapted from Brisket's online-backup pattern; no scheduling, remote upload,
retention deletion, source migration, or restoration over an existing database.
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
from datetime import datetime, timezone
from pathlib import Path

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
    args = parser.parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
