from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            conn.executescript(
                """
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
            )

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
    ) -> int:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        fetched = fetched_at_utc or utc_now_iso()

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots(
                    run_id, source, kind, entity_id, fetched_at_utc,
                    source_timestamp_utc, url, payload_sha256, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
