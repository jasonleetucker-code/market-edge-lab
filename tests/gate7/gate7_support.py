"""Shared helpers for the Gate 7 adversarial suite (tests/gate7). Test-only; no network.

Every store and ledger here lives under pytest's tmp_path. Nothing touches production.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from edge_lab import exp001_shadow as shadow
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.http import FetchResult
from edge_lab.kalshi import SETTLEMENT_SOURCE, _save
from edge_lab.shadow_ledger import LedgerConflict, LedgerError, ShadowLedger

UTC = timezone.utc
# Fixture day D = 2026-09-23: decision 2026-09-22 22:00Z, re-check windows closed by 22:20Z.
DECISION = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)
CLOSED = datetime(2026, 9, 22, 23, 0, tzinfo=UTC)
D_EVENT = "weather:us-nyc-central-park:daily-max-temp-f:2026-09-23"
D_CLUSTER = "weather:us-nyc-central-park:2026-09-23"
OPS = shadow.ACCOUNT_ID
RESEARCH = "EXP-001-stage-b-research"  # planned research account (coordinator fix 2)


def seed(lg: ShadowLedger, account: str, n: str, *, price: str, qty: int = 1, filled_at: datetime,
         event: str, cluster: str, expected_settlement: datetime | None = None, side: str = "YES") -> Decimal:
    """Record one qualified decision and a FILLED fill directly on the ledger. Returns its cost."""
    lg.record_decision(account, {
        "decision_id": f"seed-d-{n}", "opportunity_id": f"seed-o-{n}", "as_of_utc": filled_at.isoformat(),
        "qualification": "QUALIFY", "reason": "QUALIFY", "event_id": event, "market_id": f"kalshi:SEED-{n}",
        "side": side, "outcome_cluster": cluster})
    cost = FEES.taker_buy(qty, Decimal(price))
    lg.record_fill(account, {
        "fill_id": f"seed-f-{n}", "decision_id": f"seed-d-{n}", "venue": "kalshi", "market_id": f"kalshi:SEED-{n}",
        "event_id": event, "outcome_cluster": cluster, "side": side, "filled_at_utc": filled_at.isoformat(),
        "status": "FILLED", "reason": "FILLED", "quantity": qty, "price": price, "fee": str(cost.fee),
        "total_cost": str(cost.total_cost),
        "expected_settlement_utc": None if expected_settlement is None else expected_settlement.isoformat()})
    return cost.total_cost


def settle_seed(lg: ShadowLedger, account: str, n: str, outcome: str, *, settled_at: datetime,
                available_at: datetime | None = None) -> None:
    evidence: dict[str, Any] = {"test": n}
    evidence["evidence_available_utc"] = (available_at or settled_at).isoformat()
    lg.record_settlement(account, fill_id=f"seed-f-{n}", outcome=outcome, evidence=evidence,
                         settled_at_utc=settled_at.isoformat())


def seed_realized_losses(lg: ShadowLedger, prices: list[str], *, settled_at: datetime) -> Decimal:
    """Open and lose one position per price on the operational account (each settles NO)."""
    shadow.ensure_account(lg)
    total = Decimal(0)
    # All fills first, then all settlements: cash movements must be appended in knowledge-time
    # order (the ledger refuses a fill known before an already-recorded settlement).
    for i, price in enumerate(prices):
        total += seed(lg, OPS, f"loss-{i}", price=price, filled_at=settled_at - timedelta(hours=8),
                      event=f"weather:seed-event-{i}", cluster=f"weather:seed-cluster-{i}",
                      expected_settlement=settled_at)
    for i in range(len(prices)):
        settle_seed(lg, OPS, f"loss-{i}", "NO", settled_at=settled_at)
    return total


def fills(lg: ShadowLedger, account: str = OPS) -> list[dict[str, Any]]:
    return [json.loads(r["payload_json"]) for r in lg.entries(account) if r["kind"] == "fill"]


def day_fills(lg: ShadowLedger, account: str = OPS) -> list[dict[str, Any]]:
    """Fill entries for the fixture day D (excludes seeded entries)."""
    return [f for f in fills(lg, account) if not f["fill_id"].startswith("seed-")]


def store_settled_markets(store, markets: list[dict[str, Any]], *, run_id: str, fetched_at: str) -> None:
    payload = {"markets": markets, "cursor": None}
    fetch = FetchResult("u", "u", 200, "application/json", json.dumps(payload).encode(), fetched_at, 1, 1)
    store.start_run(run_id)
    _save(store, run_id=run_id, kind="settled_markets", entity_id="KXHIGHNY", url="u", payload=payload,
          fetch=fetch, spec=SETTLEMENT_SOURCE)
    store.finish_run(run_id, status="succeeded")


def settled_copy(markets: list[dict[str, Any]], value: int) -> list[dict[str, Any]]:
    from edge_lab import settlement
    return [dict(m, status="settled", expiration_value=str(value),
                 result=settlement.resolve(m, value).outcome.value) for m in markets]


# --------------------------------------------------------------------------- multiprocess workers


def concurrent_worker(path: str, account: str, worker: int, count: int, as_of: str, queue) -> None:
    """Append `count` own decisions, one shared identical decision and one contested key."""
    lg = ShadowLedger(path)
    created, errors = 0, []
    for i in range(count):
        try:
            _, new = lg.record_decision(account, {
                "decision_id": f"w{worker}-d{i}", "opportunity_id": f"w{worker}-o{i}", "as_of_utc": as_of,
                "qualification": "REJECT", "reason": "NO_EDGE"})
            created += new
        except Exception as exc:  # pragma: no cover - reported to the parent
            errors.append(f"{type(exc).__name__}: {exc}")
    shared = {"decision_id": "shared", "opportunity_id": "shared", "as_of_utc": as_of,
              "qualification": "REJECT", "reason": "NO_EDGE"}
    try:
        lg.record_decision(account, shared)
    except Exception as exc:  # pragma: no cover
        errors.append(f"shared {type(exc).__name__}: {exc}")
    contested = {"decision_id": "contested", "opportunity_id": f"contested-by-{worker}", "as_of_utc": as_of,
                 "qualification": "REJECT", "reason": "NO_EDGE"}
    try:
        _, won = lg.record_decision(account, contested)
        outcome = "won" if won else "duplicate"
    except LedgerConflict:
        outcome = "conflict"
    except LedgerError as exc:  # pragma: no cover
        outcome = f"error {exc}"
    queue.put({"worker": worker, "created": created, "errors": errors, "contested": outcome})
