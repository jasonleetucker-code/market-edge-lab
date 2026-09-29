"""In-play evidence contract v1 (#122 §13): reconstruction, clocks, game state, coverage."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab import inplay_evidence as ev
from edge_lab.inplay_evidence import Applied, BookStatus
from edge_lab.opportunity import DepthStatus, OutcomeFinality

FIXTURE = Path(__file__).parent / "fixtures" / "inplay" / "ws_orderbook_journal_fixture.jsonl"
TICKER = "KXNFLGAME-FIXTURE-HOME"


def snap(seq, yes, no=(), *, sid=1, at="2026-10-04T17:00:00Z", ticker=TICKER):
    raw = {"type": "orderbook_snapshot", "sid": sid, "seq": seq,
           "msg": {"market_ticker": ticker, "yes_dollars_fp": [list(x) for x in yes],
                   "no_dollars_fp": [list(x) for x in no]}}
    return ev.parse_book_message(raw, receipt_utc=at)


def delta(seq, price, qty, side="yes", *, sid=1, at="2026-10-04T17:00:01Z", ts_ms=None):
    body = {"market_ticker": TICKER, "price_dollars": price, "delta_fp": qty, "side": side}
    if ts_ms is not None:
        body["ts_ms"] = ts_ms
    return ev.parse_book_message({"type": "orderbook_delta", "sid": sid, "seq": seq, "msg": body}, receipt_utc=at)


# ------------------------------------------------------------------ valid start, sequence, duplicates, gaps


def test_delta_before_any_snapshot_is_ignored_and_the_book_stays_unusable():
    state, ts = ev.reconstruct(TICKER, [delta(1, "0.30", "5.00")])
    assert ts[0].applied is Applied.IGNORED_BEFORE_START
    assert state.status is BookStatus.NO_VALID_START and not state.usable
    assert state.yes_bids == () and state.best_yes_bid() is None


def test_snapshot_then_contiguous_deltas_reconstruct_the_book():
    state, ts = ev.reconstruct(TICKER, [snap(5, [("0.30", "100.00")], [("0.60", "50.00")]),
                                         delta(6, "0.31", "40.00"), delta(7, "0.30", "-100.00")])
    assert [t.applied for t in ts] == [Applied.SNAPSHOT_APPLIED, Applied.DELTA_APPLIED, Applied.DELTA_APPLIED]
    assert state.usable and state.yes_bids == ((D("0.31"), D("40.00")),)
    assert state.best_no_bid() == (D("0.60"), D("50.00"))


def test_duplicate_seq_is_ignored_not_applied_twice():
    state, ts = ev.reconstruct(TICKER, [snap(1, [("0.30", "10.00")]), delta(2, "0.30", "5.00"),
                                         delta(2, "0.30", "5.00")])
    assert ts[-1].applied is Applied.IGNORED_DUPLICATE
    assert state.yes_bids == ((D("0.30"), D("15.00")),) and state.count(Applied.IGNORED_DUPLICATE) == 1


def test_gap_makes_the_book_unusable_until_a_new_snapshot():
    msgs = [snap(1, [("0.30", "10.00")]), delta(3, "0.40", "5.00"), delta(2, "0.35", "5.00"),
            delta(4, "0.45", "5.00")]
    state, ts = ev.reconstruct(TICKER, msgs)
    assert ts[1].applied is Applied.GAP_DETECTED
    # the late seq 2 does not repair the book (no reorder buffer in v1): still unusable
    assert [t.applied for t in ts[2:]] == [Applied.IGNORED_WHILE_UNUSABLE] * 2
    assert state.status is BookStatus.GAP_AWAITING_RESYNC and state.best_yes_bid() is None
    state2, ts2 = ev.reconstruct(TICKER, msgs + [snap(9, [("0.50", "7.00")])])
    assert ts2[-1].applied is Applied.RESYNCED and state2.usable


def test_delta_from_another_subscription_is_a_gap():
    state, ts = ev.reconstruct(TICKER, [snap(1, [("0.30", "10.00")], sid=1), delta(2, "0.31", "1.00", sid=2)])
    assert ts[-1].applied is Applied.GAP_DETECTED and not state.usable


def test_negative_level_and_crossed_book_are_unusable():
    s1, t1 = ev.reconstruct(TICKER, [snap(1, [("0.30", "10.00")]), delta(2, "0.30", "-11.00")])
    assert t1[-1].applied is Applied.NEGATIVE_LEVEL and s1.status is BookStatus.INVALID_AWAITING_RESYNC
    s2, t2 = ev.reconstruct(TICKER, [snap(1, [("0.30", "10.00")], [("0.60", "5.00")]), delta(2, "0.40", "1.00")])
    assert t2[-1].applied is Applied.CROSSED_BOOK and not s2.usable
    s3, t3 = ev.reconstruct(TICKER, [snap(1, [("0.50", "1.00")], [("0.50", "1.00")])])
    assert t3[-1].applied is Applied.CROSSED_BOOK and not s3.usable


def test_snapshot_without_sequence_cannot_start_a_book():
    raw = {"type": "orderbook_snapshot", "msg": {"market_ticker": TICKER, "yes_dollars_fp": [["0.30", "1.00"]]}}
    state, ts = ev.reconstruct(TICKER, [ev.parse_book_message(raw, receipt_utc="2026-10-04T17:00:00Z")])
    assert ts[0].applied is Applied.SNAPSHOT_WITHOUT_SEQ and not state.usable


def test_wrong_market_message_changes_nothing():
    state, ts = ev.reconstruct(TICKER, [snap(1, [("0.30", "1.00")]), snap(1, [("0.90", "1.00")], ticker="OTHER")])
    assert ts[-1].applied is Applied.WRONG_MARKET and state.yes_bids == ((D("0.30"), D("1.00")),)


def test_apply_is_pure():
    base = ev.BookState(TICKER)
    t = ev.apply_message(base, snap(1, [("0.30", "1.00")]))
    assert base.status is BookStatus.NO_VALID_START and t.state.usable


# ------------------------------------------------------------------ units, scale, parse failures


@pytest.mark.parametrize("price,qty,reason", [
    ("30", "1.00", "BAD_VALUE"),  # cents, not dollars: refused, never rescaled
    ("0.30", "1.005", "BAD_VALUE"),  # off the 0.01 contract step
    ("1.00", "1.00", "BAD_VALUE"),  # a price must be strictly inside (0, 1)
    ("0.30001", "1.00", "BAD_VALUE"),  # finer than 1/100 cent
    ("0.30", "0", "ZERO_DELTA"),
])
def test_unit_scale_and_rounding_are_refused_not_guessed(price, qty, reason):
    out = delta(2, price, qty)
    assert isinstance(out, ev.ParseFailure) and out.reason == reason


def test_unknown_type_and_missing_market_are_parse_failures():
    assert ev.parse_book_message({"type": "ticker", "msg": {}}, receipt_utc="2026-10-04T17:00:00Z").reason \
        == "UNKNOWN_TYPE"
    assert ev.parse_book_message({"type": "orderbook_delta", "msg": "x"}, receipt_utc="2026-10-04T17:00:00Z"
                                 ).reason == "NO_MARKET"


# ------------------------------------------------------------------ clocks


def test_four_clocks_stay_separate_and_source_time_is_never_invented():
    m = delta(2, "0.30", "1.00", at="2026-10-04T17:00:05Z", ts_ms=1790960404000)
    assert m.stamps.receipt_utc == "2026-10-04T17:00:05Z"
    assert m.stamps.source_ts_utc.startswith("2026-")  # from ts_ms, kept apart
    assert m.stamps.processing_utc is None
    m2 = delta(2, "0.30", "1.00")
    assert m2.stamps.source_ts_utc is None  # no ts_ms: unknown, not the receipt time


def test_first_observation_cannot_postdate_receipt():
    with pytest.raises(ValueError):
        ev.Stamps(receipt_utc="2026-10-04T17:00:00Z", first_observed_utc="2026-10-04T17:00:01Z")
    with pytest.raises(ValueError):
        ev.Stamps(receipt_utc="2026-10-04T17:00:00", first_observed_utc="2026-10-04T17:00:00")  # naive


# ------------------------------------------------------------------ REST snapshots and sale walks


def test_rest_snapshot_has_no_sequence_and_keeps_anomalies():
    ok = ev.rest_snapshot(TICKER, {"orderbook_fp": {"yes_dollars": [["0.30", "10.00"]], "no_dollars": []}},
                          receipt_utc="2026-10-04T17:00:00Z", depth_limit=1)
    assert ok.anomaly is None and ok.truncated_yes
    crossed = ev.rest_snapshot(TICKER, {"orderbook_fp": {"yes_dollars": [["0.60", "1"]], "no_dollars": [["0.40", "1"]]}},
                               receipt_utc="2026-10-04T17:00:00Z", depth_limit=None)
    assert crossed.anomaly == "CROSSED" and crossed.yes_bids == ()
    assert ev.rest_snapshot(TICKER, {}, receipt_utc="2026-10-04T17:00:00Z", depth_limit=None).anomaly == "NO_BOOK"


def test_sale_walk_reuses_the_canonical_depth_walk():
    bids = ((D("0.68"), D("50")), (D("0.70"), D("30")), (D("0.72"), D("20")))
    w = ev.walk_bids(bids, D("40"))
    assert w.status is DepthStatus.FILLABLE
    assert w.levels == ((D("0.72"), D("20")), (D("0.70"), D("20")))
    assert w.gross_proceeds == D("0.72") * 20 + D("0.70") * 20 and w.worst_price == D("0.70")


def test_sale_walk_under_a_limit_and_on_truncated_or_empty_depth():
    bids = ((D("0.68"), D("50")), (D("0.70"), D("30")))
    limited = ev.walk_bids(bids, D("40"), min_price=D("0.70"), truncated=True)
    assert limited.status is DepthStatus.INSUFFICIENT_DEPTH and limited.gross_proceeds is None
    truncated = ev.walk_bids(bids, D("100"), truncated=True)
    assert truncated.status is DepthStatus.DEPTH_UNKNOWN and truncated.gross_proceeds is None
    empty = ev.walk_bids((), D("1"))
    assert empty.status is DepthStatus.INSUFFICIENT_DEPTH and empty.gross_proceeds is None


def test_trading_state_is_unknown_unless_both_flags_are_true():
    assert ev.trading_state({"exchange_active": False, "trading_active": False}, "active") \
        is ev.TradingState.EXCHANGE_PAUSED
    assert ev.trading_state({"exchange_active": True, "trading_active": False}, "active") \
        is ev.TradingState.TRADING_PAUSED
    assert ev.trading_state({"exchange_active": True}, "active") is ev.TradingState.UNKNOWN
    assert ev.trading_state(None, "active") is ev.TradingState.UNKNOWN
    assert ev.trading_state({"exchange_active": True, "trading_active": True}, "closed") \
        is ev.TradingState.MARKET_CLOSED
    assert ev.trading_state({"exchange_active": True, "trading_active": True}, "active") is ev.TradingState.OPEN


# ------------------------------------------------------------------ game state


FMAP = {"home_score": "home_points", "away_score": "away_points", "period": "period", "game_clock_text": "clock"}


def gs(payload, at, event_id="play-17"):
    return ev.game_state_from_payload("G1", payload, source_id="fixture-feed", receipt_utc=at,
                                      source_event_id=event_id, field_map=FMAP)


def test_overturned_score_keeps_the_provisional_observation():
    j = ev.GameJournal("G1")
    j = j.append(gs({"home_points": 7, "away_points": 0, "period": "Q2", "clock": "05:12"}, "2026-10-04T18:00:00Z"))
    j = j.append(gs({"home_points": 7, "away_points": 0, "period": "Q2", "clock": "05:12"}, "2026-10-04T18:00:03Z"))
    j = j.append(gs({"home_points": 0, "away_points": 0, "period": "Q2", "clock": "05:12"}, "2026-10-04T18:02:00Z"))
    kinds = [k for k, _ in j.entries]
    assert kinds == [ev.JournalEntry.NEW, ev.JournalEntry.DUPLICATE, ev.JournalEntry.CORRECTION]
    before = ev.game_state_as_of(j, "2026-10-04T18:01:00Z")
    after = ev.game_state_as_of(j, "2026-10-04T18:03:00Z")
    assert before.home_score == 7 and before.corrects is None  # what we actually saw then
    assert after.home_score == 0 and after.corrects == j.entries[0][1].observation_id
    assert j.entries[0][1].home_score == 7  # nothing was overwritten
    assert ev.game_state_as_of(j, "2026-10-04T17:59:00Z") is None


def test_null_game_stats_is_unsupported_and_unmapped_fields_stay_unknown():
    null = ev.game_state_from_payload("G1", None, source_id="kalshi-game-stats", receipt_utc="2026-10-04T18:00:00Z")
    assert null.status is ev.GameStateStatus.UNSUPPORTED_OR_UNMAPPED and null.home_score is None
    # no field map: the undocumented Kalshi schema is not guessed
    raw = ev.game_state_from_payload("G1", {"pbp": {"periods": []}, "home_points": 3}, source_id="kalshi-game-stats",
                                     receipt_utc="2026-10-04T18:00:00Z")
    assert raw.status is ev.GameStateStatus.OBSERVED and raw.home_score is None and raw.period is None
    assert raw.finality is OutcomeFinality.UNKNOWN
    bad = gs({"home_points": "7", "away_points": -1}, "2026-10-04T18:00:00Z")
    assert bad.home_score is None and bad.away_score is None  # missing is not zero, strings are not scores


# ------------------------------------------------------------------ coverage and the file transport


def test_fixture_journal_reconstruction_with_gap_reconnect_and_failures():
    state, ts, failures, parse_failures, kind = ev.replay_book_journal(FIXTURE, TICKER)
    assert kind is ev.DataKind.FIXTURE
    applied = [t.applied for t in ts]
    assert applied[0] is Applied.IGNORED_BEFORE_START
    assert Applied.IGNORED_DUPLICATE in applied and Applied.GAP_DETECTED in applied
    assert Applied.RESYNCED in applied
    # reconnect after the price moved: the new book is the snapshot's, not an interpolation
    assert state.usable and state.sid == 2
    assert state.yes_bids == ((D("0.7000"), D("60.00")), (D("0.7200"), D("20.00")))
    assert parse_failures == 2 and {f.kind for f in failures} == {ev.FailureKind.DISCONNECTED, ev.FailureKind.PARSE_ERROR}


def test_coverage_counts_unusable_and_silent_time_and_keeps_failures():
    _, ts, failures, pf, _ = ev.replay_book_journal(FIXTURE, TICKER)
    rep = ev.coverage_report(TICKER, ts, window_start="2026-10-04T17:00:00Z", window_end="2026-10-04T17:00:30Z",
                             max_silence=timedelta(seconds=3), failures=failures, parse_failures=pf)
    buckets = dict(rep.unusable_seconds_by_reason)
    assert rep.gaps == 1 and rep.resyncs == 1 and rep.duplicates == 1 and rep.ignored_before_start == 1
    assert buckets["GAP_AWAITING_RESYNC"] == D("3")  # 17:00:09 -> 17:00:12
    assert buckets["NO_VALID_START"] == D("1")
    assert "SILENT_UNKNOWN" in buckets  # silence after the last message is not assumed usable
    assert len(rep.failures) == 3 and rep.parse_failures == 2
    total = rep.usable_seconds + sum(buckets.values())
    assert total == D("30") and D(0) < rep.coverage_fraction < D(1)


def test_journal_requires_a_header(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text(json.dumps({"receipt_utc": "2026-10-04T17:00:00Z", "kind": "book", "body": {}}) + "\n")
    with pytest.raises(ValueError):
        list(ev.read_journal(p))
