"""Freshness Fabric v1: the provider registry, read-only providers for the existing schedules, and
the supervisor that writes one bounded status artifact (issue #74, ADR 0031).

The types live in `edge_lab.freshness` (the canonical owner). This module answers "what data
sources are fresh now, what is due next, and why?" without controlling anything:

- Every existing schedule is observed as EXTERNAL_SCHEDULE. A provider reads stored evidence,
  status files and the canonical scheduler functions (`forward.gate`, `odds_pilot.dashboard_status`,
  `odds_schedule.effective_due`/`deadline`, `price_observations.close_tick_alignment` /
  `protected_refusal`, `daily.pending_event_tickers`), all read-only. It never makes a network
  call, takes a lock, writes a store, or triggers a run.
- Where the fabric's view and a canonical function could disagree (a timer tick outside the
  window the code accepts, the next due time, a close tick that cannot reach its target), the
  record carries a `disagreements` entry. Nothing is silently picked.
- The supervisor (`edge-lab freshness status [--write]`) evaluates every registered provider in
  isolation. A provider that raises is reported (its declared sources become UNKNOWN); it never
  stops the others. With `--write` it replaces `<status-dir>/freshness.json` atomically
  (schema `freshness-fabric-status/1`, current state only, bounded in size, no secrets).
  Exit status is non-zero only for a genuine crash or bad arguments: a STALE or MISSED source is
  data in the artifact, not a failure.

Adding a provider (a later lane): define its `SourcePolicy` tuple and a `provide(context, now)`
function, then add ONE `FabricProvider(...)` line to `REGISTRY`. Nothing else changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import forward, odds_api, odds_pilot, odds_schedule, polymarket_sports
from . import price_observations as po
from .freshness import (
    AcquisitionMode,
    FabricContext,
    FabricProvider,
    Freshness,
    ScheduleState,
    SourceFreshness,
    SourceHealth,
    SourcePolicy,
    assess,
    iso_z,
    parse_utc,
    policy_freshness,
    usable_flags,
)
from .sources import get_source
from .storage import ODDS_TARGET_FINAL_STATES, ReadOnlyStoreError, SnapshotStore

UTC = timezone.utc
SCHEMA = "freshness-fabric-status/1"
ARTIFACT_NAME = "freshness.json"
FABRIC_VERSION = "freshness-fabric-v1"
ODDS_LEDGER_FILE = "odds_quota_ledger.json"  # beside the evidence database (edgelab-odds.service)

# Bounds: the artifact is small, current-state only, and never grows with history.
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_TEXT = 300
MAX_ITEMS = 10
MAX_DETAIL_KEYS = 24
MAX_SOURCES = 64
MAX_JSON_READ_BYTES = 1024 * 1024  # status files the fabric reads (latest.json, a manifest, ...)
HISTORY_TAIL_BYTES = 256 * 1024  # how much of shadow_daily_history.jsonl is read (newest runs)

EXTERNAL = AcquisitionMode.EXTERNAL_SCHEDULE
DAY = timedelta(days=1)

# --------------------------------------------------------------------------- timer contracts
# The fabric's copy of each systemd timer's schedule. tests/test_freshness_fabric.py pins every
# value to its unit file, so a timer change without a fabric change fails CI.

FORWARD_TIMERS = {"pfm": "edgelab-pfm.timer", "decision": "edgelab-decision.timer",
                  "recheck": "edgelab-recheck.timer", "status": "edgelab-status.timer"}
FORWARD_TICKS_ET = {"pfm": dtime(17, 45, 0), "decision": dtime(17, 55, 5), "recheck": dtime(18, 5, 0),
                    "status": dtime(18, 30, 0)}
STATUS_GRACE = timedelta(minutes=10)  # edgelab-status.service TimeoutStartSec=5min, plus slack
SETTLEMENT_TICKS_ET = (dtime(11, 15, 0), dtime(16, 15, 0))  # edgelab-settlement.timer
SHADOW_TICK_ET = dtime(18, 40, 0)  # edgelab-shadow.timer
DAILY_RUN_GRACE = timedelta(minutes=15)  # both units: TimeoutStartSec=10min, plus slack
BACKUP_TICK_UTC = dtime(4, 40, 0)  # edgelab-backup.timer
BACKUP_GRACE = timedelta(minutes=25)  # TimeoutStartSec=20min, plus slack
OBSERVE_TICK_MINUTES = (5, 20, 35, 50)  # edgelab-observe.timer, America/New_York (whole-hour offsets)
ODDS_TICK_MINUTES = (0, 15, 30, 45)  # edgelab-odds.timer
SUPERVISOR_TIMER = "edgelab-freshness.timer"
SUPERVISOR_TICK_MINUTES = tuple(range(1, 60, 5))  # edgelab-freshness.timer: *:01/5
SUPERVISOR_MAX_AGE = timedelta(minutes=15)  # three missed ticks
# The close capture runs from the 04:57:45 UTC tick to its confirming read 5 s after the 05:00:00Z close.
# A supervisor run that could overlap its normal course (TimeoutStartSec 120 s) defers like a protected window.
# A slow close run may last to its 4-minute limit (05:01:45Z) past the guard's end; that overlap is harmless,
# because the supervisor only reads (mode=ro; WAL readers never block the writer).
CLOSE_GUARD = ("kalshi_close_tick", timedelta(minutes=2, seconds=15), timedelta(minutes=3, seconds=15))


def close_guard_at(now: datetime) -> tuple[str, datetime, datetime] | None:
    """(name, start, end) when `now` is inside [close tick - 2 min 15 s, close tick + 3 min 15 s)."""
    for day in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1)):
        tick = datetime.combine(day, po.CLOSE_TICK_UTC, UTC)
        start, end = tick - CLOSE_GUARD[1], tick + CLOSE_GUARD[2]
        if start <= now < end:
            return CLOSE_GUARD[0], start, end
    return None

# Early discovery of a schedule problem is the point: only the next few targets are checked.
MAX_TARGETS_CHECKED = 50

# Daily shadow runs that did their bookkeeping (edge_lab.daily EXIT states with exit code 0 that did
# work). Everything else (LOCK_BUSY, NO_CAPTURE, NOT_CLOSED, INVALID_CAPTURE, FAILED, ...) is never a
# receipt, so it can never make the source fresh or usable.
SHADOW_SUCCESS_STATES = ("HEALTHY_TRADED", "HEALTHY_NO_SIGNAL", "PENDING_SETTLEMENT")

# `missed_count` semantics, one per kind of schedule (reported in each record's details):
MISSED_SCOPE_TICK = "the latest fixed timer tick only: 1 if it passed its grace without a recorded run, else 0"
MISSED_SCOPE_DAYS = "closed target days in the last 7 (since the first capture) without a complete capture"
MISSED_SCOPE_TARGETS = "targets recorded MISSED by the canonical scheduler (all stored targets)"


# --------------------------------------------------------------------------- small helpers


def _t(value: Any) -> datetime | None:
    return parse_utc(value)


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    s = str(text)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _et_to_utc(day: date, wall: dtime) -> datetime:
    """UTC instant of an America/New_York wall time (outside the 01:00-03:00 DST change hours)."""
    local = datetime.combine(day, wall).replace(tzinfo=UTC)
    return local - forward.eastern_offset(local + timedelta(hours=5))


def _daily_ticks(now: datetime, walls: Iterable[dtime], *, eastern: bool) -> tuple[datetime, datetime]:
    """(the latest tick at or before `now`, the first tick after it) of daily wall-clock ticks."""
    today = forward.eastern_date(now) if eastern else now.astimezone(UTC).date()
    ticks = sorted((_et_to_utc(today + timedelta(days=k), w) if eastern
                    else datetime.combine(today + timedelta(days=k), w, UTC))
                   for k in (-2, -1, 0, 1, 2) for w in walls)
    last = max(t for t in ticks if t <= now)
    nxt = min(t for t in ticks if t > now)
    return last, nxt


def _next_grid_tick(after: datetime, minutes: Sequence[int]) -> datetime:
    """The first whole-minute tick at or after `after` whose minute is in `minutes`."""
    base = after.astimezone(UTC).replace(second=0, microsecond=0)
    if base < after:
        base += timedelta(minutes=1)
    for i in range(0, 61):
        tick = base + timedelta(minutes=i)
        if tick.minute in minutes:
            return tick
    raise ValueError(f"no tick in {minutes}")


def _open_store(ctx: FabricContext) -> tuple[SnapshotStore | None, str | None]:
    """The evidence store opened read-only, or (None, why). Never creates or migrates it."""
    if ctx.db is None:
        return None, "evidence store not configured"
    if not ctx.db.is_file():
        return None, "evidence store does not exist"
    try:
        return SnapshotStore.open_readonly(ctx.db), None
    except (ReadOnlyStoreError, sqlite3.Error, OSError) as exc:
        return None, f"evidence store unreadable ({type(exc).__name__})"


def _read_json(path: Path | None) -> tuple[str, Any]:
    """(MISSING | NOT_CONFIGURED | TOO_LARGE | CORRUPT | OK, data). Read-only, bounded."""
    if path is None:
        return "NOT_CONFIGURED", None
    try:
        if path.stat().st_size > MAX_JSON_READ_BYTES:
            return "TOO_LARGE", None
        return "OK", json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "MISSING", None
    except (OSError, ValueError, UnicodeDecodeError):
        return "CORRUPT", None


def _tick_state(now: datetime, last_tick: datetime, next_tick: datetime, ran_at: datetime | None,
                grace: timedelta, what: str) -> tuple[ScheduleState, datetime, str]:
    """Schedule state of a fixed daily tick from the time of its latest recorded run."""
    if ran_at is not None and ran_at >= last_tick - timedelta(minutes=1):
        return (ScheduleState.NOT_DUE, next_tick,
                f"{what} ran at {iso_z(ran_at)} for the {iso_z(last_tick)} tick; next tick {iso_z(next_tick)}")
    if now < last_tick + grace:
        return (ScheduleState.DUE, last_tick,
                f"the {iso_z(last_tick)} tick of {what} is running or has not reported yet "
                f"(grace {int(grace.total_seconds() // 60)} min)")
    return (ScheduleState.MISSED, next_tick,
            f"no {what} run recorded for the {iso_z(last_tick)} tick (last run "
            f"{iso_z(ran_at) if ran_at else 'unknown'}); next tick {iso_z(next_tick)}")


def unknown_record(policy: SourcePolicy, now: datetime, why: str, **extra: Any) -> SourceFreshness:
    """A record that says only that nothing can be said, and why."""
    return SourceFreshness(policy=policy, as_of=now, freshness=Freshness.UNKNOWN,
                           schedule_state=ScheduleState.UNKNOWN, health=SourceHealth.UNKNOWN,
                           why_due=_clip(why), **extra)


# =========================================================================== policies

_PFM_MAX_AGE = get_source("nws_pfm_okx").max_age["pfm_product"]
_BOOK_MAX_AGE = get_source("kalshi_public").max_age["orderbook"]
_SETTLEMENT_MAX_AGE = get_source("kalshi_settlement").max_age["event_settlement_markets"]
_ODDS_MAX_AGE = get_source(odds_api.SOURCE_ID).max_age["odds"]
_DISCOVERY_MAX_AGE = get_source("the_odds_api_discovery").max_age["events"]
_PROTECTED = tuple(f"{name} {a:%H:%M}-{b:%H:%M} America/New_York" for name, a, b in po.PROTECTED_WINDOWS_ET)
_ODDS = odds_pilot.RunnerSettings()
_ODDS_CFG = _ODDS.config
_ODDS_QUIET = f"capture quiet window {_ODDS_CFG.quiet_start_et:%H:%M}-{_ODDS_CFG.quiet_end_et:%H:%M} America/New_York"
_FWD_VERSION = "exp001-forward-adr0012"


def _forward_policy(phase: str, underlying: AcquisitionMode, max_age: timedelta, what: str, retry: str) -> SourcePolicy:
    return SourcePolicy(
        source_id=f"exp001.forward.{phase}", domain="weather", mode=EXTERNAL, underlying_mode=underlying,
        description=what, policy_version=_FWD_VERSION,
        schedule_owner=f"systemd {FORWARD_TIMERS[phase]} {FORWARD_TICKS_ET[phase]:%H:%M:%S} America/New_York"
                       + (" + edge_lab.forward.gate" if phase != "status" else " + edge_lab.forward.summary"),
        max_useful_age=max_age, min_safe_cadence=DAY, max_useful_cadence=DAY,
        pacing="one capture per target day; shared collector lock and per-host pacers" if phase != "status" else None,
        retry=retry)


POLICY_PFM = _forward_policy(
    "pfm", AcquisitionMode.RELEASE_DRIVEN, _PFM_MAX_AGE,
    "PFMOKX forecast products captured before the EXP-001 cutoff (ADR 0012); objective: the registered "
    "pfm_product max_age",
    "none: window [cutoff, decision - 6 min); a missed window is lost, never fired late")
POLICY_DECISION = _forward_policy(
    "decision", AcquisitionMode.EVENT_RELATIVE, _BOOK_MAX_AGE,
    "KXHIGHNY event, markets and one book per open bracket inside [decision - 5 min, decision]; objective: "
    "the registered Kalshi orderbook max_age (a captured book is current only for minutes)",
    "none: a missed window is lost, never fired late")
POLICY_RECHECK = _forward_policy(
    "recheck", AcquisitionMode.EVENT_RELATIVE, _BOOK_MAX_AGE,
    "every bracket's book again 10-15 min after its decision book; objective: the registered Kalshi "
    "orderbook max_age",
    "none: a missed window is lost, never fired late")
POLICY_FORWARD_STATUS = _forward_policy(
    "status", AcquisitionMode.POLL, DAY + timedelta(minutes=30),
    "latest.json: Stage-B day validity from stored evidence (derived, no network); objective: one daily "
    "run plus 30 min",
    "daily; the next run re-derives everything")
FORWARD_POLICIES = (POLICY_PFM, POLICY_DECISION, POLICY_RECHECK, POLICY_FORWARD_STATUS)

POLICY_ODDS = SourcePolicy(
    source_id="the_odds_api.nfl_odds", domain="sports", mode=EXTERNAL, underlying_mode=AcquisitionMode.EVENT_RELATIVE,
    description="The Odds API NFL offered odds at T-24h / T-6h / T-60m before kickoff (ADR 0029). Offered odds "
                "are research data, never executable prices; objective: the registered odds max_age",
    policy_version=odds_schedule.POLICY_VERSION,
    schedule_owner="systemd edgelab-odds.timer every 15 min + edge_lab.odds_pilot.run_tick",
    max_useful_age=_ODDS_MAX_AGE,
    pacing="at most one paid odds call per due slot; at most three GETs per tick",
    budget=f"{_ODDS_CFG.ceiling}-credit monthly ceiling under a worst-case budget proof; "
           f"{_ODDS_CFG.reserve_credits} credits reserved",
    protected_windows=(_ODDS_QUIET,),
    retry="a failed paid call is never retried; an expired target becomes MISSED")
POLICY_ODDS_DISCOVERY = SourcePolicy(
    source_id="the_odds_api.discovery", domain="sports", mode=EXTERNAL, underlying_mode=AcquisitionMode.POLL,
    description="The Odds API quota-free NFL schedule discovery (events endpoint); objective: the registered "
                "discovery max_age",
    policy_version=odds_schedule.POLICY_VERSION,
    schedule_owner="systemd edgelab-odds.timer every 15 min + edge_lab.odds_pilot.run_tick",
    max_useful_age=_DISCOVERY_MAX_AGE, min_safe_cadence=_ODDS.discovery_max_age,
    max_useful_cadence=_ODDS.discovery_interval,
    pacing=f"at most every {int(_ODDS.discovery_interval.total_seconds() // 3600)} h, paced on the last attempt",
    budget="quota-free", protected_windows=(_ODDS_QUIET,),
    retry=f"a failed or rejected discovery is retried after {int(_ODDS.discovery_interval.total_seconds() // 3600)} h")
ODDS_POLICIES = (POLICY_ODDS, POLICY_ODDS_DISCOVERY)

_OBS_PACING = (f"at most {po.MAX_TARGETS} targets, {po.MAX_REQUESTS} GETs and {int(po.MAX_RUN.total_seconds() // 60)} "
               "min per run; shared Kalshi pacer and collector lock")
POLICY_OBSERVE = SourcePolicy(
    source_id="price_observations.later", domain="prices", mode=EXTERNAL, underlying_mode=AcquisitionMode.EVENT_RELATIVE,
    description="ADR 0030 later price observations (post-decision, pre-close, settlement-preceding, custom; "
                "decision/recheck are backfilled); objective: the registered Kalshi orderbook max_age",
    policy_version=po.POLICY_VERSION,
    schedule_owner="systemd edgelab-observe.timer :05/:20/:35/:50 America/New_York + edge_lab.price_observations",
    max_useful_age=_BOOK_MAX_AGE, pacing=_OBS_PACING, protected_windows=_PROTECTED,
    retry="a FAILED target is retried by a later tick until its deadline, then MISSED")
POLICY_OBSERVE_CLOSE = SourcePolicy(
    source_id="price_observations.close", domain="prices", mode=EXTERNAL, underlying_mode=AcquisitionMode.EVENT_RELATIVE,
    description="ADR 0030 close-window observations (Kalshi only; CLOSE only with proof); objective: the "
                "registered Kalshi orderbook max_age",
    policy_version=po.POLICY_VERSION,
    schedule_owner=f"systemd edgelab-observe-close.timer {po.CLOSE_TICK_UTC:%H:%M:%S} UTC + edge_lab.price_observations",
    max_useful_age=_BOOK_MAX_AGE, pacing=_OBS_PACING,
    retry="one close tick a day; a missed close is lost")
OBSERVATION_POLICIES = (POLICY_OBSERVE, POLICY_OBSERVE_CLOSE)

POLICY_SETTLEMENT = SourcePolicy(
    source_id="kalshi_settlement.refresh", domain="settlement", mode=EXTERNAL,
    underlying_mode=AcquisitionMode.RELEASE_DRIVEN,
    description="Targeted settlement-evidence refresh for open positions that are due, then shadow bookkeeping; "
                "objective: the registered event_settlement_markets max_age",
    policy_version="shadow-daily-adr0016",
    schedule_owner="systemd edgelab-settlement.timer 11:15 and 16:15 America/New_York + edge_lab.daily.run",
    max_useful_age=_SETTLEMENT_MAX_AGE,
    pacing="at most 10 events, shared Kalshi pacer, 120 s deadline; no request when nothing is due",
    retry="twice a day; pending positions stay pending until conclusive evidence arrives")
POLICY_SHADOW = SourcePolicy(
    source_id="exp001.shadow_daily", domain="shadow", mode=EXTERNAL, underlying_mode=AcquisitionMode.POLL,
    description="Daily EXP-001 shadow bookkeeping from stored evidence (network-free); objective: one daily "
                "run plus 1 h",
    policy_version="shadow-daily-adr0016",
    schedule_owner=f"systemd edgelab-shadow.timer {SHADOW_TICK_ET:%H:%M} America/New_York + edge_lab.daily.run",
    max_useful_age=DAY + timedelta(hours=1), min_safe_cadence=DAY, max_useful_cadence=DAY,
    retry="idempotent catch-up: the next run does what a missed one would have")
SETTLEMENT_POLICIES = (POLICY_SETTLEMENT, POLICY_SHADOW)


def _backup_policy(kind: str) -> SourcePolicy:
    return SourcePolicy(
        source_id=f"backup.{kind}", domain="operations", mode=EXTERNAL, underlying_mode=AcquisitionMode.POLL,
        description=f"Verified SQLite backup bundle of the {'evidence database' if kind == 'evidence' else 'shadow ledger'}"
                    "; objective: one daily bundle plus 2 h",
        policy_version="backup-adr0012",
        schedule_owner=f"systemd edgelab-backup.timer {BACKUP_TICK_UTC:%H:%M} UTC + edge_lab.backup create",
        max_useful_age=DAY + timedelta(hours=2), min_safe_cadence=DAY, max_useful_cadence=DAY,
        retry="daily; never deleted automatically")


POLICY_BACKUP_EVIDENCE = _backup_policy("evidence")
POLICY_BACKUP_LEDGER = _backup_policy("ledger")
BACKUP_POLICIES = (POLICY_BACKUP_EVIDENCE, POLICY_BACKUP_LEDGER)

POLICY_SUPERVISOR = SourcePolicy(
    source_id="freshness_fabric.supervisor", domain="operations", mode=EXTERNAL, underlying_mode=AcquisitionMode.POLL,
    description="This supervisor's own previous status artifact (freshness.json); objective: three missed ticks",
    policy_version=FABRIC_VERSION,
    schedule_owner=f"systemd {SUPERVISOR_TIMER} every 5 min (*:01/5) + edge_lab.freshness_fabric",
    max_useful_age=SUPERVISOR_MAX_AGE, min_safe_cadence=SUPERVISOR_MAX_AGE, max_useful_cadence=timedelta(minutes=5),
    pacing="local reads only; network-free (AF_UNIX)", protected_windows=_PROTECTED,
    retry="none needed: the next tick re-evaluates everything")
SUPERVISOR_POLICIES = (POLICY_SUPERVISOR,)


# =========================================================================== forward weather (EXP-001)


def forward_tick(phase: str, target: date) -> datetime:
    """The UTC instant the phase's timer fires for target date D (on D-1, America/New_York)."""
    return _et_to_utc(target - DAY, FORWARD_TICKS_ET[phase])


class _HidePhase:
    """A read-only view for the canonical gate that hides one phase's own captures, so the gate
    answers "would the timer tick be admitted?" regardless of whether the phase already ran."""

    def __init__(self, store: SnapshotStore | None, hidden: str) -> None:
        self.store, self.hidden = store, hidden

    def forward_captures(self, *, target_date: str | None = None, phase: str | None = None, mode: str = "live"):
        if self.store is None or phase == self.hidden:
            return []
        rows = self.store.forward_captures(target_date=target_date, phase=phase, mode=mode)
        return [r for r in rows if r["phase"] != self.hidden]


def forward_tick_disagreement(phase: str, store: SnapshotStore | None, target: date) -> str | None:
    """None when `forward.gate` admits the phase's timer tick for D; else the disagreement.
    A recheck tick cannot be judged before D's decision capture exists (not a disagreement)."""
    tick = forward_tick(phase, target)
    g = forward.gate(phase, _HidePhase(store, phase), tick)
    if g.status is None or g.status == "rejected_no_decision_capture":
        return None
    return (f"{FORWARD_TIMERS[phase]} fires at {iso_z(tick)} for {target.isoformat()}, but forward.gate answers "
            f"{g.status} ({'; '.join(g.reasons)})")


def _phase_window_open(phase: str, g: forward.Gate, now: datetime) -> bool:
    """Whether the phase's window for D still lies ahead of `now` (the gate refused only for being early)."""
    if phase == "decision":
        return now < g.window[0] - forward.EARLY_WAIT_MAX
    if phase == "recheck" and g.decision is not None:
        books = json.loads(g.decision["links_json"]).get("books") or {}
        first = min((_t(b.get("fetched_at_utc")) for b in books.values() if _t(b.get("fetched_at_utc"))), default=None)
        return first is not None and now < first
    return now < g.window[0]


def _forward_capture_record(policy: SourcePolicy, phase: str, store: SnapshotStore | None, problem: str | None,
                            now: datetime) -> SourceFreshness:
    target = forward.target_for(now)
    tick_d, tick_next = forward_tick(phase, target), forward_tick(phase, target + DAY)
    upcoming_tick = tick_d if tick_d > now else tick_next
    if store is None:
        return unknown_record(policy, now, f"{problem}; the timer's next tick is {iso_z(upcoming_tick)}",
                              intended_at=upcoming_tick, next_due=upcoming_tick,
                              details={"timer": FORWARD_TIMERS[phase], "target_date": target.isoformat()})
    rows = store.forward_captures(phase=phase)
    complete = [r for r in rows if r["status"] == "complete"]
    outcomes = [r for r in rows if r["status"] in ("complete", "partial", "failed")]
    done_today = any(r["target_date"] == target.isoformat() for r in complete)
    g = forward.gate(phase, store, now)
    window = {"start_utc": iso_z(g.window[0]), "end_utc": iso_z(g.window[1])}

    if g.status is None and now < tick_d:
        # The gate would admit a run, but nothing runs it before its timer fires.
        state, next_due, intended = ScheduleState.NOT_DUE, tick_d, tick_d
        why = (f"gate open for {target.isoformat()} [{window['start_utc']}, {window['end_utc']}); "
               f"the timer fires at {iso_z(tick_d)}")
    elif g.status is None:
        state, next_due, intended = ScheduleState.DUE, tick_d, tick_d
        why = (f"inside the canonical {phase} window for {target.isoformat()} "
               f"[{window['start_utc']}, {window['end_utc']}), after the {iso_z(tick_d)} timer tick, and no "
               "complete capture yet")
    elif g.status == "skipped_duplicate" or done_today:
        state, next_due, intended = ScheduleState.NOT_DUE, tick_next, tick_next
        why = f"complete {phase} capture for {target.isoformat()}; next at the {iso_z(tick_next)} tick"
    elif g.status == "rejected_no_decision_capture":
        decision_end = forward.windows(target)["decision"] + forward.RECHECK_MAX
        if now < decision_end:
            state, next_due, intended = ScheduleState.NOT_DUE, tick_d, tick_d
            why = f"waits for the {target.isoformat()} decision capture; recheck tick {iso_z(tick_d)}"
        else:
            state, next_due, intended = ScheduleState.MISSED, tick_next, tick_next
            why = f"no complete decision capture for {target.isoformat()}, so no recheck was possible"
    elif _phase_window_open(phase, g, now):
        state, next_due, intended = ScheduleState.NOT_DUE, tick_d, tick_d
        why = f"the {phase} window for {target.isoformat()} opens {window['start_utc']}; timer tick {iso_z(tick_d)}"
    else:
        state, next_due, intended = ScheduleState.MISSED, tick_next, tick_next
        why = (f"the {phase} window for {target.isoformat()} closed {window['end_utc']} without a complete "
               f"capture; next at the {iso_z(tick_next)} tick")

    # Misses: closed target days (the last 7) with no complete capture, since the first capture of any phase.
    first = min((date.fromisoformat(r["target_date"]) for r in store.forward_captures()), default=None)
    closed = [target - timedelta(days=k) for k in range(7, 0, -1)] + ([target] if state is ScheduleState.MISSED else [])
    have = {r["target_date"] for r in complete}
    misses = [d for d in closed if first is not None and d >= first and d.isoformat() not in have]
    recent = []
    for d in misses[-5:]:
        tried = [r for r in rows if r["target_date"] == d.isoformat()]
        last_reason = json.loads(tried[-1]["reasons_json"])[:1] if tried else ["no attempt recorded"]
        recent.append(_clip(f"{d.isoformat()}: {tried[-1]['status'] if tried else 'no attempt'}"
                            f"{': ' + last_reason[0] if last_reason else ''}", 160))

    receipt = _t(complete[-1]["completed_at_utc"]) if complete else None
    freshness = policy_freshness(policy, receipt, now)
    last = outcomes[-1]["status"] if outcomes else None
    health = {"complete": SourceHealth.OK, "partial": SourceHealth.DEGRADED, "failed": SourceHealth.FAILING,
              None: SourceHealth.UNKNOWN}[last]
    disagreement = forward_tick_disagreement(phase, store, target)
    research, decision = usable_flags(freshness, health, receipt)
    return SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
        intended_at=intended, next_due=next_due, last_attempt=_t(rows[-1]["started_at_utc"]) if rows else None,
        last_success_receipt=receipt, receipt_ts=receipt, missed_count=len(misses), recent_misses=tuple(recent),
        usable_for_research=research, usable_for_decision=decision,
        disagreements=(disagreement,) if disagreement else (),
        notes=("the day's validity (VALID/INVALID) is exp001.forward.status; a complete capture is not a valid day",),
        details={"timer": FORWARD_TIMERS[phase], "timer_tick_utc": iso_z(tick_d), "target_date": target.isoformat(),
                 "canonical_window": window, "gate_status": g.status or "PROCEED",
                 "last_complete_target_date": complete[-1]["target_date"] if complete else None,
                 "missed_scope": MISSED_SCOPE_DAYS})


def _forward_status_record(ctx: FabricContext, now: datetime) -> SourceFreshness:
    policy = POLICY_FORWARD_STATUS
    last_tick, next_tick = _daily_ticks(now, (FORWARD_TICKS_ET["status"],), eastern=True)
    if ctx.status_dir is None:
        return unknown_record(policy, now, f"status directory not configured; next tick {iso_z(next_tick)}",
                              next_due=next_tick, intended_at=next_tick)
    state_file, data = _read_json(ctx.status_dir / "latest.json")
    generated = _t(data.get("generated_at_utc")) if isinstance(data, dict) else None
    state, next_due, why = _tick_state(now, last_tick, next_tick, generated, STATUS_GRACE, "forward status")
    if state_file != "OK" or generated is None:
        health = SourceHealth.UNKNOWN if state_file == "MISSING" else SourceHealth.DEGRADED
        why = f"latest.json {state_file.lower() if state_file != 'OK' else 'has no generated_at_utc'}; " + why
        valid = None
    else:
        valid = data.get("last_closed_status")
        health = SourceHealth.OK if valid == "VALID" else SourceHealth.DEGRADED
    # latest.json is written only by a completed status run, so its time is a receipt even when the
    # day it describes is INVALID (that is data: health DEGRADED, never decision-grade).
    freshness = policy_freshness(policy, generated, now)
    research, decision = usable_flags(freshness, health, generated)
    notes = tuple(_clip(r, 160) for r in (data.get("last_closed_reasons") or [])[:3]) if isinstance(data, dict) else ()
    return SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
        intended_at=next_due, next_due=next_due, last_attempt=generated, last_success_receipt=generated,
        receipt_ts=generated, missed_count=1 if state is ScheduleState.MISSED else 0 if generated else None,
        usable_for_research=research, usable_for_decision=decision, notes=notes,
        details={"missed_scope": MISSED_SCOPE_TICK, "file": state_file, "last_closed_target_date": data.get("last_closed_target_date") if isinstance(data, dict) else None,
                 "last_closed_status": valid, "valid_days": data.get("valid_days") if isinstance(data, dict) else None})


def forward_weather(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """EXP-001 forward weather: pfm 17:45, decision 17:55:05, recheck 18:05, status 18:30 ET."""
    store, problem = _open_store(ctx)
    return [
        _forward_capture_record(POLICY_PFM, "pfm", store, problem, now),
        _forward_capture_record(POLICY_DECISION, "decision", store, problem, now),
        _forward_capture_record(POLICY_RECHECK, "recheck", store, problem, now),
        _forward_status_record(ctx, now),
    ]


# =========================================================================== The Odds API pilot

_ODDS_STATE_MAP = {  # dashboard state -> (schedule state or None for timing-based, health)
    "ERROR": (ScheduleState.UNKNOWN, SourceHealth.UNKNOWN),
    "COST_BLOCKED": (ScheduleState.BUDGET_BLOCKED, SourceHealth.DEGRADED),
    "KEY_REJECTED": (ScheduleState.PAUSED, SourceHealth.FAILING),
    "SETUP_NEEDED": (ScheduleState.PAUSED, SourceHealth.UNKNOWN),
    "QUOTA_EXHAUSTED": (ScheduleState.QUOTA_BLOCKED, SourceHealth.OK),
    "QUOTA_UNKNOWN": (ScheduleState.QUOTA_BLOCKED, SourceHealth.DEGRADED),
    "DISCOVERY_STALE": (ScheduleState.PAUSED, SourceHealth.DEGRADED),
    "DISCOVERY_FAILED": (None, SourceHealth.DEGRADED),
    "DEGRADED": (None, SourceHealth.DEGRADED),
    "ACTIVE": (None, SourceHealth.OK),
}


def odds_open_targets(store: SnapshotStore | None, now: datetime,
                      settings: odds_pilot.RunnerSettings = _ODDS) -> list[tuple[datetime, datetime, Any]]:
    """(effective due, deadline, row) of every open target, by the canonical odds_schedule functions."""
    if store is None:
        return []
    cfg = settings.config
    out = []
    for row in store.odds_targets(sport=settings.sport):
        if row["state"] in ODDS_TARGET_FINAL_STATES:
            continue
        target = odds_pilot._target(row)
        out.append((odds_schedule.effective_due(target, cfg), odds_schedule.deadline(target, cfg), row))
    return sorted(out, key=lambda x: (x[0], x[2]["priority"], x[2]["event_id"]))


def odds_tick_can_fire(due: datetime, deadline: datetime, now: datetime,
                       cfg: odds_schedule.PilotConfig = _ODDS_CFG) -> datetime | None:
    """The first edgelab-odds.timer tick at which the runner would fire a slot due at `due`
    (from due - early_tolerance, not after the deadline, outside the quiet window), or None."""
    tick = _next_grid_tick(max(now, due - cfg.early_tolerance), ODDS_TICK_MINUTES)
    while tick <= deadline:
        if not odds_schedule.in_quiet_window(tick, cfg):
            return tick
        tick = _next_grid_tick(tick + timedelta(minutes=1), ODDS_TICK_MINUTES)
    return None


def _odds_records(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    if ctx.odds_ledger is None or ctx.db is None:
        why = "The Odds API quota ledger or evidence store not configured"
        return [unknown_record(POLICY_ODDS, now, why), unknown_record(POLICY_ODDS_DISCOVERY, now, why)]
    ds = odds_pilot.dashboard_status(ctx.db, ctx.odds_ledger, ctx.odds_state_path, now=now, settings=_ODDS)
    store, problem = _open_store(ctx)
    cfg = _ODDS_CFG
    quiet = odds_schedule.in_quiet_window(now, cfg)
    dstate = ds.get("state")
    mapped, health = _ODDS_STATE_MAP.get(dstate, (ScheduleState.UNKNOWN, SourceHealth.UNKNOWN))

    # ---- paid odds captures
    targets = odds_open_targets(store, now) if store is not None else []
    upcoming = [(due, dl, row) for due, dl, row in targets if dl > now]
    overdue = [row for due, dl, row in targets if dl <= now]
    ours = upcoming[0][0] if upcoming else None
    canonical = _t((ds.get("next_capture") or {}).get("due_utc"))
    disagreements: list[str] = []
    if iso_z(ours) != iso_z(canonical):
        disagreements.append(f"next capture: fabric {iso_z(ours)} vs odds_pilot.dashboard_status {iso_z(canonical)}")
    for due, dl, row in upcoming[:MAX_TARGETS_CHECKED]:
        if odds_tick_can_fire(due, dl, now, cfg) is None:
            disagreements.append(_clip(f"{row['target_id']}: no edgelab-odds.timer tick outside the quiet window "
                                       f"between {iso_z(due - cfg.early_tolerance)} and its deadline {iso_z(dl)}"))
    if mapped is not None:
        state = mapped
        why = f"odds pilot {dstate}: {ds.get('detail')}"
    elif quiet:
        state, why = ScheduleState.PROTECTED_WINDOW, f"inside the {_ODDS_QUIET}: ticks do nothing"
    elif canonical is not None and canonical - cfg.early_tolerance <= now:
        state, why = ScheduleState.DUE, f"the capture slot due {iso_z(canonical)} is fireable now"
    elif overdue:
        state, why = ScheduleState.MISSED, f"{len(overdue)} open target(s) passed their deadline (the next tick marks them MISSED)"
    elif canonical is not None:
        state, why = ScheduleState.NOT_DUE, f"next capture slot due {iso_z(canonical)}"
    else:
        state, why = ScheduleState.NOT_DUE, "no open capture target; targets come from the next discovery"
    rows = store.odds_targets(sport=_ODDS.sport) if store is not None else []
    missed_rows = sorted((r for r in rows if r["state"] == "MISSED"), key=lambda r: r["state_at_utc"] or "")
    attempted = [_t(r["state_at_utc"]) for r in rows if r["state"] in ("CAPTURED", "FAILED")]
    latest = ds.get("latest_successful_capture") or {}
    receipt = _t(latest.get("received_at_utc"))
    freshness = policy_freshness(POLICY_ODDS, receipt, now)
    if latest.get("freshness") and latest["freshness"] != freshness.value:
        disagreements.append(f"capture freshness: fabric {freshness.value} vs dashboard_status {latest['freshness']}")
    quota = ds.get("quota") or {}
    next_capture = ds.get("next_capture") or {}
    odds_record = SourceFreshness(
        policy=POLICY_ODDS, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
        intended_at=_t(next_capture.get("due_utc")), next_due=canonical,
        last_attempt=max((a for a in attempted if a), default=None), last_success_receipt=receipt, receipt_ts=receipt,
        missed_count=((ds.get("targets") or {}).get("by_state") or {}).get("MISSED", 0) if store is not None else None,
        recent_misses=tuple(_clip(f"{r['target_id']}: {r['reason']}", 200) for r in missed_rows[-5:]),
        usable_for_research=usable_flags(freshness, health, receipt)[0],
        usable_for_decision=False,  # offered odds are a research benchmark, never an executable price
        disagreements=tuple(disagreements),
        notes=(ds.get("label") or odds_pilot.RESEARCH_LABEL, "the systemd timer state is not observable here")
              + ((f"evidence store: {problem}",) if problem else ()),
        details={"pilot_state": dstate, "quota_state": quota.get("state"), "quota_used_local": quota.get("used_local"),
                 "quota_provider_remaining": quota.get("provider_remaining"), "quota_ceiling": quota.get("ceiling"),
                 "quota_outstanding": quota.get("outstanding"),
                 "cost_blocked": None if dstate == "ERROR" else bool(ds.get("cost_block")),
                 "next_offset": next_capture.get("offset"), "next_event_id": next_capture.get("event_id"),
                 "open_targets": len(upcoming), "overdue_targets": len(overdue),
                 "targets_by_state": (ds.get("targets") or {}).get("by_state"),
                 "live_read_verified": ds.get("live_read_verified"), "missed_scope": MISSED_SCOPE_TARGETS})

    # ---- quota-free discovery
    disc = ds.get("discovery") or {}
    last_ok, last_try_at = _t(disc.get("last_success_utc")), _t(disc.get("last_attempt_utc"))
    last_try = max((t for t in (last_ok, last_try_at) if t is not None), default=None)
    next_disc = last_try + _ODDS.discovery_interval if last_try is not None else None
    outcome = disc.get("outcome")
    if dstate == "ERROR":
        dstate_s, dwhy = ScheduleState.UNKNOWN, f"odds pilot ERROR: {ds.get('detail')}"
    elif outcome in ("SETUP_NEEDED", "KEY_REJECTED") or (dstate in ("SETUP_NEEDED", "KEY_REJECTED") and last_try is None):
        dstate_s, dwhy = ScheduleState.PAUSED, f"discovery paused: {outcome or dstate}"
    elif quiet:
        dstate_s, dwhy = ScheduleState.PROTECTED_WINDOW, f"inside the {_ODDS_QUIET}: ticks do nothing"
    elif next_disc is None or next_disc <= now:
        dstate_s, dwhy = ScheduleState.DUE, (f"last discovery attempt {iso_z(last_try)} is at least "
                                             f"{int(_ODDS.discovery_interval.total_seconds() // 3600)} h old"
                                             if last_try else "no discovery on record")
    else:
        dstate_s, dwhy = ScheduleState.NOT_DUE, f"next discovery after {iso_z(next_disc)} (paced on the last attempt)"
    dhealth = {"OK": SourceHealth.OK, "FAILED": SourceHealth.FAILING, "KEY_REJECTED": SourceHealth.FAILING}.get(
        outcome, SourceHealth.UNKNOWN)
    dfresh = policy_freshness(POLICY_ODDS_DISCOVERY, last_ok, now)
    discovery_record = SourceFreshness(
        policy=POLICY_ODDS_DISCOVERY, as_of=now, freshness=dfresh, schedule_state=dstate_s, health=dhealth,
        why_due=_clip(dwhy), intended_at=next_disc, next_due=next_disc if dstate_s is not ScheduleState.PAUSED else None,
        last_attempt=last_try_at or last_ok, last_success_receipt=last_ok, receipt_ts=last_ok,
        usable_for_research=usable_flags(dfresh, dhealth, last_ok)[0],
        usable_for_decision=usable_flags(dfresh, dhealth, last_ok)[1],
        details={"events": disc.get("events"), "fresh_for_planning": disc.get("fresh"), "outcome": outcome})
    return [odds_record, discovery_record]


def odds_api_pilot(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """The Odds API NFL pilot (ADR 0029), from `odds_pilot.dashboard_status` and the stored targets."""
    return _odds_records(ctx, now)


# =========================================================================== ADR 0030 price observations

# Only an executable CAPTURED book is a successful receipt. NOT_EXECUTABLE rows are evidence, but
# not a usable price, so they never make the source fresh.
_CAPTURED_STATES = ("CAPTURED",)


def observe_tick_for(due_from: datetime, deadline: datetime, now: datetime) -> datetime | None:
    """The first edgelab-observe.timer tick in [max(now, due_from), deadline] that
    `price_observations.protected_refusal` lets start, or None."""
    tick = _next_grid_tick(max(now, due_from), OBSERVE_TICK_MINUTES)
    while tick <= deadline:
        if po.protected_refusal(tick) is None:
            return tick
        tick = _next_grid_tick(tick + timedelta(minutes=1), OBSERVE_TICK_MINUTES)
    return None


def observation_next_due(targets: Sequence[Mapping[str, Any]], now: datetime, *, close: bool | None = None) -> list[Mapping[str, Any]]:
    """Open targets whose deadline has not passed, by due time: the same rule as
    `price_observations.status` next_due. `close` selects the close phase (True), the others
    (False) or all (None)."""
    out = []
    for t in targets:
        if close is not None and (t["phase"] == "close") != close:
            continue
        state = t["state"] or "PLANNED"
        deadline = _t(t["deadline_utc"])
        if state in ("PLANNED", "FAILED") and deadline is not None and deadline >= now:
            out.append(t)
    return sorted(out, key=lambda t: t["due_from_utc"])


def _observation_record(policy: SourcePolicy, targets: Sequence[Mapping[str, Any]], all_targets: Sequence[Mapping[str, Any]],
                        now: datetime, *, close: bool) -> SourceFreshness:
    upcoming = observation_next_due(targets, now, close=close)
    overdue = [t for t in targets if (t["state"] or "PLANNED") in ("PLANNED", "FAILED")
               and _t(t["deadline_utc"]) is not None and _t(t["deadline_utc"]) < now]
    missed = sorted((t for t in targets if t["state"] == "MISSED"), key=lambda t: t["state_at_utc"] or "")
    captured = [_t(t["state_at_utc"]) for t in targets
                if t["state"] in _CAPTURED_STATES and t["phase"] not in po.BACKFILL_PHASES]
    attempted = sorted((t for t in targets if t["state"] is not None and t["phase"] not in po.BACKFILL_PHASES),
                       key=lambda t: t["state_at_utc"] or "")
    receipt = max((c for c in captured if c), default=None)
    disagreements: list[str] = []
    next_tick = None
    if close:
        alignment = po.close_tick_alignment(all_targets, now)
        disagreements += [_clip(f"{m['target_id']}: the {po.CLOSE_TICK_UTC:%H:%M:%S} UTC close tick cannot reach its "
                                f"window [{m['due_from_utc']}, {m['deadline_utc']}]")
                          for m in alignment["misaligned"]]
        due_now = [t for t in upcoming if _t(t["due_from_utc"]) <= now]
        protected = None
    else:
        alignment = None
        for t in upcoming[:MAX_TARGETS_CHECKED]:
            tick = observe_tick_for(_t(t["due_from_utc"]), _t(t["deadline_utc"]), now)
            if next_tick is None:
                next_tick = tick
            if tick is None:
                disagreements.append(_clip(f"{t['target_id']}: no edgelab-observe.timer tick outside the protected "
                                           f"windows in [{t['due_from_utc']}, {t['deadline_utc']}]"))
        due_now = [t for t in upcoming if _t(t["due_from_utc"]) <= now]
        protected = po.protected_refusal(now)
    nxt = upcoming[0] if upcoming else None
    if protected is not None:
        state, why = ScheduleState.PROTECTED_WINDOW, protected["detail"]
    elif due_now:
        state, why = ScheduleState.DUE, f"{len(due_now)} target(s) inside their due window now"
    elif overdue:
        state, why = ScheduleState.MISSED, f"{len(overdue)} open target(s) passed their deadline (the next run marks them MISSED)"
    elif nxt is not None:
        state, why = ScheduleState.NOT_DUE, f"next target {nxt['target_id']} due from {nxt['due_from_utc']}"
    else:
        state, why = ScheduleState.NOT_DUE, "no open target (targets are planned after each recorded decision)"
    last = attempted[-1]["state"] if attempted else None
    health = (SourceHealth.UNKNOWN if last is None else SourceHealth.DEGRADED if last in ("FAILED", "MISSED")
              else SourceHealth.OK)
    by_state: dict[str, int] = {}
    for t in targets:
        by_state[t["state"] or "PLANNED"] = by_state.get(t["state"] or "PLANNED", 0) + 1
    freshness = policy_freshness(policy, receipt, now)
    details: dict[str, Any] = {"targets": len(targets), "by_state": dict(sorted(by_state.items())),
                               "overdue": len(overdue), "missed_scope": MISSED_SCOPE_TARGETS}
    if close:
        details["close_tick_alignment"] = alignment["state"] if alignment else None
    else:
        details["next_tick_utc"] = iso_z(next_tick)
    return SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
        intended_at=_t(nxt["target_utc"]) if nxt else None, next_due=_t(nxt["due_from_utc"]) if nxt else None,
        last_attempt=_t(attempted[-1]["state_at_utc"]) if attempted else None, last_success_receipt=receipt,
        receipt_ts=receipt, missed_count=len(missed),
        recent_misses=tuple(_clip(f"{t['target_id']}: {t['state_reason']}", 200) for t in missed[-5:]),
        usable_for_research=usable_flags(freshness, health, receipt)[0],
        usable_for_decision=usable_flags(freshness, health, receipt)[1],
        disagreements=tuple(disagreements),
        notes=("receipt time is each observation's recorded_at_utc (seconds after receipt); "
               "decision/recheck rows are backfilled, not fetched",),
        details=details)


def price_observations_schedule(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """ADR 0030 later/closing observations, from the stored targets and the canonical helpers."""
    store, problem = _open_store(ctx)
    if store is None:
        return [unknown_record(p, now, problem or "evidence store unavailable") for p in OBSERVATION_POLICIES]
    targets = store.price_targets()
    return [_observation_record(POLICY_OBSERVE, [t for t in targets if t["phase"] != "close"], targets, now, close=False),
            _observation_record(POLICY_OBSERVE_CLOSE, [t for t in targets if t["phase"] == "close"], targets, now,
                                close=True)]


# =========================================================================== settlement refresh and shadow bookkeeping


def read_receipts(status_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """The newest daily receipts: the tail of shadow_daily_history.jsonl plus shadow_daily.json,
    oldest first, de-duplicated. Returns (receipts, unreadable lines). Read-only and bounded."""
    from . import daily

    receipts: list[dict[str, Any]] = []
    bad = 0
    path = status_dir / daily.HISTORY_NAME
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - HISTORY_TAIL_BYTES)
            stream.seek(start)
            lines = stream.read().split(b"\n")
        if start > 0:
            lines = lines[1:]  # the first line may be cut
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(item, dict):
                receipts.append(item)
    except FileNotFoundError:
        pass
    status, latest = _read_json(status_dir / daily.RECEIPT_NAME)
    if status == "OK" and isinstance(latest, dict) and latest not in receipts[-3:]:
        receipts.append(latest)
    receipts.sort(key=lambda r: _t(r.get("generated_at_utc")) or datetime.min.replace(tzinfo=UTC))
    return receipts, bad


def _is_refresh(receipt: Mapping[str, Any]) -> bool:
    refresh = ((receipt.get("settlement") or {}).get("refresh") or {}).get("status")
    return refresh not in (None, "not_requested")


def _settlement_records(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    from . import daily

    if ctx.status_dir is None:
        why = "status directory not configured (the daily receipts live there)"
        return [unknown_record(POLICY_SETTLEMENT, now, why), unknown_record(POLICY_SHADOW, now, why)]
    receipts, bad = read_receipts(ctx.status_dir)
    refreshes = [r for r in receipts if _is_refresh(r)]
    shadows = [r for r in receipts if not _is_refresh(r)]
    notes = (f"{bad} unreadable history line(s) skipped",) if bad else ()

    # ---- settlement refresh (11:15 and 16:15 ET)
    last_tick, next_tick = _daily_ticks(now, SETTLEMENT_TICKS_ET, eastern=True)
    latest = refreshes[-1] if refreshes else None
    ran_at = _t(latest.get("generated_at_utc")) if latest else None
    state, next_due, why = _tick_state(now, last_tick, next_tick, ran_at, DAILY_RUN_GRACE, "settlement refresh")
    if latest is not None and latest.get("state") == "LOCK_BUSY" and ran_at and ran_at >= last_tick - timedelta(minutes=1):
        state, why = ScheduleState.LOCK_BUSY, f"the {iso_z(last_tick)} run found the collector or ledger lock held"
    due: list[str] | None = None
    due_problem = None
    if ctx.ledger is not None and ctx.ledger.is_file():
        try:
            from .shadow_ledger import ShadowLedger

            due = daily.pending_event_tickers(ShadowLedger.open_readonly(ctx.ledger), now)
        except Exception as exc:  # noqa: BLE001 - an unreadable ledger is reported, never repaired here
            due_problem = f"ledger unreadable ({type(exc).__name__})"
    elif ctx.ledger is not None:
        due, due_problem = [], "no shadow ledger yet"
    if due is not None:
        why += f"; {len(due)} event(s) due for settlement" if due else "; no open position is due (the run makes no request)"
    refresh_status = ((((latest or {}).get("settlement") or {}).get("refresh")) or {}).get("status")
    health = {"ok": SourceHealth.OK, "skipped": SourceHealth.OK, "partial": SourceHealth.DEGRADED,
              "failed": SourceHealth.FAILING, "not_run": SourceHealth.FAILING}.get(refresh_status, SourceHealth.UNKNOWN)
    if latest is not None and latest.get("state") in ("FAILED", "SETTLEMENT_CONFLICT"):
        health = SourceHealth.FAILING
    elif latest is not None and latest.get("state") == "LOCK_BUSY":
        health = SourceHealth.DEGRADED  # it did nothing; the next tick retries
    receipt = None
    store, problem = _open_store(ctx)
    if store is not None:
        for row in store.latest_source_health():
            if row["source_id"] == "kalshi_settlement":
                receipt = _t(row["last_ok_at_utc"])  # the latest status='ok' fetch only
    freshness = policy_freshness(POLICY_SETTLEMENT, receipt, now)
    research, decision = usable_flags(freshness, health, receipt)
    settlement = SourceFreshness(
        policy=POLICY_SETTLEMENT, as_of=now, freshness=freshness, schedule_state=state, health=health,
        why_due=_clip(why), intended_at=next_due, next_due=next_due, last_attempt=ran_at,
        last_success_receipt=receipt, receipt_ts=receipt,
        missed_count=1 if state is ScheduleState.MISSED else 0 if ran_at else None,
        usable_for_research=research, usable_for_decision=decision,
        notes=notes + ((f"due positions unknown: {due_problem}",) if due_problem else ())
              + ((f"evidence store: {problem}",) if problem else ())
              + ("freshness is the latest successful settlement-evidence fetch (source_health); a run with nothing "
                 "due fetches nothing",),
        details={"events_due": len(due) if due is not None else None, "events_due_sample": (due or [])[:5],
                 "last_refresh_status": refresh_status, "last_run_state": (latest or {}).get("state"),
                 "missed_scope": MISSED_SCOPE_TICK})

    # ---- shadow bookkeeping (18:40 ET)
    # Only a run that did its bookkeeping is a receipt. LOCK_BUSY, NO_CAPTURE and NOT_CLOSED did
    # no work; FAILED, SETTLEMENT_CONFLICT and INVALID_CAPTURE did not complete it cleanly. None of
    # them ever makes this source fresh or usable.
    last_tick, next_tick = _daily_ticks(now, (SHADOW_TICK_ET,), eastern=True)
    latest = shadows[-1] if shadows else None
    ran_at = _t(latest.get("generated_at_utc")) if latest else None
    success = [r for r in shadows if r.get("state") in SHADOW_SUCCESS_STATES]
    receipt = _t(success[-1].get("generated_at_utc")) if success else None
    state, next_due, why = _tick_state(now, last_tick, next_tick, ran_at, DAILY_RUN_GRACE, "shadow bookkeeping")
    run_state = (latest or {}).get("state")
    if run_state == "LOCK_BUSY" and ran_at and ran_at >= last_tick - timedelta(minutes=1):
        state, why = ScheduleState.LOCK_BUSY, f"the {iso_z(last_tick)} run found the collector or ledger lock held"
    health = (SourceHealth.UNKNOWN if run_state is None
              else SourceHealth.OK if run_state in SHADOW_SUCCESS_STATES
              else SourceHealth.FAILING if run_state in ("FAILED", "SETTLEMENT_CONFLICT")
              else SourceHealth.DEGRADED)  # LOCK_BUSY, NO_CAPTURE, NOT_CLOSED, INVALID_CAPTURE, anything new
    freshness = policy_freshness(POLICY_SHADOW, receipt, now)
    research, decision = usable_flags(freshness, health, receipt)
    shadow = SourceFreshness(
        policy=POLICY_SHADOW, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
        intended_at=next_due, next_due=next_due, last_attempt=ran_at, last_success_receipt=receipt,
        receipt_ts=receipt, missed_count=1 if state is ScheduleState.MISSED else 0 if ran_at else None,
        usable_for_research=research, usable_for_decision=decision, notes=notes,
        details={"last_run_state": run_state,
                 "problems": len(latest.get("problems") or []) if latest is not None else None,
                 "missed_scope": MISSED_SCOPE_TICK})
    return [settlement, shadow]


def settlement_and_shadow(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """Settlement refresh (11:15/16:15 ET) and shadow bookkeeping (18:40 ET), from the daily receipts."""
    return _settlement_records(ctx, now)


# =========================================================================== backups


def newest_manifest(directory: Path) -> tuple[datetime | None, str]:
    """(completed_at of the newest complete bundle, MISSING | EMPTY | OK | CORRUPT) in `directory`."""
    try:
        manifests = [(p.stat().st_mtime, p) for p in directory.glob("edge-backup-*/manifest.json") if p.is_file()]
    except OSError:
        return None, "UNREADABLE"
    if not directory.is_dir():
        return None, "MISSING"
    if not manifests:
        return None, "EMPTY"
    best = None
    for _, path in sorted(manifests)[-3:]:
        status, data = _read_json(path)
        at = _t(data.get("completed_at_utc")) if status == "OK" and isinstance(data, dict) else None
        if at is not None and (best is None or at > best):
            best = at
    return best, "OK" if best else "CORRUPT"


def backups(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """Daily verified backups (04:40 UTC) of the evidence database and the shadow ledger."""
    out = []
    last_tick, next_tick = _daily_ticks(now, (BACKUP_TICK_UTC,), eastern=False)
    for policy, sub in ((POLICY_BACKUP_EVIDENCE, None), (POLICY_BACKUP_LEDGER, "ledger")):
        if ctx.backups_dir is None:
            out.append(unknown_record(policy, now, f"backups directory not configured; next tick {iso_z(next_tick)}",
                                      next_due=next_tick, intended_at=next_tick))
            continue
        directory = ctx.backups_dir / sub if sub else ctx.backups_dir
        at, status = newest_manifest(directory)
        state, next_due, why = _tick_state(now, last_tick, next_tick, at, BACKUP_GRACE, f"{policy.source_id}")
        notes: tuple[str, ...] = ("a manifest proves the copy completed and matched its source; restore "
                                  "verification is verify_production's job",)
        if sub == "ledger" and at is None and ctx.ledger is not None and not ctx.ledger.is_file():
            state, next_due, why = ScheduleState.NOT_DUE, next_tick, "no shadow ledger yet: the backup skips it by design"
        health = SourceHealth.OK if at else SourceHealth.DEGRADED if status == "CORRUPT" else SourceHealth.UNKNOWN
        freshness = policy_freshness(policy, at, now)
        out.append(SourceFreshness(
            policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=_clip(why),
            intended_at=next_due, next_due=next_due, last_attempt=at, last_success_receipt=at, receipt_ts=at,
            missed_count=1 if state is ScheduleState.MISSED else 0 if at else None,
            usable_for_research=usable_flags(freshness, health, at)[0],
            usable_for_decision=usable_flags(freshness, health, at)[1], notes=notes,
            details={"bundles": status, "missed_scope": MISSED_SCOPE_TICK}))
    return out


# =========================================================================== the supervisor itself


def supervisor_self(ctx: FabricContext, now: datetime) -> list[SourceFreshness]:
    """This supervisor, judged from its previous artifact (the one this run replaces)."""
    policy = POLICY_SUPERVISOR
    tick = _next_grid_tick(now + timedelta(seconds=1), SUPERVISOR_TICK_MINUTES)
    if ctx.status_dir is None:
        return [unknown_record(policy, now, "status directory not configured", next_due=tick)]
    status, data = _read_json(ctx.status_dir / ARTIFACT_NAME)
    if status == "OK" and (not isinstance(data, dict) or data.get("schema") != SCHEMA):
        status = "WRONG_SCHEMA"
    previous = _t(data.get("generated_at_utc")) if status == "OK" else None
    freshness = policy_freshness(policy, previous, now)
    health = (SourceHealth.OK if previous and freshness is Freshness.FRESH
              else SourceHealth.UNKNOWN if status == "MISSING" else SourceHealth.DEGRADED)
    state = (ScheduleState.NOT_DUE if freshness is Freshness.FRESH
             else ScheduleState.MISSED if freshness is Freshness.STALE else ScheduleState.UNKNOWN)
    why = (f"previous artifact {iso_z(previous)}; next tick {iso_z(tick)}" if previous
           else f"no previous artifact ({status.lower()}); next tick {iso_z(tick)}")
    return [SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=why,
        intended_at=tick, next_due=tick, last_attempt=previous, last_success_receipt=previous, receipt_ts=previous,
        usable_for_research=usable_flags(freshness, health, previous)[0],
        notes=("judged from the artifact this run replaces; a crash shows as this record going STALE",),
        details={"previous_artifact": status,
                 "previous_state": ((data or {}).get("supervisor") or {}).get("state") if isinstance(data, dict) else None})]


# =========================================================================== registry

# One entry per provider. A later lane adds its provider with ONE line here (ADR 0031, "Adding a
# provider"); nothing else in this module changes.
REGISTRY: tuple[FabricProvider, ...] = (
    FabricProvider("exp001_forward", FORWARD_POLICIES, forward_weather),
    FabricProvider("the_odds_api", ODDS_POLICIES, odds_api_pilot),
    FabricProvider("price_observations", OBSERVATION_POLICIES, price_observations_schedule),
    FabricProvider("settlement_and_shadow", SETTLEMENT_POLICIES, settlement_and_shadow),
    FabricProvider("backups", BACKUP_POLICIES, backups),
    FabricProvider("freshness_supervisor", SUPERVISOR_POLICIES, supervisor_self),
    FabricProvider(polymarket_sports.FABRIC_PROVIDER_NAME, polymarket_sports.fabric_policies(), polymarket_sports.fabric_provider),
)


def _check_registry(registry: Sequence[FabricProvider]) -> None:
    names = [p.name for p in registry]
    ids = [pol.source_id for p in registry for pol in p.policies]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate provider names: {names}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"a source id is declared by two providers: {sorted(i for i in ids if ids.count(i) > 1)}")
    if len(ids) > MAX_SOURCES:
        raise ValueError(f"{len(ids)} sources exceed the artifact bound {MAX_SOURCES}")


_check_registry(REGISTRY)


# =========================================================================== evaluation


def evaluate(ctx: FabricContext, now: datetime, registry: Sequence[FabricProvider] = REGISTRY
             ) -> tuple[list[SourceFreshness], list[dict[str, Any]]]:
    """Run every provider in isolation. Returns (one record per declared source, provider reports).
    A provider that raises, omits a declared source, returns an undeclared one, or returns a record
    for another instant is reported; its declared sources become UNKNOWN records."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    _check_registry(registry)
    records: list[SourceFreshness] = []
    reports: list[dict[str, Any]] = []
    for entry in registry:
        declared = {p.source_id: p for p in entry.policies}
        report: dict[str, Any] = {"provider": entry.name, "state": "OK", "problems": []}
        try:
            produced = entry.provide(ctx, now)
            if not isinstance(produced, list):
                raise TypeError(f"returned {type(produced).__name__}, not a list")
        except Exception as exc:  # noqa: BLE001 - one provider never stops the others
            report["state"] = "ERROR"
            report["problems"].append(_clip(f"{type(exc).__name__}: {exc}", 200))
            records += [unknown_record(p, now, f"provider {entry.name} failed ({type(exc).__name__}); nothing is known")
                        for p in entry.policies]
            reports.append(report)
            continue
        seen: dict[str, SourceFreshness] = {}
        for item in produced:
            if not isinstance(item, SourceFreshness):
                report["problems"].append(f"returned a {type(item).__name__}, not a SourceFreshness")
            elif item.source_id not in declared or item.policy != declared[item.source_id]:
                report["problems"].append(_clip(f"returned undeclared source {item.source_id}"))
            elif item.as_of != now:
                report["problems"].append(f"{item.source_id}: record is for {iso_z(item.as_of)}, not {iso_z(now)}")
            elif item.source_id in seen:
                report["problems"].append(f"{item.source_id}: returned twice")
            else:
                seen[item.source_id] = item
        for sid, policy in declared.items():
            if sid in seen:
                records.append(seen[sid])
            else:
                report["problems"].append(f"{sid}: no valid record")
                records.append(unknown_record(policy, now, f"provider {entry.name} returned no valid record"))
        if report["problems"]:
            report["state"] = "PARTIAL"
        reports.append(report)
    return records, reports


def _bound(value: Any, depth: int = 0) -> Any:
    """Clip strings, lists and mappings so the artifact stays small whatever a provider returns."""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, Mapping):
        if depth > 3:
            return _clip(json.dumps(value, sort_keys=True, default=str))
        items = sorted(value.items(), key=lambda kv: str(kv[0]))[:MAX_DETAIL_KEYS]
        return {str(k)[:64]: _bound(v, depth + 1) for k, v in items}
    if isinstance(value, (list, tuple)):
        clipped = [_bound(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            clipped.append(f"(+{len(value) - MAX_ITEMS} more)")
        return clipped
    if isinstance(value, datetime):
        return iso_z(value) if value.tzinfo else None
    return _clip(value)


def _summary(sources: Sequence[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    """Counts and lists over the serialized records (the same for evaluated and carried sources)."""
    def counts(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in sources:
            out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
        return dict(sorted(out.items()))

    def ids(pred: Callable[[Mapping[str, Any]], bool]) -> list[str]:
        return [r["source_id"] for r in sources if pred(r)]

    upcoming = sorted(((_t(r.get("next_due_utc")), r) for r in sources
                       if _t(r.get("next_due_utc")) is not None and _t(r.get("next_due_utc")) > now),
                      key=lambda x: (x[0], x[1]["source_id"]))
    blocked = {ScheduleState.PAUSED.value, ScheduleState.BUDGET_BLOCKED.value, ScheduleState.QUOTA_BLOCKED.value,
               ScheduleState.LOCK_BUSY.value}
    return {
        "sources": len(sources),
        "by_freshness": counts("freshness"),
        "by_schedule_state": counts("schedule_state"),
        "by_health": counts("health"),
        "fresh": ids(lambda r: r.get("freshness") == Freshness.FRESH.name),
        "due_now": ids(lambda r: r.get("schedule_state") == ScheduleState.DUE.value),
        "missed": ids(lambda r: r.get("schedule_state") == ScheduleState.MISSED.value),
        "blocked": ids(lambda r: r.get("schedule_state") in blocked),
        "unknown": ids(lambda r: r.get("schedule_state") == ScheduleState.UNKNOWN.value),
        "disagreements": sum(len(r.get("disagreements") or []) for r in sources),
        "next_due": [{"source_id": r["source_id"], "next_due_utc": iso_z(at), "why": _clip(r.get("why_due"), 160)}
                     for at, r in upcoming[:5]],
    }


# A path starts the text or follows whitespace/punctuation, never a word character: "America/New_York"
# and "17:40-18:35" stay intact; "/etc/market-edge-lab/secrets.env" and "C:\x" are scrubbed.
_PATHLIKE = re.compile(r"""(?<![\w.-])(?:[A-Za-z]:)?[\\/][^\s'",;)\]]+""")


def strip_paths(text: str) -> str:
    """Text without filesystem paths, never shortened (time zones such as America/New_York stay)."""
    return _PATHLIKE.sub("<path>", str(text))


def scrub(text: str) -> str:
    """A problem text without filesystem paths (exception messages can carry them), clipped."""
    return _clip(strip_paths(text), 200)


def code_version() -> str | None:
    """The deployed commit: EDGE_LAB_CODE_VERSION, else the installer's REVISION file. Hex only."""
    candidates = [os.environ.get("EDGE_LAB_CODE_VERSION")]
    revision = Path(__file__).resolve().parents[2] / "REVISION"
    try:
        if revision.is_file() and revision.stat().st_size < 100:
            candidates.append(revision.read_text(encoding="ascii").strip())
    except (OSError, UnicodeDecodeError):
        pass
    for value in candidates:
        if value and re.fullmatch(r"[0-9a-f]{7,40}", value):
            return value
    return None


def build_status(ctx: FabricContext, now: datetime, registry: Sequence[FabricProvider] = REGISTRY) -> dict[str, Any]:
    """The status document: current state only. No paths, no environment, no secrets."""
    records, reports = evaluate(ctx, now, registry)
    problems = [scrub(f"{r['provider']}: {p}") for r in reports for p in r["problems"]]
    # The artifact holds no filesystem paths (ADR 0031): a provider's why_due text may name one.
    sources = [{**d, "why_due": _PATHLIKE.sub("<path>", d["why_due"]) if isinstance(d.get("why_due"), str) else d.get("why_due")}
               for d in (r.to_dict() for r in records)]
    return {
        "schema": SCHEMA,
        "generated_at_utc": iso_z(now),
        "sources_evaluated_at_utc": iso_z(now),
        "fabric_version": FABRIC_VERSION,
        "supervisor": {
            "state": "OK" if all(r["state"] == "OK" for r in reports) else "PARTIAL",
            "code_version": code_version(), "network": "none", "controls_schedules": False,
            "providers": [{"provider": r["provider"], "state": r["state"]} for r in reports],
            "problems": problems,
        },
        "summary": _summary(sources, now),
        "policies": [p.to_dict() for entry in registry for p in entry.policies],
        "sources": sources,
    }


# A carried evaluation must have been made at most this long before the protected window opened.
CARRY_MARGIN = timedelta(minutes=15)


def _reassess_carried(source: Mapping[str, Any], now: datetime, evaluated: str) -> dict[str, Any]:
    """A carried record re-judged at `now` by pure arithmetic from its own receipt time and objective:
    ages and freshness move on, decision-grade use is off while deferred, and the schedule state is
    as of the evaluation (labelled so)."""
    receipt, upstream = _t(source.get("receipt_ts_utc")), _t(source.get("upstream_ts_utc"))
    max_age = source.get("max_useful_age_s")
    usable_age = isinstance(max_age, (int, float)) and not isinstance(max_age, bool) and max_age > 0
    fresh = assess(receipt, max_age=timedelta(seconds=max_age), now=now) if usable_age else Freshness.UNKNOWN
    return {
        **source,
        "freshness": fresh.name,
        "data_age_s": round((now - receipt).total_seconds(), 3) if receipt else None,
        "upstream_age_s": round((now - upstream).total_seconds(), 3) if upstream else None,
        "usable_for_research": (bool(source.get("usable_for_research")) and receipt is not None
                                and fresh is not Freshness.UNKNOWN),
        "usable_for_decision": False,
        "carried_from_utc": evaluated,
        # Label once: a record already carried keeps its label and original reason (no nesting per run).
        "why_due": source.get("why_due") if source.get("carried_from_utc") else _clip(
            f"carried from the {evaluated} evaluation (protected window): {source.get('why_due')}"),
    }


def deferred_status(ctx: FabricContext, now: datetime, window: tuple[str, datetime, datetime],
                    registry: Sequence[FabricProvider] = REGISTRY) -> dict[str, Any]:
    """Inside a protected window the supervisor opens no store. It carries the previous evaluation
    forward only if that evaluation was made at most CARRY_MARGIN before the window opened; each
    carried record is re-assessed at `now` from its receipt time (pure arithmetic) with decision-grade
    use off. Anything it cannot carry is UNKNOWN. `sources_evaluated_at_utc` stays the time of the
    evaluation actually carried (None when nothing is)."""
    status, previous = _read_json(ctx.status_dir / ARTIFACT_NAME) if ctx.status_dir else ("NOT_CONFIGURED", None)
    valid = status == "OK" and isinstance(previous, dict) and previous.get("schema") == SCHEMA
    evaluated = _t(previous.get("sources_evaluated_at_utc")) if valid else None
    problems: list[str] = []
    if not valid:
        problems.append(f"no previous evaluation to carry forward ({status.lower()})")
    elif evaluated is None or evaluated > now or evaluated < window[1] - CARRY_MARGIN:
        problems.append(f"the previous evaluation ({iso_z(evaluated)}) is too old to carry into the window "
                        f"opened {iso_z(window[1])} (margin {int(CARRY_MARGIN.total_seconds() // 60)} min)")
        evaluated = None
    carried = ({s["source_id"]: s for s in previous.get("sources") or []
                if isinstance(s, dict) and isinstance(s.get("source_id"), str)} if evaluated is not None else {})
    sources = []
    for entry in registry:
        for policy in entry.policies:
            if policy.source_id in carried:
                sources.append(_reassess_carried(carried[policy.source_id], now, iso_z(evaluated)))
            else:
                sources.append(unknown_record(policy, now, f"not evaluated: inside the {window[0]} protected window "
                                              "with no evaluation to carry").to_dict())
    return {
        "schema": SCHEMA,
        "generated_at_utc": iso_z(now),
        "sources_evaluated_at_utc": iso_z(evaluated),
        "fabric_version": FABRIC_VERSION,
        "supervisor": {
            "state": "DEFERRED_PROTECTED_WINDOW", "code_version": code_version(), "network": "none",
            "controls_schedules": False, "providers": [], "problems": problems,
            "deferred": {"window": window[0], "from_utc": iso_z(window[1]), "to_utc": iso_z(window[2]),
                         "detail": "no store opened inside a protected window; carried sources are re-assessed at "
                                   "generated_at_utc from their receipt times, never decision-grade, and their "
                                   "schedule states are as of sources_evaluated_at_utc"},
        },
        "summary": _summary(sources, now),
        "policies": [p.to_dict() for entry in registry for p in entry.policies],
        "sources": sources,
    }


def _bound_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Bound each field's value; the record's own (fixed) keys are all kept."""
    return {str(k): _bound(v) for k, v in record.items()}


def render(doc: Mapping[str, Any]) -> str:
    """Bounded JSON text of a status document (clips values first, then drops details)."""
    bounded = dict(doc)
    bounded["sources"] = [_bound_fields(s) for s in doc.get("sources") or []][:MAX_SOURCES]
    bounded["policies"] = [_bound_fields(p) for p in doc.get("policies") or []][:MAX_SOURCES]
    bounded["supervisor"] = _bound_fields(doc.get("supervisor") or {})
    text = json.dumps(bounded, sort_keys=True, indent=1, default=str) + "\n"
    if len(text.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        bounded["sources"] = [{**s, "details": {"dropped": "artifact size bound"}} for s in bounded["sources"]]
        bounded["policies"] = [{"source_id": p.get("source_id")} for p in bounded["policies"]]
        text = json.dumps(bounded, sort_keys=True, indent=1, default=str) + "\n"
    if len(text.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"status artifact exceeds {MAX_ARTIFACT_BYTES} bytes even without details")
    return text


def write_status(text: str, status_dir: Path) -> Path:
    """Atomic replace of `<status_dir>/freshness.json` (0644, non-sensitive, current state only)."""
    status_dir.mkdir(parents=True, exist_ok=True)
    target = status_dir / ARTIFACT_NAME
    tmp = status_dir / f".{ARTIFACT_NAME}.{os.getpid()}.tmp"
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
        _fsync_dir(status_dir)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def _fsync_dir(directory: Path) -> None:
    """Make the rename durable (POSIX). Windows cannot open a directory for fsync: skipped there."""
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def status(ctx: FabricContext, now: datetime, *, write: bool = False,
           registry: Sequence[FabricProvider] = REGISTRY) -> tuple[dict[str, Any], str]:
    """(document, rendered text). With `write`, a protected window defers evaluation and the
    artifact is replaced; without it (an operator's read) everything is always evaluated."""
    if write and ctx.status_dir is None:
        raise ValueError("--write needs --status-dir")
    window = (po.protected_window_at(now, now + timedelta(minutes=1)) or close_guard_at(now)) if write else None
    doc = deferred_status(ctx, now, window, registry) if window is not None else build_status(ctx, now, registry)
    text = render(doc)
    if write:
        write_status(text, ctx.status_dir)
    return doc, text


# =========================================================================== CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-lab freshness",
        description="Freshness Fabric v1 (ADR 0031): what is fresh, what is due next, and why. Read-only, "
                    "network-free; it observes the existing schedules and controls none.")
    sub = parser.add_subparsers(dest="freshness_command", required=True)
    st = sub.add_parser("status", help="Evaluate every registered source; print JSON; --write replaces freshness.json.")
    st.add_argument("--db", default="data/edge_lab.sqlite3", help="evidence store (opened read-only; never created)")
    st.add_argument("--ledger", help="shadow ledger (opened read-only)")
    st.add_argument("--odds-ledger", help=f"The Odds API quota ledger (default: {ODDS_LEDGER_FILE} beside --db)")
    st.add_argument("--odds-state", help="the Odds pilot runner state (default: <odds-ledger>.pilot.json)")
    st.add_argument("--status-dir", help="status directory (read; written only with --write)")
    st.add_argument("--backups-dir", help="backup bundles directory")
    st.add_argument("--write", action="store_true", help="replace <status-dir>/freshness.json atomically")
    st.add_argument("--now", help="evaluate at this ISO-8601 time with a zone (default: the clock)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 0 when a status was produced (whatever it says), 2 on bad arguments. Anything else
    is a genuine crash and propagates (non-zero exit with a traceback in the journal)."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    now = datetime.now(UTC)
    if args.now:
        now = parse_utc(args.now)
        if now is None:
            print("--now must be ISO-8601 with a zone", file=sys.stderr)
            return 2
    if args.write and not args.status_dir:
        print("--write needs --status-dir", file=sys.stderr)
        return 2
    db = Path(args.db)
    odds_ledger = Path(args.odds_ledger) if args.odds_ledger else db.with_name(ODDS_LEDGER_FILE)
    ctx = FabricContext(db=db, ledger=Path(args.ledger) if args.ledger else None, odds_ledger=odds_ledger,
                        odds_pilot_state=Path(args.odds_state) if args.odds_state else None,
                        status_dir=Path(args.status_dir) if args.status_dir else None,
                        backups_dir=Path(args.backups_dir) if args.backups_dir else None)
    doc, text = status(ctx, now, write=args.write)
    if args.write:
        # The timer's run: one short line for the journal (288 runs a day), not the whole document.
        summary = doc.get("summary") or {}
        print(json.dumps({"schema": SCHEMA, "written": ARTIFACT_NAME, "generated_at_utc": doc["generated_at_utc"],
                          "sources_evaluated_at_utc": doc.get("sources_evaluated_at_utc"),
                          "supervisor": doc["supervisor"]["state"], "sources": summary.get("sources"),
                          "by_schedule_state": summary.get("by_schedule_state"),
                          "disagreements": summary.get("disagreements"), "bytes": len(text.encode("utf-8"))},
                         sort_keys=True))
    else:
        sys.stdout.write(text)
    return 0


__all__ = [
    "ARTIFACT_NAME", "REGISTRY", "SCHEMA", "build_status", "evaluate", "forward_weather", "main",
    "odds_api_pilot", "price_observations_schedule", "render", "settlement_and_shadow", "status", "backups",
    "supervisor_self", "write_status",
]
