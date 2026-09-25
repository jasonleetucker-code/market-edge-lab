"""scripts/research_power_sensitivity.py: stated-assumption ranges, not a power analysis (EXP-002 §A.G)."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "research_power_sensitivity.py"


def _load():
    # scripts/ is not a package: import by file location (the tests/test_agent_context.py convention).
    spec = importlib.util.spec_from_file_location("research_power_sensitivity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


ps = _load()


def test_the_normal_quantiles_and_the_textbook_sample_size():
    assert ps.z(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert ps.z(0.80) == pytest.approx(0.8416, abs=1e-4)
    # (1.645 + 0.842)^2 * (0.5 / 0.05)^2 ~= 618.3 independent units.
    assert ps.effective_n(0.05, 0.5) == pytest.approx(618.26, abs=0.05)
    with pytest.raises(ValueError):
        ps.effective_n(0, 0.5)
    with pytest.raises(ValueError):
        ps.z(1.0)


def test_week_dependence_inflates_and_sets_a_floor_that_more_games_cannot_buy():
    n = ps.effective_n(0.005, 0.02)
    assert ps.weeks_required(0.005, 0.02, 0.0, 10) == pytest.approx(n / 10)
    assert ps.weeks_required(0.005, 0.02, 0.05, 10) > ps.weeks_required(0.005, 0.02, 0.0, 10)
    # With week-level correlation, weeks needed decreases in games per week but never below n * icc.
    weeks = [ps.weeks_required(0.005, 0.02, 0.05, m) for m in (5, 20, 100, 10_000)]
    assert weeks == sorted(weeks, reverse=True)
    assert all(w >= n * 0.05 for w in weeks) and weeks[-1] == pytest.approx(n * 0.05, rel=0.01)


def test_mde_inverts_weeks_required():
    for sd, icc, m in ((0.02, 0.05, 9.0), (0.5, 0.0, 2.7), (0.04, 0.1, 13.5), (0.5, 0.02, 0.9)):
        w = ps.weeks_required(0.01, sd, icc, m)
        assert ps.mde(w, sd, icc, m) == pytest.approx(0.01, rel=1e-9)


def test_no_analysed_game_is_no_design_not_zero_weeks():
    assert ps.weeks_required(0.01, 0.02, 0.05, 0.0) is None
    assert ps.mde(10, 0.02, 0.05, 0.0) is None
    with pytest.raises(ValueError):
        ps.units_per_week(15, 1.2, 1.0)


def test_the_grid_is_deterministic_labelled_and_shows_the_hold_to_settlement_endpoint_is_out_of_reach():
    rows = ps.grid()
    assert rows == ps.grid()
    summary = ps.summary(rows)
    hold = summary["hold-to-settlement P&L per contract (secondary)"]
    markout = summary["markout (primary, PROPOSED)"]
    # Under every stated assumption the hold-to-settlement P&L needs more than 100 weeks (about 6 seasons).
    assert hold["feasible_in_horizon"] == 0 and hold["min_weeks"] > 100
    # The markout endpoint fits the season under some assumptions and not others: a range, not a number.
    assert 0 < markout["feasible_in_horizon"] < markout["scenarios"]
    assert all(r.weeks_floor_icc == pytest.approx(r.n_eff * r.icc, abs=0.01) for r in rows)


def test_the_cli_prints_the_label_and_valid_json(capsys):
    assert ps.main([]) == 0
    text = capsys.readouterr().out
    assert text.startswith(f"# {ps.LABEL}") and "NOT A POWER ANALYSIS" in text
    assert ps.main(["--json", "--horizon-weeks", "4"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == ps.VERSION and data["rows"] and all(r["feasible_in_weeks"] == 4 for r in data["rows"])
    assert all(math.isfinite(r["n_eff"]) for r in data["rows"])


def test_the_script_is_stdlib_only_and_has_no_network_path():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"__future__", "argparse", "json", "math", "dataclasses", "statistics"}
