from __future__ import annotations

import json
import sqlite3

from edge_lab.storage import SnapshotStore


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
