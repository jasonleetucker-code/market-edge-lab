"""Component gallery (/gallery): demo/test mode only. Fixture view models, never production stores."""

from __future__ import annotations

from decimal import Decimal

from .. import components as c
from .. import data as d
from .. import fixtures
from .. import presentation as pr
from ..html import esc
from . import common as cm


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    rows = fixtures.synthetic_rows()
    label = '<p class="gallery-label">SYNTHETIC FIXTURES · component gallery · demo mode only</p>'
    parts = [c.page_head("Component gallery", "Every shared component in its states. Reuse these; never fork them.",
                         extra=label)]
    parts.append(c.section("MarketRow (board)", c.market_board(rows, p, label="Synthetic market rows"),
                           meta="weather · team sport · fight · politics · economics · long Unicode", sid="g-board",
                           flush=True))
    tiles = "".join([
        c.quote_tile(rows[0].quotes["YES"], "YES", "#", current=True),
        c.quote_tile(rows[0].quotes["NO"], "NO", "#"),
        c.quote_tile(rows[4].quotes["YES"], "YES", "#"),
        c.quote_tile(None, "NO", None, label="Does not pass"),
    ])
    parts.append(c.section("QuoteTile", f'<div class="quote-sum">{tiles}</div>', meta="selected · normal · subcent · "
                           "unavailable", sid="g-qt"))
    parts.append(c.section("EdgeValue and number formats", c.facts([
        ("Qualified edge", c.edge_value(rows[0].primary)),
        ("Marginally negative", c.edge_value(rows[1].primary)),
        ("Not evaluated", c.edge_value(None)),
        ("Probability difference", c.num(pr.pp(Decimal("0.052")))),
        ("Large amount", c.money_cell(Decimal("12345678.9012"))),
        ("Known zero", c.money_cell(Decimal("0"))),
        ("Unknown amount", c.money_cell(None)),
        ("Subcent price", c.num(pr.cents(Decimal("0.4825")))),
    ]), sid="g-edge"))
    parts.append(c.metric_strip([c.metric("Shadow equity", c.money_cell(Decimal("1000.00")), "Cost basis", lead=True),
                                 c.metric("Tradable cash", c.money_cell(Decimal("998.64")), "Settled"),
                                 c.metric("Realized P&L", c.money_cell(Decimal("-3.20"), signed=True), "Settled"),
                                 c.metric("Realized today", c.na("not computed"), "Not computed")],
                                label="Synthetic metric strip"))
    states = "".join([
        c.status_line("ok", "Last target captured · Sep 23", "Valid capture. Status report refreshed 11 min ago."),
        c.status_line("err", "Capture needs attention · Sep 23", "Missing forecast and decision evidence."),
        c.empty_state("Waiting for first capture", "No market books are stored yet.", action=("/", "Terminal")),
        c.unavailable("Data unavailable", "The evidence database is not configured."),
        c.error_state("Ledger could not be loaded", "ERROR — LedgerError: chain broken at entry 12."),
        c.blocked_state("New positions halted", "Remaining risk capacity is zero."),
    ])
    parts.append(c.section("StatusLine and Empty / Unavailable / Error / Blocked", states, sid="g-states"))
    vocab = " ".join(c.badge(k) for k in ("VALID", "INVALID_CAPTURE", "QUALIFY", "NO_EDGE", "BOOK_STALE", "HALTED",
                                          "CONSERVATIVE_BOUND", "TESTED", "LIVE_DATA_VERIFIED", "PASS", "something-new"))
    parts.append(c.section("State vocabulary", f"<p>{vocab}</p>", meta="unknown codes are neutral", sid="g-vocab"))
    parts.append(c.section("HistoryChart", c.history_chart([(fixtures.T0, "0.32"), (fixtures.T1, "0.34"),
                                                            ("2026-09-23T23:40:00+00:00", "0.335")],
                                                           label="Synthetic YES ask")
                           + c.history_chart([(fixtures.T1, "0.34")], label="Single observation"), sid="g-chart"))
    parts.append(c.section("ActivityRow and PipelineTimeline", '<ul class="rows">'
                           + c.activity_row("warn", "SYNTHETIC: source HTTP 503", "nws_pfm_okx", fixtures.T0)
                           + c.activity_row("ok", "SYNTHETIC: daily run healthy", "receipt", fixtures.T1) + "</ul>"
                           + c.timeline([("ok", "Decision capture", "complete", "6:00 PM EDT"),
                                         ("info", "Re-check capture", "scheduled", "6:10 PM EDT")]),
                           sid="g-act", flush=True))
    parts.append(c.disclosure("EvidenceDisclosure", c.kv([("code", c.code("INVALID_CAPTURE")),
                                                          ("exact value", esc("0.05120000"))]), boxed=True))
    return cm.Page("Component gallery", "", "".join(parts))
