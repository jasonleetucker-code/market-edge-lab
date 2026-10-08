"""The Odds API adapter foundation: quota, redaction, identity, research-only estimates (fixtures only)."""

from __future__ import annotations

import json
import threading
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from conftest import FakeResponse
from edge_lab import odds_api as oa
from edge_lab.fee_schedules import schedule_for
from edge_lab.opportunity import ExecutableQuote, Policy, evaluate
from edge_lab.sources import get_source
from edge_lab.storage import SnapshotStore

FIXTURES = Path(__file__).parent / "fixtures" / "odds_api"
ODDS = json.loads((FIXTURES / "v4_odds_nfl_h2h_spreads_american_documented.json").read_text())
SPORTS = json.loads((FIXTURES / "v4_sports_documented.json").read_text())
FAKE = "FAKEoddsKEY0123456789zz"  # not a real key; tests scan for it everywhere
ENV = {get_source("the_odds_api").credential_env_var: FAKE}
UTC = timezone.utc
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_default_network(monkeypatch):
    """The adapter's own no-redirect opener must never reach the network in tests either."""
    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real network call: {request.full_url}")

    monkeypatch.setattr(oa, "_no_redirect_opener", refuse)


class HeaderResponse(FakeResponse):
    def __init__(self, body: bytes, *, url: str, headers: dict[str, str], status: int = 200):
        super().__init__(body, status=status, url=url)
        self.headers = {"Content-Type": "application/json", **headers}


class Opener:
    """Replays steps; each step is (payload, headers), an exception, or (payload, headers, final_url)."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[str] = []

    def __call__(self, request, timeout):
        self.calls.append(request.get_method() + " " + request.full_url)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        payload, headers, *final = step
        return HeaderResponse(json.dumps(payload).encode(), url=final[0] if final else request.full_url,
                              headers=headers)


def quota(remaining: int, used: int, last: int | None = 0) -> dict[str, str]:
    h = {"X-Requests-Remaining": str(remaining), "X-Requests-Used": str(used), "Set-Cookie": "session=abc"}
    if last is not None:
        h["X-Requests-Last"] = str(last)
    return h


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def ledger(tmp_path: Path, ceiling: int = 450, clock: Clock | None = None) -> oa.QuotaLedger:
    return oa.QuotaLedger(tmp_path / "quota.json", ceiling, clock=clock or Clock(NOW), lock_timeout_s=10)


def reconciled(tmp_path: Path, remaining: int = 400, used: int = 100, **kw) -> oa.QuotaLedger:
    led = ledger(tmp_path, **kw)
    assert led.reconcile(quota(remaining, used)) is oa.QuotaState.READY
    return led


def _strings(obj) -> list[str]:
    """Every string reachable in a returned object (dataclasses, containers, exceptions)."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, bytes):
            out.append(v.decode("utf-8", "replace"))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, (list, tuple, set, frozenset)):
            for x in v:
                walk(x)
        elif hasattr(v, "__dataclass_fields__"):
            for f in fields(v):
                walk(getattr(v, f.name))
        elif isinstance(v, BaseException):
            out.append(str(v))
            out.append(repr(v))
    walk(obj)
    return out


# ------------------------------------------------------------------ quota arithmetic

@pytest.mark.parametrize("markets,regions,cost", [(["h2h"], ["us"], 1), (["h2h", "spreads", "totals"], ["us"], 3),
                                                  (["h2h"], ["us", "uk", "eu"], 3),
                                                  (["h2h", "spreads", "totals"], ["us", "uk", "au"], 9)])
def test_cost_is_markets_times_regions(markets, regions, cost):
    assert oa.estimate_cost(markets, regions=regions) == cost


@pytest.mark.parametrize("n_books,groups", [(1, 1), (10, 1), (11, 2), (20, 2), (21, 3)])
def test_every_group_of_ten_bookmakers_is_one_region(n_books, groups):
    books = [f"book{i}" for i in range(n_books)]
    assert oa.estimate_cost(["h2h", "spreads"], bookmakers=books) == 2 * groups


@pytest.mark.parametrize("kwargs", [
    dict(markets=[], regions=["us"]),
    dict(markets=["h2h"]),
    dict(markets=["h2h"], regions=["us"], bookmakers=["draftkings"]),
    dict(markets=["h2h", "h2h"], regions=["us"]),
    dict(markets="h2h", regions=["us"]),
    dict(markets=["H2H"], regions=["us"]),
    dict(markets=["h2h"], regions=["us&x=1"]),
])
def test_cost_inputs_are_validated(kwargs):
    with pytest.raises(ValueError):
        oa.estimate_cost(**kwargs)


def test_ceiling_must_stay_below_the_free_allowance(tmp_path):
    for bad in (0, 500, 501, -1, True):
        with pytest.raises(ValueError):
            oa.QuotaLedger(tmp_path / "q.json", bad)
    assert oa.QuotaLedger(tmp_path / "q.json").ceiling == 450


# ------------------------------------------------------------------ ledger

def test_unknown_before_any_reconciliation_and_nothing_is_reserved(tmp_path):
    led = ledger(tmp_path)
    assert led.state() is oa.QuotaState.QUOTA_UNKNOWN
    with pytest.raises(oa.QuotaRefused) as err:
        led.reserve(1)
    assert err.value.state is oa.QuotaState.QUOTA_UNKNOWN


def test_reservations_and_usage_survive_a_restart(tmp_path):
    led = reconciled(tmp_path)
    res = led.reserve(3)
    again = ledger(tmp_path)
    snap = again.snapshot()
    assert snap["outstanding"] == 3 and res.reservation_id in snap["reservations"]
    assert again.settle(res, quota(397, 103, 3)) is oa.QuotaState.READY
    third = ledger(tmp_path).snapshot()
    assert third["used_local"] == 3 and third["outstanding"] == 0 and third["last_headers"]["used"] == 103


def test_concurrent_reservations_never_exceed_the_ceiling(tmp_path):
    reconciled(tmp_path, remaining=500, used=0)
    ok, refused = [], []

    def worker():
        try:
            ok.append(ledger(tmp_path, ceiling=10).reserve(1))
        except oa.QuotaRefused as exc:
            refused.append(exc.state)

    threads = [threading.Thread(target=worker) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 10 and len(refused) == 15
    assert set(refused) == {oa.QuotaState.QUOTA_EXHAUSTED}
    assert ledger(tmp_path, ceiling=10).snapshot()["outstanding"] == 10


def test_exhaustion_by_ceiling_and_by_provider_remaining(tmp_path):
    led = reconciled(tmp_path, remaining=400, used=440)
    with pytest.raises(oa.QuotaRefused) as err:
        led.reserve(11)  # 440 + 11 > 450
    assert err.value.state is oa.QuotaState.QUOTA_EXHAUSTED
    led.reserve(10)
    assert led.state() is oa.QuotaState.QUOTA_EXHAUSTED

    other = reconciled(tmp_path / "b", remaining=2, used=10)
    with pytest.raises(oa.QuotaRefused):
        other.reserve(3)  # provider has only 2 left


@pytest.mark.parametrize("headers", [None, {}, {"x-requests-remaining": "10"},
                                     {"x-requests-remaining": "ten", "x-requests-used": "1"},
                                     {"x-requests-remaining": "-1", "x-requests-used": "1"},
                                     {"x-requests-remaining": "1.5", "x-requests-used": "1"},
                                     {"x-requests-remaining": "NaN", "x-requests-used": "1"},
                                     {"x-requests-remaining": "5.0", "x-requests-used": "1"},
                                     {"x-requests-remaining": "1e2", "x-requests-used": "1"},
                                     {"x-requests-remaining": "+5", "x-requests-used": "1"},
                                     {"x-requests-remaining": "５", "x-requests-used": "1"}])
def test_malformed_headers_are_quota_unknown(tmp_path, headers):
    assert oa.parse_quota_headers(headers) is None
    assert ledger(tmp_path).reconcile(headers) is oa.QuotaState.QUOTA_UNKNOWN


def test_malformed_headers_on_a_paid_call_keep_the_reservation(tmp_path):
    led = reconciled(tmp_path)
    res = led.reserve(2)
    assert led.settle(res, {"x-requests-remaining": "garbage"}) is oa.QuotaState.QUOTA_UNKNOWN
    snap = led.snapshot()
    assert snap["reservations"][res.reservation_id]["state"] == "AMBIGUOUS" and snap["outstanding"] == 2
    with pytest.raises(oa.QuotaRefused):
        led.reserve(1)  # unknown until reconciled again
    assert led.reconcile({"x-requests-used": "1"}) is oa.QuotaState.QUOTA_UNKNOWN
    assert led.snapshot()["outstanding"] == 2  # never dropped without a trustworthy provider reading
    led.reconcile(quota(398, 102))
    snap = led.snapshot()
    assert snap["outstanding"] == 0  # retired, with an event, once the provider counter covers it
    assert any(e["event"] == "reservation_retired" and e["reservation_id"] == res.reservation_id
               for e in snap["events"])


def test_reconciliation_retires_ambiguous_and_orphaned_reservations_only(tmp_path):
    clock = Clock(NOW)
    led = ledger(tmp_path, clock=clock)
    led.reconcile(quota(400, 100))
    orphan = led.reserve(3)  # never settled: its process "crashed"
    ambiguous = led.reserve(2)
    led.mark_ambiguous(ambiguous, "network error")
    clock.at = NOW + oa.ORPHAN_AFTER + timedelta(minutes=1)
    assert led.reconcile(quota(395, 105)) is oa.QuotaState.READY
    snap = led.snapshot()
    assert snap["reservations"] == {} and snap["outstanding"] == 0
    retired = {e["reservation_id"]: e["previous_state"] for e in snap["events"] if e["event"] == "reservation_retired"}
    assert retired == {ambiguous.reservation_id: "AMBIGUOUS", orphan.reservation_id: "RESERVED"}
    # The provider's own counter, not the retired reservations, now carries their cost.
    assert snap["last_headers"]["used"] == 105
    in_flight = led.reserve(4)  # a recent RESERVED call may still be running: kept
    clock.at += timedelta(seconds=30)
    led.reconcile(quota(395, 105))
    assert set(led.snapshot()["reservations"]) == {in_flight.reservation_id}


def test_new_utc_month_needs_reconciliation_and_never_guesses_a_reset(tmp_path):
    clock = Clock(NOW)
    led = ledger(tmp_path, clock=clock)
    led.reconcile(quota(50, 450))
    clock.at = datetime(2026, 10, 1, 0, 30, tzinfo=UTC)
    assert led.state() is oa.QuotaState.QUOTA_UNKNOWN
    assert led.reconcile(quota(50, 450)) is oa.QuotaState.QUOTA_EXHAUSTED  # provider has not reset yet
    assert led.snapshot()["last_headers"]["used"] == 450
    assert led.reconcile(quota(500, 0)) is oa.QuotaState.READY  # the provider's counter went down
    snap = led.snapshot()
    assert snap["used_local"] == 0 and any(e["event"] == "provider_reset_observed" for e in snap["events"])


def test_a_reset_is_accepted_only_from_the_providers_own_counter(tmp_path):
    led = reconciled(tmp_path, remaining=500, used=0)
    res = led.reserve(5)
    led.settle(res, quota(495, 5, 5))
    led.reconcile(quota(500, 0))  # provider reports a reset: accepted, since `used` went down
    assert led.snapshot()["used_local"] == 0


def test_a_corrupt_ledger_is_refused_not_reset(tmp_path):
    (tmp_path / "quota.json").write_text("{not json")
    with pytest.raises(ValueError):
        ledger(tmp_path).state()


def test_fetch_result_keeps_only_allowlisted_headers_and_old_constructions_work():
    from edge_lab import http

    legacy = http.FetchResult("u", "u", 200, None, b"{}", "2026-09-23T00:00:00+00:00", 1, 1, ())
    assert legacy.response_headers == ()
    kept = http.allowlisted_headers({"X-Requests-Used": "3", "Set-Cookie": "s=1", "x-requests-remaining": "7",
                                     "Authorization-Echo": "nope"})
    assert kept == (("x-requests-remaining", "7"), ("x-requests-used", "3"))
    assert http.allowlisted_headers(None) == ()


# ------------------------------------------------------------------ key handling

def test_load_key_reads_only_the_registered_variable():
    assert oa.load_key({}) is None
    assert oa.load_key({"ODDS_API_KEY": FAKE, "THE_ODDS_API_KEY": FAKE}) is None
    assert oa.load_key({get_source("the_odds_api").credential_env_var: "   "}) is None
    assert oa.load_key(ENV) == FAKE


def test_missing_key_is_setup_needed_and_sends_nothing(tmp_path):
    opener = Opener()
    led = reconciled(tmp_path)
    out = oa.fetch_odds("americanfootball_nfl", ["h2h"], regions=["us"], ledger=led, opener=opener, environ={})
    assert out.state is oa.QuotaState.SETUP_NEEDED and opener.calls == []
    assert "EDGE_LAB_ODDS_API_KEY" in out.detail and out.redacted_url is None
    assert oa.reconcile_quota(led, opener=opener, environ={}).state is oa.QuotaState.SETUP_NEEDED
    assert led.snapshot()["outstanding"] == 0


def test_build_request_redacts_and_refuses_paid_only_books():
    url, redacted = oa.build_request("americanfootball_nfl", ["h2h", "spreads"], key=FAKE, regions=["us"],
                                     odds_format="american")
    assert FAKE in url and FAKE not in redacted and "apiKey=REDACTED" in redacted
    assert url.startswith("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/?")
    with pytest.raises(ValueError):
        oa.build_request("americanfootball_nfl", ["h2h"], key=FAKE, bookmakers=["draftkings", "williamhill_us"])
    with pytest.raises(ValueError):
        oa.build_request("../orders", ["h2h"], key=FAKE, regions=["us"])
    with pytest.raises(ValueError):
        oa.build_request("americanfootball_nfl", ["h2h"], key="", regions=["us"])


def test_reconcile_uses_the_quota_free_sports_endpoint(tmp_path):
    led = ledger(tmp_path)
    opener = Opener((SPORTS, quota(480, 20, 0)))
    out = oa.reconcile_quota(led, opener=opener, environ=ENV)
    assert out.state is oa.QuotaState.READY and len(opener.calls) == 1
    assert opener.calls[0].startswith("GET https://api.the-odds-api.com/v4/sports/?apiKey=")
    assert out.fetch.response_headers == (("x-requests-remaining", "480"), ("x-requests-used", "20"),
                                          ("x-requests-last", "0"))  # Set-Cookie dropped
    assert FAKE not in " ".join(_strings(out))


def test_successful_pull_books_the_charge_and_persists_nothing_secret(tmp_path):
    led = reconciled(tmp_path)
    opener = Opener((ODDS, quota(398, 102, 2)))
    out = oa.fetch_odds("americanfootball_nfl", ["h2h", "spreads"], regions=["us"], odds_format="american",
                        ledger=led, opener=opener, environ=ENV)
    assert out.state is oa.QuotaState.READY and out.quota_after is oa.QuotaState.READY
    assert "apiKey=REDACTED" in out.fetch.final_url and "apiKey=REDACTED" in out.fetch.requested_url
    snap = led.snapshot()
    assert snap["used_local"] == 2 and snap["outstanding"] == 0

    store = SnapshotStore(tmp_path / "edge.db")
    store.start_run("run-1")
    oa.save_snapshot(store, run_id="run-1", sport="americanfootball_nfl", outcome=out)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert FAKE.encode() not in path.read_bytes(), path
    assert FAKE not in " ".join(_strings(out))
    assert FAKE in opener.calls[0]  # it was sent, as the documented query parameter only


def test_snapshot_context_is_redacted_and_stays_valid_json(tmp_path):
    """#176 review: `save_snapshot` redacts the JSON-encoded request context and parses it back. A header-shaped
    phrase inside a context string must not redact past the string's closing quote (that was invalid JSON)."""
    led = reconciled(tmp_path)
    out = oa.fetch_odds("americanfootball_nfl", ["h2h"], regions=["us"], odds_format="american",
                        ledger=led, opener=Opener((ODDS, quota(398, 102, 1))), environ=ENV)

    class Store:
        def save_snapshot(self, **kw):
            self.kw = kw
            return 1

    store = Store()
    context = {"note": "operator authorization: Basic dXNlcjpwYXNzd29yZA==", "markets": ["h2h"],
               "pasted": 'KALSHI-ACCESS-KEY: 0b5f0c33 "quoted"', "condition": "0x" + "ab" * 32}
    oa.save_snapshot(store, run_id="run-1", sport="americanfootball_nfl", outcome=out, context=context)
    request = store.kw["payload"]["request"]
    assert set(request) == {"note", "markets", "pasted", "condition"} and request["markets"] == ["h2h"]
    assert request["note"] == "operator authorization=REDACTED"
    assert request["pasted"] == "KALSHI-ACCESS-KEY=REDACTED"
    assert request["condition"] == context["condition"]  # a 0x id is not a key body
    assert "dXNlcjpwYXNzd29yZA" not in json.dumps(store.kw["payload"])


@pytest.mark.parametrize("final", [
    "https://evil.example/" + FAKE + "/odds",  # the key moved into the path
    "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/?token2=" + FAKE,  # another parameter
    "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/?apiKey=" + FAKE + "&x=1",
])
def test_redirects_are_refused_and_redacted(tmp_path, final):
    led = reconciled(tmp_path)
    with pytest.raises(oa.OddsApiError) as err:
        oa.fetch_odds("americanfootball_nfl", ["h2h"], regions=["us"], ledger=led,
                      opener=Opener((ODDS, quota(399, 101, 1), final)), environ=ENV)
    assert "redirect refused" in str(err.value) and FAKE not in str(err.value)
    assert err.value.__context__ is None and err.value.__cause__ is None
    assert led.snapshot()["reservations"]  # the call may have been charged: kept as AMBIGUOUS
    for path in tmp_path.rglob("*"):
        assert FAKE.encode() not in path.read_bytes(), path
    assert oa._redact(final, FAKE).count("REDACTED") >= 1 and FAKE not in oa._redact(final, FAKE)


def test_the_default_opener_never_follows_redirects():
    handler = oa._RefuseRedirects()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/") is None


@pytest.mark.parametrize("failure", [HTTPError("https://api.the-odds-api.com/v4/sports/x/odds/?apiKey=" + FAKE, 401,
                                               "Unauthorized", {}, None),
                                     URLError("connection reset while fetching apiKey=" + FAKE),
                                     TimeoutError("timed out")])
def test_failures_are_redacted_unchained_and_keep_the_reservation(tmp_path, failure):
    led = reconciled(tmp_path)
    with pytest.raises(oa.OddsApiError) as err:
        oa.fetch_odds("americanfootball_nfl", ["h2h"], regions=["us"], ledger=led, opener=Opener(failure),
                      environ=ENV)
    exc = err.value
    assert FAKE not in str(exc) and FAKE not in repr(exc)
    assert exc.__cause__ is None and exc.__context__ is None
    assert FAKE not in repr(exc.__context__)
    snap = led.snapshot()
    assert snap["outstanding"] == 1 and snap["state"] == "QUOTA_UNKNOWN"
    assert FAKE not in (tmp_path / "quota.json").read_text()


def test_refused_quota_sends_nothing(tmp_path):
    led = reconciled(tmp_path, remaining=400, used=449)
    opener = Opener()
    out = oa.fetch_odds("americanfootball_nfl", ["h2h", "spreads"], regions=["us"], ledger=led, opener=opener,
                        environ=ENV)
    assert out.state is oa.QuotaState.QUOTA_EXHAUSTED and opener.calls == []
    assert FAKE not in " ".join(_strings(out))


# ------------------------------------------------------------------ identity and estimates

def test_documented_sample_maps_to_events_markets_and_raw_offers():
    snap = oa.parse_odds(ODDS, odds_format="american", received_at_utc=NOW.isoformat(), evidence_id="e1")
    assert snap.problems == ()
    (event,) = snap.events
    assert event.event_id == "the_odds_api:bda33adca828c09dc3cac3a856aef176"
    assert event.target_time_utc == "2021-09-10T00:20:00+00:00"
    assert event.settlement_identity.startswith("the_odds_api:unverified:")
    books = {o.bookmaker for o in snap.offers}
    assert {"unibet", "draftkings", "fanduel", "williamhill_us"} <= books
    offer = next(o for o in snap.offers if o.bookmaker == "unibet" and o.market_key == "h2h"
                 and o.outcome_name == "Dallas Cowboys")
    assert offer.raw_price == "240" and offer.decimal_odds == Decimal("3.4") and offer.executable is False
    assert offer.market_id == "the_odds_api:unibet:bda33adca828c09dc3cac3a856aef176:h2h:Dallas Cowboys"
    spread = next(o for o in snap.offers if o.bookmaker == "unibet" and o.market_key == "spreads"
                  and o.outcome_name == "Tampa Bay Buccaneers")
    assert spread.point == "-6.5" and spread.decimal_odds == Decimal(1) + Decimal(100) / Decimal(111)
    assert all(m.venue == "the_odds_api" and m.rules_resolved is False for m in snap.markets)
    assert json.dumps(snap.to_dict())  # serializable evidence


def test_no_executable_quote_is_ever_produced():
    snap = oa.parse_odds(ODDS, odds_format="american")
    devig = oa.devig_by_market(snap)
    everything = [snap, *snap.events, *snap.markets, *snap.offers, *devig.values()]
    assert not any(isinstance(x, ExecutableQuote) for x in everything)
    assert not any(isinstance(v, ExecutableQuote) for v in vars(oa).values())
    assert all(o.executable is False for o in snap.offers)
    # The engine cannot qualify a sportsbook market: no quote (BOOK_MISSING), no fee model.
    market = snap.markets[0]
    op = evaluate(event=snap.events[0], market=market, side="YES", quote=None, estimate=None,
                  fee_schedule=schedule_for("the_odds_api"),
                  policy=Policy("p", "point", Decimal(0), 1, timedelta(minutes=5), timedelta(hours=1), "flag"),
                  as_of=NOW)
    assert op.qualification == "REJECT"
    assert {"BOOK_MISSING", "FEE_UNSUPPORTED", "RULES_UNRESOLVED", "MODEL_UNAVAILABLE"} <= set(op.reasons)


def test_devig_is_a_labelled_research_only_estimate():
    snap = oa.parse_odds(ODDS, odds_format="american")
    est = oa.devig_by_market(snap)[("the_odds_api:bda33adca828c09dc3cac3a856aef176", "unibet", "h2h")]
    assert est.label == oa.RESEARCH_ONLY and est.executable is False
    assert sum(est.probabilities) == pytest.approx(Decimal(1))
    assert est.overround > 0
    assert oa.devig_probabilities([Decimal("1.9")]) is None
    assert oa.devig_probabilities([Decimal("1.9"), None]) is None
    assert oa.devig_probabilities([Decimal("1.9"), Decimal("1")]) is None


@pytest.mark.parametrize("raw,fmt,expected", [(240, "american", Decimal("3.4")), (-200, "american", Decimal("1.5")),
                                              (100, "american", Decimal(2)), (-100, "american", Decimal(2)),
                                              (50, "american", None), (0, "american", None),
                                              ("2.25", "decimal", Decimal("2.25")), (1, "decimal", None),
                                              (True, "decimal", None), ("x", "decimal", None),
                                              ("NaN", "decimal", None)])
def test_odds_conversion(raw, fmt, expected):
    assert oa.to_decimal_odds(raw, fmt) == expected


def test_invalid_prices_are_kept_as_evidence_but_never_become_markets():
    payload = [{"id": "e1", "sport_key": "x", "commence_time": "2026-10-01T00:00:00Z", "bookmakers": [
        {"key": "draftkings", "markets": [{"key": "h2h", "last_update": "2026-09-23T14:59:00Z", "outcomes": [
            {"name": "A", "price": "abc"}, {"name": "B", "price": 1.8}]}]}]}]
    snap = oa.parse_odds(payload, odds_format="decimal")
    assert len(snap.offers) == 2 and len(snap.markets) == 1
    assert any("invalid price" in p for p in snap.problems)
    assert oa.devig_by_market(snap)[("the_odds_api:e1", "draftkings", "h2h")] is None
    assert oa.offer_freshness(snap.offers[1], now=NOW).value == "fresh"
    assert oa.offer_freshness(snap.offers[1], now=NOW + timedelta(hours=1)).value == "stale"
    assert oa.parse_odds({"not": "a list"}, odds_format="decimal").problems
    bad_line = [{"id": "e2", "bookmakers": [{"key": "fanduel", "markets": [{"key": "spreads", "outcomes": [
        {"name": "A", "price": 1.9, "point": "abc"}, {"name": "B", "price": 1.9, "point": "NaN"}]}]}]}]
    devig = oa.devig_by_market(oa.parse_odds(bad_line, odds_format="decimal"))
    assert devig == {("the_odds_api:e2", "fanduel", "spreads:invalid-line"): None}


def test_coverage_distinguishes_absent_paid_only_and_unimplemented():
    payload = json.loads(json.dumps(ODDS))
    payload[0]["bookmakers"].append({"key": "betfair_ex_uk", "markets": [
        {"key": "h2h_lay", "outcomes": [{"name": "Dallas Cowboys", "price": 3.5}, {"name": "Tampa Bay Buccaneers",
                                                                                   "price": 1.4}]}]})
    snap = oa.parse_odds(payload, odds_format="american")
    rows = {(r.scope, r.key): r.status for r in oa.coverage(snap, requested_bookmakers=["draftkings", "espnbet"],
                                                            requested_markets=["h2h", "totals"])}
    assert rows[("bookmaker", "draftkings")] is oa.CoverageStatus.RETURNED
    assert rows[("bookmaker", "espnbet")] is oa.CoverageStatus.ABSENT
    assert rows[("bookmaker", "fanatics")] is oa.CoverageStatus.PAID_ONLY_NOT_ENABLED
    assert rows[("bookmaker", "williamhill_us")] is oa.CoverageStatus.PAID_ONLY_NOT_ENABLED
    assert rows[("market", "totals")] is oa.CoverageStatus.ABSENT
    assert rows[("market", "h2h_lay")] is oa.CoverageStatus.UNIMPLEMENTED
    assert rows[("market", "h2h")] is oa.CoverageStatus.RETURNED
