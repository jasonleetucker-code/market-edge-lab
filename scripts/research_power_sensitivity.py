"""EXP-002 sample-size SENSITIVITY ranges under stated assumptions. It is not a power analysis.

    python scripts/research_power_sensitivity.py            # Markdown tables (the default grid)
    python scripts/research_power_sensitivity.py --json     # the same rows as JSON

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
range. Stdlib only, deterministic.
"""

from __future__ import annotations

import argparse
import json
import math
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
MARKOUT_SD = (0.01, 0.02, 0.04)
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
    args = parser.parse_args(argv)
    rows = grid(alpha=args.alpha, power=args.power, horizon_weeks=args.horizon_weeks)
    if args.json:
        print(json.dumps({"version": VERSION, "label": LABEL, "alpha": args.alpha, "power": args.power,
                          "summary": summary(rows), "rows": [asdict(r) for r in rows]}, indent=1, sort_keys=True))
    else:
        print(markdown(rows, alpha=args.alpha, power=args.power), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
