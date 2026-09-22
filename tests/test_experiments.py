import shutil
from pathlib import Path

from edge_lab.experiments import validate_all

EXP_001 = Path(__file__).resolve().parents[1] / "experiments" / "EXP-001-kxhighny-nws-vs-market"


def _registry(tmp_path, text=None, dirname="EXP-001-test"):
    target = tmp_path / dirname
    target.mkdir()
    source = (EXP_001 / "experiment.toml").read_text()
    (target / "experiment.toml").write_text(text(source) if text else source)
    return tmp_path


def _problems(root):
    (problems,) = validate_all(root).values()
    return problems


def test_draft_manifest_is_valid(tmp_path):
    assert _problems(_registry(tmp_path)) == []


def test_missing_failure_criteria_is_rejected(tmp_path):
    root = _registry(tmp_path, lambda s: s.replace("failure_criteria = [", "old_failure_criteria = ["))
    assert any("failure_criteria" in p for p in _problems(root))


def test_preregistered_requires_defined_periods(tmp_path):
    root = _registry(tmp_path, lambda s: s.replace('status = "DRAFT"', 'status = "PREREGISTERED"'))
    problems = _problems(root)
    assert any("periods.test" in p for p in problems)
    assert any("'decision_time'" in p for p in problems)
    assert any("costs.fee_model" in p for p in problems)


def test_preregistered_rejects_tbd_variants(tmp_path):
    root = _registry(
        tmp_path,
        lambda s: s.replace('status = "DRAFT"', 'status = "PREREGISTERED"').replace('test = "TBD"', 'test = "tbd later"'),
    )
    assert any("periods.test" in p for p in _problems(root))


def test_impossible_created_date_and_blank_list_items_are_rejected(tmp_path):
    root = _registry(
        tmp_path,
        lambda s: s.replace('created = "2026-09-22"', 'created = "2026-99-99"').replace(
            "features = [", 'features = [\n  "",'
        ),
    )
    problems = _problems(root)
    assert any("created" in p for p in problems)
    assert any("features" in p for p in problems)


def test_concluded_requires_result_evidence(tmp_path):
    root = _registry(tmp_path, lambda s: s.replace('status = "DRAFT"', 'status = "CONCLUDED_FAIL"'))
    assert any("[result]" in p for p in _problems(root))


def test_unknown_status_and_directory_mismatch_are_rejected(tmp_path):
    root = _registry(tmp_path, lambda s: s.replace('status = "DRAFT"', 'status = "WINNING"'), dirname="EXP-999-x")
    problems = _problems(root)
    assert any("status" in p for p in problems)
    assert any("directory" in p for p in problems)


def test_amendments_need_reason(tmp_path):
    root = _registry(tmp_path, lambda s: s + '\n[[amendments]]\ndate = "2026-09-23"\nchange = "x"\n')
    assert any("amendment" in p for p in _problems(root))


def test_duplicate_ids_are_rejected(tmp_path):
    _registry(tmp_path)
    shutil.copytree(tmp_path / "EXP-001-test", tmp_path / "EXP-001-copy")
    problems = [p for ps in validate_all(tmp_path).values() for p in ps]
    assert any("duplicate id" in p for p in problems)


import pytest  # noqa: E402

LOCK = ('status = "DRAFT"', 'status = "PREREGISTERED"')


def _locked_concrete(source):
    """EXP-001 with every TBD replaced by concrete text, then locked."""
    import re

    concrete = re.sub(r'"TBD[^"]*"', '"concrete value"', source)
    return concrete.replace(*LOCK)


def test_fully_specified_locked_manifest_is_valid(tmp_path):
    assert _problems(_registry(tmp_path, _locked_concrete)) == []


@pytest.mark.parametrize(
    "mutate, label",
    [
        (lambda s: s.replace('model = "concrete value"', 'model = "TODO"'), "model"),
        (lambda s: s.replace('decision_time = "concrete value"', 'decision_time = "to be determined"'), "decision_time"),
        (lambda s: s.replace('fee_model = "concrete value"', 'fee_model = ""'), "costs.fee_model"),
        (lambda s: s.replace('test = "concrete value"', 'test = { start = "TBD" }'), "periods.test.start"),
        (lambda s: s.replace('train = "concrete value"', 'train = "?"'), "periods.train"),
        (lambda s: s.replace('latency = "concrete value"', 'latency = ["pending"]'), "execution.latency[0]"),
        (lambda s: s.replace('success_criteria = [', 'success_criteria = [\n  "TBD",'), "success_criteria[0]"),
        (lambda s: s.replace('hypothesis = """', 'hypothesis = """TBD '), "hypothesis"),
    ],
)
def test_locked_manifest_rejects_placeholder_variants(tmp_path, mutate, label):
    root = _registry(tmp_path, lambda s: mutate(_locked_concrete(s)))
    assert any(f"'{label}'" in p for p in _problems(root)), _problems(root)


def test_costs_and_execution_must_name_their_assumptions(tmp_path):
    root = _registry(tmp_path, lambda s: s.replace("[costs]", "[costs]\n# emptied").replace('fee_model = "TBD', 'x_fee = "TBD'))
    assert any("[costs] missing 'fee_model'" in p for p in _problems(root))
