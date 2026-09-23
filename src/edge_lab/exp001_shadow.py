"""EXP-001 Stage B shadow trading on the append-only ledger (Gate 6). Simulation only.

For each target date D:

- `run_day` records a decision for every opportunity the Gate 5 engine produced, whether
  it qualified or was rejected. It sizes each qualified one with the frozen 1-contract
  rule, under hard caps. It then simulates the fill with `latency-confirmed-v1`, the
  frozen execution model: entry at the decision ask, confirmed by the 10–15 min
  re-check book.
- `settle_open_positions` settles open positions on the official outcome read from captured Kalshi
  settlement evidence. A position with no evidence, or with conflicting evidence, stays
  open; it is never guessed.

Rules:

- Only a VALID Stage B day can fill. On an INVALID day every qualified decision is
  recorded with `NO_FILL / STAGE_B_DAY_INVALID`, so the day is excluded and counted,
  never partially traded.
- The fee schedule is UNVERIFIED_CURRENT_SCHEDULE, so every decision carries
  `claimable = false`. No net-profitability claim may rest on this account until the
  schedule is verified.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import exp001_stageb as stageb
from . import forward, settlement
from .fill_policy import FILLED, LATENCY_CONFIRMED_V1, simulate_fill
from .freshness import parse_utc
from .kalshi import SETTLEMENT_SOURCE
from .kalshi_quotes import quotes_from_orderbook
from .opportunity import ExecutableQuote, Opportunity
from .shadow_ledger import LedgerError, ShadowLedger
from .sizing import SizingPolicy, suggest_position_size
from .storage import SnapshotStore

ACCOUNT_ID = "EXP-001-stage-b-shadow"
STRATEGY = "EXP-001 Stage B (frozen signal, 1 contract)"
STARTING_BANKROLL = Decimal("1000.00")  # notional shadow bankroll; no real money exists
OPENED_AT = "2026-09-22T00:00:00+00:00"

# The frozen rule is 1 contract per signal. The caps are hard limits that a 1-contract
# signal never reaches; they exist so the sizing path is identical to later strategies.
SIZING_POLICY = SizingPolicy(
    policy_id="EXP-001-fixed-1-v1", fixed_contracts=1, kelly_fraction=None,
    max_position_contracts=1, max_position_risk=Decimal("1.00"), max_event_risk=Decimal("6.00"),
    max_cluster_risk=Decimal("6.00"), max_portfolio_risk=Decimal("50.00"), reserve=Decimal("100.00"),
)


def ensure_account(ledger: ShadowLedger) -> None:
    ledger.open_account(ACCOUNT_ID, starting_bankroll=STARTING_BANKROLL, strategy=STRATEGY, opened_at_utc=OPENED_AT,
                        sizing_policy_id=SIZING_POLICY.policy_id, fill_policy_id=LATENCY_CONFIRMED_V1.policy_id,
                        fee_schedule_id=stageb.FEE_SCHEDULE.schedule_id)


def decision_id(opportunity: Opportunity) -> str:
    return f"dec-{opportunity.opportunity_id}"


def _recheck_quotes(store: SnapshotStore, day: dict[str, Any], mode: str) -> dict[tuple[str, str], ExecutableQuote]:
    recheck_id = day.get("recheck_capture_id")
    if recheck_id is None:
        return {}
    row = next(r for r in store.forward_captures(target_date=day["target_date"], phase="recheck", mode=mode)
               if int(r["id"]) == recheck_id)
    books = json.loads(row["links_json"]).get("books") or {}
    snaps = store.snapshots_by_id(b["snapshot_id"] for b in books.values())
    out: dict[tuple[str, str], ExecutableQuote] = {}
    for native, info in books.items():
        snap = snaps.get(info["snapshot_id"])
        if snap is None or snap["entity_id"] != native or snap["run_id"] != row["run_id"]:
            continue
        for side, q in quotes_from_orderbook(native, json.loads(snap["payload_json"]),
                                              received_at_utc=snap["fetched_at_utc"],
                                              evidence_id=f"snapshot:{snap['id']}").items():
            out[(q.market_id, side)] = q
    return out


def run_day(store: SnapshotStore, ledger: ShadowLedger, target: date, *, model=None, mode: str = "live") -> dict[str, Any]:
    """Record decisions and simulated fills for D. Safe to re-run: every append is idempotent."""
    ensure_account(ledger)
    evaluation = stageb.evaluate_day(store, target, model=model, mode=mode)
    day = evaluation.day_status
    valid = day["status"] == "VALID"
    confirmations = _recheck_quotes(store, day, mode) if valid else {}
    entry_quotes = _decision_quotes(store, evaluation, mode)
    expected_settlement = (forward.windows(target)["decision"] + timedelta(days=2)).isoformat()
    summary = {"target_date": target.isoformat(), "stage_b_day_status": day["status"], "decisions": 0,
               "qualified": 0, "filled": 0, "no_fill": {}, "problems": evaluation.problems}

    for opp in evaluation.opportunities:
        did = decision_id(opp)
        existing = ledger.find(ACCOUNT_ID, "decision", did)
        if existing is None:
            # Sized against the ledger as it stands before this decision; a re-run finds the
            # decision already recorded and reuses its size, so replays stay deterministic.
            state = ledger.state(ACCOUNT_ID)
            sizing = None
            if opp.qualification == "QUALIFY":
                sizing = suggest_position_size(
                    bankroll=state.equity, conservative_probability=opp.conservative_probability,
                    executable_price=opp.executable_price, fees=stageb.FEE_SCHEDULE,
                    available_size=opp.displayed_size, event_exposure=state.event_exposure(opp.event_id),
                    cluster_exposure=state.cluster_exposure(opp.outcome_cluster),
                    total_open_risk=state.open_worst_case_risk, policy=SIZING_POLICY,
                )
            existing = {
                "decision_id": did, "opportunity_id": opp.opportunity_id, "as_of_utc": opp.as_of_utc,
                "qualification": opp.qualification, "reason": opp.rejection_reason, "reasons": list(opp.reasons),
                "model_version": opp.model_version,
                "quote_evidence_ids": [opp.quote_evidence_id] if opp.quote_evidence_id else [],
                "event_id": opp.event_id, "market_id": opp.market_id, "side": opp.side,
                "outcome_cluster": opp.outcome_cluster, "policy_id": opp.policy_id,
                "opportunity": opp.to_dict(), "sizing": None if sizing is None else sizing.to_dict(),
                "stage_b_day_status": day["status"], "claimable": opp.claimable,
            }
            ledger.record_decision(ACCOUNT_ID, existing)
        summary["decisions"] += 1
        if opp.qualification != "QUALIFY":
            continue
        summary["qualified"] += 1
        fill = ledger.find(ACCOUNT_ID, "fill", did)
        if fill is None:
            quantity = int((existing.get("sizing") or {}).get("final_size") or 0)
            fill = _fill_payload(opp, quantity, valid, entry_quotes, confirmations, expected_settlement)
            if fill["status"] == FILLED and Decimal(fill["total_cost"]) > ledger.state(ACCOUNT_ID).settled_cash:
                fill.update(status="NO_FILL", reason="INSUFFICIENT_CASH", quantity=0, price=None, total_cost=None,
                            fee=None, detail="settled cash below the fill's cost")
            ledger.record_fill(ACCOUNT_ID, fill)
        if fill["status"] == FILLED:
            summary["filled"] += 1
        else:
            summary["no_fill"][fill["reason"]] = summary["no_fill"].get(fill["reason"], 0) + 1
    return summary


def _decision_quotes(store: SnapshotStore, evaluation, mode: str) -> dict[tuple[str, str], ExecutableQuote]:
    """The quotes the engine priced, rebuilt from the same snapshots (by evidence id)."""
    ids = {o.quote_evidence_id for o in evaluation.opportunities if o.quote_evidence_id}
    snaps = store.snapshots_by_id(int(i.split(":", 1)[1]) for i in ids)
    out: dict[tuple[str, str], ExecutableQuote] = {}
    for snap in snaps.values():
        for side, q in quotes_from_orderbook(snap["entity_id"], json.loads(snap["payload_json"]),
                                              received_at_utc=snap["fetched_at_utc"],
                                              evidence_id=f"snapshot:{snap['id']}").items():
            out[(q.market_id, side)] = q
    return out


def _fill_payload(opp: Opportunity, quantity: int, valid: bool, entries, confirmations, expected_settlement: str) -> dict[str, Any]:
    base = {
        "fill_id": f"fill-{opp.opportunity_id}", "decision_id": decision_id(opp), "venue": "kalshi",
        "market_id": opp.market_id, "event_id": opp.event_id, "outcome_cluster": opp.outcome_cluster,
        "side": opp.side, "filled_at_utc": opp.as_of_utc, "fill_policy_id": LATENCY_CONFIRMED_V1.policy_id,
        "latency": {"confirm_min_s": LATENCY_CONFIRMED_V1.confirm_min.total_seconds(),
                    "confirm_max_s": LATENCY_CONFIRMED_V1.confirm_max.total_seconds()},
        "expected_settlement_utc": expected_settlement, "fee_schedule_id": stageb.FEE_SCHEDULE.schedule_id,
    }
    if not valid:
        return {**base, "status": "NO_FILL", "reason": "STAGE_B_DAY_INVALID", "quantity": 0, "price": None,
                "fee": None, "total_cost": None, "entry_evidence_id": opp.quote_evidence_id,
                "confirmation_evidence_id": None, "detail": "the Stage B day is INVALID: excluded, never traded"}
    result = simulate_fill(quantity=quantity, entry=entries.get((opp.market_id, opp.side)),
                           confirmation=confirmations.get((opp.market_id, opp.side)),
                           as_of=parse_utc(opp.as_of_utc))
    if result.status != FILLED:
        return {**base, "status": "NO_FILL", "reason": result.reason, "quantity": 0, "price": None, "fee": None,
                "total_cost": None, "entry_evidence_id": result.entry_evidence_id,
                "confirmation_evidence_id": result.confirmation_evidence_id, "detail": result.detail}
    cost = stageb.FEE_SCHEDULE.taker_buy(result.quantity, result.price)
    return {**base, "status": "FILLED", "reason": "FILLED", "quantity": result.quantity, "price": str(result.price),
            "fee": str(cost.fee), "total_cost": str(cost.total_cost), "entry_evidence_id": result.entry_evidence_id,
            "confirmation_evidence_id": result.confirmation_evidence_id, "detail": result.detail}


# --------------------------------------------------------------------------- settlement


def settled_market(store: SnapshotStore, native_id: str) -> tuple[dict[str, Any] | None, int | None]:
    """The most recently captured settled-market record for `native_id`, with its snapshot id."""
    found, found_id = None, None
    for kind in ("settled_markets", "historical_markets"):
        for row in store.snapshots_of_kind(source=SETTLEMENT_SOURCE.legacy_name, kind=kind):
            for market in json.loads(row["payload_json"]).get("markets") or []:
                if isinstance(market, dict) and market.get("ticker") == native_id:
                    if found_id is None or int(row["id"]) > found_id:
                        found, found_id = market, int(row["id"])
    return found, found_id


def official_outcome(market: dict[str, Any]) -> tuple[str | None, str]:
    """YES/NO when Kalshi's recorded result and the frozen resolver agree on expiration_value."""
    value = settlement.parse_value(market.get("expiration_value"))
    resolved = settlement.resolve(market, value)
    recorded = settlement.kalshi_result(market)
    if resolved.outcome is settlement.Outcome.UNKNOWN:
        return None, f"resolver: {resolved.reason}"
    if recorded is settlement.Outcome.UNKNOWN:
        return None, f"Kalshi result {market.get('result')!r} is not yes/no"
    if resolved.outcome is not recorded:
        return None, f"resolver says {resolved.outcome.value}, Kalshi recorded {recorded.value}"
    return resolved.outcome.value.upper(), resolved.reason


def settle_open_positions(store: SnapshotStore, ledger: ShadowLedger) -> dict[str, Any]:
    """Settle every open position that has conclusive settlement evidence; report the rest."""
    ensure_account(ledger)
    report = {"settled": [], "pending": []}
    for position in ledger.state(ACCOUNT_ID).open_positions():
        native = position.market_id.split(":", 1)[1]
        market, snapshot_id = settled_market(store, native)
        if market is None:
            report["pending"].append({"position_id": position.position_id, "reason": "no settlement evidence yet"})
            continue
        outcome, why = official_outcome(market)
        if outcome is None:
            report["pending"].append({"position_id": position.position_id, "reason": why})
            continue
        settled_at = market.get("settlement_ts") or market.get("expiration_time") or market.get("close_time")
        try:
            ledger.record_settlement(ACCOUNT_ID, fill_id=position.position_id, outcome=outcome, settled_at_utc=str(settled_at),
                                     evidence={"snapshot_id": snapshot_id, "expiration_value": market.get("expiration_value"),
                                               "kalshi_result": market.get("result"), "resolver": why})
        except LedgerError as exc:
            report["pending"].append({"position_id": position.position_id, "reason": str(exc)})
            continue
        report["settled"].append({"position_id": position.position_id, "outcome": outcome})
    return report
