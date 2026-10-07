"""Follower policy and ownership attribution (W6, ADR 0045). Research only: no order is ever sent.

**Typed boundary.** `FollowerPolicy.decide` accepts only a `FollowSignal`, built deterministically
from a directional leader observation. There is no free-text field anywhere on the path, and the
limits are a frozen `PolicyLimits` fixed at construction. Model output, profile text or any other
string cannot reach a limit, a grant or a secret (there are none here to reach).

**Two ledgers, kept apart.**
- `FollowerBook.inventory` and `cash` are the authoritative (simulated) account.
- `FollowerBook.attribution` is the virtual attribution of that inventory to leaders. Every token's
  attributions sum exactly to its inventory (`check_invariants`, run after every change). Two leaders
  signalling the same token each own only what was bought on their own signal.

**Ownership rules.**
- A leader's sale reduces only that leader's attributable holding, scaled by the fraction of its own
  position the leader sold. With the leader's prior position unknown, nothing is sold automatically:
  the holding is kept and flagged (a monitoring gap is not a liquidation).
- A missed entry followed by a leader exit sells nothing, so no short can arise. Sales never exceed
  attributable inventory, and attributable inventory never exceeds the account's.
- Cash is spent once. Leaders cannot reuse each other's cash or inventory.
- No automatic catch-up: a leader position that predates enrollment is never bought. Catch-up would be
  a new decision at today's price and needs its own specification, so `catch_up=True` is refused.

**Caps.** Per leader, per heuristic cluster, per event, per strategy and in total, on the gross cost
of open lots. Opposing positions in one event both count towards the event cap: they are not netted
as a hedge.

**Modes.**
- FIXED_RISK_PER_SIGNAL (the transparent baseline): a fixed cash budget per entry signal, within caps.
- TARGET_EXPOSURE: hold a fixed budget while the leader holds the token, none once it is flat.
- PROPORTIONAL_TO_LEADER_EQUITY: BLOCKED whenever the leader's equity is UNKNOWN, which for public
  wallets is almost always.

**Leader states.** ACTIVE; SILENT (no new entries; holdings kept); MONITORING_GAP (history incomplete:
no new entries, exits still mirrored, holdings never liquidated for the gap); PAUSED (no action).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping

from ..provenance import canonical_json, sha256_hex
from .events import DIRECTIONAL, Action, WalletObservation
from .exact import ZERO, Labeled, add, decimal_text, div_floor, exact_decimal, mul, sub
from .timeutil import require_aware

POLICY_VERSION = "wallet-follower-policy-v1"
_ID = re.compile(r"[A-Za-z0-9:|._/#?-]{1,256}")


class NotFollowable(ValueError):
    """A non-directional or unknown action: it is never a buy or a sell signal."""


@dataclass(frozen=True)
class FollowSignal:
    signal_id: str
    leader_key: str
    cluster_key: str
    strategy: str
    instrument_id: str
    market_id: str
    event_id: str
    action: Action
    leader_quantity: Decimal
    leader_price: Decimal
    leader_time: datetime
    observable_at: datetime  # when our channel could first report it, never the leader's fill time
    leader_position_before: Decimal | None  # None: unknown

    def __post_init__(self) -> None:
        for name in ("signal_id", "leader_key", "cluster_key", "strategy", "instrument_id", "market_id", "event_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise TypeError(f"{name} must be an identifier, not free text")
        if not isinstance(self.action, Action) or self.action not in DIRECTIONAL:
            raise NotFollowable(f"{self.action} is not a directional trade")
        object.__setattr__(self, "leader_quantity", exact_decimal(self.leader_quantity, name="leader_quantity"))
        object.__setattr__(self, "leader_price", exact_decimal(self.leader_price, name="leader_price"))
        if self.leader_position_before is not None:
            object.__setattr__(self, "leader_position_before",
                               exact_decimal(self.leader_position_before, name="leader_position_before"))
        require_aware(self.leader_time, "leader_time")
        require_aware(self.observable_at, "observable_at")
        if self.observable_at < self.leader_time:
            raise ValueError("a signal cannot be observable before the leader acted")
        if self.leader_quantity <= 0 or not (ZERO < self.leader_price < Decimal(1)):
            raise ValueError("leader quantity must be positive and price inside (0, 1)")


def signal_from_observation(obs: WalletObservation, *, observable_at: datetime, cluster_key: str, strategy: str,
                            leader_position_before: Decimal | None) -> FollowSignal:
    if not obs.directional:
        raise NotFollowable(f"{obs.action.value} is not followed as a directional trade")
    if obs.price is None or obs.native_quantity is None or obs.instrument_id is None:
        raise NotFollowable("the trade lacks a price, quantity or instrument")
    return FollowSignal(obs.observation_id, obs.account.key, cluster_key, strategy, obs.instrument_id,
                        obs.market_id or "?", obs.event_id or obs.market_id or "?", obs.action,
                        obs.native_quantity, obs.price, obs.source_time, observable_at, leader_position_before)


class PolicyMode(str, Enum):
    FIXED_RISK_PER_SIGNAL = "FIXED_RISK_PER_SIGNAL"
    TARGET_EXPOSURE = "TARGET_EXPOSURE"
    PROPORTIONAL_TO_LEADER_EQUITY = "PROPORTIONAL_TO_LEADER_EQUITY"


class LeaderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SILENT = "SILENT"
    MONITORING_GAP = "MONITORING_GAP"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class PolicyLimits:
    risk_per_signal: Decimal
    per_leader: Decimal
    per_cluster: Decimal
    per_event: Decimal
    per_strategy: Decimal
    total: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    min_leader_notional: Decimal  # smaller leader trades are bait-sized and ignored
    max_signal_age: timedelta  # older at processing time: quarantined (expired backlog)
    min_price: Decimal
    max_price: Decimal
    max_price_above_leader: Decimal  # our buy limit = leader price + this, capped at max_price
    mirror_exits: bool = True
    catch_up: bool = False

    def __post_init__(self) -> None:
        for f in ("risk_per_signal", "per_leader", "per_cluster", "per_event", "per_strategy", "total",
                  "quantity_step", "min_quantity", "min_leader_notional", "min_price", "max_price",
                  "max_price_above_leader"):
            object.__setattr__(self, f, exact_decimal(getattr(self, f), name=f))
        if self.catch_up:
            raise ValueError("automatic catch-up is off: it is a new decision at today's price and needs its own "
                             "specification")
        if self.quantity_step <= 0 or not (ZERO < self.min_price <= self.max_price < Decimal(1)):
            raise ValueError("invalid step or price bounds")

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json({k: (decimal_text(v) if isinstance(v, Decimal) else str(v))
                                          for k, v in asdict(self).items()}))


class IntentKind(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SKIP = "SKIP"
    QUARANTINE = "QUARANTINE"
    BLOCKED = "BLOCKED"
    HOLD_FLAGGED = "HOLD_FLAGGED"


@dataclass(frozen=True)
class Intent:
    signal_id: str
    leader_key: str
    kind: IntentKind
    instrument_id: str
    quantity: Decimal | None
    limit_price: Decimal | None
    max_cash: Decimal | None
    reason: str


@dataclass(frozen=True)
class Lot:
    quantity: Decimal
    price: Decimal  # exact level price; fees are tracked separately


@dataclass
class FollowerBook:
    """Authoritative simulated inventory and cash, plus virtual attribution to leaders."""

    cash: Decimal
    inventory: dict[str, Decimal] = field(default_factory=dict)
    attribution: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    lots: dict[tuple[str, str], list[Lot]] = field(default_factory=dict)  # (token, leader) -> FIFO lots
    meta: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # leader -> (cluster, strategy, "")
    token_event: dict[str, str] = field(default_factory=dict)
    token_strategy: dict[tuple[str, str], str] = field(default_factory=dict)
    fees_paid: Decimal = ZERO
    fees_unknown: int = 0

    def __post_init__(self) -> None:
        self.cash = exact_decimal(self.cash, name="cash")
        if self.cash < 0:
            raise ValueError("cash must not be negative")

    def attributable(self, token: str, leader: str) -> Decimal:
        return self.attribution.get(token, {}).get(leader, ZERO)

    def exposure(self, *, leader: str | None = None, cluster: str | None = None, event: str | None = None,
                 strategy: str | None = None) -> Decimal:
        out = ZERO
        for (token, ldr), lots in self.lots.items():
            if leader is not None and ldr != leader:
                continue
            if cluster is not None and self.meta.get(ldr, ("", "", ""))[0] != cluster:
                continue
            if event is not None and self.token_event.get(token) != event:
                continue
            if strategy is not None and self.token_strategy.get((token, ldr)) != strategy:
                continue
            out = add(out, *(mul(lot.quantity, lot.price) for lot in lots))
        return out

    def record_buy(self, signal: FollowSignal, levels: tuple[tuple[Decimal, Decimal], ...], fee: Decimal | None) -> None:
        qty = add(*(s for _, s in levels))
        cash = add(*(mul(p, s) for p, s in levels))
        spend = add(cash, fee) if fee is not None else cash
        if spend > self.cash:
            raise ValueError("a fill cannot spend cash the account does not have")
        self.cash = sub(self.cash, spend)
        if fee is None:
            self.fees_unknown += 1
        else:
            self.fees_paid = add(self.fees_paid, fee)
        token, leader = signal.instrument_id, signal.leader_key
        self.inventory[token] = add(self.inventory.get(token, ZERO), qty)
        self.attribution.setdefault(token, {})[leader] = add(self.attributable(token, leader), qty)
        self.lots.setdefault((token, leader), []).extend(Lot(s, p) for p, s in levels)
        self.meta[leader] = (signal.cluster_key, signal.strategy, "")
        self.token_event[token] = signal.event_id
        self.token_strategy[(token, leader)] = signal.strategy
        self.check_invariants()

    def record_sell(self, token: str, leader: str, levels: tuple[tuple[Decimal, Decimal], ...],
                    fee: Decimal | None) -> Decimal:
        """Sell attributable inventory; returns the gross cost of the lots consumed (FIFO)."""
        qty = add(*(s for _, s in levels))
        if qty > self.attributable(token, leader):
            raise ValueError("a sale cannot exceed the leader's attributable inventory (no short, no reuse)")
        proceeds = add(*(mul(p, s) for p, s in levels))
        self.cash = add(self.cash, proceeds)
        if fee is None:
            self.fees_unknown += 1
        else:
            self.cash = sub(self.cash, fee)
            self.fees_paid = add(self.fees_paid, fee)
        self.inventory[token] = sub(self.inventory[token], qty)
        self.attribution[token][leader] = sub(self.attribution[token][leader], qty)
        consumed = self._consume(token, leader, qty)
        self.check_invariants()
        return consumed

    def settle(self, token: str, payout: Decimal) -> dict[str, tuple[Decimal, Decimal]]:
        """Pay every holder of `token` at its final payout. Returns leader -> (quantity, lot cost)."""
        out = {}
        for leader, qty in sorted(self.attribution.get(token, {}).items()):
            if qty == 0:
                continue
            cost = self._consume(token, leader, qty)
            self.cash = add(self.cash, mul(qty, payout))
            self.attribution[token][leader] = ZERO
            out[leader] = (qty, cost)
        if token in self.inventory:
            self.inventory[token] = ZERO
        self.check_invariants()
        return out

    def _consume(self, token: str, leader: str, qty: Decimal) -> Decimal:
        lots = self.lots.get((token, leader), [])
        remaining, cost = qty, ZERO
        while remaining > 0:
            lot = lots[0]
            used = min(remaining, lot.quantity)
            cost = add(cost, mul(used, lot.price))
            remaining = sub(remaining, used)
            if used == lot.quantity:
                lots.pop(0)
            else:
                lots[0] = Lot(sub(lot.quantity, used), lot.price)
        return cost

    def check_invariants(self) -> None:
        if self.cash < 0:
            raise AssertionError("negative cash")
        for token, qty in self.inventory.items():
            if qty < 0:
                raise AssertionError(f"negative inventory in {token}")
            attributed = add(*self.attribution.get(token, {}).values())
            if attributed != qty:
                raise AssertionError(f"attributions {attributed} != inventory {qty} for {token}")
            if any(v < 0 for v in self.attribution.get(token, {}).values()):
                raise AssertionError("negative attribution")
            lot_qty = add(*(lot.quantity for (t, _), lots in self.lots.items() if t == token for lot in lots))
            if lot_qty != qty:
                raise AssertionError(f"lots {lot_qty} != inventory {qty} for {token}")


@dataclass(frozen=True)
class Enrollment:
    leader_key: str
    enrolled_at: datetime
    status: LeaderStatus = LeaderStatus.ACTIVE


class FollowerPolicy:
    def __init__(self, limits: PolicyLimits, *, mode: PolicyMode = PolicyMode.FIXED_RISK_PER_SIGNAL,
                 enrollments: Mapping[str, Enrollment], leader_equity: Mapping[str, Labeled] | None = None) -> None:
        if not isinstance(limits, PolicyLimits) or not isinstance(mode, PolicyMode):
            raise TypeError("limits and mode must be typed")
        self._limits = limits
        self._mode = mode
        self._enrollments = dict(enrollments)
        self._equity = dict(leader_equity or {})

    @property
    def limits(self) -> PolicyLimits:
        return self._limits

    @property
    def mode(self) -> PolicyMode:
        return self._mode

    def decide(self, signal: FollowSignal, book: FollowerBook, *, now: datetime) -> Intent:
        if not isinstance(signal, FollowSignal):
            raise TypeError("the policy accepts only a typed FollowSignal, never text or a mapping")
        require_aware(now, "now")
        lim = self._limits

        def out(kind: IntentKind, reason: str, qty: Decimal | None = None, limit: Decimal | None = None,
                cash: Decimal | None = None) -> Intent:
            return Intent(signal.signal_id, signal.leader_key, kind, signal.instrument_id, qty, limit, cash, reason)

        if now < signal.observable_at:
            raise ValueError("a decision cannot precede the signal's observation (hindsight)")
        if now - signal.observable_at > lim.max_signal_age:
            return out(IntentKind.QUARANTINE, "EXPIRED_BACKLOG: older than max_signal_age at processing")
        enrollment = self._enrollments.get(signal.leader_key)
        if enrollment is None:
            return out(IntentKind.SKIP, "LEADER_NOT_ENROLLED")
        if signal.leader_time < enrollment.enrolled_at:
            return out(IntentKind.SKIP, "PRE_ENROLLMENT: no automatic catch-up")
        status = enrollment.status
        if status is LeaderStatus.PAUSED:
            return out(IntentKind.SKIP, "COPYING_PAUSED: holdings kept")
        if signal.action is Action.TRADE_SELL:
            return self._exit(signal, book, out)
        if status in (LeaderStatus.SILENT, LeaderStatus.MONITORING_GAP):
            return out(IntentKind.SKIP, f"{status.value}: no new entries; holdings kept")
        notional = mul(signal.leader_quantity, signal.leader_price)
        if notional < lim.min_leader_notional:
            return out(IntentKind.SKIP, "TINY_SIGNAL: below the minimum leader notional")
        if not (lim.min_price <= signal.leader_price <= lim.max_price):
            return out(IntentKind.SKIP, "PRICE_OUT_OF_BOUNDS")
        if self._mode is PolicyMode.PROPORTIONAL_TO_LEADER_EQUITY:
            equity = self._equity.get(signal.leader_key)
            if equity is None or not equity.known or equity.value is None or equity.value <= 0:
                return out(IntentKind.BLOCKED, "LEADER_EQUITY_UNKNOWN: proportional sizing is blocked")
            # The leader's share of its equity, applied to our total cap; never above the fixed budget.
            budget = min(lim.risk_per_signal, div_floor(mul(notional, lim.total), equity.value, Decimal("0.000001")))
        elif self._mode is PolicyMode.TARGET_EXPOSURE:
            if book.attributable(signal.instrument_id, signal.leader_key) > 0:
                return out(IntentKind.SKIP, "TARGET_ALREADY_HELD")
            budget = lim.risk_per_signal
        else:
            budget = lim.risk_per_signal
        headroom = min(
            sub(lim.per_leader, book.exposure(leader=signal.leader_key)),
            sub(lim.per_cluster, book.exposure(cluster=signal.cluster_key)),
            sub(lim.per_event, book.exposure(event=signal.event_id)),
            sub(lim.per_strategy, book.exposure(strategy=signal.strategy)),
            sub(lim.total, book.exposure()),
            book.cash,
        )
        budget = min(budget, headroom)
        if budget <= 0:
            return out(IntentKind.SKIP, "CAP_OR_CASH_EXHAUSTED")
        limit = min(add(signal.leader_price, lim.max_price_above_leader), lim.max_price)
        qty = div_floor(budget, limit, lim.quantity_step)
        if qty < lim.min_quantity or qty <= 0:
            return out(IntentKind.SKIP, "BELOW_MINIMUM_QUANTITY")
        return out(IntentKind.BUY, f"{self._mode.value} entry", qty, limit, budget)

    def _exit(self, signal: FollowSignal, book: FollowerBook, out) -> Intent:  # type: ignore[no-untyped-def]
        lim = self._limits
        held = book.attributable(signal.instrument_id, signal.leader_key)
        if held <= 0:
            return out(IntentKind.SKIP, "NO_ATTRIBUTABLE_INVENTORY: nothing to sell, never a short")
        if not lim.mirror_exits:
            return out(IntentKind.SKIP, "EXITS_NOT_MIRRORED: held to settlement")
        before = signal.leader_position_before
        if before is None or before <= 0:
            return out(IntentKind.HOLD_FLAGGED, "LEADER_FRACTION_UNKNOWN: held and flagged, not liquidated")
        if signal.leader_quantity >= before:
            qty = held  # the leader is flat in this token: exit everything attributable to it
        elif self._mode is PolicyMode.TARGET_EXPOSURE:
            return out(IntentKind.SKIP, "TARGET_STILL_HELD: the leader still holds the token")
        else:
            qty = div_floor(mul(held, signal.leader_quantity), before, lim.quantity_step)
        qty = min(qty, held)
        if qty <= 0:
            return out(IntentKind.SKIP, "EXIT_BELOW_STEP")
        return out(IntentKind.SELL, "mirror the leader's fractional exit", qty, None, None)
