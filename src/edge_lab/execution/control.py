"""Operating modes, kill latches and automated-policy grants (#160 packages L/N, ADR 0043). Pure.

This module decides *whether* the executor may create new risk and in what mode. It sends nothing and stores
nothing: the orchestrator persists its events through the journal and replays them with `replay`.

- **Modes**: DISARMED, OBSERVE_ONLY, SHADOW, DEMO, HUMAN_CONFIRMATION, BOUNDED_AUTO.
  - Startup is always DISARMED, and replay never restores an armed mode. Only an explicit `ArmRequest` arms,
    and only after a COMPLETE reconciliation.
  - DEMO needs the DEMO environment authorized. HUMAN_CONFIRMATION and BOUNDED_AUTO need the scope's
    environment authorized (today that is only FIXTURE: `model.AUTHORIZED_ENVIRONMENTS`).
  - BOUNDED_AUTO also needs a valid `AutomationGrant` for that scope.
- **Incidents** latch the controller to DISARMED. Rearming must acknowledge every open incident by id:
  there is no silent rearm and no automatic recovery.
- **Kill latches** (global, venue, strategy or market NEW_RISK_DISABLED) block new risk in every mode.
  Reductions can still go out in HUMAN_CONFIRMATION and BOUNDED_AUTO. A latch is cleared only by an explicit
  `ClearLatch`, and never by a restart.
- **Grants.** An `AutomationGrant` binds:
  - environment, account scope, strategy, model and policy hashes;
  - universe, allowed intent kinds and expiry;
  - exact limits (per-order cost, per-event exposure, total exposure, daily turnover).

  `grant_problems` checks one intent against the grant and the cumulative usage the caller supplies. That
  usage comes from persisted records, never process memory, so a restart cannot reset it. A grant is never
  issued here: issuing one is an owner decision recorded in EXECUTION_PLAN.

Every order still passes the risk gate (package I) and the journal's reservation regardless of mode or grant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Union
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .model import (AccountScope, Environment, ExactValueError, IntentKind, OrderIntent, canonical_json,
                    environment_authorized, exact_decimal, parse_utc_text, sha256_text)

GRANT_SCHEMA = "edge-lab-automation-grant/1"
_HASH = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")


class Mode(str, Enum):
    DISARMED = "DISARMED"  # no egress of any kind; startup state
    OBSERVE_ONLY = "OBSERVE_ONLY"  # reads and reconciliation only
    SHADOW = "SHADOW"  # full decision chain, outputs WOULD_SUBMIT / BLOCKED, never sends (package M)
    DEMO = "DEMO"  # sends to the DEMO environment only
    HUMAN_CONFIRMATION = "HUMAN_CONFIRMATION"  # sends only intents with a valid human ApprovalGrant
    BOUNDED_AUTO = "BOUNDED_AUTO"  # sends intents inside an AutomationGrant without per-order confirmation


SENDING_MODES = frozenset({Mode.DEMO, Mode.HUMAN_CONFIRMATION, Mode.BOUNDED_AUTO})


class LatchScope(str, Enum):
    GLOBAL = "GLOBAL"
    VENUE = "VENUE"
    STRATEGY = "STRATEGY"
    MARKET = "MARKET"


class Reconciliation(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


# ------------------------------------------------------------------ events (what the journal persists)


@dataclass(frozen=True)
class Started:
    """A process start. Always yields DISARMED, whatever was persisted before."""

    at_utc: str


@dataclass(frozen=True)
class ReconciliationObserved:
    status: Reconciliation
    at_utc: str
    detail: str = ""


@dataclass(frozen=True)
class IncidentRaised:
    incident_id: str
    reason: str
    at_utc: str


@dataclass(frozen=True)
class ArmRequest:
    """An explicit operator request to enter `mode`. It names every open incident it acknowledges."""

    mode: Mode
    operator_ref: str
    acknowledged_incidents: tuple[str, ...]
    at_utc: str
    grant_digest: str | None = None  # BOUNDED_AUTO: the grant being armed against


@dataclass(frozen=True)
class Disarm:
    operator_ref: str
    reason: str
    at_utc: str


@dataclass(frozen=True)
class SetLatch:
    scope: LatchScope
    key: str  # "*" for GLOBAL; a venue id, strategy id or market ticker otherwise
    reason: str
    at_utc: str


@dataclass(frozen=True)
class ClearLatch:
    scope: LatchScope
    key: str
    operator_ref: str
    at_utc: str


Event = Union[Started, ReconciliationObserved, IncidentRaised, ArmRequest, Disarm, SetLatch, ClearLatch]


# ------------------------------------------------------------------ state


@dataclass(frozen=True)
class ControlState:
    scope: AccountScope
    mode: Mode = Mode.DISARMED
    reconciliation: Reconciliation = Reconciliation.NOT_RUN
    open_incidents: tuple[str, ...] = ()
    latches: frozenset[tuple[LatchScope, str]] = frozenset()
    armed_grant_digest: str | None = None
    refusals: tuple[str, ...] = ()  # why the last arm request (if any) was refused
    log: tuple[str, ...] = field(default=())  # one line per applied event: auditable, never trimmed


def initial_state(scope: AccountScope) -> ControlState:
    if not isinstance(scope, AccountScope):
        raise ValueError("scope must be an AccountScope")
    return ControlState(scope=scope)


def _mode_problems(state: ControlState, request: ArmRequest, grants: tuple["AutomationGrant", ...],
                   now: datetime) -> list[str]:
    out = []
    env = state.scope.environment
    if request.mode is Mode.DISARMED:
        return ["ARM_TO_DISARMED: use Disarm"]
    if state.reconciliation is not Reconciliation.COMPLETE:
        out.append(f"RECONCILIATION_NOT_COMPLETE: {state.reconciliation.value}")
    missing = sorted(set(state.open_incidents) - set(request.acknowledged_incidents))
    if missing:
        out.append(f"INCIDENTS_NOT_ACKNOWLEDGED: {missing}")
    if request.mode is Mode.DEMO and env is not Environment.DEMO:
        out.append("DEMO_MODE_NEEDS_DEMO_SCOPE")
    if request.mode in SENDING_MODES and not environment_authorized(env):
        out.append(f"ENVIRONMENT_NOT_AUTHORIZED: {env.value}")
    if request.mode is Mode.BOUNDED_AUTO:
        grant = next((g for g in grants if g.digest() == request.grant_digest), None)
        if grant is None:
            out.append("GRANT_MISSING: BOUNDED_AUTO needs a recorded AutomationGrant")
        else:
            out += grant.validity_problems(state.scope, now)
    elif request.grant_digest is not None:
        out.append("GRANT_UNEXPECTED: only BOUNDED_AUTO arms against a grant")
    return out


def reduce(state: ControlState, event: Event, *, grants: tuple["AutomationGrant", ...] = (),
           now: datetime | None = None) -> ControlState:
    """Apply one event. Pure. `grants` are the recorded grants (journal), `now` the evaluation time for arm requests."""
    if isinstance(event, Started):
        return replace(state, mode=Mode.DISARMED, reconciliation=Reconciliation.NOT_RUN, armed_grant_digest=None,
                       refusals=(), log=state.log + (f"{event.at_utc} STARTED -> DISARMED",))
    if isinstance(event, ReconciliationObserved):
        disarm = event.status is not Reconciliation.COMPLETE and state.mode in SENDING_MODES
        mode = Mode.DISARMED if disarm else state.mode
        note = " (sending mode dropped: reconciliation not complete)" if disarm else ""
        return replace(state, reconciliation=event.status, mode=mode,
                       armed_grant_digest=None if disarm else state.armed_grant_digest,
                       log=state.log + (f"{event.at_utc} RECONCILIATION {event.status.value}{note}",))
    if isinstance(event, IncidentRaised):
        incidents = state.open_incidents if event.incident_id in state.open_incidents \
            else state.open_incidents + (event.incident_id,)
        return replace(state, mode=Mode.DISARMED, open_incidents=incidents, armed_grant_digest=None,
                       log=state.log + (f"{event.at_utc} INCIDENT {event.incident_id}: {event.reason} -> DISARMED",))
    if isinstance(event, ArmRequest):
        if now is None:
            raise ValueError("an arm request is evaluated at an explicit now")
        problems = _mode_problems(state, event, grants, now)
        if problems:
            return replace(state, refusals=tuple(problems),
                           log=state.log + (f"{event.at_utc} ARM {event.mode.value} REFUSED: {'; '.join(problems)}",))
        return replace(state, mode=event.mode, open_incidents=(), refusals=(),
                       armed_grant_digest=event.grant_digest if event.mode is Mode.BOUNDED_AUTO else None,
                       log=state.log + (f"{event.at_utc} ARMED {event.mode.value} by {event.operator_ref}; "
                                        f"acknowledged {list(event.acknowledged_incidents)}",))
    if isinstance(event, Disarm):
        return replace(state, mode=Mode.DISARMED, armed_grant_digest=None,
                       log=state.log + (f"{event.at_utc} DISARM by {event.operator_ref}: {event.reason}",))
    if isinstance(event, SetLatch):
        key = "*" if event.scope is LatchScope.GLOBAL else event.key
        return replace(state, latches=state.latches | {(event.scope, key)},
                       log=state.log + (f"{event.at_utc} LATCH {event.scope.value}:{key} ({event.reason})",))
    if isinstance(event, ClearLatch):
        key = "*" if event.scope is LatchScope.GLOBAL else event.key
        return replace(state, latches=state.latches - {(event.scope, key)},
                       log=state.log + (f"{event.at_utc} UNLATCH {event.scope.value}:{key} by {event.operator_ref}",))
    raise TypeError(f"unknown control event {type(event).__name__}")


def replay(scope: AccountScope, events: tuple[Event, ...], *,
           grants: tuple["AutomationGrant", ...] = ()) -> ControlState:
    """Rebuild state from persisted events. A trailing `Started` is implied: replay after a restart is DISARMED,
    with latches and open incidents kept, so a restart never resets them and never rearms."""
    state = initial_state(scope)
    for event in events:
        at = parse_utc_text(event.at_utc)
        state = reduce(state, event, grants=grants, now=at)
    return reduce(state, Started(at_utc=events[-1].at_utc if events else "1970-01-01T00:00:00+00:00"))


def new_risk_problems(state: ControlState, *, venue: str, strategy_id: str, market_ticker: str,
                      kind: IntentKind) -> list[str]:
    """Why the controller blocks this intent now (empty: the controller permits it; the risk gate still decides)."""
    out = []
    if state.mode not in SENDING_MODES:
        out.append(f"MODE_DOES_NOT_SEND: {state.mode.value}")
    if state.reconciliation is not Reconciliation.COMPLETE:
        out.append(f"RECONCILIATION_NOT_COMPLETE: {state.reconciliation.value}")
    if state.open_incidents:
        out.append(f"OPEN_INCIDENTS: {list(state.open_incidents)}")
    if kind is IntentKind.ENTRY:
        hits = [f"{s.value}:{k}" for s, k in sorted(state.latches)
                if (s is LatchScope.GLOBAL) or (s is LatchScope.VENUE and k == venue)
                or (s is LatchScope.STRATEGY and k == strategy_id) or (s is LatchScope.MARKET and k == market_ticker)]
        if hits:
            out.append(f"NEW_RISK_LATCHED: {hits}")
    return out


# ------------------------------------------------------------------ automated-policy grants


@dataclass(frozen=True)
class GrantLimits:
    """Exact limits a grant binds. Every value is a Decimal dollar amount; there is no default."""

    max_order_cost: Decimal
    max_event_exposure: Decimal
    max_total_exposure: Decimal
    max_daily_turnover: Decimal

    def __post_init__(self) -> None:
        for name in ("max_order_cost", "max_event_exposure", "max_total_exposure", "max_daily_turnover"):
            value = exact_decimal(getattr(self, name), name=name)
            if value < 0:
                raise ExactValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class GrantUsage:
    """Cumulative usage under one grant, from persisted records (journal reservations and fills), never memory.
    None is unknown and blocks: a grant cannot be used when its consumption cannot be measured."""

    event_exposure: Decimal | None
    total_exposure: Decimal | None
    turnover_today: Decimal | None

    def __post_init__(self) -> None:
        for name in ("event_exposure", "total_exposure", "turnover_today"):
            value = getattr(self, name)
            if value is not None:
                value = exact_decimal(value, name=name)
                if value < 0:
                    raise ExactValueError(f"{name} must not be negative")
                object.__setattr__(self, name, value)


@dataclass(frozen=True)
class AutomationGrant:
    environment: Environment
    scope_key: str
    strategy_id: str
    strategy_version: str
    model_hash: str
    policy_hash: str
    universe: frozenset[str]  # exact market tickers or series prefixes ending in "*"
    allowed_kinds: frozenset[IntentKind]
    limits: GrantLimits
    issued_at_utc: str
    expires_at_utc: str
    issuer_ref: str  # the EXECUTION_PLAN entry that records the owner's grant
    schema: str = GRANT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GRANT_SCHEMA:
            raise ValueError(f"unknown grant schema {self.schema!r}")
        if not isinstance(self.environment, Environment):
            raise ValueError("environment must be an Environment")
        for name in ("scope_key", "strategy_id", "strategy_version", "issuer_ref"):
            if not isinstance(getattr(self, name), str) or not _REF.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a short identifier")
        for name in ("model_hash", "policy_hash"):
            if not isinstance(getattr(self, name), str) or not _HASH.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if not isinstance(self.universe, frozenset) or not self.universe \
                or not all(isinstance(u, str) and re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*\*?", u) for u in self.universe):
            raise ValueError("universe must be a non-empty frozenset of tickers or prefixes ending in *")
        if not isinstance(self.allowed_kinds, frozenset) or not self.allowed_kinds \
                or not all(isinstance(k, IntentKind) for k in self.allowed_kinds):
            raise ValueError("allowed_kinds must be a non-empty frozenset of IntentKind")
        if not isinstance(self.limits, GrantLimits):
            raise ValueError("limits must be GrantLimits")
        if parse_utc_text(self.expires_at_utc) <= parse_utc_text(self.issued_at_utc):
            raise ValueError("a grant must expire after it is issued")

    def to_dict(self) -> dict:
        return {"schema": self.schema, "environment": self.environment.value, "scope_key": self.scope_key,
                "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
                "model_hash": self.model_hash, "policy_hash": self.policy_hash, "universe": sorted(self.universe),
                "allowed_kinds": sorted(k.value for k in self.allowed_kinds),
                "limits": {"max_order_cost": self.limits.max_order_cost,
                           "max_event_exposure": self.limits.max_event_exposure,
                           "max_total_exposure": self.limits.max_total_exposure,
                           "max_daily_turnover": self.limits.max_daily_turnover},
                "issued_at_utc": self.issued_at_utc, "expires_at_utc": self.expires_at_utc,
                "issuer_ref": self.issuer_ref}

    def digest(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))

    def validity_problems(self, scope: AccountScope, now: datetime) -> list[str]:
        out = []
        if self.scope_key != scope.key() or self.environment is not scope.environment:
            out.append("GRANT_SCOPE_MISMATCH")
        if not environment_authorized(self.environment):
            out.append(f"GRANT_ENVIRONMENT_NOT_AUTHORIZED: {self.environment.value}")
        if now < parse_utc_text(self.issued_at_utc):
            out.append("GRANT_NOT_YET_VALID")
        if now >= parse_utc_text(self.expires_at_utc):
            out.append("GRANT_EXPIRED")
        return out

    def in_universe(self, ticker: str) -> bool:
        return any(ticker == u or (u.endswith("*") and ticker.startswith(u[:-1])) for u in self.universe)


def grant_problems(grant: AutomationGrant, intent: OrderIntent, *, usage: GrantUsage, model_hash: str,
                   policy_hash: str, now: datetime) -> list[str]:
    """Why `intent` falls outside `grant` (empty: inside it). A changed model or policy hash, a changed
    strategy version or any limit breach is outside. Exposure limits apply to ENTRY; turnover to every intent."""
    out = grant.validity_problems(intent.scope, now)
    if intent.strategy_id != grant.strategy_id or intent.strategy_version != grant.strategy_version:
        out.append("GRANT_STRATEGY_MISMATCH")
    if model_hash != grant.model_hash:
        out.append("GRANT_MODEL_CHANGED")
    if policy_hash != grant.policy_hash:
        out.append("GRANT_POLICY_CHANGED")
    if not grant.in_universe(intent.market_ticker):
        out.append(f"GRANT_UNIVERSE: {intent.market_ticker} is outside the grant")
    if intent.kind not in grant.allowed_kinds:
        out.append(f"GRANT_KIND: {intent.kind.value} is not allowed")
    if intent.max_total_cost > grant.limits.max_order_cost:
        out.append(f"GRANT_ORDER_COST: {intent.max_total_cost} > {grant.limits.max_order_cost}")
    if usage.turnover_today is None:
        out.append("GRANT_USAGE_UNKNOWN: turnover")
    elif usage.turnover_today + intent.max_total_cost > grant.limits.max_daily_turnover:
        out.append("GRANT_TURNOVER")
    if intent.kind is IntentKind.ENTRY:
        if usage.event_exposure is None or usage.total_exposure is None:
            out.append("GRANT_USAGE_UNKNOWN: exposure")
        else:
            if usage.event_exposure + intent.max_total_cost > grant.limits.max_event_exposure:
                out.append("GRANT_EVENT_EXPOSURE")
            if usage.total_exposure + intent.max_total_cost > grant.limits.max_total_exposure:
                out.append("GRANT_TOTAL_EXPOSURE")
    return out
