from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .http import FetchResult
from .provenance import bytes_sha256, canonical_json, sha256_hex, shape_fingerprint

SCHEMA_VERSION = 2
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
)

_SCHEMA_V2 = """
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
"""


class SnapshotStore:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema v{version} is newer than this code (v{SCHEMA_VERSION})"
                )
            conn.executescript(_SCHEMA_V1)
            if version < 2:
                existing = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)")}
                for name, sql_type in _SNAPSHOT_V2_COLUMNS:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {sql_type}")
                conn.executescript(_SCHEMA_V2)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def start_run(self, run_id: str) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
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

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots(
                    run_id, source, kind, entity_id, fetched_at_utc,
                    source_timestamp_utc, url, payload_sha256, payload_json,
                    source_id, final_url, http_status, content_type,
                    payload_bytes, raw_sha256, attempts, fetch_duration_ms,
                    parser_version, schema_version, shape_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            return int(cursor.lastrowid)

    def recent_snapshots(self, *, limit: int = 20) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
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

    def run_source_totals(self, run_id: str, source: str) -> tuple[int, int, int]:
        """(records, payload_bytes, retries) actually stored for one source in a run."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0),
                       COALESCE(SUM(MAX(COALESCE(attempts, 1) - 1, 0)), 0)
                FROM snapshots WHERE run_id = ? AND source = ?
                """,
                (run_id, source),
            ).fetchone()
        return int(row[0]), int(row[1]), int(row[2])

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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kind, MAX(fetched_at_utc) AS latest
                FROM snapshots WHERE source = ? GROUP BY kind
                """,
                (source,),
            ).fetchall()
        return {row["kind"]: row["latest"] for row in rows}

