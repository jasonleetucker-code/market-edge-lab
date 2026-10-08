"""Demonstration B (docs/strategy/MARKET_V1_ACCEPTANCE.md §5): the autonomous core, offline.

Repeated, seeded fixture cycles through the REAL orchestrator (account reads, snapshot, control, lifecycle, risk
gate, journal and reservations), against a FakeVenue-backed `send` adapter that lives in tests. The scenario has
partial fills (resting GTC orders crossed later, IOC orders a competitor partly beats), conflicting signals, source
loss (signals stop, every read fails, the feed is down), limits hit (the gate's TEST daily new-risk limit and order
rate), injected venue faults (lost replies, timeouts, lost requests, rejects), a settlement, and two process deaths in
a subprocess (`os._exit` after `prepare_attempt` and before the send; after the send and before the reply is
recorded), each followed by a restart on the same journal store.

Everything runs inside one test-issued BOUNDED_AUTO grant. The operator acts only per start and per incident (arm,
naming the open incidents); there is no per-order intervention. The placeholder limits stay untouched: the test passes
explicit TEST limits as typed inputs.

Pass means, checked after every cycle and at the end:
- no duplicated exposure: at most one venue order per client order id, at most one attempt per intent key, and no
  venue order the journal did not prepare;
- inventory never exceeds what fills support: venue positions equal the fills' net, the journal never records more
  fills than the venue, and a COMPLETE snapshot's positions equal the venue's;
- reservations are preserved across each restart, and each unknown attempt is reconciled without a resend;
- only expected incidents (reconciliation loss during the source outage) ever open;
- a safe shutdown leaves resting orders alone; the final `verify_chain()` is OK;
- the run is deterministic: its summary hash for the seed is pinned below.

Run: `python -m pytest tests/execution/test_orchestrator_demo.py -q`.
"""

from __future__ import annotations

import random
from collections import Counter
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution.fake_venue import Fault
from edge_lab.execution.journal import AttemptState, ExecutionJournal
from edge_lab.execution.lifecycle import Operation
from edge_lab.execution_ticket import ObligationState

SEED = 20261007
CYCLES = 60
DEATH_BEFORE_SEND = 14  # the child dies after prepare_attempt, before the venue sees anything
DEATH_AFTER_SEND = 33  # the child dies after the venue acted, before the reply is recorded
OUTAGE = range(20, 24)  # source loss: no signals, every read fails, the feed is down
SETTLE_AT, SETTLE_MARKET = 44, h.MARKETS[2]
EXPECTED_INCIDENTS = ("reconciliation-lost", "reconciliation-failed")
# The pinned summary hash for SEED (recompute deliberately when the scenario or a component changes behaviour).
EXPECTED_HASH = "d331d6eb8b8dc54a4a22e59222c0129b76f90800de2ded0cd9868f0503269184"


def best_yes_ask(adapter: h.VenueAdapter, ticker: str) -> Decimal | None:
    no_bids = adapter.venue.book(ticker)["no"]
    return None if not no_bids else 1 - no_bids[0][0]


def best_yes_bid(adapter: h.VenueAdapter, ticker: str) -> Decimal | None:
    yes_bids = adapter.venue.book(ticker)["yes"]
    return None if not yes_bids else yes_bids[0][0]


class Scenario:
    """The seeded stimulus: liquidity, signals, faults and competitors per cycle."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.n = 0

    def signal_id(self, cycle: int) -> str:
        self.n += 1
        return f"c{cycle:03d}-{self.n:04d}"

    def stimulate(self, cycle: int, orch: o.Orchestrator, adapter: h.VenueAdapter, clock: h.Clock) -> list[str]:
        rng, notes = self.rng, []
        for ticker in h.MARKETS:  # fresh two-sided liquidity
            if ticker in adapter.settled:
                continue
            if rng.random() < 0.6:
                adapter.venue.add_liquidity(ticker, m.Side.NO, f"0.{rng.randint(53, 57)}", rng.randint(1, 5))
            if rng.random() < 0.5:
                adapter.venue.add_liquidity(ticker, m.Side.YES, f"0.{rng.randint(38, 43)}", rng.randint(1, 5))
        live = [t for t in h.MARKETS if t not in adapter.settled]
        if cycle in OUTAGE:
            return ["outage"]
        if rng.random() < 0.12:  # a venue fault on the next new order
            fault = rng.choice([Fault.DROP_ACK, Fault.ACCEPT_THEN_TIMEOUT, Fault.LOSE_REQUEST, Fault.REJECT])
            adapter.venue.inject(fault, operation=Operation.NEW_ORDER,
                                 reason="FIXTURE_REJECT" if fault is Fault.REJECT else None)
            notes.append(f"fault:{fault.value}")
        for _ in range(rng.choice([0, 1, 1, 2])):
            ticker = rng.choice(live)
            ask = best_yes_ask(adapter, ticker)
            if ask is None:
                continue
            gtc = rng.random() < 0.35
            limit = ask - Decimal("0.01") * rng.randint(0, 1) if gtc else ask
            qty = rng.randint(1, 4) + (rng.randint(2, 4) if gtc else 0)
            if not gtc and rng.random() < 0.25:  # someone else lifts part of the offer first: a partial IOC fill
                adapter.competitor.append((ticker, m.Side.YES, f"{1 - adapter.venue.book(ticker)['no'][0][0]:.2f}",
                                           1))
                notes.append(f"competitor:{ticker}")
            orch.submit_signal(h.signal(self.signal_id(cycle), ticker, at=clock(), limit=f"{limit:.2f}",
                                        qty=str(qty), tif="good_till_canceled" if gtc else "immediate_or_cancel"))
        if cycle % 9 == 4 and live:  # conflicting signals: both sides of one market in one cycle
            ticker = rng.choice(live)
            ask = best_yes_ask(adapter, ticker)
            bid = best_yes_bid(adapter, ticker)
            if ask is not None and bid is not None:
                orch.submit_signal(h.signal(self.signal_id(cycle), ticker, at=clock(), side="yes",
                                            limit=f"{ask:.2f}", qty="1"))
                orch.submit_signal(h.signal(self.signal_id(cycle), ticker, at=clock(), side="no",
                                            limit=f"{1 - bid:.2f}", qty="1"))
                notes.append(f"conflict:{ticker}")
        held = sorted((t, q) for (t, s), q in adapter.venue.positions.items() if s is m.Side.YES and q > 0
                      and t not in adapter.settled)
        if held and rng.random() < 0.35:  # an exit through the same chain
            ticker, q = rng.choice(held)
            bid = best_yes_bid(adapter, ticker)
            if bid is not None:
                orch.submit_signal(h.signal(self.signal_id(cycle), ticker, at=clock(), kind="EXIT", limit=f"{bid:.2f}",
                                            qty=str(min(int(q), rng.randint(1, 3)))))
                notes.append(f"exit:{ticker}")
        return notes


# ---------------------------------------------------------------- invariants after every cycle


def check_invariants(journal: ExecutionJournal, adapter: h.VenueAdapter, report: o.CycleReport | None,
                     planned_keys: set[str]) -> None:
    venue = adapter.venue
    orders = venue.list_orders()
    client_ids = [x["client_order_id"] for x in orders]
    assert len(client_ids) == len(set(client_ids)), "a client order id reached the venue twice"
    attempts = {}
    for key in planned_keys:
        found = journal.attempts_for(key)
        assert len(found) <= 1, f"{key} has {len(found)} attempts: a resend"
        for a in found:
            attempts[a.client_order_id] = a
    assert set(client_ids) <= set(attempts), "the venue holds an order the journal never prepared"
    fills = venue.list_fills()
    net: dict = {}
    for x in orders:
        mine = [f for f in fills if f["order_id"] == x["order_id"]]
        assert sum((f["count"] for f in mine), Decimal(0)) == x["fill_count"]
    for f in fills:
        key = (f["ticker"], m.Side(f["side"]))
        net[key] = net.get(key, Decimal(0)) + (f["count"] if f["action"] == "buy" else -f["count"])
    for key, qty in venue.positions.items():
        expected = Decimal(0) if key[0] in adapter.settled else net.get(key, Decimal(0))
        assert qty == expected and qty >= 0, f"{key}: position {qty} is not the fills' net {expected}"
    by_order = {x["client_order_id"]: x for x in orders}
    for r in journal.reservations.held_reservations(h.SCOPE):
        venue_order = by_order.get(r.client_order_id)
        venue_filled = Decimal(0) if venue_order is None else venue_order["fill_count"]
        assert r.filled_quantity <= venue_filled, f"{r.reservation_id} records more fills than the venue"
        assert r.quarantine_reason is None, f"{r.reservation_id} quarantined: {r.quarantine_reason}"
    snap = journal.reservations.latest_snapshot(h.SCOPE)
    if report is not None and report.reconciliation == "COMPLETE":
        assert snap is not None and snap.consistent, snap
        assert dict(snap.positions) == adapter.positions_served, (dict(snap.positions), adapter.positions_served)


def unexpected(incidents) -> list[str]:
    return [i for i in incidents if not i.startswith(EXPECTED_INCIDENTS)]


# ---------------------------------------------------------------- the run


def run_child(tmp_path: Path, jpath: Path, adapter: h.VenueAdapter, clock: h.Clock, die: str,
              sig: o.Signal) -> int:
    state = tmp_path / f"venue-{die}.pickle"
    adapter.save(str(state))
    proc = subprocess.run(h.child_command(jpath, state, clock(), die, sig), capture_output=True, text=True,
                          timeout=180)
    assert proc.returncode in (17, 18), proc.stderr[-3000:]
    return proc.returncode


def run_demo(tmp_path: Path, seed: int = SEED) -> dict:
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    jpath = tmp_path / "demo.execution.sqlite3"
    journal = ExecutionJournal.open(jpath)
    orch, feed = h.build(journal, adapter)
    scenario = Scenario(seed)
    cycles, operator, deaths, restarts, growth = [], [], [], [], []
    planned: set[str] = set()

    def operate(report: o.CycleReport) -> None:
        """The operator: after a COMPLETE cycle in DISARMED, arm BOUNDED_AUTO naming the open incidents. Only the
        expected incident kinds may ever be open."""
        assert not unexpected(orch.state.open_incidents), orch.state.open_incidents
        if report.reconciliation == "COMPLETE" and orch.state.mode is ctl.Mode.DISARMED:
            outcome = h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock)
            assert isinstance(outcome, ctl.ArmAccepted), outcome
            operator.append([report.cycle, "ARM", sorted(outcome.acknowledged_incidents)])

    def restart(kind: str, death_signal: o.Signal) -> None:
        nonlocal journal, orch, feed, adapter
        held_before = {r.reservation_id: r.cash_worst_case
                       for r in journal.reservations.held_reservations(h.SCOPE)}
        journal.close()  # this process's orchestrator is abandoned without shutdown (it is replaced)
        code = run_child(tmp_path, jpath, adapter, clock, kind, death_signal)
        if kind == "after_send":  # the venue acted in the child: take its state
            loaded = h.VenueAdapter.load(str(tmp_path / f"venue-{kind}.pickle"))
            loaded.clock, loaded.die, loaded.state_path = clock, None, None
            adapter = loaded
        clock.advance(60)
        journal = ExecutionJournal.open(jpath)
        key = f"{h.STRATEGY_ID}:{death_signal.signal_id}"
        (died,) = journal.attempts_for(key)
        assert died.state in (AttemptState.PENDING_EGRESS, AttemptState.SENT)  # nobody recorded an outcome
        orch, feed = h.build(journal, adapter)  # restart: boot (Started, DISARMED), new lease, recover
        assert orch.state.mode is ctl.Mode.DISARMED, "a restart never re-arms itself"
        (after,) = journal.attempts_for(key)
        assert after.state is AttemptState.OUTCOME_UNKNOWN
        held_after = {r.reservation_id: r for r in journal.reservations.held_reservations(h.SCOPE)}
        for rid, worst in held_before.items():  # preserved (worst case unchanged), or released on evidence
            if rid in held_after:
                assert held_after[rid].cash_worst_case == worst, rid
            else:
                r = journal.reservations.reservation(rid)  # the child's reconciliation cycle confirmed it
                assert r.state is ObligationState.RELEASED and r.release_reason is not None, r
        assert held_after[died.attempt_id].state is ObligationState.UNKNOWN  # reserved until reconciled
        planned.add(key)
        deaths.append([kind, code, died.attempt_id])
        restarts.append(key)

    for cycle in range(1, CYCLES + 1):
        if cycle in (DEATH_BEFORE_SEND, DEATH_AFTER_SEND):
            kind = "before_send" if cycle == DEATH_BEFORE_SEND else "after_send"
            ticker = h.MARKETS[0]
            ask = best_yes_ask(adapter, ticker) or Decimal("0.45")
            sig = h.signal(f"death-{kind}", ticker, at=clock() + timedelta(seconds=1), limit=f"{ask:.2f}", qty="1")
            restart(kind, sig)
        adapter.reads_fail = feed.down = cycle in OUTAGE
        if cycle == SETTLE_AT:
            adapter.settle(SETTLE_MARKET, m.Side.YES if scenario.rng.random() < 0.5 else m.Side.NO)
        notes = scenario.stimulate(cycle, orch, adapter, clock) if cycle > 1 else []
        if cycle == CYCLES:  # a bid below the market that rests through the shutdown
            ask = best_yes_ask(adapter, h.MARKETS[1])
            orch.submit_signal(h.signal("final-resting", h.MARKETS[1], at=clock(), limit=f"{ask - Decimal('0.05'):.2f}",
                                        qty="1", tif="good_till_canceled"))
        events_before = journal.verify_chain().events
        report = orch.run_cycle()
        growth.append(journal.verify_chain().events - events_before)
        planned |= {d.intent_key for d in report.decisions if d.outcome is o.Outcome.SUBMITTED}
        check_invariants(journal, adapter, report, planned)
        assert not unexpected(report.incidents), report.incidents
        cycles.append((cycle, report))
        operate(report)
        if cycle == 1:
            operator.append([cycle, "START", []])
        clock.advance(60)

    # Every restart's unknown attempt was reconciled from the venue listing, never sent again.
    for kind, _, attempt_id in deaths:
        (a,) = [x for k in planned for x in journal.attempts_for(k) if x.attempt_id == attempt_id]
        assert a.state is (AttemptState.ABSENT if kind == "before_send" else AttemptState.ACKNOWLEDGED), (kind, a)
        assert sum(1 for x in adapter.venue.list_orders() if x["client_order_id"] == a.client_order_id) == (
            0 if kind == "before_send" else 1)

    resting = sorted(x["client_order_id"] for x in adapter.venue.list_orders() if x["status"] == "resting")
    shutdown = orch.shutdown("owner", "end of demonstration B")
    assert orch.state.mode is ctl.Mode.DISARMED
    assert sorted(x["client_order_id"] for x in adapter.venue.list_orders() if x["status"] == "resting") == resting
    with pytest.raises(o.OrchestratorStopped):
        orch.run_cycle()
    chain = journal.verify_chain()
    assert chain.ok, chain.problems
    attempts = sorted(([a.attempt_id, a.state.value, a.provider_order_id] for k in planned
                       for a in journal.attempts_for(k)))
    summary = {
        "seed": seed, "cycles": [[cycle, r.cycle, r.mode_at_start.value, r.mode_at_end.value, r.reconciliation,
                                  [[d.intent_key, d.outcome.value, d.attempt_state, [x.split(":")[0] for x in d.reasons]]
                                   for d in r.decisions], list(r.resolved_unknown), r.fills_recorded,
                                  list(r.released), list(r.incidents), r.requests_used, r.records_written]
                                 for cycle, r in cycles],
        "operator": operator, "deaths": deaths,
        "venue": {"orders": [[x["client_order_id"], x["status"], str(x["fill_count"]), str(x["remaining_count"]),
                              str(x["initial_count"])]
                             for x in adapter.venue.list_orders()],
                  "positions": {f"{t}:{s.value}": str(q) for (t, s), q in sorted(adapter.venue.positions.items(),
                                                                                key=lambda kv: (kv[0][0], kv[0][1].value))},
                  "cash": str(adapter.venue.cash), "settled": dict(adapter.settled),
                  "faults": [[x["event"], x["fault"]] for x in adapter.venue.fault_log]},
        "attempts": attempts, "resting_left": list(shutdown.resting_left), "chain_events": chain.events,
        "events_per_cycle_max": max(growth),
        "records": dict(sorted(Counter(r.record_type for r in journal.control_records(h.SCOPE)).items())),
    }
    journal.close()
    summary["hash"] = m.sha256_text(m.canonical_json({k: v for k, v in summary.items() if k != "hash"}))
    return summary


def test_demonstration_b(tmp_path):
    s = run_demo(tmp_path)
    cycles = s["cycles"]  # [demo cycle, orchestrator cycle, mode at start, mode at end, reconciliation, decisions,
    #                       resolved, fills, released, incidents, requests, records]
    outcomes = [d for c in cycles for d in c[5]]
    codes = {code for d in outcomes for code in d[3]}
    states = [d[2] for d in outcomes if d[1] == "SUBMITTED"]
    assert len(cycles) >= 50
    # The scenario really exercised what demonstration B names.
    assert len(states) >= 15, outcomes
    assert {"OUTCOME_UNKNOWN", "REJECTED", "ACKNOWLEDGED"} <= set(states)
    assert [x for x in s["venue"]["orders"] if 0 < Decimal(x[2]) < Decimal(x[4])], "no partial fill happened"
    assert "ARBITRATION_ONE_INTENT_PER_MARKET" in codes  # conflicting signals: one intent per market per cycle
    assert codes & {"DAILY_NEW_RISK_LIMIT", "TRADE_COUNT_LIMIT", "EXPOSURE_PER_MARKET", "RISK_CAPACITY_INSUFFICIENT"}
    assert all(c[4] == "FAILED" and c[3] == "DISARMED" for c in cycles if c[0] in OUTAGE)  # source loss disarms
    assert sum(len(c[6]) for c in cycles) >= 3, "unknown attempts were not resolved"
    assert [d[0] for d in s["deaths"]] == ["before_send", "after_send"]
    assert list(s["venue"]["settled"]) == [SETTLE_MARKET]
    assert s["resting_left"], "shutdown should have left a resting order alone"
    assert {"SETTLEMENT", "ATTRIBUTION", "PNL_OBSERVATION", "DECISION", "SIGNAL_OUTCOME", "SHUTDOWN"} <= set(s["records"])
    # Bounded storage growth per cycle (every journal row of every kind, from the chain itself).
    assert s["events_per_cycle_max"] <= 200, s["events_per_cycle_max"]
    assert max(c[11] for c in cycles) <= 2 * h.BOUNDS.max_signals_per_cycle + 6 * h.BOUNDS.max_intents_per_cycle + 20
    assert max(c[10] for c in cycles) <= h.BOUNDS.max_requests_per_cycle
    # Operator actions: one arm per start and per incident episode, never per order.
    assert len(s["operator"]) <= 2 + len(s["deaths"]) + 1
    assert s["hash"] == EXPECTED_HASH, s["hash"]


def test_another_seed_holds_every_invariant_and_replays_to_the_same_hash(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = run_demo(tmp_path / "a", seed=7)
    second = run_demo(tmp_path / "b", seed=7)
    assert first["hash"] == second["hash"] != EXPECTED_HASH
