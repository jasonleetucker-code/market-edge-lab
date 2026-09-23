"""Deterministic conservative probabilities (Gate 5).

A model's point probability is haircut by its own sampling uncertainty, computed from
numbers the model actually has (the count of days it was fitted on). Nothing here takes
a confidence statement from an LLM or a person, and the confidence level is fixed by the
method id: it is never tuned to make opportunities look better.

Method `wilson-one-sided-95-v1`: the one-sided 95% Wilson score bounds for a binomial
proportion p estimated from n independent observations.

- For buying YES the conservative probability is the lower bound on P(YES).
- For buying NO it is 1 minus the upper bound on P(YES).

Known limitation, disclosed rather than patched: the bounds cover only sampling error at
the stated n. Serial dependence between days and model misspecification would widen
them. Calibration evidence for EXP-001 (Stage A PIT central coverage 0.806 against a
nominal 0.80) is reported alongside, not folded in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

WILSON_ONE_SIDED_95 = "wilson-one-sided-95-v1"
_CONFIDENCE = 0.95
_Z = NormalDist().inv_cdf(_CONFIDENCE)


@dataclass(frozen=True)
class ProbabilityBounds:
    """P(YES) with a deterministic lower and upper bound."""

    point: float
    lower: float
    upper: float
    method: str
    n_effective: int
    confidence: float
    standard_error: float

    def for_side(self, side: str) -> tuple[float, float]:
        """(point, conservative) probability that buying `side` pays out."""
        if side == "YES":
            return self.point, self.lower
        if side == "NO":
            return 1.0 - self.point, 1.0 - self.upper
        raise ValueError(f"unknown side {side!r}")


def wilson_bounds(p: float, n: int) -> ProbabilityBounds:
    """One-sided 95% Wilson score bounds for P(YES) = p estimated from n observations."""
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ValueError("n must be a positive integer")
    if not (isinstance(p, float) and math.isfinite(p) and 0.0 <= p <= 1.0):
        raise ValueError(f"probability must be a finite float in [0, 1], got {p!r}")
    z2 = _Z * _Z
    centre = p + z2 / (2 * n)
    spread = _Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    denominator = 1 + z2 / n
    lower = max(0.0, (centre - spread) / denominator)
    upper = min(1.0, (centre + spread) / denominator)
    return ProbabilityBounds(
        point=p, lower=min(lower, p), upper=max(upper, p), method=WILSON_ONE_SIDED_95,
        n_effective=n, confidence=_CONFIDENCE, standard_error=math.sqrt(p * (1 - p) / n),
    )
