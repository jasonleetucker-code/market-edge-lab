"""GATE7-F09 support: ledger head checkpoints (`edge_lab.ledger_anchor`, ADR 0021).

Every ledger is a disposable tmp_path file. Tampering is simulated the way the Gate 7 suite
does it: raw sqlite3, dropping the append-only triggers first, then (like a careful attacker)
restoring them by reopening the ledger for writing, so `verify_chain` passes afterwards.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import cli
from edge_lab.ledger_anchor import (
    CHECKPOINT_SCHEMA, STATUS_ORDER, checkpoint_problems, export_checkpoint, verify_checkpoint,
)
from edge_lab.shadow_ledger import LedgerError, ShadowLedger, _entry_hash, _sha, canonical

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 24, 1, 0, tzinfo=UTC)


def decide(lg: ShadowLedger, account: str, i: int) -> None:
    lg.record_decision(account, {"decision_id": f"{account}-d{i}", "opportunity_id": f"{account}-o{i}",
                                 "as_of_utc": (T0 + timedelta(minutes=i)).isoformat(),
                                 "qualification": "REJECT", "reason": "NO_EDGE"})


def open_account(lg: ShadowLedger, account: str) -> None:
    lg.open_account(account, starting_bankroll=Decimal("100.00"), strategy="anchor-test",
                    opened_at_utc=T0.isoformat(), sizing_policy_id="s", fill_policy_id="f",
                    fee_schedule_id="kalshi-quadratic-taker-v1")


def build(path, accounts=("A", "B"), decisions=3) -> ShadowLedger:
    lg = ShadowLedger(path)
    for account in accounts:
        open_account(lg, account)
        for i in range(decisions):
            decide(lg, account, i)
    return lg


def raw(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def tamper(path, *statements) -> None:
    """Drop the triggers, run the statements, then restore the triggers as an attacker would."""
    with closing(raw(path)) as conn:
        conn.execute("DROP TRIGGER ledger_entries_no_update")
        conn.execute("DROP TRIGGER ledger_entries_no_delete")
        for sql, params in statements:
            conn.execute(sql, params)
    ShadowLedger(path)  # reopening for write re-creates the triggers


def file_sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def anchored(tmp_path):
    path = tmp_path / "shadow_ledger.sqlite3"
    build(path)
    checkpoint = export_checkpoint(ShadowLedger.open_readonly(path), now=NOW)
    return path, checkpoint


def verdict(path, checkpoint):
    return verify_checkpoint(ShadowLedger.open_readonly(path), checkpoint)


def status_of(v, account):
    return next(a.status for a in v.accounts if a.account_id == account)


# --------------------------------------------------------------------------- export


def test_checkpoint_records_every_account_head(anchored):
    path, cp = anchored
    assert cp["schema"] == CHECKPOINT_SCHEMA and cp["ledger_file"] == "shadow_ledger.sqlite3"
    assert cp["created_at_utc"] == NOW.isoformat() and cp["ledger_schema_version"] == 1
    assert str(path.parent) not in json.dumps(cp), "the checkpoint names the file, not the full path"
    lg = ShadowLedger.open_readonly(path)
    for account in ("A", "B"):
        rows = lg.entries(account)
        assert cp["accounts"][account] == {
            "entries": 4, "head_seq": rows[-1]["seq"], "head_entry_hash": lg.verify_chain(account),
            "head_effective_at_utc": rows[-1]["effective_at_utc"]}
    assert checkpoint_problems(cp) == []


def test_checkpoint_digest_ignores_formatting(anchored):
    path, cp = anchored
    reparsed = json.loads(json.dumps(cp, indent=2, sort_keys=True))
    assert verdict(path, reparsed).status == "VERIFIED"


def test_export_refuses_naive_time_empty_ledger_and_broken_chain(tmp_path, anchored):
    path, _ = anchored
    with pytest.raises(ValueError, match="timezone"):
        export_checkpoint(ShadowLedger.open_readonly(path), now=NOW.replace(tzinfo=None))
    ShadowLedger(tmp_path / "empty.sqlite3")
    with pytest.raises(LedgerError, match="nothing to anchor"):
        export_checkpoint(ShadowLedger.open_readonly(tmp_path / "empty.sqlite3"), now=NOW)
    with closing(raw(path)) as conn:
        conn.execute("DROP TRIGGER ledger_entries_no_delete")
    with pytest.raises(LedgerError, match="refusing to anchor"):
        export_checkpoint(ShadowLedger.open_readonly(path), now=NOW)


# --------------------------------------------------------------------------- verify


def test_round_trip_is_verified(anchored):
    path, cp = anchored
    v = verdict(path, cp)
    assert v.status == "VERIFIED" and v.ok and v.new_accounts == ()
    assert [a.status for a in v.accounts] == ["VERIFIED", "VERIFIED"]
    d = v.to_dict()
    assert d["status"] == "VERIFIED" and d["checkpoint_sha256"] == cp["checkpoint_sha256"]
    assert any("independent evidence only if" in n for n in d["notes"])


def test_append_after_checkpoint_is_extended(anchored):
    path, cp = anchored
    decide(ShadowLedger(path), "A", 99)
    v = verdict(path, cp)
    assert v.status == "EXTENDED" and v.ok
    assert status_of(v, "A") == "EXTENDED" and status_of(v, "B") == "VERIFIED"
    a = next(x for x in v.accounts if x.account_id == "A")
    assert (a.checkpoint_entries, a.current_entries) == (4, 5)


def test_new_account_is_reported_not_a_failure(anchored):
    path, cp = anchored
    open_account(ShadowLedger(path), "C")
    v = verdict(path, cp)
    assert v.status == "VERIFIED" and v.new_accounts == ("C",)


def test_head_truncation_passes_the_chain_but_not_the_checkpoint(anchored):
    """The F09 scenario: the newest entry is removed, the triggers restored, and the shorter
    chain still verifies. Only the checkpoint exposes it."""
    path, cp = anchored
    with closing(raw(path)) as conn:
        last = conn.execute("SELECT max(seq) FROM ledger_entries WHERE account_id = 'A'").fetchone()[0]
    tamper(path, ("DELETE FROM ledger_entries WHERE seq = ?", (last,)))
    lg = ShadowLedger.open_readonly(path)
    lg.verify_chain("A")  # the hash chain alone sees nothing wrong
    v = verify_checkpoint(lg, cp)
    assert v.status == "TRUNCATED" and not v.ok
    assert status_of(v, "A") == "TRUNCATED" and status_of(v, "B") == "VERIFIED"
    a = next(x for x in v.accounts if x.account_id == "A")
    assert (a.checkpoint_entries, a.current_entries) == (4, 3) and "1 entry missing" in a.detail


def test_consistent_rewrite_of_the_newest_entry_is_rewritten(anchored):
    path, cp = anchored
    with closing(raw(path)) as conn:
        row = conn.execute("SELECT * FROM ledger_entries WHERE account_id = 'A' ORDER BY seq DESC LIMIT 1").fetchone()
    payload = json.loads(row["payload_json"])
    payload["reason"] = "FORGED"
    text = canonical(payload)
    new_hash = _entry_hash(row["prev_hash"], row["account_id"], row["kind"], row["entry_key"],
                           row["effective_at_utc"], _sha(text))
    tamper(path, ("UPDATE ledger_entries SET payload_json = ?, payload_sha256 = ?, entry_hash = ? WHERE seq = ?",
                  (text, _sha(text), new_hash, row["seq"])))
    lg = ShadowLedger.open_readonly(path)
    lg.verify_chain("A")  # consistent: the chain replays
    v = verify_checkpoint(lg, cp)
    assert v.status == "REWRITTEN" and status_of(v, "A") == "REWRITTEN"


def test_truncate_then_append_to_the_old_length_is_rewritten(anchored):
    path, cp = anchored
    with closing(raw(path)) as conn:
        last = conn.execute("SELECT max(seq) FROM ledger_entries WHERE account_id = 'B'").fetchone()[0]
    tamper(path, ("DELETE FROM ledger_entries WHERE seq = ?", (last,)))
    decide(ShadowLedger(path), "B", 77)
    v = verdict(path, cp)
    assert v.status == "REWRITTEN" and status_of(v, "B") == "REWRITTEN"


def test_missing_account(anchored):
    path, cp = anchored
    tamper(path, ("DELETE FROM ledger_entries WHERE account_id = ?", ("B",)))
    v = verdict(path, cp)
    assert v.status == "ACCOUNT_MISSING" and status_of(v, "B") == "ACCOUNT_MISSING"
    assert status_of(v, "A") == "VERIFIED"


def test_broken_chain_is_chain_invalid(anchored):
    path, cp = anchored
    tamper(path, ("UPDATE ledger_entries SET payload_json = replace(payload_json, 'NO_EDGE', 'EDGE!') "
                  "WHERE account_id = 'A' AND entry_key = 'A-d0'", ()))
    v = verdict(path, cp)
    assert v.status == "CHAIN_INVALID" and status_of(v, "A") == "CHAIN_INVALID"


def test_dropped_triggers_are_chain_invalid(anchored):
    path, cp = anchored
    with closing(raw(path)) as conn:
        conn.execute("DROP TRIGGER ledger_entries_no_update")
    v = verdict(path, cp)
    assert v.status == "CHAIN_INVALID" and any("triggers missing" in p for p in v.problems)


@pytest.mark.parametrize("mutate", [
    lambda cp: cp["accounts"]["A"].__setitem__("entries", 3),  # edited without re-digesting
    lambda cp: cp.__setitem__("schema", "edge-lab-ledger-checkpoint/0"),
    lambda cp: cp.__setitem__("checkpoint_sha256", "0" * 64),
    lambda cp: cp.pop("checkpoint_sha256"),
    lambda cp: cp.__setitem__("ledger_schema_version", 2),
])
def test_tampered_checkpoint_is_invalid(anchored, mutate):
    path, cp = anchored
    mutate(cp)
    v = verdict(path, cp)
    assert v.status == "INVALID_CHECKPOINT" and not v.ok and v.problems and v.accounts == ()


def test_malformed_checkpoint_with_a_matching_digest_is_still_invalid(anchored):
    """The digest is not a signature: anyone can recompute it, so shape is checked separately."""
    from edge_lab.ledger_anchor import _digest

    path, cp = anchored
    cp["accounts"]["A"]["entries"] = 0
    cp["checkpoint_sha256"] = _digest(cp)
    assert verdict(path, cp).status == "INVALID_CHECKPOINT"
    for bad in (None, [], "text", {}):
        assert verify_checkpoint(ShadowLedger.open_readonly(path), bad).status == "INVALID_CHECKPOINT"


def test_worst_status_wins():
    assert STATUS_ORDER[0] == "VERIFIED" and STATUS_ORDER[-1] == "INVALID_CHECKPOINT"
    assert STATUS_ORDER.index("TRUNCATED") < STATUS_ORDER.index("REWRITTEN") < STATUS_ORDER.index("CHAIN_INVALID")


def test_truncation_in_one_account_and_rewrite_in_another_reports_the_worst(anchored):
    path, cp = anchored
    with closing(raw(path)) as conn:
        last_a = conn.execute("SELECT max(seq) FROM ledger_entries WHERE account_id = 'A'").fetchone()[0]
        last_b = conn.execute("SELECT max(seq) FROM ledger_entries WHERE account_id = 'B'").fetchone()[0]
    tamper(path, ("DELETE FROM ledger_entries WHERE seq IN (?, ?)", (last_a, last_b)))
    decide(ShadowLedger(path), "B", 55)
    v = verdict(path, cp)
    assert (status_of(v, "A"), status_of(v, "B"), v.status) == ("TRUNCATED", "REWRITTEN", "REWRITTEN")


def test_export_and_verify_never_change_the_ledger_file(anchored):
    path, cp = anchored
    before = file_sha(path)
    for _ in range(2):
        lg = ShadowLedger.open_readonly(path)
        export_checkpoint(lg, now=NOW)
        verify_checkpoint(lg, cp)
    assert file_sha(path) == before


def test_verify_against_a_backup_copy(anchored, tmp_path):
    """A checkpoint also checks a backup: the file name is informational, not a failure."""
    path, cp = anchored
    copy = tmp_path / "backup-copy.sqlite3"
    shutil.copyfile(path, copy)
    v = verdict(copy, cp)
    assert v.status == "VERIFIED" and v.ledger_file == "backup-copy.sqlite3"
    assert v.checkpoint_ledger_file == "shadow_ledger.sqlite3"


# --------------------------------------------------------------------------- CLI


def run(capsys, *argv):
    code = cli.main(["shadow", "anchor", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_export_then_verify(tmp_path, capsys):
    path = tmp_path / "l.sqlite3"
    build(path)
    code, out, _ = run(capsys, "export", "--ledger", str(path))
    assert code == 0
    cp = json.loads(out)
    assert cp["schema"] == CHECKPOINT_SCHEMA and checkpoint_problems(cp) == []
    cp_file = tmp_path / "cp.json"
    cp_file.write_text(out, encoding="utf-8")
    code, out, _ = run(capsys, "verify", "--ledger", str(path), "--checkpoint", str(cp_file))
    assert code == 0 and json.loads(out)["status"] == "VERIFIED"
    decide(ShadowLedger(path), "A", 50)
    code, out, _ = run(capsys, "verify", "--ledger", str(path), "--checkpoint", str(cp_file))
    assert code == 0 and json.loads(out)["status"] == "EXTENDED"


def test_cli_verify_mismatch_exits_2(anchored, tmp_path, capsys):
    path, cp = anchored
    cp_file = tmp_path / "cp.json"
    cp_file.write_text(json.dumps(cp), encoding="utf-8")
    with closing(raw(path)) as conn:
        last = conn.execute("SELECT max(seq) FROM ledger_entries").fetchone()[0]
    tamper(path, ("DELETE FROM ledger_entries WHERE seq = ?", (last,)))
    code, out, _ = run(capsys, "verify", "--ledger", str(path), "--checkpoint", str(cp_file))
    assert code == 2 and json.loads(out)["status"] == "TRUNCATED"


def test_cli_invalid_or_missing_checkpoint_exits_2(anchored, tmp_path, capsys):
    path, _ = anchored
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")
    code, out, _ = run(capsys, "verify", "--ledger", str(path), "--checkpoint", str(garbage))
    assert code == 2 and json.loads(out)["status"] == "INVALID_CHECKPOINT"
    code, _, err = run(capsys, "verify", "--ledger", str(path), "--checkpoint", str(tmp_path / "absent.json"))
    assert code == 2 and "cannot read checkpoint" in err


def test_cli_unreadable_ledger_exits_3(anchored, tmp_path, capsys):
    _, cp = anchored
    cp_file = tmp_path / "cp.json"
    cp_file.write_text(json.dumps(cp), encoding="utf-8")
    not_db = tmp_path / "not-a-db.sqlite3"
    not_db.write_bytes(b"this is not a sqlite database" * 100)
    for ledger in (tmp_path / "absent.sqlite3", not_db):
        assert run(capsys, "export", "--ledger", str(ledger))[0] == 3
        assert run(capsys, "verify", "--ledger", str(ledger), "--checkpoint", str(cp_file))[0] == 3
    assert not (tmp_path / "absent.sqlite3").exists(), "a read-only command must not create the ledger"


def test_cli_export_refusals_exit_2(tmp_path, capsys):
    ShadowLedger(tmp_path / "empty.sqlite3")
    code, out, err = run(capsys, "export", "--ledger", str(tmp_path / "empty.sqlite3"))
    assert code == 2 and out == "" and "nothing to anchor" in err
