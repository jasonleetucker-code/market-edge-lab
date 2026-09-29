"""Game-relative capture planning and the monthly credit proof for The Odds API pilot (ADR 0029).

Pure and deterministic: no I/O, no clock, no network. The caller passes `now`, the discovered
schedule and the quota reading; everything here is arithmetic on those inputs.

Policy (owner correction 3, 2026-09-24):

- **Game-relative, not clock-relative.** Each discovered event gets capture targets at fixed
  offsets before its commence time (default T-24h, T-6h, T-60m). Nothing is captured "because
  it is 09:30". Offsets are configurable; change them only with measured evidence.
- **Coalescing.** The sport odds endpoint returns every event in its commence window for one
  price (`markets x regions` credits), so targets whose times fall within `merge_window` of the
  first target of a group become ONE paid call (a `Slot`). The slot fires at its earliest
  member's time; later members are captured a little early, and the actual capture time is
  recorded, so the deviation stays measurable.
- **Priority when the budget is short:** T-60m (closing line) > T-6h > T-24h. A slot takes the
  priority of its most important member.
- **Budget proof.** For the current UTC month (the quota ledger's month):
  `worst case = spent + reserve + admitted known slots + reserved unknown future calls`, and
  that is at most `min(ceiling, spent + provider remaining)` by construction. Capacity is
  granted class by class, highest priority first, and within a class known slots (earliest
  first) before the reservation for events not yet discovered. What does not fit is
  SKIPPED_BUDGET (known) or reported as unreservable (unknown), never spent.
- **Unknown future weeks** (after the last discovered kickoff, up to the end of the month plus
  the largest offset) use an explicit conservative assumption, `NFL_WORST_CASE`: at most 11
  distinct kickoff groups in any 7-day week, and a per-weekday maximum for a partial week.
  Evidence for the numbers is in ADR 0029. Known slots are always counted exactly.
- **Quota unknown means no paid call.** Without a provider reading this month the proof is
  QUOTA_UNKNOWN and nothing is admitted.
- **The capture quiet window.** A target whose time falls inside 17:40-18:35 America/New_York
  (the EXP-001 capture window) is moved to the end of that window if that is still
  `min_lead` before kickoff, else to five minutes before the window starts.

Sport-aware (ADR 0039, issue #134): each sport has one `SportPolicy` in `SPORT_POLICIES`
(markets, offsets, worst-case assumption, merge window, discovery horizon, rank in the shared
budget). Every sport draws on ONE quota ledger and ONE monthly ceiling. `joint_budget` proves the
month for every enabled sport at once, in rank order: NFL (rank 1) takes all of its classes and
its unknown-week reservation first, and a lower-ranked sport is admitted only from the headroom
left after that; if the higher-ranked sport's own worst case does not fully fit, the lower-ranked
sport gets nothing. `budget` is the one-sport case and is unchanged for NFL.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from .forward import eastern_date, eastern_offset
from .freshness import parse_utc

POLICY_VERSION = "game_relative_v1"
UTC = timezone.utc

# --------------------------------------------------------------------------- configuration


@dataclass(frozen=True)
class Offset:
    label: str  # "T-24h"
    before: timedelta
    priority: int  # 1 = most important (closest to kickoff)


def parse_offsets(text: str) -> tuple[Offset, ...]:
    """'24h,6h,60m' -> offsets; priority 1 goes to the one closest to kickoff."""
    values: list[timedelta] = []
    for raw in text.split(","):
        token = raw.strip().lower()
        if len(token) < 2 or token[-1] not in "hm" or not token[:-1].isdigit():
            raise ValueError(f"offset {raw!r} must look like 24h or 60m")
        amount = int(token[:-1])
        delta = timedelta(hours=amount) if token[-1] == "h" else timedelta(minutes=amount)
        if not timedelta(minutes=15) <= delta <= timedelta(days=7):
            raise ValueError(f"offset {raw!r} must be between 15m and 7 days")
        values.append(delta)
    if not values or len(set(values)) != len(values):
        raise ValueError("give one or more distinct offsets")
    ordered = sorted(values)
    return tuple(Offset(_label(d), d, i + 1) for i, d in enumerate(ordered))


def _label(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"T-{minutes // 60}h" if minutes % 60 == 0 and minutes >= 120 else f"T-{minutes}m"


DEFAULT_OFFSETS = parse_offsets("24h,6h,60m")  # T-60m p1, T-6h p2, T-24h p3


@dataclass(frozen=True)
class WorstCaseAssumption:
    """Distinct kickoff groups for weeks whose schedule is not yet discovered."""

    name: str
    max_groups_per_week: int
    # ET weekday (Monday=0) -> most kickoff groups that day; a partial week sums these.
    max_groups_by_weekday: tuple[int, int, int, int, int, int, int]
    expected_groups_per_week: float


# NFL: TNF, Sun early (London/Germany 09:30), Sun 13:00, Sun 16:05/16:25 (one group after
# coalescing), SNF, MNF (sometimes two), late-season Saturdays (up to 3), Thanksgiving (3),
# Black Friday, Christmas. The heaviest recent week had 10 groups (2024 week 17: Wed 2, Thu 1,
# Sat 3, Sun 3, Mon 1; ADR 0029); 11 leaves margin.
NFL_WORST_CASE = WorstCaseAssumption(
    name="nfl_v2",
    max_groups_per_week=11,
    #                       Mon Tue Wed Thu Fri Sat Sun
    max_groups_by_weekday=(2, 1, 2, 3, 1, 3, 4),
    expected_groups_per_week=6.0,
)

# NHL, derived from the published 2026-27 regular-season schedule (1,344 games), fetched once from
# the public NHL schedule API (keyless; the URL is in ADR 0039, never called by code) on 2026-09-29 (17:29Z), and
# coalesced by THIS planner (20-minute merge window, quiet-window shifts included) for each of
# T-60m, T-6h and T-24h. Measured maxima over every class: 37 groups in any 7 consecutive ET
# dates (T-6h/T-24h, from 2027-04-02; T-60m 34) and, per ET weekday Mon..Sun, (7, 10, 5, 6, 7,
# 9, 8); Tuesday 10 is 2026-10-13's staggered 16-game day. Average 28.0 groups a week (T-6h).
# Margin: +3 a week, +1 a weekday, for reschedules and make-up games. Derivation: ADR 0039 and
# docs/research/NHL_ODDS_BUDGET_2026-10.md.
NHL_WORST_CASE = WorstCaseAssumption(
    name="nhl_2026_27_v1",
    max_groups_per_week=40,
    #                       Mon Tue Wed Thu Fri Sat Sun
    max_groups_by_weekday=(8, 11, 6, 7, 8, 10, 9),
    expected_groups_per_week=28.0,
)


@dataclass(frozen=True)
class PilotConfig:
    offsets: tuple[Offset, ...] = DEFAULT_OFFSETS
    merge_window: timedelta = timedelta(minutes=20)
    early_tolerance: timedelta = timedelta(minutes=7)  # a tick may fire this much before a slot
    late_tolerance: timedelta = timedelta(minutes=30)  # after this a target is MISSED
    min_lead: timedelta = timedelta(minutes=5)  # never capture a "pregame" line closer than this
    ceiling: int = 450
    reserve_credits: int = 3  # one call's worth for a manual smoke read or an ambiguous failure
    assumption: WorstCaseAssumption = NFL_WORST_CASE
    quiet_start_et: time = time(17, 40)
    quiet_end_et: time = time(18, 35)

    def __post_init__(self) -> None:
        if not self.offsets:
            raise ValueError("at least one offset")
        if not 0 < self.ceiling < 500:
            raise ValueError("ceiling must be below the 500-credit free allowance")
        if self.merge_window < timedelta(0) or self.late_tolerance <= timedelta(0):
            raise ValueError("invalid tolerances")


@dataclass(frozen=True)
class SportPolicy:
    """One sport's place in the shared Odds planner (ADR 0039). Everything a sport may differ in
    lives here; the planning rules, the quiet window, the ceiling and the ledger are shared."""

    sport: str  # the provider's sport key
    rank: int  # 1 = first claim on the shared monthly budget
    markets: tuple[str, ...]  # the only markets this sport may request
    regions: tuple[str, ...]
    offsets: tuple[Offset, ...]  # the default (reviewed) offsets
    assumption: WorstCaseAssumption
    merge_window: timedelta
    discovery_horizon: timedelta
    # Scheduled collection runs only while this environment variable is exactly "on" (None: always
    # on). Off makes `odds run` and `odds smoke` for the sport send nothing and write nothing.
    switch_env: str | None = None
    # Runner-state scope in the shared state file: None keeps the historical top-level keys (NFL).
    state_scope: str | None = None
    # Record discovered targets whose deadline had already passed as MISSED with a reason, instead
    # of never writing them (NFL keeps its historical behaviour).
    record_prior_misses: bool = False

    def config(self, offsets: Sequence[Offset] | None = None) -> "PilotConfig":
        return PilotConfig(offsets=tuple(offsets) if offsets is not None else self.offsets,
                           merge_window=self.merge_window, assumption=self.assumption)


NFL = "americanfootball_nfl"
NHL = "icehockey_nhl"
NHL_SWITCH = "EDGE_LAB_ODDS_NHL"
SPORT_POLICIES: dict[str, SportPolicy] = {
    NFL: SportPolicy(sport=NFL, rank=1, markets=("h2h", "spreads", "totals"), regions=("us",),
                     offsets=DEFAULT_OFFSETS, assumption=NFL_WORST_CASE, merge_window=timedelta(minutes=20),
                     discovery_horizon=timedelta(days=35)),
    # NHL v1 (owner direction 2026-09-29, #134): h2h only, region us, T-60m by default; T-6h and T-24h
    # only when the combined proof supports them. Merge window 20 min, as NFL: games at 19:00 and
    # 19:30 ET stay two groups, so a T-60m label never covers a T-90m capture (ADR 0039).
    NHL: SportPolicy(sport=NHL, rank=2, markets=("h2h",), regions=("us",), offsets=parse_offsets("60m"),
                     assumption=NHL_WORST_CASE, merge_window=timedelta(minutes=20),
                     discovery_horizon=timedelta(days=35), switch_env=NHL_SWITCH, state_scope=NHL,
                     record_prior_misses=True),
}


def policy_for(sport: str) -> SportPolicy | None:
    return SPORT_POLICIES.get(sport)


def switch_on(policy: SportPolicy, environ: Mapping[str, str]) -> bool:
    """A sport without a switch is always on; one with a switch is on only when it reads exactly "on"."""
    return policy.switch_env is None or (environ.get(policy.switch_env) or "").strip() == "on"


# --------------------------------------------------------------------------- events and targets


@dataclass(frozen=True)
class ScheduledEvent:
    event_id: str  # the provider's native event id
    sport: str
    commence_utc: datetime
    home_team: str | None = None
    away_team: str | None = None


@dataclass(frozen=True)
class CaptureTarget:
    target_id: str
    sport: str
    event_id: str
    offset_label: str
    priority: int
    commence_utc: datetime
    target_utc: datetime  # the intended (ideal) capture time, persisted as planned
    home_team: str | None = None
    away_team: str | None = None


def iso_z(instant: datetime) -> str:
    if instant.tzinfo is None:
        raise ValueError("naive datetime")
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def target_id(sport: str, event_id: str, offset_label: str, target_utc: datetime) -> str:
    """Includes the target time: a rescheduled game gets new targets; the old ones are superseded."""
    return f"{sport}:{event_id}:{offset_label}:{iso_z(target_utc)}"


def plan_targets(events: Iterable[ScheduledEvent], offsets: Sequence[Offset] = DEFAULT_OFFSETS) -> list[CaptureTarget]:
    out = []
    for ev in events:
        if ev.commence_utc.tzinfo is None:
            raise ValueError(f"event {ev.event_id} has a naive commence time")
        for off in offsets:
            t = (ev.commence_utc - off.before).astimezone(UTC)  # UTC arithmetic: DST cannot shift it
            out.append(CaptureTarget(target_id(ev.sport, ev.event_id, off.label, t), ev.sport, ev.event_id,
                                     off.label, off.priority, ev.commence_utc.astimezone(UTC), t,
                                     ev.home_team, ev.away_team))
    return sorted(out, key=lambda x: (x.target_utc, x.priority, x.event_id))


def _et(instant: datetime) -> datetime:
    return (instant + eastern_offset(instant)).replace(tzinfo=None)


def _from_et(local: datetime) -> datetime:
    """UTC instant of a naive America/New_York wall time (outside the DST gap/overlap hours)."""
    guess = local.replace(tzinfo=UTC) - timedelta(hours=-5)  # as if EST
    return (local.replace(tzinfo=UTC) - eastern_offset(guess)).astimezone(UTC)


def in_quiet_window(instant: datetime, config: PilotConfig = PilotConfig()) -> bool:
    t = _et(instant).time()
    return config.quiet_start_et <= t < config.quiet_end_et


def effective_due(target: CaptureTarget, config: PilotConfig = PilotConfig()) -> datetime:
    """The target time, moved out of the capture quiet window if needed."""
    t = target.target_utc
    if not in_quiet_window(t, config):
        return t
    day = _et(t).date()
    after = _from_et(datetime.combine(day, config.quiet_end_et))
    if after <= target.commence_utc - config.min_lead:
        return after
    return _from_et(datetime.combine(day, config.quiet_start_et)) - timedelta(minutes=5)


def deadline(target: CaptureTarget, config: PilotConfig = PilotConfig()) -> datetime:
    """After this instant an uncaptured target is MISSED."""
    return min(effective_due(target, config) + config.late_tolerance, target.commence_utc - config.min_lead)


def is_expired(target: CaptureTarget, now: datetime, config: PilotConfig = PilotConfig()) -> bool:
    return now > deadline(target, config)


# --------------------------------------------------------------------------- EXP-002 decision horizon
#
# EXP-002 decides at T-6h (with T-24h as a prior input); its labels are the Kalshi T-60m books and settlement.
# Any NFL price captured at T-60m, or received after a game's T-6h decision cutoff, is a proxy for those labels
# (owner directive 2026-09-28 §7D; docs/research/EXP002_FREEZE_PROPOSAL.md §4), so read-only displays withhold it.
# The one rule lives here, beside the `deadline` it uses: Polymarket US (`polymarket_sports`) and The Odds API
# (`odds_consensus`) displays both call it. EXP-002's own measurement and its logged --with-results path do not.
DECISION_OFFSET = "T-6h"
PRE_DECISION_OFFSETS = ("T-24h", "T-6h")  # every other horizon (T-60m, or one this code does not know) is withheld


def decision_cutoff(commence_utc: object, config: PilotConfig = PilotConfig(), *,
                    kickoff_tolerance: timedelta = timedelta(0)) -> datetime | None:
    """EXP-002's T-6h decision cutoff for a game: `deadline` of a T-6h target at its kickoff (under the Odds
    runner's default `PilotConfig`, the one `sports_evidence` uses). `kickoff_tolerance` moves the kickoff
    earlier first, for a source whose kickoff may differ from the Odds event's by up to that much; the deadline
    never decreases with the kickoff, so the result is then never later than the Odds event's own cutoff.
    None when the kickoff is unknown or naive."""
    kick = parse_utc(commence_utc)
    if kick is None:
        return None
    kick -= kickoff_tolerance
    off = next(o for o in DEFAULT_OFFSETS if o.label == DECISION_OFFSET)
    return deadline(CaptureTarget("", "", "", off.label, off.priority, kick, kick - off.before), config)


def after_decision(commence_utc: object, received_utc: object, *,
                   kickoff_tolerance: timedelta = timedelta(0)) -> bool:
    """True when a receipt is after the game's T-6h decision cutoff, or when either time is unknown (fails
    closed)."""
    cutoff, received = decision_cutoff(commence_utc, kickoff_tolerance=kickoff_tolerance), parse_utc(received_utc)
    return cutoff is None or received is None or received > cutoff


def is_label_proxy(offset_label: object, commence_utc: object, received_utc: object, *,
                   kickoff_tolerance: timedelta = timedelta(0)) -> bool:
    """The EXP-002 label-proxy rule for one capture of one game: withheld when its horizon is not a pre-decision
    one (T-60m, or unknown: fails closed) or it was received after the T-6h decision cutoff (`after_decision`).
    A capture with no receipt holds no figure, so the horizon alone decides it."""
    if offset_label not in PRE_DECISION_OFFSETS:
        return True
    if received_utc is None:
        return False
    return after_decision(commence_utc, received_utc, kickoff_tolerance=kickoff_tolerance)


# --------------------------------------------------------------------------- slots


@dataclass(frozen=True)
class Slot:
    slot_id: str
    due_utc: datetime  # the earliest member's effective due time
    priority: int  # the most important member's priority
    members: tuple[CaptureTarget, ...]
    commence_from: datetime
    commence_to: datetime

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(sorted({m.event_id for m in self.members}))

    def fireable(self, now: datetime, config: PilotConfig = PilotConfig()) -> bool:
        return self.due_utc - config.early_tolerance <= now and any(not is_expired(m, now, config) for m in self.members)


def coalesce(targets: Iterable[CaptureTarget], config: PilotConfig = PilotConfig()) -> list[Slot]:
    """Greedy grouping by effective due time: a slot holds every target within `merge_window`
    of its first one. Deterministic for a given set of targets."""
    ordered = sorted(targets, key=lambda t: (effective_due(t, config), t.priority, t.event_id, t.offset_label))
    slots: list[Slot] = []
    group: list[CaptureTarget] = []
    start: datetime | None = None
    for t in ordered:
        due = effective_due(t, config)
        if start is not None and due - start <= config.merge_window:
            group.append(t)
            continue
        if group:
            slots.append(_slot(group, start))  # type: ignore[arg-type]
        group, start = [t], due
    if group:
        slots.append(_slot(group, start))  # type: ignore[arg-type]
    return slots


def _slot(members: list[CaptureTarget], due: datetime) -> Slot:
    commence = [m.commence_utc for m in members]
    return Slot(slot_id=f"{members[0].sport}:{iso_z(due)}", due_utc=due, priority=min(m.priority for m in members),
                members=tuple(members), commence_from=min(commence), commence_to=max(commence))


# --------------------------------------------------------------------------- budget


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    n = now.astimezone(UTC)
    start = datetime(n.year, n.month, 1, tzinfo=UTC)
    end = datetime(n.year + (n.month == 12), n.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


def _et_dates(start: datetime, end: datetime) -> list[date]:
    if end < start:
        return []
    first, last = eastern_date(start), eastern_date(end)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def unknown_groups(start: datetime, end: datetime, assumption: WorstCaseAssumption) -> tuple[int, int, int]:
    """(worst-case groups, expected groups, ET dates) for kickoffs in [start, end] not yet
    discovered. Whole ET dates count, full weeks at the weekly maximum and the remainder at
    the per-weekday maxima (capped at the weekly maximum)."""
    dates = _et_dates(start, end)
    if not dates:
        return 0, 0, 0
    full, rem = divmod(len(dates), 7)
    tail = sum(assumption.max_groups_by_weekday[d.weekday()] for d in dates[full * 7:])
    worst = full * assumption.max_groups_per_week + min(assumption.max_groups_per_week, tail)
    expected = math.ceil(len(dates) * assumption.expected_groups_per_week / 7)
    return worst, min(expected, worst), len(dates)


class BudgetInvariantError(RuntimeError):
    """The proof's own invariant failed: a bug, never a reason to spend. Callers fail closed."""


@dataclass(frozen=True)
class QuotaReading:
    """What the quota ledger knows. `state` is the ledger's QuotaState value."""

    state: str  # READY | QUOTA_UNKNOWN | QUOTA_EXHAUSTED
    local_used: int | None = None
    provider_used: int | None = None
    provider_remaining: int | None = None
    outstanding: int = 0


@dataclass(frozen=True)
class ClassBudget:
    priority: int
    offset_label: str
    known_slots: int
    admitted_slots: int
    skipped_slots: int
    unknown_calls_worst: int
    unknown_calls_reserved: int
    unknown_calls_expected: int


@dataclass(frozen=True)
class BudgetProof:
    month: str
    state: str  # PROVEN | QUOTA_UNKNOWN | QUOTA_EXHAUSTED
    ceiling: int
    cost_per_call: int
    reserve_credits: int
    spent: int | None
    provider_remaining: int | None
    outstanding: int
    headroom: int | None  # credits this plan may still commit this month
    known_horizon_utc: str | None
    unknown_window: tuple[str, str] | None
    unknown_et_dates: int
    assumption: str
    classes: tuple[ClassBudget, ...]
    admitted_slot_ids: tuple[str, ...]
    skipped_slot_ids: tuple[str, ...]
    worst_case_month_credits: int | None
    expected_month_credits: int | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def proven(self) -> bool:
        return self.state == "PROVEN"

    def to_dict(self) -> dict:
        return asdict(self) | {"proven": self.proven}


@dataclass(frozen=True)
class SportDemand:
    """One sport's open slots and assumptions for this month's joint proof."""

    sport: str
    rank: int
    slots: Sequence[Slot]
    cost_per_call: int
    known_horizon: datetime | None  # the latest discovered commence time; None: nothing is known
    config: PilotConfig


@dataclass(frozen=True)
class SportShare:
    """What one sport was granted in the joint proof."""

    sport: str
    rank: int
    cost_per_call: int
    available: int  # credits this sport could still commit when its turn came (the proof's headroom for rank 1)
    classes: tuple[ClassBudget, ...]
    admitted_slot_ids: tuple[str, ...]
    skipped_slot_ids: tuple[str, ...]
    admitted_credits: int
    reserved_unknown_credits: int
    expected_credits: int  # admitted + the expected share of the reserved unknown calls
    known_horizon_utc: str | None
    unknown_window: tuple[str, str] | None
    unknown_et_dates: int
    assumption: str
    fits: bool  # every known slot admitted and every worst-case unknown call reserved
    blocked_by: str | None  # a higher-ranked sport whose own worst case did not fit (this sport got nothing)
    notes: tuple[str, ...]


@dataclass(frozen=True)
class JointBudgetProof:
    """The month's proof for every enabled sport on the one shared ledger and ceiling."""

    month: str
    state: str  # PROVEN | QUOTA_UNKNOWN | QUOTA_EXHAUSTED
    ceiling: int
    reserve_credits: int
    spent: int | None
    provider_remaining: int | None
    outstanding: int
    headroom: int | None
    shares: tuple[SportShare, ...]
    worst_case_month_credits: int | None
    expected_month_credits: int | None
    notes: tuple[str, ...]

    @property
    def proven(self) -> bool:
        return self.state == "PROVEN"

    def share(self, sport: str) -> SportShare:
        for s in self.shares:
            if s.sport == sport:
                return s
        raise KeyError(sport)

    def proof_for(self, sport: str) -> BudgetProof:
        """This sport's view: its own classes and admissions, the JOINT month totals."""
        s = self.share(sport)
        return BudgetProof(month=self.month, state=self.state, ceiling=self.ceiling, cost_per_call=s.cost_per_call,
                           reserve_credits=self.reserve_credits, spent=self.spent,
                           provider_remaining=self.provider_remaining, outstanding=self.outstanding,
                           headroom=None if self.headroom is None else s.available,
                           known_horizon_utc=s.known_horizon_utc, unknown_window=s.unknown_window,
                           unknown_et_dates=s.unknown_et_dates, assumption=s.assumption, classes=s.classes,
                           admitted_slot_ids=s.admitted_slot_ids, skipped_slot_ids=s.skipped_slot_ids,
                           worst_case_month_credits=self.worst_case_month_credits,
                           expected_month_credits=self.expected_month_credits, notes=s.notes + self.notes)

    def to_dict(self) -> dict:
        return asdict(self) | {"proven": self.proven}


def budget(slots: Sequence[Slot], *, now: datetime, quota: QuotaReading, cost_per_call: int,
           known_horizon: datetime | None, config: PilotConfig = PilotConfig()) -> BudgetProof:
    """Admit or skip this month's open slots and prove the month's worst case fits.

    `slots` are the open (unfired, unexpired) slots; only those due before the month ends are
    this month's. `known_horizon` is the latest discovered commence time: after it the
    schedule is unknown and `config.assumption` stands in for it. The one-sport case of
    `joint_budget` (ADR 0039); its output for NFL is pinned byte-for-byte."""
    joint = joint_budget([SportDemand("", 1, slots, cost_per_call, known_horizon, config)], now=now, quota=quota)
    return joint.proof_for("")


def joint_budget(demands: Sequence[SportDemand], *, now: datetime, quota: QuotaReading) -> JointBudgetProof:
    """Admit or skip every enabled sport's slots against ONE ledger and ONE ceiling, and prove the
    month's joint worst case fits.

    Sports are served in rank order. Within a sport, as in ADR 0029: class by class (highest
    priority first), known slots (earliest first) before the reservation for undiscovered events.
    A lower-ranked sport is admitted only from the headroom left after every higher-ranked sport's
    FULL worst case. If a higher-ranked sport skips a known slot or cannot reserve a worst-case
    unknown call, every lower-ranked sport gets zero: it never takes credits the higher-ranked
    sport might need, not even a remainder too small for that sport's call.

    Invariant (checked; `BudgetInvariantError` if broken): worst <= ceiling and
    worst - spent <= provider remaining - outstanding. QUOTA_UNKNOWN admits nothing for any sport."""
    if not demands:
        raise ValueError("at least one sport")
    ordered = sorted(demands, key=lambda d: (d.rank, d.sport))
    if len({d.sport for d in ordered}) != len(ordered) or len({d.rank for d in ordered}) != len(ordered):
        raise ValueError("each sport once, each with its own rank")
    first = ordered[0].config
    if any(d.config.ceiling != first.ceiling or d.config.reserve_credits != first.reserve_credits for d in ordered):
        raise ValueError("every sport shares one ceiling and one reserve")
    ceiling, reserve = first.ceiling, first.reserve_credits
    if any(d.cost_per_call <= 0 for d in ordered):
        raise ValueError("cost_per_call must be positive")
    month_start, month_end = month_bounds(now)
    month = month_start.strftime("%Y-%m")

    def window(d: SportDemand) -> tuple[list[Slot], int, int, int, tuple[str, str] | None, str | None]:
        in_month = [s for s in d.slots if s.due_utc < month_end]
        max_offset = max(o.before for o in d.config.offsets)
        unknown_from = max(now, d.known_horizon) if d.known_horizon is not None else now
        unknown_to = month_end + max_offset
        worst_groups, expected_groups, n_dates = unknown_groups(unknown_from, unknown_to, d.config.assumption)
        win = (iso_z(unknown_from), iso_z(unknown_to)) if n_dates else None
        horizon = iso_z(d.known_horizon) if d.known_horizon is not None else None
        return in_month, worst_groups, expected_groups, n_dates, win, horizon

    shares: list[SportShare] = []
    if quota.state == "QUOTA_UNKNOWN" or quota.provider_used is None or quota.provider_remaining is None:
        for d in ordered:
            in_month, worst_groups, expected_groups, n_dates, win, horizon = window(d)
            classes = tuple(ClassBudget(o.priority, o.label, sum(1 for s in in_month if s.priority == o.priority), 0,
                                        sum(1 for s in in_month if s.priority == o.priority), worst_groups, 0,
                                        expected_groups) for o in sorted(d.config.offsets, key=lambda o: o.priority))
            shares.append(SportShare(d.sport, d.rank, d.cost_per_call, 0, classes, (),
                                     tuple(s.slot_id for s in in_month), 0, 0, 0, horizon, win, n_dates,
                                     d.config.assumption.name, False, None, ()))
        return JointBudgetProof(month=month, state="QUOTA_UNKNOWN", ceiling=ceiling, reserve_credits=reserve,
                                spent=None, provider_remaining=quota.provider_remaining, outstanding=quota.outstanding,
                                headroom=None, shares=tuple(shares), worst_case_month_credits=None,
                                expected_month_credits=None,
                                notes=("no provider quota reading this month: no paid call until a free reconcile",))

    spent = max(quota.local_used or 0, quota.provider_used) + quota.outstanding
    headroom = min(ceiling - spent, quota.provider_remaining - quota.outstanding) - reserve
    remaining = max(headroom, 0)
    blocked_by: str | None = None
    for d in ordered:
        in_month, worst_groups, expected_groups, n_dates, win, horizon = window(d)
        cost = d.cost_per_call
        mine_left = remaining if blocked_by is None else 0
        available = headroom if d is ordered[0] else mine_left
        admitted: list[Slot] = []
        skipped: list[Slot] = []
        classes: list[ClassBudget] = []
        reserved_total = expected_total = 0
        for off in sorted(d.config.offsets, key=lambda o: o.priority):
            mine = sorted((s for s in in_month if s.priority == off.priority), key=lambda s: (s.due_utc, s.slot_id))
            ok = []
            for s in mine:
                if mine_left >= cost:
                    ok.append(s)
                    mine_left -= cost
                else:
                    skipped.append(s)
            admitted += ok
            reserved = min(worst_groups, mine_left // cost)
            mine_left -= reserved * cost
            reserved_total += reserved
            expected_total += min(expected_groups, reserved)
            classes.append(ClassBudget(off.priority, off.label, len(mine), len(ok), len(mine) - len(ok), worst_groups,
                                       reserved, min(expected_groups, reserved)))
        if blocked_by is None:
            remaining = mine_left
        notes = []
        if blocked_by is not None:
            notes.append(f"nothing admitted: the higher-ranked {blocked_by} worst case does not fully fit, so no "
                         "credit is taken from it")
        elif d is not ordered[0]:
            notes.append(f"admitted only from the {available} credit(s) left after every higher-ranked sport's full "
                         "worst case")
        unreservable = sum(c.unknown_calls_worst - c.unknown_calls_reserved for c in classes)
        if unreservable:
            notes.append(f"{unreservable} worst-case future call(s) could not be reserved; if those events "
                         "materialize, their lowest-priority slots will be SKIPPED_BUDGET")
        if skipped:
            notes.append(f"{len(skipped)} known slot(s) SKIPPED_BUDGET (lowest priority, latest first)")
        fits = not unreservable and not skipped
        shares.append(SportShare(d.sport, d.rank, cost, available, tuple(classes), tuple(s.slot_id for s in admitted),
                                 tuple(s.slot_id for s in skipped), len(admitted) * cost, reserved_total * cost,
                                 len(admitted) * cost + expected_total * cost, horizon, win, n_dates,
                                 d.config.assumption.name, fits, blocked_by, tuple(notes)))
        if not fits and blocked_by is None:
            blocked_by = d.sport
    worst = spent + reserve + sum(s.admitted_credits + s.reserved_unknown_credits for s in shares)
    expected = spent + sum(s.expected_credits for s in shares)
    notes = []
    state = "PROVEN"
    if headroom < 0 or quota.state == "QUOTA_EXHAUSTED":
        state = "QUOTA_EXHAUSTED"
        notes.append("no headroom under the ceiling or the provider's remaining quota")
    # The invariant this function exists for. It holds by construction; fail closed if not.
    if state == "PROVEN" and not (worst <= ceiling and worst - spent <= quota.provider_remaining - quota.outstanding):
        raise BudgetInvariantError(f"worst case {worst} breaks the ceiling {ceiling} or the provider "
                                   f"remaining {quota.provider_remaining} (spent {spent})")
    return JointBudgetProof(month=month, state=state, ceiling=ceiling, reserve_credits=reserve, spent=spent,
                            provider_remaining=quota.provider_remaining, outstanding=quota.outstanding,
                            headroom=headroom, shares=tuple(shares), worst_case_month_credits=worst,
                            expected_month_credits=expected, notes=tuple(notes))
