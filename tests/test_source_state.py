"""Source and game-state intelligence (source-state-v1, R2 / #145, ADR 0041). Fixture-fed and offline."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab import inplay_evidence as ev
from edge_lab.freshness import Freshness
from edge_lab.inplay_evidence import (
    ClockOrigin, ClockReading, DataKind, DecisionStamp, Dependence, EvidenceStatus, GameJournal, GameState, GameStateStatus,
    JournalEntry, LatencyBreakdown, LatencyStage, LeadershipStatus, LogEntry, ObservationLog, Ordering, Phase,
    QuotePoint, RevalidationReason, SourceContext, SourceObservation, SourceSeries, StateKnowledge, StateRelation,
    Stamps, ValidityStatus,
)
from edge_lab.opportunity import OutcomeFinality

T0 = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
SEC, MS = timedelta(seconds=1), timedelta(milliseconds=1)
CTX = SourceContext("NFL", "moneyline", Phase.LIVE, "REGULAR_SEASON")


def t(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def local(seconds: float, *, precision=MS, uncertainty=timedelta(milliseconds=50), clock="host:laptop"):
    return ClockReading(t(seconds), ClockOrigin.LOCAL, clock, precision, uncertainty)


def source(seconds: float, *, precision=SEC, uncertainty=timedelta(milliseconds=200), clock="src:book"):
    return ClockReading(t(seconds), ClockOrigin.SOURCE, clock, precision, uncertainty)


def obs(oid="q1", *, received=10, published=None, family="BOOK_A", upstream=(), version=None, corrects=None,
        evidence=EvidenceStatus.SIMULATED, kind=DataKind.FIXTURE):
    return SourceObservation(oid, "book-a", "G1", local(received), CTX, evidence, kind, source_family=family,
                             upstream_ids=upstream, published=None if published is None else source(published),
                             incorporated_state_version=version,
                             incorporated_state_basis=None if version is None else "documented state_seq field",
                             corrects=corrects)


def gs(first: float, *, home=0, away=0, period="Q1", event="e1", src_ts: float | None = None,
       status=GameStateStatus.OBSERVED, raw="r"):
    stamps = Stamps(receipt_utc=t(first), first_observed_utc=t(first),
                    source_ts_utc=None if src_ts is None else t(src_ts))
    return GameState("G1", "scores", event, stamps, status, f"{raw}-{first}-{home}-{away}", home_score=home,
                     away_score=away, period=period, game_clock_text="Q1 10:00", finality=OutcomeFinality.UNKNOWN)


def journal(*states):
    j = GameJournal("G1")
    for s in states:
        j = j.append(s)
    return j


def stamp(state, *, as_of=None, requires=True, expires=None, version=True):
    return DecisionStamp("pd-1", "exit-v1", as_of or state.stamps.first_observed_utc, requires,
                         state.observation_id if version else None, expires)


# ------------------------------------------------------------------ clocks


def test_a_game_clock_and_a_naive_time_are_not_utc():
    for bad in ("Q4 02:13", "2026-10-04T17:00:00", "", "17:00"):
        with pytest.raises(ValueError, match="not a timezone-aware UTC instant"):
            ClockReading(bad, ClockOrigin.SOURCE, "src", SEC, None)
    with pytest.raises(ValueError):
        ClockReading(t(0), ClockOrigin.SOURCE, "src", -SEC, None)


def test_overlapping_clock_uncertainty_is_unordered_never_a_tie_break():
    a = source(10, uncertainty=timedelta(milliseconds=500))
    b = local(10.8, uncertainty=timedelta(milliseconds=500))
    assert a.at < b.at and ev.clock_order(a, b) is Ordering.UNORDERED  # the stamps differ; the intervals overlap
    assert ev.clock_order(a, local(13)) is Ordering.BEFORE and ev.clock_order(local(13), a) is Ordering.AFTER
    # an unknown error bound across clocks cannot be ordered at all
    assert ev.clock_order(source(10, uncertainty=None), local(100)) is Ordering.UNORDERED
    # one clock shares its error: its readings order by precision alone
    assert ev.clock_order(local(10, uncertainty=None), local(10.01, uncertainty=None)) is Ordering.BEFORE


def test_a_future_publication_stamp_is_refused_and_processing_cannot_precede_receipt():
    with pytest.raises(ValueError, match="FUTURE_PUBLICATION"):
        obs(received=10, published=20)
    obs(received=10, published=10.5)  # inside the combined uncertainty: allowed, not ordered
    with pytest.raises(ValueError, match="processing cannot precede receipt"):
        SourceObservation("q", "s", "G1", local(10), CTX, EvidenceStatus.SIMULATED, DataKind.FIXTURE,
                          processed=local(5))


# ------------------------------------------------------------------ freshness of content, not arrival


def test_stale_data_that_was_just_received_is_stale():
    now = T0 + timedelta(seconds=601)
    just_received = obs(received=600, published=0)  # arrived a second ago, published ten minutes ago
    assert ev.content_freshness(just_received, now=now, max_age=timedelta(seconds=15)) is Freshness.STALE
    fresh = obs(received=600, published=599)
    assert ev.content_freshness(fresh, now=now, max_age=timedelta(seconds=15)) is Freshness.FRESH
    # no publication stamp: a recent receipt proves nothing about the content's age
    unstamped = obs(received=600)
    assert ev.content_freshness(unstamped, now=now, max_age=timedelta(seconds=15)) is Freshness.UNKNOWN
    # but an old receipt proves staleness from below
    assert ev.content_freshness(obs(received=0), now=now, max_age=timedelta(seconds=15)) is Freshness.STALE


# ------------------------------------------------------------------ incorporated state


def test_unknown_incorporated_state_is_never_inferred_from_receipt_order():
    previous = gs(95)  # the last state before the touchdown: the event happened after it was seen
    touchdown = gs(100, home=7)
    after_previous = local(95)  # a provable lower bound on the touchdown's time
    quote = obs(received=101)  # received after the scoreboard changed
    assert quote.state_knowledge is StateKnowledge.UNKNOWN
    assert ev.state_relation(quote, touchdown, event_not_before=after_previous) is StateRelation.UNKNOWN
    declared = obs(received=101, version=touchdown.observation_id)
    assert declared.state_knowledge is StateKnowledge.KNOWN
    assert ev.state_relation(declared, touchdown, event_not_before=after_previous) is StateRelation.INCORPORATES
    # published provably before the event could have happened: it cannot reflect it, though it arrived after
    early = obs(received=101, published=90)
    assert ev.state_relation(early, touchdown, event_not_before=after_previous) is StateRelation.CANNOT_INCORPORATE
    assert previous.home_score == 0


def test_a_scoreboard_publication_time_is_not_a_lower_bound_on_the_event():
    # The touchdown was published by the scoreboard at 10 s; it may have happened any time after the
    # previous state (seen at 5 s). A book published at 8 s may already reflect it: UNKNOWN, never CANNOT.
    touchdown = gs(12, home=7, src_ts=10)
    book = obs(received=9.5, published=8)
    assert ev.state_relation(book, touchdown, event_not_before=local(5)) is StateRelation.UNKNOWN
    assert ev.state_relation(book, touchdown, event_not_before=None) is StateRelation.UNKNOWN
    # a version without its documented basis declares nothing
    with pytest.raises(ValueError, match="documented basis"):
        SourceObservation("q", "s", "G1", local(1), CTX, EvidenceStatus.SIMULATED, DataKind.FIXTURE,
                          incorporated_state_version="v")


def test_decision_that_names_no_state_version_needs_review():
    s0 = gs(10)
    v = ev.decision_validity(stamp(s0, version=False), journal(s0), at=t(20))
    assert v.status is ValidityStatus.REVIEW_REQUIRED
    assert v.reasons[0][0] is RevalidationReason.STATE_UNKNOWN and not v.usable
    missing = DecisionStamp("pd", "v1", t(20), True, "no-such-version")
    assert ev.decision_validity(missing, journal(s0), at=t(20)).reasons[0][0] is \
        RevalidationReason.STATE_VERSION_NOT_FOUND


# ------------------------------------------------------------------ validity against later state


def test_material_new_event_invalidates_the_dependent_recommendation():
    s0, td = gs(10), gs(50, home=7, event="e2")
    j = journal(s0, td)
    st = stamp(s0, as_of=t(40))
    assert ev.decision_validity(st, j, at=t(45)).status is ValidityStatus.VALID  # the touchdown is not seen yet
    v = ev.decision_validity(st, j, at=t(50))
    assert v.status is ValidityStatus.INVALIDATED and v.superseded_by == (td.observation_id,)
    assert v.reasons[0][0] is RevalidationReason.MATERIAL_STATE_CHANGE
    assert v.authorizes_execution is False
    with pytest.raises(ValueError):
        ev.StateValidity("pd", ValidityStatus.VALID, (), t(0), None, authorizes_execution=True)


def test_a_non_material_update_keeps_the_recommendation_valid():
    s0 = gs(10)
    clock_tick = GameState("G1", "scores", "e3", Stamps(t(20), t(20)), GameStateStatus.OBSERVED, "tick",
                           home_score=0, away_score=0, period="Q1", game_clock_text="Q1 09:40",
                           finality=OutcomeFinality.UNKNOWN)
    v = ev.decision_validity(stamp(s0, as_of=t(15)), journal(s0, clock_tick), at=t(25))
    assert v.status is ValidityStatus.VALID and v.non_material_updates == 1


def test_duplicate_state_changes_nothing_and_a_correction_invalidates():
    s0 = gs(10, home=7, event="e1")
    dup = gs(12, home=7, event="e1", raw="r")  # same source event and content: a duplicate
    j = journal(s0, dup)
    assert [k for k, _ in j.entries] == [JournalEntry.NEW, JournalEntry.DUPLICATE]
    assert ev.decision_validity(stamp(s0, as_of=t(15)), j, at=t(20)).status is ValidityStatus.VALID
    overturned = gs(30, home=0, event="e1")  # the touchdown is overturned: same event, new content
    j2 = j.append(overturned)
    assert j2.entries[-1][0] is JournalEntry.CORRECTION and j2.entries[0][1] == s0  # appended, nothing overwritten
    v = ev.decision_validity(stamp(s0, as_of=t(15)), j2, at=t(30))
    assert v.status is ValidityStatus.INVALIDATED
    assert any(r is RevalidationReason.STATE_CORRECTED for r, _ in v.reasons)


def test_a_journal_out_of_first_observed_order_still_invalidates():
    early, td = gs(10, home=0), gs(15, home=7, event="e2")
    j = GameJournal("G1").append(td).append(early)  # appended out of first-observed order
    assert ev.game_state_as_of(j, t(20)).observation_id == td.observation_id
    v = ev.decision_validity(stamp(early, as_of=t(11)), j, at=t(20))
    assert v.status is ValidityStatus.INVALIDATED and v.superseded_by == (td.observation_id,)
    # and a state first observed before the depended-on one is not "later", whatever its position
    v2 = ev.decision_validity(stamp(td, as_of=t(16)), j, at=t(20))
    assert v2.status is ValidityStatus.VALID


def test_reversed_event_order_needs_review_and_is_not_read_as_new_state():
    s_new = gs(10, home=7, event="e2", src_ts=9)
    s_late_old = gs(20, home=0, event="e1", src_ts=5)  # older by the source's clock, arrived later
    v = ev.decision_validity(stamp(s_new, as_of=t(15)), journal(s_new, s_late_old), at=t(25))
    assert v.status is ValidityStatus.REVIEW_REQUIRED
    assert v.reasons[0][0] is RevalidationReason.OUT_OF_ORDER_STATE and v.superseded_by == ()


def test_unreadable_later_update_needs_review():
    s0 = gs(10)
    unmapped = GameState("G1", "scores", "e9", Stamps(t(20), t(20)), GameStateStatus.UNSUPPORTED_OR_UNMAPPED, "x")
    v = ev.decision_validity(stamp(s0, as_of=t(15)), journal(s0, unmapped), at=t(25))
    assert v.status is ValidityStatus.REVIEW_REQUIRED and v.reasons[0][0] is RevalidationReason.STATE_UNKNOWN


def test_future_state_reference_and_future_as_of_are_refused():
    s0, s1 = gs(10), gs(30, home=3, event="e2")
    j = journal(s0, s1)
    # the decision claims (as of 20) a state first observed at 30: it could not have seen it
    v = ev.decision_validity(DecisionStamp("pd", "v1", t(20), True, s1.observation_id), j, at=t(40))
    assert v.status is ValidityStatus.REVIEW_REQUIRED
    assert v.reasons[0][0] is RevalidationReason.FUTURE_STATE_REFERENCE
    v2 = ev.decision_validity(DecisionStamp("pd", "v1", t(50), True, s0.observation_id), j, at=t(40))
    assert any(r is RevalidationReason.AS_OF_IN_FUTURE for r, _ in v2.reasons)
    with pytest.raises(ValueError):
        DecisionStamp("pd", "v1", "2026-10-04T17:00:00", True)  # naive
    with pytest.raises(ValueError):
        ev.decision_validity(stamp(s0), j, at="Q4 02:13")


def test_expiry_invalidates_and_unknown_material_fields_are_refused():
    s0 = gs(10)
    st = DecisionStamp("pd", "v1", t(10), False, None, expires_at_utc=t(20))
    assert ev.decision_validity(st, journal(s0), at=t(19)).status is ValidityStatus.VALID
    assert ev.decision_validity(st, journal(s0), at=t(20)).status is ValidityStatus.INVALIDATED
    with pytest.raises(ValueError, match="unknown material fields"):
        ev.decision_validity(st, journal(s0), at=t(20), material_fields=("win_probability",))


# ------------------------------------------------------------------ corrections append in the observation log


def test_observation_log_appends_corrections_and_refuses_overwrites():
    q1 = obs("q1", published=5)
    log = ObservationLog().append(q1).append(obs("q1", published=5))
    assert [k for k, _ in log.entries] == [LogEntry.NEW, LogEntry.DUPLICATE] and log.originals() == (q1,)
    with pytest.raises(ValueError, match="OVERWRITE_REFUSED"):
        log.append(obs("q1", published=6))
    fixed = obs("q1-fix", published=6, corrects="q1")
    log = log.append(fixed)
    assert log.entries[-1][0] is LogEntry.CORRECTION and log.originals() == (q1, fixed)
    with pytest.raises(ValueError, match="has not seen"):
        log.append(obs("q9", corrects="never-seen"))


# ------------------------------------------------------------------ latency stages


def test_unmeasured_latency_is_none_never_zero():
    transport = ev.measure_between(source(10), local(10.3), "receipt - source publication")
    parse = ev.measure_between(local(10.3), local(10.31), "processing - receipt")
    assert parse.uncertainty == 2 * MS  # one clock: precision only
    assert transport.uncertainty == SEC + MS + timedelta(milliseconds=250)
    b = LatencyBreakdown(((LatencyStage.TRANSPORT, transport), (LatencyStage.PARSE, parse)))
    assert b.get(LatencyStage.MODEL) is None and LatencyStage.VENUE in b.unmeasured()
    assert b.total() is None  # never a sum that treats unmeasured stages as 0
    assert b.total((LatencyStage.TRANSPORT, LatencyStage.PARSE)) == timedelta(milliseconds=310)
    assert ev.measure_between(None, local(1), "x") is None
    # across clocks an unknown error bound stays unknown, and a negative gap beyond its bound is inconsistent
    assert ev.measure_between(source(10, uncertainty=None), local(11), "x").uncertainty is None
    bad = ev.measure_between(local(20), local(10), "x")
    assert bad.clock_inconsistent
    assert LatencyBreakdown(((LatencyStage.PARSE, bad),)).total((LatencyStage.PARSE,)) is None
    with pytest.raises(ValueError):
        LatencyBreakdown(((LatencyStage.PARSE, parse), (LatencyStage.PARSE, parse)))


# ------------------------------------------------------------------ source leadership, both directions


KICK = "2026-10-04T17:00:00+00:00"


def series(sid, family, mids, *, gap=1.0, start=0.0, clock="host:laptop", spread="0.02", upstream=(),
           uncertainty=timedelta(milliseconds=50), precision=MS):
    pts = tuple(QuotePoint(f"{sid}-{i}", ClockReading(t(start + i * gap), ClockOrigin.LOCAL, clock, precision,
                                                      uncertainty),
                           D(m) - D(spread) / 2, D(m) + D(spread) / 2) for i, m in enumerate(mids))
    return SourceSeries(sid, family, CTX, "RECEIVED", pts, DataKind.FIXTURE, "G1", KICK, upstream)


KW = dict(move_threshold=D("0.03"), match_window=timedelta(seconds=5), required_resolution=timedelta(seconds=2),
          variants_tested=1, min_ordered=2)
A_LEADS = ["0.50", "0.50", "0.60", "0.60", "0.60", "0.60", "0.50", "0.50", "0.50", "0.50"]
B_LAGS = ["0.50", "0.50", "0.50", "0.50", "0.60", "0.60", "0.60", "0.60", "0.50", "0.50"]


def test_leadership_counts_both_directions_and_names_no_winner():
    r = ev.source_leadership(series("a", "EXCHANGE", A_LEADS), series("b", "BOOK", B_LAGS), **KW)
    assert r.status is LeadershipStatus.REPORTED and r.dependence is Dependence.INDEPENDENT_AS_DECLARED
    assert (r.a_first, r.b_first, r.unordered) == (2, 0, 0) and r.moves_a == r.moves_b == 2
    rev = ev.source_leadership(series("b", "BOOK", B_LAGS), series("a", "EXCHANGE", A_LEADS), **KW)
    assert (rev.a_first, rev.b_first) == (0, 2)  # the same data read the other way round
    assert "Not causal price discovery" in r.not_a_causal_claim
    assert not any(name in {f.name for f in r.__dataclass_fields__.values()} for name in ("leader", "winner"))


def test_sparse_pregame_snapshots_are_insufficient_resolution():
    sparse_a = series("a", "EXCHANGE", A_LEADS, gap=3600)  # hourly snapshots
    sparse_b = series("b", "BOOK", B_LAGS, gap=3600)
    r = ev.source_leadership(sparse_a, sparse_b, **KW)
    assert r.status is LeadershipStatus.INSUFFICIENT_RESOLUTION
    assert r.a_first is None and r.b_first is None and r.unordered is None  # nothing is claimed
    assert any("median capture gap" in x for x in r.reasons)


def test_overlapping_clock_uncertainty_makes_co_moves_unordered():
    wide = timedelta(seconds=3)
    a = series("a", "EXCHANGE", A_LEADS, clock="src:a", uncertainty=wide, precision=timedelta(0))
    b = series("b", "BOOK", B_LAGS, clock="src:b", uncertainty=wide, precision=timedelta(0))
    r = ev.source_leadership(a, b, **{**KW, "required_resolution": timedelta(seconds=10)})
    assert r.a_first == 0 and r.b_first == 0 and r.unordered == 2
    assert r.status is LeadershipStatus.INSUFFICIENT_EVIDENCE
    # an unknown cross-clock error bound cannot be resolved at all
    unk = series("b", "BOOK", B_LAGS, clock="src:b", uncertainty=None)
    assert ev.source_leadership(series("a", "EXCHANGE", A_LEADS), unk, **KW).status is \
        LeadershipStatus.INSUFFICIENT_RESOLUTION


def test_shared_upstream_and_unknown_families_are_reported_as_dependence():
    shared = ev.source_leadership(series("a", "BOOK_X", A_LEADS, upstream=("oddsfeed",)),
                                  series("b", "BOOK_Y", B_LAGS, upstream=("oddsfeed",)), **KW)
    assert shared.dependence is Dependence.SHARED_SOURCE and any("SHARED_SOURCE" in x for x in shared.reasons)
    same_family = ev.source_leadership(series("a", "BOOK", A_LEADS), series("b", "BOOK", B_LAGS), **KW)
    assert same_family.dependence is Dependence.SHARED_SOURCE
    unknown = ev.source_leadership(series("a", ev.UNKNOWN_FAMILY, A_LEADS), series("b", "BOOK", B_LAGS), **KW)
    assert unknown.dependence is Dependence.UNKNOWN


def test_bid_ask_noise_is_not_a_move():
    wide = ["0.50", "0.54", "0.50", "0.54", "0.50"]  # mid moves 4c inside a 10c spread
    r = ev.source_leadership(series("a", "EXCHANGE", wide, spread="0.10"),
                             series("b", "BOOK", wide, spread="0.10"), **KW)
    assert r.moves_a == 0 and r.noise_rejected_a == 4 and r.status is LeadershipStatus.INSUFFICIENT_EVIDENCE


def test_reversed_arrival_order_is_counted_and_ordered_by_the_source_clock():
    a = series("a", "EXCHANGE", A_LEADS)
    shuffled = SourceSeries("a", "EXCHANGE", CTX, "RECEIVED", tuple(reversed(a.points)), DataKind.FIXTURE, "G1",
                            KICK)
    r = ev.source_leadership(shuffled, series("b", "BOOK", B_LAGS), **KW)
    assert r.out_of_order_points == len(a.points) - 1
    assert (r.a_first, r.b_first) == (2, 0)


def test_research_exposure_is_required_and_reported():
    with pytest.raises(ValueError, match="variants"):
        ev.source_leadership(series("a", "X", A_LEADS), series("b", "Y", B_LAGS), **{**KW, "variants_tested": 0})
    r = ev.source_leadership(series("a", "X", A_LEADS), series("b", "Y", B_LAGS), **{**KW, "variants_tested": 7})
    assert r.variants_tested == 7


def test_synthetic_and_fixture_series_are_not_compared():
    syn = SourceSeries("b", "BOOK", CTX, "RECEIVED", series("b", "BOOK", B_LAGS).points, DataKind.SYNTHETIC, "G1",
                       KICK)
    with pytest.raises(ValueError, match="data kinds"):
        ev.source_leadership(series("a", "X", A_LEADS), syn, **KW)


def test_recorded_series_and_holdout_dates_are_refused_in_this_batch():
    pts = series("b", "BOOK", B_LAGS).points
    with pytest.raises(ValueError, match="RECORDED series are refused"):
        SourceSeries("b", "BOOK", CTX, "RECEIVED", pts, DataKind.RECORDED, "G1", KICK)
    late = (QuotePoint("late", ClockReading("2026-10-22T04:00:00+00:00", ClockOrigin.LOCAL, "c", MS, None),
                       D("0.4"), D("0.5")),)
    for kind in (DataKind.FIXTURE, DataKind.SYNTHETIC):
        with pytest.raises(ValueError, match="holdout boundary"):
            SourceSeries("b", "BOOK", CTX, "RECEIVED", late, kind, "G1", KICK)
    just_before = (QuotePoint("ok", ClockReading("2026-10-22T03:59:59+00:00", ClockOrigin.LOCAL, "c", MS, MS),
                              D("0.4"), D("0.5")),)
    SourceSeries("b", "BOOK", CTX, "RECEIVED", just_before, DataKind.FIXTURE, "G1", KICK)
    # an unknown clock bound leaves the latest possible time open: it must clear the margin
    unbounded = (QuotePoint("u", ClockReading("2026-10-21T12:00:00+00:00", ClockOrigin.LOCAL, "c", MS, None),
                            D("0.4"), D("0.5")),)
    with pytest.raises(ValueError, match="holdout boundary"):
        SourceSeries("b", "BOOK", CTX, "RECEIVED", unbounded, DataKind.FIXTURE, "G1", KICK)
    # an interval that reaches the boundary is refused even when the stamp is before it
    spanning = (QuotePoint("s", ClockReading("2026-10-22T03:59:59+00:00", ClockOrigin.LOCAL, "c", SEC,
                                             timedelta(hours=1)), D("0.4"), D("0.5")),)
    with pytest.raises(ValueError, match="holdout boundary"):
        SourceSeries("b", "BOOK", CTX, "RECEIVED", spanning, DataKind.FIXTURE, "G1", KICK)
    # a pregame point for an event kicking off on or after the boundary is refused by the kickoff
    early_point = (QuotePoint("p", ClockReading("2026-10-20T12:00:00+00:00", ClockOrigin.LOCAL, "c", MS, SEC),
                              D("0.4"), D("0.5")),)
    for kickoff in ("2026-10-22T04:00:00+00:00", "2026-10-22T00:00:00-04:00", "2026-10-25T17:00:00+00:00"):
        with pytest.raises(ValueError, match="kickoff"):
            SourceSeries("b", "BOOK", CTX, "RECEIVED", early_point, DataKind.FIXTURE, "G9", kickoff)
    SourceSeries("b", "BOOK", CTX, "RECEIVED", early_point, DataKind.FIXTURE, "G9", "2026-10-21T23:59:59-04:00")


def test_evidence_status_is_tied_to_the_input_kind():
    for kind in (DataKind.FIXTURE, DataKind.SYNTHETIC):
        with pytest.raises(ValueError, match="cannot be ACTUAL"):
            obs(evidence=EvidenceStatus.ACTUAL, kind=kind)
    ev.check_evidence(DataKind.RECORDED, EvidenceStatus.ACTUAL)
    ev.check_evidence(DataKind.RECORDED, EvidenceStatus.SIMULATED)  # a replay over recorded books
    ev.check_evidence(None, EvidenceStatus.UNAVAILABLE)
    with pytest.raises(ValueError):
        ev.check_evidence(DataKind.RECORDED, EvidenceStatus.UNAVAILABLE)  # unavailable has no input
    with pytest.raises(ValueError):
        ev.check_evidence(None, EvidenceStatus.HYPOTHETICAL)


# ------------------------------------------------------------------ no label reading, no EXP-002 coupling


def test_source_state_reads_no_labels_and_no_experiment_data():
    params = set(inspect.signature(ev.source_leadership).parameters) | set(
        inspect.signature(ev.decision_validity).parameters)
    for word in ("outcome", "settlement", "label", "result", "winner"):
        assert not [p for p in params if word in p], word
    tree = ast.parse(Path(ev.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for banned in ("sports_evidence", "exp002_timing", "settlement", "outcome_board", "storage", "research_evidence",
                   "experiments", "odds_consensus"):
        assert not [m for m in imported if m and banned in m], banned


def test_a_decision_on_an_unreadable_state_needs_review():
    unmapped = GameState("G1", "scores", "e1", Stamps(t(10), t(10)), GameStateStatus.UNSUPPORTED_OR_UNMAPPED, "x")
    v = ev.decision_validity(stamp(unmapped, as_of=t(15)), journal(unmapped), at=t(20))
    assert v.status is ValidityStatus.REVIEW_REQUIRED and v.reasons[0][0] is RevalidationReason.STATE_UNKNOWN



# ------------------------------------------------------------------ review fixes: symmetry, clock basis, events


def test_swapping_the_arguments_mirrors_the_report():
    import random

    rng = random.Random(20260930)
    for trial in range(200):
        def rand_series(sid):
            mids, m = [], 50
            for _ in range(rng.randint(3, 14)):
                m = min(90, max(10, m + rng.choice((-10, 0, 0, 10))))
                mids.append(f"{m / 100:.2f}")
            return series(sid, sid.upper(), mids, gap=rng.choice((0.5, 1.0, 1.5)), start=rng.choice((0.0, 0.3, 1.1)))

        a, b = rand_series("a"), rand_series("b")
        kw = {**KW, "match_window": timedelta(seconds=rng.choice((1, 3, 10))), "min_ordered": 1}
        r1, r2 = ev.source_leadership(a, b, **kw), ev.source_leadership(b, a, **kw)
        assert r1.status is r2.status, trial
        assert (r1.a_first, r1.b_first) == (r2.b_first, r2.a_first), trial
        assert (r1.unordered, r1.ambiguous) == (r2.unordered, r2.ambiguous), trial
        assert (r1.unmatched_a, r1.unmatched_b) == (r2.unmatched_b, r2.unmatched_a), trial


def test_a_move_with_two_candidate_partners_is_ambiguous_not_directional():
    a = series("a", "X", ["0.50", "0.60", "0.60", "0.60", "0.70", "0.70", "0.70", "0.70"])  # up at 0-1 s and 3-4 s
    b = series("b", "Y", ["0.50", "0.50", "0.50", "0.50", "0.50", "0.60", "0.60", "0.60"])  # up at 4-5 s
    kw = {**KW, "match_window": timedelta(seconds=10), "min_ordered": 1}
    r1, r2 = ev.source_leadership(a, b, **kw), ev.source_leadership(b, a, **kw)
    assert (r1.a_first, r1.b_first, r1.ambiguous) == (0, 0, 1) == (r2.b_first, r2.a_first, r2.ambiguous)
    assert r1.status is r2.status is LeadershipStatus.INSUFFICIENT_EVIDENCE


def test_series_on_different_clock_bases_or_events_are_not_compared():
    pub = tuple(QuotePoint(p.observation_id, ClockReading(p.at.utc, ClockOrigin.SOURCE, "src:a", MS,
                                                          timedelta(milliseconds=50)), p.bid, p.ask)
                for p in series("a", "X", A_LEADS).points)
    published = SourceSeries("a", "X", CTX, "PUBLISHED", pub, DataKind.FIXTURE, "G1", KICK)
    with pytest.raises(ValueError, match="clock bases"):
        ev.source_leadership(published, series("b", "Y", B_LAGS), **KW)
    with pytest.raises(ValueError, match="carries SOURCE readings only"):
        SourceSeries("a", "X", CTX, "PUBLISHED", series("a", "X", A_LEADS).points, DataKind.FIXTURE, "G1", KICK)
    other_event = SourceSeries("b", "Y", CTX, "RECEIVED", series("b", "Y", B_LAGS).points, DataKind.FIXTURE, "G2",
                               KICK)
    with pytest.raises(ValueError, match="different events"):
        ev.source_leadership(series("a", "X", A_LEADS), other_event, **KW)
    r = ev.source_leadership(series("a", "X", A_LEADS), series("b", "Y", B_LAGS), **KW)
    assert r.clock_basis == "RECEIVED" and r.event_id == "G1"


def test_one_sided_quotes_are_bridged_and_counted_not_dropped():
    mids = ["0.50", "0.50", None, "0.60", "0.60", "0.60", "0.60", "0.60"]
    pts = tuple(QuotePoint(f"a-{i}", local(i), None if m is None else D(m) - D("0.01"),
                           None if m is None else D(m) + D("0.01")) for i, m in enumerate(mids))
    a = SourceSeries("a", "X", CTX, "RECEIVED", pts, DataKind.FIXTURE, "G1", KICK)
    b = series("b", "Y", ["0.50", "0.50", "0.50", "0.50", "0.50", "0.50", "0.60", "0.60"])
    r = ev.source_leadership(a, b, **{**KW, "min_ordered": 1})
    assert r.moves_a == 1 and r.one_sided_skipped_a == 1 and r.a_first == 1  # the move spans 1-3 s
    assert any(x.startswith("ONE_SIDED_BRIDGED") for x in r.reasons)
