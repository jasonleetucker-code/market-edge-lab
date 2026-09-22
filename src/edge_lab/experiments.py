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

    periods = d.get("periods")
    if isinstance(periods, dict):
        for key in PERIOD_KEYS:
            if key not in periods:
                problems.append(f"[periods] missing '{key}' (use \"TBD\" while DRAFT)")

    if exp.status in LOCKED:
        # Once preregistered, nothing the decision depends on may be left open.
        for label in _undefined_locked_fields(d):
            problems.append(f"{exp.status} experiment has undefined '{label}' (still TBD)")

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

    return problems


def _is_tbd(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper().startswith("TBD")


def _undefined_locked_fields(d: dict[str, Any]) -> list[str]:
    labels = [key for key in ("decision_time", "model") if _is_tbd(d.get(key))]
    for table in ("periods", "costs", "execution"):
        section = d.get(table)
        if isinstance(section, dict):
            labels += [f"{table}.{k}" for k, v in section.items() if _is_tbd(v)]
    periods = d.get("periods")
    if isinstance(periods, dict):
        labels += [f"periods.{k}" for k in PERIOD_KEYS if k not in periods]
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
