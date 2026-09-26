"""Family A paired evidence (Economic Evidence v1, PR C): join, mapping, rules, attrition, gaps, economics.

Fixtures only, zero network: the recorded Kalshi KXNFLGAME listing (tests/fixtures/sports_evidence/, read
2026-09-25 under the owner's bounded-verification allowance) and SYNTHETIC stores written through the real
store APIs (`edge_lab.dashboard.sports_fixtures`).
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import sports_evidence as se
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.odds_schedule import iso_z
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FIX = Path(__file__).parent / "fixtures" / "sports_evidence"
REPO = Path(__file__).resolve().parents[1]
EVENTS = FIX / "kalshi_events_KXNFLGAME_open_2026-09-25T022444Z.json"
SERIES = FIX / "kalshi_series_KXNFLGAME_2026-09-25T022448Z.json"
LISTED_AT = datetime(2026, 9, 25, 2, 24, 44, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    """The SYNTHETIC stores live in late September 2026; the CLI clamps --as-of to its clock."""
    monkeypatch.setattr(se, "_clock", lambda: datetime(2026, 10, 10, tzinfo=timezone.utc))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("sports_evidence attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def report(path: Path, as_of: datetime, results: bool = True, **policy) -> dict:
    """Research assertions below look at outcome labels, so they opt in (a real run must be logged)."""
    return se.build_report(SnapshotStore.open_readonly(path), as_of=as_of, policy=se.JoinPolicy(**policy),
                           results=results)


def rows_by(rep: dict) -> dict[tuple[str, str], dict]:
    return {(r["event_id"], r["horizon"]): r for r in rep["rows"]}


@pytest.fixture(scope="module")
def populated(tmp_path_factory):
    return sf.fixture_store(tmp_path_factory.mktemp("populated"))


@pytest.fixture(scope="module")
def issues(tmp_path_factory):
    return sf.fixture_store(tmp_path_factory.mktemp("issues"), issues=True)


# ================================================================== recorded Kalshi evidence


def test_recorded_fixtures_match_the_request_log_byte_for_byte():
    log = json.loads((FIX / "request_log_2026-09-25.json").read_text(encoding="utf-8"))
    sent = [a for a in log["attempts"] if a["sent"]]
    assert log["requests_sent"] == len(sent) == 2
    for a in sent:
        assert hashlib.sha256((FIX / a["file"]).read_bytes()).hexdigest() == a["sha256"]


def test_recorded_rules_parse_literally_into_a_conditional_mapping():
    payload = json.loads(EVENTS.read_text(encoding="utf-8"))
    markets = [m for e in payload["events"] for m in e["markets"]]
    assert len(payload["events"]) == 32 and len(markets) == 64 and payload["cursor"] == ""
    gb = next(m for m in markets if m["ticker"] == "KXNFLGAME-26SEP24ATLGB-GB")
    clauses = se.rules_clauses(gb["rules_primary"], gb["rules_secondary"])
    assert clauses["resolved"] and clauses["tie_payout"] == "0.50"
    assert clauses["postponement_window_hours"] == 48 and clauses["not_started_fallback"] == "FAIR_PRICE_AFTER_48H"
    assert clauses["overtime"] == "UNSTATED" and clauses["originally_scheduled"] == "Sep 24, 2026"
    rel = se.relation_for(gb, clauses)
    assert rel["tier"] == se.REL_CONDITIONAL and rel["equivalent"] is False
    # every recorded market carries the same recognised clauses
    assert all(se.rules_clauses(m["rules_primary"], m["rules_secondary"])["resolved"] for m in markets)
    series = json.loads(SERIES.read_text(encoding="utf-8"))["series"]
    assert series["fee_type"] == "quadratic_with_maker_fees" and series["settlement_sources"][0]["name"] == \
        "the Governing League"


def test_every_recorded_ticker_parses_and_every_team_is_in_the_table():
    payload = json.loads(EVENTS.read_text(encoding="utf-8"))
    for e in payload["events"]:
        teams = set()
        for m in e["markets"]:
            p = se.parse_ticker(m["ticker"])
            assert p is not None and p["event_ticker"] == e["event_ticker"]
            name = se._BY_ABBR[p["team"]]
            assert se.NFL_TEAMS[name][1] == m["yes_sub_title"]
            teams.add(p["team"])
        assert len(teams) == 2 and {p for p in teams} == {se.parse_ticker(m["ticker"])["team"] for m in e["markets"]}


def _recorded_store(tmp_path, *, complete=True) -> Path:
    store = SnapshotStore(tmp_path / "rec.sqlite3")
    store.start_run("rec")
    payload = json.loads(EVENTS.read_text(encoding="utf-8"))
    if not complete:
        payload["cursor"] = "NEXT"
    store.save_snapshot(run_id="rec", source="kalshi", kind="events", entity_id="KXNFLGAME",
                        url="https://external-api.kalshi.com/trade-api/v2/events?series_ticker=KXNFLGAME",
                        payload=payload, fetched_at_utc=iso_z(LISTED_AT), source_id="kalshi_public")
    return store.path


def test_mapping_over_the_recorded_listing(tmp_path):
    store = SnapshotStore.open_readonly(_recorded_store(tmp_path))
    catalog = se.kalshi_catalog(store, LISTED_AT + timedelta(days=3), se._Payloads(store))
    later = LISTED_AT + timedelta(days=1)
    kick = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
    m = se.map_event("Miami Dolphins", "Kansas City Chiefs", kick, catalog, later)
    assert m["state"] == "MAPPED" and m["event_ticker"] == "KXNFLGAME-26SEP27KCMIA"
    assert m["checks"]["home_away"]["state"] == "MATCH"  # KC away, MIA home: the ticker lists away first
    assert {o.ticker for o in m["markets"].values()} == {"KXNFLGAME-26SEP27KCMIA-KC", "KXNFLGAME-26SEP27KCMIA-MIA"}
    # swapped home/away is recorded, not hidden
    assert se.map_event("Kansas City Chiefs", "Miami Dolphins", kick, catalog, later)["checks"]["home_away"]["state"] \
        == "DIFFERS"
    # a date the ticker does not carry, within a week: ambiguous (rescheduled?), never forced
    assert se.map_event("Miami Dolphins", "Kansas City Chiefs", kick + timedelta(days=2), catalog, later)["state"] \
        == "AMBIGUOUS"
    # teams Kalshi does not list together, in a complete listing: unmatched
    assert se.map_event("Miami Dolphins", "Green Bay Packers", kick, catalog, later)["state"] == "UNMATCHED"
    # an unknown name never maps
    assert se.map_event("Miami Dolphins", "KC Chiefs", kick, catalog, later)["state"] == "UNMATCHED"
    # before the listing was received nothing is known
    assert se.map_event("Miami Dolphins", "Kansas City Chiefs", kick, catalog, LISTED_AT - timedelta(seconds=1))[
        "state"] == "NO_LISTING"


def test_a_partial_listing_never_implies_no_market(tmp_path):
    store = SnapshotStore.open_readonly(_recorded_store(tmp_path, complete=False))
    catalog = se.kalshi_catalog(store, LISTED_AT + timedelta(days=3), se._Payloads(store))
    kick = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
    out = se.map_event("Miami Dolphins", "Green Bay Packers", kick, catalog, LISTED_AT + timedelta(days=1))
    assert out["state"] == "NOT_IN_LISTINGS_READ" and "not evidence that no market exists" in out["reasons"][0]


# ================================================================== pure helpers


def test_ticker_and_week_cluster():
    assert se.parse_ticker("KXNFLGAME-26SEP24ATLGB-GB") == {
        "event_ticker": "KXNFLGAME-26SEP24ATLGB", "date": datetime(2026, 9, 24).date(), "letters": "ATLGB", "team": "GB"}
    assert se.parse_ticker("KXNFLGAME-26XYZ24ATLGB-GB") is None and se.parse_ticker("KXHIGHNY-26SEP24-B67.5") is None
    thursday = datetime(2026, 9, 25, 0, 15, tzinfo=UTC)  # Thursday night ET
    monday = datetime(2026, 9, 29, 0, 15, tzinfo=UTC)  # Monday night ET
    next_thursday = datetime(2026, 10, 2, 0, 15, tzinfo=UTC)
    assert se.week_cluster(thursday) == se.week_cluster(monday) == "nfl-week-of-2026-09-22"
    assert se.week_cluster(next_thursday) != se.week_cluster(monday)


def test_tie_adjusted_interval_is_exact_at_the_corners_and_unknown_without_bounds():
    p, half = Decimal("0.6"), Decimal("0.5")
    assert se.tie_adjusted_interval(p, half, None, Decimal("0.01")) is None
    assert se.tie_adjusted_interval(p, half, Decimal("0.01"), None) is None
    assert se.tie_adjusted_interval(p, half, Decimal(0), Decimal(0)) == (p, p)
    lo, hi = se.tie_adjusted_interval(p, half, Decimal("0.004"), Decimal("0.002"))
    # low: t = 0.004 pulls toward 0.5, u = 0.002 with F = 0; high: t = 0, u = 0.002 with F = 1
    assert lo == (1 - Decimal("0.006")) * p + half * Decimal("0.004")
    assert hi == (1 - Decimal("0.002")) * p + Decimal("0.002")
    assert lo < p < hi


def test_policy_validates_its_inputs():
    with pytest.raises(ValueError):
        se.JoinPolicy(tie_probability_bound=Decimal("1.5"))
    with pytest.raises(ValueError):
        se.JoinPolicy(size_ladder=(Decimal(0),))
    with pytest.raises(ValueError):
        se.JoinPolicy(max_book_after_odds=timedelta(0))
    with pytest.raises(ValueError):
        se.JoinPolicy(max_book_before_odds=timedelta(seconds=-1))
    with pytest.raises(ValueError):
        se.build_report(None, as_of=datetime(2026, 9, 27))  # naive as_of refused


T0 = datetime(2026, 9, 27, 11, 0, 40, tzinfo=UTC)
START, CUTOFF = T0 - timedelta(minutes=8), T0 + timedelta(minutes=30)


def _b(seconds, sid):
    return (T0 + timedelta(seconds=seconds), sid, "u", "h")


def _pick(books):
    return se.pick_book(books, T0, START, CUTOFF)  # join v2 defaults: 5 min before, 10 min after


def test_pick_book_is_point_in_time_and_never_substitutes():
    assert se.JOIN_VERSION == "sports-paired-join-v2" and se.JoinPolicy().to_dict()["book_choice"] == se.BOOK_CHOICE
    assert _pick([_b(-60, 1), _b(60, 2)])[0][1] == 1  # a book at or before the odds wins over a later one
    assert _pick([_b(-240, 1), _b(-30, 2)])[0][1] == 2  # the latest of the earlier books
    assert _pick([_b(0, 7)])[0][1] == 7  # a book received at the odds receipt counts as at-or-before
    assert _pick([_b(9 * 60, 1), _b(90, 2)])[0][1] == 2  # else the first book after the odds
    none, why, later = _pick([_b(40 * 60, 3)])
    assert none is None and later == 1 and why.startswith("KALSHI_BOOK_MISSING") and "never substituted" in why
    none, why, _ = _pick([_b(-5 * 3600, 4)])
    assert none is None and why.startswith("KALSHI_BOOK_MISSING") and "other horizons" in why
    none, why, _ = _pick([_b(12 * 60, 5)])  # after the +10 min window
    assert none is None and why.startswith("PAIR_SKEW_EXCEEDED") and "+720 s" in why
    none, why, _ = _pick([_b(-6 * 60, 6)])  # before the -5 min window
    assert none is None and why.startswith("PAIR_SKEW_EXCEEDED")


def test_a_later_arriving_book_never_changes_a_qualifying_earlier_choice():
    # A book at or before the odds is chosen; every book that arrives after the odds receipt, however close, is
    # ignored. And once the first book after the odds qualifies, later ones never displace it.
    earlier = [_b(-200, 1)]
    for arrival in (1, 5, 60, 5 * 60, 9 * 60, 20 * 60, 29 * 60):
        assert _pick(earlier + [_b(arrival, 100 + arrival)])[0][1] == 1
    first_after = [_b(4 * 60, 2)]
    for arrival in (4 * 60 + 1, 5 * 60, 9 * 60, 10 * 60, 25 * 60):
        assert _pick(first_after + [_b(arrival, 200 + arrival)])[0][1] == 2
    # The v1 rule ("closest") would have taken the later, closer book here; v2 keeps the earlier one.
    assert _pick([_b(-240, 1), _b(10, 2)])[0][1] == 1


def test_the_choice_depends_only_on_books_received_by_the_decision():
    # Adding books after the chosen book's decision time (the later of the two receipts) never changes the pick.
    base = [_b(-100, 1), _b(-4000, 9)]
    choice = _pick(base)[0]
    for extra in ([_b(30, 3)], [_b(30, 3), _b(300, 4)], [_b(45 * 60, 5)]):
        assert _pick(base + extra)[0] == choice


# ================================================================== the join over SYNTHETIC stores


def test_populated_fixture_pairs_every_due_horizon(populated):
    path, now = populated
    rep = report(path, now)
    a = rep["join"]
    den = a["denominators"]
    assert den["targets_planned"] == 12 and den["targets_due"] == 9 and den["targets_not_yet_due"] == 3
    assert a["primary"]["PAIRED"] == 9 and sum(a["primary"].values()) == den["targets_due"]
    assert den["events"] == 4 and den["events_due"] == 3 and den["weeks_due"] == 1
    assert den["kalshi_markets_mapped"] == 6 and den["sides_paired"] == 18
    assert a["outcomes"]["OUTCOME_FINAL"] == 3 and a["outcomes"]["OUTCOME_PENDING"] == 6
    assert a["final_evaluable_targets"] == 3
    for key in ("signal", "no_signal", "fill", "no_fill"):
        assert a[key] is None  # not evaluated, never zero
    row = rows_by(rep)[("fxsyn001", "T-6h")]
    side = row["sides"]["Green Bay Packers"]
    assert side["pair_skew_seconds"] == 60 and side["decision_utc"] == side["book_received_utc"]
    assert side["decision_utc"] <= row["cutoff_utc"] and row["odds"]["received_utc"] <= row["cutoff_utc"]
    assert side["relation"]["tier"] == se.REL_CONDITIONAL and side["relation"]["equivalent"] is False
    assert side["tie_adjusted_fair_interval"] is None and side["comparison_claim"].startswith("NONE")
    assert Decimal(side["consensus_probability"]) > Decimal("0.7")
    assert side["observed_gap_unadjusted"] is not None
    assert row["outcome"]["Green Bay Packers"]["state"] == "OUTCOME_FINAL"
    assert row["outcome"]["Green Bay Packers"]["result"] == "YES"
    assert row["game_cluster"] == "fxsyn001" and row["week_cluster"] == "nfl-week-of-2026-09-22"
    # provenance of every input
    assert row["odds"]["snapshot_id"] and len(row["odds"]["input_sha256"]) == 64 and row["odds"]["consensus_version"]
    assert len(side["book_sha256"]) == 64 and len(side["rules_sha256"]) == 64 and len(side["listing_sha256"]) == 64


def test_capacity_ladder_uses_the_shared_size_ladder_with_unsupported_fees(populated):
    path, now = populated
    side = rows_by(report(path, now))[("fxsyn002", "T-60m")]["sides"]["Miami Dolphins"]
    ladder = {r["size"]: r for r in side["capacity"]}
    assert set(ladder) == {"1", "10", "25", "100", "250"}
    one, big = ladder["1"], ladder["250"]
    # research_economics.size_ladder_from_depth: the walk fills, but KXNFLGAME fees cannot be priced
    assert one["depth_status"] == "FILLABLE" and one["fee_status"] == "FEE_UNSUPPORTED"
    assert one["all_in_cost_per_unit"] is None and one["net_edge_per_unit"] is None and one["fillable"] is False
    # the complete captured ladder offers 40 + 80 + 120 = 240 < 250: insufficient, never extrapolated
    assert big["depth_status"] == "INSUFFICIENT_DEPTH" and "240.00 < 250" in big["detail"]
    assert side["depth_truncated"] is False and side["visible_depth"] == "240"
    assert side["lockup_hours"]["basis"] == "OBSERVED" and side["lockup_hours"]["expected"] > 0
    assert "_points" not in side and "_release" not in side  # private objects never reach the artifact


def test_issue_fixture_attrition_reconciles_with_every_reason_kept(issues):
    path, now = issues
    rep = report(path, now)
    a = rep["join"]
    assert sum(a["primary"].values()) == a["denominators"]["targets_due"] == 9
    assert a["primary"] == {**{s.value: 0 for s in se.Stage}, "ODDS_NOT_CAPTURED": 1, "PAIR_SKEW_EXCEEDED": 1,
                            "KALSHI_BOOK_MISSING": 1, "KALSHI_BOOK_UNUSABLE": 1, "PARTIAL_PAIR": 0, "PAIRED": 5}
    last = a["waterfall"][-1]
    assert last["remaining_after"] == a["primary"]["PAIRED"] + a["primary"]["PARTIAL_PAIR"]
    rows = rows_by(rep)
    assert rows[("fxsyn002", "T-6h")]["primary"] == "PAIR_SKEW_EXCEEDED"
    missing = rows[("fxsyn003", "T-60m")]
    assert missing["primary"] == "KALSHI_BOOK_MISSING" and "not substituted" in " ".join(missing["reasons"])
    assert "crossed book" in " ".join(rows[("fxsyn003", "T-6h")]["reasons"])
    shallow = rows[("fxsyn001", "T-60m")]["sides"]["Green Bay Packers"]
    assert shallow["depth_truncated"] is True
    big = {r["size"]: r for r in shallow["capacity"]}["250"]
    assert big["depth_status"] == "DEPTH_UNKNOWN"  # truncated capture: running out is unknown, not insufficient
    assert any(g["id"] == "G2" and g["state"] == "PARTIAL" for g in rep["gaps"])


def test_production_like_store_without_kalshi_evidence_reports_gaps_not_a_dataset(tmp_path):
    path, now = sf.fixture_store(tmp_path, kalshi=False)
    rep = report(path, now)
    assert rep["join"]["primary"]["KALSHI_NOT_MAPPED"] == 9 and rep["join"]["paired_targets"] == 0
    assert all(not r["sides"] for r in rep["rows"])
    gaps = {g["id"]: g for g in rep["gaps"]}
    assert set(gaps) == {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"} and gaps["G7"]["state"] == "DRAFT"
    assert gaps["G2"]["state"] == "MISSING" and gaps["G2"]["due_targets_without_book"] == 9
    assert gaps["G2"]["by_horizon"] == {"T-24h": 3, "T-60m": 3, "T-6h": 3}
    econ = rep["economics"]
    assert econ["state"] == "INSUFFICIENT_EVIDENCE" and econ["edge_at_size"]["state"] == "NOT_DEFENSIBLE"
    assert any(r.startswith("NO_PAIRED_EVIDENCE") for r in econ["edge_at_size"]["reasons"])
    assert {i["basis"] for i in econ["inputs"]} <= {"OBSERVED", "ESTIMATED", "OWNER_INPUT", "UNKNOWN"}
    view = se.view_from_report(rep, now)
    assert view["state"] == "UNPAIRED" and view["next_action"].startswith("Owner decision")
    assert "no new timer is authorized" in view["next_action"]


def test_not_yet_due_is_never_missed_and_superseded_is_its_own_bucket(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    store = SnapshotStore(path)
    t = next(r for r in store.odds_targets(sport=se.SPORT) if r["event_id"] == "fxsyn004" and r["offset_label"] == "T-24h")
    store.record_odds_transition(target_id=t["target_id"], state="SUPERSEDED", at_utc=iso_z(now - timedelta(minutes=5)),
                                 reason="SYNTHETIC: commence time changed")
    rep = report(path, now)
    den = rep["join"]["denominators"]
    assert den["targets_superseded"] == 1 and den["targets_not_yet_due"] == 2 and den["targets_due"] == 9
    fut = rows_by(rep)[("fxsyn004", "T-6h")]
    assert fut["status"] == "NOT_YET_DUE" and "not missed" in fut["reasons"][0] and not fut["sides"]


def test_replay_at_an_earlier_as_of_uses_only_what_was_known(populated):
    path, now = populated
    early = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)  # after G2 T-6h (11:00), before G2 T-60m (16:00)
    rep = report(path, early)
    rows = rows_by(rep)
    assert rows[("fxsyn002", "T-6h")]["status"] == "PAIRED"
    assert rows[("fxsyn002", "T-60m")]["status"] == "NOT_YET_DUE"
    side = rows[("fxsyn002", "T-6h")]["sides"]["Miami Dolphins"]
    assert side["markout_label_ref"] is None  # the later book was not received by as_of
    later = rows_by(report(path, now))[("fxsyn002", "T-6h")]["sides"]["Miami Dolphins"]["markout_label_ref"]
    assert later is not None and later["use"].startswith("LABEL_ONLY")
    assert rows[("fxsyn001", "T-60m")]["outcome"]["Green Bay Packers"]["state"] == "OUTCOME_FINAL"
    before_settlement = rows_by(report(path, datetime(2026, 9, 25, 4, 0, tzinfo=UTC)))
    assert before_settlement[("fxsyn001", "T-60m")]["outcome"]["Green Bay Packers"]["state"] == "OUTCOME_PENDING"


def test_a_capture_recorded_after_as_of_is_replayed_as_its_earlier_state(populated):
    path, _ = populated
    rows = SnapshotStore.open_readonly(path).odds_targets(sport=se.SPORT)
    t = next(r for r in rows if r["event_id"] == "fxsyn002" and r["offset_label"] == "T-6h")
    at = datetime.fromisoformat(t["captured_at_utc"].replace("Z", "+00:00"))
    rep = report(path, at - timedelta(seconds=1))
    row = rows_by(rep)[("fxsyn002", "T-6h")]
    # the cutoff has not passed at that instant either, so the horizon is not yet due
    assert row["status"] == "NOT_YET_DUE"


def test_reports_are_deterministic_and_hash_their_content(populated):
    path, now = populated
    a, b = report(path, now), report(path, now)
    assert a == b and a["output_sha256"] == b["output_sha256"]
    assert report(path, now + timedelta(minutes=1))["output_sha256"] != a["output_sha256"]
    assert report(path, now, max_book_after_odds=timedelta(minutes=2))["output_sha256"] != a["output_sha256"]


def test_declared_bounds_give_a_bounded_comparison_but_never_an_edge(populated):
    path, now = populated
    rep = report(path, now, tie_probability_bound=Decimal("0.005"), postponement_probability_bound=Decimal("0.002"))
    side = rows_by(rep)[("fxsyn002", "T-6h")]["sides"]["Miami Dolphins"]
    lo, hi = (Decimal(x) for x in side["tie_adjusted_fair_interval"])
    assert lo < Decimal(side["consensus_probability"]) < hi
    assert side["comparison_claim"].startswith("NONE")
    assert rep["economics"]["edge_at_size"]["state"] == "NOT_DEFENSIBLE"
    assert not any(g["id"] == "G5" for g in rep["gaps"])


def test_rules_or_payoff_problems_block_the_pair(tmp_path):
    path, now = sf.fixture_store(tmp_path / "a", tie_clause=False)
    rep = report(path, now)
    assert rep["join"]["primary"]["KALSHI_RULES_UNRESOLVED"] == 9
    assert "tie_payout" in " ".join(rows_by(rep)[("fxsyn001", "T-6h")]["reasons"])
    path, now = sf.fixture_store(tmp_path / "b", market_type="scalar")
    rep = report(path, now)
    tiers = {s["relation"]["tier"] for r in rep["rows"] for s in r["sides"].values()}
    assert tiers == {se.REL_PAYOFF_UNSUPPORTED} and se.view_from_report(rep, now)["state"] == "UNSUPPORTED"


def test_outcome_states_preliminary_corrected_and_unknown(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    store = SnapshotStore(path)
    g = sf.GAMES[1]
    tick = sf.event_ticker(g)
    store.start_run("SYNTHETIC-outcomes")

    def listing(at, home_status, home_result, away_result):
        store.save_snapshot(run_id="SYNTHETIC-outcomes", source="kalshi", kind="markets", entity_id=tick,
                            url=f"{sf.KALSHI_API}/markets?event_ticker={tick}",
                            payload={"markets": [sf._market(g, g.home, status=home_status, result=home_result),
                                                 sf._market(g, g.away, status=home_status, result=away_result)]},
                            fetched_at_utc=iso_z(at), source_id="kalshi_public")
    listing(g.commence + timedelta(hours=3), "determined", "yes", "no")
    assert rows_by(report(path, now))[("fxsyn002", "T-6h")]["outcome"]["Miami Dolphins"]["state"] == \
        "OUTCOME_PRELIMINARY"
    listing(now - timedelta(minutes=1), "finalized", "no", "yes")
    out = rows_by(report(path, now))[("fxsyn002", "T-6h")]["outcome"]["Miami Dolphins"]
    assert out["state"] == "OUTCOME_CORRECTED" and out["result"] == "NO" and "disagree" in out["detail"]
    g3 = sf.GAMES[2]
    store.save_snapshot(run_id="SYNTHETIC-outcomes", source="kalshi", kind="markets", entity_id=sf.event_ticker(g3),
                        url=f"{sf.KALSHI_API}/markets?event_ticker={sf.event_ticker(g3)}",
                        payload={"markets": [sf._market(g3, g3.home, status="finalized", result=""),
                                             sf._market(g3, g3.away, status="finalized", result="")]},
                        fetched_at_utc=iso_z(now - timedelta(minutes=1)), source_id="kalshi_public")
    tie = rows_by(report(path, now))[("fxsyn003", "T-6h")]["outcome"]["Washington Commanders"]
    assert tie["state"] == "OUTCOME_UNKNOWN" and "tie" in tie["detail"]


def test_a_book_whose_payload_does_not_match_its_hash_is_never_used(tmp_path):
    import sqlite3

    path, now = sf.fixture_store(tmp_path, books=False)
    row = rows_by(report(path, now))[("fxsyn002", "T-60m")]
    assert row["primary"] == "KALSHI_BOOK_MISSING"
    received = datetime.fromisoformat(row["odds"]["received_utc"].replace("Z", "+00:00")) + timedelta(seconds=60)
    ticker = row["kalshi"]["tickers"]["Miami Dolphins"]
    with sqlite3.connect(path) as conn:  # a book whose stored hash does not match its payload
        conn.execute("INSERT INTO snapshots(run_id, source, kind, entity_id, fetched_at_utc, url, payload_sha256, "
                     "payload_json) VALUES ('SYNTHETIC-pairing-fixture', 'kalshi', 'orderbook', ?, ?, 'u?depth=100', ?, ?)",
                     (ticker, iso_z(received), "0" * 64, json.dumps(sf._book(Decimal("0.42")))))
    side = rows_by(report(path, now))[("fxsyn002", "T-60m")]["sides"]["Miami Dolphins"]
    assert side["stage"] == "KALSHI_BOOK_UNUSABLE" and side["reasons"][0].startswith("PAYLOAD_HASH_MISMATCH")
    assert "yes_ask" not in side and "capacity" not in side


def test_polymarket_related_captures_are_listed_but_never_compared(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-pm")
    scan = {"scan_id": "SYNTHETIC-scan", "run_id": "SYNTHETIC-pm", "league": "nfl", "endpoint": "events",
            "started_at_utc": "2026-09-26T10:00:00Z", "completed_at_utc": "2026-09-26T10:00:05Z",
            "coverage_state": "PARTIAL", "filter_complete": 1, "pages_ok": 1, "requests": 1, "events": 1, "markets": 1,
            "coverage_detail": "SYNTHETIC", "page_snapshot_ids_json": "[]", "catalog_json": "[]",
            "anomalies_json": "[]", "parser_version": "x", "policy_version": "x"}
    store.record_pm_sports_scan(scan)
    target = {"target_id": "SYNTHETIC-pm-t", "league": "nfl", "market_slug": "synthetic-kc-mia",
              "odds_event_id": "fxsyn002", "relationship": "RELATED_NOT_EQUIVALENT", "relationship_json": "{}",
              "offset_label": "T-6h", "priority": 2, "game_start_utc": "2026-09-27T17:00:00Z",
              "target_utc": "2026-09-27T11:00:00Z", "effective_utc": "2026-09-27T11:00:00Z",
              "due_from_utc": "2026-09-27T10:53:00Z", "deadline_utc": "2026-09-27T11:30:00Z",
              "planned_at_utc": "2026-09-26T10:00:00Z", "scan_id": "SYNTHETIC-scan", "policy_version": "x",
              "detail_json": "{}"}
    store.plan_pm_sports_target(target)
    snap = store.save_snapshot(run_id="SYNTHETIC-pm", source="polymarket_us", kind="book", entity_id="synthetic-kc-mia",
                               url="https://gateway.polymarket.us/SYNTHETIC", payload={"SYNTHETIC": True},
                               fetched_at_utc="2026-09-27T11:00:10Z")
    store.record_pm_sports_observation({"run_id": "SYNTHETIC-pm", "attempt_id": "a1", "target_id": "SYNTHETIC-pm-t",
                                        "status": "CAPTURED", "received_at_utc": "2026-09-27T11:00:10Z",
                                        "snapshot_id": snap, "yes_ask": "0.4100", "freshness": "fresh",
                                        "recorded_at_utc": "2026-09-27T11:00:11Z", "policy_version": "x"})
    rows = rows_by(report(path, now))
    related = rows[("fxsyn002", "T-6h")]["related_not_equivalent"]
    assert len(related) == 1 and related[0]["relation"] == "RELATED_NOT_EQUIVALENT"
    assert rows[("fxsyn002", "T-24h")]["related_not_equivalent"] == []  # received after that cutoff
    assert "polymarket" not in json.dumps(rows[("fxsyn002", "T-6h")]["sides"]).lower()


def test_control_references_point_to_the_previous_horizon_and_another_game_of_the_week(populated):
    path, now = populated
    rows = rows_by(report(path, now))
    c = rows[("fxsyn002", "T-60m")]["controls"]
    assert c["delayed_signal_target"] == rows[("fxsyn002", "T-6h")]["target_id"]
    assert c["placebo_target"] == rows[("fxsyn003", "T-60m")]["target_id"]
    assert rows[("fxsyn002", "T-24h")]["controls"]["delayed_signal_target"] is None
    assert rows[("fxsyn004", "T-6h")]["controls"]["placebo_target"] is None  # alone in its week


# ================================================================== view, CLI, bounds


def test_view_states(tmp_path, populated):
    path, now = populated
    assert se.terminal_view(path, now=now)["family_a"]["state"] == "POPULATED"
    assert se.terminal_view(path, now=now + timedelta(days=12))["family_a"]["state"] == "STALE"
    empty = tmp_path / "empty.sqlite3"
    SnapshotStore(empty)
    assert se.terminal_view(empty, now=now)["family_a"]["state"] == "EMPTY"
    assert se.terminal_view(tmp_path / "missing.sqlite3", now=now)["state"] == "NO_STORE"
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a database at all" * 100)
    assert se.terminal_view(broken, now=now)["state"] in ("NO_STORE", "ERROR")


def test_view_is_memoized_until_the_evidence_changes(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    se._VIEW_CACHE.clear()
    first = se.terminal_view(path, now=now)
    assert len(se._VIEW_CACHE) == 1
    assert se.terminal_view(path, now=now + timedelta(seconds=30)) ["family_a"]["report_sha256"] == \
        first["family_a"]["report_sha256"]
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-more")
    store.save_snapshot(run_id="SYNTHETIC-more", source="kalshi", kind="orderbook", entity_id="KXNFLGAME-26OCT04KCLV-KC",
                        url="u", payload={"orderbook_fp": {}}, fetched_at_utc=iso_z(now))
    se.terminal_view(path, now=now)
    assert len(se._VIEW_CACHE) == 2


def test_the_report_opens_the_store_read_only_and_changes_nothing(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    before = (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    report(path, now)
    se.terminal_view(path, now=now)
    assert (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()) == before


def test_cli_report_summary_and_no_store(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(["report", "--db", str(path), "--as-of", iso_z(now), "--summary"]) == 0
    out = json.loads(buf.getvalue())
    assert out["schema"] == se.SCHEMA and "rows" not in out and out["join"]["paired_targets"] == 9
    assert out["outcome_labels"].startswith("HIDDEN") and out["join"]["outcomes"].startswith("HIDDEN")
    target = tmp_path / "out" / "report.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(["report", "--db", str(path), "--as-of", iso_z(now), "--out", str(target)]) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert json.loads(buf.getvalue())["output_sha256"] == written["output_sha256"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(["report", "--db", str(tmp_path / "nope.sqlite3")]) == 1
    assert json.loads(buf.getvalue())["state"] == "NO_STORE"


def test_bounds_are_stated_in_the_report(populated, monkeypatch):
    path, now = populated
    monkeypatch.setattr(se, "MAX_LISTING_PARSES", 0)
    rep = report(path, now)
    assert rep["bounds"]["kalshi_truncated"] is True and "LISTINGS_TRUNCATED" in rep["bounds"]["problems"][0]


# ================================================================== shared contracts (PR A)


def test_protocol_status_reads_the_registry_and_never_guesses(tmp_path):
    status = se.protocol_status()
    assert status["state"] == "DRAFT" and status["experiment_id"] == "EXP-002" and status["frozen"] is False
    assert status["unsettled_fields"] and any("episode" in f for f in status["unsettled_fields"])
    assert se.protocol_status(tmp_path)["state"] == "NOT_REGISTERED"
    definition = se.episode_definition(status)
    assert definition.start_threshold is None and definition.minimum_size is None and not definition.frozen
    assert definition.problems()  # an UNKNOWN definition yields no episodes


def test_protocol_attrition_uses_the_shared_contract_with_none_for_unregistered_stages(populated):
    path, now = populated
    att = report(path, now)["attrition"]
    den = att["denominators"]
    assert den["events"] == 4 and den["scheduled_horizons"] == 12 and den["opportunities"] == 24
    assert den["markets"] == 8 and den["snapshots"] is None  # SNAPSHOT not enumerated: unknown, never 0
    assert den["signals"] is None and den["simulated_fills"] is None  # no registered rule: None, never 0
    # EXP-002 excludes the conditional mapping (tie pays $0.50): nothing is eligible yet
    assert den["eligible_opportunities"] == 0 and den["final_evaluable_outcomes"] == 0
    opp = next(w for w in att["waterfalls"] if w["level"] == "OPPORTUNITY")
    rows = {r["exclusion"]: r for r in opp["rows"]}
    assert rows["PENDING_TARGET"]["primary_count"] == 6 and rows["RULES_UNRESOLVED"]["primary_count"] == 18
    assert rows["NO_SIGNAL"]["primary_count"] is None and rows["CAPITAL_VETO"]["primary_count"] is None
    assert all(w["reconciled"] for w in att["waterfalls"] if w["start"] is not None)
    accepted = report(path, now, conditional_mapping_accepted=True)["attrition"]["denominators"]
    assert accepted["eligible_opportunities"] == 18 and accepted["final_evaluable_outcomes"] == 6  # G1 settled


def test_protocol_attrition_without_kalshi_evidence(tmp_path):
    path, now = sf.fixture_store(tmp_path, kalshi=False)
    att = report(path, now)["attrition"]
    assert att["denominators"]["markets"] is None  # no listing stored: Kalshi markets are unknown, not 0
    opp = next(w for w in att["waterfalls"] if w["level"] == "OPPORTUNITY")
    assert {r["exclusion"]: r["primary_count"] for r in opp["rows"]}["MISSING_SOURCE"] == 18


def test_economics_come_from_the_shared_screen(populated):
    path, now = populated
    econ = report(path, now)["economics"]
    assert econ["contract"]["state"] == "WIRED" and econ["state"] == "INSUFFICIENT_EVIDENCE"
    # the episode definition is UNKNOWN in EXP-002: episodes are NOT EVALUABLE (None), never "0 episodes"
    assert econ["episodes"]["observations"] == 18 and econ["episodes"]["episodes"] is None
    assert econ["episodes"]["qualifying"] is None and econ["episodes"]["problems"]
    assert screen_minimums_unknown(econ["screen"])
    screen = econ["screen"]
    assert screen["verdict"] == "INSUFFICIENT_EVIDENCE" and screen["experiment_id"] == "EXP-002"
    assert any("no capital scenario was supplied" in r for r in screen["verdict_reasons"])
    assert screen["capital"]["total_capital"] is None  # no bankroll is ever assumed
    assert screen["fixed_cash_costs_annual"]["value"] == "0" and screen["fixed_cash_costs_annual"]["basis"] == "OBSERVED"
    assert econ["edge_at_size"]["state"] == "NOT_DEFENSIBLE"


def screen_minimums_unknown(screen: dict) -> bool:
    """The screen's minimums come from EXP-002 ([economics], MISSING_POWER_ANALYSIS today), never from here."""
    inputs = screen["inputs"]
    return all(inputs[k]["value"] is None and inputs[k]["basis"] == "UNKNOWN" and "EXP-002" in inputs[k]["note"]
               for k in ("min_episodes_for_scenario", "min_independent_clusters"))


def test_outcome_labels_are_hidden_by_default_everywhere(populated):
    path, now = populated
    rep = se.build_report(SnapshotStore.open_readonly(path), as_of=now)
    assert rep["outcome_labels"].startswith("HIDDEN")
    assert all(r.get("outcome") in (None, se.OUTCOMES_HIDDEN) for r in rep["rows"])
    assert rep["join"]["outcomes"] == se.OUTCOMES_HIDDEN and rep["join"]["final_evaluable_targets"] is None
    att = rep["attrition"]
    assert "OUTCOME" in att["not_applicable_stages"] and att["denominators"]["final_evaluable_outcomes"] is None
    opp = next(w for w in att["waterfalls"] if w["level"] == "OPPORTUNITY")
    counts = {r["exclusion"]: r["primary_count"] for r in opp["rows"]}
    assert counts["OUTCOME_PENDING"] is None and counts["OUTCOME_VOID"] is None
    text = json.dumps(rep)
    for label in ("OUTCOME_FINAL", "OUTCOME_PENDING\": 1", "\"result\": \"YES\"", "\"result\": \"NO\""):
        assert label not in text
    view = se.terminal_view(path, now=now)["family_a"]
    assert "outcomes" not in view and "final_evaluable_targets" not in view
    assert view["outcome_labels"].startswith("HIDDEN") and "OUTCOME_FINAL" not in json.dumps(view)


def _registry_copy(tmp_path) -> tuple[Path, Path]:
    """A registry holding a copy of EXP-002 (its protocol, manifest and evidence log)."""
    import shutil
    src = next((REPO / "experiments").glob("EXP-002-*"))
    root = tmp_path / "experiments"
    shutil.copytree(src, root / src.name)
    return root, root / src.name / "evidence_use.jsonl"


def test_with_results_records_in_the_experiments_own_log_before_printing(tmp_path, populated):
    from edge_lab import research_evidence as rev
    path, now = populated
    root, own = _registry_copy(tmp_path)
    base = ["report", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root)]
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base + ["--with-results"]) == 2  # no log, actor or code version: refused
    assert json.loads(buf.getvalue())["state"] == "REFUSED" and "OUTCOME_FINAL" not in buf.getvalue()
    before = len(rev.read_log(own).uses)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base + ["--with-results", "--summary", "--evidence-log", str(own), "--actor", "test",
                               "--code-version", "abc123"]) == 0
    out = json.loads(buf.getvalue())
    assert out["evidence_use"] == "APPENDED" and out["join"]["outcomes"]["OUTCOME_FINAL"] == 3
    uses = rev.read_log(own).uses
    assert len(uses) == before + 1 and uses[-1].action is rev.Action.LABEL_RESULT_INSPECTION
    assert uses[-1].viewed_labels is True and uses[-1].window.scope == "sports:nfl:moneyline"
    assert uses[-1].dataset_sha256 == out["output_sha256"]
    # any other log (even a valid EXP-002 log elsewhere) is refused, and nothing is shown
    stray = rev.init_log(tmp_path / "evidence_use.jsonl", experiment_id="EXP-002",
                         started_at_utc="2026-09-25T00:00:00Z", covered_scopes=["sports:nfl:moneyline"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base + ["--with-results", "--evidence-log", str(stray), "--actor", "test",
                               "--code-version", "abc123"]) == 2
    refused = json.loads(buf.getvalue())
    assert refused["state"] == "REFUSED" and "own log" in refused["detail"] and "OUTCOME_FINAL" not in buf.getvalue()
    assert rev.read_log(stray).uses == ()


def test_a_side_unmapped_at_its_decision_does_not_exclude_the_paired_side(tmp_path):
    """Review repro: side A's book precedes the listing (NOT_MAPPED_AT_DECISION), side B's book follows it
    (paired). With the conditional mapping accepted, the horizon's opportunities are 2 with 1 survivor."""
    path, now = sf.fixture_store(tmp_path, kalshi=False)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-repro")
    g = sf.GAMES[1]
    target = next(dict(r) for r in store.odds_targets(sport=se.SPORT)
                  if r["event_id"] == "fxsyn002" and r["offset_label"] == "T-6h")
    odds_at = datetime.fromisoformat(target["captured_at_utc"].replace("Z", "+00:00"))
    for team, offset in ((g.away, -60), (g.home, 60)):
        ticker = f"{sf.event_ticker(g)}-{se.NFL_TEAMS[team][0]}"
        store.save_snapshot(run_id="SYNTHETIC-repro", source="kalshi", kind="orderbook", entity_id=ticker,
                            url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100", payload=sf._book(Decimal("0.5")),
                            fetched_at_utc=iso_z(odds_at + timedelta(seconds=offset)), source_id="kalshi_public")
    store.save_snapshot(run_id="SYNTHETIC-repro", source="kalshi", kind="markets", entity_id=sf.event_ticker(g),
                        url=f"{sf.KALSHI_API}/markets?event_ticker={sf.event_ticker(g)}",
                        payload={"markets": [sf._market(g, g.home), sf._market(g, g.away)], "cursor": ""},
                        fetched_at_utc=iso_z(odds_at + timedelta(seconds=30)), source_id="kalshi_public")
    policy = se.JoinPolicy(conditional_mapping_accepted=True)
    ro = SnapshotStore.open_readonly(path)
    rep = se.build_report(ro, as_of=now, policy=policy)
    row = rows_by(rep)[("fxsyn002", "T-6h")]
    assert row["status"] == "PARTIAL_PAIR" and row["all_stages"] == ["KALSHI_NOT_MAPPED"]
    assert row["sides"]["Kansas City Chiefs"]["stage"] == "KALSHI_NOT_MAPPED"
    assert row["sides"]["Miami Dolphins"]["stage"] is None
    assert se._row_reasons(row) == []  # the game mapped: no row-level exclusion
    catalog = se.kalshi_catalog(ro, now, se._Payloads(ro))
    att = se.protocol_attrition([row], as_of=now, policy=policy, catalog=catalog)
    opp = next(w for w in att["waterfalls"] if w["level"] == "OPPORTUNITY")
    assert opp["start"] == 2 and opp["survivors"] == 1


def test_hidden_mode_withholds_g3_and_markout_labels(populated):
    path, now = populated
    hidden = se.build_report(SnapshotStore.open_readonly(path), as_of=now)
    g3 = next(g for g in hidden["gaps"] if g["id"] == "G3")
    assert g3["state"] == "WITHHELD" and "stored" not in g3
    sides = [s for r in hidden["rows"] for s in r["sides"].values() if s.get("stage") is None]
    assert sides and all(s["markout_label_ref"] == se.OUTCOMES_HIDDEN for s in sides)
    shown = report(path, now)
    assert not any(g["id"] == "G3" for g in shown["gaps"])  # a resolution is stored (G1 settled)
    assert any(isinstance(s.get("markout_label_ref"), dict) for r in shown["rows"] for s in r["sides"].values())


def test_as_of_in_the_future_is_clamped_to_now(tmp_path, capsys):
    path, _ = sf.fixture_store(tmp_path)  # the clock is 2026-10-10 here
    assert se.main(["report", "--db", str(path), "--as-of", "2099-01-01T00:00:00Z", "--summary"]) == 0
    captured = capsys.readouterr()
    assert "clamped" in captured.err and not json.loads(captured.out)["as_of_utc"].startswith("2099")


def test_market_denominator_counts_every_listed_market(issues):
    path, now = issues
    att = report(path, now, results=False)["attrition"]
    markets = next(w for w in att["waterfalls"] if w["level"] == "MARKET")
    assert att["denominators"]["markets"] == 8  # 4 listed games x 2 markets, not only the 6 evaluated sides
    rows = {r["exclusion"]: r["primary_count"] for r in markets["rows"]}
    assert rows["PENDING_TARGET"] == 2 and rows["RULES_UNRESOLVED"] == 6  # next week's game; conditional mapping


def test_a_listing_received_after_the_decision_time_is_never_used(tmp_path):
    """The listing arrives after the odds capture and the book (as price_observations would store it late):
    a cutoff-based mapping would use it; the decision-time rule does not."""
    path, now = sf.fixture_store(tmp_path, kalshi=False)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-late")
    g = sf.GAMES[1]
    rows = {(r["event_id"], r["offset_label"]): dict(r) for r in store.odds_targets(sport=se.SPORT)}
    six = rows[("fxsyn002", "T-6h")]
    odds_at = datetime.fromisoformat(six["captured_at_utc"].replace("Z", "+00:00"))
    for team in (g.home, g.away):
        ticker = f"{sf.event_ticker(g)}-{se.NFL_TEAMS[team][0]}"
        store.save_snapshot(run_id="SYNTHETIC-late", source="kalshi", kind="orderbook", entity_id=ticker,
                            url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100", payload=sf._book(Decimal("0.5")),
                            fetched_at_utc=iso_z(odds_at + timedelta(seconds=60)), source_id="kalshi_public")
    store.save_snapshot(run_id="SYNTHETIC-late", source="kalshi", kind="markets", entity_id=sf.event_ticker(g),
                        url=f"{sf.KALSHI_API}/markets?event_ticker={sf.event_ticker(g)}",
                        payload={"markets": [sf._market(g, g.home), sf._market(g, g.away)], "cursor": ""},
                        fetched_at_utc=iso_z(odds_at + timedelta(seconds=120)), source_id="kalshi_public")
    row = rows_by(report(path, now))[("fxsyn002", "T-6h")]
    assert row["kalshi"]["state"] == "MAPPED"  # the candidate mapping (listings known by the cutoff)
    side = row["sides"]["Miami Dolphins"]
    assert side["stage"] == "KALSHI_NOT_MAPPED" and "NOT_MAPPED_AT_DECISION" in side["reasons"][0]
    assert row["status"] == "EXCLUDED" and "rules" not in side


def test_partial_pair_keeps_the_failing_sides_stage(tmp_path):
    import sqlite3
    path, now = sf.fixture_store(tmp_path)
    row = rows_by(report(path, now))[("fxsyn002", "T-60m")]
    book = row["sides"]["Kansas City Chiefs"]["book_snapshot_id"]
    with sqlite3.connect(path) as conn:  # the stored payload no longer matches its hash
        conn.execute("DROP TRIGGER IF EXISTS snapshots_no_update")
        conn.execute("UPDATE snapshots SET payload_json = ? WHERE id = ?", ('{"orderbook_fp": {}}', book))
    row = rows_by(report(path, now))[("fxsyn002", "T-60m")]
    assert row["status"] == "PARTIAL_PAIR" and row["all_stages"] == ["KALSHI_BOOK_UNUSABLE"]


def test_fee_status_comes_from_the_schedule_not_from_text(monkeypatch, populated):
    path, now = populated
    side = rows_by(report(path, now))[("fxsyn002", "T-60m")]["sides"]["Miami Dolphins"]
    assert {r["fee_status"] for r in side["capacity"]} == {"FEE_UNSUPPORTED"}
    from edge_lab import fee_schedules
    monkeypatch.setattr(se, "fee_schedule", lambda: fee_schedules.KALSHI_QUADRATIC_TAKER_V1)
    priced = rows_by(report(path, now))[("fxsyn002", "T-60m")]["sides"]["Miami Dolphins"]["capacity"]
    assert priced[0]["fee_status"] == "PRICED" and priced[0]["all_in_cost_per_unit"] is not None


def test_terminal_cache_ignores_writes_by_other_collectors(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    se._VIEW_CACHE.clear()
    se.terminal_view(path, now=now)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-weather")
    store.save_snapshot(run_id="SYNTHETIC-weather", source="kalshi", kind="orderbook", entity_id="KXHIGHNY-26SEP27-B70.5",
                        url="u", payload={"orderbook_fp": {}}, fetched_at_utc=iso_z(now))
    se.terminal_view(path, now=now)
    assert len(se._VIEW_CACHE) == 1  # a KXHIGHNY book does not rebuild the NFL report


def test_reads_only_through_the_stores_public_metadata_api(tmp_path):
    src = Path(se.__file__).read_text(encoding="utf-8")
    assert "_connect(" not in src and "LIKE" not in src  # snapshot_metadata (exact prefix) and max_row_id only
    path, now = sf.fixture_store(tmp_path)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-lookalike")
    store.save_snapshot(run_id="SYNTHETIC-lookalike", source="kalshi", kind="orderbook",
                        entity_id="KXNFLGAMEX-26SEP27KCMIA-KC", url="u?depth=100", payload={"orderbook_fp": {}},
                        fetched_at_utc=iso_z(now - timedelta(hours=1)))
    ro = SnapshotStore.open_readonly(path)
    catalog = se.kalshi_catalog(ro, now, se._Payloads(ro))
    assert catalog.books and all(t.startswith("KXNFLGAME-") for t in catalog.books)  # never a look-alike series


def test_view_key_markers_reset_for_a_replaced_store(tmp_path):
    path, now = sf.fixture_store(tmp_path)
    key = str(SnapshotStore.open_readonly(path).path)
    se._VIEW_CACHE.clear()
    se._MARKERS[key] = (10**9, 10**9)  # ids beyond this store's: a replaced or restored store
    assert se.terminal_view(path, now=now)["state"] == "OK"
    assert se._MARKERS[key][0] is not None and se._MARKERS[key][0] < 10**9


def test_module_makes_no_network_import_at_runtime():
    src = Path(se.__file__).read_text(encoding="utf-8")
    for banned in ("import urllib.request", "from .http", "import http", "fetch_json", "requests"):
        assert banned not in src


def test_an_ad_hoc_book_of_another_horizon_is_never_picked_even_within_five_minutes():
    # The horizon window starts 2 min before the odds receipt; an ad-hoc capture 4 min before the odds is within
    # max_book_before_odds but belongs to no book of this horizon, so it is never picked.
    start = T0 - timedelta(minutes=2)
    ad_hoc = _b(-4 * 60, 1)
    none, why, _ = se.pick_book([ad_hoc], T0, start, CUTOFF)
    assert none is None and why.startswith("KALSHI_BOOK_MISSING") and "other horizons" in why
    assert se.pick_book([ad_hoc, _b(60, 2)], T0, start, CUTOFF)[0][1] == 2  # the first book after the odds instead
    assert se.pick_book([ad_hoc, _b(-60, 3)], T0, start, CUTOFF)[0][1] == 3  # an earlier book of this horizon


def before_odds_store(tmp_path) -> Path:
    """The SYNTHETIC pairing fixture, but every Kalshi book lands 60 s BEFORE its odds receipt."""
    store = SnapshotStore(tmp_path / "before.sqlite3")
    sf.write_pairing_fixture(store, books=False)
    rows = report(store.path, sf.NOW)["rows"]
    store.start_run("SYNTHETIC-books-before-odds")
    written = 0
    for r in rows:
        received = r["odds"].get("received_utc")
        tickers = (r.get("kalshi") or {}).get("tickers") or {}
        if not received or not tickers:
            continue
        at = datetime.fromisoformat(received.replace("Z", "+00:00")) - timedelta(seconds=60)
        for team, ticker in sorted(tickers.items()):
            store.save_snapshot(run_id="SYNTHETIC-books-before-odds", source=se.KALSHI, kind="orderbook",
                                entity_id=ticker, url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                payload=sf._book(Decimal("0.55")), fetched_at_utc=iso_z(at),
                                source_id="kalshi_public")
            written += 1
    store.finish_run("SYNTHETIC-books-before-odds", status="succeeded")
    assert written
    return store.path


def test_only_book_at_or_after_odds_pairs_feed_the_ladder_and_the_economics(populated, tmp_path):
    path, now = populated
    after = report(path, now)
    paired = [s for r in after["rows"] for s in r["sides"].values() if s.get("stage") is None]
    assert paired and all(s["book_timing"] == se.BOOK_AT_OR_AFTER_ODDS and s["capacity"] for s in paired)
    assert all(s["pair_use"].startswith("EXECUTABLE_PRICE_CANDIDATE") for s in paired)
    assert after["economics"]["episodes"]["observations"] == len(paired)

    before = report(before_odds_store(tmp_path), sf.NOW)
    sides = [s for r in before["rows"] for s in r["sides"].values() if s.get("stage") is None]
    # still paired (comparability-only pairs count for markout and calibration) ...
    assert sides and all(s["book_timing"] == se.BOOK_BEFORE_ODDS for s in sides)
    assert all(s["pair_use"].startswith("COMPARABILITY_ONLY") for s in sides)
    # ... but never an executable price: no size ladder and no economics observation
    assert all(s["capacity"] is None for s in sides)
    assert before["economics"]["episodes"]["observations"] == 0
    view = se.view_from_report(before, sf.NOW)
    assert view["capacity"]["latest"]["book_timing"] == se.BOOK_BEFORE_ODDS and view["capacity"]["latest"]["ladder"] == []
