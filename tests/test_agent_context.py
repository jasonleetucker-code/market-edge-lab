from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import agent_context as context


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in context.DOCUMENTS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("canonical instructions\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], cwd=root, check=True)
    return root


def test_receipt_identifies_head_without_claiming_remote_or_model_read(tmp_path):
    root = make_repo(tmp_path)
    report = context.build_context(root, "HEAD")
    assert report["receipt_complete"] is True
    assert report["dirty"] is False
    assert report["local_base_sha"] == report["repo_head"]
    assert len(report["instruction_fingerprints"]) == len(context.DOCUMENTS)
    assert "NOT_CHECKED" in report["remote_state"]
    assert "not proof" in report["meaning"]
    assert report["package_from_this_checkout"] is False
    assert json.loads(json.dumps(report))["repo_head"] == report["repo_head"]


def test_working_document_fingerprint_changes_without_overwriting_head(tmp_path):
    root = make_repo(tmp_path)
    before = context.build_context(root)
    (root / "AI_INSTRUCTIONS.md").write_text("new instructions\n")
    after = context.build_context(root)
    assert before["repo_head"] == after["repo_head"]
    assert after["dirty"] is True
    assert before["instruction_fingerprints"] != after["instruction_fingerprints"]
    assert after["local_base_sha"] is None


def test_missing_repo_and_docs_do_not_look_verified(tmp_path):
    report = context.build_context(tmp_path)
    assert report["receipt_complete"] is False
    assert report["dirty"] is None
    assert report["repo_head"] is None
    assert report["missing_documents"]


def test_missing_document_fails_receipt(tmp_path):
    root = make_repo(tmp_path)
    (root / "HANDOFF.md").unlink()
    report = context.build_context(root)
    assert report["receipt_complete"] is False
    assert "HANDOFF.md" in report["missing_documents"]


def test_context_does_not_write_files_or_fetch(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    original = subprocess.run
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert not {"fetch", "pull", "push", "reset", "checkout"}.intersection(argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(context.subprocess, "run", run)
    context.build_context(root)
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    assert before == after
    assert calls


def test_status_failure_is_unknown_not_clean(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = context.git
    def git(root, *args):
        return None if args[0] == "status" else original(root, *args)
    monkeypatch.setattr(context, "git", git)
    report = context.build_context(root)
    assert report["dirty"] is None and not report["receipt_complete"]


def test_git_timeout_returns_unknown(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 10)
    monkeypatch.setattr(context.subprocess, "run", run)
    assert context.git(tmp_path, "rev-parse", "HEAD") is None
