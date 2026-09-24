"""Stake sizing v2: the research challenger engine (ADR 0026). Shadow/research only.

`sizing.py` stays the frozen operational path (`EXP-001-fixed-1-v1`). This module never
places, simulates against a live venue, or changes a shadow fill. It turns explicit inputs
into a `SizingRecommendation` labelled RESEARCH SIZING, and every dollar figure is a
deterministic function of those inputs.

The layers are separate, and each has one owner:

1. **Probability model** (input). `model_probabilities` is a probability vector over a finite
   set of mutually exclusive, exhaustive outcome STATES for one cluster (for example the K
   temperature brackets of one day, exactly one of which settles YES). A binary YES/NO is
   K = 2. The model is not fitted here.
2. **Uncertainty** (`BoxSimplexSet`, `VertexSet`). A set of admissible probability vectors.
   The robust objective takes, for each candidate stake, the WORST expected log wealth over
   the whole set. Nothing assumes a side (owner correction 2, 2026-09-24): expected log
   wealth is linear in the probability vector, so its minimum over a polytope is attained at
   an extreme point, and the minimizing vector is derived from the payoff. It is a low YES
   probability for a YES position, a high one for a NO position, and whatever the payoff
   implies for a multi-state position. `BoxSimplexSet.worst` solves the minimum exactly and
   `vertices()` enumerates the extreme points so tests can check it.
3. **Execution cost** (`ExactCostCurve`). The exact cash cost of C contracts:
   `walk_ladder` over the captured ask ladder (the market's price grid enforced), priced by
   `price_depth_fill` under `schedule_for(venue, scope)`, plus the documented per-contract
   allowance when the fee claim basis is CONSERVATIVE_BOUND (ADR 0017). The marginal cost
   rises as the walk climbs the book. Beyond the captured depth nothing is priced, so depth
   is a hard liquidity cap.
4. **Portfolio and risk state** (`PortfolioState`, built from `risk.assess`). Equity,
   settled cash, the reserve floor, the risk module's remaining capacity, event and cluster
   exposure, loss and drawdown headroom, and breaches.
5. **Deterministic optimizer** (`solve`). An integer search over contracts. Policies A-H are
   frozen, versioned `SizingPolicyV2` values.
6. **Hard caps**, applied after the optimizer: liquidity, position, event, cluster (with
   unknown-correlation clusters sharing one cap), portfolio, reserve floor, loss/drawdown
   headroom, the risk budget and the STARTER_MAX_7D_V1 capital horizon. Every cap is recorded
   with the one that binds.
7. **Explanation**: fixed template text built from the numbers. No LLM touches any figure.

Fail-closed rules (explicit, in precedence order):

- UNSUPPORTED: a payoff that is not a plain binary paying 1; a side other than YES/NO; states
  the outcome mapping does not know; a market that is not OPEN (MARKET_NOT_OPEN) or whose
  settlement rules are not resolved (RULES_UNRESOLVED), as `opportunity.evaluate` refuses
  both; an unsupported fee schedule; a fee schedule whose point-in-time claim basis is NONE
  (config `require_fee_claim`).
- STALE_DATA: a missing, stale or malformed (INVALID_BOOK) book; a missing model estimate or
  model version; a missing or stale risk state; any input timestamped after the decision time.
- RISK_LIMIT: any risk breach, or zero remaining risk capacity.
- CAPITAL_HORIZON: no STARTER_MAX_7D_V1 verdict (unknown release), or an ineligible one.
- UNCERTAINTY_TOO_HIGH: no admissible probability set (unknown uncertainty is unbounded),
  or a positive nominal edge that the robust objective sizes to zero.
- ZERO_EDGE: no positive expected net edge (or no log-growth benefit) at the nominal model,
  or a flat/fixed rule's entry threshold is not met.
- LIQUIDITY_LIMIT / RISK_LIMIT: the policy wanted contracts, but depth, tradable cash or a
  hard cap allows none.

Missing values stay None. An unknown input never becomes zero risk and never yields SIZE.
Open exposure in the cluster that the caller cannot map to outcome states is assumed to be
lost in every state.

The optimizer works in floats (logarithms need them), over costs that come from exact
Decimal cent arithmetic. Money in the output is Decimal, cent-quantized: costs round up and
limits round down.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum
from fractions import Fraction
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .conservative import ProbabilityBounds, wilson_bounds
from .fee_schedules import (
    KALSHI_QUADRATIC_TAKER_V1, ClaimBasis, FeeScheduleStatus, FeeVerificationState, UnsupportedFeeSchedule,
    schedule_for, verification_at,
)
from .freshness import Freshness
from .freshness import assess as freshness_assess
from .freshness import parse_utc
from .opportunity import (
    DepthCost, DepthLadder, DepthStatus, FeeSchedule, Market, MarketStatus, price_depth_fill, walk_ladder,
)
from .risk import RiskPolicy, RiskReport
from .starter_policy import StarterVerdict

ENGINE_ID = "sizing-v2"
ENGINE_VERSION = "1"
LABEL = "RESEARCH SIZING (shadow/research only; not an order and not authorized for real money)"
CENT = Decimal("0.01")
EDGE_GRID = Decimal("0.0001")
PROB_GRID = Decimal("0.000001")
ZERO = Decimal(0)

SCAN_LIMIT = 40  # up to this many contracts the 1-D optimizer scans every integer
REFINE_WINDOW = 12  # above it: bisection on the discrete derivative, then a local scan of +-12
MAX_SWEEPS = 50  # coordinate-ascent sweeps for joint (policy H) problems
EXHAUSTIVE_LIMIT = 4096  # joint grids up to this many points are searched exhaustively
_TOL = 1e-12  # float tolerance for budget and probability checks


class Verdict(str, Enum):
    SIZE = "SIZE"
    ZERO_EDGE = "ZERO_EDGE"
    UNCERTAINTY_TOO_HIGH = "UNCERTAINTY_TOO_HIGH"
    LIQUIDITY_LIMIT = "LIQUIDITY_LIMIT"
    RISK_LIMIT = "RISK_LIMIT"
    STALE_DATA = "STALE_DATA"
    CAPITAL_HORIZON = "CAPITAL_HORIZON"
    UNSUPPORTED = "UNSUPPORTED"


# =========================================================================== uncertainty


def _check_vector(v: Sequence[float], k: int, what: str) -> tuple[float, ...]:
    out = tuple(float(x) for x in v)
    if len(out) != k:
        raise ValueError(f"{what} has {len(out)} entries for {k} states")
    if any(not math.isfinite(x) or x < -_TOL or x > 1 + _TOL for x in out):
        raise ValueError(f"{what} has an entry outside [0, 1]: {out}")
    if abs(sum(out) - 1.0) > 1e-9:
        raise ValueError(f"{what} does not sum to 1: {sum(out)}")
    return out


@dataclass(frozen=True)
class BoxSimplexSet:
    """Admissible probability vectors {v : lower <= v <= upper, sum(v) = 1}: a polytope.

    `nominal` (the model's point vector) lies inside the box, so the robust value is never
    above the nominal one. `worst(g)` minimizes sum(v_k * g_k) over the set exactly: start
    every state at its lower bound and give the remaining mass to the states with the
    smallest g first, each up to its upper bound (a fractional knapsack; ties by state
    order). The result is an extreme point of the polytope."""

    states: tuple[str, ...]
    nominal: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    method: str
    detail: str = ""

    def __post_init__(self) -> None:
        k = len(self.states)
        if k < 2 or len(set(self.states)) != k:
            raise ValueError("an outcome space needs at least two distinct states")
        _check_vector(self.nominal, k, "nominal")
        if len(self.lower) != k or len(self.upper) != k:
            raise ValueError("bounds must have one entry per state")
        for lo, p, hi in zip(self.lower, self.nominal, self.upper):
            if not (-_TOL <= lo <= p + _TOL and p - _TOL <= hi <= 1 + _TOL):
                raise ValueError(f"nominal {p} is outside its bounds [{lo}, {hi}]")
        if sum(self.lower) > 1 + 1e-9 or sum(self.upper) < 1 - 1e-9:
            raise ValueError("the bounds admit no probability vector")

    def worst(self, g: Sequence[float]) -> tuple[float, tuple[float, ...]]:
        v = list(self.lower)
        remaining = 1.0 - sum(v)
        for k in sorted(range(len(v)), key=lambda i: (g[i], i)):
            if remaining <= 0:
                break
            add = min(remaining, self.upper[k] - self.lower[k])
            v[k] += add
            remaining -= add
        return sum(vk * gk for vk, gk in zip(v, g) if vk), tuple(v)

    def vertices(self) -> tuple[tuple[float, ...], ...]:
        """Every extreme point: all coordinates but one at a bound, the last one fixed by the sum."""
        k = len(self.states)
        if k > 16:
            raise ValueError("vertex enumeration is limited to 16 states")
        found: dict[tuple[float, ...], tuple[float, ...]] = {}
        for free in range(k):
            others = [i for i in range(k) if i != free]
            for mask in range(1 << (k - 1)):
                v = [0.0] * k
                for bit, i in enumerate(others):
                    v[i] = self.upper[i] if mask >> bit & 1 else self.lower[i]
                v[free] = 1.0 - sum(v)
                if self.lower[free] - 1e-12 <= v[free] <= self.upper[free] + 1e-12:
                    found.setdefault(tuple(round(x, 12) for x in v), tuple(v))
        return tuple(found[key] for key in sorted(found))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "box_simplex", "states": list(self.states), "nominal": list(self.nominal),
                "lower": list(self.lower), "upper": list(self.upper), "method": self.method, "detail": self.detail}


@dataclass(frozen=True)
class VertexSet:
    """An explicit finite set of admissible probability vectors (for example posterior
    scenarios). Its convex hull is the admissible set; `nominal` is always admissible."""

    states: tuple[str, ...]
    nominal: tuple[float, ...]
    points: tuple[tuple[float, ...], ...]
    method: str
    detail: str = ""

    def __post_init__(self) -> None:
        k = len(self.states)
        if k < 2 or len(set(self.states)) != k:
            raise ValueError("an outcome space needs at least two distinct states")
        _check_vector(self.nominal, k, "nominal")
        for i, p in enumerate(self.points):
            _check_vector(p, k, f"point {i}")

    def worst(self, g: Sequence[float]) -> tuple[float, tuple[float, ...]]:
        best: tuple[float, tuple[float, ...]] | None = None
        for v in (self.nominal,) + tuple(self.points):
            value = sum(vk * gk for vk, gk in zip(v, g) if vk)
            if best is None or value < best[0]:
                best = (value, tuple(v))
        assert best is not None
        return best

    def vertices(self) -> tuple[tuple[float, ...], ...]:
        return (self.nominal,) + tuple(self.points)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "vertex_set", "states": list(self.states), "nominal": list(self.nominal),
                "points": [list(p) for p in self.points], "method": self.method, "detail": self.detail}


UncertaintySet = BoxSimplexSet | VertexSet


def binary_interval(point: float, lower: float, upper: float, *, states: tuple[str, str] = ("YES", "NO"),
                    method: str = "binary-interval") -> BoxSimplexSet:
    """P(first state) in [lower, upper] around `point`, as a two-state set."""
    return BoxSimplexSet(states, (point, 1.0 - point), (lower, 1.0 - upper), (upper, 1.0 - lower), method,
                         f"P({states[0]}) in [{lower:.6f}, {upper:.6f}]")


def from_probability_bounds(bounds: ProbabilityBounds, *, states: tuple[str, str] = ("YES", "NO")) -> BoxSimplexSet:
    """The existing conservative-probability contract (`conservative.py`) as a two-state set."""
    return binary_interval(bounds.point, bounds.lower, bounds.upper, states=states,
                           method=f"{bounds.method}(n={bounds.n_effective})")


def wilson_box(states: Sequence[str], nominal: Sequence[float], n: int) -> BoxSimplexSet:
    """Per-state one-sided 95% Wilson bounds (`conservative.wilson_bounds`) intersected with the simplex."""
    p = _check_vector(nominal, len(states), "nominal")
    bounds = [wilson_bounds(min(1.0, max(0.0, x)), n) for x in p]
    return BoxSimplexSet(tuple(states), p, tuple(b.lower for b in bounds), tuple(b.upper for b in bounds),
                         f"wilson-box-95-v1(n={n})", "per-state one-sided 95% Wilson bounds")


def dirichlet_box(states: Sequence[str], nominal: Sequence[float], n_eff: float, *, gamma: float = 0.10,
                  prior: float = 0.5) -> BoxSimplexSet:
    """Marginal credible bounds of the posterior Dirichlet(prior + n_eff * nominal).

    Each state's marginal is Beta(a_k, a_0 - a_k). The tails are Bonferroni-split so the joint
    box has at least 1 - gamma posterior mass: gamma/2 per side for K = 2 (the two marginals
    are the same constraint), gamma/(2K) per side otherwise. The box is widened, if needed,
    to contain the nominal vector. `n_eff` is the effective number of settled outcomes the
    model's calibration rests on: the evidence, not a tuning knob."""
    p = _check_vector(nominal, len(states), "nominal")
    if not (n_eff > 0 and math.isfinite(n_eff)) or not (0 < gamma < 1) or prior <= 0:
        raise ValueError("n_eff and prior must be positive and gamma in (0, 1)")
    k = len(p)
    tail = gamma / 2 if k == 2 else gamma / (2 * k)
    alpha = [prior + n_eff * x for x in p]
    total = sum(alpha)
    lower, upper = [], []
    for x, a in zip(p, alpha):
        lo, hi = beta_ppf(tail, a, total - a), beta_ppf(1 - tail, a, total - a)
        lower.append(min(lo, x))
        upper.append(max(hi, x))
    return BoxSimplexSet(tuple(states), p, tuple(lower), tuple(upper),
                         f"dirichlet-box-v1(n_eff={n_eff:g},gamma={gamma:g},prior={prior:g})",
                         "Bonferroni marginal Beta credible bounds of a Dirichlet posterior")


DEFAULT_UNCERTAINTY_METHOD = "dirichlet-box-v1"
"""The family the pre-declared simulation rule selected (docs/research/STAKE_SIZING_V2.md §7.3).
The comparison per n_eff was mixed (Wilson was ahead at n_eff 100), and the rule's winner at
n_eff 30 barely trades, so the evidence for the family is weak. The Dirichlet posterior is
kept because it is the statistically justified Bayesian model with explicit coverage. `n_eff`
is never chosen by simulation: it is the effective settled out-of-sample sample behind the model."""


def default_uncertainty(states: Sequence[str], nominal: Sequence[float], n_eff: float) -> BoxSimplexSet:
    return dirichlet_box(states, nominal, n_eff)


def beta_binary(point: float, n_eff: float, *, gamma: float = 0.10, prior: float = 0.5,
                states: tuple[str, str] = ("YES", "NO")) -> BoxSimplexSet:
    """The Beta posterior for a binary: `dirichlet_box` with K = 2."""
    return dirichlet_box(states, (point, 1.0 - point), n_eff, gamma=gamma, prior=prior)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the regularized incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b) (stdlib only)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """The q-quantile of Beta(a, b): safeguarded Newton inside a shrinking bisection bracket.

    Deterministic; stops when |I_x(a, b) - q| < 1e-13 or the bracket is narrower than 1e-15."""
    if not (0.0 < q < 1.0) or a <= 0 or b <= 0:
        raise ValueError("beta_ppf needs q in (0, 1) and positive shape parameters")
    log_norm = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    lo, hi = 0.0, 1.0
    x = a / (a + b)
    for _ in range(200):
        err = beta_cdf(x, a, b) - q
        if abs(err) < 1e-13:
            return x
        if err < 0:
            lo = x
        else:
            hi = x
        if hi - lo < 1e-15:
            break
        pdf = math.exp(log_norm + (a - 1) * math.log(x) + (b - 1) * math.log1p(-x)) if 0 < x < 1 else 0.0
        step = x - err / pdf if pdf > 0 else lo - 1.0
        x = step if lo < step < hi else (lo + hi) / 2
    return (lo + hi) / 2


# =========================================================================== cost curves


class CostCurve(Protocol):
    """Cash cost of whole contracts, fees and allowances included; monotone in n."""

    max_contracts: int

    def cost(self, n: int) -> float: ...

    def smooth(self, n: int) -> float: ...


class ExactCostCurve:
    """The exact cost of n contracts from one captured ladder under one fee schedule.

    total(n) = price_depth_fill(walk_ladder(ladder, n, price_grid)).total_cost + allowance * n.
    `max_contracts` is the captured depth usable in whole-contract takes: a level with a
    fractional size ends the usable prefix (its whole part still counts), because no fee
    rule for a fractional take is modelled. Nothing beyond the capture is ever assumed,
    and a truncated capture is flagged (`truncated`)."""

    def __init__(self, ladder: DepthLadder, schedule: FeeSchedule, *, price_grid: Any = None,
                 allowance_per_contract: Decimal = ZERO) -> None:
        self.ladder, self.schedule, self.price_grid = ladder, schedule, price_grid
        self.allowance = allowance_per_contract
        self.truncated = bool(ladder.truncated)
        self._cache: dict[int, DepthCost | None] = {}
        probe = walk_ladder(ladder, 1, price_grid=price_grid) if ladder.asks else None
        self.problem: str | None = None
        if probe is not None and probe.status is DepthStatus.INVALID_BOOK:
            self.problem, self.max_contracts = f"INVALID_BOOK: {probe.detail}", 0
            return
        usable = ZERO
        for level in ladder.asks:
            whole = level.size.to_integral_value(rounding=ROUND_FLOOR)
            usable += whole
            if whole != level.size:
                break
        self.max_contracts = int(usable)

    def depth_cost(self, n: int) -> DepthCost | None:
        if n <= 0 or n > self.max_contracts:
            return None
        if n not in self._cache:
            priced, _ = price_depth_fill(walk_ladder(self.ladder, n, price_grid=self.price_grid), self.schedule)
            self._cache[n] = priced
        return self._cache[n]

    def total(self, n: int) -> Decimal | None:
        """Exact worst-case cash for n contracts (0 -> 0; beyond the usable depth -> None)."""
        if n == 0:
            return ZERO
        priced = self.depth_cost(n)
        return None if priced is None else priced.total_cost + self.allowance * n

    def cost(self, n: int) -> float:
        total = self.total(n)
        if total is None:
            raise ValueError(f"{n} contracts exceed the usable depth {self.max_contracts}")
        return float(total)

    def smooth(self, n: int) -> float:
        """The cost before cent alignment (gross + trade fee + allowance): convex in n up to
        the fee's $0.000001 rounding. The optimizer searches on it (see `_argmax_1d`)."""
        if n == 0:
            return 0.0
        priced = self.depth_cost(n)
        if priced is None:
            raise ValueError(f"{n} contracts exceed the usable depth {self.max_contracts}")
        return float(priced.fill.gross_cost + priced.fee + self.allowance * n)

    def max_affordable(self, budget: Decimal, hi: int | None = None) -> int:
        """The most contracts, at most `hi`, whose exact cost fits in `budget`."""
        top = self.max_contracts if hi is None else min(hi, self.max_contracts)
        if budget <= 0 or top <= 0:
            return 0
        lo = 0
        while lo < top:
            mid = (lo + top + 1) // 2
            if self.total(mid) <= budget:  # type: ignore[operator]
                lo = mid
            else:
                top = mid - 1
        return lo


class IntegerLadderCostCurve:
    """The same quadratic taker cost in exact integer arithmetic, for fast simulation.

    `levels` are (price in 1/10000 dollars, whole-contract size), cheapest first. Per take
    of s contracts at P: fee = ceil(coefficient * s * p * (1 - p)) to $0.000001, and the take
    costs ceil(p * s + fee) to the cent, exactly as `QuadraticTakerSchedule.taker_buy`
    (tests hold the two equal). `allowance_per_contract` is added per contract."""

    def __init__(self, levels: Sequence[tuple[int, int]], *, coefficient: Decimal = Decimal("0.07"),
                 allowance_per_contract: float = 0.0) -> None:
        frac = Fraction(coefficient)
        self._num, self._den = frac.numerator, frac.denominator
        self.levels = tuple((int(p), int(s)) for p, s in levels if s > 0)
        self.allowance = float(allowance_per_contract)
        cum_n, cum_c, cum_s = [0], [0], [0.0]
        for p, s in self.levels:
            cum_n.append(cum_n[-1] + s)
            cum_c.append(cum_c[-1] + self._take_cents(p, s))
            cum_s.append(cum_s[-1] + self._take_smooth(p, s))
        self._cum_n, self._cum_c, self._cum_s = cum_n, cum_c, cum_s
        self.max_contracts = cum_n[-1]
        self._memo: dict[int, float] = {}
        self._smemo: dict[int, float] = {}

    def _take_smooth(self, price: int, size: int) -> float:
        p = price / 10000
        return size * p + self._num / self._den * size * p * (1 - p)

    def _level(self, n: int) -> int:
        lo, hi = 0, len(self.levels)
        while lo < hi:  # full levels at or below n contracts
            mid = (lo + hi + 1) // 2
            if self._cum_n[mid] <= n:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def smooth(self, n: int) -> float:
        """Cost before any rounding (price * size + coefficient * size * p * (1 - p) per take,
        plus the allowance): convex in n. The optimizer searches on it (see `_argmax_1d`)."""
        if n <= 0:
            return 0.0
        value = self._smemo.get(n)
        if value is None:
            if n > self.max_contracts:
                raise ValueError(f"{n} contracts exceed the depth {self.max_contracts}")
            lo = self._level(n)
            value = self._cum_s[lo] + self.allowance * n
            rest = n - self._cum_n[lo]
            if rest:
                value += self._take_smooth(self.levels[lo][0], rest)
            self._smemo[n] = value
        return value

    def _take_cents(self, price: int, size: int) -> int:
        fee_micro = -(-self._num * size * price * (10000 - price) // (self._den * 100))
        total_micro = size * price * 100 + fee_micro
        return -(-total_micro // 10000)

    def cost_cents(self, n: int) -> int:
        if n <= 0:
            return 0
        if n > self.max_contracts:
            raise ValueError(f"{n} contracts exceed the depth {self.max_contracts}")
        lo = self._level(n)
        cents, rest = self._cum_c[lo], n - self._cum_n[lo]
        if rest:
            cents += self._take_cents(self.levels[lo][0], rest)
        return cents

    def cost(self, n: int) -> float:
        value = self._memo.get(n)
        if value is None:
            value = self._memo[n] = self.cost_cents(n) / 100.0 + self.allowance * n
        return value


# =========================================================================== policies

RULES = ("FLAT_UNIT", "FIXED_FRACTION", "KELLY")


@dataclass(frozen=True)
class SizingPolicyV2:
    """One versioned sizing rule. A changed parameter is a new version, never an edit.

    - FLAT_UNIT: spend up to `unit_amount` when the nominal net edge per contract is at least
      `min_edge`. FIXED_FRACTION: the same with `bankroll_fraction` of the bankroll.
    - KELLY: maximize expected log wealth over integer contracts: nominal (`robust` False) or
      the worst case over the uncertainty set (`robust` True), then take `kelly_fraction`
      of the optimal count (floor). `drawdown_alpha`/`drawdown_beta` add the Busseti-Ryu-Boyd
      risk constraint E[(W'/W)^-lambda] <= 1 with lambda = log(beta)/log(alpha), evaluated
      exactly over the outcome states (worst case over the set when `robust_constraint`).
      `cvar_level`/`cvar_max_loss` cap the nominal one-period CVaR of the loss as a fraction
      of the bankroll. `joint` (policy H) optimizes every candidate of one cluster together
      under the shared cluster budget; otherwise candidates are sized one at a time, each
      conditional on what is already held in the cluster.
    """

    policy_id: str
    policy_version: str
    rule: str
    description: str
    unit_amount: Decimal | None = None
    bankroll_fraction: Decimal | None = None
    min_edge: Decimal = ZERO
    kelly_fraction: Decimal = Decimal(1)
    robust: bool = False
    drawdown_alpha: Decimal | None = None
    drawdown_beta: Decimal | None = None
    robust_constraint: bool = False
    cvar_level: Decimal | None = None
    cvar_max_loss: Decimal | None = None
    joint: bool = False

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"unknown rule {self.rule!r}")
        if self.rule == "FLAT_UNIT" and not (self.unit_amount and self.unit_amount > 0):
            raise ValueError("FLAT_UNIT needs a positive unit_amount")
        if self.rule == "FIXED_FRACTION" and not (self.bankroll_fraction and 0 < self.bankroll_fraction <= 1):
            raise ValueError("FIXED_FRACTION needs bankroll_fraction in (0, 1]")
        if not (ZERO < self.kelly_fraction <= 1):
            raise ValueError("kelly_fraction must be in (0, 1]")
        if (self.drawdown_alpha is None) != (self.drawdown_beta is None):
            raise ValueError("drawdown_alpha and drawdown_beta go together")
        if self.drawdown_alpha is not None and not (0 < self.drawdown_alpha < 1 and 0 < self.drawdown_beta < 1):
            raise ValueError("drawdown_alpha and drawdown_beta must be in (0, 1)")
        if (self.cvar_level is None) != (self.cvar_max_loss is None):
            raise ValueError("cvar_level and cvar_max_loss go together")
        if self.min_edge < 0:
            raise ValueError("min_edge must not be negative")

    @property
    def drawdown_lambda(self) -> float | None:
        if self.drawdown_alpha is None:
            return None
        return math.log(float(self.drawdown_beta)) / math.log(float(self.drawdown_alpha))

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


_V = "1"
POLICY_A = SizingPolicyV2("SV2-A-flat-unit", _V, "FLAT_UNIT", "A: flat $10 unit when nominal net edge >= 0.05",
                          unit_amount=Decimal("10.00"), min_edge=Decimal("0.05"))
POLICY_B = SizingPolicyV2("SV2-B-fixed-2pct", _V, "FIXED_FRACTION",
                          "B: 2% of bankroll when nominal net edge >= 0.05",
                          bankroll_fraction=Decimal("0.02"), min_edge=Decimal("0.05"))
POLICY_C = SizingPolicyV2("SV2-C-full-kelly", _V, "KELLY", "C: full Kelly on the nominal model probability")
POLICY_D = SizingPolicyV2("SV2-D-half-kelly", _V, "KELLY", "D: 1/2 Kelly, nominal", kelly_fraction=Decimal("0.5"))
POLICY_E = SizingPolicyV2("SV2-E-quarter-kelly", _V, "KELLY", "E: 1/4 Kelly, nominal",
                          kelly_fraction=Decimal("0.25"))
POLICY_F = SizingPolicyV2("SV2-F-robust-kelly", _V, "KELLY",
                          "F: robust Kelly: worst-case expected log wealth over the uncertainty set", robust=True)
POLICY_G = SizingPolicyV2("SV2-G-risk-constrained-kelly", _V, "KELLY",
                          "G: nominal Kelly subject to E[(W'/W)^-lambda] <= 1, alpha 0.7, beta 0.1 "
                          "(Busseti, Ryu and Boyd 2016)",
                          drawdown_alpha=Decimal("0.7"), drawdown_beta=Decimal("0.1"))
POLICY_H = SizingPolicyV2("SV2-H-cluster-kelly", _V, "KELLY",
                          "H: joint robust 1/2 Kelly over every candidate of a cluster, shared cluster budget",
                          kelly_fraction=Decimal("0.5"), robust=True, joint=True)
# The research candidate chosen AFTER the simulation study (188 variant runs over 18 policy
# variants, docs/research/STAKE_SIZING_V2.md §9). Frozen here; a change is a new version.
POLICY_CANDIDATE = SizingPolicyV2("SV2-H-cluster-robust-rck", _V, "KELLY",
                                  "H variant: joint robust 1/2 Kelly + robust drawdown constraint (alpha 0.7, "
                                  "beta 0.1)", kelly_fraction=Decimal("0.5"), robust=True, joint=True,
                                  drawdown_alpha=Decimal("0.7"), drawdown_beta=Decimal("0.1"),
                                  robust_constraint=True)
POLICIES: tuple[SizingPolicyV2, ...] = (POLICY_A, POLICY_B, POLICY_C, POLICY_D, POLICY_E, POLICY_F, POLICY_G,
                                        POLICY_H)


# =========================================================================== core optimizer


@dataclass(frozen=True)
class CoreCandidate:
    key: str
    payout: tuple[int, ...]  # 1 where one contract pays 1, per state
    curve: CostCurve
    cap: int  # the most contracts the optimizer may consider


@dataclass(frozen=True)
class CoreProblem:
    """One cluster: W, wealth per state before new positions, the model and its uncertainty."""

    wealth: float
    base: tuple[float, ...]
    nominal: tuple[float, ...]
    uncertainty: Any  # BoxSimplexSet | VertexSet
    candidates: tuple[CoreCandidate, ...]
    budget: float | None = None  # shared cash/risk budget across the candidates (joint)


@dataclass(frozen=True)
class CoreSolution:
    counts: tuple[int, ...]  # the policy's contracts, before hard caps
    kelly_counts: tuple[int, ...]  # the nominal full-Kelly optimum within the same bounds
    robust_counts: tuple[int, ...] | None  # the robust optimum the fraction is taken of (robust policies)
    rule_binding: str
    adverse: tuple[float, ...] | None  # the admissible vector minimizing E[log W] at `counts`
    wanted: tuple[int, ...] = ()  # the policy's counts before candidate caps and the shared budget
    # Per candidate, what stopped the optimum the policy took its fraction of: "CAP" (the
    # candidate's depth/cash cap), "BUDGET" (the shared budget; computed only with `reference`),
    # or None (the objective itself).
    limited: tuple[str | None, ...] = ()


def state_wealth(problem: CoreProblem, counts: Sequence[int], *, smooth: bool = False) -> list[float]:
    """Wealth per outcome state after the new positions settle (exact, or pre-rounding cost)."""
    w = list(problem.base)
    for cand, n in zip(problem.candidates, counts):
        if n:
            cost = cand.curve.smooth(n) if smooth else cand.curve.cost(n)
            w = [x + (n - cost if a else -cost) for x, a in zip(w, cand.payout)]
    return w


def log_growth(problem: CoreProblem, counts: Sequence[int], *, robust: bool, smooth: bool = False) -> float:
    """E[log(W'/W)] under the nominal vector, or its minimum over the uncertainty set."""
    w = state_wealth(problem, counts, smooth=smooth)
    if min(w) <= 0:
        return -math.inf
    inv = 1.0 / problem.wealth
    g = [math.log(x * inv) for x in w]
    if robust:
        return problem.uncertainty.worst(g)[0]
    return sum(p * x for p, x in zip(problem.nominal, g))


def adverse_vector(problem: CoreProblem, counts: Sequence[int]) -> tuple[float, ...] | None:
    w = state_wealth(problem, counts)
    if min(w) <= 0 or problem.uncertainty is None:
        return None
    return problem.uncertainty.worst([math.log(x / problem.wealth) for x in w])[1]


def drawdown_measure(problem: CoreProblem, counts: Sequence[int], lam: float, *, robust: bool) -> float:
    """E[(W'/W)^-lambda]; its maximum over the uncertainty set when `robust`."""
    w = state_wealth(problem, counts)
    if min(w) <= 0:
        return math.inf
    h = [(x / problem.wealth) ** (-lam) for x in w]
    if robust:
        return -problem.uncertainty.worst([-x for x in h])[0]
    return sum(p * x for p, x in zip(problem.nominal, h) if p)


def cvar_loss(problem: CoreProblem, counts: Sequence[int], level: float) -> float:
    """Nominal CVaR at `level` of the one-period loss W - W', as a fraction of W."""
    w = state_wealth(problem, counts)
    losses = sorted(((problem.wealth - x) / problem.wealth, p) for x, p in zip(w, problem.nominal))
    tail, acc = 0.0, 0.0
    for loss, p in reversed(losses):
        take = min(p, level - acc)
        if take <= 0:
            break
        tail += take * loss
        acc += take
    return tail / level


def _argmax_1d(f: Callable[[int], float], hi: int, search: Callable[[int], float] | None = None) -> int:
    """The smallest maximizer of the exact objective f on the integers 0..hi.

    Up to SCAN_LIMIT every integer is scanned. Above it, cent alignment makes f concave only
    up to noise of about $0.01 per take, which can fool a bisection when the objective is flat
    near its top. The bisection therefore runs on `search`, the same objective with the
    pre-rounding (convex) cost, which is concave; the exact f then picks the best integer
    within +-REFINE_WINDOW of that point. The result is optimal for the pre-rounding problem
    and within cent rounding of the exact one."""
    if hi <= 0:
        return 0
    cache: dict[int, float] = {}

    def val(n: int) -> float:
        if n not in cache:
            cache[n] = f(n)
        return cache[n]

    if hi <= SCAN_LIMIT:
        candidates: Iterable[int] = range(hi + 1)
    else:
        g = search or f
        scache: dict[int, float] = {}

        def sval(n: int) -> float:
            if n not in scache:
                scache[n] = g(n)
            return scache[n]

        lo, up = 0, hi
        while lo < up:
            mid = (lo + up) // 2
            if sval(mid + 1) > sval(mid):
                lo = mid + 1
            else:
                up = mid
        candidates = range(max(0, lo - REFINE_WINDOW), min(hi, lo + REFINE_WINDOW) + 1)
    best_n, best = 0, val(0)
    for n in candidates:
        v = val(n)
        if v > best + 1e-13:
            best_n, best = n, v
    return best_n


def _largest_feasible(pred: Callable[[int], bool], hi: int) -> int:
    """The largest n in 0..hi with pred(n), for a predicate true on an interval starting at 0."""
    if hi <= 0 or not pred(0):
        return 0
    lo = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pred(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def affordable(curve: CostCurve, budget: float | None, hi: int) -> int:
    """The most contracts, at most `hi` and the curve's depth, whose cost fits in `budget`."""
    top = min(hi, curve.max_contracts)
    if budget is None:
        return max(0, top)
    if budget <= 0 or top <= 0:
        return 0
    lo = 0
    while lo < top:
        mid = (lo + top + 1) // 2
        if curve.cost(mid) <= budget + 1e-9:
            lo = mid
        else:
            top = mid - 1
    return lo


def _spent(problem: CoreProblem, counts: Sequence[int], skip: int = -1) -> float:
    return sum(c.curve.cost(n) for i, (c, n) in enumerate(zip(problem.candidates, counts)) if n and i != skip)


def _maximize(problem: CoreProblem, *, robust: bool) -> tuple[int, ...]:
    cands = problem.candidates
    if len(cands) == 1:
        hi = affordable(cands[0].curve, problem.budget, cands[0].cap)
        return (_argmax_1d(lambda n: log_growth(problem, (n,), robust=robust), hi,
                           lambda n: log_growth(problem, (n,), robust=robust, smooth=True)),)
    caps = [affordable(c.curve, problem.budget, c.cap) for c in cands]
    grid = 1
    for cap in caps:
        grid *= cap + 1
    if grid <= EXHAUSTIVE_LIMIT:
        return _exhaustive(problem, caps, robust=robust)
    counts = [0] * len(cands)
    for _ in range(MAX_SWEEPS):
        changed = False
        for j, cand in enumerate(cands):
            left = None if problem.budget is None else problem.budget - _spent(problem, counts, skip=j)
            hi = affordable(cand.curve, left, cand.cap)

            def f(n: int, j: int = j, smooth: bool = False) -> float:
                trial = list(counts)
                trial[j] = n
                return log_growth(problem, trial, robust=robust, smooth=smooth)

            n = _argmax_1d(f, hi, lambda n, j=j: f(n, j, True))
            if n != counts[j]:
                counts[j], changed = n, True
        if not changed:
            break
    return tuple(counts)


def _exhaustive(problem: CoreProblem, caps: Sequence[int], *, robust: bool) -> tuple[int, ...]:
    best, best_v = tuple(0 for _ in caps), log_growth(problem, [0] * len(caps), robust=robust)
    counts = [0] * len(caps)
    while True:
        j = 0
        while j < len(caps):
            if counts[j] < caps[j]:
                counts[j] += 1
                break
            counts[j] = 0
            j += 1
        if j == len(caps):
            break
        if problem.budget is not None and _spent(problem, counts) > problem.budget + 1e-9:
            continue
        v = log_growth(problem, counts, robust=robust)
        if v > best_v + 1e-13:
            best, best_v = tuple(counts), v
    return best


def _scale_down(counts: Sequence[int], ok: Callable[[Sequence[int]], bool]) -> tuple[tuple[int, ...], bool]:
    """The largest common scaling floor(s * counts), s in [0, 1], that satisfies `ok`."""
    counts = tuple(counts)
    if ok(counts):
        return counts, False
    if len(counts) == 1:
        return (_largest_feasible(lambda n: ok((n,)), counts[0]),), True
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if ok(tuple(math.floor(mid * n) for n in counts)):
            lo = mid
        else:
            hi = mid
    scaled = tuple(math.floor(lo * n) for n in counts)
    return (scaled if ok(scaled) else tuple(0 for _ in counts)), True


def nominal_edge(problem: CoreProblem, j: int) -> float | None:
    """Nominal expected net edge of one contract of candidate j: P(pays) - cost(1)."""
    cand = problem.candidates[j]
    if cand.curve.max_contracts < 1:
        return None
    return sum(p for p, a in zip(problem.nominal, cand.payout) if a) - cand.curve.cost(1)


def _relaxed(problem: CoreProblem, frac: float) -> CoreProblem:
    """The problem with every candidate cap and the shared budget divided by `frac` (within
    the priced depth): the optimum a fractional policy takes its fraction of."""
    if frac >= 1:
        return problem
    cands = tuple(replace(c, cap=min(c.curve.max_contracts, math.floor(c.cap / frac + 1e-9)))
                  for c in problem.candidates)
    return replace(problem, candidates=cands, budget=None if problem.budget is None else problem.budget / frac)


def solve(policy: SizingPolicyV2, problem: CoreProblem, *, reference: bool = True) -> CoreSolution:
    """The policy's integer contract counts for every candidate, before hard caps.

    Candidate caps and the shared budget in `problem` are limits, applied AFTER the policy's
    fraction: a fractional Kelly policy takes floor(fraction x the optimum of the problem with
    those limits divided by the fraction), then the limits are re-imposed. So 1/2 Kelly under a
    budget B is min(1/2 x Kelly, B), whether the candidates are sized jointly or one at a time.
    `reference` False skips the nominal full-Kelly reference count when the policy does not
    need it (the simulation uses it for speed); the policy's counts are unchanged."""
    k = len(problem.candidates)
    frac = float(policy.kelly_fraction) if policy.rule == "KELLY" else 1.0
    uses_kelly = policy.rule == "KELLY" and not policy.robust and frac >= 1
    kelly = _maximize(problem, robust=False) if (reference or uses_kelly) else tuple(0 for _ in range(k))
    robust_counts = None
    if policy.rule in ("FLAT_UNIT", "FIXED_FRACTION"):
        amount = float(policy.unit_amount) if policy.rule == "FLAT_UNIT" else float(policy.bankroll_fraction) * problem.wealth
        counts, left = [], problem.budget
        for j, cand in enumerate(problem.candidates):
            edge = nominal_edge(problem, j)
            n = 0
            if edge is not None and edge >= float(policy.min_edge):
                limit = amount if left is None else min(amount, left)
                n = affordable(cand.curve, limit, cand.cap)
            counts.append(n)
            if left is not None and n:
                left -= cand.curve.cost(n)
        out = wanted = tuple(counts)
        limited = tuple(None for _ in counts)
        binding = policy.rule
    else:
        search = _relaxed(problem, frac)
        base = kelly if uses_kelly else _maximize(search, robust=policy.robust)
        robust_counts = base if policy.robust else None
        free = None
        if reference and search.budget is not None:
            free = _maximize(replace(search, budget=None), robust=policy.robust)
        limited = tuple("CAP" if c.cap > 0 and n >= c.cap else
                        "BUDGET" if free is not None and free[j] > n else None
                        for j, (c, n) in enumerate(zip(search.candidates, base)))
        binding = "ROBUST_OBJECTIVE" if policy.robust else "KELLY_OBJECTIVE"
        wanted = tuple(math.floor(frac * n + 1e-9) for n in base)
        out = tuple(min(c.cap, n) for c, n in zip(problem.candidates, wanted))
        if problem.budget is not None:
            budget = problem.budget
            out, _ = _scale_down(out, lambda c: _spent(problem, c) <= budget + 1e-9)
        lam = policy.drawdown_lambda
        if lam is not None:
            out, hit = _scale_down(out, lambda c: drawdown_measure(problem, c, lam, robust=policy.robust_constraint)
                                   <= 1.0 + 1e-12)
            binding = "RISK_CONSTRAINT" if hit else binding
        if policy.cvar_level is not None:
            level, cap = float(policy.cvar_level), float(policy.cvar_max_loss)
            out, hit = _scale_down(out, lambda c: cvar_loss(problem, c, level) <= cap + 1e-12)
            binding = "CVAR_CAP" if hit else binding
    probe = out if any(out) else tuple(1 if j == 0 and c.curve.max_contracts >= 1 else 0
                                       for j, c in enumerate(problem.candidates))
    adverse = adverse_vector(problem, probe) if problem.uncertainty is not None else None
    return CoreSolution(out, kelly, robust_counts, binding, adverse, wanted, limited)


# =========================================================================== engine inputs


@dataclass(frozen=True)
class PortfolioState:
    """The risk/capital view the engine sizes against, built from `risk.assess`."""

    as_of_utc: str
    risk_policy_id: str
    bankroll: Decimal  # equity at cost basis
    tradable_cash: Decimal  # settled cash
    reserve_floor: Decimal
    open_worst_case_risk: Decimal
    available_risk_budget: Decimal  # risk.assess remaining_risk_capacity (0 during any breach)
    drawdown_headroom: Decimal  # tightest of daily, weekly and drawdown headroom after open worst case
    event_exposure: tuple[tuple[str, Decimal], ...]
    cluster_exposure: tuple[tuple[str, Decimal], ...]
    breaches: tuple[str, ...]
    max_position_risk: Decimal
    max_event_risk: Decimal
    max_cluster_risk: Decimal
    max_portfolio_risk: Decimal

    def event(self, event_id: str) -> Decimal:
        return dict(self.event_exposure).get(event_id, ZERO)

    def cluster(self, cluster_id: str) -> Decimal:
        return dict(self.cluster_exposure).get(cluster_id, ZERO)


def portfolio_state(report: RiskReport, policy: RiskPolicy) -> PortfolioState:
    """Adapt the canonical risk report; the headroom formulas are the ones `risk.assess` uses."""
    if report.policy_id != policy.policy_id:
        raise ValueError(f"report was assessed under {report.policy_id}, not {policy.policy_id}")
    open_risk = report.open_worst_case_risk
    headroom = min(policy.daily_loss_limit - report.daily_loss - open_risk,
                   policy.weekly_loss_limit - report.weekly_loss - open_risk,
                   policy.max_drawdown - report.drawdown - open_risk)
    return PortfolioState(
        as_of_utc=report.as_of_utc, risk_policy_id=policy.policy_id, bankroll=report.equity,
        tradable_cash=report.settled_cash, reserve_floor=policy.reserve_floor, open_worst_case_risk=open_risk,
        available_risk_budget=report.remaining_risk_capacity, drawdown_headroom=max(ZERO, headroom),
        event_exposure=tuple(sorted(report.risk_per_event.items())),
        cluster_exposure=tuple(sorted(report.cluster_exposure.items())), breaches=tuple(report.breaches),
        max_position_risk=policy.max_position_risk, max_event_risk=policy.max_event_risk,
        max_cluster_risk=policy.max_cluster_risk, max_portfolio_risk=policy.max_portfolio_risk)


@dataclass(frozen=True)
class PositionCandidate:
    """Buying `side` of `market`. `yes_states` are the outcome states in which the market's
    YES settles true; NO pays in every other state."""

    market: Market
    side: str
    yes_states: tuple[str, ...]
    ladder: DepthLadder | None  # the ask ladder for `side`
    event_id: str
    outcome_cluster: str


@dataclass(frozen=True)
class HeldPosition:
    """An open position in the same cluster, mapped to outcome states."""

    market_id: str
    side: str
    yes_states: tuple[str, ...]
    contracts: int
    cost: Decimal


@dataclass(frozen=True)
class SizingRequest:
    as_of_utc: str
    states: tuple[str, ...]
    candidate: PositionCandidate
    model_probabilities: tuple[float, ...] | None  # P(state), nominal
    uncertainty: Any  # BoxSimplexSet | VertexSet | None
    model_version: str | None
    model_generated_at_utc: str | None
    portfolio: PortfolioState | None
    starter: StarterVerdict | None
    held: tuple[HeldPosition, ...] = ()
    correlated_clusters: tuple[str, ...] = ()  # clusters whose dependence on this one is unknown


@dataclass(frozen=True)
class SizingConfig:
    config_id: str = "sizing-v2-config-v1"
    max_book_age: timedelta = timedelta(minutes=5)
    max_model_age: timedelta = timedelta(hours=24, minutes=30)
    max_risk_state_age: timedelta = timedelta(hours=1)
    require_fee_claim: bool = True  # a fee claim basis of NONE is UNSUPPORTED


DEFAULT_CONFIG = SizingConfig()


@dataclass(frozen=True)
class UncertaintySummary:
    method: str
    payout_probability_min: Decimal  # lowest admissible P(this position pays)
    payout_probability_max: Decimal
    detail: str


@dataclass(frozen=True)
class SizingRecommendation:
    """RESEARCH SIZING. Cap fields: dollars of worst-case loss the cap still allows. None on
    a cap means that cap does not apply (for example an eligible 7-day verdict); an unknown
    input never yields SIZE."""

    policy_id: str
    policy_version: str
    bankroll: Decimal | None
    tradable_cash: Decimal | None
    available_risk_budget: Decimal | None
    market_id: str
    outcome_id: str
    venue_id: str
    model_probability: Decimal | None  # nominal P(this position pays)
    conservative_probability: Decimal | None  # P(pays) under the binding adverse admissible vector
    probability_uncertainty: UncertaintySummary | None
    entry_price: Decimal | None  # average fill price of the recommendation (best ask at zero contracts)
    estimated_fee: Decimal | None  # schedule fee plus the claim allowance, rounded up to the cent
    estimated_slippage: Decimal | None  # gross cost above best ask * contracts (depth impact)
    expected_net_edge: Decimal | None  # nominal P(pays) - all-in cost per contract
    unconstrained_kelly_amount: Decimal | None
    fractional_kelly_amount: Decimal | None  # the policy's amount before hard caps
    liquidity_cap: Decimal | None
    position_cap: Decimal | None
    event_cap: Decimal | None
    cluster_cap: Decimal | None
    portfolio_cap: Decimal | None
    cash_horizon_cap: Decimal | None
    drawdown_cap: Decimal | None
    recommended_amount: Decimal
    recommended_contracts: int
    maximum_allowed_amount: Decimal | None
    binding_constraint: str
    secondary_constraints: tuple[str, ...]
    verdict: str
    explanation: str
    input_timestamp: str
    model_version: str | None
    input_hash: str
    output_hash: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


# =========================================================================== engine


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, float):
        return repr(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def canonical_hash(value: Any) -> str:
    text = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _money_up(x: Decimal | None) -> Decimal | None:
    return None if x is None else x.quantize(CENT, rounding=ROUND_CEILING)


def _money_down(x: Decimal | None) -> Decimal | None:
    return None if x is None else max(ZERO, x).quantize(CENT, rounding=ROUND_FLOOR)


def _prob(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(repr(min(1.0, max(0.0, x)))).quantize(PROB_GRID)


def payout_vector(states: Sequence[str], yes_states: Sequence[str], side: str) -> tuple[int, ...]:
    ys = set(yes_states)
    if side == "YES":
        return tuple(1 if s in ys else 0 for s in states)
    return tuple(0 if s in ys else 1 for s in states)


def fee_basis(venue: str, native_id: str, as_of: datetime | str, *, fee_schedule: Any = None,
              require_claim: bool = True) -> tuple[Any, FeeVerificationState | None, Decimal, str | None]:
    """(schedule, point-in-time verification, per-contract allowance, refusal reason or None).

    The schedule is `schedule_for(venue, scope)` unless one is given. Refused: an unsupported
    schedule (FEE_UNSUPPORTED) and, with `require_claim`, a claim basis of NONE (FEE_UNVERIFIED).
    A CONSERVATIVE_BOUND claim carries its documented per-contract allowance (ADR 0017)."""
    if fee_schedule is None:
        scope = KALSHI_QUADRATIC_TAKER_V1.scope_of(native_id) if venue == "kalshi" else None
        fee_schedule = schedule_for(venue, scope, as_of=as_of)
    if isinstance(fee_schedule, UnsupportedFeeSchedule) or fee_schedule.status is FeeScheduleStatus.UNSUPPORTED:
        return fee_schedule, None, ZERO, f"FEE_UNSUPPORTED: {getattr(fee_schedule, 'reason', fee_schedule.schedule_id)}"
    state = verification_at(fee_schedule, as_of, native_id)
    if require_claim and not state.claimable:
        return fee_schedule, state, ZERO, f"FEE_UNVERIFIED: {state.detail}"
    allowance = ZERO
    if state.claim_basis is ClaimBasis.CONSERVATIVE_BOUND:
        allowance = state.rounding_allowance_per_contract or ZERO
    return fee_schedule, state, allowance, None


@dataclass
class _Prepared:
    request: SizingRequest
    blocked: Verdict | None = None
    reason: str = ""
    payout: tuple[int, ...] | None = None
    curve: ExactCostCurve | None = None
    fee_state: FeeVerificationState | None = None
    schedule_id: str | None = None


def _age_check(ts: str | None, max_age: timedelta, as_of: datetime, what: str) -> str | None:
    at = parse_utc(ts)
    if at is None:
        return f"{what.upper()}_TIME_UNKNOWN: {what} has no valid timestamp"
    if at > as_of:
        return f"{what.upper()}_LOOKAHEAD: {what} at {at.isoformat()} is after the decision time"
    if freshness_assess(at, max_age=max_age, now=as_of) is not Freshness.FRESH:
        return f"{what.upper()}_STALE: {what} is older than {max_age}"
    return None


def _prepare(req: SizingRequest, config: SizingConfig, fee_schedule: Any, as_of: datetime) -> _Prepared:
    out = _Prepared(req)
    cand, market = req.candidate, req.candidate.market

    def block(verdict: Verdict, reason: str) -> _Prepared:
        out.blocked, out.reason = verdict, reason
        return out

    if cand.side not in ("YES", "NO"):
        return block(Verdict.UNSUPPORTED, f"SIDE_UNSUPPORTED: {cand.side!r}")
    if market.payoff.kind != "binary" or market.payoff.amount != Decimal(1):
        return block(Verdict.UNSUPPORTED, f"PAYOFF_UNSUPPORTED: {market.payoff.kind} paying {market.payoff.amount}")
    if not cand.yes_states or not set(cand.yes_states) <= set(req.states):
        return block(Verdict.UNSUPPORTED, "OUTCOME_MAPPING_UNKNOWN: the YES states are not in the outcome space")
    out.payout = payout_vector(req.states, cand.yes_states, cand.side)
    if all(out.payout) or not any(out.payout):
        return block(Verdict.UNSUPPORTED, "PAYOFF_DEGENERATE: the position pays in every state or in none")
    if market.status is not MarketStatus.OPEN:
        return block(Verdict.UNSUPPORTED, f"MARKET_NOT_OPEN: market status is {market.status.value}")
    if not market.rules_resolved:
        return block(Verdict.UNSUPPORTED, f"RULES_UNRESOLVED: {market.rules_detail}")
    schedule, out.fee_state, allowance, refused = fee_basis(market.venue, market.native_id, as_of,
                                                            fee_schedule=fee_schedule,
                                                            require_claim=config.require_fee_claim)
    out.schedule_id = schedule.schedule_id
    if refused:
        return block(Verdict.UNSUPPORTED, refused)

    if cand.ladder is None:
        return block(Verdict.STALE_DATA, "BOOK_MISSING: no captured ask ladder")
    if (cand.ladder.venue, cand.ladder.market_id, cand.ladder.side) != (market.venue, market.market_id, cand.side):
        raise ValueError("the ladder does not belong to this market and side")
    problem = _age_check(cand.ladder.received_at_utc, config.max_book_age, as_of, "book")
    if problem:
        return block(Verdict.STALE_DATA, problem)
    if req.model_probabilities is None:
        return block(Verdict.STALE_DATA, "MODEL_MISSING: no model probability")
    if not req.model_version:
        return block(Verdict.STALE_DATA, "MODEL_VERSION_MISSING: the model's identity is unknown")
    problem = _age_check(req.model_generated_at_utc, config.max_model_age, as_of, "model")
    if problem:
        return block(Verdict.STALE_DATA, problem)
    if req.portfolio is None:
        return block(Verdict.STALE_DATA, "RISK_STATE_MISSING: no risk report")
    problem = _age_check(req.portfolio.as_of_utc, config.max_risk_state_age, as_of, "risk_state")
    if problem:
        return block(Verdict.STALE_DATA, problem)

    if req.portfolio.breaches:
        return block(Verdict.RISK_LIMIT, f"RISK_BREACH: {', '.join(req.portfolio.breaches)}")
    if req.portfolio.available_risk_budget <= 0:
        return block(Verdict.RISK_LIMIT, "RISK_BUDGET_EXHAUSTED: remaining risk capacity is zero")
    if req.starter is None:
        return block(Verdict.CAPITAL_HORIZON, "TRADABLE_CASH_RELEASE_UNKNOWN: no STARTER_MAX_7D_V1 verdict")
    if not req.starter.eligible:
        return block(Verdict.CAPITAL_HORIZON, f"STARTER_MAX_7D_V1: {', '.join(req.starter.reasons)}")
    if req.uncertainty is None:
        return block(Verdict.UNCERTAINTY_TOO_HIGH, "UNCERTAINTY_UNKNOWN: no admissible probability set")

    out.curve = ExactCostCurve(cand.ladder, schedule, price_grid=market.price_grid, allowance_per_contract=allowance)
    if out.curve.problem:
        return block(Verdict.STALE_DATA, out.curve.problem)  # a malformed book is not usable current data
    if out.curve.max_contracts < 1:
        return block(Verdict.LIQUIDITY_LIMIT, "NO_DEPTH: the captured ladder offers no whole contract")
    return out


CAP_ORDER = ("SIZING_RULE", "LIQUIDITY", "POSITION_CAP", "EVENT_CAP", "CLUSTER_CAP", "PORTFOLIO_CAP",
             "RESERVE_FLOOR", "DRAWDOWN_CAP", "RISK_BUDGET", "CASH_HORIZON")


@dataclass
class _Book:
    """Mutable cluster state while candidates are sized one after another."""

    base: list[float]
    spent: Decimal
    event_extra: dict[str, Decimal]
    cluster_extra: Decimal


def _dollar_caps(req: SizingRequest, book: _Book) -> dict[str, Decimal]:
    pf, cand = req.portfolio, req.candidate
    assert pf is not None
    cluster_used = sum((pf.cluster(c) for c in {cand.outcome_cluster, *req.correlated_clusters}), ZERO)
    return {
        "POSITION_CAP": pf.max_position_risk,
        "EVENT_CAP": pf.max_event_risk - pf.event(cand.event_id) - book.event_extra.get(cand.event_id, ZERO),
        "CLUSTER_CAP": pf.max_cluster_risk - cluster_used - book.cluster_extra,
        "PORTFOLIO_CAP": pf.max_portfolio_risk - pf.open_worst_case_risk - book.spent,
        "RESERVE_FLOOR": pf.tradable_cash - pf.reserve_floor - book.spent,
        "DRAWDOWN_CAP": pf.drawdown_headroom - book.spent,
        "RISK_BUDGET": pf.available_risk_budget - book.spent,
    }


def _initial_book(req: SizingRequest) -> _Book:
    pf = req.portfolio
    assert pf is not None
    w = float(pf.bankroll)
    base = [w] * len(req.states)
    mapped = ZERO
    for h in req.held:
        mapped += h.cost
        pays = payout_vector(req.states, h.yes_states, h.side)
        for k, a in enumerate(pays):
            base[k] += (h.contracts if a else 0) - float(h.cost)
    # Cluster exposure the caller could not map to states is assumed lost in every state.
    unmapped = sum((pf.cluster(c) for c in {req.candidate.outcome_cluster, *req.correlated_clusters}), ZERO) - mapped
    if unmapped > 0:
        base = [x - float(unmapped) for x in base]
    return _Book(base, ZERO, {}, ZERO)


def _blocked_record(prep: _Prepared, policy: SizingPolicyV2, config: SizingConfig) -> SizingRecommendation:
    req = prep.request
    pf = req.portfolio
    ladder = req.candidate.ladder
    best = ladder.asks[0].price if ladder is not None and ladder.asks else None
    p_pay = None
    if req.model_probabilities is not None and prep.payout is not None:
        p_pay = sum(p for p, a in zip(req.model_probabilities, prep.payout) if a)
    caps = {"CASH_HORIZON": ZERO} if prep.blocked is Verdict.CAPITAL_HORIZON else {}
    return _finish(policy, config, prep, verdict=prep.blocked.value, binding=prep.blocked.value, secondary=(),
                   contracts=0, amount=ZERO, p_pay=p_pay, p_cons=None, summary=None, entry=best, fee=None,
                   slippage=None, edge=None, kelly_amount=None, policy_amount=None, caps=caps, max_allowed=None,
                   reason=prep.reason, bankroll=pf.bankroll if pf else None, cash=pf.tradable_cash if pf else None,
                   budget=pf.available_risk_budget if pf else None)


def _finish(policy: SizingPolicyV2, config: SizingConfig, prep: _Prepared, *, verdict: str, binding: str,
            secondary: tuple[str, ...], contracts: int, amount: Decimal, p_pay: float | None, p_cons: float | None,
            summary: UncertaintySummary | None, entry: Decimal | None, fee: Decimal | None,
            slippage: Decimal | None, edge: Decimal | None, kelly_amount: Decimal | None,
            policy_amount: Decimal | None, caps: Mapping[str, Decimal | None], max_allowed: Decimal | None,
            reason: str, bankroll: Decimal | None, cash: Decimal | None, budget: Decimal | None) -> SizingRecommendation:
    req = prep.request
    market = req.candidate.market
    input_hash = canonical_hash({
        "engine": ENGINE_ID, "engine_version": ENGINE_VERSION, "policy": policy, "config": config,
        "request": req, "fee_schedule_id": prep.schedule_id,
        "fee_verification": None if prep.fee_state is None else prep.fee_state.to_dict()})
    record = dict(
        policy_id=policy.policy_id, policy_version=policy.policy_version,
        bankroll=_money_down(bankroll), tradable_cash=_money_down(cash), available_risk_budget=_money_down(budget),
        market_id=market.market_id, outcome_id=f"{req.candidate.side} {market.outcome}", venue_id=market.venue,
        model_probability=_prob(p_pay), conservative_probability=_prob(p_cons), probability_uncertainty=summary,
        entry_price=None if entry is None else entry.quantize(EDGE_GRID, rounding=ROUND_CEILING),
        estimated_fee=_money_up(fee), estimated_slippage=_money_up(slippage),
        expected_net_edge=None if edge is None else edge.quantize(EDGE_GRID, rounding=ROUND_FLOOR),
        unconstrained_kelly_amount=_money_up(kelly_amount), fractional_kelly_amount=_money_up(policy_amount),
        liquidity_cap=_money_down(caps.get("LIQUIDITY")), position_cap=_money_down(caps.get("POSITION_CAP")),
        event_cap=_money_down(caps.get("EVENT_CAP")), cluster_cap=_money_down(caps.get("CLUSTER_CAP")),
        portfolio_cap=_money_down(caps.get("PORTFOLIO_CAP")), cash_horizon_cap=_money_down(caps.get("CASH_HORIZON")),
        drawdown_cap=_money_down(caps.get("DRAWDOWN_CAP")), recommended_amount=_money_up(amount) or ZERO,
        recommended_contracts=contracts, maximum_allowed_amount=_money_down(max_allowed),
        binding_constraint=binding, secondary_constraints=secondary, verdict=verdict,
        input_timestamp=req.as_of_utc, model_version=req.model_version)
    record["explanation"] = _explain(record, policy, reason, summary)
    record["input_hash"] = input_hash
    record["output_hash"] = canonical_hash({k: v for k, v in record.items() if k != "input_hash"} | {"in": input_hash})
    return SizingRecommendation(**record)


def _explain(r: Mapping[str, Any], policy: SizingPolicyV2, reason: str, summary: UncertaintySummary | None) -> str:
    parts = [f"{LABEL}. {policy.policy_id} v{policy.policy_version} [{policy.description}].",
             f"Verdict {r['verdict']}."]
    if r["verdict"] == Verdict.SIZE.value:
        parts.append(f"Buy {r['recommended_contracts']} x {r['outcome_id']} on {r['market_id']} for at most "
                     f"${r['recommended_amount']} (worst-case loss: the full cost), average price {r['entry_price']}.")
    else:
        parts.append(f"No contracts for {r['outcome_id']} on {r['market_id']}.")
    if reason:
        parts.append(f"Reason: {reason}.")
    if r["model_probability"] is not None:
        line = f"Nominal P(pays) {r['model_probability']}"
        if r["conservative_probability"] is not None and summary is not None:
            line += (f"; adverse admissible P(pays) {r['conservative_probability']} "
                     f"(set {summary.method}, range {summary.payout_probability_min}-{summary.payout_probability_max})")
        parts.append(line + ".")
    if r["expected_net_edge"] is not None:
        parts.append(f"Expected net edge per contract {r['expected_net_edge']}; fee ${r['estimated_fee']}, "
                     f"depth slippage ${r['estimated_slippage']}.")
    if r["unconstrained_kelly_amount"] is not None:
        parts.append(f"Full-Kelly amount ${r['unconstrained_kelly_amount']}; policy amount before caps "
                     f"${r['fractional_kelly_amount']}; most any cap allows ${r['maximum_allowed_amount']}.")
    parts.append(f"Binding: {r['binding_constraint']}"
                 + (f"; also below the policy size: {', '.join(r['secondary_constraints'])}." if r["secondary_constraints"]
                    else "."))
    return " ".join(parts)


def recommend(request: SizingRequest, policy: SizingPolicyV2, config: SizingConfig = DEFAULT_CONFIG, *,
              fee_schedule: Any = None) -> SizingRecommendation:
    """One candidate. `fee_schedule` overrides `schedule_for` (tests and replacement schedules)."""
    return recommend_cluster((request,), policy, config, fee_schedule=fee_schedule)[0]


def recommend_cluster(requests: Sequence[SizingRequest], policy: SizingPolicyV2,
                      config: SizingConfig = DEFAULT_CONFIG, *, fee_schedule: Any = None) -> list[SizingRecommendation]:
    """Candidates of ONE cluster, in the given order. Joint policies optimize them together;
    the others size each one conditional on the ones before it."""
    if not requests:
        return []
    first = requests[0]
    for r in requests[1:]:
        if (r.as_of_utc, r.states, r.model_probabilities, r.uncertainty, r.portfolio, r.held,
                r.candidate.outcome_cluster) != (
                first.as_of_utc, first.states, first.model_probabilities, first.uncertainty, first.portfolio,
                first.held, first.candidate.outcome_cluster):
            raise ValueError("a cluster request shares its time, states, model, uncertainty set, portfolio, "
                             "holdings and cluster")
    as_of = parse_utc(first.as_of_utc)
    if as_of is None:
        raise ValueError("as_of_utc must be a timezone-aware time")
    if first.model_probabilities is not None:
        _check_vector(first.model_probabilities, len(first.states), "model_probabilities")
    if first.uncertainty is not None:
        if tuple(first.uncertainty.states) != tuple(first.states) or len(first.uncertainty.nominal) != len(first.states):
            raise ValueError("the uncertainty set is over different states")
        if first.model_probabilities is not None and any(
                abs(a - b) > 1e-9 for a, b in zip(first.uncertainty.nominal, first.model_probabilities)):
            raise ValueError("the uncertainty set's nominal vector is not the model's")

    preps = [_prepare(r, config, fee_schedule, as_of) for r in requests]
    out: list[SizingRecommendation | None] = [None] * len(preps)
    live = []
    for i, prep in enumerate(preps):
        if prep.blocked is not None:
            out[i] = _blocked_record(prep, policy, config)
        else:
            live.append(i)
    if not live:
        return out  # type: ignore[return-value]
    book = _initial_book(first)
    if policy.joint and len(live) > 1:
        _size_joint(preps, live, policy, config, book, out)
    else:
        for i in live:
            out[i] = _size_one(preps[i], policy, config, book)
    return out  # type: ignore[return-value]


def _problem(req: SizingRequest, book: _Book, cands: tuple[CoreCandidate, ...], budget: float | None) -> CoreProblem:
    return CoreProblem(float(req.portfolio.bankroll), tuple(book.base), tuple(req.model_probabilities),  # type: ignore[union-attr]
                       req.uncertainty, cands, budget)


def _size_one(prep: _Prepared, policy: SizingPolicyV2, config: SizingConfig, book: _Book) -> SizingRecommendation:
    req, curve = prep.request, prep.curve
    assert curve is not None and prep.payout is not None and req.portfolio is not None
    pf = req.portfolio
    cash_bound = curve.max_affordable(pf.tradable_cash - book.spent)
    cand = CoreCandidate(req.candidate.market.market_id, prep.payout, curve, cash_bound)
    problem = _problem(req, book, (cand,), None)
    sol = solve(policy, problem)
    # A policy size stopped by the captured depth or by tradable cash is bound by it, not by the rule.
    clipped = None
    if sol.wanted and (sol.wanted[0] > cash_bound or sol.limited[0] == "CAP"):
        clipped = "LIQUIDITY" if cash_bound == curve.max_contracts else "TRADABLE_CASH"
    return _apply_caps(prep, policy, config, book, problem, sol, shared_binding=clipped, cash_bound=cash_bound)


def _size_joint(preps: list[_Prepared], live: list[int], policy: SizingPolicyV2, config: SizingConfig, book: _Book,
                out: list[SizingRecommendation | None]) -> None:
    """Policy H: one joint optimum under the cluster's shared budgets; per-candidate caps after."""
    req = preps[live[0]].request
    pf = req.portfolio
    assert pf is not None
    cash = pf.tradable_cash - book.spent
    cands, dollars = [], None
    for i in live:
        p = preps[i]
        assert p.curve is not None and p.payout is not None
        dollars = dollars or _dollar_caps(p.request, book)
        cands.append(CoreCandidate(p.request.candidate.market.market_id, p.payout, p.curve,
                                   p.curve.max_affordable(cash)))
    assert dollars is not None
    shared_names = ("CLUSTER_CAP", "PORTFOLIO_CAP", "RESERVE_FLOOR", "DRAWDOWN_CAP", "RISK_BUDGET")
    tightest = min(shared_names, key=lambda n: (dollars[n], shared_names.index(n)))
    budget = float(max(ZERO, min(dollars[tightest], cash)))
    if dollars[tightest] > cash:
        tightest = "TRADABLE_CASH"
    problem = _problem(req, book, tuple(cands), budget)
    sol = solve(policy, problem)
    # The unconstrained Kelly reference: the joint nominal optimum limited only by depth and cash.
    free_kelly = _maximize(_problem(req, book, tuple(cands), float(cash)), robust=False)
    for j, i in enumerate(live):
        single = CoreSolution((sol.counts[j],), (free_kelly[j],),
                              None if sol.robust_counts is None else (sol.robust_counts[j],), sol.rule_binding,
                              sol.adverse, (sol.wanted[j],), (sol.limited[j],))
        one = CoreProblem(problem.wealth, tuple(book.base), problem.nominal, problem.uncertainty, (cands[j],), None)
        stop = None
        if sol.limited[j] == "CAP":
            stop = "LIQUIDITY" if cands[j].cap == cands[j].curve.max_contracts else "TRADABLE_CASH"
        elif sol.limited[j] == "BUDGET" or (sol.wanted[j] > sol.counts[j]
                                            and sol.rule_binding not in ("RISK_CONSTRAINT", "CVAR_CAP")):
            stop = tightest
        out[i] = _apply_caps(preps[i], policy, config, book, one, single, shared_binding=stop,
                             cash_bound=cands[j].cap)


def _apply_caps(prep: _Prepared, policy: SizingPolicyV2, config: SizingConfig, book: _Book, problem: CoreProblem,
                sol: CoreSolution, *, shared_binding: str | None, cash_bound: int) -> SizingRecommendation:
    req, curve = prep.request, prep.curve
    assert curve is not None and prep.payout is not None and req.portfolio is not None
    pf = req.portfolio
    dollars: dict[str, Decimal | None] = dict(_dollar_caps(req, book))
    dollars["LIQUIDITY"] = curve.total(curve.max_contracts)
    dollars["CASH_HORIZON"] = None  # an eligible STARTER_MAX_7D_V1 verdict imposes no dollar cap
    policy_n = sol.counts[0]
    wanted = sol.wanted[0] if sol.wanted else policy_n
    limits: list[tuple[str, int]] = [("SIZING_RULE", policy_n), ("LIQUIDITY", curve.max_contracts)]
    for name in CAP_ORDER[2:-1]:
        limits.append((name, curve.max_affordable(dollars[name])))  # type: ignore[arg-type]
    by_name = dict(limits)
    final = min(v for _, v in limits)
    cap_limits = [(n, v) for n, v in limits if n != "SIZING_RULE"]
    max_allowed_n = min(v for _, v in cap_limits)
    if shared_binding is not None and final == policy_n:
        binding = shared_binding  # depth, cash or a shared budget stopped the policy's size
    else:
        binding = next(n for n in CAP_ORDER if n in by_name and by_name[n] == final)
    secondary = tuple(n for n, v in sorted(cap_limits, key=lambda x: (x[1], CAP_ORDER.index(x[0])))
                      if n != binding and v < wanted)

    edge1 = nominal_edge(problem, 0)
    kelly_n = sol.kelly_counts[0]
    if final > 0:
        verdict = Verdict.SIZE
    elif edge1 is None or edge1 <= 0:
        verdict, binding = Verdict.ZERO_EDGE, "NO_EDGE"
    elif cash_bound == 0:
        verdict, binding = Verdict.RISK_LIMIT, "TRADABLE_CASH"  # an edge, but cash buys no contract
    elif policy.rule == "KELLY" and kelly_n == 0:
        verdict, binding = Verdict.ZERO_EDGE, "NO_GROWTH"  # an edge per contract, but no log-growth benefit
    elif policy_n == 0 and sol.rule_binding in ("RISK_CONSTRAINT", "CVAR_CAP"):
        verdict, binding = Verdict.RISK_LIMIT, sol.rule_binding
    elif policy_n == 0 and (wanted > 0 or shared_binding is not None):
        # the policy wanted contracts; depth, cash or a shared budget left none
        binding = shared_binding or binding
        verdict = Verdict.LIQUIDITY_LIMIT if binding == "LIQUIDITY" else Verdict.RISK_LIMIT
    elif policy_n == 0:
        if policy.robust and sol.robust_counts is not None and sol.robust_counts[0] == 0:
            verdict, binding = Verdict.UNCERTAINTY_TOO_HIGH, "ROBUST_OBJECTIVE"
        elif policy.rule == "KELLY":
            verdict, binding = Verdict.RISK_LIMIT, "SIZING_RULE"  # the fraction rounds below one contract
        elif edge1 < float(policy.min_edge):
            verdict, binding = Verdict.ZERO_EDGE, "MIN_EDGE"  # below the rule's entry threshold
        else:
            verdict, binding = Verdict.RISK_LIMIT, policy.rule  # the unit buys no whole contract
    elif binding == "LIQUIDITY":
        verdict = Verdict.LIQUIDITY_LIMIT
    else:
        verdict = Verdict.RISK_LIMIT
    if final > 0 and binding == "SIZING_RULE" and sol.rule_binding in ("RISK_CONSTRAINT", "CVAR_CAP"):
        binding = sol.rule_binding

    p_pay = sum(p for p, a in zip(problem.nominal, prep.payout) if a)
    probe = final if final > 0 else 1
    adverse = adverse_vector(problem, (probe,))
    p_cons = None if adverse is None else sum(v for v, a in zip(adverse, prep.payout) if a)
    lo_v = problem.uncertainty.worst([float(a) for a in prep.payout])
    hi_v = problem.uncertainty.worst([-float(a) for a in prep.payout])
    summary = UncertaintySummary(problem.uncertainty.method, _prob(lo_v[0]), _prob(-hi_v[0]),
                                 problem.uncertainty.detail)

    ladder = req.candidate.ladder
    assert ladder is not None
    best_ask = ladder.asks[0].price
    priced = curve.depth_cost(probe)
    total = curve.total(final) if final > 0 else ZERO
    entry = priced.fill.average_price if priced is not None else best_ask
    fee = slippage = edge = None
    if priced is not None:
        fee = priced.fee + curve.allowance * probe
        slippage = priced.fill.gross_cost - best_ask * probe
        all_in = curve.total(probe) / probe  # type: ignore[operator]
        edge = Decimal(repr(p_pay)) - all_in
    kelly_amount = curve.total(kelly_n)
    policy_amount = curve.total(min(wanted, curve.max_contracts))
    max_allowed = curve.total(max_allowed_n)

    if final > 0:  # the recommendation occupies the budgets of the next candidate in the cluster
        book.spent += total
        book.event_extra[req.candidate.event_id] = book.event_extra.get(req.candidate.event_id, ZERO) + total
        book.cluster_extra += total
        for k, a in enumerate(prep.payout):
            book.base[k] += (final if a else 0) - float(total)
    return _finish(policy, config, prep, verdict=verdict.value, binding=binding, secondary=secondary,
                   contracts=final, amount=total, p_pay=p_pay, p_cons=p_cons, summary=summary, entry=entry, fee=fee,
                   slippage=slippage, edge=edge, kelly_amount=kelly_amount, policy_amount=policy_amount,
                   caps=dollars, max_allowed=max_allowed, reason="", bankroll=pf.bankroll, cash=pf.tradable_cash,
                   budget=pf.available_risk_budget)
