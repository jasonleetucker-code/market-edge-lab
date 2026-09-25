"""Economic screen: episodes (not snapshots), capital-constrained replay, size ladder, honest verdicts."""

from decimal import Decimal as D

import pytest

from edge_lab.fee_schedules import get_fee_schedule
from edge_lab.opportunity import DepthLadder, DepthLevel
from edge_lab.research_economics import (
    ILLUSTRATIVE, Basis, CapitalScenario, EdgeKind, EpisodeDefinition, FillMode, Labeled, Observation, ScreenInputs,
    SizePoint, Verdict, build_episodes, capacity_ladder, cluster_bootstrap_mean, economic_screen, replay,
    size_ladder_from_depth,
)

W0, W1 = "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"  # 30-day window
DEF = EpisodeDefinition("ep-test-v1", start_threshold=D("0.02"), end_merge_gap_seconds=3600, minimum_size=D(1),
                        frozen=True)


def pt(q, net, cost="0.50", status="FILLABLE", gross=None):
    net = None if net is None else D(net)
    return SizePoint(D(q), status, None if status != "FILLABLE" else D(cost),
                     None if net is None else (D(gross) if gross else net + D("0.01")), net)


def obs(oid, t, *, keys=("kalshi:M1:YES",), cluster="day1", ladder=None, release="2026-09-03T00:00:00Z",
        venue="kalshi"):
    ladder = ladder if ladder is not None else (pt(1, "0.05"), pt(10, "0.04"), pt(100, "0.03"))
    return Observation(oid, tuple(keys), venue, t, cluster, EdgeKind.CONDITIONAL_BOUND, tuple(ladder), release)


def scen(capital="1000", reserve="0", label="S1", **venues):
    caps = {"kalshi": Labeled(D(capital), Basis.OWNER_INPUT)} if not venues else venues
    return CapitalScenario(label, caps, {v: Labeled(D(reserve), Basis.OWNER_INPUT) for v in caps})


# --------------------------------------------------------------------------- labels and ladder


def test_labeled_never_mixes_unknown_and_values():
    with pytest.raises(ValueError):
        Labeled(D(1), Basis.UNKNOWN)
    with pytest.raises(ValueError):
        Labeled(None, Basis.OBSERVED)
    with pytest.raises(ValueError):
        Labeled(1.5, Basis.OBSERVED)
    assert Labeled.unknown().value is None


def test_size_ladder_uses_the_canonical_depth_walk_and_fees_once():
    ladder = DepthLadder("kalshi", "kalshi:M1", "YES", (DepthLevel(D("0.40"), D(5)), DepthLevel(D("0.45"), D(10))),
                         False, "2026-09-02T00:00:00Z", None, "snap:1")
    fees = get_fee_schedule("kalshi-quadratic-taker-v1")
    points = size_ladder_from_depth(ladder, [D(1), D(10), D(20)], fees, value_per_unit=D("0.50"))
    one, ten, twenty = points
    assert one.fillable and one.all_in_cost_per_unit > D("0.40")  # fee included in the cost
    assert one.net_edge_per_unit == D("0.50") - one.all_in_cost_per_unit  # net = value - all-in (fees once)
    assert one.gross_edge_per_unit == D("0.50") - D("0.40")
    assert ten.net_edge_per_unit < one.net_edge_per_unit  # deeper levels cost more
    assert twenty.depth_status == "INSUFFICIENT_DEPTH" and twenty.net_edge_per_unit is None
    unknown = size_ladder_from_depth(ladder, [D(1)], fees, value_per_unit=None)
    assert unknown[0].all_in_cost_per_unit is not None and unknown[0].net_edge_per_unit is None  # no probability, no EV


# --------------------------------------------------------------------------- episodes


def test_repeated_observations_of_the_same_orders_are_one_episode():
    observations = [obs(f"o{i}", f"2026-09-02T00:{i * 5:02d}:00Z") for i in range(6)]
    result = build_episodes(observations, DEF)
    assert len(result.episodes) == 1 and result.qualifying_observations == 6
    assert result.episodes[0].observation_ids == tuple(f"o{i}" for i in range(6))


def test_gaps_and_non_qualifying_observations_end_an_episode():
    observations = [
        obs("a", "2026-09-02T00:00:00Z"),
        obs("b", "2026-09-02T00:30:00Z"),
        obs("c", "2026-09-02T00:40:00Z", ladder=(pt(1, "0.01"),)),  # below threshold: ends it
        obs("d", "2026-09-02T00:50:00Z"),
        obs("e", "2026-09-02T03:00:00Z"),  # > 1 h gap: new episode
    ]
    episodes = build_episodes(observations, DEF).episodes
    assert [e.observation_ids for e in episodes] == [("a", "b"), ("d",), ("e",)]


def test_an_unknown_or_unfrozen_definition_forms_no_episodes():
    unknown = EpisodeDefinition("v", None, 3600, D(1), frozen=True)
    result = build_episodes([obs("a", "2026-09-02T00:00:00Z")], unknown)
    assert result.episodes == () and any("start_threshold" in p for p in result.problems)
    unfrozen = EpisodeDefinition("v", D("0.02"), 3600, D(1), frozen=False)
    assert build_episodes([obs("a", "2026-09-02T00:00:00Z")], unfrozen).problems


def test_best_observation_is_a_single_observation_never_a_sum():
    observations = [obs("a", "2026-09-02T00:00:00Z", ladder=(pt(1, "0.03"), pt(10, "0.03"))),
                    obs("b", "2026-09-02T00:10:00Z", ladder=(pt(1, "0.06"), pt(10, "0.05")))]
    (episode,) = build_episodes(observations, DEF).episodes
    assert episode.entry.observation_id == "a" and episode.best.observation_id == "b"
    cons = replay([episode], scen(), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0, window_end_utc=W1)
    less = replay([episode], scen(), size=D(10), mode=FillMode.LESS_CONSERVATIVE, window_start_utc=W0,
                  window_end_utc=W1)
    assert cons.contribution == D("0.30") and less.contribution == D("0.50")  # 10 x 0.03 vs 10 x 0.05; never 0.80


# --------------------------------------------------------------------------- replay


def _episodes(*observations):
    return build_episodes(observations, DEF).episodes


def test_contribution_is_filled_quantity_times_net_edge_with_no_second_fee_or_loss_subtraction():
    eps = _episodes(obs("a", "2026-09-02T00:00:00Z"))
    r = replay(eps, scen(), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0, window_end_utc=W1)
    (fill,) = r.fills
    assert fill.state == "FILLED" and fill.filled == 10 and r.contribution == D(10) * D("0.04")
    assert fill.committed_cash == D(10) * D("0.50")  # capital, not a cost


def test_finite_capital_limits_and_vetoes_and_settlement_releases_it():
    eps = _episodes(
        obs("a", "2026-09-02T00:00:00Z", keys=("k1",), release="2026-09-04T00:00:00Z"),
        obs("b", "2026-09-03T00:00:00Z", keys=("k2",), release="2026-09-05T00:00:00Z"),
        obs("c", "2026-09-06T00:00:00Z", keys=("k3",), release="2026-09-07T00:00:00Z"),
    )
    r = replay(eps, scen(capital="7", reserve="2"), size=D(10), mode=FillMode.CONSERVATIVE,
               window_start_utc=W0, window_end_utc=W1)
    states = [f.state for f in r.fills]
    # 5 usable: a takes all 10 x 0.50; b finds nothing left; after a's release, c fills again.
    assert states == ["FILLED", "CAPITAL_VETO", "FILLED"] and r.max_deployed == D(5)
    r2 = replay(eps, scen(capital="4"), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0,
                window_end_utc=W1)
    assert r2.fills[0].state == "CAPITAL_LIMITED" and r2.fills[0].filled == D(8)


def test_simultaneous_strategies_share_one_capital_pool():
    sports = obs("s", "2026-09-02T00:00:00Z", keys=("sports:k",), cluster="g1")
    payoff = obs("p", "2026-09-02T00:01:00Z", keys=("payoff:k",), cluster="d1")
    r = replay(_episodes(sports, payoff), scen(capital="5"), size=D(10), mode=FillMode.CONSERVATIVE,
               window_start_utc=W0, window_end_utc=W1)
    assert [f.state for f in r.fills] == ["FILLED", "CAPITAL_VETO"]


def test_shared_liquidity_is_never_taken_twice():
    basket_a = obs("a", "2026-09-02T00:00:00Z", keys=("leg1", "leg2"))
    basket_b = obs("b", "2026-09-02T00:00:30Z", keys=("leg2", "leg3"))  # shares leg2 while a is open
    after = obs("c", "2026-09-05T00:00:00Z", keys=("leg2", "leg3"))  # a released on 09-03
    r = replay(_episodes(basket_a, basket_b, after), scen(), size=D(1), mode=FillMode.CONSERVATIVE,
               window_start_utc=W0, window_end_utc=W1)
    assert [f.state for f in r.fills] == ["FILLED", "SHARED_LIQUIDITY", "FILLED"]


def test_doubling_non_binding_capital_changes_nothing_no_bankroll_multiplication():
    eps = _episodes(obs("a", "2026-09-02T00:00:00Z"))
    small = replay(eps, scen(capital="100"), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0,
                   window_end_utc=W1)
    big = replay(eps, scen(capital="100000"), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0,
                 window_end_utc=W1)
    assert small.contribution == big.contribution and small.average_deployed == big.average_deployed
    assert big.return_on_total < small.return_on_total and big.return_on_deployed == small.return_on_deployed
    assert big.scenario_status == ILLUSTRATIVE


def test_unknown_edge_or_release_stays_unknown():
    no_ev = obs("a", "2026-09-02T00:00:00Z", ladder=(pt(1, "0.05"), pt(10, None)))
    r = replay(_episodes(no_ev), scen(), size=D(10), mode=FillMode.CONSERVATIVE, window_start_utc=W0,
               window_end_utc=W1)
    assert r.contribution is None and r.problems
    no_release = obs("b", "2026-09-02T00:00:00Z", release=None)
    r2 = replay(_episodes(no_release), scen(), size=D(1), mode=FillMode.CONSERVATIVE, window_start_utc=W0,
                window_end_utc=W1)
    assert r2.counts["UNKNOWN_RELEASE"] == 1 and not r2.fills[0].release_known
    assert r2.capital_days == (D("0.50") * D(29)).quantize(D("1e-12"))  # held to the window end


def test_unknown_capital_refuses_to_replay():
    scenario = CapitalScenario("x", {"kalshi": Labeled.unknown()}, {"kalshi": Labeled(D(0), Basis.OWNER_INPUT)})
    r = replay(_episodes(obs("a", "2026-09-02T00:00:00Z")), scenario, size=D(1), mode=FillMode.CONSERVATIVE,
               window_start_utc=W0, window_end_utc=W1)
    assert r.fills == () and r.contribution is None and "capital for kalshi is UNKNOWN" in r.problems


def test_capacity_ladder_marks_where_more_size_adds_only_idle_capital():
    eps = _episodes(obs("a", "2026-09-02T00:00:00Z", ladder=(pt(1, "0.05"), pt(10, "0.04"))))
    rows = capacity_ladder(eps, scen(), [D(1), D(10), D(100)], window_start_utc=W0, window_end_utc=W1)
    cons = [r for r in rows if r.mode == "CONSERVATIVE"]
    assert [r.contribution for r in cons] == [D("0.05"), D("0.40"), D("0.40")]
    assert cons[2].depth_limited == 1 and cons[2].idle_capital_flag and not cons[1].idle_capital_flag
    assert cons[1].marginal_contribution == D("0.35") and cons[0].top_cluster_share == 1


# --------------------------------------------------------------------------- screen


def _inputs(observations, **over):
    base = dict(
        family="B", experiment_id="EXP-003", episodes=build_episodes(observations, DEF), scenario=scen(),
        primary_size=D(10), sizes=(D(1), D(10)), window_start_utc=W0, window_end_utc=W1,
        fixed_cash_costs_annual=Labeled(D(0), Basis.OBSERVED, "no paid services"),
        owner_hours_annual=Labeled(D(100), Basis.OWNER_INPUT), owner_hourly_cost=Labeled(D(50), Basis.OWNER_INPUT),
        minimum_useful_annual=Labeled(D(10), Basis.OWNER_INPUT),
        min_episodes_for_scenario=Labeled(D(2), Basis.OWNER_INPUT),
        stationarity_assumption="the window's episode rate and size persist (test)",
    )
    base.update(over)
    return ScreenInputs(**base)


def _two_days():
    return [obs("a", "2026-09-02T00:00:00Z", keys=("k1",), cluster="d1"),
            obs("b", "2026-09-10T00:00:00Z", keys=("k2",), cluster="d2", release="2026-09-11T00:00:00Z")]


def test_screen_says_insufficient_evidence_instead_of_annualizing_a_few_observations():
    report = economic_screen(_inputs(_two_days(), min_episodes_for_scenario=Labeled.unknown()))
    assert report.verdict == Verdict.INSUFFICIENT_EVIDENCE.value
    assert report.variable["annual_scenario_net_conservative"].value is None
    report2 = economic_screen(_inputs(_two_days(), min_episodes_for_scenario=Labeled(D(30), Basis.OWNER_INPUT)))
    assert report2.verdict == "INSUFFICIENT_EVIDENCE" and any("< the protocol minimum 30" in r
                                                               for r in report2.verdict_reasons)


def test_annual_scenario_is_window_contribution_times_365_over_window_days():
    report = economic_screen(_inputs(_two_days()))
    window = report.variable["window_net_conservative"].value
    assert window == D("0.80")  # two episodes x 10 x 0.04
    annual = report.variable["annual_scenario_net_conservative"]
    assert annual.basis is Basis.ESTIMATED and "SIMPLIFIED SCENARIO" in annual.note
    assert annual.value == (D("0.80") * D(365) / D(30)).quantize(D("1e-12"))


def test_owner_time_is_shown_separately_and_never_inside_cash_results():
    report = economic_screen(_inputs(_two_days()))
    assert report.owner_time_cost_annual.value == D(5000)
    assert report.net_after_fixed_annual["conservative"].value == report.variable["annual_scenario_net_conservative"].value


def test_verdicts_are_research_states():
    unviable = economic_screen(_inputs(_two_days(), fixed_cash_costs_annual=Labeled(D(1800), Basis.OWNER_INPUT)))
    assert unviable.verdict == "ECONOMICALLY_UNVIABLE"
    below = economic_screen(_inputs(_two_days(), minimum_useful_annual=Labeled(D(50000), Basis.OWNER_INPUT)))
    assert below.verdict == "BELOW_MINIMUM_USEFUL"
    ok = economic_screen(_inputs(_two_days(), minimum_useful_annual=Labeled(D(5), Basis.OWNER_INPUT)))
    assert ok.verdict == "CONTINUE" and "not evidence of an edge" in ok.not_an_edge_claim
    no_min = economic_screen(_inputs(_two_days(), minimum_useful_annual=Labeled.unknown()))
    assert no_min.verdict == "INSUFFICIENT_EVIDENCE"
    no_fixed = economic_screen(_inputs(_two_days(), fixed_cash_costs_annual=Labeled.unknown()))
    assert no_fixed.verdict == "INSUFFICIENT_EVIDENCE"


def test_verdict_depending_on_the_fill_assumption_is_insufficient():
    observations = [obs("a", "2026-09-02T00:00:00Z", keys=("k1",), cluster="d1",
                        ladder=(pt(1, "0.03"), pt(10, "0.03"))),
                    obs("a2", "2026-09-02T00:10:00Z", keys=("k1",), cluster="d1",
                        ladder=(pt(1, "0.30"), pt(10, "0.30"))),
                    obs("b", "2026-09-10T00:00:00Z", keys=("k2",), cluster="d2")]
    report = economic_screen(_inputs(observations, minimum_useful_annual=Labeled(D(20), Basis.OWNER_INPUT)))
    cons = report.net_after_fixed_annual["conservative"].value
    less = report.net_after_fixed_annual["less_conservative"].value
    assert cons < 20 <= less and report.verdict == "INSUFFICIENT_EVIDENCE"


def test_screen_report_is_deterministic_and_carries_its_inputs_labels():
    a = economic_screen(_inputs(_two_days()))
    b = economic_screen(_inputs(list(reversed(_two_days()))))
    assert a.report_sha256 == b.report_sha256 and a.to_dict() == b.to_dict()
    assert a.inputs["owner_hours_annual"].basis is Basis.OWNER_INPUT
    assert a.scenario_status == ILLUSTRATIVE and a.capacity
    assert a.uncertainty["clusters"] == 2 and a.uncertainty["estimable"]


def test_cluster_bootstrap_needs_two_clusters_and_is_deterministic():
    assert cluster_bootstrap_mean({"a": D(1)}) is None
    band = cluster_bootstrap_mean({"a": D(1), "b": D(3), "c": D(2)})
    assert band == cluster_bootstrap_mean({"c": D(2), "a": D(1), "b": D(3)})
    mean, low, high = band
    assert mean == D(2) and low <= mean <= high
