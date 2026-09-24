"""SYNTHETIC view-model fixtures for the component gallery and UI tests. Never production data.

Every market id starts with DEMO- and every title says SYNTHETIC. These rows exercise the
shared components across domains (weather, a team sport, a fight, a political event and an
economic release) plus the hard cases: unsupported payoffs, missing sides, stale and blocked
states, subcent prices, long Unicode titles and very large amounts. Account balances are
never built here: the demo takes them from a real ledger replay (`demo.py`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from .. import best_price as bp
from ..fee_schedules import (
    POLYMARKET_US_EXCHANGE_SCOPE, CostModel, FeeScheduleStatus, QuadraticTakerSchedule, schedule_for,
)
from ..opportunity import (
    DepthLadder, DepthLevel, Event, Market, MarketStatus, MarketTiming, Payoff, PriceGrid, PriceRange,
)
from . import presentation as pr

T0 = "2026-09-23T21:55:04+00:00"
T1 = "2026-09-23T22:11:40+00:00"


def _q(side: str, label: str | None, price: str | None, *, size: str | None = "120", change: str | None = None,
       anomaly: str | None = None, at: str = T1) -> pr.QuoteSide:
    return pr.QuoteSide(side, label, None if price is None else Decimal(price), None if size is None else Decimal(size),
                        at, "recheck", f"snapshot:DEMO-{side}", anomaly,
                        None if change is None else Decimal(change), T0 if change is not None else None,
                        "Change in the captured ask for this side since the decision capture" if change is not None
                        else "Change unavailable: no comparable earlier observation")


def _a(side: str, qual: str, reason: str, p: str, price: str, edge: str, *, size: int | None = 1,
       reasons: tuple[str, ...] = (), eta: str | None = "2026-09-25T02:00:00+00:00", hours: str = "52.1",
       starter_reasons: tuple[str, ...] = (), fill: str | None = "FILLED") -> pr.Assessment:
    starter = {"eligible": not starter_reasons, "reasons": list(starter_reasons),
               "tradable_cash_release_eta_utc": eta, "elapsed_hours_to_tradable": hours, "policy_id": "STARTER_MAX_7D_V1"}
    return pr.Assessment(
        account_id="SYNTHETIC", decision_id=f"dec-DEMO-{side}-{reason}", decided_at_utc=T0, side=side, outcome=None,
        qualification=qual, reason=reason, reasons=reasons or (() if qual == "QUALIFY" else (reason,)),
        model_probability=Decimal(p), conservative_probability=Decimal(p) - Decimal("0.03"),
        executable_price=Decimal(price), displayed_size=Decimal("120"), fee=Decimal("0.0158"),
        all_in_cost=Decimal(price) + Decimal("0.02"), net_edge=Decimal(edge), net_edge_conservative=Decimal(edge) -
        Decimal("0.03"), fee_status="PARTIALLY_VERIFIED", claim_basis="CONSERVATIVE_BOUND", model_id="DEMO/model",
        model_version="demo", freshness="fresh", size=size if qual == "QUALIFY" else None,
        binding_constraint="fixed_contracts" if qual == "QUALIFY" else None, fill_status=fill if qual == "QUALIFY"
        else None, fill_reason=fill if qual == "QUALIFY" else None, starter=starter,
        fill_cost=Decimal(price) + Decimal("0.02") if qual == "QUALIFY" and fill == "FILLED" else None)


def _row(mid: str, domain: str, title: str, outcome: str, quotes: dict, assessments: tuple, *, league: str | None = None,
         payoff: str | None = "binary", venue: str = "kalshi") -> pr.MarketRow:
    return pr.MarketRow(venue=venue, market_id=f"{venue}:{mid}", native_id=mid, domain=domain, league=league,
                        title=f"SYNTHETIC · {title}", outcome=outcome, target_date="2026-09-24", status="active",
                        close_time_utc="2026-09-24T21:00:00+00:00", rules_primary="SYNTHETIC rules text for the gallery.",
                        payoff_kind=payoff, event_id=f"{domain}:demo:{mid}", quotes=quotes, assessments=assessments,
                        observed=True)


def synthetic_rows() -> list[pr.MarketRow]:
    return [
        _row("DEMO-HIGHNY-B67.5", "weather", "Highest temperature in NYC on Sep 24?", "67° to 68°",
             {"YES": _q("YES", "67° to 68°", "0.34", change="0.02"), "NO": _q("NO", "Not 67° to 68°", "0.67")},
             (_a("YES", "QUALIFY", "QUALIFY", "0.41", "0.34", "0.0512"),)),
        _row("DEMO-NFL-KCBUF", "sports", "Kansas City at Buffalo — winner", "Buffalo",
             {"YES": _q("YES", "Buffalo", "0.4825", change="-0.0125"), "NO": _q("NO", "Kansas City", "0.53")},
             (_a("YES", "REJECT", "NO_EDGE", "0.47", "0.4825", "-0.0003"),), league="nfl"),
        _row("DEMO-UFC-MAINEVENT", "sports", "Main event: fighter A vs fighter B — method of victory",
             "Fighter A by KO/TKO", {"YES": _q("YES", "Fighter A by KO/TKO", "0.21")},
             (), league="ufc", payoff="multi_outcome"),
        _row("DEMO-SENATE-VOTE", "politics", "Will the Senate pass the appropriations bill by Oct 1?", "Passes by Oct 1",
             {"YES": _q("YES", "Passes by Oct 1", "0.62", anomaly=None), "NO": _q("NO", "Does not pass", None,
                                                                               anomaly="no ask in the captured book")},
             (_a("YES", "REJECT", "BOOK_STALE", "0.70", "0.62", "0.06", reasons=("BOOK_STALE", "FEE_UNSUPPORTED")),)),
        _row("DEMO-CPI-OCT", "economics", "CPI year-over-year for September above 2.9%?", "Above 2.9%",
             {"YES": _q("YES", "Above 2.9%", "0.005"), "NO": _q("NO", "2.9% or below", "0.996")},
             (_a("NO", "QUALIFY", "QUALIFY", "0.999", "0.996", "0.0009", eta="2026-10-20T14:00:00+00:00",
                 hours="628.5", starter_reasons=("HORIZON_OVER_7D",), fill="STARTER_POLICY_INELIGIBLE"),)),
        _row("DEMO-LONG-UNICODE", "other", "Très long marché: will the São Paulo–Zürich rail link carry ≥ 1,000,000 "
             "passengers in its first calendar year of full commercial service after the opening ceremony?",
             "≥ 1,000,000 passengers", {}, ()),
    ]


# --------------------------------------------------------------------------- across venues (best_price)
# SYNTHETIC routes run through the real comparator (`best_price.compare`): every claim, exclusion
# and figure the gallery shows is the comparator's own output, never a hand-written verdict. No
# cross-venue market has been shown rule-equivalent in real data; these pairs are constructed.

CMP_AS_OF = "2026-09-23T22:00:00+00:00"
_FRESH = "2026-09-23T21:59:30+00:00"
_STALE = "2026-09-23T21:40:00+00:00"
_SETTLES = "SYNTHETIC settlement source: DEMO city daily high, Sep 24"
_EV_K = Event("weather", "weather:demo:DEMO-HIGH-0924", "2026-09-24", None, "DEMO-HIGH-0924", _SETTLES)
_EV_P = replace(_EV_K, event_id="weather:demo:DEMO-HIGH-0924-pm")
_EV_N = replace(_EV_K, event_id="weather:demo:DEMO-HIGH-0924-nv")
_K = Market(venue="kalshi", market_id="kalshi:DEMO-HIGH-B67.5", native_id="DEMO-HIGH-B67.5", event_id=_EV_K.event_id,
            outcome="67° to 68°", payoff=Payoff("binary", Decimal(1), "value in [67, 68]"), rules_sha256="ab" * 32,
            status=MarketStatus.OPEN, rules_resolved=True, rules_detail="SYNTHETIC",
            timing=MarketTiming(expected_resolution_utc="2026-09-25T14:00:00+00:00", settlement_timer_seconds=3600,
                                lifecycle_status="active"),
            price_grid=PriceGrid((PriceRange(Decimal(0), Decimal(1), Decimal("0.01")),), source="SYNTHETIC cent grid"))
_P = replace(_K, venue="polymarket_us", market_id="polymarket_us:demo-high-67-68", native_id="demo-high-67-68",
             event_id=_EV_P.event_id, rules_sha256="cd" * 32, timing=MarketTiming(lifecycle_status="open"))
_N = replace(_K, venue="novig", market_id="novig:DEMO-HIGH-67-68", native_id="DEMO-HIGH-67-68", event_id=_EV_N.event_id,
             rules_sha256="ef" * 32, timing=None)
_SIBLING = replace(_K, market_id="kalshi:DEMO-HIGH-B69.5", native_id="DEMO-HIGH-B69.5", outcome="69° to 70°",
                   payoff=Payoff("binary", Decimal(1), "value in [69, 70]"), rules_sha256="12" * 32)
# A SYNTHETIC exact-fee double, so the gallery can show a supported verified-total claim. Real
# Kalshi evidence is CONSERVATIVE_BOUND at best (ADR 0017).
_EXACT_FEES = QuadraticTakerSchedule("SYNTHETIC-exact-fee-double", "kalshi", Decimal("0.07"), Decimal(1),
                                     FeeScheduleStatus.VERIFIED, "SYNTHETIC gallery fee double", "2026-09-20T00:00:00Z",
                                     cost_model=CostModel.EXACT)


def _ladder(m: Market, *levels: tuple[str, str], at: str = _FRESH, truncated: bool = False) -> DepthLadder:
    return DepthLadder(m.venue, m.market_id, "YES", tuple(DepthLevel(Decimal(a), Decimal(b)) for a, b in levels),
                       truncated, at, None, f"snapshot:DEMO-{m.venue}", None)


def synthetic_comparisons() -> dict[str, bp.Comparison]:
    """name -> comparator output for the gallery: several venues with a related market and a stale
    route; every route stale; a refused payoff; and one captured route with a truncated book (the
    only shape real captures produce today)."""
    pm_fees = schedule_for("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE)
    at, age = pr.parse_utc(CMP_AS_OF), timedelta(minutes=5)
    request = bp.PositionRequest(_EV_K, _K, "YES", 10)

    def run(req: bp.PositionRequest, *routes: bp.Route) -> bp.Comparison:
        return bp.compare(req, routes, as_of=at, max_book_age=age)

    refused_market = replace(_K, payoff=replace(_K.payoff, kind="multi_outcome"))
    return {
        "multi": run(request,
                     bp.Route(_EV_K, _K, _ladder(_K, ("0.34", "6"), ("0.35", "20")), _EXACT_FEES),
                     bp.Route(_EV_P, _P, _ladder(_P, ("0.33", "40")), pm_fees),
                     bp.Route(_EV_N, _N, _ladder(_N, ("0.31", "50"), at=_STALE), schedule_for("novig")),
                     bp.Route(_EV_K, _SIBLING, _ladder(_SIBLING, ("0.12", "80")), _EXACT_FEES)),
        "stale": run(request,
                     bp.Route(_EV_K, _K, _ladder(_K, ("0.34", "30"), at=_STALE), _EXACT_FEES),
                     bp.Route(_EV_P, _P, _ladder(_P, ("0.33", "40"), at=_STALE), pm_fees)),
        "refused": run(bp.PositionRequest(_EV_K, refused_market, "YES", 10),
                       bp.Route(_EV_K, refused_market, _ladder(refused_market, ("0.34", "30")), _EXACT_FEES)),
        "single": run(bp.PositionRequest(_EV_K, _K, "YES", 1),
                      bp.Route(_EV_K, _K, _ladder(_K, ("0.34", "3"), truncated=True), schedule_for("kalshi", "DEMO"))),
    }


# --------------------------------------------------------------------------- research sizing (sizing_counterfactual)
# SYNTHETIC panels in the exact shape of Lane A's `sizing_counterfactual.panel_for_market` contract
# (panel_version 1). Every number is a string, as the contract gives it. Gallery and tests only.

SIZING_LABEL = "RESEARCH SIZING - SHADOW SIZING CHALLENGER (counterfactual; not a bet recommendation)"
SIZING_UNAVAILABLE = ("No model", "Fees unsupported", "Stale quote", "Rules unresolved",
                      "Insufficient uncertainty evidence", "Risk state unavailable", "Unsupported payoff")
SIZING_NO_SIDES = ("No recorded decision", "Ledger unavailable", "No sizing policy")
_POLICIES = (("A", "sizing-v2-flat-1"), ("B", "sizing-v2-fixed-pct"), ("C", "sizing-v2-kelly-full"),
             ("D", "sizing-v2-kelly-half"), ("E", "sizing-v2-kelly-quarter"), ("F", "sizing-v2-robust-kelly"),
             ("G", "sizing-v2-drawdown-kelly"), ("H", "sizing-v2-candidate"))
# letter -> (verdict, binding constraint, contracts, amount, fraction of bankroll): contract strings.
_SIZES = {letter: ("SIZE", "NONE", "1", "0.36", "0.00036") for letter, _ in _POLICIES}
_SIZES.update(C=("SIZE", "LIQUIDITY", "12", "4.32", "0.00432"), D=("SIZE", "POSITION_CAP", "6", "2.16", "0.00216"))


def _comparison(h: tuple[str, str, str, str, str], *, refused: bool = False) -> list[dict]:
    sizes = {**_SIZES, "H": h}
    if refused:  # the engine refuses the same inputs under every policy
        # A refused row carries placeholder zeros (as the engine's blocked rows do): never computed.
        sizes = {letter: ("UNSUPPORTED", "MODEL_UNAVAILABLE", "0", "0", "0E-10") for letter, _ in _POLICIES}
    return [{"letter": letter, "policy_id": pid, "policy_version": "1", "verdict": sizes[letter][0],
             "binding_constraint": sizes[letter][1], "final_contracts": sizes[letter][2],
             "final_amount": sizes[letter][3], "bankroll_before": "1000.00", "fraction_of_bankroll": sizes[letter][4]}
            for letter, pid in _POLICIES]


def _panel(sides: list[dict], *, available: bool = True, reason: str | None = None,
           detail: str | None = None) -> dict:
    return {"panel_version": "1", "label": SIZING_LABEL, "market_id": "kalshi:DEMO-HIGHNY-B67.5",
            "as_of_utc": T0, "available": available, "unavailable_reason": reason, "unavailable_detail": detail,
            "primary_policy": {"letter": "H", "policy_id": "sizing-v2-candidate", "policy_version": "1",
                               "description": "SYNTHETIC: robust fractional Kelly with hard caps"},
            "sides": sides, "limitations": ["SYNTHETIC: depth is the recorded top of book only.",
                                            "No statistical significance is implied by a few settlements."]}


def _side(side: str, *, verdict: str = "SIZE", contracts: str = "3", amount: str = "1.08",
          binding: str = "POSITION_CAP", fraction: str = "0.00108", reason: str | None = None) -> dict:
    primary = {
        "policy_id": "sizing-v2-candidate", "policy_version": "1", "verdict": verdict, "block_reason": None,
        "bankroll_basis": {"bankroll": "1000.00", "tradable_cash": "998.64", "available_risk_budget": "24.00"},
        "model_probability": "0.41", "conservative_probability": "0.38", "expected_net_edge": "0.0512",
        "uncertainty": {"method": "recorded_bounds", "payout_probability_min": "0.38",
                        "payout_probability_max": "0.44", "detail": "SYNTHETIC"},
        "entry_price": "0.34", "estimated_fee": "0.06", "unconstrained_kelly_amount": "4.32",
        "policy_amount_before_caps": "1.44",
        "caps": {"liquidity": "40.80", "position": "1.08", "event": "5.00", "cluster": "5.00", "portfolio": "24.00",
                 "cash_horizon": None, "drawdown": "12.00", "maximum_allowed": "1.08"},
        "capital_horizon": {"policy_id": "STARTER_MAX_7D_V1", "eligible": True,
                            "tradable_cash_release_eta_utc": "2026-09-25T02:00:00+00:00",
                            "elapsed_hours_to_tradable": "52.1", "reasons": []},
        "drawdown_cap": "12.00", "final_contracts": contracts, "final_amount": amount, "binding_constraint": binding,
        "secondary_constraints": ["EVENT_CAP"],
        "explanation": f"SYNTHETIC: {contracts} contracts under policy H; {binding} binds.",
        "fill_status": "FILLED" if contracts != "0" else None, "fill_reason": None}
    if reason is not None:  # a refusal: the engine stops before the optimizer, figures are not computed
        primary.update(verdict="UNSUPPORTED", block_reason="MODEL_UNAVAILABLE", expected_net_edge=None,
                       entry_price=None, estimated_fee=None, unconstrained_kelly_amount=None,
                       policy_amount_before_caps=None, final_contracts="0", final_amount="0",
                       binding_constraint="MODEL_UNAVAILABLE", explanation=None, fill_status=None)
    return {"side": side, "decision_id": f"dec-DEMO-{side}", "decision_time": T0,
            "recorded_qualification": "QUALIFY" if reason is None else "REJECT",
            "recorded_reason": "QUALIFY" if reason is None else "MODEL_UNAVAILABLE", "model_version": "demo",
            "recorded_in_accounts": ["EXP-001-shadow", "EXP-001-stage-b-research"],
            "merged_decision_ids": [f"dec-DEMO-{side}", f"dec-DEMO-{side}-research"],
            "available": reason is None, "unavailable_reason": reason,
            "unavailable_detail": None if reason is None else f"SYNTHETIC engine detail for: {reason}",
            "top_of_book_limited": True, "primary": primary,
            "comparison": _comparison((verdict, binding, contracts, amount, fraction), refused=reason is not None)}


def synthetic_sizing_panels() -> dict[str, dict]:
    """name -> a contract-shaped panel: sized (with the other side refused), a computed zero, each
    directive reason as the contract returns it (every side refused with that reason, the panel
    unavailable), and the two reasons with no side at all (no decision, ledger unavailable)."""
    panels = {
        "sized": _panel([_side("YES"), _side("NO", reason="No model")]),
        "zero": _panel([_side("YES", verdict="ZERO_EDGE", contracts="0", amount="0", binding="ZERO_EDGE",
                              fraction="0")]),
    }
    for reason in SIZING_UNAVAILABLE:
        side = _side("YES", reason=reason)
        panels[reason] = _panel([side], available=False, reason=reason, detail=side["unavailable_detail"])
    for reason in SIZING_NO_SIDES:
        panels[reason] = _panel([], available=False, reason=reason, detail=f"SYNTHETIC detail for: {reason}")
    return panels


# --------------------------------------------------------------------------- The Odds API pilot and alert origins
# SYNTHETIC `odds_pilot.dashboard_status` results and failure records, in the contracts' shapes.

ODDS_LABEL = "OFFERED ODDS - RESEARCH ONLY, NOT EXECUTABLE"


def synthetic_odds_statuses() -> dict[str, dict]:
    """state -> a status dict: setup needed, active with a verified live read, degraded, cost
    blocked and error; plus an ACTIVE claim without a verified read (shown as unverified)."""
    def status(state: str, *, verified: bool = False, detail: str = "") -> dict:
        return {"schema": "SYNTHETIC", "state": state, "detail": detail or f"SYNTHETIC: {state}", "label": ODDS_LABEL,
                "executable": False, "live_read_verified": verified, "timer": "NOT_OBSERVABLE_HERE",
                "latest_successful_capture": {"received_at_utc": T0, "offers": 214, "freshness": "stale"}
                if verified else None,
                "quota": {"state": "OK" if verified else "QUOTA_UNKNOWN", "used_local": 36 if verified else 0,
                          "ceiling": 450, "provider_remaining": "414" if verified else None,
                          "detail": "SYNTHETIC quota"},
                "markets_observed": ["h2h", "spreads", "totals"] if verified else [],
                "bookmakers_observed": ["SYNTHETIC-book"] if verified else [],
                "discovery": {"last_success_utc": T0, "fresh": True} if verified else None,
                "targets": None, "next_capture": {"due_utc": T1, "offset": "T-60m", "event_id": "DEMO-NFL-EVENT"}
                if verified else None, "cost_block": None, "pilot_state_file": "OK" if verified else "MISSING",
                "problems": []}
    return {
        "SETUP_NEEDED": status("SETUP_NEEDED", detail="SYNTHETIC: the owner installs the free read-only key "
                                                     "privately (sudoedit); nothing was sent."),
        "ACTIVE": status("ACTIVE", verified=True),
        "DEGRADED": status("DEGRADED", verified=True, detail="SYNTHETIC: the latest paid capture attempt failed"),
        "COST_BLOCKED": status("COST_BLOCKED"),
        "ERROR": status("ERROR", detail="SYNTHETIC: quota ledger unreadable: JSONDecodeError"),
        "ACTIVE_UNVERIFIED": status("ACTIVE"),
    }


def synthetic_failure_record(unit: str, origin: str | None = None) -> dict:
    record = {"unit": unit, "failed_at_utc": T0, "invocation_id": "0123456789abcdef0123456789abcdef"}
    if origin is not None:
        record["origin"] = origin
    return record
