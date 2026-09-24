"""Polymarket US: split / alternative settlement is represented, then refused; fee scope routing.

ADR 0027, option "represent then refuse": a market whose rules text states a 50-50 settlement is
`binary_split_on_cancel`; a sports market without that language is
`binary_alternative_settlement`. The engine (PAYOFF_UNSUPPORTED) refuses both. Kalshi is untouched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import polymarket_us as pm
from edge_lab.fee_schedules import POLYMARKET_US_EXCHANGE_SCOPE, POLYMARKET_US_TAKER_V1, UnsupportedFeeSchedule, schedule_for
from edge_lab.opportunity import Policy, Reason, evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket_us"
CAPTURED = json.loads((FIXTURES / "markets_limit5_2026-09-23T140738Z.json").read_text(encoding="utf-8"))
EVENTS = json.loads((FIXTURES / "events_schema_constructed.json").read_text(encoding="utf-8"))
BOOK = json.loads((FIXTURES / "book_documented_example.json").read_text(encoding="utf-8"))
D = Decimal


def raw(description: str | None, **kw) -> dict:
    out = {"slug": "m", "status": "MARKET_STATUS_OPEN", "feeCoefficient": 0.0695, "description": description}
    out.update(kw)
    return out


def test_every_captured_market_states_a_50_50_cancellation_and_is_split_on_cancel():
    assert len(CAPTURED["markets"]) == 5
    for m in CAPTURED["markets"]:
        market, _ = pm.market_from_polymarket(m)
        assert market.payoff.kind == pm.PAYOFF_SPLIT_ON_CANCEL == "binary_split_on_cancel"
        assert market.payoff.amount == 1  # never reinterpreted as a different amount
        assert "50-50" in market.payoff.yes_condition


@pytest.mark.parametrize("text", [
    "If the game is canceled entirely, with no make-up game, this market will resolve 50-50.",
    "Cancelled: resolves 50/50.",
    "It will settle fifty-fifty.",
    "If postponed, each contract settles at $0.50.",
    "Settles at $.50 on a tie.",
    "Void markets settle at 0.50 per contract.",
    "Void markets settle at $0.5 per contract.",
    "Void markets settle at 0.5 per contract.",
    "If cancelled this market resolves 50 50.",
    "Each contract settles at 50 cents if the game is cancelled.",
    "Contracts pay fifty cents on a tie.",
    "On a tie each contract pays half of the payout.",
    "A void market settles at half a dollar.",
    "resolves 50–50 if cancelled",
])
def test_split_language_variants_are_recognised(text):
    assert pm.payoff_kind(raw(text))[0] == pm.PAYOFF_SPLIT_ON_CANCEL


@pytest.mark.parametrize("fields", [{"category": "sports"}, {"category": "Sports"}, {"sportsMarketType": "moneyline"},
                                    {"gameStartTime": "2026-10-01T17:00:00Z"}])
def test_sports_markets_without_split_language_fail_closed_to_alternative_settlement(fields):
    kind, why = pm.payoff_kind(raw("If Team A wins, the market resolves to Team A.", **fields))
    assert kind == pm.PAYOFF_ALTERNATIVE_SETTLEMENT and "last fair market price" in why
    assert pm.payoff_kind(raw(None, **fields))[0] == pm.PAYOFF_ALTERNATIVE_SETTLEMENT  # no rules text


@pytest.mark.parametrize("category", ["weather", "crypto", "politics", None])
@pytest.mark.parametrize("text", [
    "If no data is published within one week, the contract settles at last fair market prices.",
    "Settles at the Last Fair Market Price at the time of the announcement.",
    "Cancelled events settle at LFMP.",
    "last-fair-market-price settlement applies if the source is unavailable.",
])
def test_last_fair_market_price_language_fails_closed_in_any_market(category, text):
    kind, why = pm.payoff_kind(raw(text, category=category))
    assert kind == pm.PAYOFF_ALTERNATIVE_SETTLEMENT and "last fair market price" in why
    # Both kinds of language: still refused (the price-later settlement is the broader one).
    assert pm.payoff_kind(raw(text + " Otherwise it resolves 50-50.", category=category))[0] \
        == pm.PAYOFF_ALTERNATIVE_SETTLEMENT


@pytest.mark.parametrize("text", ["Resolves Yes if BTC is above $50,000.", "Resolves Yes above 0.55.",
                                  "The high must reach 50 degrees.", "Pays $0.55 per share only if Yes.",
                                  "Resolves Yes if a team leads at half time.", "Price above 150 cents."])
def test_ordinary_numbers_are_not_split_language(text):
    assert pm.payoff_kind(raw(text, category="crypto"))[0] == "binary"


def test_a_non_sports_market_without_split_language_stays_binary():
    market, _ = pm.market_from_polymarket(raw("Resolves Yes if the NWS CLI high is 70F or above.", category="weather"))
    assert market.payoff.kind == "binary"
    assert market.payoff.yes_condition == "long side 'm' per the market rules text (not parsed)"


def _policy() -> Policy:
    return Policy("p", "point", D(0), 1, timedelta(minutes=5), timedelta(hours=1), "flag")


def test_evaluate_refuses_split_and_alternative_settlement_payoffs():
    (raw_event,) = pm.parse_events_page(EVENTS)
    event, mapping = pm.event_from_polymarket(raw_event)
    as_of = datetime(2026, 9, 24, 12, tzinfo=UTC)
    quote = pm.quotes_from_book("will-team-a-win", BOOK, received_at_utc="2026-09-24T11:59:00Z", evidence_id="ev")["YES"]
    split, meta = pm.market_from_polymarket(raw_event["markets"][0], event_id_for_market=mapping)
    assert split.payoff.kind == pm.PAYOFF_SPLIT_ON_CANCEL
    schedule = schedule_for("polymarket_us", pm.fee_scope(meta))
    assert schedule is POLYMARKET_US_TAKER_V1
    op = evaluate(event=event, market=split, side="YES", quote=quote, estimate=None, fee_schedule=schedule,
                  policy=_policy(), as_of=as_of)
    assert op.qualification == "REJECT" and Reason.PAYOFF_UNSUPPORTED.value in op.reasons
    assert any("binary_split_on_cancel" in d for d in op.details)
    alt_raw = dict(raw_event["markets"][0], description="If Kansas City wins, resolves to Kansas City.")
    alt, _ = pm.market_from_polymarket(alt_raw, event_id_for_market=mapping)
    op = evaluate(event=event, market=alt, side="NO", quote=None, estimate=None, fee_schedule=schedule,
                  policy=_policy(), as_of=as_of)
    assert Reason.PAYOFF_UNSUPPORTED.value in op.reasons


def test_the_polymarket_schedule_prices_research_opportunities_but_never_a_claim():
    """With the fee schedule wired, the fee is computed, not claimable, and FEE_UNVERIFIED under
    a policy that requires verified fees."""
    (raw_event,) = pm.parse_events_page(EVENTS)
    event, mapping = pm.event_from_polymarket(raw_event)
    weather = dict(raw_event["markets"][0], category="weather", description="Resolves Yes if the high is 70F.")
    market, meta = pm.market_from_polymarket(weather, event_id_for_market=mapping)
    assert market.payoff.kind == "binary"
    quote = pm.quotes_from_book("will-team-a-win", BOOK, received_at_utc="2026-09-24T11:59:00Z", evidence_id="ev")["YES"]
    policy = Policy("p", "point", D(0), 10, timedelta(minutes=5), timedelta(hours=1), "require")
    op = evaluate(event=event, market=market, side="YES", quote=quote, estimate=None,
                  fee_schedule=schedule_for("polymarket_us", pm.fee_scope(meta)), policy=policy,
                  as_of=datetime(2026, 9, 24, 12, tzinfo=UTC))
    assert op.fee_schedule_id == "polymarket-us-taker-v1" and op.fee_status == "PARTIALLY_VERIFIED"
    assert not op.claimable and "FEE_UNVERIFIED" in op.reasons and "FEE_UNSUPPORTED" not in op.reasons
    assert op.fee == D("0.18")  # ceil(0.0695 x 10 x 0.56 x 0.44 = 0.171248) to the cent


# ---------------------------------------------------------------- fee scope


@pytest.mark.parametrize("value,scope", [
    (0.0695, POLYMARKET_US_EXCHANGE_SCOPE), ("0.0695", POLYMARKET_US_EXCHANGE_SCOPE),
    ("0.06950", POLYMARKET_US_EXCHANGE_SCOPE), (0.07, "feeCoefficient:0.07"), ("0", "feeCoefficient:0"),
    (None, None), ("", None), ("abc", None), ("NaN", None), (True, None),
])
def test_fee_scope_needs_the_documented_theta(value, scope):
    assert pm.fee_scope({"feeCoefficient": value}) == scope
    schedule = schedule_for("polymarket_us", pm.fee_scope({"feeCoefficient": value}))
    if scope == POLYMARKET_US_EXCHANGE_SCOPE:
        assert schedule is POLYMARKET_US_TAKER_V1
    else:
        assert isinstance(schedule, UnsupportedFeeSchedule)


def test_fee_scope_reads_market_meta_and_the_captured_markets():
    for m in CAPTURED["markets"]:
        _, meta = pm.market_from_polymarket(m)
        assert meta.fee_coefficient_raw == "0.0695"
        assert pm.fee_scope(meta) == POLYMARKET_US_EXCHANGE_SCOPE
    _, meta = pm.market_from_polymarket({"slug": "x"})
    assert pm.fee_scope(meta) is None
