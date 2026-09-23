"""SYNTHETIC view-model fixtures for the component gallery and UI tests. Never production data.

Every market id starts with DEMO- and every title says SYNTHETIC. These rows exercise the
shared components across domains (weather, a team sport, a fight, a political event and an
economic release) plus the hard cases: unsupported payoffs, missing sides, stale and blocked
states, subcent prices, long Unicode titles and very large amounts. Account balances are
never built here: the demo takes them from a real ledger replay (`demo.py`).
"""

from __future__ import annotations

from decimal import Decimal

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
