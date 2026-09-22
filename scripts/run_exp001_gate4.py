"""EXP-001 Gate 4: validation selection, then the single Stage A evaluation on test.

    python scripts/run_exp001_gate4.py --phase validation   # writes gate4/validation_selection.json
    python scripts/run_exp001_gate4.py --phase test         # ONCE: writes gate4/stage_a_result.json, REPORT.md

Both phases refuse to run on a working tree with modified tracked files (so the recorded
code commit is the code that ran), without the Gate 4 pre-validation amendments in
experiment.toml, or on a dataset whose SHA-256 differs from the frozen one.

The validation phase reads only train and validation rows and refuses if its output exists.
The test phase refuses unless validation_selection.json is committed and unmodified, and
unless re-deriving it from the current code and data gives the committed numbers. It
refuses if a Stage A result or a test-opening record exists. It records the opening
(gate4/test_split_opened.json) before reading any test row, so it cannot run twice.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge_lab import exp001_baseline as b  # noqa: E402
from edge_lab import experiments  # noqa: E402

EXP = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market"
DATASET = EXP / "gate3" / "dataset.csv"
GATE4 = EXP / "gate4"
MANIFEST = EXP / "experiment.toml"
AMENDMENT_PREFIX = "Gate 4 pre-validation"
REQUIRED_AMENDMENTS = 6


class Refused(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def git_head(root: Path = ROOT) -> str:
    return _git("rev-parse", "HEAD", root=root).strip()


def require_clean_tracked_tree(root: Path = ROOT) -> None:
    dirty = _git("status", "--porcelain", "--untracked-files=no", root=root).strip()
    if dirty:
        raise Refused(f"tracked files are modified; commit first so the code commit is honest:\n{dirty}")


def require_committed_unmodified(path: Path, root: Path = ROOT) -> None:
    rel = path.relative_to(root).as_posix()
    try:
        _git("ls-files", "--error-unmatch", "--", rel, root=root)
    except subprocess.CalledProcessError:
        raise Refused(f"{rel} is not committed") from None
    if _git("status", "--porcelain", "--", rel, root=root).strip():
        raise Refused(f"{rel} differs from the committed version")


def require_amendments(manifest: Path = MANIFEST) -> None:
    exp = experiments.load(manifest)
    problems = experiments.validate(exp)
    if problems:
        raise Refused(f"experiment manifest invalid: {problems}")
    ours = [a for a in exp.data.get("amendments", []) if str(a.get("change", "")).startswith(AMENDMENT_PREFIX)]
    if len(ours) < REQUIRED_AMENDMENTS:
        raise Refused(f"expected {REQUIRED_AMENDMENTS} '{AMENDMENT_PREFIX}' amendments, found {len(ours)}")


def verified_dataset_sha(dataset: Path) -> str:
    sha = b.dataset_sha256(b.dataset_text(dataset))
    if sha != b.DATASET_SHA256:
        raise Refused(f"dataset sha256 {sha} is not the frozen {b.DATASET_SHA256}")
    return sha


# ---------------------------------------------------------------------------
# Phases (pure computation lives in edge_lab.exp001_baseline)
# ---------------------------------------------------------------------------
def validation_payload(dataset: Path = DATASET, *, expected_sha: str | None = b.DATASET_SHA256) -> dict[str, Any]:
    """Train + validation rows only. Never touches the test split."""
    sha = b.dataset_sha256(b.dataset_text(dataset))
    if expected_sha is not None and sha != expected_sha:
        raise Refused(f"dataset sha256 {sha} is not the frozen {expected_sha}")
    train = b.load_split(dataset, "train")
    validation = b.load_split(dataset, "validation")
    return b.compute_validation(train, validation, dataset_sha=sha)


def stage_a_payload(dataset: Path, test_days: list, selected_variant: str) -> dict[str, Any]:
    sha = b.dataset_sha256(b.dataset_text(dataset))
    fit = b.load_fit_window(dataset, b.FIT_SPLITS)
    return b.compute_stage_a(fit, test_days, selected_variant=selected_variant, dataset_sha=sha)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def run_validation(*, dataset: Path, gate4: Path, provenance: dict[str, Any],
                   expected_sha: str | None = b.DATASET_SHA256) -> dict[str, Any]:
    target = gate4 / b.VALIDATION_FILE
    if target.exists():
        raise Refused(f"{target} exists; the validation selection is made once")
    payload = validation_payload(dataset, expected_sha=expected_sha)
    payload["provenance"] = provenance
    gate4.mkdir(parents=True, exist_ok=True)
    _write(target, b.to_json(payload))
    return payload


def run_test(*, dataset: Path, gate4: Path, provenance: dict[str, Any],
             expected_sha: str | None = b.DATASET_SHA256) -> dict[str, Any]:
    selection_path = gate4 / b.VALIDATION_FILE
    if not selection_path.exists():
        raise Refused("run --phase validation and commit its output first")
    if (gate4 / b.STAGE_A_FILE).exists():
        raise Refused("a Stage A result exists; the test split is evaluated once")
    committed = json.loads(selection_path.read_text(encoding="utf-8"))
    stored = {k: v for k, v in committed.items() if k != "provenance"}
    if validation_payload(dataset, expected_sha=expected_sha) != stored:
        raise Refused("re-deriving the validation selection does not reproduce the committed file")
    test_days = b.open_test_once(dataset, gate4, opened_by=provenance)
    result = stage_a_payload(dataset, test_days, committed["selected_variant"])
    result["provenance"] = provenance
    _write(gate4 / b.STAGE_A_FILE, b.to_json(result))
    _write(gate4 / "REPORT.md", render_report(committed, result))
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _f(x: float, digits: int = 4) -> str:
    return f"{x:+.{digits}f}"


def _ci(block: dict[str, float]) -> str:
    return f"{_f(block['mean'])} [{_f(block['ci_lower'])}, {_f(block['ci_upper'])}]"


def render_report(validation: dict[str, Any], stage_a: dict[str, Any]) -> str:
    v, a = validation, stage_a
    verdict = a["verdict"]
    c1, c2 = a["condition_1_log_score_vs_r0"], a["condition_2_pit_coverage"]
    pit = a["pit"]
    d = v["difference_v2_minus_v1"]
    vs_r0, vs_r1 = a["difference_model_minus_r0"], a["difference_model_minus_r1"]
    n = a["n_test_days"]
    bs = a["bootstrap"]
    if verdict == "PASS":
        verdict_text = [
            "**Stage A: PASS.** Both preregistered conditions hold on the test split.",
            "",
            "This shows only that the forecast-derived probabilities were informative relative to",
            "monthly climatology and calibrated on the held-out period. **It is not evidence of a",
            "trading edge.** Stage B (prospective shadow trading against executable prices) is",
            "pending and needs owner-approved scheduled collection.",
        ]
    else:
        failed = [name for name, c in (("condition 1 (log score vs R0)", c1), ("condition 2 (PIT coverage)", c2))
                  if not c["passed"]]
        verdict_text = [
            f"**Stage A: FAIL.** Failed: {', '.join(failed)}.",
            "",
            "Per the frozen failure criteria, Stage B is not run for this model. Nothing in the",
            "frozen EXP-001 specification is changed in response. Any follow-up model is a",
            "separately preregistered EXP-002.",
        ]
    lines = [
        "# EXP-001 Gate 4 report: baseline fit, validation selection, Stage A (generated)",
        "",
        "Generated by `scripts/run_exp001_gate4.py` from `validation_selection.json` and",
        "`stage_a_result.json`; the JSON files hold every number at full precision.",
        "",
        f"- Dataset: `gate3/dataset.csv` SHA-256 `{a['dataset_sha256']}` (frozen).",
        f"- Validation phase: code commit `{v['provenance']['code_commit']}`, run {v['provenance']['run_at_utc']}.",
        f"- Test phase (single opening): code commit `{a['provenance']['code_commit']}`, "
        f"run {a['provenance']['run_at_utc']}.",
        "- Specification: `experiment.toml` (frozen in `preregistration.json`), `gate3/DESIGN.md`",
        "  §5-6, and the six dated `Gate 4 pre-validation` amendments recorded before any",
        "  validation or test score was computed.",
        "",
        "## Verdict",
        "",
        *verdict_text,
        "",
        "## 1. Fit on train (2017-01-01..2022-12-31)",
        "",
        f"Usable train days: {v['fit_window']['n_days']} ({v['fit_window']['first']}..{v['fit_window']['last']}).",
        f"V2 season sizes: {json.dumps(v['fit_counts']['V2'], sort_keys=True)}.",
        "",
        "| variant | train in-sample mean log score |",
        "|---|---|",
        *[f"| {name} | {_f(v['train_in_sample_mean_log_score'][name])} |" for name in b.VARIANTS],
        "",
        "In-sample scores describe the fit only; they select nothing.",
        "",
        "## 2. Validation comparison (2023-01-01..2024-12-31) and selection",
        "",
        f"All models fitted on train; scored on {v['scored_window']['n_days']} usable validation days.",
        "",
        "| model | validation mean log score |",
        "|---|---|",
        *[f"| {name} | {_f(v['validation_mean_log_score'][name])} |" for name in ("V1", "V2", "R0", "R1")],
        "",
        f"d = lnP_V2 - lnP_V1: mean and 95% block-bootstrap interval {_ci(d)} (n = {d['n_days']}).",
        "",
        f"Rule: {v['rule']}.",
        "",
        f"**Selected variant: {v['selected_variant']}.**",
        "",
        "## 3. Stage A on test (2025-01-01..2026-09-21), evaluated once",
        "",
        f"The selected variant ({a['selected_variant']}), R0 and R1 were refitted once on usable train +",
        f"validation days ({a['fit_window']['n_days']} days, {a['fit_window']['first']}..{a['fit_window']['last']})",
        f"and scored on {n} usable test days ({a['test_window']['first']}..{a['test_window']['last']}).",
        "",
        "| model | mean log score | mean log loss | mean Brier (reported only) |",
        "|---|---|---|---|",
        *[
            f"| {label} | {_f(a['mean_log_score'][key])} | {a['mean_log_loss'][key]:.4f} | {a['mean_brier'][key]:.4f} |"
            for label, key in ((f"model ({a['selected_variant']})", "model"), ("R0 monthly climatology", "R0"),
                               ("R1 Gaussian (reported only)", "R1"))
        ],
        "",
        "Per-day log-score differences, mean and 95% block-bootstrap interval:",
        "",
        f"- model - R0: {_ci(vs_r0)} (Stage A condition 1)",
        f"- model - R1: {_ci(vs_r1)} (reported only, not a criterion)",
        "",
        "## 4. Calibration (randomized PIT, same clamped pmf as scoring)",
        "",
        f"- Central coverage, fraction with {pit['low']} <= u <= {pit['high']}: **{pit['coverage']:.4f}** "
        f"({pit['n_inside']}/{n}); required range [{c2['coverage_range'][0]}, {c2['coverage_range'][1]}].",
        f"- u < {pit['low']}: {pit['n_below_low']} days; u > {pit['high']}: {pit['n_above_high']} days "
        "(a calibrated forecast puts about 10% in each).",
        f"- v drawn by `stats.randomized_pit` with seed {pit['seed']} in date order.",
        "",
        "## 5. Stage A criterion (exact) and outcome",
        "",
        f"1. {c1['criterion']}: **{'met' if c1['passed'] else 'NOT met'}** "
        f"(mean {_f(vs_r0['mean'])}, lower bound {_f(vs_r0['ci_lower'])}).",
        f"2. {c2['criterion']}: **{'met' if c2['passed'] else 'NOT met'}** (coverage {pit['coverage']:.4f}).",
        "",
        f"PASS iff both conditions are met. **Verdict: {verdict}.**",
        "",
        f"Bootstrap everywhere: `{bs['function']}` (block {bs['block']}, {bs['resamples']} resamples, "
        f"seed {bs['seed']}, alpha {bs['alpha']}), per-day values in date order.",
        "",
        "## 6. Scoring details",
        "",
        f"- Test errors |k| > 20 scored at k = +-20: {a['n_test_errors_clamped']}.",
        f"- R0 support (fit window) {a['r0_support'][0]}..{a['r0_support'][1]} °F; test labels outside it "
        f"(scored at the nearest end): {a['n_test_labels_outside_r0_support']}.",
        f"- R1 parameters from raw fit-window errors: mu = {a['r1_params']['mu']:.4f} °F, "
        f"sigma = {a['r1_params']['sigma']:.4f} °F; probabilities floored at 1e-9.",
        "- Brier score per day = 1 - 2 P(scored outcome) + sum_y P(y)^2 over the model's support",
        "  (R1: integers f +- 60). Log loss = - mean log score. Both are reported only.",
        "",
        "## 7. Limitations",
        "",
        "- **Stage A pass or fail is about probabilities, not money.** No historical market prices",
        "  or order books exist for us, so nothing here compares the model with the market. A pass",
        "  would not be evidence of an edge.",
        "- **Forecast age regime shift.** PFMOKX issuance thinned from mid-2025, so the chosen",
        "  forecast is older at the decision time in the test years (median about 2.8 h in 2025 and",
        "  3.5 h in 2026 versus 2.4-2.5 h in 2017-2024; `gate3/QUALITY.md`). This was disclosed",
        "  before any error was computed and is not adjusted for; it is part of what Stage A tests.",
        "- **Test protection is procedural.** `gate3/dataset.csv` contains the test forecasts and",
        "  labels. The code refuses test rows outside a single guarded opening, and",
        "  `gate4/test_split_opened.json` records that opening, but nothing cryptographic prevents",
        "  an earlier look. The git history is the evidence of the order of events.",
        "- **Fee coefficient 0.07 is unverified** against Kalshi's fee-schedule PDF. It is",
        "  irrelevant to Stage A (no trades are simulated) and must be re-verified before Stage B.",
        f"- **Sample size.** {n} test days, serially correlated; the block bootstrap (7-day blocks)",
        "  accounts for short-range dependence only.",
        "- One series, one decision time, one forecast source; no other models were tried.",
        "",
        "## 8. Reproduction",
        "",
        "```",
        "python -m pytest tests/test_exp001_baseline.py   # recomputes both JSON files from code + data",
        "python scripts/run_exp001_gate4.py --phase validation   # refuses: output exists (run once)",
        "python scripts/run_exp001_gate4.py --phase test         # refuses: test split already opened",
        "```",
        "",
        "The reproducibility test recomputes `validation_selection.json` and `stage_a_result.json`",
        "through the pure functions in `edge_lab.exp001_baseline` (not the guarded writer) and",
        "checks them against the committed files.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def provenance(phase: str) -> dict[str, Any]:
    return {
        "code_commit": git_head(),
        "command": f"python scripts/run_exp001_gate4.py --phase {phase}",
        "python": platform.python_version(),
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", choices=("validation", "test"), required=True)
    args = ap.parse_args(argv)
    try:
        require_clean_tracked_tree()
        require_amendments()
        verified_dataset_sha(DATASET)
        if args.phase == "validation":
            payload = run_validation(dataset=DATASET, gate4=GATE4, provenance=provenance("validation"))
            d = payload["difference_v2_minus_v1"]
            print(f"validation: d mean {d['mean']:+.5f} CI [{d['ci_lower']:+.5f}, {d['ci_upper']:+.5f}] "
                  f"-> selected {payload['selected_variant']}")
        else:
            require_committed_unmodified(GATE4 / b.VALIDATION_FILE)
            result = run_test(dataset=DATASET, gate4=GATE4, provenance=provenance("test"))
            print(f"Stage A verdict: {result['verdict']}")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
