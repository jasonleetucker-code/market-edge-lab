"""Stake sizing v2 simulation study and replay (SIMULATION / IN-SAMPLE evidence only). No network."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from edge_lab import sizing_eval as se
from edge_lab import sizing_v2 as sv2
from edge_lab.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
TINY = se.StudyConfig(seed=7, paths=3, rounds=15)


def _run(cfg, sc, variants):
    return se._run_scenario((cfg, sc, variants))


def test_simulation_is_reproducible_for_a_fixed_seed():
    variants = se.MAIN_VARIANTS[:3] + (se.Variant(sv2.POLICY_H.policy_id, sv2.POLICY_H),)
    a = _run(TINY, se.BASE, variants)
    b = _run(TINY, se.BASE, variants)
    assert a == b
    c = _run(replace(TINY, seed=8), se.BASE, variants)
    assert c != a


def test_every_policy_sees_the_same_world():
    w1, w2 = se._world(TINY, se.BASE, 0), se._world(TINY, se.BASE, 0)
    assert [[c.outcome for c in r] for r in w1] == [[c.outcome for c in r] for r in w2]
    assert w1[0][0].yes == w2[0][0].yes and w1[0][0].model == w2[0][0].model


def test_sizer_side_scenarios_share_worlds_with_their_base():
    by_id = {s.scenario_id: s for s in se.SCENARIOS}
    base = se._world(TINY, se.BASE, 2)
    for sid in ("overconfident", "exec_shock"):
        other = se._world(TINY, by_id[sid], 2)
        assert [[c.outcome for c in r] for r in other] == [[c.outcome for c in r] for r in base]
        assert other[0][0].market == base[0][0].market
    a = se._world(TINY, by_id["duplicate_misspecified"], 2)
    b = se._world(TINY, by_id["duplicate_shared_cap"], 2)
    assert [[c.yes for c in r] for r in a] == [[c.yes for c in r] for r in b]


def test_duplicate_clusters_share_truth_and_outcome_but_not_prices():
    sc = next(s for s in se.SCENARIOS if s.scenario_id == "duplicate_misspecified")
    world = se._world(TINY, sc, 1)
    for first, second in world:
        assert first.truth == second.truth and first.outcome == second.outcome
    assert any(a.yes != b.yes for a, b in world)


def test_metrics_are_complete_and_sane():
    out = _run(TINY, se.BASE, (se.Variant(sv2.POLICY_E.policy_id, sv2.POLICY_E),))
    m = out[sv2.POLICY_E.policy_id]
    for key in ("mean_log_growth_per_round", "median_terminal_wealth", "p05_terminal_wealth", "p10_terminal_wealth",
                "cvar05_terminal_wealth", "median_max_drawdown", "p_drawdown_over_20pct", "p_drawdown_over_50pct",
                "p_ruin", "volatility_log_return_per_round", "mean_committed_fraction_per_round", "trades_per_round",
                "turnover_cost_per_round_over_w0"):
        assert key in m
    assert m["cvar05_terminal_wealth"] <= m["p05_terminal_wealth"] + 1e-12 <= m["median_terminal_wealth"] + 1e-12
    assert 0 <= m["p_drawdown_over_50pct"] <= m["p_drawdown_over_20pct"] <= 1


def test_the_synthetic_market_is_calibrated_so_edge_comes_only_from_the_model():
    # E[q | m] = m by construction: the mean of (truth - market) is zero, state by state.
    world = se._world(replace(TINY, rounds=4000), se.BASE, 0)
    k = se.BASE.states
    diffs = [sum(r[0].truth[i] - r[0].market[i] for r in world) / len(world) for i in range(k)]
    assert all(abs(d) < 0.01 for d in diffs), diffs
    # With rho = 0 the model is the market plus noise, independent of the truth.
    no_info = next(s for s in se.SCENARIOS if s.scenario_id == "no_information")
    assert no_info.model_weight == 0.0 and se.BASE.model_weight > 0


def test_study_counts_every_variant_run():
    report = se.run_study(replace(TINY, paths=1, rounds=3), only=["uncertainty"])
    assert report["variant_runs_evaluated"] == len(se.UNCERTAINTY_VARIANTS) * len(se.UNCERTAINTY_SCENARIOS)
    assert report["uncertainty_selection"]["selected"]["variant"] in {v.variant_id for v in se.UNCERTAINTY_VARIANTS}
    assert report["label"].startswith("SIMULATION evidence")
    text = se.render_report(report)
    assert "SIMULATION evidence" in text and "Selected:" in text


def test_exp001_replay_is_skipped_with_the_reason():
    out = se.inspect_exp001(ROOT)
    assert out["status"] == "SKIPPED" and "no market price columns" in out["reason"]


def test_record_replay_is_labelled_in_sample():
    record = {"as_of_utc": "2026-09-24T22:00:00+00:00", "states": ["a", "b"], "model_probabilities": [0.7, 0.3],
              "outcome_state": "a", "candidates": [{"side": "YES", "yes_states": ["a"], "asks": [["0.50", 50]]}]}
    out = se.replay_records([record], (sv2.POLICY_C, sv2.POLICY_H))
    assert out["label"].startswith("IN-SAMPLE") and out["records"] == 1
    assert out["policies"][sv2.POLICY_C.policy_id]["trades"] == 1
    assert out["policies"][sv2.POLICY_C.policy_id]["terminal_wealth"] > 1000


def test_cli_sizing_commands(capsys, tmp_path):
    assert cli_main(["sizing", "policies"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 8 and json.loads(lines[0])["policy_id"] == "SV2-A-flat-unit"
    assert cli_main(["sizing", "simulate", "--paths", "1", "--rounds", "2", "--only", "uncertainty",
                     "--out", str(tmp_path)]) == 0
    assert list(tmp_path.glob("simulation_seed*.json")) and list(tmp_path.glob("SIMULATION_REPORT_seed*.md"))
    capsys.readouterr()
    rec = tmp_path / "r.json"
    rec.write_text(json.dumps([{"as_of_utc": "2026-09-24T22:00:00+00:00", "states": ["a", "b"],
                                "model_probabilities": [0.6, 0.4], "outcome_state": "b",
                                "candidates": [{"side": "YES", "yes_states": ["a"], "asks": [["0.45", 10]]}]}]))
    assert cli_main(["sizing", "replay", "--input", str(rec)]) == 0
    assert "IN-SAMPLE" in capsys.readouterr().out
