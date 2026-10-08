"""The supervised execution orchestrator (#160 package K, ADR 0046). Offline: FIXTURE only.

One service runs repeated, bounded cycles through the real components. It installs no timer and starts no thread
or process: the caller runs `run_cycle()` or `run(n)` with an injected clock and sleep. It imports no capability
module: every network request goes through the caller's `send(WireRequest) -> reply` (the reply has `outcome`,
`status` and `body`, as `transport.TransportResult` has), so the transport stays unimported (ADR 0043).

**Start.** The constructor first takes the egress lease (which turns an older fence's in-flight attempts into
OUTCOME_UNKNOWN) and recovers the journal; a start refused because another worker holds a live lease writes nothing.
It then reads the persisted control events and starts only through `control.boot`, persisting `Started` before
anything acts: every start is DISARMED. It never arms itself; only an operator's `request_arm` (judged once by
`control.decide_arm`, and persisted) changes the mode. Finally it quarantines every queued signal whose validity
ended while it was down: a backlog is never replayed as fresh.

**One cycle**, in this order, so that reconciliation and safety always come before new risk. Every anomaly a step
finds is raised as a control incident (which disarms) before the next step runs, so an evidence anomaly found in
step 3 stops new risk in the same cycle:
1. renew the lease; mark this process's leftover in-flight attempts OUTCOME_UNKNOWN; read the whole account
   through `send` (`account.reconcile_account`, a READ in every mode), within the cycle's request budget and
   deadline;
2. record the snapshot (`reservations`), and the venue's realized P&L when the read is COMPLETE;
3. persist `ReconciliationObserved` (in SHADOW or a sending mode, anything but COMPLETE disarms with an incident),
   then apply the venue's evidence to our own orders through the lifecycle reducer: unknown attempts are resolved
   from the order listing (never re-sent), fills and ends are recorded, and BOUND reservations are released only
   against a later, consistent snapshot;
4. drain a bounded number of queued signals, refusing expired ones;
5. run the enabled strategies (typed `Strategy` policies) on their signals and the current account; exits are
   REDUCTION intents through the same chain;
6. arbitrate: reductions first, then the strategies' order, then the intent key; at most one new intent per
   market and `max_intents_per_cycle` in all; an intent key that already has an attempt is never sent again;
7. the risk gate (`account_view` + `project_account` + `evaluate`/`revalidate`), one intent at a time on a fresh
   view, so that no two intents can spend the same capacity (the journal's reservation is the hard check);
8. control: `action_problems`; in BOUNDED_AUTO also `grant_problems` with usage computed from persisted records;
   in HUMAN_CONFIRMATION only an intent with a valid HUMAN `ApprovalGrant` proceeds;
9. `prepare_attempt` (intent, approval, reservation and PENDING_EGRESS attempt in one transaction), then `send`.
   Only a definitive OK or REJECTED is final; anything else is OUTCOME_UNKNOWN, with no retry;
10. the reply is recorded as a receipt and folded through the lifecycle reducer;
11. settlement and attribution records;
12. a health review that raises control incidents (which disarm) for quarantines, a degraded reconciliation, a
   lifecycle quarantine, an exhausted request budget or deadline, and a lost lease.

**Modes.** DISARMED and OBSERVE_ONLY read only. SHADOW runs steps 4-8 and records WOULD_SUBMIT or BLOCKED, sending
nothing. HUMAN_CONFIRMATION and BOUNDED_AUTO send. DEMO is refused (an incident): only FIXTURE is authorized.

**The account-aware shadow** (package M, ADR 0047). SHADOW is the same `_decide` as a real decision up to egress: the
shared pre-egress steps (`_egress_request`: lease, request budget, the exact create request), then what
`prepare_attempt` would check (no live earlier attempt; the reservation authority's own capacity rule,
`ReservationAuthority.decide`). A WOULD_SUBMIT carries a hypothetical reservation (`shadow.hypothetical_reservation`)
that the cycle's later decisions see as held and that nothing persists as a reservation; every SHADOW verdict is
also a `SHADOW_VERDICT` record with the full intent and every input version. A process started with
`identity=READ_ONLY` holds only a `shadow.ReadOnlySender`, arms only OBSERVE_ONLY or SHADOW, holds no grant, cancels
nothing and runs only on a shadow store.

**Bounds** (`CycleBounds`): queued signals, signals drained, proposals and intents per cycle, network requests per
cycle (account reads and sends share one budget) and a deadline per cycle. Every record a cycle writes is bounded
by these. Grant usage is kept as running aggregates (turnover per day, realized P&L per day, equity and peak),
rebuilt from the persisted records at start, so a decision never rescans history. The in-memory dedupe sets are
bounded; the persisted records stay the authority.

**Fencing.** Only the holder of the egress lease writes. If the lease is lost (another worker took it over), this
instance is FENCED OUT: it still reads the account, but it writes nothing to the journal (no snapshot, no control
event, no record, no attempt change) and sends nothing, because its live state is no longer the replay of what is
stored. Every journal write (boot included) re-reads the lease immediately before it (`_record`, `_apply` and `_write`;
a cached flag is never trusted alone); the cycle that finds it lost returns a `fenced_out` report, and every later
`run_cycle` raises `OrchestratorFencedOut` (`run(n)` stops). The read and the write are separate transactions, so a
takeover between them can still let that one write land (ADR 0046 §11); the journal's fence check inside
`prepare_attempt` remains the hard stop for a send.

**Stream recovery** (package J, optional). With a `StreamSource` and `OrchestratorConfig.recovery`, the cycle drains
the stream (bounded) before the read, before proposing (taking `recovery.marks`), at the start of each decision and
once more just before it acts; a COMPLETE read proves or contradicts it (`recovery.prove`). A decision whose market
changed since the marks, is quarantined, or lacks a live subscription is BLOCKED and never sent. A reconnect cancels
nothing.

**Shutdown.** `shutdown()` persists a Disarm (no new risk), leaves resting orders alone unless `cancel_owned=True`
asks to cancel our own resting orders (never anyone else's, and only while this process still holds the egress
lease), and writes a SHUTDOWN record. Everything else is already persisted. There is one operation in flight per
order at most: nothing here amends, and a cancel is sent only for an acknowledged order with no unknown outcome
(the package L requirement on crossing cancel and amend answers).

**FIXTURE assumption.** `account` reports the cash basis as UNKNOWN until ACC-02 is settled, so no order can pass.
`OrchestratorConfig.fixture_cash_basis` lets a FIXTURE caller declare the basis its fixture venue implements; it is
refused for any other environment and recorded in every cycle record.

Nothing here issues an `AutomationGrant`. In BOUNDED_AUTO each order gets a POLICY `ApprovalGrant` bound to its
digest and to the armed grant, single use (its nonce is the intent digest).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from ..execution_ticket import ObligationState, TicketLimits
from ..risk import RiskPolicy
from . import account as acct
from . import control as ctl
from . import conformance
from . import kalshi_wire as w
from . import lifecycle as lc
from . import recovery as rc
from . import risk_gate as gate
from . import shadow as sh
from .journal import (AttemptRefused, AttemptState, ExecutionJournal, JournalError, JournalUnavailable,
                      live_attempt_problem)
from .model import (MAX_DIGITS, AccountScope, Action, ApprovalGrant, ApprovalMethod, Environment, Grid, IntentKind,
                    OrderIntent, Side, TimeInForce, canonical_json, decimal_text, environment_authorized,
                    exact_decimal, parse_utc_text, sha256_text, utc_text)
from .reservations import (AccountSnapshot, AccountView, CashBasis, ReceiptKind, ReservationAuthority,
                           ReservationDecision, ReservationError, ReservationRefused, ReservationView, StaleFence)

VENUE = "kalshi"
SIGNAL_SCHEMA = "edge-lab-orchestrator-signal/1"
CYCLE_SCHEMA = "edge-lab-orchestrator-cycle/1"
POLICY_APPROVAL_TTL = timedelta(minutes=2)  # a POLICY approval outlives its cycle only briefly
SIGNAL_CLOCK_SKEW = timedelta(seconds=5)  # how far a signal's issue time may be ahead of our clock
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")
_INCIDENT_CHARS = re.compile(r"[^A-Za-z0-9:._/-]")
_DAY = timedelta(days=1)
_MICROSECOND = timedelta(microseconds=1)
_ZERO = Decimal(0)
RECENT_MEMORY = 4096  # how many recent dedupe keys each in-memory set keeps (the journal stays the authority)


def _exact_context() -> Context:
    """Exact arithmetic: a result that would need rounding raises. A fresh context per use (no shared state)."""
    return Context(prec=2 * MAX_DIGITS + 10, traps=[InvalidOperation, Inexact, Rounded])


class OrchestratorError(Exception):
    """A refusal of the orchestrator's contract (bad configuration, a stopped service)."""


class OrchestratorStopped(OrchestratorError):
    """`shutdown()` has run: this instance runs no further cycle."""


class OrchestratorFencedOut(OrchestratorError):
    """Another worker holds the egress lease: this instance may read but never write or send."""


class Outcome(str, Enum):
    """What happened to one proposed intent in one cycle."""

    SUBMITTED = "SUBMITTED"  # an attempt was prepared and sent (its venue outcome is in the journal)
    WOULD_SUBMIT = "WOULD_SUBMIT"  # SHADOW: every check passed; nothing was sent
    BLOCKED = "BLOCKED"  # a check refused it (reasons)
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # HUMAN_CONFIRMATION without a valid human approval


class SignalOutcome(str, Enum):
    DELIVERED = "DELIVERED"  # handed to its strategy
    EXPIRED = "EXPIRED"  # its validity ended before it was drained
    NOT_ACTED = "NOT_ACTED"  # drained in a mode that makes no decisions (DISARMED, OBSERVE_ONLY, DEMO)
    QUARANTINED_RESTART = "QUARANTINED_RESTART"  # queued before a restart and expired by the time of the restart


# ---------------------------------------------------------------------------------------------- inputs


class Sender(Protocol):
    """The caller's network capability: one allowlisted request in, one reply out (`outcome`, `status`, `body`)."""

    def __call__(self, request: w.WireRequest) -> Any: ...


class MarketFeed(Protocol):
    """Current market state (status, grid, book, fee identity) for one ticker, or None when it is not known."""

    def market_state(self, ticker: str, now: datetime) -> gate.MarketState | None: ...


@dataclass(frozen=True)
class Signal:
    """One typed, expiring input for one strategy. `fields` are (name, text) pairs the strategy interprets."""

    signal_id: str
    source_id: str
    strategy_id: str
    scope_key: str
    market_ticker: str
    issued_at_utc: str
    expires_at_utc: str
    fields: tuple[tuple[str, str], ...] = ()
    schema: str = SIGNAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SIGNAL_SCHEMA:
            raise ValueError(f"unknown signal schema {self.schema!r}")
        for name in ("signal_id", "source_id", "strategy_id", "market_ticker"):
            if not isinstance(getattr(self, name), str) or not _ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a short identifier, not {getattr(self, name)!r}")
        if not isinstance(self.scope_key, str) or not self.scope_key:
            raise ValueError("scope_key is required")
        if parse_utc_text(self.expires_at_utc) <= parse_utc_text(self.issued_at_utc):
            raise ValueError("a signal must expire after it is issued")
        if not isinstance(self.fields, tuple) or not all(
                isinstance(p, tuple) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in self.fields):
            raise ValueError("fields must be a tuple of (name, text) pairs")
        names = [k for k, _ in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("field names must be unique")
        object.__setattr__(self, "fields", tuple(sorted(self.fields)))

    def get(self, name: str) -> str | None:
        return next((v for k, v in self.fields if k == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {"signal_id": self.signal_id, "source_id": self.source_id, "strategy_id": self.strategy_id,
                "scope_key": self.scope_key, "market_ticker": self.market_ticker, "issued_at_utc": self.issued_at_utc,
                "expires_at_utc": self.expires_at_utc, "fields": [list(p) for p in self.fields],
                "schema": self.schema}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Signal":
        return cls(d["signal_id"], d["source_id"], d["strategy_id"], d["scope_key"], d["market_ticker"],
                   d["issued_at_utc"], d["expires_at_utc"], tuple((str(k), str(v)) for k, v in d["fields"]),
                   d["schema"])


@dataclass(frozen=True)
class Proposal:
    """A strategy's candidate: one intent and the decision evidence the risk gate checks it against."""

    intent: OrderIntent
    evidence: gate.DecisionEvidence


@dataclass(frozen=True)
class StrategyContext:
    """Everything a strategy may look at in one cycle. Positions and sellable quantities are from the snapshot
    just recorded (None: unknown, never empty)."""

    scope: AccountScope
    now: datetime
    cycle: int
    mode: ctl.Mode
    signals: tuple[Signal, ...]
    backlog_signal_ids: frozenset[str]  # signals queued before this process started (judged by their own age)
    positions: Mapping[tuple[str, Side], Decimal] | None
    sellable: Mapping[tuple[str, Side], Decimal | None]  # the canonical inventory rule, per held position
    pending: tuple[ReservationView, ...]  # every held reservation of the scope
    markets: Mapping[str, gate.MarketState | None]


class StreamSource(Protocol):
    """The caller's private stream (a future, separately approved transport; a fixture in tests): up to
    `max_items` stream items (`recovery.StreamItem`) received since the last call, in arrival order."""

    def drain(self, max_items: int) -> tuple: ...


class Strategy(Protocol):
    """A typed policy. It proposes; it never sends, reserves or approves anything."""

    strategy_id: str
    strategy_version: str
    model_hash: str
    policy_hash: str

    def propose(self, context: StrategyContext) -> tuple[Proposal, ...]: ...


@dataclass(frozen=True)
class CycleBounds:
    max_queued_signals: int
    max_signals_per_cycle: int
    max_proposals_per_cycle: int
    max_intents_per_cycle: int
    max_requests_per_cycle: int  # account reads and sends together
    cycle_deadline: timedelta
    max_signal_validity: timedelta

    def __post_init__(self) -> None:
        for name in ("max_queued_signals", "max_signals_per_cycle", "max_proposals_per_cycle",
                     "max_intents_per_cycle", "max_requests_per_cycle"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000:
                raise OrchestratorError(f"{name} must be an int in 1-10000")
        for name in ("cycle_deadline", "max_signal_validity"):
            if not isinstance(getattr(self, name), timedelta) or getattr(self, name) <= timedelta(0):
                raise OrchestratorError(f"{name} must be a positive timedelta")


@dataclass(frozen=True)
class RiskInputs:
    """The risk gate's limits. The defaults are the ship-blocking placeholders: they refuse every order. Real values
    are owner decisions; tests pass explicit test limits."""

    policy: RiskPolicy = gate.PLACEHOLDER_POLICY
    limits: gate.GateLimits = gate.PLACEHOLDER_LIMITS
    ticket_limits: TicketLimits = gate.PLACEHOLDER_TICKET_LIMITS


@dataclass(frozen=True)
class OrchestratorConfig:
    scope: AccountScope  # the account; its subaccount is None (the primary, venue subaccount 0)
    worker_id: str
    bounds: CycleBounds
    lease_ttl: timedelta
    snapshot_max_age: timedelta
    cycle_interval: timedelta  # what `run(n)` sleeps between cycles
    risk: RiskInputs = RiskInputs()
    grants: tuple[ctl.AutomationGrant, ...] = ()  # recorded owner grants; none is issued here
    signal_sources: Mapping[str, frozenset[str]] | None = None  # strategy id -> allowed source ids (None: any)
    page_limit: int = 100
    max_pages: int = 20
    max_resamples: int = 3
    max_data_lag: timedelta = timedelta(minutes=1)
    external_cash_policy: acct.ExternalCashPolicy = acct.ExternalCashPolicy.UNKNOWN_BLOCKS
    fixture_cash_basis: CashBasis | None = None  # FIXTURE only (module docstring)
    max_pending_approvals: int = 100
    recovery: rc.RecoveryConfig | None = None  # set exactly when a StreamSource is given (package J)
    identity: sh.ProcessIdentity = sh.ProcessIdentity.EXECUTOR  # READ_ONLY: the account-aware shadow (package M)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AccountScope) or self.scope.subaccount is not None:
            raise OrchestratorError("scope must be an AccountScope of the primary account (subaccount None)")
        if not environment_authorized(self.scope.environment):
            raise OrchestratorError(f"ENVIRONMENT_NOT_AUTHORIZED: {self.scope.environment.value}")
        if not isinstance(self.worker_id, str) or not _ID.fullmatch(self.worker_id):
            raise OrchestratorError("worker_id must be a short identifier")
        if not isinstance(self.bounds, CycleBounds) or not isinstance(self.risk, RiskInputs):
            raise OrchestratorError("bounds and risk must be typed")
        for name in ("lease_ttl", "snapshot_max_age", "cycle_interval", "max_data_lag"):
            if not isinstance(getattr(self, name), timedelta) or getattr(self, name) <= timedelta(0):
                raise OrchestratorError(f"{name} must be a positive timedelta")
        if not isinstance(self.grants, tuple) or not all(isinstance(g, ctl.AutomationGrant) for g in self.grants):
            raise OrchestratorError("grants must be a tuple of control.AutomationGrant")
        if self.signal_sources is not None:
            if not isinstance(self.signal_sources, Mapping) or not all(
                    isinstance(k, str) and isinstance(v, frozenset) for k, v in self.signal_sources.items()):
                raise OrchestratorError("signal_sources maps a strategy id to a frozenset of source ids")
            object.__setattr__(self, "signal_sources", MappingProxyType(dict(self.signal_sources)))
        if self.recovery is not None and not isinstance(self.recovery, rc.RecoveryConfig):
            raise OrchestratorError("recovery must be a recovery.RecoveryConfig")
        if not isinstance(self.identity, sh.ProcessIdentity):
            raise OrchestratorError("identity must be a shadow.ProcessIdentity")
        read_only = self.identity is sh.ProcessIdentity.READ_ONLY
        if read_only != sh.is_shadow_worker(self.worker_id):
            raise OrchestratorError(f"a READ_ONLY process, and only one, has a worker id starting "
                                    f"{sh.SHADOW_WORKER_PREFIX!r} (its store is a shadow store)")
        if read_only and self.grants:
            raise OrchestratorError("a READ_ONLY process holds no automation grant")
        if not isinstance(self.external_cash_policy, acct.ExternalCashPolicy):
            raise OrchestratorError("external_cash_policy must be an account.ExternalCashPolicy")
        if self.fixture_cash_basis is not None:
            if not isinstance(self.fixture_cash_basis, CashBasis):
                raise OrchestratorError("fixture_cash_basis must be a CashBasis")
            if self.scope.environment is not Environment.FIXTURE:
                raise OrchestratorError("a declared cash basis is a FIXTURE assumption only (ACC-02 is UNKNOWN)")
        for name, low, high in (("page_limit", 1, conformance.PAGE_LIMIT_MAX), ("max_pages", 1, 1000),
                                ("max_resamples", 1, acct.MAX_RESAMPLES), ("max_pending_approvals", 1, 10_000)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise OrchestratorError(f"{name} must be an int in {low}-{high}")


# ---------------------------------------------------------------------------------------------- reports


@dataclass(frozen=True)
class Decision:
    intent_key: str
    intent_digest: str
    strategy_id: str
    market_ticker: str
    kind: IntentKind
    outcome: Outcome
    reasons: tuple[str, ...]
    attempt_id: str | None = None
    attempt_state: str | None = None


@dataclass(frozen=True)
class SignalAdmission:
    accepted: bool
    reason: str | None


@dataclass(frozen=True)
class CycleReport:
    cycle: int
    started_at_utc: str
    mode_at_start: ctl.Mode
    mode_at_end: ctl.Mode
    reconciliation: str  # COMPLETE / PARTIAL / FAILED / NOT_RUN
    snapshot_revision: int | None
    requests_used: int
    signals: Mapping[str, int]  # SignalOutcome -> count (drained this cycle)
    signals_rejected: int  # refused at `submit_signal` since the previous cycle
    proposals: int
    proposals_ignored: int  # over the per-cycle cap, duplicates of an attempted key, or malformed
    decisions: tuple[Decision, ...]
    resolved_unknown: tuple[str, ...]  # attempt ids resolved from the venue listing (never re-sent)
    fills_recorded: int
    released: tuple[str, ...]
    incidents: tuple[str, ...]  # raised this cycle
    records_written: int  # control events and records this cycle (journal rows of every kind are bounded)
    deadline_hit: bool
    fenced_out: bool = False  # the lease was lost: this cycle read only and wrote nothing
    stream: Mapping[str, Any] | None = None  # the stream recovery summary (None: no stream configured)
    shadow_verdicts: tuple[sh.ShadowVerdict, ...] = ()  # SHADOW: every verdict of this cycle (package M)


@dataclass(frozen=True)
class ShutdownReport:
    at_utc: str
    cancels_requested: tuple[str, ...]
    cancel_outcomes: Mapping[str, str]
    resting_left: tuple[str, ...]  # our acknowledged, unended orders left alone (reservation ids)


# ---------------------------------------------------------------------------------------------- helpers


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _incident_id(prefix: str, key: str) -> str:
    text = _INCIDENT_CHARS.sub(".", f"{prefix}:{key}")
    return text[:200]


def _outcome_text(reply: Any) -> str:
    outcome = getattr(reply, "outcome", None)
    return str(getattr(outcome, "value", outcome))


def _body_text(body: Any) -> str | None:
    """A reply body as JSON text, or None when it is absent or not JSON."""
    if not isinstance(body, (bytes, bytearray)):
        return None
    try:
        text = bytes(body).decode("utf-8")
        json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return None
    return text


def request_digest(request: w.WireRequest) -> str:
    """SHA-256 of the exact request (endpoint, path, query, body, shard)."""
    return sha256_text(canonical_json({"endpoint": request.endpoint.name, "path": request.path,
                                       "query": [list(p) for p in request.query],
                                       "body": None if request.body is None else request.body.decode("ascii"),
                                       "exchange_index": request.exchange_index}))


def intent_from_dict(d: Mapping[str, Any]) -> OrderIntent:
    """Rebuild an `OrderIntent` from its `to_dict()` JSON form (the constructor re-validates every field)."""
    scope = d["scope"]
    return OrderIntent(
        intent_key=d["intent_key"], strategy_id=d["strategy_id"], strategy_version=d["strategy_version"],
        scope=AccountScope(Environment(scope["environment"]), scope["account_ref"], scope["subaccount"]),
        market_ticker=d["market_ticker"], kind=IntentKind(d["kind"]), side=Side(d["side"]),
        action=Action(d["action"]), quantity=d["quantity"], limit_price=d["limit_price"],
        time_in_force=TimeInForce(d["time_in_force"]), max_total_cost=d["max_total_cost"],
        expires_at_utc=d["expires_at_utc"], price_grid=Grid(**d["price_grid"]),
        quantity_grid=Grid(**d["quantity_grid"]), profile_version=d["profile_version"],
        risk_policy_version=d["risk_policy_version"], fee_schedule_version=d["fee_schedule_version"],
        reduce_only=d["reduce_only"], post_only=d["post_only"], evidence=tuple(d["evidence"]), schema=d["schema"])


def _own_price(order: w.VenueOrder | w.VenueFill, side: Side) -> Decimal:
    return order.yes_price if side is Side.YES else order.no_price


def _order_record(o: w.VenueOrder) -> dict[str, Any]:
    return {"order_id": o.order_id, "client_order_id": o.client_order_id, "ticker": o.ticker,
            "book_side": o.book_side, "status": o.status, "yes_price": o.yes_price, "fill_count": o.fill_count,
            "remaining_count": o.remaining_count, "initial_count": o.initial_count,
            "last_update_time": None if o.last_update_time is None else utc_text(o.last_update_time)}


def _fill_record(f: w.VenueFill) -> dict[str, Any]:
    return {"fill_id": f.fill_id, "order_id": f.order_id, "count": f.count, "yes_price": f.yes_price,
            "fee_cost": f.fee_cost, "is_taker": f.is_taker,
            "created_time": None if f.created_time is None else utc_text(f.created_time)}


def _ack_status(ack: w.CreateAck, quantity: Decimal) -> str:
    """The order status a create reply implies (it carries counts, not a status): resting while anything remains;
    otherwise executed when fully filled, canceled when not (an IOC or FOK remainder). Provisional (ORD-14)."""
    if ack.remaining_count > 0:
        return lc.VenueStatus.RESTING.value
    return lc.VenueStatus.EXECUTED.value if ack.fill_count == quantity else lc.VenueStatus.CANCELED.value


def _frozen(value: Any) -> Any:
    """A JSON-shaped value made read-only: mappings become MappingProxyType, lists tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(v) for v in value)
    return value


def _thawed(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thawed(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thawed(v) for v in value]
    return value


class _Recent:
    """A bounded, insertion-ordered set of recent keys. Forgetting a key only allows a duplicate record or a repeated
    incident later, never a send: the journal and the control state remain the authority."""

    def __init__(self, cap: int, items: tuple = ()):
        self._cap, self._items = cap, {}
        for item in items:
            self.add(item)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def add(self, key: object) -> None:
        self._items.pop(key, None)
        self._items[key] = None
        while len(self._items) > self._cap:
            self._items.pop(next(iter(self._items)))


class _Budget:
    """The cycle's network request budget, shared by account reads and sends."""

    def __init__(self, limit: int, send: Sender):
        self.limit, self.used, self._send, self.exhausted = limit, 0, send, False

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def send(self, request: w.WireRequest) -> Any:
        if self.used >= self.limit:
            self.exhausted = True
            raise OrchestratorError("REQUEST_BUDGET_EXHAUSTED")
        self.used += 1
        return self._send(request)


@dataclass
class _Cycle:
    """Mutable working state of one cycle (never module- or class-level)."""

    n: int
    start: datetime
    deadline: datetime
    budget: _Budget
    mode_at_start: ctl.Mode
    records: int = 0
    recon: acct.AccountReconciliation | None = None
    status: ctl.Reconciliation = ctl.Reconciliation.NOT_RUN
    snapshot: AccountSnapshot | None = None
    signal_counts: dict = field(default_factory=dict)
    proposals: int = 0
    ignored: int = 0
    decisions: list = field(default_factory=list)
    resolved: list = field(default_factory=list)
    fills: int = 0
    released: list = field(default_factory=list)
    incidents: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)  # (incident id, reason) for the health review
    markets: dict = field(default_factory=dict)
    deadline_hit: bool = False
    control_disarmed_on_recon: bool = False
    detail: str = ""
    read_done: bool = False
    stream_marks: rc.Marks | None = None  # taken when the strategies start proposing
    stream_items: int = 0
    stream_findings: list = field(default_factory=list)
    shadow: bool = False  # the cycle decides in SHADOW mode (package M)
    hypothetical: list = field(default_factory=list)  # (ReservationView, OrderIntent) of this cycle's WOULD_SUBMITs
    shadow_sends: int = 0  # requests this cycle's WOULD_SUBMITs would have sent (they share the request budget)
    verdicts: list = field(default_factory=list)  # shadow.ShadowVerdict


# ---------------------------------------------------------------------------------------------- the service


class Orchestrator:
    """One supervised service for one account scope. See the module docstring."""

    def __init__(self, journal: ExecutionJournal, config: OrchestratorConfig, *, send: Sender, feed: MarketFeed,
                 strategies: tuple[Strategy, ...], clock: Callable[[], datetime],
                 sleep: Callable[[float], None], stream: StreamSource | None = None):
        if not isinstance(journal, ExecutionJournal):
            raise OrchestratorError("journal must be an ExecutionJournal")
        if not isinstance(config, OrchestratorConfig):
            raise OrchestratorError("config must be an OrchestratorConfig")
        if not callable(send) or not callable(clock) or not callable(sleep) or not callable(
                getattr(feed, "market_state", None)):
            raise OrchestratorError("send, clock, sleep and feed.market_state must be callables")
        if not isinstance(strategies, tuple):
            raise OrchestratorError("strategies must be a tuple")
        if (stream is None) != (config.recovery is None) or (
                stream is not None and not callable(getattr(stream, "drain", None))):
            raise OrchestratorError("a stream (with drain) and config.recovery are given together, or neither")
        ids = [s.strategy_id for s in strategies]
        if len(set(ids)) != len(ids) or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
            raise OrchestratorError("strategy ids must be unique short identifiers")
        if isinstance(send, sh.ReadOnlySender):
            raise OrchestratorError("pass the caller's send: a READ_ONLY identity wraps it in its own ReadOnlySender")
        self._read_only = config.identity is sh.ProcessIdentity.READ_ONLY
        if self._read_only:  # the only network capability a read-only process holds refuses every write
            send = sh.ReadOnlySender(send)
        self._journal, self._config, self._send, self._feed = journal, config, send, feed
        self._strategies, self._clock, self._sleep = strategies, clock, sleep
        self._scope = config.scope
        self._stopped = False
        self._approvals: dict[str, ApprovalGrant] = {}
        self._signals_rejected = 0
        self._recorded = _Recent(RECENT_MEMORY)  # decision verdicts recorded once per (key, outcome, why)
        self._fenced_out = False
        self._stream = stream
        self._stream_state = None if stream is None else rc.initial(config.recovery)
        now = self._now()

        # A shadow store and an executor store are never the same store (ADR 0047): checked by reads only, before the
        # lease, so a read-only process never takes (or even contends for) a live executor's egress lease.
        self._check_store_identity(journal, config)
        # The egress lease comes first: a boot refused because another worker holds a live lease (LeaseHeld) has
        # written nothing, so the live worker's control log still replays to its live state. Taking the lease turns
        # an older fence's in-flight attempts into OUTCOME_UNKNOWN, and `recover` lists what is not terminal.
        self._fence: int | None = journal.reservations.acquire_lease(config.worker_id, config.lease_ttl, now)
        recovered = journal.recover(now)

        # Start only through control.boot; Started is persisted (as the lease holder) before anything acts.
        events = journal.control_events(self._scope)
        started, state = ctl.boot(self._scope, events, at_utc=utc_text(now))
        self._write(journal.append_control_event, self._scope, started, now=now)
        self._state = state
        self._raised = _Recent(RECENT_MEMORY, tuple(e.incident_id for e in events if isinstance(e, ctl.IncidentRaised)))

        self._load_records(now)
        quarantined = self._quarantine_backlog(now)
        self._record("BOOT", {"worker_id": config.worker_id, "fence_token": self._fence,
                              "identity": config.identity.value,
                              "grants": sorted(g.digest() for g in config.grants),
                              "non_terminal_attempts": [a.attempt_id for a in recovered],
                              "backlog_quarantined": quarantined, "backlog_kept": [s.signal_id for s in self._queue],
                              "fixture_cash_basis": None if config.fixture_cash_basis is None
                              else config.fixture_cash_basis.value}, now)

    # ------------------------------------------------------------------ persisted state

    @staticmethod
    def _check_store_identity(journal: ExecutionJournal, config: OrchestratorConfig) -> None:
        """Refuse a store of the other identity, by reads only: the lease holder's worker id (store-wide) and this
        scope's BOOT records. A read-only process also refuses a store with any attempt in flight (a shadow store
        never has one: nothing in it can prepare an attempt)."""
        read_only = config.identity is sh.ProcessIdentity.READ_ONLY
        lease = journal.reservations.lease()
        if lease is not None and sh.is_shadow_worker(lease.worker_id) != read_only:
            raise OrchestratorError(f"STORE_IDENTITY_MISMATCH: a {config.identity.value} process does not run on a "
                                    f"store last leased by {'an executor' if read_only else 'a shadow process'}")
        for boot in journal.control_records(config.scope, "BOOT"):
            booted_read_only = boot.body.get("identity") == sh.ProcessIdentity.READ_ONLY.value
            if booted_read_only != read_only:
                raise OrchestratorError("STORE_IDENTITY_MISMATCH: this store was booted by another identity")
        if read_only and journal.non_terminal_attempts():
            raise OrchestratorError("STORE_IDENTITY_MISMATCH: a store with attempts in flight is an executor's")

    def _load_records(self, now: datetime) -> None:
        records = self._journal.control_records(self._scope)
        genesis = next((r.body["account_genesis_utc"] for r in records if r.record_type == "GENESIS"), None)
        if genesis is None:
            genesis = utc_text(now)
            self._write(self._journal.append_control_record, self._scope, "GENESIS", {"account_genesis_utc": genesis},
                        now=now)
        self._genesis = genesis
        self._planned: dict[str, OrderIntent] = {}
        self._attempts_known: dict[str, tuple] = {}  # intent key -> ((attempt id, created), ...) once definitive
        self._turnover: dict[str, Decimal] = {}  # UTC day -> turnover of the attempts created that day
        self._pnl_by_day: dict[str, Decimal] = {}  # UTC day -> realized P&L dated that day
        self._equity, self._peak = _ZERO, _ZERO  # cumulative realized P&L and its peak
        self._pnl_as_of: str | None = None  # the last COMPLETE read the P&L ledger reflects (this process)
        accepted: dict[str, Signal] = {}
        done: set[str] = set()
        self._pnl: dict[str, Decimal] = {}
        self._ledger: list[gate.LedgerEntry] = []
        self._pnl_baseline = False
        self._settled: set[str] = set()
        self._attributed: set[str] = set()
        self._cycle = 0
        self._last_status: str | None = None
        for r in records:
            body = r.body
            if r.record_type == "INTENT_PLANNED":
                intent = intent_from_dict(body["intent"])
                if intent.digest() != body["digest"]:
                    raise OrchestratorError(f"planned intent {intent.intent_key} does not match its digest")
                self._planned[intent.intent_key] = intent
            elif r.record_type == "SIGNAL_ACCEPTED":
                s = Signal.from_dict(body["signal"])
                accepted[s.signal_id] = s
            elif r.record_type == "SIGNAL_OUTCOME":
                done.add(body["signal_id"])
            elif r.record_type == "PNL_OBSERVATION":
                self._apply_pnl_record(body)
            elif r.record_type == "PNL_BASELINE":
                self._pnl_baseline = True
            elif r.record_type == "SETTLEMENT":
                self._settled.add(body["ticker"])
            elif r.record_type == "ATTRIBUTION":
                self._attributed.add(body["attempt_id"])
            elif r.record_type == "CYCLE":
                self._cycle = max(self._cycle, int(body["cycle"]))
                self._last_status = body["reconciliation"]
        # Duplicate detection needs only ids still valid: an expired signal is refused at admission anyway.
        self._signal_ids: dict[str, datetime] = {sid: parse_utc_text(s.expires_at_utc) for sid, s in accepted.items()
                                                 if parse_utc_text(s.expires_at_utc) > now}
        self._queue: list[Signal] = [s for sid, s in accepted.items() if sid not in done]
        self._backlog = frozenset(s.signal_id for s in self._queue)
        for key in self._planned:  # once, at start: later decisions use the cache and the aggregates
            self._learn_attempts(key)

    def _apply_pnl_record(self, body: Mapping[str, Any]) -> None:
        self._pnl[body["ticker"]] = exact_decimal(body["realized_pnl"], name="realized_pnl")
        delta = exact_decimal(body["delta"], name="delta")
        if delta != 0:
            self._ledger.append(gate.LedgerEntry(body["entry_ref"], body["at_utc"], gate.LedgerKind.REALIZED_PNL,
                                                 delta))
            day = parse_utc_text(body["at_utc"]).date().isoformat()
            with localcontext(_exact_context()):
                self._pnl_by_day[day] = self._pnl_by_day.get(day, _ZERO) + delta
                self._equity += delta
                self._peak = max(self._peak, self._equity)

    def _learn_attempts(self, key: str) -> None:
        """Cache the attempts of a planned key (rows never change id or creation time) and add their turnover."""
        if key in self._attempts_known:
            return
        attempts = tuple((a.attempt_id, a.created_at_utc) for a in self._journal.attempts_for(key))
        self._attempts_known[key] = attempts
        intent = self._planned[key]
        with localcontext(_exact_context()):
            for _, created in attempts:
                day = parse_utc_text(created).date().isoformat()
                self._turnover[day] = self._turnover.get(day, _ZERO) + ctl.turnover_increment(intent)

    def _quarantine_backlog(self, now: datetime) -> list[str]:
        out = []
        for s in list(self._queue):
            if parse_utc_text(s.expires_at_utc) <= now:
                self._record("SIGNAL_OUTCOME", {"signal_id": s.signal_id,
                                                "outcome": SignalOutcome.QUARANTINED_RESTART.value, "cycle": None},
                             now)
                self._queue.remove(s)
                out.append(s.signal_id)
        return out

    def _record(self, record_type: str, body: Mapping[str, Any], now: datetime, cycle: _Cycle | None = None) -> None:
        self._check_writer()
        self._journal.append_control_record(self._scope, record_type, body, now=now)
        if cycle is not None:
            cycle.records += 1

    def _apply(self, event: ctl.Event, now: datetime, cycle: _Cycle | None = None) -> None:
        """Persist a control event, then apply it: the live state is always the replay of what is stored."""
        self._check_writer()
        self._journal.append_control_event(self._scope, event, now=now)
        self._state = ctl.reduce(self._state, event)
        if isinstance(event, ctl.IncidentRaised):
            self._raised.add(event.incident_id)
        if cycle is not None:
            cycle.records += 1

    def _now(self) -> datetime:
        at = self._clock()
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise OrchestratorError("the clock must return a timezone-aware datetime")
        return at.astimezone(timezone.utc)

    # ------------------------------------------------------------------ operator surface

    @property
    def state(self) -> ctl.ControlState:
        return self._state

    @property
    def fence_token(self) -> int | None:
        return self._fence

    @property
    def queued_signals(self) -> tuple[Signal, ...]:
        return tuple(self._queue)

    @property
    def fenced_out(self) -> bool:
        return self._fenced_out

    @property
    def stream_state(self) -> rc.RecoveryState | None:
        return self._stream_state

    @property
    def identity(self) -> sh.ProcessIdentity:
        return self._config.identity

    def request_arm(self, request: ctl.ArmRequest) -> ctl.ArmAccepted | ctl.ArmRefused:
        """An operator's arm request, judged once (`control.decide_arm`); the outcome is persisted, then applied."""
        self._check_running()
        if not isinstance(request, ctl.ArmRequest):
            raise OrchestratorError("an ArmRequest is required")
        now = self._now()
        outcome: ctl.ArmAccepted | ctl.ArmRefused
        if self._read_only and request.mode not in sh.READ_ONLY_MODES:
            outcome = ctl.ArmRefused(request.mode, request.operator_ref, (
                f"READ_ONLY_IDENTITY: a read-only process arms only {sorted(x.value for x in sh.READ_ONLY_MODES)}",),
                request.at_utc)
        else:
            outcome = ctl.decide_arm(self._state, request, grants=self._config.grants, now=now)
        self._apply(outcome, now)
        return outcome

    def acknowledge_incident(self, incident_id: str, operator_ref: str) -> None:
        now = self._now()
        self._apply(ctl.IncidentAcknowledged(incident_id, operator_ref, utc_text(now)), now)

    def disarm(self, operator_ref: str, reason: str) -> None:
        now = self._now()
        self._apply(ctl.Disarm(operator_ref, reason, utc_text(now)), now)

    def set_latch(self, scope: ctl.LatchScope, key: str, reason: str) -> None:
        now = self._now()
        self._apply(ctl.SetLatch(scope, key, reason, utc_text(now)), now)

    def clear_latch(self, scope: ctl.LatchScope, key: str, operator_ref: str) -> None:
        now = self._now()
        self._apply(ctl.ClearLatch(scope, key, operator_ref, utc_text(now)), now)

    def submit_approval(self, grant: ApprovalGrant) -> bool:
        """Offer a HUMAN approval for one intent digest (HUMAN_CONFIRMATION). It is checked when used."""
        if not isinstance(grant, ApprovalGrant) or grant.method is not ApprovalMethod.HUMAN:
            return False
        if grant.intent_digest not in self._approvals and len(self._approvals) >= self._config.max_pending_approvals:
            return False
        self._approvals[grant.intent_digest] = grant
        return True

    def submit_signal(self, signal: Signal) -> SignalAdmission:
        """Queue one signal. Refused: a stopped service, another account scope, an unknown strategy or source, a
        duplicate id, a signal from the future, expired or valid for too long, or a full queue."""
        reason = self._signal_problem(signal) or (None if self._lease_held() else "FENCED_OUT")
        if reason is not None:
            self._signals_rejected += 1
            return SignalAdmission(False, reason)
        now = self._now()
        try:
            self._record("SIGNAL_ACCEPTED", {"signal": signal.to_dict()}, now)  # persisted before it is queued
        except OrchestratorFencedOut:
            self._signals_rejected += 1
            return SignalAdmission(False, "FENCED_OUT")
        self._signal_ids[signal.signal_id] = parse_utc_text(signal.expires_at_utc)
        self._queue.append(signal)
        return SignalAdmission(True, None)

    def _signal_problem(self, signal: object) -> str | None:
        if self._stopped:
            return "STOPPED"
        if not isinstance(signal, Signal):
            return "NOT_A_SIGNAL"
        now = self._now()
        for sid in [k for k, expires in self._signal_ids.items() if expires <= now]:
            del self._signal_ids[sid]  # bounded: only ids still valid can be duplicates
        if signal.scope_key != self._scope.key():
            return "OUT_OF_IDENTITY: another account scope"
        if signal.strategy_id not in {s.strategy_id for s in self._strategies}:
            return "OUT_OF_IDENTITY: no such enabled strategy"
        sources = self._config.signal_sources
        if sources is not None and signal.source_id not in sources.get(signal.strategy_id, frozenset()):
            return "OUT_OF_IDENTITY: the source is not registered for this strategy"
        if signal.signal_id in self._signal_ids:
            return "DUPLICATE_SIGNAL"
        issued, expires = parse_utc_text(signal.issued_at_utc), parse_utc_text(signal.expires_at_utc)
        if issued > now + SIGNAL_CLOCK_SKEW:
            return "SIGNAL_FROM_FUTURE"
        if expires <= now:
            return "SIGNAL_EXPIRED"
        if expires - issued > self._config.bounds.max_signal_validity:
            return "SIGNAL_VALIDITY_TOO_LONG"
        if len(self._queue) >= self._config.bounds.max_queued_signals:
            return "QUEUE_FULL"
        return None

    def _check_running(self) -> None:
        if self._stopped:
            raise OrchestratorStopped("this orchestrator has shut down")

    def _write(self, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Every direct journal write goes through here: the lease is re-read immediately before it (ADR 0046 §11)."""
        self._check_writer()
        return operation(*args, **kwargs)

    def _check_writer(self) -> None:
        """Before every write: re-read the lease from the store. The cached flag alone would miss a takeover this
        instance has not yet noticed (a supervisor restart under the same worker id takes a new fence while this
        instance is mid-cycle). Losing the lease fences this instance out for good."""
        if not self._lease_held():
            raise OrchestratorFencedOut("another worker holds the egress lease: this instance writes nothing")

    def _lease_held(self) -> bool:
        """Whether this instance still holds the egress lease (re-read from the store). Losing it fences us out."""
        if self._fenced_out:
            return False
        lease = self._journal.reservations.lease()
        if self._fence is None or lease is None or lease.fence_token != self._fence \
                or lease.worker_id != self._config.worker_id:
            self._fenced_out, self._fence = True, None
        return not self._fenced_out

    # ------------------------------------------------------------------ the cycle

    def run(self, n: int) -> tuple[CycleReport, ...]:
        """`n` cycles, sleeping `cycle_interval` between them through the injected sleep. No timer is installed.
        It stops after the cycle that finds this instance fenced out (that report is the last one returned)."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise OrchestratorError("n must be a non-negative int")
        out = []
        for i in range(n):
            report = self.run_cycle()
            out.append(report)
            if report.fenced_out:
                break  # a fenced-out instance never cycles again (run_cycle would raise)
            if i < n - 1:
                self._sleep(self._config.cycle_interval.total_seconds())
        return tuple(out)

    def run_cycle(self) -> CycleReport:
        """One cycle (module docstring). The cycle that finds the lease lost returns a `fenced_out` report; every
        later call raises `OrchestratorFencedOut`: a fenced-out instance neither writes nor keeps reading."""
        self._check_running()
        if self._fenced_out:
            raise OrchestratorFencedOut("this instance lost the egress lease: it runs no further cycle")
        now = self._now()
        bounds = self._config.bounds
        self._cycle += 1
        cy = _Cycle(self._cycle, now, now + bounds.cycle_deadline, _Budget(bounds.max_requests_per_cycle, self._send),
                    self._state.mode)
        try:
            return self._run_cycle(cy)
        except OrchestratorFencedOut:  # a write found the lease lost mid-cycle: nothing was written from then on
            return self._fenced_cycle(cy)

    def _run_cycle(self, cy: _Cycle) -> CycleReport:
        self._renew_lease(cy)
        if self._fenced_out:
            return self._fenced_cycle(cy)
        self._drain_stream(cy)  # before the read: what arrived so far can be proven by it
        self._settle_own_in_flight(cy)
        self._reconcile(cy)
        if not self._lease_held():
            return self._fenced_cycle(cy)
        self._prove_stream(cy)
        self._apply(ctl.ReconciliationObserved(cy.status, utc_text(self._now()), cy.detail), self._now(), cy)
        self._apply_venue_evidence(cy)
        self._safety_review(cy)  # every anomaly so far is an incident (a disarm) before any decision
        delivered = self._drain_signals(cy)
        mode = self._state.mode
        if mode is ctl.Mode.DEMO:
            cy.anomalies.append((_incident_id("demo-refused", f"c{cy.n}"),
                                 "DEMO is not an authorized environment for this orchestrator"))
            self._raise_pending(cy)
        elif mode in (ctl.Mode.SHADOW, ctl.Mode.HUMAN_CONFIRMATION, ctl.Mode.BOUNDED_AUTO):
            cy.shadow = mode is ctl.Mode.SHADOW
            if self._stream is not None:
                self._drain_stream(cy)
                cy.stream_marks = rc.marks(self._stream_state)  # decisions are judged against these
            selected = self._propose_and_arbitrate(cy, delivered)
            self._raise_pending(cy)
            for proposal, strategy in selected:
                if not self._lease_held():
                    return self._fenced_cycle(cy)
                self._decide(cy, proposal, strategy)
                self._raise_pending(cy)  # a decision-phase anomaly disarms before the next decision
        if not self._lease_held():
            return self._fenced_cycle(cy)
        self._settlement_and_attribution(cy)
        self._health_review(cy)
        report = self._report(cy)
        self._record("CYCLE", self._cycle_body(report), self._now(), cy)
        self._last_status = report.reconciliation
        return replace(report, records_written=cy.records)

    def _fenced_cycle(self, cy: _Cycle) -> CycleReport:
        """A fenced-out cycle: the account may have been read; nothing was or is written."""
        if cy.recon is None and not cy.read_done:
            self._read_account(cy)
        return replace(self._report(cy), records_written=cy.records, fenced_out=True)

    # stream recovery (package J) --------------------------------------

    def _drain_stream(self, cy: _Cycle) -> None:
        """Fold what the stream source has (bounded) into the recovery state. In memory only: nothing is written.
        A failing source, a malformed item or a saturated drain quarantines like a stream anomaly."""
        if self._stream is None:
            return
        limit, now = self._config.recovery.max_items_per_drain, self._now()
        state = self._stream_state
        try:
            items = self._stream.drain(limit)
        except Exception as exc:  # a failing source is a stream problem, never a crash of the cycle
            self._stream_state = rc.note_problem(state, rc.Reason.SOURCE_FAILED, at=now,
                                                 detail=f"drain raised {type(exc).__name__}")
            return
        if not isinstance(items, tuple) or len(items) > limit:
            self._stream_state = rc.note_problem(state, rc.Reason.SOURCE_FAILED, at=now,
                                                 detail="drain must return a tuple of at most max_items items")
            return
        for item in items:
            try:
                state = rc.apply(state, item).state
            except ValueError as exc:
                state = rc.note_problem(state, rc.Reason.SOURCE_FAILED, at=now, detail=f"{exc}"[:200])
            cy.stream_items += 1
        if len(items) == limit:  # the source may hold more: what is still queued is unseen
            state = rc.note_problem(state, rc.Reason.BACKLOG, at=now, detail=f"a full drain of {limit} items")
        self._stream_state = state

    def _prove_stream(self, cy: _Cycle) -> None:
        """A COMPLETE reconciliation proves (or contradicts) the stream-dependent state. A REST/stream disagreement
        is an evidence anomaly: an incident (a disarm) before any decision, and the market stays quarantined."""
        if self._stream is None or cy.recon is None or cy.status is not ctl.Reconciliation.COMPLETE:
            return
        proof = rc.prove(self._stream_state, cy.recon, scope=self._scope)
        self._stream_state = proof.state
        for f in proof.findings:
            cy.stream_findings.append([f.kind, f.market_ticker, f.order_id, f.detail])
            if f.kind == rc.Reason.DISAGREEMENT.value:
                cy.anomalies.append((_incident_id("stream-disagreement", f.order_id), f"{f.detail}"[:300]))

    def _stream_problems(self, cy: _Cycle, intent: OrderIntent) -> tuple[str, ...]:
        """Drain, then: may a decision on this market, taken at the cycle's marks, still proceed?"""
        if self._stream is None:
            return ()
        self._drain_stream(cy)
        return rc.decision_problems(self._stream_state, intent.market_ticker, cy.stream_marks)

    # step 1 ---------------------------------------------------------

    def _renew_lease(self, cy: _Cycle) -> None:
        if self._fence is None:
            return
        try:
            self._journal.reservations.renew_lease(self._config.worker_id, self._fence, self._config.lease_ttl,
                                                   cy.start)
        except StaleFence:
            # Another worker took the lease over. This instance is fenced out: it writes nothing (not even an
            # incident, which would land in the live worker's control log and diverge from its state).
            self._fence, self._fenced_out = None, True
        if self._fence is None:
            self._fenced_out = True

    def _settle_own_in_flight(self, cy: _Cycle) -> None:
        """An attempt of THIS fence still PENDING_EGRESS or SENT at a cycle start lost its handling (an exception
        between prepare and record): it is unknown, reserved, and reconciled before anything else. Another fence's
        attempts are never touched here (the journal's lease takeover and `recover` handle superseded fences)."""
        for a in self._journal.non_terminal_attempts():
            if a.state in (AttemptState.PENDING_EGRESS, AttemptState.SENT) and a.fence_token == self._fence:
                self._write(self._journal.mark_outcome_unknown,
                            a.attempt_id, reason="IN_FLIGHT_AT_CYCLE_START", now=cy.start)

    def _read_account(self, cy: _Cycle) -> None:
        """The account read (package G) through `send`, within the cycle's budget and deadline. Writes nothing."""
        cy.read_done = True
        problems = ctl.action_problems(self._state, ctl.ControlAction.READ, venue=VENUE, strategy_id="-",
                                       market_ticker="-", now=cy.start, grants=self._config.grants)
        if problems:
            cy.detail = "; ".join(problems)
        elif cy.budget.remaining < 1:
            cy.detail = "REQUEST_BUDGET_EXHAUSTED before the account read"
            cy.budget.exhausted = True
        else:
            cfg = self._config
            plan = acct.AccountReadPlan(scope=self._scope, subaccounts=(0,), endpoints=frozenset(acct.AccountEndpoint),
                                        page_limit=cfg.page_limit, max_pages=cfg.max_pages,
                                        max_requests=cy.budget.remaining, deadline=cy.deadline,
                                        max_resamples=cfg.max_resamples, max_data_lag=cfg.max_data_lag)
            local = acct.local_orders_from_journal(self._journal, (self._scope,))
            cy.recon = acct.reconcile_account(plan, cy.budget.send, clock=self._now, local_orders=local,
                                              external_cash_policy=cfg.external_cash_policy)
            if any(r.reason and r.reason.startswith(("REQUEST_BUDGET_EXHAUSTED", "DEADLINE_EXCEEDED"))
                   for r in cy.recon.manifest.streams):
                cy.anomalies.append((_incident_id("budget", f"c{cy.n}"),
                                     "the account read ran out of its request budget or deadline"))

    def _reconcile(self, cy: _Cycle) -> None:
        """Read the account, then (as the lease holder) record the snapshot and the P&L. The caller persists the
        `ReconciliationObserved` once the lease is confirmed still held."""
        self._read_account(cy)
        detail = cy.detail
        status = ctl.Reconciliation.FAILED
        if cy.recon is not None and self._lease_held():
            status = ctl.Reconciliation(cy.recon.status.value)
            detail = "; ".join(cy.recon.problems[:3])[:400]
            inputs = cy.recon.snapshot_inputs()[0]
            basis = self._config.fixture_cash_basis
            if basis is not None and inputs.cash_basis is CashBasis.UNKNOWN \
                    and cy.recon.status is acct.ReconciliationStatus.COMPLETE and inputs.cash is not None:
                inputs = replace(inputs, cash_basis=basis)  # the declared FIXTURE assumption fills an UNKNOWN only
            latest = self._journal.reservations.latest_snapshot(self._scope)
            revision = 1 if latest is None else latest.revision + 1
            try:
                cy.snapshot = self._write(inputs.record, self._journal.reservations, revision, now=self._now())
            except ReservationError as exc:
                status, detail = ctl.Reconciliation.FAILED, f"SNAPSHOT_REFUSED: {exc}"[:400]
            if cy.snapshot is not None and not cy.snapshot.consistent and status is ctl.Reconciliation.COMPLETE:
                status, detail = ctl.Reconciliation.PARTIAL, f"SNAPSHOT_INCONSISTENT: {list(cy.snapshot.problems)[:3]}"
            if status is ctl.Reconciliation.COMPLETE:
                self._observe_pnl(cy)
        cy.status, cy.detail = status, detail
        cy.control_disarmed_on_recon = status is not ctl.Reconciliation.COMPLETE and \
            self._state.mode in ctl.RECONCILED_MODES

    def _observe_pnl(self, cy: _Cycle) -> None:
        """The venue's cumulative realized P&L per market (live and historical positions), as ledger deltas. The
        first COMPLETE read is the baseline, dated at the account genesis; later changes are dated when seen."""
        sub = cy.recon.subaccounts[0]
        rows: dict[str, Decimal] = {}
        for p in (sub.historical_positions or ()) + (sub.positions or ()):
            rows[p.ticker] = p.realized_pnl  # the live row wins (ACC-11)
        now, observed = self._now(), cy.snapshot.observed_at_utc
        baseline = not self._pnl_baseline
        for ticker in sorted(rows):
            value = rows[ticker]
            previous = self._pnl.get(ticker, _ZERO)
            if value == previous and ticker in self._pnl:
                continue
            with localcontext(_exact_context()):
                delta = value - previous
            at = self._genesis if baseline else observed
            body = {"ticker": ticker, "realized_pnl": value, "delta": delta, "at_utc": at,
                    "entry_ref": f"pnl:{ticker}:{decimal_text(value)}:{cy.n}", "cycle": cy.n}
            self._record("PNL_OBSERVATION", body, now, cy)
            self._apply_pnl_record(json.loads(canonical_json(body)))
        if baseline:
            self._record("PNL_BASELINE", {"cycle": cy.n, "tickers": sorted(rows)}, now, cy)
            self._pnl_baseline = True
        self._pnl_as_of = observed  # the ledger reflects this COMPLETE read

    # step 3 ---------------------------------------------------------

    def _apply_venue_evidence(self, cy: _Cycle) -> None:
        """Fold the venue's order listing and fills into our own orders: resolve OUTCOME_UNKNOWN attempts (never by
        a resend), record fills and ends, and release BOUND reservations a later snapshot confirms."""
        if cy.recon is None:
            return
        sub = cy.recon.subaccounts[0]
        if sub.orders is None:
            return
        complete = cy.recon.status is acct.ReconciliationStatus.COMPLETE
        # The listing's counts are true somewhere between these two (lifecycle `as_of_upper_utc`, P-3): `as_of`, the
        # earliest, decides disputes and the not-found delay; only a fill stamped after `as_of_upper` adds on top.
        as_of = None if cy.snapshot is None else cy.snapshot.observed_at_utc
        as_of_upper = None if cy.snapshot is None else utc_text(cy.recon.manifest.data_true_by)
        by_client: dict[str, list[w.VenueOrder]] = {}
        for o in sub.orders:
            by_client.setdefault(o.client_order_id, []).append(o)
        by_id = {o.order_id: o for o in sub.orders}
        fills_by_order: dict[str, list[w.VenueFill]] = {}
        for f in sub.fills or ():
            fills_by_order.setdefault(f.order_id, []).append(f)
        auth = self._journal.reservations
        for a in self._journal.non_terminal_attempts():
            if a.state is not AttemptState.OUTCOME_UNKNOWN or a.intent_key not in self._planned \
                    and not self._owns(a.reservation_id):
                continue
            self._resolve_unknown(cy, a, by_client.get(a.client_order_id, []), complete, as_of)
        for r in auth.held_reservations(self._scope):
            attempt = self._journal.attempt(r.reservation_id)
            if attempt.state is not AttemptState.ACKNOWLEDGED or attempt.provider_order_id is None:
                continue
            order = by_id.get(attempt.provider_order_id)
            if order is None:
                if complete:
                    cy.anomalies.append((_incident_id("order-missing", r.reservation_id),
                                         f"acknowledged order {attempt.provider_order_id} is not in a complete listing"))
                continue
            fills = None if sub.fills is None else tuple(fills_by_order.get(order.order_id, ()))
            self._fold_order(cy, r, attempt, order, fills, complete, as_of, as_of_upper, sub)

    def _owns(self, reservation_id: str) -> bool:
        try:
            return self._journal.reservations.reservation(reservation_id).scope_key == self._scope.key()
        except ReservationError:
            return False

    def _view(self, r: ReservationView, prepared_at: str) -> lc.OrderView:
        view = lc.open_view(client_order_id=r.client_order_id, market_ticker=r.market_ticker, side=r.side,
                            action=Action.BUY if r.kind is IntentKind.ENTRY else Action.SELL, quantity=r.quantity,
                            limit_price=r.limit_price)
        return lc.reduce(view, lc.SendPrepared(prepared_at))

    def _resolve_unknown(self, cy: _Cycle, a: Any, matches: list, complete: bool, as_of: str | None) -> None:
        r = self._journal.reservations.reservation(a.reservation_id)
        if len(matches) > 1:
            cy.anomalies.append((_incident_id("venue-duplicate-client-id", a.client_order_id),
                                 f"the venue lists {len(matches)} orders with one client order id"))
            return
        if matches:
            o = matches[0]
            payload = canonical_json({"lookup": "client_order_id", "found": True, "order": _order_record(o)})
            receipt = f"lookup:{a.attempt_id}:{sha256_text(payload)[:16]}"
            try:
                self._write(self._journal.record_receipt, receipt_id=receipt, kind=ReceiptKind.ORDER_LOOKUP,
                            source="account-reconciliation", payload_json=payload,
                            received_at=self._now(), provider_id=o.order_id, attempt_id=a.attempt_id)
                self._write(self._journal.reconcile_attempt,
                            a.attempt_id, AttemptState.ACKNOWLEDGED, receipt_id=receipt,
                            now=self._now(), provider_order_id=o.order_id)
                cy.resolved.append(a.attempt_id)
            except (JournalError, ReservationError) as exc:
                cy.anomalies.append((_incident_id("unknown-unresolved", a.attempt_id), f"{exc}"[:300]))
            return
        if not complete or as_of is None:
            return  # not found in an incomplete listing proves nothing
        view = self._view(r, a.created_at_utc)
        view = lc.reduce(view, lc.SendReturnedAmbiguous(lc.Operation.NEW_ORDER, a.state_reason or "unknown"))
        view = lc.reduce(view, lc.ReconcileObserved(client_order_id=a.client_order_id, provider_order_id=None,
                                                    found=False, authoritative_complete=True, as_of_utc=as_of))
        if view.state.value != "REJECTED":  # too soon after the send (NOT_FOUND_MIN_DELAY): stays unknown
            return
        payload = canonical_json({"lookup": "client_order_id", "found": False, "as_of_utc": as_of,
                                  "client_order_id": a.client_order_id})
        receipt = f"lookup:{a.attempt_id}:{sha256_text(payload)[:16]}"
        try:
            self._write(self._journal.record_receipt, receipt_id=receipt, kind=ReceiptKind.ORDER_LOOKUP,
                        source="account-reconciliation", payload_json=payload,
                        received_at=self._now(), attempt_id=a.attempt_id)
            self._write(self._journal.reconcile_attempt,
                        a.attempt_id, AttemptState.ABSENT, receipt_id=receipt, now=self._now())
            cy.resolved.append(a.attempt_id)
        except (JournalError, ReservationError) as exc:
            cy.anomalies.append((_incident_id("unknown-unresolved", a.attempt_id), f"{exc}"[:300]))

    def _fold_order(self, cy: _Cycle, r: ReservationView, attempt: Any, o: w.VenueOrder,
                    fills: tuple[w.VenueFill, ...] | None, complete: bool, as_of: str | None,
                    as_of_upper: str | None, sub: acct.SubaccountReconciliation) -> None:
        view = self._view(r, attempt.created_at_utc)
        view = lc.reduce(view, lc.ReconcileObserved(
            client_order_id=o.client_order_id, provider_order_id=o.order_id, found=True, status=o.status,
            filled_quantity=o.fill_count, remaining_quantity=o.remaining_count, total_quantity=o.initial_count,
            price=_own_price(o, r.side), authoritative_complete=complete, as_of_utc=as_of,
            as_of_upper_utc=as_of_upper))
        for f in sorted(fills or (), key=lambda x: (x.created_time or datetime.min.replace(tzinfo=timezone.utc),
                                                    x.fill_id)):
            view = lc.reduce(view, lc.Fill(fill_id=f.fill_id, quantity=f.count, price=_own_price(f, r.side),
                                           fee=f.fee_cost, liquidity=lc.Liquidity.TAKER if f.is_taker
                                           else lc.Liquidity.MAKER,
                                           venue_time_utc=None if f.created_time is None else utc_text(f.created_time),
                                           provider_order_id=f.order_id, client_order_id=o.client_order_id))
        if view.quarantined:
            cy.anomalies.append((_incident_id("lifecycle", r.reservation_id),
                                 f"lifecycle quarantine: {'; '.join(view.quarantine_reasons)[:300]}"))
            return
        if r.quarantine_reason is not None:
            return  # a quarantined reservation waits for an explicit resolution (health review raises it)
        auth = self._journal.reservations
        # Everything the view was derived from (with versioned code, `filled_quantity` re-derives from this payload
        # alone): both times of the listing's counts, and the uncertainty the view concluded (ADR 0046 rule 14).
        payload = canonical_json({"order": _order_record(o), "fills": [_fill_record(f) for f in fills or ()],
                                  "filled_quantity": view.filled_quantity, "as_of_utc": as_of,
                                  "as_of_upper_utc": as_of_upper, "authoritative_complete": complete,
                                  "fill_timing_uncertain": view.fill_timing_uncertain,
                                  "fees_complete": view.fees_complete})
        receipt = f"lookup:{r.reservation_id}:{sha256_text(payload)[:16]}"
        try:
            needs_receipt = view.filled_quantity > r.filled_quantity or (
                o.status == lc.VenueStatus.CANCELED.value and r.state is not ObligationState.BOUND) or (
                o.status == lc.VenueStatus.RESTING.value and r.state is ObligationState.UNKNOWN)
            if needs_receipt:
                self._write(self._journal.record_receipt, receipt_id=receipt, kind=ReceiptKind.ORDER_LOOKUP,
                            source="account-reconciliation", payload_json=payload,
                            received_at=self._now(), provider_id=o.order_id,
                            attempt_id=r.reservation_id)
            if view.filled_quantity > r.filled_quantity:
                r = self._write(auth.record_fill,
                                r.reservation_id, view.filled_quantity, self._now(), receipt_id=receipt)
                cy.fills += 1
            if r.quarantine_reason is not None:
                return
            if o.status == lc.VenueStatus.CANCELED.value and r.state is not ObligationState.BOUND:
                r = self._write(auth.confirm_cancel,
                                r.reservation_id, self._now(), receipt_id=receipt, venue_filled=o.fill_count)
            elif o.status == lc.VenueStatus.RESTING.value and r.state is ObligationState.UNKNOWN:
                r = self._write(auth.mark_open, r.reservation_id, self._now(), receipt_id=receipt)
            if r.state is ObligationState.BOUND and r.quarantine_reason is None:
                self._maybe_release(cy, r, o, sub, view)
        except (JournalError, ReservationError) as exc:
            cy.anomalies.append((_incident_id("journal-refused", r.reservation_id), f"{exc}"[:300]))

    def _maybe_release(self, cy: _Cycle, r: ReservationView, o: w.VenueOrder, sub: acct.SubaccountReconciliation,
                       view: lc.OrderView) -> None:
        snap = cy.snapshot
        if snap is None or not snap.consistent or snap.positions is None or o.status == lc.VenueStatus.RESTING.value:
            return
        if cy.recon.status is not acct.ReconciliationStatus.COMPLETE or sub.fills_by_order is None:
            return
        if sub.fills_by_order.get(o.order_id, _ZERO) != r.filled_quantity:
            return  # the position must reflect exactly the fills recorded here
        ended = [t for t in (r.ended_at_utc, r.last_fill_at_utc) if t is not None]
        if not ended or parse_utc_text(snap.observed_at_utc) <= max(parse_utc_text(t) for t in ended):
            return  # a snapshot strictly after the end is needed: the next cycle
        released = self._write(self._journal.reservations.confirm_by_snapshot,
                               r.reservation_id, snap.revision, self._now())
        cy.released.append(released.reservation_id)
        if released.filled_quantity > 0 and released.reservation_id not in self._attributed:
            intent = self._planned.get(released.intent_key)
            fills = view.fills
            with localcontext(_exact_context()):
                notional = sum((f.quantity * f.price for f in fills), _ZERO)
            self._record("ATTRIBUTION", {
                "attempt_id": released.reservation_id, "intent_key": released.intent_key,
                "strategy_id": None if intent is None else intent.strategy_id,
                "market_ticker": released.market_ticker, "side": released.side.value, "kind": released.kind.value,
                "filled_quantity": released.filled_quantity, "fill_ids": sorted(f.fill_id for f in fills),
                "notional": notional, "fees_known": view.fees_known, "fees_complete": view.fees_complete,
                "release_reason": None if released.release_reason is None else released.release_reason.value,
                "cycle": cy.n}, self._now(), cy)
            self._attributed.add(released.reservation_id)

    # step 4 ---------------------------------------------------------

    def _drain_signals(self, cy: _Cycle) -> dict[str, list[Signal]]:
        delivered: dict[str, list[Signal]] = {}
        deciding = self._state.mode in (ctl.Mode.SHADOW, ctl.Mode.HUMAN_CONFIRMATION, ctl.Mode.BOUNDED_AUTO)
        taken = self._queue[:self._config.bounds.max_signals_per_cycle]
        now = self._now()
        for s in taken:
            if parse_utc_text(s.expires_at_utc) <= now:
                outcome = SignalOutcome.EXPIRED
            elif not deciding:
                outcome = SignalOutcome.NOT_ACTED
            else:
                outcome = SignalOutcome.DELIVERED
                delivered.setdefault(s.strategy_id, []).append(s)
            self._record("SIGNAL_OUTCOME", {"signal_id": s.signal_id, "outcome": outcome.value, "cycle": cy.n}, now, cy)
            self._queue.remove(s)
            cy.signal_counts[outcome.value] = cy.signal_counts.get(outcome.value, 0) + 1
        return delivered

    # steps 5-6 ------------------------------------------------------

    def _market(self, cy: _Cycle, ticker: str) -> gate.MarketState | None:
        if ticker not in cy.markets:
            try:
                state = self._feed.market_state(ticker, self._now())
            except Exception:  # a feed failure is an unknown market, never a crash of the cycle
                state = None
            cy.markets[ticker] = state if isinstance(state, gate.MarketState) and state.ticker == ticker else None
        return cy.markets[ticker]

    def _context(self, cy: _Cycle, signals: list[Signal]) -> StrategyContext:
        view = self._journal.reservations.account_view(self._scope)
        snap = view.snapshot
        positions = None if snap is None or snap.positions is None else MappingProxyType(dict(snap.positions))
        sellable: dict[tuple[str, Side], Decimal | None] = {}
        if snap is not None and snap.positions is not None:
            with localcontext(_exact_context()):
                for (ticker, side) in sorted(snap.positions, key=lambda k: (k[0], k[1].value)):
                    available, why = ReservationAuthority.inventory_for(snap, list(view.held), ticker, side)
                    sellable[(ticker, side)] = None if why else available
        tickers = sorted({s.market_ticker for s in signals} | {t for t, _ in (positions or {})}
                         | {r.market_ticker for r in view.held})
        markets = MappingProxyType({t: self._market(cy, t) for t in tickers})
        return StrategyContext(self._scope, self._now(), cy.n, self._state.mode, tuple(signals),
                               frozenset(s.signal_id for s in signals if s.signal_id in self._backlog), positions,
                               MappingProxyType(sellable), view.held, markets)

    def _propose_and_arbitrate(self, cy: _Cycle, delivered: dict[str, list[Signal]]) -> list[tuple[Proposal, Any]]:
        candidates: list[tuple[int, int, str, Proposal, Any]] = []
        cap = self._config.bounds.max_proposals_per_cycle
        for priority, strategy in enumerate(self._strategies):
            try:
                proposals = strategy.propose(self._context(cy, delivered.get(strategy.strategy_id, [])))
            except Exception as exc:  # a failing strategy proposes nothing; the cycle goes on
                cy.anomalies.append((_incident_id("strategy-failed", f"{strategy.strategy_id}:c{cy.n}"),
                                     f"{type(exc).__name__}"))
                continue
            if not isinstance(proposals, tuple):
                cy.ignored += 1
                continue
            for p in proposals:
                cy.proposals += 1
                if len(candidates) >= cap or not self._well_formed(p, strategy):
                    cy.ignored += 1
                    continue
                kind_rank = 0 if p.intent.kind is IntentKind.REDUCTION else 1  # reductions first
                candidates.append((kind_rank, priority, p.intent.intent_key, p, strategy))
        selected: list[tuple[Proposal, Any]] = []
        markets: set[str] = set()
        keys: set[str] = set()
        for _, _, key, p, strategy in sorted(candidates, key=lambda c: (c[0], c[1], c[2])):
            if key in keys or key in self._planned:
                cy.ignored += 1  # one decision per key; an attempted key is never sent again
                continue
            keys.add(key)
            if p.intent.market_ticker in markets:
                self._decision(cy, p.intent, Outcome.BLOCKED,
                               ("ARBITRATION_ONE_INTENT_PER_MARKET: another intent on this market won this cycle",))
                continue
            if len(selected) >= self._config.bounds.max_intents_per_cycle:
                self._decision(cy, p.intent, Outcome.BLOCKED, ("ARBITRATION_CYCLE_CAP: max_intents_per_cycle",))
                continue
            markets.add(p.intent.market_ticker)
            selected.append((p, strategy))
        return selected

    def _well_formed(self, p: object, strategy: Any) -> bool:
        if not isinstance(p, Proposal) or not isinstance(p.intent, OrderIntent) \
                or not isinstance(p.evidence, gate.DecisionEvidence):
            return False
        i = p.intent
        return (i.scope == self._scope and i.strategy_id == strategy.strategy_id
                and i.strategy_version == strategy.strategy_version and p.evidence.evidence_id in i.evidence)

    # steps 7-10 -----------------------------------------------------

    def _decision(self, cy: _Cycle, intent: OrderIntent, outcome: Outcome, reasons: tuple[str, ...],
                  attempt_id: str | None = None, attempt_state: str | None = None, *,
                  reservation: ReservationView | None = None, capacity: ReservationDecision | None = None,
                  request_digest_: str | None = None, inputs: tuple[tuple[str, str | None], ...] = ()) -> None:
        d = Decision(intent.intent_key, intent.digest(), intent.strategy_id, intent.market_ticker, intent.kind,
                     outcome, reasons, attempt_id, attempt_state)
        cy.decisions.append(d)
        verdict = None
        if cy.shadow:  # every SHADOW verdict carries the full intent and what it was concluded from (package M)
            verdict = sh.ShadowVerdict(cy.n, utc_text(self._now()), intent, outcome.value, reasons, reservation,
                                       capacity, request_digest_, inputs + (("verdict_schema", sh.VERDICT_SCHEMA),))
            cy.verdicts.append(verdict)
        once = outcome in (Outcome.AWAITING_APPROVAL, Outcome.WOULD_SUBMIT, Outcome.BLOCKED)
        mark = (intent.intent_key, outcome.value, sha256_text(canonical_json(list(reasons))),
                None if verdict is None else sha256_text(canonical_json([list(x) for x in verdict.inputs])))
        if once and mark in self._recorded:
            return  # the same verdict on the same intent is recorded once, not every cycle
        self._recorded.add(mark)
        self._record("DECISION", {"cycle": cy.n, "mode": self._state.mode.value, "intent_key": intent.intent_key,
                                  "intent_digest": intent.digest(), "strategy_id": intent.strategy_id,
                                  "market_ticker": intent.market_ticker, "kind": intent.kind.value,
                                  "outcome": outcome.value, "reasons": list(reasons), "attempt_id": attempt_id,
                                  "attempt_state": attempt_state}, self._now(), cy)
        if verdict is not None:  # its own record type: never loaded as a planned intent, attempt or reservation
            self._record(sh.SHADOW_RECORD, verdict.to_record(), self._now(), cy)

    def _decide(self, cy: _Cycle, proposal: Proposal, strategy: Any) -> None:
        intent, evidence = proposal.intent, proposal.evidence
        now = self._now()
        if now >= cy.deadline:
            cy.deadline_hit = True
            self._decision(cy, intent, Outcome.BLOCKED, ("CYCLE_DEADLINE: the cycle ran out of time",))
            return
        stream = self._stream_problems(cy, intent)
        if stream:  # invalidated or unproven since the strategies proposed: dropped, never sent
            self._decision(cy, intent, Outcome.BLOCKED, stream)
            return
        mode = self._state.mode
        market = self._market(cy, intent.market_ticker)
        view = self._journal.reservations.account_view(self._scope)
        if cy.hypothetical:  # SHADOW: this cycle's WOULD_SUBMITs hold capacity, as their real reservations would
            view = AccountView(view.scope_key, view.snapshot, view.held + tuple(r for r, _ in cy.hypothetical))
        projection = self._projection(cy, view, intent)
        capacity = self._capacity(cy, view, intent, now) if cy.shadow else None
        action = ctl.ControlAction.NEW_RISK if intent.kind is IntentKind.ENTRY else ctl.ControlAction.REDUCE
        problems = ctl.action_problems(self._state, action, venue=VENUE, strategy_id=intent.strategy_id,
                                       market_ticker=intent.market_ticker, now=now, grants=self._config.grants)
        if mode is ctl.Mode.SHADOW:
            problems = [p for p in problems if not p.startswith("MODE_DOES_NOT_SEND")]
        approval: ApprovalGrant | None = None
        if mode is ctl.Mode.BOUNDED_AUTO:
            grant = next((g for g in self._config.grants if g.digest() == self._state.armed_grant_digest), None)
            if grant is None:
                problems.append("GRANT_MISSING: the armed grant is not recorded")
            else:
                event_key = market.event_key if market is not None and market.event_key else "unknown-event"
                usage = self._usage(cy, grant, view, event_key, now)
                problems += ctl.grant_problems(grant, intent, armed_grant_digest=self._state.armed_grant_digest,
                                               venue=VENUE, event_key=event_key, usage=usage,
                                               model_hash=strategy.model_hash, policy_hash=strategy.policy_hash,
                                               now=now)
                approval = self._policy_approval(intent, grant, now)
                if approval is None:
                    problems.append("POLICY_APPROVAL_EXPIRED: the intent or the grant expires now")
        elif mode is ctl.Mode.HUMAN_CONFIRMATION:
            approval = self._approvals.get(intent.digest())
            if approval is None:
                self._decision(cy, intent, Outcome.AWAITING_APPROVAL, ("NO_HUMAN_APPROVAL",))
                return
        r = self._config.risk
        if approval is not None:
            decision = gate.revalidate(intent, approval, account=projection, market=market, policy=r.policy,
                                       limits=r.limits, ticket_limits=r.ticket_limits, evidence=evidence, now=now)
        else:
            decision = gate.evaluate(intent, account=projection, market=market, policy=r.policy, limits=r.limits,
                                     ticket_limits=r.ticket_limits, evidence=evidence, now=now)
        reasons = tuple(f"{v.code.value}: {v.detail}"[:300] for v in decision.reasons) + tuple(problems)
        inputs = self._verdict_inputs(view, decision, strategy) if cy.shadow else ()
        if reasons:
            self._decision(cy, intent, Outcome.BLOCKED, reasons, capacity=capacity, inputs=inputs)
            return
        stream = self._stream_problems(cy, intent)  # once more, just before acting
        if stream:
            self._decision(cy, intent, Outcome.BLOCKED, stream, capacity=capacity, inputs=inputs)
            return
        if mode is ctl.Mode.SHADOW:
            self._shadow_tail(cy, intent, market, capacity, inputs, now)
            return
        self._prepare_and_send(cy, intent, approval, market)
        self._approvals.pop(intent.digest(), None)  # an approval is single use (the journal refuses its nonce again)

    def _capacity(self, cy: _Cycle, view: AccountView, intent: OrderIntent, now: datetime) -> ReservationDecision:
        """SHADOW: the reservation authority's own capacity rule (`ReservationAuthority.decide`, the code
        `prepare_attempt` reserves with) on the view the gate saw, this cycle's hypothetical reservations included."""
        candidate = f"{sh.SHADOW_PREFIX}{intent.client_order_id()}"
        try:
            return ReservationAuthority.decide(view.snapshot, list(view.held), intent, now,
                                               snapshot_max_age=self._config.snapshot_max_age, candidate_id=candidate)
        except ReservationError as exc:  # inexact arithmetic: refused, as `_reserve` would refuse it
            return ReservationDecision(False, (f"{exc}"[:300],), view.snapshot_revision, None, None, None)

    def _verdict_inputs(self, view: AccountView, decision: gate.GateDecision,
                        strategy: Any) -> tuple[tuple[str, str | None], ...]:
        """The version of every input a SHADOW verdict was concluded from: the gate's own list (intent, policy,
        limits, evidence, market, book, fee schedule and verification, projection, genesis, history digests), the
        snapshot, the control state and the strategy's hashes."""
        snap = view.snapshot
        own = {"snapshot_revision": None if snap is None else str(snap.revision),
               "snapshot_observed_at": None if snap is None else snap.observed_at_utc,
               "control_basis": ctl.state_basis(self._state),
               "ticket_limits": self._ticket_limits_digest(),
               "strategy_model_hash": _text_or_none(getattr(strategy, "model_hash", None)),
               "strategy_policy_hash": _text_or_none(getattr(strategy, "policy_hash", None)),
               "snapshot_max_age_us": str(self._config.snapshot_max_age // _MICROSECOND)}
        merged = dict(decision.inputs)
        merged.update({f"shadow.{k}": v for k, v in own.items()})
        return tuple(sorted(merged.items()))

    def _ticket_limits_digest(self) -> str:
        """A canonical digest of the ticket limits (they carry no id): each field as exact text."""
        tl = self._config.risk.ticket_limits
        body = {f.name: str(getattr(tl, f.name) // _MICROSECOND) if isinstance(getattr(tl, f.name), timedelta)
                else str(getattr(tl, f.name)) for f in fields(tl)}
        return sha256_text(canonical_json(body))

    def _egress_request(self, cy: _Cycle, intent: OrderIntent,
                        market: gate.MarketState) -> tuple[w.WireRequest | None, str | None]:
        """The steps between an allowed decision and `prepare_attempt`, shared by a real send and a SHADOW verdict:
        the egress lease, the cycle's request budget (a SHADOW verdict counts the request it would have sent) and
        the exact create request. (request, None), or (None, why). The lease is judged by the journal's own fence
        rule (`ReservationAuthority.fence_problem`, expiry included), so an expired lease blocks a SHADOW verdict
        exactly where it blocks a send, before anything is planned; `prepare_attempt` re-checks it in its
        transaction."""
        if self._fence is None:
            return None, "NO_EGRESS_LEASE"
        fence = ReservationAuthority.fence_problem(self._journal.reservations.lease(), self._fence, self._now())
        if fence is not None:
            return None, f"NO_EGRESS_LEASE: {fence}"[:300]
        if cy.budget.remaining - cy.shadow_sends < 1:
            cy.budget.exhausted = True
            return None, "REQUEST_BUDGET_EXHAUSTED"
        try:
            profile = conformance.MarketTradingProfile(market.ticker, market.exchange_index, market.price_bands)
            return w.build_create(intent, profile), None
        except ValueError as exc:  # UnsupportedByProfile included
            return None, f"WIRE_REFUSED: {exc}"[:300]

    def _shadow_tail(self, cy: _Cycle, intent: OrderIntent, market: gate.MarketState,
                     capacity: ReservationDecision | None, inputs: tuple, now: datetime) -> None:
        """SHADOW, after every check of the chain passed: the pre-egress steps, then what `prepare_attempt` would
        check (no earlier attempt of the intent may still be live; the reservation must fit), and the hypothetical
        reservation. Nothing is prepared, reserved or sent; nothing reaches `prepare_attempt` or `send`."""
        request, why = self._egress_request(cy, intent, market)
        reasons = [] if why is None else [why]
        attempts = self._journal.attempts_for(intent.intent_key)
        # Then `prepare_attempt`'s refusals, in its order and in its words (`PREPARE_REFUSED: <the exception>`), so
        # reasons[0] is exactly what a real decision reports; the rest of the list is every other refusal. The live
        # attempt check is a backstop: arbitration already drops a key this service planned (ADR 0047).
        blocked = live_attempt_problem(attempts)
        if blocked is not None:
            reasons.append(f"PREPARE_REFUSED: {AttemptRefused(blocked)}"[:300])
        if capacity is None or not capacity.allowed:
            refused = ReservationRefused(capacity.reasons if capacity is not None else ("CAPACITY_UNKNOWN",))
            reasons.append(f"PREPARE_REFUSED: {refused}"[:300])
        if reasons:
            self._decision(cy, intent, Outcome.BLOCKED, tuple(reasons), capacity=capacity, inputs=inputs)
            return
        reservation = sh.hypothetical_reservation(intent, attempt_no=len(attempts) + 1, at_utc=utc_text(now))
        cy.hypothetical.append((reservation, intent))
        cy.shadow_sends += 1
        self._decision(cy, intent, Outcome.WOULD_SUBMIT, (), reservation=reservation, capacity=capacity,
                       request_digest_=request_digest(request), inputs=inputs)

    def _policy_approval(self, intent: OrderIntent, grant: ctl.AutomationGrant, now: datetime) -> ApprovalGrant | None:
        expires = min(intent.expires_at(), parse_utc_text(grant.expires_at_utc), now + POLICY_APPROVAL_TTL)
        if expires <= now:
            return None
        return ApprovalGrant(intent_digest=intent.digest(), scope_key=self._scope.key(), method=ApprovalMethod.POLICY,
                             approver_ref="automation-grant", approved_at_utc=utc_text(now),
                             expires_at_utc=utc_text(expires), nonce=f"policy:{intent.digest()}",
                             policy_ref=grant.digest())

    def _prepare_and_send(self, cy: _Cycle, intent: OrderIntent, approval: ApprovalGrant,
                          market: gate.MarketState) -> None:
        if self._read_only:  # unreachable (a read-only process never arms a sending mode); kept as a second stop
            self._decision(cy, intent, Outcome.BLOCKED, ("READ_ONLY_IDENTITY: this process never sends a write",))
            return
        request, why = self._egress_request(cy, intent, market)
        if request is None:
            self._decision(cy, intent, Outcome.BLOCKED, (why,))
            return
        now = self._now()
        # The planned record is the index of every intent this service may have sent: written before the attempt.
        self._record("INTENT_PLANNED", {"intent": intent.to_dict(), "digest": intent.digest(), "cycle": cy.n}, now, cy)
        self._planned[intent.intent_key] = intent
        try:
            attempt = self._journal.prepare_attempt(intent, approval, fence_token=self._fence,
                                                    request_digest=request_digest(request),
                                                    snapshot_max_age=self._config.snapshot_max_age, now=now)
        except JournalUnavailable as exc:  # not known whether it committed: the key is re-read when next needed
            cy.anomalies.append((_incident_id("journal-unavailable", f"c{cy.n}"), f"{exc}"[:300]))
            self._decision(cy, intent, Outcome.BLOCKED, (f"PREPARE_FAILED: {exc}"[:300],))
            return
        except (JournalError, ReservationError) as exc:
            self._learn_attempts(intent.intent_key)  # a refusal committed nothing: the key has no attempt
            self._decision(cy, intent, Outcome.BLOCKED, (f"PREPARE_REFUSED: {exc}"[:300],))
            return
        self._learn_attempts(intent.intent_key)
        # The attempt is committed: from here the request is sent at most once.
        try:
            reply: Any = cy.budget.send(request)
            failure = None
        except Exception as exc:  # the request may have left: ambiguous, never retried
            reply, failure = None, f"SEND_RAISED: {type(exc).__name__}"
        state = self._record_reply(cy, intent, attempt.attempt_id, reply, failure)
        self._decision(cy, intent, Outcome.SUBMITTED, (), attempt.attempt_id, state)

    def _record_reply(self, cy: _Cycle, intent: OrderIntent, attempt_id: str, reply: Any,
                      failure: str | None) -> str:
        """Record the venue's answer and fold it through the lifecycle. Only a parsed OK naming this order, or a
        definitive REJECTED, is final; everything else is OUTCOME_UNKNOWN (reconciled later, never re-sent)."""
        j, now = self._journal, self._now()
        outcome = "SEND_FAILED" if failure else _outcome_text(reply)
        body = None if reply is None else getattr(reply, "body", None)
        text = _body_text(body)
        event: lc.Event
        # Each write below re-reads the lease (`_write`): after a takeover during the send the reply is the live
        # worker's to reconcile, not ours, and OrchestratorFencedOut ends the cycle before the next write.
        try:
            if outcome == "OK" and text is not None:
                try:
                    ack = w.parse_create_ack(body)
                except w.WireFormatError:
                    ack = None
                if ack is None or ack.client_order_id not in (None, intent.client_order_id()):
                    self._write(j.mark_sent, attempt_id, now=now)
                    self._write(j.mark_outcome_unknown,
                                attempt_id, reason="ACK_UNREADABLE_OR_FOR_ANOTHER_ORDER", now=now)
                    event = lc.SendReturnedAmbiguous(lc.Operation.NEW_ORDER, "ack unreadable")
                else:
                    receipt = f"ack:{attempt_id}"
                    self._write(j.record_receipt, receipt_id=receipt, kind=ReceiptKind.ORDER_ACK, source="venue-reply",
                                payload_json=text, received_at=now, provider_id=ack.order_id,
                                attempt_id=attempt_id)
                    self._write(j.mark_sent, attempt_id, now=now)
                    self._write(j.mark_acknowledged,
                                attempt_id, provider_order_id=ack.order_id, receipt_id=receipt, now=now)
                    event = lc.Acknowledged(provider_order_id=ack.order_id, client_order_id=intent.client_order_id(),
                                            status=_ack_status(ack, intent.quantity), filled_quantity=ack.fill_count,
                                            remaining_quantity=ack.remaining_count)
            elif outcome == "REJECTED":
                receipt = f"reject:{attempt_id}"
                payload = text if text is not None else canonical_json(
                    {"outcome": "REJECTED", "status": getattr(reply, "status", None)})
                self._write(j.record_receipt, receipt_id=receipt, kind=ReceiptKind.ORDER_REJECT, source="venue-reply",
                            payload_json=payload, received_at=now, attempt_id=attempt_id)
                self._write(j.mark_sent, attempt_id, now=now)
                self._write(j.mark_rejected, attempt_id, receipt_id=receipt, now=now)
                event = lc.Rejected(lc.Operation.NEW_ORDER, f"status {getattr(reply, 'status', None)}",
                                    client_order_id=intent.client_order_id())
            else:
                self._write(j.mark_sent, attempt_id, now=now)
                self._write(j.mark_outcome_unknown, attempt_id, reason=f"SEND_{outcome}"[:200], now=now)
                event = lc.SendReturnedAmbiguous(lc.Operation.NEW_ORDER, outcome)
        except (JournalError, ReservationError) as exc:
            cy.anomalies.append((_incident_id("journal-refused", attempt_id), f"{exc}"[:300]))
            return j.attempt(attempt_id).state.value
        prepared = j.attempt(attempt_id).created_at_utc
        view = lc.reduce(lc.reduce(lc.view_from_intent(intent), lc.SendPrepared(prepared)), event)
        if view.quarantined:
            cy.anomalies.append((_incident_id("lifecycle", attempt_id),
                                 f"lifecycle quarantine: {'; '.join(view.quarantine_reasons)[:300]}"))
        return j.attempt(attempt_id).state.value

    # risk-gate inputs, all from persisted records -------------------

    def _order_history(self) -> tuple[gate.OrderHistoryEntry, ...]:
        out = []
        for key, intent in self._planned.items():
            if key not in self._attempts_known:  # only after a prepare that failed unavailable: re-read it
                self._attempts_known.pop(key, None)
                self._learn_attempts(key)
            for attempt_id, created in self._attempts_known[key]:
                out.append(gate.OrderHistoryEntry(attempt_id, intent.market_ticker, intent.kind, created,
                                                  intent.max_total_cost if intent.kind is IntentKind.ENTRY else _ZERO))
        return tuple(out)

    def _projection(self, cy: _Cycle, view: AccountView, intent: OrderIntent) -> gate.AccountProjection:
        snap = view.snapshot
        tickers = {intent.market_ticker} | {r.market_ticker for r in view.held}
        if snap is not None:
            tickers |= {t for t, _ in (snap.positions or {})}
            tickers |= {e.market_ticker for e in snap.external_orders or () if e.market_ticker is not None}
        keys = {}
        for t in sorted(tickers):
            m = self._market(cy, t)
            if m is not None:
                keys[t] = gate.MarketKeys(m.event_key, m.cluster_key)
        intents = dict(self._planned)
        history = self._order_history()
        if cy.hypothetical:  # SHADOW: this cycle's WOULD_SUBMITs, as their real attempts would appear
            intents.update({i.intent_key: i for _, i in cy.hypothetical})
            history += tuple(gate.OrderHistoryEntry(r.reservation_id, i.market_ticker, i.kind, r.created_at_utc,
                                                    i.max_total_cost if i.kind is IntentKind.ENTRY else _ZERO)
                             for r, i in cy.hypothetical)
        return gate.project_account(
            view, projection_id=f"c{cy.n}:{intent.intent_key}"[:200], intents=MappingProxyType(intents),
            market_keys=MappingProxyType(keys),
            pnl_history=tuple(self._ledger) if self._pnl_baseline else None,
            pnl_history_since_utc=self._genesis if self._pnl_baseline else None,
            order_history=history, order_history_since_utc=self._genesis,
            account_genesis_utc=self._genesis)

    def _usage(self, cy: _Cycle, grant: ctl.AutomationGrant, view: AccountView, event_key: str,
               now: datetime) -> ctl.GrantUsage:
        """Grant usage from persisted records only: the latest snapshot and held reservations (exposure, $1 per held
        contract, an ENTRY's full cost while held), the journal's attempts (turnover today) and the venue P&L
        ledger (losses). Unknown stays None, which blocks. Its `as_of` is the time of the evidence (the older of the
        snapshot's observation and the P&L ledger's last COMPLETE read), never the decision time, so stale evidence
        is stale usage. Turnover, daily P&L and drawdown are running aggregates: nothing here rescans history."""
        day = now.date().isoformat()
        snap = view.snapshot
        event_exposure = total_exposure = None
        with localcontext(_exact_context()):
            if snap is not None and snap.positions is not None and not any(
                    r.quarantine_reason is not None for r in view.held):
                def in_event(ticker: str) -> bool:
                    m = self._market(cy, ticker)
                    return m is None or m.event_key in (None, event_key)  # unknown counts toward this event

                held = [(r.market_ticker, r.cash_worst_case) for r in view.held if r.kind is IntentKind.ENTRY]
                pos = [(t, q) for (t, _), q in snap.positions.items()]
                total_exposure = sum((c for _, c in held), _ZERO) + sum((q for _, q in pos), _ZERO)
                event_exposure = sum((c for t, c in held if in_event(t)), _ZERO) + sum(
                    (q for t, q in pos if in_event(t)), _ZERO)
            turnover = self._turnover.get(day, _ZERO)
            loss = drawdown = None
            if self._pnl_baseline:
                today = self._pnl_by_day.get(day, _ZERO)
                loss = -today if today < 0 else _ZERO
                drawdown = self._peak - self._equity
        evidence = [t for t in (None if snap is None else snap.observed_at_utc,
                                self._pnl_as_of if self._pnl_baseline else None) if t is not None]
        as_of = min(evidence, key=parse_utc_text) if len(evidence) == 2 else self._genesis  # unknown: stale
        return ctl.GrantUsage(grant.digest(), event_key, day, as_of, event_exposure, total_exposure, turnover, loss,
                              drawdown)

    # steps 11-12 ----------------------------------------------------

    def _settlement_and_attribution(self, cy: _Cycle) -> None:
        if cy.recon is None or cy.recon.status is not acct.ReconciliationStatus.COMPLETE:
            return
        sub = cy.recon.subaccounts[0]
        for s in sub.settlements or ():
            if s.ticker in self._settled:
                continue
            self._record("SETTLEMENT", {
                "ticker": s.ticker, "source": s.source.value, "event_ticker": s.event_ticker,
                "market_result": s.market_result, "yes_count": s.yes_count, "no_count": s.no_count,
                "yes_total_cost": s.yes_total_cost, "no_total_cost": s.no_total_cost, "revenue_cents": s.revenue_cents,
                "fee_cost": s.fee_cost, "settled_time": None if s.settled_time is None else utc_text(s.settled_time),
                "missing": list(s.missing), "cycle": cy.n}, self._now(), cy)
            self._settled.add(s.ticker)

    def _quarantine_scan(self, cy: _Cycle) -> None:
        for r in self._journal.reservations.held_reservations(self._scope):
            if r.quarantine_reason is not None:
                cy.anomalies.append((_incident_id("quarantine", r.reservation_id),
                                     f"reservation quarantined: {r.quarantine_reason}"[:300]))

    def _safety_review(self, cy: _Cycle) -> None:
        """Before any decision: quarantines, a degraded reconciliation, and every anomaly the read and the evidence
        produced become incidents now, so their disarm governs this cycle's decisions."""
        self._quarantine_scan(cy)
        degraded = cy.status is not ctl.Reconciliation.COMPLETE
        if degraded and not cy.control_disarmed_on_recon and self._last_status in (None, "COMPLETE"):
            cy.anomalies.append((_incident_id(f"reconciliation-{cy.status.value.lower()}", f"c{cy.n}"),
                                 f"account reconciliation {cy.status.value}"))
        self._raise_pending(cy)

    def _health_review(self, cy: _Cycle) -> None:
        self._quarantine_scan(cy)  # a reply recorded this cycle can quarantine too
        if cy.budget.exhausted:
            cy.anomalies.append((_incident_id("budget", f"c{cy.n}"), "the cycle's request budget is exhausted"))
        if cy.deadline_hit:
            cy.anomalies.append((_incident_id("deadline", f"c{cy.n}"), "the cycle deadline was reached"))
        self._raise_pending(cy)

    def _raise_pending(self, cy: _Cycle) -> None:
        """Raise every anomaly not yet raised (an open incident, or one raised recently, is not raised again)."""
        now = self._now()
        for incident_id, reason in cy.anomalies:
            if incident_id in self._raised or incident_id in self._state.open_incidents:
                continue
            self._apply(ctl.IncidentRaised(incident_id, reason, utc_text(now)), now, cy)
            cy.incidents.append(incident_id)

    # reporting ------------------------------------------------------

    def _report(self, cy: _Cycle) -> CycleReport:
        return CycleReport(cy.n, utc_text(cy.start), cy.mode_at_start, self._state.mode, cy.status.value,
                           None if cy.snapshot is None else cy.snapshot.revision, cy.budget.used,
                           MappingProxyType(dict(sorted(cy.signal_counts.items()))), self._take_rejections(),
                           cy.proposals, cy.ignored, tuple(cy.decisions), tuple(cy.resolved), cy.fills,
                           tuple(cy.released), tuple(cy.incidents), cy.records, cy.deadline_hit,
                           stream=None if self._stream is None else _frozen(self._stream_summary(cy)),
                           shadow_verdicts=tuple(cy.verdicts))

    def _stream_summary(self, cy: _Cycle) -> dict[str, Any]:
        return {**rc.summary(self._stream_state), "items_this_cycle": cy.stream_items,
                "findings": [list(f) for f in cy.stream_findings]}

    def _take_rejections(self) -> int:
        n, self._signals_rejected = self._signals_rejected, 0
        return n

    def _cycle_body(self, report: CycleReport) -> dict[str, Any]:
        return {"schema": CYCLE_SCHEMA, "cycle": report.cycle, "started_at_utc": report.started_at_utc,
                "mode_at_start": report.mode_at_start.value, "mode_at_end": report.mode_at_end.value,
                "reconciliation": report.reconciliation, "snapshot_revision": report.snapshot_revision,
                "requests_used": report.requests_used, "signals": dict(report.signals),
                "signals_rejected": report.signals_rejected, "proposals": report.proposals,
                "proposals_ignored": report.proposals_ignored,
                "decisions": [[d.intent_key, d.outcome.value, d.attempt_id, d.attempt_state] for d in report.decisions],
                "resolved_unknown": list(report.resolved_unknown), "fills_recorded": report.fills_recorded,
                "released": list(report.released), "incidents": list(report.incidents),
                "deadline_hit": report.deadline_hit,
                "fixture_cash_basis": None if self._config.fixture_cash_basis is None
                else self._config.fixture_cash_basis.value,
                **({} if report.stream is None else {"stream": json.loads(canonical_json(_thawed(report.stream)))})}

    # ------------------------------------------------------------------ shutdown

    def shutdown(self, operator_ref: str, reason: str, *, cancel_owned: bool = False) -> ShutdownReport:
        """Stop new risk (a persisted Disarm). Resting orders are left alone unless `cancel_owned` asks to cancel our
        own: each is a CANCEL_OWNED action, requested in the journal before it is sent and confirmed only by the
        venue's answer. No further cycle runs on this instance."""
        self._check_running()
        if cancel_owned and self._read_only:
            raise OrchestratorError("READ_ONLY_IDENTITY: a read-only process cancels nothing")
        now = self._now()
        if self._fenced_out or not self._lease_held():
            self._stopped = True  # the live worker owns the account: nothing is written or cancelled from here
            return ShutdownReport(utc_text(now), (), MappingProxyType({}), ())
        requested: list[str] = []
        outcomes: dict[str, str] = {}
        left: list[str] = []
        try:
            self._shutdown(operator_ref, reason, cancel_owned, now, requested, outcomes, left)
        except OrchestratorFencedOut:  # the lease was lost during the shutdown: nothing more is written from here
            pass
        self._stopped = True
        return ShutdownReport(utc_text(now), tuple(requested), MappingProxyType(dict(outcomes)), tuple(sorted(left)))

    def _shutdown(self, operator_ref: str, reason: str, cancel_owned: bool, now: datetime, requested: list[str],
                  outcomes: dict[str, str], left: list[str]) -> None:
        """The shutdown's steps; `requested`, `outcomes` and `left` are filled as it goes, so a shutdown cut short
        by a lost lease still reports what it did."""
        self._apply(ctl.Disarm(operator_ref, reason, utc_text(now)), now)
        resting: list[tuple[ReservationView, Any]] = []
        for r in self._journal.reservations.held_reservations(self._scope):
            attempt = self._journal.attempt(r.reservation_id)
            if attempt.state is AttemptState.ACKNOWLEDGED and attempt.provider_order_id is not None \
                    and r.state is ObligationState.OUTSTANDING and r.quarantine_reason is None:
                resting.append((r, attempt))
        for r, attempt in resting:
            if not cancel_owned:
                left.append(r.reservation_id)
                continue
            requested.append(r.reservation_id)
            outcomes[r.reservation_id] = self._cancel_owned(r, attempt)
        self._record("SHUTDOWN", {"operator_ref": operator_ref, "reason": reason, "cancel_owned": cancel_owned,
                                  "cancels": dict(sorted(outcomes.items())), "resting_left": sorted(left)},
                     self._now())

    def _cancel_owned(self, r: ReservationView, attempt: Any) -> str:
        if self._read_only:  # unreachable (shutdown refuses cancel_owned first); kept as a second stop
            return "REFUSED: READ_ONLY_IDENTITY"
        now = self._now()
        problems = ctl.action_problems(self._state, ctl.ControlAction.CANCEL_OWNED, venue=VENUE,
                                       strategy_id="-", market_ticker=r.market_ticker, now=now,
                                       grants=self._config.grants)
        if problems:
            return "REFUSED: " + "; ".join(problems)
        if not self._lease_held():
            return "REFUSED: NO_EGRESS_LEASE (another worker holds the lease)"
        try:
            self._journal.reservations.renew_lease(self._config.worker_id, self._fence, self._config.lease_ttl, now)
        except StaleFence:
            self._fence, self._fenced_out = None, True
            return "REFUSED: NO_EGRESS_LEASE (another worker holds the lease)"
        market = None
        try:
            market = self._feed.market_state(r.market_ticker, now)
        except Exception:
            market = None
        if not isinstance(market, gate.MarketState):
            return "REFUSED: the market's shard is unknown"
        request = w.build_cancel(self._scope, attempt.provider_order_id, exchange_index=market.exchange_index)
        auth = self._journal.reservations
        try:
            self._write(auth.request_cancel, r.reservation_id, now)  # requested in the journal before it is sent
        except OrchestratorFencedOut:
            return "REFUSED: NO_EGRESS_LEASE (another worker holds the lease)"
        try:
            reply = self._send(request)
            outcome = _outcome_text(reply)
        except Exception as exc:
            reply, outcome = None, f"SEND_RAISED: {type(exc).__name__}"
        text = None if reply is None else _body_text(getattr(reply, "body", None))
        if not self._lease_held():  # a takeover during the send: the live worker reconciles this order, not us
            return "CANCEL_OUTCOME_UNKNOWN: the egress lease was lost during the send (nothing recorded here)"
        try:
            if outcome == "OK" and text is not None:
                ack = w.parse_cancel_ack(reply.body)
                if ack.order_id != attempt.provider_order_id or ack.client_order_id not in (None, r.client_order_id):
                    # An answer for another order proves nothing about ours: kept as evidence, the order is unknown.
                    self._write(self._journal.record_receipt, receipt_id=f"cancel-mismatch:{r.reservation_id}",
                                kind="CANCEL_REPLY_MISMATCH", source="venue-reply",
                                payload_json=text, received_at=self._now(),
                                provider_id=ack.order_id, attempt_id=r.reservation_id)
                    self._write(auth.mark_unknown, r.reservation_id, self._now(), reason="CANCEL_ACK_FOR_ANOTHER_ORDER")
                    return "CANCEL_OUTCOME_UNKNOWN: the reply names another order"
                receipt = f"cancel:{r.reservation_id}"
                self._write(self._journal.record_receipt,
                            receipt_id=receipt, kind=ReceiptKind.CANCEL_CONFIRM, source="venue-reply",
                            payload_json=text, received_at=self._now(), provider_id=ack.order_id,
                            attempt_id=r.reservation_id)
                with localcontext(_exact_context()):
                    filled = r.quantity - ack.reduced_by
                self._write(auth.confirm_cancel, r.reservation_id, self._now(), receipt_id=receipt, venue_filled=filled)
                return "CANCEL_CONFIRMED"
            if outcome == "REJECTED":
                receipt = f"cancel-reject:{r.reservation_id}"
                self._write(self._journal.record_receipt,
                            receipt_id=receipt, kind=ReceiptKind.CANCEL_REJECT, source="venue-reply",
                            payload_json=text or canonical_json({"outcome": "REJECTED"}),
                            received_at=self._now(), attempt_id=r.reservation_id)
                self._write(auth.mark_open, r.reservation_id, self._now(), receipt_id=receipt)
                return "CANCEL_REJECTED"
            self._write(auth.mark_unknown, r.reservation_id, self._now(), reason=f"CANCEL_{outcome}"[:200])
            return "CANCEL_OUTCOME_UNKNOWN"
        except OrchestratorFencedOut:  # lost between two writes: what is not recorded is the live worker's to reconcile
            return "CANCEL_OUTCOME_UNKNOWN: the egress lease was lost while recording the reply"
        except (JournalError, ReservationError, w.WireFormatError) as exc:
            return f"CANCEL_RECORD_FAILED: {exc}"[:300]
