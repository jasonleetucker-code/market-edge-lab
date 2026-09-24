"""Sportsbook consensus research benchmark (#9, ADR 0033). Fixtures only; no network.

Synthetic payloads follow the provider's documented v4 odds shape (list of events, each with
bookmakers -> markets -> outcomes {name, price, point}); the documented sample fixture is reused.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from edge_lab import cli
from edge_lab import odds_api as oa
from edge_lab import odds_consensus as oc
from edge_lab.freshness import Freshness
from edge_lab.opportunity import ExecutableQuote
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
SPORT = "americanfootball_nfl"
FIXTURE = Path(__file__).parent / "fixtures" / "odds_api" / "v4_odds_nfl_h2h_spreads_american_documented.json"
SRC = Path(__file__).resolve().parents[1] / "src" / "edge_lab"
URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey=REDACTED&regions=us&markets=h2h&oddsFormat="


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the consensus benchmark attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def book(key: str, markets: list[dict], *, last_update: str | None = None) -> dict:
    out = {"key": key, "title": key.title(), "markets": markets}
    if last_update is not None:
        out["last_update"] = last_update
    return out


def market(key: str, outcomes: list[tuple], *, last_update: str | None = None) -> dict:
    rows = []
    for o in outcomes:
        row = {"name": o[0], "price": o[1]}
        if len(o) > 2:
            row["point"] = o[2]
        rows.append(row)
    out = {"key": key, "outcomes": rows}
    if last_update is not None:
        out["last_update"] = last_update
    return out


def event(eid: str, books: list[dict], *, home="Home", away="Away", commence=T0 + timedelta(days=1)) -> dict:
    return {"id": eid, "sport_key": SPORT, "sport_title": "NFL", "commence_time": iso(commence),
            "home_team": home, "away_team": away, "bookmakers": books}


def h2h(home_price, away_price, **kw) -> dict:
    return market("h2h", [("Home", home_price), ("Away", away_price)], **kw)


def spread(line: float, home_price=-110, away_price=-110, **kw) -> dict:
    """Home gives `line` points, Away gets them: the clean complement."""
    return market("spreads", [("Home", home_price, -line), ("Away", away_price, line)], **kw)


@pytest.fixture
def store(tmp_path):
    s = SnapshotStore(tmp_path / "evidence.sqlite3")
    s.start_run("run-1")
    return s


def save(store, events, *, at=T0, fmt="american", request=True, url_fmt=True, targets=()) -> int:
    payload = {"sport": SPORT, "events": events}
    if request:
        payload["request"] = {"purpose": "capture", "odds_format": fmt, "slot_id": "slot-1",
                              "targets": [dict(t) for t in targets]}
    url = URL + fmt if url_fmt else URL[: -len("&oddsFormat=")]
    return store.save_snapshot(run_id="run-1", source="the_odds_api", kind="odds", entity_id=SPORT, url=url,
                               payload=payload, fetched_at_utc=at.isoformat(), source_id="the_odds_api")


def props(result, market_key=None):
    out = [p for e in result.events for p in e.propositions]
    return [p for p in out if market_key is None or p.market_key == market_key]


def walk(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


# ================================================================== grouping by exact line


def test_spreads_and_totals_are_grouped_by_exact_normalized_line_and_never_combined(store):
    up = iso(T0 - timedelta(minutes=1))
    books = [
        book("draftkings", [market("spreads", [("Home", -110, -2.5), ("Away", -110, 2.5)], last_update=up),
                            market("totals", [("Over", -105, 44.5), ("Under", -115, 44.5)], last_update=up)]),
        book("fanduel", [market("spreads", [("Home", -105, "-2.50"), ("Away", -115, "2.5")], last_update=up),
                         market("totals", [("Over", -110, "44.50"), ("Under", -110, "44.5")], last_update=up)]),
        book("betmgm", [market("spreads", [("Home", -120, -3), ("Away", 100, 3.0)], last_update=up),
                        market("totals", [("Over", -110, 45), ("Under", -110, 45)], last_update=up)]),
        book("caesars", [market("spreads", [("Home", -110, -3.5), ("Away", -110, 3.5)], last_update=up)]),
    ]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)]))
    spreads = {p.outcomes: p for p in props(result, "spreads")}
    assert set(spreads) == {(("Away", "2.5"), ("Home", "-2.5")), (("Away", "3"), ("Home", "-3")),
                            (("Away", "3.5"), ("Home", "-3.5"))}
    two_five = spreads[(("Away", "2.5"), ("Home", "-2.5"))]
    assert two_five.status is oc.ConsensusStatus.SUPPORTED and two_five.contributing_book_count == 2
    assert [b.bookmaker for b in two_five.books] == ["draftkings", "fanduel"]
    assert {o.point for o in two_five.offered} == {"-2.5", "2.5", "-2.50"}  # as received, not rewritten
    for line in ("3", "3.5"):
        one = next(p for k, p in spreads.items() if k[0][1] == line)
        assert one.status is oc.ConsensusStatus.INSUFFICIENT_BOOKS and one.contributing_book_count == 1
        assert all(c.consensus_probability is None for c in one.consensus)  # one book is not a consensus
        assert one.market_bookmaker_count == 4  # the other books quoted other lines; they are not zeros
    totals = {p.outcomes: p for p in props(result, "totals")}
    assert set(totals) == {(("Over", "44.5"), ("Under", "44.5")), (("Over", "45"), ("Under", "45"))}
    assert totals[(("Over", "44.5"), ("Under", "44.5"))].contributing_book_count == 2


def test_legacy_consensus_by_market_uses_the_same_exact_pairing_and_the_abs_line_is_normalized():
    books = [book("a", [market("spreads", [("Home", 1.9, "-2.50"), ("Away", 1.9, "2.5")])]),
             book("b", [market("spreads", [("Home", 1.8, -2.5), ("Away", 2.0, 2.5)])]),
             book("c", [market("h2h", [("Home", 2.5), ("Away", 3.0), ("Draw", 3.2)])]),
             book("d", [market("h2h", [("Home", 2.4), ("Away", 3.1), ("Draw", 3.3)])])]
    snap = oa.parse_odds([event("g1", books)], odds_format="decimal")
    assert oa.devig_by_market(snap)[("the_odds_api:g1", "a", "spreads:2.5")] is not None  # "2.50" pairs with "2.5"
    legacy = oa.consensus_by_market(snap)
    assert list(legacy) == [("the_odds_api:g1", "spreads", (("Away", "2.5"), ("Home", "-2.5")))]
    assert all(k[1] != "h2h" for k in legacy)  # the three-way h2h is never pooled


# ================================================================== vig removal math


def test_paired_devig_math_is_exact_proportional_normalization(store):
    up = iso(T0)
    books = [book("a", [h2h(1.8, 2.1, last_update=up)]), book("b", [h2h(1.9, 2.0, last_update=up)])]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)], fmt="decimal"))
    (p,) = props(result, "h2h")
    assert p.outcomes == (("Away", None), ("Home", None))  # canonical (sorted) order
    with localcontext() as ctx:
        ctx.prec = 28
        ia, ha = Decimal(1) / Decimal("2.1"), Decimal(1) / Decimal("1.8")
        ib, hb = Decimal(1) / Decimal("2.0"), Decimal(1) / Decimal("1.9")
        a_away, b_away = ia / (ia + ha), ib / (ib + hb)
        assert p.books[0].implied_with_margin == (ia, ha)
        assert p.books[0].overround == ia + ha - 1
        assert p.books[0].probabilities == (a_away, ha / (ia + ha))
        assert p.consensus[0].consensus_probability == (a_away + b_away) / 2  # even count: mean of the two
        assert p.consensus[0].range == abs(a_away - b_away)
    assert abs(sum(c.consensus_probability for c in p.consensus) - 1) < Decimal("1e-20")
    for b in p.books:
        assert sum(b.implied_with_margin) > 1 and abs(sum(b.probabilities) - 1) < Decimal("1e-20")


def test_american_prices_convert_and_the_offered_price_stays_as_received(store):
    books = [book("a", [h2h(-150, 130)]), book("b", [h2h(-140, 120)])]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)]))
    (p,) = props(result, "h2h")
    offered = {(o.bookmaker, o.outcome_name): o for o in p.offered}
    home = offered[("a", "Home")]
    assert home.raw_price == "-150" and home.odds_format == "american" and home.decimal_odds == Decimal(1) + Decimal(100) / 150
    assert home.implied_probability_with_margin == Decimal(1) / home.decimal_odds
    assert home.label == oc.OFFERED_LABEL and home.executable is False


@pytest.mark.parametrize("values,med,mad", [
    (["0.3", "0.5", "0.4"], "0.4", "0.1"),
    (["0.3", "0.5", "0.4", "0.9"], "0.45", "0.1"),  # |dev| 0.15 0.05 0.05 0.45 -> median 0.1
    (["0.52"], "0.52", "0"),
])
def test_median_and_mad_for_odd_and_even_counts(values, med, mad):
    ds = [Decimal(v) for v in values]
    assert oa.median(ds) == Decimal(med) and oa.median_absolute_deviation(ds) == Decimal(mad)
    with pytest.raises(ValueError):
        oa.median([])


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_book_count_and_median_use_every_contributing_book(store, n):
    prices = [(1.5 + 0.1 * i, 2.8 - 0.1 * i) for i in range(n)]
    books = [book(f"book{i}", [h2h(h, a)]) for i, (h, a) in enumerate(prices)]
    (p,) = props(oc.consensus_for_snapshot(store, save(store, [event("g1", books)], fmt="decimal")), "h2h")
    home = sorted(b.probabilities[1] for b in p.books)
    expected = home[n // 2] if n % 2 else (home[n // 2 - 1] + home[n // 2]) / 2
    assert p.contributing_book_count == n == p.consensus[1].book_count
    assert p.consensus[1].consensus_probability == expected
    assert p.consensus[1].min_probability == home[0] and p.consensus[1].max_probability == home[-1]
    assert p.consensus[1].range == home[-1] - home[0]
    assert p.consensus[1].mad == oa.median_absolute_deviation(home)
    assert p.consensus[1].dispersion_method == oc.DISPERSION_METHOD


# ================================================================== unsupported shapes


def unsupported(result):
    return {(u.market_key, u.status): u for e in result.events for u in e.unsupported}


def test_three_way_h2h_and_draws_are_unsupported_with_a_reason(store):
    books = [book("a", [market("h2h", [("Home", 2.5), ("Away", 3.0), ("Draw", 3.2)])]),
             book("b", [market("h2h", [("Home", 2.4), ("Tie", 3.1)])])]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)], fmt="decimal"))
    assert props(result) == []
    group = unsupported(result)[("h2h", "NOT_TWO_WAY")]
    assert group.bookmakers == ("a", "b") and group.consensus_status is oc.ConsensusStatus.UNSUPPORTED
    assert any("three-way" in r for r in group.reasons) and len(group.offered) == 5


def test_missing_and_non_opposite_sides_are_excluded_not_zero(store):
    books = [book("a", [spread(3.5)]), book("b", [spread(3.5)]),
             book("c", [market("spreads", [("Home", -110, -3.5)])]),  # one side only
             book("d", [market("spreads", [("Home", -110, -3), ("Away", -110, -3)])]),  # not opposite
             book("e", [market("totals", [("Over", -110, 44.5), ("Under", -110, 45.5)])])]  # different points
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)]))
    (p,) = props(result, "spreads")
    assert p.contributing_book_count == 2 and p.market_bookmaker_count == 4
    groups = unsupported(result)
    missing = [u for e in result.events for u in e.unsupported if u.status == "MISSING_COMPLEMENT"]
    assert {(u.market_key, u.line): u.bookmakers for u in missing} == {
        ("spreads", "-3.5"): ("c",), ("spreads", "-3"): ("d",),  # d: Home -3 and Away -3 are not opposite
        ("totals", "44.5"): ("e",), ("totals", "45.5"): ("e",)}
    assert all(o.executable is False for u in missing for o in u.offered)
    assert all("not an exact opposite line" in r for u in missing for r in u.reasons)
    assert props(result, "totals") == []


def test_duplicates_invalid_prices_lines_names_and_markets_are_refused(store):
    books = [book("dup", [market("spreads", [("Home", -110, -3.5), ("Home", -105, -3.5), ("Away", -110, 3.5)])]),
             book("badprice", [h2h("abc", 120)]),
             book("badline", [market("totals", [("Over", -110, "x"), ("Under", -110, "x")])]),
             book("names", [market("totals", [("Yes", -110, 44.5), ("No", -110, 44.5)])]),
             book("strangers", [market("h2h", [("Other", -110), ("Team", -110)])]),
             book("lay", [market("h2h_lay", [("Home", 2.0), ("Away", 2.0)])])]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)]))
    assert props(result) == []
    statuses = {(u.market_key, u.status): u.bookmakers for e in result.events for u in e.unsupported}
    assert statuses[("spreads", "AMBIGUOUS_COMPLEMENT")] == ("dup",)
    assert statuses[("h2h", "INVALID_PRICE")] == ("badprice",)
    assert statuses[("totals", "INVALID_LINE")] == ("badline",)
    assert statuses[("totals", "UNRECOGNIZED_OUTCOME")] == ("names",)
    assert statuses[("h2h", "UNRECOGNIZED_OUTCOME")] == ("strangers",)
    assert statuses[("h2h_lay", "MARKET_NOT_SUPPORTED")] == ("lay",)
    assert any(p.startswith("PARSE:") and "invalid price" in p for p in result.problems)


def test_pick_em_spread_pairs_zero_with_zero(store):
    books = [book("a", [market("spreads", [("Home", -110, 0), ("Away", -110, "-0.0")])]),
             book("b", [market("spreads", [("Home", -105, "0.0"), ("Away", -115, 0)])])]
    (p,) = props(oc.consensus_for_snapshot(store, save(store, [event("g1", books)])), "spreads")
    assert p.outcomes == (("Away", "0"), ("Home", "0")) and p.status is oc.ConsensusStatus.SUPPORTED


# ================================================================== freshness and update bounds


def test_per_book_and_aggregate_freshness_and_update_bounds(store):
    books = [book("fresh", [h2h(-110, -110, last_update=iso(T0 - timedelta(minutes=2)))],
                  last_update=iso(T0 - timedelta(minutes=1))),
             book("stale", [h2h(-120, 100, last_update=iso(T0 - timedelta(minutes=30)))]),
             book("bookonly", [h2h(-115, -105)], last_update=iso(T0 - timedelta(minutes=4))),
             book("unknown", [h2h(-110, -110)]),
             book("future", [h2h(-110, -110, last_update=iso(T0 + timedelta(minutes=20)))])]
    (p,) = props(oc.consensus_for_snapshot(store, save(store, [event("g1", books)])), "h2h")
    by = {b.bookmaker: b for b in p.books}
    assert by["fresh"].freshness_at_receipt is Freshness.FRESH and by["fresh"].update_basis == "market"
    assert by["fresh"].age_at_receipt_seconds == 120
    assert by["stale"].freshness_at_receipt is Freshness.STALE
    assert by["bookonly"].update_basis == "bookmaker" and by["bookonly"].freshness_at_receipt is Freshness.FRESH
    assert by["unknown"].update_basis is None and by["unknown"].freshness_at_receipt is Freshness.UNKNOWN
    assert by["unknown"].age_at_receipt_seconds is None
    assert by["future"].freshness_at_receipt is Freshness.UNKNOWN  # a future timestamp is a clock problem
    assert p.freshness_at_receipt is Freshness.UNKNOWN  # the worst book decides
    assert p.market_update == oc.UpdateBounds(iso(T0 - timedelta(minutes=30)), iso(T0 + timedelta(minutes=20)), 3, 2)
    assert p.bookmaker_update == oc.UpdateBounds(iso(T0 - timedelta(minutes=4)), iso(T0 - timedelta(minutes=1)), 2, 3)
    only_fresh = [book(k, [h2h(-110, -110, last_update=iso(T0 - timedelta(minutes=1)))]) for k in ("a", "b")]
    (q,) = props(oc.consensus_for_snapshot(store, save(store, [event("g2", only_fresh)])), "h2h")
    assert q.freshness_at_receipt is Freshness.FRESH


def test_unknown_receipt_time_makes_every_book_unknown_and_is_never_known_by_an_as_of(store):
    row = {"id": 7, "fetched_at_utc": "2026-10-04 12:00:00", "url": URL + "american",
           "payload_json": json.dumps({"events": [event("g1", [book("a", [h2h(-110, -110, last_update=iso(T0))]),
                                                               book("b", [h2h(-110, -110, last_update=iso(T0))])])],
                                       "request": {"odds_format": "american"}}, sort_keys=True,
                                      separators=(",", ":"))}
    row["payload_sha256"] = hashlib.sha256(row["payload_json"].encode()).hexdigest()
    result = oc.build_snapshot_consensus(row)
    assert result.received_at_utc is None and any(p.startswith("RECEIPT_TIME_UNKNOWN") for p in result.problems)
    assert all(b.freshness_at_receipt is Freshness.UNKNOWN for p in props(result) for b in p.books)
    assert oc._known_at(row, T0 + timedelta(days=1)) is False


# ================================================================== fail closed on inputs


def test_unknown_or_conflicting_odds_format_and_hash_mismatch_fail_closed(store):
    books = [book("a", [h2h(-110, -110)]), book("b", [h2h(-110, -110)])]
    none = oc.consensus_for_snapshot(store, save(store, [event("g1", books)], request=False, url_fmt=False))
    assert none.events == () and none.problems[0].startswith("ODDS_FORMAT_UNKNOWN")
    from_url = oc.consensus_for_snapshot(store, save(store, [event("g1", books)], request=False))
    assert from_url.odds_format == "american" and props(from_url)
    sid = save(store, [event("g1", books)], fmt="decimal")
    row = dict(store.snapshots_by_id([sid])[sid])
    row["url"] = URL + "american"
    conflict = oc.build_snapshot_consensus(row)
    assert conflict.events == () and conflict.problems[0].startswith("ODDS_FORMAT_CONFLICT")
    original = dict(store.snapshots_by_id([sid])[sid])
    tampered = original | {"payload_json": original["payload_json"].replace("-110", "-111")}
    bad = oc.build_snapshot_consensus(tampered)
    assert bad.events == () and bad.problems[0].startswith("PAYLOAD_HASH_MISMATCH")


# ================================================================== point in time


def test_point_in_time_reads_use_only_snapshots_received_by_as_of(store):
    early = [book("a", [h2h(-110, -110)]), book("b", [h2h(-110, -110)])]
    late = [book("a", [h2h(-200, 170)]), book("b", [h2h(-190, 160)])]
    s1 = save(store, [event("g1", early), event("g2", early)], at=T0)
    s2 = save(store, [event("g1", late)], at=T0 + timedelta(hours=6))
    save(store, [event("g2", late)], at=T0 + timedelta(hours=7))
    assert oc.consensus_for_event(store, "g1", T0 - timedelta(seconds=1)) is None
    at_t0 = oc.consensus_for_event(store, "g1", T0)
    assert at_t0.snapshot_id == s1 and [e.event_id for e in at_t0.events] == ["g1"]
    assert at_t0.as_of_utc == iso(T0) and at_t0.freshness_as_of is Freshness.FRESH
    later = oc.consensus_for_event(store, "the_odds_api:g1", T0 + timedelta(hours=9))
    assert later.snapshot_id == s2 and later.freshness_as_of is Freshness.STALE
    series = oc.consensus_series_for_event(store, "g1", as_of=T0 + timedelta(hours=9))
    assert [s.snapshot_id for s in series] == [s1, s2]
    with pytest.raises(oc.PointInTimeError):
        oc.consensus_for_snapshot(store, s2, as_of=T0 + timedelta(hours=1))
    with pytest.raises(ValueError):
        oc.consensus_for_event(store, "g1", datetime(2026, 10, 4, 12))  # naive: refused
    assert oc.consensus_for_snapshot(store, 999) is None
    assert [s.snapshot_id for s in oc.consensus_since(store, T0 + timedelta(hours=1))] == [s2, s2 + 1]
    assert [s.snapshot_id for s in oc.consensus_since(store, as_of=T0 + timedelta(hours=6))] == [s1, s2]


def test_capture_targets_from_the_stored_request_are_attached_per_event(store):
    books = [book("a", [h2h(-110, -110)]), book("b", [h2h(-110, -110)])]
    targets = [{"target_id": "t1", "event_id": "g1", "offset": "T-60m", "target_utc": iso(T0)},
               {"target_id": "t2", "event_id": "g2", "offset": "T-6h", "target_utc": iso(T0)}]
    save(store, [event("g1", books)], targets=targets)
    result = oc.consensus_for_event(store, "g1", T0 + timedelta(minutes=1))
    assert result.events[0].capture_targets == (oc.CaptureTarget("t1", "T-60m", iso(T0)),)
    assert result.purpose == "capture" and result.slot_id == "slot-1"


# ================================================================== determinism, hashing, separation


def test_output_is_deterministic_and_hashed_and_book_order_does_not_matter(store):
    books = [book("a", [h2h(-150, 130), spread(3.5)]), book("b", [h2h(-140, 120), spread(3.5, -105, -115)]),
             book("c", [h2h(-160, 140), spread(3.5, -115, -105)])]
    s1 = save(store, [event("g1", books)])
    s2 = save(store, [event("g1", list(reversed(books)))])
    one, again = oc.consensus_for_snapshot(store, s1), oc.consensus_for_snapshot(store, s1)
    assert one == again and one.to_dict() == again.to_dict() and len(one.output_sha256) == 64
    other = oc.consensus_for_snapshot(store, s2)
    assert one.input_sha256 != other.input_sha256  # a different stored payload is a different input
    assert [p.to_dict() if hasattr(p, "to_dict") else oc._plain(p) for p in props(one)] == \
        [oc._plain(p) for p in props(other)]
    art1 = oc.build_artifact([one], selection={"snapshot_id": s1})
    art2 = oc.build_artifact([again], selection={"snapshot_id": s1})
    assert art1 == art2 and art1["label"] == oc.LABEL and art1["executable"] is False
    # the version and parameters are part of the input identity
    assert json.loads(json.dumps(one.to_dict()))["consensus_version"] == oa.CONSENSUS_VERSION


def test_offered_prices_and_consensus_probabilities_are_distinct_and_never_executable(store):
    books = [book("a", [h2h(-150, 130)]), book("b", [h2h(-140, 120)])]
    result = oc.consensus_for_snapshot(store, save(store, [event("g1", books)]))
    (p,) = props(result, "h2h")
    offered_fields = {f for f in oc.OfferedPrice.__dataclass_fields__}
    consensus_fields = {f for f in oc.OutcomeConsensus.__dataclass_fields__}
    assert "raw_price" in offered_fields and not any("probability" in f for f in offered_fields - {
        "implied_probability_with_margin"})
    assert not any("price" in f or "odds" in f for f in consensus_fields)
    assert type(p.offered[0]) is not type(p.consensus[0])
    assert p.label == oc.LABEL == "RESEARCH BENCHMARK — NOT EXECUTABLE" and result.label == oc.LABEL
    blob = result.to_dict()
    assert all(d.get("executable") is not True for d in walk(blob))
    assert sum(1 for d in walk(blob) if d.get("executable") is False) >= 6
    assert not any(isinstance(x, ExecutableQuote) for x in (*p.offered, *p.books, *p.consensus))


def test_the_consensus_module_has_no_network_order_or_ledger_path():
    text = (SRC / "odds_consensus.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", '"')))
    for forbidden in ("fetch_odds", "fetch_events", "reconcile_quota", "urlopen", "http.", "ExecutableQuote(",
                      "evaluate(", "shadow_ledger", "record_fill", "record_decision", "save_snapshot", "QuotaLedger"):
        assert forbidden not in code, forbidden


def test_documented_v4_sample_yields_a_consensus(store):
    events = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = oc.consensus_for_snapshot(store, save(store, events, at=datetime(2021, 6, 10, 13, 40, tzinfo=UTC)))
    (h,) = props(result, "h2h")
    assert h.status is oc.ConsensusStatus.SUPPORTED and h.contributing_book_count >= 2
    assert abs(sum(c.consensus_probability for c in h.consensus) - 1) < Decimal("1e-20")
    assert result.events[0].home_team == "Tampa Bay Buccaneers"
    assert any(p.status is oc.ConsensusStatus.SUPPORTED for p in props(result, "spreads"))


# ================================================================== CLI


def run_cli(argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def test_cli_prints_or_writes_a_read_only_artifact(store, tmp_path):
    books = [book("a", [h2h(-110, -110)]), book("b", [h2h(-120, 100)])]
    sid = save(store, [event("g1", books)])
    db = str(store.path)
    before = hashlib.sha256(Path(db).read_bytes()).hexdigest()
    code, out = run_cli(["odds", "consensus", "--db", db, "--snapshot", str(sid)])
    art = json.loads(out)
    assert code == 0 and art["label"] == oc.LABEL and art["snapshots"][0]["snapshot_id"] == sid
    assert art["executable"] is False and len(art["artifact_sha256"]) == 64
    target = tmp_path / "out" / "consensus.json"
    code, out = run_cli(["odds", "consensus", "--db", db, "--event", "g1", "--as-of", iso(T0), "--out", str(target)])
    assert code == 0 and json.loads(out)["state"] == "WRITTEN"
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["selection"] == {"as_of_utc": iso(T0), "event_id": "g1"}
    code, out = run_cli(["odds", "consensus", "--db", db, "--since", iso(T0)])
    assert code == 0 and len(json.loads(out)["snapshots"]) == 1
    assert run_cli(["odds", "consensus", "--db", db, "--snapshot", "999"])[0] == 1
    code, out = run_cli(["odds", "consensus", "--db", db, "--snapshot", str(sid), "--as-of",
                         iso(T0 - timedelta(hours=1))])
    assert code == 1 and json.loads(out)["state"] == "NOT_KNOWABLE_AT_AS_OF"
    assert run_cli(["odds", "consensus", "--db", str(tmp_path / "missing.sqlite3")])[0] == 1
    assert hashlib.sha256(Path(db).read_bytes()).hexdigest() == before  # the store was not written


def test_receipt_order_uses_instants_not_text(store):
    books = [book("a", [h2h(-110, -110)]), book("b", [h2h(-110, -110)])]
    later_id = save(store, [event("g1", books)], at=T0 + timedelta(milliseconds=500))  # "...00.500000+00:00"
    earlier_id = save(store, [event("g1", books)], at=T0)  # "...00+00:00" sorts after it as text
    series = oc.consensus_series_for_event(store, "g1")
    assert [s.snapshot_id for s in series] == [earlier_id, later_id]
    assert oc.consensus_for_event(store, "g1", T0 + timedelta(seconds=1)).snapshot_id == later_id
