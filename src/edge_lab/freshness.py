"""Freshness semantics for point-in-time data.

Rules (see docs/DATA_PROVENANCE.md):

- Freshness is judged against an explicit maximum age, never assumed.
- A missing or unparseable timestamp is UNKNOWN, not FRESH.
- Combining inputs yields the worst state: one stale input makes the whole
  derived value stale.
- Anything that could feed an opportunity or trading decision must call
  `require_fresh`, which fails closed on STALE and UNKNOWN.

Freshness Fabric v1 (issue #74, ADR 0031) extends this module with the shared vocabulary for
"what is fresh, what is due next, and why": `AcquisitionMode`, `ScheduleState`,
`SourceHealth`, the frozen records `SourcePolicy` and `SourceFreshness`, the read-only
`FabricContext`, and the provider protocol `Provider` (`provider(context, now) ->
list[SourceFreshness]`). `edge_lab.freshness_fabric` holds the provider registry, the
providers for the existing schedules and the supervisor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


# Higher is worse. UNKNOWN ranks worst because we cannot rule out staleness.
_SEVERITY = {Freshness.FRESH: 0, Freshness.STALE: 1, Freshness.UNKNOWN: 2}


class StaleDataError(RuntimeError):
    """Raised when decision-grade code receives data that is not provably fresh."""


def parse_utc(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive or unparseable values return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str):
        return None
    else:
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        # A timestamp without a zone is ambiguous; refuse to guess.
        return None
    return parsed.astimezone(timezone.utc)


def assess(
    observed_at: str | datetime | None,
    *,
    max_age: timedelta,
    now: datetime,
) -> Freshness:
    """Classify one observation timestamp against `max_age` at time `now`.

    A timestamp in the future beyond a small clock-skew tolerance is UNKNOWN:
    it indicates a clock or parsing problem, not exceptionally fresh data.
    """
    ts = parse_utc(observed_at)
    now_utc = parse_utc(now)
    if ts is None or now_utc is None:
        return Freshness.UNKNOWN
    age = now_utc - ts
    if age < -timedelta(minutes=5):
        return Freshness.UNKNOWN
    return Freshness.FRESH if age <= max_age else Freshness.STALE


def combine(*states: Freshness) -> Freshness:
    """Worst-of combination. No inputs is UNKNOWN, never FRESH."""
    if not states:
        return Freshness.UNKNOWN
    return max(states, key=lambda state: _SEVERITY[state])


def require_fresh(state: Freshness, *, what: str) -> None:
    """Fail closed unless `state` is FRESH."""
    if state is not Freshness.FRESH:
        raise StaleDataError(f"{what} is {state.value}; decision-grade use requires fresh data")


# =========================================================================== Freshness Fabric v1
#
# Everything above this line is unchanged and keeps its behaviour for every existing caller.
#
# Rules:
# - Unknown stays unknown: a time, age or count that is not known is None, never 0 or "now".
# - A record never claims FRESH without a receipt time, and never claims decision-grade use
#   unless it is FRESH and healthy. `require_fresh` at the point of use still decides; these
#   flags are the fabric's fail-closed summary, not a replacement for it.
# - In v1 every existing schedule is observed as EXTERNAL_SCHEDULE. A provider reports; it never
#   runs, triggers, skips or reschedules anything.


class AcquisitionMode(str, Enum):
    """How data from a source is acquired."""

    STREAM = "STREAM"  # a push connection delivers updates
    POLL = "POLL"  # fetched on a fixed cadence
    EVENT_RELATIVE = "EVENT_RELATIVE"  # fetched at offsets from an event (kickoff, close, decision)
    RELEASE_DRIVEN = "RELEASE_DRIVEN"  # fetched after an upstream publication (forecast, report)
    MANUAL = "MANUAL"  # only an operator runs it
    EXTERNAL_SCHEDULE = "EXTERNAL_SCHEDULE"  # its own scheduler (a systemd timer) runs it; the fabric observes


class ScheduleState(str, Enum):
    """Where a source's schedule stands at one instant."""

    DUE = "DUE"  # a run should happen now
    NOT_DUE = "NOT_DUE"  # nothing to do until `next_due`
    MISSED = "MISSED"  # an intended run passed its deadline without a success
    PAUSED = "PAUSED"  # deliberately not running (setup needed, key rejected, disabled)
    BUDGET_BLOCKED = "BUDGET_BLOCKED"  # a cost block or budget proof stops it
    QUOTA_BLOCKED = "QUOTA_BLOCKED"  # the provider quota is exhausted or unknown
    PROTECTED_WINDOW = "PROTECTED_WINDOW"  # its scheduler defers while a protected window is open
    LOCK_BUSY = "LOCK_BUSY"  # its last run found the shared lock held and did nothing
    UNKNOWN = "UNKNOWN"  # the evidence needed to say is missing or unreadable


class SourceHealth(str, Enum):
    """How the source's recent acquisitions went (independent of how old the data is)."""

    OK = "OK"
    DEGRADED = "DEGRADED"  # partial results, or a problem that does not stop acquisition
    FAILING = "FAILING"  # the latest attempt failed
    UNKNOWN = "UNKNOWN"  # no attempt on record, or the record is unreadable


_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")


def _positive(name: str, value: timedelta | None) -> None:
    if value is not None and (not isinstance(value, timedelta) or value <= timedelta(0)):
        raise ValueError(f"{name} must be a positive timedelta or None, not {value!r}")


def _aware(name: str, value: datetime | None) -> None:
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
        raise ValueError(f"{name} must be a timezone-aware datetime or None, not {value!r}")


def iso_z(value: datetime | None) -> str | None:
    """UTC ISO-8601 with a Z suffix; None stays None."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _seconds(value: timedelta | None) -> float | None:
    return None if value is None else round(value.total_seconds(), 3)


@dataclass(frozen=True)
class SourcePolicy:
    """The static contract of one source: identity, freshness objective and controls.

    Cadences are intervals. `min_safe_cadence` is the slowest safe cadence, as the LONGEST
    interval between acquisitions that still meets the objective; `max_useful_cadence` is the
    fastest useful cadence, as the SHORTEST interval worth running (faster adds cost or load, not
    information). None means not defined, never zero. `max_useful_age` comes from
    `edge_lab.sources.REGISTRY` wherever the source has a registered max_age (one owner per fact).
    """

    source_id: str
    domain: str
    mode: AcquisitionMode
    description: str
    policy_version: str
    schedule_owner: str  # who runs it, e.g. "systemd edgelab-pfm.timer + edge_lab.forward.gate"
    underlying_mode: AcquisitionMode | None = None  # the acquisition style behind an external schedule
    max_useful_age: timedelta | None = None
    min_safe_cadence: timedelta | None = None
    max_useful_cadence: timedelta | None = None
    pacing: str | None = None
    budget: str | None = None  # budget or quota, in words (the numbers live with their owner)
    protected_windows: tuple[str, ...] = ()
    retry: str | None = None  # retries and backoff, in words

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not _SOURCE_ID.match(self.source_id):
            raise ValueError(f"source_id must match {_SOURCE_ID.pattern}: {self.source_id!r}")
        if not isinstance(self.mode, AcquisitionMode):
            raise ValueError(f"mode must be an AcquisitionMode, not {self.mode!r}")
        if self.underlying_mode is not None and not isinstance(self.underlying_mode, AcquisitionMode):
            raise ValueError(f"underlying_mode must be an AcquisitionMode or None, not {self.underlying_mode!r}")
        for name in ("domain", "description", "policy_version", "schedule_owner"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        _positive("max_useful_age", self.max_useful_age)
        _positive("min_safe_cadence", self.min_safe_cadence)
        _positive("max_useful_cadence", self.max_useful_cadence)
        if (self.min_safe_cadence is not None and self.max_useful_cadence is not None
                and self.max_useful_cadence > self.min_safe_cadence):
            raise ValueError("max_useful_cadence (the shortest useful interval) exceeds min_safe_cadence "
                             "(the longest safe interval)")
        if not isinstance(self.protected_windows, tuple):
            raise ValueError("protected_windows must be a tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id, "domain": self.domain, "mode": self.mode.value,
            "underlying_mode": self.underlying_mode.value if self.underlying_mode else None,
            "description": self.description, "policy_version": self.policy_version,
            "schedule_owner": self.schedule_owner,
            "max_useful_age_s": _seconds(self.max_useful_age), "min_safe_cadence_s": _seconds(self.min_safe_cadence),
            "max_useful_cadence_s": _seconds(self.max_useful_cadence), "pacing": self.pacing, "budget": self.budget,
            "protected_windows": list(self.protected_windows), "retry": self.retry,
        }


def policy_freshness(policy: SourcePolicy, receipt: datetime | None, now: datetime) -> Freshness:
    """The canonical rule (`assess`) against the policy's objective. No objective is UNKNOWN."""
    if policy.max_useful_age is None:
        return Freshness.UNKNOWN
    return assess(receipt, max_age=policy.max_useful_age, now=now)


@dataclass(frozen=True)
class SourceFreshness:
    """One source at one instant (`as_of`). Built by a provider; read by the supervisor and the UI.

    Times: `intended_at` is when the current or next run is meant to happen; `next_due` is when
    the schedule next becomes due (None when unknown or nothing is planned); `last_attempt` is the
    latest attempt of any outcome; `last_success_receipt` the receipt time of the latest successful
    acquisition; `receipt_ts` / `upstream_ts` describe the data held now (our receipt time and the
    source's own timestamp). Ages derive from `as_of`, so they can never disagree with it.
    `disagreements` lists every point where the fabric's view and the canonical scheduler's view
    of the same inputs differ: reported, never silently resolved. `details` holds small,
    JSON-safe, non-secret extras for display.
    """

    policy: SourcePolicy
    as_of: datetime
    freshness: Freshness
    schedule_state: ScheduleState
    health: SourceHealth
    why_due: str
    intended_at: datetime | None = None
    next_due: datetime | None = None
    last_attempt: datetime | None = None
    last_success_receipt: datetime | None = None
    upstream_ts: datetime | None = None
    receipt_ts: datetime | None = None
    missed_count: int | None = None
    recent_misses: tuple[str, ...] = ()
    usable_for_research: bool = False
    usable_for_decision: bool = False
    disagreements: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, SourcePolicy):
            raise ValueError("policy must be a SourcePolicy")
        if not isinstance(self.freshness, Freshness):
            raise ValueError(f"freshness must be a Freshness, not {self.freshness!r}")
        if not isinstance(self.schedule_state, ScheduleState):
            raise ValueError(f"schedule_state must be a ScheduleState, not {self.schedule_state!r}")
        if not isinstance(self.health, SourceHealth):
            raise ValueError(f"health must be a SourceHealth, not {self.health!r}")
        if self.as_of is None:
            raise ValueError("as_of is required")
        for name in ("as_of", "intended_at", "next_due", "last_attempt", "last_success_receipt", "upstream_ts",
                     "receipt_ts"):
            _aware(name, getattr(self, name))
        if self.missed_count is not None and (
                isinstance(self.missed_count, bool) or not isinstance(self.missed_count, int) or self.missed_count < 0):
            raise ValueError("missed_count must be a non-negative int or None")
        for name in ("recent_misses", "disagreements", "notes"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple")
        if not isinstance(self.why_due, str) or not self.why_due.strip():
            raise ValueError("why_due is required: say why the schedule stands where it does")
        # Fail closed: FRESH needs a receipt time; decision-grade use needs FRESH data and OK health.
        if self.freshness is Freshness.FRESH and self.receipt_ts is None:
            raise ValueError("a record without receipt_ts cannot be FRESH")
        if self.usable_for_decision and (self.freshness is not Freshness.FRESH or self.health is not SourceHealth.OK):
            raise ValueError("usable_for_decision requires FRESH data and OK health")

    @property
    def source_id(self) -> str:
        return self.policy.source_id

    @property
    def data_age(self) -> timedelta | None:
        return None if self.receipt_ts is None else self.as_of - self.receipt_ts

    @property
    def upstream_age(self) -> timedelta | None:
        return None if self.upstream_ts is None else self.as_of - self.upstream_ts

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe. Enums by name, times as UTC ISO-8601 with Z, ages in seconds; None stays null."""
        return {
            "source_id": self.source_id, "domain": self.policy.domain, "mode": self.policy.mode.value,
            "underlying_mode": self.policy.underlying_mode.value if self.policy.underlying_mode else None,
            "policy_version": self.policy.policy_version, "schedule_owner": self.policy.schedule_owner,
            "as_of_utc": iso_z(self.as_of), "freshness": self.freshness.name,
            "schedule_state": self.schedule_state.value, "health": self.health.value, "why_due": self.why_due,
            "intended_at_utc": iso_z(self.intended_at), "next_due_utc": iso_z(self.next_due),
            "last_attempt_utc": iso_z(self.last_attempt), "last_success_receipt_utc": iso_z(self.last_success_receipt),
            "upstream_ts_utc": iso_z(self.upstream_ts), "receipt_ts_utc": iso_z(self.receipt_ts),
            "data_age_s": _seconds(self.data_age), "upstream_age_s": _seconds(self.upstream_age),
            "max_useful_age_s": _seconds(self.policy.max_useful_age),
            "missed_count": self.missed_count, "recent_misses": list(self.recent_misses),
            "usable_for_research": self.usable_for_research, "usable_for_decision": self.usable_for_decision,
            "disagreements": list(self.disagreements), "notes": list(self.notes), "details": dict(self.details),
        }


@dataclass(frozen=True)
class FabricContext:
    """Read-only inputs a provider may consult. None means not configured here (unknown); a
    provider then reports UNKNOWN rather than guessing. Providers open stores read-only and never
    create, migrate, lock or write anything, and never use the network."""

    db: Path | None = None  # the evidence store (SnapshotStore), opened with mode=ro
    ledger: Path | None = None  # the shadow ledger, opened with mode=ro
    odds_ledger: Path | None = None  # The Odds API quota ledger JSON, read without its lock
    odds_pilot_state: Path | None = None  # its runner state; default `<odds_ledger>.pilot.json`
    status_dir: Path | None = None  # non-sensitive status artifacts (latest.json, shadow_daily*.json)
    backups_dir: Path | None = None  # verified backup bundles (one manifest.json per bundle)

    @property
    def odds_state_path(self) -> Path | None:
        if self.odds_pilot_state is not None:
            return self.odds_pilot_state
        if self.odds_ledger is None:
            return None
        return self.odds_ledger.with_name(self.odds_ledger.name + ".pilot.json")


# The provider protocol: `provider(context, now) -> list[SourceFreshness]`, one record per declared
# policy. Deterministic for fixed inputs, read-only, no network.
Provider = Callable[[FabricContext, datetime], "list[SourceFreshness]"]


@dataclass(frozen=True)
class FabricProvider:
    """A registry entry: the provider plus the policies it reports on. Declared policies let the
    supervisor report every declared source even when the provider fails or omits one."""

    name: str
    policies: tuple[SourcePolicy, ...]
    provide: Provider

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _SOURCE_ID.match(self.name):
            raise ValueError(f"provider name must match {_SOURCE_ID.pattern}: {self.name!r}")
        if (not isinstance(self.policies, tuple) or not self.policies
                or not all(isinstance(p, SourcePolicy) for p in self.policies)):
            raise ValueError("a provider declares a non-empty tuple of SourcePolicy")
        ids = [p.source_id for p in self.policies]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate source ids in provider {self.name}: {ids}")
        if not callable(self.provide):
            raise ValueError("provide must be callable")
