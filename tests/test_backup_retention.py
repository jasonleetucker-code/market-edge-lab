"""The backup retention planner is a DRY RUN only (PROPOSED policy, docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md).

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


def plan(root: Path, now: datetime = NOW, **kw) -> dict:
    bundles, _ = backup.scan_bundles(root, now=now, policy=POLICY, verify_hashes=kw.pop("verify_hashes", False))
    return backup.retention_plan(bundles, now=now, policy=POLICY, **kw)


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


def test_the_planner_has_no_deletion_code_path():
    import ast
    import textwrap

    forbidden = {"unlink", "rmtree", "remove", "rmdir", "removedirs", "rename", "renames", "truncate",
                 "write_text", "write_bytes", "chmod", "move", "copyfile"}
    for f in (backup.inspect_bundle, backup.scan_bundles, backup.load_checkpoints, backup.retention_plan,
              backup._covers, backup._retention_main, backup._newest_mtime):
        tree = ast.parse(textwrap.dedent(inspect.getsource(f)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                owner = getattr(getattr(fn, "value", None), "id", None)
                assert name not in forbidden, f"{f.__name__} calls {name}"
                assert not (owner in ("os", "shutil") and name == "replace"), f"{f.__name__} calls os.replace"
                if name == "open":  # only reads
                    assert all(not (isinstance(a, ast.Constant) and set(str(a.value)) & set("wax+"))
                               for a in node.args[1:]), f"{f.__name__} opens for writing"
    parser_source = inspect.getsource(backup.main)
    assert "--apply" not in parser_source and "--delete" not in parser_source


def test_the_cli_deletes_nothing_even_when_every_deletion_api_would_work(tmp_path, monkeypatch, capsys):
    daily_history(tmp_path, 120)
    make_bundle(tmp_path, "edge-backup-broken", NOW - timedelta(days=50), manifest="{not json")
    before = sorted(p.as_posix() for p in tmp_path.rglob("*"))

    def refuse(*_a, **_k):
        raise AssertionError("the retention planner must never delete")
    for target, name in ((os, "remove"), (os, "unlink"), (os, "rmdir"), (os, "rename"), (os, "replace"),
                         (shutil, "rmtree"), (shutil, "move"), (Path, "unlink"), (Path, "rmdir"),
                         (Path, "rename"), (Path, "replace")):
        monkeypatch.setattr(target, name, refuse)
    code = backup.main(["retention-plan", "--root", str(tmp_path), "--now", NOW.isoformat(), "--verify-hashes"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "DRY_RUN_ONLY" and report["deletes_performed"] == 0
    assert report["policy"]["status"] == "PROPOSED"
    assert report["summary"]["evidence"]["DELETE-CANDIDATE"] > 0  # candidates are reported, never acted on
    assert sorted(p.as_posix() for p in tmp_path.rglob("*")) == before


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
    bundles, _ = backup.scan_bundles(tmp_path, now=NOW, policy=POLICY)
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
