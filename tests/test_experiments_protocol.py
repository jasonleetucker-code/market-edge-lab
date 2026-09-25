"""Research-protocol sidecar (EE v1): honest DRAFT, strict PREREGISTERED, family slots, legacy EXP-001."""

import json
import re
import shutil
from pathlib import Path

from edge_lab import experiments
from edge_lab.experiments import (
    MAX_ACTIVE_FAMILIES, PROTOCOL_NAME, freeze, frozen_hash, frozen_view, load, protocol_state, prohibited_inputs,
    validate, validate_all,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "experiments"
EXP2 = REGISTRY / "EXP-002-nfl-consensus-vs-event-market"
EXP3 = REGISTRY / "EXP-003-same-venue-payoff-consistency"
EXP1 = REGISTRY / "EXP-001-kxhighny-nws-vs-market"


def _copy(tmp_path, source=EXP2, name=None, edit_manifest=None, edit_protocol=None):
    target = tmp_path / (name or source.name)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("evidence_use.jsonl"))
    if edit_manifest:
        path = target / "experiment.toml"
        path.write_text(edit_manifest(path.read_text(encoding="utf-8")), encoding="utf-8")
    if edit_protocol:
        path = target / PROTOCOL_NAME
        path.write_text(edit_protocol(path.read_text(encoding="utf-8")), encoding="utf-8")
    return target


def _problems(path):
    return validate(load(path / "experiment.toml"))


def test_the_real_registry_holds_exactly_the_two_new_draft_families():
    results = validate_all(REGISTRY)
    assert not any(results.values()), results
    for path, family in ((EXP2, "A"), (EXP3, "B")):
        exp = load(path / "experiment.toml")
        assert exp.status == "DRAFT" and protocol_state(exp) == "PRESENT"
        assert experiments.load_protocol(exp)["family"] == family


def test_exp001_is_read_as_legacy_and_its_frozen_baseline_is_byte_identical():
    exp = load(EXP1 / "experiment.toml")
    assert protocol_state(exp) == "LEGACY" and experiments.load_protocol(exp) is None
    baseline = json.loads((EXP1 / "preregistration.json").read_text(encoding="utf-8"))
    assert frozen_hash(frozen_view(exp.data)) != "" and "protocol" not in baseline
    assert frozen_hash(baseline["frozen_fields"]) == baseline["frozen_fields_sha256"]
    assert experiments.baseline_problems(exp) == [] and experiments.protocol_problems(exp) == []


def test_draft_with_explicit_unknowns_is_valid_but_preregistered_requires_them_settled(tmp_path):
    assert _problems(_copy(tmp_path)) == []
    locked = _copy(tmp_path, name="EXP-002-locked", edit_manifest=lambda s: s.replace(
        'status = "DRAFT"', 'status = "PREREGISTERED"'))
    problems = _problems(locked)
    unsettled = [p for p in problems if "unsettled protocol field" in p]
    labels = " ".join(unsettled)
    for field in ("endpoints.primary", "episode.start_threshold", "economics.minimum_useful_effect",
                  "stopping.futility", "evaluation.untouched_future_window", "size_capital.size_ladder",
                  "budget.owner_hours"):
        assert field in labels, (field, unsettled)
    # [knowledge] may honestly stay UNKNOWN after preregistration.
    assert "knowledge." not in labels


def test_every_protocol_field_must_be_present_even_as_unknown(tmp_path):
    exp = _copy(tmp_path, edit_protocol=lambda s: s.replace(
        'minimum_size = "UNKNOWN: frozen before any outcome is viewed."\n', ""))
    assert any("[episode] missing or empty 'minimum_size'" in p for p in _problems(exp))
    blank = _copy(tmp_path, name="EXP-002-blank", edit_protocol=lambda s: s.replace(
        'review_date = "2026-10-22"', 'review_date = ""'))
    assert any("'review_date'" in p for p in _problems(blank))
    bad_date = _copy(tmp_path, name="EXP-002-baddate", edit_protocol=lambda s: s.replace(
        'review_date = "2026-10-22"', 'review_date = "next month"'))
    assert any("review_date must be" in p for p in _problems(bad_date))


def test_new_experiment_without_a_sidecar_is_refused(tmp_path):
    target = _copy(tmp_path)
    (target / PROTOCOL_NAME).unlink()
    assert any("needs a protocol.toml sidecar" in p for p in _problems(target))
    backdated = _copy(tmp_path, name="EXP-002-backdated",
                      edit_manifest=lambda s: s.replace('created = "2026-09-25"', 'created = "2026-01-01"'))
    (backdated / PROTOCOL_NAME).unlink()
    assert any("needs a protocol.toml sidecar" in p for p in _problems(backdated))  # a backdated date is no exemption


def test_sidecar_must_name_its_own_experiment_and_one_family_token(tmp_path):
    exp = _copy(tmp_path, edit_protocol=lambda s: s.replace('experiment_id = "EXP-002"', 'experiment_id = "EXP-009"')
                .replace('family = "A"', 'family = "A and C"'))
    problems = _problems(exp)
    assert any("experiment_id" in p for p in problems)
    assert any("one uppercase token" in p for p in problems)


def _registry_with_families(tmp_path, families, exception=None):
    root = tmp_path / "experiments"
    root.mkdir()
    for n, family in enumerate(families, start=2):
        name = f"EXP-{n:03d}-f{family.lower()}{n}"

        def edit_protocol(s, family=family, n=n):
            s = s.replace('family = "A"', f'family = "{family}"').replace('experiment_id = "EXP-002"',
                                                                         f'experiment_id = "EXP-{n:03d}"')
            if exception and family == exception[0]:
                s = s.replace('slot_status = "ACTIVE"', f'slot_status = "ACTIVE"\nowner_exception = "{exception[1]}"')
            return s

        _copy(root, name=name, edit_manifest=lambda s, n=n: s.replace('id = "EXP-002"', f'id = "EXP-{n:03d}"'),
              edit_protocol=edit_protocol)
    return root


def test_at_most_two_new_active_families(tmp_path):
    assert MAX_ACTIVE_FAMILIES == 2
    root = _registry_with_families(tmp_path, ["A", "B", "C"])
    failures = {k: v for k, v in validate_all(root).items() if v}
    assert len(failures) == 1
    (key, problems), = failures.items()
    assert "fc" in key and any("active family #3" in p for p in problems)


def test_several_experiments_may_share_one_family_slot(tmp_path):
    root = _registry_with_families(tmp_path, ["A", "A", "B"])
    assert not any(validate_all(root).values())


def test_an_extra_family_needs_an_existing_owner_exception_document(tmp_path):
    (tmp_path / "docs" / "owner").mkdir(parents=True)
    (tmp_path / "docs" / "owner" / "ok.md").write_text("owner decision", encoding="utf-8")
    (tmp_path / "README.md").write_text("not an owner decision", encoding="utf-8")
    root = _registry_with_families(tmp_path, ["A", "B", "C"], exception=("C", "docs/owner/ok.md"))
    assert not any(validate_all(root).values())
    outside = tmp_path / "third"
    outside.mkdir()
    (outside / "README.md").write_text("x", encoding="utf-8")
    root3 = _registry_with_families(outside, ["A", "B", "C"], exception=("C", "README.md"))
    problems = [p for ps in validate_all(root3).values() for p in ps]
    assert any("inside docs/owner/" in p for p in problems) and any("active family #3" in p for p in problems)
    escape = tmp_path / "fourth"
    escape.mkdir()
    (escape / "docs" / "owner").mkdir(parents=True)
    (escape / "README.md").write_text("x", encoding="utf-8")
    root4 = _registry_with_families(escape, ["A", "B", "C"], exception=("C", "docs/owner/../../README.md"))
    problems4 = [p for ps in validate_all(root4).values() for p in ps]
    assert any("inside docs/owner/" in p for p in problems4) and any("active family #3" in p for p in problems4)
    missing = tmp_path / "second"
    missing.mkdir()
    root2 = _registry_with_families(missing, ["A", "B", "C"], exception=("C", "no_such_file.md"))
    assert any(validate_all(root2).values())


def test_ended_or_concluded_families_free_their_slot(tmp_path):
    root = _registry_with_families(tmp_path, ["A", "B", "C"])
    third = next(p for p in root.iterdir() if p.name.startswith("EXP-004"))
    protocol = third / PROTOCOL_NAME
    protocol.write_text(protocol.read_text(encoding="utf-8").replace('slot_status = "ACTIVE"', 'slot_status = "QUEUED"'),
                        encoding="utf-8")
    assert not any(validate_all(root).values())


def _settled(text):
    import re

    pattern = r'"[^"\n]*(UNKNOWN|UNVERIFIED|TBD|MISSING_OWNER_INPUT|MISSING_POWER_ANALYSIS|to be frozen|to be chosen)[^"\n]*"'
    text = re.sub(pattern, '"settled concrete value"', text)
    return re.sub(r'(min_episodes_for_scenario|min_independent_clusters) = "settled concrete value"', r"\1 = 12", text)


def _decided(text):
    return re.sub(r"open_decisions = \[.*?\n\]", "open_decisions = []", _settled(text), flags=re.S)


def _settled_manifest(text):
    import re

    return re.sub(r'"TBD[^"]*"', '"concrete value"', text).replace('status = "DRAFT"', 'status = "PREREGISTERED"')


def test_freeze_includes_the_protocol_and_detects_a_later_protocol_edit(tmp_path):
    target = _copy(tmp_path, edit_manifest=_settled_manifest, edit_protocol=_decided)
    exp = load(target / "experiment.toml")
    assert [p for p in validate(exp) if "baseline" not in p] == []
    baseline_path = freeze(exp, now_utc="2026-09-25T12:00:00Z")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline["protocol_sha256"] == frozen_hash(baseline["protocol"])
    assert validate(load(target / "experiment.toml")) == []
    protocol = target / PROTOCOL_NAME
    protocol.write_text(protocol.read_text(encoding="utf-8").replace("2026-10-22", "2026-12-31"), encoding="utf-8")
    assert any("protocol.toml changed since preregistration" in p for p in validate(load(target / "experiment.toml")))


def test_protocol_amendments_may_name_protocol_fields(tmp_path):
    target = _copy(tmp_path, edit_manifest=lambda s: s + (
        '\n[[amendments]]\ndate = "2026-09-26"\nfield = "protocol.episode.minimum_size"\n'
        'change = "x"\nreason = "y"\n'))
    assert _problems(target) == []
    bad = _copy(tmp_path, name="EXP-002-bad", edit_manifest=lambda s: s + (
        '\n[[amendments]]\ndate = "2026-09-26"\nfield = "protocol.nonsense"\nchange = "x"\nreason = "y"\n'))
    assert any("unknown field" in p for p in _problems(bad))


def test_family_b_prohibits_exp001_forecasts_outcomes_and_ledger():
    prohibited = prohibited_inputs(load(EXP3 / "experiment.toml"))
    for prefix in ("exp001:", "shadow_ledger:", "nws_pfm:", "kalshi_settlement:"):
        assert prefix in prohibited
    assert prohibited_inputs(load(EXP1 / "experiment.toml")) == ()



def test_preregistered_rejects_unsettled_tokens_anywhere_in_a_value(tmp_path):
    for bad in ("frozen later: will be decided after a look", "20 games, source links UNKNOWN", "0.05 (UNVERIFIED)"):
        target = _copy(tmp_path, name=f"EXP-002-{abs(hash(bad))}", edit_manifest=_settled_manifest,
                       edit_protocol=lambda s, bad=bad: _settled(s).replace(
                           'review_date = "2026-10-22"', 'review_date = "2026-10-22"').replace(
                           'futility = "settled concrete value"', f'futility = "{bad}"'))
        assert any("stopping.futility" in p for p in _problems(target)), bad



def test_prohibited_fields_must_be_field_names():
    from edge_lab.experiments import prohibited_fields

    assert "result" in prohibited_fields(load(EXP3 / "experiment.toml"))
    assert prohibited_fields(load(EXP1 / "experiment.toml")) == ()


def test_prohibited_fields_reject_non_field_entries(tmp_path):
    exp = _copy(tmp_path, source=EXP3, edit_protocol=lambda s: s.replace(
        '"settlement_ts"]', '"settlement_ts", "last price after close"]'))
    assert any("prohibited_fields must be a list of record field names" in p for p in _problems(exp))



def test_open_decisions_block_preregistration(tmp_path):
    settled = _copy(tmp_path, edit_manifest=_settled_manifest, edit_protocol=_settled)
    problems = [p for p in _problems(settled) if "baseline" not in p]
    assert any("open decision" in p for p in problems) and len(problems) == 1  # EXP-002 lists five
    emptied = _copy(tmp_path, name="EXP-002-decided", edit_manifest=_settled_manifest,
                    edit_protocol=lambda s: re.sub(r"open_decisions = \[.*?\n\]", "open_decisions = []",
                                                   _settled(s), flags=re.S))
    assert [p for p in _problems(emptied) if "baseline" not in p] == []
    draft = _copy(tmp_path, name="EXP-002-draft")
    assert _problems(draft) == []  # a DRAFT may list open decisions



def test_preregistered_count_minimums_are_whole_numbers_of_at_least_two(tmp_path):
    for value, ok in (("0", False), ("1", False), ("2.5", False), ("2", True), ("30", True)):
        target = _copy(tmp_path, name=f"EXP-002-min{value.replace('.', '_')}", edit_manifest=_settled_manifest,
                       edit_protocol=lambda s, v=value: re.sub(
                           r'min_independent_clusters = \S+', f"min_independent_clusters = {v}",
                           _decided(s)))
        problems = [p for p in _problems(target) if "baseline" not in p]
        assert (not any("min_independent_clusters must be a whole number" in p for p in problems)) == ok, (value, problems)


def test_the_screen_test_ids_are_reserved(tmp_path):
    target = _copy(tmp_path, name="EXP-900-real", edit_manifest=lambda s: s.replace('id = "EXP-002"', 'id = "EXP-900"'),
                   edit_protocol=lambda s: s.replace('experiment_id = "EXP-002"', 'experiment_id = "EXP-900"'))
    assert any("reserved for unit tests" in p for p in _problems(target))


def test_holdout_windows_are_machine_readable(tmp_path):
    from edge_lab.experiments import holdout_windows

    assert holdout_windows(load(EXP3 / "experiment.toml")) == []  # untouched window still UNKNOWN: none declared
    bad = _copy(tmp_path, source=EXP3, edit_protocol=lambda s: s.replace(
        "[evaluation]\n", '[evaluation]\nholdout_windows = ["2026-11"]\n'))
    assert any("holdout_windows must be a list" in p for p in _problems(bad))
    good = _copy(tmp_path, source=EXP3, name="EXP-003-good", edit_protocol=lambda s: s.replace(
        "[evaluation]\n", '[evaluation]\nholdout_windows = [{scope = "kalshi:KXHIGHNY", start_utc = '
                          '"2026-11-01T00:00:00Z", end_utc = "2026-12-31T23:59:59Z"}]\n'))
    assert _problems(good) == []
    assert holdout_windows(load(good / "experiment.toml")) == [
        ("kalshi:KXHIGHNY", "2026-11-01T00:00:00Z", "2026-12-31T23:59:59Z")]
