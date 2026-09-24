"""The provider-neutral notification contract (issue #33, ADR 0020) and redaction."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from edge_lab import daily, notifications as n
from edge_lab.redaction import REDACTED, contains_secret, redact_text, redact_url

UTC = timezone.utc
NOW = datetime(2026, 9, 25, 22, 45, tzinfo=UTC)


def ev(kind=n.EventType.SOURCE_FAILURE, severity=n.Severity.WARNING, key="k", **kw):
    return n.make_event(kind, severity, created_at=kw.pop("created_at", NOW), summary=kw.pop("summary", "x"),
                        dedupe_key=key, **kw)


class Boom:
    sink_id = "boom"

    def __init__(self, fail_times=99):
        self.calls, self.fail_times = 0, fail_times

    def deliver(self, event):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("provider down")
        return n.DeliveryStatus.DELIVERED


def test_every_directive_event_type_exists():
    assert {e.value for e in n.EventType} == {
        "SOURCE_FAILURE", "CAPTURE_INVALID", "OPPORTUNITY_QUALIFIED", "PRICE_TARGET_REACHED", "APPROVAL_REQUIRED",
        "QUOTE_EXPIRING", "RISK_VETO", "KILL_SWITCH", "POSITION_FILLED", "POSITION_PARTIAL", "POSITION_EXPIRED",
        "SETTLED", "SEVEN_DAY_POLICY_EXCEPTION", "TEST"}


def test_event_carries_the_contract_fields_and_a_deterministic_id():
    e = ev(ttl=timedelta(minutes=2), venue_id="kalshi", market_id="kalshi:X", event_ref="weather:x",
           values={"price": "0.48"}, action_mode=n.ActionMode.OPEN_MARKET_EDGE, deep_link="http://127.0.0.1:8765/")
    d = e.to_dict()
    for field in ("event_id", "severity", "created_at_utc", "expires_at_utc", "venue_id", "market_id", "event_ref",
                  "summary", "values", "action_mode", "deep_link", "dedupe_key"):
        assert field in d
    assert e.event_id == ev(ttl=timedelta(minutes=2)).event_id


def test_outbox_delivers_and_sms_is_disabled(tmp_path):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    results = n.dispatch([ev()], [outbox, n.DisabledSmsSink()], now=NOW)
    assert [r["status"] for r in results] == ["DELIVERED", "DISABLED_NO_PROVIDER"]
    assert json.loads((tmp_path / "out.jsonl").read_text())["dedupe_key"] == "k"


def test_duplicates_are_not_resent(tmp_path):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    n.dispatch([ev()], [outbox], now=NOW)
    again = n.dispatch([ev(created_at=NOW + timedelta(hours=5))], [outbox], now=NOW + timedelta(hours=5),
                       history=outbox.history())
    assert [r["status"] for r in again] == ["DEDUPED"]
    assert len(outbox.history()) == 1


def test_expired_events_are_never_delivered():
    old = ev(created_at=NOW - timedelta(minutes=10), ttl=timedelta(minutes=2))
    assert n.dispatch([old], [n.DisabledSmsSink()], now=NOW)[0]["status"] == "EXPIRED"


def test_a_flood_of_info_never_suppresses_a_critical_alert(tmp_path):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    flood = [ev(n.EventType.OPPORTUNITY_QUALIFIED, n.Severity.INFO, key=f"i{i}") for i in range(1000)]
    critical = ev(n.EventType.KILL_SWITCH, n.Severity.CRITICAL, key="kill")
    results = n.dispatch([*flood, critical], [outbox], now=NOW)
    statuses = {r["event_id"]: r["status"] for r in results}
    assert statuses[critical.event_id] == "DELIVERED"
    delivered_info = sum(1 for r in results if r["severity"] == "INFO" and r["status"] == "DELIVERED")
    assert delivered_info == n.Limits().per_window[n.Severity.INFO]
    assert sum(1 for r in results if r["status"] == "RATE_LIMITED") == 1000 - delivered_info


def test_retries_are_bounded_and_a_failing_sink_never_raises():
    boom = Boom()
    results = n.dispatch([ev()], [boom], now=NOW)
    assert results[0]["status"] == "FAILED" and results[0]["attempts"] == 3 and boom.calls == 3
    flaky = Boom(fail_times=1)
    assert n.dispatch([ev()], [flaky], now=NOW)[0]["status"] == "DELIVERED" and flaky.calls == 2


@pytest.mark.parametrize("field,value", [
    ("summary", "retry with api_key=abc123def456"), ("values", {"auth": "Bearer abcdefghijklmnop"}),
    ("summary", "session cookie: s=123"), ("deep_link", "https://kalshi.com/x?token=zzz"),
])
def test_secrets_are_refused(field, value):
    kw = {field: value}
    result = n.dispatch([ev(**kw)], [n.DisabledSmsSink()], now=NOW)[0]
    assert result["status"] == "REFUSED_SECRET"


@pytest.mark.parametrize("link", ["http://kalshi.com/x", "https://evil.example/x", "javascript:alert(1)",
                                  "https://kalshi.com.evil.example/", "https://evil.com?.kalshi.com",
                                  "https://evil.com#.kalshi.com", "https://evil.com\\.kalshi.com",
                                  "https://user@kalshi.com/", "HTTPS://evil.com/", "https://kalshi.com.xn--evil/",
                                  "https://kаlshi.com/"])
def test_unsafe_links_are_refused(link):
    assert n.dispatch([ev(deep_link=link)], [n.DisabledSmsSink()], now=NOW)[0]["status"] == "REFUSED_LINK"


def test_safe_links_pass():
    for link in ("https://kalshi.com/markets/kxhighny", "http://127.0.0.1:8765/risk", "https://docs.polymarket.us/x"):
        assert n.dispatch([ev(deep_link=link, key=link)], [n.DisabledSmsSink()], now=NOW)[0]["status"] != "REFUSED_LINK"


def test_outbox_rotates_once_and_stays_bounded(tmp_path):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl", max_bytes=2000)
    for i in range(100):
        outbox.deliver(ev(key=f"r{i}"))
    assert (tmp_path / "out.jsonl.1").exists()
    assert (tmp_path / "out.jsonl").stat().st_size < 3000 and (tmp_path / "out.jsonl.1").stat().st_size < 3000
    assert not (tmp_path / "out.jsonl.2").exists()


def test_events_from_a_receipt():
    receipt = {"state": "INVALID_CAPTURE", "generated_at_utc": NOW.isoformat(), "problems": [],
               "days": [{"target_date": "2026-09-25", "capture_status": "INVALID", "result": "INVALID_CAPTURE",
                         "accounts": {"op": {"risk_vetoes": 2}}}],
               "settlement": {"settled": 1, "conflicts": []}}
    exceptions = [{"fill_id": "f1", "market_id": "kalshi:X", "tradable_cash_release_eta_utc": "2026-09-25T00:00Z"}]
    kinds = {e.type.value for e in n.events_from_receipt(receipt, now=NOW, exceptions=exceptions)}
    assert kinds == {"CAPTURE_INVALID", "RISK_VETO", "SETTLED", "SEVEN_DAY_POLICY_EXCEPTION"}


# ---------------------------------------------------------------- the daily run

def test_notification_failure_never_changes_the_receipt_or_the_ledger(tmp_path, monkeypatch):
    import sqlite3
    from test_daily import _run
    from test_forward import _full_day
    from edge_lab import exp001_stageb as stageb
    from edge_lab.storage import SnapshotStore

    model = stageb.load_model()

    def run(root):
        root.mkdir()
        store = SnapshotStore(root / "fwd.sqlite3")
        _full_day(store, monkeypatch)
        receipt, code = _run(store, root, model)
        with sqlite3.connect(root / "ledger.sqlite3") as con:
            entries = con.execute("SELECT account_id, kind, entry_key, payload_sha256 FROM ledger_entries "
                                  "ORDER BY seq").fetchall()
        return receipt, code, entries

    ok, ok_code, ok_entries = run(tmp_path / "a")

    def broken(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(n, "dispatch", broken)
    bad, bad_code, bad_entries = run(tmp_path / "b")
    assert ok["notifications"]["status"] == "ok" and bad["notifications"]["status"] == "failed"
    assert (ok["state"], ok_code) == (bad["state"], bad_code)
    assert ok["days"] == bad["days"] and ok["accounts"] == bad["accounts"]
    assert ok_entries == bad_entries


# ---------------------------------------------------------------- redaction

def test_redact_url_hides_query_keys_and_userinfo():
    url = redact_url("https://user:pw@api.the-odds-api.com/v4/sports/x/odds?apiKey=SECRET1&regions=us")
    assert "SECRET1" not in url and "pw" not in url and f"apiKey={REDACTED}" in url and "regions=us" in url


def test_redact_text_and_detection():
    text = "GET https://x/y?apiKey=abc&a=1 failed; api_key: zzz; Bearer abcdefghijkl"
    out = redact_text(text, ("abc",))
    assert "zzz" not in out and "abcdefghijkl" not in out and "a=1" in out
    assert contains_secret("token=abc") and not contains_secret("plain words about tokens")


def test_every_persisted_field_is_scanned_for_secrets():
    for kw in ({"market_id": "api_key=abc123"}, {"event_ref": "token=zzz"}, {"venue_id": "password: x"}):
        assert n.dispatch([ev(**kw)], [n.DisabledSmsSink()], now=NOW)[0]["status"] == "REFUSED_SECRET"
    assert n.dispatch([ev(key="session_id=abc")], [n.DisabledSmsSink()], now=NOW)[0]["status"] == "REFUSED_SECRET"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX umask/mode bits; Windows has no group/other permission bits (st_mode is 0o666)")
def test_outbox_is_world_readable_under_a_strict_umask(tmp_path):
    import os
    import stat
    old = os.umask(0o077)
    try:
        n.JsonlOutbox(tmp_path / "out.jsonl").deliver(ev())
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "out.jsonl").stat().st_mode) == 0o644


def test_outbox_stays_under_the_dashboard_read_limit(tmp_path):
    from edge_lab.dashboard.data import STATUS_FILE_MAX_BYTES
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    assert outbox.max_bytes < STATUS_FILE_MAX_BYTES


# ---------------------------------------------------------------- origin (ADR 0020 amendment, 2026-09-24)

class External:
    """An external sink that records what it was given. It declares nothing, so it counts as external."""

    sink_id = "push"

    def __init__(self):
        self.got = []

    def deliver(self, event):
        self.got.append(event)
        return n.DeliveryStatus.SUBMITTED


def test_the_origin_vocabulary_is_exactly_the_directive_list():
    assert {o.value for o in n.Origin} == {"PRODUCTION", "TEST", "DEPLOYMENT_VERIFICATION", "MANUAL_DIAGNOSTIC",
                                           "REPLAY", "DEMO"}
    assert n.NEVER_PUSHED_ORIGINS == {n.Origin.DEPLOYMENT_VERIFICATION, n.Origin.REPLAY, n.Origin.DEMO}


@pytest.mark.parametrize("origin", list(n.Origin))
def test_the_origin_survives_the_outbox_round_trip(tmp_path, origin):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    e = ev(origin=origin, ttl=timedelta(hours=1), values={"k": "v"})
    outbox.deliver(e)
    (line,) = outbox.history()
    assert line["origin"] == origin.value
    assert n.event_from_dict(line) == e


def test_an_old_outbox_line_without_origin_reads_as_production():
    old = ev().to_dict()
    del old["origin"]
    assert n.event_from_dict(old).origin is n.Origin.PRODUCTION
    assert n.origin_of(old) is n.Origin.PRODUCTION


@pytest.mark.parametrize("bad", ["NOT_AN_ORIGIN", "production", 7, ["DEMO"]])
def test_an_unknown_origin_is_not_guessed(bad):
    assert n.event_from_dict({**ev().to_dict(), "origin": bad}) is None


def test_the_event_id_does_not_depend_on_the_origin():
    """Ids of events relayed before the field existed must not change, or the relay would re-send them."""
    assert len({ev(origin=o).event_id for o in n.Origin}) == 1


def test_only_production_reaches_an_external_sink_by_default(tmp_path):
    outbox, push = n.JsonlOutbox(tmp_path / "out.jsonl"), External()
    events = [ev(origin=o, key=o.value) for o in n.Origin]
    results = n.dispatch(events, [outbox, push], now=NOW)
    assert [e.origin for e in push.got] == [n.Origin.PRODUCTION]
    held = {r["origin"] for r in results if r["status"] == "HELD_BY_ORIGIN"}
    assert held == {o.value for o in n.Origin} - {"PRODUCTION"}
    assert all(r["sink"] == "push" for r in results if r["status"] == "HELD_BY_ORIGIN")
    # Every origin is still stored locally, for the dashboard.
    assert {h["origin"] for h in outbox.history()} == {o.value for o in n.Origin}


def test_test_and_manual_diagnostic_are_pushed_only_when_requested():
    push = External()
    n.dispatch([ev(origin=n.Origin.TEST, key="t"), ev(origin=n.Origin.MANUAL_DIAGNOSTIC, key="m")], [push], now=NOW)
    assert push.got == []
    n.dispatch([ev(origin=n.Origin.TEST, key="t"), ev(origin=n.Origin.MANUAL_DIAGNOSTIC, key="m")], [push], now=NOW,
               push_origins=[n.Origin.MANUAL_DIAGNOSTIC])
    assert [e.origin for e in push.got] == [n.Origin.MANUAL_DIAGNOSTIC]


@pytest.mark.parametrize("origin", sorted(n.NEVER_PUSHED_ORIGINS))
def test_verification_replay_and_demo_can_never_be_requested(origin):
    push = External()
    with pytest.raises(ValueError):
        n.dispatch([ev(origin=origin)], [push], now=NOW, push_origins=[origin])
    assert push.got == []


def test_the_disabled_sms_sink_counts_as_external():
    (r,) = n.dispatch([ev(origin=n.Origin.DEMO)], [n.DisabledSmsSink()], now=NOW)
    assert r["status"] == "HELD_BY_ORIGIN"


def test_a_verification_event_never_dedupes_or_rate_limits_a_production_one(tmp_path):
    outbox = n.JsonlOutbox(tmp_path / "out.jsonl")
    noise = [ev(key=f"v{i}", origin=n.Origin.DEPLOYMENT_VERIFICATION) for i in range(50)]
    n.dispatch([*noise, ev(key="same", origin=n.Origin.DEPLOYMENT_VERIFICATION)], [outbox], now=NOW)
    push = External()
    results = n.dispatch([ev(key="same"), ev(key="other")], [outbox, push], now=NOW, history=outbox.history())
    assert [r["status"] for r in results if r["sink"] == "push"] == ["SUBMITTED", "SUBMITTED"]


def test_a_held_event_uses_no_rate_limit_budget():
    push = External()
    demo = [ev(n.EventType.OPPORTUNITY_QUALIFIED, n.Severity.INFO, key=f"d{i}", origin=n.Origin.DEMO)
            for i in range(100)]
    real = [ev(n.EventType.OPPORTUNITY_QUALIFIED, n.Severity.INFO, key=f"p{i}") for i in range(5)]
    results = n.dispatch([*demo, *real], [push], now=NOW)
    assert len(push.got) == 5 and sum(r["status"] == "HELD_BY_ORIGIN" for r in results) == 100


def test_events_from_a_receipt_carry_the_callers_origin():
    receipt = {"state": "FAILED", "generated_at_utc": NOW.isoformat(), "problems": ["x"], "days": []}
    (prod,) = n.events_from_receipt(receipt, now=NOW)
    (replay,) = n.events_from_receipt(receipt, now=NOW, origin=n.Origin.REPLAY)
    assert prod.origin is n.Origin.PRODUCTION and replay.origin is n.Origin.REPLAY
    assert prod.event_id == replay.event_id


def test_the_daily_run_writes_production_events(tmp_path):
    receipt = {"state": "FAILED", "generated_at_utc": NOW.isoformat(), "problems": ["x"], "days": []}
    out = daily._notify(tmp_path, receipt)
    assert out["status"] == "ok" and out["delivered"] == 1
    (line,) = n.JsonlOutbox(tmp_path / daily.NOTIFICATIONS_NAME).history()
    assert line["origin"] == "PRODUCTION"
