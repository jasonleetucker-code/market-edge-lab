"""Executor health for the alert path: liveness and reconciliation health, kept apart (#160 package O, ADR 0048).

Pure: it judges the sanitized status export (`status_export`, `execution_status.json`) and a few facts the caller
reads (the newest backup's time, the chain anchor check, free disk space). It sends nothing and changes nothing.

**Liveness is not health.** A process can be alive and wrong (cycling, but its last reconciliation failed), or dead
with a clean last state. So there are two separate verdicts, computed from disjoint parts of the export:
- **Liveness** (`LIVENESS_SECTIONS`: `generated_at_utc`, `service`, `cycles`): did the executor write its status and
  finish a cycle recently? LIVE, STALE, STOPPED (a shutdown was recorded after the last start), NEVER_STARTED or
  UNKNOWN.
- **Reconciliation health** (`RECONCILIATION_SECTIONS`: `journal`, `control`, `attempts`, `account`): is the
  executor's view of the account trustworthy now? HEALTHY only when every one of these holds: the journal opens and
  its chain verifies; the last reconciliation was COMPLETE and is recent; no incident is open; no attempt has an
  unknown outcome; no reservation is quarantined; the latest snapshot is consistent. Otherwise DEGRADED with every
  reason, or UNKNOWN when the export cannot say.

Neither verdict reads the other's sections (a test perturbs each section and checks the other verdict is unchanged),
so a LIVE process never makes reconciliation look healthy, and a recent COMPLETE reconciliation never makes a dead
process look alive. Reconciliation ages against the caller's clock, so a stale export ages its reconciliation too.

Backups and disk are judged separately again (`backup_verdict`, `disk_verdict`). `exit_code` sets one bit per
failing verdict, so the alert names what failed: 1 liveness, 2 reconciliation, 4 backup, 8 disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .model import parse_utc_text, utc_text
from .status_export import MAX_BYTES as STATUS_MAX_BYTES
from .status_export import SCHEMA as STATUS_SCHEMA

HEALTH_SCHEMA = "edge-lab-execution-health/1"
LIVENESS_SECTIONS = ("generated_at_utc", "service", "cycles")
RECONCILIATION_SECTIONS = ("journal", "control", "attempts", "account")
LIVENESS_BIT, RECONCILIATION_BIT, BACKUP_BIT, DISK_BIT = 1, 2, 4, 8


class Liveness(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    STOPPED = "STOPPED"
    NEVER_STARTED = "NEVER_STARTED"
    UNKNOWN = "UNKNOWN"


class ReconciliationHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class BackupHealth(str, Enum):
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"
    ANCHOR_BROKEN = "ANCHOR_BROKEN"  # the live chain no longer contains the newest backup's head event


class DiskHealth(str, Enum):
    OK = "OK"
    DISK_PRESSURE = "DISK_PRESSURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HealthLimits:
    """Bounds for the verdicts. The defaults fit a one-minute cycle; the unit passes the deployed values."""

    max_status_age: timedelta = timedelta(minutes=5)
    max_cycle_gap: timedelta = timedelta(minutes=5)
    max_reconciliation_age: timedelta = timedelta(minutes=10)
    max_backup_age: timedelta = timedelta(hours=26)
    min_free_bytes: int = 2 * 1024 ** 3

    def __post_init__(self) -> None:
        for name in ("max_status_age", "max_cycle_gap", "max_reconciliation_age", "max_backup_age"):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise ValueError(f"{name} must be a positive timedelta")
        if isinstance(self.min_free_bytes, bool) or not isinstance(self.min_free_bytes, int) or self.min_free_bytes < 0:
            raise ValueError("min_free_bytes must be a non-negative int")


@dataclass(frozen=True)
class Verdict:
    state: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reasons": list(self.reasons)}


def _age(text: Any, now: datetime) -> timedelta | None:
    if not isinstance(text, str):
        return None
    try:
        return now - parse_utc_text(text)
    except ValueError:
        return None


def _section(status: Mapping[str, Any], name: str) -> Any:
    return status.get(name) if isinstance(status, Mapping) else None


def liveness(status: Mapping[str, Any] | None, *, now: datetime, limits: HealthLimits) -> Verdict:
    """From `LIVENESS_SECTIONS` only."""
    if status is None:
        return Verdict(Liveness.UNKNOWN.value, ("NO_STATUS: no readable status export",))
    service, cycles = _section(status, "service"), _section(status, "cycles")
    generated = _age(_section(status, "generated_at_utc"), now)
    if not isinstance(service, Mapping) or not isinstance(cycles, Mapping) or generated is None:
        return Verdict(Liveness.UNKNOWN.value, ("STATUS_INCOMPLETE: the export holds no service or cycle section",))
    state = service.get("state")
    if state == "NEVER_STARTED":
        return Verdict(Liveness.NEVER_STARTED.value, ("NEVER_STARTED: no start is recorded",))
    if state == "SHUTDOWN_RECORDED":
        return Verdict(Liveness.STOPPED.value, ("STOPPED: a shutdown was recorded after the last start",))
    if state != "STARTED_NO_SHUTDOWN_RECORDED":
        return Verdict(Liveness.UNKNOWN.value, (f"SERVICE_STATE_UNKNOWN: {state!r}",))
    reasons = []
    if generated > limits.max_status_age:
        reasons.append(f"STATUS_STALE: written {int(generated.total_seconds())} s ago")
    if generated < -limits.max_status_age:
        reasons.append("STATUS_IN_FUTURE: the export is stamped ahead of this clock")
    cycle_age = _age(cycles.get("last_recorded_at_utc"), now)
    if cycle_age is None:
        reasons.append("NO_CYCLE: started, but no cycle is recorded")
    elif cycle_age > limits.max_cycle_gap:
        reasons.append(f"CYCLE_STALE: last cycle {int(cycle_age.total_seconds())} s ago")
    return Verdict(Liveness.STALE.value if reasons else Liveness.LIVE.value, tuple(reasons))


def reconciliation(status: Mapping[str, Any] | None, *, now: datetime, limits: HealthLimits) -> Verdict:
    """From `RECONCILIATION_SECTIONS` only."""
    if status is None:
        return Verdict(ReconciliationHealth.UNKNOWN.value, ("NO_STATUS: no readable status export",))
    journal, control = _section(status, "journal"), _section(status, "control")
    attempts, account = _section(status, "attempts"), _section(status, "account")
    if not isinstance(journal, Mapping):
        return Verdict(ReconciliationHealth.UNKNOWN.value, ("STATUS_INCOMPLETE: no journal section",))
    if journal.get("state") != "OK":
        return Verdict(ReconciliationHealth.UNKNOWN.value,
                       (f"JOURNAL_{journal.get('state')}: the executor's journal could not be read",))
    if not isinstance(control, Mapping) or not isinstance(attempts, Mapping) or not isinstance(account, Mapping):
        return Verdict(ReconciliationHealth.UNKNOWN.value, ("STATUS_INCOMPLETE: control, attempts or account missing",))
    reasons = []
    if journal.get("chain_ok") is not True:
        reasons.append("CHAIN_NOT_VERIFIED: the journal's hash chain did not verify")
    last = control.get("last_reconciliation")
    if not isinstance(last, Mapping):
        reasons.append("NEVER_RECONCILED: no reconciliation is recorded")
    else:
        if last.get("status") != "COMPLETE":
            reasons.append(f"RECONCILIATION_{last.get('status')}: the last reconciliation was not COMPLETE")
        age = _age(last.get("at_utc"), now)
        if age is None:
            reasons.append("RECONCILIATION_TIME_UNKNOWN")
        elif age > limits.max_reconciliation_age:
            reasons.append(f"RECONCILIATION_STALE: last observed {int(age.total_seconds())} s ago")
    incidents = control.get("open_incidents")
    if not isinstance(incidents, list):
        reasons.append("INCIDENTS_UNKNOWN")
    elif incidents:
        reasons.append(f"OPEN_INCIDENTS: {len(incidents)}")
    by_state = attempts.get("by_state")
    unknown = by_state.get("OUTCOME_UNKNOWN") if isinstance(by_state, Mapping) else None
    if not isinstance(unknown, int) or isinstance(unknown, bool):
        reasons.append("ATTEMPT_STATES_UNKNOWN")
    elif unknown:
        reasons.append(f"OUTCOME_UNKNOWN_ATTEMPTS: {unknown}")
    reservations = account.get("reservations")
    quarantined = reservations.get("quarantined_count") if isinstance(reservations, Mapping) else None
    if not isinstance(quarantined, int) or isinstance(quarantined, bool):
        reasons.append("RESERVATIONS_UNKNOWN")
    elif quarantined:
        reasons.append(f"QUARANTINED_RESERVATIONS: {quarantined}")
    snapshot = account.get("snapshot")
    if not isinstance(snapshot, Mapping):
        reasons.append("NO_SNAPSHOT: no account snapshot is recorded")
    elif snapshot.get("consistent") is not True:
        reasons.append("SNAPSHOT_INCONSISTENT: the latest account snapshot is not consistent")
    return Verdict(ReconciliationHealth.DEGRADED.value if reasons else ReconciliationHealth.HEALTHY.value,
                   tuple(reasons))


def backup_verdict(newest_created_at_utc: str | None, *, now: datetime, limits: HealthLimits,
                   anchor_problems: tuple[str, ...] = ()) -> Verdict:
    if newest_created_at_utc is None:
        return Verdict(BackupHealth.MISSING.value, ("NO_COMPLETE_BACKUP",))
    if anchor_problems:
        return Verdict(BackupHealth.ANCHOR_BROKEN.value, tuple(anchor_problems))
    age = _age(newest_created_at_utc, now)
    if age is None or age > limits.max_backup_age:
        shown = "unknown" if age is None else f"{int(age.total_seconds())} s"
        return Verdict(BackupHealth.STALE.value, (f"BACKUP_STALE: newest complete backup is {shown} old",))
    return Verdict(BackupHealth.OK.value)


def disk_verdict(free_bytes: int | None, *, limits: HealthLimits) -> Verdict:
    if free_bytes is None:
        return Verdict(DiskHealth.UNKNOWN.value, ("FREE_SPACE_UNKNOWN",))
    if free_bytes < limits.min_free_bytes:
        return Verdict(DiskHealth.DISK_PRESSURE.value,
                       (f"DISK_PRESSURE: {free_bytes} bytes free, {limits.min_free_bytes} required",))
    return Verdict(DiskHealth.OK.value)


def load_status(path: str | Path) -> tuple[Mapping[str, Any] | None, str | None]:
    """The export at `path`, or (None, reason). Bounded: a file larger than the export's own bound is refused."""
    p = Path(path)
    try:
        if p.is_symlink() or not p.is_file():
            return None, "NO_STATUS_FILE"
        if p.stat().st_size > STATUS_MAX_BYTES:
            return None, "STATUS_FILE_TOO_LARGE"
        status = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return None, f"STATUS_UNREADABLE: {type(exc).__name__}"
    if not isinstance(status, dict) or status.get("schema") != STATUS_SCHEMA:
        return None, "STATUS_FOREIGN_SCHEMA"
    return status, None


def report(status: Mapping[str, Any] | None, *, now: datetime, limits: HealthLimits,
           newest_backup_utc: str | None = None, anchor_problems: tuple[str, ...] = (),
           free_bytes: int | None = None, status_problem: str | None = None) -> dict[str, Any]:
    """Every verdict, each on its own, and the exit code with one bit per failing verdict."""
    live = liveness(status, now=now, limits=limits)
    recon = reconciliation(status, now=now, limits=limits)
    backup = backup_verdict(newest_backup_utc, now=now, limits=limits, anchor_problems=anchor_problems)
    disk = disk_verdict(free_bytes, limits=limits)
    code = (LIVENESS_BIT * (live.state != Liveness.LIVE.value)
            | RECONCILIATION_BIT * (recon.state != ReconciliationHealth.HEALTHY.value)
            | BACKUP_BIT * (backup.state != BackupHealth.OK.value)
            | DISK_BIT * (disk.state != DiskHealth.OK.value))
    return {"schema": HEALTH_SCHEMA, "at_utc": utc_text(now), "status_problem": status_problem,
            "environment": None if status is None else status.get("environment"),
            "liveness": live.to_dict(), "reconciliation": recon.to_dict(), "backup": backup.to_dict(),
            "disk": disk.to_dict(), "exit_code": code}
