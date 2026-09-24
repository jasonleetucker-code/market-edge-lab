"""Best price for size: one comparator over the shared market objects (ADR 0027, issue #30).

Input: a requested position (a reference event and market, a side, a quantity) and candidate
routes. Each route is one market on one venue, with its captured ask ladder for that side and
its fee schedule (`fee_schedules.schedule_for`). There is no venue-specific logic here: every
number comes from the shared primitives:

- `opportunity.walk_ladder(ladder, qty, price_grid=market.price_grid)` for the depth walk and
  the market's own tick grid (its first production caller, ADR 0023);
- `opportunity.price_depth_fill` for fees, each take priced as its own taker fill;
- `fee_schedules.verification_at` / `claim_adjusted_net` for what the fee evidence supports;
- `discovery.is_equivalent` for rule equivalence (a title never counts);
- `venues` for account-route availability, `starter_policy` for capital release timing.

Four claims are made separately, each only when the evidence supports it; otherwise it is None
with a machine-readable reason:

- BEST OBSERVED QUOTE: the lowest top-of-book ask. It is a quote, not a fill for the size.
- BEST GROSS COST FOR SIZE: the lowest cost of the whole quantity before fees, from a ladder
  that covers it.
- BEST VERIFIED TOTAL COST: the lowest total with fees, among routes whose fee evidence
  supports a claim (claim basis EXACT or CONSERVATIVE_BOUND). Under CONSERVATIVE_BOUND the
  total includes the rounding allowance, so it is an upper bound: the lowest bound, which is
  not by itself a proven order (`proven_cheaper`, `Claim.proven_below`).
- BEST ACCOUNT-FEASIBLE ROUTE: the above, restricted to routes with a connected account
  (`venues`: account read LIVE_DATA_VERIFIED) and capital eligible under `STARTER_MAX_7D_V1`.

Every claim ranks routes with a FRESH book only; a stale or unknown-age route that would
otherwise pass is named in `Claim.stale_candidates`. Markets that are not rule-equivalent to
the request are listed as RELATED and never priced against it, and a market is compared with
at most one capture of itself. Payoffs other than a binary contract paying 1 (for example
Polymarket US `binary_split_on_cancel`) are refused, never reinterpreted. The summary says one
route "is cheaper" than another only when that is proven (`proven_cheaper`).

Nothing here connects, authenticates or trades. `execution_authorized` is always False.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from typing import Any, Iterable, Sequence

from . import starter_policy, venues
from .discovery import _series_scope, is_equivalent
from .fee_schedules import ClaimBasis, FeeScheduleStatus, claim_adjusted_net, verification_at
from .freshness import Freshness, parse_utc
from .opportunity import (
    SIDES, DepthFill, DepthLadder, DepthStatus, Event, FeeSchedule, Market, MarketStatus, _freshness, _plain,
    price_depth_fill, walk_ladder,
)

COMPARATOR_VERSION = "1"


class FeeStatus(str, Enum):
    VERIFIED = "VERIFIED"  # claim basis EXACT: the fee is the venue's exact debit
    CONSERVATIVE_BOUND = "CONSERVATIVE_BOUND"  # the total plus the allowance bounds the real debit
    UNVERIFIED = "UNVERIFIED"  # a documented schedule prices it, but no claim may rest on it
    UNSUPPORTED = "UNSUPPORTED"  # no fee model: the fee is unknown


class Liquidity(str, Enum):
    FILLABLE = "FILLABLE"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"  # the complete captured ladder offers less
    DEPTH_UNKNOWN = "DEPTH_UNKNOWN"  # the ladder ran out, but the capture was truncated
    INVALID_BOOK = "INVALID_BOOK"  # anomaly, malformed or off-grid level, or the wrong market/side
    BOOK_MISSING = "BOOK_MISSING"


class Equivalence(str, Enum):
    REFERENCE = "REFERENCE"  # the requested market itself
    MATCHED_EQUIVALENT = "MATCHED_EQUIVALENT"  # discovery.is_equivalent
    RELATED_NOT_EQUIVALENT = "RELATED_NOT_EQUIVALENT"  # listed, never compared


class Exclusion(str, Enum):
    """Why a route cannot back a claim. The order is the gate order: a route that fails a
    later gate got further than one that fails an earlier gate."""

    PAYOFF_UNSUPPORTED = "PAYOFF_UNSUPPORTED"
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    BOOK_MISSING = "BOOK_MISSING"
    INVALID_BOOK = "INVALID_BOOK"
    NO_OFFER = "NO_OFFER"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    DEPTH_UNKNOWN = "DEPTH_UNKNOWN"
    FEE_UNSUPPORTED = "FEE_UNSUPPORTED"
    FEE_NOT_PRICED = "FEE_NOT_PRICED"
    FEE_UNVERIFIED = "FEE_UNVERIFIED"
    NOT_FRESH = "NOT_FRESH"
    NO_ACCOUNT_CONNECTED = "NO_ACCOUNT_CONNECTED"
    CAPITAL_RELEASE_INELIGIBLE = "CAPITAL_RELEASE_INELIGIBLE"


_GATE = {e: i for i, e in enumerate(Exclusion)}


class ClaimKind(str, Enum):
    BEST_OBSERVED_QUOTE = "BEST_OBSERVED_QUOTE"
    BEST_GROSS_COST_FOR_SIZE = "BEST_GROSS_COST_FOR_SIZE"
    BEST_VERIFIED_TOTAL_COST = "BEST_VERIFIED_TOTAL_COST"
    BEST_ACCOUNT_FEASIBLE_ROUTE = "BEST_ACCOUNT_FEASIBLE_ROUTE"


# Every claim ranks FRESH routes only; a route stale or of unknown freshness that passes every
# other gate is named in the claim's `stale_candidates`, never ranked.
_OBSERVED = frozenset({Exclusion.PAYOFF_UNSUPPORTED, Exclusion.MARKET_NOT_OPEN, Exclusion.BOOK_MISSING,
                       Exclusion.INVALID_BOOK, Exclusion.NO_OFFER, Exclusion.NOT_FRESH})
_GROSS = _OBSERVED | {Exclusion.INSUFFICIENT_DEPTH, Exclusion.DEPTH_UNKNOWN}
_VERIFIED = _GROSS | {Exclusion.FEE_UNSUPPORTED, Exclusion.FEE_NOT_PRICED, Exclusion.FEE_UNVERIFIED}
_FEASIBLE = _VERIFIED | {Exclusion.NO_ACCOUNT_CONNECTED, Exclusion.CAPITAL_RELEASE_INELIGIBLE}
CLAIM_GATES = {ClaimKind.BEST_OBSERVED_QUOTE: _OBSERVED, ClaimKind.BEST_GROSS_COST_FOR_SIZE: _GROSS,
               ClaimKind.BEST_VERIFIED_TOTAL_COST: _VERIFIED, ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE: _FEASIBLE}
CLAIM_BASIS_TEXT = {
    ClaimKind.BEST_OBSERVED_QUOTE: "top-of-book ask per contract from a fresh book; a quote, not a fill for the size",
    ClaimKind.BEST_GROSS_COST_FOR_SIZE: "cost of the whole quantity from a fresh captured ladder, fees excluded",
    ClaimKind.BEST_VERIFIED_TOTAL_COST: "total with fees, claim-grade fee evidence, fresh book; an upper bound "
                                        "under CONSERVATIVE_BOUND (lowest bound, not a proven order: see proven_below)",
    ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE: "verified total on a connected account with capital eligible under "
                                           f"{starter_policy.POLICY_ID}; execution is never authorized",
}
# Reasons a claim can be absent that are not a route's own exclusion.
NO_EQUIVALENT_ROUTE = "NO_EQUIVALENT_ROUTE"
NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"

VENUE_NAMES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US", "polymarket_international":
               "Polymarket International", "novig": "Novig"}


# --------------------------------------------------------------------------- contracts


@dataclass(frozen=True)
class PositionRequest:
    """Buy `quantity` contracts of `side` of the payoff that `market` defines."""

    event: Event
    market: Market
    side: str
    quantity: Decimal | int

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"unknown side {self.side!r}")
        qty = self.quantity
        if isinstance(qty, bool) or not isinstance(qty, (int, Decimal)) or not Decimal(qty).is_finite() or qty <= 0:
            raise ValueError("quantity must be a positive, finite number of contracts")


@dataclass(frozen=True)
class Route:
    """One market on one venue, its captured ask ladder for the requested side (None when no
    book was captured) and its fee schedule (`fee_schedules.schedule_for`)."""

    event: Event
    market: Market
    ladder: DepthLadder | None
    fee_schedule: FeeSchedule


@dataclass(frozen=True)
class RouteAssessment:
    venue: str
    market_id: str
    side: str
    quantity: Decimal
    equivalence: str
    payoff_kind: str
    market_status: str
    liquidity: str | None  # None: not assessed (payoff unsupported)
    available: Decimal | None  # offered up to the quantity
    observed_ask: Decimal | None  # top-of-book ask
    observed_ask_size: Decimal | None
    gross_cost: Decimal | None
    average_price: Decimal | None
    worst_price: Decimal | None  # the deepest price taken: the limit a taker order would need
    levels_taken: int
    fee_schedule_id: str
    fee_status: str
    claim_basis: str
    fee: Decimal | None  # None: unknown or not priced
    total_cost: Decimal | None  # gross + fee under the schedule; an estimate unless claim-grade
    claim_total_cost: Decimal | None  # total a claim may use (allowance included); None: no claim
    fee_detail: str
    freshness: str
    book_received_at_utc: str | None
    book_evidence_id: str | None
    account_read_stage: str | None
    account_connected: bool
    capital_release_eta_utc: str | None  # STARTER_MAX_7D_V1 tradable-cash release; None: UNKNOWN
    capital_release_eligible: bool
    capital_release_reasons: tuple[str, ...]
    exclusions: tuple[str, ...]  # gate order
    details: tuple[str, ...]
    execution_authorized: bool = False


@dataclass(frozen=True)
class Claim:
    kind: str
    supported: bool
    market_id: str | None
    venue: str | None
    value: Decimal | None  # quote: price per contract; the others: cost of the whole quantity
    basis: str
    reason: str | None  # machine-readable, when not supported
    detail: str
    candidates: tuple[str, ...]  # market ids that passed this claim's gates (fresh routes only)
    freshness: str | None = None  # the winning route's book freshness (always "fresh" when supported)
    stale_candidates: tuple[str, ...] = ()  # would have passed but the book is stale or of unknown age
    # Candidates whose real cost is PROVEN above the winner's. For quotes and gross costs these
    # are observed values, so a strictly higher value is proven. For totals it needs
    # `proven_cheaper`: a bound below another bound proves nothing.
    proven_below: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comparison:
    comparator_version: str
    as_of_utc: str
    request_market_id: str
    side: str
    quantity: Decimal
    max_book_age_seconds: int
    routes: tuple[RouteAssessment, ...]  # equivalent routes only (REFERENCE, MATCHED_EQUIVALENT)
    related: tuple[str, ...]  # market ids offered but not equivalent: never compared
    claims: tuple[Claim, ...]
    summary: str
    execution_authorized: bool = False

    def claim(self, kind: ClaimKind | str) -> Claim:
        kind = ClaimKind(kind).value
        return next(c for c in self.claims if c.kind == kind)

    def to_dict(self) -> dict[str, Any]:
        return {k: _plain(v) for k, v in asdict(self).items()}


# --------------------------------------------------------------------------- assessment


def _payoff_supported(market: Market) -> bool:
    # The same guard as `opportunity.evaluate` (PAYOFF_UNSUPPORTED): binary paying exactly 1.
    return market.payoff.kind == "binary" and market.payoff.amount == 1


def _contract(event: Event, market: Market) -> tuple:
    return (market.venue, market.market_id, market.event_id, market.outcome, market.payoff, market.rules_sha256,
            event.event_id, event.settlement_identity)


def _equivalence(request: PositionRequest, route: Route) -> Equivalence:
    a, b = request.market, route.market
    if b.market_id == a.market_id:
        # The requested market itself, only when every contract field matches (a later capture may
        # differ in status or timing, never in rules). A capture of the same market whose rules or
        # payoff changed is never compared with the request: it is RELATED.
        same = _contract(route.event, b) == _contract(request.event, a)
        return Equivalence.REFERENCE if same else Equivalence.RELATED_NOT_EQUIVALENT
    if is_equivalent(request.event, request.market, route.event, route.market):
        return Equivalence.MATCHED_EQUIVALENT
    return Equivalence.RELATED_NOT_EQUIVALENT


def _fee_status(basis: ClaimBasis, status: FeeScheduleStatus) -> FeeStatus:
    if status is FeeScheduleStatus.UNSUPPORTED:
        return FeeStatus.UNSUPPORTED
    return {ClaimBasis.EXACT: FeeStatus.VERIFIED, ClaimBasis.CONSERVATIVE_BOUND: FeeStatus.CONSERVATIVE_BOUND}.get(
        basis, FeeStatus.UNVERIFIED)


def _walk(route: Route, side: str, qty: Decimal) -> tuple[Liquidity, DepthFill | None, str]:
    ladder, market = route.ladder, route.market
    if ladder is None:
        return Liquidity.BOOK_MISSING, None, "no captured book for this market and side"
    if (ladder.venue, ladder.market_id, ladder.side) != (market.venue, market.market_id, side):
        return Liquidity.INVALID_BOOK, None, (f"ladder is for {ladder.venue}/{ladder.market_id}/{ladder.side}, not "
                                              f"{market.venue}/{market.market_id}/{side}")
    fill = walk_ladder(ladder, qty, price_grid=market.price_grid)
    return Liquidity(fill.status.value), fill, fill.detail


def assess_route(request: PositionRequest, route: Route, *, as_of: datetime,
                 max_book_age: timedelta) -> RouteAssessment:
    """Every fact the claims need about one route, with its exclusions in gate order."""
    at = parse_utc(as_of)
    if at is None:
        raise ValueError("as_of must be timezone-aware")
    side, qty = request.side, Decimal(request.quantity)
    market, ladder = route.market, route.ladder
    out: set[Exclusion] = set()
    details: list[str] = []

    def exclude(reason: Exclusion, detail: str) -> None:
        out.add(reason)
        details.append(f"{reason.value}: {detail}")

    equivalence = _equivalence(request, route)
    payoff_ok = _payoff_supported(market)
    if not payoff_ok:
        exclude(Exclusion.PAYOFF_UNSUPPORTED, f"payoff kind {market.payoff.kind!r} paying {market.payoff.amount}: "
                                              "only binary contracts paying 1 are priced")
    if market.status is not MarketStatus.OPEN:
        exclude(Exclusion.MARKET_NOT_OPEN, f"market status {market.status.value}")

    # Depth: never walked for a refused payoff, so no price for it can be quoted by accident.
    liquidity: Liquidity | None = None
    fill: DepthFill | None = None
    observed = observed_size = None
    if payoff_ok:
        liquidity, fill, why = _walk(route, side, qty)
        if liquidity is Liquidity.BOOK_MISSING:
            exclude(Exclusion.BOOK_MISSING, why)
        elif liquidity is Liquidity.INVALID_BOOK:
            exclude(Exclusion.INVALID_BOOK, why)
        else:
            if ladder.asks:
                observed, observed_size = ladder.asks[0].price, ladder.asks[0].size
            else:
                exclude(Exclusion.NO_OFFER, "nothing offered on this side")
            if liquidity is Liquidity.INSUFFICIENT_DEPTH:
                exclude(Exclusion.INSUFFICIENT_DEPTH, why)
            elif liquidity is Liquidity.DEPTH_UNKNOWN:
                exclude(Exclusion.DEPTH_UNKNOWN, why)

    # Fees: point-in-time evidence (ADR 0017); a cost only for a fillable walk.
    schedule = route.fee_schedule
    state = verification_at(schedule, at, market.native_id)
    fee_status = _fee_status(state.claim_basis, state.status)
    fee = total = claim_total = None
    fee_detail = state.detail
    if fee_status is FeeStatus.UNSUPPORTED:
        exclude(Exclusion.FEE_UNSUPPORTED, f"no fee model: {schedule.schedule_id}")
    elif fill is not None and fill.status is DepthStatus.FILLABLE:
        cost, why = price_depth_fill(fill, schedule)
        if cost is None:
            exclude(Exclusion.FEE_NOT_PRICED, why)
            fee_detail = f"{fee_detail}; not priced: {why}"
        else:
            fee, total = cost.fee, cost.total_cost
            if state.claimable:
                adjusted = claim_adjusted_net(-total, qty, state)  # the claim-grade cost is -(net) of a zero payout
                claim_total = None if adjusted is None else -adjusted
    if fee_status is FeeStatus.UNVERIFIED:
        exclude(Exclusion.FEE_UNVERIFIED, f"{schedule.schedule_id}: claim basis {state.claim_basis.value}")
    if fee_status in (FeeStatus.VERIFIED, FeeStatus.CONSERVATIVE_BOUND) and fill is not None \
            and fill.status is DepthStatus.FILLABLE and claim_total is None and Exclusion.FEE_NOT_PRICED not in out:
        exclude(Exclusion.FEE_NOT_PRICED, "the claim allowance is unknown")

    # Freshness: a stale or unknown-age book is never ranked by any claim (Claim.stale_candidates).
    fresh, why = (Freshness.UNKNOWN, "no captured book") if ladder is None else _freshness(
        ladder.received_at_utc, max_age=max_book_age, as_of=at)
    if fresh is not Freshness.FRESH:
        exclude(Exclusion.NOT_FRESH, f"book {fresh.value}: {why}")

    # Account route: only a recorded account read counts as connected (venues, ADR 0019).
    spec = venues.VENUES.get(market.venue)
    stage = None if spec is None else spec.stage(venues.Capability.ACCOUNT_READ)
    connected = stage is venues.ConnectivityStage.LIVE_DATA_VERIFIED
    if not connected:
        exclude(Exclusion.NO_ACCOUNT_CONNECTED, f"account read for {market.venue} is "
                                                f"{stage.value if stage else 'not registered'}")

    # Capital release timing: the starter policy's governing clock, unknown stays unknown.
    verdict = starter_policy.assess(commitment=at, timing=market.timing,
                                    lag=starter_policy.lag_evidence(market.venue, _series_scope(market)),
                                    cash=venues.cash_timing(market.venue))
    if not verdict.eligible:
        exclude(Exclusion.CAPITAL_RELEASE_INELIGIBLE, ", ".join(verdict.reasons))

    ordered = tuple(e.value for e in sorted(out, key=_GATE.__getitem__))
    return RouteAssessment(
        venue=market.venue, market_id=market.market_id, side=side, quantity=qty, equivalence=equivalence.value,
        payoff_kind=market.payoff.kind, market_status=market.status.value,
        liquidity=None if liquidity is None else liquidity.value,
        available=None if fill is None else fill.available,
        observed_ask=observed, observed_ask_size=observed_size,
        gross_cost=None if fill is None else fill.gross_cost,
        average_price=None if fill is None else fill.average_price,
        worst_price=None if fill is None else fill.limit_price,
        levels_taken=0 if fill is None else len(fill.takes),
        fee_schedule_id=schedule.schedule_id, fee_status=fee_status.value, claim_basis=state.claim_basis.value,
        fee=fee, total_cost=total, claim_total_cost=claim_total, fee_detail=fee_detail,
        freshness=fresh.value, book_received_at_utc=None if ladder is None else ladder.received_at_utc,
        book_evidence_id=None if ladder is None else ladder.evidence_id,
        account_read_stage=None if stage is None else stage.value, account_connected=connected,
        capital_release_eta_utc=verdict.tradable_cash_release_eta_utc,
        capital_release_eligible=verdict.eligible, capital_release_reasons=verdict.reasons,
        exclusions=ordered, details=tuple(details),
    )


# --------------------------------------------------------------------------- claims


def _claim_value(kind: ClaimKind, r: RouteAssessment) -> Decimal | None:
    if kind is ClaimKind.BEST_OBSERVED_QUOTE:
        return r.observed_ask
    if kind is ClaimKind.BEST_GROSS_COST_FOR_SIZE:
        return r.gross_cost
    return r.claim_total_cost


def _order(r: RouteAssessment) -> tuple:
    return (r.venue, r.market_id, r.book_evidence_id or "", r.book_received_at_utc or "")


def proven_cheaper(a: RouteAssessment, b: RouteAssessment) -> bool:
    """Is `a`'s real total cost PROVEN below `b`'s? Both need claim-grade totals.

    `a.claim_total_cost` is an upper bound on what `a` really costs (exact when VERIFIED). What
    `b` really costs is known exactly only when its fee is VERIFIED (EXACT); under
    CONSERVATIVE_BOUND it lies between its gross cost (a taker never pays less than price x
    quantity) and its claim total. So `a` is proven cheaper only when its bound is below `b`'s
    exact total, or below `b`'s gross cost. Two overlapping bounds prove no order."""
    if a.claim_total_cost is None or b.claim_total_cost is None:
        return False
    floor = b.claim_total_cost if b.fee_status == FeeStatus.VERIFIED.value else b.gross_cost
    return floor is not None and a.claim_total_cost < floor


def _proven_below(kind: ClaimKind, best: RouteAssessment, passing: Sequence[RouteAssessment]) -> tuple[str, ...]:
    others = [r for r in sorted(passing, key=_order) if r is not best]
    if kind in (ClaimKind.BEST_OBSERVED_QUOTE, ClaimKind.BEST_GROSS_COST_FOR_SIZE):
        # Observed prices and ladder costs are exact observations, not bounds.
        return tuple(r.market_id for r in others if _claim_value(kind, r) > _claim_value(kind, best))
    return tuple(r.market_id for r in others if proven_cheaper(best, r))


def _make_claim(kind: ClaimKind, routes: Sequence[RouteAssessment], request_problem: str | None) -> Claim:
    gates = CLAIM_GATES[kind]
    basis = CLAIM_BASIS_TEXT[kind]
    fresh_gates = gates - {Exclusion.NOT_FRESH}
    stale = tuple(r.market_id for r in sorted(routes, key=_order)
                  if Exclusion.NOT_FRESH.value in r.exclusions and _claim_value(kind, r) is not None
                  and not fresh_gates & {Exclusion(e) for e in r.exclusions})

    def absent(reason: str, detail: str) -> Claim:
        return Claim(kind.value, False, None, None, None, basis, reason, detail, (), None,
                     stale if request_problem is None else ())

    if request_problem is not None:
        return absent(Exclusion.PAYOFF_UNSUPPORTED.value, request_problem)
    if not routes:
        return absent(NO_EQUIVALENT_ROUTE, "no route is the requested market or rule-equivalent to it")
    passing = [r for r in routes if not gates & {Exclusion(e) for e in r.exclusions}
               and _claim_value(kind, r) is not None]
    if not passing:
        # The route that got furthest through the gates names the reason.
        firsts = [min((Exclusion(e) for e in r.exclusions if Exclusion(e) in gates), key=_GATE.__getitem__)
                  for r in routes if any(Exclusion(e) in gates for e in r.exclusions)]
        reason = max(firsts, key=_GATE.__getitem__).value if firsts else NO_ELIGIBLE_ROUTE
        blocked = "; ".join(f"{r.market_id}: {', '.join(e for e in r.exclusions if Exclusion(e) in gates)}"
                            for r in sorted(routes, key=_order))
        return absent(reason, f"no route passes the {kind.value} gates ({blocked})")
    best = min(passing, key=lambda r: (_claim_value(kind, r), _order(r)))
    candidates = tuple(r.market_id for r in sorted(passing, key=_order))
    return Claim(kind.value, True, best.market_id, best.venue, _claim_value(kind, best), basis, None,
                 f"lowest of {len(passing)} fresh route(s) passing the {kind.value} gates", candidates,
                 best.freshness, stale, _proven_below(kind, best, passing))


def compare(request: PositionRequest, routes: Iterable[Route], *, as_of: datetime,
            max_book_age: timedelta) -> Comparison:
    """Assess every equivalent route and make the four claims. Deterministic in its inputs."""
    at = parse_utc(as_of)
    if at is None:
        raise ValueError("as_of must be timezone-aware")
    if not isinstance(max_book_age, timedelta) or max_book_age < timedelta(0):
        raise ValueError("max_book_age must be a non-negative timedelta")
    routes = list(routes)
    seen: set[str] = set()
    for route in routes:
        # One capture per market: two captures of one market must never compete with each other.
        if route.market.market_id in seen:
            raise ValueError(f"more than one route for {route.market.market_id}: pass exactly one capture per market")
        seen.add(route.market.market_id)
    assessed: list[RouteAssessment] = []
    related: set[str] = set()
    for route in routes:
        if _equivalence(request, route) is Equivalence.RELATED_NOT_EQUIVALENT:
            related.add(route.market.market_id)
        else:
            assessed.append(assess_route(request, route, as_of=at, max_book_age=max_book_age))
    assessed.sort(key=_order)
    problem = None
    if not _payoff_supported(request.market):
        problem = (f"requested payoff kind {request.market.payoff.kind!r} paying {request.market.payoff.amount} is not "
                   "supported: only binary contracts paying 1 are compared")
    claims = tuple(_make_claim(kind, assessed, problem) for kind in ClaimKind)
    qty = Decimal(request.quantity)
    related_ids = tuple(sorted(related))
    return Comparison(
        comparator_version=COMPARATOR_VERSION, as_of_utc=at.isoformat(), request_market_id=request.market.market_id,
        side=request.side, quantity=qty, max_book_age_seconds=int(max_book_age.total_seconds()),
        routes=tuple(assessed), related=related_ids, claims=claims,
        summary=summarize(request, tuple(assessed), related_ids, claims, at, problem),
    )


# --------------------------------------------------------------------------- summary


def _usd(value: Decimal) -> str:
    """Dollars, rounded up (a displayed cost is never understated): cents when exact, else 1/100 cent."""
    cents = value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return f"${cents}" if cents == value else f"${value.quantize(Decimal('0.0001'), rounding=ROUND_CEILING)}"


def _name(venue: str) -> str:
    return VENUE_NAMES.get(venue, venue)


def _cost_range(r: RouteAssessment) -> str:
    if r.fee_status == FeeStatus.VERIFIED.value:
        return f"{_name(r.venue)} exactly {_usd(r.claim_total_cost)}"
    return f"{_name(r.venue)} between {_usd(r.gross_cost)} and {_usd(r.claim_total_cost)}"


def _route_line(r: RouteAssessment) -> str:
    name, ex = _name(r.venue), set(r.exclusions)
    where = f"{name} ({r.market_id})"
    if Exclusion.PAYOFF_UNSUPPORTED.value in ex:
        return f"{where}: payoff {r.payoff_kind} is not supported; not priced"
    if r.liquidity == Liquidity.BOOK_MISSING.value:
        return f"{where}: no captured book"
    if r.liquidity == Liquidity.INVALID_BOOK.value:
        return f"{where}: invalid book; not priced"
    if r.liquidity == Liquidity.INSUFFICIENT_DEPTH.value:
        return f"{where}: insufficient depth ({r.available} of {r.quantity} offered)"
    if r.liquidity == Liquidity.DEPTH_UNKNOWN.value:
        return f"{where}: depth unknown (truncated capture shows {r.available} of {r.quantity})"
    fresh = "" if r.freshness == Freshness.FRESH.value else f"; book {r.freshness}"
    closed = "" if r.market_status == MarketStatus.OPEN.value else f"; market {r.market_status}"
    gross = _usd(r.gross_cost)
    if r.claim_total_cost is not None and Exclusion.NOT_FRESH.value not in ex:
        bound = " at most" if r.fee_status == FeeStatus.CONSERVATIVE_BOUND.value else ""
        return f"{where}{bound} {_usd(r.claim_total_cost)} total ({gross} gross, fees {r.fee_status}){closed}"
    if r.claim_total_cost is not None:
        return f"{where} {gross} gross; total not claimed{fresh}{closed}"
    if r.fee_status == FeeStatus.UNVERIFIED.value and r.fee is not None:
        return (f"{where} {gross} gross, fees unverified (published-schedule estimate {_usd(r.fee)}, not "
                f"claim-grade){fresh}{closed}")
    if r.fee_status == FeeStatus.UNSUPPORTED.value:
        return f"{where} {gross} gross, fees unknown{fresh}{closed}"
    return f"{where} {gross} gross, fees not priced{fresh}{closed}"


def summarize(request: PositionRequest, routes: tuple[RouteAssessment, ...], related: tuple[str, ...],
              claims: tuple[Claim, ...], at: datetime, problem: str | None) -> str:
    """Deterministic plain text. "Cheaper" appears only where `proven_cheaper` holds: both
    routes carry a verified total, and the winner's bound is below the other's exact total or
    below its gross cost. Overlapping bounds are stated as separate figures, with no order."""
    by_kind = {c.kind: c for c in claims}
    lines = [f"Buy {Decimal(request.quantity)} {request.side} like {request.market.market_id}, as of {at.isoformat()}."]
    if problem is not None:
        lines.append(f"Refused: {problem}.")
    lines += [_route_line(r) for r in routes]
    if not routes:
        lines.append("No equivalent route.")
    stale = sorted({m for c in claims for m in c.stale_candidates})
    if stale:
        lines.append("Not ranked (book stale or of unknown age): " + ", ".join(stale) + ".")
    verified = sorted((r for r in routes if r.market_id in by_kind[ClaimKind.BEST_VERIFIED_TOTAL_COST.value].candidates),
                      key=lambda r: (r.claim_total_cost, _order(r)))
    label = lambda r: f"{_name(r.venue)} ({r.market_id})"  # noqa: E731
    if problem is None and len(verified) >= 2:
        best, rest = verified[0], verified[1:]
        proven = [r for r in rest if proven_cheaper(best, r)]
        exact_ties = [r for r in rest if best.fee_status == r.fee_status == FeeStatus.VERIFIED.value
                      and r.claim_total_cost == best.claim_total_cost]
        unordered = [r for r in rest if r not in proven and r not in exact_ties]
        if proven:
            lines.append(f"On verified total cost, {label(best)} is cheaper than "
                         + ", ".join(label(r) for r in proven) + ".")
        if exact_ties:
            lines.append(f"{label(best)} and " + ", ".join(label(r) for r in exact_ties)
                         + " have equal exact total costs.")
        if unordered:
            lines.append("No proven order between " + label(best) + " and " + ", ".join(label(r) for r in unordered)
                         + ": their cost bounds overlap (" + "; ".join(_cost_range(r) for r in [best, *unordered])
                         + ").")
    elif problem is None and routes:
        lines.append(f"No cheaper-than claim: {len(verified)} of {len(routes)} route(s) have a verified total cost.")
    feasible = by_kind[ClaimKind.BEST_ACCOUNT_FEASIBLE_ROUTE.value]
    if not feasible.supported:
        lines.append(f"No account-feasible route ({feasible.reason}).")
    etas = [f"{_name(r.venue)} {r.capital_release_eta_utc or 'UNKNOWN'}" for r in routes]
    if etas:
        lines.append("Tradable cash release: " + "; ".join(etas) + ".")
    if related:
        lines.append("Related, not equivalent (never compared): " + ", ".join(related) + ".")
    lines.append("Execution is not authorized.")
    return "\n".join(lines)
