"""Seeded Monte Carlo study and replay for stake sizing v2 (ADR 0026). SIMULATION evidence only.

Everything here is synthetic unless stated. The study asks one question: how do the sizing
policies behave when the model's edge is strong, modest, absent or negative, when the model
is overconfident, when execution costs more than the sizer saw, and when positions believed
independent are really one outcome? It never shows that an edge exists.

Design:

- **One world per (scenario, path), shared by every policy variant** (common random
  numbers), so policy differences are not sampling noise between worlds. Seeds are strings
  hashed by `random.Random` (version 2 seeding), which is stable across processes and
  platforms.
- **A round** is one settlement cycle: `clusters_per_round` clusters of K mutually exclusive
  outcome states (brackets). The market's belief m ~ Dirichlet(concentration), and the truth
  q ~ Dirichlet(market_information * m), so E[q | m] = m: the market is calibrated by
  construction and any edge comes only from the model's information. The model reports
  softmax(tau * (log m + rho * (log q - log m) + sigma_P z)): rho is the share of the truth
  the model sees beyond the market (0: none, negative: anti-informative), sigma_P its noise,
  tau its overconfidence. YES and NO asks are the market probability rounded up to the cent
  plus a half-spread, with `levels` ask levels one cent apart and random whole-contract sizes.
  Costs use the Kalshi quadratic taker fee in exact integer arithmetic
  (`IntegerLadderCostCurve`, held equal to the Decimal schedule by tests). `exec_shock`
  dollars per contract are added to the realized cost and hidden from the sizer.
- **The sizer is the engine's own optimizer** (`sizing_v2.solve`). Hard caps: cash, the
  captured depth, and a per-cluster cap of `cluster_cap_fraction` of wealth. When
  `merge_unknown` is set, clusters whose dependence is unknown share one cap (ADR 0026: no
  invented correlation coefficients).
- **Ruin** is wealth below `ruin_fraction` of the starting bankroll (the operational
  shadow account's reserve floor is 10% of its bankroll). A ruined path stops trading.

Percentiles use linear interpolation between order statistics. Every variant run is
counted and reported.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import sizing_v2 as sv2
from .sizing_v2 import CoreCandidate, CoreProblem, IntegerLadderCostCurve, SizingPolicyV2

SIM_VERSION = "1"
LABEL = ("SIMULATION evidence: synthetic markets and outcomes. Not a backtest, not an edge claim, "
         "not authority to change any shadow fill.")
REPLAY_LABEL = ("IN-SAMPLE replay: historical prices are not fills, and this is not evidence of an edge.")
DEFAULT_OUT = Path("experiments/sizing_v2/results")


# =========================================================================== configuration


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    market_information: float = 30.0  # truth ~ Dirichlet(market_information * market belief)
    model_weight: float = 0.5  # rho: the share of (log truth - log market) the model sees
    model_noise: float = 0.15  # sigma_P
    overconfidence: float = 1.0  # tau > 1 sharpens the model's probabilities
    exec_shock: float = 0.0  # $ per contract added to realized cost, unseen by the sizer
    clusters_per_round: int = 1
    duplicate_clusters: bool = False  # extra clusters settle on the SAME outcome
    merge_unknown: bool = False  # the sizer shares one cap across clusters of unknown dependence
    states: int = 4
    concentration: float = 2.0
    half_spread_cents: int = 1
    levels: int = 5
    level_size: tuple[int, int] = (20, 200)
    # Scenarios that differ only in what the sizer knows or how fills are realized (overconfidence
    # transforms the same draws; exec_shock and merge_unknown touch no draw) share a world id,
    # so their comparison uses common random numbers. None: the scenario id.
    world: str | None = None


@dataclass(frozen=True)
class Variant:
    variant_id: str
    policy: SizingPolicyV2
    uncertainty_method: str = "dirichlet"  # "dirichlet" | "wilson"
    n_eff: float = 100.0


@dataclass(frozen=True)
class StudyConfig:
    seed: int = 20260924
    paths: int = 100
    rounds: int = 250
    bankroll: float = 1000.0
    ruin_fraction: float = 0.10
    cluster_cap_fraction: float = 0.25
    gamma: float = 0.10


BASE = Scenario("modest_edge", "model sees half of the truth's deviation from the market (rho 0.5), noise 0.15")
SCENARIOS: tuple[Scenario, ...] = (
    replace(BASE, scenario_id="strong_edge", description="model sees 80% of the truth's deviation (rho 0.8)",
            model_weight=0.8),
    BASE,
    replace(BASE, scenario_id="no_information",
            description="model = calibrated market + noise (rho 0): zero edge before costs, negative after",
            model_weight=0.0),
    replace(BASE, scenario_id="negative_edge",
            description="anti-informative model (rho -0.5): it leans against the truth", model_weight=-0.5),
    replace(BASE, scenario_id="overconfident", description="modest edge, model log-odds sharpened x1.5 (tau 1.5)",
            overconfidence=1.5, world="modest_edge"),
    replace(BASE, scenario_id="exec_shock", description="modest edge, +$0.02 per contract unseen execution cost",
            exec_shock=0.02, world="modest_edge"),
    replace(BASE, scenario_id="independent_clusters", description="modest edge, two independent clusters per round",
            clusters_per_round=2),
    replace(BASE, scenario_id="duplicate_misspecified",
            description="two clusters per round that are secretly ONE outcome; the sizer believes them independent",
            clusters_per_round=2, duplicate_clusters=True),
    replace(BASE, scenario_id="duplicate_shared_cap",
            description="same duplicate truth; unknown dependence -> the two clusters share one cluster cap",
            clusters_per_round=2, duplicate_clusters=True, merge_unknown=True, world="duplicate_misspecified"),
)

_P = sv2
F_HALF = SizingPolicyV2("SV2-F-robust-half-kelly", "1", "KELLY", "F variant: robust 1/2 Kelly",
                        kelly_fraction=Decimal("0.5"), robust=True)
G_ROBUST = SizingPolicyV2("SV2-G-robust-rck-half", "1", "KELLY",
                          "G variant: robust 1/2 Kelly with the robust drawdown constraint (alpha 0.7, beta 0.1)",
                          kelly_fraction=Decimal("0.5"), robust=True, drawdown_alpha=Decimal("0.7"),
                          drawdown_beta=Decimal("0.1"), robust_constraint=True)
H_RCK = SizingPolicyV2("SV2-H-cluster-robust-rck", "1", "KELLY",
                       "H variant: joint robust 1/2 Kelly + robust drawdown constraint (alpha 0.7, beta 0.1)",
                       kelly_fraction=Decimal("0.5"), robust=True, joint=True, drawdown_alpha=Decimal("0.7"),
                       drawdown_beta=Decimal("0.1"), robust_constraint=True)

H_NOMINAL = SizingPolicyV2("SV2-H-cluster-nominal-half", "1", "KELLY",
                           "H variant: joint NOMINAL 1/2 Kelly (isolates joint vs sequential sizing; compare D)",
                           kelly_fraction=Decimal("0.5"), joint=True)

MAIN_VARIANTS: tuple[Variant, ...] = tuple(Variant(p.policy_id, p) for p in (
    _P.POLICY_A, _P.POLICY_B, _P.POLICY_C, _P.POLICY_D, _P.POLICY_E, _P.POLICY_F, F_HALF, _P.POLICY_G, G_ROBUST,
    _P.POLICY_H, H_NOMINAL, H_RCK))

# Uncertainty-method comparison, declared before any run. Selection rule (fixed in advance):
# the method/n_eff maximizing the minimum, over UNCERTAINTY_SCENARIOS, of the 10th-percentile
# terminal wealth of robust 1/2 Kelly; ties broken by the higher mean log growth over them.
UNCERTAINTY_VARIANTS: tuple[Variant, ...] = tuple(
    Variant(f"{F_HALF.policy_id}[{method},n={n:g}]", F_HALF, method, n)
    for method in ("wilson", "dirichlet") for n in (30.0, 100.0, 300.0))
UNCERTAINTY_SCENARIOS = ("modest_edge", "overconfident", "exec_shock", "no_information")

SWEEP_POLICIES = (_P.POLICY_C, _P.POLICY_D, _P.POLICY_E, _P.POLICY_G, F_HALF, _P.POLICY_H, H_RCK)
SWEEPS: tuple[tuple[str, str, tuple[float, ...]], ...] = (
    ("overconfidence", "calibration error: model log-odds multiplied by tau", (1.0, 1.25, 1.5, 2.0)),
    ("exec_shock", "unseen execution cost, $ per contract", (0.0, 0.01, 0.02, 0.04)),
)


# =========================================================================== world


def _softmax(x: Sequence[float]) -> list[float]:
    m = max(x)
    e = [math.exp(v - m) for v in x]
    s = sum(e)
    return [v / s for v in e]


def _clean(p: Sequence[float], floor: float = 1e-4) -> list[float]:
    q = [max(floor, v) for v in p]
    s = sum(q)
    return [v / s for v in q]


@dataclass
class _Cluster:
    truth: list[float]
    model: list[float]
    outcome: int
    yes: list[tuple[tuple[int, int], ...]]  # per state: ladder levels (price in 1e-4 $, size)
    no: list[tuple[tuple[int, int], ...]]
    market: list[float]
    sets: dict[tuple[str, float], Any] = field(default_factory=dict)
    curves: list | None = None


def _ladder(rng: random.Random, cents: int, sc: Scenario) -> tuple[tuple[int, int], ...]:
    lo, hi = sc.level_size
    return tuple((c * 100, rng.randint(lo, hi)) for c in range(cents, min(99, cents + sc.levels - 1) + 1))


def _dirichlet(rng: random.Random, alpha: Sequence[float]) -> list[float]:
    g = [rng.gammavariate(a, 1.0) for a in alpha]
    total = sum(g)
    return _clean([x / total for x in g])


def _cluster(rng: random.Random, sc: Scenario, truth: list[float] | None = None, outcome: int | None = None,
             market: list[float] | None = None) -> _Cluster:
    k = sc.states
    if truth is None:
        market = _dirichlet(rng, [sc.concentration] * k)
        truth = _dirichlet(rng, [sc.market_information * x for x in market])
    elif market is None:
        raise ValueError("a cluster with a given truth needs its market belief")
    logm = [math.log(x) for x in market]
    signal = [lm + sc.model_weight * (math.log(q) - lm) + sc.model_noise * rng.gauss(0, 1)
              for lm, q in zip(logm, truth)]
    model = _clean(_softmax([sc.overconfidence * v for v in signal]), 1e-3)
    if outcome is None:
        u, acc, outcome = rng.random(), 0.0, k - 1
        for i, x in enumerate(truth):
            acc += x
            if u < acc:
                outcome = i
                break
    yes, no = [], []
    for m in market:
        y = min(99, max(1, math.ceil(100 * m - 1e-9) + sc.half_spread_cents))
        n = min(99, max(1, math.ceil(100 * (1 - m) - 1e-9) + sc.half_spread_cents))
        yes.append(_ladder(rng, y, sc))
        no.append(_ladder(rng, n, sc))
    return _Cluster(truth, model, outcome, yes, no, market)


def _world(cfg: StudyConfig, sc: Scenario, path: int) -> list[list[_Cluster]]:
    rng = random.Random(f"sizing-v2-sim:{cfg.seed}:{sc.world or sc.scenario_id}:{path}")
    rounds = []
    for _ in range(cfg.rounds):
        first = _cluster(rng, sc)
        clusters = [first]
        for _ in range(sc.clusters_per_round - 1):
            if sc.duplicate_clusters:
                # the same outcome listed again (another venue or series): a near-identical price
                # with its own small noise, the same truth and the same settlement
                twin = _dirichlet(rng, [300.0 * x for x in first.market])
                clusters.append(_cluster(rng, sc, truth=first.truth, outcome=first.outcome, market=twin))
            else:
                clusters.append(_cluster(rng, sc))
        rounds.append(clusters)
    return rounds


def _uncertainty(cluster: _Cluster, states: tuple[str, ...], method: str, n_eff: float, gamma: float) -> Any:
    key = (method, n_eff)
    if key not in cluster.sets:
        if method == "wilson":
            cluster.sets[key] = sv2.wilson_box(states, cluster.model, int(n_eff))
        elif method == "dirichlet":
            cluster.sets[key] = sv2.dirichlet_box(states, cluster.model, n_eff, gamma=gamma)
        else:
            raise ValueError(f"unknown uncertainty method {method!r}")
    return cluster.sets[key]


# =========================================================================== one path


@dataclass
class _PathResult:
    terminal: float
    max_drawdown: float
    min_wealth: float
    ruined: bool
    log_returns: list[float]
    committed_fraction: float  # mean over trading rounds of cost / wealth
    trades: int
    cost_traded: float
    pnl: float


def _candidates(cluster: _Cluster) -> list[tuple[tuple[int, ...], IntegerLadderCostCurve]]:
    """Every (payout, cost curve) of the cluster, built once and shared by all variants."""
    if cluster.curves is None:
        k = len(cluster.model)
        out = []
        for i in range(k):
            for side, levels in (("YES", cluster.yes[i]), ("NO", cluster.no[i])):
                payout = tuple((1 if j == i else 0) if side == "YES" else (0 if j == i else 1) for j in range(k))
                out.append((payout, IntegerLadderCostCurve(levels)))
        cluster.curves = out
    return cluster.curves


def run_path(cfg: StudyConfig, sc: Scenario, world: list[list[_Cluster]], variant: Variant) -> _PathResult:
    policy = variant.policy
    states = tuple(f"s{i}" for i in range(sc.states))
    w0 = cfg.bankroll
    wealth, peak, max_dd, min_w = w0, w0, 0.0, w0
    ruined = False
    log_returns, committed, trades, cost_traded, pnl = [], [], 0, 0.0, 0.0
    for clusters in world:
        if wealth < cfg.ruin_fraction * w0:
            ruined = True
            break
        start = wealth
        cash_left = wealth
        group_left: dict[int, float] = {}
        realized = 0.0
        spent_round = 0.0
        for ci, cluster in enumerate(clusters):
            group = 0 if sc.merge_unknown else ci
            if group not in group_left:
                group_left[group] = cfg.cluster_cap_fraction * start
            uset = _uncertainty(cluster, states, variant.uncertainty_method, variant.n_eff, cfg.gamma)
            cands = []
            for payout, curve in _candidates(cluster):
                edge = sum(p for p, a in zip(cluster.model, payout) if a) - curve.cost(1) if curve.max_contracts else -1
                threshold = float(policy.min_edge) if policy.rule != "KELLY" else 0.0
                if edge > 0 and edge >= threshold:
                    cands.append((edge, payout, curve))
            if not cands:
                continue
            cands.sort(key=lambda c: (-c[0], c[1]))
            base = [start] * sc.states
            chosen: list[tuple[tuple[int, ...], IntegerLadderCostCurve, int]] = []
            if policy.joint:
                cap_budget = min(group_left[group], cash_left)
                core = tuple(CoreCandidate(str(j), p, c, c.max_contracts) for j, (_, p, c) in enumerate(cands))
                sol = sv2.solve(policy, CoreProblem(start, tuple(base), tuple(cluster.model), uset, core, cap_budget),
                                reference=False)
                chosen = [(p, c, n) for (_, p, c), n in zip(cands, sol.counts) if n]
            else:
                for _, payout, curve in cands:
                    bound = sv2._affordable(curve, cash_left, curve.max_contracts)
                    core = (CoreCandidate("c", payout, curve, bound),)
                    sol = sv2.solve(policy, CoreProblem(start, tuple(base), tuple(cluster.model), uset, core, None),
                                    reference=False)
                    n = min(sol.counts[0], sv2._affordable(curve, min(group_left[group], cash_left), bound))
                    if n:
                        cost = curve.cost(n)
                        cash_left -= cost
                        group_left[group] -= cost
                        for k, a in enumerate(payout):
                            base[k] += (n if a else 0) - cost
                        chosen.append((payout, curve, n))
            if policy.joint:
                for payout, curve, n in chosen:
                    cost = curve.cost(n)
                    cash_left -= cost
                    group_left[group] -= cost
            for payout, curve, n in chosen:
                cost = curve.cost(n) + sc.exec_shock * n
                win = n if payout[cluster.outcome] else 0
                realized += win - cost
                spent_round += cost
                cost_traded += cost
                trades += 1
        wealth = max(0.0, start + realized)
        pnl += realized
        committed.append(spent_round / start)
        log_returns.append(math.log(wealth / start) if wealth > 0 else -math.inf)
        peak = max(peak, wealth)
        max_dd = max(max_dd, (peak - wealth) / peak)
        min_w = min(min_w, wealth)
    if wealth < cfg.ruin_fraction * w0:
        ruined = True
    return _PathResult(wealth, max_dd, min_w, ruined, log_returns,
                       sum(committed) / len(committed) if committed else 0.0, trades, cost_traded, pnl)


# =========================================================================== metrics


def _quantile(values: Sequence[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return math.nan
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def summarize(cfg: StudyConfig, results: Sequence[_PathResult]) -> dict[str, float]:
    w0 = cfg.bankroll
    n = len(results)
    terminal = [r.terminal / w0 for r in results]
    growth = [(math.log(r.terminal / w0) / cfg.rounds) if r.terminal > 0 else -math.inf for r in results]
    finite = [g for g in growth if math.isfinite(g)]
    tail = sorted(terminal)[:max(1, math.ceil(0.05 * n))]
    lr = [x for r in results for x in r.log_returns if math.isfinite(x)]
    mean_lr = sum(lr) / len(lr) if lr else 0.0
    dd = [r.max_drawdown for r in results]
    cost = sum(r.cost_traded for r in results)
    return {
        "paths": n,
        "mean_log_growth_per_round": (sum(finite) / len(finite)) if len(finite) == n else -math.inf,
        "median_log_growth_per_round": _quantile(growth, 0.5) if finite else -math.inf,
        "median_terminal_wealth": _quantile(terminal, 0.5),
        "p05_terminal_wealth": _quantile(terminal, 0.05),
        "p10_terminal_wealth": _quantile(terminal, 0.10),
        "cvar05_terminal_wealth": sum(tail) / len(tail),
        "mean_terminal_wealth": sum(terminal) / n,
        "median_max_drawdown": _quantile(dd, 0.5),
        "p90_max_drawdown": _quantile(dd, 0.9),
        "p_drawdown_over_20pct": sum(1 for d in dd if d > 0.20) / n,
        "p_drawdown_over_50pct": sum(1 for d in dd if d > 0.50) / n,
        "p_ruin": sum(1 for r in results if r.ruined) / n,
        "volatility_log_return_per_round": math.sqrt(sum((x - mean_lr) ** 2 for x in lr) / (len(lr) - 1))
        if len(lr) > 1 else 0.0,
        "mean_committed_fraction_per_round": sum(r.committed_fraction for r in results) / n,
        "trades_per_round": sum(r.trades for r in results) / (n * cfg.rounds),
        "turnover_cost_per_round_over_w0": cost / (n * cfg.rounds * w0),
        "realized_net_return_per_dollar_traded": (sum(r.pnl for r in results) / cost) if cost else 0.0,
    }


# =========================================================================== study


def _run_scenario(args: tuple[StudyConfig, Scenario, tuple[Variant, ...]]) -> dict[str, dict[str, float]]:
    cfg, sc, variants = args
    per_variant: dict[str, list[_PathResult]] = {v.variant_id: [] for v in variants}
    for path in range(cfg.paths):
        world = _world(cfg, sc, path)
        for v in variants:
            per_variant[v.variant_id].append(run_path(cfg, sc, world, v))
    return {vid: summarize(cfg, rs) for vid, rs in per_variant.items()}


def _jobs(cfg: StudyConfig) -> list[tuple[str, tuple[StudyConfig, Scenario, tuple[Variant, ...]]]]:
    jobs = [(f"main/{sc.scenario_id}", (cfg, sc, MAIN_VARIANTS)) for sc in SCENARIOS]
    by_id = {sc.scenario_id: sc for sc in SCENARIOS}
    jobs += [(f"uncertainty/{sid}", (cfg, by_id[sid], UNCERTAINTY_VARIANTS)) for sid in UNCERTAINTY_SCENARIOS]
    sweep_variants = tuple(Variant(p.policy_id, p) for p in SWEEP_POLICIES)
    for name, _, values in SWEEPS:
        for value in values:
            sc = replace(BASE, scenario_id=f"{BASE.scenario_id}[{name}={value:g}]", world=BASE.scenario_id,
                         **{name: value})
            jobs.append((f"sweep/{name}/{value:g}", (cfg, sc, sweep_variants)))
    return jobs


def select_uncertainty_method(uncertainty: dict[str, dict[str, dict[str, float]]]) -> dict[str, Any]:
    """Apply the pre-declared selection rule to the uncertainty-comparison results."""
    table = []
    for v in UNCERTAINTY_VARIANTS:
        rows = [uncertainty[sid][v.variant_id] for sid in UNCERTAINTY_SCENARIOS]
        table.append({"variant": v.variant_id, "method": v.uncertainty_method, "n_eff": v.n_eff,
                      "min_p10_terminal_wealth": min(r["p10_terminal_wealth"] for r in rows),
                      "mean_log_growth": sum(r["mean_log_growth_per_round"] for r in rows) / len(rows)})
    best = max(table, key=lambda r: (round(r["min_p10_terminal_wealth"], 12), r["mean_log_growth"]))
    return {"rule": "maximize min over scenarios of p10 terminal wealth (robust 1/2 Kelly); tie -> higher mean "
                    "log growth", "scenarios": list(UNCERTAINTY_SCENARIOS), "table": table, "selected": best}


def run_study(cfg: StudyConfig, *, workers: int = 1, only: Iterable[str] | None = None) -> dict[str, Any]:
    jobs = _jobs(cfg)
    if only is not None:
        wanted = set(only)
        jobs = [j for j in jobs if j[0].split("/")[0] in wanted]
    started = time.time()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            outputs = list(pool.map(_run_scenario, [a for _, a in jobs]))
    else:
        outputs = [_run_scenario(a) for _, a in jobs]
    results: dict[str, Any] = {"main": {}, "uncertainty": {}, "sweep": {}}
    runs = 0
    for (name, (_, sc, variants)), out in zip(jobs, outputs):
        kind, rest = name.split("/", 1)
        results[kind][rest] = out
        runs += len(variants)
    report: dict[str, Any] = {
        "label": LABEL, "sim_version": SIM_VERSION, "engine": f"{sv2.ENGINE_ID} v{sv2.ENGINE_VERSION}",
        "config": asdict(cfg),
        "scenarios": [asdict(s) for s in SCENARIOS],
        "variants": {"main": [_variant_dict(v) for v in MAIN_VARIANTS],
                     "uncertainty": [_variant_dict(v) for v in UNCERTAINTY_VARIANTS],
                     "sweep_policies": [p.policy_id for p in SWEEP_POLICIES],
                     "sweeps": [{"parameter": n, "meaning": m, "values": list(vals)} for n, m, vals in SWEEPS]},
        "variant_runs_evaluated": runs,
        "distinct_policy_variants": len({v.variant_id for v in MAIN_VARIANTS + UNCERTAINTY_VARIANTS}),
        "results": results,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    if results["uncertainty"] and all(s in results["uncertainty"] for s in UNCERTAINTY_SCENARIOS):
        report["uncertainty_selection"] = select_uncertainty_method(results["uncertainty"])
    return report


def _variant_dict(v: Variant) -> dict[str, Any]:
    return {"variant_id": v.variant_id, "policy": v.policy.to_dict(), "uncertainty_method": v.uncertainty_method,
            "n_eff": v.n_eff}


# =========================================================================== report


_COLUMNS = (("mean_log_growth_per_round", "growth/round", "{:+.5f}"), ("median_terminal_wealth", "median W_T", "{:.3f}"),
            ("p05_terminal_wealth", "p5 W_T", "{:.3f}"), ("p10_terminal_wealth", "p10 W_T", "{:.3f}"),
            ("cvar05_terminal_wealth", "CVaR5 W_T", "{:.3f}"), ("median_max_drawdown", "med maxDD", "{:.3f}"),
            ("p_drawdown_over_20pct", "P(DD>20%)", "{:.2f}"), ("p_drawdown_over_50pct", "P(DD>50%)", "{:.2f}"),
            ("p_ruin", "P(ruin)", "{:.2f}"), ("volatility_log_return_per_round", "vol/round", "{:.4f}"),
            ("mean_committed_fraction_per_round", "committed", "{:.3f}"))


def _fmt(value: float, spec: str) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        return "-inf" if value < 0 else "nan"
    return spec.format(value)


def _table(rows: dict[str, dict[str, float]]) -> list[str]:
    head = "| variant | " + " | ".join(c[1] for c in _COLUMNS) + " |"
    lines = [head, "|" + "---|" * (len(_COLUMNS) + 1)]
    for vid, m in rows.items():
        lines.append(f"| {vid} | " + " | ".join(_fmt(m[c[0]], c[2]) for c in _COLUMNS) + " |")
    return lines


def render_report(report: dict[str, Any]) -> str:
    cfg = report["config"]
    out = ["# Stake sizing v2: simulation results (generated)", "",
           f"**{report['label']}**", "",
           f"Generated by `edge-lab sizing simulate` ({report['engine']}, simulation v{report['sim_version']}). "
           f"Seed {cfg['seed']}, {cfg['paths']} paths x {cfg['rounds']} rounds per scenario, starting bankroll "
           f"{cfg['bankroll']:g}, ruin below {cfg['ruin_fraction']:g} x start, per-cluster cap "
           f"{cfg['cluster_cap_fraction']:g} x wealth.", "",
           f"Variant runs evaluated: **{report['variant_runs_evaluated']}** "
           f"({report['distinct_policy_variants']} distinct policy variants). Wealth figures are multiples of the "
           "starting bankroll. `growth/round` is the mean over paths of log(W_T/W_0)/T (-inf when any path lost "
           "everything).", ""]
    for sc in report["scenarios"]:
        sid = sc["scenario_id"]
        if sid not in report["results"]["main"]:
            continue
        out += [f"## Scenario `{sid}`", "", sc["description"], ""]
        out += _table(report["results"]["main"][sid]) + [""]
    if report["results"]["uncertainty"]:
        out += ["## Uncertainty-method comparison (robust 1/2 Kelly)", ""]
        for sid, rows in report["results"]["uncertainty"].items():
            out += [f"### `{sid}`", ""] + _table(rows) + [""]
        sel = report.get("uncertainty_selection")
        if sel:
            out += [f"Selection rule (declared before the run): {sel['rule']}.", "",
                    "| variant | min p10 W_T | mean growth |", "|---|---|---|"]
            out += [f"| {r['variant']} | {r['min_p10_terminal_wealth']:.4f} | {r['mean_log_growth']:+.5f} |"
                    for r in sel["table"]]
            out += ["", f"**Selected: {sel['selected']['variant']}.**", ""]
    if report["results"]["sweep"]:
        out += ["## Sensitivity sweeps (base scenario `modest_edge`)", ""]
        for key, rows in report["results"]["sweep"].items():
            out += [f"### {key}", ""] + _table(rows) + [""]
    out.append(f"Elapsed {report['elapsed_seconds']} s.")
    return "\n".join(out) + "\n"


# =========================================================================== replay


PRICE_COLUMNS = ("yes_ask", "no_ask", "ask", "best_ask", "price", "orderbook", "asks")


def inspect_exp001(root: Path = Path(".")) -> dict[str, Any]:
    """Can EXP-001's committed history support a sizing replay? Reads headers only.

    Gate 3's dataset has forecasts and labels but no market prices (`market_price_available`
    is false on every row), and Gate 4 holds aggregate scores, not per-day probabilities with
    prices. The test split (2025-01-01..2026-09-21) was opened once for Stage A and is
    protected by the preregistration, so no replay touches it."""
    exp = root / "experiments" / "EXP-001-kxhighny-nws-vs-market"
    dataset = exp / "gate3" / "dataset.csv"
    if not dataset.exists():
        return {"status": "SKIPPED", "reason": f"{dataset} not found"}
    with dataset.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        available = sum(1 for row in reader if row.get("market_price_available") == "true")
    price_cols = [c for c in header if c in PRICE_COLUMNS]
    if price_cols and available:
        return {"status": "AVAILABLE", "price_columns": price_cols, "rows_with_prices": available}
    return {
        "status": "SKIPPED",
        "reason": ("EXP-001 gate3/dataset.csv has no market price columns and market_price_available is true on "
                   f"{available} rows; gate4 holds aggregate Stage A scores only. There are no per-day executable "
                   "prices to size against, and the test split was opened once for Stage A and stays protected. "
                   "Replay waits for prospective Stage B decision records."),
        "columns_checked": len(header),
        "test_split_marker": str((exp / "gate4" / "test_split_opened.json").as_posix()),
    }


def replay_records(records: Sequence[dict[str, Any]], policies: Sequence[SizingPolicyV2], *,
                   bankroll: float = 1000.0, n_eff: float = 100.0, gamma: float = 0.10,
                   cluster_cap_fraction: float = 0.25) -> dict[str, Any]:
    """Counterfactual replay of point-in-time decision records (IN-SAMPLE, not fills).

    Each record: {"as_of_utc", "states": [...], "model_probabilities": [...], "outcome_state",
    "candidates": [{"side", "yes_states": [...], "asks": [[price, size], ...]}]}. Prices are
    dollars on the cent grid. Records are replayed in `as_of_utc` order."""
    ordered = sorted(records, key=lambda r: r["as_of_utc"])
    out = {"label": REPLAY_LABEL, "records": len(ordered), "policies": {}}
    for policy in policies:
        wealth, trades, path = bankroll, 0, []
        for rec in ordered:
            states = tuple(rec["states"])
            p = [float(x) for x in rec["model_probabilities"]]
            uset = sv2.dirichlet_box(states, p, n_eff, gamma=gamma)
            outcome = states.index(rec["outcome_state"])
            base = [wealth] * len(states)
            cands = []
            for c in rec["candidates"]:
                levels = [(int(round(Decimal(str(px)) * 10000)), int(sz)) for px, sz in c["asks"]]
                curve = IntegerLadderCostCurve(levels)
                payout = sv2._payout(states, c["yes_states"], c["side"])
                cands.append(CoreCandidate(c.get("market_id", "m"), payout, curve,
                                           sv2._affordable(curve, wealth, curve.max_contracts)))
            realized, left = 0.0, cluster_cap_fraction * wealth
            if policy.joint and cands:
                sol = sv2.solve(policy, CoreProblem(wealth, tuple(base), tuple(p), uset, tuple(cands), left))
                picks = list(zip(cands, sol.counts))
            else:
                picks = []
                for cand in cands:
                    sol = sv2.solve(policy, CoreProblem(wealth, tuple(base), tuple(p), uset, (cand,), None))
                    n = min(sol.counts[0], sv2._affordable(cand.curve, left, cand.cap))
                    if n:
                        cost = cand.curve.cost(n)
                        left -= cost
                        for k, a in enumerate(cand.payout):
                            base[k] += (n if a else 0) - cost
                    picks.append((cand, n))
            for cand, n in picks:
                if n:
                    trades += 1
                    realized += (n if cand.payout[outcome] else 0) - cand.curve.cost(n)
            wealth += realized
            path.append(round(wealth, 2))
        out["policies"][policy.policy_id] = {"terminal_wealth": round(wealth, 2), "trades": trades, "path": path}
    return out


# =========================================================================== CLI


def _write(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = report["config"]["seed"]
    js = out_dir / f"simulation_seed{seed}.json"
    md = out_dir / f"SIMULATION_REPORT_seed{seed}.md"
    js.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")
    md.write_text(render_report(report), encoding="utf-8", newline="\n")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edge-lab sizing", description="Stake sizing v2 research tools "
                                     "(RESEARCH SIZING; shadow/research only).")
    sub = parser.add_subparsers(dest="sizing_command", required=True)
    sim = sub.add_parser("simulate", help="Seeded Monte Carlo study of policies A-H (SIMULATION evidence).")
    sim.add_argument("--seed", type=int, default=StudyConfig.seed)
    sim.add_argument("--paths", type=int, default=StudyConfig.paths)
    sim.add_argument("--rounds", type=int, default=StudyConfig.rounds)
    sim.add_argument("--workers", type=int, default=1)
    sim.add_argument("--only", nargs="*", choices=("main", "uncertainty", "sweep"))
    sim.add_argument("--out", default=str(DEFAULT_OUT))
    sim.add_argument("--no-write", action="store_true", help="print the summary only")
    rep = sub.add_parser("replay", help="Counterfactual replay (IN-SAMPLE; historical prices are not fills).")
    rep.add_argument("--exp001", action="store_true", help="inspect EXP-001 history for replayable prices")
    rep.add_argument("--input", help="JSON file with a list of point-in-time decision records")
    sub.add_parser("policies", help="List the canonical sizing policies A-H.")
    args = parser.parse_args(argv)

    if args.sizing_command == "policies":
        for p in sv2.POLICIES:
            print(json.dumps(p.to_dict(), sort_keys=True))
        return 0
    if args.sizing_command == "replay":
        if args.input:
            records = json.loads(Path(args.input).read_text(encoding="utf-8"))
            print(json.dumps(replay_records(records, sv2.POLICIES), indent=1, sort_keys=True))
            return 0
        print(json.dumps(inspect_exp001(Path(".")), indent=1, sort_keys=True))
        return 0
    cfg = StudyConfig(seed=args.seed, paths=args.paths, rounds=args.rounds)
    report = run_study(cfg, workers=max(1, args.workers), only=args.only)
    if args.no_write:
        print(json.dumps({"label": LABEL, "variant_runs_evaluated": report["variant_runs_evaluated"],
                          "uncertainty_selection": report.get("uncertainty_selection", {}).get("selected")},
                         indent=1, sort_keys=True, default=str))
        return 0
    js, md = _write(report, Path(args.out))
    print(f"{LABEL}\nwrote {js}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
