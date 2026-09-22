from __future__ import annotations

import subprocess
import sys

import pytest

from scripts import validate


def tree(tmp_path):
    for folder in ("src/edge_lab", "scripts", "tests", "experiments"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "src/edge_lab/cli.py").write_text("x = 1\n")
    (tmp_path / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n")
    return tmp_path


def test_quick_is_explicitly_syntax_only(tmp_path):
    report = validate.run_checks(tree(tmp_path), "quick", [], "origin/main")
    assert report["status"] == "REQUESTED_CHECKS_PASSED"
    assert [c["name"] for c in report["checks"]] == ["python_syntax"]
    assert report["ci_verified"] is False


def test_syntax_error_and_empty_tree_fail(tmp_path):
    assert validate.syntax_check(tmp_path)
    root = tree(tmp_path)
    (root / "src/edge_lab/cli.py").write_text("if :\n")
    assert validate.run_checks(root, "quick", [], "HEAD")["status"] == "FAILED"


@pytest.mark.parametrize("target", ["tests/missing.py", "../outside.py", "--collect-only", "src/edge_lab/cli.py"])
def test_targeted_rejects_invalid_scope(tmp_path, target):
    assert validate.run_checks(tree(tmp_path), "targeted", [target], "HEAD")["status"] == "FAILED"


def test_targeted_requires_explicit_scope(tmp_path):
    report = validate.run_checks(tree(tmp_path), "targeted", [], "HEAD")
    assert report["status"] == "FAILED"


def test_full_uses_same_interpreter_and_never_narrows(tmp_path):
    plan = validate.commands("full", tree(tmp_path), [], "origin/main")
    assert [name for name, _ in plan] == ["comparison_base", "package_identity", "dependencies", "full_tests", "experiment_registry", "frozen_experiments"]
    assert all(argv[0] == sys.executable for name, argv in plan if name != "comparison_base")
    assert plan[3][1] == [sys.executable, "-m", "pytest"]
    with pytest.raises(ValueError):
        validate.commands("full", tmp_path, ["tests/test_ok.py"], "HEAD")


def test_dependency_failure_is_not_ignored(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        code = 1 if "pip" in argv else 0
        return subprocess.CompletedProcess(argv, code, "", "dependency conflict" if code else "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "origin/main")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["name"] == "dependencies"
    assert len(calls) == 3


def test_unavailable_base_cannot_skip_freeze_check_and_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(validate.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 128, "", "missing base"))
    report = validate.run_checks(tree(tmp_path), "full", [], "origin/main")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["name"] == "comparison_base"


def test_no_tests_collected_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(validate.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 5, "no tests ran", ""))
    report = validate.run_checks(tree(tmp_path), "targeted", ["tests/test_ok.py"], "HEAD")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["exit_code"] == 5


def test_timeout_fails_instead_of_printing_success(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)
    monkeypatch.setattr(validate.subprocess, "run", run)
    assert validate.run_checks(tree(tmp_path), "targeted", ["tests/test_ok.py"], "HEAD")["status"] == "FAILED"


def test_full_runs_all_steps_when_they_succeed(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["check"] is False and kwargs["timeout"] > 0
        return subprocess.CompletedProcess(argv, 0, "passed", "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "REQUESTED_CHECKS_PASSED"
    assert len(calls) == 6
    assert not report["ci_verified"]


def test_wrong_checkout_package_fails_before_tests(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        code = 1 if "-c" in argv else 0
        return subprocess.CompletedProcess(argv, code, "", "wrong checkout" if code else "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["name"] == "package_identity"
