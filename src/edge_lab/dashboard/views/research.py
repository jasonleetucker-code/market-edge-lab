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
        ("Books", c.num(pr.count(o.book_count))
         + _sub(f"contributing · {pr.count(p.market_bookmaker_count)} quoting this market (any line)")),
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


# --------------------------------------------------------------------------- Polymarket US related markets (ADR 0032)

PM_LABEL = "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"  # polymarket_sports.LABEL (tested equal)
PM_NOTE = ("A related Polymarket US market shares the league, both teams and the kickoff; its contract is not "
           "proven equal to any sportsbook's (payout structure differs; rule dimensions unverified), so it is never "
           "ranked, never compared as cheaper and never executable. A research book capture is evidence of one "
           "moment, not a price to act on. A listing that is partial, stale or not yet read says nothing about "
           "whether a market exists.")
PM_UNCHECKED = ("NO_SCAN", "FAILED")  # no usable scan: nothing has been looked for


def _pm(v: Any, key: str) -> Any:
    return v.get(key) if isinstance(v, dict) else None


def _pm_word(prefix: str, code: Any) -> pr.StateWord:
    """The PM_* state word for a code; a code the family does not know is neutral with its own text."""
    known = pr.STATES.get(f"{prefix}_{code}")
    if known is not None:
        return known
    if code is None:
        return pr.StateWord("Not recorded", pr.ND_K)
    text = str(code)
    return pr.StateWord(text.replace("_", " ").capitalize() if text.isupper() else text, pr.ND_K)


def _pm_badge(prefix: str, code: Any) -> str:
    word = _pm_word(prefix, code)
    return c.badge(code, label=word.label, kind=word.kind)


def pm_event_state(event: Any, catalog_state: Any) -> tuple[str, pr.StateWord]:
    """The event's relationship state as shown: no related market reads as "not checked" when there is
    no usable scan, and says the listing is partial or stale otherwise (absence is never evidence)."""
    state = _pm(event, "state")
    if state == "NO_RELATED_MARKET":
        if catalog_state in PM_UNCHECKED:
            return "PM_EVENT_NOT_CHECKED", _pm_word("PM_EVENT", "NOT_CHECKED")
        if catalog_state in ("PARTIAL_CATALOG", "STALE"):
            return "PM_EVENT_NONE_IN_PARTIAL", _pm_word("PM_EVENT", "NONE_IN_PARTIAL")
    return str(state), _pm_word("PM_EVENT", state)


def _pm_capture(cap: Any, source: str, now: Any) -> str:
    if not isinstance(cap, dict):
        return c.na("no research book captured yet")
    fresh = pr.freshness_code(cap.get("freshness"))
    bid, ask = pr.cents(cap.get("yes_bid")), pr.cents(cap.get("yes_ask"))
    return (c.num(f"YES bid {bid or '—'}") + " · " + c.num(f"YES ask {ask or '—'}")
            + _sub(f"sizes {pr.quantity(cap.get('yes_bid_size')) or '—'} / {pr.quantity(cap.get('yes_ask_size')) or '—'} "
                   "contracts")
            + _sub(f"received {pr.datetime_et(cap.get('received_at_utc')) or 'at an unrecorded time'}"
                   + (f" ({pr.age_text(cap.get('received_at_utc'), now)})" if pr.age_text(cap.get('received_at_utc'), now)
                      else "") + " · research capture, not current")
            # Timing quality of one research capture, never a signal about the price: not green.
            + c.state_text(fresh, label=f"{pr.state_word(fresh).label} at capture (its target window)",
                           kind=pr.INFO_K if fresh == "FRESH" else pr.state_word(fresh).kind)
            + _sub(f"{_pm(cap, 'label') or 'research book capture'} · {source}"))


def _pm_targets(history: Any) -> str:
    if not isinstance(history, list) or not history:
        return c.na("no capture target planned for this market")
    return " ".join(c.state_text(f"PM_TARGET_{t.get('state')}", label=f"{t.get('offset')} "
                                 f"{_pm_word('PM_TARGET', t.get('state')).label}",
                                 kind=_pm_word("PM_TARGET", t.get("state")).kind)
                    for t in history if isinstance(t, dict))


def pm_market_block(m: Any, source: str, history: Any, now: Any) -> str:
    """One related (or ambiguous) Polymarket US market: relationship with reasons and checks, the latest
    research book capture with attribution, the capture targets' states; nothing is ranked or priced
    against a sportsbook."""
    checks = _pm(m, "checks") if isinstance(_pm(m, "checks"), dict) else {}
    rows = [[esc(name.replace("_", " ")), _pm_badge("PM_CHECK", _pm(v, "state")), esc(_pm(v, "detail") or "—")]
            for name, v in checks.items()]
    attempts = [a for t in history or [] if isinstance(t, dict) for a in t.get("attempts") or [] if isinstance(a, dict)]
    body = c.facts([
        ("Relationship", _pm_badge("PM_EVENT", _pm(m, "relationship")) + _sub("; ".join(
            str(r) for r in _pm(m, "reasons") or [] if isinstance(r, str)) or None)),
        ("Latest research book", _pm_capture(_pm(m, "latest_capture"), source, now)),
        ("Capture targets", _pm_targets(history)),
        ("Sides (as listed)", esc(f"long {_pm(m, 'long_side') or '—'} · short {_pm(m, 'short_side') or '—'}")),
    ], wide=True, text_cols=(0, 1, 2, 3))
    detail = c.disclosure("Relationship checks, flags and attempts", c.kv([
        ("market", c.code(_pm(m, "market_slug"))), ("title", esc(_pm(m, "title") or "—")),
        ("game start (UTC)", c.code(_pm(m, "game_start_utc"))), ("payoff kind", c.code(_pm(m, "payoff_kind"))),
        ("rules sha256", c.code(_pm(m, "rules_sha256"))),
        ("flags", c.ul([str(f) for f in _pm(m, "flags") or []], empty="none")),
        ("equivalent", esc("never (by construction)")),
        ("source", esc(source)),
    ]) + c.table(["dimension", "state", "detail"], rows, wrap=(2,), caption="Relationship checks")
      + c.table(["target", "status", "received", "YES bid", "YES ask", "reason"],
                [[c.code(a.get("target_id")), c.state_text(f"PM_TARGET_{a.get('status')}",
                                                            label=_pm_word("PM_TARGET", a.get("status")).label,
                                                            kind=_pm_word("PM_TARGET", a.get("status")).kind),
                  esc(pr.datetime_et(a.get("received_at_utc")) or "—"), c.num(pr.cents(a.get("yes_bid")), reason="none"),
                  c.num(pr.cents(a.get("yes_ask")), reason="none"), esc(d.scrub_paths(a.get("reason")) or "—")]
                 for a in attempts], wrap=(5,), caption="Capture attempts", empty="no attempt recorded"))
    title = esc(_pm(m, "title") or _pm(m, "market_slug") or "Polymarket US market")
    return f'<h4 class="eyebrow">{title}</h4>' + body + detail


def pm_event_row(event: Any, catalog_state: Any, source: str, histories: Any, now: Any) -> str:
    code, word = pm_event_state(event, catalog_state)
    markets = [m for m in _pm(event, "markets") or [] if isinstance(m, dict)]
    body = "".join(pm_market_block(m, source, (histories or {}).get(_pm(m, "market_slug")), now) for m in markets)
    if not markets:
        body = f'<p class="row-sub">{esc(PM_EVENT_EMPTY.get(code, "No related market in the listing read."))}</p>'
    sub = f"kickoff {pr.datetime_et(_pm(event, 'commence_utc')) or 'not recorded'} · Odds API event {_pm(event, 'odds_event_id')}"
    # The aside capsule never wraps, so it carries a short word; the full label leads the row body.
    lead = f'<p class="eyebrow">{esc(word.label)}</p>'
    return c.row(esc(pr.odds_event_label(_pm(event, "away_team"), _pm(event, "home_team"), _pm(event, "odds_event_id"))),
                 sub=sub, aside=c.badge(code, label=PM_SHORT.get(code, word.label), kind=word.kind),
                 body=f"<div>{lead}{body}</div>")


PM_SHORT = {"RELATED_NOT_EQUIVALENT": "Related", "AMBIGUOUS": "Ambiguous", "NO_RELATED_MARKET": "None seen",
            "PM_EVENT_NONE_IN_PARTIAL": "None seen", "PM_EVENT_NOT_CHECKED": "Not checked"}


PM_EVENT_EMPTY = {
    "PM_EVENT_NOT_CHECKED": "Not looked for yet: no usable Polymarket US scan exists. This says nothing about whether "
                            "a market exists.",
    "PM_EVENT_NONE_IN_PARTIAL": "None in the listing read, but that listing is partial or stale: absence is not "
                                "evidence.",
    "NO_RELATED_MARKET": "None in the filtered NFL moneyline listing read (a filtered listing, never the full catalog: "
                         "absence is not evidence).",
}


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
    out.append(c.facts([
        ("Access", _pm_badge("PM_ACCESS", access) + _sub(f"decision: {_pm(status, 'access_decision')}"
                                                         if _pm(status, "access_decision") else None)),
        ("Catalog", _pm_badge("PM_CATALOG", cstate)
         + _sub(f"{pr.count(_pm(catalog, 'markets'))} markets · scan {pr.datetime_et(_pm(catalog, 'usable_scan_utc'))}"
                if _pm(catalog, "usable_scan_utc") else _pm(catalog, "detail"))
         + _sub(_pm(catalog, "coverage_note") if isinstance(_pm(catalog, "coverage_note"), str) else None)),
        ("Last scan attempt", c.txt(pr.datetime_et(_pm(catalog, "last_attempt_utc")), reason="none")
         + _sub(" · ".join(str(x) for x in (_pm(catalog, "last_attempt_coverage"), _pm(catalog, "last_attempt_detail"))
                           if isinstance(x, str) and x) or None)),
        ("Next discovery", c.txt(pr.datetime_et(_pm(status, "discovery_next_due_utc")), reason="not scheduled")),
    ], wide=True, text_cols=(0, 1, 2, 3)))
    return "".join(out)


def pm_related_body(result: d.Loaded, now: Any, event_ids: Any = (), histories: Any = None) -> str:
    """Every state: populated (related, ambiguous, none), no scan, partial or stale catalog, gate blocked,
    capture captured / missed / failed / not executable, error, source unavailable."""
    if result.status == d.ERROR:
        return c.error_state("Polymarket US related markets unavailable (read error)",
                             f"ERROR — {result.message}. This is not an empty listing.")
    if result.status != d.OK:
        return c.unavailable("Polymarket US related markets unavailable", result.message[:1].upper()
                             + result.message[1:] + ".")
    view = result.value
    related = _pm(view, "related") if isinstance(_pm(view, "related"), dict) else {}
    source = str(_pm(view, "source") or _pm(related, "source") or "source not recorded")
    catalog_state = _pm(_pm(_pm(view, "status"), "catalog"), "state")
    events = _pm(related, "events") if isinstance(_pm(related, "events"), dict) else {}
    out = [f'<p class="eyebrow">{esc(_pm(view, "label") or PM_LABEL)}</p>', _pm_header(view, now)]
    if not events:
        out.append(c.empty_state("No Odds API NFL schedule stored", "Relationships are made per Odds API event; no "
                                 "stored schedule was found."))
    else:
        wanted = [e for e in event_ids if e in events][:d.PM_EVENTS_SHOWN] or sorted(
            events, key=lambda k: str(_pm(events[k], "commence_utc")))[:d.PM_EVENTS_SHOWN]
        out.append('<ul class="rows">' + "".join(pm_event_row(events[e], catalog_state, source, histories, now)
                                                 for e in wanted) + "</ul>")
        table = c.table(["event", "kickoff", "state", "market", "latest YES bid · ask", "received"], [
            [esc(pr.odds_event_label(_pm(e, "away_team"), _pm(e, "home_team"), _pm(e, "odds_event_id"))),
             esc(pr.datetime_et(_pm(e, "commence_utc")) or "—"),
             c.state_text(pm_event_state(e, catalog_state)[0], label=pm_event_state(e, catalog_state)[1].label,
                          kind=pm_event_state(e, catalog_state)[1].kind),
             c.ul([str(_pm(m, "market_slug")) for m in _pm(e, "markets") or [] if isinstance(m, dict)], empty="—"),
             esc(" / ".join(f"{pr.cents(_pm(_pm(m, 'latest_capture'), 'yes_bid')) or '—'} · "
                            f"{pr.cents(_pm(_pm(m, 'latest_capture'), 'yes_ask')) or '—'}"
                            for m in _pm(e, "markets") or [] if isinstance(m, dict) and _pm(m, "latest_capture"))
                 or "—"),
             esc(" / ".join(pr.datetime_et(_pm(_pm(m, "latest_capture"), "received_at_utc")) or "—"
                            for m in _pm(e, "markets") or [] if isinstance(m, dict) and _pm(m, "latest_capture"))
                 or "—")]
            for e in sorted(events.values(), key=lambda e: str(_pm(e, "commence_utc")))], wrap=(0, 3),
            caption="Polymarket US relationships per Odds API event")
        out.append(c.disclosure(f"All Odds API events ({pr.count(len(events))})", table, boxed=True))
    out.append(f'<p class="note">{esc(PM_NOTE)} Source: {esc(source)}.</p>')
    return "".join(x for x in out if x)


def pm_event_states(result: d.Loaded) -> dict[str, tuple[str, pr.StateWord]] | None:
    """Odds API event id -> the relationship state shown for it (None when the view is not readable)."""
    if result.status != d.OK:
        return None
    events = _pm(_pm(result.value, "related"), "events")
    catalog_state = _pm(_pm(_pm(result.value, "status"), "catalog"), "state")
    return {k: pm_event_state(e, catalog_state) for k, e in events.items()} if isinstance(events, dict) else None


def pm_related_section(ctx: d.Context) -> str:
    """After the Odds capture targets: the events of the rows shown there first, then the rest."""
    result = ctx.pm_sports
    ids: list[str] = []
    if ctx.odds_targets.status == d.OK:
        for t in (*ctx.odds_targets.value.recent, *ctx.odds_targets.value.upcoming):
            if t.event_id not in ids:
                ids.append(t.event_id)
    histories = None
    if result.status == d.OK:
        events = _pm(_pm(result.value, "related"), "events") or {}
        shown = [e for e in ids if e in events][:d.PM_EVENTS_SHOWN]
        slugs = sorted({_pm(m, "market_slug") for e in shown for m in _pm(events[e], "markets") or []
                        if isinstance(_pm(m, "market_slug"), str)})
        loaded = d.pm_market_history(ctx, slugs)
        histories = loaded.value if loaded.status == d.OK else None
    return c.section("Polymarket US related markets", pm_related_body(result, ctx.now, ids, histories),
                     meta="NFL moneyline · research only · never ranked",
                     sid="pm-h")


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
