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
            elif "field" in amendment and amendment["field"] not in FROZEN_FIELDS:
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
    """Validate every manifest under `root`, including cross-manifest ID uniqueness."""
    results: dict[str, list[str]] = {}
    seen: dict[str, Path] = {}
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
    return problems


def changed_baselines(base_ref: str, *, repo: Path) -> list[str]:
    """Baseline files modified or deleted relative to `base_ref` (additions are fine)."""
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--name-status", base_ref, "HEAD", "--", f"experiments/*/{BASELINE_NAME}"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line and not line.startswith("A")]
