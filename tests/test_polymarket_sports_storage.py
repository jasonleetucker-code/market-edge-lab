"""Evidence schema v7 (ADR 0032): additive Polymarket US NFL pilot tables and the v7 -> v6 rollback stamp.

The v6 -> v5 -> v4 chain is pinned in tests/test_storage_rollback.py (with "the current code" held
at v6 there); this file covers the step this lane added."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from edge_lab import storage
from edge_lab.storage import SnapshotStore


def _v7_store_with_rows(tmp_path: Path) -> Path:
    db = tmp_path / "edge.sqlite3"
    store = SnapshotStore(db)
    assert store.schema_version() == storage.SCHEMA_VERSION == 7
    store.start_run("r")
    store.record_pm_sports_scan({
        "scan_id": "s1", "run_id": "r", "league": "nfl", "endpoint": "e", "started_at_utc": "2026-09-24T21:00:00+00:00",
        "completed_at_utc": "2026-09-24T21:00:02+00:00", "coverage_state": "PARTIAL", "filter_complete": 1,
        "pages_ok": 2, "requests": 2, "events": 1, "markets": 1, "coverage_detail": "d", "page_snapshot_ids_json": "[]",
        "catalog_json": "[]", "anomalies_json": "[]", "parser_version": "1", "policy_version": "v"})
    target = {"target_id": "t1", "league": "nfl", "market_slug": "m", "pm_event_slug": "e", "odds_event_id": "o",
              "relationship": "RELATED_NOT_EQUIVALENT", "relationship_json": "{}", "offset_label": "T-60m", "priority": 1,
              "game_start_utc": "2026-09-27T17:00:00+00:00", "target_utc": "2026-09-27T16:00:00+00:00",
              "effective_utc": "2026-09-27T16:00:00+00:00", "due_from_utc": "2026-09-27T15:53:00+00:00",
              "deadline_utc": "2026-09-27T16:30:00+00:00", "planned_at_utc": "2026-09-24T21:00:02+00:00",
              "scan_id": "s1", "planned_rules_sha256": None, "policy_version": "v", "detail_json": "{}"}
    assert store.plan_pm_sports_target(target)
    assert not store.plan_pm_sports_target({**target, "target_utc": "changed"})  # re-planning keeps the original
    store.record_pm_sports_observation({"run_id": "r", "attempt_id": "a1", "target_id": "t1", "status": "MISSED",
                                        "reason": "NOT_CAPTURED_BY_DEADLINE", "freshness": "unknown",
                                        "recorded_at_utc": "2026-09-27T16:31:00+00:00", "policy_version": "v"})
    store.finish_run("r", status="succeeded")
    return db


def _version(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_v7_objects_are_additive_and_touch_no_older_table():
    for obj in storage.V7_OBJECTS:
        assert obj.startswith(("pm_sports_", "idx_pm_sports_")), obj
    older = storage.V5_OBJECTS | storage.V6_OBJECTS
    assert not storage.V7_OBJECTS & older
    for trigger in ("ON pm_sports_scans", "ON pm_sports_targets", "ON pm_sports_observations"):
        assert trigger in storage._SCHEMA_V7
    assert "ON snapshots" not in storage._SCHEMA_V7 and "ALTER TABLE" not in storage._SCHEMA_V7


def test_captured_rows_need_evidence_and_other_rows_carry_no_prices(tmp_path):
    db = _v7_store_with_rows(tmp_path)
    store = SnapshotStore(db)
    base = {"run_id": "r", "target_id": "t1", "freshness": "unknown", "recorded_at_utc": "x", "policy_version": "v"}
    with pytest.raises(sqlite3.IntegrityError):  # final is final (MISSED already)
        store.record_pm_sports_observation({**base, "attempt_id": "a2", "status": "FAILED", "reason": "late"})
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO pm_sports_targets(target_id, league, market_slug, relationship, relationship_json, "
                     "offset_label, priority, game_start_utc, target_utc, effective_utc, due_from_utc, deadline_utc, "
                     "planned_at_utc, scan_id, policy_version) VALUES ('t2', 'nfl', 'm', 'RELATED_NOT_EQUIVALENT', '{}', "
                     "'T-6h', 2, '2026-09-27T17:00:00+00:00', '2026-09-27T11:00', '2026-09-27T11:00', '2026-09-27T10:53', "
                     "'2026-09-27T11:30', 'p', 's1', 'v')")
        with pytest.raises(sqlite3.IntegrityError):  # a captured row without evidence
            conn.execute("INSERT INTO pm_sports_observations(run_id, attempt_id, target_id, status, freshness, "
                         "recorded_at_utc, policy_version) VALUES ('r', 'a3', 't2', 'CAPTURED', 'fresh', 'x', 'v')")
        with pytest.raises(sqlite3.IntegrityError):  # a failed row with prices
            conn.execute("INSERT INTO pm_sports_observations(run_id, attempt_id, target_id, status, reason, yes_bid, "
                         "freshness, recorded_at_utc, policy_version) VALUES ('r', 'a4', 't2', 'FAILED', 'x', '0.5', "
                         "'unknown', 'x', 'v')")
        with pytest.raises(sqlite3.IntegrityError):  # there is no equivalent relationship state
            conn.execute("INSERT INTO pm_sports_targets(target_id, league, market_slug, relationship, relationship_json, "
                         "offset_label, priority, game_start_utc, target_utc, effective_utc, due_from_utc, deadline_utc, "
                         "planned_at_utc, scan_id, policy_version) VALUES ('t3', 'nfl', 'm', 'EQUIVALENT', '{}', "
                         "'T-6h', 2, '2026-09-27T17:00:00+00:00', '2026-09-27T11:00', '2026-09-27T11:00', "
                         "'2026-09-27T10:53', '2026-09-27T11:30', 'p', 's1', 'v')")


def test_v7_to_v6_stamp_keeps_every_row_and_refuses_anything_else(tmp_path, capsys):
    db = _v7_store_with_rows(tmp_path)
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 1  # a v7 store must go to v6 first
    assert "expected a v6 evidence store, found v7" in json.loads(capsys.readouterr().out)["detail"]
    assert storage.main(["mark-v6-for-rollback", "--db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out) == {"db": str(db), "from": 7, "to": 6, "pm_sports_targets_kept": 1,
                                                   "pm_sports_scans_kept": 1, "pm_sports_observations_kept": 1}
    assert _version(db) == 6
    assert storage.main(["mark-v6-for-rollback", "--db", str(db)]) == 1  # already v6: refused
    capsys.readouterr()
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 0  # the chain continues
    capsys.readouterr()
    # Re-installing the current code stamps v7 again; nothing is lost.
    store = SnapshotStore(db)
    assert store.schema_version() == 7 and len(store.pm_sports_targets()) == 1


def test_the_helper_refuses_an_incomplete_v7_store(tmp_path, capsys):
    db = _v7_store_with_rows(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER pm_sports_observations_final_is_final")
    assert storage.main(["mark-v6-for-rollback", "--db", str(db)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "REFUSED" and "pm_sports_observations_final_is_final" in out["detail"]
    assert _version(db) == 7
    SnapshotStore(db)  # the write path re-creates the missing object
    assert storage.main(["mark-v6-for-rollback", "--db", str(db)]) == 0


def test_a_v6_stamped_store_opens_and_backs_up_verified_under_v6_semantics(tmp_path, monkeypatch):
    """In-process stand-in for the v6 code: SCHEMA_VERSION 6, so no v7 step."""
    from edge_lab import backup

    db = _v7_store_with_rows(tmp_path)
    storage.mark_schema_v6_for_rollback(db)
    monkeypatch.setattr(storage, "SCHEMA_VERSION", 6)
    monkeypatch.setattr(backup, "CURRENT_SCHEMA_VERSION", 6)
    monkeypatch.setattr(backup, "_reference_triggers_cache", None)
    store = SnapshotStore(db)
    assert store.schema_version() == 6 and SnapshotStore.open_readonly(db).schema_version() == 6
    store.start_run("after-rollback")
    assert backup.create_backup(db, tmp_path / "backups").exists()


V6_COMMIT = "e6dfb69"  # main before schema v7 (ADR 0032)


def test_the_real_v6_code_opens_and_backs_up_a_stamped_v7_store(tmp_path):
    import os
    import subprocess
    import sys

    from test_storage_rollback import _extract_code, _probe, _real_code_opens_and_backs_up

    src = _extract_code(V6_COMMIT, tmp_path / "v6")
    if src is None:
        pytest.skip(f"commit {V6_COMMIT} is not in this checkout (shallow clone)")
    db = _v7_store_with_rows(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(src)}
    refused = subprocess.run([sys.executable, "-c", _probe(6), str(db)], env=env, capture_output=True, text=True,
                             timeout=120)
    assert refused.returncode != 0 and "newer than this code" in refused.stderr  # why the helper exists
    storage.mark_schema_v6_for_rollback(db)
    report = _real_code_opens_and_backs_up(src, db, 6, tmp_path / "backups")
    assert report["row_counts"]["pm_sports_targets"] == 1


def test_the_current_code_backs_up_a_v7_store_verified(tmp_path):
    from edge_lab import backup

    db = _v7_store_with_rows(tmp_path)
    assert backup.create_backup(db, tmp_path / "backups").exists()
