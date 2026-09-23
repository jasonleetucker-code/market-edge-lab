"""The optional ntfy push sink (ADR 0022). Fixtures and an injected opener only: no network."""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

import pytest

from edge_lab import notifications as n
from edge_lab import notify_ntfy as ntfy

UTC = timezone.utc
NOW = datetime(2026, 9, 25, 22, 45, tzinfo=UTC)
TOPIC = "mel-Secret_Topic-7f3a9c"
URL = f"https://ntfy.example.org/{TOPIC}"
TOKEN = "tk_abcdefghijklmnopqrstuvwxyz0123"


@pytest.fixture(autouse=True)
def no_ntfy_network(monkeypatch):
    """The sink's real opener is never reached from a unit test."""

    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real ntfy send: {request.full_url}")

    monkeypatch.setattr(ntfy, "_default_opener", refuse)


class Response:
    def __init__(self, status=200, body=b'{"id":"abc","event":"message"}'):
        self.status, self._body = status, body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Replays scripted steps: a Response, an int status, or an exception to raise."""

    def __init__(self, *steps):
        self.steps = list(steps) or [Response()]
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return Response(step) if isinstance(step, int) else step


def http_error(code):
    return HTTPError(URL, code, "err", {}, None)


def ev(kind=n.EventType.SOURCE_FAILURE, severity=n.Severity.WARNING, key="daily:FAILED:2026-09-25", **kw):
    return n.make_event(kind, severity, created_at=kw.pop("created_at", NOW), summary=kw.pop("summary", "run failed"),
                        dedupe_key=key, **kw)


def sink(opener=None, **kw):
    sleeps = []
    s = ntfy.NtfySink(URL, opener=opener or Opener(), sleep=sleeps.append, clock=kw.pop("clock", lambda: NOW), **kw)
    s.sleeps = sleeps
    return s


def headers(request):
    return {k.lower(): v for k, v in request.header_items()}


# ------------------------------------------------------------------ disabled by default

def test_disabled_by_default_when_unconfigured():
    assert ntfy.sink_from_env({}) is None
    assert ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: "   "}) is None
    assert ntfy.sink_from_env({ntfy.ENV_TOKEN: TOKEN}) is None  # a token alone enables nothing


def test_factory_builds_the_sink_only_from_an_explicit_topic_url():
    s = ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: URL, ntfy.ENV_TOKEN: TOKEN}, opener=Opener())
    assert isinstance(s, ntfy.NtfySink) and s.sink_id == "ntfy"
    assert TOPIC not in repr(s) and TOKEN not in repr(s) and TOPIC not in s.target.label


def test_factory_reads_the_process_environment_when_no_mapping_is_given(monkeypatch):
    monkeypatch.delenv(ntfy.ENV_TOPIC_URL, raising=False)
    assert ntfy.sink_from_env() is None
    monkeypatch.setenv(ntfy.ENV_TOPIC_URL, URL)
    assert ntfy.sink_from_env(opener=Opener()) is not None


@pytest.mark.parametrize("bad", ["http://ntfy.example.org/t", "https://ntfy.example.org/a/b", "https://kalshi.com/t",
                                 f"https://u:p@ntfy.example.org/{TOPIC}", f"https://ntfy.example.org/{TOPIC}?auth=x"])
def test_invalid_configuration_is_refused_without_echoing_the_url(bad):
    with pytest.raises(ntfy.NtfyConfigError) as err:
        ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: bad})
    assert TOPIC not in str(err.value) and "auth=x" not in str(err.value) and "u:p" not in str(err.value)


@pytest.mark.parametrize("token", ["has space", "a\r\nX-Evil: 1", "x" * 129, "tok/en"])
def test_a_malformed_token_is_refused_without_echoing_it(token):
    with pytest.raises(ntfy.NtfyConfigError) as err:
        ntfy.NtfySink(URL, token=token, opener=Opener())
    assert token not in str(err.value)


def test_nothing_constructs_the_sink_outside_its_module(repo_root):
    """Activation needs owner approval: no run path, timer or deploy file wires it in."""
    wiring = re.compile(r"import\s+notify_ntfy|notify_ntfy\s+import|from\s+\S*notify_ntfy|NtfySink\(|sink_from_env\("
                        r"|EDGE_LAB_NTFY_")
    users = []
    for base in ("src", "deploy", "scripts"):
        for path in (repo_root / base).rglob("*"):
            if path.is_file() and path.name != "notify_ntfy.py" and "__pycache__" not in path.parts:
                if wiring.search(path.read_text(encoding="utf-8", errors="ignore")):
                    users.append(path.relative_to(repo_root).as_posix())
    assert users == []


# ------------------------------------------------------------------ mapping and payload

def test_headers_map_title_priority_tags_and_sequence_id():
    opener = Opener()
    assert sink(opener).deliver(ev()) is n.DeliveryStatus.SUBMITTED
    (request,) = opener.requests
    h = headers(request)
    assert request.get_method() == "POST" and request.full_url == URL
    assert h["x-title"] == "Market Edge WARNING: SOURCE_FAILURE"
    assert h["x-priority"] == "4"
    assert h["x-tags"] == "warning,source_failure"
    assert h["x-sequence-id"] == "daily_FAILED_2026-09-25"
    assert "authorization" not in h and "x-click" not in h and "x-actions" not in h
    assert request.data == b"run failed"


@pytest.mark.parametrize("severity,priority", [(n.Severity.INFO, "2"), (n.Severity.WARNING, "4"),
                                               (n.Severity.CRITICAL, "5")])
def test_priority_follows_severity(severity, priority):
    opener = Opener()
    sink(opener).deliver(ev(severity=severity))
    assert headers(opener.requests[0])["x-priority"] == priority


def test_optional_bearer_token_is_sent_only_as_a_header():
    opener = Opener()
    sink(opener, token=TOKEN).deliver(ev())
    request = opener.requests[0]
    assert headers(request)["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.full_url and TOKEN.encode() not in request.data


def test_payload_is_type_severity_and_summary_only():
    e = ev(n.EventType.SEVEN_DAY_POLICY_EXCEPTION, n.Severity.CRITICAL, key="starter-exception:fill-1",
           summary="Capital past its expected release", ttl=timedelta(hours=1),
           values={"fill_id": "fill-1", "position": "12 contracts", "pnl": "-3.10", "balance": "250.00",
                   "account": "acct-778899"},
           venue_id="kalshi", market_id="kalshi:KXHIGHNY-X", event_ref="weather:nyc",
           action_mode=n.ActionMode.OPEN_MARKET_EDGE, deep_link="https://kalshi.com/markets/kxhighny")
    opener = Opener()
    assert sink(opener).deliver(e) is n.DeliveryStatus.SUBMITTED
    request = opener.requests[0]
    sent = request.data.decode() + json.dumps(request.header_items())
    assert request.data == b"Capital past its expected release"
    for leaked in ("fill-1", "12 contracts", "3.10", "250.00", "acct-778899", "kalshi", "KXHIGHNY", "weather:nyc",
                   "OPEN_MARKET_EDGE", "https://", e.event_id):
        assert leaked not in sent.replace("starter-exception_fill-1", ""), leaked
    assert set(headers(request)) == {"x-title", "x-priority", "x-tags", "x-sequence-id", "content-type"}


def test_a_long_summary_is_truncated_and_marked():
    opener = Opener()
    sink(opener).deliver(ev(summary="word " * 200))
    body = opener.requests[0].data.decode()
    assert len(body) <= ntfy.MAX_SUMMARY_CHARS and body.endswith("[truncated]")


@pytest.mark.parametrize("field,value", [("summary", "retry with api_key=abc123def456"),
                                         ("values", {"auth": "Bearer abcdefghijklmnop"})])
def test_an_event_carrying_a_secret_is_refused_and_not_sent(field, value):
    opener = Opener()
    assert sink(opener).deliver(ev(**{field: value})) is n.DeliveryStatus.REFUSED_SECRET
    assert opener.requests == []


# ------------------------------------------------------------------ expiry and dedupe

def test_an_event_expired_at_send_time_is_not_sent():
    opener = Opener()
    old = ev(created_at=NOW - timedelta(minutes=10), ttl=timedelta(minutes=2))
    assert sink(opener).deliver(old) is n.DeliveryStatus.EXPIRED
    assert opener.requests == []


def test_an_event_that_expires_during_retries_stops_being_sent():
    times = iter([NOW, NOW + timedelta(minutes=5)])
    opener = Opener(http_error(503))
    s = sink(opener, clock=lambda: next(times))
    assert s.deliver(ev(ttl=timedelta(minutes=1))) is n.DeliveryStatus.EXPIRED
    assert len(opener.requests) == 1


@pytest.mark.parametrize("key,expected", [
    ("daily:FAILED:2026-09-25", "daily_FAILED_2026-09-25"),
    ("plain-key_1", "plain-key_1"),
    ("veto:research/é 2026", "veto_research___2026"),
])
def test_sequence_id_is_sanitised(key, expected):
    assert ntfy.sequence_id(key) == expected


def test_a_long_dedupe_key_is_hashed_to_a_valid_distinct_sequence_id():
    a, b = "settlement-conflict:" + "x" * 200, "settlement-conflict:" + "x" * 199 + "y"
    sa, sb = ntfy.sequence_id(a), ntfy.sequence_id(b)
    assert ntfy.SEQUENCE_ID.fullmatch(sa) and ntfy.SEQUENCE_ID.fullmatch(sb)
    assert len(sa) == 64 and sa != sb and sa == ntfy.sequence_id(a)


def test_an_empty_dedupe_key_sends_no_sequence_id_and_is_never_retried():
    opener = Opener(http_error(503))
    s = sink(opener)
    assert s.deliver(ev(key="")) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == 1 and "x-sequence-id" not in headers(opener.requests[0])


def test_dispatch_dedupe_prevents_a_second_publish(tmp_path, monkeypatch):
    if not hasattr(n.os, "fchmod"):  # POSIX-only; stubbed so this test also runs on Windows
        monkeypatch.setattr(n.os, "fchmod", lambda fd, mode: None, raising=False)
    outbox, opener = n.JsonlOutbox(tmp_path / "out.jsonl"), Opener()
    s = sink(opener)
    first = n.dispatch([ev()], [outbox, s], now=NOW)
    later = NOW + timedelta(hours=3)
    again = n.dispatch([ev(created_at=later)], [outbox, s], now=later, history=outbox.history())
    assert [r["status"] for r in first] == ["DELIVERED", "SUBMITTED"]
    assert [r["status"] for r in again] == ["DEDUPED"] and len(opener.requests) == 1


def test_dispatch_dedupe_by_history_prevents_a_second_publish():
    opener = Opener()
    history = [ev().to_dict()]
    results = n.dispatch([ev(created_at=NOW + timedelta(hours=1))], [sink(opener)], now=NOW + timedelta(hours=1),
                         history=history)
    assert [r["status"] for r in results] == ["DEDUPED"] and opener.requests == []


# ------------------------------------------------------------------ failures, retries, never raises

def test_retries_are_bounded_with_injected_backoff():
    opener = Opener(http_error(503))
    s = sink(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == ntfy.MAX_ATTEMPTS == s.last_attempts == 3
    assert s.sleeps == [1.0, 2.0] and s.last_http_status == 503


def test_max_attempts_cannot_be_raised_past_the_fixed_bound():
    opener = Opener(http_error(500))
    s = sink(opener, max_attempts=50)
    s.deliver(ev())
    assert len(opener.requests) == ntfy.MAX_ATTEMPTS


def test_a_transient_failure_then_success_is_submitted():
    opener = Opener(http_error(502), Response())
    s = sink(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.SUBMITTED and s.last_attempts == 2 and s.last_error is None


def test_429_is_rate_limited_and_not_retried():
    opener = Opener(http_error(429))
    s = sink(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.RATE_LIMITED
    assert len(opener.requests) == 1 and s.sleeps == [] and s.last_http_status == 429


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413])
def test_other_4xx_fail_without_retry(code):
    opener = Opener(http_error(code))
    s = sink(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED and len(opener.requests) == 1


def test_a_redirect_is_a_failure_not_a_follow():
    opener = Opener(http_error(302))
    assert sink(opener).deliver(ev()) is n.DeliveryStatus.FAILED and len(opener.requests) == 1


def test_the_real_opener_refuses_to_follow_redirects():
    handler = ntfy._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/x") is None


def test_a_non_2xx_success_response_is_not_submitted():
    assert sink(Opener(Response(status=500))).deliver(ev()) is n.DeliveryStatus.FAILED


@pytest.mark.parametrize("exc", [socket.timeout("timed out"), TimeoutError("timed out"),
                                 URLError(f"connect to {URL} refused"), ConnectionResetError("reset")])
def test_timeouts_and_network_errors_fail_after_bounded_retries(exc):
    opener = Opener(exc)
    s = sink(opener, token=TOKEN)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == 3
    assert TOPIC not in s.last_error and TOKEN not in s.last_error and URL not in s.last_error


def test_errors_are_redacted_even_when_the_provider_echoes_secrets():
    opener = Opener(URLError(f"proxy said: {URL} Bearer {TOKEN} token={TOKEN}"))
    s = sink(opener, token=TOKEN)
    s.deliver(ev())
    assert TOPIC not in s.last_error and TOKEN not in s.last_error
    assert "ntfy.example.org" in s.last_error  # the host alone is not the secret


def test_the_sink_never_raises_even_on_an_unexpected_error():
    opener = Opener(RuntimeError(f"bug near {URL} with {TOKEN}"))
    s = sink(opener, token=TOKEN)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert TOPIC not in s.last_error and TOKEN not in s.last_error


def test_dispatch_records_the_redacted_failure_and_continues():
    opener = Opener(http_error(503))
    s = sink(opener, token=TOKEN)
    results = n.dispatch([ev(), ev(key="second")], [s, n.DisabledSmsSink()], now=NOW)
    statuses = [(r["sink"], r["status"]) for r in results]
    assert statuses == [("ntfy", "FAILED"), ("sms-disabled", "DISABLED_NO_PROVIDER")] * 2
    ntfy_records = [r for r in results if r["sink"] == "ntfy"]
    assert all(r["error"] and TOPIC not in r["error"] and TOKEN not in r["error"] for r in ntfy_records)
    assert [r["attempts"] for r in ntfy_records] == [3, 3]  # the sink's own bounded attempts, not dispatch's


def test_a_submitted_push_is_never_reported_as_delivered():
    results = n.dispatch([ev()], [sink()], now=NOW)
    assert [r["status"] for r in results] == ["SUBMITTED"]
    assert n.DeliveryStatus.SUBMITTED is not n.DeliveryStatus.DELIVERED


def test_notification_failure_changes_no_caller_state():
    """The sink holds no reference to risk, ledger or trading state; a failure only sets its own
    diagnostic fields, and the event is unchanged."""
    e = ev()
    before = e.to_dict()
    s = sink(Opener(OSError("down")))
    s.deliver(e)
    assert e.to_dict() == before
    assert set(vars(s)) == {"_secrets", "target", "_token", "_opener", "_sleep", "_clock", "max_attempts",
                            "backoff", "timeout", "last_error", "last_attempts", "last_http_status", "sleeps"}
