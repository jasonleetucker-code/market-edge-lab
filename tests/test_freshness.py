from datetime import datetime, timedelta, timezone

from edge_lab.freshness import Freshness, assess, parse_utc

NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)


def test_parse_utc_accepts_z_and_offsets():
    assert parse_utc("2026-09-22T17:00:00Z") == datetime(2026, 9, 22, 17, tzinfo=timezone.utc)
    assert parse_utc("2026-09-22T13:00:00-04:00") == datetime(2026, 9, 22, 17, tzinfo=timezone.utc)


def test_assess_fresh_and_stale():
    assert assess("2026-09-22T17:58:00Z", max_age=timedelta(minutes=5), now=NOW) is Freshness.FRESH
    assert assess("2026-09-22T17:50:00Z", max_age=timedelta(minutes=5), now=NOW) is Freshness.STALE


def test_boundary_is_fresh():
    assert assess("2026-09-22T17:55:00Z", max_age=timedelta(minutes=5), now=NOW) is Freshness.FRESH


def test_non_string_timestamps_are_unparseable():
    assert parse_utc(1695400000) is None
    assert assess(1695400000, max_age=timedelta(days=1), now=NOW) is Freshness.UNKNOWN
