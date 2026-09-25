"""Evidence consumption (append-only, holdout identity by window, legacy UNKNOWN) and attrition waterfalls."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from edge_lab.experiments import load, prohibited_inputs
from edge_lab.research_evidence import (
    LOG_NAME, OUT_OF_BAND_LIMITATION, Action, AttritionUnit, DatasetRole, EvidenceError, EvidenceUse, Exclusion,
    HoldoutState, InformationWindow, Level, ProhibitedInput, Stage, attrition_report, check_append_only,
    holdout_status, init_log, load_all_logs, read_log, record_use,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "experiments"
LOG_START = "2026-09-25T00:00:00Z"
FUTURE = InformationWindow("sports:nfl:moneyline", "2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")


def use(**over):
    base = dict(
        experiment_id="EXP-002", family="A", dataset_id="the_odds_api:nfl_h2h_paired", dataset_version="v1",
        dataset_sha256="a" * 64, role=DatasetRole.HOLDOUT, window=FUTURE, actor="claude-code:test",
        tool="pytest", action_time_utc="2026-11-02T12:00:00Z", action=Action.OPERATIONAL_ACCESS,
        code_version="deadbeef", model_version=None, prompt_version=None, viewed_features=False,
        viewed_labels=False, viewed_results=False, influenced_tuning=False,
    )
    base.update(over)
    return EvidenceUse(**base)


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "EXP-002-x" / LOG_NAME
    path.parent.mkdir()
    init_log(path, experiment_id="EXP-002", started_at_utc=LOG_START)
    return path


# --------------------------------------------------------------------------- consumption


def test_record_is_append_only_and_dedupes_only_identical_events(log):
    first = use()
    assert record_use(log, first) == "APPENDED"
    assert record_use(log, first) == "DUPLICATE"  # the identical event id
    assert record_use(log, replace(first, sequence=1)) == "APPENDED"  # a distinct view is kept
    assert record_use(log, replace(first, action_time_utc="2026-11-02T12:00:01Z")) == "APPENDED"
    parsed = read_log(log)
    assert len(parsed.uses) == 3 and parsed.started_at_utc == LOG_START
    assert len({u.event_id for u in parsed.uses}) == 3


def test_a_log_is_never_restarted_and_edited_lines_are_detected(log):
    with pytest.raises(EvidenceError):
        init_log(log, experiment_id="EXP-002", started_at_utc=LOG_START)
    record_use(log, use())
    text = log.read_text(encoding="utf-8")
    log.write_text(text.replace('"viewed_labels":false', '"viewed_labels":true'), encoding="utf-8")
    with pytest.raises(EvidenceError, match="does not match"):
        read_log(log)


def test_record_refuses_a_missing_log_and_a_foreign_experiment(tmp_path, log):
    with pytest.raises(EvidenceError):
        record_use(tmp_path / "nope.jsonl", use())
    with pytest.raises(EvidenceError, match="belongs to"):
        record_use(log, use(experiment_id="EXP-003", family="B"))


def test_untouched_evaluation_must_use_a_holdout_and_times_must_be_aware(log):
    with pytest.raises(EvidenceError):
        record_use(log, use(action=Action.UNTOUCHED_EVALUATION, role=DatasetRole.VALIDATION))
    with pytest.raises(EvidenceError):
        record_use(log, use(action_time_utc="2026-11-02 12:00:00"))
    with pytest.raises(EvidenceError):
        record_use(log, use(window=InformationWindow("s", "2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z")))


def test_family_b_cannot_log_access_to_exp001_forecasts_outcomes_or_ledger(tmp_path):
    prefixes = prohibited_inputs(load(REGISTRY / "EXP-003-same-venue-payoff-consistency" / "experiment.toml"))
    path = tmp_path / LOG_NAME
    init_log(path, experiment_id="EXP-003", started_at_utc=LOG_START)
    for dataset in ("exp001:gate3_dataset", "shadow_ledger:operational", "nws_pfm:okx", "kalshi_settlement:KXHIGHNY"):
        with pytest.raises(ProhibitedInput):
            record_use(path, use(experiment_id="EXP-003", family="B", dataset_id=dataset), prohibited_prefixes=prefixes)
    assert record_use(path, use(experiment_id="EXP-003", family="B", dataset_id="kalshi_public:KXHIGHNY_books"),
                      prohibited_prefixes=prefixes) == "APPENDED"


def _status(log_path, *uses, sha="a" * 64, window=FUTURE):
    for u in uses:
        record_use(log_path, u)
    return holdout_status([read_log(log_path)], dataset_sha256=sha, window=window)


def test_future_holdout_with_only_blind_operational_access_is_untouched(log):
    status = _status(log, use())
    assert status.state is HoldoutState.UNTOUCHED and status.clean_untouched_claim_allowed
    assert status.limitation == OUT_OF_BAND_LIMITATION


def test_feature_inspection_is_not_untouched(log):
    status = _status(log, use(action=Action.FEATURE_INSPECTION, viewed_features=True))
    assert status.state is HoldoutState.FEATURES_VIEWED and not status.clean_untouched_claim_allowed


def test_the_single_evaluation_consumes_the_holdout(log):
    status = _status(log, use(action=Action.UNTOUCHED_EVALUATION, viewed_labels=True, viewed_results=True))
    assert status.state is HoldoutState.CONSUMED and not status.clean_untouched_claim_allowed


@pytest.mark.parametrize("over", [
    dict(action=Action.LABEL_RESULT_INSPECTION, viewed_labels=True),
    dict(action=Action.VALIDATION_TUNING, role=DatasetRole.VALIDATION),
    dict(action=Action.TRAINING_DEVELOPMENT, role=DatasetRole.DEVELOPMENT),
    dict(viewed_results=True),
    dict(influenced_tuning=True),
    dict(viewed_labels=None),  # unknown counts as viewed
    dict(action=Action.UNTOUCHED_EVALUATION, viewed_labels=True, viewed_results=True, influenced_tuning=None),
])
def test_label_result_viewing_tuning_or_unknowns_contaminate(log, over):
    status = _status(log, use(**over))
    assert status.state is HoldoutState.CONTAMINATED and status.reasons


def test_copying_or_rehashing_the_same_outcomes_never_restores_untouched(log):
    record_use(log, use(action=Action.UNTOUCHED_EVALUATION, viewed_labels=True, viewed_results=True))
    copied = InformationWindow(FUTURE.scope, "2026-10-15T00:00:00Z", "2026-11-15T00:00:00Z")  # overlaps
    status = holdout_status([read_log(log)], dataset_sha256="b" * 64, window=copied)
    assert status.state is HoldoutState.CONSUMED
    elsewhere = InformationWindow("kalshi:KXHIGHNY", FUTURE.start_utc, FUTURE.end_utc)
    assert holdout_status([read_log(log)], dataset_sha256="b" * 64, window=elsewhere).state is HoldoutState.UNTOUCHED
    later = InformationWindow(FUTURE.scope, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    assert holdout_status([read_log(log)], dataset_sha256="b" * 64, window=later).state is HoldoutState.UNTOUCHED


def test_consumption_is_judged_across_every_experiments_log(tmp_path, log):
    other = tmp_path / "EXP-003-y" / LOG_NAME
    other.parent.mkdir()
    init_log(other, experiment_id="EXP-003", started_at_utc=LOG_START)
    record_use(other, use(experiment_id="EXP-003", family="B", action=Action.LABEL_RESULT_INSPECTION,
                          viewed_labels=True, dataset_sha256="c" * 64))
    status = holdout_status(load_all_logs(tmp_path), dataset_sha256="a" * 64, window=FUTURE)
    assert status.state is HoldoutState.CONTAMINATED


def test_legacy_history_is_unknown_never_certified_untouched(log):
    past = InformationWindow(FUTURE.scope, "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")
    assert holdout_status([read_log(log)], dataset_sha256="z" * 64, window=past).state is HoldoutState.UNKNOWN_LEGACY
    assert holdout_status([], dataset_sha256="z" * 64, window=FUTURE).state is HoldoutState.UNKNOWN_LEGACY


def test_the_real_registry_logs_are_valid_and_start_empty():
    logs = load_all_logs(REGISTRY)
    assert {log.experiment_id for log in logs} >= {"EXP-002", "EXP-003"}
    assert all(log.started_at_utc for log in logs)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_append_only_check_against_a_git_base(tmp_path):
    repo = tmp_path / "repo"
    path = repo / "experiments" / "EXP-002-x" / LOG_NAME
    path.parent.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    init_log(path, experiment_id="EXP-002", started_at_utc=LOG_START)
    record_use(path, use())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    record_use(path, use(sequence=1))
    _git(repo, "commit", "-q", "-am", "append")
    assert check_append_only(base, repo=repo) == []
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")  # drop a line
    _git(repo, "commit", "-q", "-am", "rewrite")
    assert any("only be appended" in p for p in check_append_only(base, repo=repo))
    path.unlink()
    _git(repo, "commit", "-q", "-am", "delete")
    assert any("only be appended" in p for p in check_append_only(base, repo=repo))


# --------------------------------------------------------------------------- attrition


AS_OF = "2026-09-25T12:00:00Z"
ALL = list(Level)


def _opp(uid, *reasons, **kw):
    return AttritionUnit(Level.OPPORTUNITY, uid, tuple(reasons), **kw)


def test_waterfall_reconciles_with_one_primary_reason_and_keeps_every_raw_reason():
    units = [
        _opp("o1", "STALE", "INSUFFICIENT_DEPTH", cluster_id="g1"),  # primary STALE
        _opp("o2", "INSUFFICIENT_DEPTH", "CAPITAL_VETO", cluster_id="g1"),  # primary INSUFFICIENT_DEPTH
        _opp("o3", "NO_SIGNAL", cluster_id="g2"),
        _opp("o4", "NO_FILL", cluster_id="g2"),
        _opp("o5", "OUTCOME_PENDING", cluster_id="g3"),
        _opp("o6", cluster_id="g3"),
        _opp("o7", "COLLECTION_FAILURE", "STALE", cluster_id="g4"),
    ]
    report = attrition_report(units, as_of_utc=AS_OF, levels_enumerated=ALL)
    opp = next(w for w in report.waterfalls if w.level == "OPPORTUNITY")
    primaries = {r.exclusion: r.primary_count for r in opp.rows}
    assert primaries["STALE"] == 1 and primaries["INSUFFICIENT_DEPTH"] == 1 and primaries["CAPITAL_VETO"] == 0
    assert primaries["COLLECTION_FAILURE"] == 1
    assert sum(v for v in primaries.values()) + opp.survivors == opp.start == 7 and opp.reconciled
    assert opp.raw_reason_counts["STALE"] == 2 and opp.raw_reason_counts["CAPITAL_VETO"] == 1
    assert opp.clusters == 4
    d = report.denominators
    assert (d["opportunities"], d["eligible_opportunities"], d["signals"], d["simulated_fills"],
            d["final_evaluable_outcomes"]) == (7, 4, 3, 2, 1)


def test_no_signal_no_fill_and_collection_failure_are_distinct():
    units = [_opp("a", "NO_SIGNAL"), _opp("b", "NO_FILL"), _opp("c", "COLLECTION_FAILURE")]
    opp = next(w for w in attrition_report(units, as_of_utc=AS_OF, levels_enumerated=ALL).waterfalls
               if w.level == "OPPORTUNITY")
    counts = {r.exclusion: r.primary_count for r in opp.rows}
    assert counts["NO_SIGNAL"] == counts["NO_FILL"] == counts["COLLECTION_FAILURE"] == 1


def test_a_future_target_is_never_missed_before_its_deadline():
    units = [
        AttritionUnit(Level.HORIZON, "h-future", ("MISSED_TARGET",), deadline_utc="2026-09-26T00:00:00Z"),
        AttritionUnit(Level.HORIZON, "h-past", ("MISSED_TARGET",), deadline_utc="2026-09-24T00:00:00Z"),
        AttritionUnit(Level.HORIZON, "h-fail-future", ("COLLECTION_FAILURE",), deadline_utc="2026-09-26T00:00:00Z"),
    ]
    report = attrition_report(units, as_of_utc=AS_OF, levels_enumerated=ALL)
    horizon = next(w for w in report.waterfalls if w.level == "HORIZON")
    counts = {r.exclusion: r.primary_count for r in horizon.rows}
    assert counts["PENDING_TARGET"] == 2 and counts["MISSED_TARGET"] == 1 and counts["COLLECTION_FAILURE"] == 0
    assert horizon.corrected_premature == ("h-fail-future", "h-future")


def test_zero_is_not_missing():
    report = attrition_report([], as_of_utc=AS_OF, levels_enumerated=[Level.EVENT])
    assert report.denominators["events"] == 0
    assert report.denominators["markets"] is None and report.denominators["final_evaluable_outcomes"] is None
    with pytest.raises(ValueError, match="not declared enumerated"):
        attrition_report([AttritionUnit(Level.MARKET, "m")], as_of_utc=AS_OF, levels_enumerated=[Level.EVENT])


def test_not_applicable_stages_report_none_and_refuse_their_reasons():
    report = attrition_report([_opp("a"), _opp("b", "NO_SIGNAL")], as_of_utc=AS_OF, levels_enumerated=ALL,
                              not_applicable_stages=[Stage.FILL])
    assert report.denominators["simulated_fills"] is None and report.denominators["signals"] == 1
    opp = next(w for w in report.waterfalls if w.level == "OPPORTUNITY")
    assert next(r for r in opp.rows if r.exclusion == "NO_FILL").primary_count is None
    with pytest.raises(ValueError, match="NOT_APPLICABLE"):
        attrition_report([_opp("c", "NO_FILL")], as_of_utc=AS_OF, levels_enumerated=ALL,
                         not_applicable_stages=[Stage.FILL])


def test_duplicates_and_unknown_reasons_are_refused():
    with pytest.raises(ValueError, match="double count"):
        attrition_report([_opp("x"), _opp("x")], as_of_utc=AS_OF, levels_enumerated=ALL)
    with pytest.raises(ValueError, match="unknown attrition reason"):
        attrition_report([_opp("x", "SOMETHING_ELSE")], as_of_utc=AS_OF, levels_enumerated=ALL)


def test_report_is_deterministic_and_order_independent():
    units = [_opp("o1", "STALE"), _opp("o2"), AttritionUnit(Level.EVENT, "e1"), _opp("o3", "NO_SIGNAL")]
    a = attrition_report(units, as_of_utc=AS_OF, levels_enumerated=ALL)
    b = attrition_report(list(reversed(units)), as_of_utc=AS_OF, levels_enumerated=ALL)
    assert a.report_sha256 == b.report_sha256 and a.to_dict() == b.to_dict()
    assert [e.value for e in Exclusion][0] == "PENDING_TARGET"


def test_cli_record_use_refuses_prohibited_inputs_and_reports_status(tmp_path, capsys):
    import json
    import shutil

    from edge_lab.cli import main

    root = tmp_path / "experiments"
    target = root / "EXP-003-same-venue-payoff-consistency"
    shutil.copytree(REGISTRY / target.name, target)
    event = use(experiment_id="EXP-003", family="B", dataset_id="exp001:gate3_dataset").to_dict()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(event), encoding="utf-8")
    assert main(["experiments", "record-use", "EXP-003", "--use", str(bad), "--root", str(root)]) == 1
    event.update(dataset_id="kalshi_public:KXHIGHNY_books")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(event), encoding="utf-8")
    assert main(["experiments", "record-use", "EXP-003", "--use", str(good), "--root", str(root)]) == 0
    assert main(["experiments", "record-use", "EXP-003", "--use", str(good), "--root", str(root)]) == 0
    assert "DUPLICATE" in capsys.readouterr().out
    assert main(["experiments", "holdout-status", "--dataset-sha256", "a" * 64, "--scope", FUTURE.scope,
                 "--start", FUTURE.start_utc, "--end", FUTURE.end_utc, "--root", str(root)]) == 0
    assert '"state": "UNTOUCHED"' in capsys.readouterr().out
