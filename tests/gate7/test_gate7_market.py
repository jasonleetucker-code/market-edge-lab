"""Gate 7 C — market, model and execution adversarial inputs.

Complements, malformed and non-finite prices, liquidity, stale/future quotes, wrong events,
unresolved rules, incomplete forecasts, missing re-checks, price movement, fee/latency
sensitivity (diagnostic only: the frozen fee schedule and fill policy are asserted unchanged)
and the frozen DESIGN §5 tail-bin and probability-to-bracket conversion. No model variant
is introduced and nothing is tuned on outcomes.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import exp001_baseline as base
from edge_lab import exp001_shadow as shadow
from edge_lab import exp001_stageb as stageb
from edge_lab import settlement
from edge_lab.conservative import wilson_bounds
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.fee_schedules import FeeScheduleStatus
from edge_lab.fill_policy import FILLED, LATENCY_CONFIRMED_V1, FillPolicy, simulate_fill
from edge_lab.kalshi_quotes import check_event_identity, market_from_kalshi, quotes_from_orderbook
from edge_lab.opportunity import (
    Event, ExecutableQuote, Market, MarketStatus, ModelEstimate, Payoff, Policy, evaluate,
)

from test_forward import D, MARKETS

from gate7.gate7_support import CLOSED, OPS

UTC = timezone.utc
AS_OF = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)
EVENT = Event("weather", "ev", "2026-09-23", None, "cl", "test")
MARKET = Market("kalshi", "kalshi:M", "M", "ev", "x", Payoff("binary", Decimal(1), "x"), "sha",
                MarketStatus.OPEN, True, "ok")
POLICY = Policy("gate7", "point", Decimal("0.05"), 1, timedelta(minutes=5), timedelta(hours=24, minutes=30), "flag")
TEMPLATE = next(m for m in MARKETS["markets"] if m["strike_type"] == "between")


def q(side="YES", ask="0.40", bid="0.30", size="10", at=AS_OF - timedelta(minutes=2), market="kalshi:M",
      evidence="snap:1", anomaly=None):
    return ExecutableQuote("kalshi", market, side, None if bid is None else Decimal(bid),
                           None if ask is None else Decimal(ask), None if size is None else Decimal(size),
                           None if at is None else at.isoformat(), None, evidence, anomaly)


def est(p=0.70, market="kalshi:M", event="ev"):
    return ModelEstimate("EXP-001/V1", "v", event, market, p, wilson_bounds(p, 3551), AS_OF.isoformat(), "in",
                         (AS_OF - timedelta(hours=3)).isoformat())


def run(side="YES", quote="default", estimate="default", market=MARKET, as_of=AS_OF, fees=FEES):
    quote = q(side=side) if quote == "default" else quote
    estimate = est() if estimate == "default" else estimate
    return evaluate(event=EVENT, market=market, side=side, quote=quote, estimate=estimate, fee_schedule=fees,
                    policy=POLICY, as_of=as_of)


def book(yes, no):
    return {"orderbook_fp": {"yes_dollars": yes, "no_dollars": no}}


def bracket(strike_type, floor=None, cap=None):
    """A synthetic KXHIGHNY bracket whose rules text agrees with its strikes (frozen resolver)."""
    phrase = {"between": f"between {floor}-{cap}°", "greater": f"greater than {floor}°",
              "less": f"less than {cap}°"}[strike_type]
    rules = TEMPLATE["rules_primary"].replace("between 71-72°", phrase)
    return dict(TEMPLATE, ticker=f"SYN-{strike_type}-{floor}-{cap}", strike_type=strike_type, floor_strike=floor,
                cap_strike=cap, rules_primary=rules)


# --------------------------------------------------------------------------- YES/NO complements


@pytest.mark.parametrize("yes_bid, no_bid", [("0.30", "0.60"), ("0.01", "0.01"), ("0.49", "0.50"), ("0.0001", "0.9998")])
def test_implied_asks_are_complements_of_opposite_bids(yes_bid, no_bid):
    quotes = quotes_from_orderbook("M", book([[yes_bid, "3"]], [[no_bid, "7"]]), received_at_utc="t", evidence_id="e")
    assert quotes["YES"].best_ask == 1 - Decimal(no_bid) and quotes["YES"].displayed_size == 7
    assert quotes["NO"].best_ask == 1 - Decimal(yes_bid) and quotes["NO"].displayed_size == 3
    assert quotes["YES"].anomaly is None
    # an uncrossed book never lets both sides be bought for less than the $1 payout
    assert quotes["YES"].best_ask + quotes["NO"].best_ask > 1


@pytest.mark.parametrize("yes_bid, no_bid", [("0.50", "0.50"), ("0.60", "0.45")])
def test_locked_or_crossed_book_is_invalid_on_both_sides(yes_bid, no_bid):
    quotes = quotes_from_orderbook("M", book([[yes_bid, "3"]], [[no_bid, "7"]]), received_at_utc="t", evidence_id="e")
    assert quotes["YES"].anomaly and quotes["NO"].anomaly
    for side in ("YES", "NO"):
        assert run(side=side, quote=replace(quotes[side], market_id="kalshi:M",
                                            received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat())
                   ).rejection_reason == "INVALID_PRICE"


@pytest.mark.parametrize("p", [0.0, 0.05, 0.3043539, 0.5, 0.95, 1.0])
def test_model_side_probabilities_are_complements(p):
    b = wilson_bounds(p, 3551)
    yes_point, yes_cons = b.for_side("YES")
    no_point, no_cons = b.for_side("NO")
    assert yes_point + no_point == pytest.approx(1.0, abs=1e-15)
    assert yes_cons <= yes_point and no_cons <= no_point  # the haircut never helps either side
    assert yes_cons + no_cons <= 1.0 + 1e-15


def test_fixture_day_yes_and_no_probabilities_sum_to_one(full_day, model):
    ev = stageb.evaluate_day(full_day, D, model=model)
    by_market: dict[str, dict[str, Decimal]] = {}
    for o in ev.opportunities:
        by_market.setdefault(o.market_id, {})[o.side] = o.model_probability
    assert len(by_market) == 6
    for sides in by_market.values():
        assert abs(sides["YES"] + sides["NO"] - 1) <= Decimal("1e-11")
    assert abs(sum(s["YES"] for s in by_market.values()) - 1) <= Decimal("1e-11")


# --------------------------------------------------------------------------- liquidity


@pytest.mark.parametrize("payload, reason", [
    (book([], []), "INSUFFICIENT_SIZE"),
    (book([["0.30", "0"]], [["0.60", "0"]]), "INSUFFICIENT_SIZE"),  # zero-size levels are no offer
    (book(None, None), "INSUFFICIENT_SIZE"),
    ({"orderbook_fp": None}, "BOOK_MISSING"),
    ({}, "BOOK_MISSING"),
    (None, "BOOK_MISSING"),
])
def test_zero_or_missing_liquidity_never_qualifies(payload, reason):
    quotes = quotes_from_orderbook("M", payload, received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat(),
                                   evidence_id="e")
    quote = quotes.get("YES")
    o = run(quote=None if quote is None else replace(quote, market_id="kalshi:M"))
    assert o.qualification == "REJECT" and o.rejection_reason == reason
    assert o.executable_price is None and o.net_edge is None  # missing is not zero


def test_displayed_size_below_quantity_is_not_filled():
    r = simulate_fill(quantity=2, entry=q(size="1"), confirmation=q(size="5", at=AS_OF + timedelta(minutes=9)),
                      as_of=AS_OF)
    assert r.status == "NO_FILL" and r.reason == "INSUFFICIENT_SIZE"


# --------------------------------------------------------------------------- malformed / non-finite prices


@pytest.mark.parametrize("level", [["NaN", "5"], ["Infinity", "5"], ["-Infinity", "5"], ["abc", "5"], [True, "5"],
                                   ["0.30", "NaN"], ["0.30", "-1"], ["0.30"], "0.30", None])
def test_malformed_levels_mark_the_book_invalid(level):
    quotes = quotes_from_orderbook("M", book([level], [["0.60", "5"]]), received_at_utc=AS_OF.isoformat(),
                                   evidence_id="e")
    assert quotes["YES"].anomaly and quotes["NO"].anomaly and quotes["YES"].best_ask is None
    assert run(quote=replace(quotes["YES"], market_id="kalshi:M",
                             received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat())
               ).rejection_reason == "INVALID_PRICE"


@pytest.mark.parametrize("ask", ["0", "1", "1.5", "-0.1", "0.12345", "Infinity"])
def test_out_of_range_or_off_grid_ask_is_invalid_price(ask):
    o = run(quote=q(ask=ask, bid=None))
    assert o.qualification == "REJECT" and o.rejection_reason == "INVALID_PRICE" and o.executable_price is None


@pytest.mark.parametrize("yes_bid", ["-0.10", "1.50", "1.00", "0"])
def test_nonsense_bid_levels_never_become_valid_asks(yes_bid):
    quotes = quotes_from_orderbook("M", book([[yes_bid, "5"]], []), received_at_utc="t", evidence_id="e")
    no = replace(quotes["NO"], market_id="kalshi:M", received_at_utc=(AS_OF - timedelta(minutes=1)).isoformat())
    assert run(side="NO", quote=no).rejection_reason in ("INVALID_PRICE", "INSUFFICIENT_SIZE")


@pytest.mark.xfail(strict=True, reason="GATE7-F07: a NaN Decimal ask reaching the engine raises "
                                       "InvalidOperation instead of INVALID_PRICE")
def test_nan_ask_from_any_adapter_is_invalid_price_not_a_crash():
    o = run(quote=q(ask="NaN", bid=None))
    assert o.rejection_reason == "INVALID_PRICE"
    r = simulate_fill(quantity=1, entry=q(ask="NaN"), confirmation=None, as_of=AS_OF)
    assert r.status == "NO_FILL" and r.reason == "NO_ENTRY_PRICE"


def test_non_finite_model_probability_is_refused():
    for bad in (float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValueError):
            wilson_bounds(bad, 100)


# --------------------------------------------------------------------------- stale / future quotes


@pytest.mark.parametrize("age, fresh", [(timedelta(minutes=5), True), (timedelta(minutes=5, microseconds=1), False),
                                        (timedelta(0), True), (-timedelta(microseconds=1), False),
                                        (-timedelta(minutes=3), False)])
def test_quote_age_boundary_and_future_quotes(age, fresh):
    o = run(quote=q(at=AS_OF - age))
    assert (o.book_freshness == "fresh") is fresh
    if not fresh:
        assert "BOOK_STALE" in o.reasons and o.qualification == "REJECT"


@pytest.mark.parametrize("entry_age, reason", [(timedelta(minutes=5, microseconds=1), "STALE_ENTRY_QUOTE"),
                                               (-timedelta(seconds=1), "STALE_ENTRY_QUOTE")])
def test_fill_refuses_stale_or_future_entry(entry_age, reason):
    entry = q(at=AS_OF - entry_age)
    confirm = q(at=AS_OF - entry_age + timedelta(minutes=11))
    assert simulate_fill(quantity=1, entry=entry, confirmation=confirm, as_of=AS_OF).reason == reason


@pytest.mark.parametrize("delay, ok", [(timedelta(minutes=10), True), (timedelta(minutes=15), True),
                                       (timedelta(minutes=10) - timedelta(microseconds=1), False),
                                       (timedelta(minutes=15, microseconds=1), False)])
def test_confirmation_window_is_inclusive(delay, ok):
    entry_at = AS_OF - timedelta(minutes=1)
    r = simulate_fill(quantity=1, entry=q(at=entry_at), confirmation=q(at=entry_at + delay), as_of=AS_OF)
    assert (r.status == FILLED) is ok
    if not ok:
        assert r.reason == "CONFIRMATION_OUTSIDE_WINDOW"


def test_quote_without_timestamp_is_unknown_not_fresh():
    o = run(quote=q(at=None))
    assert o.book_freshness == "unknown" and o.qualification == "REJECT"


# --------------------------------------------------------------------------- wrong events and rules


def test_wrong_event_ticker_is_event_mismatch():
    raw = dict(TEMPLATE, event_ticker="KXHIGHNY-26SEP24")
    market = market_from_kalshi(raw, event_id_for_ticker={"KXHIGHNY-26SEP23": "ev"})
    assert market.event_id.startswith("unmapped:")
    o = run(market=replace(market, market_id="kalshi:M"))
    assert "EVENT_MISMATCH" in o.reasons and o.qualification == "REJECT"
    assert check_event_identity(EVENT, {"event": {"event_ticker": "KXHIGHNY-26SEP24"}}, "KXHIGHNY-26SEP23")
    assert check_event_identity(EVENT, {"nope": 1}, "KXHIGHNY-26SEP23")


@pytest.mark.parametrize("quote, estimate", [("other-market", "default"), ("default", "other-market"),
                                             ("default", "other-event")])
def test_quote_or_estimate_for_another_market_is_mismatch(quote, estimate):
    qq = q(market="kalshi:OTHER") if quote == "other-market" else "default"
    ee = {"other-market": est(market="kalshi:OTHER"), "other-event": est(event="ev2")}.get(estimate, "default")
    assert "EVENT_MISMATCH" in run(quote=qq, estimate=ee).reasons


@pytest.mark.parametrize("mutate", [
    lambda m: dict(m, rules_primary=m["rules_primary"].replace("The Weather Company", "somebody")),
    lambda m: dict(m, floor_strike=70),  # strikes contradict the rules text
    lambda m: dict(m, strike_type="greater"),
    lambda m: dict(m, rules_primary=None),
    lambda m: dict(m, cap_strike=None),
])
def test_unresolved_rules_block_the_market(model, mutate):
    raw = mutate(TEMPLATE)
    assert settlement.resolve(raw, 71).outcome is settlement.Outcome.UNKNOWN
    market = market_from_kalshi(raw, event_id_for_ticker={TEMPLATE["event_ticker"]: "ev"})
    assert market.rules_resolved is False
    assert "RULES_UNRESOLVED" in run(market=replace(market, market_id="kalshi:M")).reasons
    p, why = stageb.bracket_probability(model, raw, 67, D)
    assert p is None and why


@pytest.mark.parametrize("value, result", [("67.5", "yes"), (None, "yes"), ("abc", "no"), ("67", "void"),
                                           ("67", None), ("Infinity", "yes")])
def test_official_outcome_never_guesses(value, result):
    market = dict(TEMPLATE, expiration_value=value, result=result)
    outcome, why = shadow.official_outcome(market)
    assert outcome is None and why


def test_official_outcome_disagreement_is_not_settled():
    market = dict(TEMPLATE, expiration_value="71", result="no")  # resolver: 71 in [71, 72] -> YES
    outcome, why = shadow.official_outcome(market)
    assert outcome is None and "Kalshi recorded" in why


# --------------------------------------------------------------------------- incomplete evidence at run_day


def test_incomplete_forecast_day_never_fills(store, ledger, monkeypatch, model):
    from edge_lab.http import HttpFetchError
    from test_forward import Clock, FakeApi, _run, at, default_routes
    routes = {"/products/types/PFM": HttpFetchError("HTTP 503", status=503, attempts=3), **default_routes()}
    clock = Clock(at(21, 45))
    api = FakeApi(clock, routes)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)
    clock.now = at(22, 5)
    _run(store, "recheck", clock, api, monkeypatch)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    state = ledger.state(OPS)
    assert summary["stage_b_day_status"] == "INVALID" and summary["qualified"] == 0 and state.fills == 0
    assert state.decisions == 12 and state.settled_cash == shadow.STARTING_BANKROLL


def test_missing_recheck_for_one_bracket_never_fills(store, ledger, monkeypatch, model):
    from test_forward import BOOK, BRACKETS, Clock, FakeApi, _run, at, default_routes
    from edge_lab.http import HttpFetchError
    calls = {"n": 0}

    def recheck_fails_once(url):
        calls["n"] += 1
        if calls["n"] > len(BRACKETS) and BRACKETS[1] in url:
            return HttpFetchError("HTTP 500", status=500, attempts=3)
        return BOOK
    routes = default_routes()
    routes["/orderbook"] = recheck_fails_once
    clock = Clock(at(21, 45))
    api = FakeApi(clock, routes)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)
    clock.now = at(22, 5)
    _run(store, "recheck", clock, api, monkeypatch)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    assert summary["stage_b_day_status"] == "INVALID" and ledger.state(OPS).fills == 0


def test_missing_confirmation_is_unverified_no_fill():
    r = simulate_fill(quantity=1, entry=q(), confirmation=None, as_of=AS_OF)
    assert r.status == "NO_FILL" and r.reason == "NO_CONFIRMATION" and r.price is None


# --------------------------------------------------------------------------- price movement


@pytest.mark.parametrize("confirm_ask, filled", [("0.39", True), ("0.40", True), ("0.41", False)])
def test_price_movement_between_entry_and_confirmation(confirm_ask, filled):
    entry_at = AS_OF - timedelta(minutes=1)
    r = simulate_fill(quantity=1, entry=q(ask="0.40", at=entry_at),
                      confirmation=q(ask=confirm_ask, at=entry_at + timedelta(minutes=11)), as_of=AS_OF)
    assert (r.status == FILLED) is filled
    if filled:
        assert r.price == Decimal("0.40")  # always the entry price, never the later better one
    else:
        assert r.reason == "PRICE_MOVED_AWAY"


def test_confirmation_for_the_other_side_is_mismatch():
    entry_at = AS_OF - timedelta(minutes=1)
    r = simulate_fill(quantity=1, entry=q(at=entry_at), confirmation=q(side="NO", at=entry_at + timedelta(minutes=11)),
                      as_of=AS_OF)
    assert r.reason == "CONFIRMATION_MISMATCH"


# --------------------------------------------------------------------------- fee and latency sensitivity (diagnostic)


def test_worse_fees_never_add_opportunities_and_leave_the_frozen_schedule_alone(full_day, model, monkeypatch):
    frozen = stageb.evaluate_day(full_day, D, model=model)
    frozen_q = {(o.market_id, o.side) for o in frozen.opportunities if o.qualification == "QUALIFY"}
    frozen_edge = {(o.market_id, o.side): o.net_edge for o in frozen.opportunities}
    previous = frozen_q
    for coefficient in ("0.14", "0.35", "0.70"):
        worse = replace(FEES, schedule_id=f"gate7-sensitivity-x{coefficient}", coefficient=Decimal(coefficient))
        monkeypatch.setattr(stageb, "FEE_SCHEDULE", worse)
        ev = stageb.evaluate_day(full_day, D, model=model)
        qualified = {(o.market_id, o.side) for o in ev.opportunities if o.qualification == "QUALIFY"}
        assert qualified <= previous
        for o in ev.opportunities:
            assert o.fee_schedule_id == worse.schedule_id and o.claimable is False
            if o.net_edge is not None:
                assert o.net_edge <= frozen_edge[(o.market_id, o.side)]
        previous = qualified
        monkeypatch.undo()
    assert previous < frozen_q  # at 10x the frozen coefficient some signal disappears
    assert stageb.FEE_SCHEDULE is FEES and FEES.coefficient == Decimal("0.07")
    assert FEES.schedule_id == "kalshi-quadratic-taker-v1"
    assert FEES.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE


def test_higher_latency_never_adds_fills_and_leaves_the_frozen_policy_alone():
    entry_at = AS_OF - timedelta(minutes=1)
    confirmations = [q(at=entry_at + timedelta(minutes=m)) for m in (10, 12, 15, 20, 25)]
    policies = [LATENCY_CONFIRMED_V1] + [
        FillPolicy(f"gate7-latency-{lo}-{hi}", timedelta(minutes=5), timedelta(minutes=lo), timedelta(minutes=hi))
        for lo, hi in ((12, 17), (20, 25), (30, 35))]
    fills = [sum(simulate_fill(quantity=1, entry=q(at=entry_at), confirmation=c, as_of=AS_OF, policy=p).status
                 == FILLED for c in confirmations) for p in policies]
    assert fills[0] == 3 and fills[-1] == 0
    assert (LATENCY_CONFIRMED_V1.confirm_min, LATENCY_CONFIRMED_V1.confirm_max, LATENCY_CONFIRMED_V1.max_entry_age) \
        == (timedelta(minutes=10), timedelta(minutes=15), timedelta(minutes=5))


# --------------------------------------------------------------------------- DESIGN §5: tail bins and brackets


def _day(k, n=0):
    return base.Day(f"2020-01-{n + 1:02d}", "train", 60, 60 + k)


def test_errors_beyond_twenty_are_counted_at_the_ends():
    days = [_day(25, 0), _day(-30, 1), _day(20, 2), _day(0, 3)]
    pmf = base.error_pmf(days)
    denominator = 4 + 0.5 * 41
    assert len(pmf) == 41 and math.isclose(math.fsum(pmf), 1.0, abs_tol=1e-12)
    assert pmf[40] == (2 + 0.5) / denominator  # +25 and +20 both land on k = +20
    assert pmf[0] == (1 + 0.5) / denominator  # -30 lands on k = -20
    assert pmf[20] == (1 + 0.5) / denominator
    assert base.pmf_log_score(pmf, _day(99)) == math.log(pmf[40])  # scored at the end, never -inf


@pytest.mark.parametrize("f", [67, 30, 100, 120, 10])
def test_bracket_partition_sums_to_one_for_any_forecast(model, f):
    probs = [stageb.bracket_probability(model, raw, f, D)[0] for raw in MARKETS["markets"]]
    assert None not in probs
    assert math.isclose(math.fsum(probs), 1.0, abs_tol=1e-12)


def test_comparison_semantics_greater_strict_less_strict_between_inclusive(model):
    pmf = model.pmf_for(D)
    f = 67
    greater = bracket("greater", floor=70)  # YES iff y > 70  -> k >= 4
    less = bracket("less", cap=65)  # YES iff y < 65  -> k <= -3
    between = bracket("between", floor=66, cap=68)  # YES iff 66 <= y <= 68 -> k in [-1, 1]
    assert settlement.resolve(greater, 70).outcome is settlement.Outcome.NO
    assert settlement.resolve(greater, 71).outcome is settlement.Outcome.YES
    assert settlement.resolve(less, 65).outcome is settlement.Outcome.NO
    assert settlement.resolve(less, 64).outcome is settlement.Outcome.YES
    assert settlement.resolve(between, 66).outcome is settlement.Outcome.YES
    assert settlement.resolve(between, 68).outcome is settlement.Outcome.YES
    assert settlement.resolve(between, 69).outcome is settlement.Outcome.NO
    idx = lambda k: k - base.K_MIN  # noqa: E731
    assert stageb.bracket_probability(model, greater, f, D)[0] == pytest.approx(math.fsum(pmf[idx(4):]))
    assert stageb.bracket_probability(model, less, f, D)[0] == pytest.approx(math.fsum(pmf[:idx(-2)]))
    assert stageb.bracket_probability(model, between, f, D)[0] == pytest.approx(math.fsum(pmf[idx(-1):idx(2)]))


def test_tail_bins_follow_the_frozen_clamp(model):
    """DESIGN §5: mass beyond ±20 sits at k = ±20. A bracket reaching past the support gets
    exactly the end bin, and one lying wholly beyond it gets 0 (a frozen-spec property)."""
    pmf = model.pmf_for(D)
    f = 67
    p_end = stageb.bracket_probability(model, bracket("greater", floor=f + 19), f, D)[0]
    p_beyond = stageb.bracket_probability(model, bracket("greater", floor=f + 20), f, D)[0]
    p_low_end = stageb.bracket_probability(model, bracket("less", cap=f - 19), f, D)[0]
    p_all = stageb.bracket_probability(model, bracket("greater", floor=f - 40), f, D)[0]
    assert p_end == pmf[40] and p_low_end == pmf[0]
    assert p_beyond == 0.0
    assert p_all == pytest.approx(1.0, abs=1e-12)
    assert 0.0 <= p_end <= 1.0 and 0.0 <= p_all <= 1.0
