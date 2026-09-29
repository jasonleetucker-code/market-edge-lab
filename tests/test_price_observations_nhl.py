"""Kalshi KXNHLGAME prospective evidence (NHL-B, ADR 0040): identity, rules, the schedule planner and the capture.

Offline: every GET goes to a fake serving the recorded KXNHLGAME listing (tests/fixtures/sports_nhl/, read once on
2026-09-29) and a recorded Kalshi order book. The NHL schedule is a stored The Odds API `icehockey_nhl` discovery
snapshot built from real 2026-09-29..10-05 games (kickoffs are the listing's occurrence_datetime minus 3 h, which
matches the public NHL schedule for every listed game). NHL is DATA_COLLECTION / DEVELOPMENT_ONLY: nothing here is
EXP-002."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import price_observations as po
from edge_lab import sports_nhl as nhl
from edge_lab.http import FetchResult, HttpFetchError
from edge_lab.storage import SnapshotStore
from test_forward import BOOK, MARKETS, Clock
from test_price_observations_nfl import ARI_NYG, _close_target, odds_captured, odds_schedule, routes as nfl_routes
from test_price_observations_nfl import ON as NFL_ON

UTC = timezone.utc
FIX = Path(__file__).parent / "fixtures" / "sports_nhl"
LISTING = json.loads((FIX / "kalshi_events_KXNHLGAME_open_2026-09-29.json").read_text(encoding="utf-8"))
EVENTS = {e["event_ticker"]: e for e in LISTING["events"]}
SEASON = json.loads((FIX / "nhl_schedule_2026_27_regular_season.json").read_text(encoding="utf-8"))["games"]
BY_ABBR = {abbr: name for name, (abbr, _) in nhl.NHL_TEAMS.items()}
NHL_ON = {po.NHL_SWITCH: "on"}
BOTH_ON = {po.NHL_SWITCH: "on", po.NFL_SWITCH: "on"}
OFF = {}


def z(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def game(event_ticker: str, *, odds_id: str | None = None, shift: timedelta = timedelta(0)) -> dict:
    """An Odds API event for a real listed game: teams from the ticker, puck drop = occurrence - 3 h."""
    parsed, problem = nhl.parse_ticker(event_ticker)
    assert parsed is not None, problem
    occ = z(EVENTS[event_ticker]["markets"][0]["occurrence_datetime"])
    return {"id": odds_id or f"odds_{event_ticker[10:].lower()}", "sport_key": nhl.NHL_SPORT,
            "commence_time": (occ - timedelta(hours=3) + shift).isoformat().replace("+00:00", "Z"),
            "home_team": BY_ABBR[parsed["home"]], "away_team": BY_ABBR[parsed["away"]]}


def discovery(store: SnapshotStore, events: list[dict], at: datetime) -> int:
    run = f"odds-discovery-{at.isoformat()}"
    store.start_run(run)
    sid = store.save_snapshot(run_id=run, source="the_odds_api", kind="events", entity_id=nhl.NHL_SPORT,
                              url="https://api.the-odds-api.com/v4/sports/icehockey_nhl/events?apiKey=REDACTED",
                              payload={"sport": nhl.NHL_SPORT, "events": events,
                                       "request": {"purpose": "discovery", "tick_utc": at.isoformat()}},
                              fetched_at_utc=at.isoformat(), source_id="the_odds_api")
    store.finish_run(run, status="succeeded")
    return sid


def store_listing(store: SnapshotStore, event: str, payload: dict, at: datetime) -> None:
    run = f"listing-{event}-{at.isoformat()}"
    store.start_run(run)
    store.save_snapshot(run_id=run, source="kalshi", kind="markets", entity_id=event,
                        url=f"https://example.invalid/markets?event_ticker={event}", payload=payload,
                        fetched_at_utc=at.isoformat(), source_id="kalshi_public")
    store.finish_run(run, status="succeeded")


class Api:
    """Routes URL fragments to payloads or exceptions; records every URL and its retries argument."""

    def __init__(self, clock: Clock, routes: dict):
        self.clock, self.routes = clock, routes
        self.calls: list[str] = []
        self.retries: list = []

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


def routes(*events: str, settled=None) -> dict:
    out: dict = {"/orderbook": BOOK}
    for e in events:
        out[f"/markets?event_ticker={e}&"] = {"cursor": "", "markets": EVENTS[e]["markets"]}
    if settled is not None:
        out["series_ticker=KXNHLGAME"] = settled
    return out


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "edge.sqlite3")


def nhl_targets(store: SnapshotStore) -> list:
    return [t for t in store.price_targets() if po.is_nhl_target(t)]


def plan(store, now, environ=NHL_ON):
    return po.run_plan(store.path, None, now=now, environ=environ)[1]


def capture(store, clock, environ=NHL_ON, **kw):
    return po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=environ, **kw)


def detail(t) -> dict:
    return json.loads(t["detail_json"])


# Thursday 2026-10-01: BUF@CBJ, PHI@NJ, TB@NYR at 19:00 ET (23:00Z); MIN@NSH 20:00 ET; four western games later.
OCT1 = ["KXNHLGAME-26OCT01BUFCBJ", "KXNHLGAME-26OCT01PHINJ", "KXNHLGAME-26OCT01TBNYR", "KXNHLGAME-26OCT01MINNSH",
        "KXNHLGAME-26OCT01SEACGY", "KXNHLGAME-26OCT01CHIUTA", "KXNHLGAME-26OCT01EDMVAN", "KXNHLGAME-26OCT01FLASJ"]
DISC_AT = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)  # 06:00 ET
MORNING = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)  # 08:05 ET, an observe tick clear of every protected window


def oct1(store, at=DISC_AT, names=OCT1):
    return discovery(store, [game(e) for e in names], at)


# --------------------------------------------------------------------------- identity and scope


def test_every_listed_kxnhlgame_ticker_parses_and_round_trips():
    assert len(EVENTS) == 43
    for event, ev in EVENTS.items():
        parsed, problem = nhl.parse_ticker(event)
        assert problem is None and parsed["team"] is None
        assert nhl.event_ticker(parsed["away"], parsed["home"], parsed["date"]) == event
        assert ev["sub_title"].startswith(f"{parsed['away']} vs {parsed['home']}")  # away first
        for m in ev["markets"]:
            side, problem = nhl.parse_ticker(m["ticker"])
            assert problem is None and side["team"] in (parsed["away"], parsed["home"])
            # The team table's label is Kalshi's own market label.
            assert nhl.NHL_TEAMS[BY_ABBR[side["team"]]][1] == m["yes_sub_title"]
    assert {a for e in EVENTS for a in (nhl.parse_ticker(e)[0]["away"], nhl.parse_ticker(e)[0]["home"])} \
        == set(nhl.KALSHI_ABBRS)  # all 32 teams were listed on 2026-09-29


@pytest.mark.parametrize("ticker, problem", [
    ("KXNFLGAME-26OCT04ARINYG-ARI", "NOT_HOCKEY"),  # an NFL ticker is never NHL
    ("KXNHLTOTAL-26OCT01BUFCBJ-6", "FAMILY_NOT_ADMITTED"),
    ("KXNHLGOAL-26OCT01BUFCBJ-BUF", "FAMILY_NOT_ADMITTED"),
    ("KXNHLGAMEX-26OCT01BUFCBJ-BUF", "FAMILY_NOT_ADMITTED"),  # a look-alike series
    ("KXNHL-27", "FAMILY_NOT_ADMITTED"),  # futures
    ("KXNHLGAME-26OCT01BUFXYZ-BUF", "UNKNOWN_TEAM"),
    ("KXNHLGAME-26OCT01BUFCBJ-TOR", "SIDE_NOT_IN_GAME"),
    ("KXNHLGAME-26FOO01BUFCBJ-BUF", "MALFORMED"),
    ("KXNHLGAME-26FEB30BUFCBJ-BUF", "BAD_DATE"),
    ("", "NOT_HOCKEY"),
])
def test_unknown_hockey_families_and_bad_tickers_fail_closed(ticker, problem):
    assert nhl.parse_ticker(ticker) == (None, problem)


def test_nhl_and_nfl_never_cross():
    from edge_lab import sports_evidence as se

    assert se.parse_ticker("KXNHLGAME-26SEP29NYRBOS-NYR") is None
    assert nhl.parse_ticker("KXNFLGAME-26OCT04ARINYG-ARI") == (None, "NOT_HOCKEY")
    assert not se._is_nfl_entity("orderbook", "KXNHLGAME-26SEP29NYRBOS-NYR")
    assert not se._is_nfl_entity("markets", "KXNHLGAME")
    assert nhl.hockey_family("KXNFLGAME-26OCT04ARINYG") is None
    # Label withholding: an NHL row is never an EXP-002 label, and an NFL row never an NHL outcome.
    assert not po.nfl_label_withheld(None, venue="kalshi", native_market_id="KXNHLGAME-26SEP29NYRBOS-NYR", at_utc=None)
    assert not po.nhl_outcome_withheld(None, venue="kalshi", native_market_id="KXNFLGAME")


def test_ambiguous_abbreviation_splits_are_refused(monkeypatch):
    assert nhl.split_teams("LASJ") == (("LA", "SJ"), None)
    assert nhl.split_teams("TBNYR") == (("TB", "NYR"), None)
    monkeypatch.setattr(nhl, "KALSHI_ABBRS", frozenset({"NY", "NYR", "RBOS", "BOS"}))
    assert nhl.split_teams("NYRBOS") == (None, "AMBIGUOUS_SPLIT")


def test_team_names_and_aliases_map_and_unknown_names_do_not():
    assert nhl.team("Montréal Canadiens") == nhl.team("Montreal Canadiens") == ("MTL", "Montreal")
    assert nhl.team("St Louis Blues") == nhl.team("St. Louis Blues") == ("STL", "St. Louis")
    assert nhl.team("Utah Hockey Club") == ("UTA", "Utah")
    assert nhl.team("Quebec Nordiques") is None and nhl.team(None) is None
    assert nhl.NHL_COM_TO_KALSHI == {"LAK": "LA", "SJS": "SJ", "TBL": "TB", "NJD": "NJ"}


def test_rules_clauses_on_every_listed_market():
    hashes = set()
    for ev in EVENTS.values():
        for m in ev["markets"]:
            c = nhl.nhl_rules_clauses(m["rules_primary"], m["rules_secondary"])
            assert c["resolved"] and c["missing"] == []
            assert c["win_condition"] == "TEAM_WINS_GAME" and c["official_final_result"] is True
            assert c["postponement_window_hours"] == 48 and c["not_started_fallback"] == "FAIR_PRICE_AFTER_48H"
            # Not stated in the market rules text: never assumed.
            assert c["overtime"] == c["shootout"] == c["tie"] == "UNSTATED"
            hashes.add(m["rules_primary"].split(" wins the ")[1].split(" NHL game")[0])
    assert len(hashes) == 43
    reading = nhl.CONTRACT_TERMS_READING
    assert reading["overtime"]["status"] == "VERIFIED"
    assert reading["shootout"]["status"] == reading["tie"]["status"] == "RULES_UNRESOLVED"
    assert nhl.FEE_STATE == "FEE_UNSUPPORTED"


def test_missing_rules_clauses_are_unresolved():
    c = nhl.nhl_rules_clauses("If New York R wins the New York R vs Boston NHL game, then Yes.", None)
    assert not c["resolved"] and set(c["missing"]) == {"official_final_result", "postponement_window_hours",
                                                      "not_started_fallback"}
    assert nhl.nhl_rules_clauses(None, None)["win_condition"] is None


# --------------------------------------------------------------------------- the switch


@pytest.mark.parametrize("value, state", [(None, "OFF"), ("", "OFF"), ("off", "OFF"), ("on", "ON"), ("ON", "INVALID"),
                                          (" on", "INVALID"), ("1", "INVALID"), ("true", "INVALID")])
def test_the_switch_defaults_off(value, state):
    env = {} if value is None else {po.NHL_SWITCH: value}
    assert po.nhl_switch_value(env) == state
    assert po.nhl_capture_enabled(env) is (state == "ON")


def test_switch_off_plans_nothing_and_sends_nothing(store, monkeypatch):
    oct1(store)
    report = plan(store, MORNING, environ=OFF)
    assert "nhl" not in report and nhl_targets(store) == []  # the plan is exactly what it was before NHL-B
    clock = Clock(MORNING + timedelta(seconds=20))
    api = Api(clock, routes(*OCT1))
    monkeypatch.setattr(po, "fetch_json_result", api)
    assert capture(store, clock, environ=OFF)[1]["state"] == "NOTHING_DUE" and api.calls == []


def test_an_invalid_switch_is_reported_and_plans_nothing(store):
    oct1(store)
    report = plan(store, MORNING, environ={po.NHL_SWITCH: "yes"})
    assert report["nhl"]["state"] == "INVALID" and nhl_targets(store) == []


def test_switch_off_after_planning_holds_every_pending_target_without_a_request(store, monkeypatch):
    oct1(store)
    plan(store, MORNING)
    tick = datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC)
    clock = Clock(tick)
    api = Api(clock, routes(*OCT1))
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock, environ=OFF)
    assert code == 0 and api.calls == [] and report["nhl_held"]
    assert all(r.startswith("NHL_CAPTURE_DISABLED") for r in report["nhl_held"].values())


# --------------------------------------------------------------------------- planning


def test_plans_t6h_and_t60m_for_both_team_markets_from_the_schedule(store):
    oct1(store)
    report = plan(store, MORNING)
    nhl_report = report["nhl"]
    assert nhl_report["state"] == "ON" and nhl_report["odds_api_calls"] == 0 and nhl_report["requests"] == 0
    assert nhl_report["games"] == {"discovered": 8, "in_horizon": 8, "mapped": 8, "unmapped": 0}
    targets = nhl_targets(store)
    assert len(targets) == 8 * 2 * 2
    by = {(t["native_market_id"], detail(t)["horizon"]): t for t in targets}
    t6 = by[("KXNHLGAME-26OCT01BUFCBJ-BUF", "T-6h")]
    d = detail(t6)
    # Puck drop 19:00 ET (23:00Z): nominal T-6h 13:00 ET; the nearest observe tick is 13:05 ET.
    assert d["nominal_utc"] == "2026-10-01T17:00:00+00:00" and t6["target_utc"] == "2026-10-01T17:05:00+00:00"
    assert d["shift_reason"] is None and d["shift_minutes"] == 5 and t6["deadline_utc"] == "2026-10-01T17:34:00+00:00"
    t1 = by[("KXNHLGAME-26OCT01BUFCBJ-BUF", "T-60m")]
    d1 = detail(t1)
    # Nominal T-60m 18:00 ET is inside the EXP-001 window (17:40-18:50 ET): the nearest allowed tick is 17:35 ET.
    assert d1["nominal_utc"] == "2026-10-01T22:00:00+00:00" and t1["target_utc"] == "2026-10-01T21:35:00+00:00"
    assert d1["shift_reason"].startswith("PROTECTED_WINDOW: exp001_capture_window_and_shadow_run")
    assert t1["deadline_utc"] == "2026-10-01T22:04:00+00:00"
    # MIN@NSH 20:00 ET: T-60m nominal 19:00 ET, nearest tick 19:05 ET.
    assert by[("KXNHLGAME-26OCT01MINNSH-NSH", "T-60m")]["target_utc"] == "2026-10-01T23:05:00+00:00"
    for t in targets:
        assert t["origin"] == po.NHL_ORIGIN and t["phase"] == "custom" and t["venue"] == "kalshi"
        assert nhl.hockey_family(t["native_market_id"]) == "ADMITTED"
        assert t["target_id"].endswith(f"|{po.NHL_ORIGIN}:{detail(t)['horizon']}")
        assert detail(t)["classification"].startswith("DATA_COLLECTION / DEVELOPMENT_ONLY")
        assert detail(t)["mapping"] == "DERIVED" and detail(t)["fee_state"] == "FEE_UNSUPPORTED"
        # Never inside a protected window, and always before puck drop - the minimum lead.
        start = po._t(t["target_utc"])
        assert po.protected_window_at(start, start + po.MAX_RUN) is None
        assert po._t(t["deadline_utc"]) <= po._t(detail(t)["commence_utc"]) - po.NHL_MIN_LEAD
    assert nhl_report["budget"]["game_horizons"] == 16 and nhl_report["budget"]["worst_case_gets"] == 96


def test_replanning_never_duplicates(store):
    oct1(store)
    plan(store, MORNING)
    again = plan(store, MORNING + timedelta(minutes=15))
    assert again["state"] == "NOTHING_TO_DO" and len(nhl_targets(store)) == 32
    assert po.plan_nhl_targets(SnapshotStore.open_readonly(store.path), MORNING)[0] == []


def test_games_starting_on_the_same_tick_share_it_up_to_the_run_room():
    commence = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)  # 19:00 ET: the season's busiest start (9 games)
    load: dict = {}
    ticks = []
    for _ in range(9):
        tick, why = po.nhl_effective_tick(commence - timedelta(minutes=60), commence,
                                          {k: len(v) for k, v in load.items()})
        load.setdefault(tick, set()).add(len(load.get(tick, ())))
        ticks.append((tick, why))
    assert Counter(t for t, _ in ticks) == {datetime(2026, 11, 5, 22, 35, tzinfo=UTC): 8,
                                            datetime(2026, 11, 5, 22, 20, tzinfo=UTC): 1}
    assert ticks[-1][1].startswith("PROTECTED_WINDOW")  # the nearest tick is protected; the next nearest was full


def test_a_19_30_game_moves_after_the_window_and_a_20_00_game_to_the_nearest_tick():
    c1930 = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
    assert po.nhl_effective_tick(c1930 - timedelta(hours=1), c1930)[0] == datetime(2026, 10, 1, 22, 50, tzinfo=UTC)
    c2000 = datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
    assert po.nhl_effective_tick(c2000 - timedelta(hours=1), c2000) == (datetime(2026, 10, 1, 23, 5, tzinfo=UTC), None)


def test_unknown_teams_and_ambiguous_odds_events_are_unmapped_and_counted(store):
    events = [game("KXNHLGAME-26OCT01BUFCBJ"),
              {**game("KXNHLGAME-26OCT01PHINJ"), "home_team": "Hartford Whalers"},
              game("KXNHLGAME-26OCT01TBNYR", odds_id="dup_a"), game("KXNHLGAME-26OCT01TBNYR", odds_id="dup_b")]
    discovery(store, events, DISC_AT)
    report = plan(store, MORNING)["nhl"]
    assert report["games"] == {"discovered": 4, "in_horizon": 4, "mapped": 1, "unmapped": 3}
    assert report["not_planned_counts"] == {"AMBIGUOUS_ODDS_EVENTS": 2, "UNMAPPED_TEAM": 1}
    assert {t["native_event_id"] for t in nhl_targets(store)} == {"KXNHLGAME-26OCT01BUFCBJ"}


def test_a_stored_listing_confirms_or_stops_the_mapping(store):
    oct1(store, names=OCT1[:3])
    ok, missing, far = OCT1[0], OCT1[1], OCT1[2]
    store_listing(store, ok, {"cursor": "", "markets": EVENTS[ok]["markets"]}, DISC_AT)
    store_listing(store, missing, {"cursor": "", "markets": EVENTS[missing]["markets"][:1]}, DISC_AT)
    moved = [{**m, "occurrence_datetime": "2026-10-03T02:00:00Z"} for m in EVENTS[far]["markets"]]
    store_listing(store, far, {"cursor": "", "markets": moved}, DISC_AT)
    report = plan(store, MORNING)["nhl"]
    assert {t["native_event_id"] for t in nhl_targets(store)} == {ok}
    assert {detail(t)["mapping"] for t in nhl_targets(store)} == {"LISTED"}
    assert report["not_planned_counts"] == {"AMBIGUOUS": 1, "NOT_LISTED": 1}
    assert any("COMMENCE_MISMATCH" in s["reason"] for s in report["not_planned"])


def test_a_stale_or_missing_schedule_plans_nothing_new(store):
    assert plan(store, MORNING)["nhl"]["state"] == "SCHEDULE_NO_DISCOVERY"
    oct1(store, at=MORNING - timedelta(hours=25))
    report = plan(store, MORNING)["nhl"]
    assert report["state"] == "SCHEDULE_STALE" and nhl_targets(store) == []
    # A discovery received after `now` is unknown at `now` (point in time).
    oct1(store, at=MORNING + timedelta(hours=1))
    assert po.nhl_dry_run(store.path, now=MORNING)["state"] == "SCHEDULE_STALE"


def test_a_reschedule_supersedes_open_targets_and_keeps_the_original_ticker_date(store):
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    first = {t["target_id"] for t in nhl_targets(store)}
    assert len(first) == 4
    # Postponed by one day (within Kalshi's 48 h rule): the ticker keeps the originally scheduled date.
    discovery(store, [game(OCT1[0], shift=timedelta(days=1))], MORNING + timedelta(minutes=30))
    report = plan(store, MORNING + timedelta(minutes=35))
    assert sorted(s["target_id"] for s in report["superseded"]) == sorted(first)
    old = [t for t in nhl_targets(store) if t["target_id"] in first]
    assert {t["state"] for t in old} == {"MISSED"} and all(t["state_reason"].startswith("SUPERSEDED_RESCHEDULED")
                                                           for t in old)
    new = [t for t in nhl_targets(store) if t["target_id"] not in first]
    assert len(new) == 4 and {t["native_event_id"] for t in new} == {"KXNHLGAME-26OCT01BUFCBJ"}
    assert {detail(t)["commence_utc"] for t in new} == {"2026-10-02T23:00:00+00:00"}
    assert {detail(t)["original_commence_utc"] for t in new} == {"2026-10-01T23:00:00+00:00"}


def test_opening_night_past_horizons_are_missed_before_activation_and_manual_rows_untouched(store, monkeypatch):
    """2026-09-29: the coordinator's manual custom observations stay manual; a later first NHL plan records the
    horizons it can no longer reach as NOT_COLLECTED_BEFORE_ACTIVATION and never captures them late."""
    night = ["KXNHLGAME-26SEP29FLACAR", "KXNHLGAME-26SEP29MTLTOR", "KXNHLGAME-26SEP29NYRBOS",
             "KXNHLGAME-26SEP29VANEDM", "KXNHLGAME-26SEP29CHIVGK"]
    manual = [po.custom_target(venue="kalshi", native_market_id=m["ticker"], at=datetime(2026, 9, 29, 23, 5, tzinfo=UTC))
              for m in EVENTS["KXNHLGAME-26SEP29NYRBOS"]["markets"]]
    po.run_plan(store.path, None, now=datetime(2026, 9, 29, 17, 22, tzinfo=UTC), custom=manual, environ=OFF)
    before = [dict(t) for t in store.price_targets()]
    discovery(store, [game(e) for e in night], datetime(2026, 9, 29, 16, 0, tzinfo=UTC))
    now = datetime(2026, 9, 29, 23, 5, tzinfo=UTC)  # 19:05 ET: the first NHL plan ("activation")
    report = plan(store, now)["nhl"]
    by = {(t["native_event_id"], detail(t)["horizon"]): t for t in nhl_targets(store)
          if t["native_market_id"] == t["native_event_id"] + "-" + nhl.parse_ticker(t["native_event_id"])[0]["home"]}
    for key in [("KXNHLGAME-26SEP29FLACAR", "T-6h"), ("KXNHLGAME-26SEP29FLACAR", "T-60m"),
                ("KXNHLGAME-26SEP29MTLTOR", "T-6h"), ("KXNHLGAME-26SEP29MTLTOR", "T-60m"),
                ("KXNHLGAME-26SEP29NYRBOS", "T-6h")]:
        assert by[key]["state"] == "MISSED" and by[key]["state_reason"].startswith("NOT_COLLECTED_BEFORE_ACTIVATION")
    assert by[("KXNHLGAME-26SEP29NYRBOS", "T-60m")]["state"] is None  # 19:05 ET: still genuinely due
    assert {m["reason"] for m in report["missed_on_plan"]} == {"NOT_COLLECTED_BEFORE_ACTIVATION"}
    # The manual rows are exactly as they were (same ids, origin, times); NHL never relabels them.
    after = {t["target_id"]: dict(t) for t in store.price_targets()}
    for t in before:
        assert after[t["target_id"]] == t and t["origin"] == "manual"
    # A missed horizon is never fetched late: the capture reads only the still-due NYR@BOS T-60m (and the manual pair).
    clock = Clock(now + timedelta(seconds=20))
    api = Api(clock, routes("KXNHLGAME-26SEP29NYRBOS"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    capture(store, clock)
    assert all("NYRBOS" in c for c in api.calls) and len(api.calls) == 6  # 3 manual + 3 NHL, separate groups
    assert plan(store, now + timedelta(minutes=15))["nhl"]["missed_on_plan"] == []  # never re-recorded


# --------------------------------------------------------------------------- capture


def test_capture_is_one_listing_and_two_books_without_in_run_retries(store, monkeypatch):
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    clock = Clock(datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC))
    api = Api(clock, routes(OCT1[0]))
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock)
    assert code == 0 and report["requests"] == 3 and api.retries == [0, 0, 0]
    assert "limit=1000" in api.calls[0] and all("/orderbook" in c for c in api.calls[1:])
    t6 = [t for t in nhl_targets(store) if detail(t)["horizon"] == "T-6h"]
    assert {t["state"] for t in t6} == {"CAPTURED"}
    rows = [r for r in store.price_observations() if r["target_id"] in {t["target_id"] for t in t6}]
    for r in rows:
        # Receipt, record and source times stay distinct; a missing source time stays None.
        assert r["observed_at_utc"] and r["recorded_at_utc"] and r["source_timestamp_utc"] is None
        assert r["rules_sha256"] == nhl_rules_hash(OCT1[0], r["native_market_id"])
        assert r["bid"] is not None and r["ask"] is not None  # a pregame book is a feature: stored and shown
    shown = po.market_history(store, f"kalshi:{OCT1[0]}-BUF")
    assert any(h["ask"] is not None for h in shown) and not any("nhl_outcome" in h for h in shown)


def nhl_rules_hash(event: str, ticker: str) -> str:
    from edge_lab import kalshi_quotes

    return kalshi_quotes.rules_sha256(next(m for m in EVENTS[event]["markets"] if m["ticker"] == ticker))


def test_a_failed_game_horizon_is_retried_once_and_never_more(store, monkeypatch):
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    clock = Clock(datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC))
    api = Api(clock, {**routes(OCT1[0]),
                      f"/markets?event_ticker={OCT1[0]}&": HttpFetchError("HTTP 503", status=503, attempts=1)})
    monkeypatch.setattr(po, "fetch_json_result", api)
    code, report = capture(store, clock)
    assert code == 0 and len(report["nhl_failed"]) == 2 and report["failed_final"] == []  # never pages
    clock.now = datetime(2026, 10, 1, 17, 20, 20, tzinfo=UTC)
    capture(store, clock)
    assert len(api.calls) == 2  # the one retry: a listing again (it fails again)
    clock.now = datetime(2026, 10, 1, 17, 33, 0, tzinfo=UTC)
    _, report = capture(store, clock, max_requests=40)
    assert len(api.calls) == 2 and all(r.startswith("NHL_ATTEMPT_LIMIT") for r in report.get("nhl_held", {}).values())


def test_nhl_never_takes_an_nfl_or_adr0030_targets_place(store, monkeypatch):
    """NFL T-24h pairs and NHL T-6h books due at the same tick: NFL first, NHL only with what is left."""
    at = datetime(2026, 10, 3, 17, 0, 4, tzinfo=UTC)
    ids = odds_schedule(store, ARI_NYG, planned_at=at - timedelta(days=2))
    odds_captured(store, ids[(ARI_NYG.event_id, "T-24h")], at)
    # CHI@BUF and three more on 2026-10-03 at 19:00 ET: their T-6h tick is 13:05 ET too.
    oct3 = ["KXNHLGAME-26OCT03CHIBUF", "KXNHLGAME-26OCT03OTTTOR", "KXNHLGAME-26OCT03WSHTB"]
    discovery(store, [game(e) for e in oct3], at - timedelta(hours=3))
    tick = datetime(2026, 10, 3, 17, 5, tzinfo=UTC)
    report = po.run_plan(store.path, None, now=tick, environ=BOTH_ON)[1]
    assert len(report["nfl"]["planned"]) == 2 and len(report["nhl"]["planned"]) == 12
    clock = Clock(tick + timedelta(seconds=20))
    api = Api(clock, {**nfl_routes("KXNFLGAME-26OCT04ARINYG"), **routes(*oct3)})
    monkeypatch.setattr(po, "fetch_json_result", api)
    _, report = capture(store, clock, environ=BOTH_ON, max_requests=6)
    assert all("KXNFLGAME" in c for c in api.calls[:3]) and all("KXNHLGAME" in c for c in api.calls[3:])
    nfl_states = {t["state"] for t in store.price_targets() if po.is_nfl_target(t)}
    assert nfl_states == {"CAPTURED"}
    assert len(report["nhl_deferred_for_budget"]) == 4  # two NHL game-horizons waited; one fitted in the 3 left
    assert report["requests"] == 6
    # With a full run budget NHL stays inside its own share (24 GETs = 8 game-horizons).
    assert po.NHL_RUN_GET_SHARE == 24 and po.MAX_REQUESTS == 40


def test_the_nhl_run_share_caps_nhl_gets_in_one_run(store, monkeypatch):
    """Ten NHL game-horizons due at one tick (planned directly): at most 24 GETs go to NHL in the run."""
    tick = datetime(2026, 10, 1, 16, 5, tzinfo=UTC)
    names = [e for e in EVENTS if e.startswith("KXNHLGAME-26OCT03")][:10]
    for e in names:
        for m in EVENTS[e]["markets"]:
            t = po.custom_target(venue="kalshi", native_market_id=m["ticker"], at=tick, native_event_id=e)
            t.update(target_id=t["target_id"] + f"|{po.NHL_ORIGIN}:T-6h", origin=po.NHL_ORIGIN,
                     detail={"nhl_role": "book", "horizon": "T-6h"}, planned_at_utc=po._iso(tick - timedelta(hours=1)))
            assert store.plan_price_target(t)
    clock = Clock(tick + timedelta(seconds=20))
    api = Api(clock, routes(*names))
    monkeypatch.setattr(po, "fetch_json_result", api)
    _, report = capture(store, clock)
    assert report["requests"] == len(api.calls) <= po.NHL_RUN_GET_SHARE
    assert len(api.calls) == 24 and len(report["nhl_deferred_for_budget"]) == 4


def test_a_due_exp001_close_target_keeps_the_whole_run(store, monkeypatch):
    close = datetime(2026, 9, 24, 5, 0, tzinfo=UTC)
    commence = datetime(2026, 9, 24, 5, 50, tzinfo=UTC)  # T-60m tick 04:50Z, due until 05:19Z
    discovery(store, [{**game("KXNHLGAME-26SEP29NYRBOS"), "commence_time": "2026-09-24T05:50:00Z"}],
              datetime(2026, 9, 24, 0, 0, tzinfo=UTC))
    plan(store, datetime(2026, 9, 24, 4, 50, tzinfo=UTC))
    t60 = [t for t in nhl_targets(store) if detail(t)["horizon"] == "T-60m"]
    assert t60 and po._t(detail(t60[0])["commence_utc"]) == commence
    _close_target(store, close)
    clock = Clock(datetime(2026, 9, 24, 4, 57, 45, tzinfo=UTC))
    api = Api(clock, {**routes(), "/markets?event_ticker=KXHIGHNY-26SEP23": MARKETS,
                      "/markets?event_ticker=KXNHLGAME": {"cursor": "", "markets": []}})
    monkeypatch.setattr(po, "fetch_json_result", api)
    _, report = po.run_capture(store.path, clock=clock, sleep=clock.sleep, max_requests=3, environ=NHL_ON)
    assert all("KXNHLGAME" not in c for c in api.calls) and len(api.calls) == 3
    assert sorted(report["nhl_deferred_for_close"]) == sorted(t["target_id"] for t in t60)


def test_zero_odds_api_calls(store, monkeypatch):
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    clock = Clock(datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC))
    api = Api(clock, routes(OCT1[0]))
    monkeypatch.setattr(po, "fetch_json_result", api)
    capture(store, clock)
    assert api.calls and all("the-odds-api" not in c for c in api.calls)


# --------------------------------------------------------------------------- the bound


def _kalshi(abbr: str) -> str:
    return nhl.NHL_COM_TO_KALSHI.get(abbr, abbr)


def test_the_request_bound_holds_for_the_whole_published_season():
    """The arithmetic in ADR 0040 from the published 2026-27 schedule: every game-horizon gets an allowed tick,
    no tick holds more than the run room, and no week exceeds the game-horizon cap (so 727 GETs)."""
    assert len(SEASON) == 1344
    load: dict = {}
    weekly: Counter = Counter()
    per_day: Counter = Counter()
    shifts: Counter = Counter()
    for start, away, home in sorted(SEASON):
        commence = z(start)
        assert _kalshi(away) in nhl.KALSHI_ABBRS and _kalshi(home) in nhl.KALSHI_ABBRS
        per_day[nhl.et_date(commence)] += 1
        for horizon, offset in po.NHL_HORIZONS:
            pick = po.nhl_effective_tick(commence - offset, commence, {k: len(v) for k, v in load.items()})
            assert pick is not None, (start, horizon)
            tick, why = pick
            load.setdefault(tick, set()).add((start, away, home))
            weekly[po.nhl_week(tick)] += 1
            shifts[abs(int((tick - (commence - offset)).total_seconds() // 60))] += 1
            assert po.protected_window_at(tick, tick + po.MAX_RUN) is None
            assert tick <= commence - po.NHL_MIN_LEAD
    assert max(len(v) for v in load.values()) <= po.NHL_RUN_GAME_HORIZONS
    assert max(per_day.values()) == 16 and max(weekly.values()) <= po.NHL_WEEKLY_GAME_HORIZONS
    assert max(weekly.values()) * po.NHL_WORST_GETS_PER_GAME_HORIZON + 7 <= po.NHL_WEEKLY_GET_CAP == 727
    assert po.NFL_WEEKLY_GET_CAP == 295  # the NFL bound is its own and unchanged
    assert max(shifts) <= 120


def test_the_heaviest_day_through_plan_and_capture_stays_inside_every_bound(store, monkeypatch):
    """2026-10-13 has 16 games. Plan once, then run every observe tick of the day with a fake API."""
    day = [(z(s), _kalshi(a), _kalshi(h)) for s, a, h in SEASON if nhl.et_date(z(s)).isoformat() == "2026-10-13"]
    assert len(day) == 16
    events = [{"id": f"g{i}", "sport_key": nhl.NHL_SPORT, "commence_time": c.isoformat(), "home_team": BY_ABBR[h],
               "away_team": BY_ABBR[a]} for i, (c, a, h) in enumerate(day)]
    at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
    discovery(store, events, at - timedelta(hours=1))
    plan(store, at)
    assert len(nhl_targets(store)) == 16 * 2 * 2
    book = {"orderbook_fp": {"yes_dollars": [["0.4500", "10.00"]], "no_dollars": [["0.5300", "12.00"]]}}

    def listing(url):
        if "status=settled" in url:
            return {"cursor": "", "markets": []}
        event = url.split("event_ticker=")[1].split("&")[0]
        parsed, _ = nhl.parse_ticker(event)
        return {"cursor": "", "markets": [{"ticker": f"{event}-{t}", "event_ticker": event, "status": "active",
                                           "yes_sub_title": nhl.NHL_TEAMS[BY_ABBR[t]][1]}
                                          for t in (parsed["away"], parsed["home"])]}

    calls: list = []
    clock = Clock(at)

    def fake(url, **kw):
        calls.append(url)
        clock.now += timedelta(seconds=0.3)
        payload = book if "/orderbook" in url else listing(url)
        return payload, FetchResult(url, url, 200, "application/json", json.dumps(payload).encode(),
                                    clock.now.isoformat(), 1, 1)

    monkeypatch.setattr(po, "fetch_json_result", fake)
    tick = datetime(2026, 10, 13, 8, 5, tzinfo=UTC)
    per_run = []
    while tick < datetime(2026, 10, 14, 12, 0, tzinfo=UTC):
        before = len(calls)
        clock.now = tick + timedelta(seconds=20)
        plan(store, tick)
        capture(store, clock)
        per_run.append(len(calls) - before)
        tick += timedelta(minutes=15)
    assert max(per_run) <= po.NHL_RUN_GET_SHARE
    books = [t for t in nhl_targets(store) if detail(t)["nhl_role"] == "book"]
    assert {t["state"] for t in books} == {"CAPTURED"}
    reads = [t for t in nhl_targets(store) if detail(t)["nhl_role"] != "book"]
    assert len(reads) == 1  # one settled-markets read for the game day, and it was sent once
    assert len(calls) == 32 * 3 + 1


# --------------------------------------------------------------------------- outcomes are withheld


def test_the_settled_read_is_one_get_never_retried_and_its_result_is_withheld(store, monkeypatch):
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    tick = po.next_observe_tick(datetime(2026, 10, 1, 23, 0, tzinfo=UTC) + po.NHL_SETTLEMENT_AFTER_PUCK)
    assert tick == datetime(2026, 10, 2, 5, 35, tzinfo=UTC)  # 19:00 ET + 6 h 30 min = 01:30 ET -> 01:35 ET
    plan(store, tick - timedelta(minutes=10))
    reads = [t for t in nhl_targets(store) if detail(t)["nhl_role"] == po.NHL_ROLE_SETTLEMENT]
    assert len(reads) == 1 and reads[0]["native_market_id"] == "KXNHLGAME"
    settled = {"cursor": "", "markets": [{**m, "status": "finalized", "result": "yes"} for m in EVENTS[OCT1[0]]["markets"]]}
    clock = Clock(tick + timedelta(seconds=10))
    api = Api(clock, routes(settled=settled))
    monkeypatch.setattr(po, "fetch_json_result", api)
    capture(store, clock)
    assert len(api.calls) == 1 and "status=settled" in api.calls[0] and api.retries == [0]
    assert "series_ticker=KXNHLGAME" in api.calls[0] and "limit=100" in api.calls[0]
    history = po.market_history(store, "kalshi:KXNHLGAME")
    row = next(h for h in history if h["observation_id"] is not None)
    assert row["nhl_outcome"].startswith("HIDDEN") and "bid" not in row and "ask" not in row
    assert row["miss_reason"] == "SETTLEMENT_METADATA_READ: withheld (NHL outcome)"
    status = po.status(SnapshotStore.open_readonly(store.path), now=tick + timedelta(days=1),
                       systemctl=lambda args: "enabled")
    assert not any("SETTLEMENT_METADATA_READ: 2" in (m["reason"] or "") for m in status["recent_misses"])
    clock.now = tick + timedelta(minutes=15, seconds=10)
    capture(store, clock)
    assert len(api.calls) == 1


# --------------------------------------------------------------------------- freshness


def _fabric(store, now):
    from edge_lab import freshness_fabric as ff
    from edge_lab.freshness import FabricContext

    return {r.source_id: r for r in [*ff.price_observations_schedule(FabricContext(db=store.path), now),
                                      *ff.kalshi_nhl_schedule(FabricContext(db=store.path), now)]}


def test_nhl_has_its_own_freshness_identity_and_never_touches_exp001_or_nfl(store, monkeypatch):
    from edge_lab.freshness import ScheduleState

    now = MORNING
    before = _fabric(store, now)
    assert before["kalshi_nhl.game_books"].schedule_state is ScheduleState.PAUSED  # nothing planned: off by default
    oct1(store, names=OCT1[:1])
    plan(store, MORNING)
    clock = Clock(datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC))
    api = Api(clock, {**routes(OCT1[0]),
                      f"/markets?event_ticker={OCT1[0]}&": HttpFetchError("HTTP 503", status=503, attempts=1)})
    monkeypatch.setattr(po, "fetch_json_result", api)
    capture(store, clock)
    later = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    capture(store, Clock(later))  # everything past its deadline: NHL misses recorded
    after = _fabric(store, later)
    base = _fabric(SnapshotStore(store.path.with_name("empty.sqlite3")), later)
    for sid in ("price_observations.later", "price_observations.close"):
        assert after[sid].missed_count == base[sid].missed_count and after[sid].health == base[sid].health
        assert after[sid].receipt_ts == base[sid].receipt_ts
    nhl_rec = after["kalshi_nhl.game_books"]
    assert nhl_rec.missed_count == 4 and nhl_rec.details["missed_reasons"]
    assert nhl_rec.usable_for_decision is False


def test_nfl_and_adr0030_misses_never_change_the_nhl_record(store, monkeypatch):
    now = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
    base = _fabric(store, now)["kalshi_nhl.game_books"]
    at = datetime(2026, 10, 3, 17, 0, 4, tzinfo=UTC)
    ids = odds_schedule(store, ARI_NYG, planned_at=at - timedelta(days=2))
    odds_captured(store, ids[(ARI_NYG.event_id, "T-24h")], at)
    po.run_plan(store.path, None, now=datetime(2026, 10, 3, 17, 5, tzinfo=UTC), environ=NFL_ON)
    po.run_capture(store.path, clock=Clock(datetime(2026, 10, 3, 17, 5, 20, tzinfo=UTC)), sleep=lambda s: None,
                   environ={po.NFL_SWITCH: "off"})  # NFL targets MISSED at once
    manual = po.custom_target(venue="kalshi", native_market_id="KXHIGHNY-26OCT03-B70.5",
                              at=datetime(2026, 10, 3, 12, 0, tzinfo=UTC))
    po.run_plan(store.path, None, now=now, custom=[manual], environ=OFF)  # an ADR 0030 custom target, overdue
    after = _fabric(store, now)["kalshi_nhl.game_books"]
    assert (after.schedule_state, after.health, after.missed_count, after.receipt_ts) == \
        (base.schedule_state, base.health, base.missed_count, base.receipt_ts)


def test_coverage_counts_games_targets_and_mapping(store, monkeypatch):
    oct1(store, names=OCT1[:2] + ["KXNHLGAME-26OCT01SEACGY"])
    plan(store, MORNING)
    clock = Clock(datetime(2026, 10, 1, 17, 5, 20, tzinfo=UTC))
    monkeypatch.setattr(po, "fetch_json_result", Api(clock, routes(*OCT1)))
    capture(store, clock)
    cov = po.nhl_coverage(SnapshotStore.open_readonly(store.path), datetime(2026, 10, 1, 17, 10, tzinfo=UTC))
    assert cov["games"]["discovered"] == 3 and cov["targets"]["games"] == 3
    assert cov["targets"]["game_horizons"] == 6 and cov["targets"]["game_horizons_captured"] == 2
    assert cov["next"]["horizon"] in ("T-6h", "T-60m") and cov["fee"]["state"] == "FEE_UNSUPPORTED"
    assert cov["rules"]["clauses"]["resolved"] is True and cov["contract_terms"]["shootout"] == "RULES_UNRESOLVED"
    assert cov["settlement_reads"]["results"].startswith("withheld")
    assert "bid" not in json.dumps(cov) and "result\": \"yes" not in json.dumps(cov)


def test_dry_run_writes_nothing(store, capsys):
    oct1(store)
    before = store.path.read_bytes()
    out = po.nhl_dry_run(store.path, now=MORNING)
    assert out["writes"] == 0 and out["requests"] == 0 and len(out["would_plan"]) == 32
    assert store.path.read_bytes() == before and nhl_targets(store) == []
    assert po.main(["nhl-dry-run", "--db", str(store.path), "--now", MORNING.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["command"] == "nhl dry-run"


# --------------------------------------------------------------------------- install.sh keeps the switch


@pytest.mark.parametrize("value", ["on", "off"])
def test_install_keeps_the_nhl_switch_across_installs(tmp_path, value):
    from test_deploy_units import _run_env_section

    result = _run_env_section(tmp_path, f"NWS_USER_AGENT=ua (x@y.z)\nEDGE_LAB_KALSHI_NHL_CAPTURE={value}\n")
    assert result.returncode == 0, result.stderr
    assert f"EDGE_LAB_KALSHI_NHL_CAPTURE={value}" in result.stdout.splitlines()


def test_install_writes_no_nhl_switch_when_none_was_set_and_refuses_an_invalid_one(tmp_path):
    from test_deploy_units import _run_env_section

    result = _run_env_section(tmp_path, "NWS_USER_AGENT=ua (x@y.z)\n")
    assert result.returncode == 0 and "EDGE_LAB_KALSHI_NHL_CAPTURE" not in result.stdout  # the default (off)
    bad = _run_env_section(tmp_path, "NWS_USER_AGENT=ua (x@y.z)\nEDGE_LAB_KALSHI_NHL_CAPTURE=yes\n")
    assert bad.returncode != 0 and "must be on or off" in bad.stderr
