"""Forward Stage-B collector (ADR 0012): timing gates, validity, failure modes. No network.

Fixtures in tests/fixtures/forward are real public payloads captured on 2026-09-22:
the KXHIGHNY-26SEP23 event (six open brackets), its market list and one order book, and
PFMOKX FOUS51 KOKX 221853 from api.weather.gov (Central Park max for 2026-09-23: 67 F).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import cli, forward
from edge_lab.http import FetchResult, HttpFetchError
from edge_lab.storage import SnapshotStore

FIX = Path(__file__).parent / "fixtures" / "forward"
D = date(2026, 9, 23)  # decision 2026-09-22 18:00 EDT = 22:00Z
UTC = timezone.utc


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


EVENT = _load("event_KXHIGHNY-26SEP23.json")
MARKETS = _load("markets_KXHIGHNY-26SEP23.json")
BOOK = _load("orderbook_KXHIGHNY-26SEP23-B69.5.json")
PFM_PRODUCT = _load("pfm_product_366aab20.json")
PFM_ID = "366aab20-ab3f-4c80-afb3-d6a9f05e62ad"
BRACKETS = sorted(m["ticker"] for m in MARKETS["markets"])


def at(hh: int, mm: int, ss: int = 0, day: int = 22) -> datetime:
    return datetime(2026, 9, day, hh, mm, ss, tzinfo=UTC)


class Clock:
    """Deterministic time: sleeping and fetching advance it."""

    def __init__(self, start: datetime):
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class FakeApi:
    """Routes URL fragments to payloads (or exceptions); each call takes `latency`."""

    def __init__(self, clock: Clock, routes: dict | None = None, latency: float = 0.4):
        self.clock = clock
        self.latency = latency
        self.calls: list[str] = []
        self.routes = routes if routes is not None else default_routes()

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        self.clock.now += timedelta(seconds=self.latency)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if callable(payload):
                    payload = payload(url)
                if isinstance(payload, BaseException):
                    raise payload
                result = FetchResult(url, url, 200, "application/json", json.dumps(payload).encode(),
                                     self.clock.now.isoformat(), 1, 1)
                return payload, result
        raise AssertionError(f"unexpected url {url}")

    def count(self, fragment: str) -> int:
        return sum(fragment in c for c in self.calls)


def default_routes() -> dict:
    return {
        "/orderbook": BOOK,
        "/events/KXHIGHNY-26SEP23": EVENT,
        "/markets?event_ticker=KXHIGHNY-26SEP23": MARKETS,
        "/products/types/PFM/locations/OKX": {"@graph": [
            {"id": PFM_ID, "issuanceTime": "2026-09-22T18:53:00+00:00"},
        ]},
        f"/products/{PFM_ID}": PFM_PRODUCT,
    }


@pytest.fixture
def store(tmp_path):
    s = SnapshotStore(tmp_path / "fwd.sqlite3")
    return s


def _run(store, phase, clock, api, monkeypatch, run_id=None, **kw):
    monkeypatch.setattr(forward, "fetch_json_result", api)
    run_id = run_id or f"{phase}-{clock.now.isoformat()}"
    store.start_run(run_id)
    fn = {"pfm": forward.capture_pfm, "decision": forward.capture_decision,
          "recheck": forward.capture_recheck}[phase]
    extra = {"user_agent": "test"} if phase == "pfm" else {}
    outcome = fn(store, run_id=run_id, clock=clock, sleep=clock.sleep, **extra, **kw)
    store.finish_run(run_id, status="succeeded" if outcome.status == "complete" else "failed",
                     error=None if outcome.status == "complete" else outcome.status)
    return outcome


def _full_day(store, monkeypatch, api_routes=None):
    clock = Clock(at(21, 45))
    api = FakeApi(clock, api_routes)
    assert _run(store, "pfm", clock, api, monkeypatch).status == "complete"
    clock.now = at(21, 55, 5)
    decision = _run(store, "decision", clock, api, monkeypatch)
    clock.now = at(22, 5)
    recheck = _run(store, "recheck", clock, api, monkeypatch)
    return decision, recheck, api, clock


# --------------------------------------------------------------------------- time


@pytest.mark.parametrize("target, decision_utc", [
    (date(2026, 9, 23), datetime(2026, 9, 22, 22, 0, tzinfo=UTC)),   # EDT
    (date(2026, 12, 15), datetime(2026, 12, 14, 23, 0, tzinfo=UTC)),  # EST
    (date(2026, 3, 8), datetime(2026, 3, 7, 23, 0, tzinfo=UTC)),     # D-1 is the last EST day
    (date(2026, 3, 9), datetime(2026, 3, 8, 22, 0, tzinfo=UTC)),     # spring-forward day
    (date(2026, 11, 1), datetime(2026, 10, 31, 22, 0, tzinfo=UTC)),  # D-1 is the last EDT day
    (date(2026, 11, 2), datetime(2026, 11, 1, 23, 0, tzinfo=UTC)),   # fall-back day
])
def test_decision_time_and_target_are_dst_correct(target, decision_utc):
    assert forward.windows(target)["decision"] == decision_utc
    # Every instant in the decision window maps back to the same target date.
    for minutes in (-5, -1, 0, 15):
        assert forward.target_for(decision_utc + timedelta(minutes=minutes)) == target


def test_eastern_offset_matches_zoneinfo_when_available():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        ny = zoneinfo.ZoneInfo("America/New_York")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("no tz database on this machine")
    t = datetime(2026, 1, 1, tzinfo=UTC)
    while t < datetime(2027, 1, 1, tzinfo=UTC):
        assert forward.eastern_offset(t) == t.astimezone(ny).utcoffset(), t
        t += timedelta(minutes=30)


def test_event_ticker_and_date_wording():
    assert forward.event_ticker_for(D) == "KXHIGHNY-26SEP23"
    assert forward.event_ticker_for(date(2026, 10, 5)) == "KXHIGHNY-26OCT05"
    assert "Sep 23, 2026" in forward.date_labels(D)
    labels = forward.date_labels(date(2026, 7, 9))
    assert "July 09, 2026" in labels and "Jul 9, 2026" in labels  # both regimes' wording


# --------------------------------------------------------------------------- happy path


def test_full_day_is_valid_and_linked(store, monkeypatch):
    decision, recheck, api, clock = _full_day(store, monkeypatch)
    assert decision.status == "complete", decision.reasons
    assert recheck.status == "complete", recheck.reasons
    assert sorted(decision.links["books"]) == BRACKETS
    assert api.count("/orderbook") == 2 * len(BRACKETS)
    status = forward.day_status(store, D)
    assert status["status"] == "VALID", status["reasons"]
    assert status["forecast"]["forecast_max_f"] == 67
    assert status["forecast"]["wmo_header"] == "FOUS51 KOKX 221853"
    summary = forward.summary(store, now_utc=at(22, 30))
    assert summary["last_closed_target_date"] == D.isoformat()
    assert summary["valid_days"] == 1 and summary["last_closed_status"] == "VALID"


def test_recheck_waits_for_each_brackets_window(store, monkeypatch):
    decision, recheck, *_ = _full_day(store, monkeypatch)
    for bracket, info in recheck.links["books"].items():
        first = datetime.fromisoformat(decision.links["books"][bracket]["fetched_at_utc"])
        again = datetime.fromisoformat(info["fetched_at_utc"])
        assert timedelta(minutes=10) <= again - first <= timedelta(minutes=15)


# --------------------------------------------------------------------------- timing gates


@pytest.mark.parametrize("when", [at(23, 0), at(21, 52), at(21, 59, 45), at(12, 0)])
def test_decision_outside_window_is_rejected_before_any_network(store, monkeypatch, when):
    clock = Clock(when)
    api = FakeApi(clock)
    outcome = _run(store, "decision", clock, api, monkeypatch)
    assert outcome.status == "rejected_out_of_window"
    assert api.calls == []  # no event, market or order-book request at all
    assert outcome.exit_code == 1
    row = store.forward_captures(phase="decision")[-1]
    assert row["status"] == "rejected_out_of_window" and json.loads(row["links_json"]) == {}


def test_slightly_early_timer_waits_for_the_window(store, monkeypatch):
    clock = Clock(at(21, 54, 0))
    api = FakeApi(clock)
    outcome = _run(store, "decision", clock, api, monkeypatch)
    assert clock.slept and clock.slept[0] == 60.0
    assert outcome.status == "complete"


def test_recheck_without_decision_capture_is_rejected_without_network(store, monkeypatch):
    clock = Clock(at(22, 5))
    api = FakeApi(clock)
    outcome = _run(store, "recheck", clock, api, monkeypatch)
    assert outcome.status == "rejected_no_decision_capture" and api.calls == []


def test_late_recheck_is_rejected_without_network(store, monkeypatch):
    clock = Clock(at(21, 55, 5))
    api = FakeApi(clock)
    assert _run(store, "decision", clock, api, monkeypatch).status == "complete"
    clock.now = at(22, 20)
    api.calls.clear()
    outcome = _run(store, "recheck", clock, api, monkeypatch)
    assert outcome.status == "rejected_out_of_window" and api.calls == []
    assert forward.day_status(store, D)["status"] == "INVALID"


def test_pfm_outside_its_window_is_rejected(store, monkeypatch):
    clock = Clock(at(20, 0))
    api = FakeApi(clock)
    outcome = _run(store, "pfm", clock, api, monkeypatch)
    assert outcome.status == "rejected_out_of_window" and api.calls == []


# --------------------------------------------------------------------------- invalid days


def test_missing_bracket_book_makes_the_day_invalid(store, monkeypatch):
    routes = default_routes()
    bad = BRACKETS[2]
    routes = {f"/markets/{bad}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3), **routes}
    decision, recheck, *_ = _full_day(store, monkeypatch, routes)
    assert decision.status == "partial"
    assert any(bad in r for r in decision.reasons)
    assert recheck.status == "rejected_no_decision_capture"  # no complete decision capture
    status = forward.day_status(store, D)
    assert status["status"] == "INVALID"


def test_missing_second_capture_makes_the_day_invalid(store, monkeypatch):
    clock = Clock(at(21, 45))
    api = FakeApi(clock)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    assert _run(store, "decision", clock, api, monkeypatch).status == "complete"
    status = forward.day_status(store, D)
    assert status["status"] == "INVALID" and "no complete recheck capture" in status["reasons"]


def test_one_late_recheck_bracket_invalidates_the_whole_day(store, monkeypatch):
    clock = Clock(at(21, 45))
    api = FakeApi(clock)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)
    # The recheck API stalls for 6 minutes on its first request, so that bracket misses.
    slow = {"n": 0}

    def stall(url):
        slow["n"] += 1
        if slow["n"] == 1:
            clock.now += timedelta(minutes=6)
        return BOOK

    api.routes = {"/orderbook": stall}
    clock.now = at(22, 5)
    recheck = _run(store, "recheck", clock, api, monkeypatch)
    assert recheck.status == "partial"
    assert forward.day_status(store, D)["status"] == "INVALID"


def test_wrong_event_fetches_no_books(store, monkeypatch):
    wrong = json.loads(json.dumps(EVENT))
    wrong["event"]["event_ticker"] = "KXHIGHNY-26SEP24"
    routes = default_routes()
    routes["/events/KXHIGHNY-26SEP23"] = wrong
    clock = Clock(at(21, 55, 5))
    api = FakeApi(clock, routes)
    outcome = _run(store, "decision", clock, api, monkeypatch)
    assert outcome.status == "partial" and api.count("/orderbook") == 0
    assert any("wrong event" in r for r in outcome.reasons)


def test_wording_mismatch_still_captures_books_but_day_is_invalid(store, monkeypatch):
    odd = json.loads(json.dumps(MARKETS))
    odd["markets"][0]["rules_primary"] = "Different wording with no date"
    decision, recheck, api, _ = _full_day(store, monkeypatch, {"/markets?event_ticker": odd, **default_routes()})
    assert decision.status == "partial" and api.count("/orderbook") == len(BRACKETS)
    assert forward.day_status(store, D)["status"] == "INVALID"


def test_stale_forecast_makes_the_day_invalid(store, monkeypatch):
    # For D = 2026-09-24 the cutoff is 2026-09-23 21:30Z; the only product (issued
    # 2026-09-22 18:53Z) is 26.6 h old there.
    clock = Clock(at(21, 45, day=23))
    api = FakeApi(clock, {**default_routes(), "/events/": EVENT})
    outcome = _run(store, "pfm", clock, api, monkeypatch)
    assert outcome.status == "failed"
    assert any("PFM_STALE_AT_CUTOFF" in r for r in outcome.reasons)


def test_forecast_source_down_makes_the_day_invalid(store, monkeypatch):
    routes = {"/products/types/PFM": HttpFetchError("HTTP 503", status=503, attempts=3), **default_routes()}
    clock = Clock(at(21, 45))
    api = FakeApi(clock, routes)
    outcome = _run(store, "pfm", clock, api, monkeypatch)
    assert outcome.status == "failed"
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)
    clock.now = at(22, 5)
    _run(store, "recheck", clock, api, monkeypatch)
    status = forward.day_status(store, D)
    assert status["status"] == "INVALID" and any("forecast" in r for r in status["reasons"])


def test_smoke_rows_are_never_evidence(store, monkeypatch):
    clock = Clock(at(21, 45))
    api = FakeApi(clock)
    for phase, when in (("pfm", at(21, 45)), ("decision", at(21, 55, 5)), ("recheck", at(22, 5))):
        clock.now = when
        _run(store, phase, clock, api, monkeypatch, mode="smoke")
    assert forward.day_status(store, D, mode="smoke")["status"] == "VALID"
    live = forward.day_status(store, D)
    assert live["status"] == "INVALID" and "no complete decision capture" in live["reasons"]


# --------------------------------------------------------------------------- reruns


def test_duplicate_invocation_is_skipped_without_network(store, monkeypatch):
    clock = Clock(at(21, 55, 5))
    api = FakeApi(clock)
    assert _run(store, "decision", clock, api, monkeypatch).status == "complete"
    api.calls.clear()
    clock.now = at(21, 56)
    again = _run(store, "decision", clock, api, monkeypatch)
    assert again.status == "skipped_duplicate" and again.exit_code == 0 and api.calls == []


def test_interrupted_run_then_restart_inside_the_window(store, monkeypatch):
    routes = default_routes()
    boom = {"n": 0}

    def interrupt(url):
        boom["n"] += 1
        if boom["n"] == 3:
            raise KeyboardInterrupt  # killed mid-capture: nothing is recorded as complete
        return BOOK

    routes["/orderbook"] = interrupt
    clock = Clock(at(21, 55, 5))
    api = FakeApi(clock, routes)
    monkeypatch.setattr(forward, "fetch_json_result", api)
    store.start_run("killed")
    with pytest.raises(KeyboardInterrupt):
        forward.capture_decision(store, run_id="killed", clock=clock, sleep=clock.sleep)
    store.finish_run("killed", status="failed", error="aborted")
    assert store.forward_captures(phase="decision") == []
    # The restart (systemd or manual) captures everything again inside the window.
    clock.now = at(21, 56)
    restart = _run(store, "decision", clock, FakeApi(clock), monkeypatch)
    assert restart.status == "complete"
    clock.now = at(21, 45)
    _run(store, "pfm", clock, FakeApi(clock), monkeypatch)
    clock.now = at(22, 6)
    assert _run(store, "recheck", clock, FakeApi(clock), monkeypatch).status == "complete"
    assert forward.day_status(store, D)["status"] == "VALID"


# --------------------------------------------------------------------------- bounded retries


def test_rate_limit_retries_stop_at_the_deadline(monkeypatch):
    from conftest import ScriptedOpener, http_error

    import edge_lab.http as http_module

    opener = ScriptedOpener(*[http_error(429)] * 10)
    monkeypatch.setattr(http_module, "_default_opener", opener)
    monkeypatch.setattr(forward, "fetch_json_result", http_module.fetch_json_result)
    # 5 s left: the first backoff (1-1.5 s) fits, the second (2-3 s) would not.
    clock = Clock(at(21, 59, 55))
    budget = forward._Budget(at(22, 0), clock, clock.sleep)
    with pytest.raises(forward.DeadlineExceeded):
        budget.get("https://example.test/x", pacer=None)
    assert len(opener.calls) <= 3  # never retries past the window
    assert clock.now < at(22, 0)


def test_no_request_starts_with_less_than_the_minimum_budget(monkeypatch):
    clock = Clock(at(21, 59, 58))
    api = FakeApi(clock)
    monkeypatch.setattr(forward, "fetch_json_result", api)
    with pytest.raises(forward.DeadlineExceeded):
        forward._Budget(at(22, 0), clock, clock.sleep).get("https://example.test/x", pacer=None)
    assert api.calls == []


def test_timeout_is_bounded_by_remaining_time(monkeypatch):
    seen = {}

    def spy(url, **kwargs):
        seen.update(kwargs)
        return {}, FetchResult(url, url, 200, None, b"{}", at(21, 59).isoformat(), 1, 1)

    monkeypatch.setattr(forward, "fetch_json_result", spy)
    clock = Clock(at(21, 59, 54))
    forward._Budget(at(22, 0), clock, clock.sleep).get("https://example.test/x", pacer=None)
    assert seen["timeout"] <= 5.0 and seen["retries"] == 2


# --------------------------------------------------------------------------- lock, CLI, DB


def test_lock_excludes_a_second_capture(tmp_path):
    lock = tmp_path / "db.forward.lock"
    with forward.exclusive_lock(lock):
        with pytest.raises(forward.LockBusy):
            with forward.exclusive_lock(lock, timeout_s=0.2, sleep=lambda s: None):
                pass
    with forward.exclusive_lock(lock, timeout_s=0.2):
        pass  # released


def test_cli_capture_outside_window_records_rejection_and_no_source_health(tmp_path, capsys):
    # The real clock is almost never inside 17:55-17:59:30 ET, and the autouse no_network
    # fixture fails the test if any request is attempted.
    now = datetime.now(UTC)
    g = forward.gate("decision", SnapshotStore(tmp_path / "probe.sqlite3"), now)
    if g.status is None:
        pytest.skip("running inside the live decision window")
    db = tmp_path / "e.sqlite3"
    code = cli.main(["forward", "capture", "--phase", "decision", "--db", str(db)])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["status"] == "rejected_out_of_window"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_health").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM collection_runs").fetchone()[0] == "failed"
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_cli_pfm_requires_user_agent(tmp_path, monkeypatch):
    monkeypatch.delenv("NWS_USER_AGENT", raising=False)
    assert cli.main(["forward", "capture", "--phase", "pfm", "--db", str(tmp_path / "e.sqlite3"),
                     "--nws-user-agent", ""]) == 2


def test_cli_status_writes_a_non_sensitive_status_file(tmp_path, monkeypatch, capsys):
    store = SnapshotStore(tmp_path / "e.sqlite3")
    _full_day(store, monkeypatch)
    status_file = tmp_path / "status" / "latest.json"
    code = cli.main(["forward", "status", "--db", str(store.path), "--date", D.isoformat(),
                     "--status-file", str(status_file)])
    capsys.readouterr()
    assert code == 0
    written = json.loads(status_file.read_text(encoding="utf-8"))
    assert written["status"] == "VALID"
    assert "payload_json" not in status_file.read_text(encoding="utf-8")


def test_health_forward_profile_is_schedule_aware(tmp_path, capsys):
    db = tmp_path / "e.sqlite3"
    SnapshotStore(db)
    # Nothing captured yet: the last closed day is not VALID, so forward health fails.
    assert cli.main(["health", "--db", str(db), "--profile", "forward"]) == 1
    assert json.loads(capsys.readouterr().out)["last_closed_status"] == "INVALID"


def test_database_failure_is_a_nonzero_exit(tmp_path):
    bad = tmp_path / "is_a_directory"
    bad.mkdir()
    with pytest.raises(sqlite3.Error):
        cli.main(["forward", "capture", "--phase", "decision", "--db", str(bad)])


def test_forward_captures_are_immutable(store, monkeypatch):
    _full_day(store, monkeypatch)
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE forward_captures SET status = 'complete'")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM forward_captures")
