"""Forecast scoring for recorded probability forecasts (#192, ADR 0049). Deterministic, stdlib-only.

Canonical owner of forecast scoring. `src/edge_lab/stats.py` cannot take these functions because EXP-001's
preregistration pins its SHA-256 (tests/invariants/test_exp001_frozen_artifacts.py).
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

# --------------------------------------------------------------------------- forecast scoring (ADR 0049)


def _forecast_pairs(pairs: Iterable[tuple[float, int]]) -> list[tuple[float, int]]:
    """Validated (probability, outcome) pairs: p a finite real in [0, 1], y exactly 0 or 1."""
    out = []
    for item in pairs:
        try:
            p, y = item
        except (TypeError, ValueError):
            raise ValueError(f"expected a (probability, outcome) pair, got {item!r}") from None
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError(f"probability must be a finite number in [0, 1], got {p!r}")
        if isinstance(y, bool) or not isinstance(y, int) or y not in (0, 1):
            raise ValueError(f"outcome must be the integer 0 or 1, got {y!r}")
        out.append((float(p), y))
    return out


def brier_score(pairs: Iterable[tuple[float, int]]) -> float | None:
    """Mean squared error (p - y)^2 of binary forecasts. Lower is better; 0.25 is a constant 0.5.

    None for no pairs: an unscored forecaster has no score, which is not a perfect 0.
    Raises ValueError on a probability outside [0, 1] or not finite, or an outcome not 0/1."""
    checked = _forecast_pairs(pairs)
    if not checked:
        return None
    return math.fsum((p - y) ** 2 for p, y in checked) / len(checked)


def _bin_index(p: float, bins: int) -> int:
    # Decimal of the shortest repr, so 0.3 lands in [0.3, 0.4) rather than below it by float error.
    try:
        scaled = Decimal(repr(p)) * bins
    except InvalidOperation:  # pragma: no cover - p is already validated finite
        raise ValueError(f"unbinnable probability {p!r}") from None
    return min(int(scaled), bins - 1)


def calibration_bins(pairs: Iterable[tuple[float, int]], bins: int = 10) -> tuple[dict[str, Any], ...]:
    """Reliability table: `bins` equal-width forecast bins on [0, 1].

    Bin i covers [i/bins, (i+1)/bins); the last bin also holds p = 1. Each row is
    {lower, upper, n, mean_forecast, observed_rate}. An empty bin has n = 0 and None means:
    no forecasts there is unknown, never a rate of 0. Validation is that of `brier_score`."""
    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
        raise ValueError("bins must be a positive integer")
    members: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in _forecast_pairs(pairs):
        members[_bin_index(p, bins)].append((p, y))
    rows = []
    for i, group in enumerate(members):
        n = len(group)
        rows.append({
            "lower": i / bins,
            "upper": (i + 1) / bins,
            "n": n,
            "mean_forecast": math.fsum(p for p, _ in group) / n if n else None,
            "observed_rate": sum(y for _, y in group) / n if n else None,
        })
    return tuple(rows)
