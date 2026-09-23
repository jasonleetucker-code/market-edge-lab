"""Markets (/opportunities) and Market detail (/market). docs/design/UI_CONTRACT.md §12-13."""

from __future__ import annotations

from urllib.parse import urlencode

from ... import exp001_stageb as stageb, venues
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm


def _select(name: str, label: str, options, current: str) -> str:
    opts = "".join(f'<option value="{esc(k)}"{" selected" if k == current else ""}>{esc(v)}</option>'
                   for k, v in options)
    return (f'<div class="field"><label for="f-{esc(name)}">{esc(label)}</label><div class="select-wrap">'
            f'<select class="select" id="f-{esc(name)}" name="{esc(name)}">{opts}</select>'
            f'{c.icon("chevron-down")}</div></div>')


def venue_options() -> list[tuple[str, str]]:
    return [("all", "All venues")] + [(v, pr.venue_label(v)) for v in sorted(venues.VENUES)]


def filter_form(p: pr.Params, between: str) -> str:
    """GET filters that work without JavaScript, in the contract order: search, domain strip (and
    sport filter) passed in as `between`, then venue, state, cash release and sort."""
    hidden = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
                     for k, v in (("domain", p.domain), ("sport", p.sport), ("account", p.account))
                     if v not in ("all", "operational"))
    return (
        '<form class="filters" method="get" action="/opportunities" role="search" aria-label="Filter captured markets">'
        f'<div class="field"><label class="sr" for="f-q">Search captured markets</label><div class="search-wrap">'
        f'{c.icon("search")}<input class="input" id="f-q" type="search" name="q" maxlength="{pr.MAX_QUERY}" '
        f'value="{esc(p.q)}" placeholder="Search captured markets" autocomplete="off"></div></div>'
        + between +
        '<div class="filter-row">'
        + _select("venue", "Venue", venue_options(), p.venue)
        + _select("state", "State", pr.BOARD_STATES, p.board_state())
        + _select("horizon", "Cash release", pr.HORIZONS, p.horizon)
        + _select("sort", "Sort", pr.SORTS, p.sort)
        + "</div>" + hidden
        + '<div class="btn-row"><button class="btn btn-primary" type="submit">Apply filters</button>'
        + f'{c.link("/opportunities" + ("?account=research" if p.account == "research" else ""), "Clear filters", "btn")}'
        + "</div></form>")


def domain_tabs(p: pr.Params, rows: list[pr.MarketRow]) -> str:
    items = []
    for key, label in pr.DOMAINS:
        n = sum(1 for r in rows if key == "all" or r.domain == key)
        items.append((p.href("/opportunities", domain=key, sport="all", page=1), label, key == p.domain, str(n)))
    return c.tabs(items, label="Market domain")


def sport_filter(p: pr.Params, rows: list[pr.MarketRow], sports: list[str]) -> str:
    if p.domain != "sports":
        return ""
    if not sports:
        return c.empty_state("No sport or league data connected",
                             "No sports market has been captured, so no league filter exists. This is "
                             "unsupported / no data, not a verified zero-market result.", kind="nd")
    items = [(p.href("/opportunities", sport="all", page=1), "All sports", p.sport == "all", None)]
    items += [(p.href("/opportunities", sport=s, page=1), s.upper(), p.sport == s, None) for s in sports]
    return c.tabs(items, label="Sport or league")


def coverage_line(ctx: d.Context, total: int, shown: int) -> str:
    if ctx.observed.status == d.OK:
        cov = cm.coverage_text(ctx.observed.value)
    elif ctx.observed.status == d.ERROR:
        cov = "Captured books unavailable (read error)"
    else:
        cov = "No books captured yet"
    return f'<p class="coverage" role="status">{esc(shown)} of {esc(total)} markets · {esc(cov)}</p>'


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    all_rows = cm.board_rows(ctx, p)
    sports = sorted({r.league for r in all_rows if r.domain == "sports" and r.league})
    in_domain = [r for r in all_rows if p.domain == "all" or r.domain == p.domain]
    filtered = pr.sort_rows(pr.filter_rows(all_rows, p), p.sort)
    page_rows, pages = pr.page_slice(filtered, p.page)
    sub = "Observed prices and model assessments. " + (
        f"Coverage: {cm.coverage_text(ctx.observed.value)}." if ctx.observed.status == d.OK
        else "No captured coverage yet.")
    switch = c.account_switch(p, "/opportunities", {k: v for k, v in p.filters().items() if k != "account"})
    parts = [c.page_head("Markets", sub, extra=switch)]
    if p.account == "research":
        parts.append(f'<p class="note">{cm.research_badge(p)} Assessments shown are the frozen research account\'s '
                     "recorded decisions. Operational figures are unaffected.</p>")
    parts.append(filter_form(p, domain_tabs(p, all_rows) + sport_filter(p, in_domain, sports)))
    parts.append(coverage_line(ctx, len(all_rows), len(filtered)))
    starter = (f'<p class="note">Starter rule STARTER_MAX_7D_V1: new operational capital only where tradable cash is '
               "expected back on the same venue within 168 hours. Browsing an ineligible market never allocates "
               "to it.</p>")
    if page_rows:
        pager = ""
        if pages > 1:
            prev = p.href("/opportunities", page=p.page - 1) if p.page > 1 else None
            nxt = p.href("/opportunities", page=p.page + 1) if p.page < pages else None
            pager = ('<nav class="btn-row" aria-label="Pages">'
                     + (c.link(prev, "Previous", "btn") if prev else "")
                     + f'<span class="meta">Page {esc(p.page)} of {esc(pages)}</span>'
                     + (c.link(nxt, "Next", "btn") if nxt else "") + "</nav>")
        body = c.market_board(page_rows, p, label="Captured markets") + (f'<div class="pad">{pager}</div>'
                                                                         if pager else "")
    elif ctx.observed.status == d.ERROR and not all_rows:
        body = c.error_state("Market data unavailable", ctx.observed.message)
    elif not all_rows:
        body = c.empty_state("Waiting for first capture",
                             "No market books or decisions are stored yet. Markets appear here after the collector "
                             "captures a market list and order books.",
                             action=("/experiments?tab=sources", "Data sources"))
    else:
        body = c.empty_state("No matches in captured data",
                             "The filters exclude every captured market. This says nothing about markets that were "
                             "never captured.", action=("/opportunities" + ("?account=research" if p.account ==
                                                                              "research" else ""), "Clear filters"))
    parts.append(c.section("Market board", body, meta=cm.scope_label(p), sid="mb-h", flush=True))
    parts.append(starter)
    parts.append(decisions_detail(ctx, p))
    return cm.Page("Markets", "markets", "".join(parts), account_scoped=True)


def decisions_detail(ctx: d.Context, p: pr.Params) -> str:
    """Every recorded decision payload for the selected account, exactly as written (Gate 5 engine)."""
    view = cm.account_view(ctx, p)
    unavailable = cm.account_unavailable(view, what="Decision record")
    if unavailable:
        return c.disclosure("All recorded decisions (technical)", unavailable, boxed=True)
    rows = []
    decisions = sorted(view.decisions, key=lambda x: (str(x.get("as_of_utc")), str(x.get("decision_id"))),
                       reverse=True)
    for dec_ in decisions[:cm.MAX_ROWS]:
        opp = cm.get(dec_, "opportunity") or {}
        sizing = cm.get(dec_, "sizing")
        fill = view.fills.get(dec_.get("decision_id"))
        slot = str(dec_.get("slot") or "")
        rows.append([
            esc(dec_.get("as_of_utc")), esc(slot.split("|")[0] if slot else None), esc(dec_.get("market_id")),
            esc(dec_.get("side")), c.code(dec_.get("qualification")), esc(dec_.get("reason")),
            esc(", ".join(map(str, cm.as_list(dec_.get("reasons")))) or None),
            esc(cm.get(opp, "model_probability")), esc(cm.get(opp, "conservative_probability")),
            esc(cm.get(opp, "executable_price")), esc(cm.get(opp, "fee")), esc(cm.get(opp, "all_in_cost")),
            esc(cm.get(opp, "net_edge")), esc(cm.get(opp, "net_edge_conservative")),
            esc(cm.get(sizing, "final_size")), esc(cm.get(sizing, "binding_constraint")),
            (c.code(fill.get("status")) + " " + esc(fill.get("reason"))) if fill else esc(None),
            esc(cm.get(opp, "freshness")), esc(cm.get(opp, "fee_status")),
            c.code(dec_.get("claim_basis") or ("NONE" if dec_.get("claimable") is False else None)),
            starter_cell(dec_.get("starter_policy")),
        ])
    note = (f'<p class="note">{esc(len(view.decisions))} decisions recorded'
            + (f"; newest {cm.MAX_ROWS} shown" if len(view.decisions) > cm.MAX_ROWS else "") + ". Figures are the "
            "decision payloads written at decision time (Gate 5 engine); nothing is recomputed. Edge is net of "
            "the provisional fee schedule; prices, fees and edges are dollars per $1 contract.</p>")
    headers = ["decided (UTC)", "target", "market", "side", "qualification", "primary reason", "all reasons",
               "model P", "conservative P", "exec price", "fee", "all-in cost/contract", "net edge",
               "net edge (conservative)", "size", "binding constraint", "fill", "freshness", "fee status",
               "claim basis", "7-day starter (operational)"]
    return c.disclosure(f"All recorded decisions (technical): {cm.account_heading(view)}",
                        note + c.table(headers, rows, wrap=(6,), caption="Recorded decisions"), boxed=True)


def starter_cell(verdict) -> str:
    if not isinstance(verdict, dict):
        return esc(None)
    if verdict.get("eligible"):
        return c.code("ELIGIBLE") + " " + esc(f"{verdict.get('elapsed_hours_to_tradable')} h")
    return c.code("STARTER_POLICY_INELIGIBLE") + " " + esc(", ".join(verdict.get("reasons") or []))


# --------------------------------------------------------------------------- market detail


def _find(ctx: d.Context, p: pr.Params) -> pr.MarketRow | None:
    for r in cm.board_rows(ctx, p):
        if r.venue == p.venue and r.native_id == p.market_id:
            return r
    return None


def not_found(p: pr.Params, message: str) -> cm.Page:
    back = p.href("/opportunities")
    body = (c.page_head("Market not found") +
            c.section("No such market in captured data", c.empty_state(
                "Market not found", message, action=(back, "Back to Markets")), sid="nf-h"))
    return cm.Page("Market not found", "markets", body, status=404)


def detail(ctx: d.Context, p: pr.Params) -> cm.Page:
    if not p.venue or not p.market_id:
        return not_found(p, "A market link needs a venue and a market id.")
    row = _find(ctx, p)
    if row is None:
        return not_found(p, "No captured market or recorded decision matches this venue and id. Market ids are "
                            "matched exactly against stored records.")
    # Every section follows one side: the requested one, else the primary assessment's.
    side = p.side or (row.primary.side if row.primary and row.primary.side else "YES")
    back = p.href("/opportunities")
    crumb = f'<a class="crumb" href="{esc(back)}">{c.icon("arrow-left", "ic-sm")}<span>Markets</span></a>'
    labels = ('<div class="labels">' + c.badge("DOMAIN", label=pr.DOMAIN_LABELS.get(row.domain, "Other"), kind="nd")
              + c.badge("VENUE", label=pr.venue_label(row.venue), kind="nd")
              + (c.badge("OBSERVED", label="Captured quote", kind="info") if row.observed
                 else c.badge("DECISION", label="Decision-time price only", kind="nd"))
              + cm.research_badge(p) + "</div>")
    head = (f'<div class="page-head">{crumb}<div class="stack">{labels}'
            f'<h1 class="page-title detail-q">{esc(pr.market_title(row))}</h1>'
            f'<p class="page-sub">{esc(row.native_id)} · target {esc(pr.date_label(row.target_date) or "unknown")}'
            f' · closes {esc(pr.datetime_et(row.close_time_utc) or "time not captured")}</p></div></div>')
    main = [quote_section(row, side, p, ctx.now), history_section(ctx, row, side), assessment_section(row, side),
            venues_section(row)]
    side_col = [capital_section(row, side), ticket_section(row, side, p)]
    # Source order = the contract's phone order; Rules & evidence comes last, after the inspector.
    body = (head + '<div class="detail"><div class="detail-main">' + "".join(main) + "</div>"
            + '<aside class="detail-side" aria-label="Capital and decision preview">' + "".join(side_col)
            + "</aside></div>" + rules_section(row))
    return cm.Page(pr.market_title(row)[:80], "markets", body, account_scoped=True)


def quote_freshness(q: pr.QuoteSide, now) -> str:
    """The engine's own book-age rule (Stage B policy max_book_age) applied to the capture time."""
    if q.phase != "decision payload" and not q.capture_complete:
        return c.badge("CAPTURE_INCOMPLETE")
    state, _ = d.freshness(q.received_at_utc, now, max_age=stageb.STAGE_B_POLICY.max_book_age)
    if state == "FRESH":
        return c.badge("FRESH", label="Captured · within the engine's book-age limit")
    if state == "STALE":
        return c.badge("BOOK_STALE")
    return c.badge("UNKNOWN", label="Capture time unknown")


def quote_section(row: pr.MarketRow, side: str, p: pr.Params, now) -> str:
    tiles = "".join(c.quote_tile(row.quotes.get(s), s, c.market_href(row, p, s), current=(s == side),
                                 label=row.outcome if s == "YES" and not row.quotes.get(s) else None)
                    for s in ("YES", "NO"))
    q = row.quotes.get(side)
    if q is None:
        facts = c.empty_state("No quote for this side", "No book was captured for this side of the market.")
    else:
        facts = c.facts([
            ("Price (ask, per contract)", c.num(pr.cents(q.price), reason="no ask captured")),
            ("Price type", esc("Captured executable ask" if q.phase != "decision payload"
                               else "Decision-time executable price")),
            ("Source time", c.txt(pr.datetime_et(q.received_at_utc), reason="capture time not recorded")),
            ("Available size at ask", c.num(pr.quantity(q.size), reason="size not captured")),
            ("Freshness", quote_freshness(q, now)),
            ("Change", c.num(pr.cents(q.change, signed=True), cls=c.signed_cls(q.change),
                             reason=q.change_note) + f'<span class="cell-sub">{esc(q.change_note)}</span>'),
        ], text_cols=(1, 4))
        if q.anomaly:
            facts += c.blocked_state("Book anomaly", q.anomaly)
    return c.section("Quote", f'<div class="quote-sum">{tiles}</div>' + facts,
                     meta="Captured prices are delayed evidence, never live", sid="q-h")


def history_section(ctx: d.Context, row: pr.MarketRow, side: str) -> str:
    pts = []
    if ctx.observed.status == d.OK:
        m = next((m for m in ctx.observed.value.markets if m.market_id == row.market_id), None)
        if m is not None:
            for phase in ("decision", "recheck"):
                q = m.quotes.get(phase, {}).get(side)
                if q is not None and q.ask is not None and not q.anomaly:
                    pts.append((q.received_at_utc, q.ask))
    return c.section("Price history", c.history_chart(pts, label=f"{side} ask, captured observations"),
                     meta=f"{side} side · captured asks only", sid="hist-h")


def history_table(items) -> str:
    return c.table(["decided (UTC)", "target", "side", "qualification", "model P", "price", "net edge"],
                   [[esc(a.decided_at_utc), esc(a.target_date), esc(a.side), c.code(a.qualification),
                     esc(a.model_probability), esc(a.executable_price), esc(a.net_edge)] for a in items],
                   caption="Earlier decisions")


def assessment_section(row: pr.MarketRow, side: str) -> str:
    a = row.for_side(side)
    earlier = (c.disclosure(f"Decisions for earlier target days ({len(row.history)})", history_table(row.history))
               if row.history else "")
    if a is None:
        return c.section("Our assessment", c.empty_state(
            "Not evaluated yet", f"No decision has been recorded for the {side} side of this market's current target "
                                 "day in this account. No assessment is shown rather than a guessed 50%.") + earlier,
            sid="as-h")
    body = c.facts([
        ("Model probability", c.num(pr.percent(a.model_probability), reason="no model probability")),
        ("Conservative probability", c.num(pr.percent(a.conservative_probability), reason="not recorded")),
        ("Net expected value / contract", c.edge_value(a)),
        ("Conservative net / contract", c.num(pr.edge_cents(a.net_edge_conservative), reason="not recorded",
                                              cls=c.signed_cls(a.net_edge_conservative))),
        ("Price at decision", c.num(pr.cents(a.executable_price), reason="not recorded")),
        ("All-in cost / contract", c.num(pr.cents(a.all_in_cost), reason="not recorded")),
        ("Fee status", c.badge(a.fee_status) if a.fee_status else c.na("not recorded")),
        ("Claim basis", c.badge(a.claim_basis) if a.claim_basis else c.na("not recorded")),
    ], wide=False, text_cols=(6, 7))
    verdict = c.state_text(a.qualification if a.qualification == "QUALIFY" else (a.reason or "REJECT"))
    exact = c.kv([("decision id", c.code(a.decision_id)), ("decided at (UTC)", esc(a.decided_at_utc)),
                  ("side", esc(a.side)), ("target day", esc(a.target_date)),
                  ("model", esc(a.model_id)), ("model version", esc(a.model_version)),
                  ("qualification", c.code(a.qualification)), ("all reasons", c.ul(a.reasons)),
                  ("exact model P", esc(a.model_probability)), ("exact net edge ($/contract)", esc(a.net_edge)),
                  ("exact conservative net edge", esc(a.net_edge_conservative)), ("exact fee ($)", esc(a.fee)),
                  ("freshness", esc(a.freshness))])
    scope = ("decision for an earlier target day, not current" if row.historical
             else "recorded decision, not a current observation")
    return c.section("Our assessment", f"<p>{verdict} <span class=\"meta\">Recorded "
                     f"{esc(pr.datetime_et(a.decided_at_utc) or 'at an unknown time')} · {esc(a.side)} side · "
                     f"{scope}</span></p>" + body
                     + c.disclosure("Exact recorded values", exact) + earlier, sid="as-h")


def venues_section(row: pr.MarketRow) -> str:
    only = (f"Only {pr.venue_label(row.venue)} is captured for this market. No equivalent venue price is verified: "
            "a similar title on another venue is not settlement equivalence.")
    return c.section("Across venues", c.empty_state("No equivalent venue price verified", only)
                     + '<p class="note">Lowest observed quote, best verified total cost and best account-feasible '
                       "route are shown only when rules equivalence, fees, depth and account access are proven.</p>",
                     sid="xv-h")


OLD_NOTE = '<p class="note">Decision for an earlier target day; not current.</p>'


def capital_section(row: pr.MarketRow, side: str) -> str:
    a = row.for_side(side)  # the same side as the assessment and the ticket preview
    verdict = a.starter if a is not None and isinstance(a.starter, dict) else None
    eta = verdict.get("tradable_cash_release_eta_utc") if verdict else None
    hours = verdict.get("elapsed_hours_to_tradable") if verdict else None
    if a is None:
        body = c.empty_state("Size not evaluated", "No recorded decision, so no maximum loss, quantity or cash-release "
                                                   "estimate exists for this account.")
    else:
        body = c.facts([
            ("Requested size", c.num(pr.quantity(a.size), reason="size not evaluated")),
            ("Maximum loss (simulated fill cost)", c.money_cell(a.fill_cost, reason="no simulated fill recorded")),
            ("Binding constraint", esc(a.binding_constraint) if a.binding_constraint else c.na("not recorded")),
            ("Tradable cash ETA", c.txt(pr.datetime_et(eta), reason="not evaluated")),
            ("Hours to tradable", c.num(pr.hours_text(hours), reason="not evaluated")),
        ], text_cols=(1,))
        policy = (c.badge("ELIGIBLE") if isinstance(verdict, dict) and verdict.get("eligible") else
                  c.badge("STARTER_POLICY_INELIGIBLE") if isinstance(verdict, dict) else
                  c.badge("NOT_EVALUATED", label="Not evaluated"))
        body += f"<p>{policy} <span class=\"meta\">168-hour starter rule (same-venue tradable cash, not bank arrival)</span></p>"
        if isinstance(verdict, dict):
            body += c.disclosure("Starter verdict details", c.kv([(k, esc(v)) for k, v in sorted(verdict.items())]))
        if row.historical:
            body = OLD_NOTE + body
    return c.section("Capital & timing", body, sid="cap-h")


def ticket_section(row: pr.MarketRow, side: str, p: pr.Params) -> str:
    a = row.for_side(side)
    flag = f'<p class="ticket-flag">{c.icon("lock", "ic-sm")}Read-only · Trading disabled</p>'
    if a is None:
        body = flag + c.empty_state("No decision to preview", "Nothing was decided for this side in this account.")
    else:
        body = flag + c.facts([
            ("Side", esc(f"{a.side} · {a.outcome or ''}".strip(" ·"))),
            ("Quantity", c.num(pr.quantity(a.size), reason="size not evaluated")),
            ("Price at decision", c.num(pr.cents(a.executable_price), reason="not recorded")),
            ("Fill (simulated)", c.badge(a.fill_status) if a.fill_status else c.na("no fill recorded")),
        ], text_cols=(0,))
        if a.fill_reason and a.fill_reason not in ("FILLED",):
            body += f'<p class="note">Fill reason: {c.code(a.fill_reason)}</p>'
        if row.historical:
            body += OLD_NOTE
    body += ('<p class="note">No submit, deposit, withdrawal or approval control exists. Execution is not authorized '
             "for any venue.</p>")
    return c.section("Decision preview", body, sid="tk-h")


def rules_section(row: pr.MarketRow) -> str:
    pairs = [("full question", esc(row.title)), ("YES outcome", esc(row.outcome)),
             ("settlement definition (captured rules)", esc(row.rules_primary)),
             ("venue", esc(row.venue)), ("market id", c.code(row.market_id)), ("native id", c.code(row.native_id)),
             ("event", c.code(row.event_id)), ("payoff", esc(row.payoff_kind)), ("status (venue word)", esc(row.status)),
             ("close time (UTC)", esc(row.close_time_utc)), ("target date", esc(row.target_date))]
    for side, q in sorted(row.quotes.items()):
        pairs.append((f"{side} quote evidence", c.code(q.evidence_id) + " " + esc(f"{q.phase} · {q.received_at_utc}")))
    return c.disclosure("Rules & evidence", c.kv(pairs), boxed=True)


def more_href(**params) -> str:
    return "/market?" + urlencode(params)
