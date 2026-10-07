"""W5 and W6: follower replay at attainable prices, the policy, attribution, caps, ladders and benchmarks."""

from __future__ import annotations

from datetime import timedelta

import pytest
from wallet_support import D, Books, at, book, config, enrolled, limits, signal

from edge_lab.wallet_intel.events import Action
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.policy import (Enrollment, FollowerBook, FollowerPolicy, IntentKind, LeaderStatus,
                                          PolicyMode)
from edge_lab.wallet_intel.replay import (FillStatus, RequestResult, Resolution, benchmarks, describe_times, ladder,
                                          replay, unknown_fee, with_detection_delay)


def _run(signals, *, lim=None, cash="100", books=None, res=None, cfg=None, enroll=None, mode=PolicyMode.FIXED_RISK_PER_SIGNAL,  # type: ignore[no-untyped-def]
         equity=None):
    pol = FollowerPolicy(lim or limits(), mode=mode, enrollments=enroll or enrolled("L1", "L2"), leader_equity=equity)
    return replay(signals, pol, initial_cash=D(cash), books=books or Books(book(captured=at(1))), resolutions=res or {},
                  config=cfg or config(), horizon=at(days=1))


def test_the_follower_timeline_starts_at_observation_time_not_the_leader_fill():
    s = signal("b", when=at(0), delay=timedelta(minutes=3))
    times = describe_times(s, config())
    assert times["observable_at"] == at(3).isoformat() and times["arrives_at"] == (at(3) + timedelta(seconds=2)).isoformat()
    # The leader bought at 0.40 from a book that is gone by the time we can act.
    books = Books(book(bid="0.39", ask="0.41", captured=at(0)), book(bid="0.47", ask="0.49", captured=at(2)))
    r = _run([s], books=books, lim=limits(max_price_above_leader=D("0.20")))
    assert r.fills[0].levels[0][0] == D("0.49")
    assert r.fills[0].arrived_at >= s.observable_at


def test_a_book_from_after_arrival_is_never_used():
    r = _run([signal("b")], books=Books(book(captured=at(30))))
    assert r.fills[0].status is FillStatus.NO_FILL and r.fills[0].reason == "MISSING_BOOK"


def test_limit_price_bounds_slippage():
    r = _run([signal("b", price="0.30")], books=Books(book(bid="0.49", ask="0.50", captured=at(1))))
    assert r.fills[0].status is FillStatus.NO_FILL and r.fills[0].reason == "NO_DEPTH_WITHIN_LIMIT"


def test_minimum_quantity_after_depth_rejects_dust_fills():
    r = _run([signal("b")], lim=limits(min_quantity=D(10)), books=Books(book(size="3", levels=1, captured=at(1))))
    assert r.fills[0].status is FillStatus.NO_FILL and "MINIMUM" in r.fills[0].reason
    assert r.final_book.inventory == {}


def test_unknown_fee_blocks_net_economics_only():
    r = _run([signal("b")], cfg=config(fee_fn=unknown_fee),
             res={"m1-yes": Resolution("m1-yes", D(1), at(hours=3))})
    assert r.follower.gross_pnl.known and not r.follower.net_pnl.known and not r.follower.fees.known
    assert not r.difference_by_event["evt-m1"].known


def test_failed_requests_retry_against_a_fresh_book_then_give_up():
    attempts = []

    def flaky(sid, n):  # type: ignore[no-untyped-def]
        attempts.append(n)
        return RequestResult.FAILED if n == 1 else RequestResult.OK

    books = Books(book(captured=at(1)), book(bid="0.42", ask="0.44", captured=at(1) + timedelta(seconds=10)))
    r = _run([signal("b")], books=books, cfg=config(request_outcome=flaky, max_attempts=2,
                                                    retry_delay=timedelta(seconds=10)))
    assert attempts == [1, 2] and r.fills[0].attempts == 2 and r.fills[0].levels[0][0] == D("0.44")
    dead = _run([signal("b")], cfg=config(request_outcome=lambda s, n: RequestResult.FAILED, max_attempts=3))
    assert dead.fills[0].status is FillStatus.FAILED and dead.final_book.inventory == {}


def test_nothing_trades_after_resolution_and_holdings_settle():
    res = {"m1-yes": Resolution("m1-yes", D(0), at(hours=2))}
    r = _run([signal("b"), signal("late", when=at(hours=3))], res=res,
             books=Books(book(captured=at(1)), book(captured=at(hours=3))))
    by = {o.signal_id: o for o in r.outcomes}
    assert by["b"].decision == "BUY" and by["late"].reason == "MARKET_RESOLVED"
    assert r.final_book.inventory["m1-yes"] == 0 and r.follower.gross_pnl.value < 0
    assert all(r.reconciliation.values())


def test_open_holdings_at_horizon_are_valued_only_at_captured_bids():
    r = _run([signal("b")], books=Books(book(captured=at(1))))
    assert not r.follower.open_value.known and not r.follower.gross_pnl.known  # no book at the horizon
    r2 = _run([signal("b")], books=Books(book(captured=at(1)), book(captured=at(days=1) - timedelta(minutes=1))))
    assert r2.follower.open_value.known and r2.follower.gross_pnl.value < 0  # bought at the ask, valued at the bid


def test_policy_caps_cash_and_opposing_signals_are_not_hedges():
    lim = limits(per_event=D(15), risk_per_signal=D(10))
    yes = signal("y", token="m1-yes")
    no = signal("n", leader="L2", token="m1-no", price="0.58")
    books = Books(book(captured=at(1)), book("m1-no", bid="0.57", ask="0.59", captured=at(1)))
    r = _run([yes, no], lim=lim, books=books)
    assert r.final_book.exposure(event="evt-m1") <= D(15)  # gross, both sides count
    fb = FollowerBook(D(5))
    pol = FollowerPolicy(limits(risk_per_signal=D(10)), enrollments=enrolled("L1"))
    intent = pol.decide(signal("b"), fb, now=at(2))
    assert intent.kind is IntentKind.BUY and intent.max_cash == D(5)  # cash is a cap


def test_proportional_mode_is_blocked_without_leader_equity():
    for equity in (None, {"L1": Labeled.unknown("public wallet")}):
        r = _run([signal("b")], mode=PolicyMode.PROPORTIONAL_TO_LEADER_EQUITY, equity=equity)
        assert r.outcomes[0].decision == "BLOCKED" and "LEADER_EQUITY_UNKNOWN" in r.outcomes[0].reason
    r = _run([signal("b", qty="100", price="0.40")], mode=PolicyMode.PROPORTIONAL_TO_LEADER_EQUITY,
             equity={"L1": Labeled.observed(D(4000))})
    assert r.outcomes[0].decision == "BUY"  # 40/4000 of a 500 total cap = 5, under the 10 budget
    assert r.fills[0].gross_cash <= D(5)


def test_no_catch_up_and_enrollment_rules():
    with pytest.raises(ValueError, match="catch-up"):
        limits(catch_up=True)
    pol = FollowerPolicy(limits(), enrollments={"L1": Enrollment("L1", at(10))})
    fb = FollowerBook(D(100))
    assert pol.decide(signal("pre", when=at(0)), fb, now=at(2)).reason.startswith("PRE_ENROLLMENT")
    assert pol.decide(signal("x", leader="L9"), fb, now=at(2)).reason == "LEADER_NOT_ENROLLED"
    paused = FollowerPolicy(limits(), enrollments={"L1": Enrollment("L1", at(-10), LeaderStatus.PAUSED)})
    assert paused.decide(signal("b"), fb, now=at(2)).kind is IntentKind.SKIP
    silent = FollowerPolicy(limits(), enrollments={"L1": Enrollment("L1", at(-10), LeaderStatus.SILENT)})
    assert "no new entries" in silent.decide(signal("b"), fb, now=at(2)).reason


def test_a_decision_cannot_precede_the_observation():
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    with pytest.raises(ValueError, match="hindsight"):
        pol.decide(signal("b", delay=timedelta(minutes=5)), FollowerBook(D(10)), now=at(1))


def test_fractional_leader_exit_sells_the_same_fraction_of_attributable_inventory():
    buy = signal("b", qty="100", before="0")
    quarter = signal("q", Action.TRADE_SELL, qty="25", before="100", when=at(30))
    r = _run([buy, quarter], lim=limits(risk_per_signal=D(20)), books=Books(book(captured=at(1)), book(captured=at(31))))
    bought = r.fills[0].filled
    sold = r.fills[1].filled
    assert sold == (bought * 25) // 100


def test_target_exposure_holds_one_budget_and_exits_fully():
    s1, s2 = signal("a"), signal("b", when=at(5))
    trim = signal("x", Action.TRADE_SELL, qty="10", before="200", when=at(30))
    flat = signal("y", Action.TRADE_SELL, qty="190", before="190", when=at(40))
    r = _run([s1, s2, trim, flat], mode=PolicyMode.TARGET_EXPOSURE,
             books=Books(book(captured=at(1)), book(captured=at(6)), book(captured=at(31)), book(captured=at(41))))
    assert [o.decision for o in r.outcomes] == ["BUY", "SKIP", "SKIP", "SELL"]
    assert "TARGET_STILL_HELD" in r.outcomes[2].reason
    assert r.final_book.inventory["m1-yes"] == 0


def test_ladder_and_benchmarks_run_on_matched_inputs():
    signals = [signal("b"), signal("s", Action.TRADE_SELL, before="100", when=at(30))]
    books = Books(book(captured=at(0)), book(bid="0.45", ask="0.47", captured=at(31)))
    rows = ladder(signals, limits(), enrolled("L1"), sizes=[D(5), D(10)], delays=[timedelta(seconds=10),
                                                                                  timedelta(minutes=5)],
                  initial_cash=D(100), books=books, resolutions={}, config=config(), horizon=at(days=1))
    assert len(rows) == 4 and {r.detection_delay for r in rows} == {timedelta(seconds=10), timedelta(minutes=5)}
    assert all(r.follower_gross.basis.value in ("ESTIMATED", "UNKNOWN") for r in rows)
    bench = benchmarks(signals, limits(), enrolled("L1"), initial_cash=D(100), books=books, resolutions={},
                       config=config(), horizon=at(days=1))
    assert set(bench) == {"DO_NOTHING", "MATCHED_BUY_AND_HOLD", "NAIVE_FROZEN_FOLLOWING", "FIXED_RULE_FILTER"}
    assert bench["DO_NOTHING"].gross_pnl.value == 0
    assert all(b.initial_cash == D(100) for b in bench.values())
    delayed = with_detection_delay(signals, timedelta(hours=1))
    assert all(s.observable_at >= s.leader_time + timedelta(hours=1) for s in delayed)
