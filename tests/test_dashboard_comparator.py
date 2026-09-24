"""Across venues: the market-detail slot rendered from the canonical comparator (best_price, ADR 0027).

The dashboard computes no figure here. These tests check that the four claims stay separate,
every state (populated, single route, stale, refused payoff, not evaluated, no data, error) has
its own treatment, figures match the comparator's own output, and nothing invites a stake entry.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import best_price as bp
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import components as c
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.demo import build_demo
from edge_lab.dashboard.views import markets

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "browser"))
from fixture_states import broken  # noqa: E402

CLAIM_TITLES = ("Best observed quote", "Best gross cost for size", "Best verified total cost",
                "Best account-feasible route")


def call(app, path):
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
    out = {}
    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query,
                         "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.fixture(scope="module")
def cmps():
    return fixtures.synthetic_comparisons()


@pytest.fixture(scope="module")
def demo():
    cfg, root = build_demo(experiments_root=REPO / "experiments")
    frozen = datetime.now(timezone.utc)
    cfg = dataclasses.replace(cfg, clock=lambda: frozen)
    yield cfg
    shutil.rmtree(root)


# --------------------------------------------------------------------------- component


def test_four_claims_are_separate_and_never_one_best_badge(cmps):
    html = c.venue_comparison(cmps["multi"])
    text = plain(html)
    positions = [text.index(t) for t in CLAIM_TITLES]
    assert positions == sorted(positions)  # the fixed order, each once
    assert all(text.count(t) == 2 for t in CLAIM_TITLES)  # the grid plus "What each claim means"
    assert not re.search(r">\s*BEST\s*<", html) and "Best buy" not in text and "Recommended" not in text


def test_figures_are_the_comparators_own(cmps):
    cmp = cmps["multi"]
    text = plain(c.venue_comparison(cmp))
    quote, gross = cmp.claim("BEST_OBSERVED_QUOTE"), cmp.claim("BEST_GROSS_COST_FOR_SIZE")
    verified = cmp.claim("BEST_VERIFIED_TOTAL_COST")
    assert (quote.value, gross.value, verified.value) == (Decimal("0.33"), Decimal("3.30"), Decimal("3.61"))
    assert f"{pr.cents(quote.value)} per contract · Polymarket US · lowest of 2 fresh routes" in text
    assert f"{pr.money(gross.value)} for 10 contracts · Polymarket US" in text
    assert f"{pr.money(verified.value)} for 10 contracts · Kalshi · lowest of 1 fresh route" in text
    # The account-feasible claim is absent with the comparator's own reason, never a figure.
    feasible = cmp.claim("BEST_ACCOUNT_FEASIBLE_ROUTE")
    assert not feasible.supported and feasible.reason == "NO_ACCOUNT_CONNECTED"
    assert "Best account-feasible route No account connected Not claimed" in text


def test_route_rows_separate_fee_evidence_and_verified_totals(cmps):
    text = plain(c.venue_comparison(cmps["multi"]))
    assert "Unverified estimate — not claim-grade" in text  # Polymarket US: a schedule estimate only
    assert "Unavailable: no fee model" in text  # Novig: fee unknown, never $0
    assert "Verified (exact)" in text  # the synthetic exact-fee double
    kalshi = next(r for r in cmps["multi"].routes if r.venue == "kalshi")
    assert kalshi.claim_total_cost == kalshi.total_cost and f"{pr.money(kalshi.total_cost)} Exact" in text
    # When the claim figure carries an allowance, the exact debit is shown beside it, never merged.
    padded = dataclasses.replace(kalshi, claim_total_cost=kalshi.total_cost + Decimal("0.101"))
    assert (f"{pr.money(padded.claim_total_cost)} Exact debit {pr.money(kalshi.total_cost)} plus the claim "
            "allowance") in plain(c.comparison_route(padded))
    bound = plain(c.comparison_route(dataclasses.replace(kalshi, fee_status="CONSERVATIVE_BOUND")))
    assert "At most (conservative bound)" in bound
    assert "Not verified" in text  # routes without a claim-grade total show — plus the reason
    assert "$0.00" not in text


def test_related_markets_are_labelled_and_unranked(cmps):
    cmp = cmps["multi"]
    html = c.venue_comparison(cmp)
    assert cmp.related == ("kalshi:DEMO-HIGH-B69.5",)
    related_block = html[html.index("Related markets · unranked"):]
    assert "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT" in related_block
    assert "Never priced against this market".lower() in plain(related_block).lower()
    # Its captured 12¢ ask (far below every equivalent route) appears nowhere.
    assert "12¢" not in plain(html)


def test_stale_routes_are_named_and_never_ranked(cmps):
    multi = plain(c.venue_comparison(cmps["multi"]))
    assert "Not ranked because the book is stale or of unknown age: novig:DEMO-HIGH-67-68." in multi
    assert "Routes not ranked by any claim" in multi and "Stale quote — not ranked" in multi
    stale = plain(c.venue_comparison(cmps["stale"]))
    assert stale.count("Not claimed") == 4
    assert "Routes ranked by at least one claim" not in stale
    assert "kalshi:DEMO-HIGH-B67.5, polymarket_us:demo-high-67-68" in stale


def test_unsupported_payoff_is_refused_not_reinterpreted(cmps):
    html = c.venue_comparison(cmps["refused"])
    text = plain(html)
    assert "Comparison refused: payoff not supported" in text and 'class="empty k-warn"' in html
    assert text.count("Payoff not supported") >= 4 and "Not assessed" in text
    assert "¢ per contract" not in text


def test_single_captured_route_says_nothing_is_ranked_across_venues(cmps):
    text = plain(c.venue_comparison(cmps["single"]))
    assert "Only Kalshi is captured for this market." in text
    assert "for 1 contract ·" in text and "for 1 contracts" not in text
    assert "Fees unverified Not claimed" in text


def test_no_stake_entry_or_order_control(cmps):
    for cmp in cmps.values():
        html = c.venue_comparison(cmp).lower()
        for tag in ("<input", "<form", "<button", "<select", "<textarea"):
            assert tag not in html
        assert "submit" not in html and "place order" not in html


def test_bounds_that_overlap_prove_no_order():
    cmp = fixtures.synthetic_comparisons()["multi"]
    claim = cmp.claim("BEST_VERIFIED_TOTAL_COST")
    two = dataclasses.replace(claim, candidates=(claim.market_id, "polymarket_us:demo-high-67-68"), proven_below=())
    shown = dataclasses.replace(cmp, claims=tuple(two if c_.kind == claim.kind else c_ for c_ in cmp.claims))
    assert "No proven order against: polymarket_us:demo-high-67-68 (cost bounds overlap)" in plain(
        c.venue_comparison(shown))


def test_claim_value_text_formats_without_computing():
    route = fixtures.synthetic_comparisons()["multi"].routes[0]
    bound = dataclasses.replace(route, fee_status="CONSERVATIVE_BOUND")
    make = lambda kind, value: bp.Claim(kind, True, route.market_id, route.venue, Decimal(value), "", None, "",  # noqa: E731
                                        (route.market_id,))
    assert pr.claim_value_text(make("BEST_OBSERVED_QUOTE", "0.4825"), route) == "48.25¢"
    assert pr.claim_value_text(make("BEST_GROSS_COST_FOR_SIZE", "4.05"), bound) == "$4.05"
    assert pr.claim_value_text(make("BEST_VERIFIED_TOTAL_COST", "4.331"), bound) == "at most $4.331"
    assert pr.claim_value_text(make("BEST_VERIFIED_TOTAL_COST", "4.331"), route) == "$4.331"
    absent = bp.Claim("BEST_VERIFIED_TOTAL_COST", False, None, None, None, "", "FEE_UNVERIFIED", "", ())
    assert pr.claim_value_text(absent, route) is None


# --------------------------------------------------------------------------- states


@pytest.mark.parametrize("status,title,kind", [
    ("NOT_EVALUATED", "Not evaluated yet", "nd"),
    (d.NO_DATA, "No captured book to compare", "nd"),
    (d.ERROR, "Comparison unavailable", "err"),
])
def test_every_non_ok_state_has_its_own_treatment(status, title, kind):
    html = markets.comparison_body(d.VenueComparison(status, "some reason"))
    assert title in html and f'class="empty k-{kind}"' in html and "some reason" in html.lower()
    if status == d.ERROR:
        assert 'role="alert"' in html and "not an empty comparison" in html


def test_adapter_needs_an_evaluated_size_and_time(demo):
    ctx = d.Context(demo)
    for size in (None, 0, -1, "abc", True):
        assert d.venue_comparison(ctx, "kalshi:DEMO-B71.5", "YES", size, "2026-09-23T15:00:00+00:00").status \
            == "NOT_EVALUATED"
    assert d.venue_comparison(ctx, "kalshi:DEMO-B71.5", "YES", 1, None).status == "NOT_EVALUATED"
    assert d.venue_comparison(ctx, "kalshi:NOT-CAPTURED", "YES", 1, "2026-09-23T15:00:00+00:00").status == d.NO_DATA


def test_adapter_on_a_read_error_is_error_and_without_a_store_is_no_data(tmp_path):
    cfg, _ = broken(tmp_path)
    result = d.venue_comparison(d.Context(cfg), "kalshi:X", "YES", 1, "2026-09-23T15:00:00+00:00")
    assert result.status == d.ERROR and result.comparison is None
    empty = d.venue_comparison(d.Context(Config()), "kalshi:X", "YES", 1, "2026-09-23T15:00:00+00:00")
    assert empty.status == d.NO_DATA


def test_adapter_runs_the_comparator_on_the_decision_capture(demo):
    ctx = d.Context(demo)
    market = next(m for m in ctx.observed.value.markets if m.market_id == "kalshi:DEMO-B71.5")
    book = market.books["decision"]
    quote = market.quotes["decision"]["YES"]
    as_of = (datetime.fromisoformat(book.received_at_utc) + timedelta(seconds=30)).isoformat()
    result = d.venue_comparison(ctx, market.market_id, "YES", 1, as_of)
    assert result.status == d.OK
    cmp = result.comparison
    (route,) = cmp.routes
    assert (route.equivalence, route.freshness, route.book_evidence_id) == ("REFERENCE", "fresh", book.evidence_id)
    # The top of the depth ladder is the captured quote the rest of the page shows.
    assert route.observed_ask == quote.ask and cmp.claim("BEST_OBSERVED_QUOTE").value == quote.ask
    assert cmp.quantity == 1 and cmp.execution_authorized is False
    # An hour later the same book is stale: named, never ranked.
    late = d.venue_comparison(ctx, market.market_id, "YES", 1,
                              (datetime.fromisoformat(book.received_at_utc) + timedelta(hours=1)).isoformat())
    assert all(not c_.supported for c_ in late.comparison.claims)
    assert late.comparison.claim("BEST_OBSERVED_QUOTE").stale_candidates == (market.market_id,)


@pytest.mark.parametrize("url,depth", [
    ("https://api.elections.kalshi.com/trade-api/v2/markets/X/orderbook?depth=100", 100),
    ("demo://book/DEMO-B67.5", None), (None, None), ("https://x/y?depth=abc", None),
])
def test_depth_limit_comes_from_the_stored_request_url(url, depth):
    assert d._depth_limit(url) == depth


# --------------------------------------------------------------------------- pages


def test_detail_page_shows_the_comparison_at_the_evaluated_size(demo):
    app = make_app(demo)
    status, body = call(app, "/market?venue=kalshi&id=DEMO-B71.5&side=YES")
    assert status == "200 OK"
    section = body[body.index('aria-labelledby="xv-h"'):]
    section = section[:section.index("</section>")]
    text = plain(section)
    assert "YES · 1 contract (evaluated size) · as of" in text
    assert all(t in text for t in CLAIM_TITLES)
    assert "<input" not in section and "<form" not in section
    status, body = call(app, "/market?venue=kalshi&id=DEMO-B71.5&side=NO")
    assert "Not evaluated yet" in plain(body[body.index('aria-labelledby="xv-h"'):])


def test_gallery_shows_every_comparison_state(demo):
    status, body = call(make_app(demo), "/gallery")
    text = plain(body)
    assert status == "200 OK"
    for needle in ("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", "Only Kalshi is captured for this market.",
                   "Comparison refused: payoff not supported", "Not ranked because the book is stale",
                   "Not evaluated yet", "No captured book to compare", "Comparison unavailable"):
        assert needle in text, needle
