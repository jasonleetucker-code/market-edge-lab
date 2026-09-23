"""The future execution-ticket contract (issue #32 §4). This is data only: execution is disabled.

A ticket is what a future approval screen would show before any order: the exact venue,
route, market and side; the model estimate; a fresh quote and its expiry; the all-in
maximum cost; the fee claim basis; the starter-policy verdict; and the risk constraints.

Nothing here can submit anything. `ExecutionTicket.execution_enabled` is always False,
and constructing one with True raises. The API action modes are refused while the venue's
`order_write` capability is not authorized, which is every venue
(`edge_lab.venues`). Approval, re-validation and submission are later, separately
authorized work.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from .freshness import parse_utc
from .opportunity import Opportunity
from .starter_policy import StarterVerdict
from .venues import Capability, VenueSpec

TICKET_SCHEMA = "edge-lab-execution-ticket/1"


class ActionMode(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    SIMULATION = "SIMULATION"
    ALERT_AND_DEEPLINK = "ALERT_AND_DEEPLINK"  # a person acts in the venue's own app
    APP_APPROVAL_API = "APP_APPROVAL_API"  # future: approve in Market Edge, submit by API
    BOUNDED_AUTO_API = "BOUNDED_AUTO_API"  # future: separately approved bounded automation


API_MODES = frozenset({ActionMode.APP_APPROVAL_API, ActionMode.BOUNDED_AUTO_API})


class TicketStatus(str, Enum):
    DRAFT = "DRAFT"  # complete and current; still nothing is submitted
    EXPIRED = "EXPIRED"  # the quote is too old or past the ticket's expiry
    REJECTED = "REJECTED"  # a precondition fails; `reasons` says which


@dataclass(frozen=True)
class ExecutionTicket:
    ticket_id: str
    schema: str
    status: TicketStatus
    reasons: tuple[str, ...]
    created_at_utc: str
    expires_at_utc: str
    venue_id: str
    route_id: str
    market_id: str
    side: str
    quantity: int
    limit_price: Decimal | None
    max_total_cost: Decimal | None  # fees included
    max_loss: Decimal | None
    max_payout: Decimal | None
    fee_schedule_id: str
    fee_claimable: bool
    model_id: str | None
    model_version: str | None
    probability: str | None
    conservative_probability: str | None
    quote_received_at_utc: str | None
    starter_policy: Mapping[str, Any]
    risk_constraints: Mapping[str, str]
    action_mode: ActionMode
    execution_enabled: bool = False

    def __post_init__(self) -> None:
        if self.execution_enabled:
            raise ValueError("execution is disabled: no ticket may be marked executable")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Enum):
                value = value.value
            elif isinstance(value, Decimal):
                value = str(value)
            elif isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, Mapping):
                value = dict(value)
            out[key] = value
        return out


def draft_ticket(opportunity: Opportunity, *, venue: VenueSpec, route_id: str | None, verdict: StarterVerdict,
                 action_mode: ActionMode, now: datetime, ttl: timedelta, max_quote_age: timedelta,
                 risk_constraints: Mapping[str, str] | None = None) -> ExecutionTicket:
    """Draft (never submit) a ticket for one opportunity. Every failed precondition is listed."""
    created = parse_utc(now)
    if created is None:
        raise ValueError("now must be timezone-aware")
    reasons: list[str] = []
    status = TicketStatus.DRAFT
    if opportunity.qualification != "QUALIFY":
        reasons.append(f"NOT_QUALIFIED: {opportunity.rejection_reason}")
    if not opportunity.claimable:
        reasons.append("FEE_CLAIM_BASIS_NONE")
    if not verdict.eligible:
        reasons.append("STARTER_POLICY_INELIGIBLE: " + ",".join(verdict.reasons))
    committed = parse_utc(verdict.commitment_utc)
    if committed is None or abs(created - committed) > max_quote_age:
        reasons.append("STARTER_VERDICT_NOT_CURRENT: the verdict was not assessed at this ticket's time")
    if action_mode in API_MODES:
        reasons.append(f"{action_mode.value}_NOT_AUTHORIZED: {venue.venue_id} order_write is "
                       f"{venue.stage(Capability.ORDER_WRITE).value} and execution_authorized is False")
    if opportunity.market_id.split(":", 1)[0] != venue.venue_id:
        reasons.append(f"VENUE_MISMATCH: {opportunity.market_id} is not on {venue.venue_id}")
    received = parse_utc(opportunity.quote_received_at_utc)
    if received is None or created - received > max_quote_age or received > created:
        status = TicketStatus.EXPIRED
        reasons.append("QUOTE_STALE_OR_MISSING")
    if reasons and status is TicketStatus.DRAFT:
        status = TicketStatus.REJECTED

    q = opportunity.quantity
    cost = None if opportunity.all_in_cost is None else opportunity.all_in_cost * q
    terms = {"venue": venue.venue_id, "route": route_id or venue.route_id, "market": opportunity.market_id,
             "side": opportunity.side, "quantity": q, "limit": str(opportunity.executable_price),
             "max_cost": str(cost), "opportunity": opportunity.opportunity_id, "created": created.isoformat()}
    return ExecutionTicket(
        ticket_id="tkt-" + hashlib.sha256(json.dumps(terms, sort_keys=True).encode()).hexdigest()[:24],
        schema=TICKET_SCHEMA, status=status, reasons=tuple(reasons), created_at_utc=created.isoformat(),
        expires_at_utc=(created + ttl).isoformat(), venue_id=venue.venue_id,
        route_id=route_id or venue.route_id, market_id=opportunity.market_id, side=opportunity.side,
        quantity=q, limit_price=opportunity.executable_price, max_total_cost=cost, max_loss=cost,
        max_payout=None if cost is None else Decimal(q), fee_schedule_id=opportunity.fee_schedule_id,
        fee_claimable=opportunity.claimable, model_id=opportunity.model_id, model_version=opportunity.model_version,
        probability=opportunity.model_probability, conservative_probability=opportunity.conservative_probability,
        quote_received_at_utc=opportunity.quote_received_at_utc, starter_policy=verdict.to_dict(),
        risk_constraints=dict(risk_constraints or {}), action_mode=action_mode,
    )
