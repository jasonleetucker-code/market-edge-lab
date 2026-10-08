"""The account-aware shadow (#160 package M, ADR 0047). FIXTURE only: the account is a FakeVenue behind the harness
adapter (`test_orchestrator_harness`), and nothing leaves the process.

A READ_ONLY orchestrator in SHADOW mode runs the one decision chain and records a WOULD_SUBMIT or BLOCKED verdict for
every proposal, with the full intent and a hypothetical reservation, and can never send a write.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import test_orchestrator_harness as h
from edge_lab.execution import conformance
from edge_lab.execution import control as ctl
from edge_lab.execution import kalshi_wire as w
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution import risk_gate as g
from edge_lab.execution import shadow as sh
from edge_lab.execution.journal import ExecutionJournal
from edge_lab.execution.reservations import AccountView, ReservationAuthority

B70, B72, B74 = h.MARKETS
READ_ONLY = sh.ProcessIdentity.READ_ONLY


@pytest.fixture
def env(tmp_path: Path):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(tmp_path / "m.execution.sqlite3")
    yield journal, adapter, clock
    journal.close()


class Recorder:
    """The caller's send, recording every request that reaches it."""

    def __init__(self, inner):
        self.inner, self.seen = inner, []

    def __call__(self, request):
        self.seen.append(request)
        return self.inner(request)


class Unclamped(h.DemoStrategy):
    """Proposes exactly what its signals say: an EXIT is never clamped to what is sellable, and `headroom` sets the
    fee allowance per contract (DemoStrategy uses 0.04). `delay` seconds pass while it thinks (a slow strategy), and
    `peek` stamps its evidence that far in the future (a strategy that looked at what had not happened yet)."""

    def __init__(self, clock: h.Clock, *, delay: float = 0, peek: timedelta | None = None):
        super().__init__()
        self.clock, self.delay, self.peek = clock, delay, peek

    def propose(self, ctx: o.StrategyContext) -> tuple[o.Proposal, ...]:
        out = []
        for s in ctx.signals:
            side, limit, qty = m.Side(s.get("side")), Decimal(s.get("limit")), Decimal(s.get("qty"))
            headroom = Decimal(s.get("headroom") or "0.04")
            stamp = ctx.now + (self.peek or timedelta(0))
            ev = g.DecisionEvidence(evidence_id=f"sig:{s.signal_id}", strategy_id=self.strategy_id,
                                    strategy_version=self.strategy_version, model_version="m1",
                                    decided_at_utc=m.utc_text(stamp),
                                    sources=(g.SourceStamp(s.source_id, m.utc_text(stamp) if self.peek
                                                           else s.issued_at_utc),))
            entry = s.get("kind") == "ENTRY"
            intent = m.OrderIntent(
                intent_key=f"{self.strategy_id}:{s.signal_id}", strategy_id=self.strategy_id,
                strategy_version=self.strategy_version, scope=ctx.scope, market_ticker=s.market_ticker,
                kind=m.IntentKind.ENTRY if entry else m.IntentKind.REDUCTION, side=side,
                action=m.Action.BUY if entry else m.Action.SELL, quantity=qty, limit_price=limit,
                time_in_force=m.TimeInForce(s.get("tif")) if entry else m.TimeInForce.IMMEDIATE_OR_CANCEL,
                max_total_cost=qty * (limit + headroom) if entry else qty * headroom,
                expires_at_utc=m.utc_text(ctx.now + timedelta(minutes=10)), price_grid=h.CENT,
                quantity_grid=h.WHOLE, profile_version="kalshi-ordinary-v0", risk_policy_version=h.POLICY.policy_id,
                fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=not entry, evidence=(ev.evidence_id,))
            out.append(o.Proposal(intent, ev))
        self.clock.advance(self.delay)
        return tuple(out)


class FeeFeed(h.Feed):
    """The market's fee identity changes (a new schedule id the intent was not priced under)."""

    def __init__(self, adapter, fee_schedule_id: str):
        super().__init__(adapter)
        self.fee_schedule_id = fee_schedule_id

    def market_state(self, ticker, now):
        state = super().market_state(ticker, now)
        return None if state is None else replace(state, fee_schedule_id=self.fee_schedule_id)


def shadow_orch(journal, adapter, clock, *, send=None, feed=None, strategies=None, **kw) -> o.Orchestrator:
    base = dict(worker_id="shadow-m", grants=(), identity=READ_ONLY)
    base.update(kw)
    return o.Orchestrator(journal, h.config(**base), send=send or adapter, feed=feed or h.Feed(adapter),
                          strategies=strategies if strategies is not None else (h.DemoStrategy(),), clock=clock,
                          sleep=clock.sleep)


def armed_shadow(journal, adapter, clock, **kw) -> o.Orchestrator:
    orch = shadow_orch(journal, adapter, clock, **kw)
    first = orch.run_cycle()
    assert first.reconciliation == "COMPLETE", first
    assert isinstance(h.arm(orch, ctl.Mode.SHADOW, clock), ctl.ArmAccepted)
    clock.advance(60)
    return orch


def sig(signal_id, ticker, clock, **kw):
    fields = {k: kw.pop(k) for k in ("headroom",) if k in kw}
    s = h.signal(signal_id, ticker, at=clock(), **kw)
    if fields:
        s = replace(s, fields=s.fields + tuple(fields.items()))
    return s


def manual(adapter, ticker, side, action, qty, price, tif=m.TimeInForce.IMMEDIATE_OR_CANCEL, ref="manual-1"):
    """An order a person placed in the venue's own interface (or the venue's native auto-sell): not ours."""
    reply = adapter.venue.new_order(ticker=ticker, side=side, action=action, count=Decimal(qty), price=Decimal(price),
                                    time_in_force=tif, client_order_id=ref)
    assert reply.outcome == "ok", reply
    adapter.sync()
    return reply


def verdicts(journal):
    return [r.body for r in journal.control_records(h.SCOPE, sh.SHADOW_RECORD)]


def reasons_of(verdict) -> str:
    return " | ".join(verdict.reasons)


# ---------------------------------------------------------------- the verdict


def test_a_would_submit_carries_the_full_intent_and_a_hypothetical_reservation(env):
    journal, adapter, clock = env
    recorder = Recorder(adapter)
    orch = armed_shadow(journal, adapter, clock, send=recorder)
    assert orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45", qty="3")).accepted
    report = orch.run_cycle()
    (verdict,) = report.shadow_verdicts
    assert verdict.outcome == "WOULD_SUBMIT" and verdict.reasons == ()
    intent = verdict.intent
    r = verdict.reservation
    assert r.reservation_id == f"shadow:{intent.client_order_id()}#1" and r.fence_token == sh.SHADOW_FENCE
    assert (r.quantity, r.limit_price, r.cash_worst_case, r.filled_quantity) == (
        intent.quantity, intent.limit_price, intent.max_total_cost, Decimal(0))
    assert verdict.capacity.allowed and verdict.capacity.cash_required == intent.max_total_cost
    market = h.Feed(adapter).market_state(B70, clock())
    expected = w.build_create(intent, conformance.MarketTradingProfile(B70, 0, market.price_bands))
    assert verdict.request_digest == o.request_digest(expected)  # the exact request it would have sent

    (record,) = verdicts(journal)
    assert m.canonical_json(record) == m.canonical_json(verdict.to_record())
    assert o.intent_from_dict(record["intent"]).digest() == intent.digest() == record["intent_digest"]

    # Nothing was written to the venue; every request that reached the caller's send was a read.
    assert adapter.writes == [] and recorder.seen and all(not q.is_write() for q in recorder.seen)
    # Nothing real was created: no intent, attempt, approval or reservation, and the real capacity is unchanged.
    assert journal.attempts_for(intent.intent_key) == [] and journal.non_terminal_attempts() == []
    assert journal.reservations.held_reservations(h.SCOPE) == []
    assert journal.control_records(h.SCOPE, "INTENT_PLANNED") == ()
    real = journal.reservations.evaluate(intent, clock(), snapshot_max_age=timedelta(minutes=2))
    assert real.cash_required == verdict.capacity.cash_required and real.cash_available == \
        verdict.capacity.cash_available
    assert journal.verify_chain().ok


def test_hypothetical_reservations_hold_capacity_within_their_cycle_only(env):
    """The cycle's second entry sees the first one's hypothetical reservation, as it would see a real one; the next
    cycle starts again from the real account."""
    journal, adapter, clock = env
    adapter.venue.cash = Decimal("6")
    no_floor = o.RiskInputs(replace(h.POLICY, reserve_floor=Decimal(0)), h.LIMITS, h.TICKET)
    orch = armed_shadow(journal, adapter, clock, risk=no_floor)
    gtc = "good_till_canceled"
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45", qty="10", tif=gtc))  # 4.90 at most
    orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.45", qty="10", tif=gtc))
    first = orch.run_cycle()
    assert [v.outcome for v in first.shadow_verdicts] == ["WOULD_SUBMIT", "BLOCKED"]
    blocked = first.shadow_verdicts[1]
    assert "RESERVE_FLOOR" in reasons_of(blocked) or "CASH_CAPACITY_INSUFFICIENT" in reasons_of(blocked)
    assert not blocked.capacity.allowed
    assert blocked.capacity.cash_required == Decimal("9.8")  # the first verdict's 4.90 is held next to its own
    assert journal.reservations.held_reservations(h.SCOPE) == []  # ... in this cycle's memory only

    clock.advance(60)
    orch.submit_signal(h.signal("s3", B72, at=clock(), limit="0.45", qty="10", tif=gtc))
    second = orch.run_cycle()
    assert [v.outcome for v in second.shadow_verdicts] == ["WOULD_SUBMIT"]
    assert second.shadow_verdicts[0].capacity.cash_required == Decimal("4.9")


def test_a_cycle_s_hypothetical_orders_count_toward_its_order_rate(env):
    journal, adapter, clock = env
    tight = replace(h.TICKET, max_orders_per_window=1)
    orch = armed_shadow(journal, adapter, clock, risk=o.RiskInputs(h.POLICY, h.LIMITS, tight))
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    assert [v.outcome for v in report.shadow_verdicts] == ["WOULD_SUBMIT", "BLOCKED"]
    assert "TRADE_COUNT_LIMIT" in reasons_of(report.shadow_verdicts[1])


# ---------------------------------------------------------------- every relevant constraint


def test_a_forbidden_size_or_side_is_blocked(env):
    journal, adapter, clock = env
    manual(adapter, B74, m.Side.YES, m.Action.BUY, "2", "0.46")  # we hold 2 YES on B74 (a manual trade)
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock),))
    orch.submit_signal(sig("big", B70, clock, limit="0.45", qty="20"))  # over the TEST per-order quantity
    orch.submit_signal(sig("flip", B74, clock, side="no", limit="0.55", qty="1"))  # the opposite side of a holding
    orch.submit_signal(sig("oversell", B74, clock, kind="EXIT", side="yes", limit="0.40", qty="5"))  # 2 held
    report = orch.run_cycle()
    by_key = {v.intent.intent_key.split(":")[1]: v for v in report.shadow_verdicts}
    assert by_key["big"].outcome == "BLOCKED" and "QUANTITY_LIMIT" in reasons_of(by_key["big"])
    # One intent per market per cycle: the reduction (first in arbitration) is judged; the flip waits its turn.
    assert by_key["oversell"].outcome == "BLOCKED" and "INVENTORY_INSUFFICIENT" in reasons_of(by_key["oversell"])
    assert any("INSUFFICIENT_INVENTORY" in x for x in by_key["oversell"].capacity.reasons)
    assert by_key["flip"].outcome == "BLOCKED" and "ARBITRATION_ONE_INTENT_PER_MARKET" in reasons_of(by_key["flip"])
    assert by_key["flip"].capacity is None  # not asked: not "no obligations"
    clock.advance(60)
    orch.submit_signal(sig("flip2", B74, clock, side="no", limit="0.55", qty="1"))
    (flip,) = orch.run_cycle().shadow_verdicts
    assert flip.outcome == "BLOCKED" and "FLIP_FORBIDDEN" in reasons_of(flip)
    assert adapter.writes == []


def test_changed_fees_are_blocked(env):
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock),))
    orch.submit_signal(sig("thin", B70, clock, limit="0.45", qty="5", headroom="0"))  # no room for the fee
    (thin,) = orch.run_cycle().shadow_verdicts
    assert thin.outcome == "BLOCKED" and "FEE_HEADROOM_INSUFFICIENT" in reasons_of(thin)
    journal2 = journal  # same store, a new process whose market feed now names another fee schedule
    clock.advance(60)
    orch.shutdown("owner", "restart with the new feed")
    again = shadow_orch(journal2, adapter, clock, feed=FeeFeed(adapter, "kalshi-quadratic-taker-v2"),
                        strategies=(Unclamped(clock),))
    assert again.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(again, ctl.Mode.SHADOW, clock), ctl.ArmAccepted)
    clock.advance(60)
    again.submit_signal(sig("repriced", B70, clock, limit="0.45", qty="5"))
    (changed,) = again.run_cycle().shadow_verdicts
    assert changed.outcome == "BLOCKED" and "FEE_SCHEDULE_MISMATCH" in reasons_of(changed)


def test_manual_and_native_orders_are_included(env):
    journal, adapter, clock = env
    # A manual resting buy on B72 and, on B74, a holding of 3 with a resting sell of all 3 (a native auto-sell).
    manual(adapter, B72, m.Side.YES, m.Action.BUY, "5", "0.30", tif=m.TimeInForce.GOOD_TILL_CANCELED)
    manual(adapter, B74, m.Side.YES, m.Action.BUY, "3", "0.46", ref="manual-2")
    manual(adapter, B74, m.Side.YES, m.Action.SELL, "3", "0.60", tif=m.TimeInForce.GOOD_TILL_CANCELED,
           ref="native-auto-sell")
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock),))
    snap = journal.reservations.latest_snapshot(h.SCOPE)
    assert len(snap.external_orders) == 2  # both are listed: nothing outside our journal is ignored
    orch.submit_signal(sig("e70", B70, clock, limit="0.45", qty="2"))
    orch.submit_signal(sig("e72", B72, clock, limit="0.45", qty="2"))
    orch.submit_signal(sig("x74", B74, clock, kind="EXIT", side="yes", limit="0.40", qty="1"))
    report = orch.run_cycle()
    by_key = {v.intent.intent_key.split(":")[1]: v for v in report.shadow_verdicts}
    # Both external orders bind at their full worst case (FULL_NOTIONAL: 5 + 3 contracts at the most a contract can
    # cost) next to the candidate's own cost.
    assert by_key["e70"].outcome == "WOULD_SUBMIT"
    assert by_key["e70"].capacity.cash_required == 8 * m.MAX_COST_PER_CONTRACT + by_key["e70"].intent.max_total_cost
    # Any external order on the market, side unknown, could hold the other side: no entry there.
    assert by_key["e72"].outcome == "BLOCKED" and "FLIP_FORBIDDEN" in reasons_of(by_key["e72"])
    # The native sell already sells everything held: nothing is left to reduce.
    assert by_key["x74"].outcome == "BLOCKED" and "INVENTORY_INSUFFICIENT" in reasons_of(by_key["x74"])
    # Manual trading is untouched: no write, the venue's resting orders and cash are exactly as the person left them.
    assert adapter.writes == []
    assert sorted(o_["client_order_id"] for o_ in adapter.venue.list_orders() if o_["status"] == "resting") == [
        "manual-1", "native-auto-sell"]


def test_a_latch_blocks_the_shadow_verdict_too(env):
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock)
    orch.set_latch(ctl.LatchScope.MARKET, B70, "operator stop")
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (v,) = orch.run_cycle().shadow_verdicts
    assert v.outcome == "BLOCKED" and "NEW_RISK_LATCHED" in reasons_of(v)


# ---------------------------------------------------------------- stale and missing fail closed


def test_an_outdated_snapshot_fails_closed(env):
    journal, adapter, clock = env
    short = replace(h.TICKET, max_order_state_age=timedelta(seconds=5))
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock, delay=10),),
                        snapshot_max_age=timedelta(seconds=5), risk=o.RiskInputs(h.POLICY, h.LIMITS, short))
    orch.submit_signal(sig("slow", B70, clock, limit="0.45", qty="2"))
    (v,) = orch.run_cycle().shadow_verdicts  # the strategy took 10 s: the snapshot is 11 s old when judged
    assert v.outcome == "BLOCKED" and "ACCOUNT_SNAPSHOT_STALE" in reasons_of(v)
    assert any(x.startswith("SNAPSHOT_STALE") for x in v.capacity.reasons) and not v.capacity.allowed


def test_the_shadow_checks_what_prepare_attempt_would_check(env):
    """The gate passes (its own snapshot age is 2 min) but the reservation authority's capacity rule, the one
    `prepare_attempt` reserves with, refuses a snapshot older than `snapshot_max_age`: so does the shadow."""
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock, delay=10),),
                        snapshot_max_age=timedelta(seconds=5))
    orch.submit_signal(sig("slow", B70, clock, limit="0.45", qty="2"))
    (v,) = orch.run_cycle().shadow_verdicts
    assert v.outcome == "BLOCKED" and len(v.reasons) == 1
    assert v.reasons[0].startswith("PREPARE_REFUSED: SNAPSHOT_STALE")  # live's words (`PREPARE_REFUSED: <exc>`)


def test_would_be_sends_share_the_request_budget(env, tmp_path):
    journal, adapter, clock = env
    probe = armed_shadow(journal, adapter, clock)
    reads = probe.run_cycle().requests_used  # one cycle's account read
    clock.advance(60)
    probe.shutdown("owner", "probe done")
    bounds = replace(h.BOUNDS, max_requests_per_cycle=reads + 1)
    with ExecutionJournal.open(tmp_path / "budget.execution.sqlite3") as other:
        orch = armed_shadow(other, adapter, clock, bounds=bounds)
        orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
        orch.submit_signal(h.signal("s2", B72, at=clock(), limit="0.45"))
        report = orch.run_cycle()
        assert report.requests_used == reads  # nothing was sent
        assert [v.outcome for v in report.shadow_verdicts] == ["WOULD_SUBMIT", "BLOCKED"]
        assert report.shadow_verdicts[1].reasons == ("REQUEST_BUDGET_EXHAUSTED",)


def test_a_failed_read_in_shadow_disarms_and_judges_nothing(env):
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock)
    adapter.reads_fail = True
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    report = orch.run_cycle()
    assert report.reconciliation == "FAILED" and orch.state.mode is ctl.Mode.DISARMED
    assert report.shadow_verdicts == () and verdicts(journal) == [] and dict(report.signals) == {"NOT_ACTED": 1}


def test_absent_history_is_unknown_never_zero(env):
    journal, adapter, clock = env

    def no_fill_history(request):
        if request.endpoint.name in ("GET_FILLS", "GET_HISTORICAL_FILLS"):
            return h.Reply("UNAVAILABLE", None)
        return adapter(request)

    orch = shadow_orch(journal, adapter, clock, send=no_fill_history)
    first = orch.run_cycle()
    assert first.reconciliation != "COMPLETE"
    snap = journal.reservations.latest_snapshot(h.SCOPE)
    assert snap.cash is None  # unknown, not 0
    refused = h.arm(orch, ctl.Mode.SHADOW, clock)
    assert isinstance(refused, ctl.ArmRefused) and any("RECONCILIATION_NOT_COMPLETE" in r for r in refused.reasons)
    # The capacity rule itself: no snapshot is no capacity, with every figure unknown.
    intent = Unclamped(clock).propose(o.StrategyContext(h.SCOPE, clock(), 1, ctl.Mode.SHADOW, (
        sig("x", B70, clock, limit="0.45"),), frozenset(), None, {}, (), {}))[0].intent
    none = ReservationAuthority.decide(None, [], intent, clock(), snapshot_max_age=timedelta(minutes=2),
                                       candidate_id="c")
    assert not none.allowed and none.reasons[0].startswith("NO_ACCOUNT_SNAPSHOT")
    assert (none.cash_available, none.cash_required, none.snapshot_revision) == (None, None, None)


# ---------------------------------------------------------------- point in time and repeatability


def test_a_strategy_that_looks_ahead_is_blocked(env):
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock, strategies=(Unclamped(clock, peek=timedelta(minutes=5)),))
    orch.submit_signal(sig("ahead", B70, clock, limit="0.45", qty="2"))
    (v,) = orch.run_cycle().shadow_verdicts
    assert v.outcome == "BLOCKED"
    assert "DECISION_STALE" in reasons_of(v) and "SOURCE_STALE" in reasons_of(v)  # "stale or future"


def test_the_strategy_context_holds_no_outcome_and_a_recorded_verdict_never_changes(env):
    journal, adapter, clock = env
    assert set(o.StrategyContext.__dataclass_fields__) == {
        "scope", "now", "cycle", "mode", "signals", "backlog_signal_ids", "positions", "sellable", "pending",
        "markets"}  # no settlement, outcome, P&L or future fill: a new field here needs review
    orch = armed_shadow(journal, adapter, clock)
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    orch.run_cycle()
    before = [m.canonical_json(b) for b in verdicts(journal)]
    adapter.settle(B70, m.Side.YES)  # the outcome becomes known later
    clock.advance(60)
    orch.run_cycle()
    assert [m.canonical_json(b) for b in verdicts(journal)][:len(before)] == before
    assert journal.verify_chain().ok


def _scenario(tmp_path: Path, name: str) -> list[str]:
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    manual(adapter, B72, m.Side.YES, m.Action.BUY, "5", "0.30", tif=m.TimeInForce.GOOD_TILL_CANCELED)
    journal = ExecutionJournal.open(tmp_path / f"{name}.execution.sqlite3")
    try:
        orch = armed_shadow(journal, adapter, clock)
        for i, (ticker, limit, qty) in enumerate(((B70, "0.45", "3"), (B72, "0.45", "2"), (B74, "0.45", "20"))):
            orch.submit_signal(h.signal(f"s{i}", ticker, at=clock(), limit=limit, qty=qty))
        orch.run_cycle()
        return [m.canonical_json(b) for b in verdicts(journal)]
    finally:
        journal.close()


def test_verdicts_repeat_exactly_from_the_same_input_versions(tmp_path):
    first, second = _scenario(tmp_path, "a"), _scenario(tmp_path, "b")
    assert len(first) == 3 and first == second
    inputs = dict(json.loads(first[0])["inputs"])
    for name in ("intent", "policy", "limits", "evidence", "market", "book", "fee_schedule", "fee_verification",
                 "projection", "account_genesis", "pnl_history", "order_history", "shadow.snapshot_revision",
                 "shadow.snapshot_observed_at", "shadow.control_basis", "shadow.strategy_model_hash",
                 "shadow.ticket_limits", "verdict_schema"):
        assert inputs.get(name) is not None, name


def test_the_shadow_verdict_is_the_live_decision_up_to_egress(tmp_path):
    """The same proposals on the same account: the shadow's WOULD_SUBMIT is the request the executor sends, and the
    shadow's BLOCKED carries the executor's own gate reasons."""
    results = {}
    for name, identity, mode in (("shadow", READ_ONLY, ctl.Mode.SHADOW),
                                 ("live", sh.ProcessIdentity.EXECUTOR, ctl.Mode.BOUNDED_AUTO)):
        clock = h.Clock()
        adapter = h.VenueAdapter(clock)
        h.seed_books(adapter)
        journal = ExecutionJournal.open(tmp_path / f"{name}.execution.sqlite3")
        kw = dict(worker_id="shadow-m", grants=(), identity=identity) if identity is READ_ONLY else {}
        orch = o.Orchestrator(journal, h.config(**kw), send=adapter, feed=h.Feed(adapter),
                              strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
        assert orch.run_cycle().reconciliation == "COMPLETE"
        assert isinstance(h.arm(orch, mode, clock), ctl.ArmAccepted)
        clock.advance(60)
        orch.submit_signal(h.signal("ok", B70, at=clock(), limit="0.45", qty="3"))
        orch.submit_signal(h.signal("big", B72, at=clock(), limit="0.45", qty="20"))
        report = orch.run_cycle()
        results[name] = (report, journal, adapter)
    shadow_report, _, shadow_adapter = results["shadow"]
    live_report, live_journal, live_adapter = results["live"]
    s_big, s_ok = shadow_report.shadow_verdicts  # arbitration orders entries by intent key: big, then ok
    l_big, l_ok = live_report.decisions
    assert (s_ok.intent.intent_key, l_ok.intent_key) == ("synthetic-demo:ok",) * 2
    assert s_ok.intent.digest() == l_ok.intent_digest and l_ok.outcome is o.Outcome.SUBMITTED
    (attempt,) = live_journal.attempts_for(s_ok.intent.intent_key)
    assert attempt.request_digest == s_ok.request_digest  # byte for byte the request the executor sent
    assert s_ok.reservation.cash_worst_case == live_journal.reservations.reservation(
        attempt.reservation_id).cash_worst_case
    assert l_big.outcome is o.Outcome.BLOCKED and s_big.reasons == l_big.reasons
    assert shadow_adapter.writes == [] and live_adapter.writes
    for _, journal, _ in results.values():
        journal.close()


def _side_by_side(tmp_path: Path, name: str, identity: sh.ProcessIdentity, *, delay: float = 0, bounds=None,
                  **config_kw):
    """One fresh account and store, booted, reconciled, armed (SHADOW or BOUNDED_AUTO), then one cycle on one
    signal for B70 through `Unclamped(delay)`. Returns (report, journal); the caller closes the journal."""
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    journal = ExecutionJournal.open(tmp_path / f"{name}.execution.sqlite3")
    kw = dict(config_kw)
    if bounds is not None:
        kw["bounds"] = bounds
    if identity is READ_ONLY:
        kw.update(worker_id="shadow-m", grants=(), identity=identity)
    orch = o.Orchestrator(journal, h.config(**kw), send=adapter, feed=h.Feed(adapter),
                          strategies=(Unclamped(clock, delay=delay),), clock=clock, sleep=clock.sleep)
    assert orch.run_cycle().reconciliation == "COMPLETE"
    assert isinstance(h.arm(orch, ctl.Mode.SHADOW if identity is READ_ONLY else ctl.Mode.BOUNDED_AUTO, clock),
                      ctl.ArmAccepted)
    clock.advance(60)
    orch.submit_signal(sig("one", B70, clock, limit="0.45", qty="2"))
    report = orch.run_cycle()
    assert adapter.writes == [] or identity is not READ_ONLY
    return report, journal


@pytest.mark.parametrize("case,kw,first", [
    # the gate passes; prepare_attempt's reservation refuses a snapshot older than snapshot_max_age
    ("stale-snapshot", dict(delay=10, snapshot_max_age=timedelta(seconds=5)), "PREPARE_REFUSED: SNAPSHOT_STALE"),
    # a slow strategy outlives the egress lease: blocked before anything is planned, in both
    ("expired-lease", dict(delay=25, lease_ttl=timedelta(seconds=20)), "NO_EGRESS_LEASE: fence 1 expired at"),
])
def test_post_gate_refusals_are_live_s_own_words(tmp_path, case, kw, first):
    shadow_report, shadow_journal = _side_by_side(tmp_path, f"{case}-shadow", READ_ONLY, **kw)
    live_report, live_journal = _side_by_side(tmp_path, f"{case}-live", sh.ProcessIdentity.EXECUTOR, **kw)
    try:
        (verdict,) = shadow_report.shadow_verdicts
        (decision,) = live_report.decisions
        assert decision.outcome is o.Outcome.BLOCKED and verdict.outcome == "BLOCKED"
        assert decision.reasons[0].startswith(first), decision.reasons
        assert verdict.reasons == decision.reasons  # the same words, the same order
        assert live_journal.attempts_for(verdict.intent.intent_key) == []
        if case == "expired-lease":  # refused at egress: nothing was planned
            assert live_journal.control_records(h.SCOPE, "INTENT_PLANNED") == ()
    finally:
        shadow_journal.close()
        live_journal.close()


# ---------------------------------------------------------------- the shared pre-egress order (live and shadow)


def _reads_per_cycle(tmp_path: Path) -> int:
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    with ExecutionJournal.open(tmp_path / "reads-probe.execution.sqlite3") as journal:
        orch, _ = h.build(journal, adapter)
        orch.run_cycle()
        assert isinstance(h.arm(orch, ctl.Mode.BOUNDED_AUTO, clock), ctl.ArmAccepted)
        clock.advance(60)
        return orch.run_cycle().requests_used


@pytest.mark.parametrize("identity", [sh.ProcessIdentity.EXECUTOR, READ_ONLY])
def test_an_exhausted_budget_blocks_before_anything_is_planned(tmp_path, identity):
    bounds = replace(h.BOUNDS, max_requests_per_cycle=_reads_per_cycle(tmp_path))
    report, journal = _side_by_side(tmp_path, identity.value, identity, bounds=bounds)
    try:
        (decision,) = report.decisions
        assert decision.outcome is o.Outcome.BLOCKED and decision.reasons == ("REQUEST_BUDGET_EXHAUSTED",)
        assert journal.control_records(h.SCOPE, "INTENT_PLANNED") == ()  # the plan record follows the egress steps
        assert journal.non_terminal_attempts() == []
    finally:
        journal.close()


@pytest.mark.parametrize("identity", [sh.ProcessIdentity.EXECUTOR, READ_ONLY])
def test_the_lease_is_judged_before_the_budget(tmp_path, identity):
    bounds = replace(h.BOUNDS, max_requests_per_cycle=_reads_per_cycle(tmp_path))
    report, journal = _side_by_side(tmp_path, identity.value, identity, bounds=bounds, delay=25,
                                    lease_ttl=timedelta(seconds=20))
    try:
        (decision,) = report.decisions
        assert decision.outcome is o.Outcome.BLOCKED and len(decision.reasons) == 1
        assert decision.reasons[0].startswith("NO_EGRESS_LEASE: fence 1 expired at"), decision.reasons
    finally:
        journal.close()


def test_a_shadow_verdict_rejudged_from_new_inputs_is_recorded_again(env):
    """The same intent, outcome and reasons on a later snapshot is a new judgement: it is recorded (before, the
    dedupe on key, outcome and reasons alone dropped it)."""
    journal, adapter, clock = env

    class Fixed(Unclamped):
        def propose(self, ctx):  # one identical intent every cycle, blocked for the same reason (its size)
            ev = g.DecisionEvidence(evidence_id="fixed-ev", strategy_id=self.strategy_id,
                                    strategy_version=self.strategy_version, model_version="m1",
                                    decided_at_utc=m.utc_text(ctx.now),
                                    sources=(g.SourceStamp("fixture-signals", m.utc_text(ctx.now)),))
            intent = m.OrderIntent(
                intent_key=f"{self.strategy_id}:fixed", strategy_id=self.strategy_id,
                strategy_version=self.strategy_version, scope=ctx.scope, market_ticker=B70,
                kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY, quantity=Decimal(20),
                limit_price=Decimal("0.45"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("9.8"), expires_at_utc=m.utc_text(h.T0 + timedelta(hours=1)),
                price_grid=h.CENT, quantity_grid=h.WHOLE, profile_version="kalshi-ordinary-v0",
                risk_policy_version=h.POLICY.policy_id, fee_schedule_version="kalshi-quadratic-taker-v1",
                reduce_only=False, evidence=(ev.evidence_id,))
            return (o.Proposal(intent, ev),)

    orch = armed_shadow(journal, adapter, clock, strategies=(Fixed(clock),))
    first = orch.run_cycle()
    clock.advance(60)
    second = orch.run_cycle()
    (a,), (b,) = first.shadow_verdicts, second.shadow_verdicts
    assert a.intent.digest() == b.intent.digest() and (a.outcome, a.reasons) == (b.outcome, b.reasons)
    assert dict(a.inputs)["shadow.snapshot_revision"] != dict(b.inputs)["shadow.snapshot_revision"]
    assert len(verdicts(journal)) == 2
    assert dict(a.inputs)["shadow.strategy_model_hash"] == h.MODEL_HASH


def test_a_missing_strategy_hash_stays_unknown_in_the_verdict_inputs(env):
    journal, adapter, clock = env

    class NoHash(h.DemoStrategy):
        model_hash = None

    orch = armed_shadow(journal, adapter, clock, strategies=(NoHash(),))
    orch.submit_signal(h.signal("s1", B70, at=clock(), limit="0.45"))
    (v,) = orch.run_cycle().shadow_verdicts
    inputs = dict(v.inputs)
    assert inputs["shadow.strategy_model_hash"] is None and inputs["shadow.strategy_policy_hash"] == h.POLICY_HASH


# ---------------------------------------------------------------- the read-only identity


def _create(clock) -> w.WireRequest:
    intent = Unclamped(clock).propose(o.StrategyContext(h.SCOPE, clock(), 1, ctl.Mode.SHADOW, (
        sig("x", B70, clock, limit="0.45"),), frozenset(), None, {}, (), {}))[0].intent
    return w.build_create(intent, conformance.MarketTradingProfile(B70, 0, (h.CENT,)))


def test_the_read_only_sender_refuses_every_write_before_the_caller_s_send(env):
    _, adapter, clock = env
    inner = Recorder(adapter)
    send = sh.ReadOnlySender(inner)
    for request in (_create(clock), w.build_cancel(h.SCOPE, "ord-1", exchange_index=0),
                    w.build_decrease(h.SCOPE, "ord-1", exchange_index=0, reduce_by=Decimal(1))):
        with pytest.raises(sh.ShadowWriteRefused):
            send(request)
    for junk in (object(), "POST /portfolio/events/orders", None):
        with pytest.raises(sh.ShadowWriteRefused):
            send(junk)
    assert inner.seen == [] and adapter.writes == []
    assert send(w.build_get_balance(h.SCOPE)).outcome == "OK" and len(inner.seen) == 1
    with pytest.raises(ValueError):
        sh.ReadOnlySender(send)  # wrapped once, never re-wrapped into something that could unwrap it


class LyingRequest(w.WireRequest):
    """A WireRequest subclass that claims to be a read (review M1's probe): it is a create underneath."""

    def is_write(self) -> bool:
        return False

    @property
    def method(self) -> w.HttpMethod:
        return w.HttpMethod.GET


def test_a_request_subclass_that_lies_about_being_a_read_is_refused(env):
    _, adapter, clock = env
    real = _create(clock)
    liar = LyingRequest(real.endpoint, real.scope, real.path, real.query, real.body, real.exchange_index)
    assert liar.is_write() is False and liar.method is w.HttpMethod.GET  # what a method-trusting guard would see
    with pytest.raises(ValueError):  # the allowlist refuses it too, since #160 BF2 (exact type, ADR 0043 item 9)
        w.check_allowlisted(liar)
    inner = Recorder(adapter)
    with pytest.raises(sh.ShadowWriteRefused, match="LyingRequest"):
        sh.ReadOnlySender(inner)(liar)
    assert inner.seen == [] and adapter.writes == []

    class HonestSubclass(w.WireRequest):  # even a subclass of a genuine read is refused: only the type itself
        pass

    balance = w.build_get_balance(h.SCOPE)
    with pytest.raises(sh.ShadowWriteRefused):
        sh.ReadOnlySender(inner)(HonestSubclass(balance.endpoint, balance.scope, balance.path, balance.query))
    assert inner.seen == []


def test_the_sender_s_decision_comes_from_the_endpoint_spec_not_the_request(env, monkeypatch):
    """With both exact-type checks bypassed (the sender's and the allowlist's), the endpoint's own spec (bucket and
    method) still refuses a write."""
    _, adapter, clock = env
    real = _create(clock)
    liar = LyingRequest(real.endpoint, real.scope, real.path, real.query, real.body, real.exchange_index)
    inner = Recorder(adapter)
    sender = sh.ReadOnlySender(inner)
    monkeypatch.setattr(sh, "type", lambda _: w.WireRequest, raising=False)  # the probe: the type check passes
    monkeypatch.setattr(w, "type", lambda _: w.WireRequest, raising=False)  # and so does check_allowlisted's
    with pytest.raises(sh.ShadowWriteRefused, match="ORDER_CREATE is not a read"):
        sender(liar)
    assert inner.seen == []


def test_an_existing_read_only_sender_is_not_accepted_as_send(env):
    journal, adapter, clock = env
    for kw in (dict(worker_id="shadow-m", grants=(), identity=READ_ONLY), {}):
        with pytest.raises(o.OrchestratorError, match="ReadOnlySender"):
            o.Orchestrator(journal, h.config(**kw), send=sh.ReadOnlySender(adapter), feed=h.Feed(adapter),
                           strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
    assert journal.reservations.lease() is None  # refused before anything was written


def test_a_proxy_reaching_for_the_network_from_the_shadow_path_gets_only_the_read_only_sender(env):
    """The shadow path imports no transport or signer (the boundary invariants). At runtime the only network
    capability a READ_ONLY orchestrator holds is its `ReadOnlySender`: a component that reaches it anyway, even by its
    private name, cannot get a write past it."""
    journal, adapter, clock = env
    orch = armed_shadow(journal, adapter, clock)
    capability = orch._send  # noqa: SLF001 - the adversarial probe: everything the service could send through
    assert isinstance(capability, sh.ReadOnlySender)
    with pytest.raises(sh.ShadowWriteRefused):
        capability(_create(clock))
    assert adapter.writes == [] and not any(n.startswith("ORDER_") for n in adapter.requests)


@pytest.mark.parametrize("mode", [ctl.Mode.HUMAN_CONFIRMATION, ctl.Mode.BOUNDED_AUTO, ctl.Mode.DEMO])
def test_a_read_only_process_never_arms_a_sending_mode(env, mode):
    journal, adapter, clock = env
    orch = shadow_orch(journal, adapter, clock)
    assert orch.run_cycle().reconciliation == "COMPLETE"
    outcome = h.arm(orch, mode, clock, grant_digest=h.grant().digest() if mode is ctl.Mode.BOUNDED_AUTO else None)
    assert isinstance(outcome, ctl.ArmRefused) and outcome.reasons[0].startswith("READ_ONLY_IDENTITY")
    assert orch.state.mode is ctl.Mode.DISARMED
    assert isinstance(journal.control_events(h.SCOPE)[-1], ctl.ArmRefused)  # persisted, like every arm outcome


def test_a_read_only_process_holds_no_grant_and_cancels_nothing(env):
    journal, adapter, clock = env
    with pytest.raises(o.OrchestratorError, match="no automation grant"):
        h.config(worker_id="shadow-m", identity=READ_ONLY)
    with pytest.raises(o.OrchestratorError, match="worker id"):
        h.config(worker_id="worker-k", grants=(), identity=READ_ONLY)
    with pytest.raises(o.OrchestratorError, match="worker id"):
        h.config(worker_id="shadow-x")  # an executor never takes a shadow worker id
    orch = shadow_orch(journal, adapter, clock)
    with pytest.raises(o.OrchestratorError, match="READ_ONLY_IDENTITY"):
        orch.shutdown("owner", "stop", cancel_owned=True)
    assert orch.shutdown("owner", "stop").cancels_requested == ()


def test_a_shadow_never_runs_on_an_executor_store_and_an_executor_never_on_a_shadow_store(tmp_path):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    live_path, shadow_path = tmp_path / "live.execution.sqlite3", tmp_path / "shadow.execution.sqlite3"
    with ExecutionJournal.open(live_path) as live:
        h.build(live, adapter)  # an executor booted here and holds the store's egress lease
        lease, events = live.reservations.lease(), len(live.control_events(h.SCOPE))
        with pytest.raises(o.OrchestratorError, match="STORE_IDENTITY_MISMATCH"):
            shadow_orch(live, adapter, clock)
        assert live.reservations.lease() == lease and len(live.control_events(h.SCOPE)) == events  # untouched
    with ExecutionJournal.open(shadow_path) as store:
        shadow_orch(store, adapter, clock)
        with pytest.raises(o.OrchestratorError, match="STORE_IDENTITY_MISMATCH"):
            h.build(store, adapter)
        boot = store.control_records(h.SCOPE, "BOOT")[-1].body
        assert boot["identity"] == "READ_ONLY" and boot["worker_id"].startswith(sh.SHADOW_WORKER_PREFIX)


# Each store-identity guard alone (review LOW): every store below passes the other two guards.


def test_store_guard_lease_an_executor_of_another_scope_on_a_shadow_store(tmp_path):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.seed_books(adapter)
    other = m.AccountScope(m.Environment.FIXTURE, "other-acct")
    with ExecutionJournal.open(tmp_path / "s.execution.sqlite3") as store:
        shadow_orch(store, adapter, clock)  # the lease row is a shadow worker's; the BOOT is in h.SCOPE
        assert store.control_records(other, "BOOT") == ()  # nothing in the other scope: only the lease can tell
        lease = store.reservations.lease()
        with pytest.raises(o.OrchestratorError, match="STORE_IDENTITY_MISMATCH: an? EXECUTOR"):
            o.Orchestrator(store, h.config(scope=other, grants=()), send=adapter, feed=h.Feed(adapter),
                           strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
        assert store.reservations.lease() == lease


@pytest.mark.parametrize("booted,runs", [("EXECUTOR", READ_ONLY), ("READ_ONLY", sh.ProcessIdentity.EXECUTOR)])
def test_store_guard_boot_a_boot_record_without_a_lease_row(tmp_path, booted, runs):
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    with ExecutionJournal.open(tmp_path / "b.execution.sqlite3") as store:
        store.append_control_record(h.SCOPE, "BOOT", {"identity": booted, "worker_id": "x"}, now=clock())
        assert store.reservations.lease() is None and store.non_terminal_attempts() == []
        kw = dict(worker_id="shadow-m", grants=(), identity=runs) if runs is READ_ONLY else {}
        with pytest.raises(o.OrchestratorError, match="booted by another identity"):
            o.Orchestrator(store, h.config(**kw), send=adapter, feed=h.Feed(adapter),
                           strategies=(h.DemoStrategy(),), clock=clock, sleep=clock.sleep)
        assert store.reservations.lease() is None


def test_store_guard_attempts_a_store_with_an_attempt_in_flight(tmp_path):
    import test_journal_fixtures as f

    journal, token = f.ready(tmp_path / "a.execution.sqlite3")
    try:
        f.prepare(journal, f.entry(), token)  # an executor's attempt, PENDING_EGRESS
        # The lease then passes to a shadow worker id (after it expired): the lease guard sees a shadow store, no BOOT
        # record exists, and the takeover leaves the attempt OUTCOME_UNKNOWN, still in flight.
        journal.reservations.acquire_lease("shadow-m", f.TTL, f.NOW + f.TTL + timedelta(seconds=1))
        assert journal.non_terminal_attempts() and journal.control_records(h.SCOPE, "BOOT") == ()
        clock = h.Clock(f.NOW + f.TTL + timedelta(seconds=2))
        adapter = h.VenueAdapter(clock)
        with pytest.raises(o.OrchestratorError, match="attempts in flight"):
            shadow_orch(journal, adapter, clock)
    finally:
        journal.close()


def test_a_verdict_is_well_formed_or_refused(env):
    _, _, clock = env
    intent = Unclamped(clock).propose(o.StrategyContext(h.SCOPE, clock(), 1, ctl.Mode.SHADOW, (
        sig("x", B70, clock, limit="0.45"),), frozenset(), None, {}, (), {}))[0].intent
    real = ReservationAuthority.new_reservation(intent, reservation_id="r#1", fence_token=3, at_utc=m.utc_text(clock()))
    hypo = sh.hypothetical_reservation(intent, attempt_no=1, at_utc=m.utc_text(clock()))
    allowed = ReservationAuthority.decide(None, [], intent, clock(), snapshot_max_age=timedelta(minutes=2),
                                          candidate_id="c")
    allowed = replace(allowed, allowed=True, reasons=())
    ok = sh.ShadowVerdict(1, m.utc_text(clock()), intent, "WOULD_SUBMIT", (), hypo, allowed, "a" * 64, ())
    assert ok.digest() == sh.ShadowVerdict(1, m.utc_text(clock()), intent, "WOULD_SUBMIT", (), hypo, allowed,
                                           "a" * 64, ()).digest()
    for bad in (dict(outcome="SUBMITTED"), dict(reasons=("X",)), dict(reservation=None), dict(reservation=real),
                dict(capacity=None), dict(request_digest=None), dict(outcome="BLOCKED", reasons=("X",))):
        with pytest.raises(ValueError):
            replace(ok, **bad)
    view = AccountView(h.SCOPE.key(), None, (hypo,))
    assert view.held[0].fence_token == 0 and view.held[0].reservation_id.startswith("shadow:")
