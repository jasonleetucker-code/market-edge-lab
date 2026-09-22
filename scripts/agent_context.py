#!/usr/bin/env python3
"""Read-only filesystem context receipt; adapted from Brisket's session receipt.

No network, pulls, resets, model calls, or file writes. A fingerprint identifies
bytes, not proof that an agent read/understood them. See RELIABILITY_TOOLKIT.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "AI_INSTRUCTIONS.md", "docs/AGENT_OPERATING_SYSTEM.md",
    "docs/EXECUTION_PLAN.md", "HANDOFF.md", "docs/WORK_CLAIMS.md",
)


def git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args], cwd=root, capture_output=True, text=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            encoding="utf-8", errors="replace", timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else None


def build_context(root: Path, base: str = "origin/main") -> dict:
    root = root.resolve()
    top = git(root, "rev-parse", "--show-toplevel")
    is_repo = top is not None and Path(top).resolve() == root
    head = git(root, "rev-parse", "--verify", "HEAD") if is_repo else None
    base_sha = git(root, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}") if is_repo else None
    status = git(root, "status", "--porcelain=v1", "--untracked-files=normal") if is_repo else None
    status_lines = status.splitlines() if status else []
    fingerprints, missing = {}, []
    for rel in DOCUMENTS:
        path = root / rel
        try:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise OSError("not a regular document")
            body = path.read_bytes()
        except OSError:
            missing.append(rel)
            continue
        fingerprints[rel] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    try:
        spec = importlib.util.find_spec("edge_lab")
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
    except (ImportError, ValueError, OSError):
        origin = None
    expected = root / "src" / "edge_lab" / "__init__.py"
    return {
        "receipt_version": 1,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": head,
        "branch": git(root, "branch", "--show-current") if is_repo else None,
        "local_base_ref": base,
        "local_base_sha": base_sha,
        "remote_state": "NOT_CHECKED: inspect live PRs, branches and claims separately",
        "dirty": bool(status_lines) if status is not None else None,
        "change_summary": status_lines[:40],
        "change_summary_truncated": len(status_lines) > 40,
        "instruction_fingerprints": fingerprints,
        "missing_documents": missing,
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "sqlite_version": sqlite3.sqlite_version,
        "package_from_this_checkout": origin == expected,
        "receipt_complete": bool(is_repo and head and status is not None and not missing),
        "meaning": "Filesystem evidence only; not proof of instruction loading, compliance, or merge authority",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    report = build_context(ROOT, args.base)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["receipt_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
