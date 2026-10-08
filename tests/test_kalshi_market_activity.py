"""Kalshi market activity (last trade, volume, open interest): documented fields only, never fillable."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab.kalshi_quotes import ActivityState, market_activity
from edge_lab.payoff_constraints import PROHIBITED_MARKET_FIELDS

FIXTURE = Path(__file__).parent / "fixtures" / "kalshi_weather_families" / "markets_open_KXHIGHCHI_20260924T224050Z.json"
RECEIVED = "2026-09-24T22:40:50Z"  # the fixture's capture time (file name)


def _fixture_market() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["markets"][0]


def _record(**over) -> dict:
    base = {"ticker": "KXSYN-26OCT09-T1", "event_ticker": "KXSYN-26OCT09", "status": "active",
            "close_time": "2026-10-09T00:00:00Z", "last_price_dollars": "0.5600", "volume_fp": "10.00",
            "volume_24h_fp": "2.50", "open_interest_fp": "7.00", "result": "yes", "expiration_value": "42",
            "settlement_value_dollars": "1.0000", "settlement_ts": "2026-10-09T01:00:00Z",
            "previous_price_dollars": "0.9900"}
    base.update(over)
    return base


def test_documented_fixture_shape_parses_exactly():
    a = market_activity(_fixture_market(), received_at_utc=RECEIVED, prohibited_fields=())
    assert a.pre_close is True
    assert (a.last_trade_price.value, a.volume.value, a.volume_24h.value, a.open_interest.value) == (
        D("0.0100"), D("1154.73"), D("1154.73"), D("948.07"))
    assert {f.state for f in (a.last_trade_price, a.volume, a.volume_24h, a.open_interest)} == {"OBSERVED"}
    assert a.fillable is False and a.price_kind == "LAST_TRADE_NOT_EXECUTABLE"


def test_settled_fields_are_never_read_or_hashed():
    a = market_activity(_record(), received_at_utc="2026-10-08T12:00:00Z", prohibited_fields=())
    b = market_activity(_record(result="no", expiration_value="1", settlement_value_dollars="0.0000"),
                        received_at_utc="2026-10-08T12:00:00Z", prohibited_fields=())
    assert a.payload_sha256 == b.payload_sha256  # the hash does not depend on settled fields
    text = json.dumps(a.to_dict())
    assert "expiration_value" in a.fields_never_read and '"42"' not in text and "0.9900" not in text
    assert set(PROHIBITED_MARKET_FIELDS) - {"last_price_dollars"} <= set(a.fields_never_read)


@pytest.mark.parametrize("over,received", [
    ({"status": "closed"}, "2026-10-08T12:00:00Z"),
    ({"status": "finalized"}, "2026-10-08T12:00:00Z"),
    ({}, "2026-10-09T00:00:00Z"),  # at close
    ({"status": None}, "2026-10-08T12:00:00Z"),  # unknown status: fail closed
    ({"close_time": None}, "2026-10-08T12:00:00Z"),
    ({}, None),  # unknown receipt time
])
def test_last_trade_is_withheld_at_or_after_close_or_when_timing_is_unknown(over, received):
    a = market_activity(_record(**over), received_at_utc=received, prohibited_fields=())
    assert a.last_trade_price.value is None
    assert a.last_trade_price.state == ActivityState.WITHHELD_POST_CLOSE.value
    assert a.volume.value == D("10.00")  # volume is not a label proxy


def test_protocol_prohibited_fields_are_withheld():
    a = market_activity(_record(), received_at_utc="2026-10-08T12:00:00Z",
                        prohibited_fields=list(PROHIBITED_MARKET_FIELDS) + ["open_interest_fp"])
    assert a.last_trade_price.state == a.open_interest.state == ActivityState.WITHHELD_PROHIBITED.value
    assert a.last_trade_price.value is None and a.open_interest.value is None
    assert "last_price_dollars" in a.fields_never_read


@pytest.mark.parametrize("field,raw,state", [
    ("last_price_dollars", "0.0000", "NOT_A_TRADE_PRICE"),  # no trade can print at 0
    ("last_price_dollars", "1.0000", "NOT_A_TRADE_PRICE"),
    ("last_price_dollars", None, "MISSING"),
    ("last_price_dollars", 0.56, "MALFORMED"),  # a float is never trusted
    ("volume_fp", "", "MISSING"),
    ("volume_fp", "-1.00", "MALFORMED"),
    ("volume_fp", "NaN", "MALFORMED"),
    ("open_interest_fp", "abc", "MALFORMED"),
])
def test_missing_or_malformed_values_stay_unknown_never_zero(field, raw, state):
    a = market_activity(_record(**{field: raw}), received_at_utc="2026-10-08T12:00:00Z", prohibited_fields=())
    name = {"last_price_dollars": "last_trade_price", "volume_fp": "volume",
            "open_interest_fp": "open_interest"}[field]
    got = getattr(a, name)
    assert got.value is None and got.state == state
