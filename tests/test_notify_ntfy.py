"""The optional ntfy push sink (ADR 0022). Fixtures and an injected opener only: no network."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from edge_lab import notifications as n
from edge_lab import notify_ntfy as ntfy

UTC = timezone.utc
NOW = datetime(2026, 9, 25, 22, 45, tzinfo=UTC)
TOPIC = "mel-Secret_Topic-7f3a9c"
URL = f"https://ntfy.sh/{TOPIC}"
TOKEN = "tk_abcdefghijklmnopqrstuvwxyz0123"


@pytest.fixture(autouse=True)
def no_ntfy_network(monkeypatch):
    """The sink's real opener is never reached from a unit test."""

    def refuse(request, timeout):
        raise AssertionError(f"test attempted a real ntfy send: {request.full_url}")

    monkeypatch.setattr(ntfy, "_default_opener", refuse)


class Response:
    def __init__(self, status=200, body=b'{"id":"abc","event":"message"}'):
        if status is not None:
            self.status = status
        self._body = body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Replays scripted steps (a Response, an int status, or an exception); the last step repeats."""

    def __init__(self, *steps):
        self.steps = list(steps) or [Response()]
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return Response(step) if isinstance(step, int) else step


class Clock:
    """A fake monotonic clock that `sleep` advances."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def http_error(code):
    return HTTPError(URL, code, "err", {}, None)


def ev(kind=n.EventType.SOURCE_FAILURE, severity=n.Severity.WARNING, key="daily:FAILED:2026-09-25", **kw):
    return n.make_event(kind, severity, created_at=kw.pop("created_at", NOW), summary=kw.pop("summary", "run failed"),
                        dedupe_key=key, **kw)


def make(opener=None, clock=None, **kw):
    clock = clock or Clock()
    return ntfy.NtfySink(URL, opener=opener or Opener(), sleep=clock.sleep, monotonic=clock,
                         clock=kw.pop("now", lambda: NOW), **kw), clock


def headers(request):
    return {k.lower(): v for k, v in request.header_items()}


def sent_text(request):
    return request.full_url + request.data.decode() + json.dumps(request.header_items())


# ------------------------------------------------------------------ disabled by default

def test_disabled_by_default_when_unconfigured():
    assert ntfy.sink_from_env({}) is None
    assert ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: "   "}) is None
    assert ntfy.sink_from_env({ntfy.ENV_TOKEN: TOKEN}) is None  # a token alone enables nothing


def test_factory_builds_the_sink_only_from_an_explicit_topic_url():
    s = ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: URL, ntfy.ENV_TOKEN: TOKEN}, opener=Opener())
    assert isinstance(s, ntfy.NtfySink) and s.sink_id == "ntfy" and s.target.host == "ntfy.sh"


def test_factory_reads_the_process_environment_when_no_mapping_is_given(monkeypatch):
    monkeypatch.delenv(ntfy.ENV_TOPIC_URL, raising=False)
    assert ntfy.sink_from_env() is None
    monkeypatch.setenv(ntfy.ENV_TOPIC_URL, URL)
    assert ntfy.sink_from_env(opener=Opener()) is not None


@pytest.mark.parametrize("bad", [f"http://ntfy.sh/{TOPIC}", f"https://ntfy.sh/{TOPIC}/x", f"https://evil.example/{TOPIC}",
                                 f"https://u:p@ntfy.sh/{TOPIC}", f"https://ntfy.sh/{TOPIC}?auth=x",
                                 f"https://169.254.169.254/{TOPIC}", "https://ntfy.sh/short", f"\x00https://ntfy.sh/{TOPIC}",
                                 f"\x1fhttps://ntfy.sh/{TOPIC}", f"https://ntfy.sh/{TOPIC}\x7f",
                                 f"https://ntfy.sh/{TOPIC}?", f"https://ntfy.sh/{TOPIC}#", f"https://ntfy.sh/{TOPIC}\t"])
def test_invalid_configuration_is_refused_without_echoing_the_url(bad):
    with pytest.raises(ntfy.NtfyConfigError) as err:
        ntfy.sink_from_env({ntfy.ENV_TOPIC_URL: bad})
    for part in (TOPIC, "auth=x", "u:p", "short", "evil"):
        assert part not in str(err.value)


@pytest.mark.parametrize("token", ["has space", "a\r\nX-Evil: 1", "x" * 129, "tok/en"])
def test_a_malformed_token_is_refused_without_echoing_it(token):
    with pytest.raises(ntfy.NtfyConfigError) as err:
        ntfy.NtfySink(URL, token=token, opener=Opener())
    assert token not in str(err.value)


# The owner approved activation on 2026-09-24: `edge-lab notify relay|test` (cli.py) are the
# ONLY constructors. The daily run, the shadow unit (no network) and every deploy file stay out.
_CONSTRUCT = re.compile(r"import\s+notify_ntfy|notify_ntfy\s+import|from\s+\S*notify_ntfy|import\s[^\n]*\bnotify_ntfy\b"
                        r"|NtfySink\(|sink_from_env\(")
_SECRET_NAME = re.compile(r"EDGE_LAB_NTFY_")


def _users(repo_root, pattern):
    users = []
    for base in ("src", "deploy", "scripts"):
        for path in (repo_root / base).rglob("*"):
            if path.is_file() and path.name != "notify_ntfy.py" and "__pycache__" not in path.parts:
                if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                    users.append(path.relative_to(repo_root).as_posix())
    return set(users)


def test_only_the_notify_commands_construct_the_sink(repo_root):
    """No run path, timer or deploy file constructs the sink."""
    assert _users(repo_root, _CONSTRUCT) == {"src/edge_lab/cli.py"}
    cli = (repo_root / "src/edge_lab/cli.py").read_text(encoding="utf-8")
    assert cli.count("sink_from_env(") == 1 and "NtfySink(" not in cli
    handler = cli[cli.index("def _notify("):cli.index("def main(")]
    assert "sink_from_env(" in handler  # the one construction lives in the notify handler
    assert "notify_ntfy" not in (repo_root / "src/edge_lab/daily.py").read_text(encoding="utf-8")


def test_only_the_topic_script_names_the_secret_variables(repo_root):
    """The topic lives in the secrets file; only the root-run topic writer names it."""
    assert _users(repo_root, _SECRET_NAME) == {"deploy/vps/set_ntfy_topic.py"}


# ------------------------------------------------------------------ the target cannot be redirected

def test_the_target_property_cannot_be_reassigned():
    s, _ = make()
    with pytest.raises(AttributeError):
        s.target = ntfy.parse_topic_url(URL)
    with pytest.raises(AttributeError):
        s.extra = 1  # __slots__: no ad-hoc attributes


def test_a_directly_built_target_is_validated():
    with pytest.raises(ntfy.NtfyConfigError):
        ntfy.Target(f"https://api.betfair.com/{TOPIC}")


def test_a_tampered_target_is_revalidated_and_never_sent():
    opener = Opener()
    s, _ = make(opener)
    forged = object.__new__(ntfy.Target)
    object.__setattr__(forged, "url", f"https://api.betfair.com/{TOPIC}")
    object.__setattr__(forged, "host", "api.betfair.com")
    s._target = forged
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert opener.requests == [] and "NtfyConfigError" in s.last_error


def test_a_target_mutated_in_place_is_revalidated_and_never_sent():
    opener = Opener()
    s, _ = make(opener)
    object.__setattr__(s.target, "url", f"https://ntfy.sh.evil.com/{TOPIC}")
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED and opener.requests == []


def test_the_opener_refuses_any_url_but_the_validated_one():
    opener = Opener()
    s, _ = make(opener)
    for url in (f"https://api.betfair.com/{TOPIC}", "https://ntfy.sh/another-topic-0123456"):
        with pytest.raises(ntfy.NtfyConfigError):
            s._opener(Request(url, data=b"x", method="POST"), 1.0)
    with pytest.raises(ntfy.NtfyConfigError):
        s._opener(Request(URL), 1.0)  # a GET is not a publish either
    assert opener.requests == []


def test_the_default_opener_is_guarded_too():
    s = ntfy.NtfySink(URL)  # no injected opener: the guard wraps the real one
    with pytest.raises(ntfy.NtfyConfigError):
        s._opener(Request("https://api.pinnacle.com/x", data=b"x", method="POST"), 1.0)


def test_the_real_opener_ignores_proxies_and_redirects():
    handler = ntfy._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/x") is None
    source = open(ntfy.__file__, encoding="utf-8").read()
    assert "build_opener(ProxyHandler({}), _NoRedirect)" in source


# ------------------------------------------------------------------ repr and secrets

def test_repr_and_str_never_show_the_topic_or_token():
    s, _ = make(token=TOKEN)
    for text in (repr(s), str(s), repr(s.target), str(s.target), s.target.label):
        assert TOPIC not in text and TOKEN not in text, text
    assert "ntfy.sh" in repr(s)
    with pytest.raises(TypeError):
        vars(s)  # __slots__: no __dict__ to dump


def test_no_attribute_holds_the_token_or_the_redaction_list():
    s, _ = make(token=TOKEN)
    for name in ntfy.NtfySink.__slots__:
        value = getattr(s, name)
        assert value != TOKEN and TOKEN not in repr(value), name
        assert not isinstance(value, tuple), name  # no stored secrets list
    assert not hasattr(s, "_token") and not hasattr(s, "_secrets")


@pytest.mark.parametrize("copier", ["pickle", "copy", "deepcopy"])
def test_the_sink_and_its_target_refuse_to_be_pickled_or_copied(copier):
    import copy
    import pickle

    s, _ = make(token=TOKEN)
    do = {"pickle": lambda o: pickle.dumps(o, protocol=pickle.HIGHEST_PROTOCOL), "copy": copy.copy,
          "deepcopy": copy.deepcopy}[copier]
    for obj in (s, s.target):
        with pytest.raises(TypeError):
            do(obj)
    with pytest.raises(TypeError):
        pickle.dumps(s, protocol=0)
    with pytest.raises(TypeError):
        s.__getstate__()


# ------------------------------------------------------------------ mapping and payload

def test_headers_map_title_priority_tags_and_hashed_sequence_id():
    opener = Opener()
    s, _ = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.SUBMITTED
    (request,) = opener.requests
    h = headers(request)
    assert request.get_method() == "POST" and request.full_url == URL
    assert h["x-title"] == "Market Edge WARNING: SOURCE_FAILURE"
    assert h["x-priority"] == "4"
    assert h["x-tags"] == "warning,source_failure"
    assert h["x-sequence-id"] == hashlib.blake2b(b"daily:FAILED:2026-09-25", key=TOPIC.encode(),
                                                 digest_size=32).hexdigest()
    assert set(h) == {"x-title", "x-priority", "x-tags", "x-sequence-id", "content-type"}
    assert request.data == b"A run or data source failed. Open Market Edge for details."


@pytest.mark.parametrize("severity,priority", [(n.Severity.INFO, "2"), (n.Severity.WARNING, "4"),
                                               (n.Severity.CRITICAL, "5")])
def test_priority_follows_severity(severity, priority):
    opener = Opener()
    make(opener)[0].deliver(ev(severity=severity))
    assert headers(opener.requests[0])["x-priority"] == priority


def test_every_event_type_has_a_fixed_headline():
    assert set(ntfy.HEADLINES) == set(n.EventType)


def test_optional_bearer_token_is_sent_only_as_a_header():
    opener = Opener()
    make(opener, token=TOKEN)[0].deliver(ev())
    request = opener.requests[0]
    assert headers(request)["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.full_url and TOKEN.encode() not in request.data


def test_real_receipt_events_send_no_identifier():
    """Events built by `events_from_receipt` carry market ids, account labels, fill ids and
    dates in their summaries, values and dedupe keys. None of it may reach ntfy."""
    receipt = {"state": "FAILED", "generated_at_utc": NOW.isoformat(), "problems": ["nws timeout"],
               "days": [{"target_date": "2026-09-24", "capture_status": "INVALID", "result": "INVALID_CAPTURE",
                         "accounts": {"research-acct-5521": {"risk_vetoes": 3}, "starter-acct-9034": {"risk_vetoes": 1}}}],
               "settlement": {"settled": 4, "conflicts": [{"market_id": "kalshi:KXHIGHNY-26SEP24-T71",
                                                           "sources": ["cli", "kalshi"]}]}}
    exceptions = [{"fill_id": "fill-7d1c93", "market_id": "kalshi:KXHIGHNY-26SEP20-B68.5",
                   "tradable_cash_release_eta_utc": "2026-09-21T00:00:00+00:00"}]
    events = n.events_from_receipt(receipt, now=NOW, exceptions=exceptions)
    assert {e.type for e in events} == {n.EventType.SOURCE_FAILURE, n.EventType.CAPTURE_INVALID, n.EventType.RISK_VETO,
                                        n.EventType.SETTLED, n.EventType.SEVEN_DAY_POLICY_EXCEPTION}
    opener = Opener()
    s, _ = make(opener)
    assert {s.deliver(e) for e in events} == {n.DeliveryStatus.SUBMITTED}
    assert len(opener.requests) == len(events)
    forbidden = ["KXHIGHNY", "kalshi", "research-acct-5521", "starter-acct-9034", "acct", "fill-7d1c93", "2026-09",
                 "nws timeout", "127.0.0.1", "OPEN_MARKET_EDGE"]
    for e in events:
        forbidden += [e.dedupe_key, e.summary, e.event_id, *(v for v in e.values.values() if len(v) >= 4)]
    for request in opener.requests:
        text = sent_text(request).replace(URL, "")
        for item in forbidden:
            assert item not in text, (item, text)


def test_payload_ignores_values_refs_and_links():
    e = ev(n.EventType.SEVEN_DAY_POLICY_EXCEPTION, n.Severity.CRITICAL, key="starter-exception:fill-1",
           summary="Capital past release: kalshi:KXHIGHNY-X", ttl=timedelta(hours=1),
           values={"position": "12 contracts", "pnl": "-3.10", "balance": "250.00", "account": "acct-778899"},
           venue_id="kalshi", market_id="kalshi:KXHIGHNY-X", event_ref="weather:nyc",
           action_mode=n.ActionMode.OPEN_MARKET_EDGE, deep_link="https://kalshi.com/markets/kxhighny")
    opener = Opener()
    make(opener)[0].deliver(e)
    text = sent_text(opener.requests[0]).replace(URL, "")
    for leaked in ("12 contracts", "3.10", "250.00", "acct-778899", "kalshi", "KXHIGHNY", "weather:nyc", "fill-1",
                   "https://", e.event_id):
        assert leaked not in text, leaked


@pytest.mark.parametrize("field,value", [("summary", "retry with api_key=abc123def456"),
                                         ("values", {"auth": "Bearer abcdefghijklmnop"})])
def test_an_event_carrying_a_secret_is_refused_and_not_sent(field, value):
    opener = Opener()
    s, _ = make(opener)
    assert s.deliver(ev(**{field: value})) is n.DeliveryStatus.REFUSED_SECRET
    assert opener.requests == [] and s.last_attempts == 0


# ------------------------------------------------------------------ expiry and dedupe

def test_an_event_expired_at_send_time_is_not_sent():
    opener = Opener()
    old = ev(created_at=NOW - timedelta(minutes=10), ttl=timedelta(minutes=2))
    assert make(opener)[0].deliver(old) is n.DeliveryStatus.EXPIRED
    assert opener.requests == []


@pytest.mark.parametrize("expiry", ["not a time", "2026-09-25T23:00:00", ""])
def test_an_unparseable_expiry_fails_closed(expiry):
    opener = Opener()
    e = n.NotificationEvent(event_id="ntf-x", type=n.EventType.SETTLED, severity=n.Severity.INFO,
                            created_at_utc=NOW.isoformat(), expires_at_utc=expiry, summary="x", dedupe_key="k")
    assert make(opener)[0].deliver(e) is n.DeliveryStatus.EXPIRED and opener.requests == []


def test_an_event_that_expires_during_retries_stops_being_sent():
    times = iter([NOW, NOW + timedelta(minutes=5)])
    opener = Opener(http_error(503))
    s, _ = make(opener, now=lambda: next(times))
    assert s.deliver(ev(ttl=timedelta(minutes=1))) is n.DeliveryStatus.EXPIRED
    assert len(opener.requests) == 1


KEY = TOPIC.encode()
OTHER_KEY = b"another-topic-0123456789"


def test_sequence_id_is_keyed_by_the_topic_and_not_a_plain_hash():
    for key in ("daily:FAILED:2026-09-25", "veto:acct1:2026-09-23", "settlement-conflict:" + "x" * 500, "ok_key"):
        seq = ntfy.sequence_id(key, KEY)
        assert ntfy.SEQUENCE_ID.fullmatch(seq) and seq == ntfy.sequence_id(key, KEY)  # stable per topic
        assert seq == hashlib.blake2b(key.encode(), key=KEY, digest_size=32).hexdigest()
        assert seq != hashlib.sha256(key.encode()).hexdigest()  # a guessable key cannot be brute-forced
        assert seq != hashlib.blake2b(key.encode(), digest_size=32).hexdigest()
        assert seq != ntfy.sequence_id(key, OTHER_KEY)  # differs across topics
        assert "acct1" not in seq and "2026" not in seq and "ok_key" not in seq
    assert ntfy.sequence_id("a:b", KEY) != ntfy.sequence_id("a/b", KEY)
    assert ntfy.sequence_id("", KEY) is None


def test_the_sequence_key_is_the_validated_topic_capped_at_64_bytes():
    assert ntfy.sequence_key(URL) == KEY
    long_topic = "t" * 64
    assert ntfy.sequence_key(f"https://ntfy.sh/{long_topic}") == long_topic.encode()
    with pytest.raises(ntfy.NtfyConfigError):
        ntfy.sequence_id("k", b"short")


def test_sinks_on_different_topics_send_different_sequence_ids_for_one_key():
    a, b = Opener(), Opener()
    make(a)[0].deliver(ev())
    ntfy.NtfySink("https://ntfy.sh/another-topic-0123456789", opener=b, sleep=lambda s: None,
                  clock=lambda: NOW).deliver(ev())
    assert headers(a.requests[0])["x-sequence-id"] != headers(b.requests[0])["x-sequence-id"]


def test_an_empty_dedupe_key_sends_no_sequence_id_and_is_never_retried():
    opener = Opener(http_error(503))
    s, _ = make(opener)
    assert s.deliver(ev(key="")) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == 1 and "x-sequence-id" not in headers(opener.requests[0])


def test_dispatch_dedupe_prevents_a_second_publish(tmp_path, monkeypatch):
    if not hasattr(n.os, "fchmod"):  # POSIX-only; stubbed so this test also runs on Windows
        monkeypatch.setattr(n.os, "fchmod", lambda fd, mode: None, raising=False)
    outbox, opener = n.JsonlOutbox(tmp_path / "out.jsonl"), Opener()
    s, _ = make(opener)
    first = n.dispatch([ev()], [outbox, s], now=NOW)
    later = NOW + timedelta(hours=3)
    again = n.dispatch([ev(created_at=later)], [outbox, s], now=later, history=outbox.history())
    assert [r["status"] for r in first] == ["DELIVERED", "SUBMITTED"]
    assert [r["status"] for r in again] == ["DEDUPED"] and len(opener.requests) == 1


def test_dispatch_dedupe_by_history_prevents_a_second_publish():
    opener = Opener()
    later = NOW + timedelta(hours=1)
    results = n.dispatch([ev(created_at=later)], [make(opener)[0]], now=later, history=[ev().to_dict()])
    assert [r["status"] for r in results] == ["DEDUPED"] and opener.requests == []


# ------------------------------------------------------------------ failures, retries, never raises

def test_retries_are_bounded_with_injected_backoff():
    opener = Opener(http_error(503))
    s, clock = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == ntfy.MAX_ATTEMPTS == s.last_attempts == 3
    assert clock.sleeps == [1.0, 2.0] and s.last_http_status == 503


def test_max_attempts_cannot_be_raised_past_the_fixed_bound():
    opener = Opener(http_error(500))
    make(opener, max_attempts=50)[0].deliver(ev())
    assert len(opener.requests) == ntfy.MAX_ATTEMPTS


class SlowOpener(Opener):
    """Each attempt takes `cost` seconds of fake monotonic time."""

    def __init__(self, clock, cost, *steps):
        super().__init__(*steps)
        self.clock, self.cost = clock, cost

    def __call__(self, request, timeout):
        self.clock.t += min(self.cost, timeout)
        return super().__call__(request, timeout)


def test_a_per_event_deadline_bounds_the_total_time():
    clock = Clock()
    opener = SlowOpener(clock, 10.0, socket.timeout("timed out"))
    s, _ = make(opener, clock=clock)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert clock.t <= ntfy.DEADLINE_SECONDS
    assert len(opener.requests) == 2 and opener.timeouts == [10.0, 4.0]


def test_the_deadline_cannot_be_raised_past_the_fixed_bound():
    s, _ = make(deadline=600.0, timeout=600.0)
    assert s.deadline == ntfy.DEADLINE_SECONDS and s.timeout == ntfy.DEADLINE_SECONDS


def test_a_circuit_breaker_stops_sending_to_a_dead_host_then_recovers():
    clock = Clock()
    opener = Opener(URLError("connection refused"))
    s, _ = make(opener, clock=clock)
    for i in range(ntfy.BREAKER_THRESHOLD):
        assert s.deliver(ev(key=f"k{i}")) is n.DeliveryStatus.FAILED
    sent = len(opener.requests)
    assert s.deliver(ev(key="next")) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == sent and "circuit open" in s.last_error and s.last_attempts == 0
    clock.t += ntfy.BREAKER_COOLDOWN_SECONDS
    opener.steps = [Response()]
    assert s.deliver(ev(key="after")) is n.DeliveryStatus.SUBMITTED
    assert s.deliver(ev(key="again")) is n.DeliveryStatus.SUBMITTED


def test_a_transient_failure_then_success_is_submitted():
    opener = Opener(http_error(502), Response())
    s, _ = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.SUBMITTED and s.last_attempts == 2 and s.last_error is None


def test_429_is_rate_limited_and_not_retried():
    opener = Opener(http_error(429))
    s, clock = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.RATE_LIMITED
    assert len(opener.requests) == 1 and clock.sleeps == [] and s.last_http_status == 429


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 302])
def test_other_4xx_and_redirects_fail_without_retry(code):
    opener = Opener(http_error(code))
    s, _ = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED and len(opener.requests) == 1


@pytest.mark.parametrize("response", [Response(status=500), Response(status=None), Response(status="200")])
def test_a_non_2xx_or_missing_status_is_not_submitted(response):
    assert make(Opener(response))[0].deliver(ev()) is n.DeliveryStatus.FAILED


@pytest.mark.parametrize("exc", [ssl.SSLCertVerificationError("certificate verify failed"),
                                 URLError(ssl.SSLCertVerificationError("certificate verify failed"))])
def test_certificate_errors_are_not_retried(exc):
    opener = Opener(exc)
    s, _ = make(opener)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED and len(opener.requests) == 1


@pytest.mark.parametrize("exc", [socket.timeout("timed out"), TimeoutError("timed out"),
                                 URLError(f"connect to {URL} refused"), ConnectionResetError("reset")])
def test_timeouts_and_network_errors_fail_after_bounded_retries(exc):
    opener = Opener(exc)
    s, _ = make(opener, token=TOKEN)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert len(opener.requests) == 3
    assert TOPIC not in s.last_error and TOKEN not in s.last_error


def test_errors_are_redacted_even_when_the_provider_echoes_secrets():
    s, _ = make(Opener(URLError(f"proxy said: {URL} Bearer {TOKEN} token={TOKEN}")), token=TOKEN)
    s.deliver(ev())
    assert TOPIC not in s.last_error and TOKEN not in s.last_error
    assert "ntfy.sh" in s.last_error  # the host alone is not the secret


def test_the_sink_never_raises_even_on_an_unexpected_error():
    s, _ = make(Opener(RuntimeError(f"bug near {URL} with {TOKEN}")), token=TOKEN)
    assert s.deliver(ev()) is n.DeliveryStatus.FAILED
    assert TOPIC not in s.last_error and TOKEN not in s.last_error


def test_dispatch_records_the_redacted_failure_and_the_sinks_own_attempts():
    s, _ = make(Opener(http_error(503)), token=TOKEN)
    results = n.dispatch([ev(), ev(key="second")], [s, n.DisabledSmsSink()], now=NOW)
    assert [(r["sink"], r["status"]) for r in results] == [("ntfy", "FAILED"), ("sms-disabled", "DISABLED_NO_PROVIDER")] * 2
    ntfy_records = [r for r in results if r["sink"] == "ntfy"]
    assert all(r["error"] and TOPIC not in r["error"] and TOKEN not in r["error"] for r in ntfy_records)
    assert [r["attempts"] for r in ntfy_records] == [3, 3]


def test_dispatch_records_zero_attempts_when_the_sink_refused_before_sending():
    s, clock = make(Opener())
    stale = n.NotificationEvent(event_id="ntf-x", type=n.EventType.SETTLED, severity=n.Severity.INFO,
                                created_at_utc=NOW.isoformat(), expires_at_utc="garbage", summary="x", dedupe_key="k")
    (record,) = n.dispatch([stale], [s], now=NOW)
    assert record["status"] == "EXPIRED" and record["attempts"] == 0


def test_a_submitted_push_is_never_reported_as_delivered():
    results = n.dispatch([ev()], [make()[0]], now=NOW)
    assert [r["status"] for r in results] == ["SUBMITTED"]


def test_notification_failure_changes_no_caller_state():
    """The sink holds no reference to risk, ledger or trading state; a failure only sets its own
    diagnostic fields, and the event is unchanged."""
    e = ev()
    before = e.to_dict()
    s, _ = make(Opener(OSError("down")))
    s.deliver(e)
    assert e.to_dict() == before
    assert set(ntfy.NtfySink.__slots__) == {
        "_target", "_has_token", "_redact", "_opener", "_sleep", "_clock", "_monotonic", "max_attempts", "backoff",
        "timeout", "deadline", "last_error", "last_attempts", "last_http_status", "_consecutive_failures",
        "_open_until"}


# ------------------------------------------------------------------ relay and test send (2026-09-24)

def _outbox_with(tmp_path, *events):
    box = n.JsonlOutbox(tmp_path / "notifications.jsonl")
    for e in events:
        box.deliver(e)
    return tmp_path / "notifications.jsonl", tmp_path / ntfy.RELAY_NAME


def test_relay_forwards_each_recent_outbox_event_once(tmp_path):
    outbox, relay = _outbox_with(tmp_path, ev(key="a"), ev(n.EventType.SETTLED, n.Severity.INFO, key="b"))
    opener = Opener()
    s, _ = make(opener=opener)
    first = ntfy.relay_outbox(outbox, relay, s, now=NOW)
    assert first == {"status": "ok", "candidates": 2, "by_status": {"SUBMITTED": 2}}
    assert len(opener.requests) == 2
    second = ntfy.relay_outbox(outbox, relay, s, now=NOW)
    assert second == {"status": "ok", "candidates": 0, "by_status": {}}  # already in the relay history
    assert len(opener.requests) == 2  # nothing re-sent


def test_relay_retries_a_failed_event_on_the_next_run(tmp_path):
    outbox, relay = _outbox_with(tmp_path, ev(key="a"))
    down, _ = make(opener=Opener(http_error(400)))
    assert ntfy.relay_outbox(outbox, relay, down, now=NOW)["by_status"] == {"FAILED": 1}
    up, _ = make(opener=Opener())
    assert ntfy.relay_outbox(outbox, relay, up, now=NOW)["by_status"] == {"SUBMITTED": 1}


def test_relay_does_not_replay_old_history(tmp_path):
    old = ev(key="old", created_at=NOW - ntfy.RELAY_MAX_AGE - timedelta(minutes=1))
    outbox, relay = _outbox_with(tmp_path, old, ev(key="new"))
    opener = Opener()
    s, _ = make(opener=opener)
    assert ntfy.relay_outbox(outbox, relay, s, now=NOW)["candidates"] == 1
    assert len(opener.requests) == 1


def test_relay_sends_only_the_fixed_headline(tmp_path):
    secretish = ev(key="a", summary="EXP-001 B66.5 NO filled 1 @ 0.56; balance $999.44",
                   market_id="kalshi:KXHIGHNY-26SEP24-B66.5", values={"stake": "0.56"})
    outbox, relay = _outbox_with(tmp_path, secretish)
    opener = Opener()
    s, _ = make(opener=opener)
    ntfy.relay_outbox(outbox, relay, s, now=NOW)
    body = opener.requests[0].data.decode()
    assert "0.56" not in body and "KXHIGHNY" not in body and "999" not in body
    assert ntfy.HEADLINES[n.EventType.SOURCE_FAILURE] in body


def test_relay_never_raises_and_reports_counts_only(tmp_path):
    (tmp_path / "notifications.jsonl").write_text("not json\n{\"schema\": \"other\"}\n", encoding="utf-8")
    s, _ = make()
    out = ntfy.relay_outbox(tmp_path / "notifications.jsonl", tmp_path / ntfy.RELAY_NAME, s, now=NOW)
    assert out == {"status": "ok", "candidates": 0, "by_status": {}}
    broken = ntfy.relay_outbox(tmp_path / "notifications.jsonl", tmp_path / ntfy.RELAY_NAME, s, now="not a time")
    assert broken["status"] == "failed" and TOPIC not in json.dumps(broken)


def test_the_relay_history_is_not_written_for_a_failure(tmp_path):
    outbox, relay = _outbox_with(tmp_path, ev(key="a"))
    s, _ = make(opener=Opener(http_error(429)))
    assert ntfy.relay_outbox(outbox, relay, s, now=NOW)["by_status"] == {"RATE_LIMITED": 1}
    assert not relay.exists()


def test_send_test_submits_one_fixed_event():
    opener = Opener()
    s, _ = make(opener=opener)
    out = ntfy.send_test(s, now=NOW)
    assert out["by_status"] == {"SUBMITTED": 1} and out["error"] is None
    assert len(opener.requests) == 1
    assert ntfy.HEADLINES[n.EventType.TEST] in opener.requests[0].data.decode()


def test_an_outbox_line_round_trips_to_the_same_event():
    e = ev(key="a", market_id="kalshi:X", values={"k": "v"}, ttl=timedelta(hours=1))
    assert n.event_from_dict(e.to_dict()) == e
    assert n.event_from_dict({"schema": n.SCHEMA, "type": "NOT_A_TYPE"}) is None


def test_relay_records_each_submission_at_once(tmp_path):
    """A relay killed after the first send must not re-send it."""
    outbox, relay = _outbox_with(tmp_path, ev(key="a"), ev(key="b"))

    class DiesOnSecond:
        sink_id = "ntfy"
        calls = 0

        def deliver(self, event):
            self.calls += 1
            if self.calls == 2:
                raise KeyboardInterrupt  # stands in for SIGKILL mid-run
            return n.DeliveryStatus.SUBMITTED

    with pytest.raises(KeyboardInterrupt):
        ntfy.relay_outbox(outbox, relay, DiesOnSecond(), now=NOW)
    opener = Opener()
    s, _ = make(opener=opener)
    assert ntfy.relay_outbox(outbox, relay, s, now=NOW)["by_status"] == {"SUBMITTED": 1}
    assert len(opener.requests) == 1


def test_relay_dedupes_by_event_id_even_without_a_dedupe_key(tmp_path):
    outbox, relay = _outbox_with(tmp_path, ev(key=""))
    opener = Opener()
    s, _ = make(opener=opener)
    ntfy.relay_outbox(outbox, relay, s, now=NOW)
    ntfy.relay_outbox(outbox, relay, s, now=NOW)
    assert len(opener.requests) == 1


def test_relay_pushes_a_unit_failure_that_left_no_outbox_event(tmp_path):
    failure = tmp_path / "last_failure.json"
    failure.write_text(json.dumps({"unit": "edgelab-shadow.service", "failed_at_utc": "2026-09-25T22:40:05Z"}))
    opener = Opener()
    s, _ = make(opener=opener)
    out = ntfy.relay_outbox(tmp_path / "notifications.jsonl", tmp_path / ntfy.RELAY_NAME, s, now=NOW,
                            failure_path=failure)
    assert out["by_status"] == {"SUBMITTED": 1}
    body = opener.requests[0].data.decode()
    assert ntfy.HEADLINES[n.EventType.SOURCE_FAILURE] in body and "shadow" not in body
    again = ntfy.relay_outbox(tmp_path / "notifications.jsonl", tmp_path / ntfy.RELAY_NAME, s, now=NOW,
                              failure_path=failure)
    assert again["candidates"] == 0 and len(opener.requests) == 1


@pytest.mark.parametrize("record", [{"unit": "rm -rf /", "failed_at_utc": "2026-09-25T22:40:05Z"},
                                    {"unit": "edgelab-shadow.service", "failed_at_utc": "yesterday"}, {}])
def test_a_malformed_failure_record_is_ignored(record):
    assert ntfy.unit_failure_event(record) is None


def test_relay_skips_expired_events_and_reads_the_rotated_outbox(tmp_path):
    expired = ev(key="gone", ttl=timedelta(minutes=1), created_at=NOW - timedelta(hours=1))
    rotated = n.JsonlOutbox(tmp_path / "notifications.jsonl.1")
    rotated.path = tmp_path / "notifications.jsonl.1"
    rotated.deliver(ev(key="rotated"))
    outbox, relay = _outbox_with(tmp_path, expired)
    opener = Opener()
    s, _ = make(opener=opener)
    out = ntfy.relay_outbox(outbox, relay, s, now=NOW)
    assert out["by_status"] == {"EXPIRED": 1, "SUBMITTED": 1}


def test_relay_sends_critical_first_and_never_rate_limits_it(tmp_path):
    flood = [ev(n.EventType.OPPORTUNITY_QUALIFIED, n.Severity.INFO, key=f"i{i}") for i in range(25)]
    kill = ev(n.EventType.KILL_SWITCH, n.Severity.CRITICAL, key="kill")
    outbox, relay = _outbox_with(tmp_path, *flood, kill)
    opener = Opener()
    s, _ = make(opener=opener)
    out = ntfy.relay_outbox(outbox, relay, s, now=NOW)
    assert out["by_status"] == {"SUBMITTED": 21, "RATE_LIMITED": 5}
    assert ntfy.HEADLINES[n.EventType.KILL_SWITCH] in opener.requests[0].data.decode()


# ------------------------------------------------------------------ CLI (edge-lab notify)

def test_cli_without_a_topic_is_not_configured_and_exits_zero(monkeypatch, capsys, tmp_path):
    from edge_lab import cli
    monkeypatch.delenv(ntfy.ENV_TOPIC_URL, raising=False)
    assert cli.main(["notify", "relay", "--status-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "not_configured"}


def test_cli_with_an_invalid_topic_exits_one_without_echoing_it(monkeypatch, capsys):
    from edge_lab import cli
    bad = "https://ntfy.sh/short-secret"
    monkeypatch.setenv(ntfy.ENV_TOPIC_URL, bad)
    assert cli.main(["notify", "test"]) == 1
    out = capsys.readouterr().out
    assert "short-secret" not in out and json.loads(out)["status"] == "config_error"


def test_cli_prints_counts_only_never_the_topic(monkeypatch, capsys, tmp_path):
    from edge_lab import cli
    opener = Opener()
    monkeypatch.setattr(ntfy, "sink_from_env", lambda *a, **k: make(opener=opener, now=lambda: datetime.now(UTC))[0])
    _outbox_with(tmp_path, ev(key="a", created_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert cli.main(["notify", "relay", "--status-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert TOPIC not in out and json.loads(out)["by_status"] == {"SUBMITTED": 1}
    assert cli.main(["notify", "test"]) == 0
    out = capsys.readouterr().out
    assert TOPIC not in out and json.loads(out)["by_status"] == {"SUBMITTED": 1}
