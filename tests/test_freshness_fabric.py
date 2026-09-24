"""Freshness Fabric v1 (ADR 0031): providers, parity with the canonical schedulers, the supervisor,
the status artifact and the systemd units. Deterministic fixtures; zero network."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import cli, forward, odds_schedule
from edge_lab import freshness_fabric as ff
from edge_lab import price_observations as po
from edge_lab.freshness import (
    AcquisitionMode,
    FabricContext,
    FabricProvider,
    Freshness,
    ScheduleState,
    SourceFreshness,
    SourceHealth,
    SourcePolicy,
    iso_z,
)
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "vps" / "systemd"
INSTALL = (ROOT / "deploy" / "vps" / "install.sh").read_text(encoding="utf-8")
D = date(2026, 9, 25)  # target date: decision 2026-09-24 18:00 EDT = 22:00Z


def z(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def unit(name: str) -> dict[tuple[str, str], list[str]]:
    values: dict[tuple[str, str], list[str]] = {}
    section = None
    for line in (UNITS / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault((section, key), []).append(value)
    return values


def by_id(records):
    return {r.source_id: r for r in records}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "db" / "edge_lab.sqlite3"
    SnapshotStore(path)
    return path


def capture(store, phase, target=D, *, status="complete", at="2026-09-24T21:45:30Z", links=None, decision_id=None):
    run = f"run-{phase}-{uuid.uuid4().hex[:6]}"
    store.start_run(run)
    return store.record_forward_capture(
        run_id=run, experiment="EXP-001", phase=phase, mode="live", target_date=target.isoformat(),
        event_ticker=forward.event_ticker_for(target), started_at_utc=at, completed_at_utc=at,
        window_start_utc=at, window_end_utc=at, status=status, reasons=[] if status == "complete" else ["why"],
        links=links or {}, decision_capture_id=decision_id)


DECISION_LINKS = {"event_snapshot": 1, "market_snapshots": [], "books": {
    "KXHIGHNY-26SEP25-B67.5": {"snapshot_id": 2, "fetched_at_utc": "2026-09-24T21:55:10+00:00"},
    "KXHIGHNY-26SEP25-B69.5": {"snapshot_id": 3, "fetched_at_utc": "2026-09-24T21:55:40+00:00"}}}


# =========================================================================== timer contracts (pinned to the units)


def test_every_fabric_timer_constant_matches_its_unit_file():
    for phase, name in ff.FORWARD_TIMERS.items():
        assert unit(name)[("Timer", "OnCalendar")] == [f"*-*-* {ff.FORWARD_TICKS_ET[phase]:%H:%M:%S} America/New_York"]
    assert unit("edgelab-settlement.timer")[("Timer", "OnCalendar")] == [
        f"*-*-* {t:%H:%M:%S} America/New_York" for t in ff.SETTLEMENT_TICKS_ET]
    assert unit("edgelab-shadow.timer")[("Timer", "OnCalendar")] == [f"*-*-* {ff.SHADOW_TICK_ET:%H:%M:%S} America/New_York"]
    assert unit("edgelab-backup.timer")[("Timer", "OnCalendar")] == [f"*-*-* {ff.BACKUP_TICK_UTC:%H:%M:%S} UTC"]
    assert unit("edgelab-observe.timer")[("Timer", "OnCalendar")] == ["*-*-* *:05/15:00 America/New_York"]
    assert ff.OBSERVE_TICK_MINUTES == tuple(range(5, 60, 15))
    assert unit("edgelab-odds.timer")[("Timer", "OnCalendar")] == ["*-*-* *:00/15:00"]
    assert ff.ODDS_TICK_MINUTES == tuple(range(0, 60, 15))
    assert unit("edgelab-freshness.timer")[("Timer", "OnCalendar")] == ["*-*-* *:01/5:00"]
    assert ff.SUPERVISOR_TICK_MINUTES == tuple(range(1, 60, 5))


def _timeout(name: str) -> timedelta:
    value = unit(name)[("Service", "TimeoutStartSec")][0]
    m = re.fullmatch(r"(\d+)(min|s)", value)
    return timedelta(minutes=int(m.group(1))) if m.group(2) == "min" else timedelta(seconds=int(m.group(1)))


def test_grace_periods_cover_each_units_timeout():
    assert ff.STATUS_GRACE > _timeout("edgelab-status.service")
    assert ff.DAILY_RUN_GRACE > _timeout("edgelab-settlement.service")
    assert ff.DAILY_RUN_GRACE > _timeout("edgelab-shadow.service")
    assert ff.BACKUP_GRACE > _timeout("edgelab-backup.service")


def test_every_installed_timer_is_explained_by_a_registered_source():
    """The v1 goal: one abstraction that can explain every existing schedule."""
    owners = " ".join(p.schedule_owner for entry in ff.REGISTRY for p in entry.policies)
    for timer in sorted(p.name for p in UNITS.glob("*.timer")):
        assert timer in owners, f"{timer} has no fabric source"
    for entry in ff.REGISTRY:
        for p in entry.policies:
            assert p.mode is AcquisitionMode.EXTERNAL_SCHEDULE  # v1 observes; it never schedules


def test_the_supervisor_tick_grid_is_staggered_and_clear_of_the_close_tick():
    others = set(ff.ODDS_TICK_MINUTES) | set(ff.OBSERVE_TICK_MINUTES) | {0, 5, 15, 30, 40, 45, 55}
    assert not set(ff.SUPERVISOR_TICK_MINUTES) & others
    # The close capture runs from the 04:57:45 UTC tick until its confirming read 5 s after the
    # 05:00:00Z close: no supervisor run (at most TimeoutStartSec long) may overlap that span.
    close_tick = datetime.combine(D, po.CLOSE_TICK_UTC, UTC)
    close_done = datetime.combine(D, ff.dtime(5, 0, 30), UTC)
    timeout = _timeout("edgelab-freshness.service")
    for start in (close_tick.replace(minute=0, second=0) + timedelta(minutes=m + 60 * h)
                  for h in (0, 1) for m in ff.SUPERVISOR_TICK_MINUTES):
        assert start + timeout < close_tick or start >= close_done, start


# =========================================================================== the supervisor unit


def test_freshness_unit_is_network_free_small_and_writes_only_the_status_dir():
    s = unit("edgelab-freshness.service")
    assert s[("Service", "Type")] == ["oneshot"] and s[("Service", "User")] == ["edgelab"]
    assert s[("Service", "Slice")] == ["edgelab.slice"]
    assert s[("Service", "RestrictAddressFamilies")] == ["AF_UNIX"] and s[("Service", "IPAddressDeny")] == ["any"]
    assert s[("Service", "ReadWritePaths")] == ["/var/lib/market-edge-lab-status"]
    assert s[("Service", "ProtectSystem")] == ["strict"] and s[("Service", "NoNewPrivileges")] == ["yes"]
    assert s[("Service", "MemoryMax")] == ["128M"] and s[("Service", "CPUQuota")] == ["10%"]
    assert s[("Service", "TimeoutStartSec")] == ["60s"] and s[("Service", "UMask")] == ["0022"]
    assert ("Service", "EnvironmentFile") not in s  # no secrets, no settings
    assert ("Unit", "OnFailure") not in s and ("Unit", "OnSuccess") not in s  # ADR 0031: no alert spam
    # The same hardening block as the observation collector, except the network.
    observe = unit("edgelab-observe.service")
    for key in ("NoNewPrivileges", "PrivateTmp", "PrivateDevices", "ProtectSystem", "ProtectHome",
                "ProtectKernelTunables", "ProtectKernelModules", "ProtectKernelLogs", "ProtectControlGroups",
                "RestrictSUIDSGID", "RestrictNamespaces", "LockPersonality"):
        assert s[("Service", key)] == observe[("Service", key)], key
    t = unit("edgelab-freshness.timer")
    assert t[("Timer", "Persistent")] == ["false"] and t[("Timer", "Unit")] == ["edgelab-freshness.service"]
    assert t[("Timer", "AccuracySec")] == ["5s"]


def test_freshness_unit_reads_the_production_paths_the_other_units_write():
    args = unit("edgelab-freshness.service")[("Service", "ExecStart")][0].split()
    assert args[:4] == ["/opt/market-edge-lab/venv/bin/python", "-m", "edge_lab.cli", "freshness"]
    assert args[4] == "status" and "--write" in args

    def arg(name, argv=args):
        return argv[argv.index(name) + 1]

    odds = unit("edgelab-odds.service")[("Service", "ExecStart")][0].split()
    settle = unit("edgelab-settlement.service")[("Service", "ExecStart")][0].split()
    assert arg("--db") == arg("--db", odds) == arg("--db", settle)
    assert arg("--ledger") == arg("--ledger", settle)
    assert arg("--odds-ledger") == arg("--ledger", odds)
    assert Path(arg("--odds-ledger")).name == ff.ODDS_LEDGER_FILE
    assert arg("--status-dir") == arg("--status-dir", settle) == "/var/lib/market-edge-lab-status"
    backup = (UNITS / "edgelab-backup.service").read_text(encoding="utf-8")
    assert f"--out {arg('--backups-dir')} " in backup and f"--out {arg('--backups-dir')}/ledger " in backup


def test_installer_installs_it_as_a_core_timer():
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    assert "edgelab-freshness" in units
    assert "SEPARATELY_ACTIVATED=edgelab-odds" in INSTALL  # so it lands in CORE_TIMERS


# =========================================================================== forward weather parity


def _forward(db, now):
    return by_id(ff.forward_weather(FabricContext(db=db), now))


# Every minute through the pfm, decision and recheck windows (21:30-22:11Z), plus points either side.
GRID = [z("2026-09-24T21:25:00Z") + timedelta(minutes=m) for m in range(0, 55)] + [
    z("2026-09-24T12:00:00Z"), z("2026-09-24T21:54:59Z"), z("2026-09-24T21:59:31Z"), z("2026-09-24T23:30:00Z")]


@pytest.mark.parametrize("setup", ["empty", "pfm_done", "decision_done", "all_done"])
def test_forward_due_equals_the_canonical_gate_at_every_minute(db, setup):
    store = SnapshotStore(db)
    if setup in ("pfm_done", "all_done"):
        capture(store, "pfm", at="2026-09-24T21:45:30Z")
    if setup in ("decision_done", "all_done"):
        did = capture(store, "decision", at="2026-09-24T21:55:50Z", links=DECISION_LINKS)
        if setup == "all_done":
            capture(store, "recheck", at="2026-09-24T22:06:00Z", decision_id=did)
    ro = SnapshotStore.open_readonly(db)
    for now in GRID:
        records = _forward(db, now)
        for phase in ("pfm", "decision", "recheck"):
            rec = records[f"exp001.forward.{phase}"]
            assert (rec.schedule_state is ScheduleState.DUE) == forward.would_proceed(phase, ro, now), (phase, now)
            assert rec.disagreements == (), (phase, now, rec.disagreements)


def test_forward_states_before_during_after_and_next_day(db):
    store = SnapshotStore(db)
    before = _forward(db, z("2026-09-24T20:00:00Z"))["exp001.forward.pfm"]
    assert before.schedule_state is ScheduleState.NOT_DUE and before.next_due == z("2026-09-24T21:45:00Z")
    assert before.health is SourceHealth.UNKNOWN and before.freshness is Freshness.UNKNOWN
    assert before.missed_count == 0 and before.last_success_receipt is None
    missed = _forward(db, z("2026-09-24T22:30:00Z"))["exp001.forward.pfm"]
    assert missed.schedule_state is ScheduleState.MISSED and missed.next_due == z("2026-09-25T21:45:00Z")
    capture(store, "pfm", at="2026-09-24T21:45:30Z")
    done = _forward(db, z("2026-09-24T22:30:00Z"))["exp001.forward.pfm"]
    assert done.schedule_state is ScheduleState.NOT_DUE and done.next_due == z("2026-09-25T21:45:00Z")
    assert done.freshness is Freshness.FRESH and done.health is SourceHealth.OK and done.usable_for_decision
    assert done.receipt_ts == z("2026-09-24T21:45:30Z") and done.missed_count == 0
    later = _forward(db, z("2026-09-26T12:00:00Z"))["exp001.forward.pfm"]  # nothing captured for D=26
    assert later.freshness is Freshness.STALE and later.missed_count == 1 and not later.usable_for_decision
    assert later.recent_misses[0].startswith("2026-09-26: no attempt")  # D=26 was due on the 25th


def test_recheck_waits_for_the_decision_then_is_missed_without_it(db):
    wait = _forward(db, z("2026-09-24T21:50:00Z"))["exp001.forward.recheck"]
    assert wait.schedule_state is ScheduleState.NOT_DUE and "waits for" in wait.why_due
    gone = _forward(db, z("2026-09-24T22:40:00Z"))["exp001.forward.recheck"]
    assert gone.schedule_state is ScheduleState.MISSED


def test_a_failed_capture_is_failing_health_and_a_partial_is_degraded(db):
    store = SnapshotStore(db)
    capture(store, "decision", status="failed", at="2026-09-24T21:55:30Z")
    rec = _forward(db, z("2026-09-24T22:30:00Z"))["exp001.forward.decision"]
    assert rec.health is SourceHealth.FAILING and rec.schedule_state is ScheduleState.MISSED
    assert rec.recent_misses and "failed: why" in rec.recent_misses[-1]
    capture(store, "decision", status="partial", at="2026-09-24T21:56:30Z")
    assert _forward(db, z("2026-09-24T22:30:00Z"))["exp001.forward.decision"].health is SourceHealth.DEGRADED


def test_a_timer_tick_the_gate_would_reject_is_reported_not_hidden(db, monkeypatch):
    monkeypatch.setitem(ff.FORWARD_TICKS_ET, "pfm", ff.dtime(17, 58))  # after the pfm window closes
    rec = _forward(db, z("2026-09-24T20:00:00Z"))["exp001.forward.pfm"]
    assert rec.disagreements and "rejected_out_of_window" in rec.disagreements[0]
    monkeypatch.setitem(ff.FORWARD_TICKS_ET, "decision", ff.dtime(17, 59, 50))  # later than start margin
    assert _forward(db, z("2026-09-24T20:00:00Z"))["exp001.forward.decision"].disagreements


def test_forward_without_a_store_is_unknown_but_knows_the_timer(tmp_path):
    rec = _forward(tmp_path / "missing.sqlite3", z("2026-09-24T20:00:00Z"))["exp001.forward.decision"]
    assert rec.schedule_state is ScheduleState.UNKNOWN and rec.freshness is Freshness.UNKNOWN
    assert rec.next_due == z("2026-09-24T21:55:05Z") and "does not exist" in rec.why_due
    assert not (tmp_path / "missing.sqlite3").exists()  # never created


def test_forward_status_file(tmp_path):
    status = tmp_path / "status"
    status.mkdir()
    ctx = FabricContext(status_dir=status)
    rec = by_id(ff.forward_weather(ctx, z("2026-09-24T20:00:00Z")))["exp001.forward.status"]
    assert rec.health is SourceHealth.UNKNOWN and rec.details["file"] == "MISSING"
    (status / "latest.json").write_text(json.dumps({
        "generated_at_utc": "2026-09-24T22:30:02+00:00", "last_closed_status": "INVALID",
        "last_closed_reasons": ["no complete recheck capture"], "last_closed_target_date": "2026-09-24"}))
    rec = by_id(ff.forward_weather(ctx, z("2026-09-24T23:00:00Z")))["exp001.forward.status"]
    assert rec.schedule_state is ScheduleState.NOT_DUE and rec.next_due == z("2026-09-25T22:30:00Z")
    assert rec.health is SourceHealth.DEGRADED and rec.notes == ("no complete recheck capture",)
    assert rec.freshness is Freshness.FRESH
    late = by_id(ff.forward_weather(ctx, z("2026-09-25T22:45:00Z")))["exp001.forward.status"]
    assert late.schedule_state is ScheduleState.MISSED
    (status / "latest.json").write_text("{not json")
    assert by_id(ff.forward_weather(ctx, z("2026-09-24T23:00:00Z")))["exp001.forward.status"].details["file"] == "CORRUPT"


# =========================================================================== The Odds API parity

SPORT = "americanfootball_nfl"


def plan_odds(store, commence, event_id="ev1"):
    events = [odds_schedule.ScheduledEvent(event_id, SPORT, commence, "Green Bay Packers", "Atlanta Falcons")]
    targets = odds_schedule.plan_targets(events)
    for t in targets:
        store.plan_odds_target(target_id=t.target_id, sport=SPORT, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=odds_schedule.iso_z(t.commence_utc),
                               target_utc=odds_schedule.iso_z(t.target_utc), planned_at_utc="2026-09-20T00:00:00Z",
                               policy_version=odds_schedule.POLICY_VERSION, home_team=t.home_team, away_team=t.away_team)
    return targets


def odds_ctx(db):
    return FabricContext(db=db, odds_ledger=db.with_name(ff.ODDS_LEDGER_FILE))


def canonical_next(targets, now):
    cfg = odds_schedule.PilotConfig()
    dues = [odds_schedule.effective_due(t, cfg) for t in targets if odds_schedule.deadline(t, cfg) > now]
    return min(dues) if dues else None


@pytest.mark.parametrize("now", ["2026-09-25T12:00:00Z", "2026-09-26T21:50:00Z", "2026-09-27T16:10:00Z",
                                 "2026-09-28T00:00:00Z"])
def test_odds_next_due_equals_the_canonical_schedule(db, now):
    # Kickoff 18:00 ET: its T-24h target falls in the quiet window and is moved by effective_due.
    targets = plan_odds(SnapshotStore(db), z("2026-09-27T22:00:00Z"))
    now = z(now)
    rec = by_id(ff.odds_api_pilot(odds_ctx(db), now))["the_odds_api.nfl_odds"]
    assert rec.next_due == canonical_next(targets, now)
    assert rec.disagreements == ()
    assert rec.details["pilot_state"] == "SETUP_NEEDED" and rec.schedule_state is ScheduleState.PAUSED
    assert rec.freshness is Freshness.UNKNOWN and rec.receipt_ts is None and rec.usable_for_decision is False


def _as_active(monkeypatch, **override):
    real = ff.odds_pilot.dashboard_status

    def fake(*args, **kwargs):
        out = real(*args, **kwargs)
        out.update(state="ACTIVE", detail="test", **override)
        return out

    monkeypatch.setattr(ff.odds_pilot, "dashboard_status", fake)


def test_odds_timing_states_when_the_pilot_is_active(db, monkeypatch):
    targets = plan_odds(SnapshotStore(db), z("2026-09-27T17:00:00Z"))
    _as_active(monkeypatch)
    due = canonical_next(targets, z("2026-09-26T00:00:00Z"))  # T-24h: 2026-09-26T17:00Z
    rec = lambda now: by_id(ff.odds_api_pilot(odds_ctx(db), now))["the_odds_api.nfl_odds"]  # noqa: E731
    assert rec(due - timedelta(hours=1)).schedule_state is ScheduleState.NOT_DUE
    assert rec(due - timedelta(minutes=5)).schedule_state is ScheduleState.DUE
    assert rec(z("2026-09-25T21:50:00Z")).schedule_state is ScheduleState.PROTECTED_WINDOW  # 17:50 ET
    assert rec(due).health is SourceHealth.OK


def test_odds_blocks_map_to_schedule_states(db, monkeypatch):
    plan_odds(SnapshotStore(db), z("2026-09-27T17:00:00Z"))
    for state, expected in (("COST_BLOCKED", ScheduleState.BUDGET_BLOCKED), ("QUOTA_EXHAUSTED", ScheduleState.QUOTA_BLOCKED),
                            ("QUOTA_UNKNOWN", ScheduleState.QUOTA_BLOCKED), ("KEY_REJECTED", ScheduleState.PAUSED),
                            ("ERROR", ScheduleState.UNKNOWN)):
        real = ff.odds_pilot.dashboard_status

        def fake(*args, _state=state, _real=real, **kwargs):
            out = _real(*args, **kwargs)
            out["state"] = _state
            return out

        monkeypatch.setattr(ff.odds_pilot, "dashboard_status", fake)
        rec = by_id(ff.odds_api_pilot(odds_ctx(db), z("2026-09-26T00:00:00Z")))["the_odds_api.nfl_odds"]
        assert rec.schedule_state is expected, state
        monkeypatch.setattr(ff.odds_pilot, "dashboard_status", real)


def test_odds_disagreement_is_reported_not_resolved(db, monkeypatch):
    plan_odds(SnapshotStore(db), z("2026-09-27T17:00:00Z"))
    real = ff.odds_pilot.dashboard_status

    def skewed(*args, **kwargs):
        out = real(*args, **kwargs)
        out["next_capture"] = dict(out["next_capture"], due_utc="2026-09-26T18:00:00Z")
        return out

    monkeypatch.setattr(ff.odds_pilot, "dashboard_status", skewed)
    rec = by_id(ff.odds_api_pilot(odds_ctx(db), z("2026-09-26T00:00:00Z")))["the_odds_api.nfl_odds"]
    assert rec.disagreements and "fabric 2026-09-26T17:00:00Z vs odds_pilot.dashboard_status 2026-09-26T18:00:00Z" in rec.disagreements[0]
    assert rec.next_due == z("2026-09-26T18:00:00Z")  # the canonical value is shown; the conflict is flagged


def test_odds_tick_feasibility_uses_the_quiet_window():
    # A slot due 18:05 ET with a 1-minute deadline: the 18:00 tick is quiet, the 18:15 tick is too late.
    assert ff.odds_tick_can_fire(z("2026-09-24T22:05:00Z"), z("2026-09-24T22:06:00Z"), z("2026-09-24T20:00:00Z")) is None
    assert ff.odds_tick_can_fire(z("2026-09-24T19:05:00Z"), z("2026-09-24T19:35:00Z"),
                                 z("2026-09-24T18:00:00Z")) == z("2026-09-24T19:00:00Z")


def test_odds_missed_targets_and_discovery(db, monkeypatch):
    store = SnapshotStore(db)
    targets = plan_odds(store, z("2026-09-27T17:00:00Z"))
    store.record_odds_transition(target_id=targets[0].target_id, state="MISSED", at_utc="2026-09-26T17:31:00Z",
                                 reason="NOT_CAPTURED_BY_DEADLINE")
    state = db.with_name(ff.ODDS_LEDGER_FILE + ".pilot.json")
    state.write_text(json.dumps({"discovery_outcome": "OK", "last_discovery_attempt_utc": "2026-09-26T12:00:00Z"}))
    _as_active(monkeypatch, discovery={"last_success_utc": "2026-09-26T12:00:00Z", "last_attempt_utc": "2026-09-26T12:00:00Z",
                                       "fresh": True, "events": 1, "outcome": "OK"})
    recs = by_id(ff.odds_api_pilot(odds_ctx(db), z("2026-09-26T17:40:00Z")))
    odds = recs["the_odds_api.nfl_odds"]
    assert odds.missed_count == 1 and odds.recent_misses[0].endswith("NOT_CAPTURED_BY_DEADLINE")
    disc = recs["the_odds_api.discovery"]
    assert disc.next_due == z("2026-09-26T18:00:00Z") and disc.schedule_state is ScheduleState.NOT_DUE
    assert disc.freshness is Freshness.FRESH and disc.health is SourceHealth.OK
    # The runner's own rule: a discovery is attempted once `now - last try >= discovery_interval`.
    assert by_id(ff.odds_api_pilot(odds_ctx(db), z("2026-09-26T18:00:00Z")))["the_odds_api.discovery"].schedule_state is ScheduleState.DUE


def test_odds_without_configuration_is_unknown():
    recs = ff.odds_api_pilot(FabricContext(), z("2026-09-26T00:00:00Z"))
    assert [r.schedule_state for r in recs] == [ScheduleState.UNKNOWN, ScheduleState.UNKNOWN]


# =========================================================================== ADR 0030 parity

MARKET = "KXHIGHNY-26SEP25-B67.5"


def custom(at: datetime):
    return po.custom_target(venue="kalshi", native_market_id=MARKET, at=at)


def close_target(close: datetime):
    base = custom(close - po.CLOSE_AIM)
    aim = close - po.CLOSE_AIM
    due, deadline = po._window("close", aim, close)
    return {**base, "phase": "close", "target_id": po.target_id(base["market_id"], "close", aim),
            "due_from_utc": po._iso(due), "deadline_utc": po._iso(deadline), "close_time_utc": po._iso(close)}


def plan_obs(db, targets, now=z("2026-09-24T12:00:00Z")):
    po.plan(SnapshotStore(db), decisions=[], now=now, custom=targets)


def obs(db, now):
    return by_id(ff.price_observations_schedule(FabricContext(db=db), now))


def canonical_status(db, now):
    return po.status(SnapshotStore.open_readonly(db), now=now, systemctl=lambda args: "")


@pytest.mark.parametrize("now", ["2026-09-24T12:30:00Z", "2026-09-24T19:58:00Z", "2026-09-25T04:58:00Z",
                                 "2026-09-25T06:00:00Z"])
def test_observation_next_due_equals_price_observations_status(db, now):
    plan_obs(db, [custom(z("2026-09-24T20:00:00Z")), custom(z("2026-09-25T14:00:00Z")),
                  close_target(z("2026-09-25T05:00:00Z"))])
    now = z(now)
    recs = obs(db, now)
    status = canonical_status(db, now)
    ours = [r.next_due for r in recs.values() if r.next_due is not None]
    theirs = [z(n["due_from_utc"]) for n in status["next_due"]]
    assert (min(ours) if ours else None) == (min(theirs) if theirs else None)
    for rec in recs.values():  # the fabric's per-phase view is the canonical list, split by phase
        assert (rec.next_due is None) or rec.next_due in theirs
    assert recs["price_observations.close"].details["close_tick_alignment"] == status["close_tick_alignment"]["state"]


def test_observation_misses_match_the_canonical_expiry(db):
    plan_obs(db, [custom(z("2026-09-24T13:00:00Z"))])
    po.plan(SnapshotStore(db), decisions=[], now=z("2026-09-24T14:00:00Z"))  # expires the target: MISSED
    rec = obs(db, z("2026-09-24T14:05:00Z"))["price_observations.later"]
    status = canonical_status(db, z("2026-09-24T14:05:00Z"))
    assert rec.missed_count == status["by_phase"]["custom"]["MISSED"] == 1
    assert rec.recent_misses[0].split(":")[0] + ":" in status["recent_misses"][0]["target_id"] + ":"
    assert rec.health is SourceHealth.DEGRADED and rec.schedule_state is ScheduleState.NOT_DUE


def test_observation_states(db):
    plan_obs(db, [custom(z("2026-09-24T20:00:00Z"))])
    assert obs(db, z("2026-09-24T19:30:00Z"))["price_observations.later"].schedule_state is ScheduleState.NOT_DUE
    assert obs(db, z("2026-09-24T19:58:00Z"))["price_observations.later"].schedule_state is ScheduleState.DUE
    # Inside a protected window (16:13-16:30 ET) the observe runner defers.
    assert obs(db, z("2026-09-24T20:20:00Z"))["price_observations.later"].schedule_state is ScheduleState.PROTECTED_WINDOW
    assert obs(db, z("2026-09-24T20:35:00Z"))["price_observations.later"].schedule_state is ScheduleState.MISSED


def test_a_target_no_observe_tick_can_reach_is_reported(db):
    # Due 17:45-18:20 ET: entirely inside the 17:40-18:50 ET protected window.
    plan_obs(db, [custom(z("2026-09-24T21:50:00Z"))])
    rec = obs(db, z("2026-09-24T12:00:00Z"))["price_observations.later"]
    assert rec.disagreements and "no edgelab-observe.timer tick" in rec.disagreements[0]


def test_a_misaligned_close_target_is_a_disagreement(db):
    plan_obs(db, [close_target(z("2026-09-25T06:00:00Z"))])  # the fixed 04:57:45 UTC tick cannot reach it
    now = z("2026-09-24T12:00:00Z")
    rec = obs(db, now)["price_observations.close"]
    assert rec.details["close_tick_alignment"] == "MISALIGNED" == canonical_status(db, now)["close_tick_alignment"]["state"]
    assert rec.disagreements


# =========================================================================== settlement and shadow


def receipt(at: str, *, refresh="skipped", state="PENDING_SETTLEMENT"):
    return {"schema": "edge-lab-shadow-daily-receipt/1", "generated_at_utc": at, "state": state,
            "settlement": {"refresh": {"status": refresh}}, "problems": []}


def write_history(status: Path, receipts, *, pad: int = 0):
    status.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"schema": "x", "generated_at_utc": "2026-09-01T00:00:00Z", "pad": "p" * 500,
                         "settlement": {"refresh": {"status": "not_requested"}}})] * pad
    lines += [json.dumps(r) for r in receipts]
    (status / "shadow_daily_history.jsonl").write_text("\n".join(lines) + "\n")


def settle(tmp_path, now, **ctx):
    return by_id(ff.settlement_and_shadow(FabricContext(status_dir=tmp_path / "status", **ctx), now))


def test_settlement_tick_states(tmp_path):
    write_history(tmp_path / "status", [receipt("2026-09-24T15:15:02+00:00"),
                                        receipt("2026-09-24T22:40:03+00:00", refresh="not_requested")])
    due = settle(tmp_path, z("2026-09-24T20:20:00Z"))["kalshi_settlement.refresh"]  # 16:20 ET, the 16:15 run not seen
    assert due.schedule_state is ScheduleState.DUE and due.next_due == z("2026-09-24T20:15:00Z")
    missed = settle(tmp_path, z("2026-09-24T20:40:00Z"))["kalshi_settlement.refresh"]
    assert missed.schedule_state is ScheduleState.MISSED and missed.next_due == z("2026-09-25T15:15:00Z")
    ok = settle(tmp_path, z("2026-09-24T19:00:00Z"))["kalshi_settlement.refresh"]
    assert ok.schedule_state is ScheduleState.NOT_DUE and ok.health is SourceHealth.OK
    shadow = settle(tmp_path, z("2026-09-24T23:00:00Z"))["exp001.shadow_daily"]
    assert shadow.schedule_state is ScheduleState.NOT_DUE and shadow.next_due == z("2026-09-25T22:40:00Z")
    assert shadow.freshness is Freshness.FRESH and shadow.health is SourceHealth.OK


def test_settlement_lock_busy_failure_and_due_positions(tmp_path):
    write_history(tmp_path / "status", [receipt("2026-09-24T20:15:02+00:00", state="LOCK_BUSY", refresh="not_run")])
    rec = settle(tmp_path, z("2026-09-24T20:20:00Z"), ledger=tmp_path / "missing-ledger.sqlite3")
    assert rec["kalshi_settlement.refresh"].schedule_state is ScheduleState.LOCK_BUSY
    assert rec["kalshi_settlement.refresh"].health is SourceHealth.FAILING
    assert rec["kalshi_settlement.refresh"].details["events_due"] == 0  # no ledger yet: nothing can be due
    assert rec["kalshi_settlement.refresh"].missed_count == 0
    unknown = settle(tmp_path, z("2026-09-24T20:20:00Z"))["kalshi_settlement.refresh"]
    assert unknown.details["events_due"] is None  # ledger not configured: unknown, not zero


def test_settlement_freshness_comes_from_source_health(tmp_path, db):
    store = SnapshotStore(db)
    store.start_run("r1")
    store.record_source_health(run_id="r1", source_id="kalshi_settlement", started_at_utc="2026-09-24T15:15:05+00:00",
                               completed_at_utc="2026-09-24T15:15:09+00:00", duration_ms=4000, status="ok", records=3)
    write_history(tmp_path / "status", [receipt("2026-09-24T15:15:02+00:00", refresh="ok")])
    rec = settle(tmp_path, z("2026-09-24T19:00:00Z"), db=db)["kalshi_settlement.refresh"]
    assert rec.receipt_ts == z("2026-09-24T15:15:09Z") and rec.freshness is Freshness.FRESH


def test_history_tail_is_bounded_and_tolerates_a_cut_line(tmp_path):
    write_history(tmp_path / "status", [receipt("2026-09-24T15:15:02+00:00")], pad=800)  # > 256 KB
    with (tmp_path / "status" / "shadow_daily_history.jsonl").open("a") as f:
        f.write('{"torn": ')
    receipts, bad = ff.read_receipts(tmp_path / "status")
    assert bad == 1 and receipts[-1]["generated_at_utc"] == "2026-09-24T15:15:02+00:00"
    assert len(receipts) < 800


# =========================================================================== backups


def manifest(directory: Path, completed: str):
    bundle = directory / f"edge-backup-{uuid.uuid4().hex[:8]}"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({"completed_at_utc": completed}))


def test_backups(tmp_path):
    backups = tmp_path / "backups"
    manifest(backups, "2026-09-24T04:40:30+00:00")
    manifest(backups / "ledger", "2026-09-23T04:40:40+00:00")
    recs = by_id(ff.backups(FabricContext(backups_dir=backups, ledger=tmp_path / "ledger.sqlite3"), z("2026-09-24T12:00:00Z")))
    assert recs["backup.evidence"].schedule_state is ScheduleState.NOT_DUE
    assert recs["backup.evidence"].freshness is Freshness.FRESH and recs["backup.evidence"].health is SourceHealth.OK
    assert recs["backup.ledger"].schedule_state is ScheduleState.MISSED
    empty = by_id(ff.backups(FabricContext(backups_dir=tmp_path / "none"), z("2026-09-24T12:00:00Z")))
    assert empty["backup.evidence"].health is SourceHealth.UNKNOWN and empty["backup.evidence"].details["bundles"] == "MISSING"


# =========================================================================== the supervisor


def _policy(sid="lane_b.demo"):
    return SourcePolicy(source_id=sid, domain="sports", mode=AcquisitionMode.EXTERNAL_SCHEDULE, description="demo",
                        policy_version="v1", schedule_owner="systemd edgelab-demo.timer")


def test_a_later_lane_registers_a_provider_with_one_entry():
    pol = _policy()

    def provide(ctx, now):
        return [SourceFreshness(policy=pol, as_of=now, freshness=Freshness.UNKNOWN, schedule_state=ScheduleState.NOT_DUE,
                                health=SourceHealth.UNKNOWN, why_due="demo")]

    registry = ff.REGISTRY + (FabricProvider("polymarket_us_nfl", (pol,), provide),)
    records, reports = ff.evaluate(FabricContext(), z("2026-09-24T12:00:00Z"), registry)
    assert by_id(records)["lane_b.demo"].schedule_state is ScheduleState.NOT_DUE
    assert reports[-1] == {"provider": "polymarket_us_nfl", "state": "OK", "problems": []}
    with pytest.raises(ValueError):  # one source, one owner
        ff.evaluate(FabricContext(), z("2026-09-24T12:00:00Z"),
                    registry + (FabricProvider("dup", (ff.POLICY_PFM,), provide),))


def test_a_failing_or_misbehaving_provider_is_isolated_and_reported():
    good, bad = _policy("demo.good"), _policy("demo.bad")
    now = z("2026-09-24T12:00:00Z")

    def boom(ctx, now):
        raise RuntimeError("provider bug")

    def sloppy(ctx, now):
        rec = SourceFreshness(policy=good, as_of=now, freshness=Freshness.UNKNOWN, schedule_state=ScheduleState.DUE,
                              health=SourceHealth.OK, why_due="x")
        other = SourceFreshness(policy=_policy("demo.undeclared"), as_of=now, freshness=Freshness.UNKNOWN,
                                schedule_state=ScheduleState.DUE, health=SourceHealth.OK, why_due="x")
        return [rec, rec, other, "junk"]

    records, reports = ff.evaluate(FabricContext(), now, (FabricProvider("boom", (bad,), boom),
                                                          FabricProvider("sloppy", (good, _policy("demo.omitted")), sloppy)))
    recs = by_id(records)
    assert recs["demo.bad"].schedule_state is ScheduleState.UNKNOWN and "failed (RuntimeError)" in recs["demo.bad"].why_due
    assert recs["demo.good"].schedule_state is ScheduleState.DUE
    assert recs["demo.omitted"].schedule_state is ScheduleState.UNKNOWN and "demo.undeclared" not in recs
    assert reports[0]["state"] == "ERROR" and reports[1]["state"] == "PARTIAL" and len(reports[1]["problems"]) == 4


def populated(tmp_path):
    db = tmp_path / "data" / "db" / "edge_lab.sqlite3"
    store = SnapshotStore(db)
    capture(store, "pfm", at="2026-09-24T21:45:30Z")
    plan_odds(store, z("2026-09-27T17:00:00Z"))
    plan_obs(db, [custom(z("2026-09-25T14:00:00Z")), close_target(z("2026-09-25T05:00:00Z"))])
    status = tmp_path / "status"
    write_history(status, [receipt("2026-09-24T15:15:02+00:00")])
    manifest(tmp_path / "data" / "backups", "2026-09-24T04:40:30+00:00")
    return FabricContext(db=db, ledger=tmp_path / "data" / "ledger" / "shadow_ledger.sqlite3",
                         odds_ledger=db.with_name(ff.ODDS_LEDGER_FILE), status_dir=status,
                         backups_dir=tmp_path / "data" / "backups")


def test_the_artifact_is_written_atomically_bounded_and_current_only(tmp_path):
    ctx = populated(tmp_path)
    doc, text = ff.status(ctx, z("2026-09-24T23:01:00Z"), write=True)
    path = ctx.status_dir / ff.ARTIFACT_NAME
    assert path.read_text(encoding="utf-8") == text and len(text.encode()) <= ff.MAX_ARTIFACT_BYTES
    assert [p.name for p in ctx.status_dir.iterdir() if p.name.endswith(".tmp")] == []
    data = json.loads(text)
    assert data["schema"] == "freshness-fabric-status/1" and data["generated_at_utc"] == "2026-09-24T23:01:00Z"
    assert data["supervisor"]["state"] == "OK" and data["supervisor"]["network"] == "none"
    assert data["supervisor"]["controls_schedules"] is False
    assert len(data["sources"]) == sum(len(e.policies) for e in ff.REGISTRY) == data["summary"]["sources"]
    assert {s["source_id"] for s in data["sources"]} == {p["source_id"] for p in data["policies"]}
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o644
    # The supervisor judges itself from this artifact on the next run.
    again, _ = ff.status(ctx, z("2026-09-24T23:06:00Z"), write=True)
    me = next(s for s in again["sources"] if s["source_id"] == "freshness_fabric.supervisor")
    assert me["freshness"] == "FRESH" and me["last_success_receipt_utc"] == "2026-09-24T23:01:00Z"
    assert sorted(p.name for p in ctx.status_dir.iterdir() if "freshness" in p.name) == [ff.ARTIFACT_NAME]


def test_the_artifact_holds_no_paths_or_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_LAB_ODDS_API_KEY", "SECRET-KEY-0123456789")
    monkeypatch.setenv("EDGE_LAB_ALERT_URL", "https://ntfy.sh/SECRET-TOPIC-abcdef")
    ctx = populated(tmp_path)
    _, text = ff.status(ctx, z("2026-09-24T23:01:00Z"))
    assert "SECRET" not in text and str(tmp_path) not in text and "secrets.env" not in text.replace(
        "/etc/market-edge-lab/secrets.env", "")


def test_a_huge_provider_output_is_clipped_to_the_bound(tmp_path):
    pol = _policy()

    def huge(ctx, now):
        return [SourceFreshness(policy=pol, as_of=now, freshness=Freshness.UNKNOWN, schedule_state=ScheduleState.DUE,
                                health=SourceHealth.OK, why_due="w" * 10_000, notes=tuple("n" * 5000 for _ in range(500)),
                                details={f"k{i}": "v" * 5000 for i in range(500)})]

    doc = ff.build_status(FabricContext(), z("2026-09-24T12:00:00Z"), (FabricProvider("huge", (pol,), huge),))
    text = ff.render(doc)
    assert len(text.encode()) <= ff.MAX_ARTIFACT_BYTES
    src = json.loads(text)["sources"][0]
    assert len(src["why_due"]) <= ff.MAX_TEXT and len(src["notes"]) == ff.MAX_ITEMS + 1
    assert len(src["details"]) <= ff.MAX_DETAIL_KEYS


def test_inside_a_protected_window_the_write_opens_no_store_and_carries_the_last_evaluation(tmp_path, monkeypatch):
    ctx = populated(tmp_path)
    ff.status(ctx, z("2026-09-24T21:30:00Z"), write=True)  # 17:30 ET: evaluated

    def refuse(*args, **kwargs):
        raise AssertionError("no store may be opened inside a protected window")

    monkeypatch.setattr(ff.SnapshotStore, "open_readonly", refuse)
    doc, text = ff.status(ctx, z("2026-09-24T21:46:00Z"), write=True)  # 17:46 ET
    assert doc["supervisor"]["state"] == "DEFERRED_PROTECTED_WINDOW"
    assert doc["supervisor"]["deferred"]["window"] == "exp001_capture_window_and_shadow_run"
    assert doc["generated_at_utc"] == "2026-09-24T21:46:00Z" and doc["sources_evaluated_at_utc"] == "2026-09-24T21:30:00Z"
    assert len(doc["sources"]) == sum(len(e.policies) for e in ff.REGISTRY)
    fresh = FabricContext(status_dir=tmp_path / "empty-status")
    first, _ = ff.status(fresh, z("2026-09-24T21:46:00Z"), write=True)
    assert first["sources"] == [] and first["supervisor"]["problems"]


def test_an_operator_read_evaluates_even_inside_a_protected_window(tmp_path):
    doc, _ = ff.status(populated(tmp_path), z("2026-09-24T21:46:00Z"))
    assert doc["supervisor"]["state"] == "OK" and doc["sources"]


def test_the_supervisor_is_network_free_and_changes_no_store(tmp_path, monkeypatch):
    ctx = populated(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    import gc
    import sqlite3

    gc.collect()
    conn = sqlite3.connect(ctx.db)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode = DELETE")  # as tests/test_readonly_stores.py: no -wal/-shm to compare
    conn.close()
    before = hashlib.sha256(ctx.db.read_bytes()).hexdigest()
    files = sorted(p.name for p in ctx.db.parent.iterdir())
    doc, _ = ff.status(ctx, z("2026-09-24T23:01:00Z"), write=True)
    assert doc["supervisor"]["state"] == "OK"
    gc.collect()
    assert hashlib.sha256(ctx.db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in ctx.db.parent.iterdir()) == files  # no ledger, pilot state or lock created
    assert not ctx.ledger.exists()


def test_cli(tmp_path, capsys):
    ctx = populated(tmp_path)
    argv = ["freshness", "status", "--db", str(ctx.db), "--status-dir", str(ctx.status_dir), "--now",
            "2026-09-24T23:01:00Z", "--backups-dir", str(ctx.backups_dir)]
    assert cli.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema"] == ff.SCHEMA and not (ctx.status_dir / ff.ARTIFACT_NAME).exists()
    assert cli.main(argv + ["--write"]) == 0
    assert json.loads((ctx.status_dir / ff.ARTIFACT_NAME).read_text())["generated_at_utc"] == "2026-09-24T23:01:00Z"
    line = capsys.readouterr().out  # the timer's journal line: one short summary, not the document
    assert line.count("\n") == 1 and len(line) < 600 and json.loads(line)["written"] == ff.ARTIFACT_NAME
    assert cli.main(["freshness", "status", "--write", "--db", str(ctx.db)]) == 2
    assert cli.main(["freshness", "status", "--now", "2026-09-24T23:01:00", "--db", str(ctx.db)]) == 2  # naive
    missing = tmp_path / "nowhere" / "edge_lab.sqlite3"
    assert cli.main(["freshness", "status", "--db", str(missing), "--now", "2026-09-24T23:01:00Z"]) == 0
    assert not missing.parent.exists()


def test_every_source_record_carries_a_reason_and_valid_enums(tmp_path):
    doc, _ = ff.status(populated(tmp_path), z("2026-09-24T23:01:00Z"))
    for s in doc["sources"]:
        assert s["why_due"].strip()
        assert s["freshness"] in ("FRESH", "STALE", "UNKNOWN")
        assert s["schedule_state"] in {x.value for x in ScheduleState}
        assert s["health"] in {x.value for x in SourceHealth}
        if s["freshness"] == "FRESH":
            assert s["receipt_ts_utc"] is not None
    assert iso_z(z("2026-09-24T23:01:00Z")) == doc["generated_at_utc"]
