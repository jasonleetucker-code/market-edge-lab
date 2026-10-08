"""The repeatable secret scan (`scripts/secret_scan.py`, #160 package O, ADR 0047).

Every credential-shaped sample here is assembled at run time, so this file holds no literal credential and the scan of
this repository's own history stays clean. Temporary repositories live under pytest's tmp_path; nothing is pushed."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "secret_scan.py"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = _module("secret_scan_under_test", SCRIPT)

SAMPLES = {
    "private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "AWS access key": "AKIA" + "Q" * 16,
    "GitHub token": "ghp_" + "a1" * 18,
    "OpenAI/Anthropic-style key": "sk-" + "ant-" + "b2" * 14,
    "Slack token": "xoxb-" + "1234567890-abc",
    "assigned secret": "password = '" + "hunter2hunter2" + "'",
    "venue auth header value": "KALSHI-ACCESS-SIGNATURE: " + "c2ln" * 6,
    "bearer credential": "Authorization: Bearer " + "abc.def-" * 4,
    "credentials in a URL": "https://" + "user" + ":" + "s3cr3tpw" + "@example.com/x",
    "API key query value": "https://api.example.com/v4?apiKey=" + "f00d" * 8,
    "ntfy topic URL": "https://ntfy.sh/" + "private-topic-" + "x9" * 4,
}
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


def test_every_pattern_has_a_sample_that_it_and_only_it_is_tested_with():
    assert set(SAMPLES) == set(scan.PATTERNS)
    for label, sample in SAMPLES.items():
        assert [f["pattern"] for f in scan.scan_text(sample, {})] == [label], label


@pytest.mark.parametrize("benign", [
    "the KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP and KALSHI-ACCESS-SIGNATURE headers",
    "apiKey=REDACTED", "https://ntfy.sh/<topic>", "Authorization: Bearer REDACTED", "sha256 " + "ab" * 32,
    "password = os.environ['X']",
])
def test_names_placeholders_and_hashes_are_not_findings(benign):
    assert list(scan.scan_text(benign, {})) == []


def test_the_scan_covers_every_pattern_of_the_tracked_file_invariant():
    invariant = _module("no_secrets_invariant", ROOT / "tests" / "invariants" / "test_no_secrets.py")
    for label, pattern in invariant.PATTERNS.items():
        assert scan.PATTERNS[label].pattern == pattern.pattern and scan.PATTERNS[label].flags == pattern.flags, label


def test_a_finding_never_carries_the_value():
    sample = SAMPLES["venue auth header value"]
    (finding,) = list(scan.scan_text("x\n" + sample, {"path": "a.log"}))
    assert finding == {"path": "a.log", "line": 2, "pattern": "venue auth header value",
                       "fingerprint": scan.fingerprint(sample)}
    assert "c2ln" not in json.dumps(finding)


def test_every_allowlisted_fingerprint_has_a_reason():
    for fp, reason in scan.ALLOWED_FINGERPRINTS.items():
        assert len(fp) == scan.FINGERPRINT_CHARS and int(fp, 16) >= 0 and len(reason) > 20


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "t"),
                 ("config", "commit.gpgsign", "false")):
        subprocess.run([GIT, "-C", str(repo), *args], check=True)
    return repo


def _commit(repo: Path, files: dict[str, bytes], message: str) -> None:
    for name, data in files.items():
        path = repo / name
        if data is None:
            subprocess.run([GIT, "-C", str(repo), "rm", "-q", name], check=True)
            continue
        path.write_bytes(data)
        subprocess.run([GIT, "-C", str(repo), "add", name], check=True)
    subprocess.run([GIT, "-C", str(repo), "commit", "-q", "-m", message], check=True)


@needs_git
def test_history_finds_a_secret_the_tree_no_longer_has_and_never_prints_it(tmp_path, capsys):
    repo = _repo(tmp_path)
    token = SAMPLES["GitHub token"]
    _commit(repo, {"config.txt": f"token: {token}\n".encode()}, "add config")
    _commit(repo, {"config.txt": None}, "remove config")
    _commit(repo, {"notes.txt": b"hello\n"}, "note with " + SAMPLES["AWS access key"])
    tree_code, tree = scan.run(["--tree", "--repo", str(repo)])
    assert tree_code == 0 and tree["clean"] is True
    code = scan.main(["--history", "--repo", str(repo)])
    out = capsys.readouterr().out
    result = json.loads(out)
    assert code == 1 and result["clean"] is False and result["commits"] == 3
    found = {(f["pattern"], f.get("path") or "message") for f in result["findings"]}
    assert found == {("GitHub token", "config.txt"), ("AWS access key", "message")}
    assert token not in out and SAMPLES["AWS access key"] not in out


@needs_git
def test_binary_and_oversized_blobs_are_counted_not_silently_dropped(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo, {"blob.bin": b"\x00\x01" + SAMPLES["AWS access key"].encode(), "big.txt": b"a" * 2048,
                   "ok.txt": b"fine\n"}, "mixed")
    monkeypatch.setattr(scan, "MAX_BLOB_BYTES", 1024)
    code, result = scan.run(["--history", "--repo", str(repo)])
    assert code == 0 and result["skipped_binary"] == 1 and result["skipped_large"] == 1 and result["blobs_scanned"] == 1
    assert any("binary" in limitation for limitation in result["limitations"])


@needs_git
def test_an_allowlisted_fingerprint_is_reported_as_allowlisted_not_hidden(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    sample = SAMPLES["ntfy topic URL"]
    _commit(repo, {"t.py": f"TOPIC = '{sample}'\n".encode()}, "fixture topic")
    monkeypatch.setattr(scan, "ALLOWED_FINGERPRINTS", {scan.fingerprint(sample): "a synthetic topic for this test"})
    code, result = scan.run(["--history", "--repo", str(repo)])
    assert code == 0 and result["clean"] is True and result["allowlisted"] == 1


def test_artifacts_are_scanned_before_upload(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "junit.xml").write_text("<testcase><system-out>" + SAMPLES["bearer credential"] +
                                         "</system-out></testcase>", encoding="utf-8")
    (artifacts / "clean.log").write_text("all good\n", encoding="utf-8")
    code, result = scan.run(["--paths", str(artifacts)])
    assert code == 1 and [f["pattern"] for f in result["findings"]] == ["bearer credential"]
    assert result["files_scanned"] == 2


def test_a_scan_that_cannot_run_is_never_clean(tmp_path):
    code, result = scan.run(["--paths", str(tmp_path / "missing")])
    assert code == 2 and result["clean"] is False
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    if GIT is not None:
        code, result = scan.run(["--history", "--repo", str(not_a_repo)])
        assert code == 2 and result["clean"] is False
    code, result = scan.run(["--history", "--rev=--output=x", "--repo", str(ROOT)])
    assert code == 2


@needs_git
def test_this_repository_is_clean_in_its_tree_and_its_head_history():
    for argv in (["--tree"], ["--history", "--rev", "HEAD"]):
        code, result = scan.run([*argv, "--repo", str(ROOT)])
        assert code == 0, [f for f in result.get("findings", [])][:5] or result
        assert result["clean"] is True


def test_the_script_is_standard_library_only():
    done = subprocess.run([sys.executable, "-I", "-c",
                           f"import runpy, sys; runpy.run_path({str(SCRIPT)!r}, run_name='probe'); "
                           "print(sorted(m for m in sys.modules if m.split('.')[0] in ('edge_lab', 'requests')))"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "[]", done.stderr
