"""Static checks of the VPS unit files: schedule, isolation, combined budget, both backups."""

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "vps" / "systemd"
INSTALL = (ROOT / "deploy" / "vps" / "install.sh").read_text()


def _parse(name):
    cp = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    text = (UNITS / name).read_text()
    # systemd allows repeated keys (ExecStart, OnCalendar); keep them all.
    values: dict[tuple[str, str], list[str]] = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault((section, key), []).append(value)
    return values


def _minutes_ny(calendar):
    m = re.fullmatch(r"\*-\*-\* (\d\d):(\d\d):(\d\d) America/New_York", calendar)
    assert m, f"timer must name America/New_York explicitly: {calendar}"
    return int(m.group(1)) * 60 + int(m.group(2))


def test_every_service_is_in_the_shared_slice_with_caps_and_hardening():
    for path in UNITS.glob("*.service"):
        u = _parse(path.name)
        assert u[("Service", "Slice")] == ["edgelab.slice"], path.name
        if path.name not in ("edgelab-alert@.service", "edgelab-dashboard.service"):
            assert u[("Service", "User")] == ["edgelab"] and u[("Service", "MemoryMax")] == ["256M"], path.name
            assert u[("Service", "ProtectSystem")] == ["strict"] and u[("Service", "NoNewPrivileges")] == ["yes"]
            if path.name == "edgelab-notify.service":  # the relay needs only the status directory
                assert u[("Service", "ReadWritePaths")] == ["/var/lib/market-edge-lab-status"]
                assert u[("Service", "InaccessiblePaths")] == ["/var/lib/market-edge-lab"]
            else:
                assert u[("Service", "ReadWritePaths")] == ["/var/lib/market-edge-lab /var/lib/market-edge-lab-status"]
    s = _parse("edgelab.slice")
    assert s[("Slice", "MemoryMax")] == ["384M"] and s[("Slice", "CPUQuota")] == ["25%"]


def test_dashboard_is_read_only_loopback_only_and_tailnet_host_pinned():
    u = _parse("edgelab-dashboard.service")
    assert u[("Service", "User")] == ["edgelab"] and u[("Service", "Slice")] == ["edgelab.slice"]
    assert u[("Service", "ProtectSystem")] == ["strict"] and u[("Service", "NoNewPrivileges")] == ["yes"]
    assert ("Service", "ReadWritePaths") not in u  # it writes nothing
    assert u[("Service", "IPAddressDeny")] == ["any"] and u[("Service", "IPAddressAllow")] == ["localhost"]
    assert u[("Service", "RestrictAddressFamilies")] == ["AF_INET AF_UNIX"]
    assert u[("Service", "MemoryMax")] == ["128M"]
    exec_start = u[("Service", "ExecStart")]
    assert len(exec_start) == 1
    args = exec_start[0].split()
    assert args[args.index("--host") + 1] == "127.0.0.1" and args[args.index("--port") + 1] == "8765"
    assert args[args.index("--tailscale-serve-host") + 1] == "${EDGE_LAB_TAILSCALE_SERVE_HOST}"
    assert "--allow-non-loopback" not in args and "--demo" not in args
    # The name comes from a required file: a missing file fails the unit rather than serving without it.
    assert u[("Service", "EnvironmentFile")] == ["/etc/market-edge-lab/dashboard.env"]
    assert "edgelab-dashboard" in INSTALL


def test_new_timers_avoid_the_capture_windows_and_use_new_york_time():
    for name in ("edgelab-shadow.timer", "edgelab-settlement.timer"):
        for cal in _parse(name)[("Timer", "OnCalendar")]:
            minute = _minutes_ny(cal)
            assert not (17 * 60 + 40 <= minute <= 18 * 60 + 35), f"{name} fires inside 17:40-18:35 ET"
    assert _minutes_ny(_parse("edgelab-shadow.timer")[("Timer", "OnCalendar")][0]) > 18 * 60 + 35


def test_shadow_bookkeeping_has_no_network_and_settlement_refresh_is_bounded():
    shadow = _parse("edgelab-shadow.service")
    assert shadow[("Service", "RestrictAddressFamilies")] == ["AF_UNIX"]
    assert shadow[("Service", "IPAddressDeny")] == ["any"]
    assert "--refresh-settlements" not in shadow[("Service", "ExecStart")][0]
    refresh = _parse("edgelab-settlement.service")[("Service", "ExecStart")][0]
    assert "--refresh-settlements" in refresh and "--max-events 10" in refresh and "--deadline-s 120" in refresh


def test_backup_covers_both_stores():
    text = (UNITS / "edgelab-backup.service").read_text()
    exec_line = text[text.index("ExecStart="):text.index("exit $$rc")]  # $$: systemd would expand $rc itself
    # One shell step runs both copies, so a failed evidence backup never skips the ledger one.
    assert exec_line.count("edge_lab.backup create") == 2 and exec_line.count("|| rc=1") == 2
    assert "--kind evidence" in exec_line and "--kind ledger" in exec_line
    assert "--if-exists" in exec_line and "--lock-file" in exec_line


def test_install_script_knows_every_timer_and_keeps_the_ledger_private():
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    timers = sorted(p.stem for p in UNITS.glob("*.timer"))
    assert sorted(units) == timers
    assert '"$DATA/ledger"' in INSTALL and "cannot list the shadow ledger" in INSTALL
    assert "edgelab.slice" in INSTALL


def test_readme_install_window_matches_the_capture_window():
    text = (ROOT / "deploy/vps/README.md").read_text()
    ends = re.findall(r"17:40 and (?:\*\*)?18:(\d\d)", text)
    assert ends, "README must state the install window (17:40 and 18:35 America/New_York)"
    assert all(int(end) >= 35 for end in ends), "README install window must cover 17:40-18:35 America/New_York"
    assert "America/New_York" in text and "edgelab-" in text
    runbook = (ROOT / "docs/deploy/DAILY_SHADOW_ACTIVATION.md").read_text()
    assert "17:40 and 18:35 America/New_York" in runbook, "runbook and README windows diverge"


# --------------------------------------------------------------------------- verify_production.sh

VERIFY = ROOT / "deploy" / "vps" / "verify_production.sh"
VERIFY_STATES = (
    "NY_TIME", "IN_CAPTURE_WINDOW", "RUNNING_UNITS", "DEPLOYED_SHA", "TIMERS", "UNIT_RESULTS", "SHADOW_TIMER",
    "SETTLEMENT_TIMER", "LATEST_JSON", "LATEST_JSON_AGE", "COLLECTOR_HEALTH", "VALID_DAY_OBSERVED", "SHADOW_DAILY",
    "LAST_FAILURE", "COLLECTOR_INSTALLED", "TIMERS_ENABLED", "PFM_CAPTURE_OBSERVED", "DECISION_CAPTURE_OBSERVED",
    "RECHECK_CAPTURE_OBSERVED", "DB_SIZES", "BACKUPS", "BACKUP_REPORTS_8D", "BACKUP_EVIDENCE_DB",
    "BACKUP_SHADOW_LEDGER", "RESTORE_EVIDENCE_DB", "RESTORE_SHADOW_LEDGER", "JOURNAL_WARNINGS_24H", "OOM_30D",
    "MEMORY", "DISK", "BRISKET_UNITS", "API_HEALTH", "CHASE_UPSIDE_HEALTH",
)
# The directive's post-deployment states (integration directive section 6), one line each.
DIRECTIVE_STATES = ("DEPLOYED_SHA", "COLLECTOR_HEALTH", "SHADOW_TIMER", "SETTLEMENT_TIMER", "BACKUP_EVIDENCE_DB",
                    "BACKUP_SHADOW_LEDGER", "RESTORE_EVIDENCE_DB", "RESTORE_SHADOW_LEDGER", "CHASE_UPSIDE_HEALTH")
SYSTEMCTL_VERBS = {"show", "is-enabled", "is-active", "list-units", "list-timers", "cat"}
CURL_LINE = "resp=$(curl -q --proto =https -sS -m 5 -w '\\n%{http_code}' https://chaseupside.com/api/health 2>&1)"
COMMAND_START = r"(^|[|;&(`]|\bthen\b|\bdo\b|\belse\b)\s*"
MUTATING = {
    "errexit": re.compile(r"\bset\s+-[a-z]*e|\bset\s+-o\s+errexit"),
    "privilege": re.compile(r"\bsudo\b|\bsu\s+-|\brunuser\b|\bdoas\b"),
    "file or attribute change": re.compile(
        COMMAND_START + r"(rm|mv|cp|chattr|chmod|chown|tee|touch|truncate|dd|ln|mkdir|install|shred|rsync|scp|"
        r"sqlite3|logger)\b"),
    "other programs": re.compile(
        COMMAND_START + r"(docker|service|kill|pkill|killall|wget|nc|ncat|ssh|apt|apt-get|dpkg|pip|pip3|xargs|find|"
        r"eval|exec|source|bash|sh|crontab|systemd-run)\b"),
    "find -delete": re.compile(r"(^|\s)-delete\b"),
    "request with a body or method": re.compile(
        r"\bcurl\b.*\s(-X|--request|-d|--data\S*|-F|--form|-T|--upload-file|-o|--output|-O|-K|--config)\b"),
    "in-place edit": re.compile(r"\bsed\s+(-[a-zA-Z]*i|--in-place)"),
    "journal maintenance": re.compile(r"\bjournalctl\b.*--(vacuum|rotate|flush|sync|relinquish)"),
    "lab command": re.compile(r"edge_lab\.|edge-lab\s"),
}
EMBEDDED_PYTHON_FORBIDDEN = {
    "write mode": re.compile(r"""open\([^)]*?,\s*(mode\s*=\s*)?["'][^"')]*[wax+][^"')]*["']\s*[,)]"""),
    "os module": re.compile(r"\bos\.|\bimport\s+os\b|\bfrom\s+os\b"),
    "subprocess": re.compile(r"subprocess"),
    "socket": re.compile(r"socket"),
    "urllib": re.compile(r"urllib|http\.client|requests"),
    "file removal": re.compile(r"unlink|rmtree|remove\(|rename\(|replace\(\s*[A-Za-z_]+\s*\)\s*$"),
}
REDIRECT_ALLOWED = re.compile(r"(?:2>/dev/null|>/dev/null|2>&1|>&2)(?![\w./-])")


@pytest.mark.parametrize("label,bad", [
    ("errexit", "set -eu"), ("privilege", "x=$(sudo cat /etc/shadow)"), ("file or attribute change", "  rm -f x"),
    ("file or attribute change", "a | tee out"), ("other programs", "  docker ps"), ("other programs", "x | xargs rm"),
    ("other programs", "; kill 1"), ("other programs", "  wget https://x"), ("find -delete", "find / -delete"),
    ("request with a body or method", "curl -sS -X POST https://x"), ("request with a body or method", "curl -d a u"),
    ("in-place edit", "sed -i s/a/b/ f"), ("journal maintenance", "journalctl --vacuum-time=1d"),
    ("lab command", "python -m edge_lab.cli shadow daily"),
])
def test_mutating_patterns_are_not_vacuous(label, bad):
    assert MUTATING[label].search(bad)


@pytest.mark.parametrize("line", ["echo x >/dev/nullx", "echo x > out.txt", "echo x >> log", "cmd 2>/dev/null.bak"])
def test_redirect_allowlist_is_not_vacuous(line):
    assert ">" in REDIRECT_ALLOWED.sub("", line)


@pytest.mark.parametrize("label,bad", [
    ("write mode", 'open(p, "w")'), ("write mode", "open(p, mode='a', encoding='utf-8')"),
    ("os module", "import os"), ("subprocess", "import subprocess"), ("socket", "import socket"),
    ("urllib", "from urllib.request import urlopen"),
])
def test_embedded_python_patterns_are_not_vacuous(label, bad):
    assert EMBEDDED_PYTHON_FORBIDDEN[label].search(bad)
    assert not EMBEDDED_PYTHON_FORBIDDEN["write mode"].search('open(sys.argv[1], encoding="utf-8") as stream')


def _verify_code_lines():
    """Non-comment lines of the script (the embedded Python has no comments)."""
    return [line for line in VERIFY.read_text().splitlines() if not line.lstrip().startswith("#")]


def _embedded_python():
    text = VERIFY.read_text()
    bodies = re.findall(r"<<'PY'[^\n]*\n(.*?)\nPY\n", text, re.S)
    assert len(bodies) == 3, "expected the latest.json, shadow_daily.json and backup-journal parsers"
    return bodies


def test_verify_production_script_exists_with_lf_and_is_not_scheduled():
    raw = VERIFY.read_bytes()
    assert raw.startswith(b"#!/usr/bin/env bash\n") and b"\r\n" not in raw
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    assert not [u for u in units if "verify" in u]
    assert "verify_production" not in INSTALL
    assert not [p.name for p in UNITS.iterdir() if "verify_production" in p.read_text()]


def test_verify_production_script_parses():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    result = subprocess.run([bash, "-n", str(VERIFY)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_verify_production_reports_every_state_separately():
    text = VERIFY.read_text()
    for name in VERIFY_STATES:  # the smoke run below checks each is actually printed exactly once
        assert re.search(rf"\b{name}\b", text), f"no STATE line for {name}"
    assert "STATE %s: %s" in text and "SUMMARY" in text and "One state does not imply the next" in text
    assert "NOT_READABLE_WITHOUT_PRIVILEGE" in text
    for timer in ("pfm", "decision", "recheck", "status", "backup", "shadow", "settlement"):
        assert re.search(rf"NAMES=\([^)]*\b{timer}\b", text)
    assert "set -u" in text


def test_verify_production_uses_only_allowlisted_commands():
    lines = _verify_code_lines()
    hits = [f"{label}: {line.strip()}" for line in lines for label, rx in MUTATING.items() if rx.search(line)]
    assert not hits, "\n".join(hits)
    verbs = {m.group(1) for line in lines for m in re.finditer(r"\bsystemctl\s+(\S+)", line)}
    assert verbs and verbs <= SYSTEMCTL_VERBS, f"systemctl verbs outside the read-only allowlist: {verbs - SYSTEMCTL_VERBS}"
    continued = [line for line in lines if line.rstrip().endswith("\\")]
    assert not continued, "line continuations hide commands from these checks:\n" + "\n".join(continued)
    redirects = [line.strip() for line in lines if ">" in REDIRECT_ALLOWED.sub("", line)]
    assert not redirects, "output redirection to a file:\n" + "\n".join(redirects)
    curls = [line.strip() for line in lines if re.search(COMMAND_START + r"curl\b", line)]
    assert curls == [CURL_LINE]
    pythons = [line for line in lines if re.search(r"\bpython3\b", line)]
    assert pythons and all(re.search(r"\bpython3 -I -B -c ", line) for line in pythons), pythons


def test_embedded_python_only_reads():
    for body in _embedded_python():
        for label, rx in EMBEDDED_PYTHON_FORBIDDEN.items():
            assert not rx.search(body), f"embedded python: {label}"
        assert ">" not in body, "keep the embedded python free of '>' so the redirect check stays exact"
        compile(body, "<embedded>", "exec")


# --------------------------------------------------------------------------- running the script


def _run_verify(tmp_path, **env_extra):
    """Run the script with `curl` stubbed on PATH (no network). Returns (states, stdout)."""
    bash = shutil.which("bash")
    if bash is None or sys.platform != "linux" or shutil.which("python3") is None:
        pytest.skip("needs bash and python3 on Linux")
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    stub = stubs / "curl"
    stub.write_text("#!/bin/sh\nprintf '{\"status\":\"stub\"}\\n200'\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}", **env_extra}
    result = subprocess.run([bash, str(VERIFY)], capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, result.stderr
    states = {}
    for line in result.stdout.splitlines():
        m = re.fullmatch(r"STATE ([A-Z0-9_]+): (.*)", line)
        if m:
            assert m.group(1) not in states, f"{m.group(1)} printed twice"
            states[m.group(1)] = m.group(2)
    return states, result.stdout


def test_verify_production_runs_to_the_summary_without_network(tmp_path):
    states, out = _run_verify(tmp_path)
    summary = out[out.index("== SUMMARY"):]
    assert set(states) == set(VERIFY_STATES)
    for name in VERIFY_STATES:
        assert f"  {name}: " in summary, name
    for name in DIRECTIVE_STATES:
        assert states[name], name
    assert states["API_HEALTH"].startswith("HTTP 200") and "OVERRIDE" not in out


def _journal(path, runs):
    """Write `journalctl -o json`-shaped lines: one entry per stdout line of each run."""
    with path.open("w", encoding="utf-8") as stream:
        for i, (invocation, text) in enumerate(runs):
            for j, line in enumerate(text.splitlines()):
                stream.write(json.dumps({"MESSAGE": line, "_SYSTEMD_INVOCATION_ID": invocation,
                                         "__REALTIME_TIMESTAMP": str(1790000000000000 + i * 10**9 + j)}) + "\n")
            stream.write(json.dumps({"MESSAGE": "Finished edgelab-backup.service.", "INVOCATION_ID": invocation,
                                     "__REALTIME_TIMESTAMP": str(1790000000000000 + i * 10**9 + 999)}) + "\n")
    return path


def _backup_stdout(capsys, *argv):
    from edge_lab import backup

    backup.main(list(argv))
    return capsys.readouterr().out


def test_verify_production_parses_real_status_files_and_backup_reports(tmp_path, monkeypatch, capsys):
    """Fixtures come from the real code: forward.summary (latest.json), daily.run (shadow_daily.json)
    and edge_lab.backup (the backup unit's two reports)."""
    from test_forward import _full_day, at

    from edge_lab import daily, forward
    from edge_lab.storage import SnapshotStore

    store = SnapshotStore(tmp_path / "fwd.sqlite3")
    _full_day(store, monkeypatch)
    status = tmp_path / "status"
    status.mkdir()
    latest = forward.summary(store, now_utc=at(22, 30))
    (status / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    ledger = tmp_path / "ledger.sqlite3"
    receipt, _ = daily.run(store.path, ledger, status_dir=status, now=at(23, 0))
    assert receipt["state"] == "PENDING_SETTLEMENT"
    out_dir = tmp_path / "bk" / "backups"
    evidence = _backup_stdout(capsys, "create", "--kind", "evidence", "--db", str(store.path), "--out", str(out_dir))
    ledger_report = _backup_stdout(capsys, "create", "--kind", "ledger", "--if-exists", "--db", str(ledger),
                                   "--out", str(out_dir / "ledger"))
    journal = _journal(tmp_path / "journal.json", [("run-1", evidence + ledger_report)])

    states, out = _run_verify(tmp_path, EDGE_LAB_VERIFY_STATUS_DIR=str(status),
                              EDGE_LAB_VERIFY_BACKUP_JOURNAL=str(journal))
    assert "OVERRIDE status files read from" in out and "OVERRIDE backup reports read from" in out
    assert json.loads(states["LATEST_JSON"])["valid_days"] == 1
    assert states["COLLECTOR_HEALTH"].startswith(f"VALID (last closed day {latest['last_closed_target_date']};")
    assert states["VALID_DAY_OBSERVED"] == "YES (latest.json valid_days = 1)"
    assert states["LATEST_JSON_AGE"].endswith(f"(generated_at_utc {latest['generated_at_utc']})")
    shadow = json.loads(states["SHADOW_DAILY"])
    assert shadow["state"] == "PENDING_SETTLEMENT" and shadow["valid_days"] == 1
    assert shadow["fee"]["schedule_id"] == receipt["fee"]["schedule_id"] and "claim_basis" in shadow["fee"]
    assert shadow["days"][0]["target_date"] == receipt["days"][0]["target_date"]
    assert shadow["settlement"]["pending"] == len(receipt["settlement"]["pending"])
    assert states["BACKUP_REPORTS_8D"] == "2 report(s) in 1 run(s)"
    assert states["BACKUP_EVIDENCE_DB"].startswith("CREATED at ") and str(out_dir) in states["BACKUP_EVIDENCE_DB"]
    assert states["BACKUP_SHADOW_LEDGER"].startswith("CREATED at ") and "/ledger/" in states["BACKUP_SHADOW_LEDGER"]
    assert states["RESTORE_EVIDENCE_DB"].startswith("VERIFIED at ") and "row counts" in states["RESTORE_EVIDENCE_DB"]
    assert states["RESTORE_SHADOW_LEDGER"].startswith("VERIFIED at ") and "ledger_entries" in states["RESTORE_SHADOW_LEDGER"]
    assert "attributed by its order" not in out


def test_verify_production_backup_failure_skip_and_latest_run(tmp_path, capsys):
    """RESTORE_* is never inferred from BACKUP_*: a FAILED report gives no restore, a skipped ledger
    gives NOT_RUN, and the newest run wins."""
    failed = _backup_stdout(capsys, "create", "--db", str(tmp_path / "absent.sqlite3"), "--out", str(tmp_path / "b"))
    skipped = _backup_stdout(capsys, "create", "--kind", "ledger", "--if-exists", "--db",
                             str(tmp_path / "absent-ledger.sqlite3"), "--out", str(tmp_path / "b" / "ledger"))
    assert json.loads(failed)["status"] == "FAILED" and json.loads(skipped)["status"] == "SKIPPED_NO_SOURCE"
    old_ok = json.dumps({"status": "VERIFIED_BACKUP_AND_RESTORE", "row_counts": {"snapshots": 1},
                         "schema_sha256": "0" * 64, "bundle": "/var/lib/market-edge-lab/backups/old"}, indent=2)
    journal = _journal(tmp_path / "j.json", [("old", old_ok), ("new", failed + skipped)])
    states, _ = _run_verify(tmp_path, EDGE_LAB_VERIFY_BACKUP_JOURNAL=str(journal))
    assert states["BACKUP_REPORTS_8D"] == "3 report(s) in 2 run(s)"
    assert states["BACKUP_EVIDENCE_DB"].startswith("FAILED at ") and "attributed by its order" in states["BACKUP_EVIDENCE_DB"]
    assert states["RESTORE_EVIDENCE_DB"].startswith("FAILED_OR_NOT_RUN at ")
    assert states["BACKUP_SHADOW_LEDGER"].startswith("SKIPPED_NO_SOURCE at ")
    assert states["RESTORE_SHADOW_LEDGER"].startswith("NOT_RUN at ")


def test_verify_production_backup_verified_without_restore_fields_is_not_restore_verified(tmp_path):
    report = json.dumps({"status": "VERIFIED_BACKUP_AND_RESTORE", "bundle": "/var/lib/market-edge-lab/backups/x"})
    states, _ = _run_verify(tmp_path, EDGE_LAB_VERIFY_BACKUP_JOURNAL=str(_journal(tmp_path / "j.json", [("r", report)])))
    assert states["BACKUP_EVIDENCE_DB"].startswith("CREATED at ")
    assert states["RESTORE_EVIDENCE_DB"].startswith("UNKNOWN at ")
    assert states["BACKUP_SHADOW_LEDGER"].startswith("NONE_IN_WINDOW")


def test_verify_production_marks_a_store_missing_from_the_newest_run(tmp_path):
    """An older VERIFIED ledger report must not read as current when the newest run has none
    (for example the ledger step crashed before printing a report)."""
    ok = {"status": "VERIFIED_BACKUP_AND_RESTORE", "row_counts": {"t": 1}, "schema_sha256": "0" * 64}
    old = json.dumps({**ok, "bundle": "/var/lib/market-edge-lab/backups/e1"}, indent=2) + "\n" + json.dumps(
        {**ok, "bundle": "/var/lib/market-edge-lab/backups/ledger/l1"}, indent=2)
    new = json.dumps({**ok, "bundle": "/var/lib/market-edge-lab/backups/e2"}, indent=2) + "\nTraceback (most recent call last):"
    states, _ = _run_verify(tmp_path, EDGE_LAB_VERIFY_BACKUP_JOURNAL=str(_journal(tmp_path / "j.json",
                                                                                   [("old", old), ("new", new)])))
    assert states["BACKUP_EVIDENCE_DB"].startswith("CREATED at ") and "/e2" in states["BACKUP_EVIDENCE_DB"]
    assert states["BACKUP_SHADOW_LEDGER"].startswith("NOT_IN_LATEST_RUN")
    assert states["RESTORE_SHADOW_LEDGER"].startswith("NOT_IN_LATEST_RUN")
    assert states["RESTORE_EVIDENCE_DB"].startswith("VERIFIED at ")


def test_verify_production_no_valid_day_and_no_capture_receipt(tmp_path):
    from test_forward import at

    from edge_lab import daily, forward
    from edge_lab.storage import SnapshotStore

    status = tmp_path / "status"
    status.mkdir()
    latest = forward.summary(SnapshotStore(tmp_path / "empty.sqlite3"), now_utc=at(22, 30))
    (status / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    receipt, _ = daily.run(tmp_path / "missing.sqlite3", tmp_path / "l.sqlite3", status_dir=status, now=at(23, 0))
    states, _ = _run_verify(tmp_path, EDGE_LAB_VERIFY_STATUS_DIR=str(status))
    assert states["VALID_DAY_OBSERVED"] == "NO (latest.json valid_days = 0)"
    assert states["COLLECTOR_HEALTH"].startswith(f"{latest['last_closed_status']} (")
    assert json.loads(states["SHADOW_DAILY"])["state"] == receipt["state"] == "NO_CAPTURE"


@pytest.mark.parametrize("content,valid,health", [
    ('{"valid_days": "3", "last_closed_status": "VALID"}', "UNKNOWN (latest.json valid_days is not a non-negative integer: '3')", "VALID ("),
    ('{"valid_days": true}', "UNKNOWN (latest.json valid_days is not a non-negative integer: True)", "UNKNOWN (latest.json has no"),
    ('{"valid_days": -1}', "UNKNOWN (latest.json valid_days is not a non-negative integer: -1)", "UNKNOWN ("),
    ('{}', "UNKNOWN (latest.json valid_days is not a non-negative integer: None)", "UNKNOWN ("),
    ('[1, 2]', "UNKNOWN (latest.json NOT_A_JSON_OBJECT (list))", "UNKNOWN (latest.json NOT_A_JSON_OBJECT"),
    ('"text"', "UNKNOWN (latest.json NOT_A_JSON_OBJECT (str))", "UNKNOWN ("),
    ('{not json', "UNKNOWN (latest.json UNPARSEABLE (JSONDecodeError))", "UNKNOWN (latest.json UNPARSEABLE"),
])
def test_verify_production_malformed_latest_json_is_unknown(tmp_path, content, valid, health):
    status = tmp_path / "status"
    status.mkdir()
    (status / "latest.json").write_text(content, encoding="utf-8")
    (status / "shadow_daily.json").write_text(content, encoding="utf-8")
    states, _ = _run_verify(tmp_path, EDGE_LAB_VERIFY_STATUS_DIR=str(status))
    assert states["VALID_DAY_OBSERVED"] == valid
    assert states["COLLECTOR_HEALTH"].startswith(health)
    assert states["LATEST_JSON_AGE"].startswith("UNKNOWN")
    shadow = states["SHADOW_DAILY"]
    assert shadow.startswith(("NOT_A_JSON_OBJECT", "UNPARSEABLE")) or json.loads(shadow)["state"] is None


# --------------------------------------------------------------------------- ntfy relay + secrets (ADR 0028)

def test_notify_relay_runs_in_its_own_networked_unit_after_each_daily_run():
    relay = _parse("edgelab-notify.service")
    assert relay[("Service", "ExecStart")] == [
        "/opt/market-edge-lab/venv/bin/python -m edge_lab.cli notify relay --status-dir /var/lib/market-edge-lab-status"]
    assert relay[("Service", "EnvironmentFile")] == ["/etc/market-edge-lab/env", "-/etc/market-edge-lab/secrets.env"]
    assert ("Unit", "OnFailure") not in relay  # a relay failure never alerts about itself in a loop
    assert not (UNITS / "edgelab-notify.timer").exists()
    for name in ("edgelab-shadow.service", "edgelab-settlement.service"):
        u = _parse(name)
        assert u[("Unit", "OnSuccess")] == ["edgelab-notify.service"], name
        assert u[("Unit", "OnFailure")] == ["edgelab-alert@%n.service"], name
        assert ("Service", "EnvironmentFile") in u and "-/etc/market-edge-lab/secrets.env" not in u[
            ("Service", "EnvironmentFile")], f"{name} must not load the owner's secrets"
    # A failure is recorded by alert.sh (last_failure.json) first, then relayed as a fixed headline.
    assert _parse("edgelab-alert@.service")[("Unit", "OnSuccess")] == ["edgelab-notify.service"]
    # The bookkeeping unit keeps no network: the push happens only in the relay.
    assert _parse("edgelab-shadow.service")[("Service", "IPAddressDeny")] == ["any"]


def test_only_units_that_need_a_secret_load_the_secrets_file():
    loaders = sorted(p.name for p in UNITS.glob("*.service") if "secrets.env" in p.read_text())
    assert set(loaders) <= {"edgelab-notify.service", "edgelab-odds.service"}, loaders
    for name in loaders:
        assert "-/etc/market-edge-lab/secrets.env" in _parse(name)[("Service", "EnvironmentFile")]


def test_install_creates_the_secrets_file_once_and_never_reads_it():
    assert 'SECRETS_FILE=$ETC/secrets.env' in INSTALL
    assert 'if [ ! -e "$SECRETS_FILE" ]; then' in INSTALL
    assert 'install -o root -g root -m 0600 /dev/null "$SECRETS_FILE"' in INSTALL
    assert 'chown root:root "$SECRETS_FILE"; chmod 0600 "$SECRETS_FILE"' in INSTALL
    reads = [line.strip() for line in INSTALL.splitlines()
             if "SECRETS_FILE" in line and re.search(r"\b(cat|sed|grep|source|head|tail|cp|mv|awk)\b|<\s*\"?\$SECRETS", line)]
    assert not reads, reads
    assert "secrets file is root:root 600" in INSTALL
    assert 'expect_not "edgelab cannot read the secrets file"' in INSTALL
    assert "cannot read the secrets file" in INSTALL
    assert "edgelab-notify" in INSTALL


# --------------------------------------------------------------------------- topic writer (ADR 0028)

def _topic_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("set_ntfy_topic", ROOT / "deploy/vps/set_ntfy_topic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _topic(text):
    return [line for line in text.splitlines() if line.startswith("EDGE_LAB_NTFY_TOPIC_URL=")]


def test_topic_writer_adds_a_topic_keeps_other_lines_and_prints_nothing_secret(tmp_path, capsys):
    mod = _topic_module()
    path = tmp_path / "secrets.env"
    path.write_text("EDGE_LAB_ODDS_API_KEY=abc\n")
    uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (0, 0)
    assert mod.write_topic(str(path), uid=uid, gid=gid) == "written"
    text = path.read_text()
    assert "EDGE_LAB_ODDS_API_KEY=abc" in text and len(_topic(text)) == 1
    url = _topic(text)[0].split("=", 1)[1]
    from edge_lab import notify_ntfy
    assert notify_ntfy.parse_topic_url(url)  # a valid, allowlisted topic URL
    assert url not in capsys.readouterr().out
    if hasattr(os, "getuid"):
        assert (path.stat().st_mode & 0o777) == 0o600


def test_topic_writer_keeps_an_existing_topic_unless_forced(tmp_path):
    mod = _topic_module()
    path = tmp_path / "secrets.env"
    path.write_text("export EDGE_LAB_NTFY_TOPIC_URL=https://ntfy.sh/mel-existing-topic-000\n")
    uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (0, 0)
    assert mod.write_topic(str(path), uid=uid, gid=gid) == "kept"
    assert "mel-existing-topic-000" in path.read_text()
    assert mod.write_topic(str(path), force=True, uid=uid, gid=gid) == "written"
    text = path.read_text()
    assert "mel-existing-topic-000" not in text and len(_topic(text)) == 1
    assert not list(tmp_path.glob("secrets.env.new.*"))


def test_runbook_uses_the_tested_topic_writer_not_an_inline_snippet():
    runbook = (ROOT / "docs/deploy/DAILY_SHADOW_ACTIVATION.md").read_text()
    section = runbook[runbook.index("## 5a."):runbook.index("## 6.")]
    assert "deploy/vps/set_ntfy_topic.py" in section and "python3 - <<" not in section
    assert "EDGE_LAB_ALERT_URL" in section  # the warning not to point it at the topic
