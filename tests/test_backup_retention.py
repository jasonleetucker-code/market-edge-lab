"""The backup retention planner is a DRY RUN only (policy proposed-v1, owner-approved 2026-09-26; deletion is the separate retention-apply).

Synthetic bundle directories (a manifest plus database bytes of the stated length); no real
database is needed because the planner reads manifests and sizes only (hashes with --verify-hashes).
The planner must never delete: every deletion API is made to fail while it runs."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import backup

UTC = timezone.utc
NOW = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)
POLICY = backup.RETENTION_POLICIES["proposed-v1"]


def make_bundle(root: Path, name: str, completed: datetime, *, kind: str = "evidence", rows: int = 10,
                schema_version: int = 7, schema_sha: str = "s7", chain_heads: dict | None = None,
                manifest: dict | str | None = "default", db_bytes: bytes | None = None) -> Path:
    directory = (root / "ledger" if kind == "ledger" else root) / name
    directory.mkdir(parents=True)
    data = db_bytes if db_bytes is not None else f"{name}-{rows}".encode() * 8
    (directory / backup.DB_NAME).write_bytes(data)
    if manifest == "default":
        manifest = {"format_version": 1, "database": backup.DB_NAME, "store_kind": kind,
                    "started_at_utc": (completed - timedelta(seconds=1)).isoformat(),
                    "completed_at_utc": completed.isoformat(), "database_bytes": len(data),
                    "database_sha256": hashlib.sha256(data).hexdigest(), "schema_version": schema_version,
                    "schema_sha256": schema_sha,
                    "row_counts": {"ledger_entries": rows} if kind == "ledger" else {"snapshots": rows, "collection_runs": rows}}
        if kind == "ledger":
            manifest["chain_heads"] = chain_heads or {"acct": f"h{rows}"}
    if isinstance(manifest, dict):
        (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    elif isinstance(manifest, str):
        (directory / backup.MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    return directory


def recorded_verifications(root: Path, *, skip: set[str] = frozenset()) -> dict[str, str]:
    """{database_sha256: bundle name} as if every bundle's `backup create` report said VERIFIED_BACKUP_AND_RESTORE."""
    out = {}
    for manifest in sorted(root.rglob(backup.MANIFEST_NAME)):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("database_sha256"), str) and manifest.parent.name not in skip:
            out[data["database_sha256"]] = manifest.parent.name
    return out


def write_journal(path: Path, verified: dict[str, str], failed: dict[str, str] = {}) -> Path:
    """The recorded reports as `journalctl -u edgelab-backup.service -o cat` prints them: pretty-printed JSON
    interleaved with systemd's own lines."""
    chunks = ["Starting edgelab-backup.service - Market Edge Lab: verified SQLite backups..."]
    for sha, name in verified.items():
        chunks.append(json.dumps({"status": "VERIFIED_BACKUP_AND_RESTORE", "database_sha256": sha,
                                  "bundle": f"/var/lib/market-edge-lab/backups/{name}", "row_counts": {"x": 1}},
                                 indent=2, sort_keys=True))
    for sha, name in failed.items():
        chunks.append(json.dumps({"status": "FAILED", "error": "restored schema or row counts differ",
                                  "database_sha256": sha, "bundle": name}, indent=2))
    chunks.append("Finished edgelab-backup.service.")
    path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    return path


def plan(root: Path, now: datetime = NOW, **kw) -> dict:
    verified = kw.pop("verified", None)
    bundles, _ = backup.scan_bundles(root, now=now, policy=POLICY, verify_hashes=kw.pop("verify_hashes", False),
                                     verified=recorded_verifications(root) if verified is None else verified)
    return backup.retention_plan(bundles, now=now, policy=POLICY, **kw)


def snapshot(root: Path) -> list[tuple]:
    """Every path with its size, modification time and content hash."""
    out = []
    for p in sorted(root.rglob("*")):
        st = p.stat()
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        out.append((p.as_posix(), p.is_file(), st.st_size if p.is_file() else None, st.st_mtime_ns, digest))
    return out


def by_name(report: dict) -> dict[str, dict]:
    return {b["name"]: b for b in report["bundles"]}


def daily_history(root: Path, days: int, *, per_day: int = 1, kind: str = "evidence") -> list[str]:
    """One (or more) bundle per day, ending an hour before NOW, rows growing (append-only store)."""
    names = []
    for i in range(days):
        for j in range(per_day):
            at = NOW - timedelta(days=days - 1 - i, hours=1) - timedelta(hours=per_day - 1 - j)
            name = f"edge-backup-d{i:03d}-{j}"
            make_bundle(root, name, at, kind=kind, rows=100 + i * per_day + j)
            names.append(name)
    return names


# --------------------------------------------------------------------------- never deletes


def _reachable_planner_functions():
    """Every module-level function of backup.py reachable (by name) from the retention CLI entry point."""
    import ast

    module = ast.parse(inspect.getsource(backup))
    defs = {n.name: n for n in module.body if isinstance(n, ast.FunctionDef)}
    todo, seen = ["_retention_main"], set()
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        for node in ast.walk(defs[name]):
            if isinstance(node, ast.Name) and node.id in defs:
                todo.append(node.id)
    return {n: defs[n] for n in seen}


def test_the_planner_has_no_deletion_code_path():
    import ast

    reachable = _reachable_planner_functions()
    # The walk really covers the planner, including the helpers it calls.
    assert {"_retention_main", "scan_bundles", "inspect_bundle", "retention_plan", "_covers", "load_checkpoints",
            "load_verify_reports", "_newest_mtime", "file_hash"} <= set(reachable)
    assert not {"create_backup", "verify_backup", "copy_online"} & set(reachable)
    forbidden = {"unlink", "rmtree", "remove", "rmdir", "removedirs", "rename", "renames", "truncate",
                 "write_text", "write_bytes", "chmod", "chown", "move", "copyfile", "copy", "copy2", "mkdir",
                 "makedirs", "touch", "utime", "symlink_to", "hardlink_to", "fsync", "connect", "backup"}
    for fname, fn_def in reachable.items():
        for node in ast.walk(fn_def):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                owner = getattr(getattr(fn, "value", None), "id", None)
                assert name not in forbidden, f"{fname} calls {name}"
                assert not (owner in ("os", "shutil") and name == "replace"), f"{fname} calls os.replace"
                if name == "open":  # only reads
                    modes = [a for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                    modes += [k.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                    assert all(not set(str(m.value)) & set("wax+") for m in modes), f"{fname} opens for writing"
    # retention-plan accepts no apply/delete option (deletion is only the separate retention-apply command).
    for option in ("--apply", "--delete", "--confirm"):
        with pytest.raises(SystemExit):
            backup.main(["retention-plan", "--root", ".", option])


def test_the_cli_changes_nothing_even_when_every_deletion_api_would_work(tmp_path, monkeypatch, capsys):
    root = tmp_path / "backups"
    daily_history(root, 120)
    make_bundle(root, "edge-backup-broken", NOW - timedelta(days=50), manifest="{not json")
    journal = write_journal(tmp_path / "journal.txt", recorded_verifications(root))
    before = snapshot(tmp_path)

    def refuse(*_a, **_k):
        raise AssertionError("the retention planner must never delete")
    for target, name in ((os, "remove"), (os, "unlink"), (os, "rmdir"), (os, "rename"), (os, "replace"),
                         (os, "utime"), (os, "truncate"), (shutil, "rmtree"), (shutil, "move"), (Path, "unlink"),
                         (Path, "rmdir"), (Path, "rename"), (Path, "replace"), (Path, "touch"),
                         (Path, "write_text"), (Path, "write_bytes")):
        monkeypatch.setattr(target, name, refuse)
    code = backup.main(["retention-plan", "--root", str(root), "--now", NOW.isoformat(), "--verify-hashes",
                        "--verify-reports", str(journal)])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "DRY_RUN_ONLY" and report["deletes_performed"] == 0
    assert report["policy"]["status"].startswith("APPROVED 2026-09-26")
    assert report["verify_reports"]["verified_database_sha256s"] == 120
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] > 0  # candidates are reported, never acted on
    assert snapshot(tmp_path) == before  # same paths, sizes, modification times and contents


# --------------------------------------------------------------------------- restore verification


def test_without_recorded_restore_verification_nothing_is_a_candidate(tmp_path, capsys):
    daily_history(tmp_path, 120)
    report = plan(tmp_path, verified={})
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] == 0
    assert "UNVERIFIED_PRESENT:evidence" in report["flags"] and "NO_GOOD_BUNDLE:evidence" in report["flags"]
    assert all(any(r.startswith("UNVERIFIED_RESTORE") for r in b["reasons"]) for b in report["bundles"])
    # The CLI without --verify-reports is the same: a manifest and a size are not a verified restore.
    assert backup.main(["retention-plan", "--root", str(tmp_path), "--now", NOW.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["evidence"]["DELETE-CANDIDATE"] == 0


def test_backups_failing_verification_trip_the_freshness_freeze(tmp_path):
    """The newest bundles exist and have valid manifests, but their restore checks failed: the newest
    restore-verified bundle is 5 days old, so nothing may become a candidate."""
    names = daily_history(tmp_path, 60)
    report = plan(tmp_path, verified=recorded_verifications(tmp_path, skip=set(names[-5:])))
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] == 0
    assert "NEWEST_GOOD_STALE:evidence" in report["flags"]
    rows = by_name(report)
    assert all(rows[n]["decision"] == "KEEP" and any(r.startswith("UNVERIFIED_RESTORE") for r in rows[n]["reasons"])
               for n in names[-5:])
    assert not any(r.startswith("NEWEST_GOOD") for n in names[-5:] for r in rows[n]["reasons"])


def test_a_bundle_that_failed_verification_never_covers_an_older_one(tmp_path):
    names = daily_history(tmp_path, 60)
    # Day 30 held more rows than any later verified bundle; only an UNVERIFIED later bundle would cover it.
    manifest_path = tmp_path / names[30] / backup.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["row_counts"] = {"snapshots": 10**9, "collection_runs": 1}
    manifest_path.write_text(json.dumps(manifest))
    big = make_bundle(tmp_path, "edge-backup-unverified-big", NOW - timedelta(days=10), rows=10**9 + 1)
    verified = recorded_verifications(tmp_path, skip={big.name})
    row = by_name(plan(tmp_path, verified=verified))[names[30]]
    assert row["decision"] == "KEEP" and any(x.startswith("NOT_COVERED") for x in row["reasons"])


def test_recorded_reports_are_read_from_journal_text(tmp_path):
    daily_history(tmp_path / "b", 3)
    all_verified = recorded_verifications(tmp_path / "b")
    shas = sorted(all_verified)
    journal = write_journal(tmp_path / "j.txt", {shas[0]: all_verified[shas[0]], shas[1]: "edge-backup-other"},
                            failed={shas[2]: all_verified[shas[2]]})
    verified, n = backup.load_verify_reports(journal)
    assert n == 3 and set(verified) == {shas[0], shas[1]}
    bundles, _ = backup.scan_bundles(tmp_path / "b", now=NOW, policy=POLICY, verified=verified)
    flags = {b.name: b.restore_verified for b in bundles}
    assert flags[all_verified[shas[0]]] is True
    assert flags[all_verified[shas[1]]] is False  # a named report must name this bundle
    assert flags[all_verified[shas[2]]] is False  # a FAILED report is not a verification


def _info(name, *, rows, version=7, sha="s7", kind="evidence", verified=True, database=backup.DB_NAME):
    return backup.BundleInfo(kind=kind, name=name, path=name, status="GOOD", restore_verified=verified,
                             completed=NOW, database_bytes=1,
                             manifest={"store_kind": kind, "database": database, "schema_version": version,
                                       "schema_sha256": sha, "row_counts": {"snapshots": rows}})


def test_only_a_verified_copy_of_the_same_store_covers():
    old = _info("old", rows=10)
    assert backup._covers(_info("new", rows=11), old)
    assert not backup._covers(_info("new", rows=11, verified=False), old)
    assert not backup._covers(_info("foreign", rows=10**6, sha="other-store"), old)  # same version, other schema
    assert not backup._covers(_info("older-schema", rows=11, version=6, sha="s6"), old)
    assert not backup._covers(_info("ledger", rows=11, kind="ledger"), old)
    assert not backup._covers(_info("other-db", rows=11, database="other.sqlite3"), old)
    assert backup._covers(_info("migrated", rows=11, version=8, sha="s8"), old)  # a later schema of the same store


# --------------------------------------------------------------------------- keep rules


def test_newest_good_bundles_are_always_kept(tmp_path):
    names = daily_history(tmp_path, 10, per_day=4)
    make_bundle(tmp_path, "edge-backup-zz-corrupt-newest", NOW - timedelta(minutes=40), manifest="{")
    report = by_name(plan(tmp_path))
    for name in names[-3:]:
        assert report[name]["decision"] == "KEEP"
        assert any(r.startswith("NEWEST_GOOD") for r in report[name]["reasons"])
    # A corrupt bundle is never "newest good".
    assert report["edge-backup-zz-corrupt-newest"]["decision"] == "QUARANTINE"


def test_weekly_and_monthly_points_are_selected(tmp_path):
    daily_history(tmp_path, 400)
    report = plan(tmp_path)
    rows = by_name(report)
    kept = [r for r in report["bundles"] if r["decision"] == "KEEP"]
    reasons = [x for r in kept for x in r["reasons"]]
    assert sum(x.startswith("DAILY") for x in reasons) == 7
    assert sum(x.startswith("WEEKLY") for x in reasons) == 8
    assert sum(x.startswith("MONTHLY") for x in reasons) == 12
    assert sum(x.startswith("FIRST_BUNDLE_BASELINE") for x in reasons) == 1
    # One kept point per calendar month in the monthly window: the month's newest bundle.
    november = [r for r in report["bundles"] if r["completed_at_utc"].startswith("2026-11")]
    kept_nov = [r for r in november if any(x.startswith("MONTHLY") for x in r["reasons"])]
    assert len(kept_nov) == 1 and kept_nov[0]["completed_at_utc"].startswith("2026-11-30")
    # Something mid-week, a few months back, and not a month-end: a candidate.
    assert rows["edge-backup-d300-0"]["decision"] == "DELETE-CANDIDATE"
    assert any(x.startswith("SUPERSEDED") for x in rows["edge-backup-d300-0"]["reasons"])
    # Bounded: 400 days of daily copies reduce to at most 48 h + 7 + 8 + 12 + first + newest points.
    assert report["summary"]["evidence"]["KEEP"] <= 2 + 7 + 8 + 12 + 1 + 3


def test_everything_younger_than_48_hours_is_kept(tmp_path):
    for i in range(12):  # deploy pairs: before and after each install
        make_bundle(tmp_path, f"edge-backup-deploy-{i:02d}", NOW - timedelta(hours=47) + timedelta(hours=4 * i),
                    rows=100 + i)
    report = plan(tmp_path)
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] == 0


def test_ledger_bundles_are_never_candidates_under_proposed_v1(tmp_path):
    daily_history(tmp_path, 60, kind="ledger")
    report = plan(tmp_path)
    assert report["summary"]["ledger"]["DELETE-CANDIDATE"] == 0
    assert all(any(x.startswith("NOT_ELIGIBLE_KIND") for x in r["reasons"]) for r in report["bundles"])


def test_schema_boundaries_are_kept(tmp_path):
    names = daily_history(tmp_path, 60)
    # Rebuild day 20 onwards at a newer schema.
    for name in names[20:]:
        manifest_path = tmp_path / name / backup.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text())
        manifest.update(schema_version=8, schema_sha256="s8")
        manifest_path.write_text(json.dumps(manifest))
    rows = by_name(plan(tmp_path))
    assert any(x.startswith("SCHEMA_BOUNDARY") for x in rows[names[19]]["reasons"])
    assert any(x.startswith("SCHEMA_BOUNDARY") for x in rows[names[20]]["reasons"])


def test_checkpoint_linked_bundles_are_kept(tmp_path):
    names = daily_history(tmp_path, 90)
    ledger = daily_history(tmp_path, 90, kind="ledger")
    cp_time = NOW - timedelta(days=60, hours=12)
    checkpoint = {"name": "2026-11-01T000000Z.json", "created_at_utc": cp_time,
                  "heads": {"acct": "h129"}}  # ledger bundle d029's head
    report = plan(tmp_path, checkpoints=[checkpoint])
    rows = {(b["kind"], b["name"]): b for b in report["bundles"]}
    exact = rows[("ledger", "edge-backup-d029-0")]
    assert exact["decision"] == "KEEP" and any(x.startswith("CHECKPOINT_EXACT") for x in exact["reasons"])
    bracket = [b for b in report["bundles"] if b["kind"] == "evidence"
               and any(x.startswith("CHECKPOINT_EVIDENCE_BRACKET") for x in b["reasons"])]
    assert len(bracket) == 2 and all(b["decision"] == "KEEP" for b in bracket)
    assert {c["match"] for c in report["checkpoints"]} == {"EXACT", "EVIDENCE_BRACKET"}
    assert names and ledger


def test_pinned_baselines_are_kept_and_unknown_pins_reported(tmp_path):
    names = daily_history(tmp_path, 100)
    report = plan(tmp_path, pins=[names[40], "edge-backup-not-here"])
    assert by_name(report)[names[40]]["decision"] == "KEEP"
    assert report["pins_not_found"] == ["edge-backup-not-here"]


def test_a_bundle_holding_rows_no_newer_kept_bundle_holds_is_kept(tmp_path):
    names = daily_history(tmp_path, 60)
    # Day 30 held more rows than every later bundle (a restore to an older state happened after it).
    manifest_path = tmp_path / names[30] / backup.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["row_counts"] = {"snapshots": 10**9, "collection_runs": 1}
    manifest_path.write_text(json.dumps(manifest))
    row = by_name(plan(tmp_path))[names[30]]
    assert row["decision"] == "KEEP" and any(x.startswith("NOT_COVERED") for x in row["reasons"])


def test_a_stale_newest_good_bundle_blocks_every_candidate(tmp_path):
    daily_history(tmp_path, 60)
    report = plan(tmp_path, now=NOW + timedelta(days=3))
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] == 0
    assert "NEWEST_GOOD_STALE:evidence" in report["flags"] and report["state"] == "REVIEW"


# --------------------------------------------------------------------------- invalid and incomplete bundles


@pytest.mark.parametrize("manifest, problem", [
    ("{not json", "MANIFEST_INVALID"),
    ({"format_version": 2, "database": backup.DB_NAME}, "MANIFEST_INVALID"),
    ({"format_version": 1, "database": backup.DB_NAME, "store_kind": "evidence"}, "MANIFEST_INVALID"),
    ({"format_version": 1, "database": backup.DB_NAME, "store_kind": "ledger",
      "started_at_utc": "2026-10-01T00:00:00+00:00", "completed_at_utc": "2026-10-01T00:00:01+00:00"},
     "KIND_LOCATION_MISMATCH"),
    ({"format_version": 1, "database": backup.DB_NAME, "store_kind": "evidence",
      "started_at_utc": "2026-10-01T00:00:00", "completed_at_utc": "2026-10-01T00:00:01"}, "MANIFEST_INVALID"),
])
def test_invalid_manifests_are_quarantined_never_deleted(tmp_path, manifest, problem):
    daily_history(tmp_path, 30)
    make_bundle(tmp_path, "edge-backup-bad", NOW - timedelta(days=20), manifest=manifest)
    row = by_name(plan(tmp_path))["edge-backup-bad"]
    assert row["decision"] == "QUARANTINE" and any(x.startswith(problem) for x in row["reasons"])


def test_size_and_hash_mismatches_are_quarantined(tmp_path):
    daily_history(tmp_path, 30)
    short = make_bundle(tmp_path, "edge-backup-short", NOW - timedelta(days=20))
    (short / backup.DB_NAME).write_bytes(b"x")
    flipped = make_bundle(tmp_path, "edge-backup-flipped", NOW - timedelta(days=19))
    data = (flipped / backup.DB_NAME).read_bytes()
    (flipped / backup.DB_NAME).write_bytes(bytes([data[0] ^ 1]) + data[1:])
    rows = by_name(plan(tmp_path, verify_hashes=True))
    assert rows["edge-backup-short"]["decision"] == "QUARANTINE"
    assert any(x.startswith("SIZE_MISMATCH") for x in rows["edge-backup-short"]["reasons"])
    assert any(x.startswith("HASH_MISMATCH") for x in rows["edge-backup-flipped"]["reasons"])
    # Without --verify-hashes the flipped byte is not detected (same length): the report says so.
    assert by_name(plan(tmp_path))["edge-backup-flipped"]["decision"] != "QUARANTINE"


def test_an_incomplete_bundle_is_active_while_recent_then_quarantined(tmp_path):
    daily_history(tmp_path, 30)
    partial = make_bundle(tmp_path, "edge-backup-partial", NOW, manifest=None)
    stamp = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(partial / backup.DB_NAME, (stamp, stamp))
    os.utime(partial, (stamp, stamp))
    row = by_name(plan(tmp_path))["edge-backup-partial"]
    assert row["decision"] == "KEEP" and row["reasons"][0].startswith("ACTIVE_OR_IN_PROGRESS")
    later = by_name(plan(tmp_path, now=NOW + timedelta(hours=2)))["edge-backup-partial"]
    assert later["decision"] == "QUARANTINE" and later["reasons"][0].startswith("INCOMPLETE_NO_MANIFEST")


def test_non_bundle_entries_are_ignored_and_listed(tmp_path, capsys):
    daily_history(tmp_path, 3)
    (tmp_path / "notes.txt").write_text("hello")
    assert backup.main(["retention-plan", "--root", str(tmp_path), "--now", NOW.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["ignored_entries"] == ["notes.txt"]


# --------------------------------------------------------------------------- determinism


def test_the_plan_is_deterministic(tmp_path):
    daily_history(tmp_path, 120, per_day=2)
    daily_history(tmp_path, 40, kind="ledger")
    first = plan(tmp_path)
    bundles, _ = backup.scan_bundles(tmp_path, now=NOW, policy=POLICY, verified=recorded_verifications(tmp_path))
    random.Random(7).shuffle(bundles)
    shuffled = backup.retention_plan(bundles, now=NOW, policy=POLICY)
    assert json.dumps(first, sort_keys=True) == json.dumps(shuffled, sort_keys=True)
    assert json.dumps(plan(tmp_path), sort_keys=True) == json.dumps(first, sort_keys=True)


def test_checkpoint_files_are_read_from_a_directory(tmp_path):
    cps = tmp_path / "cps"
    cps.mkdir()
    (cps / "a.json").write_text(json.dumps({"created_at_utc": "2026-09-25T20:18:36+00:00",
                                            "accounts": {"x": {"head_entry_hash": "h"}}}))
    (cps / "b.json").write_text("{nope")
    loaded, problems = backup.load_checkpoints(cps)
    assert [c["heads"] for c in loaded] == [{"x": "h"}] and problems == ["b.json: JSONDecodeError"]


def test_the_cli_needs_a_zone_and_an_existing_root(tmp_path, capsys):
    assert backup.main(["retention-plan", "--root", str(tmp_path / "missing")]) == 1
    assert backup.main(["retention-plan", "--root", str(tmp_path), "--now", "2026-09-25T00:00:00"]) == 2
