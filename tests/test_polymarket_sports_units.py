"""The Polymarket US NFL pilot units (ADR 0032): hardened, networked for the public gateway only,
no secrets, non-persistent timers pinned to the code, and not enabled by the installer.

The timers are committed as `*.timer.proposed`: install.sh (coordinator-owned) must list every
`*.timer` in UNITS, and the separately activated set is a single value today. The coordinator
renames them when it extends that set (see ADR 0032, "Coordinator integration")."""

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


def test_proposed_timers_are_nonpersistent_staggered_and_pinned_to_the_code():
    cap = _parse("edgelab-pm-sports.timer.proposed")
    disc = _parse("edgelab-pm-sports-discover.timer.proposed")
    assert cap[("Timer", "OnCalendar")] == ["*-*-* *:10/15:00 America/New_York"]
    assert ps.TICK_INTERVAL == timedelta(minutes=15)
    assert cap[("Timer", "Persistent")] == ["false"] and disc[("Timer", "Persistent")] == ["false"]
    assert cap[("Timer", "Unit")] == ["edgelab-pm-sports.service"]
    assert disc[("Timer", "Unit")] == ["edgelab-pm-sports-discover.service"]
    m = re.fullmatch(r"\*-\*-\* ([\d,]+):(\d\d):00 America/New_York", disc[("Timer", "OnCalendar")][0])
    hours = [int(h) for h in m.group(1).split(",")]
    assert len(hours) == 4 and all((b - a) == 6 for a, b in zip(hours, hours[1:]))  # every 6 h
    assert ps.DISCOVERY_INTERVAL == timedelta(hours=6)
    # No discovery tick can start inside a protected window (a Wednesday in EDT and one in EST).
    for day in (datetime(2026, 9, 23, tzinfo=timezone.utc), datetime(2026, 12, 2, tzinfo=timezone.utc)):
        offset = timedelta(hours=4 if day.month == 9 else 5)
        for h in hours:
            start = day + timedelta(hours=h, minutes=int(m.group(2))) + offset
            assert protected_window_at(start, start + ps.MAX_RUN) is None, (day, h)


def test_the_installer_does_not_know_or_enable_the_pilot_timers():
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    assert not [u for u in units if u.startswith("edgelab-pm-sports")]
    assert not list(UNITS.glob("edgelab-pm-sports*.timer"))  # staged, never picked up by the installer's list
