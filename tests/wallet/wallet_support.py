"""Builders for wallet-intelligence tests. Every value is SYNTHETIC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from edge_lab.opportunity import DepthLevel
from edge_lab.wallet_intel.events import Action, AssetAmount, ChainFinality, WalletObservation, token_asset
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.identity import AccountRef
from edge_lab.wallet_intel.market_data import Book
from edge_lab.wallet_intel.policy import Enrollment, FollowSignal, PolicyLimits
from edge_lab.wallet_intel.replay import ReplayConfig, zero_fee_documented

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "wallet" / "polymarket_v2"
D = Decimal


def at(minutes: float = 0, *, hours: float = 0, days: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes, hours=hours, days=days)


def acct(n: int, product: str = "synthetic_venue") -> AccountRef:
    return AccountRef(product, f"0xsynthetic{n:04d}")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


_counter = [0]


def obs(account: AccountRef, action: Action, token: str = "m1-yes", qty: str | int = 10, price: str = "0.40",
        when: datetime | None = None, *, market: str = "m1", event: str | None = None, outcome: int | None = None,
        tx: str | None = None, sub_index: int | None = None, event_id: str | None = None,
        fee: Decimal | None = D(0), receipt_delay: timedelta = timedelta(seconds=30),
        category: str | None = "cat-a", ambiguities: tuple[str, ...] = (), cash: str | None = None) -> WalletObservation:
    _counter[0] += 1
    when = when or at()
    q = D(qty)
    p = D(price)
    if outcome is None:
        outcome = 0 if token.endswith("yes") else 1
    notional = D(cash) if cash is not None else q * p
    paid: tuple[AssetAmount, ...] = ()
    received: tuple[AssetAmount, ...] = ()
    if action is Action.TRADE_BUY:
        paid, received = (AssetAmount("USDC", notional),), (AssetAmount(token_asset(token), q),)
    elif action is Action.TRADE_SELL:
        paid, received = (AssetAmount(token_asset(token), q),), (AssetAmount("USDC", notional),)
    elif action is Action.TRANSFER_IN:
        received = (AssetAmount(token_asset(token), q),)
    elif action is Action.TRANSFER_OUT:
        paid = (AssetAmount(token_asset(token), q),)
    elif action is Action.REWARD:
        received = (AssetAmount("USDC", notional),)
    elif action is Action.SPLIT:
        paid = (AssetAmount("USDC", q),)
        received = (AssetAmount(token_asset(f"{market}-yes"), q), AssetAmount(token_asset(f"{market}-no"), q))
    elif action is Action.MERGE:
        received = (AssetAmount("USDC", q),)
        paid = (AssetAmount(token_asset(f"{market}-yes"), q), AssetAmount(token_asset(f"{market}-no"), q))
    elif action is Action.REDEEM:
        paid = (AssetAmount(token_asset(token), q),)
        if notional > 0:
            received = (AssetAmount("USDC", notional),)
    directional = action in (Action.TRADE_BUY, Action.TRADE_SELL)
    return WalletObservation(
        source="synthetic", product=account.product, chain=None, account=account, source_event_id=event_id,
        transaction_id=tx or f"0xsyntx{_counter[0]:06d}", sub_index=sub_index, occurrence=0, action=action,
        raw_action=action.value, instrument_id=token, market_id=market, event_id=event or f"evt-{market}",
        outcome_index=outcome, native_quantity=q, native_decimals=None, paid=paid, received=received,
        price=p if directional else None, price_basis="USDC_PER_SHARE" if directional else None,
        fee=Labeled.observed(fee) if fee is not None else Labeled.unknown("synthetic: fee not reported"),
        source_time=when, receipt_time=when + receipt_delay, finality=ChainFinality.FINAL,
        raw_ref=f"synthetic:{_counter[0]}", parser_version="test", category=category, ambiguities=ambiguities,
        synthetic=True)


def book(token: str = "m1-yes", *, bid: str | None = "0.39", ask: str | None = "0.41", size: str = "100",
         captured: datetime | None = None, levels: int = 2, truncated: bool = False) -> Book:
    def side(start: str | None, step: Decimal) -> tuple[DepthLevel, ...]:
        if start is None:
            return ()
        return tuple(DepthLevel(D(start) + step * i, D(size)) for i in range(levels))
    return Book(token, side(bid, D("-0.01")), side(ask, D("0.01")), captured or at(), bids_truncated=truncated,
                asks_truncated=truncated)


class Books:
    """A fixture book provider: the latest registered book at or before the request time."""

    def __init__(self, *books: Book) -> None:
        self._books = sorted(books, key=lambda b: b.captured_at)

    def __call__(self, token: str, when: datetime) -> Book | None:
        best = None
        for b in self._books:
            if b.instrument_id == token and b.captured_at <= when:
                best = b
        return best


def limits(**kw) -> PolicyLimits:  # type: ignore[no-untyped-def]
    base = dict(risk_per_signal=D(10), per_leader=D(100), per_cluster=D(100), per_event=D(50), per_strategy=D(500),
                total=D(500), quantity_step=D(1), min_quantity=D(1), min_leader_notional=D(1),
                max_signal_age=timedelta(minutes=30), min_price=D("0.05"), max_price=D("0.95"),
                max_price_above_leader=D("0.05"))
    base.update(kw)
    return PolicyLimits(**base)


def config(**kw) -> ReplayConfig:  # type: ignore[no-untyped-def]
    base = dict(detection_delay=timedelta(seconds=60), processing_delay=timedelta(seconds=1),
                arrival_delay=timedelta(seconds=1), max_book_age=timedelta(minutes=10), fee_fn=zero_fee_documented)
    base.update(kw)
    return ReplayConfig(**base)


def signal(sid: str, action: Action = Action.TRADE_BUY, *, leader: str = "L1", token: str = "m1-yes",
           qty: str = "100", price: str = "0.40", when: datetime | None = None, delay: timedelta = timedelta(minutes=1),
           before: str | None = "0", cluster: str | None = None, event: str = "evt-m1", market: str = "m1",
           strategy: str = "s1") -> FollowSignal:
    when = when or at()
    return FollowSignal(sid, leader, cluster or leader, strategy, token, market, event, action, D(qty), D(price), when,
                        when + delay, None if before is None else D(before))


def enrolled(*leaders: str, when: datetime | None = None) -> dict[str, Enrollment]:
    return {k: Enrollment(k, when or at(-60 * 24)) for k in leaders}
