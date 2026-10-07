"""Operating modes, actions, latches, incidents and automation grants (execution/control.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab.execution import control as c
from edge_lab.execution import model as m

UTC = timezone.utc
T0 = datetime(2026, 10, 7, 20, 0, tzinfo=UTC)
FIX = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
DEMO = m.AccountScope(m.Environment.DEMO, "demo-acct")
PROD = m.AccountScope(m.Environment.PRODUCTION, "prod-acct")
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE = m.Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("100000"))
H1, H2 = "a" * 64, "b" * 64
KW = dict(venue="kalshi", strategy_id="synthetic-demo", market_ticker="KXTEST-1")


def at(minutes: float = 0) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def now(minutes: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes)


def intent(**kw) -> m.OrderIntent:
    base = dict(intent_key="synthetic:1", strategy_id="synthetic-demo", strategy_version="v1", scope=FIX,
                market_ticker="KXTEST-26OCT07-T50", kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal("5"), limit_price=Decimal("0.40"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("2.10"), expires_at_utc=at(30), price_grid=CENT, quantity_grid=WHOLE,
                profile_version="kalshi-ordinary-v0", risk_policy_version="r1", fee_schedule_version="f1",
                reduce_only=False)
    base.update(kw)
    return m.OrderIntent(**base)


def reduction(**kw) -> m.OrderIntent:
    base = dict(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=True,
                time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL, max_total_cost=Decimal("0.10"))
    base.update(kw)
    return intent(**base)


def limits(**kw) -> c.GrantLimits:
    base = dict(max_order_cost=Decimal("5"), max_event_exposure=Decimal("10"), max_total_exposure=Decimal("20"),
                max_daily_turnover=Decimal("50"), max_daily_loss=Decimal("15"), max_drawdown=Decimal("25"))
    base.update(kw)
    return c.GrantLimits(**base)


def grant(**kw) -> c.AutomationGrant:
    base = dict(environment=m.Environment.FIXTURE, scope_key=FIX.key(), venue="kalshi", strategy_id="synthetic-demo",
                strategy_version="v1", model_hash=H1, policy_hash=H2, risk_policy_version="r1",
                fee_schedule_version="f1", profile_version="kalshi-ordinary-v0", universe=frozenset({"KXTEST-*"}),
                allowed_kinds=frozenset({m.IntentKind.ENTRY, m.IntentKind.REDUCTION}), limits=limits(),
                issued_at_utc=at(-60), expires_at_utc=at(600), issuer_ref="EXECUTION_PLAN:test")
    base.update(kw)
    return c.AutomationGrant(**base)


def usage(g: c.AutomationGrant, **kw) -> c.GrantUsage:
    base = dict(grant_digest=g.digest(), event_key="EVT-1", utc_day=T0.date().isoformat(), as_of_utc=at(-1),
                event_exposure=Decimal("0"), total_exposure=Decimal("0"), turnover_today=Decimal("0"),
                realized_loss_today=Decimal("0"), drawdown=Decimal("0"))
    base.update(kw)
    return c.GrantUsage(**base)


def check(g, i, u, **kw):
    args = dict(armed_grant_digest=g.digest(), venue="kalshi", event_key="EVT-1", usage=u, model_hash=H1,
                policy_hash=H2, now=T0)
    args.update(kw)
    return c.grant_problems(g, i, **args)


def arm(state, mode, *, grants=(), digest=None, acks=(), minutes=1):
    outcome = c.decide_arm(state, c.ArmRequest(mode, "owner", tuple(acks), at(minutes), digest), grants=grants,
                           now=now(minutes))
    return c.reduce(state, outcome), outcome


def reconciled(scope=FIX):
    return c.reduce(c.initial_state(scope), c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)))


def test_startup_is_disarmed_but_can_read_and_cancel_its_own_orders():
    s = c.initial_state(FIX)
    assert s.mode is c.Mode.DISARMED
    assert c.action_problems(s, c.ControlAction.READ, now=T0, **KW) == []
    assert c.action_problems(s, c.ControlAction.CANCEL_OWNED, now=T0, **KW) == []
    assert any("MODE_DOES_NOT_SEND" in p for p in c.action_problems(s, c.ControlAction.NEW_RISK, now=T0, **KW))
    s2, out = arm(s, c.Mode.OBSERVE_ONLY)  # observing is how a disarmed executor reconciles
    assert isinstance(out, c.ArmAccepted) and s2.mode is c.Mode.OBSERVE_ONLY


def test_unauthorized_environments_cannot_read_arm_or_send():
    for scope in (DEMO, PROD):
        s = reconciled(scope)
        assert any("ENVIRONMENT_NOT_AUTHORIZED" in p for p in c.action_problems(s, c.ControlAction.READ, now=T0, **KW))
        for mode in (c.Mode.OBSERVE_ONLY, c.Mode.SHADOW, c.Mode.DEMO, c.Mode.HUMAN_CONFIRMATION):
            assert isinstance(arm(s, mode)[1], c.ArmRefused), (scope, mode)
    assert any("DEMO_MODE_NEEDS_DEMO_SCOPE" in r for r in arm(reconciled(), c.Mode.DEMO)[1].reasons)


def test_shadow_and_sending_modes_need_complete_reconciliation():
    s = c.initial_state(FIX)
    for mode in (c.Mode.SHADOW, c.Mode.HUMAN_CONFIRMATION):
        assert any("RECONCILIATION_NOT_COMPLETE" in r for r in arm(s, mode)[1].reasons)
    assert arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)[0].mode is c.Mode.HUMAN_CONFIRMATION


def test_losing_reconciliation_raises_an_incident_that_must_be_acknowledged():
    s, _ = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    s = c.reduce(s, c.ReconciliationObserved(c.Reconciliation.FAILED, at(5)))
    assert s.mode is c.Mode.DISARMED and len(s.open_incidents) == 1
    s = c.reduce(s, c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(6)))
    assert any("INCIDENTS_NOT_ACKNOWLEDGED" in r for r in arm(s, c.Mode.HUMAN_CONFIRMATION, minutes=7)[1].reasons)
    s2, out = arm(s, c.Mode.HUMAN_CONFIRMATION, acks=s.open_incidents, minutes=7)
    assert isinstance(out, c.ArmAccepted) and s2.open_incidents == ()


def test_incidents_can_be_acknowledged_without_arming():
    s = c.reduce(reconciled(), c.IncidentRaised("inc-1", "lost ack", at(2)))
    s = c.reduce(s, c.IncidentAcknowledged("inc-1", "owner", at(3)))
    assert s.open_incidents == () and s.mode is c.Mode.DISARMED


def test_replay_applies_stored_outcomes_and_never_re_decides():
    """Regression: an arm refused live (grant expired by then) must stay refused after restart, and the incident it
    did not clear must stay open."""
    g = grant(expires_at_utc=at(10))
    s = c.reduce(reconciled(), c.IncidentRaised("inc-1", "x", at(1)))
    refused = c.decide_arm(s, c.ArmRequest(c.Mode.BOUNDED_AUTO, "owner", ("inc-1",), at(2), g.digest()), grants=(g,),
                           now=now(30))  # judged live at T+30: the grant has expired
    assert isinstance(refused, c.ArmRefused)
    events = (c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)), c.IncidentRaised("inc-1", "x", at(1)), refused)
    after = c.replay(FIX, events)
    assert after.mode is c.Mode.DISARMED and after.open_incidents == ("inc-1",)
    assert any("REFUSED" in line for line in after.log)


def test_restart_is_disarmed_and_keeps_latches_closeouts_and_incidents():
    s, accepted = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    events = (c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)), accepted,
              c.SetLatch(c.LatchScope.MARKET, "kxtest-1", "manual stop", at(2)),
              c.CloseoutAuthorized(c.LatchScope.MARKET, "KXTEST-1", "owner", at(3), at(60)),
              c.IncidentRaised("inc-9", "lost ack", at(4)))
    after = c.replay(FIX, events)
    assert after.mode is c.Mode.DISARMED and after.reconciliation is c.Reconciliation.NOT_RUN
    assert (c.LatchScope.MARKET, "KXTEST-1") in after.latches and after.closeouts
    assert after.open_incidents == ("inc-9",)
    assert c.replay(FIX, events[:2]).mode is c.Mode.DISARMED  # an armed mode is never restored


def test_latch_keys_are_normalized():
    s, _ = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    s = c.reduce(s, c.SetLatch(c.LatchScope.VENUE, "Kalshi", "kill", at(2)))
    assert any("NEW_RISK_LATCHED" in p for p in c.action_problems(s, c.ControlAction.NEW_RISK, now=T0, **KW))


def bounded(g=None):
    g = g or grant()
    s, out = arm(reconciled(), c.Mode.BOUNDED_AUTO, grants=(g,), digest=g.digest())
    assert isinstance(out, c.ArmAccepted), out
    return s, g


def test_bounded_auto_stops_when_its_grant_expires():
    s, g = bounded(grant(expires_at_utc=at(10)))
    assert c.action_problems(s, c.ControlAction.NEW_RISK, now=now(5), grants=(g,), **KW) == []
    assert any("GRANT_EXPIRED" in p for p in c.action_problems(s, c.ControlAction.NEW_RISK, now=now(10), grants=(g,), **KW))
    assert any("GRANT_MISSING" in p for p in c.action_problems(s, c.ControlAction.NEW_RISK, now=now(5), grants=(), **KW))


def test_reductions_under_a_latch_need_an_explicit_closeout_in_bounded_auto():
    s, g = bounded()
    s = c.reduce(s, c.SetLatch(c.LatchScope.GLOBAL, "*", "kill", at(2)))
    args = dict(now=now(3), grants=(g,), **KW)
    assert any("NEW_RISK_LATCHED" in p for p in c.action_problems(s, c.ControlAction.NEW_RISK, **args))
    assert any("REDUCTION_UNDER_LATCH_NEEDS_CLOSEOUT" in p for p in c.action_problems(s, c.ControlAction.REDUCE, **args))
    assert any("CLOSEOUT_NOT_AUTHORIZED" in p for p in c.action_problems(s, c.ControlAction.CLOSEOUT, **args))
    s = c.reduce(s, c.CloseoutAuthorized(c.LatchScope.GLOBAL, "*", "owner", at(4), at(30)))
    assert c.action_problems(s, c.ControlAction.REDUCE, **args) == []
    assert c.action_problems(s, c.ControlAction.CLOSEOUT, **args) == []
    human, _ = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    human = c.reduce(human, c.SetLatch(c.LatchScope.GLOBAL, "*", "kill", at(2)))
    assert c.action_problems(human, c.ControlAction.REDUCE, now=now(3), **KW) == []  # each order is human-approved


def test_bounded_auto_needs_a_valid_recorded_grant_to_arm():
    g = grant()
    assert any("GRANT_MISSING" in r for r in arm(reconciled(), c.Mode.BOUNDED_AUTO, digest=g.digest())[1].reasons)
    other = grant(scope_key=m.AccountScope(m.Environment.FIXTURE, "other").key())
    assert any("GRANT_SCOPE_MISMATCH" in r for r in
               arm(reconciled(), c.Mode.BOUNDED_AUTO, grants=(other,), digest=other.digest())[1].reasons)
    assert any("GRANT_UNEXPECTED" in r for r in arm(reconciled(), c.Mode.HUMAN_CONFIRMATION, digest=g.digest())[1].reasons)


def test_grant_binds_every_version_hash_venue_universe_kind_and_limit():
    g = grant()
    assert check(g, intent(), usage(g)) == []
    expect = {"GRANT_MODEL_CHANGED": dict(model_hash="c" * 64), "GRANT_POLICY_CHANGED": dict(policy_hash="c" * 64),
              "GRANT_VENUE_MISMATCH": dict(venue="polymarket_us")}
    for code, kw in expect.items():
        assert any(code in p for p in check(g, intent(), usage(g), **kw)), code
    for field, value in (("strategy_version", "v2"), ("risk_policy_version", "r2"), ("fee_schedule_version", "f2"),
                         ("profile_version", "other")):
        assert any(f"GRANT_{field.upper()}_CHANGED" in p for p in check(g, intent(**{field: value}), usage(g))), field
    assert any("GRANT_UNIVERSE" in p for p in check(g, intent(market_ticker="KXOTHER-1"), usage(g)))
    only_red = grant(allowed_kinds=frozenset({m.IntentKind.REDUCTION}))
    assert any("GRANT_KIND" in p for p in check(only_red, intent(), usage(only_red)))
    big = intent(quantity=Decimal("13"), max_total_cost=Decimal("5.21"))
    assert any("GRANT_ORDER_COST" in p for p in check(g, big, usage(g)))
    for code, kw in (("GRANT_EVENT_EXPOSURE", dict(event_exposure=Decimal("8"))),
                     ("GRANT_TOTAL_EXPOSURE", dict(total_exposure=Decimal("18"))),
                     ("GRANT_TURNOVER", dict(turnover_today=Decimal("48"))),
                     ("GRANT_DAILY_LOSS_REACHED", dict(realized_loss_today=Decimal("15"))),
                     ("GRANT_DRAWDOWN_REACHED", dict(drawdown=Decimal("25")))):
        assert any(code in p for p in check(g, intent(), usage(g, **kw))), code
    exact = usage(g, event_exposure=Decimal("7.90"), total_exposure=Decimal("17.90"), turnover_today=Decimal("47.90"))
    assert check(g, intent(), exact) == []  # exactly at each limit after this order is allowed


def test_reduction_turnover_counts_the_notional_sold():
    g = grant()
    sale = reduction(quantity=Decimal("100"), limit_price=Decimal("0.90"))  # $90 notional, $0.10 fee ceiling
    assert c.turnover_increment(sale) == Decimal("90.10")
    assert any("GRANT_TURNOVER" in p for p in check(g, sale, usage(g, turnover_today=Decimal("0"))))
    assert not any("GRANT_DAILY_LOSS" in p for p in
                   check(g, reduction(), usage(g, realized_loss_today=Decimal("99"))))  # losses stop entries, not exits


def test_usage_must_be_anchored_fresh_and_known():
    g = grant()
    for code, kw in (("GRANT_USAGE_FOR_ANOTHER_GRANT", dict(grant_digest="d" * 64)),
                     ("GRANT_USAGE_FOR_ANOTHER_EVENT", dict(event_key="EVT-2")),
                     ("GRANT_USAGE_FOR_ANOTHER_DAY", dict(utc_day="2026-10-06")),
                     ("GRANT_USAGE_STALE_OR_FUTURE", dict(as_of_utc=at(-6))),
                     ("GRANT_USAGE_STALE_OR_FUTURE", dict(as_of_utc=at(1))),
                     ("GRANT_USAGE_UNKNOWN: exposure", dict(event_exposure=None)),
                     ("GRANT_USAGE_UNKNOWN: turnover", dict(turnover_today=None)),
                     ("GRANT_USAGE_UNKNOWN: losses", dict(drawdown=None))):
        assert any(code in p for p in check(g, intent(), usage(g, **kw))), code


def test_any_grant_change_changes_its_digest():
    g = grant()
    variants = [grant(universe=frozenset({"KXTEST-*", "KXMORE-*"})), grant(expires_at_utc=at(601)),
                grant(limits=limits(max_drawdown=Decimal("26"))), grant(model_hash="c" * 64),
                grant(issuer_ref="EXECUTION_PLAN:other"), grant(fee_schedule_version="f2"), grant(venue="other")]
    assert len({v.digest() for v in variants} | {g.digest()}) == len(variants) + 1


@pytest.mark.parametrize("kw", [dict(model_hash="short"), dict(universe=frozenset()), dict(universe=frozenset({"x y"})),
                                dict(allowed_kinds=frozenset()), dict(expires_at_utc=at(-60)),
                                dict(environment="FIXTURE"), dict(venue=""), dict(issued_at_utc="2026-10-07T20:00:00")])
def test_grant_construction_is_strict(kw):
    with pytest.raises(ValueError):
        grant(**kw)


@pytest.mark.parametrize("bad", [0.5, True, "-1", float("nan")])
def test_limits_and_usage_are_exact(bad):
    with pytest.raises((ValueError, m.ExactValueError)):
        limits(max_order_cost=bad)
    with pytest.raises((ValueError, m.ExactValueError)):
        usage(grant(), total_exposure=bad)


@pytest.mark.parametrize("make", [
    lambda: c.ArmRequest("BOUNDED_AUTO", "owner", (), at(0)),
    lambda: c.ArmRequest(c.Mode.SHADOW, "", (), at(0)),
    lambda: c.ArmRequest(c.Mode.SHADOW, "owner", (), "not-a-time"),
    lambda: c.ArmRequest(c.Mode.SHADOW, "owner", (), "2026-10-07T20:00:00"),
    lambda: c.SetLatch(c.LatchScope.MARKET, " ", "x", at(0)),
    lambda: c.IncidentRaised("", "x", at(0)),
    lambda: c.ReconciliationObserved("COMPLETE", at(0)),
])
def test_events_are_validated_at_construction(make):
    with pytest.raises(ValueError):
        make()


def test_the_log_records_every_event():
    s, _ = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    s = c.reduce(s, c.Disarm("owner", "end of session", at(9)))
    assert s.mode is c.Mode.DISARMED and len(s.log) == 3 and "DISARM by owner" in s.log[-1]


def test_a_stale_acceptance_cannot_arm():
    """Regression (N1): events landing between the decision and its outcome invalidate the outcome."""
    s = reconciled()
    accepted = c.decide_arm(s, c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", (), at(1)), grants=(), now=now(1))
    assert isinstance(accepted, c.ArmAccepted)
    for between in (c.ReconciliationObserved(c.Reconciliation.FAILED, at(1.5)), c.IncidentRaised("inc-x", "x", at(1.5)),
                    c.SetLatch(c.LatchScope.GLOBAL, "*", "kill", at(1.5))):
        after = c.reduce(c.reduce(s, between), accepted)
        assert after.mode is c.Mode.DISARMED and "STALE_DECISION" in after.log[-1], between
    assert c.reduce(s, accepted).mode is c.Mode.HUMAN_CONFIRMATION


def test_closeouts_need_an_active_latch_and_expire():
    s, g = bounded()
    s = c.reduce(s, c.CloseoutAuthorized(c.LatchScope.MARKET, "KXTEST-1", "owner", at(2), at(30)))
    assert not s.closeouts and "CLOSEOUT REFUSED" in s.log[-1]  # authorized before its latch existed: ignored
    s = c.reduce(s, c.SetLatch(c.LatchScope.MARKET, "KXTEST-1", "stop", at(3)))
    s = c.reduce(s, c.CloseoutAuthorized(c.LatchScope.MARKET, "KXTEST-1", "owner", at(4), at(10)))
    assert c.action_problems(s, c.ControlAction.REDUCE, now=now(5), grants=(g,), **KW) == []
    assert any("REDUCTION_UNDER_LATCH_NEEDS_CLOSEOUT" in p for p in
               c.action_problems(s, c.ControlAction.REDUCE, now=now(10), grants=(g,), **KW))  # lapsed


def test_grant_problems_require_the_armed_grant():
    g, other = grant(), grant(issuer_ref="EXECUTION_PLAN:other")
    assert any("GRANT_NOT_ARMED" in p for p in check(other, intent(), usage(other), armed_grant_digest=g.digest()))
    assert any("GRANT_NOT_ARMED" in p for p in check(g, intent(), usage(g), armed_grant_digest=None))


def test_unknown_losses_block_entries_only():
    g = grant()
    assert any("GRANT_USAGE_UNKNOWN: losses" in p for p in check(g, intent(), usage(g, drawdown=None)))
    assert not any("losses" in p for p in check(g, reduction(), usage(g, drawdown=None)))


def test_reconciliation_lost_incident_ids_are_valid_identifiers():
    s, _ = arm(reconciled(), c.Mode.HUMAN_CONFIRMATION)
    s = c.reduce(s, c.ReconciliationObserved(c.Reconciliation.FAILED, at(5)))
    (incident,) = s.open_incidents
    c.IncidentAcknowledged(incident, "owner", at(6))  # constructs: the generated id is a valid identifier


@pytest.mark.parametrize("make", [
    lambda: c.ArmAccepted("HUMAN_CONFIRMATION", "owner", (), None, at(0), "a" * 64),
    lambda: c.ArmAccepted(c.Mode.BOUNDED_AUTO, "owner", (), None, at(0), "a" * 64),
    lambda: c.ArmAccepted(c.Mode.SHADOW, "owner", (), None, "bad", "a" * 64),
    lambda: c.ArmAccepted(c.Mode.SHADOW, "owner", (), None, at(0), "nope"),
    lambda: c.ArmRefused(c.Mode.SHADOW, "owner", (), at(0)),
    lambda: c.IncidentAcknowledged("", "owner", at(0)),
    lambda: c.CloseoutAuthorized(c.LatchScope.GLOBAL, "*", "owner", at(5), at(5)),
])
def test_authority_events_are_validated(make):
    with pytest.raises(ValueError):
        make()


def test_demo_mode_reductions_under_a_latch_also_need_a_closeout():
    s = c.reduce(c.initial_state(FIX), c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)))
    forced = c.ArmAccepted(c.Mode.DEMO, "owner", (), None, at(1), c.state_basis(s))  # DEMO is unauthorized live;
    s = c.reduce(s, forced)                                                            # this exercises the rule
    s = c.reduce(s, c.SetLatch(c.LatchScope.GLOBAL, "*", "kill", at(2)))
    assert any("REDUCTION_UNDER_LATCH_NEEDS_CLOSEOUT" in p for p in
               c.action_problems(s, c.ControlAction.REDUCE, now=now(3), **KW))
