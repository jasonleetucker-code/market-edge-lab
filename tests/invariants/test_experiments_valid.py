from pathlib import Path

from edge_lab.experiments import validate_all

ROOT = Path(__file__).resolve().parents[2] / "experiments"


def test_registry_is_not_empty():
    assert validate_all(ROOT)


def test_all_experiment_manifests_are_valid():
    failures = {path: problems for path, problems in validate_all(ROOT).items() if problems}
    assert not failures, failures
