"""Private execution-journal backups, verification and offline restore (#160 package O, ADR 0048). Offline.

This is not the research backup (`edge_lab.backup`). The execution journal has its own store, its own service user,
its own private backup directory and its own retention, and the execution package may not import research code
(ADR 0043). Nothing here deletes a bundle, a journal or any other file it did not create in the same call.

**Backup** (`create_backup`), safe while a writer is live:
1. Refuse before writing anything when the live file is missing, is not an execution journal of this code's schema,
   when the backup root does not exist or sits beside the live journal, or when free space is short
   (`DISK_PRESSURE`: the copy plus a disposable verification copy plus headroom).
2. Copy with the SQLite online backup API in one step, from a read-only connection. In WAL mode that step reads one
   consistent snapshot while the writer keeps committing; nothing is copied file by file, and the live file is never
   written (not even a checkpoint).
3. Make the copy one self-contained file (rollback journal), then check it: `integrity_check`, `foreign_key_check`,
   store kind, schema version and the schema fingerprint of this code.
4. Restore it into a disposable directory, open it with `ExecutionJournal.open` (every table, index and trigger must
   be this code's) and run `verify_chain`. Its identity must equal the copy's.
5. Write `manifest.json` (counts and digests only: no intent, order, receipt or approval identifier and no payload),
   fsync, and publish the bundle by renaming its `.partial-*` directory. An interrupted run leaves only a
   `.partial-*` directory, which is never listed as a backup.

Any failure removes only this call's partial directory and raises `BackupFailed`; earlier bundles and the live file
are untouched.

**Identity.** Intents (key, digest), approvals, attempts (id, client order id, request digest, fence, state,
provider order id), receipts (sequence, id, status, kind, payload hash), reservations and the event chain head are
digested per table. A restore must reproduce every digest, so order-intent and receipt identity are preserved
exactly. The manifest's chain head is also an external anchor: a live journal whose chain no longer contains the
backup's head event (`extends_backup`) was truncated or replaced, which `verify_chain` alone cannot see.

**Restore** (`restore_bundle`) always writes a NEW file: the target must not exist (nor its `-wal`/`-shm`), it is
created by an atomic no-overwrite link, and it can never be one of the live paths given. The bundle's bytes are
verified against the manifest first, and the restored journal is opened, chain-verified and identity-checked.
`restore_drill` restores into a drill directory and, unless asked to keep it, removes its own copy afterwards.

**Schema.** Only a store of this code's schema version and fingerprint is backed up or restored. A pre-migration
backup is therefore taken by the release that still runs the old schema, before the new code is installed
(`docs/execution/runbooks/MIGRATION_AND_ROLLBACK.md`). Older or newer stores are refused, never converted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .journal import FILENAME_SUFFIX, SCHEMA_VERSION, STORE_KIND, ExecutionJournal, JournalError
from .model import canonical_json, parse_utc_text, sha256_text, utc_text

BUNDLE_SCHEMA = "edge-lab-execution-journal-backup/1"
BUNDLE_PREFIX = "exec-journal-"
PARTIAL_PREFIX = ".partial-"
DB_NAME = "journal" + FILENAME_SUFFIX
MANIFEST_NAME = "manifest.json"
MANIFEST_MAX_BYTES = 256 * 1024
DEFAULT_TIMEOUT_S = 300.0
FREE_SPACE_FACTOR = 3  # the copy, the disposable verification copy, and as much again as headroom
MIN_FREE_BYTES = 64 * 1024 * 1024  # never fill a volume to its last bytes, whatever the journal's size
# Identity sections: table -> the columns that identify each row (ordered by the first).
_IDENTITY = (
    ("intents", ("intent_key", "digest")),
    ("approvals", ("nonce", "intent_key", "intent_digest", "attempt_id")),
    ("attempts", ("attempt_id", "intent_key", "attempt_no", "client_order_id", "request_digest", "fence_token",
                  "state", "provider_order_id")),
    ("receipts", ("receipt_seq", "receipt_id", "status", "kind", "attempt_id", "provider_id", "payload_sha256")),
    ("reservations", ("reservation_id", "intent_key", "client_order_id", "state", "filled_quantity")),
    ("account_snapshots", ("scope_key", "revision", "observed_at_utc")),
)


class BackupError(Exception):
    """Base of every backup or restore refusal and failure."""


class BackupRefused(BackupError):
    """A precondition failed (missing file, wrong store, disk pressure, existing target). Nothing was written."""


class BackupFailed(BackupError):
    """The backup or restore started and failed. Only this call's own partial files were removed."""


@dataclass(frozen=True)
class StoreIdentity:
    """What a journal file holds, read without changing it: kind, schema, counts and identity digests."""

    store_kind: str
    schema_version: int
    schema_fingerprint: str
    row_counts: Mapping[str, int]
    identity: Mapping[str, str]  # table -> sha256 of its identifying rows
    event_head_seq: int
    event_head_hash: str | None
    in_flight_attempts: int
    outcome_unknown_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return {"store_kind": self.store_kind, "schema_version": self.schema_version,
                "schema_fingerprint": self.schema_fingerprint, "row_counts": dict(self.row_counts),
                "identity": dict(self.identity), "event_head_seq": self.event_head_seq,
                "event_head_hash": self.event_head_hash, "in_flight_attempts": self.in_flight_attempts,
                "outcome_unknown_attempts": self.outcome_unknown_attempts}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StoreIdentity":
        try:
            return cls(str(d["store_kind"]), int(d["schema_version"]), str(d["schema_fingerprint"]),
                       {str(k): int(v) for k, v in dict(d["row_counts"]).items()},
                       {str(k): str(v) for k, v in dict(d["identity"]).items()}, int(d["event_head_seq"]),
                       None if d["event_head_hash"] is None else str(d["event_head_hash"]),
                       int(d["in_flight_attempts"]), int(d["outcome_unknown_attempts"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupFailed(f"manifest identity is malformed: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class BackupRecord:
    bundle: Path
    manifest: Mapping[str, Any]

    @property
    def identity(self) -> StoreIdentity:
        return StoreIdentity.from_dict(self.manifest["identity"])


@dataclass(frozen=True)
class RestoreReport:
    target: Path
    bundle: Path
    identity: StoreIdentity
    chain_events: int
    removed_after_drill: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"target": str(self.target), "bundle": str(self.bundle), "verified": True,
                "chain_events": self.chain_events, "identity": self.identity.to_dict(),
                "removed_after_drill": self.removed_after_drill,
                "note": "a restored journal starts DISARMED; in-flight attempts become OUTCOME_UNKNOWN when a new "
                        "worker takes the lease, and every unknown outcome is reconciled from the venue before "
                        "any arm"}


@dataclass(frozen=True)
class BundleInfo:
    path: Path
    complete: bool  # a published bundle directory with a manifest (bytes are checked by verify_bundle)
    created_at_utc: str | None


# ------------------------------------------------------------------ reading a store without changing it


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";").strip()


def _open_existing(path: Path) -> sqlite3.Connection:
    """A read-only connection (`mode=ro`) to an existing regular file: SQLite never creates the file and never
    writes it. In particular it never checkpoints a crashed writer's WAL into the main file on close, which a
    read-write connection would do. For a WAL journal SQLite may create the empty `-wal`/`-shm` side files when no
    writer holds them (the directory must be writable); the journal's next opener uses them."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise BackupRefused(f"not an existing, non-empty journal file: {path.name}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _identity(conn: sqlite3.Connection) -> StoreIdentity:
    """Read one consistent identity of an open store (one read transaction)."""
    conn.execute("BEGIN")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "schema_meta" not in tables:
            raise BackupRefused("the file has no schema_meta: not an execution journal")
        meta = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
        if meta.get("store_kind") != STORE_KIND:
            raise BackupRefused(f"the file is a {meta.get('store_kind')!r} store, not {STORE_KIND!r}")
        version = str(meta.get("schema_version"))
        if not version.isdigit():
            raise BackupRefused(f"unreadable schema version {version!r}")
        schema_rows = sorted((t, n, _normalized(s)) for t, n, s in conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        fingerprint = sha256_text(canonical_json([list(r) for r in schema_rows]))
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                  for t in sorted(tables) if not t.startswith("sqlite_")}
        identity = {}
        for table, cols in _IDENTITY:
            if table not in tables:
                identity[table] = "ABSENT"
                continue
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {cols[0]}").fetchall()
            identity[table] = sha256_text(canonical_json([list(r) for r in rows]))
        head = conn.execute("SELECT seq, row_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone() \
            if "events" in tables else None
        in_flight = unknown = 0
        if "attempts" in tables:
            in_flight = conn.execute("SELECT COUNT(*) FROM attempts WHERE state IN ('PENDING_EGRESS', 'SENT')"
                                     ).fetchone()[0]
            unknown = conn.execute("SELECT COUNT(*) FROM attempts WHERE state = 'OUTCOME_UNKNOWN'").fetchone()[0]
    finally:
        if conn.in_transaction:
            conn.execute("COMMIT")
    return StoreIdentity(STORE_KIND, int(version), fingerprint, counts, identity,
                         0 if head is None else int(head[0]), None if head is None else str(head[1]), in_flight,
                         unknown)


def store_identity(path: str | Path) -> StoreIdentity:
    """The identity of the journal at `path`, read-only. Refuses a missing or foreign file (never creates one)."""
    p = Path(path)
    try:
        with closing(_open_existing(p)) as conn:
            return _identity(conn)
    except sqlite3.Error as exc:
        raise BackupRefused(f"the journal could not be read: {type(exc).__name__}: {exc}") from exc


def code_schema_fingerprint() -> str:
    """The schema fingerprint of a journal created by this code (an empty journal in a disposable directory)."""
    with tempfile.TemporaryDirectory(prefix="exec-schema-ref-", ignore_cleanup_errors=True) as temp:
        path = Path(temp) / ("reference" + FILENAME_SUFFIX)
        ExecutionJournal.open(path).close()
        return store_identity(path).schema_fingerprint


def schema_problems(identity: StoreIdentity, *, expected_fingerprint: str | None = None) -> list[str]:
    """Why a store's schema is not this code's (empty when it is)."""
    out = []
    if identity.store_kind != STORE_KIND:
        out.append(f"STORE_KIND: {identity.store_kind}")
    if identity.schema_version > SCHEMA_VERSION:
        out.append(f"STORE_NEWER_THAN_CODE: store v{identity.schema_version}, code v{SCHEMA_VERSION}")
    elif identity.schema_version < SCHEMA_VERSION:
        out.append(f"STORE_OLDER_THAN_CODE: store v{identity.schema_version}, code v{SCHEMA_VERSION} "
                   f"(forward-only migration needed)")
    expected = expected_fingerprint or code_schema_fingerprint()
    if identity.schema_version == SCHEMA_VERSION and identity.schema_fingerprint != expected:
        out.append("SCHEMA_OBJECTS_DIFFER: same version, different tables, indexes or triggers")
    return out


# ------------------------------------------------------------------ helpers


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as stream:  # Windows fsync needs a handle opened for writing
        stream.flush()
        os.fsync(stream.fileno())


def _live_bytes(path: Path) -> int:
    total = path.stat().st_size
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.is_file():
            total += side.stat().st_size
    return total


def _require_space(directory: Path, needed: int, disk_usage: Callable[[str], Any]) -> int:
    free = int(disk_usage(str(directory)).free)
    if free < needed:
        raise BackupRefused(f"DISK_PRESSURE: {free} bytes free under {directory.name or directory}, {needed} needed")
    return free


class _Deadline:
    def __init__(self, seconds: float, monotonic: Callable[[], float]):
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0 < seconds <= 86400:
            raise ValueError("timeout_s must be a number in (0, 86400]")
        self._monotonic = monotonic
        self._end = monotonic() + seconds

    def check(self, stage: str) -> None:
        if self._monotonic() >= self._end:
            raise BackupFailed(f"TIME_BUDGET_EXHAUSTED at {stage}")


def _check_copy(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise BackupFailed("the copy fails SQLite integrity_check")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise BackupFailed("the copy fails SQLite foreign_key_check")


def _verify_by_restore(db: Path, expected: StoreIdentity, scratch_parent: Path | None = None) -> int:
    """Copy `db` into a disposable directory, open it as a journal, verify its chain and identity. Returns the
    number of chain events."""
    with tempfile.TemporaryDirectory(prefix="exec-restore-check-", dir=scratch_parent,
                                     ignore_cleanup_errors=True) as temp:
        check = Path(temp) / ("check" + FILENAME_SUFFIX)
        shutil.copyfile(db, check)
        try:
            with ExecutionJournal.open(check) as journal:
                chain = journal.verify_chain()
                restored = store_identity(check)
        except JournalError as exc:
            raise BackupFailed(f"the copy does not open as this code's journal: {type(exc).__name__}: {exc}") from exc
        if not chain.ok:
            raise BackupFailed(f"CHAIN_INVALID: {list(chain.problems[:5])}")
    if restored != expected:
        raise BackupFailed("IDENTITY_MISMATCH: the restored copy differs from the backup")
    return chain.events


# ------------------------------------------------------------------ backup


def create_backup(live: str | Path, backup_root: str | Path, *, now: datetime, timeout_s: float = DEFAULT_TIMEOUT_S,
                  disk_usage: Callable[[str], Any] = shutil.disk_usage,
                  monotonic: Callable[[], float] = time.monotonic,
                  fault: Callable[[str], None] | None = None) -> BackupRecord:
    """A verified, published backup bundle of the live journal. See the module docstring. `fault` is a test seam
    called with "copied", "verified" and "before_publish"; production never passes it."""
    deadline = _Deadline(timeout_s, monotonic)
    created_at = utc_text(now)  # the snapshot's time, as the caller's clock gives it
    live_path, root = Path(live), Path(backup_root)
    if not live_path.name.endswith(FILENAME_SUFFIX):
        raise BackupRefused(f"the live journal's name must end in {FILENAME_SUFFIX!r}")
    if not root.is_dir() or root.is_symlink():
        raise BackupRefused("the backup root must be an existing directory (created by the install runbook)")
    if not live_path.is_file():
        raise BackupRefused(f"no live journal at {live_path.name}")
    live_dir, root_dir = live_path.resolve().parent, root.resolve()
    if root_dir == live_dir or live_dir in root_dir.parents or root_dir in live_dir.parents:
        raise BackupRefused("the backup root may not be the live journal's directory, inside it or above it")
    expected_fingerprint = code_schema_fingerprint()
    try:
        with closing(_open_existing(live_path)) as probe:
            problems = schema_problems(_identity(probe), expected_fingerprint=expected_fingerprint)
    except sqlite3.Error as exc:
        raise BackupRefused(f"the live journal could not be read: {type(exc).__name__}: {exc}") from exc
    if problems:
        raise BackupRefused(f"refusing a store this code cannot verify: {problems}")
    _require_space(root, _live_bytes(live_path) * FREE_SPACE_FACTOR + MIN_FREE_BYTES, disk_usage)
    deadline.check("start")

    token = uuid.uuid4().hex[:12]
    partial = root / f"{PARTIAL_PREFIX}{token}"
    partial.mkdir(mode=0o700)
    try:
        db = partial / DB_NAME
        try:
            with closing(_open_existing(live_path)) as src, \
                    closing(sqlite3.connect(str(db), isolation_level=None)) as dst:
                src.backup(dst, pages=-1)  # one step: one consistent snapshot, even with a live writer
                dst.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
                if fault:
                    fault("copied")
                deadline.check("copy")
                _check_copy(dst)
                copied = _identity(dst)
        except sqlite3.Error as exc:
            raise BackupFailed(f"the online copy failed: {type(exc).__name__}: {exc}") from exc
        problems = schema_problems(copied, expected_fingerprint=expected_fingerprint)
        if problems:
            raise BackupFailed(f"the copy is not this code's schema: {problems}")
        events = _verify_by_restore(db, copied, scratch_parent=partial)
        if fault:
            fault("verified")
        deadline.check("verify")
        os.chmod(db, 0o600)
        _fsync_file(db)
        manifest = {
            "schema": BUNDLE_SCHEMA, "database": DB_NAME, "created_at_utc": created_at,
            "database_sha256": _file_sha256(db),
            "database_bytes": db.stat().st_size, "chain_verified": True, "chain_events": events,
            "identity": copied.to_dict(), "source_name": live_path.name,
        }
        tmp_manifest = partial / ".manifest.tmp"
        with tmp_manifest.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(manifest) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_manifest, 0o600)
        tmp_manifest.replace(partial / MANIFEST_NAME)
        if fault:
            fault("before_publish")
        deadline.check("publish")
        stamp = parse_utc_text(created_at).strftime("%Y%m%dT%H%M%SZ")
        bundle = root / f"{BUNDLE_PREFIX}{stamp}-{token}"
        partial.rename(bundle)  # publication: a bundle exists only once it is complete
        return BackupRecord(bundle, manifest)
    except BaseException as exc:
        shutil.rmtree(partial, ignore_errors=True)  # only this call's own partial directory
        if isinstance(exc, BackupError):
            raise
        if isinstance(exc, (OSError, JournalError)):
            raise BackupFailed(f"backup failed: {type(exc).__name__}: {exc}") from exc
        raise


# ------------------------------------------------------------------ verify, list


def read_manifest(bundle: str | Path) -> dict[str, Any]:
    b = Path(bundle)
    manifest_path, db = b / MANIFEST_NAME, b / DB_NAME
    if b.is_symlink() or manifest_path.is_symlink() or db.is_symlink():
        raise BackupFailed("symlinked bundles are refused")
    if not manifest_path.is_file():
        raise BackupFailed("INCOMPLETE: the bundle has no manifest")
    if manifest_path.stat().st_size > MANIFEST_MAX_BYTES:
        raise BackupFailed("the manifest is larger than its bound")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BackupFailed("the manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("database") != DB_NAME:
        raise BackupFailed("not a journal backup manifest of this format")
    return manifest


def verify_bundle(bundle: str | Path) -> BackupRecord:
    """Bytes against the manifest, then a disposable restore: schema, chain and identity. Never changes the bundle."""
    b = Path(bundle)
    manifest = read_manifest(b)
    db = b / DB_NAME
    if not db.is_file() or db.stat().st_size != manifest.get("database_bytes") \
            or _file_sha256(db) != manifest.get("database_sha256"):
        raise BackupFailed("BYTES_MISMATCH: the database differs from its manifest")
    expected = StoreIdentity.from_dict(manifest.get("identity") or {})
    problems = schema_problems(expected)
    if problems:
        raise BackupFailed(f"the bundle is not this code's schema: {problems}")
    _verify_by_restore(db, expected)
    return BackupRecord(b, manifest)


def list_bundles(backup_root: str | Path) -> list[BundleInfo]:
    """Every bundle and partial directory under the root, oldest first. A partial is never complete."""
    root = Path(backup_root)
    out = []
    for p in sorted(root.iterdir()) if root.is_dir() else []:
        if p.is_dir() and p.name.startswith(PARTIAL_PREFIX):
            out.append(BundleInfo(p, False, None))
        elif p.is_dir() and p.name.startswith(BUNDLE_PREFIX):
            try:
                created = str(read_manifest(p).get("created_at_utc"))
                out.append(BundleInfo(p, True, created))
            except BackupError:
                out.append(BundleInfo(p, False, None))
    return out


def newest_complete(backup_root: str | Path) -> BundleInfo | None:
    complete = [b for b in list_bundles(backup_root) if b.complete and b.created_at_utc]
    return max(complete, key=lambda b: parse_utc_text(b.created_at_utc), default=None)  # type: ignore[arg-type]


def extends_backup(live: str | Path, bundle: str | Path) -> list[str]:
    """Problems if the live journal's chain does not contain the bundle's head event (truncated or replaced)."""
    head = StoreIdentity.from_dict(read_manifest(bundle).get("identity") or {})
    if head.event_head_seq == 0:
        return []
    try:
        with closing(_open_existing(Path(live))) as conn:
            row = conn.execute("SELECT row_hash FROM events WHERE seq = ?", (head.event_head_seq,)).fetchone()
    except sqlite3.Error as exc:
        return [f"LIVE_UNREADABLE: {type(exc).__name__}"]
    if row is None:
        return [f"LIVE_CHAIN_SHORTER_THAN_BACKUP: no event {head.event_head_seq}"]
    if row[0] != head.event_head_hash:
        return [f"LIVE_CHAIN_DIVERGES_FROM_BACKUP at event {head.event_head_seq}"]
    return []


# ------------------------------------------------------------------ restore


def _siblings(path: Path) -> tuple[Path, ...]:
    return (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"),
            path.with_name(path.name + "-journal"))


def restore_bundle(bundle: str | Path, target: str | Path, *, live_paths: Iterable[str | Path] = (),
                   disk_usage: Callable[[str], Any] = shutil.disk_usage) -> RestoreReport:
    """Restore a verified bundle to a NEW journal file at `target` (see the module docstring)."""
    b, t = Path(bundle), Path(target)
    if not t.name.endswith(FILENAME_SUFFIX) or t.name == FILENAME_SUFFIX:
        raise BackupRefused(f"the restore target's name must end in {FILENAME_SUFFIX!r}")
    if not t.parent.is_dir():
        raise BackupRefused("the restore target's directory must exist")
    resolved = t.resolve()
    for live in live_paths:
        if resolved in {s.resolve() for s in _siblings(Path(live))}:
            raise BackupRefused("NEVER_OVER_LIVE: the restore target is a live journal path")
    if any(s.exists() or s.is_symlink() for s in _siblings(t)):
        raise BackupRefused("TARGET_EXISTS: a restore never overwrites a file (journal or side file)")
    record = verify_bundle(b)
    db = b / DB_NAME
    _require_space(t.parent, db.stat().st_size * 2 + MIN_FREE_BYTES, disk_usage)
    tmp = t.parent / f".restore-{uuid.uuid4().hex[:12]}.tmp"
    created = False
    try:
        shutil.copyfile(db, tmp)
        os.chmod(tmp, 0o600)
        _fsync_file(tmp)
        try:
            os.link(tmp, t)  # atomic and never overwrites: fails if the target appeared meanwhile
        except FileExistsError as exc:
            raise BackupRefused("TARGET_EXISTS: the target appeared during the restore") from exc
        created = True
        with ExecutionJournal.open(t) as journal:
            chain = journal.verify_chain()
            restored = store_identity(t)  # while the journal is open, so its close tidies the side files
        if not chain.ok:
            raise BackupFailed(f"CHAIN_INVALID after restore: {list(chain.problems[:5])}")
        if restored != record.identity:
            raise BackupFailed("IDENTITY_MISMATCH: the restored journal differs from its backup")
        return RestoreReport(t, b, restored, chain.events)
    except BaseException as exc:
        if created:  # only the file this call created
            for s in _siblings(t):
                try:
                    s.unlink()
                except OSError:
                    pass
        if isinstance(exc, BackupError):
            raise
        if isinstance(exc, (OSError, JournalError)):
            raise BackupFailed(f"restore failed: {type(exc).__name__}: {exc}") from exc
        raise
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def restore_drill(bundle: str | Path, drill_dir: str | Path, *, live_paths: Iterable[str | Path] = (),
                  keep: bool = False, disk_usage: Callable[[str], Any] = shutil.disk_usage) -> RestoreReport:
    """A restore drill: restore into a fresh name under `drill_dir` (never a live path), verify, report, and remove
    the drill's own copy unless `keep`."""
    d = Path(drill_dir)
    target = d / f"drill-{uuid.uuid4().hex[:12]}{FILENAME_SUFFIX}"
    report = restore_bundle(bundle, target, live_paths=live_paths, disk_usage=disk_usage)
    if keep:
        return report
    for s in _siblings(target):
        try:
            s.unlink()
        except FileNotFoundError:
            pass
    return RestoreReport(report.target, report.bundle, report.identity, report.chain_events, removed_after_drill=True)
