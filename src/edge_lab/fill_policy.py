"""Deterministic simulated-fill policy (Gate 6). Simulation only: nothing is sent anywhere.

`latency-confirmed-v1` generalizes the frozen EXP-001 execution model:

- entry at the decision quote's executable ask, with quantity no more than its displayed
  size, and a quote no older than `max_entry_age` at the decision time;
- the fill counts only if a confirmation quote, captured `confirm_min`–`confirm_max`
  after the entry quote, still offers no more than the entry price with size ≥ quantity.

It never assumes any of these:

- midpoint fills;
- unlimited liquidity;
- fills at a better price seen later;
- stale fills;
- a fill without a quote.

When the evidence is insufficient, the result is `NO_FILL` with an explicit reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .fee_schedules import valid_price
from .freshness import parse_utc
from .opportunity import ExecutableQuote

FILLED = "FILLED"
NO_FILL = "NO_FILL"


@dataclass(frozen=True)
class FillPolicy:
    policy_id: str
    max_entry_age: timedelta
    confirm_min: timedelta
    confirm_max: timedelta


LATENCY_CONFIRMED_V1 = FillPolicy(
    policy_id="latency-confirmed-v1",
    max_entry_age=timedelta(minutes=5),
    confirm_min=timedelta(minutes=10),
    confirm_max=timedelta(minutes=15),
)


@dataclass(frozen=True)
class FillResult:
    status: str  # FILLED | NO_FILL
    reason: str  # machine-readable
    quantity: int  # filled quantity (0 for NO_FILL)
    price: Decimal | None  # entry price actually paid (never a later, better price)
    entry_evidence_id: str | None
    confirmation_evidence_id: str | None
    detail: str
    policy_id: str


def simulate_fill(
    *,
    quantity: int,
    entry: ExecutableQuote | None,
    confirmation: ExecutableQuote | None,
    as_of: datetime,
    policy: FillPolicy = LATENCY_CONFIRMED_V1,
) -> FillResult:
    """Fill `quantity` contracts at the entry ask, if the evidence supports it."""
    entry_id = None if entry is None else entry.evidence_id
    confirm_id = None if confirmation is None else confirmation.evidence_id

    def no(reason: str, detail: str) -> FillResult:
        return FillResult(NO_FILL, reason, 0, None, entry_id, confirm_id, detail, policy.policy_id)

    decided = parse_utc(as_of)
    if decided is None:
        raise ValueError("as_of must be timezone-aware")
    if quantity <= 0:
        return no("ZERO_SIZE", "sizing produced no contracts")
    if entry is None:
        return no("NO_ENTRY_QUOTE", "no captured quote at the decision")
    entry_at = parse_utc(entry.received_at_utc)
    if entry_at is None or entry_at > decided or decided - entry_at > policy.max_entry_age:
        return no("STALE_ENTRY_QUOTE", f"entry quote received {entry.received_at_utc}, decision {decided.isoformat()}")
    if entry.anomaly or entry.best_ask is None or not valid_price(entry.best_ask):
        return no("NO_ENTRY_PRICE", entry.anomaly or "no valid executable ask at the decision")
    if entry.displayed_size is None or entry.displayed_size < quantity:
        return no("INSUFFICIENT_SIZE", f"displayed {entry.displayed_size} < quantity {quantity}")
    if confirmation is None:
        return no("NO_CONFIRMATION", "no confirmation quote in the latency window (unverified)")
    if (confirmation.market_id, confirmation.side) != (entry.market_id, entry.side):
        return no("CONFIRMATION_MISMATCH", f"confirmation is for {confirmation.market_id}/{confirmation.side}")
    confirmed_at = parse_utc(confirmation.received_at_utc)
    if confirmed_at is None or not (entry_at + policy.confirm_min <= confirmed_at <= entry_at + policy.confirm_max):
        return no("CONFIRMATION_OUTSIDE_WINDOW",
                  f"confirmation received {confirmation.received_at_utc}; window "
                  f"[{(entry_at + policy.confirm_min).isoformat()}, {(entry_at + policy.confirm_max).isoformat()}]")
    if confirmation.anomaly or confirmation.best_ask is None or not valid_price(confirmation.best_ask):
        return no("CONFIRMATION_NO_OFFER", confirmation.anomaly or "nothing offered at confirmation")
    if confirmation.best_ask > entry.best_ask:
        return no("PRICE_MOVED_AWAY", f"confirmation ask {confirmation.best_ask} > entry {entry.best_ask}")
    if confirmation.displayed_size is None or confirmation.displayed_size < quantity:
        return no("CONFIRMATION_INSUFFICIENT_SIZE", f"confirmation displayed {confirmation.displayed_size} < {quantity}")
    return FillResult(FILLED, "FILLED", quantity, entry.best_ask, entry_id, confirm_id,
                      "offer persisted through the latency window", policy.policy_id)
