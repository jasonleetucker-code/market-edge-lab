"""#160 package P: load and performance on the declared synthetic workload. FIXTURE only, no network.

What is measured (and printed with `-s`; written as JSON to $EDGE_LAB_PERF_OUT when set) and what is asserted:

- **Declared workload** (`chaos_support.Workload`, LOAD_PROFILE below): queue depth, intents per cycle, network requests
  per cycle, and p50/p95/p99 latency of a whole cycle, a decision (`Orchestrator._decide`), a journal write (every
  outermost BEGIN IMMEDIATE ... COMMIT), and the risk gate (`risk_gate.evaluate`/`revalidate`, and separately the
  `project_account` projection). Harness time (the fake venue behind `send`, the fixture feed) is measured apart.
  Asserted: the bounds (queue, intents, requests, records and journal events per cycle), not speed.
- **Growth**: journal events and bytes per cycle, restart (boot) time against history, and Python memory with
  `tracemalloc` across the run. Asserted: memory growth per cycle stays under a generous leak bound.
- **Signal burst** well above the bounds: backlog, refusals, drain time.
- **Rate budget exhausted**: the reserved PROTECTIVE headroom of the real `transport.RateBudget` still covers a full
  account read and a cancel of our own order after ordinary traffic has drained the buckets.
- **Read ceiling**: the account history at which one complete read no longer fits the cycle's request budget; past
  it the cycle is not COMPLETE, the controller disarms and nothing is sent.

Defaults are small (EDGE_LAB_LOAD_CYCLES=120, EDGE_LAB_MEMORY_CYCLES=60). EDGE_LAB_CHAOS_SCALE=full runs 2,000 latency
cycles and 500 memory cycles. Timings are of this machine and this fixture; they are not venue latency and carry no
statistical claim. Results and the machine they were measured on: docs/execution/PERFORMANCE.md.
"""

from __future__ import annotations

import gc
import json
import os
import time
import tracemalloc
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import chaos_support as cs
import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution import risk_gate as gate
from edge_lab.risk import RiskPolicy

CYCLES = cs.knob("LOAD_CYCLES", 120, 2000)
MEMORY_CYCLES = cs.knob("MEMORY_CYCLES", 60, 500)  # tracemalloc with 12-frame tracebacks is slow
SEED = 2026
LOAD_PROFILE = {
    "markets": len(h.MARKETS), "cycle_interval_s": 60, "entries_per_cycle": [0, 0, 1],
    "exit_probability": 0.5, "gtc_share": 0.35, "venue_cash": "10000",
    "test_limits": "harness caps; loss, daily new risk and grant lifetime widened (LOAD_POLICY, LOAD_GRANT)",
    "competitor_share_of_ioc": 0.25,
    "bounds": {"max_queued_signals": h.BOUNDS.max_queued_signals,
               "max_signals_per_cycle": h.BOUNDS.max_signals_per_cycle,
               "max_intents_per_cycle": h.BOUNDS.max_intents_per_cycle,
               "max_requests_per_cycle": h.BOUNDS.max_requests_per_cycle,
               "cycle_deadline_s": h.BOUNDS.cycle_deadline.total_seconds()},
    "ticket_max_orders_per_window": h.TICKET.max_orders_per_window,
}
# Explicit TEST limits for the load passes, wider than the harness's on loss, daily new risk and grant lifetime only,
# so that a run of 2,000 cycles (33 hours of fixture time) keeps sending instead of stopping at a daily or loss limit
# (the synthetic strategy pays the spread every round trip). Position, event, cluster and portfolio caps, the order
# rate and every bound are the harness's. Not owner limits; the policy id is the harness's because the synthetic
# strategy stamps it on every intent.
LOAD_POLICY = RiskPolicy(h.POLICY.policy_id, reserve_floor=Decimal("10"), max_position_risk=Decimal("15"),
                         max_event_risk=Decimal("60"), max_cluster_risk=Decimal("80"),
                         max_portfolio_risk=Decimal("80"), daily_loss_limit=Decimal("100000"),
                         weekly_loss_limit=Decimal("100000"), max_drawdown=Decimal("100000"))
LOAD_RISK = o.RiskInputs(LOAD_POLICY, replace(h.LIMITS, daily_new_risk=Decimal("100000")), h.TICKET)
LOAD_GRANT = h.grant(expires_at_utc=m.utc_text(h.T0 + timedelta(days=30)),
                     limits=ctl.GrantLimits(max_order_cost=Decimal("10"), max_event_exposure=Decimal("80"),
                                            max_total_exposure=Decimal("100"), max_daily_turnover=Decimal("100000"),
                                            max_daily_loss=Decimal("100000"), max_drawdown=Decimal("100000")))
LOAD_CASH = Decimal("10000")
RECORDS_BOUND = 2 * h.BOUNDS.max_signals_per_cycle + 6 * h.BOUNDS.max_intents_per_cycle + 20  # as demonstration B
EVENTS_BOUND = 200
LEAK_BOUND_BYTES_PER_CYCLE = 64 * 1024  # a leak detector, not a target: the measured slope is in PERFORMANCE.md


def _emit(name: str, result: dict) -> None:
    result = {"test": name, "hardware": cs.hardware(), "cycles_setting": CYCLES, **result}
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    out = os.environ.get("EDGE_LAB_PERF_OUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, sort_keys=True, default=str) + "\n")


def _run(tmp_path, monkeypatch, cycles: int, *, memory: bool) -> dict:
    rig = cs.Rig(tmp_path, risk=LOAD_RISK, grants=(LOAD_GRANT,))
    rig.adapter.venue.cash = LOAD_CASH
    timings = cs.Timings()
    rig.warm()
    workload = cs.Workload(SEED, per_cycle=(0, 0, 1), exit_share=0.5)

    def instrument() -> None:
        if memory:
            return  # the memory pass keeps no samples of its own
        timings.instrument_journal(rig.journal)
        rig.orch._decide = timings.wrap("decision", rig.orch._decide)
        rig.orch._prepare_and_send = timings.wrap("prepare_send_record", rig.orch._prepare_and_send)
        rig.feed.market_state = timings.wrap("feed", rig.feed.market_state)

    if not memory:
        monkeypatch.setattr(gate, "evaluate", timings.wrap("risk_gate", gate.evaluate))
        monkeypatch.setattr(gate, "revalidate", timings.wrap("risk_gate", gate.revalidate))
        monkeypatch.setattr(gate, "project_account", timings.wrap("risk_projection", gate.project_account))
        rig.send = timings.wrap("send", rig.adapter)
    instrument()
    restarts = []
    per_cycle = []
    blocked = Counter()
    memory_points = []
    if memory:
        tracemalloc.start(MEMORY_FRAMES)
        first = None
    checkpoint = max(1, cycles // 4)
    for c in range(1, cycles + 1):
        if c % checkpoint == 0 and c < cycles:  # a process restart at each quarter: boot time against history
            events = cs.max_seq(rig.journal)
            start = time.perf_counter()
            rig.restart()
            restarts.append({"cycle": c, "events": events, "boot_ms": round((time.perf_counter() - start) * 1000, 2)})
            instrument()
        workload.stimulate(c, rig.orch, rig.adapter, rig.clock)
        depth = len(rig.orch.queued_signals)
        events = cs.max_seq(rig.journal)
        send_before = len(timings.samples["send"])
        start = time.perf_counter()
        report = rig.orch.run_cycle()
        elapsed = time.perf_counter() - start
        send_time = sum(timings.samples["send"][send_before:])
        timings.samples["cycle"].append(elapsed)
        timings.samples["cycle_excluding_venue"].append(elapsed - send_time)
        sent = len([d for d in report.decisions if d.outcome is o.Outcome.SUBMITTED])
        blocked.update(d.reasons[0].split(":")[0] for d in report.decisions if d.outcome is o.Outcome.BLOCKED)
        per_cycle.append({"depth": depth, "decisions": len(report.decisions), "submitted": sent,
                          "requests": report.requests_used, "records": report.records_written,
                          "events": cs.max_seq(rig.journal) - events, "reconciliation": report.reconciliation})
        if not memory:  # the memory pass retains no report of its own
            rig.reports.append(report)
        rig.operate(report)
        if memory and c % max(1, cycles // 10) == 0:
            gc.collect()  # count what is retained, not cyclic garbage waiting for the collector
            memory_points.append((c, tracemalloc.get_traced_memory()[0]))
            if first is None:  # the package's own share is attributed at the first point and at the end only
                first, first_cycle = tracemalloc.take_snapshot(), c
        if c % 25 == 0 or c == cycles:
            cs.check_invariants(rig.journal, rig.adapter, live=rig.orch, report=report, chain=(c == cycles))
        rig.clock.advance(60)
    result = {"per_cycle": per_cycle, "restarts": restarts, "timings": timings, "rig": rig, "blocked": blocked}
    if memory:
        gc.collect()
        last = tracemalloc.take_snapshot()
        result["memory_points"] = memory_points
        before, after = _src_traces(first), _src_traces(last)
        grew = Counter(after)
        grew.subtract(before)
        result["memory_src"] = {"first_cycle": first_cycle, "last_cycle": cycles, "first_bytes": sum(before.values()),
                                "last_bytes": sum(after.values())}
        result["memory_top"] = [f"{where}: {size / 1024:+.1f} KiB" for where, size in grew.most_common(8)]
        tracemalloc.stop()
    rig.journal._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result["db_bytes_checkpointed"] = cs.journal_bytes(rig.jpath)
    return result


MEMORY_FRAMES = 12
_SRC = os.sep + os.path.join("src", "edge_lab") + os.sep
_TESTS = os.sep + os.path.join("tests", "execution") + os.sep
_HARNESS_IN_SRC = "fake_venue.py"  # the fake exchange lives in the package but is the venue, not the executor


def _owner(trace) -> str | None:
    """The innermost of our frames (src or tests) of one allocation: src code (or the stdlib it called) owns it."""
    for frame in reversed(trace.traceback):  # frames run oldest first: walk from the innermost outwards
        name = frame.filename
        if _TESTS in name or name.endswith(_HARNESS_IN_SRC):
            return None
        if _SRC in name:
            return f"{name.split(_SRC)[1]}:{frame.lineno}"
    return None


def _src_traces(snapshot) -> Counter:
    out = Counter()
    for trace in snapshot.traces:
        where = _owner(trace)
        if where is not None:
            out[where] += trace.size
    return out


def _slope(points: list[tuple[int, int]]) -> float:
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / den if den else 0.0


def test_the_declared_workload_stays_inside_its_bounds_with_measured_latency(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, CYCLES, memory=False)
    rows, t, rig = r["per_cycle"], r["timings"], r["rig"]
    statuses = Counter(x["reconciliation"] for x in rows)
    quarter = max(1, len(rows) // 4)
    decision = t.samples["decision"]
    q = max(1, len(decision) // 4)
    _emit("declared_workload", {
        "profile": LOAD_PROFILE, "cycles": len(rows),
        "orders_sent": len(rig.adapter.creates), "fills": len(rig.adapter.venue.list_fills()),
        "queue_depth_max": max(x["depth"] for x in rows),
        "intents_per_cycle": dict(Counter(x["submitted"] for x in rows)),
        "blocked_first_reason": dict(r["blocked"]),
        "orders_sent_per_quarter": [sum(x["submitted"] for x in rows[i * quarter:(i + 1) * quarter])
                                    for i in range(4)],
        "decisions_per_cycle_max": max(x["decisions"] for x in rows),
        "requests_per_cycle": {"first_quarter_max": max(x["requests"] for x in rows[:quarter]),
                               "last_quarter_max": max(x["requests"] for x in rows[-quarter:])},
        "records_per_cycle_max": max(x["records"] for x in rows),
        "events_per_cycle": {"max": max(x["events"] for x in rows),
                             "mean": round(sum(x["events"] for x in rows) / len(rows), 1)},
        "events_total": cs.max_seq(rig.journal),
        "latency_ms": {k: t.summary(k) for k in ("cycle", "cycle_excluding_venue", "decision", "prepare_send_record",
                                                 "journal_write", "risk_gate", "risk_projection", "send", "feed")},
        "db_bytes_checkpointed": r["db_bytes_checkpointed"],
        "decision_p50_ms_first_vs_last_quarter": [round(cs.percentile(decision[:q], 50) * 1000, 3),
                                                  round(cs.percentile(decision[-q:], 50) * 1000, 3)],
        "restarts": r["restarts"], "reconciliation": dict(statuses)})
    assert max(x["depth"] for x in rows) <= h.BOUNDS.max_queued_signals
    assert max(x["submitted"] for x in rows) <= h.BOUNDS.max_intents_per_cycle
    assert max(x["requests"] for x in rows) <= h.BOUNDS.max_requests_per_cycle
    assert max(x["records"] for x in rows) <= RECORDS_BOUND
    assert max(x["events"] for x in rows) <= EVENTS_BOUND
    assert statuses["COMPLETE"] == len(rows), statuses  # a quiet venue: every read is complete
    assert sum(x["submitted"] for x in rows[-quarter:]) > 0, r["blocked"]  # flow is sustained to the end
    assert t.summary("cycle")["p99"] < 5000  # a sanity bound only (5 s on any machine), not a target
    rig.close()


def test_memory_and_journal_growth_across_the_run(tmp_path, monkeypatch):
    """Python memory with tracemalloc: everything traced (harness and fake venue included), and the part allocated by
    the execution package (the innermost of our frames is under src/edge_lab). The package's slope is asserted under
    a leak bound; its biggest growth sites are reported."""
    r = _run(tmp_path, monkeypatch, MEMORY_CYCLES, memory=True)
    points = r["memory_points"]
    total = _slope(points[len(points) // 5:]) if len(points) >= 3 else 0.0
    m_src = r["memory_src"]
    src = (m_src["last_bytes"] - m_src["first_bytes"]) / max(1, m_src["last_cycle"] - m_src["first_cycle"])
    rows = r["per_cycle"]
    events = cs.max_seq(r["rig"].journal)
    _emit("memory_growth", {"cycles": len(rows), "tracemalloc_points_cycle_total": points, "src": m_src,
                            "bytes_per_cycle_slope_total": round(total), "bytes_per_cycle_slope_src": round(src),
                            "top_src_growth_since_first_point": r["memory_top"], "events_total": events,
                            "db_bytes_checkpointed": r["db_bytes_checkpointed"],
                            "db_bytes_per_event": round(r["db_bytes_checkpointed"] / max(1, events)),
                            "db_bytes_per_cycle": round(r["db_bytes_checkpointed"] / max(1, len(rows)))})
    assert src < LEAK_BOUND_BYTES_PER_CYCLE, src
    r["rig"].close()


def test_a_signal_burst_far_above_the_bounds_keeps_the_backlog_bounded(tmp_path):
    """Ten times the queue bound arrives every cycle for five cycles, then nothing: the queue never exceeds its bound,
    the excess is refused at admission (QUEUE_FULL), at most `max_signals_per_cycle` are drained per cycle, and the
    backlog is gone within ceil(queue / drain) cycles of the burst ending."""
    rig = cs.Rig(tmp_path)
    rig.warm()
    burst = 10 * h.BOUNDS.max_queued_signals
    timings = cs.Timings()
    rows, reasons = [], Counter()
    for c in range(1, 12):
        if c <= 5:
            for i in range(burst):
                t = h.MARKETS[i % 3]
                ask = cs.best_yes_ask(rig.adapter, t)
                start = time.perf_counter()
                admission = rig.orch.submit_signal(h.signal(f"burst{c}-{i}", t, at=rig.clock(), limit=f"{ask:.2f}",
                                                            qty="1"))
                timings.samples["submit_signal"].append(time.perf_counter() - start)
                reasons[admission.reason or "ACCEPTED"] += 1
        depth = len(rig.orch.queued_signals)
        report = rig.step()
        rows.append({"cycle": c, "depth_before": depth, "depth_after": len(rig.orch.queued_signals),
                     "drained": sum(report.signals.values()), "decisions": len(report.decisions),
                     "records": report.records_written})
    assert max(x["depth_before"] for x in rows) <= h.BOUNDS.max_queued_signals
    assert max(x["drained"] for x in rows) <= h.BOUNDS.max_signals_per_cycle
    assert max(x["records"] for x in rows) <= RECORDS_BOUND
    drain_cycles = -(-h.BOUNDS.max_queued_signals // h.BOUNDS.max_signals_per_cycle)
    assert rows[5 + drain_cycles - 1]["depth_after"] == 0, rows
    assert reasons["QUEUE_FULL"] >= 5 * (burst - h.BOUNDS.max_queued_signals)
    _emit("signal_burst", {"burst_per_cycle": burst, "admissions": dict(reasons), "rows": rows,
                           "submit_signal_ms": timings.summary("submit_signal"),
                           "drain_cycles_after_burst": drain_cycles})


def test_reserved_cancel_and_reconcile_headroom_survive_an_exhausted_rate_budget(tmp_path):
    """The real `RateBudget` (basic tier, 30% reserved) behind the real transport. Ordinary traffic sharing the
    account's budget drains both buckets to their reserve and the clock stops (no refill). Then: the account read
    (PROTECTIVE) still completes; a new order (ORDINARY) is NOT_SENT and nothing reaches the venue; and a cancel of our
    own resting order (PROTECTIVE) is confirmed at shutdown. A second read in the same window does not fit: the cycle
    is not COMPLETE and the controller disarms."""
    from edge_lab.execution import transport as tr
    from edge_lab.execution.kalshi_wire import Bucket

    mono = {"ns": 0}
    budget = tr.RateBudget(monotonic_ns=lambda: mono["ns"])
    rig = cs.Rig(tmp_path, http={"budget": budget})
    tick = 10 * 1_000_000_000  # ten seconds of refill: the buckets are full again

    def step(**kw):
        mono["ns"] += tick
        return rig.step(**kw)

    report = rig.cycle()
    rig.operate(report)
    rig.clock.advance(60)
    rig.orch.submit_signal(h.signal("rest", h.MARKETS[1], at=rig.clock(), limit="0.43", qty="6",
                                    tif="good_till_canceled"))
    step()
    step()
    mono["ns"] += tick
    drained = Counter()
    while budget.try_acquire(Bucket.READ, None, tr.Priority.ORDINARY):
        drained["read"] += 1
    while budget.try_acquire(Bucket.WRITE, 0, tr.Priority.ORDINARY):
        drained["write"] += 1
    reserve = Counter()  # what is left for protective requests, measured on a copy of the state
    probe = tr.RateBudget(monotonic_ns=lambda: mono["ns"])
    for kind, shard in ((Bucket.READ, None), (Bucket.WRITE, 0)):
        while probe.try_acquire(kind, shard, tr.Priority.ORDINARY):
            pass
        while probe.try_acquire(kind, shard, tr.Priority.PROTECTIVE):
            reserve["read" if kind is Bucket.READ else "write"] += 1
    sent = len(rig.adapter.creates)
    rig.orch.submit_signal(h.signal("new", h.MARKETS[0], at=rig.clock(), limit="0.45", qty="1"))
    first = rig.step()  # the clock (monotonic) does not move
    (d,) = [x for x in first.decisions if x.outcome is o.Outcome.SUBMITTED]
    assert first.reconciliation == "COMPLETE" and first.requests_used <= reserve["read"] + 1
    assert d.attempt_state == "OUTCOME_UNKNOWN" and len(rig.adapter.creates) == sent  # NOT_SENT: nothing left
    second = rig.step()
    assert second.reconciliation != "COMPLETE" and second.mode_at_end is ctl.Mode.DISARMED
    shutdown = rig.orch.shutdown("owner", "rate budget exhausted", cancel_owned=True)
    assert list(shutdown.cancel_outcomes.values()) == ["CANCEL_CONFIRMED"], shutdown
    mono["ns"] += tick
    rig.restart()
    rig.clock.advance(60)
    rig.settle(6)
    assert rig.journal.attempt(d.attempt_id).state.value == "ABSENT"
    _emit("rate_budget_headroom", {"tier": "basic", "reserve_fraction": "3/10", "token_cost": 10,
                                   "ordinary_drained": dict(drained), "protective_left": dict(reserve),
                                   "account_read_requests": first.requests_used,
                                   "second_read": second.reconciliation})


def test_the_account_read_ceiling_fails_closed(tmp_path):
    """Every cycle reads the whole account history (orders and fills, twice for stability). With history placed at the
    venue by someone else (filled manual orders: external, no cash held), requests per cycle grow with history; past
    the request budget the read is not COMPLETE, the controller disarms and a queued signal is not sent."""
    sizes = [0, 600, 1200] + ([1500, 1600, 1700, 1800, 2000] if cs.full_scale() else [1700])
    rows = []
    rig = cs.Rig(tmp_path)
    rig.warm()
    rig.adapter.venue.cash += Decimal(max(sizes))  # someone else's purchases are paid from the same account
    placed = 0
    t = h.MARKETS[2]
    for size in sizes:
        rig.adapter.venue.add_liquidity(t, m.Side.NO, "0.55", str(size - placed + 1))
        while placed < size:
            placed += 1
            rig.adapter.place_manual(t, m.Side.YES, "0.45", "1", n=placed)
        sent = len(rig.adapter.creates)
        rig.orch.submit_signal(h.signal(f"probe{size}", h.MARKETS[0], at=rig.clock(), limit="0.46", qty="1"))
        start = time.perf_counter()
        report = rig.step()
        rows.append({"history_orders": size + len(rig.adapter.creates), "requests": report.requests_used,
                     "reconciliation": report.reconciliation, "sent": len(rig.adapter.creates) - sent,
                     "decisions": [d.outcome.value for d in report.decisions],
                     "cycle_ms": round((time.perf_counter() - start) * 1000)})
        if report.reconciliation != "COMPLETE":  # disarmed before step 4: no decision was even made
            assert report.mode_at_end is ctl.Mode.DISARMED and report.decisions == () and rows[-1]["sent"] == 0, rows
            assert report.requests_used <= h.BOUNDS.max_requests_per_cycle
            break
    assert rows[-1]["reconciliation"] != "COMPLETE", rows  # the ceiling was reached and failed closed
    _emit("read_ceiling", {"page_limit": 100, "max_pages": 20,
                           "max_requests_per_cycle": h.BOUNDS.max_requests_per_cycle, "rows": rows})
