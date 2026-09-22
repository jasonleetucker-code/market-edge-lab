"""Stale or unknown data can never pass as current."""

from datetime import datetime, timedelta, timezone

import pytest

from edge_lab.freshness import Freshness, StaleDataError, assess, combine, require_fresh

NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
AGE = timedelta(minutes=5)


@pytest.mark.parametrize("ts", [None, "", "not-a-time", "2026-09-22T17:59:00"])  # last: naive
def test_missing_or_ambiguous_timestamp_is_unknown_not_fresh(ts):
    assert assess(ts, max_age=AGE, now=NOW) is Freshness.UNKNOWN


def test_future_timestamp_is_unknown():
    assert assess("2026-09-22T19:00:00Z", max_age=AGE, now=NOW) is Freshness.UNKNOWN


def test_combine_is_worst_of_and_empty_is_unknown():
    assert combine(Freshness.FRESH, Freshness.FRESH) is Freshness.FRESH
    assert combine(Freshness.FRESH, Freshness.STALE) is Freshness.STALE
    assert combine(Freshness.STALE, Freshness.UNKNOWN) is Freshness.UNKNOWN
    assert combine() is Freshness.UNKNOWN


@pytest.mark.parametrize("state", [Freshness.STALE, Freshness.UNKNOWN])
def test_require_fresh_fails_closed(state):
    with pytest.raises(StaleDataError):
        require_fresh(state, what="orderbook KXHIGHNY-X")


def test_require_fresh_passes_only_fresh():
    require_fresh(Freshness.FRESH, what="orderbook")


def test_every_active_source_declares_max_ages():
    from edge_lab.sources import REGISTRY, SourceStatus

    for spec in REGISTRY.values():
        if spec.status is SourceStatus.ACTIVE:
            assert spec.max_age, f"{spec.source_id} has no freshness contract"
