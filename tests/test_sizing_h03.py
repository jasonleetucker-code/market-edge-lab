"""H03 decision-policy comparison (#184): ideal toy arithmetic vs the executable, costed comparison. SYNTHETIC."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from edge_lab import sizing_eval as se
from edge_lab import sizing_v2 as sv2
from edge_lab.fee_schedules import schedule_for
from edge_lab.opportunity import DepthLadder, DepthLevel, Market, MarketStatus, Payoff, PriceGrid, PriceRange
from edge_lab.research_diagnostics import EvidenceClass

GRID = PriceGrid((PriceRange(D("0"), D("1"), D("0.01")),), source="test cent grid")
AS_OF = "2026-10-01T12:00:00Z"
P = (D(".64"), D(".32"), D(".04"))
Q = (D(".80"), D(".10"), D(".10"))
TRUTH = (D(".10"), D(".10"), D(".80"))


def leg(event, state, ask, size=500, venue="kalshi", received="2026-10-01T11:59:00Z"):
    native = f"KXSYN-{event}-{state}" if venue == "kalshi" else f"{event}-{state}"
    m = Market(venue, f"{venue}:{native}", native, f"{venue}:{event}", state, Payoff("binary", D(1), state), "r" * 64,
               MarketStatus.OPEN, True, "synthetic", price_grid=GRID)
    lad = DepthLadder(venue, m.market_id, "YES", (DepthLevel(D(ask), D(size)),), False, received, None, "syn")
    return se.OutcomeLeg(state, m, lad, schedule_for(venue, "KXSYN" if venue == "kalshi" else None, as_of=AS_OF))


def toy_event(eid="E1", cluster="c1", outcome="C", venue="kalshi", received="2026-10-01T11:59:00Z", lockup=D(2)):
    return se.PolicyEvent(eid, cluster, "synthetic:toy", AS_OF, P,
                          tuple(leg(eid, s, str(q), venue=venue, received=received) for s, q in zip("ABC", Q)),
                          outcome, TRUTH, lockup)


def run(events, **kw):
    return se.compare_policies(events, evidence_class=EvidenceClass.SYNTHETIC, code_version="test", **kw)


def by(report, policy, event="E1"):
    return next(r for r in report.results if r.policy == policy and r.event_id == event)


# --------------------------------------------------------------------------- the owner's three toy numbers


def test_ideal_toy_reproduces_the_paper_arithmetic_exactly():
    ideal = se.ideal_comparison(P, Q, TRUTH)
    assert ideal.forecast_expected_brier_loss == D("1.2576") < ideal.market_expected_brier_loss == D("1.32")
    assert ideal.kelly_positions == (D("0.8"), D("3.2"), D("0.4"))
    assert ideal.kelly_expected_profit == D("-0.28")
    assert ideal.brier_positions == (D("-0.32"), D("0.44"), D("-0.12"))
    assert ideal.brier_expected_profit == D("0.14")
    # the ideal guarantee: E[Brier profit] = (L(q) - L(p)) + sum (p - q)^2 >= the Brier improvement > 0
    assert (ideal.loss_improvement, ideal.squared_distance) == (D("0.0624"), D("0.0776"))
    assert ideal.identity_holds and ideal.brier_expected_profit >= ideal.loss_improvement > 0
    assert "Not executable" in ideal.label and "shorting allowed" in ideal.assumptions


def test_identity_holds_for_other_vectors():
    p, q, t = (D(".2"), D(".5"), D(".3")), (D(".25"), D(".25"), D(".5")), (D(".3"), D(".3"), D(".4"))
    ideal = se.ideal_comparison(p, q, t)
    assert ideal.identity_holds
    assert ideal.brier_expected_profit == ideal.loss_improvement + ideal.squared_distance


# --------------------------------------------------------------------------- constraints and costs break it


def test_long_only_constraint_alone_breaks_the_strict_guarantee():
    long_only = tuple(max(D(0), s) for s in se.brier_positions(P, Q))
    assert se.expected_position_profit(long_only, Q, TRUTH) == D(0)  # not > 0, although L(p) < L(q)


def test_costed_executable_policies_lose_although_the_forecast_is_better():
    rep = run([toy_event()])
    brier, kelly, fixed, abstain = (by(rep, n) for n in ("CAUTIOUS_BRIER", "CAPPED_FRACTIONAL_KELLY", "FIXED_DOLLAR",
                                                          "ABSTAIN"))
    # cautious Brier: leg B costs 0.11 all-in for one contract (0.10 + fee, cent-aligned): floor(50 x 2 x 0.21) = 21
    assert brier.contracts == (0, 21, 0)
    assert (brier.gross_cost, brier.total_cost, brier.expected_net) == (D("2.10"), D("2.24"), D("-0.14"))
    # fixed dollar: $10 buys 94 of B; 0.10 x 94 - 10.00
    assert fixed.contracts == (0, 94, 0) and fixed.total_cost == D("10.00") and fixed.expected_net == D("-0.60")
    assert kelly.expected_net < 0 and kelly.total_cost <= D(25)
    assert abstain.contracts == (0, 0, 0) and abstain.expected_net == abstain.realized_net == D(0)
    # under the declared truth, abstaining beats every trading policy: the ideal guarantee did not carry over
    assert all(r.expected_net < abstain.expected_net for r in (brier, kelly, fixed))


# --------------------------------------------------------------------------- paired, capital-days, turnover


def test_paired_event_level_evaluation_with_capital_days_and_turnover():
    events = [toy_event("E1", "c1", "C"), toy_event("E2", "c1", "B"), toy_event("E3", "c2", "B")]
    rep = run(events)
    b = {e: by(rep, "CAUTIOUS_BRIER", e) for e in ("E1", "E2", "E3")}
    assert [b[e].realized_net for e in ("E1", "E2", "E3")] == [D("-2.24"), D("18.76"), D("18.76")]
    s = next(x for x in rep.summaries if x.policy == "CAUTIOUS_BRIER")
    assert (s.events, s.traded, s.abstained, s.realized_net) == (3, 3, 0, D("35.28"))
    assert s.capital_days == D("13.440000000000")  # 3 x 2.24 x 2 days
    assert s.turnover == D("0.063000000000")  # 3 x 2.10 notional / $100
    assert s.net_per_capital_day == (D("35.28") / D("13.44")).quantize(D("1e-12"))
    pair = next(p for p in rep.paired if (p.policy, p.baseline) == ("CAUTIOUS_BRIER", "ABSTAIN"))
    assert (pair.pairs, pair.clusters, pair.total_difference) == (3, 2, D("35.28"))  # clusters, not events
    assert pair.band is not None
    vs_fixed = next(p for p in rep.paired if (p.policy, p.baseline) == ("CAUTIOUS_BRIER", "FIXED_DOLLAR"))
    fixed = next(x for x in rep.summaries if x.policy == "FIXED_DOLLAR")
    assert vs_fixed.total_difference == s.realized_net - fixed.realized_net
    assert rep.stamp.evidence_class == "SYNTHETIC" and rep.stamp.edge_claim == "NONE"
    assert rep.status == "ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL" and rep.bankroll == D(100)


def test_every_policy_respects_the_event_budget_and_depth():
    rep = run([toy_event()], event_budget=D(5))
    for name in ("FIXED_DOLLAR", "CAPPED_FRACTIONAL_KELLY", "CAUTIOUS_BRIER"):
        assert by(rep, name).total_cost <= D(5)
    thin = se.PolicyEvent("T", "c", "synthetic:toy", AS_OF, P,
                          tuple(leg("T", s, str(q), size=3) for s, q in zip("ABC", Q)), "C", TRUTH, D(1))
    assert all(n <= 3 for n in by(run([thin]), "FIXED_DOLLAR", "T").contracts)


# --------------------------------------------------------------------------- unknowns propagate


def test_unknown_fee_gives_unknown_net_and_abstain_stays_a_known_zero():
    rep = run([toy_event(venue="novig"), toy_event("E2", "c2")])
    for name in ("FIXED_DOLLAR", "CAPPED_FRACTIONAL_KELLY", "CAUTIOUS_BRIER"):
        r = by(rep, name)
        assert r.state == "FEE_UNKNOWN" and r.total_cost is None and r.realized_net is None and r.expected_net is None
        s = next(x for x in rep.summaries if x.policy == name)
        assert s.realized_net is None and s.unknown == 1
        pair = next(p for p in rep.paired if (p.policy, p.baseline) == (name, "ABSTAIN"))
        assert pair.total_difference is None and pair.unknown_pairs == 1
    assert by(rep, "ABSTAIN").realized_net == D(0)


def test_unknown_outcome_and_stale_books():
    rep = run([toy_event(outcome=None), toy_event("E2", received="2026-10-01T11:00:00Z")])
    assert by(rep, "CAUTIOUS_BRIER").realized_net is None and by(rep, "CAUTIOUS_BRIER").expected_net == D("-0.14")
    stale = by(rep, "CAUTIOUS_BRIER", "E2")
    assert stale.state == "STALE_BOOK" and stale.total_cost is None


# --------------------------------------------------------------------------- determinism and labels


def test_identical_inputs_give_identical_outputs():
    a, b = run([toy_event(), toy_event("E2", "c2", "B")]), run([toy_event(), toy_event("E2", "c2", "B")])
    assert a == b and a.report_sha256 == b.report_sha256 and len(a.report_sha256) == 64
    c = run([toy_event(), toy_event("E2", "c2", "A")])
    assert c.stamp.input_sha256 != a.stamp.input_sha256 and c.report_sha256 != a.report_sha256


def test_policy_definitions_and_legacy_dicts():
    assert "brier_scale" not in sv2.POLICY_A.to_dict()  # earlier policy dicts and run ids are unchanged
    assert se.H03_CAUTIOUS_BRIER.to_dict()["brier_scale"] == "50"
    with pytest.raises(ValueError, match="brier_scale"):
        sv2.SizingPolicyV2("x", "1", "BRIER", "no scale")
    with pytest.raises(ValueError, match="ABSTAIN"):
        run([toy_event()], policies=se.H03_POLICIES[:3])


def test_protected_outcomes_are_refused_for_governed_runs():
    ev = toy_event()
    nfl = se.PolicyEvent("N", "c", "sports:nfl:moneyline", AS_OF, P, ev.legs, "C", None, None)
    with pytest.raises(ValueError, match="protected label scope"):
        se.compare_policies([nfl], evidence_class=EvidenceClass.RETROSPECTIVE_EXPLORATORY, code_version="t",
                            experiment_id="EXP-010", evidence_use_event_id="eu-" + "2" * 32)
    assert run([nfl]).stamp.label.startswith("SYNTHETIC")
