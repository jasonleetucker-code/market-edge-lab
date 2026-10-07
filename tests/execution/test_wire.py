"""Kalshi wire format (#160 package F): deterministic builders from `OrderIntent`, strict parsers, documentation
fixtures. Pure: nothing here signs or sends."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.execution import conformance as c
from edge_lab.execution import kalshi_wire as w
from edge_lab.execution import model as m

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kalshi_exec"
UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, 30, 750000, tzinfo=UTC)
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
MILLI = m.Grid(step=Decimal("0.001"), minimum=Decimal("0.001"), maximum=Decimal("0.999"))
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
TICKER = "HIGHNY-24JAN01-T60"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture(name: str) -> dict:
    return json.loads(fixture_bytes(name))


MARKET = c.MarketTradingProfile.from_market_record(fixture("market_binary_active.json"))
LINEAR_CENT = c.MarketTradingProfile.from_market_record(
    {**fixture("market_binary_active.json"), "exchange_index": 3,
     "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}]})


def intent(**kw) -> m.OrderIntent:
    base = dict(intent_key="EXP-TEST:ticket-0001", strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
                market_ticker=TICKER, kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal("10"), limit_price=Decimal("0.56"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("6.00"), expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(),
                price_grid=CENT, quantity_grid=c.quantity_grid("1000"), profile_version=c.PROFILE_VERSION,
                risk_policy_version="risk-v1", fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=False)
    base.update(kw)
    return m.OrderIntent(**base)


def reduction(**kw) -> m.OrderIntent:
    base = dict(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=True,
                time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL, max_total_cost=Decimal("1.00"))
    base.update(kw)
    return intent(**base)


def body(request: w.WireRequest) -> dict:
    return json.loads(request.body)


# ---------------------------------------------------------------------------------------------- create


def test_create_matches_the_documented_shape_and_formats():
    doc = fixture("create_order_v2_request.json")
    req = w.build_create(intent(), MARKET)
    assert req.method is w.HttpMethod.POST and req.path == "/portfolio/events/orders"
    assert req.full_path == "/trade-api/v2/portfolio/events/orders" and req.query == ()
    got = body(req)
    assert set(got) == set(doc) | {"expiration_time"}
    for key in ("ticker", "side", "count", "price", "time_in_force", "self_trade_prevention_type", "post_only",
                "reduce_only", "subaccount", "exchange_index"):
        assert got[key] == doc[key], key  # same values and the same text formats as the official example
    assert got["client_order_id"] == intent().client_order_id()
    assert got["cancel_order_on_pause"] is True  # profile decision; the example uses false
    assert req.exchange_index == 0 and req.is_write()


def test_create_body_is_deterministic_canonical_json():
    a, b = w.build_create(intent(), MARKET), w.build_create(intent(), MARKET)
    assert a == b and a.body == b.body
    assert a.body == json.dumps(json.loads(a.body), sort_keys=True, separators=(",", ":")).encode()
    assert b"." not in re.sub(rb'"[^"]*"', b"", a.body)  # every decimal is a string, never a JSON number


@pytest.mark.parametrize("side,action,limit,book,yes_price", [
    (m.Side.YES, m.Action.BUY, "0.56", "bid", "0.5600"),
    (m.Side.NO, m.Action.BUY, "0.44", "ask", "0.5600"),
    (m.Side.YES, m.Action.SELL, "0.56", "ask", "0.5600"),
    (m.Side.NO, m.Action.SELL, "0.44", "bid", "0.5600"),
    (m.Side.NO, m.Action.BUY, "0.055", "ask", "0.9450"),  # edge band, 0.001 tick
])
def test_direction_and_yes_price_mapping(side, action, limit, book, yes_price):
    grid = MILLI if "055" in limit else CENT
    if action is m.Action.BUY:
        built = intent(side=side, limit_price=Decimal(limit), price_grid=grid, time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL)
    else:
        built = reduction(side=side, limit_price=Decimal(limit), price_grid=grid)
    got = body(w.build_create(built, MARKET))
    assert (got["side"], got["price"]) == (book, yes_price)
    assert got["reduce_only"] is (action is m.Action.SELL)


def test_expiry_is_sent_for_gtc_only_and_floored_to_seconds():
    expires = datetime(2026, 10, 7, 15, 5, 30, 999000, tzinfo=UTC)
    got = body(w.build_create(intent(expires_at_utc=expires.isoformat()), MARKET))
    assert got["expiration_time"] == int(datetime(2026, 10, 7, 15, 5, 30, tzinfo=UTC).timestamp())
    for tif in (m.TimeInForce.IMMEDIATE_OR_CANCEL, m.TimeInForce.FILL_OR_KILL):
        assert "expiration_time" not in body(w.build_create(intent(time_in_force=tif), MARKET))


@pytest.mark.parametrize("tif", [m.TimeInForce.GOOD_TILL_CANCELED, m.TimeInForce.FILL_OR_KILL])
def test_reduce_only_requires_ioc(tif):
    with pytest.raises(c.UnsupportedByProfile):
        w.build_create(reduction(time_in_force=tif), MARKET)


def test_a_yes_price_off_the_market_grid_is_refused():
    no_intent = intent(side=m.Side.NO, limit_price=Decimal("0.555"), price_grid=MILLI)
    with pytest.raises(c.UnsupportedByProfile):
        w.build_create(no_intent, LINEAR_CENT)  # 1 - 0.555 = 0.445 is not on a 0.01 grid


def test_the_intent_must_match_the_profile_and_the_market():
    with pytest.raises(c.UnsupportedByProfile):
        w.build_create(intent(profile_version="kalshi-ordinary-v1"), MARKET)
    with pytest.raises(ValueError):
        w.build_create(intent(market_ticker="OTHER-TICKER"), MARKET)
    with pytest.raises(ValueError):
        w.build_create(intent(), fixture("market_binary_active.json"))  # a raw record is not a checked profile


def test_subaccount_is_always_explicit():
    assert body(w.build_create(intent(), MARKET))["subaccount"] == 0
    sub = m.AccountScope(m.Environment.FIXTURE, "fixture-acct", subaccount=7)
    assert body(w.build_create(intent(scope=sub), MARKET))["subaccount"] == 7
    with pytest.raises(c.UnsupportedByProfile):
        w.build_create(intent(scope=m.AccountScope(m.Environment.FIXTURE, "fixture-acct", subaccount=64)), MARKET)


def test_the_shard_comes_from_the_market_record():
    req = w.build_create(intent(), LINEAR_CENT)
    assert body(req)["exchange_index"] == 3 and req.exchange_index == 3


@pytest.mark.parametrize("value,places", [(Decimal("0.12345"), 4), (Decimal("1.005"), 2)])
def test_text_formats_never_round(value, places):
    with pytest.raises(c.UnsupportedByProfile):
        (w.price_text if places == 4 else w.count_text)(value)
    assert w.price_text(Decimal("0.5")) == "0.5000" and w.count_text(Decimal("3")) == "3.00"


# ---------------------------------------------------------------------------------------------- cancel, amend, decrease

ORDER_ID = "3b23c1c7-f4ef-4f0d-8b9a-9e53c61f1a0d"


def test_cancel_names_subaccount_and_shard():
    req = w.build_cancel(SCOPE, ORDER_ID, exchange_index=2)
    assert req.method is w.HttpMethod.DELETE and req.body is None
    assert req.path == f"/portfolio/events/orders/{ORDER_ID}"
    assert req.query == (("exchange_index", "2"), ("subaccount", "0")) and req.exchange_index == 2
    assert req.endpoint.value.protective


@pytest.mark.parametrize("bad", ["../balance", "a/b", "a?b=1", "", "x" * 65, "a b", "%2e%2e"])
def test_order_ids_cannot_escape_the_template(bad):
    with pytest.raises(ValueError):
        w.build_cancel(SCOPE, bad, exchange_index=0)
    with pytest.raises(ValueError):
        w.build_get_order(SCOPE, bad)


@pytest.mark.parametrize("shard", [None, -1, True, "0"])
def test_cancel_requires_an_explicit_shard(shard):
    with pytest.raises(ValueError):
        w.build_cancel(SCOPE, ORDER_ID, exchange_index=shard)


def test_amend_count_is_filled_plus_desired_remaining():
    doc = fixture("amend_order_v2_request.json")
    req = w.build_amend(intent(), MARKET, order_id=ORDER_ID, new_limit_price=Decimal("0.55"),
                        filled_count=Decimal("2"), desired_remaining=Decimal("6"),
                        current_client_order_id=intent().client_order_id(),
                        updated_client_order_id="2a0e3fc9-b593-4aa3-96e5-82f7f7566c2a")
    got = body(req)
    assert set(got) == set(doc)
    assert got["count"] == "8.00" and got["price"] == "0.5500" and got["side"] == "bid"
    assert got["client_order_id"] == intent().client_order_id()
    assert req.path == f"/portfolio/events/orders/{ORDER_ID}/amend" and req.query == (("subaccount", "0"),)


AMEND = dict(order_id=ORDER_ID, new_limit_price=Decimal("0.55"), filled_count=Decimal("0"),
             desired_remaining=Decimal("5"))
UPDATED_ID = "2a0e3fc9-b593-4aa3-96e5-82f7f7566c2a"


def test_a_later_amend_sends_the_updated_client_order_id():
    first = body(w.build_amend(intent(), MARKET, **AMEND, current_client_order_id=intent().client_order_id(),
                               updated_client_order_id=UPDATED_ID))
    second = body(w.build_amend(intent(), MARKET, **{**AMEND, "new_limit_price": Decimal("0.54")},
                                current_client_order_id=UPDATED_ID))
    assert first["client_order_id"] == intent().client_order_id() and first["updated_client_order_id"] == UPDATED_ID
    assert second["client_order_id"] == UPDATED_ID and "updated_client_order_id" not in second
    with pytest.raises(TypeError):  # the current id is required: the original cannot be sent by default
        w.build_amend(intent(), MARKET, **AMEND)  # type: ignore[call-arg]
    for bad in ("", "has space", None, 7):
        with pytest.raises(ValueError):
            w.build_amend(intent(), MARKET, **AMEND, current_client_order_id=bad)
    with pytest.raises(ValueError):
        w.build_amend(intent(), MARKET, **AMEND, current_client_order_id=UPDATED_ID, updated_client_order_id=UPDATED_ID)


@pytest.mark.parametrize("kw", [
    dict(new_limit_price=Decimal("0.57")),  # a buy made more aggressive than approved
    dict(filled_count=Decimal("5"), desired_remaining=Decimal("6")),  # above the approved quantity
])
def test_amend_never_exceeds_the_approved_intent(kw):
    args = {**AMEND, "current_client_order_id": intent().client_order_id(), **kw}
    with pytest.raises(c.UnsupportedByProfile):
        w.build_amend(intent(), MARKET, **args)


def test_amend_refuses_zero_remaining_float_and_non_resting_orders():
    args = dict(order_id=ORDER_ID, new_limit_price=Decimal("0.55"), filled_count=Decimal("0"),
                current_client_order_id=intent().client_order_id())
    with pytest.raises(ValueError):
        w.build_amend(intent(), MARKET, desired_remaining=Decimal("0"), **args)
    with pytest.raises(ValueError):
        w.build_amend(intent(), MARKET, desired_remaining=5.0, **args)
    with pytest.raises(c.UnsupportedByProfile):
        w.build_amend(intent(time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL), MARKET,
                      desired_remaining=Decimal("1"), **args)


def test_a_reduction_cannot_rest_so_it_cannot_be_amended():
    with pytest.raises(c.UnsupportedByProfile):
        w.build_amend(reduction(limit_price=Decimal("0.50")), MARKET, order_id=ORDER_ID,
                      new_limit_price=Decimal("0.55"), filled_count=Decimal("0"), desired_remaining=Decimal("1"),
                      current_client_order_id=reduction().client_order_id())


def test_decrease_sends_reduce_by_only():
    doc = fixture("decrease_order_v2_request.json")
    req = w.build_decrease(SCOPE, ORDER_ID, exchange_index=0, reduce_by=Decimal("2"))
    assert body(req) == doc and req.endpoint.value.protective
    for kw in (dict(reduce_by=Decimal("0")), dict(reduce_by=Decimal("-1")), dict(reduce_by=2)):
        with pytest.raises(ValueError):
            w.build_decrease(SCOPE, ORDER_ID, exchange_index=0, **kw)
    with pytest.raises(TypeError):
        w.build_decrease(SCOPE, ORDER_ID, exchange_index=0)  # type: ignore[call-arg]


def test_reduce_to_is_unknown_so_it_is_never_built_or_sent():
    with pytest.raises(c.UnsupportedByProfile):
        w.build_decrease(SCOPE, ORDER_ID, exchange_index=0, reduce_by=Decimal("1"), reduce_to=Decimal("0"))
    for raw in (b'{"exchange_index":0,"reduce_to":"0.00"}', b'{"exchange_index":0,"reduce_by":"1.00","reduce_to":"0.00"}'):
        with pytest.raises(ValueError):  # a hand-built request cannot smuggle it into protective capacity
            w.WireRequest(w.Endpoint.ORDER_DECREASE, SCOPE, f"/portfolio/events/orders/{ORDER_ID}/decrease",
                          (("subaccount", "0"),), body=raw, exchange_index=0)
    facts = {f.id: f for f in w.ENDPOINT_FACTS}
    assert facts["ORD-34"].support is c.Support.UNKNOWN


# ---------------------------------------------------------------------------------------------- reads


def test_reads_are_canonical_and_always_name_the_subaccount():
    req = w.build_get_positions(SCOPE, settlement_status="all", cursor="abc", limit=50, ticker=TICKER)
    assert req.method is w.HttpMethod.GET and req.body is None and not req.is_write()
    assert req.query == (("cursor", "abc"), ("limit", "50"), ("settlement_status", "all"), ("subaccount", "0"),
                         ("ticker", TICKER))
    assert req.query_string() == f"cursor=abc&limit=50&settlement_status=all&subaccount=0&ticker={TICKER}"
    for build in (w.build_get_balance, w.build_get_orders, w.build_get_fills, w.build_get_settlements,
                  w.build_get_historical_positions):
        assert ("subaccount", "0") in build(SCOPE).query, build.__name__


def test_positions_require_an_explicit_settlement_status():
    with pytest.raises(TypeError):
        w.build_get_positions(SCOPE)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        w.build_get_positions(SCOPE, settlement_status="archived")


def test_historical_reads_use_their_own_endpoints():
    assert w.build_get_orders(SCOPE, historical=True).path == "/historical/orders"
    assert w.build_get_fills(SCOPE, historical=True).path == "/historical/fills"
    assert w.build_get_historical_positions(SCOPE).path == "/historical/positions"
    assert w.build_get_historical_cutoff(SCOPE).path == "/historical/cutoff"
    with pytest.raises(ValueError):
        w.build_get_orders(SCOPE, historical=True, status="resting")


@pytest.mark.parametrize("kw", [dict(limit=101), dict(limit=0), dict(limit=True), dict(cursor="a b"),
                                dict(cursor=""), dict(min_ts=-1), dict(max_ts=1.5), dict(status="open")])
def test_read_parameters_are_validated(kw):
    with pytest.raises(ValueError):
        w.build_get_orders(SCOPE, **kw)


@pytest.mark.parametrize("make", [
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/positions"),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance?subaccount=0"),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", (("evil", "1"),)),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", (("subaccount", "0"), ("exchange_index", "1"))),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", (("subaccount", "0"), ("subaccount", "1"))),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", (("subaccount", "a b"),)),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", body=b"{}"),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, SCOPE, "/portfolio/balance", exchange_index=0),
    lambda: w.WireRequest(w.Endpoint.ORDER_CREATE, SCOPE, "/portfolio/events/orders", body=b'{"a": 1}', exchange_index=0),
    lambda: w.WireRequest(w.Endpoint.ORDER_CREATE, SCOPE, "/portfolio/events/orders", body=b'{"a":1.5}', exchange_index=0),
    lambda: w.WireRequest(w.Endpoint.ORDER_CREATE, SCOPE, "/portfolio/events/orders", body=b'{"a":1}'),
    lambda: w.WireRequest(w.Endpoint.ORDER_CREATE, SCOPE, "/portfolio/events/orders", exchange_index=0),
    lambda: w.WireRequest(w.Endpoint.ORDER_CANCEL, SCOPE, "/portfolio/events/orders/../balance", exchange_index=0),
    lambda: w.WireRequest("ORDER_CREATE", SCOPE, "/portfolio/events/orders"),
    lambda: w.WireRequest(w.Endpoint.GET_BALANCE, "FIXTURE:acct", "/portfolio/balance"),
])
def test_a_wire_request_off_the_allowlist_cannot_be_built(make):
    with pytest.raises(ValueError):
        make()


def test_check_allowlisted_accepts_only_wire_requests():
    req = w.build_get_balance(SCOPE)
    assert w.check_allowlisted(req) is req
    with pytest.raises(ValueError):
        w.check_allowlisted({"path": "/portfolio/balance"})


def test_the_allowlist_has_only_get_post_delete_and_documented_paths():
    specs = [e.value for e in w.Endpoint]
    assert len(specs) == len(w.Endpoint.__members__) == 16  # no two endpoints alias one another
    assert {s.method for s in specs} == {w.HttpMethod.GET, w.HttpMethod.POST, w.HttpMethod.DELETE}
    assert {e.name for e in w.Endpoint if e.value.bucket is w.Bucket.WRITE} == {
        "ORDER_CREATE", "ORDER_CANCEL", "ORDER_AMEND", "ORDER_DECREASE"}
    assert not any(e.value.protective for e in (w.Endpoint.ORDER_CREATE, w.Endpoint.ORDER_AMEND))
    assert all(s.template.startswith(("/portfolio/", "/historical/", "/exchange/")) for s in specs)
    assert not any("/portfolio/orders" == s.template and s.method is not w.HttpMethod.GET for s in specs)  # ORD-02


# ---------------------------------------------------------------------------------------------- parsers: fixtures


def test_documentation_example_responses_parse():
    create = w.parse_create_ack(fixture_bytes("create_order_v2_response.json"))
    assert create.order_id == ORDER_ID and create.fill_count == Decimal("0") and create.remaining_count == Decimal("10")
    assert create.average_fill_price is None and create.ts_ms == 1715793600123
    cancel = w.parse_cancel_ack(fixture_bytes("cancel_order_v2_response.json"))
    assert cancel.reduced_by == Decimal("10.00") and cancel.ts_ms == 1715793660456
    amend = w.parse_amend_ack(fixture_bytes("amend_order_v2_response.json"))
    assert amend.remaining_count == Decimal("8") and amend.fill_count == Decimal("0")
    assert amend.client_order_id == "2a0e3fc9-b593-4aa3-96e5-82f7f7566c2a"
    decrease = w.parse_decrease_ack(fixture_bytes("decrease_order_v2_response.json"))
    assert decrease.remaining_count == Decimal("8")
    assert w.parse_error(fixture_bytes("rate_limited_429.json")).error == "too many requests"


def test_schema_constructed_reads_parse_to_exact_values():
    page = w.parse_orders_page(fixture_bytes("get_orders_page.json"))
    order = page.items[0]
    assert page.cursor == "fixture-cursor-2" and order.status == "resting" and order.book_side == "bid"
    assert order.fill_count == Decimal("2.50") and order.maker_fees == Decimal("0.012250")
    assert order.expiration_time is None and order.created_time == datetime(2026, 10, 7, 15, tzinfo=UTC)
    assert set(order.extra) == {"side", "action"}  # deprecated legacy fields kept, never interpreted
    assert w.parse_order(fixture_bytes("get_order.json")) == order
    fills = w.parse_fills_page(fixture_bytes("get_fills_page.json"))
    assert fills.cursor is None and fills.items[0].fee_cost == Decimal("0.012250") and fills.items[0].is_taker is False
    positions = w.parse_positions_page(fixture_bytes("get_positions_page.json"))
    assert positions.market_positions[0].position == Decimal("-2.50") and positions.cursor is None
    settlements = w.parse_settlements_page(fixture_bytes("get_settlements_page.json"))
    s = settlements.items[0]
    assert s.revenue_cents == 250 and s.value_cents == 100 and s.fee_cost == Decimal("0.34") and s.market_result == "yes"
    balance = w.parse_balance(fixture_bytes("get_balance.json"))
    assert balance.balance_cents == 10000 and balance.balance_dollars == Decimal("100") and balance.updated_ts == 1791385205
    assert balance.breakdown == ((0, Decimal("100")),)
    cutoff = w.parse_historical_cutoff(fixture_bytes("historical_cutoff.json"))
    assert cutoff.market_positions_last_updated == datetime(2026, 8, 25, tzinfo=UTC)
    status = w.parse_exchange_status(fixture_bytes("exchange_status.json"))
    assert status.exchange_active and not status.trading_active and status.index_statuses == ((0, True, False),)
    assert w.parse_user_data_timestamp(b'{"as_of_time": "2026-10-07T15:00:00Z"}') == datetime(2026, 10, 7, 15, tzinfo=UTC)


def _drop(name: str, key: str, path: tuple = ()) -> bytes:
    obj = fixture(name)
    target = obj
    for step in path:
        target = target[step]
    del target[key]
    return json.dumps(obj).encode()


_REQUIRED = [
    ("create_order_v2_response.json", w.parse_create_ack, (), ("order_id", "fill_count", "remaining_count", "ts_ms")),
    ("cancel_order_v2_response.json", w.parse_cancel_ack, (), ("order_id", "reduced_by", "ts_ms")),
    ("amend_order_v2_response.json", w.parse_amend_ack, (), ("order_id", "ts_ms")),
    ("decrease_order_v2_response.json", w.parse_decrease_ack, (), ("order_id", "remaining_count", "ts_ms")),
    ("get_orders_page.json", w.parse_orders_page, ("orders", 0),
     ("order_id", "user_id", "client_order_id", "ticker", "outcome_side", "book_side", "type", "status",
      "yes_price_dollars", "no_price_dollars", "fill_count_fp", "remaining_count_fp", "initial_count_fp",
      "taker_fees_dollars", "maker_fees_dollars", "taker_fill_cost_dollars", "maker_fill_cost_dollars")),
    ("get_orders_page.json", w.parse_orders_page, (), ("orders", "cursor")),
    ("get_fills_page.json", w.parse_fills_page, ("fills", 0),
     ("fill_id", "exchange_index", "trade_id", "order_id", "ticker", "market_ticker", "outcome_side", "book_side",
      "count_fp", "yes_price_dollars", "no_price_dollars", "is_taker", "fee_cost")),
    ("get_positions_page.json", w.parse_positions_page, ("market_positions", 0),
     ("ticker", "exchange_index", "total_traded_dollars", "position_fp", "market_exposure_dollars",
      "realized_pnl_dollars", "fees_paid_dollars", "last_updated_ts")),
    ("get_positions_page.json", w.parse_positions_page, (), ("market_positions", "event_positions")),
    ("get_settlements_page.json", w.parse_settlements_page, ("settlements", 0),
     ("ticker", "exchange_index", "event_ticker", "market_result", "yes_count_fp", "yes_total_cost_dollars",
      "no_count_fp", "no_total_cost_dollars", "revenue", "settled_time", "fee_cost")),
    ("get_balance.json", w.parse_balance, (), ("balance", "balance_dollars", "portfolio_value", "updated_ts")),
    ("historical_cutoff.json", w.parse_historical_cutoff, (), ("market_settled_ts", "trades_created_ts",
                                                                "orders_updated_ts")),
    ("exchange_status.json", w.parse_exchange_status, (), ("exchange_active", "trading_active")),
]


@pytest.mark.parametrize("name,parse,path,key", [(n, p, path, k) for n, p, path, keys in _REQUIRED for k in keys])
def test_a_missing_required_field_raises_never_defaults_to_zero(name, parse, path, key):
    parse(fixture_bytes(name))  # the fixture itself is valid
    with pytest.raises(w.WireFormatError):
        parse(_drop(name, key, path))


def test_a_null_required_field_raises():
    obj = fixture("create_order_v2_response.json")
    obj["remaining_count"] = None
    with pytest.raises(w.WireFormatError):
        w.parse_create_ack(json.dumps(obj).encode())


@pytest.mark.parametrize("value", [0, 10.0, "1e1", "10.000", " 10.00", "+10.00", "NaN", "10,00", True, [], {}])
def test_mixed_units_and_malformed_numbers_are_refused(value):
    obj = fixture("create_order_v2_response.json")
    obj["remaining_count"] = value
    with pytest.raises(w.WireFormatError):
        w.parse_create_ack(json.dumps(obj).encode())


@pytest.mark.parametrize("value", ["10000", 100.0, True, None])
def test_integer_cent_fields_must_be_integers(value):
    obj = fixture("get_balance.json")
    obj["balance"] = value
    with pytest.raises(w.WireFormatError):
        w.parse_balance(json.dumps(obj).encode())


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b'"x"', b"\xff\xfe", b"{", b'{"order_id": NaN}',
                                 b'{"order_id": "a", "order_id": "b", "fill_count": "0", "remaining_count": "1", '
                                 b'"ts_ms": 1}', "not bytes"])
def test_malformed_documents_are_refused(raw):
    with pytest.raises(w.WireFormatError):
        w.parse_create_ack(raw)


def test_unknown_extra_fields_are_preserved_not_rejected():
    obj = fixture("create_order_v2_response.json")
    obj["future_field"] = {"nested": [1, 2]}
    ack = w.parse_create_ack(json.dumps(obj).encode())
    assert ack.extra["future_field"] == {"nested": [1, 2]}
    with pytest.raises(TypeError):
        ack.extra["x"] = 1  # read-only


def test_optional_amend_counts_stay_none_when_absent():
    ack = w.parse_amend_ack(b'{"order_id": "o-1", "ts_ms": 1715793690123}')
    assert ack.remaining_count is None and ack.fill_count is None  # not reported, never "zero"


def test_a_reported_fill_without_its_price_is_refused():
    obj = fixture("create_order_v2_response.json")
    obj["fill_count"] = "2.00"
    with pytest.raises(w.WireFormatError):
        w.parse_create_ack(json.dumps(obj).encode())


@pytest.mark.parametrize("change", [{"status": "open"}, {"status": "pending"}, {"outcome_side": "no"},
                                    {"book_side": "ask"}, {"type": "stop"}, {"fill_count_fp": "-1.00"},
                                    {"created_time": "2026-10-07T15:00:00"}, {"created_time": "yesterday"},
                                    {"self_trade_prevention_type": "none"}])
def test_order_records_are_checked_against_the_documented_vocabulary(change):
    obj = fixture("get_orders_page.json")
    obj["orders"][0].update(change)
    with pytest.raises(w.WireFormatError):
        w.parse_orders_page(json.dumps(obj).encode())


@pytest.mark.parametrize("change", [{"trade_id": "f-0002"}, {"market_ticker": "OTHER"}, {"is_taker": "false"}])
def test_fill_identity_fields_must_agree(change):
    obj = fixture("get_fills_page.json")
    obj["fills"][0].update(change)
    with pytest.raises(w.WireFormatError):
        w.parse_fills_page(json.dumps(obj).encode())


def test_settlement_result_vocabulary_is_closed():
    obj = fixture("get_settlements_page.json")
    obj["settlements"][0]["market_result"] = "void"
    with pytest.raises(w.WireFormatError):
        w.parse_settlements_page(json.dumps(obj).encode())


def test_error_bodies_are_read_tolerantly():
    assert w.parse_error(b"<html>bad gateway</html>") == w.VenueError(None, None, None, None)
    assert w.parse_error(b'{"code": "x", "message": 5}') == w.VenueError("x", None, None, None)


# ---------------------------------------------------------------------------------------------- fixture inventory


def test_every_fixture_is_labelled_and_every_documentation_example_is_used():
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| `([^`]+)` \| (documentation-example|schema-constructed) \|", readme, re.M))
    files = {p.name for p in FIXTURES.glob("*.json")}
    assert set(rows) == files
    here = Path(__file__).read_text(encoding="utf-8")
    for name, label in rows.items():
        if label == "documentation-example":
            assert f'"{name}"' in here, f"{name} is not exercised"
