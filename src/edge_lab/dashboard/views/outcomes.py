"""Outcomes (/outcome-board): What matters today. docs/design/UI_CONTRACT.md §15."""

from __future__ import annotations

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

HORIZON_LABELS = {"within_1_hour": "Within 1 hour", "within_1_day": "Within 1 day", "within_1_week": "Within 1 week",
                  "later": "Later than 1 week", "unknown": "Unknown", "settled": "Settled"}


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
    return c.row(esc(g.outcome_cluster), sub=sub, aside=c.state_text(g.status), body=bar + facts + why)


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
        largest = max(open_groups, key=lambda g: g.account_impact, default=None)
        parts.append(c.metric_strip([
            c.metric("Linked outcome groups", c.num(pr.count(len(open_groups))), "Open or partly settled", lead=True),
            c.metric("Open risk", c.money_cell(v.state.open_worst_case_risk), "Worst case, open positions"),
            c.metric("Largest exposure", c.money_cell(largest.current_exposure) if largest else
                     c.na("no open exposure"), largest.outcome_cluster if largest else "None open"),
        ], label="Outcome exposure summary"))
        if groups:
            top = max((g.current_exposure for g in groups), default=0)
            body = '<ul class="rows">' + "".join(group_row(g, top) for g in groups) + "</ul>"
        else:
            body = c.empty_state("No linked positions",
                                 "The account loaded and holds no positions, so no outcome carries exposure.")
        parts.append(c.section("Linked outcomes", body, meta=f"Bars: current exposure · {cm.BOUND_LABEL} for max "
                                                             "loss and gain", sid="oc-h", flush=True))
    parts.append(c.disclosure("How to read the board", f"<p>{esc(how)}</p>", boxed=True))
    return cm.Page("Outcomes", "outcomes", "".join(parts), account_scoped=True)
