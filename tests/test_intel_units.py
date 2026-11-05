"""Static checks of the news intelligence units (#192, ADR 0049): modelled on the Polymarket US pilot units,
shipped disabled and separately activated, clear of every protected window, and covered by the existing
install, verify and stop tooling. No network; systemd-analyze is used only when it is installed."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import forward
from edge_lab import price_observations as po
from edge_lab.intel import kalshi_link
from edge_lab.intel.cli import build_parser

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "vps" / "systemd"
INSTALL = (ROOT / "deploy" / "vps" / "install.sh").read_text(encoding="utf-8")
VERIFY = (ROOT / "deploy" / "vps" / "verify_production.sh").read_text(encoding="utf-8")
RUNBOOK = (ROOT / "docs" / "deploy" / "NEWS_INTEL_ACTIVATION.md").read_text(encoding="utf-8")
DB = "/var/lib/market-edge-lab/db/edge_lab.sqlite3"
INBOX = "/var/lib/market-edge-lab/intel-inbox"
STATUS = "/var/lib/market-edge-lab-status"
PY = "/opt/market-edge-lab/venv/bin/python -m edge_lab.cli"
NEWS_CAL = "*-*-* 01/2:32:00 America/New_York"
INBOX_CAL = "*-*-* *:03/5:00 America/New_York"


def unit(name: str) -> dict[tuple[str, str], list[str]]:
    values: dict[tuple[str, str], list[str]] = {}
    section = None
    for line in (UNITS / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault((section, key), []).append(value)
    return values


def timeout(name: str) -> timedelta:
    m = re.fullmatch(r"(\d+)(min|s)", unit(name)[("Service", "TimeoutStartSec")][0])
    return timedelta(minutes=int(m.group(1))) if m.group(2) == "min" else timedelta(seconds=int(m.group(1)))


# --------------------------------------------------------------------------- services


@pytest.mark.parametrize("name", ["edgelab-news.service", "edgelab-news-inbox.service"])
def test_services_copy_the_pilot_units_hardening_and_load_no_secret(name):
    u, model = unit(name), unit("edgelab-pm-sports-discover.service")
    # Every key the pilot unit sets, the news unit sets to the same value, except what it runs and how long.
    differ = {("Unit", "Description"), ("Unit", "Documentation"), ("Service", "ExecStart"),
              ("Service", "TimeoutStartSec")}
    assert set(u) == set(model)
    for key in set(model) - differ:
        assert u[key] == model[key], key
    assert u[("Service", "User")] == ["edgelab"] and u[("Service", "Slice")] == ["edgelab.slice"]
    assert u[("Service", "MemoryMax")] == ["256M"]
    assert u[("Service", "ReadWritePaths")] == ["/var/lib/market-edge-lab /var/lib/market-edge-lab-status"]
    assert u[("Unit", "OnFailure")] == ["edgelab-alert@%n.service"]
    assert u[("Service", "EnvironmentFile")] == ["/etc/market-edge-lab/env"]  # never secrets.env
    assert "secrets" not in (UNITS / name).read_text(encoding="utf-8").replace("No secrets", "")
    assert u[("Unit", "Documentation")] == ["file:///opt/market-edge-lab/app/docs/decisions/0049-news-intel-slice.md"]
    # Bounded: a hung run is killed well inside the 2-hour cadence and the calendar's clearances.
    assert timedelta(minutes=1) <= timeout(name) <= timedelta(minutes=6)


def test_exec_lines_are_the_cli_entry_points_with_the_production_paths():
    news = unit("edgelab-news.service")[("Service", "ExecStart")]
    inbox = unit("edgelab-news-inbox.service")[("Service", "ExecStart")]
    assert news == [f"{PY} intel --db {DB} run --inbox {INBOX} --status-dir {STATUS}"]
    assert inbox == [f"{PY} intel --db {DB} process-inbox --inbox {INBOX} --status-dir {STATUS}"]
    for line, cmd in ((news[0], "run"), (inbox[0], "process-inbox")):
        argv = line.split()[line.split().index("intel") + 1:]
        args = build_parser().parse_args(argv)
        assert (args.cmd, args.db, args.inbox, args.status_dir) == (cmd, DB, INBOX, STATUS)
    # edge_lab.cli hands `intel ...` to the intel CLI.
    assert 'argv[:1] == ["intel"]' in (ROOT / "src" / "edge_lab" / "cli.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- timers


def test_timers_are_nonpersistent_new_york_and_point_at_their_service():
    for name, cal, svc in (("edgelab-news.timer", NEWS_CAL, "edgelab-news.service"),
                           ("edgelab-news-inbox.timer", INBOX_CAL, "edgelab-news-inbox.service")):
        t = unit(name)
        assert t[("Timer", "OnCalendar")] == [cal]
        assert t[("Timer", "Persistent")] == ["false"]
        assert t[("Timer", "Unit")] == [svc]
        assert t[("Install", "WantedBy")] == ["timers.target"]
        assert ("Timer", "RandomizedDelaySec") not in t


def _grid_minutes(cal: str) -> set[int]:
    """The minutes of an every-hour grid calendar (`*:MM/step` or `*:MM`), or of a fixed-time one."""
    m = re.search(r"(?:\*|[\d,/]+):(\d\d)(?:/(\d+))?:\d\d", cal)
    assert m, cal
    start, step = int(m.group(1)), int(m.group(2) or 60)
    return set(range(start, 60, step))


def test_tick_minutes_collide_with_no_other_edgelab_timer():
    others: set[int] = set()
    for path in UNITS.glob("*.timer"):
        if path.name in ("edgelab-news.timer", "edgelab-news-inbox.timer"):
            continue
        for cal in unit(path.name)[("Timer", "OnCalendar")]:
            if "UTC" not in cal:  # the two UTC timers (backup, close tick) are checked as instants below
                others |= _grid_minutes(cal)
    news, inbox = _grid_minutes(NEWS_CAL), _grid_minutes(INBOX_CAL)
    assert news == {32} and inbox == set(range(3, 60, 5))
    assert not news & others and not inbox & others and not news & inbox


def _et_to_utc(day: date, hour: int, minute: int) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
    return local - forward.eastern_offset(local + timedelta(hours=5))


def _news_starts(day: date) -> list[datetime]:
    return [_et_to_utc(day, h, 32) for h in range(1, 24, 2)]


# Days in EST and in EDT, including both DST change days.
DAYS = (date(2026, 1, 14), date(2026, 3, 8), date(2026, 7, 1), date(2026, 11, 1), date(2026, 11, 5), date(2026, 12, 21))


@pytest.mark.parametrize("day", DAYS)
def test_every_news_run_is_clear_of_protected_windows_the_backup_and_the_close_tick(day):
    run = timeout("edgelab-news.service")
    backup_run = timeout("edgelab-backup.service")
    for start in _news_starts(day):
        end = start + run
        # The protected windows (EXP-001 capture + shadow, both settlement runs): the whole run is outside.
        assert po.protected_window_at(start, end) is None, start
        # The Kalshi lane's own refusal never fires on the scheduled run's start.
        assert kalshi_link.window_refusal(start) is None, start
        for k in (-1, 0, 1):
            d = day + timedelta(days=k)
            close = datetime.combine(d, po.CLOSE_TICK_UTC, UTC)
            assert end < close - kalshi_link.CLOSE_TICK_GUARD or start > close + kalshi_link.CLOSE_TICK_GUARD, start
            backup = datetime(d.year, d.month, d.day, 4, 40, tzinfo=UTC)
            assert end < backup or start > backup + backup_run, start
        # The EXP-001 forward ticks (17:45, 17:55:05, 18:05, 18:30 ET) lie inside the capture window above;
        # the 18:40 shadow run inside its protected tail. Nothing else to check per tick.


def test_the_calendar_model_matches_systemd_where_systemd_is_installed():
    exe = shutil.which("systemd-analyze")
    if exe is None:
        pytest.skip("systemd-analyze not installed")
    for base, day in (("2026-01-14 05:00:00 UTC", date(2026, 1, 14)), ("2026-07-01 04:00:00 UTC", date(2026, 7, 1))):
        out = subprocess.run([exe, "calendar", "--iterations=12", f"--base-time={base}", NEWS_CAL],
                             capture_output=True, text=True, timeout=30, env={"TZ": "UTC", "LANG": "C"})
        if out.returncode != 0:
            pytest.skip(f"systemd-analyze calendar unavailable: {out.stderr.strip()[:200]}")
        got = sorted(datetime.strptime(m, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                     for m in re.findall(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC", out.stdout))
        after = datetime.strptime(base[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        model = sorted(t for k in (-1, 0, 1) for t in _news_starts(day + timedelta(days=k)) if t > after)[:12]
        assert got == model


# --------------------------------------------------------------------------- install / verify / stop


def _array(name: str) -> list[str]:
    return re.search(rf"{name}=\(([^)]*)\)", INSTALL).group(1).split()


def test_install_knows_both_units_and_never_enables_them():
    for u in ("edgelab-news", "edgelab-news-inbox"):
        assert u in _array("UNITS") and u in _array("SEPARATELY_ACTIVATED")
    for line in INSTALL.splitlines():
        if "enable" in line and "news" in line:
            raise AssertionError(f"install.sh must never enable a news timer: {line}")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    start = INSTALL.index("UNITS=(")
    end = INSTALL.index("# The unprivileged account")
    script = INSTALL[start:end] + 'echo "${CORE_TIMERS[*]}"\n'
    core = subprocess.run([bash, "-c", script], capture_output=True, text=True, timeout=30).stdout.split()
    assert core and "edgelab-news" not in core and "edgelab-news-inbox" not in core


def test_install_creates_the_private_inbox_layout():
    assert 'install -d -o edgelab -g edgelab -m 0700 "$DATA/intel-inbox"' in INSTALL
    from edge_lab.intel.inbox import DIRS
    for sub in DIRS:
        assert f'"$DATA/intel-inbox/{sub}"' in INSTALL
    assert 'expect "intel inbox is edgelab:edgelab 700"' in INSTALL
    assert 'cannot list the intel inbox' in INSTALL


def test_verify_reports_both_timers_separately_and_outside_the_core_count():
    assert "timer_state NEWS_TIMER edgelab-news\n" in VERIFY
    assert "timer_state NEWS_INBOX_TIMER edgelab-news-inbox\n" in VERIFY
    names = re.search(r"NAMES=\(([^)]*)\)", VERIFY).group(1).split()
    assert not [n for n in names if "news" in n]


def test_every_stop_everything_line_names_both_timers():
    for path in (ROOT / "docs/deploy/DAILY_SHADOW_ACTIVATION.md", ROOT / "deploy/vps/README.md"):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines()
                 if "disable --now" in line and "edgelab-pfm.timer" in line]
        assert lines, path
        for line in lines:
            assert "edgelab-news.timer" in line and "edgelab-news-inbox.timer" in line, (path, line)


def test_rollback_docs_stamp_v7_and_remove_the_news_units():
    for path in (ROOT / "docs/deploy/DAILY_SHADOW_ACTIVATION.md", ROOT / "deploy/vps/README.md", ROOT / "docs/deploy/NEWS_INTEL_ACTIVATION.md"):
        text = path.read_text(encoding="utf-8")
        assert "mark-v7-for-rollback" in text, path
        assert "/etc/systemd/system/edgelab-news-inbox.timer" in text, path


def test_the_activation_runbook_is_the_owners_and_states_the_bounds():
    text = RUNBOOK
    assert "sudo systemctl enable --now edgelab-news.timer edgelab-news-inbox.timer" in text
    assert "sudo systemctl disable --now edgelab-news.timer edgelab-news-inbox.timer" in text
    assert "verify-sources" in text and text.index("verify-sources") < text.index("enable --now")
    assert "v8" in text and "mark-v7-for-rollback" in text
    assert "intel.json" in text and "news_feeds_public" in text and "intel_inbox" in text
    for bound in ("60 feed GETs", "120 Kalshi GETs", "protected windows", "close tick"):
        assert bound in text, bound
    assert "does **not** authorize deploying" in text
    assert "01:32, 03:32, ..., 23:32" in text and ":03, :08, ..., :58" in text
