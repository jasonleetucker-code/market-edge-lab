"""Operating modes, kill latches and automation grants (execution/control.py)."""

from __future__ import annotations

from dataclasses import replace
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


def at(minutes: float = 0) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def intent(**kw) -> m.OrderIntent:
    base = dict(intent_key="synthetic:1", strategy_id="synthetic-demo", strategy_version="v1", scope=FIX,
                market_ticker="KXTEST-26OCT07-T50", kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal("5"), limit_price=Decimal("0.40"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("2.10"), expires_at_utc=at(30), price_grid=CENT, quantity_grid=WHOLE,
                profile_version="kalshi-ordinary-v0", risk_policy_version="r1", fee_schedule_version="f1",
                reduce_only=False)
    base.update(kw)
    return m.OrderIntent(**base)


def grant(**kw) -> c.AutomationGrant:
    base = dict(environment=m.Environment.FIXTURE, scope_key=FIX.key(), strategy_id="synthetic-demo",
                strategy_version="v1", model_hash=H1, policy_hash=H2, universe=frozenset({"KXTEST-*"}),
                allowed_kinds=frozenset({m.IntentKind.ENTRY, m.IntentKind.REDUCTION}),
                limits=c.GrantLimits(Decimal("5"), Decimal("10"), Decimal("20"), Decimal("50")),
                issued_at_utc=at(-60), expires_at_utc=at(600), issuer_ref="EXECUTION_PLAN:test")
    base.update(kw)
    return c.AutomationGrant(**base)


def armed(scope=FIX, mode=c.Mode.HUMAN_CONFIRMATION, grants=(), digest=None) -> c.ControlState:
    s = c.initial_state(scope)
    s = c.reduce(s, c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)))
    return c.reduce(s, c.ArmRequest(mode, "owner", (), at(1), digest), grants=grants, now=T0 + timedelta(minutes=1))


def test_startup_is_disarmed_and_nothing_sends():
    s = c.initial_state(FIX)
    assert s.mode is c.Mode.DISARMED
    assert any(p.startswith("MODE_DOES_NOT_SEND") for p in
               c.new_risk_problems(s, venue="kalshi", strategy_id="x", market_ticker="K", kind=m.IntentKind.ENTRY))


def test_arming_needs_a_complete_reconciliation():
    s = c.reduce(c.initial_state(FIX), c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", (), at(1)), now=T0)
    assert s.mode is c.Mode.DISARMED and any("RECONCILIATION_NOT_COMPLETE" in r for r in s.refusals)
    s = c.reduce(s, c.ReconciliationObserved(c.Reconciliation.PARTIAL, at(2)))
    s = c.reduce(s, c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", (), at(3)), now=T0)
    assert s.mode is c.Mode.DISARMED
    assert armed().mode is c.Mode.HUMAN_CONFIRMATION


def test_demo_and_production_cannot_arm_a_sending_mode():
    assert armed(DEMO, c.Mode.DEMO).mode is c.Mode.DISARMED  # DEMO is not authorized
    assert any("ENVIRONMENT_NOT_AUTHORIZED" in r for r in armed(DEMO, c.Mode.DEMO).refusals)
    assert armed(PROD, c.Mode.HUMAN_CONFIRMATION).mode is c.Mode.DISARMED
    assert any("DEMO_MODE_NEEDS_DEMO_SCOPE" in r for r in armed(FIX, c.Mode.DEMO).refusals)
    assert armed(PROD, c.Mode.SHADOW).mode is c.Mode.SHADOW  # shadow sends nothing


def test_an_incident_disarms_and_rearming_must_acknowledge_it():
    s = armed()
    s = c.reduce(s, c.IncidentRaised("inc-1", "reconciliation mismatch", at(5)))
    assert s.mode is c.Mode.DISARMED and s.open_incidents == ("inc-1",)
    s = c.reduce(s, c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", (), at(6)), now=T0)
    assert s.mode is c.Mode.DISARMED and any("INCIDENTS_NOT_ACKNOWLEDGED" in r for r in s.refusals)
    s = c.reduce(s, c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", ("inc-1",), at(7)), now=T0)
    assert s.mode is c.Mode.HUMAN_CONFIRMATION and s.open_incidents == ()


def test_a_reconciliation_loss_drops_a_sending_mode():
    s = c.reduce(armed(), c.ReconciliationObserved(c.Reconciliation.FAILED, at(5)))
    assert s.mode is c.Mode.DISARMED


def test_restart_replay_is_disarmed_and_keeps_latches_and_incidents():
    events = (c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(0)),
              c.ArmRequest(c.Mode.HUMAN_CONFIRMATION, "owner", (), at(1)),
              c.SetLatch(c.LatchScope.MARKET, "KXTEST-1", "manual stop", at(2)),
              c.IncidentRaised("inc-9", "lost ack", at(3)))
    s = c.replay(FIX, events)
    assert s.mode is c.Mode.DISARMED and s.reconciliation is c.Reconciliation.NOT_RUN
    assert (c.LatchScope.MARKET, "KXTEST-1") in s.latches and s.open_incidents == ("inc-9",)
    clean = c.replay(FIX, events[:2])
    assert clean.mode is c.Mode.DISARMED  # never restored armed


def test_latches_block_new_risk_but_not_reductions():
    s = c.reduce(armed(), c.SetLatch(c.LatchScope.STRATEGY, "synthetic-demo", "drawdown", at(2)))
    kw = dict(venue="kalshi", strategy_id="synthetic-demo", market_ticker="KXTEST-1")
    assert any("NEW_RISK_LATCHED" in p for p in c.new_risk_problems(s, kind=m.IntentKind.ENTRY, **kw))
    assert c.new_risk_problems(s, kind=m.IntentKind.REDUCTION, **kw) == []
    g = c.reduce(armed(), c.SetLatch(c.LatchScope.GLOBAL, "ignored", "kill", at(2)))
    assert (c.LatchScope.GLOBAL, "*") in g.latches
    assert c.new_risk_problems(c.reduce(g, c.ClearLatch(c.LatchScope.GLOBAL, "*", "owner", at(3))),
                               kind=m.IntentKind.ENTRY, **kw) == []


def test_bounded_auto_needs_a_valid_recorded_grant():
    g = grant()
    s = armed(mode=c.Mode.BOUNDED_AUTO, grants=(g,), digest=g.digest())
    assert s.mode is c.Mode.BOUNDED_AUTO and s.armed_grant_digest == g.digest()
    assert any("GRANT_MISSING" in r for r in armed(mode=c.Mode.BOUNDED_AUTO, grants=(), digest=g.digest()).refusals)
    expired = grant(expires_at_utc=at(0.5))
    assert any("GRANT_EXPIRED" in r for r in
               armed(mode=c.Mode.BOUNDED_AUTO, grants=(expired,), digest=expired.digest()).refusals)
    other = grant(scope_key=m.AccountScope(m.Environment.FIXTURE, "other").key())
    assert any("GRANT_SCOPE_MISMATCH" in r for r in
               armed(mode=c.Mode.BOUNDED_AUTO, grants=(other,), digest=other.digest()).refusals)
    assert any("GRANT_UNEXPECTED" in r for r in armed(mode=c.Mode.HUMAN_CONFIRMATION, digest=g.digest()).refusals)


def usage(e="0", t="0", d="0"):
    return c.GrantUsage(Decimal(e), Decimal(t), Decimal(d))


def test_grant_problems_bind_strategy_model_policy_universe_kinds_and_limits():
    g = grant()
    ok = intent()
    assert c.grant_problems(g, ok, usage=usage(), model_hash=H1, policy_hash=H2, now=T0) == []
    cases = {
        "GRANT_MODEL_CHANGED": dict(model_hash="c" * 64),
        "GRANT_POLICY_CHANGED": dict(policy_hash="c" * 64),
    }
    for code, kw in cases.items():
        args = dict(usage=usage(), model_hash=H1, policy_hash=H2, now=T0)
        args.update(kw)
        assert any(code in p for p in c.grant_problems(g, ok, **args)), code
    assert any("GRANT_STRATEGY_MISMATCH" in p for p in
               c.grant_problems(g, intent(strategy_version="v2"), usage=usage(), model_hash=H1, policy_hash=H2, now=T0))
    assert any("GRANT_UNIVERSE" in p for p in
               c.grant_problems(g, intent(market_ticker="KXOTHER-1"), usage=usage(), model_hash=H1, policy_hash=H2,
                                now=T0))
    only_red = grant(allowed_kinds=frozenset({m.IntentKind.REDUCTION}))
    assert any("GRANT_KIND" in p for p in c.grant_problems(only_red, ok, usage=usage(), model_hash=H1, policy_hash=H2,
                                                            now=T0))
    big = intent(quantity=Decimal("13"), max_total_cost=Decimal("5.21"))
    assert any("GRANT_ORDER_COST" in p for p in c.grant_problems(g, big, usage=usage(), model_hash=H1, policy_hash=H2,
                                                                  now=T0))
    for code, u in (("GRANT_EVENT_EXPOSURE", usage(e="8")), ("GRANT_TOTAL_EXPOSURE", usage(t="18")),
                    ("GRANT_TURNOVER", usage(d="48"))):
        assert any(code in p for p in c.grant_problems(g, ok, usage=u, model_hash=H1, policy_hash=H2, now=T0)), code
    exact = usage(e="7.90", t="17.90", d="47.90")  # exactly at each limit after this order: allowed
    assert c.grant_problems(g, ok, usage=exact, model_hash=H1, policy_hash=H2, now=T0) == []


def test_unknown_usage_blocks_the_grant():
    g = grant()
    unknown = c.GrantUsage(None, Decimal("0"), Decimal("0"))
    assert any("GRANT_USAGE_UNKNOWN" in p for p in
               c.grant_problems(g, intent(), usage=unknown, model_hash=H1, policy_hash=H2, now=T0))
    assert any("GRANT_USAGE_UNKNOWN" in p for p in
               c.grant_problems(g, intent(), usage=c.GrantUsage(Decimal(0), Decimal(0), None), model_hash=H1,
                                policy_hash=H2, now=T0))


def test_any_grant_change_changes_its_digest():
    g = grant()
    variants = [grant(universe=frozenset({"KXTEST-*", "KXMORE-*"})), grant(expires_at_utc=at(601)),
                grant(limits=c.GrantLimits(Decimal("5"), Decimal("10"), Decimal("20"), Decimal("51"))),
                grant(model_hash="c" * 64), grant(issuer_ref="EXECUTION_PLAN:other")]
    assert len({v.digest() for v in variants} | {g.digest()}) == len(variants) + 1


@pytest.mark.parametrize("kw", [dict(model_hash="short"), dict(universe=frozenset()), dict(universe=frozenset({"x y"})),
                                dict(allowed_kinds=frozenset()), dict(expires_at_utc=at(-60)),
                                dict(environment="FIXTURE")])
def test_grant_construction_is_strict(kw):
    with pytest.raises(ValueError):
        grant(**kw)


@pytest.mark.parametrize("bad", [0.5, True, "-1", float("nan")])
def test_limits_and_usage_are_exact(bad):
    with pytest.raises((ValueError, m.ExactValueError)):
        c.GrantLimits(bad, Decimal(1), Decimal(1), Decimal(1))
    with pytest.raises((ValueError, m.ExactValueError)):
        c.GrantUsage(bad, Decimal(1), Decimal(1))


def test_the_log_records_every_event_and_refusal():
    s = armed()
    s = c.reduce(s, c.Disarm("owner", "end of session", at(9)))
    assert s.mode is c.Mode.DISARMED and len(s.log) == 3 and "DISARM by owner" in s.log[-1]
    assert replace(s) == s  # frozen and comparable
