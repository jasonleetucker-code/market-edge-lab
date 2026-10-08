"""Defensive screens for manipulated or misleading leader signals (W7, directive §11).

These are threat scenarios, not accusations: every output is a HEURISTIC flag on public pseudonymous
accounts, never a finding about a person. Nothing here implements manipulation or evasion.

- `co_trading_clusters`: accounts that repeatedly trade the same token in the same direction within a
  short window, or share a stated funding source, are merged into one heuristic cluster, so several
  wallets cannot pose as independent confirmation.
- `round_trip_share`: the share of turnover that is quickly reversed (wash or churn). Volume made of
  round trips is not skill.
- `off_market_fills` (**v1, legacy, role-unaware**): compares a buy to the best ask and a sale to the
  best bid. It therefore labels a legitimate passive (maker) fill OFF_MARKET: a maker BUY at 0.45 in a
  0.45 / 0.55 book is ordinary. Kept unchanged for existing callers; new code uses the v2 diagnostics.
- `is_bait_size`: a leader trade too small to matter is not a signal.
Fake marks, illiquid gifts, hidden hedges, stale replays and a leader exiting while we enter are
handled where the decision is made (accounting, selection, policy and replay).

**Role-aware quality diagnostics (v2, ADR 0045 amendment 2026-10-08 B).** Four separately typed
concepts, never merged into one score:

1. `liquidity_role` (MAKER / TAKER / MIXED / UNKNOWN) comes only from the observation's
   source-stated field (`WalletObservation.liquidity_role`, with its source). It is never inferred
   from where the price sits in the spread.
2. `price_consistency` (CONSISTENT / INCONSISTENT / INSUFFICIENT_EVIDENCE): could the captured book
   have produced this price for this role? It checks the timestamp (book before the trade under the
   stated clock-skew bound, not stale), the price unit (a known per-share basis in (0, 1) that agrees
   with the cash leg) and the book's validity (a crossed or locked capture cannot be built). With an
   UNKNOWN or MIXED role the price is CONSISTENT when some role explains it; the row names which.
   CONSISTENT is about the leader's own print only. It says nothing about what a follower can get.
3. `contamination_evidence`: PROVISIONAL flags for shared activity, stated funding links, churn and
   source-reported counterparty self-trades or circular flows. Each flag carries its observability,
   evidence kind and uncertainty notes. Without counterparties the counterparty detector is
   UNOBSERVABLE, not clean. Co-trading does not prove common ownership or wrongdoing.
4. `follower_copyability`: what *our* later arrival could execute, read from the canonical follower
   replay (`replay.replay`), never from a second fill engine and never from the leader's price.

A maker BUY at 0.45 in a 0.45 / 0.55 book is CONSISTENT, and that does not mean a follower can buy at
0.45: the follower's later arrival takes the ask (or does not fill).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from .events import Action, LiquidityRole, WalletObservation
from .exact import ZERO, Basis, Labeled, add, decimal_text, mul, ratio, sub
from .market_data import Book, BookProvider
from .policy import FollowSignal
from .replay import REPLAY_VERSION, FillStatus, ReplayResult
from .timeutil import utc_text

OFF_MARKET_V1_SCHEMA = "wallet-off-market-v1"
QUALITY_SCHEMA = "wallet-quality-diagnostics-v2"
COPYABILITY_SCHEMA = "wallet-follower-copyability-v1"
NOT_PROOF = "NOT_PROOF_OF_COMMON_OWNERSHIP_OR_WRONGDOING"
KNOWN_PRICE_BASES = frozenset({"USDC_PER_SHARE"})  # the price unit every current parser emits
LEGACY_V1_NOTE = ("v1 is role-unaware: it compares a buy to the best ask and a sale to the best bid, so a "
                  "legitimate maker fill can read OFF_MARKET. OFF_MARKET is not evidence of manipulation.")


def _shared_trade_pairs(observations: Sequence[WalletObservation], *, window: timedelta, min_shared: int,
                        min_overlap: Decimal) -> list[tuple[str, str, tuple[str, ...]]]:
    """Account pairs (a < b) meeting the co-trading thresholds, with the observation ids involved."""
    trades: dict[str, list[WalletObservation]] = {}
    for o in observations:
        if o.directional:
            trades.setdefault(o.account.key, []).append(o)
    accounts = sorted({o.account.key for o in observations})
    pairs = []
    for i, a in enumerate(accounts):
        for b in accounts[i + 1:]:
            ta, tb = trades.get(a, []), trades.get(b, [])
            if not ta or not tb:
                continue
            ids: set[str] = set()
            shared = 0
            for x in ta:
                matches = [y for y in tb if y.instrument_id == x.instrument_id and y.action is x.action
                           and abs(y.source_time - x.source_time) <= window]
                if matches:
                    shared += 1
                    ids.add(x.observation_id)
                    ids.update(y.observation_id for y in matches)
            smaller = min(len(ta), len(tb))
            if shared >= min_shared and Decimal(shared) >= mul(min_overlap, Decimal(smaller)):
                pairs.append((a, b, tuple(sorted(ids))))
    return pairs


def co_trading_clusters(observations: Sequence[WalletObservation], *, window: timedelta, min_shared: int,
                        min_overlap: Decimal, funding_sources: Mapping[str, str] | None = None) -> dict[str, str]:
    """account key -> heuristic cluster key (the smallest member key). Union-find over two links:
    (1) at least `min_shared` same-token, same-direction trades within `window` of each other making
    up at least `min_overlap` of the smaller account's trades; (2) the same stated funding source."""
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

    for a, b, _ in _shared_trade_pairs(observations, window=window, min_shared=min_shared, min_overlap=min_overlap):
        union(a, b)
    for members in _funding_groups(accounts, funding_sources).values():
        for other in members[1:]:
            union(members[0], other)
    return {a: find(a) for a in accounts}


def _funding_groups(accounts: Sequence[str], funding_sources: Mapping[str, str] | None) -> dict[str, list[str]]:
    by_source: dict[str, list[str]] = {}
    known = set(accounts)
    for account, source in sorted((funding_sources or {}).items()):
        if account in known:
            by_source.setdefault(source, []).append(account)
    return by_source


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

    def to_dict(self) -> dict:
        return {"observation_id": self.observation_id, "judgement": self.judgement.value, "detail": self.detail}


def off_market_fills(observations: Sequence[WalletObservation], books: BookProvider, *, tolerance: Decimal,
                     max_book_age: timedelta) -> tuple[OffMarketRow, ...]:
    """LEGACY v1 (`OFF_MARKET_V1_SCHEMA`), role-unaware; behaviour unchanged. See `price_consistency`."""
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


def off_market_report_v1(rows: Sequence[OffMarketRow]) -> dict:
    """The v1 rows as an explicitly versioned, role-unaware payload."""
    return {"schema": OFF_MARKET_V1_SCHEMA, "role_aware": False, "interpretation": LEGACY_V1_NOTE,
            "rows": [r.to_dict() for r in rows]}


def is_bait_size(o: WalletObservation, *, min_notional: Decimal) -> bool:
    if not o.directional or o.native_quantity is None or o.price is None:
        return False
    return mul(o.native_quantity, o.price) < min_notional


# --- v2: role-aware quality diagnostics ------------------------------------------------------------

class DataClass(str, Enum):
    """Where the inputs came from. Synthetic results are engineering tests, never evidence of an edge."""

    SYNTHETIC = "SYNTHETIC"
    FIXTURE = "FIXTURE"
    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"


class PriceConsistency(str, Enum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class RoleEvidence:
    role: LiquidityRole
    source: str | None  # the field (or "fixture:...") that states it; None when UNKNOWN


def liquidity_role(o: WalletObservation) -> RoleEvidence:
    """The role exactly as the observation states it. Never derived from the price or the book."""
    return RoleEvidence(o.liquidity_role, o.liquidity_role_source)


@dataclass(frozen=True)
class PriceConsistencyRow:
    observation_id: str
    side: str  # BUY | SELL
    role: LiquidityRole
    verdict: PriceConsistency
    consistent_roles: tuple[LiquidityRole, ...]  # the roles under which the book explains the price
    reasons: tuple[str, ...]
    price: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    book_captured_at: datetime | None
    provenance: tuple[tuple[str, str], ...]  # sorted (key, value) pairs; missing values are omitted

    def to_dict(self) -> dict:
        def t(v: Decimal | None) -> str | None:
            return None if v is None else decimal_text(v)
        return {"observation_id": self.observation_id, "side": self.side, "role": self.role.value,
                "verdict": self.verdict.value, "consistent_roles": [r.value for r in self.consistent_roles],
                "reasons": list(self.reasons), "price": t(self.price), "best_bid": t(self.best_bid),
                "best_ask": t(self.best_ask),
                "book_captured_at": None if self.book_captured_at is None else utc_text(self.book_captured_at),
                "provenance": dict(self.provenance)}


_C, _I, _X = PriceConsistency.CONSISTENT, PriceConsistency.INCONSISTENT, PriceConsistency.INSUFFICIENT_EVIDENCE


def _judge(buying: bool, role: LiquidityRole, price: Decimal, book: Book, tol: Decimal) -> tuple[PriceConsistency, str]:
    """One role's verdict against the captured inside quote and depth."""
    bid, ask = book.best_bid(), book.best_ask()
    if role is LiquidityRole.TAKER:
        if buying:
            if ask is None:
                return _X, "TAKER_BUY_NO_ASKS: no captured ask to take"
            if price < sub(ask, tol):
                return _I, f"TAKER_BUY_BELOW_BEST_ASK: {price} < ask {ask}"
            deepest = book.asks[-1].price
            if price > add(deepest, tol):
                return ((_X, f"TAKER_BUY_BEYOND_CAPTURED_DEPTH: {price} > deepest captured ask {deepest} (truncated)")
                        if book.asks_truncated else
                        (_I, f"TAKER_BUY_ABOVE_EVERY_ASK: {price} > deepest ask {deepest}, side complete"))
            return _C, f"TAKER_BUY_AT_OR_THROUGH_ASK: ask {ask}"
        if bid is None:
            return _X, "TAKER_SELL_NO_BIDS: no captured bid to hit"
        if price > add(bid, tol):
            return _I, f"TAKER_SELL_ABOVE_BEST_BID: {price} > bid {bid}"
        lowest = book.bids[-1].price
        if price < sub(lowest, tol):
            return ((_X, f"TAKER_SELL_BEYOND_CAPTURED_DEPTH: {price} < lowest captured bid {lowest} (truncated)")
                    if book.bids_truncated else
                    (_I, f"TAKER_SELL_BELOW_EVERY_BID: {price} < lowest bid {lowest}, side complete"))
        return _C, f"TAKER_SELL_AT_OR_THROUGH_BID: bid {bid}"
    # MAKER: a resting order, filled by someone else's arrival.
    if bid is None or ask is None:
        return _X, "MAKER_NEEDS_BOTH_SIDES: the inside quote is not fully captured"
    if buying:
        if price > add(ask, tol):
            return _I, f"MAKER_BUY_ABOVE_ASK: a resting bid at {price} would have crossed ask {ask}"
        if price < sub(bid, tol):
            return _X, f"MAKER_BUY_BELOW_BEST_BID: {price} < bid {bid}; only a sweep the capture cannot show reaches it"
        return _C, f"MAKER_BUY_INSIDE_QUOTE: bid {bid} / ask {ask}"
    if price < sub(bid, tol):
        return _I, f"MAKER_SELL_BELOW_BID: a resting offer at {price} would have crossed bid {bid}"
    if price > add(ask, tol):
        return _X, f"MAKER_SELL_ABOVE_BEST_ASK: {price} > ask {ask}; only a sweep the capture cannot show reaches it"
    return _C, f"MAKER_SELL_INSIDE_QUOTE: bid {bid} / ask {ask}"


def _unit_problem(o: WalletObservation, tol: Decimal) -> str | None:
    if o.price_basis not in KNOWN_PRICE_BASES:
        return f"UNKNOWN_PRICE_UNIT: basis {o.price_basis!r}"
    assert o.price is not None
    if not (ZERO < o.price < Decimal(1)):
        return f"PRICE_OUTSIDE_UNIT_INTERVAL: {o.price} (wrong unit or scale?)"
    cash_legs = [a for a in (o.paid if o.action is Action.TRADE_BUY else o.received) if a.is_cash]
    if len(cash_legs) == 1 and o.native_quantity:
        implied = ratio(cash_legs[0].quantity, o.native_quantity)
        if implied is not None and abs(sub(implied, o.price)) > tol:
            return f"PRICE_AND_CASH_LEG_DISAGREE: price {o.price}, cash/quantity {implied}"
    return None


def price_consistency(observations: Sequence[WalletObservation], books: BookProvider, *, tolerance: Decimal,
                      max_book_age: timedelta, max_clock_skew: timedelta) -> tuple[PriceConsistencyRow, ...]:
    """Role-aware: could the captured book have produced each trade's price for its stated role?

    `max_clock_skew` bounds the disagreement between the observation source's clock and the book
    source's clock. A book captured less than that before the trade may postdate it, so it cannot
    judge the trade. Non-trades (transfers, splits, rewards...) carry no execution price: no row.
    """
    if tolerance < 0 or max_clock_skew < timedelta(0) or max_book_age < timedelta(0):
        raise ValueError("tolerance, clock skew and book age bounds must be non-negative")
    out = []
    for o in observations:
        if not o.directional:
            continue
        buying = o.action is Action.TRADE_BUY
        side = "BUY" if buying else "SELL"
        prov = {"observation_source": o.source, "observation_raw_ref": o.raw_ref, "parser_version": o.parser_version,
                "observation_source_time": utc_text(o.source_time)}
        if o.liquidity_role_source:
            prov["role_source"] = o.liquidity_role_source

        def row(verdict: PriceConsistency, reasons: tuple[str, ...], consistent: tuple[LiquidityRole, ...] = (),
                book: Book | None = None) -> PriceConsistencyRow:
            if book is not None:
                prov["book_instrument"] = book.instrument_id
                for key, value in (("book_source", book.source), ("book_raw_ref", book.raw_ref)):
                    if value:
                        prov[key] = value
                if book.received_at is not None:
                    prov["book_received_at"] = utc_text(book.received_at)
            return PriceConsistencyRow(o.observation_id, side, o.liquidity_role, verdict, consistent, reasons, o.price,
                                       None if book is None else book.best_bid(),
                                       None if book is None else book.best_ask(),
                                       None if book is None else book.captured_at, tuple(sorted(prov.items())))

        if o.price is None or o.instrument_id is None:
            out.append(row(_X, ("MISSING_PRICE",)))
            continue
        unit = _unit_problem(o, tolerance)
        if unit:
            out.append(row(_X, (unit,)))
            continue
        if o.receipt_time < o.source_time - max_clock_skew:
            out.append(row(_X, ("SOURCE_CLOCK_INCONSISTENT: received before the stated trade time",)))
            continue
        try:
            book = books(o.instrument_id, o.source_time)
        except ValueError as exc:  # a crossed, locked or otherwise invalid capture
            out.append(row(_X, (f"BOOK_INVALID: {exc}",)))
            continue
        if book is None:
            out.append(row(_X, ("NO_BOOK",)))
            continue
        if book.received_at is not None and book.received_at < book.captured_at - max_clock_skew:
            out.append(row(_X, ("BOOK_CLOCK_INCONSISTENT: received before its stated capture time",), book=book))
            continue
        gap = o.source_time - book.captured_at
        if gap < timedelta(0):
            out.append(row(_X, ("BOOK_AFTER_TRADE",), book=book))
            continue
        if gap < max_clock_skew:
            out.append(row(_X, ("BOOK_TIME_AMBIGUOUS_UNDER_CLOCK_SKEW: the book may postdate the trade",), book=book))
            continue
        if gap + max_clock_skew > max_book_age:
            out.append(row(_X, (f"STALE_BOOK: up to {int((gap + max_clock_skew).total_seconds())}s old",), book=book))
            continue
        candidates = ((LiquidityRole.MAKER, LiquidityRole.TAKER)
                      if o.liquidity_role in (LiquidityRole.UNKNOWN, LiquidityRole.MIXED) else (o.liquidity_role,))
        judged = [(r, *_judge(buying, r, o.price, book, tolerance)) for r in candidates]
        consistent = tuple(r for r, v, _ in judged if v is _C)
        reasons = tuple(f"{r.value}: {why}" for r, _, why in judged)
        if consistent:
            verdict = _C
            if o.liquidity_role in (LiquidityRole.UNKNOWN, LiquidityRole.MIXED) and len(consistent) < len(candidates):
                reasons += (f"CONSISTENT_ONLY_AS_{'_OR_'.join(r.value for r in consistent)}: role is "
                            f"{o.liquidity_role.value}, not inferred",)
        elif all(v is _I for _, v, _ in judged):
            verdict = _I
        else:
            verdict = _X
        out.append(row(verdict, reasons, consistent, book))
    return tuple(out)


# --- Contamination evidence ------------------------------------------------------------------------

class Observability(str, Enum):
    OBSERVED = "OBSERVED"  # every input the detector needs is present
    PARTIAL = "PARTIAL"  # present for some observations only
    UNOBSERVABLE = "UNOBSERVABLE"  # the detector cannot run on these inputs


class EvidenceKind(str, Enum):
    SHARED_ACTIVITY_TIMING = "SHARED_ACTIVITY_TIMING"
    STATED_FUNDING_LINK = "STATED_FUNDING_LINK"
    ROUND_TRIP_CHURN = "ROUND_TRIP_CHURN"
    SELF_TRADE_REPORTED_COUNTERPARTY = "SELF_TRADE_REPORTED_COUNTERPARTY"
    CIRCULAR_FLOW_REPORTED_COUNTERPARTY = "CIRCULAR_FLOW_REPORTED_COUNTERPARTY"


class FlagStatus(str, Enum):
    PROVISIONAL_FLAG = "PROVISIONAL_FLAG"  # a heuristic pattern, never a finding
    NO_FLAG = "NO_FLAG"  # the detector ran and found nothing (not a clearance of the account)
    UNOBSERVABLE = "UNOBSERVABLE"  # the detector could not run: not clean, not flagged


@dataclass(frozen=True)
class ContaminationEvidence:
    detector: str
    kind: EvidenceKind
    status: FlagStatus
    observability: Observability
    accounts: tuple[str, ...]
    observation_ids: tuple[str, ...]
    uncertainty: tuple[str, ...]
    detail: str
    provisional: bool = True

    def __post_init__(self) -> None:
        if not self.provisional:
            raise ValueError("contamination evidence is always provisional")
        if self.status is FlagStatus.PROVISIONAL_FLAG and NOT_PROOF not in self.uncertainty:
            raise ValueError("every flag must state that it is not proof of common ownership or wrongdoing")
        if (self.status is FlagStatus.UNOBSERVABLE) != (self.observability is Observability.UNOBSERVABLE):
            raise ValueError("UNOBSERVABLE status and observability go together")

    def to_dict(self) -> dict:
        return {"detector": self.detector, "kind": self.kind.value, "status": self.status.value,
                "observability": self.observability.value, "accounts": list(self.accounts),
                "observation_ids": list(self.observation_ids), "uncertainty": list(self.uncertainty),
                "detail": self.detail, "provisional": self.provisional}


def shared_activity_evidence(observations: Sequence[WalletObservation], *, window: timedelta, min_shared: int,
                             min_overlap: Decimal, funding_sources: Mapping[str, str] | None = None,
                             public_events: Sequence[datetime] = ()) -> tuple[ContaminationEvidence, ...]:
    """Pairwise shared-activity and stated-funding links (the evidence behind `co_trading_clusters`).

    `public_events` are times of public news or announcements. Trades shortly after one have an
    ordinary alternative explanation, and the flag says so."""
    out = []
    by_id = {o.observation_id: o for o in observations}
    for a, b, ids in _shared_trade_pairs(observations, window=window, min_shared=min_shared, min_overlap=min_overlap):
        uncertainty = [NOT_PROOF, "COMMON_PUBLIC_INFORMATION_NOT_EXCLUDED", "LIQUIDITY_ROLES_NOT_CONSIDERED"]
        if any(timedelta(0) <= by_id[i].source_time - e <= window for i in ids for e in public_events):
            uncertainty.append("COINCIDENT_PUBLIC_EVENT: trades follow a public event within the window")
        out.append(ContaminationEvidence("shared_activity", EvidenceKind.SHARED_ACTIVITY_TIMING,
                                         FlagStatus.PROVISIONAL_FLAG, Observability.OBSERVED, (a, b), ids,
                                         tuple(sorted(uncertainty)),
                                         f"{len(ids)} same-token, same-direction trades within {window}"))
    accounts = sorted({o.account.key for o in observations})
    for source, members in sorted(_funding_groups(accounts, funding_sources).items()):
        if len(members) > 1:
            out.append(ContaminationEvidence(
                "stated_funding", EvidenceKind.STATED_FUNDING_LINK, FlagStatus.PROVISIONAL_FLAG,
                Observability.OBSERVED, tuple(members), (),
                (NOT_PROOF, "SHARED_FUNDING_SOURCE_MAY_BE_AN_EXCHANGE_OR_BRIDGE"), f"stated funding source {source}"))
    if not out:
        out.append(ContaminationEvidence("shared_activity", EvidenceKind.SHARED_ACTIVITY_TIMING, FlagStatus.NO_FLAG,
                                         Observability.OBSERVED, tuple(accounts), (), (),
                                         "no pair met the shared-activity thresholds"))
    return tuple(out)


def churn_evidence(observations: Sequence[WalletObservation], *, max_hold: timedelta,
                   threshold: Decimal) -> tuple[ContaminationEvidence, ...]:
    """Per account, quickly reversed turnover (`round_trip_share`) as a provisional flag. Round trips
    made of maker fills are what market making looks like, and the flag says so."""
    out = []
    by_account: dict[str, list[WalletObservation]] = {}
    for o in observations:
        by_account.setdefault(o.account.key, []).append(o)
    for account, rows in sorted(by_account.items()):
        share = round_trip_share(rows, max_hold=max_hold)
        if share is None:
            continue
        trades = [o for o in rows if o.directional]
        roles = {o.liquidity_role for o in trades}
        notes = [NOT_PROOF]
        if roles & {LiquidityRole.MAKER, LiquidityRole.MIXED}:
            notes.append("MAKER_ROUND_TRIPS_ARE_CONSISTENT_WITH_MARKET_MAKING")
        if LiquidityRole.UNKNOWN in roles:
            notes.append("LIQUIDITY_ROLE_UNKNOWN")
        if any(o.action in (Action.TRANSFER_IN, Action.TRANSFER_OUT) for o in rows):
            notes.append("TOKEN_TRANSFERS_PRESENT: legs may continue off this account")
        flagged = share >= threshold
        out.append(ContaminationEvidence(
            "churn", EvidenceKind.ROUND_TRIP_CHURN, FlagStatus.PROVISIONAL_FLAG if flagged else FlagStatus.NO_FLAG,
            Observability.OBSERVED, (account,), tuple(sorted(o.observation_id for o in trades)) if flagged else (),
            tuple(sorted(notes)) if flagged else (),
            f"round-trip share {decimal_text(share)} vs threshold {decimal_text(threshold)} within {max_hold}"))
    return tuple(out)


def counterparty_flow_evidence(observations: Sequence[WalletObservation], *,
                               window: timedelta) -> tuple[ContaminationEvidence, ...]:
    """Self-trades and circular token flows, using only source-reported counterparties.

    Without any reported counterparty both detectors are UNOBSERVABLE: absence of evidence here is
    not evidence of absence. A flow is a token moving seller -> buyer; a circle returns a token to an
    account it left, within `window`."""
    trades = [o for o in observations if o.directional]
    with_cp = [o for o in trades if o.counterparty is not None]
    if not with_cp:
        return tuple(ContaminationEvidence(name, kind, FlagStatus.UNOBSERVABLE, Observability.UNOBSERVABLE, (), (),
                                           ("NO_SOURCE_REPORTED_COUNTERPARTIES",),
                                           "no observation carries a source-reported counterparty")
                     for name, kind in (("self_trade", EvidenceKind.SELF_TRADE_REPORTED_COUNTERPARTY),
                                        ("circular_flow", EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY)))
    observability = Observability.OBSERVED if len(with_cp) == len(trades) else Observability.PARTIAL
    base = (NOT_PROOF, "COUNTERPARTY_AS_REPORTED_BY_SOURCE") + (
        ("COUNTERPARTY_MISSING_FOR_SOME_TRADES",) if observability is Observability.PARTIAL else ())
    out = []
    selfs = sorted((o for o in with_cp if o.counterparty is not None and o.counterparty.key == o.account.key),
                   key=lambda o: o.observation_id)
    for o in selfs:
        out.append(ContaminationEvidence("self_trade", EvidenceKind.SELF_TRADE_REPORTED_COUNTERPARTY,
                                         FlagStatus.PROVISIONAL_FLAG, observability, (o.account.key,),
                                         (o.observation_id,), tuple(sorted(base + ("SELF_MATCH_MAY_BE_ACCIDENTAL",))),
                                         "the source reports this account on both sides of the fill"))
    if not selfs:
        out.append(ContaminationEvidence("self_trade", EvidenceKind.SELF_TRADE_REPORTED_COUNTERPARTY,
                                         FlagStatus.NO_FLAG, observability, (), (), (),
                                         f"{len(with_cp)} trades with a reported counterparty; none self-matched"))
    # Directed token flows, one per fill even when both sides report it.
    edges: dict[tuple, tuple[str, str, str, datetime, str]] = {}
    for o in with_cp:
        assert o.counterparty is not None and o.instrument_id is not None
        if o.counterparty.key == o.account.key:
            continue
        frm, to = (o.counterparty.key, o.account.key) if o.action is Action.TRADE_BUY else (o.account.key,
                                                                                            o.counterparty.key)
        key = (frm, to, o.instrument_id, o.source_time, decimal_text(o.native_quantity or ZERO))
        if key not in edges or o.observation_id < edges[key][4]:
            edges[key] = (frm, to, o.instrument_id, o.source_time, o.observation_id)
    flows = sorted(edges.values(), key=lambda e: (e[3], e[4]))
    cycles: dict[frozenset[str], tuple[tuple[str, ...], tuple[str, ...]]] = {}

    def walk(start: str, path: list[tuple[str, str, str, datetime, str]]) -> None:
        last = path[-1]
        for e in flows:
            if e[2] != last[2] or e[0] != last[1] or e[3] < last[3] or e[3] - path[0][3] > window or e in path:
                continue
            if e[1] == start:
                ids = frozenset(x[4] for x in (*path, e))
                cycles.setdefault(ids, (tuple(sorted({x[0] for x in (*path, e)})), tuple(sorted(ids))))
            elif len(path) < 8 and all(e[1] != x[0] for x in path):
                walk(start, [*path, e])

    for e in flows:
        walk(e[0], [e])
    for _, (accounts, ids) in sorted(cycles.items(), key=lambda kv: kv[1][1]):
        out.append(ContaminationEvidence("circular_flow", EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY,
                                         FlagStatus.PROVISIONAL_FLAG, observability, accounts, ids,
                                         tuple(sorted(base + ("REVERSALS_CAN_BE_ORDINARY_TRADING",))),
                                         f"a token returns to its origin through {len(accounts)} accounts "
                                         f"within {window}"))
    if not cycles:
        out.append(ContaminationEvidence("circular_flow", EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY,
                                         FlagStatus.NO_FLAG, observability, (), (), (),
                                         f"{len(flows)} reported flows; no token returned to its origin"))
    return tuple(out)


# --- The combined v2 report and its versioned reader -----------------------------------------------

@dataclass(frozen=True)
class QualityParams:
    tolerance: Decimal
    max_book_age: timedelta
    max_clock_skew: timedelta
    shared_window: timedelta
    min_shared: int
    min_overlap: Decimal
    churn_max_hold: timedelta
    churn_threshold: Decimal
    circular_window: timedelta

    def to_dict(self) -> dict:
        return {"tolerance": decimal_text(self.tolerance), "max_book_age_s": self.max_book_age.total_seconds(),
                "max_clock_skew_s": self.max_clock_skew.total_seconds(),
                "shared_window_s": self.shared_window.total_seconds(), "min_shared": self.min_shared,
                "min_overlap": decimal_text(self.min_overlap),
                "churn_max_hold_s": self.churn_max_hold.total_seconds(),
                "churn_threshold": decimal_text(self.churn_threshold),
                "circular_window_s": self.circular_window.total_seconds()}


@dataclass(frozen=True)
class QualityReport:
    """Role, price consistency and contamination, side by side and never combined into a score."""

    schema: str
    data_class: DataClass
    params: QualityParams
    roles: tuple[tuple[str, RoleEvidence], ...]  # observation id -> stated role, for every trade
    price: tuple[PriceConsistencyRow, ...]
    contamination: tuple[ContaminationEvidence, ...]

    def to_dict(self) -> dict:
        return {"schema": self.schema, "data_class": self.data_class.value, "role_aware": True,
                "params": self.params.to_dict(),
                "roles": [{"observation_id": oid, "role": r.role.value, "source": r.source} for oid, r in self.roles],
                "price_consistency": [r.to_dict() for r in self.price],
                "contamination": [c.to_dict() for c in self.contamination],
                "disclaimer": "Heuristic diagnostics on pseudonymous accounts; not findings about any person."}


def quality_report(observations: Sequence[WalletObservation], books: BookProvider, *, params: QualityParams,
                   data_class: DataClass, funding_sources: Mapping[str, str] | None = None,
                   public_events: Sequence[datetime] = ()) -> QualityReport:
    if not isinstance(data_class, DataClass):
        raise ValueError("data_class must be a DataClass")
    if data_class is DataClass.OBSERVED and any(o.synthetic for o in observations):
        raise ValueError("synthetic observations cannot be reported as OBSERVED")
    roles = tuple((o.observation_id, liquidity_role(o)) for o in observations if o.directional)
    price = price_consistency(observations, books, tolerance=params.tolerance, max_book_age=params.max_book_age,
                              max_clock_skew=params.max_clock_skew)
    contamination = (
        shared_activity_evidence(observations, window=params.shared_window, min_shared=params.min_shared,
                                 min_overlap=params.min_overlap, funding_sources=funding_sources,
                                 public_events=public_events)
        + churn_evidence(observations, max_hold=params.churn_max_hold, threshold=params.churn_threshold)
        + counterparty_flow_evidence(observations, window=params.circular_window))
    return QualityReport(QUALITY_SCHEMA, data_class, params, roles, price, contamination)


@dataclass(frozen=True)
class LegacyOffMarketView:
    schema: str
    rows: tuple[OffMarketRow, ...]
    role_aware: bool = False
    interpretation: str = LEGACY_V1_NOTE


@dataclass(frozen=True)
class QualityView:
    schema: str
    data_class: DataClass
    roles: dict[str, LiquidityRole]
    price: dict[str, PriceConsistency]
    contamination: tuple[tuple[str, EvidenceKind, FlagStatus, Observability], ...]
    role_aware: bool = True


def read_threat_report(payload: Mapping) -> LegacyOffMarketView | QualityView:
    """Read a serialized threat report by its explicit schema. v1 stays v1 (role-unaware, never
    upgraded: it has no role to upgrade with). An unknown schema is refused."""
    schema = payload.get("schema")
    if schema == OFF_MARKET_V1_SCHEMA:
        return LegacyOffMarketView(schema, tuple(OffMarketRow(r["observation_id"], FillJudgement(r["judgement"]),
                                                              r["detail"]) for r in payload["rows"]))
    if schema == QUALITY_SCHEMA:
        return QualityView(schema, DataClass(payload["data_class"]),
                           {r["observation_id"]: LiquidityRole(r["role"]) for r in payload["roles"]},
                           {r["observation_id"]: PriceConsistency(r["verdict"]) for r in payload["price_consistency"]},
                           tuple((c["detector"], EvidenceKind(c["kind"]), FlagStatus(c["status"]),
                                  Observability(c["observability"])) for c in payload["contamination"]))
    raise ValueError(f"unknown threat report schema {schema!r}")


# --- Follower copyability (read from the canonical replay) -----------------------------------------

class Copyability(str, Enum):
    COPYABLE = "COPYABLE"  # our later arrival filled in full at the simulated price
    PARTIALLY_COPYABLE = "PARTIALLY_COPYABLE"
    NOT_COPYABLE = "NOT_COPYABLE"  # a fresh, valid book could not fill it within our limits and cash
    UNKNOWN = "UNKNOWN"  # no valid fresh book, or the request outcome is unknown: never a fill
    NOT_ATTEMPTED = "NOT_ATTEMPTED"  # the policy skipped or quarantined it; kept in the denominator


# `FollowerFill.reason` prefixes that mean "no valid book to judge with", not "no liquidity".
_UNKNOWN_BOOK_REASONS = ("MISSING_BOOK", "STALE_BOOK", "BOOK_FROM_THE_FUTURE")


@dataclass(frozen=True)
class CopyabilityVerdict:
    signal_id: str
    leader_key: str
    side: str
    verdict: Copyability
    leader_price: Decimal  # the leader's own print: a reference, never a price we could get
    leader_price_consistency: PriceConsistency | None  # carried alongside, never used to decide
    decision: str
    reason: str
    fill_status: str | None
    requested: Decimal | None
    filled: Decimal | None
    follower_avg_price: Labeled
    adverse_gap_per_unit: Labeled  # follower worse than leader per unit (buy: avg - leader; sell: leader - avg)
    fee: Labeled
    decided_at: datetime | None
    arrived_at: datetime | None
    book_age_at_arrival: timedelta | None  # None: unknown (no provider given, no book, or an invalid one)
    replay_version: str = REPLAY_VERSION

    def to_dict(self) -> dict:
        def t(v: Decimal | None) -> str | None:
            return None if v is None else decimal_text(v)
        return {"schema": COPYABILITY_SCHEMA, "signal_id": self.signal_id, "leader_key": self.leader_key,
                "side": self.side, "verdict": self.verdict.value, "leader_price": t(self.leader_price),
                "leader_price_consistency": None if self.leader_price_consistency is None
                else self.leader_price_consistency.value,
                "decision": self.decision, "reason": self.reason, "fill_status": self.fill_status,
                "requested": t(self.requested), "filled": t(self.filled),
                "follower_avg_price": self.follower_avg_price.to_dict(),
                "adverse_gap_per_unit": self.adverse_gap_per_unit.to_dict(), "fee": self.fee.to_dict(),
                "decided_at": None if self.decided_at is None else utc_text(self.decided_at),
                "arrived_at": None if self.arrived_at is None else utc_text(self.arrived_at),
                "book_age_at_arrival_s": None if self.book_age_at_arrival is None
                else self.book_age_at_arrival.total_seconds(), "replay_version": self.replay_version,
                "label": "FOLLOWER_SIMULATED"}


def follower_copyability(result: ReplayResult, signals: Sequence[FollowSignal], *, books: BookProvider | None = None,
                         leader_consistency: Mapping[str, PriceConsistencyRow] | None = None,
                         ) -> tuple[CopyabilityVerdict, ...]:
    """One typed verdict per replayed signal outcome, read from `replay.replay`'s fills.

    The leader's price consistency is carried for reference only. `books`, when given, is re-read at
    our arrival time only to report the age of the book the replay used; nothing is re-filled."""
    by_id = {s.signal_id: s for s in signals}
    out = []
    for oc in result.outcomes:
        s = by_id[oc.signal_id]
        lc = (leader_consistency or {}).get(oc.signal_id)
        consistency = None if lc is None else lc.verdict
        side = "BUY" if s.action is Action.TRADE_BUY else "SELL"
        f = oc.fill
        if f is None:
            out.append(CopyabilityVerdict(oc.signal_id, oc.leader_key, side, Copyability.NOT_ATTEMPTED, s.leader_price,
                                          consistency, oc.decision, oc.reason, None, None, None,
                                          Labeled.unknown("not attempted"), Labeled.unknown("not attempted"),
                                          Labeled.unknown("not attempted"), None, None, None))
            continue
        if f.status is FillStatus.FILLED:
            verdict = Copyability.COPYABLE
        elif f.status is FillStatus.PARTIAL:
            verdict = Copyability.PARTIALLY_COPYABLE
        elif f.status is FillStatus.UNKNOWN or f.reason.startswith(_UNKNOWN_BOOK_REASONS):
            verdict = Copyability.UNKNOWN
        else:
            verdict = Copyability.NOT_COPYABLE
        avg = ratio(f.gross_cash, f.filled) if f.filled > 0 else None
        avg_l = Labeled(avg, Basis.ESTIMATED, "simulated from captured levels") if avg is not None else \
            Labeled.unknown("no simulated fill")
        gap = None if avg is None else (sub(avg, s.leader_price) if side == "BUY" else sub(s.leader_price, avg))
        gap_l = Labeled(gap, Basis.ESTIMATED, "follower minus leader, per unit") if gap is not None else \
            Labeled.unknown("no simulated fill")
        age = None
        if books is not None:
            try:
                b = books(f.instrument_id, f.arrived_at)
            except ValueError:
                b = None
            if b is not None and b.captured_at <= f.arrived_at:
                age = f.arrived_at - b.captured_at
        out.append(CopyabilityVerdict(oc.signal_id, oc.leader_key, side, verdict, s.leader_price, consistency,
                                      oc.decision, f.reason, f.status.value, f.requested, f.filled, avg_l, gap_l,
                                      f.fee, f.decided_at, f.arrived_at, age))
    return tuple(out)
