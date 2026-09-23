"""Gate 7 A — risk enforcement: risk.assess and exp001_shadow.run_day reviewed together.

Question under test: are loss, drawdown, capacity and exposure limits enforced *before* a
simulated fill, or only displayed afterwards? Fixture evidence only; nothing here is
evidence about profitability.

Behaviour pinned by these regression tests (written as strict xfails before the fixes) (coordinator fix 1/2):
- before a FILLED fill on the operational account `EXP-001-stage-b-shadow`,
  `risk.assess(point-in-time state, RISK_POLICY, as_of=decision time)` is checked; if
  `new_risk_allowed` is false or the candidate's worst-case cost exceeds
  `remaining_risk_capacity`, the fill is NO_FILL with reason "RISK_VETO" and a payload
  `risk_veto = {"binding": <name>, ...}`;
- a separate research account `EXP-001-stage-b-research` records the frozen EXP-001 rule
  (1 contract per signalled bracket, latency-confirmed-v1) without operational vetoes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab import exp001_shadow as shadow
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.risk import RiskPolicy, assess
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.sizing import SizingPolicy, suggest_position_size

from test_forward import D

from gate7.gate7_support import (
    CLOSED, D_CLUSTER, DECISION, OPS, RESEARCH, day_fills, seed, seed_realized_losses, settle_seed,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
ACC = "risk-acct"
LOOSE = RiskPolicy("gate7-loose", reserve_floor=Decimal("0"), max_position_risk=Decimal("1000"),
                   max_event_risk=Decimal("1000"), max_cluster_risk=Decimal("1000"),
                   max_portfolio_risk=Decimal("1000"), daily_loss_limit=Decimal("1000"),
                   weekly_loss_limit=Decimal("1000"), max_drawdown=Decimal("1000"))
# The three signals the fixture day produces, in ranked order, with their all-in costs.
B675_YES = ("kalshi:KXHIGHNY-26SEP23-B67.5", "YES")  # 0.15
B655_YES = ("kalshi:KXHIGHNY-26SEP23-B65.5", "YES")  # 0.15
T72_NO = ("kalshi:KXHIGHNY-26SEP23-T72", "NO")  # 0.88


def acct(tmp_path, bankroll="100.00") -> ShadowLedger:
    lg = ShadowLedger(tmp_path / "risk.sqlite3")
    lg.open_account(ACC, starting_bankroll=Decimal(bankroll), strategy="gate7", opened_at_utc=T0.isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id=FEES.schedule_id)
    return lg


def by_key(fill_rows):
    return {(f["market_id"], f["side"]): f for f in fill_rows}


# --------------------------------------------------------------------------- risk.assess boundaries


@pytest.mark.parametrize("limit, breach", [("2.01", False), ("2.00", False), ("1.99", True)])
def test_portfolio_limit_exact_boundary(tmp_path, limit, breach):
    lg = acct(tmp_path)
    for n in ("a", "b"):  # two $1.00 positions (price 0.99, fee and cent alignment included)
        seed(lg, ACC, n, price="0.99", filled_at=T0, event=f"e{n}", cluster=f"c{n}")
    r = assess(lg.state(ACC), replace(LOOSE, max_portfolio_risk=Decimal(limit)), T0)
    assert r.open_worst_case_risk == Decimal("2.00")
    assert ("MAX_PORTFOLIO_RISK" in r.breaches) is breach
    assert r.remaining_risk_capacity == (Decimal(0) if breach else Decimal(limit) - Decimal("2.00"))
    if breach:
        assert r.new_risk_allowed is False


@pytest.mark.parametrize("name, field", [("MAX_POSITION_RISK", "max_position_risk"),
                                         ("MAX_EVENT_RISK", "max_event_risk"),
                                         ("MAX_CLUSTER_RISK", "max_cluster_risk")])
@pytest.mark.parametrize("limit, breach", [("1.01", False), ("1.00", False), ("0.99", True)])
def test_position_event_cluster_limits_exact_boundary(tmp_path, name, field, limit, breach):
    lg = acct(tmp_path)
    seed(lg, ACC, "a", price="0.99", filled_at=T0, event="e", cluster="c")  # cost 1.00
    r = assess(lg.state(ACC), replace(LOOSE, **{field: Decimal(limit)}), T0)
    assert (name in r.breaches) is breach
    assert r.new_risk_allowed is (not breach)
    if breach:
        assert r.remaining_risk_capacity == 0


@pytest.mark.parametrize("floor, breach, capacity", [("98.99", False, "0.01"), ("99.00", False, "0"),
                                                    ("99.01", True, "0")])
def test_reserve_floor_exact_boundary(tmp_path, floor, breach, capacity):
    lg = acct(tmp_path)
    seed(lg, ACC, "a", price="0.99", filled_at=T0, event="e", cluster="c")  # settled cash 99.00
    r = assess(lg.state(ACC), replace(LOOSE, reserve_floor=Decimal(floor)), T0)
    assert r.settled_cash == Decimal("99.00")
    assert ("RESERVE_FLOOR" in r.breaches) is breach
    assert r.remaining_risk_capacity == Decimal(capacity)


@pytest.mark.parametrize("limit, breach", [("1.01", False), ("1.00", False), ("0.99", True)])
def test_daily_loss_exact_boundary(tmp_path, limit, breach):
    lg = acct(tmp_path)
    seed(lg, ACC, "a", price="0.99", filled_at=T0, event="e", cluster="c")
    settle_seed(lg, ACC, "a", "NO", settled_at=T0 + timedelta(hours=1))  # realized loss 1.00
    r = assess(lg.state(ACC), replace(LOOSE, daily_loss_limit=Decimal(limit)), T0 + timedelta(hours=2))
    assert r.daily_loss == Decimal("1.00")
    assert ("DAILY_LOSS_LIMIT" in r.breaches) is breach
    assert r.remaining_risk_capacity == (Decimal(0) if breach else Decimal(limit) - Decimal("1.00"))


def test_daily_loss_window_is_trailing_24h_exclusive_of_its_start(tmp_path):
    lg = acct(tmp_path)
    seed(lg, ACC, "a", price="0.99", filled_at=T0, event="e", cluster="c")
    settled = T0 + timedelta(hours=1)
    settle_seed(lg, ACC, "a", "NO", settled_at=settled)
    policy = replace(LOOSE, daily_loss_limit=Decimal("0.50"))
    at_edge = assess(lg.state(ACC), policy, settled + timedelta(days=1))  # exactly 24 h later: outside
    inside = assess(lg.state(ACC), policy, settled + timedelta(days=1) - timedelta(microseconds=1))
    assert at_edge.daily_loss == 0 and "DAILY_LOSS_LIMIT" not in at_edge.breaches
    assert inside.daily_loss == Decimal("1.00") and "DAILY_LOSS_LIMIT" in inside.breaches


@pytest.mark.parametrize("limit, breach", [("1.00", False), ("0.99", True)])
def test_drawdown_exact_boundary(tmp_path, limit, breach):
    lg = acct(tmp_path)
    seed(lg, ACC, "a", price="0.99", filled_at=T0, event="e", cluster="c")
    settle_seed(lg, ACC, "a", "NO", settled_at=T0 + timedelta(hours=1))
    r = assess(lg.state(ACC), replace(LOOSE, max_drawdown=Decimal(limit)), T0 + timedelta(days=30))
    assert r.drawdown == Decimal("1.00") and r.daily_loss == 0 and r.weekly_loss == 0
    assert ("MAX_DRAWDOWN" in r.breaches) is breach


def test_open_worst_case_counts_against_loss_headroom(tmp_path):
    """Correlated existing exposure: open positions are assumed lost when sizing new risk."""
    lg = acct(tmp_path)
    for n in range(3):
        seed(lg, ACC, str(n), price="0.99", filled_at=T0, event="e", cluster="same-underlying")
    r = assess(lg.state(ACC), replace(LOOSE, daily_loss_limit=Decimal("3.00")), T0)
    assert r.cluster_exposure == {"same-underlying": Decimal("3.00")}
    assert r.breaches == () and r.remaining_risk_capacity == 0


def test_zero_capacity_never_reports_new_risk_allowed(tmp_path):
    lg = acct(tmp_path)
    for n in ("a", "b"):
        seed(lg, ACC, n, price="0.99", filled_at=T0, event=f"e{n}", cluster=f"c{n}")
    r = assess(lg.state(ACC), replace(LOOSE, max_portfolio_risk=Decimal("2.00")), T0)
    assert r.breaches == () and r.remaining_risk_capacity == 0
    assert r.new_risk_allowed is False


# --------------------------------------------------------------------------- sizing caps


def _size(**kw):
    policy = SizingPolicy("gate7-fixed-1", fixed_contracts=1, kelly_fraction=None, max_position_contracts=1,
                          max_position_risk=Decimal("1.00"), max_event_risk=Decimal("6.00"),
                          max_cluster_risk=Decimal("6.00"), max_portfolio_risk=Decimal("50.00"),
                          reserve=Decimal("100.00"))
    args = dict(bankroll=Decimal("1000"), conservative_probability=Decimal("0.5"),
                executable_price=Decimal("0.14"), fees=FEES, available_size=Decimal("10"),
                event_exposure=Decimal(0), cluster_exposure=Decimal(0), total_open_risk=Decimal(0), policy=policy)
    args.update(kw)
    return suggest_position_size(**args)


@pytest.mark.parametrize("field, used, fits", [
    ("cluster_exposure", "5.85", True), ("cluster_exposure", "5.86", False),
    ("event_exposure", "5.85", True), ("event_exposure", "5.86", False),
    ("total_open_risk", "49.85", True), ("total_open_risk", "49.86", False),
])
def test_candidate_crossing_a_cap_is_sized_to_zero(field, used, fits):
    r = _size(**{field: Decimal(used)})  # candidate costs 0.15
    assert r.final_size == (1 if fits else 0)
    if not fits:
        assert r.binding_constraint == {"cluster_exposure": "MAX_CLUSTER_RISK", "event_exposure": "MAX_EVENT_RISK",
                                        "total_open_risk": "MAX_PORTFOLIO_RISK"}[field]


def test_existing_cap_overrun_never_goes_negative():
    r = _size(cluster_exposure=Decimal("9.00"), event_exposure=Decimal("9.00"))
    assert r.final_size == 0 and r.total_cost == 0


def test_reserve_cap_uses_settled_cash_after_open_risk():
    ok = _size(bankroll=Decimal("100.15"), total_open_risk=Decimal("0"))
    short = _size(bankroll=Decimal("100.14"))
    assert ok.final_size == 1 and short.final_size == 0 and short.binding_constraint == "RESERVE"


def test_operational_sizing_and_risk_limits_agree():
    """Sizing enforces per-event/cluster caps; risk only portfolio-level capacity. They must not drift."""
    s, r = shadow.SIZING_POLICY, shadow.RISK_POLICY
    assert (s.max_position_risk, s.max_event_risk, s.max_cluster_risk, s.max_portfolio_risk, s.reserve) == (
        r.max_position_risk, r.max_event_risk, r.max_cluster_risk, r.max_portfolio_risk, r.reserve_floor)


# --------------------------------------------------------------------------- run_day: what sizing already stops


def test_correlated_cluster_exposure_at_cap_blocks_every_fill_and_persists_binding(full_day, ledger, model):
    shadow.ensure_account(ledger)
    for n in range(6):  # 6 x $1.00 in D's outcome cluster, on another event id
        seed(ledger, OPS, f"c{n}", price="0.99", filled_at=DECISION - timedelta(hours=10),
             event="weather:other-contract-same-underlying", cluster=D_CLUSTER)
    summary = shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    assert summary["filled"] == 0 and summary["qualified"] == 3
    decisions = {d["decision_id"]: d for d in (
        json.loads(r["payload_json"]) for r in ledger.entries(OPS) if r["kind"] == "decision")}
    for f in day_fills(ledger):
        assert f["status"] == "NO_FILL" and f["reason"] == "ZERO_SIZE"
        assert decisions[f["decision_id"]]["sizing"]["binding_constraint"] == "MAX_CLUSTER_RISK"


def test_consecutive_candidates_share_cluster_headroom(full_day, ledger, model):
    shadow.ensure_account(ledger)
    used = sum(seed(ledger, OPS, f"c{n}", price=p, filled_at=DECISION - timedelta(hours=10),
                    event="weather:other-contract-same-underlying", cluster=D_CLUSTER)
               for n, p in enumerate(["0.99"] * 5 + ["0.68"]))
    assert used == Decimal("5.70")  # 0.30 headroom: exactly the two 0.15 signals, not the 0.88 one
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    got = by_key(day_fills(ledger))
    assert got[B675_YES]["status"] == got[B655_YES]["status"] == "FILLED"
    assert got[T72_NO]["status"] == "NO_FILL" and got[T72_NO]["reason"] == "ZERO_SIZE"
    assert ledger.state(OPS).cluster_exposure(D_CLUSTER) == Decimal("6.00")  # at the cap, never over


# --------------------------------------------------------------------------- run_day: pre-fill risk veto (planned)


def _run_with_losses(full_day, ledger, model, prices, total):
    lost = seed_realized_losses(ledger, prices, settled_at=DECISION - timedelta(hours=2))
    assert lost == Decimal(total)
    before = assess(ledger.state(OPS), shadow.RISK_POLICY, DECISION)
    summary = shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    return before, summary, by_key(day_fills(ledger))


def _assert_veto(fill, binding=None):
    assert fill["status"] == "NO_FILL" and fill["reason"] == "RISK_VETO"
    veto = fill["risk_veto"]
    assert isinstance(veto.get("binding"), str) and veto["binding"]
    if binding is not None:
        assert veto["binding"] == binding


def test_zero_capacity_without_breach_vetoes_every_fill(full_day, ledger, model):
    before, summary, got = _run_with_losses(full_day, ledger, model, ["0.99"] * 10, "10.00")
    assert before.breaches == () and before.remaining_risk_capacity == 0
    assert summary["filled"] == 0 and summary["no_fill"].get("RISK_VETO") == 3
    for key in (B675_YES, B655_YES, T72_NO):
        _assert_veto(got[key])
    assert ledger.state(OPS).open_positions() == []


def test_concurrent_candidates_stop_at_exact_capacity(full_day, ledger, model):
    # capacity 0.30: B67.5 (0.15) fits, B65.5 (0.15) fits exactly at the boundary, T72 NO (0.88) is vetoed.
    before, summary, got = _run_with_losses(full_day, ledger, model, ["0.99"] * 9 + ["0.68"], "9.70")
    assert before.remaining_risk_capacity == Decimal("0.30") and before.new_risk_allowed
    assert got[B675_YES]["status"] == got[B655_YES]["status"] == "FILLED"
    _assert_veto(got[T72_NO])
    after = assess(ledger.state(OPS), shadow.RISK_POLICY, CLOSED)  # fills are stamped at confirmation (~22:05Z)
    assert after.remaining_risk_capacity == 0 and after.open_worst_case_risk == Decimal("0.30")


def test_one_cent_over_capacity_is_vetoed(full_day, ledger, model):
    # capacity 0.29: one 0.15 bracket fits; then 0.14 < 0.15 so the other and T72 NO are vetoed.
    before, summary, got = _run_with_losses(full_day, ledger, model, ["0.99"] * 9 + ["0.69"], "9.71")
    assert before.remaining_risk_capacity == Decimal("0.29")
    # Fills are applied in confirmation-time order, so whichever 0.15 bracket confirmed first
    # takes the capacity; the other (0.14 left < 0.15) and T72 NO are vetoed.
    small = [got[B675_YES], got[B655_YES]]
    assert sorted(f["status"] for f in small) == ["FILLED", "NO_FILL"]
    _assert_veto(next(f for f in small if f["status"] == "NO_FILL"))
    _assert_veto(got[T72_NO])


def test_daily_loss_breach_vetoes_and_names_the_breach(full_day, ledger, model):
    before, summary, got = _run_with_losses(full_day, ledger, model, ["0.99"] * 9 + ["0.68", "0.29"], "10.01")
    assert before.breaches == ("DAILY_LOSS_LIMIT",) and before.new_risk_allowed is False
    assert summary["filled"] == 0
    for key in (B675_YES, B655_YES, T72_NO):
        _assert_veto(got[key], binding="DAILY_LOSS_LIMIT")


def test_open_exposure_exhausting_headroom_vetoes(full_day, ledger, model):
    shadow.ensure_account(ledger)
    for n in range(10):  # $10.00 open across two other clusters: daily headroom 10 - 0 - 10 = 0
        seed(ledger, OPS, f"o{n}", price="0.99", filled_at=DECISION - timedelta(hours=10),
             event=f"weather:other-{n}", cluster=f"weather:other-cluster-{n % 2}",
             expected_settlement=DECISION + timedelta(days=1))
    before = assess(ledger.state(OPS), shadow.RISK_POLICY, DECISION)
    assert before.breaches == () and before.remaining_risk_capacity == 0
    shadow.run_day(full_day, ledger, D, model=model, now=CLOSED)
    for f in day_fills(ledger):
        _assert_veto(f)


def test_research_account_keeps_the_frozen_rule_when_operations_veto(full_day, ledger, model):
    before, summary, got = _run_with_losses(full_day, ledger, model, ["0.99"] * 10, "10.00")
    research = ledger.state(RESEARCH)
    assert research.decisions == 12 and research.fills == 3
    for f in day_fills(ledger, RESEARCH):
        assert f["status"] == "FILLED" and f["quantity"] == 1
        assert f["fill_policy_id"] == "latency-confirmed-v1" and "risk_veto" not in f
    # the research account's own journal is independent of the operational vetoes
    assert all(f["reason"] == "RISK_VETO" for f in day_fills(ledger, OPS))
