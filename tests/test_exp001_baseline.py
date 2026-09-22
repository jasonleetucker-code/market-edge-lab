"""EXP-001 Gate 4 baseline: model math, references, selection rule, PIT, test-split guards.

Every test here uses SYNTHETIC data, except `test_dataset_constant_matches_frozen_pin`,
which reads only the preregistration file.
"""

import csv
import importlib.util
import io
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from edge_lab import exp001_baseline as b
from edge_lab import stats

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market"


def day(target="2020-01-15", f=50, y=50, split="train"):
    return b.Day(target_date=target, split=split, f=f, y=y)


def _script():
    spec = importlib.util.spec_from_file_location("run_exp001_gate4", ROOT / "scripts" / "run_exp001_gate4.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_csv(step=5, seed=7, seasonal_bias=False):
    """Rows 2017-01-01..2026-09-21 every `step` days with integer forecast/label."""
    rng = random.Random(seed)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["target_date", "split", "forecast_max_f", "label_f", "usable"],
                            lineterminator="\n")
    writer.writeheader()
    current = date(2017, 1, 1)
    while current <= date(2026, 9, 21):
        split = "train" if current.year <= 2022 else "validation" if current.year <= 2024 else "test"
        climate = 55 + 25 * math.sin((current.timetuple().tm_yday - 105) / 365 * 2 * math.pi)
        f = round(climate + rng.gauss(0, 6))
        bias = (4 if current.month in (6, 7, 8) else -4) if seasonal_bias else 0
        y = f + bias + round(rng.gauss(0.4, 3))
        writer.writerow({"target_date": current.isoformat(), "split": split, "forecast_max_f": f,
                         "label_f": y, "usable": "true"})
        current += timedelta(days=step)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Model math
# ---------------------------------------------------------------------------
def test_pmf_formula_and_clamped_counting():
    days = [day(y=50), day(y=50), day(y=51), day(y=49), day(y=75), day(y=10)]  # k = 0,0,1,-1,+25,-40
    pmf = b.error_pmf(days)
    denominator = 6 + 0.5 * 41
    assert len(pmf) == 41
    assert pmf[20] == 2.5 / denominator  # k = 0
    assert pmf[21] == 1.5 / denominator and pmf[19] == 1.5 / denominator
    assert pmf[40] == 1.5 / denominator  # +25 counted at +20
    assert pmf[0] == 1.5 / denominator  # -40 counted at -20
    assert pmf[30] == 0.5 / denominator
    assert math.isclose(math.fsum(pmf), 1.0, rel_tol=1e-12)


def test_clamping_and_scoring_outside_range():
    assert b.clamp_k(25) == 20 and b.clamp_k(-30) == -20 and b.clamp_k(7) == 7
    pmf = b.error_pmf([day(y=50)])
    assert b.pmf_log_score(pmf, day(f=50, y=90)) == math.log(pmf[40])
    assert b.pmf_log_score(pmf, day(f=50, y=0)) == math.log(pmf[0])


def test_seasons_use_the_frozen_mapping():
    assert [day(f"2021-{m:02d}-05").season for m in range(1, 13)] == [
        "DJF", "DJF", "MAM", "MAM", "MAM", "JJA", "JJA", "JJA", "SON", "SON", "SON", "DJF"]


def test_v2_counts_within_season_and_v1_pools():
    days = [day("2020-01-01", y=53), day("2020-01-02", y=53), day("2020-07-01", y=45)]
    v1, v2 = b.fit_model("V1", days), b.fit_model("V2", days)
    assert v1.n_fit == {"ALL": 3}
    assert v2.n_fit == {"DJF": 2, "MAM": 0, "JJA": 1, "SON": 0}
    djf = v2.pmf_for(day("2021-12-10"))
    assert djf[23] == 2.5 / (2 + 20.5) and djf[15] == 0.5 / (2 + 20.5)
    assert v2.pmf_for(day("2021-04-10")) == tuple([1 / 41] * 41)  # empty season: uniform
    assert v1.pmf_for(day("2021-04-10"))[23] == 2.5 / (3 + 20.5)
    with pytest.raises(ValueError):
        b.fit_model("V3", days)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------
def test_r0_support_edges_nearest_end_and_month_counts():
    fit = [day("2020-01-01", y=50), day("2020-01-02", y=60), day("2020-02-01", y=55)]
    r0 = b.fit_r0(fit)
    assert (r0.lo, r0.hi, r0.size) == (40, 70, 31)  # support shared by every month
    jan = 2 + 0.5 * 31
    assert r0.prob(day("2024-01-09", y=50)) == 1.5 / jan
    assert r0.prob(day("2024-01-09", y=80)) == r0.pmfs[1][30] == 0.5 / jan  # above: scored at 70
    assert r0.prob(day("2024-01-09", y=10)) == r0.pmfs[1][0]  # below: scored at 40
    assert r0.prob(day("2024-02-09", y=55)) == 1.5 / (1 + 0.5 * 31)
    assert r0.prob(day("2024-07-09", y=55)) == 1 / 31  # month without fit days
    for month in range(1, 13):
        assert math.isclose(math.fsum(r0.pmfs[month]), 1.0, rel_tol=1e-12)


def test_r1_uses_raw_errors_erf_mass_and_floor():
    fit = [day(f=50, y=50), day(f=50, y=52), day(f=50, y=80)]  # raw k = 0, 2, 30 (not clamped)
    r1 = b.fit_r1(fit)
    assert r1.mu == 32 / 3
    assert r1.sigma == math.sqrt(((0 - 32 / 3) ** 2 + (2 - 32 / 3) ** 2 + (30 - 32 / 3) ** 2) / 3)
    g = b.Gaussian(mu=0.5, sigma=2.0)
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    assert math.isclose(g.prob(50, 51), phi((51.5 - 50.5) / 2) - phi((50.5 - 50.5) / 2), rel_tol=1e-12)
    assert b.Gaussian(mu=0.0, sigma=0.5).prob(50, 90) == 1e-9
    # Floored tail cells add ~1e-9 each, so the mass is 1 only up to the floor.
    total = math.fsum(g.prob(50, y) for y in range(-10, 111))
    assert 1.0 <= total <= 1.0 + 121 * 1e-9
    with pytest.raises(ValueError):
        b.fit_r1([day(f=50, y=52), day(f=40, y=42)])  # zero variance


# ---------------------------------------------------------------------------
# Selection and Stage A conditions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mean, lower, expected",
    [(0.0, 0.0, "V1"),  # tie -> V1
     (0.0, -0.1, "V1"),
     (0.05, -0.01, "V1"),  # mean > 0 but lower bound <= 0 -> V1
     (0.05, 0.0, "V1"),  # strict
     (0.05, 0.001, "V2"),
     (-0.05, 0.001, "V1")],
)
def test_selection_rule(mean, lower, expected):
    assert b.select_variant(mean, lower) == expected


def test_conditions_strict_and_inclusive_bounds():
    assert b.condition_1(0.01, 0.001) and not b.condition_1(0.01, 0.0) and not b.condition_1(0.0, 0.1)
    assert b.condition_2(0.75) and b.condition_2(0.85) and b.condition_2(0.8)
    assert not b.condition_2(0.7499) and not b.condition_2(0.8501)


def test_identical_variants_select_v1():
    # Every day in DJF with the same errors: V2's DJF pmf equals V1's, so d == 0 everywhere.
    train = [day(f"2017-01-{i:02d}", y=50 + (i % 3)) for i in range(1, 29)]
    validation = [day(f"2023-01-{i:02d}", y=50 + (i % 4), split="validation") for i in range(1, 29)]
    out = b.compute_validation(train, validation, dataset_sha="x")
    assert out["difference_v2_minus_v1"]["mean"] == 0.0 and out["selected_variant"] == "V1"


def test_clear_seasonal_bias_selects_v2():
    text = synthetic_csv(step=3, seasonal_bias=True)
    train, validation = b._days(text, ["train"]), b._days(text, ["validation"])
    out = b.compute_validation(train, validation, dataset_sha="x")
    assert out["difference_v2_minus_v1"]["ci_lower"] > 0 and out["selected_variant"] == "V2"


# ---------------------------------------------------------------------------
# PIT and Brier
# ---------------------------------------------------------------------------
def test_pit_components_hand_computed():
    pmf = b.error_pmf([day(y=50), day(y=51)])  # counts: k=0 -> 1, k=1 -> 1
    denominator = 2 + 20.5
    below, mass = b.pmf_pit_components(pmf, day(f=50, y=51))  # k_c = 1, index 21
    assert mass == 1.5 / denominator
    assert math.isclose(below, (20 * 0.5 + 1.5) / denominator, rel_tol=1e-15)
    below_low, mass_low = b.pmf_pit_components(pmf, day(f=50, y=0))  # clamped to -20
    assert below_low == 0.0 and mass_low == pmf[0]
    below_high, mass_high = b.pmf_pit_components(pmf, day(f=50, y=99))  # clamped to +20
    assert math.isclose(below_high + mass_high, 1.0, rel_tol=1e-12)
    pit = stats.randomized_pit([(below, mass)], seed=20260922)
    assert pit[0] == below + random.Random(20260922).random() * mass


def test_brier_formula_matches_definition():
    probs = [0.2, 0.5, 0.3]
    for observed in range(3):
        direct = sum((p - (i == observed)) ** 2 for i, p in enumerate(probs))
        assert math.isclose(b.brier(probs, observed), direct, rel_tol=1e-12)
    pmf = b.error_pmf([day(y=50)])
    assert b.pmf_brier(pmf, day(y=95)) == b.brier(pmf, 40)


# ---------------------------------------------------------------------------
# Data access and test-split guards
# ---------------------------------------------------------------------------
def test_load_split_refuses_test_and_returns_usable_rows_in_order(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text(
        "target_date,split,forecast_max_f,label_f,usable\n"
        "2017-01-02,train,40,41,true\n2017-01-01,train,40,42,true\n2017-01-03,train,40,43,false\n"
        "2025-01-01,test,1,2,true\n", encoding="utf-8")
    with pytest.raises(b.TestSplitRefused):
        b.load_split(path, "test")
    with pytest.raises(ValueError):
        b.load_split(path, "holdout")
    assert [(d.target_date, d.y) for d in b.load_split(path, "train")] == [("2017-01-01", 42), ("2017-01-02", 41)]


def test_validation_path_never_parses_test_rows(tmp_path, monkeypatch):
    path = tmp_path / "d.csv"
    path.write_text(synthetic_csv(step=11), encoding="utf-8")
    seen = []
    original = b._to_day

    def recording(row):
        seen.append(row["split"])
        return original(row)

    monkeypatch.setattr(b, "_to_day", recording)
    _script().validation_payload(path, expected_sha=None)
    assert seen and set(seen) == {"train", "validation"}


def test_open_test_once_guard(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text(synthetic_csv(step=17), encoding="utf-8")
    gate4 = tmp_path / "gate4"
    gate4.mkdir()
    with pytest.raises(b.TestSplitRefused):
        b.load_test_for_reproduction(path, gate4)  # no committed result yet
    days = b.open_test_once(path, gate4, opened_by={"code_commit": "abc"})
    assert days and {d.split for d in days} == {"test"}
    assert json.loads((gate4 / b.TEST_OPENED_FILE).read_text(encoding="utf-8"))["code_commit"] == "abc"
    with pytest.raises(b.TestSplitRefused):
        b.open_test_once(path, gate4, opened_by={})  # opened already
    (gate4 / b.TEST_OPENED_FILE).unlink()
    (gate4 / b.STAGE_A_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(b.TestSplitRefused):
        b.open_test_once(path, gate4, opened_by={})  # result exists
    assert b.load_test_for_reproduction(path, gate4) == days


def test_dataset_constant_matches_frozen_pin():
    frozen = json.loads((EXP / "preregistration.json").read_text(encoding="utf-8"))
    assert f"dataset.csv sha256={b.DATASET_SHA256}" in json.dumps(frozen["frozen_fields"])


# ---------------------------------------------------------------------------
# End-to-end on synthetic data (guards exercised, report rendered)
# ---------------------------------------------------------------------------
def test_synthetic_end_to_end_single_run(tmp_path):
    script = _script()
    path = tmp_path / "d.csv"
    path.write_text(synthetic_csv(step=4), encoding="utf-8")
    gate4 = tmp_path / "gate4"
    prov = {"code_commit": "0" * 40, "run_at_utc": "2026-01-01T00:00:00+00:00"}
    with pytest.raises(script.Refused):
        script.run_test(dataset=path, gate4=gate4, provenance=prov, expected_sha=None)  # no selection yet
    with pytest.raises(script.Refused):
        script.validation_payload(path)  # wrong dataset hash
    selection = script.run_validation(dataset=path, gate4=gate4, provenance=prov, expected_sha=None)
    assert selection["selected_variant"] in ("V1", "V2")
    with pytest.raises(script.Refused):
        script.run_validation(dataset=path, gate4=gate4, provenance=prov, expected_sha=None)
    result = script.run_test(dataset=path, gate4=gate4, provenance=prov, expected_sha=None)
    assert result["verdict"] in ("PASS", "FAIL")
    assert result["verdict"] == ("PASS" if result["condition_1_log_score_vs_r0"]["passed"]
                                 and result["condition_2_pit_coverage"]["passed"] else "FAIL")
    assert result["pit"]["n_inside"] + result["pit"]["n_below_low"] + result["pit"]["n_above_high"] == result["n_test_days"]
    assert result["mean_log_loss"]["model"] == -result["mean_log_score"]["model"]
    stored = json.loads((gate4 / b.STAGE_A_FILE).read_text(encoding="utf-8"))
    assert stored == result
    report = (gate4 / "REPORT.md").read_text(encoding="utf-8")
    assert f"Verdict: {result['verdict']}" in report and "Stage A pass or fail is about probabilities" in report
    with pytest.raises((script.Refused, b.TestSplitRefused)):
        script.run_test(dataset=path, gate4=gate4, provenance=prov, expected_sha=None)
    # Tampered selection is refused before the test split is opened.
    other = tmp_path / "gate4b"
    other.mkdir()
    tampered = dict(selection, selected_variant="V2" if selection["selected_variant"] == "V1" else "V1")
    (other / b.VALIDATION_FILE).write_text(b.to_json(tampered), encoding="utf-8")
    with pytest.raises(script.Refused):
        script.run_test(dataset=path, gate4=other, provenance=prov, expected_sha=None)
    assert not (other / b.TEST_OPENED_FILE).exists()


@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_report_renders_both_verdicts(tmp_path, verdict):
    script = _script()
    text = synthetic_csv(step=6)
    train, validation = b._days(text, ["train"]), b._days(text, ["validation"])
    selection = b.compute_validation(train, validation, dataset_sha="x")
    stage = b.compute_stage_a(sorted(train + validation, key=lambda d: d.target_date), b._days(text, ["test"]),
                              selected_variant="V1", dataset_sha="x")
    prov = {"code_commit": "c", "run_at_utc": "t"}
    stage = dict(stage, verdict=verdict, provenance=prov)
    report = script.render_report(dict(selection, provenance=prov), stage)
    assert f"**Stage A: {verdict}.**" in report
    assert ("EXP-002" in report) == (verdict == "FAIL")
    assert "not evidence of a" in report or verdict == "FAIL"


def test_stage_a_refuses_overlapping_or_wrong_windows():
    fit = [day("2017-01-01"), day("2023-01-01", split="validation")]
    with pytest.raises(ValueError):
        b.compute_stage_a(fit, [day("2022-06-01", split="test")], selected_variant="V1", dataset_sha="x")
    with pytest.raises(ValueError):
        b.compute_stage_a(fit, [day("2025-01-01", split="validation")], selected_variant="V1", dataset_sha="x")
