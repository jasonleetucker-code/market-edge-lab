"""Terminal (/): market overview. Order and hierarchy: docs/design/UI_CONTRACT.md §11."""

from __future__ import annotations

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

BOARD_ROWS = 5
MATTERS_ROWS = 3
ACTIVITY_ROWS = 5


def summary(ctx: d.Context, p: pr.Params) -> str:
    """The single shadow summary region: primary equity plus a 2x2 of canonical figures."""
    view = cm.account_view(ctx, p)
    title = f"{cm.scope_label(p)} summary"
    unavailable = cm.account_unavailable(view, what=cm.scope_label(p) + " account")
    if unavailable:
        return c.section(title, unavailable, sid="sum-h", cls="ws-band")
    s = view.state
    rep = view.risk.value if view.risk is not None and view.risk.status == d.OK else None
    realized_today = c.metric("Realized today", c.na("not computed: the engine reports trailing 24 h realized loss "
                                                     "(Risk), not a calendar-day result"),
                              "Not computed · see Risk for trailing 24 h loss")
    cells = [
        c.metric("Tradable cash", c.money_cell(s.settled_cash), "Settled shadow cash"),
        c.metric("Committed", c.money_cell(s.committed_capital), "Open positions at cost"),
        c.metric("Open risk", c.money_cell(s.open_worst_case_risk), "Worst case, open positions"),
        realized_today,
    ]
    risk_note = ""
    if rep is not None and cm.risk_state(rep) != "OK":
        risk_note = f'<p class="note">{c.badge(cm.risk_state(rep))} New positions halted; see Risk.</p>'
    body = (
        f'<section class="section ws-band" aria-labelledby="sum-h"><div class="summary">'
        f'<div><h2 class="eyebrow" id="sum-h">{esc(cm.scope_label(p))} {cm.research_badge(p)}</h2>'
        '<p class="summary-primary-label">Shadow equity · cost basis</p>'
        f'<p class="summary-primary">{c.money_cell(s.equity)}</p>'
        f'<p class="summary-basis" title="{esc(cm.EQUITY_LABEL)}">Notional {esc(pr.money(s.starting_bankroll))} bankroll '
        "· simulated</p></div>"
        f'<dl class="metrics">{"".join(cells)}</dl></div>{risk_note}</section>')
    return body


def board(ctx: d.Context, p: pr.Params) -> str:
    rows = pr.sort_rows(cm.board_rows(ctx, p))
    counts = {k: sum(1 for r in rows if k == "all" or r.state == k) for k, _ in pr.BOARD_STATES}
    current = p.board_state()
    tab_items = []
    for key, label in pr.BOARD_STATES:
        params = {"state": key} if key != "all" else {}
        if p.account != "operational":
            params["account"] = p.account
        href = "/" + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
        tab_items.append((href, "All" if key == "all" else label, key == current, str(counts[key])))
    shown = [r for r in rows if current == "all" or r.state == current]
    all_href = p.href("/opportunities", state=current if current != "all" else "", page=1)
    if shown:
        content = c.market_board(shown[:BOARD_ROWS], p)
    elif ctx.observed.status == d.ERROR:
        content = c.error_state("Market data unavailable", ctx.observed.message)
    elif not rows:
        content = c.empty_state(
            "No markets captured yet",
            "The board fills from captured order books and recorded decisions. "
            + ("No market books are stored in the evidence database yet."
               if ctx.observed.status != d.OK else "No market is visible to this account."),
            times=_next_capture_text(ctx), action=("/experiments?tab=sources", "Data sources"))
    else:
        content = c.empty_state(f"No {dict(pr.BOARD_STATES)[current].lower()} markets",
                                f"{len(rows)} market(s) are captured; none is in this group.",
                                action=("/", "Show all"))
    action = f'<a href="{c.esc(all_href)}">View all markets</a>'
    body = c.tabs(tab_items, label="Market board filter") + content
    return c.section("Market board", body, meta=_coverage(ctx), action=action, sid="board-h", cls="ws-main flush")


def _coverage(ctx: d.Context) -> str:
    if ctx.observed.status == d.ERROR:
        return "Captured books unavailable"
    if ctx.observed.status != d.OK:
        return "No captured books"
    return cm.coverage_text(ctx.observed.value)


def _next_capture_text(ctx: d.Context) -> str | None:
    nxt = cm.next_windows(ctx.now)
    if not nxt:
        return None
    label, when = nxt[0]
    return f"Next collector window: {pr.datetime_et(when)} ({label.lower()}; the schedule, not proof it runs)."


def matters(ctx: d.Context, p: pr.Params) -> str:
    view = cm.account_view(ctx, p)
    title = "What matters today"
    link = '<a href="/outcome-board' + ("?account=research" if p.account == "research" else "") + '">Outcomes</a>'
    unavailable = cm.account_unavailable(view, what="Exposure")
    if unavailable:
        return c.section(title, unavailable, sid="matters-h", cls="ws-matters", action=link)
    if view.board is None or view.board.status != d.OK:
        return c.section(title, c.error_state("Outcome board unavailable", view.board.message if view.board else ""),
                         sid="matters-h", cls="ws-matters", action=link)
    groups = [g for g in view.board.value if g.status != "SETTLED"][:MATTERS_ROWS]
    if not groups:
        body = c.empty_state("No open exposure", "The account loaded and holds no open shadow positions.")
    else:
        top = max((g.current_exposure for g in groups), default=0)
        items = [c.row(esc(pr.cluster_label(g.outcome_cluster)), sub=f"{len(g.positions)} linked position(s) · settles "
                       f"{pr.datetime_et(g.settles_by_utc) or 'time unknown'}",
                       aside=c.money_cell(g.current_exposure),
                       body=c.bar(g.current_exposure, top, label=f"Exposure {pr.money(g.current_exposure)}"))
                 for g in groups]
        body = f'<ul class="rows">{"".join(items)}</ul>'
    return c.section(title, body, meta=cm.scope_label(p), sid="matters-h", cls="ws-matters flush", action=link)


def activity(ctx: d.Context) -> str:
    events: list[tuple[str, str, str, str | None, str | None]] = []
    if ctx.notifications.status == d.OK:
        from ... import notifications as nt
        for n in ctx.notifications.value:
            origin = nt.origin_of(n)
            if origin is not None and origin is not nt.Origin.PRODUCTION:
                continue  # tests, checks, diagnostics, replays and demos stay on Alerts, never mixed in here
            kind = {"CRITICAL": "err", "WARNING": "warn", "INFO": "info"}.get(str(n.get("severity")), "nd")
            events.append((kind, str(n.get("summary") or n.get("type") or "Notification"), pr.state_word(n.get("type")).label,
                           n.get("created_at_utc"), "/alerts"))
    if ctx.receipt.status == d.OK:
        r = ctx.receipt.value
        word = pr.state_word(r.get("state"))
        events.append((word.kind, f"Daily shadow run: {word.label}", f"Receipt state {r.get('state') or 'not recorded'}",
                       r.get("generated_at_utc"), None))
    if ctx.collector_status.status == d.OK:
        s = ctx.collector_status.value
        word = pr.state_word(s.get("last_closed_status"))
        day = pr.date_label(s.get("last_closed_target_date")) or "unknown day"
        events.append((word.kind, f"Collector report: target {day} {word.label.lower()}", "latest.json",
                       s.get("generated_at_utc"), None))
    for f in ctx.failure_records:
        a = cm.failure_alert(f)
        if a.group == "attention":  # production incidents only; verification records stay on Alerts
            events.append((a.kind, a.title, f.source, a.when_utc, "/alerts"))
    events.sort(key=lambda e: str(e[3] or ""), reverse=True)
    if not events:
        body = c.empty_state("No activity recorded yet", "Collector reports, pipeline runs and notifications appear "
                             "here with their recorded times.")
    else:
        body = '<ul class="rows">' + "".join(c.activity_row(k, t, dt, w, href=h)
                                             for k, t, dt, w, h in events[:ACTIVITY_ROWS]) + "</ul>"
    return c.section("Activity", body, sid="act-h", cls="ws-activity flush", action='<a href="/alerts">Alerts</a>')


def status_panel(ctx: d.Context) -> str:
    st = cm.collection_status(ctx)
    steps = [("info", label, "Collector schedule (forward.windows); not proof the timer is running",
              pr.time_et(when) or "") for label, when in cm.next_windows(ctx.now)]
    body = (c.status_line(st.kind, st.title, st.detail, detail_html=' <a href="#system">Details</a>')
            .replace('class="statusline', 'class="statusline flat', 1)
            + (c.timeline(steps) if steps else ""))
    return body


def system(ctx: d.Context) -> str:
    """Collapsed System & evidence: every source field, blocker and account detail, with codes."""
    parts = []
    blockers = cm.blockers_cached(ctx)
    parts.append("<h3 class=\"eyebrow\">Blockers and warnings</h3>" + c.ul(blockers, empty="none"))
    s = ctx.collector_status
    title = "Collector status file (latest.json)"
    missing = cm.loaded_state(title, s)
    if missing:
        parts.append(missing)
    else:
        v = s.value
        fresh, _ = d.freshness(v.get("generated_at_utc"), ctx.now)
        parts.append(f'<h3 class="eyebrow">{esc(title)}</h3>' + c.kv([
            ("freshness", c.badge(fresh, label=fresh) + " " + esc(f"generated {v.get('generated_at_utc')} "
                                                               f"({pr.age_text(v.get('generated_at_utc'), ctx.now)}; "
                                                               "stale after 26 h)")),
            ("last closed target date", esc(v.get("last_closed_target_date"))),
            ("last closed status", c.badge(v.get("last_closed_status")) + " " + c.code(v.get("last_closed_status"))),
            ("reasons", c.ul(cm.as_list(v.get("last_closed_reasons")))),
            ("valid days", esc(v.get("valid_days"))), ("first valid day", esc(v.get("first_valid_day"))),
            ("days with captures", esc(v.get("days_with_captures"))),
            ("invalid days", c.ul(cm.as_list(v.get("invalid_days")))),
        ]))
    db = ctx.collector_db
    title = "Collector status from the evidence DB (computed now)"
    missing = cm.loaded_state(title, db)
    if missing:
        parts.append(missing)
    else:
        v = db.value
        started = (v.get("days_with_captures") or 0) > 0
        parts.append(f'<h3 class="eyebrow">{esc(title)}</h3>' + c.kv([
            ("captures", esc(v.get("days_with_captures")) if started else c.badge("NOT_STARTED",
                                                                                   label="NOT STARTED: no captures")),
            ("last closed target date", esc(v.get("last_closed_target_date"))),
            ("last closed status", c.badge(v.get("last_closed_status")) + " " + c.code(v.get("last_closed_status"))),
            ("reasons", c.ul(cm.as_list(v.get("last_closed_reasons")))),
            ("valid days", esc(v.get("valid_days"))), ("first valid day", esc(v.get("first_valid_day"))),
            ("invalid days", c.ul(cm.as_list(v.get("invalid_days")))),
        ]) + '<p class="note">Re-derived by forward.summary from stored evidence at page render.</p>')
    for f in ctx.failure_records:
        heading = ("Last production unit failure" if f.source == d.FAILURE_FILE
                   else "Last deployment verification record")
        if f.error is not None:
            parts.append(c.error_state(f"{heading} ({f.source})", f.error))
            continue
        shown = cm.failure_alert(f).title.split(":", 1)[0]
        parts.append(f'<h3 class="eyebrow">{esc(heading)} ({esc(f.source)})</h3>' + c.kv([
            ("shown as", esc(shown)), ("origin recorded", c.code(f.record.get("origin") or "none (production)")),
            ("unit", esc(f.record.get("unit"))), ("failed at", esc(f.record.get("failed_at_utc"))),
            ("invocation", c.code(f.record.get("invocation_id"))),
            ("age", esc(pr.age_text(f.record.get("failed_at_utc"), ctx.now)))]))
    parts.append(receipt_detail(ctx))
    for view in ctx.accounts:
        parts.append(account_detail(view))
    return c.disclosure("System & evidence", "".join(parts), boxed=True).replace(
        '<details class="disclosure boxed"', '<details id="system" class="disclosure boxed ws-system"', 1)


def receipt_detail(ctx: d.Context, *, days: bool = False) -> str:
    title = "Daily shadow pipeline receipt (shadow_daily.json)"
    missing = cm.loaded_state(title, ctx.receipt)
    if missing:
        return missing
    r = ctx.receipt.value
    schema = r.get("schema")
    settlement = cm.get(r, "settlement")
    refresh = cm.get(settlement, "refresh")
    fee = cm.get(r, "fee")
    latest = cm.get(r, "latest_day")
    conflicts = cm.as_list(cm.get(settlement, "conflicts"))
    fresh, _ = d.freshness(r.get("generated_at_utc"), ctx.now)
    pairs = [
        ("state", c.badge(r.get("state")) + " " + c.code(r.get("state"))
         + (" " + c.badge("REPEAT", label="REPEAT OF PREVIOUS ALERT") if r.get("repeat_of_previous_alert") else "")),
        ("exit code", esc(r.get("exit_code"))),
        ("latest day", (f"{esc(cm.get(latest, 'target_date'))} {c.badge_code(cm.get(latest, 'capture_status'))} "
                        f"{c.badge_code(cm.get(latest, 'result'))}") if isinstance(latest, dict) else esc(None)),
        ("valid / closed capture days", f"{esc(r.get('valid_days'))} / {esc(r.get('closed_capture_days'))}"),
        ("missing capture days", cm.list_field(r, "missing_capture_days")),
        ("freshness", c.badge(fresh, label=fresh) + " " + esc(f"generated {r.get('generated_at_utc')} (stale after 26 h)")),
        ("code version", esc(r.get("code_version"))),
        ("schema", esc(schema) + ("" if schema in (None, d.RECEIPT_SCHEMA) else " " +
                                  c.badge("UNEXPECTED_SCHEMA", label="UNEXPECTED SCHEMA", kind="warn"))),
        ("days processed", esc(len(cm.as_list(r.get("days")))) if "days" in r else esc(None)),
        ("settled this run", esc(cm.get(settlement, "settled"))),
        ("pending settlements", esc(len(cm.as_list(cm.get(settlement, "pending")))) if isinstance(settlement, dict)
         and "pending" in settlement else esc(None)),
        ("settlement conflicts", cm.list_field(settlement, "conflicts") if cm.malformed(settlement, "conflicts") else
         (c.badge("SETTLEMENT_CONFLICT", label=f"{len(conflicts)} SETTLEMENT_CONFLICT") if conflicts else esc("none"))
         if isinstance(settlement, dict) and "conflicts" in settlement else esc(None)),
        ("settlement evidence cutoff", esc(cm.get(settlement, "evidence_cutoff_utc"))),
        ("settlement refresh", c.code(cm.get(refresh, "status")) if refresh is not None else esc(None)),
        ("fee schedule", esc(cm.get(fee, "schedule_id")) + " " + (c.code(cm.get(fee, "status")) if fee else "")),
        ("fee claim basis (at this run)", c.code(cm.get(fee, "claim_basis")) if fee else esc(None)),
        ("fee claim allowed (lower bound only)", esc(cm.get(fee, "claimable"))),
        ("problems", c.ul(cm.as_list(r.get("problems")))),
    ]
    body = f'<h3 class="eyebrow">{esc(title)}</h3>' + c.kv(pairs)
    if days:
        rows = []
        for day in cm.as_list(r.get("days")):
            accounts = cm.get(day, "accounts")
            acct = "; ".join(
                f"{a}: {cm.get(v, 'decisions')} decisions, {cm.get(v, 'qualified')} qualified, {cm.get(v, 'fills')} fills, "
                f"{cm.no_fills(cm.get(v, 'no_fills'))} no-fills, {cm.get(v, 'risk_vetoes')} risk vetoes"
                for a, v in accounts.items()) if isinstance(accounts, dict) else None
            rows.append([esc(cm.get(day, "target_date")), c.code(cm.get(day, "capture_status")),
                         esc(cm.get(day, "decision_time_utc")), esc(cm.get(day, "result")), esc(acct),
                         esc("; ".join(map(str, cm.as_list(cm.get(day, "problems")))) or None)])
        body += "<h4 class=\"eyebrow\">Days</h4>" + c.table(
            ["target date", "capture", "decision time", "result", "accounts", "problems"], rows, wrap=(4, 5))
        body += "<h4 class=\"eyebrow\">Settlement evidence conflicts</h4>" + conflicts_table(conflicts)
        if isinstance(refresh, dict):
            body += "<h4 class=\"eyebrow\">Settlement evidence refresh</h4>" + c.kv([
                ("status", c.code(refresh.get("status"))), ("events requested", esc(refresh.get("events_requested"))),
                ("markets stored", esc(refresh.get("markets_stored"))),
                ("errors", c.ul(cm.as_list(refresh.get("errors"))))])
    return body


def conflicts_table(conflicts: list) -> str:
    return c.table(["account", "position", "recorded outcome", "latest evidence outcome", "evidence variants", "reason"],
                   [[esc(cm.get(x, "account_id")), esc(cm.get(x, "position_id")), esc(cm.get(x, "recorded_outcome")),
                     esc(cm.get(x, "latest_evidence_outcome")), esc(cm.get(x, "variants")), esc(cm.get(x, "reason"))]
                    for x in conflicts], wrap=(4, 5), empty="none recorded")


def account_detail(view: d.AccountView) -> str:
    head = f'<h3 class="eyebrow">{esc(cm.account_heading(view))}</h3>'
    note = view.role.note if view.role else "an account the dashboard does not recognise; shown for completeness"
    if view.status != d.OK:
        return head + (c.error_state("Account unreadable", view.message) if view.status == d.ERROR else
                       c.unavailable("NO DATA / NOT STARTED", view.message))
    s = view.state
    pairs = [
        (cm.BANKROLL_LABEL, c.money_cell(s.starting_bankroll) + " " + c.badge("NOTIONAL", label="NOTIONAL", kind="nd")),
        (cm.EQUITY_LABEL, c.money_cell(s.equity)), ("settled cash", c.money_cell(s.settled_cash)),
        ("committed capital (open, at cost)", c.money_cell(s.committed_capital)),
        ("open worst-case risk", c.money_cell(s.open_worst_case_risk)),
        ("realized P&L", c.money_cell(s.realized_pnl, signed=True)),
        ("fees paid (provisional schedule)", c.money_cell(s.fees_paid)),
        ("decisions / qualified", f"{esc(s.decisions)} / {esc(s.qualified_decisions)}"),
        ("fills / no-fills / settlements", f"{esc(s.fills)} / {esc(s.no_fills)} / {esc(s.settlements)}"),
        ("open positions", esc(len(s.open_positions()))),
    ]
    if view.risk is not None and view.risk.status == d.OK:
        pairs.append(("new risk allowed", cm.risk_line(view.risk.value)))
        pairs.append(("remaining risk capacity", c.money_cell(view.risk.value.remaining_risk_capacity)))
    else:
        pairs.append(("risk", esc(view.risk.message if view.risk else None)))
    pairs.append(("withdrawal", c.badge("NOT_RECOMMENDED", label="NOT RECOMMENDED")))
    return head + f'<p class="note">{esc(note)}</p>' + c.kv(pairs)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    now_line = f"{pr.to_et(ctx.now):%A}, {pr.datetime_et(ctx.now)}"  # the New York weekday, not UTC's
    switch = c.account_switch(p, "/", {"state": p.state} if p.state else None)
    head = c.page_head("Market overview", now_line)
    # Mobile order (contract §11): heading, status line, account scope, summary, board, ...
    body = (head + '<div class="ws">'
            + f'<div class="ws-status">{status_panel(ctx)}</div>'
            + f'<div class="ws-switch">{switch}</div>'
            + summary(ctx, p) + board(ctx, p) + matters(ctx, p) + activity(ctx) + system(ctx) + "</div>")
    return cm.Page("Terminal", "terminal", body, account_scoped=True)
