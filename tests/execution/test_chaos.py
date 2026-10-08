"""#160 package P: chaos scenarios against the real merged execution components. FIXTURE only, no network.

Every scenario runs the real orchestrator, journal, reservations, lifecycle, control, risk gate and account reads (and,
where named, the real transport with a fixture signer and rate budget) against the in-memory fake venue
(`chaos_support`). After every step it asserts the package P global invariants (`chaos_support.check_invariants`):
no venue order without a prepared attempt; at most one attempt per intent key; the journal never shows more fills than
the venue; positions reconcile; no reservation released without confirmation; `verify_chain` OK; the controller is
DISARMED after any incident until it is rearmed, and nothing is prepared unless the replayed mode sends.

Seeds are recorded in the parametrization. No statistical claim is made from these fixtures. Scale with
EDGE_LAB_CHAOS_SCALE=full (or EDGE_LAB_CHAOS_SEEDS / EDGE_LAB_DISK_POINTS); see docs/execution/PERFORMANCE.md.

Bugs found are `xfail(strict=True)` tests at the end of this file, each with its reason; P-1 and P-2, fixed by
#177, are regressions there now.
"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter
from datetime import timedelta

import pytest

import chaos_support as cs
import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution.journal import ExecutionJournal, JournalBusy, JournalUnavailable
from edge_lab.execution.reservations import LeaseHeld


@pytest.fixture(autouse=True)
def _close_rigs():
    """Close every rig's journal after each test (Windows keeps open SQLite files locked)."""
    yield
    cs.close_all()


SEEDS = list(range(1, cs.knob("CHAOS_SEEDS", 3, 25) + 1))
B70, B72, B74 = h.MARKETS


def submitted(report: o.CycleReport) -> list[o.Decision]:
    return [d for d in report.decisions if d.outcome is o.Outcome.SUBMITTED]


def rest_order(rig: cs.Rig, t: str = B72, signal_id: str = "rest") -> o.Decision:
    """A GTC buy of 6 at 0.43: our order becomes the best YES bid and rests (the book's best is 0.42)."""
    assert rig.orch.submit_signal(h.signal(signal_id, t, at=rig.clock(), limit="0.43", qty="6",
                                           tif="good_till_canceled")).accepted
    (d,) = submitted(rig.step())
    assert d.attempt_state == "ACKNOWLEDGED", d
    return d


def cross(rig: cs.Rig, t: str = B72, qty: str = "3") -> None:
    """Someone sells into our resting bid now (a maker fill of `qty`)."""
    rig.adapter.sync()
    rig.adapter.venue.add_liquidity(t, m.Side.NO, "0.57", qty)


# ---------------------------------------------------------------------------------------------- disk full


def _commit_points(seed: int) -> list[int]:
    """The commits of one busy cycle are numbered from 1; a sample of them (all of them at full scale)."""
    total = 32  # a three-signal cycle commits 22-30 times on this workload (measured); past the end is a no-op
    k = cs.knob("DISK_POINTS", 6, total)
    rng = random.Random(seed)
    return sorted({1, 2, total - 6} | set(rng.sample(range(1, total + 1), min(k, total))))


@pytest.mark.parametrize("persistent,restart", [(True, True), (False, False)], ids=["stays-full-restart",
                                                                                     "one-failure-continue"])
def test_a_full_disk_at_any_commit_of_a_cycle_fails_loud_and_recovers(tmp_path, persistent, restart):
    """The disk fills at commit N of a busy cycle (SQLITE_FULL from just before COMMIT: the transaction is rolled
    back). The cycle either fails loud (JournalUnavailable) or finishes with an incident; after space returns, a
    restart (or the same instance) reconciles every attempt from the venue and no invariant breaks."""
    outcomes = []
    for point in _commit_points(seed=20261007):
        rig = cs.Rig(tmp_path / f"p{point}-{persistent}", venue_lag=cs.SHORT_LAG)
        rig.warm()
        workload = cs.Workload(point)
        rig.step(workload, n=2)
        workload.stimulate(99, rig.orch, rig.adapter, rig.clock, 3)
        seen = {"n": 0}

        def hook(where, seen=seen, point=point):
            seen["n"] += 1
            if seen["n"] == point or (persistent and seen["n"] > point):
                raise sqlite3.OperationalError("database or disk is full")

        rig.journal._fault_hook = hook
        try:
            rig.orch.run_cycle()
            outcome = "finished"
        except JournalUnavailable as exc:
            assert "full" in str(exc), exc
            outcome = "raised"
        rig.journal._fault_hook = None  # space is back
        cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
        if restart:
            rig.restart()
        rig.clock.advance(60)
        rig.settle(8)
        cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
        outcomes.append((point, seen["n"], outcome))
        rig.close()
    assert any(o == "raised" for _, _, o in outcomes), outcomes


@pytest.mark.parametrize("extra_pages", [1, 3])
def test_a_real_sqlite_full_error_fails_the_cycle_loud_and_a_restart_recovers(tmp_path, extra_pages):
    """A real SQLITE_FULL: the journal connection's `max_page_count` is set just above its size mid-run."""
    rig = cs.Rig(tmp_path)
    rig.warm()
    workload = cs.Workload(extra_pages)
    conn = rig.journal._conn
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.execute(f"PRAGMA max_page_count = {pages + extra_pages}")
    raised = None
    for _ in range(40):
        try:
            rig.step(workload, n=2)
        except JournalUnavailable as exc:
            raised = exc
            break
    assert raised is not None and "full" in str(raised).lower(), raised
    cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
    rig.restart()  # a new connection: no page limit
    rig.clock.advance(60)
    rig.settle(8)
    for _ in range(3):
        rig.step(workload)
    cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)


# ---------------------------------------------------------------------------------------------- a locked journal


def _holder(rig: cs.Rig) -> sqlite3.Connection:
    return sqlite3.connect(str(rig.jpath), timeout=0.1, isolation_level=None)


def test_a_journal_locked_before_the_cycle_fails_it_loud_with_nothing_read_or_sent(tmp_path):
    rig = cs.Rig(tmp_path)
    rig.warm()
    rig.orch.submit_signal(h.signal("s1", B70, at=rig.clock(), limit="0.45"))
    holder = _holder(rig)
    holder.execute("BEGIN IMMEDIATE")  # another connection holds the write lock
    requests = len(rig.adapter.requests)
    with pytest.raises(JournalBusy):
        rig.orch.run_cycle()
    assert len(rig.adapter.requests) == requests and rig.adapter.creates == []  # the lease renewal is the 1st write
    holder.execute("ROLLBACK")
    holder.close()
    report = rig.cycle()  # the same instance carries on once the lock is gone
    assert report.reconciliation == "COMPLETE" and [d.attempt_state for d in submitted(report)] == ["ACKNOWLEDGED"]


@pytest.mark.parametrize("seed", SEEDS)
def test_a_journal_locked_mid_cycle_loses_nothing(tmp_path, seed):
    """A second connection takes the write lock at a seeded request of a busy cycle (during the read, or after an
    attempt was committed and its order sent). The cycle fails loud with JournalBusy; afterwards every attempt is
    reconciled from the venue, never re-sent."""
    rng = random.Random(seed)
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    workload = cs.Workload(seed)
    rig.step(workload, n=2)
    workload.stimulate(99, rig.orch, rig.adapter, rig.clock, 3)
    at = rng.randint(1, 20)
    holder = _holder(rig)
    calls = {"n": 0}

    def send(request):
        calls["n"] += 1
        if calls["n"] == at:
            holder.execute("BEGIN IMMEDIATE")
        return rig.adapter(request)

    rig.send = send
    try:
        rig.orch.run_cycle()
        raised = False
    except JournalBusy:
        raised = True
    assert raised == (calls["n"] >= at), (seed, at, calls["n"])  # once the lock is taken, the cycle fails loud
    if holder.in_transaction:
        holder.execute("ROLLBACK")
    holder.close()
    rig.send = rig.adapter
    cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
    rig.clock.advance(60)
    rig.settle(8)
    assert len(rig.adapter.creates) == len(set(rig.adapter.creates))


# ---------------------------------------------------------------------------------------------- wrong clocks


@pytest.mark.parametrize("jump", [-3600, -30, 600, 2 * 86400], ids=["back-1h", "back-30s", "fwd-10m", "fwd-2d"])
def test_a_jumping_clock_fails_closed_and_recovers_after_it_is_fixed(tmp_path, jump):
    """Our clock jumps; the venue's does not. The venue's user-data timestamp then disagrees with ours (in the future,
    or stale), so reconciliation is not COMPLETE: the controller disarms and nothing is sent while the clock is wrong.
    Once the clock is right again, the operator re-arms and orders flow."""
    rig = cs.Rig(tmp_path)
    rig.warm()
    workload = cs.Workload(abs(jump))
    for _ in range(3):
        rig.step(workload)
    sent = len(rig.adapter.creates)
    rig.jump(jump)
    for _ in range(3):
        report = rig.step(workload)
        assert report.reconciliation != "COMPLETE" and report.mode_at_end is ctl.Mode.DISARMED, report
    assert len(rig.adapter.creates) == sent, "an order was sent while our clock was wrong"
    rig.jump(-jump)
    for _ in range(6):
        rig.step(workload)
    assert rig.orch.state.mode is ctl.Mode.BOUNDED_AUTO and len(rig.adapter.creates) > sent


@pytest.mark.parametrize("seed", SEEDS)
def test_clock_jitter_within_tolerance_keeps_every_invariant(tmp_path, seed):
    """Our clock wanders up to 3 s either way of the venue's every cycle (inside every tolerance)."""
    rng = random.Random(seed)
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    workload = cs.Workload(seed)
    for _ in range(15):
        rig.adapter.skew = rng.uniform(-3, 3)
        rig.step(workload)
    assert len(rig.adapter.creates) > 0


# ---------------------------------------------------------------------------------------------- HTTP errors


@pytest.mark.parametrize("fault,resolved", [
    ("ok", "ACKNOWLEDGED"), ("429", "ABSENT"), ("503_before", "ABSENT"), ("timeout_before", "ABSENT"),
    ("503_after", "ACKNOWLEDGED"), ("timeout_after", "ACKNOWLEDGED"), ("malformed_after", "ACKNOWLEDGED"),
    ("409_after", "ACKNOWLEDGED")])
def test_every_http_write_failure_is_unknown_never_retried_and_reconciled(tmp_path, fault, resolved):
    """Through the real transport: a create answered with 429, 5xx, a timeout, a malformed 2xx body or 409 is
    OUTCOME_UNKNOWN (the transport says THROTTLED or AMBIGUOUS; the orchestrator trusts only OK or REJECTED), is never
    sent again, and is resolved from the order listing: ABSENT when the venue never acted, ACKNOWLEDGED when it did."""
    rig = cs.Rig(tmp_path, http={})
    rig.warm()
    rig.http.script = [fault]
    rig.orch.submit_signal(h.signal("s1", B70, at=rig.clock(), limit="0.45", qty="2"))
    (d,) = submitted(rig.step())
    assert d.attempt_state == ("ACKNOWLEDGED" if fault == "ok" else "OUTCOME_UNKNOWN"), d
    rig.settle(6)
    attempt = rig.journal.attempt(d.attempt_id)
    assert attempt.state.value == resolved
    assert rig.adapter.creates.count(attempt.client_order_id) == (0 if resolved == "ABSENT" else 1)
    assert [x for x in rig.http.log if x[0] == "ORDER_CREATE"] == [("ORDER_CREATE", fault)]  # sent once


@pytest.mark.parametrize("seed", SEEDS)
def test_a_seeded_mix_of_http_errors_holds_every_invariant(tmp_path, seed):
    """Every write fault and a read fault mix (429, 503, timeouts, malformed pages) through the real transport for
    25 cycles; then the network heals and every attempt is reconciled."""
    mix = dict(write_mix=tuple((f, 1) for f in cs.WRITE_FAULTS),
               read_mix=(("ok", 30), ("429", 1), ("503", 1), ("timeout", 1), ("malformed", 1)))
    rig = cs.Rig(tmp_path, http=mix, seed=seed, venue_lag=cs.SHORT_LAG)
    report = rig.cycle()
    rig.operate(report)
    rig.clock.advance(60)
    workload = cs.Workload(seed)
    for _ in range(25):
        rig.step(workload, n=2)
    faults = {f for name, f in rig.http.log if name == "ORDER_CREATE"}
    assert len(faults) >= 3, faults
    rig.http.write_mix = rig.http.read_mix = (("ok", 1),)
    rig.settle(8)


@pytest.mark.parametrize("fault,resolved,reached", [("raise_before", "ABSENT", 0), ("raise_after", "ACKNOWLEDGED", 1)])
def test_a_send_that_raises_is_unknown_never_retried_and_reconciled(tmp_path, fault, resolved, reached):
    """The orchestrator's `send` itself raises (the real transport never does: it turns every failure into a result),
    before anything left or after the venue acted. Either way the attempt is OUTCOME_UNKNOWN (SEND_RAISED), the
    create is never sent again, and the listing resolves it."""
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    rig.adapter.raise_script = [fault]
    rig.orch.submit_signal(h.signal("s1", B70, at=rig.clock(), limit="0.45", qty="2"))
    (d,) = submitted(rig.step())
    assert d.attempt_state == "OUTCOME_UNKNOWN", d
    rig.settle(6)
    attempt = rig.journal.attempt(d.attempt_id)
    assert attempt.state.value == resolved and rig.adapter.raised == [("ORDER_CREATE", fault)]
    assert rig.adapter.creates.count(attempt.client_order_id) == reached


@pytest.mark.parametrize("seed", SEEDS)
def test_a_seeded_mix_of_raising_sends_holds_every_invariant(tmp_path, seed):
    """30% of writes (creates and, at the end, cancels) raise, half of them after the venue acted, for 20 workload
    cycles; then sends stop failing and everything is reconciled."""
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    rig.adapter.raise_rate, rig.adapter.raise_seed = 0.3, seed
    workload = cs.Workload(seed)
    for _ in range(20):
        rig.step(workload, n=2)
    assert rig.adapter.raised, "the seed never raised: the scenario exercised nothing"
    rig.adapter.raise_rate = 0.0
    rig.settle(8)


# ---------------------------------------------------------------------------------------------- receipts


@pytest.mark.parametrize("fault", ["duplicate_fills", "reverse_listings", "stale_orders", "crossed_with_id",
                                   "crossed_without_id"])
def test_duplicate_and_out_of_order_receipts_keep_every_invariant(tmp_path, fault):
    """Duplicated fills in a page, pages served newest first, an older version of every order row (stale update
    stamps), and a create reply that is another order's ack (with or without its client id)."""
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    workload = cs.Workload(31)
    rest_order(rig)
    rig.step(workload, n=1)
    if fault.startswith("crossed"):
        rig.adapter.crossed_reply = fault.split("_", 1)[1]
    else:
        setattr(rig.adapter, fault, True)
    cross(rig)
    sent = len(rig.adapter.creates)
    reports = [rig.step(workload, n=1) for _ in range(3)]
    if fault == "stale_orders":
        # The first stale listing is indistinguishable from an order listing that lags its fills (it is COMPLETE and
        # may send); once our recorded fills exceed the stale rows, the attribution fails: never COMPLETE again.
        assert all(r.reconciliation != "COMPLETE" for r in reports[1:]), reports
        assert len(rig.adapter.creates) <= sent + 1
    if fault in ("duplicate_fills", "reverse_listings"):  # identical duplicates collapse; order does not matter
        assert all(r.reconciliation == "COMPLETE" and not r.incidents for r in reports), reports
    rig.adapter.stale_orders = rig.adapter.duplicate_fills = rig.adapter.reverse_listings = False
    rig.adapter.crossed_reply = None
    for _ in range(3):
        rig.step(workload, n=1)
    rig.settle(8)


# ---------------------------------------------------------------------------------------------- many markets


def test_many_markets_at_once_stay_inside_every_bound(tmp_path):
    """60 markets, one ENTRY signal on every one of them each cycle (three times the queue): one intent per market,
    at most `max_intents_per_cycle`, the request budget, and the risk gate's order-rate limit all hold."""
    markets = tuple(cs.ticker(i) for i in range(60))
    rig = cs.Rig(tmp_path, markets=markets)
    rig.warm()
    workload = cs.Workload(60, markets)
    rejected = 0
    for c in range(8):
        workload.liquidity(rig.adapter)
        for t in markets:
            ask = cs.best_yes_ask(rig.adapter, t)
            rejected += not rig.orch.submit_signal(h.signal(f"mm{c}-{t}", t, at=rig.clock(), limit=f"{ask:.2f}",
                                                            qty="1")).accepted
        report = rig.step()
        sent = [d.market_ticker for d in submitted(report)]
        assert len(sent) == len(set(sent)) <= h.BOUNDS.max_intents_per_cycle
        assert report.requests_used <= h.BOUNDS.max_requests_per_cycle and len(rig.orch.queued_signals) <= 20
    assert rejected >= 8 * (60 - h.BOUNDS.max_queued_signals)
    orders = rig.adapter.creates
    assert 0 < len(orders) <= h.TICKET.max_orders_per_window * 2  # 8 per 10 minutes over 8 minutes


# ---------------------------------------------------------------------------------------------- lease races


@pytest.mark.parametrize("seed", SEEDS)
def test_lease_takeovers_at_random_points_never_double_send(tmp_path, seed):
    """Workers stall past their lease and new ones take over at seeded points; stalled ones wake up and run cycles;
    a worker started while the lease is live is refused. A stale worker's first cycle after the takeover is a
    `fenced_out` report and every later one raises `OrchestratorFencedOut` (#177); either way it writes nothing and
    sends nothing, and the live one reconciles everything."""
    rng = random.Random(seed)
    rig = cs.Rig(tmp_path, venue_lag=cs.SHORT_LAG)
    rig.warm()
    workload = cs.Workload(seed)
    workers = [rig.orch]
    journals = [rig.journal]
    outcomes = Counter()
    for step in range(16):
        action = rng.random()
        if 0.4 <= action < 0.5 and rig.journal.reservations.lease().live_at(rig.clock()):
            # a second start while the live worker holds the lease: refused before it writes anything (P-1, #177)
            events = cs.max_seq(rig.journal)
            journal = ExecutionJournal.open(rig.jpath)
            with pytest.raises(LeaseHeld):
                o.Orchestrator(journal, h.config(worker_id=f"x{seed}-{step}"), send=rig.adapter,
                               feed=h.Feed(rig.adapter), strategies=(h.DemoStrategy(),), clock=rig.clock,
                               sleep=rig.clock.sleep)
            journal.close()
            assert cs.max_seq(rig.journal) == events
            outcomes["refused_start"] += 1
            continue
        if action < 0.2:  # the live worker stalls past its lease; a new worker takes over
            rig.clock.advance(400)
            journal = ExecutionJournal.open(rig.jpath)
            orch = o.Orchestrator(journal, h.config(worker_id=f"w{seed}-{step}"), send=rig.adapter,
                                  feed=h.Feed(rig.adapter), strategies=(h.DemoStrategy(),), clock=rig.clock,
                                  sleep=rig.clock.sleep)
            workers.append(orch)
            journals.append(journal)
            rig.orch, rig.journal = orch, journal
        elif action < 0.4 and len(workers) > 1:  # a stalled worker wakes up and runs a cycle
            stale = rng.choice(workers[:-1])
            events, sent = cs.max_seq(rig.journal), len(rig.adapter.creates)
            try:
                report = stale.run_cycle()
                assert report.fenced_out and report.records_written == 0
                outcomes["fenced_report"] += 1
            except o.OrchestratorFencedOut:  # it already knows it is fenced out: it runs no further cycle
                outcomes["fenced_raise"] += 1
            assert cs.max_seq(rig.journal) == events and len(rig.adapter.creates) == sent
            cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
            continue
        rig.step(workload, n=rng.choice([0, 1, 2]))
    rig.settle(8)
    print(seed, dict(outcomes))  # which paths this seed exercised (-s)
    for j in journals:
        j.close()


# ---------------------------------------------------------------------------------------------- budgets and deadlines


def test_a_request_budget_exhausted_mid_send_blocks_the_rest_and_disarms(tmp_path):
    rig = cs.Rig(tmp_path)
    rig.warm()
    probe = rig.cycle()
    read_cost = probe.requests_used
    rig.clock.advance(60)
    rig.restart(bounds=o.CycleBounds(20, 6, 10, 3, read_cost + 1, timedelta(seconds=30), timedelta(minutes=10)))
    rig.warm()
    for i, t in enumerate(h.MARKETS):
        rig.orch.submit_signal(h.signal(f"b{i}", t, at=rig.clock(), limit="0.45", qty="1"))
    report = rig.step()
    assert [d.outcome for d in report.decisions][:1] == [o.Outcome.SUBMITTED]
    assert any("REQUEST_BUDGET_EXHAUSTED" in r for d in report.decisions for r in d.reasons)
    assert report.mode_at_end is ctl.Mode.DISARMED and any(i.startswith("budget:") for i in report.incidents)
    assert report.requests_used <= read_cost + 1 and len(rig.adapter.creates) == 1


def test_a_read_that_overruns_the_deadline_disarms_and_sends_nothing(tmp_path):
    rig = cs.Rig(tmp_path)
    rig.warm()
    rig.orch.submit_signal(h.signal("d1", B70, at=rig.clock(), limit="0.45"))

    def slow(request):  # every request takes 3 seconds: the read passes the 30 s cycle deadline
        rig.clock.advance(3)
        return rig.adapter(request)

    rig.send = slow
    report = rig.step()
    assert report.reconciliation != "COMPLETE" and report.mode_at_end is ctl.Mode.DISARMED
    assert rig.adapter.creates == [] and report.decisions == ()
    rig.send = rig.adapter
    rig.settle(4)


# ---------------------------------------------------------------------------------------------- regressions and bugs


BUG_P3 = ("BUG P-3: fills that execute shortly before an account read are counted twice when the venue's user-data "
          "timestamp lags (here 20 s; account.py accepts up to max_data_lag = 1 min) or our clock trails the venue's "
          "by more than lifecycle.TIMESTAMP_SKEW (2 s; account.py tolerates CLOCK_SKEW = 5 s). "
          "Orchestrator._fold_order labels the listing's cumulative fill count with snapshot.observed_at = min(read "
          "start, user-data as_of), earlier than the moment the listing was read, so the lifecycle adds fills stamped "
          "after that label on top of a count that already includes them, and record_fill writes more fills than the "
          "venue has. It fails closed one or two cycles later (an attribution mismatch, then a lifecycle quarantine).")


# P-1 and P-2 were found here as strict xfails and fixed by #177 (lease-first boot, per-write lease fencing). They now
# run as regressions; docs/execution/PERFORMANCE.md keeps their history.


def test_p1_a_refused_second_start_writes_nothing_and_the_live_worker_carries_on(tmp_path):
    """P-1 (fixed by #177): a second orchestrator started while another worker holds the egress lease is refused
    before it writes anything, so the stored control log still replays to the live worker's state."""
    rig = cs.Rig(tmp_path)
    rig.warm()
    events = cs.max_seq(rig.journal)
    journal_b = ExecutionJournal.open(rig.jpath)
    with pytest.raises(LeaseHeld):
        o.Orchestrator(journal_b, h.config(worker_id="worker-b"), send=rig.adapter, feed=h.Feed(rig.adapter),
                       strategies=(h.DemoStrategy(),), clock=rig.clock, sleep=rig.clock.sleep)
    journal_b.close()
    assert cs.max_seq(rig.journal) == events, "the refused start wrote to the journal"
    rig.orch.submit_signal(h.signal("s1", B70, at=rig.clock(), limit="0.45"))
    (d,) = submitted(rig.step())  # check_invariants: INV7 (live state == replay; prepared only while sending)
    assert d.attempt_state == "ACKNOWLEDGED" and rig.orch.state.mode is ctl.Mode.BOUNDED_AUTO


def test_p2_a_worker_fenced_out_mid_send_writes_nothing_after_the_takeover(tmp_path):
    """P-2 (fixed by #177): worker A stalls inside a send for longer than its lease and B takes over. A writes
    nothing after the takeover, its later cycles raise OrchestratorFencedOut, and B reconciles A's in-flight order
    from the venue (never re-sent), arms and sends with its live state equal to the replay of the store."""
    rig = cs.Rig(tmp_path)
    rig.warm()
    taken = {}

    def send(request):
        if request.is_write() and "b" not in taken:  # A stalls in the send; B takes the lease over
            rig.clock.advance(400)
            taken["journal"] = ExecutionJournal.open(rig.jpath)
            taken["b"] = o.Orchestrator(taken["journal"], h.config(worker_id="worker-b"), send=rig.adapter,
                                        feed=h.Feed(rig.adapter), strategies=(h.DemoStrategy(),), clock=rig.clock,
                                        sleep=rig.clock.sleep)
            taken["seq"] = cs.max_seq(taken["journal"])
        return rig.adapter(request)

    rig.send = send
    rig.orch.submit_signal(h.signal("s1", B70, at=rig.clock(), limit="0.45"))
    report = rig.orch.run_cycle()
    assert report.fenced_out
    a, rig.orch, rig.journal = rig.orch, taken["b"], taken["journal"]
    rig.send = rig.adapter
    assert cs.max_seq(rig.journal) == taken["seq"], "the fenced-out worker wrote after the takeover"
    cs.check_invariants(rig.journal, rig.adapter, live=rig.orch)
    with pytest.raises(o.OrchestratorFencedOut):
        a.run_cycle()
    rig.clock.advance(60)
    rig.settle(6)  # B reconciles A's unknown attempt from the listing; the operator arms B
    rig.orch.submit_signal(h.signal("s2", B72, at=rig.clock(), limit="0.45"))
    (d,) = submitted(rig.step())
    assert d.attempt_state == "ACKNOWLEDGED"
    assert len(rig.adapter.creates) == len(set(rig.adapter.creates)) == 2
    rig.close()


@pytest.mark.xfail(strict=True, raises=cs.InvariantViolation, reason=BUG_P3)
@pytest.mark.parametrize("as_of_lag,skew", [(20.0, 0.0), (0.0, 4.0)], ids=["user-data-lags-20s",
                                                                            "our-clock-4s-slow"])
def test_bug_the_journal_never_records_more_fills_than_the_venue_near_a_read(tmp_path, as_of_lag, skew):
    clock = h.Clock()
    adapter = cs.ChaosAdapter(clock, journal_path=str(tmp_path / "p.execution.sqlite3"), venue_lag=5.0 - skew,
                              as_of_lag=as_of_lag, skew=skew)
    cs.seed_books(adapter, h.MARKETS)
    rig = cs.Rig(tmp_path, adapter=adapter, clock=clock)
    rig.warm()
    rest_order(rig)
    rig.step()
    cross(rig)  # 3 of our 6 fill a few seconds before the next read
    rig.step()  # check_invariants: INV3 (the journal records 6 filled, the venue 3)
