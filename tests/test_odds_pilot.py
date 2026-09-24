"""The Odds API NFL pilot runner (ADR 0029): discovery, targets, budget, one paid call per tick.

Fixtures only. Every HTTP call goes through a scripted router; the adapter's real opener is
replaced by one that fails the test."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FakeResponse
from edge_lab import cli, odds_api as oa, odds_pilot as op
from edge_lab.forward import exclusive_lock
from edge_lab.odds_schedule import PilotConfig
from edge_lab.sources import get_source
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FAKE = "FAKEpilotKEY9876543210zz"  # not a real key; every test scans for it
ENV = {get_source("the_odds_api").credential_env_var: FAKE}
SPORT = "americanfootball_nfl"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# Week 5-like schedule (EDT): TNF Thu 1 Oct 20:15, Sun 4 Oct 13:00 x3, 16:25, SNF 20:20, MNF Mon 20:15.
EVENTS = [
    {"id": "e0tnf", "commence_time": "2026-10-02T00:15:00Z", "home_team": "Rams", "away_team": "49ers"},
    {"id": "e1", "commence_time": "2026-10-04T17:00:00Z", "home_team": "Bills", "away_team": "Jets"},
    {"id": "e2", "commence_time": "2026-10-04T17:00:00Z", "home_team": "Bears", "away_team": "Lions"},
    {"id": "e3", "commence_time": "2026-10-04T17:00:00Z", "home_team": "Colts", "away_team": "Titans"},
    {"id": "e4", "commence_time": "2026-10-04T20:25:00Z", "home_team": "Chiefs", "away_team": "Raiders"},
    {"id": "e5snf", "commence_time": "2026-10-05T00:20:00Z", "home_team": "Eagles", "away_team": "Cowboys"},
    {"id": "e6mnf", "commence_time": "2026-10-06T00:15:00Z", "home_team": "Packers", "away_team": "Vikings"},
]
for e in EVENTS:
    e.update(sport_key=SPORT, sport_title="NFL")


def odds_for(event: dict) -> dict:
    books = []
    for key in ("draftkings", "fanduel"):
        books.append({"key": key, "title": key, "last_update": event["commence_time"], "markets": [
            {"key": "h2h", "last_update": event["commence_time"],
             "outcomes": [{"name": event["home_team"], "price": -150}, {"name": event["away_team"], "price": 130}]},
            {"key": "spreads", "outcomes": [{"name": event["home_team"], "price": -110, "point": -3.5},
                                            {"name": event["away_team"], "price": -110, "point": 3.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 44.5},
                                           {"name": "Under", "price": -115, "point": 44.5}]},
        ]})
    return {k: event[k] for k in ("id", "sport_key", "commence_time", "home_team", "away_team")} | {"bookmakers": books}


class HeaderResponse(FakeResponse):
    def __init__(self, body: bytes, *, url: str, headers: dict[str, str]):
        super().__init__(body, url=url)
        self.headers = {"Content-Type": "application/json", **headers}


class Provider:
    """A scripted The Odds API: events (free), sports (free), odds (paid, 3 credits)."""

    def __init__(self, events=None, *, used: int = 20, remaining: int = 480, headers_on_free: bool = True,
                 odds_error: BaseException | None = None, sports_headers: bool = True,
                 events_error: BaseException | None = None, charge: int | None = None,
                 odds_raw: bytes | None = None, sports_raw: bytes = b"[]"):
        self.events_error, self.charge, self.odds_raw, self.sports_raw = events_error, charge, odds_raw, sports_raw
        self.events = list(EVENTS if events is None else events)
        self.used, self.remaining = used, remaining
        self.headers_on_free = headers_on_free
        self.sports_headers = sports_headers
        self.odds_error = odds_error
        self.calls: list[str] = []

    def paid(self) -> list[str]:
        return [c for c in self.calls if "/odds/" in c]

    def _headers(self, last: int) -> dict[str, str]:
        return {"X-Requests-Remaining": str(self.remaining), "X-Requests-Used": str(self.used),
                "X-Requests-Last": str(last), "Set-Cookie": "session=abc"}

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert q.get("apiKey") == FAKE  # sent, as the documented query parameter only
        lo, hi = q.get("commenceTimeFrom"), q.get("commenceTimeTo")
        chosen = [e for e in self.events if (lo is None or e["commence_time"] >= lo)
                  and (hi is None or e["commence_time"] <= hi)]
        if parts.path.endswith("/events/"):
            if self.events_error is not None:
                raise self.events_error
            return HeaderResponse(json.dumps(chosen).encode(), url=url,
                                  headers=self._headers(0) if self.headers_on_free else {})
        if parts.path == "/v4/sports/":
            return HeaderResponse(self.sports_raw, url=url, headers=self._headers(0) if self.sports_headers else
                                  {"X-Requests-Remaining": "lots"})
        assert parts.path.endswith("/odds/"), url
        if self.odds_error is not None:
            raise self.odds_error
        assert q["markets"] == "h2h,spreads,totals" and q["regions"] == "us"
        cost = (3 if chosen else 0) if self.charge is None else self.charge  # an empty response is free
        self.used += cost
        self.remaining -= cost
        body = self.odds_raw if self.odds_raw is not None else json.dumps([odds_for(e) for e in chosen]).encode()
        return HeaderResponse(body, url=url, headers=self._headers(cost))


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real network call: {request.full_url}")

    monkeypatch.setattr(oa, "_no_redirect_opener", refuse)
    monkeypatch.delenv(get_source("the_odds_api").credential_env_var, raising=False)


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "edge.sqlite3", tmp_path / "odds_quota.json"


def tick(paths, provider, at, env=ENV, settings=op.RunnerSettings(), **kw):
    return op.run_tick(paths[0], paths[1], settings, clock=Clock(at), opener=provider, environ=env, **kw)


def states(paths) -> dict[str, str]:
    return {r["target_id"]: r["state"] for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT)}


def no_key_anywhere(root: Path, *objects) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            assert FAKE.encode() not in path.read_bytes(), path
    for obj in objects:
        assert FAKE not in json.dumps(obj, default=str)


# ------------------------------------------------------------------ setup and quiet window

def test_missing_key_is_setup_needed_sends_nothing_and_creates_nothing(paths, tmp_path, capsys):
    provider = Provider()
    code, report = tick(paths, provider, utc(2026, 10, 1, 12), env={})
    assert code == 0 and report["state"] == "SETUP_NEEDED" and provider.calls == []
    assert "EDGE_LAB_ODDS_API_KEY" in report["detail"] and not paths[0].exists() and not paths[1].exists()
    # Through the CLI too: exit 0, JSON only, nothing secret.
    assert cli.main(["odds", "run", "--db", str(paths[0]), "--ledger", str(paths[1])]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["state"] == "SETUP_NEEDED" and printed["paid_calls"] == 0


def test_ticks_inside_the_capture_window_do_nothing_at_all(paths):
    provider = Provider()
    code, report = tick(paths, provider, utc(2026, 10, 1, 22, 0))  # 18:00 EDT
    assert code == 0 and report["state"] == "DEFERRED_CAPTURE_WINDOW" and provider.calls == []
    assert not paths[0].exists()


# ------------------------------------------------------------------ discovery and planning

def test_first_tick_discovers_for_free_plans_targets_and_spends_nothing(paths, tmp_path):
    provider = Provider()
    code, report = tick(paths, provider, utc(2026, 10, 1, 12, 0))
    assert code == 0 and report["state"] == "IDLE" and report["paid_calls"] == 0
    assert len(provider.calls) == 1 and "/events/" in provider.calls[0] and provider.paid() == []
    assert report["discovery"]["state"] == "REFRESHED" and report["discovery"]["events"] == 7
    assert report["targets"]["planned_new"] == 20 and report["targets"]["by_state"] == {"PLANNED": 20}  # TNF T-24h already past
    assert report["budget"]["state"] == "PROVEN" and report["budget"]["worst_case_month_credits"] <= 450
    store = SnapshotStore(paths[0])
    row = store.latest_snapshot(source="the_odds_api", kind="events", entity_id=SPORT)
    assert "apiKey=REDACTED" in row["url"] and row["raw_sha256"]
    payload = json.loads(row["payload_json"])
    assert payload["request"]["purpose"] == "discovery" and payload["quota_headers"]["x-requests-used"] == "20"
    # Every target persists its intended time before any capture.
    t = store.odds_targets(sport=SPORT)[0]
    assert t["target_utc"] and t["planned_at_utc"] == "2026-10-01T12:00:00Z" and t["discovery_snapshot_id"] == row["id"]
    # The free call reconciled the quota ledger.
    assert oa.QuotaLedger(paths[1], clock=Clock(utc(2026, 10, 1, 12))).state() is oa.QuotaState.READY
    no_key_anywhere(tmp_path, report)


def test_discovery_is_refreshed_at_most_every_six_hours(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 1, 12, 0))
    tick(paths, provider, utc(2026, 10, 1, 14, 0))
    assert len(provider.calls) == 1
    tick(paths, provider, utc(2026, 10, 1, 18, 0))
    assert len(provider.calls) == 2


# ------------------------------------------------------------------ captures

def test_a_due_slot_makes_exactly_one_paid_call_and_a_second_tick_makes_none(paths, tmp_path):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))  # plan (TNF already past)
    at = utc(2026, 10, 3, 17, 0)  # T-24h of the three 13:00 ET games
    code, report = tick(paths, provider, at)
    assert code == 0 and report["state"] == "CAPTURED" and report["paid_calls"] == 1
    assert len(provider.paid()) == 1
    q = parse_qs(urlsplit(provider.paid()[0]).query)
    assert q["commenceTimeFrom"] == ["2026-10-04T17:00:00Z"] and q["commenceTimeTo"] == ["2026-10-04T17:00:00Z"]
    fired = report["fired"]
    assert fired["targets"] == 3 and fired["credits_last"] == 3 and fired["bookmakers"] == ["draftkings", "fanduel"]
    captured = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["state"] == "CAPTURED"]
    assert {r["event_id"] for r in captured} == {"e1", "e2", "e3"}
    for r in captured:
        detail = json.loads(r["detail_json"])
        assert r["snapshot_id"] == fired["snapshot_id"] and r["credits_last"] == 3 and r["captured_at_utc"]
        assert detail["event_present"] and detail["missing_markets"] == [] and detail["offset"] == "T-24h"
    snap = SnapshotStore(paths[0]).snapshots_by_id([fired["snapshot_id"]])[fired["snapshot_id"]]
    payload = json.loads(snap["payload_json"])
    assert payload["request"]["purpose"] == "capture" and len(payload["request"]["targets"]) == 3
    assert payload["quota_headers"] == {"x-requests-last": "3", "x-requests-remaining": "477", "x-requests-used": "23"}
    assert {e["id"] for e in payload["events"]} == {"e1", "e2", "e3"}
    # Same minute again: nothing is due any more, so no second paid call.
    code2, report2 = tick(paths, provider, at)
    assert code2 == 0 and report2["paid_calls"] == 0 and len(provider.paid()) == 1
    no_key_anywhere(tmp_path, report, report2)


def test_concurrent_tick_is_lock_busy_and_spends_nothing(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    lock = paths[1].with_name(paths[1].name + ".tick.lock")
    with exclusive_lock(lock, timeout_s=1):
        code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0), lock_timeout_s=0.2)
    assert code == 0 and report["state"] == "LOCK_BUSY" and provider.paid() == []


def test_only_one_paid_call_per_tick_even_when_two_slots_are_due(paths):
    a = dict(EVENTS[1], id="ea", commence_time="2026-10-04T17:00:00Z")  # T-60m at 16:00 UTC
    b = dict(EVENTS[4], id="eb", commence_time="2026-10-04T22:25:00Z")  # T-6h at 16:25 UTC: its own slot
    provider = Provider(events=[a, b])
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 4, 16, 20))  # both slots are due now
    assert report["paid_calls"] == 1 and len(provider.paid()) == 1
    assert report["fired"]["priority"] == 1  # the closing line goes first
    code, report = tick(paths, provider, utc(2026, 10, 4, 16, 21))
    assert report["paid_calls"] == 1 and len(provider.paid()) == 2 and report["fired"]["priority"] == 2


def test_expired_targets_become_missed_with_their_reason_and_stay_final(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    # Nothing ran between Saturday 10:00 and Sunday 12:00 UTC: Saturday's T-24h targets and Sunday's
    # 13:00-game T-6h targets were missed.
    code, report = tick(paths, provider, utc(2026, 10, 4, 12, 0))
    assert report["targets"]["missed_now"] == 3 + 3 + 1 + 1  # T-24h x3 and T-6h x3 (13:00), T-24h 16:25 and SNF
    store = SnapshotStore(paths[0])
    missed = [r for r in store.odds_targets(sport=SPORT) if r["state"] == "MISSED"]
    assert missed and all("not captured by" in r["reason"] and "last state PLANNED" in r["reason"] for r in missed)
    assert all(r["target_utc"] < "2026-10-04T12:00:00Z" for r in missed)
    with pytest.raises(sqlite3.IntegrityError, match="final state"):
        store.record_odds_transition(target_id=missed[0]["target_id"], state="PLANNED", at_utc="2026-10-04T12:01:00Z")


def test_quota_unknown_blocks_the_paid_call(paths):
    provider = Provider(headers_on_free=False, sports_headers=False)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert report["state"] == "QUOTA_UNKNOWN" and provider.paid() == [] and code == 0
    assert any("/v4/sports/?" in c for c in provider.calls)  # a free reconcile was tried
    assert report["targets"]["by_state"].get("QUOTA_UNKNOWN") == 3


def test_budget_short_skips_t24_but_keeps_closing_lines(paths):
    provider = Provider(used=430, remaining=70)  # 450 - 430 - 3 reserve = 17 credits: 5 calls
    code, report = tick(paths, provider, utc(2026, 10, 3, 10, 0))
    by_state = report["targets"]["by_state"]
    assert by_state.get("SKIPPED_BUDGET", 0) > 0
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert all(r["offset_label"] != "T-60m" for r in rows if r["state"] == "SKIPPED_BUDGET")
    # A skipped slot never fires even when due.
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert provider.paid() == []


def test_a_failed_paid_call_is_final_redacted_and_never_retried(paths, tmp_path):
    provider = Provider(odds_error=URLError(f"boom apiKey={FAKE}"))
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 1 and report["state"] == "FAILED" and len(provider.paid()) == 1
    rows = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["state"] == "FAILED"]
    assert len(rows) == 3 and all("not retried" in r["reason"] for r in rows)
    provider.odds_error = None
    tick(paths, provider, utc(2026, 10, 3, 17, 5))
    assert len(provider.paid()) == 1  # no retry: the first call may have been charged
    no_key_anywhere(tmp_path, report)


def test_a_capture_interrupted_mid_call_becomes_failed_not_retried(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    store = SnapshotStore(paths[0])
    target = [r for r in store.odds_targets(sport=SPORT) if r["event_id"] == "e1" and r["offset_label"] == "T-24h"][0]
    store.record_odds_transition(target_id=target["target_id"], state="CAPTURING", at_utc="2026-10-03T17:00:00Z",
                                 slot_id="x")
    tick(paths, provider, utc(2026, 10, 3, 17, 2))
    assert states(paths)[target["target_id"]] == "FAILED"


def test_a_moved_game_supersedes_its_old_targets_and_gets_new_ones(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 1, 12, 0))
    provider.events = [dict(e, commence_time="2026-10-05T00:25:00Z") if e["id"] == "e5snf" else e for e in EVENTS]
    code, report = tick(paths, provider, utc(2026, 10, 1, 18, 0))
    assert report["targets"]["superseded_now"] == 3 and report["targets"]["planned_new"] == 3
    rows = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["event_id"] == "e5snf"]
    assert sorted(r["state"] for r in rows) == ["PLANNED"] * 3 + ["SUPERSEDED"] * 3
    assert all("commence time changed" in r["reason"] for r in rows if r["state"] == "SUPERSEDED")


def test_stale_discovery_defers_captures(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    def broken(request, timeout):  # every later request fails: discovery cannot refresh
        provider.calls.append(request.full_url)
        raise URLError("down")

    code, report = op.run_tick(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 4, 15, 55)),
                               opener=broken, environ=ENV)
    assert report["discovery"]["state"] == "FAILED" and not report["discovery"]["fresh"] and code == 1
    assert report["state"] == "DEFERRED"
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert any(r["state"] == "DEFERRED" and "DISCOVERY_STALE" in r["reason"] for r in rows)


# ------------------------------------------------------------------ plan and smoke

def test_plan_offline_is_read_only_and_proves_the_month(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 1, 12, 0))
    before = SnapshotStore(paths[0]).recent_snapshots(limit=50)
    calls = len(provider.calls)
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), offline=True, clock=Clock(utc(2026, 10, 1, 13)))
    assert code == 0 and report["state"] == "PROVEN" and report["verdict"].startswith("PROVEN for 2026-10")
    assert len(provider.calls) == calls and report["paid_calls"] == 0
    assert len(report["schedule"]) == 7 and report["recorded_targets"] == {"PLANNED": 20}
    assert sum(s["targets"] for s in report["slots"]) == 20
    b = report["budget"]
    assert b["worst_case_month_credits"] <= 450 and b["expected_month_credits"] <= b["worst_case_month_credits"]
    assert b["worst_case_month_credits"] - b["spent"] <= b["provider_remaining"] - b["outstanding"]
    assert len(SnapshotStore(paths[0]).recent_snapshots(limit=50)) == len(before)
    assert report["projection_next_month"]["month"] == "2026-11"


def test_plan_online_makes_free_calls_only(paths):
    provider = Provider()
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                           opener=provider, environ=ENV)
    assert code == 0 and report["state"] == "PROVEN" and provider.paid() == []
    assert all("/events/" in c or "/v4/sports/?" in c for c in provider.calls)
    assert not paths[0].exists()  # never writes the evidence store
    assert "request" not in report["discovery"] and FAKE not in json.dumps(report) and "apiKey" not in json.dumps(report)


def test_plan_without_a_key_is_setup_needed(paths):
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                           opener=Provider(), environ={})
    assert code == 0 and report["state"] == "SETUP_NEEDED"


def test_smoke_refuses_when_the_quota_is_unknown(paths):
    provider = Provider(sports_headers=False)
    code, report = op.smoke(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                            opener=provider, environ=ENV)
    assert code == 1 and report["state"] == "QUOTA_UNKNOWN" and provider.paid() == []


def test_smoke_is_one_bounded_read_that_records_books_markets_and_quota(paths, tmp_path):
    provider = Provider()
    code, report = op.smoke(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                            opener=provider, environ=ENV)
    assert code == 0 and report["state"] == "CAPTURED" and len(provider.paid()) == 1
    q = parse_qs(urlsplit(provider.paid()[0]).query)
    assert q["commenceTimeFrom"] == ["2026-10-01T12:00:00Z"] and q["commenceTimeTo"] == ["2026-10-08T12:00:00Z"]
    assert report["bookmakers"] == ["draftkings", "fanduel"] and report["markets_returned"] == ["h2h", "spreads", "totals"]
    assert report["credits_last"] == 3 and report["quota_after"] == {"remaining": 477, "used": 23}
    assert any(c["status"] == "PAID_ONLY_NOT_ENABLED" for c in report["coverage"])
    # Counts, books and markets only: no URL of any kind in what is printed.
    assert "apiKey" not in json.dumps(report) and "http" not in json.dumps(report)
    no_key_anywhere(tmp_path, report)


def test_smoke_without_a_key_is_setup_needed(paths):
    code, report = op.smoke(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                            opener=Provider(), environ={})
    assert code == 0 and report["state"] == "SETUP_NEEDED" and report["paid_calls"] == 0


# ------------------------------------------------------------------ adapter additions

def test_events_request_is_quota_free_and_redacted():
    url, redacted = oa.build_events_request(SPORT, key=FAKE, commence_from=utc(2026, 10, 1),
                                            commence_to=utc(2026, 10, 2, 12, 30))
    assert url.startswith("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/?apiKey=" + FAKE)
    assert "commenceTimeFrom=2026-10-01T00:00:00Z" in url and "commenceTimeTo=2026-10-02T12:30:00Z" in url
    assert FAKE not in redacted and "apiKey=REDACTED" in redacted
    with pytest.raises(ValueError):
        oa.build_events_request(SPORT, key=FAKE, commence_from=datetime(2026, 10, 1))  # naive
    with pytest.raises(ValueError):
        oa.build_events_request(SPORT, key=FAKE, commence_from=utc(2026, 10, 2), commence_to=utc(2026, 10, 1))
    with pytest.raises(ValueError):
        oa.build_events_request(SPORT, key=FAKE, event_ids=["bad id"])


def test_fetch_events_does_not_reserve_and_ignores_missing_headers(tmp_path):
    led = oa.QuotaLedger(tmp_path / "q.json", clock=Clock(utc(2026, 10, 1)))
    out = oa.fetch_events(SPORT, ledger=led, opener=Provider(headers_on_free=False), environ=ENV)
    assert out.state is oa.QuotaState.READY and out.quota_after is None
    snap = led.snapshot()
    assert snap["reservations"] == {} and snap["state"] == "QUOTA_UNKNOWN"  # untouched, not marked unknown by it
    out2 = oa.fetch_events(SPORT, ledger=led, opener=Provider(), environ=ENV)
    assert out2.quota_after is oa.QuotaState.READY and led.snapshot()["used_local"] == 0
    assert oa.fetch_events(SPORT, ledger=led, opener=Provider(), environ={}).state is oa.QuotaState.SETUP_NEEDED


def test_fetch_events_errors_are_redacted_without_a_chain():
    def boom(request, timeout):
        raise URLError(f"refused {request.full_url}")

    with pytest.raises(oa.OddsApiError) as info:
        oa.fetch_events(SPORT, opener=boom, environ=ENV)
    assert FAKE not in str(info.value) and info.value.__cause__ is None and info.value.__context__ is None


def test_parse_events_skips_and_reports_malformed_entries():
    events, problems = oa.parse_events([
        EVENTS[1], {"id": "Bad Id", "commence_time": "2026-10-04T17:00:00Z"},
        {"id": "e9", "commence_time": "2026-10-04T17:00:00"},  # naive
        {"id": "e8", "sport_key": "basketball_nba", "commence_time": "2026-10-04T17:00:00Z"}, EVENTS[1], "x",
    ], sport=SPORT)
    assert [e.event_id for e in events] == ["e1"] and len(problems) == 5
    assert oa.parse_events({"not": "a list"}, sport=SPORT) == ((), ("events payload is not a list",))


# ------------------------------------------------------------------ storage v5 (additive migration)

def test_v4_store_migrates_additively_and_old_rows_stay_readable(tmp_path):
    from edge_lab import storage

    db = tmp_path / "v4.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(storage._SCHEMA_V1)
        for name, sql_type in storage._SNAPSHOT_V2_COLUMNS:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {sql_type}")
        conn.executescript(storage._SCHEMA_V2 + storage._SCHEMA_V3 + storage._SCHEMA_V4)
        conn.execute("INSERT INTO collection_runs VALUES ('old', 't0', 't1', 'succeeded', NULL)")
        conn.execute("INSERT INTO snapshots(run_id, source, kind, entity_id, fetched_at_utc, url, payload_sha256,"
                     " payload_json) VALUES ('old', 'kalshi', 'series', 'S', 't0', 'u', 'h', '{}')")
        conn.execute("PRAGMA user_version = 4")
    store = SnapshotStore(db)
    assert store.schema_version() == storage.SCHEMA_VERSION >= 5
    assert [r["run_id"] for r in store.recent_snapshots()] == ["old"]
    assert store.odds_targets() == []
    assert SnapshotStore.open_readonly(db).schema_version() == storage.SCHEMA_VERSION


def test_odds_targets_and_transitions_are_immutable(tmp_path):
    store = SnapshotStore(tmp_path / "e.sqlite3")
    kw = dict(target_id="t1", sport=SPORT, event_id="e1", offset_label="T-60m", priority=1,
              commence_time_utc="2026-10-04T17:00:00Z", target_utc="2026-10-04T16:00:00Z",
              planned_at_utc="2026-10-01T12:00:00Z", policy_version="game_relative_v1")
    assert store.plan_odds_target(**kw) is True
    assert store.plan_odds_target(**(kw | {"planned_at_utc": "2026-10-02T00:00:00Z"})) is False
    (row,) = store.odds_targets()
    assert row["planned_at_utc"] == "2026-10-01T12:00:00Z" and row["state"] == "PLANNED"
    with sqlite3.connect(store.path) as conn:
        for sql in ("UPDATE odds_capture_targets SET target_utc = 'x'", "DELETE FROM odds_capture_targets",
                    "UPDATE odds_capture_transitions SET state = 'CAPTURED'", "DELETE FROM odds_capture_transitions"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(sql)
        with pytest.raises(sqlite3.IntegrityError):  # a capture must name its evidence
            conn.execute("INSERT INTO odds_capture_transitions(target_id, state, at_utc) VALUES ('t1', 'CAPTURED', 'x')")
        with pytest.raises(sqlite3.IntegrityError):  # a miss must explain itself
            conn.execute("INSERT INTO odds_capture_transitions(target_id, state, at_utc) VALUES ('t1', 'MISSED', 'x')")
    with pytest.raises(ValueError):
        store.record_odds_transition(target_id="t1", state="DONE", at_utc="x")


# ------------------------------------------------------------------ review fixes: pacing, absence, anomalies

def http_error(code):
    return HTTPError("https://api.the-odds-api.com/x", code, "err", {}, None)


def test_failing_discovery_is_paced_and_alerts_once(paths):
    provider = Provider(events_error=URLError("down"))
    code, report = tick(paths, provider, utc(2026, 10, 1, 12, 0))
    assert code == 1 and report["discovery"]["state"] == "FAILED"  # a new failure alerts
    for minutes in (15, 30, 45, 5 * 60):
        code, report = tick(paths, provider, utc(2026, 10, 1, 12, 0) + timedelta(minutes=minutes))
        assert code == 0 and report["discovery"]["state"] == "FAILED_WAITING"
    assert len(provider.calls) == 1  # no retry before discovery_interval
    code, report = tick(paths, provider, utc(2026, 10, 1, 18, 0))
    assert len(provider.calls) == 2 and report["discovery"]["state"] == "FAILED" and code == 0  # same failure
    provider.events_error = None
    code, report = tick(paths, provider, utc(2026, 10, 2, 0, 0))
    assert code == 0 and report["discovery"]["state"] == "REFRESHED"


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_a_setup_state_not_an_alert_loop(paths, status):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))  # good discovery, targets planned
    provider.events_error = http_error(status)
    code, report = tick(paths, provider, utc(2026, 10, 3, 12, 0))
    assert code == 1 and report["discovery"]["state"] == "KEY_REJECTED" and report["state"] == "KEY_REJECTED"
    code, report = tick(paths, provider, utc(2026, 10, 3, 12, 15))  # persists: no second alert
    assert code == 0 and report["state"] == "KEY_REJECTED"
    # A slot falls due while the key is rejected: nothing is paid for.
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 0 and report["state"] == "KEY_REJECTED" and provider.paid() == []
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert any(r["state"] == "SETUP_NEEDED" and "KEY_REJECTED" in r["reason"] for r in rows)
    assert sum("/events/" in c for c in provider.calls) == 2  # paced: one retry per discovery_interval at most


def test_a_game_missing_from_a_fresh_discovery_is_never_paid_for_and_can_come_back(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))
    provider.events = [e for e in EVENTS if e["id"] not in ("e1", "e2", "e3")]  # the 13:00 games vanish
    code, report = tick(paths, provider, utc(2026, 10, 3, 11, 0))
    assert report["targets"]["event_absent"] == 9
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))  # their T-24h slot is due
    assert provider.paid() == [] and report["state"] == "IDLE"
    rows = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["event_id"] in ("e1", "e2", "e3")]
    assert rows and all(r["state"] in ("DEFERRED", "MISSED") for r in rows)
    assert all(r["reason"].startswith("EVENT_ABSENT") for r in rows if r["state"] == "DEFERRED")
    provider.events = EVENTS  # the games are listed again
    tick(paths, provider, utc(2026, 10, 3, 23, 10))
    rows = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["event_id"] == "e1"]
    assert {r["offset_label"]: r["state"] for r in rows}["T-60m"] == "PLANNED"


def test_an_empty_discovery_does_not_mark_every_game_absent(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))
    provider.events = []
    code, report = tick(paths, provider, utc(2026, 10, 3, 11, 0))
    assert report["targets"]["event_absent"] == 0
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert len(provider.paid()) == 1


def test_a_non_json_quota_reconcile_keeps_quota_unknown_and_closes_the_run(paths):
    provider = Provider(headers_on_free=False, sports_raw=b"<html>not json</html>", sports_headers=False)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert report["state"] == "QUOTA_UNKNOWN" and provider.paid() == []
    with sqlite3.connect(paths[0]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_runs WHERE status = 'running'").fetchone()[0] == 0


def test_reconcile_quota_tolerates_a_non_json_body(tmp_path):
    led = oa.QuotaLedger(tmp_path / "q.json", clock=Clock(utc(2026, 10, 1)))
    out = oa.reconcile_quota(led, opener=Provider(sports_raw=b"nope"), environ=ENV)
    assert out.state is oa.QuotaState.READY and out.payload is None


def test_a_charge_above_the_estimate_stops_paid_calls_until_cleared(paths):
    provider = Provider(charge=6)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 1 and report["state"] == "COST_ANOMALY" and report["cost_block"]["charged"] == 6
    code, report = tick(paths, provider, utc(2026, 10, 3, 20, 25))  # the 16:25 game's T-24h: blocked
    assert code == 0 and report["state"] == "COST_BLOCKED" and len(provider.paid()) == 1
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert any(r["state"] == "QUOTA_EXHAUSTED" and "COST_ANOMALY" in r["reason"] for r in rows)
    provider.charge = None
    code, report = tick(paths, provider, utc(2026, 10, 3, 20, 30), clear_cost_block=True)
    assert report["state"] == "CAPTURED" and len(provider.paid()) == 2 and "cost_block" not in report


def test_an_undecodable_paid_response_is_kept_as_raw_evidence_and_not_retried(paths):
    provider = Provider(odds_raw=b"<html>upstream error</html>")
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 1 and report["state"] == "FAILED" and report["fired"]["raw_document_id"]
    with sqlite3.connect(paths[0]) as conn:
        url, doc_type = conn.execute("SELECT requested_url, doc_type FROM document_retrievals").fetchone()
    assert doc_type == "odds_undecodable_response" and "apiKey=REDACTED" in url and FAKE not in url
    tick(paths, provider, utc(2026, 10, 3, 17, 5))
    assert len(provider.paid()) == 1


def test_a_broken_proof_fails_closed_without_a_paid_call(paths, monkeypatch):
    from edge_lab import odds_schedule

    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))

    def broken(*args, **kwargs):
        raise odds_schedule.BudgetInvariantError("bug")

    monkeypatch.setattr(op, "budget", broken)
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 1 and report["state"] == "FAILED" and provider.paid() == []
    with sqlite3.connect(paths[0]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_runs WHERE status = 'running'").fetchone()[0] == 0


# ------------------------------------------------------------------ re-review: alerts once, plan blocks, fail closed

def test_a_vanished_key_after_activation_alerts_once(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))  # active: a discovery succeeded
    code, report = tick(paths, provider, utc(2026, 10, 3, 5, 15), env={})
    assert code == 1 and report["state"] == "SETUP_NEEDED"  # the transition alerts
    code, report = tick(paths, provider, utc(2026, 10, 3, 5, 30), env={})
    assert code == 0 and report["state"] == "SETUP_NEEDED"  # while it persists: no alert
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0), env={})
    assert code == 0 and provider.paid() == []


def test_setup_needed_before_activation_never_alerts(paths):
    SnapshotStore(paths[0])  # the shared evidence DB exists long before the pilot is activated
    for minute in (0, 15):
        code, report = tick(paths, Provider(), utc(2026, 10, 3, 5, minute), env={})
        assert code == 0 and report["state"] == "SETUP_NEEDED"


def test_plan_is_not_a_go_ahead_while_a_cost_block_is_active(paths):
    provider = Provider(charge=6)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))  # overcharge -> cost block
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), offline=True, clock=Clock(utc(2026, 10, 3, 17, 5)))
    assert code == 1 and report["state"] == "COST_BLOCKED" and report["verdict"].startswith("NOT A GO-AHEAD")
    assert report["runner_state"]["cost_block"]["charged"] == 6
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 3, 17, 5)),
                           opener=Provider(), environ=ENV)
    assert code == 1 and report["state"] == "COST_BLOCKED"


def test_plan_offline_surfaces_a_rejected_key(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))
    provider.events_error = http_error(401)
    tick(paths, provider, utc(2026, 10, 3, 12, 0))
    code, report = op.plan(paths[0], paths[1], op.RunnerSettings(), offline=True, clock=Clock(utc(2026, 10, 3, 12, 5)))
    assert code == 1 and report["state"] == "KEY_REJECTED" and "PROVEN" not in report["verdict"].split(":")[0]


def test_an_absent_game_is_not_reopened_by_an_empty_discovery(paths):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 5, 0))
    provider.events = [e for e in EVENTS if e["id"] not in ("e1", "e2", "e3")]
    tick(paths, provider, utc(2026, 10, 3, 11, 0))  # e1-e3 become EVENT_ABSENT
    provider.events = []  # the next discovery is empty: not evidence that anything is back
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))  # also the T-24h slot's due time
    assert provider.paid() == [] and report["targets"]["event_absent"] >= 3
    rows = [r for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT) if r["event_id"] in ("e1", "e2", "e3")]
    assert not any(r["state"] in ("PLANNED", "CAPTURING", "CAPTURED") for r in rows)


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_a_damaged_runner_state_file_fails_closed(paths, damage):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))  # one paid call: history exists
    state_file = paths[1].with_name(paths[1].name + ".pilot.json")
    if damage == "corrupt":
        state_file.write_text("{not json", encoding="utf-8")
    else:
        state_file.unlink()
    code, report = tick(paths, provider, utc(2026, 10, 3, 20, 25))  # the 16:25 game's T-24h is due
    assert report["state"] == "COST_BLOCKED" and len(provider.paid()) == 1
    assert "PILOT_STATE" in report["cost_block"]["reason"]
    tick(paths, provider, utc(2026, 10, 3, 20, 30), clear_cost_block=True)
    assert len(provider.paid()) == 2


def test_smoke_writes_the_runner_state_so_the_first_tick_is_not_blocked(paths):
    provider = Provider()
    code, _ = op.smoke(paths[0], paths[1], op.RunnerSettings(), clock=Clock(utc(2026, 10, 3, 5)), opener=provider,
                       environ=ENV)
    assert code == 0 and paths[1].with_name(paths[1].name + ".pilot.json").exists()
    code, report = tick(paths, provider, utc(2026, 10, 3, 5, 15))
    assert "cost_block" not in report and report["state"] != "COST_BLOCKED"


def test_the_traceback_of_an_unexpected_error_is_logged_redacted(paths, monkeypatch, capsys):
    provider = Provider()
    tick(paths, provider, utc(2026, 10, 3, 10, 0))

    def boom(*args, **kwargs):
        raise RuntimeError(f"boom apiKey={FAKE}")

    monkeypatch.setattr(op, "coalesce", boom)
    code, report = tick(paths, provider, utc(2026, 10, 3, 10, 15))
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" in err and "RuntimeError" in err and FAKE not in err


def test_every_entry_point_accepts_string_paths_as_the_cli_passes_them(paths):
    """Production 2026-09-24: `edge-lab odds smoke` crashed with AttributeError ('str' has no
    with_name) before any request, because smoke() did not normalise the CLI's string paths."""
    db, ledger = str(paths[0]), str(paths[1])
    provider = Provider()
    code, report = op.smoke(db, ledger, op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12)),
                            opener=provider, environ=ENV)
    assert code == 0 and report["state"] == "CAPTURED" and len(provider.paid()) == 1
    code, report = op.plan(db, ledger, op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12, 5)),
                           opener=Provider(), environ=ENV)
    assert code == 0 and report["state"] == "PROVEN"
    code, report = op.run_tick(db, ledger, op.RunnerSettings(), clock=Clock(utc(2026, 10, 1, 12, 10)),
                               opener=Provider(), environ=ENV)
    assert code == 0 and report["state"] == "IDLE" and "error_kind" not in report
