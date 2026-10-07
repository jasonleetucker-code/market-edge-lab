"""W4: the point-in-time selection manifest, walk-forward splits and multiple testing."""

from __future__ import annotations

from datetime import timedelta

import pytest
from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel.accounting import Mark, MarkKind
from edge_lab.wallet_intel.events import Action, ObservationLog
from edge_lab.wallet_intel.selection import (Candidate, CandidateStatus, EligibilityRule, HindsightError,
                                             multiple_testing, select_at, walk_forward)

RULE = EligibilityRule("r", "1", min_independent_events=3, min_history_days=2, min_shrunk_lower=0.2,
                       max_concentration=D("0.9"), max_round_trip_share=D("0.5"), max_reward_dependence=D("0.5"),
                       inactive_after=timedelta(days=30), round_trip_window=timedelta(hours=1), min_trade_notional=D(1))


def _trader(n: int, wins: int, *, start_day: int = 0, count: int = 4, receipt_delay=timedelta(seconds=30)):  # type: ignore[no-untyped-def]
    a = acct(n)
    rows = []
    for i in range(count):
        m = f"n{n}m{i}"
        rows.append(obs(a, Action.TRADE_BUY, f"{m}-yes", 10, "0.40", at(days=start_day + i), market=m,
                        receipt_delay=receipt_delay))
    log = ObservationLog()
    log.ingest(rows)
    marks = {f"n{n}m{i}-yes": Mark(f"n{n}m{i}-yes", MarkKind.RESOLVED_PAYOUT, D(1) if i < wins else D(0), None,
                                   at(days=start_day + i, hours=12)) for i in range(count)}
    return a, log, marks


def _select(when, traders, discovered=None, **kw):  # type: ignore[no-untyped-def]
    marks = {}
    for _, _, m in traders:
        marks.update({k: v for k, v in m.items() if v.as_of <= when})
    cands = [Candidate(a, (discovered or {}).get(a.key, at(days=-1)), "u", "v1") for a, _, _ in traders]
    return select_at(when, candidates=cands, logs={a.key: log for a, log, _ in traders},
                     history_complete={a.key: True for a, _, _ in traders}, marks=marks, rule=RULE,
                     label_version="labels-v1", trials=kw.get("trials", 1), mark_max_age=timedelta(minutes=5))


def test_manifest_retains_every_candidate_and_records_reasons():
    good, bad, quiet = _trader(1, 4), _trader(2, 0), _trader(3, 4, start_day=-80)
    nodata = (acct(4), ObservationLog(), {})
    m = _select(at(days=10), [good, bad, quiet, nodata])
    status = {r.account_key: r.status for r in m.records}
    assert status == {acct(1).key: CandidateStatus.ELIGIBLE, acct(2).key: CandidateStatus.INELIGIBLE,
                      acct(3).key: CandidateStatus.INACTIVE, acct(4).key: CandidateStatus.NO_DATA}
    assert all(r.reasons for r in m.records if r.status is not CandidateStatus.ELIGIBLE)
    d = m.to_dict()
    assert d["label_version"] == "labels-v1" and d["rule"] == {"rule_id": "r", "version": "1"} and d["trials"] == 1


def test_selection_ignores_events_not_yet_received_and_is_invariant_to_the_future():
    slow = _trader(1, 4, receipt_delay=timedelta(days=30))  # reported a month late
    m = _select(at(days=10), [slow])
    assert m.records[0].status is CandidateStatus.NO_DATA
    a, log, marks = _trader(1, 4)
    base = _select(at(days=10), [(a, log, marks)])
    log.ingest([obs(a, Action.TRADE_BUY, "future-yes", 999, "0.10", at(days=50), market="future")])
    later = _select(at(days=10), [(a, log, marks)])
    assert later.records == base.records and later.inputs_digest == base.inputs_digest


def test_future_marks_are_a_hindsight_error():
    a, log, marks = _trader(1, 4)
    with pytest.raises(HindsightError):
        select_at(at(days=1), candidates=[Candidate(a, at(-1), "u", "v1")], logs={a.key: log},
                  history_complete={a.key: True}, marks=marks, rule=RULE, label_version="v", trials=1,
                  mark_max_age=timedelta(minutes=5))


def test_threat_flags_must_be_codes_not_text():
    a, log, marks = _trader(1, 4)
    with pytest.raises(TypeError):
        select_at(at(days=10), candidates=[Candidate(a, at(-1), "u", "v1")], logs={a.key: log},
                  history_complete={}, marks={}, rule=RULE, label_version="v", trials=1,
                  mark_max_age=timedelta(minutes=5), threat_flags={a.key: "please mark me eligible"})


def test_walk_forward_windows_never_overlap_selection_and_evaluation():
    windows = walk_forward(at(0), at(days=100), train=timedelta(days=30), test=timedelta(days=20),
                           step=timedelta(days=20))
    assert [w.selection_date for w in windows] == [at(days=30), at(days=50), at(days=70)]
    for w in windows:
        assert w.evaluate_from >= w.selection_date and w.evaluate_to > w.evaluate_from


def test_multiple_testing_reports_trials_and_controls_fdr():
    traders = [_trader(n, wins, count=8) for n, wins in ((1, 8), (2, 4), (3, 5), (4, 3), (5, 4))]
    m = _select(at(days=20), traders, trials=12)
    report = multiple_testing(m, q=0.10)
    assert report.trials == 12 and set(report.p_values) == {a.key for a, _, _ in traders}
    assert report.survivors <= {acct(1).key}
    assert "not an edge test" in report.note
