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
import os
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
    # The canonical F09 checkpoint directory (in production the deployed app's committed set). One checkpoint,
    # taken between d010 and d011, so both are F09-linked (the evidence bracket).
    cps = tmp_path / "app" / "docs" / "engineering" / "ledger_checkpoints"
    cps.mkdir(parents=True)
    (cps / "2026-11-10T100000Z.json").write_text(json.dumps({
        "schema": "edge-lab-ledger-checkpoint/1", "created_at_utc": (NOW - timedelta(days=50, hours=1)).isoformat(),
        "accounts": {"acct": {"head_entry_hash": "h", "entries": 1, "head_seq": 1}}}), encoding="utf-8")
    return {"tmp": tmp_path, "live": live, "root": root, "real": real, "names": names, "reports": reports, "cps": cps}


def dry_run(site, now=NOW, **kw) -> tuple[Path, str, dict]:
    kw.setdefault("checkpoints_dir", site["cps"])
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
    kw.setdefault("canonical_checkpoints", site["cps"])
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
    (lambda r: r["inputs"].update(pins=sorted([*POLICY.pins, _first_candidate(r)["name"]])), "PROTECTED"),
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
        backup.retention_apply(other, path, digest, now=NOW + timedelta(minutes=5), canonical_checkpoints=site["cps"])
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


# --------------------------------------------------------------------------- F09 checkpoints and pins (review BLOCKER)


def test_f09_linked_bundles_survive_because_apply_requires_the_canonical_checkpoints(site):
    """The reviewer's repro: a dry run without --checkpoints made d010 a candidate. The apply refuses it."""
    with_cps = dry_run(site)[2]
    rows = {r["name"]: r for r in with_cps["bundles"]}
    assert rows["edge-backup-d010"]["decision"] == "KEEP"
    assert any(x.startswith("CHECKPOINT_EVIDENCE_BRACKET") for x in rows["edge-backup-d010"]["reasons"])
    path, digest, report = dry_run(site, checkpoints_dir=None)
    assert "edge-backup-d010" in candidates(report)  # what an unguarded apply would have deleted
    assert_refused(site, "CHECKPOINTS_NOT_CANONICAL", lambda: apply(site, path, digest))
    assert (site["root"] / "edge-backup-d010").is_dir()


def test_a_non_canonical_or_empty_checkpoint_directory_refuses(site):
    other = site["tmp"] / "other-checkpoints"
    shutil.copytree(site["cps"], other)
    path, digest, _ = dry_run(site, checkpoints_dir=other)  # same files, but not the committed directory
    assert_refused(site, "CHECKPOINTS_NOT_CANONICAL", lambda: apply(site, path, digest))
    empty = site["tmp"] / "empty-cps"
    empty.mkdir()
    path2, digest2, _ = dry_run(site, checkpoints_dir=empty)
    assert_refused(site, "CHECKPOINTS_NOT_CANONICAL",
                   lambda: apply(site, path2, digest2, canonical_checkpoints=empty))


def test_changed_committed_checkpoints_refuse(site):
    path, digest, _ = dry_run(site)
    (site["cps"] / "2026-12-01T000000Z.json").write_text(json.dumps({
        "created_at_utc": "2026-12-01T00:00:00+00:00", "accounts": {"acct": {"head_entry_hash": "h2"}}}))
    assert_refused(site, "INPUTS_CHANGED", lambda: apply(site, path, digest))


def test_the_canonical_checkpoint_directory_is_the_running_codes_committed_set():
    assert backup.CANONICAL_CHECKPOINTS.parts[-3:] == ("docs", "engineering", "ledger_checkpoints")
    assert sorted(backup.CANONICAL_CHECKPOINTS.glob("*.json"))  # this checkout commits the F09 checkpoints


def test_the_policy_pins_are_committed_and_always_applied(site):
    assert set(POLICY.pins) >= {"edge-backup-eqfiomf5", "edge-backup-iu9x5w73", "edge-backup-gci308lm"}
    victim = site["names"][20]
    pinned = site["root"] / "edge-backup-iu9x5w73"
    (site["root"] / victim).rename(pinned)  # a real baseline name in the history
    _journal(site["reports"], site["root"])
    report = dry_run(site)[2]  # no --pin at all
    row = {r["name"]: r for r in report["bundles"]}["edge-backup-iu9x5w73"]
    assert row["decision"] == "KEEP" and any(x.startswith("PINNED_BASELINE") for x in row["reasons"])
    assert "edge-backup-iu9x5w73" in report["policy_pins_found"] and report["pins_not_found"] == []
    assert set(report["inputs"]["pins"]) >= set(POLICY.pins)


def test_a_report_without_the_policy_pins_refuses(site):
    path, _, report = dry_run(site)
    report["inputs"]["pins"] = []
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert_refused(site, "PINS_MISSING", lambda: apply(site, path, digest))


def test_the_report_age_limit_cannot_be_raised_above_30_minutes(site, capsys):
    path, digest, _ = dry_run(site)
    assert_refused(site, "MAX_AGE_INVALID", lambda: apply(site, path, digest, max_age=timedelta(minutes=31)))
    code = backup.main(["retention-apply", "--root", str(site["root"]), "--report", str(path), "--confirm", digest,
                        "--max-report-age-min", "60"])
    assert code == 2 and "MAX_AGE_INVALID" in json.loads(capsys.readouterr().out)["reason"]


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
    marker = json.loads((pull / backup.OFFHOST_MARKER).read_text())
    assert marker["state"] == "VERIFIED" and len(marker["bundles"]) == 2
    # A damaged copy fails, and its pull no longer counts as verified; a pull missing the ledger is incomplete.
    db = pull / site["real"].name / backup.DB_NAME
    data = bytearray(db.read_bytes())
    data[-1] ^= 0xFF
    db.write_bytes(bytes(data))
    assert backup.offhost_verify(pull)["state"] == "FAILED"
    assert not (pull / backup.OFFHOST_MARKER).exists()
    only = site["tmp"] / "only-evidence"
    shutil.copytree(site["real"], only / site["real"].name)
    assert backup.offhost_verify(only)["state"] == "INCOMPLETE" and not (only / backup.OFFHOST_MARKER).exists()
    assert backup.offhost_verify(site["tmp"] / "empty-dir-not-there")["state"] == "FAILED"


def _pull(base: Path, name: str, verified: bool) -> Path:
    d = base / name
    (d / "edge-backup-x").mkdir(parents=True)
    (d / "edge-backup-x" / backup.DB_NAME).write_bytes(b"copy")
    if verified:
        (d / backup.OFFHOST_MARKER).write_text(json.dumps({"state": "VERIFIED", "bundles": [{"bundle": "x"}]}))
    return d


def test_offhost_prune_keeps_the_four_newest_verified_pulls_and_never_counts_a_failed_one(tmp_path, capsys,
                                                                                         monkeypatch):
    reverified = []
    monkeypatch.setattr(backup, "offhost_verify",  # the synthetic pulls hold no restorable bundle
                        lambda p, timeout=120: reverified.append(p.name) or {"state": "VERIFIED"})
    base = tmp_path / "market-edge-offhost"
    for day in ("2026-09-27", "2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25"):
        _pull(base, day, verified=True)
    _pull(base, "2026-11-01", verified=False)  # the newest pull failed verification
    (base / "2026-10-26").mkdir()
    (base / "2026-10-26" / backup.OFFHOST_MARKER).write_text('{"state": "FAILED"}')  # not a VERIFIED marker
    (base / "notes").mkdir()  # not a dated pull: never touched
    listed = backup.offhost_prune(base, keep=4)
    assert listed["kept_verified"] == ["2026-10-25", "2026-10-18", "2026-10-11", "2026-10-04"]
    assert listed["remove"] == ["2026-09-27"] and not listed["applied"]
    assert sorted(listed["not_verified_left_alone"]) == ["2026-10-26", "2026-11-01"]
    assert (base / "2026-09-27").is_dir()  # listing only
    assert reverified == []  # a listing re-verifies nothing
    assert backup.main(["offhost-prune", "--base", str(base), "--keep", "4", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["remove"] == ["2026-09-27"] and out["state"] == "REMOVED"
    assert sorted(reverified) == ["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25"]  # the kept ones, first
    assert sorted(p.name for p in base.iterdir()) == ["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25",
                                                     "2026-10-26", "2026-11-01", "notes"]
    with pytest.raises(ValueError):
        backup.offhost_prune(base, keep=0)


# --------------------------------------------------------------------------- follow-ups (2026-09-26)


def _real_pull(site, base: Path, day: str) -> Path:
    """A pull holding a real evidence bundle and a real ledger bundle, verified (marker written)."""
    ledger_db = site["tmp"] / "ledger-src" / "shadow_ledger.sqlite3"
    if not ledger_db.exists():
        ledger_db.parent.mkdir()
        ShadowLedger(ledger_db)
    ledger_bundle = backup.create_backup(ledger_db, site["tmp"] / f"staging-{day}", kind="ledger")
    pull = base / day
    shutil.copytree(site["real"], pull / site["real"].name)
    shutil.copytree(ledger_bundle, pull / "ledger" / ledger_bundle.name)
    assert backup.offhost_verify(pull)["state"] == "VERIFIED"
    return pull


def test_prune_apply_re_verifies_the_kept_pulls_and_refuses_if_one_is_stale(site, capsys):
    base = site["tmp"] / "market-edge-offhost"
    old = _real_pull(site, base, "2026-09-26")
    new = _real_pull(site, base, "2026-10-03")
    db = new / site["real"].name / backup.DB_NAME  # the marker still says VERIFIED, but the bytes changed
    data = bytearray(db.read_bytes())
    data[-1] ^= 0xFF
    db.write_bytes(bytes(data))
    assert backup.offhost_prune(base, keep=1)["remove"] == ["2026-09-26"]  # the listing trusts the marker
    code = backup.main(["offhost-prune", "--base", str(base), "--keep", "1", "--apply"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["state"] == "REFUSED" and out["reverified"] == {"2026-10-03": "FAILED"}
    assert old.is_dir()  # nothing removed
    assert not (new / backup.OFFHOST_MARKER).exists()  # the stale marker is gone: the pull no longer counts
    # With the damaged pull no longer counted, the older verified one is kept, not removed.
    assert backup.offhost_prune(base, keep=1)["kept_verified"] == ["2026-09-26"]


def test_prune_apply_removes_after_a_successful_re_verification(site):
    base = site["tmp"] / "market-edge-offhost"
    _real_pull(site, base, "2026-09-26")
    _real_pull(site, base, "2026-10-03")
    out = backup.offhost_prune(base, keep=1, apply=True)
    assert out["state"] == "REMOVED" and out["reverified"] == {"2026-10-03": "VERIFIED"}
    assert sorted(p.name for p in base.iterdir()) == ["2026-10-03"]


def test_prune_never_counts_follows_or_removes_links(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "offhost_verify", lambda p, timeout=120: {"state": "VERIFIED"})
    base = tmp_path / "market-edge-offhost"
    target = _pull(tmp_path / "elsewhere", "2026-09-01", verified=True)  # a verified pull outside the base
    for day in ("2026-10-04", "2026-10-11"):
        _pull(base, day, verified=True)
    link = base / "2026-12-31"
    made = False
    if hasattr(os, "name") and os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))  # a Windows junction, not a symlink
        made = True
        assert not link.is_symlink() and backup._is_link(link)
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
            made = True
        except OSError:
            pytest.skip("cannot create a directory link here")
    assert made
    listed = backup.offhost_prune(base, keep=1)
    assert listed["links_ignored"] == ["2026-12-31"] and "2026-12-31" not in listed["kept_verified"]
    assert listed["kept_verified"] == ["2026-10-11"] and listed["remove"] == ["2026-10-04"]
    assert backup.offhost_prune(base, keep=1, apply=True)["state"] == "REMOVED"
    assert link.exists() and (target / backup.OFFHOST_MARKER).is_file()  # the link and its target are untouched


def test_is_link_falls_back_to_the_reparse_point_attribute(tmp_path, monkeypatch):
    d = tmp_path / "d"
    d.mkdir()
    assert backup._is_link(d) is False

    class Stat:
        st_file_attributes = backup._FILE_ATTRIBUTE_REPARSE_POINT
    monkeypatch.delattr(Path, "is_junction", raising=False)  # as on Python < 3.12
    monkeypatch.setattr(backup.os, "lstat", lambda p: Stat())
    assert backup._is_link(d) is True


def _ledger_bundle(site, completed: datetime) -> None:
    template = json.loads((site["real"] / backup.MANIFEST_NAME).read_text())
    d = site["root"] / "ledger" / "edge-backup-ledger-synthetic"
    d.mkdir(parents=True)
    data = b"ledger-bytes" * 10
    (d / backup.DB_NAME).write_bytes(data)
    manifest = {**template, "store_kind": "ledger", "database_bytes": len(data),
                "database_sha256": hashlib.sha256(data).hexdigest(), "row_counts": {"ledger_entries": 2},
                "chain_heads": {"acct": "h"}, "started_at_utc": (completed - timedelta(seconds=1)).isoformat(),
                "completed_at_utc": completed.isoformat()}
    (d / backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def test_apply_refuses_when_f09_is_overdue(site):
    """The newest committed checkpoint is 50 days older than the newest ledger bundle: an F09 is missing."""
    _ledger_bundle(site, NOW - timedelta(hours=2))
    path, digest, _ = dry_run(site)
    assert_refused(site, "F09_OVERDUE", lambda: apply(site, path, digest))
    # After an F09 is taken, committed and deployed (a checkpoint within the cadence), the apply proceeds.
    (site["cps"] / "2026-12-30T000000Z.json").write_text(json.dumps({
        "created_at_utc": (NOW - timedelta(days=1, hours=12)).isoformat(),
        "accounts": {"acct": {"head_entry_hash": "h"}}}), encoding="utf-8")
    path2, digest2, _ = dry_run(site)
    assert apply(site, path2, digest2)["state"] == "DELETED"


def test_the_f09_cadence_is_eight_days():
    assert backup.F09_MAX_GAP == timedelta(days=8)
