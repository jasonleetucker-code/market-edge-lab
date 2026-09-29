"""In-play research (/experiments/inplay) and its demo-only state gallery (/gallery/inplay). Owner Idea 122, §21B.

Formats the `inplay_view` contract (schema inplay-view/1) with the shared components only. It computes
nothing: every figure is the contract's string, formatted by `presentation`. Honesty rules:
- never LIVE: the mode badge says fixture, synthetic or not authorized;
- inventory is simulated and there is no balance;
- exit proceeds are an estimate at displayed depth, not a fill;
- replay P&L comes from a synthetic cohort; oracle diagnostics sit in a disclosure;
- no edge score, input, order or trade control.

It lives under Research & Data (nav "research"), and no global navigation item is added.
"""

from __future__ import annotations

from typing import Any

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

MODE_LABELS = {"FIXTURE": "Fixture replay · not live", "SYNTHETIC_REPLAY": "Synthetic replay · not live",
               "NOT_AUTHORIZED": "No in-play source authorized"}
STATE_WORDS = {  # (label, kind): nothing is green; a populated fixture is information, not success
    "POPULATED": ("Fixture evidence", "info"), "EMPTY": ("No evidence in journal", "nd"),
    "STALE": ("Stale book — not actionable", "warn"), "PARTIAL": ("Partial evidence", "warn"),
    "UNSUPPORTED": ("Policy unsupported", "nd"), "PAUSED": ("Market paused", "warn"),
    "ERROR": ("Data unavailable", "err"), "NOT_AUTHORIZED": ("Not authorized", "warn"),
}
ACTION_WORDS = {"HOLD": ("Hold", "nd"), "REDUCE": ("Reduce · proposal only", "info"),
                "EXIT": ("Exit · proposal only", "info")}
DECISION_WORDS = {"PROPOSED": ("Proposed · not sent", "info"), "BLOCKED": ("Blocked · no new risk", "warn"),
                  "UNSUPPORTED": ("Unsupported", "nd"), "NO_POSITION": ("No position", "nd")}
BOOK_WORDS = {"VALID": ("Reconstructed", "info"), "NO_VALID_START": ("No valid start", "warn"),
              "GAP_AWAITING_RESYNC": ("Gap · awaiting resync", "warn"),
              "INVALID_AWAITING_RESYNC": ("Invalid · awaiting resync", "warn")}
TRADING_WORDS = {"OPEN": ("Open", "nd"), "TRADING_PAUSED": ("Trading paused", "warn"),
                 "EXCHANGE_PAUSED": ("Exchange paused", "warn"), "MARKET_CLOSED": ("Closed", "nd"),
                 "UNKNOWN": ("Unknown", "warn")}
ARM_LABELS = {("HOLD", None): "Hold to settlement", ("FULL_EXIT", "BOT_TRIGGERED"): "Full exit · bot-triggered",
              ("FULL_EXIT", "PREPLACED_LIMIT"): "Full exit · preplaced limit",
              ("PARTIAL_EXIT", "BOT_TRIGGERED"): "Partial exit · bot-triggered",
              ("PARTIAL_EXIT", "PREPLACED_LIMIT"): "Partial exit · preplaced limit"}
FEE_UNKNOWN = "after-cost figure unavailable: fee unknown"


def _word(table: dict, code: Any, prefix: str) -> str:
    label, kind = table.get(code, (str(code).replace("_", " ").capitalize() if code else "Not recorded", "nd"))
    return c.state_text(f"{prefix}_{code}", label=label, kind=kind)


def _badge(table: dict, code: Any, prefix: str) -> str:
    label, kind = table.get(code, (str(code).replace("_", " ").capitalize() if code else "Not recorded", "nd"))
    return c.badge(f"{prefix}_{code}", label=label, kind=kind)


def _money(value: Any, reason: str, *, signed: bool = False) -> str:
    """Money with its sign but never coloured: replay figures come from fixtures or synthetic cohorts,
    and a green figure would read as a result (nothing here is green)."""
    return c.num(pr.money(value, signed=signed), reason=reason)


def _seconds(value: Any, reason: str) -> str:
    v = pr.dec(value)
    return c.num(None if v is None else f"{v.normalize():f} s", reason=reason)


def header(view: dict[str, Any]) -> str:
    mode, state = view.get("mode"), view.get("state")
    capsules = (_badge({k: (v, "warn") for k, v in MODE_LABELS.items()}, mode, "INPLAY_MODE") + " "
                + _badge(STATE_WORDS, state, "INPLAY_STATE"))
    label, kind = STATE_WORDS.get(state, ("Unknown state", "warn"))
    kind = {"info": "info", "warn": "warn", "err": "err"}.get(kind, "nd")
    top = f'<p class="meta">{esc(view.get("label") or "")}</p><p>{capsules}</p>'
    if state in ("ERROR", "NOT_AUTHORIZED"):  # the error or blocked state below carries the detail once
        return top
    as_of = view.get("as_of_utc")
    clock =(f"Replay clock {pr.datetime_et(as_of)} (the fixture's time, not now)." if as_of else
             "No replay clock: nothing was replayed.")
    return top + c.status_line(kind, label, f"{view.get('detail') or ''} {clock}".strip())


def position_section(view: dict[str, Any]) -> str:
    con, src, inv = view.get("contract") or {}, view.get("source") or {}, view.get("inventory") or {}
    if view.get("state") == "EMPTY":
        body = c.empty_state("No book messages", "The journal loaded and holds no book message for this market. "
                                                 "Nothing is shown as a price.")
    else:
        body = ""
    facts = c.facts([
        ("Contract", c.txt(con.get("native_id"), reason="no contract")),
        ("Game", c.txt(con.get("game"), reason="no game label")),
        ("Book", _word(BOOK_WORDS, src.get("book_status"), "INPLAY_BOOK")),
        ("Book age at replay clock", _seconds(src.get("age_seconds"), "no book received")),
        ("Coverage in window", c.num(pr.percent(src.get("coverage_fraction")), reason="not evaluated")),
        ("Market", _word(TRADING_WORDS, src.get("trading_state"), "INPLAY_TRADING")),
        ("Initial inventory · simulated", c.num(pr.count(pr.dec(inv.get("initial"))), reason="no inventory")),
        ("Remaining · simulated", c.num(pr.count(pr.dec(inv.get("remaining"))), reason="no inventory")),
        ("Reserved by resting sales", c.num(pr.count(pr.dec(inv.get("reserved"))), reason="not evaluated")),
    ], text_cols=(0, 1))
    failures = src.get("failures") or []
    detail = c.disclosure("Source and reconstruction details", c.kv([
        ("route", c.code(src.get("route"))), ("contract version", c.code(src.get("contract_version"))),
        ("last book receipt", c.txt(pr.datetime_et(src.get("last_receipt_utc")), reason="none")),
        ("last source timestamp", c.txt(pr.datetime_et(src.get("last_source_ts_utc")), reason="not sent")),
        ("max book age", _seconds(src.get("max_age_seconds"), "not set")),
        ("gaps", c.num(pr.count(src.get("gaps")), reason="not evaluated")),
        ("resyncs", c.num(pr.count(src.get("resyncs")), reason="not evaluated")),
        ("duplicates ignored", c.num(pr.count(src.get("duplicates")), reason="not evaluated")),
        ("deltas before a valid start", c.num(pr.count(src.get("ignored_before_start")), reason="not evaluated")),
        ("parse failures", c.num(pr.count(src.get("parse_failures")), reason="not evaluated")),
        ("unusable time", c.ul([f"{u.get('reason')}: {u.get('seconds')} s" for u in src.get("unusable") or []],
                               empty="none")),
        ("failures kept", c.ul([f"{f.get('kind')} at {pr.datetime_et(f.get('at_utc'))}: {f.get('detail')}"
                                for f in failures], empty="none")),
        ("rules version", c.code(con.get("rules_version"))), ("data kind", c.code(con.get("data_kind"))),
    ]))
    return c.section("Position · simulated", body + facts + detail, meta="Simulated inventory · no account read",
                     sid="ip-pos")


def policy_section(view: dict[str, Any]) -> str:
    pol, est = view.get("policy") or {}, view.get("exit_estimate") or {}
    reasons = pol.get("reasons") or []
    action = (_badge(ACTION_WORDS, pol.get("action"), "INPLAY_ACTION") if pol.get("action") else
              c.na("no action: the decision is blocked or unsupported"))
    facts = c.facts([
        ("Proposal", action),
        ("Decision", _word(DECISION_WORDS, pol.get("status"), "INPLAY_DECISION")),
        ("Quantity", c.num(pr.count(pr.dec(pol.get("quantity"))), reason="none")),
        ("Limit", c.num(pr.cents(pol.get("limit_price")), reason="no limit")),
        ("Execution assumption", c.txt((pol.get("execution") or "").replace("_", " ").lower() or None,
                                       reason="none")),
        ("Primary reason", c.txt(reasons[0] if reasons else None, reason="no reason recorded")),
    ], text_cols=(4, 5))
    size = pr.count(pr.dec(est.get("quantity")))
    estimate = c.facts([
        ("Contracts", c.num(size, reason="no inventory")),
        ("Gross at displayed bids", _money(est.get("gross"), "no usable book or not fillable at displayed depth")),
        ("Sale fees", _money(est.get("fee"), "fee unknown for this series")),
        ("Net proceeds (not profit)", _money(est.get("net"), FEE_UNKNOWN)),
        ("Worst price taken", c.num(pr.cents(est.get("worst_price")), reason="not fillable")),
    ])
    note = f'<p class="meta">{esc(est.get("note") or "")}</p>'
    detail = c.disclosure("Policy details", c.kv([
        ("policy", c.code(pol.get("policy_id"))), ("policy version", c.code(pol.get("policy_version"))),
        ("policy kind", c.code(pol.get("policy_kind"))), ("evaluator", c.code(pol.get("evaluator"))),
        ("decision id", c.code(pol.get("decision_id"))), ("all reasons", c.ul(reasons)),
        ("proposal gross at the target", _money(pol.get("gross_proceeds"), "not a bot-triggered sale now")),
        ("proposal net", _money(pol.get("net_proceeds"), FEE_UNKNOWN)),
        ("fee claim basis", c.code(pol.get("fee_claim_basis"))),
        ("no new risk", esc("yes" if pol.get("no_new_risk") else "no")),
        ("authorizes execution", esc("no" if not pol.get("authorizes_execution") else "INVALID")),
    ]))
    body = facts + '<h3 class="eyebrow">Exit proceeds estimate at size</h3>' + estimate + note + detail
    return c.section("Policy proposal", body, meta="Research proposal · nothing is sent · no trade control",
                     sid="ip-pol")


def comparison_section(view: dict[str, Any]) -> str:
    comp = view.get("comparison")
    if not comp:
        return c.section("Hold versus exit", c.unavailable(
            "No replay", "No cohort was replayed for this state, so no comparison is shown."), sid="ip-cmp")
    rows = []
    for a in comp.get("arms") or []:
        title = ARM_LABELS.get((a.get("arm"), a.get("semantics")), f"{a.get('arm')} · {a.get('semantics')}")
        incomplete = a.get("incomplete") or 0
        not_placed = a.get("not_placed") or 0
        aside = c.state_text("INPLAY_ENTRIES", label=f"{a.get('complete')}/{a.get('entries')} complete",
                             kind="warn" if incomplete or not_placed else "nd")
        is_hold = a.get("arm") == "HOLD"
        placed = ([("Resting sale never placed", c.num(pr.count(not_placed), reason="not recorded"))]
                  if a.get("semantics") == "PREPLACED_LIMIT" else [])
        facts = c.facts([
            ("Replay P&L (gross)", _money(a.get("pnl_gross"), "incomplete entries: not valued", signed=True)),
            ("Replay P&L (net)", _money(a.get("pnl_net"), FEE_UNKNOWN, signed=True)),
            ("Change vs hold (gross)", c.na("the baseline") if is_hold else
             _money(a.get("change_vs_hold_gross"), "not comparable: incomplete", signed=True)),
            ("Change vs hold (net)", c.na("the baseline") if is_hold else
             _money(a.get("change_vs_hold_net"), FEE_UNKNOWN, signed=True)),
            ("Worst entry (gross)", _money(a.get("worst_entry_pnl_gross"), "no complete entry", signed=True)),
            ("Best entry (gross)", _money(a.get("best_entry_pnl_gross"), "no complete entry", signed=True)),
        ] + placed)
        rows.append(c.row(esc(title), sub=f"{a.get('entries')} entries · {a.get('clusters')} clusters",
                          aside=aside, body=facts))
    diag = view.get("diagnostics") or []
    diag_table = c.table(["diagnostic", "arm", "entries", "with a value", "gross proceeds (sum)", "meaning"],
                         [[c.code(x.get("label")), esc(x.get("arm")), esc(x.get("entries")), esc(x.get("with_value")),
                           _money(x.get("gross_proceeds_total"), "never reached"), esc(x.get("note"))]
                          for x in diag], wrap=(5,), caption="Oracle diagnostics (not policy results)")
    details = c.disclosure("Diagnostics, notes and provenance", diag_table + c.kv([
        ("after-cost claim", esc("permitted" if view.get("after_cost_claim") else "not permitted")),
        ("why", esc(view.get("after_cost_reason"))),
        ("cohort", c.code(comp.get("cohort_id"))), ("cohort sha256", c.code(comp.get("cohort_sha256"))),
        ("cohort label", esc(comp.get("label"))), ("config variant", c.code(comp.get("config_variant"))),
        ("fill rule", c.code(comp.get("fill_rule"))), ("fee model", c.code(comp.get("fee_model"))),
        ("diagnostic mode", c.code(comp.get("diagnostic_mode")) if comp.get("diagnostic_mode") else
         esc("none: a policy replay with modelled latency")),
        ("fee claim basis", c.code(comp.get("fee_claim_basis"))), ("replay", c.code(comp.get("replay_version"))),
        ("notes", c.ul(comp.get("notes") or [])),
    ]))
    meta = f"{comp.get('data_kind')} cohort · identical entries in every arm · not evidence of an edge"
    return c.section("Hold versus exit", '<ul class="rows">' + "".join(rows) + "</ul>" + details, meta=meta,
                     sid="ip-cmp", flush=True)


def authority_section(view: dict[str, Any]) -> str:
    body = c.facts([
        ("Authority", c.txt(view.get("authority"), reason="not recorded")),
        ("Pilot", c.txt(view.get("pilot"), reason="not recorded")),
        ("Blocker", c.txt(view.get("blocker"), reason="none recorded")),
    ], wide=True, text_cols=(0, 1, 2))
    assumptions = view.get("assumptions") or []
    if assumptions:
        body += c.disclosure("Assumptions", c.ul(assumptions))
    return c.section("Blocker and approval", body, sid="ip-auth")


def inplay_body(view: dict[str, Any]) -> str:
    """The whole in-play view for one inplay-view/1 mapping (also used per state in the gallery)."""
    state = view.get("state")
    parts = [header(view)]
    if state == "ERROR":
        parts.append(c.error_state("In-play evidence unavailable", view.get("detail") or "read failure"))
        parts.append(authority_section(view))
        return "".join(parts)
    if state == "NOT_AUTHORIZED":
        parts.append(c.blocked_state("No in-play source is authorized", view.get("detail") or "",
                                     action=("/experiments", "Research & Data")))
        parts.append(authority_section(view))
        return "".join(parts)
    parts += [position_section(view), policy_section(view), comparison_section(view), authority_section(view)]
    return "".join(parts)


def _crumb() -> str:
    return f'<a class="crumb" href="/experiments">{c.icon("arrow-left", "ic-sm")}<span>Research &amp; Data</span></a>'


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head("In-play research", "Owner Idea 122 · hold versus exit · research only", crumb=_crumb())
    loaded = d.inplay_view(ctx)
    missing = cm.loaded_state("In-play research view", loaded)
    body = missing if missing else inplay_body(loaded.value)
    return cm.Page("In-play research", "research", head + '<div class="stack">' + body + "</div>")


def gallery(ctx: d.Context, p: pr.Params) -> cm.Page:
    label = '<p class="gallery-label">FIXTURE STATES · in-play research view · demo mode only</p>'
    head = c.page_head("In-play states", "Every state of the in-play research view, from fixtures.", extra=label,
                       crumb=_crumb())
    loaded = d.inplay_fixture_views(ctx)
    missing = cm.loaded_state("In-play fixture states", loaded)
    if missing:
        return cm.Page("In-play states", "research", head + missing)
    parts = []
    for name, item in loaded.value.items():
        inner = cm.loaded_state(f"State {name}", item) or inplay_body(item.value)
        parts.append(c.section(f"State · {name}", inner, sid=f"ip-g-{name}", level=2))
    return cm.Page("In-play states", "research", head + '<div class="stack">' + "".join(parts) + "</div>")


INPLAY_PAGES = {"/experiments/inplay": ("In-play research", view)}
INPLAY_DEMO_PAGES = {"/gallery/inplay": ("In-play states", gallery)}
