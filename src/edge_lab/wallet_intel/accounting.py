"""Leader reconstruction: cash-flow-aware accounting and leader dimensions (W3, ADR 0045).

LEADER_OBSERVED_ECONOMICS: what the public record says the leader's account did. It is never a
follower result (replay.py owns that), and it is never a ranking score.

Separated lines (directive §9), each `Labeled`; UNKNOWN carries no number:
- contributions and withdrawals (cash transfers in and out);
- realized trading P&L, per market, from **cash flows**: a market's P&L is known only once all of
  its tokens are flat or resolved, the history is complete and no token arrived by transfer;
- unrealized positions, valued only at an executable bid with enough depth for the whole holding
  and fresh enough, or at a final resolution payout. A last print or a vendor mark is never
  withdrawable value;
- fees (UNKNOWN when the source reports none, as Polymarket v2 activity does: net P&L is then
  UNKNOWN, and gross is labelled gross);
- rewards, rebates and referrals, never counted as trading skill;
- inventory transfers (tokens in or out with unknown cost basis);
- equity (needs a known opening balance, observed cash flows, complete history, known fees and
  every open position valued);
- capital employed (the peak net trading outlay), turnover, remaining risk and coverage.

**Unknown cost basis stays unknown and no ROI is invented.** ROI is produced only when realized net
P&L and capital employed are both known on complete coverage. There is no path from a vendor's
displayed profit counter (positions `realized_pnl`, `total_pnl`) to any figure here.

`leader_dimensions` reports the directive's dimensions separately, with uncertainty, and with
Beta-binomial shrinkage on per-event win rates. There is deliberately no single score. Hidden
hedges are always UNKNOWN: other venues and accounts cannot be observed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from .events import Action, WalletObservation
from .exact import ZERO, Basis, Labeled, add, decimal_text, mul, ratio, sub
from .stats import BetaPrior, ShrunkRate, shrunk_rate
from .timeutil import require_aware, utc_text

ACCOUNTING_VERSION = "wallet-accounting-v1"


class MarkKind(str, Enum):
    EXECUTABLE_BID = "EXECUTABLE_BID"  # a captured bid we could sell into, with its depth
    RESOLVED_PAYOUT = "RESOLVED_PAYOUT"  # a final settlement value
    LAST_PRINT = "LAST_PRINT"  # never withdrawable value
    VENDOR_MARK = "VENDOR_MARK"  # a vendor's displayed price or value; never withdrawable value


@dataclass(frozen=True)
class Mark:
    instrument_id: str
    kind: MarkKind
    price: Decimal
    depth: Decimal | None  # bid size at or above `price` (EXECUTABLE_BID only)
    as_of: datetime

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")


class MarketState(str, Enum):
    CLOSED = "CLOSED"  # every token flat
    SETTLED = "SETTLED"  # holdings remain, all at final payouts
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


@dataclass
class _Market:
    market_id: str
    event_id: str | None
    category: str | None
    trading_cash: Decimal = ZERO  # + received, - paid, trades/splits/merges/redemptions/conversions
    fees: Decimal = ZERO
    fees_unknown: int = 0
    holdings: dict[str, Decimal] = field(default_factory=dict)
    unknown_reasons: list[str] = field(default_factory=list)
    transferred_tokens: bool = False
    buy_notional: Decimal = ZERO
    first_at: datetime | None = None
    last_at: datetime | None = None


@dataclass(frozen=True)
class MarketResult:
    market_id: str
    event_id: str | None
    category: str | None
    state: MarketState
    pnl_gross: Labeled
    pnl_net: Labeled
    open_value: Labeled  # liquidation value of what is still held (0 when closed)
    opened_at: datetime | None
    closed_at: datetime | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LeaderAccount:
    account_key: str
    as_of: datetime
    contributions: Labeled
    withdrawals: Labeled
    realized_trading_pnl_gross: Labeled
    realized_trading_pnl_net: Labeled
    unrealized_value: Labeled
    fees: Labeled
    rewards: Labeled
    inventory_transfers: tuple[tuple[str, str, Decimal], ...]  # (direction, asset, quantity)
    equity: Labeled
    capital_employed: Labeled
    turnover: Labeled
    remaining_risk: Labeled
    roi_net: Labeled
    roi_gross: Labeled
    coverage_complete: bool
    coverage_notes: tuple[str, ...]
    markets: tuple[MarketResult, ...]
    economics_label: str = "LEADER_OBSERVED_ECONOMICS"

    def to_dict(self) -> dict:
        lab = {k: getattr(self, k).to_dict() for k in (
            "contributions", "withdrawals", "realized_trading_pnl_gross", "realized_trading_pnl_net",
            "unrealized_value", "fees", "rewards", "equity", "capital_employed", "turnover", "remaining_risk",
            "roi_net", "roi_gross")}
        return {"economics_label": self.economics_label, "account": self.account_key, "as_of": utc_text(self.as_of),
                **lab, "inventory_transfers": [[d, a, decimal_text(q)] for d, a, q in self.inventory_transfers],
                "coverage_complete": self.coverage_complete, "coverage_notes": list(self.coverage_notes),
                "markets": [{"market_id": m.market_id, "event_id": m.event_id, "state": m.state.value,
                             "pnl_gross": m.pnl_gross.to_dict(), "pnl_net": m.pnl_net.to_dict(),
                             "reasons": list(m.reasons)} for m in self.markets]}


def _sum_known(values: Sequence[Labeled], note: str) -> Labeled:
    if any(not v.known for v in values):
        return Labeled.unknown(note)
    return Labeled(add(*(v.value for v in values if v.value is not None)), Basis.OBSERVED)


def reconstruct(observations: Sequence[WalletObservation], *, as_of: datetime, history_complete: bool,
                cash_flows_observed: bool, opening_balance: Labeled, marks: Mapping[str, Mark],
                mark_max_age: timedelta) -> LeaderAccount:
    """Account economics from effective observations (`ObservationLog.as_known_at(as_of)`).

    `history_complete`: the observations cover the account from its start (otherwise prior
    holdings, and every P&L that depends on them, are UNKNOWN). `cash_flows_observed`: deposits and
    withdrawals were requested (Polymarket v2 excludes them by default).
    """
    require_aware(as_of, "as_of")
    accounts = {o.account.key for o in observations}
    if len(accounts) > 1:
        raise ValueError("reconstruct one account at a time")
    if any(o.source_time > as_of for o in observations):
        raise ValueError("an observation is after as_of: pass the point-in-time view")
    notes: list[str] = []
    if not history_complete:
        notes.append("history is not complete from the account's start")
    if not cash_flows_observed:
        notes.append("deposits and withdrawals were not observed")
    markets: dict[str, _Market] = {}
    contributions = withdrawals = rewards = turnover = ZERO
    transfers: list[tuple[str, str, Decimal]] = []
    running_trading = ZERO
    peak_outlay = ZERO
    def market(o: WalletObservation) -> _Market:
        m = markets.setdefault(o.market_id or "?", _Market(o.market_id or "?", o.event_id, o.category))
        m.first_at = m.first_at or o.source_time
        m.last_at = o.source_time
        return m

    for o in sorted(observations, key=lambda x: (x.source_time, x.observation_id)):
        cash_in = add(*(a.quantity for a in o.received if a.is_cash))
        cash_out = add(*(a.quantity for a in o.paid if a.is_cash))
        if o.action is Action.TRANSFER_IN or o.action is Action.TRANSFER_OUT:
            contributions = add(contributions, cash_in)
            withdrawals = add(withdrawals, cash_out)
            for leg, sign in [*((a, 1) for a in o.received), *((a, -1) for a in o.paid)]:
                if not leg.is_cash:
                    transfers.append(("IN" if sign > 0 else "OUT", leg.asset, leg.quantity))
                    m = market(o)
                    m.transferred_tokens = True
                    _move(m, leg.asset, leg.quantity if sign > 0 else -leg.quantity)
            continue
        if o.action is Action.REWARD:
            rewards = add(rewards, cash_in)
            continue
        m = market(o)
        if o.action is Action.UNKNOWN:
            m.unknown_reasons.append(f"unknown action {o.raw_action}")
            continue
        net = sub(cash_in, cash_out)
        m.trading_cash = add(m.trading_cash, net)
        running_trading = add(running_trading, net)
        if -running_trading > peak_outlay:
            peak_outlay = -running_trading
        if o.directional:
            turnover = add(turnover, cash_in, cash_out)
            if o.action is Action.TRADE_BUY:
                m.buy_notional = add(m.buy_notional, cash_out)
            if o.fee.known and o.fee.value is not None:
                m.fees = add(m.fees, o.fee.value)
            else:
                m.fees_unknown += 1
        if "LEGS_NOT_ITEMIZED" in o.ambiguities:
            if not (o.action is Action.REDEEM and _reconcile_redeem(m, cash_in, marks, o.source_time)):
                m.unknown_reasons.append(f"{o.action.value} legs are not itemized by the source")
            continue
        for leg in o.received:
            if not leg.is_cash:
                _move(m, leg.asset, leg.quantity)
        for leg in o.paid:
            if not leg.is_cash:
                _move(m, leg.asset, -leg.quantity)

    results: list[MarketResult] = []
    for m in sorted(markets.values(), key=lambda x: x.market_id):
        results.append(_market_result(m, history_complete, marks, as_of, mark_max_age))

    fee_unknown = any(m.fees_unknown for m in markets.values())
    fees = Labeled.unknown("the source reports no fee for some trades") if fee_unknown else Labeled(
        add(*(m.fees for m in markets.values())), Basis.OBSERVED)
    realized = [r for r in results if r.state in (MarketState.CLOSED, MarketState.SETTLED)]
    unresolved = [r for r in results if r.state in (MarketState.OPEN, MarketState.UNKNOWN)]
    complete = history_complete and all(r.pnl_gross.known for r in realized) and \
        all(r.state is not MarketState.UNKNOWN for r in results)
    if any(r.state is MarketState.UNKNOWN for r in results):
        notes.append("some markets have unknown inventory")
    if not history_complete:
        realized_gross = Labeled.unknown("history incomplete: realized P&L cannot be reconstructed")
    elif any(r.state is MarketState.UNKNOWN for r in results):
        realized_gross = Labeled.unknown("a market's inventory is unknown, so its realized P&L is unknown")
    else:
        realized_gross = _sum_known([r.pnl_gross for r in realized], "a realized market's P&L is unknown")
    realized_net = _sum_known([r.pnl_net for r in realized], "fees unknown: net P&L is unknown") \
        if realized_gross.known else Labeled.unknown("gross realized P&L is unknown")
    unrealized = _sum_known([r.open_value for r in unresolved], "an open position has no executable value") \
        if history_complete else Labeled.unknown("history incomplete")
    if not history_complete:
        capital = Labeled.unknown("history incomplete: capital employed is unknown")
    elif transfers:
        capital = Labeled.unknown("tokens moved by transfer: their sales are not funded by observed outlay")
    else:
        capital = Labeled(peak_outlay, Basis.OBSERVED, "peak net trading outlay")
    remaining = _remaining_risk(unresolved, markets) if history_complete else Labeled.unknown("history incomplete")
    contrib = Labeled(contributions, Basis.OBSERVED) if cash_flows_observed else Labeled.unknown(
        "deposits/withdrawals not observed")
    withdr = Labeled(withdrawals, Basis.OBSERVED) if cash_flows_observed else Labeled.unknown(
        "deposits/withdrawals not observed")
    equity = Labeled.unknown("equity needs a known opening balance, observed cash flows, complete history, "
                             "known fees and every open position valued")
    # Holdings value: open positions plus resolved-but-unredeemed holdings at their final payout.
    held_value = _sum_known([r.open_value for r in results if r.state is not MarketState.CLOSED],
                            "a holding has no executable value")
    if (opening_balance.known and cash_flows_observed and history_complete and fees.known and held_value.known
            and opening_balance.value is not None and fees.value is not None and held_value.value is not None):
        cash = add(opening_balance.value, contributions, -withdrawals, running_trading, rewards, -fees.value)
        equity = Labeled(add(cash, held_value.value), Basis.OBSERVED)
    roi_net = _roi(realized_net, capital, complete)
    roi_gross = _roi(realized_gross, capital, complete)
    return LeaderAccount(
        account_key=next(iter(accounts), ""), as_of=as_of, contributions=contrib, withdrawals=withdr,
        realized_trading_pnl_gross=realized_gross, realized_trading_pnl_net=realized_net, unrealized_value=unrealized,
        fees=fees, rewards=Labeled(rewards, Basis.OBSERVED, "rewards, rebates and referrals: not trading P&L"),
        inventory_transfers=tuple(transfers), equity=equity, capital_employed=capital,
        turnover=Labeled(turnover, Basis.OBSERVED, "observed window only"), remaining_risk=remaining,
        roi_net=roi_net, roi_gross=roi_gross, coverage_complete=complete, coverage_notes=tuple(notes),
        markets=tuple(results))


def _reconcile_redeem(m: _Market, cash: Decimal, marks: Mapping[str, Mark], at: datetime) -> bool:
    """An un-itemized redemption is reconciled only when every held token has a final payout known by
    then and the payouts sum exactly to the cash received. The holdings are then redeemed (zeroed)."""
    held = {a: q for a, q in m.holdings.items() if q != 0}
    if not held:
        return False
    expected = ZERO
    for asset, qty in held.items():
        mark = marks.get(asset.removeprefix("token:"))
        if mark is None or mark.kind is not MarkKind.RESOLVED_PAYOUT or mark.as_of > at or qty < 0:
            return False
        expected = add(expected, mul(qty, mark.price))
    if expected != cash:
        return False
    for asset in held:
        m.holdings[asset] = ZERO
    return True


def _move(m: _Market, asset: str, qty: Decimal) -> None:
    new = add(m.holdings.get(asset, ZERO), qty)
    if new < 0:
        m.unknown_reasons.append(f"a sale of {asset} exceeds the reconstructed holding (missing history)")
    m.holdings[asset] = new


def _market_result(m: _Market, history_complete: bool, marks: Mapping[str, Mark], as_of: datetime,
                   max_age: timedelta) -> MarketResult:
    reasons = list(dict.fromkeys(m.unknown_reasons))
    if not history_complete:
        reasons.append("history is not complete from the account's start")
    if m.transferred_tokens:
        reasons.append("tokens arrived or left by transfer: cost basis unknown")
    held = {a: q for a, q in m.holdings.items() if q != 0}
    if reasons:
        unk = Labeled.unknown("; ".join(reasons))
        return MarketResult(m.market_id, m.event_id, m.category, MarketState.UNKNOWN, unk, unk, unk, m.first_at,
                            None, tuple(reasons))
    values: list[Labeled] = []
    final = True
    for asset, qty in sorted(held.items()):
        value, is_final = _value(asset.removeprefix("token:"), qty, marks, as_of, max_age)
        values.append(value)
        final = final and is_final
    open_value = _sum_known(values, "an open position has no executable value") if values else Labeled(
        ZERO, Basis.OBSERVED)
    state = MarketState.CLOSED if not held else (MarketState.SETTLED if final else MarketState.OPEN)
    if state is MarketState.OPEN:
        unk = Labeled.unknown("the market is still open")
        return MarketResult(m.market_id, m.event_id, m.category, state, unk, unk, open_value, m.first_at, None,
                            tuple(v.note for v in values if not v.known))
    assert open_value.value is not None
    gross = Labeled(add(m.trading_cash, open_value.value), Basis.OBSERVED)
    net = Labeled(sub(gross.value, m.fees), Basis.OBSERVED) if (m.fees_unknown == 0 and gross.value is not None) \
        else Labeled.unknown("the source reports no fee for this market's trades")
    return MarketResult(m.market_id, m.event_id, m.category, state, gross, net, open_value, m.first_at, m.last_at,
                        ())


def _value(token: str, qty: Decimal, marks: Mapping[str, Mark], as_of: datetime,
           max_age: timedelta) -> tuple[Labeled, bool]:
    mark = marks.get(token)
    if mark is None:
        return Labeled.unknown(f"no mark for {token}"), False
    if mark.kind is MarkKind.RESOLVED_PAYOUT:
        if mark.as_of > as_of:
            return Labeled.unknown(f"{token} resolves after as_of"), False
        return Labeled(mul(qty, mark.price), Basis.OBSERVED, "final payout"), True
    if mark.kind in (MarkKind.LAST_PRINT, MarkKind.VENDOR_MARK):
        return Labeled.unknown(f"{token}: a {mark.kind.value} is not withdrawable value"), False
    if mark.as_of > as_of or as_of - mark.as_of > max_age:
        return Labeled.unknown(f"{token}: the bid is stale or from the future"), False
    if mark.depth is None or mark.depth < qty:
        return Labeled.unknown(f"{token}: bid depth does not cover the holding"), False
    return Labeled(mul(qty, mark.price), Basis.OBSERVED, "executable bid"), False


def _remaining_risk(unresolved: Sequence[MarketResult], markets: Mapping[str, _Market]) -> Labeled:
    if any(r.state is MarketState.UNKNOWN for r in unresolved):
        return Labeled.unknown("some open inventory is unknown")
    outlay = ZERO
    for r in unresolved:
        cash = markets[r.market_id].trading_cash
        if cash < 0:
            outlay = add(outlay, -cash)
    return Labeled(outlay, Basis.OBSERVED, "net cash still committed to open markets (the loss if they pay 0)")


def _roi(pnl: Labeled, capital: Labeled, complete: bool) -> Labeled:
    if not complete:
        return Labeled.unknown("coverage incomplete: no ROI")
    if not (pnl.known and capital.known) or pnl.value is None or capital.value is None:
        return Labeled.unknown("P&L or capital employed unknown: no ROI")
    r = ratio(pnl.value, capital.value)
    if r is None:
        return Labeled.unknown("no capital employed")
    return Labeled(r, Basis.OBSERVED, "realized P&L / peak net trading outlay")


# --- Leader dimensions -----------------------------------------------------------------------------

@dataclass(frozen=True)
class LeaderDimensions:
    account_key: str
    history_days: Labeled
    independent_events: int
    event_win_rate: ShrunkRate
    category_win_rates: dict[str, ShrunkRate]
    concentration: Labeled  # largest share of buy notional in one market
    max_drawdown: Labeled  # of cumulative realized gross P&L by close time
    turnover_to_capital: Labeled
    median_holding_hours: Labeled
    reward_dependence: Labeled
    data_complete: bool
    unknown_markets: int
    follower_execution_quality: Labeled  # filled by replay; UNKNOWN until then
    hidden_hedges: str = "UNKNOWN"  # never NONE: other venues and accounts are unobservable
    score: None = None  # deliberately absent: there is no single score

    def to_dict(self) -> dict:
        return {"account": self.account_key, "history_days": self.history_days.to_dict(),
                "independent_events": self.independent_events, "event_win_rate": self.event_win_rate.to_dict(),
                "category_win_rates": {k: v.to_dict() for k, v in sorted(self.category_win_rates.items())},
                "concentration": self.concentration.to_dict(), "max_drawdown": self.max_drawdown.to_dict(),
                "turnover_to_capital": self.turnover_to_capital.to_dict(),
                "median_holding_hours": self.median_holding_hours.to_dict(),
                "reward_dependence": self.reward_dependence.to_dict(), "data_complete": self.data_complete,
                "unknown_markets": self.unknown_markets,
                "follower_execution_quality": self.follower_execution_quality.to_dict(),
                "hidden_hedges": self.hidden_hedges}


def event_outcomes(account: LeaderAccount) -> dict[str, Decimal]:
    """Realized gross P&L per independent event (markets of one event are one cluster).

    An event counts only when every one of its markets is closed or settled with a known P&L. One open
    or UNKNOWN market makes the whole event UNKNOWN, so it is left out: never a partial win.

    Caveat: leaving unknown events out of the trials can flatter a reported win rate, because an
    account's unknown events may be its losers (a loss hidden behind an untraced transfer, say). The
    rate is therefore a rate over *known* events only, and `LeaderDimensions.unknown_markets` reports how
    much is missing. Selection does not rely on the rate alone: `selection._eligibility` rejects any
    account with an unknown market (`UNKNOWN_MARKETS`) and any account with incomplete coverage."""
    out: dict[str, Decimal] = {}
    unknown: set[str] = set()
    for r in account.markets:
        key = r.event_id or r.market_id
        if r.state in (MarketState.CLOSED, MarketState.SETTLED) and r.pnl_gross.value is not None:
            out[key] = add(out.get(key, ZERO), r.pnl_gross.value)
        else:
            unknown.add(key)
    return {k: v for k, v in out.items() if k not in unknown}


def leader_dimensions(account: LeaderAccount, observations: Sequence[WalletObservation], *,
                      prior: BetaPrior) -> LeaderDimensions:
    times = sorted(o.source_time for o in observations)
    days = Labeled(Decimal((times[-1] - times[0]).days), Basis.OBSERVED, "observed span") if times else \
        Labeled.unknown("no observations")
    outcomes = event_outcomes(account)
    wins = sum(1 for v in outcomes.values() if v > 0)
    by_cat: dict[str, list[Decimal]] = {}
    for r in account.markets:
        if r.state in (MarketState.CLOSED, MarketState.SETTLED) and r.pnl_gross.value is not None and r.category:
            by_cat.setdefault(r.category, []).append(r.pnl_gross.value)
    cat_rates = {c: shrunk_rate(sum(1 for v in vs if v > 0), len(vs), prior) for c, vs in by_cat.items()}
    buys: dict[str, Decimal] = {}
    for o in observations:
        if o.action is Action.TRADE_BUY:
            buys[o.market_id or "?"] = add(buys.get(o.market_id or "?", ZERO),
                                            *(a.quantity for a in o.paid if a.is_cash))
    total_buys = add(*buys.values()) if buys else ZERO
    concentration = Labeled(ratio(max(buys.values()), total_buys), Basis.OBSERVED) if total_buys > 0 else \
        Labeled.unknown("no buys")
    closed = sorted((r for r in account.markets if r.closed_at is not None and r.pnl_gross.value is not None),
                    key=lambda r: (r.closed_at, r.market_id))
    peak = cum = worst = ZERO
    for r in closed:
        assert r.pnl_gross.value is not None
        cum = add(cum, r.pnl_gross.value)
        peak = max(peak, cum)
        worst = max(worst, sub(peak, cum))
    drawdown = Labeled(worst, Basis.OBSERVED) if closed and account.coverage_complete else Labeled.unknown(
        "needs complete coverage and closed markets")
    t2c = Labeled.unknown("capital employed unknown")
    if account.capital_employed.value and account.turnover.value is not None:
        r = ratio(account.turnover.value, account.capital_employed.value)
        t2c = Labeled(r, Basis.OBSERVED) if r is not None else t2c
    holds = sorted((r.closed_at - r.opened_at).total_seconds() / 3600 for r in closed if r.opened_at)
    median = Labeled(Decimal(str(round(holds[len(holds) // 2], 3))), Basis.OBSERVED, "hours, statistic") if holds \
        else Labeled.unknown("no closed markets")
    reward_dep = Labeled.unknown("realized P&L unknown")
    if account.realized_trading_pnl_gross.value is not None and account.rewards.value is not None:
        denom = add(abs(account.realized_trading_pnl_gross.value), account.rewards.value)
        rd = ratio(account.rewards.value, denom)
        reward_dep = Labeled(rd, Basis.OBSERVED) if rd is not None else Labeled.unknown("no P&L and no rewards")
    return LeaderDimensions(
        account_key=account.account_key, history_days=days, independent_events=len(outcomes),
        event_win_rate=shrunk_rate(wins, len(outcomes), prior), category_win_rates=cat_rates,
        concentration=concentration, max_drawdown=drawdown, turnover_to_capital=t2c, median_holding_hours=median,
        reward_dependence=reward_dep, data_complete=account.coverage_complete,
        unknown_markets=sum(1 for r in account.markets if r.state is MarketState.UNKNOWN),
        follower_execution_quality=Labeled.unknown("no follower replay yet"))
