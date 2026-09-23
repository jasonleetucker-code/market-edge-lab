"""Static checks of the VPS unit files: schedule, isolation, combined budget, both backups."""

import configparser
import re
from pathlib import Path

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
    execs = _parse("edgelab-backup.service")[("Service", "ExecStart")]
    assert len(execs) == 2
    assert "--kind evidence" in execs[0] and "edge_lab.sqlite3" in execs[0]
    assert "--kind ledger" in execs[1] and "--if-exists" in execs[1] and "--lock-file" in execs[1]


def test_install_script_knows_every_timer_and_keeps_the_ledger_private():
    units = re.search(r"UNITS=\(([^)]*)\)", INSTALL).group(1).split()
    timers = sorted(p.stem for p in UNITS.glob("*.timer"))
    assert sorted(units) == timers
    assert '"$DATA/ledger"' in INSTALL and "cannot list the shadow ledger" in INSTALL
    assert "edgelab.slice" in INSTALL
