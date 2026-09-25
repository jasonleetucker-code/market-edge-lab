"""Fill-mode labels v2 (ADR 0037): first detection is zero-latency, the best observation is a hindsight bound.

Neither fill mode is executable performance, and the hindsight upper bound can only rule a family out.
The enum values are unchanged for compatibility; EXP-001 is not touched.
"""

from decimal import Decimal as D
from pathlib import Path

from edge_lab import research_economics as rec
from edge_lab.research_economics import (
    Basis, CapitalScenario, EdgeKind, EpisodeDefinition, FillMode, Labeled, Observation, ScreenInputs, SizePoint,
    build_episodes, capacity_ladder, economic_screen, replay,
)

ROOT = Path(__file__).resolve().parents[1]
W0, W1 = "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
DEF = EpisodeDefinition("ep-labels-v2", start_threshold=D("0.02"), end_merge_gap_seconds=3600, minimum_size=D(1),
                        frozen=True)


def pt(q, net, cost="0.50"):
    return SizePoint(D(q), "FILLABLE", D(cost), D(net) + D("0.01"), D(net))


def obs(oid, t, *, keys, cluster, ladder, release="2026-09-20T00:00:00Z"):
    return Observation(oid, tuple(keys), "kalshi", t, cluster, EdgeKind.CONDITIONAL_BOUND, tuple(ladder), release)


def scen(capital="1000"):
    return CapitalScenario("S", {"kalshi": Labeled(D(capital), Basis.OWNER_INPUT)},
                           {"kalshi": Labeled(D(0), Basis.OWNER_INPUT)})


def _inputs(observations, **over):
    base = dict(
        family="B", experiment_id="EXP-900", episodes=build_episodes(observations, DEF), scenario=scen(),
        primary_size=D(1), sizes=(D(1),), window_start_utc=W0, window_end_utc=W1,
        fixed_cash_costs_annual=Labeled(D(0), Basis.OBSERVED, "none"),
        owner_hours_annual=Labeled.unknown(), owner_hourly_cost=Labeled.unknown(),
        minimum_useful_annual=Labeled(D(10), Basis.OWNER_INPUT),
        min_episodes_for_scenario=Labeled(D(2), Basis.OWNER_INPUT),
        stationarity_assumption="test", min_independent_clusters=Labeled(D(2), Basis.OWNER_INPUT),
    )
    base.update(over)
    return ScreenInputs(**base)


def _hindsight_rich():
    """Each episode's first look is weak (0.03) and a later look is huge (0.90): only hindsight is rich."""
    out = []
    for i, day in enumerate(("02", "09", "16")):
        out.append(obs(f"first{i}", f"2026-09-{day}T00:00:00Z", keys=(f"k{i}",), cluster=f"d{i}",
                       ladder=(pt(1, "0.03"),)))
        out.append(obs(f"later{i}", f"2026-09-{day}T00:30:00Z", keys=(f"k{i}",), cluster=f"d{i}",
                       ladder=(pt(1, "0.90"),)))
    return out


def test_enum_values_are_unchanged_for_compatibility_and_the_version_is_bumped():
    assert [m.value for m in FillMode] == ["CONSERVATIVE", "LESS_CONSERVATIVE"]
    assert rec.ECONOMICS_VERSION == "research-economics-v2"
    assert rec.FILL_MODE_LABELS_VERSION == "fill-mode-labels-v2"


def test_the_labels_say_what_each_mode_is_and_neither_is_executable():
    first = rec.FILL_MODE_SEMANTICS[FillMode.CONSERVATIVE]
    hindsight = rec.FILL_MODE_SEMANTICS[FillMode.LESS_CONSERVATIVE]
    assert first.label == "FIRST_DETECTION_ZERO_LATENCY" and hindsight.label == "HINDSIGHT_UPPER_BOUND"
    assert first.prospective_selection and not hindsight.prospective_selection
    for sem in (first, hindsight):
        assert sem.executable_performance is False and sem.delay_adjusted is False
        assert sem.to_dict()["labels_version"] == rec.FILL_MODE_LABELS_VERSION
    assert "never supports CONTINUE" in hindsight.permitted_use
    assert "zero decision and submission delay" in first.caveat
    assert rec.EXECUTABLE_PERFORMANCE.startswith("NONE")


def test_replays_and_capacity_rows_carry_the_mode_label():
    episodes = build_episodes(_hindsight_rich(), DEF).episodes
    for mode in FillMode:
        r = replay(episodes, scen(), size=D(1), mode=mode, window_start_utc=W0, window_end_utc=W1)
        assert r.mode_label == rec.fill_mode_label(mode)
    rows = capacity_ladder(episodes, scen(), [D(1)], window_start_utc=W0, window_end_utc=W1)
    assert {(row.mode, row.mode_label) for row in rows} == {
        ("CONSERVATIVE", "FIRST_DETECTION_ZERO_LATENCY"), ("LESS_CONSERVATIVE", "HINDSIGHT_UPPER_BOUND")}


def test_the_screen_report_states_the_labels_and_that_nothing_is_executable_performance():
    report = economic_screen(_inputs(_hindsight_rich()))
    body = report.to_dict()
    assert body["fill_modes"]["conservative"]["label"] == "FIRST_DETECTION_ZERO_LATENCY"
    assert body["fill_modes"]["less_conservative"]["label"] == "HINDSIGHT_UPPER_BOUND"
    assert all(m["executable_performance"] is False for m in body["fill_modes"].values())
    assert body["executable_performance"].startswith("NONE")
    # Every less-conservative figure carries the hindsight label in its note.
    less = {k: v for k, v in report.variable.items() if k.endswith("less_conservative")}
    assert less and all("HINDSIGHT_UPPER_BOUND" in v.note for v in less.values())
    assert all("HINDSIGHT_UPPER_BOUND" in v.note for k, v in report.net_after_fixed_annual.items()
               if k.startswith("less_conservative"))


def test_a_hindsight_upper_bound_alone_never_supports_continue():
    # The hindsight bound clears the minimum by far; the first-detection bound does not. The screen
    # may not say CONTINUE on the hindsight figure.
    report = economic_screen(_inputs(_hindsight_rich(), minimum_useful_annual=Labeled(D(3), Basis.OWNER_INPUT)))
    less_upper = report.net_after_fixed_annual["less_conservative_upper"].value
    cons_lower = report.net_after_fixed_annual["conservative_lower"].value
    assert less_upper >= 3 > cons_lower
    assert report.verdict != "CONTINUE"


def test_the_hindsight_bound_may_rule_a_family_out():
    # Even the hindsight upper bound cannot clear the fixed costs: UNVIABLE is a legitimate use of an upper bound.
    report = economic_screen(_inputs(_hindsight_rich(),
                                     fixed_cash_costs_annual=Labeled(D(100000), Basis.OWNER_INPUT)))
    assert report.verdict == "ECONOMICALLY_UNVIABLE"


def test_family_a_fill_mode_texts_lead_with_the_honest_labels():
    from edge_lab import sports_evidence

    texts = {m["id"]: m["text"] for m in sports_evidence.FILL_MODES}
    assert texts["CONSERVATIVE"].startswith("FIRST_DETECTION_ZERO_LATENCY")
    assert texts["LESS_CONSERVATIVE"].startswith("HINDSIGHT_UPPER_BOUND")
    assert all("not executable performance" in t or "never an achievable policy or executable performance" in t
               for t in texts.values())


def test_the_research_principles_and_the_exp002_draft_use_the_v2_labels():
    principles = (ROOT / "docs" / "RESEARCH_PRINCIPLES.md").read_text(encoding="utf-8")
    protocol = (ROOT / "experiments" / "EXP-002-nfl-consensus-vs-event-market" / "protocol.toml").read_text(
        encoding="utf-8")
    for text in (principles, protocol):
        assert "HINDSIGHT_UPPER_BOUND" in text and "FIRST_DETECTION_ZERO_LATENCY" in text
    assert "less-conservative bound (the best single observation)" not in principles
