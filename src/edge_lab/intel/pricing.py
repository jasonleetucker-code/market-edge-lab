"""Deterministic pricing sheet for one owner-confirmed Kalshi link and one forecast (#192, ADR 0049).

`price_link` turns a captured Kalshi market, its captured book and one recorded forecast into
a `PricingSheet`: executable asks, the fee each side would pay, the break-even probability,
cost-inclusive expected value at the point and conservative probabilities, the highest price
the conservative probability can pay, the starter lock-up verdict and one action under the
versioned policy `intel-action-v1`.

What this module guarantees:

- **Deterministic code owns every number.** Prices come from the captured book, fees from
  `fee_schedules`, limits from `opportunity`. A forecast supplies probabilities only.
- **Missing is not zero.** Every unavailable number is None. A side with no fee model has no
  cost, so it has no EV at all, never an EV of 0.
- **Stale is not current.** A book older than `PricingPolicy.max_book_age` at `as_of`, a book
  with no or a future receipt time, a closed market or an anomalous book yields SKIP and no EV.
- **There is no BUY.** The highest action is INVESTIGATE, and an unverified fee schedule is
  never claimable (`fee_claimable` False), whatever the numbers say.
- **The canonical engine is still asked.** `opportunity.evaluate` runs for each side and its
  reasons are surfaced as `canonical_reasons` (RULES_UNRESOLVED is expected for these
  non-weather markets). They do not override the intel action: an owner-confirmed link means
  the owner read the captured rules.

Nothing here fetches, sends, places or simulates an order.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any, Mapping

from .. import starter_policy, venues
from ..conservative import ProbabilityBounds
from ..fee_schedules import FeeScheduleStatus, schedule_for, valid_price, verification_at
from ..freshness import parse_utc
from ..kalshi_quotes import (
    OPEN_STATUSES, ladders_from_orderbook, market_from_kalshi, price_grid_from_kalshi, quotes_from_orderbook,
    timing_from_kalshi,
)
from ..opportunity import (
    Event, ExecutableQuote, ModelEstimate, Policy, PriceGrid, break_even_probability, evaluate,
    max_acceptable_price, walk_ladder,
)
from .contracts import INSUFFICIENT_EVIDENCE_TEXT, Action, ForecastBasis

ACTION_POLICY_ID = "intel-action-v1"
VENUE = "kalshi"
PROTECTED_SERIES = frozenset({"KXHIGHNY", "KXNFLGAME", "KXNHLGAME"})
PROTECTED_PREFIXES = ("KXMVE",)
SIDES = ("YES", "NO")
EV_GRID = Decimal("0.0001")
PROVISIONAL_BASES = frozenset({ForecastBasis.OWNER_JUDGMENT, ForecastBasis.AI_ASSISTED_UNVALIDATED})
_ACTION_RANK = {Action.INVESTIGATE: 0, Action.WATCH: 1, Action.SKIP: 2}


def series_of(ticker: str | None) -> str:
    """A Kalshi ticker's series: the text before the first "-" (upper-cased)."""
    return str(ticker or "").split("-", 1)[0].strip().upper()


def protected_reason(ticker: str) -> str | None:
    """"PROTECTED_SCOPE" when the ticker's series belongs to protected research, else None."""
    series = series_of(ticker)
    if series in PROTECTED_SERIES or any(series.startswith(p) for p in PROTECTED_PREFIXES):
        return "PROTECTED_SCOPE"
    return None


# --------------------------------------------------------------------------- contracts


@dataclass(frozen=True)
class Forecast:
    """One recorded probability that the linked market's YES outcome happens."""

    forecast_id: str
    event_id: str
    outcome_id: str
    point: float | None
    low: float | None
    high: float | None
    basis: ForecastBasis
    calibrated: bool
    recorded_at_utc: str
    abstained: bool = False


@dataclass(frozen=True)
class PricingPolicy:
    """`intel-action-v1` parameters. Versioned by `policy_id`; never tuned in place."""

    policy_id: str = ACTION_POLICY_ID
    quantity: int = 1
    safety_margin: Decimal = Decimal("0.03")
    max_book_age: timedelta = timedelta(minutes=15)
    watch_band: Decimal = Decimal("0.00")  # reserved: not used by intel-action-v1

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        for name in ("safety_margin", "watch_band"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite, non-negative Decimal")
        if not isinstance(self.max_book_age, timedelta) or self.max_book_age <= timedelta(0):
            raise ValueError("max_book_age must be a positive timedelta")


@dataclass(frozen=True)
class SidePricing:
    """Buying `quantity` contracts of one side at its best ask. Every number is None when unavailable.

    `fee_per_contract` is everything paid per contract above the ask (the trade fee and the
    balance's cent alignment), so `ask + fee_per_contract == all_in_cost`. `break_even` is the
    probability at which the buy has zero expected value (equal to `all_in_cost`, payoff 1).
    """

    side: str
    ask: Decimal | None
    bid: Decimal | None
    spread: Decimal | None
    top_size: Decimal | None
    depth_status: str | None
    fee_schedule_id: str
    fee_status: str
    fee_claimable: bool
    fee_per_contract: Decimal | None
    all_in_cost: Decimal | None
    break_even: Decimal | None
    p_point: Decimal | None
    p_conservative: Decimal | None
    ev_point: Decimal | None
    ev_conservative: Decimal | None
    return_on_capital: Decimal | None
    max_loss: Decimal | None
    max_acceptable_price: Decimal | None
    qualifies_on_price: bool | None  # None: no ask or no maximum price to compare
    reasons: tuple[str, ...]
    canonical_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PricingSheet:
    ticker: str
    event_ticker: str
    as_of_utc: str
    quote_received_at_utc: str | None
    quote_age_seconds: float | None
    quote_fresh: bool
    market_status: str | None
    close_time_utc: str | None
    expected_resolution_utc: str | None
    hours_to_close: float | None
    lockup_policy: str
    lockup_reasons: tuple[str, ...]
    yes: SidePricing | None
    no: SidePricing | None
    action: Action
    best_side: str | None
    action_reasons: tuple[str, ...]
    explanation: str
    provisional: bool
    policy_id: str
    series: str = ""
    forecast_id: str | None = None
    quote_evidence_id: str | None = None


# --------------------------------------------------------------------------- helpers


def _unwrap_market(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """The market object: GET /markets/{ticker} wraps it in {"market": {...}}."""
    if not isinstance(raw, Mapping):
        return {}
    inner = raw.get("market")
    return inner if isinstance(inner, Mapping) else raw


def _real(value: Any) -> Decimal | None:
    """A forecast number as an exact Decimal of its shortest repr; None if absent or not a finite real."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        d = Decimal(repr(float(value)))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return d if d.is_finite() else None


def _floor(value: Decimal) -> Decimal:
    return value.quantize(EV_GRID, rounding=ROUND_FLOOR)


def _forecast_problem(forecast: Forecast | None, as_of: datetime) -> str | None:
    if forecast is None:
        return "NO_FORECAST"
    if forecast.abstained:
        return "FORECAST_ABSTAINED"
    if forecast.point is None:
        return "NO_POINT_ESTIMATE"
    try:
        ForecastBasis(forecast.basis)
    except ValueError:
        return "FORECAST_INVALID"
    p, lo, hi = _real(forecast.point), forecast.low, forecast.high
    lo_d = None if lo is None else _real(lo)
    hi_d = None if hi is None else _real(hi)
    if p is None or (lo is not None and lo_d is None) or (hi is not None and hi_d is None):
        return "FORECAST_INVALID"
    for v in (p, lo_d, hi_d):
        if v is not None and not (Decimal(0) <= v <= Decimal(1)):
            return "FORECAST_INVALID"
    if (lo_d is not None and lo_d > p) or (hi_d is not None and hi_d < p):
        return "FORECAST_INVALID"
    recorded = parse_utc(forecast.recorded_at_utc)
    if recorded is None or recorded > as_of:
        return "FORECAST_NOT_POINT_IN_TIME"  # unknown time or recorded after the decision time
    return None


def _bounds(forecast: Forecast) -> tuple[ProbabilityBounds, Decimal, Decimal, Decimal, bool]:
    """The ProbabilityBounds for `evaluate`, plus exact Decimal (point, lower, upper) and
    whether the range was missing (lower/upper then equal the point)."""
    p = _real(forecast.point)
    lo = _real(forecast.low) if forecast.low is not None else None
    hi = _real(forecast.high) if forecast.high is not None else None
    missing = lo is None or hi is None
    lo = p if lo is None else lo
    hi = p if hi is None else hi
    basis = ForecastBasis(forecast.basis)
    bounds = ProbabilityBounds(
        point=float(p), lower=float(lo), upper=float(hi),
        method="owner_range" if basis is ForecastBasis.OWNER_JUDGMENT else "analysis_range",
        n_effective=0, confidence=0.0, standard_error=0.0)
    return bounds, p, lo, hi, missing


def side_probabilities(point: Decimal, lower: Decimal, upper: Decimal, side: str) -> tuple[Decimal, Decimal]:
    """(point, conservative) P(side pays), exactly as `ProbabilityBounds.for_side` but in Decimal:
    YES (p, lower); NO (1 - p, 1 - upper)."""
    if side == "YES":
        return point, lower
    if side == "NO":
        return Decimal(1) - point, Decimal(1) - upper
    raise ValueError(f"unknown side {side!r}")


def _fmt(value: Decimal, unit: str) -> str:
    text = format((value * 100).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}{unit}"


def cents(value: Decimal) -> str:
    """0.38 -> "38¢"; 0.385 -> "38.5¢"."""
    return _fmt(value, "¢")


def percent(value: Decimal) -> str:
    """0.47 -> "47%"."""
    return _fmt(value, "%")


# --------------------------------------------------------------------------- one side


def _canonical(market: Mapping[str, Any], side: str, quote: ExecutableQuote | None, forecast: Forecast | None,
               bounds: ProbabilityBounds | None, schedule: Any, policy: PricingPolicy,
               as_of: datetime) -> tuple[str, ...]:
    """`opportunity.evaluate`'s reasons for this side, or EVALUATE_UNAVAILABLE if its inputs cannot be built."""
    try:
        event_ticker = str(market.get("event_ticker") or "")
        event_id = f"intel:{VENUE}:{event_ticker}"
        mk = market_from_kalshi(market, event_id_for_ticker={event_ticker: event_id})
        timing = mk.timing
        target = ((timing.expected_resolution_utc or timing.close_time_utc or "")[:10]) or "unknown"
        event = Event("intel", event_id, target, timing.expected_resolution_utc, event_id,
                      "captured Kalshi rules (owner-confirmed link)")
        estimate = None
        if forecast is not None and bounds is not None:
            estimate = ModelEstimate(
                model_id=f"intel-forecast:{forecast.forecast_id}", version=ForecastBasis(forecast.basis).value,
                event_id=event_id, market_id=mk.market_id, probability=bounds.point, bounds=bounds,
                generated_at_utc=forecast.recorded_at_utc, input_version=forecast.forecast_id,
                input_observed_at_utc=forecast.recorded_at_utc)
        engine_policy = Policy(policy_id=ACTION_POLICY_ID, edge_basis="conservative",
                               min_net_edge=policy.safety_margin, quantity=policy.quantity,
                               max_book_age=policy.max_book_age, max_model_input_age=timedelta(days=3650),
                               fee_verification="flag")
        opp = evaluate(event=event, market=mk, side=side, quote=quote, estimate=estimate, fee_schedule=schedule,
                       policy=engine_policy, as_of=as_of)
        return opp.reasons or (opp.rejection_reason,)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        return ("EVALUATE_UNAVAILABLE",)


def _price_side(*, side: str, quote: ExecutableQuote | None, ladder: Any, anomaly: bool, schedule: Any,
                fee_state: Any, grid: PriceGrid | None, policy: PricingPolicy,
                probs: tuple[Decimal, Decimal] | None, extra_reasons: tuple[str, ...],
                canonical: tuple[str, ...]) -> SidePricing:
    reasons: list[str] = []
    q = policy.quantity
    ask = bid = top_size = spread = depth = None
    if anomaly:
        reasons.append("BOOK_ANOMALY")
    elif quote is not None:
        ask, bid = quote.best_ask, quote.best_bid
        top_size = quote.displayed_size if ask is not None else None  # no offer: size unknown, not 0
        if ask is not None and bid is not None:
            spread = ask - bid
        if ladder is not None:
            # The capture's requested depth is not known here, so running out of levels is
            # DEPTH_UNKNOWN, never a claim that the book is complete.
            depth = walk_ladder(replace(ladder, truncated=True), q, price_grid=grid).status.value

    priceable = False
    if not anomaly and quote is not None:
        if ask is None:
            reasons.append("NO_OFFER")
        elif not valid_price(ask) or (grid is not None and not grid.contains(ask)):
            reasons.append("INVALID_PRICE")
        else:
            priceable = True
            if top_size is None or top_size < q:
                reasons.append("INSUFFICIENT_SIZE")

    unsupported = fee_state.status is FeeScheduleStatus.UNSUPPORTED
    if unsupported:
        reasons.append("FEE_UNSUPPORTED")
    elif not fee_state.claimable:
        reasons.append("FEE_UNVERIFIED")

    all_in = fee_pc = be = max_loss = None
    if priceable and not unsupported:
        be = break_even_probability(schedule, ask, q)
        if be is None:
            reasons.append("FEE_UNSUPPORTED")
        else:
            all_in = be
            fee_pc = all_in - ask
            max_loss = all_in * q

    p_point = p_cons = ev_point = ev_cons = roc = max_price = None
    qualifies = None
    if probs is not None:
        p_point, p_cons = probs
        if not unsupported:
            max_price = max_acceptable_price(p_cons, schedule, quantity=q, margin=policy.safety_margin, grid=grid)
        if all_in is not None:
            ev_point = _floor(p_point - all_in)
            ev_cons = _floor(p_cons - all_in)
            roc = _floor(ev_cons / all_in)
        if ask is not None and priceable and not unsupported:
            qualifies = max_price is not None and ask <= max_price
            if not qualifies:
                reasons.append("ASK_ABOVE_MAX_PRICE")
    reasons.extend(r for r in extra_reasons if r not in reasons)
    return SidePricing(
        side=side, ask=ask, bid=bid, spread=spread, top_size=top_size, depth_status=depth,
        fee_schedule_id=schedule.schedule_id, fee_status=fee_state.status.value, fee_claimable=fee_state.claimable,
        fee_per_contract=fee_pc, all_in_cost=all_in, break_even=be, p_point=p_point, p_conservative=p_cons,
        ev_point=ev_point, ev_conservative=ev_cons, return_on_capital=roc, max_loss=max_loss,
        max_acceptable_price=max_price, qualifies_on_price=qualifies, reasons=tuple(reasons),
        canonical_reasons=tuple(canonical))


def _side_action(s: SidePricing, margin: Decimal) -> Action:
    blocked = {"INSUFFICIENT_SIZE", "INVALID_PRICE", "BOOK_ANOMALY", "FEE_UNSUPPORTED",
               "NO_UNCERTAINTY_RANGE"} & set(s.reasons)
    if (s.ev_conservative is not None and s.ev_conservative > 0 and s.ev_conservative >= margin
            and s.qualifies_on_price is True and not blocked):
        return Action.INVESTIGATE
    if s.ev_point is not None and s.ev_point > 0:
        return Action.WATCH
    return Action.SKIP


# --------------------------------------------------------------------------- explanation


def _explain(action: Action, reasons: tuple[str, ...], best: SidePricing | None, *, series: str,
             market_status: str | None, age: float | None, policy: PricingPolicy, provisional: bool,
             owner: bool, facts: tuple[SidePricing | None, ...]) -> str:
    primary = reasons[0] if reasons else ""
    if primary == "PROTECTED_SCOPE":
        return f"{series or 'This series'} is protected research scope; this lane does not price it."
    if primary == "MARKET_UNIDENTIFIED":
        return "Skipped: the captured market has no ticker, so nothing can be priced."
    if action is Action.INSUFFICIENT_EVIDENCE:
        text = f"No independent probability: {INSUFFICIENT_EVIDENCE_TEXT}."
        shown = [s for s in facts if s is not None and s.ask is not None]
        current = not ({"MARKET_NOT_OPEN", "MARKET_CLOSED_BY_TIME", "CLOSE_TIME_UNKNOWN", "BOOK_STALE",
                        "BOOK_ANOMALY", "BOOK_MISSING"} & set(reasons))
        if shown and not current:
            text += (" No current market price is shown: the market is closed or its book is stale, missing or "
                     "malformed" + (f" ({int(age // 60)} minutes old)" if age is not None else "") + ".")
        elif shown:
            parts = [f"{s.side} is offered at {cents(s.ask)}"
                     + (f" ({cents(s.all_in_cost)} after fees)" if s.all_in_cost is not None else "")
                     for s in shown]
            text += " Market facts only: " + " and ".join(parts) + "."
        return text
    if primary == "MARKET_NOT_OPEN":
        return f"Skipped: the market is not open (status {market_status or 'unknown'}), so no EV is computed."
    if primary == "MARKET_CLOSED_BY_TIME":
        return "Skipped: the market's close time has passed, so no EV is computed."
    if primary == "CLOSE_TIME_UNKNOWN":
        return "Skipped: the market's close time is unknown, so its tradability cannot be confirmed."
    if primary == "BOOK_MISSING":
        return "Skipped: no order book was captured for this market, so there is no executable price."
    if primary == "BOOK_STALE":
        limit = int(policy.max_book_age.total_seconds() // 60)
        if age is None:
            return ("Skipped: the order book's receipt time is missing or after the decision time, "
                    "so its prices cannot be treated as current.")
        return (f"Skipped: the order book is {int(age // 60)} minutes old (limit {limit}), "
                "so its prices are not current and no EV is computed.")
    if primary == "BOOK_ANOMALY":
        return "Skipped: the captured order book is crossed or malformed, so no price from it is used."
    if primary == "FEE_UNSUPPORTED":
        return (f"Skipped: FEE_UNSUPPORTED — no cost-inclusive EV. Series {series} has no supported fee "
                "schedule, so no cost can be stated.")
    if best is None or best.ev_conservative is None or best.ask is None or best.all_in_cost is None:
        return "Skipped: neither side has an executable, fee-priced offer, so no EV can be computed."

    who = "Your" if owner else "The imported"
    no_range = "NO_UNCERTAINTY_RANGE" in best.reasons
    est = "point estimate (no range given)" if no_range else "conservative estimate"
    after = "after costs" if best.fee_claimable else "after estimated (unverified) fees"
    fee = best.fee_per_contract
    first = (f"{best.side} costs {cents(best.ask)} plus a {cents(fee)} fee." if fee else
             f"{best.side} costs {cents(best.ask)} with no fee.")
    pc, be, ev = best.p_conservative, best.break_even, best.ev_conservative
    if ev > 0:
        second = (f"{who} {est} ({percent(pc)}) is above the {cents(be)} break-even, "
                  f"leaving about {cents(ev)} per contract {after}.")
    elif ev == 0:
        second = f"{who} {est} ({percent(pc)}) only equals the {cents(be)} break-even."
    elif best.ev_point is not None and best.ev_point > 0:
        second = (f"Only the point estimate ({percent(best.p_point)}) is above the {cents(be)} break-even; "
                  f"the conservative estimate ({percent(pc)}) would lose about {cents(-ev)} per contract.")
    else:
        second = (f"{who} {est} ({percent(pc)}) is below the {cents(be)} break-even, "
                  f"so it would lose about {cents(-ev)} per contract {after}.")
    caveats = []
    if "ASK_ABOVE_MAX_PRICE" in best.reasons and best.max_acceptable_price is not None:
        caveats.append(f"the ask is above the {cents(best.max_acceptable_price)} maximum acceptable price")
    if best.max_acceptable_price is None and ev > 0:
        caveats.append("no price clears the safety margin, so there is no maximum acceptable price")
    if no_range:
        caveats.append("no uncertainty range was given, so nothing conservative can be computed")
    if "INSUFFICIENT_SIZE" in best.reasons:
        caveats.append(f"fewer than {policy.quantity} contracts are offered at the ask")
    if not best.fee_claimable:
        caveats.append("fees for this series are unverified")
    if provisional:
        caveats.append("the forecast is provisional")
    if caveats:
        third = ", ".join(caveats[:-1]) + (" and " if len(caveats) > 1 else "") + caveats[-1]
        third = third[0].upper() + third[1:] + ", so this is not a claimable edge."
    elif action is Action.INVESTIGATE:
        third = "This is a lead to investigate, not a trade."
    else:
        third = "There is no edge after costs at this price."
    return " ".join((first, second, third))


# --------------------------------------------------------------------------- the sheet


def price_link(
    *,
    market_raw: dict,
    orderbook_raw: dict | None,
    quote_received_at_utc: str | None,
    quote_evidence_id: str | None,
    forecast: Forecast | None,
    as_of_utc: str,
    policy: PricingPolicy = PricingPolicy(),
) -> PricingSheet:
    """Price one owner-confirmed Kalshi link against one forecast at `as_of_utc` (intel-action-v1).

    Precedence: protected scope (SKIP) > no usable forecast (INSUFFICIENT_EVIDENCE, market facts
    still shown) > market not open, book missing, stale or anomalous (SKIP) > both sides without a
    fee model (SKIP FEE_UNSUPPORTED) > the best side's action (INVESTIGATE, WATCH or SKIP NO_EDGE).
    """
    as_of = parse_utc(as_of_utc)
    if as_of is None:
        raise ValueError("as_of_utc must be a timezone-aware ISO-8601 time")
    market = _unwrap_market(market_raw)
    ticker = str(market.get("ticker") or "")
    event_ticker = str(market.get("event_ticker") or "")
    series = series_of(ticker)
    status_raw = market.get("status")
    market_status = None if status_raw in (None, "") else str(status_raw)
    timing = timing_from_kalshi(market)
    close = parse_utc(timing.close_time_utc)
    hours_to_close = None if close is None else round((close - as_of).total_seconds() / 3600, 4)

    received = parse_utc(quote_received_at_utc)
    age = None
    quote_fresh = False
    book_time_problem = None
    if received is None:
        book_time_problem = "BOOK_RECEIPT_TIME_UNKNOWN"
    elif received > as_of:
        book_time_problem = "BOOK_TIMESTAMP_IN_FUTURE"
    else:
        age = (as_of - received).total_seconds()
        quote_fresh = as_of - received <= policy.max_book_age

    def sheet(**kw: Any) -> PricingSheet:
        base = dict(
            ticker=ticker, event_ticker=event_ticker, as_of_utc=as_of.isoformat(),
            quote_received_at_utc=quote_received_at_utc, quote_age_seconds=age, quote_fresh=quote_fresh,
            market_status=market_status, close_time_utc=timing.close_time_utc,
            expected_resolution_utc=timing.expected_resolution_utc, hours_to_close=hours_to_close,
            lockup_policy=starter_policy.POLICY_ID, policy_id=policy.policy_id, series=series,
            forecast_id=None if forecast is None else forecast.forecast_id, quote_evidence_id=quote_evidence_id)
        base.update(kw)
        return PricingSheet(**base)

    # 1. Protected research scope: nothing is priced.
    protected = protected_reason(ticker) or (protected_reason(event_ticker) if event_ticker else None)
    if protected or not ticker:
        reasons = (protected or "MARKET_UNIDENTIFIED",)
        return sheet(lockup_reasons=(), yes=None, no=None, action=Action.SKIP, best_side=None,
                     action_reasons=reasons, provisional=True,
                     explanation=_explain(Action.SKIP, reasons, None, series=series, market_status=market_status,
                                          age=age, policy=policy, provisional=True, owner=False, facts=()))

    # Lock-up overlay (reported; it does not change the intel action).
    verdict = starter_policy.assess(commitment=as_of, timing=timing,
                                    lag=starter_policy.lag_evidence(VENUE, series),
                                    cash=venues.cash_timing(VENUE))

    # 2. Forecast.
    problem = _forecast_problem(forecast, as_of)
    bounds = None
    probs: dict[str, tuple[Decimal, Decimal]] = {}
    range_missing = False
    if problem is None:
        bounds, p, lo, hi, range_missing = _bounds(forecast)
        probs = {side: side_probabilities(p, lo, hi, side) for side in SIDES}
    provisional = (problem is not None or range_missing or not forecast.calibrated
                   or ForecastBasis(forecast.basis) in PROVISIONAL_BASES)

    # 3. Market and book.
    gate: list[str] = []
    if (market_status or "").lower() not in OPEN_STATUSES:
        gate.append("MARKET_NOT_OPEN")
    if close is None:
        gate.append("CLOSE_TIME_UNKNOWN")
    elif close <= as_of:
        gate.append("MARKET_CLOSED_BY_TIME")  # the captured status can lag the venue's own close time
    quotes = quotes_from_orderbook(ticker, orderbook_raw if isinstance(orderbook_raw, Mapping) else None,
                                   received_at_utc=quote_received_at_utc, evidence_id=quote_evidence_id)
    ladders = ladders_from_orderbook(ticker, orderbook_raw if isinstance(orderbook_raw, Mapping) else None,
                                     received_at_utc=quote_received_at_utc, evidence_id=quote_evidence_id,
                                     depth_limit=None)
    anomaly = any(q.anomaly for q in quotes.values())
    if not quotes:
        gate.append("BOOK_MISSING")
    else:
        if not quote_fresh:
            gate.append("BOOK_STALE")
            if book_time_problem:
                gate.append(book_time_problem)
        if anomaly:
            gate.append("BOOK_ANOMALY")

    # 4. Fee schedule (one per series, so one for both sides).
    schedule = schedule_for(VENUE, series or None, as_of=as_of)
    fee_state = verification_at(schedule, as_of, ticker)
    grid = price_grid_from_kalshi(market)

    # EV only from a usable forecast, an open market and a fresh, sound book.
    use_probs = problem is None and not gate
    extra = ("NO_UNCERTAINTY_RANGE",) if (problem is None and range_missing) else ()
    sides: dict[str, SidePricing] = {}
    for side in SIDES:
        quote = quotes.get(side)
        canonical = _canonical(market, side, quote, forecast if problem is None else None, bounds, schedule,
                               policy, as_of)
        sides[side] = _price_side(side=side, quote=quote, ladder=ladders.get(side), anomaly=anomaly,
                                  schedule=schedule, fee_state=fee_state, grid=grid, policy=policy,
                                  probs=probs.get(side) if use_probs else None, extra_reasons=extra,
                                  canonical=canonical)
    yes, no = sides["YES"], sides["NO"]

    def done(action: Action, reasons: list[str], best: SidePricing | None) -> PricingSheet:
        if provisional and problem is None and "PROVISIONAL_FORECAST" not in reasons:
            reasons.append("PROVISIONAL_FORECAST")
        ordered = tuple(dict.fromkeys(reasons))
        owner = forecast is not None and problem is None and ForecastBasis(forecast.basis) is ForecastBasis.OWNER_JUDGMENT
        return sheet(lockup_reasons=verdict.reasons, yes=yes, no=no, action=action,
                     best_side=None if best is None else best.side, action_reasons=ordered,
                     provisional=provisional,
                     explanation=_explain(action, ordered, best, series=series, market_status=market_status,
                                          age=age, policy=policy, provisional=provisional, owner=owner,
                                          facts=(yes, no)))

    unsupported = fee_state.status is FeeScheduleStatus.UNSUPPORTED
    if problem is not None:
        reasons = ["INSUFFICIENT_EVIDENCE", problem] + gate + (["FEE_UNSUPPORTED"] if unsupported else [])
        return done(Action.INSUFFICIENT_EVIDENCE, reasons, None)
    if gate:
        return done(Action.SKIP, gate + (["FEE_UNSUPPORTED"] if unsupported else []), None)
    if unsupported:
        return done(Action.SKIP, ["FEE_UNSUPPORTED"], None)

    # 5-7. Choose the side: best action first, then higher conservative EV, then YES.
    priced = [s for s in (yes, no) if s.ev_conservative is not None]
    if not priced:
        return done(Action.SKIP, ["NO_PRICEABLE_SIDE"] + [r for s in (yes, no) for r in s.reasons], None)
    margin = policy.safety_margin
    best = min(priced, key=lambda s: (_ACTION_RANK[_side_action(s, margin)], -s.ev_conservative,
                                      SIDES.index(s.side)))
    action = _side_action(best, margin)
    head = {Action.INVESTIGATE: "CONSERVATIVE_EDGE", Action.WATCH: "POINT_EDGE_ONLY", Action.SKIP: "NO_EDGE"}[action]
    if action is Action.INVESTIGATE and not best.fee_claimable:
        head = "ESTIMATE_ONLY_FEES_UNVERIFIED"  # never shown as an edge while the fee schedule is unverified
    return done(action, [head] + list(best.reasons), best)
