"""NHL-B against NHL-A's real discovery (#137, merged 7e0b81d): the Kalshi NHL planner reads the `icehockey_nhl`
discovery that `odds_pilot.run_tick` itself stores, through a scripted provider. No network, no credits, and no
paid odds call is needed (the ticks run before any NHL target is due; the discovery is quota-free)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from edge_lab import http
from edge_lab import odds_pilot as op
from edge_lab import price_observations as po
from edge_lab import sports_nhl as nhl
from edge_lab.storage import SnapshotStore
from test_odds_nhl import (ENV_ON, NHL_SETTINGS, Clock, ReceiptClock, TwoSportProvider, nhl_event,  # noqa: F401
                           no_network, paths)

UTC = timezone.utc
# Real 2026-10-01 games with The Odds API style full names: BUF@CBJ and TB@NYR at 19:00 ET.
GAMES = [nhl_event("h_bufcbj", "2026-10-01T23:00:00Z", "Columbus Blue Jackets", "Buffalo Sabres"),
         nhl_event("h_tbnyr", "2026-10-01T23:00:00Z", "New York Rangers", "Tampa Bay Lightning")]


def tick(paths, provider, at, monkeypatch):
    """One tick at `at`, its discovery received at `at` too. The transport stamps receipts with the wall
    clock, and the planner reads only discoveries received at or before its `now`: unpinned, these tests
    failed once the real date passed the fixed 2026-10-01 games."""
    monkeypatch.setattr(http, "datetime", type("Receipt", (ReceiptClock,), {"at": at}))
    return op.run_tick(paths[0], paths[1], NHL_SETTINGS, clock=Clock(at), opener=provider, environ=ENV_ON)


def test_the_planner_reads_the_discovery_odds_pilot_stores(paths, monkeypatch):
    at = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    provider = TwoSportProvider(nhl=GAMES, nfl=[])
    code, report = tick(paths, provider, at, monkeypatch)
    assert report["discovery"]["state"] == "REFRESHED" and not provider.paid()
    store = SnapshotStore.open_readonly(paths[0])
    schedule = nhl.read_schedule(store, at + timedelta(minutes=5), max_age=po.NHL_SCHEDULE_MAX_AGE)
    assert schedule.state == "OK" and {e.event_id for e in schedule.events} == {"h_bufcbj", "h_tbnyr"}
    assert schedule.window_from == at and schedule.window_to == at + timedelta(days=35)  # #137's request context
    new, closures, plan = po.plan_nhl_targets(store, datetime(2026, 10, 1, 12, 5, tzinfo=UTC))
    assert plan["state"] == "ON" and plan["games"]["mapped"] == 2 and closures == []
    assert {t["native_event_id"] for t in new} == {"KXNHLGAME-26OCT01BUFCBJ", "KXNHLGAME-26OCT01TBNYR"}
    assert len(new) == 8


def test_a_game_nhl_a_no_longer_lists_is_superseded_and_a_moved_one_rescheduled(paths, monkeypatch):
    at = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    provider = TwoSportProvider(nhl=GAMES, nfl=[])
    tick(paths, provider, at, monkeypatch)
    code, report = po.run_plan(paths[0], None, now=datetime(2026, 10, 1, 12, 5, tzinfo=UTC),
                               environ={po.NHL_SWITCH: "on"})
    assert len(report["nhl"]["planned"]) == 8
    # Six hours later (its discovery interval) NHL-A rediscovers: BUF@CBJ is gone, TB@NYR moved two days.
    provider.events["icehockey_nhl"] = [nhl_event("h_tbnyr", "2026-10-03T23:00:00Z", "New York Rangers",
                                                  "Tampa Bay Lightning")]
    later = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    tick(paths, provider, later, monkeypatch)
    code, report = po.run_plan(paths[0], None, now=later + timedelta(minutes=5), environ={po.NHL_SWITCH: "on"})
    superseded = SnapshotStore.open_readonly(paths[0]).price_targets()
    reasons = {t["target_id"]: t["state_reason"] for t in superseded if t["state"] == "MISSED"}
    assert len(reasons) == 8
    assert sum(r.startswith("SUPERSEDED_NOT_IN_SCHEDULE") for r in reasons.values()) == 4
    assert sum(r.startswith("SUPERSEDED_RESCHEDULED") for r in reasons.values()) == 4
