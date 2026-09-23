"""The six dashboard views. Each takes a request `Context` and returns escaped HTML.

Views only format figures the canonical modules produced (see `data.py`).
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Any

from .. import exp001_shadow
from ..fee_schedules import RECHECK_WARNING
from ..freshness import parse_utc
from . import data as d
from .html import age, error, esc, kv, money, no_data, panel, state_tag, table, tag, ul

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


def _loaded_panel(title: str, loaded: d.Loaded) -> str | None:
    """The NO DATA or ERROR panel for a source that is not OK, else None."""
    if loaded.status == d.NO_DATA:
        return no_data(title, loaded.message)
    if loaded.status == d.ERROR:
        return error(title, loaded.message)
    return None


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _malformed(container: Any, key: str) -> bool:
    """True when `key` is present with a value that is not a list: shown as MALFORMED, never as none."""
    return isinstance(container, dict) and container.get(key) is not None and not isinstance(container[key], list)


def _list_field(container: Any, key: str) -> str:
    """A receipt list field: its items, "none" when empty, unknown when absent, MALFORMED otherwise."""
    if _malformed(container, key):
        return tag("MALFORMED (expected a list)", "err") + " " + esc(container[key])
    if not isinstance(container, dict) or key not in container:
        return esc(None)
    return ul(container[key]) if container[key] else esc("none")


def _no_fills(value: Any) -> str:
    """The pipeline writes no-fill counts by reason ({"RISK_VETO": 1}); older shapes are an int."""
    if isinstance(value, dict):
        total = sum(v for v in value.values() if isinstance(v, int))
        return f"{total} ({', '.join(f'{k} {v}' for k, v in sorted(value.items(), key=str))})" if value else "0"
    return str(value)


def _account_heading(view: d.AccountView) -> str:
    role = view.role.label if view.role else "UNCLASSIFIED ACCOUNT"
    return f"{view.account_id} — {role}"


def _account_intro(view: d.AccountView) -> str:
    note = view.role.note if view.role else "an account the dashboard does not recognise; shown for completeness"
    return f'<p class="note">{esc(note)}</p>'


def _account_unavailable(view: d.AccountView) -> str | None:
    if view.status == d.OK:
        return None
    title = _account_heading(view)
    if view.status == d.ERROR:
        return error(title, view.message)
    return no_data(title, view.message)


def _fresh_line(ts: Any, now) -> str:
    state, delta = d.freshness(ts, now)
    return f"{state_tag(state)} generated {esc(ts)} (age {age(delta)}; stale after 26 h)"


# --------------------------------------------------------------------------- overview


def collector_panels(ctx: d.Context) -> str:
    out = []
    status = ctx.collector_status
    missing = _loaded_panel("Collector status file (latest.json)", status)
    if missing:
        out.append(missing)
    else:
        s = status.value
        fresh, _ = d.freshness(s.get("generated_at_utc"), ctx.now)
        out.append(panel("Collector status file (latest.json)", kv([
            ("freshness", _fresh_line(s.get("generated_at_utc"), ctx.now)),
            ("last closed target date", esc(s.get("last_closed_target_date"))),
            ("last closed status", state_tag(s.get("last_closed_status"))),
            ("reasons", ul(_list(s.get("last_closed_reasons")))),
            ("valid days", esc(s.get("valid_days"))),
            ("first valid day", esc(s.get("first_valid_day"))),
            ("days with captures", esc(s.get("days_with_captures"))),
            ("invalid days", ul(_list(s.get("invalid_days")))),
        ]), "" if fresh == "FRESH" else "stale"))
    db = ctx.collector_db
    missing = _loaded_panel("Collector status from the evidence DB (computed now)", db)
    if missing:
        out.append(missing)
    else:
        s = db.value
        started = (s.get("days_with_captures") or 0) > 0
        out.append(panel("Collector status from the evidence DB (computed now)", kv([
            ("captures", esc(s.get("days_with_captures")) if started else tag("NOT STARTED: no captures", "nd")),
            ("last closed target date", esc(s.get("last_closed_target_date"))),
            ("last closed status", state_tag(s.get("last_closed_status"))),
            ("reasons", ul(_list(s.get("last_closed_reasons")))),
            ("valid days", esc(s.get("valid_days"))),
            ("first valid day", esc(s.get("first_valid_day"))),
            ("invalid days", ul(_list(s.get("invalid_days")))),
        ]) + '<p class="note">Re-derived by forward.summary from stored evidence at page render.</p>'))
    failure = ctx.last_failure
    if failure.status == d.OK:
        f = failure.value
        out.append(panel("Last unit failure (last_failure.json)", kv([
            ("unit", esc(f.get("unit"))), ("failed at", esc(f.get("failed_at_utc"))),
            ("age", age(d.freshness(f.get("failed_at_utc"), ctx.now)[1])),
        ]), "stale"))
    elif failure.status == d.ERROR:
        out.append(error("Last unit failure (last_failure.json)", failure.message))
    return "".join(out)


def receipt_panel(ctx: d.Context, *, detail: bool = False) -> str:
    title = "Daily shadow pipeline receipt (shadow_daily.json)"
    missing = _loaded_panel(title, ctx.receipt)
    if missing:
        return missing
    r = ctx.receipt.value
    fresh, _ = d.freshness(r.get("generated_at_utc"), ctx.now)
    schema = r.get("schema")
    settlement = _get(r, "settlement")
    refresh = _get(settlement, "refresh")
    fee = _get(r, "fee")
    latest = _get(r, "latest_day")
    conflicts = _list(_get(settlement, "conflicts"))
    pairs = [
        ("state", state_tag(r.get("state"))
         + (" " + tag("REPEAT OF PREVIOUS ALERT", "nd") if r.get("repeat_of_previous_alert") else "")),
        ("exit code", esc(r.get("exit_code"))),
        ("latest day", (f"{esc(_get(latest, 'target_date'))} {state_tag(_get(latest, 'capture_status'))} "
                        f"{state_tag(_get(latest, 'result'))}") if isinstance(latest, dict) else esc(None)),
        ("valid / closed capture days", f"{esc(r.get('valid_days'))} / {esc(r.get('closed_capture_days'))}"),
        ("missing capture days", _list_field(r, "missing_capture_days")),
        ("freshness", _fresh_line(r.get("generated_at_utc"), ctx.now)),
        ("code version", esc(r.get("code_version"))),
        ("schema", esc(schema) + ("" if schema in (None, d.RECEIPT_SCHEMA) else " " + tag("UNEXPECTED SCHEMA", "warn"))),
        ("days processed", esc(len(_list(r.get("days")))) if "days" in r else esc(None)),
        ("settled this run", esc(_get(settlement, "settled"))),
        ("pending settlements", esc(len(_list(_get(settlement, "pending")))) if isinstance(settlement, dict)
         and "pending" in settlement else esc(None)),
        ("settlement conflicts", _list_field(settlement, "conflicts") if _malformed(settlement, "conflicts") else
         (tag(f"{len(conflicts)} SETTLEMENT_CONFLICT", "err") if conflicts else esc("none"))
         if isinstance(settlement, dict) and "conflicts" in settlement else esc(None)),
        ("settlement evidence cutoff", esc(_get(settlement, "evidence_cutoff_utc"))),
        ("settlement refresh", state_tag(_get(refresh, "status")) if refresh is not None else esc(None)),
        ("fee schedule", esc(_get(fee, "schedule_id")) + " " + (state_tag(_get(fee, "status")) if fee else "")),
        ("fee claim basis (at this run)", state_tag(_get(fee, "claim_basis")) if fee else esc(None)),
        ("fee claim allowed (lower bound only)", esc(_get(fee, "claimable"))),
        ("problems", ul(_list(r.get("problems")))),
    ]
    body = kv(pairs)
    if detail:
        rows = []
        for day in _list(r.get("days")):
            accounts = _get(day, "accounts")
            acct = "; ".join(
                f"{a}: {_get(v, 'decisions')} decisions, {_get(v, 'qualified')} qualified, {_get(v, 'fills')} fills, "
                f"{_no_fills(_get(v, 'no_fills'))} no-fills, {_get(v, 'risk_vetoes')} risk vetoes"
                for a, v in accounts.items()) if isinstance(accounts, dict) else None
            rows.append([esc(_get(day, "target_date")), state_tag(_get(day, "capture_status")),
                         esc(_get(day, "decision_time_utc")), esc(_get(day, "result")), esc(acct),
                         esc("; ".join(map(str, _list(_get(day, "problems")))) or None)])
        body += "<h3>Days</h3>" + table(["target date", "capture", "decision time", "result", "accounts",
                                         "problems"], rows, wrap=(4, 5))
        body += "<h3>Settlement evidence conflicts</h3>" + conflicts_table(conflicts)
        if isinstance(refresh, dict):
            body += "<h3>Settlement evidence refresh</h3>" + kv([
                ("status", state_tag(refresh.get("status"))), ("events requested", esc(refresh.get("events_requested"))),
                ("markets stored", esc(refresh.get("markets_stored"))), ("errors", ul(_list(refresh.get("errors")))),
            ])
    return panel(title, body, "" if fresh == "FRESH" else "stale")


def conflicts_table(conflicts: list) -> str:
    return table(["account", "position", "recorded outcome", "latest evidence outcome", "evidence variants"],
                 [[esc(_get(c, "account_id")), esc(_get(c, "position_id")), esc(_get(c, "recorded_outcome")),
                   esc(_get(c, "latest_evidence_outcome")), esc(_get(c, "variants"))] for c in conflicts], wrap=(4,))


def risk_state(rep: Any) -> str:
    """OK, BREACH (a limit is breached) or HALTED (no limit breached, but no risk capacity left)."""
    if rep.breaches:
        return "BREACH"
    return "OK" if rep.new_risk_allowed else "HALTED"


def _risk_line(rep: Any) -> str:
    state = risk_state(rep)
    detail = (", ".join(rep.breaches) if state == "BREACH" else
              "no limit breached, but remaining risk capacity is zero" if state == "HALTED" else "no breaches")
    return state_tag(state) + " " + esc(detail)


def _account_summary(view: d.AccountView) -> str:
    unavailable = _account_unavailable(view)
    if unavailable:
        return unavailable
    s = view.state
    pairs = [
        (BANKROLL_LABEL, money(s.starting_bankroll) + " " + tag("NOTIONAL", "nd")),
        (EQUITY_LABEL, money(s.equity)),
        ("settled cash", money(s.settled_cash)),
        ("committed capital (open, at cost)", money(s.committed_capital)),
        ("open worst-case risk", money(s.open_worst_case_risk)),
        ("realized P&L", money(s.realized_pnl)),
        ("fees paid (provisional schedule)", money(s.fees_paid)),
        ("decisions / qualified", f"{esc(s.decisions)} / {esc(s.qualified_decisions)}"),
        ("fills / no-fills / settlements", f"{esc(s.fills)} / {esc(s.no_fills)} / {esc(s.settlements)}"),
        ("open positions", esc(len(s.open_positions()))),
    ]
    if view.risk is not None and view.risk.status == d.OK:
        rep = view.risk.value
        pairs.append(("new risk allowed", _risk_line(rep)))
        pairs.append(("remaining risk capacity", money(rep.remaining_risk_capacity)))
    else:
        pairs.append(("risk", esc(view.risk.message if view.risk else None)))
    pairs.append(("withdrawal", tag("NOT RECOMMENDED", "err")))
    return panel(_account_heading(view), _account_intro(view) + kv(pairs))


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
        settlement = _get(ctx.receipt.value, "settlement")
        pending = _list(_get(settlement, "pending"))
        if pending:
            out.append(f"{len(pending)} settlement(s) pending in the latest receipt")
        conflicts = _list(_get(settlement, "conflicts"))
        if conflicts:
            out.append(f"{len(conflicts)} settlement evidence conflict(s): "
                       + ", ".join(f"{_get(c, 'account_id')}/{_get(c, 'position_id')}" for c in conflicts[:10])
                       + " (see Positions)")
        missing = _list(ctx.receipt.value.get("missing_capture_days"))
        if missing:
            out.append(f"{len(missing)} closed day(s) with no capture (lost Stage B days): "
                       + ", ".join(map(str, missing[:10])))
        for owner, key in ((settlement, "pending"), (settlement, "conflicts"),
                           (ctx.receipt.value, "missing_capture_days")):
            if _malformed(owner, key):
                out.append(f"pipeline receipt field {key} is MALFORMED (not a list); its contents are unknown")
        latest = _get(ctx.receipt.value, "latest_day")
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


def overview(ctx: d.Context) -> str:
    body = ['<div class="grid">', collector_panels(ctx), receipt_panel(ctx), "</div>"]
    body.append(panel("Blockers and warnings", ul(blockers(ctx)), "stale" if blockers(ctx) else ""))
    body.append('<div class="grid">' + "".join(_account_summary(v) for v in ctx.accounts) + "</div>")
    body.append(notifications_panel(ctx))
    return "".join(body)


def notifications_panel(ctx: d.Context) -> str:
    loaded = ctx.notifications
    note = ('<p class="note">' + esc("Local outbox only (notifications.jsonl). SMS is the preferred urgent channel "
                                    "but no provider is approved or configured, so nothing is texted.") + "</p>")
    if loaded.status != d.OK:
        return panel("Notifications", note + (no_data if loaded.status == d.NO_DATA else error)(
            "Notifications", loaded.message))
    return panel("Notifications", note + table(
        ["created (UTC)", "severity", "type", "summary", "expires", "action"],
        [[esc(n.get("created_at_utc")), state_tag(n.get("severity")), esc(n.get("type")), esc(n.get("summary")),
          esc(n.get("expires_at_utc")), esc(n.get("action_mode"))] for n in loaded.value], wrap=(3,)))


# --------------------------------------------------------------------------- opportunities


def opportunities(ctx: d.Context) -> str:
    out = []
    ledger = _loaded_panel("Shadow ledger", ctx.ledger)
    if ledger:
        out.append(ledger)
    for view in ctx.accounts:
        unavailable = _account_unavailable(view)
        if unavailable:
            out.append(unavailable)
            continue
        rows = []
        decisions = sorted(view.decisions, key=lambda x: (str(x.get("as_of_utc")), str(x.get("decision_id"))),
                           reverse=True)
        for dec in decisions[:MAX_ROWS]:
            opp = _get(dec, "opportunity") or {}
            sizing = _get(dec, "sizing")
            fill = view.fills.get(dec.get("decision_id"))
            slot = str(dec.get("slot") or "")
            rows.append([
                esc(dec.get("as_of_utc")), esc(slot.split("|")[0] if slot else None), esc(dec.get("market_id")),
                esc(dec.get("side")), state_tag(dec.get("qualification")), esc(dec.get("reason")),
                esc(", ".join(map(str, _list(dec.get("reasons")))) or None),
                esc(_get(opp, "model_probability")), esc(_get(opp, "conservative_probability")),
                money(_get(opp, "executable_price")), money(_get(opp, "fee")), money(_get(opp, "all_in_cost")),
                esc(_get(opp, "net_edge")), esc(_get(opp, "net_edge_conservative")),
                esc(_get(sizing, "final_size")), esc(_get(sizing, "binding_constraint")),
                (state_tag(fill.get("status")) + " " + esc(fill.get("reason"))) if fill else esc(None),
                esc(_get(opp, "freshness")), esc(_get(opp, "fee_status")),
                state_tag(dec.get("claim_basis") or ("NONE" if dec.get("claimable") is False else None)),
                _starter_cell(dec.get("starter_policy")),
            ])
        note = (f'<p class="note">{esc(len(view.decisions))} decisions recorded'
                + (f"; newest {MAX_ROWS} shown" if len(view.decisions) > MAX_ROWS else "") + ". Figures are the "
                "decision payloads written at decision time (Gate 5 engine); nothing is recomputed. Edge is net of "
                "the provisional fee schedule.</p>")
        headers = ["decided (UTC)", "target", "market", "side", "qualification", "primary reason", "all reasons",
                   "model P", "conservative P", "exec price", "fee", "all-in cost/contract", "net edge",
                   "net edge (conservative)", "size", "binding constraint", "fill", "freshness", "fee status",
                   "claim basis", "7-day starter (operational)"]
        out.append(panel(_account_heading(view), _account_intro(view) + note + table(headers, rows, wrap=(6,))))
    return "".join(out)


# --------------------------------------------------------------------------- positions


def positions(ctx: d.Context) -> str:
    out = [panel("Accounting basis", f'<p>{esc(ACCOUNTING_NOTE)}</p>')]
    ledger = _loaded_panel("Shadow ledger", ctx.ledger)
    if ledger:
        out.append(ledger)
    for view in ctx.accounts:
        unavailable = _account_unavailable(view)
        if unavailable:
            out.append(unavailable)
            continue
        s = view.state
        body = _account_intro(view) + kv([
            (BANKROLL_LABEL, money(s.starting_bankroll)), (EQUITY_LABEL, money(s.equity)),
            ("realized P&L", money(s.realized_pnl)), ("fees paid", money(s.fees_paid)),
            ("committed capital", money(s.committed_capital)),
            ("fills / no-fills / settlements", f"{esc(s.fills)} / {esc(s.no_fills)} / {esc(s.settlements)}"),
        ])
        body += "<h3>NO_FILL reasons</h3>" + table(
            ["reason", "count"], [[state_tag(k), esc(v)] for k, v in sorted(s.no_fill_reasons.items())])
        fills = sorted(view.fills.values(), key=lambda f: (str(f.get("filled_at_utc")), str(f.get("fill_id"))),
                       reverse=True)
        body += "<h3>Simulated fills (FILLED and NO_FILL)</h3>" + table(
            ["filled at (UTC)", "fill id", "market", "side", "status", "reason", "qty", "price", "fee",
             "total cost", "fee schedule", "detail"],
            [[esc(f.get("filled_at_utc")), esc(f.get("fill_id")), esc(f.get("market_id")), esc(f.get("side")),
              state_tag(f.get("status")), esc(f.get("reason")), esc(f.get("quantity")), money(f.get("price")),
              money(f.get("fee")), money(f.get("total_cost")), esc(f.get("fee_schedule_id")), esc(f.get("detail"))]
             for f in fills[:MAX_ROWS]], wrap=(11,))
        open_rows = []
        for p in sorted(s.open_positions(), key=lambda p: p.position_id):
            expected = parse_utc(p.expected_settlement_utc)
            pend = "no expected time (locked)" if expected is None else (
                "overdue: pending official evidence" if expected < ctx.now else "awaiting settlement")
            open_rows.append([esc(p.position_id), esc(p.market_id), esc(p.side), esc(p.quantity), money(p.price),
                              money(p.cost_basis), money(p.fees), esc(p.opened_at_utc),
                              esc(p.expected_settlement_utc), esc(pend)])
        body += "<h3>Open positions (pending settlement)</h3>" + table(
            ["position", "market", "side", "qty", "price", "cost basis", "fees", "opened", "expected settlement",
             "settlement state"], open_rows)
        settled = sorted((p for p in s.positions if p.status == "SETTLED"),
                         key=lambda p: str(p.settled_at_utc), reverse=True)
        body += "<h3>Settled positions</h3>" + table(
            ["position", "market", "side", "qty", "cost basis", "outcome", "payout", "net P&L", "settled at",
             "evidence snapshot"],
            [[esc(p.position_id), esc(p.market_id), esc(p.side), esc(p.quantity), money(p.cost_basis),
              esc(p.outcome), money(p.payout), money(p.net_pnl), esc(p.settled_at_utc),
              esc(_get(_get(view.settlements.get(p.position_id), "evidence"), "snapshot_id"))] for p in settled])
        out.append(panel(_account_heading(view), body))
    if ctx.receipt.status == d.OK:
        pending = _list(_get(_get(ctx.receipt.value, "settlement"), "pending"))
        out.append(panel("Pending settlements reported by the latest receipt", table(
            ["account", "position", "reason"],
            [[esc(_get(p, "account_id")), esc(_get(p, "position_id")), esc(_get(p, "reason"))] for p in pending],
            wrap=(2,))))
        conflicts = _list(_get(_get(ctx.receipt.value, "settlement"), "conflicts"))
        out.append(panel("Settlement evidence conflicts reported by the latest receipt", conflicts_table(conflicts)
                         + '<p class="note">A conflict means official evidence snapshots disagree; the position is '
                           'not settled (or its settlement is questioned) until the owner reviews the evidence.</p>',
                         "stale" if conflicts else ""))
    else:
        out.append(_loaded_panel("Pending settlements reported by the latest receipt", ctx.receipt))
    return "".join(out)


# --------------------------------------------------------------------------- outcome board


def outcome_board(ctx: d.Context) -> str:
    out = [panel("How to read the board", "<p>" + esc(
        "Positions are grouped by the real-world outcome they depend on (outcome cluster) and ranked by account "
        "impact. Max loss and max gain are upper bounds, not predicted scenarios: they add up position worst/best "
        "cases and ignore that mutually exclusive brackets cannot all lose or all win.") + "</p>")]
    ledger = _loaded_panel("Shadow ledger", ctx.ledger)
    if ledger:
        out.append(ledger)
    for view in ctx.accounts:
        unavailable = _account_unavailable(view)
        if unavailable:
            out.append(unavailable)
            continue
        board = _loaded_panel(_account_heading(view), view.board)
        if board:
            out.append(board)
            continue
        rows, linked = [], []
        for rank, g in enumerate(view.board.value, 1):
            rows.append([esc(rank), esc(g.outcome_cluster), esc(", ".join(g.event_ids)), esc(len(g.positions)),
                         money(g.current_exposure), money(g.max_account_loss), money(g.max_account_gain),
                         money(g.account_impact), money(g.realized_pnl), esc(g.settles_by_utc),
                         esc(g.unknown_settlement_positions), state_tag(g.horizon), state_tag(g.status),
                         esc(g.worst_case_method)])
            for p in g.positions:
                linked.append([esc(g.outcome_cluster), esc(p.position_id), esc(p.market_id), esc(p.side),
                               esc(p.quantity), money(p.cost_basis), money(p.potential_payout), state_tag(p.status),
                               money(p.net_pnl)])
        body = _account_intro(view) + table(
            ["rank", "outcome cluster", "events", "positions", "current exposure",
             f"max loss ({BOUND_LABEL})", f"max gain ({BOUND_LABEL})", "account impact", "realized P&L",
             "settles by (UTC)", "positions w/o settlement time", "horizon", "status", "bound method"], rows,
            wrap=(13,))
        body += "<h3>Linked positions</h3>" + table(
            ["cluster", "position", "market", "side", "qty", "cost basis", "potential payout", "status", "net P&L"],
            linked)
        out.append(panel(_account_heading(view), body))
    return "".join(out)


# --------------------------------------------------------------------------- risk


def _policy_rows(policy: Any) -> list[list[str]]:
    return [[esc(f.name), money(getattr(policy, f.name)) if f.name != "policy_id" else esc(policy.policy_id)]
            for f in dc_fields(policy)]


def _sizing_policy_rows(policy: Any) -> list[list[str]]:
    return [[esc(f.name), esc(getattr(policy, f.name))] for f in dc_fields(policy)]


def risk_view(ctx: d.Context) -> str:
    out = []
    ledger = _loaded_panel("Shadow ledger", ctx.ledger)
    if ledger:
        out.append(ledger)
    for view in ctx.accounts:
        unavailable = _account_unavailable(view)
        if unavailable:
            out.append(unavailable)
            continue
        body = _account_intro(view)
        if view.policy is not None:
            body += f"<h3>Risk policy caps ({esc(view.policy.policy_id)})</h3>" + table(
                ["limit", "value"], _policy_rows(view.policy))
        if view.risk.status != d.OK:
            body += (no_data if view.risk.status == d.NO_DATA else error)("Risk report", view.risk.message)
        else:
            r = view.risk.value
            body += "<h3>Risk report</h3>" + kv([
                ("as of", esc(r.as_of_utc)), (EQUITY_LABEL, money(r.equity)), ("settled cash", money(r.settled_cash)),
                ("reserve floor", money(r.reserve_floor)), ("committed capital", money(r.committed_capital)),
                ("open worst-case risk", money(r.open_worst_case_risk)),
                ("remaining risk capacity", money(r.remaining_risk_capacity)),
                ("peak equity", money(r.peak_equity)), ("drawdown", money(r.drawdown)),
                ("trailing 24 h realized loss", money(r.daily_loss)),
                ("trailing 7 d realized loss", money(r.weekly_loss)),
                ("breaches", ul(r.breaches)),
                ("new risk allowed", _risk_line(r)),
                ("notes", ul(r.notes)),
            ])
            body += "<h3>Capital release by horizon</h3>" + table(
                ["horizon", "committed / cash", "guaranteed cash", "best-case payout (never counted as cash)",
                 "positions"],
                [[esc(b.horizon), money(b.committed_capital), money(b.guaranteed_cash), money(b.best_case_payout),
                  esc(b.positions)] for b in r.capital_release])
            body += "<h3>Exposure by event</h3>" + table(
                ["event", "worst-case risk"], [[esc(k), money(v)] for k, v in r.risk_per_event.items()])
            body += "<h3>Exposure by outcome cluster</h3>" + table(
                ["cluster", "worst-case risk"], [[esc(k), money(v)] for k, v in r.cluster_exposure.items()])
        sizing_id = view.opened.get("sizing_policy_id")
        body += f"<h3>Sizing policy ({esc(sizing_id)})</h3>"
        if sizing_id == exp001_shadow.SIZING_POLICY.policy_id:
            body += table(["parameter", "value"], _sizing_policy_rows(exp001_shadow.SIZING_POLICY))
        elif sizing_id == exp001_shadow.RESEARCH_SIZING_ID:
            body += ('<p class="note">' + esc("Frozen EXP-001 rule: exactly 1 contract per signalled bracket, "
                                              "latency-confirmed-v1 fills, no operational caps and no risk vetoes. "
                                              "Never re-tuned.") + "</p>")
        else:
            body += '<p class="na">sizing policy parameters are not registered in this dashboard</p>'
        counts: dict[str, int] = {}
        for dec in view.decisions:
            constraint = _get(_get(dec, "sizing"), "binding_constraint")
            if constraint is not None:
                counts[constraint] = counts.get(constraint, 0) + 1
        body += "<h3>Binding sizing constraints (qualified decisions)</h3>" + table(
            ["binding constraint", "decisions"], [[esc(k), esc(v)] for k, v in sorted(counts.items())])
        body += _starter_panel(view, ctx.now)
        body += _withdrawal(view)
        out.append(panel(_account_heading(view), body))
    return "".join(out)


def _starter_cell(verdict: Any) -> str:
    if not isinstance(verdict, dict):
        return esc(None)
    if verdict.get("eligible"):
        return state_tag("ELIGIBLE") + " " + esc(f"{verdict.get('elapsed_hours_to_tradable')} h")
    return state_tag("STARTER_POLICY_INELIGIBLE") + " " + esc(", ".join(verdict.get("reasons") or []))


def _starter_panel(view: d.AccountView, now) -> str:
    s = d.starter_view(view, now)
    if s is None:
        return ""
    body = (f"<h3>Seven-day starter policy ({esc(s['policy_id'])})</h3>" + '<p class="note">' + esc(
        f"Eligible only if settled cash is expected to be tradable again on the same venue within "
        f"{s['max_hours']} elapsed hours of the commitment (governing clock: tradable_cash_release_eta). "
        f"Applies to operational decisions from {s['effective_from_utc']}; the research account is never "
        "affected. A position that runs past its expected release is an exception: capital stays reserved, "
        "nothing is force-sold.") + "</p>")
    body += "<h4>Exceptions</h4>" + table(
        ["fill", "market", "committed", "expected tradable cash", "past 168 h", "action"],
        [[esc(e["fill_id"]), esc(e["market_id"]), esc(e["commitment_utc"]), esc(e["tradable_cash_release_eta_utc"]),
          esc(e["past_168h"]), esc(e["action"])] for e in s["exceptions"]])
    body += "<h4>Verdicts on fills</h4>" + table(
        ["fill", "eligible", "reasons", "committed", "resolution ETA", "tradable cash ETA (governs)",
         "hours to tradable", "abnormal-path bound (reported only)"],
        [[esc(f.get("fill_id")), state_tag("ELIGIBLE" if f["starter_policy"].get("eligible") else
                                           "STARTER_POLICY_INELIGIBLE"),
          esc(", ".join(f["starter_policy"].get("reasons") or []) or None), esc(f["starter_policy"].get("commitment_utc")),
          esc(f["starter_policy"].get("resolution_eta_utc")), esc(f["starter_policy"].get("tradable_cash_release_eta_utc")),
          esc(f["starter_policy"].get("elapsed_hours_to_tradable")), esc(f["starter_policy"].get("abnormal_path_bound_utc"))]
         for f in s["verdicts"][-MAX_ROWS:]], wrap=(2, 7))
    return body


def _withdrawal(view: d.AccountView) -> str:
    head = f"<h3>Withdrawal</h3><p>{tag('NOT RECOMMENDED', 'err')} Withdrawal recommendations are unavailable.</p>"
    if view.withdrawal is None or view.withdrawal.status != d.OK:
        return head + f'<p class="na">{esc(view.withdrawal.message if view.withdrawal else None)}</p>'
    w = view.withdrawal.value
    return head + kv([
        ("recommendation status", state_tag(w.recommendation_status)),
        ("recommended owner draw", esc(w.recommended_owner_draw) if w.recommended_owner_draw is not None
         else "none (no recommendation exists)"),
        ("technically withdrawable (simulated arithmetic only; NOT available, NOT recommended)",
         money(w.technically_withdrawable)),
        ("policy-safe bound (simulated arithmetic only; NOT available, NOT recommended)",
         money(w.policy_safe_withdrawable)),
        ("why not recommended", ul(w.reasons)),
    ])


# --------------------------------------------------------------------------- experiments


def experiments_view(ctx: d.Context) -> str:
    out = []
    exps = ctx.experiments
    if ctx.config.demo:
        out.append(panel("Demo mode", "<p>" + esc("The experiment registry below is read from the repository "
                                                 "(real manifests). Source health, fees-in-receipt and the "
                                                 "receipt are synthetic.") + "</p>", "stale"))
    missing = _loaded_panel("Experiment registry", exps)
    if missing:
        out.append(missing)
    else:
        rows = [[esc(e["id"]), esc(e["title"]), state_tag(e["status"]),
                 tag("VALID MANIFEST", "ok") if not e["problems"] else esc("; ".join(e["problems"]))]
                for e in exps.value]
        out.append(panel("Experiment registry", table(["id", "title", "status", "manifest validation"], rows,
                                                      wrap=(1, 3))))
        for e in exps.value:
            if e["id"] != "EXP-001":
                continue
            stage = e["stage_a"]
            if stage is None:
                stage_html = '<p class="na">no Stage A result recorded</p>'
            else:
                stage_html = kv([
                    ("verdict", state_tag(stage.get("verdict"))), ("phase", esc(stage.get("phase"))),
                    ("test days", esc(stage.get("n_test_days"))),
                    ("test window", f"{esc(stage.get('test_first'))} to {esc(stage.get('test_last'))}"),
                    ("selected variant", esc(stage.get("selected_variant"))),
                    ("conditions", ul(f"{k}: {'passed' if v else 'not passed' if v is not None else 'unknown'}"
                                      for k, v in (stage.get("conditions") or {}).items())),
                    ("dataset sha256", esc(stage.get("dataset_sha256"))),
                ] + ([("error", esc(stage["error"]))] if stage.get("error") else []))
            out.append(panel("EXP-001 — " + str(e["title"] or ""), kv([
                ("status", state_tag(e["status"])),
                ("Stage A (historical probability validation)", stage_html),
                ("Stage B (live shadow)", esc("research evidence accrues only from VALID live days; see Overview")),
                ("gate reports in the repository (names only)", ul(e["reports"])),
            ]) + '<p class="note">A Stage A PASS is a probability-validation result, not a trading edge.</p>'))
    health = ctx.source_health
    missing = _loaded_panel("Source health (latest per source)", health)
    if missing:
        out.append(missing)
    else:
        rows = []
        for h in health.value:
            fresh, delta = d.freshness(h.get("completed_at_utc"), ctx.now)
            rows.append([esc(h.get("source_id")), state_tag(h.get("status")), esc(h.get("completed_at_utc")),
                         age(delta), state_tag(fresh), esc(h.get("last_ok_at_utc")), esc(h.get("records")),
                         esc(h.get("http_errors")), esc(h.get("retries")), esc(h.get("error"))])
        out.append(panel("Source health (latest per source)", table(
            ["source", "status", "completed", "age", "freshness (26 h)", "last ok", "records", "http errors",
             "retries", "error"], rows, wrap=(9,))))
    fees = d.fee_rows(ctx.now)
    fee_rows = [[esc(f["schedule_id"]) + (" " + tag("ACTIVE", "nd") if f["active"] else ""), esc(f["venue"]),
                 state_tag(f["status"]), state_tag(f["claim_basis"]), esc(f["checked_at_utc"]),
                 esc(f["recheck_by_utc"]), esc(f["detail"]), esc(f["evidence"])]
                for f in fees]
    body = ('<p class="note">Current view: the verification known now. Each decision carries the basis known '
            'when it was made; nothing earlier is restated.</p>'
            + table(["schedule", "venue", "verification", "claim basis", "verified at", "re-check by", "detail",
                     "evidence"], fee_rows, wrap=(6, 7)))
    for f in fees:
        if f["components"]:
            body += (f"<h3>Components of {esc(f['verification_id'])}</h3>" + table(
                ["component", "state", "detail", "evidence"],
                [[esc(c["component"]), state_tag(c["state"]), esc(c["detail"]), esc(c["evidence"])]
                 for c in f["components"]], wrap=(2, 3)))
    if ctx.receipt.status == d.OK and isinstance(ctx.receipt.value.get("fee"), dict):
        fee = ctx.receipt.value["fee"]
        body += "<h3>As reported by the latest pipeline receipt</h3>" + kv([
            ("schedule", esc(fee.get("schedule_id"))), ("status", state_tag(fee.get("status"))),
            ("claim basis", state_tag(fee.get("claim_basis"))),
            ("claim allowed (lower bound only)", esc(fee.get("claimable"))),
            ("allowance per contract", esc(fee.get("claim_allowance_per_contract")))])
    out.append(panel("Fee schedule verification", body))
    out.append(panel("Venue capability registry", '<p class="note">' + esc(
        "What each venue's documented interface could do, and what this repository has shown with evidence. "
        "Code existing is not a connection; only LIVE_DATA_VERIFIED rows rest on recorded reads. Execution is "
        "not authorized for any venue.") + "</p>" + table(
        ["venue", "kind", "capability", "stage", "auth required", "execution authorized", "evidence"],
        [[esc(r["venue_id"]), esc(r["kind"]), esc(r["capability"]), state_tag(r["stage"]), esc(r["auth_required"]),
          esc(r["execution_authorized"]), esc(r["evidence"])] for r in d.venue_rows()], wrap=(6,))))
    out.append(receipt_panel(ctx, detail=True))
    return "".join(out)


PAGES = {
    "/": ("Overview", overview),
    "/opportunities": ("Opportunities", opportunities),
    "/positions": ("Positions & performance", positions),
    "/outcome-board": ("Outcome Board", outcome_board),
    "/risk": ("Risk & capital", risk_view),
    "/experiments": ("Experiments & sources", experiments_view),
}
