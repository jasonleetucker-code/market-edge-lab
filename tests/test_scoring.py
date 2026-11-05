"""`scoring.brier_score` and `scoring.calibration_bins` (ADR 0049)."""

from __future__ import annotations

import math

import pytest

from edge_lab.scoring import brier_score, calibration_bins


def test_brier_hand_computed():
    # (0.9-1)^2 + (0.2-0)^2 + (0.5-1)^2 = 0.01 + 0.04 + 0.25 = 0.30; mean 0.1
    assert brier_score([(0.9, 1), (0.2, 0), (0.5, 1)]) == pytest.approx(0.1)
    assert brier_score([(1.0, 1), (0.0, 0)]) == 0.0
    assert brier_score([(0.5, 0), (0.5, 1)]) == 0.25
    assert brier_score(iter([(0, 1)])) == 1.0  # generators and ints accepted


def test_empty_input_is_none_not_zero():
    assert brier_score([]) is None
    assert brier_score(iter(())) is None


@pytest.mark.parametrize("pair", [
    (1.1, 1), (-0.1, 0), (math.nan, 1), (math.inf, 0), ("0.5", 1), (None, 1), (True, 1),
    (0.5, 2), (0.5, -1), (0.5, 0.0), (0.5, None), (0.5, True), (0.5,), (0.5, 1, 0), 0.5,
])
def test_invalid_pairs_raise(pair):
    with pytest.raises(ValueError):
        brier_score([(0.5, 1), pair])
    with pytest.raises(ValueError):
        calibration_bins([pair])


def test_calibration_bins_shape_and_values():
    pairs = [(0.05, 0), (0.15, 0), (0.15, 1), (0.3, 1), (0.95, 1), (1.0, 1), (0.0, 0)]
    rows = calibration_bins(pairs, bins=10)
    assert len(rows) == 10
    assert [r["n"] for r in rows] == [2, 2, 0, 1, 0, 0, 0, 0, 0, 2]
    assert rows[0]["lower"] == 0.0 and rows[0]["upper"] == 0.1 and rows[9]["upper"] == 1.0
    assert rows[0]["mean_forecast"] == pytest.approx(0.025) and rows[0]["observed_rate"] == 0.0
    assert rows[1]["mean_forecast"] == pytest.approx(0.15) and rows[1]["observed_rate"] == 0.5
    assert rows[3]["mean_forecast"] == 0.3 and rows[3]["observed_rate"] == 1.0  # 0.3 is not lost below its bin
    assert rows[9]["mean_forecast"] == pytest.approx(0.975) and rows[9]["observed_rate"] == 1.0  # p = 1 in the last bin


def test_empty_bins_have_none_means_not_zero():
    rows = calibration_bins([(0.55, 1)], bins=4)
    assert [r["n"] for r in rows] == [0, 0, 1, 0]
    for i in (0, 1, 3):
        assert rows[i]["mean_forecast"] is None and rows[i]["observed_rate"] is None
    assert all(r["n"] == 0 and r["mean_forecast"] is None for r in calibration_bins([], bins=3))


@pytest.mark.parametrize("bins", [0, -1, 1.5, True, None])
def test_invalid_bin_count_raises(bins):
    with pytest.raises(ValueError):
        calibration_bins([(0.5, 1)], bins=bins)


def test_bin_edges_are_exact_for_decimal_like_inputs():
    for i in range(10):
        p = i / 10
        rows = calibration_bins([(p, 1)], bins=10)
        assert rows[i]["n"] == 1, p
