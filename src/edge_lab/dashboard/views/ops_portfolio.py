"""Execution portfolio (/positions/execution): Market v1 journey J5, read-only.

Actual versus FIXTURE holdings, cash with its basis, reserves, pending and unknown orders, fills, partial exits,
settlement and P&L, from the execution status export (never by importing the execution package, ADR 0043). No real
account is connected, so the actual-holdings section is always the blocked "Access not connected" state, and every
execution figure is labelled with its environment (today FIXTURE: a fake venue). Unknown is the unavailable marker,
never 0: a missing snapshot is "holdings unknown", a snapshot with no positions is a known empty list. Money is
signed but never coloured. Lives under Portfolio (nav "portfolio"); no global navigation item is added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from . import ops_common as oc

PATH = "/positions/execution"
CASH_BASIS = {"AVAILABLE_AFTER_VENUE_HOLDS": "available after venue holds",
              "UNKNOWN": "basis unknown: blocks new risk"}
ATTEMPT_WORDS = {"PENDING_EGRESS": ("Prepared · not known sent", "warn"), "SENT": ("Sent · no answer yet", "warn"),
                 "ACKNOWLEDGED": ("Accepted by venue", "info"), "REJECTED": ("Rejected by venue", "nd"),
                 "OUTCOME_UNKNOWN": ("Outcome unknown · reserved", "warn"), "ABSENT": ("Absent at venue", "nd")}
RESERVATION_WORDS = {"OUTSTANDING": ("Resting · reserved", "info"), "CANCEL_REQUESTED": ("Cancel requested", "warn"),
                     "UNKNOWN": ("Unknown · reserved", "warn"), "BOUND": ("Ended · awaiting snapshot", "info"),
                     "RELEASED": ("Released", "nd")}


def actual_section(es: d.ExecutionStatus | None) -> str:
    return c.section("Actual holdings", actual_body(es), meta="real accounts", sid="xp-actual")


def actual_body(es: d.ExecutionStatus | None) -> str:
    """The "Access not connected" state, with the code's authorized environments from the export when readable.
    Shared by the execution portfolio and the outcome board (J8)."""
    authorized = oc.lst(es.doc, "environments", "authorized") if es is not None else None
    if authorized is None:
        basis = ("The code's authorized environments are not readable here (no usable export); EXECUTION_PLAN records "
                 "FIXTURE only.")
    else:
        basis = f"Authorized environments in code (from the export): {', '.join(authorized) or 'none'}."
    return c.blocked_state("Access not connected",
                           f"No real account is connected. {basis} DEMO and PRODUCTION reads need activation packet "
                           "Decisions 1 and 2. No real holding, cash or order appears anywhere on this page.",
                           action=("/setup", "Setup & readiness"))


def account_strip(doc: dict) -> str:
    snap = oc.g(doc, "account", "snapshot")
    res = oc.g(doc, "account", "reservations") or {}
    env = doc.get("environment")
    if snap is None:
        cash_cell = oc.money(None, "no account snapshot recorded yet")
        usable_cell = oc.money(None, "no account snapshot recorded yet")
        cash_basis = "no snapshot yet"
    else:
        cash_cell = oc.money(snap.get("cash"), "the venue's cash was not readable")
        usable_cell = oc.money(snap.get("usable_cash"), "unusable: the cash basis is unknown")
        cash_basis = CASH_BASIS.get(snap.get("cash_basis"), f"basis {snap.get('cash_basis')}")
    pnl = oc.g(doc, "pnl") or {}
    held = res.get("held_count")
    return c.metric_strip([
        c.metric("Cash", cash_cell, f"{env} venue · {cash_basis}", lead=True),
        c.metric("Usable cash", usable_cell, "only with a known basis"),
        c.metric("Reserved", oc.money(res.get("held_cash_worst_case_total")),
                 f"worst case of {held if held is not None else '—'} held reservations"),
        c.metric("Realized P&L", oc.money(pnl.get("realized_total"), "no complete account read yet", signed=True),
                 "venue-reported · not ours to compute"),
        c.metric("Unrealized", oc.money(pnl.get("unrealized"), pnl.get("unrealized_note") or "not computed"),
                 "no mark source"),
    ], label=f"{env} execution account")


def snapshot_line(doc: dict) -> str:
    snap = oc.g(doc, "account", "snapshot")
    control = oc.g(doc, "control") or {}
    recon = control.get("reconciliation")
    if snap is None:
        return c.status_line("warn", "No account snapshot yet — holdings unknown",
                             "The journal holds no account read for this scope. Positions and cash are unknown, "
                             "not empty.")
    observed = pr.datetime_et(snap.get("observed_at_utc")) or "an unknown time"
    detail = f"Snapshot revision {snap.get('revision')}, observed {observed}."
    problems = oc.lst(snap, "problems") or []
    if recon != "COMPLETE" or snap.get("consistent") is False or problems:
        why = oc.g(control, "last_reconciliation", "detail")
        return c.status_line("warn", "Reconciliation incomplete — holdings may be wrong",
                             f"{detail} Last reconciliation: {recon}." + (f" {why}" if why else "")
                             + (f" Snapshot problems: {'; '.join(map(str, problems))}." if problems else ""))
    if snap.get("freshness_at_export") != "FRESH":
        state = snap.get("freshness_at_export")
        return c.status_line("warn", "Snapshot not fresh at export" if state == "STALE"
                             else "Snapshot age unknown at export", detail + (
            f" Older than its {pr.duration_text(snap.get('max_age_s'))} bound." if state == "STALE"
            else " The exporter had no age bound (no configuration)."))
    return c.status_line("info", "Reconciled at export", detail)


def positions_section(doc: dict) -> str:
    env = doc.get("environment")
    positions = oc.lst(doc, "account", "positions")
    if oc.g(doc, "account", "snapshot") is None or positions is None:
        body = c.unavailable("Holdings unknown", "No account snapshot with positions is recorded, so holdings are "
                                                 "unknown, not empty.")
    elif not positions:
        body = c.empty_state(f"No {env} positions", "The latest snapshot was read and lists no position.")
    else:
        rows = [c.row(esc(p.get("market_ticker")), sub=f"{str(p.get('side')).upper()} · {env} venue",
                      aside=oc.qty(p.get("quantity")), body="") for p in positions]
        body = '<ul class="rows">' + "".join(rows) + "</ul>"
    externals = oc.lst(doc, "account", "external_orders")
    if externals:
        body += c.disclosure(f"Open orders not placed by the executor ({len(externals)})", c.table(
            ["Origin", "Market", "Side", "Action", "Remaining", "Unreflected cash"],
            [[esc(x.get("origin")), esc(x.get("market_ticker")), esc(x.get("side")), esc(x.get("action")),
              oc.qty(x.get("remaining_quantity")), oc.money(x.get("unreflected_cash"))]
             for x in externals], right=(4, 5), caption="External open orders"))
    return c.section(f"{env} positions", body, meta="from the latest account snapshot", sid="xp-pos", flush=True)


def _attempt_row(a: dict, env: Any) -> str:
    filled, quantity = a.get("filled_quantity"), a.get("quantity")
    fill_text = f"{pr.quantity(filled) or '—'} of {pr.quantity(quantity) or '—'} filled"
    if a.get("partial"):
        fill_text += " · partial"
    sub = (f"{str(a.get('action') or '').upper()} {str(a.get('side') or '').upper()} · {a.get('kind')} · "
           f"{fill_text} · {env}")
    body = c.facts([
        ("Limit", oc.price(a.get("limit_price"))),
        ("Reservation", oc.word(RESERVATION_WORDS, a.get("reservation_state"), "XP_RES")),
        ("Created", oc.when(a.get("created_at_utc"))),
        ("Reason", c.txt(a.get("state_reason") or a.get("quarantine_reason"), reason="none recorded")),
    ], text_cols=(1, 2, 3))
    return c.row(esc(a.get("market_ticker")), sub=sub, aside=oc.word(ATTEMPT_WORDS, a.get("state"), "XP_ATTEMPT"),
                 body=body)


def orders_section(doc: dict) -> str:
    env = doc.get("environment")
    attempts = oc.g(doc, "attempts") or {}
    rows = oc.lst(attempts, "rows")
    if rows is None:
        return c.section("Orders", c.unavailable("Orders unknown", "The export carries no attempt list."),
                         sid="xp-orders")
    # The unknown and in-flight lists are separate from the newest-rows list, each cut to the exporter's bound with
    # its omitted count shown; resting orders are every held reservation of the latest account view (not cut).
    unknown = (oc.lst(attempts, "unknown") or []) + (oc.lst(attempts, "in_flight") or [])
    cut = sum(x for x in (attempts.get("unknown_omitted"), attempts.get("in_flight_omitted")) if isinstance(x, int))
    seen = {a.get("attempt_id") for a in unknown}
    by_id = {a.get("attempt_id"): a for a in rows}
    pending = [by_id.get(r.get("reservation_id")) or {**r, "state": None, "reservation_state": r.get("state")}
               for r in oc.lst(doc, "account", "reservations", "held") or []
               if r.get("state") in ("OUTSTANDING", "CANCEL_REQUESTED") and r.get("reservation_id") not in seen]
    parts = []
    counts = attempts.get("by_state") or {}
    parts.append(c.facts([(ATTEMPT_WORDS.get(k, (k,))[0], c.num(pr.count(v), reason=oc.UNKNOWN_REASON))
                          for k, v in sorted(counts.items())]) if counts else "")
    if unknown:
        parts.append('<h3 class="eyebrow">Unknown or in flight · reserved until reconciled, never re-sent</h3>'
                     '<ul class="rows">' + "".join(_attempt_row(a, env) for a in unknown) + "</ul>"
                     + omitted_note(cut, "unknown or in-flight attempts"))
    if pending:
        parts.append('<h3 class="eyebrow">Resting</h3><ul class="rows">'
                     + "".join(_attempt_row(a, env) for a in pending) + "</ul>")
    if not rows and not unknown and not pending and attempts.get("total") == 0:
        parts.append(c.empty_state(f"No {env} orders", "The journal was read and holds no order attempt."))
    elif not unknown and not pending:
        parts.append(c.empty_state("Nothing pending or unknown", "Every recorded attempt has a final venue answer."))
    if rows:
        omitted = attempts.get("rows_omitted") or 0
        parts.append(c.disclosure(f"All recorded attempts ({attempts.get('total')})" + (
            f", newest {len(rows)} shown" if omitted else ""), c.table(
            ["Market", "Side", "Kind", "Quantity", "Filled", "Limit", "State", "Reservation", "Created"],
            [[esc(a.get("market_ticker")), esc(a.get("side")), esc(a.get("kind")), oc.qty(a.get("quantity")),
              oc.qty(a.get("filled_quantity")), oc.price(a.get("limit_price")),
              oc.word(ATTEMPT_WORDS, a.get("state"), "XP_ATTEMPT"),
              oc.word(RESERVATION_WORDS, a.get("reservation_state"), "XP_RES"), oc.when(a.get("created_at_utc"))]
             for a in rows], right=(3, 4, 5), caption="Recorded order attempts") + omitted_note(omitted, "attempts")))
    return c.section("Orders", "".join(parts), meta=f"{env} · pending, unknown and recorded", sid="xp-orders")


def fills_section(doc: dict) -> str:
    env = doc.get("environment")
    rows = oc.lst(doc, "attribution", "rows")
    parts = []
    if rows is None:
        parts.append(c.unavailable("Fills unknown", "The export carries no attribution list."))
    elif not rows:
        parts.append(c.empty_state("No attributed fills yet", "A fill is attributed once a later snapshot confirms "
                                                              "the order's result."))
    else:
        parts.append(c.table(["Market", "Side", "Kind", "Filled", "Notional", "Fees", "Fees complete", "Recorded"],
                             [[esc(r.get("market_ticker")), esc(r.get("side")), esc(r.get("kind")),
                               oc.qty(r.get("filled_quantity")), oc.money(r.get("notional")),
                               oc.money(r.get("fees_known")),
                               esc("yes" if r.get("fees_complete") else "no: some fees unknown"),
                               oc.when(r.get("recorded_at_utc"))] for r in rows],
                             right=(3, 4, 5), caption="Attributed fills")
                     + omitted_note(oc.g(doc, "attribution", "rows_omitted"), "attributed fills"))
    parts.append(c.facts([
        ("Partly filled orders", c.num(pr.count(oc.g(doc, "attempts", "partial_orders")), reason=oc.UNKNOWN_REASON)),
        ("Partial exits", c.num(pr.count(oc.g(doc, "attempts", "partial_reductions")), reason=oc.UNKNOWN_REASON)),
    ]))
    return c.section("Fills and partial exits", "".join(parts), meta=f"{env} · attributed after confirmation",
                     sid="xp-fills")


def settlement_section(doc: dict) -> str:
    env = doc.get("environment")
    rows = oc.lst(doc, "settlements", "rows")
    if rows is None:
        body = c.unavailable("Settlements unknown", "The export carries no settlement list.")
    elif not rows:
        body = c.empty_state("No settlement recorded", f"No {env} market has settled in this journal.")
    else:
        body = c.table(["Market", "Result", "YES held", "NO held", "Cost", "Revenue", "Fees", "Settled", "Missing"],
                       [[esc(r.get("ticker")), esc(r.get("market_result")), oc.qty(r.get("yes_count")),
                         oc.qty(r.get("no_count")), oc.money(r.get("yes_total_cost")), oc.money(r.get("revenue")),
                         oc.money(r.get("fee_cost")), oc.when(r.get("settled_time")),
                         esc(", ".join(r.get("missing") or []) or "none")] for r in rows],
                       right=(2, 3, 4, 5, 6), caption="Recorded settlements")
        body += omitted_note(oc.g(doc, "settlements", "rows_omitted"), "settlements")
    return c.section("Settlement", body, meta=f"{env} · venue settlement records", sid="xp-settle")


def pnl_section(doc: dict) -> str:
    env = doc.get("environment")
    pnl = oc.g(doc, "pnl") or {}
    rows = oc.lst(pnl, "by_market")
    if not pnl.get("baseline_recorded"):
        body = c.unavailable("P&L not known yet", "No complete account read has recorded the venue's realized P&L "
                                                  "baseline. It is unknown, not zero.")
    else:
        body = c.facts([("Realized total", oc.money(pnl.get("realized_total"), signed=True)),
                        ("Unrealized", oc.money(pnl.get("unrealized"), pnl.get("unrealized_note") or "not computed")),
                        ("Basis", c.txt(pnl.get("basis")))], text_cols=(2,))
        body += c.table(["Market", "Realized", "Observed"],
                        [[esc(r.get("market_ticker")), oc.money(r.get("realized_pnl"), signed=True),
                          oc.when(r.get("observed_at_utc"))] for r in rows or []],
                        right=(1,), caption="Realized P&L by market", empty="no market has realized P&L")
    return c.section("P&L", body, meta=f"{env} · venue-reported, signed, never coloured", sid="xp-pnl")


def omitted_note(count: Any, what: str) -> str:
    """The exporter keeps the newest items of a list; how many older ones it left out is said, never hidden."""
    if isinstance(count, int) and count > 0:
        return f'<p class="note">{count} older {esc(what)} are not in the export (it keeps the newest).</p>'
    return ""


def chain_text(j: dict) -> str:
    ok, events = j.get("chain_ok"), j.get("chain_events")
    if ok is None:
        return c.na("chain verification not recorded")
    word = "verified" if ok is True else "NOT verified"
    count = c.num(pr.count(events), reason="event count not recorded")
    problems = c.ul(j.get("chain_problems")) if j.get("chain_problems") else ""
    return (f"{esc(word)} · {count} events" + problems
            + omitted_note(j.get("chain_problems_omitted"), "chain problems"))


def details(doc: dict) -> str:
    j = oc.g(doc, "journal") or {}
    svc = oc.g(doc, "service") or {}
    return c.disclosure("How these figures are recorded", c.kv([
        ("Source", esc("execution_status.json, written by the execution package from its journal; this page "
                       "imports nothing from it")),
        ("Schema", c.code(doc.get("schema"))),
        ("Scope", c.code(doc.get("scope_key"))),
        ("Generated", esc(f"{pr.datetime_et(doc.get('generated_at_utc'))} ({doc.get('generated_at_utc')})")),
        ("Journal chain", chain_text(j)),
        ("Service", esc(svc.get("state"))),
        ("Configuration supplied", esc(doc.get("config_supplied"))),
        ("Left out by design", c.ul(doc.get("omitted_by_design") or [])),
    ]))


def portfolio_body(loaded: d.Loaded, now: datetime) -> str:
    missing, es = oc.export_state(loaded)
    parts = []
    if es is not None:
        parts.append(oc.export_status_line(es, now))
    parts.append(actual_section(es))
    if missing:
        parts.append(c.section("Execution account", missing, sid="xp-acct"))
        return "".join(parts)
    doc = es.doc
    journal = oc.journal_state(doc)
    if journal:
        parts.append(c.section("Execution account", journal, sid="xp-acct"))
        return "".join(parts)
    env = doc.get("environment")
    paused = oc.paused_line(doc)
    acct = (f'<p>{oc.env_badge(env)}</p>' + snapshot_line(doc) + (paused or "") + account_strip(doc))
    parts.append(c.section(f"{env} account", acct, meta="the fake venue's account, as recorded", sid="xp-acct"))
    parts += [positions_section(doc), orders_section(doc), fills_section(doc), settlement_section(doc),
              pnl_section(doc), details(doc)]
    return "".join(parts)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head("Execution portfolio", "From the execution journal · FIXTURE-labelled until real account reads "
                                              "exist · read-only", crumb=oc.crumb("/positions", "Portfolio"))
    body = portfolio_body(d.execution_status(ctx), ctx.now)
    return cm.Page("Execution portfolio", "portfolio",
                   head + oc.journey_tabs(PATH) + '<div class="stack">' + body + "</div>")
