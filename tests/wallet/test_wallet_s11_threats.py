"""Directive §11 defensive scenarios, one test each. Threat scenarios on SYNTHETIC accounts, never
accusations about named traders. Nothing here implements manipulation or evasion."""

from __future__ import annotations

from datetime import timedelta

from wallet_support import D, Books, acct, at, book, config, enrolled, limits, obs, signal

from edge_lab.wallet_intel.accounting import Mark, MarkKind, leader_dimensions, reconstruct
from edge_lab.wallet_intel.events import Action, ObservationLog
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.policy import FollowerPolicy
from edge_lab.wallet_intel.replay import FillStatus, replay
from edge_lab.wallet_intel.selection import Candidate, CandidateStatus, EligibilityRule, select_at
from edge_lab.wallet_intel.stats import WEAK_PRIOR
from edge_lab.wallet_intel.threats import (FillJudgement, co_trading_clusters, independent_count, is_bait_size,
                                           off_market_fills, round_trip_share)


def _rule(**kw):  # type: ignore[no-untyped-def]
    base = dict(min_independent_events=3, min_history_days=1, min_shrunk_lower=0.0, max_concentration=D("0.9"),
                max_round_trip_share=D("0.5"), max_reward_dependence=D("0.5"), inactive_after=timedelta(days=60),
                round_trip_window=timedelta(hours=1), min_trade_notional=D(1))
    base.update(kw)
    return EligibilityRule("threat-rule", "1", **base)


def test_coordinated_wallets_appearing_independent_are_one_cluster():
    rows = []
    for i in range(5):
        t = at(days=i)
        rows += [obs(acct(1), Action.TRADE_BUY, f"m{i}-yes", 10, "0.4", t, market=f"m{i}"),
                 obs(acct(2), Action.TRADE_BUY, f"m{i}-yes", 10, "0.4", t + timedelta(seconds=15), market=f"m{i}"),
                 obs(acct(3), Action.TRADE_BUY, f"m{i}-yes", 10, "0.4", t + timedelta(seconds=40), market=f"m{i}"),
                 obs(acct(4), Action.TRADE_BUY, f"m{i}-no", 10, "0.6", t + timedelta(hours=5), market=f"m{i}")]
    clusters = co_trading_clusters(rows, window=timedelta(minutes=1), min_shared=3, min_overlap=D("0.6"))
    keys = [acct(n).key for n in (1, 2, 3, 4)]
    assert clusters[keys[0]] == clusters[keys[1]] == clusters[keys[2]] != clusters[keys[3]]
    assert independent_count(keys[:3], clusters) == 1  # three agreeing wallets are one confirmation
    # A shared stated funding source also links accounts.
    funded = co_trading_clusters(rows, window=timedelta(seconds=1), min_shared=99, min_overlap=D(1),
                                 funding_sources={keys[0]: "src-x", keys[3]: "src-x"})
    assert funded[keys[0]] == funded[keys[3]]
    # Cluster caps: two coordinated leaders share one cluster budget.
    pol = FollowerPolicy(limits(per_cluster=D(10), risk_per_signal=D(10)), enrollments=enrolled("L1", "L2"))
    r = replay([signal("a", leader="L1", cluster="C"), signal("b", leader="L2", cluster="C", token="m2-yes",
                                                              market="m2", event="evt-m2")],
               pol, initial_cash=D(100), books=Books(book(captured=at(1)), book("m2-yes", captured=at(1))),
               resolutions={}, config=config(), horizon=at(days=1))
    # The second leader gets only the cluster's remaining headroom, not a fresh budget.
    assert r.final_book.exposure(cluster="C") <= D(10)
    second = next(f for f in r.fills if f.signal_id == "b")
    first = next(f for f in r.fills if f.signal_id == "a")
    assert second.gross_cash <= D(10) - first.gross_cash


def test_wash_or_churn_activity_does_not_qualify():
    a = acct(1)
    rows = []
    for i in range(6):
        t = at(days=i)
        rows += [obs(a, Action.TRADE_BUY, f"m{i}-yes", 500, "0.50", t, market=f"m{i}"),
                 obs(a, Action.TRADE_SELL, f"m{i}-yes", 500, "0.51", t + timedelta(minutes=3), market=f"m{i}")]
    share = round_trip_share(rows, max_hold=timedelta(hours=1))
    assert share == 1  # all turnover is quick round trips
    log = ObservationLog()
    log.ingest(rows)
    m = select_at(at(days=10), candidates=[Candidate(a, at(-1), "u", "v1")], logs={a.key: log},
                  history_complete={a.key: True}, marks={}, rule=_rule(), label_version="v1", trials=1,
                  mark_max_age=timedelta(minutes=5))
    assert m.records[0].status is CandidateStatus.INELIGIBLE
    assert "ROUND_TRIP_CHURN_OR_NO_TRADES" in m.records[0].reasons


def test_cheap_off_market_leader_allocations_are_flagged_and_unreachable():
    a = acct(1)
    cheap = obs(a, Action.TRADE_BUY, "m1-yes", 100, "0.10", at(0))  # the book offered 0.41
    fair = obs(a, Action.TRADE_BUY, "m1-yes", 100, "0.41", at(0))
    books = Books(book(captured=at(-1)))
    judged = {r.observation_id: r.judgement for r in off_market_fills([cheap, fair], books, tolerance=D("0.02"),
                                                                       max_book_age=timedelta(minutes=5))}
    assert judged[cheap.observation_id] is FillJudgement.OFF_MARKET
    assert judged[fair.observation_id] is FillJudgement.AT_MARKET
    # No book: not cleared.
    assert off_market_fills([cheap], Books(), tolerance=D("0.02"), max_book_age=timedelta(minutes=5))[0].judgement \
        is FillJudgement.UNJUDGED
    # A follower pays the book, never the leader's allocation price.
    pol = FollowerPolicy(limits(max_price_above_leader=D("0.50")), enrollments=enrolled("L1"))
    r = replay([signal("c", price="0.10")], pol, initial_cash=D(100), books=Books(book(captured=at(1))),
               resolutions={}, config=config(), horizon=at(days=1))
    assert r.fills[0].levels[0][0] == D("0.41")


def test_tiny_bait_trades_are_not_followed():
    assert is_bait_size(obs(acct(1), Action.TRADE_BUY, qty=1, price="0.30"), min_notional=D(5))
    pol = FollowerPolicy(limits(min_leader_notional=D(5)), enrollments=enrolled("L1"))
    r = replay([signal("tiny", qty="2", price="0.30")], pol, initial_cash=D(100), books=Books(book(captured=at(1))),
               resolutions={}, config=config(), horizon=at(days=1))
    assert r.outcomes[0].decision == "SKIP" and "TINY_SIGNAL" in r.outcomes[0].reason and r.fills == ()


def test_hidden_hedges_are_unknown_not_none():
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0))]
    acc = reconstruct(rows, as_of=at(10), history_complete=True, cash_flows_observed=False,
                      opening_balance=Labeled.unknown(), marks={}, mark_max_age=timedelta(minutes=5))
    assert leader_dimensions(acc, rows, prior=WEAK_PRIOR).hidden_hedges == "UNKNOWN"


def test_fake_marks_and_illiquid_holdings_are_not_wealth():
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10000, "0.01", at(0))]
    for mark in (Mark("m1-yes", MarkKind.LAST_PRINT, D("0.99"), None, at(9)),
                 Mark("m1-yes", MarkKind.VENDOR_MARK, D("0.99"), None, at(9)),
                 Mark("m1-yes", MarkKind.EXECUTABLE_BID, D("0.99"), D(3), at(9)),  # too thin
                 Mark("m1-yes", MarkKind.EXECUTABLE_BID, D("0.99"), D(10000), at(-600))):  # stale
        acc = reconstruct(rows, as_of=at(10), history_complete=True, cash_flows_observed=True,
                          opening_balance=Labeled.observed(D(100)), marks={"m1-yes": mark},
                          mark_max_age=timedelta(minutes=5))
        assert not acc.unrealized_value.known and not acc.equity.known, mark
    ok = reconstruct(rows, as_of=at(10), history_complete=True, cash_flows_observed=True,
                     opening_balance=Labeled.observed(D(100)),
                     marks={"m1-yes": Mark("m1-yes", MarkKind.EXECUTABLE_BID, D("0.02"), D(10000), at(9))},
                     mark_max_age=timedelta(minutes=5))
    assert ok.unrealized_value.value == D(200) and ok.equity.value == D(200)


def test_stale_replayed_signals_are_quarantined_or_deduplicated():
    pol = FollowerPolicy(limits(max_signal_age=timedelta(minutes=5)), enrollments=enrolled("L1"))
    stale = signal("s", when=at(0))
    r = replay([stale, stale], pol, initial_cash=D(100), books=Books(book(captured=at(1))), resolutions={},
               config=config(resume_at=at(30)), horizon=at(days=1))
    assert [o.decision for o in r.outcomes] == ["QUARANTINE", "SKIP"]
    assert "DUPLICATE_SIGNAL" in r.outcomes[1].reason
    fresh = replay([signal("f"), signal("f")], pol, initial_cash=D(100), books=Books(book(captured=at(1))),
                   resolutions={}, config=config(), horizon=at(days=1))
    assert [o.decision for o in fresh.outcomes] == ["BUY", "SKIP"]  # replayed twice, entered once


def test_leader_exiting_while_we_enter_skips_the_entry():
    buy = signal("b", when=at(0), delay=timedelta(minutes=2))
    quick_exit = signal("x", Action.TRADE_SELL, when=at(0, hours=0) + timedelta(seconds=30),
                        delay=timedelta(seconds=30), before="100")
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    r = replay([buy, quick_exit], pol, initial_cash=D(100), books=Books(book(captured=at(0))), resolutions={},
               config=config(), horizon=at(days=1))
    by = {o.signal_id: o for o in r.outcomes}
    assert by["b"].decision == "SKIP" and by["b"].reason == "LEADER_EXITED_BEFORE_ENTRY"
    assert by["x"].decision == "SKIP"  # nothing attributable to sell
    assert not [f for f in r.fills if f.status is FillStatus.FILLED]
    # An exit that only became observable after our order arrived does not cancel a valid entry.
    late_exit = signal("y", Action.TRADE_SELL, when=at(1), delay=timedelta(minutes=30), before="100")
    r2 = replay([buy, late_exit], pol, initial_cash=D(100), books=Books(book(captured=at(0)), book(captured=at(31))),
                resolutions={}, config=config(), horizon=at(days=1))
    assert {o.signal_id: o.decision for o in r2.outcomes} == {"b": "BUY", "y": "SELL"}
