"""Risk & capital (/risk). docs/design/UI_CONTRACT.md §16. Policies are shown, never editable."""

from __future__ import annotations

from dataclasses import fields as dc_fields

from ... import exp001_shadow
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

RELEASE_LABELS = {
    "available_now": "Available now",
    "within_1_hour": "Within 1 hour",
    "within_1_day": "Within 1 day",
    "within_1_week": "Within 7 days",
    "locked": "Later than 7 days, unknown or delayed",
}


def limit_row(label: str, used, limit, *, used_label: str, note: str = "") -> str:
    """One limit: used vs cap when both are canonical amounts with the same definition."""
    used_d, limit_d = pr.dec(used), pr.dec(limit)
    if limit_d is None:
        aside = c.na("no limit registered")
        bar = ""
    elif used_d is None:
        aside = c.num(f"— / {pr.money(limit_d)}")
        bar = ""
    else:
        aside = c.num(f"{pr.money(used_d)} / {pr.money(limit_d)}", cls="neg" if used_d > limit_d else "")
        bar = c.bar(used_d, limit_d, kind="limit", label=f"{label}: {pr.money(used_d)} used of {pr.money(limit_d)}")
        if limit_d <= 0:
            bar = f'<p class="note">Limit is {esc(pr.money(limit_d))}: no ratio is shown.</p>'
    sub = used_label + (f" · {note}" if note else "")
    return c.row(esc(label), sub=sub, aside=aside, body=bar)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    v = cm.account_view(ctx, p)
    head = c.page_head("Risk & capital", f"{cm.scope_label(p)} · limits are shadow policy constants, not an "
                                         "owner-approved real-money policy", extra=c.account_switch(p, "/risk"))
    parts = [head]
    unavailable = cm.account_unavailable(v, what="Risk report")
    if unavailable:
        parts.append(c.section("Capacity for new positions", unavailable, sid="cap-h"))
        return cm.Page("Risk & capital", "risk", "".join(parts), account_scoped=True)
    if v.risk is None or v.risk.status != d.OK:
        message = v.risk.message if v.risk else "no risk report"
        state = (c.unavailable("Risk figures not computed", "NO DATA / NOT STARTED — " + message)
                 if v.risk is not None and v.risk.status == d.NO_DATA else c.error_state("Risk report unavailable",
                                                                                         "ERROR — " + message))
        parts.append(c.section("Capacity for new positions", state, sid="cap-h"))
    else:
        r = v.risk.value
        parts.append(c.metric_strip([
            c.metric("Tradable cash", c.money_cell(r.settled_cash), "Settled shadow cash", lead=True),
            c.metric("Committed", c.money_cell(r.committed_capital), "At cost"),
            c.metric("Remaining risk capacity", c.money_cell(r.remaining_risk_capacity), "For new positions"),
            c.metric("Realized loss · 24 h", c.money_cell(r.daily_loss), "Trailing, realized"),
            c.metric("Realized loss · 7 d", c.money_cell(r.weekly_loss), "Trailing, realized"),
            c.metric("Drawdown", c.money_cell(r.drawdown), "Below peak equity"),
        ], label=f"{cm.scope_label(p)} risk figures"))
        state = cm.risk_state(r)
        if state == "OK":
            verdict = c.status_line("ok", f"New positions allowed · capacity {pr.money(r.remaining_risk_capacity)}",
                                    "new_risk_allowed is true and no limit is breached. The risk engine does not "
                                    "report which headroom binds; the amount is exact.")
        elif state == "HALTED":
            verdict = c.status_line("err", "New positions halted",
                                    "No limit is breached, but remaining risk capacity is zero "
                                    "(new_risk_allowed is false).")
        else:
            verdict = c.status_line("err", "New positions halted · limit breached",
                                    "Breached: " + ", ".join(r.breaches) + ".")
        pol = v.policy
        per_pos = max(r.risk_per_position.values(), default=None)
        per_event = max(r.risk_per_event.values(), default=None)
        per_cluster = max(r.cluster_exposure.values(), default=None)
        limits = '<ul class="rows">' + "".join([
            limit_row("Position", per_pos, pol.max_position_risk, used_label="Largest single position, worst case"),
            limit_row("Event", per_event, pol.max_event_risk, used_label="Largest event, worst case"),
            limit_row("Related outcomes", per_cluster, pol.max_cluster_risk, used_label="Largest outcome cluster"),
            limit_row("Portfolio", r.open_worst_case_risk, pol.max_portfolio_risk, used_label="Open worst-case risk"),
            limit_row("Daily loss", r.daily_loss, pol.daily_loss_limit, used_label="Realized, trailing 24 h"),
            limit_row("Weekly loss", r.weekly_loss, pol.weekly_loss_limit, used_label="Realized, trailing 7 d"),
            limit_row("Drawdown", r.drawdown, pol.max_drawdown, used_label="Below peak equity"),
        ]) + "</ul>"
        if per_pos is None:
            limits += '<p class="note">No open positions: per-position, event and cluster usage is not applicable.</p>'
        parts.append(c.section("Capacity for new positions", verdict.replace('class="statusline', 'class="statusline flat', 1)
                               + limits, meta=f"Policy {pol.policy_id}", sid="cap-h"))
        release = '<ul class="rows">' + "".join(
            c.row(esc(RELEASE_LABELS.get(b.horizon, b.horizon)),
                  sub=f"{b.positions} position(s) · best-case payout {pr.money(b.best_case_payout)} is never counted "
                      "as cash" if b.horizon != "available_now" else "Settled shadow cash",
                  aside=c.money_cell(b.committed_capital))
            for b in r.capital_release) + "</ul>"
        parts.append(c.section("Capital release", release + '<p class="note">Separate windows from the risk engine '
                               "(each position appears once; the windows are not cumulative). Overdue or unknown "
                               "settlement is delayed, never about to release.</p>", sid="rel-h", flush=False))
    parts.append(starter_section(v, ctx))
    parts.append(c.section("Withdrawal", c.blocked_state("Not enabled", "There is no withdrawal action. Withdrawal "
                                                         "recommendations are unavailable (NOT RECOMMENDED)."),
                           sid="wd-h"))
    parts.append(policy_details(v, ctx))
    return cm.Page("Risk & capital", "risk", "".join(parts), account_scoped=True)


def starter_section(v: d.AccountView, ctx: d.Context) -> str:
    s = d.starter_view(v, ctx.now)
    text = ("Starter rule: estimated tradable cash within 168 hours. New operational capital goes only where "
            "settled cash is expected to be tradable again on the same venue within 168 elapsed hours of the "
            "commitment. This is about reusing proceeds on the venue, not arrival in a bank.")
    if s is None:
        return c.section("Starter rule", f'<p class="note">{esc(text)}</p>' + c.unavailable(
            "Not applied to this account", "The frozen research account is never affected by the starter policy."),
            sid="st-h")
    exc = s["exceptions"]
    head = (c.status_line("err", f"{len(exc)} current exception(s)", "Capital stays reserved; nothing is force-sold.")
            if exc else c.status_line("ok", "No current exceptions", "")).replace('class="statusline', 'class="statusline flat', 1)
    return c.section("Starter rule", f"<p>{esc(text)}</p>" + head, meta=s["policy_id"], sid="st-h")


def _policy_rows(policy) -> list[list[str]]:
    return [[esc(f.name), c.money_cell(getattr(policy, f.name)) if f.name != "policy_id" else esc(policy.policy_id)]
            for f in dc_fields(policy)]


def policy_details(v: d.AccountView, ctx: d.Context) -> str:
    body = f'<p class="note">{esc(v.role.note if v.role else "")}</p>'
    if v.policy is not None:
        body += f'<h3 class="eyebrow">Risk policy caps ({esc(v.policy.policy_id)})</h3>' + c.table(
            ["limit", "value"], _policy_rows(v.policy), caption="Risk policy caps")
    if v.risk is not None and v.risk.status == d.OK:
        r = v.risk.value
        body += '<h3 class="eyebrow">Risk report</h3>' + c.kv([
            ("as of", esc(r.as_of_utc)), (cm.EQUITY_LABEL, c.money_cell(r.equity)),
            ("settled cash", c.money_cell(r.settled_cash)), ("reserve floor", c.money_cell(r.reserve_floor)),
            ("committed capital", c.money_cell(r.committed_capital)),
            ("open worst-case risk", c.money_cell(r.open_worst_case_risk)),
            ("remaining risk capacity", c.money_cell(r.remaining_risk_capacity)),
            ("peak equity", c.money_cell(r.peak_equity)), ("drawdown", c.money_cell(r.drawdown)),
            ("trailing 24 h realized loss", c.money_cell(r.daily_loss)),
            ("trailing 7 d realized loss", c.money_cell(r.weekly_loss)),
            ("breaches", c.ul(r.breaches)), ("new risk allowed", cm.risk_line(r)), ("notes", c.ul(r.notes)),
        ])
        body += '<h3 class="eyebrow">Capital release by horizon</h3>' + c.table(
            ["horizon", "committed / cash", "guaranteed cash", "best-case payout (never counted as cash)", "positions"],
            [[c.code(b.horizon), c.money_cell(b.committed_capital), c.money_cell(b.guaranteed_cash),
              c.money_cell(b.best_case_payout), esc(b.positions)] for b in r.capital_release])
        body += '<h3 class="eyebrow">Exposure by event</h3>' + c.table(
            ["event", "worst-case risk"], [[esc(k), c.money_cell(x)] for k, x in r.risk_per_event.items()])
        body += '<h3 class="eyebrow">Exposure by outcome cluster</h3>' + c.table(
            ["cluster", "worst-case risk"], [[esc(k), c.money_cell(x)] for k, x in r.cluster_exposure.items()])
    sizing_id = v.opened.get("sizing_policy_id")
    body += f'<h3 class="eyebrow">Sizing policy ({esc(sizing_id)})</h3>'
    if sizing_id == exp001_shadow.SIZING_POLICY.policy_id:
        body += c.table(["parameter", "value"], [[esc(f.name), esc(getattr(exp001_shadow.SIZING_POLICY, f.name))]
                                                 for f in dc_fields(exp001_shadow.SIZING_POLICY)])
    elif sizing_id == exp001_shadow.RESEARCH_SIZING_ID:
        body += ('<p class="note">' + esc("Frozen EXP-001 rule: exactly 1 contract per signalled bracket, "
                                          "latency-confirmed-v1 fills, no operational caps and no risk vetoes. "
                                          "Never re-tuned.") + "</p>")
    else:
        body += '<p class="na">sizing policy parameters are not registered in this dashboard</p>'
    counts: dict[str, int] = {}
    for dec_ in v.decisions:
        constraint = cm.get(cm.get(dec_, "sizing"), "binding_constraint")
        if constraint is not None:
            counts[constraint] = counts.get(constraint, 0) + 1
    body += '<h3 class="eyebrow">Binding sizing constraints (qualified decisions)</h3>' + c.table(
        ["binding constraint", "decisions"], [[esc(k), esc(x)] for k, x in sorted(counts.items())])
    s = d.starter_view(v, ctx.now)
    if s is not None:
        body += (f'<h3 class="eyebrow">Seven-day starter policy ({esc(s["policy_id"])})</h3><p class="note">' + esc(
            f"Eligible only if settled cash is expected to be tradable again on the same venue within "
            f"{s['max_hours']} elapsed hours of the commitment (governing clock: tradable_cash_release_eta). "
            f"Applies to operational decisions from {s['effective_from_utc']}; the research account is never "
            "affected. A position that runs past its expected release is an exception: capital stays reserved, "
            "nothing is force-sold.") + "</p>")
        body += '<h4 class="eyebrow">Exceptions</h4>' + c.table(
            ["fill", "market", "committed", "expected tradable cash", "past 168 h", "action"],
            [[esc(e["fill_id"]), esc(e["market_id"]), esc(e["commitment_utc"]), esc(e["tradable_cash_release_eta_utc"]),
              esc(e["past_168h"]), esc(e["action"])] for e in s["exceptions"]])
        body += '<h4 class="eyebrow">Verdicts on fills</h4>' + c.table(
            ["fill", "eligible", "reasons", "committed", "resolution ETA", "tradable cash ETA (governs)",
             "hours to tradable", "abnormal-path bound (reported only)"],
            [[esc(f.get("fill_id")), c.code("ELIGIBLE" if f["starter_policy"].get("eligible") else
                                            "STARTER_POLICY_INELIGIBLE"),
              esc(", ".join(f["starter_policy"].get("reasons") or []) or None),
              esc(f["starter_policy"].get("commitment_utc")), esc(f["starter_policy"].get("resolution_eta_utc")),
              esc(f["starter_policy"].get("tradable_cash_release_eta_utc")),
              esc(f["starter_policy"].get("elapsed_hours_to_tradable")),
              esc(f["starter_policy"].get("abnormal_path_bound_utc"))]
             for f in s["verdicts"][-cm.MAX_ROWS:]], wrap=(2, 7))
    body += withdrawal(v)
    return c.disclosure(f"Policy details: {cm.account_heading(v)}", body, boxed=True)


def withdrawal(v: d.AccountView) -> str:
    head = (f'<h3 class="eyebrow">Withdrawal</h3><p>{c.badge("NOT_RECOMMENDED", label="NOT RECOMMENDED")} '
            "Withdrawal recommendations are unavailable.</p>")
    if v.withdrawal is None or v.withdrawal.status != d.OK:
        return head + f'<p class="na">{esc(v.withdrawal.message if v.withdrawal else None)}</p>'
    w = v.withdrawal.value
    return head + c.kv([
        ("recommendation status", c.code(w.recommendation_status)),
        ("recommended owner draw", esc(w.recommended_owner_draw) if w.recommended_owner_draw is not None
         else "none (no recommendation exists)"),
        ("technically withdrawable (simulated arithmetic only; NOT available, NOT recommended)",
         c.money_cell(w.technically_withdrawable)),
        ("policy-safe bound (simulated arithmetic only; NOT available, NOT recommended)",
         c.money_cell(w.policy_safe_withdrawable)),
        ("why not recommended", c.ul(w.reasons)),
    ])
