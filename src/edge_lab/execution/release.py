"""The execution release manifest: what one installed release pins, and when a store or rollback fits it
(#160 package O, ADR 0047). Offline; it sends nothing and changes no store.

A release manifest is generated from the code at release time (`build_manifest`) and installed beside the code. It
pins:
- `code_revision`: the 40-hex commit the release was built from;
- `journal`: the store kind, schema version and schema fingerprint (every table, index and trigger) this code
  creates and accepts;
- `contracts`: the versioned formats the executor reads and writes (intent, approval, automation grant, signal,
  cycle record, private stream, risk projections, status export) and the conformance pack's retrieval date;
- `fees`: each fee schedule the profile can route to, by id and a digest of its terms, so changed fee math under an
  old id is a different release;
- `profile`: the conformance profile version;
- `authorized_environments`: `model.AUTHORIZED_ENVIRONMENTS` as built (today FIXTURE only);
- `compatible_rollback`: the release this one may roll back to without touching the store (same journal schema), or
  None.

`release_problems` is the start check (the executor unit runs it before anything else): the manifest must be this
code's own pins, the installed revision must match, and an existing journal must have exactly the pinned schema. A
store newer than the code is refused (old code never runs against a newer schema), and so is an older one (it needs a
forward-only migration, run as its own approved step). `rollback_problems` judges a planned rollback the same way: a
target release whose journal schema differs from the store's cannot run against it; the way back is an offline
restore of the pre-migration backup to a NEW path (`docs/execution/runbooks/MIGRATION_AND_ROLLBACK.md`).
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .. import fee_schedules
from . import conformance
from . import control
from . import recovery
from . import risk_gate
from . import status_export
from .journal import SCHEMA_VERSION, STORE_KIND
from .journal_backup import StoreIdentity, code_schema_fingerprint
from .model import APPROVAL_SCHEMA, AUTHORIZED_ENVIRONMENTS, INTENT_SCHEMA, canonical_json, sha256_text
from .orchestrator import CYCLE_SCHEMA, SIGNAL_SCHEMA

MANIFEST_SCHEMA = "edge-lab-execution-release/1"
MANIFEST_MAX_BYTES = 64 * 1024
_REVISION = re.compile(r"[0-9a-f]{40}")
# The fee schedules the ordinary-event profile can route to (risk_gate routes the profile's venue through
# `fee_schedules.schedule_for`; for Kalshi that is the general quadratic taker schedule).
_PROFILE_FEE_SCHEDULES = (fee_schedules.KALSHI_QUADRATIC_TAKER_V1,)


class ReleaseError(ValueError):
    """A manifest is malformed or not a release manifest."""


def _fee_pin(schedule: Any) -> dict[str, str]:
    terms = dataclasses.asdict(schedule)
    return {"schedule_id": schedule.schedule_id, "terms_sha256": sha256_text(canonical_json(terms))}


def code_pins() -> dict[str, Any]:
    """Everything a manifest pins except the revision and the rollback target, read from this code."""
    return {
        "journal": {"store_kind": STORE_KIND, "schema_version": SCHEMA_VERSION,
                    "schema_fingerprint": code_schema_fingerprint()},
        "contracts": {"intent": INTENT_SCHEMA, "approval": APPROVAL_SCHEMA, "automation_grant": control.GRANT_SCHEMA,
                      "signal": SIGNAL_SCHEMA, "cycle": CYCLE_SCHEMA, "private_stream": recovery.STREAM_SCHEMA,
                      "risk_projection": risk_gate.PROJECTION_SCHEMA, "risk_market_state": risk_gate.MARKET_STATE_SCHEMA,
                      "risk_limits": risk_gate.LIMITS_SCHEMA, "decision_evidence": risk_gate.EVIDENCE_SCHEMA,
                      "risk_decision": risk_gate.DECISION_SCHEMA, "status_export": status_export.SCHEMA,
                      "conformance_retrieved": conformance.RETRIEVED},
        "fees": [_fee_pin(s) for s in _PROFILE_FEE_SCHEDULES],
        "profile": conformance.PROFILE_VERSION,
        "authorized_environments": sorted(e.value for e in AUTHORIZED_ENVIRONMENTS),
    }


def _check_revision(name: str, value: Any, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ReleaseError(f"{name} must be a full 40-hex lowercase commit, not {value!r}")


def build_manifest(code_revision: str, *, rollback_revision: str | None = None,
                   rollback_journal_schema_version: int | None = None) -> dict[str, Any]:
    """A manifest for this code at `code_revision`. A rollback target is named only with its journal schema version,
    and only when that version equals this code's (otherwise it is not a compatible rollback)."""
    _check_revision("code_revision", code_revision)
    _check_revision("rollback_revision", rollback_revision, optional=True)
    if (rollback_revision is None) != (rollback_journal_schema_version is None):
        raise ReleaseError("a rollback target needs both its revision and its journal schema version")
    if rollback_journal_schema_version is not None and rollback_journal_schema_version != SCHEMA_VERSION:
        raise ReleaseError(f"INCOMPATIBLE_ROLLBACK: the target runs journal schema v{rollback_journal_schema_version}, "
                           f"this release v{SCHEMA_VERSION}; the way back is an offline restore, not a rollback")
    body = {"schema": MANIFEST_SCHEMA, "code_revision": code_revision, **code_pins(),
            "compatible_rollback": None if rollback_revision is None else {
                "code_revision": rollback_revision, "journal_schema_version": rollback_journal_schema_version}}
    return {**body, "digest": sha256_text(canonical_json(body))}


def parse_manifest(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MANIFEST_MAX_BYTES:
        raise ReleaseError("the manifest is larger than its bound")
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise ReleaseError("the manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ReleaseError(f"not a {MANIFEST_SCHEMA} manifest")
    body = {k: v for k, v in manifest.items() if k != "digest"}
    if manifest.get("digest") != sha256_text(canonical_json(body)):
        raise ReleaseError("the manifest digest does not match its content")
    _check_revision("code_revision", manifest.get("code_revision"))
    rollback = manifest.get("compatible_rollback")
    if rollback is not None:
        if not isinstance(rollback, dict):
            raise ReleaseError("compatible_rollback must be an object or null")
        _check_revision("compatible_rollback.code_revision", rollback.get("code_revision"))
    return manifest


def load_manifest(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ReleaseError(f"no release manifest at {p.name}")
    return parse_manifest(p.read_text(encoding="utf-8"))


def render_manifest(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, sort_keys=True, indent=2) + "\n"


def _store_problems(pinned: Mapping[str, Any], store: StoreIdentity, label: str = "RELEASE") -> list[str]:
    out = []
    if store.store_kind != pinned.get("store_kind"):
        out.append(f"STORE_KIND_MISMATCH: {store.store_kind}")
    version = pinned.get("schema_version")
    if isinstance(version, int) and store.schema_version > version:
        out.append(f"STORE_NEWER_THAN_{label}: store v{store.schema_version}, release v{version}; old code never "
                   f"runs against a newer schema (restore the pre-migration backup offline instead)")
    elif isinstance(version, int) and store.schema_version < version:
        out.append(f"STORE_OLDER_THAN_{label}: store v{store.schema_version}, release v{version}; a forward-only "
                   f"migration is its own approved step")
    elif store.schema_fingerprint != pinned.get("schema_fingerprint"):
        out.append("STORE_SCHEMA_OBJECTS_DIFFER: same version, different tables, indexes or triggers")
    return out


def release_problems(manifest: Mapping[str, Any], *, installed_revision: str | None,
                     store: StoreIdentity | None) -> list[str]:
    """Why this release must not start (empty when it may). `store` is None when no journal exists yet."""
    out = []
    pins = code_pins()
    for key, value in pins.items():
        if manifest.get(key) != value:
            out.append(f"MANIFEST_NOT_THIS_CODE: {key} differs from the installed code")
    revision = (installed_revision or "").strip()
    if revision != manifest.get("code_revision"):
        out.append("REVISION_MISMATCH: the installed REVISION is not the manifest's code_revision")
    if store is not None:
        out += _store_problems(pins["journal"], store)
    return out


def rollback_problems(current: Mapping[str, Any], target: Mapping[str, Any], *, store: StoreIdentity) -> list[str]:
    """Why rolling back from `current` to `target` against `store` is not a plain code rollback."""
    out = []
    pinned = target.get("journal") if isinstance(target.get("journal"), Mapping) else {}
    out += _store_problems(pinned, store, "TARGET_RELEASE")
    named = current.get("compatible_rollback") or {}
    if named.get("code_revision") != target.get("code_revision"):
        out.append("NOT_THE_NAMED_ROLLBACK: the current release names another (or no) compatible rollback")
    if target.get("authorized_environments") != current.get("authorized_environments"):
        out.append("AUTHORIZATION_DIFFERS: a rollback never changes the authorized environments")
    return out

