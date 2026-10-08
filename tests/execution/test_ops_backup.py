"""Private journal backups, restore drills and their failure modes (#160 package O, ADR 0047). FIXTURE only, offline;
every journal and backup root lives under pytest's tmp_path.

Covers: identity-preserving backup and restore, a consistent snapshot while a writer is live, restore only to a NEW
path, backup failure at every stage, disk pressure, an exhausted time budget, obsolete state (an old backup, in-flight
attempts), an interrupted migration, a truncated or replaced live chain, and a restart after restore coming up
DISARMED."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from collections import namedtuple
from datetime import timedelta
from pathlib import Path

import pytest

import test_journal_fixtures as f
import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import journal_backup as jb
from edge_lab.execution.journal import AttemptRefused, AttemptState, ExecutionJournal, UnknownSchema
from edge_lab.execution.reservations import ReceiptKind as K

NOW = f.NOW
Usage = namedtuple("Usage", "total used free")


@pytest.fixture
def dirs(tmp_path: Path):
    live_dir, root, drill = tmp_path / "live", tmp_path / "backups", tmp_path / "drill"
    for d in (live_dir, root, drill):
        d.mkdir()
    return live_dir / "kalshi.execution.sqlite3", root, drill


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rich(path: Path) -> ExecutionJournal:
    """A journal with an acknowledged order, a rejected one, a conflicting duplicate receipt and an in-flight one."""
    journal, token = f.ready(path)
    a1 = f.prepare(journal, f.entry("EXP-TEST:ticket-0001", quantity="4", cost="2.00"), token)
    journal.mark_sent(a1.attempt_id, now=NOW)
    f.receipt(journal, "ack-1", K.ORDER_ACK, a1.attempt_id, payload='{"order":{"id":"p-1"}}', provider_id="p-1")
    journal.mark_acknowledged(a1.attempt_id, provider_order_id="p-1", receipt_id="ack-1", now=NOW)
    f.receipt(journal, "ack-1", K.ORDER_ACK, a1.attempt_id, payload='{"order":{"id":"p-1"},"x":1}', provider_id="p-1")
    a2 = f.prepare(journal, f.entry("EXP-TEST:ticket-0002", quantity="2", cost="1.00"), token)
    journal.mark_sent(a2.attempt_id, now=NOW)
    f.receipt(journal, "rej-2", K.ORDER_REJECT, a2.attempt_id, payload='{"error":"insufficient"}')
    journal.mark_rejected(a2.attempt_id, receipt_id="rej-2", now=NOW)
    f.prepare(journal, f.entry("EXP-TEST:ticket-0003", quantity="1", cost="0.50"), token)  # PENDING_EGRESS
    return journal


def _business_view(journal: ExecutionJournal) -> dict:
    """Order-intent and receipt identity through the journal's own API."""
    keys = ("EXP-TEST:ticket-0001", "EXP-TEST:ticket-0002", "EXP-TEST:ticket-0003")
    return {"attempts": [journal.attempts_for(k) for k in keys],
            "receipts": {r: journal.receipts(r) for r in ("ack-1", "rej-2")},
            "chain": journal.verify_chain()}


# ---------------------------------------------------------------- backup and restore preserve identity


def test_backup_then_restore_to_a_new_path_preserves_intent_and_receipt_identity(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    assert sorted(p.name for p in record.bundle.iterdir()) == [jb.DB_NAME, jb.MANIFEST_NAME]
    assert record.bundle.name.startswith(jb.BUNDLE_PREFIX + "20261007T150000Z-")
    target = drill / "restored.execution.sqlite3"
    report = jb.restore_bundle(record.bundle, target, live_paths=[live])
    assert report.identity == jb.store_identity(live) == record.identity
    with ExecutionJournal.open(target) as restored:
        assert _business_view(restored) == _business_view(journal)
        assert restored.verify_chain().ok and restored.verify_chain().events == report.chain_events
    assert record.identity.in_flight_attempts == 1 and record.identity.row_counts["receipts"] == 3
    journal.close()


def test_the_manifest_holds_counts_and_digests_only(dirs):
    live, root, _ = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    text = (record.bundle / jb.MANIFEST_NAME).read_text(encoding="utf-8")
    for value in ("EXP-TEST:ticket-0001", "ack-1", "p-1", "nonce-", "insufficient", "fixture-acct", "worker-a"):
        assert value not in text, value
    assert json.loads(text)["schema"] == jb.BUNDLE_SCHEMA
    journal.close()


def test_a_backup_taken_while_a_writer_commits_is_a_consistent_prefix(dirs):
    live, root, _ = dirs
    journal, token = f.ready(live)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            with ExecutionJournal.open(live, busy_timeout_ms=5000) as w:
                i = 0
                while not stop.is_set():
                    f.receipt(w, f"stream-{i}", K.ORDER_LOOKUP, payload=json.dumps({"i": i}))
                    i += 1
        except BaseException as exc:  # reported below, never swallowed
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        records = [jb.create_backup(live, root, now=NOW + timedelta(seconds=i)) for i in range(3)]
    finally:
        stop.set()
        thread.join(timeout=60)
    assert not errors and not thread.is_alive()
    live_events = dict(sqlite3.connect(live).execute("SELECT seq, row_hash FROM events").fetchall())
    heads = []
    for record in records:
        jb.verify_bundle(record.bundle)
        copy = sqlite3.connect(record.bundle / jb.DB_NAME)
        backup_events = dict(copy.execute("SELECT seq, row_hash FROM events").fetchall())
        copy.close()
        assert all(live_events[seq] == hash_ for seq, hash_ in backup_events.items())  # a prefix of the live chain
        heads.append(record.identity.event_head_seq)
    assert heads == sorted(heads) and max(live_events) >= heads[-1]
    journal.close()


def test_a_write_landing_during_the_backup_is_not_in_that_backup(dirs):
    live, root, _ = dirs
    journal, _ = f.ready(live)
    before = jb.store_identity(live)

    def write_meanwhile(stage: str) -> None:
        if stage == "copied":
            f.receipt(journal, "late", K.ORDER_LOOKUP)

    record = jb.create_backup(live, root, now=NOW, fault=write_meanwhile)
    assert record.identity == before
    assert jb.store_identity(live).row_counts["receipts"] == 1
    jb.verify_bundle(record.bundle)
    journal.close()


def test_a_drill_restores_verifies_and_removes_its_own_copy(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    report = jb.restore_drill(record.bundle, drill, live_paths=[live])
    assert report.removed_after_drill and list(drill.iterdir()) == []
    kept = jb.restore_drill(record.bundle, drill, live_paths=[live], keep=True)
    assert kept.target.is_file() and not kept.removed_after_drill
    journal.close()


# ---------------------------------------------------------------- never over live evidence


def test_a_restore_never_writes_over_the_live_journal_or_any_existing_file(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    journal.close()
    before = _sha(live)
    with pytest.raises(jb.BackupRefused, match="NEVER_OVER_LIVE"):
        jb.restore_bundle(record.bundle, live, live_paths=[live])
    with pytest.raises(jb.BackupRefused, match="TARGET_EXISTS"):
        jb.restore_bundle(record.bundle, live)  # even when the caller forgot to name it live
    side = drill / "x.execution.sqlite3-wal"
    side.write_bytes(b"")
    with pytest.raises(jb.BackupRefused, match="TARGET_EXISTS"):
        jb.restore_bundle(record.bundle, drill / "x.execution.sqlite3")
    with pytest.raises(jb.BackupRefused, match="must end in"):
        jb.restore_bundle(record.bundle, drill / "research.sqlite3")
    assert _sha(live) == before


# ---------------------------------------------------------------- backup failure


@pytest.mark.parametrize("stage", ["copied", "verified", "before_publish"])
def test_a_backup_failing_at_any_stage_leaves_no_bundle_and_keeps_earlier_ones(dirs, stage):
    live, root, _ = dirs
    journal = _rich(live)
    good = jb.create_backup(live, root, now=NOW)

    def disk_full(where: str) -> None:
        if where == stage:
            raise OSError(errno.ENOSPC, "No space left on device")

    live_before = jb.store_identity(live)
    with pytest.raises(jb.BackupFailed, match="No space left"):
        jb.create_backup(live, root, now=NOW + timedelta(hours=1), fault=disk_full)
    assert [p.name for p in root.iterdir()] == [good.bundle.name]  # no partial, no second bundle
    jb.verify_bundle(good.bundle)
    assert jb.store_identity(live) == live_before
    f.receipt(journal, "after-failure", K.ORDER_LOOKUP)  # the live journal is still usable
    assert journal.verify_chain().ok
    journal.close()


def test_backup_refusals_write_nothing(dirs, tmp_path):
    live, root, _ = dirs
    with pytest.raises(jb.BackupRefused, match="no live journal"):
        jb.create_backup(live, root, now=NOW)
    with pytest.raises(jb.BackupRefused, match="must end in"):
        jb.create_backup(tmp_path / "edge_lab.sqlite3", root, now=NOW)
    foreign = live.parent / "foreign.execution.sqlite3"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE snapshots (id INTEGER)")
    conn.commit()
    conn.close()
    before = _sha(foreign)
    with pytest.raises(jb.BackupRefused, match="schema_meta"):
        jb.create_backup(foreign, root, now=NOW)
    assert _sha(foreign) == before
    journal, _ = f.ready(live)
    with pytest.raises(jb.BackupRefused, match="existing directory"):
        jb.create_backup(live, tmp_path / "missing-root", now=NOW)
    for beside in (live.parent, live.parent / "sub", live.parent.parent):
        beside.mkdir(exist_ok=True)
        with pytest.raises(jb.BackupRefused, match="live journal's directory"):
            jb.create_backup(live, beside, now=NOW)
    (live.parent / "sub").rmdir()
    assert list(root.iterdir()) == [] and not (tmp_path / "missing-root").exists()
    journal.close()


def test_a_damaged_bundle_is_refused_by_verify_and_restore(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    db = record.bundle / jb.DB_NAME
    data = bytearray(db.read_bytes())
    data[-100] ^= 0xFF
    db.write_bytes(bytes(data))
    with pytest.raises(jb.BackupFailed, match="BYTES_MISMATCH"):
        jb.verify_bundle(record.bundle)
    with pytest.raises(jb.BackupFailed, match="BYTES_MISMATCH"):
        jb.restore_bundle(record.bundle, drill / "r.execution.sqlite3")
    assert list(drill.iterdir()) == []
    journal.close()


def test_a_manifest_whose_identity_differs_from_the_bytes_is_refused(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    path = record.bundle / jb.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["identity"]["identity"]["receipts"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(jb.BackupFailed, match="IDENTITY_MISMATCH"):
        jb.verify_bundle(record.bundle)
    with pytest.raises(jb.BackupFailed, match="IDENTITY_MISMATCH"):
        jb.restore_bundle(record.bundle, drill / "r.execution.sqlite3")
    assert list(drill.iterdir()) == []
    journal.close()


def test_an_interrupted_backup_leaves_only_a_partial_that_is_never_a_backup(dirs):
    live, root, _ = dirs
    journal, _ = f.ready(live)
    good = jb.create_backup(live, root, now=NOW)
    partial = root / f"{jb.PARTIAL_PREFIX}deadbeef0000"
    partial.mkdir()
    (partial / jb.DB_NAME).write_bytes(b"half a copy")
    unpublished = root / f"{jb.BUNDLE_PREFIX}20991231T000000Z-feedface0000"
    unpublished.mkdir()  # no manifest
    infos = {b.path.name: b.complete for b in jb.list_bundles(root)}
    assert infos == {good.bundle.name: True, partial.name: False, unpublished.name: False}
    assert jb.newest_complete(root).path == good.bundle
    journal.close()


# ---------------------------------------------------------------- disk pressure and resource exhaustion


def test_disk_pressure_refuses_before_writing_anything(dirs):
    live, root, drill = dirs
    journal = _rich(live)
    tight = lambda _path: Usage(10 ** 9, 10 ** 9 - 1024, 1024)  # noqa: E731
    with pytest.raises(jb.BackupRefused, match="DISK_PRESSURE"):
        jb.create_backup(live, root, now=NOW, disk_usage=tight)
    assert list(root.iterdir()) == []
    record = jb.create_backup(live, root, now=NOW)
    with pytest.raises(jb.BackupRefused, match="DISK_PRESSURE"):
        jb.restore_bundle(record.bundle, drill / "r.execution.sqlite3", disk_usage=tight)
    assert list(drill.iterdir()) == []
    journal.close()


def test_the_free_space_bound_covers_the_copy_its_check_and_headroom(dirs):
    live, root, _ = dirs
    journal = _rich(live)
    size = live.stat().st_size + sum(p.stat().st_size for p in live.parent.iterdir() if p.name != live.name)
    need = size * 3 + 64 * 1024 * 1024  # the copy, its verification copy, as much again, and 64 MiB
    with pytest.raises(jb.BackupRefused, match="DISK_PRESSURE"):
        jb.create_backup(live, root, now=NOW, disk_usage=lambda _p: Usage(0, 0, need - 1))
    assert jb.create_backup(live, root, now=NOW, disk_usage=lambda _p: Usage(0, 0, need)).bundle.is_dir()
    journal.close()


def test_an_exhausted_time_budget_publishes_nothing(dirs):
    live, root, _ = dirs
    journal = _rich(live)
    ticks = iter([0.0, 1.0, 10_000.0, 10_000.0, 10_000.0])
    with pytest.raises(jb.BackupFailed, match="TIME_BUDGET_EXHAUSTED"):
        jb.create_backup(live, root, now=NOW, timeout_s=60, monotonic=lambda: next(ticks))
    assert list(root.iterdir()) == []
    with pytest.raises(ValueError):
        jb.create_backup(live, root, now=NOW, timeout_s=0)
    journal.close()


# ---------------------------------------------------------------- obsolete state


def test_an_old_backup_restored_turns_its_in_flight_attempt_unknown_and_never_resends_it(dirs):
    live, root, drill = dirs
    journal = _rich(live)  # ticket-0003 is PENDING_EGRESS
    record = jb.create_backup(live, root, now=NOW)
    target = drill / "restored.execution.sqlite3"
    assert jb.restore_bundle(record.bundle, target, live_paths=[live]).identity.in_flight_attempts == 1
    with ExecutionJournal.open(target) as restored:
        later = NOW + f.TTL + timedelta(minutes=1)  # the restored lease is the old worker's until it expires
        restored.reservations.acquire_lease("worker-restored", f.TTL, later)
        (pending,) = restored.attempts_for("EXP-TEST:ticket-0003")
        assert pending.state is AttemptState.OUTCOME_UNKNOWN  # nobody can know whether it was sent
        token = restored.reservations.lease().fence_token
        with pytest.raises(AttemptRefused):
            f.prepare(restored, f.entry("EXP-TEST:ticket-0003", quantity="1", cost="0.50"), token, nonce="again",
                      at=later)
    journal.close()


def test_a_restored_journal_restarts_disarmed_and_cannot_arm_before_reconciling(tmp_path):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    live, root, drill = tmp_path / "live" / "k.execution.sqlite3", tmp_path / "bk", tmp_path / "drill"
    for d in (live.parent, root, drill):
        d.mkdir()
    journal = ExecutionJournal.open(live)
    orch, _ = h.build(journal, adapter)
    assert orch.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    assert orch.state.mode is ctl.Mode.BOUNDED_AUTO
    record = jb.create_backup(live, root, now=clock())  # taken while ARMED
    target = drill / "restored.execution.sqlite3"
    jb.restore_bundle(record.bundle, target, live_paths=[live])
    journal.close()
    clock.advance(600)  # past the old lease
    with ExecutionJournal.open(target) as restored:
        again, _ = h.build(restored, adapter, worker_id="worker-restored")
        assert again.state.mode is ctl.Mode.DISARMED and again.state.armed_grant_digest is None
        assert isinstance(restored.control_events(h.SCOPE)[-1], ctl.Started)
        refused = h.arm(again, ctl.Mode.BOUNDED_AUTO, clock)
        assert isinstance(refused, ctl.ArmRefused) and any("RECONCILIATION_NOT_COMPLETE" in r for r in refused.reasons)
        assert again.state.mode is ctl.Mode.DISARMED


# ---------------------------------------------------------------- interrupted migration and foreign schemas


def _force(path: Path, *statements: str) -> None:
    """What a crashed or half-applied migration could leave: raw SQL around the journal's own triggers."""
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER schema_meta_no_update")
    for s in statements:
        conn.execute(s)
    conn.commit()
    conn.close()


@pytest.mark.parametrize("statements,problem", [
    (("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'",), "STORE_NEWER_THAN_CODE"),
    (("UPDATE schema_meta SET value = '0' WHERE key = 'schema_version'",), "STORE_OLDER_THAN_CODE"),
    (("CREATE TABLE migration_v2_scratch (x TEXT)",), "SCHEMA_OBJECTS_DIFFER"),
])
def test_a_half_applied_migration_is_refused_everywhere_and_the_file_is_kept(dirs, statements, problem):
    live, root, drill = dirs
    journal, _ = f.ready(live)
    good = jb.create_backup(live, root, now=NOW)
    journal.close()
    _force(live, *statements)
    before = _sha(live)
    with pytest.raises(jb.BackupRefused, match=problem):
        jb.create_backup(live, root, now=NOW + timedelta(hours=1))
    with pytest.raises(UnknownSchema):
        ExecutionJournal.open(live)
    assert _sha(live) == before and [p.name for p in root.iterdir()] == [good.bundle.name]
    # The way back is the pre-migration backup, restored to a NEW path; the broken file stays as evidence.
    report = jb.restore_bundle(good.bundle, drill / "pre-migration.execution.sqlite3", live_paths=[live])
    assert report.identity == good.identity


# ---------------------------------------------------------------- the backup as an external chain anchor


def test_the_live_chain_must_extend_the_newest_backup(dirs, tmp_path):
    live, root, _ = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    f.receipt(journal, "later", K.ORDER_LOOKUP)
    assert jb.extends_backup(live, record.bundle) == []
    journal.close()
    shorter = tmp_path / "shorter.execution.sqlite3"
    other, _ = f.ready(shorter)
    other.close()
    assert jb.extends_backup(shorter, record.bundle)[0].startswith("LIVE_CHAIN_SHORTER_THAN_BACKUP")
    replaced = tmp_path / "replaced.execution.sqlite3"
    other, _ = f.ready(replaced)
    for i in range(record.identity.event_head_seq):
        f.receipt(other, f"pad-{i}", K.ORDER_LOOKUP, payload=json.dumps({"pad": i}))
    other.close()
    assert jb.extends_backup(replaced, record.bundle)[0].startswith("LIVE_CHAIN_DIVERGES_FROM_BACKUP")


def test_a_live_journal_with_a_broken_chain_is_never_published_as_a_backup(dirs):
    live, root, _ = dirs
    journal = _rich(live)
    journal.close()
    conn = sqlite3.connect(live)
    conn.execute("DROP TRIGGER receipts_no_update")
    conn.execute("UPDATE receipts SET payload_json = '{\"forged\":true}' WHERE receipt_id = 'rej-2'")
    conn.execute("CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT, "
                 "'receipts is append-only'); END;")
    conn.commit()
    conn.close()
    with pytest.raises(jb.BackupFailed, match="CHAIN_INVALID"):
        jb.create_backup(live, root, now=NOW)
    assert list(root.iterdir()) == []


IDENTITY_TABLES = ("intents", "approvals", "attempts", "receipts", "reservations", "account_snapshots")


def test_identity_covers_every_identifying_table():
    assert tuple(t for t, _ in jb._IDENTITY) == IDENTITY_TABLES


@pytest.mark.parametrize("table", IDENTITY_TABLES)
def test_each_identifying_table_has_its_own_digest(dirs, table):
    live, _, _ = dirs
    journal = _rich(live)
    journal.close()
    before = jb.store_identity(live)
    conn = sqlite3.connect(live)
    cols = dict(jb._IDENTITY)[table]
    conn.executescript(f"DROP TRIGGER IF EXISTS {table}_no_update;")
    conn.execute(f"UPDATE {table} SET {cols[-1]} = ? WHERE rowid = (SELECT MIN(rowid) FROM {table})", ("f" * 64,))
    conn.commit()
    conn.close()
    after = jb.store_identity(live)
    assert after.identity[table] != before.identity[table]
    assert {k: v for k, v in after.identity.items() if k != table} == \
        {k: v for k, v in before.identity.items() if k != table}


def test_a_bundle_swapped_after_verification_is_never_restored(dirs, tmp_path, monkeypatch):
    live, root, drill = dirs
    journal = _rich(live)
    first = jb.create_backup(live, root, now=NOW)
    f.receipt(journal, "later", K.ORDER_LOOKUP)
    second = jb.create_backup(live, root, now=NOW + timedelta(hours=1))
    journal.close()
    real_verify = jb.verify_bundle

    def verify_then_swap(bundle):
        record = real_verify(bundle)
        (first.bundle / jb.DB_NAME).write_bytes((second.bundle / jb.DB_NAME).read_bytes())  # after the check
        return record

    monkeypatch.setattr(jb, "verify_bundle", verify_then_swap)
    with pytest.raises(jb.BackupFailed, match="IDENTITY_MISMATCH"):
        jb.restore_bundle(first.bundle, drill / "r.execution.sqlite3")
    assert list(drill.iterdir()) == []


def test_backup_and_identity_never_write_the_live_file_even_after_a_crash(dirs):
    """A writer killed mid-run leaves its WAL uncheckpointed and no connection open. Reading it read-only must not
    checkpoint that WAL into the main file, which the last read-write connection would do on close."""
    live, root, _ = dirs
    journal, token = f.ready(live)
    journal.close()
    helper = Path(f.__file__)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path(jb.__file__).resolve().parents[2]), str(helper.parent)])}
    done = subprocess.run([sys.executable, str(helper), str(live), "after_sent", str(token)], env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 19, done.stderr
    wal = live.with_name(live.name + "-wal")
    assert wal.is_file() and wal.stat().st_size > 0  # the crash left committed rows only in the WAL
    main_before = _sha(live)
    assert jb.store_identity(live).in_flight_attempts == 1  # the WAL's rows are read
    record = jb.create_backup(live, root, now=NOW)
    assert record.identity.in_flight_attempts == 1
    assert jb.extends_backup(live, record.bundle) == []
    assert _sha(live) == main_before and wal.stat().st_size > 0


def test_a_bundle_altered_after_verification_fails_the_restore_chain_check(dirs, monkeypatch):
    """An event changed inside the bundle after it was verified keeps every identity digest (the head hash is
    stored, not recomputed) but breaks the chain: the restore's own chain check refuses it."""
    live, root, drill = dirs
    journal = _rich(live)
    record = jb.create_backup(live, root, now=NOW)
    journal.close()
    real_verify = jb.verify_bundle

    def verify_then_alter(bundle):
        verified = real_verify(bundle)
        conn = sqlite3.connect(Path(bundle) / jb.DB_NAME)
        conn.execute("DROP TRIGGER events_no_update")
        conn.execute("UPDATE events SET at_utc = '2020-01-01T00:00:00+00:00' WHERE seq = 2")
        conn.execute("CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, "
                     "'events is append-only'); END;")
        conn.commit()
        conn.close()
        return verified

    monkeypatch.setattr(jb, "verify_bundle", verify_then_alter)
    with pytest.raises(jb.BackupFailed, match="CHAIN_INVALID"):
        jb.restore_bundle(record.bundle, drill / "r.execution.sqlite3")
    assert list(drill.iterdir()) == []
