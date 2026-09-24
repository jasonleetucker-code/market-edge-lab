"""Schema v5 is forward-only unless the rollback helper stamps it back to v4 (runbook "Rollback").

The v5 migration only adds the odds capture tables. After `mark-v4-for-rollback`, the previous
(v4) code must open the store read/write and read-only, and its backup must still be VERIFIED."""

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


def _v5_store_with_rows(tmp_path: Path) -> Path:
    db = tmp_path / "edge.sqlite3"
    store = SnapshotStore(db)
    store.start_run("r")
    sid = store.save_snapshot(run_id="r", source="the_odds_api", kind="events", entity_id="nfl", url="u",
                              payload={"events": []})
    store.finish_run("r", status="succeeded")
    store.plan_odds_target(target_id="t1", sport="nfl", event_id="e1", offset_label="T-60m", priority=1,
                           commence_time_utc="2026-10-04T17:00:00Z", target_utc="2026-10-04T16:00:00Z",
                           planned_at_utc="2026-10-01T12:00:00Z", policy_version="v", discovery_snapshot_id=sid)
    assert store.schema_version() == 5
    return db


def test_rollback_helper_stamps_v4_keeps_every_row_and_refuses_anything_else(tmp_path, capsys):
    db = _v5_store_with_rows(tmp_path)
    assert storage.main(["mark-v4-for-rollback", "--db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out) == {"db": str(db), "from": 5, "to": 4, "odds_targets_kept": 1}
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM odds_capture_transitions").fetchone()[0] == 1
    assert storage.main(["mark-v4-for-rollback", "--db", str(db)]) == 1  # already v4: refused
    assert json.loads(capsys.readouterr().out)["status"] == "REFUSED"
    assert storage.main(["mark-v4-for-rollback", "--db", str(tmp_path / "missing.sqlite3")]) == 1
    # Re-installing v5 code stamps v5 again; nothing is lost.
    assert SnapshotStore(db).schema_version() == 5 and len(SnapshotStore(db).odds_targets()) == 1


def test_a_stamped_store_opens_and_backs_up_verified_under_v4_semantics(tmp_path, monkeypatch):
    """In-process stand-in for the v4 code: SCHEMA_VERSION 4 and no v5 script."""
    from edge_lab import backup

    db = _v5_store_with_rows(tmp_path)
    storage.mark_schema_v4_for_rollback(db)
    monkeypatch.setattr(storage, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(storage, "_SCHEMA_V5", "")
    monkeypatch.setattr(backup, "CURRENT_SCHEMA_VERSION", 4)
    monkeypatch.setattr(backup, "_reference_triggers_cache", None)
    store = SnapshotStore(db)  # v4 write path: no "newer than this code" refusal
    assert store.schema_version() == 4 and SnapshotStore.open_readonly(db).schema_version() == 4
    store.start_run("after-rollback")
    bundle = backup.create_backup(db, tmp_path / "backups")  # raises BackupError unless verified
    assert bundle.exists()


def _extract_v4_code(dest: Path) -> Path | None:
    try:
        archive = subprocess.run(["git", "archive", V4_COMMIT, "src/edge_lab"], cwd=ROOT, capture_output=True,
                                 timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data") if sys.version_info >= (3, 12) else tar.extractall(dest)
    return dest / "src"


def test_the_real_v4_code_opens_and_backs_up_a_stamped_store(tmp_path):
    src = _extract_v4_code(tmp_path / "v4")
    if src is None:
        pytest.skip(f"commit {V4_COMMIT} is not in this checkout (shallow clone)")
    db = _v5_store_with_rows(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(src)}
    probe = ("import sys; from edge_lab.storage import SnapshotStore, SCHEMA_VERSION; assert SCHEMA_VERSION == 4;"
             "SnapshotStore(sys.argv[1])")
    refused = subprocess.run([sys.executable, "-c", probe, str(db)], env=env, capture_output=True, text=True,
                             timeout=120)
    assert refused.returncode != 0 and "newer than this code" in refused.stderr  # why the helper exists
    storage.mark_schema_v4_for_rollback(db)
    opened = subprocess.run([sys.executable, "-c", probe + ";SnapshotStore.open_readonly(sys.argv[1])", str(db)],
                            env=env, capture_output=True, text=True, timeout=120)
    assert opened.returncode == 0, opened.stderr
    result = subprocess.run([sys.executable, "-m", "edge_lab.backup", "create", "--db", str(db), "--out",
                             str(tmp_path / "backups")], env=env, capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout)
    assert report["status"] == "VERIFIED_BACKUP_AND_RESTORE", result.stdout + result.stderr
    assert report["schema_version"] == 4 and report["row_counts"]["odds_capture_targets"] == 1
