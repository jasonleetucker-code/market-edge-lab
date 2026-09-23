"""Risk and capital foundation (issue #6, P0). Simulation only: it reads a replayed shadow account.

Every figure here is a deterministic function of the account state (`shadow_ledger.replay`),
a `RiskPolicy` and an `as_of` instant. Nothing reads a venue balance, and nothing moves
money.

Rules:

- **Worst case, not hope.** A long binary position can lose its entire cost. Open risk is
  therefore the committed capital, and remaining capacity is measured against the worst
  case.
- **Expected winnings are never available cash.** Capital "released" by a horizon is
  reported as the committed cost settling in that window. Its guaranteed cash value is
  zero: a losing binary returns nothing. The best-case payout is reported separately and
  is never added to available cash.
- **Missing is not zero.** A position without an expected settlement time is `locked`. It
  is never assumed to settle soon.

The withdrawal contract computes what could technically be withdrawn and what a reserve
policy would allow. It deliberately makes **no owner-draw recommendation**: that needs a
verified edge, a verified fee schedule and an owner-approved policy, and none of them
exists yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .freshness import parse_utc
from .shadow_ledger import AccountState

HORIZONS = ("available_now", "within_1_hour", "within_1_day", "within_1_week", "locked")
_BOUNDS = (("within_1_hour", timedelta(hours=1)), ("within_1_day", timedelta(days=1)),
           ("within_1_week", timedelta(weeks=1)))
ZERO = Decimal(0)
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RiskPolicy:
    policy_id: str
    reserve_floor: Decimal  # settled cash never committed or withdrawn
    max_position_risk: Decimal
    max_event_risk: Decimal
    max_cluster_risk: Decimal
    max_portfolio_risk: Decimal
    # Loss limits are measured over trailing windows (24 h, 7 d) of *net* realized P&L, not
    # calendar periods: a win inside the window offsets losses in it.
    daily_loss_limit: Decimal  # net realized loss over the trailing 24 h that halts new risk
    weekly_loss_limit: Decimal
    max_drawdown: Decimal  # $ below peak equity that halts new risk

    def __post_init__(self) -> None:
        for name in ("reserve_floor", "max_position_risk", "max_event_risk", "max_cluster_risk",
                     "max_portfolio_risk", "daily_loss_limit", "weekly_loss_limit", "max_drawdown"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class HorizonBucket:
    horizon: str
    committed_capital: Decimal  # cost basis settling in this window (available_now: settled cash)
    guaranteed_cash: Decimal  # what is certain to be cash by then (0 for open binaries)
    best_case_payout: Decimal  # maximum payout if every position wins; never counted as cash
    positions: int


@dataclass(frozen=True)
class RiskReport:
    account_id: str
    as_of_utc: str
    policy_id: str
    starting_bankroll: Decimal
    equity: Decimal
    settled_cash: Decimal
    committed_capital: Decimal
    open_worst_case_risk: Decimal
    total_portfolio_exposure: Decimal
    risk_per_position: dict[str, Decimal]
    risk_per_event: dict[str, Decimal]
    cluster_exposure: dict[str, Decimal]
    peak_equity: Decimal
    drawdown: Decimal
    daily_loss: Decimal
    weekly_loss: Decimal
    reserve_floor: Decimal
    remaining_risk_capacity: Decimal
    capital_release: tuple[HorizonBucket, ...]
    breaches: tuple[str, ...]
    new_risk_allowed: bool
    notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [plain(x) for x in v]
            if isinstance(v, HorizonBucket):
                return {k: plain(x) for k, x in v.__dict__.items()}
            return v
        return {k: plain(v) for k, v in self.__dict__.items()}


def _sum(values) -> Decimal:
    return sum(values, ZERO)


def _grouped(state: AccountState, key: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for p in state.open_positions():
        k = getattr(p, key)
        out[k] = out.get(k, ZERO) + p.max_downside
    return dict(sorted(out.items()))


def equity_curve(state: AccountState) -> list[tuple[str, Decimal]]:
    """Equity after each settlement, in settlement order (cost-basis equity moves only on settlement)."""
    settled = sorted((p for p in state.positions if p.status == "SETTLED"),
                     key=lambda p: (parse_utc(p.settled_at_utc) or _EARLIEST, p.position_id))
    equity, curve = state.starting_bankroll, [("start", state.starting_bankroll)]
    for p in settled:
        equity += p.net_pnl
        curve.append((p.settled_at_utc, equity))
    return curve


def _realized_since(state: AccountState, since: datetime, until: datetime) -> Decimal:
    total = ZERO
    for p in state.positions:
        at = parse_utc(p.settled_at_utc) if p.status == "SETTLED" else None
        if at is not None and since < at <= until:
            total += p.net_pnl
    return total


def capital_release(state: AccountState, as_of: datetime) -> tuple[HorizonBucket, ...]:
    """Committed capital by when it is expected to settle. Overdue or unknown -> `locked`."""
    as_of = parse_utc(as_of)
    if as_of is None:
        raise ValueError("as_of must be timezone-aware")
    buckets = {h: [] for h in HORIZONS[1:]}
    for p in state.open_positions():
        expected = parse_utc(p.expected_settlement_utc)
        horizon = "locked"
        # A position past its expected settlement and still open is stuck or disputed:
        # it is locked, never "about to release".
        if expected is not None and expected >= as_of:
            for name, width in _BOUNDS:
                if expected <= as_of + width:
                    horizon = name
                    break
        buckets[horizon].append(p)
    out = [HorizonBucket("available_now", state.settled_cash, state.settled_cash, ZERO, 0)]
    for name in HORIZONS[1:]:
        ps = buckets[name]
        out.append(HorizonBucket(name, _sum(p.cost_basis for p in ps), ZERO, _sum(p.potential_payout for p in ps),
                                 len(ps)))
    return tuple(out)


def latest_activity(state: AccountState) -> datetime | None:
    """The latest fill or settlement time in the replayed state."""
    times = [parse_utc(p.opened_at_utc) for p in state.positions]
    times += [parse_utc(p.settled_at_utc) for p in state.positions if p.status == "SETTLED"]
    known = [t for t in times if t is not None]
    return max(known) if known else None


def require_point_in_time(state: AccountState, as_of: datetime) -> datetime:
    """Refuse an `as_of` earlier than the ledger's activity: the state would contain the future."""
    as_of_utc = parse_utc(as_of)
    if as_of_utc is None:
        raise ValueError("as_of must be timezone-aware")
    latest = latest_activity(state)
    if latest is not None and as_of_utc < latest:
        raise ValueError(f"as_of {as_of_utc.isoformat()} precedes ledger activity at {latest.isoformat()}; "
                         "the replayed state is not point-in-time for that instant")
    return as_of_utc


def assess(state: AccountState, policy: RiskPolicy, as_of: datetime) -> RiskReport:
    as_of_utc = require_point_in_time(state, as_of)
    curve = equity_curve(state)
    peak = max(e for _, e in curve)
    drawdown = peak - state.equity
    daily = -min(ZERO, _realized_since(state, as_of_utc - timedelta(days=1), as_of_utc))
    weekly = -min(ZERO, _realized_since(state, as_of_utc - timedelta(weeks=1), as_of_utc))
    per_position = {p.position_id: p.max_downside for p in state.open_positions()}
    per_event, per_cluster = _grouped(state, "event_id"), _grouped(state, "outcome_cluster")

    breaches = []
    if state.settled_cash < policy.reserve_floor:
        breaches.append("RESERVE_FLOOR")
    if state.open_worst_case_risk > policy.max_portfolio_risk:
        breaches.append("MAX_PORTFOLIO_RISK")
    if any(v > policy.max_position_risk for v in per_position.values()):
        breaches.append("MAX_POSITION_RISK")
    if any(v > policy.max_event_risk for v in per_event.values()):
        breaches.append("MAX_EVENT_RISK")
    if any(v > policy.max_cluster_risk for v in per_cluster.values()):
        breaches.append("MAX_CLUSTER_RISK")
    if daily > policy.daily_loss_limit:
        breaches.append("DAILY_LOSS_LIMIT")
    if weekly > policy.weekly_loss_limit:
        breaches.append("WEEKLY_LOSS_LIMIT")
    if drawdown > policy.max_drawdown:
        breaches.append("MAX_DRAWDOWN")

    # New risk may only use the tightest headroom. Loss and drawdown limits are measured as
    # if every open position lost too: new risk must fit after the current worst case.
    open_risk = state.open_worst_case_risk
    capacity = max(ZERO, min(
        policy.max_portfolio_risk - open_risk,
        state.settled_cash - policy.reserve_floor,
        policy.daily_loss_limit - daily - open_risk,
        policy.weekly_loss_limit - weekly - open_risk,
        policy.max_drawdown - drawdown - open_risk,
    ))
    if breaches:
        capacity = ZERO
    return RiskReport(
        account_id=state.account_id, as_of_utc=as_of_utc.isoformat(), policy_id=policy.policy_id,
        starting_bankroll=state.starting_bankroll, equity=state.equity, settled_cash=state.settled_cash,
        committed_capital=state.committed_capital, open_worst_case_risk=state.open_worst_case_risk,
        total_portfolio_exposure=state.open_worst_case_risk, risk_per_position=per_position,
        risk_per_event=per_event, cluster_exposure=per_cluster, peak_equity=peak, drawdown=drawdown,
        daily_loss=daily, weekly_loss=weekly, reserve_floor=policy.reserve_floor,
        remaining_risk_capacity=capacity, capital_release=capital_release(state, as_of_utc),
        # Zero capacity never authorizes new risk, breach or not.
        breaches=tuple(breaches), new_risk_allowed=not breaches and capacity > ZERO,
        notes=("worst case for a long binary is its full cost; committed capital settling later is not cash",),
    )


# --------------------------------------------------------------------------- withdrawal contract


@dataclass(frozen=True)
class WithdrawalAssessment:
    account_id: str
    as_of_utc: str
    technically_withdrawable: Decimal  # settled cash not committed to open positions
    policy_safe_withdrawable: Decimal  # after the reserve floor, and zero while a limit is breached
    recommended_owner_draw: Decimal | None  # None until policy and evidence support a recommendation
    recommendation_status: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, Decimal) else list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


def withdrawal_assessment(state: AccountState, report: RiskReport, *, simulation: bool = True,
                          edge_verified: bool = False, fee_claim_basis: str = "NONE",
                          owner_policy_approved: bool = False) -> WithdrawalAssessment:
    """The withdrawal contract. It never recommends a draw until every precondition holds."""
    technical = max(ZERO, state.settled_cash)
    safe = ZERO if report.breaches else max(ZERO, state.settled_cash - report.reserve_floor)
    missing = []
    if simulation:
        missing.append("SHADOW_ACCOUNT: no real money exists")
    if not edge_verified:
        missing.append("EDGE_NOT_VERIFIED")
    if fee_claim_basis not in ("CONSERVATIVE_BOUND", "EXACT"):
        # Only verified fees support a claim; a conservative bound under-states profit,
        # so it is enough for a withdrawal floor (ADR 0017).
        missing.append("FEE_SCHEDULE_UNVERIFIED")
    if not owner_policy_approved:
        missing.append("NO_OWNER_APPROVED_WITHDRAWAL_POLICY")
    # Even with every precondition met, the draw formula itself needs owner approval. This
    # contract stops at the policy-safe bound.
    missing.append("DRAW_FORMULA_NOT_DEFINED")
    return WithdrawalAssessment(
        account_id=state.account_id, as_of_utc=report.as_of_utc, technically_withdrawable=technical,
        policy_safe_withdrawable=safe, recommended_owner_draw=None, recommendation_status="NOT_RECOMMENDED",
        reasons=tuple(missing),
    )
