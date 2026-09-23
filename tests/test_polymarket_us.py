"""Polymarket US public-data adapter: fixtures only (the live smoke capture and documented examples)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import ScriptedOpener, http_error
from edge_lab import polymarket_us as pm, venues
from edge_lab.discovery import CoverageState
from edge_lab.fee_schedules import schedule_for
from edge_lab.opportunity import MarketStatus, Policy, evaluate
from edge_lab.venues import Capability, ConnectivityStage

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket_us"
SMOKE = FIXTURES / "markets_limit5_2026-09-23T140738Z.json"
SMOKE_SHA256 = "55de7665830ee28c8653da2b952a670a8d8b79c710c7c26e82d854768dab2900"
BOOK = json.loads((FIXTURES / "book_documented_example.json").read_text())
BBO = json.loads((FIXTURES / "bbo_documented_example.json").read_text())
EVENTS = json.loads((FIXTURES / "events_schema_constructed.json").read_text())
UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


class Pacer:
    def wait(self) -> None:
        pass


def test_smoke_capture_is_the_recorded_bytes():
    assert hashlib.sha256(SMOKE.read_bytes()).hexdigest() == SMOKE_SHA256
    note = (REPO / "experiments/multi_venue/polymarket_us_smoke_2026-09-23.md").read_text()
    assert SMOKE_SHA256 in note and "https://gateway.polymarket.us/v1/markets?limit=5" in note


def test_smoke_markets_map_to_generic_markets_without_rule_equivalence():
    rows = pm.parse_markets_page(json.loads(SMOKE.read_text()))
    assert len(rows) == 5
    market, meta = pm.market_from_polymarket(rows[0])
    assert market.venue == "polymarket_us" and market.market_id == "polymarket_us:aec-nfl-lac-ten-2025-11-02"
    assert market.native_id == "aec-nfl-lac-ten-2025-11-02"
    assert market.outcome == "Chargers" and meta.short_side == "Titans"  # the long (YES) side
    assert market.status is MarketStatus.CLOSED and meta.status_raw == "MARKET_STATUS_RESOLVED"
    assert market.rules_resolved is False and "not established" in market.rules_detail
    assert market.rules_sha256 == hashlib.sha256(rows[0]["description"].encode()).hexdigest()
    assert market.event_id == "unmapped:polymarket_us:aec-nfl-lac-ten-2025-11-02"
    assert meta.fee_coefficient_raw == "0.0695" and meta.minimum_trade_qty_raw == "1"
    assert meta.end_date_raw == "2025-11-03T18:00:00Z"
    # The docs do not define endDate as close or resolution time: timing stays unknown.
    t = market.timing
    assert (t.close_time_utc, t.expected_resolution_utc, t.latest_resolution_utc, t.settlement_timer_seconds) == \
        (None, None, None, None)
    assert t.lifecycle_status == "resolved"
    assert pm.lifecycle_word("MARKET_STATUS_OPEN") == "open" and pm.lifecycle_word(None) is None


@pytest.mark.parametrize("status,expected", [("MARKET_STATUS_OPEN", MarketStatus.OPEN),
                                             ("MARKET_STATUS_RESOLVING", MarketStatus.CLOSED),
                                             ("MARKET_STATUS_HALTED", MarketStatus.CLOSED),
                                             ("MARKET_STATUS_UNSPECIFIED", MarketStatus.UNKNOWN),
                                             ("MARKET_STATUS_SOMETHING_NEW", MarketStatus.UNKNOWN),
                                             (None, MarketStatus.UNKNOWN)])
def test_status_mapping_fails_to_unknown(status, expected):
    assert pm.status_of({"status": status}) is expected


def test_crypto_window_end_is_the_only_timing_taken():
    raw = {"slug": "btc-above", "status": "MARKET_STATUS_OPEN",
           "assetPriceTerms": {"windowEnd": "2026-09-21T21:00:00Z"}, "endDate": "2026-09-30T00:00:00Z"}
    market, _ = pm.market_from_polymarket(raw)
    assert market.timing.event_end_utc == "2026-09-21T21:00:00Z"
    assert market.timing.expected_resolution_utc is None


def test_events_give_identity_and_venue_local_settlement_identity():
    (raw_event,) = pm.parse_events_page(EVENTS)
    event, mapping = pm.event_from_polymarket(raw_event)
    assert event.event_id == "polymarket_us:aec-nfl-kc-phi-2026-02-09"
    assert event.target_date == "2026-02-09" and event.target_time_utc == "2026-02-09T23:30:00Z"
    assert event.settlement_identity.startswith("polymarket_us:unverified:")
    market, _ = pm.market_from_polymarket(raw_event["markets"][0], event_id_for_market=mapping)
    assert market.event_id == event.event_id and market.status is MarketStatus.OPEN


def test_book_gives_executable_quotes_with_explicit_units():
    quotes = pm.quotes_from_book("will-team-a-win", BOOK, received_at_utc="2025-01-20T12:30:46Z", evidence_id="ev")
    yes, no = quotes["YES"], quotes["NO"]
    assert (yes.best_ask, yes.displayed_size, yes.best_bid) == (Decimal("0.56"), Decimal("750"), Decimal("0.55"))
    # Buying NO is selling YES at the best bid.
    assert (no.best_ask, no.displayed_size, no.best_bid) == (Decimal("0.45"), Decimal("1000"), Decimal("0.44"))
    assert yes.source_timestamp_utc == "2025-01-20T12:30:45.123Z" and yes.anomaly is None
    assert "contracts" in pm.QUANTITY_UNIT and "USD" in pm.PRICE_UNIT


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d["marketData"].update(bids=[{"px": {"value": "0.60", "currency": "USD"}, "qty": "1"}]), "crossed"),
    (lambda d: d["marketData"].update(offers=[{"px": {"value": "abc", "currency": "USD"}, "qty": "1"}]), "malformed"),
    (lambda d: d["marketData"].update(offers=[{"px": {"value": "0.5", "currency": "EUR"}, "qty": "1"}]), "malformed"),
    (lambda d: d["marketData"].update(offers=[{"px": {"value": "1.5", "currency": "USD"}, "qty": "1"}]), "malformed"),
    (lambda d: d["marketData"].update(offers=[{"px": {"value": "0.5", "currency": "USD"}, "qty": "-1"}]), "malformed"),
    (lambda d: d["marketData"].update(state="MARKET_STATE_HALTED"), "not open"),
    (lambda d: d["marketData"].update(marketSlug="another"), "book is for"),
])
def test_bad_books_are_flagged_never_priced(mutate, expect):
    book = json.loads(json.dumps(BOOK))
    mutate(book)
    quotes = pm.quotes_from_book("will-team-a-win", book, received_at_utc=None, evidence_id=None)
    assert all(expect in (q.anomaly or "") for q in quotes.values())


def test_missing_book_and_bbo_never_become_quotes():
    assert pm.quotes_from_book("x", None, received_at_utc=None, evidence_id=None) == {}
    assert pm.quotes_from_book("x", {"marketData": None}, received_at_utc=None, evidence_id=None) == {}
    bbo = pm.bbo_summary("will-team-a-win", BBO)
    assert (bbo.best_bid, bbo.best_ask, bbo.executable) == (Decimal("0.54"), Decimal("0.56"), False)
    assert bbo.ask_shares_total_rounded is None  # no size at the best price
    empty_side = pm.quotes_from_book("will-team-a-win", {"marketData": {"marketSlug": "will-team-a-win",
                                                                        "bids": [], "offers": []}},
                                     received_at_utc=None, evidence_id=None)
    assert empty_side["YES"].best_ask is None and empty_side["YES"].displayed_size == 0


def test_settlement_value():
    assert pm.settlement_value(json.loads((FIXTURES / "settlement_documented_example.json").read_text())) == 1
    assert pm.settlement_value({"slug": "x"}) is None
    assert pm.settlement_value({"settlement": "nan"}) is None


def test_opportunities_reject_fee_unsupported_and_rules_unresolved():
    (raw_event,) = pm.parse_events_page(EVENTS)
    event, mapping = pm.event_from_polymarket(raw_event)
    market, _ = pm.market_from_polymarket(raw_event["markets"][0], event_id_for_market=mapping)
    as_of = datetime(2025, 1, 20, 12, 31, tzinfo=UTC)
    quote = pm.quotes_from_book("will-team-a-win", BOOK, received_at_utc="2025-01-20T12:30:46Z",
                                evidence_id="ev")["YES"]
    schedule = schedule_for("polymarket_us")
    op = evaluate(event=event, market=market, side="YES", quote=quote, estimate=None, fee_schedule=schedule,
                  policy=Policy("p", "point", Decimal(0), 1, timedelta(minutes=5), timedelta(hours=1), "flag"),
                  as_of=as_of)
    assert op.qualification == "REJECT"
    assert {"FEE_UNSUPPORTED", "RULES_UNRESOLVED", "MODEL_UNAVAILABLE"} <= set(op.reasons)
    assert op.executable_price == Decimal("0.56") and op.fee is None and op.net_edge is None


def _page(n: int, start: int = 0) -> dict:
    return {"markets": [{"id": str(start + i), "slug": f"m-{start + i}", "status": "MARKET_STATUS_OPEN"}
                        for i in range(n)]}


def test_catalog_complete_only_after_a_short_final_page():
    opener = ScriptedOpener(_page(2), _page(2, 2), _page(1, 4))
    pages = []
    rows, cov = pm.read_catalog(limit=2, opener=opener, pacer=Pacer(), on_page=lambda p, r: pages.append(p))
    assert [r["slug"] for r in rows] == ["m-0", "m-1", "m-2", "m-3", "m-4"]
    assert cov.state is CoverageState.COMPLETE and cov.pages_ok == 3 and len(pages) == 3
    assert opener.calls[1] == "GET https://gateway.polymarket.us/v1/markets?limit=2&offset=2"


def test_a_failed_page_is_partial_and_never_evidence_of_absence():
    opener = ScriptedOpener(_page(2), http_error(404))
    rows, cov = pm.read_catalog(limit=2, opener=opener, pacer=Pacer())
    assert cov.state is CoverageState.PARTIAL and len(rows) == 2 and not cov.complete
    rows, cov = pm.read_catalog(limit=2, opener=ScriptedOpener(http_error(403)), pacer=Pacer())
    assert cov.state is CoverageState.FAILED and rows == []
    rows, cov = pm.read_catalog(limit=2, opener=ScriptedOpener({"unexpected": True}), pacer=Pacer())
    assert cov.state is CoverageState.FAILED
    rows, cov = pm.read_catalog(limit=2, max_pages=2, opener=ScriptedOpener(_page(2), _page(2, 2)), pacer=Pacer())
    assert cov.state is CoverageState.PARTIAL and "cap" in cov.detail


def test_coverage_from_stored_pages():
    assert pm.coverage_from_pages([100, 100, 7], limit=100, as_of_utc=None).state is CoverageState.COMPLETE
    assert pm.coverage_from_pages([100, None], limit=100, as_of_utc=None).state is CoverageState.PARTIAL
    assert pm.coverage_from_pages([None], limit=100, as_of_utc=None).state is CoverageState.FAILED
    assert pm.coverage_from_pages([100, 100], limit=100, as_of_utc=None).state is CoverageState.PARTIAL
    assert pm.coverage_from_pages([], limit=100, as_of_utc=None).state is CoverageState.FAILED


def test_only_the_public_gateway_is_used_and_it_is_not_polymarket_international():
    assert pm.BASE_URL == "https://gateway.polymarket.us"
    assert pm.book_url("a b") == "https://gateway.polymarket.us/v1/markets/a%20b/book"
    source = Path(pm.__file__).read_text()
    assert "api.polymarket.us" not in source  # never the authenticated host
    assert "polymarket.com" not in source
    assert venues.get_venue("polymarket_us").stage(Capability.ORDER_WRITE) is ConnectivityStage.NEEDS_ACCESS
    assert venues.get_venue("polymarket_us").stage(Capability.CATALOG_READ) is ConnectivityStage.TESTED
