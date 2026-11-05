"""News & political intelligence workspace (/experiments/intel) and its research packet page (issue 192, ADR 0049).

Formats `intel.view.IntelView` (built by `data.Context.intel_view` over the read-only store) with the shared
components. It computes nothing financial: every price, fee, EV, maximum price and action is the stored decision
sheet's own value, formatted by `presentation`. Honesty rules (owner refinement 3):
- every section names its provenance: COLLECTED, CLASSIFIED, IMPORTED AI ANALYSIS, OWNER JUDGMENT, PROVISIONAL
  FORECAST, and ECONOMICS as ESTIMATE / FEE UNSUPPORTED / VERIFIED (only with a claimable fee: none today);
- the actions are INVESTIGATE / WATCH / SKIP / INSUFFICIENT EVIDENCE: there is no buy, and nothing is green;
- a decision older than the pricing policy's book age is shown as not current, with a refresh;
- forms exist only when the dashboard was started with an inbox (`--intel-inbox`); they drop one file into the
  private inbox through the single POST route (`app.py`). When the collector is not running they still queue and
  say so: a submission waits, it is never silently lost and the button is never dead.

It lives under Research & Data (nav "research"); no global navigation item is added.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlencode

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

PATH = pr.INTEL_PATH
PACKET_PATH = pr.INTEL_PACKET_PATH
TITLE = "News & political intelligence"

ACTION_WORDS = {  # never green: research leads, not results
    "INVESTIGATE": ("Investigate · not a trade", "info"), "WATCH": ("Watch", "nd"), "SKIP": ("Skip", "nd"),
    "INSUFFICIENT_EVIDENCE": ("Insufficient evidence", "warn"),
}
EVENT_WORDS = {
    "NEW": ("New", "nd"), "RESEARCHING": ("Researching", "info"), "VERIFIED": ("Verified evidence", "info"),
    "NEEDS_EVIDENCE": ("Needs evidence", "warn"), "FORECAST_READY": ("Forecast recorded", "info"),
    "MONITOR": ("Monitor", "nd"), "RESOLVED": ("Resolved", "nd"),
}
VERIFICATION_WORDS = {
    "CONFIRMED_PRIMARY": ("Primary source", "info"), "CORROBORATED": ("Corroborated", "info"),
    "SINGLE_SOURCE": ("Single source", "warn"), "UNVERIFIED": ("Unverified", "nd"),
    "CONTRADICTED": ("Contradicted", "warn"),
}
SOURCE_WORDS = {
    "ACTIVE": ("Active · verified feed", "info"), "LIMITED": ("Limited · headlines only", "info"),
    "UNAVAILABLE": ("Unavailable", "nd"), "BLOCKED": ("Blocked", "warn"), "UNVERIFIED": ("Unverified", "nd"),
}
INBOX_WORDS = {"QUEUED": ("Queued", "info"), "DONE": ("Done", "nd"), "REJECTED": ("Rejected", "warn"),
               "REFUSED": ("Refused", "warn")}
HORIZON_WORDS = {"ALIGNED": ("Horizon matches close", "nd"), "MISMATCH": ("Horizon ≠ market close", "warn"),
                 "UNKNOWN": ("Horizon check unknown", "nd")}
HYPOTHETICAL_LINE = "HYPOTHETICAL RESEARCH DECISION — no order, no fill, not a recommendation to trade"
CATEGORY_TITLES = (("POLITICS", "Politics"), ("FINANCE", "Finance & economy"), ("PRIMARY", "Primary sources"),
                   ("GENERAL", "General news"))
ITEMS_PER_CATEGORY = 8
KIND_WORDS = {"transcript": "Transcript", "analysis": "Analysis", "refresh": "Refresh", "link": "Market link",
              "packet": "Research packet"}


def _row(title_html: str, *, sub: str = "", aside: str = "", body: str = "") -> str:
    """The canonical row with its body in one full-width block. `.row` is a two-column grid, and loose
    body elements would land in the narrow aside column and squeeze the title (seen at 390 px)."""
    return c.row(title_html, sub=sub, aside=aside, body=f'<div class="row-body">{body}</div>' if body else "")


def _word(table: Mapping[str, tuple[str, str]], code: Any, prefix: str, *, capsule: bool = True) -> str:
    label, kind = table.get(code, (str(code).replace("_", " ").capitalize() if code else "Not recorded", "nd"))
    fn = c.badge if capsule else c.state_text
    return fn(f"{prefix}_{code}", label=label, kind=kind)


def _label(text: str) -> str:
    """A provenance label: a short eyebrow, plain words, never a colour alone."""
    return f'<p class="eyebrow">{esc(text)}</p>'


def _when(ts: Any, reason: str = "time not recorded") -> str:
    return c.txt(pr.datetime_et(ts), reason=reason)


def _ext(url: str | None, text: str) -> str:
    """An external link, only for an http(s) URL (checked by `intel.view.safe_link`); text otherwise."""
    from ...intel.view import safe_link

    url = safe_link(url) if url else None
    if not url:
        return esc(text)
    return (f'<a class="link" href="{esc(url)}" rel="noopener noreferrer" target="_blank">{esc(text)}'
            f'{c.icon("external-link", "ic-sm", label="opens the source site")}</a>')


def href(tab: str | None = None, *, event: str | None = None) -> str:
    q = {k: v for k, v in (("tab", tab if tab != "today" else None), ("event", event)) if v}
    return PATH + ("?" + urlencode(q) if q else "")


def packet_href(event_id: str) -> str:
    return PACKET_PATH + "?" + urlencode({"event": event_id})


def _crumb() -> str:
    return f'<a class="crumb" href="/experiments">{c.icon("arrow-left", "ic-sm")}<span>Research &amp; Data</span></a>'


def basis_text(basis: Any) -> str:
    return "OWNER JUDGMENT (unvalidated)" if basis == "OWNER_JUDGMENT" else "IMPORTED AI ANALYSIS (unvalidated)"


def _range(fc: Mapping[str, Any] | None) -> str | None:
    if not fc or fc.get("abstained") or fc.get("point") is None:
        return None
    lo, hi = pr.percent(fc.get("low")), pr.percent(fc.get("high"))
    point = pr.percent(fc.get("point"))
    return f"{point} (range {lo}–{hi})" if lo and hi else f"{point} (no range given)"


# --------------------------------------------------------------------------- the forms (inbox enabled only)


class Forms:
    """Builds inbox forms for one request; returns "" for every form when submissions are not enabled."""

    def __init__(self, ctx: d.Context, view: Any) -> None:
        self.enabled = bool(ctx.config.intel_inbox is not None and ctx.form_token and view.inbox.configured)
        self.token = ctx.form_token or ""
        self.processor = view.processor

    def form(self, kind: str, body: str, **kw: Any) -> str:
        return c.inbox_form(self.token, kind, body, **kw) if self.enabled else ""

    def refresh(self, scope: str, text: str, *, back: str, event: str | None = None, outcome: str | None = None,
                label: str) -> str:
        return self.form("refresh", "", submit=text, label=label, inline=True,
                         hidden={"scope": scope, "event_id": event, "outcome_id": outcome, "return_tab": back,
                                 "return_event": event})

    def packet(self, event_id: str, *, back: str, default_horizon: str | None) -> str:
        fid = c.form_id("hz", event_id)
        body = c.form_field("Forecast horizon (YYYY-MM-DD)", c.text_input("horizon_date", fid, kind="date",
                                                                          maxlength=10, value=""), for_id=fid,
                            hint="Each outcome counts as YES only if it happens on or before this date. Empty: "
                                 f"the end of this year{f' ({default_horizon})' if default_horizon else ''}.")
        return self.form("packet", body, submit="Prepare research packet", label="Prepare research packet",
                         hidden={"event_id": event_id, "return_tab": back, "return_event": event_id})

    def analysis(self, event_id: str | None, *, back: str) -> str:
        fid = c.form_id("an", event_id or "any")
        body = (c.form_field("Paste the assistant's whole reply (or your own JSON)",
                             c.textarea("text", fid, rows=10, maxlength=262144, required=True, mono=True), for_id=fid,
                             hint="It is validated against the recorded packet when you submit. Prices, fees and "
                                  "tickers in the reply are refused.")
                + c.checkbox("owner_judgment", c.form_id("oj", event_id or "any"),
                             "This is my own judgment, not an assistant's reply"))
        return self.form("analysis", body, submit="Import analysis", label="Paste analysis", multipart=True,
                         hidden={"return_tab": back, "return_event": event_id})


def submissions_state(view: Any, forms: Forms) -> str:
    """Whether submissions can be made and processed, said once at the top."""
    if not view.inbox.configured:
        return c.blocked_state(
            "Submissions are not enabled on this dashboard",
            "It was started without an intel inbox (--intel-inbox), so transcripts, analyses, links and refreshes "
            "cannot be submitted here. Everything collected is still shown; the CLI (edge-lab intel) can do each step.")
    if view.inbox.error:
        return c.error_state("Inbox unavailable", f"The inbox could not be listed ({view.inbox.error}). "
                                                  "Submissions may fail; nothing was changed.")
    pending = len(view.inbox.pending)
    queued = f" {pending} submission{'s' if pending != 1 else ''} waiting." if pending else ""
    if not view.processor.available:
        return c.blocked_state("Collector not processing submissions",
                               view.processor.reason + " The forms below still queue it privately." + queued)
    return c.status_line("info", "Submissions are processed by the collector",
                         view.processor.reason + " Each one is handled within about five minutes." + queued)


def submitted_line(view: Any, p: pr.Params) -> str:
    if not p.submitted:
        return ""
    done = next((r for r in view.inbox.results if r.get("id") == p.submitted), None)
    if done is not None:
        status = str(done.get("status"))
        detail = done.get("message") or ""
        return c.status_line("warn" if status != "DONE" else "info",
                             f"Submission {status.lower()} · {p.submitted}", str(detail))
    waiting = "" if view.processor.available else " The collector is not running, so it waits until it runs."
    return c.status_line("info", f"Submission queued · {p.submitted}",
                         "It is in the private inbox and is processed when the collector next runs." + waiting)


def legend(view: Any) -> str:
    rows = [
        (view.labels["collected"], "Headlines, links, times and short snippets read from verified free feeds."),
        (view.labels["classified"], "Topics, entities, claim types and events from versioned keyword rules: "
                                    "heuristic, not understanding."),
        (view.labels["imported_ai"], "An assistant's reply you pasted back: validated for format and ids, not for truth."),
        (view.labels["owner"], "Your own judgment, recorded as such."),
        (view.labels["provisional"], "No forecast here has a calibration history yet."),
        (view.labels["econ_estimate"], "Cost-inclusive figures use a fee schedule that is not verified: not claimable."),
        (view.labels["econ_unsupported"], "No supported fee schedule: no cost, so no EV at all."),
        (view.labels["econ_verified"], "Only when the fee for the side shown is verified and claimable. None is today."),
        (view.labels["hypothetical"], "Decisions are research records. No order, fill or position exists."),
    ]
    return c.disclosure("What the labels mean", c.kv([(k, esc(v)) for k, v in rows]))


# --------------------------------------------------------------------------- A · today


def _item_row(item: Mapping[str, Any]) -> str:
    when = item.get("published_utc") or item.get("first_seen_utc")
    sub = " · ".join(x for x in (item.get("source"), pr.datetime_et(when) or "time unknown",
                                 "via aggregator" if item.get("via_aggregator") else None) if x)
    body = c.facts([("Evidence type", _word({}, item.get("evidence_type"), "EVIDENCE", capsule=False)),
                    ("Storage", esc(str(item.get("rights") or "").replace("_", " ").lower() or None))])
    snippet = f'<p class="note">{esc(item.get("snippet"))}</p>' if item.get("snippet") else ""
    return _row(_ext(item.get("link"), item.get("title") or "(untitled)"), sub=sub, body=body + snippet)


def today_tab(view: Any, forms: Forms) -> str:
    run = view.last_run
    if run:
        run_line = (f"Last collection {pr.datetime_et(run.get('started_at_utc')) or 'time unknown'}: "
                    f"{run.get('ok', 0)} feeds read, {run.get('not_modified', 0)} unchanged, "
                    f"{run.get('failed', 0)} failed, {run.get('skipped', 0)} skipped, "
                    f"{run.get('new_items', 0)} new items.")
    else:
        run_line = "No news collection has run on this store yet."
    parts = []
    if not view.items:
        parts.append(c.section("Today's intelligence", c.empty_state(
            "Waiting for first collection", "No news item is stored yet. " + run_line,
            action=None), sid="in-today"))
    else:
        groups = []
        for code, title in CATEGORY_TITLES:
            rows = [i for i in view.items if i.get("category") == code][:ITEMS_PER_CATEGORY]
            if rows:
                groups.append(f'<h3 class="eyebrow">{esc(title)}</h3><ul class="rows">'
                              + "".join(_item_row(i) for i in rows) + "</ul>")
        parts.append(c.section("Today's intelligence", _label(view.labels["collected"])
                               + f'<p class="note">{esc(run_line)} Newest first; links open the publisher.</p>'
                               + "".join(groups), meta=f"{view.item_total} latest items", sid="in-today"))
    recent = view.transcripts[:3]
    if recent:
        rows = "".join(_transcript_row(t) for t in recent)
        parts.append(c.section("Recent podcast intelligence", _label(view.labels["classified"])
                               + '<p class="note">Owner-supplied transcripts: commentary, not evidence.</p>'
                               + f'<ul class="rows">{rows}</ul>', sid="in-pod",
                               action=f'<a href="{esc(href("transcripts"))}">All transcripts</a>'))
    changed = [e for e in view.events if e.changed][:6]
    body = (_label(view.labels["classified"]) + '<ul class="rows">' + "".join(_event_row(e) for e in changed)
            + "</ul>") if changed else c.empty_state("No event has new evidence in the last 24 hours",
                                                      "Events are built from collected news and transcripts.")
    parts.append(c.section("Events with changing evidence", body, sid="in-changed",
                           action=f'<a href="{esc(href("events"))}">All events</a>'))
    return "".join(parts)


# --------------------------------------------------------------------------- B · opportunities


def _side(sheet: Mapping[str, Any]) -> Mapping[str, Any] | None:
    best = sheet.get("best_side")
    for s in (sheet.get("yes"), sheet.get("no")):
        if isinstance(s, Mapping) and s.get("side") == best:
            return s
    return None


def _sides_table(sheet: Mapping[str, Any]) -> str:
    rows = []
    for s in (sheet.get("yes"), sheet.get("no")):
        if not isinstance(s, Mapping):
            continue
        rows.append([esc(s.get("side")), c.num(pr.cents(s.get("ask")), reason="no ask"),
                     c.num(pr.cents(s.get("bid")), reason="no bid"),
                     c.num(pr.cents(s.get("fee_per_contract")), reason="fee unknown"),
                     c.code(s.get("fee_status")), esc("yes" if s.get("fee_claimable") is True else "no"),
                     c.num(pr.cents(s.get("all_in_cost")), reason="no cost"),
                     c.num(pr.cents(s.get("break_even")), reason="no break-even"),
                     c.num(pr.percent(s.get("p_point")), reason="no probability"),
                     c.num(pr.percent(s.get("p_conservative")), reason="no probability"),
                     c.num(pr.edge_cents(s.get("ev_point")), reason="no EV"),
                     c.num(pr.edge_cents(s.get("ev_conservative")), reason="no EV"),
                     c.num(pr.cents(s.get("max_acceptable_price")), reason="no maximum price"),
                     c.num(pr.quantity(s.get("top_size")), reason="size unknown"),
                     esc(", ".join(s.get("reasons") or []) or "none"),
                     esc(", ".join(s.get("canonical_reasons") or []) or "none")])
    return c.table(["Side", "Ask", "Bid", "Fee", "Fee status", "Claimable", "All-in cost", "Break-even",
                    "P(this side wins) point", "P(this side wins) conservative", "EV point", "EV conservative", "Max price", "Top size",
                    "Reasons", "Canonical reasons"], rows, wrap=(14, 15), caption="Both sides at decision time")


def opportunity_card(o: Any, forms: Forms, now: Any) -> str:
    title = esc(o.ticker) + (f" · {esc(o.market_title)}" if o.market_title else "")
    sub = f"{o.event_title} · {o.outcome_text}"
    dec = o.decision
    refresh = forms.refresh("quotes", "Refresh price", back="opportunities", outcome=o.outcome_id,
                            label=f"Refresh the price of {o.ticker}")
    if not dec:
        body = c.empty_state("Not priced yet", "The link is confirmed; no price was read since. Refresh the price to "
                                               "record a decision.") + refresh
        return _row(title, sub=sub, aside=c.badge("INTEL_ACTION_NONE", label="Not priced yet", kind="nd"), body=body)
    sheet = dec.get("sheet") or {}
    action = sheet.get("action")
    side = _side(sheet)
    fc = o.forecast
    insufficient = action == "INSUFFICIENT_EVIDENCE"
    econ = o.economics
    horizon = dec.get("horizon_check")
    facts = [
        ("Side", esc(sheet.get("best_side")) if sheet.get("best_side") else c.na("no side chosen")),
        ("Entry ask", c.num(pr.cents(side.get("ask")) if side else None, reason="no executable ask")),
        ("Independent probability of YES", c.txt(_range(fc), reason="unavailable: no usable forecast")),
        ("Conservative max price", c.num(pr.cents(side.get("max_acceptable_price")) if side else None,
                                         reason="no maximum acceptable price")),
        ("Estimated edge after costs", c.num(pr.edge_cents(side.get("ev_conservative")) if side else None,
                                             reason="not computed") + f'<span class="cell-sub"> {esc(econ)}</span>'),
        ("Confidence", esc(fc.get("label") or "PROVISIONAL") if fc else c.na("no forecast")),
        ("Market close", _when(dec.get("market_close_utc") or sheet.get("close_time_utc"), "close time unknown")
         + (f'<span class="cell-sub"> {esc(pr.hours_text(sheet.get("hours_to_close")))} at decision</span>'
            if sheet.get("hours_to_close") is not None else "")),
        ("Forecast horizon", c.txt(pr.date_label(dec.get("forecast_horizon_date")), reason="horizon not recorded")
         + " " + _word(HORIZON_WORDS, horizon or "UNKNOWN", "INTEL_HORIZON", capsule=False)),
        ("Priced", _when(dec.get("decided_utc")) + f'<span class="cell-sub"> '
         f'{esc("current" if o.current else "not current: " + (pr.age_text(dec.get("decided_utc"), now) or "age unknown"))}'
         "</span>"),
        ("Quote received", _when(sheet.get("quote_received_at_utc"), "no book captured")),
    ]
    why = (fc or {}).get("reasoning")
    risk = (fc or {}).get("main_risk")
    labels = _label(HYPOTHETICAL_LINE) + _label(econ)
    if fc:
        labels += _label(basis_text(fc.get("basis")))
    if sheet.get("provisional"):
        labels += _label("PROVISIONAL FORECAST (no calibration history)")
    warn = ""
    if insufficient:
        warn += c.blocked_state("INSUFFICIENT EVIDENCE — NO RELIABLE EDGE ESTIMATE",
                                "There is no usable independent probability for this outcome.")
    if horizon == "MISMATCH":
        warn += c.status_line("warn", "Forecast horizon does not match the market's close",
                              f"The forecast is for {dec.get('forecast_horizon_date') or 'an unknown date'}; the market "
                              f"closes {pr.datetime_et(dec.get('market_close_utc')) or 'at an unknown time'}. "
                              "The forecast does not answer this market's question until they match.")
    if not o.current:
        warn += c.status_line("warn", "Price evidence is not current",
                              f"Priced {pr.datetime_et(dec.get('decided_utc')) or 'at an unknown time'}; a book older "
                              "than 15 minutes is stale — not actionable. Refresh the price for a new decision.")
    text = (f'<p>{esc(sheet.get("explanation"))}</p>'
            + (f'<p class="note"><strong>Why:</strong> {esc(why)}</p>' if why else "")
            + (f'<p class="note"><strong>Main risk:</strong> {esc(risk)}</p>' if risk else ""))
    details = c.disclosure("Pricing sheet details", _sides_table(sheet) + c.kv([
        ("Action reasons", c.ul(sheet.get("action_reasons") or [])),
        ("Lock-up policy", c.code(sheet.get("lockup_policy"))), ("Lock-up reasons", c.ul(sheet.get("lockup_reasons") or [])),
        ("Action policy", c.code(sheet.get("policy_id"))), ("Market status", c.code(sheet.get("market_status"))),
        ("Quote fresh at decision", esc(bool(sheet.get("quote_fresh")))),
        ("Quote age at decision", c.num(pr.duration_text(sheet.get("quote_age_seconds")), reason="unknown")),
        ("Quote evidence", c.code(sheet.get("quote_evidence_id"))), ("Forecast", c.code(dec.get("forecast_id"))),
        ("Price awareness", c.code(dec.get("price_awareness"))), ("Decision label", esc(dec.get("label"))),
        ("Outcome", c.code(o.outcome_id)),
        ("Decided (UTC)", esc(dec.get("decided_utc"))),
    ]))
    return _row(title, sub=sub, aside=_word(ACTION_WORDS, action, "INTEL_ACTION"),
                 body=labels + warn + c.facts(facts, wide=True, text_cols=(2, 4, 5, 6, 7, 8, 9)) + text + refresh + details)



def _rules_block(rules: Mapping[str, Any] | None) -> str:
    if not rules:
        return c.blocked_state("Rules not captured", "No captured rules text was found for this candidate, so it "
                                                     "cannot be confirmed here. Run Find Kalshi markets again.")
    pairs = [(k, esc(rules.get(k))) for k in ("title", "yes_sub_title", "no_sub_title", "rules_primary",
                                              "rules_secondary", "settlement_sources") if rules.get(k)]
    pairs += [("Close", _when(rules.get("close_time"), "close not captured")),
              ("Captured", _when(rules.get("captured_utc")))]
    return '<p class="eyebrow">CAPTURED RULES (read before confirming)</p>' + c.kv(pairs)


def candidate_row(event: Any, cand: Mapping[str, Any], forms: Forms) -> str:
    ticker = str(cand.get("ticker"))
    rules = cand.get("rules")
    form = ""
    if rules:
        sel = c.form_id("oc", event.event_id, ticker)
        body = (c.form_field("This market's YES is the outcome", c.select("outcome_id", sel, [
                    (o.outcome_id, o.text) for o in event.outcomes]), for_id=sel)
                + c.checkbox("rules_read", c.form_id("rr", event.event_id, ticker), "I read the rules")
                + c.checkbox("yes_matches_outcome", c.form_id("ym", event.event_id, ticker),
                             "YES means this outcome"))
        form = forms.form("link", body, label=f"Confirm or reject {ticker}",
                          hidden={"ticker": ticker, "return_tab": "opportunities", "return_event": event.event_id},
                          buttons=(("status", "CONFIRMED", "Confirm link", True),
                                   ("status", "REJECTED", "Reject candidate", False)))
    body = (f'<p class="note">{esc(cand.get("note"))}</p>'
            + c.facts([("Matched words", esc(", ".join(cand.get("matched") or []) or None)),
                       ("Match score", c.num(str(cand.get("score")) if cand.get("score") is not None else None)),
                       ("Event", esc(event.title))], text_cols=(0, 2))
            + c.disclosure("Captured rules — read before confirming", _rules_block(rules), open_=False) + form)
    return _row(esc(f"CANDIDATE · {ticker}"), sub=str(cand.get("title") or ""),
                 aside=c.badge("INTEL_CANDIDATE", label="Candidate · unconfirmed", kind="nd"), body=body)


def opportunities_tab(view: Any, forms: Forms, now: Any, event_id: str | None = None) -> str:
    cards = "".join(opportunity_card(o, forms, now) for o in view.opportunities)
    note = (_label(HYPOTHETICAL_LINE)
            + '<p class="note">One card per market you confirmed. Each figure is the recorded decision\'s own value; '
              "an uncalibrated forecast or an unverified fee is never a proven opportunity.</p>")
    first = (note + f'<ul class="rows">{cards}</ul>') if cards else c.empty_state(
        "No confirmed market yet", "Open an event, prepare its research packet, import an analysis, find Kalshi markets "
                                   "and confirm one after reading its rules. Then refresh its price.",
        action=(href("events"), "Events"))
    refresh = forms.refresh("quotes", "Refresh all prices", back="opportunities", label="Refresh prices")
    parts = [c.section("Potential opportunities", first + refresh, sid="in-opps", meta="research only · no orders")]
    # Candidates for the selected event, else for events you have forecasts on (the ones you are working).
    selected = [e for e in view.events if event_id and e.event_id == event_id]
    pool = selected or [e for e in view.events if e.candidates and any(o.forecast for o in e.outcomes)]
    cands = [(e, cand) for e in pool for cand in e.candidates][:12]
    if cands:
        scope = "for this event" if selected else "for events you have forecasts on"
        parts.append(c.section("Candidate markets", f'<p class="note">Shown {scope}. A title or keyword match is not '
                               "settlement equivalence. Nothing here is priced until you confirm it.</p>"
                               '<ul class="rows">' + "".join(candidate_row(e, cand, forms) for e, cand in cands)
                               + "</ul>", sid="in-cands", meta="unconfirmed · never priced"))
    return "".join(parts)


# --------------------------------------------------------------------------- C · transcripts


def _transcript_row(t: Any) -> str:
    meta = t.meta or {}
    sub = " · ".join(x for x in (meta.get("podcast"), pr.date_label(meta.get("published_date")),
                                 f"imported {pr.datetime_et(t.imported_utc)}" if t.imported_utc else None) if x)
    facts = c.facts([("Claims", c.num(pr.count(t.claims))), ("Unverified", c.num(pr.count(t.unverified))),
                     ("New information", c.num(pr.count(t.new_information))),
                     ("Topics", esc(", ".join(t.topics) or "none recognised"))], text_cols=(3,))
    claims = c.table(["Claim", "Type", "Verification", "Speaker"],
                     [[esc(cl.get("text")), c.code(cl.get("claim_type")), c.code(cl.get("verification")),
                       esc(cl.get("speaker"))] for cl in t.sample_claims], wrap=(0,), caption="First claims")
    details = c.disclosure("Claims and details", claims + c.kv([
        ("Label", esc(t.label)), ("Source of the text", esc(meta.get("transcript_source"))),
        ("Episode page", _ext(meta.get("episode_url"), meta.get("episode_url") or "not given")),
        ("Notes", esc(meta.get("notes"))), ("Format", c.code(t.format)), ("Characters", c.num(pr.count(t.chars))),
        ("Transcript id", c.code(t.transcript_id))]))
    return _row(esc(meta.get("episode") or "(episode not named)"), sub=sub,
                 aside=c.badge("INTEL_PROCESSED", label="Imported", kind="nd"), body=facts + details)


def transcript_form(forms: Forms) -> str:
    if not forms.enabled:
        return ""
    f = lambda *a: c.form_id("tr", *a)  # noqa: E731
    body = (c.form_field("Transcript text", c.textarea("text", f("text"), rows=10, maxlength=1_500_000), for_id=f("text"),
                         hint="Paste the text, or choose a file below (a file wins when both are given).")
            + c.form_field("Or a file (.txt, .md, .srt, .vtt; UTF-8)", c.text_input(
                "file", f("file"), kind="file", accept=".txt,.md,.srt,.vtt,text/plain,text/markdown,text/vtt"),
                for_id=f("file"))
            + c.form_field("Podcast", c.text_input("podcast", f("podcast"), required=True), for_id=f("podcast"))
            + c.form_field("Episode", c.text_input("episode", f("episode"), required=True), for_id=f("episode"))
            + c.form_field("Published date", c.text_input("published_date", f("date"), kind="date", maxlength=10),
                           for_id=f("date"))
            + c.form_field("Episode URL", c.text_input("episode_url", f("url"), kind="url", maxlength=2000),
                           for_id=f("url"))
            + c.form_field("Where the text came from", c.text_input("transcript_source", f("src"), value="owner paste",
                                                                    maxlength=120, required=True), for_id=f("src"))
            + c.form_field("Notes", c.textarea("notes", f("notes"), rows=3, maxlength=4000), for_id=f("notes")))
    return c.section("Import a transcript", '<p class="note">Stored privately. A podcast is commentary, not evidence: '
                     "its claims are cross-checked against collected news.</p>"
                     + forms.form("transcript", body, submit="Import transcript", label="Import a transcript",
                                  multipart=True, hidden={"return_tab": "transcripts"}), sid="in-tr-form")


def transcripts_tab(view: Any, forms: Forms) -> str:
    listing = ('<ul class="rows">' + "".join(_transcript_row(t) for t in view.transcripts) + "</ul>"
               if view.transcripts else c.empty_state("No transcript imported yet",
                                                      "Paste or upload one; it appears here once the collector "
                                                      "processes it."))
    return transcript_form(forms) + c.section("Imported transcripts", _label(view.labels["classified"]) + listing,
                                              meta=f"{len(view.transcripts)} imported", sid="in-tr")


# --------------------------------------------------------------------------- D · events


def _event_row(e: Any) -> str:
    sub = " · ".join(x for x in (e.topic.replace("_", " ").lower(), f"{len(e.origins)} independent origins",
                                 f"{len(e.evidence)} evidence items",
                                 f"latest {pr.datetime_et(e.last_evidence_utc)}" if e.last_evidence_utc else None) if x)
    return _row(f'<a class="link" href="{esc(href("events", event=e.event_id))}">{esc(e.title)}</a>', sub=sub,
                 aside=_word(EVENT_WORDS, e.status, "INTEL_EVENT"))


def _outcome_block(o: Any) -> str:
    fc = o.forecast
    if fc and fc.get("abstained"):
        fc_html = esc("Abstained: the analysis gave no estimate.")
    elif fc:
        fc_html = c.num(_range(fc), reason="no point") + f'<span class="cell-sub"> {esc(fc.get("label") or "PROVISIONAL")}</span>'
    else:
        fc_html = c.na("no forecast imported")
    link = o.link
    link_html = (esc(f"{link.get('status')} · {link.get('ticker')}") if link else c.na("no market linked"))
    return c.facts([("Outcome", esc(o.text)), ("Resolves on", esc(o.resolution_condition)),
                    ("Forecast", fc_html), ("Basis", esc(fc and ("OWNER JUDGMENT (unvalidated)" if fc.get("basis") ==
                                                                 "OWNER_JUDGMENT" else "IMPORTED AI ANALYSIS (unvalidated)"))
                                            if fc else c.na("no forecast")),
                    ("Market", link_html),
                    ("Resolution", esc(o.resolution.get("result")) if o.resolution else c.na("not resolved"))],
                   wide=True, text_cols=(0, 1, 3, 4))


def event_detail(e: Any, view: Any, forms: Forms) -> str:
    facts = c.facts([
        ("Status", _word(EVENT_WORDS, e.status, "INTEL_EVENT", capsule=False)),
        ("Why", esc(e.status_reason)),
        ("Verification", _word(VERIFICATION_WORDS, e.verification, "INTEL_VERIFY", capsule=False)),
        ("Independent origins", esc(", ".join(e.origins) or "none")),
        ("Primary sources", esc(", ".join(e.primary_sources) or "none")),
        ("First evidence", _when(e.first_evidence_utc)), ("Latest evidence", _when(e.last_evidence_utc)),
    ], wide=True, text_cols=(1, 3, 4))
    pk = e.packet
    packet_line = (f'<p class="note">Research packet {esc(pk["packet_id"])} recorded '
                   f'{esc(pr.datetime_et(pk.get("created_utc")) or "")} · horizon '
                   f'{esc(pr.date_label(pk.get("horizon_date")) or "not recorded")} '
                   f'({esc(pk.get("horizon_set_by") or "unknown")}).</p>' if pk else
                   '<p class="note">No research packet is recorded for this event yet.</p>')
    actions = ('<div class="btn-row">'
               + (f'<a class="btn btn-primary" href="{esc(packet_href(e.event_id))}">Open research packet</a>' if pk else "")
               + forms.refresh("discover", "Find Kalshi markets", back="opportunities", event=e.event_id,
                               label="Find Kalshi markets for this event")
               + "</div>")
    default_hz = f"{view.as_of_utc[:4]}-12-31"  # service.create_packet's default horizon
    parts = [c.section("Event", _label(view.labels["classified"]) + facts + packet_line + actions,
                       sid="in-ev", meta=e.event_id)]
    parts.append(c.section("Outcomes and resolution conditions", '<ul class="rows">' + "".join(
        _row(esc(o.outcome_id), body=_outcome_block(o)) for o in e.outcomes) + "</ul>"
        if e.outcomes else c.empty_state("No outcome template for this topic", "Nothing can be forecast here yet."),
        sid="in-ev-out"))
    ev_rows = "".join(_row(_ext(x.get("link"), x.get("title") or "(untitled)"),
                            sub=" · ".join(y for y in (x.get("source"), x.get("evidence_type"),
                                                       pr.datetime_et(x.get("observed_utc")),
                                                       x.get("claim_type")) if y))
                      for x in e.evidence)
    parts.append(c.section("Evidence", (f'<ul class="rows">{ev_rows}</ul>' if ev_rows else
                                        c.empty_state("No evidence shown", "The event has no stored evidence.")),
                           meta=f"{len(e.evidence)} items", sid="in-ev-evidence"))
    extra = []
    if e.contradictions:
        extra.append('<h3 class="eyebrow">Contradictions</h3>' + c.ul(f"{a} ↔ {b}" for a, b in e.contradictions))
    extra.append('<h3 class="eyebrow">Unconfirmed podcast claims</h3>' + c.ul(e.unconfirmed_claims, empty="none"))
    parts.append(c.section("Contradictions and unconfirmed claims", "".join(extra), sid="in-ev-contra"))
    if forms.enabled:
        parts.append(c.section("Research packet", forms.packet(e.event_id, back="events", default_horizon=default_hz),
                               sid="in-ev-packet", meta="records a packet with your forecast horizon"))
        parts.append(c.section("Paste analysis", forms.analysis(e.event_id, back="events"), sid="in-ev-an",
                               meta="assistant reply or your own judgment"))
    return "".join(parts)


def events_tab(view: Any, forms: Forms, p: pr.Params) -> str:
    if p.event:
        ev = next((e for e in view.events if e.event_id == p.event), None)
        if ev is None:
            return c.section("Event", c.empty_state("Event not in the current window",
                                                    "Events are rebuilt from the last 14 days of evidence; this one "
                                                    "has no current evidence.", action=(href("events"), "All events")),
                             sid="in-ev")
        return event_detail(ev, view, forms)
    if not view.events:
        return c.section("Events to watch", c.empty_state("No event yet", "Events appear once collected news or a "
                                                                         "transcript names a recognised development."),
                         sid="in-evs")
    # Events you are working (a forecast or a link) first, then the best supported; at most EVENTS_SHOWN.
    worked = [e for e in view.events if any(o.forecast or o.link for o in e.outcomes)]
    rest = [e for e in view.events if e not in worked]
    shown = (worked + rest)[:EVENTS_SHOWN]
    more = (f'<p class="note">Showing {len(shown)} of {len(view.events)} events: the ones you are working, then the '
            "best supported by independent sources. Single-source events stay in the evidence store.</p>"
            if len(view.events) > len(shown) else "")
    return c.section("Events to watch", _label(view.labels["classified"]) + more + '<ul class="rows">'
                     + "".join(_event_row(e) for e in shown) + "</ul>", meta=f"{len(view.events)} events",
                     sid="in-evs")


EVENTS_SHOWN = 40


# --------------------------------------------------------------------------- E · history


HISTORY_ROWS = 100  # newest rows per table; the journal keeps everything


def _newest(rows: Any, key: str) -> list:
    return sorted(rows, key=lambda r: str(r.get(key) or ""), reverse=True)[:HISTORY_ROWS]


def history_tab(view: Any) -> str:
    h = view.history
    fc_rows = [[_when(f.get("recorded_at_utc")), c.code(f.get("outcome_id")), c.num(_range(f), reason="abstained"),
                esc("OWNER JUDGMENT" if f.get("basis") == "OWNER_JUDGMENT" else "IMPORTED AI"),
                c.code(f.get("price_awareness")), c.txt(pr.date_label(f.get("horizon_date")), reason="not recorded"),
                esc("superseded" if f.get("superseded") else "active")] for f in _newest(h.forecasts, "recorded_at_utc")]
    dec_rows = [[_when(x.get("decided_utc")), c.code(x.get("ticker")),
                 esc(ACTION_WORDS.get((x.get("sheet") or {}).get("action"), ("Unknown", ""))[0]),
                 esc((x.get("sheet") or {}).get("explanation"))] for x in _newest(h.decisions, "decided_utc")]
    res_rows = [[c.code(r.get("outcome_id")), esc(r.get("result")), esc(r.get("source")), _when(r.get("recorded_utc"))]
                for r in h.resolutions]
    perf = h.performance
    if perf is None:
        perf_body = c.error_state("Performance unavailable", f"ERROR — {h.performance_error or 'not computed'}.")
    else:
        brier = perf.get("brier_by_basis") or {}
        perf_body = (_label(perf.get("label") or "PROVISIONAL / HYPOTHETICAL") + c.facts(
            [(f"Brier · {b.replace('_', ' ').lower()}", c.num(None if v.get("brier") is None else f"{v['brier']:.4f}",
                                                             reason="no resolved forecast")
              + f'<span class="cell-sub"> n={esc(v.get("n"))}</span>') for b, v in sorted(brier.items())]
            + [("Resolved outcomes", c.num(pr.count(perf.get("resolved_outcomes")))),
               ("Hypothetical entries", c.num(pr.count(perf.get("hypothetical_entries")))),
               ("Hypothetical P&L per contract", c.num(pr.money(perf.get("hypothetical_pnl_per_contract"), signed=True),
                                                       reason="no resolved INVESTIGATE decision"))], wide=True))
    rej = [[c.code(r.get("outcome_id")), c.code(r.get("ticker")), _when(r.get("decided_utc"))] for r in h.rejected_links]
    an_rows = [[_when(a.get("recorded_at_utc")), esc(a.get("label")), esc(a.get("assistant")), esc(a.get("summary"))]
               for a in _newest(h.analyses, "recorded_at_utc")]
    inbox_rows = ([[c.code(x.get("id")), esc(KIND_WORDS.get(x.get("kind"), x.get("kind"))),
                    _word(INBOX_WORDS, "QUEUED", "INTEL_INBOX", capsule=False), _when(x.get("queued_utc")), esc("")]
                   for x in view.inbox.pending]
                  + [[c.code(x.get("id") or x.get("file")), esc(KIND_WORDS.get(x.get("kind"), x.get("kind"))),
                      _word(INBOX_WORDS, x.get("status"), "INTEL_INBOX", capsule=False), _when(x.get("recorded_at_utc")),
                      esc(x.get("message") or x.get("code") or "")] for x in view.inbox.results])
    return "".join([
        c.section("Performance", perf_body, sid="in-perf", meta="provisional · hypothetical"),
        c.section("Forecasts", _label(view.labels["provisional"]) + c.table(
            ["Recorded", "Outcome", "Probability", "Basis", "Price awareness", "Horizon", "State"], fc_rows,
            caption="Every forecast, newest first", empty="No forecast recorded yet"), sid="in-fc"),
        c.section("Decisions", _label(HYPOTHETICAL_LINE) + c.table(
            ["Decided", "Market", "Action", "Explanation"], dec_rows, wrap=(3,), caption=f"Every decision, SKIP included (newest {min(HISTORY_ROWS, len(h.decisions))} of {len(h.decisions)})",
            empty="No decision recorded yet"), sid="in-dec"),
        c.section("Resolutions", c.table(["Outcome", "Result", "Source", "Recorded"], res_rows, wrap=(2,),
                                         caption="Resolutions", empty="No outcome resolved yet"), sid="in-res"),
        c.section("Rejected markets", c.table(["Outcome", "Market", "Rejected"], rej, caption="Rejected candidates",
                                              empty="No candidate rejected"), sid="in-rej"),
        c.section("Imported analyses", c.table(["Recorded", "Label", "Assistant", "Summary"], an_rows, wrap=(3,),
                                               caption="Analyses", empty="No analysis imported yet"), sid="in-an"),
        c.section("Submissions", c.table(["Submission", "Kind", "State", "Time", "Message"], inbox_rows, wrap=(4,),
                                         caption="Inbox submissions", empty="No submission recorded"
                                         if view.inbox.configured else "Submissions are not enabled here"),
                  sid="in-inbox"),
    ])


# --------------------------------------------------------------------------- sources


def sources_tab(view: Any) -> str:
    by_source: dict[str, list[Mapping[str, Any]]] = {}
    for s in view.sources:
        by_source.setdefault(s["source_id"], []).append(s)
    counts = " · ".join(f"{SOURCE_WORDS.get(k, (k, ''))[0]} {v}" for k, v in sorted(view.feed_counts.items()))
    rows = []
    for sid, feeds in sorted(by_source.items(), key=lambda kv: kv[1][0].get("number") or 0):
        first = feeds[0]
        status = min((f["status"] for f in feeds), key=lambda st: list(SOURCE_WORDS).index(st)
                     if st in SOURCE_WORDS else 99)
        facts = c.facts([
            ("Category", esc(str(first.get("category") or "").lower() or None)),
            ("Evidence type", esc(first.get("evidence_type"))),
            ("Last success", _when(max((f.get("last_success_utc") or "" for f in feeds), default="") or None,
                                   "never collected")),
            ("Last verified", _when(max((f.get("verified_ok_utc") or "" for f in feeds), default="") or None,
                                    "no recorded verification")),
            ("Last error", esc("; ".join(str(f["last_error"]) for f in feeds if f.get("last_error")) or "none recorded")),
        ], text_cols=(0, 1, 4))
        details = c.disclosure("Feeds and terms", c.table(
            ["Feed", "Status", "Last attempt", "Outcome", "Signal"],
            [[c.code(f.get("feed_id")), c.code(f.get("status")), _when(f.get("last_attempt_utc"), "never"),
              c.code(f.get("last_outcome")), c.code(f.get("access_signal"))] for f in feeds],
            caption="Feeds", empty="No machine-readable feed") + c.kv([
                ("Mechanism", esc(first.get("mechanism"))), ("Terms", esc(first.get("terms"))),
                ("Storage", esc(first.get("rights"))), ("Declared status", c.code(first.get("declared_status")))]))
        rows.append(_row(esc(f"{first.get('number')}. {first.get('name')}"), sub=str(first.get("note") or ""),
                          aside=_word(SOURCE_WORDS, status, "INTEL_SOURCE"), body=facts + details))
    return c.section("Sources", f'<p class="note">{esc(counts)}. An inaccessible source is never active; '
                     "collection needs a verification younger than 14 days.</p>"
                     + '<ul class="rows">' + "".join(rows) + "</ul>", meta=f"{len(by_source)} candidates", sid="in-src")


# --------------------------------------------------------------------------- pages


def workspace_body(view: Any, forms: Forms, p: pr.Params, now: Any) -> str:
    tab = p.tab if p.tab in dict(pr.INTEL_TABS) else "today"
    counts = {"opportunities": str(len(view.opportunities)), "events": str(len(view.events)),
              "transcripts": str(len(view.transcripts))}
    strip = c.tabs([(href(k), label, k == tab, counts.get(k)) for k, label in pr.INTEL_TABS],
                   label="Intelligence workspace")
    controls = ""
    if forms.enabled:
        controls = ('<div class="btn-row">' + forms.refresh("news", "Refresh news", back=tab, label="Refresh news")
                    + forms.refresh("quotes", "Refresh prices", back=tab, label="Refresh prices") + "</div>")
    body = {"today": lambda: today_tab(view, forms), "opportunities": lambda: opportunities_tab(view, forms, now, getattr(p, "event", None)),
            "events": lambda: events_tab(view, forms, p), "transcripts": lambda: transcripts_tab(view, forms),
            "history": lambda: history_tab(view), "sources": lambda: sources_tab(view)}[tab]()
    return (submitted_line(view, p) + submissions_state(view, forms) + controls + legend(view) + strip
            + '<div class="stack">' + body + "</div>")


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head(TITLE, "Collected news, transcripts, research packets and provisional forecasts · research "
                              "only · no orders", crumb=_crumb())
    loaded = ctx.intel_view
    if loaded.status != d.OK:
        missing = (c.unavailable("Intelligence workspace", "NO DATA / NOT STARTED — " + loaded.message)
                   if loaded.status == d.NO_DATA else
                   c.error_state("Intelligence workspace unavailable", "Data unavailable — " + loaded.message))
        return cm.Page(TITLE, "research", head + missing)
    forms = Forms(ctx, loaded.value)
    return cm.Page(TITLE, "research", head + workspace_body(loaded.value, forms, p, ctx.now))


def packet_body(ctx: d.Context, p: pr.Params, view: Any | None, forms: Forms | None) -> str:
    if not p.event:
        return c.empty_state("No event chosen", "Open an event and choose Open research packet.",
                             action=(href("events"), "Events"))
    loaded = ctx.intel_packet(p.event)
    event = next((e for e in (view.events if view else ()) if e.event_id == p.event), None)
    title = f'<p class="note">Event: {esc(event.title if event else p.event)}</p>'
    if loaded.status == d.ERROR:
        return c.error_state("Research packet unavailable", "Data unavailable — " + loaded.message)
    if loaded.status != d.OK:
        default_hz = f"{view.as_of_utc[:4]}-12-31" if view else None
        prepare = forms.packet(p.event, back="events", default_horizon=default_hz) if forms and forms.enabled else ""
        state = c.empty_state("No research packet recorded yet",
                              "Packets are prepared by the collector for the best-supported events, or on request. "
                              + ("Prepare one below; it appears here after the collector runs." if prepare else
                                 "Submissions are not enabled here; use edge-lab intel packet on the host."))
        return title + state + prepare
    packet, record = loaded.value["packet"], loaded.value["record"]
    facts = c.facts([("Packet", c.code(packet.packet_id)), ("Recorded", _when(record.get("created_utc"))),
                     ("Forecast horizon", c.txt(pr.date_label(record.get("horizon_date")), reason="not recorded")
                      + f'<span class="cell-sub"> {esc(record.get("horizon_set_by") or "")}</span>'),
                     ("Evidence items", c.num(pr.count(len(packet.evidence_ids)))),
                     ("Outcomes", c.num(pr.count(len(packet.outcome_ids))))])
    copy = c.copy_text("packet-text", packet.text, label="Research packet (copy all of it)",
                       button="Copy research packet")
    steps = c.ul(["Copy the packet and paste it into Claude, ChatGPT or another assistant.",
                  "Paste the assistant's whole reply below and import it; it is validated when you submit.",
                  "The packet holds no Kalshi data, price, fee or ticker, so the forecast stays independent."])
    after = (c.section("Paste analysis", forms.analysis(p.event, back="events"), sid="pk-an")
             if forms and forms.enabled else "")
    return (title + c.section("Research packet", _label("CONTAINS NO MARKET DATA · for any assistant") + facts + steps
                              + copy, sid="pk", meta="sha256 " + packet.packet_sha256[:12]) + after)


def packet_view(ctx: d.Context, p: pr.Params) -> cm.Page:
    crumb = (f'<a class="crumb" href="{esc(href("events", event=p.event or None))}">{c.icon("arrow-left", "ic-sm")}'
             f"<span>Intelligence workspace</span></a>")
    head = c.page_head("Research packet", "For your chosen assistant · no market data", crumb=crumb)
    loaded = ctx.intel_view
    view_obj = loaded.value if loaded.status == d.OK else None
    if loaded.status == d.ERROR:
        return cm.Page("Research packet", "research",
                       head + c.error_state("Research packet unavailable", "Data unavailable — " + loaded.message))
    if loaded.status == d.NO_DATA:
        return cm.Page("Research packet", "research",
                       head + c.unavailable("Research packet", "NO DATA / NOT STARTED — " + loaded.message))
    forms = Forms(ctx, view_obj)
    return cm.Page("Research packet", "research",
                   head + submitted_line(view_obj, p) + '<div class="stack">' + packet_body(ctx, p, view_obj, forms)
                   + "</div>")


def error_page(code: int, reason: str, back: str) -> str:
    """The body shown for a refused submission (rendered by the app with the shell)."""
    return (c.page_head("Submission refused", f"HTTP {code} · nothing was written")
            + c.blocked_state("Your submission was not queued", reason, action=(back, "Back to the workspace")))


# --------------------------------------------------------------------------- gallery (demo only)


def gallery(ctx: d.Context, p: pr.Params) -> cm.Page:
    from .. import fixtures

    label = '<p class="gallery-label">SYNTHETIC FIXTURES · intelligence workspace · demo mode only</p>'
    head = c.page_head("Intelligence states", "Every state of the intelligence workspace, from synthetic stores.",
                       extra=label, crumb=_crumb())
    parts = []
    for name, (loaded, tab) in fixtures.synthetic_intel_views(ctx.now).items():
        if loaded.status != d.OK:
            inner = cm.loaded_state(f"State {name}", loaded) or ""
        else:
            forms = Forms(ctx, loaded.value)
            inner = workspace_body(loaded.value, forms, pr.Params(route=PATH, tab=tab), ctx.now)
        parts.append(c.section(f"State · {name}", inner, sid=f"in-g-{name}"))
    return cm.Page("Intelligence states", "research", head + '<div class="stack">' + "".join(parts) + "</div>")


INTEL_PAGES = {PATH: (TITLE, view), PACKET_PATH: ("Research packet", packet_view)}
INTEL_DEMO_PAGES = {"/gallery/intel": ("Intelligence states", gallery)}
INTEL_NAV_KEYS = {PATH: "research", PACKET_PATH: "research"}
