"""The supervised orchestrator (#160 package K): start, modes, bounds, signals, arbitration, restart and shutdown.
FIXTURE only: the `send` is a FakeVenue-backed adapter in tests (`test_orchestrator_harness`)."""

from __future__ import annotations

import ast
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
from edge_lab.execution.reservations import CashBasis

B70, B72, B74 = h.MARKETS
SRC = Path(o.__file__).resolve()


@pytest.fixture
def jpath(tmp_path: Path) -> Path:
    return tmp_path / "k.execution.sqlite3"


@pytest.fixture
def env(jpath):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(jpath)
    yield journal, adapter, clock
    journal.close()


def armed(journal, adapter, clock, mode=ctl.Mode.BOUNDED_AUTO, **kw):
    orch, feed = h.build(journal, adapter, **kw)
    first = orch.run_cycle()
    assert first.reconciliation == "COMPLETE", first
    outcome = h.arm(orch, mode, clock)
    assert isinstance(outcome, ctl.ArmAccepted), outcome
    clock.advance(60)
    return orch, feed


def by_outcome(report, outcome):
    return [d for d in report.decisions if d.outcome is outcome]


def writes(adapter):
    return [n for n in adapter.requests if n.startswith("ORDER_")]


# ---------------------------------------------------------------- the happy path and its records


def test_a_signal_becomes_one_order_and_its_fills_and_release_follow(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    assert orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45", qty="3")).accepted
    assert orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.44", qty="8", tif="good_till_canceled")).accepted
    r1 = orch.run_cycle()
    assert [d.attempt_state for d in by_outcome(r1, o.Outcome.SUBMITTED)] == ["ACKNOWLEDGED", "ACKNOWLEDGED"]
    clock.advance(60)
    r2 = orch.run_cycle()  # the account read shows the fills: recorded; the orders' ends make them BOUND
    assert r2.fills_recorded == 2
    clock.advance(60)
    r3 = orch.run_cycle()  # a snapshot strictly after the end releases the IOC; the GTC rests (partly filled)
    assert len(r3.released) == 1
    held = journal.reservations.held_reservations(h.SCOPE)
    assert [(r.quantity, r.filled_quantity) for r in held] == [(Decimal(8), Decimal(4))]
    assert [r.body["attempt_id"] for r in journal.control_records(h.SCOPE, "ATTRIBUTION")] == list(r3.released)
    assert journal.verify_chain().ok


# ---------------------------------------------------------------- start, restart and modes


def test_start_is_disarmed_through_boot_and_a_restart_never_rearms(env, jpath):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    assert orch.state.mode is ctl.Mode.BOUNDED_AUTO
    journal.close()
    again = ExecutionJournal.open(jpath)
    restarted, _ = h.build(again, adapter)
    assert restarted.state.mode is ctl.Mode.DISARMED and restarted.state.armed_grant_digest is None
    events = again.control_events(h.SCOPE)
    assert [type(e).__name__ for e in events].count("Started") == 2 and isinstance(events[-1], ctl.Started)
    assert restarted.fence_token == orch.fence_token + 1  # a new fence: the old one's attempts cannot send
    again.close()


@pytest.mark.parametrize("mode", [ctl.Mode.DISARMED, ctl.Mode.OBSERVE_ONLY])
def test_disarmed_and_observe_only_read_and_never_decide(env, mode):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    if mode is ctl.Mode.OBSERVE_ONLY:
        assert isinstance(h.arm(orch, mode, clock), ctl.ArmAccepted)
    orch.submit_signal(h.signal("s1", B70, at=clock()))
    report = orch.run_cycle()
    assert report.reconciliation == "COMPLETE" and report.decisions == () and writes(adapter) == []
    assert dict(report.signals) == {"NOT_ACTED": 1}


def test_shadow_runs_the_whole_chain_and_sends_nothing(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock, mode=ctl.Mode.SHADOW)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.30", qty="20"))  # over the TEST quantity limit
    report = orch.run_cycle()
    assert [d.outcome for d in report.decisions] == [o.Outcome.WOULD_SUBMIT, o.Outcome.BLOCKED]
    assert any(x.startswith("QUANTITY_LIMIT") for x in report.decisions[1].reasons)
    assert writes(adapter) == [] and journal.non_terminal_attempts() == []
    assert {r.body["outcome"] for r in journal.control_records(h.SCOPE, "DECISION")} == {"WOULD_SUBMIT", "BLOCKED"}


def test_human_confirmation_sends_only_with_a_valid_human_approval(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock, mode=ctl.Mode.HUMAN_CONFIRMATION)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    first = orch.run_cycle()
    assert [d.outcome for d in first.decisions] == [o.Outcome.AWAITING_APPROVAL] and writes(adapter) == []
    digest = first.decisions[0].intent_digest
    policy = m.ApprovalGrant(digest, h.SCOPE.key(), m.ApprovalMethod.POLICY, "x", m.utc_text(clock()),
                             m.utc_text(clock() + timedelta(minutes=5)), "n1", policy_ref="p")
    assert orch.submit_approval(policy) is False  # only a HUMAN approval is accepted here
    other = m.ApprovalGrant("c" * 64, h.SCOPE.key(), m.ApprovalMethod.HUMAN, "owner", m.utc_text(clock()),
                            m.utc_text(clock() + timedelta(minutes=5)), "n2")
    assert orch.submit_approval(other)  # an approval of another digest unlocks nothing
    orch.submit_signal(h.signal("s1b", B70, at=clock(), limit="0.45"))
    clock.advance(1)
    second = orch.run_cycle()
    assert [d.outcome for d in second.decisions] == [o.Outcome.AWAITING_APPROVAL]
    assert writes(adapter) == []


def test_human_confirmation_with_an_approval_bound_to_the_digest_sends(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock, mode=ctl.Mode.HUMAN_CONFIRMATION)
    sig = h.signal("s1", B70, at=clock(), limit="0.45")
    (proposal,) = h.DemoStrategy().propose(o.StrategyContext(
        h.SCOPE, clock(), 2, ctl.Mode.HUMAN_CONFIRMATION, (sig,), frozenset(), None, {}, (), {}))
    assert orch.submit_approval(m.ApprovalGrant(proposal.intent.digest(), h.SCOPE.key(), m.ApprovalMethod.HUMAN,
                                                "owner", m.utc_text(clock()),
                                                m.utc_text(clock() + timedelta(minutes=5)), "human-1"))
    orch.submit_signal(sig)
    report = orch.run_cycle()
    assert [(d.outcome, d.attempt_state) for d in report.decisions] == [(o.Outcome.SUBMITTED, "ACKNOWLEDGED")]


def test_demo_is_refused():
    with pytest.raises(o.OrchestratorError, match="ENVIRONMENT_NOT_AUTHORIZED"):
        h.config(scope=m.AccountScope(m.Environment.DEMO, "demo-acct"))
    with pytest.raises(o.OrchestratorError, match="ENVIRONMENT_NOT_AUTHORIZED"):
        h.config(scope=m.AccountScope(m.Environment.PRODUCTION, "prod-acct"))


def test_arming_demo_on_a_fixture_scope_is_refused_and_persisted(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    orch.run_cycle()
    outcome = h.arm(orch, ctl.Mode.DEMO, clock)
    assert isinstance(outcome, ctl.ArmRefused) and "DEMO_MODE_NEEDS_DEMO_SCOPE" in outcome.reasons
    assert orch.state.mode is ctl.Mode.DISARMED and journal.control_events(h.SCOPE)[-1] == outcome


# ---------------------------------------------------------------- placeholders and the FIXTURE assumption


def test_placeholder_limits_block_every_order(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock, risk=o.RiskInputs())
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and any(r.startswith("LIMITS_NOT_SET_BY_OWNER") for r in d.reasons)
    assert writes(adapter) == []


def test_without_the_declared_fixture_cash_basis_nothing_can_be_sent(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter, fixture_cash_basis=None)
    orch.run_cycle()
    snap = journal.reservations.latest_snapshot(h.SCOPE)
    assert snap.cash_basis is CashBasis.UNKNOWN  # account (package G) reports ACC-02 as unknown
    h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock)
    clock.advance(60)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and any(r.startswith("CASH_UNKNOWN") for r in d.reasons)
    assert writes(adapter) == []


# ---------------------------------------------------------------- signals


def test_signal_admission_refuses_out_of_identity_expired_future_duplicate_and_overflow(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter, signal_sources={h.STRATEGY_ID: frozenset({"fixture-signals"})},
                      bounds=o.CycleBounds(2, 2, 10, 3, 80, timedelta(seconds=30), timedelta(minutes=10)))
    now = clock()
    other = m.AccountScope(m.Environment.FIXTURE, "other-acct")
    cases = [(h.signal("a", B70, at=now, scope=other), "OUT_OF_IDENTITY: another account scope"),
             (h.signal("b", B70, at=now, strategy="nobody"), "OUT_OF_IDENTITY: no such enabled strategy"),
             (h.signal("c", B70, at=now, source="stranger"), "OUT_OF_IDENTITY: the source is not registered"),
             (h.signal("d", B70, at=now - timedelta(minutes=5)), "SIGNAL_EXPIRED"),
             (h.signal("e", B70, at=now + timedelta(minutes=1)), "SIGNAL_FROM_FUTURE"),
             (h.signal("f", B70, at=now, valid=timedelta(minutes=30)), "SIGNAL_VALIDITY_TOO_LONG")]
    for sig, why in cases:
        admission = orch.submit_signal(sig)
        assert not admission.accepted and admission.reason.startswith(why), (sig.signal_id, admission)
    assert orch.submit_signal(h.signal("g", B70, at=now)).accepted
    assert orch.submit_signal(h.signal("g", B70, at=now)).reason == "DUPLICATE_SIGNAL"
    assert orch.submit_signal(h.signal("h", B70, at=now)).accepted
    assert orch.submit_signal(h.signal("i", B70, at=now)).reason == "QUEUE_FULL"
    assert orch.run_cycle().signals_rejected == 8


def test_signals_expire_at_drain_and_the_drain_is_bounded(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock,
                    bounds=o.CycleBounds(10, 2, 10, 3, 80, timedelta(seconds=30), timedelta(minutes=10)))
    orch.submit_signal(h.signal("old", B70, at=clock(), valid=timedelta(seconds=30)))
    for i in range(3):
        orch.submit_signal(h.signal(f"s{i}", B72, at=clock()))
    clock.advance(31)
    report = orch.run_cycle()
    assert dict(report.signals) == {"DELIVERED": 1, "EXPIRED": 1}
    assert [s.signal_id for s in orch.queued_signals] == ["s1", "s2"]


def test_after_a_restart_an_expired_backlog_is_quarantined_never_replayed(env, jpath):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    orch.submit_signal(h.signal("short", B70, at=clock(), valid=timedelta(minutes=1)))
    orch.submit_signal(h.signal("long", B72, at=clock(), valid=timedelta(minutes=9)))
    journal.close()
    clock.advance(120)  # down for two minutes
    again = ExecutionJournal.open(jpath)
    restarted, _ = h.build(again, adapter)
    assert [s.signal_id for s in restarted.queued_signals] == ["long"]
    outcomes = {r.body["signal_id"]: r.body["outcome"] for r in again.control_records(h.SCOPE, "SIGNAL_OUTCOME")}
    assert outcomes == {"short": "QUARANTINED_RESTART"}
    boot = again.control_records(h.SCOPE, "BOOT")[-1].body
    assert boot["backlog_quarantined"] == ["short"] and boot["backlog_kept"] == ["long"]
    again.close()


# ---------------------------------------------------------------- arbitration and identity


def test_conflicting_signals_get_one_intent_per_market_and_reductions_go_first(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    orch.submit_signal(h.signal("buy", B70, at=clock(), limit="0.45", qty="3"))
    orch.run_cycle()
    clock.advance(60)
    orch.run_cycle()  # fills recorded; the position is in the snapshot
    clock.advance(60)
    orch.submit_signal(h.signal("yes", B70, at=clock(), limit="0.45", qty="1"))
    orch.submit_signal(h.signal("no", B70, at=clock(), side="no", limit="0.58", qty="1"))
    orch.submit_signal(h.signal("exit", B70, at=clock(), kind="EXIT", limit="0.40", qty="2"))
    report = orch.run_cycle()
    outcomes = {d.intent_key.split(":")[1]: d for d in report.decisions}
    assert {k: d.outcome for k, d in outcomes.items()} == {
        "exit": o.Outcome.SUBMITTED, "no": o.Outcome.BLOCKED, "yes": o.Outcome.BLOCKED}  # the reduction goes first
    assert all(r.startswith("ARBITRATION_ONE_INTENT_PER_MARKET") for k in ("no", "yes") for r in outcomes[k].reasons)


def test_the_intent_cap_holds_and_an_attempted_key_is_never_sent_again(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock,
                    bounds=o.CycleBounds(20, 10, 10, 1, 80, timedelta(seconds=30), timedelta(minutes=10)))
    orch.submit_signal(h.signal("a", B70, at=clock(), limit="0.45"))
    orch.submit_signal(h.signal("b", B72, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    outcomes = {d.intent_key.split(":")[1]: d for d in report.decisions}
    assert outcomes["a"].outcome is o.Outcome.SUBMITTED
    assert outcomes["b"].reasons == ("ARBITRATION_CYCLE_CAP: max_intents_per_cycle",)

    class Repeater(h.DemoStrategy):  # proposes the already-sent intent again, every cycle
        def propose(self, ctx):
            return super().propose(o.StrategyContext(ctx.scope, ctx.now, ctx.cycle, ctx.mode,
                                                     (h.signal("a", B70, at=ctx.now, limit="0.45"),), frozenset(),
                                                     ctx.positions, ctx.sellable, ctx.pending, ctx.markets))

    journal_writes = len(writes(adapter))
    again, _ = h.build(journal, adapter, strategies=(Repeater(),))
    again.run_cycle()
    assert isinstance(h.arm(again, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    repeat = again.run_cycle()
    assert repeat.decisions == () and repeat.proposals_ignored == 1
    assert len(writes(adapter)) == journal_writes


def test_a_strategy_outside_the_grant_is_blocked(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock, strategies=(h.DemoStrategy("other-strategy"),))
    orch.submit_signal(h.signal("s1", B70, at=clock(), strategy="other-strategy", limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and "GRANT_STRATEGY_ID_CHANGED" in d.reasons


def test_a_market_latch_stops_new_risk(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    orch.set_latch(ctl.LatchScope.MARKET, B70, "operator")
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and any(r.startswith("NEW_RISK_LATCHED") for r in d.reasons)


# ---------------------------------------------------------------- ambiguity: no retry, reconcile


@pytest.mark.parametrize("fault,resolved", [(Fault.DROP_ACK, AttemptState.ACKNOWLEDGED),
                                            (Fault.ACCEPT_THEN_TIMEOUT, AttemptState.ACKNOWLEDGED),
                                            (Fault.LOSE_REQUEST, AttemptState.ABSENT)])
def test_an_ambiguous_send_is_unknown_never_retried_and_reconciled_from_the_listing(env, fault, resolved):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    adapter.venue.inject(fault, operation=Operation.NEW_ORDER)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.attempt_state == "OUTCOME_UNKNOWN"
    orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.45"))  # new risk waits for reconciliation
    clock.advance(60)
    report = orch.run_cycle()
    assert report.resolved_unknown == (d.attempt_id,)
    assert journal.attempt(d.attempt_id).state is resolved
    assert writes(adapter).count("ORDER_CREATE") == 2  # the unknown one was never re-sent
    assert len(journal.attempts_for(d.intent_key)) == 1


def test_a_send_that_raises_is_unknown(env):
    journal, adapter, clock = env

    def broken(request):
        if request.is_write():
            raise ConnectionError("reset")
        return adapter(request)

    orch, feed = h.build(journal, adapter)
    orch.run_cycle()
    h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock)
    clock.advance(60)
    orch2 = o.Orchestrator(journal, h.config(), send=broken, feed=feed, strategies=(h.DemoStrategy(),), clock=clock,
                           sleep=clock.sleep)
    orch2.run_cycle()
    h.arm(orch2, ctl.Mode.BOUNDED_AUTO, clock)
    clock.advance(60)
    orch2.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch2.run_cycle().decisions
    assert d.attempt_state == "OUTCOME_UNKNOWN"
    assert journal.attempt(d.attempt_id).state_reason == "SEND_SEND_FAILED"


# ---------------------------------------------------------------- bounds, incidents and the lease


def test_the_request_budget_bounds_the_read_and_raises_an_incident(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter, bounds=o.CycleBounds(20, 6, 10, 3, 5, timedelta(seconds=30),
                                                             timedelta(minutes=10)))
    report = orch.run_cycle()
    assert report.requests_used == 5 and report.reconciliation != "COMPLETE"
    assert any(i.startswith("budget:") for i in report.incidents)


def test_the_cycle_deadline_stops_new_risk(env):
    journal, adapter, clock = env

    class SlowFeed(h.Feed):  # the market feed takes a minute: the cycle's deadline passes after the read
        def market_state(self, ticker, now):
            clock.advance(60)
            return super().market_state(ticker, clock())

    orch, _ = armed(journal, adapter, clock, feed=SlowFeed(adapter))
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    assert report.reconciliation == "COMPLETE" and report.deadline_hit
    assert [d.reasons for d in report.decisions] == [("CYCLE_DEADLINE: the cycle ran out of time",)]
    assert writes(adapter) == [] and any(i.startswith("deadline:") for i in report.incidents)


def test_a_failed_read_while_armed_disarms_and_rearming_needs_the_incident_named(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    adapter.reads_fail = True
    report = orch.run_cycle()
    assert report.reconciliation == "FAILED" and orch.state.mode is ctl.Mode.DISARMED
    (incident,) = orch.state.open_incidents
    adapter.reads_fail = False
    clock.advance(60)
    orch.run_cycle()
    refused = orch.request_arm(ctl.ArmRequest(ctl.Mode.BOUNDED_AUTO, "owner", (), m.utc_text(clock()),
                                              h.grant().digest()))
    assert isinstance(refused, ctl.ArmRefused)
    assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)


def test_a_lost_lease_fences_the_instance_out_it_reads_and_writes_nothing(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    clock.advance(600)  # past the lease
    journal.reservations.acquire_lease("another-worker", timedelta(minutes=5), clock())
    events = journal.verify_chain().events
    report = orch.run_cycle()
    assert report.fenced_out and orch.fenced_out and orch.fence_token is None
    assert report.reconciliation == "NOT_RUN" and report.requests_used > 0  # it read the account
    assert journal.verify_chain().events == events and writes(adapter) == []  # and wrote nothing at all
    assert orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45")).reason == "FENCED_OUT"
    with pytest.raises(o.OrchestratorFencedOut):
        orch.request_arm(ctl.ArmRequest(ctl.Mode.OBSERVE_ONLY, "owner", (), m.utc_text(clock())))


# ---------------------------------------------------------------- shutdown


def _resting(journal, adapter, clock):
    orch, _ = armed(journal, adapter, clock)
    orch.submit_signal(h.signal("rest", B72, at=clock(), limit="0.30", qty="2", tif="good_till_canceled"))
    report = orch.run_cycle()
    assert by_outcome(report, o.Outcome.SUBMITTED)
    manual = adapter.venue.new_order(ticker=B74, side=m.Side.YES, action=m.Action.BUY, count="1", price="0.20",
                                     time_in_force=m.TimeInForce.GOOD_TILL_CANCELED, client_order_id="manual-1")
    assert manual.outcome == "ok"
    clock.advance(60)
    orch.run_cycle()
    return orch


def test_shutdown_stops_new_risk_and_leaves_resting_orders_alone(env):
    journal, adapter, clock = env
    orch = _resting(journal, adapter, clock)
    report = orch.shutdown("owner", "maintenance")
    assert orch.state.mode is ctl.Mode.DISARMED and len(report.resting_left) == 1 and report.cancels_requested == ()
    assert sorted(x["status"] for x in adapter.venue.list_orders() if x["status"] == "resting") == ["resting"] * 2
    with pytest.raises(o.OrchestratorStopped):
        orch.run_cycle()
    assert orch.submit_signal(h.signal("late", B70, at=clock())).reason == "STOPPED"
    assert journal.control_records(h.SCOPE, "SHUTDOWN")[-1].body["cancel_owned"] is False


def test_a_fenced_out_process_does_not_cancel_or_write_at_shutdown(env):
    journal, adapter, clock = env
    orch = _resting(journal, adapter, clock)
    clock.advance(600)
    journal.reservations.acquire_lease("another-worker", timedelta(minutes=5), clock())
    events = journal.verify_chain().events
    report = orch.shutdown("owner", "end of day", cancel_owned=True)
    assert report.cancels_requested == () and "ORDER_CANCEL" not in writes(adapter)
    assert journal.verify_chain().events == events
    with pytest.raises(o.OrchestratorStopped):
        orch.run_cycle()


def test_shutdown_with_cancel_owned_cancels_only_our_orders(env):
    journal, adapter, clock = env
    orch = _resting(journal, adapter, clock)
    report = orch.shutdown("owner", "end of day", cancel_owned=True)
    assert list(report.cancel_outcomes.values()) == ["CANCEL_CONFIRMED"]
    statuses = {x["client_order_id"]: x["status"] for x in adapter.venue.list_orders()}
    assert statuses["manual-1"] == "resting"  # never anyone else's
    assert sorted(statuses.values()).count("canceled") == 1
    (rid,) = report.cancels_requested
    assert journal.reservations.reservation(rid).state.value == "BOUND"  # released only by a later snapshot


# ---------------------------------------------------------------- no scheduler, no capability


def test_run_sleeps_through_the_injected_sleep_only(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    start = clock()
    reports = orch.run(3)
    assert [r.cycle for r in reports] == [1, 2, 3] and clock() - start == timedelta(seconds=120)


def test_the_orchestrator_installs_no_timer_thread_or_process_and_imports_no_capability():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(("." * node.level) + (node.module or ""))
            modules |= {f"{'.' * node.level}{node.module or ''}.{a.name}" for a in node.names}
    banned = {"threading", "time", "sched", "asyncio", "signal", "subprocess", "multiprocessing", "concurrent"}
    assert not modules & banned, modules & banned
    assert not any("transport" in x or "signer" in x or "fake_venue" in x for x in modules), modules


# ---------------------------------------------------------------- review findings (regressions)


def test_f1_an_evidence_anomaly_disarms_before_any_decision_in_the_same_cycle(env):
    """An acknowledged GTC order of ours vanishes from a COMPLETE listing: the incident is raised before step 4, so
    the ENTRY queued for the same cycle is never sent."""
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    orch.submit_signal(h.signal("rest", B72, at=clock(), limit="0.30", qty="2", tif="good_till_canceled"))
    (d,) = orch.run_cycle().decisions
    assert d.attempt_state == "ACKNOWLEDGED"
    adapter.hidden_orders.add(journal.attempt(d.attempt_id).provider_order_id)
    clock.advance(60)
    orch.submit_signal(h.signal("new-risk", B70, at=clock(), limit="0.45"))
    before = len(writes(adapter))
    report = orch.run_cycle()
    assert report.reconciliation == "COMPLETE"
    assert any(i.startswith("order-missing:") for i in report.incidents)
    assert report.decisions == () and dict(report.signals) == {"NOT_ACTED": 1}
    assert len(writes(adapter)) == before and report.mode_at_end is ctl.Mode.DISARMED
    kinds = [type(e).__name__ for e in journal.control_events(h.SCOPE)]
    assert kinds[-2:] == ["ReconciliationObserved", "IncidentRaised"]  # the disarm precedes the cycle's decisions


def test_f2_a_stalled_worker_never_touches_the_live_workers_in_flight_attempt(env, jpath):
    """A stalls past its lease, B takes over and sends; A wakes up mid-send and runs a cycle. A must not mark B's
    PENDING_EGRESS attempt unknown (B's ack is then recorded), and A writes nothing at all."""
    journal_a, adapter, clock = env
    a, feed = armed(journal_a, adapter, clock)
    clock.advance(600)
    journal_b = ExecutionJournal.open(jpath)
    seen = {}

    def send_b(request):
        if request.is_write():  # B's attempt is committed PENDING_EGRESS; A wakes up now
            seen["events_before"] = journal_b.verify_chain().events
            seen["a"] = a.run_cycle()
            seen["events_after"] = journal_b.verify_chain().events
        return adapter(request)

    b = o.Orchestrator(journal_b, h.config(worker_id="worker-b"), send=send_b, feed=feed,
                       strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
    b.run_cycle()
    assert isinstance(h.arm(b, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
    clock.advance(60)
    b.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = b.run_cycle().decisions
    assert d.attempt_state == "ACKNOWLEDGED", d
    assert seen["a"].fenced_out and seen["events_after"] == seen["events_before"]
    assert a.fenced_out and journal_b.attempt(d.attempt_id).state_reason is None
    journal_b.close()


def test_f3_grant_usage_is_as_of_its_evidence_not_the_decision_time(env):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    orch.run_cycle()
    snap = journal.reservations.latest_snapshot(h.SCOPE)
    clock.advance(600)  # ten minutes with no new read
    now = clock()
    cy = o._Cycle(99, now, now, o._Budget(1, adapter), orch.state.mode)  # test-only: the usage seam
    usage = orch._usage(cy, h.grant(), journal.reservations.account_view(h.SCOPE), h.EVENT, now)
    assert usage.as_of_utc == snap.observed_at_utc
    intent = h.DemoStrategy().propose(o.StrategyContext(h.SCOPE, now, 99, orch.state.mode,
                                                        (h.signal("x", B70, at=now, limit="0.45"),), frozenset(),
                                                        None, {}, (), {}))[0].intent
    problems = ctl.grant_problems(h.grant(), intent, armed_grant_digest=h.grant().digest(), venue="kalshi",
                                  event_key=h.EVENT, usage=usage, model_hash=h.MODEL_HASH,
                                  policy_hash=h.POLICY_HASH, now=now)
    assert "GRANT_USAGE_STALE_OR_FUTURE" in problems


def test_f4_a_cancel_reply_for_another_order_confirms_nothing(env):
    journal, adapter, clock = env
    orch = _resting(journal, adapter, clock)
    adapter.cancel_ack_order_id = "fake-ord-999999"
    report = orch.shutdown("owner", "end of day", cancel_owned=True)
    assert [v.startswith("CANCEL_OUTCOME_UNKNOWN") for v in report.cancel_outcomes.values()] == [True]
    (rid,) = report.cancels_requested
    r = journal.reservations.reservation(rid)
    assert r.state.value == "UNKNOWN" and r.filled_quantity == 0  # held in full; reduced_by was never used
    assert journal.receipts(f"cancel-mismatch:{rid}")[0]["kind"] == "CANCEL_REPLY_MISMATCH"


def test_f5_the_fixture_cash_basis_fills_only_an_unknown_basis(env, monkeypatch):
    journal, adapter, clock = env
    from edge_lab.execution import account
    monkeypatch.setattr(account, "CASH_BASIS", CashBasis.AVAILABLE_AFTER_VENUE_HOLDS)  # as if ACC-02 were settled
    orch, _ = h.build(journal, adapter, fixture_cash_basis=CashBasis.UNKNOWN)
    orch.run_cycle()
    assert journal.reservations.latest_snapshot(h.SCOPE).cash_basis is CashBasis.AVAILABLE_AFTER_VENUE_HOLDS


def test_f6_decisions_never_rescan_history_and_memory_is_bounded(env, monkeypatch):
    journal, adapter, clock = env
    orch, _ = armed(journal, adapter, clock)
    for i in range(3):
        orch.submit_signal(h.signal(f"warm{i}", h.MARKETS[i], at=clock(), limit="0.45", qty="1"))
    orch.run_cycle()
    clock.advance(60)
    calls = []
    original = journal.attempts_for
    monkeypatch.setattr(journal, "attempts_for", lambda key: calls.append(key) or original(key))
    orch.submit_signal(h.signal("next", B70, at=clock(), limit="0.45", qty="1"))
    report = orch.run_cycle()
    assert report.decisions and calls == [d.intent_key for d in report.decisions if d.attempt_id]  # the new key only
    recent = o._Recent(3)
    for i in range(10):
        recent.add(i)
    assert len(recent) == 3 and 9 in recent and 0 not in recent
    for i in range(30):  # signal ids are kept only while they are still valid
        orch.submit_signal(h.signal(f"burst{i}", B74, at=clock(), valid=timedelta(seconds=30)))
        clock.advance(20)
        orch._queue.clear()  # test-only: keep the queue from filling
    assert len(orch._signal_ids) <= 2
