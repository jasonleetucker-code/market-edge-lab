"""Research & Data (/experiments): two read-only tabs. docs/design/UI_CONTRACT.md §17."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from ... import sources, venues
from ...freshness import parse_utc
from ...research_economics import FILL_MODE_SEMANTICS, FillMode
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
        return "".join(out) + c.section("Experiments", missing, sid="ex-h") + economics_section(ctx)
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
    return ("".join(out) + "".join(cards) + economics_section(ctx)
            + c.disclosure("Experiment registry (all manifests)", registry, boxed=True))


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


def _books_flag(t: d.OddsTarget) -> str | None:
    """A short history-table flag for a books note (the full note is on the row)."""
    note = t.books_note or ""
    if t.books is None:
        return None
    return " · ".join(x for x in ("event not in the response" if "not in the stored response" in note else None,
                                  "may be incomplete" if "parse problem" in note else None) if x) or None


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


# --------------------------------------------------------------------------- sportsbook consensus (ADR 0033)

CONSENSUS_LABEL = "RESEARCH BENCHMARK — NOT EXECUTABLE"  # odds_consensus.LABEL (tested equal)
CONSENSUS_NOTE = ("A consensus probability is the median, across books, of each book's de-vigged two-way probability "
                  "at one exact line: a research estimate, not a price anyone can trade at. Offered prices are "
                  "each book's quote as received; their implied probability still includes the book's margin. "
                  "Spreads and totals are never combined across lines.")
DISPERSION_TEXT = "range (max − min) and MAD (median absolute deviation, unscaled) of the books' de-vigged probabilities"


def _side(name: Any, line: Any, market: Any = None) -> str:
    """An outcome with its exact line as the contract normalized it; a spread's positive line gets "+"."""
    if line is None:
        return str(name)
    text = str(line)
    signed = market == "spreads" and text[:1] not in "+-" and text not in ("0", "0.0")
    return f"{name} +{text}" if signed else f"{name} {text}"


def _proposition(p: Any) -> str:
    """One proposition: its consensus table, then (separately) the offered prices and each book's de-vig."""
    title = f"{pr.odds_market_label(p.market_key)} · " + " / ".join(_side(n, ln, p.market_key) for n, ln in p.outcomes)
    status = p.status.value if hasattr(p.status, "value") else str(p.status)
    # The market-level last_update when any book gave one, else the bookmaker-level one (both are the contract's).
    bounds, basis = ((p.market_update, "market last_update") if p.market_update.known
                     else (p.bookmaker_update, "bookmaker last_update"))
    # One compact facts grid per outcome (readable at 360 px without scrolling), never a price in it.
    consensus = "".join(c.facts([
        ("Outcome", esc(_side(o.outcome_name, o.line, p.market_key))),
        ("Consensus probability", c.num(pr.percent(o.consensus_probability), reason="no consensus: fewer than two books")),
        ("Range · MAD", c.num(" · ".join(x or "—" for x in (pr.pp_size(o.range), pr.pp_size(o.mad)))
                              if o.range is not None or o.mad is not None else None, reason="not computed")),
        ("Books", c.num(pr.count(o.book_count)) + " <span>contributing</span>"
         + _sub(f"{pr.count(p.market_bookmaker_count)} quoting this market (any line)")),
    ], wide=True, text_cols=(0,)) for o in p.consensus)
    consensus = f'<div role="group" aria-label="{esc("Consensus probability, " + title)}">{consensus}</div>'
    head = c.facts([
        ("Status", c.state_text(f"CONSENSUS_{status}", label=pr.state_word(f"CONSENSUS_{status}").label
                                if f"CONSENSUS_{status}" in pr.STATES else None)),
        ("Freshness at receipt", c.badge(pr.freshness_code(p.freshness_at_receipt),
                                         label=f"{pr.state_word(pr.freshness_code(p.freshness_at_receipt)).label} "
                                               "(worst of books)")),
        ("Earliest contributing update", c.txt(pr.datetime_et(bounds.earliest_utc), reason="no usable update time")
         + _sub(basis)),
        ("Latest contributing update", c.txt(pr.datetime_et(bounds.latest_utc), reason="no usable update time")
         + _sub(f"{pr.count(bounds.unknown)} book(s) without one" if bounds.unknown else None)),
    ], wide=True, text_cols=(0, 1, 2, 3))
    offered = c.table(
        ["book", "outcome", "offered price (as received)", "implied incl. margin"],
        [[esc(o.bookmaker), esc(_side(o.outcome_name, o.line, p.market_key)), c.code(f"{o.raw_price} ({o.odds_format})"),
          c.num(pr.percent(o.implied_probability_with_margin), reason="not a valid quote")] for o in p.offered],
        wrap=(1,), right=(3,), caption=f"Offered prices, {title}")
    books = c.table(
        ["book", "de-vigged " + " / ".join(_side(n, ln, p.market_key) for n, ln in p.outcomes), "margin (overround)",
         "freshness at receipt", "update basis"],
        [[esc(b.bookmaker), c.num(" / ".join(pr.percent(x) or "—" for x in b.probabilities)),
          c.num(pr.pp(b.overround)), c.state_text(pr.freshness_code(b.freshness_at_receipt)),
          esc(b.update_basis or "none")] for b in p.books], right=(1, 2), caption=f"Each book's de-vig, {title}")
    return (f'<h4 class="eyebrow">{esc(title)}</h4>' + head
            + (f'<p class="note">{esc(p.reason)}</p>' if p.reason else "")
            + '<p class="meta">Consensus probability (research estimate, not a price)</p>' + consensus
            + c.disclosure(f"Offered prices as received ({pr.count(len(p.offered))}) and each book's de-vig",
                           '<p class="note">Offered prices are sportsbook quotes, not probabilities and not '
                           'executable.</p>' + offered + books))


def consensus_body(result: d.Loaded | None, capture_snapshot_id: Any = None) -> str:
    """Every state of one capture's consensus: populated, insufficient books, unsupported groups,
    stale / unknown freshness, this capture unusable (an earlier one shown), newer captures unusable,
    no consensus, not installed / unavailable, read error. Strings and figures are the contract's."""
    if result is None:
        return ""
    if result.status == d.ERROR:
        return c.error_state("Consensus unavailable (read error)",
                             f"ERROR — {result.message}. This is not an empty benchmark.")
    if result.status != d.OK:
        return c.unavailable("Consensus unavailable", result.message[:1].upper() + result.message[1:] + ".")
    r = result.value
    if r is None:
        if capture_snapshot_id is not None:  # the row names a stored capture, yet none is found: never calm
            return c.empty_state("No consensus found for this capture", f"This target records snapshot "
                                 f"{capture_snapshot_id}, but no stored odds response holding this event was found by "
                                 "its receipt time. The stored evidence is inconsistent; check the capture.",
                                 kind="warn")
        return c.empty_state("No consensus for this capture", "No stored odds response holding this event had been "
                                                             "received by this capture's time.")
    out = [f'<p class="eyebrow">{esc(r.label)}</p>']
    unusable = list(r.newer_unusable or ())
    if unusable:
        out.append(c.empty_state(
            f"{pr.count(len(unusable))} newer capture{'' if len(unusable) == 1 else 's'} of this event unusable",
            "; ".join(f"snapshot {u.snapshot_id} ({pr.datetime_et(u.received_at_utc) or 'receipt time unknown'}): "
                      + ", ".join(u.problems) for u in unusable), kind="warn"))
    event = r.events[0] if r.events else None
    if r.failed_closed or event is None:
        out.append(c.blocked_state("No usable consensus at this capture",
                                   f"Snapshot {r.snapshot_id}: " + ("; ".join(r.problems) or "no event in it") + "."))
        return "".join(out)
    if capture_snapshot_id is not None and r.snapshot_id != capture_snapshot_id:
        out.append(c.empty_state("This capture is not used", f"Its response gave this event no usable consensus; the "
                                 f"latest usable earlier capture is shown: snapshot {r.snapshot_id}, received "
                                 f"{pr.datetime_et(r.received_at_utc) or 'at an unknown time'}.", kind="warn"))
    fresh = pr.freshness_code(r.freshness_as_of)
    out.append(c.facts([
        ("Snapshot", c.code(r.snapshot_id) + _sub(f"received {pr.datetime_et(r.received_at_utc)}"
                                                  if r.received_at_utc else None)),
        ("Freshness at this capture", c.badge(fresh, label=f"{pr.state_word(fresh).label} (worst of books)")
         + _sub(f"as of {pr.datetime_et(r.as_of_utc)}" if r.as_of_utc else None)),
        ("Books quoting this event", c.num(pr.count(event.bookmaker_count))),
        ("Consensus version", c.code(r.consensus_version)),
    ], wide=True, text_cols=(1,)))
    order = {"h2h": 0, "spreads": 1, "totals": 2}
    props = sorted(event.propositions, key=lambda p: (order.get(p.market_key, 9), p.market_key,
                                                      tuple(ln or "" for _, ln in p.outcomes)))
    out += [_proposition(p) for p in props] or [c.empty_state(
        "No proposition paired", "No book offered a clean two-sided market for this event in this capture.")]
    if event.unsupported:
        out.append('<h4 class="eyebrow">Not in any consensus (unsupported)</h4>' + c.table(
            ["market", "line", "reason code", "reasons", "books"],
            [[esc(pr.odds_market_label(g.market_key)), esc(g.line or "—"), c.code(g.status), esc("; ".join(g.reasons)),
              esc(", ".join(g.bookmakers))] for g in event.unsupported], wrap=(3, 4), caption="Unsupported groups"))
    detail = [("dispersion method", c.code(getattr(event.propositions[0].consensus[0], "dispersion_method", None)
                                           if event.propositions else None) + _sub(DISPERSION_TEXT)),
              ("input sha256", c.code(r.input_sha256)), ("output sha256", c.code(r.output_sha256)),
              ("odds format", c.code(r.odds_format)), ("purpose", c.code(r.purpose)), ("slot", c.code(r.slot_id)),
              ("problems", c.ul(r.problems, empty="none"))]
    out.append(c.disclosure("Consensus provenance", c.kv(detail)))
    out.append(f'<p class="note">{esc(CONSENSUS_NOTE)}</p>')
    return "".join(out)


def target_row(t: d.OddsTarget, now: Any, max_age: Any = None, related: Any = None) -> str:
    """One capture target: event, horizon, intended time, receipt, state, credits, books, freshness."""
    facts = [("Intended (ET)", _intended(t)), ("Actual receipt", _receipt(t)), ("Credits", target_credits(t)),
             ("Books returned", target_books(t)), ("Freshness", target_freshness(t, now, max_age))]
    if t.reason:
        facts.append(("Reason", esc(t.reason)))
    if isinstance(related, dict) and t.event_id in related:  # the Polymarket US relationship of this event
        code, word = related[t.event_id]
        facts.append(("Polymarket US", c.state_text(code, label=word.label, kind=word.kind)
                      + _sub("details under Polymarket US related markets")))
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
    consensus = (c.disclosure(f"Consensus at this capture · {CONSENSUS_LABEL}",
                              consensus_body(t.consensus, t.snapshot_id)) if t.consensus is not None else "")
    return c.row(esc(pr.odds_event_label(t.away_team, t.home_team, t.event_id)), sub=sub, aside=c.badge(t.state),
                 body=c.facts(facts, wide=True, text_cols=(0, 1, 4, 5)) + consensus + detail)


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
          + _sub(_books_flag(t)),
          _at_receipt(t) if t.state == "CAPTURED" else c.state_text(t.freshness)] for t in rows],
        wrap=(0,), right=(5, 6), caption="Odds capture targets")
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


def odds_targets_body(result: d.Loaded, status: d.Loaded, now: Any, related: Any = None) -> str:
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
            '<ul class="rows">' + "".join(target_row(t, now, data.odds_max_age, related) for t in group) + "</ul>"
            if group else f'<p class="meta">{esc(none)}</p>'))
    out.append(c.disclosure(f"All targets ({pr.count(len(data.rows))})", targets_table(data), boxed=True))
    out.append(f'<p class="note">{esc(TARGETS_NOTE)}</p>')
    return "".join(x for x in out if x)


def odds_targets_section(ctx: d.Context) -> str:
    from ...odds_pilot import RunnerSettings

    settings = RunnerSettings()
    horizons = " / ".join(o.label for o in sorted(settings.config.offsets, key=lambda o: -o.before))
    return c.section("Odds capture targets", odds_targets_body(ctx.odds_targets, ctx.odds_status, ctx.now,
                                                               pm_event_states(ctx.pm_sports)),
                     meta=f"{pr.sport_label(settings.sport)} · {horizons} before kickoff · research only",
                     sid="odds-t-h")


# --------------------------------------------------------------------------- Freshness Fabric (ADR 0031)

FRESHNESS_NOTE = ("The fabric observes; it runs, triggers and reschedules nothing. A source in external-schedule mode "
                  "is run by its own timer (named on each row) and only supervised here. Every verdict is the "
                  "supervisor's at its evaluation time, never recomputed here: data fresh then may be older now. "
                  "Research use needs a receipt of known freshness; decision use needs fresh data and healthy "
                  "acquisition, and never rests on a stale or undated report.")


def _scrub(text: str) -> str:
    """Free text without filesystem paths, by the fabric's own rule (`freshness_fabric.scrub`: time zones
    such as America/New_York and windows such as 17:40-18:35 stay intact)."""
    from ...freshness_fabric import strip_paths

    return strip_paths(text)  # never shortened: the details disclosure shows everything


def _texts(value: Any) -> list[str]:
    """A JSON list of free texts as a list (a bare string is one item, never its characters), scrubbed."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [_scrub(x if isinstance(x, str) else json.dumps(x, default=str)) for x in value]


def _text(value: Any) -> str | None:
    """An identifier or recorded time as written (a string only; anything else is unknown)."""
    return value if isinstance(value, str) and value else None


def _items(summary: Any, key: str) -> list | None:
    value = summary.get(key) if isinstance(summary, dict) else None
    return value if isinstance(value, list) else None


def _count_of(summary: Any, key: str) -> str:
    items = _items(summary, key)
    return c.num(pr.count(len(items)) if items is not None else None, reason="not recorded in the report")


def _trusted_badge(code: Any, word: pr.StateWord, trusted: bool, suffix: str = "") -> str:
    """A state capsule; under a report that is not fresh, a positive verdict is shown neutral, never green."""
    kind = word.kind if trusted or word.kind != pr.OK_K else pr.ND_K
    return c.badge(code, label=word.label + suffix, kind=kind)


def _usable(src: Any, trusted: bool, report_word: str) -> str:
    research, decision = src.get("usable_for_research") is True, src.get("usable_for_decision") is True
    if not trusted:
        return c.state_text("UNKNOWN", label=f"Not decision-grade: report {report_word}", kind=pr.WARN_K)
    if decision:
        return c.state_text("FRESH", label="Research and decision, at evaluation")
    if research:
        return c.state_text("STALE", label="Research only")
    return c.state_text("UNKNOWN", label="Not usable")


ATTENTION_SCHEDULE = ("MISSED", "PAUSED", "BUDGET_BLOCKED", "QUOTA_BLOCKED", "LOCK_BUSY")
ATTENTION_HEALTH = ("FAILING", "DEGRADED")


def needs_attention(src: Any) -> bool:
    """A source the owner should look at first, by the artifact's own states (a filter, not a verdict)."""
    return (src.get("schedule_state") in ATTENTION_SCHEDULE or src.get("health") in ATTENTION_HEALTH
            or bool(_texts(src.get("disagreements"))))


def fabric_source_row(src: Any, policy: Any, now: Any, *, trusted: bool = True, report_word: str = "stale",
                      judged_at: Any = None) -> str:
    """One supervised source: freshness and usability at evaluation, schedule state, health, next due,
    why; the policy and every recorded time in a disclosure. Values are the artifact's, only formatted.
    `trusted` is False when the report itself is stale or undated: nothing then reads as current."""
    src = src if isinstance(src, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    carried = _text(src.get("carried_from_utc"))
    at = _text(judged_at) or (_text(src.get("as_of_utc")))
    at_text = f"at evaluation, {pr.datetime_et(at)}" if pr.datetime_et(at) else "at evaluation"
    age = pr.duration_text(src.get("data_age_s"))
    objective = pr.duration_text(src.get("max_useful_age_s"))
    fresh_code = pr.freshness_code(src.get("freshness"))
    facts = [
        ("Freshness", _trusted_badge(fresh_code, pr.state_word(fresh_code), trusted) + _sub(" · ".join(x for x in (
            at_text, f"data {age} old then" if age else "no receipt recorded",
            f"objective {objective}" if objective else "no objective") if x))),
        ("Schedule", _trusted_badge(src.get("schedule_state"), pr.prefixed_word("SCHEDULE", src.get("schedule_state")),
                                    trusted) + _sub(f"as of {pr.datetime_et(carried)}" if carried else None)),
        ("Health", _trusted_badge(src.get("health"), pr.prefixed_word("HEALTH", src.get("health")), trusted)),
        ("Next due", c.txt(pr.datetime_et(src.get("next_due_utc")), reason="nothing planned or not known")),
        ("Last successful receipt", c.txt(pr.datetime_et(src.get("last_success_receipt_utc")),
                                          reason="no successful receipt recorded")),
        ("Usable for", _usable(src, trusted, report_word) + _sub(at_text if trusted else None)),
        ("Why", esc(_scrub(_text(src.get("why_due")) or "not stated"))),
    ]
    misses = src.get("missed_count")
    disagreements = _texts(src.get("disagreements"))
    details = src.get("details") if isinstance(src.get("details"), dict) else {}
    if isinstance(misses, int) and not isinstance(misses, bool) and misses > 0:
        facts.append(("Missed", c.num(pr.count(misses), cls="neg") + _sub(_text(details.get("missed_scope")))))
    if disagreements:
        facts.append(("Disagreements", c.state_text("WARNING", label=f"{pr.count(len(disagreements))} with the canonical "
                                                                      "scheduler")))
    detail = c.disclosure("Source details and policy", c.kv([
        ("source id", c.code(_text(src.get("source_id")))),
        ("description", esc(_text(policy.get("description")) or "not recorded")),
        ("acquisition mode", esc(pr.mode_label(src.get("mode"))) + " " + c.code(_text(src.get("mode")))),
        ("underlying mode", c.code(_text(src.get("underlying_mode")))),
        ("run by (schedule owner)", esc(_text(src.get("schedule_owner")) or "not recorded")),
        ("policy version", c.code(_text(src.get("policy_version")))),
        ("objective (max useful age)", c.txt(pr.duration_text(src.get("max_useful_age_s")), reason="no objective")),
        ("slowest safe cadence", c.txt(pr.duration_text(policy.get("min_safe_cadence_s")), reason="not defined")),
        ("fastest useful cadence", c.txt(pr.duration_text(policy.get("max_useful_cadence_s")), reason="not defined")),
        ("pacing", esc(_text(policy.get("pacing")) or "not stated")),
        ("budget or quota", esc(_text(policy.get("budget")) or "not stated")),
        ("protected windows", c.ul(_texts(policy.get("protected_windows")), empty="none")),
        ("retry", esc(_text(policy.get("retry")) or "not stated")),
        ("intended at", c.code(_text(src.get("intended_at_utc")))), ("next due", c.code(_text(src.get("next_due_utc")))),
        ("last attempt", c.code(_text(src.get("last_attempt_utc")))), ("receipt", c.code(_text(src.get("receipt_ts_utc")))),
        ("upstream timestamp", c.code(_text(src.get("upstream_ts_utc")))),
        ("upstream age at evaluation", c.txt(pr.duration_text(src.get("upstream_age_s")), reason="not recorded")),
        ("evaluated at", c.code(_text(src.get("as_of_utc")))), ("carried from", c.code(carried)),
        ("recent misses", c.ul(_texts(src.get("recent_misses")), empty="none")),
        ("disagreements", c.ul(disagreements, empty="none")), ("notes", c.ul(_texts(src.get("notes")), empty="none")),
        ("details", esc(_scrub(c._json_text(details))) if details else c.na("none recorded")),
    ]))
    sub = f"{_text(src.get('domain')) or 'domain not recorded'} · {pr.mode_label(src.get('mode'))}"
    if src.get("mode") == "EXTERNAL_SCHEDULE":
        sub += f" · run by {_text(src.get('schedule_owner')) or 'an owner not recorded'}"
    return c.row(esc(_text(src.get("source_id")) or "unnamed source"), sub=sub,
                 aside=_trusted_badge(fresh_code, pr.state_word(fresh_code), trusted),
                 body=c.facts(facts, wide=True, text_cols=(0, 1, 2, 3, 4, 5, 6)) + detail)


def supervisor_state(doc: Any, report: d.FreshnessReport, now: Any) -> str:
    """The report-level states: stale or undated report, deferred (carried or not), partial or unknown."""
    sup = doc.get("supervisor") if isinstance(doc.get("supervisor"), dict) else {}
    out = []
    generated = _text(doc.get("generated_at_utc"))
    if report.report_freshness != "FRESH":
        ago = pr.age_text(generated, now)
        out.append(c.empty_state(
            "Freshness report is stale" if report.report_freshness == "STALE" else "Freshness report time unknown",
            f"Generated {pr.datetime_et(generated) or 'at an unreadable time'}" + (f" ({ago})" if ago else "")
            + f"; the supervisor runs every 5 minutes and a report older than "
            f"{pr.duration_text(report.max_age.total_seconds())} is stale. Every source below is as of that time, not "
            "now, and none is decision-grade.", kind="warn"))
    state = sup.get("state")
    if state == "DEFERRED_PROTECTED_WINDOW":
        deferred = sup.get("deferred") if isinstance(sup.get("deferred"), dict) else {}
        evaluated = _text(doc.get("sources_evaluated_at_utc"))
        window = (f"{pr.window_label(deferred.get('window'))} ({pr.datetime_et(deferred.get('from_utc')) or '?'} to "
                  f"{pr.time_et(deferred.get('to_utc')) or '?'})")
        text = (f"Inside the {window} the supervisor opens no store. Sources are carried from the "
                f"{pr.datetime_et(evaluated)} evaluation and re-judged at {pr.datetime_et(generated)} from their receipt "
                "times; schedule states are as of that evaluation; none is decision-grade."
                if pr.datetime_et(evaluated) else f"Inside the {window} the supervisor opens no store, and no recent "
                                                  "evaluation could be carried: every source is unknown until the "
                                                  "window closes.")
        out.append(c.empty_state("Supervisor deferred: protected window", text, kind="warn"))
    elif state is None:
        out.append(c.empty_state("Supervisor state not recorded", "The report does not say how the supervisor ran; "
                                 "its sources are shown as recorded.", kind="nd"))
    elif state != "OK":
        out.append(c.empty_state(pr.prefixed_word("SUPERVISOR", state).label,
                                 "; ".join(_texts(sup.get("problems"))) or "a provider reported a problem", kind="warn"))
    return "".join(out)


def _freshness_view(report: d.FreshnessReport, now: Any) -> str:
    doc = report.doc
    sources = [s for s in doc.get("sources") or [] if isinstance(s, dict)]
    policies = {p["source_id"]: p for p in doc.get("policies") or []
                if isinstance(p, dict) and isinstance(p.get("source_id"), str)}
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    sup = doc.get("supervisor") if isinstance(doc.get("supervisor"), dict) else {}
    out = [supervisor_state(doc, report, now)]
    if not sources:
        out.append(c.empty_state("No sources in the report", "The supervisor's report lists no source."))
        return "".join(out)
    trusted = report.report_freshness == "FRESH"
    report_word = "stale" if report.report_freshness == "STALE" else "time unknown"
    generated = _text(doc.get("generated_at_utc"))
    fresh_ids = _items(summary, "fresh")
    total = summary.get("sources") if isinstance(summary.get("sources"), int) else None
    external = sum(1 for s in sources if s.get("mode") == "EXTERNAL_SCHEDULE")
    out.append(c.facts([
        ("Report generated", c.txt(pr.datetime_et(generated), reason="not recorded") + _sub(pr.age_text(generated, now))),
        ("Sources evaluated", c.txt(pr.datetime_et(doc.get("sources_evaluated_at_utc")), reason="nothing evaluated")),
        ("Fresh at evaluation", c.num(f"{pr.count(len(fresh_ids))} of {pr.count(total)}"
                                      if fresh_ids is not None and total is not None else None,
                                      reason="not recorded in the report")),
        ("Due now", _count_of(summary, "due_now")), ("Missed", _count_of(summary, "missed")),
        ("Blocked", _count_of(summary, "blocked")), ("Schedule unknown", _count_of(summary, "unknown")),
    ], wide=True, text_cols=(0, 1)))
    if total is not None and total != len(sources):
        out.append(f'<p class="meta">The report counts {esc(pr.count(total))} sources and lists '
                   f"{esc(pr.count(len(sources)))}.</p>")
    out.append(f'<p class="meta">{esc(pr.count(external))} of {esc(pr.count(len(sources)))} sources listed are external '
               f"schedules the fabric only supervises · network: {esc(_text(sup.get('network')) or 'not recorded')} · "
               f"controls schedules: {'no' if sup.get('controls_schedules') is False else 'not recorded'}</p>")
    upcoming = [n for n in _items(summary, "next_due") or [] if isinstance(n, dict)]
    if upcoming:
        out.append('<h3 class="eyebrow">Due next (at evaluation)</h3>' + c.ul(
            f"{pr.datetime_et(n.get('next_due_utc')) or 'time not recorded'} · {_text(n.get('source_id')) or '—'}: "
            f"{_scrub(_text(n.get('why')) or '—')}" for n in upcoming))

    def rows(items: list) -> str:
        return '<ul class="rows">' + "".join(fabric_source_row(
            s, policies.get(s.get("source_id")) if isinstance(s.get("source_id"), str) else None, now,
            trusted=trusted, report_word=report_word,
            judged_at=generated if s.get("carried_from_utc") else None) for s in items) + "</ul>"
    attention = [s for s in sources if needs_attention(s)]
    out.append('<h3 class="eyebrow">Needs attention</h3>' + (
        rows(attention) if attention else '<p class="meta">No source is missed, blocked, failing, degraded or '
                                          "disagreeing with its scheduler.</p>"))
    domains: dict[str, list] = {}
    for s in sources:
        domains.setdefault(_text(s.get("domain")) or "other", []).append(s)
    every = "".join(f'<h4 class="eyebrow">{esc(domain)}</h4>' + rows(items) for domain, items in domains.items())
    out.append(c.disclosure(f"Every source by domain ({pr.count(len(sources))})", every, boxed=True))
    word = pr.prefixed_word("SUPERVISOR", sup.get("state"))
    word = word if trusted or word.kind != pr.OK_K else pr.StateWord(word.label, pr.ND_K)
    out.append(c.disclosure("Supervisor details", c.kv([
        ("schema", c.code(_text(doc.get("schema")))), ("fabric version", c.code(_text(doc.get("fabric_version")))),
        ("supervisor state", c.state_text(sup.get("state"), label=word.label, kind=word.kind) + " "
         + c.code(_text(sup.get("state")))), ("code version", c.code(_text(sup.get("code_version")))),
        ("providers", c.ul(f"{x.get('provider')}: {x.get('state')}" for x in _items(sup, "providers") or []
                           if isinstance(x, dict))),
        ("problems", c.ul(_texts(sup.get("problems")), empty="none")),
        ("disagreements (all sources)", c.num(pr.count(summary.get("disagreements")), reason="not recorded")),
        ("generated at (UTC)", c.code(generated)),
        ("sources evaluated at (UTC)", c.code(_text(doc.get("sources_evaluated_at_utc")))),
    ])))
    out.append(f'<p class="note">{esc(FRESHNESS_NOTE)}</p>')
    return "".join(x for x in out if x)


def freshness_body(result: d.Loaded, now: Any) -> str:
    """Every state of the freshness view: populated, stale or undated report (nothing reads as current),
    deferred (carried or not), partial or unrecorded supervisor state, no sources, not written yet /
    not configured (source unavailable), read error, foreign schema or a malformed report."""
    if result.status == d.ERROR:
        return c.error_state("Source freshness unavailable (read error)",
                             f"ERROR — {result.message}. This is not a healthy or empty report.")
    if result.status != d.OK:
        msg = result.message or "the status directory is not configured"
        return c.unavailable("Source freshness unavailable", msg[:1].upper() + msg[1:] + ".")
    try:
        return _freshness_view(result.value, now)
    except Exception as exc:  # noqa: BLE001 - a malformed report is an error here, never a failed page
        return c.error_state("Source freshness unavailable (malformed report)",
                             f"ERROR — {d.short_error(exc)}. This is not a healthy or empty report.")


def freshness_section(ctx: d.Context) -> str:
    return c.section("Source freshness", freshness_body(ctx.freshness_status, ctx.now),
                     meta="What is fresh, what is due next, and why · Freshness Fabric", sid="fresh-h")


# --------------------------------------------------------------------------- Polymarket US related markets (ADR 0032)

PM_LABEL = "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"  # polymarket_sports.LABEL (tested equal)
PM_NOTE = ("A related Polymarket US market shares the league, both teams and the kickoff; its contract is not "
           "proven equal to any sportsbook's (payout structure differs; rule dimensions unverified), so it is never "
           "ranked, never compared as cheaper and never executable. A research book capture is evidence of one "
           "moment, not a price to act on. A listing that is partial, stale or not yet read says nothing about "
           "whether a market exists.")
PM_RESEARCH = "research book captures · not an executable price claim"
# Only a filtered listing read in full may say "no related market in the listing read"; every other
# catalog state (partial, stale, failed, none, or one this code does not know) says less.
PM_LISTED = "FILTER_COMPLETE"
PM_PARTIAL = ("PARTIAL_CATALOG", "STALE")
PM_NOT_LOADED = object()  # a market's capture history was not read for this page (never "none planned")
PM_COVERAGE = {"PARTIAL": "a filtered listing (never the full catalog)", "COMPLETE": "complete",
               "FAILED": "failed"}


def _pm(v: Any, key: str) -> Any:
    return v.get(key) if isinstance(v, dict) else None


def _pm_list(v: Any) -> list:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _pm_word(prefix: str, code: Any) -> pr.StateWord:
    return pr.prefixed_word(prefix, code)


def _pm_badge(prefix: str, code: Any) -> str:
    word = _pm_word(prefix, code)
    return c.badge(code, label=word.label, kind=word.kind)


def _pm_state(prefix: str, code: Any, label: str | None = None) -> str:
    word = _pm_word(prefix, code)
    return c.state_text(f"{prefix}_{code}", label=label or word.label, kind=word.kind)


def pm_event_state(event: Any, catalog_state: Any) -> tuple[str, pr.StateWord]:
    """The event's relationship state as shown. "No related market in the listing read" only under a
    filtered listing read in full; partial or stale says so; anything else reads "not checked"."""
    state = _pm(event, "state")
    if state == "NO_RELATED_MARKET" and catalog_state != PM_LISTED:
        if catalog_state in PM_PARTIAL:
            return "PM_EVENT_NONE_IN_PARTIAL", _pm_word("PM_EVENT", "NONE_IN_PARTIAL")
        return "PM_EVENT_NOT_CHECKED", _pm_word("PM_EVENT", "NOT_CHECKED")
    return str(state), _pm_word("PM_EVENT", state)


def _pm_fresh(value: Any) -> str:
    """Freshness of one research capture at its receipt (within its target window). Never green."""
    fresh = pr.freshness_code(value)
    return c.state_text(fresh, label=f"{pr.state_word(fresh).label} at capture",
                        kind=pr.INFO_K if fresh == "FRESH" else pr.state_word(fresh).kind)


def _pm_capture(cap: Any, source: str, now: Any) -> str:
    if not isinstance(cap, dict):
        return c.na("no research book captured yet")
    bid, ask = pr.cents(cap.get("yes_bid")), pr.cents(cap.get("yes_ask"))
    received = cap.get("received_at_utc")
    ago = pr.age_text(received, now)
    return (c.num(f"YES bid {bid or '—'}") + " · " + c.num(f"YES ask {ask or '—'}")
            + _sub(f"sizes {pr.quantity(cap.get('yes_bid_size')) or '—'} / {pr.quantity(cap.get('yes_ask_size')) or '—'} "
                   "contracts")
            + _sub(f"received {pr.datetime_et(received) or 'at an unrecorded time'}" + (f" ({ago})" if ago else "")
                   + " · research capture, not current")
            + _pm_fresh(cap.get("freshness")) + _sub("within its target window")
            + _sub(f"{_pm(cap, 'label') or 'research book capture'} · {source}"))


def _pm_targets(history: Any) -> str:
    if history is PM_NOT_LOADED:
        return c.state_text("UNKNOWN", label="Not loaded on this page", kind=pr.ND_K) + _sub(
            "capture history is read only for the events shown with the Odds targets")
    if not isinstance(history, list):
        return c.state_text("UNKNOWN", label="Capture history unreadable", kind=pr.WARN_K)
    if not history:
        return c.na("no capture target planned for this market")
    return " ".join(_pm_state("PM_TARGET", t.get("display_state") or t.get("state"),
                              f"{t.get('offset')} {_pm_word('PM_TARGET', t.get('display_state') or t.get('state')).label}")
                    for t in history if isinstance(t, dict))


def pm_market_block(m: Any, source: str, history: Any, now: Any) -> str:
    """One related (or ambiguous) Polymarket US market: relationship with reasons and checks, the latest
    research book capture with attribution, the capture targets' states; nothing is ranked or priced
    against a sportsbook."""
    checks = _pm(m, "checks") if isinstance(_pm(m, "checks"), dict) else {}
    rows = [[esc(str(name).replace("_", " ")), _pm_badge("PM_CHECK", _pm(v, "state")), esc(_pm(v, "detail") or "—")]
            for name, v in checks.items()]
    attempts = [a for t in (history if isinstance(history, list) else []) if isinstance(t, dict)
                for a in _pm_list(t.get("attempts"))]
    reasons = _pm(m, "reasons")
    body = c.facts([
        ("Relationship", _pm_badge("PM_EVENT", _pm(m, "relationship")) + _sub("; ".join(
            str(r) for r in (reasons if isinstance(reasons, list) else []) if isinstance(r, str)) or None)),
        ("Latest research book", _pm_capture(_pm(m, "latest_capture"), source, now)),
        ("Capture targets", _pm_targets(history)),
        ("Sides (as listed)", esc(f"long {_pm(m, 'long_side') or '—'} · short {_pm(m, 'short_side') or '—'}")),
    ], wide=True, text_cols=(0, 1, 2, 3))
    flags = _pm(m, "flags")
    attempts_html = (f'<p class="meta">{esc(source)} · {esc(PM_RESEARCH)}</p>' + c.table(
        ["target", "status", "received", "YES bid", "YES ask", "freshness at capture", "reason"],
        [[c.code(a.get("target_id")), _pm_state("PM_TARGET", a.get("status")),
          esc(pr.datetime_et(a.get("received_at_utc")) or "—"), c.num(pr.cents(a.get("yes_bid")), reason="none"),
          c.num(pr.cents(a.get("yes_ask")), reason="none"),
          _pm_fresh(a.get("freshness")) if a.get("received_at_utc") else c.na("nothing received"),
          esc(d.scrub_paths(a.get("reason")) or "—")] for a in attempts],
        wrap=(6,), caption=f"Capture attempts · {source} · {PM_RESEARCH}", empty="no attempt recorded")
        if history is not PM_NOT_LOADED else '<p class="meta">Capture attempts are not loaded on this page.</p>')
    detail = c.disclosure("Relationship checks, flags and attempts", c.kv([
        ("market", c.code(_pm(m, "market_slug"))), ("title", esc(_pm(m, "title") or "—")),
        ("game start (UTC)", c.code(_pm(m, "game_start_utc"))), ("payoff kind", c.code(_pm(m, "payoff_kind"))),
        ("rules sha256", c.code(_pm(m, "rules_sha256"))),
        ("flags", c.ul([str(f) for f in (flags if isinstance(flags, list) else [])], empty="none")),
        ("equivalent", esc("never (by construction)")), ("source", esc(source)),
    ]) + c.table(["dimension", "state", "detail"], rows, wrap=(2,), caption="Relationship checks") + attempts_html)
    title = esc(_pm(m, "title") or _pm(m, "market_slug") or "Polymarket US market")
    return f'<h4 class="eyebrow">{title}</h4>' + body + detail


PM_SHORT = {"RELATED_NOT_EQUIVALENT": "Related", "AMBIGUOUS": "Ambiguous", "NO_RELATED_MARKET": "None seen",
            "PM_EVENT_NONE_IN_PARTIAL": "None seen", "PM_EVENT_NOT_CHECKED": "Not checked"}
PM_EVENT_EMPTY = {
    "PM_EVENT_NOT_CHECKED": "Not looked for: no usable, complete Polymarket US listing exists. This says nothing about "
                            "whether a market exists.",
    "PM_EVENT_NONE_IN_PARTIAL": "None in the listing read, but that listing is partial or stale: absence is not "
                                "evidence.",
    "NO_RELATED_MARKET": "None in the filtered NFL moneyline listing read (a filtered listing, never the full catalog: "
                         "absence is not evidence).",
}


def pm_event_row(event: Any, catalog_state: Any, source: str, histories: Any, now: Any) -> str:
    code, word = pm_event_state(event, catalog_state)
    markets = _pm_list(_pm(event, "markets"))

    def history(m: Any) -> Any:
        if not isinstance(histories, dict) or _pm(m, "market_slug") not in histories:
            return PM_NOT_LOADED
        return histories[_pm(m, "market_slug")]
    body = "".join(pm_market_block(m, source, history(m), now) for m in markets)
    if not markets:
        body = f'<p class="row-sub">{esc(PM_EVENT_EMPTY.get(code, "No related market is recorded for this event."))}</p>'
    sub = (f"kickoff {pr.datetime_et(_pm(event, 'commence_utc')) or 'not recorded'} · Odds API event "
           f"{_pm(event, 'odds_event_id')}")
    # The aside capsule never wraps, so it carries a short word; the full label leads the row body.
    lead = f'<p class="eyebrow">{esc(word.label)}</p>'
    return c.row(esc(pr.odds_event_label(_pm(event, "away_team"), _pm(event, "home_team"), _pm(event, "odds_event_id"))),
                 sub=sub, aside=c.badge(code, label=PM_SHORT.get(code, word.label), kind=word.kind),
                 body=f"<div>{lead}{body}</div>")


def _pm_header(view: Any, now: Any) -> str:
    status = _pm(view, "status") if isinstance(_pm(view, "status"), dict) else {}
    catalog = _pm(status, "catalog") if isinstance(_pm(status, "catalog"), dict) else {}
    access = _pm(view, "access")
    out = []
    if access != "ALLOWED_BY_OWNER_RISK_DECISION":
        out.append(c.blocked_state("Polymarket US pilot blocked: terms review",
                                   "No networked run is allowed until the owner records an access decision. What was "
                                   "stored before is shown below as recorded."))
    cstate = _pm(catalog, "state")
    notes = {"NO_SCAN": ("No Polymarket US scan yet", "Nothing has been looked for: no event below can read as having "
                                                      "no market."),
             "FAILED": ("No usable Polymarket US scan", "The last scan failed (its detail is under Last scan attempt); "
                                                        "nothing below can read as having no market."),
             "PARTIAL_CATALOG": ("Partial Polymarket US listing", "Not every page of the filtered listing was read (the "
                                                                  "detail is under Last scan attempt). A market missing "
                                                                  "below may exist."),
             "STALE": ("Polymarket US listing is stale", "The latest usable scan is older than a day; relationships "
                                                         "below are as of that scan.")}
    if cstate in notes:
        out.append(c.empty_state(notes[cstate][0], notes[cstate][1], kind="warn" if cstate != "NO_SCAN" else "nd"))
    elif cstate != PM_LISTED:
        out.append(c.empty_state("Polymarket US listing state not recognised",
                                 f"The pilot reports {cstate!r}; no event below reads as having no market.", kind="warn"))
    last, usable = _pm(catalog, "last_attempt_utc"), _pm(catalog, "usable_scan_utc")
    if isinstance(last, str) and isinstance(usable, str) and last != usable:
        out.append(c.empty_state("The latest scan attempt was not usable",
                                 f"The attempt at {pr.datetime_et(last) or last} did not produce a usable listing; the "
                                 f"listing from {pr.datetime_et(usable) or usable} is still used.", kind="warn"))
    coverage = _pm(catalog, "last_attempt_coverage")
    coverage_text = PM_COVERAGE.get(coverage, coverage) if isinstance(coverage, str) else None
    out.append(c.facts([
        ("Access", _pm_badge("PM_ACCESS", access) + _sub(f"decision: {_pm(status, 'access_decision')}"
                                                         if _pm(status, "access_decision") else None)),
        ("Catalog", _pm_badge("PM_CATALOG", cstate)
         + _sub(f"{pr.count(_pm(catalog, 'markets'))} markets · scan {pr.datetime_et(usable)}"
                if isinstance(usable, str) else _pm(catalog, "detail"))
         + _sub(_pm(catalog, "coverage_note") if isinstance(_pm(catalog, "coverage_note"), str) else None)),
        ("Last scan attempt", c.txt(pr.datetime_et(last), reason="none")
         + _sub(" · ".join(x for x in (f"coverage: {coverage_text}" if coverage_text else None,
                                        _pm(catalog, "last_attempt_detail")) if isinstance(x, str) and x) or None)),
        ("Next discovery", c.txt(pr.datetime_et(_pm(status, "discovery_next_due_utc")), reason="not scheduled")),
    ], wide=True, text_cols=(0, 1, 2, 3)))
    return "".join(out)


def pm_shown_events(events: Any, event_ids: Any = ()) -> list[str]:
    """The events shown as rows: those of the Odds target rows shown, else the soonest; bounded."""
    if not isinstance(events, dict):
        return []
    wanted = [e for e in event_ids if e in events][:d.PM_EVENTS_SHOWN]
    return wanted or sorted(events, key=lambda k: str(_pm(events[k], "commence_utc")))[:d.PM_EVENTS_SHOWN]


def _pm_view(view: Any, now: Any, event_ids: Any, histories: Any) -> str:
    related = _pm(view, "related") if isinstance(_pm(view, "related"), dict) else {}
    source = str(_pm(view, "source") or _pm(related, "source") or "source not recorded")
    catalog_state = _pm(_pm(_pm(view, "status"), "catalog"), "state")
    events = _pm(related, "events")
    if events is not None and not isinstance(events, dict):
        raise TypeError("the related events are not a mapping")
    events = {k: v for k, v in (events or {}).items() if isinstance(v, dict)}
    out = [f'<p class="eyebrow">{esc(_pm(view, "label") or PM_LABEL)}</p>', _pm_header(view, now)]
    if not events:
        out.append(c.empty_state("No Odds API NFL schedule stored", "Relationships are made per Odds API event; no "
                                 "stored schedule was found."))
    else:
        out.append('<ul class="rows">' + "".join(pm_event_row(events[e], catalog_state, source, histories, now)
                                                 for e in pm_shown_events(events, event_ids)) + "</ul>")

        def captures(e: Any) -> list:
            return [m for m in _pm_list(_pm(e, "markets")) if isinstance(_pm(m, "latest_capture"), dict)]
        table = c.table(["event", "kickoff", "state", "market", "latest YES bid · ask (research)", "received",
                         "freshness at capture"], [
            [esc(pr.odds_event_label(_pm(e, "away_team"), _pm(e, "home_team"), _pm(e, "odds_event_id"))),
             esc(pr.datetime_et(_pm(e, "commence_utc")) or "—"),
             c.state_text(pm_event_state(e, catalog_state)[0], label=pm_event_state(e, catalog_state)[1].label,
                          kind=pm_event_state(e, catalog_state)[1].kind),
             c.ul([str(_pm(m, "market_slug")) for m in _pm_list(_pm(e, "markets"))], empty="—"),
             esc(" / ".join(f"{pr.cents(_pm(_pm(m, 'latest_capture'), 'yes_bid')) or '—'} · "
                            f"{pr.cents(_pm(_pm(m, 'latest_capture'), 'yes_ask')) or '—'}" for m in captures(e)) or "—"),
             esc(" / ".join(pr.datetime_et(_pm(_pm(m, "latest_capture"), "received_at_utc")) or "—"
                            for m in captures(e)) or "—"),
             " ".join(_pm_fresh(_pm(_pm(m, "latest_capture"), "freshness")) for m in captures(e)) or c.na("no capture")]
            for e in sorted(events.values(), key=lambda e: str(_pm(e, "commence_utc")))], wrap=(0, 3),
            caption=f"Polymarket US relationships per Odds API event · {source} · {PM_RESEARCH}")
        out.append(c.disclosure(f"All Odds API events ({pr.count(len(events))})",
                                f'<p class="meta">{esc(source)} · {esc(PM_RESEARCH)}</p>' + table, boxed=True))
    out.append(f'<p class="note">{esc(PM_NOTE)} Source: {esc(source)}.</p>')
    return "".join(x for x in out if x)


def pm_related_body(result: d.Loaded, now: Any, event_ids: Any = (), histories: Any = None) -> str:
    """Every state: populated (related, ambiguous, none), no scan, partial, stale or unrecognised catalog,
    gate blocked, capture captured / missed / failed / overdue / not executable, history not loaded,
    error (including a malformed view), source unavailable."""
    if result.status == d.ERROR:
        return c.error_state("Polymarket US related markets unavailable (read error)",
                             f"ERROR — {result.message}. This is not an empty listing.")
    if result.status != d.OK:
        return c.unavailable("Polymarket US related markets unavailable", result.message[:1].upper()
                             + result.message[1:] + ".")
    try:
        return _pm_view(result.value, now, event_ids, histories)
    except Exception as exc:  # noqa: BLE001 - a malformed view is an error here, never a failed page
        return c.error_state("Polymarket US related markets unavailable (malformed view)",
                             f"ERROR — {d.short_error(exc)}. This is not an empty listing.")


def pm_event_states(result: d.Loaded) -> dict[str, tuple[str, pr.StateWord]] | None:
    """Odds API event id -> the relationship state shown for it (None when the view is not readable)."""
    if result.status != d.OK:
        return None
    events = _pm(_pm(result.value, "related"), "events")
    catalog_state = _pm(_pm(_pm(result.value, "status"), "catalog"), "state")
    if not isinstance(events, dict):
        return None
    return {k: pm_event_state(e, catalog_state) for k, e in events.items() if isinstance(e, dict)}


def pm_related_section(ctx: d.Context) -> str:
    """After the Odds capture targets: the events of the rows shown there first, else the soonest; the
    capture history is read for exactly the events rendered (bounded)."""
    result = ctx.pm_sports
    ids: list[str] = []
    if ctx.odds_targets.status == d.OK:
        for t in (*ctx.odds_targets.value.recent, *ctx.odds_targets.value.upcoming):
            if t.event_id not in ids:
                ids.append(t.event_id)
    histories = None
    if result.status == d.OK:
        events = _pm(_pm(result.value, "related"), "events")
        shown = pm_shown_events(events, ids)
        slugs = sorted({_pm(m, "market_slug") for e in shown for m in _pm_list(_pm(events[e], "markets"))
                        if isinstance(_pm(m, "market_slug"), str)})
        loaded = d.pm_market_history(ctx, slugs)
        histories = loaded.value if loaded.status == d.OK else None
    return c.section("Polymarket US related markets", pm_related_body(result, ctx.now, ids, histories),
                     meta="NFL moneyline · research only · never ranked", sid="pm-h")


# --------------------------------------------------------------------------- Economic evidence (Economic Evidence v1)

EV_LABEL = "PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM"  # sports_evidence.LABEL (tested equal)
EV_NOTE = ("Two research families at most, read-only. Nothing here is an edge, a captured result, a funded account or "
           "a recommendation. Missing evidence is listed as missing and never counted as zero; a paired observation is "
           "not an episode, and visible depth is not capacity.")
EV_STATE_TEXT = {
    "PARTIAL": ("Evidence incomplete", "Some due horizons have no paired evidence. What is missing is listed under "
                                       "Missing evidence; nothing is filled from a later book."),
    "STALE": ("Evidence is stale", "No new evidence has arrived for longer than an NFL week while horizons fell due. "
                                   "Nothing here is current."),
    "UNPAIRED": ("No paired evidence yet", "Horizons fell due, but none has both a usable consensus and a Kalshi "
                                           "book. What is missing is listed under Missing evidence."),
    "EMPTY": ("No NFL capture targets yet", "The Odds API pilot has planned no due horizon, so there is nothing to "
                                            "pair yet."),
    "UNSUPPORTED": ("Kalshi payoff unsupported", "The mapped Kalshi markets are not $1 binary contracts, so no "
                                                 "comparison is made."),
}


def _ev(v: Any, *keys: str) -> Any:
    for k in keys:
        v = v.get(k) if isinstance(v, dict) else None
    return v


def _ev_count(v: Any, *keys: str) -> str | None:
    return pr.count(_ev(v, *keys))


def _fill_mode_line(mode: dict) -> str:
    """One fill mode, led by its research_economics v2 label (ADR 0037), not the legacy enum id.

    The label comes from `research_economics.FILL_MODE_SEMANTICS`; the report text already starts with it,
    so that prefix is not repeated. An unknown id is shown as recorded."""
    mid, basis, text = _ev(mode, "id"), _ev(mode, "basis"), str(_ev(mode, "text") or "")
    try:
        label = FILL_MODE_SEMANTICS[FillMode(mid)].label
    except (ValueError, KeyError):
        return f"{mid} ({basis}): {text}"
    if text.startswith(label + ":"):
        text = text[len(label) + 1:].strip()
    return f"{label} ({basis}; legacy id {mid}): {text}"


def _book_timing_text(timing: Any) -> str:
    """Plain text for the paired book's timing (sports_evidence join v2); no new state word or style."""
    return {"AT_OR_AFTER_ODDS": "book at or after the odds (executable-price candidate)",
            "BEFORE_ODDS": "book before the odds (comparability only)"}.get(timing, "book timing not recorded")


def _ev_capacity(cap: Any) -> str:
    """The latest paired book's size ladder (research_economics.size_ladder_from_depth), as the report gives it."""
    latest = _ev(cap, "latest")
    modes = [_fill_mode_line(a) for a in (_ev(cap, "fill_modes") or []) if isinstance(a, dict)]
    head = (f'<p class="meta">{esc(_ev_count(cap, "sides_with_book") or "—")} paired side(s) with a book · '
            f'{esc(_ev_count(cap, "truncated") or "—")} truncated capture(s)</p>')
    if not isinstance(latest, dict):
        body = c.empty_state("Capacity not measured", "No paired Kalshi book exists, so no size ladder can be walked. "
                                                      "Visible depth would still not be capacity.")
    else:
        lock = _ev(latest, "lockup_hours")
        meta = (f"Latest paired book: {_ev(latest, 'ticker')} · {_ev(latest, 'horizon')} · decision "
                f"{pr.datetime_et(_ev(latest, 'decision_utc')) or 'time not recorded'} · captured depth "
                f"{pr.quantity(_ev(latest, 'visible_depth')) or '—'} contracts, "
                f"{'truncated' if _ev(latest, 'depth_truncated') else 'complete as requested'} · "
                f"{_book_timing_text(_ev(latest, 'book_timing'))} · lockup to expected "
                f"expiration {_ev(lock, 'expected') if _ev(lock, 'expected') is not None else '—'} h (latest "
                f"{_ev(lock, 'latest') if _ev(lock, 'latest') is not None else '—'} h)")
        rows = [[c.num(pr.quantity(_ev(r, "size"))), _pm_state("EV_FILL", _ev(r, "depth_status")),
                 c.num(pr.cents(_ev(r, "all_in_cost_per_unit")), reason="no all-in cost: fees not priced"),
                 c.state_text("EV_GAP_UNSUPPORTED", label="Fee unsupported") if _ev(r, "fee_status") == "FEE_UNSUPPORTED"
                 else _pm_state("EV_FEE", _ev(r, "fee_status"))]
                for r in (_ev(latest, "ladder") or []) if isinstance(r, dict)]
        if _ev(latest, "book_timing") == "BEFORE_ODDS":
            ladder_html = c.empty_state("Comparability-only pair", "This book was received before the odds, so it is "
                                                                   "older than the decision time and is not an "
                                                                   "executable price. It counts for markout and "
                                                                   "calibration; no size ladder is walked and no "
                                                                   "economics episode is formed.")
        else:
            ladder_html = c.table(["contracts", "captured depth", "all-in cost / contract", "fee"], rows, wrap=(1, 3),
                                  right=(0, 2), caption="Size ladder over the latest paired book (research_economics)")
        body = f'<p class="meta">{esc(meta)}</p>' + ladder_html
    return head + body + '<p class="meta">Fill modes (applied to episodes, never to one look):</p>' + c.ul(
        modes, empty="no fill mode recorded") + (
        '<p class="note">Visible depth is an instantaneous ceiling, not capacity; a small fill is never extrapolated '
        "across a bankroll. All-in cost is unknown while fees are unsupported, and no expected value is estimated "
        "without a probability of this contract's payoff.</p>")


def _ev_none(value: Any, reason: str) -> str:
    """A denominator: a number, or the unavailable marker (None is unknown / not applicable, never 0)."""
    return c.num(pr.count(value), reason=reason)


def _ev_protocol_attrition(pa: Any) -> str:
    den = _ev(pa, "denominators") if isinstance(_ev(pa, "denominators"), dict) else {}
    labels = (("events", "games"), ("markets", "Kalshi markets"), ("scheduled_horizons", "scheduled horizons"),
              ("snapshots", "snapshots"), ("opportunities", "opportunities (horizon × side)"),
              ("eligible_opportunities", "eligible"), ("signals", "signals"), ("simulated_fills", "simulated fills"),
              ("final_evaluable_outcomes", "final-evaluable outcomes"))
    facts = c.facts([(label, _ev_none(den.get(key), "not enumerated or not applicable: unknown, not zero"))
                     for key, label in labels], wide=True)
    opp = next((w for w in (_ev(pa, "waterfalls") or []) if isinstance(w, dict) and w.get("level") == "OPPORTUNITY"),
               None)
    table = "" if not isinstance(opp, dict) else c.table(
        ["exclusion", "stage", "primary", "remaining"],
        [[esc(str(r.get("exclusion")).replace("_", " ").capitalize()), esc(str(r.get("stage")).capitalize()),
          c.num(pr.count(r.get("primary_count")), reason="not applicable (no registered rule) or withheld (outcome "
                                                          "labels): unknown, not zero"),
          c.num(pr.count(r.get("remaining_after")))] for r in opp.get("rows") or [] if isinstance(r, dict)],
        wrap=(0,), right=(2, 3), caption="Opportunity waterfall (research_evidence.attrition_report)")
    return facts + table + c.ul([str(n) for n in (_ev(pa, "notes") or [])], empty="")


def _ev_screen(screen: Any) -> str:
    eps = _ev(screen, "episodes") if isinstance(_ev(screen, "episodes"), dict) else {}
    return (c.facts([("Verdict", _pm_badge("EV_SCREEN", _ev(screen, "verdict"))),
                     ("Observations", c.num(pr.count(eps.get("observations")), reason="not recorded")),
                     ("Episodes", c.num(pr.count(eps.get("episodes")),
                                        reason="not evaluable: no frozen episode definition")),
                     ("Report sha256", c.code(_ev(screen, "report_sha256")))], wide=True, text_cols=(0, 3))
            + c.ul([str(r) for r in (_ev(screen, "reasons") or [])], empty="no reason recorded")
            + f'<p class="note">{esc(_ev(screen, "not_an_edge_claim") or "A screen verdict is a research state, not an edge.")}'
              "</p>")


GATE_TEXT = {  # sports_evidence gate v3 verdicts, in plain words; nothing here is a pass
    "INSUFFICIENT_EVIDENCE": "Spreads cannot bound latent, stale or shared book error, so the bias of the markout is "
                             "not bounded (assumption W is not identified from these observations).",
    "INSUFFICIENT_DATA": "Too few admissible T-6h games or NFL weeks for any bound.",
    "FAIL": "The two team books quote as one (mirror quoting): the cross-book design removes none of the bias.",
}
ACCESS_TEXT = {"NO_LABEL_VIEW_LOGGED": "No logged label view", "LABEL_VIEWS_LOGGED": "Label views logged",
               "NO_LOG": "No evidence-use log · access unknown", "NO_PROTOCOL": "No protocol registered",
               "UNREADABLE": "Evidence-use log unreadable · access unknown"}


def _gate_access(acc: Any) -> str:
    if not isinstance(acc, dict):
        return c.txt(None, reason="outcome access not recorded")
    state = acc.get("state")
    label = ACCESS_TEXT.get(str(state), str(state))
    if state == "LABEL_VIEWS_LOGGED":
        label = (f"{pr.count(acc.get('label_views'))} logged label view(s) · latest "
                 f"{pr.datetime_et(acc.get('latest_label_view_utc')) or 'time not recorded'} · "
                 f"{', '.join(acc.get('roles') or []) or 'role not recorded'}")
    return c.txt(label) + _sub("the gate reads no label; this page shows none · the log records declared access only")


def _ev_exp002_gate(g: Any, family_state: str) -> str:
    """The EXP-002 gate line (UI_CONTRACT §8 Family A; owner directive 2026-09-28 §21A): gate v3's version, as-of,
    input horizons, admissible count, diagnostics, outcome access, the insufficiency or failure reason and a
    diagnostic-only flag, with freeze eligibility shown separately. Never green and never "ready to freeze"."""
    if not isinstance(g, dict):
        return c.facts([("EXP-002 pre-freeze gate", c.txt(None, reason="not computed by this build")
                         + _sub("gate status not available in this view"))], wide=True, text_cols=(0,))
    if g.get("state") != "OK":
        err = pr.prefixed_word("EV_STATE", "ERROR")  # the canonical error kind; the gate names its own label
        return c.facts([("EXP-002 pre-freeze gate", c.badge("EV_GATE_ERROR", label="Gate error", kind=err.kind) + _sub(
            f"{g.get('version') or 'gate'} could not be computed: {g.get('detail') or 'no detail'}")),
                        ("Freeze eligibility", _pm_badge("EV_FREEZE", "NOT_ELIGIBLE")
                         + _sub("no gate result: not eligible"))], wide=True, text_cols=(0, 1))
    verdict = str(g.get("verdict") or "UNKNOWN")
    counts = g.get("counts") if isinstance(g.get("counts"), dict) else {}
    est = g.get("estimates") if isinstance(g.get("estimates"), dict) else {}
    horizons = g.get("input_horizons") if isinstance(g.get("input_horizons"), dict) else {}
    freeze = g.get("freeze") if isinstance(g.get("freeze"), dict) else {}
    reasons = [str(x) for x in (g.get("insufficient") or [])]
    why = "; ".join(reasons) if verdict == "INSUFFICIENT_DATA" and reasons else GATE_TEXT.get(verdict, verdict)
    stale = " · evidence stale: nothing here is current" if family_state == "STALE" else ""
    line = c.facts([
        ("EXP-002 pre-freeze gate", _pm_badge("EV_GATE", verdict)
         + _sub(f"{g.get('version')} · diagnostic only · as of {pr.datetime_et(g.get('as_of_utc')) or '—'} · inputs "
                f"{horizons.get('bound') or '—'} (bound), {', '.join(horizons.get('diagnostics') or []) or '—'} "
                f"(diagnostics){stale}")
         + _sub(f"{pr.count(counts.get('admissible_games')) or '0'} admissible T-6h game(s) of "
                f"{pr.count(counts.get('t6_due')) or '0'} due · {pr.count(counts.get('weeks')) or '0'} NFL week(s)")
         + _sub(why)),
        ("Outcome access", _gate_access(g.get("outcome_access"))),
        ("Freeze eligibility", _pm_badge("EV_FREEZE", freeze.get("state") or "NOT_ELIGIBLE")
         + _sub("separate from the gate: a diagnostic is never freeze eligibility")
         + _sub((freeze.get("reasons") or ["no reason recorded"])[0])),
    ], wide=True, text_cols=(0, 1, 2))
    table = c.table(
        ["delta_min", "tolerable bias", "bound, upper 90%", "bound state", "verdict"],
        [[c.num(pr.cents(r.get("min_effect"))), c.num(pr.cents(r.get("tolerable_bias"))),
          c.num(pr.cents(r.get("bound_upper_90")), reason="not estimable"),
          esc(str(r.get("bound_state") or "").replace("_", " ").capitalize()), _pm_state("EV_GATE", r.get("verdict"))]
         for r in (g.get("by_candidate_min_effect") or []) if isinstance(r, dict)],
        wrap=(3,), right=(0, 1, 2),
        caption="Conditional bias bound per candidate delta_min (delta_min is not frozen)")
    spreads = est.get("spreads_t6") if isinstance(est.get("spreads_t6"), dict) else {}
    details = c.kv([
        ("counts", esc(f"due T-6h {counts.get('t6_due', '—')} · admissible {counts.get('admissible_games', '—')} · not "
                       f"paired {counts.get('t6_not_paired', '—')} · one-sided or empty "
                       f"{counts.get('t6_book_one_sided_or_empty', '—')} · locked {counts.get('t6_book_locked', '—')} · "
                       f"crossed {counts.get('t6_book_crossed', '—')} · no consensus {counts.get('t6_no_consensus', '—')}"
                       f" · book-before-odds sides {counts.get('t6_admissible_book_before_odds', '—')} "
                       "(comparability only) · wide books (3¢ or more) " f"{counts.get('wide_books', '—')}")),
        ("T-6h spreads", esc(f"median {pr.cents(spreads.get('median')) or '—'} · max {pr.cents(spreads.get('max')) or '—'}"
                             f" over {spreads.get('n', 0)} books")),
        ("gaps inside the spread", c.num(pr.percent(est.get("share_gaps_within_spread")), reason="no admissible game")
         + _sub(f"gap SD {pr.cents(est.get('gap_sd')) or '—'} (consensus minus Kalshi mid, both books)")),
        ("same-capture dispersion", esc(f"{counts.get('dispersion_pairs', 0)} pairs · zero in "
                                        f"{pr.percent(est.get('share_dispersion_zero')) or '—'} · mirror quoting "
                                        f"{'yes' if est.get('mirror_quoting') else 'no'}")),
        ("why a spread is not a bound", esc(g.get("not_a_bound") or "")),
        ("not identifiable here", c.ul(g.get("unidentified") or [], empty="none recorded")),
        ("freeze blockers", c.ul(freeze.get("reasons") or [], empty="none recorded")),
    ])
    return line + c.disclosure(f"EXP-002 gate {g.get('version')} details (diagnostic only)", table + details)


def _ev_family_a(v: dict, now: Any) -> str:
    state = str(v.get("state") or "UNKNOWN")
    word = pr.prefixed_word("EV_STATE", state)
    den = v.get("denominators") if isinstance(v.get("denominators"), dict) else {}
    rel = v.get("relation") if isinstance(v.get("relation"), dict) else {}
    tier = rel.get("tier") or "NONE"
    protocol = v.get("protocol") if isinstance(v.get("protocol"), dict) else {}
    edge = v.get("edge_at_size") if isinstance(v.get("edge_at_size"), dict) else {}
    window = v.get("window") if isinstance(v.get("window"), dict) else {}
    waterfall = [w for w in (v.get("join_stages") or []) if isinstance(w, dict)]
    gaps = [g for g in (v.get("gaps") or []) if isinstance(g, dict)]
    top = max(waterfall, key=lambda w: (w.get("excluded") or 0), default=None)
    out = [f'<p class="eyebrow">{esc(v.get("label") or EV_LABEL)}</p>',
           f'<p class="meta">{c.badge(f"EV_STATE_{state}", label=word.label, kind=word.kind)} '
           f'{esc(v.get("title") or "Sportsbook consensus vs Kalshi NFL moneyline")} · NFL pregame moneyline · stored '
           'evidence only · no winner model</p>']
    if state in EV_STATE_TEXT:
        title, text = EV_STATE_TEXT[state]
        out.append(c.blocked_state(title, text) if state == "UNSUPPORTED" else
                   c.empty_state(title, text, kind="nd" if state == "EMPTY" else "warn"))
    first, last = window.get("first_receipt_utc"), window.get("last_receipt_utc")
    out.append(c.facts([
        ("Protocol", _pm_badge("EV_PROTOCOL", protocol.get("state")) + _sub(protocol.get("experiment_id")
                                                                           or protocol.get("detail"))),
        ("As of", c.txt(pr.datetime_et(v.get("as_of_utc")), reason="not recorded")
         + _sub(f"evidence received {pr.datetime_et(first)} to {pr.datetime_et(last)}" if first and last
                else "no evidence received")),
        ("Due horizons", c.num(pr.count(den.get("targets_due")), reason="not recorded")
         + _sub(f"{_ev_count(den, 'events_due') or '—'} games · {_ev_count(den, 'weeks_due') or '—'} NFL weeks · "
                f"{_ev_count(den, 'targets_not_yet_due') or '—'} not yet due · "
                f"{_ev_count(den, 'targets_superseded') or '—'} superseded")),
        ("Paired", c.num(f"{pr.count(v.get('paired_targets')) or '—'} of {pr.count(den.get('targets_due')) or '—'}")
         + _sub(f"{pr.count(v.get('partial_targets')) or '—'} partial · {pr.count(v.get('paired_games')) or '—'} games · "
                f"{pr.count(v.get('paired_weeks')) or '—'} weeks")),
        ("Largest exclusion", (_pm_state("EV_KIND", top.get("kind"), label=str(top.get("stage")).replace("_", " ")
                                         .capitalize())
                               + _sub(f"{pr.count(top.get('excluded'))} of {pr.count(top.get('of'))} · {top.get('text')}"))
         if top and top.get("excluded") else c.txt("none", reason="no exclusion")),
        ("Outcome labels", c.txt("Hidden · holdout protection")
         + _sub("EXP-002 labels (outcome states and results) are shown only by a report run logged in its "
                "evidence-use log, never here")),
        ("Probability / relation", _pm_badge("EV_REL", tier)
         + _sub("consensus: conditional on a decided game (book tie rules unverified) · Kalshi YES pays $0.50 on a "
                "tie")),
        ("Edge at a size", _pm_badge("EV_EDGE", edge.get("state"))
         + _sub((edge.get("reasons") or ["no reason recorded"])[0] if isinstance(edge.get("reasons"), list) else None)),
        ("Protocol-eligible", _ev_none(_ev(v, "protocol_attrition", "denominators", "eligible_opportunities"),
                                       "not enumerated: unknown, not zero")
         + _sub(f"of {pr.count(_ev(v, 'protocol_attrition', 'denominators', 'opportunities')) or '—'} opportunities · "
                "signals and fills not evaluated (no registered rule)")),
        ("Economic screen", _pm_badge("EV_SCREEN", _ev(v, "screen", "verdict"))
         + _sub((f"{pr.count(_ev(v, 'screen', 'episodes', 'episodes'))} episodes"
                 if _ev(v, "screen", "episodes", "episodes") is not None else
                 "episodes not evaluable (no frozen episode definition)") + " · no capital scenario supplied")),
        ("Next action", c.txt(v.get("next_action"), reason="none recorded") + _sub(
            f"blocker: {v['blocker']}" if v.get("blocker") else None)),
    ], wide=True, text_cols=tuple(range(11))))
    out.append(_ev_exp002_gate(v.get("exp002_gate"), state))
    out.append(c.disclosure(f"Join diagnostics over {pr.count(den.get('targets_due')) or '—'} due horizons", c.table(
        ["stage", "excluded", "remaining", "kind", "meaning"],
        [[esc(str(w.get("stage")).replace("_", " ").capitalize()), c.num(pr.count(w.get("excluded"))),
          c.num(pr.count(w.get("remaining_after"))), _pm_state("EV_KIND", w.get("kind")),
          esc(w.get("text"))] for w in waterfall], wrap=(0, 4), right=(1, 2),
        caption="Attrition waterfall: one primary reason per due horizon, every raw reason kept in the report")
        + f'<p class="meta">Denominators: {esc(_ev_count(den, "targets_planned") or "—")} planned horizons, '
          f'{esc(_ev_count(den, "events") or "—")} games, {esc(_ev_count(den, "kalshi_markets_mapped") or "—")} Kalshi '
          f'markets mapped, {esc(_ev_count(den, "odds_snapshots_used") or "—")} odds snapshots and '
          f'{esc(_ev_count(den, "kalshi_books_used") or "—")} Kalshi books used.</p>'))
    out.append(c.disclosure(f"Missing evidence ({pr.count(len(gaps))})", c.table(
        ["id", "stream", "state", "why", "smallest fix"],
        [[c.code(g.get("id")), esc(g.get("stream")), _pm_state("EV_GAP", g.get("state")), esc(g.get("why")),
          esc(g.get("smallest_fix"))] for g in gaps], wrap=(1, 3, 4), empty="no gap recorded",
        caption="Data gaps: exact missing streams and the smallest justified fix")))
    out.append(c.disclosure(f"Protocol attrition ({protocol.get('experiment_id') or 'no protocol'})",
                            _ev_protocol_attrition(v.get("protocol_attrition"))))
    out.append(c.disclosure("Economic screen", _ev_screen(v.get("screen"))))
    out.append(c.disclosure("Capacity and fill modes", _ev_capacity(v.get("capacity"))))
    inputs = [i for i in (v.get("inputs") or []) if isinstance(i, dict)]
    costs = [f for f in (v.get("fixed_costs") or []) if isinstance(f, dict)]
    out.append(c.disclosure("Costs and inputs", c.table(
        ["item", "cash / month", "basis", "detail"],
        [[esc(f.get("item")), c.num(pr.money(f.get("cash_per_month")), reason="unknown"),
          _pm_state("EV_BASIS", f.get("basis")), esc(f.get("detail"))] for f in costs], wrap=(0, 3),
        caption="Fixed costs, shown apart from any per-trade figure") + c.table(
        ["input", "value", "basis", "detail"],
        [[esc(i.get("name")), c.txt(", ".join(i["value"]) if isinstance(i.get("value"), list) else
                                    (str(i["value"]) if i.get("value") is not None else None), reason="not supplied"),
          _pm_state("EV_BASIS", i.get("basis")), esc(i.get("detail"))] for i in inputs], wrap=(0, 1, 3),
        caption="Economic inputs with their evidence class")))
    prov = v.get("provenance") if isinstance(v.get("provenance"), dict) else {}
    econ = v.get("economics_contract") if isinstance(v.get("economics_contract"), dict) else {}
    out.append(c.disclosure("Provenance, relation and sampling", c.kv([
        ("sportsbook source", esc(prov.get("odds"))),
        ("Kalshi rules (sha256)", c.ul(prov.get("kalshi_rules") or [], empty="no rules captured")),
        ("fees", esc(prov.get("fee"))),
        ("join", esc(prov.get("join"))),
        ("relation reasons", c.ul(rel.get("reasons") or [], empty="none")),
        ("sampling", esc(_ev(v, "sampling", "resolution"))),
        ("economics contract", c.code(econ.get("state")) + _sub(econ.get("detail"))),
        ("report sha256", c.code(v.get("report_sha256"))),
    ])))
    return "".join(out)


PAYOFF_LABEL = "PAYOFF RESEARCH — NOT A CAPTURED RESULT"
PAYOFF_NOTE = ("A proof is about contract payoffs; a claim is about stored books at one size. Nothing here was "
               "executed: legs are never assumed atomic and no fill is simulated. A conditional full-fill surplus is "
               "not captured arbitrage, and no other claim ever shows a positive figure.")
PAYOFF_LEGACY_NOTE = ("Set construction: legacy (every anchor). This scan built a set at every book receipt, so its "
                      "INVALID set counts include mid-round anchor artifacts; they are not comparable with per-round "
                      "results.")
PAYOFF_LEGACY_HASH_NOTE = ("Dataset hash: legacy definition (books of evaluated sets only). This file's input snapshot "
                           "hash is not comparable with a current-definition hash for the same store and window.")
PAYOFF_ROWS_SHOWN = 4  # newest evaluated sets shown as rows; every set is in the disclosure table
POSITIVE_CLAIM = "CONDITIONAL_FULL_FILL_SURPLUS"  # payoff_constraints.Claim: the only claim with a positive figure


def _source_badge(source: Any) -> str:
    return _pm_badge("EV_SOURCE", str(source).upper() if isinstance(source, str) else source)


def _payoff_settlement(size: dict) -> str:
    """Settlement costs from the evaluator's structured fields only (never its reason text):
    - a state it skipped (`states_skipped`) could not be valued because a refund rule is UNKNOWN;
    - an evaluated size with no `worst_state_surplus` and no skipped state has an UNKNOWN settlement cost;
    - otherwise every state was costed."""
    if not size.get("evaluated"):
        return c.na("not evaluated at this size")
    skipped = [str(s) for s in size.get("states_skipped") or []]
    if skipped:
        return c.state_text("EV_SETTLE_REFUND_UNKNOWN", kind=pr.WARN_K) + _sub(
            f"state(s) {', '.join(skipped)} not valued")
    if size.get("worst_state_surplus") is None:
        return c.state_text("EV_SETTLE_UNKNOWN", kind=pr.WARN_K)
    return c.txt("Costed by the evaluator")


def _settlement_fact(evaluated: list, refund_unknown: int, settle_unknown: int) -> str:
    """The section's settlement-cost fact, from the same structured fields as `_payoff_settlement`."""
    if not evaluated:
        return c.na("no size was evaluated, so no settlement cost was assessed")
    parts = []
    if settle_unknown:
        parts.append(c.state_text("EV_SETTLE_UNKNOWN", label="Unknown", kind=pr.WARN_K)
                     + _sub(f"{pr.count(settle_unknown)} evaluated size(s): settlement cost not yet verified, "
                            "so surpluses after all costs cannot be stated"))
    if refund_unknown:
        parts.append(c.state_text("EV_SETTLE_REFUND_UNKNOWN", kind=pr.WARN_K)
                     + _sub(f"{pr.count(refund_unknown)} evaluated size(s): a state could not be valued"))
    return "".join(parts) or c.txt("Costed by the evaluator where evaluated")


def _payoff_surplus(size: dict) -> str:
    """A figure only for the evaluator's own positive claim (its claim-adjusted surplus); every other claim
    reads its claim, not a number."""
    if size.get("claim") == POSITIVE_CLAIM:
        return c.num(pr.money(size.get("claim_adjusted_surplus")),
                     reason="the evaluator stated no claim-adjusted figure") + _sub(
            "conditional on every leg filling · not captured arbitrage")
    return c.na("no positive claim: the evaluator made none at this size")


def _orphan_amount(value: Any) -> str:
    """A leg that fills alone, as an unsigned exposure: the worst-state loss, or none. A gain is never shown."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "unknown"
    if not amount.is_finite():
        return "unknown"
    return f"{pr.money(-amount)} worst-state loss" if amount < 0 else "no worst-state loss"


def _payoff_orphans(size: dict) -> str:
    orphans = size.get("orphan_exposure") if isinstance(size.get("orphan_exposure"), dict) else {}
    if not orphans:
        return c.na("no leg evaluated alone at this size")
    return c.ul([f"{leg}: {_orphan_amount(v) if v is not None else 'unknown'}" for leg, v in sorted(orphans.items())])


def _payoff_set(e: dict) -> str:
    sizes = [s for s in e.get("sizes") or [] if isinstance(s, dict)]
    rows = [[c.num(pr.quantity(s.get("basket_quantity"))), _pm_state("EV_CLAIM", s.get("claim")),
             esc("; ".join(str(r) for r in s.get("claim_reasons") or []) or "—"),
             c.num(pr.money(s.get("acquisition_cost")), reason="not priced at this size"),
             _payoff_settlement(s), _payoff_surplus(s)] for s in sizes]
    table = c.table(["basket", "claim", "reasons (NOT_EVALUATED included)", "all-in acquisition cost",
                     "settlement costs", "surplus"], rows, wrap=(1, 2, 4, 5), right=(0, 3),
                    caption=f"Claims per size for {e.get('set_id')}") if sizes else c.empty_state(
        "No size evaluated for this set", "The evaluator made no claim at any size: quotes "
        + str(e.get("quote_validity") or "not recorded").lower() + " ("
        + ("; ".join(str(r) for r in e.get("quote_reasons") or []) or "no reason recorded") + ").", kind="nd")
    orphans = c.table(["basket", "orphan-leg exposure (a leg that fills alone: its worst-state loss after its cost)"],
                      [[c.num(pr.quantity(s.get("basket_quantity"))), _payoff_orphans(s)] for s in sizes],
                      wrap=(1,), right=(0,), caption=f"Orphan-leg exposure for {e.get('set_id')}")
    head = c.facts([
        ("Proof", _pm_badge("EV_PROOF", e.get("relationship"))
         + _sub((e.get("relationship_reasons") or [None])[0])),
        ("As of", c.txt(pr.datetime_et(e.get("as_of_utc")), reason="not recorded")),
        ("Quotes", _pm_badge("EV_QUOTES", e.get("quote_validity"))
         + _sub((e.get("quote_reasons") or [None])[0])),
        ("Kind", c.txt(str(e.get("kind") or "").replace("_", " ").lower() or None, reason="not recorded")),
    ], wide=True, text_cols=(0, 1, 2, 3))
    # A heading, not a row: a row's aside column would narrow the claims table on phones.
    return (f'<h4 class="eyebrow">{esc(str(e.get("set_id") or "set"))}</h4>' + head + table
            + c.disclosure("Orphan-leg exposure", orphans)
            + c.disclosure("Proof reasons and assumptions", c.ul(
                [str(r) for r in (e.get("relationship_reasons") or []) + (e.get("assumptions") or [])],
                empty="none recorded")))


def _payoff_method(v: dict[str, Any], key: str) -> str:
    """A method value read by payoff_constraints' helper, or unavailable with the helper's problem."""
    value = v.get(key)
    if not value:
        return c.na(str(v.get(f"{key}_problem") or "not recorded"))
    return c.code(value) + (" (legacy)" if v.get(f"{key}_legacy") else "")


def _payoff_view(v: dict, now: Any) -> str:
    state = str(v.get("state") or "UNKNOWN")
    out = [f'<p class="eyebrow">{esc(PAYOFF_LABEL)}</p>']
    if state == "BLOCKED":
        return "".join(out) + c.blocked_state("EXP-003 results not shown", str(v.get("detail") or "blocked"))
    if state == "EMPTY":
        return "".join(out) + c.empty_state("No EXP-003 result recorded yet", str(v.get("detail") or "")
                                            + ". A result appears after a logged payoff-scan run adds a file.")
    result = v.get("result") if isinstance(v.get("result"), dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    prov = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
    source = prov.get("source_store")
    evaluations = sorted([e for e in report.get("evaluations") or [] if isinstance(e, dict)],
                         key=lambda e: str(e.get("as_of_utc")), reverse=True)
    sizes = [s for e in evaluations for s in e.get("sizes") or [] if isinstance(s, dict)]
    positive = sum(1 for s in sizes if s.get("claim") == POSITIVE_CLAIM)
    evaluated = [s for s in sizes if s.get("evaluated")]
    refund_unknown = sum(1 for s in evaluated if s.get("states_skipped"))
    settle_unknown = sum(1 for s in evaluated if not s.get("states_skipped") and s.get("worst_state_surplus") is None)
    out.append(f'<p class="meta">{_source_badge(source)} {_pm_badge("EV_BSTATE", state)} '
               f'{esc(report.get("series") or "")} · file {esc(v.get("file"))}</p>')
    if source != "production":
        out.append(c.empty_state("Not production evidence", f"This result was computed from a {source or 'unnamed'} "
                                 "store, not the production evidence store. It shows how the evaluator behaves; it "
                                 "is not evidence about production books.", kind="warn"))
    if state == "STALE":
        out.append(c.empty_state("Result is stale", f"The newest evaluation is older than {v.get('stale_after_days')} "
                                 "days. Nothing here is current.", kind="warn"))
    if v.get("set_construction_legacy"):
        out.append(f'<p class="note">{esc(PAYOFF_LEGACY_NOTE)}</p>')
    if v.get("input_hash_definition_legacy"):
        out.append(f'<p class="note">{esc(PAYOFF_LEGACY_HASH_NOTE)}</p>')
    counts = report.get("relationship_counts") if isinstance(report.get("relationship_counts"), dict) else {}
    claims = report.get("claim_counts_by_size_row") if isinstance(report.get("claim_counts_by_size_row"), dict) else {}
    out.append(c.facts([
        ("Source", _source_badge(source) + _sub(f"generated {pr.datetime_et(prov.get('generated_at_utc')) or '—'}")),
        ("As of", c.txt(pr.datetime_et(v.get("as_of_utc")), reason="not recorded")
         + _sub(f"event window {' to '.join(str(x) for x in prov.get('event_window') or []) or '—'}")),
        ("Sets", c.num(pr.count(report.get("sets_evaluated")), reason="not recorded")
         + _sub(f"{pr.count(len(report.get('sets_skipped') or []))} skipped · {pr.count(report.get('events'))} events")),
        ("Proof completeness", c.txt(" · ".join(f"{k.lower()} {pr.count(n)}" for k, n in sorted(counts.items()))
                                     or None, reason="no set evaluated")),
        ("Claims (set × size)", c.txt(" · ".join(f"{k.replace('_', ' ').lower()} {pr.count(n)}"
                                                 for k, n in sorted(claims.items())) or None, reason="none")),
        ("Settlement costs", _settlement_fact(evaluated, refund_unknown, settle_unknown)),
        ("Positive claims", c.num(pr.count(positive)) + _sub("conditional full-fill surplus only · never captured")),
        ("Execution", c.txt("None") + _sub(str(report.get("actual_result") or "no fills"))),
    ], wide=True, text_cols=(0, 1, 3, 4, 5, 7)))
    shown = evaluations[:PAYOFF_ROWS_SHOWN]
    out.append("".join(_payoff_set(e) for e in shown) if shown else
               c.empty_state("No set evaluated", "The scan found no complete, time-overlapping book set.", kind="nd"))
    if evaluations:
        out.append(c.disclosure(f"All evaluated sets ({pr.count(len(evaluations))})", c.table(
            ["set", "as of", "proof", "quotes", "claims by size"],
            [[esc(e.get("set_id")), esc(pr.datetime_et(e.get("as_of_utc")) or "—"), _pm_state("EV_PROOF", e.get("relationship")),
              _pm_state("EV_QUOTES", e.get("quote_validity")),
              esc(" · ".join(f"{s.get('basket_quantity')}: {str(s.get('claim')).replace('_', ' ').lower()}"
                             for s in e.get("sizes") or [] if isinstance(s, dict)))] for e in evaluations],
            wrap=(0, 4), caption="Every evaluated set in the result file")))
    skipped = [s for s in report.get("sets_skipped") or [] if isinstance(s, dict)]
    if skipped:
        out.append(c.disclosure(f"Skipped sets ({pr.count(len(skipped))})", c.table(
            ["event", "as of", "reason"], [[esc(s.get("event")), esc(s.get("as_of")), esc(s.get("reason"))]
                                           for s in skipped], wrap=(2,), caption="Sets the scan skipped")))
    identity = prov.get("store_identity") if isinstance(prov.get("store_identity"), dict) else {}
    out.append(c.disclosure("Provenance and verification", c.kv([
        ("file", c.code(v.get("file"))), ("verification", esc(v.get("verification"))),
        ("store-provenance sidecar", c.code(v.get("sidecar")) if v.get("sidecar") else c.na("no sidecar beside "
                                                                                             "this result")),
        ("set construction", _payoff_method(v, "set_construction")),
        ("input hash definition", _payoff_method(v, "input_hash_definition")),
        ("source store", _source_badge(source)),
        ("store identity", esc(", ".join(f"{k} {val}" for k, val in sorted(identity.items())) or "—")),
        ("code version", c.code(prov.get("code_version"))), ("generated", esc(prov.get("generated_at_utc"))),
        ("event window", esc(" to ".join(str(x) for x in prov.get("event_window") or []))),
        ("evidence-use event", c.code(prov.get("evidence_use_event_id"))),
        ("scan parameters", esc(f"sizes {', '.join(str(s) for s in report.get('sizes') or [])} · max quote age "
                                f"{report.get('max_quote_age_seconds')} s · max leg skew "
                                f"{report.get('max_leg_skew_seconds')} s (stated per run; protocol values UNKNOWN)")),
        ("settled fields never read", c.ul(report.get("prohibited_fields_never_read") or [], empty="not declared")),
        ("simulated execution", esc(report.get("simulated_execution"))),
        ("report sha256", c.code(report.get("report_sha256"))), ("envelope sha256", c.code(result.get("envelope_sha256"))),
        ("page views", esc("read-only: this display writes no evidence-use event (a registered known unlogged "
                           "consumer); the producing run logged its own")),
        ("other files", c.ul(v.get("unreadable") or [], empty="none unreadable")),
    ])))
    out.append(f'<p class="note">{esc(PAYOFF_NOTE)}</p>')
    return "".join(out)


def family_b_body(result: d.Loaded, now: Any = None) -> str:
    """Family B in every state: populated, stale, empty, blocked, error (unreadable / unverified), unknown
    (evaluator or registry unavailable), malformed. Every figure is the result file's own, only formatted."""
    if result.status == d.ERROR:
        return c.error_state("Family B unavailable (read error)", f"ERROR — {result.message}. This is not an empty "
                                                                  "result.")
    if result.status != d.OK:
        return (f'<p class="meta">{c.badge("EV_STATE_NOT_AVAILABLE")} Same-venue payoff consistency · Kalshi '
                "complements, partitions and nested thresholds · no EXP-001 data</p>"
                + c.unavailable("Not yet available", result.message[:1].upper() + result.message[1:] + ". No payoff "
                                "proof, conditional surplus or captured result is shown."))
    try:
        return _payoff_view(result.value, now)
    except Exception as exc:  # noqa: BLE001 - a malformed result is an error here, never a failed page
        return c.error_state("Family B unavailable (malformed result)", f"ERROR — {d.short_error(exc)}.")


def family_a_body(result: d.Loaded, now: Any) -> str:
    """Family A in every state: populated, partial, stale, empty, unsupported, unknown (not configured or not
    readable), error, malformed."""
    if result.status == d.ERROR:
        return c.error_state("Family A unavailable (read error)", f"ERROR — {result.message}. This is not an empty "
                                                                  "result.")
    if result.status != d.OK:
        return (f'<p class="meta">{c.badge("EV_STATE_UNKNOWN")} Family A</p>'
                + c.unavailable("Family A evidence unknown", result.message[:1].upper() + result.message[1:]
                                + ". Nothing is known here, which is not the same as nothing recorded."))
    try:
        return _ev_family_a(result.value, now)
    except Exception as exc:  # noqa: BLE001 - a malformed view is an error here, never a failed page
        return c.error_state("Family A unavailable (malformed view)", f"ERROR — {d.short_error(exc)}.")


def economics_body(a: d.Loaded, b: d.Loaded, now: Any) -> str:
    """Both families in one body (the gallery); the page uses one section per family (`economics_section`)."""
    return (f'<p class="note">{esc(EV_NOTE)}</p><h3 class="eyebrow">Family A</h3>' + family_a_body(a, now)
            + '<h3 class="eyebrow">Family B</h3>' + family_b_body(b, now))


def economics_section(ctx: d.Context) -> str:
    """Research tab, after the experiments: one section per research family (no new navigation)."""
    return (c.section("Economic evidence · A", f'<p class="note">{esc(EV_NOTE)}</p>'
                      + family_a_body(ctx.economic_a, ctx.now),
                      meta="Sportsbook consensus vs Kalshi NFL · research only · no edge claimed", sid="ev-h")
            + c.section("Economic evidence · B", family_b_body(ctx.economic_b, ctx.now),
                        meta="Same-venue payoff consistency · research only", sid="ev-b-h"))


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
    out.append(pm_related_section(ctx))
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
