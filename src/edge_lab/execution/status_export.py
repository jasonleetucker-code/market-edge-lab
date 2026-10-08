"""A sanitized, versioned, read-only projection of the execution journal for the operator Terminal (ADR 0043).

The dashboard never imports this package. It reads the JSON file this module writes, the same way it reads the
Freshness Fabric's `freshness.json` from the status directory. So the projection is the whole interface:

- **Versioned.** `schema` is `SCHEMA`. A reader refuses any other value.
- **Labelled.** `environment` names the scope's environment (today only FIXTURE can exist). Every section is about
  that environment and nothing else; a FIXTURE export never describes a real account.
- **Sanitized.** Fields are copied by allowlist, never by dumping a record: no approval nonce, request digest,
  receipt payload, venue order id, key, signature or credential is ever included. Attempt and reservation ids are
  kept (incidents name them); they embed the client order id, which is derived from the intent and is no
  credential. Free text (reasons, details, log lines) passes through `redaction.redact_text`, and the finished
  text is refused (`ExportRefused`) if it still matches `redaction.contains_secret` or a PEM header.
- **Exact.** No float anywhere: money, prices and quantities are canonical Decimal text (`model.decimal_text`).
  Integers are counts, sequence numbers or revisions only.
- **Unknown stays unknown.** A value the journal does not hold is None (or the string "UNKNOWN" for a state), never
  0 and never an empty list. A known empty list means the journal was read and holds none.
- **Bounded.** Each list keeps its newest `MAX_ROWS` (or `MAX_LOG`) items and states how many were left out.

`build_status` reads one open journal. `status_for_path` opens a journal file read-only in effect: it refuses a
missing file instead of letting SQLite create one, and turns any journal failure into an ERROR state instead of
raising. `render` validates and serializes; `write_status` writes atomically. Nothing here sends, reserves,
approves or arms anything: arm readiness is judged with the pure `control.decide_arm`, and nothing is persisted.

The export is assembled from several journal reads, each consistent on its own (the account snapshot and its held
reservations are one read). `generated_at_utc` is the time of assembly; the dashboard judges the export's own age
from it, and the snapshot's age separately.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .. import redaction
from ..freshness import assess as assess_freshness
from . import control as ctl
from .journal import AttemptState, ExecutionJournal, JournalError
from .model import (AUTHORIZED_ENVIRONMENTS, AccountScope, Environment, canonical_json, decimal_text,
                    environment_authorized, utc_text)
from .orchestrator import CYCLE_SCHEMA, OrchestratorConfig
from .reservations import CorruptRecord, ReservationError, ReservationView
from .risk_gate import PLACEHOLDER_ID

SCHEMA = "edge-lab-execution-status/1"
FILENAME = "execution_status.json"  # beside freshness.json in the status directory
MAX_ROWS = 50
MAX_LOG = 30
MAX_REFUSALS = 5
MAX_BYTES = 1_000_000  # under the dashboard's 2 MB status-file cap
EXPORT_OPERATOR_REF = "status-export"  # the label on the hypothetical arm requests judged for arm readiness
ENVIRONMENT_NOTES = (  # (environment, what it is), in display order
    ("FIXTURE", "fake transport and a disposable store; no real account"),
    ("DEMO", "the venue's mock-funds environment"),
    ("PRODUCTION", "the real-money account"),
)
OMITTED = ("approval nonces", "request digests", "receipt payloads", "venue order ids", "keys, signatures and "
           "credentials (the journal holds none)")
_PEM = re.compile(r"-----BEGIN [A-Z ]*-----")
_REDACTED_VALUE = re.compile(r"\s*[:=]\s*" + re.escape(redaction.REDACTED) + r"(?![A-Za-z0-9_])")
_ABS_PATH = re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|/)(?:[^\s\\/:'\"]+[\\/])+[^\s\\/:'\"]*")  # absolute paths only


class ExportRefused(ValueError):
    """The projection failed validation (a float, a secret-looking string, a foreign schema or its size bound).
    Nothing was written."""


# ------------------------------------------------------------------ small helpers


def _text(value: Decimal | None) -> str | None:
    return None if value is None else decimal_text(value)


def _free(value: Any, limit: int = 300) -> str | None:
    """Free text from the journal: redacted, paths reduced to their last name, bounded."""
    if value is None:
        return None
    text = _ABS_PATH.sub(lambda m: m.group(0).rstrip("\\/").replace("\\", "/").rsplit("/", 1)[-1] or "(path)",
                         redaction.redact_text(str(value)))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _short_error(exc: BaseException) -> str:
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {_free(first, 200)}" if first else type(exc).__name__


def _tail(items: list, limit: int) -> tuple[list, int]:
    """The newest `limit` items (in their order) and how many older ones were left out."""
    return (items[-limit:], max(0, len(items) - limit)) if limit else ([], len(items))


def _count(body: Mapping[str, Any], key: str) -> int | None:
    """The length of a record's list field, or None when the field is absent or not a list (unknown, never 0)."""
    value = body.get(key)
    return len(value) if isinstance(value, (list, tuple)) else None


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def _money_field(value: Any) -> Any:
    """A record's money field as exact text: Decimal text stays; an int (whole cents or units) becomes text."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ExportRefused("a boolean where money was expected")
    if isinstance(value, (int, Decimal)):
        return decimal_text(Decimal(value))
    raise ExportRefused(f"money field of type {type(value).__name__}")


def _pick(body: Mapping[str, Any], text_fields: tuple[str, ...] = (), money: tuple[str, ...] = (),
          free: tuple[str, ...] = (), lists: tuple[str, ...] = ()) -> dict[str, Any]:
    """An allowlisted copy of a record body. Absent fields are None (unknown), never 0."""
    out: dict[str, Any] = {}
    for name in text_fields:
        value = body.get(name)
        out[name] = value if value is None or isinstance(value, (str, int, bool)) else str(value)
    for name in money:
        out[name] = _money_field(body.get(name))
    for name in free:
        out[name] = _free(body.get(name))
    for name in lists:
        value = body.get(name)
        out[name] = None if value is None else [_free(v) for v in value]
    return out


# ------------------------------------------------------------------ sections


def _environments(scope: AccountScope) -> dict[str, Any]:
    authorized = sorted(e.value for e in AUTHORIZED_ENVIRONMENTS)
    return {"scope_environment": scope.environment.value,
            "scope_environment_authorized": environment_authorized(scope.environment),
            "authorized": authorized,
            "rows": [{"environment": name, "authorized": name in authorized, "note": note}
                     for name, note in ENVIRONMENT_NOTES if name in {e.value for e in Environment}]}


def _grant_summary(grant: ctl.AutomationGrant, scope: AccountScope, now: datetime) -> dict[str, Any]:
    lim = grant.limits
    return {"digest": grant.digest(), "environment": grant.environment.value, "scope_key": grant.scope_key,
            "venue": grant.venue, "strategy_id": grant.strategy_id, "strategy_version": grant.strategy_version,
            "model_hash": grant.model_hash, "policy_hash": grant.policy_hash,
            "risk_policy_version": grant.risk_policy_version, "fee_schedule_version": grant.fee_schedule_version,
            "profile_version": grant.profile_version, "universe": sorted(grant.universe),
            "allowed_kinds": sorted(k.value for k in grant.allowed_kinds),
            "limits": {"max_order_cost": _text(lim.max_order_cost), "max_event_exposure": _text(lim.max_event_exposure),
                       "max_total_exposure": _text(lim.max_total_exposure),
                       "max_daily_turnover": _text(lim.max_daily_turnover), "max_daily_loss": _text(lim.max_daily_loss),
                       "max_drawdown": _text(lim.max_drawdown)},
            "issued_at_utc": grant.issued_at_utc, "expires_at_utc": grant.expires_at_utc,
            "issuer_ref": grant.issuer_ref, "validity_problems": grant.validity_problems(scope, now)}


def _control(journal: ExecutionJournal, scope: AccountScope, now: datetime,
             config: OrchestratorConfig | None) -> tuple[dict[str, Any], ctl.ControlState]:
    events = journal.control_events(scope)
    state = ctl.replay(scope, events)
    raised = {e.incident_id: (e.reason, e.at_utc) for e in events if isinstance(e, ctl.IncidentRaised)}
    for e in events:  # `control.reduce` raises these itself, named after the observation's time
        if isinstance(e, ctl.ReconciliationObserved) and e.status is not ctl.Reconciliation.COMPLETE:
            key = "reconciliation-lost:" + re.sub(r"[^A-Za-z0-9]", "", e.at_utc)
            raised.setdefault(key, (f"reconciliation {e.status.value} while in SHADOW or a sending mode"
                                    + (f": {e.detail}" if e.detail else ""), e.at_utc))
    incidents = []
    for incident_id in state.open_incidents:
        reason, at = raised.get(incident_id, (None, None))
        incidents.append({"incident_id": incident_id, "reason": _free(reason), "raised_at_utc": at})
    set_events = {(e.scope, e.key): e for e in events if isinstance(e, ctl.SetLatch)}
    latches = []
    for scope_name, key in sorted(state.latches, key=lambda x: (x[0].value, x[1])):
        event = set_events.get((scope_name, key))
        latches.append({"scope": scope_name.value, "key": key, "reason": None if event is None else _free(event.reason),
                        "set_at_utc": None if event is None else event.at_utc})
    closeouts = [{"scope": s.value, "key": k, "expires_at_utc": exp}
                 for s, k, exp in sorted(state.closeouts, key=lambda x: (x[0].value, x[1], x[2]))]
    refusals, refusals_omitted = _tail([e for e in events if isinstance(e, ctl.ArmRefused)], MAX_REFUSALS)
    starts = [e for e in events if isinstance(e, ctl.Started)]
    disarms = [e for e in events if isinstance(e, ctl.Disarm)]
    arms = [e for e in events if isinstance(e, ctl.ArmAccepted)]
    recon = [e for e in events if isinstance(e, ctl.ReconciliationObserved)]
    log, log_omitted = _tail(list(state.log), MAX_LOG)
    grants = None if config is None else config.grants
    armed = None
    if state.armed_grant_digest is not None:
        match = next((g for g in grants or () if g.digest() == state.armed_grant_digest), None)
        armed = {"digest": state.armed_grant_digest,
                 "summary": None if match is None else _grant_summary(match, scope, now),
                 "found_in_config": None if grants is None else match is not None}
    readiness = []
    first_grant = None if not grants else grants[0].digest()
    for mode in ctl.Mode:
        if mode is ctl.Mode.DISARMED:
            continue
        request = ctl.ArmRequest(mode, EXPORT_OPERATOR_REF, (), utc_text(now),
                                 first_grant if mode is ctl.Mode.BOUNDED_AUTO else None)
        outcome = ctl.decide_arm(state, request, grants=grants or (), now=now)
        reasons = list(outcome.reasons) if isinstance(outcome, ctl.ArmRefused) else []
        readiness.append({"mode": mode.value, "verdict": "REFUSED" if reasons else "NO_CONTROL_BLOCKER",
                          "reasons": [_free(r) for r in reasons]})
    section = {
        "mode": state.mode.value,
        "reconciliation": state.reconciliation.value,
        "events": len(events),
        "open_incidents": incidents,
        "latches": latches,
        "closeouts": closeouts,
        "armed_grant": armed,
        "last_refusals": [{"mode": e.mode.value, "operator_ref": e.operator_ref, "at_utc": e.at_utc,
                           "reasons": [_free(r) for r in e.reasons]} for e in reversed(refusals)],
        "refusals_omitted": refusals_omitted,
        "last_started_at_utc": starts[-1].at_utc if starts else None,
        "starts": len(starts),
        "last_arm": None if not arms else {"mode": arms[-1].mode.value, "operator_ref": arms[-1].operator_ref,
                                           "at_utc": arms[-1].at_utc, "grant_digest": arms[-1].grant_digest},
        "last_disarm": None if not disarms else {"operator_ref": disarms[-1].operator_ref,
                                                 "reason": _free(disarms[-1].reason), "at_utc": disarms[-1].at_utc},
        "last_reconciliation": None if not recon else {"status": recon[-1].status.value, "at_utc": recon[-1].at_utc,
                                                       "detail": _free(recon[-1].detail) or None},
        "arm_readiness": readiness,
        "log": [_free(line) for line in log],
        "log_omitted": log_omitted,
    }
    return section, state


def _limits(config: OrchestratorConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    policy, gate, ticket = config.risk.policy, config.risk.limits, config.risk.ticket_limits
    placeholder = PLACEHOLDER_ID in (policy.policy_id, gate.limits_id)
    return {
        "placeholder": placeholder,
        "owner_approval_ref": gate.owner_approval_ref,
        "risk_policy": {"policy_id": policy.policy_id, "reserve_floor": _text(policy.reserve_floor),
                        "max_position_risk": _text(policy.max_position_risk),
                        "max_event_risk": _text(policy.max_event_risk),
                        "max_cluster_risk": _text(policy.max_cluster_risk),
                        "max_portfolio_risk": _text(policy.max_portfolio_risk),
                        "daily_loss_limit": _text(policy.daily_loss_limit),
                        "weekly_loss_limit": _text(policy.weekly_loss_limit),
                        "max_drawdown": _text(policy.max_drawdown)},
        "gate_limits": {"limits_id": gate.limits_id, "max_quantity_per_order": _text(gate.max_quantity_per_order),
                        "max_slippage": _text(gate.max_slippage),
                        "max_decision_age_s": _seconds(gate.max_decision_age),
                        "max_source_age_s": _seconds(gate.max_source_age),
                        "daily_new_risk": _text(gate.daily_new_risk),
                        "max_strategy_risk": _text(gate.max_strategy_risk)},
        "ticket_limits": {"max_book_age_s": _seconds(ticket.max_book_age),
                          "max_order_state_age_s": _seconds(ticket.max_order_state_age),
                          "max_orders_per_window": ticket.max_orders_per_window,
                          "order_window_s": _seconds(ticket.order_window),
                          "market_cooldown_s": _seconds(ticket.market_cooldown)},
    }


def _seconds(value: timedelta) -> str:
    return decimal_text(Decimal(value.days * 86400 + value.seconds) + Decimal(value.microseconds) / 1_000_000)


def _bounds(config: OrchestratorConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    b = config.bounds
    return {"max_queued_signals": b.max_queued_signals, "max_signals_per_cycle": b.max_signals_per_cycle,
            "max_proposals_per_cycle": b.max_proposals_per_cycle, "max_intents_per_cycle": b.max_intents_per_cycle,
            "max_requests_per_cycle": b.max_requests_per_cycle, "cycle_deadline_s": _seconds(b.cycle_deadline),
            "max_signal_validity_s": _seconds(b.max_signal_validity), "cycle_interval_s": _seconds(config.cycle_interval),
            "lease_ttl_s": _seconds(config.lease_ttl), "snapshot_max_age_s": _seconds(config.snapshot_max_age),
            "fixture_cash_basis": None if config.fixture_cash_basis is None else config.fixture_cash_basis.value}


def _reservation_row(r: ReservationView) -> dict[str, Any]:
    return {"reservation_id": r.reservation_id, "intent_key": r.intent_key, "market_ticker": r.market_ticker,
            "side": r.side.value, "kind": r.kind.value, "quantity": _text(r.quantity),
            "limit_price": _text(r.limit_price), "filled_quantity": _text(r.filled_quantity),
            "cash_worst_case": _text(r.cash_worst_case), "state": r.state.value,
            "partial": Decimal(0) < r.filled_quantity < r.quantity,
            "release_reason": _enum(r.release_reason), "end_reason": _enum(r.end_reason),
            "ended_at_utc": r.ended_at_utc, "quarantine_reason": _free(r.quarantine_reason),
            "provider_held": r.provider_held, "created_at_utc": r.created_at_utc, "updated_at_utc": r.updated_at_utc,
            "last_fill_at_utc": r.last_fill_at_utc}


def _account(journal: ExecutionJournal, scope: AccountScope, now: datetime,
             config: OrchestratorConfig | None) -> dict[str, Any]:
    view = journal.reservations.account_view(scope)
    snap = view.snapshot
    held = [_reservation_row(r) for r in view.held]
    total = sum((r.cash_worst_case for r in view.held), Decimal(0))
    reserves = {"held": held, "held_count": len(held),
                "held_cash_worst_case_total": _text(total),
                "venue_held_count": sum(1 for r in view.held if r.provider_held),
                "quarantined_count": sum(1 for r in view.held if r.quarantine_reason is not None)}
    if snap is None:
        return {"snapshot": None, "positions": None, "external_orders": None, "reservations": reserves}
    max_age = None if config is None else config.snapshot_max_age
    fresh = "UNKNOWN" if max_age is None else assess_freshness(snap.observed_at_utc, max_age=max_age,
                                                               now=now).value.upper()
    positions = None if snap.positions is None else [
        {"market_ticker": t, "side": s.value, "quantity": _text(q)}
        for (t, s), q in sorted(snap.positions.items(), key=lambda kv: (kv[0][0], kv[0][1].value))]
    externals = None if snap.external_orders is None else [
        {"origin": o.origin.value, "market_ticker": o.market_ticker,
         "side": _enum(o.side), "action": _enum(o.action), "remaining_quantity": _text(o.remaining_quantity),
         "unreflected_cash": _text(o.unreflected_cash)} for o in snap.external_orders]
    return {
        "snapshot": {"revision": snap.revision, "observed_at_utc": snap.observed_at_utc,
                     "recorded_at_utc": snap.recorded_at_utc, "cash": _text(snap.cash),
                     "cash_basis": snap.cash_basis.value, "usable_cash": _text(snap.usable_cash()),
                     "consistent": snap.consistent, "problems": [_free(p) for p in snap.problems],
                     "freshness_at_export": fresh,
                     "max_age_s": None if max_age is None else _seconds(max_age),
                     "attributed_open_orders": len(snap.attributed)},
        "positions": positions,
        "external_orders": externals,
        "reservations": reserves,
    }


def _records(journal: ExecutionJournal, scope: AccountScope) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in journal.control_records(scope):
        out.setdefault(r.record_type, []).append(r)
    return out


def _attempts(journal: ExecutionJournal, records: dict[str, list]) -> dict[str, Any]:
    planned: dict[str, Mapping[str, Any]] = {}
    for r in records.get("INTENT_PLANNED", ()):
        planned[r.body["intent"]["intent_key"]] = r.body["intent"]
    keys = list(planned)
    for a in journal.non_terminal_attempts():
        if a.intent_key not in planned and a.intent_key not in keys:
            keys.append(a.intent_key)
    rows = []
    for key in keys:
        for a in journal.attempts_for(key):
            try:
                r = journal.reservations.reservation(a.reservation_id)
            except (ReservationError, CorruptRecord):
                r = None
            intent = planned.get(a.intent_key) or {}
            quantity = r.quantity if r is not None else None
            filled = r.filled_quantity if r is not None else None
            rows.append({
                "attempt_id": a.attempt_id, "intent_key": a.intent_key, "attempt_no": a.attempt_no,
                "strategy_id": intent.get("strategy_id"),
                "market_ticker": r.market_ticker if r is not None else intent.get("market_ticker"),
                "side": r.side.value if r is not None else intent.get("side"),
                "action": intent.get("action"),
                "kind": r.kind.value if r is not None else intent.get("kind"),
                "quantity": _text(quantity) if r is not None else intent.get("quantity"),
                "limit_price": _text(r.limit_price) if r is not None else intent.get("limit_price"),
                "time_in_force": intent.get("time_in_force"),
                "state": a.state.value, "state_reason": _free(a.state_reason),
                "filled_quantity": _text(filled),
                "partial": None if r is None else Decimal(0) < r.filled_quantity < r.quantity,
                "reservation_state": None if r is None else r.state.value,
                "release_reason": None if r is None else _enum(r.release_reason),
                "end_reason": None if r is None else _enum(r.end_reason),
                "quarantine_reason": None if r is None else _free(r.quarantine_reason),
                "created_at_utc": a.created_at_utc, "updated_at_utc": a.updated_at_utc})
    rows.sort(key=lambda x: (x["created_at_utc"], x["attempt_id"]))
    counts = {s.value: 0 for s in AttemptState}
    for row in rows:
        counts[row["state"]] += 1
    unknown = [row for row in rows if row["state"] == AttemptState.OUTCOME_UNKNOWN.value]
    in_flight = [row for row in rows if row["state"] in (AttemptState.PENDING_EGRESS.value, AttemptState.SENT.value)]
    shown, omitted = _tail(rows, MAX_ROWS)
    return {"total": len(rows), "by_state": counts, "rows": list(reversed(shown)), "rows_omitted": omitted,
            "unknown": unknown[-MAX_ROWS:], "in_flight": in_flight[-MAX_ROWS:],
            "partial_orders": sum(1 for row in rows if row["partial"]),
            "partial_reductions": sum(1 for row in rows if row["kind"] == "REDUCTION" and row["partial"])}


_CYCLE_FIELDS = ("cycle", "started_at_utc", "mode_at_start", "mode_at_end", "reconciliation", "snapshot_revision",
                 "requests_used", "signals_rejected", "proposals", "proposals_ignored", "fills_recorded",
                 "deadline_hit", "fixture_cash_basis", "schema")


def _cycles(records: dict[str, list]) -> dict[str, Any]:
    cycles = records.get("CYCLE", [])
    if not cycles:
        return {"count": 0, "last": None, "last_recorded_at_utc": None}
    last = cycles[-1]
    body = _pick(last.body, text_fields=_CYCLE_FIELDS, lists=("incidents", "released", "resolved_unknown"))
    body["signals"] = {str(k): v for k, v in (last.body.get("signals") or {}).items() if isinstance(v, int)}
    body["decisions"] = _count(last.body, "decisions")
    body["schema_known"] = last.body.get("schema") == CYCLE_SCHEMA
    return {"count": len(cycles), "last": body, "last_recorded_at_utc": last.at_utc}


def _decisions(records: dict[str, list]) -> dict[str, Any]:
    rows, omitted = _tail(records.get("DECISION", []), MAX_ROWS)
    out = []
    for r in reversed(rows):
        row = _pick(r.body, text_fields=("cycle", "mode", "intent_key", "strategy_id", "market_ticker", "kind",
                                         "outcome", "attempt_id", "attempt_state"), lists=("reasons",))
        row["recorded_at_utc"] = r.at_utc
        out.append(row)
    counts: dict[str, int] = {}
    for r in records.get("DECISION", []):
        counts[str(r.body.get("outcome"))] = counts.get(str(r.body.get("outcome")), 0) + 1
    return {"rows": out, "rows_omitted": omitted, "by_outcome": dict(sorted(counts.items()))}


def _pnl(records: dict[str, list]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for r in records.get("PNL_OBSERVATION", []):
        latest[r.body["ticker"]] = r
    baseline = bool(records.get("PNL_BASELINE"))
    by_market = [{"market_ticker": t, "realized_pnl": _money_field(r.body.get("realized_pnl")),
                  "observed_at_utc": r.body.get("at_utc"), "cycle": r.body.get("cycle")}
                 for t, r in sorted(latest.items())]
    total = None
    if baseline:
        total = decimal_text(sum((Decimal(row["realized_pnl"]) for row in by_market), Decimal(0)))
    return {"baseline_recorded": baseline, "by_market": by_market, "realized_total": total,
            "basis": "venue-reported cumulative realized P&L per market, read at COMPLETE reconciliations",
            "unrealized": None, "unrealized_note": "not computed: no mark source in the execution package"}


def _settlements(records: dict[str, list]) -> dict[str, Any]:
    rows, omitted = _tail(records.get("SETTLEMENT", []), MAX_ROWS)
    out = []
    for r in reversed(rows):
        row = _pick(r.body, text_fields=("ticker", "source", "event_ticker", "market_result", "settled_time", "cycle"),
                    money=("yes_count", "no_count", "yes_total_cost", "no_total_cost", "fee_cost"),
                    lists=("missing",))
        cents = r.body.get("revenue_cents")
        row["revenue"] = None if cents is None else decimal_text(Decimal(int(cents)) / 100)
        row["recorded_at_utc"] = r.at_utc
        out.append(row)
    return {"rows": out, "rows_omitted": omitted, "count": len(records.get("SETTLEMENT", []))}


def _attribution(records: dict[str, list]) -> dict[str, Any]:
    rows, omitted = _tail(records.get("ATTRIBUTION", []), MAX_ROWS)
    out = []
    for r in reversed(rows):
        row = _pick(r.body, text_fields=("attempt_id", "intent_key", "strategy_id", "market_ticker", "side", "kind",
                                         "release_reason", "fees_complete", "cycle"),
                    money=("filled_quantity", "notional", "fees_known"))
        row["fill_count"] = _count(r.body, "fill_ids")
        row["recorded_at_utc"] = r.at_utc
        out.append(row)
    return {"rows": out, "rows_omitted": omitted, "count": len(records.get("ATTRIBUTION", []))}


def _service(records: dict[str, list]) -> dict[str, Any]:
    boots, shutdowns = records.get("BOOT", []), records.get("SHUTDOWN", [])
    last_boot = boots[-1] if boots else None
    last_shutdown = shutdowns[-1] if shutdowns else None
    if last_boot is None:
        state = "NEVER_STARTED"
    elif last_shutdown is not None and last_shutdown.seq > last_boot.seq:
        state = "SHUTDOWN_RECORDED"
    else:
        state = "STARTED_NO_SHUTDOWN_RECORDED"
    return {
        "state": state,
        "boots": len(boots),
        "last_boot": None if last_boot is None else {
            "at_utc": last_boot.at_utc, "worker_id": last_boot.body.get("worker_id"),
            "fence_token": last_boot.body.get("fence_token"),
            "grant_digests": list(last_boot.body.get("grants") or ()),
            "non_terminal_attempts": _count(last_boot.body, "non_terminal_attempts"),
            "backlog_quarantined": _count(last_boot.body, "backlog_quarantined"),
            "fixture_cash_basis": last_boot.body.get("fixture_cash_basis")},
        "last_shutdown": None if last_shutdown is None else {
            "at_utc": last_shutdown.at_utc, "operator_ref": last_shutdown.body.get("operator_ref"),
            "reason": _free(last_shutdown.body.get("reason")),
            "cancel_owned": last_shutdown.body.get("cancel_owned"),
            "resting_left": _count(last_shutdown.body, "resting_left")},
    }


# ------------------------------------------------------------------ assembly


def _base(scope: AccountScope, now: datetime, config: OrchestratorConfig | None) -> dict[str, Any]:
    return {"schema": SCHEMA, "generated_at_utc": utc_text(now), "environment": scope.environment.value,
            "scope_key": scope.key(), "environments": _environments(scope),
            "config_supplied": config is not None, "omitted_by_design": list(OMITTED)}


def build_status(journal: ExecutionJournal, scope: AccountScope, *, now: datetime,
                 config: OrchestratorConfig | None = None) -> dict[str, Any]:
    """The projection of one open journal for `scope`. `config` (the running orchestrator's) supplies limits, bounds,
    grants and the snapshot age bound; without it those are None (unknown). Journal failures propagate."""
    if not isinstance(scope, AccountScope):
        raise ValueError("scope must be an AccountScope")
    if config is not None and (not isinstance(config, OrchestratorConfig) or config.scope != scope):
        raise ValueError("config must be the OrchestratorConfig of this scope")
    out = _base(scope, now, config)
    chain = journal.verify_chain()
    control_section, _ = _control(journal, scope, now, config)
    records = _records(journal, scope)
    out.update({
        "journal": {"state": "OK", "detail": None, "chain_ok": chain.ok, "chain_events": chain.events,
                    "chain_problems": [_free(p) for p in chain.problems[:MAX_LOG]]},
        "service": _service(records),
        "control": control_section,
        "grants": {"configured": None if config is None else [_grant_summary(g, scope, now) for g in config.grants],
                   "note": "No grant is issued by this package; a grant is an owner decision recorded in "
                           "EXECUTION_PLAN."},
        "limits": _limits(config),
        "bounds": _bounds(config),
        "account": _account(journal, scope, now, config),
        "attempts": _attempts(journal, records),
        "decisions": _decisions(records),
        "cycles": _cycles(records),
        "pnl": _pnl(records),
        "settlements": _settlements(records),
        "attribution": _attribution(records),
    })
    return out


def status_for_path(path: str | Path, scope: AccountScope, *, now: datetime,
                    config: OrchestratorConfig | None = None) -> dict[str, Any]:
    """The projection of the journal file at `path`. A missing or empty file is NO_JOURNAL (never created here);
    any journal failure is ERROR with a short, redacted reason. It never raises for a journal problem."""
    p = Path(path)
    out = _base(scope, now, config)
    try:
        exists = p.is_file() and p.stat().st_size > 0
    except OSError as exc:
        out["journal"] = {"state": "ERROR", "detail": _short_error(exc)}
        return out
    if not exists:
        out["journal"] = {"state": "NO_JOURNAL", "detail": f"no execution journal at {p.name}"}
        return out
    try:
        with ExecutionJournal.open(p) as journal:
            return build_status(journal, scope, now=now, config=config)
    except (JournalError, ReservationError, CorruptRecord, KeyError, TypeError, ValueError) as exc:
        out["journal"] = {"state": "ERROR", "detail": _short_error(exc)}
        return out


# ------------------------------------------------------------------ validation and writing


def _check(value: Any, where: str = "$") -> None:
    if isinstance(value, float):
        raise ExportRefused(f"a float at {where}: money and quantities are exact text")
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ExportRefused(f"a non-text key at {where}")
            _check(v, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check(v, f"{where}[{i}]")
    elif not (value is None or isinstance(value, (str, int, bool))):
        raise ExportRefused(f"a {type(value).__name__} at {where}")


def render(status: Mapping[str, Any]) -> str:
    """Validate and serialize: the schema, no float or other non-JSON value, no secret-looking text, the size bound."""
    if not isinstance(status, Mapping) or status.get("schema") != SCHEMA:
        raise ExportRefused(f"not a {SCHEMA} projection")
    _check(status)
    text = canonical_json(status)
    probe = _REDACTED_VALUE.sub("", text)  # a value already replaced by `redact_text` is not a secret
    if redaction.contains_secret(probe) or _PEM.search(text):
        raise ExportRefused("the projection contains text that looks like a secret")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ExportRefused(f"the projection is larger than {MAX_BYTES} bytes")
    json.loads(text)  # round-trips
    return text + "\n"


def write_status(status: Mapping[str, Any], out_path: str | Path) -> Path:
    """Write `render(status)` atomically (a temporary file in the same directory, fsync, then replace)."""
    text = render(status)
    target = Path(out_path)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
