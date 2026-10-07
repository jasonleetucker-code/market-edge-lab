"""Operating modes, actions, kill latches and automated-policy grants (#160 packages L/N, ADR 0043). Pure.

This module decides *what* the executor may do now. It sends nothing and stores nothing: the orchestrator
persists events through the journal and rebuilds state with `replay`.

**Decisions are events.**
- An `ArmRequest` is judged once, live, by `decide_arm`. That produces an `ArmAccepted` or `ArmRefused` outcome,
  which is persisted.
- `replay` applies stored outcomes and never re-decides. So a restart can neither revive a refused request nor
  drop an incident that was never acknowledged.

**Modes:** DISARMED, OBSERVE_ONLY, SHADOW, DEMO, HUMAN_CONFIRMATION, BOUNDED_AUTO.
- Startup and replay always end DISARMED.
- Leaving DISARMED needs the scope's environment authorized (`model.AUTHORIZED_ENVIRONMENTS`, today FIXTURE
  only), because every other mode at least reads.
- SHADOW and the sending modes also need a COMPLETE reconciliation and no unacknowledged incident.
- DEMO needs a DEMO scope.
- BOUNDED_AUTO needs a recorded, valid `AutomationGrant`, and that grant is re-checked on every action, so expiry
  stops it.

**Actions** (`action_problems`) are judged separately:
- **READ** (account and market reads for reconciliation): allowed whenever the environment is authorized,
  DISARMED included, since that is how a disarmed executor reconciles.
- **CANCEL_OWNED** (cancel our own resting orders): an emergency action, allowed in any mode, DISARMED included,
  when the environment is authorized. It never touches unattributed orders.
- **NEW_RISK** (ENTRY): only in a sending mode, with COMPLETE reconciliation, no open incident and no matching
  latch.
- **REDUCE** (a reduce-only sale): in a sending mode. Under a matching latch, the automated modes (DEMO,
  BOUNDED_AUTO) need an explicit, unexpired `CloseoutAuthorized` for that active latch. HUMAN_CONFIRMATION approves
  each order anyway.
- **CLOSEOUT** (a separately authorized liquidation): needs `CloseoutAuthorized` and a sending mode. It is never
  automatic.

**Incidents.**
- An incident, or losing reconciliation while in SHADOW or a sending mode, raises an incident and drops to
  DISARMED.
- Incidents are cleared only by `IncidentAcknowledged`, or by an accepted arm request that names them.

**Latches.**
- GLOBAL, VENUE, STRATEGY and MARKET NEW_RISK latches survive restarts, and only `ClearLatch` removes them.
- Keys are normalized: venue lower-case, market ticker upper-case.

**Grants.**
- An `AutomationGrant` binds environment, account scope and venue; strategy, model, policy, risk-policy, fee and
  profile versions; universe, kinds and exact limits, loss limits included; and expiry.
- `GrantUsage` is anchored to one grant digest, one event key and one UTC day, with an as-of time. A mismatched or
  stale usage record blocks.
- No grant is issued here; issuing one is an owner decision recorded in EXECUTION_PLAN.

Every order still passes the risk gate (package I) and the journal's reservation, whatever the mode or grant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Union

from .model import (AccountScope, Environment, ExactValueError, IntentKind, OrderIntent, canonical_json,
                    environment_authorized, exact_decimal, exact_product, parse_utc_text, sha256_text)

GRANT_SCHEMA = "edge-lab-automation-grant/2"
USAGE_MAX_AGE = timedelta(minutes=5)  # usage older than this at decision time is stale and blocks
_HASH = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")
_INCIDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")


class Mode(str, Enum):
    DISARMED = "DISARMED"  # reads and owned-order cancels only; startup state
    OBSERVE_ONLY = "OBSERVE_ONLY"  # reads and reconciliation
    SHADOW = "SHADOW"  # the full decision chain, output WOULD_SUBMIT / BLOCKED, never sends (package M)
    DEMO = "DEMO"  # sends to the DEMO environment only
    HUMAN_CONFIRMATION = "HUMAN_CONFIRMATION"  # sends only intents with a valid human ApprovalGrant
    BOUNDED_AUTO = "BOUNDED_AUTO"  # sends inside an AutomationGrant without per-order confirmation


SENDING_MODES = frozenset({Mode.DEMO, Mode.HUMAN_CONFIRMATION, Mode.BOUNDED_AUTO})
AUTOMATED_MODES = frozenset({Mode.DEMO, Mode.BOUNDED_AUTO})  # send without a human approving each order
RECONCILED_MODES = SENDING_MODES | {Mode.SHADOW}


class ControlAction(str, Enum):
    READ = "READ"
    CANCEL_OWNED = "CANCEL_OWNED"
    NEW_RISK = "NEW_RISK"
    REDUCE = "REDUCE"
    CLOSEOUT = "CLOSEOUT"


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


def latch_key(scope: LatchScope, key: str) -> str:
    """The normalized key a latch is stored and matched under."""
    if scope is LatchScope.GLOBAL:
        return "*"
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"a {scope.value} latch needs a key")
    key = key.strip()
    return key.lower() if scope is LatchScope.VENUE else key.upper() if scope is LatchScope.MARKET else key


def _check_time(text: str) -> None:
    parse_utc_text(text)  # raises on naive or malformed text, so a bad event fails at construction, not at replay


def _check_ref(name: str, value: str) -> None:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty short identifier, not {value!r}")


# ------------------------------------------------------------------ events (what the journal persists)


@dataclass(frozen=True)
class Started:
    at_utc: str

    def __post_init__(self) -> None:
        _check_time(self.at_utc)


@dataclass(frozen=True)
class ReconciliationObserved:
    status: Reconciliation
    at_utc: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, Reconciliation):
            raise ValueError("status must be a Reconciliation")
        _check_time(self.at_utc)


@dataclass(frozen=True)
class IncidentRaised:
    incident_id: str
    reason: str
    at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, str) or not _INCIDENT.fullmatch(self.incident_id):
            raise ValueError("incident_id must be a short identifier")
        _check_time(self.at_utc)


@dataclass(frozen=True)
class IncidentAcknowledged:
    incident_id: str
    operator_ref: str
    at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, str) or not _INCIDENT.fullmatch(self.incident_id):
            raise ValueError("incident_id must be a short identifier")
        _check_ref("operator_ref", self.operator_ref)
        _check_time(self.at_utc)


@dataclass(frozen=True)
class ArmRequest:
    """An operator's request to enter `mode`. It is never persisted as authority: `decide_arm` turns it into an
    outcome."""

    mode: Mode
    operator_ref: str
    acknowledged_incidents: tuple[str, ...]
    at_utc: str
    grant_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, Mode):
            raise ValueError("mode must be a Mode")
        _check_ref("operator_ref", self.operator_ref)
        if not isinstance(self.acknowledged_incidents, tuple):
            raise ValueError("acknowledged_incidents must be a tuple")
        if self.grant_digest is not None and not _HASH.fullmatch(self.grant_digest):
            raise ValueError("grant_digest must be a SHA-256 hex digest")
        _check_time(self.at_utc)


@dataclass(frozen=True)
class ArmAccepted:
    """A live arm decision. `basis` is `state_basis` of the state it was decided on: `reduce` refuses it if any
    event landed in between (reconciliation change, incident, latch...), so a stale acceptance cannot arm."""

    mode: Mode
    operator_ref: str
    acknowledged_incidents: tuple[str, ...]
    grant_digest: str | None
    at_utc: str
    basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, Mode) or self.mode is Mode.DISARMED:
            raise ValueError("an accepted arm names a Mode other than DISARMED")
        _check_ref("operator_ref", self.operator_ref)
        if not isinstance(self.acknowledged_incidents, tuple):
            raise ValueError("acknowledged_incidents must be a tuple")
        if self.grant_digest is not None and not _HASH.fullmatch(self.grant_digest):
            raise ValueError("grant_digest must be a SHA-256 hex digest")
        if (self.mode is Mode.BOUNDED_AUTO) != (self.grant_digest is not None):
            raise ValueError("a grant digest is required for, and only for, BOUNDED_AUTO")
        if not isinstance(self.basis, str) or not _HASH.fullmatch(self.basis):
            raise ValueError("basis must be a state_basis digest")
        _check_time(self.at_utc)


@dataclass(frozen=True)
class ArmRefused:
    mode: Mode
    operator_ref: str
    reasons: tuple[str, ...]
    at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, Mode):
            raise ValueError("mode must be a Mode")
        _check_ref("operator_ref", self.operator_ref)
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("a refusal states its reasons")
        _check_time(self.at_utc)


@dataclass(frozen=True)
class Disarm:
    operator_ref: str
    reason: str
    at_utc: str

    def __post_init__(self) -> None:
        _check_ref("operator_ref", self.operator_ref)
        _check_time(self.at_utc)


@dataclass(frozen=True)
class SetLatch:
    scope: LatchScope
    key: str
    reason: str
    at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LatchScope):
            raise ValueError("scope must be a LatchScope")
        object.__setattr__(self, "key", latch_key(self.scope, self.key))
        _check_time(self.at_utc)


@dataclass(frozen=True)
class ClearLatch:
    scope: LatchScope
    key: str
    operator_ref: str
    at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LatchScope):
            raise ValueError("scope must be a LatchScope")
        object.__setattr__(self, "key", latch_key(self.scope, self.key))
        _check_ref("operator_ref", self.operator_ref)
        _check_time(self.at_utc)


@dataclass(frozen=True)
class CloseoutAuthorized:
    """An operator's explicit, expiring authorization to reduce or close out under one *active* latch. It is
    ignored (and logged as refused) if that latch is not set when it arrives, and it lapses at `expires_at_utc`."""

    scope: LatchScope
    key: str
    operator_ref: str
    at_utc: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LatchScope):
            raise ValueError("scope must be a LatchScope")
        object.__setattr__(self, "key", latch_key(self.scope, self.key))
        _check_ref("operator_ref", self.operator_ref)
        _check_time(self.at_utc)
        if parse_utc_text(self.expires_at_utc) <= parse_utc_text(self.at_utc):
            raise ValueError("a closeout authorization must expire after it is given")


Event = Union[Started, ReconciliationObserved, IncidentRaised, IncidentAcknowledged, ArmAccepted, ArmRefused, Disarm,
              SetLatch, ClearLatch, CloseoutAuthorized]


# ------------------------------------------------------------------ state


@dataclass(frozen=True)
class ControlState:
    scope: AccountScope
    mode: Mode = Mode.DISARMED
    reconciliation: Reconciliation = Reconciliation.NOT_RUN
    open_incidents: tuple[str, ...] = ()
    latches: frozenset[tuple[LatchScope, str]] = frozenset()
    closeouts: frozenset[tuple[LatchScope, str, str]] = frozenset()  # (scope, key, expires_at_utc)
    armed_grant_digest: str | None = None
    log: tuple[str, ...] = ()  # one line per applied event: auditable, never trimmed


def state_basis(state: ControlState) -> str:
    """A digest of everything an arm decision depends on, plus the log length (any applied event changes it)."""
    return sha256_text(canonical_json({
        "scope": state.scope.key(), "mode": state.mode.value, "reconciliation": state.reconciliation.value,
        "incidents": list(state.open_incidents), "latches": sorted(f"{s.value}:{k}" for s, k in state.latches),
        "grant": state.armed_grant_digest, "events": len(state.log)}))


def initial_state(scope: AccountScope) -> ControlState:
    if not isinstance(scope, AccountScope):
        raise ValueError("scope must be an AccountScope")
    return ControlState(scope=scope)


def decide_arm(state: ControlState, request: ArmRequest, *, grants: tuple["AutomationGrant", ...],
               now: datetime) -> Union[ArmAccepted, ArmRefused]:
    """Judge an arm request once, live. The outcome is what gets persisted and replayed."""
    out = []
    env = state.scope.environment
    if request.mode is Mode.DISARMED:
        out.append("ARM_TO_DISARMED: use Disarm")
    if not environment_authorized(env):
        out.append(f"ENVIRONMENT_NOT_AUTHORIZED: {env.value}")
    if request.mode in RECONCILED_MODES and state.reconciliation is not Reconciliation.COMPLETE:
        out.append(f"RECONCILIATION_NOT_COMPLETE: {state.reconciliation.value}")
    missing = sorted(set(state.open_incidents) - set(request.acknowledged_incidents))
    if missing and request.mode is not Mode.OBSERVE_ONLY:
        out.append(f"INCIDENTS_NOT_ACKNOWLEDGED: {missing}")
    if request.mode is Mode.DEMO and env is not Environment.DEMO:
        out.append("DEMO_MODE_NEEDS_DEMO_SCOPE")
    if request.mode is Mode.BOUNDED_AUTO:
        grant = _grant(grants, request.grant_digest)
        out += ["GRANT_MISSING: BOUNDED_AUTO needs a recorded AutomationGrant"] if grant is None \
            else grant.validity_problems(state.scope, now)
    elif request.grant_digest is not None:
        out.append("GRANT_UNEXPECTED: only BOUNDED_AUTO arms against a grant")
    if out:
        return ArmRefused(request.mode, request.operator_ref, tuple(out), request.at_utc)
    acknowledged = tuple(i for i in request.acknowledged_incidents if i in state.open_incidents)
    return ArmAccepted(request.mode, request.operator_ref, acknowledged,
                       request.grant_digest if request.mode is Mode.BOUNDED_AUTO else None, request.at_utc,
                       state_basis(state))


def _grant(grants: tuple["AutomationGrant", ...], digest: str | None) -> "AutomationGrant | None":
    return next((g for g in grants if digest is not None and g.digest() == digest), None)


def _incident(state: ControlState, incident_id: str, line: str) -> ControlState:
    incidents = state.open_incidents if incident_id in state.open_incidents else state.open_incidents + (incident_id,)
    return replace(state, mode=Mode.DISARMED, open_incidents=incidents, armed_grant_digest=None,
                   log=state.log + (line,))


def reduce(state: ControlState, event: Event) -> ControlState:
    """Apply one persisted event. Pure and deterministic: it never re-judges a decision."""
    if isinstance(event, Started):
        return replace(state, mode=Mode.DISARMED, reconciliation=Reconciliation.NOT_RUN, armed_grant_digest=None,
                       log=state.log + (f"{event.at_utc} STARTED -> DISARMED",))
    if isinstance(event, ReconciliationObserved):
        line = f"{event.at_utc} RECONCILIATION {event.status.value}"
        state = replace(state, reconciliation=event.status, log=state.log + (line,))
        if event.status is not Reconciliation.COMPLETE and state.mode in RECONCILED_MODES:
            return _incident(state, "reconciliation-lost:" + re.sub(r"[^A-Za-z0-9]", "", event.at_utc),
                             f"{event.at_utc} INCIDENT reconciliation lost in {state.mode.value} -> DISARMED")
        return state
    if isinstance(event, IncidentRaised):
        return _incident(state, event.incident_id, f"{event.at_utc} INCIDENT {event.incident_id}: {event.reason} -> DISARMED")
    if isinstance(event, IncidentAcknowledged):
        return replace(state, open_incidents=tuple(i for i in state.open_incidents if i != event.incident_id),
                       log=state.log + (f"{event.at_utc} ACK {event.incident_id} by {event.operator_ref}",))
    if isinstance(event, ArmAccepted):
        if event.basis != state_basis(state):
            return replace(state, log=state.log + (f"{event.at_utc} ARM {event.mode.value} REFUSED: STALE_DECISION "
                                                   f"(state changed after it was decided)",))
        return replace(state, mode=event.mode, armed_grant_digest=event.grant_digest,
                       open_incidents=tuple(i for i in state.open_incidents if i not in event.acknowledged_incidents),
                       log=state.log + (f"{event.at_utc} ARMED {event.mode.value} by {event.operator_ref}; "
                                        f"acknowledged {list(event.acknowledged_incidents)}",))
    if isinstance(event, ArmRefused):
        return replace(state, log=state.log + (f"{event.at_utc} ARM {event.mode.value} REFUSED: "
                                               f"{'; '.join(event.reasons)}",))
    if isinstance(event, Disarm):
        return replace(state, mode=Mode.DISARMED, armed_grant_digest=None,
                       log=state.log + (f"{event.at_utc} DISARM by {event.operator_ref}: {event.reason}",))
    if isinstance(event, SetLatch):
        return replace(state, latches=state.latches | {(event.scope, event.key)},
                       log=state.log + (f"{event.at_utc} LATCH {event.scope.value}:{event.key} ({event.reason})",))
    if isinstance(event, ClearLatch):
        return replace(state, latches=state.latches - {(event.scope, event.key)},
                       closeouts=frozenset(x for x in state.closeouts if (x[0], x[1]) != (event.scope, event.key)),
                       log=state.log + (f"{event.at_utc} UNLATCH {event.scope.value}:{event.key} by {event.operator_ref}",))
    if isinstance(event, CloseoutAuthorized):
        if (event.scope, event.key) not in state.latches:
            return replace(state, log=state.log + (f"{event.at_utc} CLOSEOUT REFUSED {event.scope.value}:{event.key}: "
                                                   f"no such active latch",))
        return replace(state, closeouts=state.closeouts | {(event.scope, event.key, event.expires_at_utc)},
                       log=state.log + (f"{event.at_utc} CLOSEOUT AUTHORIZED {event.scope.value}:{event.key} "
                                        f"by {event.operator_ref}",))
    raise TypeError(f"unknown control event {type(event).__name__}")


def replay(scope: AccountScope, events: tuple[Event, ...]) -> ControlState:
    """Rebuild state from persisted events, then apply an implied restart. The result is DISARMED, with latches,
    closeout authorizations and open incidents kept."""
    state = initial_state(scope)
    for event in events:
        state = reduce(state, event)
    return reduce(state, Started(at_utc=events[-1].at_utc if events else "1970-01-01T00:00:00+00:00"))


def _matching_latches(state: ControlState, *, venue: str, strategy_id: str, market_ticker: str) -> list[tuple]:
    keys = {LatchScope.GLOBAL: "*", LatchScope.VENUE: latch_key(LatchScope.VENUE, venue),
            LatchScope.STRATEGY: latch_key(LatchScope.STRATEGY, strategy_id),
            LatchScope.MARKET: latch_key(LatchScope.MARKET, market_ticker)}
    return sorted(latch for latch in state.latches if keys[latch[0]] == latch[1])


def action_problems(state: ControlState, action: ControlAction, *, venue: str, strategy_id: str,
                    market_ticker: str, now: datetime, grants: tuple["AutomationGrant", ...] = ()) -> list[str]:
    """Why the controller blocks `action` now (empty: it permits it). The risk gate and journal still decide."""
    if not isinstance(action, ControlAction):
        raise ValueError("action must be a ControlAction")
    out = []
    if not environment_authorized(state.scope.environment):
        out.append(f"ENVIRONMENT_NOT_AUTHORIZED: {state.scope.environment.value}")
    if action in (ControlAction.READ, ControlAction.CANCEL_OWNED):
        return out  # reconciliation reads and emergency cancels of our own orders, in any mode
    if state.mode not in SENDING_MODES:
        out.append(f"MODE_DOES_NOT_SEND: {state.mode.value}")
    if state.reconciliation is not Reconciliation.COMPLETE:
        out.append(f"RECONCILIATION_NOT_COMPLETE: {state.reconciliation.value}")
    if state.open_incidents:
        out.append(f"OPEN_INCIDENTS: {list(state.open_incidents)}")
    if state.mode is Mode.BOUNDED_AUTO:
        grant = _grant(grants, state.armed_grant_digest)
        out += ["GRANT_MISSING: the armed grant is not recorded"] if grant is None \
            else grant.validity_problems(state.scope, now)
    latched = _matching_latches(state, venue=venue, strategy_id=strategy_id, market_ticker=market_ticker)
    if action is ControlAction.NEW_RISK and latched:
        out.append(f"NEW_RISK_LATCHED: {[f'{s.value}:{k}' for s, k in latched]}")
    live = {(sc, k) for sc, k, exp in state.closeouts if now < parse_utc_text(exp)}
    uncovered = [latch for latch in latched if latch not in live]
    if action is ControlAction.REDUCE and state.mode in AUTOMATED_MODES and uncovered:
        out.append(f"REDUCTION_UNDER_LATCH_NEEDS_CLOSEOUT: {[f'{s.value}:{k}' for s, k in uncovered]}")
    if action is ControlAction.CLOSEOUT and (not latched or uncovered):
        out.append("CLOSEOUT_NOT_AUTHORIZED: a closeout needs a latch and an explicit CloseoutAuthorized for it")
    return out


# ------------------------------------------------------------------ automated-policy grants


@dataclass(frozen=True)
class GrantLimits:
    """Exact limits a grant binds, in dollars. There are no defaults."""

    max_order_cost: Decimal
    max_event_exposure: Decimal
    max_total_exposure: Decimal
    max_daily_turnover: Decimal
    max_daily_loss: Decimal
    max_drawdown: Decimal

    def __post_init__(self) -> None:
        for name in ("max_order_cost", "max_event_exposure", "max_total_exposure", "max_daily_turnover",
                     "max_daily_loss", "max_drawdown"):
            value = exact_decimal(getattr(self, name), name=name)
            if value < 0:
                raise ExactValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class GrantUsage:
    """Cumulative usage under one grant, computed from persisted records (journal reservations, fills and
    settlements), never process memory. It is anchored to one grant, one event and one UTC day. None is unknown,
    and unknown blocks."""

    grant_digest: str
    event_key: str
    utc_day: str  # YYYY-MM-DD (UTC) the turnover and loss figures cover
    as_of_utc: str
    event_exposure: Decimal | None
    total_exposure: Decimal | None
    turnover_today: Decimal | None
    realized_loss_today: Decimal | None  # a positive number is a loss
    drawdown: Decimal | None  # a positive number is below peak

    def __post_init__(self) -> None:
        if not isinstance(self.grant_digest, str) or not _HASH.fullmatch(self.grant_digest):
            raise ValueError("grant_digest must be a SHA-256 hex digest")
        _check_ref("event_key", self.event_key)
        if not isinstance(self.utc_day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.utc_day):
            raise ValueError("utc_day must be YYYY-MM-DD")
        _check_time(self.as_of_utc)
        for name in ("event_exposure", "total_exposure", "turnover_today", "realized_loss_today", "drawdown"):
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
    venue: str
    strategy_id: str
    strategy_version: str
    model_hash: str
    policy_hash: str
    risk_policy_version: str
    fee_schedule_version: str
    profile_version: str
    universe: frozenset[str]  # exact market tickers, or series prefixes ending in "*"
    allowed_kinds: frozenset[IntentKind]
    limits: GrantLimits
    issued_at_utc: str
    expires_at_utc: str
    issuer_ref: str  # the EXECUTION_PLAN entry recording the owner's grant
    schema: str = GRANT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GRANT_SCHEMA:
            raise ValueError(f"unknown grant schema {self.schema!r}")
        if not isinstance(self.environment, Environment):
            raise ValueError("environment must be an Environment")
        for name in ("scope_key", "venue", "strategy_id", "strategy_version", "risk_policy_version",
                     "fee_schedule_version", "profile_version", "issuer_ref"):
            _check_ref(name, getattr(self, name))
        object.__setattr__(self, "venue", self.venue.lower())
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
        _check_time(self.issued_at_utc)
        if parse_utc_text(self.expires_at_utc) <= parse_utc_text(self.issued_at_utc):
            raise ValueError("a grant must expire after it is issued")

    def to_dict(self) -> dict:
        lim = self.limits
        return {"schema": self.schema, "environment": self.environment.value, "scope_key": self.scope_key,
                "venue": self.venue, "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
                "model_hash": self.model_hash, "policy_hash": self.policy_hash,
                "risk_policy_version": self.risk_policy_version, "fee_schedule_version": self.fee_schedule_version,
                "profile_version": self.profile_version, "universe": sorted(self.universe),
                "allowed_kinds": sorted(k.value for k in self.allowed_kinds),
                "limits": {"max_order_cost": lim.max_order_cost, "max_event_exposure": lim.max_event_exposure,
                           "max_total_exposure": lim.max_total_exposure, "max_daily_turnover": lim.max_daily_turnover,
                           "max_daily_loss": lim.max_daily_loss, "max_drawdown": lim.max_drawdown},
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


def turnover_increment(intent: OrderIntent) -> Decimal:
    """Turnover an intent adds. ENTRY: its full cost ceiling. REDUCTION: the notional sold
    (quantity × limit) plus its fee ceiling, because a sale's turnover is not its fees."""
    if intent.kind is IntentKind.ENTRY:
        return intent.max_total_cost
    return exact_product(intent.quantity, intent.limit_price) + intent.max_total_cost


def grant_problems(grant: AutomationGrant, intent: OrderIntent, *, armed_grant_digest: str | None, venue: str,
                   event_key: str, usage: GrantUsage, model_hash: str, policy_hash: str, now: datetime) -> list[str]:
    """Why `intent` falls outside `grant` (empty: inside it). `grant` must be the one the controller is armed
    against. A change to any bound version or hash, a limit breach, or unanchored, stale or unknown usage is outside."""
    out = grant.validity_problems(intent.scope, now)
    if armed_grant_digest != grant.digest():
        out.append("GRANT_NOT_ARMED: the controller is not armed against this grant")
    if venue.lower() != grant.venue:
        out.append("GRANT_VENUE_MISMATCH")
    for name in ("strategy_id", "strategy_version", "risk_policy_version", "fee_schedule_version", "profile_version"):
        if getattr(intent, name) != getattr(grant, name):
            out.append(f"GRANT_{name.upper()}_CHANGED")
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
    # Usage must be about this grant, this event, today, and fresh.
    at = now.astimezone(timezone.utc)
    if usage.grant_digest != grant.digest():
        out.append("GRANT_USAGE_FOR_ANOTHER_GRANT")
    if usage.event_key != event_key:
        out.append("GRANT_USAGE_FOR_ANOTHER_EVENT")
    if usage.utc_day != at.date().isoformat():
        out.append("GRANT_USAGE_FOR_ANOTHER_DAY")
    as_of = parse_utc_text(usage.as_of_utc)
    if as_of > at or at - as_of > USAGE_MAX_AGE:
        out.append("GRANT_USAGE_STALE_OR_FUTURE")
    lim = grant.limits
    if usage.turnover_today is None:
        out.append("GRANT_USAGE_UNKNOWN: turnover")
    elif usage.turnover_today + turnover_increment(intent) > lim.max_daily_turnover:
        out.append("GRANT_TURNOVER")
    if intent.kind is IntentKind.ENTRY:  # loss limits stop new risk; they never trap an exit
        if usage.realized_loss_today is None or usage.drawdown is None:
            out.append("GRANT_USAGE_UNKNOWN: losses")
        else:
            if usage.realized_loss_today >= lim.max_daily_loss:
                out.append("GRANT_DAILY_LOSS_REACHED")
            if usage.drawdown >= lim.max_drawdown:
                out.append("GRANT_DRAWDOWN_REACHED")
    if intent.kind is IntentKind.ENTRY:
        if usage.event_exposure is None or usage.total_exposure is None:
            out.append("GRANT_USAGE_UNKNOWN: exposure")
        else:
            if usage.event_exposure + intent.max_total_cost > lim.max_event_exposure:
                out.append("GRANT_EVENT_EXPOSURE")
            if usage.total_exposure + intent.max_total_cost > lim.max_total_exposure:
                out.append("GRANT_TOTAL_EXPOSURE")
    return out
