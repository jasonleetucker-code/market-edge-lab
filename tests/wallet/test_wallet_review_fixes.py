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
