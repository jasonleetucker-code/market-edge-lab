from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    # scripts/ has no __init__.py (it is not a package), so import it by file
    # location instead of `from scripts import ...` — the convention already
    # used by tests/test_gate3_reproducible.py.
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = _load("validate")


def tree(tmp_path):
    for folder in ("src/edge_lab", "scripts", "tests", "experiments"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "src/edge_lab/cli.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
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
    assert [name for name, _ in plan] == [
        "comparison_base", "working_tree_clean", "package_identity",
        "dependencies", "full_tests", "experiment_registry", "frozen_experiments",
    ]
    # comparison_base and working_tree_clean shell out to git; everything else
    # must run under the same interpreter that is running validate.py itself.
    assert all(argv[0] == sys.executable for name, argv in plan if name not in ("comparison_base", "working_tree_clean"))
    assert plan[1][1] == validate._WORKING_TREE_CLEAN_CHECK
    assert plan[4][1] == [sys.executable, "-m", "pytest"]
    with pytest.raises(ValueError):
        validate.commands("full", tmp_path, ["tests/test_ok.py"], "HEAD")


def test_package_identity_check_has_no_bare_assert(tmp_path):
    # A bare `assert` inside `python -c "..."` is stripped under -O/PYTHONOPTIMIZE,
    # silently turning the check into a no-op that always reports green.
    assert "assert" not in validate._PACKAGE_IDENTITY_CHECK
    assert "sys.exit(1)" in validate._PACKAGE_IDENTITY_CHECK


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
    assert len(calls) == 4


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
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
        # git status reporting nothing staged/untracked is what "clean" looks like.
        stdout = "" if argv == validate._WORKING_TREE_CLEAN_CHECK else "passed"
        return subprocess.CompletedProcess(argv, 0, stdout, "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "REQUESTED_CHECKS_PASSED"
    assert len(calls) == 7
    assert not report["ci_verified"]


def test_dirty_working_tree_fails_full_even_when_every_other_check_passes(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        if argv == validate._WORKING_TREE_CLEAN_CHECK:
            return subprocess.CompletedProcess(argv, 0, " M src/edge_lab/backup.py\n?? scratch.txt\n", "")
        return subprocess.CompletedProcess(argv, 0, "passed", "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "FAILED"
    dirty_check = report["checks"][[c["name"] for c in report["checks"]].index("working_tree_clean")]
    assert dirty_check["exit_code"] == 1
    assert dirty_check["dirty_paths"] == [" M src/edge_lab/backup.py", "?? scratch.txt"]


def test_working_tree_check_failure_stops_before_running_tests(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv == validate._WORKING_TREE_CLEAN_CHECK:
            return subprocess.CompletedProcess(argv, 0, "?? untracked\n", "")
        return subprocess.CompletedProcess(argv, 0, "passed", "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "FAILED"
    # comparison_base, then working_tree_clean — never reaches full_tests.
    assert len(calls) == 2
    assert [c["name"] for c in report["checks"]] == ["python_syntax", "comparison_base", "working_tree_clean"]


def test_undecodable_subprocess_output_fails_instead_of_crashing(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "bad byte")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["exit_code"] == 1
    assert "error" in report["checks"][-1]


def test_wrong_checkout_package_fails_before_tests(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        code = 1 if "-c" in argv else 0
        return subprocess.CompletedProcess(argv, code, "", "wrong checkout" if code else "")
    monkeypatch.setattr(validate.subprocess, "run", run)
    report = validate.run_checks(tree(tmp_path), "full", [], "HEAD")
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["name"] == "package_identity"
