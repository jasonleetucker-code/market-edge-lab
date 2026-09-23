"""EXP-001 Gate 4: the frozen baseline, its references and the Stage A evaluation.

Implements exactly what `experiments/EXP-001-kxhighny-nws-vs-market/experiment.toml`
(frozen in `preregistration.json`) and `gate3/DESIGN.md` §5-6 specify, with the dated
Gate 4 `[[amendments]]` that resolve ambiguities before any validation or test score was
computed. Nothing here is tuned: there are no free parameters beyond the frozen constants.

Notation: f = forecast_max_f, y = label_f (integer °F), k = y - f, k_c = clamp(k, -20, 20).

- Model: P(y = f + k) = (n_k + 0.5) / (N + 0.5 * 41), k in [-20, 20], n_k counted with
  clamped errors; V1 pooled, V2 one pmf per meteorological season of D. Score ln P(k_c).
- R0: monthly climatology, add-0.5 over the integer support [min y - 10, max y + 10] of the
  whole fit window (same support for every month); outcomes outside scored at the nearest end.
- R1: y ~ N(f + mu, sigma^2) with mu, sigma the fit-window mean and population sd of the raw
  (unclamped) k; mass on [y - 0.5, y + 0.5] via math.erf, floored at 1e-9. Reported only.
- Every interval: `stats.block_bootstrap_mean_ci` with the frozen defaults.

Test-split protection is procedural (dataset.csv contains test rows). `load_split` refuses
the test split. Test rows are reachable only through `open_test_once`, which refuses if the
split was already opened or a Stage A result exists, and through
`load_test_for_reproduction`, which works only after a committed result exists.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import stats
from .describe_exp001 import SEASONS

EXPERIMENT_ID = "EXP-001"
# The frozen dataset (preregistration.json pins this; tests assert they are equal).
DATASET_SHA256 = "1794b23cd519a4c4a952700dc97530df0f0452f070962c0cb7500fd1afcef51a"

K_MIN, K_MAX = -20, 20
K_SIZE = K_MAX - K_MIN + 1  # 41
PSEUDOCOUNT = 0.5
R0_MARGIN = 10
R1_FLOOR = 1e-9
R1_BRIER_HALF_WIDTH = 60  # R1 Brier support: integers f - 60 .. f + 60 (amendment, reporting only)

SEED = stats.PREREGISTERED_SEED
BLOCK = 7
RESAMPLES = 10_000
ALPHA = 0.05
PIT_LOW, PIT_HIGH = 0.10, 0.90
COVERAGE_MIN, COVERAGE_MAX = 0.75, 0.85  # inclusive on both ends (amendment)

VARIANTS = ("V1", "V2")
FIT_SPLITS = ("train", "validation")
TEST_SPLIT = "test"
ALL_SPLITS = FIT_SPLITS + (TEST_SPLIT,)

VALIDATION_FILE = "validation_selection.json"
STAGE_A_FILE = "stage_a_result.json"
TEST_OPENED_FILE = "test_split_opened.json"

SELECTION_RULE = (
    "per validation day in date order d = lnP_V2 - lnP_V1 (both fitted on usable train days); "
    "choose V2 only if mean(d) > 0 and the 95% block-bootstrap lower bound > 0 (strict); "
    "otherwise V1 (ties -> V1)"
)
CONDITION_1 = (
    "mean(lnP_model - lnP_R0) over usable test days > 0 and its 95% block-bootstrap lower bound > 0 "
    "(strict inequalities)"
)
CONDITION_2 = (
    "randomized-PIT central coverage stats.central_coverage(pit, 0.10, 0.90) within [0.75, 0.85] "
    "(inclusive), u = F(y-1) + v*P(y) from the same clamped pmf used for scoring, v from "
    "stats.randomized_pit(seed 20260922) in date order"
)


class TestSplitRefused(PermissionError):
    """Raised when code tries to reach the test split outside the single guarded opening."""

    __test__ = False  # not a pytest test class


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Day:
    target_date: str  # YYYY-MM-DD
    split: str
    f: int  # forecast_max_f
    y: int  # label_f

    @property
    def month(self) -> int:
        return int(self.target_date[5:7])

    @property
    def season(self) -> str:
        return SEASONS[self.month]

    @property
    def k(self) -> int:
        return self.y - self.f

    @property
    def k_clamped(self) -> int:
        return clamp_k(self.k)


def dataset_text(path: Path | str) -> str:
    # Universal newlines: a CRLF checkout hashes and parses like the committed LF bytes.
    return Path(path).read_text(encoding="utf-8")


def dataset_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _to_day(row: dict[str, str]) -> Day:
    """The only place a row's forecast and label are read."""
    return Day(target_date=row["target_date"], split=row["split"],
               f=int(row["forecast_max_f"]), y=int(row["label_f"]))


def _days(csv_text: str, splits: Iterable[str]) -> list[Day]:
    """Usable rows of the given splits, in date order. Rows of any other split are dropped
    before any of their values is parsed."""
    wanted = frozenset(splits)
    unknown = wanted - set(ALL_SPLITS)
    if unknown:
        raise ValueError(f"unknown split(s) {sorted(unknown)}")
    out: list[Day] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row["split"] not in wanted:
            continue
        if row["usable"] not in ("true", "false"):
            raise ValueError(f"{row['target_date']}: usable must be 'true' or 'false'")
        if row["usable"] != "true":
            continue
        out.append(_to_day(row))
    out.sort(key=lambda d: d.target_date)
    dates = [d.target_date for d in out]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate target dates")
    return out


def load_split(path: Path | str, split: str) -> list[Day]:
    """Usable rows of `split` (train or validation) in date order. Refuses the test split."""
    if split == TEST_SPLIT:
        raise TestSplitRefused("the test split is reachable only through open_test_once()")
    if split not in FIT_SPLITS:
        raise ValueError(f"unknown split {split!r}")
    return _days(dataset_text(path), [split])


def load_fit_window(path: Path | str, splits: Sequence[str]) -> list[Day]:
    """Usable rows of several fit splits (never test), in date order."""
    days: list[Day] = []
    for split in splits:
        days += load_split(path, split)
    return sorted(days, key=lambda d: d.target_date)


def open_test_once(path: Path | str, gate4_dir: Path | str, *, opened_by: dict[str, Any]) -> list[Day]:
    """Open the test split, once. Refuses if a Stage A result or an opening record exists.

    The opening record (`test_split_opened.json`) is created exclusively *before* any test
    row is read, so a crash after this point cannot be followed by a silent second opening.
    """
    gate4 = Path(gate4_dir)
    if (gate4 / STAGE_A_FILE).exists():
        raise TestSplitRefused(f"{gate4 / STAGE_A_FILE} exists: the test split was already evaluated")
    marker = gate4 / TEST_OPENED_FILE
    record = {"opened_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **opened_by}
    try:
        with marker.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
    except FileExistsError:
        raise TestSplitRefused(f"{marker} exists: the test split was already opened") from None
    return _days(dataset_text(path), [TEST_SPLIT])


def load_test_for_reproduction(path: Path | str, gate4_dir: Path | str) -> list[Day]:
    """Test rows for recomputing an already committed Stage A result (never a first look)."""
    if not (Path(gate4_dir) / STAGE_A_FILE).exists():
        raise TestSplitRefused("no committed Stage A result: use open_test_once() for the single evaluation")
    return _days(dataset_text(path), [TEST_SPLIT])


# ---------------------------------------------------------------------------
# Model: empirical integer error pmf (V1 pooled, V2 seasonal)
# ---------------------------------------------------------------------------
def clamp_k(k: int) -> int:
    return max(K_MIN, min(K_MAX, k))


def error_pmf(days: Sequence[Day]) -> tuple[float, ...]:
    """(n_k + 0.5) / (N + 0.5 * 41) for k = -20..20 (index k + 20), errors clamped."""
    counts = [0] * K_SIZE
    for d in days:
        counts[d.k_clamped - K_MIN] += 1
    denominator = len(days) + PSEUDOCOUNT * K_SIZE
    return tuple((c + PSEUDOCOUNT) / denominator for c in counts)


@dataclass(frozen=True)
class ErrorModel:
    variant: str
    pmfs: dict[str, tuple[float, ...]]  # "ALL" for V1; season name for V2
    n_fit: dict[str, int]

    def pmf_for(self, day: Day) -> tuple[float, ...]:
        return self.pmfs["ALL" if self.variant == "V1" else day.season]


def fit_model(variant: str, days: Sequence[Day]) -> ErrorModel:
    if variant == "V1":
        return ErrorModel("V1", {"ALL": error_pmf(days)}, {"ALL": len(days)})
    if variant == "V2":
        groups = {s: [d for d in days if d.season == s] for s in ("DJF", "MAM", "JJA", "SON")}
        return ErrorModel("V2", {s: error_pmf(g) for s, g in groups.items()},
                          {s: len(g) for s, g in groups.items()})
    raise ValueError(f"unknown variant {variant!r}; the spec has exactly V1 and V2")


def pmf_log_score(pmf: Sequence[float], day: Day) -> float:
    return math.log(pmf[day.k_clamped - K_MIN])


def pmf_pit_components(pmf: Sequence[float], day: Day) -> tuple[float, float]:
    """(F(y-1), P(y)) from the clamped pmf: F(y-1) = fsum of the pmf over k < k_c, ascending."""
    i = day.k_clamped - K_MIN
    return math.fsum(pmf[:i]), pmf[i]


def brier(probabilities: Sequence[float], observed_index: int) -> float:
    """Multi-category Brier score 1 - 2 P(observed) + sum P(y)^2 (reported only)."""
    return 1.0 - 2.0 * probabilities[observed_index] + math.fsum(p * p for p in probabilities)


def pmf_brier(pmf: Sequence[float], day: Day) -> float:
    return brier(pmf, day.k_clamped - K_MIN)


# ---------------------------------------------------------------------------
# R0: monthly climatology
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Climatology:
    lo: int
    hi: int
    pmfs: dict[int, tuple[float, ...]]  # month -> P over lo..hi
    n_fit: dict[int, int]

    @property
    def size(self) -> int:
        return self.hi - self.lo + 1

    def index(self, y: int) -> int:
        """Outcome index on the support; outside the support scored at the nearest end."""
        return max(self.lo, min(self.hi, y)) - self.lo

    def prob(self, day: Day) -> float:
        return self.pmfs[day.month][self.index(day.y)]

    def log_score(self, day: Day) -> float:
        return math.log(self.prob(day))

    def brier(self, day: Day) -> float:
        return brier(self.pmfs[day.month], self.index(day.y))


def fit_r0(days: Sequence[Day]) -> Climatology:
    if not days:
        raise ValueError("R0 needs at least one fit day")
    lo = min(d.y for d in days) - R0_MARGIN
    hi = max(d.y for d in days) + R0_MARGIN
    size = hi - lo + 1
    pmfs: dict[int, tuple[float, ...]] = {}
    n_fit: dict[int, int] = {}
    for month in range(1, 13):
        counts = [0] * size
        month_days = [d for d in days if d.month == month]
        for d in month_days:
            counts[d.y - lo] += 1
        denominator = len(month_days) + PSEUDOCOUNT * size
        pmfs[month] = tuple((c + PSEUDOCOUNT) / denominator for c in counts)
        n_fit[month] = len(month_days)
    return Climatology(lo, hi, pmfs, n_fit)


# ---------------------------------------------------------------------------
# R1: discretized Gaussian (reported only)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Gaussian:
    mu: float
    sigma: float

    def prob(self, f: int, y: int) -> float:
        centre = f + self.mu
        scale = self.sigma * math.sqrt(2.0)
        upper = 0.5 * (1.0 + math.erf((y + 0.5 - centre) / scale))
        lower = 0.5 * (1.0 + math.erf((y - 0.5 - centre) / scale))
        return max(upper - lower, R1_FLOOR)

    def log_score(self, day: Day) -> float:
        return math.log(self.prob(day.f, day.y))

    def brier(self, day: Day) -> float:
        support = range(day.f - R1_BRIER_HALF_WIDTH, day.f + R1_BRIER_HALF_WIDTH + 1)
        probabilities = [self.prob(day.f, y) for y in support]
        observed = day.y
        if support.start <= observed < support.stop:
            return brier(probabilities, observed - support.start)
        # Outcome outside f +- 60: the observed category is not on the reported support.
        return 1.0 - 2.0 * self.prob(day.f, observed) + math.fsum(p * p for p in probabilities)


def fit_r1(days: Sequence[Day]) -> Gaussian:
    """mu, sigma = mean and population sd of the raw (unclamped) errors k (amendment)."""
    if not days:
        raise ValueError("R1 needs at least one fit day")
    ks = [d.k for d in days]
    mu = math.fsum(ks) / len(ks)
    sigma = math.sqrt(math.fsum((k - mu) ** 2 for k in ks) / len(ks))
    if sigma <= 0:
        raise ValueError("R1 undefined: zero error variance in the fit window")
    return Gaussian(mu, sigma)


# ---------------------------------------------------------------------------
# Summaries and decisions
# ---------------------------------------------------------------------------
def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("no values")
    return math.fsum(values) / len(values)


def bootstrap(values: Sequence[float]) -> dict[str, float]:
    m, lower, upper = stats.block_bootstrap_mean_ci(values, block=BLOCK, resamples=RESAMPLES, seed=SEED, alpha=ALPHA)
    return {"mean": m, "ci_lower": lower, "ci_upper": upper}


def select_variant(d_mean: float, d_lower: float) -> str:
    """Frozen rule: V2 only if mean(d) > 0 and lower bound > 0 (strict); else V1."""
    return "V2" if (d_mean > 0 and d_lower > 0) else "V1"


def condition_1(diff_mean: float, diff_lower: float) -> bool:
    return diff_mean > 0 and diff_lower > 0


def condition_2(coverage: float) -> bool:
    return COVERAGE_MIN <= coverage <= COVERAGE_MAX


def _window(days: Sequence[Day]) -> dict[str, Any]:
    return {
        "splits": sorted({d.split for d in days}),
        "first": days[0].target_date,
        "last": days[-1].target_date,
        "n_days": len(days),
    }


def _bootstrap_settings() -> dict[str, Any]:
    return {"function": "edge_lab.stats.block_bootstrap_mean_ci", "block": BLOCK, "resamples": RESAMPLES,
            "seed": SEED, "alpha": ALPHA}


def _require(days: Sequence[Day], splits: set[str], label: str) -> None:
    if not days:
        raise ValueError(f"{label}: no usable days")
    found = {d.split for d in days}
    if found != splits:
        raise ValueError(f"{label}: expected splits {sorted(splits)}, got {sorted(found)}")
    dates = [d.target_date for d in days]
    if dates != sorted(dates):
        raise ValueError(f"{label}: days not in date order")


def compute_validation(train: Sequence[Day], validation: Sequence[Day], *, dataset_sha: str) -> dict[str, Any]:
    """Fit V1/V2 (and R0/R1) on train, score validation, apply the frozen selection rule."""
    _require(train, {"train"}, "train")
    _require(validation, {"validation"}, "validation")
    models = {v: fit_model(v, train) for v in VARIANTS}
    r0, r1 = fit_r0(train), fit_r1(train)
    scores = {v: [pmf_log_score(models[v].pmf_for(d), d) for d in validation] for v in VARIANTS}
    scores["R0"] = [r0.log_score(d) for d in validation]
    scores["R1"] = [r1.log_score(d) for d in validation]
    d_values = [b - a for a, b in zip(scores["V1"], scores["V2"])]
    diff = bootstrap(d_values)
    selected = select_variant(diff["mean"], diff["ci_lower"])
    return {
        "experiment_id": EXPERIMENT_ID,
        "phase": "validation",
        "dataset_sha256": dataset_sha,
        "fit_window": _window(train),
        "scored_window": _window(validation),
        "train_in_sample_mean_log_score": {
            v: mean([pmf_log_score(models[v].pmf_for(d), d) for d in train]) for v in VARIANTS
        },
        "validation_mean_log_score": {name: mean(values) for name, values in scores.items()},
        "difference_v2_minus_v1": {**diff, "n_days": len(d_values)},
        "bootstrap": _bootstrap_settings(),
        "rule": SELECTION_RULE,
        "selected_variant": selected,
        "fit_counts": {"V1": models["V1"].n_fit, "V2": models["V2"].n_fit},
        "r0_support": [r0.lo, r0.hi],
        "r1_params": {"mu": r1.mu, "sigma": r1.sigma},
    }


def compute_stage_a(fit: Sequence[Day], test: Sequence[Day], *, selected_variant: str, dataset_sha: str) -> dict[str, Any]:
    """Refit the selected variant (and R0/R1) on train+validation; score the test days once."""
    _require(fit, {"train", "validation"}, "fit window")
    _require(test, {"test"}, "test")
    if fit[-1].target_date >= test[0].target_date:
        raise ValueError("fit window overlaps the test period")
    model = fit_model(selected_variant, fit)
    r0, r1 = fit_r0(fit), fit_r1(fit)

    log_model = [pmf_log_score(model.pmf_for(d), d) for d in test]
    log_r0 = [r0.log_score(d) for d in test]
    log_r1 = [r1.log_score(d) for d in test]
    brier_scores = {
        "model": mean([pmf_brier(model.pmf_for(d), d) for d in test]),
        "R0": mean([r0.brier(d) for d in test]),
        "R1": mean([r1.brier(d) for d in test]),
    }
    vs_r0 = bootstrap([m - r for m, r in zip(log_model, log_r0)])
    vs_r1 = bootstrap([m - r for m, r in zip(log_model, log_r1)])

    pit = stats.randomized_pit([pmf_pit_components(model.pmf_for(d), d) for d in test], seed=SEED)
    coverage = stats.central_coverage(pit, PIT_LOW, PIT_HIGH)
    passed_1 = condition_1(vs_r0["mean"], vs_r0["ci_lower"])
    passed_2 = condition_2(coverage)
    mean_scores = {"model": mean(log_model), "R0": mean(log_r0), "R1": mean(log_r1)}
    return {
        "experiment_id": EXPERIMENT_ID,
        "phase": "stage_a",
        "dataset_sha256": dataset_sha,
        "selected_variant": selected_variant,
        "fit_window": _window(fit),
        "test_window": _window(test),
        "n_test_days": len(test),
        "mean_log_score": mean_scores,
        "mean_log_loss": {name: -value for name, value in mean_scores.items()},
        "mean_brier": brier_scores,
        "difference_model_minus_r0": vs_r0,
        "difference_model_minus_r1": vs_r1,
        "pit": {
            "seed": SEED,
            "low": PIT_LOW,
            "high": PIT_HIGH,
            "coverage": coverage,
            "n_below_low": sum(u < PIT_LOW for u in pit),
            "n_inside": sum(PIT_LOW <= u <= PIT_HIGH for u in pit),
            "n_above_high": sum(u > PIT_HIGH for u in pit),
        },
        "condition_1_log_score_vs_r0": {"criterion": CONDITION_1, "passed": passed_1},
        "condition_2_pit_coverage": {"criterion": CONDITION_2, "coverage_range": [COVERAGE_MIN, COVERAGE_MAX],
                                     "passed": passed_2},
        "verdict": "PASS" if (passed_1 and passed_2) else "FAIL",
        "bootstrap": _bootstrap_settings(),
        "fit_counts": model.n_fit,
        "r0_support": [r0.lo, r0.hi],
        "r1_params": {"mu": r1.mu, "sigma": r1.sigma},
        "n_test_errors_clamped": sum(d.k != d.k_clamped for d in test),
        "n_test_labels_outside_r0_support": sum(not (r0.lo <= d.y <= r0.hi) for d in test),
    }


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
