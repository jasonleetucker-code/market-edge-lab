"""The Odds API NFL pilot runner: discovery, targets, budget and at most one paid call per tick.

ADR 0029, owner correction 3 (2026-09-24). This module composes the adapter
(`edge_lab.odds_api`), the pure planner (`edge_lab.odds_schedule`) and the evidence store. It
owns no provider format, no quota arithmetic and no planning rule of its own.

One tick (`run_tick`, the `edgelab-odds` timer every 15 minutes):

1. No key: SETUP_NEEDED, exit 0, nothing sent, nothing secret printed.
2. Inside the 17:40-18:35 America/New_York capture window: DEFERRED, no network, no writes.
3. One tick at a time (a file lock); a second concurrent tick exits LOCK_BUSY.
4. A capture that crashed mid-call (state CAPTURING) becomes FAILED: never retried, so a
   lost response cannot spend credits twice.
5. Discovery through the quota-free events endpoint, at most every `discovery_interval`,
   stored as immutable evidence. Its quota headers reconcile the ledger.
6. Plan new targets, supersede targets whose event moved, mark expired targets MISSED.
7. Coalesce open targets into slots and run the monthly credit proof. Skipped slots are
   SKIPPED_BUDGET.
8. If an admitted slot is due: exactly ONE `fetch_odds` call, stored with its request
   identity, quota headers and coverage; members become CAPTURED (or FAILED, QUOTA_*).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import http, odds_api
from .forward import LockBusy, eastern_offset, exclusive_lock
from .freshness import parse_utc
from .odds_schedule import (
    POLICY_VERSION,
    BudgetProof,
    CaptureTarget,
    PilotConfig,
    QuotaReading,
    ScheduledEvent,
    Slot,
    budget,
    coalesce,
    deadline,
    effective_due,
    in_quiet_window,
    is_expired,
    iso_z,
    month_bounds,
    plan_targets,
)
from .storage import ODDS_TARGET_FINAL_STATES, ReadOnlyStoreError, SnapshotStore

UTC = timezone.utc
SOURCE = odds_api.get_source(odds_api.SOURCE_ID).legacy_name
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class RunnerSettings:
    sport: str = "americanfootball_nfl"
    markets: tuple[str, ...] = ("h2h", "spreads", "totals")
    regions: tuple[str, ...] = ("us",)
    odds_format: str = "american"  # what US books publish; kept raw, converted by parse_odds
    discovery_interval: timedelta = timedelta(hours=6)  # free, but polite
    discovery_max_age: timedelta = timedelta(hours=24)  # older: no paid call (DEFERRED)
    discovery_horizon: timedelta = timedelta(days=35)  # covers the rest of any month
    smoke_horizon: timedelta = timedelta(days=7)
    config: PilotConfig = field(default_factory=PilotConfig)

    @property
    def cost_per_call(self) -> int:
        return odds_api.estimate_cost(list(self.markets), list(self.regions))


def _real_clock() -> datetime:
    return datetime.now(UTC)


def _parse(value: str) -> datetime:
    parsed = parse_utc(value)
    if parsed is None:
        raise ValueError(f"not a zoned timestamp: {value!r}")
    return parsed.astimezone(UTC)


def _et_text(instant: datetime) -> str:
    local = instant + eastern_offset(instant)
    return local.strftime("%a %Y-%m-%d %H:%M ET")


class _LazyRun:
    """A collection_runs row only when something is stored: 96 idle ticks a day add nothing."""

    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.run_id: str | None = None

    def id(self) -> str:
        if self.run_id is None:
            self.run_id = f"odds-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
            self.store.start_run(self.run_id)
        return self.run_id

    def finish(self, failed: bool) -> None:
        if self.run_id is not None:
            self.store.finish_run(self.run_id, status="failed" if failed else "succeeded",
                                  error="see the odds tick report" if failed else None)


def _target(row: Mapping[str, Any]) -> CaptureTarget:
    return CaptureTarget(row["target_id"], row["sport"], row["event_id"], row["offset_label"], int(row["priority"]),
                         _parse(row["commence_time_utc"]), _parse(row["target_utc"]), row["home_team"],
                         row["away_team"])


def _quota(ledger: odds_api.QuotaLedger | None) -> QuotaReading:
    if ledger is None:
        return QuotaReading("QUOTA_UNKNOWN")
    snap = ledger.snapshot()
    headers = snap.get("last_headers") or {}
    return QuotaReading(state=snap["state"], local_used=int(snap["used_local"]),
                        provider_used=headers.get("used") if snap["state"] != "QUOTA_UNKNOWN" else None,
                        provider_remaining=headers.get("remaining") if snap["state"] != "QUOTA_UNKNOWN" else None,
                        outstanding=int(snap["outstanding"]))


def _events_from_snapshot(row: Any, sport: str) -> tuple[tuple[ScheduledEvent, ...], tuple[str, ...], dict]:
    payload = json.loads(row["payload_json"])
    events, problems = odds_api.parse_events(payload.get("events"), sport=sport)
    return events, problems, payload.get("request") or {}


def _discovered_at(row: Any) -> datetime:
    """When a discovery was made on the tick's clock (`tick_utc`), else its receipt time. The two
    agree in production; the tick clock is what planning and tests measure age against."""
    request = json.loads(row["payload_json"]).get("request") or {}
    stamped = parse_utc(request.get("tick_utc"))
    return stamped.astimezone(UTC) if stamped is not None else _parse(row["fetched_at_utc"])


def _counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return dict(sorted(out.items()))


def _event_coverage(snapshot: odds_api.OddsSnapshot, native_event: str, markets: Sequence[str]) -> dict[str, Any]:
    eid = odds_api.event_id(native_event)
    offers = [o for o in snapshot.offers if o.event_id == eid]
    books = sorted({o.bookmaker for o in offers})
    got = sorted({o.market_key for o in offers})
    return {"event_present": any(e.event_id == eid for e in snapshot.events), "bookmakers": books,
            "markets": got, "missing_markets": sorted(set(markets) - set(got)), "offers": len(offers)}


# --------------------------------------------------------------------------- the tick


def run_tick(db_path: str | Path, ledger_path: str | Path, settings: RunnerSettings = RunnerSettings(), *,
             clock: Clock = _real_clock, opener: http.Opener | None = None, pacer: http.Pacer | None = None,
             environ: Mapping[str, str] | None = None, lock_timeout_s: float = 5.0,
             clear_cost_block: bool = False) -> tuple[int, dict[str, Any]]:
    """One idempotent tick. Returns (exit code, report). The report never holds the key."""
    now = clock()
    cfg = settings.config
    report: dict[str, Any] = {"command": "odds run", "now_utc": iso_z(now), "sport": settings.sport,
                              "policy_version": POLICY_VERSION, "paid_calls": 0}
    db_path, ledger_path = Path(db_path), Path(ledger_path)
    key_present = odds_api.load_key(environ) is not None
    if not key_present and not db_path.exists():
        report.update(state="SETUP_NEEDED", detail=_setup_text())
        return 0, report
    if in_quiet_window(now, cfg):
        report.update(state="DEFERRED_CAPTURE_WINDOW",
                      detail="inside 17:40-18:35 America/New_York: no network, no writes this tick")
        return 0, report
    try:
        with exclusive_lock(ledger_path.with_name(ledger_path.name + ".tick.lock"), timeout_s=lock_timeout_s):
            return _tick_locked(db_path, ledger_path, settings, now, clock, opener, pacer, environ, key_present,
                                report, clear_cost_block)
    except LockBusy:
        report.update(state="LOCK_BUSY", detail="another odds tick is running; this one did nothing")
        return 0, report


def _setup_text() -> str:
    var = odds_api.get_source(odds_api.SOURCE_ID).credential_env_var
    return (f"SETUP_NEEDED: the owner installs the free read-only key as {var} in "
            "/etc/market-edge-lab/secrets.env (sudoedit; never in git or chat). Nothing was sent.")


class PilotState:
    """Small non-secret runner state beside the quota ledger (`<ledger>.pilot.json`): the last
    discovery attempt and its outcome (to pace retries and alert only on a change), and a cost
    block set when the provider charged more than the estimate. Never holds the key."""

    def __init__(self, ledger_path: Path) -> None:
        self.path = ledger_path.with_name(ledger_path.name + ".pilot.json")
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            loaded = {}
        self.data: dict[str, Any] = loaded if isinstance(loaded, dict) else {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, **values: Any) -> None:
        self.data.update(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(self.data, sort_keys=True, indent=1), encoding="utf-8")
        tmp.replace(self.path)


KEY_REJECTED_STATUSES = (401, 403)


def _tick_locked(db_path: Path, ledger_path: Path, settings: RunnerSettings, now: datetime, clock: Clock,
                 opener: http.Opener | None, pacer: http.Pacer | None, environ: Mapping[str, str] | None,
                 key_present: bool, report: dict[str, Any], clear_cost_block: bool = False) -> tuple[int, dict[str, Any]]:
    store = SnapshotStore(db_path)
    run = _LazyRun(store)
    try:
        return _tick_body(store, run, ledger_path, settings, now, clock, opener, pacer, environ, key_present, report,
                          clear_cost_block)
    except Exception as exc:  # never leave a collection run 'running' or print a raw error
        run.finish(True)
        report.update(state="FAILED", error_kind=type(exc).__name__,
                      detail="unexpected error; the tick stopped (see the journal for the redacted traceback)")
        return 1, report


def _tick_body(store: SnapshotStore, run: _LazyRun, ledger_path: Path, settings: RunnerSettings, now: datetime,
               clock: Clock, opener: http.Opener | None, pacer: http.Pacer | None, environ: Mapping[str, str] | None,
               key_present: bool, report: dict[str, Any], clear_cost_block: bool) -> tuple[int, dict[str, Any]]:
    cfg = settings.config
    ledger = odds_api.QuotaLedger(ledger_path, cfg.ceiling, clock=clock)
    pilot = PilotState(ledger_path)
    failed = False
    alert = False  # exit 1 only for a new failure, not for every tick of a known one
    notes: list[str] = []
    stamp = iso_z(now)
    if clear_cost_block and pilot.get("cost_block"):
        notes.append(f"cost block cleared by the operator (was: {pilot.get('cost_block')})")
        pilot.set(cost_block=None)

    def move(row: Mapping[str, Any], state: str, reason: str | None = None, **extra: Any) -> None:
        store.record_odds_transition(target_id=row["target_id"], state=state, at_utc=stamp, reason=reason, **extra)

    # 1. A capture interrupted by a crash is never retried: its credits may already be spent.
    for row in store.odds_targets(sport=settings.sport):
        if row["state"] == "CAPTURING":
            move(row, "FAILED", "capture attempt did not complete (process ended mid-call); not retried",
                 slot_id=row["slot_id"])
            notes.append(f"{row['target_id']}: interrupted capture marked FAILED")

    # 2. Discovery (quota-free), at most every discovery_interval.
    discovery: dict[str, Any] = {"state": "NOT_NEEDED"}
    refreshed: tuple[tuple[ScheduledEvent, ...], datetime, datetime] | None = None
    latest = store.latest_snapshot(source=SOURCE, kind="events", entity_id=settings.sport)
    last_at = _discovered_at(latest) if latest is not None else None
    # Pace on the last ATTEMPT, successful or not: a failing or rejected discovery is retried
    # at most every discovery_interval, not on every 15-minute tick.
    attempted = parse_utc(pilot.get("last_discovery_attempt_utc"))
    last_try = max((t for t in (last_at, attempted) if t is not None), default=None)
    previous_outcome = pilot.get("discovery_outcome")
    if not key_present:
        discovery = {"state": "SETUP_NEEDED"}
    elif last_try is None or now - last_try >= settings.discovery_interval:
        start, end = now, now + settings.discovery_horizon
        try:
            out = odds_api.fetch_events(settings.sport, ledger=ledger, opener=opener, pacer=pacer,
                                        commence_from=start, commence_to=end, environ=environ)
            sid = odds_api.save_snapshot(store, run_id=run.id(), sport=settings.sport, outcome=out, kind="events",
                                         context={"purpose": "discovery", "tick_utc": stamp,
                                                  "commence_from": iso_z(start), "commence_to": iso_z(end),
                                                  "policy_version": POLICY_VERSION})
            events, problems = odds_api.parse_events(out.payload, sport=settings.sport)
            refreshed = (events, start, end)
            discovery = {"state": "REFRESHED", "snapshot_id": sid, "events": len(events),
                         "problems": list(problems)[:20], "quota_after": out.quota_after.value if out.quota_after else None}
            latest = store.latest_snapshot(source=SOURCE, kind="events", entity_id=settings.sport)
            last_at = _discovered_at(latest)
            pilot.set(last_discovery_attempt_utc=stamp, discovery_outcome="OK", discovery_status=None)
        except (odds_api.OddsApiError, ValueError) as exc:
            status = getattr(exc, "status", None)
            outcome = "KEY_REJECTED" if status in KEY_REJECTED_STATUSES else "FAILED"
            discovery = {"state": outcome, "error_status": status, "error_kind": type(exc).__name__,
                         "next_attempt_after_utc": iso_z(now + settings.discovery_interval)}
            pilot.set(last_discovery_attempt_utc=stamp, discovery_outcome=outcome, discovery_status=status)
            if outcome == "FAILED":
                failed = True
                alert = alert or previous_outcome != "FAILED"
    elif pilot.get("discovery_outcome") in ("FAILED", "KEY_REJECTED"):
        discovery = {"state": f"{pilot.get('discovery_outcome')}_WAITING",
                     "error_status": pilot.get("discovery_status"),
                     "next_attempt_after_utc": iso_z(last_try + settings.discovery_interval)}
    key_rejected = key_present and pilot.get("discovery_outcome") == "KEY_REJECTED"
    events: tuple[ScheduledEvent, ...] = ()
    discovery_snapshot_id = None
    window: tuple[datetime, datetime] | None = None
    if latest is not None:
        events, _, request = _events_from_snapshot(latest, settings.sport)
        discovery_snapshot_id = int(latest["id"])
        discovery["last_discovery_utc"] = iso_z(last_at)
        lo, hi = parse_utc(request.get("commence_from")), parse_utc(request.get("commence_to"))
        window = (lo, hi) if lo is not None and hi is not None else None
    discovery_fresh = last_at is not None and now - last_at <= settings.discovery_max_age
    discovery["fresh"] = discovery_fresh
    report["discovery"] = discovery

    # 3. Supersede targets whose event moved (only on a discovery made this tick).
    superseded = 0
    rows = store.odds_targets(sport=settings.sport)
    if refreshed is not None:
        fresh_events, start, end = refreshed
        by_id = {e.event_id: e for e in fresh_events}
        for row in rows:
            if row["state"] in ODDS_TARGET_FINAL_STATES:
                continue
            ev = by_id.get(row["event_id"])
            old = _parse(row["commence_time_utc"])
            if ev is not None and ev.commence_utc != old:
                move(row, "SUPERSEDED", f"commence time changed from {iso_z(old)} to {iso_z(ev.commence_utc)}")
                superseded += 1

    # 4. Plan new targets that can still be met.
    planned_new = 0
    if discovery_fresh:
        for t in plan_targets(events, cfg.offsets):
            if deadline(t, cfg) <= now:
                continue
            if store.plan_odds_target(target_id=t.target_id, sport=t.sport, event_id=t.event_id,
                                      offset_label=t.offset_label, priority=t.priority,
                                      commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                                      planned_at_utc=stamp, policy_version=POLICY_VERSION, home_team=t.home_team,
                                      away_team=t.away_team, discovery_snapshot_id=discovery_snapshot_id):
                planned_new += 1

    # 5. Expired targets become MISSED, with the state they were stuck in as the reason.
    #    A game missing from a fresh discovery that covered its kickoff (postponed, cancelled,
    #    delisted) is held as DEFERRED EVENT_ABSENT and never paid for; it comes back if the
    #    game reappears. A discovery with no events at all is not trusted for this.
    present = {e.event_id for e in events}
    absence_known = discovery_fresh and window is not None and bool(present)
    missed = absent = 0
    rows = store.odds_targets(sport=settings.sport)
    open_rows = []
    for row in rows:
        if row["state"] in ODDS_TARGET_FINAL_STATES:
            continue
        t = _target(row)
        if is_expired(t, now, cfg):
            why = f"not captured by {iso_z(deadline(t, cfg))}; last state {row['state']}"
            if row["reason"]:
                why += f" ({row['reason']})"
            move(row, "MISSED", why)
            missed += 1
            continue
        was_absent = row["state"] == "DEFERRED" and (row["reason"] or "").startswith("EVENT_ABSENT")
        if absence_known and window[0] <= t.commence_utc <= window[1] and t.event_id not in present:
            if not was_absent:
                move(row, "DEFERRED", f"EVENT_ABSENT: not in the discovery of {discovery.get('last_discovery_utc')} "
                                      "that covered its kickoff (postponed or cancelled?); no paid call")
            absent += 1
            continue
        if was_absent and t.event_id in present:
            move(row, "PLANNED")
        open_rows.append(row)
    report["targets"] = {"planned_new": planned_new, "superseded_now": superseded, "missed_now": missed,
                         "event_absent": absent}

    # 6. Slots and the monthly proof.
    by_target = {r["target_id"]: r for r in open_rows}
    slots = coalesce([_target(r) for r in open_rows], cfg)
    horizon = max((e.commence_utc for e in events), default=None)
    quota = _quota(ledger)
    fireable = [s for s in slots if s.fireable(now, cfg)]
    if fireable and quota.state == "QUOTA_UNKNOWN" and key_present and not key_rejected:
        try:
            rec = odds_api.reconcile_quota(ledger, opener=opener, pacer=pacer, environ=environ)
            notes.append(f"quota reconcile (free): {rec.state.value}")
        except Exception as exc:  # stays QUOTA_UNKNOWN: no paid call
            notes.append(f"quota reconcile (free) failed: {type(exc).__name__}; quota stays unknown")
        quota = _quota(ledger)
    proof = budget(slots, now=now, quota=quota, cost_per_call=settings.cost_per_call, known_horizon=horizon,
                   config=cfg)
    report["budget"] = _proof_summary(proof)
    admitted = set(proof.admitted_slot_ids)
    if proof.state == "PROVEN":
        for slot in slots:
            if slot.slot_id in proof.skipped_slot_ids:
                for m in slot.members:
                    if by_target[m.target_id]["state"] != "SKIPPED_BUDGET":
                        move(by_target[m.target_id], "SKIPPED_BUDGET",
                             f"monthly proof {proof.month}: headroom {proof.headroom} credits kept for "
                             "higher-priority captures", slot_id=slot.slot_id)
            elif slot.slot_id in admitted:
                for m in slot.members:
                    if by_target[m.target_id]["state"] == "SKIPPED_BUDGET":
                        move(by_target[m.target_id], "PLANNED", slot_id=slot.slot_id)

    # 7. At most one paid call: the most important due slot.
    state = "IDLE"
    if fireable:
        slot = min(fireable, key=lambda s: (s.slot_id not in admitted, s.priority, s.due_utc))

        def block(new_state: str, reason: str) -> None:
            for m in slot.members:
                row = by_target[m.target_id]
                if row["state"] != new_state:
                    move(row, new_state, reason, slot_id=slot.slot_id)

        cost_block = pilot.get("cost_block")
        if not key_present:
            state = "SETUP_NEEDED"
            block("SETUP_NEEDED", "no key installed; nothing sent")
        elif key_rejected:
            state = "KEY_REJECTED"
            block("SETUP_NEEDED", f"KEY_REJECTED: the provider refused the key (HTTP {pilot.get('discovery_status')}); "
                                  "nothing sent until a discovery succeeds")
        elif cost_block:
            state = "COST_BLOCKED"
            block("QUOTA_EXHAUSTED", f"COST_ANOMALY: charged {cost_block.get('charged')} > estimate "
                                     f"{cost_block.get('estimate')}; paid calls stopped until an operator reviews "
                                     "and runs `odds run --clear-cost-block`")
        elif not discovery_fresh:
            state = "DEFERRED"
            block("DEFERRED", f"DISCOVERY_STALE: last discovery {discovery.get('last_discovery_utc')}; no paid call")
        elif proof.state == "QUOTA_UNKNOWN":
            state = "QUOTA_UNKNOWN"
            block("QUOTA_UNKNOWN", "no provider quota reading this month; no paid call")
        elif proof.state == "QUOTA_EXHAUSTED":
            state = "QUOTA_EXHAUSTED"
            block("QUOTA_EXHAUSTED", "; ".join(proof.notes) or "no headroom")
        elif slot.slot_id not in admitted:
            state = "SKIPPED_BUDGET"
        else:
            state, fired, call_failed = _capture(store, ledger, run, settings, slot, by_target, stamp, opener, pacer,
                                                 environ)
            report["fired"] = fired
            report["paid_calls"] = fired.get("paid_calls", 0)
            if fired.get("error_status") in KEY_REJECTED_STATUSES:
                pilot.set(discovery_outcome="KEY_REJECTED", discovery_status=fired["error_status"])
            credits = fired.get("credits_last")
            if isinstance(credits, int) and credits > settings.cost_per_call:
                # The provider charged more than the documented formula: stop paying until reviewed.
                pilot.set(cost_block={"at_utc": stamp, "charged": credits, "estimate": settings.cost_per_call,
                                      "slot_id": slot.slot_id})
                state = "COST_ANOMALY"
                call_failed = True
            failed = failed or call_failed
            alert = alert or call_failed
    if not key_present and state == "IDLE":
        state = "SETUP_NEEDED"
        report["detail"] = _setup_text()
    if key_rejected and state == "IDLE":
        state = "KEY_REJECTED"
    report["state"] = "FAILED" if failed and state in ("IDLE", "FAILED") else state
    report["targets"]["by_state"] = _counts(store.odds_targets(sport=settings.sport))
    report["next_slot"] = _next_slot(slots, now, cfg)
    if pilot.get("cost_block"):
        report["cost_block"] = pilot.get("cost_block")
    if notes:
        report["notes"] = notes
    run.finish(failed)
    return (1 if alert else 0), report


def _capture(store: SnapshotStore, ledger: odds_api.QuotaLedger, run: _LazyRun, settings: RunnerSettings,
             slot: Slot, by_target: Mapping[str, Mapping[str, Any]], stamp: str, opener: http.Opener | None,
             pacer: http.Pacer | None, environ: Mapping[str, str] | None) -> tuple[str, dict[str, Any], bool]:
    """Exactly one fetch_odds call for one slot. Returns (state, report, failed)."""
    members = slot.members
    for m in members:
        store.record_odds_transition(target_id=m.target_id, state="CAPTURING", at_utc=stamp, slot_id=slot.slot_id)
    fired: dict[str, Any] = {"slot_id": slot.slot_id, "due_utc": iso_z(slot.due_utc), "priority": slot.priority,
                             "targets": len(members), "events": len(slot.event_ids),
                             "commence_from": iso_z(slot.commence_from), "commence_to": iso_z(slot.commence_to),
                             "paid_calls": 0}

    def finish(state: str, reason: str | None, **extra: Any) -> None:
        for m in members:
            store.record_odds_transition(target_id=m.target_id, state=state, at_utc=stamp, reason=reason,
                                         slot_id=slot.slot_id, **extra)

    try:
        out = odds_api.fetch_odds(settings.sport, list(settings.markets), ledger=ledger, regions=list(settings.regions),
                                  odds_format=settings.odds_format, opener=opener, pacer=pacer, environ=environ,
                                  commence_from=slot.commence_from, commence_to=slot.commence_to)
    except odds_api.OddsApiError as exc:
        fired["paid_calls"] = 1  # it may have reached the provider; the reservation is kept
        reason = f"paid call failed (not retried): {exc}"
        if exc.fetch is not None:  # charged but undecodable: keep the exact bytes as evidence
            doc_id, digest, _ = store.save_document(run_id=run.id(), source_id=odds_api.SOURCE_ID,
                                                    doc_type="odds_undecodable_response", fetch=exc.fetch)
            fired["raw_document_id"] = doc_id
            reason += f"; raw response kept as document {doc_id} (sha256 {digest})"
        finish("FAILED", reason)
        fired["error_status"] = exc.status  # the redacted reason is in the target transitions
        return "FAILED", fired, True
    if out.state is not odds_api.QuotaState.READY:
        finish(out.state.value, f"refused before sending: {out.detail}")
        fired["refused"] = out.state.value
        return out.state.value, fired, False
    fired["paid_calls"] = 1
    headers = odds_api.parse_quota_headers(out.fetch.response_headers) if out.fetch else None
    credits = headers.last if headers is not None else None
    try:
        context = {"purpose": "capture", "policy_version": POLICY_VERSION, "slot_id": slot.slot_id,
                   "slot_due_utc": iso_z(slot.due_utc), "markets": list(settings.markets),
                   "regions": list(settings.regions), "odds_format": settings.odds_format,
                   "commence_from": iso_z(slot.commence_from), "commence_to": iso_z(slot.commence_to),
                   "targets": [{"target_id": m.target_id, "event_id": m.event_id, "offset": m.offset_label,
                                "target_utc": iso_z(m.target_utc)} for m in members]}
        sid = odds_api.save_snapshot(store, run_id=run.id(), sport=settings.sport, outcome=out, context=context)
        received = out.fetch.received_at_utc
        parsed = odds_api.parse_odds(out.payload, odds_format=settings.odds_format, received_at_utc=received,
                                     evidence_id=str(sid))
        cov = odds_api.coverage(parsed, requested_markets=list(settings.markets))
    except Exception as exc:  # the call was paid for: record it, never retry it
        reason = odds_api.redact_text(f"fetched but not stored: {type(exc).__name__}: {exc}")
        finish("FAILED", reason)
        fired["error_kind"] = type(exc).__name__
        return "FAILED", fired, True
    received_dt = _parse(received)
    for m in members:
        detail = _event_coverage(parsed, m.event_id, settings.markets)
        detail.update(offset=m.offset_label, target_utc=iso_z(m.target_utc),
                      deviation_minutes=round((received_dt - m.target_utc).total_seconds() / 60, 1),
                      lead_minutes=round((m.commence_utc - received_dt).total_seconds() / 60, 1),
                      parse_problems=len(parsed.problems))
        store.record_odds_transition(target_id=m.target_id, state="CAPTURED", at_utc=stamp, slot_id=slot.slot_id,
                                     snapshot_id=sid, captured_at_utc=received, credits_last=credits, detail=detail)
    fired.update(snapshot_id=sid, credits_last=credits, received_at_utc=received,
                 quota_after=out.quota_after.value if out.quota_after else None,
                 bookmakers=sorted({o.bookmaker for o in parsed.offers}),
                 coverage=[{"scope": c.scope, "key": c.key, "status": c.status.value} for c in cov],
                 events_in_response=len(parsed.events), parse_problems=len(parsed.problems))
    return "CAPTURED", fired, False


def _proof_summary(proof: BudgetProof) -> dict[str, Any]:
    return {"state": proof.state, "month": proof.month, "spent": proof.spent, "headroom": proof.headroom,
            "provider_remaining": proof.provider_remaining, "ceiling": proof.ceiling,
            "worst_case_month_credits": proof.worst_case_month_credits,
            "expected_month_credits": proof.expected_month_credits,
            "admitted_slots": len(proof.admitted_slot_ids), "skipped_slots": len(proof.skipped_slot_ids)}


def _next_slot(slots: Sequence[Slot], now: datetime, cfg: PilotConfig) -> dict[str, Any] | None:
    upcoming = [s for s in slots if s.due_utc - cfg.early_tolerance > now]
    if not upcoming:
        return None
    s = min(upcoming, key=lambda x: x.due_utc)
    return {"slot_id": s.slot_id, "due_utc": iso_z(s.due_utc), "due_et": _et_text(s.due_utc), "priority": s.priority,
            "targets": len(s.members)}


# --------------------------------------------------------------------------- plan (read-only)


def plan(db_path: str | Path, ledger_path: str | Path, settings: RunnerSettings = RunnerSettings(), *,
         offline: bool = False, clock: Clock = _real_clock, opener: http.Opener | None = None,
         pacer: http.Pacer | None = None, environ: Mapping[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    """Enumerate the schedule and prove the month's credits. Never a paid call; never writes the
    evidence store. Online it makes free calls only (events, and the sports list if the quota
    is still unknown), which reconcile the quota ledger. Offline it reads the latest stored
    discovery and the ledger file as they are."""
    now = clock()
    cfg = settings.config
    db_path, ledger_path = Path(db_path), Path(ledger_path)
    report: dict[str, Any] = {"command": "odds plan", "now_utc": iso_z(now), "now_et": _et_text(now),
                              "sport": settings.sport, "markets": list(settings.markets),
                              "regions": list(settings.regions), "cost_per_call": settings.cost_per_call,
                              "policy_version": POLICY_VERSION, "offline": offline, "paid_calls": 0,
                              "offsets": [o.label for o in cfg.offsets],
                              "merge_window_minutes": cfg.merge_window.total_seconds() / 60,
                              "assumption": {"name": cfg.assumption.name,
                                             "max_groups_per_week": cfg.assumption.max_groups_per_week,
                                             "max_groups_by_weekday_mon_to_sun": list(cfg.assumption.max_groups_by_weekday),
                                             "expected_groups_per_week": cfg.assumption.expected_groups_per_week}}
    try:
        store = SnapshotStore.open_readonly(db_path) if db_path.is_file() else None
    except ReadOnlyStoreError as exc:
        report.update(state="STORE_UNREADABLE", detail=str(exc))
        return 1, report
    ledger = odds_api.QuotaLedger(ledger_path, cfg.ceiling, clock=clock)
    if offline:
        if store is None:
            report.update(state="NO_STORE", detail=f"{db_path} does not exist; nothing discovered yet")
            return 1, report
        row = store.latest_snapshot(source=SOURCE, kind="events", entity_id=settings.sport)
        if row is None:
            report.update(state="NO_DISCOVERY", detail="no stored events discovery; run `odds plan` online or a tick")
            return 1, report
        events, problems, _ = _events_from_snapshot(row, settings.sport)
        report["discovery"] = {"source": "stored", "snapshot_id": int(row["id"]), "fetched_at_utc": row["fetched_at_utc"],
                               "events": len(events), "problems": list(problems)[:20]}
        quota = _quota(ledger) if ledger_path.exists() else QuotaReading("QUOTA_UNKNOWN")
    else:
        if odds_api.load_key(environ) is None:
            report.update(state="SETUP_NEEDED", detail=_setup_text())
            return 0, report
        start, end = now, now + settings.discovery_horizon
        try:
            out = odds_api.fetch_events(settings.sport, ledger=ledger, opener=opener, pacer=pacer,
                                        commence_from=start, commence_to=end, environ=environ)
        except (odds_api.OddsApiError, ValueError) as exc:
            report.update(state="DISCOVERY_FAILED", error_status=getattr(exc, "status", None), error_kind=type(exc).__name__)
            return 1, report
        events, problems = odds_api.parse_events(out.payload, sport=settings.sport)
        report["discovery"] = {"source": "live (quota-free events endpoint)", "events": len(events),
                               "problems": list(problems)[:20]}
        if ledger.state() is odds_api.QuotaState.QUOTA_UNKNOWN:
            rec = odds_api.reconcile_quota(ledger, opener=opener, pacer=pacer, environ=environ)
            report["discovery"]["quota_reconcile"] = rec.state.value
        quota = _quota(ledger)

    targets = [t for t in plan_targets(events, cfg.offsets) if deadline(t, cfg) > now]
    recorded: dict[str, str] = {}
    if store is not None:
        rows = store.odds_targets(sport=settings.sport)
        recorded = {r["target_id"]: r["state"] for r in rows}
        report["recorded_targets"] = _counts(rows)
        report["recent_missed"] = [{"target_id": r["target_id"], "reason": r["reason"]} for r in rows
                                   if r["state"] == "MISSED"][-10:]
        targets = [t for t in targets if recorded.get(t.target_id) not in ODDS_TARGET_FINAL_STATES]
    slots = coalesce(targets, cfg)
    horizon = max((e.commence_utc for e in events), default=None)
    proof = budget(slots, now=now, quota=quota, cost_per_call=settings.cost_per_call, known_horizon=horizon, config=cfg)
    _, month_end = month_bounds(now)
    projection = budget([s for s in slots if s.due_utc >= month_end], now=month_end,
                        quota=QuotaReading("READY", local_used=0, provider_used=0,
                                           provider_remaining=odds_api.FREE_TIER_MONTHLY_CREDITS),
                        cost_per_call=settings.cost_per_call, known_horizon=horizon, config=cfg)
    admitted = set(proof.admitted_slot_ids) | set(projection.admitted_slot_ids)
    report["schedule"] = [{"event_id": e.event_id, "commence_utc": iso_z(e.commence_utc),
                           "commence_et": _et_text(e.commence_utc), "away": e.away_team, "home": e.home_team}
                          for e in events]
    report["slots"] = [{"slot_id": s.slot_id, "due_utc": iso_z(s.due_utc), "due_et": _et_text(s.due_utc),
                        "priority": s.priority, "offsets": sorted({m.offset_label for m in s.members}),
                        "events": len(s.event_ids), "targets": len(s.members),
                        "shifted_from_quiet_window": any(effective_due(m, cfg) != m.target_utc for m in s.members),
                        "month": s.due_utc.strftime("%Y-%m"),
                        "admitted": s.slot_id in admitted} for s in slots]
    report["budget"] = proof.to_dict()
    report["projection_next_month"] = projection.to_dict() | {
        "assumption_note": "a fresh month: 0 used and the free allowance remaining; the first reconcile decides"}
    report["state"] = proof.state
    report["verdict"] = _verdict(proof)
    return 0, report


def _verdict(proof: BudgetProof) -> str:
    if proof.state == "QUOTA_UNKNOWN":
        return "NOT PROVEN: no provider quota reading; reconcile (free) before enabling"
    if proof.state != "PROVEN":
        return f"NOT PROVEN: {proof.state}"
    return (f"PROVEN for {proof.month}: worst case {proof.worst_case_month_credits} <= ceiling {proof.ceiling} and "
            f"{proof.worst_case_month_credits - proof.spent} still to commit <= provider remaining "
            f"{proof.provider_remaining} - outstanding {proof.outstanding}; expected {proof.expected_month_credits}")


# --------------------------------------------------------------------------- smoke (one live read)


def smoke(db_path: str | Path, ledger_path: str | Path, settings: RunnerSettings = RunnerSettings(), *,
          clock: Clock = _real_clock, opener: http.Opener | None = None, pacer: http.Pacer | None = None,
          environ: Mapping[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    """Exactly one bounded paid read for activation, after a free quota reconcile. Refuses when
    the quota is unknown or insufficient. Records exactly which books and markets came back."""
    now = clock()
    cfg = settings.config
    report: dict[str, Any] = {"command": "odds smoke", "now_utc": iso_z(now), "sport": settings.sport,
                              "markets": list(settings.markets), "regions": list(settings.regions), "paid_calls": 0}
    if odds_api.load_key(environ) is None:
        report.update(state="SETUP_NEEDED", detail=_setup_text())
        return 0, report
    if in_quiet_window(now, cfg):
        report.update(state="DEFERRED_CAPTURE_WINDOW", detail="inside 17:40-18:35 America/New_York: nothing sent; retry after 18:35 ET")
        return 1, report
    ledger = odds_api.QuotaLedger(ledger_path, cfg.ceiling, clock=clock)
    rec = odds_api.reconcile_quota(ledger, opener=opener, pacer=pacer, environ=environ)
    before = ledger.snapshot().get("last_headers") or {}
    report["quota_before"] = {k: before.get(k) for k in ("remaining", "used")} if before else None
    if rec.state is not odds_api.QuotaState.READY:
        report.update(state=rec.state.value, detail="refused: the quota is unknown or insufficient; nothing sent")
        return 1, report
    store = SnapshotStore(db_path)
    run = _LazyRun(store)
    start, end = now, now + settings.smoke_horizon
    try:
        out = odds_api.fetch_odds(settings.sport, list(settings.markets), ledger=ledger, regions=list(settings.regions),
                                  odds_format=settings.odds_format, opener=opener, pacer=pacer, environ=environ,
                                  commence_from=start, commence_to=end)
    except odds_api.OddsApiError as exc:
        report.update(state="FAILED", error_status=exc.status, paid_calls=1,
                      detail="the call failed; its reservation is kept (the quota ledger holds the redacted reason)")
        return 1, report
    if out.state is not odds_api.QuotaState.READY:
        report.update(state=out.state.value, detail="refused before sending by the quota ledger")
        return 1, report
    report["paid_calls"] = 1
    sid = odds_api.save_snapshot(store, run_id=run.id(), sport=settings.sport, outcome=out,
                                 context={"purpose": "smoke", "markets": list(settings.markets),
                                          "regions": list(settings.regions), "odds_format": settings.odds_format,
                                          "commence_from": iso_z(start), "commence_to": iso_z(end)})
    run.finish(False)
    parsed = odds_api.parse_odds(out.payload, odds_format=settings.odds_format,
                                 received_at_utc=out.fetch.received_at_utc, evidence_id=str(sid))
    headers = odds_api.parse_quota_headers(out.fetch.response_headers)
    # Counts, books and markets only: no URL, no error text, nothing that could carry the key.
    report.update(state="CAPTURED", snapshot_id=sid, received_at_utc=out.fetch.received_at_utc,
                  credits_last=headers.last if headers else None,
                  quota_after={"remaining": headers.remaining, "used": headers.used} if headers else None,
                  events=len(parsed.events), offers=len(parsed.offers),
                  bookmakers=sorted({o.bookmaker for o in parsed.offers}),
                  markets_returned=sorted({o.market_key for o in parsed.offers}),
                  coverage=[{"scope": c.scope, "key": c.key, "status": c.status.value}
                            for c in odds_api.coverage(parsed, requested_markets=list(settings.markets))],
                  parse_problems=len(parsed.problems))
    return 0, report
