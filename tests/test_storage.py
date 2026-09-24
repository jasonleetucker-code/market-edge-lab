from __future__ import annotations

import json
import sqlite3

import pytest

from edge_lab.storage import SCHEMA_VERSION, SnapshotStore


def test_snapshot_store_preserves_raw_payload(tmp_path):
    db = tmp_path / "edge.sqlite3"
    store = SnapshotStore(db)
    run_id = "run-1"
    payload = {"markets": [{"ticker": "TEST", "yes_bid_dollars": "0.42"}]}

    store.start_run(run_id)
    snapshot_id = store.save_snapshot(
        run_id=run_id,
        source="kalshi",
        kind="markets",
        entity_id="TESTSERIES",
        url="https://example.test/markets",
        payload=payload,
        fetched_at_utc="2026-09-22T17:00:00+00:00",
    )
    store.finish_run(run_id, status="succeeded")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT payload_json, payload_sha256 FROM snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        run = conn.execute(
            "SELECT status, finished_at_utc FROM collection_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    assert json.loads(row[0]) == payload
    assert len(row[1]) == 64
    assert run[0] == "succeeded"
    assert run[1] is not None


def test_repeated_identical_payloads_are_kept_as_separate_observations(tmp_path):
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    payload = {"unchanged": True}

    for run_id in ("run-1", "run-2"):
        store.start_run(run_id)
        store.save_snapshot(
            run_id=run_id,
            source="nws",
            kind="forecast",
            entity_id="point",
            url="https://example.test/forecast",
            payload=payload,
        )
        store.finish_run(run_id, status="succeeded")

    rows = list(store.recent_snapshots(limit=10))
    assert len(rows) == 2
    assert rows[0]["payload_sha256"] == rows[1]["payload_sha256"]


MILESTONE_1_DDL = """
CREATE TABLE collection_runs (
    run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, finished_at_utc TEXT,
    status TEXT NOT NULL, error TEXT
);
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, source TEXT NOT NULL,
    kind TEXT NOT NULL, entity_id TEXT NOT NULL, fetched_at_utc TEXT NOT NULL,
    source_timestamp_utc TEXT, url TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL, FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
);
"""


def test_milestone_1_database_migrates_in_place(tmp_path):
    db = tmp_path / "m1.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(MILESTONE_1_DDL)
        conn.execute("INSERT INTO collection_runs VALUES ('old', 't0', 't1', 'succeeded', NULL)")
        conn.execute(
            "INSERT INTO snapshots(run_id, source, kind, entity_id, fetched_at_utc, url,"
            " payload_sha256, payload_json) VALUES ('old','kalshi','series','S','t0','u','h','{}')"
        )

    store = SnapshotStore(db)

    assert store.schema_version() == SCHEMA_VERSION
    rows = list(store.recent_snapshots(limit=10))
    assert len(rows) == 1 and rows[0]["run_id"] == "old"
    # Reopening an already-migrated database is a no-op.
    assert SnapshotStore(db).schema_version() == SCHEMA_VERSION


def test_database_from_newer_code_is_refused(tmp_path):
    db = tmp_path / "future.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError):
        SnapshotStore(db)


def test_fetch_provenance_is_stored(tmp_path):
    from edge_lab.http import FetchResult

    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    fetch = FetchResult(
        requested_url="https://example.test/a",
        final_url="https://example.test/a?redirected=1",
        http_status=200,
        content_type="application/json",
        body=b'{"a": 1}',
        received_at_utc="2026-09-22T17:00:00+00:00",
        duration_ms=12,
        attempts=2,
    )
    snapshot_id = store.save_snapshot(
        run_id="r", source="kalshi", kind="series", entity_id="S",
        url=fetch.requested_url, payload={"a": 1}, fetch=fetch,
        source_id="kalshi_public", parser_version="1", schema_version="1",
    )
    with sqlite3.connect(store.path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()

    assert row["url"] == "https://example.test/a"
    assert row["final_url"].endswith("redirected=1")
    assert row["fetched_at_utc"] == fetch.received_at_utc
    assert row["payload_bytes"] == len(fetch.body)
    assert row["attempts"] == 2 and row["http_status"] == 200
    assert row["raw_sha256"] and row["shape_sha256"]
    assert store.run_source_totals("r", "kalshi") == (1, len(fetch.body), 1)


def _health(store, **overrides):
    values = dict(
        run_id="r", source_id="kalshi_public", started_at_utc="t0", completed_at_utc="t1",
        duration_ms=5, status="ok", records=3,
    )
    values.update(overrides)
    return store.record_source_health(**values)


def test_source_health_invariants_are_enforced_by_schema(tmp_path):
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    _health(store)
    _health(store, status="partial", anomalies=["paginated"])
    _health(store, status="failed", records=0, error="HttpFetchError: HTTP 503")

    with pytest.raises(sqlite3.IntegrityError):
        _health(store, status="failed", records=0, error=None)  # failure must explain itself
    with pytest.raises(sqlite3.IntegrityError):
        _health(store, status="failed", records=4, error="x")  # failure never claims records
    with pytest.raises(sqlite3.IntegrityError):
        _health(store, status="ok", error="x")  # ok carries no error
    with pytest.raises(sqlite3.IntegrityError):
        _health(store, status="partial")  # partial must say why

    latest = store.latest_source_health()
    assert len(latest) == 1
    assert latest[0]["status"] == "failed"
    assert latest[0]["last_ok_at_utc"] == "t1"


def test_every_connection_the_store_opens_is_closed(tmp_path, monkeypatch):
    """A `with conn:` block commits but does not close. Unclosed connections leak file handles
    (and on Windows keep the database from being moved or deleted), so each use must close."""
    import sqlite3

    from edge_lab.http import FetchResult
    from edge_lab.storage import SnapshotStore

    opened: list[sqlite3.Connection] = []
    original = SnapshotStore._connect

    def recording(self):
        conn = original(self)
        opened.append(conn)
        return conn

    monkeypatch.setattr(SnapshotStore, "_connect", recording)
    store = SnapshotStore(tmp_path / "e.sqlite3")
    store.start_run("r")
    fetch = FetchResult("https://x.test/a", "https://x.test/a", 200, "application/json", b"{}",
                        "2026-09-23T18:00:00+00:00", 1, 1)
    store.save_snapshot(run_id="r", source="s", kind="k", entity_id="e", url="https://x.test/a",
                        payload={"a": 1}, fetch=fetch)
    store.save_document(run_id="r", source_id="s", doc_type="t", fetch=fetch)
    store.finish_run("r", status="succeeded")
    store.recent_snapshots()
    store.snapshots_of_kind(source="s", kind="k")
    store.latest_source_health()
    store.schema_version()
    assert len(opened) >= 8
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")  # closed connections refuse every statement


def _v5_store(db):
    from edge_lab import storage

    with sqlite3.connect(db) as conn:
        conn.executescript(storage._SCHEMA_V1)
        for name, sql_type in storage._SNAPSHOT_V2_COLUMNS:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {sql_type}")
        conn.executescript(storage._SCHEMA_V2 + storage._SCHEMA_V3 + storage._SCHEMA_V4 + storage._SCHEMA_V5)
        conn.execute("INSERT INTO collection_runs VALUES ('old', 't0', 't1', 'succeeded', NULL)")
        conn.execute("INSERT INTO snapshots(run_id, source, kind, entity_id, fetched_at_utc, url, payload_sha256,"
                     " payload_json) VALUES ('old', 'kalshi', 'series', 'S', 't0', 'u', 'h', '{}')")
        conn.execute("PRAGMA user_version = 5")


def test_v5_store_migrates_to_v6_additively(tmp_path):
    from edge_lab import storage

    db = tmp_path / "v5.sqlite3"
    _v5_store(db)
    store = SnapshotStore(db)
    # v5 migrates additively to the current version (v6 and every later step, ADR 0030/0032).
    assert store.schema_version() == storage.SCHEMA_VERSION >= 6
    assert [r["run_id"] for r in store.recent_snapshots()] == ["old"]
    with sqlite3.connect(db) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert storage.V6_OBJECTS <= names and storage.V5_OBJECTS <= names
    assert store.price_targets() == [] and store.price_observations() == []


def test_a_failed_v6_migration_leaves_a_clean_v5_store(tmp_path, monkeypatch):
    from edge_lab import storage

    db = tmp_path / "v5.sqlite3"
    _v5_store(db)
    monkeypatch.setattr(storage, "_SCHEMA_V6", storage._SCHEMA_V6 + "\nCREATE TABLE broken (;\n")
    with pytest.raises(sqlite3.OperationalError):
        SnapshotStore(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert not (storage.V6_OBJECTS & names)  # all or nothing
    monkeypatch.undo()
    assert SnapshotStore(db).schema_version() == storage.SCHEMA_VERSION  # the next open migrates cleanly
