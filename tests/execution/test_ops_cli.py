"""The operator commands (`python -m edge_lab.execution.ops`, #160 package O, ADR 0048): results, exit codes and
sanitized output. FIXTURE only, offline; every path is under pytest's tmp_path."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import journal_backup as jb
from edge_lab.execution import ops
from edge_lab.execution import release as rl

REV = "c" * 40
# Credential-shaped samples, assembled at run time so no literal credential sits in the repository.
SIGNATURE = "c2lnbmF0dXJl" * 4
HEADER_LINE = "KALSHI-ACCESS-SIGNATURE: " + SIGNATURE
BEARER_LINE = "Authorization: Bearer " + "tok" * 10
PEM_LINE = "-----BEGIN " + "PRIVATE KEY-----"


def _run(*argv: str) -> tuple[int, dict, str]:
    out = io.StringIO()
    code = ops.main(list(argv), out=out)
    text = out.getvalue()
    assert text.count("\n") == 1, text  # one JSON line, never a traceback
    return code, json.loads(text), text


@pytest.fixture
def host(tmp_path: Path):
    (tmp_path / "journal").mkdir()
    (tmp_path / "backup").mkdir()
    (tmp_path / "drill").mkdir()
    live = tmp_path / "journal" / "kalshi.execution.sqlite3"
    journal, token = f.ready(live)
    f.prepare(journal, f.entry(), token)
    journal.close()
    (tmp_path / "REVISION").write_text(REV + "\n", encoding="ascii")
    return tmp_path, live


def test_backup_verify_and_drill_through_the_commands(host):
    root, live = host
    code, out, _ = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == 0 and out["ok"] and out["in_flight_attempts"] == 1
    bundle = root / "backup" / out["bundle"]
    code, out, _ = _run("verify-backup", "--bundle", str(bundle))
    assert code == 0 and out["verified"] is True
    code, out, _ = _run("restore-drill", "--bundle", str(bundle), "--drill-dir", str(root / "drill"), "--live", str(live))
    assert code == 0 and out["removed_after_drill"] is True and list((root / "drill").iterdir()) == []
    code, out, _ = _run("restore", "--bundle", str(bundle), "--target", str(live), "--live", str(live))
    assert code == 1 and "NEVER_OVER_LIVE" in out["error"]


def test_release_manifest_check_and_run(host):
    root, live = host
    manifest = root / "release.json"
    code, out, _ = _run("release-manifest", "--revision", REV, "--out", str(manifest))
    assert code == 0 and rl.load_manifest(manifest)["code_revision"] == REV
    code, out, _ = _run("release-manifest", "--revision", REV, "--out", str(manifest))
    assert code == 1 and "FileExistsError" in out["error"]  # never over an existing manifest
    args = ("--manifest", str(manifest), "--revision-file", str(root / "REVISION"), "--journal", str(live))
    code, out, _ = _run("release-check", *args)
    assert code == 0 and out["problems"] == []
    code, out, _ = _run("run", *args)
    assert code == ops.EXIT_NO_RUNNER and out["started"] is False and out["problems"][0].startswith("NO_RUNNER")
    (root / "REVISION").write_text("d" * 40, encoding="ascii")
    code, out, _ = _run("run", *args)
    assert code == 1 and out["started"] is False and out["problems"][0].startswith("REVISION_MISMATCH")


def test_health_reports_each_verdict_and_sets_bits(host):
    root, live = host
    code, out, _ = _run("health", "--status-file", str(root / "missing.json"), "--backup-root", str(root / "backup"),
                        "--journal", str(live), "--disk-path", str(root))
    assert out["liveness"]["state"] == "UNKNOWN" and out["reconciliation"]["state"] == "UNKNOWN"
    assert out["backup"]["state"] == "MISSING" and out["status_problem"] == "NO_STATUS_FILE"
    assert code == out["exit_code"] and code & 1 and code & 2 and code & 4


@pytest.mark.parametrize("message", [HEADER_LINE, BEARER_LINE, PEM_LINE + "\nMIIEv", "token=" + "x" * 30])
def test_an_error_carrying_a_header_or_secret_is_printed_redacted(host, monkeypatch, message):
    root, live = host

    def leaky(*_a, **_k):
        raise jb.BackupFailed("copy failed: " + message)

    monkeypatch.setattr(jb, "create_backup", leaky)
    code, out, text = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == 1 and "REDACTED" in out["error"]
    for secret in (SIGNATURE, "tok" * 10, "MIIEv", "x" * 30):
        assert secret not in text


def test_an_unexpected_failure_is_one_redacted_line_not_a_traceback(host, monkeypatch):
    root, live = host

    def boom(*_a, **_k):
        raise RuntimeError(BEARER_LINE)

    monkeypatch.setattr(jb, "create_backup", boom)
    code, out, text = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == ops.EXIT_INTERNAL and out["error"].startswith("RuntimeError: Authorization=REDACTED")
    assert "Traceback" not in text and "tok" * 10 not in text


def test_a_result_still_secret_looking_after_redaction_is_withheld():
    text = ops.render({"ok": True, ("api_key=" + "k" * 20): 1})  # a key is not redacted, so the whole is withheld
    assert json.loads(text) == {"ok": False, "error": ops.WITHHELD}
    assert ops.render({"ok": True, "note": HEADER_LINE}) == json.dumps(
        {"note": "KALSHI-ACCESS-SIGNATURE=REDACTED", "ok": True}, sort_keys=True, separators=(",", ":"))


def test_usage_errors_exit_2_and_print_no_result(capsys):
    assert ops.main(["no-such-command"], out=io.StringIO()) == ops.EXIT_USAGE
    assert ops.main(["backup"], out=io.StringIO()) == ops.EXIT_USAGE


def test_the_ops_module_runs_without_cryptography_or_network_modules():
    """The VPS venv is stdlib-only (EXECUTION_PLAN): the operator commands must import without the signer."""
    probe = ("import sys; import edge_lab.execution.ops; "
             "bad = sorted(m for m in ('cryptography', 'edge_lab.execution.signer', 'edge_lab.execution.transport', "
             "'socket', 'ssl', 'http.client', 'urllib.request') if m in sys.modules); print(bad)")
    src = Path(ops.__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=str(src), timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_contains_unredacted_secret_sets_aside_only_what_redaction_replaced():
    from edge_lab import redaction

    redacted = redaction.redact_text(HEADER_LINE + "\n" + BEARER_LINE)
    assert redaction.contains_secret(redacted) and not redaction.contains_unredacted_secret(redacted)
    assert redaction.contains_unredacted_secret(HEADER_LINE)
    assert redaction.contains_unredacted_secret("a=REDACTED; " + HEADER_LINE)  # one redacted value hides no other
    assert redaction.contains_unredacted_secret("Authorization=REDACTED" + SIGNATURE)  # not a whole redacted value


def test_an_error_line_is_redacted_on_its_own():
    for message in (HEADER_LINE, BEARER_LINE):
        line = ops.safe_error(jb.BackupFailed(message + "\nsecond line"))
        assert "REDACTED" in line and SIGNATURE not in line and "tok" * 10 not in line and "second" not in line
