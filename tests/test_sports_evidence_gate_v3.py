"""EXP-002 gate v3 (owner directive 2026-09-28 §7 and §23; docs/research/EXP002_GATE_V3.md).

The spread-based noise scale was a CANDIDATE needing validation. These tests pin what the validation found:
the candidate passes while the true bias exceeds the tolerable level (sticky, stale, shared-upstream quotes), a
quoted spread is not a bound, and gate v3 therefore has no PASS state. Offline and SYNTHETIC only; no network.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import shutil
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.storage import SnapshotStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_sports_evidence_exp002 as t2  # noqa: E402  (the SYNTHETIC store builder of the v2 tests)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "research_power_sensitivity.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("research_power_sensitivity_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ps = _load_script()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    monkeypatch.setattr(se, "_clock", lambda: datetime(2026, 11, 1, tzinfo=UTC))


def _side(bid: str | None, ask: str | None, p: float, *, timing: str = se.BOOK_AT_OR_AFTER_ODDS,
          received: str = "2026-10-04T11:00:00Z") -> dict:
    return {"yes_bid": bid, "yes_ask": ask, "consensus_probability": f"{p:.4f}", "book_received_utc": received,
            "book_timing": timing, "rules": {}}


def _row(game: str, week: str, horizon: str = "T-6h", *, status: str = se.PAIRED, home=("0.49", "0.50"),
         away=("0.50", "0.51"), c: float = 0.52, timing: str = se.BOOK_AT_OR_AFTER_ODDS, away_received=None) -> dict:
    return {"horizon": horizon, "status": status, "home_team": "H", "away_team": "A", "week_cluster": week,
            "event_id": game, "sides": {} if status != se.PAIRED else {
                "H": _side(*home, c, timing=timing),
                "A": _side(*away, 1 - c, timing=timing, received=away_received or "2026-10-04T11:00:02Z")}}


def _many(n_weeks: int = 4, per_week: int = 6, **kw) -> list[dict]:
    rng = random.Random(3)
    rows = []
    for w in range(n_weeks):
        for i in range(per_week):
            c = 0.5 + rng.gauss(0, 0.03)
            rows.append(_row(f"g{w}-{i}", f"week-{w}", c=c, **kw))
            rows.append(_row(f"g{w}-{i}", f"week-{w}", "T-24h", c=c, **kw))
    return rows


# ================================================================== the bound and its assumptions


def test_the_conditional_bound_is_the_documented_formula():
    g = se.GateV3Game("w", "g", h_mid=0.50, h_spread=0.01, a_mid=0.51, a_spread=0.02, c=0.505, c_prime=0.55,
                      timing=(None, None), capture_skew_seconds=2)
    # |c - H6| = 0.005 <= s_H: the first half counts s_A; |c' - A6| = 0.04 > s_A: the second counts nothing.
    assert se.v3_bias_bound_terms([g]) == [("w", "g", pytest.approx(0.5 * 0.02))]
    edge = se.GateV3Game("w", "g", 0.50, 0.01, 0.50, 0.01, 0.51, 0.49, (None, None), 0)
    assert se.v3_bias_bound_terms([edge])[0][2] == pytest.approx(0.01)  # a gap equal to the spread is inside


def test_the_bound_holds_when_the_value_is_inside_every_spread_even_with_a_perfectly_shared_error():
    # Worst case under W: both books carry the SAME error at +-s/2 (fully shared), the consensus knows V6 up to
    # a small deviation. The simulated bias of the cross-book markout never exceeds the bound B.
    rng = random.Random(11)
    ys, bs = [], []
    for _ in range(15_000):
        v6 = rng.uniform(0.3, 0.7)
        v1 = v6 + rng.gauss(0, 0.02)
        e = rng.choice((-0.005, 0.005))  # |mid - V| = s/2, shared by both books
        h6 = a6 = v6 + e
        h1 = a1 = v1 + rng.choice((-0.005, 0.005))
        c = v6 + rng.gauss(0, 0.004)
        ys.append(se.cross_book_markout(c, c, h6, a6, h1, a1))
        bs.append(se.v3_bias_bound_terms([se.GateV3Game("w", "g", h6, 0.01, a6, 0.01, c, c, (None, None), 0)])[0][2])
    mean_y, se_y = sum(ys) / len(ys), (sum((y - sum(ys) / len(ys)) ** 2 for y in ys) / (len(ys) - 1) / len(ys)) ** 0.5
    assert mean_y > 0.001  # a real bias exists (shared error reverts) ...
    assert mean_y + 3 * se_y <= sum(bs) / len(bs)  # ... and the bound covers it


def test_a_spread_is_not_a_bound_when_the_value_leaves_it():
    # Narrow (1-tick) but stale quotes: the latent value moved 3c while the quote did not. The bound B under W
    # is small, yet the true bias is far larger: nothing in the spreads reveals it.
    sc = ps.GateScenario("stale_test", "stale", stale_prob=0.5, sigma_idio=0.001, consensus_sd=0.06)
    truth, truth_se = ps.true_bias(sc, n=20_000)
    rows, _ = ps._rows_for(sc, random.Random(5))
    gate = se.noise_gate_v3(se.gate_v3_observations(rows), resamples=200)
    assert truth - 3 * truth_se > gate["estimates"]["bias_bound_upper_90"]  # the bound understates the bias
    assert gate["verdict"] == se.V3_INSUFFICIENT_EVIDENCE and gate["freeze_eligible"] is False
    assert "not a bound" in gate["not_a_bound"]


# ================================================================== verdicts and states


def test_gate_v3_has_no_pass_state_and_nothing_is_freeze_eligible():
    for rows in (_many(), _many(n_weeks=1), [], _many(home=("0.49", "0.50"), away=("0.50", "0.51"))):
        gate = se.noise_gate_v3(se.gate_v3_observations(rows), resamples=100)
        assert gate["verdict"] in (se.V3_FAIL, se.V3_INSUFFICIENT_DATA, se.V3_INSUFFICIENT_EVIDENCE)
        assert gate["freeze_eligible"] is False and gate["diagnostic_only"] is True
        assert all(r["freeze_eligible"] is False and r["verdict"] != "PASS" for r in gate["by_candidate_min_effect"])
        assert "\"PASS" not in json.dumps(gate)  # no verdict value starts with PASS


def test_mirror_quoting_fails_and_enough_varied_books_are_insufficient_evidence():
    mirror = se.noise_gate_v3(se.gate_v3_observations(_many()), resamples=100)  # H = 1 - away mid exactly
    assert mirror["estimates"]["mirror_quoting"] and mirror["verdict"] == se.V3_FAIL
    rng = random.Random(8)
    varied = []
    for w in range(4):
        for i in range(6):
            c = 0.5 + rng.gauss(0, 0.03)
            away = rng.choice((("0.50", "0.51"), ("0.49", "0.51"), ("0.50", "0.52")))
            varied += [_row(f"g{w}-{i}", f"week-{w}", c=c, away=away), _row(f"g{w}-{i}", f"week-{w}", "T-24h", c=c,
                                                                             away=away)]
    gate = se.noise_gate_v3(se.gate_v3_observations(varied), min_effect=0.005, resamples=200)
    assert gate["verdict"] == se.V3_INSUFFICIENT_EVIDENCE == gate["verdict_for_min_effect"]["verdict"]
    assert gate["verdict_for_min_effect"]["bound_state"] in (se.V3_BOUND_BELOW, se.V3_BOUND_AT_OR_ABOVE)
    assert gate["min_effect_state"] == "SUPPLIED"


def test_small_and_empty_samples_are_insufficient_data_never_a_verdict():
    empty = se.noise_gate_v3(se.gate_v3_observations([]), resamples=50)
    assert empty["verdict"] == se.V3_INSUFFICIENT_DATA and empty["counts"]["admissible_games"] == 0
    assert empty["estimates"]["bias_bound_mean"] is None and empty["estimates"]["admissible_share_of_due_t6"] is None
    three_weeks = se.noise_gate_v3(se.gate_v3_observations(_many(n_weeks=3, per_week=10)), resamples=50)
    assert three_weeks["verdict"] in (se.V3_INSUFFICIENT_DATA, se.V3_FAIL)
    assert any("NFL week" in x for x in three_weeks["insufficient"])
    few = se.noise_gate_v3(se.gate_v3_observations(_many(n_weeks=4, per_week=2)), resamples=50)
    assert any("admissible T-6h games" in x for x in few["insufficient"])


def test_an_empty_log_reads_no_label_view_and_the_committed_exposure_record_is_unconfirmed(tmp_path):
    root, own = t2._registry_copy(tmp_path)
    protocol = se.protocol_status(root)
    uses = rev.read_log(own).uses
    hand = [u for u in uses if u.actor == "coordinator (recorded by VF Writer A)"]
    # the opening record (to 01:16:30Z) and its follow-up closing the window at the #124 deploy
    assert len(hand) == 2 and all(u.viewed_labels is None and u.influenced_tuning is False for u in hand)
    assert all(u.role is rev.DatasetRole.DEVELOPMENT and u.window.scope == "sports:nfl:moneyline" for u in hand)
    assert all("NOT A CONFIRMED VIEW" in u.note for u in hand)
    assert max(u.window.end_utc for u in hand) == "2026-09-29T02:09:50Z"
    header = own.read_text(encoding="utf-8").splitlines()[0]
    own.write_text(header + "\n", encoding="utf-8")  # a copy in tmp_path; the committed log is never touched
    assert se.outcome_access(protocol, root)["state"] == "NO_LABEL_VIEW_LOGGED"


def test_book_states_and_attrition_reconcile():
    rows = [
        _row("ok", "w1"),
        _row("before", "w1", timing=se.BOOK_BEFORE_ODDS),  # comparability-only: still admissible for the markout
        _row("locked", "w1", home=("0.50", "0.50")),
        _row("crossed", "w1", away=("0.52", "0.51")),
        _row("onesided", "w1", home=(None, "0.50")),
        _row("unpaired", "w1", status="EXCLUDED"),
        _row("later", "w1", status=se.NOT_YET_DUE),
        _row("skewed", "w1", away_received="2026-10-04T11:09:00Z"),
        _row("t60", "w1", "T-60m"),  # a label horizon: never looked at
    ]
    rows[0]["sides"]["H"]["consensus_probability"] = "0.5200"
    nocons = _row("nocons", "w1")
    nocons["sides"]["A"]["consensus_probability"] = None
    rows.append(nocons)
    before = json.dumps(rows, sort_keys=True)
    c = se.gate_v3_observations(rows).counts
    assert json.dumps(rows, sort_keys=True) == before  # the join's pairing is read, never changed
    assert c["rows_other_horizon_ignored"] == 1 and c["t6_not_yet_due_or_superseded"] == 1
    assert c["t6_due"] == 8
    assert c["t6_due"] == (c["t6_not_paired"] + c["t6_book_one_sided_or_empty"] + c["t6_book_locked"]
                           + c["t6_book_crossed"] + c["t6_no_consensus"] + c["t6_admissible"])
    assert (c["t6_book_locked"], c["t6_book_crossed"], c["t6_book_one_sided_or_empty"]) == (1, 1, 1)
    assert c["t6_not_paired"] == 1 and c["t6_no_consensus"] == 1 and c["t6_admissible"] == 3
    assert c["t6_admissible_book_before_odds"] == 2  # both sides of the BEFORE_ODDS game, counted, not dropped
    assert c["not_same_capture"] == 1  # the skewed pair is admissible but gives no same-capture dispersion


def test_the_gate_reads_the_markouts_own_consensus_value_and_units():
    obs = se.gate_v3_observations([_row("g", "w", c=0.53, away=("0.46", "0.48"))])
    g = obs.games[0]
    assert g.h_mid == pytest.approx(0.495) and g.a_mid == pytest.approx(1 - 0.47)  # home-team units
    assert g.c == pytest.approx(0.53) and g.c_prime == pytest.approx(0.53)  # c' = 1 - consensus of the away side
    assert g.a_spread == pytest.approx(0.02)


# ================================================================== label safety and versioning (SYNTHETIC store)


def test_gate_v3_never_loads_a_t60m_book_and_v2_is_unchanged(tmp_path, monkeypatch):
    path, now, sids = t2.build_store(tmp_path)
    loaded: list[int] = []
    original = se._Payloads.payload

    def spy(self, sid):
        loaded.append(sid)
        return original(self, sid)

    monkeypatch.setattr(se._Payloads, "payload", spy)
    out = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now)
    assert not set(loaded) & sids["T-60m"]  # no label book, whichever gate
    assert out["version"] == "exp002-measurement-v3" and out["gate"]["version"] == "exp002-noise-gate-v2"
    v3 = out["gate_v3"]
    assert v3["version"] == se.GATE_V3_VERSION == "exp002-noise-gate-v3" and v3["label_free"]
    assert v3["counts"]["admissible_games"] == 12 and v3["counts"]["weeks"] == 2
    assert v3["verdict"] == se.V3_INSUFFICIENT_DATA  # two weeks < four
    # v2 keeps its own semantics: the same verdict as before gate v3 existed, never freeze-eligible
    assert out["gate"]["verdict"] == se.INSUFFICIENT and out["gate"]["freeze_eligible"] is False
    assert out["markout"]["state"] == "HIDDEN"


def test_a_legacy_v2_pass_never_makes_anything_freeze_eligible():
    obs = t2._obs(rho=0.15)
    v2 = se.noise_gate(obs, min_effect=0.0025, resamples=200)
    assert v2["verdict"] == se.PASS and v2["freeze_eligible"] is False
    protocol = {"state": "DRAFT", "experiment_id": "EXP-002", "unsettled_fields": ["a", "b"]}
    for gate in (v2, se.noise_gate_v3(se.gate_v3_observations(_many()), resamples=50)):
        freeze = se.freeze_eligibility(gate, protocol)
        assert freeze["state"] == "NOT_ELIGIBLE" and freeze["reasons"]
        assert "no gate state authorizes a freeze" in freeze["reasons"][0]


def test_the_gate_line_reports_logged_label_access_and_keeps_freeze_separate(tmp_path):
    path, now, _ = t2.build_store(tmp_path)
    root, own = t2._registry_copy(tmp_path)
    store = SnapshotStore.open_readonly(path)
    protocol = se.protocol_status(root)
    line = se.exp002_gate_line(store, as_of=now, protocol=protocol, experiments_root=root, resamples=100)
    assert line["state"] == "OK" and line["diagnostic_only"] and line["label_free"]
    # The committed log holds one hand-recorded POSSIBLE exposure (the pre-#124 Terminal display; viewed_labels
    # unknown): counted apart from confirmed views and never read as "no access".
    first = line["outcome_access"]
    assert first["state"] == "POSSIBLE_LABEL_EXPOSURE_LOGGED" and first["label_views"] == 0
    assert first["possible_label_exposures"] >= 1 and first["roles"] == ["DEVELOPMENT"]
    assert line["freeze"]["state"] == "NOT_ELIGIBLE"
    measured = se.measure_exp002(store, as_of=now, results=True, experiments_root=root)
    se.record_markout_view(measured, log=own, actor="test", code_version="abc123", experiments_root=root)
    after = se.outcome_access(protocol, root)
    assert after["state"] == "LABEL_VIEWS_LOGGED" and after["label_views"] == 1 and after["roles"] == ["DEVELOPMENT"]
    assert after["possible_label_exposures"] == first["possible_label_exposures"]
    assert rev.read_log(own).uses[-1].action is rev.Action.LABEL_RESULT_INSPECTION
    assert se.outcome_access({"state": "NOT_REGISTERED"}, root)["state"] == "NO_PROTOCOL"


def test_the_terminal_view_carries_the_gate_line_and_hides_t60m_prices(tmp_path):
    path, now, sids = t2.build_store(tmp_path)
    root, own = t2._registry_copy(tmp_path)
    view = se.terminal_view(path, now=now, experiments_root=root)
    family = view["family_a"]
    gate = family["exp002_gate"]
    assert gate["state"] == "OK" and gate["version"] == se.GATE_V3_VERSION and gate["freeze"]["state"] == "NOT_ELIGIBLE"
    assert gate["outcome_access"]["state"] == "POSSIBLE_LABEL_EXPOSURE_LOGGED"  # the committed hand record
    assert family["capacity"]["latest"]["horizon"] in ("T-24h", "T-6h")  # a T-60m book is a label: not shown
    # a label view logged after the first render shows on the next one (the log is read per view, not cached)
    measured = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, experiments_root=root)
    se.record_markout_view(measured, log=own, actor="test", code_version="abc123", experiments_root=root)
    again = se.terminal_view(path, now=now, experiments_root=root)["family_a"]["exp002_gate"]
    assert again["outcome_access"]["state"] == "LABEL_VIEWS_LOGGED"


def test_the_full_report_hides_t60m_book_prices_unless_the_view_is_logged(tmp_path, capsys):
    path, now, sids = t2.build_store(tmp_path)
    root, own = t2._registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    assert se.main(["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root)]) == 0
    plain_report = json.loads(capsys.readouterr().out)
    t60 = [s for r in plain_report["rows"] if r["horizon"] == "T-60m" for s in r["sides"].values()]
    assert t60 and all(s.get("book_snapshot_id") for s in t60)  # availability stays visible ...
    for s in t60:  # ... prices, sizes, depth and the ladder do not
        assert not set(s) & set(se.LABEL_BOOK_FIELDS) and s["label_book"] == se.LABEL_BOOK_HIDDEN
    earlier = [s for r in plain_report["rows"] if r["horizon"] in ("T-24h", "T-6h") for s in r["sides"].values()]
    assert earlier and all(s.get("yes_ask") is not None for s in earlier)  # features stay
    assert len(rev.read_log(own).uses) == before  # nothing was logged, nothing label-bearing was shown
    view = se.terminal_view(path, now=now, experiments_root=root)["family_a"]
    assert view["capacity"]["latest"]["horizon"] != "T-60m"
    assert se.main(["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root),
                    "--with-results", "--evidence-log", str(own), "--actor", "test", "--code-version", "abc"]) == 0
    logged = json.loads(capsys.readouterr().out)
    t60_logged = [s for r in logged["rows"] if r["horizon"] == "T-60m" for s in r["sides"].values()]
    assert any(s.get("yes_ask") is not None for s in t60_logged) and logged["evidence_use"] == "APPENDED"


def test_a_crossed_t60m_book_leaks_no_price_through_its_reasons(tmp_path, capsys):
    from decimal import Decimal

    from edge_lab.dashboard import sports_fixtures as sf
    from edge_lab.odds_schedule import iso_z

    path, now, _ = t2.build_store(tmp_path)
    rows = se.build_report(SnapshotStore.open_readonly(path), as_of=now, results=True)["rows"]
    target = next(r for r in rows if r["horizon"] == "T-60m" and (r.get("kalshi") or {}).get("tickers"))
    ticker = sorted(target["kalshi"]["tickers"].values())[0]
    at = datetime.fromisoformat(target["odds"]["received_utc"].replace("Z", "+00:00")) + timedelta(seconds=30)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-crossed-t60m")
    store.save_snapshot(run_id="SYNTHETIC-crossed-t60m", source=se.KALSHI, kind="orderbook", entity_id=ticker,
                        url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                        payload=sf._book(Decimal("0.61"), crossed=True), fetched_at_utc=iso_z(at),
                        source_id="kalshi_public")
    store.finish_run("SYNTHETIC-crossed-t60m", status="succeeded")
    logged = se.build_report(SnapshotStore.open_readonly(path), as_of=now, results=True)
    crossed = [s for r in logged["rows"] if r["event_id"] == target["event_id"] and r["horizon"] == "T-60m"
               for s in r["sides"].values() if any("crossed book" in x for x in s.get("reasons") or [])]
    assert crossed  # the fixture really produced a crossed T-60m book whose reason quotes its bids
    root, _ = t2._registry_copy(tmp_path)
    assert se.main(["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root)]) == 0
    text = capsys.readouterr().out
    assert "crossed book" not in text and "0.62" not in text  # neither the anomaly nor the crossed YES bid
    shown = json.loads(text)
    row = next(r for r in shown["rows"] if r["event_id"] == target["event_id"] and r["horizon"] == "T-60m")
    side = next(s for s in row["sides"].values() if s["ticker"] == ticker)
    assert side["stage"] == "KALSHI_BOOK_UNUSABLE" and side["reasons"] == [
        f"KALSHI_BOOK_UNUSABLE: {se.LABEL_BOOK_REASON}"]
    assert f"KALSHI_BOOK_UNUSABLE [{side['team']}]: {se.LABEL_BOOK_REASON}" in row["reasons"]
    view = se.terminal_view(path, now=now, experiments_root=root)
    assert "crossed book" not in json.dumps(view, default=str)


def test_a_gate_error_is_a_state_not_a_crash(tmp_path, monkeypatch):
    path, now, _ = t2.build_store(tmp_path)

    def broken(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(se, "noise_gate_v3", broken)
    line = se.exp002_gate_line(SnapshotStore.open_readonly(path), as_of=now, rows=[])
    assert line["state"] == "ERROR" and "boom" in line["detail"]


def test_cli_prints_both_gate_verdicts_and_no_freeze(tmp_path, capsys):
    path, now, _ = t2.build_store(tmp_path)
    root, _ = t2._registry_copy(tmp_path)
    out = tmp_path / "m.json"
    assert se.main(["exp002", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root),
                    "--out", str(out)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["gate_v3_verdict"] == se.V3_INSUFFICIENT_DATA and summary["freeze_eligible"] is False
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["gate_v3"]["version"] == se.GATE_V3_VERSION and "games" not in body["markout"]


# ================================================================== adversarial validation (small, deterministic)


def _scenario(name: str):
    return next(s for s in ps.GATE_SCENARIOS if s.name == name)


def test_the_spread_candidate_false_passes_under_sticky_stale_and_shared_quotes():
    rows = ps.validate_gate_v3(reps=12, truth_games=15_000, resamples=100,
                               scenarios=(_scenario("sticky_band"), _scenario("narrow_but_stale"),
                                          _scenario("shared_upstream_near_mirror")))
    above = [r for r in rows if r.bias_state == "ABOVE"]
    assert len(above) == 9  # every row's true bias is far above the tolerable level
    assert max(r.candidate_pass_rate for r in above) > ps.ACCEPTANCE_FALSE_PASS  # the candidate is rejected
    assert all(r.v3_pass_rate == 0 for r in rows)  # v3 never passes
    assert all(set(r.v3_verdicts) <= {"INSUFFICIENT_EVIDENCE", "INSUFFICIENT_DATA", "FAIL"} for r in rows)


def test_correlated_book_noise_and_underestimated_latent_noise_never_pass_v3():
    rows = ps.validate_gate_v3(reps=10, truth_games=15_000, resamples=100,
                               scenarios=(_scenario("review_grid_rho_055"), _scenario("narrow_but_stale_wide_gaps")))
    stale_wide = [r for r in rows if r.scenario == "narrow_but_stale_wide_gaps" and r.min_effect == 0.01][0]
    # the conditional bound (what v3 would pass IF W were granted) is below the tolerable level in most samples
    # while the true bias is above it: the latent noise beyond the spread is invisible
    assert stale_wide.bias_state == "ABOVE" and stale_wide.v3_conditional_below_rate > ps.ACCEPTANCE_FALSE_PASS
    assert all(r.v3_pass_rate == 0 for r in rows)


def test_where_assumption_w_holds_the_conditional_bound_does_not_false_pass():
    rows = ps.validate_gate_v3(reps=12, truth_games=20_000, resamples=100,
                               scenarios=(_scenario("asymmetric_spreads_within"),))
    above = [r for r in rows if r.bias_state == "ABOVE"]
    assert above and all(r.w_holds for r in above)
    assert max(r.v3_conditional_below_rate for r in above) <= ps.ACCEPTANCE_FALSE_PASS


def test_small_samples_with_informative_missingness_are_insufficient_data():
    rows = ps.validate_gate_v3(reps=8, truth_games=5_000, resamples=50,
                               scenarios=(_scenario("small_sample_missing"),))
    assert all(r.v3_pass_rate == 0 for r in rows)
    assert all(r.v3_verdicts.get("INSUFFICIENT_DATA", 0) + r.v3_verdicts.get("FAIL", 0) == 8 for r in rows)


def test_the_committed_validation_document_matches_a_rerun():
    doc = (ROOT / "docs" / "research" / "EXP002_GATE_V3_VALIDATION.md").read_text(encoding="utf-8")
    rows = ps.validate_gate_v3(reps=200, scenarios=(_scenario("small_sample_missing"),))
    rerun = [line for line in ps.gate_validation_markdown(rows).splitlines() if line.startswith("| small_sample")]
    assert len(rerun) == 3 and all(line in doc.splitlines() for line in rerun)
    assert "| v3_verdict | 37 | 0% | 0 |" in doc and "| spread_candidate | 37 | 98% | 21 |" in doc


def test_the_validation_is_deterministic_and_the_summary_counts_only_rows_clearly_above():
    a = ps.validate_gate_v3(reps=3, truth_games=3_000, resamples=30, scenarios=(_scenario("sticky_band"),))
    b = ps.validate_gate_v3(reps=3, truth_games=3_000, resamples=30, scenarios=(_scenario("sticky_band"),))
    assert a == b
    s = ps.false_pass_summary(a)
    assert s["v3_verdict"]["max_false_pass"] == 0
    assert ps._bias_state(0.01, 0.001, 0.005) == "ABOVE" and ps._bias_state(0.001, 0.001, 0.005) == "BELOW"
    assert ps._bias_state(0.005, 0.001, 0.005) == "BORDERLINE"
    text = ps.gate_validation_markdown(a)
    assert "v3 itself never passes" in text and "sticky_band" in text
