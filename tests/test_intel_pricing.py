"""Deterministic pricing sheet for owner-confirmed Kalshi links (`edge_lab.intel.pricing`, ADR 0049).

Every market and book here is a hand-written FIXTURE under tests/fixtures/intel/kalshi/ (invented
tickers and prices). Nothing here is a recommendation. Fee hand checks use the quadratic taker
formula: all-in = ceil_cent(P + ceil_6dp(0.07 * P * (1 - P))) for one contract.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.conservative import ProbabilityBounds
from edge_lab.intel import pricing
from edge_lab.intel.contracts import INSUFFICIENT_EVIDENCE_TEXT, Action, ForecastBasis
from edge_lab.intel.pricing import (
    ACTION_POLICY_ID, Forecast, PricingPolicy, SidePricing, price_link, protected_reason, side_probabilities,
)

D = Decimal
FIX = Path(__file__).parent / "fixtures" / "intel" / "kalshi"
AS_OF = "2026-11-05T15:00:00Z"
FRESH = "2026-11-05T14:55:00Z"
POL = "KXPOLFIXTURE-26DEC31-Y"
CPI = "KXCPI-26DEC-T0.3"

NUMERIC = ("ask", "bid", "spread", "top_size", "fee_per_contract", "all_in_cost", "break_even", "p_point",
           "p_conservative", "ev_point", "ev_conservative", "return_on_capital", "max_loss", "max_acceptable_price")
EV_FIELDS = ("p_point", "p_conservative", "ev_point", "ev_conservative", "return_on_capital", "max_acceptable_price")


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def market(fixture=POL, **changes) -> dict:
    raw = load(f"market_{fixture}.json")
    raw["market"].update(changes)
    return raw


def book(fixture=POL) -> dict:
    return load(f"orderbook_{fixture}.json")


def forecast(point=0.55, low=0.47, high=0.62, basis=ForecastBasis.OWNER_JUDGMENT, calibrated=False,
             recorded="2026-11-05T14:00:00Z", abstained=False) -> Forecast:
    return Forecast("fc-1", "intel-event-1", "YES", point, low, high, basis, calibrated, recorded, abstained)


def sheet(m=None, ob="default", received=FRESH, f="default", as_of=AS_OF, policy=PricingPolicy()):
    return price_link(market_raw=market() if m is None else m, orderbook_raw=book() if ob == "default" else ob,
                      quote_received_at_utc=received, quote_evidence_id="snapshot:fixture-1",
                      forecast=forecast() if f == "default" else f, as_of_utc=as_of, policy=policy)


def assert_no_zero_placeholders(side: SidePricing, unavailable=()):
    for name in unavailable:
        assert getattr(side, name) is None, (side.side, name, getattr(side, name))


def test_fixtures_are_labelled():
    for path in FIX.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["data_kind"] == "FIXTURE" and "FIXTURE" in data["note"], path


# --------------------------------------------------------------------------- the directive example


def test_directive_example_fixture_yes_ev_is_hand_checked():
    """FIXTURE, not a recommendation: ask 38c, p = 0.55, p_cons = 0.47."""
    s = sheet()
    yes = s.yes
    assert yes.ask == D("0.38") and yes.bid == D("0.36") and yes.spread == D("0.02") and yes.top_size == D("75")
    # fee: 0.07 * 0.38 * 0.62 = 0.016492; 0.38 + 0.016492 = 0.396492 -> 0.40 all-in.
    assert yes.all_in_cost == D("0.40") and yes.break_even == D("0.40") and yes.fee_per_contract == D("0.02")
    assert yes.break_even > yes.ask
    assert yes.p_point == D("0.55") and yes.p_conservative == D("0.47")
    assert yes.ev_point == D("0.15") and yes.ev_conservative == D("0.07")  # 0.55 - 0.40, 0.47 - 0.40
    assert yes.return_on_capital == D("0.175")  # 0.07 / 0.40
    assert yes.max_loss == D("0.40")
    # Highest price with all-in <= 0.47 - 0.03 = 0.44: 0.42 (0.437052 -> 0.44); 0.43 costs 0.45.
    assert yes.max_acceptable_price == D("0.42") and yes.qualifies_on_price is True
    assert yes.depth_status == "FILLABLE"
    assert s.action is Action.INVESTIGATE and s.best_side == "YES"
    # Unverified fees: the head reason never calls it an edge (review finding 8).
    assert s.action_reasons[0] == "ESTIMATE_ONLY_FEES_UNVERIFIED"
    assert "FEE_UNVERIFIED" in s.action_reasons and "PROVISIONAL_FORECAST" in s.action_reasons
    assert s.provisional is True and s.policy_id == ACTION_POLICY_ID == "intel-action-v1"
    assert s.quote_fresh is True and s.quote_age_seconds == 300.0


def test_directive_example_no_side_hand_checked():
    no = sheet().no
    # NO ask = 1 - best YES bid 0.36 = 0.64; fee 0.07 * 0.64 * 0.36 = 0.016128 -> 0.656128 -> 0.66.
    assert no.ask == D("0.64") and no.bid == D("0.62") and no.top_size == D("120")
    assert no.all_in_cost == D("0.66") and no.fee_per_contract == D("0.02")
    assert no.p_point == D("0.45") and no.p_conservative == D("0.38")  # 1 - 0.55, 1 - 0.62
    assert no.ev_point == D("-0.21") and no.ev_conservative == D("-0.28")
    # Highest price with all-in <= 0.38 - 0.03 = 0.35: 0.33 (0.33 + 0.015477 -> 0.35); 0.34 costs 0.36.
    assert no.max_acceptable_price == D("0.33") and no.qualifies_on_price is False
    assert "ASK_ABOVE_MAX_PRICE" in no.reasons


def test_explanation_is_plain_and_never_claims_profit():
    text = sheet().explanation
    assert text == ("YES costs 38¢ plus a 2¢ fee. Your conservative estimate (47%) is above the 40¢ break-even, "
                    "leaving about 7¢ per contract after estimated (unverified) fees. Fees for this series are unverified and the "
                    "forecast is provisional, so this is not a claimable edge.")
    for s in (sheet(), sheet(f=forecast(point=0.30, low=0.25, high=0.35)), sheet(f=None)):
        assert "profit" not in s.explanation.lower() and "buy" not in s.explanation.lower()


def test_side_probabilities_match_for_side():
    b = ProbabilityBounds(0.55, 0.47, 0.62, "owner_range", 0, 0.0, 0.0)
    for side in ("YES", "NO"):
        point, cons = side_probabilities(D("0.55"), D("0.47"), D("0.62"), side)
        fp, fc = b.for_side(side)
        assert abs(float(point) - fp) < 1e-12 and abs(float(cons) - fc) < 1e-12


def test_canonical_reasons_surface_rules_unresolved_without_overriding():
    s = sheet()
    assert "RULES_UNRESOLVED" in s.yes.canonical_reasons and "RULES_UNRESOLVED" in s.no.canonical_reasons
    assert s.action is Action.INVESTIGATE  # surfaced, not overriding: the owner confirmed the link


def test_lockup_is_reported():
    s = sheet()
    assert s.lockup_policy == "STARTER_MAX_7D_V1"
    assert "SETTLEMENT_TIMING_UNVERIFIED" in s.lockup_reasons
    assert s.close_time_utc == "2026-12-31T23:59:00Z" and s.expected_resolution_utc == "2027-01-01T15:00:00Z"
    assert s.hours_to_close == pytest.approx((56 * 24 + 8 + 59 / 60), abs=1e-3)


# --------------------------------------------------------------------------- price limits and actions


def test_ask_above_fee_inclusive_max_price_is_not_investigate():
    # FIXTURE book with YES ask 0.43 (NO bid 0.57), p_cons 0.465, margin 0.03. The naive limit
    # 0.465 - 0.03 = 0.435 would admit the ask; the fee-inclusive limit does not:
    # all-in at 0.43 is 0.43 + 0.017157 -> 0.45, so ev_cons = 0.015 < 0.03.
    ob = book()
    ob["orderbook_fp"]["no_dollars"] = [["0.5700", "75.00"]]
    s = sheet(ob=ob, f=forecast(point=0.60, low=0.465, high=0.62))
    yes = s.yes
    assert yes.ask == D("0.43") and yes.all_in_cost == D("0.45")
    assert yes.ev_conservative == D("0.015")  # 0.465 - 0.45: positive but below the 0.03 margin
    assert yes.max_acceptable_price == D("0.41")  # 0.41 -> 0.426933 -> 0.43 <= 0.435; 0.42 -> 0.44 > 0.435
    assert D("0.465") - D("0.03") > yes.ask  # the naive limit would wrongly admit this ask
    assert yes.qualifies_on_price is False and "ASK_ABOVE_MAX_PRICE" in yes.reasons
    assert s.action is Action.WATCH and s.action_reasons[0] == "POINT_EDGE_ONLY"
    assert "maximum acceptable price" in s.explanation


def test_negative_conservative_and_point_ev_is_skip_no_edge():
    s = sheet(f=forecast(point=0.36, low=0.30, high=0.40))
    assert s.action is Action.SKIP and s.action_reasons[0] == "NO_EDGE"
    assert s.yes.ev_point == D("-0.04") and s.yes.ev_conservative == D("-0.10")  # 0.36 / 0.30 - 0.40
    assert s.no.ev_point == D("-0.02") and s.no.ev_conservative == D("-0.06")  # 0.64 / 0.60 - 0.66
    assert s.best_side == "NO"
    assert "lose about" in s.explanation


def test_point_edge_only_is_watch():
    s = sheet(f=forecast(point=0.45, low=0.35, high=0.50))
    assert s.yes.ev_point == D("0.05") and s.yes.ev_conservative == D("-0.05")
    assert s.action is Action.WATCH and s.best_side == "YES"
    assert s.explanation.startswith("YES costs 38¢") and "Only the point estimate (45%)" in s.explanation


def test_insufficient_size_cannot_investigate():
    ob = book()
    ob["orderbook_fp"]["no_dollars"] = [["0.6200", "0.50"]]
    s = sheet(ob=ob)
    assert s.yes.top_size == D("0.50") and "INSUFFICIENT_SIZE" in s.yes.reasons
    assert s.yes.depth_status == "DEPTH_UNKNOWN"
    assert s.action is Action.WATCH


def test_calibrated_model_forecast_still_tops_out_at_investigate():
    s = sheet(f=forecast(basis=ForecastBasis.MODEL, calibrated=True))
    assert s.action is Action.INVESTIGATE and s.provisional is False
    assert "PROVISIONAL_FORECAST" not in s.action_reasons
    assert "fees for this series are unverified" in s.explanation.lower()
    assert {a.value for a in Action} == {"INVESTIGATE", "WATCH", "SKIP", "INSUFFICIENT_EVIDENCE"}


@pytest.mark.parametrize("basis", [ForecastBasis.OWNER_JUDGMENT, ForecastBasis.AI_ASSISTED_UNVALIDATED])
def test_judgment_bases_are_provisional_even_when_marked_calibrated(basis):
    assert sheet(f=forecast(basis=basis, calibrated=True)).provisional is True


# --------------------------------------------------------------------------- fail-closed gates


def test_stale_book_is_skip_with_no_ev():
    s = sheet(received="2026-11-05T14:40:00Z")  # 20 minutes old, limit 15
    assert s.action is Action.SKIP and s.action_reasons[0] == "BOOK_STALE"
    assert s.quote_fresh is False and s.quote_age_seconds == 1200.0
    assert s.yes.ask == D("0.38") and s.yes.all_in_cost == D("0.40")  # market facts shown
    assert_no_zero_placeholders(s.yes, EV_FIELDS)
    assert_no_zero_placeholders(s.no, EV_FIELDS)
    assert "20 minutes old" in s.explanation


def test_book_at_exactly_the_limit_is_fresh():
    s = sheet(received="2026-11-05T14:45:00Z")
    assert s.quote_fresh is True and s.action is Action.INVESTIGATE


def test_future_stamped_quote_is_skip():
    s = sheet(received="2026-11-05T15:00:01Z")
    assert s.action is Action.SKIP and s.action_reasons[:2] == ("BOOK_STALE", "BOOK_TIMESTAMP_IN_FUTURE")
    assert s.quote_age_seconds is None and s.quote_fresh is False
    assert_no_zero_placeholders(s.yes, EV_FIELDS)


@pytest.mark.parametrize("received", [None, "", "not a time", "2026-11-05T14:55:00"])
def test_missing_or_naive_receipt_time_is_skip(received):
    s = sheet(received=received)
    assert s.action is Action.SKIP and "BOOK_RECEIPT_TIME_UNKNOWN" in s.action_reasons
    assert s.quote_age_seconds is None


@pytest.mark.parametrize("status", ["closed", "settled", "determined", "paused", "", None])
def test_market_not_open_is_skip(status):
    s = sheet(m=market(status=status))
    assert s.action is Action.SKIP and s.action_reasons[0] == "MARKET_NOT_OPEN"
    assert_no_zero_placeholders(s.yes, EV_FIELDS)
    assert "MARKET_CLOSED" in s.yes.canonical_reasons


def test_missing_orderbook_is_skip_book_missing():
    for ob in (None, {}, {"orderbook_fp": None}):
        s = sheet(ob=ob)
        assert s.action is Action.SKIP and s.action_reasons[0] == "BOOK_MISSING"
        assert_no_zero_placeholders(s.yes, NUMERIC)
        assert_no_zero_placeholders(s.no, NUMERIC)
        assert "BOOK_MISSING" in s.yes.canonical_reasons
        assert s.yes.fee_schedule_id == "kalshi-quadratic-taker-v1"  # fee facts still shown


def test_crossed_book_is_skip_book_anomaly():
    ob = book()
    ob["orderbook_fp"]["yes_dollars"] = [["0.4000", "10.00"]]  # yes bid 0.40 + no bid 0.62 >= 1
    s = sheet(ob=ob)
    assert s.action is Action.SKIP and s.action_reasons[0] == "BOOK_ANOMALY"
    assert_no_zero_placeholders(s.yes, NUMERIC)
    assert "BOOK_ANOMALY" in s.yes.reasons


def test_empty_book_side_has_no_size_not_zero():
    ob = book()
    ob["orderbook_fp"]["yes_dollars"] = []  # nobody bids YES, so nothing is offered on NO
    s = sheet(ob=ob)
    assert s.no.ask is None and s.no.top_size is None and s.no.ev_conservative is None
    assert "NO_OFFER" in s.no.reasons
    assert s.yes.bid is None and s.yes.spread is None
    assert s.action is Action.INVESTIGATE and s.best_side == "YES"


@pytest.mark.parametrize("ticker", ["KXHIGHNY-26NOV06-B55.5", "KXNFLGAME-26NOV08DALNYG-DAL", "KXNHLGAME-X-Y",
                                    "KXMVEXYZ-26NOV-ABC", "KXMVESPORTSMULTI-1"])
def test_protected_series_is_skip_without_pricing(ticker):
    assert protected_reason(ticker) == "PROTECTED_SCOPE"
    s = sheet(m=market(ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0]))
    assert s.ticker == ticker
    assert s.action is Action.SKIP and s.action_reasons == ("PROTECTED_SCOPE",)
    assert s.yes is None and s.no is None and s.best_side is None


def test_protected_reason_is_exact_on_series():
    assert protected_reason("KXHIGHNYC-26NOV06") is None  # a different series, not a prefix family
    assert protected_reason("KXHIGHNY") == "PROTECTED_SCOPE"
    assert protected_reason("kxmve-1") == "PROTECTED_SCOPE"
    assert protected_reason(POL) is None


def test_market_without_ticker_is_skip():
    s = sheet(m={"market": {"status": "active"}})
    assert s.action is Action.SKIP and s.action_reasons == ("MARKET_UNIDENTIFIED",)


# --------------------------------------------------------------------------- fees


def test_econ_series_is_fee_unsupported_with_no_ev_numbers():
    s = sheet(m=market(CPI), ob=book(CPI))
    assert s.action is Action.SKIP and s.action_reasons[0] == "FEE_UNSUPPORTED"
    assert "NO_EDGE" not in s.action_reasons
    assert "FEE_UNSUPPORTED — no cost-inclusive EV" in s.explanation
    for side in (s.yes, s.no):
        assert side.fee_schedule_id == "unsupported:kalshi:KXCPI" and side.fee_status == "UNSUPPORTED"
        assert side.fee_claimable is False and "FEE_UNSUPPORTED" in side.reasons
        assert side.ask is not None  # market facts still shown
        assert_no_zero_placeholders(side, ("fee_per_contract", "all_in_cost", "break_even", "ev_point",
                                           "ev_conservative", "return_on_capital", "max_loss",
                                           "max_acceptable_price"))
        assert side.qualifies_on_price is None
        assert "FEE_UNSUPPORTED" in side.canonical_reasons
    assert s.yes.ask == D("0.45") and s.no.ask == D("0.57")


def test_politics_series_is_fee_unverified_but_computed():
    s = sheet()
    for side in (s.yes, s.no):
        assert side.fee_schedule_id == "kalshi-quadratic-taker-v1"
        assert side.fee_status == "UNVERIFIED_CURRENT_SCHEDULE" and side.fee_claimable is False
        assert "FEE_UNVERIFIED" in side.reasons and side.all_in_cost is not None


# --------------------------------------------------------------------------- forecasts


def test_no_forecast_is_insufficient_evidence_with_market_facts():
    s = sheet(f=None)
    assert s.action is Action.INSUFFICIENT_EVIDENCE
    assert s.action_reasons[:2] == ("INSUFFICIENT_EVIDENCE", "NO_FORECAST")
    assert INSUFFICIENT_EVIDENCE_TEXT in s.explanation and "38¢" in s.explanation
    assert s.yes.ask == D("0.38") and s.yes.all_in_cost == D("0.40") and s.yes.break_even == D("0.40")
    assert s.no.ask == D("0.64") and s.no.all_in_cost == D("0.66")
    for side in (s.yes, s.no):
        assert_no_zero_placeholders(side, EV_FIELDS)
        assert side.qualifies_on_price is None
        assert "MODEL_UNAVAILABLE" in side.canonical_reasons and "RULES_UNRESOLVED" in side.canonical_reasons
    assert s.best_side is None and s.forecast_id is None


def test_insufficient_evidence_outranks_book_and_market_gates():
    s = sheet(f=None, m=market(status="closed"), received="2026-11-05T10:00:00Z")
    assert s.action is Action.INSUFFICIENT_EVIDENCE
    assert s.action_reasons == ("INSUFFICIENT_EVIDENCE", "NO_FORECAST", "MARKET_NOT_OPEN", "BOOK_STALE")


@pytest.mark.parametrize("f, code", [
    (forecast(abstained=True), "FORECAST_ABSTAINED"),
    (forecast(point=None), "NO_POINT_ESTIMATE"),
    (forecast(point=1.2), "FORECAST_INVALID"),
    (forecast(point=0.5, low=0.6), "FORECAST_INVALID"),
    (forecast(point=0.5, high=0.4), "FORECAST_INVALID"),
    (forecast(point=float("nan")), "FORECAST_INVALID"),
    (forecast(recorded="2026-11-05T15:00:01Z"), "FORECAST_NOT_POINT_IN_TIME"),
    (forecast(recorded="yesterday"), "FORECAST_NOT_POINT_IN_TIME"),
])
def test_unusable_forecasts_are_insufficient_evidence(f, code):
    s = sheet(f=f)
    assert s.action is Action.INSUFFICIENT_EVIDENCE and s.action_reasons[:2] == ("INSUFFICIENT_EVIDENCE", code)
    assert_no_zero_placeholders(s.yes, EV_FIELDS)
    assert s.yes.ask == D("0.38")


@pytest.mark.parametrize("low, high", [(None, None), (0.47, None), (None, 0.62)])
def test_missing_range_is_flagged_and_provisional(low, high):
    s = sheet(f=forecast(low=low, high=high, basis=ForecastBasis.MODEL, calibrated=True))
    assert s.provisional is True
    assert "NO_UNCERTAINTY_RANGE" in s.yes.reasons and "NO_UNCERTAINTY_RANGE" in s.action_reasons
    if low is None:
        assert s.yes.p_conservative == s.yes.p_point == D("0.55")
        assert s.yes.ev_conservative == D("0.15")
    if high is None:
        assert s.no.p_conservative == s.no.p_point == D("0.45")


# --------------------------------------------------------------------------- robustness


def test_bare_market_object_is_accepted():
    wrapped = market()
    assert sheet(m=dict(wrapped["market"])) == sheet(m=wrapped)


def test_deterministic_and_inputs_untouched():
    m, ob = market(), book()
    before = copy.deepcopy((m, ob))
    assert sheet(m=m, ob=ob) == sheet(m=m, ob=ob)
    assert (m, ob) == before


def test_evaluate_unavailable_never_crashes(monkeypatch):
    def boom(**kw):
        raise ValueError("cannot build")

    monkeypatch.setattr(pricing, "evaluate", boom)
    s = sheet()
    assert s.yes.canonical_reasons == ("EVALUATE_UNAVAILABLE",)
    assert s.action is Action.INVESTIGATE


def test_policy_quantity_changes_costs():
    s = sheet(policy=PricingPolicy(quantity=10))
    # 10 x 0.38 = 3.80 + fee 0.16492 = 3.96492 -> 3.97, i.e. 0.397 per contract.
    assert s.yes.all_in_cost == D("0.397") and s.yes.max_loss == D("3.97")
    assert s.yes.ev_conservative == D("0.073")


@pytest.mark.parametrize("kw", [dict(quantity=0), dict(quantity=True), dict(safety_margin=D("-0.01")),
                                dict(safety_margin=0.03), dict(max_book_age=timedelta(0))])
def test_invalid_policy_is_refused(kw):
    with pytest.raises(ValueError):
        PricingPolicy(**kw)


def test_naive_as_of_is_refused():
    with pytest.raises(ValueError):
        sheet(as_of="2026-11-05T15:00:00")


def test_no_numeric_field_is_a_zero_placeholder_where_unavailable():
    """Over every sheet built here: a field with nothing to compute from is None, never Decimal(0)."""
    money = ("ev_point", "ev_conservative", "return_on_capital", "max_acceptable_price")
    sheets = [sheet(f=None), sheet(ob=None), sheet(m=market(CPI), ob=book(CPI)), sheet(received=None)]
    for s in sheets:
        for side in (s.yes, s.no):
            for name in money:
                assert getattr(side, name) is None, (s.ticker, side.side, name)
    # With no forecast there is no probability either; an unsupported fee keeps the forecast's
    # probabilities (they are facts of the forecast) but no cost or EV.
    assert sheets[0].yes.p_point is None and sheets[0].yes.p_conservative is None
    cpi = sheets[2].yes
    assert cpi.p_point == D("0.55") and cpi.all_in_cost is None and cpi.ev_point is None


def test_sheet_fields_are_typed_as_specified():
    names = [f.name for f in dataclasses.fields(SidePricing)]
    assert names[:4] == ["side", "ask", "bid", "spread"] and names[-2:] == ["reasons", "canonical_reasons"]
    s = sheet()
    for name in NUMERIC:
        assert isinstance(getattr(s.yes, name), Decimal)


def test_pricing_module_imports_no_execution_or_network():
    tree = ast.parse(Path(pricing.__file__).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not any("execution" in m or m.split(".")[-1] in {"http", "urllib", "socket", "requests", "kalshi"}
                   for m in mods), mods


# ---------------------------------------------------------------- review regressions (PR #194)


def test_market_past_its_close_time_is_skipped_even_if_status_says_active():
    s = sheet(m=market(close_time="2026-11-01T00:00:00Z"))
    assert s.action is Action.SKIP and "MARKET_CLOSED_BY_TIME" in s.action_reasons
    assert s.yes.ev_conservative is None and "close time has passed" in s.explanation


def test_unknown_close_time_is_skipped():
    s = sheet(m=market(close_time=None))
    assert s.action is Action.SKIP and "CLOSE_TIME_UNKNOWN" in s.action_reasons


def test_no_range_can_never_investigate_and_is_not_called_conservative():
    s = sheet(f=forecast(low=None, high=None))
    assert s.action is not Action.INVESTIGATE
    assert "NO_UNCERTAINTY_RANGE" in s.action_reasons
    assert "conservative estimate" not in s.explanation.split(".")[1]
    assert "point estimate (no range given)" in s.explanation


def test_stale_book_prices_are_not_described_as_current():
    old = "2026-11-01T12:00:00Z"
    s = sheet(received=old, f=None)
    assert s.action is Action.INSUFFICIENT_EVIDENCE
    assert "offered at" not in s.explanation and "No current market price" in s.explanation
    closed = sheet(m=market(status="closed"), f=None)
    assert "offered at" not in closed.explanation
