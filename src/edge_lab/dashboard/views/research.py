"""Research & Data (/experiments): two read-only tabs. docs/design/UI_CONTRACT.md §17."""

from __future__ import annotations

import re

from ... import sources, venues
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from .terminal import receipt_detail

_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)\b")


def looks(plan: str | None) -> list[int]:
    """The preregistered valid-day looks named in the manifest's Stage B plan (e.g. 180th, 365th)."""
    return sorted({int(n) for n in _ORDINAL.findall(plan or "")})


def progress_bar(done: int, target: int, label: str) -> str:
    if target <= 0:
        return ""
    frac = min(done / target, 1)
    return (f'<svg class="progress-svg" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="{esc(label)}">'
            f'<rect class="bar-track" x="0" y="0" width="100" height="8" rx="4"></rect>'
            f'<rect class="bar-fill limit" x="0" y="0" width="{frac * 100:.2f}" height="8" rx="4"></rect></svg>')


def research_tab(ctx: d.Context) -> str:
    exps = ctx.experiments
    out = []
    if ctx.config.demo:
        out.append(c.status_line("warn", "Demo mode", "The experiment registry below is read from the repository (real "
                                 "manifests). Source health, fees-in-receipt and the receipt are synthetic."))
    missing = cm.loaded_state("Experiment registry", exps)
    if missing:
        return "".join(out) + c.section("Experiments", missing, sid="ex-h")
    valid_days = None
    if ctx.collector_status.status == d.OK:
        valid_days = ctx.collector_status.value.get("valid_days")
    elif ctx.collector_db.status == d.OK:
        valid_days = ctx.collector_db.value.get("valid_days")
    cards = []
    for e in exps.value:
        stage = e["stage_a"]
        plan_looks = looks(e.get("stage_b_plan"))
        nxt = next((n for n in plan_looks if not isinstance(valid_days, int) or n > valid_days), None)
        facts = [
            ("Research stage", c.badge(e["status"]) if e["status"] else c.na("no status")),
            ("Historical result", (c.badge(stage.get("verdict")) if stage and stage.get("verdict") else
                                   c.na("no historical result recorded"))),
            ("Forward valid days", c.num(pr.count(valid_days), reason="no collector status") if e["id"] == "EXP-001"
             else c.na("not tracked here")),
            ("Next preregistered look", c.num(f"{nxt}th valid day" if nxt else None, reason="no look in the plan")),
        ]
        bar = ""
        if e["id"] == "EXP-001" and isinstance(valid_days, int) and nxt:
            bar = (f'<p class="meta">Observations toward the next scheduled evaluation: {esc(valid_days)} of '
                   f"{esc(nxt)} valid forward days. Historical test days do not count; this is not a countdown to "
                   "success.</p>" + progress_bar(valid_days, nxt, f"{valid_days} of {nxt} valid forward days"))
        limits = e.get("limitations") or []
        detail_pairs = [("manifest", c.code(e["key"])), ("manifest validation",
                        c.badge("VALID", label="Valid manifest") if not e["problems"] else c.ul(e["problems"])),
                        ("Stage B plan", esc(e.get("stage_b_plan"))),
                        ("gate reports in the repository (names only)", c.ul(e["reports"]))]
        if stage is not None:
            detail_pairs += [
                ("Stage A verdict", c.code(stage.get("verdict"))), ("phase", esc(stage.get("phase"))),
                ("test days", esc(stage.get("n_test_days"))),
                ("test window", f"{esc(stage.get('test_first'))} to {esc(stage.get('test_last'))}"),
                ("selected variant", esc(stage.get("selected_variant"))),
                ("conditions", c.ul(f"{k}: {'passed' if v else 'not passed' if v is not None else 'unknown'}"
                                    for k, v in (stage.get("conditions") or {}).items())),
                ("dataset sha256", c.code(stage.get("dataset_sha256"))),
            ] + ([("error", esc(stage["error"]))] if stage.get("error") else [])
        detail_pairs.append(("Stage B (live shadow)", esc("research evidence accrues only from VALID live days; see "
                                                          "Terminal")))
        body = (f'<p class="meta">{esc(e["id"])} · operational pipeline status is on the Terminal</p>'
                + c.facts(facts, text_cols=(0, 1)) + bar
                + ('<p class="note">A historical validation pass (Stage A) is a probability-validation result, not '
                   "a trading edge and not profitability.</p>" if stage else "")
                + (c.disclosure("Limitations", c.ul(limits)) if limits else "")
                + c.disclosure("Details", c.kv(detail_pairs)))
        cards.append(c.section(str(e["title"] or e["key"]), body, sid=f"ex-{esc(e['id'] or 'x')}-h"))
    registry = c.table(["id", "title", "status", "manifest validation"],
                       [[esc(e["id"]), esc(e["title"]), c.code(e["status"]),
                         esc("VALID MANIFEST") if not e["problems"] else esc("; ".join(e["problems"]))]
                        for e in exps.value], wrap=(1, 3), caption="Experiment registry")
    return "".join(out) + "".join(cards) + c.disclosure("Experiment registry (all manifests)", registry, boxed=True)


def _requirement(stage: str, cap: str, authorized: bool) -> str:
    if cap == "order_write":
        return "Execution not authorized"
    return {"LIVE_DATA_VERIFIED": "None for read-only data", "TESTED": "Scheduled live read not recorded",
            "NEEDS_ACCESS": "Owner credential or approval", "IMPLEMENTED": "Tests and a recorded read",
            "PLANNED": "Not built", "UNSUPPORTED": "Not offered or out of scope",
            "PARTIAL": "Partly verified", "STALE": "Re-verify"}.get(stage, "Unknown")


def sources_tab(ctx: d.Context) -> str:
    out = []
    rows = []
    for v in venues.VENUES.values():
        quote = v.stage(venues.Capability.QUOTE_READ).value
        by_stage: dict[str, list[str]] = {}
        for cap in venues.Capability:
            stage = v.stage(cap).value
            if stage not in ("UNSUPPORTED", "PLANNED"):
                by_stage.setdefault(pr.state_word(stage).label.lower(), []).append(cap.value.split("_")[0])
        caps = "; ".join(f"{', '.join(names)}: {label}" for label, names in by_stage.items())
        last = max((s.last_verified_utc for s in v.capabilities.values() if s.last_verified_utc), default=None)
        rows.append(c.row(esc(pr.venue_label(v.venue_id)),
                          sub=f"{v.kind.value.capitalize()} · {caps or 'no capability built'}",
                          body=c.facts([
                              ("Access stage (quotes)", c.badge(quote)),
                              ("Last verified read", c.txt(pr.datetime_et(last), reason="no recorded live read")),
                              ("Orders", c.badge("NOT_RECOMMENDED", label="Not authorized")),
                              ("Outstanding requirement", esc(_requirement(quote, "quote_read", v.execution_authorized))),
                          ], text_cols=(0, 2, 3))))
    out.append(c.section("Venues", '<ul class="rows">' + "".join(rows) + "</ul>"
                         + '<div class="pad"><p class="note">Tested is not connected. A single smoke read is '
                           "not a scheduled feed. Daily files are not real-time books. Public market reads do not "
                           "imply account or order access.</p></div>", sid="ven-h", flush=True))
    health = ctx.source_health
    missing = cm.loaded_state("Collected sources", health)
    if missing:
        out.append(c.section("Collected sources", missing, sid="src-h"))
    else:
        items = []
        for h in health.value:
            fresh, _ = d.freshness(h.get("completed_at_utc"), ctx.now)
            try:
                spec = sources.get_source(h.get("source_id"))
                scope = spec.description
            except Exception:  # noqa: BLE001 - an unknown id is shown, never hidden
                scope = "not in the source registry"
            items.append(c.row(esc(h.get("source_id")), sub=scope, aside=c.badge(h.get("status")),
                               body=c.facts([
                                   ("Last run", c.txt(pr.datetime_et(h.get("completed_at_utc")), reason="not recorded")),
                                   ("Freshness (26 h)", c.badge(fresh, label=fresh)),
                                   ("Last successful observation", c.txt(pr.datetime_et(h.get("last_ok_at_utc")),
                                                                         reason="no successful run recorded")),
                                   ("Outstanding requirement", esc(h.get("error") or "None recorded")),
                               ], text_cols=(1, 3))))
        detail = c.table(["source", "status", "completed", "age", "freshness (26 h)", "last ok", "records",
                          "http errors", "retries", "error"],
                         [[esc(h.get("source_id")), c.code(h.get("status")), esc(h.get("completed_at_utc")),
                           esc(pr.age_text(h.get("completed_at_utc"), ctx.now)),
                           c.code(d.freshness(h.get("completed_at_utc"), ctx.now)[0]), esc(h.get("last_ok_at_utc")),
                           esc(h.get("records")), esc(h.get("http_errors")), esc(h.get("retries")), esc(h.get("error"))]
                          for h in health.value], wrap=(9,), caption="Source health")
        out.append(c.section("Collected sources", '<ul class="rows">' + "".join(items) + "</ul>"
                             + f'<div class="pad">{c.disclosure("Source health (latest per source)", detail)}</div>',
                             sid="src-h", flush=True))
    out.append(fees_section(ctx))
    venue_table = c.table(
        ["venue", "kind", "capability", "stage", "auth required", "execution authorized", "evidence"],
        [[esc(r["venue_id"]), esc(r["kind"]), esc(r["capability"]), c.code(r["stage"]), esc(r["auth_required"]),
          esc(r["execution_authorized"]), esc(r["evidence"])] for r in d.venue_rows()], wrap=(6,),
        caption="Venue capability registry")
    out.append(c.disclosure("Venue capability registry", '<p class="note">' + esc(
        "What each venue's documented interface could do, and what this repository has shown with evidence. "
        "Code existing is not a connection; only LIVE_DATA_VERIFIED rows rest on recorded reads. Execution is "
        "not authorized for any venue.") + "</p>" + venue_table, boxed=True))
    out.append(c.disclosure("Pipeline receipt (full)", receipt_detail(ctx, days=True), boxed=True))
    return "".join(out)


def fees_section(ctx: d.Context) -> str:
    fees = d.fee_rows(ctx.now)
    active = next((f for f in fees if f["active"]), None)
    summary = (c.facts([("Active schedule", c.code(active["schedule_id"])),
                        ("Verification", c.badge(active["status"])),
                        ("Claim basis", c.badge(active["claim_basis"])),
                        ("Re-check by", c.txt(pr.datetime_et(active["recheck_by_utc"]), reason="no re-check date"))],
                       text_cols=(0, 1, 2)) if active else c.unavailable("No active fee schedule", ""))
    rows = [[esc(f["schedule_id"]) + (" " + c.badge("ACTIVE", label="ACTIVE", kind="nd") if f["active"] else ""),
             esc(f["venue"]), c.code(f["status"]), c.code(f["claim_basis"]), esc(f["checked_at_utc"]),
             esc(f["recheck_by_utc"]), esc(f["detail"]), esc(f["evidence"])] for f in fees]
    body = ('<p class="note">Current view: the verification known now. Each decision carries the basis known '
            'when it was made; nothing earlier is restated.</p>'
            + c.table(["schedule", "venue", "verification", "claim basis", "verified at", "re-check by", "detail",
                       "evidence"], rows, wrap=(6, 7), caption="Fee schedules"))
    for f in fees:
        if f["components"]:
            body += (f'<h4 class="eyebrow">Components of {esc(f["verification_id"])}</h4>' + c.table(
                ["component", "state", "detail", "evidence"],
                [[esc(x["component"]), c.code(x["state"]), esc(x["detail"]), esc(x["evidence"])]
                 for x in f["components"]], wrap=(2, 3)))
    if ctx.receipt.status == d.OK and isinstance(ctx.receipt.value.get("fee"), dict):
        fee = ctx.receipt.value["fee"]
        body += '<h4 class="eyebrow">As reported by the latest pipeline receipt</h4>' + c.kv([
            ("schedule", esc(fee.get("schedule_id"))), ("status", c.code(fee.get("status"))),
            ("claim basis", c.code(fee.get("claim_basis"))),
            ("claim allowed (lower bound only)", esc(fee.get("claimable"))),
            ("allowance per contract", esc(fee.get("claim_allowance_per_contract")))])
    return c.section("Fee schedule verification", summary + c.disclosure("Fee verification details", body), sid="fee-h")


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    items = [("/experiments", "Research", p.tab == "research", None),
             ("/experiments?tab=sources", "Data sources", p.tab == "sources", None)]
    head = c.page_head("Research & Data", "Experiments, evidence sources and fee verification · read-only")
    body = head + c.tabs(items, label="Research and data") + '<div class="stack">' + (
        research_tab(ctx) if p.tab == "research" else sources_tab(ctx)) + "</div>"
    return cm.Page("Research & Data", "research", body)
