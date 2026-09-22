"""Descriptive forecast-vs-settlement statistics for EXP-001: TRAIN ROWS ONLY.

This characterizes the forecasting process so the baseline model can be specified. It
does not search thresholds, windows or variants, and it never touches validation or test
rows: `describe` raises if given any. Error e = settlement label - forecast max (°F).
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import mean, median, pstdev
from typing import Any

SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


class NotTrainData(ValueError):
    """Raised when non-train rows reach the descriptive analysis."""


def _errors(rows):
    return [int(r["label_f"]) - int(r["forecast_max_f"]) for r in rows]


def _quantile(sorted_values, q):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[idx]


def _summary(errors):
    n = len(errors)
    if n == 0:
        return {"n": 0}
    s = sorted(errors)
    return {
        "n": n,
        "mean": round(mean(errors), 3),
        "median": median(errors),
        "sd": round(pstdev(errors), 3),
        "mae": round(mean(abs(e) for e in errors), 3),
        "rmse": round(math.sqrt(mean(e * e for e in errors)), 3),
        "exact_pct": round(100 * sum(e == 0 for e in errors) / n, 1),
        "within_1_pct": round(100 * sum(abs(e) <= 1 for e in errors) / n, 1),
        "within_2_pct": round(100 * sum(abs(e) <= 2 for e in errors) / n, 1),
        "within_3_pct": round(100 * sum(abs(e) <= 3 for e in errors) / n, 1),
        "p05": _quantile(s, 0.05),
        "p95": _quantile(s, 0.95),
        "min": s[0],
        "max": s[-1],
    }


def _bin(value: int) -> int:
    """Kalshi-style 2°F bracket pairing (80-81, 82-83, ...): even lower bound."""
    return value - (value % 2)


def _log_scores_error_pmf(errors: list[int]) -> list[float]:
    """ln p(e) under the add-0.5 pmf of the same train errors on [-20, 20] (in-sample)."""
    clipped = [max(-20, min(20, e)) for e in errors]
    counts, n = Counter(clipped), len(clipped)
    return [math.log((counts[e] + 0.5) / (n + 0.5 * 41)) for e in clipped]


def _log_scores_monthly_climatology(rows) -> list[float]:
    labels = [int(r["label_f"]) for r in rows]
    size = max(labels) - min(labels) + 21
    by_month: dict[int, Counter] = {}
    for r in rows:
        by_month.setdefault(int(r["target_date"][5:7]), Counter())[int(r["label_f"])] += 1
    out = []
    for r in rows:
        c = by_month[int(r["target_date"][5:7])]
        out.append(math.log((c[int(r["label_f"])] + 0.5) / (sum(c.values()) + 0.5 * size)))
    return out


def _lag1(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    m = mean(values)
    den = sum((v - m) ** 2 for v in values)
    return round(sum((values[i] - m) * (values[i + 1] - m) for i in range(len(values) - 1)) / den, 3) if den else None


def power_inputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Variance inputs for the power check: moments of the train error distribution and of
    train monthly climatology, in-sample on train. Sizing only; selects nothing."""
    _require_train(rows)
    rows = sorted((r for r in rows if r.get("usable") == "true"), key=lambda r: r["target_date"])
    if not rows:
        return {}
    errors = _errors(rows)
    pmf = _log_scores_error_pmf(errors)
    clim = _log_scores_monthly_climatology(rows)
    diff = [a - b for a, b in zip(pmf, clim)]
    return {
        "n_days": len(rows),
        "error_pmf_log_score_mean": round(mean(pmf), 3),
        "error_pmf_log_score_sd": round(pstdev(pmf), 3),
        "climatology_log_score_mean": round(mean(clim), 3),
        "difference_mean": round(mean(diff), 3),
        "difference_sd": round(pstdev(diff), 3),
        "lag1_autocorrelation_error": _lag1([float(e) for e in errors]),
        "lag1_autocorrelation_difference": _lag1(diff),
    }


def _require_train(rows) -> None:
    bad = [r["target_date"] for r in rows if r.get("split") != "train"]
    if bad:
        raise NotTrainData(f"descriptive analysis is train-only; got non-train rows e.g. {bad[:3]}")


def describe(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _require_train(rows)
    rows = [r for r in rows if r.get("usable") == "true"]
    errors = _errors(rows)
    by_season = {}
    for season in ("DJF", "MAM", "JJA", "SON"):
        sub = [r for r in rows if SEASONS[int(r["target_date"][5:7])] == season]
        by_season[season] = _summary(_errors(sub))
    with_prior = [r for r in rows if r.get("prior_forecast_max_f") not in (None, "")]
    prior_err = [int(r["label_f"]) - int(r["prior_forecast_max_f"]) for r in with_prior]
    chosen_err = _errors(with_prior)
    boundary = sum(_bin(int(r["label_f"])) != _bin(int(r["forecast_max_f"])) for r in rows)
    return {
        "scope": "train split only (2017-01-01..2022-12-31), usable rows",
        "error_definition": "settlement label - chosen forecast max (°F)",
        "overall": _summary(errors),
        "distribution": dict(sorted(Counter(errors).items())),
        "by_season": by_season,
        "revision": {
            "n_with_prior": len(with_prior),
            "prior_issuance_mae": round(mean(abs(e) for e in prior_err), 3) if prior_err else None,
            "chosen_issuance_mae": round(mean(abs(e) for e in chosen_err), 3) if chosen_err else None,
            "forecast_changed_pct": round(
                100 * sum(r["prior_forecast_max_f"] != r["forecast_max_f"] for r in with_prior) / len(with_prior), 1
            ) if with_prior else None,
        },
        "power_inputs": power_inputs(rows),
        "bracket_boundary": {
            "outcome_in_different_2F_bracket_than_forecast_pct": round(100 * boundary / len(rows), 1) if rows else None,
        },
    }
