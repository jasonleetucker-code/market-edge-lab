"""Polymarket US NFL research pilot (ADR 0032): catalog, relationships, planning, captures, gate.

Every test is network-free: real gateway bytes captured on 2026-09-24 (tests/fixtures/polymarket_us,
recorded in experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md) are replayed through a
scripted opener."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import ScriptedOpener, http_error
from edge_lab import polymarket_sports as ps
from edge_lab import polymarket_us as pm
from edge_lab.discovery import CoverageState
from edge_lab.forward import exclusive_lock
from edge_lab.odds_schedule import ScheduledEvent
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FIX = Path(__file__).parent / "fixtures" / "polymarket_us"
EVENTS_P0 = FIX / "nfl_events_moneyline_p0_2026-09-24T205921Z.json"
EVENTS_P1 = FIX / "nfl_events_moneyline_p1_2026-09-24T205942Z.json"
BOOK_KC_MIA = FIX / "book_aec-nfl-kc-mia-2026-09-27_2026-09-24T205949Z.json"
BOOK_404 = FIX / "book_404_2026-09-24T210000Z.json"
NOW = datetime(2026, 9, 24, 21, 0, tzinfo=UTC)  # 17:00 ET, outside every protected window
KC_MIA = "aec-nfl-kc-mia-2026-09-27"
ALLOW = "test: access decision recorded"


def _events() -> list[dict]:
    return json.loads(EVENTS_P0.read_bytes())["events"]


def _catalog() -> list[ps.NflMarket]:
    markets, anomalies = ps.catalog_from_events(_events())
    assert anomalies == []
    return markets


def _market(slug: str = KC_MIA) -> ps.NflMarket:
    return next(m for m in _catalog() if m.market_slug == slug)


def _odds_event(eid: str, home: str, away: str, commence: str) -> dict:
    return {"id": eid, "sport_key": "americanfootball_nfl", "commence_time": commence, "home_team": home,
            "away_team": away}


ODDS_EVENTS = [
    _odds_event("e_kc_mia", "Miami Dolphins", "Kansas City Chiefs", "2026-09-27T17:00:00Z"),
    _odds_event("e_atl_gb", "Green Bay Packers", "Atlanta Falcons", "2026-09-25T00:15:00Z"),
    _odds_event("e_lac_sea", "Seattle Seahawks", "Los Angeles Chargers", "2026-10-04T20:25:00Z"),
]


def _scheduled(raw: list[dict]) -> list[ScheduledEvent]:
    from edge_lab import odds_api

    return list(odds_api.parse_events(raw, sport="americanfootball_nfl")[0])


def _store(tmp_path: Path, odds_events: list[dict] | None = ODDS_EVENTS, *, odds_at: datetime = NOW) -> Path:
    db = tmp_path / "edge.sqlite3"
    store = SnapshotStore(db)
    if odds_events is not None:
        store.start_run("odds-disc")
        store.save_snapshot(run_id="odds-disc", source="the_odds_api", kind="events", entity_id="americanfootball_nfl",
                            url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events",
                            payload={"events": odds_events, "request": {"tick_utc": odds_at.isoformat()}},
                            fetched_at_utc=odds_at.isoformat())
        store.finish_run("odds-disc", status="succeeded")
    return db


def _discovered(tmp_path: Path, **kw) -> Path:
    db = _store(tmp_path, **kw)
    opener = ScriptedOpener(EVENTS_P0.read_bytes(), EVENTS_P1.read_bytes())
    code, report = ps.run_discover(db, clock=lambda: NOW, sleep=lambda s: None, opener=opener, access_decision=ALLOW)
    assert code == 0 and report["state"] == "FILTER_COMPLETE", report
    return db


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


# --------------------------------------------------------------------------- catalog and rules


def test_catalog_from_the_real_filtered_listing():
    markets = _catalog()
    assert len(markets) == 33
    kc = _market()
    assert kc.pm_event_slug == "nfl-kc-mia-2026-09-27" and kc.game_start_utc == "2026-09-27T17:00:00Z"
    assert kc.teams == ("Kansas City Chiefs", "Miami Dolphins") and kc.long_team == "Kansas City Chiefs"
    # Sports rules: tie at $0.50 and last-fair-market-price postponement -> never plain binary.
    assert kc.payoff_kind == pm.PAYOFF_ALTERNATIVE_SETTLEMENT
    assert kc.clauses["overtime"] == "INCLUDED" and kc.clauses["tie_settlement"] == "0.50"
    assert kc.clauses["last_fair_market_price"] is True and kc.clauses["postponement_window"] in ("two days", "two weeks")


def test_filter_violations_are_dropped_and_reported():
    events = _events()[:2]
    events[0] = {**events[0], "tags": []}
    spread = {**events[1]["markets"][0], "slug": "asc-x", "sportsMarketType": "football_team_full_game_spread"}
    events[1] = {**events[1], "markets": [events[1]["markets"][0], spread, events[1]["markets"][0]]}
    markets, anomalies = ps.catalog_from_events(events)
    assert [m.market_slug for m in markets] == [events[1]["markets"][0]["slug"]]
    assert any("filter not honoured" in a and "nfl" in a for a in anomalies)
    assert any("asc-x" in a for a in anomalies) and any("listed twice" in a for a in anomalies)


def test_rules_clauses_are_matched_literally_and_unknown_stays_unknown():
    assert ps.rules_clauses(None) == {"overtime": "UNSTATED", "tie_settlement": None, "postponement_window": None,
                                      "last_fair_market_price": False, "outcome_source": None,
                                      "participant_start_condition": False}
    c = ps.rules_clauses("Regulation time only. Outcome sourced from NFL.")
    assert c["overtime"] == "EXCLUDED" and c["outcome_source"] == "NFL"


# --------------------------------------------------------------------------- relationships


def test_same_teams_and_kickoff_is_related_never_equivalent():
    rel = ps.relate(_market(), _scheduled(ODDS_EVENTS))
    assert rel.status == ps.RELATED and rel.odds_event_id == "e_kc_mia" and rel.odds_market_key == "h2h"
    assert rel.equivalent is False and "EQUIVALENT" not in ps.RELATIONSHIP_STATES
    assert set(rel.flags) == {"RULES_UNRESOLVED", "PAYOFF_UNSUPPORTED"}
    for dim in ("teams", "date", "start_time", "league"):
        assert rel.checks[dim]["state"] == "MATCH", dim
    for dim in ("regulation_vs_overtime", "ties", "postponement_cancellation_no_contest", "participant_start",
                "settlement_provider"):
        assert rel.checks[dim]["state"] == "UNVERIFIED", dim
    assert rel.checks["payout_structure"]["state"] == "DIFFERS"
    assert rel.checks["alternative_settlement"]["state"] == "DIFFERS"
    assert rel.checks["home_away"]["state"] == "UNVERIFIED"


@pytest.mark.parametrize("odds, status, why", [
    ([], ps.UNMATCHED, "no Odds API NFL event"),
    ([_odds_event("x", "Miami Dolphins", "Kansas City Chiefs", "2026-10-11T17:00:00Z")], ps.UNMATCHED, "36 h"),
    ([_odds_event("x", "Miami Dolphins", "Buffalo Bills", "2026-09-27T17:00:00Z")], ps.AMBIGUOUS, "exactly one team"),
    ([_odds_event("x", "Miami Dolphins", "Kansas City Chiefs", "2026-09-27T20:25:00Z")], ps.AMBIGUOUS, "differ by"),
    ([_odds_event("x", "Miami Dolphins", "Kansas City Chiefs", "2026-09-27T17:00:00Z"),
      _odds_event("y", "Kansas City Chiefs", "Miami Dolphins", "2026-09-28T17:00:00Z")], ps.AMBIGUOUS, "2 Odds API events"),
])
def test_unmatched_and_ambiguous_fail_closed(odds, status, why):
    rel = ps.relate(_market(), _scheduled(odds))
    assert rel.status == status and why in " ".join(rel.reasons)
    assert rel.odds_event_id is None and rel.equivalent is False


def test_missing_start_or_team_names_is_ambiguous():
    m = _market()
    no_start = ps.NflMarket.from_dict({**m.to_dict(), "game_start_utc": None})
    assert ps.relate(no_start, _scheduled(ODDS_EVENTS)).status == ps.AMBIGUOUS
    one_team = ps.NflMarket.from_dict({**m.to_dict(), "teams": ["Kansas City Chiefs"]})
    assert ps.relate(one_team, _scheduled(ODDS_EVENTS)).status == ps.AMBIGUOUS


# --------------------------------------------------------------------------- listing completeness


def _page(n: int) -> dict:
    return {"events": [{"id": str(i), "slug": f"e{i}"} for i in range(n)]}


def test_filtered_listing_read_to_an_empty_page_is_still_only_partial():
    opener = ScriptedOpener(_page(2), _page(0))
    rows, cov = pm.read_events_listing(extra=ps.DISCOVERY_FILTER, limit=2, get=_getter(opener))
    assert len(rows) == 2 and cov.state is CoverageState.PARTIAL and "FILTERED" in cov.detail and cov.pages_ok == 2
    assert "tagSlug=nfl" in opener.calls[0] and opener.calls[1].split("?")[1].startswith("limit=2&offset=2")


def _getter(opener):
    from edge_lab import http

    return lambda url: http.fetch_json_result(url, opener=opener, retries=0, sleep=lambda s: None)


def test_listing_failure_partial_page_cap_and_malformed():
    rows, cov = pm.read_events_listing(extra=(), limit=2, get=_getter(ScriptedOpener(_page(2), http_error(503))))
    assert cov.state is CoverageState.PARTIAL and "failed" in cov.detail and len(rows) == 2
    rows, cov = pm.read_events_listing(extra=(), limit=2, get=_getter(ScriptedOpener(http_error(500))))
    assert cov.state is CoverageState.FAILED and rows == []
    rows, cov = pm.read_events_listing(extra=(), limit=2, max_pages=1, get=_getter(ScriptedOpener(_page(2))))
    assert cov.state is CoverageState.PARTIAL and "cap" in cov.detail
    rows, cov = pm.read_events_listing(extra=(), limit=2, get=_getter(ScriptedOpener({"nope": 1})))
    assert cov.state is CoverageState.FAILED and "malformed" in cov.detail
    # Unfiltered and read to an empty page: the only COMPLETE.
    rows, cov = pm.read_events_listing(extra=(), limit=2, get=_getter(ScriptedOpener(_page(1), _page(0))))
    assert cov.state is CoverageState.COMPLETE


# --------------------------------------------------------------------------- the access gate and refusals


def test_the_owner_risk_decision_is_the_gate_and_is_read_at_call_time(tmp_path, monkeypatch):
    # The Terms did not clear collection; the owner's recorded risk decision (not a Polymarket grant) is the gate.
    assert ps.OWNER_ACCESS_DECISION == "OWNER_RISK_DECISION_2026-09-24"
    assert ps.access_decision_now() == ps.OWNER_ACCESS_DECISION and ps.access_decision_now(None) is None
    db = _store(tmp_path)
    opener = ScriptedOpener(EVENTS_P0.read_bytes(), EVENTS_P1.read_bytes())
    code, report = ps.run_discover(db, clock=lambda: NOW, sleep=lambda s: None, opener=opener)  # the default gate
    assert code == 0 and report["state"] == "FILTER_COMPLETE" and report["access_decision"] == ps.OWNER_ACCESS_DECISION
    status = ps.terminal_view(db, now=NOW)
    assert status["access"] == ps.ACCESS_ALLOWED == "ALLOWED_BY_OWNER_RISK_DECISION"
    # Set to None after import: every networked run is blocked again, with no redeploy of callers.
    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)
    blocked = ScriptedOpener()
    for run in (ps.run_discover, ps.run_capture):
        code, report = run(db, clock=lambda: NOW + timedelta(hours=7), sleep=lambda s: None, opener=blocked)
        assert code == 0 and report["state"] == "BLOCKED_TERMS_REVIEW" and report["requests"] == 0
    assert blocked.calls == [] and len(SnapshotStore(db).pm_sports_scans()) == 1
    assert ps.terminal_view(db, now=NOW)["state"] == "BLOCKED_TERMS_REVIEW"


def test_the_terms_gate_blocks_every_networked_run_before_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)
    db = _store(tmp_path)
    opener = ScriptedOpener()  # any call would fail: pop from an empty list
    for run in (ps.run_discover, ps.run_capture):
        code, report = run(db, clock=lambda: NOW, sleep=lambda s: None, opener=opener)
        assert code == 0 and report["state"] == "BLOCKED_TERMS_REVIEW" and report["requests"] == 0
    assert opener.calls == [] and SnapshotStore(db).pm_sports_scans() == []


@pytest.mark.parametrize("et", ["11:12", "16:15", "17:40", "18:49"])
def test_protected_windows_refuse_before_the_lock(tmp_path, et):
    db = _store(tmp_path)
    h, m = map(int, et.split(":"))
    at = datetime(2026, 9, 24, h + 4, m, tzinfo=UTC)  # EDT
    for run in (ps.run_discover, ps.run_capture):
        code, report = run(db, clock=lambda: at, opener=ScriptedOpener(), access_decision=ALLOW)
        assert code == 0 and report["state"] == "DEFERRED_PROTECTED_WINDOW"


def test_lock_busy_and_missing_store_do_nothing(tmp_path):
    db = _store(tmp_path)
    with exclusive_lock(db.with_name(db.name + ".pm-sports.lock"), timeout_s=1):
        code, report = ps.run_capture(db, clock=lambda: NOW, opener=ScriptedOpener(), access_decision=ALLOW)
    assert code == 0 and report["state"] == "LOCK_BUSY"
    code, report = ps.run_discover(tmp_path / "nope.sqlite3", clock=lambda: NOW, access_decision=ALLOW)
    assert code == 0 and report["state"] == "NO_STORE" and not (tmp_path / "nope.sqlite3").exists()


def test_the_pilot_lock_is_not_the_kalshi_collector_lock():
    db = Path("x/edge.sqlite3")
    assert ps._lock_path(db).name == "edge.sqlite3.pm-sports.lock"
    from edge_lab import price_observations

    assert ps._lock_path(db) != price_observations._lock_path(db)


# --------------------------------------------------------------------------- discovery


def test_discovery_stores_pages_scan_and_plans_related_targets(tmp_path):
    db = _discovered(tmp_path)
    store = SnapshotStore(db)
    scan = store.pm_sports_scans()[0]
    assert scan["coverage_state"] == "PARTIAL" and scan["filter_complete"] == 1  # filtered: never COMPLETE
    assert scan["pages_ok"] == 2 and scan["markets"] == 33 and scan["requests"] == 2
    assert len(json.loads(scan["page_snapshot_ids_json"])) == 2
    targets = store.pm_sports_targets()
    by_market = {}
    for t in targets:
        by_market.setdefault(t["market_slug"], []).append(t)
    # Only markets related to a stored Odds API event get targets.
    assert set(by_market) == {KC_MIA, "aec-nfl-atl-gb-2026-09-24", "aec-nfl-lac-sea-2026-10-04"}
    kc = {t["offset_label"]: t for t in by_market[KC_MIA]}
    assert kc["T-60m"]["target_utc"] == "2026-09-27T16:00:00+00:00"
    assert kc["T-6h"]["target_utc"] == "2026-09-27T11:00:00+00:00"
    assert kc["T-24h"]["target_utc"] == "2026-09-26T17:00:00+00:00"
    assert all(t["relationship"] == ps.RELATED and t["odds_event_id"] == "e_kc_mia" for t in kc.values())
    assert kc["T-60m"]["due_from_utc"] == "2026-09-27T15:53:00+00:00"
    assert kc["T-60m"]["deadline_utc"] == "2026-09-27T16:30:00+00:00"
    # ATL-GB kicks off at 00:15Z: T-24h and T-6h deadlines already passed at planning -> not planned.
    assert [t["offset_label"] for t in by_market["aec-nfl-atl-gb-2026-09-24"]] == ["T-60m"]
    # LAC-SEA T-24h (16:25 ET Saturday) falls in the 16:13-16:30 ET settlement window: moved to its end.
    lac = {t["offset_label"]: t for t in by_market["aec-nfl-lac-sea-2026-10-04"]}
    assert lac["T-24h"]["target_utc"] == "2026-10-03T20:25:00+00:00"
    assert lac["T-24h"]["effective_utc"] == "2026-10-03T20:30:00+00:00"
    assert json.loads(lac["T-24h"]["detail_json"])["shifted_out_of_protected_window"] == "settlement_run_1615"
    health = {r["source_id"]: r for r in store.latest_source_health()}
    assert health["polymarket_us_nfl_discovery"]["status"] == "ok"


def test_discovery_cadence_and_idempotent_planning(tmp_path):
    db = _discovered(tmp_path)
    n = len(SnapshotStore(db).pm_sports_targets())
    code, report = ps.run_discover(db, clock=lambda: NOW + timedelta(hours=3), opener=ScriptedOpener(),
                                   access_decision=ALLOW)
    assert code == 0 and report["state"] == "NOT_DUE"
    later = NOW + timedelta(hours=6)
    code, report = ps.run_discover(db, clock=lambda: later, sleep=lambda s: None,
                                   opener=ScriptedOpener(EVENTS_P0.read_bytes(), EVENTS_P1.read_bytes()),
                                   access_decision=ALLOW)
    assert code == 0 and report["state"] == "FILTER_COMPLETE"
    assert len(SnapshotStore(db).pm_sports_targets()) == n  # nothing planned twice


def test_partial_catalog_is_recorded_and_plans_only_what_was_seen(tmp_path):
    db = _store(tmp_path)
    opener = ScriptedOpener(EVENTS_P0.read_bytes(), http_error(503), http_error(503))
    code, report = ps.run_discover(db, clock=lambda: NOW, sleep=lambda s: None, opener=opener, access_decision=ALLOW)
    assert code == 0 and report["state"] == "PARTIAL" and report["filter_complete"] is False
    store = SnapshotStore(db)
    scan = store.pm_sports_scans()[0]
    assert scan["coverage_state"] == "PARTIAL" and scan["filter_complete"] == 0 and scan["requests"] == 3
    assert ps.catalog_state(store, now=NOW)["state"] == "PARTIAL_CATALOG"
    disc, _ = ps.freshness_records(store, now=NOW, access_decision=ALLOW)
    # A partial scan plans what it read, but it is an attempt, never a receipt.
    assert disc["receipt_utc"] is None and disc["freshness"] == "unknown" and disc["health"] == "DEGRADED"
    assert disc["planning_scan_utc"] is not None and disc["last_attempt_utc"] is not None
    assert store.latest_source_health()[0]["status"] == "partial"
    assert store.pm_sports_targets()  # the markets that were read are still usable


def test_a_failed_first_discovery_alerts_once_then_waits(tmp_path):
    db = _store(tmp_path)
    code, report = ps.run_discover(db, clock=lambda: NOW, sleep=lambda s: None,
                                   opener=ScriptedOpener(http_error(500), http_error(500)), access_decision=ALLOW)
    assert code == 1 and report["state"] == "FAILED" and report["catalog_stale"] is True
    store = SnapshotStore(db)
    assert store.pm_sports_scans()[0]["coverage_state"] == "FAILED" and store.pm_sports_targets() == []
    assert ps.catalog_state(store, now=NOW)["state"] == "FAILED"
    later = NOW + timedelta(hours=6)
    code, report = ps.run_discover(db, clock=lambda: later, sleep=lambda s: None,
                                   opener=ScriptedOpener(http_error(500), http_error(500)), access_decision=ALLOW)
    assert code == 0 and report["state"] == "FAILED"  # the same failure: no second alert


def test_a_failure_that_makes_a_good_catalog_stale_alerts(tmp_path):
    db = _discovered(tmp_path)
    at = NOW + timedelta(hours=27)  # 20:00 ET, outside the protected windows
    code, report = ps.run_discover(db, clock=lambda: at, sleep=lambda s: None,
                                   opener=ScriptedOpener(http_error(500), http_error(500)), access_decision=ALLOW)
    assert code == 1 and report["catalog_stale"] is True
    at2 = NOW + timedelta(hours=7)
    db2 = _discovered(tmp_path / "b")
    code, report = ps.run_discover(db2, clock=lambda: at2, sleep=lambda s: None,
                                   opener=ScriptedOpener(http_error(500), http_error(500)), access_decision=ALLOW)
    assert code == 0 and report["catalog_stale"] is False  # still fresh enough: retried in 6 h, no alert


def test_the_stale_transition_alerts_once_even_after_earlier_failures(tmp_path):
    db = _discovered(tmp_path)
    fail = ScriptedOpener
    runs = []
    for hours in (20, 26, 32):  # 13:00, 19:00 and 01:00 ET: outside the protected windows
        at = NOW + timedelta(hours=hours)
        code, report = ps.run_discover(db, clock=lambda: at, sleep=lambda s: None,
                                       opener=fail(http_error(500), http_error(500)), access_decision=ALLOW)
        runs.append((code, report["state"], report["catalog_stale"]))
    # Still fresh at 20 h (no alert); stale from 26 h: one alert on the transition, then silence.
    assert runs == [(0, "FAILED", False), (1, "FAILED", True), (0, "FAILED", True)]


def test_a_corrupt_store_is_an_error_view_not_an_exception(tmp_path):
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"not a database at all" * 100)
    assert ps.terminal_view(bad, now=NOW)["state"] in ("ERROR", "NO_STORE")


def test_no_odds_schedule_means_no_targets(tmp_path):
    db = _discovered(tmp_path, odds_events=None)
    assert SnapshotStore(db).pm_sports_targets() == []
    db2 = _discovered(tmp_path / "stale", odds_at=NOW - timedelta(hours=30))
    assert SnapshotStore(db2).pm_sports_targets() == []


def test_slot_cap_skips_visibly(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MAX_MARKETS_PER_SLOT", 1)
    odds = [_odds_event(f"e{i}", h, a, c) for i, (h, a, c) in enumerate([
        ("Miami Dolphins", "Kansas City Chiefs", "2026-09-27T17:00:00Z"),
        ("Cleveland Browns", "Carolina Panthers", "2026-09-27T17:00:00Z")])]
    db = _discovered(tmp_path, odds_events=odds)
    store = SnapshotStore(db)
    states = [(t["offset_label"], t["state"]) for t in store.pm_sports_targets()]
    assert sorted(s for _, s in states if s) == ["SKIPPED_CAP"] * 3  # one of the two markets per slot
    skipped = [t for t in store.pm_sports_targets() if t["state"] == "SKIPPED_CAP"]
    assert all("SLOT_CAP" in t["state_reason"] for t in skipped)


# --------------------------------------------------------------------------- captures


def _due_clock_for_kc() -> datetime:
    return datetime(2026, 9, 27, 15, 55, tzinfo=UTC)  # 11:55 ET: the KC-MIA T-60m target is due


def _fresh_catalog_at(db: Path, at: datetime) -> None:
    """Re-run discovery at `at` so the catalog is not stale (captures refuse a stale one)."""
    code, report = ps.run_discover(db, clock=lambda: at, sleep=lambda s: None,
                                   opener=ScriptedOpener(EVENTS_P0.read_bytes(), EVENTS_P1.read_bytes()),
                                   access_decision=ALLOW, force=True)
    assert report["state"] == "FILTER_COMPLETE"


def test_capture_records_a_research_book_from_real_bytes(tmp_path):
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = _due_clock_for_kc()
    _fresh_catalog_at(db, at - timedelta(hours=2))
    opener = ScriptedOpener(BOOK_KC_MIA.read_bytes())
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None, opener=opener, access_decision=ALLOW)
    assert code == 0 and report["state"] == "CAPTURED" and report["by_status"] == {"CAPTURED": 1}
    assert opener.calls == [f"GET https://gateway.polymarket.us/v1/markets/{KC_MIA}/book"]
    store = SnapshotStore(db)
    t = next(t for t in store.pm_sports_targets() if t["market_slug"] == KC_MIA and t["offset_label"] == "T-60m")
    row = store.pm_sports_observations(target_id=t["target_id"])[-1]
    assert row["status"] == "CAPTURED" and row["yes_bid"] == "0.8500" and row["yes_ask"] == "0.8550"
    assert row["yes_ask_size"] == "632877.8400" and row["yes_bid_size"] == "434910.6900"
    assert row["book_state"] == "MARKET_STATE_OPEN" and row["source_timestamp_utc"].startswith("2026-09-24T20:59:13")
    assert row["snapshot_id"] and json.loads(row["depth_json"])["truncated"] is True
    with sqlite3.connect(db) as conn:
        kind, source_id = conn.execute("SELECT kind, source_id FROM snapshots WHERE id = ?",
                                       (row["snapshot_id"],)).fetchone()
    assert kind == "book" and source_id == "polymarket_us_public"
    # Idempotent: a second tick finds the target final and sends nothing.
    code, report = ps.run_capture(db, clock=lambda: at + timedelta(minutes=15), opener=ScriptedOpener(),
                                  access_decision=ALLOW)
    assert code == 0 and report["attempted"] == 0


def test_the_1610_tick_captures_a_1605_target_although_the_timer_fires_late(tmp_path, monkeypatch):
    """Regression (ARI-SF and MIN-TB on 2026-09-26, MIA-MIN on 2026-10-03, all MISSED): the T-24h target
    of a 16:05 ET Sunday kickoff is due 15:58-16:35 ET Saturday, and 16:10 is its only tick clear of the
    16:13 settlement window. The timer fires seconds late, a full MAX_RUN from then overlapped the
    window, and the tick was refused. Now it runs, with its deadline cut to end before the window."""
    slug = "aec-nfl-ari-sf-2026-09-27"
    at = datetime(2026, 9, 26, 20, 10, 7, tzinfo=UTC)  # the 16:10 EDT tick, 7 s late
    odds = [_odds_event("e_ari_sf", "San Francisco 49ers", "Arizona Cardinals", "2026-09-27T20:05:00Z")]
    db = _discovered(tmp_path, odds_events=odds, odds_at=at - timedelta(hours=1))
    _fresh_catalog_at(db, at - timedelta(hours=2))
    t = next(t for t in SnapshotStore(db).pm_sports_targets()
             if t["market_slug"] == slug and t["offset_label"] == "T-24h")
    assert t["effective_utc"] == "2026-09-26T20:05:00+00:00" and t["deadline_utc"] == "2026-09-26T20:35:00+00:00"
    deadlines = []
    real = ps._Requests

    def recording(limit, deadline, *a, **kw):
        deadlines.append(deadline)
        return real(limit, deadline, *a, **kw)

    monkeypatch.setattr(ps, "_Requests", recording)
    book = BOOK_KC_MIA.read_bytes().replace(KC_MIA.encode(), slug.encode())
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None, opener=ScriptedOpener(book),
                                  access_decision=ALLOW)
    assert code == 0 and report["by_status"] == {"CAPTURED": 1}, report
    assert deadlines == [datetime(2026, 9, 26, 20, 12, 30, tzinfo=UTC)]  # 30 s before the 16:13 window


def test_404_is_final_not_executable_and_503_retries_once(tmp_path):
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = _due_clock_for_kc()
    _fresh_catalog_at(db, at - timedelta(hours=2))
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None,
                                  opener=ScriptedOpener(http_error(404)), access_decision=ALLOW)
    assert code == 0 and report["by_status"] == {"NOT_EXECUTABLE": 1}
    store = SnapshotStore(db)
    assert any("BOOK_NOT_FOUND" in (t["state_reason"] or "") for t in store.pm_sports_targets())


def test_a_retryable_failure_exits_zero_and_is_retried_next_tick(tmp_path):
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = _due_clock_for_kc()
    _fresh_catalog_at(db, at - timedelta(hours=2))
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None,
                                  opener=ScriptedOpener(http_error(503), http_error(503)), access_decision=ALLOW)
    assert code == 0 and report["state"] == "PARTIAL_RETRYING" and report["requests"] == 2  # one retry only
    assert report["failed_retrying"] and not report["failed_final"]
    code, report = ps.run_capture(db, clock=lambda: at + timedelta(minutes=15), sleep=lambda s: None,
                                  opener=ScriptedOpener(BOOK_KC_MIA.read_bytes()), access_decision=ALLOW)
    assert code == 0 and report["by_status"] == {"CAPTURED": 1}


def test_a_failure_no_later_tick_can_retry_exits_one(tmp_path):
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = datetime(2026, 9, 27, 16, 20, tzinfo=UTC)  # 10 min before the T-60m deadline
    _fresh_catalog_at(db, at - timedelta(hours=2))
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None,
                                  opener=ScriptedOpener(http_error(503), http_error(503)), access_decision=ALLOW)
    assert code == 1 and report["state"] == "PARTIAL" and report["failed_final"]


def test_budget_exhaustion_defers_without_failing(tmp_path):
    odds = [_odds_event(f"e{i}", h, a, "2026-09-27T17:00:00Z") for i, (h, a) in enumerate([
        ("Miami Dolphins", "Kansas City Chiefs"), ("Cleveland Browns", "Carolina Panthers"),
        ("New York Giants", "Tennessee Titans")])]
    db = _discovered(tmp_path, odds_events=odds, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = _due_clock_for_kc()
    _fresh_catalog_at(db, at - timedelta(hours=2))
    book = BOOK_KC_MIA.read_bytes()
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None, max_requests=2,
                                  opener=ScriptedOpener(book, book), access_decision=ALLOW)
    # Two books fit the 2-request budget; the third is deferred, not failed (the other markets' book
    # payload names KC-MIA, so it is recorded as an anomaly, NOT_EXECUTABLE).
    assert code == 0 and report["attempted"] == 2 and len(report["deferred"]) == 1 and report["requests"] == 2
    assert "FAILED" not in report["by_status"]
    with pytest.raises(ValueError):
        ps.run_capture(db, clock=lambda: at, max_requests=51, access_decision=ALLOW)


def test_book_for_another_market_is_not_executable(tmp_path):
    odds = [_odds_event("e0", "Cleveland Browns", "Carolina Panthers", "2026-09-27T17:00:00Z")]
    db = _discovered(tmp_path, odds_events=odds, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = _due_clock_for_kc()
    _fresh_catalog_at(db, at - timedelta(hours=2))
    code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None,
                                  opener=ScriptedOpener(BOOK_KC_MIA.read_bytes()), access_decision=ALLOW)
    assert report["by_status"] == {"NOT_EXECUTABLE": 1}
    row = SnapshotStore(db).pm_sports_observations()[-1]
    assert "BOOK_ANOMALY" in row["reason"] and row["yes_bid"] is None and row["snapshot_id"]


def test_missed_targets_are_recorded_never_fetched_late(tmp_path):
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = datetime(2026, 9, 27, 16, 40, tzinfo=UTC)  # past the T-60m deadline (16:30Z)
    _fresh_catalog_at(db, at - timedelta(hours=2))
    opener = ScriptedOpener()
    code, report = ps.run_capture(db, clock=lambda: at, opener=opener, access_decision=ALLOW)
    assert code == 0 and opener.calls == []
    missed = {m["target_id"]: m["reason"] for m in report["missed"]}
    kc = [tid for tid in missed if KC_MIA in tid]
    assert kc and all("NOT_CAPTURED_BY_DEADLINE" in missed[t] for t in kc)
    store = SnapshotStore(db)
    with pytest.raises(sqlite3.IntegrityError):  # final is final: no late capture can follow
        store.record_pm_sports_observation({**ps._row(ps._LazyRun(store, "x"), {"target_id": kc[0]}, "CAPTURED", at),
                                            "snapshot_id": 1, "received_at_utc": at.isoformat()})


def test_a_stale_catalog_pauses_captures_and_says_so_in_the_miss(tmp_path):
    db = _discovered(tmp_path)  # catalog from NOW; the KC-MIA T-60m target is 2.8 days later
    at = _due_clock_for_kc()
    opener = ScriptedOpener()
    code, report = ps.run_capture(db, clock=lambda: at, opener=opener, access_decision=ALLOW)
    assert code == 0 and report["state"] == "CATALOG_STALE" and report["deferred"] and opener.calls == []
    code, report = ps.run_capture(db, clock=lambda: at + timedelta(hours=1), opener=opener, access_decision=ALLOW)
    assert any("captures paused" in m["reason"] for m in report["missed"])


def test_a_moved_kickoff_supersedes_open_targets(tmp_path):
    db = _discovered(tmp_path)
    moved = _events()
    for e in moved:
        if e["slug"] == "nfl-kc-mia-2026-09-27":
            e["markets"][0]["gameStartTime"] = "2026-09-27T20:25:00Z"
    body = json.dumps({"events": moved}).encode()
    later = NOW + timedelta(hours=6)
    ps.run_discover(db, clock=lambda: later, sleep=lambda s: None, opener=ScriptedOpener(body, EVENTS_P1.read_bytes()),
                    access_decision=ALLOW)
    store = SnapshotStore(db)
    kc = [t for t in store.pm_sports_targets() if t["market_slug"] == KC_MIA]
    superseded = [t for t in kc if t["state"] == "SUPERSEDED"]
    assert len(superseded) == 3 and all("GAME_START_CHANGED" in t["state_reason"] for t in superseded)
    # The Odds API still says 17:00Z: the moved market is AMBIGUOUS now, so no new targets.
    assert len(kc) == 3


def test_targets_and_attempts_are_immutable(tmp_path):
    db = _discovered(tmp_path)
    with sqlite3.connect(db) as conn:
        for sql in ("UPDATE pm_sports_targets SET target_utc = 'x'", "DELETE FROM pm_sports_targets",
                    "UPDATE pm_sports_scans SET markets = 0", "DELETE FROM pm_sports_scans"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


# --------------------------------------------------------------------------- read-only views


def test_related_markets_view_for_the_terminal(tmp_path):
    db = _discovered(tmp_path)
    store = SnapshotStore.open_readonly(db)
    view = ps.related_markets(store, now=NOW)
    assert view["label"] == "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"
    assert view["executable"] is False and view["ranked"] is False and view["absence_is_evidence"] is False
    assert view["source"] == ps.ATTRIBUTION == "Polymarket US (gateway.polymarket.us public API)"
    kc = view["events"]["e_kc_mia"]
    assert kc["state"] == ps.RELATED and kc["markets"][0]["market_slug"] == KC_MIA
    assert kc["markets"][0]["equivalent"] is False and "PAYOFF_UNSUPPORTED" in kc["markets"][0]["flags"]
    assert kc["markets"][0]["latest_capture"] is None
    assert view["catalog"]["state"] == "FILTER_COMPLETE"


def test_terminal_view_states(tmp_path):
    assert ps.terminal_view(tmp_path / "missing.sqlite3", now=NOW)["state"] == "NO_STORE"
    db = _store(tmp_path)
    v = ps.terminal_view(db, now=NOW, access_decision=None)
    assert v["state"] == "BLOCKED_TERMS_REVIEW" and v["schema"] == "pm-sports-status/1"
    assert ps.terminal_view(db, now=NOW, access_decision=ALLOW)["state"] == "NO_SCAN"
    db2 = _discovered(tmp_path / "b")
    assert ps.terminal_view(db2, now=NOW, access_decision=ALLOW)["state"] == "FILTER_COMPLETE"
    assert ps.terminal_view(db2, now=NOW + timedelta(days=2), access_decision=ALLOW)["state"] == "STALE"


def test_freshness_records_for_the_fabric(tmp_path):
    db = _discovered(tmp_path)
    store = SnapshotStore.open_readonly(db)
    disc, cap = ps.freshness_records(store, now=NOW, access_decision=None)
    assert disc["acquisition_mode"] == "POLL" and cap["acquisition_mode"] == "EVENT_RELATIVE"
    assert disc["mode"] == cap["mode"] == "EXTERNAL_SCHEDULE"
    assert disc["schedule_state"] == "PAUSED" and "BLOCKED_TERMS_REVIEW" in disc["why"]
    disc, cap = ps.freshness_records(store, now=NOW, access_decision=ALLOW)
    assert disc["schedule_state"] == "NOT_DUE" and disc["freshness"] == "fresh" and disc["health"] == "OK"
    assert disc["catalog_state"] == "FILTER_COMPLETE"
    assert cap["schedule_state"] == "NOT_DUE" and cap["next_due_utc"] and cap["last_success_utc"] is None
    assert cap["freshness"] == "unknown" and cap["data_age_s"] is None  # missing is never zero
    disc, _ = ps.freshness_records(store, now=NOW + timedelta(hours=7), access_decision=ALLOW)
    assert disc["schedule_state"] == "DUE" and disc["freshness"] == "stale"


def test_fabric_provider_meets_the_c1_contract(tmp_path, monkeypatch):
    fr = pytest.importorskip("edge_lab.freshness")
    if not hasattr(fr, "SourceFreshness"):
        pytest.skip("the Freshness Fabric types (Lane A, feat/freshness-fabric) are not on this branch yet")
    db = _discovered(tmp_path)
    ctx = fr.FabricContext(db=db)
    assert [r.schedule_state for r in ps.fabric_provider(ctx, NOW)] == [fr.ScheduleState.NOT_DUE] * 2  # allowed
    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)  # the gate, read at call time
    disc, cap = ps.fabric_provider(ctx, NOW)
    assert (disc.policy, cap.policy) == ps.fabric_policies()  # equal to the declared policies
    # Fabric v1 (ADR 0031): run by its own timer, so EXTERNAL_SCHEDULE; the style is the underlying mode.
    assert disc.source_id == "polymarket_us_nfl_discovery" and disc.policy.underlying_mode is fr.AcquisitionMode.POLL
    assert cap.source_id == "polymarket_us_nfl_book" and cap.policy.underlying_mode is fr.AcquisitionMode.EVENT_RELATIVE
    assert disc.policy.mode is cap.policy.mode is fr.AcquisitionMode.EXTERNAL_SCHEDULE
    assert "edgelab-pm-sports-discover.timer" in disc.policy.schedule_owner
    assert "edgelab-pm-sports.timer" in cap.policy.schedule_owner
    assert disc.as_of == NOW and disc.schedule_state is fr.ScheduleState.PAUSED  # the terms gate
    assert disc.freshness is fr.Freshness.FRESH and disc.health is fr.SourceHealth.OK and disc.receipt_ts is not None
    assert cap.freshness is fr.Freshness.UNKNOWN and cap.receipt_ts is None and cap.health is fr.SourceHealth.UNKNOWN
    assert not disc.usable_for_decision and not cap.usable_for_decision
    assert disc.usable_for_research and not cap.usable_for_research  # a receipt of known freshness only
    assert cap.details["missed_scope"] == ps.MISSED_SCOPE_TARGETS and cap.missed_count == 0
    fabric_mod = pytest.importorskip("edge_lab.freshness_fabric")
    assert ps.MISSED_SCOPE_TARGETS == fabric_mod.MISSED_SCOPE_TARGETS  # one scope vocabulary
    if hasattr(fr, "usable_flags"):  # never looser than the fabric's rule
        assert (disc.usable_for_research, False) == (fr.usable_flags(disc.freshness, disc.health, disc.receipt_ts)[0],
                                                     disc.usable_for_decision)
    missing = ps.fabric_provider(fr.FabricContext(db=tmp_path / "none.sqlite3"), NOW)
    assert [r.schedule_state for r in missing] == [fr.ScheduleState.UNKNOWN] * 2
    assert [r.freshness for r in missing] == [fr.Freshness.UNKNOWN] * 2
    fabric = pytest.importorskip("edge_lab.freshness_fabric")
    entry = fr.FabricProvider(ps.FABRIC_PROVIDER_NAME, ps.fabric_policies(), ps.fabric_provider)
    records, reports = fabric.evaluate(ctx, NOW, registry=(entry,))
    assert reports == [{"provider": ps.FABRIC_PROVIDER_NAME, "state": "OK", "problems": []}]
    assert [r.to_dict()["schedule_state"] for r in records] == ["PAUSED", "PAUSED"]


def test_status_and_cli(tmp_path, capsys, monkeypatch):
    db = _discovered(tmp_path)
    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)  # no real clock-driven network run from a test
    assert ps.main(["status", "--db", str(db), "--market", KC_MIA]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["access"] == "BLOCKED_TERMS_REVIEW" and out["catalog"]["state"] in ("FILTER_COMPLETE", "STALE")
    assert len(out["market_history"]) == 3
    from edge_lab import cli

    assert cli.main(["pm-sports", "capture", "--db", str(db)]) == 0  # the gate: no network, exit 0
    assert json.loads(capsys.readouterr().out)["state"] == "BLOCKED_TERMS_REVIEW"
    # Out-of-range caps are a clean usage error, not a traceback.
    assert cli.main(["pm-sports", "capture", "--db", str(db), "--max-requests", "51"]) == 2
    assert cli.main(["pm-sports", "capture", "--db", str(db), "--max-books", "0"]) == 2
    assert "--max-books must be in 1..20" in capsys.readouterr().err


def test_at_most_100_requests_per_minute_per_run():
    from edge_lab import http

    now = [0.0]
    req = ps._Requests(500, NOW + timedelta(minutes=3), lambda: NOW, lambda s: None, http.Pacer(0),
                       opener=lambda r, t: None, monotonic=lambda: now[0])
    for _ in range(ps.MAX_REQUESTS_PER_MINUTE):
        req._open(None, 1.0)
    with pytest.raises(ps.RequestRateCapReached):
        req._open(None, 1.0)
    now[0] = 60.0  # a minute later the window has room again
    req._open(None, 1.0)
    assert req.attempts == ps.MAX_REQUESTS_PER_MINUTE + 1
    assert issubclass(ps.RequestRateCapReached, ps.RequestBudgetExhausted)  # deferred, never FAILED
    assert ps.MAX_REQUESTS_PER_MINUTE == 100 and 60 / ps.PACER_INTERVAL_S <= ps.MAX_REQUESTS_PER_MINUTE


# --------------------------------------------------------------------------- EXP-002 label proxy (display)
#
# A related market's book at T-60m, or received after EXP-002's T-6h decision cutoff, is a proxy for the Kalshi
# T-60m label books (docs/research/EXP002_FREEZE_PROPOSAL.md §4): the read-only views withhold its figures.

PROXY_BID, PROXY_ASK, PROXY_QTY = "0.4125", "0.4175", "777.0000"  # SYNTHETIC: absent from every recorded body


_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_HEX_ID = re.compile(r"\b[0-9a-f]{8,}(?:-[0-9a-f]{4,})*\b")


def _scrub_volatile(text: str) -> str:
    """`text` with ISO timestamps and hex / uuid ids replaced: they are wall-clock or random, not figures."""
    return _HEX_ID.sub("<id>", _ISO_TIME.sub("<time>", text))


def _proxy_book() -> bytes:
    """The recorded KC-MIA book with SYNTHETIC top levels (so a leak of the T-60m figures is detectable)."""
    raw = json.loads(BOOK_KC_MIA.read_bytes())
    data = {k: v for k, v in raw["marketData"].items() if k != "stats"}
    data["bids"] = [{"px": {"value": PROXY_BID, "currency": "USD"}, "qty": PROXY_QTY}]
    data["offers"] = [{"px": {"value": PROXY_ASK, "currency": "USD"}, "qty": PROXY_QTY}]
    return json.dumps({"marketData": data}).encode()


def _capture_at(db: Path, at: datetime, body: bytes, monkeypatch) -> dict:
    from edge_lab import http as pm_http

    class _At(datetime):  # the fetch layer stamps receipt with the wall clock: pin it
        @classmethod
        def now(cls, tz=None):
            return at + timedelta(seconds=20)
    _fresh_catalog_at(db, at - timedelta(hours=2))
    with monkeypatch.context() as m:
        m.setattr(pm_http, "datetime", _At)
        code, report = ps.run_capture(db, clock=lambda: at, sleep=lambda s: None, opener=ScriptedOpener(body),
                                      access_decision=ALLOW)
    assert code == 0 and report["by_status"] == {"CAPTURED": 1}, report
    return report


def test_the_decision_cutoff_is_never_later_than_the_odds_t6h_deadline():
    """Kickoff 17:00Z: moved 15 min earlier, T-6h at 10:45Z, + the 30-min late tolerance = 11:15Z. For every
    Polymarket kickoff and every Odds kickoff within the relation's tolerance, the cutoff is never later than
    the Odds T-6h target's own deadline (quiet-window shifts included)."""
    from edge_lab.odds_schedule import CaptureTarget, PilotConfig, deadline

    assert ps.decision_cutoff("2026-09-27T17:00:00Z") == datetime(2026, 9, 27, 11, 15, tzinfo=UTC)
    assert ps.decision_cutoff(None) is None and ps.decision_cutoff("not a time") is None
    base = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    for step in range(0, 24 * 12):  # every 5 minutes over a day: crosses the 17:40-18:35 ET quiet window
        pm_kick = base + timedelta(minutes=5 * step)
        cutoff = ps.decision_cutoff(pm_kick.isoformat())
        for delta in (-15, -10, -5, 0, 5, 10, 15):
            kick = pm_kick + timedelta(minutes=delta)
            odds = CaptureTarget("x", "americanfootball_nfl", "e", "T-6h", 2, kick, kick - timedelta(hours=6))
            assert cutoff <= deadline(odds, PilotConfig()), (pm_kick, delta)


@pytest.mark.parametrize("offset,received,hidden", [
    ("T-24h", "2026-09-26T17:00:20Z", False),
    ("T-6h", "2026-09-27T11:00:25Z", False),
    ("T-6h", "2026-09-27T11:15:00Z", False),  # at the cutoff
    ("T-6h", "2026-09-27T11:15:01Z", True),  # after the T-6h decision cutoff
    ("T-24h", "2026-09-27T12:00:00Z", True),
    ("T-60m", "2026-09-27T16:00:20Z", True),
    ("T-60m", None, True),  # the horizon alone withholds it
    ("T-2h", "2026-09-27T10:00:00Z", True),  # a horizon this code does not know fails closed
    ("T-6h", "garbage", True),
    ("T-6h", None, False),  # nothing received: no figure exists
])
def test_which_captures_are_a_label_proxy(offset, received, hidden):
    assert ps.is_label_proxy(offset, "2026-09-27T17:00:00Z", received) is hidden
    assert ps.is_label_proxy("T-6h", None, "2026-09-26T17:00:20Z") is True  # unknown kickoff fails closed


def test_withholding_keeps_status_timing_and_the_reason_code_only():
    row = {"target_id": "t", "status": "NOT_EXECUTABLE",
           "reason": "BOOK_ANOMALY: crossed book: bid 0.4225 >= offer 0.4175",
           "received_at_utc": "2026-09-27T16:00:20Z", "source_timestamp_utc": "2026-09-27T16:00:19Z",
           "book_state": "MARKET_STATE_OPEN", "freshness": "fresh", "snapshot_id": 7, "deviation_s": 20.0,
           "yes_bid": None, "yes_bid_size": None, "yes_ask": None, "yes_ask_size": None, "depth_json": None}
    out = ps.withhold_label_proxy(row, offset_label="T-60m", game_start_utc="2026-09-27T17:00:00Z")
    assert out["reason"] == "BOOK_ANOMALY: withheld (EXP-002 label proxy)" and "0.42" not in json.dumps(out)
    assert out["label_proxy"] == ps.LABEL_PROXY_HIDDEN and not set(ps.LABEL_PROXY_FIELDS) & set(out)
    for key in ("status", "received_at_utc", "source_timestamp_utc", "book_state", "freshness", "snapshot_id",
                "deviation_s"):
        assert out[key] == row[key], key
    marker = ps.LABEL_PROXY_HIDDEN
    for name in ("EXP-002", "T-60m", "T-6h"):
        marker = marker.replace(name, "")
    assert not any(ch.isdigit() for ch in marker)  # the marker itself carries no figure
    free = ps.withhold_label_proxy({**row, "reason": "no code here 0.42"}, offset_label="T-60m",
                                   game_start_utc="2026-09-27T17:00:00Z")
    assert free["reason"] == ps.LABEL_PROXY_REASON
    early = {**row, "status": "CAPTURED", "reason": None, "received_at_utc": "2026-09-27T11:00:25Z",
             "yes_bid": "0.3050"}
    kept = ps.withhold_label_proxy(early, offset_label="T-6h", game_start_utc="2026-09-27T17:00:00Z")
    assert kept == early  # T-6h before the cutoff: unchanged
    late = ps.withhold_label_proxy(row, offset_label="T-6h", game_start_utc="2026-09-27T17:00:00Z")
    assert late["label_proxy"] == ps.LABEL_PROXY_HIDDEN  # a T-6h target read after the cutoff is withheld too


def test_t60m_captures_are_withheld_from_the_views_and_the_cli(tmp_path, capsys, monkeypatch):
    """Real bytes at T-24h and T-6h, a SYNTHETIC-priced book at T-60m: the views and `pm-sports status`
    show the pre-decision figures and withhold the T-60m ones; counts, states and timing are unchanged and
    the stored rows keep every figure (raw evidence is immutable)."""
    db = _discovered(tmp_path, odds_at=NOW)
    for at, body in ((datetime(2026, 9, 26, 17, 0, tzinfo=UTC), BOOK_KC_MIA.read_bytes()),
                     (datetime(2026, 9, 27, 11, 0, tzinfo=UTC), BOOK_KC_MIA.read_bytes()),
                     (datetime(2026, 9, 27, 16, 0, tzinfo=UTC), _proxy_book())):
        _capture_at(db, at, body, monkeypatch)
    store = SnapshotStore.open_readonly(db)
    stored = {t["offset_label"]: store.pm_sports_observations(target_id=t["target_id"])[-1]
              for t in store.pm_sports_targets(market_slug=KC_MIA)}
    assert stored["T-60m"]["yes_bid"] == PROXY_BID and stored["T-60m"]["yes_ask"] == PROXY_ASK  # stored as received
    assert stored["T-24h"]["yes_bid"] == stored["T-6h"]["yes_bid"] == "0.8500"

    history = {t["offset"]: t for t in ps.market_history(store, KC_MIA)}
    assert [history[o]["state"] for o in ("T-24h", "T-6h", "T-60m")] == ["CAPTURED"] * 3
    for o in ("T-24h", "T-6h"):
        a = history[o]["attempts"][-1]
        assert a["yes_bid"] == "0.8500" and a["yes_ask"] == "0.8550" and "label_proxy" not in a
        assert a["depth_json"] is not None
    hidden = history["T-60m"]["attempts"][-1]
    assert hidden["label_proxy"] == ps.LABEL_PROXY_HIDDEN and not set(ps.LABEL_PROXY_FIELDS) & set(hidden)
    assert hidden["status"] == "CAPTURED" and hidden["received_at_utc"] == stored["T-60m"]["received_at_utc"]
    assert hidden["freshness"] == "fresh" and hidden["book_state"] == "MARKET_STATE_OPEN"

    later = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    view = ps.related_markets(store, now=later)
    latest = view["events"]["e_kc_mia"]["markets"][0]["latest_capture"]
    assert latest["offset"] == "T-60m" and latest["label_proxy"] == ps.LABEL_PROXY_HIDDEN
    assert latest["received_at_utc"] == stored["T-60m"]["received_at_utc"] and latest["freshness"] == "fresh"
    assert not set(ps.LABEL_PROXY_FIELDS) & set(latest)

    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)  # no clock-driven network run from a test
    assert ps.main(["status", "--db", str(db), "--market", KC_MIA]) == 0
    out = capsys.readouterr().out
    # The output also holds uuid4 run / attempt ids and a microsecond `now`: a figure must not match inside them
    # (a bare "777" did about 1.3% of runs), so they are replaced before the substring check.
    scrubbed = _scrub_volatile(out)
    for figure in (PROXY_BID, PROXY_ASK, PROXY_QTY, "41.25", "41.75", "777"):
        assert figure not in scrubbed, figure  # no reveal path in the CLI either
    assert "0.8500" in out and ps.LABEL_PROXY_HIDDEN in out
    tv = json.dumps(ps.terminal_view(db, now=later, access_decision=ALLOW), default=str)
    assert PROXY_BID not in tv and PROXY_ASK not in tv and PROXY_QTY not in tv


def test_a_withheld_targets_miss_reason_is_its_code_everywhere(tmp_path):
    """Review NIT 3: `status().recent_misses` and the fabric's `recent_misses` reduce a T-60m target's MISSED
    reason to its code, as `market_history` does; a pre-decision target's reason stays in full."""
    db = _discovered(tmp_path, odds_at=_due_clock_for_kc() - timedelta(hours=1))
    at = datetime(2026, 9, 27, 16, 40, tzinfo=UTC)  # past every KC-MIA deadline: all three are MISSED
    _fresh_catalog_at(db, at - timedelta(hours=2))
    ps.run_capture(db, clock=lambda: at, opener=ScriptedOpener(), access_decision=ALLOW)
    store = SnapshotStore.open_readonly(db)
    withheld = f"NOT_CAPTURED_BY_DEADLINE: {ps.LABEL_PROXY_REASON}"
    misses = {m["target_id"]: m["reason"] for m in ps.status(store, now=at, access_decision=ALLOW)["recent_misses"]}
    kc = {tid.split(":")[2]: reason for tid, reason in misses.items() if KC_MIA in tid}
    assert kc["T-60m"] == withheld
    assert kc["T-6h"].startswith("NOT_CAPTURED_BY_DEADLINE: no capture in [") and kc["T-6h"] != withheld
    history = {t["offset"]: t["attempts"][-1]["reason"] for t in ps.market_history(store, KC_MIA)}
    assert history["T-60m"] == withheld and history["T-6h"] == kc["T-6h"]
    _, cap = ps.freshness_records(store, now=at, access_decision=ALLOW)
    t60 = [m for m in cap["recent_misses"] if KC_MIA in m and ":T-60m:" in m]
    assert t60 and all(m.endswith(f": {withheld}") for m in t60)
    assert ps.withhold_reason(None, offset_label="T-60m", game_start_utc=None) is None
