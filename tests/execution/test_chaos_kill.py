"""#160 package P: process death at random points, then restart and full invariant checks. FIXTURE only.

For each seed a child process (`chaos_support.kill_child_main`) boots a real orchestrator on the shared journal file
and the pickled fake-venue state, runs workload cycles with the operator arming, and dies with `os._exit(19)` at a
seeded kill point: just before the COMMIT of any journal transaction (the transaction is lost), or around any venue
write (before the venue acts, or after it acted and before the reply is recorded). The venue's state at the moment of
death is kept: the venue outlives our process.

The run is deterministic, so a first child on a copy of the store counts the kill points of the plan; the kill point
is then drawn uniformly from them. The parent restarts on the same store and checks:

- the restart is DISARMED and the store already satisfies every global invariant (`check_invariants`) before any
  cycle runs;
- after quiet cycles (the operator re-arms after a COMPLETE one) every attempt is terminal, each unknown one resolved
  from the venue listing and never re-sent;
- further workload cycles keep every invariant.

Kill points around venue writes are a few percent of all points, so besides N seeds over every point, N/2 seeds each
draw only among the before-send and only among the after-send points. Seeds and kill points are in the assertion
messages and printed (`-s`). Scale: EDGE_LAB_KILL_SEEDS (default N = 4; EDGE_LAB_CHAOS_SCALE=full runs 60).
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess

import pytest

import chaos_support as cs
from edge_lab.execution import control as ctl

N = cs.knob("KILL_SEEDS", 4, 60)
# (seed, kind of kill point): any point, then points around venue writes only (they are a few percent of all points).
CASES = ([(s, None) for s in range(101, 101 + N)] + [(s, "before_send") for s in range(201, 201 + max(1, N // 2))]
         + [(s, "after_send") for s in range(301, 301 + max(1, N // 2))])
CHILD_CYCLES = 3


def _child(rig: cs.Rig, journal, state, plan: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cs.kill_command(journal, state, plan), capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("seed,label", CASES)
def test_a_kill_at_a_random_point_then_restart_keeps_every_invariant(tmp_path, seed, label):
    rng = random.Random(seed)
    rig = cs.Rig(tmp_path)
    rig.warm()
    workload = cs.Workload(seed)
    for _ in range(2):
        rig.step(workload)
    state = tmp_path / "venue.pickle"
    rig.adapter.save(str(state))
    rig.journal.close()  # this process's orchestrator is abandoned; the child takes over the store
    plan = {"seed": seed, "kill_at": 0, "cycles": CHILD_CYCLES, "at": cs.at_text(rig.clock),
            "markets": list(rig.markets), "label": label}

    dry = tmp_path / "dry"
    dry.mkdir()
    shutil.copy(rig.jpath, dry / rig.jpath.name)
    shutil.copy(state, dry / state.name)
    counted = _child(rig, dry / rig.jpath.name, dry / state.name, plan)
    assert counted.returncode == 3, counted.stderr[-3000:]
    points = json.loads(re.search(r"SURVIVED (\{.*\})", counted.stdout).group(1))[label or "all"]

    plan["kill_at"] = rng.randint(1, points)
    proc = _child(rig, rig.jpath, state, plan)
    where = f"seed={seed} label={label} kill_at={plan['kill_at']}/{points}: {proc.stdout.strip()[-200:]}"
    assert proc.returncode == 19 and "KILLED" in proc.stdout, f"{where}\n{proc.stderr[-3000:]}"
    print(where)  # the seed, the kill point and where it fell (shown with -s)

    adapter = cs.ChaosAdapter.load(str(state))  # the venue as it was when the child died
    adapter.journal_path, adapter.state_path = str(rig.jpath), None
    rig.adapter, rig.send, rig.clock = adapter, adapter, adapter.clock
    rig.clock.advance(60)
    rig.restart()  # asserts DISARMED: a restart never re-arms itself
    cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
    rig.settle(10)
    for _ in range(3):
        rig.step(workload)
    assert rig.orch.state.mode is ctl.Mode.BOUNDED_AUTO, where
    assert len(rig.adapter.creates) == len(set(rig.adapter.creates)), where
