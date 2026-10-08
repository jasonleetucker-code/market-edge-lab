"""W3: cash-flow-aware leader reconstruction, dimensions and shrinkage."""

from __future__ import annotations

from datetime import timedelta

import pytest
from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel.accounting import Mark, MarkKind, MarketState, leader_dimensions, reconstruct
from edge_lab.wallet_intel.events import Action
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.stats import (WEAK_PRIOR, benjamini_hochberg, beta_quantile, cluster_bootstrap,
                                         fit_beta_prior, shrunk_rate)

A = acct(1)
AGE = timedelta(minutes=5)


def _rec(rows, *, complete=True, cash=True, opening=Labeled.observed(D(100)), marks=None, as_of=None):  # type: ignore[no-untyped-def]
    return reconstruct(rows, as_of=as_of or at(days=10), history_complete=complete, cash_flows_observed=cash,
                       opening_balance=opening, marks=marks or {}, mark_max_age=AGE)


def test_closed_market_pnl_comes_from_cash_flows():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 100, "0.40", at(0), fee=D("0.5")),
            obs(A, Action.TRADE_SELL, "m1-yes", 100, "0.55", at(60), fee=D("0.5"))]
    acc = _rec(rows)
    assert acc.realized_trading_pnl_gross.value == D(15) and acc.realized_trading_pnl_net.value == D(14)
    assert acc.fees.value == D(1) and acc.capital_employed.value == D(40) and acc.turnover.value == D(95)
    assert acc.equity.value == D(114) and acc.roi_net.value == D("0.35")
    assert acc.economics_label == "LEADER_OBSERVED_ECONOMICS"


def test_unknown_fee_blocks_net_and_net_roi_but_gross_is_labelled():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 100, "0.40", at(0), fee=None),
            obs(A, Action.TRADE_SELL, "m1-yes", 100, "0.55", at(60), fee=None)]
    acc = _rec(rows)
    assert acc.realized_trading_pnl_gross.value == D(15)
    assert not acc.realized_trading_pnl_net.known and not acc.fees.known and not acc.roi_net.known
    assert acc.roi_gross.known and not acc.equity.known


def test_resolved_holdings_settle_at_the_final_payout_only_once_known():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0))]
    resolved = {"m1-yes": Mark("m1-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=2))}
    acc = _rec(rows, marks=resolved)
    assert acc.markets[0].state is MarketState.SETTLED and acc.realized_trading_pnl_gross.value == D(6)
    early = _rec(rows, marks=resolved, as_of=at(days=1))
    assert early.markets[0].state is MarketState.OPEN and not early.unrealized_value.known


def test_unitemized_redemption_reconciles_only_on_an_exact_payout():
    buy = obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0))
    marks = {"m1-yes": Mark("m1-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=2))}
    redeem = obs(A, Action.REDEEM, "m1-yes", 10, "0", at(days=3), cash="10", ambiguities=("LEGS_NOT_ITEMIZED",))
    acc = _rec([buy, redeem], marks=marks)
    assert acc.markets[0].state is MarketState.CLOSED and acc.realized_trading_pnl_gross.value == D(6)
    wrong = obs(A, Action.REDEEM, "m1-yes", 10, "0", at(days=3), cash="9", ambiguities=("LEGS_NOT_ITEMIZED",))
    acc = _rec([buy, wrong], marks=marks)
    assert acc.markets[0].state is MarketState.UNKNOWN and not acc.realized_trading_pnl_gross.known


def test_rewards_and_contributions_are_separate_lines():
    rows = [obs(A, Action.REWARD, "m1-yes", 1, "1", at(0), market="m1", cash="2.5")]
    acc = _rec(rows)
    assert acc.rewards.value == D("2.5") and acc.realized_trading_pnl_gross.value == D(0)
    assert acc.markets == ()  # a reward is not a trading market
    no_cash = _rec(rows, cash=False)
    assert not no_cash.contributions.known and not no_cash.withdrawals.known and not no_cash.equity.known


def test_equity_needs_a_known_opening_balance():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0)), obs(A, Action.TRADE_SELL, "m1-yes", 10, "0.5", at(9))]
    assert not _rec(rows, opening=Labeled.unknown()).equity.known
    assert _rec(rows).equity.value == D(101)


def test_remaining_risk_is_the_cash_still_committed_to_open_markets():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0)),
            obs(A, Action.TRADE_BUY, "m2-yes", 5, "0.20", at(0), market="m2")]
    bids = {"m1-yes": Mark("m1-yes", MarkKind.EXECUTABLE_BID, D("0.38"), D(50), at(days=10)),
            "m2-yes": Mark("m2-yes", MarkKind.EXECUTABLE_BID, D("0.18"), D(50), at(days=10))}
    acc = _rec(rows, marks=bids)
    assert acc.remaining_risk.value == D(5) and acc.unrealized_value.value == D("4.7")


def test_one_account_at_a_time_and_no_future_observation():
    with pytest.raises(ValueError):
        _rec([obs(A, Action.TRADE_BUY), obs(acct(2), Action.TRADE_BUY)])
    with pytest.raises(ValueError):
        _rec([obs(A, Action.TRADE_BUY, when=at(days=20))])


def test_dimensions_are_separate_with_uncertainty_and_no_single_score():
    rows = []
    for i in range(4):
        m = f"m{i}"
        rows += [obs(A, Action.TRADE_BUY, f"{m}-yes", 10, "0.40", at(days=i), market=m),
                 obs(A, Action.TRADE_SELL, f"{m}-yes", 10, "0.50" if i < 3 else "0.30", at(days=i, hours=5), market=m)]
    acc = _rec(rows)
    dims = leader_dimensions(acc, rows, prior=WEAK_PRIOR)
    assert dims.independent_events == 4 and dims.event_win_rate.wins == 3
    assert dims.event_win_rate.lower < 0.75 < dims.event_win_rate.upper
    assert dims.score is None and "score" not in dims.to_dict()
    assert dims.max_drawdown.value == D(1) and dims.concentration.value == D("0.25")
    assert not dims.follower_execution_quality.known


def test_shrinkage_keeps_small_lucky_samples_from_dominating():
    pool = [(5, 10), (6, 10), (4, 10), (5, 10), (7, 10), (3, 10)]
    prior = fit_beta_prior(pool)
    lucky = shrunk_rate(3, 3, prior)
    steady = shrunk_rate(70, 100, prior)
    assert lucky.raw_rate == 1.0 and lucky.posterior_mean < steady.posterior_mean + 0.2
    assert lucky.lower < steady.lower
    assert fit_beta_prior([(1, 2)]) is WEAK_PRIOR


def test_beta_and_bootstrap_and_bh_are_deterministic_and_sane():
    assert abs(beta_quantile(0.5, 2, 2) - 0.5) < 1e-9
    assert cluster_bootstrap({"a": 1.0}) is None
    assert cluster_bootstrap({"a": 1.0, "b": 3.0}) == cluster_bootstrap({"b": 3.0, "a": 1.0})
    assert benjamini_hochberg({"x": 0.001, "y": 0.04, "z": 0.9}, q=0.1) == {"x", "y"}


def test_equity_counts_resolved_but_unredeemed_holdings_at_the_payout():
    rows = [obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0))]
    resolved = {"m1-yes": Mark("m1-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=2))}
    acc = _rec(rows, marks=resolved)
    assert acc.equity.value == D(106)  # 100 - 4 cash + 10 shares x $1 payout


def test_token_transfers_make_capital_employed_unknown():
    rows = [obs(A, Action.TRANSFER_IN, "m1-yes", 50, "0", at(0)), obs(A, Action.TRADE_SELL, "m1-yes", 50, "0.9", at(5)),
            obs(A, Action.TRADE_BUY, "m2-yes", 10, "0.5", at(6), market="m2"),
            obs(A, Action.TRADE_SELL, "m2-yes", 10, "0.6", at(7), market="m2")]
    acc = _rec(rows)
    assert not acc.capital_employed.known and not acc.roi_gross.known and not acc.realized_trading_pnl_gross.known
