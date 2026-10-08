"""Regression tests for the independent review of the wallet lane (findings F1-F8). Each failed first."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel.accounting import Mark, MarkKind
from edge_lab.wallet_intel.events import Action, ObservationLog
from edge_lab.wallet_intel.selection import Candidate, EligibilityRule, select_at

RULE = EligibilityRule("r", "1", min_independent_events=2, min_history_days=1, min_shrunk_lower=0.0,
                       max_concentration=D("0.9"), max_round_trip_share=D("0.9"), max_reward_dependence=D("0.9"),
                       inactive_after=timedelta(days=60), round_trip_window=timedelta(hours=1), min_trade_notional=D(0))


# F1: a conflict detected later must not change an earlier point-in-time view -----------------------
def test_f1_a_later_conflicting_version_does_not_rewrite_an_earlier_view():
    o = obs(acct(1), Action.TRADE_BUY, event_id="fill-1", when=at(0), receipt_delay=timedelta(0))
    log = ObservationLog()
    log.ingest([o])
    assert len(log.as_known_at(at(days=1))) == 1
    log.ingest([replace(o, native_quantity=D(11), receipt_time=at(days=5))])
    assert len(log.as_known_at(at(days=1))) == 1  # the day-1 view is unchanged
    assert log.as_known_at(at(days=6)) == ()  # from detection on, the identity is reported, not used
    assert log.conflicted_ids(at(days=1)) == frozenset() and log.conflicted_ids() == {o.observation_id}


def test_f1_transaction_time_conflicts_are_point_in_time_too():
    a = obs(acct(1), Action.TRADE_BUY, tx="0xsame", when=at(0), receipt_delay=timedelta(0))
    log = ObservationLog()
    log.ingest([a])
    log.ingest([obs(acct(1), Action.TRADE_BUY, tx="0xsame", when=at(5), qty=3, receipt_delay=timedelta(days=5))])
    assert log.as_known_at(at(days=1)) == (a,)
    assert log.as_known_at(at(days=6)) == ()


def test_f1_select_at_a_past_date_is_reproducible_after_newer_data_arrives():
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, f"m{i}-yes", 10, "0.40", at(days=i), market=f"m{i}", event_id=f"f{i}")
            for i in range(3)]
    log = ObservationLog()
    log.ingest(rows)
    marks = {f"m{i}-yes": Mark(f"m{i}-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=i, hours=6))
             for i in range(3)}

    def run():  # type: ignore[no-untyped-def]
        return select_at(at(days=5), candidates=[Candidate(a, at(-1), "u", "v1")], logs={a.key: log},
                         history_complete={a.key: True}, marks=marks, rule=RULE, label_version="v1", trials=1,
                         mark_max_age=timedelta(minutes=5))

    before = run()
    log.ingest([replace(rows[0], native_quantity=D(99), receipt_time=at(days=20))])  # a conflicting later copy
    log.ingest([obs(a, Action.TRADE_BUY, "m9-yes", 5, "0.5", at(days=19), market="m9")])
    after = run()
    assert after.records == before.records and after.inputs_digest == before.inputs_digest


# F2: the leader's outcome is judged only on its trades inside the horizon --------------------------
def test_f2_leader_sales_after_the_horizon_are_not_matched():
    from edge_lab.wallet_intel.replay import _leader_per_unit
    from wallet_support import signal

    buy = signal("b", qty="10", price="0.40", when=at(0))
    late_sell = signal("s", Action.TRADE_SELL, qty="10", price="0.90", when=at(days=3), before="10")
    out = _leader_per_unit([buy, late_sell], {}, at(days=1))
    assert not out["b"].known  # was a known +0.50
    in_window = _leader_per_unit([buy, replace(late_sell, leader_time=at(hours=5), observable_at=at(hours=5))], {},
                                 at(days=1))
    assert in_window["b"].value == D("0.5")


def test_f2_through_replay_an_open_leader_position_at_the_horizon_is_unknown():
    from edge_lab.wallet_intel.policy import FollowerPolicy
    from edge_lab.wallet_intel.replay import replay
    from wallet_support import Books, book, config, enrolled, limits, signal

    buy = signal("b", qty="10", price="0.40", when=at(0))
    late_sell = signal("s", Action.TRADE_SELL, qty="10", price="0.90", when=at(days=3), before="10")
    r = replay([buy, late_sell], FollowerPolicy(limits(), enrollments=enrolled("L1")), initial_cash=D(100),
               books=Books(book(captured=at(1))), resolutions={}, config=config(), horizon=at(days=1))
    assert not r.leader.per_unit["b"].known and not r.leader.scaled_to_follower.known


# F3: signals are built point in time, so a later retraction cannot erase our fill -----------------
def test_f3_a_retraction_after_our_observation_keeps_the_signal_but_one_before_removes_it():
    from edge_lab.wallet_intel.events import Correction, CorrectionKind
    from edge_lab.wallet_intel.policy import signals_from_log

    o = obs(acct(1), Action.TRADE_BUY, when=at(0), receipt_delay=timedelta(seconds=30))
    for recorded, expected in ((at(30), 1), (at(0) + timedelta(seconds=40), 0)):
        log = ObservationLog()
        log.ingest([o])
        log.append_correction(Correction("c", o.observation_id, CorrectionKind.RETRACTED, recorded, "synthetic"))
        sigs = signals_from_log(log, detection_delay=timedelta(minutes=1), cluster_key=lambda k: k, strategy="s")
        assert len(sigs) == expected, recorded
        assert log.as_known_at(at(days=1)) == ()  # the horizon view has lost it either way


def test_f3_the_demo_builds_signals_point_in_time():
    import inspect

    from edge_lab.wallet_intel import demo
    source = inspect.getsource(demo.run_synthetic_demo)
    assert "signals_from_log(" in source and "signal_from_observation(" not in source


# F4: an event with any unknown market is unknown, never a win --------------------------------------
def test_f4_a_partly_unknown_event_is_not_a_win_and_is_not_pooled():
    from edge_lab.wallet_intel.accounting import event_outcomes, reconstruct
    from edge_lab.wallet_intel.exact import Labeled

    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0), market="m1", event="E"),
            obs(a, Action.TRADE_SELL, "m1-yes", 10, "0.60", at(5), market="m1", event="E"),  # +2 in E
            obs(a, Action.TRANSFER_IN, "m2-yes", 50, "0", at(1), market="m2", event="E")]  # E's other market unknown
    acc = reconstruct(rows, as_of=at(days=1), history_complete=True, cash_flows_observed=True,
                      opening_balance=Labeled.observed(D(10)), marks={}, mark_max_age=timedelta(minutes=5))
    assert "E" not in event_outcomes(acc)
    open_rows = rows[:2] + [obs(a, Action.TRADE_BUY, "m3-yes", 5, "0.5", at(2), market="m3", event="E")]
    acc = reconstruct(open_rows, as_of=at(days=1), history_complete=True, cash_flows_observed=True,
                      opening_balance=Labeled.observed(D(10)), marks={}, mark_max_age=timedelta(minutes=5))
    assert "E" not in event_outcomes(acc)  # a still-open market also keeps the event out


# F5 / F8 (P19): facts cite docs.polymarket.com where a page states them; spec citations carry the ruling --
def test_f5_spec_citations_carry_the_owner_ruling_and_docs_pages_are_preferred():
    from test_wallet_source_matrix import _rows, _text

    ruling = "owner ruling 2026-10-07: specs are documentation"
    rows = _rows("## Polymarket Data API v2 pins")
    for number, fact, klass, url, retrieved in rows:
        if "openapi.json" in url:
            assert ruling in url, number
        else:
            assert url.startswith("https://docs.polymarket.com/"), number
    docs_sourced = {r[0] for r in rows if r[3].startswith("https://docs.polymarket.com/")}
    assert {"P3", "P5", "P9", "P17", "P19", "P21", "P23", "P24"} <= docs_sourced
    rate = next(r for r in rows if r[0] == "P24")
    assert rate[2] == "DOCUMENTED" and rate[3] == "https://docs.polymarket.com/api-reference/rate-limits"
    assert "ruling pending" not in _text()
    for line in _text().splitlines():  # every other spec citation in the document carries the ruling too
        if line.startswith("|") and "openapi.json" in line:
            assert ruling in line, line[:80]


# F6: the leader-exit skip uses only exits observable when we decided -------------------------------
def test_f6_an_exit_seen_only_after_our_decision_does_not_cancel_the_entry():
    from edge_lab.wallet_intel.policy import FollowerPolicy
    from edge_lab.wallet_intel.replay import replay
    from wallet_support import Books, book, config, enrolled, limits, signal

    buy = signal("b", when=at(0), delay=timedelta(minutes=2))  # decided at 2:01, arrives at 2:02
    exit_ = signal("x", Action.TRADE_SELL, when=at(1), delay=timedelta(seconds=61, milliseconds=500), before="100")
    assert buy.observable_at + timedelta(seconds=1) < exit_.observable_at <= buy.observable_at + timedelta(seconds=2)
    r = replay([buy, exit_], FollowerPolicy(limits(), enrollments=enrolled("L1")), initial_cash=D(100),
               books=Books(book(captured=at(0))), resolutions={}, config=config(), horizon=at(days=1))
    assert {o.signal_id: o.decision for o in r.outcomes}["b"] == "BUY"


# F7: after an UNKNOWN fill the run stops new entries and the ladder count is not optimistic --------
def test_f7_unknown_fill_stops_new_entries_and_blanks_the_ladder_count():
    from edge_lab.wallet_intel.policy import FollowerPolicy
    from edge_lab.wallet_intel.replay import RequestResult, ladder, replay
    from wallet_support import Books, book, config, enrolled, limits, signal

    first_unknown = lambda sid, n: RequestResult.UNKNOWN if sid == "a" else RequestResult.OK  # noqa: E731
    sigs = [signal("a"), signal("b", token="m2-yes", market="m2", event="evt-m2", when=at(5))]
    books = Books(book(captured=at(1)), book("m2-yes", captured=at(6)))
    r = replay(sigs, FollowerPolicy(limits(), enrollments=enrolled("L1")), initial_cash=D(100), books=books,
               resolutions={}, config=config(request_outcome=first_unknown), horizon=at(days=1))
    by = {o.signal_id: o for o in r.outcomes}
    assert by["a"].fill.status.value == "UNKNOWN"
    assert by["b"].decision == "SKIP" and "STOPPED_AFTER_UNKNOWN_FILL" in by["b"].reason
    assert r.final_book.cash == D(100) and r.final_book.inventory == {}
    rows = ladder(sigs, limits(), enrolled("L1"), sizes=[D(10)], delays=[timedelta(minutes=1)], initial_cash=D(100),
                  books=books, resolutions={}, config=config(request_outcome=first_unknown), horizon=at(days=1))
    assert rows[0].filled is None and rows[0].unknown_fills == 1 and rows[0].to_dict()["filled"] is None
