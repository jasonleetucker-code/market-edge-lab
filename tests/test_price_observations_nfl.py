"""Kalshi NFL pairing (owner approval 2026-09-25, EXP-002): the planner and the capture's NFL rules.

Offline: every GET goes to a fake serving the recorded KXNFLGAME listing
(tests/fixtures/sports_evidence/) and a recorded Kalshi order book. The Odds schedule uses real
week-4 matchups from that listing; kickoffs are its occurrence_datetime minus 3 h (the listing's
occurrence time is kickoff + 3 h for every game, e.g. ATL@GB 20:15 ET).
Hard guards tested here: KXNFLGAME only, at most 6 GETs per game-horizon and 288 + 7 a week, the
existing per-run caps, zero Odds calls, protected windows, idempotent re-planning, the switch."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import http, odds_api
from edge_lab import price_observations as po
from edge_lab.http import FetchResult, HttpFetchError
from edge_lab.odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z, plan_targets
from edge_lab.sports_evidence import NFL_TEAMS
from edge_lab.storage import SnapshotStore
from test_forward import BOOK, Clock

UTC = timezone.utc
FIX = Path(__file__).parent / "fixtures" / "sports_evidence"
LISTING = json.loads((FIX / "kalshi_events_KXNFLGAME_open_2026-09-25T022444Z.json").read_text(encoding="utf-8"))
EVENTS = {e["event_ticker"]: e for e in LISTING["events"]}
BY_ABBR = {abbr: name for name, (abbr, _) in NFL_TEAMS.items()}
ON = {po.NFL_SWITCH: "on"}
OFF: dict[str, str] = {}
SPORT = po.NFL_SPORT


def game(event_ticker: str) -> ScheduledEvent:
    """A real matchup from the recorded listing: away/home from the ticker, kickoff from occurrence - 3 h."""
    ev = EVENTS[event_ticker]
    away, home = ev["sub_title"].split(" (")[0].split(" vs ")
    kickoff = datetime.fromisoformat(ev["markets"][0]["occurrence_datetime"].replace("Z", "+00:00")) - timedelta(hours=3)
    return ScheduledEvent(f"odds-{event_ticker}", SPORT, kickoff, home_team=BY_ABBR[home], away_team=BY_ABBR[away])


ARI_NYG = game("KXNFLGAME-26OCT04ARINYG")  # Sunday 2026-10-04 13:00 ET (17:00Z)
DEN_SF = game("KXNFLGAME-26OCT04DENSF")  # Sunday 16:25 ET
KC_LV = game("KXNFLGAME-26OCT04KCLV")  # Sunday 16:25 ET


def listing_payload(event_ticker: str) -> dict:
    return {"cursor": "", "markets": EVENTS[event_ticker]["markets"]}


class Api:
    """Routes URL fragments to payloads or exceptions; records every URL and its retries argument."""

    def __init__(self, clock: Clock, routes: dict):
        self.clock, self.routes = clock, routes
        self.calls: list[str] = []
        self.retries: list[int | None] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        self.retries.append(kwargs.get("retries"))
        self.clock.now += timedelta(seconds=0.3)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, BaseException):
                    raise payload
                body = json.dumps(payload).encode()
                return payload, FetchResult(url, url, 200, "application/json", body, self.clock.now.isoformat(), 1, 1)
        raise AssertionError(f"unexpected url {url}")


def routes(*events: str, book=BOOK, settled=None) -> dict:
    out: dict = {"/orderbook": book}
    for e in events:
        out[f"/markets?event_ticker={e}&"] = listing_payload(e)
    if settled is not None:
        out["series_ticker=KXNFLGAME"] = settled
    return out


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "edge.sqlite3")


def odds_schedule(store: SnapshotStore, *games: ScheduledEvent, planned_at: datetime) -> dict[tuple[str, str], str]:
    """Plan the Odds pilot's targets as the runner does; returns {(odds event, offset): target id}."""
    ids = {}
    for t in plan_targets(games, DEFAULT_OFFSETS):
        store.plan_odds_target(target_id=t.target_id, sport=SPORT, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                               planned_at_utc=iso_z(planned_at), policy_version="game_relative_v1",
                               home_team=t.home_team, away_team=t.away_team)
        ids[(t.event_id, t.offset_label)] = t.target_id
    return ids


def odds_captured(store: SnapshotStore, target_id: str, at: datetime) -> None:
    run = f"odds-{target_id}"
    store.start_run(run)
    sid = store.save_snapshot(run_id=run, source="the_odds_api", kind="odds", entity_id=SPORT,
                              url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey=REDACTED",
                              payload={"events": []}, fetched_at_utc=at.isoformat(), source_id="the_odds_api")
    store.finish_run(run, status="succeeded")
    store.record_odds_transition(target_id=target_id, state="CAPTURING", at_utc=iso_z(at))
    store.record_odds_transition(target_id=target_id, state="CAPTURED", at_utc=iso_z(at), snapshot_id=sid,
                                 captured_at_utc=at.isoformat(), credits_last=3)


def nfl_targets(store: SnapshotStore) -> list:
    return [t for t in store.price_targets() if po.is_nfl_target(t)]


def plan(store, now, environ=ON):
    return po.run_plan(store.path, None, now=now, environ=environ)[1]


def capture(store, clock, environ=ON):
    return po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=environ)


# T-24h of ARI@NYG: Saturday 2026-10-03 13:00 ET = 17:00Z. The Odds tick fires at 17:00; observe at 17:05.
T24 = datetime(2026, 10, 3, 17, 0, 4, tzinfo=UTC)
TICK = datetime(2026, 10, 3, 17, 5, tzinfo=UTC)


def setup_captured(store, *games, at=T24, offset="T-24h"):
    ids = odds_schedule(store, *games, planned_at=at - timedelta(days=2))
    for g in games:
        odds_captured(store, ids[(g.event_id, offset)], at)
    return ids


# --------------------------------------------------------------------------- the switch


@pytest.mark.parametrize("value, on", [("on", True), ("ON", True), ("1", True), ("true", True), ("yes", True),
                                       ("", False), ("off", False), ("0", False), ("enabled", False)])
def test_the_switch_is_on_only_when_set_explicitly(value, on):
    assert po.nfl_capture_enabled({po.NFL_SWITCH: value}) is on
    assert po.nfl_capture_enabled({}) is False


def test_switch_off_plans_nothing(store):
    setup_captured(store, ARI_NYG)
    report = plan(store, TICK, environ=OFF)
    assert report["nfl"]["state"] == "OFF"
    assert nfl_targets(store) == []


def test_switch_off_holds_pending_targets_without_a_request(store, monkeypatch):
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    assert len(nfl_targets(store)) == 2
    clock = Clock(TICK + timedelta(seconds=20))
    api = Api(clock, routes("KXNFLGAME-26OCT04ARINYG"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock, environ=OFF)
    assert api.calls == []
    assert report["nfl_held"]["reason"] == "NFL_CAPTURE_OFF" and len(report["nfl_held"]["targets"]) == 2
    # They expire MISSED at their deadline; nothing is fetched late.
    later = Clock(T24 + timedelta(minutes=45))
    capture(store, later, environ=OFF)
    assert {t["state"] for t in nfl_targets(store)} == {"MISSED"}


# --------------------------------------------------------------------------- planning


def test_pairs_both_team_markets_at_the_odds_receipt_time(store):
    ids = setup_captured(store, ARI_NYG)
    report = plan(store, TICK)
    targets = {t["native_market_id"]: t for t in nfl_targets(store)}
    assert set(targets) == {"KXNFLGAME-26OCT04ARINYG-ARI", "KXNFLGAME-26OCT04ARINYG-NYG"}
    for t in targets.values():
        assert t["native_event_id"] == "KXNFLGAME-26OCT04ARINYG" and t["phase"] == "custom"
        assert t["origin"] == po.NFL_ORIGIN
        assert t["target_utc"] == "2026-10-03T17:00:04+00:00"  # the Odds receipt, to the second
        assert t["deadline_utc"] == "2026-10-03T17:29:04+00:00"  # two ticks at most
        detail = json.loads(t["detail_json"])
        assert detail["odds_target_id"] == ids[(ARI_NYG.event_id, "T-24h")] and detail["odds_offset"] == "T-24h"
        assert detail["mapping"] == "DERIVED" and detail["game_date"] == "2026-10-04"
    assert report["nfl"]["budget"]["game_horizons"] == 1
    assert report["nfl"]["budget"]["worst_case_gets"] == 6 and report["nfl"]["budget"]["expected_gets"] == 3
    assert report["nfl"]["odds_api_calls"] == 0


def test_replanning_never_duplicates(store):
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    again = plan(store, TICK + timedelta(minutes=15))
    assert again["state"] == "NOTHING_TO_DO"
    assert len(nfl_targets(store)) == 2
    assert po.plan_nfl_targets(SnapshotStore.open_readonly(store.path), TICK)[0] == []


def test_only_fresh_odds_captures_are_paired(store):
    ids = odds_schedule(store, ARI_NYG, DEN_SF, planned_at=T24 - timedelta(days=2))
    odds_captured(store, ids[(ARI_NYG.event_id, "T-24h")], T24 - timedelta(minutes=40))  # too old to pair
    store.record_odds_transition(target_id=ids[(DEN_SF.event_id, "T-24h")], state="SKIPPED_BUDGET",
                                 at_utc=iso_z(T24), reason="monthly proof")
    plan(store, TICK)
    assert nfl_targets(store) == []  # no pair without an Odds capture; nothing is fetched late


def test_a_rescheduled_game_keeps_its_originally_scheduled_ticker_date(store):
    ids = odds_schedule(store, ARI_NYG, planned_at=T24 - timedelta(days=3))
    for key, tid in ids.items():
        store.record_odds_transition(target_id=tid, state="SUPERSEDED", at_utc=iso_z(T24 - timedelta(days=1)),
                                     reason="commence time changed")
    moved = ScheduledEvent(ARI_NYG.event_id, SPORT, ARI_NYG.commence_utc + timedelta(days=1),
                           home_team=ARI_NYG.home_team, away_team=ARI_NYG.away_team)
    new = odds_schedule(store, moved, planned_at=T24 - timedelta(days=1))
    at = T24 + timedelta(days=1)
    odds_captured(store, new[(moved.event_id, "T-24h")], at)
    plan(store, at + timedelta(minutes=5))
    assert {t["native_event_id"] for t in nfl_targets(store)} == {"KXNFLGAME-26OCT04ARINYG"}  # not 26OCT05
    assert {json.loads(t["detail_json"])["game_date"] for t in nfl_targets(store)} == {"2026-10-05"}


def test_a_book_is_never_planned_inside_the_last_five_minutes_before_kickoff(store):
    ids = odds_schedule(store, ARI_NYG, planned_at=T24 - timedelta(days=2))
    late = ARI_NYG.commence_utc - timedelta(minutes=20)
    odds_captured(store, ids[(ARI_NYG.event_id, "T-60m")], late)
    plan(store, late + timedelta(minutes=5))
    assert {t["deadline_utc"] for t in nfl_targets(store)} == {iso_z(ARI_NYG.commence_utc - po.NFL_MIN_LEAD)
                                                               .replace("Z", "+00:00")}
    report = plan(store, ARI_NYG.commence_utc - timedelta(minutes=4), environ=ON)
    assert report["state"] in ("NOTHING_TO_DO", "OK")


def test_unknown_teams_and_other_sports_are_never_planned(store):
    stranger = ScheduledEvent("odds-x", SPORT, ARI_NYG.commence_utc, home_team="London Monarchs",
                              away_team="Arizona Cardinals")
    college = ScheduledEvent("odds-ncaa", "americanfootball_ncaaf", ARI_NYG.commence_utc,
                             home_team="New York Giants", away_team="Arizona Cardinals")
    ids = odds_schedule(store, stranger, planned_at=T24 - timedelta(days=2))
    odds_captured(store, ids[("odds-x", "T-24h")], T24)
    for t in plan_targets([college], DEFAULT_OFFSETS):
        store.plan_odds_target(target_id=t.target_id, sport="americanfootball_ncaaf", event_id=t.event_id,
                               offset_label=t.offset_label, priority=t.priority,
                               commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                               planned_at_utc=iso_z(T24), policy_version="game_relative_v1",
                               home_team=t.home_team, away_team=t.away_team)
        odds_captured(store, t.target_id, T24)
    report = plan(store, TICK)
    assert nfl_targets(store) == []
    assert any(s["reason"].startswith("UNMAPPED_TEAM") for s in report["nfl"]["not_planned"])


def test_every_planned_ticker_is_kxnflgame(store):
    setup_captured(store, ARI_NYG, DEN_SF, KC_LV)
    plan(store, TICK)
    assert all(t["native_market_id"].startswith("KXNFLGAME-") for t in nfl_targets(store))


def _store_listing(store, event, payload, at):
    store.start_run("listing")
    store.save_snapshot(run_id="listing", source="kalshi", kind="markets", entity_id=event,
                        url=f"https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker={event}",
                        payload=payload, fetched_at_utc=at.isoformat(), source_id="kalshi_public")
    store.finish_run("listing", status="succeeded")


def test_mapping_comes_only_from_listings_stored_by_the_planning_time(store):
    event = "KXNFLGAME-26OCT04ARINYG"
    setup_captured(store, ARI_NYG)
    _store_listing(store, event, listing_payload(event), T24 - timedelta(hours=1))
    plan(store, TICK)
    assert {json.loads(t["detail_json"])["mapping"] for t in nfl_targets(store)} == {"LISTED"}


@pytest.mark.parametrize("mutate, state", [
    (lambda ms: ms[:1], "NOT_LISTED"),
    (lambda ms: [{**m, "yes_sub_title": "Somewhere Else"} for m in ms], "AMBIGUOUS"),
])
def test_a_stored_listing_that_contradicts_the_mapping_stops_planning(store, mutate, state):
    event = "KXNFLGAME-26OCT04ARINYG"
    setup_captured(store, ARI_NYG)
    _store_listing(store, event, {"cursor": "", "markets": mutate(EVENTS[event]["markets"])}, T24 - timedelta(hours=1))
    report = plan(store, TICK)
    assert nfl_targets(store) == []
    assert any(s["reason"].startswith(state) for s in report["nfl"]["not_planned"])


def test_the_weekly_game_horizon_bound_is_enforced(store, monkeypatch):
    assert po.NFL_WEEKLY_GET_CAP == 288 + 7 and po.NFL_WORST_GETS_PER_GAME_HORIZON == 6
    monkeypatch.setattr(po, "NFL_WEEKLY_GAME_HORIZONS", 2)
    setup_captured(store, ARI_NYG, DEN_SF, KC_LV)
    report = plan(store, TICK)
    assert len({t["native_event_id"] for t in nfl_targets(store)}) == 2
    assert [s for s in report["nfl"]["not_planned"] if s["reason"].startswith("WEEKLY_BUDGET")]
    assert report["nfl"]["budget"]["worst_case_gets"] == 12


# --------------------------------------------------------------------------- capture


def test_capture_is_one_listing_and_two_books_without_in_run_retries(store, monkeypatch):
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    clock = Clock(TICK + timedelta(seconds=20))
    api = Api(clock, routes("KXNFLGAME-26OCT04ARINYG"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock)
    assert code == 0 and report["requests"] == 3
    assert sum("/markets?event_ticker=KXNFLGAME-26OCT04ARINYG" in c for c in api.calls) == 1
    assert sum("/orderbook" in c for c in api.calls) == 2
    assert api.retries == [0, 0, 0]
    assert all(c.startswith(po.forward.KALSHI_BASE) for c in api.calls)
    assert {t["state"] for t in nfl_targets(store)} == {"CAPTURED"}
    rows = [r for r in store.price_observations() if r["native_market_id"].startswith("KXNFLGAME-")]
    assert len(rows) == 4 and {r["rules_sha256"] is not None for r in rows} == {True}


def test_a_failed_game_horizon_is_retried_once_then_final(store, monkeypatch):
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    failing = routes("KXNFLGAME-26OCT04ARINYG", book=HttpFetchError("HTTP 503", status=503, attempts=1))
    clock = Clock(TICK + timedelta(seconds=20))
    api = Api(clock, failing)
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, first = capture(store, clock)
    assert code == 0 and sorted(first["failed_retrying"]) == sorted(t["target_id"] for t in nfl_targets(store))
    clock.now = TICK + timedelta(minutes=15, seconds=20)
    code, second = capture(store, clock)
    assert code == 1 and len(second["failed_final"]) == 2  # the one retry is spent: final, alerting
    clock.now = TICK + timedelta(minutes=30, seconds=20)  # a third tick (past the deadline) sends nothing
    capture(store, clock)
    assert len(api.calls) == 6 <= po.NFL_WORST_GETS_PER_GAME_HORIZON
    assert {t["state"] for t in nfl_targets(store)} == {"MISSED"}


def test_the_attempt_limit_holds_even_if_a_deadline_would_allow_a_third_tick(store, monkeypatch):
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    with sqlite3.connect(store.path) as conn:  # simulate a longer window: the guard is not the deadline alone
        conn.execute("DROP TRIGGER IF EXISTS price_observation_targets_no_update")
        conn.execute("UPDATE price_observation_targets SET deadline_utc = ? WHERE origin = ?",
                     ("2026-10-03T18:00:00+00:00", po.NFL_ORIGIN))
    failing = routes("KXNFLGAME-26OCT04ARINYG", book=HttpFetchError("HTTP 503", status=503, attempts=1))
    clock = Clock(TICK + timedelta(seconds=20))
    api = Api(clock, failing)
    monkeypatch.setattr(po, "fetch_json_result", api)
    for minutes in (0, 15, 30, 45):
        clock.now = TICK + timedelta(minutes=minutes, seconds=20)
        _, report = capture(store, clock)
    assert len(api.calls) == 6
    assert report["nfl_held"]["reason"] == "NFL_ATTEMPT_LIMIT"


def test_nfl_targets_never_take_an_adr0030_targets_place(store, monkeypatch):
    setup_captured(store, ARI_NYG)
    manual = po.custom_target(venue="kalshi", native_market_id="KXHIGHNY-26SEP23-B69.5", at=T24 + timedelta(minutes=2))
    po.plan(store, decisions=[], now=TICK, custom=[manual])
    plan(store, TICK)
    clock = Clock(TICK + timedelta(seconds=20))
    from test_forward import MARKETS
    api = Api(clock, {**routes("KXNFLGAME-26OCT04ARINYG"), "/markets?event_ticker=KXHIGHNY-26SEP23": MARKETS})
    monkeypatch.setattr(po, "fetch_json_result", api)
    _, report = po.run_capture(store.path, clock=clock, sleep=clock.sleep, max_targets=1, environ=ON)
    assert "KXHIGHNY-26SEP23" in api.calls[0]  # the ADR 0030 / manual target goes first
    assert all("KXNFLGAME" not in c for c in api.calls)  # only 1 market fits: the NFL ones wait
    assert len(report["deferred"]) == 2


def test_capture_respects_the_protected_settlement_window(store, monkeypatch):
    # An Odds capture at 16:15 ET is paired at the 16:35 tick: the 16:13-16:30 window refuses 16:20.
    at = datetime(2026, 10, 3, 20, 15, 3, tzinfo=UTC)  # 16:15 ET
    ids = odds_schedule(store, ARI_NYG, planned_at=at - timedelta(days=2))
    odds_captured(store, ids[(ARI_NYG.event_id, "T-24h")], at)
    refused = plan(store, datetime(2026, 10, 3, 20, 20, tzinfo=UTC))
    assert refused["state"] == "DEFERRED_PROTECTED_WINDOW" and nfl_targets(store) == []
    plan(store, datetime(2026, 10, 3, 20, 35, tzinfo=UTC))
    assert len(nfl_targets(store)) == 2
    clock = Clock(datetime(2026, 10, 3, 20, 20, 5, tzinfo=UTC))
    api = Api(clock, routes("KXNFLGAME-26OCT04ARINYG"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    _, report = capture(store, clock)
    assert report["state"] == "DEFERRED_PROTECTED_WINDOW" and api.calls == []
    clock.now = datetime(2026, 10, 3, 20, 35, 5, tzinfo=UTC)
    capture(store, clock)
    assert len(api.calls) == 3 and {t["state"] for t in nfl_targets(store)} == {"CAPTURED"}


def test_zero_odds_api_calls(store, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("no Odds API call is allowed")
    for name in ("fetch_events", "fetch_odds", "reconcile_quota"):
        if hasattr(odds_api, name):
            monkeypatch.setattr(odds_api, name, forbidden)
    monkeypatch.setattr(http, "fetch", forbidden)
    setup_captured(store, ARI_NYG)
    plan(store, TICK)
    clock = Clock(TICK + timedelta(seconds=20))
    api = Api(clock, routes("KXNFLGAME-26OCT04ARINYG"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    capture(store, clock)
    assert api.calls and all("the-odds-api" not in c for c in api.calls)


# --------------------------------------------------------------------------- settlement read


SETTLE_TICK = datetime(2026, 10, 3, 23, 35, tzinfo=UTC)  # the game day's last kickoff + 6 h 30 min, as a tick


def _books_for_game_day(store):
    """ARI@NYG (13:00 ET) and DEN@SF (16:25 ET) books planned for game day 2026-10-04."""
    setup_captured(store, ARI_NYG, DEN_SF)
    plan(store, TICK)


def test_one_settlement_read_per_game_day_after_the_last_expected_expiration(store):
    _books_for_game_day(store)
    tick = po.next_observe_tick(DEN_SF.commence_utc + po.NFL_SETTLEMENT_AFTER_KICKOFF)
    assert tick == datetime(2026, 10, 5, 3, 5, tzinfo=UTC)  # 16:25 ET + 6 h 30 min = 22:55 ET -> 23:05 ET tick
    assert plan(store, tick - timedelta(hours=2))["nfl"]["planned"] == []  # not yet
    report = plan(store, tick - timedelta(minutes=20))
    reads = [t for t in nfl_targets(store) if json.loads(t["detail_json"])["nfl_role"] == po.NFL_ROLE_SETTLEMENT]
    assert len(reads) == 1 and reads[0]["target_utc"] == "2026-10-05T03:05:00+00:00"
    assert reads[0]["deadline_utc"] == "2026-10-05T03:14:00+00:00"  # only that tick fits
    assert report["nfl"]["budget"]["settlement_reads"] == 1
    plan(store, tick - timedelta(minutes=5))
    assert len([t for t in nfl_targets(store) if json.loads(t["detail_json"])["nfl_role"] == po.NFL_ROLE_SETTLEMENT]) == 1


def test_the_settlement_read_is_one_listing_only_get_and_never_retried(store, monkeypatch):
    _books_for_game_day(store)
    tick = datetime(2026, 10, 5, 3, 5, tzinfo=UTC)
    plan(store, tick - timedelta(minutes=10))
    settled = {"cursor": "", "markets": [{**m, "status": "finalized"} for m in EVENTS["KXNFLGAME-26OCT04ARINYG"]["markets"]]}
    clock = Clock(tick + timedelta(seconds=10))
    api = Api(clock, routes(settled=settled))
    monkeypatch.setattr(po, "fetch_json_result", api)
    # The two game-day books expired long ago (MISSED); only the read is due.
    capture(store, clock)
    assert len(api.calls) == 1 and "status=settled" in api.calls[0] and "series_ticker=KXNFLGAME" in api.calls[0]
    assert "min_close_ts=" in api.calls[0] and "limit=100" in api.calls[0] and api.retries == [0]
    row = [r for r in store.price_observations() if r["native_market_id"] == "KXNFLGAME"][-1]
    assert row["collection_status"] == "NOT_EXECUTABLE" and row["miss_reason"].startswith("SETTLEMENT_METADATA_READ: 2")
    snap = store.snapshots_by_id([row["snapshot_id"]])[row["snapshot_id"]]
    assert snap["kind"] == "settled_markets" and snap["entity_id"] == "KXNFLGAME"


def test_a_failed_settlement_read_is_final(store, monkeypatch):
    _books_for_game_day(store)
    tick = datetime(2026, 10, 5, 3, 5, tzinfo=UTC)
    plan(store, tick - timedelta(minutes=10))
    clock = Clock(tick + timedelta(seconds=10))
    api = Api(clock, routes(settled=HttpFetchError("HTTP 400", status=400, attempts=1)))
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock)
    assert code == 1 and len(report["failed_final"]) == 1
    clock.now = tick + timedelta(minutes=15, seconds=10)
    capture(store, clock)
    assert len(api.calls) == 1


# --------------------------------------------------------------------------- dry run


def test_dry_run_shows_the_plan_and_writes_nothing(store, capsys):
    setup_captured(store, ARI_NYG, DEN_SF)
    before = store.path.read_bytes()
    out = po.nfl_dry_run(store.path, now=TICK)
    assert out["writes"] == 0 and out["requests"] == 0 and out["odds_api_calls"] == 0
    assert sorted(t["native_market_id"] for t in out["would_plan"]) == [
        "KXNFLGAME-26OCT04ARINYG-ARI", "KXNFLGAME-26OCT04ARINYG-NYG",
        "KXNFLGAME-26OCT04DENSF-DEN", "KXNFLGAME-26OCT04DENSF-SF"]
    assert out["budget"]["game_horizons"] == 2  # the week's budget as it would be after this plan
    assert nfl_targets(store) == [] and store.path.read_bytes() == before
    assert po.main(["nfl-dry-run", "--db", str(store.path), "--now", TICK.isoformat()]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert len(printed["would_plan"]) == 4 and printed["command"] == "nfl dry-run"


def test_observe_plan_shows_the_planned_nfl_targets_for_a_sample_schedule(store):
    """A Saturday T-24h slot for three Sunday games: what `observe plan` reports with the switch on."""
    setup_captured(store, ARI_NYG, DEN_SF, KC_LV)
    report = plan(store, TICK)
    assert report["state"] == "OK" and report["targets_planned"] == 6
    nfl = report["nfl"]
    assert nfl["state"] == "ON" and len(nfl["planned"]) == 6
    assert nfl["budget"] == {"week": "nfl-week-of-2026-09-29", "game_horizons": 3, "game_horizon_cap": 48,
                             "settlement_reads": 0, "settlement_read_cap": 7, "worst_case_gets": 18,
                             "weekly_get_cap": 295, "worst_gets_per_game_horizon": 6, "expected_gets": 9}
