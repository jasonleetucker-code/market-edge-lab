"""Exact-type `WireRequest` and spec-derived transport and signer decisions (#160 BF2). FIXTURE only: an injected
fake opener, keys generated at test time, nothing can reach a network (the FIXTURE host is `fixture.invalid`).

A subclass of `WireRequest` can override `is_write`, `method`, `full_path` and `query_string`. The allowlist guard
therefore accepts only the exact type, and the transport and signer read the endpoint specification and the
validated plain fields, never those methods. Two layers are tested separately:

- the guard refuses every lying subclass (`check_allowlisted`, and through it the signer, transport and account);
- with the guard bypassed, every transport and signer decision still follows the endpoint specification.

The byte-identity pin proves that genuine requests go out exactly as before the change: same method, URL, body,
auth headers, pre-sign text and retry count, for every allowlisted endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from edge_lab.execution import account as a
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
CREATE_ACK = (FIXTURES / "create_order_v2_response.json").read_bytes()
BALANCE_BODY = (FIXTURES / "get_balance.json").read_bytes()


class Response:
    def __init__(self, status: int, body: bytes = b"{}"):
        self.status, self._body, self._url = status, body, None

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
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        outcome._url = request.full_url
        return outcome


@pytest.fixture(scope="module")
def key():
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def signer(key):
    return s.Signer(key_id=KEY_ID, private_key=key, environment=m.Environment.FIXTURE, account_ref="fixture-acct")


def transport(signer, opener):
    return t.Transport(m.Environment.FIXTURE, signer, opener, lambda: NOW, sleep=lambda _: None)


def market():
    return c.MarketTradingProfile.from_market_record(json.loads((FIXTURES / "market_binary_active.json").read_bytes()))


def intent():
    grid = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
    return m.OrderIntent(
        intent_key="EXP-TEST:ticket-0001", strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
        market_ticker="HIGHNY-24JAN01-T60", kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
        quantity=Decimal("10"), limit_price=Decimal("0.56"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
        max_total_cost=Decimal("6.00"), expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), price_grid=grid,
        quantity_grid=c.quantity_grid("1000"), profile_version=c.PROFILE_VERSION, risk_policy_version="risk-v1",
        fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=False)


def every_endpoint() -> dict[w.Endpoint, w.WireRequest]:
    """One genuine request per allowlisted endpoint, with queries and bodies wherever the endpoint takes them."""
    i = intent()
    built = [
        w.build_create(i, market()),
        w.build_cancel(SCOPE, ORDER_ID, exchange_index=0),
        w.build_amend(i, market(), order_id=ORDER_ID, new_limit_price=Decimal("0.55"), filled_count=Decimal("0"),
                      desired_remaining=Decimal("5"), current_client_order_id=i.client_order_id()),
        w.build_decrease(SCOPE, ORDER_ID, exchange_index=0, reduce_by=Decimal("2")),
        w.build_get_order(SCOPE, ORDER_ID),
        w.build_get_orders(SCOPE, status="resting", ticker="HIGHNY-24JAN01-T60", cursor="abc", limit=5, min_ts=1,
                           max_ts=2),
        w.build_get_orders(SCOPE, historical=True, limit=7),
        w.build_get_balance(SCOPE, exchange_index=0),
        w.build_get_positions(SCOPE, settlement_status="all", limit=9),
        w.build_get_historical_positions(SCOPE, limit=3),
        w.build_get_fills(SCOPE, order_id=ORDER_ID, limit=4),
        w.build_get_fills(SCOPE, historical=True, limit=6),
        w.build_get_settlements(SCOPE, limit=8),
        w.build_get_historical_cutoff(SCOPE),
        w.build_get_exchange_status(SCOPE),
        w.build_get_user_data_timestamp(SCOPE),
    ]
    out = {r.endpoint: r for r in built}
    assert set(out) == set(w.Endpoint) and len(out) == len(built)
    return out


def priority_for(request: w.WireRequest) -> t.Priority:
    return t.Priority.PROTECTIVE if request.endpoint.value.protective else t.Priority.ORDINARY


GENUINE_METHOD = {e: e.value.method.value for e in w.Endpoint}


# ---------------------------------------------------------------------------------------------- byte identity

# sha256 of the canonical record of every genuine request on the wire, computed on main before this change
# (5c7657e). Every field that reaches the opener is in it except the signature bytes, which are verified instead
# against the pinned pre-sign text with the test-time key's public half (Ed25519 is deterministic, so a matching
# text means matching signature bytes).
WIRE_PIN = "e8b925f11326f6649e61960b3eecc6ad5e3787abb7974f5222eba31a5a8d0d9f"


def wire_record(signer, wrap=lambda request: request) -> list[dict]:
    """What reaches the opener for each endpoint's genuine request, sent as `wrap(request)`. The pre-sign text
    is always computed from the genuine request, so a lying wrapper cannot vouch for its own signature."""
    rows = []
    for endpoint, request in every_endpoint().items():
        opener = Opener(Response(500), Response(500), Response(500))  # unknown: reads retry, writes never do
        result = transport(signer, opener).send(wrap(request), priority=priority_for(request))
        sent = opener.calls[0]
        headers = {k.lower(): v for k, v in sent.header_items()}
        signature = headers.pop("kalshi-access-signature")
        presign = s.Signer.presign_text(request, NOW_MS)
        signer.public_key().verify(base64.b64decode(signature), presign.encode("utf-8"))
        for other in opener.calls[1:]:  # every retry is the same request, re-signed
            assert (other.get_method(), other.full_url, other.data) == (sent.get_method(), sent.full_url, sent.data)
        rows.append({"endpoint": endpoint.name, "method": sent.get_method(), "url": sent.full_url,
                     "body": None if sent.data is None else sent.data.decode("ascii"),
                     "headers": sorted(headers.items()), "presign": presign,
                     "attempts": len(opener.calls), "result_attempts": result.attempts,
                     "outcome": result.outcome.value, "reason": result.reason})
    return rows


def test_every_allowlisted_endpoint_goes_out_byte_identical(signer):
    rows = wire_record(signer)
    by_name = {r["endpoint"]: r for r in rows}
    for endpoint in w.Endpoint:  # the shape, stated plainly, before the digest
        row = by_name[endpoint.name]
        write = endpoint.value.bucket is w.Bucket.WRITE
        assert row["method"] == GENUINE_METHOD[endpoint]
        assert row["presign"].startswith(f"{NOW_MS}{GENUINE_METHOD[endpoint]}/trade-api/v2/")
        assert (row["attempts"], row["outcome"]) == ((1, "AMBIGUOUS") if write else (3, "UNAVAILABLE"))
        assert (row["body"] is not None) == (endpoint.value.method is w.HttpMethod.POST)
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == WIRE_PIN


# ---------------------------------------------------------------------------------------------- lying subclasses


class WriteClaimingRead(w.WireRequest):
    def is_write(self) -> bool:
        return False


class ReadClaimingWrite(w.WireRequest):
    def is_write(self) -> bool:
        return True


class ClaimsGet(w.WireRequest):
    @property
    def method(self) -> w.HttpMethod:
        return w.HttpMethod.GET


class PathElsewhere(w.WireRequest):
    @property
    def full_path(self) -> str:
        return c.API_PATH_PREFIX + "/portfolio/balance"


class QueryElsewhere(w.WireRequest):
    def query_string(self) -> str:
        return "subaccount=7"


class Liar(w.WireRequest):
    """Every overridable answer is wrong: write-ness negated, the method swapped, the path pointed at another
    allowlisted route and the query replaced."""

    def _genuine_write(self) -> bool:
        return self.endpoint.value.bucket is w.Bucket.WRITE

    def is_write(self) -> bool:
        return not self._genuine_write()

    @property
    def method(self) -> w.HttpMethod:
        return w.HttpMethod.POST if self.endpoint.value.method is w.HttpMethod.GET else w.HttpMethod.GET

    @property
    def full_path(self) -> str:
        return c.API_PATH_PREFIX + ("/portfolio/balance" if self._genuine_write() else "/portfolio/events/orders")

    def query_string(self) -> str:
        return "subaccount=7"


class Plain(w.WireRequest):
    """Overrides nothing: still not the exact type."""


@dataclass(frozen=True)
class DataclassSub(w.WireRequest):
    pass


def as_(cls, request: w.WireRequest) -> w.WireRequest:
    return cls(**{f.name: getattr(request, f.name) for f in fields(w.WireRequest)})


def balance():
    return w.build_get_balance(SCOPE)


LYING = [
    (WriteClaimingRead, lambda: every_endpoint()[w.Endpoint.ORDER_CREATE]),
    (ReadClaimingWrite, balance),
    (ClaimsGet, lambda: w.build_cancel(SCOPE, ORDER_ID, exchange_index=0)),
    (PathElsewhere, lambda: every_endpoint()[w.Endpoint.ORDER_CREATE]),
    (QueryElsewhere, lambda: every_endpoint()[w.Endpoint.GET_ORDERS]),
    (Liar, balance),
    (Plain, balance),
    (DataclassSub, balance),
]
LYING_IDS = [cls.__name__ for cls, _ in LYING]


def test_the_lying_subclasses_really_lie():
    """Guard against a vacuous suite: each subclass's overridden answer differs from the genuine one."""
    create = every_endpoint()[w.Endpoint.ORDER_CREATE]
    assert create.is_write() and not as_(WriteClaimingRead, create).is_write()
    assert not balance().is_write() and as_(ReadClaimingWrite, balance()).is_write()
    cancel = w.build_cancel(SCOPE, ORDER_ID, exchange_index=0)
    assert cancel.method is w.HttpMethod.DELETE and as_(ClaimsGet, cancel).method is w.HttpMethod.GET
    assert as_(PathElsewhere, create).full_path != create.full_path
    orders = every_endpoint()[w.Endpoint.GET_ORDERS]
    assert as_(QueryElsewhere, orders).query_string() != orders.query_string()
    for request in every_endpoint().values():
        liar = as_(Liar, request)
        assert liar.is_write() != request.is_write() and liar.method is not request.method
        assert liar.full_path != request.full_path and liar.query_string() != request.query_string()
        assert all(getattr(liar, f.name) == getattr(request, f.name) for f in fields(w.WireRequest))  # same fields


@pytest.mark.parametrize("cls,make", LYING, ids=LYING_IDS)
def test_check_allowlisted_refuses_anything_but_the_exact_type(cls, make):
    genuine = make()
    assert w.check_allowlisted(genuine) is genuine
    with pytest.raises(ValueError):
        w.check_allowlisted(as_(cls, genuine))


def test_a_subclass_built_without_init_is_refused_too():
    tampered = object.__new__(Plain)
    for f in fields(w.WireRequest):
        object.__setattr__(tampered, f.name, getattr(balance(), f.name))
    with pytest.raises(ValueError):
        w.check_allowlisted(tampered)


@pytest.mark.parametrize("cls,make", LYING, ids=LYING_IDS)
def test_signer_transport_and_account_refuse_a_lying_subclass(signer, cls, make):
    lying = as_(cls, make())
    with pytest.raises(ValueError):
        signer.sign(lying, timestamp_ms=NOW_MS)
    with pytest.raises(ValueError):
        s.Signer.presign_text(lying, NOW_MS)
    opener = Opener(Response(201, CREATE_ACK), Response(201, CREATE_ACK), Response(201, CREATE_ACK))
    with pytest.raises(t.RequestNotAllowed):
        transport(signer, opener).send(lying, priority=priority_for(lying))
    with pytest.raises(t.RequestNotAllowed):
        transport(signer, opener).send_and_parse(lying, w.parse_create_ack, priority=priority_for(lying))
    assert opener.calls == []
    with pytest.raises(a.AccountReadError):
        a.check_read_request(lying)


def test_the_package_m_probe_is_refused_before_anything_is_sent(signer):
    """The finding: an ORDER_CREATE whose subclass said `is_write() == False` went out as POST three times and was
    reported UNAVAILABLE. It is now refused before signing; nothing reaches the opener."""
    opener = Opener(Response(500), Response(500), Response(500))
    with pytest.raises(t.RequestNotAllowed):
        transport(signer, opener).send(as_(WriteClaimingRead, every_endpoint()[w.Endpoint.ORDER_CREATE]))
    assert opener.calls == []


# ---------------------------------------------------------------------------------------------- guard bypassed


def _isinstance_only(request: object) -> w.WireRequest:
    """The guard as it was before this change: any subclass passes, fields re-validated."""
    if not isinstance(request, w.WireRequest):
        raise ValueError("only a kalshi_wire.WireRequest is accepted")
    w.WireRequest(request.endpoint, request.scope, request.path, request.query, request.body, request.exchange_index)
    return request


@pytest.fixture
def bypass(monkeypatch):
    """Defence in depth: as if the exact-type check were missing. Every decision must still follow the spec."""
    monkeypatch.setattr(w, "check_allowlisted", _isinstance_only)
    assert w.check_allowlisted(as_(Liar, balance())) is not None


def test_bypassed_every_endpoint_still_goes_out_as_its_spec_says(signer, bypass):
    """Method, URL (path and query), body, auth headers, signature and retry count, for every allowlisted endpoint,
    are those of the genuine request although every overridable answer of the subclass is wrong."""
    assert wire_record(signer, lambda r: as_(Liar, r)) == wire_record(signer)


def test_bypassed_the_package_m_probe_is_sent_once_and_ambiguous(signer, bypass):
    opener = Opener(Response(500), Response(500), Response(201, CREATE_ACK))
    result = transport(signer, opener).send(as_(WriteClaimingRead, every_endpoint()[w.Endpoint.ORDER_CREATE]))
    assert result.outcome is t.Outcome.AMBIGUOUS and result.attempts == 1 and len(opener.calls) == 1
    assert opener.calls[0].get_method() == "POST"


def test_bypassed_a_read_claiming_write_is_still_retried_as_a_read(signer, bypass):
    opener = Opener(Response(500), Response(500), Response(200, BALANCE_BODY))
    result = transport(signer, opener).send(as_(ReadClaimingWrite, balance()))
    assert result.outcome is t.Outcome.OK and result.attempts == 3 and len(opener.calls) == 3


@pytest.mark.parametrize("cls,make,outcome", [
    (WriteClaimingRead, lambda: every_endpoint()[w.Endpoint.ORDER_CREATE], t.Outcome.AMBIGUOUS),
    (ReadClaimingWrite, balance, t.Outcome.UNAVAILABLE),
], ids=["write-claiming-read", "read-claiming-write"])
def test_bypassed_an_unparseable_2xx_is_classified_by_the_spec(signer, bypass, cls, make, outcome):
    opener = Opener(Response(201, b"<html>ok</html>"))
    result = transport(signer, opener).send_and_parse(as_(cls, make()), w.parse_create_ack)
    assert result.outcome is outcome and result.reason == "UNPARSEABLE_SUCCESS" and len(opener.calls) == 1


@pytest.mark.parametrize("endpoint", list(w.Endpoint), ids=lambda e: e.name)
def test_bypassed_the_signer_signs_what_the_spec_says(signer, bypass, endpoint):
    genuine = every_endpoint()[endpoint]
    liar = as_(Liar, genuine)
    text = s.Signer.presign_text(genuine, NOW_MS)
    assert text == f"{NOW_MS}{endpoint.value.method.value}{c.API_PATH_PREFIX}{genuine.path}"
    assert s.Signer.presign_text(liar, NOW_MS) == text
    for cls in (ClaimsGet, PathElsewhere):
        assert s.Signer.presign_text(as_(cls, genuine), NOW_MS) == text
    auth = signer.sign(liar, timestamp_ms=NOW_MS)
    signer.public_key().verify(base64.b64decode(auth.signature), text.encode("utf-8"))


def test_bypassed_the_account_read_guard_follows_the_spec(bypass):
    reading = as_(ReadClaimingWrite, w.build_get_balance(SCOPE))
    assert a.check_read_request(reading) is reading  # a read is a read, whatever it claims
    with pytest.raises(a.AccountReadError):
        a.check_read_request(as_(WriteClaimingRead, w.build_cancel(SCOPE, ORDER_ID, exchange_index=0)))


def test_the_spec_helpers_agree_with_the_genuine_methods():
    for request in every_endpoint().values():
        assert w.request_method(request) is request.method
        assert w.request_is_write(request) is request.is_write()
        assert w.request_full_path(request) == request.full_path
        assert w.request_query_string(request) == request.query_string()