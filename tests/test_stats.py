"""The preregistered bootstrap and PIT procedures are deterministic and behave sanely."""

import pytest

from edge_lab.stats import block_bootstrap_mean_ci, central_coverage, randomized_pit


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    values = [((i * 37) % 11) - 5 + 0.3 for i in range(200)]
    a = block_bootstrap_mean_ci(values, resamples=2000)
    b = block_bootstrap_mean_ci(list(values), resamples=2000)
    assert a == b
    mean, lo, hi = a
    assert lo < mean < hi


def test_bootstrap_constant_series_has_zero_width():
    assert block_bootstrap_mean_ci([2.0] * 50, resamples=500) == (2.0, 2.0, 2.0)


def test_bootstrap_seed_changes_draws_and_rejects_empty():
    values = [((i * i * 7919) % 101) / 7 for i in range(60)]
    assert block_bootstrap_mean_ci(values, resamples=300, seed=1) != block_bootstrap_mean_ci(values, resamples=300, seed=2)
    with pytest.raises(ValueError):
        block_bootstrap_mean_ci([])


def test_randomized_pit_and_coverage():
    u = randomized_pit([(0.0, 0.2), (0.5, 0.1), (0.95, 0.05)])
    assert u == randomized_pit([(0.0, 0.2), (0.5, 0.1), (0.95, 0.05)])
    assert 0 <= u[0] <= 0.2 and 0.5 <= u[1] <= 0.6 and 0.95 <= u[2] <= 1.0
    assert central_coverage([0.05, 0.5, 0.95, 0.10]) == 0.5
