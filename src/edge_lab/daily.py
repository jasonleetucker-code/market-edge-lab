"""Daily shadow operation for EXP-001 Stage B: one bounded, idempotent orchestration run.

`run` reuses the existing engines and adds no trading logic of its own:

1. Takes the collector lock (`<db>.forward.lock`, shared with the forward captures, so it
   never overlaps a capture and shares one Kalshi pacing budget per host), then the
   ledger lock (`<ledger>.lock`, shared with backups and manual `shadow` commands).
2. Opens the evidence store **read-only** (`SnapshotStore.open_readonly`): analysis never
   creates, migrates or changes it.
3. Finds the closed capture days in date order. For each one, it first settles positions
   whose settlement evidence had been received by that day's decision time. Then it runs
   `exp001_shadow.run_day`, which records decisions and fills for the research and
   operational accounts. Catch-up therefore follows modeled time: evidence received later
   never funds an earlier fill, and the ledger also enforces this with `state_as_of`.
4. Optionally (`refresh_settlements=True`), refreshes official settlement evidence for the
   pending events only, through the collector's existing write path. This step is
   bounded: a limited number of events, pacing, bounded retries and a deadline.
5. Settles every position with conclusive, compatible evidence. Missing or conflicting
   evidence leaves it pending.
6. Computes the account, risk and Outcome Board summaries with the canonical functions.
7. Writes a receipt atomically and returns an explicit exit code.

Decision logic never sees settlement labels or later quotes: `run_day` reads the day's
decision and re-check captures only, and settlement is a separate stage.

States and exit codes:

| State | Exit code |
|---|---|
| HEALTHY_TRADED, HEALTHY_NO_SIGNAL, PENDING_SETTLEMENT, NO_CAPTURE, NOT_CLOSED | 0 |
| INVALID_CAPTURE (the latest closed capture day is INVALID; nothing filled) | 3 |
| FAILED, LOCK_BUSY | 1 |

Timestamps are kept apart:
- `generated_at_utc` is processing time;
- each day's `decision_time_utc` is event (modeled) time;
- settlement entries carry `evidence_available_utc` (receipt of the evidence); processing
  time is each ledger row's `appended_at_utc` (outside the hash, so replays stay identical).
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import exp001_shadow as shadow
from . import forward, outcome_board, risk
from .shadow_ledger import LedgerError, ShadowLedger
from .storage import SnapshotStore

RECEIPT_SCHEMA = "edge-lab-shadow-daily-receipt/1"
RECEIPT_NAME = "shadow_daily.json"
EXIT = {"HEALTHY_TRADED": 0, "HEALTHY_NO_SIGNAL": 0, "PENDING_SETTLEMENT": 0, "NO_CAPTURE": 0, "NOT_CLOSED": 0,
        "INVALID_CAPTURE": 3, "SETTLEMENT_CONFLICT": 1, "FAILED": 1, "LOCK_BUSY": 1}
# Settlement for D is normally published the morning after D. Asking earlier wastes
# requests, so an event becomes "due" 30 h after its decision time (about 00:00 ET on D+1).
SETTLEMENT_DUE_AFTER = timedelta(hours=30)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


def closed_capture_days(store: SnapshotStore, now: datetime, *, mode: str = "live") -> list[date]:
    """Every target date with at least one stored capture whose windows have closed, oldest first."""
    last = forward.last_closed_target(now)
    return sorted({d for d in (date.fromisoformat(r["target_date"]) for r in store.forward_captures(mode=mode))
                   if d <= last})


def processed_days(ledger: ShadowLedger, account_id: str) -> set[date]:
    """Days with at least one recorded decision in the account (slot = 'D|market|side')."""
    if account_id not in ledger.accounts():
        return set()
    return {date.fromisoformat(s.split("|", 1)[0]) for s in ledger.state(account_id).decision_slots}


RECHECK_RECENT_DAYS = 7  # the latest capture days are always re-run (idempotent) to heal a crash


def incomplete_days(ledger: ShadowLedger, account_id: str) -> set[date]:
    """Days with a qualified decision that has no fill entry (a crash between the two)."""
    if account_id not in ledger.accounts():
        return set()
    decisions, filled = {}, set()
    for row in ledger.entries(account_id):
        payload = json.loads(row["payload_json"])
        if row["kind"] == "decision" and payload.get("qualification") == "QUALIFY" and payload.get("slot"):
            decisions[payload["decision_id"]] = date.fromisoformat(payload["slot"].split("|", 1)[0])
        elif row["kind"] == "fill":
            filled.add(payload["decision_id"])
    return {d for did, d in decisions.items() if did not in filled}


def missing_capture_days(days: list[date], last_closed: date) -> list[date]:
    """Closed target dates since the first stored capture that have no capture at all."""
    if not days:
        return []
    have, out, d = set(days), [], days[0]
    while d <= last_closed:
        if d not in have:
            out.append(d)
        d += timedelta(days=1)
    return out


def settlement_cutoff(store: SnapshotStore, ledger: ShadowLedger, now: datetime, *, model=None) -> datetime:
    """The latest evidence-receipt time settlements may use now.

    While a closed capture day that can still produce fills is unprocessed or incomplete in
    either account, settling on evidence received after that day's decision would record
    cash movements its fills must precede, and the ledger (knowledge-time order) would then
    refuse those fills forever. So settlement is capped at the earliest such day's decision
    time until it is done. A day with no qualifying opportunity (for example a capture that
    stored no markets) can never fill, so it never holds settlement back."""
    from . import exp001_stageb

    days = closed_capture_days(store, now)
    done = processed_days(ledger, shadow.RESEARCH_ACCOUNT_ID) & processed_days(ledger, shadow.ACCOUNT_ID)
    broken = incomplete_days(ledger, shadow.RESEARCH_ACCOUNT_ID) | incomplete_days(ledger, shadow.ACCOUNT_ID)
    for day in days:
        if day in broken:
            return forward.windows(day)["decision"]
        if day not in done:
            evaluation = exp001_stageb.evaluate_day(store, day, model=model)
            if any(o.qualification == "QUALIFY" for o in evaluation.opportunities):
                return forward.windows(day)["decision"]
    return now


def _previous_receipt(status_dir: Path | None) -> dict[str, Any] | None:
    if status_dir is None:
        return None
    try:
        return json.loads((status_dir / RECEIPT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pending_event_tickers(ledger: ShadowLedger, now: datetime) -> list[str]:
    """Kalshi event tickers of open positions whose settlement is due (see SETTLEMENT_DUE_AFTER)."""
    from .kalshi import event_ticker_of

    tickers: set[str] = set()
    for account in shadow.ACCOUNTS:
        if account.account_id not in ledger.accounts():
            continue
        for p in ledger.state(account.account_id).open_positions():
            opened = datetime.fromisoformat(p.opened_at_utc)
            if now - opened >= SETTLEMENT_DUE_AFTER - timedelta(minutes=15):  # opened ~10 min after decision
                tickers.add(event_ticker_of(p.market_id.split(":", 1)[1]))
    return sorted(tickers)


def _refresh(db: Path, ledger: ShadowLedger, now: datetime, *, max_events: int, deadline_s: float) -> dict[str, Any]:
    """Targeted settlement refresh through the collector's write path, with source health recorded."""
    from .cli import _run_source
    from .kalshi import refresh_event_settlements

    tickers = pending_event_tickers(ledger, now)
    if not tickers:
        return {"status": "skipped", "events_requested": 0, "markets_stored": 0, "errors": [],
                "reason": "no open position is due for settlement"}
    store = SnapshotStore(db)  # the authorized evidence write path (collection), not analysis
    run_id = f"settlement-refresh-{uuid.uuid4()}"
    store.start_run(run_id)
    outcome: dict[str, Any] = {}
    try:
        outcome = _run_source(store, run_id=run_id, source_id="kalshi_settlement",
                              collect=lambda anomalies: refresh_event_settlements(
                                  store, run_id=run_id, event_tickers=tickers, max_events=max_events,
                                  deadline_s=deadline_s, anomalies=anomalies))
    finally:
        status = outcome.get("status")
        store.finish_run(run_id, status={"ok": "succeeded", "partial": "partial"}.get(status, "failed"),
                         error=None if status == "ok" else (outcome.get("error") or "see source_health"))
    counts = outcome.get("counts") or {}
    return {"status": status or "failed", "run_id": run_id, "events_requested": counts.get("events_requested", 0),
            "markets_stored": counts.get("markets", 0), "settled_markets": counts.get("settled_markets", 0),
            "errors": [e for e in [outcome.get("error")] if e] + list(outcome.get("anomalies") or [])}


def _summaries(ledger: ShadowLedger, now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for account in shadow.ACCOUNTS:
        if account.account_id not in ledger.accounts():
            out[account.account_id] = {"status": "NOT_STARTED"}
            continue
        state = ledger.state(account.account_id)
        entry: dict[str, Any] = {
            "role": "research (frozen EXP-001 rule)" if account.risk_policy is None else "operational",
            "equity_basis": "cost basis (no liquidation marks)",
            "starting_bankroll_notional": str(state.starting_bankroll), "equity": str(state.equity),
            "settled_cash": str(state.settled_cash), "committed_capital": str(state.committed_capital),
            "open_positions": len(state.open_positions()), "fills": state.fills, "no_fills": state.no_fills,
            "settlements": state.settlements, "realized_pnl": str(state.realized_pnl),
            "no_fill_reasons": dict(sorted(state.no_fill_reasons.items())),
        }
        if account.risk_policy is not None:
            report = risk.assess(state, account.risk_policy, now)
            entry["risk"] = {"remaining_risk_capacity": str(report.remaining_risk_capacity),
                             "new_risk_allowed": report.new_risk_allowed, "breaches": list(report.breaches),
                             "open_worst_case_risk": str(report.open_worst_case_risk)}
            entry["outcome_board_groups"] = len(outcome_board.build_board(state, now))
        out[account.account_id] = entry
    return out


def _write_receipt(status_dir: Path | None, receipt: dict[str, Any]) -> None:
    if status_dir is None:
        return
    status_dir.mkdir(parents=True, exist_ok=True)
    target = status_dir / RECEIPT_NAME
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The receipt is a non-sensitive summary meant for the status directory; the service
    # runs with UMask 0077 so the ledger stays private, and only the receipt is opened up.
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)


def run(db: Path, ledger_path: Path, *, status_dir: Path | None = None, now: datetime | None = None,
        refresh_settlements: bool = False, max_events: int = 10, deadline_s: float = 120.0,
        lock_timeout_s: float = 60.0, model=None, code_version: str | None = None,
        clock: Callable[[], datetime] | None = None) -> tuple[dict[str, Any], int]:
    """One daily orchestration run. Returns (receipt, exit_code). Never raises for an
    operational failure: it is recorded as FAILED in the receipt."""
    now = now or (clock or (lambda: datetime.now(timezone.utc)))()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "generated_at_utc": _iso(now), "code_version": code_version,
        "state": "FAILED", "exit_code": 1, "days": [],
        "settlement": {"refresh": {"status": "not_requested" if not refresh_settlements else "not_run"},
                       "settled": 0, "pending": []},
        "fee": shadow.fee_fields(), "accounts": {}, "problems": [],
    }
    receipt["fee"]["schedule_id"] = receipt["fee"].pop("fee_schedule_id")
    receipt["fee"]["status"] = receipt["fee"].pop("fee_status")
    if not db.is_file():
        receipt["state"] = "NO_CAPTURE"
        receipt["problems"].append("evidence store does not exist yet")
        return _finish(status_dir, receipt)
    with ExitStack() as stack:
        try:
            stack.enter_context(forward.exclusive_lock(db.with_name(db.name + ".forward.lock"),
                                                       timeout_s=lock_timeout_s))
            stack.enter_context(forward.exclusive_lock(ledger_path.with_name(ledger_path.name + ".lock"),
                                                       timeout_s=lock_timeout_s))
        except forward.LockBusy as exc:
            receipt["state"] = "LOCK_BUSY"
            receipt["problems"].append(str(exc))
            return _finish(status_dir, receipt)
        except Exception as exc:  # noqa: BLE001 - e.g. a lock file that cannot be opened
            receipt["state"] = "FAILED"
            receipt["problems"].append(f"lock: {type(exc).__name__}: {exc}")
            return _finish(status_dir, receipt)
        try:
            _run_locked(db, ledger_path, now, receipt, refresh_settlements=refresh_settlements,
                        max_events=max_events, deadline_s=deadline_s, model=model)
        except Exception as exc:  # noqa: BLE001 - every failure ends in an explicit FAILED receipt
            receipt["state"] = "FAILED"
            receipt["problems"].append(f"{type(exc).__name__}: {exc}")
        except BaseException as exc:  # SIGTERM/timeout (SystemExit), Ctrl+C: receipt first, then stop
            receipt["state"] = "FAILED"
            receipt["problems"].append(f"interrupted: {type(exc).__name__}")
            _finish(status_dir, receipt)
            raise
    return _finish(status_dir, receipt)


def _alert_key(receipt: dict[str, Any]) -> Any:
    if receipt.get("state") == "INVALID_CAPTURE":
        return (receipt.get("latest_day") or {}).get("target_date")
    conflicts = (receipt.get("settlement") or {}).get("conflicts") or []
    return sorted((c.get("account_id"), c.get("position_id"), json.dumps(c.get("variants"), sort_keys=True))
                  for c in conflicts)


def _finish(status_dir: Path | None, receipt: dict[str, Any]) -> tuple[dict[str, Any], int]:
    receipt["exit_code"] = EXIT[receipt["state"]]
    if receipt["state"] in ("INVALID_CAPTURE", "SETTLEMENT_CONFLICT"):
        # Alert once per condition: later runs re-derive the same invalid day or the same set
        # of conflicts. A new invalid day or a changed conflict set alerts again.
        previous = _previous_receipt(status_dir) or {}
        if previous.get("state") == receipt["state"] and _alert_key(previous) == _alert_key(receipt):
            receipt["exit_code"] = 0
            receipt["repeat_of_previous_alert"] = True
    try:
        _write_receipt(status_dir, receipt)
    except OSError as exc:  # the receipt itself failing is a failure
        receipt["problems"].append(f"receipt not written: {exc}")
        receipt["state"], receipt["exit_code"] = "FAILED", 1
    return receipt, receipt["exit_code"]


def _run_locked(db: Path, ledger_path: Path, now: datetime, receipt: dict[str, Any], *, refresh_settlements: bool,
                max_events: int, deadline_s: float, model) -> None:
    store = SnapshotStore.open_readonly(db)
    ledger = ShadowLedger(ledger_path)
    days = closed_capture_days(store, now)
    last_closed = forward.last_closed_target(now)
    done = processed_days(ledger, shadow.RESEARCH_ACCOUNT_ID) & processed_days(ledger, shadow.ACCOUNT_ID)
    broken = incomplete_days(ledger, shadow.RESEARCH_ACCOUNT_ID) | incomplete_days(ledger, shadow.ACCOUNT_ID)
    # New days, days left incomplete by a crash, and the most recent days again (idempotent),
    # so a restart between a decision and its fill is always completed.
    todo = [d for d in days if d not in done or d in broken or d in set(days[-RECHECK_RECENT_DAYS:])]
    receipt["missing_capture_days"] = [d.isoformat() for d in missing_capture_days(days, last_closed)]
    failed = False
    for day in todo:
        decision = forward.windows(day)["decision"]
        entry: dict[str, Any] = {"target_date": day.isoformat(), "decision_time_utc": _iso(decision),
                                 "accounts": {}, "problems": []}
        try:
            # Positions settled with evidence received before this day's decision count as
            # cash for it; anything received later waits (catch-up never borrows from the future).
            shadow.settle_open_positions(store, ledger, known_by=decision, now=now)
            result = shadow.run_day(store, ledger, day, model=model, now=now)
        except LedgerError as exc:  # includes LedgerConflict: recorded, not a crash
            failed = True
            entry.update(capture_status="UNKNOWN", result="FAILED")
            entry["problems"].append(f"{type(exc).__name__}: {exc}")
            receipt["days"].append(entry)
            # Later days must not run ahead of a failed one: that would record cash movements
            # before it and force it out of knowledge-time order when it is retried.
            receipt["problems"].append(f"stopped at {day.isoformat()}; later days wait for it")
            break
        entry["capture_status"] = result["stage_b_day_status"]
        entry["problems"] = list(result["problems"])
        entry["accounts"] = {acct: {"decisions": s["decisions"], "qualified": s["qualified"], "fills": s["filled"],
                                    "no_fills": s["no_fill"], "risk_vetoes": len(s.get("vetoes", []))}
                             for acct, s in result["accounts"].items()}
        filled = sum(s["filled"] for s in result["accounts"].values())
        entry["result"] = ("INVALID_CAPTURE" if result["stage_b_day_status"] != "VALID"
                           else "HEALTHY_TRADED" if filled else "HEALTHY_NO_SIGNAL")
        receipt["days"].append(entry)

    if refresh_settlements:
        try:
            receipt["settlement"]["refresh"] = _refresh(db, ledger, now, max_events=max_events, deadline_s=deadline_s)
        except Exception as exc:  # noqa: BLE001 - a failed refresh must not lose the bookkeeping
            receipt["settlement"]["refresh"] = {"status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}
        store = SnapshotStore.open_readonly(db)  # fresh read-only view including the new evidence
    cutoff = settlement_cutoff(store, ledger, now, model=model)
    if cutoff < now:
        receipt["problems"].append(f"settlement held at evidence received by {_iso(cutoff)} until the earliest "
                                   "unfinished capture day is processed")
    receipt["settlement"]["evidence_cutoff_utc"] = _iso(cutoff)
    report = shadow.settle_open_positions(store, ledger, known_by=cutoff)
    receipt["settlement"]["settled"] = len(report["settled"])
    receipt["settlement"]["pending"] = report["pending"]
    receipt["settlement"]["conflicts"] = report["conflicts"]
    if report["conflicts"]:
        receipt["problems"].append(f"{len(report['conflicts'])} settlement evidence conflict(s); see settlement.conflicts")
    receipt["accounts"] = _summaries(ledger, now)
    receipt["valid_days"] = sum(1 for d in days if forward.day_status(store, d)["status"] == "VALID")
    receipt["closed_capture_days"] = len(days)

    refresh_status = receipt["settlement"]["refresh"].get("status")
    latest = receipt["days"][-1] if receipt["days"] else None
    if days and last_closed not in days:
        # The last closed decision window left no capture at all: that day is lost (a missed
        # window can never be fetched retrospectively), which is an invalid Stage B day.
        latest = {"target_date": last_closed.isoformat(), "result": "INVALID_CAPTURE",
                  "capture_status": "MISSING_CAPTURE"}
        receipt["problems"].append(f"no capture stored for {last_closed.isoformat()} (missed decision window)")
    receipt["latest_day"] = None if latest is None else {k: latest.get(k) for k in
                                                           ("target_date", "result", "capture_status")}
    if failed or refresh_status == "failed":
        receipt["state"] = "FAILED"
    elif days and latest is not None and latest["result"] == "INVALID_CAPTURE":
        receipt["state"] = "INVALID_CAPTURE"  # conflicts, if any, are still listed in settlement.conflicts
    elif report["conflicts"]:
        receipt["state"] = "SETTLEMENT_CONFLICT"
    elif not days:
        receipt["state"] = "NO_CAPTURE" if not store.forward_captures() else "NOT_CLOSED"
    elif report["pending"]:
        receipt["state"] = "PENDING_SETTLEMENT"
    elif latest is not None and latest["result"] == "HEALTHY_TRADED":
        receipt["state"] = "HEALTHY_TRADED"
    else:
        receipt["state"] = "HEALTHY_NO_SIGNAL"
