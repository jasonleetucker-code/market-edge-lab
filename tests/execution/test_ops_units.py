"""Static checks of the executor's unit files, installer separation, runbook gates and CI artifacts
(#160 package O, ADR 0048). Nothing here installs, enables or runs anything."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from edge_lab.execution import ops

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "deploy" / "executor" / "systemd"
RESEARCH_UNITS = ROOT / "deploy" / "vps" / "systemd"
RUNBOOKS = ROOT / "docs" / "execution" / "runbooks"
SERVICES = ("edgelab-exec.service", "edgelab-exec-backup.service", "edgelab-exec-health.service")
EXEC_PATHS = ("/var/lib/market-edge-lab-exec", "/var/lib/market-edge-lab-exec-status", "/var/lib/market-edge-lab-exec-backup")
JOURNAL = "/var/lib/market-edge-lab-exec/journal/kalshi.execution.sqlite3"


def _parse(path: Path) -> dict[tuple[str, str], list[str]]:
    values: dict[tuple[str, str], list[str]] = {}
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault((section, key), []).append(value)
    return values


def _memory(value: str) -> int:
    m = re.fullmatch(r"(\d+)([KMG])", value)
    assert m, value
    return int(m.group(1)) * {"K": 1, "M": 1024, "G": 1024 * 1024}[m.group(2)]


def _one(unit: dict, key: str, section: str = "Service") -> str:
    values = unit.get((section, key))
    assert values is not None and len(values) == 1, (key, values)
    return values[0]


def test_exactly_these_units_ship_and_none_is_a_timer_or_trigger():
    assert sorted(p.name for p in UNITS.iterdir()) == sorted((*SERVICES, "edgelab-exec.slice"))
    triggers = [p for p in ROOT.joinpath("deploy").rglob("*") if p.suffix in (".timer", ".socket", ".path")
                and "edgelab-exec" in p.name]
    assert triggers == []


@pytest.mark.parametrize("name", (*SERVICES, "edgelab-exec.slice"))
def test_no_executor_unit_can_be_enabled(name):
    """No [Install] section: `systemctl enable` has nothing to enable, even after a copy."""
    text = (UNITS / name).read_text(encoding="utf-8")
    assert not re.search(r"^\s*\[Install\]", text, re.M)
    assert not re.search(r"^\s*(WantedBy|RequiredBy|UpheldBy|Alias|Also)\s*=", text, re.M)
    assert "\r" not in text  # LF only: parsed on Linux


@pytest.mark.parametrize("name", SERVICES)
def test_each_service_runs_as_the_executor_user_without_privileges(name):
    u = _parse(UNITS / name)
    assert _one(u, "User") == "edgelab-exec" and _one(u, "Group") == "edgelab-exec"
    assert _one(u, "Slice") == "edgelab-exec.slice"
    for key, value in (("NoNewPrivileges", "yes"), ("ProtectSystem", "strict"), ("ProtectHome", "yes"),
                       ("PrivateTmp", "yes"), ("PrivateDevices", "yes"), ("CapabilityBoundingSet", ""),
                       ("AmbientCapabilities", ""), ("RestrictSUIDSGID", "yes"), ("RestrictNamespaces", "yes"),
                       ("LockPersonality", "yes"), ("ProtectKernelTunables", "yes"), ("ProtectKernelModules", "yes"),
                       ("ProtectControlGroups", "yes"), ("ProtectProc", "invisible"), ("UMask", "0077"),
                       ("SystemCallArchitectures", "native")):
        assert _one(u, key) == value, (name, key)
    assert u[("Service", "SystemCallFilter")] == ["@system-service", "~@privileged"]


@pytest.mark.parametrize("name", SERVICES)
def test_no_network_no_environment_and_no_key_today(name):
    u = _parse(UNITS / name)
    assert _one(u, "RestrictAddressFamilies") == "AF_UNIX"
    assert _one(u, "IPAddressDeny") == "any" and ("Service", "IPAddressAllow") not in u
    for key in ("EnvironmentFile", "Environment", "PassEnvironment", "LoadCredential", "LoadCredentialEncrypted",
                "SetCredential", "SetCredentialEncrypted", "ImportCredential"):
        assert ("Service", key) not in u, (name, key)
    text = (UNITS / name).read_text(encoding="utf-8")
    assert "secrets.env" not in text and "--key" not in text


@pytest.mark.parametrize("name", SERVICES)
def test_writes_stay_inside_executor_paths_and_research_and_secrets_are_invisible(name):
    u = _parse(UNITS / name)
    writable = _one(u, "ReadWritePaths").split()
    assert writable
    for p in writable:
        assert any(p == e or p.startswith(e + "/") for e in EXEC_PATHS), (name, p)
    hidden = set(_one(u, "InaccessiblePaths").split())
    assert {"-/var/lib/market-edge-lab", "-/etc/market-edge-lab", "-/etc/market-edge-lab-exec/credentials"} <= hidden
    assert not any(p.lstrip("-") in writable for p in hidden)


def test_the_executor_cannot_reach_its_own_backups_and_the_backup_job_cannot_reach_the_status():
    executor = set(_one(_parse(UNITS / "edgelab-exec.service"), "InaccessiblePaths").split())
    assert "-/var/lib/market-edge-lab-exec-backup" in executor
    backup = _parse(UNITS / "edgelab-exec-backup.service")
    assert _one(backup, "ReadWritePaths").split() == ["/var/lib/market-edge-lab-exec/journal",
                                                       "/var/lib/market-edge-lab-exec-backup"]
    assert _one(_parse(UNITS / "edgelab-exec-health.service"), "ReadWritePaths").split() == [
        "/var/lib/market-edge-lab-exec/journal"]


def test_resources_are_capped_inside_a_slice_that_leaves_the_host_headroom():
    slice_ = _parse(UNITS / "edgelab-exec.slice")
    cap = _memory(_one(slice_, "MemoryMax", "Slice"))
    assert _one(slice_, "MemorySwapMax", "Slice") == "0" and _one(slice_, "TasksMax", "Slice") == "64"
    for name in SERVICES:
        u = _parse(UNITS / name)
        high, top = _memory(_one(u, "MemoryHigh")), _memory(_one(u, "MemoryMax"))
        assert high < top <= cap, name
        assert _one(u, "MemorySwapMax") == "0" and int(_one(u, "TasksMax")) <= 64
        assert re.fullmatch(r"\d+%", _one(u, "CPUQuota")) and int(_one(u, "CPUQuota")[:-1]) <= 50
    research = _memory(_one(_parse(RESEARCH_UNITS / "edgelab.slice"), "MemoryMax", "Slice"))
    # Both slices together stay far below the VPS's lowest observed available memory, 3.9 GB of 7.9 GB, no swap
    # (docs/deploy/VPS_REVIEW_2026-09-22.md).
    assert cap + research <= 1200 * 1024


@pytest.mark.parametrize("name", SERVICES)
def test_a_failure_reaches_the_existing_alert_path(name):
    assert _parse(UNITS / name)[("Unit", "OnFailure")] == ["edgelab-alert@%n.service"]
    assert (RESEARCH_UNITS / "edgelab-alert@.service").is_file()


def _exec_args(name: str) -> list[str]:
    argv = shlex.split(_one(_parse(UNITS / name), "ExecStart"))
    assert argv[:3] == ["/opt/market-edge-lab-exec/venv/bin/python", "-m", "edge_lab.execution.ops"], argv
    return argv[3:]


@pytest.mark.parametrize("name,command", [("edgelab-exec.service", "run"), ("edgelab-exec-backup.service", "backup"),
                                          ("edgelab-exec-health.service", "health")])
def test_every_exec_start_is_a_real_ops_command_on_the_one_journal_path(name, command):
    args = _exec_args(name)
    parsed = ops._parser().parse_args(args)
    assert parsed.command == command
    assert parsed.journal == JOURNAL
    if command == "backup":
        assert parsed.out.startswith("/var/lib/market-edge-lab-exec-backup/")
        assert "/var/lib/market-edge-lab/backups" not in " ".join(args)  # never the research backups
    if command == "health":
        assert parsed.backup_root == "/var/lib/market-edge-lab-exec-backup/journal"
        assert parsed.status_file == "/var/lib/market-edge-lab-exec-status/execution_status.json"


def test_the_executor_restarts_on_failure_but_never_loops_on_its_refusal():
    u = _parse(UNITS / "edgelab-exec.service")
    assert _one(u, "Restart") == "on-failure"
    assert _one(u, "RestartPreventExitStatus") == str(ops.EXIT_NO_RUNNER) == "78"
    assert int(_one(u, "StartLimitBurst", "Unit")) <= 3 and _one(u, "Type") == "simple"


def test_nothing_in_the_repository_installs_starts_or_enables_an_executor_unit():
    install = (ROOT / "deploy" / "vps" / "install.sh").read_text(encoding="utf-8")
    assert "deploy/executor" not in install and "edgelab-exec" not in install
    assert '"$APP_ROOT/app/deploy/vps/systemd/"edgelab-*' in install  # the installer copies the research directory only
    hits = []
    for base in (ROOT / "deploy", ROOT / "scripts", ROOT / ".github"):
        for path in base.rglob("*"):
            if path.is_file() and UNITS not in path.parents and path.suffix not in (".md",):
                text = path.read_text(encoding="utf-8", errors="replace")
                if "edgelab-exec" in text or "deploy/executor" in text:
                    hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def _runbooks() -> list[Path]:
    return sorted(p for p in RUNBOOKS.glob("*.md") if p.name != "README.md")


def test_every_runbook_names_its_approval_gate():
    books = _runbooks()
    assert {p.name for p in books} >= {"INSTALL.md", "START_DISARMED.md", "BACKUP_AND_RESTORE.md", "KEYS.md",
                                       "SECRET_SCAN.md", "MIGRATION_AND_ROLLBACK.md", "INCIDENT_RESPONSE.md"}
    for path in books:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^\*\*Approval gate:\*\*\s*\S", text, re.M), path.name
    index = (RUNBOOKS / "README.md").read_text(encoding="utf-8")
    assert all(p.name in index for p in books)


def test_runbooks_never_enable_an_executor_unit_and_never_restore_over_the_live_journal():
    for path in _runbooks():
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"systemctl\s+enable\b[^\n]*edgelab-exec", line), (path.name, line)
            if " restore " in f" {line} " and "--target" in line:
                assert JOURNAL not in line.split("--target", 1)[1].split()[0], (path.name, line)


def test_the_ci_workflow_uploads_no_artifacts_and_reads_no_secrets():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "upload-artifact" not in text and "secrets." not in text and "pull_request_target" not in text
        assert re.search(r"^permissions:\s*\n\s+contents: read\s*$", text, re.M), path.name
