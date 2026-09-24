"""Stake sizing v2 research challenger engine (ADR 0026). Deterministic; no network."""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import sizing_v2 as sv2
from edge_lab.fee_schedules import (
    KALSHI_QUADRATIC_TAKER_V1, CostModel, FeeScheduleStatus, QuadraticTakerSchedule,
)
from edge_lab.opportunity import DepthLadder, DepthLevel, Market, MarketStatus, Payoff
from edge_lab.risk import RiskPolicy, assess
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.sizing_v2 import (
    BoxSimplexSet, CoreCandidate, CoreProblem, ExactCostCurve, IntegerLadderCostCurve, PortfolioState,
    PositionCandidate, SizingRequest, Verdict,
)
from edge_lab.starter_policy import StarterVerdict

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
T = datetime(2026, 9, 24, 21, 0, tzinfo=UTC)  # after the KXHIGHNY fee verification record
AS_OF = T.isoformat()
STATES = ("B1", "B2", "B3", "B4")
ZERO_FEE = QuadraticTakerSchedule("test-zero-fee", "kalshi", Decimal(0), Decimal(1), FeeScheduleStatus.VERIFIED,
                                  "test double", "2026-09-24T00:00:00Z", CostModel.EXACT)
BIG = Decimal("1000000")


def market(native="KXHIGHNY-26SEP25-B1", *, venue="kalshi", kind="binary", amount=Decimal(1)):
    return Market(venue=venue, market_id=f"{venue}:{native}", native_id=native, event_id="ev", outcome=native,
                  payoff=Payoff(kind, amount, "test"), rules_sha256=None, status=MarketStatus.OPEN,
                  rules_resolved=True, rules_detail="test")


def ladder(m, side, levels, *, received=AS_OF, truncated=False):
    return DepthLadder(m.venue, m.market_id, side, tuple(DepthLevel(Decimal(p), Decimal(s)) for p, s in levels),
                       truncated, received, received, "test")


def portfolio(**over):
    base = dict(as_of_utc=AS_OF, risk_policy_id="test", bankroll=Decimal("10000"), tradable_cash=Decimal("10000"),
                reserve_floor=Decimal(0), open_worst_case_risk=Decimal(0), available_risk_budget=BIG,
                drawdown_headroom=BIG, event_exposure=(), cluster_exposure=(), breaches=(),
                max_position_risk=BIG, max_event_risk=BIG, max_cluster_risk=BIG, max_portfolio_risk=BIG)
    base.update(over)
    return PortfolioState(**base)


def starter(eligible=True):
    return StarterVerdict("STARTER_MAX_7D_V1", eligible, () if eligible else ("HORIZON_OVER_7D",), AS_OF, None, None,
                          None, None, None, None, None, 168, ())


def binary_request(p=0.55, lo=0.50, hi=0.60, *, side="YES", price="0.40", size=100000, pf=None, **over):
    m = market()
    cand = PositionCandidate(m, side, ("YES",), ladder(m, side, [(price, size)]), "ev", "cl")
    req = SizingRequest(AS_OF, ("YES", "NO"), cand, (p, 1 - p), sv2.binary_interval(p, lo, hi), "test-model v1",
                        AS_OF, pf or portfolio(), starter())
    return replace(req, **over)


def rec(req, policy=sv2.POLICY_C, **kw):
    kw.setdefault("fee_schedule", ZERO_FEE)
    return sv2.recommend(req, policy, **kw)


# --------------------------------------------------------------------------- Kelly and the optimizer


def test_kelly_closed_form_matches_the_integer_scan():
    # Binary paying 1 at all-in cost c: f* = (p - c) / (1 - c) of wealth. Here 0.25 of $10,000 = 6,250 contracts.
    r = rec(binary_request(0.55, 0.55, 0.55))
    f_star = (0.55 - 0.40) / (1 - 0.40)
    assert abs(r.recommended_contracts - f_star * 10000 / 0.40) <= 1
    assert r.verdict == "SIZE" and r.binding_constraint == "SIZING_RULE"
    assert r.unconstrained_kelly_amount == r.recommended_amount


def test_kelly_scan_small_case_is_the_exact_argmax():
    curve = IntegerLadderCostCurve([(5000, 1000)], coefficient=Decimal(0))
    problem = CoreProblem(100.0, (100.0, 100.0), (0.6, 0.4), sv2.binary_interval(0.6, 0.6, 0.6), (
        CoreCandidate("m", (1, 0), curve, 200),))
    brute = max(range(201), key=lambda n: (sv2.log_growth(problem, (n,), robust=False), -n))
    n = sv2.solve(sv2.POLICY_C, problem).counts[0]
    assert n == brute and abs(n - (0.6 - 0.5) / 0.5 * 100 / 0.5) <= 1


def test_bisection_matches_a_full_scan_with_fees():
    rng = random.Random(7)
    for _ in range(25):
        levels = [(p * 100, rng.randint(50, 400)) for p in range(rng.randint(20, 60), 99, 3)][:6]
        curve = IntegerLadderCostCurve(levels)
        p = min(0.95, levels[0][0] / 10000 + rng.uniform(0.02, 0.25))
        w = rng.uniform(200, 5000)
        problem = CoreProblem(w, (w, w), (p, 1 - p), sv2.binary_interval(p, p, p),
                              (CoreCandidate("m", (1, 0), curve, curve.max_contracts),))
        hi = sv2.affordable(curve, w, curve.max_contracts)
        f = lambda n: sv2.log_growth(problem, (n,), robust=False)  # noqa: E731
        g = lambda n: sv2.log_growth(problem, (n,), robust=False, smooth=True)  # noqa: E731
        got = sv2.solve(sv2.POLICY_C, problem).counts[0]
        # The search is exact for the pre-rounding (concave) problem ...
        smooth_best = max(range(hi + 1), key=lambda n: (g(n), -n))
        assert abs(got - smooth_best) <= sv2.REFINE_WINDOW
        # ... and within cent rounding of the exact one: at most $0.01 per take per state.
        slack = 0.01 * len(levels) / (w - curve.cost(hi))
        assert f(got) >= max(f(n) for n in range(hi + 1)) - slack


def test_integer_cost_curve_equals_the_decimal_schedule_and_depth_walk():
    rng = random.Random(11)
    m = market()
    for _ in range(20):
        start = rng.randint(1, 90)
        levels = [(f"0.{c:02d}", rng.randint(1, 30)) for c in range(start, min(99, start + 4) + 1)]
        exact = ExactCostCurve(ladder(m, "YES", levels), KALSHI_QUADRATIC_TAKER_V1)
        fast = IntegerLadderCostCurve([(int(Decimal(p) * 10000), s) for p, s in levels])
        assert exact.max_contracts == fast.max_contracts
        for n in range(1, exact.max_contracts + 1):
            assert exact.total(n) == Decimal(fast.cost_cents(n)) / 100


def test_marginal_cost_rises_through_the_book():
    m = market()
    curve = ExactCostCurve(ladder(m, "YES", [("0.40", 5), ("0.45", 5), ("0.55", 5)]), KALSHI_QUADRATIC_TAKER_V1)
    marginal = [curve.total(n + 1) - curve.total(n) for n in range(curve.max_contracts)]
    assert marginal[0] < marginal[7] < marginal[12]
    assert curve.depth_cost(16) is None and curve.max_affordable(Decimal("1000")) == 15


# --------------------------------------------------------------------------- uncertainty


def test_robust_objective_never_exceeds_nominal():
    rng = random.Random(3)
    for _ in range(50):
        p = [rng.random() + 0.05 for _ in STATES]
        p = [x / sum(p) for x in p]
        uset = sv2.dirichlet_box(STATES, p, rng.choice([10, 50, 200]))
        curve = IntegerLadderCostCurve([(3000, 500)])
        payout = tuple(rng.choice((0, 1)) for _ in STATES[:-1]) + (0,)
        if not any(payout):
            payout = (1, 0, 0, 0)
        problem = CoreProblem(1000.0, (1000.0,) * 4, tuple(p), uset, (CoreCandidate("m", payout, curve, 500),))
        for n in (0, 1, 10, 100, 400):
            assert sv2.log_growth(problem, (n,), robust=True) <= sv2.log_growth(problem, (n,), robust=False) + 1e-15


def test_adverse_point_is_derived_from_the_payoff_low_for_yes_high_for_no():
    # Same engine, same uncertainty set; only the side differs. Nothing in the code names a side.
    yes = rec(binary_request(0.60, 0.50, 0.70, side="YES", price="0.30"), sv2.POLICY_F)
    no = rec(binary_request(0.30, 0.20, 0.40, side="NO", price="0.30"), sv2.POLICY_F)
    assert yes.verdict == "SIZE" and no.verdict == "SIZE"
    assert yes.conservative_probability == Decimal("0.500000")  # P(YES) at its low end
    assert no.conservative_probability == Decimal("0.600000")  # P(NO) = 1 - P(YES) at its HIGH end 0.40
    assert yes.probability_uncertainty.payout_probability_min == Decimal("0.500000")
    assert no.probability_uncertainty.payout_probability_max == Decimal("0.800000")


def test_multi_state_minimum_over_extreme_points_equals_a_dense_interior_grid():
    uset = BoxSimplexSet(("a", "b", "c"), (0.3, 0.3, 0.4), (0.2, 0.1, 0.3), (0.4, 0.5, 0.6), "test")
    grid = [(i / 100, j / 100, 1 - i / 100 - j / 100) for i in range(20, 41) for j in range(10, 51)
            if 0.3 - 1e-12 <= 1 - i / 100 - j / 100 <= 0.6 + 1e-12]
    rng = random.Random(5)
    for _ in range(40):
        g = [rng.uniform(-1, 1) for _ in range(3)]
        greedy, v = uset.worst(g)
        at_vertices = min(sum(a * b for a, b in zip(x, g)) for x in uset.vertices())
        dense = min(sum(a * b for a, b in zip(x, g)) for x in grid)
        assert greedy == pytest.approx(at_vertices, abs=1e-12) == pytest.approx(dense, abs=1e-12)
        assert any(all(abs(a - b) < 1e-9 for a, b in zip(v, x)) for x in uset.vertices())


def test_multi_state_position_adverse_vector_moves_mass_to_its_losing_states():
    uset = sv2.dirichlet_box(STATES, (0.1, 0.4, 0.3, 0.2), 50)
    curve = IntegerLadderCostCurve([(5500, 1000)])
    payout = (0, 1, 1, 0)  # pays in B2 or B3
    problem = CoreProblem(1000.0, (1000.0,) * 4, uset.nominal, uset, (CoreCandidate("m", payout, curve, 1000),))
    adverse = sv2.adverse_vector(problem, (50,))
    assert adverse[1] + adverse[2] == pytest.approx(min(v[1] + v[2] for v in uset.vertices()))


def test_beta_functions():
    assert sv2.beta_cdf(0.4, 2, 3) == pytest.approx(6 * 0.16 - 8 * 0.064 + 3 * 0.0256, abs=1e-12)
    assert sv2.beta_ppf(0.5, 2, 2) == pytest.approx(0.5, abs=1e-12)
    for a, b, q in ((0.5, 0.5, 0.05), (60.5, 40.5, 0.0125), (3, 200, 0.99)):
        assert sv2.beta_cdf(sv2.beta_ppf(q, a, b), a, b) == pytest.approx(q, abs=1e-10)


def test_uncertainty_sets_contain_the_nominal_and_widen_with_less_evidence():
    narrow, wide = sv2.dirichlet_box(STATES, (0.1, 0.4, 0.3, 0.2), 300), sv2.dirichlet_box(STATES, (0.1, 0.4, 0.3, 0.2), 30)
    for u in (narrow, wide):
        assert all(lo <= p <= hi for lo, p, hi in zip(u.lower, u.nominal, u.upper))
    assert all(w_hi - w_lo > n_hi - n_lo for w_lo, w_hi, n_lo, n_hi in zip(wide.lower, wide.upper, narrow.lower,
                                                                            narrow.upper))
    wb = sv2.wilson_box(STATES, (0.1, 0.4, 0.3, 0.2), 100)
    assert wb.method.startswith("wilson") and all(lo <= p <= hi for lo, p, hi in zip(wb.lower, wb.nominal, wb.upper))


def test_uncertainty_too_high_when_the_robust_objective_sizes_zero():
    r = rec(binary_request(0.45, 0.30, 0.60, price="0.40"), sv2.POLICY_F)
    assert r.verdict == "UNCERTAINTY_TOO_HIGH" and r.recommended_contracts == 0
    assert rec(binary_request(0.45, 0.30, 0.60, price="0.40"), sv2.POLICY_C).verdict == "SIZE"
    missing = rec(binary_request(uncertainty=None))
    assert missing.verdict == "UNCERTAINTY_TOO_HIGH"


# --------------------------------------------------------------------------- policies


def test_fractions_and_flat_rules_scale_as_declared():
    full = rec(binary_request(0.55, 0.55, 0.55)).recommended_contracts
    half = rec(binary_request(0.55, 0.55, 0.55), sv2.POLICY_D).recommended_contracts
    quarter = rec(binary_request(0.55, 0.55, 0.55), sv2.POLICY_E).recommended_contracts
    assert half == math.floor(full / 2) and quarter == math.floor(full / 4)
    flat = rec(binary_request(0.55, 0.55, 0.55), sv2.POLICY_A)
    assert flat.recommended_contracts == 25 and flat.recommended_amount == Decimal("10.00")
    pct = rec(binary_request(0.55, 0.55, 0.55), sv2.POLICY_B)
    assert pct.recommended_amount == Decimal("200.00")
    thin = rec(binary_request(0.43, 0.43, 0.43), sv2.POLICY_A)  # edge 0.03 < the 0.05 entry threshold
    assert thin.verdict == "ZERO_EDGE" and thin.recommended_contracts == 0


def test_risk_constrained_kelly_satisfies_its_drawdown_constraint_and_bets_less():
    req = binary_request(0.60, 0.60, 0.60, price="0.40")
    g, c = rec(req, sv2.POLICY_G), rec(req, sv2.POLICY_C)
    assert 0 < g.recommended_contracts < c.recommended_contracts
    assert g.binding_constraint == "RISK_CONSTRAINT"
    curve = IntegerLadderCostCurve([(4000, 100000)], coefficient=Decimal(0))
    problem = CoreProblem(10000.0, (10000.0, 10000.0), (0.6, 0.4), sv2.binary_interval(0.6, 0.6, 0.6),
                          (CoreCandidate("m", (1, 0), curve, 25000),))
    lam = sv2.POLICY_G.drawdown_lambda
    assert lam == pytest.approx(math.log(0.1) / math.log(0.7))
    n = g.recommended_contracts
    assert sv2.drawdown_measure(problem, (n,), lam, robust=False) <= 1
    assert sv2.drawdown_measure(problem, (n + 1,), lam, robust=False) > 1


def test_joint_cluster_search_matches_exhaustive_and_respects_the_budget():
    p = (0.15, 0.45, 0.30, 0.10)
    uset = sv2.dirichlet_box(STATES, p, 2000)
    cands = (CoreCandidate("b2", (0, 1, 0, 0), IntegerLadderCostCurve([(3500, 60)]), 60),
             CoreCandidate("b3", (0, 0, 1, 0), IntegerLadderCostCurve([(2200, 60)]), 60))
    problem = CoreProblem(200.0, (200.0,) * 4, p, uset, cands, 40.0)
    got = sv2._maximize(problem, robust=True)  # 61 x 61 grid: exhaustive
    # the coordinate-ascent path agrees with the exhaustive search on this grid
    old = sv2.EXHAUSTIVE_LIMIT
    try:
        sv2.EXHAUSTIVE_LIMIT = 0
        ascent = sv2._maximize(problem, robust=True)
    finally:
        sv2.EXHAUSTIVE_LIMIT = old
    assert sv2.log_growth(problem, ascent, robust=True) == pytest.approx(sv2.log_growth(problem, got, robust=True),
                                                                         abs=1e-9)
    assert sum(c.curve.cost(n) for c, n in zip(cands, got)) <= 40.0 + 1e-9
    assert any(got)


def test_joint_policy_in_the_engine_shares_the_cluster_cap():
    p = (0.15, 0.45, 0.30, 0.10)
    reqs = []
    for i, (state, price) in enumerate((("B2", "0.35"), ("B3", "0.22"))):
        m = market(f"KXHIGHNY-26SEP25-{state}")
        cand = PositionCandidate(m, "YES", (state,), ladder(m, "YES", [(price, 1000)]), "ev", "cl")
        reqs.append(SizingRequest(AS_OF, STATES, cand, p, sv2.dirichlet_box(STATES, p, 200), "m v1", AS_OF,
                                  portfolio(max_cluster_risk=Decimal("50")), starter()))
    out = sv2.recommend_cluster(reqs, sv2.POLICY_H, fee_schedule=ZERO_FEE)
    assert sum(r.recommended_amount for r in out) <= Decimal("50")
    assert out[0].verdict == "SIZE" and out[0].binding_constraint == "CLUSTER_CAP"
    # the shared budget went to the better candidate; the other one says why it got nothing
    assert out[1].recommended_contracts == 0 and (out[1].verdict, out[1].binding_constraint) == (
        "RISK_LIMIT", "CLUSTER_CAP")
    sequential = sv2.recommend_cluster(reqs, sv2.POLICY_C, fee_schedule=ZERO_FEE)
    assert sum(r.recommended_amount for r in sequential) <= Decimal("50")


# --------------------------------------------------------------------------- hard caps


@pytest.mark.parametrize("field,value,binding", [
    ("max_position_risk", Decimal("40"), "POSITION_CAP"),
    ("max_event_risk", Decimal("40"), "EVENT_CAP"),
    ("max_cluster_risk", Decimal("40"), "CLUSTER_CAP"),
    ("max_portfolio_risk", Decimal("40"), "PORTFOLIO_CAP"),
    ("reserve_floor", Decimal("9960"), "RESERVE_FLOOR"),
    ("drawdown_headroom", Decimal("40"), "DRAWDOWN_CAP"),
    ("available_risk_budget", Decimal("40"), "RISK_BUDGET"),
])
def test_each_cap_binds_when_it_should(field, value, binding):
    r = rec(binary_request(pf=portfolio(**{field: value})))
    assert r.verdict == "SIZE" and r.binding_constraint == binding
    assert r.recommended_contracts == 100 and r.recommended_amount == Decimal("40.00")
    assert r.maximum_allowed_amount == Decimal("40.00") and r.fractional_kelly_amount > r.recommended_amount


def test_existing_exposure_reduces_event_and_cluster_caps_and_ties_are_secondary():
    pf = portfolio(event_exposure=(("ev", Decimal("60")),), cluster_exposure=(("cl", Decimal("60")),),
                   max_event_risk=Decimal("100"), max_cluster_risk=Decimal("100"), open_worst_case_risk=Decimal("60"))
    r = rec(binary_request(pf=pf))
    assert r.binding_constraint == "EVENT_CAP" and r.recommended_amount == Decimal("40.00")
    assert "CLUSTER_CAP" in r.secondary_constraints and r.event_cap == r.cluster_cap == Decimal("40.00")


def test_liquidity_binds_and_zero_depth_is_liquidity_limit():
    r = rec(binary_request(size=30))
    assert r.binding_constraint == "LIQUIDITY" and r.recommended_contracts == 30 and r.verdict == "SIZE"
    m = market()
    bad = binary_request()
    bad = replace(bad, candidate=replace(bad.candidate, ladder=ladder(m, "YES", [("0.40", "0.5")])))
    assert rec(bad).verdict == "LIQUIDITY_LIMIT"


def test_cap_that_allows_nothing_is_risk_limit():
    r = rec(binary_request(pf=portfolio(max_position_risk=Decimal("0.30"))))
    assert r.verdict == "RISK_LIMIT" and r.binding_constraint == "POSITION_CAP" and r.recommended_contracts == 0


def test_unknown_correlation_clusters_share_the_cluster_cap():
    pf = portfolio(cluster_exposure=(("other", Decimal("70")),), open_worst_case_risk=Decimal("70"),
                   max_cluster_risk=Decimal("100"))
    alone = rec(binary_request(pf=pf))
    shared = rec(binary_request(pf=pf, correlated_clusters=("other",)))
    assert alone.binding_constraint == shared.binding_constraint == "CLUSTER_CAP"
    assert alone.recommended_amount == Decimal("100.00") and shared.recommended_amount == Decimal("30.00")


def test_unmapped_cluster_exposure_is_assumed_lost():
    pf = portfolio(cluster_exposure=(("cl", Decimal("5000")),), open_worst_case_risk=Decimal("5000"))
    r = rec(binary_request(pf=pf))
    clean = rec(binary_request())
    assert 0 < r.recommended_contracts < clean.recommended_contracts


def test_risk_breach_and_zero_capacity_block():
    assert rec(binary_request(pf=portfolio(breaches=("MAX_DRAWDOWN",)))).verdict == "RISK_LIMIT"
    assert rec(binary_request(pf=portfolio(available_risk_budget=Decimal(0)))).verdict == "RISK_LIMIT"


def test_capital_horizon_blocks_ineligible_and_unknown():
    r = rec(binary_request(starter=starter(False)))
    assert r.verdict == "CAPITAL_HORIZON" and r.cash_horizon_cap == Decimal("0.00")
    assert rec(binary_request(starter=None)).verdict == "CAPITAL_HORIZON"


def test_portfolio_state_reuses_risk_assess(tmp_path):
    lg = ShadowLedger(tmp_path / "l.sqlite3")
    lg.open_account("a", starting_bankroll=Decimal("100.00"), strategy="t", opened_at_utc=(T - timedelta(hours=1)).isoformat(),
                    sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")
    policy = RiskPolicy("rp", reserve_floor=Decimal("20"), max_position_risk=Decimal("5"), max_event_risk=Decimal("10"),
                        max_cluster_risk=Decimal("10"), max_portfolio_risk=Decimal("30"), daily_loss_limit=Decimal("5"),
                        weekly_loss_limit=Decimal("10"), max_drawdown=Decimal("15"))
    report = assess(lg.state("a"), policy, T)
    pf = sv2.portfolio_state(report, policy)
    assert pf.available_risk_budget == report.remaining_risk_capacity == Decimal("5")
    assert pf.drawdown_headroom == Decimal("5") and pf.bankroll == Decimal("100.00")
    r = rec(binary_request(pf=pf))
    assert r.verdict == "SIZE" and r.recommended_amount <= Decimal("5.00")
    assert r.binding_constraint == "POSITION_CAP" and "DRAWDOWN_CAP" in r.secondary_constraints


# --------------------------------------------------------------------------- fail closed


def test_unsupported_payoff_fee_and_side():
    assert rec(binary_request(candidate=replace(binary_request().candidate, market=market(kind="scalar")))
               ).verdict == "UNSUPPORTED"
    assert rec(binary_request(candidate=replace(binary_request().candidate, market=market(amount=Decimal(2))))
               ).verdict == "UNSUPPORTED"
    poly = market("some-slug", venue="polymarket_us")
    req = binary_request(candidate=PositionCandidate(poly, "YES", ("YES",), ladder(poly, "YES", [("0.40", 10)]), "ev", "cl"))
    r = sv2.recommend(req, sv2.POLICY_C)  # the real schedule_for: no verified fee schedule for this venue
    assert r.verdict == "UNSUPPORTED" and "FEE_UNSUPPORTED" in r.explanation
    nonstandard = market("KXNFLGAME-26SEP25-X")
    req = binary_request(candidate=PositionCandidate(nonstandard, "YES", ("YES",),
                                                     ladder(nonstandard, "YES", [("0.40", 10)]), "ev", "cl"))
    assert sv2.recommend(req, sv2.POLICY_C).verdict == "UNSUPPORTED"
    bad_side = binary_request(candidate=replace(binary_request().candidate, side="MAYBE"))
    assert rec(bad_side).verdict == "UNSUPPORTED"


def test_unverified_fee_claim_basis_is_unsupported_before_the_verification_record():
    early = "2026-09-23T10:00:00+00:00"  # before the KXHIGHNY record's knowledge time
    req = binary_request(as_of_utc=early, model_generated_at_utc=early, pf=portfolio(as_of_utc=early))
    req = replace(req, candidate=replace(req.candidate, ladder=replace(req.candidate.ladder, received_at_utc=early)))
    r = sv2.recommend(req, sv2.POLICY_C)
    assert r.verdict == "UNSUPPORTED" and "FEE_UNVERIFIED" in r.explanation


def test_conservative_bound_allowance_is_added_to_the_cost():
    r = sv2.recommend(binary_request(pf=portfolio(max_position_risk=Decimal("5.00"))), sv2.POLICY_C)
    assert r.verdict == "SIZE"
    n = r.recommended_contracts
    base = KALSHI_QUADRATIC_TAKER_V1.taker_buy(n, Decimal("0.40")).total_cost
    assert r.recommended_amount == (base + Decimal("0.0101") * n).quantize(Decimal("0.01"), rounding="ROUND_CEILING")
    assert r.recommended_amount <= Decimal("5.00")


@pytest.mark.parametrize("change", ["stale_book", "future_book", "missing_book", "stale_model", "missing_model",
                                    "missing_risk", "stale_risk"])
def test_stale_or_missing_inputs_are_stale_data(change):
    req = binary_request()
    old = (T - timedelta(hours=30)).isoformat()
    if change == "stale_book":
        req = replace(req, candidate=replace(req.candidate, ladder=replace(req.candidate.ladder,
                                                                             received_at_utc=(T - timedelta(minutes=6)).isoformat())))
    elif change == "future_book":
        req = replace(req, candidate=replace(req.candidate, ladder=replace(req.candidate.ladder,
                                                                             received_at_utc=(T + timedelta(seconds=1)).isoformat())))
    elif change == "missing_book":
        req = replace(req, candidate=replace(req.candidate, ladder=None))
    elif change == "stale_model":
        req = replace(req, model_generated_at_utc=old)
    elif change == "missing_model":
        req = replace(req, model_probabilities=None, uncertainty=None)
    elif change == "missing_risk":
        req = replace(req, portfolio=None)
    elif change == "stale_risk":
        req = replace(req, portfolio=portfolio(as_of_utc=old))
    r = rec(req)
    assert r.verdict == "STALE_DATA" and r.recommended_contracts == 0 and r.recommended_amount == Decimal(0)


@pytest.mark.parametrize("missing", ["candidate.ladder", "model_probabilities", "uncertainty", "model_generated_at_utc",
                                     "portfolio", "starter"])
def test_a_missing_input_never_yields_size(missing):
    req = binary_request()
    if missing == "candidate.ladder":
        req = replace(req, candidate=replace(req.candidate, ladder=None))
    elif missing == "model_probabilities":
        req = replace(req, model_probabilities=None, uncertainty=None)
    else:
        req = replace(req, **{missing: None})
    assert rec(req).verdict != "SIZE"


def test_no_edge_is_zero_edge():
    r = rec(binary_request(0.38, 0.38, 0.38))
    assert r.verdict == "ZERO_EDGE" and r.binding_constraint == "NO_EDGE" and r.expected_net_edge < 0


# --------------------------------------------------------------------------- record


def test_recommendation_has_exactly_the_contract_fields():
    expected = ("policy_id policy_version bankroll tradable_cash available_risk_budget market_id outcome_id venue_id "
                "model_probability conservative_probability probability_uncertainty entry_price estimated_fee "
                "estimated_slippage expected_net_edge unconstrained_kelly_amount fractional_kelly_amount liquidity_cap "
                "position_cap event_cap cluster_cap portfolio_cap cash_horizon_cap drawdown_cap recommended_amount "
                "recommended_contracts maximum_allowed_amount binding_constraint secondary_constraints verdict "
                "explanation input_timestamp model_version input_hash output_hash").split()
    assert [f for f in sv2.SizingRecommendation.__dataclass_fields__] == expected
    assert {v.value for v in Verdict} == {"SIZE", "ZERO_EDGE", "UNCERTAINTY_TOO_HIGH", "LIQUIDITY_LIMIT",
                                          "RISK_LIMIT", "STALE_DATA", "CAPITAL_HORIZON", "UNSUPPORTED"}


def test_money_is_cent_quantized_and_explanation_is_labelled():
    r = sv2.recommend(binary_request(pf=portfolio(max_position_risk=Decimal("7"))), sv2.POLICY_D)
    for name in ("recommended_amount", "unconstrained_kelly_amount", "position_cap", "estimated_fee", "bankroll"):
        assert getattr(r, name).as_tuple().exponent == -2, name
    assert r.explanation.startswith("RESEARCH SIZING") and "not an order" in r.explanation


def test_identical_inputs_give_identical_hashes_and_records():
    a, b = rec(binary_request()), rec(binary_request())
    assert a == b and a.input_hash == b.input_hash and a.output_hash == b.output_hash
    c = rec(binary_request(0.56, 0.50, 0.60))
    assert c.input_hash != a.input_hash and c.output_hash != a.output_hash
    assert a.to_dict()["recommended_amount"] == str(a.recommended_amount)


def test_policies_are_versioned_and_validated():
    assert len({p.policy_id for p in sv2.POLICIES}) == 8
    assert all(p.policy_version for p in sv2.POLICIES)
    with pytest.raises(ValueError):
        sv2.SizingPolicyV2("x", "1", "KELLY", "bad", kelly_fraction=Decimal("1.5"))
    with pytest.raises(ValueError):
        sv2.SizingPolicyV2("x", "1", "KELLY", "bad", drawdown_alpha=Decimal("0.7"))


# --------------------------------------------------------------------------- frozen paths untouched


FROZEN = {
    # LF-normalized SHA-256 at origin/main b62db44. sizing v2 must not modify them; a legitimate,
    # reviewed change elsewhere updates the pin in the same PR.
    "src/edge_lab/sizing.py": "cbeb04abcf65c83491edc8c5238f01c1164709ef3913b3a11230811538801ddd",
    "src/edge_lab/exp001_shadow.py": "ce74ea3f8a042eee5837639541bc553347c0e9e145aaf13b6ec7454fa7833880",
    "src/edge_lab/fees.py": "13925022e7bee7c4c27214d8fa44b99a53e6795e5d8054b79a8dd6b9a5789396",
}


@pytest.mark.parametrize("path,digest", sorted(FROZEN.items()))
def test_operational_and_frozen_modules_are_unchanged(path, digest):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest
    # The EXP-001 preregistration pins (dataset, design, fees, stats, settlement) are checked by
    # tests/invariants/test_exp001_frozen_artifacts.py.


def test_sizing_v2_does_not_import_the_frozen_shadow_accounts():
    for name in ("sizing_v2.py", "sizing_eval.py"):
        text = (ROOT / "src" / "edge_lab" / name).read_text(encoding="utf-8")
        assert "exp001_shadow" not in text and "from .sizing import" not in text
        assert "shadow_ledger" not in text and "ShadowLedger" not in text  # never writes a ledger


def test_combinatorial_vertex_enumeration_is_bounded():
    big = sv2.dirichlet_box(tuple(f"s{i}" for i in range(17)), [1 / 17] * 17, 50)
    with pytest.raises(ValueError):
        big.vertices()
    assert len(list(itertools.islice(sv2.dirichlet_box(STATES, (0.25,) * 4, 50).vertices(), 100))) > 4


@pytest.mark.parametrize("kind", ["binary_split_on_cancel", "binary_alternative_settlement", "scalar", "BINARY"])
def test_only_plain_binary_paying_one_is_supported(kind):
    # Lane B (PR #58) adds payoff kinds that are not a plain binary; sizing must refuse them.
    req = binary_request()
    r = rec(replace(req, candidate=replace(req.candidate, market=market(kind=kind))))
    assert r.verdict == "UNSUPPORTED" and "PAYOFF_UNSUPPORTED" in r.explanation and r.recommended_contracts == 0


# --------------------------------------------------------------------------- review fixes (PR #60)


def test_closed_market_or_unresolved_rules_is_unsupported_never_size():
    req = binary_request(0.55, 0.55, 0.55)
    closed = replace(req.candidate.market, status=MarketStatus.CLOSED, rules_resolved=False)
    r = rec(replace(req, candidate=replace(req.candidate, market=closed)))
    assert r.verdict == "UNSUPPORTED" and "MARKET_NOT_OPEN" in r.explanation and r.recommended_contracts == 0
    unresolved = replace(req.candidate.market, rules_resolved=False, rules_detail="threshold not in captured rules")
    r = rec(replace(req, candidate=replace(req.candidate, market=unresolved)))
    assert r.verdict == "UNSUPPORTED" and "RULES_UNRESOLVED" in r.explanation
    unknown = replace(req.candidate.market, status=MarketStatus.UNKNOWN)
    assert rec(replace(req, candidate=replace(req.candidate, market=unknown))).verdict == "UNSUPPORTED"


@pytest.mark.parametrize("version", [None, ""])
def test_missing_model_version_is_stale_data(version):
    r = rec(binary_request(model_version=version))
    assert r.verdict == "STALE_DATA" and "MODEL_VERSION_MISSING" in r.explanation and r.recommended_contracts == 0


def test_fraction_is_applied_before_a_shared_budget_joint_equals_sequential():
    # 1/2 Kelly under budget B must be min(1/2 Kelly, B) whether sized jointly or alone.
    curve = IntegerLadderCostCurve([(4000, 100000)], coefficient=Decimal(0))
    joint_half = sv2.SizingPolicyV2("t-joint-half", "1", "KELLY", "t", kelly_fraction=Decimal("0.5"), joint=True)
    for budget in (500.0, 1000.0, 2000.0, 5000.0):
        problem = CoreProblem(10000.0, (10000.0, 10000.0), (0.55, 0.45), sv2.binary_interval(0.55, 0.55, 0.55),
                              (CoreCandidate("m", (1, 0), curve, 25000),), budget)
        full = sv2.solve(sv2.POLICY_C, replace(problem, budget=None)).counts[0]  # 6,250
        got = sv2.solve(joint_half, problem).counts[0]
        assert abs(got - min(full // 2, sv2.affordable(curve, budget, 25000))) <= 1, (budget, got)


def test_joint_reports_the_true_unconstrained_kelly_and_a_sub_contract_position_cap():
    p = (0.15, 0.45, 0.30, 0.10)
    reqs = []
    for state, price in (("B2", "0.35"), ("B3", "0.22")):
        m = market(f"KXHIGHNY-26SEP25-{state}")
        cand = PositionCandidate(m, "YES", (state,), ladder(m, "YES", [(price, 100000)]), "ev", "cl")
        reqs.append(SizingRequest(AS_OF, STATES, cand, p, sv2.dirichlet_box(STATES, p, 5000), "m v1", AS_OF,
                                  portfolio(max_position_risk=Decimal("0.20")), starter()))
    out = sv2.recommend_cluster(reqs, sv2.POLICY_H, fee_schedule=ZERO_FEE)
    for r in out:
        assert r.verdict == "RISK_LIMIT" and r.binding_constraint == "POSITION_CAP" and r.recommended_contracts == 0
    assert out[0].unconstrained_kelly_amount > Decimal("100")  # not capped by the $0.20 position cap


def test_cash_that_buys_no_contract_is_risk_limit_not_zero_edge():
    r = rec(binary_request(pf=portfolio(tradable_cash=Decimal("0.30"))))
    assert r.verdict == "RISK_LIMIT" and r.binding_constraint == "TRADABLE_CASH"
    capped = rec(binary_request(pf=portfolio(tradable_cash=Decimal("100"))))
    assert capped.binding_constraint == "TRADABLE_CASH" and capped.recommended_amount == Decimal("100.00")


def test_cluster_requests_must_share_one_uncertainty_set():
    a = binary_request()
    b = replace(binary_request(), uncertainty=sv2.binary_interval(0.55, 0.40, 0.70))
    with pytest.raises(ValueError):
        sv2.recommend_cluster([a, b], sv2.POLICY_H, fee_schedule=ZERO_FEE)
    wrong = replace(binary_request(), uncertainty=sv2.dirichlet_box(STATES, (0.25,) * 4, 50))
    with pytest.raises(ValueError):
        rec(wrong)


def test_invalid_book_is_stale_data():
    m = market()
    req = binary_request()
    bad = ladder(m, "YES", [("0.45", 10), ("0.40", 10)])  # not ascending
    r = rec(replace(req, candidate=replace(req.candidate, ladder=bad)))
    assert r.verdict == "STALE_DATA" and "INVALID_BOOK" in r.explanation


def test_flat_unit_that_buys_no_contract_is_risk_limit():
    tiny = sv2.SizingPolicyV2("t-flat", "1", "FLAT_UNIT", "t", unit_amount=Decimal("0.30"), min_edge=Decimal("0.05"))
    r = rec(binary_request(0.55, 0.55, 0.55), tiny)
    assert r.verdict == "RISK_LIMIT" and r.binding_constraint == "FLAT_UNIT"
    below = rec(binary_request(0.43, 0.43, 0.43), sv2.POLICY_A)
    assert below.verdict == "ZERO_EDGE" and below.binding_constraint == "MIN_EDGE"


def test_polymarket_us_schedule_from_pr58_maps_to_its_claim_basis():
    # PR #58's Polymarket US schedule prices trades, but while its SETTLEMENT_AND_TRANSFER_FEES
    # component is unverified the point-in-time claim basis is NONE: research sizing refuses it.
    from edge_lab.fee_schedules import POLYMARKET_US_EXCHANGE_SCOPE, schedule_for, verification_at
    schedule = schedule_for("polymarket_us", POLYMARKET_US_EXCHANGE_SCOPE, as_of=AS_OF)
    poly = market("some-slug", venue="polymarket_us")
    req = binary_request(candidate=PositionCandidate(poly, "YES", ("YES",), ladder(poly, "YES", [("0.40", 10)]),
                                                     "ev", "cl"))
    r = sv2.recommend(req, sv2.POLICY_C, fee_schedule=schedule)
    if verification_at(schedule, AS_OF, "some-slug").claimable:
        assert r.verdict == "SIZE"  # completed evidence: the claim path applies
    else:
        assert r.verdict == "UNSUPPORTED" and "FEE_UNVERIFIED" in r.explanation
    # without an explicit schedule (the scope needs the market's own feeCoefficient) it is refused
    assert sv2.recommend(req, sv2.POLICY_C).verdict == "UNSUPPORTED"


def test_research_candidate_is_a_frozen_policy_in_the_engine():
    from edge_lab import sizing_eval
    c = sv2.POLICY_CANDIDATE
    assert sizing_eval.H_RCK is c and c.policy_id == "SV2-H-cluster-robust-rck" and c.policy_version == "1"
    assert c.joint and c.robust and c.robust_constraint and c.kelly_fraction == Decimal("0.5")
