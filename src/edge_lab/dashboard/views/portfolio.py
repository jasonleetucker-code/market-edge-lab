"""Portfolio (/positions). docs/design/UI_CONTRACT.md §14."""

from __future__ import annotations

from urllib.parse import urlencode

from ...freshness import parse_utc
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from .terminal import conflicts_table


def position_state(pos, now) -> str:
    """open | settling | closed, from the ledger's status and its recorded expected settlement."""
    if pos.status == "SETTLED":
        return "closed"
    expected = parse_utc(pos.expected_settlement_utc)
    return "settling" if expected is not None and expected < now else "open"


def metrics(view: d.AccountView, p: pr.Params) -> str:
    s = view.state
    return c.metric_strip([
        c.metric("Shadow equity", c.money_cell(s.equity), "Cost basis, not liquidation value", lead=True),
        c.metric("Tradable cash", c.money_cell(s.settled_cash), "Settled shadow cash"),
        c.metric("Committed", c.money_cell(s.committed_capital), "Open positions at cost"),
        c.metric("Open worst-case risk", c.money_cell(s.open_worst_case_risk), "Upper bound"),
        c.metric("Realized P&L", c.money_cell(s.realized_pnl, signed=True), "Settled on official evidence"),
    ], label=f"{cm.scope_label(p)} balances")


def position_row(pos, view: d.AccountView, now) -> str:
    state = position_state(pos, now)
    fill = view.fills.get(pos.decision_id) or {}
    verdict = fill.get("starter_policy") if isinstance(fill.get("starter_policy"), dict) else None
    eta = verdict.get("tradable_cash_release_eta_utc") if verdict else None
    state_code = {"open": "OPEN", "settling": "PENDING_SETTLEMENT", "closed": "SETTLED"}[state]
    label = {"open": "Open · awaiting settlement", "settling": "Settling · pending official evidence",
             "closed": "Settled"}[state]
    if pos.expected_settlement_utc is None and state == "open":
        label = "Open · no expected time (locked)"
    venue, _, native = pos.market_id.partition(":")
    title = f'<a href="/market?{esc(urlencode({"venue": venue, "id": native, "side": pos.side}))}">{esc(native or pos.market_id)}</a>'
    facts = [
        ("Side · quantity", esc(f"{pos.side} · {pos.quantity}")),
        ("Entry price", c.num(pr.cents(pos.price))),
        ("Cost", c.money_cell(pos.cost_basis)),
        ("Maximum loss", c.money_cell(pos.max_downside)),
        ("Expected settlement", c.txt(pr.datetime_et(pos.expected_settlement_utc), reason="no expected time")),
        ("Tradable cash ETA", c.txt(pr.datetime_et(eta), reason="not recorded for this fill")),
    ]
    if state == "closed":
        facts += [("Outcome", esc(pos.outcome)), ("Payout", c.money_cell(pos.payout)),
                  ("Realized result", c.money_cell(pos.net_pnl, signed=True))]
    detail = c.disclosure("Position details", c.kv([
        ("position id", c.code(pos.position_id)), ("decision id", c.code(pos.decision_id)),
        ("market", c.code(pos.market_id)), ("event", c.code(pos.event_id)), ("cluster", esc(pos.outcome_cluster)),
        ("opened (UTC)", esc(pos.opened_at_utc)), ("fees", c.money_cell(pos.fees)),
        ("expected settlement (UTC)", esc(pos.expected_settlement_utc)), ("settled at (UTC)", esc(pos.settled_at_utc)),
        ("strategy", esc(pos.strategy))]))
    return c.row(title, sub=f"{pr.venue_label(venue)} · {pr.cluster_label(pos.outcome_cluster)}",
                 aside=c.state_text(state_code, label=label), body=c.facts(facts, wide=True, text_cols=(0,)) + detail)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    v = cm.account_view(ctx, p)
    extra = {"state": p.state} if p.state else None
    head = c.page_head("Portfolio", f"{cm.scope_label(p)} · simulated positions and balances",
                       extra=c.account_switch(p, "/positions", extra))
    parts = [head]
    if p.account == "research":
        parts.append(f'<p class="note">{cm.research_badge(p)} The frozen research account is shown alone; its '
                     "notional bankroll is never added to the operational account.</p>")
    unavailable = cm.account_unavailable(v, what="Portfolio")
    if unavailable:
        if ctx.ledger.status == d.ERROR:
            parts.append(c.section("Positions", c.error_state("Ledger could not be loaded",
                                                              f"ERROR — {ctx.ledger.message}. This is not an empty "
                                                              "portfolio."), sid="pos-h"))
        else:
            parts.append(c.section("Positions", unavailable, sid="pos-h"))
    else:
        parts.append(metrics(v, p))
        now = ctx.now
        positions = sorted(v.state.positions, key=lambda x: (str(x.opened_at_utc), x.position_id), reverse=True)
        counts = {k: sum(1 for x in positions if k == "all" or position_state(x, now) == k)
                  for k, _ in pr.POSITION_STATES}
        cur = p.position_state()
        items = []
        for key, label in pr.POSITION_STATES:
            params = {"state": key} if key != "open" else {}
            if p.account != "operational":
                params["account"] = p.account
            items.append(("/positions" + ("?" + urlencode(params) if params else ""), label, key == cur,
                          str(counts[key])))
        shown = [x for x in positions if cur == "all" or position_state(x, now) == cur]
        if shown:
            content = '<ul class="rows">' + "".join(position_row(x, v, now) for x in shown[:cm.MAX_ROWS]) + "</ul>"
        elif not positions:
            evaluated = v.state.decisions > 0
            content = c.empty_state(
                "No open shadow positions",
                "Positions will appear after a qualifying decision and simulated fill."
                if evaluated else "Not evaluated yet: no decision has been recorded for this account, so no position "
                                  "could exist.")
        else:
            content = c.empty_state(f"No {dict(pr.POSITION_STATES)[cur].lower()} positions",
                                    f"{len(positions)} position(s) exist in other states.")
        parts.append(c.section("Positions", c.tabs(items, label="Position state") + content,
                               meta="Carried at cost · realized only on settlement evidence", sid="pos-h", flush=True))
        parts.append(ledger_detail(v))
    parts.append(c.disclosure("How these balances are calculated", f"<p>{esc(cm.ACCOUNTING_NOTE)}</p>", boxed=True))
    parts.append(receipt_settlements(ctx))
    return cm.Page("Portfolio", "portfolio", "".join(parts), account_scoped=True)


def ledger_detail(v: d.AccountView) -> str:
    s = v.state
    body = f'<p class="note">{esc(v.role.note if v.role else "")}</p>' + c.kv([
        (cm.BANKROLL_LABEL, c.money_cell(s.starting_bankroll)), (cm.EQUITY_LABEL, c.money_cell(s.equity)),
        ("realized P&L", c.money_cell(s.realized_pnl, signed=True)), ("fees paid", c.money_cell(s.fees_paid)),
        ("committed capital", c.money_cell(s.committed_capital)),
        ("fills / no-fills / settlements", f"{esc(s.fills)} / {esc(s.no_fills)} / {esc(s.settlements)}"),
    ])
    body += '<h3 class="eyebrow">NO_FILL reasons</h3>' + c.table(
        ["reason", "count"], [[c.badge_code(k), esc(v_)] for k, v_ in sorted(s.no_fill_reasons.items())])
    fills = sorted(v.fills.values(), key=lambda f: (str(f.get("filled_at_utc")), str(f.get("fill_id"))), reverse=True)
    body += '<h3 class="eyebrow">Simulated fills (FILLED and NO_FILL)</h3>' + c.table(
        ["filled at (UTC)", "fill id", "market", "side", "status", "reason", "qty", "price", "fee", "total cost",
         "fee schedule", "detail"],
        [[esc(f.get("filled_at_utc")), esc(f.get("fill_id")), esc(f.get("market_id")), esc(f.get("side")),
          c.code(f.get("status")), esc(f.get("reason")), esc(f.get("quantity")), c.money_cell(f.get("price")),
          c.money_cell(f.get("fee")), c.money_cell(f.get("total_cost")), esc(f.get("fee_schedule_id")),
          esc(f.get("detail"))] for f in fills[:cm.MAX_ROWS]], wrap=(11,), caption="Simulated fills")
    settled = sorted((x for x in s.positions if x.status == "SETTLED"), key=lambda x: str(x.settled_at_utc), reverse=True)
    body += '<h3 class="eyebrow">Settled positions</h3>' + c.table(
        ["position", "market", "side", "qty", "cost basis", "outcome", "payout", "net P&L", "settled at",
         "evidence snapshot"],
        [[esc(x.position_id), esc(x.market_id), esc(x.side), esc(x.quantity), c.money_cell(x.cost_basis),
          esc(x.outcome), c.money_cell(x.payout), c.money_cell(x.net_pnl, signed=True), esc(x.settled_at_utc),
          esc(cm.get(cm.get(v.settlements.get(x.position_id), "evidence"), "snapshot_id"))] for x in settled],
        caption="Settled positions")
    return c.disclosure(f"Ledger record: {cm.account_heading(v)}", body, boxed=True)


def receipt_settlements(ctx: d.Context) -> str:
    if ctx.receipt.status != d.OK:
        missing = cm.loaded_state("Pending settlements reported by the latest receipt", ctx.receipt)
        return c.section("Settlement evidence", missing or "", sid="se-h")
    settlement = cm.get(ctx.receipt.value, "settlement")
    pending = cm.as_list(cm.get(settlement, "pending"))
    conflicts = cm.as_list(cm.get(settlement, "conflicts"))
    body = ""
    if conflicts:
        body += c.blocked_state(f"{len(conflicts)} settlement conflict(s)",
                                "Official evidence snapshots disagree. The position is not settled (or its settlement "
                                "is questioned) until the owner reviews the evidence.")
    body += ('<h3 class="eyebrow">Pending settlements reported by the latest receipt</h3>' + c.table(
        ["account", "position", "reason"],
        [[esc(cm.get(x, "account_id")), esc(cm.get(x, "position_id")), esc(cm.get(x, "reason"))] for x in pending],
        wrap=(2,)))
    body += ('<h3 class="eyebrow">Settlement evidence conflicts reported by the latest receipt</h3>'
             + conflicts_table(conflicts)
             + '<p class="note">A conflict means official evidence snapshots disagree; the position is not settled '
               "(or its settlement is questioned) until the owner reviews the evidence.</p>")
    return c.section("Settlement evidence", body, meta=f"Receipt {pr.datetime_et(cm.receipt_time(ctx)) or ''}",
                     sid="se-h")
