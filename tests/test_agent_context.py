from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    # scripts/ has no __init__.py (it is not a package), so import it by file
    # location instead of `from scripts import ...` — the convention already
    # used by tests/test_gate3_reproducible.py.
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context = _load("agent_context")

# Local, hermetic git identity/config for throwaway test repos: never touch the
# developer's real gpg signing, commit hooks, or global user identity.
_GIT_TEST_CONFIG = [
    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
    "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
]


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in context.DOCUMENTS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("canonical instructions\n", encoding="utf-8")
    subprocess.run(["git", *_GIT_TEST_CONFIG, "add", "."], cwd=root, check=True)
    subprocess.run(["git", *_GIT_TEST_CONFIG, "commit", "-qm", "baseline"], cwd=root, check=True)
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
    (root / "AI_INSTRUCTIONS.md").write_text("new instructions\n", encoding="utf-8")
    after = context.build_context(root)
    assert before["repo_head"] == after["repo_head"]
    assert after["dirty"] is True
    assert before["instruction_fingerprints"] != after["instruction_fingerprints"]
    assert after["local_base_sha"] is None


def test_fingerprint_is_line_ending_independent(tmp_path):
    # A Windows checkout with core.autocrlf=true must fingerprint the same
    # commit identically to a Linux checkout of the same content.
    root = make_repo(tmp_path)
    lf = context.build_context(root)
    (root / "AI_INSTRUCTIONS.md").write_bytes(b"canonical instructions\r\n")
    crlf = context.build_context(root)
    assert lf["instruction_fingerprints"]["AI_INSTRUCTIONS.md"]["sha256"] == \
        crlf["instruction_fingerprints"]["AI_INSTRUCTIONS.md"]["sha256"]
    # The reported byte count still reflects what is actually on disk.
    assert crlf["instruction_fingerprints"]["AI_INSTRUCTIONS.md"]["bytes"] == len(b"canonical instructions\r\n")


def test_adapter_files_are_part_of_the_instruction_system(tmp_path):
    root = make_repo(tmp_path)
    assert "AGENTS.md" in context.DOCUMENTS
    assert "CLAUDE.md" in context.DOCUMENTS


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


def _is_git_lock(rel):
    return rel.parts[0] == ".git" and rel.name.endswith(".lock")


def test_context_does_not_write_files_or_fetch(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    # Git lock files under .git/ are excluded: background maintenance may create them at any time.
    # Everything else under .git/ (new refs, FETCH_HEAD, objects) is still compared.
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*") if not _is_git_lock(p.relative_to(root)))
    original = subprocess.run
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert not {"fetch", "pull", "push", "reset", "checkout"}.intersection(argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(context.subprocess, "run", run)
    context.build_context(root)
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*") if not _is_git_lock(p.relative_to(root)))
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
