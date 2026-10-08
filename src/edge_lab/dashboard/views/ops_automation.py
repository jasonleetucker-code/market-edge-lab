"""Automation (/risk/automation): Market v1 journey J6, read-only.

The controller's mode (DISARMED … BOUNDED_AUTO), the armed grant and its scope, the next action, the limits and
bounds, stop reasons (incidents, latches, refusals, disarms), the rearm procedure and the control log, all from the
execution status export (ADR 0043: no import of the execution package). Arm readiness is the exporter's own
`control.decide_arm` verdict per mode, judged without persisting anything; this page computes no rule. A TEST grant or
TEST limits are labelled as such and never as owner-set. There is no arm, disarm, acknowledge or approve control.
Lives under Risk (nav "risk"); no global navigation item is added.
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

PATH = "/risk/automation"
SERVICE_WORDS = {"NEVER_STARTED": ("Never started", "nd"), "SHUTDOWN_RECORDED": ("Shut down · disarmed", "nd"),
                 "STARTED_NO_SHUTDOWN_RECORDED": ("Started · no shutdown since", "nd")}
READINESS_WORDS = {"REFUSED": ("Would be refused", "warn"), "NO_CONTROL_BLOCKER": ("No control blocker", "info")}
REARM_STEPS = (
    "Every process start is DISARMED. Nothing arms itself.",
    "Read the stop reasons above. Clear the cause first: a failed or partial account read, a lost lease, a quarantined "
    "reservation, an exhausted request budget or a passed cycle deadline.",
    "Wait for a COMPLETE reconciliation: SHADOW and every sending mode need one.",
    "Arm with a request that names each open incident (or acknowledge each one first). An arm decided on an older "
    "state is refused as STALE_DECISION: decide again.",
    "BOUNDED_AUTO also needs a recorded, unexpired grant for this scope; it is re-checked on every order.",
    "A latch is removed only by clearing it. Reducing under a latch in an automated mode needs an explicit, expiring "
    "closeout authorization for that latch.",
    "Every order still passes the risk gate and the journal's reservation, whatever the mode.",
)


def _fixture_label(environment: Any) -> str:
    """Decided by the environment, never by a name: in FIXTURE every grant and limit is a fixture artifact."""
    return " · FIXTURE, not owner-set" if environment == "FIXTURE" else ""


def state_section(doc: dict) -> str:
    control = oc.g(doc, "control") or {}
    svc = oc.g(doc, "service") or {}
    cycle = oc.g(doc, "cycles", "last") or {}
    bounds = oc.g(doc, "bounds") or {}
    last_recon = control.get("last_reconciliation") or {}
    capsules = (oc.word(oc.MODE_WORDS, control.get("mode"), "XP_MODE", capsule=True) + " "
                + oc.word(oc.RECON_WORDS, control.get("reconciliation"), "XP_RECON", capsule=True) + " "
                + oc.env_badge(doc.get("environment")))
    used, limit = cycle.get("requests_used"), bounds.get("max_requests_per_cycle")
    body = f"<p>{capsules}</p>" + c.facts([
        ("Mode", c.txt(oc.MODE_WORDS.get(control.get("mode"), (control.get("mode"),))[0], reason=oc.UNKNOWN_REASON)),
        ("Reconciliation", c.txt(f"{control.get('reconciliation')} · {pr.datetime_et(last_recon.get('at_utc'))}"
                                 if last_recon else control.get("reconciliation"), reason=oc.UNKNOWN_REASON)),
        ("Service", oc.word(SERVICE_WORDS, svc.get("state"), "XP_SVC")),
        ("Last start", oc.when(control.get("last_started_at_utc"), "never started")),
        ("Last cycle", c.txt(None if not cycle else f"#{cycle.get('cycle')} · {pr.datetime_et(cycle.get('started_at_utc'))}"
                             f" · {cycle.get('mode_at_end')}", reason="no cycle recorded")),
        ("Requests in last cycle", c.num(None if used is None else f"{used} of {limit if limit is not None else '—'}",
                                         reason="no cycle recorded")),
    ], text_cols=(0, 1, 2, 3, 4))
    return c.section("Current state", body, meta=f"{doc.get('environment')} · from the control log", sid="xa-state")


def _grant_facts(s: dict) -> str:
    lim = s.get("limits") or {}
    return c.facts([
        ("Strategy", c.txt(f"{s.get('strategy_id')} {s.get('strategy_version')}")),
        ("Environment · scope", c.txt(f"{s.get('environment')} · {s.get('scope_key')}")),
        ("Universe", c.txt(", ".join(s.get("universe") or []) or None)),
        ("Kinds", c.txt(", ".join(s.get("allowed_kinds") or []) or None)),
        ("Max order cost", oc.money(lim.get("max_order_cost"))),
        ("Event exposure", oc.money(lim.get("max_event_exposure"))),
        ("Total exposure", oc.money(lim.get("max_total_exposure"))),
        ("Daily turnover", oc.money(lim.get("max_daily_turnover"))),
        ("Daily loss", oc.money(lim.get("max_daily_loss"))),
        ("Drawdown", oc.money(lim.get("max_drawdown"))),
        ("Valid", c.txt(f"{pr.datetime_et(s.get('issued_at_utc'))} – {pr.datetime_et(s.get('expires_at_utc'))}")),
        ("Issuer", c.txt(f"{s.get('issuer_ref')}{_fixture_label(s.get('environment'))}")),
    ], text_cols=(0, 1, 2, 3, 10, 11)) + c.disclosure("Grant identity", c.kv([
        ("Digest", c.code(s.get("digest"))), ("Model hash", c.code(s.get("model_hash"))),
        ("Policy hash", c.code(s.get("policy_hash"))), ("Risk policy", c.code(s.get("risk_policy_version"))),
        ("Fee schedule", c.code(s.get("fee_schedule_version"))), ("Profile", c.code(s.get("profile_version"))),
        ("Validity problems now", c.ul(s.get("validity_problems") or [], empty="none")),
    ]))


def grant_section(doc: dict) -> str:
    armed = oc.g(doc, "control", "armed_grant")
    configured = oc.lst(doc, "grants", "configured")
    if armed is None:
        body = c.empty_state("No grant armed", "BOUNDED_AUTO is not active, so no automation grant is in force.")
    elif armed.get("summary") is None:
        body = c.blocked_state("Armed against a grant this export cannot describe",
                               f"Grant {armed.get('digest')}: "
                               + ("the exporter had no configuration." if armed.get("found_in_config") is None
                                  else "it is not among the configured grants."))
    else:
        s = armed["summary"]
        body = (f'<p>{c.badge("XP_GRANT_ARMED", label="Armed grant" + _fixture_label(s.get("environment")), kind="info")}'
                f"</p>" + _grant_facts(s))
    if configured is None:
        body += '<p class="note">Configured grants: unknown (the exporter had no configuration).</p>'
    elif not configured:
        body += '<p class="note">No grant is configured. None is issued by the software; a grant is an owner decision.</p>'
    else:
        body += c.disclosure(f"Configured grants ({len(configured)})", "".join(
            c.section(f"{x.get('strategy_id')} · {x.get('issuer_ref')}", _grant_facts(x), level=3) for x in configured))
    return c.section("Active grant and scope", body, meta=oc.g(doc, "grants", "note"), sid="xa-grant")


def next_action(doc: dict) -> str:
    """What the operator would do next, from the export's own verdicts (open incidents, reconciliation, mode)."""
    control = oc.g(doc, "control") or {}
    incidents = oc.lst(control, "open_incidents")
    mode, recon = control.get("mode"), control.get("reconciliation")
    if incidents is None:
        title, text = "Stop reasons unknown", ("The export carries no readable incident list, so whether anything "
                                               "blocks arming is unknown.")
    elif incidents:
        names = ", ".join(str(i.get("incident_id")) for i in incidents)
        title, text = "Acknowledge the open incidents", (f"Name each open incident ({names}) in the arm request, or "
                                                         "acknowledge it, after its cause is cleared.")
    elif recon != "COMPLETE":
        title, text = "Wait for a complete reconciliation", (f"Reconciliation is {recon}. SHADOW and every sending "
                                                             "mode need a COMPLETE account read first.")
    elif mode == "DISARMED":
        title, text = "Nothing is armed", ("An operator arm request in the executor process would be judged now; "
                                           "the readiness below shows what control would refuse.")
    else:
        title, text = f"Armed in {mode}", ("No control action is pending. Every order still passes the risk gate "
                                           "and the journal's reservation.")
    readiness = oc.lst(control, "arm_readiness")
    table = c.unavailable("Arm readiness unknown", "The export carries no arm readiness.") if readiness is None else \
        c.table(["Mode", "Control verdict now", "Reasons"],
                [[esc(r.get("mode")), oc.word(READINESS_WORDS, r.get("verdict"), "XP_READY"),
                  c.ul(r.get("reasons") or [], empty="none")] for r in readiness],
                wrap=(2,), caption="Arm readiness per mode")
    body = (c.status_line("warn" if incidents is None or incidents or recon != "COMPLETE" else "info", title, text)
            + table
            + '<p class="note">Judged by the exporter with control.decide_arm and nothing acknowledged; nothing was '
              "persisted. The risk gate, the grant and the reservation still decide each order.</p>"
            + oc.no_control_note())
    return c.section("Next action", body, sid="xa-next")


def stops_section(doc: dict) -> str:
    control = oc.g(doc, "control") or {}
    incidents, latches = oc.lst(control, "open_incidents"), oc.lst(control, "latches")
    refusals, closeouts = oc.lst(control, "last_refusals") or [], oc.lst(control, "closeouts") or []
    rows = []
    for i in incidents or []:
        rows.append(c.row(esc(i.get("incident_id")), sub=f"Incident · raised {pr.datetime_et(i.get('raised_at_utc')) or 'at an unknown time'}",
                          aside=c.state_text("XP_INCIDENT", label="Open incident", kind="warn"),
                          body=f'<p class="note">{esc(i.get("reason") or "reason not recorded")}</p>'))
    for x in latches or []:
        rows.append(c.row(esc(f"{x.get('scope')}: {x.get('key')}"),
                          sub=f"New-risk latch · set {pr.datetime_et(x.get('set_at_utc')) or 'at an unknown time'}",
                          aside=c.state_text("XP_LATCH", label="Latched", kind="warn"),
                          body=f'<p class="note">{esc(x.get("reason") or "reason not recorded")}</p>'))
    if incidents is None or latches is None:
        body = c.unavailable("Stop reasons unknown", "The export carries no incident or latch list.")
    elif not rows:
        body = c.empty_state("No open incident or latch", "Nothing currently stops new risk at the controller.")
    else:
        body = '<ul class="rows">' + "".join(rows) + "</ul>"
    extra = []
    if refusals:
        extra.append(("Recent refused arm requests", c.table(
            ["When", "Mode", "By", "Reasons"],
            [[oc.when(r.get("at_utc")), esc(r.get("mode")), esc(r.get("operator_ref")), c.ul(r.get("reasons") or [])]
             for r in refusals], wrap=(3,), caption="Refused arm requests")
            + (f'<p class="note">{control.get("refusals_omitted")} older refusals are not in the export.</p>'
               if isinstance(control.get("refusals_omitted"), int) and control.get("refusals_omitted") > 0 else "")))
    disarm = control.get("last_disarm")
    if disarm:
        extra.append(("Last disarm", c.kv([("When", oc.when(disarm.get("at_utc"))), ("By", esc(disarm.get("operator_ref"))),
                                           ("Reason", esc(disarm.get("reason")))])))
    if closeouts:
        extra.append(("Closeout authorizations", c.table(
            ["Latch", "Expires"], [[esc(f"{x.get('scope')}: {x.get('key')}"), oc.when(x.get("expires_at_utc"))]
                                   for x in closeouts], caption="Closeout authorizations")))
    for title, html in extra:
        body += c.disclosure(title, html)
    return c.section("Stop reasons", body, meta="incidents, latches, refusals, disarms", sid="xa-stops")


def limits_section(doc: dict) -> str:
    limits, bounds = oc.g(doc, "limits"), oc.g(doc, "bounds")
    if limits is None:
        body = c.unavailable("Limits unknown here", "The exporter had no configuration, so the limits and bounds in "
                                                    "force are not recorded in this export.")
        return c.section("Limits and bounds", body, sid="xa-limits")
    policy, gate, ticket = limits.get("risk_policy") or {}, limits.get("gate_limits") or {}, \
        limits.get("ticket_limits") or {}
    ref = limits.get("owner_approval_ref")
    if limits.get("placeholder"):
        badge = c.badge("XP_LIMITS_PLACEHOLDER", label="Placeholder limits · refuse every order", kind="warn")
    elif ref is None:
        badge = c.badge("XP_LIMITS_NO_OWNER", label="No owner approval recorded · refuses every order", kind="warn")
    else:
        fixture = doc.get("environment") == "FIXTURE"
        badge = c.badge("XP_LIMITS_SET", label="FIXTURE limits · not owner-set" if fixture else
                        "Owner approval recorded", kind="warn" if fixture else "nd")
    body = f"<p>{badge}</p>" + f'<p class="note">Approval reference: {esc(ref or "none")}</p>' + c.facts([
        ("Reserve floor", oc.money(policy.get("reserve_floor"))),
        ("Position risk", oc.money(policy.get("max_position_risk"))),
        ("Event risk", oc.money(policy.get("max_event_risk"))),
        ("Cluster risk", oc.money(policy.get("max_cluster_risk"))),
        ("Portfolio risk", oc.money(policy.get("max_portfolio_risk"))),
        ("Daily loss", oc.money(policy.get("daily_loss_limit"))),
        ("Weekly loss", oc.money(policy.get("weekly_loss_limit"))),
        ("Drawdown", oc.money(policy.get("max_drawdown"))),
        ("Daily new risk", oc.money(gate.get("daily_new_risk"))),
        ("Strategy risk", oc.money(gate.get("max_strategy_risk"))),
        ("Quantity per order", oc.qty(gate.get("max_quantity_per_order"))),
        ("Orders per window", c.num(pr.count(ticket.get("max_orders_per_window")), reason=oc.UNKNOWN_REASON)),
    ])
    body += c.disclosure("Ages, windows and cycle bounds", c.kv([
        ("Risk policy", c.code(policy.get("policy_id"))), ("Gate limits", c.code(gate.get("limits_id"))),
        ("Max slippage", oc.money(gate.get("max_slippage"))),
        ("Decision age", oc.seconds(gate.get("max_decision_age_s"))),
        ("Source age", oc.seconds(gate.get("max_source_age_s"))),
        ("Book age", oc.seconds(ticket.get("max_book_age_s"))),
        ("Order window", oc.seconds(ticket.get("order_window_s"))),
        ("Market cooldown", oc.seconds(ticket.get("market_cooldown_s"))),
    ] + ([] if bounds is None else [
        ("Intents per cycle", c.num(pr.count(bounds.get("max_intents_per_cycle")))),
        ("Requests per cycle", c.num(pr.count(bounds.get("max_requests_per_cycle")))),
        ("Queued signals", c.num(pr.count(bounds.get("max_queued_signals")))),
        ("Cycle deadline", oc.seconds(bounds.get("cycle_deadline_s"))),
        ("Cycle interval", oc.seconds(bounds.get("cycle_interval_s"))),
        ("Snapshot age bound", oc.seconds(bounds.get("snapshot_max_age_s"))),
        ("Cash basis assumption", esc(bounds.get("fixture_cash_basis") or "none declared")),
    ])))
    return c.section("Limits and bounds", body, meta="as configured in the executor · never editable here",
                     sid="xa-limits")


def procedure_section() -> str:
    items = "".join(f"<li>{esc(s)}</li>" for s in REARM_STEPS)
    return c.section("Rearm procedure", f'<ol class="tight">{items}</ol>' + oc.no_control_note(), sid="xa-rearm")


def log_section(doc: dict) -> str:
    control = oc.g(doc, "control") or {}
    log = oc.lst(control, "log")
    omitted = control.get("log_omitted") or 0
    body = c.unavailable("Control log unknown", "The export carries no control log.") if log is None else \
        c.ul(log, empty="no control event recorded")
    note = f'<p class="note">{omitted} older lines are not in the export.</p>' if omitted else ""
    return c.disclosure(f"Control log ({control.get('events')} events)", body + note)


def automation_body(loaded: d.Loaded, now: datetime) -> str:
    missing, es = oc.export_state(loaded)
    if missing:
        return (c.section("Current state", missing, sid="xa-state") + procedure_section())
    doc = es.doc
    parts = [oc.export_status_line(es, now)]
    journal = oc.journal_state(doc)
    if journal:
        return "".join(parts) + c.section("Current state", journal, sid="xa-state") + procedure_section()
    paused = oc.paused_line(doc, link=False)
    if paused:
        parts.append(paused)
    parts += [state_section(doc), next_action(doc), stops_section(doc), grant_section(doc), limits_section(doc),
              procedure_section(), log_section(doc)]
    return "".join(parts)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head("Automation", "Controller mode, grant, limits and stop reasons · from the execution journal · "
                                     "read-only", crumb=oc.crumb("/risk", "Risk & capital"))
    body = automation_body(d.execution_status(ctx), ctx.now)
    return cm.Page("Automation", "risk", head + oc.journey_tabs(PATH) + '<div class="stack">' + body + "</div>")
