"""The manual, reviewed retention apply step (owner approval 2026-09-26, policy proposed-v1) and the O1
off-host helpers. The apply deletes exactly the DELETE-CANDIDATE bundles of a fresh, reviewed, confirmed
dry-run report, after restore-verifying every bundle those deletions rely on, and otherwise nothing.

The newest bundle is a real backup of a real store, so the restore verification is real. The older history
reuses its manifest with synthetic database bytes (the planner reads manifests and sizes; only the bundles
relied on are restored)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import backup
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
NOW = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)
POLICY = backup.RETENTION_POLICIES["proposed-v1"]


def _set_times(bundle: Path, completed: datetime) -> dict:
    path = bundle / backup.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(started_at_utc=(completed - timedelta(seconds=1)).isoformat(), completed_at_utc=completed.isoformat())
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _journal(path: Path, root: Path) -> Path:
    """`journalctl -u edgelab-backup.service -o cat`-style text: a VERIFIED report for every bundle present."""
    lines = ["Starting edgelab-backup.service..."]
    for manifest in sorted(root.rglob(backup.MANIFEST_NAME)):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        lines.append(json.dumps({"status": "VERIFIED_BACKUP_AND_RESTORE", "database_sha256": m["database_sha256"],
                                 "bundle": f"/var/lib/market-edge-lab/backups/{manifest.parent.name}"}, indent=2))
    lines.append("Finished edgelab-backup.service.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def site(tmp_path):
    """A live store (outside the backups directory), a backups root with 60 days of daily evidence bundles
    whose newest is a real, restorable backup, and the recorded verification reports."""
    live = tmp_path / "db" / "edge_lab.sqlite3"
    store = SnapshotStore(live)
    store.start_run("r1")
    store.save_snapshot(run_id="r1", source="kalshi", kind="markets", entity_id="E", url="https://x", payload={"a": 1})
    store.finish_run("r1", status="succeeded")
    root = tmp_path / "backups"
    root.mkdir()
    staged = backup.create_backup(live, tmp_path / "staging", kind="evidence")
    real = root / "edge-backup-zz-newest-real"
    shutil.copytree(staged, real)
    template = _set_times(real, NOW - timedelta(hours=1))
    names = []
    for i in range(60):
        name = f"edge-backup-d{i:03d}"
        data = f"synthetic-{i}".encode() * 40
        (root / name).mkdir()
        (root / name / backup.DB_NAME).write_bytes(data)
        completed = NOW - timedelta(days=60 - i, hours=2)
        manifest = {**template, "database_bytes": len(data), "database_sha256": hashlib.sha256(data).hexdigest(),
                    "started_at_utc": (completed - timedelta(seconds=1)).isoformat(),
                    "completed_at_utc": completed.isoformat()}
        (root / name / backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        names.append(name)
    reports = _journal(tmp_path / "backup-reports.txt", root)
    return {"tmp": tmp_path, "live": live, "root": root, "real": real, "names": names, "reports": reports}


def dry_run(site, now=NOW, **kw) -> tuple[Path, str, dict]:
    report = backup.build_plan(site["root"], now=now, policy=POLICY, verify_reports=site["reports"], **kw)
    path = site["tmp"] / f"plan-{now:%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), report


def candidates(report) -> list[str]:
    return sorted(r["name"] for r in report["bundles"] if r["decision"] == "DELETE-CANDIDATE")


def state(path: Path) -> list[tuple]:
    return [(p.as_posix(), p.stat().st_size if p.is_file() else None, p.stat().st_mtime_ns,
             hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(path.rglob("*"))]


def apply(site, path, confirm, now=NOW + timedelta(minutes=5), **kw):
    return backup.retention_apply(site["root"], path, confirm, now=now, **kw)


# --------------------------------------------------------------------------- the happy path


def test_apply_deletes_exactly_the_reviewed_candidates_and_logs_each(site):
    path, digest, report = dry_run(site)
    expected = candidates(report)
    assert expected and "edge-backup-zz-newest-real" not in expected
    assert {r["covered_by"] for r in report["bundles"] if r["decision"] == "DELETE-CANDIDATE"} == {"edge-backup-zz-newest-real"}
    live_before = state(site["live"].parent)
    kept_before = {p.name for p in site["root"].iterdir() if p.name not in expected}
    result = apply(site, path, digest)
    assert result["state"] == "DELETED" and sorted(d["name"] for d in result["deleted"]) == expected
    assert result["restore_verified_now"] == {"edge-backup-zz-newest-real": json.loads(
        (site["real"] / backup.MANIFEST_NAME).read_text())["database_sha256"]}
    remaining = {p.name for p in site["root"].iterdir()}
    assert remaining == kept_before | {backup.APPLY_LOG_NAME}  # exactly the candidates are gone
    assert state(site["live"].parent) == live_before  # the live store is untouched
    log = [json.loads(line) for line in (site["root"] / backup.APPLY_LOG_NAME).read_text().splitlines()]
    assert [e["event"] for e in log] == ["apply_start"] + ["deleted"] * len(expected) + ["apply_end"]
    assert log[0]["report_sha256"] == digest and [c["name"] for c in log[0]["candidates"]] == expected
    for entry in log[1:-1]:
        assert entry["database_sha256"] and entry["database_bytes"] and entry["reason"].startswith("SUPERSEDED")
    # The next dry run after the apply has nothing more to delete, and re-applying an old report refuses.
    assert candidates(dry_run(site, now=NOW + timedelta(minutes=6))[2]) == []
    with pytest.raises(backup.ApplyRefused, match="CANDIDATES_CHANGED"):
        apply(site, path, digest)


def test_the_log_is_append_only_across_applies(site):
    path, digest, _ = dry_run(site)
    apply(site, path, digest)
    first = (site["root"] / backup.APPLY_LOG_NAME).read_text()
    path2, digest2, _ = dry_run(site, now=NOW + timedelta(minutes=10))
    assert apply(site, path2, digest2, now=NOW + timedelta(minutes=12))["state"] == "NOTHING_TO_DELETE"
    second = (site["root"] / backup.APPLY_LOG_NAME).read_text()
    assert second.startswith(first) and json.loads(second.splitlines()[-1])["event"] == "apply_nothing"


# --------------------------------------------------------------------------- refusals (nothing deleted)


def assert_refused(site, match, fn):
    before = state(site["root"])
    with pytest.raises(backup.ApplyRefused, match=match):
        fn()
    assert state(site["root"]) == before


def test_a_wrong_confirmation_refuses(site):
    path, digest, _ = dry_run(site)
    assert_refused(site, "CONFIRM_MISMATCH", lambda: apply(site, path, "0" * 64))
    assert_refused(site, "CONFIRM_MISMATCH", lambda: apply(site, path, digest.upper()))


def test_a_stale_or_future_report_refuses(site):
    path, digest, _ = dry_run(site)
    assert_refused(site, "STALE_REPORT", lambda: apply(site, path, digest, now=NOW + timedelta(minutes=31)))
    assert_refused(site, "STALE_REPORT", lambda: apply(site, path, digest, now=NOW - timedelta(minutes=5)))


def test_a_changed_candidate_set_refuses(site):
    path, digest, report = dry_run(site)
    victim = candidates(report)[0]
    manifest_path = site["root"] / victim / backup.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["row_counts"] = {k: 10**9 for k in manifest["row_counts"]}  # now nothing covers it: not a candidate
    manifest_path.write_text(json.dumps(manifest))
    assert_refused(site, "CANDIDATES_CHANGED", lambda: apply(site, path, digest))


def test_changed_inputs_refuse(site):
    path, digest, _ = dry_run(site)
    site["reports"].write_text(site["reports"].read_text() + "\n{\"status\": \"FAILED\"}\n")
    assert_refused(site, "INPUTS_CHANGED", lambda: apply(site, path, digest))


def test_a_report_without_recorded_verifications_refuses(site):
    report = backup.build_plan(site["root"], now=NOW, policy=POLICY)
    path = site["tmp"] / "plan-unverified.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert_refused(site, "INPUTS_CHANGED", lambda: apply(site, path, digest))


def test_a_failed_restore_verification_of_the_covering_bundle_refuses(site):
    path, digest, _ = dry_run(site)
    db = site["real"] / backup.DB_NAME
    data = bytearray(db.read_bytes())
    data[-1] ^= 0xFF  # same length: only a real verification notices
    db.write_bytes(bytes(data))
    assert_refused(site, "RELIED_BUNDLE_NOT_VERIFIED", lambda: apply(site, path, digest))


def _tampered(site, monkeypatch, mutate):
    """The reviewed report and the re-run plan agree, but a candidate row is one the apply must never delete."""
    path, _, report = dry_run(site)
    fresh = copy.deepcopy(report)
    mutate(fresh)
    path.write_text(json.dumps(fresh, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(backup, "build_plan", lambda *a, **k: copy.deepcopy(fresh))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _first_candidate(report):
    return next(r for r in report["bundles"] if r["decision"] == "DELETE-CANDIDATE")


@pytest.mark.parametrize("mutate, match", [
    (lambda r: _first_candidate(r).update(kind="ledger"), "PROTECTED"),
    (lambda r: _first_candidate(r).update(path="ledger/" + _first_candidate(r)["name"]), "PROTECTED"),
    (lambda r: _first_candidate(r)["reasons"].append("CHECKPOINT_EVIDENCE_BRACKET: F09 checkpoint x.json"), "PROTECTED"),
    (lambda r: _first_candidate(r)["reasons"].append("SCHEMA_BOUNDARY: the first bundle at schema v8"), "PROTECTED"),
    (lambda r: _first_candidate(r).update(reasons=["UNVERIFIED_RESTORE: no recorded report"]), "PROTECTED"),
    (lambda r: _first_candidate(r).update(reasons=["ACTIVE_OR_IN_PROGRESS: no manifest yet"]), "PROTECTED"),
    (lambda r: r["checkpoints"].append({"checkpoint": "x.json", "kind": "evidence", "match": "EVIDENCE_BRACKET",
                                        "bundles": [_first_candidate(r)["name"]]}), "PROTECTED"),
    (lambda r: r["inputs"].update(pins=[_first_candidate(r)["name"]]), "PROTECTED"),
    (lambda r: _first_candidate(r).update(covered_by=None), "PROTECTED"),
    (lambda r: r["flags"].append("NEWEST_GOOD_STALE:evidence"), "STALE_FREEZE"),
])
def test_a_protected_class_or_the_stale_freeze_refuses(site, monkeypatch, mutate, match):
    path, digest = _tampered(site, monkeypatch, mutate)
    assert_refused(site, match, lambda: apply(site, path, digest))


def test_a_root_that_is_not_a_backups_directory_refuses(site):
    path, digest, _ = dry_run(site)
    (site["root"] / "edge_lab.sqlite3").write_bytes(b"a live store must never be here")
    assert_refused(site, "NOT_A_BACKUPS_DIRECTORY", lambda: apply(site, path, digest))


def test_a_report_for_another_root_refuses(site, tmp_path):
    path, digest, _ = dry_run(site)
    other = tmp_path / "elsewhere"
    shutil.copytree(site["root"], other)
    before = state(other)
    with pytest.raises(backup.ApplyRefused, match="ROOT_MISMATCH"):
        backup.retention_apply(other, path, digest, now=NOW + timedelta(minutes=5))
    assert state(other) == before


def test_the_cli_refuses_with_exit_2_and_deletes_nothing(site, capsys):
    path, _, _ = dry_run(site)
    before = state(site["root"])
    code = backup.main(["retention-apply", "--root", str(site["root"]), "--report", str(path), "--confirm", "0" * 64])
    assert code == 2 and json.loads(capsys.readouterr().out)["state"] == "REFUSED"
    assert state(site["root"]) == before


def test_the_planner_never_reaches_the_apply_step():
    from test_backup_retention import _reachable_planner_functions

    reachable = set(_reachable_planner_functions())
    assert "build_plan" in reachable
    assert not {"retention_apply", "_apply_main", "_log", "verify_backup", "offhost_verify"} & reachable


# --------------------------------------------------------------------------- O1 helpers


def test_newest_verified_names_the_newest_restore_verified_bundle_per_store(site):
    ledger_db = site["tmp"] / "ledger" / "shadow_ledger.sqlite3"
    ledger_db.parent.mkdir()
    ShadowLedger(ledger_db)
    staged = backup.create_backup(ledger_db, site["tmp"] / "staging-ledger", kind="ledger")
    shutil.copytree(staged, site["root"] / "ledger" / "edge-backup-ledger-real")
    _set_times(site["root"] / "ledger" / "edge-backup-ledger-real", NOW - timedelta(hours=1))
    reports = _journal(site["tmp"] / "reports-all.txt", site["root"])
    out = backup.newest_verified(site["root"], verify_reports=reports, now=NOW)
    assert out["state"] == "OK"
    assert out["evidence"]["name"] == "edge-backup-zz-newest-real"
    assert out["ledger"]["path"] == "ledger/edge-backup-ledger-real"
    # Without a recorded verification there is nothing to pull.
    empty = site["tmp"] / "none.txt"
    empty.write_text("no reports\n")
    assert backup.newest_verified(site["root"], verify_reports=empty, now=NOW)["state"] == "MISSING_VERIFIED_BUNDLE"


def test_offhost_verify_checks_copied_bundles_locally(site, capsys):
    ledger_db = site["tmp"] / "ledger" / "shadow_ledger.sqlite3"
    ledger_db.parent.mkdir()
    ShadowLedger(ledger_db)
    ledger_bundle = backup.create_backup(ledger_db, site["tmp"] / "staging-ledger", kind="ledger")
    pull = site["tmp"] / "market-edge-offhost" / "2026-09-27"
    shutil.copytree(site["real"], pull / site["real"].name)
    shutil.copytree(ledger_bundle, pull / "ledger" / ledger_bundle.name)
    assert backup.main(["offhost-verify", "--dir", str(pull)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "VERIFIED" and {b["store_kind"] for b in out["bundles"]} == {"evidence", "ledger"}
    # A damaged copy fails; a pull missing the ledger is incomplete.
    db = pull / site["real"].name / backup.DB_NAME
    data = bytearray(db.read_bytes())
    data[-1] ^= 0xFF
    db.write_bytes(bytes(data))
    assert backup.offhost_verify(pull)["state"] == "FAILED"
    only = site["tmp"] / "only-evidence"
    shutil.copytree(site["real"], only / site["real"].name)
    assert backup.offhost_verify(only)["state"] == "INCOMPLETE"
    assert backup.offhost_verify(site["tmp"] / "empty-dir-not-there")["state"] == "FAILED"
