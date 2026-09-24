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
  the largest offset) use an explicit conservative assumption, `NFL_WORST_CASE`: at most 10
  distinct kickoff groups in any 7-day week, and a per-weekday maximum for a partial week.
  Evidence for the numbers is in ADR 0029. Known slots are always counted exactly.
- **Quota unknown means no paid call.** Without a provider reading this month the proof is
  QUOTA_UNKNOWN and nothing is admitted.
- **The capture quiet window.** A target whose time falls inside 17:40-18:35 America/New_York
  (the EXP-001 capture window) is moved to the end of that window if that is still
  `min_lead` before kickoff, else to five minutes before the window starts.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Sequence

from .forward import eastern_date, eastern_offset

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
# Black Friday, Christmas. The heaviest recent weeks had 9 groups (ADR 0029); 10 leaves margin.
NFL_WORST_CASE = WorstCaseAssumption(
    name="nfl_v1",
    max_groups_per_week=10,
    #                       Mon Tue Wed Thu Fri Sat Sun
    max_groups_by_weekday=(2, 1, 2, 3, 1, 3, 4),
    expected_groups_per_week=6.0,
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


def budget(slots: Sequence[Slot], *, now: datetime, quota: QuotaReading, cost_per_call: int,
           known_horizon: datetime | None, config: PilotConfig = PilotConfig()) -> BudgetProof:
    """Admit or skip this month's open slots and prove the month's worst case fits.

    `slots` are the open (unfired, unexpired) slots; only those due before the month ends are
    this month's. `known_horizon` is the latest discovered commence time: after it the
    schedule is unknown and `config.assumption` stands in for it."""
    if cost_per_call <= 0:
        raise ValueError("cost_per_call must be positive")
    month_start, month_end = month_bounds(now)
    month = month_start.strftime("%Y-%m")
    in_month = [s for s in slots if s.due_utc < month_end]
    max_offset = max(o.before for o in config.offsets)
    unknown_from = max(now, known_horizon) if known_horizon is not None else now
    unknown_to = month_end + max_offset
    worst_groups, expected_groups, n_dates = unknown_groups(unknown_from, unknown_to, config.assumption)
    window = (iso_z(unknown_from), iso_z(unknown_to)) if n_dates else None
    horizon = iso_z(known_horizon) if known_horizon is not None else None
    common = dict(month=month, ceiling=config.ceiling, cost_per_call=cost_per_call,
                  reserve_credits=config.reserve_credits, outstanding=quota.outstanding,
                  known_horizon_utc=horizon, unknown_window=window, unknown_et_dates=n_dates,
                  assumption=config.assumption.name)

    if quota.state == "QUOTA_UNKNOWN" or quota.provider_used is None or quota.provider_remaining is None:
        classes = tuple(ClassBudget(o.priority, o.label, sum(1 for s in in_month if s.priority == o.priority), 0,
                                    sum(1 for s in in_month if s.priority == o.priority), worst_groups, 0,
                                    expected_groups) for o in sorted(config.offsets, key=lambda o: o.priority))
        return BudgetProof(state="QUOTA_UNKNOWN", spent=None, provider_remaining=quota.provider_remaining,
                           headroom=None, classes=classes, admitted_slot_ids=(),
                           skipped_slot_ids=tuple(s.slot_id for s in in_month), worst_case_month_credits=None,
                           expected_month_credits=None,
                           notes=("no provider quota reading this month: no paid call until a free reconcile",),
                           **common)

    spent = max(quota.local_used or 0, quota.provider_used) + quota.outstanding
    headroom = min(config.ceiling - spent, quota.provider_remaining - quota.outstanding) - config.reserve_credits
    remaining = max(headroom, 0)
    admitted: list[Slot] = []
    skipped: list[Slot] = []
    classes: list[ClassBudget] = []
    reserved_unknown_total = 0
    expected_unknown_total = 0
    for off in sorted(config.offsets, key=lambda o: o.priority):
        mine = sorted((s for s in in_month if s.priority == off.priority), key=lambda s: (s.due_utc, s.slot_id))
        ok = []
        for s in mine:
            if remaining >= cost_per_call:
                ok.append(s)
                remaining -= cost_per_call
            else:
                skipped.append(s)
        admitted += ok
        reserved = min(worst_groups, remaining // cost_per_call)
        remaining -= reserved * cost_per_call
        reserved_unknown_total += reserved
        expected_unknown_total += min(expected_groups, reserved)
        classes.append(ClassBudget(off.priority, off.label, len(mine), len(ok), len(mine) - len(ok), worst_groups,
                                   reserved, min(expected_groups, reserved)))
    admitted_credits = len(admitted) * cost_per_call
    worst = spent + config.reserve_credits + admitted_credits + reserved_unknown_total * cost_per_call
    expected = spent + admitted_credits + expected_unknown_total * cost_per_call
    notes = []
    unreservable = sum(c.unknown_calls_worst - c.unknown_calls_reserved for c in classes)
    if unreservable:
        notes.append(f"{unreservable} worst-case future call(s) could not be reserved; if those events "
                     "materialize, their lowest-priority slots will be SKIPPED_BUDGET")
    if skipped:
        notes.append(f"{len(skipped)} known slot(s) SKIPPED_BUDGET (lowest priority, latest first)")
    state = "PROVEN"
    if headroom < 0 or quota.state == "QUOTA_EXHAUSTED":
        state = "QUOTA_EXHAUSTED"
        notes.append("no headroom under the ceiling or the provider's remaining quota")
    # The invariant this function exists for. It holds by construction; fail loudly if not.
    if state == "PROVEN":
        assert worst <= config.ceiling and worst - spent <= quota.provider_remaining - quota.outstanding, (worst, spent)
    return BudgetProof(state=state, spent=spent, provider_remaining=quota.provider_remaining, headroom=headroom,
                       classes=tuple(classes), admitted_slot_ids=tuple(s.slot_id for s in admitted),
                       skipped_slot_ids=tuple(s.slot_id for s in skipped), worst_case_month_credits=worst,
                       expected_month_credits=expected, notes=tuple(notes), **common)
