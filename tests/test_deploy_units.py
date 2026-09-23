"""Static checks of the VPS unit files: schedule, isolation, combined budget, both backups."""

import configparser
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
        if path.name != "edgelab-alert@.service":
            assert u[("Service", "User")] == ["edgelab"] and u[("Service", "MemoryMax")] == ["256M"], path.name
            assert u[("Service", "ProtectSystem")] == ["strict"] and u[("Service", "NoNewPrivileges")] == ["yes"]
            assert u[("Service", "ReadWritePaths")] == ["/var/lib/market-edge-lab /var/lib/market-edge-lab-status"]
    s = _parse("edgelab.slice")
    assert s[("Slice", "MemoryMax")] == ["384M"] and s[("Slice", "CPUQuota")] == ["25%"]


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
    "NY_TIME", "IN_CAPTURE_WINDOW", "DEPLOYED_SHA", "TIMERS", "UNIT_RESULTS", "LATEST_JSON", "SHADOW_DAILY",
    "LAST_FAILURE", "COLLECTOR_INSTALLED", "TIMERS_ENABLED", "PFM_CAPTURE_OBSERVED", "DECISION_CAPTURE_OBSERVED",
    "RECHECK_CAPTURE_OBSERVED", "VALID_DAY_OBSERVED", "DB_SIZES", "BACKUPS", "JOURNAL_WARNINGS_24H", "OOM_30D",
    "MEMORY", "DISK", "BRISKET_UNITS", "API_HEALTH",
)
MUTATING = {
    "errexit": re.compile(r"\bset\s+-[a-z]*e|\bset\s+-o\s+errexit"),
    "privilege": re.compile(r"\bsudo\b|\bsu\s+-|\brunuser\b"),
    "file or attribute change": re.compile(
        r"(^|[|;&(`]|\bthen\b|\bdo\b|\belse\b)\s*(rm|mv|cp|chattr|chmod|chown|tee|touch|truncate|dd|ln|mkdir|"
        r"install|shred|rsync|scp|sqlite3|logger)\b"),
    "service control": re.compile(r"\bsystemctl\s+(start|stop|restart|reload|try-restart|enable|disable|reenable|"
                                  r"reset-failed|daemon-reload|mask|unmask|kill|edit|set-property|isolate)\b"),
    "request with a body or method": re.compile(
        r"\bcurl\b.*\s(-X|--request|-d|--data\S*|-F|--form|-T|--upload-file|-o|--output|-O|-K|--config)\b"),
    "in-place edit": re.compile(r"\bsed\s+(-[a-zA-Z]*i|--in-place)"),
    "journal maintenance": re.compile(r"\bjournalctl\b.*--(vacuum|rotate|flush|sync|relinquish)"),
    "lab command": re.compile(r"edge_lab\.|edge-lab\s"),
}


@pytest.mark.parametrize("label,bad", [
    ("errexit", "set -eu"), ("privilege", "x=$(sudo cat /etc/shadow)"), ("file or attribute change", "  rm -f x"),
    ("file or attribute change", "a | tee out"), ("service control", "systemctl restart edgelab-pfm.service"),
    ("request with a body or method", "curl -sS -X POST https://x"), ("request with a body or method", "curl -d a u"),
    ("in-place edit", "sed -i s/a/b/ f"), ("journal maintenance", "journalctl --vacuum-time=1d"),
    ("lab command", "python -m edge_lab.cli shadow daily"),
])
def test_mutating_patterns_are_not_vacuous(label, bad):
    assert MUTATING[label].search(bad)


def _verify_code_lines():
    """Non-comment lines of the script (the embedded Python has no comments)."""
    return [line for line in VERIFY.read_text().splitlines() if not line.lstrip().startswith("#")]


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
    for name in VERIFY_STATES:
        assert re.search(rf"\b(state|observed) {name}\b", text), f"no STATE line for {name}"
    assert "STATE %s: %s" in text and "SUMMARY" in text and "One state does not imply the next" in text
    assert "NOT_READABLE_WITHOUT_PRIVILEGE" in text
    for timer in ("pfm", "decision", "recheck", "status", "backup", "shadow", "settlement"):
        assert re.search(rf"NAMES=\([^)]*\b{timer}\b", text)
    assert "set -u" in text


def test_verify_production_contains_no_mutating_command():
    lines = _verify_code_lines()
    hits = [f"{label}: {line.strip()}" for line in lines for label, rx in MUTATING.items() if rx.search(line)]
    assert not hits, "\n".join(hits)
    allowed = re.compile(r"2>/dev/null|>/dev/null|2>&1|>&2")
    redirects = [line.strip() for line in lines if ">" in allowed.sub("", line)]
    assert not redirects, "output redirection to a file:\n" + "\n".join(redirects)
    curls = [line for line in lines if re.search(r"\bcurl\s+-", line)]
    assert len(curls) == 1 and "https://chaseupside.com/api/health" in curls[0]


def test_verify_production_runs_to_the_summary_without_network(tmp_path):
    """Smoke run on this host with `curl` stubbed: every state is printed and it exits 0."""
    bash = shutil.which("bash")
    if bash is None or sys.platform != "linux" or shutil.which("python3") is None:
        pytest.skip("needs bash and python3 on Linux")
    stub = tmp_path / "curl"
    stub.write_text("#!/bin/sh\nprintf '{\"status\":\"stub\"}\\n200'\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    result = subprocess.run([bash, str(VERIFY)], capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, result.stderr
    summary = result.stdout[result.stdout.index("== SUMMARY"):]
    for name in VERIFY_STATES:
        assert f"STATE {name}: " in result.stdout and f"  {name}: " in summary, name
    assert "STATE API_HEALTH: HTTP 200" in result.stdout
