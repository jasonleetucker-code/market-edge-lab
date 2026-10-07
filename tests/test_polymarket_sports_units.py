"""The Polymarket US NFL pilot units (ADR 0032): hardened, networked for the public gateway only,
no secrets, non-persistent timers pinned to the code, installed with the other units but
separately activated: install.sh never enables them (runbook section 5e does, under the owner's
recorded risk decision)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edge_lab import polymarket_sports as ps
from edge_lab.price_observations import protected_window_at

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "vps" / "systemd"
INSTALL = (ROOT / "deploy" / "vps" / "install.sh").read_text()


def _parse(name: str) -> dict[tuple[str, str], list[str]]:
    values: dict[tuple[str, str], list[str]] = {}
    section = None
    for line in (UNITS / name).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault((section, key), []).append(value)
    return values


def test_services_are_hardened_bounded_and_load_no_secret():
    for name, command in (("edgelab-pm-sports-discover.service", "pm-sports discover"),
                          ("edgelab-pm-sports.service", "pm-sports capture")):
        u = _parse(name)
        assert u[("Service", "Slice")] == ["edgelab.slice"] and u[("Service", "User")] == ["edgelab"]
        assert u[("Service", "MemoryMax")] == ["256M"] and u[("Service", "TimeoutStartSec")] == ["5min"]
        assert u[("Service", "RestrictAddressFamilies")] == ["AF_INET AF_INET6 AF_UNIX"]
        assert u[("Service", "ProtectSystem")] == ["strict"] and u[("Service", "NoNewPrivileges")] == ["yes"]
        assert u[("Service", "EnvironmentFile")] == ["/etc/market-edge-lab/env"]  # never secrets.env
        assert "secrets.env" not in (UNITS / name).read_text()
        exec_start = u[("Service", "ExecStart")]
        assert len(exec_start) == 1 and f"-m edge_lab.cli {command} --db /var/lib/market-edge-lab/db/edge_lab.sqlite3" \
            in exec_start[0]
        assert "--force" not in exec_start[0]
    # The code's own deadline sits well inside the unit's hard stop.
    assert ps.MAX_RUN < timedelta(minutes=5)


def test_timers_are_nonpersistent_staggered_and_pinned_to_the_code():
    cap = _parse("edgelab-pm-sports.timer")
    disc = _parse("edgelab-pm-sports-discover.timer")
    assert cap[("Timer", "OnCalendar")] == ["*-*-* *:10/15:00 America/New_York"]
    assert ps.TICK_INTERVAL == timedelta(minutes=15)
    assert cap[("Timer", "Persistent")] == ["false"] and disc[("Timer", "Persistent")] == ["false"]
    assert cap[("Timer", "Unit")] == ["edgelab-pm-sports.service"]
    assert disc[("Timer", "Unit")] == ["edgelab-pm-sports-discover.service"]
    m = re.fullmatch(r"\*-\*-\* ([\d,]+):(\d\d):00 America/New_York", disc[("Timer", "OnCalendar")][0])
    hours = [int(h) for h in m.group(1).split(",")]
    assert len(hours) == 4 and all((b - a) == 6 for a, b in zip(hours, hours[1:]))  # every 6 h
    assert ps.DISCOVERY_INTERVAL == timedelta(hours=6)
    # Discovery never shares a minute with a capture tick (both take the pilot lock; LOCK_BUSY would
    # skip a scan for 6 h) nor with the odds, observe or freshness ticks.
    minute = int(m.group(2))
    capture_minutes = {10, 25, 40, 55}
    assert minute not in capture_minutes | {0, 15, 30, 45} | {5, 20, 35, 50} | set(range(1, 60, 5))
    # No discovery tick can start inside a protected window (a Wednesday in EDT and one in EST).
    for day in (datetime(2026, 9, 23, tzinfo=timezone.utc), datetime(2026, 12, 2, tzinfo=timezone.utc)):
        offset = timedelta(hours=4 if day.month == 9 else 5)
        for h in hours:
            start = day + timedelta(hours=h, minutes=int(m.group(2))) + offset
            assert protected_window_at(start, start + ps.MAX_RUN) is None, (day, h)


def test_capture_ticks_next_to_the_settlement_windows_finish_before_them():
    day = datetime(2026, 9, 23, tzinfo=timezone.utc)  # EDT
    for et, allowed in (("11:10", True), ("11:25", False), ("16:10", True), ("16:25", False), ("17:40", False),
                        ("18:40", False), ("18:55", True)):
        h, m = map(int, et.split(":"))
        at = day + timedelta(hours=h + 4, minutes=m)
        assert (ps.protected_refusal(at, "pm-sports capture") is None) is allowed, et


def test_a_late_tick_before_a_settlement_window_runs_with_a_shortened_deadline():
    """systemd fires the :10 ticks a few seconds late; a full MAX_RUN from then would reach the :13
    window. The run is cut to end RUN_MARGIN before it, and only refused with under MIN_RUN left."""
    day = datetime(2026, 9, 26, tzinfo=timezone.utc)  # a Saturday in EDT
    for h in (11, 16):
        window = day + timedelta(hours=h + 4, minutes=13)
        for late_s in (0, 7, 30, 90):
            at = day + timedelta(hours=h + 4, minutes=10, seconds=late_s)
            assert ps.run_deadline(at) == window - ps.RUN_MARGIN, (h, late_s)
            assert ps.protected_refusal(at, "pm-sports capture") is None, (h, late_s)
        too_late = window - ps.RUN_MARGIN - ps.MIN_RUN + timedelta(seconds=1)
        assert ps.run_deadline(too_late) is None
        assert ps.protected_refusal(too_late, "pm-sports capture")["state"] == "DEFERRED_PROTECTED_WINDOW"
        assert ps.run_deadline(window + timedelta(minutes=5)) is None  # inside the window
    clear = day + timedelta(hours=21)  # 17:00 EDT: nothing near
    assert ps.run_deadline(clear) == clear + ps.MAX_RUN
    assert ps.MIN_RUN + ps.RUN_MARGIN < ps.MAX_RUN


def test_the_installer_installs_but_never_enables_the_pilot_timers():
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    separate = re.search(r"SEPARATELY_ACTIVATED=\(([^)]*)\)", INSTALL).group(1).split()
    for unit in ("edgelab-pm-sports", "edgelab-pm-sports-discover"):
        assert unit in units and unit in separate  # installed and verified, activated separately
        assert (UNITS / f"{unit}.timer").is_file() and (UNITS / f"{unit}.service").is_file()
    assert not list(UNITS.glob("*.proposed"))
    assert "systemctl enable" not in INSTALL.split("cat <<EOF")[0]  # the installer enables nothing itself
    # The printed stop line names every separately activated timer too.
    assert "disable --now ${CORE_TIMERS[*]/%/.timer} ${SEPARATELY_ACTIVATED[*]/%/.timer}" in INSTALL


def test_fabric_schedule_owner_names_the_timers_real_schedule():
    """The fabric shows schedule_owner verbatim in Terminal; it must match the unit files."""
    disc = _parse("edgelab-pm-sports-discover.timer")[("Timer", "OnCalendar")][0]
    cal = disc.removeprefix("*-*-* ").replace(":00 America/New_York", " America/New_York")
    import inspect

    assert f"edgelab-pm-sports-discover.timer {cal}" in inspect.getsource(ps), cal
