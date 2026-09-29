"""EXP-002 E1: the PROPOSED executable round-trip endpoint (docs/research/EXP002_FREEZE_PROPOSAL.md §3 rows 3-5,
11, 15; docs/research/EXP002_E1_ENDPOINT.md).

Offline, SYNTHETIC only (hand-built rows and fixture stores; no production data, no network). Pinned here:
- the entry rule uses T-6h information only (margin >= theta against the side's OWN c_low, displayed depth, one
  side per game, BEFORE_ODDS never entered, stale and undeclared bounds never entered);
- the exit is the first T-60m bid; every missing exit is scored at settlement (primary) and at 0 (sensitivity),
  never dropped; an unsettled game or an open T-60m window is PENDING, never 0;
- label safety: the label-free output never loads a T-60m book or a settlement and is identical whether T-60m
  books and settlements exist or not; the results path is logged before anything is shown;
- gross only: no fee is applied and no net figure exists.
"""

from __future__ import annotations

import io
import json
import shutil
import socket
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.odds_schedule import iso_z
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
BOUNDS = (Decimal("0.01"), Decimal("0.005"))  # the proposal's PROPOSED t_max, u_max (row 1): a test candidate
POLICY = se.JoinPolicy(tie_probability_bound=BOUNDS[0], postponement_probability_bound=BOUNDS[1])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    monkeypatch.setattr(se, "_clock", lambda: datetime(2026, 11, 1, tzinfo=UTC))


def D(x: str) -> Decimal:
    return Decimal(x)


def c_low(p: str) -> Decimal:
    return se.tie_adjusted_interval(D(p), D("0.50"), *BOUNDS)[0]


# ================================================================== entry rule (hand-built T-6h rows)


def _side(ask: str | None, p: str | None, *, size: str | None = "10", timing: str = se.BOOK_AT_OR_AFTER_ODDS,
          book_fresh: str = "fresh", odds_fresh: str = "fresh", stage=None, tie: str | None = "0.50",
          ticker: str = "KXNFLGAME-26OCT04AAABBB-AAA") -> dict:
    return {"ticker": ticker, "stage": stage, "book_timing": timing, "book_freshness_at_decision": book_fresh,
            "decision_freshness_odds": odds_fresh, "yes_bid": None if ask is None else str(D(ask) - D("0.02")),
            "yes_ask": None if ask is None else D(ask), "yes_ask_size": None if size is None else D(size),
            "consensus_probability": None if p is None else D(p), "rules": {"tie_payout": tie},
            "book_snapshot_id": 1, "decision_utc": "2026-10-04T11:01:00Z"}


def _row(event: str, home: dict | None, away: dict | None, *, week: str = "nfl-week-of-2026-09-29",
         status: str = se.PAIRED, horizon: str = "T-6h", all_stages: list | None = None) -> dict:
    sides = {}
    if home is not None:
        sides["Home"] = home
    if away is not None:
        sides["Away"] = away
    return {"event_id": event, "horizon": horizon, "status": status, "week_cluster": week,
            "commence_utc": "2026-10-04T17:00:00Z", "home_team": "Home", "away_team": "Away", "target_id": f"{event}-6",
            "sides": sides, "all_stages": all_stages or [], "primary": status}


def _game(entries: dict, event: str) -> dict:
    return next(g for g in entries["games"] if g["event_id"] == event)


def test_margin_at_or_above_theta_with_depth_enters_and_below_theta_does_not():
    assert c_low("0.60") == D("0.596")  # min over the A.D corners: 0.985 * 0.60 + 0.005
    rows = [_row("at", _side("0.586", "0.60"), None),  # margin exactly theta: eligible (>=)
            _row("below", _side("0.587", "0.60"), None),  # margin 0.009 < theta
            _row("wide", _side("0.50", "0.60"), None)]
    e = se.e1_entries(rows, POLICY)
    at = _game(e, "at")
    assert at["decision"] == se.E1_TRADE and at["entry"]["margin"] == se.E1_THETA == D("0.01")
    assert at["entry"]["c_low"] == D("0.596") and at["entry"]["ask"] == D("0.586")
    assert _game(e, "below")["decision"] == se.E1_NO_ELIGIBLE
    assert _game(e, "below")["sides"]["home"]["reason"] == se.E1_BELOW_THETA
    assert _game(e, "wide")["entry"]["margin"] == D("0.096")
    assert e["counts"]["entries"] == 2 and e["counts"]["games_evaluable"] == 3
    assert e["operational_futility_inputs"]["trade_rate"]["value"] == pytest.approx(2 / 3)


def test_ask_depth_must_show_at_least_one_contract_and_missing_depth_is_not_eligible():
    e = se.e1_entries([_row("none", _side("0.50", "0.60", size=None), None),
                       _row("half", _side("0.50", "0.60", size="0.5"), None),
                       _row("one", _side("0.50", "0.60", size="1"), None)], POLICY)
    assert _game(e, "none")["sides"]["home"]["reason"] == se.E1_ASK_DEPTH_MISSING
    assert _game(e, "half")["sides"]["home"]["reason"] == se.E1_ASK_DEPTH_BELOW_MIN
    assert _game(e, "one")["decision"] == se.E1_TRADE
    assert e["sides_by_reason"][se.E1_ASK_DEPTH_MISSING] == e["sides_by_reason"][se.E1_ASK_DEPTH_BELOW_MIN] == 1


def test_at_most_one_side_per_game_the_larger_margin_and_an_exact_tie_trades_neither():
    both = _row("both", _side("0.55", "0.60"), _side("0.40", "0.47", ticker="KXNFLGAME-26OCT04AAABBB-BBB"))
    tied = _row("tied", _side("0.556", "0.60"), _side("0.556", "0.60", ticker="KXNFLGAME-26OCT04AAABBB-BBB"))
    e = se.e1_entries([both, tied], POLICY)
    g = _game(e, "both")
    margins = {role: s["margin"] for role, s in g["sides"].items()}
    assert all(s["reason"] == se.E1_ELIGIBLE for s in g["sides"].values())
    assert g["decision"] == se.E1_TRADE and g["entry"]["role"] == max(margins, key=margins.get)
    t = _game(e, "tied")
    assert t["decision"] == se.E1_MARGIN_TIE and t["entry"] is None
    assert e["counts"]["margin_ties_no_trade"] == 1 and e["counts"]["entries"] == 1


def test_the_away_side_uses_its_own_c_low_not_one_minus_the_home_interval():
    # The two consensus values need not sum to 1, and the fallback F applies to each contract separately.
    e = se.e1_entries([_row("g", _side("0.70", "0.60"), _side("0.40", "0.45", ticker="T-AWAY"))], POLICY)
    away = _game(e, "g")["sides"]["away"]
    assert away["c_low"] == c_low("0.45") == se.tie_adjusted_interval(D("0.45"), D("0.50"), *BOUNDS)[0]
    home_high = se.tie_adjusted_interval(D("0.60"), D("0.50"), *BOUNDS)[1]
    assert away["c_low"] != 1 - home_high
    assert away["margin"] == c_low("0.45") - D("0.40") and _game(e, "g")["entry"]["role"] == "away"


def test_before_odds_sides_are_counted_and_never_entered():
    e = se.e1_entries([_row("g", _side("0.30", "0.60", timing=se.BOOK_BEFORE_ODDS),
                            _side("0.20", "0.45", timing=se.BOOK_BEFORE_ODDS, ticker="T-AWAY"))], POLICY)
    g = _game(e, "g")
    assert g["decision"] == se.E1_NO_ELIGIBLE and all(s["margin"] is None for s in g["sides"].values())
    assert e["sides_by_reason"][se.E1_BEFORE_ODDS] == 2 and e["counts"]["games_with_at_or_after_side"] == 0
    assert e["operational_futility_inputs"]["t6_at_or_after_odds_pairing_yield"] == 0


def test_stale_or_unknown_inputs_are_not_eligible_and_are_counted():
    e = se.e1_entries([
        _row("book", _side("0.50", "0.60", book_fresh="stale"), None),
        _row("odds", _side("0.50", "0.60", odds_fresh="unknown"), None),
        _row("row", None, None, status="EXCLUDED", all_stages=[se.Stage.ODDS_NOT_FRESH.value]),
        _row("unpaired", _side("0.50", "0.60", book_fresh="stale", stage=se.Stage.KALSHI_BOOK_UNUSABLE), None,
             status="EXCLUDED", all_stages=[se.Stage.KALSHI_BOOK_UNUSABLE.value]),
    ], POLICY)
    assert e["counts"]["entries"] == 0
    for event in ("book", "odds", "row", "unpaired"):
        assert _game(e, event)["sides"]["home"]["reason"] == se.E1_STALE, event
    assert _game(e, "row")["sides"]["away"]["reason"] == se.E1_STALE
    assert e["sides_by_reason"][se.E1_NOT_PAIRED] == 3  # the away sides of book / odds / unpaired: no side at all


def test_undeclared_bounds_compute_no_entry_and_never_fall_back_to_the_unadjusted_consensus():
    rows = [_row("g", _side("0.40", "0.60"), None)]  # a 20-cent unadjusted gap
    e = se.e1_entries(rows, se.JoinPolicy())
    side = _game(e, "g")["sides"]["home"]
    assert side["reason"] == se.E1_BOUNDS_UNDECLARED and side["c_low"] is None and side["margin"] is None
    assert e["bounds_undeclared"] == 1 and e["counts"]["entries"] == 0 and e["counts"]["games_evaluable"] == 0
    assert e["operational_futility_inputs"]["trade_rate"]["value"] is None
    assert e["bounds"]["source"].startswith("UNDECLARED")
    unparsed = se.e1_entries([_row("g", _side("0.40", "0.60", tie=None), None)], POLICY)
    assert _game(unparsed, "g")["sides"]["home"]["reason"] == se.E1_TIE_PAYOUT_UNKNOWN


def test_a_partial_pair_still_lets_the_paired_side_trade_and_other_horizons_are_ignored():
    rows = [_row("g", _side("0.50", "0.60"), _side(None, None, stage=se.Stage.KALSHI_BOOK_MISSING, ticker="T-A"),
                 status=se.PARTIAL_PAIR),
            _row("g", _side("0.10", "0.60"), None, horizon="T-60m"),
            _row("later", _side("0.10", "0.60"), None, status=se.NOT_YET_DUE)]
    e = se.e1_entries(rows, POLICY)
    assert e["counts"]["rows_other_horizon_ignored"] == 1 and e["counts"]["t6_not_yet_due_or_superseded"] == 1
    g = _game(e, "g")
    assert g["decision"] == se.E1_TRADE and g["entry"]["role"] == "home"
    assert g["sides"]["away"]["reason"] == se.E1_NOT_PAIRED
    assert g["sides"]["away"]["join_stage"] == se.Stage.KALSHI_BOOK_MISSING.value


# ================================================================== wild cluster bootstrap


def test_the_wild_cluster_bootstrap_enumerates_every_sign_pattern_for_few_weeks():
    pairs = [("w1", 0.02), ("w1", 0.04), ("w2", -0.01)]
    out = se._wild_cluster_bounds(pairs, seed=1, resamples=100)
    mean = 0.05 / 3
    s1, s2 = (0.02 - mean) + (0.04 - mean), -0.01 - mean
    devs = sorted((a * s1 + b * s2) / 3 for a in (-1, 1) for b in (-1, 1))
    assert out["exact_enumeration"] and out["weight_patterns"] == 4 and out["state"] == "COARSE_FEW_CLUSTERS"
    assert out["lower_90_one_sided"] == pytest.approx(mean - devs[3])
    assert out["upper_90_one_sided"] == pytest.approx(mean - devs[0])
    assert se._wild_cluster_bounds([("w1", 0.1), ("w1", 0.2)], seed=1, resamples=10)["state"] == "INSUFFICIENT_CLUSTERS"
    many = [(f"w{i:02d}", 0.01 * ((i % 5) - 2)) for i in range(14)]
    a = se._wild_cluster_bounds(many, seed=7, resamples=500)
    assert not a["exact_enumeration"] and a == se._wild_cluster_bounds(many, seed=7, resamples=500)
    assert a["lower_90_one_sided"] <= sum(v for _, v in many) / 14 <= a["upper_90_one_sided"]


# ================================================================== SYNTHETIC stores (exits, settlement, labels)


TEAMS = list(se.NFL_TEAMS)
KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
HOME_ASK6 = D("0.55")  # home consensus about 0.60: c_low about 0.596, margin about 0.046 -> every game buys home
AWAY_ASK6 = D("0.45")  # away consensus about 0.40: margin negative


def _payload(bid: str | None, bid_size: str, ask: str, ask_size: str = "40") -> dict:
    yes = [] if bid is None else [[f"{D(bid):.4f}", f"{D(bid_size):.2f}"]]
    return {"orderbook_fp": {"yes_dollars": yes, "no_dollars": [[f"{1 - D(ask):.4f}", f"{D(ask_size):.2f}"]]}}


CROSSED = {"orderbook_fp": {"yes_dollars": [["0.6000", "10.00"]], "no_dollars": [["0.5000", "10.00"]]}}
# Per game (home side): the T-60m books in receipt order, and the home market's settlement listing
# (status, result, settlement_value_dollars) or None for no settled listing.
SPECS = [
    ("exit", [_payload("0.58", "30", "0.60"), _payload("0.70", "30", "0.72")], ("finalized", "yes", "1.0000")),
    ("no_book", [], ("finalized", "yes", None)),
    ("no_bid", [_payload(None, "0", "0.60")], ("settled", "no", "0.0000")),
    ("thin_bid", [_payload("0.58", "0.5", "0.60")], ("finalized", "", "0.5000")),  # a tie at $0.50
    ("crossed", [CROSSED], ("determined", "yes", None)),  # preliminary: not final -> PENDING
    ("exit_loss", [_payload("0.53", "5", "0.55")], None),
    ("value_unknown", [], ("finalized", "", None)),
    ("conflict", [], ("finalized", "yes", "0.0000")),
]


def build_e1_store(tmp_path: Path, *, labels: bool = True, specs: list | None = None) -> tuple[Path, datetime, dict]:
    """Eight games over two NFL weeks. Every T-6h side is paired AT_OR_AFTER_ODDS (a book 60 s after the odds)
    with the home ask at 0.55 and the away ask at 0.45. `labels=False` writes no T-60m book and no settlement:
    the label-free output must not change. `specs` replaces SPECS (same shape)."""
    specs = SPECS if specs is None else specs
    games = [sf.Game(f"fxe1{i:02d}", TEAMS[2 * (i % 4)], TEAMS[2 * (i % 4) + 1], KICKOFF + timedelta(days=7 * (i // 4)),
                     D("0.60")) for i in range(len(specs))]
    now = max(g.commence for g in games) + timedelta(hours=8)
    store = SnapshotStore(tmp_path / ("e1.sqlite3" if labels else "e1-nolabels.sqlite3"))
    sf.write_pairing_fixture(store, games=games, now=now, books=False, settle=False)
    rows = se.build_report(SnapshotStore.open_readonly(store.path), as_of=now)["rows"]
    run = "SYNTHETIC-e1-books"
    store.start_run(run)
    ids = {"T-6h": set(), "T-60m": set(), "first": {}, "second": set(), "games": {g.event_id: s[0] for g, s in
                                                                                     zip(games, specs)}}
    spec_of = {g.event_id: s for g, s in zip(games, specs)}
    for r in rows:
        received = r["odds"].get("received_utc")
        tickers = (r.get("kalshi") or {}).get("tickers") or {}
        if not received or not tickers or r["horizon"] not in ("T-6h", "T-60m"):
            continue
        at = datetime.fromisoformat(received.replace("Z", "+00:00"))
        for team, ticker in sorted(tickers.items()):
            home = team == r["home_team"]
            if r["horizon"] == "T-6h":
                ask = HOME_ASK6 if home else AWAY_ASK6
                books = [_payload(str(ask - D("0.02")), "40", str(ask))]
            elif not labels:
                continue
            else:
                books = spec_of[r["event_id"]][1] if home else [_payload("0.40", "40", "0.42")]
            for k, payload in enumerate(books):
                sid = store.save_snapshot(run_id=run, source=se.KALSHI, kind="orderbook", entity_id=ticker,
                                          url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100", payload=payload,
                                          fetched_at_utc=iso_z(at + timedelta(seconds=60 + 120 * k)),
                                          source_id="kalshi_public")
                ids[r["horizon"]].add(sid)
                if r["horizon"] == "T-60m" and home:
                    if k == 0:
                        ids["first"][r["event_id"]] = sid
                    else:
                        ids["second"].add(sid)
    if labels:
        for g, (_, _, settle) in zip(games, specs):
            if settle is None:
                continue
            status, result, value = settle
            home = sf._market(g, g.home, status=status, result=result)
            away = sf._market(g, g.away, status=status, result={"yes": "no", "no": "yes"}.get(result, result))
            if value is not None:
                home["settlement_value_dollars"] = value
                away["settlement_value_dollars"] = str(1 - D(value))
            store.save_snapshot(run_id=run, source=se.KALSHI, kind="markets", entity_id=sf.event_ticker(g),
                                url=f"{sf.KALSHI_API}/markets?event_ticker={sf.event_ticker(g)}",
                                payload={"markets": [home, away], "cursor": ""},
                                fetched_at_utc=iso_z(g.commence + timedelta(hours=5)), source_id="kalshi_public")
    store.finish_run(run, status="succeeded")
    return store.path, now, ids


def _by_name(e1: dict, ids: dict) -> dict:
    return {ids["games"][g["event_id"]]: g for g in e1["games"]}


def test_the_exit_is_the_first_t60m_bid_and_every_missing_exit_is_scored_never_dropped(tmp_path):
    path, now, ids = build_e1_store(tmp_path)
    out = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, e1_bounds=BOUNDS)
    e1 = out["e1"]
    assert out["version"] == "exp002-measurement-v3" and e1["version"] == se.E1_VERSION
    assert e1["state"] == se.E1_STATE and "NOT FROZEN" in e1["state"] and "NOT A TEST" in e1["state"]
    assert e1["freeze_eligible"] is False and e1["verdict"].startswith("NONE")
    assert "FIRST_DETECTION_ZERO_LATENCY" in e1["fill_assumption"]
    assert "a displayed quote is not a proven fill" in e1["fill_assumption"].lower()
    g = _by_name(e1, ids)
    assert all(x["decision"] == se.E1_TRADE and x["role"] == "home" and D(x["ask6"]) == D("0.55") for x in g.values())
    # EXIT_BID: the first book's bid (0.58), never the later 0.70 book
    ex = g["exit"]
    assert ex["exit_basis"] == se.E1_EXIT_BID and D(ex["exit_value"]) == D("0.58") and D(ex["bid_depth"]) == 30
    assert ex["t60_book"]["snapshot_id"] == ids["first"][ex["event_id"]] not in ids["second"]
    assert D(ex["gross"]) == D("0.58") - D("0.55") == D(ex["gross_exit_at_0"])
    assert g["exit_loss"]["exit_basis"] == se.E1_EXIT_BID and D(g["exit_loss"]["gross"]) == D("-0.02")
    # missing exits, each scored at settlement (primary) and at 0 (sensitivity)
    expect = {"no_book": ("NO_T60_BOOK", "1", "0.45"), "no_bid": ("NO_BID", "0", "-0.55"),
              "thin_bid": ("BID_DEPTH_BELOW_1", "0.5", "-0.05")}
    for name, (reason, payoff, gross) in expect.items():
        x = g[name]
        assert x["missing_exit"] == reason and x["exit_basis"] == se.E1_SETTLEMENT_FALLBACK, name
        assert D(x["exit_value"]) == D(payoff) and D(x["gross"]) == D(gross), name
        assert D(x["gross_exit_at_0"]) == D("-0.55"), name
    # unsettled (determined = preliminary), unknown settled value, contradicting value: PENDING, never 0
    for name, why, missing in (("crossed", "SETTLEMENT_NOT_FINAL", "UNUSABLE_BOOK"),
                               ("value_unknown", "SETTLED_VALUE_UNKNOWN", "NO_T60_BOOK"),
                               ("conflict", "SETTLEMENT_CONFLICT", "NO_T60_BOOK")):
        x = g[name]
        assert x["exit_basis"] == se.E1_PENDING and x["pending_reason"] == why and x["missing_exit"] == missing, name
        assert x["gross"] is None and D(x["gross_exit_at_0"]) == D("-0.55"), name
    att = e1["attrition"]
    assert att["trades"] == 8 and att["exit_determined"] == 8 and att["exit_bid"] == 2
    assert att["missing_exit"] == {"NO_T60_TARGET": 0, "NO_T60_BOOK": 3, "UNUSABLE_BOOK": 1, "NO_BID": 1,
                                   "BID_DEPTH_MISSING": 0, "BID_DEPTH_BELOW_1": 1}
    assert att["missing_exit_total"] == 6 == (att["missing_exit_settlement_fallback_scored"]
                                              + sum(att["missing_exit_settlement_pending"].values()))
    assert att["missing_exit_settlement_fallback_scored"] == 3
    assert att["scored_primary"] == 5 and att["scored_exit_at_0_sensitivity"] == 8
    s = e1["summary"]
    primary = [0.03, -0.02, 0.45, -0.55, -0.05]
    assert s["primary"]["n"] == 5 and s["primary"]["mean_gross"] == pytest.approx(sum(primary) / 5)
    assert s["primary"]["weeks"] == 2 and s["primary"]["week_cluster_bounds"]["exact_enumeration"]
    sens = [0.03, -0.02] + [-0.55] * 6
    assert s["sensitivity_exit_at_0"]["mean_gross"] == pytest.approx(sum(sens) / 8)
    # secondary (b): hold to settlement for every trade whose settlement is final (exit / no_book / no_bid / thin_bid)
    hold = s["secondary_hold_to_settlement"]
    assert hold["n"] == 4 and hold["mean_gross"] == pytest.approx((0.45 + 0.45 - 0.55 - 0.05) / 4)
    assert D(g["exit"]["hold_to_settlement_gross"]) == D("0.45") and g["exit_loss"]["hold_to_settlement_gross"] is None
    ops = e1["operational_futility_inputs"]
    assert ops["t6_at_or_after_odds_pairing_yield"] == 1.0 and ops["trade_rate"]["value"] == 1.0
    assert ops["entries_per_week"]["mean"] == 4.0 and ops["entries_per_week"]["weeks_with_due_t6"] == 2


def test_no_t60m_target_is_a_missing_exit_after_kickoff_and_pending_before_it(tmp_path):
    path, now, ids = build_e1_store(tmp_path)
    store = SnapshotStore.open_readonly(path)
    rows, _, payloads, targets, _ = se._join(store, now, se.JoinPolicy(), results=False, horizons=se.GATE_HORIZONS,
                                             drop_settled=True)
    entries = se.e1_entries(rows, POLICY)
    no_t60 = [t for t in targets if t["offset_label"] != "T-60m"]
    full = se.kalshi_catalog(store, now, payloads)
    after = se._plain(se.e1_endpoint(entries, no_t60, full, payloads, as_of=now))
    x = _by_name(after, ids)["exit"]
    assert x["missing_exit"] == "NO_T60_TARGET" and x["exit_basis"] == se.E1_SETTLEMENT_FALLBACK
    assert after["attrition"]["missing_exit"]["NO_T60_TARGET"] == 8
    first_kickoff = KICKOFF
    before = se._plain(se.e1_endpoint(entries, no_t60, full, payloads, as_of=first_kickoff - timedelta(minutes=10)))
    assert {g["pending_reason"] for g in before["games"]} == {"NO_T60_TARGET_BEFORE_KICKOFF"}
    assert before["attrition"]["scored_primary"] == before["attrition"]["scored_exit_at_0_sensitivity"] == 0


def test_an_open_t60m_window_is_pending_and_its_book_is_never_read(tmp_path, monkeypatch):
    path, now, ids = build_e1_store(tmp_path)
    as_of = KICKOFF + timedelta(days=7) - timedelta(minutes=40)  # week 2: T-6h due, T-60m window still open
    loaded: list[int] = []
    original = se._Payloads.payload
    monkeypatch.setattr(se._Payloads, "payload", lambda self, sid: (loaded.append(sid), original(self, sid))[1])
    e1 = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=as_of, results=True, e1_bounds=BOUNDS)["e1"]
    g = _by_name(e1, ids)
    week2 = ("crossed", "exit_loss", "value_unknown", "conflict")
    for name in week2:
        assert g[name]["exit_basis"] == se.E1_PENDING and g[name]["pending_reason"] == "T60_WINDOW_OPEN", name
        assert g[name]["gross"] is None and g[name]["gross_exit_at_0"] is None, name
    assert e1["attrition"]["exit_pending"]["T60_WINDOW_OPEN"] == 4 and e1["attrition"]["exit_determined"] == 4
    week2_first = {ids["first"][e] for e, n in ids["games"].items() if n in week2 and e in ids["first"]}
    assert week2_first and not set(loaded) & week2_first


def test_the_label_free_path_reads_no_t60m_book_and_no_settlement(tmp_path, monkeypatch):
    path, now, ids = build_e1_store(tmp_path)
    loaded: list[int] = []
    calls: list[str] = []
    original = se._Payloads.payload
    monkeypatch.setattr(se._Payloads, "payload", lambda self, sid: (loaded.append(sid), original(self, sid))[1])
    for name in ("_first_book", "outcome_for", "_e1_settlement", "_e1_exit", "e1_endpoint"):
        real = getattr(se, name)
        monkeypatch.setattr(se, name, lambda *a, _n=name, _r=real, **k: (calls.append(_n), _r(*a, **k))[1])
    real_catalog = se.kalshi_catalog
    drops: list[tuple] = []
    monkeypatch.setattr(se, "kalshi_catalog", lambda store, as_of, payloads, drop_fields=(): (
        drops.append(tuple(drop_fields)), real_catalog(store, as_of, payloads, drop_fields))[1])
    out = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, e1_bounds=BOUNDS)
    assert not calls  # no T-60m window lookup, exit, outcome or settlement read
    assert drops == [se.SETTLED_LISTING_FIELDS]  # one catalog only, without the settled listing fields
    assert not set(loaded) & ids["T-60m"]
    e1 = out["e1"]
    assert e1["exit_and_pnl"].startswith("HIDDEN") and "games" not in e1 and "attrition" not in e1
    assert e1["counts"]["entries"] == 8 and e1["sides_by_reason"][se.E1_ELIGIBLE] == 8
    text = json.dumps(e1)
    for word in ("gross", "exit_basis", "t60_book", "settlement\"", "missing_exit", "payoff"):
        assert word not in text, word


def test_the_label_free_output_is_identical_with_or_without_t60m_books_and_settlements(tmp_path):
    with_labels, now, _ = build_e1_store(tmp_path, labels=True)
    without, now2, _ = build_e1_store(tmp_path, labels=False)
    assert now == now2
    a = se.measure_exp002(SnapshotStore.open_readonly(with_labels), as_of=now, e1_bounds=BOUNDS)["e1"]
    b = se.measure_exp002(SnapshotStore.open_readonly(without), as_of=now, e1_bounds=BOUNDS)["e1"]
    assert a == b  # no field, count or reason reveals whether a T-60m book or a settlement exists


def test_without_declared_bounds_no_entry_is_computed_on_a_store(tmp_path):
    path, now, _ = build_e1_store(tmp_path)
    e1 = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now)["e1"]
    assert e1["bounds_undeclared"] == 16 and e1["counts"]["entries"] == 0
    assert e1["bounds"]["tie_probability_bound"] is None and e1["bounds"]["source"].startswith("UNDECLARED")
    declared = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, e1_bounds=BOUNDS)
    assert declared["e1"]["bounds"]["source"].startswith("CALLER_DECLARED_CANDIDATE")
    assert declared["e1"]["bounds"]["tie_probability_bound"] == "0.01"
    plain = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now)
    # the E1 bounds never reach the gates: their inputs and outputs are the same with or without them
    assert declared["gate"] == plain["gate"] and declared["gate_v3"] == plain["gate_v3"]
    assert declared["policy"] == plain["policy"]


def test_gross_only_no_fee_is_applied_and_no_net_figure_exists(tmp_path):
    path, now, ids = build_e1_store(tmp_path)
    e1 = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, e1_bounds=BOUNDS)["e1"]
    assert "FEE_UNSUPPORTED" in e1["costs"] and "no fee is treated as 0" in e1["costs"]

    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)
    assert not [k for k in keys(e1) if "net" in k.lower() or "fee" in k.lower()]
    for g in e1["games"]:
        if g.get("exit_basis") in (se.E1_EXIT_BID, se.E1_SETTLEMENT_FALLBACK):
            assert D(g["gross"]) == D(g["exit_value"]) - D(g["ask6"])  # exactly: nothing subtracted


def test_the_e1_measurement_is_deterministic(tmp_path):
    path, now, _ = build_e1_store(tmp_path)
    a = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, e1_bounds=BOUNDS)
    b = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, e1_bounds=BOUNDS)
    assert a == b and a["output_sha256"] == b["output_sha256"]
    c = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, e1_bounds=BOUNDS)
    d = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, e1_bounds=BOUNDS)
    assert c["output_sha256"] == d["output_sha256"] != a["output_sha256"]


# ================================================================== CLI: labels only on the logged path


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


def test_cli_refuses_results_without_a_log_and_records_before_showing(tmp_path, monkeypatch):
    path, now, _ = build_e1_store(tmp_path)
    root, own = _registry_copy(tmp_path)
    base = ["exp002", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root),
            "--e1-tie-bound", "0.01", "--e1-postponement-bound", "0.005"]
    before = len(rev.read_log(own).uses)
    code, text = _run(base)
    assert code == 0 and json.loads(text)["e1"]["exit_and_pnl"].startswith("HIDDEN")
    assert len(rev.read_log(own).uses) == before  # the label-free run logs nothing
    code, text = _run(base + ["--with-results"])
    assert code == 2 and json.loads(text)["state"] == "REFUSED" and "gross" not in text and "exit_basis" not in text
    # a failed record shows nothing
    code, text = _run(base + ["--with-results", "--evidence-log", str(tmp_path / "other.jsonl"), "--actor", "t",
                              "--code-version", "abc"])
    assert code == 2 and json.loads(text)["state"] == "REFUSED" and "gross" not in text
    assert len(rev.read_log(own).uses) == before
    # the record happens before anything is printed: stdout is still empty when the view is recorded
    printed_at_record: list[str] = []
    real = se.record_markout_view

    def spy(*a, **k):
        printed_at_record.append(sys.stdout.getvalue())
        return real(*a, **k)

    monkeypatch.setattr(se, "record_markout_view", spy)
    code, text = _run(base + ["--with-results", "--evidence-log", str(own), "--actor", "test",
                              "--code-version", "abc123"])
    assert code == 0 and printed_at_record == [""]
    shown = json.loads(text)
    assert shown["evidence_use"] == "APPENDED" and shown["e1"]["attrition"]["trades"] == 8
    use = rev.read_log(own).uses[-1]
    assert len(rev.read_log(own).uses) == before + 1 and use.action is rev.Action.LABEL_RESULT_INSPECTION
    assert use.dataset_sha256 == shown["output_sha256"] and use.role is rev.DatasetRole.DEVELOPMENT
    assert se.E1_VERSION in use.note and "tie=0.01" in use.note and "postponement=0.005" in use.note
    assert use.viewed_labels and use.viewed_results


def test_cli_e1_bounds_go_together_and_are_validated(tmp_path, capsys):
    path, now, _ = build_e1_store(tmp_path)
    base = ["exp002", "--db", str(path), "--as-of", iso_z(now)]
    with pytest.raises(SystemExit):
        se.main(base + ["--e1-tie-bound", "0.01"])
    with pytest.raises(SystemExit):
        se.main(base + ["--e1-tie-bound", "1.5", "--e1-postponement-bound", "0.005"])
    # refused before the store opens (a missing store would otherwise answer NO_STORE with exit 1)
    missing = ["exp002", "--db", str(tmp_path / "absent.sqlite3"), "--as-of", iso_z(now)]
    for tie, post in (("abc", "0.005"), ("0.01", "NaN"), ("-0.01", "0.005"), ("0.6", "0.6"), ("inf", "0"),
                      ("0.01", "")):
        with pytest.raises(SystemExit) as refused:
            se.main(missing + ["--e1-tie-bound", tie, "--e1-postponement-bound", post, "--with-results"])
        assert refused.value.code == 2, (tie, post)
        assert "E1 bounds" in capsys.readouterr().err, (tie, post)
    assert se.e1_bounds_problem((D("0.5"), D("0.5"))) is None  # a sum of exactly 1 is allowed
    assert se.e1_bounds_problem((D("0.6"), D("0.6"))).startswith("tie + postponement")
    with pytest.raises(ValueError, match="E1 bounds"):
        se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, e1_bounds=(None, D("0.005")))
    capsys.readouterr()


def test_the_recorded_window_covers_e1_games_the_markout_does_not_show(tmp_path):
    # Week 2's home markets have no T-60m book: the markout shows only week 1, while E1 still scores the week-2
    # trades (missing exits at settlement), so the logged window must reach week 2's kickoff.
    specs = SPECS[:4] + [(name, [], settle) for name, _, settle in SPECS[4:]]
    path, now, ids = build_e1_store(tmp_path, specs=specs)
    root, own = _registry_copy(tmp_path)
    measured = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, e1_bounds=BOUNDS,
                                 experiments_root=root)
    markout_kickoffs = {g["commence_utc"] for g in measured["markout"]["games"]}
    e1_kickoffs = {g["commence_utc"] for g in measured["e1"]["games"]}
    assert markout_kickoffs and max(e1_kickoffs) > max(markout_kickoffs)  # E1 reaches beyond the markout
    week2 = [g for g in measured["e1"]["games"] if g["commence_utc"] == max(e1_kickoffs)]
    assert week2 and all(g["missing_exit"] == "NO_T60_BOOK" for g in week2)
    se.record_markout_view(measured, log=own, actor="test", code_version="abc123", experiments_root=root)
    window = rev.read_log(own).uses[-1].window
    assert window.start_utc == min(markout_kickoffs | e1_kickoffs) and window.end_utc == max(e1_kickoffs)


def test_cli_out_summary_names_the_e1_state(tmp_path):
    path, now, _ = build_e1_store(tmp_path)
    code, text = _run(["exp002", "--db", str(path), "--as-of", iso_z(now), "--out", str(tmp_path / "m.json")])
    assert code == 0 and json.loads(text)["e1_state"] == se.E1_STATE and json.loads(text)["freeze_eligible"] is False
    written = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert written["e1"]["bounds_undeclared"] == 16 and "games" not in written["e1"]
