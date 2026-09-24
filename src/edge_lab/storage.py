from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .http import FetchResult
from .provenance import bytes_sha256, canonical_json, sha256_hex, shape_fingerprint

SCHEMA_VERSION = 5
SOURCE_HEALTH_STATUSES = ("ok", "partial", "failed")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Version 1 is the Milestone 1 schema. It must stay byte-for-byte compatible so
# databases created before migrations existed still open.
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS collection_runs (
    run_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    source_timestamp_utc TEXT,
    url TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
ON snapshots(source, kind, entity_id, fetched_at_utc);

CREATE INDEX IF NOT EXISTS idx_snapshots_run
ON snapshots(run_id);
"""

# Version 2: provenance columns, immutable evidence, per-source health.
# New snapshot columns are nullable so Milestone 1 rows remain valid as-is.
_SNAPSHOT_V2_COLUMNS = (
    ("source_id", "TEXT"),
    ("final_url", "TEXT"),
    ("http_status", "INTEGER"),
    ("content_type", "TEXT"),
    ("payload_bytes", "INTEGER"),
    ("raw_sha256", "TEXT"),
    ("attempts", "INTEGER"),
    ("fetch_duration_ms", "INTEGER"),
    ("parser_version", "TEXT"),
    ("schema_version", "TEXT"),
    ("shape_sha256", "TEXT"),
    # v3: why each failed attempt before success failed, e.g. ["http_429"].
    ("retry_reasons_json", "TEXT"),
)

_SCHEMA_V2 = """
-- INSERT OR REPLACE would otherwise delete-and-reinsert an existing row
-- without firing the delete trigger.
CREATE TRIGGER IF NOT EXISTS snapshots_no_replace
BEFORE INSERT ON snapshots
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM snapshots WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'snapshots are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS snapshots_no_update
BEFORE UPDATE ON snapshots
BEGIN
    SELECT RAISE(ABORT, 'snapshots are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS snapshots_no_delete
BEFORE DELETE ON snapshots
BEGIN
    SELECT RAISE(ABORT, 'snapshots are immutable evidence');
END;

CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed')),
    records INTEGER NOT NULL CHECK (records >= 0),
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    http_errors INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    anomalies_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    -- A failure always explains itself and never claims records.
    CHECK (status != 'failed' OR (error IS NOT NULL AND records = 0)),
    -- A clean run carries no error.
    CHECK (status != 'ok' OR error IS NULL),
    -- A partial run says why it is partial.
    CHECK (status != 'partial' OR error IS NOT NULL OR anomalies_json != '[]'),
    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_source_health_lookup
ON source_health(source_id, completed_at_utc);

-- Health history is evidence too: a failure cannot be rewritten as success.
CREATE TRIGGER IF NOT EXISTS source_health_no_update
BEFORE UPDATE ON source_health
BEGIN
    SELECT RAISE(ABORT, 'source_health rows are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS source_health_no_delete
BEFORE DELETE ON source_health
BEGIN
    SELECT RAISE(ABORT, 'source_health rows are immutable evidence');
END;

-- A run may be finished once; after that its outcome is fixed.
CREATE TRIGGER IF NOT EXISTS collection_runs_finish_once
BEFORE UPDATE ON collection_runs
WHEN OLD.status != 'running'
BEGIN
    SELECT RAISE(ABORT, 'finished collection runs are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS collection_runs_no_delete
BEFORE DELETE ON collection_runs
BEGIN
    SELECT RAISE(ABORT, 'collection runs are immutable evidence');
END;
"""


# Version 3: immutable raw documents (PDFs, text products, HTML) stored as exact bytes.
# Content is deduplicated by hash; every retrieval is its own row, so re-fetching an
# unchanged document proves it was still published, and a changed document becomes a
# new version without touching the old one.
_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS document_blobs (
    sha256 TEXT PRIMARY KEY,
    byte_length INTEGER NOT NULL,
    body BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS document_retrievals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    fetched_at_utc TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    byte_length INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    series_ticker TEXT,
    market_ticker TEXT,
    attempts INTEGER,
    retry_reasons_json TEXT,
    FOREIGN KEY (sha256) REFERENCES document_blobs(sha256),
    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_document_retrievals_url
ON document_retrievals(requested_url, fetched_at_utc);

-- Content-addressed: inserting an existing hash never replaces the stored bytes,
-- even through INSERT OR REPLACE on a connection without recursive triggers.
CREATE TRIGGER IF NOT EXISTS document_blobs_keep_original
BEFORE INSERT ON document_blobs
WHEN EXISTS (SELECT 1 FROM document_blobs WHERE sha256 = NEW.sha256)
BEGIN
    SELECT RAISE(IGNORE);
END;

CREATE TRIGGER IF NOT EXISTS document_retrievals_no_replace
BEFORE INSERT ON document_retrievals
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM document_retrievals WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'documents are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS document_blobs_no_update
BEFORE UPDATE ON document_blobs
BEGIN
    SELECT RAISE(ABORT, 'documents are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS document_blobs_no_delete
BEFORE DELETE ON document_blobs
BEGIN
    SELECT RAISE(ABORT, 'documents are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS document_retrievals_no_update
BEFORE UPDATE ON document_retrievals
BEGIN
    SELECT RAISE(ABORT, 'documents are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS document_retrievals_no_delete
BEFORE DELETE ON document_retrievals
BEGIN
    SELECT RAISE(ABORT, 'documents are immutable evidence');
END;
"""


# Version 4: forward Stage-B capture outcomes (ADR 0012). One row per capture attempt,
# written once when the attempt ends. It links the attempt to the snapshots it stored, so
# a day's validity can be re-derived from evidence. Rows are never updated: a rerun is a
# new row.
FORWARD_CAPTURE_STATUSES = (
    "complete",
    "partial",
    "failed",
    "skipped_duplicate",
    "rejected_out_of_window",
    "rejected_no_decision_capture",
)

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS forward_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    experiment TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('pfm', 'decision', 'recheck')),
    -- 'smoke' rows come from tests or manual smoke checks with an injected clock and are
    -- never evidence.
    mode TEXT NOT NULL CHECK (mode IN ('live', 'smoke')),
    target_date TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT NOT NULL,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'complete', 'partial', 'failed', 'skipped_duplicate',
        'rejected_out_of_window', 'rejected_no_decision_capture'
    )),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    links_json TEXT NOT NULL DEFAULT '{}',
    decision_capture_id INTEGER,
    code_version TEXT,
    -- A complete capture has nothing to explain; anything else says why.
    CHECK (status != 'complete' OR reasons_json = '[]'),
    CHECK (status = 'complete' OR reasons_json != '[]'),
    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id),
    FOREIGN KEY (decision_capture_id) REFERENCES forward_captures(id)
);

CREATE INDEX IF NOT EXISTS idx_forward_captures_day
ON forward_captures(target_date, phase, mode);

CREATE TRIGGER IF NOT EXISTS forward_captures_no_replace
BEFORE INSERT ON forward_captures
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM forward_captures WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'forward captures are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS forward_captures_no_update
BEFORE UPDATE ON forward_captures
BEGIN
    SELECT RAISE(ABORT, 'forward captures are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS forward_captures_no_delete
BEFORE DELETE ON forward_captures
BEGIN
    SELECT RAISE(ABORT, 'forward captures are immutable evidence');
END;
"""


# Version 5: The Odds API pilot's game-relative capture targets (ADR 0029). Additive only:
# two new tables, nothing existing changes. A target is written once, when first planned, with
# its intended capture time. Its life is an append-only list of state transitions; the current
# state is the latest one. A final state (CAPTURED, MISSED, FAILED, SUPERSEDED) cannot be
# followed by another, so a missed capture stays visible and is never silently replaced.
ODDS_TARGET_STATES = (
    "PLANNED", "CAPTURING", "CAPTURED", "MISSED", "SKIPPED_BUDGET", "QUOTA_UNKNOWN", "QUOTA_EXHAUSTED",
    "SETUP_NEEDED", "DEFERRED", "FAILED", "SUPERSEDED",
)
ODDS_TARGET_FINAL_STATES = ("CAPTURED", "MISSED", "FAILED", "SUPERSEDED")

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS odds_capture_targets (
    target_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    event_id TEXT NOT NULL,
    offset_label TEXT NOT NULL,
    priority INTEGER NOT NULL,
    commence_time_utc TEXT NOT NULL,
    target_utc TEXT NOT NULL,
    planned_at_utc TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    home_team TEXT,
    away_team TEXT,
    discovery_snapshot_id INTEGER,
    FOREIGN KEY (discovery_snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_odds_capture_targets_time
ON odds_capture_targets(sport, target_utc);

CREATE TABLE IF NOT EXISTS odds_capture_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'PLANNED', 'CAPTURING', 'CAPTURED', 'MISSED', 'SKIPPED_BUDGET', 'QUOTA_UNKNOWN',
        'QUOTA_EXHAUSTED', 'SETUP_NEEDED', 'DEFERRED', 'FAILED', 'SUPERSEDED'
    )),
    at_utc TEXT NOT NULL,
    reason TEXT,
    slot_id TEXT,
    snapshot_id INTEGER,
    captured_at_utc TEXT,
    credits_last INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}',
    -- A capture names its evidence and when it was received.
    CHECK (state != 'CAPTURED' OR (snapshot_id IS NOT NULL AND captured_at_utc IS NOT NULL)),
    -- Anything that is not plain progress explains itself.
    CHECK (state IN ('PLANNED', 'CAPTURING', 'CAPTURED') OR reason IS NOT NULL),
    FOREIGN KEY (target_id) REFERENCES odds_capture_targets(target_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_odds_capture_transitions_target
ON odds_capture_transitions(target_id, id);

-- Planning is idempotent: re-planning a known target keeps the original row (and its
-- planned_at_utc), even through INSERT OR REPLACE.
CREATE TRIGGER IF NOT EXISTS odds_capture_targets_keep_original
BEFORE INSERT ON odds_capture_targets
WHEN EXISTS (SELECT 1 FROM odds_capture_targets WHERE target_id = NEW.target_id)
BEGIN
    SELECT RAISE(IGNORE);
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_targets_no_update
BEFORE UPDATE ON odds_capture_targets
BEGIN
    SELECT RAISE(ABORT, 'odds capture targets are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_targets_no_delete
BEFORE DELETE ON odds_capture_targets
BEGIN
    SELECT RAISE(ABORT, 'odds capture targets are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_transitions_no_replace
BEFORE INSERT ON odds_capture_transitions
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM odds_capture_transitions WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'odds capture transitions are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_transitions_final_is_final
BEFORE INSERT ON odds_capture_transitions
WHEN (SELECT state FROM odds_capture_transitions WHERE target_id = NEW.target_id ORDER BY id DESC LIMIT 1)
     IN ('CAPTURED', 'MISSED', 'FAILED', 'SUPERSEDED')
BEGIN
    SELECT RAISE(ABORT, 'odds capture target already reached a final state');
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_transitions_no_update
BEFORE UPDATE ON odds_capture_transitions
BEGIN
    SELECT RAISE(ABORT, 'odds capture transitions are immutable evidence');
END;

CREATE TRIGGER IF NOT EXISTS odds_capture_transitions_no_delete
BEFORE DELETE ON odds_capture_transitions
BEGIN
    SELECT RAISE(ABORT, 'odds capture transitions are immutable evidence');
END;
"""


V4_REQUIRED_TABLES = ("collection_runs", "snapshots", "source_health", "document_blobs", "document_retrievals",
                      "forward_captures")


def mark_schema_v4_for_rollback(db_path: str | Path) -> dict[str, Any]:
    """Code rollback helper (runbook "Rollback"): stamp a v5 evidence store as v4 so the
    previous (v4) code opens it.

    Nothing is deleted or rewritten. v5 only added the odds capture tables and their triggers,
    which v4 code never reads; every v4 table, column and trigger is checked present first.
    Re-installing v5 code later stamps v5 again (its migration is idempotent). Refuses anything
    that is not exactly a complete v5 store. Run it with the collector timers stopped."""
    path = Path(db_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} is missing or not a regular file")
    with closing(sqlite3.connect(path, timeout=30.0)) as conn:
        conn.row_factory = sqlite3.Row
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != 5:
            raise ValueError(f"expected a v5 evidence store, found v{version}; nothing changed")
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
        missing = [t for t in V4_REQUIRED_TABLES if t not in names]
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")}
        missing += [f"snapshots.{c}" for c, _ in _SNAPSHOT_V2_COLUMNS if c not in columns]
        if missing:
            raise ValueError(f"not a complete store; missing {missing}; nothing changed")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("integrity_check failed; nothing changed")
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        return {"db": str(path), "from": 5, "to": 4,
                "odds_targets_kept": int(conn.execute("SELECT COUNT(*) FROM odds_capture_targets").fetchone()[0])}


def main(argv: list[str] | None = None) -> int:
    """`python -m edge_lab.storage mark-v4-for-rollback --db PATH` (see the rollback runbook)."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m edge_lab.storage")
    sub = parser.add_subparsers(dest="command", required=True)
    rb = sub.add_parser("mark-v4-for-rollback", help="stamp a v5 evidence store as v4 before a code rollback")
    rb.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(mark_schema_v4_for_rollback(args.db), sort_keys=True))
    except ValueError as exc:
        print(json.dumps({"status": "REFUSED", "detail": str(exc)}))
        return 1
    return 0


class ReadOnlyStoreError(RuntimeError):
    """The evidence store cannot be opened read-only as required (missing, wrong schema)."""


class SnapshotStore:
    _read_only = False

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def open_readonly(cls, db_path: str | Path) -> "SnapshotStore":
        """Open an existing evidence store for analysis without creating, migrating or
        changing it: no mkdir, no schema script, no journal-mode PRAGMA, SQLite `mode=ro`
        plus `query_only`. Refuses a missing file, a symlink, or a schema version other
        than this code's (an older store must be migrated by the collector's write path,
        never by an analysis run)."""
        path = Path(db_path)
        if path.is_symlink() or not path.is_file():
            raise ReadOnlyStoreError(f"evidence store {path} is missing or not a regular file")
        store = cls.__new__(cls)
        store.path = path
        store._read_only = True
        version = store.schema_version()
        if version != SCHEMA_VERSION:
            raise ReadOnlyStoreError(
                f"evidence store schema v{version} != code v{SCHEMA_VERSION}; refusing to analyse"
            )
        return store

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _connect(self) -> sqlite3.Connection:
        """A configured connection. Callers close it (`closing`); if configuring it fails, it
        is closed here, so a failed PRAGMA never leaks a handle."""
        if self._read_only:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=30.0)
        else:
            # Scheduled captures and manual runs may overlap: wait for a lock instead of
            # failing at once with "database is locked".
            conn = sqlite3.connect(self.path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 30000")
            if self._read_only:
                conn.execute("PRAGMA query_only = ON")
            else:
                conn.execute("PRAGMA foreign_keys = ON")
                # Make REPLACE conflict resolution fire delete triggers too.
                conn.execute("PRAGMA recursive_triggers = ON")
                conn.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            conn.close()
            raise
        return conn

    def _initialize(self) -> None:
        with closing(self._connect()) as conn, conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema v{version} is newer than this code (v{SCHEMA_VERSION})"
                )
            conn.executescript(_SCHEMA_V1)
            if version < SCHEMA_VERSION:
                existing = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)")}
                for name, sql_type in _SNAPSHOT_V2_COLUMNS:
                    if name not in existing:
                        try:
                            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {sql_type}")
                        except sqlite3.OperationalError as exc:
                            # Another process migrated concurrently.
                            if "duplicate column" not in str(exc):
                                raise
            # Idempotent (IF NOT EXISTS): also installs protections added after a
            # database was first migrated.
            conn.executescript(_SCHEMA_V2)
            conn.executescript(_SCHEMA_V3)
            conn.executescript(_SCHEMA_V4)
            # v5's tables and triggers land in one transaction, and the version is stamped
            # only after every object exists: a crash leaves either v4 or a complete v5.
            conn.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA_V5 + "\nCOMMIT;")
            if version < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        with closing(self._connect()) as conn, conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def start_run(self, run_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO collection_runs(run_id, started_at_utc, status)
                VALUES (?, ?, 'running')
                """,
                (run_id, utc_now_iso()),
            )

    def finish_run(self, run_id: str, *, status: str, error: str | None = None) -> None:
        if status not in {"succeeded", "failed", "partial"}:
            raise ValueError(f"Unsupported run status: {status}")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE collection_runs
                SET finished_at_utc = ?, status = ?, error = ?
                WHERE run_id = ?
                """,
                (utc_now_iso(), status, error, run_id),
            )

    def save_snapshot(
        self,
        *,
        run_id: str,
        source: str,
        kind: str,
        entity_id: str,
        url: str,
        payload: dict[str, Any],
        source_timestamp_utc: str | None = None,
        fetched_at_utc: str | None = None,
        source_id: str | None = None,
        fetch: FetchResult | None = None,
        parser_version: str | None = None,
        schema_version: str | None = None,
    ) -> int:
        canonical = canonical_json(payload)
        digest = sha256_hex(canonical)
        fetched = fetched_at_utc or (fetch.received_at_utc if fetch else None) or utc_now_iso()

        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots(
                    run_id, source, kind, entity_id, fetched_at_utc,
                    source_timestamp_utc, url, payload_sha256, payload_json,
                    source_id, final_url, http_status, content_type,
                    payload_bytes, raw_sha256, attempts, fetch_duration_ms,
                    parser_version, schema_version, shape_sha256, retry_reasons_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source,
                    kind,
                    entity_id,
                    fetched,
                    source_timestamp_utc,
                    url,
                    digest,
                    canonical,
                    source_id,
                    fetch.final_url if fetch else None,
                    fetch.http_status if fetch else None,
                    fetch.content_type if fetch else None,
                    len(fetch.body) if fetch else len(canonical.encode("utf-8")),
                    bytes_sha256(fetch.body) if fetch else None,
                    fetch.attempts if fetch else None,
                    fetch.duration_ms if fetch else None,
                    parser_version,
                    schema_version,
                    shape_fingerprint(payload),
                    json.dumps(list(fetch.retry_reasons)) if fetch else None,
                ),
            )
            return int(cursor.lastrowid)

    def snapshots_by_id(self, ids: Iterable[int]) -> dict[int, sqlite3.Row]:
        """Snapshots (payload included) keyed by id; ids not found are absent."""
        wanted = sorted({int(i) for i in ids})
        if not wanted:
            return {}
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"""
                SELECT id, run_id, source, kind, entity_id, fetched_at_utc, url,
                       payload_sha256, payload_json
                FROM snapshots WHERE id IN ({",".join("?" * len(wanted))})
                """,
                wanted,
            ).fetchall()
        return {int(row["id"]): row for row in rows}

    def record_forward_capture(
        self,
        *,
        run_id: str,
        experiment: str,
        phase: str,
        mode: str,
        target_date: str,
        event_ticker: str,
        started_at_utc: str,
        completed_at_utc: str,
        window_start_utc: str,
        window_end_utc: str,
        status: str,
        reasons: list[str],
        links: dict[str, Any],
        decision_capture_id: int | None = None,
        code_version: str | None = None,
    ) -> int:
        if status not in FORWARD_CAPTURE_STATUSES:
            raise ValueError(f"Unsupported forward capture status: {status}")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO forward_captures(
                    run_id, experiment, phase, mode, target_date, event_ticker,
                    started_at_utc, completed_at_utc, window_start_utc, window_end_utc,
                    status, reasons_json, links_json, decision_capture_id, code_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, experiment, phase, mode, target_date, event_ticker,
                    started_at_utc, completed_at_utc, window_start_utc, window_end_utc,
                    status, json.dumps(reasons), canonical_json(links),
                    decision_capture_id, code_version,
                ),
            )
            return int(cursor.lastrowid)

    def forward_captures(
        self, *, target_date: str | None = None, phase: str | None = None, mode: str = "live"
    ) -> list[sqlite3.Row]:
        """Capture attempts, oldest first, optionally for one target date and phase."""
        clauses, params = ["mode = ?"], [mode]
        if target_date is not None:
            clauses.append("target_date = ?")
            params.append(target_date)
        if phase is not None:
            clauses.append("phase = ?")
            params.append(phase)
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                f"SELECT * FROM forward_captures WHERE {' AND '.join(clauses)} ORDER BY id",
                params,
            ).fetchall()

    # ------------------------------------------------------------ odds capture targets (v5)

    def plan_odds_target(
        self,
        *,
        target_id: str,
        sport: str,
        event_id: str,
        offset_label: str,
        priority: int,
        commence_time_utc: str,
        target_utc: str,
        planned_at_utc: str,
        policy_version: str,
        home_team: str | None = None,
        away_team: str | None = None,
        discovery_snapshot_id: int | None = None,
    ) -> bool:
        """Record a newly planned target and its PLANNED transition, atomically. Returns False
        (and changes nothing) when the target already exists."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO odds_capture_targets(
                    target_id, sport, event_id, offset_label, priority, commence_time_utc,
                    target_utc, planned_at_utc, policy_version, home_team, away_team,
                    discovery_snapshot_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (target_id, sport, event_id, offset_label, priority, commence_time_utc, target_utc,
                 planned_at_utc, policy_version, home_team, away_team, discovery_snapshot_id),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                "INSERT INTO odds_capture_transitions(target_id, state, at_utc) VALUES (?, 'PLANNED', ?)",
                (target_id, planned_at_utc),
            )
            return True

    def record_odds_transition(
        self,
        *,
        target_id: str,
        state: str,
        at_utc: str,
        reason: str | None = None,
        slot_id: str | None = None,
        snapshot_id: int | None = None,
        captured_at_utc: str | None = None,
        credits_last: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        if state not in ODDS_TARGET_STATES:
            raise ValueError(f"Unsupported odds target state: {state}")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO odds_capture_transitions(
                    target_id, state, at_utc, reason, slot_id, snapshot_id, captured_at_utc,
                    credits_last, detail_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (target_id, state, at_utc, reason, slot_id, snapshot_id, captured_at_utc, credits_last,
                 canonical_json(detail or {})),
            )
            return int(cursor.lastrowid)

    def odds_targets(self, *, sport: str | None = None) -> list[sqlite3.Row]:
        """Every target with its current (latest) state, by intended capture time."""
        where, params = ("WHERE t.sport = ?", [sport]) if sport is not None else ("", [])
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                f"""
                SELECT t.*, x.state, x.at_utc AS state_at_utc, x.reason, x.slot_id, x.snapshot_id,
                       x.captured_at_utc, x.credits_last, x.detail_json
                FROM odds_capture_targets t
                JOIN odds_capture_transitions x ON x.id = (
                    SELECT MAX(id) FROM odds_capture_transitions WHERE target_id = t.target_id)
                {where}
                ORDER BY t.target_utc, t.priority, t.event_id
                """,
                params,
            ).fetchall()

    def odds_transitions(self, target_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                "SELECT * FROM odds_capture_transitions WHERE target_id = ? ORDER BY id", (target_id,)
            ).fetchall()

    def latest_snapshot(self, *, source: str, kind: str, entity_id: str) -> sqlite3.Row | None:
        """The newest snapshot of one kind for one entity (payload included), or None."""
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                """
                SELECT id, run_id, entity_id, fetched_at_utc, url, payload_sha256, raw_sha256, payload_json
                FROM snapshots WHERE source = ? AND kind = ? AND entity_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (source, kind, entity_id),
            ).fetchone()

    def recent_snapshots(self, *, limit: int = 20) -> Iterable[sqlite3.Row]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT id, run_id, source, kind, entity_id, fetched_at_utc,
                       source_timestamp_utc, url, payload_sha256
                FROM snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def has_snapshot(self, *, source: str, kind: str, entity_id: str) -> bool:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT 1 FROM snapshots WHERE source = ? AND kind = ? AND entity_id = ? LIMIT 1",
                (source, kind, entity_id),
            ).fetchone()
        return row is not None

    def snapshots_of_kind(self, *, source: str, kind: str) -> list[sqlite3.Row]:
        """Every stored snapshot of one kind, oldest first (payload included)."""
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                """
                SELECT id, run_id, entity_id, fetched_at_utc, source_timestamp_utc, url,
                       payload_sha256, payload_json
                FROM snapshots WHERE source = ? AND kind = ? ORDER BY id
                """,
                (source, kind),
            ).fetchall()

    def save_document(
        self,
        *,
        run_id: str,
        source_id: str,
        doc_type: str,
        fetch: FetchResult,
        series_ticker: str | None = None,
        market_ticker: str | None = None,
    ) -> tuple[int, str, bool]:
        """Store the exact bytes of a retrieved document.

        Returns (retrieval_id, sha256, is_new_version). Old versions are never touched.
        """
        digest = bytes_sha256(fetch.body)
        with closing(self._connect()) as conn, conn:
            previous = conn.execute(
                """
                SELECT sha256 FROM document_retrievals
                WHERE requested_url = ? ORDER BY id DESC LIMIT 1
                """,
                (fetch.requested_url,),
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO document_blobs(sha256, byte_length, body) VALUES (?, ?, ?)",
                (digest, len(fetch.body), fetch.body),
            )
            cursor = conn.execute(
                """
                INSERT INTO document_retrievals(
                    run_id, source_id, doc_type, requested_url, final_url, fetched_at_utc,
                    http_status, content_type, byte_length, sha256, series_ticker,
                    market_ticker, attempts, retry_reasons_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source_id,
                    doc_type,
                    fetch.requested_url,
                    fetch.final_url,
                    fetch.received_at_utc,
                    fetch.http_status,
                    fetch.content_type,
                    len(fetch.body),
                    digest,
                    series_ticker,
                    market_ticker,
                    fetch.attempts,
                    json.dumps(list(fetch.retry_reasons)),
                ),
            )
            is_new = previous is None or previous["sha256"] != digest
            return int(cursor.lastrowid), digest, is_new

    def document_versions(self, requested_url: str) -> list[sqlite3.Row]:
        """Distinct content versions of one URL, with first/last time each was seen."""
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                """
                SELECT sha256, byte_length, MIN(fetched_at_utc) AS first_seen_utc,
                       MAX(fetched_at_utc) AS last_seen_utc, COUNT(*) AS retrievals
                FROM document_retrievals WHERE requested_url = ?
                GROUP BY sha256 ORDER BY MIN(id)
                """,
                (requested_url,),
            ).fetchall()

    def document_hashes(self, *, doc_type: str) -> list[str]:
        """Distinct content hashes stored for a document type, oldest first."""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT sha256 FROM document_retrievals WHERE doc_type = ? GROUP BY sha256 ORDER BY MIN(id)",
                (doc_type,),
            ).fetchall()
        return [row["sha256"] for row in rows]

    def document_bytes(self, sha256: str) -> bytes | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT body FROM document_blobs WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return bytes(row["body"]) if row else None

    def run_source_totals(
        self, run_id: str, source: str, source_id: str | None = None
    ) -> tuple[int, int, int]:
        """(records, payload_bytes, retries) actually stored for one source in a run.

        Records count JSON snapshots under the legacy `source` name plus raw documents
        stored under `source_id`.
        """
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0),
                       COALESCE(SUM(MAX(COALESCE(attempts, 1) - 1, 0)), 0)
                FROM snapshots WHERE run_id = ? AND source = ?
                """,
                (run_id, source),
            ).fetchone()
            docs = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(byte_length), 0),
                       COALESCE(SUM(MAX(COALESCE(attempts, 1) - 1, 0)), 0)
                FROM document_retrievals WHERE run_id = ? AND source_id = ?
                """,
                (run_id, source_id),
            ).fetchone()
        return (
            int(row[0]) + int(docs[0]),
            int(row[1]) + int(docs[1]),
            int(row[2]) + int(docs[2]),
        )

    def record_source_health(
        self,
        *,
        run_id: str,
        source_id: str,
        started_at_utc: str,
        completed_at_utc: str,
        duration_ms: int,
        status: str,
        records: int,
        payload_bytes: int = 0,
        http_errors: int = 0,
        retries: int = 0,
        anomalies: list[str] | None = None,
        error: str | None = None,
    ) -> int:
        if status not in SOURCE_HEALTH_STATUSES:
            raise ValueError(f"Unsupported source health status: {status}")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO source_health(
                    run_id, source_id, started_at_utc, completed_at_utc, duration_ms,
                    status, records, payload_bytes, http_errors, retries,
                    anomalies_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source_id,
                    started_at_utc,
                    completed_at_utc,
                    duration_ms,
                    status,
                    records,
                    payload_bytes,
                    http_errors,
                    retries,
                    json.dumps(anomalies or []),
                    error,
                ),
            )
            return int(cursor.lastrowid)

    def latest_source_health(self) -> list[sqlite3.Row]:
        """Most recent health row per source, plus its last successful completion."""
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                """
                SELECT h.*,
                       (SELECT MAX(completed_at_utc) FROM source_health s
                        WHERE s.source_id = h.source_id AND s.status = 'ok')
                           AS last_ok_at_utc
                FROM source_health h
                WHERE h.id = (SELECT MAX(id) FROM source_health x
                              WHERE x.source_id = h.source_id)
                ORDER BY h.source_id
                """
            ).fetchall()

    def latest_fetch_by_kind(self, source: str) -> dict[str, str]:
        """Latest receipt timestamp per payload kind for one legacy source name."""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT kind, MAX(fetched_at_utc) AS latest
                FROM snapshots WHERE source = ? GROUP BY kind
                """,
                (source,),
            ).fetchall()
        return {row["kind"]: row["latest"] for row in rows}



if __name__ == "__main__":
    raise SystemExit(main())
