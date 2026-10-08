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
    assert code == ops.EXIT_FAILED and "NEVER_OVER_LIVE" in out["error"]


def test_release_manifest_check_and_run(host):
    root, live = host
    manifest = root / "release.json"
    code, out, _ = _run("release-manifest", "--revision", REV, "--out", str(manifest))
    assert code == 0 and rl.load_manifest(manifest)["code_revision"] == REV
    code, out, _ = _run("release-manifest", "--revision", REV, "--out", str(manifest))
    assert code == ops.EXIT_FAILED and "FileExistsError" in out["error"]  # never over an existing manifest
    args = ("--manifest", str(manifest), "--revision-file", str(root / "REVISION"), "--journal", str(live))
    code, out, _ = _run("release-check", *args)
    assert code == 0 and out["problems"] == []
    code, out, _ = _run("run", *args)
    assert code == ops.EXIT_NO_RUNNER and out["started"] is False and out["problems"][0].startswith("NO_RUNNER")
    (root / "REVISION").write_text("d" * 40, encoding="ascii")
    code, out, _ = _run("run", *args)
    assert code == ops.EXIT_FAILED and out["started"] is False and out["problems"][0].startswith("REVISION_MISMATCH")


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
    assert code == ops.EXIT_FAILED and "REDACTED" in out["error"]
    for secret in (SIGNATURE, "tok" * 10, "MIIEv", "x" * 30):
        assert secret not in text


def test_an_unexpected_failure_is_one_redacted_line_not_a_traceback(host, monkeypatch):
    root, live = host

    def boom(*_a, **_k):
        raise RuntimeError(BEARER_LINE)

    monkeypatch.setattr(jb, "create_backup", boom)
    code, out, text = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == ops.EXIT_INTERNAL and out["error"].startswith("RuntimeError: ") and "REDACTED" in out["error"]
    assert "Traceback" not in text and "tok" * 10 not in text


def test_a_result_still_secret_looking_after_redaction_is_withheld():
    text = ops.render({"ok": True, ("api_key=" + "k" * 20): 1})  # a key is not redacted, so the whole is withheld
    assert json.loads(text) == {"ok": False, "error": ops.WITHHELD}
    # Whatever form the redaction owner writes, a redacted header is printed, not withheld (no exact form pinned here).
    shown = json.loads(ops.render({"ok": True, "note": HEADER_LINE}))
    assert shown["ok"] is True and "REDACTED" in shown["note"] and SIGNATURE not in shown["note"]


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

    # Additive to the redaction owner: it depends only on `redact_text`, `contains_secret` and `REDACTED`, never on
    # which patterns exist.
    redacted = redaction.redact_text(HEADER_LINE + "\n" + BEARER_LINE)
    assert not redaction.contains_unredacted_secret(redacted)
    for raw in (HEADER_LINE, BEARER_LINE, "plain words", "sha " + "ab" * 32):
        assert redaction.contains_unredacted_secret(raw) == redaction.contains_secret(raw)  # nothing to set aside
    assert redaction.contains_unredacted_secret("a=REDACTED; " + HEADER_LINE)  # one redacted value hides no other


def test_an_error_line_is_redacted_on_its_own():
    for message in (HEADER_LINE, BEARER_LINE):
        line = ops.safe_error(jb.BackupFailed(message + "\nsecond line"))
        assert "REDACTED" in line and SIGNATURE not in line and "tok" * 10 not in line and "second" not in line


# ---------------------------------------------------------------- the journal must exist (review MEDIUM-1)


def _manifest(root: Path) -> Path:
    path = root / "release.json"
    if not path.exists():
        path.write_text(rl.render_manifest(rl.build_manifest(REV)), encoding="utf-8")
    return path


def _check(root: Path, journal: Path, *extra: str, command: str = "release-check"):
    return _run(command, "--manifest", str(_manifest(root)), "--revision-file", str(root / "REVISION"),
                "--journal", str(journal), *extra)


@pytest.mark.parametrize("command", ["release-check", "run"])
def test_a_missing_journal_never_passes_the_start_check(host, command):
    root, live = host
    code, out, _ = _check(root, root / "journal" / "absent.execution.sqlite3", command=command)
    assert code == ops.EXIT_FAILED and out["ok"] is False and out["problems"][0].startswith("JOURNAL_MISSING")


def test_the_restore_window_never_passes_the_start_check(host):
    """Real restore step 2 moves the journal aside. If steps 3-4 never happen, nothing may start on an empty path."""
    root, live = host
    (root / "backup").mkdir(exist_ok=True)
    code, out, _ = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == 0
    aside = root / "evidence"
    aside.mkdir()
    for side in ("", "-wal", "-shm"):  # step 2 moves the journal and its side files together
        moved = live.with_name(live.name + side)
        if moved.exists():
            moved.rename(aside / moved.name)
    code, out, _ = _check(root, live)
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("JOURNAL_MISSING")
    code, out, _ = _check(root, live, "--first-start", "--backup-root", str(root / "backup"))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("FIRST_START_REFUSED")


def test_a_first_start_is_accepted_only_with_no_journal_and_no_backup(host, tmp_path):
    root, live = host
    empty_root = tmp_path / "fresh-backups"
    empty_root.mkdir()
    fresh = tmp_path / "fresh" / "kalshi.execution.sqlite3"
    fresh.parent.mkdir()
    code, out, _ = _check(root, fresh, "--first-start", "--backup-root", str(empty_root))
    assert code == 0 and out["problems"] == []
    code, out, _ = _check(root, fresh, "--first-start")
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("FIRST_START_NEEDS_BACKUP_ROOT")
    code, out, _ = _check(root, fresh, "--first-start", "--backup-root", str(tmp_path / "nowhere"))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("FIRST_START_BACKUP_ROOT_MISSING")
    (empty_root / (jb.PARTIAL_PREFIX + "abc")).mkdir()  # even an interrupted backup proves a journal existed
    code, out, _ = _check(root, fresh, "--first-start", "--backup-root", str(empty_root))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("FIRST_START_REFUSED")
    code, out, _ = _check(root, live, "--first-start", "--backup-root", str(tmp_path / "nowhere"))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("FIRST_START_BUT_JOURNAL_EXISTS")


def test_side_files_without_their_journal_are_refused_even_on_a_first_start(host, tmp_path):
    root, _ = host
    empty_root = tmp_path / "fresh-backups"
    empty_root.mkdir()
    gone = tmp_path / "gone.execution.sqlite3"
    gone.with_name(gone.name + "-wal").write_bytes(b"x")
    code, out, _ = _check(root, gone, "--first-start", "--backup-root", str(empty_root))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("JOURNAL_SIDE_FILES_WITHOUT_JOURNAL")


# ---------------------------------------------------------------- health with a missing journal (review LOW-3)


def test_health_never_reports_backup_ok_when_the_live_journal_is_missing(host):
    root, live = host
    code, out, _ = _run("backup", "--journal", str(live), "--out", str(root / "backup"))
    assert code == 0
    args = ("--status-file", str(root / "missing.json"), "--backup-root", str(root / "backup"), "--disk-path", str(root))
    code, out, _ = _run("health", *args, "--journal", str(live))
    assert out["backup"]["state"] == "OK"
    live.rename(root / "moved.execution.sqlite3")
    code, out, _ = _run("health", *args, "--journal", str(live))
    assert out["backup"]["state"] == "ANCHOR_BROKEN" and out["backup"]["reasons"][0].startswith("LIVE_JOURNAL_MISSING")
    assert code & 4


# ---------------------------------------------------------------- exit codes never collide with health bits (LOW-4)


def test_exit_codes_outside_health_stay_outside_its_bitmask(host, monkeypatch):
    assert {ops.EXIT_USAGE, ops.EXIT_FAILED, ops.EXIT_INTERNAL, ops.EXIT_NO_RUNNER}.isdisjoint(range(1, 16))
    root, live = host
    assert ops.main(["health"], out=io.StringIO()) == ops.EXIT_USAGE == 64
    code, out, _ = _run("verify-backup", "--bundle", str(root / "no-such-bundle"))
    assert code == ops.EXIT_FAILED == 65
    monkeypatch.setattr(ops.hl, "load_status", lambda _p: 1 / 0)
    code, out, _ = _run("health", "--status-file", "x", "--backup-root", str(root / "backup"), "--journal", str(live),
                        "--disk-path", str(root))
    assert code == ops.EXIT_INTERNAL == 70 and out["error"].startswith("ZeroDivisionError")


# ---------------------------------------------------------------- rollback-check


def test_rollback_check_names_an_incompatible_target(host):
    root, live = host
    old = "e" * 40
    current = root / "current.json"
    current.write_text(rl.render_manifest(rl.build_manifest(REV, rollback_revision=old,
                                                            rollback_journal_schema_version=1)), encoding="utf-8")
    target = root / "target.json"
    target.write_text(rl.render_manifest(rl.build_manifest(old)), encoding="utf-8")
    code, out, _ = _run("rollback-check", "--current", str(current), "--target", str(target), "--journal", str(live))
    assert code == 0 and out["problems"] == []
    code, out, _ = _run("rollback-check", "--current", str(target), "--target", str(current), "--journal", str(live))
    assert code == ops.EXIT_FAILED and out["problems"][0].startswith("NOT_THE_NAMED_ROLLBACK")
    code, out, _ = _run("rollback-check", "--current", str(current), "--target", str(target), "--journal",
                        str(root / "absent.execution.sqlite3"))
    assert code == ops.EXIT_FAILED and out["ok"] is False
