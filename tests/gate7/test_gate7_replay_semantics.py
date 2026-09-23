"""Gate 7 C/B — execution and settlement semantics that replay frameworks get wrong.

Scenario sources (ideas only; no code copied, see THIRD_PARTY_NOTICES.md TPN-R002): the
execution assumptions of Oddpool/PredictionMarketBench, nautilus_trader and flumine, as
reviewed in docs/GITHUB_REUSE_AUDIT.md. Those frameworks model resting orders, queue
position, partial fills and maker fees. EXP-001's frozen `latency-confirmed-v1` models none
of them. Each test pins that the unsupported behaviour fails closed instead of being
approximated, so a later change cannot quietly loosen the frozen execution assumptions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import product

import pytest

from edge_lab import exp001_shadow as shadow
from edge_lab import settlement
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.fill_policy import FILLED, NO_FILL, simulate_fill
from edge_lab.opportunity import ExecutableQuote

from test_forward import D, MARKETS

from gate7.gate7_support import CLOSED, OPS, settled_copy, store_settled_markets

UTC = timezone.utc
T0 = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)


def q(ask, size, *, at=T0, bid=None, side="YES", market="kalshi:M", evidence="e", anomaly=None):
    return ExecutableQuote("kalshi", market, side, None if bid is None else Decimal(bid),
                           None if ask is None else Decimal(ask), None if size is None else Decimal(size),
                           at.isoformat(), None, evidence, anomaly)


def fill(qty, entry, confirm, as_of=T0 + timedelta(minutes=1)):
    return simulate_fill(quantity=qty, entry=entry, confirmation=confirm, as_of=as_of)


# --------------------------------------------------------------------------- execution (C)


def test_bid_only_entry_never_fills_as_a_resting_order():
    """A resting buy would sit at the bid and wait for sellers (queue position, trade prints).
    The frozen policy has no resting orders: with nothing offered there is no fill."""
    result = fill(1, q(None, "0", bid="0.40"), q("0.40", "100", at=T0 + timedelta(minutes=12)))
    assert result.status == NO_FILL and result.reason == "NO_ENTRY_PRICE"


def test_an_offer_that_appears_only_at_confirmation_never_fills():
    """A limit order that would have rested until a seller arrived is not modelled."""
    result = fill(1, q(None, "0"), q("0.30", "100", at=T0 + timedelta(minutes=12)))
    assert result.status == NO_FILL


def test_every_fill_is_a_taker_fill_at_the_entry_ask():
    """No maker fee or rebate, no price improvement from a better confirmation quote, no midpoint."""
    for confirm_ask in ("0.30", "0.44", "0.45"):
        result = fill(3, q("0.45", "10", bid="0.40"), q(confirm_ask, "10", at=T0 + timedelta(minutes=12)))
        assert result.status == FILLED and result.price == Decimal("0.45")
    assert not hasattr(FEES, "maker_buy")  # taker schedule only; maker fees are unmodelled


def test_no_partial_fill_when_the_best_level_is_short():
    """PredictionMarketBench fills partially and walks every level. The frozen policy sees only
    the best level (`ExecutableQuote` carries nothing deeper) and is all or nothing."""
    for entry_size, confirm_size in (("2", "10"), ("10", "2"), ("0", "10")):
        result = fill(3, q("0.45", entry_size), q("0.45", confirm_size, at=T0 + timedelta(minutes=12)))
        assert result.status == NO_FILL and result.quantity == 0 and result.price is None


def test_confirmation_window_is_pinned_not_the_most_favourable_capture():
    entry = q("0.45", "10")
    for minutes, expected in ((9, NO_FILL), (10, FILLED), (15, FILLED), (16, NO_FILL)):
        result = fill(1, entry, q("0.45", "10", at=T0 + timedelta(minutes=minutes)))
        assert result.status == expected, minutes


def test_shadow_run_records_at_most_one_fill_per_market_side_and_day(full_day, ledger, model):
    """Liquidity reuse: `simulate_fill` is stateless, so the same displayed size must not be
    taken twice by recording several fills against one market side on one day."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)  # re-run must not add fills
    keys = [(f["market_id"], f["side"]) for f in _payloads(ledger, "fill") if f["status"] == FILLED]
    assert keys, "the fixture day must fill something, or this test proves nothing"
    assert len(keys) == len(set(keys))


def test_missing_prices_are_never_marked_at_a_default():
    """PredictionMarketBench marks a missing bid at 0.50; missing is not a price here."""
    for entry in (q(None, None), q(None, "5"), q("0.45", None)):
        result = fill(1, entry, q("0.45", "10", at=T0 + timedelta(minutes=12)))
        assert result.status == NO_FILL and result.price is None


@pytest.mark.parametrize("contracts, price", [(4, "0.50"), (1, "0.01"), (1, "0.99"), (100, "0.50"), (3, "0.3333")])
def test_fee_is_exact_decimal_rounded_once_not_per_float_step(contracts, price):
    """Regression from the audit: a float implementation of ceil(0.07*C*P*(1-P)) overcharges a
    cent at C=4, P=0.50 (0.07 exactly). Our schedule computes in Decimal and rounds up once."""
    p = Decimal(price)
    quote = FEES.taker_buy(contracts, p)
    exact = Decimal("0.07") * contracts * p * (1 - p)
    assert quote.fee >= exact and quote.fee - exact < Decimal("0.000001")
    assert quote.total_cost >= contracts * p + exact


def test_fee_c4_p050_is_seven_cents_not_eight():
    assert FEES.taker_buy(4, Decimal("0.50")).fee == Decimal("0.070000")


def test_fee_monotone_in_quantity_on_the_price_grid():
    for price, c in product(("0.01", "0.25", "0.50", "0.75", "0.99"), range(1, 40)):
        assert FEES.taker_buy(c + 1, Decimal(price)).total_cost > FEES.taker_buy(c, Decimal(price)).total_cost


# --------------------------------------------------------------------------- settlement (B)


def _payloads(ledger, kind):
    import json
    return [json.loads(r["payload_json"]) for r in ledger.entries(OPS) if r["kind"] == kind]


def _self_yes(market: dict) -> dict:
    """A settled copy of `market` whose own expiration_value puts it in the money."""
    for value in range(-50, 150):
        if settlement.resolve(market, value).outcome is settlement.Outcome.YES:
            return dict(market, status="settled", expiration_value=str(value), result="yes")
    raise AssertionError(f"no YES value for {market.get('ticker')}")


def test_an_event_with_several_yes_brackets_does_not_settle(full_day, ledger, model):
    """Each captured market is internally consistent, but together the event resolves to more
    than one YES bracket (different expiration values). Gate 2 requires exactly one YES bracket
    per event; the shadow ledger must not book several winners."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    filled = {f["market_id"].split(":", 1)[1] for f in _payloads(ledger, "fill") if f["status"] == FILLED}
    assert len(filled) >= 2, "fixture day must fill at least two brackets for this scenario"
    store_settled_markets(full_day, [_self_yes(m) for m in MARKETS["markets"]], run_id="many-yes",
                          fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert [s for s in report["settled"] if s["account_id"] == OPS] == []
    pending = {p["position_id"]: p["reason"] for p in report["pending"] if p["account_id"] == OPS}
    assert pending and all("YES brackets" in why for why in pending.values())
    assert {c["position_id"] for c in report["conflicts"] if c["account_id"] == OPS} == set(pending)


def _self_no(market: dict) -> dict:
    """A settled copy of `market` whose own expiration_value puts it out of the money."""
    for value in range(150, -50, -1):
        if settlement.resolve(market, value).outcome is settlement.Outcome.NO:
            return dict(market, status="settled", expiration_value=str(value), result="no")
    raise AssertionError(f"no NO value for {market.get('ticker')}")


def test_brackets_that_each_lose_on_their_own_value_do_not_settle(full_day, ledger, model):
    """Every captured market settles NO, each on a different expiration value: the brackets
    contradict each other, so this is not a clean set of losses."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    store_settled_markets(full_day, [_self_no(m) for m in MARKETS["markets"]], run_id="no-yes",
                          fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert [s for s in report["settled"] if s["account_id"] == OPS] == []
    pending = {p["position_id"]: p["reason"] for p in report["pending"] if p["account_id"] == OPS}
    assert pending and all("different expiration values" in why for why in pending.values())


def test_brackets_stating_different_values_do_not_settle(full_day, ledger, model):
    """Exactly one YES bracket, but another bracket states a different expiration value."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    settled = settled_copy(MARKETS["markets"], 67)
    loser = next(i for i, m in enumerate(settled) if m["result"] == "no"
                 and settlement.resolve(m, 90).outcome is settlement.Outcome.NO)
    settled[loser] = dict(settled[loser], expiration_value="90")
    store_settled_markets(full_day, settled, run_id="split", fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert [s for s in report["settled"] if s["account_id"] == OPS] == []
    pending = [p["reason"] for p in report["pending"] if p["account_id"] == OPS]
    assert pending and all("different expiration values" in why for why in pending)


# --------------------------------------------------------------------------- incomplete is not contradictory


def _positions(ledger):
    return {p.market_id.split(":", 1)[1]: p.position_id for p in ledger.state(OPS).positions}


def test_unsettled_brackets_are_pending_not_a_conflict(full_day, ledger, model):
    """The daily refresh often captures an event before Kalshi publishes results. Unsettled
    records mean the evidence is incomplete, not contradictory: no alert, just pending."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    unsettled = [dict(m, expiration_value=None, result="") for m in MARKETS["markets"]]
    store_settled_markets(full_day, unsettled, run_id="early", fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert report["settled"] == [] and report["conflicts"] == []
    assert {p["position_id"] for p in report["pending"] if p["account_id"] == OPS} == set(_positions(ledger).values())


def test_losing_brackets_settle_while_the_winning_bracket_is_not_yet_settled(full_day, ledger, model):
    """One stated value, the YES bracket not settled yet: every captured bracket resolves on
    that value, so the losers settle exactly as they did before F14 and nothing is flagged."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    settled = settled_copy(MARKETS["markets"], 67)
    winner = next(i for i, m in enumerate(settled) if m["result"] == "yes")
    winner_ticker = settled[winner]["ticker"]
    settled[winner] = dict(MARKETS["markets"][winner], expiration_value=None, result="")
    store_settled_markets(full_day, settled, run_id="partial", fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert report["conflicts"] == []
    positions = _positions(ledger)
    assert winner_ticker in positions, "the fixture day must hold a position on the winning bracket"
    booked = {s["position_id"]: s["outcome"] for s in report["settled"] if s["account_id"] == OPS}
    held = {p["position_id"] for p in report["pending"] if p["account_id"] == OPS}
    assert positions[winner_ticker] in held
    others = {t: pid for t, pid in positions.items() if t != winner_ticker}
    assert others and all(booked.get(pid) == "NO" for pid in others.values())


def test_an_unsettled_bracket_holding_a_position_stays_pending(full_day, ledger, model):
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    positions = _positions(ledger)
    settled = settled_copy(MARKETS["markets"], 67)
    loser = next(i for i, m in enumerate(settled) if m["result"] == "no" and m["ticker"] in positions)
    loser_ticker = settled[loser]["ticker"]
    settled[loser] = dict(MARKETS["markets"][loser], expiration_value=None, result="")
    store_settled_markets(full_day, settled, run_id="partial", fetched_at="2026-09-24T14:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    assert report["conflicts"] == []
    booked = {s["position_id"] for s in report["settled"] if s["account_id"] == OPS}
    held = {p["position_id"] for p in report["pending"] if p["account_id"] == OPS}
    assert positions[loser_ticker] in held
    assert {pid for t, pid in positions.items() if t != loser_ticker} <= booked


def test_a_later_contradiction_is_reported_for_already_settled_positions(full_day, ledger, model):
    """Settled on coherent evidence, then a later capture adds a second YES bracket: the booked
    positions are reported as conflicts (never silently rewritten)."""
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    store_settled_markets(full_day, settled_copy(MARKETS["markets"], 67), run_id="s1",
                          fetched_at="2026-09-24T14:00:00+00:00")
    first = shadow.settle_open_positions(full_day, ledger)
    settled_ids = {s["position_id"] for s in first["settled"] if s["account_id"] == OPS}
    assert settled_ids and first["conflicts"] == []
    store_settled_markets(full_day, [_self_yes(m) for m in MARKETS["markets"]], run_id="s2",
                          fetched_at="2026-09-24T15:00:00+00:00")
    report = shadow.settle_open_positions(full_day, ledger)
    flagged = {c["position_id"] for c in report["conflicts"] if c["account_id"] == OPS}
    assert settled_ids <= flagged
    assert any("YES brackets" in (c.get("reason") or "") for c in report["conflicts"])
