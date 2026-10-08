"""Fencing follow-ups from the package K review (#160, ADR 0046 §11). FIXTURE only.

1. A writer re-reads the lease before every write, so a takeover it has not yet noticed (a supervisor restart with
   the same worker id) stops it before it writes anything: no control event, record or evidence row.
2. Once fenced out, `run(n)` stops and `run_cycle` raises `OrchestratorFencedOut`: a fenced instance does not keep
   reading the whole account every interval."""

from __future__ import annotations

from datetime import timedelta

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution.journal import AttemptState, ExecutionJournal

B70, B72, B74 = h.MARKETS


@pytest.fixture
def jpath(tmp_path):
    return tmp_path / "fence.execution.sqlite3"


@pytest.fixture
def env(jpath):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(jpath)
    yield journal, adapter, clock
    journal.close()


def armed(journal, adapter, clock, **kw):
    orch, feed = h.build(journal, adapter, **kw)
    assert orch.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    return orch, feed


def test_a_supervisor_restart_with_the_same_worker_id_stops_the_old_instance_before_any_write(env, jpath):
    """The reviewer's scenario: A sends; while the request is out, a supervisor restarts the worker under the SAME
    worker id. B boots (Started), takes the lease (A's in-flight attempt becomes OUTCOME_UNKNOWN) and A's reply then
    comes back. A must not record the reply, raise `journal-refused`, or write anything else after B's Started."""
    journal_a, adapter, clock = env
    seen = {}

    def send_a(request):
        reply = adapter(request)
        if request.is_write() and "b" not in seen:  # the venue acted; B starts before A sees the reply
            journal_b = ExecutionJournal.open(jpath)
            seen["journal_b"] = journal_b
            seen["b"] = o.Orchestrator(journal_b, h.config(), send=adapter, feed=h.Feed(adapter),
                                       strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
            seen["events_after_b"] = journal_b.verify_chain().events
        return reply

    a = o.Orchestrator(journal_a, h.config(), send=send_a, feed=h.Feed(adapter), strategies=(h.DemoStrategy(),),
                       clock=clock, sleep=clock.sleep)
    assert a.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(a, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    a.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = a.run_cycle()

    journal_b, b = seen["journal_b"], seen["b"]
    assert report.fenced_out and a.fenced_out
    assert journal_b.verify_chain().events == seen["events_after_b"]  # A wrote nothing after B booted
    assert [type(e).__name__ for e in journal_b.control_events(h.SCOPE)][-1] == "Started"
    assert not any(e.incident_id.startswith("journal-refused") for e in journal_b.control_events(h.SCOPE)
                   if isinstance(e, ctl.IncidentRaised))
    (attempt,) = journal_b.attempts_for(f"{h.STRATEGY_ID}:s1")
    assert attempt.state is AttemptState.OUTCOME_UNKNOWN  # B's takeover made it unknown; A did not touch it
    with pytest.raises(o.OrchestratorFencedOut):
        a.run_cycle()
    with pytest.raises(o.OrchestratorFencedOut):
        a.request_arm(ctl.ArmRequest(ctl.Mode.OBSERVE_ONLY, "owner", (), m.utc_text(clock())))
    assert a.submit_signal(h.signal("s2", B72, at=clock(), limit="0.45")).reason == "FENCED_OUT"

    # B, the live worker, resolves A's attempt from the venue listing: found, never re-sent.
    clock.advance(60)
    rb = b.run_cycle()
    assert attempt.attempt_id in rb.resolved_unknown
    assert journal_b.attempt(attempt.attempt_id).state is AttemptState.ACKNOWLEDGED
    assert sum(1 for x in adapter.venue.list_orders() if x["client_order_id"] == attempt.client_order_id) == 1
    assert journal_b.verify_chain().ok
    journal_b.close()


def test_an_operator_call_after_an_unnoticed_takeover_writes_nothing(env):
    """The cached flag is not trusted: an operator action on an instance whose lease was taken over (and which has
    run no cycle since) re-reads the lease and refuses before writing."""
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    journal.reservations.acquire_lease(h.config().worker_id, timedelta(minutes=5), clock())  # same id, new fence
    events = journal.verify_chain().events
    assert not orch.fenced_out  # not yet noticed
    for act in (lambda: orch.disarm("owner", "x"), lambda: orch.set_latch(ctl.LatchScope.GLOBAL, "*", "x"),
                lambda: orch.acknowledge_incident("none", "owner")):
        with pytest.raises(o.OrchestratorFencedOut):
            act()
    assert orch.fenced_out and journal.verify_chain().events == events


def test_a_fenced_shutdown_after_an_unnoticed_takeover_writes_nothing(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    journal.reservations.acquire_lease(h.config().worker_id, timedelta(minutes=5), clock())
    events = journal.verify_chain().events
    report = orch.shutdown("owner", "maintenance", cancel_owned=True)
    assert report.cancels_requested == () and journal.verify_chain().events == events
    with pytest.raises(o.OrchestratorStopped):
        orch.run_cycle()


def test_run_stops_once_fenced_out_and_does_not_keep_reading_the_account(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    clock.advance(600)
    journal.reservations.acquire_lease("another-worker", timedelta(minutes=5), clock())
    events = journal.verify_chain().events
    before = len(adapter.requests)
    start = clock()
    reports = orch.run(5)
    assert len(reports) == 1 and reports[0].fenced_out and orch.fenced_out
    reads = len(adapter.requests) - before
    assert reads == reports[0].requests_used > 0  # the cycle that found out read once; nothing after it
    assert clock() == start  # no sleep after the fenced cycle
    with pytest.raises(o.OrchestratorFencedOut):
        orch.run_cycle()
    with pytest.raises(o.OrchestratorFencedOut):
        orch.run(3)
    assert len(adapter.requests) - before == reads and journal.verify_chain().events == events


def test_run_runs_every_cycle_while_the_lease_is_held(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    reports = orch.run(3)
    assert [r.fenced_out for r in reports] == [False, False, False]


def test_a_takeover_during_a_shutdown_cancel_send_records_nothing_after_it(env):
    """The lease is taken over (same worker id) while our cancel is out: the reply is not recorded here, no SHUTDOWN
    record is written, and the report still says what was requested."""
    journal, adapter, clock = env
    taken = {}

    def send(request):
        reply = adapter(request)
        if request.is_write() and request.endpoint.name == "ORDER_CANCEL" and not taken:
            journal.reservations.acquire_lease(h.config().worker_id, timedelta(minutes=5), clock())
            taken["events"] = journal.verify_chain().events
        return reply

    orch = o.Orchestrator(journal, h.config(), send=send, feed=h.Feed(adapter), strategies=(h.DemoStrategy(),),
                          clock=clock, sleep=clock.sleep)
    assert orch.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    orch.submit_signal(h.signal("rest", B72, at=clock(), limit="0.30", qty="2", tif="good_till_canceled"))
    (d,) = orch.run_cycle().decisions
    assert d.attempt_state == "ACKNOWLEDGED"
    clock.advance(60)
    report = orch.shutdown("owner", "end of day", cancel_owned=True)
    (rid,) = report.cancels_requested
    assert report.cancel_outcomes[rid].startswith("CANCEL_OUTCOME_UNKNOWN: the egress lease was lost")
    assert journal.verify_chain().events == taken["events"]
    assert not journal.control_records(h.SCOPE, "SHUTDOWN")
    with pytest.raises(o.OrchestratorStopped):
        orch.run_cycle()
