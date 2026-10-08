"""Statistics for wallet research: shrinkage, cluster bootstrap and multiple testing (W3, W4).

Floats are allowed here and only here. Their results are reported uncertainty; they never become a
money value or an order quantity.

- `BetaPrior` / `fit_beta_prior`: an empirical-Bayes Beta prior fitted by the method of moments
  across candidates (with a weak fallback), so a 3-for-3 newcomer is shrunk towards the pool.
- `beta_interval`: an equal-tailed credible interval from the regularized incomplete beta function
  (continued fraction), inverted by bisection. Deterministic.
- `cluster_bootstrap`: resamples whole clusters (an event, not a trade), the dependence unit the
  directive asks for. None with fewer than two clusters.
- `benjamini_hochberg`: which of m hypotheses survive at false-discovery rate q. Use it whenever
  several leaders are tested on the same data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Mapping, Sequence

BOOTSTRAP_SEED = 20261007
BOOTSTRAP_RESAMPLES = 2000


@dataclass(frozen=True)
class BetaPrior:
    alpha: float
    beta: float
    source: str  # "EMPIRICAL_BAYES_MOMENTS" | "WEAK_DEFAULT"

    def __post_init__(self) -> None:
        if not (self.alpha > 0 and self.beta > 0):
            raise ValueError("Beta prior parameters must be positive")


WEAK_PRIOR = BetaPrior(1.0, 1.0, "WEAK_DEFAULT")


def fit_beta_prior(records: Sequence[tuple[int, int]], *, min_candidates: int = 5) -> BetaPrior:
    """Method-of-moments Beta prior from (wins, trials) per candidate. With too few candidates, or
    when the observed spread is no wider than binomial noise, the weak default is returned."""
    usable = [(w, n) for w, n in records if n > 0]
    if len(usable) < min_candidates:
        return WEAK_PRIOR
    rates = [w / n for w, n in usable]
    mean = math.fsum(rates) / len(rates)
    var = math.fsum((r - mean) ** 2 for r in rates) / (len(rates) - 1)
    avg_n = math.fsum(n for _, n in usable) / len(usable)
    noise = mean * (1 - mean) / avg_n
    excess = var - noise
    if not (0 < mean < 1) or excess <= 0:
        return WEAK_PRIOR
    strength = mean * (1 - mean) / excess - 1
    if strength <= 0:
        return WEAK_PRIOR
    return BetaPrior(max(mean * strength, 1e-3), max((1 - mean) * strength, 1e-3), "EMPIRICAL_BAYES_MOMENTS")


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny, eps = 1e-300, 3e-14

    def guard(v: float) -> float:
        return tiny if abs(v) < tiny else v

    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 / guard(1.0 - qab * x / qap)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 / guard(1.0 + aa * d)
        c = guard(1.0 + aa / c)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 / guard(1.0 + aa * d)
        c = guard(1.0 + aa / c)
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(ln)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def beta_quantile(p: float, a: float, b: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if beta_cdf(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@dataclass(frozen=True)
class ShrunkRate:
    wins: int
    trials: int
    raw_rate: float | None  # None with no trials
    posterior_mean: float
    lower: float
    upper: float
    level: float
    prior: BetaPrior

    def to_dict(self) -> dict:
        return {"wins": self.wins, "trials": self.trials, "raw_rate": self.raw_rate,
                "posterior_mean": round(self.posterior_mean, 6), "lower": round(self.lower, 6),
                "upper": round(self.upper, 6), "level": self.level, "prior": [self.prior.alpha, self.prior.beta,
                                                                               self.prior.source]}


def shrunk_rate(wins: int, trials: int, prior: BetaPrior, *, level: float = 0.90) -> ShrunkRate:
    if wins < 0 or trials < wins:
        raise ValueError("need 0 <= wins <= trials")
    a, b = prior.alpha + wins, prior.beta + trials - wins
    tail = (1 - level) / 2
    return ShrunkRate(wins, trials, None if trials == 0 else wins / trials, a / (a + b),
                      beta_quantile(tail, a, b), beta_quantile(1 - tail, a, b), level, prior)


def cluster_bootstrap(values_by_cluster: Mapping[str, float], *, seed: int = BOOTSTRAP_SEED,
                      resamples: int = BOOTSTRAP_RESAMPLES, alpha: float = 0.10) -> tuple[float, float, float] | None:
    """(mean, lower, upper) of the per-cluster value, resampling whole clusters. None with < 2 clusters."""
    keys = sorted(values_by_cluster)
    if len(keys) < 2:
        return None
    values = [float(values_by_cluster[k]) for k in keys]
    rng = random.Random(seed)
    n = len(values)
    means = sorted(math.fsum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lower = means[math.floor(alpha / 2 * resamples)]
    upper = means[math.ceil((1 - alpha / 2) * resamples) - 1]
    return math.fsum(values) / n, lower, upper


def benjamini_hochberg(p_values: Mapping[str, float], *, q: float = 0.10, m: int | None = None) -> frozenset[str]:
    """Hypotheses rejected at false-discovery rate `q` (step-up procedure).

    `m` is the total number of hypotheses tested, which may exceed the p-values passed in (earlier
    selection trials whose p-values are not at hand count as untested p = 1). It defaults to len(p)."""
    if not (0 < q < 1):
        raise ValueError("q must be in (0, 1)")
    ranked = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    total = len(ranked) if m is None else m
    if total < len(ranked):
        raise ValueError("m cannot be smaller than the number of p-values")
    cutoff = 0
    for i, (_, p) in enumerate(ranked, 1):
        if not (0 <= p <= 1):
            raise ValueError("p-values must be in [0, 1]")
        if p <= q * i / total:
            cutoff = i
    return frozenset(k for k, _ in ranked[:cutoff])


def binomial_tail_p(wins: int, trials: int, p0: float = 0.5) -> float:
    """One-sided P(X >= wins) under Binomial(trials, p0): an exact p-value for a win count."""
    if trials == 0:
        return 1.0
    return math.fsum(math.comb(trials, k) * p0 ** k * (1 - p0) ** (trials - k) for k in range(wins, trials + 1))
