"""The evidence schema is forward-only unless the rollback helper stamps it back (runbook "Rollback").

v5 (ADR 0029) only added the odds capture tables; v6 (ADR 0030) only added the price observation
tables. After `mark-v5-for-rollback` the previous (v5) code, and after a further
`mark-v4-for-rollback` the v4 code, must open the store read/write and read-only, and their
backups must still be VERIFIED. Re-installing the newer code stamps it again and keeps every row."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from edge_lab import storage
from edge_lab.storage import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
V4_COMMIT = "dd3ab4d"  # main before schema v5 (PR #57)
V5_COMMIT = "cbfbddf"  # main before schema v6 (ADR 0030)


@pytest.fixture(autouse=True)
def _v6_code(monkeypatch):
    """These tests pin the v6 -> v5 -> v4 chain, so "the current code" here is the v6 code (no v7
    step). The v7 -> v6 step (ADR 0032) is tested in tests/test_polymarket_sports_storage.py."""
    from edge_lab import backup

    monkeypatch.setattr(storage, "SCHEMA_VERSION", 6)
    monkeypatch.setattr(backup, "CURRENT_SCHEMA_VERSION", 6)
    monkeypatch.setattr(backup, "_reference_triggers_cache", None)


def _v6_store_with_rows(tmp_path: Path) -> Path:
    db = tmp_path / "edge.sqlite3"
    store = SnapshotStore(db)
    store.start_run("r")
    sid = store.save_snapshot(run_id="r", source="the_odds_api", kind="events", entity_id="nfl", url="u",
                              payload={"events": []})
    store.plan_odds_target(target_id="t1", sport="nfl", event_id="e1", offset_label="T-60m", priority=1,
                           commence_time_utc="2026-10-04T17:00:00Z", target_utc="2026-10-04T16:00:00Z",
                           planned_at_utc="2026-10-01T12:00:00Z", policy_version="v", discovery_snapshot_id=sid)
    target = {"target_id": "kalshi:M|custom|2026-10-01T12:00:00+00:00", "venue": "kalshi", "market_id": "kalshi:M",
              "native_market_id": "M", "event_id": "kalshi:E", "native_event_id": "E", "phase": "custom",
              "target_utc": "2026-10-01T12:00:00+00:00", "due_from_utc": "2026-10-01T11:55:00+00:00",
              "deadline_utc": "2026-10-01T12:30:00+00:00", "planned_at_utc": "2026-10-01T11:00:00+00:00",
              "policy_version": "v", "origin": "manual", "close_basis": "kalshi_close_time_v1"}
    assert store.plan_price_target(target)
    store.record_price_observations([{
        "run_id": "r", "attempt_id": "a1", "target_id": target["target_id"], "phase": "custom", "venue": "kalshi",
        "market_id": "kalshi:M", "native_market_id": "M", "event_id": "kalshi:E", "side": "YES",
        "target_utc": target["target_utc"], "observed_at_utc": "2026-10-01T12:00:01+00:00", "bid": "0.40",
        "ask": "0.42", "ask_size": "10", "depth_json": "{}", "freshness": "fresh", "snapshot_id": sid,
        "collection_status": "CAPTURED", "recorded_at_utc": "2026-10-01T12:00:02+00:00", "policy_version": "v"}])
    store.finish_run("r", status="succeeded")
    assert store.schema_version() == storage.SCHEMA_VERSION == 6
    return db


def _version(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_v6_to_v5_stamp_keeps_every_row_and_refuses_anything_else(tmp_path, capsys):
    db = _v6_store_with_rows(tmp_path)
    assert storage.main(["mark-v4-for-rollback", "--db", str(db)]) == 1  # a v6 store must go to v5 first
    assert "expected a v5 evidence store, found v6" in json.loads(capsys.readouterr().out)["detail"]
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out) == {"db": str(db), "from": 6, "to": 5,
                                                   "price_observation_targets_kept": 1, "price_observations_kept": 1}
    assert _version(db) == 5
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 1
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 1  # already v5: refused
    assert json.loads(capsys.readouterr().out)["status"] == "REFUSED"
    assert storage.main(["mark-v5-for-rollback", "--db", str(tmp_path / "missing.sqlite3")]) == 1
    # Re-installing v6 code stamps v6 again; nothing is lost.
    store = SnapshotStore(db)
    assert store.schema_version() == 6 and len(store.price_observations()) == 1 and len(store.odds_targets()) == 1


def test_the_chain_v6_v5_v4_keeps_every_row(tmp_path, capsys):
    db = _v6_store_with_rows(tmp_path)
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 0
    assert storage.main(["mark-v4-for-rollback", "--db", str(db)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[-1]) == {"db": str(db), "from": 5, "to": 4, "odds_targets_kept": 1}
    assert _version(db) == 4
    assert SnapshotStore(db).schema_version() == 6  # current code migrates forward again, idempotently


def test_a_v5_stamped_store_opens_and_backs_up_verified_under_v5_semantics(tmp_path, monkeypatch):
    """In-process stand-in for the v5 code: SCHEMA_VERSION 5, so no v6 step."""
    from edge_lab import backup

    db = _v6_store_with_rows(tmp_path)
    storage.mark_schema_v5_for_rollback(db)
    monkeypatch.setattr(storage, "SCHEMA_VERSION", 5)
    monkeypatch.setattr(backup, "CURRENT_SCHEMA_VERSION", 5)
    monkeypatch.setattr(backup, "_reference_triggers_cache", None)
    store = SnapshotStore(db)  # v5 write path: no "newer than this code" refusal
    assert store.schema_version() == 5 and SnapshotStore.open_readonly(db).schema_version() == 5
    store.start_run("after-rollback")
    bundle = backup.create_backup(db, tmp_path / "backups")  # raises BackupError unless verified
    assert bundle.exists()


def test_a_v4_stamped_store_opens_and_backs_up_verified_under_v4_semantics(tmp_path, monkeypatch):
    """In-process stand-in for the v4 code: SCHEMA_VERSION 4 and no v5 script."""
    from edge_lab import backup

    db = _v6_store_with_rows(tmp_path)
    storage.mark_schema_v5_for_rollback(db)
    storage.mark_schema_v4_for_rollback(db)
    monkeypatch.setattr(storage, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(storage, "_SCHEMA_V5", "")
    monkeypatch.setattr(backup, "CURRENT_SCHEMA_VERSION", 4)
    monkeypatch.setattr(backup, "_reference_triggers_cache", None)
    store = SnapshotStore(db)
    assert store.schema_version() == 4 and SnapshotStore.open_readonly(db).schema_version() == 4
    store.start_run("after-rollback")
    assert backup.create_backup(db, tmp_path / "backups").exists()


def _extract_code(commit: str, dest: Path) -> Path | None:
    try:
        archive = subprocess.run(["git", "archive", commit, "src/edge_lab"], cwd=ROOT, capture_output=True,
                                 timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data") if sys.version_info >= (3, 12) else tar.extractall(dest)
    return dest / "src"


def _probe(version: int) -> str:
    return (f"import sys; from edge_lab.storage import SnapshotStore, SCHEMA_VERSION; assert SCHEMA_VERSION == {version};"
            "SnapshotStore(sys.argv[1])")


def _real_code_opens_and_backs_up(src: Path, db: Path, version: int, backups: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(src)}
    opened = subprocess.run([sys.executable, "-c", _probe(version) + ";SnapshotStore.open_readonly(sys.argv[1])",
                             str(db)], env=env, capture_output=True, text=True, timeout=120)
    assert opened.returncode == 0, opened.stderr
    result = subprocess.run([sys.executable, "-m", "edge_lab.backup", "create", "--db", str(db), "--out", str(backups)],
                            env=env, capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout)
    assert report["status"] == "VERIFIED_BACKUP_AND_RESTORE", result.stdout + result.stderr
    assert report["schema_version"] == version
    return report


def test_the_real_v5_code_opens_and_backs_up_a_stamped_v6_store(tmp_path):
    src = _extract_code(V5_COMMIT, tmp_path / "v5")
    if src is None:
        pytest.skip(f"commit {V5_COMMIT} is not in this checkout (shallow clone)")
    db = _v6_store_with_rows(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(src)}
    refused = subprocess.run([sys.executable, "-c", _probe(5), str(db)], env=env, capture_output=True, text=True,
                             timeout=120)
    assert refused.returncode != 0 and "newer than this code" in refused.stderr  # why the helper exists
    storage.mark_schema_v5_for_rollback(db)
    report = _real_code_opens_and_backs_up(src, db, 5, tmp_path / "backups")
    assert report["row_counts"]["price_observations"] == 1 and report["row_counts"]["odds_capture_targets"] == 1
    # Back on the new code: v6 again, rows intact, and a v6 backup is VERIFIED too.
    from edge_lab import backup

    assert SnapshotStore(db).schema_version() == 6
    assert backup.create_backup(db, tmp_path / "backups-v6").exists()


def test_the_real_v4_code_opens_and_backs_up_a_twice_stamped_store(tmp_path):
    src = _extract_code(V4_COMMIT, tmp_path / "v4")
    if src is None:
        pytest.skip(f"commit {V4_COMMIT} is not in this checkout (shallow clone)")
    db = _v6_store_with_rows(tmp_path)
    storage.mark_schema_v5_for_rollback(db)
    storage.mark_schema_v4_for_rollback(db)
    report = _real_code_opens_and_backs_up(src, db, 4, tmp_path / "backups")
    assert report["row_counts"]["odds_capture_targets"] == 1 and report["row_counts"]["price_observations"] == 1


@pytest.mark.parametrize("dropped", ["price_observations_final_is_final", "price_observation_targets_no_update",
                                     "idx_price_observations_attempt_side"])
def test_the_helper_refuses_an_incomplete_v6_store(tmp_path, capsys, dropped):
    db = _v6_store_with_rows(tmp_path)
    kind = "INDEX" if dropped.startswith("idx_") else "TRIGGER"
    with sqlite3.connect(db) as conn:
        conn.execute(f"DROP {kind} {dropped}")
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "REFUSED" and dropped in out["detail"]
    assert _version(db) == 6
    SnapshotStore(db)  # the v6 write path re-creates the missing object
    assert storage.main(["mark-v5-for-rollback", "--db", str(db)]) == 0


def test_the_helper_refuses_an_incomplete_v5_store(tmp_path, capsys):
    db = _v6_store_with_rows(tmp_path)
    storage.mark_schema_v5_for_rollback(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER odds_capture_transitions_final_is_final")
    assert storage.main(["mark-v4-for-rollback", "--db", str(db)]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["status"] == "REFUSED" and "odds_capture_transitions_final_is_final" in out["detail"]
    assert _version(db) == 5
