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
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .conservative import ProbabilityBounds
from .fee_schedules import FeeQuote, FeeScheduleStatus, valid_price, verification_at
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
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"  # the evidence set it belongs to is incomplete
    MARKET_CLOSED = "MARKET_CLOSED"
    RULES_UNRESOLVED = "RULES_UNRESOLVED"
    PAYOFF_UNSUPPORTED = "PAYOFF_UNSUPPORTED"  # the engine prices binary contracts paying 1 only
    BOOK_MISSING = "BOOK_MISSING"
    BOOK_STALE = "BOOK_STALE"
    MODEL_STALE = "MODEL_STALE"
    INVALID_PRICE = "INVALID_PRICE"
    INSUFFICIENT_SIZE = "INSUFFICIENT_SIZE"
    FEE_UNVERIFIED = "FEE_UNVERIFIED"
    FEE_UNSUPPORTED = "FEE_UNSUPPORTED"  # no fee model exists for this venue/scope: never qualifies
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
class PriceRange:
    start: Decimal
    end: Decimal
    step: Decimal


@dataclass(frozen=True)
class PriceGrid:
    """The prices a venue accepts for one market, as the venue publishes them (ADR 0023).

    A price is on the grid when it lies in some range, ends included, at a whole number of
    steps from that range's start. The grid is market metadata read by depth walks and
    tickets. `evaluate` keeps the universal 1/100-cent check (`valid_price`), so the frozen
    EXP-001 decisions do not change. Idea provenance: TPN-R003."""

    ranges: tuple[PriceRange, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.ranges:
            raise ValueError("a price grid needs at least one range")
        for r in self.ranges:
            values = (r.start, r.end, r.step)
            if not all(isinstance(v, Decimal) and v.is_finite() for v in values):
                raise ValueError(f"non-finite price range {r}")
            if not (Decimal(0) <= r.start < r.end <= Decimal(1)) or not (0 < r.step <= r.end - r.start):
                raise ValueError(f"invalid price range {r}")
            try:
                (r.end - r.start) % r.step  # a step too fine for Decimal arithmetic is refused here
            except InvalidOperation:
                raise ValueError(f"price range step {r.step} is too fine to evaluate") from None

    def contains(self, price: Decimal) -> bool:
        if not isinstance(price, Decimal) or not price.is_finite():
            return False
        try:
            return any(r.start <= price <= r.end and (price - r.start) % r.step == 0 for r in self.ranges)
        except InvalidOperation:
            return False  # fail closed: a price that cannot be checked is not on the grid


@dataclass(frozen=True)
class MarketTiming:
    """When a market's outcome, and the cash it releases, are expected, as the venue states it.

    Every field is optional: unknown stays None and is never guessed. `lifecycle_status`
    is the venue's raw status word (for example Kalshi "determined", "disputed").
    """

    event_end_utc: str | None = None  # when the underlying event/observation ends
    close_time_utc: str | None = None  # trading closes
    expected_resolution_utc: str | None = None  # the venue's forecast of when the outcome is known
    latest_resolution_utc: str | None = None  # the contractual latest time (abnormal path)
    settlement_timer_seconds: int | None = None  # dispute window after determination
    lifecycle_status: str | None = None
    rescheduled: bool = False  # the venue moved the event or its close
    source: str | None = None  # evidence id of the record these fields came from


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
    timing: MarketTiming | None = None  # never part of the opportunity id; used by eligibility policies
    price_grid: PriceGrid | None = None  # venue-published tick grid; None = not published (never assumed)
    # Semantic conformance metadata (EE v1). Never part of the opportunity id. None = a legacy
    # market: read it through `semantics_for`, which reports every field UNKNOWN, never guessed.
    semantics: ContractSemantics | None = None


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


class DepthStatus(str, Enum):
    FILLABLE = "FILLABLE"  # the captured ladder covers the whole quantity
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"  # the complete captured ladder offers less
    DEPTH_UNKNOWN = "DEPTH_UNKNOWN"  # the ladder ran out, but the capture was truncated
    INVALID_BOOK = "INVALID_BOOK"  # anomaly or malformed ladder: nothing is computed


@dataclass(frozen=True)
class DepthLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class DepthLadder:
    """Every captured offer to sell one side of a market, cheapest first.

    `asks` holds one level per price, with the sizes at that price summed by the adapter.
    `truncated` means the source returned as many levels as it was asked for, so more depth
    may exist past the last level: running out of levels is then unknown, not insufficient.
    Like `ExecutableQuote`, there is deliberately no midpoint or last-price field.
    """

    venue: str
    market_id: str
    side: str  # "YES" | "NO"
    asks: tuple[DepthLevel, ...]
    truncated: bool
    received_at_utc: str | None
    source_timestamp_utc: str | None
    evidence_id: str | None
    anomaly: str | None = None


@dataclass(frozen=True)
class DepthFill:
    """What taking `quantity` contracts from a ladder would cost, before fees.

    All or nothing: unless `status` is FILLABLE, `takes` is empty and every cost field is
    None, so a partial fill can never be priced by accident. `available` is how much the
    ladder offers up to `quantity` (None for an invalid book).
    """

    venue: str
    market_id: str
    side: str
    status: DepthStatus
    quantity: Decimal
    available: Decimal | None
    takes: tuple[DepthLevel, ...]  # (price, size taken), cheapest first
    gross_cost: Decimal | None  # sum of price * size over `takes`; fees excluded
    average_price: Decimal | None  # gross_cost / quantity, rounded up at 1e-12
    limit_price: Decimal | None  # the worst price taken: the limit a taker order would need
    detail: str


@dataclass(frozen=True)
class DepthCost:
    """A fillable ladder walk priced under one fee schedule, each take as its own taker fill.

    This is a cost, not a claim: a net result built on it still follows the schedule's
    point-in-time verification (`verification_at`), including `claim_adjusted_net` for a
    CONSERVATIVE_BOUND claim (ADR 0017)."""

    fill: DepthFill
    fee_quotes: tuple[FeeQuote, ...]
    fee: Decimal
    total_cost: Decimal  # cash that leaves the balance, fees included
    cost_per_contract: Decimal  # total_cost / quantity, rounded up at 1e-12


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
    venue: str
    status: FeeScheduleStatus

    def scope_of(self, native_id: str | None) -> str | None: ...

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
    claimable: bool  # fee evidence supports a net-result claim (claim basis not NONE) at as_of
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
    evidence_problem: str | None = None,
) -> Opportunity:
    """Evaluate buying `policy.quantity` contracts of `side` in `market` as of `as_of`.

    `evidence_problem` names a defect in the evidence set this opportunity belongs to (for
    example an INVALID Stage B day). The opportunity is still evaluated and reported, but
    it can never qualify.
    """
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

    if evidence_problem:
        fail(Reason.EVIDENCE_INCOMPLETE, evidence_problem)
    if market.status is not MarketStatus.OPEN:
        fail(Reason.MARKET_CLOSED, f"market status {market.status.value}")
    if not market.rules_resolved:
        fail(Reason.RULES_UNRESOLVED, market.rules_detail)
    if market.payoff.kind != "binary" or market.payoff.amount != 1:
        # Edges below are probability minus price per contract, which is only a dollar edge
        # for a binary contract paying exactly 1. Anything else is refused, never reinterpreted.
        fail(Reason.PAYOFF_UNSUPPORTED,
             f"payoff kind {market.payoff.kind!r} paying {market.payoff.amount}: only binary contracts paying 1")

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
    # Fee verification is point-in-time: only evidence known at as_of counts (ADR 0017).
    fee_state = verification_at(fee_schedule, as_of_utc, market.native_id)
    fee_quote = None
    if fee_state.status is FeeScheduleStatus.UNSUPPORTED:
        # No cost can be computed, so no edge exists to qualify on, whatever the policy.
        fail(Reason.FEE_UNSUPPORTED, f"no fee model for {fee_schedule.schedule_id}")
    elif price is not None:
        fee_quote = fee_schedule.taker_buy(policy.quantity, price)
    if not fee_state.claimable and policy.fee_verification == "require":
        fail(Reason.FEE_UNVERIFIED, f"fee schedule {fee_schedule.schedule_id} is {fee_state.status.value}")

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
            event=event.event_id, market=[market.market_id, market.event_id, market.status, market.rules_sha256,
                                          market.rules_resolved],
            side=side,
            model=None if estimate is None else [estimate.model_id, estimate.version, estimate.input_version,
                                                 None if estimate.probability is None else repr(estimate.probability)],
            quote=None if quote is None else [quote.evidence_id, quote.best_bid, quote.best_ask,
                                              quote.displayed_size, quote.received_at_utc, quote.anomaly],
            fees=fee_schedule.schedule_id, evidence_problem=evidence_problem,
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
        fee_status=fee_state.status.value,
        claimable=fee_state.claimable,
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
    evidence_problem: str | None = None,
) -> list[Opportunity]:
    """Every (market, side) of an event, evaluated and ranked. Nothing is dropped."""
    out = [
        evaluate(event=event, market=m, side=side, quote=quotes.get((m.market_id, side)),
                 estimate=estimates.get(m.market_id), fee_schedule=fee_schedule, policy=policy, as_of=as_of,
                 evidence_problem=evidence_problem)
        for m in markets
        for side in SIDES
    ]
    return rank(out)


# --------------------------------------------------------------------------- depth


_AVERAGE_GRID = Decimal("1e-12")


def _ladder_problem(ladder: DepthLadder, grid: PriceGrid | None) -> str | None:
    if ladder.anomaly:
        return ladder.anomaly
    previous = None
    for level in ladder.asks:
        if not valid_price(level.price):
            return f"ask {level.price} is not a valid contract price"
        if grid is not None and not grid.contains(level.price):
            return f"ask {level.price} is off the market's price grid ({grid.source})"
        if not isinstance(level.size, Decimal) or not level.size.is_finite() or level.size <= 0:
            return f"level at {level.price} has invalid size {level.size}"
        if previous is not None and level.price <= previous:
            return f"asks not strictly ascending: {level.price} after {previous}"
        previous = level.price
    return None


def walk_ladder(ladder: DepthLadder, quantity: Decimal | int, *, price_grid: PriceGrid | None = None) -> DepthFill:
    """Take `quantity` contracts from the cheapest asks upward.

    Only captured levels are used. The walk never extrapolates past the last level, and it
    never prices a partial fill (see `DepthFill`). With the market's `price_grid`, a level off
    that grid makes the whole ladder INVALID_BOOK. The result depends only on its inputs.
    """
    qty = Decimal(quantity) if isinstance(quantity, int) and not isinstance(quantity, bool) else quantity
    if not isinstance(qty, Decimal) or not qty.is_finite() or qty <= 0:
        raise ValueError("quantity must be a positive, finite number of contracts")

    def unfilled(status: DepthStatus, available: Decimal | None, detail: str) -> DepthFill:
        return DepthFill(ladder.venue, ladder.market_id, ladder.side, status, qty, available, (), None, None, None,
                         detail)

    problem = _ladder_problem(ladder, price_grid)
    if problem:
        return unfilled(DepthStatus.INVALID_BOOK, None, problem)
    remaining, takes = qty, []
    for level in ladder.asks:
        if remaining <= 0:
            break
        size = min(remaining, level.size)
        takes.append(DepthLevel(level.price, size))
        remaining -= size
    if remaining > 0:
        available = qty - remaining
        if ladder.truncated:
            return unfilled(DepthStatus.DEPTH_UNKNOWN, available,
                            f"truncated capture offers {available} < {qty}; deeper levels were not captured")
        return unfilled(DepthStatus.INSUFFICIENT_DEPTH, available, f"complete capture offers {available} < {qty}")
    gross = sum((t.price * t.size for t in takes), Decimal(0))
    return DepthFill(ladder.venue, ladder.market_id, ladder.side, DepthStatus.FILLABLE, qty, qty, tuple(takes), gross,
                     (gross / qty).quantize(_AVERAGE_GRID, rounding=ROUND_CEILING), takes[-1].price,
                     f"{len(takes)} level(s)")


def price_depth_fill(fill: DepthFill, fee_schedule: FeeSchedule) -> tuple[DepthCost | None, str]:
    """Fees for a fillable walk, each take priced as its own taker fill.

    Returns (None, why) when no cost can be stated: the walk is not fillable, the schedule
    belongs to another venue, a take is a fractional number of contracts (no fee rule for
    fractional fills is modelled), or the schedule refuses a take. It never raises. This
    makes no new fee claim: claimability stays with `verification_at` (ADR 0017), whose
    rounding allowance already covers an order that executes as several fills.
    """
    if fill.status is not DepthStatus.FILLABLE:
        return None, f"walk is {fill.status.value}: {fill.detail}"
    if fee_schedule.venue != fill.venue:
        return None, f"fee schedule {fee_schedule.schedule_id} prices {fee_schedule.venue}, not {fill.venue}"
    if any(t.size != t.size.to_integral_value() for t in fill.takes):
        return None, "a take is a fractional number of contracts; no fee rule for it is modelled"
    try:
        quotes = tuple(fee_schedule.taker_buy(int(t.size), t.price) for t in fill.takes)
    except ValueError as exc:
        return None, f"fee schedule {fee_schedule.schedule_id} refused a take: {exc}"
    total = sum((q.total_cost for q in quotes), Decimal(0))
    return DepthCost(
        fill=fill,
        fee_quotes=quotes,
        fee=sum((q.fee for q in quotes), Decimal(0)),
        total_cost=total,
        cost_per_contract=(total / fill.quantity).quantize(_AVERAGE_GRID, rounding=ROUND_CEILING),
    ), "priced"


def reason_counts(opportunities: Iterable[Opportunity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in opportunities:
        counts[o.rejection_reason] = counts.get(o.rejection_reason, 0) + 1
    return dict(sorted(counts.items()))



# --------------------------------------------------------------------------- semantic conformance (EE v1)
#
# The minimum metadata two contracts need before any economic comparison between them is
# meaningful (#96, handoff section 6). It is additive: legacy `Market`s carry no semantics and
# `semantics_for` reads them as UNKNOWN, so every frozen EXP-001 id and output is unchanged, and
# nothing downstream may treat an unknown unit, rule, fee, clock or right as a known one.

SEMANTICS_VERSION = "contract-semantics-v1"


class ProbabilityMeaning(str, Enum):
    """What a probability-like number means. These are never interchangeable."""

    PHYSICAL_ESTIMATE = "PHYSICAL_ESTIMATE"  # a model's estimate of the real-world frequency
    SPORTSBOOK_CONSENSUS = "SPORTSBOOK_CONSENSUS"  # de-vigged book prices (conditional on book rules)
    MARKET_IMPLIED_PRICE = "MARKET_IMPLIED_PRICE"  # an executable price read as a probability
    RISK_NEUTRAL_OPTION_QUANTITY = "RISK_NEUTRAL_OPTION_QUANTITY"  # not a physical probability
    DETERMINISTIC_PAYOFF_BOUND = "DETERMINISTIC_PAYOFF_BOUND"  # a replication/payoff bound, no probability
    UNKNOWN = "UNKNOWN"


class RelationTier(str, Enum):
    """The economic relation between contracts, independent of probability meaning."""

    EQUIVALENT = "EQUIVALENT"  # identical payoff in every admissible state (proven)
    CONDITIONAL_EQUIVALENT = "CONDITIONAL_EQUIVALENT"  # identical only on stated states (e.g. no tie, played)
    COMPLEMENT = "COMPLEMENT"
    PARTITION_MEMBER = "PARTITION_MEMBER"
    NESTED_THRESHOLD = "NESTED_THRESHOLD"
    RELATED_NOT_EQUIVALENT = "RELATED_NOT_EQUIVALENT"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


class OutcomeFinality(str, Enum):
    PENDING = "PENDING"
    PRELIMINARY = "PRELIMINARY"
    CORRECTED = "CORRECTED"
    FINAL = "FINAL"
    UNKNOWN = "UNKNOWN"


class ClockKind(str, Enum):
    EVENT = "EVENT"  # when the real-world thing happened
    SOURCE_UPDATE = "SOURCE_UPDATE"  # the source's own update time
    FIRST_OBSERVED = "FIRST_OBSERVED"  # when we first saw this content
    RECEIPT = "RECEIPT"  # fetched_at_utc of this copy
    INGESTION = "INGESTION"  # stored
    PROCESSING = "PROCESSING"  # derived


class FeeRoundingScope(str, Enum):
    PER_FILL = "PER_FILL"  # each fill (each ladder level taken) is rounded on its own
    PER_ORDER = "PER_ORDER"
    PER_SETTLEMENT = "PER_SETTLEMENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class UnitSemantics:
    """Native units exactly as the venue documents them. None = UNKNOWN (never assumed)."""

    quantity_step: Decimal | None  # smallest native quantity (Kalshi fixed point: 0.01)
    price_convention: str | None  # e.g. "USD_PER_CONTRACT", "DECIMAL_PROBABILITY_PER_CENT_CONTRACT"
    payout_per_unit: Decimal | None  # what one winning native unit pays, in `currency`
    currency: str | None
    multiplier: Decimal | None
    normalization_version: str
    evidence: str = ""
    verification: str = "UNVERIFIED"  # VERIFIED_FROM_DOCS (dated fixture) | UNVERIFIED

    @property
    def known(self) -> bool:
        return None not in (self.quantity_step, self.price_convention, self.payout_per_unit, self.currency,
                            self.multiplier)

    def incompatibility(self, other: "UnitSemantics") -> str | None:
        """Why a quantity of `self` cannot be added to a quantity of `other` without an explicit
        conversion, or None when they are the same native unit."""
        if not (self.known and other.known):
            return "native units UNKNOWN"
        for name in ("price_convention", "payout_per_unit", "currency", "multiplier"):
            if getattr(self, name) != getattr(other, name):
                return f"native {name} differs: {getattr(self, name)} vs {getattr(other, name)}"
        return None


def payout_value(quantity: Decimal, units: UnitSemantics) -> Decimal:
    """The currency value of `quantity` winning native units: the only unit conversion allowed.

    Refuses unknown units and quantities off the native step (a fractional count is never
    truncated, and a one-cent contract is never counted as a $1 contract)."""
    if not units.known:
        raise ValueError("native units are UNKNOWN: no conversion is possible")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
        raise ValueError("quantity must be a non-negative finite Decimal")
    if quantity % units.quantity_step != 0:
        raise ValueError(f"quantity {quantity} is off the native step {units.quantity_step}")
    return quantity * units.payout_per_unit * units.multiplier


# Dated venue facts (tests/fixtures/conformance/venue_facts_2026-09-25.json holds the source
# quotes and URLs). Verified from documentation only; no endpoint was called.
KALSHI_BINARY_UNITS = UnitSemantics(
    quantity_step=Decimal("0.01"), price_convention="USD_PER_CONTRACT", payout_per_unit=Decimal("1"),
    currency="USD", multiplier=Decimal("1"), normalization_version="kalshi-fixed-point-v1",
    evidence="docs.kalshi.com/getting_started/fixed_point_migration (last updated 2026-08-20): minimum "
             "granularity 0.01 contracts; fractional values appear in fills",
    verification="VERIFIED_FROM_DOCS")
NOVIG_V3_UNITS = UnitSemantics(
    quantity_step=Decimal("1"), price_convention="DECIMAL_PROBABILITY_PER_CENT_CONTRACT",
    payout_per_unit=Decimal("0.01"), currency="USD", multiplier=Decimal("1"),
    normalization_version="novig-v3-cent-contract-v1",
    evidence="docs.novig.com api-reference execution/place-an-order and public/get-the-order-book (API 3.0.0): "
             "a winning contract pays 1 cent; integer contract counts",
    verification="VERIFIED_FROM_DOCS")


@dataclass(frozen=True)
class RulesIdentity:
    rules_sha256: str | None
    settlement_identity: str | None  # source, station/instrument, window: what settles it
    evidence_hash: str | None  # the captured rules document or payload
    captured_at_utc: str | None


@dataclass(frozen=True)
class FeeSemantics:
    schedule_id: str | None
    effective_from_utc: str | None
    rounding_scope: FeeRoundingScope
    claim_basis: str  # fee_schedules.ClaimBasis value at the evaluation time; NONE when unknown


@dataclass(frozen=True)
class ClockStamp:
    kind: ClockKind
    value_utc: str | None
    precision_seconds: Decimal | None  # None = UNKNOWN
    uncertainty_seconds: Decimal | None  # None = UNKNOWN
    origin: str  # which field or process produced it


@dataclass(frozen=True)
class DataRights:
    """Use restrictions a dataset carries. A derived dataset inherits the union of its inputs'."""

    restrictions: frozenset[str]
    sources: tuple[str, ...]
    version: str = "data-rights-v1"

    @staticmethod
    def inherit(*inputs: "DataRights | None") -> "DataRights":
        """The most restrictive combination. An input with unknown rights adds UNKNOWN_RIGHTS:
        it never makes the output less restricted."""
        restrictions: set[str] = set()
        sources: list[str] = []
        for rights in inputs:
            if rights is None:
                restrictions.add("UNKNOWN_RIGHTS")
                continue
            restrictions |= set(rights.restrictions)
            sources += [s for s in rights.sources if s not in sources]
        return DataRights(frozenset(restrictions), tuple(sources))


@dataclass(frozen=True)
class ContractSemantics:
    units: UnitSemantics
    rules: RulesIdentity
    fees: FeeSemantics | None
    probability_meaning: ProbabilityMeaning
    relation_tier: RelationTier
    source_family: str | None  # None = UNKNOWN (independence is never assumed)
    clocks: tuple[ClockStamp, ...]
    finality: OutcomeFinality
    rights: DataRights | None
    version: str = SEMANTICS_VERSION
    legacy: bool = False


LEGACY_UNITS = UnitSemantics(None, None, None, None, None, normalization_version="legacy-unknown")


def semantics_for(market: Market) -> ContractSemantics:
    """The compatibility reader. A market built before EE v1 has no semantics: every field is
    UNKNOWN except what the legacy contract already states (its rules hash). Its `Payoff.amount`
    is the frozen engine's binary assumption, not documented native units, so it is not copied."""
    if market.semantics is not None:
        return market.semantics
    return ContractSemantics(
        units=LEGACY_UNITS,
        rules=RulesIdentity(market.rules_sha256, None, None, None),
        fees=None,
        probability_meaning=ProbabilityMeaning.UNKNOWN,
        relation_tier=RelationTier.UNKNOWN,
        source_family=None,
        clocks=(),
        finality=OutcomeFinality.UNKNOWN,
        rights=None,
        legacy=True,
    )
