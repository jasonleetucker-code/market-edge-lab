"""Outcome Board backend (issue #3 foundation): positions grouped by the real-world outcome.

The board answers one question: which underlying outcomes matter most to the account?
Positions are grouped by `outcome_cluster`, the normalized underlying the Gate 5 `Event`
assigns. Each group reports its account impact, its current exposure, when it settles
and its status. Groups are ranked by account impact.

This is data only. There is no UI here, and nothing trades.

About "worst case": a cluster's maximum loss is the sum of its positions' worst cases.
That is an upper bound. Mutually exclusive brackets (for example several YES brackets on
one temperature) cannot all lose in some scenarios. Tightening the bound needs per-outcome
scenario enumeration, and every group names the method it used so the bound is never
mistaken for an exact figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .freshness import parse_utc
from .shadow_ledger import AccountState, Position

ZERO = Decimal(0)
WORST_CASE_METHOD = "sum_of_position_worst_cases (upper bound; ignores mutual exclusivity)"
BEST_CASE_METHOD = "sum_of_position_best_cases (upper bound; mutually exclusive brackets cannot all win)"


@dataclass(frozen=True)
class LinkedPosition:
    position_id: str
    market_id: str
    event_id: str
    side: str
    quantity: int
    cost_basis: Decimal
    potential_payout: Decimal
    status: str
    net_pnl: Decimal | None


@dataclass(frozen=True)
class OutcomeGroup:
    outcome_cluster: str
    event_ids: tuple[str, ...]
    positions: tuple[LinkedPosition, ...]
    current_exposure: Decimal  # committed cost of open positions
    max_account_loss: Decimal  # worst case (upper bound), open positions
    max_account_gain: Decimal  # best case (upper bound): payouts minus cost, open positions
    account_impact: Decimal  # max(|loss|, gain): the swing this outcome can cause
    realized_pnl: Decimal  # already settled positions in this cluster
    settles_by_utc: str | None  # earliest known expected settlement of an open position
    unknown_settlement_positions: int  # open positions with no expected settlement time
    horizon: str  # within_1_hour | within_1_day | within_1_week | later | unknown | settled
    status: str  # OPEN | PARTIALLY_SETTLED | SETTLED
    worst_case_method: str
    best_case_method: str

    def to_dict(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, tuple):
                return [plain(x) for x in v]
            if isinstance(v, LinkedPosition):
                return {k: plain(x) for k, x in v.__dict__.items()}
            return v
        return {k: plain(v) for k, v in self.__dict__.items()}


def _horizon(settles: datetime | None, as_of: datetime) -> str:
    if settles is None:
        return "unknown"
    if settles < as_of:
        return "overdue"  # expected to have settled and still open: stuck or disputed
    for name, width in (("within_1_hour", timedelta(hours=1)), ("within_1_day", timedelta(days=1)),
                        ("within_1_week", timedelta(weeks=1))):
        if settles <= as_of + width:
            return name
    return "later"


def _link(p: Position) -> LinkedPosition:
    return LinkedPosition(p.position_id, p.market_id, p.event_id, p.side, p.quantity, p.cost_basis,
                          p.potential_payout, p.status, p.net_pnl)


def build_board(state: AccountState, as_of: datetime, *, include_settled: bool = False) -> list[OutcomeGroup]:
    """Groups ranked by account impact (descending), then earliest settlement, then cluster id."""
    from .risk import require_point_in_time

    as_of_utc = require_point_in_time(state, as_of)
    clusters: dict[str, list[Position]] = {}
    for p in state.positions:
        clusters.setdefault(p.outcome_cluster, []).append(p)
    groups = []
    for cluster, ps in clusters.items():
        open_ = [p for p in ps if p.status == "OPEN"]
        if not open_ and not include_settled:
            continue
        loss = sum((p.max_downside for p in open_), ZERO)
        gain = sum((p.potential_payout - p.cost_basis for p in open_), ZERO)
        times = [t for t in (parse_utc(p.expected_settlement_utc) for p in open_) if t is not None]
        unknown = sum(parse_utc(p.expected_settlement_utc) is None for p in open_)
        settles = min(times) if times else None
        status = "SETTLED" if not open_ else ("PARTIALLY_SETTLED" if len(open_) < len(ps) else "OPEN")
        groups.append(OutcomeGroup(
            outcome_cluster=cluster,
            event_ids=tuple(sorted({p.event_id for p in ps})),
            positions=tuple(_link(p) for p in sorted(ps, key=lambda p: p.position_id)),
            current_exposure=sum((p.cost_basis for p in open_), ZERO),
            max_account_loss=loss, max_account_gain=gain, account_impact=max(loss, gain),
            realized_pnl=sum((p.net_pnl for p in ps if p.status == "SETTLED"), ZERO),
            settles_by_utc=None if settles is None else settles.isoformat(),
            unknown_settlement_positions=unknown,
            horizon="settled" if not open_ else _horizon(settles, as_of_utc),
            status=status, worst_case_method=WORST_CASE_METHOD, best_case_method=BEST_CASE_METHOD,
        ))
    far = datetime.max.replace(tzinfo=as_of_utc.tzinfo)
    return sorted(groups, key=lambda g: (-g.account_impact, parse_utc(g.settles_by_utc) or far, g.outcome_cluster))
