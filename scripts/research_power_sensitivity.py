"""EXP-002 sample-size SENSITIVITY ranges under stated assumptions. It is not a power analysis.

    python scripts/research_power_sensitivity.py            # Markdown tables (the default grid)
    python scripts/research_power_sensitivity.py --json     # the same rows as JSON
    python scripts/research_power_sensitivity.py --null-check   # the markout statistics under a no-information null
    python scripts/research_power_sensitivity.py --gate-v3-validation [--reps N] [--json]
        # adversarial false-pass simulation of the EXP-002 gate v3 and of the spread candidate it rejected

It reads no data and makes no request. Every input is an assumption stated in the output, so the
result is a *range* of what a design would need, never a sample size to freeze. The frozen value
comes later, from a logged development pilot (docs/research/RESEARCH_UNBLOCKING_DECISIONS.md §A.G).

Model (one primary per-game statistic, cluster = NFL week):
- One statistic per game (both team sides of one game are complements, so they are one unit;
  books and horizons are nested inside the game and are averaged or chosen, never counted).
- Games in one NFL week share news, weather and market-wide flows. The intra-week correlation
  `icc` is UNKNOWN; the design effect is `DE = 1 + (m - 1) * icc`, with `m` the analysed games
  per week.
- Effective independent games for a one-sample test of a mean `effect` with per-game standard
  deviation `sd`: `n_eff = ((z(1 - alpha) + z(power)) * sd / effect) ** 2` (normal approximation,
  one-sided `alpha`). Games needed = `n_eff * DE`; weeks needed = games needed / `m`.
- A consequence worth seeing: as `m` grows, weeks needed falls towards `n_eff * icc` and no lower.
  More games per week cannot buy past week-level dependence.
- The inverse (`mde`) is the smallest effect detectable with a given number of weeks.

Limits: a normal approximation with an exchangeable within-week correlation; no multiplicity
adjustment (divide `alpha` by the number of registered variants, or use the variant budget);
no interim looks; `m` is an average; `sd` and `icc` must come from development data or stay a
range.

Null-bias simulation (`simulate_null`, `--null-check`): under a model where the latent value is a
martingale, the consensus knows only the current latent value (no information about later moves)
and each Kalshi mid is the latent value plus noise, it reports the mean of three per-game
statistics:
- `naive`: sign(c - k6) * (k1 - k6) on one book. It is **biased upward under the null**, because the
  noise in k6 enters both the sign and the base (mean reversion of mid noise).
- `cross` (PROPOSED primary): the gap sign from one team market's book and the markout from the other
  team market's book (converted to the same team's units), averaged over both assignments. Unbiased
  when the two books' noises are independent.
- `placebo` (PROPOSED required bias check): `cross` with the consensus replaced by the signal book's own
  earlier (T-24h) mid, a Kalshi-only signal with no consensus information. Zero under the model; away from
  zero when the two books' noises are correlated (for example mirror-quoted) or Kalshi has its own
  momentum or reversal.
Stdlib only, deterministic (fixed seeds).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass
from statistics import NormalDist

VERSION = "research-power-sensitivity-v1"
LABEL = "SENSITIVITY RANGE UNDER STATED ASSUMPTIONS - NOT A POWER ANALYSIS, NOT A FROZEN SAMPLE SIZE"
_N = NormalDist()


def z(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability {p!r} must be in (0, 1)")
    return _N.inv_cdf(p)


def effective_n(effect: float, sd: float, *, alpha: float = 0.05, power: float = 0.80) -> float:
    """Independent units for a one-sided one-sample test of mean `effect` (> 0) with unit SD `sd`."""
    if effect <= 0 or sd <= 0:
        raise ValueError("effect and sd must be positive")
    return ((z(1 - alpha) + z(power)) * sd / effect) ** 2


def design_effect(m: float, icc: float) -> float:
    if m < 1 or not 0 <= icc <= 1:
        raise ValueError("m must be >= 1 and icc in [0, 1]")
    return 1 + (m - 1) * icc


def units_per_week(games_per_week: float, eligible_fraction: float, qualifying_fraction: float) -> float:
    """Analysed games per week: scheduled games x the fraction that pair and pass the rules x the fraction
    that qualify for the endpoint (1.0 when every eligible game is analysed, as for a markout or calibration
    endpoint; the episode rate for an economics endpoint)."""
    for name, v in (("eligible_fraction", eligible_fraction), ("qualifying_fraction", qualifying_fraction)):
        if not 0 <= v <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    if games_per_week <= 0:
        raise ValueError("games_per_week must be positive")
    return games_per_week * eligible_fraction * qualifying_fraction


def _de(m: float, icc: float) -> float:
    """The design effect for an average of `m` analysed games a week; below one a week, weeks are mostly
    singletons, so no inflation (DE = 1)."""
    return design_effect(max(m, 1.0), icc)


def weeks_required(effect: float, sd: float, icc: float, m: float, *, alpha: float = 0.05,
                   power: float = 0.80) -> float | None:
    """Weeks of analysed games needed; None when no game is analysed at all (no design)."""
    if m <= 0:
        return None
    return effective_n(effect, sd, alpha=alpha, power=power) * _de(m, icc) / m


def mde(weeks: float, sd: float, icc: float, m: float, *, alpha: float = 0.05, power: float = 0.80) -> float | None:
    """Smallest mean effect detectable with `weeks` weeks of `m` analysed games a week."""
    if m <= 0 or weeks <= 0:
        return None
    return (z(1 - alpha) + z(power)) * sd * math.sqrt(_de(m, icc) / (weeks * m))


@dataclass(frozen=True)
class Row:
    endpoint: str
    sd: float
    effect: float
    icc: float
    games_per_week: float
    eligible_fraction: float
    qualifying_fraction: float
    analysed_per_week: float
    n_eff: float
    design_effect: float | None
    games_needed: float | None
    weeks_needed: float | None
    weeks_floor_icc: float  # n_eff * icc: the floor however many games a week are analysed
    feasible_in_weeks: float  # the planning horizon the row is judged against
    feasible: bool | None


# Assumption grids (ASSUMPTIONS, not measurements). Each is stated in the output.
# Per-game SD of the primary markout statistic (the signed change of the Kalshi mid, in probability points,
# from the decision horizon to the later horizon): UNKNOWN until pilot data; range spans quiet to volatile.
# The top of the range (6-8 cents) covers games repriced by inactive/injury news between T-6h and T-60m.
MARKOUT_SD = (0.01, 0.02, 0.04, 0.06, 0.08)
# 0.25 cent is at or below half a tick of mid resolution (a mid on a 1-cent grid moves in 0.5-cent steps):
# it is kept as a lower-edge scenario, not as a detectable price move of a single game.
MARKOUT_EFFECT = (0.0025, 0.005, 0.01)
# Per-contract P&L of a binary contract held to settlement: SD = sqrt(p (1 - p)) <= 0.5, a mathematical
# bound (ties and fair prices only lower it), so 0.5 is conservative and 0.45 is near p = 0.3 or 0.7.
OUTCOME_SD = (0.45, 0.5)
OUTCOME_EFFECT = (0.01, 0.02, 0.05)
ICC = (0.0, 0.02, 0.05, 0.10)
GAMES_PER_WEEK = 15.0  # about 272 regular-season games over 18 weeks; byes make it 13-16
ELIGIBLE = (0.3, 0.6, 0.9)  # fraction of due primary horizons that pair and pass the rules: UNKNOWN
EPISODE_RATE = (0.1, 0.3)  # fraction of eligible games whose after-cost edge qualifies: UNKNOWN
# Planning horizon: about 14 regular-season weeks remain after one pilot week if collection starts in
# NFL week 4 (kickoffs from 2026-10-01); playoffs add 13 games over 4 weeks. An assumption, not a schedule.
SEASON_WEEKS_AVAILABLE = 14.0


def grid(*, alpha: float = 0.05, power: float = 0.80, horizon_weeks: float = SEASON_WEEKS_AVAILABLE) -> list[Row]:
    rows: list[Row] = []
    plans = [("markout (primary, PROPOSED)", MARKOUT_SD, MARKOUT_EFFECT, (1.0,)),
             ("hold-to-settlement P&L per contract (secondary)", OUTCOME_SD, OUTCOME_EFFECT, EPISODE_RATE)]
    for endpoint, sds, effects, rates in plans:
        for sd in sds:
            for effect in effects:
                for icc in ICC:
                    for elig in ELIGIBLE:
                        for rate in rates:
                            m = units_per_week(GAMES_PER_WEEK, elig, rate)
                            n = effective_n(effect, sd, alpha=alpha, power=power)
                            w = weeks_required(effect, sd, icc, m, alpha=alpha, power=power)
                            de = None if m <= 0 else _de(m, icc)
                            rows.append(Row(endpoint, sd, effect, icc, GAMES_PER_WEEK, elig, rate, round(m, 4),
                                            round(n, 2), None if de is None else round(de, 4),
                                            None if w is None else round(w * m, 1),
                                            None if w is None else round(w, 2), round(n * icc, 2), horizon_weeks,
                                            None if w is None else w <= horizon_weeks))
    return rows


def summary(rows: list[Row]) -> dict[str, dict[str, float | int | None]]:
    out: dict[str, dict[str, float | int | None]] = {}
    for endpoint in sorted({r.endpoint for r in rows}):
        mine = [r for r in rows if r.endpoint == endpoint]
        weeks = [r.weeks_needed for r in mine if r.weeks_needed is not None]
        out[endpoint] = {"scenarios": len(mine), "feasible_in_horizon": sum(1 for r in mine if r.feasible),
                         "min_weeks": min(weeks) if weeks else None, "max_weeks": max(weeks) if weeks else None}
    return out


# --------------------------------------------------------------------------- null-bias simulation


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _round_to(x: float, tick: float) -> float:
    return x if tick <= 0 else round(x / tick) * tick


@dataclass(frozen=True)
class NullCheck:
    noise_sd: float  # SD of each book's mid around the latent value
    book_noise_corr: float  # correlation of the two books' noises at the same time (1 = mirror-quoted)
    tick: float  # rounding of each mid (0 = none)
    informative: bool  # False: the no-information null; True: the consensus knows the later latent value
    n: int
    seed: int
    naive_mean: float
    naive_se: float
    cross_mean: float
    cross_se: float
    placebo_mean: float
    placebo_se: float


def simulate_null(*, noise_sd: float, book_noise_corr: float = 0.0, tick: float = 0.0, informative: bool = False,
                  n: int = 40_000, seed: int = 20260925, move_sd: float = 0.02, early_move_sd: float = 0.03,
                  consensus_sd: float = 0.01) -> NullCheck:
    """Means (and standard errors) of the naive, cross-book and placebo markout statistics per game.

    Model: latent L24 ~ U(0.3, 0.7); L6 = L24 + N(0, early_move_sd); L1 = L6 + N(0, move_sd) (a martingale:
    under the null nothing predicts L1 - L6). Consensus c = L6 + N(0, consensus_sd), or L1 + N(0,
    consensus_sd) when `informative`. Book mids (home-team units): H_t = L_t + e_t, A_t = L_t + f_t, with
    corr(e_t, f_t) = `book_noise_corr`, independent across t, each rounded to `tick`."""
    if not (noise_sd >= 0 and -1 <= book_noise_corr <= 1 and n >= 2):
        raise ValueError("noise_sd >= 0, book_noise_corr in [-1, 1], n >= 2")
    rng = random.Random(seed)
    rho, rest = book_noise_corr, math.sqrt(max(0.0, 1 - book_noise_corr ** 2))

    def books(latent: float) -> tuple[float, float]:
        z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1)
        return (_round_to(latent + noise_sd * z1, tick), _round_to(latent + noise_sd * (rho * z1 + rest * z2), tick))

    sums = {"naive": [0.0, 0.0], "cross": [0.0, 0.0], "placebo": [0.0, 0.0]}
    for _ in range(n):
        l24 = rng.uniform(0.3, 0.7)
        l6 = l24 + rng.gauss(0, early_move_sd)
        l1 = l6 + rng.gauss(0, move_sd)
        c = (l1 if informative else l6) + rng.gauss(0, consensus_sd)
        h24, a24 = books(l24)
        h6, a6 = books(l6)
        h1, a1 = books(l1)
        values = {
            "naive": _sign(c - h6) * (h1 - h6),
            "cross": 0.5 * (_sign(c - h6) * (a1 - a6) + _sign(c - a6) * (h1 - h6)),
            "placebo": 0.5 * (_sign(h24 - h6) * (a1 - a6) + _sign(a24 - a6) * (h1 - h6)),
        }
        for k, v in values.items():
            sums[k][0] += v
            sums[k][1] += v * v

    def mean_se(k: str) -> tuple[float, float]:
        total, sq = sums[k]
        mean = total / n
        var = max(0.0, (sq - n * mean * mean) / (n - 1))
        return mean, math.sqrt(var / n)

    (nm, ns), (cm, cs), (pm, pse) = mean_se("naive"), mean_se("cross"), mean_se("placebo")
    return NullCheck(noise_sd, book_noise_corr, tick, informative, n, seed, nm, ns, cm, cs, pm, pse)


NULL_CHECK_GRID = ((0.0025, 0.0, 0.0), (0.005, 0.0, 0.0), (0.005, 0.0, 0.01),
                   (0.005, 0.25, 0.0), (0.005, 0.5, 0.0), (0.005, 0.75, 0.0), (0.005, 1.0, 0.0),
                   (0.01, 0.0, 0.0), (0.01, 0.25, 0.0), (0.01, 0.5, 0.0), (0.01, 1.0, 0.0))
SQRT_2_OVER_PI = math.sqrt(2 / math.pi)


def naive_bias(noise_sd: float, gap_sd: float) -> float:
    """Approximate bias of the old same-book statistic sign(c - k6) * (k1 - k6) under the null.

    With the gap g = c - k6 and the book noise e (SD `noise_sd`) jointly normal, cov(e, g) = -noise_sd**2,
    so E[-e * sign(g)] = noise_sd**2 * sqrt(2/pi) / sd(g). `gap_sd` is the observed SD of the gap (noise
    included). Both inputs are feature-side quantities: no label is needed."""
    if noise_sd < 0 or gap_sd <= 0:
        raise ValueError("noise_sd >= 0 and gap_sd > 0")
    return noise_sd ** 2 * SQRT_2_OVER_PI / gap_sd


def rho_max(min_effect: float, noise_sd: float, gap_sd: float, *, tolerable_fraction: float = 0.25) -> float:
    """The largest cross-book noise correlation the cross-book primary can tolerate.

    The cross-book statistic's remaining bias is about rho x naive_bias. Tolerating at most
    `tolerable_fraction` of the pre-registered minimum effect gives
    rho_max = tolerable_fraction * min_effect / naive_bias(noise_sd, gap_sd), capped at 1."""
    if min_effect <= 0 or not 0 < tolerable_fraction <= 1:
        raise ValueError("min_effect > 0 and tolerable_fraction in (0, 1]")
    bias = naive_bias(noise_sd, gap_sd)
    return 1.0 if bias == 0 else min(1.0, tolerable_fraction * min_effect / bias)


def null_check_markdown(n: int = 40_000, consensus_sd: float = 0.01) -> str:
    lines = ["# Markout statistics under a no-information null (simulation; model in the module docstring)", "",
             "Means in cents per game (standard error). Under the null a valid statistic has mean 0. `rho x naive` "
             "is the approximation of the cross-book bias; `analytic naive` is noise^2 * sqrt(2/pi) / sd(gap).", "",
             "| mid noise SD | book-noise corr (rho) | tick | naive | analytic naive | cross (primary) | rho x naive "
             "| placebo (supplementary) |",
             "|---|---|---|---|---|---|---|---|"]
    for noise, corr, tick in NULL_CHECK_GRID:
        r = simulate_null(noise_sd=noise, book_noise_corr=corr, tick=tick, n=n, consensus_sd=consensus_sd)
        analytic = naive_bias(noise, math.sqrt(consensus_sd ** 2 + noise ** 2))
        lines.append(f"| {noise * 100:.2f}c | {corr} | {tick * 100:.0f}c | {r.naive_mean * 100:+.3f} "
                     f"({r.naive_se * 100:.3f}) | {analytic * 100:+.3f} | {r.cross_mean * 100:+.3f} "
                     f"({r.cross_se * 100:.3f}) | {corr * r.naive_mean * 100:+.3f} | {r.placebo_mean * 100:+.3f} "
                     f"({r.placebo_se * 100:.3f}) |")
    lines += ["", "Worked rho_max (tolerable bias = 1/4 of the minimum effect; gap SD = sqrt(1c^2 + noise^2)):", "",
              "| minimum effect | mid noise SD | naive bias | rho_max |", "|---|---|---|---|"]
    for effect in (0.0025, 0.005, 0.01):
        for noise in (0.0025, 0.005, 0.01):
            gap = math.sqrt(consensus_sd ** 2 + noise ** 2)
            lines.append(f"| {effect * 100:.2f}c | {noise * 100:.2f}c | {naive_bias(noise, gap) * 100:.3f}c | "
                         f"{rho_max(effect, noise, gap):.2f} |")
    return "\n".join(lines) + "\n"


def markdown(rows: list[Row], *, alpha: float, power: float) -> str:
    horizon = rows[0].feasible_in_weeks if rows else SEASON_WEEKS_AVAILABLE
    lines = [f"# {LABEL}", "", f"`{VERSION}`; alpha {alpha} one-sided, power {power}; planning horizon "
             f"{horizon} weeks; games per week {GAMES_PER_WEEK}. Every value below is an assumption "
             "or a consequence of one.", ""]
    for endpoint, s in summary(rows).items():
        lines.append(f"- **{endpoint}**: {s['feasible_in_horizon']} of {s['scenarios']} scenarios fit the horizon; "
                     f"weeks needed range {s['min_weeks']} to {s['max_weeks']}.")
    lines += ["", "| endpoint | sd | effect | icc | eligible | qualifying | games/wk analysed | n_eff | DE | "
              "games | weeks | floor n_eff*icc | fits |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.endpoint} | {r.sd} | {r.effect} | {r.icc} | {r.eligible_fraction} | "
                     f"{r.qualifying_fraction} | {r.analysed_per_week} | {r.n_eff} | {r.design_effect} | "
                     f"{r.games_needed} | {r.weeks_needed} | {r.weeks_floor_icc} | "
                     f"{'-' if r.feasible is None else ('yes' if r.feasible else 'no')} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- gate v3 adversarial validation
#
# Owner directive 2026-09-28 §7C; docs/research/EXP002_GATE_V3.md. A data-generating process (DGP) for the
# label-free gate inputs (T-24h and T-6h paired books of both team markets, their spreads, the consensus) and for
# the T-60m books, under the A.A null: the latent value V is a martingale and the consensus knows V6 up to its own
# independent deviation w, nothing about V1 - V6. Each book's quote is a tick interval (plus optional widening)
# around the market maker's quoted fair q = V + error; the scenarios change only the error and the quoting. The
# TRUE bias of the cross-book markout, E[y], comes from a separate large simulation of the same DGP (its own
# seed); the gates see only small label-free samples (their own seeds). A false pass is a PASS (candidate) or a
# bound below the tolerable level (v3 conditional) when the true bias exceeds the tolerable 1/4 of delta_min.
# Every scenario and seed was fixed before any gate result was looked at; none is tuned to a gate outcome.

GATE_VALIDATION_VERSION = "exp002-gate-v3-validation-v1"
GATE_VALIDATION_SEED = 20260928  # gate samples; independent of the unit tests' seeds and of the bootstrap seed
TRUTH_SEED = 20261001  # the true-bias simulation
TRUTH_GAMES = 60_000
GATE_DELTAS = (0.0025, 0.005, 0.01)
TOLERABLE = 0.25
VALIDATION_RESAMPLES = 200  # bootstrap resamples per simulated gate run (the gate's own default is 2000)
ACCEPTANCE_FALSE_PASS = 0.10


@dataclass(frozen=True)
class GateScenario:
    name: str
    tests: str  # which directive §7C case it covers
    weeks: int = 4
    games_per_week: int = 15
    tick: float = 0.01
    widen_max_ticks: int = 0  # each book independently widened by 0..n ticks on each side (value stays inside)
    skew_ticks: int = 0  # one shared side widened by this many ticks per game-time (asymmetric spreads)
    quote_around_value: bool = False  # True: the spread brackets V itself (W holds); False: it brackets q = V + err
    sigma_common: float = 0.0  # error shared by both team books (one market maker / one upstream source)
    sigma_idio: float = 0.0  # error of one book
    week_common_sd: float = 0.0  # error shared by every book of one NFL week (cross-game dependence)
    sticky_half_band: float = 0.0  # shared hysteresis error, uniform in +-band
    stale_prob: float = 0.0  # probability that both books show a stale fair (the value moved since)
    stale_move_sd: float = 0.03
    frozen_since_t24_prob: float = 0.0  # T-6h quote identical to the T-24h quote (zero observed movement)
    persistence: float = 0.0  # share of the T-6h error still present at T-60m
    capture_gap_move_sd: float = 0.0  # latent move between the home and away book captures of one run
    consensus_sd: float = 0.015  # w = c - V6
    consensus_week_sd: float = 0.0
    early_move_sd: float = 0.03  # V24 -> V6
    move_sd: float = 0.02  # V6 -> V1
    missing_prob: float = 0.0  # a T-6h pair missing
    missing_if_stale_prob: float | None = None  # informative missingness: the rate for a stale game


# Revision 2 (before any result was used for a decision, after one 10-rep smoke run): the first set gave the
# stale, sticky, frozen, week and persistence cases no book-specific error, so both books quoted the same tick
# interval, every dispersion was exactly zero and those cases exercised only the mirror-quoting path. They now
# carry 0.1c of book-specific error (as real books do), and two near-mirror and within-spread cases were added.
# The gate v3 code was not changed after the smoke run.
_IDIO = 0.001
GATE_SCENARIOS = (
    GateScenario("w_holds_mirror_one_tick", "discreteness; mirror quoting (both books the tick interval around V)",
                 quote_around_value=True),
    GateScenario("w_holds_varied_widths", "control where assumption W holds: V inside each book's spread",
                 quote_around_value=True, widen_max_ticks=1),
    GateScenario("w_holds_varied_widths_wide_gaps", "control where W holds, consensus far from Kalshi (sd 6c)",
                 quote_around_value=True, widen_max_ticks=1, consensus_sd=0.06),
    GateScenario("asymmetric_spreads_within", "asymmetric spreads: a shared 1-tick skew plus 0-1 tick widening, V "
                 "inside the spread (W holds)", quote_around_value=True, skew_ticks=1, widen_max_ticks=1),
    GateScenario("asymmetric_spreads_within_wide_gaps", "the same, consensus far from Kalshi (sd 6c)",
                 quote_around_value=True, skew_ticks=1, widen_max_ticks=1, consensus_sd=0.06),
    GateScenario("review_grid_rho_055", "the #119 review grid: 1c noise, book-noise correlation 0.55, 1-tick quotes",
                 sigma_common=0.01 * math.sqrt(0.55), sigma_idio=0.01 * math.sqrt(0.45)),
    GateScenario("shared_upstream", "correlated team-market quoting / a shared upstream source (1.5c shared error, "
                 "0.2c book-specific)", sigma_common=0.015, sigma_idio=0.002),
    GateScenario("shared_upstream_near_mirror", "a shared upstream source with near-mirror books (1.5c shared, 0.1c "
                 "book-specific)", sigma_common=0.015, sigma_idio=_IDIO),
    GateScenario("shared_upstream_wide_gaps", "shared upstream error with consensus far from Kalshi (sd 6c)",
                 sigma_common=0.015, sigma_idio=0.002, consensus_sd=0.06),
    GateScenario("narrow_but_stale", "narrow but stale quotes: 35% of games quote a fair 3c-SD old",
                 stale_prob=0.35, sigma_idio=_IDIO),
    GateScenario("narrow_but_stale_wide_gaps", "narrow but stale quotes, consensus far from Kalshi (sd 6c)",
                 stale_prob=0.35, consensus_sd=0.06, sigma_idio=_IDIO),
    GateScenario("sticky_band", "sticky prices: a shared hysteresis band of +-1.5c", sticky_half_band=0.015,
                 sigma_idio=_IDIO),
    GateScenario("zero_movement_hidden", "zero observed movement with hidden uncertainty: half the T-6h quotes "
                 "unchanged since T-24h while V moved (3c SD)", frozen_since_t24_prob=0.5, sigma_idio=_IDIO),
    GateScenario("common_move_between_captures", "a common-value move between the two captures (1.5c) inflating "
                 "the dispersion, with a 1c shared error", sigma_common=0.01, capture_gap_move_sd=0.015),
    GateScenario("discreteness_small_noise", "price discreteness with 0.1c book-specific error", sigma_idio=_IDIO),
    GateScenario("week_dependence", "cross-game and cross-week dependence: 1c week-shared error, 1c week-shared "
                 "consensus deviation, 0.5c game-shared error", week_common_sd=0.01, consensus_week_sd=0.01,
                 sigma_common=0.005, sigma_idio=_IDIO),
    GateScenario("partial_persistence", "sticky error that half persists to T-60m (1.5c shared)", sigma_common=0.015,
                 persistence=0.5, sigma_idio=_IDIO),
    GateScenario("small_sample_missing", "small samples and missing horizons: 2 weeks x 8 games, 40% of T-6h pairs "
                 "missing, 80% for stale games", weeks=2, games_per_week=8, stale_prob=0.35, missing_prob=0.4,
                 missing_if_stale_prob=0.8, sigma_idio=_IDIO),
)


def _quote(fair: float, tick: float, below: int, above: int) -> tuple[float, float]:
    """The tick interval containing `fair`, widened by `below` / `above` ticks, clamped to (0, 1)."""
    base = math.floor(fair / tick + 1e-9) * tick
    bid, ask = base - below * tick, base + (1 + above) * tick
    bid, ask = max(tick, bid), min(1 - tick, ask)
    if ask <= bid:
        bid, ask = ask - tick, ask
    return round(bid, 6), round(ask, 6)


class _GameDraw:
    """One game of one scenario: latent path, consensus, the four T-24h / T-6h books and the two T-60m books."""

    def __init__(self, sc: GateScenario, rng: random.Random, week_err: dict[str, float], consensus_week: float):
        self.sc, self.rng = sc, rng
        v24 = rng.uniform(0.25, 0.75)
        v6 = v24 + rng.gauss(0, sc.early_move_sd)
        v1 = v6 + rng.gauss(0, sc.move_sd)
        self.v = {"T-24h": v24, "T-6h": v6, "T-60m": v1}
        self.c = v6 + rng.gauss(0, sc.consensus_sd) + consensus_week
        self.stale = rng.random() < sc.stale_prob
        self.frozen = rng.random() < sc.frozen_since_t24_prob
        self.books: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
        err6 = None
        for horizon in ("T-24h", "T-6h", "T-60m"):
            shared = rng.gauss(0, sc.sigma_common) + week_err[horizon]
            if sc.sticky_half_band:
                shared += rng.uniform(-sc.sticky_half_band, sc.sticky_half_band)
            if horizon == "T-6h" and self.stale:
                shared -= rng.gauss(0, sc.stale_move_sd)  # the value moved since the quote was set
            errs = [shared + rng.gauss(0, sc.sigma_idio) for _ in range(2)]
            if horizon == "T-6h":
                err6 = errs
            if horizon == "T-60m" and sc.persistence and err6 is not None:
                errs = [sc.persistence * e6 + math.sqrt(1 - sc.persistence ** 2) * e for e6, e in zip(err6, errs)]
            gap_move = rng.gauss(0, sc.capture_gap_move_sd) if sc.capture_gap_move_sd else 0.0
            skew = (0, 0)
            if sc.skew_ticks:
                skew = (sc.skew_ticks, 0) if rng.random() < 0.5 else (0, sc.skew_ticks)
            quotes = []
            for k, err in enumerate(errs):
                value = self.v[horizon] + (gap_move if k == 1 else 0.0)
                fair = value if sc.quote_around_value else value + err
                widen = (rng.randint(0, sc.widen_max_ticks), rng.randint(0, sc.widen_max_ticks))
                quotes.append(_quote(min(0.98, max(0.02, fair)), sc.tick, widen[0] + skew[0], widen[1] + skew[1]))
            self.books[horizon] = (quotes[0], quotes[1])
        if self.frozen:
            self.books["T-6h"] = self.books["T-24h"]

    def mid(self, horizon: str, k: int) -> float:
        b, a = self.books[horizon][k]
        return (b + a) / 2


def true_bias(sc: GateScenario, *, n: int = TRUTH_GAMES, seed: int = TRUTH_SEED) -> tuple[float, float]:
    """Mean and standard error of the cross-book markout y under the scenario's null (the true bias)."""
    rng = random.Random(f"{seed}:{sc.name}")
    total = sq = 0.0
    count = 0
    per_week = sc.games_per_week
    for i in range(n):
        if i % per_week == 0:
            week_err = {h: rng.gauss(0, sc.week_common_sd) for h in ("T-24h", "T-6h", "T-60m")}
            cons_week = rng.gauss(0, sc.consensus_week_sd)
        g = _GameDraw(sc, rng, week_err, cons_week)
        h6, a6, h1, a1 = g.mid("T-6h", 0), g.mid("T-6h", 1), g.mid("T-60m", 0), g.mid("T-60m", 1)
        y = 0.5 * (_sign(g.c - h6) * (a1 - a6) + _sign(g.c - a6) * (h1 - h6))
        total += y
        sq += y * y
        count += 1
    mean = total / count
    return mean, math.sqrt(max(0.0, (sq - count * mean * mean) / (count - 1)) / count)


def _rows_for(sc: GateScenario, rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Label-free gate rows (T-24h and T-6h, the join's shapes) and per-game candidate inputs for one sample."""
    rows, per_game = [], []
    for w in range(sc.weeks):
        week = f"nfl-week-sim-{w:02d}"
        week_err = {h: rng.gauss(0, sc.week_common_sd) for h in ("T-24h", "T-6h", "T-60m")}
        cons_week = rng.gauss(0, sc.consensus_week_sd)
        for i in range(sc.games_per_week):
            game = f"sim-{w:02d}-{i:02d}"
            g = _GameDraw(sc, rng, week_err, cons_week)
            miss_p = sc.missing_if_stale_prob if (g.stale and sc.missing_if_stale_prob is not None) else sc.missing_prob
            missing = rng.random() < miss_p
            record = {"week": week, "game": game, "d": [], "s2": [], "gap": None}
            for horizon in ("T-24h", "T-6h"):
                (hb, ha), (ab, aa) = g.books[horizon]
                paired = not (missing and horizon == "T-6h")
                rows.append({
                    "horizon": horizon, "status": "PAIRED" if paired else "EXCLUDED", "home_team": "HOME",
                    "away_team": "AWAY", "week_cluster": week, "event_id": game,
                    "sides": {} if not paired else {
                        "HOME": {"yes_bid": f"{hb:.4f}", "yes_ask": f"{ha:.4f}", "consensus_probability": f"{g.c:.6f}",
                                 "book_received_utc": "2026-10-04T11:00:00Z", "book_timing": "AT_OR_AFTER_ODDS",
                                 "rules": {}},
                        # the away market's own YES book is the complement of its home-unit quote
                        "AWAY": {"yes_bid": f"{1 - aa:.4f}", "yes_ask": f"{1 - ab:.4f}",
                                 "consensus_probability": f"{1 - g.c:.6f}", "book_received_utc": "2026-10-04T11:00:02Z",
                                 "book_timing": "AT_OR_AFTER_ODDS", "rules": {}}}})
                if not paired:
                    continue
                h, a = (hb + ha) / 2, (ab + aa) / 2
                record["d"].append(h - a)
                record["s2"] += [(ha - hb) ** 2, (aa - ab) ** 2]
                if horizon == "T-6h":
                    record["gap"] = g.c - h
            per_game.append(record)
    return rows, per_game


def _candidate_rho(games: list[dict]) -> float | None:
    d = [x for g in games for x in g["d"]]
    s2 = [x for g in games for x in g["s2"]]
    if len(d) < 2 or not s2:
        return None
    sigma2_spread = sum(s2) / len(s2) / 12
    return max(-1.0, min(1.0, 1 - statistics.variance(d) / (2 * sigma2_spread)))


def candidate_spread_gate(per_game: list[dict], *, seed: int, resamples: int = VALIDATION_RESAMPLES,
                          deltas: tuple[float, ...] = GATE_DELTAS) -> dict[float, str]:
    """The REJECTED candidate (RESEARCH_UNBLOCKING_DECISIONS A.I option ii): sigma2 = mean(spread^2) / 12,
    rho_hat = 1 - var(d) / (2 sigma2), MODEL_MISFIT below 0, a week- and game-cluster bootstrap upper 90% bound,
    b_hat = max(sigma2, var(d) / 2) sqrt(2/pi) / sd(gap), PASS when the bound is below rho_max = (delta/4) / b_hat.
    Kept only to measure its false-pass rate; it is not in the gate."""
    d = [x for g in per_game for x in g["d"]]
    gaps = [g["gap"] for g in per_game if g["gap"] is not None]
    weeks = sorted({g["week"] for g in per_game if g["d"]})
    if len(d) < 20 or len(weeks) < 4 or len(gaps) < 10:
        return {delta: "INSUFFICIENT_DATA" for delta in deltas}
    var_d = statistics.variance(d)
    if var_d <= 1e-10:
        return {delta: "FAIL" for delta in deltas}
    rho = _candidate_rho(per_game)
    if rho is None or rho < 0:
        return {delta: "INSUFFICIENT_DATA" for delta in deltas}
    rng = random.Random(seed)
    uppers = []
    for key in ("week", "game"):
        clusters = sorted({g[key] for g in per_game if g["d"]})
        by = {c: [g for g in per_game if g[key] == c] for c in clusters}
        vals = []
        for _ in range(resamples):
            sample = [g for _ in clusters for g in by[clusters[rng.randrange(len(clusters))]]]
            r = _candidate_rho(sample)
            if r is not None:
                vals.append(r)
        vals.sort()
        uppers.append(vals[min(len(vals) - 1, max(0, math.ceil(0.9 * len(vals)) - 1))] if vals else None)
    if None in uppers:
        return {delta: "INSUFFICIENT_DATA" for delta in deltas}
    upper = max(uppers)
    if upper < 0:
        return {delta: "INSUFFICIENT_DATA" for delta in deltas}
    s2 = [x for g in per_game for x in g["s2"]]
    sigma2 = max(sum(s2) / len(s2) / 12, var_d / 2)
    b_hat = sigma2 * SQRT_2_OVER_PI / statistics.stdev(gaps)
    out = {}
    for delta in deltas:
        limit = 1.0 if b_hat <= 0 else min(1.0, TOLERABLE * delta / b_hat)
        out[delta] = "PASS" if upper < limit else "FAIL"
    return out


def _gate_module():
    try:
        from edge_lab import sports_evidence
    except ModuleNotFoundError:  # run from a checkout without an installed package
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from edge_lab import sports_evidence
    return sports_evidence


@dataclass(frozen=True)
class GateValidationRow:
    scenario: str
    tests: str
    w_holds: bool  # the scenario keeps V inside every quoted spread (assumption W true by construction)
    min_effect: float
    tolerable: float
    true_bias: float
    true_bias_se: float
    truth_games: int
    bias_state: str  # ABOVE / BELOW the tolerable level by more than 2 SE, else BORDERLINE (excluded from rates)
    reps: int
    candidate_pass_rate: float
    v3_conditional_below_rate: float
    v3_pass_rate: float
    v3_verdicts: dict


def _bias_state(truth: float, se: float, tolerable: float) -> str:
    if truth - 2 * se > tolerable:
        return "ABOVE"
    if truth + 2 * se < tolerable:
        return "BELOW"
    return "BORDERLINE"


def validate_gate_v3(*, reps: int = 200, scenarios: tuple[GateScenario, ...] = GATE_SCENARIOS,
                     seed: int = GATE_VALIDATION_SEED, truth_games: int = TRUTH_GAMES,
                     resamples: int = VALIDATION_RESAMPLES) -> list[GateValidationRow]:
    """Run every scenario: the true bias once (a large simulation), then `reps` small label-free samples through
    the rejected spread candidate and through `sports_evidence.noise_gate_v3`. Deterministic."""
    se = _gate_module()
    rows_out = []
    for sc in scenarios:
        truth, truth_se = true_bias(sc, n=truth_games)
        cand = {d: 0 for d in GATE_DELTAS}
        below = {d: 0 for d in GATE_DELTAS}
        v3_pass = {d: 0 for d in GATE_DELTAS}
        verdicts: dict[float, dict[str, int]] = {d: {} for d in GATE_DELTAS}
        for rep in range(reps):
            rng = random.Random(f"{seed}:{sc.name}:{rep}")
            rows, per_game = _rows_for(sc, rng)
            for d, v in candidate_spread_gate(per_game, seed=seed + rep, resamples=resamples).items():
                cand[d] += v == "PASS"
            gate = se.noise_gate_v3(se.gate_v3_observations(rows), resamples=resamples, seed=seed + rep)
            for row in gate["by_candidate_min_effect"]:
                d = row["min_effect"]
                below[d] += row["bound_state"] == se.V3_BOUND_BELOW
                v3_pass[d] += row["verdict"] == "PASS"
                verdicts[d][row["verdict"]] = verdicts[d].get(row["verdict"], 0) + 1
        for d in GATE_DELTAS:
            rows_out.append(GateValidationRow(
                sc.name, sc.tests, sc.quote_around_value, d, TOLERABLE * d, truth, truth_se, truth_games,
                _bias_state(truth, truth_se, TOLERABLE * d), reps, cand[d] / reps, below[d] / reps, v3_pass[d] / reps,
                dict(sorted(verdicts[d].items()))))
    return rows_out


def false_pass_summary(rows: list[GateValidationRow]) -> dict[str, dict[str, float | int | None]]:
    """Per rule: the worst false-pass rate over the rows whose true bias is ABOVE the tolerable level, how many rows
    exceed the 10% acceptance, and the lowest pass rate (power) over the rows BELOW it. The v3 conditional bound is
    also split by whether the scenario satisfies assumption W."""
    above = [r for r in rows if r.bias_state == "ABOVE"]
    below = [r for r in rows if r.bias_state == "BELOW"]
    out: dict[str, dict[str, float | int | None]] = {}
    rules = (("spread_candidate", "candidate_pass_rate", None),
             ("v3_conditional_bound", "v3_conditional_below_rate", None),
             ("v3_conditional_bound_where_W_holds", "v3_conditional_below_rate", True),
             ("v3_conditional_bound_where_W_fails", "v3_conditional_below_rate", False),
             ("v3_verdict", "v3_pass_rate", None))
    for name, attr, w in rules:
        bad = [getattr(r, attr) for r in above if w is None or r.w_holds is w]
        good = [getattr(r, attr) for r in below if w is None or r.w_holds is w]
        out[name] = {"rows_with_bias_above_tolerable": len(bad), "max_false_pass": max(bad) if bad else None,
                     "rows_over_acceptance": sum(x > ACCEPTANCE_FALSE_PASS for x in bad),
                     "rows_with_bias_below_tolerable": len(good),
                     "min_pass_rate_when_below": min(good) if good else None}
    return out


def gate_validation_markdown(rows: list[GateValidationRow]) -> str:
    summary = false_pass_summary(rows)
    n = rows[0].truth_games if rows else TRUTH_GAMES
    reps = rows[0].reps if rows else 0
    lines = [f"# EXP-002 gate v3 adversarial validation (`{GATE_VALIDATION_VERSION}`)", "",
             "SIMULATION UNDER STATED ASSUMPTIONS. True bias = mean cross-book markout under the scenario's null "
             f"({n:,} simulated games, seed {TRUTH_SEED}); {reps} label-free gate samples per scenario (seed "
             f"{GATE_VALIDATION_SEED}; {VALIDATION_RESAMPLES} bootstrap resamples). False pass: a pass while the true "
             f"bias is above {TOLERABLE} x delta_min by more than 2 SE (BORDERLINE rows are excluded). Acceptance: at "
             f"most {ACCEPTANCE_FALSE_PASS:.0%}. `v3 bound below` is what v3 would pass IF assumption W were granted; "
             "v3 itself never passes.", "",
             "| rule | rows with bias above tolerable | worst false-pass rate | rows over 10% | rows below | lowest "
             "pass rate when below |", "|---|---|---|---|---|---|"]
    for name, s in summary.items():
        worst = "-" if s["max_false_pass"] is None else f"{s['max_false_pass']:.0%}"
        power = "-" if s["min_pass_rate_when_below"] is None else f"{s['min_pass_rate_when_below']:.0%}"
        lines.append(f"| {name} | {s['rows_with_bias_above_tolerable']} | {worst} | {s['rows_over_acceptance']} | "
                     f"{s['rows_with_bias_below_tolerable']} | {power} |")
    lines += ["", "| scenario | W holds | delta_min | tolerable | true bias (SE) | bias vs tolerable | candidate PASS | "
                  "v3 bound below (if W) | v3 PASS | v3 verdicts |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.scenario} | {'yes' if r.w_holds else 'no'} | {r.min_effect * 100:.2f}c | "
                     f"{r.tolerable * 100:.3f}c | {r.true_bias * 100:+.3f}c ({r.true_bias_se * 100:.3f}) | "
                     f"{r.bias_state} | {r.candidate_pass_rate:.0%} | {r.v3_conditional_below_rate:.0%} | "
                     f"{r.v3_pass_rate:.0%} | {', '.join(f'{k} {v}' for k, v in r.v3_verdicts.items())} |")
    lines += ["", "Scenarios:", ""] + [f"- `{s.name}`: {s.tests}" for s in GATE_SCENARIOS]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    parser.add_argument("--horizon-weeks", type=float, default=SEASON_WEEKS_AVAILABLE)
    parser.add_argument("--null-check", action="store_true", help="simulate the markout statistics under the null")
    parser.add_argument("--gate-v3-validation", action="store_true",
                        help="adversarial false-pass simulation of the EXP-002 gate v3 and the rejected spread candidate")
    parser.add_argument("--reps", type=int, default=200, help="gate samples per scenario (--gate-v3-validation)")
    args = parser.parse_args(argv)
    if args.null_check:
        print(null_check_markdown(), end="")
        return 0
    if args.gate_v3_validation:
        rows = validate_gate_v3(reps=args.reps)
        if args.json:
            print(json.dumps({"version": GATE_VALIDATION_VERSION, "summary": false_pass_summary(rows),
                              "rows": [asdict(r) for r in rows]}, indent=1, sort_keys=True))
        else:
            print(gate_validation_markdown(rows), end="")
        return 0
    rows = grid(alpha=args.alpha, power=args.power, horizon_weeks=args.horizon_weeks)
    if args.json:
        print(json.dumps({"version": VERSION, "label": LABEL, "alpha": args.alpha, "power": args.power,
                          "summary": summary(rows), "rows": [asdict(r) for r in rows]}, indent=1, sort_keys=True))
    else:
        print(markdown(rows, alpha=args.alpha, power=args.power), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
