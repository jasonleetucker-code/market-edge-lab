"""Execution contracts (ADR 0043): exact, typed values every execution module shares. Pure data.

Nothing here signs, sends, reads an account or touches a store.

- **Exact numbers.** Prices, quantities and money are `Decimal` values from `str`, `int` or `Decimal`,
  never `float` or `bool`. NaN and infinity are refused, and off-grid values are refused against a `Grid`.
- **Closed vocabularies.** Environment, side, action, time in force and intent kind. Only the
  documented combinations are valid; a flip is never one.
- **Layered identity.**
  - `OrderIntent.intent_key` is the business key the strategy supplies.
  - `OrderIntent.digest()` is the content identity: the same key with a different digest is a
    conflict, never an update.
  - `client_order_id()` is derived from the digest.
  - An `ApprovalGrant` binds to one digest, one account scope and an expiry.
- **Missing is not zero.** There is no default price, quantity, fee or expiry.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

INTENT_SCHEMA = "edge-lab-execution-intent/1"
APPROVAL_SCHEMA = "edge-lab-execution-approval/1"
_CLIENT_ID_NAMESPACE = uuid.UUID("6f1d6a5e-6c1b-4d8e-9a59-0d7c3f0e8b21")  # fixed: ids are reproducible
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,127}")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")


class Environment(str, Enum):
    FIXTURE = "FIXTURE"  # fake transport and a disposable store: the only authorized environment
    DEMO = "DEMO"  # the venue's mock-funds environment: disabled until separately approved
    PRODUCTION = "PRODUCTION"  # real money: disabled


# The environments whose egress is authorized. The canonical and only owner: every transport checks
# this, and `tests/invariants/test_execution_boundary.py` pins it to the authorization phrase in
# docs/EXECUTION_PLAN.md. Adding DEMO is a reviewed change made in the same PR as a recorded owner
# approval. PRODUCTION is not added by this campaign.
AUTHORIZED_ENVIRONMENTS: frozenset[Environment] = frozenset({Environment.FIXTURE})


def environment_authorized(environment: Environment) -> bool:
    return environment in AUTHORIZED_ENVIRONMENTS


class Side(str, Enum):
    YES = "yes"
    NO = "no"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TimeInForce(str, Enum):
    GOOD_TILL_CANCELED = "good_till_canceled"
    IMMEDIATE_OR_CANCEL = "immediate_or_cancel"
    FILL_OR_KILL = "fill_or_kill"


class IntentKind(str, Enum):
    ENTRY = "ENTRY"  # buy contracts of `side` to open or add: new risk
    REDUCTION = "REDUCTION"  # sell contracts of `side` already held: reduce-only, never a flip


class ExactValueError(ValueError):
    """A value that is not an exact, finite number of the expected kind."""


def exact_decimal(value: object, *, name: str) -> Decimal:
    """`value` as a finite Decimal. Accepts Decimal, int or a numeric str; refuses bool, float,
    NaN, infinity and anything else. A float is refused even when it looks round: its binary
    value is already inexact."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ExactValueError(f"{name} must be an exact Decimal, int or numeric string, not {type(value).__name__}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", text):
            raise ExactValueError(f"{name} is not a plain decimal string: {value!r}")
        try:
            d = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - the pattern already excludes this
            raise ExactValueError(f"{name} is not a decimal: {value!r}") from exc
    else:
        raise ExactValueError(f"{name} must be a Decimal, int or numeric string, not {type(value).__name__}")
    if not d.is_finite():
        raise ExactValueError(f"{name} must be finite, not {d}")
    return d


def decimal_text(value: Decimal) -> str:
    """A canonical, exponent-free text for a finite Decimal: equal values give equal text
    (`Decimal("1.50")` and `Decimal("1.5")` both give `"1.5"`)."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ExactValueError(f"not a finite Decimal: {value!r}")
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text


@dataclass(frozen=True)
class Grid:
    """An inclusive range with a step: a market's price tick or quantity increment. The venue
    documents it per market (conformance pack); there is no default grid."""

    step: Decimal
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        for f in ("step", "minimum", "maximum"):
            object.__setattr__(self, f, exact_decimal(getattr(self, f), name=f"grid {f}"))
        if self.step <= 0 or self.minimum > self.maximum:
            raise ExactValueError(f"invalid grid: step {self.step}, range [{self.minimum}, {self.maximum}]")
        if (self.minimum % self.step) != 0 or (self.maximum % self.step) != 0:
            raise ExactValueError("grid bounds must lie on the grid")

    def check(self, value: object, *, name: str) -> Decimal:
        """`value` if it is exact, in range and on the grid; otherwise raises with why."""
        d = exact_decimal(value, name=name)
        if d < self.minimum or d > self.maximum:
            raise ExactValueError(f"{name} {d} is outside [{self.minimum}, {self.maximum}]")
        if d % self.step != 0:
            raise ExactValueError(f"{name} {d} is off the {self.step} grid")
        return d


def utc_text(value: datetime) -> str:
    """An aware datetime as ISO-8601 UTC text. Naive datetimes are refused: their zone is unknown."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"a timezone-aware datetime is required, not {value!r}")
    return value.astimezone(timezone.utc).isoformat()


def parse_utc_text(text: str) -> datetime:
    """Parse text written by `utc_text` (or any aware ISO-8601). Naive or malformed text raises."""
    try:
        at = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not an ISO-8601 time: {text!r}") from exc
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"time has no zone: {text!r}")
    return at.astimezone(timezone.utc)


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no spaces, Decimals as canonical text, enums as values."""

    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return decimal_text(o)
        if isinstance(o, Enum):
            return o.value
        raise TypeError(f"not serializable: {type(o).__name__}")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default, ensure_ascii=True,
                      allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AccountScope:
    """Which account an action is for. `account_ref` is an opaque local label (never a key, a
    member id or a credential). `subaccount` is the venue's subaccount number, or None for the
    primary account. The scope is part of every digest, so an approval for one account can never
    authorize another."""

    environment: Environment
    account_ref: str
    subaccount: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.environment, Environment):
            raise ValueError("environment must be an Environment")
        if not isinstance(self.account_ref, str) or not _KEY.fullmatch(self.account_ref):
            raise ValueError(f"account_ref must be a short opaque label, not {self.account_ref!r}")
        if self.subaccount is not None and (isinstance(self.subaccount, bool) or not isinstance(self.subaccount, int)
                                            or self.subaccount < 0):
            raise ValueError(f"subaccount must be a non-negative int or None, not {self.subaccount!r}")

    def key(self) -> str:
        sub = "primary" if self.subaccount is None else str(self.subaccount)
        return f"{self.environment.value}:{self.account_ref}:{sub}"

    def to_dict(self) -> dict[str, Any]:
        return {"environment": self.environment.value, "account_ref": self.account_ref,
                "subaccount": self.subaccount}


@dataclass(frozen=True)
class OrderIntent:
    """One business decision to place one ordinary limit order. Immutable once built.

    Semantics:
    - `limit_price` is dollars per contract of `side`: a buy's maximum, a sell's minimum.
    - `max_total_cost` is the most cash the order may consume, fees included.
      - ENTRY: it must cover quantity × limit_price.
      - REDUCTION: it bounds fees only, since a sale's proceeds are not cost.
    - ENTRY is BUY and never reduce-only. REDUCTION is SELL and always reduce-only. There is no flip.
    - `price_grid` / `quantity_grid` come from the conformance profile for this market. The intent
      refuses off-grid values at construction.
    - `evidence` names the decision evidence (ticket id, model and book snapshot ids). It is part of
      the digest.
    """

    intent_key: str
    strategy_id: str
    strategy_version: str
    scope: AccountScope
    market_ticker: str
    kind: IntentKind
    side: Side
    action: Action
    quantity: Decimal
    limit_price: Decimal
    time_in_force: TimeInForce
    max_total_cost: Decimal
    expires_at_utc: str
    price_grid: Grid
    quantity_grid: Grid
    profile_version: str
    risk_policy_version: str
    fee_schedule_version: str
    reduce_only: bool
    post_only: bool = False
    evidence: tuple[str, ...] = ()
    schema: str = INTENT_SCHEMA

    def __post_init__(self) -> None:
        for name in ("intent_key", "strategy_id", "strategy_version", "profile_version", "risk_policy_version",
                     "fee_schedule_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _KEY.fullmatch(value):
                raise ValueError(f"{name} must be a non-empty short identifier, not {value!r}")
        if self.schema != INTENT_SCHEMA:
            raise ValueError(f"unknown intent schema {self.schema!r}")
        if not isinstance(self.scope, AccountScope):
            raise ValueError("scope must be an AccountScope")
        if not isinstance(self.market_ticker, str) or not _TICKER.fullmatch(self.market_ticker):
            raise ValueError(f"market_ticker is not a venue ticker: {self.market_ticker!r}")
        for name, enum in (("kind", IntentKind), ("side", Side), ("action", Action), ("time_in_force", TimeInForce)):
            if not isinstance(getattr(self, name), enum):
                raise ValueError(f"{name} must be a {enum.__name__}")
        for name in ("reduce_only", "post_only"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")
        if not isinstance(self.price_grid, Grid) or not isinstance(self.quantity_grid, Grid):
            raise ValueError("price_grid and quantity_grid must be Grids from the conformance profile")
        object.__setattr__(self, "quantity", self.quantity_grid.check(self.quantity, name="quantity"))
        if self.quantity <= 0:
            raise ExactValueError("quantity must be positive")
        object.__setattr__(self, "limit_price", self.price_grid.check(self.limit_price, name="limit_price"))
        if not 0 < self.limit_price < 1:
            raise ExactValueError(f"limit_price {self.limit_price} must be strictly between 0 and 1 dollar")
        object.__setattr__(self, "max_total_cost", exact_decimal(self.max_total_cost, name="max_total_cost"))
        if self.max_total_cost < 0:
            raise ExactValueError("max_total_cost must not be negative")
        parse_utc_text(self.expires_at_utc)
        if not isinstance(self.evidence, tuple) or not all(isinstance(e, str) and e for e in self.evidence):
            raise ValueError("evidence must be a tuple of non-empty strings")
        if self.kind is IntentKind.ENTRY:
            if self.action is not Action.BUY or self.reduce_only:
                raise ValueError("an ENTRY is a BUY and is never reduce-only")
            if self.max_total_cost < self.quantity * self.limit_price:
                raise ExactValueError(f"max_total_cost {self.max_total_cost} understates quantity × limit "
                                      f"{self.quantity * self.limit_price}")
        else:
            if self.action is not Action.SELL or not self.reduce_only:
                raise ValueError("a REDUCTION is a SELL and is always reduce-only (no flip)")
        if self.post_only and self.time_in_force is not TimeInForce.GOOD_TILL_CANCELED:
            raise ValueError("post_only requires good_till_canceled")

    def expires_at(self) -> datetime:
        return parse_utc_text(self.expires_at_utc)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, AccountScope):
                value = value.to_dict()
            elif isinstance(value, Grid):
                value = {"step": value.step, "minimum": value.minimum, "maximum": value.maximum}
            elif isinstance(value, tuple):
                value = list(value)
            out[f.name] = value
        return out

    def canonical(self) -> str:
        return canonical_json(self.to_dict())

    def digest(self) -> str:
        """The content identity: every field, the scope and the grids included."""
        return sha256_text(self.canonical())

    def client_order_id(self) -> str:
        """The client order id for this intent: a UUID derived from the digest, the same on every attempt.
        A repeated id lets the venue refuse a duplicate. It is not proof that only one order exists:
        an ambiguous send is reconciled before anything is retried."""
        return str(uuid.uuid5(_CLIENT_ID_NAMESPACE, self.digest()))


class ApprovalMethod(str, Enum):
    HUMAN = "HUMAN"  # the owner approved this exact intent in the private interface
    POLICY = "POLICY"  # a separately approved bounded-automation policy (none exists; package N/T)


@dataclass(frozen=True)
class ApprovalGrant:
    """Permission to send exactly one intent: bound to its digest, its scope and an expiry.
    A changed price, size, account, strategy or expiry is a different digest and needs a new grant."""

    intent_digest: str
    scope_key: str
    method: ApprovalMethod
    approver_ref: str  # an opaque local label, never a credential
    approved_at_utc: str
    expires_at_utc: str
    nonce: str  # single use: the journal refuses a second use
    policy_ref: str | None = None
    schema: str = APPROVAL_SCHEMA

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.intent_digest or ""):
            raise ValueError("intent_digest must be a SHA-256 hex digest")
        if not isinstance(self.method, ApprovalMethod):
            raise ValueError("method must be an ApprovalMethod")
        for name in ("scope_key", "approver_ref", "nonce"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        if (self.method is ApprovalMethod.POLICY) != bool(self.policy_ref):
            raise ValueError("policy_ref is required for, and only for, a POLICY approval")
        if self.schema != APPROVAL_SCHEMA:
            raise ValueError(f"unknown approval schema {self.schema!r}")
        if parse_utc_text(self.expires_at_utc) <= parse_utc_text(self.approved_at_utc):
            raise ValueError("an approval must expire after it is granted")

    def problems(self, intent: OrderIntent, *, now: datetime) -> list[str]:
        """Why this grant does not authorize `intent` at `now` (empty: it binds). Nonce reuse is the
        journal's check, not this one."""
        out = []
        if self.intent_digest != intent.digest():
            out.append("APPROVAL_DIGEST_MISMATCH: the intent changed after approval")
        if self.scope_key != intent.scope.key():
            out.append("APPROVAL_SCOPE_MISMATCH: approved for another account or environment")
        at = now.astimezone(timezone.utc)
        if at < parse_utc_text(self.approved_at_utc):
            out.append("APPROVAL_FROM_FUTURE: granted after now (clock disagreement)")
        if at >= parse_utc_text(self.expires_at_utc):
            out.append("APPROVAL_EXPIRED")
        if at >= intent.expires_at():
            out.append("INTENT_EXPIRED")
        return out
