"""W2: the strict Polymarket Data API v2 parser on documentation-shaped fixtures (no network)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from wallet_support import FIXTURES, at, fixture

from edge_lab.wallet_intel import polymarket_v2 as pm
from edge_lab.wallet_intel.events import Action, ChainFinality

RECEIPT = at(days=30)


def test_v1_retirement_and_routes_are_pinned():
    assert pm.V1_RETIREMENT_DATE == "2026-10-24"
    assert pm.SOURCE == "polymarket_data_api_v2" and pm.CHAIN == "polygon:137"


def test_numbers_become_decimals_and_floats_are_refused():
    page = pm.parse_activity_page(fixture("activity_page1.json"), receipt_time=RECEIPT, synthetic=True)
    first = page.observations[0]
    assert isinstance(first.native_quantity, Decimal) and first.price == Decimal("0.48")
    assert first.paid[0].quantity == Decimal("4.8")
    floaty = json.loads(fixture("activity_page1.json"))  # decoded with floats
    with pytest.raises(pm.V2ParseError, match="binary float"):
        pm.activity_observation(floaty["data"][0], index=0, page_sha256="x", receipt_time=RECEIPT, synthetic=True)
    with pytest.raises(pm.V2ParseError):
        pm.decode('{"data": [NaN]}')


def test_rows_carry_unknown_fee_unknown_finality_and_no_profile_text():
    page = pm.parse_activity_page(fixture("activity_page1.json"), receipt_time=RECEIPT, synthetic=True)
    for o in page.observations:
        assert not o.fee.known and o.finality is ChainFinality.UNKNOWN
        assert o.source_event_id is None and o.sub_index is None
        assert o.raw_ref.startswith("sha256:") and o.parser_version == pm.PARSER_VERSION
        assert "Pseudonym" not in repr(o)  # profile fields are validated, then dropped


def test_type_mapping_is_conservative():
    page = pm.parse_activity_page(fixture("activity_page1.json"), receipt_time=RECEIPT, synthetic=True)
    assert [o.action for o in page.observations] == [Action.TRADE_BUY] * 3 + [Action.SPLIT, Action.REWARD]
    split = page.observations[3]
    assert "LEGS_NOT_ITEMIZED" in split.ambiguities and split.received == ()
    unknown = pm.parse_activity_page(fixture("activity_unknown_type.json"), receipt_time=RECEIPT, synthetic=True)
    assert unknown.observations[0].action is Action.UNKNOWN
    assert "UNRECOGNIZED_TYPE:SOMETHING_NEW" in unknown.observations[0].ambiguities
    sideless = pm.parse_activity_page(fixture("activity_trade_without_side.json"), receipt_time=RECEIPT,
                                      synthetic=True)
    assert sideless.observations[0].action is Action.UNKNOWN and not sideless.observations[0].directional
    tip = pm.parse_activity_page(fixture("activity_page2.json"), receipt_time=RECEIPT, synthetic=True).observations[-1]
    assert tip.action is Action.TRANSFER_IN and tip.outcome_index is None and "OUTCOME_UNLABELABLE" in tip.ambiguities


def test_overview_pagination_shape_with_limit_and_offset_is_accepted():
    page = pm.parse_activity_page(fixture("activity_overview_pagination_shape.json"), receipt_time=RECEIPT,
                                  synthetic=True)
    assert page.page.next_cursor is None and page.page.unrecognized_fields == ()


def test_page_limit_and_parse_errors_are_incomplete_walks():
    pages = {None: (200, fixture("activity_page1.json"), {}),
             "c2-synthetic-opaque": (200, fixture("activity_page2.json"), {})}
    w = pm.walk(lambda c: pages[c], receipt_time=RECEIPT, synthetic=True, max_pages=1)
    assert w.stop is pm.WalkStop.PAGE_LIMIT and not pm.history_complete(w, start_param=1)
    bad = {None: (200, fixture("activity_missing_usdc_size.json"), {})}
    w = pm.walk(lambda c: bad[c], receipt_time=RECEIPT, synthetic=True, max_pages=3)
    assert w.stop is pm.WalkStop.PARSE_ERROR and "usdc_size" in w.detail
    malformed_error = {None: (400, fixture("error_missing_code.json"), {})}
    w = pm.walk(lambda c: malformed_error[c], receipt_time=RECEIPT, synthetic=True, max_pages=3)
    assert w.stop is pm.WalkStop.PARSE_ERROR


def test_error_status_must_match_documented_code():
    err = pm.parse_error(500, fixture("error_429_rate_limited.json"))
    assert not err.status_matches_code
    with pytest.raises(pm.V2ParseError):
        pm.parse_error(429, fixture("error_429_rate_limited.json"), retry_after="soon")


def test_positions_vendor_values_are_kept_apart():
    _, rows = pm.parse_positions_page(fixture("positions_page.json"))
    assert rows[0].vendor_reported["realized_pnl"] == Decimal("1.8")
    assert not hasattr(rows[0], "realized_pnl")  # never a first-class P&L field


def test_trades_page_parses_documented_subset():
    page = pm.parse_trades_page(fixture("trades_page.json"), receipt_time=RECEIPT, synthetic=True)
    (o,) = page.observations
    assert o.action is Action.TRADE_BUY and o.native_quantity == 4 and o.paid[0].quantity == Decimal("1.2")


def test_every_fixture_is_classified_in_the_manifest():
    manifest = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
    names = sorted(p.name for p in FIXTURES.glob("*.json") if p.name != "MANIFEST.json")
    assert sorted(manifest["fixtures"]) == names
    assert manifest["retrieved"] == "2026-10-07" and "SYNTHETIC" in manifest["statement"]
    assert set(manifest["fixtures"].values()) <= {"DOCUMENTED_SHAPE", "DOCUMENTED_ERROR_SCHEMA", "NEGATIVE_CASE"}


def test_fixtures_hold_no_real_looking_addresses():
    for p in FIXTURES.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        for token in json.dumps(json.loads(text)).split('"'):
            if token.startswith("0x") and len(token) == 42:
                assert token.startswith("0x" + "0" * 30), (p.name, token)  # synthetic, near-zero
