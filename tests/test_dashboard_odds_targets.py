"""The Odds API capture target / history table (Research & Data -> Data sources).

Owner directive 2026-09-24 (Freshness Fabric + sports), Terminal v1 and contract C4; ADR 0029.
Every visible value comes from the stored `odds_capture_targets` / `odds_capture_transitions`
rows, the captured snapshot parsed by `odds_api.parse_odds`, the canonical planner's deadline and
the source's freshness rule. States: populated, empty, no captures yet, stale (overdue), missed,
quota blocked, error, source unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import odds_api
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.views import research
from edge_lab.odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z, plan_targets
from edge_lab.storage import ODDS_TARGET_STATES, SnapshotStore

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

NOW = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)
SPORT = "americanfootball_nfl"
KICKOFF = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def get(cfg: Config, path: str = "/experiments", query: str = "tab=sources") -> tuple[str, str]:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query,
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


def section(body: str, sid: str) -> str:
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


def _store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "edge_lab.sqlite3")


def _plan(store: SnapshotStore, event: ScheduledEvent, *, offsets=DEFAULT_OFFSETS) -> dict:
    out = {}
    for t in plan_targets([event], offsets):
        store.plan_odds_target(target_id=t.target_id, sport=SPORT, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=iso_z(t.commence_utc),
                               target_utc=iso_z(t.target_utc), planned_at_utc="2026-09-24T12:00:00Z",
                               policy_version="game_relative_v1", home_team=t.home_team, away_team=t.away_team)
        out[t.offset_label] = t
    return out


def _event(native="evt1", home="Green Bay Packers", away="Atlanta Falcons", kickoff=KICKOFF) -> ScheduledEvent:
    return ScheduledEvent(native, SPORT, kickoff, home_team=home, away_team=away)


def _capture(store: SnapshotStore, targets, events: list[dict], *, credits=3, at="2026-09-24T18:15:41Z",
             payload=None, source="the_odds_api", kind="odds") -> int:
    store.start_run(f"run-{at}")
    sid = store.save_snapshot(run_id=f"run-{at}", source=source, kind=kind, entity_id=SPORT, url="https://x/odds",
                              payload=payload if payload is not None else
                              {"sport": SPORT, "events": events, "request": {"odds_format": "american"}},
                              fetched_at_utc=at)
    for t in targets:
        store.record_odds_transition(target_id=t.target_id, state="CAPTURING", at_utc=at, slot_id="slot-1")
        store.record_odds_transition(target_id=t.target_id, state="CAPTURED", at_utc=at, slot_id="slot-1",
                                     snapshot_id=sid, captured_at_utc=at, credits_last=credits,
                                     detail={"deviation_minutes": 0.7})
    return sid


def _cfg(tmp_path: Path, now: datetime = NOW, **kw) -> Config:
    return Config(db=tmp_path / "edge_lab.sqlite3", clock=lambda: now, **kw)


def _body(tmp_path: Path, now: datetime = NOW) -> str:
    _, body = get(_cfg(tmp_path, now))
    return section(body, "odds-t-h")


# --------------------------------------------------------------------------- production shape


@pytest.fixture
def production():
    cfg, root = fixture_states.odds_pilot()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def test_production_shape_95_targets_one_captured_with_nine_books(production):
    result = d.Context(production).odds_targets
    assert result.status == d.OK
    targets = result.value
    assert len(targets.rows) == 95 and targets.by_state == {"CAPTURED": 1, "PLANNED": 94}
    (cap,) = [t for t in targets.rows if t.state == "CAPTURED"]
    assert cap.offset_label == "T-6h" and cap.credits_last == 3 and len(cap.books) == 9 and cap.offers == 54
    assert cap.freshness == "FRESH"  # judged at receipt: the offers were a minute old when received
    assert cap.shared_targets == 1 and cap.transitions is not None
    assert len(targets.recent) <= d.ODDS_TARGETS_SHOWN and len(targets.upcoming) == d.ODDS_TARGETS_SHOWN
    status, body = get(production)
    text = plain(section(body, "odds-t-h"))
    assert status == "200 OK"
    for needle in ("Odds capture targets", "T-24h / T-6h / T-60m before kickoff", "Targets 95", "Captured 1",
                   "Missed 0", "Atlanta Falcons @ Green Bay Packers", "T-6h · kickoff Sep 24, 8:15 PM EDT",
                   "Intended (ET) Sep 24, 2:15 PM EDT", "Actual receipt Sep 24, 2:15 PM EDT", "Credits 3 one paid call",
                   "Books returned 9 54 offers", "Freshness Fresh at receipt", "historical, not current", "odds max age 10 min", "All targets (95)",
                   "never executable prices"):
        assert needle in text, needle
    assert "Paid captures paused" not in text and "No captures yet" not in text
    assert "past the deadline" not in text


def test_the_section_sits_with_the_odds_card_and_adds_no_navigation(production):
    _, body = get(production)
    assert body.index('aria-labelledby="odds-h"') < body.index('aria-labelledby="odds-t-h"') \
        < body.index('aria-labelledby="src-h"')
    _, home = get(production, "/", "")
    def nav(html: str) -> list[str]:
        (rail,) = re.findall(r'<nav class="rail".*?</nav>', html, re.S)
        return re.findall(r'href="([^"]+)"', rail)
    assert nav(home) == nav(body) and not any("odds" in h for h in nav(body))


def test_the_history_table_lists_every_target_and_rows_are_bounded(production):
    _, body = get(production)
    part = section(body, "odds-t-h")
    table = part[part.index("All targets (95)"):]
    assert table.count("<tr>") == 96  # header + 95
    shown = part[:part.index("All targets (95)")]
    assert shown.count('class="row"') == 1 + d.ODDS_TARGETS_SHOWN


def test_the_history_table_is_capped_and_says_so(production, monkeypatch):
    monkeypatch.setattr(d, "ODDS_TARGETS_MAX", 10)
    _, body = get(production)
    part = section(body, "odds-t-h")
    assert part[part.index("All targets (95)"):].count("<tr>") == 11
    assert "85 older targets are not listed here" in plain(part)


def test_the_loader_never_writes(production):
    path = production.db
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    get(production)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


# --------------------------------------------------------------------------- states


def test_source_unavailable_without_a_database(tmp_path):
    for cfg in (Config(clock=lambda: NOW), _cfg(tmp_path)):  # not configured; configured but absent
        result = d.Context(cfg).odds_targets
        assert result.status == d.NO_DATA
        html = research.odds_targets_body(result, d.Loaded(d.NO_DATA), NOW)
        assert "Capture targets unavailable" in plain(html) and "Source unavailable" in plain(html)
        assert "k-err" not in html and "No capture targets planned yet" not in html


def test_a_read_error_is_an_error_never_an_empty_schedule(tmp_path, monkeypatch):
    bad = tmp_path / "edge_lab.sqlite3"
    bad.write_bytes(b"not a database" * 50)
    text = _body(tmp_path)
    assert "Capture targets unavailable (read error)" in plain(text) and 'role="alert"' in text
    assert "This is not an empty schedule" in plain(text) and "No capture targets planned yet" not in text

    good = tmp_path / "good"
    good.mkdir()
    _store(good)

    def boom(self, **kw):
        raise RuntimeError(f"disk gone at {good}")
    monkeypatch.setattr(SnapshotStore, "odds_targets", boom)
    result = d.Context(_cfg(good)).odds_targets
    assert result.status == d.ERROR and str(good) not in result.message


def test_empty_when_no_target_is_stored(tmp_path):
    _store(tmp_path)
    text = plain(_body(tmp_path))
    assert "No capture targets planned yet" in text and "Targets 0" not in text


def test_no_captures_yet(tmp_path):
    store = _store(tmp_path)
    _plan(store, _event(kickoff=datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)))
    text = plain(_body(tmp_path))
    assert "No captures yet" in text and "3 targets are stored and none has been captured" in text
    assert "Next target due Sep 26, 1:00 PM EDT" in text
    assert "Captured 0" in text and "Not captured yet" in text


def test_an_open_target_past_its_deadline_is_stale_never_pending(tmp_path):
    store = _store(tmp_path)
    targets = _plan(store, _event())
    later = targets["T-60m"].target_utc + timedelta(minutes=31)  # the canonical deadline has passed
    result = d.Context(_cfg(tmp_path, later)).odds_targets.value
    by = {t.offset_label: t for t in result.rows}
    assert by["T-60m"].freshness == d.TARGET_OVERDUE and by["T-60m"].state == "PLANNED"
    text = plain(_body(tmp_path, later))
    assert "open targets past the deadline" in text or "open target past the deadline" in text
    assert "as Failed if a capture was left in progress" in text  # review SF-3
    assert "Overdue no outcome recorded since the deadline" in text and "not observable here" in text
    early = d.Context(_cfg(tmp_path, targets["T-60m"].target_utc + timedelta(minutes=29))).odds_targets.value
    assert {t.offset_label: t.freshness for t in early.rows}["T-60m"] == d.TARGET_PENDING


def test_missed_failed_skipped_and_superseded_show_their_reasons(tmp_path):
    store = _store(tmp_path)
    t = _plan(store, _event(kickoff=NOW - timedelta(hours=2)))
    store.record_odds_transition(target_id=t["T-24h"].target_id, state="MISSED", at_utc="2026-09-23T19:00:00Z",
                                 reason="expired while PLANNED")
    store.record_odds_transition(target_id=t["T-6h"].target_id, state="CAPTURING", at_utc="2026-09-24T13:00:00Z")
    store.record_odds_transition(target_id=t["T-6h"].target_id, state="FAILED", at_utc="2026-09-24T13:00:01Z",
                                 reason="paid call failed (not retried): HTTP 500")
    store.record_odds_transition(target_id=t["T-60m"].target_id, state="SUPERSEDED", at_utc="2026-09-24T13:00:02Z",
                                 reason="commence time changed")
    later = _plan(store, _event("evt2", "Houston Texans", "Jacksonville Jaguars",
                                datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)))
    store.record_odds_transition(target_id=later["T-24h"].target_id, state="SKIPPED_BUDGET",
                                 at_utc="2026-09-24T20:00:00Z", reason="monthly credit proof: no headroom")
    text = plain(_body(tmp_path))
    for needle in ("Missed 1", "Failed 1", "Missed Intended", "Reason expired while PLANNED",
                   "Reason paid call failed (not retried): HTTP 500", "Superseded",
                   "Skipped · budget", "Reason monthly credit proof: no headroom", "Nothing captured"):
        assert needle in text, needle
    html = _body(tmp_path)
    assert "a failed call may still have been charged" in html  # FAILED credits unknown, never 0


def test_quota_blocked_is_a_blocked_state_from_the_canonical_status(tmp_path):
    store = _store(tmp_path)
    _plan(store, _event())
    targets = d.Context(_cfg(tmp_path)).odds_targets
    for state in research.ODDS_PAUSED:
        status = d.Loaded(d.OK, {"state": state, "detail": f"detail for {state}", "live_read_verified": True})
        html = research.odds_targets_body(targets, status, NOW)
        assert f"Paid captures paused — {pr.state_word(state).label}" in plain(html), state
        assert "Detail for " + state in plain(html) and 'class="empty k-warn"' in html
    for status in (d.Loaded(d.OK, {"state": "ACTIVE", "live_read_verified": True}),
                   d.Loaded(d.OK, {"state": "SETUP_NEEDED"}), d.Loaded(d.ERROR, message="x"), d.Loaded(d.NO_DATA)):
        assert "Paid captures paused" not in research.odds_targets_body(targets, status, NOW)


def test_the_real_quota_exhausted_fixture_blocks_and_marks_the_overdue_target():
    cfg, root = fixture_states.odds_issues()
    try:
        _, body = get(cfg)
        text = plain(section(body, "odds-t-h"))
        assert "Paid captures paused — Quota exhausted" in text
        assert "1 open target past the deadline" in text and "Missed 3" in text and "Failed 1" in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------------------- books, credits, freshness


def _odds(native: str, books: list[str], updated: str | None = None) -> dict:
    return {"id": native, "sport_key": SPORT, "commence_time": iso_z(KICKOFF), "home_team": "H", "away_team": "A",
            "bookmakers": [{"key": b, **({"last_update": updated} if updated else {}),
                            "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": -150},
                                                                     {"name": "A", "price": 130}]}]}
                           for b in books]}


def test_books_come_from_the_snapshot_and_a_known_zero_is_not_unknown(tmp_path):
    store = _store(tmp_path)
    one = _plan(store, _event("evt1"))
    two = _plan(store, _event("evt2", "Houston Texans", "Jacksonville Jaguars"))
    # One paid call for both games' T-6h targets; only evt1 is in the response.
    _capture(store, [one["T-6h"], two["T-6h"]], [_odds("evt1", ["draftkings", "fanduel"])])
    rows = {t.event_id: t for t in d.Context(_cfg(tmp_path)).odds_targets.value.rows if t.state == "CAPTURED"}
    assert rows["evt1"].books == ("draftkings", "fanduel") and rows["evt1"].offers == 4
    assert rows["evt2"].books == () and rows["evt2"].books_note == "this event is not in the stored response"
    assert rows["evt1"].shared_targets == rows["evt2"].shared_targets == 2
    html = _body(tmp_path)
    text = plain(html)
    assert "one paid call shared by 2 targets" in text
    assert plain(research.targets_table(d.Context(_cfg(tmp_path)).odds_targets.value)).count("shared by 2") == 2
    assert "Books returned 0 0 offers · this event is not in the stored response" in text
    assert "Credits 6" not in text  # one call's credits are never added up per target


def test_an_unreadable_or_foreign_snapshot_leaves_books_unknown(tmp_path):
    store = _store(tmp_path)
    one = _plan(store, _event("evt1"))
    two = _plan(store, _event("evt2"))
    _capture(store, [one["T-6h"]], [], payload={"sport": SPORT, "events": [], "request": {"odds_format": "nope"}})
    _capture(store, [two["T-6h"]], [], at="2026-09-24T18:16:00Z", source="kalshi", kind="orderbook")
    rows = {t.event_id: t for t in d.Context(_cfg(tmp_path)).odds_targets.value.rows if t.state == "CAPTURED"}
    assert rows["evt1"].books is None and "unreadable" in rows["evt1"].books_note
    assert rows["evt2"].books is None and "not a stored odds response" in rows["evt2"].books_note
    assert d.Context(_cfg(tmp_path)).odds_targets.status == d.OK  # one bad capture never hides the table


def test_a_capture_is_judged_fresh_or_stale_at_receipt_never_as_current(tmp_path):
    store = _store(tmp_path)
    one, two, three = (_plan(store, _event(f"evt{i}")) for i in (1, 2, 3))
    limit = odds_api.get_source(odds_api.SOURCE_ID).max_age["odds"]
    received = datetime(2026, 9, 24, 18, 15, 43, tzinfo=timezone.utc)
    _capture(store, [one["T-6h"]], [_odds("evt1", ["draftkings"], "2026-09-24T18:15:00Z")])  # 41 s old at receipt
    _capture(store, [two["T-6h"]], [_odds("evt2", ["draftkings"], iso_z(received - limit - timedelta(minutes=1)))],
             at="2026-09-24T18:15:43Z")
    _capture(store, [three["T-6h"]], [_odds("evt3", ["draftkings"])], at="2026-09-24T18:15:42Z")  # no last_update
    later = NOW + timedelta(hours=1)  # hours after receipt a capture is still "fresh at receipt", never current
    rows = {t.event_id: t for t in d.Context(_cfg(tmp_path, later)).odds_targets.value.rows if t.state == "CAPTURED"}
    assert {k: v.freshness for k, v in rows.items()} == {"evt1": "FRESH", "evt2": "STALE", "evt3": "UNKNOWN"}
    text = plain(_body(tmp_path, later))
    for needle in ("Fresh at receipt", "Stale at receipt", "Unknown at receipt", "historical, not current"):
        assert needle in text, needle


def test_parsing_is_bounded_to_the_rows_shown_and_memoized(tmp_path, monkeypatch):
    """Review SF-1: never parse every stored capture on a page load."""
    store = _store(tmp_path)
    for i in range(30):  # 30 past games, each T-60m captured by its own paid call
        t = _plan(store, _event(f"old{i}", kickoff=datetime(2026, 9, 10, 17, tzinfo=timezone.utc)
                                + timedelta(hours=i)))
        _capture(store, [t["T-60m"]], [_odds(f"old{i}", ["draftkings", "fanduel"])],
                 at=iso_z(t["T-60m"].target_utc + timedelta(seconds=30)))
        for gone in ("T-24h", "T-6h"):
            store.record_odds_transition(target_id=t[gone].target_id, state="MISSED", at_utc="2026-09-11T00:00:00Z",
                                         reason="expired while PLANNED")
    calls = []  # the dashboard's own parses (evidence id "N") and the consensus contract's ("snapshot:N")
    real = odds_api.parse_odds
    monkeypatch.setattr(odds_api, "parse_odds", lambda *a, **k: calls.append(str(k.get("evidence_id"))) or real(*a, **k))
    d._PARSED.clear()
    result = d.Context(_cfg(tmp_path)).odds_targets.value
    assert len(result.rows) == 90 and result.count("CAPTURED") == 30
    mine = [c for c in calls if not c.startswith("snapshot:")]
    assert 0 < len(mine) <= 2 * d.ODDS_TARGETS_SHOWN and len(result.snapshots) == len(mine)
    shown_captures = sum(t.state == "CAPTURED" for t in (*result.recent, *result.upcoming))
    assert len(calls) - len(mine) == shown_captures  # one consensus read per captured row shown, no more
    history = [t for t in result.rows if t.state == "CAPTURED" and t.transitions is None]
    assert history and all(t.books_source is None and t.freshness == d.NOT_EVALUATED for t in history)
    calls.clear()
    d.Context(_cfg(tmp_path)).odds_targets  # the same page again: books and consensus from the bounded caches
    assert calls == [] and len(d._PARSED) <= d.ODDS_PARSE_CACHE_MAX
    assert len(d._CONSENSUS) <= d.ODDS_CONSENSUS_CACHE_MAX
    store.start_run("later")  # another source's write leaves the consensus memo valid (review SF-1)
    store.save_snapshot(run_id="later", source="kalshi", kind="markets", entity_id="x", url="u", payload={})
    d.Context(_cfg(tmp_path)).odds_targets
    assert calls == [] and shown_captures > 0


def test_history_rows_use_the_runners_record_at_capture(tmp_path):
    store = _store(tmp_path)
    one = _plan(store, _event("evt1", kickoff=datetime(2026, 9, 10, 17, tzinfo=timezone.utc)))
    sid = _capture(store, [], [_odds("evt1", ["draftkings"])], at="2026-09-10T11:00:20Z")
    store.record_odds_transition(target_id=one["T-6h"].target_id, state="CAPTURED", at_utc="2026-09-10T11:00:20Z",
                                 snapshot_id=sid, captured_at_utc="2026-09-10T11:00:20Z", credits_last=3,
                                 detail={"bookmakers": ["draftkings", "fanduel"], "offers": 4, "parse_problems": 2})
    for i in range(12):  # push the capture out of the rows shown
        _plan(store, _event(f"late{i}", kickoff=datetime(2026, 9, 23, 17, tzinfo=timezone.utc) + timedelta(hours=i)))
    targets = d.Context(_cfg(tmp_path)).odds_targets.value
    (row,) = [t for t in targets.rows if t.target_id == one["T-6h"].target_id]
    assert row not in targets.recent and row.books == ("draftkings", "fanduel") and row.offers == 4
    assert row.books_source == d.BOOKS_RECORDED and "2 parse problems" in row.books_note
    assert "2 may be incomplete" in plain(research.targets_table(targets))


def test_parse_problems_are_a_caveat_never_a_confident_count(tmp_path):
    """Review SF-2: a response with skipped or malformed bookmakers carries a caveat."""
    store = _store(tmp_path)
    t = _plan(store, _event())
    event = _odds("evt1", ["draftkings", "fanduel"])
    event["bookmakers"].append({"markets": []})  # a bookmaker without a key: skipped by the parser
    _capture(store, [t["T-6h"]], [event])
    (row,) = [x for x in d.Context(_cfg(tmp_path)).odds_targets.value.rows if x.state == "CAPTURED"]
    assert row.books == ("draftkings", "fanduel") and "1 parse problem" in row.books_note
    assert "the count may be incomplete" in plain(_body(tmp_path))


def test_other_sports_targets_are_not_mixed_in(tmp_path):
    store = _store(tmp_path)
    _plan(store, _event())
    for t in plan_targets([ScheduledEvent("nba1", "basketball_nba", KICKOFF, "X", "Y")], DEFAULT_OFFSETS):
        store.plan_odds_target(target_id=t.target_id, sport="basketball_nba", event_id=t.event_id,
                               offset_label=t.offset_label, priority=t.priority,
                               commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                               planned_at_utc="2026-09-24T12:00:00Z", policy_version="game_relative_v1")
    targets = d.Context(_cfg(tmp_path)).odds_targets.value
    assert len(targets.rows) == 3 and {t.sport for t in targets.rows} == {SPORT}
    assert "NFL · T-24h / T-6h / T-60m before kickoff" in plain(get(_cfg(tmp_path))[1])


def test_an_unknown_state_is_shown_neutral_with_its_code():
    targets = fixtures.synthetic_odds_targets()["populated"]
    html = research.odds_targets_body(targets, d.Loaded(d.NO_DATA), NOW)
    assert 'title="code: SOMETHING_NEW"' in html and "Something new" in plain(html)
    assert "SOMETHING_NEW" not in ODDS_TARGET_STATES


def test_every_canonical_target_state_has_a_plain_word():
    for state in ODDS_TARGET_STATES:
        assert state in pr.STATES, state
    for code in (d.TARGET_OVERDUE, d.TARGET_PENDING, d.TARGET_NO_CAPTURE):
        assert code in pr.STATES


def test_untrusted_text_is_escaped(tmp_path):
    evil = "<script>alert(1)</script>"
    store = _store(tmp_path)
    t = _plan(store, _event(home=evil, away=evil))
    store.record_odds_transition(target_id=t["T-24h"].target_id, state="MISSED", at_utc="2026-09-24T01:00:00Z",
                                 reason=evil)
    html = _body(tmp_path)
    assert evil not in html and "&lt;script&gt;" in html


def test_gallery_shows_every_state():
    from edge_lab.dashboard.demo import build_demo
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        status, body = get(cfg, "/gallery", "")
        assert status == "200 OK"
        text = plain(body)
        for needle in ("Odds capture targets (populated)", "Paid captures paused — Quota exhausted", "No captures yet",
                       "No capture targets planned yet", "Capture targets unavailable", "(read error)",
                       "Overdue no outcome recorded since the deadline", "Captured", "Missed", "Skipped · budget",
                       "Superseded", "Deferred", "Something new"):
            assert needle in text, needle
        # The demo store holds no targets: the sources tab shows the empty state, never synthetic rows.
        _, sources = get(cfg)
        assert "No capture targets planned yet" in plain(section(sources, "odds-t-h"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_rows_keep_the_recorded_order_and_selection(production):
    targets = d.Context(production).odds_targets.value
    assert [t.target_utc for t in targets.upcoming] == sorted(t.target_utc for t in targets.upcoming)
    assert all(parse <= NOW for parse in (datetime.fromisoformat(t.target_utc.replace("Z", "+00:00"))
                                           for t in targets.recent))
    assert json.dumps([t.target_id for t in targets.rows]) == json.dumps(
        [t.target_id for t in sorted(targets.rows, key=lambda t: (t.target_utc, t.priority, t.event_id))])
    assert replace(targets.rows[0]) == targets.rows[0]
