"""Stream recovery wired into the orchestrator (#160 package J). FIXTURE only: the stream is an in-memory fixture
source; there is no stream transport.

Decisions in a cycle are dropped when recovery reports their market invalidated (or the stream unproven) after the
strategies proposed; a gap is proven only by the next cycle's COMPLETE read; a reconnect cancels nothing."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution import recovery as rc
from edge_lab.execution.journal import ExecutionJournal
from edge_lab.execution_ticket import ObligationState

B70, B72, B74 = h.MARKETS
ORDERS, FILLS = rc.Channel.ORDERS, rc.Channel.FILLS
RCFG = rc.RecoveryConfig(max_items_per_window=200, max_opens_per_window=10, max_items_per_drain=50)


class FixtureStream:
    """An in-memory stream source: items are pushed by the test and drained by the orchestrator."""

    def __init__(self, clock: h.Clock):
        self.clock, self.queue, self.seq, self.sid, self.fail = clock, [], {}, 0, False
        self.sids: dict = {}
        self.drains, self.before_drain = 0, {}  # drain number -> a callable run just before that drain

    def drain(self, max_items: int) -> tuple:
        self.drains += 1
        if self.drains in self.before_drain:
            self.before_drain.pop(self.drains)()
        if self.fail:
            raise ConnectionError("fixture source down")
        out, self.queue = tuple(self.queue[:max_items]), self.queue[max_items:]
        return out

    def open(self) -> None:
        for channel in (ORDERS, FILLS):
            self.sid += 1
            self.sids[channel] = self.sid
            self.queue.append(rc.SubscriptionOpened(self.sid, channel, m.utc_text(self.clock())))

    def lose(self) -> None:
        self.queue.append(rc.ConnectionLost(m.utc_text(self.clock()), "fixture: socket closed"))

    def _next(self, channel, skip: int = 0) -> tuple[int, int]:
        sid = self.sids[channel]
        self.seq[sid] = self.seq.get(sid, 0) + 1 + skip
        return sid, self.seq[sid]

    def fill(self, market: str, *, fill_id: str, order_id: str, count: str = "1", skip: int = 0) -> None:
        sid, seq = self._next(FILLS, skip)
        self.queue.append(rc.StreamMessage(sid, seq, FILLS, rc.FillEvent(fill_id, order_id, market, Decimal(count),
                                                                         Decimal("0.44")),
                                           rc.Clocks(m.utc_text(self.clock()))))


class Hooked:
    """The demo strategy, plus a hook run while it proposes (after the cycle's stream marks were taken)."""

    def __init__(self, hook=None):
        self.inner, self.hook = h.DemoStrategy(), hook
        self.strategy_id, self.strategy_version = self.inner.strategy_id, self.inner.strategy_version
        self.model_hash, self.policy_hash = self.inner.model_hash, self.inner.policy_hash

    def propose(self, ctx):
        if self.hook is not None:
            self.hook(ctx)
        return self.inner.propose(ctx)


@pytest.fixture
def env(tmp_path):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(tmp_path / "j.execution.sqlite3")
    yield journal, adapter, clock
    journal.close()


def build(journal, adapter, clock, *, hook=None, mode=ctl.Mode.BOUNDED_AUTO, open_stream=True):
    stream = FixtureStream(clock)
    if open_stream:
        stream.open()
        clock.advance(2)  # the first read's venue data (as of its start minus 1 s) then post-dates the subscriptions
    strategy = Hooked(hook)
    orch = o.Orchestrator(journal, h.config(recovery=RCFG), send=adapter, feed=h.Feed(adapter),
                          strategies=(strategy,), clock=clock, sleep=clock.sleep, stream=stream)
    first = orch.run_cycle()
    assert first.reconciliation == "COMPLETE", first
    assert isinstance(h.arm(orch, mode, clock), ctl.ArmAccepted)
    clock.advance(60)
    return orch, stream, strategy


def writes(adapter):
    return [n for n in adapter.requests if n.startswith("ORDER_")]


def test_the_stream_and_its_configuration_come_together(env):
    journal, adapter, clock = env
    with pytest.raises(o.OrchestratorError):
        o.Orchestrator(journal, h.config(recovery=RCFG), send=adapter, feed=h.Feed(adapter),
                       strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
    with pytest.raises(o.OrchestratorError):
        o.Orchestrator(journal, h.config(), send=adapter, feed=h.Feed(adapter), strategies=(h.DemoStrategy(),),
                       clock=clock, sleep=clock.sleep, stream=FixtureStream(clock))


def test_the_first_complete_read_proves_the_baseline_and_a_clean_stream_lets_orders_through(env):
    journal, adapter, clock = env
    orch, stream, _ = build(journal, adapter, clock)
    assert orch.stream_state.connected and not orch.stream_state.quarantines
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    (d,) = report.decisions
    assert d.outcome is o.Outcome.SUBMITTED and report.stream["quarantines"] == ()
    with pytest.raises(TypeError):
        report.stream["incoming"] = 0  # the report's summary is read-only all the way down
    assert isinstance(report.stream["subscriptions"], tuple)
    cycle = journal.control_records(h.SCOPE, "CYCLE")[-1].body
    assert cycle["stream"]["connected"] is True and cycle["stream"]["incoming"] == 2


def manual_fill(adapter, ticker, client_id):
    """A real venue order of the account placed outside this service (a manual order), filled: (order id, fill id)."""
    order = adapter.venue.new_order(ticker=ticker, side=m.Side.YES, action=m.Action.BUY, count="1", price="0.45",
                                    time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL, client_order_id=client_id)
    order_id = order.body["order"]["order_id"]
    (fill_id,) = [f["fill_id"] for f in adapter.venue.list_fills(order_id)]
    adapter.sync()
    return order_id, fill_id


def test_a_fill_on_the_market_after_proposing_drops_the_decision_until_it_is_re_evaluated(env):
    journal, adapter, clock = env
    pushes = []

    def hook(ctx):
        if pushes:
            order_id, fill_id = pushes.pop()
            stream.fill(B70, fill_id=fill_id, order_id=order_id)

    orch, stream, _ = build(journal, adapter, clock, hook=hook)
    pushes.append(manual_fill(adapter, B70, "manual-70"))
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.46"))
    report = orch.run_cycle()
    (d,) = report.decisions
    assert d.outcome is o.Outcome.BLOCKED and d.reasons[0].startswith(f"STREAM_INVALIDATED: {B70} changed")
    assert writes(adapter) == [] and not journal.attempts_for(d.intent_key)  # dropped: never prepared or sent
    (record,) = [r for r in journal.control_records(h.SCOPE, "DECISION") if r.body["intent_key"] == d.intent_key]
    assert record.body["outcome"] == "BLOCKED"
    # Re-evaluated from fresh evidence: the next read agrees with the stream, and a new signal goes through.
    clock.advance(60)
    orch.submit_signal(h.signal("s2", B70, at=clock(), limit="0.46"))
    later = orch.run_cycle()
    (d2,) = later.decisions
    assert d2.outcome is o.Outcome.SUBMITTED, d2.reasons
    assert later.stream["findings"] == () and not later.incidents


def test_rest_stream_disagreement_is_an_incident_and_keeps_the_market_quarantined(env):
    journal, adapter, clock = env
    orch, stream, _ = build(journal, adapter, clock)
    stream.fill(B70, fill_id="ghost-fill", order_id="ghost-order")  # the venue's REST listing never has it
    clock.advance(1)
    orch.submit_signal(h.signal("s1", B72, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    assert report.reconciliation == "COMPLETE"
    assert any(i.startswith("stream-disagreement:ghost-order") for i in report.incidents)
    assert report.decisions == () and orch.state.mode is ctl.Mode.DISARMED  # disarmed before any decision
    assert [f[0] for f in report.stream["findings"]] == ["DISAGREEMENT"]
    assert [(q.reason, q.market_ticker) for q in orch.stream_state.quarantines] == [(rc.Reason.DISAGREEMENT, B70)]


def test_a_change_during_the_risk_gate_is_caught_by_the_check_just_before_acting(env):
    """Drains in a deciding cycle: 1 before the read, 2 before proposing (the marks), 3 when the decision starts,
    4 just before it acts. A fill arriving between 3 and 4 still drops the decision."""
    journal, adapter, clock = env
    orch, stream, _ = build(journal, adapter, clock)
    order_id, fill_id = manual_fill(adapter, B70, "manual-70")
    stream.drains = 0
    stream.before_drain[4] = lambda: stream.fill(B70, fill_id=fill_id, order_id=order_id)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.46"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and d.reasons[0].startswith(f"STREAM_INVALIDATED: {B70} changed")
    assert stream.drains == 4 and writes(adapter) == []


def test_concurrent_markets_a_fill_elsewhere_does_not_drop_the_decision(env):
    journal, adapter, clock = env
    order_id, fill_id = manual_fill(adapter, B72, "manual-72")
    fired = []

    def hook(ctx):
        if not fired:
            fired.append(1)
            stream.fill(B72, fill_id=fill_id, order_id=order_id)

    orch, stream, _ = build(journal, adapter, clock, hook=hook)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.SUBMITTED, d.reasons  # B72 changed, B70 did not
    clock.advance(60)
    report = orch.run_cycle()  # the stream's B72 fill agrees with REST: proven, no incident
    assert not any(i.startswith("stream-disagreement") for i in report.incidents)
    assert [f[0] for f in report.stream["findings"]] == []


def test_a_dropped_delta_blocks_every_market_until_the_next_cycles_read_proves_it(env):
    journal, adapter, clock = env
    gaps = []

    def hook(ctx):
        if gaps:
            gaps.pop()
            stream.fill(B74, fill_id="g1", order_id="manual-74", skip=1)  # seq 2 on a fresh sid: seq 1 was dropped

    orch, stream, _ = build(journal, adapter, clock, hook=hook)
    gaps.append(1)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and any("SEQUENCE_GAP" in r for r in d.reasons)
    assert orch.stream_state.reconciliation_required
    clock.advance(60)
    orch.run_cycle()  # the read starts after the gap: SEQUENCE_GAP is proven (the unknown fill is a disagreement)
    assert "SEQUENCE_GAP" not in [q.reason.value for q in orch.stream_state.quarantines]


def test_a_reconnect_cancels_nothing_and_blocks_until_resubscribed_and_proven(env):
    journal, adapter, clock = env
    orch, stream, _ = build(journal, adapter, clock)
    orch.submit_signal(h.signal("rest", B72, at=clock(), limit="0.30", qty="2", tif="good_till_canceled"))
    (d,) = orch.run_cycle().decisions
    assert d.attempt_state == "ACKNOWLEDGED"
    rid = d.attempt_id
    clock.advance(60)
    stream.lose()
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    (blocked,) = report.decisions
    assert blocked.outcome is o.Outcome.BLOCKED and blocked.reasons[0].startswith("STREAM_DOWN")
    assert journal.reservations.reservation(rid).state is ObligationState.OUTSTANDING  # still resting, ours
    assert [x["status"] for x in adapter.venue.list_orders() if x["client_order_id"] == d.intent_key.split(":")[0]
            or x["order_id"] == journal.attempt(rid).provider_order_id] == ["resting"]
    assert "ORDER_CANCEL" not in writes(adapter)
    clock.advance(60)
    stream.open()  # resubscribed: new sids, a new sequence scope
    blocked_again = orch.run_cycle()  # this read's venue data (as of its start minus 1 s) predates the resubscription
    assert any("BASELINE_REQUIRED" in q[0] for q in blocked_again.stream["quarantines"])
    clock.advance(2)  # proven by the next read, whose venue data post-dates it
    orch.submit_signal(h.signal("s2", B70, at=clock(), limit="0.45"))
    (d2,) = orch.run_cycle().decisions
    assert d2.outcome is o.Outcome.SUBMITTED, d2.reasons
    assert journal.reservations.reservation(rid).state is ObligationState.OUTSTANDING


def test_shadow_mode_drops_invalidated_decisions_too(env):
    journal, adapter, clock = env
    pushed = []

    def hook(ctx):
        if not pushed:
            pushed.append(1)
            stream.fill(B70, fill_id="sx", order_id="manual-s")

    orch, stream, _ = build(journal, adapter, clock, hook=hook, mode=ctl.Mode.SHADOW)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (d,) = orch.run_cycle().decisions
    assert d.outcome is o.Outcome.BLOCKED and d.reasons[0].startswith("STREAM_INVALIDATED")


def test_a_failing_source_or_a_full_drain_quarantines_and_the_cycle_goes_on(env):
    journal, adapter, clock = env
    flood = []

    def hook(ctx):
        if flood:
            flood.pop()
            stream.queue.extend(rc.BookObservation(B74, Decimal("0.42"), Decimal("0.44"),
                                                   rc.Clocks(m.utc_text(clock())))
                                for _ in range(RCFG.max_items_per_drain))

    orch, stream, _ = build(journal, adapter, clock, hook=hook)
    stream.fail = True
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    assert report.reconciliation == "COMPLETE"
    (d,) = report.decisions
    assert d.outcome is o.Outcome.BLOCKED and any("SOURCE_FAILED" in r for r in d.reasons)
    stream.fail = False
    clock.advance(60)
    flood.append(1)  # while the strategy proposes, a full drain's worth arrives: more may be waiting
    orch.submit_signal(h.signal("s2", B70, at=clock(), limit="0.45"))
    (d2,) = orch.run_cycle().decisions
    assert d2.outcome is o.Outcome.BLOCKED and any("BACKLOG" in r for r in d2.reasons)
    clock.advance(60)
    orch.submit_signal(h.signal("s3", B70, at=clock(), limit="0.45"))
    (d3,) = orch.run_cycle().decisions
    assert d3.outcome is o.Outcome.SUBMITTED, d3.reasons  # the next read proved both


def test_without_a_stream_nothing_changes(env):
    journal, adapter, clock = env
    orch, _ = h.build(journal, adapter)
    report = orch.run_cycle()
    assert report.stream is None and orch.stream_state is None
    assert "stream" not in journal.control_records(h.SCOPE, "CYCLE")[-1].body
