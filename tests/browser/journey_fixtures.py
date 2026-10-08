"""FIXTURE execution journals and their status exports, for the operator journeys (J1, J5, J6). Tests only.

Each scenario runs the REAL orchestrator (`tests/execution/test_orchestrator_harness.py`: a FakeVenue-backed `send`,
a TEST-issued grant and explicit TEST limits) against a fresh journal, then writes the projection with the real
`execution.status_export`. Nothing leaves the process; no real account, key or venue is involved. Every figure is a
FIXTURE figure from the fake venue.

Scenarios:
- `populated`: armed BOUNDED_AUTO under the TEST grant; an IOC entry filled and released, a GTC entry partly filled
  and resting, a full reduction, a settled market, and one order whose reply was lost (OUTCOME_UNKNOWN).
- `paused`: the same history, then a market latch, a failed account read that disarms with an incident, and an
  operator's refused re-arm (the incident not named): DISARMED, reconciliation FAILED.
- `idle`: one boot and one COMPLETE read, never armed: no attempt, an empty FIXTURE account.
- `no_config`: `idle` exported without the orchestrator's config: limits, bounds and grants unknown.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "tests" / "execution"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import test_orchestrator_harness as h  # noqa: E402
from edge_lab.execution import control as ctl  # noqa: E402
from edge_lab.execution import status_export as se  # noqa: E402
from edge_lab.execution.fake_venue import Fault  # noqa: E402
from edge_lab.execution.journal import ExecutionJournal  # noqa: E402
from edge_lab.execution.lifecycle import Operation  # noqa: E402
from edge_lab.execution.model import Side  # noqa: E402

B70, B72, B74 = h.MARKETS
SCENARIOS = ("populated", "paused", "idle", "no_config")


def _armed(journal, adapter, clock):
    orch, _ = h.build(journal, adapter)
    orch.run_cycle()
    assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    return orch


def _history(journal, adapter, clock):
    orch = _armed(journal, adapter, clock)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45", qty="3"))
    orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.44", qty="8", tif="good_till_canceled"))
    orch.submit_signal(h.signal("s3", B74, at=clock(), limit="0.46", qty="2"))
    orch.run_cycle()
    for _ in range(2):
        clock.advance(60)
        orch.run_cycle()
    orch.submit_signal(h.signal("s4", B70, at=clock(), kind="EXIT", limit="0.41", qty="3"))
    orch.run_cycle()
    clock.advance(60)
    adapter.settle(B74, Side.YES)
    clock.advance(60)
    orch.run_cycle()
    clock.advance(60)
    orch.run_cycle()
    return orch


def build(scenario: str, root: Path, *, now: datetime | None = None) -> tuple[Path, datetime]:
    """Run `scenario` into `root` and write `root/execution_status.json`. Returns (export path, export time)."""
    if scenario not in SCENARIOS:
        raise ValueError(scenario)
    root.mkdir(parents=True, exist_ok=True)
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    path = root / "fixture.execution.sqlite3"
    if path.exists():
        raise FileExistsError(f"{path} exists: each scenario needs a fresh directory")
    journal = ExecutionJournal.open(path)
    try:
        config = h.config()
        if scenario in ("idle", "no_config"):
            orch, _ = h.build(journal, adapter)
            orch.run_cycle()
        else:
            orch = _history(journal, adapter, clock)
            if scenario == "populated":
                adapter.venue.inject(Fault.ACCEPT_THEN_TIMEOUT, operation=Operation.NEW_ORDER)
                orch.submit_signal(h.signal("s5", B72, at=clock(), limit="0.45", qty="1"))
                orch.run_cycle()
            else:
                orch.set_latch(ctl.LatchScope.MARKET, B72, "operator: thin book")
                adapter.reads_fail = True
                clock.advance(60)
                orch.run_cycle()
                adapter.reads_fail = False
                orch.request_arm(ctl.ArmRequest(ctl.Mode.BOUNDED_AUTO, "owner", (), h.m.utc_text(clock()),
                                                h.grant().digest()))
        at = now or clock() + timedelta(seconds=30)
        status = se.build_status(journal, h.SCOPE, now=at, config=None if scenario == "no_config" else config)
    finally:
        journal.close()
    out = se.write_status(status, root / se.FILENAME)
    return out, at


def missing_journal(root: Path, *, now: datetime) -> Path:
    """The export for a journal file that does not exist (NO_JOURNAL)."""
    root.mkdir(parents=True, exist_ok=True)
    status = se.status_for_path(root / "absent.execution.sqlite3", h.SCOPE, now=now)
    return se.write_status(status, root / se.FILENAME)
