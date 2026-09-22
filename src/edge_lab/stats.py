"""Preregistered statistical procedures (EXP-001 and later). Deterministic, stdlib-only.

The algorithms are pinned here so that "block bootstrap, seed 20260922" means exactly one
computation: two honest implementations can otherwise disagree at a borderline.
"""

from __future__ import annotations

import math
import random
from typing import Sequence

PREREGISTERED_SEED = 20260922


def block_bootstrap_mean_ci(
    values: Sequence[float],
    *,
    block: int = 7,
    resamples: int = 10_000,
    seed: int = PREREGISTERED_SEED,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """(mean, lower, upper) by a circular moving-block bootstrap of the mean.

    `values` are per-day quantities in date order. Algorithm:
    - rng = random.Random(seed); n = len(values); k = ceil(n / block);
    - each resample: k times, start = rng.randrange(n) and append
      values[(start + j) % n] for j in 0..block-1; truncate to the first n values;
      record math.fsum(sample) / n;
    - sort the resample means m[0..B-1]; lower = m[floor(alpha/2 * B)],
      upper = m[ceil((1 - alpha/2) * B) - 1].
    """
    n = len(values)
    if n == 0:
        raise ValueError("no values")
    if block < 1 or resamples < 1 or not (0 < alpha < 1):
        raise ValueError("invalid bootstrap parameters")
    rng = random.Random(seed)
    k = math.ceil(n / block)
    means = []
    for _ in range(resamples):
        sample: list[float] = []
        for _ in range(k):
            start = rng.randrange(n)
            sample.extend(values[(start + j) % n] for j in range(block))
        means.append(math.fsum(sample[:n]) / n)
    means.sort()
    lower = means[math.floor(alpha / 2 * resamples)]
    upper = means[math.ceil((1 - alpha / 2) * resamples) - 1]
    return math.fsum(values) / n, lower, upper


def randomized_pit(cdf_below_and_mass: Sequence[tuple[float, float]], *, seed: int = PREREGISTERED_SEED) -> list[float]:
    """Randomized PIT for integer outcomes: u = F(y-1) + v * P(y), one v per day from
    random.Random(seed).random(), drawn in the order given (date order)."""
    rng = random.Random(seed)
    return [below + rng.random() * mass for below, mass in cdf_below_and_mass]


def central_coverage(pit: Sequence[float], low: float = 0.10, high: float = 0.90) -> float:
    """Fraction of PIT values with low <= u <= high."""
    if not pit:
        raise ValueError("no PIT values")
    return sum(low <= u <= high for u in pit) / len(pit)
