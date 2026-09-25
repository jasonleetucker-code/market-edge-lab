"""Additive public metadata reads on the evidence store (EE v1 PR B): no payloads, bounded, read-only."""

import pytest

from edge_lab.storage import SnapshotStore


def _save(store, entity, kind="orderbook", source="kalshi"):
    return store.save_snapshot(run_id="r1", source=source, kind=kind, entity_id=entity, url=f"https://x/{entity}",
                               payload={"entity": entity}, fetched_at_utc="2026-09-24T12:00:00Z")


def test_snapshot_metadata_is_payload_free_prefix_exact_and_paged(tmp_path):
    store = SnapshotStore(tmp_path / "e.sqlite3")
    store.start_run("r1")
    ids = [_save(store, e) for e in ("KXNFLGAME-A", "KXNFLGAME-B", "KX%GAME-C", "KXHIGHNY-D")]
    _save(store, "KXNFLGAME-E", kind="markets")
    rows = store.snapshot_metadata(source="kalshi", kinds=["orderbook"], entity_prefix="KXNFLGAME", limit=10)
    assert [r["entity_id"] for r in rows] == ["KXNFLGAME-A", "KXNFLGAME-B"]
    assert "payload_json" not in rows[0].keys() and rows[0]["payload_sha256"]
    assert [r["entity_id"] for r in store.snapshot_metadata(source="kalshi", kinds=["orderbook"],
                                                            entity_prefix="KX%", limit=10)] == ["KX%GAME-C"]
    page = store.snapshot_metadata(source="kalshi", kinds=["orderbook", "markets"], limit=2, after_id=ids[1])
    assert [r["entity_id"] for r in page] == ["KX%GAME-C", "KXHIGHNY-D"]
    assert store.max_row_id("snapshots") == max(ids) + 1
    with pytest.raises(ValueError):
        store.max_row_id("sqlite_master")
    with pytest.raises(ValueError):
        store.snapshot_metadata(source="kalshi", kinds=[], limit=1)
    readonly = SnapshotStore.open_readonly(tmp_path / "e.sqlite3")
    assert len(readonly.snapshot_metadata(source="kalshi", kinds=["orderbook"], limit=10)) == 4
