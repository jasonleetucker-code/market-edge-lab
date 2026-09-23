"""Verified backups of the shadow ledger (both stores are backed up; the ledger is not evidence-derived-only)."""

import json
import sqlite3
from decimal import Decimal

import pytest

from edge_lab import backup
from edge_lab.shadow_ledger import ShadowLedger

ACCT = dict(starting_bankroll=Decimal("100"), strategy="t", opened_at_utc="2026-09-23T00:00:00+00:00",
            sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="x")


def _ledger(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    lg = ShadowLedger(path)
    lg.open_account("A", **ACCT)
    lg.record_decision("A", {"decision_id": "d1", "opportunity_id": "o1", "as_of_utc": "2026-09-23T22:00:00+00:00",
                             "qualification": "REJECT", "reason": "EDGE_BELOW_THRESHOLD"})
    return path, lg


def test_ledger_backup_verifies_triggers_and_hash_chain(tmp_path):
    path, lg = _ledger(tmp_path)
    bundle = backup.create_backup(path, tmp_path / "backups", kind="ledger")
    report = backup.verify_backup(bundle)
    assert report["status"] == "VERIFIED_BACKUP_AND_RESTORE" and report["store_kind"] == "ledger"
    assert report["row_counts"] == {"ledger_entries": 2}
    assert report["chain_heads"] == {"A": lg.verify_chain("A")}
    assert json.loads((bundle / "manifest.json").read_text())["store_kind"] == "ledger"
    restored = ShadowLedger.open_readonly(bundle / "database.sqlite3")
    assert restored.state("A").decisions == 1


def test_ledger_without_triggers_or_with_a_broken_chain_is_never_verified(tmp_path):
    path, _ = _ledger(tmp_path)
    conn = sqlite3.connect(path)
    trigger = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' LIMIT 1").fetchone()[0]
    conn.execute(f'DROP TRIGGER "{trigger}"')
    conn.commit()
    conn.close()
    # Copied as forensic evidence, never VERIFIED.
    report = backup.verify_backup(backup.create_backup(path, tmp_path / "b1", kind="ledger"))
    assert report["status"] == "BACKED_UP_LEDGER_TAMPERED_TRIGGERS" and trigger in report["missing_triggers"]

    path2, _ = _ledger(tmp_path / "x")
    conn = sqlite3.connect(path2)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        conn.execute(f'DROP TRIGGER "{name}"')
    conn.execute("UPDATE ledger_entries SET payload_json = replace(payload_json, 'REJECT', 'QUALIFY') WHERE seq = 2")
    conn.commit()
    conn.close()
    report = backup.verify_backup(backup.create_backup(path2, tmp_path / "b2", kind="ledger"))
    assert report["status"] == "BACKED_UP_LEDGER_TAMPERED_TRIGGERS" and report["chain_heads"]["A"].startswith("REPLAY_FAILED")


def test_a_ledger_with_a_broken_chain_is_still_copied_but_never_verified(tmp_path, capsys):
    path, _ = _ledger(tmp_path)
    conn = sqlite3.connect(path)
    triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'").fetchall()
    for name, _ in triggers:
        conn.execute(f'DROP TRIGGER "{name}"')
    conn.execute("UPDATE ledger_entries SET payload_json = replace(payload_json, 'REJECT', 'QUALIFY') WHERE seq = 2")
    for _, sql in triggers:
        conn.execute(sql)  # triggers restored, chain still broken
    conn.commit()
    conn.close()
    assert backup.main(["create", "--db", str(path), "--out", str(tmp_path / "bk"), "--kind", "ledger"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BACKED_UP_LEDGER_CHAIN_INVALID"
    assert report["chain_heads"]["A"].startswith("REPLAY_FAILED") and (tmp_path / "bk").exists()


def test_cli_backs_up_both_stores_and_skips_a_ledger_not_created_yet(tmp_path, capsys):
    path, _ = _ledger(tmp_path)
    lock = tmp_path / "ledger.sqlite3.lock"
    assert backup.main(["create", "--db", str(path), "--out", str(tmp_path / "bk"), "--kind", "ledger",
                        "--lock-file", str(lock)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_BACKUP_AND_RESTORE"
    missing = tmp_path / "none.sqlite3"
    assert backup.main(["create", "--db", str(missing), "--out", str(tmp_path / "bk"), "--kind", "ledger",
                        "--if-exists"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED_NO_SOURCE" and not missing.exists()
    # Without --if-exists a missing source is a failure, never an empty backup.
    assert backup.main(["create", "--db", str(missing), "--out", str(tmp_path / "bk2"), "--kind", "ledger"]) == 1


def test_evidence_db_is_not_accepted_as_a_ledger(tmp_path):
    from edge_lab.storage import SnapshotStore

    SnapshotStore(tmp_path / "e.sqlite3")
    with pytest.raises(backup.BackupError, match="not a Market Edge shadow ledger"):
        backup.create_backup(tmp_path / "e.sqlite3", tmp_path / "b", kind="ledger")
