"""Versioned venue fee schedules for the opportunity engine (Gate 5).

A fee schedule is data plus a deterministic cost function. Schedules are replaced by
adding a new `schedule_id`, never by editing an existing one, so every opportunity
names the exact schedule that priced it.

`status` is the schedule's *base* status: what was known when the schedule was declared.
Verification is evidence that arrives later, so it lives in separate, dated
`FeeVerificationRecord`s (ADR 0017), and `verification_at(schedule, as_of, native_id)`
gives the point-in-time view:
- an unverified schedule may price research opportunities, but no net-profitability claim
  may rest on it (`claim_basis` NONE, `Opportunity.claimable` false);
- `CONSERVATIVE_BOUND` means the coefficient, series multiplier, scheduled changes and
  rounding mechanics are verified from primary sources, for a direct-member account. The
  real debit of an order is proven to be below the schedule's cost plus a documented
  per-contract rounding allowance (`rounding_allowance_per_contract`). A net result minus
  that allowance is a lower bound (`claim_adjusted_net`), never an exact figure;
- `EXACT` additionally needs the account type verified and an exact cost model.

The verification is a record beside the schedule, not a new schedule id, because the cost
math does not change and shadow accounts pin their `fee_schedule_id` when opened. A fee
schedule is keyed by venue and never prices another venue (`schedule_for`).

Nothing here places orders; costs are computed for simulation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any, Iterable, Mapping

from . import fees
from .freshness import parse_utc

SIX_DP = Decimal("0.000001")
CENTICENT = Decimal("0.0001")
CENT = Decimal("0.01")
PRICE_GRID = Decimal("0.0001")


class FeeScheduleStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED_CURRENT_SCHEDULE = "UNVERIFIED_CURRENT_SCHEDULE"
    UNSUPPORTED = "UNSUPPORTED"


class ClaimBasis(str, Enum):
    """What kind of net-result claim the fee evidence supports."""

    NONE = "NONE"  # no net-profitability claim may rest on this fee
    CONSERVATIVE_BOUND = "CONSERVATIVE_BOUND"  # net minus the rounding allowance is a lower bound
    EXACT = "EXACT"  # every component verified and the cost is the exact venue debit

    @classmethod
    def weakest(cls, bases) -> "ClaimBasis":
        """The weakest basis among `bases` (NONE if any is NONE or unknown; NONE if empty)."""
        order = {cls.NONE: 0, cls.CONSERVATIVE_BOUND: 1, cls.EXACT: 2}
        found = [cls(b) if b in {m.value for m in cls} else cls.NONE for b in bases]
        return min(found, key=order.__getitem__) if found else cls.NONE


class VerificationComponent(str, Enum):
    COEFFICIENT = "COEFFICIENT"
    SERIES_MULTIPLIER = "SERIES_MULTIPLIER"
    SCHEDULED_CHANGES = "SCHEDULED_CHANGES"
    ROUNDING_FOR_ACCOUNT_TYPE = "ROUNDING_FOR_ACCOUNT_TYPE"
    ACCOUNT_TYPE = "ACCOUNT_TYPE"
    MAKER_FEES = "MAKER_FEES"


class ComponentState(str, Enum):
    VERIFIED = "VERIFIED"
    OWNER_ATTESTED = "OWNER_ATTESTED"  # the owner's statement; not checked against the venue
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CostModel(str, Enum):
    """How a schedule's cost relates to the venue's real cash debit."""

    CONSERVATIVE_UPPER_BOUND = "CONSERVATIVE_UPPER_BOUND"
    EXACT = "EXACT"


@dataclass(frozen=True)
class FeeQuote:
    """The cost of buying `contracts` at `price` under one schedule (taker, no rebates)."""

    schedule_id: str
    status: FeeScheduleStatus
    contracts: int
    price: Decimal
    fee: Decimal  # trade fee for the whole quantity
    total_cost: Decimal  # cash that leaves the balance, fee included
    cost_per_contract: Decimal


def valid_price(price: Decimal) -> bool:
    """A binary-contract price strictly inside (0, 1) on the 1/100-cent grid. Non-finite
    (NaN, infinity) or non-Decimal values are invalid, never an exception."""
    if not isinstance(price, Decimal) or not price.is_finite():
        return False
    return Decimal("0") < price < Decimal("1") and price == price.quantize(PRICE_GRID)


@dataclass(frozen=True)
class QuadraticTakerSchedule:
    """Kalshi-style quadratic taker fee.

    model fee = multiplier * coefficient * C * P * (1 - P); trade fee = ceil to $0.000001;
    cash change = floor to the cent of (-P*C - trade fee) (non-direct member). Taker only:
    no maker fills, rebates or rounding refunds are assumed (they can only lower cost).
    """

    schedule_id: str
    venue: str
    coefficient: Decimal
    multiplier: Decimal
    status: FeeScheduleStatus  # base status, before any dated verification record
    evidence: str
    checked_at_utc: str
    cost_model: CostModel = CostModel.CONSERVATIVE_UPPER_BOUND

    @staticmethod
    def _scope(venue: str, native_id: str | None) -> str | None:
        if venue != "kalshi" or not native_id:
            return None
        return native_id.split("-", 1)[0] or None

    def scope_of(self, native_id: str | None) -> str | None:
        """The fee scope of a native market id. Kalshi fees are set per series, and a
        Kalshi market ticker starts with its series ticker. Other venues: unknown."""
        return self._scope(self.venue, native_id)

    def taker_buy(self, contracts: int, price: Decimal) -> FeeQuote:
        if not isinstance(contracts, int) or isinstance(contracts, bool) or contracts <= 0:
            raise ValueError("contracts must be a positive integer")
        p = Decimal(str(price))
        if not valid_price(p):
            raise ValueError(f"{p} is not a valid binary-contract price")
        model_fee = self.multiplier * self.coefficient * contracts * p * (1 - p)
        trade_fee = model_fee.quantize(SIX_DP, rounding=ROUND_CEILING)
        aligned = (-(p * contracts) - trade_fee).quantize(CENT, rounding=ROUND_FLOOR)
        total = -aligned
        return FeeQuote(self.schedule_id, self.status, contracts, p, trade_fee, total, total / contracts)


# The EXP-001 frozen fee model (src/edge_lab/fees.py, hash-pinned). Re-checked 2026-09-23
# 02:20 UTC: the public API reports KXHIGHNY fee_type "quadratic", fee_multiplier 1 and no
# scheduled fee changes; docs.kalshi.com "Fee Rounding" confirms the rounding. The 0.07
# coefficient could not be read from a primary source (the fee-schedule PDF and fee pages
# answered HTTP 429 to automated requests), so the schedule stays UNVERIFIED.
KALSHI_QUADRATIC_TAKER_V1 = QuadraticTakerSchedule(
    schedule_id="kalshi-quadratic-taker-v1",
    venue="kalshi",
    coefficient=fees.QUADRATIC_TAKER_COEFFICIENT,
    multiplier=Decimal("1"),
    status=FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE,
    evidence=(
        "experiments/EXP-001-kxhighny-nws-vs-market/gate3/evidence/kalshi_docs_fee_rounding.html "
        "(0.07 worked example, captured 2026-09-22); KXHIGHNY series fee_type=quadratic, "
        "fee_multiplier=1 (API, 2026-09-23T02:20Z); /series/fee_changes empty; fee-schedule PDF "
        "not retrievable (HTTP 429)"
    ),
    checked_at_utc="2026-09-23T02:20:00Z",
)

FEE_SCHEDULES: dict[str, QuadraticTakerSchedule] = {
    KALSHI_QUADRATIC_TAKER_V1.schedule_id: KALSHI_QUADRATIC_TAKER_V1,
}


def get_fee_schedule(schedule_id: str) -> QuadraticTakerSchedule:
    try:
        return FEE_SCHEDULES[schedule_id]
    except KeyError:
        raise KeyError(f"unknown fee schedule {schedule_id!r}") from None


# --------------------------------------------------------------------------- verification

@dataclass(frozen=True)
class ComponentEvidence:
    component: VerificationComponent
    state: ComponentState
    evidence: str
    detail: str


@dataclass(frozen=True)
class FeeVerificationRecord:
    """Dated verification evidence for one schedule and a set of fee scopes (series).

    `knowledge_time_utc` is when every component was in hand; before it the record did not
    exist, so it never changes what a decision recorded earlier could have known.
    `account_type` is the account the rounding component was verified for.
    `rounding_allowance_per_contract` bounds, per contract, how much a real order split into
    several fills can cost above the schedule's single-fill cost (ADR 0017).
    `applies_from_utc` is the effective date of the primary source: trades before it are not
    covered. `recheck_by_utc` bounds how long the "no scheduled change" check is trusted;
    after it the record stops supporting claims until a new record is added ("stale is not
    current").
    """

    verification_id: str
    schedule_id: str
    venue: str
    scope: tuple[str, ...]
    knowledge_time_utc: str
    applies_from_utc: str
    recheck_by_utc: str
    components: tuple[ComponentEvidence, ...]
    account_type: str = "direct"
    rounding_allowance_per_contract: Decimal | None = None

    def component(self, component: VerificationComponent) -> ComponentEvidence:
        for c in self.components:
            if c.component is component:
                return c
        raise KeyError(component.value)

    @property
    def full_schedule_verified(self) -> bool:
        states = {c.component: c.state for c in self.components}
        return all(states.get(c) in (ComponentState.VERIFIED, ComponentState.NOT_APPLICABLE)
                   for c in VerificationComponent)

    def claim_basis(self, cost_model: CostModel) -> ClaimBasis:
        core = (VerificationComponent.COEFFICIENT, VerificationComponent.SERIES_MULTIPLIER,
                VerificationComponent.SCHEDULED_CHANGES, VerificationComponent.ROUNDING_FOR_ACCOUNT_TYPE)
        if not all(self.component(c).state is ComponentState.VERIFIED for c in core):
            return ClaimBasis.NONE
        if cost_model is CostModel.EXACT and self.full_schedule_verified:
            return ClaimBasis.EXACT
        # The bound is proven only for a direct member (the non-direct bound is loose, and an
        # FCM may add its own fees, PDF p.3), with a stated per-contract rounding allowance.
        account = self.component(VerificationComponent.ACCOUNT_TYPE).state
        if (cost_model is CostModel.CONSERVATIVE_UPPER_BOUND and self.account_type == "direct"
                and account in (ComponentState.VERIFIED, ComponentState.OWNER_ATTESTED)
                and self.rounding_allowance_per_contract is not None):
            return ClaimBasis.CONSERVATIVE_BOUND
        return ClaimBasis.NONE


@dataclass(frozen=True)
class FeeVerificationState:
    """The point-in-time verification view of a schedule for one fee scope."""

    schedule_id: str
    status: FeeScheduleStatus
    claim_basis: ClaimBasis
    verification_id: str | None
    full_schedule_verified: bool
    detail: str
    rounding_allowance_per_contract: Decimal | None = None

    @property
    def claimable(self) -> bool:
        return self.claim_basis is not ClaimBasis.NONE

    def ledger_fields(self) -> dict[str, Any]:
        """Fee fields carried on shadow decisions and fills. Before any verification record
        applies they are exactly the three legacy keys, so entries recorded (or rebuilt) for
        that period are byte-identical to what earlier code wrote."""
        out: dict[str, Any] = {"fee_schedule_id": self.schedule_id, "fee_status": self.status.value,
                               "claimable": self.claimable}
        if self.verification_id is not None:
            out.update(claim_basis=self.claim_basis.value, fee_verification_id=self.verification_id,
                       claim_allowance_per_contract=_s(self.rounding_allowance_per_contract))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"schedule_id": self.schedule_id, "status": self.status.value, "claimable": self.claimable,
                "claim_basis": self.claim_basis.value, "verification_id": self.verification_id,
                "full_schedule_verified": self.full_schedule_verified, "detail": self.detail,
                "claim_allowance_per_contract": _s(self.rounding_allowance_per_contract)}


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def claim_adjusted_net(net: Decimal, contracts: Decimal | int, state: FeeVerificationState) -> Decimal | None:
    """The net result a claim may use: None when no claim is possible; under
    CONSERVATIVE_BOUND, the recorded net minus the rounding allowance for every contract."""
    if not state.claimable:
        return None
    allowance = state.rounding_allowance_per_contract or Decimal(0)
    if state.claim_basis is ClaimBasis.CONSERVATIVE_BOUND and state.rounding_allowance_per_contract is None:
        return None
    return net - allowance * Decimal(contracts)


_EVIDENCE_DIR = "experiments/EXP-001-kxhighny-nws-vs-market/fee_verification"

# Evidence: the owner-supplied Kalshi fee-schedule PDF (received 2026-09-23T12:54:30Z,
# "Last updated and effective: July 7, 2026"), the public series and fee-change API
# captures and the Fee Rounding docs page, all under `_EVIDENCE_DIR` (MANIFEST.json,
# VERIFICATION.md). The record is complete at the last capture (fill granularity), 2026-09-23T13:39:48Z.
KALSHI_KXHIGHNY_VERIFICATION_2026_09_23 = FeeVerificationRecord(
    verification_id="kalshi-kxhighny-fee-verification-2026-09-23",
    schedule_id="kalshi-quadratic-taker-v1",
    venue="kalshi",
    scope=("KXHIGHNY",),
    knowledge_time_utc="2026-09-23T13:39:48Z",
    applies_from_utc="2026-07-07T00:00:00-04:00",
    recheck_by_utc="2026-10-23T13:39:48Z",
    account_type="direct",
    # A direct member's order of C contracts fills in at most 100*C fills (minimum granularity
    # 0.01 contracts, docs Fixed-Point Representation). Each fill adds under $0.000001 of fee
    # rounding and under $0.0001 of balance rounding, and rebates only lower that. So the real
    # debit is below the frozen single-fill cost + $0.0101 per contract, whatever the price
    # grid and even if a rebate cap applies (ADR 0017; tests/test_fee_verification.py).
    rounding_allowance_per_contract=Decimal("0.0101"),
    components=(
        ComponentEvidence(VerificationComponent.COEFFICIENT, ComponentState.VERIFIED,
                          f"{_EVIDENCE_DIR}/kalshi-fee-schedule_effective-2026-07-07_received-2026-09-23.pdf p.2",
                          "general taker fee = round up(M x 0.07 x C x P x (1-P)), effective July 7, 2026"),
        ComponentEvidence(VerificationComponent.SERIES_MULTIPLIER, ComponentState.VERIFIED,
                          f"PDF pp.6-11 (KXHIGHNY not in Non-Standard Fees); "
                          f"{_EVIDENCE_DIR}/api_series_KXHIGHNY_2026-09-23T131747Z.json",
                          "general schedule, taker multiplier 1 (API fee_type quadratic, fee_multiplier 1)"),
        ComponentEvidence(VerificationComponent.SCHEDULED_CHANGES, ComponentState.VERIFIED,
                          f"{_EVIDENCE_DIR}/api_series_fee_changes_KXHIGHNY_2026-09-23T131748Z.json",
                          "no scheduled fee change for KXHIGHNY as of 2026-09-23T13:17:48Z; re-check by recheck_by"),
        ComponentEvidence(VerificationComponent.ROUNDING_FOR_ACCOUNT_TYPE, ComponentState.VERIFIED,
                          f"PDF p.2 (fee + positionCost rounded up to a centicent); "
                          f"{_EVIDENCE_DIR}/docs_kalshi_fee_rounding_2026-09-23T131803Z.md",
                          "trade fee ceil $0.000001; direct-member balance aligned to $0.0001 (non-direct $0.01); "
                          "rounding overpayment rebated per order (capped). Fill granularity 0.01 contracts: "
                          f"{_EVIDENCE_DIR}/docs_kalshi_fixed_point_2026-09-23T133948Z.md. The frozen cost bounds "
                          "a single fill; a split order is bounded with a $0.0101-per-contract allowance"),
        ComponentEvidence(VerificationComponent.ACCOUNT_TYPE, ComponentState.OWNER_ATTESTED,
                          "docs/owner/2026-09-23-integration-production-directive.md (owner answer 1)",
                          "direct member (account held at kalshi.com); not verified through an account read"),
        ComponentEvidence(VerificationComponent.MAKER_FEES, ComponentState.VERIFIED,
                          "PDF p.2 (maker M default 0) and pp.6-11 (KXHIGHNY not listed)",
                          "maker fee 0 for KXHIGHNY; the simulation is taker-only"),
    ),
)

FEE_VERIFICATIONS: tuple[FeeVerificationRecord, ...] = (KALSHI_KXHIGHNY_VERIFICATION_2026_09_23,)


def _base_state(schedule: Any, detail: str) -> FeeVerificationState:
    """No dated record applies: the schedule's declared base status decides (test doubles and
    replacement schedules). A declared VERIFIED schedule supports EXACT only with an exact
    cost model. A conservative one has no proven rounding allowance, so, like a record without
    one, it supports no claim."""
    status = schedule.status
    if status is FeeScheduleStatus.VERIFIED and getattr(schedule, "cost_model", None) is CostModel.EXACT:
        return FeeVerificationState(schedule.schedule_id, status, ClaimBasis.EXACT, None, True, detail, Decimal(0))
    return FeeVerificationState(schedule.schedule_id, status, ClaimBasis.NONE, None, False, detail)


def _records_for(schedule: Any, scope: str | None) -> list[FeeVerificationRecord]:
    return [r for r in FEE_VERIFICATIONS
            if r.schedule_id == schedule.schedule_id and r.venue == getattr(schedule, "venue", None)
            and scope in r.scope]


def _state_from(schedule: QuadraticTakerSchedule, record: FeeVerificationRecord, at: datetime) -> FeeVerificationState:
    if at > parse_utc(record.recheck_by_utc):
        return FeeVerificationState(schedule.schedule_id, FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE,
                                    ClaimBasis.NONE, record.verification_id, False,
                                    f"{record.verification_id} is past its re-check date {record.recheck_by_utc}")
    basis = record.claim_basis(schedule.cost_model)
    status = FeeScheduleStatus.VERIFIED if record.full_schedule_verified else FeeScheduleStatus.PARTIALLY_VERIFIED
    pending = [c.component.value for c in record.components
               if c.state not in (ComponentState.VERIFIED, ComponentState.NOT_APPLICABLE)]
    detail = f"{record.verification_id}: claim basis {basis.value}"
    if basis is ClaimBasis.CONSERVATIVE_BOUND:
        detail += f" (subtract {record.rounding_allowance_per_contract} USD per contract before any claim)"
    if pending:
        detail += f"; not venue-verified: {', '.join(pending)}"
    return FeeVerificationState(schedule.schedule_id, status, basis, record.verification_id,
                                record.full_schedule_verified, detail,
                                record.rounding_allowance_per_contract if basis is not ClaimBasis.NONE else None)


def _scope_of(schedule: Any, native_id: str | None) -> str | None:
    scope_of = getattr(schedule, "scope_of", None)
    if callable(scope_of):
        return scope_of(native_id)
    return QuadraticTakerSchedule._scope(getattr(schedule, "venue", ""), native_id)


def verification_at(schedule: Any, as_of: datetime | str, native_id: str | None = None,
                    *, scope: str | None = None) -> FeeVerificationState:
    """What was known about `schedule` for this market's fee scope at `as_of`.

    Only records whose knowledge time is at or before `as_of`, whose effective date is at or
    before `as_of`, and whose scope covers the market count. Otherwise the schedule's base
    status applies. Pass `native_id` (a market) or `scope` (for example a Kalshi series).
    """
    at = parse_utc(as_of)
    if at is None:
        raise ValueError("as_of must be a timezone-aware time")
    scope = scope if scope is not None else _scope_of(schedule, native_id)
    usable = [r for r in _records_for(schedule, scope)
              if parse_utc(r.knowledge_time_utc) <= at and parse_utc(r.applies_from_utc) <= at]
    if not usable:
        return _base_state(schedule, f"no fee verification record known at {at.isoformat()} for scope {scope}")
    return _state_from(schedule, max(usable, key=lambda r: parse_utc(r.knowledge_time_utc)), at)


def restated_verification(schedule: Any, trade_at: datetime | str, now: datetime | str,
                          native_id: str | None = None, *, scope: str | None = None) -> FeeVerificationState:
    """A reporting restatement: the evidence known at `now` applied to a trade at `trade_at`.

    Never written back into the ledger. A trade before a record's effective date, or after
    its re-check date, is not covered by it."""
    trade, known = parse_utc(trade_at), parse_utc(now)
    if trade is None or known is None:
        raise ValueError("times must be timezone-aware")
    scope = scope if scope is not None else _scope_of(schedule, native_id)
    usable = [r for r in _records_for(schedule, scope)
              if parse_utc(r.knowledge_time_utc) <= known and parse_utc(r.applies_from_utc) <= trade]
    if not usable:
        return _base_state(schedule, f"no fee verification record covers a trade at {trade.isoformat()}")
    return _state_from(schedule, max(usable, key=lambda r: parse_utc(r.knowledge_time_utc)), trade)


# --------------------------------------------------------------------------- exact Kalshi debit

@dataclass(frozen=True)
class ExactFeeQuote:
    """The exact single-fill taker debit for one account type (reporting only)."""

    account_type: str
    contracts: int
    price: Decimal
    model_fee: Decimal
    trade_fee: Decimal
    rounding_fee: Decimal
    total_cost: Decimal


BALANCE_PRECISION = {"direct": CENTICENT, "non_direct": CENT}


def kalshi_exact_taker_buy(contracts: int, price: Decimal, *, account_type: str,
                           coefficient: Decimal = fees.QUADRATIC_TAKER_COEFFICIENT,
                           multiplier: Decimal = Decimal("1")) -> ExactFeeQuote:
    """Kalshi's documented debit for ONE taker fill that is the first fill of its order.

    trade fee = model fee rounded up to $0.000001; the balance change is floored to the
    account's precision ($0.0001 direct, $0.01 non-direct); the difference is the rounding
    fee. A first fill earns no rebate: rebates pay back accumulated rounding overpayment in
    whole precision units, and one fill's rounding fee is below one unit. Later fills of the
    same order can earn rebates, so multi-fill orders are not modelled here.
    """
    if account_type not in BALANCE_PRECISION:
        raise ValueError(f"unknown account type {account_type!r}")
    if not isinstance(contracts, int) or isinstance(contracts, bool) or contracts <= 0:
        raise ValueError("contracts must be a positive integer")
    p = Decimal(str(price))
    if not valid_price(p):
        raise ValueError(f"{p} is not a valid binary-contract price")
    model_fee = multiplier * coefficient * contracts * p * (1 - p)
    trade_fee = model_fee.quantize(SIX_DP, rounding=ROUND_CEILING)
    revenue = -(p * contracts)
    aligned = (revenue - trade_fee).quantize(BALANCE_PRECISION[account_type], rounding=ROUND_FLOOR)
    rounding_fee = (revenue - trade_fee) - aligned
    return ExactFeeQuote(account_type, contracts, p, model_fee, trade_fee, rounding_fee, -aligned)


def displayed_fee(contracts: int, price: Decimal, *, multiplier: Decimal = Decimal("1")) -> Decimal:
    """The fee as Kalshi's general fee table displays it: the model fee rounded up to the cent."""
    p = Decimal(str(price))
    return (multiplier * fees.QUADRATIC_TAKER_COEFFICIENT * contracts * p * (1 - p)).quantize(CENT, rounding=ROUND_CEILING)


# --------------------------------------------------------------------------- venue routing

# Series on the PDF's "Non-Standard Fees" list (pp.6-11): they have their own multipliers,
# so the general schedule never prices them. Transcribed in
# `_EVIDENCE_DIR/pdf_nonstandard_series.json`; a test keeps this set equal to that file.
KALSHI_NONSTANDARD_SERIES = frozenset({
    "KXAAAGASM", "KXATPMATCH", "KXBALLONDOR", "KXBTCMAX150", "KXBTCY", "KXCITRINI", "KXCPI", "KXCPIYOY",
    "KXDOED", "KXEGGS", "KXELECTIRAN", "KXEMMYCACTO", "KXEMMYCACTR", "KXEMMYCSERIES", "KXEMMYDACTO",
    "KXEMMYDACTR", "KXEMMYDSERIES", "KXETHY", "KXFED", "KXFEDDECISION", "KXGAMBLINGREPEAL", "KXGDP",
    "KXGREENLAND", "KXHEISMAN", "KXINXY", "KXIPO", "KXIRANDEMOCRACY", "KXLALIGA", "KXLAYOFFSYINFO", "KXLLM1",
    "KXMARMAD", "KXMENWORLDCUP", "KXMLB", "KXMLBAL", "KXMLBASGAME", "KXMLBGAME", "KXMLBNL", "KXMVE",
    "KXNASDAQ100Y", "KXNBA", "KXNBAEAST", "KXNBAMVP", "KXNBAROY", "KXNBAWEST", "KXNCAAF", "KXNCAAFACC",
    "KXNCAAFB10", "KXNCAAFB12", "KXNCAAFGAME", "KXNCAAFPLAYOFF", "KXNCAAFSEC", "KXNFLAFCCHAMP", "KXNFLAFCEAST",
    "KXNFLAFCNORTH", "KXNFLAFCSOUTH", "KXNFLAFCWEST", "KXNFLCOTY", "KXNFLCPOTY", "KXNFLDPOTY", "KXNFLDROTY",
    "KXNFLGAME", "KXNFLMVP", "KXNFLNFCCHAMP", "KXNFLNFCEAST", "KXNFLNFCNORTH", "KXNFLNFCSOUTH", "KXNFLNFCWEST",
    "KXNFLOPOTY", "KXNFLOROTY", "KXNHL", "KXNHLEAST", "KXNHLWEST", "KXPAHLAVIHEAD", "KXPAYROLLS", "KXPGARYDER",
    "KXPGASOLHEIM", "KXPGATOUR", "KXRATECUTCOUNT", "KXSB", "KXSUPERBOWLHEADLINE", "KXU3", "KXUCL", "KXUCLGAME",
    "KXWCGAME", "KXWNBA", "KXWNBAGAME", "KXWTAMATCH",
})


@dataclass(frozen=True)
class UnsupportedFeeSchedule:
    """No verified fee model for this venue or scope. It never prices anything, and an
    opportunity priced against it is rejected (FEE_UNSUPPORTED)."""

    venue: str
    scope: str | None
    reason: str

    @property
    def schedule_id(self) -> str:
        return f"unsupported:{self.venue}:{self.scope or '*'}"

    status = FeeScheduleStatus.UNSUPPORTED

    def scope_of(self, native_id: str | None) -> str | None:
        return self.scope

    def taker_buy(self, contracts: int, price: Decimal) -> FeeQuote:
        raise ValueError(f"{self.schedule_id}: {self.reason}")


def schedule_for(venue: str, scope: str | None = None) -> QuadraticTakerSchedule | UnsupportedFeeSchedule:
    """The fee schedule for a venue and fee scope. Kalshi's general schedule covers only
    Kalshi series that are not on the non-standard list; every other venue has its own
    fees and stays unsupported until its own primary evidence is captured."""
    if venue != "kalshi":
        return UnsupportedFeeSchedule(venue, scope, "no fee schedule has been verified for this venue")
    if not scope:
        return UnsupportedFeeSchedule(venue, scope, "the Kalshi series is unknown")
    if scope in KALSHI_NONSTANDARD_SERIES:
        return UnsupportedFeeSchedule(venue, scope, "series has a non-standard Kalshi fee schedule (PDF pp.6-11)")
    return KALSHI_QUADRATIC_TAKER_V1


def recorded_claim_basis(fills: Iterable[Mapping[str, Any]]) -> ClaimBasis:
    """The weakest claim basis over an account's FILLED fills, as recorded at their decision
    times. A fill with no `claim_basis` (recorded before any verification record) is NONE.
    With no fills there is nothing to claim: NONE."""
    return ClaimBasis.weakest(f.get("claim_basis", "NONE") for f in fills if f.get("status") == "FILLED")


def recheck_due(now: datetime | str) -> list[str]:
    """The newest record per (schedule, scope) whose re-check date has passed at `now`.
    A record superseded by a newer one for the same scope is not due."""
    at = parse_utc(now)
    if at is None:
        return []
    newest: dict[tuple[str, tuple[str, ...]], FeeVerificationRecord] = {}
    for r in FEE_VERIFICATIONS:
        key = (r.schedule_id, r.scope)
        if key not in newest or parse_utc(r.knowledge_time_utc) > parse_utc(newest[key].knowledge_time_utc):
            newest[key] = r
    return [r.verification_id for r in newest.values() if at > parse_utc(r.recheck_by_utc)]


RECHECK_WARNING = timedelta(days=7)
