"""The future execution-ticket contract (issue #32 §4). This is data only: execution is disabled.

A ticket is what a future approval screen would show before any order: the exact venue,
route, market and side; the model estimate; a fresh quote and its expiry; the all-in
maximum cost; the fee claim basis; the starter-policy verdict; and the risk constraints.

Nothing here can submit anything. `ExecutionTicket.execution_enabled` is always False,
and constructing one with True raises. The API action modes are refused while the venue's
`order_write` capability is not authorized, which is every venue
(`edge_lab.venues`). Approval and submission are later, separately authorized work.

`pre_submit_checks` is the re-validation a future boundary would run just before sending.
It is an ordered control chain (the idea is from flumine's trading controls, reimplemented
here; no code copied): every failing control is listed in evaluation order and the first
one is the primary reason. Its last control, EXECUTION_NOT_AUTHORIZED, always fails, so no
ticket can ever come out of it clean. There is no force or bypass argument. `ticket_id` is
content-derived and is the idempotency key a future client order id must be derived from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .freshness import parse_utc
from .fee_schedules import valid_price
from .opportunity import ExecutableQuote, Market, MarketStatus, Opportunity, PriceGrid
from .risk import RiskPolicy, RiskReport
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


# Allowed ticket transitions. Terminal states map to nothing. No ticket state means "may be sent".
TICKET_TRANSITIONS: Mapping[TicketStatus, frozenset[TicketStatus]] = MappingProxyType({
    TicketStatus.DRAFT: frozenset({TicketStatus.EXPIRED, TicketStatus.REJECTED}),
    TicketStatus.EXPIRED: frozenset(),
    TicketStatus.REJECTED: frozenset(),
})


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
    event_id: str | None = None  # exposure grouping keys; None is unknown and fails closed
    outcome_cluster: str | None = None
    quote_evidence_id: str | None = None  # the book snapshot the ticket was priced from

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
        risk_constraints=dict(risk_constraints or {}), action_mode=action_mode, event_id=opportunity.event_id,
        outcome_cluster=opportunity.outcome_cluster, quote_evidence_id=opportunity.quote_evidence_id,
    )


# ---------------------------------------------------------------- pre-submit control chain


class Control(str, Enum):
    """Pre-submit controls. Declaration order is evaluation order."""

    TICKET_NOT_DRAFT = "TICKET_NOT_DRAFT"
    TICKET_EXPIRED = "TICKET_EXPIRED"
    QTY_INVALID = "QTY_INVALID"
    PRICE_INVALID = "PRICE_INVALID"
    PRICE_OFF_GRID = "PRICE_OFF_GRID"
    MAX_LOSS_UNDERSTATED = "MAX_LOSS_UNDERSTATED"  # below quantity * limit, the cost before fees
    MARKET_UNKNOWN = "MARKET_UNKNOWN"
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    BOOK_MISSING = "BOOK_MISSING"
    BOOK_STALE = "BOOK_STALE"  # rejected, never merely warned
    QUOTE_CHANGED = "QUOTE_CHANGED"  # price moved, or less size than the ticket, since pricing
    ORDER_STATE_UNHEALTHY = "ORDER_STATE_UNHEALTHY"  # no current view of our own orders: no new risk
    ORDER_TIME_UNKNOWN = "ORDER_TIME_UNKNOWN"  # an order without a creation time: counts cannot be trusted
    DUPLICATE_TICKET = "DUPLICATE_TICKET"
    DUPLICATE_OPEN_ORDER = "DUPLICATE_OPEN_ORDER"  # an order on this market and side is still open
    RISK_REPORT_MISSING = "RISK_REPORT_MISSING"  # account-level limits cannot be judged without one
    RISK_REPORT_BLOCKS = "RISK_REPORT_BLOCKS"  # the `risk.assess` report is not current or forbids this risk
    EXPOSURE_UNKNOWN = "EXPOSURE_UNKNOWN"
    EXPOSURE_PER_POSITION = "EXPOSURE_PER_POSITION"  # one market and side, this ticket included
    EXPOSURE_PER_EVENT = "EXPOSURE_PER_EVENT"
    EXPOSURE_PER_CLUSTER = "EXPOSURE_PER_CLUSTER"
    EXPOSURE_GLOBAL = "EXPOSURE_GLOBAL"
    TRADE_COUNT_LIMIT = "TRADE_COUNT_LIMIT"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    EXECUTION_NOT_AUTHORIZED = "EXECUTION_NOT_AUTHORIZED"  # always fails while execution is disabled


class OrderState(str, Enum):
    PENDING = "PENDING"  # intent recorded, no venue answer yet
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"  # an answer was lost: reconcile before any retry
    RESTING = "RESTING"  # on the book, possibly partly filled
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"  # may have partly filled first
    REJECTED = "REJECTED"  # never accepted


OPEN_ORDER_STATES = frozenset({OrderState.PENDING, OrderState.OUTCOME_UNKNOWN, OrderState.RESTING})
ORDER_TRANSITIONS: Mapping[OrderState, frozenset[OrderState]] = MappingProxyType({
    OrderState.PENDING: frozenset({OrderState.OUTCOME_UNKNOWN, OrderState.RESTING, OrderState.FILLED,
                                   OrderState.CANCELLED, OrderState.REJECTED}),  # CANCELLED: unfilled IOC
    OrderState.OUTCOME_UNKNOWN: frozenset({OrderState.RESTING, OrderState.FILLED, OrderState.CANCELLED,
                                           OrderState.REJECTED}),
    OrderState.RESTING: frozenset({OrderState.FILLED, OrderState.CANCELLED,
                                   OrderState.OUTCOME_UNKNOWN}),  # a cancel whose answer was lost
    OrderState.FILLED: frozenset(), OrderState.CANCELLED: frozenset(), OrderState.REJECTED: frozenset(),
})


def transition(current: TicketStatus | OrderState, new: TicketStatus | OrderState) -> TicketStatus | OrderState:
    """Return `new` if its table allows the move; an illegal or post-terminal move raises."""
    table = TICKET_TRANSITIONS if isinstance(current, TicketStatus) else ORDER_TRANSITIONS
    if type(new) is not type(current) or new not in table[current]:
        raise ValueError(f"illegal transition {current.value} -> {new.value}")
    return new


@dataclass(frozen=True)
class OrderRecord:
    """One of our own orders, as a future order-state feed would report it (none exists yet).

    `worst_case_loss` covers the order's pending, resting and filled parts together; for a
    CANCELLED order it covers only the filled part. None, or anything that is not a finite,
    non-negative Decimal, is unknown and fails closed. Settled positions are not passed in."""

    ticket_id: str
    market_id: str
    event_id: str | None
    outcome_cluster: str | None
    side: str
    state: OrderState
    worst_case_loss: Decimal | None
    created_at_utc: str | None


@dataclass(frozen=True)
class TicketLimits:
    """Ticket-specific limits. Money limits are `risk.RiskPolicy`'s, never copied here."""

    max_book_age: timedelta  # a quote exactly this old is still current
    max_order_state_age: timedelta
    max_orders_per_window: int  # every order created in the window counts, failed ones too
    order_window: timedelta  # an order exactly this old has left the window
    market_cooldown: timedelta  # minimum gap between orders on one market; exactly this gap is allowed
    max_risk_report_age: timedelta | None = None  # None: the same as max_order_state_age


@dataclass(frozen=True)
class Violation:
    control: Control
    detail: str


def _finite(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _known_loss(value: object) -> bool:
    return _finite(value) and value >= 0


def pre_submit_checks(ticket: ExecutionTicket, *, now: datetime, market: Market | None,
                      quote: ExecutableQuote | None, order_state_as_of_utc: str | None,
                      orders: tuple[OrderRecord, ...], limits: TicketLimits, risk_policy: RiskPolicy,
                      account_id: str, risk_report: RiskReport | None,
                      price_grid: PriceGrid | None = None) -> tuple[Violation, ...]:
    """Every failing control, in `Control` order; the first is the primary reason. Never empty.
    Malformed inputs fail a named control; nothing here raises except for a naive `now`.

    `price_grid` defaults to the ticket's market's own published grid. `risk_report` is the
    `risk.assess` report for `account_id`, used as computed (breaches, capacity), never
    recomputed; None fails closed. Its capacity must also cover our own open orders, which
    the ledger-based report cannot see.

    Future timestamps (quote, order state, risk report, orders) are rejected outright. That
    is stricter than `freshness.assess`, which tolerates 5 minutes of clock skew: a check just
    before sending has no reason to trust a clock that runs ahead."""
    at = parse_utc(now)
    if at is None:
        raise ValueError("now must be timezone-aware")
    out: list[Violation] = []

    def fail(control: Control, detail: str) -> None:
        out.append(Violation(control, detail))

    def age_bad(stamp: str | None, max_age: timedelta) -> bool:
        seen = parse_utc(stamp)
        return seen is None or seen > at or at - seen > max_age

    if ticket.status is not TicketStatus.DRAFT:
        fail(Control.TICKET_NOT_DRAFT, f"{ticket.status.value}: {'; '.join(ticket.reasons)}")
    expires = parse_utc(ticket.expires_at_utc)
    if expires is None or at >= expires:
        fail(Control.TICKET_EXPIRED, f"expires {ticket.expires_at_utc}")
    q, price, max_loss = ticket.quantity, ticket.limit_price, ticket.max_loss
    q_ok = type(q) is int and q > 0
    if not q_ok:
        fail(Control.QTY_INVALID, f"quantity {q!r} is not a positive whole number of contracts")
    price_ok = valid_price(price)  # Decimal, finite, inside (0, 1), on the 1/100-cent grid
    same_market = market is not None and market.market_id == ticket.market_id
    grid = price_grid if price_grid is not None else (market.price_grid if same_market else None)
    if not price_ok:
        fail(Control.PRICE_INVALID, f"limit {price!r}")
    elif grid is not None and not grid.contains(price):
        fail(Control.PRICE_OFF_GRID, f"limit {price} is not on the grid from {grid.source}")
    if q_ok and price_ok and _known_loss(max_loss) and max_loss < q * price:
        fail(Control.MAX_LOSS_UNDERSTATED, f"max_loss {max_loss} < {q} x {price}")
    if not same_market:
        fail(Control.MARKET_UNKNOWN, ticket.market_id)
    elif market.status is not MarketStatus.OPEN:
        fail(Control.MARKET_NOT_OPEN, market.status.value)
    if (quote is None or quote.market_id != ticket.market_id or quote.side != ticket.side
            or not _finite(quote.best_ask) or quote.anomaly):
        fail(Control.BOOK_MISSING, "no usable book for this market and side")
    else:
        received, created = parse_utc(quote.received_at_utc), parse_utc(ticket.created_at_utc)
        priced = parse_utc(ticket.quote_received_at_utc)
        new_evidence = (quote.evidence_id is not None and ticket.quote_evidence_id is not None
                        and quote.evidence_id != ticket.quote_evidence_id)
        if age_bad(quote.received_at_utc, limits.max_book_age):
            fail(Control.BOOK_STALE, f"received {quote.received_at_utc}")
        elif created is None or received < created:
            fail(Control.BOOK_STALE, f"the quote ({quote.received_at_utc}) predates the ticket "
                                     f"({ticket.created_at_utc}): a re-check needs a new book")
        elif not ((priced is not None and received > priced) or new_evidence):
            fail(Control.BOOK_STALE, f"re-check is the pricing quote ({quote.evidence_id} at {quote.received_at_utc})")
        size = quote.displayed_size
        if not price_ok or quote.best_ask != price or not _finite(size) or (q_ok and size < q):
            fail(Control.QUOTE_CHANGED, f"ask {quote.best_ask} x {size}; ticket {price} x {q}")
    if age_bad(order_state_as_of_utc, limits.max_order_state_age):
        fail(Control.ORDER_STATE_UNHEALTHY, f"order state as of {order_state_as_of_utc}")
    timed = [(parse_utc(o.created_at_utc), o) for o in orders]
    if any(c is None for c, _ in timed):
        fail(Control.ORDER_TIME_UNKNOWN, "an order has no creation time")
    timed = [(c, o) for c, o in timed if c is not None]
    if any(o.ticket_id == ticket.ticket_id for o in orders):
        fail(Control.DUPLICATE_TICKET, ticket.ticket_id)
    typed = [o for o in orders if isinstance(o.state, OrderState)]
    open_orders = [o for o in typed if o.state in OPEN_ORDER_STATES]
    if any(o.market_id == ticket.market_id and o.side == ticket.side
           for o in open_orders):
        fail(Control.DUPLICATE_OPEN_ORDER, f"{ticket.market_id} {ticket.side}")

    report = risk_report
    if report is None:
        fail(Control.RISK_REPORT_MISSING, "reserve, loss-limit and drawdown controls cannot be judged")
    else:
        report_at, state_at = parse_utc(report.as_of_utc), parse_utc(order_state_as_of_utc)
        capacity = report.remaining_risk_capacity
        report_age = limits.max_order_state_age if limits.max_risk_report_age is None else limits.max_risk_report_age
        breaches = report.breaches if isinstance(report.breaches, (tuple, list)) else ()
        open_losses = [o.worst_case_loss for o in open_orders]
        if report.account_id != account_id or report.policy_id != risk_policy.policy_id:
            fail(Control.RISK_REPORT_BLOCKS, f"report is for {report.account_id}/{report.policy_id}, "
                                             f"not {account_id}/{risk_policy.policy_id}")
        elif age_bad(report.as_of_utc, report_age):
            fail(Control.RISK_REPORT_BLOCKS, f"report as of {report.as_of_utc} is not current")
        elif state_at is None or report_at < state_at:
            fail(Control.RISK_REPORT_BLOCKS, f"report older than order state ({order_state_as_of_utc})")
        elif report.new_risk_allowed is not True:
            fail(Control.RISK_REPORT_BLOCKS, str((tuple(breaches) or ("NO_REMAINING_RISK_CAPACITY",))[0]))
        elif not _finite(capacity):
            fail(Control.RISK_REPORT_BLOCKS, f"remaining risk capacity {capacity!r} is unknown")
        elif _known_loss(max_loss) and all(_known_loss(v) for v in open_losses):
            need = max_loss + sum(open_losses, Decimal(0))  # the report sees fills, not our open orders
            if need > capacity:
                fail(Control.RISK_REPORT_BLOCKS, f"REMAINING_RISK_CAPACITY: {need} with open orders > {capacity}")

    counted = [o for o in orders if o.state is not OrderState.REJECTED]
    if (len(typed) != len(orders) or not _known_loss(max_loss) or not ticket.event_id or not ticket.outcome_cluster
            or any(not _known_loss(o.worst_case_loss) or not o.event_id or not o.outcome_cluster for o in counted)):
        fail(Control.EXPOSURE_UNKNOWN, "an order state, worst-case loss, event or cluster is missing or invalid")
    else:
        def total(keep) -> Decimal:
            return max_loss + sum((o.worst_case_loss for o in counted if keep(o)), Decimal(0))

        for control, limit, amount in (
                (Control.EXPOSURE_PER_POSITION, risk_policy.max_position_risk,
                 total(lambda o: o.market_id == ticket.market_id and o.side == ticket.side)),
                (Control.EXPOSURE_PER_EVENT, risk_policy.max_event_risk,
                 total(lambda o: o.event_id == ticket.event_id)),
                (Control.EXPOSURE_PER_CLUSTER, risk_policy.max_cluster_risk,
                 total(lambda o: o.outcome_cluster == ticket.outcome_cluster)),
                (Control.EXPOSURE_GLOBAL, risk_policy.max_portfolio_risk, total(lambda o: True))):
            if amount > limit:  # exactly at a limit is allowed, as in `exp001_shadow.risk_veto`
                fail(control, f"{amount} > {limit}")

    recent = sum(1 for c, _ in timed if c > at - limits.order_window)  # future-dated ones count
    if recent >= limits.max_orders_per_window:
        fail(Control.TRADE_COUNT_LIMIT, f"{recent} orders in {limits.order_window}")
    if any(o.market_id == ticket.market_id and at - c < limits.market_cooldown for c, o in timed):
        fail(Control.COOLDOWN_ACTIVE, f"{ticket.market_id} within {limits.market_cooldown}")
    fail(Control.EXECUTION_NOT_AUTHORIZED, "execution is disabled for every venue (docs/EXECUTION_PLAN.md)")
    return tuple(out)
