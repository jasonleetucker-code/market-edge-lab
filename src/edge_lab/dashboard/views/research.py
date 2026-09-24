"""Research & Data (/experiments): two read-only tabs. docs/design/UI_CONTRACT.md §17."""

from __future__ import annotations

import re
from typing import Any

from ... import sources, venues
from ...freshness import parse_utc
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


def odds_body(result: d.Loaded) -> str:
    """Every state of the Odds API card; OK carries `odds_pilot.dashboard_status`."""
    if result.status == d.OK:
        return c.odds_status_card(result.value)
    if result.status == d.ERROR:
        return c.error_state("The Odds API — status unavailable", f"ERROR — {result.message}. This is not a "
                                                                  "healthy or empty feed.")
    return c.unavailable("The Odds API — status unavailable", result.message[:1].upper() + result.message[1:] + ".")


def odds_section(ctx: d.Context) -> str:
    return c.section("The Odds API (NFL pilot)", odds_body(ctx.odds_status),
                     meta="Offered odds · research only · not executable", sid="odds-h", flush=True)


# --------------------------------------------------------------------------- Odds capture targets (ADR 0029)

# dashboard_status states in which the runner makes no paid capture (each state's own detail says why).
# SETUP_NEEDED is left out: before the first live read it does not stop captures, and telling it apart
# from a removed key would re-derive odds_pilot policy here (a canonical "paused" flag belongs there).
ODDS_PAUSED = ("COST_BLOCKED", "KEY_REJECTED", "QUOTA_EXHAUSTED", "QUOTA_UNKNOWN", "DISCOVERY_STALE")
TARGETS_NOTE = ("Offered odds are research data, never executable prices. Credits are the provider's reported cost "
                "of the paid call (x-requests-last); one call can serve several targets, so credits are never added "
                "up per target here. A capture is historical evidence, not current odds: its freshness is judged at "
                "receipt (the offers' last update against the source's odds max age). Books in the full list are "
                "the runner's record at capture; the rows above parse the stored response.")


def _sub(text: str | None) -> str:
    return f'<span class="cell-sub">{esc(text)}</span>' if text else ""


def _minutes(delta: Any) -> str | None:
    return f"{int(delta.total_seconds() // 60)} min" if delta is not None else None


def target_credits(t: d.OddsTarget) -> str:
    if t.credits_last is None:
        return c.na({"CAPTURED": "not recorded for this capture",
                     "FAILED": "not recorded (a failed call may still have been charged; see the reason)"}
                    .get(t.state, "no paid call recorded for this target"))
    return c.num(pr.count(t.credits_last), reason="not recorded") + _sub(_shared(t, "one paid call"))


def _shared(t: d.OddsTarget, alone: str | None) -> str | None:
    if t.shared_targets and t.shared_targets > 1:
        return f"one paid call shared by {t.shared_targets} targets"
    return alone


def target_books(t: d.OddsTarget) -> str:
    if t.state != "CAPTURED":
        return c.na("nothing captured for this target")
    if t.books is None:
        return c.na(t.books_note or "unknown")
    return c.num(pr.count(len(t.books))) + _sub(" · ".join(x for x in (
        f"{pr.count(t.offers)} offers" if t.offers is not None else None,
        "recorded at capture" if t.books_source == d.BOOKS_RECORDED else None, t.books_note) if x))


def _at_receipt(t: d.OddsTarget) -> str:
    """A captured row's freshness at receipt, in the existing state words ("Fresh at receipt")."""
    if t.freshness == d.NOT_EVALUATED:
        return c.na("freshness at receipt is evaluated for the rows shown above")
    return c.state_text(t.freshness, label=f"{pr.state_word(t.freshness).label} at receipt")


def target_freshness(t: d.OddsTarget, now: Any, max_age: Any) -> str:
    if t.state == "CAPTURED":
        age = pr.age_text(t.captured_at_utc, now)
        limit = _minutes(max_age)
        head = (c.na("freshness at receipt not evaluated") if t.freshness == d.NOT_EVALUATED else
                c.badge(t.freshness, label=f"{pr.state_word(t.freshness).label} at receipt"))
        return head + _sub(" · ".join(x for x in (
            f"received {age}" if age else None, "historical, not current",
            f"odds max age {limit}" if limit else None) if x))
    if t.freshness == d.TARGET_PENDING:
        due = pr.age_text(t.due_utc, now)
        return c.state_text(t.freshness) + _sub(f"due {due}" if due else None)
    if t.freshness == d.TARGET_OVERDUE:
        return c.badge(t.freshness) + _sub(f"no outcome recorded since the deadline, {pr.datetime_et(t.deadline_utc)}"
                                         if t.deadline_utc else "no outcome recorded")
    if t.freshness == d.TARGET_NO_CAPTURE:
        return c.state_text(t.freshness)
    return c.badge("UNKNOWN", label="Unknown")


def _receipt(t: d.OddsTarget) -> str:
    reason = {"CAPTURED": "receipt time not recorded", "MISSED": "missed: nothing received",
              "FAILED": "failed: nothing stored", "SUPERSEDED": "superseded before capture"}.get(t.state, "not captured")
    deviation = t.detail.get("deviation_minutes") if t.state == "CAPTURED" else None
    return c.txt(pr.datetime_et(t.captured_at_utc), reason=reason) + _sub(
        f"{deviation} min from intended (recorded)" if isinstance(deviation, (int, float)) else None)


def _intended(t: d.OddsTarget) -> str:
    moved = (t.due_utc is not None and parse_utc(t.due_utc) != parse_utc(t.target_utc))
    return c.txt(pr.datetime_et(t.target_utc), reason="not recorded") + _sub(
        f"due {pr.time_et(t.due_utc)} (outside the capture quiet window)" if moved else None)


def _transitions(t: d.OddsTarget) -> str:
    if t.transitions is None:
        return ""
    return c.table(["state", "at", "reason", "slot", "snapshot", "credits"],
                   [[c.badge_code(x.get("state")), esc(pr.datetime_et(x.get("at_utc")) or x.get("at_utc")),
                     esc(d.scrub_paths(x.get("reason"))), c.code(x.get("slot_id")), c.code(x.get("snapshot_id")),
                     esc(x.get("credits_last"))] for x in t.transitions], wrap=(2,), caption="State history")


def target_row(t: d.OddsTarget, now: Any, max_age: Any = None) -> str:
    """One capture target: event, horizon, intended time, receipt, state, credits, books, freshness."""
    facts = [("Intended (ET)", _intended(t)), ("Actual receipt", _receipt(t)), ("Credits", target_credits(t)),
             ("Books returned", target_books(t)), ("Freshness", target_freshness(t, now, max_age))]
    if t.reason:
        facts.append(("Reason", esc(t.reason)))
    detail = c.disclosure("Target details and history", c.kv([
        ("target id", c.code(t.target_id)), ("event id", c.code(t.event_id)), ("sport", c.code(t.sport)),
        ("horizon · priority", esc(f"{t.offset_label} · {t.priority}")),
        ("kickoff (UTC)", c.code(t.commence_utc)), ("intended (UTC)", c.code(t.target_utc)),
        ("effective due (UTC)", c.code(t.due_utc)), ("deadline (UTC)", c.code(t.deadline_utc)),
        ("planned at (UTC)", c.code(t.planned_at_utc)), ("policy", c.code(t.policy_version)),
        ("state", c.badge_code(t.state)), ("state recorded at (UTC)", c.code(t.state_at_utc)),
        ("slot", c.code(t.slot_id)), ("snapshot", c.code(t.snapshot_id)),
        ("received (UTC)", c.code(t.captured_at_utc)), ("credits (x-requests-last)", c.code(t.credits_last)),
        ("books in the stored response", c.ul(t.books, empty="none") if t.books is not None
         else c.na(t.books_note or "not captured")),
        ("recorded at capture", esc(c._json_text(t.detail)) if t.detail else c.na("nothing recorded")),
    ]) + _transitions(t))
    sub = f"{t.offset_label} · kickoff {pr.datetime_et(t.commence_utc) or 'not recorded'}"
    return c.row(esc(pr.odds_event_label(t.away_team, t.home_team, t.event_id)), sub=sub, aside=c.badge(t.state),
                 body=c.facts(facts, wide=True, text_cols=(0, 1, 4, 5)) + detail)


def targets_table(targets: d.OddsTargets) -> str:
    rows = targets.rows[-d.ODDS_TARGETS_MAX:]
    left_out = len(targets.rows) - len(rows)
    table = c.table(
        ["event", "horizon", "intended (ET)", "actual receipt (ET)", "state", "credits", "books", "freshness"],
        [[esc(pr.odds_event_label(t.away_team, t.home_team, t.event_id)), esc(t.offset_label),
          esc(pr.datetime_et(t.target_utc)), c.txt(pr.datetime_et(t.captured_at_utc), reason="not captured"),
          c.state_text(t.state),
          c.num(pr.count(t.credits_last), reason="not recorded") + _sub(_shared(t, None)),
          c.num(pr.count(len(t.books)) if t.books is not None else None, reason=t.books_note or "not captured")
          + _sub("may be incomplete" if t.books is not None and t.books_note else None),
          _at_receipt(t) if t.state == "CAPTURED" else c.state_text(t.freshness)] for t in rows], wrap=(0,), right=(5, 6), caption="Odds capture targets")
    more = (f'<p class="note">{esc(pr.count(left_out))} older targets are not listed here; every target stays in '
            "the evidence database.</p>" if left_out > 0 else "")
    return table + more


def _paused(status: d.Loaded) -> str:
    if status.status != d.OK:
        return ""  # the card above shows the unreadable status; the targets below are still read
    state = pr.odds_state(status.value)
    if state not in ODDS_PAUSED:
        return ""
    detail = str((status.value or {}).get("detail") or "").rstrip(".")
    return c.blocked_state(f"Paid captures paused — {pr.state_word(state).label}",
                           (f"{detail[:1].upper()}{detail[1:]}. " if detail else "")
                           + "Open targets are not captured while this holds.")


def odds_targets_body(result: d.Loaded, status: d.Loaded, now: Any) -> str:
    """Every state of the capture-target table: source unavailable, read error, no targets, no
    captures yet, captures paused (quota or cost), overdue (stale records), missed, populated."""
    if result.status == d.ERROR:
        return c.error_state("Capture targets unavailable (read error)",
                             f"ERROR — {result.message}. This is not an empty schedule.")
    if result.status != d.OK:
        msg = result.message or "the evidence database is not available"
        return c.unavailable("Capture targets unavailable", f"Source unavailable — {msg}.")
    data: d.OddsTargets = result.value
    out = [_paused(status)]
    if not data.rows:
        out.append(c.empty_state("No capture targets planned yet", "Targets are planned from the quota-free schedule "
                                 "discovery, at fixed horizons before each kickoff. None is stored yet."))
        return "".join(out)
    labels = " · ".join(f"{pr.state_word(s).label} {pr.count(n)}" for s, n in sorted(
        data.by_state.items(), key=lambda kv: (-kv[1], kv[0])))
    out.append(c.facts([
        ("Targets", c.num(pr.count(len(data.rows)))),
        ("Captured", c.num(pr.count(data.count("CAPTURED")))),
        ("Missed", c.num(pr.count(data.count("MISSED")))),
        ("Failed", c.num(pr.count(data.count("FAILED")))),
        ("Open", c.num(pr.count(data.open_count))),
        ("Last recorded change", c.txt(pr.datetime_et(data.last_change_utc), reason="not recorded")
         + _sub(pr.age_text(data.last_change_utc, now))),
    ], wide=True, text_cols=(5,)) + f'<p class="meta">By state: {esc(labels)}</p>')
    if data.count("CAPTURED") == 0:
        first = next((t for t in data.rows if t.freshness == d.TARGET_PENDING), None)
        out.append(c.empty_state("No captures yet", f"{pr.count(len(data.rows))} targets are stored and none has been "
                                 "captured.", times=(f"Next target due {pr.datetime_et(first.due_utc)}"
                                                     if first is not None and first.due_utc else None)))
    overdue = sum(1 for t in data.rows if t.freshness == d.TARGET_OVERDUE)
    if overdue:
        out.append(c.empty_state(
            f"{pr.count(overdue)} open target{'' if overdue == 1 else 's'} past the deadline",
            "No outcome has been recorded since the deadline passed, so this record is stale. The runner records "
            "an expired target as Missed on its next run, or as Failed if a capture was left in progress. Whether "
            "its timer runs is not observable here.", kind="warn"))
    for title, group, none in (("Recent · intended time passed", data.recent, "No target's intended time has passed."),
                               ("Next", data.upcoming, "No target is ahead.")):
        out.append(f'<h3 class="eyebrow">{esc(title)}</h3>' + (
            '<ul class="rows">' + "".join(target_row(t, now, data.odds_max_age) for t in group) + "</ul>"
            if group else f'<p class="meta">{esc(none)}</p>'))
    out.append(c.disclosure(f"All targets ({pr.count(len(data.rows))})", targets_table(data), boxed=True))
    out.append(f'<p class="note">{esc(TARGETS_NOTE)}</p>')
    return "".join(x for x in out if x)


def odds_targets_section(ctx: d.Context) -> str:
    from ...odds_pilot import RunnerSettings

    settings = RunnerSettings()
    horizons = " / ".join(o.label for o in sorted(settings.config.offsets, key=lambda o: -o.before))
    return c.section("Odds capture targets", odds_targets_body(ctx.odds_targets, ctx.odds_status, ctx.now),
                     meta=f"{pr.sport_label(settings.sport)} · {horizons} before kickoff · research only",
                     sid="odds-t-h")


# --------------------------------------------------------------------------- Freshness Fabric (ADR 0031)

FRESHNESS_NOTE = ("The fabric observes; it runs, triggers and reschedules nothing. A source in external-schedule mode "
                  "is run by its own timer (named on each row) and only supervised here. Every figure is the "
                  "supervisor's, as of its evaluation; research use needs a receipt of known freshness, decision use "
                  "needs fresh data and healthy acquisition.")


def _fabric_badge(prefix: str, code: Any) -> str:
    word = pr.prefixed_word(prefix, code)
    return c.badge(code, label=word.label, kind=word.kind)


def _usable(src: Any) -> str:
    research, decision = src.get("usable_for_research") is True, src.get("usable_for_decision") is True
    if decision:
        return c.state_text("FRESH", label="Research and decision")
    if research:
        return c.state_text("STALE", label="Research only")
    return c.state_text("UNKNOWN", label="Not usable")


ATTENTION_SCHEDULE = ("MISSED", "PAUSED", "BUDGET_BLOCKED", "QUOTA_BLOCKED", "LOCK_BUSY")
ATTENTION_HEALTH = ("FAILING", "DEGRADED")


def needs_attention(src: Any) -> bool:
    """A source the owner should look at first, by the artifact's own states (a filter, not a verdict)."""
    return (src.get("schedule_state") in ATTENTION_SCHEDULE or src.get("health") in ATTENTION_HEALTH
            or bool(src.get("disagreements")))


def fabric_source_row(src: Any, policy: Any, now: Any) -> str:
    """One supervised source: freshness, schedule state, health, next due and why, usability; the
    policy and every recorded time in a disclosure. Values are the artifact's, only formatted."""
    src = src if isinstance(src, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    carried = src.get("carried_from_utc")
    age = pr.duration_text(src.get("data_age_s"))
    objective = pr.duration_text(src.get("max_useful_age_s"))
    facts = [
        ("Freshness", _fabric_badge("FRESHNESS", src.get("freshness")) + _sub(" · ".join(x for x in (
            f"data {age} old at evaluation" if age else "no receipt recorded",
            f"objective {objective}" if objective else "no objective") if x))),
        ("Schedule", _fabric_badge("SCHEDULE", src.get("schedule_state"))
         + _sub(f"as of {pr.datetime_et(carried)}" if carried else None)),
        ("Health", _fabric_badge("HEALTH", src.get("health"))),
        ("Next due", c.txt(pr.datetime_et(src.get("next_due_utc")), reason="nothing planned or not known")),
        ("Last successful receipt", c.txt(pr.datetime_et(src.get("last_success_receipt_utc")),
                                          reason="no successful receipt recorded")),
        ("Usable for", _usable(src)),
        ("Why", esc(src.get("why_due") or "not stated")),
    ]
    misses, disagreements = src.get("missed_count"), src.get("disagreements") or []
    if isinstance(misses, int) and not isinstance(misses, bool) and misses > 0:
        facts.append(("Missed", c.num(pr.count(misses), cls="neg") + _sub((src.get("details") or {}).get("missed_scope")
                                                                          if isinstance(src.get("details"), dict) else None)))
    if disagreements:
        facts.append(("Disagreements", c.state_text("WARNING", label=f"{pr.count(len(disagreements))} with the canonical "
                                                                      "scheduler")))
    details = src.get("details") if isinstance(src.get("details"), dict) else {}
    detail = c.disclosure("Source details and policy", c.kv([
        ("source id", c.code(src.get("source_id"))), ("description", esc(policy.get("description") or "not recorded")),
        ("acquisition mode", esc(pr.mode_label(src.get("mode"))) + " " + c.code(src.get("mode"))),
        ("underlying mode", c.code(src.get("underlying_mode"))), ("run by (schedule owner)", esc(src.get("schedule_owner"))),
        ("policy version", c.code(src.get("policy_version"))),
        ("objective (max useful age)", c.txt(pr.duration_text(src.get("max_useful_age_s")), reason="no objective")),
        ("slowest safe cadence", c.txt(pr.duration_text(policy.get("min_safe_cadence_s")), reason="not defined")),
        ("fastest useful cadence", c.txt(pr.duration_text(policy.get("max_useful_cadence_s")), reason="not defined")),
        ("pacing", esc(policy.get("pacing") or "not stated")), ("budget or quota", esc(policy.get("budget") or "not stated")),
        ("protected windows", c.ul(policy.get("protected_windows") or (), empty="none")),
        ("retry", esc(policy.get("retry") or "not stated")),
        ("intended at", c.code(src.get("intended_at_utc"))), ("next due", c.code(src.get("next_due_utc"))),
        ("last attempt", c.code(src.get("last_attempt_utc"))), ("receipt", c.code(src.get("receipt_ts_utc"))),
        ("upstream timestamp", c.code(src.get("upstream_ts_utc"))),
        ("upstream age at evaluation", c.txt(pr.duration_text(src.get("upstream_age_s")), reason="not recorded")),
        ("evaluated at", c.code(src.get("as_of_utc"))), ("carried from", c.code(carried)),
        ("recent misses", c.ul(src.get("recent_misses") or (), empty="none")),
        ("disagreements", c.ul(disagreements, empty="none")), ("notes", c.ul(src.get("notes") or (), empty="none")),
        ("details", esc(c._json_text(details)) if details else c.na("none recorded")),
    ]))
    sub = f"{src.get('domain') or 'domain not recorded'} · {pr.mode_label(src.get('mode'))}"
    if src.get("mode") == "EXTERNAL_SCHEDULE":
        sub += f" · run by {src.get('schedule_owner') or 'an owner not recorded'}"
    return c.row(esc(src.get("source_id") or "unnamed source"), sub=sub,
                 aside=_fabric_badge("FRESHNESS", src.get("freshness")),
                 body=c.facts(facts, wide=True, text_cols=(0, 1, 2, 3, 4, 5, 6)) + detail)


def _supervisor_state(doc: Any, report: d.FreshnessReport, now: Any) -> str:
    sup = doc.get("supervisor") if isinstance(doc.get("supervisor"), dict) else {}
    out = []
    generated = doc.get("generated_at_utc")
    if report.report_freshness != "FRESH":
        out.append(c.empty_state(
            "Freshness report is stale" if report.report_freshness == "STALE" else "Freshness report time unknown",
            f"Generated {pr.datetime_et(generated) or 'at an unreadable time'}"
            + (f" ({pr.age_text(generated, now)})" if pr.age_text(generated, now) else "")
            + f"; the supervisor runs every 5 minutes and a report older than {pr.duration_text(report.max_age.total_seconds())} "
            "is stale. Every source below is as of that time, not now.", kind="warn"))
    state = sup.get("state")
    if state == "DEFERRED_PROTECTED_WINDOW":
        deferred = sup.get("deferred") if isinstance(sup.get("deferred"), dict) else {}
        evaluated = doc.get("sources_evaluated_at_utc")
        window = f"{pr.window_label(deferred.get('window'))} ({pr.datetime_et(deferred.get('from_utc')) or '?'} to " \
                 f"{pr.time_et(deferred.get('to_utc')) or '?'})"
        text = (f"Inside the {window} the supervisor opens no store. Sources are carried from the "
                f"{pr.datetime_et(evaluated)} evaluation and re-judged at {pr.datetime_et(generated)} from their receipt "
                "times; schedule states are as of that evaluation; none is decision-grade."
                if evaluated else f"Inside the {window} the supervisor opens no store, and no recent evaluation could be "
                                  "carried: every source is unknown until the window closes.")
        out.append(c.empty_state("Supervisor deferred: protected window", text, kind="warn"))
    elif state not in (None, "OK"):
        problems = [str(x) for x in sup.get("problems") or []]
        out.append(c.empty_state(pr.prefixed_word("SUPERVISOR", state).label,
                                 "; ".join(problems) or "a provider reported a problem", kind="warn"))
    return "".join(out)


def freshness_body(result: d.Loaded, now: Any) -> str:
    """Every state of the freshness view: populated, stale report, deferred (carried or not), partial,
    no sources, not written yet / not configured (source unavailable), read error or foreign schema."""
    if result.status == d.ERROR:
        return c.error_state("Source freshness unavailable (read error)",
                             f"ERROR — {result.message}. This is not a healthy or empty report.")
    if result.status != d.OK:
        msg = result.message or "the status directory is not configured"
        return c.unavailable("Source freshness unavailable", msg[:1].upper() + msg[1:] + ".")
    report: d.FreshnessReport = result.value
    doc = report.doc
    sources = [s for s in doc.get("sources") or [] if isinstance(s, dict)]
    policies = {p.get("source_id"): p for p in doc.get("policies") or [] if isinstance(p, dict)}
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    sup = doc.get("supervisor") if isinstance(doc.get("supervisor"), dict) else {}
    out = [_supervisor_state(doc, report, now)]
    if not sources:
        out.append(c.empty_state("No sources in the report", "The supervisor's report lists no source."))
        return "".join(out)
    by_fresh = summary.get("by_freshness") if isinstance(summary.get("by_freshness"), dict) else {}
    external = sum(1 for s in sources if s.get("mode") == "EXTERNAL_SCHEDULE")
    generated = doc.get("generated_at_utc")
    out.append(c.facts([
        ("Report generated", c.txt(pr.datetime_et(generated), reason="not recorded")
         + _sub(pr.age_text(generated, now))),
        ("Sources evaluated", c.txt(pr.datetime_et(doc.get("sources_evaluated_at_utc")), reason="nothing evaluated")),
        ("Fresh", c.num(f"{pr.count(by_fresh.get('FRESH', 0))} of {pr.count(len(sources))}")),
        ("Due now", c.num(pr.count(len(summary.get("due_now") or [])))),
        ("Missed", c.num(pr.count(len(summary.get("missed") or [])))),
        ("Blocked", c.num(pr.count(len(summary.get("blocked") or [])))),
        ("Schedule unknown", c.num(pr.count(len(summary.get("unknown") or [])))),
    ], wide=True, text_cols=(0, 1)))
    out.append(f'<p class="meta">{esc(pr.count(external))} of {esc(pr.count(len(sources)))} sources are external '
               f"schedules the fabric only supervises · network: {esc(sup.get('network') or 'not recorded')} · controls "
               f"schedules: {'no' if sup.get('controls_schedules') is False else 'not recorded'}</p>")
    upcoming = [n for n in summary.get("next_due") or [] if isinstance(n, dict)]
    if upcoming:
        out.append('<h3 class="eyebrow">Due next</h3>' + c.ul(
            f"{pr.datetime_et(n.get('next_due_utc')) or 'time not recorded'} · {n.get('source_id')}: {n.get('why')}"
            for n in upcoming))
    attention = [s for s in sources if needs_attention(s)]
    out.append('<h3 class="eyebrow">Needs attention</h3>' + (
        '<ul class="rows">' + "".join(fabric_source_row(s, policies.get(s.get("source_id")), now) for s in attention)
        + "</ul>" if attention else '<p class="meta">No source is missed, blocked, failing, degraded or disagreeing '
                                    "with its scheduler.</p>"))
    domains: dict[str, list] = {}
    for s in sources:
        domains.setdefault(str(s.get("domain") or "other"), []).append(s)
    every = "".join(f'<h4 class="eyebrow">{esc(domain)}</h4><ul class="rows">'
                    + "".join(fabric_source_row(s, policies.get(s.get("source_id")), now) for s in rows) + "</ul>"
                    for domain, rows in domains.items())
    out.append(c.disclosure(f"Every source by domain ({pr.count(len(sources))})", every, boxed=True))
    problems = [str(x) for x in sup.get("problems") or []]
    out.append(c.disclosure("Supervisor details", c.kv([
        ("schema", c.code(doc.get("schema"))), ("fabric version", c.code(doc.get("fabric_version"))),
        ("supervisor state", c.state_text(sup.get("state"), label=pr.prefixed_word("SUPERVISOR", sup.get("state")).label,
                                           kind=pr.prefixed_word("SUPERVISOR", sup.get("state")).kind)
         + " " + c.code(sup.get("state"))), ("code version", c.code(sup.get("code_version"))),
        ("providers", c.ul(f"{x.get('provider')}: {x.get('state')}" for x in sup.get("providers") or []
                           if isinstance(x, dict))),
        ("problems", c.ul(problems, empty="none")), ("disagreements (all sources)", esc(summary.get("disagreements"))),
        ("generated at (UTC)", c.code(generated)), ("sources evaluated at (UTC)", c.code(doc.get("sources_evaluated_at_utc"))),
    ])))
    out.append(f'<p class="note">{esc(FRESHNESS_NOTE)}</p>')
    return "".join(x for x in out if x)


def freshness_section(ctx: d.Context) -> str:
    return c.section("Source freshness", freshness_body(ctx.freshness_status, ctx.now),
                     meta="What is fresh, what is due next, and why · Freshness Fabric", sid="fresh-h")


def sources_tab(ctx: d.Context) -> str:
    out = [freshness_section(ctx)]
    rows = []
    for v in venues.VENUES.values():
        quote = v.stage(venues.Capability.QUOTE_READ).value
        by_stage: dict[str, list[str]] = {}
        for cap in venues.Capability:
            stage = v.stage(cap).value
            if stage not in ("UNSUPPORTED", "PLANNED"):
                by_stage.setdefault(pr.state_word(stage).label.lower(), []).append(cap.value.split("_")[0])
        caps = "; ".join(f"{', '.join(names)}: {label}" for label, names in by_stage.items())
        last = v.capabilities[venues.Capability.QUOTE_READ].last_verified_utc  # the quote read itself
        rows.append(c.row(esc(pr.venue_label(v.venue_id)),
                          sub=f"{v.kind.value.capitalize()} · {caps or 'no capability built'}",
                          body=c.facts([
                              ("Access stage (quotes)", c.badge(quote)),
                              ("Last verified quote read", c.txt(pr.datetime_et(last), reason="no recorded live read")),
                              ("Orders", c.badge("NOT_RECOMMENDED", label="Not authorized")),
                              ("Outstanding requirement", esc(_requirement(quote, "quote_read", v.execution_authorized))),
                          ], text_cols=(0, 2, 3))))
    out.append(c.section("Venues", '<ul class="rows">' + "".join(rows) + "</ul>"
                         + '<div class="pad"><p class="note">Tested is not connected. A single smoke read is '
                           "not a scheduled feed. Daily files are not real-time books. Public market reads do not "
                           "imply account or order access.</p></div>", sid="ven-h", flush=True))
    out.append(odds_section(ctx))
    out.append(odds_targets_section(ctx))
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
                                   ("Last error", esc(h.get("error")) if h.get("error") else c.txt("none recorded")),
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
