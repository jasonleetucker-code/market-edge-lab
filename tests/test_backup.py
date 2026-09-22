from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from edge_lab import backup


def source_db(tmp_path: Path, *, wal: bool = False):
    path = tmp_path / "source.sqlite3"
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript("""
        CREATE TABLE collection_runs(id INTEGER PRIMARY KEY);
        CREATE TABLE snapshots(id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES collection_runs(id), value TEXT);
        CREATE TRIGGER immutable BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT, 'immutable'); END;
        PRAGMA user_version=3;
        INSERT INTO collection_runs VALUES(1);
        INSERT INTO snapshots VALUES(1,1,'original');
    """)
    conn.commit()
    return path, conn


def test_online_backup_includes_uncheckpointed_wal_and_preserves_triggers(tmp_path):
    source, conn = source_db(tmp_path, wal=True)
    try:
        conn.execute("INSERT INTO snapshots VALUES(2,1,'in WAL')")
        conn.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        bundle = backup.create_backup(source, tmp_path / "backups")
        report = backup.verify_backup(bundle)
        assert report["status"] == "VERIFIED_BACKUP_AND_RESTORE"
        assert report["row_counts"]["snapshots"] == 2
        assert report["schema_version"] == 3
        with closing(sqlite3.connect(bundle / backup.DB_NAME)) as restored:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                restored.execute("UPDATE snapshots SET value='changed'")
        assert conn.execute("SELECT value FROM snapshots WHERE id=2").fetchone() == ("in WAL",)
    finally:
        conn.close()


def test_repeated_backups_do_not_overwrite_previous_evidence(tmp_path):
    source, conn = source_db(tmp_path)
    conn.close()
    first = backup.create_backup(source, tmp_path / "backups")
    digest = backup.file_hash(first / backup.DB_NAME)
    second = backup.create_backup(source, tmp_path / "backups")
    assert first != second
    assert digest == backup.file_hash(first / backup.DB_NAME)
    assert backup.verify_backup(second)["row_counts"]["snapshots"] == 1


def test_missing_source_never_creates_database(tmp_path):
    missing = tmp_path / "typo.sqlite3"
    with pytest.raises(backup.BackupError):
        backup.create_backup(missing, tmp_path / "backups")
    assert not missing.exists()
    assert not (tmp_path / "backups").exists()


def test_wrong_database_and_corrupt_file_rejected_without_published_bundle(tmp_path):
    source = tmp_path / "wrong.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE unrelated(x)")
    with pytest.raises(backup.BackupError, match="required tables"):
        backup.create_backup(source, tmp_path / "backups")
    assert list((tmp_path / "backups").iterdir()) == []
    source.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        backup.create_backup(source, tmp_path / "backups")
    assert list((tmp_path / "backups").iterdir()) == []


def test_foreign_key_violation_is_not_success(tmp_path):
    source, conn = source_db(tmp_path)
    conn.execute("INSERT INTO snapshots VALUES(2,999,'orphan')")
    conn.commit()
    conn.close()
    with pytest.raises(backup.BackupError, match="foreign_key"):
        backup.create_backup(source, tmp_path / "backups")


def test_missing_manifest_and_tampered_bytes_rejected(tmp_path):
    source, conn = source_db(tmp_path)
    conn.close()
    bundle = backup.create_backup(source, tmp_path / "backups")
    manifest = bundle / backup.MANIFEST_NAME
    original = manifest.read_bytes()
    manifest.unlink()
    with pytest.raises(backup.BackupError, match="incomplete"):
        backup.verify_backup(bundle)
    manifest.write_bytes(original)
    with (bundle / backup.DB_NAME).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(backup.BackupError, match="hash or length"):
        backup.verify_backup(bundle)


def test_manifest_cannot_redirect_verification_to_external_file(tmp_path):
    source, conn = source_db(tmp_path)
    conn.close()
    bundle = backup.create_backup(source, tmp_path / "backups")
    manifest = bundle / backup.MANIFEST_NAME
    data = json.loads(manifest.read_text())
    data["database"] = "../../source.sqlite3"
    manifest.write_text(json.dumps(data))
    with pytest.raises(backup.BackupError, match="unsupported"):
        backup.verify_backup(bundle)


def test_incorrect_manifest_counts_rejected(tmp_path):
    source, conn = source_db(tmp_path)
    conn.close()
    bundle = backup.create_backup(source, tmp_path / "backups")
    manifest = bundle / backup.MANIFEST_NAME
    data = json.loads(manifest.read_text())
    data["row_counts"]["snapshots"] = 0
    manifest.write_text(json.dumps(data))
    with pytest.raises(backup.BackupError, match="row_counts"):
        backup.verify_backup(bundle)


def test_timeout_removes_only_own_incomplete_bundle(tmp_path, monkeypatch):
    source, conn = source_db(tmp_path)
    conn.close()
    output = tmp_path / "backups"
    output.mkdir()
    preserved = output / "keep.txt"
    preserved.write_text("existing backup")
    def fail(*args):
        raise backup.BackupError("time budget")
    monkeypatch.setattr(backup, "copy_online", fail)
    with pytest.raises(backup.BackupError):
        backup.create_backup(source, output)
    assert list(output.iterdir()) == [preserved]
    assert source.exists()


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_fails_before_writes(tmp_path, seconds):
    with pytest.raises(ValueError):
        backup.create_backup(tmp_path / "missing", tmp_path / "out", timeout=seconds)
    assert not (tmp_path / "out").exists()


def test_read_only_source_rejects_symlink(tmp_path):
    source, conn = source_db(tmp_path)
    conn.close()
    link = tmp_path / "link"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(backup.BackupError):
        backup.create_backup(link, tmp_path / "backups")


def test_backup_cli_reports_failure_without_exception(tmp_path, capsys):
    assert backup.main(["create", "--db", str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"


def test_backup_current_store_integration(tmp_path):
    # Runs against the real current schema in CI; no network or synthetic stub.
    from edge_lab.storage import SnapshotStore
    store = SnapshotStore(tmp_path / "actual.sqlite3")
    store.start_run("backup-integration")
    store.save_snapshot(run_id="backup-integration", source="kalshi", kind="series", entity_id="S", url="https://example.invalid", payload={"value": 0})
    store.finish_run("backup-integration", status="succeeded")
    bundle = backup.create_backup(store.path, tmp_path / "backups")
    report = backup.verify_backup(bundle)
    assert report["row_counts"]["snapshots"] == 1
    assert report["schema_version"] == store.schema_version()
    with closing(sqlite3.connect(bundle / backup.DB_NAME)) as restored:
        payload, digest = restored.execute("SELECT payload_json,payload_sha256 FROM snapshots").fetchone()
        assert json.loads(payload)["value"] == 0
        assert hashlib.sha256(payload.encode()).hexdigest() == digest
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            restored.execute("DELETE FROM snapshots")


def test_expired_budget_cannot_report_verification_success(tmp_path):
    source, conn = source_db(tmp_path)
    try:
        with pytest.raises(backup.BackupError, match="time budget"):
            backup.inspect_database(conn, 0)
        with pytest.raises(backup.BackupError, match="time budget"):
            backup.file_hash(source, 0)
    finally:
        conn.close()
