"""Defensive screens for manipulated or misleading leader signals (W7, directive §11).

These are threat scenarios, not accusations: every output is a HEURISTIC flag on public pseudonymous
accounts, never a finding about a person. Nothing here implements manipulation or evasion.

- `co_trading_clusters`: accounts that repeatedly trade the same token in the same direction within a
  short window, or share a stated funding source, are merged into one heuristic cluster, so several
  wallets cannot pose as independent confirmation.
- `round_trip_share`: the share of turnover that is quickly reversed (wash or churn). Volume made of
  round trips is not skill.
- `off_market_fills`: leader fills at prices the captured book did not offer at the time (cheap or
  off-market allocations). A follower can never get that price, so these fills do not qualify a
  leader. With no book the fill is UNJUDGED, not cleared.
- `is_bait_size`: a leader trade too small to matter is not a signal.
Fake marks, illiquid gifts, hidden hedges, stale replays and a leader exiting while we enter are
handled where the decision is made (accounting, selection, policy and replay).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from .events import Action, WalletObservation
from .exact import ZERO, add, mul, ratio
from .market_data import BookProvider


def co_trading_clusters(observations: Sequence[WalletObservation], *, window: timedelta, min_shared: int,
                        min_overlap: Decimal, funding_sources: Mapping[str, str] | None = None) -> dict[str, str]:
    """account key -> heuristic cluster key (the smallest member key). Union-find over two links:
    (1) at least `min_shared` same-token, same-direction trades within `window` of each other making
    up at least `min_overlap` of the smaller account's trades; (2) the same stated funding source."""
    trades: dict[str, list[WalletObservation]] = {}
    for o in observations:
        if o.directional:
            trades.setdefault(o.account.key, []).append(o)
    accounts = sorted({o.account.key for o in observations})
    parent = {a: a for a in accounts}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, a in enumerate(accounts):
        for b in accounts[i + 1:]:
            ta, tb = trades.get(a, []), trades.get(b, [])
            if not ta or not tb:
                continue
            shared = sum(1 for x in ta if any(
                y.instrument_id == x.instrument_id and y.action is x.action
                and abs(y.source_time - x.source_time) <= window for y in tb))
            smaller = min(len(ta), len(tb))
            if shared >= min_shared and Decimal(shared) >= mul(min_overlap, Decimal(smaller)):
                union(a, b)
    by_source: dict[str, list[str]] = {}
    for account, source in sorted((funding_sources or {}).items()):
        if account in parent:
            by_source.setdefault(source, []).append(account)
    for members in by_source.values():
        for other in members[1:]:
            union(members[0], other)
    return {a: find(a) for a in accounts}


def independent_count(accounts: Sequence[str], clusters: Mapping[str, str]) -> int:
    """How many independent confirmations a set of agreeing accounts really is."""
    return len({clusters.get(a, a) for a in accounts})


def round_trip_share(observations: Sequence[WalletObservation], *, max_hold: timedelta) -> Decimal | None:
    """Share of trade notional that is a buy reversed by a sale of the same token within `max_hold`
    (FIFO quantity matching). None when there is no trade notional."""
    lots: dict[str, list[list]] = {}
    matched = ZERO
    turnover = ZERO
    for o in sorted(observations, key=lambda x: (x.source_time, x.observation_id)):
        if not o.directional or o.native_quantity is None or o.price is None or o.instrument_id is None:
            continue
        notional = mul(o.native_quantity, o.price)
        turnover = add(turnover, notional)
        if o.action is Action.TRADE_BUY:
            lots.setdefault(o.instrument_id, []).append([o.source_time, o.native_quantity, o.price])
            continue
        remaining = o.native_quantity
        for lot in lots.get(o.instrument_id, []):
            if remaining <= 0:
                break
            if lot[1] <= 0 or o.source_time - lot[0] > max_hold:
                continue
            used = min(remaining, lot[1])
            matched = add(matched, mul(used, lot[2]), mul(used, o.price))
            lot[1] = add(lot[1], -used)
            remaining = add(remaining, -used)
    return ratio(matched, turnover)


class FillJudgement(str, Enum):
    AT_MARKET = "AT_MARKET"
    OFF_MARKET = "OFF_MARKET"
    UNJUDGED = "UNJUDGED"  # no book at the time: not cleared


@dataclass(frozen=True)
class OffMarketRow:
    observation_id: str
    judgement: FillJudgement
    detail: str


def off_market_fills(observations: Sequence[WalletObservation], books: BookProvider, *, tolerance: Decimal,
                     max_book_age: timedelta) -> tuple[OffMarketRow, ...]:
    out = []
    for o in observations:
        if not o.directional or o.price is None or o.instrument_id is None:
            continue
        book = books(o.instrument_id, o.source_time)
        if book is None or book.captured_at > o.source_time or o.source_time - book.captured_at > max_book_age:
            out.append(OffMarketRow(o.observation_id, FillJudgement.UNJUDGED, "no contemporaneous book"))
            continue
        if o.action is Action.TRADE_BUY:
            ask = book.best_ask()
            if ask is None:
                out.append(OffMarketRow(o.observation_id, FillJudgement.UNJUDGED, "no asks"))
                continue
            off = o.price < add(ask, -tolerance)
            detail = f"bought at {o.price} with best ask {ask}"
        else:
            bid = book.best_bid()
            if bid is None:
                out.append(OffMarketRow(o.observation_id, FillJudgement.UNJUDGED, "no bids"))
                continue
            off = o.price > add(bid, tolerance)
            detail = f"sold at {o.price} with best bid {bid}"
        out.append(OffMarketRow(o.observation_id, FillJudgement.OFF_MARKET if off else FillJudgement.AT_MARKET,
                                detail))
    return tuple(out)


def is_bait_size(o: WalletObservation, *, min_notional: Decimal) -> bool:
    if not o.directional or o.native_quantity is None or o.price is None:
        return False
    return mul(o.native_quantity, o.price) < min_notional
