"""The execution release manifest, the start check and rollback compatibility (#160 package O, ADR 0047). Offline."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab import fee_schedules
from edge_lab.execution import journal as journal_module
from edge_lab.execution import journal_backup as jb
from edge_lab.execution import release as rl
from edge_lab.execution.model import AUTHORIZED_ENVIRONMENTS

REV, OLD_REV = "a" * 40, "b" * 40
# The journal schema each version means, pinned. Changing a table, index or trigger without bumping
# `journal.SCHEMA_VERSION` fails here: a version number never names two schemas (the ledger's package D note; ADR 0047).
KNOWN_SCHEMA_FINGERPRINTS = {1: "1c61fcfcbd51fd163db00d9067fcc5caf37bb1906676e3f9d9a23ee1339a69e6"}


def _rebuild(manifest: dict, **changes) -> dict:
    body = {k: v for k, v in manifest.items() if k != "digest"}
    body.update(changes)
    return {**body, "digest": rl.sha256_text(rl.canonical_json(body))}


def test_the_schema_version_names_exactly_one_schema():
    assert KNOWN_SCHEMA_FINGERPRINTS[journal_module.SCHEMA_VERSION] == jb.code_schema_fingerprint()


def test_the_manifest_pins_code_schema_contracts_fees_profile_and_authorization():
    m = rl.build_manifest(REV)
    assert m["schema"] == rl.MANIFEST_SCHEMA and m["code_revision"] == REV
    assert m["journal"] == {"store_kind": journal_module.STORE_KIND, "schema_version": journal_module.SCHEMA_VERSION,
                            "schema_fingerprint": KNOWN_SCHEMA_FINGERPRINTS[journal_module.SCHEMA_VERSION]}
    assert {"intent", "approval", "automation_grant", "signal", "cycle", "status_export"} <= set(m["contracts"])
    assert [p["schedule_id"] for p in m["fees"]] == ["kalshi-quadratic-taker-v1"]
    assert m["profile"] == "kalshi-ordinary-v0"
    assert m["authorized_environments"] == ["FIXTURE"] == sorted(e.value for e in AUTHORIZED_ENVIRONMENTS)
    assert m["compatible_rollback"] is None
    assert rl.parse_manifest(rl.render_manifest(m)) == m


def test_changed_fee_terms_under_the_same_id_are_a_different_release():
    schedule = fee_schedules.KALSHI_QUADRATIC_TAKER_V1
    changed = dataclasses.replace(schedule, multiplier=Decimal("2"))
    assert rl._fee_pin(changed)["schedule_id"] == rl._fee_pin(schedule)["schedule_id"]
    assert rl._fee_pin(changed)["terms_sha256"] != rl._fee_pin(schedule)["terms_sha256"]


@pytest.mark.parametrize("mutate,match", [
    (lambda t: t.replace('"FIXTURE"', '"DEMO"'), "digest"),
    (lambda t: t.replace(rl.MANIFEST_SCHEMA, "edge-lab-execution-release/0"), "not a"),
    (lambda t: "{" * 3, "not valid JSON"),
    (lambda t: t + " " * rl.MANIFEST_MAX_BYTES, "bound"),
])
def test_a_tampered_or_foreign_manifest_is_refused(mutate, match):
    with pytest.raises(rl.ReleaseError, match=match):
        rl.parse_manifest(mutate(rl.render_manifest(rl.build_manifest(REV))))


@pytest.mark.parametrize("revision", ["A" * 40, "a" * 39, "", None, "a" * 64])
def test_a_revision_must_be_a_full_lowercase_commit(revision):
    with pytest.raises(rl.ReleaseError):
        rl.build_manifest(revision)


def test_the_start_check_passes_only_for_this_code_this_revision_and_this_schema(tmp_path: Path):
    m = rl.build_manifest(REV)
    assert rl.release_problems(m, installed_revision=REV + "\n", store=None) == []
    journal, _ = f.ready(tmp_path / "x.execution.sqlite3")
    store = jb.store_identity(journal.path)
    journal.close()
    assert rl.release_problems(m, installed_revision=REV, store=store) == []
    assert any(p.startswith("REVISION_MISMATCH") for p in rl.release_problems(m, installed_revision=OLD_REV, store=store))
    assert any(p.startswith("REVISION_MISMATCH") for p in rl.release_problems(m, installed_revision=None, store=store))
    older_code = _rebuild(m, contracts={**m["contracts"], "cycle": "edge-lab-orchestrator-cycle/0"})
    assert rl.release_problems(older_code, installed_revision=REV, store=store) == [
        "MANIFEST_NOT_THIS_CODE: contracts differs from the installed code"]
    widened = _rebuild(m, authorized_environments=["DEMO", "FIXTURE"])
    assert any("authorized_environments" in p for p in rl.release_problems(widened, installed_revision=REV, store=store))


def _with_version(store: jb.StoreIdentity, version: int, fingerprint: str | None = None) -> jb.StoreIdentity:
    return dataclasses.replace(store, schema_version=version, schema_fingerprint=fingerprint or store.schema_fingerprint)


def test_old_code_never_starts_against_a_newer_store_and_new_code_never_migrates_silently(tmp_path: Path):
    m = rl.build_manifest(REV)
    journal, _ = f.ready(tmp_path / "x.execution.sqlite3")
    store = jb.store_identity(journal.path)
    journal.close()
    newer = rl.release_problems(m, installed_revision=REV, store=_with_version(store, store.schema_version + 1))
    assert newer and newer[0].startswith("STORE_NEWER_THAN_RELEASE")
    older = rl.release_problems(m, installed_revision=REV, store=_with_version(store, store.schema_version - 1))
    assert older and older[0].startswith("STORE_OLDER_THAN_RELEASE")
    altered = rl.release_problems(m, installed_revision=REV, store=_with_version(store, store.schema_version, "0" * 64))
    assert altered and altered[0].startswith("STORE_SCHEMA_OBJECTS_DIFFER")


def test_a_real_half_migrated_store_fails_the_start_check(tmp_path: Path):
    path = tmp_path / "x.execution.sqlite3"
    journal, _ = f.ready(path)
    journal.close()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE added_by_a_future_migration (x TEXT)")
    conn.commit()
    conn.close()
    problems = rl.release_problems(rl.build_manifest(REV), installed_revision=REV, store=jb.store_identity(path))
    assert problems == ["STORE_SCHEMA_OBJECTS_DIFFER: same version, different tables, indexes or triggers"]


def test_a_rollback_is_compatible_only_to_the_named_release_with_the_same_journal_schema(tmp_path: Path):
    journal, _ = f.ready(tmp_path / "x.execution.sqlite3")
    store = jb.store_identity(journal.path)
    journal.close()
    target = rl.build_manifest(OLD_REV)
    current = rl.build_manifest(REV, rollback_revision=OLD_REV, rollback_journal_schema_version=store.schema_version)
    assert current["compatible_rollback"] == {"code_revision": OLD_REV, "journal_schema_version": store.schema_version}
    assert rl.rollback_problems(current, target, store=store) == []
    unnamed = rl.build_manifest(REV)
    assert rl.rollback_problems(unnamed, target, store=store)[0].startswith("NOT_THE_NAMED_ROLLBACK")
    # The store was migrated forward after the target was built: the target cannot run against it.
    old_schema_target = _rebuild(target, journal={**target["journal"], "schema_version": store.schema_version - 1})
    assert rl.rollback_problems(current, old_schema_target, store=store)[0].startswith("STORE_NEWER_THAN_TARGET_RELEASE")
    wider = _rebuild(target, authorized_environments=["DEMO", "FIXTURE"])
    assert "AUTHORIZATION_DIFFERS" in " ".join(rl.rollback_problems(current, wider, store=store))


def test_a_manifest_cannot_name_an_incompatible_rollback():
    with pytest.raises(rl.ReleaseError, match="INCOMPATIBLE_ROLLBACK"):
        rl.build_manifest(REV, rollback_revision=OLD_REV,
                          rollback_journal_schema_version=journal_module.SCHEMA_VERSION - 1)
    with pytest.raises(rl.ReleaseError, match="both"):
        rl.build_manifest(REV, rollback_revision=OLD_REV)


def test_load_manifest_refuses_a_missing_file_and_round_trips_a_written_one(tmp_path: Path):
    with pytest.raises(rl.ReleaseError, match="no release manifest"):
        rl.load_manifest(tmp_path / "release.json")
    path = tmp_path / "release.json"
    path.write_text(rl.render_manifest(rl.build_manifest(REV)), encoding="utf-8")
    assert rl.load_manifest(path)["code_revision"] == REV
    assert json.loads(path.read_text(encoding="utf-8"))["digest"] == rl.load_manifest(path)["digest"]
