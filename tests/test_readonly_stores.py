"""Analysis opens the evidence store and ledger without creating, migrating or changing them."""

import gc
import hashlib
import sqlite3

from decimal import Decimal

import pytest

from edge_lab.shadow_ledger import LedgerError, ShadowLedger
from edge_lab.storage import SCHEMA_VERSION, ReadOnlyStoreError, SnapshotStore


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(dirpath):
    return sorted(p.name for p in dirpath.iterdir())


def test_evidence_readonly_open_changes_nothing(tmp_path):
    db = tmp_path / "evidence.sqlite3"
    SnapshotStore(db).start_run("r1")
    # Checkpoint WAL so the main file holds everything, then snapshot the directory.
    gc.collect()  # release the writer's connections before switching journal mode
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()
    before, names, mtime = _digest(db), _files(tmp_path), db.stat().st_mtime_ns
    store = SnapshotStore.open_readonly(db)
    assert store.read_only and store.schema_version() == SCHEMA_VERSION
    store.forward_captures()
    store.recent_snapshots()
    with pytest.raises(sqlite3.OperationalError):
        store.start_run("r2")
    assert _digest(db) == before and db.stat().st_mtime_ns == mtime
    assert _files(tmp_path) == names


def test_evidence_readonly_refuses_missing_symlink_and_wrong_schema(tmp_path):
    with pytest.raises(ReadOnlyStoreError):
        SnapshotStore.open_readonly(tmp_path / "missing.sqlite3")
    assert not (tmp_path / "missing.sqlite3").exists()
    old = tmp_path / "old.sqlite3"
    with sqlite3.connect(old) as conn:
        conn.execute("PRAGMA user_version = 3")
    with pytest.raises(ReadOnlyStoreError):
        SnapshotStore.open_readonly(old)
    real = tmp_path / "real.sqlite3"
    SnapshotStore(real)
    link = tmp_path / "link.sqlite3"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ReadOnlyStoreError):
        SnapshotStore.open_readonly(link)


_ACCT = dict(starting_bankroll=Decimal("100"), strategy="t", opened_at_utc="2026-09-23T00:00:00+00:00",
             sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="x")


def test_ledger_readonly_open_changes_nothing(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = ShadowLedger(path)
    ledger.open_account("A", **_ACCT)
    before = _digest(path)
    ro = ShadowLedger.open_readonly(path)
    assert ro.read_only and ro.accounts() == ["A"] and ro.state("A").settled_cash == 100
    with pytest.raises(sqlite3.OperationalError):
        ro.open_account("B", **_ACCT)
    assert _digest(path) == before
    with pytest.raises(LedgerError):
        ShadowLedger.open_readonly(tmp_path / "none.sqlite3")
    assert not (tmp_path / "none.sqlite3").exists()
