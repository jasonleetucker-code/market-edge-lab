"""The Odds API readiness without a key (directive 2026-09-24b, Deliverable 6). Fixtures only.

Adversarial quota tests, event identity, the separation of offered odds / implied / de-vigged /
consensus (never executable), the prospective time-series storage contract (issue #50), failed
collections as evidence, a whole-season month simulation with provider cost semantics, and the
read-only dashboard status. No test reaches the network: the adapter's real opener fails the test.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FakeResponse
from edge_lab import odds_api as oa, odds_pilot as op, odds_schedule as sch
from edge_lab.fee_schedules import schedule_for
from edge_lab.opportunity import ExecutableQuote, Policy, evaluate
from edge_lab.sources import get_source
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FAKE = "FAKEreadyKEY55555555zz"  # not a real key; every test scans for it
ENV = {get_source("the_odds_api").credential_env_var: FAKE}
SPORT = "americanfootball_nfl"
SRC = Path(__file__).resolve().parents[1] / "src" / "edge_lab"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real network call: {request.full_url}")

    monkeypatch.setattr(oa, "_no_redirect_opener", refuse)
    monkeypatch.delenv(get_source("the_odds_api").credential_env_var, raising=False)


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class HeaderResponse(FakeResponse):
    def __init__(self, body: bytes, *, url: str, headers: dict[str, str]):
        super().__init__(body, url=url)
        self.headers = {"Content-Type": "application/json", **headers}


def quota(remaining: int, used: int, last: int | None = 0) -> dict[str, str]:
    h = {"X-Requests-Remaining": str(remaining), "X-Requests-Used": str(used)}
    if last is not None:
        h["X-Requests-Last"] = str(last)
    return h


def odds_body(event: dict, *, shift: int = 0, markets=("h2h", "spreads", "totals"),
              books=("draftkings", "fanduel")) -> dict:
    out = []
    for i, key in enumerate(books):
        mk = []
        if "h2h" in markets:
            mk.append({"key": "h2h", "last_update": event["commence_time"], "outcomes": [
                {"name": event["home_team"], "price": -150 - shift - i * 5},
                {"name": event["away_team"], "price": 130 + shift + i * 5}]})
        if "spreads" in markets:
            mk.append({"key": "spreads", "outcomes": [
                {"name": event["home_team"], "price": -110, "point": -3.5},
                {"name": event["away_team"], "price": -110, "point": 3.5}]})
        if "totals" in markets:
            mk.append({"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 44.5},
                                                      {"name": "Under", "price": -115, "point": 44.5}]})
        out.append({"key": key, "title": key, "last_update": event["commence_time"], "markets": mk})
    keep = ("id", "sport_key", "sport_title", "commence_time", "home_team", "away_team")
    return {k: event[k] for k in keep if k in event} | {"bookmakers": out}


class Provider:
    """A scripted The Odds API with provider cost semantics: /events and /sports are free; one
    /odds call costs markets x regions (3) when the response holds any event, 0 when empty. The
    monthly counter resets when the clock enters a new UTC month (the provider's own reset)."""

    def __init__(self, events, *, clock: Clock | None = None, used: int = 0, remaining: int = 500):
        self.events = list(events)
        self.clock = clock
        self.used, self.remaining = used, remaining
        self.month = clock().strftime("%Y-%m") if clock else None
        self.calls: list[str] = []
        self.charges: list[tuple[str, int]] = []  # (UTC month, credits)
        self.odds_error: BaseException | None = None
        self.events_error: BaseException | None = None
        self.shift = 0
        self.markets = ("h2h", "spreads", "totals")
        self.lock = threading.Lock()

    def paid(self) -> list[str]:
        return [c for c in self.calls if "/odds/" in c]

    def _headers(self, last: int) -> dict[str, str]:
        return {"X-Requests-Remaining": str(self.remaining), "X-Requests-Used": str(self.used),
                "X-Requests-Last": str(last)}

    def __call__(self, request, timeout):
        with self.lock:
            if self.clock is not None and self.clock().strftime("%Y-%m") != self.month:
                self.month = self.clock().strftime("%Y-%m")
                self.used, self.remaining = 0, 500
            url = request.full_url
            self.calls.append(url)
            parts = urlsplit(url)
            q = {k: v[0] for k, v in parse_qs(parts.query).items()}
            assert q.get("apiKey") == FAKE and parts.netloc == "api.the-odds-api.com"
            lo, hi = q.get("commenceTimeFrom"), q.get("commenceTimeTo")
            chosen = [e for e in self.events if (lo is None or e["commence_time"] >= lo)
                      and (hi is None or e["commence_time"] <= hi)]
            if parts.path.endswith("/events/"):
                if self.events_error is not None:
                    raise self.events_error
                return HeaderResponse(json.dumps(chosen).encode(), url=url, headers=self._headers(0))
            if parts.path == "/v4/sports/":
                return HeaderResponse(b"[]", url=url, headers=self._headers(0))
            assert parts.path.endswith("/odds/"), url
            # Never a paid fallback: always the one region and the three approved markets.
            assert q["regions"] == "us" and q["markets"] == "h2h,spreads,totals" and "bookmakers" not in q
            if self.odds_error is not None:
                raise self.odds_error
            cost = 3 if chosen else 0
            self.used += cost
            self.remaining -= cost
            self.charges.append((self.month or "?", cost))
            body = [odds_body(e, shift=self.shift, markets=self.markets) for e in chosen]
            return HeaderResponse(json.dumps(body).encode(), url=url, headers=self._headers(cost))


def ev(eid: str, commence: datetime, home: str, away: str) -> dict:
    return {"id": eid, "sport_key": SPORT, "sport_title": "NFL",
            "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": home, "away_team": away}


WEEK = [ev("e1", utc(2026, 10, 4, 17), "Buffalo Bills", "New York Jets"),
        ev("e2", utc(2026, 10, 4, 17), "Chicago Bears", "Detroit Lions"),
        ev("e3", utc(2026, 10, 4, 20, 25), "Kansas City Chiefs", "Las Vegas Raiders"),
        ev("e4", utc(2026, 10, 5, 0, 20), "Philadelphia Eagles", "Dallas Cowboys")]


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "edge.sqlite3", tmp_path / "odds_quota.json"


def tick(paths, provider, at, **kw):
    return op.run_tick(paths[0], paths[1], clock=Clock(at), opener=provider, environ=ENV, **kw)


def state_path(paths) -> Path:
    return paths[1].with_name(paths[1].name + ".pilot.json")


def no_key_anywhere(root: Path, *objects) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            assert FAKE.encode() not in path.read_bytes(), path
    for obj in objects:
        assert FAKE not in json.dumps(obj, default=str)


def ledger(tmp_path: Path, ceiling: int = 450, clock: Clock | None = None) -> oa.QuotaLedger:
    return oa.QuotaLedger(tmp_path / "quota.json", ceiling, clock=clock or Clock(utc(2026, 10, 3, 12)),
                          lock_timeout_s=10)


# ================================================================== 1. quota, adversarially

def test_the_450_ceiling_is_hard_and_cannot_be_configured_to_the_free_allowance(tmp_path):
    for bad in (500, 501, 0, -1):
        with pytest.raises(ValueError):
            oa.QuotaLedger(tmp_path / "q.json", bad)
        with pytest.raises(ValueError):
            sch.PilotConfig(ceiling=bad)
    for bad in (450.0, True):
        with pytest.raises(ValueError):
            oa.QuotaLedger(tmp_path / "q.json", bad)
    assert oa.DEFAULT_CEILING == 450 and sch.PilotConfig().ceiling == 450 and op.RunnerSettings().config.ceiling == 450
    led = ledger(tmp_path)
    led.reconcile(quota(500, 0))
    spent = 0
    while True:
        try:
            res = led.reserve(3)
        except oa.QuotaRefused as refusal:
            assert refusal.state is oa.QuotaState.QUOTA_EXHAUSTED
            break
        led.settle(res, quota(500 - spent - 3, spent + 3, 3))
        spent += 3
    assert spent == 450 and led.state() is oa.QuotaState.QUOTA_EXHAUSTED  # 150 calls, never a 151st


def test_the_provider_counter_overrides_a_lower_local_count(tmp_path):
    led = ledger(tmp_path)
    led.reconcile(quota(490, 10))
    res = led.reserve(3)
    led.settle(res, quota(487, 13, 3))
    assert led.snapshot()["used_local"] == 3
    # Someone else used the same key (or a charge we never saw): the provider says 300 used.
    led.reconcile(quota(200, 300))
    snap = led.snapshot()
    assert snap["used_local"] == 3 and snap["last_headers"]["used"] == 300  # not "reset" to the lower number
    with pytest.raises(oa.QuotaRefused):
        led.reserve(151)  # 300 + 151 > 450: the provider's figure is what counts
    led.reserve(150)
    # And the local count wins when the provider lags behind it.
    other = ledger(tmp_path / "b")
    other.reconcile(quota(500, 0))
    for _ in range(3):
        other.settle(other.reserve(3), quota(500, 0, 3))  # headers not yet updated by the provider
    assert other.snapshot()["used_local"] == 9
    with pytest.raises(oa.QuotaRefused):
        other.reserve(442)  # 9 + 442 > 450


def test_provider_remaining_below_the_ceiling_wins(tmp_path):
    led = ledger(tmp_path)
    led.reconcile(quota(5, 0))  # the ceiling would allow 450; the provider has 5 left
    with pytest.raises(oa.QuotaRefused) as err:
        led.reserve(6)
    assert err.value.state is oa.QuotaState.QUOTA_EXHAUSTED
    led.reserve(3)
    with pytest.raises(oa.QuotaRefused):
        led.reserve(3)  # 3 outstanding + 3 > 5


def test_a_charge_above_the_reservation_is_booked_in_full(tmp_path):
    led = ledger(tmp_path)
    led.reconcile(quota(500, 0))
    led.settle(led.reserve(3), quota(491, 9, 9))
    assert led.snapshot()["used_local"] == 9  # booked what the provider charged, not the estimate


@pytest.mark.parametrize("failure", [HTTPError("u", 429, "Too Many Requests", {}, None),
                                     HTTPError("u", 503, "Unavailable", {}, None),
                                     HTTPError("u", 500, "Error", {}, None),
                                     URLError("timed out"), TimeoutError("read timed out"),
                                     ConnectionResetError("reset by peer")])
def test_a_failed_paid_call_is_sent_once_never_retried_and_keeps_its_reservation(tmp_path, failure):
    led = ledger(tmp_path)
    led.reconcile(quota(500, 0))
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise failure

    with pytest.raises(oa.OddsApiError) as err:
        oa.fetch_odds(SPORT, ["h2h", "spreads", "totals"], regions=["us"], ledger=led, opener=opener, environ=ENV)
    assert len(calls) == 1  # a retry could be charged twice
    assert err.value.__cause__ is None and err.value.__context__ is None and FAKE not in str(err.value)
    snap = led.snapshot()
    assert snap["outstanding"] == 3 and snap["state"] == "QUOTA_UNKNOWN"
    assert [r["state"] for r in snap["reservations"].values()] == ["AMBIGUOUS"]


def test_out_of_order_readings_are_stale_not_a_reset(tmp_path):
    """Deterministic version of the race: two calls in flight, the provider counted both before
    answering the first, and the second's headers (older counter) arrive last."""
    led = ledger(tmp_path)
    led.reconcile(quota(500, 0))
    a, b = led.reserve(3), led.reserve(3)
    led.settle(a, quota(494, 6, 3))  # already includes b's charge
    assert led.settle(b, quota(497, 3, 3)) is oa.QuotaState.READY  # older reading, delivered late
    snap = led.snapshot()
    assert snap["used_local"] == 6 and snap["last_headers"]["used"] == 6 and snap["outstanding"] == 0
    assert any(e["event"] == "stale_reading_ignored" for e in snap["events"])
    assert not any(e["event"] == "provider_reset_observed" for e in snap["events"])
    with pytest.raises(oa.QuotaRefused):
        led.reserve(445)  # 6 spent + 445 > 450: nothing was handed back
    # A free reconcile carrying an older counter while a call is in flight is stale too.
    c = led.reserve(3)
    led.reconcile(quota(497, 3))
    snap = led.snapshot()
    assert snap["last_headers"]["used"] == 6 and snap["used_local"] == 6
    led.settle(c, quota(491, 9, 3))
    assert led.snapshot()["used_local"] == 9


def test_a_genuine_reset_with_reservations_outstanding_is_still_a_reset(tmp_path):
    clock = Clock(utc(2026, 10, 31, 23, 58))
    led = ledger(tmp_path, clock=clock)
    led.reconcile(quota(200, 300))
    in_flight = led.reserve(3)
    clock.at = utc(2026, 11, 1, 0, 1)
    assert led.reconcile(quota(500, 0)) is oa.QuotaState.READY  # 300 -> 0 is far more than 3 in flight
    snap = led.snapshot()
    assert snap["used_local"] == 0 and snap["last_headers"]["used"] == 0
    assert any(e["event"] == "provider_reset_observed" for e in snap["events"])
    assert snap["outstanding"] == 3 and in_flight.reservation_id in snap["reservations"]  # still counted
    led.settle(in_flight, quota(497, 3, 3))
    assert led.snapshot()["used_local"] == 3


def test_a_lost_response_counts_conservatively_across_a_restart(tmp_path):
    clock = Clock(utc(2026, 10, 3, 12))
    led = ledger(tmp_path, clock=clock)
    led.reconcile(quota(497, 3))

    def lost(request, timeout):
        raise URLError("connection reset after the request was sent")  # did the provider charge? unknown

    with pytest.raises(oa.OddsApiError):
        oa.fetch_odds(SPORT, ["h2h", "spreads", "totals"], regions=["us"], ledger=led, opener=lost, environ=ENV)
    # The process restarts: the reservation is still on disk and nothing can be spent.
    again = ledger(tmp_path, clock=clock)
    snap = again.snapshot()
    assert snap["outstanding"] == 3 and snap["state"] == "QUOTA_UNKNOWN"
    with pytest.raises(oa.QuotaRefused) as err:
        again.reserve(3)
    assert err.value.state is oa.QuotaState.QUOTA_UNKNOWN
    # A reading that does not cover the call (no x-requests-used) never drops the reservation.
    again.reconcile({"X-Requests-Remaining": "497"})
    assert again.snapshot()["outstanding"] == 3
    # The provider's counter after the call carries its cost: the reservation retires, never twice.
    clock.at += timedelta(minutes=1)
    assert again.reconcile(quota(494, 6)) is oa.QuotaState.READY
    snap = again.snapshot()
    assert snap["outstanding"] == 0 and snap["last_headers"]["used"] == 6
    spent = max(snap["used_local"], snap["last_headers"]["used"])
    assert spent == 6  # 3 before + the 3 the lost call cost


def test_concurrent_paid_calls_never_exceed_the_headroom(tmp_path):
    led = ledger(tmp_path)
    led.reconcile(quota(56, 444))  # 450 - 444 = 6: exactly two 3-credit calls
    provider = Provider(WEEK, used=444, remaining=56)
    results, errors = [], []

    def worker():
        try:
            out = oa.fetch_odds(SPORT, ["h2h", "spreads", "totals"], regions=["us"],
                                ledger=ledger(tmp_path), opener=provider, environ=ENV)
            results.append(out.state)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert Counter(results) == {oa.QuotaState.READY: 2, oa.QuotaState.QUOTA_EXHAUSTED: 10}
    assert len(provider.paid()) == 2 and provider.used == 450
    assert ledger(tmp_path).state() is oa.QuotaState.QUOTA_EXHAUSTED


def test_a_month_reset_is_taken_only_from_the_provider_and_retires_last_months_ambiguity(tmp_path):
    clock = Clock(utc(2026, 9, 30, 23, 50))
    led = ledger(tmp_path, clock=clock)
    led.reconcile(quota(60, 440))
    ambiguous = led.reserve(3)
    led.mark_ambiguous(ambiguous, "timeout")
    clock.at = utc(2026, 10, 1, 0, 5)
    assert led.state() is oa.QuotaState.QUOTA_UNKNOWN  # a new UTC month is never assumed to be reset
    with pytest.raises(oa.QuotaRefused):
        led.reserve(3)
    assert led.reconcile(quota(50, 450)) is oa.QuotaState.QUOTA_EXHAUSTED  # provider not reset yet: still spent
    assert led.snapshot()["outstanding"] == 0  # its counter now covers the September call
    assert led.reconcile(quota(500, 0)) is oa.QuotaState.READY  # the provider's own counter went down
    snap = led.snapshot()
    assert snap["used_local"] == 0 and snap["outstanding"] == 0
    assert any(e["event"] == "provider_reset_observed" for e in snap["events"])


def test_no_paid_fallback_exists_anywhere_in_the_odds_modules():
    """Only the documented v4 host, only the three free endpoints, no historical endpoint, no
    paid-only bookmaker, no second key or account."""
    for name in ("odds_api.py", "odds_pilot.py", "odds_schedule.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        hosts = set(re.findall(r"https?://([^/\s\"')]+)", text))
        assert hosts <= {"api.the-odds-api.com", "the-odds-api.com"}, (name, hosts)
        code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
        assert "/historical" not in code and "/v4/historical" not in code
    url, _ = oa.build_request(SPORT, ["h2h"], key=FAKE, regions=["us"])
    assert urlsplit(url).path == "/v4/sports/americanfootball_nfl/odds/"
    for book in oa.PAID_ONLY_BOOKMAKERS:
        with pytest.raises(ValueError):
            oa.build_request(SPORT, ["h2h"], key=FAKE, bookmakers=[book])
    # Bookmaker groups of 10 count as one region each; the pilot's call is 3 x 1 = 3 credits.
    assert oa.estimate_cost(["h2h", "spreads", "totals"], bookmakers=[f"b{i}" for i in range(10)]) == 3
    assert oa.estimate_cost(["h2h", "spreads", "totals"], bookmakers=[f"b{i}" for i in range(11)]) == 6
    assert op.RunnerSettings().cost_per_call == 3


def test_an_exhausted_month_makes_no_paid_call_from_the_runner(paths, tmp_path):
    provider = Provider(WEEK, used=449, remaining=51)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))  # T-24h of the 13:00 games is due
    assert provider.paid() == [] and report["paid_calls"] == 0
    assert report["state"] == "QUOTA_EXHAUSTED" and report["budget"]["state"] == "QUOTA_EXHAUSTED"
    no_key_anywhere(tmp_path, report)


# ================================================================== 2. event identity

def _offers(payload, **kw):
    return oa.parse_odds(payload, odds_format="american", **kw).offers


def test_repeated_observations_of_one_proposition_link_into_one_series():
    e = ev("g1", utc(2026, 10, 4, 17), "New York Giants", "Dallas Cowboys")
    early = _offers([odds_body(e)])
    late = _offers([odds_body(e, shift=20)])
    links = oa.link_series([*early, *late])
    assert len(links.series) == len(early) == len(late)
    assert all(len(v) == 2 for v in links.series.values())
    assert links.identity_conflicts == () and links.rescheduled == () and links.incomplete == ()
    ident = oa.observation_identity(early[0])
    assert ident.provider_event_id == "g1" and ident.sport_key == SPORT and ident.league == "NFL"
    assert ident.home_team == "New York Giants" and ident.commence_time_utc == "2026-10-04T17:00:00+00:00"


def test_distinct_events_with_equal_or_similar_team_names_never_collapse():
    games = [ev("g1", utc(2026, 10, 4, 17), "New York Giants", "Dallas Cowboys"),
             ev("g2", utc(2026, 12, 27, 18), "New York Giants", "Dallas Cowboys"),  # the rematch
             ev("g3", utc(2026, 11, 8, 18), "Dallas Cowboys", "New York Giants"),  # home and away swapped
             ev("g4", utc(2026, 10, 4, 17), "New York Jets", "Dallas Cowboys"),  # a similar name
             ev("g5", utc(2026, 10, 4, 17), "New York Giants", "Dallas Cowboys")]  # same teams + start, new id
    offers = _offers([odds_body(g, books=("draftkings",)) for g in games])
    links = oa.link_series(offers)
    per_event = {}
    for sid, obs in links.series.items():
        assert len({o.event_id for o in obs}) == 1  # a series never spans two events
        per_event.setdefault(obs[0].event_id, set()).add(sid)
    assert len(per_event) == 5 and len(set().union(*per_event.values())) == len(offers)
    assert links.identity_conflicts == ()


def test_line_side_book_and_market_are_part_of_the_identity():
    e = ev("g1", utc(2026, 10, 4, 17), "Home", "Away")
    base = odds_body(e)
    moved = json.loads(json.dumps(base))
    for book in moved["bookmakers"]:
        for m in book["markets"]:
            if m["key"] == "spreads":
                m["outcomes"][0]["point"], m["outcomes"][1]["point"] = -3.0, 3.0
            if m["key"] == "totals":
                for o in m["outcomes"]:
                    o["point"] = "44.50"  # same line, different spelling
    ids_a = {oa.observation_identity(o).series_id: o for o in _offers([base])}
    ids_b = {oa.observation_identity(o).series_id: o for o in _offers([moved])}
    common = set(ids_a) & set(ids_b)
    assert {ids_a[s].market_key for s in common} == {"h2h", "totals"}  # -3.5 and -3 never link
    assert oa.normalize_line("44.50") == oa.normalize_line("44.5") == "44.5"
    assert oa.normalize_line("30") == "30" and oa.normalize_line("-0.0") == "0" and oa.normalize_line("x") == "x"
    assert len({oa.observation_identity(o).series_id for o in _offers([base])}) == len(_offers([base]))


def test_an_event_id_reported_with_other_teams_is_a_conflict_and_is_not_merged():
    a = ev("g1", utc(2026, 10, 4, 17), "Home", "Away")
    b = ev("g1", utc(2026, 10, 4, 17), "Other Home", "Away")
    moved = ev("g1", utc(2026, 10, 5, 0, 15), "Home", "Away")
    bare = {"id": "g9", "commence_time": "2026-10-04T17:00:00Z", "bookmakers": odds_body(a)["bookmakers"]}
    links = oa.link_series(_offers([odds_body(a)]) + _offers([odds_body(b)]) + _offers([odds_body(moved)])
                           + _offers([bare]))
    assert links.identity_conflicts == ("g1",) and links.rescheduled == ("g1",)
    assert all(len(v) == 1 for v in links.series.values())  # three versions of g1, never merged
    assert links.incomplete and all(links.series[s][0].event_id == "the_odds_api:g9" for s in links.incomplete)


# ================================================================== 3. research values stay separate, never executable

def test_offered_implied_devigged_and_consensus_are_distinct_labelled_and_not_executable():
    e = ev("g1", utc(2026, 10, 4, 17), "Home", "Away")
    snap = oa.parse_odds([odds_body(e, books=("draftkings", "fanduel", "betmgm"))], odds_format="american")
    offer = next(o for o in snap.offers if o.market_key == "h2h" and o.bookmaker == "draftkings")
    implied = [oa.implied_probability(o) for o in snap.offers if o.market_key == "h2h" and o.bookmaker == "draftkings"]
    devig = oa.devig_by_market(snap)[(offer.event_id, "draftkings", "h2h")]
    consensus = oa.consensus_by_market(snap)
    h2h = next(v for k, v in consensus.items() if k[1] == "h2h")
    assert offer.raw_price == "-150" and offer.decimal_odds is not None  # offered, as received
    assert sum(i.probability for i in implied) > 1  # implied still holds the margin
    assert sum(devig.probabilities) == pytest.approx(Decimal(1)) and devig.outcomes  # fair estimate, one book
    assert sum(h2h.probabilities) == pytest.approx(Decimal(1)) and h2h.bookmakers == ("betmgm", "draftkings", "fanduel")
    labels = {implied[0].label, devig.label, h2h.label}
    assert labels == {oa.IMPLIED_WITH_MARGIN, oa.RESEARCH_ONLY, oa.RESEARCH_ONLY_CONSENSUS}
    for value in (offer, implied[0], devig, h2h):
        assert value.executable is False and not isinstance(value, ExecutableQuote)
    assert len({type(v) for v in (offer, implied[0], devig, h2h)}) == 4
    # The consensus pools only identical propositions; one book is not a consensus.
    single = oa.parse_odds([odds_body(e, books=("draftkings",))], odds_format="american")
    assert oa.consensus_by_market(single) == {}
    with pytest.raises(ValueError):
        oa.consensus_by_market(snap, min_books=1)
    assert oa.implied_probability(oa.OddsOffer("x", "m", "b", "h2h", "A", None, "abc", "decimal", None, None)) is None


def test_different_spread_lines_are_never_pooled_into_one_consensus():
    e = ev("g1", utc(2026, 10, 4, 17), "Home", "Away")
    a = odds_body(e, books=("draftkings", "fanduel"))
    b = json.loads(json.dumps(a))
    for m in b["bookmakers"][1]["markets"]:
        if m["key"] == "spreads":
            m["outcomes"][0]["point"], m["outcomes"][1]["point"] = -3.0, 3.0
    spreads = {k: v for k, v in oa.consensus_by_market(oa.parse_odds([b], odds_format="american")).items()
               if k[1] == "spreads"}
    assert spreads == {}  # -3.5 at one book and -3 at the other: no consensus at all


def test_nothing_from_the_odds_modules_can_reach_an_executable_quote_or_qualify():
    for name in ("odds_api.py", "odds_pilot.py", "odds_schedule.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", '"')))
        for forbidden in ("ExecutableQuote(", "DepthLadder(", "evaluate(", "evaluate_event(", "best_price",
                          "shadow_ledger", "record_fill", "record_decision"):
            assert forbidden not in code, (name, forbidden)
    # Even a forged quote on a sportsbook market cannot qualify: the payoff is not a binary
    # contract paying 1, the house rules are not captured and no fee model exists.
    e = ev("g1", utc(2026, 10, 4, 17), "Home", "Away")
    snap = oa.parse_odds([odds_body(e)], odds_format="american")
    market = snap.markets[0]
    forged = ExecutableQuote(market.venue, market.market_id, "YES", None, Decimal("0.40"), Decimal(100),
                             "2026-10-04T16:59:00+00:00", None, "forged")
    result = evaluate(event=snap.events[0], market=market, side="YES", quote=forged, estimate=None,
                      fee_schedule=schedule_for("the_odds_api"),
                      policy=Policy("p", "point", Decimal(0), 1, timedelta(minutes=5), timedelta(hours=1), "flag"),
                      as_of=utc(2026, 10, 4, 17))
    assert result.qualification == "REJECT"
    assert {"PAYOFF_UNSUPPORTED", "RULES_UNRESOLVED", "FEE_UNSUPPORTED"} <= set(result.reasons)


# ================================================================== 4. storage contract: prospective time series

def _all_snapshot_columns(db: Path, sid: int) -> dict:
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM snapshots WHERE id = ?", (sid,)).fetchone())


def test_repeated_captures_are_kept_as_a_time_series_with_every_contract_field(paths, tmp_path):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    _, first = tick(paths, provider, utc(2026, 10, 4, 11, 0))  # T-6h of the 13:00 games (e1, e2)
    provider.shift = 25
    provider.markets = ("h2h", "spreads")  # the book pulls totals: partial coverage
    _, second = tick(paths, provider, utc(2026, 10, 4, 16, 0))  # T-60m of the same games
    assert first["state"] == second["state"] == "CAPTURED"
    sids = [first["fired"]["snapshot_id"], second["fired"]["snapshot_id"]]
    assert sids[0] != sids[1]  # a new row per observation, never overwritten
    rows = [_all_snapshot_columns(paths[0], s) for s in sids]
    spec = get_source("the_odds_api")
    observations = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        # request identity (redacted), source hash, parser/schema version, receipt time, quota metadata
        assert "apiKey=REDACTED" in row["url"] and FAKE not in row["payload_json"]
        assert row["raw_sha256"] and len(row["raw_sha256"]) == 64 and row["payload_sha256"]
        assert row["parser_version"] == oa.PARSER_VERSION and row["schema_version"] == spec.schema_version
        assert row["source_id"] == "the_odds_api" and row["fetched_at_utc"] and row["http_status"] == 200
        req = payload["request"]
        assert req["purpose"] == "capture" and req["markets"] == ["h2h", "spreads", "totals"]
        assert req["regions"] == ["us"] and req["slot_id"] and req["commence_from"] and req["targets"]
        assert all({"target_id", "event_id", "offset", "target_utc"} <= set(t) for t in req["targets"])
        assert set(payload["quota_headers"]) == {"x-requests-last", "x-requests-remaining", "x-requests-used"}
        # event, book, market, side, threshold, odds, provider update time: in the raw provider body
        snap = oa.parse_odds(payload["events"], odds_format=req["odds_format"], received_at_utc=row["fetched_at_utc"],
                             evidence_id=str(row["id"]))
        for o in snap.offers:
            assert o.event_id and o.bookmaker and o.market_key and o.outcome_name and o.raw_price
            assert o.home_team and o.away_team and o.commence_time_utc and o.sport_key == SPORT
            if o.market_key in ("spreads", "totals"):
                assert o.point is not None
            if o.market_key == "h2h":
                assert o.market_last_update_utc
            observations.append((row["id"], row["fetched_at_utc"], o))
    links = oa.link_series(o for _, _, o in observations)
    h2h = [v for v in links.series.values() if v[0].market_key == "h2h"]
    assert h2h and all(len(v) == 2 for v in h2h)  # the same proposition at T-6h and T-60m
    assert all(v[0].raw_price != v[1].raw_price for v in h2h)  # the price moved and both are kept
    totals = [v for v in links.series.values() if v[0].market_key == "totals"]
    assert totals and all(len(v) == 1 for v in totals)  # missing in the second capture, not zero
    # Coverage per target: missing markets recorded, not guessed.
    store = SnapshotStore(paths[0])
    late = [r for r in store.odds_targets(sport=SPORT) if r["snapshot_id"] == sids[1]]
    assert late and all(json.loads(r["detail_json"])["missing_markets"] == ["totals"] for r in late)
    assert all(r["credits_last"] == 3 and r["captured_at_utc"] for r in late)
    no_key_anywhere(tmp_path, first, second)


def _health(db: Path, source_id: str = op.HEALTH_ODDS) -> list[dict]:
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM source_health WHERE source_id = ? ORDER BY id",
                                              (source_id,))]


def test_failed_and_successful_collections_are_recorded_as_source_health(paths, tmp_path):
    provider = Provider(WEEK)
    provider.events_error = URLError(f"down apiKey={FAKE}")
    tick(paths, provider, utc(2026, 10, 3, 4, 0))
    provider.events_error = None
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    assert _health(paths[0]) == []  # a free discovery is never reported as odds-feed health
    provider.odds_error = HTTPError("u", 500, "Error", {}, None)
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    provider.odds_error = None
    tick(paths, provider, utc(2026, 10, 3, 20, 25))
    spec = get_source(op.HEALTH_DISCOVERY)  # a registered source, not an unknown id on the dashboard
    assert spec.status.value == "planned" and spec.max_age == {"events": timedelta(hours=6, minutes=30)}
    discovery = _health(paths[0], op.HEALTH_DISCOVERY)
    # failed (04:00); ok (10:00); ok (17:00, 6 h later). records = snapshots stored.
    assert [r["status"] for r in discovery] == ["failed", "ok", "ok"]
    assert "discovery FAILED" in discovery[0]["error"] and discovery[0]["records"] == 0
    assert discovery[1]["records"] == discovery[2]["records"] == 1
    odds = _health(paths[0])
    assert [r["status"] for r in odds] == ["failed", "ok"]
    assert "capture" in odds[0]["error"] and odds[0]["http_errors"] == 1 and odds[0]["records"] == 0
    assert odds[1]["records"] == 1 and odds[1]["error"] is None
    no_key_anywhere(tmp_path)


def test_a_rejected_key_is_recorded_once_per_attempt(paths, tmp_path):
    provider = Provider(WEEK)
    provider.events_error = HTTPError("u", 401, "Unauthorized", {}, None)
    tick(paths, provider, utc(2026, 10, 3, 4, 0))
    tick(paths, provider, utc(2026, 10, 3, 4, 15))  # paced: no second attempt, no second row
    rows = _health(paths[0], op.HEALTH_DISCOVERY)
    assert len(rows) == 1 and rows[0]["status"] == "failed" and "KEY_REJECTED" in rows[0]["error"]
    assert _health(paths[0]) == []


def test_an_empty_odds_response_is_a_partial_health_row(paths):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    provider.events = []  # the games vanish from the odds endpoint (free, empty response)
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    (row,) = _health(paths[0])
    assert row["status"] == "partial" and "no offers" in row["anomalies_json"] and row["records"] == 1


def test_a_failing_health_write_never_changes_what_a_capture_recorded(paths, monkeypatch, capsys):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))

    def boom(self, **kw):
        raise sqlite3.OperationalError(f"disk full apiKey={FAKE}")

    monkeypatch.setattr(SnapshotStore, "record_source_health", boom)
    code, report = tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert code == 0 and report["state"] == "CAPTURED" and len(provider.paid()) == 1
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert sum(r["state"] == "CAPTURED" for r in rows) == 2
    err = capsys.readouterr().err
    assert "source_health row not written" in err and FAKE not in err


def test_the_health_row_is_written_after_the_capture_transitions(paths, monkeypatch):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    seen = []
    original = SnapshotStore.record_source_health

    def spy(self, **kw):
        if kw["source_id"] == op.HEALTH_ODDS:
            seen.append({r["state"] for r in self.odds_targets(sport=SPORT)
                         if r["event_id"] in ("e1", "e2") and r["offset_label"] == "T-24h"})
        return original(self, **kw)

    monkeypatch.setattr(SnapshotStore, "record_source_health", spy)
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert seen == [{"CAPTURED"}]  # the targets were already final when the health row was written
    provider.odds_error = HTTPError("u", 500, "Error", {}, None)
    seen.clear()
    tick(paths, provider, utc(2026, 10, 3, 20, 25))
    assert _health(paths[0])[-1]["status"] == "failed"
    states = {r["state"] for r in SnapshotStore(paths[0]).odds_targets(sport=SPORT)
              if r["event_id"] == "e3" and r["offset_label"] == "T-24h"}
    assert states == {"FAILED"}


# ================================================================== 5. a whole NFL month under 450

def _et(y, m, d, h, mi=0) -> datetime:
    return sch._from_et(datetime(y, m, d, h, mi))


def season_2026() -> list[dict]:
    """A realistic 2026 season shape (NOT the published schedule; kickoffs in ET).

    Weekly: TNF 20:15, Sunday 13:00 (8 games), 16:05 (2), 16:25 (3), SNF 20:20, MNF 20:15.
    Extras: a Friday opener abroad (Sep 11 20:00), a Monday doubleheader (Sep 21 19:00 and 22:00),
    three London Sundays (09:30) in October, Germany and Madrid Sundays (09:30) in November,
    Thanksgiving (12:30, 16:30, 20:20) and Black Friday (15:00), Saturday tripleheaders on
    Dec 19 and Dec 26, three Christmas Friday games (13:00, 16:30, 20:15) after a Christmas Eve
    TNF (that week has 11 kickoff groups, the planner's worst-case maximum), and week 18 on
    Sat 2 / Sun 3 Jan 2027."""
    games: list[datetime] = []
    thursdays = [datetime(2026, 9, 10) + timedelta(weeks=i) for i in range(17)]
    london = {datetime(2026, 10, 4).date(), datetime(2026, 10, 11).date(), datetime(2026, 10, 18).date(),
              datetime(2026, 11, 8).date(), datetime(2026, 11, 15).date()}
    for thu in thursdays:
        sun, mon = thu + timedelta(days=3), thu + timedelta(days=4)
        if thu.date() == datetime(2026, 11, 26).date():  # Thanksgiving and Black Friday
            games += [_et(2026, 11, 26, 12, 30), _et(2026, 11, 26, 16, 30), _et(2026, 11, 26, 20, 20),
                      _et(2026, 11, 27, 15, 0)]
        else:
            games.append(_et(thu.year, thu.month, thu.day, 20, 15))
        if sun.date() in london:
            games.append(_et(sun.year, sun.month, sun.day, 9, 30))
        games += [_et(sun.year, sun.month, sun.day, 13)] * 8 + [_et(sun.year, sun.month, sun.day, 16, 5)] * 2
        games += [_et(sun.year, sun.month, sun.day, 16, 25)] * 3 + [_et(sun.year, sun.month, sun.day, 20, 20)]
        games.append(_et(mon.year, mon.month, mon.day, 20, 15))
    games += [_et(2026, 9, 11, 20), _et(2026, 9, 21, 19), _et(2026, 9, 21, 22)]
    for day in (19, 26):
        games += [_et(2026, 12, day, 13), _et(2026, 12, day, 16, 30), _et(2026, 12, day, 20, 15)]
    games += [_et(2026, 12, 25, 13), _et(2026, 12, 25, 16, 30), _et(2026, 12, 25, 20, 15)]
    games += [_et(2027, 1, 2, 16, 30), _et(2027, 1, 2, 20)] + [_et(2027, 1, 3, 13)] * 9
    games += [_et(2027, 1, 3, 16, 25)] * 4 + [_et(2027, 1, 3, 20, 20)]
    return [ev(f"s{i:03d}", when, f"Home {i}", f"Away {i}") for i, when in enumerate(sorted(games))]


def _tick_times(events: list[dict], start: datetime, end: datetime) -> list[datetime]:
    """The quarter-hour timer ticks that matter: every 12 h for discovery (fresh for 24 h), and
    for each capture target the first tick at most 7 minutes before it plus the next one (two
    slots due in the same quarter hour fire on consecutive ticks). The timer's other ticks find
    nothing due and change nothing; they are skipped to keep this fast."""
    cfg = sch.PilotConfig()
    scheduled = [sch.ScheduledEvent(e["id"], SPORT, datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")))
                 for e in events]
    times = set()
    t = start
    while t < end:
        times.add(t)
        t += timedelta(hours=12)
    for target in sch.plan_targets(scheduled):
        due = sch.effective_due(target, cfg)
        q = due - timedelta(minutes=7)
        q = q.replace(second=0, microsecond=0) + timedelta(minutes=(-q.minute) % 15)
        for k in range(2):
            if start <= q + timedelta(minutes=15 * k) < end:
                times.add(q + timedelta(minutes=15 * k))
    return sorted(times)


def simulate(paths, start: datetime, end: datetime, *, month: str, used: int = 0, remaining: int = 500):
    clock = Clock(start)
    events = season_2026()
    provider = Provider(events, clock=clock, used=used, remaining=remaining)
    worst_seen = 0
    states = Counter()
    for at in _tick_times(events, start, end):
        clock.at = at
        code, report = op.run_tick(paths[0], paths[1], clock=clock, opener=provider, environ=ENV)
        states[report["state"]] += 1
        worst = (report.get("budget") or {}).get("worst_case_month_credits")
        if worst is not None:
            assert worst <= 450, (at, report["budget"])
            worst_seen = max(worst_seen, worst)
        assert report["state"] not in ("FAILED", "COST_ANOMALY"), report
    rows = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    settled_by = (end - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")  # targets whose fate is known
    in_month = [r for r in rows if r["target_utc"].startswith(month) and r["target_utc"] <= settled_by]
    credits = sum(c for m, c in provider.charges if m == month)
    calls = sum(1 for m, c in provider.charges if m == month)
    by = Counter((r["offset_label"], r["state"]) for r in in_month)
    return {"credits": credits, "calls": calls, "worst_case_seen": worst_seen, "targets": len(in_month),
            "by_offset_state": dict(sorted(by.items())), "provider": provider, "tick_states": states}


# Deterministic results (reproduce: this simulation). October matches ADR 0029's table (74 calls,
# 222 credits, worst case 225). December is the heaviest month (Christmas week has 11 kickoff groups).
@pytest.mark.parametrize("month,calls,worst", [((2026, 10), 74, 225), ((2026, 12), 90, 273)])
def test_a_whole_season_month_stays_under_450_with_every_closing_line_captured(paths, month, calls, worst):
    start = utc(*month, 1)
    end = utc(month[0] + month[1] // 12, month[1] % 12 + 1, 1)
    # Start a day early so the month begins with a discovery already made, as in production.
    out = simulate(paths, start - timedelta(days=1), end, month=start.strftime("%Y-%m"))
    assert out["credits"] <= 450 and out["credits"] <= 500
    assert out["calls"] == calls and out["credits"] == 3 * calls, out
    assert out["worst_case_seen"] == worst <= 450
    missing = {k: v for k, v in out["by_offset_state"].items() if k[1] != "CAPTURED"}
    assert missing == {}, missing  # with the full free allowance every target is captured
    assert out["provider"].remaining >= 50  # the provider never came near its own limit


def test_a_month_with_most_of_the_allowance_already_used_keeps_closing_lines_first(paths):
    start = utc(2026, 12, 1)
    out = simulate(paths, start, utc(2026, 12, 21), month="2026-12", used=380, remaining=120)
    # The provider already counted 380 this month: at most 450 - 380 - 3 = 67 credits (22 calls).
    assert out["credits"] == 51 <= 450 - 380 - 3 and out["provider"].used <= 450  # 17 calls
    by = out["by_offset_state"]
    # Every closing-line (T-60m) target is captured; T-6h and T-24h give way (skipped, then missed).
    assert by.get(("T-60m", "CAPTURED"), 0) > 0 and not any(k[0] == "T-60m" and k[1] != "CAPTURED" for k in by)
    assert not any(k[0] != "T-60m" and k[1] == "CAPTURED" for k in by)
    missed = SnapshotStore(paths[0]).odds_targets(sport=SPORT)
    assert any(r["state"] == "MISSED" and "SKIPPED_BUDGET" in (r["reason"] or "") for r in missed)


# ================================================================== 6. dashboard status (read-only)

def _fingerprint(root: Path) -> dict[str, str]:
    """Every file's hash. SQLite's WAL index (-shm) and an EMPTY write-ahead log may appear when
    a WAL database is opened read-only; they carry no data, so they are left out."""
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.endswith("-shm"):
            continue
        if p.name.endswith("-wal") and p.stat().st_size == 0:
            continue
        out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def status(paths, at):
    return op.dashboard_status(paths[0], paths[1], state_path(paths), now=at)


def test_nothing_installed_is_setup_needed_and_creates_nothing(paths, tmp_path):
    out = status(paths, utc(2026, 10, 3, 12))
    assert out["state"] == "SETUP_NEEDED" and out["live_read_verified"] is False
    assert out["quota"]["state"] == "QUOTA_UNKNOWN" and out["latest_successful_capture"] is None
    assert out["executable"] is False and "RESEARCH ONLY" in out["label"]
    assert list(tmp_path.iterdir()) == []  # read-only: no store, ledger or state file created
    assert json.dumps(out)  # plain JSON for the dashboard


def test_a_successful_discovery_is_not_a_live_read(paths, tmp_path):
    tick(paths, Provider(WEEK), utc(2026, 10, 3, 10, 0))
    before = _fingerprint(tmp_path)
    out = status(paths, utc(2026, 10, 3, 10, 5))
    assert _fingerprint(tmp_path) == before
    assert out["state"] == "SETUP_NEEDED" and out["live_read_verified"] is False
    assert "no odds read has succeeded" in out["detail"]
    assert out["quota"]["state"] == "READY" and out["discovery"]["events"] == len(WEEK)
    assert out["next_capture"]["offset"] == "T-24h" and out["targets"]["open"] > 0


def test_active_only_after_a_stored_live_read_and_never_writes(paths, tmp_path):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))  # first paid capture
    before = _fingerprint(tmp_path)
    out = status(paths, utc(2026, 10, 3, 17, 5))
    assert _fingerprint(tmp_path) == before
    assert out["state"] == "ACTIVE" and out["live_read_verified"] is True
    cap = out["latest_successful_capture"]
    assert cap["purpose"] == "capture" and cap["offers"] > 0 and cap["payload_sha256"]
    assert out["markets_observed"] == ["h2h", "spreads", "totals"]
    assert out["bookmakers_observed"] == ["draftkings", "fanduel"]
    assert out["quota"]["provider_used"] == 3 and out["quota"]["ceiling"] == 450
    assert out["next_capture"] is not None and out["targets"]["by_state"]["CAPTURED"] == 2
    assert out["timer"] == "NOT_OBSERVABLE_HERE"
    no_key_anywhere(tmp_path, out)
    # A day later without a discovery: stale, not active.
    assert status(paths, utc(2026, 10, 4, 18, 0))["state"] == "DISCOVERY_STALE"


@pytest.mark.parametrize("status_code", [401, 403])
def test_a_rejected_key_shows_key_rejected(paths, status_code):
    provider = Provider(WEEK)
    provider.events_error = HTTPError("u", status_code, "no", {}, None)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    out = status(paths, utc(2026, 10, 3, 10, 5))
    assert out["state"] == "KEY_REJECTED" and out["live_read_verified"] is False


def test_cost_blocks_and_damaged_files_are_shown_not_repaired(paths, tmp_path):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    sp = state_path(paths)
    data = json.loads(sp.read_text())
    sp.write_text(json.dumps(data | {"cost_block": {"reason": "COST_ANOMALY", "charged": 6, "estimate": 3}}))
    out = status(paths, utc(2026, 10, 3, 17, 5))
    assert out["state"] == "COST_BLOCKED" and "COST_ANOMALY" in out["detail"]
    sp.write_text("{broken")
    assert status(paths, utc(2026, 10, 3, 17, 5))["state"] == "COST_BLOCKED"
    assert sp.read_text() == "{broken"  # shown, never rewritten
    sp.unlink()
    assert status(paths, utc(2026, 10, 3, 17, 5))["state"] == "COST_BLOCKED"  # missing although paid calls exist
    assert not sp.exists()
    paths[1].write_text("{not json")
    out = status(paths, utc(2026, 10, 3, 17, 5))
    assert out["state"] == "ERROR" and out["quota"]["state"] == "UNREADABLE"


def test_quota_unknown_and_exhausted_are_reported_after_a_live_read(paths):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    led = oa.QuotaLedger(paths[1], clock=Clock(utc(2026, 10, 3, 17, 1)))
    led.reconcile(quota(40, 450))
    assert status(paths, utc(2026, 10, 3, 17, 2))["state"] == "QUOTA_EXHAUSTED"
    led.reconcile({"X-Requests-Remaining": "x"})
    assert status(paths, utc(2026, 10, 3, 17, 3))["state"] == "QUOTA_UNKNOWN"


def test_an_empty_odds_read_is_not_a_live_read(paths):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    provider.events = []  # the paid call returns [] (free): stored, but it proves nothing
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    assert SnapshotStore(paths[0]).latest_snapshot(source="the_odds_api", kind="odds", entity_id=SPORT)
    out = status(paths, utc(2026, 10, 3, 17, 5))
    assert out["state"] == "SETUP_NEEDED" and out["live_read_verified"] is False
    assert "none held any offers" in out["detail"]


def test_an_older_read_with_offers_still_verifies_but_newer_empty_reads_are_reported(paths):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))  # offers
    provider.events = [e for e in WEEK if e["id"] != "e3"]
    tick(paths, provider, utc(2026, 10, 3, 20, 25))  # e3's window is now empty
    out = status(paths, utc(2026, 10, 3, 20, 30))
    assert out["live_read_verified"] is True and out["latest_successful_capture"]["offers"] > 0
    assert any("held no offers" in p for p in out["problems"])


def test_failing_captures_after_a_success_are_degraded_not_active(paths):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))  # success
    assert status(paths, utc(2026, 10, 3, 17, 5))["state"] == "ACTIVE"
    provider.odds_error = HTTPError("u", 502, "Bad Gateway", {}, None)
    tick(paths, provider, utc(2026, 10, 3, 20, 25))  # the next paid attempt fails
    # The failed call also made the quota ambiguous; DEGRADED names the failing capture first.
    out = status(paths, utc(2026, 10, 3, 20, 30))
    assert out["state"] == "DEGRADED" and "failed" in out["detail"]
    assert any("latest paid capture attempt failed" in p for p in out["problems"])
    provider.odds_error = None
    _, report = tick(paths, provider, utc(2026, 10, 4, 0, 20))  # SNF's T-24h: free reconcile, then success
    assert report["state"] == "CAPTURED"
    assert status(paths, utc(2026, 10, 4, 0, 25))["state"] == "ACTIVE"


def test_missing_store_with_paid_history_or_unreadable_evidence_is_error(paths, tmp_path, monkeypatch):
    provider = Provider(WEEK)
    tick(paths, provider, utc(2026, 10, 3, 10, 0))
    tick(paths, provider, utc(2026, 10, 3, 17, 0))
    moved = tmp_path / "elsewhere.sqlite3"
    out = op.dashboard_status(moved, paths[1], state_path(paths), now=utc(2026, 10, 3, 17, 5))
    assert out["state"] == "ERROR" and "missing" in out["detail"] and not moved.exists()
    # A stored odds payload that cannot be read is ERROR: not a crash and not a guess.
    real = SnapshotStore.snapshots_of_kind
    monkeypatch.setattr(SnapshotStore, "snapshots_of_kind",
                        lambda self, **kw: [dict(r) | {"payload_json": "{not json"} for r in real(self, **kw)])
    out = status(paths, utc(2026, 10, 3, 17, 5))
    assert out["state"] == "ERROR" and "unreadable" in out["detail"]
