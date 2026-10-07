"""Environment-isolated transport (#160 package F). FIXTURE only, an injected fake opener, keys generated at test
time. Nothing here can reach a network: the FIXTURE host is `fixture.invalid` and the opener is a script."""

from __future__ import annotations

import base64
import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from edge_lab.execution import conformance as c
from edge_lab.execution import kalshi_wire as w
from edge_lab.execution import model as m
from edge_lab.execution import signer as s
from edge_lab.execution import transport as t

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kalshi_exec"
UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, 30, 750999, tzinfo=UTC)
NOW_MS = 1791385230750
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
KEY_ID = "fixture-key-id"
ORDER_ID = "3b23c1c7-f4ef-4f0d-8b9a-9e53c61f1a0d"
BASE = "https://fixture.invalid/trade-api/v2"


class Response:
    def __init__(self, status: int, body: bytes = b"{}", url: str | None = None):
        self.status, self._body, self._url = status, body, url

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def geturl(self):
        return self._url


class Opener:
    """A scripted opener: each call pops the next outcome (a Response, or an exception to raise)."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, request, timeout):
        self.calls.append(request)
        self.timeout = timeout
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome._url is None:
            outcome._url = request.full_url
        return outcome


class Clock:
    def __init__(self):
        self.ns = 0

    def __call__(self) -> int:
        return self.ns


@pytest.fixture(scope="module")
def key():
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def signer(key):
    return s.Signer(key_id=KEY_ID, private_key=key, environment=m.Environment.FIXTURE, account_ref="fixture-acct")


def transport(signer, opener, **kw):
    sleeps = kw.pop("sleeps", [])
    return t.Transport(m.Environment.FIXTURE, signer, opener, lambda: NOW, sleep=sleeps.append, **kw)


def market():
    return c.MarketTradingProfile.from_market_record(json.loads((FIXTURES / "market_binary_active.json").read_bytes()))


def create_request(**kw):
    grid = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
    base = dict(intent_key="EXP-TEST:ticket-0001", strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
                market_ticker="HIGHNY-24JAN01-T60", kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal("10"), limit_price=Decimal("0.56"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("6.00"), expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(),
                price_grid=grid, quantity_grid=c.quantity_grid("1000"), profile_version=c.PROFILE_VERSION,
                risk_policy_version="risk-v1", fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=False)
    base.update(kw)
    return w.build_create(m.OrderIntent(**base), market())


CREATE_ACK = (FIXTURES / "create_order_v2_response.json").read_bytes()
CANCEL_ACK = (FIXTURES / "cancel_order_v2_response.json").read_bytes()
BALANCE = (FIXTURES / "get_balance.json").read_bytes()


# ---------------------------------------------------------------------------------------------- environment


@pytest.mark.parametrize("env", [m.Environment.DEMO, m.Environment.PRODUCTION, "FIXTURE", None])
def test_only_fixture_is_authorized(signer, env):
    with pytest.raises(t.EnvironmentNotAuthorized):
        t.Transport(env, signer, Opener(), lambda: NOW)


def test_there_is_no_override_or_force_parameter():
    params = set(inspect.signature(t.Transport).parameters)
    assert params == {"environment", "signer", "opener", "clock", "host", "budget", "timeout_s", "read_attempts",
                      "sleep"}
    assert not any("force" in p or "override" in p or "unsafe" in p for p in params)


def test_production_write_is_impossible_even_with_a_key(key):
    with pytest.raises(s.SigningRefused):  # no production signer can exist
        s.Signer(key_id=KEY_ID, private_key=key, environment=m.Environment.PRODUCTION, account_ref="prod")
    fixture_signer = s.Signer(key_id=KEY_ID, private_key=key, environment=m.Environment.FIXTURE, account_ref="prod")
    with pytest.raises(t.EnvironmentNotAuthorized):
        t.Transport(m.Environment.PRODUCTION, fixture_signer, Opener(), lambda: NOW)
    prod_request = w.build_get_balance(m.AccountScope(m.Environment.PRODUCTION, "prod"))
    opener = Opener(Response(200))
    with pytest.raises(t.EnvironmentNotAuthorized):
        transport(fixture_signer, opener).send(prod_request)
    assert opener.calls == []


def test_send_rechecks_authorization(signer, monkeypatch):
    opener = Opener(Response(200, BALANCE))
    tr = transport(signer, opener)
    monkeypatch.setattr(t, "environment_authorized", lambda env: False)  # as a later revocation would
    with pytest.raises(t.EnvironmentNotAuthorized):
        tr.send(w.build_get_balance(SCOPE))
    assert opener.calls == []


def test_an_opener_must_be_injected(signer):
    with pytest.raises(t.RequestNotAllowed):
        t.Transport(m.Environment.FIXTURE, signer, None, lambda: NOW)
    with pytest.raises(t.RequestNotAllowed):
        t.Transport(m.Environment.FIXTURE, object(), Opener(), lambda: NOW)


@pytest.mark.parametrize("host", ["external-api.kalshi.com", "demo-api.kalshi.co", "evil.example",
                                  "fixture.invalid.evil.example", "fixture.invalid:8443", "user@fixture.invalid"])
def test_hosts_outside_the_environment_allowlist_are_refused(signer, host):
    with pytest.raises(t.HostNotAllowed):
        transport(signer, Opener(), host=host)


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "10"])
def test_timeouts_are_bounded(signer, timeout):
    with pytest.raises(ValueError):
        transport(signer, Opener(), timeout_s=timeout)


# ---------------------------------------------------------------------------------------------- requests on the wire


def test_a_read_is_signed_and_sent_to_the_allowlisted_url(signer):
    opener = Opener(Response(200, BALANCE))
    result = transport(signer, opener).send(w.build_get_balance(SCOPE))
    assert result.outcome is t.Outcome.OK and result.status == 200 and result.attempts == 1
    assert w.parse_balance(result.body).balance_cents == 10000
    (sent,) = opener.calls
    assert sent.get_method() == "GET" and sent.data is None
    assert sent.full_url == f"{BASE}/portfolio/balance?subaccount=0"
    headers = {k.lower(): v for k, v in sent.header_items()}
    names = t.header_names()
    assert headers[names["key"].lower()] == KEY_ID
    assert headers[names["timestamp"].lower()] == str(NOW_MS)  # exact ms, floored from the injected clock
    text = f"{NOW_MS}GET/trade-api/v2/portfolio/balance"  # the query is not signed
    signer.public_key().verify(base64.b64decode(headers[names["signature"].lower()]), text.encode())
    assert "authorization" not in headers and "cookie" not in headers
    assert opener.timeout == 10.0


def test_a_create_posts_the_canonical_body_once(signer):
    req = create_request()
    opener = Opener(Response(201, CREATE_ACK))
    result = transport(signer, opener).send(req)
    assert result.outcome is t.Outcome.OK and w.parse_create_ack(result.body).order_id == ORDER_ID
    (sent,) = opener.calls
    assert sent.get_method() == "POST" and sent.data == req.body
    assert sent.full_url == f"{BASE}/portfolio/events/orders"
    assert dict((k.lower(), v) for k, v in sent.header_items())["content-type"] == "application/json"


def test_a_cancel_is_a_delete(signer):
    opener = Opener(Response(200, CANCEL_ACK))
    result = transport(signer, opener).send(w.build_cancel(SCOPE, ORDER_ID, exchange_index=0),
                                            priority=t.Priority.PROTECTIVE)
    assert result.outcome is t.Outcome.OK and w.parse_cancel_ack(result.body).reduced_by == Decimal("10")
    assert opener.calls[0].get_method() == "DELETE" and opener.calls[0].data is None


@pytest.mark.parametrize("clock", [lambda: datetime(2026, 10, 7, 15, 0), lambda: "2026-10-07T15:00:00Z",
                                   lambda: 1791385230750])
def test_a_naive_or_non_datetime_clock_is_refused(signer, clock):
    opener = Opener(Response(200))
    tr = t.Transport(m.Environment.FIXTURE, signer, opener, clock)
    with pytest.raises(t.RequestNotAllowed):
        tr.send(w.build_get_balance(SCOPE))
    assert opener.calls == []


def test_a_skewed_clock_in_seconds_or_microseconds_cannot_reach_the_wire(signer):
    opener = Opener(Response(200))
    early = t.Transport(m.Environment.FIXTURE, signer, opener, lambda: datetime(1970, 1, 21, tzinfo=UTC))
    with pytest.raises(s.SigningRefused):
        early.send(w.build_get_balance(SCOPE))
    assert opener.calls == []


def test_non_allowlisted_or_foreign_requests_are_refused_before_sending(signer):
    opener = Opener(Response(200))
    tr = transport(signer, opener)
    tampered = object.__new__(w.WireRequest)
    for name, value in (("endpoint", w.Endpoint.GET_BALANCE), ("scope", SCOPE), ("path", "/portfolio/withdrawals"),
                        ("query", ()), ("body", None), ("exchange_index", None)):
        object.__setattr__(tampered, name, value)
    with pytest.raises(t.RequestNotAllowed):
        tr.send(tampered)
    with pytest.raises(t.RequestNotAllowed):
        tr.send("/portfolio/balance")
    with pytest.raises(t.RequestNotAllowed):
        tr.send(w.build_get_balance(m.AccountScope(m.Environment.FIXTURE, "other-acct")))
    with pytest.raises(t.EnvironmentNotAuthorized):
        tr.send(w.build_get_balance(m.AccountScope(m.Environment.DEMO, "fixture-acct")))
    with pytest.raises(t.RequestNotAllowed):  # a create can never jump the queue into reserved capacity
        tr.send(create_request(), priority=t.Priority.PROTECTIVE)
    assert opener.calls == []


# ---------------------------------------------------------------------------------------------- outcomes and retries


@pytest.mark.parametrize("failure,reason", [
    (TimeoutError("timed out"), "NO_RESPONSE"), (URLError("reset"), "NO_RESPONSE"), (ConnectionResetError(), "NO_RESPONSE"),
    (Response(500), "VENUE_ERROR"), (Response(503), "VENUE_ERROR"), (Response(302), "REDIRECT_REFUSED"),
    (Response(200, CREATE_ACK, url="https://evil.example/x"), "REDIRECT_REFUSED"),
    (HTTPError(f"{BASE}/portfolio/events/orders", 307, "redirect", {}, None), "REDIRECT_REFUSED"),
    (Response(200, b"x" * (t.MAX_RESPONSE_BYTES + 1)), "BODY_UNREADABLE"), (RuntimeError("opener bug"), "OPENER_ERROR"),
])
def test_an_unknowable_write_is_ambiguous_and_never_retried(signer, failure, reason):
    opener = Opener(failure, Response(201, CREATE_ACK))
    sleeps = []
    result = transport(signer, opener, sleeps=sleeps).send(create_request())
    assert result.outcome is t.Outcome.AMBIGUOUS and result.reason == reason
    assert len(opener.calls) == 1 and sleeps == []


@pytest.mark.parametrize("status,outcome", [(400, t.Outcome.REJECTED), (401, t.Outcome.REJECTED),
                                            (409, t.Outcome.REJECTED), (429, t.Outcome.THROTTLED)])
def test_definitive_write_refusals_are_reported_not_retried(signer, status, outcome):
    opener = Opener(Response(status, b'{"error": "too many requests"}'), Response(201, CREATE_ACK))
    result = transport(signer, opener).send(create_request())
    assert result.outcome is outcome and result.status == status and len(opener.calls) == 1


def test_http_error_statuses_from_a_real_style_opener_are_classified(signer):
    err = HTTPError(f"{BASE}/portfolio/events/orders", 409, "conflict", {}, None)
    result = transport(signer, Opener(err)).send(create_request())
    assert result.outcome is t.Outcome.REJECTED and result.status == 409


def test_reads_are_retried_a_bounded_number_of_times(signer):
    opener = Opener(Response(500), TimeoutError(), Response(200, BALANCE))
    sleeps = []
    result = transport(signer, opener, sleeps=sleeps).send(w.build_get_balance(SCOPE))
    assert result.outcome is t.Outcome.OK and result.attempts == 3 and sleeps == [0.5, 1.0]
    stamps = {dict(r.header_items())["Kalshi-access-timestamp"] for r in opener.calls}
    assert stamps == {str(NOW_MS)}  # re-signed each attempt (same fake clock)
    opener = Opener(Response(429), Response(500), Response(502))
    result = transport(signer, opener, sleeps=[]).send(w.build_get_balance(SCOPE))
    assert result.outcome is t.Outcome.UNAVAILABLE and result.attempts == 3 and len(opener.calls) == 3


def test_a_redirected_read_is_refused_and_not_retried(signer):
    opener = Opener(Response(301), Response(200, BALANCE))
    result = transport(signer, opener).send(w.build_get_balance(SCOPE))
    assert result.outcome is t.Outcome.UNAVAILABLE and result.reason == "REDIRECT_REFUSED" and len(opener.calls) == 1


def test_a_rejected_read_is_not_retried(signer):
    opener = Opener(Response(404), Response(200, BALANCE))
    result = transport(signer, opener).send(w.build_get_order(SCOPE, ORDER_ID))
    assert result.outcome is t.Outcome.REJECTED and len(opener.calls) == 1


# ---------------------------------------------------------------------------------------------- rate budget


def test_reserved_headroom_keeps_cancels_flowing_when_ordinary_writes_are_throttled(signer):
    clock = Clock()
    budget = t.RateBudget(monotonic_ns=clock)  # basic: write 100 tokens/s, capacity 1 s; 10 per request; 30% reserved
    opener = Opener(*[Response(201, CREATE_ACK)] * 7, *[Response(200, CANCEL_ACK)] * 3)
    tr = transport(signer, opener, budget=budget)
    creates = [tr.send(create_request()).outcome for _ in range(8)]
    assert creates == [t.Outcome.OK] * 7 + [t.Outcome.NOT_SENT]
    cancel = w.build_cancel(SCOPE, ORDER_ID, exchange_index=0)
    with pytest.raises(t.RequestNotAllowed):
        tr.send(create_request(), priority=t.Priority.PROTECTIVE)
    assert [tr.send(cancel, priority=t.Priority.PROTECTIVE).outcome for _ in range(4)] == \
        [t.Outcome.OK] * 3 + [t.Outcome.NOT_SENT]
    assert len(opener.calls) == 10  # a NOT_SENT request never reached the opener
    assert tr.send(cancel).outcome is t.Outcome.NOT_SENT  # an ordinary cancel cannot use the reserve either
    clock.ns += 1_000_000_000  # one second refills a basic write bucket
    opener.outcomes.append(Response(201, CREATE_ACK))
    assert tr.send(create_request()).outcome is t.Outcome.OK


def test_write_budgets_are_per_shard_and_reads_are_separate(signer):
    clock = Clock()
    budget = t.RateBudget(monotonic_ns=clock)
    for _ in range(7):
        assert budget.try_acquire(w.Bucket.WRITE, 0, t.Priority.ORDINARY)
    assert not budget.try_acquire(w.Bucket.WRITE, 0, t.Priority.ORDINARY)
    assert budget.try_acquire(w.Bucket.WRITE, 3, t.Priority.ORDINARY)  # shard 3 has its own full budget (RL-05)
    assert budget.try_acquire(w.Bucket.READ, None, t.Priority.ORDINARY)  # reads draw from the read bucket
    with pytest.raises(t.RequestNotAllowed):
        budget.try_acquire(w.Bucket.WRITE, None, t.Priority.ORDINARY)
    reads = 0
    while budget.try_acquire(w.Bucket.READ, None, t.Priority.ORDINARY):
        reads += 1
    assert reads + 1 == 600 * 7 // 10 // 10  # basic read: 200/s, 3 s capacity, 30% reserved, 10 tokens each


@pytest.mark.parametrize("kw", [dict(tier="platinum"), dict(reserve_fraction=(0, 10)), dict(reserve_fraction=(10, 10)),
                                dict(token_cost=0), dict(token_cost=True)])
def test_the_budget_refuses_undocumented_settings(kw):
    with pytest.raises(ValueError):
        t.RateBudget(**kw)


# ---------------------------------------------------------------------------------------------- redaction


def test_results_and_errors_never_carry_headers_signatures_or_bodies(signer):
    req = create_request()
    opener = Opener(Response(201, CREATE_ACK))
    tr = transport(signer, opener)
    result = tr.send(req)
    signature = dict(opener.calls[0].header_items())["Kalshi-access-signature"]
    texts = [repr(result), str(result), repr(tr), str(tr), repr(req)]
    for exc_type, call in ((t.RequestNotAllowed, lambda: tr.send(req, priority=t.Priority.PROTECTIVE)),
                           (t.RequestNotAllowed, lambda: tr.send(w.build_get_balance(
                               m.AccountScope(m.Environment.FIXTURE, "other-acct")))),
                           (t.HostNotAllowed, lambda: transport(signer, Opener(), host="evil.example"))):
        with pytest.raises(exc_type) as info:
            call()
        texts += [str(info.value), repr(info.value)]
        assert info.value.__cause__ is None
    for text in texts:
        assert signature not in text and KEY_ID not in text
        assert "ticker" not in text and CREATE_ACK.decode()[:20] not in text and req.body.decode()[:20] not in text
    with pytest.raises(TypeError):
        __import__("pickle").dumps(tr)
