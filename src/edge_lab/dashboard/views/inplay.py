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
# A populated view is labelled by where its evidence came from (the mode), never a fixed word.
POPULATED_WORDS = {"FIXTURE": "Fixture evidence", "SYNTHETIC_REPLAY": "Synthetic evidence",
                   "RECORDED": "Recorded evidence"}
STATE_WORDS = {  # (label, kind): nothing is green; a populated view is information, not success
    "POPULATED": ("Evidence of unknown origin", "warn"), "EMPTY": ("No evidence in journal", "nd"),
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
# source-state-v1 (ADR 0041) words: nothing is green; a valid decision is information, not success
VALIDITY_WORDS = {"VALID": ("Valid at replay clock", "info"),
                  "INVALIDATED": ("Invalidated · recompute", "warn"),
                  "REVIEW_REQUIRED": ("Review required", "warn")}
FRESHNESS_WORDS = {"fresh": ("Fresh by publication time", "info"), "stale": ("Stale — not actionable", "warn"),
                   "unknown": ("Unknown age: source clock bound unknown", "nd")}
KNOWLEDGE_WORDS = {"KNOWN": ("Declared by the source", "info"),
                   "UNKNOWN": ("Unknown: not declared by the source", "nd")}
EVIDENCE_WORDS = {"ACTUAL": ("Actual", "info"), "SIMULATED": ("Simulated · not actual", "warn"),
                  "HYPOTHETICAL": ("Hypothetical · never sent", "warn"),
                  "UNAVAILABLE": ("Unavailable to us", "nd")}
DATA_KIND_WORDS = {"FIXTURE": ("Fixture input", "warn"), "SYNTHETIC": ("Synthetic input", "warn"),
                   "RECORDED": ("Recorded input", "info")}
# Phase enum values in plain words: this page never prints the word for a live feed (none is authorized)
PHASE_WORDS = {"PREGAME": "pregame", "LIVE": "in game", "BREAK": "break", "POSTGAME": "postgame",
               "UNKNOWN": "unknown"}
MISSING_WORDS = {"FEE_SCOPE_UNKNOWN": "fees unknown: net blocked",
                 "RESIDUAL_INVENTORY": "open inventory: total not known",
                 "SUBSIDY_MASKS_LOSS": "rebates hide an unsubsidized loss"}


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


def state_words(mode: Any) -> dict[str, tuple[str, str]]:
    """STATE_WORDS with the populated label taken from the mode (fixture, synthetic replay, recorded)."""
    words = dict(STATE_WORDS)
    if mode in POPULATED_WORDS:
        words["POPULATED"] = (POPULATED_WORDS[mode], "info")
    return words


def header(view: dict[str, Any]) -> str:
    mode, state = view.get("mode"), view.get("state")
    words = state_words(mode)
    capsules = (_badge({k: (v, "warn") for k, v in MODE_LABELS.items()}, mode, "INPLAY_MODE") + " "
                + _badge(words, state, "INPLAY_STATE"))
    label, kind = words.get(state, ("Unknown state", "warn"))
    kind = {"info": "info", "warn": "warn", "err": "err"}.get(kind, "nd")
    top = f'<p class="meta">{esc(view.get("label") or "")}</p><p>{capsules}</p>'
    if state in ("ERROR", "NOT_AUTHORIZED"):  # the error or blocked state below carries the detail once
        return top
    as_of = view.get("as_of_utc")
    clock = (f"Replay clock {pr.datetime_et(as_of)} (the fixture's time, not now)." if as_of else
             "No replay clock: nothing was replayed.")
    return top + c.status_line(kind, label, f"{view.get('detail') or ''} {clock}".strip())


CAVEAT_PREFIXES = ("FEE_UNKNOWN",)  # caveats on a proposal's figures, not the reason for the proposal


def primary_reason(reasons: list[str]) -> str | None:
    """The reason the decision was taken: the first reason that is not a figure caveat (FEE_UNKNOWN),
    so an EXIT reads TARGET_REACHED and a block reads its blocking reason. A caveat is shown only when
    it is the only reason. A game-state reason shows its codes only (STATE_INVALIDATED:
    MATERIAL_STATE_CHANGE); its observation ids and times stay in Policy details with every reason."""
    decisive = [r for r in reasons if not r.startswith(CAVEAT_PREFIXES)]
    first = (decisive or reasons or [None])[0]
    return reason_codes(first) if first and first.startswith("STATE_") else first


def reason_codes(reason: str | None) -> str | None:
    """`CODE: SUBCODE: detail` as `CODE: SUBCODE` (the detail is shown in a disclosure)."""
    if reason is None:
        return None
    return ": ".join(reason.split(": ")[:2])


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
        ("Primary reason", c.txt(primary_reason(reasons), reason="no reason recorded")),
        ("Other reasons", c.txt(f"{len(reasons) - 1} more in Policy details" if len(reasons) > 1 else "none",
                                reason="none")),
    ], text_cols=(4, 5, 6))
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
    scope = comp.get("scope_note") or "A separate replay cohort, not this contract."
    # the scope is body text (section meta is hidden on phones), read before any arm; a padded section
    # body keeps it aligned, and its rows still run edge to edge
    note = f'<p class="note">{esc(scope)}</p>'
    meta = "Identical entries in every arm · not evidence of an edge"
    return c.section("Hold versus exit", note + '<ul class="rows">' + "".join(rows) + "</ul>" + details,
                     meta=meta, sid="ip-cmp")


def source_state_section(view: dict[str, Any]) -> str:
    """Source, state and clock validity (inplay_evidence source-state-v1): compact facts, details disclosed."""
    ss = view.get("source_state")
    if not ss:
        return c.section("Source and state validity", c.unavailable(
            "Not evaluated", "No game-state journal accompanies this view, so no decision was checked against the "
            "game state."), sid="ip-ss")
    dec_ = ss.get("decision") or {}
    reasons = dec_.get("reasons") or []
    facts = c.facts([
        ("Evidence", _word(EVIDENCE_WORDS, ss.get("evidence_status"), "EVIDENCE") + " "
         + _word(DATA_KIND_WORDS, ss.get("data_kind"), "DATA_KIND")),
        ("Source", c.txt(ss.get("source_id"), reason="no book received")),
        ("Source family", c.txt(ss.get("source_family"), reason="UNKNOWN")),
        ("Content age", _word(FRESHNESS_WORDS, ss.get("content_freshness"), "CONTENT_FRESHNESS")
         if ss.get("content_freshness") else c.na("no book received")),
        ("Game state in the quote", _word(KNOWLEDGE_WORDS, ss.get("incorporated_state"), "INCORPORATED")
         if ss.get("incorporated_state") else c.na("no book received")),
        ("Decision validity", _word(VALIDITY_WORDS, dec_.get("status"), "VALIDITY")),
        ("Reason", c.txt(reason_codes(reasons[0]).split(": ")[0] if reasons else "no later material state"
                         if dec_.get("status") == "VALID" else None, reason="none recorded")),
    ], text_cols=(1, 2, 6))
    lat = c.table(["stage", "seconds", "± seconds", "method"],
                  [[esc(x.get("stage")), c.num(x.get("seconds"), reason="not measured"),
                    c.num(x.get("uncertainty_seconds"), reason="unknown bound" if x.get("measured") else "not measured"),
                    c.txt(x.get("method"), reason="not measured")] for x in ss.get("latency") or []],
                  wrap=(3,), caption="Latency stages (unmeasured is not zero)", empty="no book received")
    ctx_ = ss.get("context") or {}
    detail = c.disclosure("Clocks, context and decision", c.kv([
        ("received (our clock)", c.txt(pr.datetime_et(ss.get("received_utc")), reason="none")
         + (" " + esc(f"± {ss.get('received_uncertainty_seconds')} s") if ss.get("received_uncertainty_seconds")
            else "")),
        ("published (venue clock)", c.txt(pr.datetime_et(ss.get("published_utc")), reason="not sent")
         + (" " + esc(f"bound {ss.get('published_uncertainty')}") if ss.get("published_uncertainty") else "")),
        ("sport · market · phase · regime", esc(" · ".join(
            PHASE_WORDS.get(ctx_.get(k), "unknown") if k == "phase" else str(ctx_.get(k) or "unknown")
            for k in ("sport", "market", "phase", "regime")))),
        ("decision as of", c.txt(pr.datetime_et(dec_.get("as_of_utc")), reason="none")),
        ("state version", c.code(dec_.get("state_version"))),
        ("checked at", c.txt(pr.datetime_et(dec_.get("checked_at_utc")), reason="none")),
        ("superseded by", c.ul(dec_.get("superseded_by") or [], empty="none")),
        ("all reasons", c.ul(reasons, empty="none")),
        ("contract", c.code(ss.get("contract_version"))),
    ]) + lat + f'<p class="note">{esc(ss.get("note") or "")} {esc(ss.get("game_clock_note") or "")}</p>')
    return c.section("Source and state validity", facts + detail,
                     meta="A recommendation on an old game state is recomputed, never sent", sid="ip-ss")


def economics_section(view: dict[str, Any]) -> str:
    """Fill-conditioned economics from the synthetic replay's simulated fills, per execution mode."""
    fe = view.get("fill_economics")
    if not fe or fe.get("state") == "NOT_EVALUATED":
        return c.section("Fill-conditioned economics", c.unavailable(
            "Not evaluated", (fe or {}).get("detail") or "No replay, so no simulated fills."), sid="ip-econ")
    rows = []
    for r in fe.get("rows") or []:
        if r.get("state") == "ERROR":
            rows.append(c.row(esc(r.get("arm")), aside=c.state_text("ECON_ERROR", label="Refused", kind="err"),
                              body=c.error_state("Economics refused", r.get("detail") or "")))
            continue
        missing = [MISSING_WORDS.get(m, m) for m in r.get("missing") or []]
        facts = c.facts([
            ("Mode", c.txt(" + ".join(m.replace("_", " ").lower() for m in r.get("modes") or []) or None,
                           reason="no fill")),
            ("Evidence", _word(EVIDENCE_WORDS, r.get("evidence"), "EVIDENCE")),
            ("Simulated fills", c.num(pr.count(r.get("fills")), reason="none")),
            ("Gross (simulated)", _money(r.get("gross"), "open inventory: not known", signed=True)),
            ("Net (simulated)", _money(r.get("net"), FEE_UNKNOWN, signed=True)),
            ("Peak collateral", _money(r.get("peak_collateral"), "not evaluated")),
            ("Return on deployed", c.num(pr.percent(r.get("return_on_deployed")), reason="net unknown")),
            ("Turnover of total capital", c.num(pr.ratio(r.get("turnover")), reason="no capital")),
        ], text_cols=(0, 1))
        aside = c.state_text("ECON_MISSING", label=f"{len(missing)} missing" if missing else "All figures known",
                             kind="warn" if missing else "nd")
        rows.append(c.row(esc(r.get("arm")), sub="; ".join(missing) or "every denominator known",
                          aside=aside, body=facts))
    detail = c.disclosure("Economics details", c.kv(
        [(str(r.get("arm")), c.ul(r.get("reasons") or [], empty="none")) for r in fe.get("rows") or []]
        + [("capital-days · notional", c.ul([f"{r.get('arm')}: {r.get('capital_days')} capital-days, notional "
                                             f"{r.get('notional')}" for r in fe.get("rows") or []
                                             if r.get("state") == "POPULATED"]))]))
    note = f'<p class="note">{esc(fe.get("detail") or "")} {esc(fe.get("rfq") or "")}</p>'
    return c.section("Fill-conditioned economics", note + '<ul class="rows">' + "".join(rows) + "</ul>" + detail,
                     meta="Simulated fills only · taker and maker kept apart · not an edge", sid="ip-econ")


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
    parts += [position_section(view), source_state_section(view), policy_section(view), comparison_section(view),
              economics_section(view), authority_section(view)]
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
