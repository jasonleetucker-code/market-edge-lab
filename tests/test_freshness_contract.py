"""The Freshness Fabric v1 types in edge_lab.freshness (ADR 0031): contract and fail-closed rules."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import freshness
from edge_lab.freshness import (
    AcquisitionMode,
    FabricContext,
    FabricProvider,
    Freshness,
    ScheduleState,
    SourceFreshness,
    SourceHealth,
    SourcePolicy,
    assess,
    combine,
    policy_freshness,
    require_fresh,
)

NOW = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)


def policy(**overrides):
    base = dict(source_id="demo.source", domain="demo", mode=AcquisitionMode.EXTERNAL_SCHEDULE,
                description="a demo", policy_version="v1", schedule_owner="systemd demo.timer",
                max_useful_age=timedelta(minutes=10))
    base.update(overrides)
    return SourcePolicy(**base)


def record(**overrides):
    base = dict(policy=policy(), as_of=NOW, freshness=Freshness.UNKNOWN, schedule_state=ScheduleState.UNKNOWN,
                health=SourceHealth.UNKNOWN, why_due="nothing known")
    base.update(overrides)
    return SourceFreshness(**base)


def test_existing_freshness_api_is_unchanged():
    assert [f.value for f in Freshness] == ["fresh", "stale", "unknown"]
    assert assess("2026-09-24T20:58:00Z", max_age=timedelta(minutes=5), now=NOW) is Freshness.FRESH
    assert combine(Freshness.FRESH, Freshness.UNKNOWN) is Freshness.UNKNOWN
    with pytest.raises(freshness.StaleDataError):
        require_fresh(Freshness.STALE, what="x")


def test_the_contract_vocabulary():
    assert [m.value for m in AcquisitionMode] == ["STREAM", "POLL", "EVENT_RELATIVE", "RELEASE_DRIVEN", "MANUAL",
                                                  "EXTERNAL_SCHEDULE"]
    assert {s.value for s in ScheduleState} == {"DUE", "NOT_DUE", "MISSED", "PAUSED", "BUDGET_BLOCKED",
                                                "QUOTA_BLOCKED", "PROTECTED_WINDOW", "LOCK_BUSY", "UNKNOWN"}
    import collections.abc
    import typing

    assert typing.get_origin(freshness.Provider) is collections.abc.Callable
    assert typing.get_args(freshness.Provider)[0] == [FabricContext, datetime]


@pytest.mark.parametrize("bad", [
    dict(source_id="Bad Id"), dict(source_id=""), dict(mode="POLL"), dict(domain=" "), dict(schedule_owner=""),
    dict(max_useful_age=timedelta(0)), dict(max_useful_age=5), dict(min_safe_cadence=timedelta(-1)),
    dict(min_safe_cadence=timedelta(hours=1), max_useful_cadence=timedelta(hours=2)),
    dict(protected_windows=["x"]), dict(underlying_mode="POLL"),
])
def test_policy_rejects_invalid_contracts(bad):
    with pytest.raises(ValueError):
        policy(**bad)


def test_policy_unknown_values_stay_none():
    p = policy(max_useful_age=None)
    d = p.to_dict()
    assert d["max_useful_age_s"] is None and d["min_safe_cadence_s"] is None and d["pacing"] is None
    assert policy_freshness(p, NOW, NOW) is Freshness.UNKNOWN  # no objective: never FRESH
    assert policy_freshness(policy(), None, NOW) is Freshness.UNKNOWN
    assert policy_freshness(policy(), NOW - timedelta(minutes=11), NOW) is Freshness.STALE
    assert policy_freshness(policy(), NOW - timedelta(minutes=10), NOW) is Freshness.FRESH


def test_fresh_needs_a_receipt_and_decision_use_needs_fresh_and_ok():
    with pytest.raises(ValueError):
        record(freshness=Freshness.FRESH)
    with pytest.raises(ValueError):
        record(usable_for_decision=True, freshness=Freshness.STALE, receipt_ts=NOW)
    with pytest.raises(ValueError):
        record(usable_for_decision=True, freshness=Freshness.FRESH, receipt_ts=NOW, health=SourceHealth.DEGRADED)
    ok = record(usable_for_decision=True, freshness=Freshness.FRESH, receipt_ts=NOW, health=SourceHealth.OK)
    assert ok.usable_for_decision


@pytest.mark.parametrize("bad", [
    dict(as_of=datetime(2026, 9, 24, 21)), dict(as_of=None), dict(next_due=datetime(2026, 9, 24)),
    dict(missed_count=-1), dict(missed_count=True), dict(missed_count=1.5), dict(recent_misses=["x"]),
    dict(freshness="fresh"), dict(schedule_state="DUE"), dict(health="OK"), dict(why_due=""),
    dict(policy="demo.source"),
])
def test_record_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        record(**bad)


def test_missing_is_not_zero_in_the_record_and_its_json():
    r = record()
    assert r.data_age is None and r.upstream_age is None and r.missed_count is None
    d = json.loads(json.dumps(r.to_dict()))
    for key in ("next_due_utc", "last_attempt_utc", "receipt_ts_utc", "data_age_s", "upstream_age_s", "missed_count"):
        assert d[key] is None, key
    assert d["freshness"] == "UNKNOWN" and d["schedule_state"] == "UNKNOWN" and d["usable_for_decision"] is False


def test_ages_derive_from_as_of_and_times_serialize_in_utc():
    other_zone = timezone(timedelta(hours=-4))
    r = record(receipt_ts=datetime(2026, 9, 24, 16, 30, tzinfo=other_zone), upstream_ts=NOW - timedelta(hours=1),
               freshness=Freshness.STALE, missed_count=0)
    assert r.data_age == timedelta(minutes=30) and r.upstream_age == timedelta(hours=1)
    d = r.to_dict()
    assert d["receipt_ts_utc"] == "2026-09-24T20:30:00Z" and d["data_age_s"] == 1800.0 and d["missed_count"] == 0


def test_context_defaults_the_odds_state_beside_the_ledger():
    assert FabricContext().odds_state_path is None
    ctx = FabricContext(odds_ledger=Path("/x/odds_quota_ledger.json"))
    assert ctx.odds_state_path == Path("/x/odds_quota_ledger.json.pilot.json")
    assert FabricContext(odds_ledger=Path("/x/l.json"), odds_pilot_state=Path("/y/s.json")).odds_state_path == Path("/y/s.json")


def test_provider_entry_validation():
    fn = lambda ctx, now: []  # noqa: E731
    FabricProvider("demo", (policy(),), fn)
    with pytest.raises(ValueError):
        FabricProvider("demo", (policy(), policy()), fn)  # duplicate source id
    with pytest.raises(ValueError):
        FabricProvider("demo", (), fn)
    with pytest.raises(ValueError):
        FabricProvider("Demo Provider", (policy(),), fn)
    with pytest.raises(ValueError):
        FabricProvider("demo", (policy(),), "not callable")
