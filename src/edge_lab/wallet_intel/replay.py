"""Follower replay and copyability (W5, ADR 0045). Simulation only: nothing is sent anywhere.

**The follower timeline starts at our observation time**, never at the leader's fill time:
`observable_at` (leader time + detection delay, and never before our receipt) + processing delay +
venue arrival delay. A restart (`resume_at`) delays everything queued before it, so an old backlog
ages and the policy quarantines it.

**Fills come only from a provided book** at our arrival time, no older than `max_book_age`:
- buys walk captured asks up to the policy's limit price and cash budget; sells walk captured bids;
- missing depth is no fill, never executable size. A truncated side fills only what was captured;
- partial fills stay partial; a fill below the minimum quantity is rejected; quantities round down
  to the step;
- the pluggable fee function never invents a fee: None means UNKNOWN, which blocks net economics;
- a request can fail (retried up to `max_attempts` against a fresh book) or end UNKNOWN. An UNKNOWN
  fill changes no inventory and makes the run's economics UNKNOWN: it is never a win;
- a buy is skipped when the same leader's exit of that token was observable before our order arrived
  (the leader exits while we are entering);
- nothing trades after its market resolves; holdings settle at the final payout.

**Two economics, never merged.** LEADER_OBSERVED_ECONOMICS: the leader's own per-unit outcome for each
followed buy, from its later sells (FIFO) or the payout (gross: leader fees are not reported).
FOLLOWER_SIMULATED_ECONOMICS: our cash, fees, settlements and liquidation value. The difference is
reported per event (the dependence cluster) with a cluster-bootstrap band.

Ladders over size and delay, and the benchmarks (do nothing, matched buy-and-hold, naive frozen
following, a fixed-rule filter), all run through the same engine with the same costs and capital.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Mapping, Sequence

from .events import Action
from .exact import ZERO, Basis, Labeled, add, decimal_text, mul, ratio, sub
from .market_data import Book, BookProvider, take
from .policy import Enrollment, FollowerBook, FollowerPolicy, FollowSignal, IntentKind, PolicyLimits, PolicyMode
from .stats import cluster_bootstrap
from .timeutil import require_aware, utc_text

REPLAY_VERSION = "wallet-follower-replay-v1"

FeeFunction = Callable[[str, tuple[tuple[Decimal, Decimal], ...]], "Decimal | None"]


def unknown_fee(side: str, levels: tuple[tuple[Decimal, Decimal], ...]) -> Decimal | None:
    """The default: no fee is invented."""
    return None


def zero_fee_documented(side: str, levels: tuple[tuple[Decimal, Decimal], ...]) -> Decimal | None:
    """For a market whose fee is documented as zero (an explicit choice, never a default)."""
    return ZERO


class RequestResult(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


def always_ok(signal_id: str, attempt: int) -> RequestResult:
    return RequestResult.OK


@dataclass(frozen=True)
class ReplayConfig:
    detection_delay: timedelta
    processing_delay: timedelta
    arrival_delay: timedelta
    max_book_age: timedelta
    fee_fn: FeeFunction = unknown_fee
    request_outcome: Callable[[str, int], RequestResult] = always_ok
    max_attempts: int = 1
    retry_delay: timedelta = timedelta(seconds=1)
    resume_at: datetime | None = None


@dataclass(frozen=True)
class Resolution:
    instrument_id: str
    payout: Decimal
    resolved_at: datetime


class FillStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    NO_FILL = "NO_FILL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FollowerFill:
    signal_id: str
    leader_key: str
    side: str
    instrument_id: str
    requested: Decimal
    filled: Decimal
    levels: tuple[tuple[Decimal, Decimal], ...]
    gross_cash: Decimal
    fee: Labeled
    status: FillStatus
    reason: str
    decided_at: datetime
    arrived_at: datetime
    attempts: int


@dataclass(frozen=True)
class SignalOutcome:
    signal_id: str
    leader_key: str
    event_id: str
    action: Action
    decision: str  # IntentKind value or an engine skip
    reason: str
    fill: FollowerFill | None


def observable_time(leader_time: datetime, detection_delay: timedelta, receipt_time: datetime | None = None) -> datetime:
    t = leader_time + detection_delay
    return max(t, receipt_time) if receipt_time is not None else t


def with_detection_delay(signals: Sequence[FollowSignal], delay: timedelta) -> tuple[FollowSignal, ...]:
    """The same signals as seen by a channel with `delay` (never earlier than already observed)."""
    return tuple(replace(s, observable_at=max(s.observable_at, s.leader_time + delay)) for s in signals)


@dataclass
class _Run:
    book: FollowerBook
    outcomes: list[SignalOutcome] = field(default_factory=list)
    fills: list[FollowerFill] = field(default_factory=list)
    realized_by_event: dict[str, Decimal] = field(default_factory=dict)
    fees_unknown_events: set[str] = field(default_factory=set)
    bought: dict[str, tuple[Decimal, str]] = field(default_factory=dict)  # signal -> (qty, event)
    settlements: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)
    unknown_fills: int = 0


@dataclass(frozen=True)
class FollowerEconomics:
    label: str
    initial_cash: Decimal
    final_cash: Decimal
    open_value: Labeled
    gross_pnl: Labeled
    net_pnl: Labeled
    fees: Labeled
    unknown_fills: int
    decisions: dict[str, int]
    fill_statuses: dict[str, int]

    def to_dict(self) -> dict:
        return {"label": self.label, "initial_cash": decimal_text(self.initial_cash),
                "final_cash": decimal_text(self.final_cash), "open_value": self.open_value.to_dict(),
                "gross_pnl": self.gross_pnl.to_dict(), "net_pnl": self.net_pnl.to_dict(), "fees": self.fees.to_dict(),
                "unknown_fills": self.unknown_fills, "decisions": dict(sorted(self.decisions.items())),
                "fill_statuses": dict(sorted(self.fill_statuses.items()))}


@dataclass(frozen=True)
class LeaderEconomics:
    label: str
    per_unit: dict[str, Labeled]  # buy signal id -> leader's per-unit outcome (gross)
    scaled_to_follower: Labeled  # sum over followed buys of follower qty x leader per-unit outcome

    def to_dict(self) -> dict:
        return {"label": self.label, "per_unit": {k: v.to_dict() for k, v in sorted(self.per_unit.items())},
                "scaled_to_follower": self.scaled_to_follower.to_dict()}


@dataclass(frozen=True)
class ReplayResult:
    outcomes: tuple[SignalOutcome, ...]
    fills: tuple[FollowerFill, ...]
    follower: FollowerEconomics
    leader: LeaderEconomics
    difference_by_event: dict[str, Labeled]
    difference_band: tuple[float, float, float] | None  # cluster bootstrap over events (mean, lo, hi)
    reconciliation: dict[str, bool]
    final_book: FollowerBook


def _book_ok(book: Book | None, at: datetime, max_age: timedelta) -> str | None:
    if book is None:
        return "MISSING_BOOK"
    if book.captured_at > at:
        return "BOOK_FROM_THE_FUTURE"
    if at - book.captured_at > max_age:
        return "STALE_BOOK"
    return None


def replay(signals: Sequence[FollowSignal], policy: FollowerPolicy, *, initial_cash: Decimal, books: BookProvider,
           resolutions: Mapping[str, Resolution], config: ReplayConfig, horizon: datetime) -> ReplayResult:
    require_aware(horizon, "horizon")
    run = _Run(FollowerBook(initial_cash))
    seen: set[str] = set()
    lim = policy.limits

    def decision_time(s: FollowSignal) -> datetime:
        t = s.observable_at + config.processing_delay
        return max(t, config.resume_at) if config.resume_at is not None else t

    timeline: list[tuple[datetime, int, str, object]] = []
    for s in signals:
        timeline.append((decision_time(s), 1, s.signal_id, s))
    for token, res in resolutions.items():
        require_aware(res.resolved_at, "resolved_at")
        if res.resolved_at <= horizon:
            timeline.append((res.resolved_at, 0, token, res))
    timeline.sort(key=lambda x: (x[0], x[1], x[2]))
    exits = [s for s in signals if s.action is Action.TRADE_SELL]

    for at, _, _, item in timeline:
        if at > horizon:
            break
        if isinstance(item, Resolution):
            for leader, (qty, cost) in run.book.settle(item.instrument_id, item.payout).items():
                event = run.book.token_event.get(item.instrument_id, "?")
                run.realized_by_event[event] = add(run.realized_by_event.get(event, ZERO),
                                                   sub(mul(qty, item.payout), cost))
                run.settlements.append((item.instrument_id, qty, item.payout))
            continue
        s = item
        assert isinstance(s, FollowSignal)

        def record(decision: str, reason: str, fill: FollowerFill | None = None) -> None:
            run.outcomes.append(SignalOutcome(s.signal_id, s.leader_key, s.event_id, s.action, decision, reason, fill))

        if s.signal_id in seen:
            record("SKIP", "DUPLICATE_SIGNAL: a replayed signal is never entered twice")
            continue
        seen.add(s.signal_id)
        res = resolutions.get(s.instrument_id)
        if res is not None and res.resolved_at <= at:
            record("SKIP", "MARKET_RESOLVED")
            continue
        intent = policy.decide(s, run.book, now=at)
        if intent.kind not in (IntentKind.BUY, IntentKind.SELL):
            record(intent.kind.value, intent.reason)
            continue
        arrived = at + config.arrival_delay
        if intent.kind is IntentKind.BUY and any(
                e.leader_key == s.leader_key and e.instrument_id == s.instrument_id and e.leader_time > s.leader_time
                and e.observable_at <= arrived for e in exits):
            record("SKIP", "LEADER_EXITED_BEFORE_ENTRY")
            continue
        fill = _execute(s, intent.kind, intent.quantity, intent.limit_price, intent.max_cash, run, books, config,
                        lim, at, arrived)
        record(intent.kind.value, intent.reason, fill)

    return _finish(signals, run, initial_cash, books, resolutions, config, horizon)


def _execute(s: FollowSignal, kind: IntentKind, qty: Decimal | None, limit: Decimal | None, max_cash: Decimal | None,
             run: _Run, books: BookProvider, config: ReplayConfig, lim: PolicyLimits, decided: datetime,
             arrived: datetime) -> FollowerFill:
    assert qty is not None
    side = "BUY" if kind is IntentKind.BUY else "SELL"

    def result(status: FillStatus, reason: str, attempts: int, at: datetime,  # type: ignore[no-untyped-def]
               levels=(), fee=None) -> FollowerFill:
        filled = add(*(sz for _, sz in levels))
        cash = add(*(mul(p, sz) for p, sz in levels))
        fee_l = Labeled.unknown("fee function returned UNKNOWN") if fee is None else Labeled(fee, Basis.ESTIMATED,
                                                                                              "fee model")
        f = FollowerFill(s.signal_id, s.leader_key, side, s.instrument_id, qty, filled, tuple(levels), cash, fee_l,
                         status, reason, decided, at, attempts)
        run.fills.append(f)
        return f

    at = arrived
    for attempt in range(1, config.max_attempts + 1):
        outcome = config.request_outcome(s.signal_id, attempt)
        if outcome is RequestResult.UNKNOWN:
            run.unknown_fills += 1
            return result(FillStatus.UNKNOWN, "REQUEST_OUTCOME_UNKNOWN: inventory unchanged, economics UNKNOWN",
                          attempt, at)
        if outcome is RequestResult.FAILED:
            if attempt == config.max_attempts:
                return result(FillStatus.FAILED, "REQUEST_FAILED", attempt, at)
            at = at + config.retry_delay
            continue
        book = books(s.instrument_id, at)
        problem = _book_ok(book, at, config.max_book_age)
        if problem:
            return result(FillStatus.NO_FILL, problem, attempt, at)
        assert book is not None
        if kind is IntentKind.BUY:
            if not book.asks:
                return result(FillStatus.NO_FILL, "MISSING_DEPTH: no asks", attempt, at)
            t = take(book.asks, quantity=qty, limit=limit, buying=True, max_cash=max_cash, step=lim.quantity_step,
                     truncated=book.asks_truncated)
        else:
            if not book.bids:
                return result(FillStatus.NO_FILL, "MISSING_DEPTH: no bids", attempt, at)
            t = take(book.bids, quantity=qty, limit=None, buying=False, max_cash=None, step=lim.quantity_step,
                     truncated=book.bids_truncated)
        if t.quantity <= 0:
            return result(FillStatus.NO_FILL, "NO_DEPTH_WITHIN_LIMIT", attempt, at)
        if kind is IntentKind.BUY and t.quantity < lim.min_quantity:
            return result(FillStatus.NO_FILL, "BELOW_MINIMUM_QUANTITY after depth", attempt, at)
        levels = tuple((lv.price, lv.size) for lv in t.levels)
        fee = config.fee_fn(side, levels)
        event = s.event_id
        if kind is IntentKind.BUY:
            if fee is not None and add(t.cash, fee) > run.book.cash:
                return result(FillStatus.NO_FILL, "INSUFFICIENT_CASH_FOR_FEE", attempt, at)
            run.book.record_buy(s, levels, fee)
            run.bought[s.signal_id] = (t.quantity, event)
            if fee is not None:
                run.realized_by_event[event] = sub(run.realized_by_event.get(event, ZERO), fee)
            else:
                run.fees_unknown_events.add(event)
        else:
            cost = run.book.record_sell(s.instrument_id, s.leader_key, levels, fee)
            pnl = sub(t.cash, cost)
            if fee is not None:
                pnl = sub(pnl, fee)
            else:
                run.fees_unknown_events.add(event)
            run.realized_by_event[event] = add(run.realized_by_event.get(event, ZERO), pnl)
        status = FillStatus.FILLED if t.quantity == qty else FillStatus.PARTIAL
        reason = "filled" if status is FillStatus.FILLED else (
            "PARTIAL: captured depth exhausted, deeper levels unknown" if t.beyond_capture_unknown
            else "PARTIAL: depth, limit or cash bound")
        return result(status, reason, attempt, at, levels, fee)
    raise AssertionError("unreachable")  # pragma: no cover


def _leader_per_unit(signals: Sequence[FollowSignal], resolutions: Mapping[str, Resolution],
                     horizon: datetime) -> dict[str, Labeled]:
    """The leader's own gross per-unit outcome for each buy signal: FIFO against its later sells, then
    the payout for any remainder resolved by the horizon. UNKNOWN if any part is unresolved.

    Only leader trades at or before the horizon count: a sale after the horizon is outside the evaluation
    window, so a position still open at the horizon stays UNKNOWN (unless resolved by then)."""
    queues: dict[tuple[str, str], list[list]] = {}
    totals: dict[str, Decimal] = {}
    qtys: dict[str, Decimal] = {}
    for s in sorted(signals, key=lambda x: (x.leader_time, x.signal_id)):
        if s.leader_time > horizon:
            continue
        key = (s.leader_key, s.instrument_id)
        if s.action is Action.TRADE_BUY:
            queues.setdefault(key, []).append([s.signal_id, s.leader_quantity, s.leader_price])
            totals[s.signal_id] = ZERO
            qtys[s.signal_id] = s.leader_quantity
            continue
        remaining = s.leader_quantity
        for lot in queues.get(key, []):
            if remaining <= 0:
                break
            used = min(remaining, lot[1])
            if used <= 0:
                continue
            totals[lot[0]] = add(totals[lot[0]], mul(used, sub(s.leader_price, lot[2])))
            lot[1] = sub(lot[1], used)
            remaining = sub(remaining, used)
    out: dict[str, Labeled] = {}
    for (leader, token), lots in queues.items():
        res = resolutions.get(token)
        for sid, left, price in lots:
            total = totals[sid]
            if left > 0:
                if res is None or res.resolved_at > horizon:
                    out[sid] = Labeled.unknown("leader still holds part of this buy at the horizon")
                    continue
                total = add(total, mul(left, sub(res.payout, price)))
            r = ratio(total, qtys[sid])
            out[sid] = Labeled(r, Basis.OBSERVED, "leader gross per unit") if r is not None else Labeled.unknown("")
    return out


def _finish(signals: Sequence[FollowSignal], run: _Run, initial_cash: Decimal, books: BookProvider,
            resolutions: Mapping[str, Resolution], config: ReplayConfig, horizon: datetime) -> ReplayResult:
    book = run.book
    # Open holdings at the horizon: liquidation value from captured bids only.
    open_values: list[Labeled] = []
    for token, qty in sorted(book.inventory.items()):
        if qty == 0:
            continue
        b = books(token, horizon)
        if _book_ok(b, horizon, config.max_book_age) or b is None:
            open_values.append(Labeled.unknown(f"{token}: no fresh book at the horizon"))
            continue
        t = take(b.bids, quantity=qty, limit=None, buying=False, max_cash=None, step=Decimal("1e-18"),
                 truncated=b.bids_truncated)
        open_values.append(Labeled(t.cash, Basis.ESTIMATED, "liquidation at captured bids") if t.quantity == qty
                           else Labeled.unknown(f"{token}: captured bids do not cover the holding"))
    open_value = Labeled(ZERO, Basis.OBSERVED) if not open_values else (
        Labeled.unknown("an open holding has no executable value") if any(not v.known for v in open_values)
        else Labeled(add(*(v.value for v in open_values if v.value is not None)), Basis.ESTIMATED))
    fees_known = book.fees_unknown == 0
    unknown = run.unknown_fills > 0
    # Gross P&L: cash change plus fees paid plus open value. Fees unknown were never deducted from cash.
    gross = Labeled.unknown("an UNKNOWN fill: economics are UNKNOWN, never a win") if unknown else (
        Labeled.unknown("open holdings have no executable value") if not open_value.known else
        Labeled(add(sub(book.cash, initial_cash), book.fees_paid, open_value.value or ZERO),
                Basis.ESTIMATED, "simulated, gross of fees"))
    net = Labeled.unknown("fees UNKNOWN: net economics blocked") if not fees_known else (
        Labeled(sub(gross.value, book.fees_paid), Basis.ESTIMATED, "simulated, net of modelled fees")
        if gross.known and gross.value is not None else Labeled.unknown(gross.note))
    decisions: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for o in run.outcomes:
        decisions[o.decision] = decisions.get(o.decision, 0) + 1
        if o.fill is not None:
            statuses[o.fill.status.value] = statuses.get(o.fill.status.value, 0) + 1
    follower = FollowerEconomics("FOLLOWER_SIMULATED_ECONOMICS", initial_cash, book.cash, open_value, gross, net,
                                 Labeled(book.fees_paid, Basis.ESTIMATED) if fees_known else Labeled.unknown(
                                     "fee function returned UNKNOWN"), run.unknown_fills, decisions, statuses)

    per_unit = _leader_per_unit(signals, resolutions, horizon)
    scaled: dict[str, Decimal] = {}
    scaled_known = True
    leader_unknown_events: set[str] = set()
    for sid, (qty, event) in run.bought.items():
        pu = per_unit.get(sid)
        if pu is None or pu.value is None:
            scaled_known = False
            leader_unknown_events.add(event)
            continue
        scaled[event] = add(scaled.get(event, ZERO), mul(qty, pu.value))
    leader = LeaderEconomics("LEADER_OBSERVED_ECONOMICS", per_unit,
                             Labeled(add(*scaled.values()), Basis.ESTIMATED, "leader per-unit x follower quantity")
                             if scaled_known else Labeled.unknown("a followed buy's leader outcome is unresolved"))

    # Per-event difference: only events whose follower lots are all closed and fees known.
    open_events = {book.token_event.get(t) for t, q in book.inventory.items() if q != 0}
    diff: dict[str, Labeled] = {}
    for event in sorted({e for _, e in run.bought.values()}):
        if unknown:
            diff[event] = Labeled.unknown("an UNKNOWN fill in the run")
        elif event in open_events:
            diff[event] = Labeled.unknown("follower lots still open at the horizon")
        elif event in run.fees_unknown_events:
            diff[event] = Labeled.unknown("fees UNKNOWN for this event")
        elif event not in scaled or event in leader_unknown_events:
            diff[event] = Labeled.unknown("leader outcome unresolved")
        else:
            diff[event] = Labeled(sub(run.realized_by_event.get(event, ZERO), scaled[event]), Basis.ESTIMATED,
                                  "follower net - leader-scaled gross")
    band = cluster_bootstrap({k: float(v.value) for k, v in diff.items() if v.value is not None})

    reconciliation = _reconcile(run, initial_cash)
    return ReplayResult(tuple(run.outcomes), tuple(run.fills), follower, leader, diff, band, reconciliation, book)


def _reconcile(run: _Run, initial_cash: Decimal) -> dict[str, bool]:
    """Terminal wealth reconciles exactly: initial cash + every fill's cash flow + settlements = cash."""
    flows = ZERO
    for f in run.fills:
        if f.status not in (FillStatus.FILLED, FillStatus.PARTIAL):
            continue
        fee = f.fee.value or ZERO
        flows = add(flows, sub(ZERO, add(f.gross_cash, fee)) if f.side == "BUY" else sub(f.gross_cash, fee))
    settled = add(*(mul(q, p) for _, q, p in run.settlements))
    book = run.book
    bought = {}
    for f in run.fills:
        if f.status in (FillStatus.FILLED, FillStatus.PARTIAL):
            sign = 1 if f.side == "BUY" else -1
            bought[f.instrument_id] = add(bought.get(f.instrument_id, ZERO), f.filled if sign > 0 else -f.filled)
    for token, qty, _ in run.settlements:
        bought[token] = sub(bought.get(token, ZERO), qty)
    inventory_ok = all(bought.get(t, ZERO) == q for t, q in book.inventory.items()) and all(
        book.inventory.get(t, ZERO) == q for t, q in bought.items())
    try:
        book.check_invariants()
        invariants = True
    except AssertionError:
        invariants = False
    return {"cash_reconciles": add(initial_cash, flows, settled) == book.cash, "inventory_reconciles": inventory_ok,
            "attribution_sums_to_inventory": invariants}


# --- Ladders and benchmarks ------------------------------------------------------------------------

@dataclass(frozen=True)
class LadderRow:
    risk_per_signal: Decimal
    detection_delay: timedelta
    follower_gross: Labeled
    follower_net: Labeled
    leader_scaled: Labeled
    filled: int
    unknown_fills: int

    def to_dict(self) -> dict:
        return {"risk_per_signal": decimal_text(self.risk_per_signal),
                "detection_delay_s": int(self.detection_delay.total_seconds()),
                "follower_gross": self.follower_gross.to_dict(), "follower_net": self.follower_net.to_dict(),
                "leader_scaled": self.leader_scaled.to_dict(), "filled": self.filled,
                "unknown_fills": self.unknown_fills}


def ladder(signals: Sequence[FollowSignal], limits: PolicyLimits, enrollments: Mapping[str, Enrollment], *,
           sizes: Sequence[Decimal], delays: Sequence[timedelta], initial_cash: Decimal, books: BookProvider,
           resolutions: Mapping[str, Resolution], config: ReplayConfig, horizon: datetime) -> tuple[LadderRow, ...]:
    rows = []
    for size in sizes:
        for delay in delays:
            pol = FollowerPolicy(replace(limits, risk_per_signal=size), enrollments=enrollments)
            r = replay(with_detection_delay(signals, delay), pol, initial_cash=initial_cash, books=books,
                       resolutions=resolutions, config=replace(config, detection_delay=delay), horizon=horizon)
            rows.append(LadderRow(size, delay, r.follower.gross_pnl, r.follower.net_pnl, r.leader.scaled_to_follower,
                                  r.follower.fill_statuses.get("FILLED", 0) + r.follower.fill_statuses.get("PARTIAL", 0),
                                  r.follower.unknown_fills))
    return tuple(rows)


def benchmarks(signals: Sequence[FollowSignal], limits: PolicyLimits, enrollments: Mapping[str, Enrollment], *,
               initial_cash: Decimal, books: BookProvider, resolutions: Mapping[str, Resolution], config: ReplayConfig,
               horizon: datetime) -> dict[str, FollowerEconomics]:
    """Matched capital, universe, horizon and costs for every arm."""
    start = min((s.leader_time for s in signals), default=horizon)
    frozen = {k: replace(e, enrolled_at=min(e.enrolled_at, start)) for k, e in enrollments.items()}
    arms = {
        "MATCHED_BUY_AND_HOLD": FollowerPolicy(replace(limits, mirror_exits=False), enrollments=enrollments),
        "NAIVE_FROZEN_FOLLOWING": FollowerPolicy(replace(limits, min_leader_notional=ZERO,
                                                         min_price=Decimal("0.001"), max_price=Decimal("0.999")),
                                                 enrollments=frozen),
        "FIXED_RULE_FILTER": FollowerPolicy(limits, enrollments=enrollments, mode=PolicyMode.FIXED_RISK_PER_SIGNAL),
    }
    out = {"DO_NOTHING": FollowerEconomics("FOLLOWER_SIMULATED_ECONOMICS", initial_cash, initial_cash,
                                           Labeled(ZERO, Basis.OBSERVED), Labeled(ZERO, Basis.OBSERVED),
                                           Labeled(ZERO, Basis.OBSERVED), Labeled(ZERO, Basis.OBSERVED), 0, {}, {})}
    for name, pol in arms.items():
        out[name] = replay(signals, pol, initial_cash=initial_cash, books=books, resolutions=resolutions,
                           config=config, horizon=horizon).follower
    return out


def describe_times(signal: FollowSignal, config: ReplayConfig) -> dict[str, str]:
    decided = signal.observable_at + config.processing_delay
    return {"leader_time": utc_text(signal.leader_time), "observable_at": utc_text(signal.observable_at),
            "decided_at": utc_text(decided), "arrives_at": utc_text(decided + config.arrival_delay)}
