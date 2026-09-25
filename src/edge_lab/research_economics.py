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
- `Observation`: one point-in-time look at one liquidity pool (a market side, or the legs of a
  basket). It carries its size ladder, its dependence clusters (a fine `cluster_id` and an
  optional coarser `outer_cluster_id`, for example game and NFL week) and its capital-release
  time.
- `EpisodeDefinition` / `build_episodes`: distinct opportunity episodes under a definition that
  is frozen in the protocol **before outcomes are viewed** (start threshold, end/merge gap,
  minimum size).
  - Observations that share any liquidity key form one pool (connected components), so a leg
    and a basket containing it are never two opportunities.
  - Repeated observations of the same resting orders are one episode, never many.
  - An incomplete or unfrozen definition yields no episodes (INSUFFICIENT_EVIDENCE).
- `CapitalScenario` / `replay`: chronological, capital-constrained replay.
  - Capital is finite per venue, with a reserve and release on settlement.
  - Every strategy passed in together shares one pool, so capital is never double counted
    across simultaneous strategies.
  - A liquidity pool held by an open position is not taken again until release.
  - A release before entry is refused.
- `capacity_ladder`: the replay at every rung, in both fill modes (labels v2, ADR 0037):
  FIRST_DETECTION_ZERO_LATENCY (enum CONSERVATIVE: the first qualifying observation, with no
  decision or submission delay) and HINDSIGHT_UPPER_BOUND (enum LESS_CONSERVATIVE: the best
  single observation *at that size*, chosen after the whole episode was seen). Neither is
  executable performance (`FILL_MODE_SEMANTICS`). It reports marginal contribution and
  marginal capital, and flags where more capital only adds idle balance.
- `economic_screen` reports, each shown separately:
  - variable economics, fixed cash costs and owner-hour cost;
  - return on deployed versus total capital, and capital-days;
  - frequency;
  - a cluster-bootstrap band on the coarsest cluster level;
  - assumptions and data gaps;
  - a verdict decided on the band, not the point estimate.

Rules:
- Every input is `Labeled` OBSERVED / ESTIMATED / OWNER_INPUT / UNKNOWN; UNKNOWN has no value.
- `net_edge_per_unit` is after variable costs (fees, spread, slippage). Nothing subtracts a
  fee or a loss again later. There is no bankroll x size x turnover product anywhere.
- Observed depth is a ceiling, not a guaranteed fill; fill probability is not assumed.
- Only episodes that start inside the window count, for frequency, clusters and minima alike.
- The annual figure is a SIMPLIFIED SCENARIO (window contribution x 365 / window days) under a
  stated stationarity assumption. It is produced only when the protocol's minimum episode count
  is supplied and met, and it is never an income forecast.
- The verdicts are INSUFFICIENT_EVIDENCE, ECONOMICALLY_UNVIABLE, BELOW_MINIMUM_USEFUL and
  CONTINUE. They are research states, not code failures, and none of them is an edge claim.
  - CONTINUE needs the conservative band's *lower* bound, net of fixed costs, to reach the
    owner's minimum.
  - Fewer than two independent clusters is INSUFFICIENT_EVIDENCE.

Pure, deterministic, stdlib-only and network-free.
"""


import random
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .experiments import RESERVED_TEST_EXPERIMENT_IDS as _RESERVED_TEST_IDS
from .freshness import parse_utc
from .opportunity import DepthLadder, DepthStatus, FeeSchedule, PriceGrid, price_depth_fill, walk_ladder
from .provenance import canonical_json, sha256_hex

# v2 (2026-09-25, ADR 0037): fill-mode labels only. The arithmetic, the enum values and the verdict
# rules are unchanged from v1; reports now say what each fill mode is (FILL_MODE_SEMANTICS).
ECONOMICS_VERSION = "research-economics-v2"
REPO_EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
PROTOCOL_MINIMUMS = ("min_episodes_for_scenario", "min_independent_clusters")
# The only experiment ids whose screen minimums may come from the caller (unit tests). Every
# other id, whatever its spelling, takes them from the repository protocol, and an id without
# settled protocol values gets UNKNOWN, never the caller's numbers.
SCREEN_TEST_EXPERIMENT_IDS = _RESERVED_TEST_IDS  # reserved in the registry (experiments.validate)


def normalize_experiment_id(experiment_id: str) -> str:
    return str(experiment_id).strip().upper()
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
    """The enum values are kept for compatibility (v1 reports, callers). What they mean, and what they
    may be used for, is `FILL_MODE_SEMANTICS` (labels v2, ADR 0037); read the label, not the name."""

    CONSERVATIVE = "CONSERVATIVE"  # label FIRST_DETECTION_ZERO_LATENCY: the first qualifying observation
    LESS_CONSERVATIVE = "LESS_CONSERVATIVE"  # label HINDSIGHT_UPPER_BOUND: the best single observation, ex post


FILL_MODE_LABELS_VERSION = "fill-mode-labels-v2"
# What a replay under any fill mode is. There are no actual or delay-adjusted fills in this module.
EXECUTABLE_PERFORMANCE = ("NONE: every fill mode replays captured books with no order, no queue, no decision or "
                          "submission delay and no fill probability; no figure here is executable performance")


@dataclass(frozen=True)
class FillModeSemantics:
    """The honest reading of one fill mode (labels v2, 2026-09-25, ADR 0037).

    v1 called the two modes "conservative (fill at detection)" and "less conservative (the best single
    observation)". Both names overstated what the evidence shows:
    - the first detected quote was not shown to survive a realistic decision and submission delay, so
      "conservative" is not conservative about latency;
    - the best observation is chosen after the whole episode was seen, so it is an oracle (hindsight)
      upper bound, not a policy anyone could have followed.
    """

    mode: FillMode
    label: str
    selection: str
    prospective_selection: bool  # chosen with only information available at the entry time
    delay_adjusted: bool  # accounts for decision and submission delay
    executable_performance: bool  # always False: no fill here is executable performance
    permitted_use: str
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "label": self.label, "selection": self.selection,
                "prospective_selection": self.prospective_selection, "delay_adjusted": self.delay_adjusted,
                "executable_performance": self.executable_performance, "permitted_use": self.permitted_use,
                "caveat": self.caveat, "labels_version": FILL_MODE_LABELS_VERSION}


FILL_MODE_SEMANTICS: dict[FillMode, FillModeSemantics] = {
    FillMode.CONSERVATIVE: FillModeSemantics(
        FillMode.CONSERVATIVE, "FIRST_DETECTION_ZERO_LATENCY",
        "the episode's first qualifying observation, taken at its receipt time",
        prospective_selection=True, delay_adjusted=False, executable_performance=False,
        permitted_use="the screen's lower-side band (the CONTINUE test); a research state, never an execution result",
        caveat="assumes zero decision and submission delay: the first observed quote may already be gone by the time "
               "an order could reach the venue, so this is not a conservative bound on latency"),
    FillMode.LESS_CONSERVATIVE: FillModeSemantics(
        FillMode.LESS_CONSERVATIVE, "HINDSIGHT_UPPER_BOUND",
        "the episode's best single observation at the replayed size (never a sum), chosen after the whole episode "
        "was seen",
        prospective_selection=False, delay_adjusted=False, executable_performance=False,
        permitted_use="an upper bound only: it may rule a family out (ECONOMICALLY_UNVIABLE, BELOW_MINIMUM_USEFUL) "
                      "and never supports CONTINUE or any performance claim",
        caveat="an oracle choice: no prospective policy could have known which observation would be best"),
}


def fill_mode_label(mode: FillMode) -> str:
    return FILL_MODE_SEMANTICS[mode].label


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


# --------------------------------------------------------------------------- episodes


@dataclass(frozen=True)
class Observation:
    observation_id: str
    liquidity_keys: tuple[str, ...]  # resting-order pools it draws on (a market side; every leg of a basket)
    venue: str
    observed_at_utc: str  # receipt time of the newest input
    cluster_id: str  # the fine dependence unit (game / event day)
    edge_kind: EdgeKind
    ladder: tuple[SizePoint, ...]
    release_at_utc: str | None  # when an entry here would get its cash back (settlement); None = unknown
    evidence_ids: tuple[str, ...] = ()
    outer_cluster_id: str | None = None  # a coarser dependence unit (NFL week / slate), when one applies

    def rung(self, quantity: Decimal) -> SizePoint | None:
        for point in self.ladder:
            if point.quantity == quantity:
                return point
        return None

    def best_fillable_at_most(self, quantity: Decimal) -> SizePoint | None:
        fillable = [p for p in self.ladder if p.quantity <= quantity and p.fillable]
        return max(fillable, key=lambda p: p.quantity) if fillable else None

    def value_at(self, quantity: Decimal) -> Decimal | None:
        """Net contribution of taking up to `quantity` here, before capital limits (None = unknown)."""
        point = self.best_fillable_at_most(quantity)
        if point is None or point.net_edge_per_unit is None:
            return None
        return point.quantity * point.net_edge_per_unit


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
    liquidity_keys: tuple[str, ...]  # the union over the pool's observations in this episode
    venue: str
    cluster_id: str
    outer_cluster_id: str | None
    edge_kind: str
    start_utc: str
    end_utc: str
    observation_ids: tuple[str, ...]
    observations: tuple[Observation, ...]  # the qualifying observations, in time order

    @property
    def entry(self) -> Observation:
        """FIRST_DETECTION_ZERO_LATENCY (enum CONSERVATIVE): the first qualifying observation, as if an order
        reached the venue at its receipt time with no decision or submission delay."""
        return self.observations[0]

    def best_at(self, size: Decimal, *, until: datetime | None = None) -> Observation:
        """HINDSIGHT_UPPER_BOUND (enum LESS_CONSERVATIVE): the single observation (never a sum) with the
        largest value at the replayed `size`, chosen after the whole episode was seen (an oracle choice, not a
        prospective policy); ties go to the earliest. Observations after `until` are not eligible."""
        eligible = [o for o in self.observations if until is None or _time(o.observed_at_utc, "t") <= until]
        if not eligible:
            return self.entry
        known = [o for o in eligible if o.value_at(size) is not None]
        if not known:
            return eligible[0]
        return max(known, key=lambda o: (o.value_at(size), -_time(o.observed_at_utc, "t").timestamp()))

    def chosen(self, mode: FillMode, size: Decimal, *, until: datetime | None = None) -> Observation:
        return self.entry if mode is FillMode.CONSERVATIVE else self.best_at(size, until=until)


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


def _components(observations: Sequence[Observation]) -> dict[str, list[Observation]]:
    """Pools = connected components of observations that share any liquidity key."""
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for obs in observations:
        if not obs.liquidity_keys:
            raise ValueError(f"observation {obs.observation_id} has no liquidity key")
        keys = sorted(obs.liquidity_keys)
        for other in keys[1:]:
            a, b = find(keys[0]), find(other)
            if a != b:
                parent[max(a, b)] = min(a, b)
    pools: dict[str, list[Observation]] = {}
    for obs in observations:
        pools.setdefault(find(sorted(obs.liquidity_keys)[0]), []).append(obs)
    return pools


def build_episodes(observations: Iterable[Observation], definition: EpisodeDefinition) -> EpisodeSet:
    """Group observations into distinct episodes per shared-liquidity pool.

    A pool is a connected component of observations linked by any common liquidity key. In
    time order within a pool, a qualifying observation starts an episode, or extends the open
    one when it is within the merge gap of the previous qualifying observation. The episode
    ends when the latest observation of every instrument in the pool no longer qualifies, or
    when the gap is exceeded. Observation ids must be unique."""
    observations = list(observations)
    ids = [o.observation_id for o in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("observation ids must be unique")
    problems = definition.problems()
    if problems:
        return EpisodeSet(definition, (), len(observations), 0, tuple(problems))
    gap = timedelta(seconds=definition.end_merge_gap_seconds)
    for obs in observations:
        _time(obs.observed_at_utc, "observed_at_utc")
    episodes: list[Episode] = []
    qualifying = 0

    def close(run: list[Observation]) -> None:
        if not run:
            return
        first = run[0]
        keys = tuple(sorted({k for o in run for k in o.liquidity_keys}))
        eid = "ep-" + sha256_hex(canonical_json([definition.version, list(keys),
                                                 [o.observation_id for o in run]]))[:24]
        episodes.append(Episode(eid, keys, first.venue, first.cluster_id, first.outer_cluster_id,
                                first.edge_kind.value, first.observed_at_utc, run[-1].observed_at_utc,
                                tuple(o.observation_id for o in run), tuple(run)))

    pools = _components(observations)
    for root in sorted(pools):
        run: list[Observation] = []
        latest: dict[tuple[str, ...], bool] = {}
        last_t: datetime | None = None
        for obs in sorted(pools[root], key=lambda o: (_time(o.observed_at_utc, "t"), o.observation_id)):
            t = _time(obs.observed_at_utc, "t")
            q = _qualifies(obs, definition)
            if q and run and last_t is not None and t - last_t > gap:
                close(run)
                run, latest = [], {}
            latest[tuple(sorted(obs.liquidity_keys))] = q
            if q:
                qualifying += 1
                run.append(obs)
                last_t = t
            elif run and not any(latest.values()):
                close(run)
                run, latest = [], {}
        close(run)
    episodes.sort(key=lambda e: (e.start_utc, e.episode_id))
    return EpisodeSet(definition, tuple(episodes), len(observations), qualifying, ())


def in_window(episodes: Iterable[Episode], window_start_utc: str, window_end_utc: str) -> tuple[Episode, ...]:
    """Episodes that start inside [start, end]: the only ones that count anywhere."""
    start, end = _time(window_start_utc, "window start"), _time(window_end_utc, "window end")
    return tuple(e for e in episodes if start <= _time(e.start_utc, "episode start") <= end)


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
    outer_cluster_id: str | None
    state: str  # FILLED / CAPITAL_LIMITED / CAPITAL_VETO / DEPTH_LIMITED / NOT_FILLABLE / SHARED_LIQUIDITY /
    #             INVALID_RELEASE
    requested: Decimal
    filled: Decimal
    rung_used: Decimal | None
    net_edge_per_unit: Decimal | None
    gross_edge_per_unit: Decimal | None
    committed_cash: Decimal
    entry_utc: str  # the chosen observation's time
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
    mode_label: str = ""  # FILL_MODE_SEMANTICS label (labels v2); never executable performance


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


REPLAY_STATES = ("FILLED", "CAPITAL_LIMITED", "CAPITAL_VETO", "DEPTH_LIMITED", "NOT_FILLABLE", "SHARED_LIQUIDITY",
                 "INVALID_RELEASE", "UNKNOWN_RELEASE")


def replay(episodes: Sequence[Episode], scenario: CapitalScenario, *, size: Decimal, mode: FillMode,
           window_start_utc: str, window_end_utc: str) -> ReplayResult:
    """Chronological, capital-constrained replay of the in-window episodes at one requested size.

    Each episode is entered once, at the chosen observation (CONSERVATIVE, labelled
    FIRST_DETECTION_ZERO_LATENCY: the first, with no decision or submission delay; LESS_CONSERVATIVE,
    labelled HINDSIGHT_UPPER_BOUND: the best single observation at `size` inside the window, chosen ex
    post). Neither is executable performance (`EXECUTABLE_PERFORMANCE`). The entry
    takes the largest FILLABLE rung at or below `size`, cut to the venue cash left after the
    reserve and open commitments.
    - Commitments are released at `release_at_utc`. An unknown release keeps the cash committed
      to the window end (flagged); a release before the entry is refused (INVALID_RELEASE).
    - An episode sharing a liquidity key with a position that is still open gets nothing.
      Stored books never show our own simulated take, so the same resting orders could otherwise
      be taken twice (conservative: one entry per pool until release).
    - Contribution uses the rung's per-unit net edge. A capital-limited smaller fill keeps that
      (lower, deeper-rung) edge, which understates rather than overstates."""
    start, end = _time(window_start_utc, "window start"), _time(window_end_utc, "window end")
    if end <= start:
        raise ValueError("the replay window must have positive length")
    problems = scenario.problems()
    total = scenario.total()
    counts = {s: 0 for s in REPLAY_STATES}
    if problems:
        return ReplayResult(scenario.label, scenario.status, mode.value, size, window_start_utc, window_end_utc, (),
                            None, None, Decimal(0), Decimal(0), Decimal(0), total, None, None, None, counts,
                            tuple(problems), fill_mode_label(mode))
    open_positions: list[tuple[datetime, str, Decimal, tuple[str, ...]]] = []  # release, venue, cash, keys
    committed: dict[str, Decimal] = {v: Decimal(0) for v in scenario.capital_by_venue}
    fills: list[EpisodeFill] = []
    capital_days = Decimal(0)
    max_deployed = Decimal(0)
    unknown_edge = False
    extra_problems: list[str] = []
    entries = []
    for ep in in_window(episodes, window_start_utc, window_end_utc):
        obs = ep.chosen(mode, size, until=end)
        entries.append((_time(obs.observed_at_utc, "entry"), ep.episode_id, ep, obs))
    for entry_t, _, ep, obs in sorted(entries, key=lambda x: (x[0], x[1])):
        for pos in [p for p in open_positions if p[0] <= entry_t]:
            committed[pos[1]] -= pos[2]
            open_positions.remove(pos)
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
                ep.episode_id, ep.cluster_id, ep.outer_cluster_id, state, size, filled,
                None if point is None else point.quantity, net, gross, cash, obs.observed_at_utc,
                obs.release_at_utc, known,
                None if net is None else (filled * net).quantize(_Q),
                None if gross is None else (filled * gross).quantize(_Q)))

        if ep.venue not in scenario.capital_by_venue:
            record("CAPITAL_VETO", Decimal(0), None, Decimal(0), None)
            continue
        release = None
        if obs.release_at_utc:
            release = parse_utc(obs.release_at_utc)
            if release is None or release < entry_t:
                record("INVALID_RELEASE", Decimal(0), None, Decimal(0), None)
                extra_problems.append(f"{ep.episode_id}: release {obs.release_at_utc} is unparseable or before the "
                                      f"entry {obs.observed_at_utc}; not filled")
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
    if unknown_edge:
        extra_problems.append("contribution UNKNOWN: a filled episode has no net edge (no probability, no EV)")
    return ReplayResult(scenario.label, scenario.status, mode.value, size, window_start_utc, window_end_utc,
                        tuple(fills), contribution, gross, capital_days.quantize(_Q), average_deployed, max_deployed,
                        total, idle, rod, rot, counts, tuple(extra_problems), fill_mode_label(mode))


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
    mode_label: str = ""  # FILL_MODE_SEMANTICS label (labels v2); never executable performance


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
                        key = f.outer_cluster_id or f.cluster_id
                        by_cluster[key] = by_cluster.get(key, Decimal(0)) + f.contribution
                share = (max(by_cluster.values()) / r.contribution).quantize(_Q) if by_cluster else None
            rows.append(CapacityRow(size, mode.value, r.counts["FILLED"] + r.counts["DEPTH_LIMITED"]
                                    + r.counts["CAPITAL_LIMITED"], r.counts["DEPTH_LIMITED"],
                                    r.counts["CAPITAL_LIMITED"], r.counts["CAPITAL_VETO"], r.contribution,
                                    r.max_deployed, r.capital_days, marginal, marginal_capital, idle, share,
                                    fill_mode_label(mode)))
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
    # Protocol input: the minimum number of independent clusters, at the level actually used,
    # before any verdict other than INSUFFICIENT_EVIDENCE. UNKNOWN (the default) = no verdict.
    min_independent_clusters: Labeled = field(default_factory=lambda: Labeled(
        None, Basis.UNKNOWN, "protocol minimum independent clusters not supplied"))


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
    episodes: int  # distinct episodes that start inside the window
    episodes_outside_window: int
    clusters: int  # on `cluster_level`
    cluster_level: str  # "outer" (for example NFL week) when every episode has one, else "fine"
    observations: int
    episodes_per_cluster: Decimal | None
    variable: dict[str, Labeled]  # window and annual-scenario variable economics, both fill modes
    fixed_cash_costs_annual: Labeled
    owner_time_cost_annual: Labeled  # shown separately; never inside the cash figures
    net_after_fixed_annual: dict[str, Labeled]  # point, band lower and band upper, per fill mode
    capital: dict[str, Any]
    uncertainty: dict[str, Any]
    capacity: tuple[CapacityRow, ...]
    inputs: dict[str, Labeled]
    assumptions: tuple[str, ...]
    data_gaps: tuple[str, ...]
    scenario_status: str
    # What each fill mode is (labels v2, ADR 0037), keyed like the report's figures (conservative /
    # less_conservative), and the statement that none of them is executable performance.
    fill_modes: dict[str, Any] = field(default_factory=dict)
    executable_performance: str = EXECUTABLE_PERFORMANCE
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
    """(mean, lower, upper) of the per-cluster total, resampling whole clusters.

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


def protocol_minimums(experiment_id: str, *, root: Path | None = None) -> dict[str, Labeled]:
    """The screen minimums an experiment's protocol has settled, as `Labeled` values.

    Callers (PR C, the Terminal) take `min_episodes_for_scenario` and `min_independent_clusters`
    from here and never pass their own numbers. A value the protocol has not settled (for example
    "MISSING_POWER_ANALYSIS: ...") is UNKNOWN, so the screen can only say INSUFFICIENT_EVIDENCE.
    An experiment without a protocol yields UNKNOWN for both."""
    from . import experiments

    # The repository's own experiments/ registry, not a dashboard --experiments-root: the
    # screen's minimums are whatever the committed protocol says.
    root = root or REPO_EXPERIMENTS
    experiment_id = normalize_experiment_id(experiment_id)
    out = {k: Labeled.unknown(f"{experiment_id}: no protocol value") for k in PROTOCOL_MINIMUMS}
    matches = [p for p in experiments.discover(root) if p.parent.name.startswith(experiment_id + "-")]
    if len(matches) != 1:
        return out
    try:
        protocol = experiments.load_protocol(experiments.load(matches[0])) or {}
    except (OSError, ValueError):
        return out
    table = protocol.get("economics") if isinstance(protocol.get("economics"), dict) else {}
    for key in PROTOCOL_MINIMUMS:
        raw = table.get(key)
        if isinstance(raw, bool) or raw is None:
            continue
        if isinstance(raw, str) and experiments._unsettled(raw):
            out[key] = Labeled.unknown(f"{experiment_id} protocol [economics] {key}: {raw}")
            continue
        try:
            value = Decimal(str(raw).strip())
        except Exception:  # noqa: BLE001 - any unparseable text stays UNKNOWN
            out[key] = Labeled.unknown(f"{experiment_id} protocol [economics] {key} is not a number: {raw!r}")
            continue
        if value.is_finite() and value >= 0 and value == value.to_integral_value():
            out[key] = Labeled(value, Basis.OWNER_INPUT, f"{experiment_id} protocol [economics] {key}")
        else:
            out[key] = Labeled.unknown(f"{experiment_id} protocol [economics] {key} is not a whole count: {raw!r}")
    return out


def _cluster_key(outer: bool, cluster_id: str, outer_id: str | None) -> str:
    return (outer_id or cluster_id) if outer else cluster_id


def economic_screen(inputs: ScreenInputs) -> ScreenReport:
    """The screen. It never raises for thin or missing evidence: it says INSUFFICIENT_EVIDENCE."""
    start = _time(inputs.window_start_utc, "window start")
    end = _time(inputs.window_end_utc, "window end")
    window_days = (Decimal((end - start).total_seconds()) / Decimal(86400)).quantize(_Q)
    all_episodes = inputs.episodes.episodes
    episodes = in_window(all_episodes, inputs.window_start_utc, inputs.window_end_utc)
    outside = len(all_episodes) - len(episodes)
    reasons: list[str] = list(inputs.episodes.problems)
    # The minimums come from the experiment's protocol (the repository experiments/ root); a caller
    # never supplies them. Only the explicit test ids may. Anything else that is not found, or whose
    # protocol lacks the keys, is UNKNOWN, so the verdict is INSUFFICIENT_EVIDENCE (fail closed).
    if normalize_experiment_id(inputs.experiment_id) not in SCREEN_TEST_EXPERIMENT_IDS:
        declared = protocol_minimums(inputs.experiment_id)
        supplied = {"min_episodes_for_scenario": inputs.min_episodes_for_scenario,
                    "min_independent_clusters": inputs.min_independent_clusters}
        mismatched = [k for k in PROTOCOL_MINIMUMS if supplied[k].value != declared[k].value]
        if mismatched:
            reasons.append(f"screen minimums {mismatched} differ from {inputs.experiment_id!r}'s protocol; the "
                           "protocol values are used (research_economics.protocol_minimums)")
        inputs = replace(inputs, min_episodes_for_scenario=declared["min_episodes_for_scenario"],
                         min_independent_clusters=declared["min_independent_clusters"])
    reasons += inputs.scenario.problems()
    runs = {mode: replay(episodes, inputs.scenario, size=inputs.primary_size, mode=mode,
                         window_start_utc=inputs.window_start_utc, window_end_utc=inputs.window_end_utc)
            for mode in FillMode}
    for mode, run in runs.items():
        reasons += [f"{mode.value}: {p}" for p in run.problems if f"{mode.value}: {p}" not in reasons]
    outer = bool(episodes) and all(e.outer_cluster_id for e in episodes)
    mixed = not outer and any(e.outer_cluster_id for e in episodes)
    level = "outer" if outer else ("mixed" if mixed else "fine")
    if mixed:
        # Falling back to the finer level would narrow the band; refuse a verdict instead.
        reasons.append("some episodes carry an outer cluster id and some do not: the dependence level is "
                       "inconsistent, so no verdict beyond INSUFFICIENT_EVIDENCE is possible")
    clusters = sorted({_cluster_key(outer, e.cluster_id, e.outer_cluster_id) for e in episodes})
    min_n = inputs.min_episodes_for_scenario
    annual_ok = bool(episodes) and min_n.value is not None and len(episodes) >= min_n.value and window_days > 0
    if outside:
        reasons.append(f"{outside} episode(s) outside the window are not counted")
    if not episodes and not inputs.episodes.problems:
        reasons.append("no distinct episode qualified in the window")
    if min_n.value is None:
        reasons.append("no annual scenario: the protocol's minimum episode count is UNKNOWN")
    elif len(episodes) < min_n.value:
        reasons.append(f"no annual scenario: {len(episodes)} distinct in-window episodes < the protocol minimum "
                       f"{min_n.value}")

    scale = DAYS_PER_YEAR / window_days if window_days > 0 else None
    fixed = inputs.fixed_cash_costs_annual
    variable: dict[str, Labeled] = {}
    net_after_fixed: dict[str, Labeled] = {}
    bands: dict[FillMode, tuple[Decimal, Decimal, Decimal] | None] = {}
    for mode, run in runs.items():
        key = mode.value.lower()
        tag = f"{fill_mode_label(mode)}; not executable performance"
        per_cluster: dict[str, Decimal] = {c: Decimal(0) for c in clusters}
        if run.contribution is not None:
            for f in run.fills:
                if f.contribution is not None:
                    k = _cluster_key(outer, f.cluster_id, f.outer_cluster_id)
                    per_cluster[k] = per_cluster.get(k, Decimal(0)) + f.contribution
        bands[mode] = cluster_bootstrap_mean(per_cluster) if run.contribution is not None else None
        variable[f"window_net_{key}"] = (Labeled(run.contribution, Basis.ESTIMATED,
                                                 "window sum of filled qty x net edge per unit (after variable costs)"
                                                 f"; {tag}")
                                         if run.contribution is not None else Labeled.unknown(f"edge unknown; {tag}"))
        variable[f"window_gross_{key}"] = (Labeled(run.gross_contribution, Basis.ESTIMATED,
                                                   f"before variable costs; {tag}")
                                           if run.gross_contribution is not None else Labeled.unknown(tag))
        scenario_note = f"SIMPLIFIED SCENARIO under stationarity: {inputs.stationarity_assumption}; {tag}"
        if annual_ok and run.contribution is not None:
            annual = (run.contribution * scale).quantize(_Q)
            variable[f"annual_scenario_net_{key}"] = Labeled(annual, Basis.ESTIMATED, scenario_note)
            band = bands[mode]
            per_year = Decimal(len(clusters)) * scale
            for label, value in (("lower", None if band is None else band[1]),
                                 ("upper", None if band is None else band[2])):
                variable[f"annual_band_{label}_{key}"] = (
                    Labeled((value * per_year).quantize(_Q), Basis.ESTIMATED,
                            f"95% cluster-bootstrap {label} bound ({level} clusters), annualized; {scenario_note}")
                    if value is not None else Labeled.unknown("fewer than two independent clusters"))
            for label, source in (("point", f"annual_scenario_net_{key}"), ("lower", f"annual_band_lower_{key}"),
                                  ("upper", f"annual_band_upper_{key}")):
                value = variable[source].value
                net_after_fixed[f"{key}_{label}"] = (
                    Labeled((value - fixed.value).quantize(_Q), Basis.ESTIMATED,
                            f"{label} minus fixed cash costs; {tag}")
                    if value is not None and fixed.value is not None
                    else Labeled.unknown("fixed cash costs or the band UNKNOWN"))
        else:
            variable[f"annual_scenario_net_{key}"] = Labeled.unknown("no annual scenario")
            for label in ("lower", "upper"):
                variable[f"annual_band_{label}_{key}"] = Labeled.unknown("no annual scenario")
            for label in ("point", "lower", "upper"):
                net_after_fixed[f"{key}_{label}"] = Labeled.unknown("no annual scenario")
    if fixed.value is None:
        reasons.append("incremental fixed cash costs are UNKNOWN")

    hours, rate = inputs.owner_hours_annual, inputs.owner_hourly_cost
    owner_cost = (Labeled((hours.value * rate.value).quantize(_Q), Basis.OWNER_INPUT,
                          "owner hours x chosen hourly opportunity cost; never inside cash P&L")
                  if hours.value is not None and rate.value is not None
                  else Labeled.unknown("owner hours or hourly opportunity cost UNKNOWN"))

    cons, less = runs[FillMode.CONSERVATIVE], runs[FillMode.LESS_CONSERVATIVE]
    inversion = (cons.contribution is not None and less.contribution is not None
                 and less.contribution < cons.contribution)
    if inversion:
        reasons.append(f"fill-mode inversion: {fill_mode_label(FillMode.LESS_CONSERVATIVE)} {less.contribution} < "
                       f"{fill_mode_label(FillMode.CONSERVATIVE)} {cons.contribution} (capital path dependence); the "
                       "band check uses each mode as computed")
    uncertainty = {
        "method": f"cluster bootstrap of per-cluster contribution (seed {BOOTSTRAP_SEED}, {BOOTSTRAP_RESAMPLES} "
                  "resamples, 95%), on the coarsest cluster level present on every episode",
        "cluster_level": level,
        "clusters": len(clusters),
        **{f"{m.value.lower()}_per_cluster_{name}": (None if bands[m] is None else bands[m][i])
           for m in FillMode for i, name in enumerate(("mean", "lower", "upper"))},
        "estimable": bands[FillMode.CONSERVATIVE] is not None and bands[FillMode.LESS_CONSERVATIVE] is not None,
        "note": "episodes within a cluster are dependent; the band is on clusters, never on episodes or snapshots. "
                "The annualized band scales the per-cluster mean by the observed cluster rate: it does not include "
                "uncertainty in how often clusters occur, so it is narrower than the full uncertainty",
        "min_independent_clusters": inputs.min_independent_clusters.value,
    }
    capital = {
        "scenario_label": inputs.scenario.label,
        "scenario_status": inputs.scenario.status,
        "total_capital": inputs.scenario.total(),
        **{f"{m.value.lower()}_{k}": getattr(runs[m], k) for m in FillMode
           for k in ("average_deployed", "max_deployed", "capital_days", "idle_capital_average",
                     "return_on_deployed", "return_on_total")},
        "conservative_counts": cons.counts,
        "less_conservative_counts": less.counts,
        "fill_mode_inversion": inversion,
    }
    capacity = capacity_ladder(episodes, inputs.scenario, inputs.sizes or (inputs.primary_size,),
                               window_start_utc=inputs.window_start_utc,
                               window_end_utc=inputs.window_end_utc) if not inputs.scenario.problems() else ()

    verdict, why = _verdict(inputs, net_after_fixed, uncertainty["estimable"] and not mixed, len(clusters), level,
                            inversion, reasons)
    input_labels = {"fixed_cash_costs_annual": fixed, "owner_hours_annual": hours, "owner_hourly_cost": rate,
                    "minimum_useful_annual": inputs.minimum_useful_annual,
                    "min_episodes_for_scenario": min_n,
                    "min_independent_clusters": inputs.min_independent_clusters,
                    **{f"capital:{v}": a for v, a in sorted(inputs.scenario.capital_by_venue.items())},
                    **{f"reserve:{v}": a for v, a in sorted(inputs.scenario.reserve_by_venue.items())}}
    report = ScreenReport(
        ECONOMICS_VERSION, inputs.family, inputs.experiment_id, verdict.value, tuple(why),
        "A screen verdict is a research state. It is not evidence of an edge, and no amount here is an approved "
        "bankroll or an income forecast.",
        inputs.window_start_utc, inputs.window_end_utc, window_days, len(episodes), outside, len(clusters), level,
        inputs.episodes.observations,
        (Decimal(len(episodes)) / len(clusters)).quantize(_Q) if clusters else None,
        variable, fixed, owner_cost, net_after_fixed, capital, uncertainty, capacity, input_labels,
        tuple(inputs.assumptions) + (f"stationarity: {inputs.stationarity_assumption}",
                                     "observed depth is a ceiling, not a guaranteed fill",
                                     "fees are inside net edge per unit and are not subtracted again"),
        tuple(inputs.data_gaps), inputs.scenario.status,
        {m.value.lower(): FILL_MODE_SEMANTICS[m].to_dict() for m in FillMode})
    body = report.to_dict()
    body.pop("report_sha256")
    return replace(report, report_sha256=sha256_hex(canonical_json(body)))


def _verdict(inputs: ScreenInputs, net: Mapping[str, Labeled], estimable: bool, clusters: int, level: str,
             inversion: bool, reasons: list[str]) -> tuple[Verdict, list[str]]:
    """Decided on the cluster-bootstrap band, never on the point estimate alone.

    Preconditions, each otherwise INSUFFICIENT_EVIDENCE:
    - an annual scenario exists;
    - the band is estimable at one consistent cluster level;
    - the protocol's minimum number of independent clusters is supplied and met;
    - the fill modes do not invert.

    Then UNVIABLE: even the less-conservative band's upper bound cannot clear the fixed costs.
    BELOW_MINIMUM_USEFUL: even that upper bound is below the owner's minimum. CONTINUE: the
    conservative band's lower bound reaches the minimum. Anything else is INSUFFICIENT_EVIDENCE.

    Labels v2 (ADR 0037): the less-conservative mode is a HINDSIGHT_UPPER_BOUND, so it is used only to rule
    out (UNVIABLE, BELOW_MINIMUM_USEFUL) and never to support CONTINUE. The conservative mode is
    FIRST_DETECTION_ZERO_LATENCY: not delay-adjusted, so even CONTINUE is a research state, not an
    execution result."""
    reasons = list(reasons)
    cons_lower = net.get("conservative_lower")
    less_upper = net.get("less_conservative_upper")
    points = [net.get("conservative_point"), net.get("less_conservative_point")]
    if any(p is None or p.value is None for p in points):
        return Verdict.INSUFFICIENT_EVIDENCE, reasons or ["annual scenario unavailable"]
    if not estimable:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            f"{clusters} independent cluster(s) at level {level}: no usable uncertainty band, so no verdict beyond "
            "INSUFFICIENT_EVIDENCE is possible"]
    min_clusters = inputs.min_independent_clusters
    if min_clusters.value is None:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            "the protocol's minimum number of independent clusters is UNKNOWN"]
    if clusters < min_clusters.value:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            f"{clusters} independent {level} cluster(s) < the protocol minimum {min_clusters.value}"]
    if inversion or cons_lower.value > less_upper.value:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            f"the fill modes invert (conservative lower {cons_lower.value} vs less-conservative upper "
            f"{less_upper.value}): capital path dependence makes the bounds unreliable"]
    if less_upper.value <= 0:
        return Verdict.ECONOMICALLY_UNVIABLE, reasons + [
            f"even the less-conservative band's upper bound net of fixed cash costs is {less_upper.value} <= 0"]
    minimum = inputs.minimum_useful_annual
    if minimum.value is None:
        return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
            "the minimum useful annual contribution is an OWNER_INPUT that was not supplied"]
    if less_upper.value < minimum.value:
        return Verdict.BELOW_MINIMUM_USEFUL, reasons + [
            f"less-conservative upper bound {less_upper.value} < minimum useful {minimum.value}"]
    if cons_lower.value >= minimum.value:
        return Verdict.CONTINUE, reasons + [
            f"conservative lower bound {cons_lower.value} >= minimum useful {minimum.value}; continue research, "
            "not an edge claim"]
    return Verdict.INSUFFICIENT_EVIDENCE, reasons + [
        f"the band straddles the minimum: conservative lower {cons_lower.value} < minimum {minimum.value} <= "
        f"less-conservative upper {less_upper.value}"]
