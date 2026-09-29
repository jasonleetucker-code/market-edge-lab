"""EXP-002 A.C timing calibration (`edge_lab.exp002_timing`): label-free, logged first, PROPOSED input only.

Offline, SYNTHETIC only (fixture stores; no production data, no network). Pinned here:
- window fractions of due T-6h pairs and the A.C step 3 rule (inclusive limits, the narrowness order, no qualifier);
- short-interval drift pairs (same market and horizon, within 15 min, by the target's cutoff only);
- label safety: no T-60m target, book or availability and no settlement is read (a payload spy), and the output is
  identical with or without T-60m data present;
- the CLI refuses without log arguments and records the look before anything is printed; deterministic output.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import exp002_timing as tm
from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.odds_schedule import deadline, effective_due, iso_z
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
D = Decimal
TEAMS = list(se.NFL_TEAMS)
KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
DELTA = D("0.01")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    monkeypatch.setattr(se, "_clock", lambda: datetime(2026, 11, 1, tzinfo=UTC))


def _book(ask: str, bid: str, size: str = "40") -> dict:
    return {"orderbook_fp": {"yes_dollars": [[f"{D(bid):.4f}", "30.00"]],
                             "no_dollars": [[f"{1 - D(ask):.4f}", f"{D(size):.2f}"]]}}


# Per game: the T-6h (and T-24h) book offset from the odds receipt, in seconds.
SKEWS = (60, 8 * 60, -7 * 60, 12 * 60)


def build_store(tmp_path: Path, *, labels: bool, name: str | None = None, repeat_change: str = "0.00",
                skews: tuple[int, ...] = SKEWS, outside: bool = False, t24_repeat: bool = False
                ) -> tuple[Path, datetime, dict]:
    """Four games in one NFL week. T-24h and T-6h odds are captured; each team market gets one book of that horizon
    at the game's skew. The home market of game 0 gets a repeat book 5 min after its first T-6h book (its ask and
    bid moved by `repeat_change`). `labels=True` adds T-60m odds captures, T-60m books and settled listings: none of
    it may change the output. `outside` adds a fully captured game kicking off 2026-10-25 (after the pilot weeks);
    `t24_repeat` gives game 0's home market an unchanged repeat book 5 min after its T-24h book."""
    games = [sf.Game(f"fxtm{i:02d}", TEAMS[2 * i], TEAMS[2 * i + 1], KICKOFF + timedelta(hours=3 * (i % 2)), D("0.60"))
             for i in range(len(skews))]
    now = max(g.commence for g in games) + timedelta(hours=8)
    early = min(g.commence for g in games) - timedelta(hours=2)  # T-24h and T-6h due, T-60m not yet
    store = SnapshotStore(tmp_path / (name or ("tm-labels.sqlite3" if labels else "tm-clean.sqlite3")))
    if outside:
        # One fixture run: the pilot games' T-60m odds are then captured too (never read by the tool).
        late_game = sf.Game("fxtmout", TEAMS[20], TEAMS[21], datetime(2026, 10, 25, 17, 0, tzinfo=UTC), D("0.60"))
        sf.write_pairing_fixture(store, games=games + [late_game], now=late_game.commence - timedelta(hours=2),
                                 books=False, settle=False)
        games_all = games + [late_game]
        skews = tuple(skews) + (60,)
        now = late_game.commence + timedelta(hours=8)
    else:
        sf.write_pairing_fixture(store, games=games, now=early, books=False, settle=False)
        games_all = games
    cfg = se.PILOT_CONFIG
    run = "SYNTHETIC-timing"
    store.start_run(run)
    ids = {"t60m_books": set(), "horizon_books": set(), "late_books": set()}
    by_event = {g.event_id: (g, s) for g, s in zip(games_all, skews)}
    for t in store.odds_targets(sport=se.SPORT):
        g, skew = by_event[t["event_id"]]
        target = se._capture_target(dict(t))
        if t["offset_label"] == "T-60m":
            if not labels or t["state"] == "CAPTURED":
                continue
            received = effective_due(target, cfg) + timedelta(seconds=40)
            sid = store.save_snapshot(run_id=run, source="the_odds_api", kind="odds", entity_id=se.SPORT, url=sf.ODDS_URL,
                                      payload={"sport": se.SPORT, "events": [sf._odds_event(g, received)],
                                               "request": {"purpose": "capture", "odds_format": "american"}},
                                      fetched_at_utc=iso_z(received), source_id="the_odds_api")
            store.record_odds_transition(target_id=t["target_id"], state="CAPTURED", at_utc=iso_z(received),
                                         snapshot_id=sid, captured_at_utc=iso_z(received), credits_last=1)
            for team in (g.home, g.away):
                ticker = f"{sf.event_ticker(g)}-{se.NFL_TEAMS[team][0]}"
                bsid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                           url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                           payload=_book("0.80", "0.70"), fetched_at_utc=iso_z(received + timedelta(seconds=60)),
                                           source_id="kalshi_public")
                ids["t60m_books"].add(bsid)
            continue
        received = se.parse_utc(t["captured_at_utc"])
        for team in (g.home, g.away):
            ticker = f"{sf.event_ticker(g)}-{se.NFL_TEAMS[team][0]}"
            at = received + timedelta(seconds=skew)
            sid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                      url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                      payload=_book("0.61", "0.59"), fetched_at_utc=iso_z(at), source_id="kalshi_public")
            ids["horizon_books"].add(sid)
            if t["offset_label"] == "T-24h" and t24_repeat and g is games[0] and team == g.home:
                rsid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                           url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                           payload=_book("0.61", "0.59"),
                                           fetched_at_utc=iso_z(at + timedelta(minutes=5)), source_id="kalshi_public")
                ids["horizon_books"].add(rsid)
            if t["offset_label"] == "T-6h" and g is games[0] and team == g.home:
                moved = D(repeat_change)
                rsid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                           url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                           payload=_book(str(D("0.61") + moved), str(D("0.59") + moved)),
                                           fetched_at_utc=iso_z(at + timedelta(minutes=5)), source_id="kalshi_public")
                ids["horizon_books"].add(rsid)
            if t["offset_label"] == "T-6h" and labels:
                # a book after the T-6h cutoff but before T-60m: never read
                late = deadline(target, cfg) + timedelta(minutes=10)
                lsid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                           url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                           payload=_book("0.95", "0.90"), fetched_at_utc=iso_z(late),
                                           source_id="kalshi_public")
                ids["late_books"].add(lsid)
    if labels:
        for g in games:
            store.save_snapshot(run_id=run, source=se.KALSHI, kind="markets", entity_id=sf.event_ticker(g),
                                url=f"{sf.KALSHI_API}/markets?event_ticker={sf.event_ticker(g)}",
                                payload={"markets": [sf._market(g, g.home, status="finalized", result="yes"),
                                                     sf._market(g, g.away, status="finalized", result="no")],
                                         "cursor": ""},
                                fetched_at_utc=iso_z(g.commence + timedelta(hours=5)), source_id="kalshi_public")
    store.finish_run(run, status="succeeded")
    return store.path, now, ids


def calibrate(path: Path, now: datetime, delta: Decimal = DELTA) -> dict:
    return tm.calibrate(SnapshotStore.open_readonly(path), as_of=now, delta_min=delta)


def _window(out: dict, name: str) -> dict:
    return next(w for w in out["windows_tried"] if w["window"] == name)


# ================================================================== windows, drift and the rule


def test_window_fractions_of_due_t6h_pairs_and_the_recommendation(tmp_path):
    path, now, _ = build_store(tmp_path, labels=False)
    out = calibrate(path, now)
    assert out["label"] == tm.LABEL == "PROPOSED calibration input, not a freeze"
    assert [w["window"] for w in out["windows_tried"]] == ["[-5,+5]", "[-5,+10]", "[-10,+15]"]
    # skews +1, +8, -7, +12 min, both sides of each game: 8 due T-6h pairs
    a, b, c = (_window(out, n) for n in ("[-5,+5]", "[-5,+10]", "[-10,+15]"))
    assert (a["t6h_due_pairs"], a["t6h_kept"], a["t6h_kept_fraction"]) == (8, 2, 0.25)
    assert (b["t6h_kept"], b["t6h_lost"], b["t6h_kept_fraction"]) == (4, 4, 0.5)
    assert (c["t6h_kept"], c["t6h_kept_fraction"]) == (8, 1.0)
    assert c["t24h_kept_fraction"] == 1.0 and a["t24h_kept_fraction"] == 0.25
    # the one repeat pair (5 min apart, no price change) is inside every window's gap
    assert all(w["drift"]["pairs"] == 1 and w["drift"]["median_abs"] == 0 for w in out["windows_tried"])
    assert [w["qualifies"] for w in out["windows_tried"]] == [False, False, True]
    rec = out["recommendation"]
    assert rec["window"] == "[-10,+15]" and rec["basis"] == "QUALIFIED" and rec["kept_fraction"] == 1.0
    assert out["inputs"]["delta_min"] == "0.01" and out["inputs"]["drift_limit"] == pytest.approx(0.01 / 3)
    assert "count against" in out["variant_budget"] and "3 windows" in out["variant_budget"]
    assert out["exposure_caveat"].startswith("T-60m book prices possibly seen (UNKNOWN, unlogged Terminal display)")


def test_drift_above_a_third_of_delta_min_fails_every_window_and_falls_back(tmp_path):
    path, now, _ = build_store(tmp_path, labels=False, repeat_change="0.01")  # mid moves 1 cent in 5 min
    out = calibrate(path, now)
    assert all(w["drift"]["median_abs"] == pytest.approx(0.01) for w in out["windows_tried"])
    assert not any(w["qualifies"] for w in out["windows_tried"])
    rec = out["recommendation"]
    assert rec["window"] == "[-5,+10]" and rec["basis"] == "NO_QUALIFIER_FALLBACK"
    assert rec["attrition"] == {"due_pairs": 8, "lost": 4} and "option" in rec["note"] and "(b)" in rec["note"]
    # delta_min is an input: with 3 cents the same drift (1 cent = delta_min/3) qualifies, inclusively
    loose = calibrate(path, now, D("0.03"))
    assert loose["recommendation"]["window"] == "[-10,+15]" and loose["inputs"]["delta_min"] == "0.03"


def test_the_rule_is_inclusive_at_both_limits_and_fails_closed_without_data():
    assert tm.window_verdict(10, 7, 0.0, DELTA) == []  # exactly 70% kept
    assert tm.window_verdict(10, 6, 0.0, DELTA) == ["KEEPS 6/10 < 70%"]
    assert tm.window_verdict(10, 10, 0.005, D("0.015")) == []  # drift exactly delta_min / 3
    assert tm.window_verdict(10, 10, 0.0055, D("0.015"))[0].startswith("MEDIAN_DRIFT")
    assert tm.window_verdict(0, 0, 0.0, DELTA) == ["NO_DUE_T6H_PAIRS"]
    assert tm.window_verdict(10, 10, None, DELTA)[0].startswith("DRIFT_UNKNOWN")


def test_the_narrowest_qualifier_wins_and_equal_widths_break_by_the_smaller_after_side():
    def row(name, before, after, ok):
        return {"window": name, "before_min": before, "after_min": after, "width_min": before + after,
                "qualifies": ok, "t6h_kept_fraction": 0.9, "drift": {"median_abs": 0.0}, "t6h_due_pairs": 10,
                "t6h_lost": 1}
    rows = [row("[-10,+15]", 10, 15, True), row("[-10,+5]", 10, 5, True), row("[-5,+10]", 5, 10, True),
            row("[-5,+5]", 5, 5, False)]
    assert tm.recommend(rows, delta_min=DELTA)["window"] == "[-10,+5]"  # width 15 ties [-5,+10]; after 5 < 10
    assert tm.recommend([row("[-5,+5]", 5, 5, False)], delta_min=DELTA)["basis"] == "NO_QUALIFIER_FALLBACK"


def test_drift_pairs_are_same_market_same_horizon_within_15_min_and_by_the_cutoff(tmp_path):
    path, now, ids = build_store(tmp_path, labels=True)
    obs = tm.timing_observations(SnapshotStore.open_readonly(path), as_of=now)
    assert [(d["horizon"], d["gap_s"]) for d in obs["drift"]] == [("T-6h", 300)]
    # the late book (after the T-6h cutoff) is never paired, read or counted
    assert not set(obs["books_read"]) & ids["late_books"]


def test_distributions_report_skew_ages_spread_and_depth(tmp_path):
    path, now, _ = build_store(tmp_path, labels=False)
    d6 = calibrate(path, now)["distributions"]["T-6h"]
    assert d6["nearest_book_skew_seconds"]["n"] == 8 and d6["nearest_book_skew_seconds"]["min"] == -420
    # at the fallback window [-5,+10] only the +1 and +8 min books are chosen
    assert d6["skew_seconds_chosen_book_at_fallback_window"]["n"] == 4
    assert d6["book_age_at_decision_seconds"]["max"] == 0 and d6["odds_age_at_decision_seconds"]["max"] == 480
    assert d6["odds_book_last_update_age_seconds"]["median"] == 120  # the fixture's books update 2 min earlier
    assert d6["spread"]["median"] == pytest.approx(0.02) and d6["displayed_ask_depth"]["median"] == 40


# ================================================================== label safety


def _spy_reads(monkeypatch) -> list[int]:
    """Every snapshot id read through `_Payloads` (payloads and rows: odds snapshots are loaded by `row`)."""
    loaded: list[int] = []
    original_row = se._Payloads.row
    monkeypatch.setattr(se._Payloads, "row", lambda self, sid: (loaded.append(sid), original_row(self, sid))[1])
    return loaded


def _t60m_odds_ids(path: Path) -> set[int]:
    return {int(r["snapshot_id"]) for r in SnapshotStore.open_readonly(path).odds_targets(sport=se.SPORT)
            if r["offset_label"] == "T-60m" and r["snapshot_id"] is not None}


def test_the_read_spy_catches_a_t60m_odds_read(tmp_path, monkeypatch):
    """The spy is not vacuous: an odds read through the consensus (it uses `_Payloads.row`) is recorded."""
    path, now, _ = build_store(tmp_path, labels=True)
    loaded = _spy_reads(monkeypatch)
    t60 = _t60m_odds_ids(path)
    se._Consensus(se._Payloads(SnapshotStore.open_readonly(path))).snapshot(min(t60))
    assert set(loaded) & t60


def test_no_t60m_book_later_book_or_settlement_is_read(tmp_path, monkeypatch):
    path, now, ids = build_store(tmp_path, labels=True)
    loaded = _spy_reads(monkeypatch)
    calls: list[str] = []
    for name in ("_first_book", "outcome_for", "_e1_settlement", "_e1_exit", "e1_endpoint", "markout_endpoint", "_join"):
        real = getattr(se, name)
        monkeypatch.setattr(se, name, lambda *a, _n=name, _r=real, **k: (calls.append(_n), _r(*a, **k))[1])
    drops: list[tuple] = []
    real_catalog = se.kalshi_catalog
    monkeypatch.setattr(se, "kalshi_catalog", lambda store, as_of, payloads, drop_fields=(): (
        drops.append(tuple(drop_fields)), real_catalog(store, as_of, payloads, drop_fields))[1])
    captured_odds = _t60m_odds_ids(path)
    out = calibrate(path, now)
    assert not calls and drops == [se.SETTLED_LISTING_FIELDS]
    assert captured_odds and not set(loaded) & (ids["t60m_books"] | ids["late_books"] | captured_odds)
    text = json.dumps(out)
    for word in ("T-60m\"", "settlement_value", "\"result\"", "expiration_value", "markout", "gross_", "exit"):
        assert word not in text, word


def test_the_output_is_identical_with_or_without_t60m_data(tmp_path):
    with_labels, now, _ = build_store(tmp_path, labels=True)
    without, now2, _ = build_store(tmp_path, labels=False)
    assert now == now2
    assert calibrate(with_labels, now) == calibrate(without, now)


def test_the_calibration_is_deterministic(tmp_path):
    path, now, _ = build_store(tmp_path, labels=True)
    a, b = calibrate(path, now), calibrate(path, now)
    assert a == b and a["output_sha256"] == b["output_sha256"]
    assert calibrate(path, now, D("0.02"))["output_sha256"] != a["output_sha256"]


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        tm.calibrate(None, as_of=datetime(2026, 10, 1), delta_min=DELTA)  # naive
    for bad in (D("0"), D("1"), 0.01):
        with pytest.raises(ValueError):
            tm.calibrate(None, as_of=datetime(2026, 10, 1, tzinfo=UTC), delta_min=bad)


# ================================================================== CLI: logged before shown


def _registry_copy(tmp_path: Path) -> tuple[Path, Path]:
    src = next((REPO / "experiments").glob("EXP-002-*"))
    root = tmp_path / "experiments"
    shutil.copytree(src, root / src.name)
    return root, root / src.name / "evidence_use.jsonl"


def _run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = se.main(argv)
    return code, buf.getvalue()


def test_cli_refuses_without_log_arguments_and_shows_nothing(tmp_path, monkeypatch):
    path, now, _ = build_store(tmp_path, labels=False)
    root, own = _registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    monkeypatch.delenv("EDGE_LAB_CODE_VERSION", raising=False)
    base = ["exp002-timing", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root), "--delta-min", "0.01"]
    for extra in ([], ["--evidence-log", str(own)], ["--evidence-log", str(own), "--actor", "t"],
                  ["--actor", "t", "--code-version", "abc"]):
        code, text = _run(base + extra)
        assert code == 2 and json.loads(text)["state"] == "REFUSED" and "windows_tried" not in text
    # a record that fails (not EXP-002's own log) shows nothing either
    other = tmp_path / "other.jsonl"
    code, text = _run(base + ["--evidence-log", str(other), "--actor", "t", "--code-version", "abc"])
    assert code == 2 and json.loads(text)["state"] == "REFUSED" and "windows_tried" not in text
    assert len(rev.read_log(own).uses) == before


def test_cli_records_a_feature_inspection_before_printing(tmp_path, monkeypatch):
    path, now, _ = build_store(tmp_path, labels=False)
    root, own = _registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    printed_at_record: list[str] = []
    real = tm.record_timing_view

    def spy(*a, **k):
        printed_at_record.append(sys.stdout.getvalue())
        return real(*a, **k)

    monkeypatch.setattr(tm, "record_timing_view", spy)
    code, text = _run(["exp002-timing", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root),
                       "--delta-min", "0.01", "--evidence-log", str(own), "--actor", "test", "--code-version", "abc123"])
    assert code == 0 and printed_at_record == [""]
    shown = json.loads(text)
    assert shown["evidence_use"] == "APPENDED" and shown["recommendation"]["window"] == "[-10,+15]"
    uses = rev.read_log(own).uses
    assert len(uses) == before + 1
    use = uses[-1]
    assert use.action is rev.Action.FEATURE_INSPECTION and use.role is rev.DatasetRole.DEVELOPMENT
    assert use.viewed_features is True and use.viewed_labels is False and use.viewed_results is False
    assert use.influenced_tuning is True  # it informs a PROPOSED join limit
    assert use.window.scope == "sports:nfl:moneyline" and use.dataset_sha256 == shown["output_sha256"]
    assert use.window.start_utc == shown["coverage"]["first_kickoff_utc"]
    assert use.window.end_utc == shown["coverage"]["last_kickoff_utc"]
    assert tm.TIMING_VERSION in use.note and "T-60m book prices possibly seen" in use.note


# ================================================================== review fixes (#142)


def test_games_outside_the_pilot_weeks_are_ignored_and_never_logged(tmp_path, monkeypatch):
    path, now, _ = build_store(tmp_path, labels=False, outside=True)
    loaded = _spy_reads(monkeypatch)
    out = calibrate(path, now)
    read_here = set(loaded)  # before any other store is read (snapshot ids are per store)
    assert out["inputs"]["pilot_kickoffs_et"]["first"] == "2026-09-27"
    assert out["inputs"]["pilot_kickoffs_et"]["last"] == "2026-10-19"
    assert out["coverage"]["games"] == 4 and out["coverage"]["last_kickoff_utc"] < "2026-10-20"
    assert "fxtmout" not in json.dumps(out)
    clean, _, _ = build_store(tmp_path, labels=False, name="tm-clean-2.sqlite3")
    assert {k: v for k, v in calibrate(clean, now).items() if k not in ("as_of_utc", "output_sha256")} == {
        k: v for k, v in out.items() if k not in ("as_of_utc", "output_sha256")}
    outside_odds = {int(r["snapshot_id"]) for r in SnapshotStore.open_readonly(path).odds_targets(sport=se.SPORT)
                    if r["event_id"] == "fxtmout" and r["snapshot_id"] is not None}
    assert outside_odds and not read_here & outside_odds
    root, own = _registry_copy(tmp_path)
    code, text = _run(["exp002-timing", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root),
                       "--delta-min", "0.01", "--evidence-log", str(own), "--actor", "t", "--code-version", "abc"])
    assert code == 0
    use = rev.read_log(own).uses[-1]
    assert use.window.end_utc < "2026-10-20" and "fxtmout" not in text


def test_last_update_ages_are_collected_even_when_a_book_is_stale(tmp_path, monkeypatch):
    real = sf._odds_event

    def stale(g, received):
        ev = real(g, received)
        if g.event_id == "fxtm00":  # one game's books last updated 15 min before receipt: not fresh
            stamp = iso_z(received - timedelta(minutes=15))
            for book in ev["bookmakers"]:
                book["last_update"] = stamp
                for m in book["markets"]:
                    m["last_update"] = stamp
        return ev

    monkeypatch.setattr(sf, "_odds_event", stale)
    path, now, _ = build_store(tmp_path, labels=False)
    out = calibrate(path, now)
    ages = out["distributions"]["T-6h"]["odds_book_last_update_age_seconds"]
    assert ages["max"] == 900 and ages["n"] == 12  # 4 games x 3 books, the stale game included
    by = out["coverage"]["by_horizon"]["T-6h"]
    assert by["odds_not_fresh"] == 1 and by["sides_lost_upstream"] == 2 and by["odds_not_captured"] == 0
    w = _window(out, "[-10,+15]")
    assert w["t6h_due_pairs"] == 6 and w["t6h_all_due_sides"] == 8 and w["t6h_kept_over_all_due_sides"] == 6 / 8


def test_t24h_drift_is_descriptive_and_never_decides_the_rule(tmp_path):
    base, now, _ = build_store(tmp_path, labels=False, repeat_change="0.01")
    both, _, _ = build_store(tmp_path, labels=False, repeat_change="0.01", t24_repeat=True, name="tm-t24.sqlite3")
    a, b = calibrate(base, now), calibrate(both, now)
    assert a["recommendation"]["basis"] == b["recommendation"]["basis"] == "NO_QUALIFIER_FALLBACK"
    wb = _window(b, "[-10,+15]")
    assert wb["drift"]["horizon"] == "T-6h" and wb["drift"]["median_abs"] == pytest.approx(0.01)
    assert wb["drift"]["t24h_descriptive"] == {"pairs": 1, "median_abs": 0.0}
    assert b["short_interval_drift"]["T-24h"]["abs_mid_change"]["n"] == 1


def test_a_truncated_catalog_refuses_with_no_counts(tmp_path, monkeypatch):
    path, now, _ = build_store(tmp_path, labels=True)
    monkeypatch.setattr(se, "MAX_KALSHI_ROWS", 5)
    with pytest.raises(tm.TimingRefused):
        calibrate(path, now)
    root, own = _registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    code, text = _run(["exp002-timing", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root),
                       "--delta-min", "0.01", "--evidence-log", str(own), "--actor", "t", "--code-version", "abc"])
    out = json.loads(text)
    assert code == 2 and out["state"] == "REFUSED" and "windows_tried" not in text and "TRUNCATED" not in text
    assert not re.search(r"\d", out["detail"].replace("T-60m", "").replace("T-24h", ""))  # no count leaks
    assert len(rev.read_log(own).uses) == before  # nothing shown, nothing logged
