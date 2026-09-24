"""Shared page helpers: account scope, board rows, attention items and the status line.

Pages compose `components` from `presentation` view models built here. Every figure is a
canonical value read through `data.Context`; nothing here computes money or eligibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ... import forward
from ...fee_schedules import RECHECK_WARNING
from ...freshness import parse_utc
from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc

EQUITY_LABEL = "cost-basis shadow equity (not liquidation value)"
BANKROLL_LABEL = "notional starting bankroll"
BOUND_LABEL = "upper bound, not a predicted scenario"
ACCOUNTING_NOTE = (
    "Accounting basis: open positions are carried at cost (cash paid, fees included). No mark-to-market: "
    "unrealized gains are never counted, and hypothetical winnings are never available cash. Realized P&L "
    "moves only when a position settles on official evidence. Fees come from the recorded fee schedule. Each "
    "decision carries the fee verification known when it was made: claim basis NONE allows no net-profitability "
    "claim; CONSERVATIVE_BOUND means fees are verified and costs are over-stated, so net results are lower "
    "bounds, never exact figures."
)
MAX_ROWS = 1000

ACCOUNT_IDS = {"operational": d.OPERATIONAL_ACCOUNT_ID, "research": d.RESEARCH_ACCOUNT_ID}
ACCOUNT_NAMES = {"operational": "Operational shadow", "research": "Research · frozen EXP-001 rule"}


@dataclass
class Page:
    title: str
    nav: str
    body: str
    account_scoped: bool = False
    status: int = 200


def get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def malformed(container: Any, key: str) -> bool:
    """True when `key` is present with a value that is not a list: shown as MALFORMED, never as none."""
    return isinstance(container, dict) and container.get(key) is not None and not isinstance(container[key], list)


def list_field(container: Any, key: str) -> str:
    """A receipt list field: its items, "none" when empty, unknown when absent, MALFORMED otherwise."""
    if malformed(container, key):
        return c.badge("MALFORMED", label="MALFORMED (expected a list)") + " " + esc(container[key])
    if not isinstance(container, dict) or key not in container:
        return esc(None)
    return c.ul(container[key]) if container[key] else esc("none")


def no_fills(value: Any) -> str:
    """The pipeline writes no-fill counts by reason ({"RISK_VETO": 1}); older shapes are an int."""
    if isinstance(value, dict):
        total = sum(v for v in value.values() if isinstance(v, int))
        return f"{total} ({', '.join(f'{k} {v}' for k, v in sorted(value.items(), key=str))})" if value else "0"
    return str(value)


def loaded_state(title: str, loaded: d.Loaded) -> str | None:
    """The unavailable or error state for a source that is not OK, else None."""
    if loaded.status == d.NO_DATA:
        return c.unavailable(title, "NO DATA / NOT STARTED — " + loaded.message)
    if loaded.status == d.ERROR:
        return c.error_state(title, "Data unavailable — " + loaded.message)
    return None


# --------------------------------------------------------------------------- account scope


def account_view(ctx: d.Context, p: pr.Params) -> d.AccountView:
    return ctx.account(ACCOUNT_IDS[p.account])


def account_heading(view: d.AccountView) -> str:
    role = view.role.label if view.role else "UNCLASSIFIED ACCOUNT"
    return f"{view.account_id} — {role}"


def scope_label(p: pr.Params) -> str:
    return ACCOUNT_NAMES[p.account]


def research_badge(p: pr.Params) -> str:
    return c.badge("FROZEN", label="FROZEN RESEARCH RULE", kind="info") if p.account == "research" else ""


def account_unavailable(view: d.AccountView, *, what: str = "Account") -> str | None:
    """The honest state for an account that is not loaded: not started, or an error (never zeros)."""
    if view.status == d.OK:
        return None
    if view.status == d.ERROR:
        return c.error_state(f"{what} unavailable", f"The shadow ledger could not be read: ERROR — {view.message}")
    return c.unavailable(f"{what} not started", f"NO DATA / NOT STARTED — {view.message or 'the account has not been opened'}."
                         " Balances appear after the daily shadow run opens the account.")


def board_rows(ctx: d.Context, p: pr.Params) -> list[pr.MarketRow]:
    """Every market the selected account can see: captured books joined with its recorded decisions."""
    cache = ctx.__dict__.setdefault("_rows", {})
    if p.account not in cache:
        view = account_view(ctx, p)
        board = ctx.observed.value if ctx.observed.status == d.OK else None
        open_ids = [pos.market_id for pos in view.state.open_positions()] if view.state is not None else []
        cache[p.account] = pr.build_rows(
            board.markets if board else [], view.account_id, view.decisions, view.fills, open_ids,
            current_target=board.target_date if board else None,
            capture_status={phase: c.get("status") for phase, c in board.captures.items()} if board else None,
            now=ctx.now)
    return cache[p.account]


# --------------------------------------------------------------------------- blockers (carried over verbatim)


def blockers(ctx: d.Context) -> list[str]:
    out = []
    for fee in d.fee_rows(ctx.now):
        if not fee["active"]:
            continue
        if not fee["claimable"]:
            out.append(f"Fee schedule {fee['schedule_id']} is {fee['status']}: claimable = false, no "
                       "net-profitability claim may rest on shadow results.")
        elif fee["claim_basis"] == "CONSERVATIVE_BOUND":
            out.append(f"Fee schedule {fee['schedule_id']}: claim basis CONSERVATIVE_BOUND for decisions from "
                       f"{fee['checked_at_utc']} (current view). A claim uses net minus "
                       f"{fee['claim_allowance_per_contract']} USD per contract, a lower bound, never an exact figure; "
                       "earlier decisions keep the basis recorded with them.")
        recheck = parse_utc(fee.get("recheck_by_utc"))
        if recheck is not None and ctx.now > recheck:
            out.append(f"Fee verification {fee['verification_id']} is OVERDUE for re-check (due "
                       f"{fee['recheck_by_utc']}): new decisions carry claim basis NONE until a new record lands.")
        elif recheck is not None and recheck - ctx.now <= RECHECK_WARNING:
            out.append(f"Fee verification {fee['verification_id']} must be re-checked by {fee['recheck_by_utc']}; "
                       "after that date new decisions carry claim basis NONE.")
    for view in ctx.accounts:
        starter = d.starter_view(view, ctx.now) if view.status == d.OK else None
        for exc in (starter or {}).get("exceptions", []):
            out.append(f"SEVEN_DAY_POLICY_EXCEPTION on {view.account_id}: {exc['fill_id']} ({exc['market_id']}) is "
                       f"still open past its expected tradable-cash release {exc['tradable_cash_release_eta_utc']}. "
                       "Capital stays reserved; review before adding starter exposure.")
    for label, loaded in (("collector status file", ctx.collector_status), ("pipeline receipt", ctx.receipt)):
        if loaded.status != d.OK:
            out.append(f"{label}: {loaded.status.replace('_', ' ')} — {loaded.message}")
        else:
            fresh, _ = d.freshness(loaded.value.get("generated_at_utc"), ctx.now)
            if fresh != "FRESH":
                out.append(f"{label} is {fresh} (generated {loaded.value.get('generated_at_utc')})")
    if ctx.receipt.status == d.OK:
        state = ctx.receipt.value.get("state")
        if state not in ("HEALTHY_NO_SIGNAL", "HEALTHY_TRADED"):
            out.append(f"pipeline receipt state is {state}")
        settlement = get(ctx.receipt.value, "settlement")
        pending = as_list(get(settlement, "pending"))
        if pending:
            out.append(f"{len(pending)} settlement(s) pending in the latest receipt")
        conflicts = as_list(get(settlement, "conflicts"))
        if conflicts:
            out.append(f"{len(conflicts)} settlement evidence conflict(s): "
                       + ", ".join(f"{get(x, 'account_id')}/{get(x, 'position_id')}" for x in conflicts[:10])
                       + " (see Portfolio)")
        missing = as_list(ctx.receipt.value.get("missing_capture_days"))
        if missing:
            out.append(f"{len(missing)} closed day(s) with no capture (lost Stage B days): "
                       + ", ".join(map(str, missing[:10])))
        for owner, key in ((settlement, "pending"), (settlement, "conflicts"),
                           (ctx.receipt.value, "missing_capture_days")):
            if malformed(owner, key):
                out.append(f"pipeline receipt field {key} is MALFORMED (not a list); its contents are unknown")
        latest = get(ctx.receipt.value, "latest_day")
        if isinstance(latest, dict) and latest.get("result") == "INVALID_CAPTURE":
            out.append(f"latest day {latest.get('target_date')} is INVALID_CAPTURE ({latest.get('capture_status')})")
    if ctx.ledger.status != d.OK:
        out.append(f"shadow ledger: {ctx.ledger.status.replace('_', ' ')} — {ctx.ledger.message}")
    for view in ctx.accounts:
        if view.status == d.ERROR:
            out.append(f"{view.account_id}: ERROR — {view.message}")
        if view.status != d.OK:
            continue
        overdue = [p for p in view.state.open_positions()
                   if (parse_utc(p.expected_settlement_utc) or ctx.now) < ctx.now]
        if overdue:
            out.append(f"{view.account_id}: {len(overdue)} open position(s) past their expected settlement "
                       "(pending official evidence)")
        if view.risk is not None and view.risk.status == d.OK and view.risk.value.breaches:
            out.append(f"{view.account_id}: risk breaches {', '.join(view.risk.value.breaches)}; new risk halted")
        elif view.risk is not None and view.risk.status == d.OK and not view.risk.value.new_risk_allowed:
            out.append(f"{view.account_id}: remaining risk capacity is zero; new risk halted (no limit breached)")
        invalid_cash = view.state.no_fill_reasons.get("RESEARCH_INVALID_CASH")
        if invalid_cash:
            out.append(f"{view.account_id}: {invalid_cash} RESEARCH_INVALID_CASH no-fill(s): the research record "
                       "deviated from the frozen EXP-001 rule (experiment validity problem)")
        if view.risk is not None and view.risk.status == d.ERROR:
            out.append(f"{view.account_id}: risk report ERROR — {view.risk.message}")
    return out


def blockers_cached(ctx: d.Context) -> list[str]:
    if "_blockers" not in ctx.__dict__:
        ctx.__dict__["_blockers"] = blockers(ctx)
    return ctx.__dict__["_blockers"]


def risk_state(rep: Any) -> str:
    """OK, BREACH (a limit is breached) or HALTED (no limit breached, but no risk capacity left)."""
    if rep.breaches:
        return "BREACH"
    return "OK" if rep.new_risk_allowed else "HALTED"


def risk_line(rep: Any) -> str:
    state = risk_state(rep)
    detail = (", ".join(rep.breaches) if state == "BREACH" else
              "no limit breached, but remaining risk capacity is zero" if state == "HALTED" else "no breaches")
    return c.badge(state, label=state if state != "OK" else "OK") + " " + esc(detail)


# --------------------------------------------------------------------------- collection status and schedule

_MISSING = (("forecast", "forecast"), ("decision capture", "decision"), ("complete decision", "decision"),
            ("recheck", "re-check"), ("re-check", "re-check"), ("book", "order-book"), ("market", "market list"),
            ("event", "event"))


def missing_evidence(reasons: list) -> str | None:
    """"Missing forecast and decision evidence." from the recorded reason strings (no guessing)."""
    found: list[str] = []
    for r in reasons:
        text = str(r).lower()
        for needle, label in _MISSING:
            if needle in text and label not in found:
                found.append(label)
                break
    if not found:
        return None
    joined = found[0] if len(found) == 1 else ", ".join(found[:-1]) + " and " + found[-1]
    return f"Missing {joined} evidence."


def next_windows(now: datetime) -> list[tuple[str, datetime]]:
    """The collector's next scheduled capture windows (forward.windows), soonest first."""
    today = forward.eastern_date(now)
    out = []
    for offset in (1, 2):
        target = today + timedelta(days=offset)
        w = forward.windows(target)
        out.append((f"Decision capture for {target:%b} {target.day}", w["decision"]))
        out.append((f"Re-check capture for {target:%b} {target.day}", w["decision"] + forward.RECHECK_MIN))
    return sorted([(label, t) for label, t in out if t > now], key=lambda x: x[1])[:2]


@dataclass(frozen=True)
class Status:
    kind: str
    title: str
    detail: str


def collection_status(ctx: d.Context) -> Status:
    """The Terminal status line. A fresh report is never shown as a healthy capture."""
    s = ctx.collector_status
    report_time = None
    if s.status == d.OK:
        report_time = s.value.get("generated_at_utc")
    elif ctx.collector_db.status == d.OK:
        s = ctx.collector_db
    if s.status == d.ERROR:
        return Status("err", "Data unavailable", f"The collector status could not be read: {s.message}")
    if s.status != d.OK:
        return Status("nd", "Waiting for first capture",
                      "No collector status has been recorded here yet. " + s.message.capitalize() + ".")
    v = s.value
    target = v.get("last_closed_target_date")
    target_text = pr.date_label(target) if target else None
    status = v.get("last_closed_status")
    fresh, _ = d.freshness(v.get("generated_at_utc"), ctx.now)
    report = (f"Report refreshed {pr.age_text(report_time, ctx.now)}"
              if report_time else "Status re-derived from the evidence database just now")
    if report_time and fresh != "FRESH":
        report = f"Status report is {fresh.lower()} (generated {pr.datetime_et(report_time) or 'at an unknown time'})"
    where = f" · {target_text}" if target_text else ""
    if status == "VALID":
        return Status("ok" if fresh == "FRESH" or not report_time else "warn", f"Last target captured{where}",
                      f"Valid capture. {report}.")
    if status is None:
        return Status("warn", f"Capture timing not verified{where}", f"No capture status recorded. {report}.")
    missing = missing_evidence(as_list(v.get("last_closed_reasons")))
    return Status("err", f"Capture needs attention{where}",
                  f"{missing or pr.state_word(status).label + '.'} {report}.")


def coverage_text(board: Any) -> str:
    """Which captured day the board shows, when, and whether that capture was complete."""
    times = [v.get("completed_at_utc") for v in board.captures.values() if v.get("completed_at_utc")]
    when = pr.datetime_et(max(times)) if times else None
    text = f"Target {pr.date_label(board.target_date) or 'unknown day'} · captured {when or 'at an unknown time'}"
    if not board.complete:
        text += " · capture incomplete"
    if board.total_markets > len(board.markets):
        text += f" · first {len(board.markets)} of {board.total_markets} markets shown"
    return text


def receipt_time(ctx: d.Context) -> str | None:
    return ctx.receipt.value.get("generated_at_utc") if ctx.receipt.status == d.OK else None


# --------------------------------------------------------------------------- alerts


@dataclass(frozen=True)
class Alert:
    group: str  # attention | standing | recent | checks | expired
    kind: str
    title: str
    subject: str | None
    when_utc: str | None
    reason: str
    href: str | None
    delivery: str
    code: str | None
    raw: dict | None = None
    origin: str | None = "PRODUCTION"  # notifications.Origin value; None = unrecognised (treated as production)


def _safe_local_href(link: Any) -> str | None:
    """A same-origin path from a notification deep link; any other URL is not linked."""
    if not isinstance(link, str):
        return None
    for prefix in ("http://127.0.0.1:8765", "http://localhost:8765"):
        if link.startswith(prefix):
            link = link[len(prefix):] or "/"
    path = link.split("?", 1)[0]
    from . import PAGES  # local: avoids an import cycle
    return path if path in PAGES else None


def failure_alert(f: d.FailureRecord) -> Alert:
    """A unit-failure record as an alert. Only a root-confirmed deployment verification is a check;
    every other record (whatever origin it claims) is a production incident that needs attention."""
    unit = f.record.get("unit") or "unknown unit"
    if f.error is not None:
        return Alert("attention", "err", f"Unit-failure record unreadable ({f.source})", None, None, f.error, None,
                     "Recorded locally", "ERROR")
    if f.verification:
        return Alert("checks", "nd", f"Verification check: {unit} refused as expected", f.record.get("unit"),
                     f.record.get("failed_at_utc"), f"Deployment verification confirmed by root ({f.source}). "
                     "Not an incident; never pushed.", None, "Stored locally; never pushed (verification)",
                     "DEPLOYMENT_VERIFICATION", f.record, "DEPLOYMENT_VERIFICATION")
    claimed = f.record.get("origin")
    why = f"Recorded in {f.source} by the failure hook."
    if claimed not in (None, "PRODUCTION"):
        why += (f" It claims origin {claimed}, but no root confirmation of a verification exists, so it is "
                "treated as a production failure.")
    return Alert("attention", "err", f"Production incident: unit failed: {unit}", f.record.get("unit"),
                 f.record.get("failed_at_utc"), why, None, "Recorded locally", "FAILED", f.record, "PRODUCTION")


def _delivery(origin: Any) -> str:
    """How a notification of this origin is delivered (notifications' origin policy); the outbox row
    is the only record here."""
    from ... import notifications as n

    if origin is None:
        return "Recorded locally (outbox); origin unrecognised, so treated as production"
    o = n.Origin(origin)
    if o in n.DEFAULT_PUSH_ORIGINS:
        return "Recorded locally (outbox); phone delivery not recorded"
    if o in n.REQUESTABLE_PUSH_ORIGINS:
        return "Recorded locally (outbox); pushed only when explicitly requested; phone delivery not recorded"
    return "Stored locally; never pushed (held by origin)"


def alerts(ctx: d.Context) -> list[Alert]:
    """Every attention item available locally: outbox notifications, the unit-failure records and the
    system blockers. Nothing is sent; a row in a file is not proof a phone received anything.

    Origins never mix: only production (or an unrecognised origin, failing closed) can need
    attention; tests, verification checks, diagnostics, replays and demos are their own group."""
    from ... import notifications as n

    items: list[Alert] = []
    for text in blockers_cached(ctx):
        title, kind = blocker_title(text)
        group = "standing" if kind == "info" else "attention"
        items.append(Alert(group, kind, title, None, None, text, None, "Shown here only (not a notification)", None))
    items.extend(failure_alert(f) for f in ctx.failure_records)
    if ctx.notifications.status == d.OK:
        for row in ctx.notifications.value:
            origin = n.origin_of(row)
            origin_value = None if origin is None else origin.value
            expires = parse_utc(row.get("expires_at_utc"))
            expired = expires is not None and expires < ctx.now
            sev = str(row.get("severity") or "")
            kind = {"CRITICAL": "err", "WARNING": "warn", "INFO": "info"}.get(sev, "nd")
            if origin is not None and origin is not n.Origin.PRODUCTION:
                group, kind = "checks", "nd"
            else:
                group = "expired" if expired and sev != "CRITICAL" else ("attention" if sev in ("CRITICAL", "WARNING")
                                                                         else "recent")
            items.append(Alert(group, kind, str(row.get("summary") or row.get("type") or "Notification"),
                               row.get("market_id") or row.get("venue_id"), row.get("created_at_utc"),
                               f"{pr.state_word(row.get('type')).label if row.get('type') else 'Event'}"
                               + (" · expired" if expired else ""), _safe_local_href(row.get("deep_link")),
                               _delivery(origin_value), row.get("type"), row, origin_value))
    return items


_BLOCKER_TITLES = (
    ("is OVERDUE for re-check", "Fee re-check overdue", "err"),
    ("must be re-checked by", "Fee re-check due soon", "warn"),
    ("claim basis CONSERVATIVE_BOUND", "Fee claims are lower bounds", "info"),
    ("claimable = false", "No fee claim basis", "err"),
    ("SEVEN_DAY_POLICY_EXCEPTION", "Starter-policy exception", "err"),
    ("collector status file", "Collector status", "warn"),
    ("pipeline receipt state is", "Pipeline run needs attention", "err"),
    ("pipeline receipt field", "Pipeline receipt malformed", "err"),
    ("pipeline receipt", "Pipeline receipt", "warn"),
    ("settlement(s) pending", "Settlements pending", "warn"),
    ("settlement evidence conflict", "Settlement conflict", "err"),
    ("closed day(s) with no capture", "Missed capture days", "err"),
    ("is INVALID_CAPTURE", "Latest day capture incomplete", "err"),
    ("shadow ledger:", "Shadow ledger unavailable", "warn"),
    ("risk breaches", "Risk limit breached", "err"),
    ("remaining risk capacity is zero", "New positions halted", "err"),
    ("RESEARCH_INVALID_CASH", "Frozen-rule deviation", "err"),
    ("past their expected settlement", "Settlement overdue", "warn"),
    ("risk report ERROR", "Risk report unavailable", "err"),
    (": ERROR", "Account unreadable", "err"),
)


def blocker_title(text: str) -> tuple[str, str]:
    """A short title and severity for one blocker line (the full line is always shown too)."""
    for needle, title, kind in _BLOCKER_TITLES:
        if needle in text:
            unreadable = {"collector status file": "Collector status unreadable",
                          "pipeline receipt": "Pipeline receipt unreadable", "shadow ledger:": "Shadow ledger unreadable"}
            if needle in unreadable and ": ERROR" in text:
                return unreadable[needle], "err"
            if needle == "collector status file" and "NO DATA" in text:
                return "Collector status not available", "nd"
            if needle == "pipeline receipt" and "NO DATA" in text:
                return "No pipeline receipt yet", "nd"
            if needle == "shadow ledger:" and "NO DATA" in text:
                return "Shadow ledger not started", "nd"
            return title, kind
    return "System check", "warn"


def attention_count(ctx: d.Context) -> int | None:
    try:
        return sum(1 for a in alerts(ctx) if a.group == "attention")
    except Exception:  # noqa: BLE001 - the header never fails a page
        return None


def et_day(ts: str | None) -> date | None:
    local = pr.to_et(ts)
    return local.date() if local else None


def jdump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
