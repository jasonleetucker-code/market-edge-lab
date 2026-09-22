#!/usr/bin/env python3
"""Small cross-platform validation tiers, adapted from Brisket's L0/L1/L2 idea.

Quick = Python syntax. Targeted = syntax + explicitly named tests. Full = syntax,
dependency check, every test, registry and frozen-spec check. None deploy or
fetch anything. Full CI is still required; a local result is not CI evidence.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def syntax_check(root: Path) -> list[str]:
    errors = []
    paths = sorted(p for folder in ("src", "scripts", "tests") for p in (root / folder).rglob("*.py"))
    if not paths:
        return ["No Python files found; refusing an empty success"]
    for path in paths:
        try:
            if path.is_symlink():
                raise ValueError("symlinked source is not supported")
            with tokenize.open(path) as stream:
                ast.parse(stream.read(), filename=str(path))
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    return errors


def test_targets(root: Path, values: list[str]) -> list[str]:
    if not values:
        raise ValueError("targeted mode requires --test; use full for the whole suite")
    tests = (root / "tests").resolve()
    targets = []
    for value in values:
        # Accept pytest node IDs but never arbitrary options or external paths.
        file_name = value.split("::", 1)[0]
        path = (root / file_name).resolve()
        if path != tests and tests not in path.parents:
            raise ValueError(f"test target must be inside tests/: {value}")
        if not path.exists():
            raise ValueError(f"test target does not exist: {value}")
        targets.append(value)
    return targets


_PACKAGE_IDENTITY_CHECK = """
import sys
from pathlib import Path
import edge_lab
actual = Path(edge_lab.__file__).resolve()
expected = Path("src/edge_lab/__init__.py").resolve()
if actual != expected:
    print(f"edge_lab is not installed from this checkout: {actual} != {expected}", file=sys.stderr)
    sys.exit(1)
"""

# A bare `assert` in the -c string above would previously be stripped whenever
# the interpreter runs with -O/PYTHONOPTIMIZE, silently turning this check into
# a no-op that always reports green. The explicit if/sys.exit above cannot be
# optimized away.

_WORKING_TREE_CLEAN_CHECK = ["git", "status", "--porcelain=v1", "--untracked-files=normal"]


def commands(level: str, root: Path, targets: list[str], base: str) -> list[tuple[str, list[str]]]:
    python = sys.executable
    if level == "quick":
        if targets:
            raise ValueError("--test is only valid with targeted mode")
        return []
    if level == "targeted":
        return [("targeted_tests", [python, "-m", "pytest", *test_targets(root, targets)])]
    if level != "full":
        raise ValueError(f"unknown validation level: {level}")
    if targets:
        raise ValueError("full mode never narrows the test suite")
    for relative in ("tests", "experiments", "src/edge_lab/cli.py"):
        if not (root / relative).exists():
            raise ValueError(f"required path missing: {relative}")
    if not base or base.startswith("-"):
        raise ValueError("full mode needs a valid comparison base")
    return [
        ("comparison_base", ["git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"]),
        # Dirty means the tree has uncommitted or untracked changes: "full" is
        # meant to stand in for what CI would see on a clean checkout, so it
        # must not report green over local changes it never actually validated.
        ("working_tree_clean", list(_WORKING_TREE_CLEAN_CHECK)),
        ("package_identity", [python, "-c", _PACKAGE_IDENTITY_CHECK]),
        ("dependencies", [python, "-m", "pip", "check"]),
        ("full_tests", [python, "-m", "pytest"]),
        ("experiment_registry", [python, "-m", "edge_lab.cli", "experiments", "validate"]),
        ("frozen_experiments", [python, "-m", "edge_lab.cli", "experiments", "check-frozen", "--base", base]),
    ]


def run_checks(root: Path, level: str, targets: list[str], base: str, timeout: float = 600) -> dict:
    report = {"level": level, "status": "FAILED", "checks": [], "ci_verified": False}
    try:
        plan = commands(level, root, targets, base)
    except ValueError as exc:
        report["error"] = str(exc)
        return report
    errors = syntax_check(root)
    report["checks"].append({"name": "python_syntax", "exit_code": 1 if errors else 0, "errors": errors})
    if errors:
        return report
    for name, argv in plan:
        started = time.monotonic()
        try:
            done = subprocess.run(
                argv, cwd=root, capture_output=True, timeout=timeout, check=False,
                encoding="utf-8", errors="replace",
            )
            exit_code = done.returncode
            entry = {"name": name, "exit_code": exit_code, "seconds": round(time.monotonic() - started, 3)}
            if name == "working_tree_clean" and exit_code == 0:
                # `git status` itself exits 0 whether the tree is dirty or not;
                # dirtiness shows up in stdout, so interpret it explicitly rather
                # than trusting the exit code alone.
                dirty_paths = done.stdout.splitlines()
                if dirty_paths:
                    entry["exit_code"] = 1
                    entry["dirty_paths"] = dirty_paths[:40]
            if entry["exit_code"]:
                entry["output_tail"] = (done.stdout + done.stderr)[-6000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            entry = {"name": name, "exit_code": 1, "error": str(exc)}
        except UnicodeError as exc:
            # A check whose output cannot be decoded must fail, never crash
            # silently past the report or (worse) be treated as green.
            entry = {"name": name, "exit_code": 1, "error": f"undecodable subprocess output: {exc}"}
        report["checks"].append(entry)
        if entry["exit_code"]:
            return report
    report["status"] = "REQUESTED_CHECKS_PASSED"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", choices=("quick", "targeted", "full"))
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    report = run_checks(ROOT, args.level, args.test, args.base)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "REQUESTED_CHECKS_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
