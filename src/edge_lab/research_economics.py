"""Economic screen, opportunity episodes, capital-constrained replay and the size ladder (#96, EE v1).

The canonical owner of "is this research family worth money, at what size, with how much
capital?". It is a derived research layer: it never writes the shadow ledger, never sizes a
real position and never touches EXP-001. Every money amount it sees is a scenario input; **no
amount is an approved bankroll** (`ILLUSTRATIVE`).

Shared contract (Family A in `sports_evidence.py` and Family B in `payoff_constraints.py`
build these; they never re-implement the arithmetic):

- `SizePoint` / `size_ladder_from_depth`: one rung of a size ladder for one observation,
  priced by the existing depth walk and fee schedule (`opportunity.walk_ladder`,
  `opportunity.price_depth_fill`). Fees enter **once**, inside `net_edge_per_unit`.
- `Observation`: one point-in-time look at one liquidity pool (a market side, or the legs
  of a basket), with its size ladder, cluster and capital-release time.
- `EpisodeDefinition` / `build_episodes`: distinct opportunity episodes under a definition
  frozen in the protocol **before outcomes are viewed** (start threshold, end/merge gap,
  minimum size). Repeated observations of the same resting orders are one episode, never
  many. An incomplete or unfrozen definition yields no episodes (INSUFFICIENT_EVIDENCE).
- `CapitalScenario` / `replay`: chronological, capital-constrained replay with finite
  capital per venue, a reserve, release on settlement, and one shared pool for every
  strategy passed in together (capital is never double counted across simultaneous
  strategies). A liquidity pool held by an open position is not taken again until release.
- `capacity_ladder`: the replay at every rung, conservative (fill at detection) and less
  conservative (best single observation), with marginal contribution and marginal capital,
  flagging where more capital only adds idle balance.
- `economic_screen`: variable economics, fixed cash costs, owner-hour cost (all shown
  separately), return on deployed versus total capital, capital-days, frequency, a
  cluster-bootstrap uncertainty band, assumptions and data gaps, and a verdict.

Rules:
- Every input is `Labeled` OBSERVED / ESTIMATED / OWNER_INPUT / UNKNOWN; UNKNOWN has no value.
- `net_edge_per_unit` is after variable costs (fees, spread, slippage). Nothing subtracts a
  fee or a loss again later. There is no bankroll x size x turnover product anywhere.
- Observed depth is a ceiling, not a guaranteed fill; fill probability is not assumed.
- The annual figure is a SIMPLIFIED SCENARIO (window contribution x 365 / window days) under a
  stated stationarity assumption, produced only when the protocol's minimum episode count
  is supplied and met. It is never an income forecast.
- Verdicts (INSUFFICIENT_EVIDENCE, ECONOMICALLY_UNVIABLE, BELOW_MINIMUM_USEFUL, CONTINUE) are
  research states, not code failures, and none of them is an edge claim.

Pure, deterministic, stdlib-only and network-free.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .freshness import parse_utc
from .opportunity import DepthLadder, DepthStatus, FeeSchedule, PriceGrid, price_depth_fill, walk_ladder
from .provenance import canonical_json, sha256_hex

ECONOMICS_VERSION = "research-economics-v1"
ILLUSTRATIVE = "ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL"
DAYS_PER_YEAR = Decimal(365)
# Analysis parameters of the uncertainty band (not research thresholds): a fixed seed and
# resample count make the band one deterministic computation.
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_RESAMPLES = 2000
_Q = Decimal("1e-12")


class Basis(str, Enum):
    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"
    OWNER_INPUT = "OWNER_INPUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Labeled:
    """A number with its evidential basis. UNKNOWN never carries a value; a value is never UNKNOWN."""

    value: Decimal | None
    basis: Basis
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.basis, Basis):
            raise ValueError("basis must be a Basis")
        if (self.value is None) != (self.basis is Basis.UNKNOWN):
            raise ValueError("UNKNOWN has no value, and a value needs a basis other than UNKNOWN")
        if self.value is not None and (not isinstance(self.value, Decimal) or not self.value.is_finite()):
            raise ValueError(f"value must be a finite Decimal, not {self.value!r}")

    @classmethod
    def unknown(cls, note: str = "") -> "Labeled":
        return cls(None, Basis.UNKNOWN, note)


class EdgeKind(str, Enum):
    EXPECTED_VALUE = "EXPECTED_VALUE"  # a probability-based expectation (Family A)
    CONDITIONAL_BOUND = "CONDITIONAL_BOUND"  # a full-fill worst-state payoff bound (Family B)
    REALIZED = "REALIZED"  # an actual result: none exist in this batch (no actual fills)


class FillMode(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"  # the episode's first observation: what was there at detection
    LESS_CONSERVATIVE = "LESS_CONSERVATIVE"  # the episode's best single observation (never a sum)


class Verdict(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ECONOMICALLY_UNVIABLE = "ECONOMICALLY_UNVIABLE"
    BELOW_MINIMUM_USEFUL = "BELOW_MINIMUM_USEFUL"
    CONTINUE = "CONTINUE"  # passes the screen; still not evidence of an edge


# --------------------------------------------------------------------------- size ladder


@dataclass(frozen=True)
class SizePoint:
    """One rung: requesting `quantity` native units from one observation's captured ladder."""

    quantity: Decimal
    depth_status: str  # opportunity.DepthStatus value
    all_in_cost_per_unit: Decimal | None  # cash out per unit, fees included (capital, not a cost)
    gross_edge_per_unit: Decimal | None  # value per unit - average price (before fees)
    net_edge_per_unit: Decimal | None  # value per unit - all-in cost per unit (after fees; counted once)
    detail: str = ""

    @property
    def fillable(self) -> bool:
        return self.depth_status == DepthStatus.FILLABLE.value and self.all_in_cost_per_unit is not None


def size_ladder_from_depth(ladder: DepthLadder, quantities: Sequence[Decimal], fee_schedule: FeeSchedule, *,
                           value_per_unit: Decimal | None, price_grid: PriceGrid | None = None) -> tuple[SizePoint, ...]:
    """Price each rung with the canonical depth walk and fee schedule.

    `value_per_unit` is what one unit is worth under the family's method: a probability times
    the payout per unit (EXPECTED_VALUE) or a proven worst-state payout (CONDITIONAL_BOUND). None
    (unknown) leaves every edge None: no probability means no estimated EV."""
    points = []
    for quantity in sorted(set(quantities)):
        fill = walk_ladder(ladder, quantity, price_grid=price_grid)
        cost, why = price_depth_fill(fill, fee_schedule)
        if cost is None:
            points.append(SizePoint(quantity, fill.status.value, None, None, None, why))
            continue
        gross = None if value_per_unit is None else value_per_unit - fill.average_price
        net = None if value_per_unit is None else value_per_unit - cost.cost_per_contract
        points.append(SizePoint(quantity, fill.status.value, cost.cost_per_contract, gross, net, fill.detail))
    return tuple(points)


# --------------------------------------------------------------------------- episodes


@dataclass(frozen=True)
class Observation:
    observation_id: str
    liquidity_keys: tuple[str, ...]  # resting-order pools it draws on (a market side; every leg of a basket)
    venue: str
    observed_at_utc: str  # receipt time of the newest input
    cluster_id: str  # game / event day: the dependence unit
    edge_kind: EdgeKind
    ladder: tuple[SizePoint, ...]
    release_at_utc: str | None  # when an entry here would get its cash back (settlement); None = unknown
    evidence_ids: tuple[str, ...] = ()

    def rung(self, quantity: Decimal) -> SizePoint | None:
        for point in self.ladder:
            if point.quantity == quantity:
                return point
        return None

    def best_fillable_at_most(self, quantity: Decimal) -> SizePoint | None:
        fillable = [p for p in self.ladder if p.quantity <= quantity and p.fillable]
        return max(fillable, key=lambda p: p.quantity) if fillable else None


@dataclass(frozen=True)
class EpisodeDefinition:
    """Frozen in the protocol before any outcome is viewed. A None field is UNKNOWN."""

    version: str
    start_threshold: Decimal | None  # net edge per unit at `minimum_size` that starts an episode
    end_merge_gap_seconds: int | None  # a gap longer than this ends the episode
    minimum_size: Decimal | None  # the rung at which qualification is judged
    frozen: bool  # recorded in a protocol before outcomes were viewed

    def problems(self) -> list[str]:
        missing = [n for n in ("start_threshold", "end_merge_gap_seconds", "minimum_size") if getattr(self, n) is None]
        out = [f"episode definition {self.version}: {', '.join(missing)} UNKNOWN"] if missing else []
        if not self.frozen:
            out.append(f"episode definition {self.version} is not frozen in a protocol before outcomes were viewed")
        return out


@dataclass(frozen=True)
class Episode:
    episode_id: str
    liquidity_keys: tuple[str, ...]
    venue: str
    cluster_id: str
    edge_kind: str
    start_utc: str
    end_utc: str
    observation_ids: tuple[str, ...]
    entry: Observation  # CONSERVATIVE: the first qualifying observation
    best: Observation  # LESS_CONSERVATIVE: the best single qualifying observation

    def chosen(self, mode: FillMode) -> Observation:
        return self.entry if mode is FillMode.CONSERVATIVE else self.best


@dataclass(frozen=True)
class EpisodeSet:
    definition: EpisodeDefinition
    episodes: tuple[Episode, ...]
    observations: int
    qualifying_observations: int
    problems: tuple[str, ...]  # non-empty: no episodes could be formed


def _qualifies(obs: Observation, d: EpisodeDefinition) -> bool:
    point = obs.rung(d.minimum_size)
    return (point is not None and point.fillable and point.net_edge_per_unit is not None
            and point.net_edge_per_unit >= d.start_threshold)


def _time(value: str, what: str) -> datetime:
    parsed = parse_utc(value)
    if parsed is None:
        raise ValueError(f"{what} {value!r} is not a timezone-aware time")
    return parsed


def build_episodes(observations: Iterable[Observation], definition: EpisodeDefinition) -> EpisodeSet:
    """Group observations into distinct episodes per liquidity pool.

    Per pool (the observation's full key tuple), in time order: a qualifying observation
    starts an episode or extends the open one when within the merge gap; a non-qualifying
    observation, or a longer gap, ends it. The best observation is chosen by the net edge x
    quantity at `minimum_size`. Observation ids must be unique."""
    observations = list(observations)
    ids = [o.observation_id for o in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("observation ids must be unique")
    problems = definition.problems()
    if problems:
        return EpisodeSet(definition, (), len(observations), 0, tuple(problems))
    gap = timedelta(seconds=definition.end_merge_gap_seconds)
    pools: dict[tuple[str, ...], list[Observation]] = {}
    for obs in observations:
        _time(obs.observed_at_utc, "observed_at_utc")
        pools.setdefault(tuple(sorted(obs.liquidity_keys)), []).append(obs)
    episodes: list[Episode] = []
    qualifying = 0

    def close(run: list[Observation]) -> None:
        if not run:
            return
        size = definition.minimum_size

        def value(o: Observation) -> Decimal:
            return o.rung(size).net_edge_per_unit * size

        best = max(run, key=lambda o: (value(o), o.observed_at_utc, o.observation_id))
        first = run[0]
        eid = "ep-" + sha256_hex(canonical_json([definition.version, list(first.liquidity_keys),
                                                 [o.observation_id for o in run]]))[:24]
        episodes.append(Episode(eid, tuple(sorted(first.liquidity_keys)), first.venue, first.cluster_id,
                                first.edge_kind.value, first.observed_at_utc, run[-1].observed_at_utc,
                                tuple(o.observation_id for o in run), first, best))

    for key in sorted(pools):
        run: list[Observation] = []
        for obs in sorted(pools[key], key=lambda o: (_time(o.observed_at_utc, "observed_at_utc"), o.observation_id)):
            if not _qualifies(obs, definition):
                close(run)
                run = []
                continue
            qualifying += 1
            if run and _time(obs.observed_at_utc, "t") - _time(run[-1].observed_at_utc, "t") > gap:
                close(run)
                run = []
            run.append(obs)
        close(run)
    episodes.sort(key=lambda e: (e.start_utc, e.episode_id))
    return EpisodeSet(definition, tuple(episodes), len(observations), qualifying, ())


# --------------------------------------------------------------------------- replay


@dataclass(frozen=True)
class CapitalScenario:
    """Finite capital per venue. Every amount is a scenario, never an approved bankroll."""

    label: str
    capital_by_venue: Mapping[str, Labeled]
    reserve_by_venue: Mapping[str, Labeled]
    quantity_step: Decimal = Decimal(1)  # the smallest native quantity an entry may take
    status: str = ILLUSTRATIVE

    def problems(self) -> list[str]:
        out = []
        for venue, amount in sorted(self.capital_by_venue.items()):
            if amount.value is None:
                out.append(f"capital for {venue} is UNKNOWN")
            reserve = self.reserve_by_venue.get(venue)
            if reserve is None or reserve.value is None:
                out.append(f"reserve for {venue} is UNKNOWN")
        if not self.capital_by_venue:
            out.append("no capital scenario was supplied")
        if not (isinstance(self.quantity_step, Decimal) and self.quantity_step > 0):
            out.append("quantity_step must be a positive Decimal")
        return out

    def total(self) -> Decimal | None:
        values = [a.value for a in self.capital_by_venue.values()]
        return None if any(v is None for v in values) or not values else sum(values, Decimal(0))


@dataclass(frozen=True)
class EpisodeFill:
    episode_id: str
    cluster_id: str
    state: str  # FILLED / CAPITAL_LIMITED / CAPITAL_VETO / DEPTH_LIMITED / NOT_FILLABLE / SHARED_LIQUIDITY
    requested: Decimal
    filled: Decimal
    rung_used: Decimal | None
    net_edge_per_unit: Decimal | None
    gross_edge_per_unit: Decimal | None
    committed_cash: Decimal
    entry_utc: str
    release_utc: str | None
    release_known: bool
    contribution: Decimal | None  # filled x net edge per unit; None when the edge is unknown
    gross_contribution: Decimal | None


@dataclass(frozen=True)
class ReplayResult:
    scenario_label: str
    scenario_status: str
    mode: str
    size: Decimal
    window_start_utc: str
    window_end_utc: str
    fills: tuple[EpisodeFill, ...]
    contribution: Decimal | None  # sum over fills; None if any filled episode's edge is unknown
    gross_contribution: Decimal | None
    capital_days: Decimal
    average_deployed: Decimal
    max_deployed: Decimal
    total_capital: Decimal | None
    idle_capital_average: Decimal | None
    return_on_deployed: Decimal | None  # contribution / average deployed, over the window
    return_on_total: Decimal | None  # contribution / total capital, over the window
    counts: dict[str, int]
    problems: tuple[str, ...]


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def replay(episodes: Sequence[Episode], scenario: CapitalScenario, *, size: Decimal, mode: FillMode,
           window_start_utc: str, window_end_utc: str) -> ReplayResult:
    """Chronological, capital-constrained replay of the episodes at one requested size.

    Each episode is entered once, at its start, using the chosen observation's ladder: the
    largest FILLABLE rung at or below `size`, then cut to the venue cash left after the
    reserve and open commitments. Commitments are released at `release_at_utc`; an unknown
    release keeps the cash committed to the window end (flagged). An episode sharing a
    liquidity key with a position that is still open gets nothing: stored books never show
    our own simulated take, so the same resting orders could otherwise be taken twice
    (conservative: one entry per pool until release). Contribution uses the rung's per-unit
    net edge; a capital-limited smaller fill keeps that (lower, deeper-rung) edge, which
    understates rather than overstates."""
    start, end = _time(window_start_utc, "window start"), _time(window_end_utc, "window end")
    if end <= start:
        raise ValueError("the replay window must have positive length")
    problems = scenario.problems()
    total = scenario.total()
    counts = {s: 0 for s in ("FILLED", "CAPITAL_LIMITED", "CAPITAL_VETO", "DEPTH_LIMITED", "NOT_FILLABLE",
                             "SHARED_LIQUIDITY", "UNKNOWN_RELEASE")}
    if problems:
        return ReplayResult(scenario.label, scenario.status, mode.value, size, window_start_utc, window_end_utc, (),
                            None, None, Decimal(0), Decimal(0), Decimal(0), total, None, None, None, counts,
                            tuple(problems))
    open_positions: list[tuple[datetime, str, Decimal, tuple[str, ...]]] = []  # release, venue, cash, keys
    committed: dict[str, Decimal] = {v: Decimal(0) for v in scenario.capital_by_venue}
    fills: list[EpisodeFill] = []
    capital_days = Decimal(0)
    max_deployed = Decimal(0)
    unknown_edge = False
    ordered = sorted(episodes, key=lambda e: (_time(e.start_utc, "start"), e.episode_id))
    for ep in ordered:
        entry_t = _time(ep.start_utc, "episode start")
        if entry_t < start or entry_t > end:
            continue
        for pos in [p for p in open_positions if p[0] <= entry_t]:
            committed[pos[1]] -= pos[2]
            open_positions.remove(pos)
        obs = ep.chosen(mode)
        keys = set(ep.liquidity_keys)

        def record(state: str, filled: Decimal, point, cash: Decimal, release: datetime | None) -> None:
            nonlocal capital_days, unknown_edge
            counts[state] += 1
            known = release is not None
            release_t = release if known else end
            if filled > 0:
                capital_days += cash * Decimal((min(release_t, end) - entry_t).total_seconds()) / Decimal(86400)
            net = point.net_edge_per_unit if point is not None else None
            gross = point.gross_edge_per_unit if point is not None else None
            if filled > 0 and net is None:
                unknown_edge = True
            fills.append(EpisodeFill(
                ep.episode_id, ep.cluster_id, state, size, filled, None if point is None else point.quantity,
                net, gross, cash, ep.start_utc, obs.release_at_utc, known,
                None if net is None else (filled * net).quantize(_Q),
                None if gross is None else (filled * gross).quantize(_Q)))

        if ep.venue not in scenario.capital_by_venue:
            record("CAPITAL_VETO", Decimal(0), None, Decimal(0), None)
            continue
        if any(keys & set(p[3]) for p in open_positions):
            record("SHARED_LIQUIDITY", Decimal(0), None, Decimal(0), None)
            continue
        point = obs.best_fillable_at_most(size)
        if point is None:
            record("NOT_FILLABLE", Decimal(0), None, Decimal(0), None)
            continue
        available = scenario.capital_by_venue[ep.venue].value - scenario.reserve_by_venue[ep.venue].value \
            - committed[ep.venue]
        affordable = _floor_to(max(available, Decimal(0)) / point.all_in_cost_per_unit, scenario.quantity_step)
        filled = min(point.quantity, affordable)
        if filled <= 0:
            record("CAPITAL_VETO", Decimal(0), point, Decimal(0), None)
            continue
        cash = filled * point.all_in_cost_per_unit
        release = parse_utc(obs.release_at_utc) if obs.release_at_utc else None
        state = "CAPITAL_LIMITED" if filled < point.quantity else ("DEPTH_LIMITED" if point.quantity < size else "FILLED")
        if release is None:
            counts["UNKNOWN_RELEASE"] += 1
        record(state, filled, point, cash, release)
        committed[ep.venue] += cash
        open_positions.append((release if release is not None else end + timedelta(days=36500), ep.venue, cash,
                               ep.liquidity_keys))
        max_deployed = max(max_deployed, sum(committed.values(), Decimal(0)))
    window_days = Decimal((end - start).total_seconds()) / Decimal(86400)
    filled_fills = [f for f in fills if f.filled > 0]
    contribution = None if unknown_edge else sum((f.contribution for f in filled_fills), Decimal(0))
    gross = None if any(f.gross_contribution is None for f in filled_fills) else \
        sum((f.gross_contribution for f in filled_fills), Decimal(0))
    average_deployed = (capital_days / window_days).quantize(_Q)
    rod = None if contribution is None or average_deployed == 0 else (contribution / average_deployed).quantize(_Q)
    rot = None if contribution is None or not total else (contribution / total).quantize(_Q)
    idle = None if total is None else (total - average_deployed).quantize(_Q)
    return ReplayResult(scenario.label, scenario.status, mode.value, size, window_start_utc, window_end_utc,
                        tuple(fills), contribution, gross, capital_days.quantize(_Q), average_deployed, max_deployed,
                        total, idle, rod, rot, counts,
                        ("contribution UNKNOWN: a filled episode has no net edge (no probability, no EV)",)
                        if unknown_edge else ())


# --------------------------------------------------------------------------- capacity


@dataclass(frozen=True)
class CapacityRow:
    size: Decimal
    mode: str
    filled_episodes: int
    depth_limited: int
    capital_limited: int
    capital_vetoed: int
    contribution: Decimal | None
    max_deployed: Decimal
    capital_days: Decimal
    marginal_contribution: Decimal | None  # vs the previous rung in the same mode
    marginal_capital: Decimal | None
    idle_capital_flag: bool  # more size/capital added nothing productive
    top_cluster_share: Decimal | None  # concentration: the largest cluster's share of contribution


def capacity_ladder(episodes: Sequence[Episode], scenario: CapitalScenario, sizes: Sequence[Decimal], *,
                    window_start_utc: str, window_end_utc: str) -> tuple[CapacityRow, ...]:
    rows: list[CapacityRow] = []
    for mode in FillMode:
        previous: ReplayResult | None = None
        for size in sorted(set(sizes)):
            r = replay(episodes, scenario, size=size, mode=mode, window_start_utc=window_start_utc,
                       window_end_utc=window_end_utc)
            marginal = None
            marginal_capital = None
            if previous is not None:
                marginal_capital = r.max_deployed - previous.max_deployed
                if r.contribution is not None and previous.contribution is not None:
                    marginal = r.contribution - previous.contribution
            idle = previous is not None and (marginal is not None and marginal <= 0) and marginal_capital >= 0
            share = None
            if r.contribution is not None and r.contribution > 0:
                by_cluster: dict[str, Decimal] = {}
                for f in r.fills:
                    if f.contribution is not None and f.filled > 0:
                        by_cluster[f.cluster_id] = by_cluster.get(f.cluster_id, Decimal(0)) + f.contribution
                share = (max(by_cluster.values()) / r.contribution).quantize(_Q) if by_cluster else None
            rows.append(CapacityRow(size, mode.value, r.counts["FILLED"] + r.counts["DEPTH_LIMITED"]
                                    + r.counts["CAPITAL_LIMITED"], r.counts["DEPTH_LIMITED"],
                                    r.counts["CAPITAL_LIMITED"], r.counts["CAPITAL_VETO"], r.contribution,
                                    r.max_deployed, r.capital_days, marginal, marginal_capital, idle, share))
            previous = r
    return tuple(rows)


# --------------------------------------------------------------------------- screen


@dataclass(frozen=True)
class ScreenInputs:
    family: str
    experiment_id: str
    episodes: EpisodeSet
    scenario: CapitalScenario
    primary_size: Decimal
    sizes: tuple[Decimal, ...]
    window_start_utc: str
    window_end_utc: str
    fixed_cash_costs_annual: Labeled  # incremental fixed cash costs (data, hosting) per year
    owner_hours_annual: Labeled
    owner_hourly_cost: Labeled  # the owner's chosen opportunity cost per hour
    minimum_useful_annual: Labeled  # OWNER_INPUT; the $50k-100k aspiration is not this
    min_episodes_for_scenario: Labeled  # protocol input; UNKNOWN = no annual scenario
    stationarity_assumption: str
    data_gaps: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreenReport:
    version: str
    family: str
    experiment_id: str
    verdict: str
    verdict_reasons: tuple[str, ...]
    not_an_edge_claim: str
    window_start_utc: str
    window_end_utc: str
    window_days: Decimal
    episodes: int
    clusters: int
    observations: int
    episodes_per_cluster: Decimal | None
    variable: dict[str, Labeled]  # window and annual-scenario variable economics, both fill modes
    fixed_cash_costs_annual: Labeled
    owner_time_cost_annual: Labeled  # shown separately; never inside the cash figures
    net_after_fixed_annual: dict[str, Labeled]
    capital: dict[str, Any]
    uncertainty: dict[str, Any]
    capacity: tuple[CapacityRow, ...]
    inputs: dict[str, Labeled]
    assumptions: tuple[str, ...]
    data_gaps: tuple[str, ...]
    scenario_status: str
    report_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def cluster_bootstrap_mean(values_by_cluster: Mapping[str, Decimal], *, seed: int = BOOTSTRAP_SEED,
                           resamples: int = BOOTSTRAP_RESAMPLES, alpha: float = 0.05) -> tuple[Decimal, Decimal, Decimal] | None:
    """(mean, lower, upper) of the per-cluster total, resampling whole clusters (games / event days).

    None with fewer than two clusters: no band is estimable. Deterministic for a given seed."""
    keys = sorted(values_by_cluster)
    if len(keys) < 2:
        return None
    values = [values_by_cluster[k] for k in keys]
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum((values[rng.randrange(n)] for _ in range(n)), Decimal(0)) / n for _ in range(resamples))
    lower = means[int(alpha / 2 * resamples)]
    upper = means[min(resamples - 1, int((1 - alpha / 2) * resamples + 0.999999) - 1)]
    return (sum(values, Decimal(0)) / n).quantize(_Q), lower.quantize(_Q), upper.quantize(_Q)


def economic_screen(inputs: ScreenInputs) -> ScreenReport:
    """The screen. It never raises for thin or missing evidence: it says INSUFFICIENT_EVIDENCE."""
    start = _time(inputs.window_start_utc, "window start")
    end = _time(inputs.window_end_utc, "window end")
    window_days = (Decimal((end - start).total_seconds()) / Decimal(86400)).quantize(_Q)
    episodes = inputs.episodes.episodes
    reasons: list[str] = list(inputs.episodes.problems)
    reasons += inputs.scenario.problems()
    runs = {mode: replay(episodes, inputs.scenario, size=inputs.primary_size, mode=mode,
                         window_start_utc=inputs.window_start_utc, window_end_utc=inputs.window_end_utc)
            for mode in FillMode}
    for mode, run in runs.items():
        reasons += [f"{mode.value}: {p}" for p in run.problems if p not in reasons]
    clusters = sorted({e.cluster_id for e in episodes})
    min_n = inputs.min_episodes_for_scenario
    annual_ok = bool(episodes) and min_n.value is not None and len(episodes) >= min_n.value and window_days > 0
    if not episodes and not inputs.episodes.problems:
        reasons.append("no distinct episode qualified in the window")
    if min_n.value is None:
        reasons.append("no annual scenario: the protocol's minimum episode count is UNKNOWN")
    elif len(episodes) < min_n.value:
        reasons.append(f"no annual scenario: {len(episodes)} distinct episodes < the protocol minimum {min_n.value}")

    variable: dict[str, Labeled] = {}
    net_after_fixed: dict[str, Labeled] = {}
    scale = DAYS_PER_YEAR / window_days if window_days > 0 else None
    fixed = inputs.fixed_cash_costs_annual
    for mode, run in runs.items():
        key = mode.value.lower()
        variable[f"window_net_{key}"] = (Labeled(run.contribution, Basis.ESTIMATED,
                                                 "window sum of filled qty x net edge per unit (after variable costs)")
                                         if run.contribution is not None else Labeled.unknown("edge unknown"))
        variable[f"window_gross_{key}"] = (Labeled(run.gross_contribution, Basis.ESTIMATED, "before variable costs")
                                           if run.gross_contribution is not None else Labeled.unknown())
        if annual_ok and run.contribution is not None:
            annual = (run.contribution * scale).quantize(_Q)
            variable[f"annual_scenario_net_{key}"] = Labeled(
                annual, Basis.ESTIMATED, f"SIMPLIFIED SCENARIO under stationarity: {inputs.stationarity_assumption}")
            net_after_fixed[key] = (Labeled((annual - fixed.value).quantize(_Q), Basis.ESTIMATED,
                                            "annual scenario minus incremental fixed cash costs")
                                    if fixed.value is not None else Labeled.unknown("fixed cash costs UNKNOWN"))
        else:
            variable[f"annual_scenario_net_{key}"] = Labeled.unknown("no annual scenario")
            net_after_fixed[key] = Labeled.unknown("no annual scenario")
    if fixed.value is None:
        reasons.append("incremental fixed cash costs are UNKNOWN")

    hours, rate = inputs.owner_hours_annual, inputs.owner_hourly_cost
    owner_cost = (Labeled((hours.value * rate.value).quantize(_Q), Basis.OWNER_INPUT,
                          "owner hours x chosen hourly opportunity cost; never inside cash P&L")
                  if hours.value is not None and rate.value is not None
                  else Labeled.unknown("owner hours or hourly opportunity cost UNKNOWN"))

    cons = runs[FillMode.CONSERVATIVE]
    per_cluster: dict[str, Decimal] = {c: Decimal(0) for c in clusters}
    if cons.contribution is not None:
        for f in cons.fills:
            if f.contribution is not None:
                per_cluster[f.cluster_id] = per_cluster.get(f.cluster_id, Decimal(0)) + f.contribution
    band = cluster_bootstrap_mean(per_cluster) if cons.contribution is not None else None
    uncertainty = {
        "method": f"cluster bootstrap of per-cluster conservative contribution (seed {BOOTSTRAP_SEED}, "
                  f"{BOOTSTRAP_RESAMPLES} resamples, 95%)",
        "clusters": len(clusters),
        "per_cluster_mean": None if band is None else band[0],
        "per_cluster_lower": None if band is None else band[1],
        "per_cluster_upper": None if band is None else band[2],
        "estimable": band is not None,
        "note": "episodes within a cluster are dependent; the band is on clusters, never on episodes or snapshots",
    }
    capital = {
        "scenario_label": inputs.scenario.label,
        "scenario_status": inputs.scenario.status,
        "total_capital": inputs.scenario.total(),
        **{f"{m.value.lower()}_{k}": getattr(runs[m], k) for m in FillMode
           for k in ("average_deployed", "max_deployed", "capital_days", "idle_capital_average",
                     "return_on_deployed", "return_on_total")},
        "conservative_counts": cons.counts,
        "less_conservative_counts": runs[FillMode.LESS_CONSERVATIVE].counts,
    }
    capacity = capacity_ladder(episodes, inputs.scenario, inputs.sizes or (inputs.primary_size,),
                               window_start_utc=inputs.window_start_utc,
                               window_end_utc=inputs.window_end_utc) if not inputs.scenario.problems() else ()

    verdict, why = _verdict(inputs, net_after_fixed, reasons)
    input_labels = {"fixed_cash_costs_annual": fixed, "owner_hours_annual": hours, "owner_hourly_cost": rate,
                    "minimum_useful_annual": inputs.minimum_useful_annual,
                    "min_episodes_for_scenario": min_n,
                    **{f"capital:{v}": a for v, a in sorted(inputs.scenario.capital_by_venue.items())},
                    **{f"reserve:{v}": a for v, a in sorted(inputs.scenario.reserve_by_venue.items())}}
    report = ScreenReport(
        ECONOMICS_VERSION, inputs.family, inputs.experiment_id, verdict.value, tuple(why),
        "A screen verdict is a research state. It is not evidence of an edge, and no amount here is an approved "
        "bankroll or an income forecast.",
        inputs.window_start_utc, inputs.window_end_utc, window_days, len(episodes), len(clusters),
        inputs.episodes.observations,
        (Decimal(len(episodes)) / len(clusters)).quantize(_Q) if clusters else None,
        variable, fixed, owner_cost, net_after_fixed, capital, uncertainty, capacity, input_labels,
        tuple(inputs.assumptions) + (f"stationarity: {inputs.stationarity_assumption}",
                                     "observed depth is a ceiling, not a guaranteed fill",
                                     "fees are inside net edge per unit and are not subtracted again"),
        tuple(inputs.data_gaps), inputs.scenario.status)
    body = report.to_dict()
    body.pop("report_sha256")
    return _with_hash(report, sha256_hex(canonical_json(body)))


def _with_hash(report: ScreenReport, digest: str) -> ScreenReport:
    return replace(report, report_sha256=digest)


def _verdict(inputs: ScreenInputs, net_after_fixed: Mapping[str, Labeled],
             reasons: list[str]) -> tuple[Verdict, list[str]]:
    cons = net_after_fixed.get(FillMode.CONSERVATIVE.value.lower())
    less = net_after_fixed.get(FillMode.LESS_CONSERVATIVE.value.lower())
    if less is None or less.value is None or cons is None or cons.value is None:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons or ["annual scenario unavailable"]
    if less.value <= 0:
        return Verdict.ECONOMICALLY_UNVIABLE, [
            f"even the less-conservative annual scenario net of fixed cash costs is {less.value} <= 0"]
    minimum = inputs.minimum_useful_annual
    if minimum.value is None:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            "the minimum useful annual contribution is an OWNER_INPUT that was not supplied"]
    if less.value < minimum.value:
        return Verdict.BELOW_MINIMUM_USEFUL, [
            f"less-conservative scenario {less.value} < minimum useful {minimum.value}"]
    if cons.value >= minimum.value:
        return Verdict.CONTINUE, [f"conservative scenario {cons.value} >= minimum useful {minimum.value}; "
                                  "continue research, not an edge claim"]
    return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
        f"the verdict depends on the fill assumption: conservative {cons.value} < minimum {minimum.value} "
        f"<= less-conservative {less.value}"]
