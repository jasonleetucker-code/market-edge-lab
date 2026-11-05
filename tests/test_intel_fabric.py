"""The news intelligence Freshness Fabric provider (#192, ADR 0049; ADR 0031 contract C1): registered once,
pinned to its unit files, read-only and network-free, and honest about a lane that ships disabled."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import freshness_fabric as ff
from edge_lab import polymarket_sports
from edge_lab.freshness import AcquisitionMode, FabricContext, Freshness, ScheduleState, SourceHealth
from edge_lab.intel import fabric as intel_fabric
from edge_lab.intel.cli import write_heartbeat
from edge_lab.sources import get_source
from edge_lab.storage import SnapshotStore, mark_schema_v7_for_rollback

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "vps" / "systemd"
# 2026-11-05 is EST: the 13:32 ET tick is 18:32Z; the next is 20:32Z.
TICK = datetime(2026, 11, 5, 18, 32, tzinfo=UTC)


def z(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def unit_value(name: str, section: str, key: str) -> list[str]:
    values, current = [], None
    for line in (UNITS / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            current = line.strip("[]")
        elif current == section and line.startswith(f"{key}="):
            values.append(line.partition("=")[2])
    return values


def records(ctx: FabricContext, now: datetime) -> dict:
    return {r.source_id: r for r in intel_fabric.fabric_provider(ctx, now)}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "db" / "edge_lab.sqlite3"
    SnapshotStore(path)  # a current (v8) store with empty intel tables
    return path


def record_run(path: Path, started: datetime, *, ok=0, not_modified=0, failed=0, skipped=0,
               fetches: tuple[tuple[str, str], ...] = ()) -> None:
    """One collection run as `intel.service.collect_news` records it: fetch rows, then the run journal record."""
    store = SnapshotStore(path)
    run_id = f"intel-news-{started:%Y%m%dT%H%M%SZ}-test"
    store.start_run(run_id)
    for i, (feed, outcome) in enumerate(fetches):
        store.record_intel_fetch({"run_id": run_id, "source_id": "bbc", "feed_id": feed,
                                  "requested_url": f"https://example.invalid/{feed}",
                                  "attempted_at_utc": iso(started + timedelta(seconds=i)), "outcome": outcome,
                                  "retained": "NONE", "parser_version": "intel-feeds-v1"})
    store.finish_run(run_id, status="succeeded" if not failed else "partial")
    payload = {"run_id": run_id, "started_at_utc": iso(started), "feeds": ok + not_modified + failed + skipped,
               "ok": ok, "not_modified": not_modified, "failed": failed, "skipped": skipped, "new_items": 3 * ok,
               "gets": ok + not_modified + failed}
    store.append_intel_record(kind="run", subject_id="news", schema="market-edge-intel-record/1", payload=payload,
                              recorded_at_utc=iso(started))


# --------------------------------------------------------------------------- registry and policies


def test_registered_once_before_the_last_entry_with_two_external_schedule_sources():
    names = [p.name for p in ff.REGISTRY]
    assert names.count(intel_fabric.FABRIC_PROVIDER_NAME) == 1
    # dashboard/fixtures.py breaks REGISTRY[-1] for its "partial" fixture: the Polymarket entry stays last.
    assert ff.REGISTRY[-1].name == polymarket_sports.FABRIC_PROVIDER_NAME
    entry = next(p for p in ff.REGISTRY if p.name == intel_fabric.FABRIC_PROVIDER_NAME)
    assert [p.source_id for p in entry.policies] == ["news_feeds_public", "intel_inbox"]
    for p in entry.policies:
        assert p.mode is AcquisitionMode.EXTERNAL_SCHEDULE and p.underlying_mode is AcquisitionMode.POLL
        assert p.domain == "news"
        assert p.protected_windows and all("America/New_York" in w for w in p.protected_windows)
    news, inbox = entry.policies
    assert news.max_useful_age == get_source("news_feeds_public").max_age["feed"] == timedelta(hours=3)
    assert "edgelab-news.timer" in news.schedule_owner and "edgelab-news-inbox.timer" in inbox.schedule_owner
    assert news.min_safe_cadence == timedelta(hours=2) and news.max_useful_cadence == timedelta(minutes=15)


def test_the_fabrics_copy_of_each_schedule_is_pinned_to_the_unit_files():
    cal = unit_value("edgelab-news.timer", "Timer", "OnCalendar")
    m = re.fullmatch(r"\*-\*-\* (\d\d)/(\d):(\d\d):00 America/New_York", cal[0])
    assert len(cal) == 1 and m
    first, step, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert intel_fabric.NEWS_TICKS_ET == tuple(dtime(h, minute) for h in range(first, 24, step))
    assert intel_fabric.NEWS_INTERVAL == timedelta(hours=step)
    cal = unit_value("edgelab-news-inbox.timer", "Timer", "OnCalendar")
    m = re.fullmatch(r"\*-\*-\* \*:(\d\d)/(\d+):00 America/New_York", cal[0])
    assert len(cal) == 1 and m
    assert intel_fabric.INBOX_TICK_MINUTES == tuple(range(int(m.group(1)), 60, int(m.group(2))))
    assert intel_fabric.INBOX_INTERVAL == timedelta(minutes=int(m.group(2)))
    # Grace and objective cover each unit's TimeoutStartSec.
    for name, bound in (("edgelab-news.service", intel_fabric.NEWS_GRACE),
                        ("edgelab-news-inbox.service", intel_fabric.INBOX_MAX_AGE)):
        value = unit_value(name, "Service", "TimeoutStartSec")[0]
        assert value.endswith("min") and bound > timedelta(minutes=int(value[:-3]))
    from edge_lab.intel import service
    assert intel_fabric.NEWS_MIN_INTERVAL == service.NEWS_REFRESH_MIN_INTERVAL


# --------------------------------------------------------------------------- unknown, not activated


def test_unconfigured_inputs_are_unknown_never_guessed():
    out = records(FabricContext(), TICK)
    for r in out.values():
        assert r.freshness is Freshness.UNKNOWN and r.schedule_state is ScheduleState.UNKNOWN
        assert r.health is SourceHealth.UNKNOWN and not r.usable_for_research and not r.usable_for_decision
    assert "not configured" in out["news_feeds_public"].why_due
    assert "not configured" in out["intel_inbox"].why_due


def test_a_store_older_than_v8_is_unreadable_not_empty(db, tmp_path):
    mark_schema_v7_for_rollback(db)
    r = records(FabricContext(db=db, status_dir=tmp_path), TICK)["news_feeds_public"]
    assert r.schedule_state is ScheduleState.UNKNOWN and "unreadable" in r.why_due


def test_a_deployed_but_never_activated_lane_reads_paused_not_activated(db, tmp_path):
    out = records(FabricContext(db=db, status_dir=tmp_path), TICK + timedelta(hours=7))
    for sid, timer in (("news_feeds_public", "edgelab-news.timer"), ("intel_inbox", "edgelab-news-inbox.timer")):
        r = out[sid]
        assert r.schedule_state is ScheduleState.PAUSED and r.freshness is Freshness.UNKNOWN
        assert r.health is SourceHealth.UNKNOWN and r.missed_count is None
        assert r.why_due.startswith("not activated") and timer in r.why_due
        assert "NEWS_INTEL_ACTIVATION.md" in r.why_due and r.next_due is None
        assert intel_fabric.TIMER_NOT_OBSERVABLE in r.notes


# --------------------------------------------------------------------------- the news run


def test_a_run_for_the_latest_tick_is_not_due_fresh_and_research_only(db, tmp_path):
    record_run(db, TICK + timedelta(seconds=20), ok=2, not_modified=1, fetches=(("a", "OK"), ("b", "OK"), ("c", "NOT_MODIFIED")))
    r = records(FabricContext(db=db, status_dir=tmp_path), TICK + timedelta(minutes=30))["news_feeds_public"]
    assert r.schedule_state is ScheduleState.NOT_DUE and r.next_due == TICK + timedelta(hours=2)
    assert r.freshness is Freshness.FRESH and r.health is SourceHealth.OK
    assert r.receipt_ts == TICK + timedelta(seconds=22)  # the newest OK/NOT_MODIFIED fetch, a 304 included
    assert r.last_attempt == TICK + timedelta(seconds=20)
    assert r.usable_for_research and not r.usable_for_decision
    assert r.missed_count == 0 and r.details["missed_scope"] == ff.MISSED_SCOPE_TICK
    assert r.details["ok"] == 2 and r.details["not_modified"] == 1 and r.details["feeds_on_record"] == 3


def test_a_tick_still_running_is_due_then_missed_after_its_grace(db, tmp_path):
    record_run(db, TICK - timedelta(hours=2), ok=1, fetches=(("a", "OK"),))
    ctx = FabricContext(db=db, status_dir=tmp_path)
    running = records(ctx, TICK + timedelta(minutes=3))["news_feeds_public"]
    assert running.schedule_state is ScheduleState.DUE and running.freshness is Freshness.FRESH
    late = records(ctx, TICK + intel_fabric.NEWS_GRACE + timedelta(minutes=1))["news_feeds_public"]
    assert late.schedule_state is ScheduleState.MISSED and late.missed_count == 1
    assert any("disabled" in n for n in late.notes)  # a paused or never-enabled timer is named as a cause
    stale = records(ctx, TICK + timedelta(hours=1, minutes=5))["news_feeds_public"]
    assert stale.freshness is Freshness.STALE and stale.usable_for_research and not stale.usable_for_decision


@pytest.mark.parametrize("counts,fetches,health", [
    ({"ok": 1, "failed": 1}, (("a", "OK"), ("b", "FAILED")), SourceHealth.DEGRADED),
    ({"failed": 2}, (("a", "FAILED"), ("b", "REFUSED")), SourceHealth.FAILING),
])
def test_health_follows_the_last_runs_outcomes(db, tmp_path, counts, fetches, health):
    record_run(db, TICK + timedelta(seconds=5), fetches=fetches, **counts)
    r = records(FabricContext(db=db, status_dir=tmp_path), TICK + timedelta(minutes=10))["news_feeds_public"]
    assert r.health is health
    if health is SourceHealth.FAILING:  # nothing ever succeeded: no receipt, so no freshness to claim
        assert r.receipt_ts is None and r.freshness is Freshness.UNKNOWN and not r.usable_for_research


def test_a_run_that_skipped_every_feed_is_paused_for_verification(db, tmp_path):
    record_run(db, TICK + timedelta(seconds=5), skipped=4, fetches=(("a", "SKIPPED"), ("b", "SKIPPED")))
    r = records(FabricContext(db=db, status_dir=tmp_path), TICK + timedelta(minutes=10))["news_feeds_public"]
    assert r.schedule_state is ScheduleState.PAUSED and r.health is SourceHealth.UNKNOWN
    assert "verify-sources" in r.why_due and r.receipt_ts is None


# --------------------------------------------------------------------------- the inbox heartbeat


@pytest.mark.parametrize("processor", ["inbox", "run"])
def test_a_recent_heartbeat_is_a_fresh_drain(tmp_path, processor):
    at = TICK + timedelta(minutes=1)
    write_heartbeat(str(tmp_path), {"schema": "intel-heartbeat/1", "processor": processor, "at_utc": iso(at),
                                    "processed": 2})
    r = records(FabricContext(status_dir=tmp_path), at + timedelta(minutes=4))["intel_inbox"]
    assert r.schedule_state is ScheduleState.NOT_DUE and r.freshness is Freshness.FRESH
    assert r.health is SourceHealth.OK and r.receipt_ts == at and r.usable_for_research and not r.usable_for_decision
    assert r.next_due.minute in intel_fabric.INBOX_TICK_MINUTES and r.next_due > at + timedelta(minutes=4)
    assert r.details == {"heartbeat": "OK", "processor": processor, "processed": 2}


def test_an_old_heartbeat_is_missed_and_stale(tmp_path):
    at = TICK - timedelta(hours=1)
    write_heartbeat(str(tmp_path), {"schema": "intel-heartbeat/1", "processor": "run", "at_utc": iso(at)})
    r = records(FabricContext(status_dir=tmp_path), TICK)["intel_inbox"]
    assert r.schedule_state is ScheduleState.MISSED and r.freshness is Freshness.STALE
    assert r.details["processed"] is None


@pytest.mark.parametrize("content", ["{not json", json.dumps({"schema": "other/1", "processor": "inbox",
                                                               "at_utc": "2026-11-05T18:30:00Z"}),
                                     json.dumps({"schema": "intel-heartbeat/1", "processor": "inbox"}),
                                     json.dumps({"schema": "intel-heartbeat/1", "processor": "x",
                                                 "at_utc": "2026-11-05T18:30:00Z"}),
                                     json.dumps(["intel-heartbeat/1"])])
def test_an_unreadable_heartbeat_is_unknown(tmp_path, content):
    (tmp_path / "intel.json").write_text(content, encoding="utf-8")
    r = records(FabricContext(status_dir=tmp_path), TICK)["intel_inbox"]
    assert r.schedule_state is ScheduleState.UNKNOWN and r.health is SourceHealth.UNKNOWN
    assert r.freshness is Freshness.UNKNOWN


# --------------------------------------------------------------------------- read-only, network-free, in the artifact


def test_the_provider_reads_only_and_never_opens_a_socket(db, tmp_path, monkeypatch):
    record_run(db, TICK, ok=1, fetches=(("a", "OK"),))
    write_heartbeat(str(tmp_path), {"schema": "intel-heartbeat/1", "processor": "inbox", "at_utc": iso(TICK)})
    snapshot = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (*db.parent.iterdir(), *tmp_path.glob("*.json"))
                if p.is_file()}

    def no_network(*args, **kwargs):
        raise AssertionError("the fabric provider opened a socket")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    records(FabricContext(db=db, status_dir=tmp_path), TICK + timedelta(minutes=5))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (*db.parent.iterdir(), *tmp_path.glob("*.json"))
             if p.is_file() and p.name in snapshot}
    assert after == snapshot


def test_the_supervisor_artifact_carries_both_rows(db, tmp_path):
    ctx = FabricContext(db=db, status_dir=tmp_path)
    doc = ff.build_status(ctx, TICK)
    rows = {s["source_id"]: s for s in doc["sources"]}
    assert rows["news_feeds_public"]["schedule_state"] == "PAUSED"
    assert rows["intel_inbox"]["schedule_state"] == "PAUSED"
    assert "edgelab-news.timer" in rows["news_feeds_public"]["schedule_owner"]
    json.dumps(doc)  # JSON-safe
    assert {"provider": intel_fabric.FABRIC_PROVIDER_NAME, "state": "OK"} in doc["supervisor"]["providers"]
