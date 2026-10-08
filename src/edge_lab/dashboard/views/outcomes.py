"""Outcomes (/outcome-board): What matters today. docs/design/UI_CONTRACT.md §15."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...kalshi import event_ticker_of
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from . import ops_common as oc
from .ops_portfolio import actual_body, omitted_note, snapshot_line

HORIZON_LABELS = {"within_1_hour": "Within 1 hour", "within_1_day": "Within 1 day", "within_1_week": "Within 1 week",
                  "later": "Later than 1 week", "unknown": "Unknown", "settled": "Settled",
                  "overdue": "Overdue · still open after its expected settlement"}
# Journey J8 (acceptance §2): the outcome board joined with the execution status export. The export carries positions,
# settlements and venue-reported P&L per market, but no cost basis, worst case or expected settlement time per
# position, so those read unknown here: the board's bounds are never recomputed in the page.
EXEC_NO_BOUND = "not in the execution export: it records no cost basis or worst case per position"
EXEC_NO_SETTLE_TIME = "not in the execution export: it records no expected settlement time"
EXEC_GROUP_WORDS = {"OPEN": ("Open", pr.INFO_K), "PARTIALLY_SETTLED": ("Partly settled", pr.WARN_K),
                    "SETTLED": ("Settled", pr.ND_K),
                    "CLOSED": ("Exited before settlement", pr.ND_K),
                    "HOLDINGS_UNKNOWN": ("Holdings unknown", pr.WARN_K)}


def group_row(g, top) -> str:
    domain = pr.DOMAIN_LABELS.get(pr.domain_of(g.outcome_cluster), "Other")
    sub = (f"{domain} · {len(g.event_ids)} event(s) · {len(g.positions)} linked position(s) · "
           f"{HORIZON_LABELS.get(g.horizon, g.horizon)}")
    facts = c.facts([
        ("Current exposure", c.money_cell(g.current_exposure)),
        ("Max loss (upper bound)", c.money_cell(g.max_account_loss)),
        ("Max gain (upper bound)", c.money_cell(g.max_account_gain)),
        ("Settles by", c.txt(pr.datetime_et(g.settles_by_utc), reason="no expected settlement time")),
    ])
    linked = c.table(["position", "market", "side", "qty", "cost basis", "potential payout", "status", "net P&L"],
                     [[c.code(x.position_id), esc(x.market_id), esc(x.side), esc(x.quantity), c.money_cell(x.cost_basis),
                       c.money_cell(x.potential_payout), c.code(x.status), c.money_cell(x.net_pnl, signed=True)]
                      for x in g.positions], caption="Linked positions")
    why = c.disclosure("Why it matters", c.kv([
        ("outcome cluster", c.code(g.outcome_cluster)), ("events", c.ul(g.event_ids)),
        ("account impact", c.money_cell(g.account_impact)), ("realized P&L", c.money_cell(g.realized_pnl, signed=True)),
        ("positions without a settlement time", esc(g.unknown_settlement_positions)),
        ("horizon", c.code(g.horizon)), ("status", c.code(g.status)),
        ("worst-case method", esc(g.worst_case_method)), ("best-case method", esc(g.best_case_method)),
    ]) + '<h4 class="eyebrow">Linked positions and contributions</h4>' + linked)
    bar = c.bar(g.current_exposure, top, label=f"Current exposure {pr.money(g.current_exposure)} of the largest "
                                                f"{pr.money(top)} shown")
    return c.row(esc(pr.cluster_label(g.outcome_cluster)), sub=sub, aside=c.state_text(g.status), body=bar + facts + why)


def _event_of(ticker: Any, event: Any = None) -> str:
    """The Kalshi event a market belongs to: the record's own event ticker, else `kalshi.event_ticker_of`."""
    if isinstance(event, str) and event:
        return event
    return event_ticker_of(ticker) if isinstance(ticker, str) and ticker else "unknown event"


def _realized(doc: dict) -> dict[Any, Any] | None:
    """Venue-reported realized P&L per market, or None while no baseline is recorded (unknown, never zero)."""
    pnl = oc.g(doc, "pnl") or {}
    if not pnl.get("baseline_recorded"):
        return None
    return {r.get("market_ticker"): r.get("realized_pnl") for r in oc.lst(pnl, "by_market") or []}


def execution_groups(doc: dict) -> list[tuple[str, list[dict], list[dict], list[str]]]:
    """(event, held positions, settlement rows, markets with venue P&L only) per event, open events first. A market
    exited before settlement is neither held nor settled, but its venue P&L belongs to the outcome. Grouping only:
    no figure is computed."""
    groups: dict[str, tuple[list, list, list]] = {}
    seen: set = set()
    for pos in oc.lst(doc, "account", "positions") or []:
        groups.setdefault(_event_of(pos.get("market_ticker")), ([], [], []))[0].append(pos)
        seen.add(pos.get("market_ticker"))
    for row in oc.lst(doc, "settlements", "rows") or []:
        groups.setdefault(_event_of(row.get("ticker"), row.get("event_ticker")), ([], [], []))[1].append(row)
        seen.add(row.get("ticker"))
    for ticker in sorted((_realized(doc) or {}).keys() - seen, key=str):
        groups.setdefault(_event_of(ticker), ([], [], []))[2].append(ticker)
    return sorted(((k, *v) for k, v in groups.items()), key=lambda g: (not g[1], g[0]))


def holdings_known(doc: dict) -> bool:
    return oc.g(doc, "account", "snapshot") is not None and oc.lst(doc, "account", "positions") is not None


def execution_group_row(event: str, held: list[dict], settled: list[dict], closed: list[str], doc: dict) -> str:
    """One event. When no snapshot lists positions, what is held is unknown: never 0 held, never "settled"."""
    env = doc.get("environment")
    realized = _realized(doc)
    known = holdings_known(doc)
    settled_by = {r.get("ticker"): r for r in settled}
    if not known:
        status = "HOLDINGS_UNKNOWN"
    else:
        status = ("OPEN" if not settled else "PARTIALLY_SETTLED") if held else "SETTLED" if settled else "CLOSED"
    label, kind = EXEC_GROUP_WORDS[status]
    tickers = sorted({p.get("market_ticker") for p in held} | set(settled_by) | set(closed), key=str)
    rows = []
    for t in tickers:
        pos = next((p for p in held if p.get("market_ticker") == t), None)
        s = settled_by.get(t)
        not_held = "not held now" if known else "holdings unknown: no snapshot lists positions"
        rows.append([esc(t), esc(str(pos.get("side")).upper()) if pos else c.na(not_held),
                     oc.qty(pos.get("quantity")) if pos else c.na(not_held),
                     esc(s.get("market_result")) if s and s.get("market_result") else c.na(
                         "not settled in this journal" if not s else "result not recorded"),
                     oc.money(s.get("revenue")) if s else c.na("not settled"),
                     oc.money(s.get("fee_cost")) if s else c.na("not settled"),
                     oc.money(realized.get(t), "no venue P&L observed for this market", signed=True)
                     if realized is not None else c.na("P&L baseline not recorded yet: unknown, not zero")])
    table = c.table(["Market", "Side", "Held", "Result", "Revenue", "Fees", "Realized (venue)"], rows,
                    right=(2, 4, 5, 6), caption=f"{event}: markets")
    facts = c.facts([
        ("Positions held", c.num(pr.count(len(held)) if known else None,
                                 reason="holdings unknown: no snapshot lists positions")),
        ("Settled markets", c.num(pr.count(len(settled)))),
        ("Max loss (upper bound)", c.na(EXEC_NO_BOUND)),
        ("Settles by", c.na(EXEC_NO_SETTLE_TIME)),
    ])
    return c.row(esc(event), sub=f"{env} venue · not a real position · {len(tickers)} market(s)",
                 aside=c.state_text(f"XO_{status}", label=label, kind=kind),
                 body=facts + c.disclosure(f"Markets in this event ({len(tickers)})", table))


def execution_outcomes_body(loaded: d.Loaded, now: datetime) -> str:
    """Every state: actual positions not connected; export missing, unreadable, refused or mismatched; no journal or
    journal error; stale export; paused; reconciliation incomplete or no snapshot (holdings unknown); a known-empty
    account; populated FIXTURE groups."""
    missing, es = oc.export_state(loaded)
    actual = '<h3 class="eyebrow">Actual positions</h3>' + actual_body(es)
    if missing:
        return actual + missing
    doc = es.doc
    parts = [actual, oc.export_status_line(es, now)]
    journal = oc.journal_state(doc)
    if journal:
        return "".join(parts) + journal
    env = doc.get("environment")
    parts += [f"<p>{oc.env_badge(env)}</p>", snapshot_line(doc), oc.paused_line(doc) or ""]
    positions = oc.lst(doc, "account", "positions")
    groups = execution_groups(doc)
    if (oc.g(doc, "account", "snapshot") is None or positions is None) and not groups:
        parts.append(c.unavailable("Holdings unknown", "No account snapshot with positions is recorded, so the "
                                                       "outcomes these positions depend on are unknown, not empty."))
    elif not groups:
        parts.append(c.empty_state(f"No {env} positions or settlements",
                                   "The latest snapshot lists no position and the journal records no settlement."))
    else:
        if not holdings_known(doc):
            parts.append(c.status_line("warn", "Open holdings unknown",
                                       "No snapshot lists positions: what is held is unknown; only settled and "
                                       "exited markets are shown below."))
        parts.append('<ul class="rows">' + "".join(execution_group_row(*g, doc) for g in groups) + "</ul>")
        parts.append(omitted_note(oc.g(doc, "settlements", "rows_omitted"), "settlements"))
    parts.append('<p class="note">Orders, fills and cash: ' + c.link("/positions/execution", "Execution portfolio")
                 + ". Nothing here is a real position or a real-world result.</p>")
    return "".join(x for x in parts if x)


def execution_section(ctx: d.Context) -> str:
    return c.section("Execution positions by outcome", execution_outcomes_body(d.execution_status(ctx), ctx.now),
                     meta="FIXTURE-labelled · from the execution export · grouped by event · impact not computed",
                     sid="oc-x")


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    v = cm.account_view(ctx, p)
    head = c.page_head("What matters today", f"Outcomes · {cm.scope_label(p)} · ranked by account impact",
                       extra=c.account_switch(p, "/outcome-board"))
    parts = [head]
    how = ("Positions are grouped by the real-world outcome they depend on (outcome cluster) and ranked by account "
           "impact. Max loss and max gain are upper bounds, not predicted scenarios: they add up position worst/best "
           "cases and ignore that mutually exclusive brackets cannot all lose or all win.")
    unavailable = cm.account_unavailable(v, what="Outcome board")
    if unavailable:
        parts.append(c.section("Linked outcomes", unavailable, sid="oc-h"))
    elif v.board is None or v.board.status != d.OK:
        parts.append(c.section("Linked outcomes", c.error_state("Outcome board unavailable",
                                                                v.board.message if v.board else ""), sid="oc-h"))
    else:
        groups = list(v.board.value)
        open_groups = [g for g in groups if g.status != "SETTLED"]
        largest = max(open_groups, key=lambda g: g.current_exposure, default=None)
        parts.append(c.metric_strip([
            c.metric("Linked outcome groups", c.num(pr.count(len(open_groups))), "Open or partly settled", lead=True),
            c.metric("Open risk", c.money_cell(v.state.open_worst_case_risk), "Worst case, open positions"),
            c.metric("Largest exposure", c.money_cell(largest.current_exposure) if largest else
                     c.na("no open exposure"), pr.cluster_label(largest.outcome_cluster) if largest else "None open"),
        ], label="Outcome exposure summary"))
        if groups:
            top = max((g.current_exposure for g in groups), default=0)
            body = '<ul class="rows">' + "".join(group_row(g, top) for g in groups) + "</ul>"
        else:
            body = c.empty_state("No linked positions",
                                 "The account loaded and holds no positions, so no outcome carries exposure.")
        parts.append(c.section("Linked outcomes", body, meta=f"Bars: current exposure · {cm.BOUND_LABEL} for max "
                                                             "loss and gain", sid="oc-h", flush=True))
    parts.append(execution_section(ctx))
    parts.append(c.disclosure("How to read the board", f"<p>{esc(how)}</p>", boxed=True))
    return cm.Page("Outcomes", "outcomes", "".join(parts), account_scoped=True)
