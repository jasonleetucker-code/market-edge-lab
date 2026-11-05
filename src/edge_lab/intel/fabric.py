"""Freshness Fabric provider for the news intelligence lane (#192, ADR 0049, ADR 0031 contract C1).

Two declared sources, both run by their own systemd timer (fabric mode EXTERNAL_SCHEDULE):

- `news_feeds_public`: the 2-hour news run (`edgelab-news.timer`, `edge-lab intel run`). The
  receipt is the newest successful feed fetch (`intel_fetches` outcome OK or NOT_MODIFIED: a 304
  confirms the copy we hold is current). The last attempt is the newest `run` journal record.
- `intel_inbox`: the dashboard inbox drain (`edgelab-news-inbox.timer`, `edge-lab intel
  process-inbox`; the 2-hour run drains it too). The receipt is the `intel.json` heartbeat both
  write to the status directory.

Both timers ship DISABLED (install.sh SEPARATELY_ACTIVATED); activation is the owner's
(`docs/deploy/NEWS_INTEL_ACTIVATION.md`). Whether a timer is enabled is not observable here, so a
source with no run on record reads PAUSED ("not activated"), and one whose runs stopped reads
MISSED with the reason spelled out. Nothing is guessed: unknown stays UNKNOWN.

`provide(context, now)` is read-only and network-free: the evidence store is opened with
`SnapshotStore.open_readonly` (mode=ro, query_only; it refuses a store that is not v8), and the
heartbeat is a bounded JSON read. It never takes a lock, writes, migrates, or triggers a run.
"""

from __future__ import annotations

import json
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any

from ..sources import get_source

FABRIC_PROVIDER_NAME = "news_intel"
POLICY_VERSION = "news-intel-fabric-v1"
NEWS_SOURCE_ID = "news_feeds_public"
INBOX_SOURCE_ID = "intel_inbox"

# The fabric's copy of each timer's schedule; tests/test_intel_fabric.py pins them to the unit files.
NEWS_TIMER = "edgelab-news.timer"
INBOX_TIMER = "edgelab-news-inbox.timer"
NEWS_TICKS_ET = tuple(dtime(h, 32) for h in range(1, 24, 2))  # OnCalendar=*-*-* 01/2:32:00 America/New_York
NEWS_INTERVAL = timedelta(hours=2)
NEWS_GRACE = timedelta(minutes=10)  # edgelab-news.service TimeoutStartSec=6min, plus slack
INBOX_TICK_MINUTES = tuple(range(3, 60, 5))  # OnCalendar=*-*-* *:03/5:00 America/New_York (whole-hour offsets)
INBOX_INTERVAL = timedelta(minutes=5)
INBOX_MAX_AGE = timedelta(minutes=15)  # three missed ticks, as for the supervisor's own record
NEWS_MIN_INTERVAL = timedelta(minutes=15)  # intel.service.NEWS_REFRESH_MIN_INTERVAL: an owner refresh at most this often

HEARTBEAT_FILE = "intel.json"
HEARTBEAT_SCHEMA = "intel-heartbeat/1"
HEARTBEAT_PROCESSORS = ("inbox", "run")  # both drain the inbox
ACTIVATION_DOC = "docs/deploy/NEWS_INTEL_ACTIVATION.md"
NOT_ACTIVATED = ("ships disabled (install.sh SEPARATELY_ACTIVATED); enabling it is the owner's decision "
                 f"({ACTIVATION_DOC})")
TIMER_NOT_OBSERVABLE = "whether the news timers are enabled is not observable here"


def fabric_policies() -> tuple[Any, Any]:
    """The two `freshness.SourcePolicy` records this provider declares (news run, inbox drain)."""
    from ..freshness import AcquisitionMode, SourcePolicy
    from ..price_observations import PROTECTED_WINDOWS_ET
    from .contracts import MAX_FEED_GETS_PER_RUN, MAX_INBOX_PENDING, MAX_KALSHI_GETS_PER_RUN

    windows = tuple(f"{name} {a:%H:%M}-{b:%H:%M} America/New_York" for name, a, b in PROTECTED_WINDOWS_ET)
    return (
        SourcePolicy(
            source_id=NEWS_SOURCE_ID, domain="news", mode=AcquisitionMode.EXTERNAL_SCHEDULE,
            underlying_mode=AcquisitionMode.POLL,
            description="News intelligence feeds (#192, ADR 0049): verified public RSS/Atom and official feeds, "
                        "headline, link, timestamps and a <=300-char snippet; objective: the registered feed max_age. "
                        "Feed GETs are not refused inside protected windows (they are not Kalshi); the run's Kalshi "
                        "quote refresh (kalshi_public_intel) is, by the code",
            policy_version=POLICY_VERSION,
            schedule_owner=f"systemd {NEWS_TIMER} every 2 h at :32 past odd hours America/New_York (installed, "
                           f"enabled only by {ACTIVATION_DOC}) + edge_lab.intel.service.collect_news",
            max_useful_age=get_source(NEWS_SOURCE_ID).max_age["feed"],
            min_safe_cadence=NEWS_INTERVAL, max_useful_cadence=NEWS_MIN_INTERVAL,
            pacing="at most 1 GET per collected feed per run; conditional GETs (ETag / Last-Modified)",
            budget=f"at most {MAX_FEED_GETS_PER_RUN} feed GETs and {MAX_KALSHI_GETS_PER_RUN} Kalshi GETs per run",
            protected_windows=windows,
            retry="1 retry per feed GET; a failed feed is recorded and retried by the next run, never fetched late"),
        SourcePolicy(
            source_id=INBOX_SOURCE_ID, domain="news", mode=AcquisitionMode.EXTERNAL_SCHEDULE,
            underlying_mode=AcquisitionMode.POLL,
            description="The dashboard's private inbox (transcripts, analysis pastes, link decisions, refresh "
                        "requests) drained by the collector; objective: a drain within three 5-minute ticks. No "
                        "network unless the owner queued a refresh",
            policy_version=POLICY_VERSION,
            schedule_owner=f"systemd {INBOX_TIMER} every 5 min at :03/:08/.../:58 America/New_York (installed, "
                           f"enabled only by {ACTIVATION_DOC}) + edge_lab.intel.inbox.process_inbox; "
                           f"{NEWS_TIMER} drains it too",
            max_useful_age=INBOX_MAX_AGE, min_safe_cadence=INBOX_MAX_AGE, max_useful_cadence=INBOX_INTERVAL,
            pacing=f"at most {MAX_INBOX_PENDING} submissions per drain; a queued news refresh at most once per "
                   f"{int(NEWS_MIN_INTERVAL.total_seconds() // 60)} min",
            budget="a queued refresh uses the news run's bounds",
            protected_windows=windows,
            retry="a rejected submission is recorded and moved to rejected/; it is never retried"),
    )


def _news_record(policy: Any, ctx: Any, now: datetime) -> Any:
    from .. import freshness_fabric as ff
    from ..freshness import ScheduleState, SourceFreshness, SourceHealth, policy_freshness, usable_flags

    store, problem = ff._open_store(ctx)
    if store is None:
        return ff.unknown_record(policy, now, problem, notes=(TIMER_NOT_OBSERVABLE,))
    try:
        run = store.latest_intel_record("run", "news")
        fetches = store.intel_fetch_summary()
    except Exception as exc:  # noqa: BLE001 - reported as UNKNOWN; the supervisor must not fail on it
        return ff.unknown_record(policy, now, f"intel tables unreadable ({type(exc).__name__})",
                                 notes=(TIMER_NOT_OBSERVABLE,))
    receipt = max((t for t in (ff._t(r["last_success_utc"]) for r in fetches) if t is not None), default=None)
    freshness = policy_freshness(policy, receipt, now)
    last_tick, next_tick = ff._daily_ticks(now, NEWS_TICKS_ET, eastern=True)
    if run is None:
        health = SourceHealth.UNKNOWN
        research, _ = usable_flags(freshness, health, receipt)
        return SourceFreshness(
            policy=policy, as_of=now, freshness=freshness, schedule_state=ScheduleState.PAUSED, health=health,
            why_due=ff._clip(f"not activated: no news run on record; {NEWS_TIMER} {NOT_ACTIVATED}"),
            intended_at=next_tick, last_success_receipt=receipt, receipt_ts=receipt, missed_count=None,
            usable_for_research=research, usable_for_decision=False,
            notes=(TIMER_NOT_OBSERVABLE,), details={"feeds_on_record": len(fetches)})
    try:
        payload = json.loads(run["payload_json"])
    except (TypeError, ValueError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    ran_at = ff._t(payload.get("started_at_utc")) or ff._t(run["recorded_at_utc"])
    counts = {k: payload.get(k) if isinstance(payload.get(k), int) else None
              for k in ("feeds", "ok", "not_modified", "failed", "skipped", "gets", "new_items")}
    success = None if counts["ok"] is None or counts["not_modified"] is None else counts["ok"] + counts["not_modified"]
    failed = counts["failed"]
    if success is None or failed is None:
        health = SourceHealth.UNKNOWN
    elif success and not failed:
        health = SourceHealth.OK
    elif success:
        health = SourceHealth.DEGRADED
    elif failed:
        health = SourceHealth.FAILING
    else:
        health = SourceHealth.UNKNOWN  # nothing was fetched at all: no attempt to judge
    state, next_due, why = ff._tick_state(now, last_tick, next_tick, ran_at, NEWS_GRACE, "news")
    notes = [TIMER_NOT_OBSERVABLE]
    if state is ScheduleState.MISSED:
        notes.append(f"a MISSED tick is expected while {NEWS_TIMER} is disabled (not yet activated, or paused); "
                     "a manual `edge-lab intel collect` or a queued refresh also records a run")
    if success == 0 and not failed:
        state, next_due = ScheduleState.PAUSED, None
        why = (f"the last run ({ff.iso_z(ran_at)}) fetched no feed: every feed was skipped (none ACTIVE or LIMITED "
               "and verified in the last 14 days); the owner runs `edge-lab intel verify-sources`")
    research, _ = usable_flags(freshness, health, receipt)
    return SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=ff._clip(why),
        intended_at=next_due, next_due=next_due, last_attempt=ran_at, last_success_receipt=receipt,
        receipt_ts=receipt, missed_count=1 if state is ScheduleState.MISSED else 0,
        usable_for_research=research, usable_for_decision=False,  # research evidence only, never decision-grade
        notes=tuple(ff._clip(n) for n in notes),
        details={**counts, "run_id": ff._clip(payload.get("run_id"), 80) if payload.get("run_id") else None,
                 "feeds_on_record": len(fetches), "missed_scope": ff.MISSED_SCOPE_TICK})


def _inbox_record(policy: Any, ctx: Any, now: datetime) -> Any:
    from .. import freshness_fabric as ff
    from ..freshness import Freshness, ScheduleState, SourceFreshness, SourceHealth, policy_freshness, usable_flags

    status_dir = getattr(ctx, "status_dir", None)
    if status_dir is None:
        return ff.unknown_record(policy, now, "status directory not configured", notes=(TIMER_NOT_OBSERVABLE,))
    status, data = ff._read_json(Path(status_dir) / HEARTBEAT_FILE)
    next_tick = ff._next_grid_tick(now, INBOX_TICK_MINUTES)
    if status == "MISSING":
        return SourceFreshness(
            policy=policy, as_of=now, freshness=Freshness.UNKNOWN, schedule_state=ScheduleState.PAUSED,
            health=SourceHealth.UNKNOWN,
            why_due=ff._clip(f"not activated: no {HEARTBEAT_FILE} heartbeat; {INBOX_TIMER} {NOT_ACTIVATED}"),
            intended_at=next_tick, notes=(TIMER_NOT_OBSERVABLE,), details={"heartbeat": status})
    at = ff._t(data.get("at_utc")) if status == "OK" and isinstance(data, dict) else None
    if (at is None or data.get("schema") != HEARTBEAT_SCHEMA
            or data.get("processor") not in HEARTBEAT_PROCESSORS or at > now + timedelta(minutes=1)):
        return ff.unknown_record(policy, now, f"{HEARTBEAT_FILE} is not a readable {HEARTBEAT_SCHEMA} heartbeat "
                                              f"({status.lower()})", notes=(TIMER_NOT_OBSERVABLE,),
                                 details={"heartbeat": status})
    freshness = policy_freshness(policy, at, now)
    health = SourceHealth.OK  # the heartbeat is written only after a drain completed
    if now - at <= INBOX_MAX_AGE:
        state, next_due = ScheduleState.NOT_DUE, next_tick
        why = f"drained at {ff.iso_z(at)} ({data['processor']}); next tick {ff.iso_z(next_tick)}"
        notes: tuple[str, ...] = (TIMER_NOT_OBSERVABLE,)
    else:
        state, next_due = ScheduleState.MISSED, next_tick
        why = (f"no drain since {ff.iso_z(at)} ({data['processor']}): more than "
               f"{int(INBOX_MAX_AGE.total_seconds() // 60)} min, three ticks; next tick {ff.iso_z(next_tick)}")
        notes = (TIMER_NOT_OBSERVABLE,
                 f"expected while {INBOX_TIMER} is disabled; {NEWS_TIMER} alone drains the inbox every 2 h")
    research, _ = usable_flags(freshness, health, at)
    processed = data.get("processed")
    return SourceFreshness(
        policy=policy, as_of=now, freshness=freshness, schedule_state=state, health=health, why_due=ff._clip(why),
        intended_at=next_due, next_due=next_due, last_attempt=at, last_success_receipt=at, receipt_ts=at,
        usable_for_research=research, usable_for_decision=False, notes=notes,
        details={"heartbeat": status, "processor": data["processor"],
                 "processed": processed if isinstance(processed, int) and not isinstance(processed, bool) else None})


def fabric_provider(context: Any, now: datetime) -> list[Any]:
    """Freshness Fabric provider (contract C1: `provider(context, now) -> list[SourceFreshness]`).
    Read-only and network-free; a missing or unreadable input is reported as UNKNOWN, never raised."""
    news_policy, inbox_policy = fabric_policies()
    return [_news_record(news_policy, context, now), _inbox_record(inbox_policy, context, now)]


__all__ = ["FABRIC_PROVIDER_NAME", "INBOX_SOURCE_ID", "NEWS_SOURCE_ID", "fabric_policies", "fabric_provider"]
