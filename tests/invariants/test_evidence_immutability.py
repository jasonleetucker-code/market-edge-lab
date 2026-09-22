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
