"""Executor health (#160 package O, ADR 0048): liveness and reconciliation health are separate verdicts from disjoint
parts of the real status export. FIXTURE only: the exports come from the real orchestrator against the test
FakeVenue."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import health as hl
from edge_lab.execution import status_export as se
from edge_lab.execution.journal import ExecutionJournal

LIMITS = hl.HealthLimits()


def _export(tmp_path: Path, *, reads_fail: bool = False, cycles: int = 1, shutdown: bool = False):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(tmp_path / "k.execution.sqlite3")
    orch, _ = h.build(journal, adapter)
    for _ in range(cycles):
        adapter.reads_fail = reads_fail
        orch.run_cycle()
        clock.advance(60)
    if shutdown:
        orch.shutdown(operator_ref="owner", reason="planned stop")
    status = json.loads(se.render(se.build_status(journal, h.SCOPE, now=clock(), config=h.config())))
    journal.close()
    return status, clock


@pytest.fixture(scope="module")
def healthy(tmp_path_factory):
    return _export(tmp_path_factory.mktemp("healthy"))


def test_a_cycling_reconciled_executor_is_live_and_healthy(healthy):
    status, clock = healthy
    report = hl.report(status, now=clock(), limits=LIMITS, newest_backup_utc=status["generated_at_utc"],
                       free_bytes=10 * 1024 ** 3)
    assert report["liveness"] == {"state": "LIVE", "reasons": []}
    assert report["reconciliation"] == {"state": "HEALTHY", "reasons": []}
    assert report["backup"]["state"] == "OK" and report["disk"]["state"] == "OK" and report["exit_code"] == 0


def test_alive_but_not_reconciled_is_live_and_degraded(tmp_path):
    status, clock = _export(tmp_path, reads_fail=True)
    report = hl.report(status, now=clock(), limits=LIMITS)
    assert report["liveness"]["state"] == "LIVE"
    assert report["reconciliation"]["state"] == "DEGRADED"
    assert any(r.startswith("RECONCILIATION_") for r in report["reconciliation"]["reasons"])
    assert report["exit_code"] & hl.RECONCILIATION_BIT and not report["exit_code"] & hl.LIVENESS_BIT


def test_dead_with_a_clean_last_reconciliation_is_stale_not_healthy_liveness(healthy):
    status, clock = healthy
    later = clock() + timedelta(minutes=6)  # past the cycle and status bounds, inside the reconciliation bound
    report = hl.report(status, now=later, limits=LIMITS)
    assert report["liveness"]["state"] == "STALE" and report["reconciliation"]["state"] == "HEALTHY"
    assert report["exit_code"] & hl.LIVENESS_BIT and not report["exit_code"] & hl.RECONCILIATION_BIT
    much_later = clock() + timedelta(hours=1)  # a stale export ages its reconciliation too
    assert any(r.startswith("RECONCILIATION_STALE") for r in hl.reconciliation(status, now=much_later, limits=LIMITS).reasons)


def test_a_recorded_shutdown_is_stopped(tmp_path):
    status, clock = _export(tmp_path, shutdown=True)
    assert hl.liveness(status, now=clock(), limits=LIMITS).state == "STOPPED"


# Each perturbation touches exactly one verdict's sections.
LIVENESS_PERTURBATIONS = {
    "status stale": lambda s: s.update(generated_at_utc="2026-10-07T00:00:00+00:00"),
    "status in future": lambda s: s.update(generated_at_utc="2027-01-01T00:00:00+00:00"),
    "no service": lambda s: s.pop("service"),
    "never started": lambda s: s["service"].update(state="NEVER_STARTED"),
    "shutdown": lambda s: s["service"].update(state="SHUTDOWN_RECORDED"),
    "odd state": lambda s: s["service"].update(state="WHATEVER"),
    "cycle stale": lambda s: s["cycles"].update(last_recorded_at_utc="2026-10-07T00:00:00+00:00"),
    "no cycle": lambda s: s["cycles"].update(last_recorded_at_utc=None),
    "no cycles section": lambda s: s.pop("cycles"),
}
RECONCILIATION_PERTURBATIONS = {
    "journal error": lambda s: s["journal"].update(state="ERROR"),
    "chain broken": lambda s: s["journal"].update(chain_ok=False),
    "last FAILED": lambda s: s["control"]["last_reconciliation"].update(status="FAILED"),
    "last PARTIAL": lambda s: s["control"]["last_reconciliation"].update(status="PARTIAL"),
    "reconciliation stale": lambda s: s["control"]["last_reconciliation"].update(at_utc="2026-10-07T00:00:00+00:00"),
    "never reconciled": lambda s: s["control"].update(last_reconciliation=None),
    "incident": lambda s: s["control"].update(open_incidents=[{"incident_id": "x"}]),
    "unknown outcome": lambda s: s["attempts"]["by_state"].update(OUTCOME_UNKNOWN=1),
    "quarantine": lambda s: s["account"]["reservations"].update(quarantined_count=2),
    "inconsistent snapshot": lambda s: s["account"]["snapshot"].update(consistent=False),
    "no snapshot": lambda s: s["account"].update(snapshot=None),
    "no attempts section": lambda s: s.pop("attempts"),
}


@pytest.mark.parametrize("name", sorted(LIVENESS_PERTURBATIONS))
def test_a_liveness_change_never_moves_reconciliation_health(healthy, name):
    status, clock = healthy
    changed = copy.deepcopy(status)
    LIVENESS_PERTURBATIONS[name](changed)
    assert hl.liveness(changed, now=clock(), limits=LIMITS).state != "LIVE"
    assert hl.reconciliation(changed, now=clock(), limits=LIMITS) == hl.reconciliation(status, now=clock(), limits=LIMITS)


@pytest.mark.parametrize("name", sorted(RECONCILIATION_PERTURBATIONS))
def test_a_reconciliation_change_never_moves_liveness(healthy, name):
    status, clock = healthy
    changed = copy.deepcopy(status)
    RECONCILIATION_PERTURBATIONS[name](changed)
    assert hl.reconciliation(changed, now=clock(), limits=LIMITS).state != "HEALTHY"
    assert hl.liveness(changed, now=clock(), limits=LIMITS) == hl.liveness(status, now=clock(), limits=LIMITS)


def test_the_two_verdicts_read_disjoint_sections_of_the_export(healthy):
    status, clock = healthy
    assert not set(hl.LIVENESS_SECTIONS) & set(hl.RECONCILIATION_SECTIONS)
    for key in status:
        dropped = {k: v for k, v in status.items() if k != key}
        if key not in hl.LIVENESS_SECTIONS:
            assert hl.liveness(dropped, now=clock(), limits=LIMITS) == hl.liveness(status, now=clock(), limits=LIMITS), key
        if key not in hl.RECONCILIATION_SECTIONS:
            assert hl.reconciliation(dropped, now=clock(), limits=LIMITS) == \
                hl.reconciliation(status, now=clock(), limits=LIMITS), key


def test_no_status_is_unknown_for_both_and_sets_both_bits():
    report = hl.report(None, now=h.T0, limits=LIMITS, status_problem="NO_STATUS_FILE")
    assert report["liveness"]["state"] == "UNKNOWN" and report["reconciliation"]["state"] == "UNKNOWN"
    assert report["exit_code"] == hl.LIVENESS_BIT | hl.RECONCILIATION_BIT | hl.BACKUP_BIT | hl.DISK_BIT


def test_backup_and_disk_verdicts(healthy):
    _, clock = healthy
    now = clock()
    assert hl.backup_verdict(None, now=now, limits=LIMITS).state == "MISSING"
    old = (now - timedelta(hours=27)).isoformat()
    assert hl.backup_verdict(old, now=now, limits=LIMITS).state == "STALE"
    assert hl.backup_verdict(now.isoformat(), now=now, limits=LIMITS, anchor_problems=("LIVE_CHAIN_X",)).state == \
        "ANCHOR_BROKEN"
    assert hl.backup_verdict("not a time", now=now, limits=LIMITS).state == "STALE"
    assert hl.disk_verdict(None, limits=LIMITS).state == "UNKNOWN"
    assert hl.disk_verdict(LIMITS.min_free_bytes - 1, limits=LIMITS).state == "DISK_PRESSURE"
    assert hl.disk_verdict(LIMITS.min_free_bytes, limits=LIMITS).state == "OK"


def test_load_status_is_bounded_and_refuses_foreign_files(healthy, tmp_path):
    status, _ = healthy
    good = tmp_path / se.FILENAME
    good.write_text(json.dumps(status), encoding="utf-8")
    assert hl.load_status(good) == (status, None)
    assert hl.load_status(tmp_path / "missing.json") == (None, "NO_STATUS_FILE")
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (se.MAX_BYTES + 1))
    assert hl.load_status(big) == (None, "STATUS_FILE_TOO_LARGE")
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({**status, "schema": "edge-lab-execution-status/0"}), encoding="utf-8")
    assert hl.load_status(foreign) == (None, "STATUS_FOREIGN_SCHEMA")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert hl.load_status(broken)[1].startswith("STATUS_UNREADABLE")


@pytest.mark.parametrize("kw", [dict(max_status_age=timedelta(0)), dict(max_backup_age=timedelta(seconds=-1)),
                                dict(min_free_bytes=-1), dict(min_free_bytes=True)])
def test_limits_are_validated(kw):
    with pytest.raises(ValueError):
        hl.HealthLimits(**kw)
