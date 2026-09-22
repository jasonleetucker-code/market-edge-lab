"""Raw evidence is append-only."""

import sqlite3

import pytest

from edge_lab.storage import SnapshotStore


@pytest.fixture
def store_with_row(tmp_path):
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    store.save_snapshot(
        run_id="r", source="kalshi", kind="orderbook", entity_id="T",
        url="https://example.test", payload={"orderbook_fp": {}},
    )
    return store


@pytest.mark.parametrize(
    "sql",
    ["UPDATE snapshots SET payload_json = '{}'", "UPDATE snapshots SET fetched_at_utc = 'x'", "DELETE FROM snapshots"],
)
def test_snapshots_cannot_be_modified_or_deleted(store_with_row, sql):
    with sqlite3.connect(store_with_row.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(sql)
    assert len(list(store_with_row.recent_snapshots())) == 1


def test_insert_or_replace_cannot_overwrite_a_snapshot(store_with_row):
    with sqlite3.connect(store_with_row.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "INSERT OR REPLACE INTO snapshots(id, run_id, source, kind, entity_id,"
                " fetched_at_utc, url, payload_sha256, payload_json)"
                " VALUES (1, 'r', 'kalshi', 'orderbook', 'T', 't', 'u', 'forged', '{}')"
            )
    (row,) = store_with_row.recent_snapshots()
    assert row["payload_sha256"] != "forged"


def test_source_health_history_cannot_be_rewritten(store_with_row):
    store_with_row.record_source_health(
        run_id="r", source_id="kalshi_public", started_at_utc="t0", completed_at_utc="t1",
        duration_ms=1, status="failed", records=0, error="HTTP 503",
    )
    with sqlite3.connect(store_with_row.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE source_health SET status = 'ok', error = NULL")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM source_health")


def test_finished_run_outcome_cannot_be_changed(store_with_row):
    store_with_row.finish_run("r", status="failed", error="all sources failed")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store_with_row.finish_run("r", status="succeeded")
    with sqlite3.connect(store_with_row.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM collection_runs")
