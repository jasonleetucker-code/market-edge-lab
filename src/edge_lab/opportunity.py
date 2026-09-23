"""Domain-neutral market-vs-model opportunity engine (Gate 5).

This module answers one question: given a model probability and an executable market
quote, is there a measurable opportunity once uncertainty, fees, freshness, liquidity
and execution constraints are counted?

The contracts here know nothing about weather, Kalshi or EXP-001. Venue adapters build
`Event`, `Market` and `ExecutableQuote` objects from stored evidence; model adapters build
`ModelEstimate` objects. `evaluate` is a pure function of those inputs, a `FeeSchedule`,
a `Policy` and an `as_of` instant.

Rules this module enforces:

- **Executable prices only.** A buy is priced at the side's best ask, meaning the price
  someone is actually offering. A midpoint or last trade price never stands in for a fill;
  the quote contract does not even carry one.
- **Missing is not zero.** An absent quote or model leaves prices, sizes and edges `None`.
- **Stale is not current.** A quote or model input older than the policy allows, or
  timestamped after `as_of` (lookahead), is rejected.
- **Nothing is discarded.** Every (market, side) pair yields an `Opportunity`, whether it
  qualifies or not. Rejections carry machine-readable reasons, and they are research
  evidence too.
- **No execution.** Nothing here authenticates, places or simulates orders against a
  venue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .conservative import ProbabilityBounds
from .fee_schedules import FeeQuote, FeeScheduleStatus, valid_price
from .freshness import Freshness, assess, combine, parse_utc

ENGINE_VERSION = "1"
SIDES = ("YES", "NO")


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class Reason(str, Enum):
    """Machine-readable qualification states. Order here = precedence of the primary reason."""

    QUALIFY = "QUALIFY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    EVENT_MISMATCH = "EVENT_MISMATCH"
    MARKET_CLOSED = "MARKET_CLOSED"
    RULES_UNRESOLVED = "RULES_UNRESOLVED"
    BOOK_MISSING = "BOOK_MISSING"
    BOOK_STALE = "BOOK_STALE"
    MODEL_STALE = "MODEL_STALE"
    INVALID_PRICE = "INVALID_PRICE"
    INSUFFICIENT_SIZE = "INSUFFICIENT_SIZE"
    FEE_UNVERIFIED = "FEE_UNVERIFIED"
    NO_EDGE = "NO_EDGE"


_PRECEDENCE = {reason: i for i, reason in enumerate(Reason)}


# --------------------------------------------------------------------------- contracts


@dataclass(frozen=True)
class Event:
    """One real-world question whose answer settles one or more markets."""

    domain: str  # e.g. "weather"
    event_id: str  # normalized, venue-independent
    target_date: str  # YYYY-MM-DD the outcome refers to
    target_time_utc: str | None  # when the outcome is determined, if known
    outcome_cluster: str  # correlated outcomes share a cluster (exposure grouping)
    settlement_identity: str  # the source and measurement that settle it


@dataclass(frozen=True)
class Payoff:
    """A binary contract pays `amount` per contract if the market's outcome occurs."""

    kind: str  # "binary"
    amount: Decimal
    yes_condition: str  # human-readable YES condition, from the venue's structured fields


@dataclass(frozen=True)
class Market:
    venue: str
    market_id: str  # normalized: "<venue>:<native id>"
    native_id: str
    event_id: str  # normalized event this market settles on (as read from the venue)
    outcome: str  # the YES outcome, short label
    payoff: Payoff
    rules_sha256: str | None
    status: MarketStatus
    rules_resolved: bool  # settlement equivalence established from the captured rules
    rules_detail: str


@dataclass(frozen=True)
class ExecutableQuote:
    """What one side of a market could be bought at, as captured.

    `best_ask` is the executable buy price for `side`; `displayed_size` is the quantity
    offered at exactly that price. There is deliberately no midpoint or last-price field.
    """

    venue: str
    market_id: str
    side: str  # "YES" | "NO"
    best_bid: Decimal | None
    best_ask: Decimal | None
    displayed_size: Decimal | None
    received_at_utc: str | None
    source_timestamp_utc: str | None
    evidence_id: str | None
    anomaly: str | None = None  # malformed or crossed book, detected by the adapter


@dataclass(frozen=True)
class ModelEstimate:
    model_id: str  # experiment/model, e.g. "EXP-001/V1"
    version: str  # code + fit data version
    event_id: str
    market_id: str
    probability: float | None  # P(YES); None when the model cannot say
    bounds: ProbabilityBounds | None
    generated_at_utc: str  # the point in time the estimate is valid for
    input_version: str  # hash/version of the inputs (e.g. forecast product)
    input_observed_at_utc: str | None  # when the newest model input was issued
    unavailable_reason: str | None = None
    unavailable_because_stale: bool = False  # no estimate because the only input was too old


class FeeSchedule(Protocol):
    schedule_id: str
    status: FeeScheduleStatus

    def taker_buy(self, contracts: int, price: Decimal) -> FeeQuote: ...


@dataclass(frozen=True)
class Policy:
    """How opportunities qualify. Versioned by `policy_id`; never tuned in place."""

    policy_id: str
    edge_basis: str  # "point" | "conservative": which probability the net edge uses
    min_net_edge: Decimal  # qualify iff net_edge >= min_net_edge (and net_edge > 0)
    quantity: int  # contracts evaluated per opportunity
    max_book_age: timedelta
    max_model_input_age: timedelta
    fee_verification: str  # "require": unverified fees reject; "flag": allowed, not claimable

    def __post_init__(self) -> None:
        if self.edge_basis not in ("point", "conservative"):
            raise ValueError("edge_basis must be 'point' or 'conservative'")
        if self.fee_verification not in ("require", "flag"):
            raise ValueError("fee_verification must be 'require' or 'flag'")
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        if self.min_net_edge < 0:
            raise ValueError("min_net_edge must not be negative")


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    engine_version: str
    as_of_utc: str
    policy_id: str
    event_id: str
    market_id: str
    outcome: str
    side: str
    outcome_cluster: str
    model_id: str | None
    model_version: str | None
    model_probability: Decimal | None  # probability that this side pays out
    conservative_probability: Decimal | None
    executable_price: Decimal | None
    displayed_size: Decimal | None
    quantity: int
    fee: Decimal | None  # trade fee for `quantity`
    all_in_cost: Decimal | None  # per contract, fee and cent alignment included
    gross_edge: Decimal | None  # model_probability - executable_price
    net_edge: Decimal | None  # basis probability - all_in_cost
    net_edge_point: Decimal | None
    net_edge_conservative: Decimal | None
    book_freshness: str
    model_freshness: str
    freshness: str  # worst of the two
    fee_schedule_id: str
    fee_status: str
    claimable: bool  # a net result may be claimed only on a verified fee schedule
    qualification: str  # "QUALIFY" | "REJECT"
    rejection_reason: str  # primary reason (Reason.QUALIFY when qualified)
    reasons: tuple[str, ...]  # every failed check, precedence order
    details: tuple[str, ...]
    quote_evidence_id: str | None
    quote_received_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {k: _plain(v) for k, v in asdict(self).items()}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, Enum):
        return value.value
    return value


def _dec(value: float) -> Decimal:
    """Exact decimal value of a float probability (no rounding, fully deterministic)."""
    return Decimal(value)


def _q(value: Decimal | None) -> Decimal | None:
    """Reported precision for probabilities and edges (1e-12); comparisons use exact values."""
    return None if value is None else value.quantize(Decimal("1e-12"))


def opportunity_id(**key: Any) -> str:
    canonical = json.dumps({k: _plain(v) for k, v in key.items()}, sort_keys=True, separators=(",", ":"))
    return "opp-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------- evaluation


def _freshness(observed: str | None, *, max_age: timedelta, as_of: datetime) -> tuple[Freshness, str | None]:
    ts = parse_utc(observed)
    if ts is None:
        return Freshness.UNKNOWN, "timestamp missing or unparseable"
    if ts > as_of:
        return Freshness.UNKNOWN, f"timestamp {observed} is after as_of (lookahead)"
    state = assess(ts, max_age=max_age, now=as_of)
    return state, None if state is Freshness.FRESH else f"age {as_of - ts} exceeds {max_age}"


def evaluate(
    *,
    event: Event,
    market: Market,
    side: str,
    quote: ExecutableQuote | None,
    estimate: ModelEstimate | None,
    fee_schedule: FeeSchedule,
    policy: Policy,
    as_of: datetime,
) -> Opportunity:
    """Evaluate buying `policy.quantity` contracts of `side` in `market` as of `as_of`."""
    if side not in SIDES:
        raise ValueError(f"unknown side {side!r}")
    as_of_utc = parse_utc(as_of)
    if as_of_utc is None:
        raise ValueError("as_of must be timezone-aware")
    reasons: set[Reason] = set()
    details: list[str] = []

    def fail(reason: Reason, detail: str) -> None:
        reasons.add(reason)
        details.append(f"{reason.value}: {detail}")

    # Identity: the market, the quote and the estimate must all be about this event.
    if market.event_id != event.event_id:
        fail(Reason.EVENT_MISMATCH, f"market settles on {market.event_id}, not {event.event_id}")
    if quote is not None and (quote.market_id != market.market_id or quote.side != side):
        fail(Reason.EVENT_MISMATCH, f"quote is for {quote.market_id}/{quote.side}")
    if estimate is not None and (estimate.event_id != event.event_id or estimate.market_id != market.market_id):
        fail(Reason.EVENT_MISMATCH, f"estimate is for {estimate.event_id}/{estimate.market_id}")

    if market.status is not MarketStatus.OPEN:
        fail(Reason.MARKET_CLOSED, f"market status {market.status.value}")
    if not market.rules_resolved:
        fail(Reason.RULES_UNRESOLVED, market.rules_detail)

    # Model.
    model_state = Freshness.UNKNOWN
    p_side = p_cons = None
    if estimate is None or estimate.probability is None or estimate.bounds is None:
        why = (estimate.unavailable_reason if estimate is not None else None) or "no model estimate"
        if estimate is not None and estimate.unavailable_because_stale:
            fail(Reason.MODEL_STALE, why)
        else:
            fail(Reason.MODEL_UNAVAILABLE, why)
    else:
        generated = parse_utc(estimate.generated_at_utc)
        if generated is None or generated > as_of_utc:
            fail(Reason.MODEL_STALE, f"estimate generated at {estimate.generated_at_utc}, as_of {as_of_utc.isoformat()}")
        model_state, why = _freshness(estimate.input_observed_at_utc, max_age=policy.max_model_input_age, as_of=as_of_utc)
        if model_state is not Freshness.FRESH:
            fail(Reason.MODEL_STALE, f"model input: {why}")
        point, conservative = estimate.bounds.for_side(side)
        p_side, p_cons = _dec(point), _dec(conservative)

    # Quote.
    book_state = Freshness.UNKNOWN
    price = size = None
    if quote is None:
        fail(Reason.BOOK_MISSING, "no captured book for this market")
    else:
        book_state, why = _freshness(quote.received_at_utc, max_age=policy.max_book_age, as_of=as_of_utc)
        if book_state is not Freshness.FRESH:
            fail(Reason.BOOK_STALE, f"book: {why}")
        if quote.anomaly:
            fail(Reason.INVALID_PRICE, quote.anomaly)
        elif quote.best_ask is None or not quote.displayed_size:
            fail(Reason.INSUFFICIENT_SIZE, "nothing offered on this side")
        elif not valid_price(quote.best_ask):
            fail(Reason.INVALID_PRICE, f"ask {quote.best_ask} is not a valid contract price")
        elif quote.best_bid is not None and quote.best_bid >= quote.best_ask:
            fail(Reason.INVALID_PRICE, f"crossed book: bid {quote.best_bid} >= ask {quote.best_ask}")
        else:
            price, size = quote.best_ask, quote.displayed_size
            if size < policy.quantity:
                fail(Reason.INSUFFICIENT_SIZE, f"displayed {size} < quantity {policy.quantity}")

    # Costs and edges exist only for a valid executable price.
    fee_quote = None
    if price is not None:
        fee_quote = fee_schedule.taker_buy(policy.quantity, price)
    if fee_schedule.status is not FeeScheduleStatus.VERIFIED and policy.fee_verification == "require":
        fail(Reason.FEE_UNVERIFIED, f"fee schedule {fee_schedule.schedule_id} is {fee_schedule.status.value}")

    gross = net_point = net_cons = net = None
    if fee_quote is not None and p_side is not None:
        gross = p_side - price
        net_point = p_side - fee_quote.cost_per_contract
        net_cons = p_cons - fee_quote.cost_per_contract
        net = net_point if policy.edge_basis == "point" else net_cons
        if not (net >= policy.min_net_edge and net > 0):
            fail(Reason.NO_EDGE, f"net edge {_q(net)} below {policy.min_net_edge} ({policy.edge_basis})")

    ordered = sorted(reasons, key=_PRECEDENCE.__getitem__)
    qualified = not ordered
    return Opportunity(
        opportunity_id=opportunity_id(
            engine=ENGINE_VERSION, as_of=as_of_utc.isoformat(), policy=policy.policy_id,
            event=event.event_id, market=market.market_id, side=side,
            model=None if estimate is None else [estimate.model_id, estimate.version, estimate.input_version],
            quote=None if quote is None else quote.evidence_id, fees=fee_schedule.schedule_id,
        ),
        engine_version=ENGINE_VERSION,
        as_of_utc=as_of_utc.isoformat(),
        policy_id=policy.policy_id,
        event_id=event.event_id,
        market_id=market.market_id,
        outcome=market.outcome,
        side=side,
        outcome_cluster=event.outcome_cluster,
        model_id=None if estimate is None else estimate.model_id,
        model_version=None if estimate is None else estimate.version,
        model_probability=_q(p_side),
        conservative_probability=_q(p_cons),
        executable_price=price,
        displayed_size=size,
        quantity=policy.quantity,
        fee=None if fee_quote is None else fee_quote.fee,
        all_in_cost=None if fee_quote is None else fee_quote.cost_per_contract,
        gross_edge=_q(gross),
        net_edge=_q(net),
        net_edge_point=_q(net_point),
        net_edge_conservative=_q(net_cons),
        book_freshness=book_state.value,
        model_freshness=model_state.value,
        freshness=combine(book_state, model_state).value,
        fee_schedule_id=fee_schedule.schedule_id,
        fee_status=fee_schedule.status.value,
        claimable=fee_schedule.status is FeeScheduleStatus.VERIFIED,
        qualification="QUALIFY" if qualified else "REJECT",
        rejection_reason=Reason.QUALIFY.value if qualified else ordered[0].value,
        reasons=tuple(r.value for r in ordered),
        details=tuple(details),
        quote_evidence_id=None if quote is None else quote.evidence_id,
        quote_received_at_utc=None if quote is None else quote.received_at_utc,
    )


def rank(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    """Deterministic total order: qualified first, then larger net edge, then identity."""

    def key(o: Opportunity) -> tuple:
        missing = o.net_edge is None
        return (
            o.qualification != "QUALIFY",
            missing,
            -(o.net_edge or Decimal(0)),
            -(o.net_edge_conservative or Decimal(0)),
            o.market_id,
            o.side,
            o.opportunity_id,
        )

    return sorted(opportunities, key=key)


def evaluate_event(
    *,
    event: Event,
    markets: Sequence[Market],
    quotes: Mapping[tuple[str, str], ExecutableQuote],
    estimates: Mapping[str, ModelEstimate],
    fee_schedule: FeeSchedule,
    policy: Policy,
    as_of: datetime,
) -> list[Opportunity]:
    """Every (market, side) of an event, evaluated and ranked. Nothing is dropped."""
    out = [
        evaluate(event=event, market=m, side=side, quote=quotes.get((m.market_id, side)),
                 estimate=estimates.get(m.market_id), fee_schedule=fee_schedule, policy=policy, as_of=as_of)
        for m in markets
        for side in SIDES
    ]
    return rank(out)


def reason_counts(opportunities: Iterable[Opportunity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in opportunities:
        counts[o.rejection_reason] = counts.get(o.rejection_reason, 0) + 1
    return dict(sorted(counts.items()))
