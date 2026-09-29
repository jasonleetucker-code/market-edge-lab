"""NHL on the sport-aware Odds planner (ADR 0039, issue #134): one ledger, one ceiling, NFL first.

Fixtures only: a scripted provider for both sports, and the published 2026-27 NHL schedule
(fetched once, offline, for the NHL_WORST_CASE derivation). No network, no credits."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FakeResponse
from edge_lab import cli, http, odds_api as oa, odds_consensus as oc, odds_pilot as op, odds_schedule as sch
from edge_lab.forward import eastern_date
from edge_lab.odds_schedule import QuotaReading, ScheduledEvent, SportDemand
from edge_lab.sources import get_source
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FAKE = "FAKEnhlKEY0123456789abcd"  # not a real key
KEY_VAR = get_source("the_odds_api").credential_env_var
ENV_ON = {KEY_VAR: FAKE, "EDGE_LAB_ODDS_NHL": "on"}
ENV_OFF = {KEY_VAR: FAKE}
NFL, NHL = sch.NFL, sch.NHL
NHL_SETTINGS = op.RunnerSettings.for_sport(NHL)
NFL_SETTINGS = op.RunnerSettings()
FIXTURE = Path(__file__).parent / "fixtures" / "odds_api" / "nhl_schedule_2026_27_nhle.json"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def nhl_event(eid: str, commence: str, home: str = "Bruins", away: str = "Rangers") -> dict:
    return {"id": eid, "sport_key": NHL, "sport_title": "NHL", "commence_time": commence,
            "home_team": home, "away_team": away}


def nfl_event(eid: str, commence: str) -> dict:
    return {"id": eid, "sport_key": NFL, "sport_title": "NFL", "commence_time": commence,
            "home_team": "Bills", "away_team": "Jets"}


# Sep 30 2026 (EDT): 19:30, 19:30, 22:00 ET, from the published schedule; Oct 1: 19:00 x3.
NHL_EVENTS = [nhl_event("h1", "2026-09-30T23:30:00Z", "Senators", "Blackhawks"),
              nhl_event("h2", "2026-09-30T23:30:00Z", "Flyers", "Penguins"),
              nhl_event("h3", "2026-10-01T02:00:00Z", "Kraken", "Ducks"),
              nhl_event("h4", "2026-10-01T23:00:00Z", "Bruins", "Rangers"),
              nhl_event("h5", "2026-10-01T23:00:00Z", "Devils", "Islanders"),
              nhl_event("h6", "2026-10-01T23:00:00Z", "Capitals", "Hurricanes")]
# NFL week 5 shape (EDT): TNF Thu 20:15, Sun 09:30 (international), 13:00, 16:25, SNF 20:20, MNF 20:15: six
# kickoff groups, which reproduces the measured 2026-09-29 production projection for October (worst 450,
# expected 270). NFL_FIVE drops the early game.
NFL_EVENTS = [nfl_event("n1", "2026-10-02T00:15:00Z"), nfl_event("n0", "2026-10-04T13:30:00Z"),
              nfl_event("n2", "2026-10-04T17:00:00Z"), nfl_event("n3", "2026-10-04T20:25:00Z"),
              nfl_event("n4", "2026-10-05T00:20:00Z"), nfl_event("n5", "2026-10-06T00:15:00Z")]
NFL_FIVE = [e for e in NFL_EVENTS if e["id"] != "n0"]


class Response(FakeResponse):
    def __init__(self, body: bytes, *, url: str, headers: dict[str, str]):
        super().__init__(body, url=url)
        self.headers = {"Content-Type": "application/json", **headers}


class TwoSportProvider:
    """A scripted The Odds API for NFL and NHL: events and sports are free; odds cost markets x regions."""

    def __init__(self, *, nhl=None, nfl=None, used: int = 45, remaining: int = 455, draw: bool = False,
                 events_error: dict | None = None):
        self.events = {NHL: list(NHL_EVENTS if nhl is None else nhl), NFL: list(NFL_EVENTS if nfl is None else nfl)}
        self.used, self.remaining, self.draw = used, remaining, draw
        self.events_error = events_error or {}
        self.calls: list[str] = []

    def paid(self, sport: str | None = None) -> list[str]:
        return [c for c in self.calls if "/odds/" in c and (sport is None or f"/{sport}/" in c)]

    def headers(self, last: int) -> dict[str, str]:
        return {"X-Requests-Remaining": str(self.remaining), "X-Requests-Used": str(self.used),
                "X-Requests-Last": str(last)}

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert q.get("apiKey") == FAKE
        if parts.path == "/v4/sports/":
            return Response(b"[]", url=url, headers=self.headers(0))
        sport = parts.path.split("/")[3]
        lo, hi = q.get("commenceTimeFrom"), q.get("commenceTimeTo")
        chosen = [e for e in self.events[sport] if (lo is None or e["commence_time"] >= lo)
                  and (hi is None or e["commence_time"] <= hi)]
        if parts.path.endswith("/events/"):
            if sport in self.events_error:
                raise self.events_error[sport]
            return Response(json.dumps(chosen).encode(), url=url, headers=self.headers(0))
        assert parts.path.endswith("/odds/"), url
        markets, regions = q["markets"].split(","), q["regions"].split(",")
        if sport == NHL:
            assert markets == ["h2h"] and regions == ["us"], "NHL is h2h / us only"
        cost = len(markets) * len(regions) if chosen else 0
        self.used += cost
        self.remaining -= cost
        body = [self.odds_for(e, markets) for e in chosen]
        return Response(json.dumps(body).encode(), url=url, headers=self.headers(cost))

    def odds_for(self, event: dict, markets: list[str]) -> dict:
        books = []
        for key in ("draftkings", "fanduel"):
            outcomes = [{"name": event["home_team"], "price": -140}, {"name": event["away_team"], "price": 120}]
            if self.draw and event["sport_key"] == NHL:
                outcomes.append({"name": "Draw", "price": 380})  # a regulation-time three-way line
            mk = [{"key": "h2h", "outcomes": outcomes}]
            if "spreads" in markets:
                mk.append({"key": "spreads", "outcomes": [{"name": event["home_team"], "price": -110, "point": -3.5},
                                                          {"name": event["away_team"], "price": -110, "point": 3.5}]})
            if "totals" in markets:
                mk.append({"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 44.5},
                                                         {"name": "Under", "price": -110, "point": 44.5}]})
            books.append({"key": key, "title": key, "last_update": event["commence_time"], "markets": mk})
        return {k: event[k] for k in ("id", "sport_key", "commence_time", "home_team", "away_team")} | {
            "bookmakers": books}


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class ReceiptClock(datetime):
    """The transport stamps receipts with the wall clock; tests that measure receipt ages pin it."""

    at = datetime(2026, 9, 30, 22, 35, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.at if tz is not None else cls.at.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real network call: {request.full_url}")

    monkeypatch.setattr(oa, "_no_redirect_opener", refuse)
    monkeypatch.delenv(KEY_VAR, raising=False)
    monkeypatch.delenv("EDGE_LAB_ODDS_NHL", raising=False)


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "edge.sqlite3", tmp_path / "odds_quota.json"


def run(paths, provider, at, settings=NHL_SETTINGS, env=ENV_ON, **kw):
    return op.run_tick(paths[0], paths[1], settings, clock=Clock(at), opener=provider, environ=env, **kw)


def rows(paths, sport):
    return SnapshotStore(paths[0]).odds_targets(sport=sport)


def states(paths, sport) -> dict[str, str]:
    return {r["target_id"]: r["state"] for r in rows(paths, sport)}


# ------------------------------------------------------------------ policies


def test_policies_one_table_nfl_unchanged_and_nhl_h2h_us_t60m():
    nfl, nhl = sch.SPORT_POLICIES[NFL], sch.SPORT_POLICIES[NHL]
    assert op.RunnerSettings.for_sport(NFL) == op.RunnerSettings()  # NFL's defaults are the historical ones
    assert nfl.config() == sch.PilotConfig() and nfl.rank == 1 and nfl.switch_env is None and nfl.state_scope is None
    assert (nhl.rank, nhl.markets, nhl.regions, [o.label for o in nhl.offsets]) == (2, ("h2h",), ("us",), ["T-60m"])
    assert nhl.switch_env == "EDGE_LAB_ODDS_NHL" and nhl.state_scope == NHL and nhl.record_prior_misses
    assert NHL_SETTINGS.cost_per_call == 1 and NFL_SETTINGS.cost_per_call == 3
    assert nhl.merge_window == nfl.merge_window == timedelta(minutes=20)
    # One ceiling, one reserve, for every sport.
    assert {p.config().ceiling for p in sch.SPORT_POLICIES.values()} == {450}
    assert {p.config().reserve_credits for p in sch.SPORT_POLICIES.values()} == {3}


@pytest.mark.parametrize("value, on", [("on", True), (" on ", True), ("off", False), ("ON", False), ("1", False),
                                       ("", False), (None, False)])
def test_the_nhl_switch_is_on_only_for_exactly_on(value, on):
    env = {} if value is None else {"EDGE_LAB_ODDS_NHL": value}
    assert sch.switch_on(sch.SPORT_POLICIES[NHL], env) is on
    assert sch.switch_on(sch.SPORT_POLICIES[NFL], env)  # NFL has no switch


# ------------------------------------------------------------------ NHL_WORST_CASE derivation


def _published() -> list[ScheduledEvent]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [ScheduledEvent(gid, NHL, datetime.fromisoformat(t.replace("Z", "+00:00")), home, away)
            for t, gid, away, home in doc["games"]]


def test_nhl_worst_case_bounds_the_published_2026_27_schedule_with_margin():
    """Re-derives the numbers ADR 0039 records: every class, coalesced by this planner."""
    games = _published()
    assert len(games) == 1344  # 32 teams x 84 games / 2
    week_max, day_max, avg = 0, [0] * 7, 0.0
    for off in ("60m", "6h", "24h"):
        cfg = sch.SPORT_POLICIES[NHL].config(sch.parse_offsets(off))
        per: dict = {}
        for g in games:
            per.setdefault(eastern_date(g.commence_utc), []).append(g)
        groups = {d: len(sch.coalesce(sch.plan_targets(es, cfg.offsets), cfg)) for d, es in per.items()}
        # Kickoff dates never merge across midnight: per-date counts add up to the season's slots.
        assert sum(groups.values()) == len(sch.coalesce(sch.plan_targets(games, cfg.offsets), cfg))
        first, last = min(groups), max(groups)
        days = [first + timedelta(i) for i in range((last - first).days + 1)]
        week_max = max(week_max, max(sum(groups.get(d + timedelta(i), 0) for i in range(7)) for d in days))
        for d in days:
            day_max[d.weekday()] = max(day_max[d.weekday()], groups.get(d, 0))
        avg = max(avg, sum(groups.values()) / len(days) * 7)
    assert (week_max, day_max) == (37, [7, 10, 5, 6, 7, 9, 8])  # measured; ADR 0039
    assert round(avg, 2) == 28.0
    a = sch.NHL_WORST_CASE
    assert a.max_groups_per_week >= week_max + 3
    assert all(m >= d + 1 for m, d in zip(a.max_groups_by_weekday, day_max))
    assert a.expected_groups_per_week >= avg


# ------------------------------------------------------------------ coalescing and the quiet window


def _nhl(eid, when):
    return ScheduledEvent(eid, NHL, when)


def test_nhl_games_at_one_start_form_one_group_and_separate_starts_stay_separate():
    cfg6 = sch.SPORT_POLICIES[NHL].config(sch.parse_offsets("6h"))
    games = [_nhl(f"a{i}", utc(2026, 10, 3, 23, 0)) for i in range(7)] + [_nhl("b", utc(2026, 10, 3, 23, 30)),
                                                                        _nhl("c", utc(2026, 10, 4, 0, 0)),
                                                                        _nhl("d", utc(2026, 10, 4, 2, 0)),
                                                                        _nhl("e", utc(2026, 10, 4, 2, 30))]
    slots = sch.coalesce(sch.plan_targets(games, cfg6.offsets), cfg6)
    # T-6h: 19:00 (x7) | 19:30 | 20:00 | 22:00 | 22:30 ET -> five groups; the seven 19:00 games are one call.
    assert [len(s.members) for s in slots] == [7, 1, 1, 1, 1]
    # T-60m: 19:00 and 19:30 both fall in the 17:40-18:35 ET quiet window and move to 18:35 (one call);
    # 20:00 (19:00), 22:00 (21:00) and 22:30 (21:30) stay separate at a 20-minute merge window.
    cfg = sch.SPORT_POLICIES[NHL].config()
    slots = sch.coalesce(sch.plan_targets(games, cfg.offsets), cfg)
    assert [(sch.iso_z(s.due_utc), len(s.members)) for s in slots] == [
        ("2026-10-03T22:35:00Z", 8), ("2026-10-03T23:00:00Z", 1), ("2026-10-04T01:00:00Z", 1),
        ("2026-10-04T01:30:00Z", 1)]


def test_nhl_targets_in_the_quiet_window_shift_exactly_as_nfl_targets_do():
    for when in (utc(2026, 10, 3, 23, 0), utc(2026, 10, 3, 23, 30), utc(2026, 12, 5, 23, 45), utc(2026, 10, 3, 22, 40)):
        hockey = sch.plan_targets([_nhl("x", when)], sch.SPORT_POLICIES[NHL].offsets)[0]
        football = sch.plan_targets([ScheduledEvent("x", NFL, when)], sch.DEFAULT_OFFSETS)[-1]
        assert hockey.offset_label == football.offset_label == "T-60m"
        due = sch.effective_due(hockey, sch.SPORT_POLICIES[NHL].config())
        assert due == sch.effective_due(football) and not sch.in_quiet_window(due)


def test_an_nhl_tick_inside_a_protected_window_does_nothing(paths):
    provider = TwoSportProvider()
    code, report = run(paths, provider, utc(2026, 9, 30, 22, 0))  # 18:00 EDT
    assert code == 0 and report["state"] == "DEFERRED_CAPTURE_WINDOW" and provider.calls == []
    assert not paths[0].exists() and not paths[1].exists()


# ------------------------------------------------------------------ the joint proof (pure)


def _slots(sport, cfg, events, now):
    return sch.coalesce([t for t in sch.plan_targets(events, cfg.offsets) if not sch.is_expired(t, now, cfg)], cfg)


def _nfl_week(thursday: datetime, early: bool = True) -> list[ScheduledEvent]:
    """ET kickoffs (EDT): TNF 20:15, (Sun 09:30), Sun 13:00, 16:25, SNF 20:20, MNF 20:15."""
    kick = [thursday.replace(hour=20, minute=15)]
    kick += [(thursday + timedelta(days=3)).replace(hour=9, minute=30)] if early else []
    kick += [(thursday + timedelta(days=3)).replace(hour=13),
            (thursday + timedelta(days=3)).replace(hour=16, minute=25),
            (thursday + timedelta(days=3)).replace(hour=20, minute=20), (thursday + timedelta(days=4)).replace(hour=20, minute=15)]
    return [ScheduledEvent(f"f{thursday:%m%d}{i}", NFL, (k + timedelta(hours=4)).replace(tzinfo=UTC))
            for i, k in enumerate(kick)]


def _demands(now, nfl_events, nfl_horizon, nhl_events, nhl_horizon, nhl_offsets="60m"):
    nfl_cfg = sch.SPORT_POLICIES[NFL].config()
    nhl_cfg = sch.SPORT_POLICIES[NHL].config(sch.parse_offsets(nhl_offsets))
    return [SportDemand(NFL, 1, _slots(NFL, nfl_cfg, nfl_events, now), 3, nfl_horizon, nfl_cfg),
            SportDemand(NHL, 2, _slots(NHL, nhl_cfg, nhl_events, now), 1, nhl_horizon, nhl_cfg)]


def test_nfl_alone_in_the_joint_proof_is_exactly_budget_and_nhl_never_changes_nfl():
    now = utc(2026, 10, 1, 12)
    nfl_events = _nfl_week(datetime(2026, 10, 1))
    quota = QuotaReading("READY", local_used=45, provider_used=45, provider_remaining=455)
    nfl, nhl = _demands(now, nfl_events, utc(2026, 10, 6), _published()[:60], utc(2026, 10, 9))
    alone = sch.budget(nfl.slots, now=now, quota=quota, cost_per_call=3, known_horizon=nfl.known_horizon)
    joint = sch.joint_budget([nfl, nhl], now=now, quota=quota)
    nfl_view = joint.proof_for(NFL)
    for field in ("state", "classes", "admitted_slot_ids", "skipped_slot_ids", "headroom", "unknown_window"):
        assert getattr(nfl_view, field) == getattr(alone, field), field
    assert sch.joint_budget([nfl], now=now, quota=quota).proof_for(NFL).to_dict() == alone.to_dict() | {
        "proven": alone.proven}


def test_october_with_the_nfl_worst_case_filling_the_ceiling_admits_zero_nhl():
    """The measured 2026-09-29 production case: NFL known to 2026-10-06, its unknown weeks reserved."""
    now = utc(2026, 10, 1)
    quota = QuotaReading("READY", local_used=0, provider_used=0, provider_remaining=500)
    nfl, nhl = _demands(now, _nfl_week(datetime(2026, 10, 1)), utc(2026, 10, 6, 0, 15),
                        [g for g in _published() if g.commence_utc < utc(2026, 10, 9)], utc(2026, 10, 9))
    joint = sch.joint_budget([nfl, nhl], now=now, quota=quota)
    nfl_share, nhl_share = joint.share(NFL), joint.share(NHL)
    assert not nfl_share.fits  # NFL's own worst case does not fully fit the ceiling
    assert nhl_share.admitted_slot_ids == () and nhl_share.available == 0 and nhl_share.blocked_by == NFL
    assert nhl_share.reserved_unknown_credits == 0 and len(nhl_share.skipped_slot_ids) == len(
        [s for s in nhl.slots if s.due_utc < utc(2026, 11, 1)])
    assert joint.worst_case_month_credits == 450  # the whole ceiling, as measured in production
    assert joint.expected_month_credits == 270
    assert any("does not fully fit" in n for n in joint.proof_for(NHL).notes)


def test_nhl_gets_nothing_even_from_a_remainder_smaller_than_one_nfl_call():
    """2 credits left after NFL cannot pay an NFL call (3) but must not go to NHL while NFL is short."""
    now = utc(2026, 10, 1, 12)
    nfl, nhl = _demands(now, _nfl_week(datetime(2026, 10, 1)), None, _published()[:40], utc(2026, 10, 9))
    for used in range(0, 451, 7):
        quota = QuotaReading("READY", local_used=used, provider_used=used, provider_remaining=500 - used)
        joint = sch.joint_budget([nfl, nhl], now=now, quota=quota)
        if not joint.share(NFL).fits:
            assert joint.share(NHL).admitted_slot_ids == () and joint.share(NHL).reserved_unknown_credits == 0


def test_the_combined_proof_never_exceeds_the_ceiling_and_nfl_admissions_never_move():
    rng = random.Random(134)
    games = _published()
    for _ in range(300):
        now = utc(2026, rng.choice([9, 10, 11]), rng.randint(1, 28), rng.randint(0, 23))
        used = rng.randint(0, 460)
        outstanding = rng.choice([0, 0, 1, 3])
        quota = QuotaReading(rng.choice(["READY", "READY", "READY", "QUOTA_EXHAUSTED"]), local_used=used,
                             provider_used=max(0, used - rng.randint(0, 3)),
                             provider_remaining=max(0, 500 - used - rng.randint(0, 20)), outstanding=outstanding)
        thursdays = [now.replace(hour=0, tzinfo=None) + timedelta(days=d) for d in range(0, 35, 7)]
        nfl_events = [e for t in thursdays for e in _nfl_week(t)]
        nhl_events = [g for g in games if now <= g.commence_utc <= now + timedelta(days=rng.randint(1, 35))]
        offsets = rng.choice(["60m", "6h,60m", "24h,6h,60m"])
        nfl_h = rng.choice([None, now + timedelta(days=rng.randint(0, 20))])
        nhl_h = rng.choice([None, now + timedelta(days=rng.randint(0, 35))])
        nfl, nhl = _demands(now, nfl_events, nfl_h, nhl_events, nhl_h, offsets)
        joint = sch.joint_budget([nhl, nfl], now=now, quota=quota)  # order given does not matter: rank does
        alone = sch.budget(nfl.slots, now=now, quota=quota, cost_per_call=3, known_horizon=nfl_h)
        assert joint.share(NFL).admitted_slot_ids == alone.admitted_slot_ids
        assert joint.share(NFL).classes == alone.classes
        if joint.state == "PROVEN":
            assert joint.worst_case_month_credits <= 450
            assert joint.worst_case_month_credits - joint.spent <= quota.provider_remaining - quota.outstanding
            nhl_share = joint.share(NHL)
            assert nhl_share.admitted_credits + nhl_share.reserved_unknown_credits <= nhl_share.available
            if not joint.share(NFL).fits:
                assert nhl_share.admitted_credits == 0
        else:
            assert joint.share(NHL).admitted_slot_ids == () or joint.state == "QUOTA_EXHAUSTED"


def test_unknown_quota_admits_nothing_for_any_sport():
    now = utc(2026, 9, 30, 12)
    nfl, nhl = _demands(now, _nfl_week(datetime(2026, 10, 1)), utc(2026, 10, 6), _published()[:20], utc(2026, 10, 9))
    joint = sch.joint_budget([nfl, nhl], now=now, quota=QuotaReading("QUOTA_UNKNOWN"))
    assert joint.state == "QUOTA_UNKNOWN" and joint.worst_case_month_credits is None
    assert all(s.admitted_slot_ids == () for s in joint.shares)


def test_a_rank_or_ceiling_collision_is_refused():
    now = utc(2026, 9, 30, 12)
    nfl, nhl = _demands(now, [], None, [], None)
    with pytest.raises(ValueError):
        sch.joint_budget([nfl, replace(nhl, rank=1)], now=now, quota=QuotaReading("QUOTA_UNKNOWN"))
    with pytest.raises(ValueError):
        sch.joint_budget([nfl, replace(nhl, config=replace(nhl.config, ceiling=449))], now=now,
                         quota=QuotaReading("QUOTA_UNKNOWN"))


# ------------------------------------------------------------------ the runner: switch, policy, isolation


def test_switch_off_makes_zero_requests_and_writes_nothing(paths, tmp_path, capsys):
    provider = TwoSportProvider()
    for env in (ENV_OFF, {**ENV_OFF, "EDGE_LAB_ODDS_NHL": "off"}, {**ENV_OFF, "EDGE_LAB_ODDS_NHL": "yes"}):
        code, report = run(paths, provider, utc(2026, 9, 30, 12), env=env)
        assert code == 0 and report["state"] == "DISABLED" and report["paid_calls"] == 0
        code, report = op.smoke(paths[0], paths[1], NHL_SETTINGS, clock=Clock(utc(2026, 9, 30, 12)), opener=provider,
                                environ=env)
        assert report["state"] == "DISABLED" and report["paid_calls"] == 0
    assert provider.calls == [] and list(tmp_path.iterdir()) == []
    # Through the CLI (the production path): the env switch is absent, so the NHL line does nothing.
    assert cli.main(["odds", "run", "--db", str(paths[0]), "--ledger", str(paths[1]), "--sport", NHL,
                     "--markets", "h2h", "--regions", "us", "--offsets", "60m"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "DISABLED" and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("markets, regions", [(("h2h", "spreads"), ("us",)), (("totals",), ("us",)),
                                              (("h2h",), ("us", "uk")), ((), ("us",))])
def test_nhl_may_request_h2h_us_only(paths, markets, regions):
    provider = TwoSportProvider()
    settings = replace(NHL_SETTINGS, markets=markets, regions=regions)
    code, report = run(paths, provider, utc(2026, 9, 30, 12), settings=settings)
    assert code == 1 and report["state"] == "POLICY_REFUSED" and provider.calls == []
    code, report = op.smoke(paths[0], paths[1], settings, clock=Clock(utc(2026, 9, 30, 12)), opener=provider,
                            environ=ENV_ON)
    assert report["state"] == "POLICY_REFUSED" and provider.calls == []


def test_a_sport_without_a_policy_sends_nothing(paths):
    provider = TwoSportProvider()
    code, report = run(paths, provider, utc(2026, 9, 30, 12), settings=op.RunnerSettings(sport="basketball_nba"))
    assert code == 1 and report["state"] == "UNSUPPORTED_SPORT" and provider.calls == []


def test_nfl_and_nhl_events_and_targets_never_cross(paths):
    provider = TwoSportProvider()
    # An NFL event leaking into the NHL listing is skipped by sport_key, never planned as hockey.
    provider.events[NHL].append(nfl_event("leak", "2026-10-01T00:00:00Z") | {"sport_key": NFL})
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    code, report = run(paths, provider, utc(2026, 9, 30, 12, 15))
    assert code == 0 and report["discovery"]["events"] == 6
    nhl_rows, nfl_rows = rows(paths, NHL), rows(paths, NFL)
    assert nhl_rows and nfl_rows
    assert {r["event_id"] for r in nhl_rows} == {e["id"] for e in NHL_EVENTS}
    assert {r["event_id"] for r in nfl_rows} == {e["id"] for e in NFL_EVENTS}
    assert all(r["target_id"].startswith(f"{NHL}:") for r in nhl_rows)
    assert all(r["target_id"].startswith(f"{NFL}:") for r in nfl_rows)
    assert {r["offset_label"] for r in nhl_rows} == {"T-60m"}
    store = SnapshotStore(paths[0])
    assert json.loads(store.latest_snapshot(source="the_odds_api", kind="events", entity_id=NHL)["payload_json"])[
        "sport"] == NHL


def test_september_nhl_t60m_is_admitted_and_captured_with_h2h_only(paths):
    provider = TwoSportProvider(used=45, remaining=455)  # the measured 2026-09-29 production reading
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    code, report = run(paths, provider, utc(2026, 9, 30, 12, 15))
    joint = report["joint_budget"]
    nfl_share, nhl_share = joint["sports"]
    assert nfl_share["sport"] == NFL and nfl_share["fits"] and nhl_share["sport"] == NHL
    # September: NFL has nothing left to spend (its next targets are October UTC), so NHL may use
    # min(450 - 45, 455) - 3 = 402.
    assert nhl_share["available"] == 402 and report["budget"]["headroom"] == 402
    assert report["budget"]["admitted_slots"] == 1  # the 19:30 ET pair at 18:35 ET; 22:00 ET's T-60m is October
    # 18:35 ET: the 19:30 pair is captured in one h2h call costing 1 credit.
    code, report = run(paths, provider, utc(2026, 9, 30, 22, 35))
    assert report["state"] == "CAPTURED" and report["fired"]["targets"] == 2 and report["fired"]["credits_last"] == 1
    assert len(provider.paid(NHL)) == 1 and "markets=h2h&" in provider.paid(NHL)[0] + "&"
    captured = [r for r in rows(paths, NHL) if r["state"] == "CAPTURED"]
    assert {r["event_id"] for r in captured} == {"h1", "h2"}
    assert all(json.loads(r["detail_json"])["offset"] == "T-60m" for r in captured)


def test_an_nhl_tick_in_october_is_admitted_nothing_while_nfl_reserves_the_ceiling(paths):
    provider = TwoSportProvider(used=0, remaining=500)
    at = utc(2026, 10, 1, 0, 5)
    run(paths, provider, at, settings=NFL_SETTINGS)
    code, report = run(paths, provider, at)
    assert report["budget"]["admitted_slots"] == 0 and report["joint_budget"]["sports"][1]["blocked_by"] == NFL
    # As in production, every tick runs NFL first, then NHL: NFL captures its TNF T-24h and T-6h.
    for tick in (utc(2026, 10, 1, 0, 15), utc(2026, 10, 1, 18, 15), utc(2026, 10, 1, 22, 35)):
        run(paths, provider, tick, settings=NFL_SETTINGS)
        code, report = run(paths, provider, tick)
    assert len(provider.paid(NFL)) == 2
    # 18:35 ET: the Oct 1 19:00 ET group's T-60m is due, but NFL's worst case still fills the ceiling.
    assert report["state"] == "SKIPPED_BUDGET" and report["paid_calls"] == 0 and provider.paid(NHL) == []
    assert {r["state"] for r in rows(paths, NHL) if r["event_id"] in ("h4", "h5", "h6")} == {"SKIPPED_BUDGET"}


@pytest.mark.parametrize("nfl_events, nhl_spends", [(NFL_EVENTS, False), (NFL_FIVE, True)])
def test_nhl_budget_exhaustion_changes_no_nfl_target_or_history(tmp_path, nfl_events, nhl_spends):
    """With six NFL groups NHL is exhausted (zero); with five it takes only what NFL's full worst case leaves.
    Either way every NFL target, transition and paid call is the same as with no NHL at all."""
    def nfl_history(p):
        store = SnapshotStore(p[0])
        return {r["target_id"]: [(x["state"], x["at_utc"], x["reason"], x["slot_id"]) for x in
                                 store.odds_transitions(r["target_id"])] for r in store.odds_targets(sport=NFL)}

    ticks = [utc(2026, 10, 1, 4) + timedelta(minutes=15 * i) for i in range(0, 4 * 24 * 2, 3)]
    alone = (tmp_path / "a.sqlite3", tmp_path / "a.json")
    both = (tmp_path / "b.sqlite3", tmp_path / "b.json")
    p1 = TwoSportProvider(used=0, remaining=500, nfl=nfl_events)
    p2 = TwoSportProvider(used=0, remaining=500, nfl=nfl_events)
    for at in ticks:
        run(alone, p1, at, settings=NFL_SETTINGS)
        run(both, p2, at, settings=NFL_SETTINGS)
        run(both, p2, at, settings=NHL_SETTINGS)
    assert nfl_history(alone) == nfl_history(both) and nfl_history(alone)
    assert p1.paid(NFL) == p2.paid(NFL) and p1.paid(NFL)
    assert bool(p2.paid(NHL)) is nhl_spends
    assert p2.used <= 450


def test_quota_unknown_means_no_paid_nhl_read(paths):
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12))
    ledger = json.loads(paths[1].read_text())
    ledger["quota_known"] = False
    paths[1].write_text(json.dumps(ledger))
    provider.headers = lambda last: {}  # no quota headers anywhere: the free reconcile cannot help
    code, report = run(paths, provider, utc(2026, 9, 30, 22, 35))
    assert report["state"] == "QUOTA_UNKNOWN" and provider.paid() == []


# ------------------------------------------------------------------ opening night, reschedules


def test_opening_night_targets_past_their_deadline_are_missed_and_never_relabelled(paths):
    provider = TwoSportProvider()
    first = utc(2026, 9, 30, 23, 10)  # 19:10 ET: the 19:30 games' T-60m (18:35 ET) deadline 19:05 ET has passed
    run(paths, provider, first, settings=NFL_SETTINGS)
    code, report = run(paths, provider, first)
    assert report["targets"]["missed_before_planning"] == 2
    missed = {r["event_id"]: r for r in rows(paths, NHL) if r["state"] == "MISSED"}
    assert set(missed) == {"h1", "h2"}
    assert all(r["reason"].startswith("NOT_COLLECTED_BEFORE_ACTIVATION") for r in missed.values())
    # Later ticks, even with offers available, never capture or relabel them.
    for at in (first + timedelta(minutes=15), utc(2026, 10, 1, 1, 0), utc(2026, 10, 1, 1, 15)):
        run(paths, provider, at)
    after = {r["event_id"]: r for r in rows(paths, NHL)}
    assert after["h1"]["state"] == after["h2"]["state"] == "MISSED"
    assert [x["state"] for x in SnapshotStore(paths[0]).odds_transitions(missed["h1"]["target_id"])] == [
        "PLANNED", "MISSED"]
    # 22:00 ET: still genuinely due after activation, so planned for real (T-60m is October: NFL decides).
    assert after["h3"]["state"] in ("PLANNED", "CAPTURED", "SKIPPED_BUDGET")


def test_a_game_first_listed_after_its_deadline_is_missed_with_its_own_reason(paths):
    provider = TwoSportProvider(nhl=NHL_EVENTS[:1])
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))  # activation
    provider.events[NHL].append(nhl_event("late", "2026-10-01T00:00:00Z"))  # 20:00 ET, listed at 19:40 ET
    code, report = run(paths, provider, utc(2026, 9, 30, 23, 40))
    assert report["discovery"]["state"] == "REFRESHED"
    late = [r for r in rows(paths, NHL) if r["event_id"] == "late"]
    assert late and late[0]["state"] == "MISSED" and late[0]["reason"].startswith("NOT_DISCOVERED_BEFORE_DEADLINE")


def test_an_nhl_reschedule_supersedes_the_old_targets(paths):
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12))
    old = {r["target_id"] for r in rows(paths, NHL) if r["event_id"] == "h4"}
    provider.events[NHL][3] = nhl_event("h4", "2026-10-02T23:00:00Z")  # postponed a day
    code, report = run(paths, provider, utc(2026, 9, 30, 18, 1))  # six hours on: a new discovery
    assert report["targets"]["superseded_now"] == 1
    now_rows = {r["target_id"]: r for r in rows(paths, NHL) if r["event_id"] == "h4"}
    assert {now_rows[t]["state"] for t in old} == {"SUPERSEDED"}
    assert any(r["state"] == "PLANNED" and r["target_utc"] == "2026-10-02T22:00:00Z" for r in now_rows.values())


# ------------------------------------------------------------------ per-sport runner state


def test_an_nhl_discovery_failure_never_marks_nfl_degraded_or_stale(paths):
    provider = TwoSportProvider(events_error={NHL: URLError("down")})
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    code, report = run(paths, provider, utc(2026, 9, 30, 12, 15))
    assert code == 1 and report["discovery"]["state"] == "FAILED"
    state_file = paths[1].with_name(paths[1].name + ".pilot.json")
    data = json.loads(state_file.read_text())
    assert data["discovery_outcome"] == "OK" and data["sports"][NHL]["discovery_outcome"] == "FAILED"
    nfl = op.dashboard_status(paths[0], paths[1], state_file, now=utc(2026, 9, 30, 12, 20))
    nhl = op.dashboard_status(paths[0], paths[1], state_file, now=utc(2026, 9, 30, 12, 20), settings=NHL_SETTINGS)
    assert nfl["discovery"]["outcome"] == "OK" and nhl["discovery"]["outcome"] == "FAILED"
    # And the reverse: an NFL failure never reaches NHL's state.
    provider.events_error = {NFL: URLError("down")}
    run(paths, provider, utc(2026, 9, 30, 18, 30), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 18, 45))
    data = json.loads(state_file.read_text())
    assert data["discovery_outcome"] == "FAILED" and data["sports"][NHL]["discovery_outcome"] == "OK"


def test_a_cost_anomaly_on_any_sport_blocks_every_sports_paid_calls(paths):
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    original = provider.headers
    provider.headers = lambda last: original(5 if last == 1 else last)  # charged 5 for a 1-credit NHL call
    code, report = run(paths, provider, utc(2026, 9, 30, 22, 35))
    assert report["state"] == "COST_ANOMALY"
    state = json.loads(paths[1].with_name(paths[1].name + ".pilot.json").read_text())
    assert state["cost_block"]["reason"] == "COST_ANOMALY"  # shared, top level
    code, report = run(paths, provider, utc(2026, 10, 1, 23, 15), settings=NFL_SETTINGS)  # NFL TNF T-60m due
    assert report["state"] == "COST_BLOCKED" and provider.paid(NFL) == []


# ------------------------------------------------------------------ h2h honesty


def test_an_nhl_h2h_with_a_draw_fails_honestly_and_is_recorded(paths):
    provider = TwoSportProvider(draw=True)
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    code, report = run(paths, provider, utc(2026, 9, 30, 22, 35))
    assert report["state"] == "CAPTURED"
    store = SnapshotStore(paths[0])
    captured = [r for r in store.odds_targets(sport=NHL) if r["state"] == "CAPTURED"]
    assert captured and all(json.loads(r["detail_json"])["h2h_not_two_way"] == 6 for r in captured)  # 2 books x 3
    health = {r["source_id"]: r for r in store.latest_source_health()}["the_odds_api"]
    assert health["status"] == "partial" and "not a clean two-way market" in health["anomalies_json"]
    parsed = oa.parse_odds([provider.odds_for(NHL_EVENTS[0], ["h2h"])], odds_format="american")
    paired, unpaired = oa.pair_offers(parsed)
    assert paired == () and {u.status for u in unpaired} == {oa.PairingStatus.NOT_TWO_WAY}


@pytest.mark.parametrize("outcomes", [
    [{"name": "Bruins", "price": -140}, {"name": "Rangers", "price": 120}, {"name": "Draw", "price": 380}],
    [{"name": "Bruins", "price": -140}, {"name": "Tie", "price": 380}],
    [{"name": "Bruins", "price": 150}, {"name": "Rangers", "price": 150}, {"name": "Flyers", "price": 900}],
])
def test_nhl_h2h_that_is_not_two_way_is_unsupported_in_the_consensus(outcomes):
    event = nhl_event("x", "2026-10-03T23:00:00Z") | {"bookmakers": [
        {"key": b, "title": b, "markets": [{"key": "h2h", "outcomes": outcomes}]} for b in ("draftkings", "fanduel")]}
    parsed = oa.parse_odds([event], odds_format="american")
    paired, unpaired = oa.pair_offers(parsed)
    assert paired == () and {u.status for u in unpaired} == {oa.PairingStatus.NOT_TWO_WAY}
    assert not oa.consensus_by_market(parsed)
    two_way = event | {"bookmakers": [{"key": b, "title": b, "markets": [{"key": "h2h", "outcomes": [
        {"name": "Bruins", "price": -140}, {"name": "Rangers", "price": 120}]}]} for b in ("draftkings", "fanduel")]}
    assert len(oa.pair_offers(oa.parse_odds([two_way], odds_format="american"))[0]) == 2
    assert oc.LABEL_PROXY_SPORTS == ("americanfootball_nfl",)  # NHL is never an EXP-002 label proxy


# ------------------------------------------------------------------ plan and status


def test_nhl_plan_offline_shows_the_joint_proof_and_changes_nothing(paths):
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    before = paths[0].read_bytes(), paths[1].read_bytes()
    code, report = op.plan(paths[0], paths[1], NHL_SETTINGS, offline=True, clock=Clock(utc(2026, 9, 30, 13)))
    assert code == 0 and report["paid_calls"] == 0 and report["cost_per_call"] == 1
    assert [s["sport"] for s in report["joint_budget"]["sports"]] == [NFL, NHL]
    assert report["joint_projection_next_month"]["sports"][1]["blocked_by"] == NFL  # October: NFL first
    assert report["assumption"]["name"] == "nhl_2026_27_v1"
    assert (paths[0].read_bytes(), paths[1].read_bytes()) == before


def test_odds_status_reports_each_sports_coverage_separately(paths, capsys, monkeypatch):
    monkeypatch.setattr(http, "datetime", ReceiptClock)
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    run(paths, provider, utc(2026, 9, 30, 22, 35))
    nhl = op.coverage_status(paths[0], now=utc(2026, 9, 30, 22, 40), settings=NHL_SETTINGS)
    nfl = op.coverage_status(paths[0], now=utc(2026, 9, 30, 22, 40), settings=NFL_SETTINGS)
    assert nhl["sport"] == NHL and nhl["captured"] == 2 and nhl["attempted"] == 2 and nhl["new_24h"] == 2
    assert nhl["stale"] is False and nhl["due"] == 0 and nhl["targets"] == 6
    assert nhl["latest_capture_utc"] == "2026-09-30T22:35:00Z" and nhl["discovery"]["fresh"] is True
    # Offered odds go stale after the registered odds max_age (10 minutes).
    assert op.coverage_status(paths[0], now=utc(2026, 9, 30, 23, 0), settings=NHL_SETTINGS)["stale"] is True
    assert nfl["sport"] == NFL and nfl["captured"] == 0 and nfl["targets"] == 18 and nfl["stale"] is True
    done = op.coverage_status(paths[0], now=utc(2026, 10, 1, 0, 0), settings=NHL_SETTINGS)
    assert done["games_started"] == 2 and done["games_complete"] == 2
    assert cli.main(["odds", "status", "--db", str(paths[0]), "--ledger", str(paths[1]), "--sport", NHL]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["coverage"]["sport"] == NHL and printed["switch"] == {"env": "EDGE_LAB_ODDS_NHL", "on": False}


# ------------------------------------------------------------------ review fixes (#137)


def test_an_nhl_smoke_is_refused_while_nfl_holds_the_month_and_spends_nothing(paths):
    """October 2026: NFL's worst case fills the ceiling, so NHL is admitted nothing. A manual NHL smoke must
    not spend a credit out of NFL's reservation either (review blocker): smoke is for the rank-1 sport only."""
    provider = TwoSportProvider(used=0, remaining=500)
    at = utc(2026, 10, 1, 12)
    run(paths, provider, at, settings=NFL_SETTINGS)
    code, report = run(paths, provider, at)
    assert report["joint_budget"]["sports"][1]["available"] == 0
    ledger_before = paths[1].read_bytes()
    calls_before = list(provider.calls)
    for _ in range(3):
        code, report = op.smoke(paths[0], paths[1], NHL_SETTINGS, clock=Clock(at), opener=provider, environ=ENV_ON)
        assert code == 1 and report["state"] == "SMOKE_REFUSED_RANK" and report["paid_calls"] == 0
    assert provider.calls == calls_before and provider.paid(NHL) == [] and paths[1].read_bytes() == ledger_before
    # NFL, rank 1, may still smoke (after its free reconcile), exactly as before.
    code, report = op.smoke(paths[0], paths[1], NFL_SETTINGS, clock=Clock(at), opener=provider, environ=ENV_ON)
    assert report["state"] == "CAPTURED" and report["paid_calls"] == 1


class OneOutcomeNFL(TwoSportProvider):
    def odds_for(self, event, markets):
        out = super().odds_for(event, markets)
        if event["sport_key"] == NFL:
            for book in out["bookmakers"]:
                for m in book["markets"]:
                    if m["key"] == "h2h":
                        m["outcomes"] = m["outcomes"][:1]  # a book listing one h2h side only
        return out


def test_the_two_way_h2h_record_is_nhl_only_and_nfl_captures_are_unchanged(paths):
    provider = OneOutcomeNFL()
    at = utc(2026, 10, 1, 23, 15)  # NFL TNF T-60m (Oct 2 00:15Z kickoff)
    run(paths, provider, utc(2026, 10, 1, 12), settings=NFL_SETTINGS)
    code, report = run(paths, provider, at, settings=NFL_SETTINGS)
    assert report["state"] == "CAPTURED"
    store = SnapshotStore(paths[0])
    captured = [r for r in store.odds_targets(sport=NFL) if r["state"] == "CAPTURED"]
    assert captured and all("h2h_not_two_way" not in json.loads(r["detail_json"]) for r in captured)
    health = {r["source_id"]: r for r in store.latest_source_health()}["the_odds_api"]
    assert health["status"] == "ok" and "two-way" not in health["anomalies_json"]
    assert sch.SPORT_POLICIES[NFL].check_two_way_h2h is False and sch.SPORT_POLICIES[NHL].check_two_way_h2h


def test_the_nhl_two_way_anomaly_names_the_actual_outcomes(paths):
    provider = TwoSportProvider(draw=True)
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    run(paths, provider, utc(2026, 9, 30, 22, 35))
    health = {r["source_id"]: r for r in SnapshotStore(paths[0]).latest_source_health()}["the_odds_api"]
    assert "draftkings: 3 outcome(s) ['Blackhawks', 'Draw', 'Senators']" in health["anomalies_json"]


def test_activation_is_the_first_tick_that_can_plan_not_the_first_switched_on_tick(paths):
    provider = TwoSportProvider(events_error={NHL: URLError("down")})
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))  # switched on, key present, discovery failed: not yet active
    state_file = paths[1].with_name(paths[1].name + ".pilot.json")
    assert json.loads(state_file.read_text())["sports"][NHL].get("activated_utc") is None
    provider.events_error = {}
    run(paths, provider, utc(2026, 9, 30, 18, 5))
    assert json.loads(state_file.read_text())["sports"][NHL]["activated_utc"] == "2026-09-30T18:05:00Z"


def test_nhl_t60m_actual_leads_over_the_published_season():
    """Disclosure (ADR 0039): the quiet window moves many NHL "T-60m" captures closer to the puck drop."""
    cfg = sch.SPORT_POLICIES[NHL].config()
    leads: dict[int, int] = {}
    for t in sch.plan_targets(_published(), cfg.offsets):
        m = int((t.commence_utc - sch.effective_due(t, cfg)).total_seconds() // 60)
        leads[m] = leads.get(m, 0) + 1
    assert leads == {60: 750, 55: 107, 40: 2, 25: 484, 10: 1}
    bands = {"lead_ge_55m": 750 + 107, "lead_25_to_55m": 2 + 484, "lead_lt_25m": 1}
    assert sum(bands.values()) == 1344 and round(484 / 1344, 3) == 0.360


def test_odds_status_reports_actual_lead_bands(paths, monkeypatch):
    monkeypatch.setattr(http, "datetime", ReceiptClock)
    provider = TwoSportProvider()
    run(paths, provider, utc(2026, 9, 30, 12), settings=NFL_SETTINGS)
    run(paths, provider, utc(2026, 9, 30, 12))
    run(paths, provider, utc(2026, 9, 30, 22, 35))
    cov = op.coverage_status(paths[0], now=utc(2026, 9, 30, 22, 40), settings=NHL_SETTINGS)
    # 19:30 ET games captured at 18:35 ET (T-55m); 22:00 ET at 21:00 (T-60m); 19:00 ET games at 18:35 (T-25m).
    assert cov["captured_lead_bands"] == {"lead_ge_55m": 2}
    assert cov["planned_lead_bands"] == {"lead_25_to_55m": 3, "lead_ge_55m": 3}


def test_a_failing_nhl_cli_run_names_the_sport_for_the_shared_units_alert(paths, capsys):
    code = cli.main(["odds", "run", "--db", str(paths[0]), "--ledger", str(paths[1]), "--sport", NHL,
                     "--markets", "h2h,totals"])
    out = capsys.readouterr()
    assert code == 1 and json.loads(out.out)["sport"] == NHL
    assert "odds run icehockey_nhl: exit 1, state POLICY_REFUSED" in out.err
