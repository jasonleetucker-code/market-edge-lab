"""EXP-002 sample-size SENSITIVITY ranges under stated assumptions. It is not a power analysis.

    python scripts/research_power_sensitivity.py            # Markdown tables (the default grid)
    python scripts/research_power_sensitivity.py --json     # the same rows as JSON
    python scripts/research_power_sensitivity.py --null-check   # the markout statistics under a no-information null

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    parser.add_argument("--horizon-weeks", type=float, default=SEASON_WEEKS_AVAILABLE)
    parser.add_argument("--null-check", action="store_true", help="simulate the markout statistics under the null")
    args = parser.parse_args(argv)
    if args.null_check:
        print(null_check_markdown(), end="")
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
