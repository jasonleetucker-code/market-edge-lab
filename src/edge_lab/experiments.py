"""Experiment registry: load and validate `experiments/*/experiment.toml`.

The manifest is the durable record of what an experiment claimed before it ran
and what it found afterwards. Validation is deliberately strict about
structure and lifecycle and says nothing about whether a result is "good".
See experiments/README.md for the lifecycle and amendment rules.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

STATUSES = (
    "DRAFT",
    "PREREGISTERED",
    "RUNNING",
    "CONCLUDED_PASS",
    "CONCLUDED_FAIL",
    "CONCLUDED_INCONCLUSIVE",
    "ABANDONED",
)
CONCLUDED = {s for s in STATUSES if s.startswith("CONCLUDED_")}
# From PREREGISTERED on, the hypothesis and criteria are locked; changes go in
# [[amendments]] with a reason and date instead of editing the original text.
LOCKED = CONCLUDED | {"PREREGISTERED", "RUNNING"}

REQUIRED_STRINGS = (
    "id",
    "title",
    "status",
    "hypothesis",
    "economic_rationale",
    "market",
    "decision_time",
    "model",
    "owner",
    "created",
)
REQUIRED_LISTS = (
    "data_sources",
    "features",
    "success_criteria",
    "failure_criteria",
    "risk_constraints",
    "limitations",
    "gates_required",
)
REQUIRED_TABLES = ("periods", "costs", "execution", "artifacts")
PERIOD_KEYS = ("train", "validation", "test")
ID_PATTERN = re.compile(r"^EXP-\d{3}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Experiment:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))


def load(path: Path) -> Experiment:
    with path.open("rb") as handle:
        return Experiment(path=path, data=tomllib.load(handle))


def validate(exp: Experiment) -> list[str]:
    """Return human-readable problems. An empty list means the manifest is valid."""
    d = exp.data
    problems: list[str] = []

    for key in REQUIRED_STRINGS:
        value = d.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"missing or empty string field '{key}'")
    for key in REQUIRED_LISTS:
        value = d.get(key)
        if not isinstance(value, list) or not value:
            problems.append(f"missing or empty list field '{key}'")
        elif not all(isinstance(item, str) and item.strip() for item in value):
            problems.append(f"list field '{key}' must contain only non-empty strings")
    for key in REQUIRED_TABLES:
        if not isinstance(d.get(key), dict):
            problems.append(f"missing table [{key}]")

    if exp.id and not ID_PATTERN.match(exp.id):
        problems.append(f"id '{exp.id}' must look like EXP-001")
    if exp.id and not exp.path.parent.name.startswith(exp.id + "-"):
        problems.append(f"directory '{exp.path.parent.name}' must start with '{exp.id}-'")
    if exp.status and exp.status not in STATUSES:
        problems.append(f"status '{exp.status}' not in {', '.join(STATUSES)}")
    created = d.get("created")
    if isinstance(created, str):
        try:
            if not DATE_PATTERN.match(created):
                raise ValueError
            date.fromisoformat(created)
        except ValueError:
            problems.append("created must be a real date in YYYY-MM-DD form")

    for table, keys in TABLE_KEYS.items():
        section = d.get(table)
        if isinstance(section, dict):
            for key in keys:
                if key not in section:
                    problems.append(f"[{table}] missing '{key}' (use \"TBD\" while DRAFT)")

    if exp.status in LOCKED:
        # Once preregistered, nothing the decision depends on may be left open.
        for label in _undefined_locked_fields(d):
            problems.append(f"{exp.status} experiment has undefined '{label}' (placeholder or empty)")

    amendments = d.get("amendments", [])
    if not isinstance(amendments, list):
        problems.append("amendments must be an array of tables")
    else:
        for i, amendment in enumerate(amendments):
            if not isinstance(amendment, dict) or not all(
                isinstance(amendment.get(k), str) and amendment.get(k)
                for k in ("date", "change", "reason")
            ):
                problems.append(f"amendment {i} needs non-empty date, change, reason")
            elif "field" in amendment and not _amendable_field(amendment["field"]):
                problems.append(f"amendment {i} names unknown field {amendment['field']!r}")

    if exp.status in CONCLUDED:
        result = d.get("result")
        if not isinstance(result, dict):
            problems.append("concluded experiment needs a [result] table")
        else:
            for key in ("code_commit", "dataset_version", "report", "summary"):
                if not result.get(key):
                    problems.append(f"[result] missing '{key}'")
            report = result.get("report")
            if isinstance(report, str) and report and not (exp.path.parent / report).exists():
                problems.append(f"[result] report '{report}' does not exist")

    problems.extend(protocol_problems(exp))
    problems.extend(baseline_problems(exp))
    return problems


# Values that mean "not decided yet". Matched case-insensitively at the start of
# a string, so "TBD: candidate is ..." and "to be determined" both count.
_PLACEHOLDER = re.compile(r"^\s*(tbd|tba|todo|to be (determined|decided|defined)|pending|unknown|n/?a\b|\?+|-+\s*$|$)", re.I)
# Decision parameters that must be concrete once an experiment is locked.
LOCKED_STRINGS = ("hypothesis", "economic_rationale", "market", "decision_time", "model")
LOCKED_LISTS = ("data_sources", "features", "success_criteria", "failure_criteria")
LOCKED_TABLES = ("periods", "costs", "execution")
# Keys each table must define (as "TBD" while DRAFT, concretely once locked).
TABLE_KEYS = {
    "periods": PERIOD_KEYS,
    "costs": ("fee_model", "spread"),
    "execution": ("fill_model", "latency"),
}


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER.match(value))


def _placeholders(value: Any, path: str) -> list[str]:
    """Paths of every placeholder or empty value, recursing into tables and arrays."""
    if isinstance(value, dict):
        if not value:
            return [path]
        return [p for k, v in value.items() for p in _placeholders(v, f"{path}.{k}")]
    if isinstance(value, list):
        if not value:
            return [path]
        return [p for i, v in enumerate(value) for p in _placeholders(v, f"{path}[{i}]")]
    return [path] if _is_placeholder(value) else []


def _undefined_locked_fields(d: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in LOCKED_STRINGS + LOCKED_LISTS + LOCKED_TABLES:
        labels += _placeholders(d.get(key, ""), key)
    return labels


def discover(root: Path) -> list[Path]:
    return sorted(root.glob("*/experiment.toml"))


def validate_all(root: Path) -> dict[str, list[str]]:
    """Validate every manifest under `root`, including cross-manifest ID uniqueness
    and the active research-family slot limit."""
    results: dict[str, list[str]] = {}
    seen: dict[str, Path] = {}
    loaded: list[tuple[str, Experiment]] = []
    for path in discover(root):
        key = str(path.relative_to(root))
        try:
            exp = load(path)
        except tomllib.TOMLDecodeError as exc:
            results[key] = [f"invalid TOML: {exc}"]
            continue
        problems = validate(exp)
        if exp.id in seen:
            problems.append(f"duplicate id {exp.id} (also {seen[exp.id]})")
        seen[exp.id] = path
        results[key] = problems
        loaded.append((key, exp))
    for key, problem in family_slot_problems(loaded, repo=root.resolve().parent):
        results[key].append(problem)
    return results


# ---------------------------------------------------------------------------
# Preregistration freeze
# ---------------------------------------------------------------------------
# The fields a preregistered experiment may never change in place. Changes go in
# [[amendments]] (date, change, reason, and optionally field + value), so the
# original text stays in the manifest and the baseline, and the effective spec is
# original + amendments.
FROZEN_FIELDS = (
    "hypothesis",
    "economic_rationale",
    "market",
    "decision_time",
    "model",
    "data_sources",
    "features",
    "success_criteria",
    "failure_criteria",
    "risk_constraints",
    "periods",
    "costs",
    "execution",
)
BASELINE_NAME = "preregistration.json"
FREEZE_VERSION = "1"


def frozen_view(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data.get(key) for key in FROZEN_FIELDS}


def frozen_hash(view: dict[str, Any]) -> str:
    import hashlib
    import json

    text = json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def freeze(exp: Experiment, *, now_utc: str) -> Path:
    """Write the preregistration baseline for a manifest already set to PREREGISTERED.

    Refuses to overwrite an existing baseline and refuses manifests that are not fully
    specified: a freeze is a one-time act.
    """
    import json

    target = exp.path.parent / BASELINE_NAME
    if target.exists():
        raise FileExistsError(f"{target} already exists; preregistration baselines are never rewritten")
    if exp.status != "PREREGISTERED":
        raise ValueError("set status = \"PREREGISTERED\" in the manifest before freezing")
    problems = [p for p in validate(exp) if "preregistration baseline" not in p]
    if problems:
        raise ValueError("manifest is not freezable: " + "; ".join(problems))
    view = frozen_view(exp.data)
    baseline = {
        "experiment_id": exp.id,
        "frozen_at_utc": now_utc,
        "freeze_version": FREEZE_VERSION,
        "frozen_fields_sha256": frozen_hash(view),
        "frozen_fields": view,
    }
    protocol = load_protocol(exp)
    if protocol is not None:
        # Additive: only experiments with a protocol sidecar carry these keys, so every
        # existing baseline (EXP-001) keeps its exact bytes and hash.
        baseline["protocol_file"] = PROTOCOL_NAME
        baseline["protocol_sha256"] = frozen_hash(protocol)
        baseline["protocol"] = protocol
    target.write_text(json.dumps(baseline, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    return target


def baseline_problems(exp: Experiment) -> list[str]:
    """For locked experiments: the baseline must exist, be self-consistent and match."""
    import json

    if exp.status not in LOCKED:
        return []
    target = exp.path.parent / BASELINE_NAME
    if not target.exists():
        return [f"{exp.status} experiment has no preregistration baseline ({BASELINE_NAME}); run `edge-lab experiments freeze`"]
    try:
        baseline = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"preregistration baseline unreadable: {exc}"]
    problems = []
    recorded = baseline.get("frozen_fields")
    if not isinstance(recorded, dict) or frozen_hash(recorded) != baseline.get("frozen_fields_sha256"):
        problems.append("preregistration baseline does not match its own hash (edited?)")
    if baseline.get("experiment_id") != exp.id:
        problems.append("preregistration baseline belongs to a different experiment")
    current = frozen_view(exp.data)
    if isinstance(recorded, dict) and current != recorded:
        changed = sorted(k for k in FROZEN_FIELDS if current.get(k) != recorded.get(k))
        problems.append(
            f"locked fields changed since preregistration: {changed} "
            "(record changes in [[amendments]] instead of editing)"
        )
    try:
        protocol = load_protocol(exp)
    except (OSError, tomllib.TOMLDecodeError):
        protocol = None  # reported by protocol_problems
    if "protocol" in baseline:
        frozen_protocol = baseline.get("protocol")
        if not isinstance(frozen_protocol, dict) or frozen_hash(frozen_protocol) != baseline.get("protocol_sha256"):
            problems.append("preregistration baseline protocol does not match its own hash (edited?)")
        elif protocol != frozen_protocol:
            problems.append(
                f"{PROTOCOL_NAME} changed since preregistration "
                "(record changes in [[amendments]] with field = \"protocol.<table>.<key>\")"
            )
    elif protocol is not None:
        problems.append(f"{PROTOCOL_NAME} was added after preregistration; it is not part of the frozen baseline")
    return problems


def changed_baselines(base_ref: str, *, repo: Path) -> list[str]:
    """Baseline files modified or deleted relative to `base_ref` (additions are fine)."""
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--name-status", base_ref, "HEAD", "--", f"experiments/*/{BASELINE_NAME}"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line and not line.startswith("A")]



# ---------------------------------------------------------------------------
# Research-protocol sidecar (Economic Evidence v1, #96)
# ---------------------------------------------------------------------------
# New experiments carry `protocol.toml` beside `experiment.toml`. The sidecar holds the
# research-governance fields the original manifest schema never had: family slot,
# mechanism, universe, clustering, endpoints, information cutoff, data roles, variants
# and multiple testing, cost/fill and size/capital assumptions, chronological and
# untouched-future evaluation, budget, review date, stopping/futility, minimum useful
# effect, readiness and the frozen episode definition.
#
# Compatibility: the sidecar is additive. Only the experiments in LEGACY_EXPERIMENTS (EXP-001,
# which predates the sidecar) may lack one; they are read as LEGACY and nothing in their
# manifest, baseline or validation changes. Every other experiment needs a sidecar, whatever
# its `created` date says (a backdated manifest cannot dodge the rule). A sidecar is part of
# the preregistration baseline of any experiment frozen with one.
#
# Honesty rules: in DRAFT every field must be present, but its value may be an explicit
# "UNKNOWN: ..." or "MISSING_OWNER_INPUT: ..." / "MISSING_POWER_ANALYSIS: ...". From
# PREREGISTERED on, every *decision* field must be settled. The [knowledge] table holds
# facts that may honestly stay UNKNOWN even after preregistration (for example source
# independence or an annual opportunity count); it must be present, never invented.
# The settled-value check is a heuristic: it rejects UNKNOWN / UNVERIFIED / TBD / MISSING_*
# tokens anywhere and deferral phrases ("to be frozen", "will be decided"); an inadequate
# but concrete-looking value is still a review question.

PROTOCOL_NAME = "protocol.toml"
PROTOCOL_VERSION = "research-protocol-v1"
LEGACY_EXPERIMENTS = frozenset({"EXP-001"})  # predate the sidecar; the only experiments allowed without one
OWNER_EXCEPTION_DIR = "docs/owner/"
MAX_ACTIVE_FAMILIES = 2
SLOT_STATES = ("ACTIVE", "QUEUED", "ENDED")
PROTOCOL_TOP = ("protocol_version", "experiment_id", "family", "family_title", "slot_status", "authority",
                "mechanism", "named_hypothesis", "baseline")
PROTOCOL_TABLES: dict[str, tuple[str, ...]] = {
    "universe": ("eligible", "exclusions"),
    "observation": ("unit", "clusters", "dependence"),
    "endpoints": ("primary", "secondary"),
    "information": ("cutoff", "max_input_age", "clock_uncertainty"),
    "data_roles": ("data", "features", "labels", "permission_lineage", "prohibited_inputs"),
    "variants": ("allowed", "multiple_testing"),
    "costs_fills": ("fees", "fills", "evidence_quality"),
    "size_capital": ("size_ladder", "capital_scenarios", "capital_assumptions"),
    "evaluation": ("chronological", "untouched_future_window", "exposure_history", "controls"),
    "budget": ("research_cash_usd", "owner_hours", "data_costs", "review_date"),
    "stopping": ("futility", "stop", "continue_rule", "verdicts"),
    "economics": ("minimum_useful_effect", "power_analysis"),
    "readiness": ("product", "strategy", "permitted_uses", "remaining_blockers"),
    "episode": ("definition", "start_threshold", "end_merge_gap", "minimum_size"),
    "knowledge": ("source_independence", "annual_episode_count", "fill_probability"),
}
# May stay UNKNOWN after preregistration (descriptive facts, never decision parameters).
PROTOCOL_KNOWLEDGE_TABLE = "knowledge"
_UNSETTLED_START = re.compile(r"^\s*(missing|unknown|unverified\b)", re.I)
_UNSETTLED_TOKEN = re.compile(r"\bUNKNOWN\b|\bUNVERIFIED\b|\bTBD\b|MISSING_OWNER_INPUT|MISSING_POWER_ANALYSIS")
_UNSETTLED_PHRASE = re.compile(r"\b(to be|will be|still to be|yet to be)\s+(frozen|decided|determined|settled|chosen|"
                               r"defined|set|agreed)\b", re.I)


def protocol_path(exp: Experiment) -> Path:
    return exp.path.parent / PROTOCOL_NAME


def load_protocol(exp: Experiment) -> dict[str, Any] | None:
    """The experiment's protocol sidecar, or None when it has none (a LEGACY experiment).

    Raises tomllib.TOMLDecodeError for a malformed sidecar; `protocol_problems` reports it."""
    path = protocol_path(exp)
    if not path.exists():
        return None
    with path.open("rb") as handle:
        return tomllib.load(handle)


def protocol_state(exp: Experiment) -> str:
    """PRESENT, LEGACY (an allowlisted pre-sidecar experiment: EXP-001) or MISSING.

    This is the explicit compatibility reader: callers never infer protocol fields for a
    LEGACY experiment; every such field is UNKNOWN."""
    if protocol_path(exp).exists():
        return "PRESENT"
    if exp.id in LEGACY_EXPERIMENTS:
        return "LEGACY"
    return "MISSING"


def _unsettled(value: Any) -> bool:
    return isinstance(value, str) and (bool(_UNSETTLED_START.match(value)) or bool(_UNSETTLED_TOKEN.search(value))
                                       or bool(_UNSETTLED_PHRASE.search(value)) or _is_placeholder(value))


def _unsettled_paths(value: Any, path: str) -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [path]
        return [p for k, v in value.items() for p in _unsettled_paths(v, f"{path}.{k}")]
    if isinstance(value, list):
        if not value:
            return [path]
        return [p for i, v in enumerate(value) for p in _unsettled_paths(v, f"{path}[{i}]")]
    return [path] if _unsettled(value) else []


def _present(value: Any) -> bool:
    """Present means stated: a non-empty string, a number, a bool, or a non-empty list/table of them.
    An explicit "UNKNOWN: ..." string is present; an empty value is not."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(_present(v) for v in value)
    if isinstance(value, dict):
        return bool(value) and all(_present(v) for v in value.values())
    return False


def protocol_problems(exp: Experiment) -> list[str]:
    """Problems with the protocol sidecar. LEGACY experiments have none by construction."""
    state = protocol_state(exp)
    if state == "LEGACY":
        return []
    if state == "MISSING":
        return [f"every experiment except {', '.join(sorted(LEGACY_EXPERIMENTS))} needs a {PROTOCOL_NAME} sidecar "
                "(experiments/README.md, Research-protocol sidecar)"]
    try:
        protocol = load_protocol(exp)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{PROTOCOL_NAME} is not valid TOML: {exc}"]
    assert protocol is not None
    problems: list[str] = []
    for key in PROTOCOL_TOP:
        if not _present(protocol.get(key)):
            problems.append(f"{PROTOCOL_NAME} missing or empty '{key}' (write \"UNKNOWN: <why>\" if unknown)")
    for table, keys in PROTOCOL_TABLES.items():
        section = protocol.get(table)
        if not isinstance(section, dict):
            problems.append(f"{PROTOCOL_NAME} missing table [{table}]")
            continue
        for key in keys:
            if not _present(section.get(key)):
                problems.append(f"{PROTOCOL_NAME} [{table}] missing or empty '{key}' "
                                "(write \"UNKNOWN: <why>\" if unknown)")
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        problems.append(f"{PROTOCOL_NAME} protocol_version must be {PROTOCOL_VERSION!r}")
    if protocol.get("experiment_id") != exp.id:
        problems.append(f"{PROTOCOL_NAME} experiment_id {protocol.get('experiment_id')!r} is not {exp.id!r}")
    if protocol.get("slot_status") not in SLOT_STATES:
        problems.append(f"{PROTOCOL_NAME} slot_status must be one of {', '.join(SLOT_STATES)}")
    family = protocol.get("family")
    if isinstance(family, str) and not re.fullmatch(r"[A-Z][A-Z0-9_]*", family):
        problems.append(f"{PROTOCOL_NAME} family {family!r} must be one uppercase token (one slot, no hidden split)")
    roles = protocol.get("data_roles")
    prohibited = roles.get("prohibited_inputs") if isinstance(roles, dict) else None
    if prohibited is not None and not (isinstance(prohibited, list) and all(isinstance(p, str) for p in prohibited)):
        problems.append(f"{PROTOCOL_NAME} [data_roles] prohibited_inputs must be a list of dataset-id prefixes")
    label_scopes = roles.get("prohibited_label_scopes") if isinstance(roles, dict) else None
    if label_scopes is not None and not (isinstance(label_scopes, list)
                                         and all(isinstance(s, str) and s.strip() for s in label_scopes)):
        problems.append(f"{PROTOCOL_NAME} [data_roles] prohibited_label_scopes must be a list of outcome scopes")
    exception = protocol.get("owner_exception")
    if exception is not None and not (isinstance(exception, str) and exception.startswith(OWNER_EXCEPTION_DIR)):
        problems.append(f"{PROTOCOL_NAME} owner_exception must name an owner decision under {OWNER_EXCEPTION_DIR}")
    budget = protocol.get("budget")
    review = budget.get("review_date") if isinstance(budget, dict) else None
    if isinstance(review, str) and not _unsettled(review):
        try:
            if not DATE_PATTERN.match(review):
                raise ValueError
            date.fromisoformat(review)
        except ValueError:
            problems.append(f"{PROTOCOL_NAME} [budget] review_date must be YYYY-MM-DD or \"UNKNOWN: <why>\"")
    if exp.status in LOCKED:
        for table in PROTOCOL_TABLES:
            if table == PROTOCOL_KNOWLEDGE_TABLE:
                continue
            for label in _unsettled_paths(protocol.get(table, {}), table):
                problems.append(f"{exp.status} experiment has unsettled protocol field '{label}' "
                                "(settle it, with a power/cost rationale, before preregistering)")
        for key in PROTOCOL_TOP:
            for label in _unsettled_paths(protocol.get(key, ""), key):
                problems.append(f"{exp.status} experiment has unsettled protocol field '{label}'")
    return problems


def prohibited_label_scopes(exp: Experiment) -> tuple[str, ...]:
    """Outcome scopes whose labels/results this experiment may never view (none for LEGACY)."""
    try:
        protocol = load_protocol(exp)
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    roles = (protocol or {}).get("data_roles")
    values = roles.get("prohibited_label_scopes") if isinstance(roles, dict) else None
    return tuple(v for v in values if isinstance(v, str) and v.strip()) if isinstance(values, list) else ()


def prohibited_inputs(exp: Experiment) -> tuple[str, ...]:
    """Dataset-id prefixes this experiment's protocol forbids it to access (none for LEGACY)."""
    try:
        protocol = load_protocol(exp)
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    roles = (protocol or {}).get("data_roles")
    values = roles.get("prohibited_inputs") if isinstance(roles, dict) else None
    return tuple(v for v in values if isinstance(v, str) and v.strip()) if isinstance(values, list) else ()


def family_slot_problems(loaded: list[tuple[str, Experiment]], *, repo: Path) -> list[tuple[str, str]]:
    """At most MAX_ACTIVE_FAMILIES distinct ACTIVE families among open experiments.

    EXP-001 (LEGACY, protected) does not use a slot. A family beyond the limit needs an
    `owner_exception` naming an existing owner-decision document. Several experiments may
    share one family (one slot); splitting a family into differently named families to
    dodge the limit is exactly what this check refuses."""
    active: dict[str, list[str]] = {}
    exceptions: set[str] = set()
    for key, exp in loaded:
        if exp.status in CONCLUDED or exp.status == "ABANDONED":
            continue
        try:
            protocol = load_protocol(exp)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if not protocol or protocol.get("slot_status") != "ACTIVE" or not isinstance(protocol.get("family"), str):
            continue
        family = protocol["family"]
        active.setdefault(family, []).append(key)
        exception = protocol.get("owner_exception")
        if isinstance(exception, str) and exception.startswith(OWNER_EXCEPTION_DIR) and (repo / exception).is_file():
            exceptions.add(family)
    unexcepted = [f for f in sorted(active) if f not in exceptions]
    problems: list[tuple[str, str]] = []
    for position, family in enumerate(unexcepted, start=1):
        if position <= MAX_ACTIVE_FAMILIES:
            continue
        for key in active[family]:
            problems.append((key, f"family {family!r} would be active family #{position}; at most "
                                  f"{MAX_ACTIVE_FAMILIES} new active families are allowed without an "
                                  "owner_exception document (#96)"))
    return problems


def _amendable_field(field: Any) -> bool:
    if not isinstance(field, str):
        return False
    if field in FROZEN_FIELDS:
        return True
    parts = field.split(".")
    return len(parts) >= 2 and parts[0] == "protocol" and (parts[1] in PROTOCOL_TABLES or parts[1] in PROTOCOL_TOP)
