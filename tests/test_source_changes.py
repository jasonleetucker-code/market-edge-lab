"""Source change/event envelope v1 (#181 Deliverable E, ADR 0041 addendum): envelope, ledger, freshness, cost.

Fixture-fed and offline. The first section demonstrates what existing owners already cover (and pins their
serialized forms); the rest tests what `edge_lab.source_changes` adds."""

from __future__ import annotations

import ast
import itertools
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab import source_changes as sc
from edge_lab.discovery import CoverageState
from edge_lab.freshness import Freshness, StaleDataError, assess, combine, require_fresh
from edge_lab.inplay_evidence import (
    ClockOrigin, ClockReading, DataKind, EvidenceStatus, Phase, SourceContext, content_freshness,
)
from edge_lab.provenance import bytes_sha256, canonical_json, payload_sha256, shape_fingerprint
from edge_lab.sources import REGISTRY, SourceStatus
from edge_lab.source_changes import (
    UNKNOWN_COST, ChangeKind, ChangeLedger, CopyOrder, CostBasis, FetchCost, IdentityBasis, LinkKind, OrderBasis,
    SourcePermission, SubjectRef, key_freshness, make_envelope, require_current, total_cost,
)

FIXTURE = Path(__file__).parent / "fixtures" / "source_changes" / "rules_and_cli.jsonl"
T0 = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
MS, SEC = timedelta(milliseconds=1), timedelta(seconds=1)
KAL = SubjectRef("kalshi:market", "KXHIGHNY-26OCT08-B70", IdentityBasis.SOURCE_NATIVE)
KEY = (KAL.key, "status")
FREE = FetchCost(CostBasis.DOCUMENTED, 1, None, D("0"), "fixture: documented keyless endpoint")


def t(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def local(seconds: float, *, unc: timedelta | None = timedelta(milliseconds=50), clock="host:fixture"):
    return ClockReading(t(seconds), ClockOrigin.LOCAL, clock, MS, unc)


def src(seconds: float, *, unc: timedelta | None = timedelta(seconds=2), clock="src:kalshi"):
    return ClockReading(t(seconds), ClockOrigin.SOURCE, clock, SEC, unc)


def env(value="open", *, at=0.0, source="kalshi_public", kind="markets", subject=KAL, aspect="status",
        requested: float | None = None, published: float | None = None, pub_unc=timedelta(seconds=2),
        pub_clock="src:kalshi", seq=None,
        scope="per market", data_kind=DataKind.FIXTURE, evidence=EvidenceStatus.SIMULATED, cost=FREE,
        family="KALSHI", context=SourceContext(None, "KXHIGHNY"), **extra):
    opt = dict(extra)
    if requested is not None:
        opt["requested"] = local(requested)
    if published is not None:
        opt["claimed_published"] = src(published, unc=pub_unc, clock=pub_clock)
        opt["publication_field"] = "updated_time"
    if seq is not None:
        opt["upstream_seq"], opt["seq_scope"] = seq, scope
    return make_envelope(source_id=source, kind=kind, subject=subject, aspect=aspect, content={"value": value},
                         received=local(at), data_kind=data_kind, evidence=evidence,
                         coverage=CoverageState.COMPLETE, cost=cost, source_family=family, context=context, **opt)


def ledger(*envs):
    led = ChangeLedger()
    for e in envs:
        led = led.append(e)
    return led


def kinds(led):
    return [r.kind for r in led.records]


# =========================================================================== already covered: demonstrated, not rebuilt


def test_provenance_digests_are_pinned_and_reused_unchanged():
    payload = {"b": [1, {"z": None, "a": True}], "a": "x"}
    assert canonical_json(payload) == '{"a":"x","b":[1,{"a":true,"z":null}]}'
    assert payload_sha256(payload) == "b19526a1396b32e611c90cf39f5438985b37eb7b8a4cd75ddeed70151ef4569f"
    assert shape_fingerprint(payload) == "03e352967719ea2663230cd92ce7b788ed2aed0c692054e90717a463316ed88e"
    assert bytes_sha256(b"edge") == "a1cb100f57e971cacf269e7c26e4630a25a8e9d4bdd35e32df1a80b66b896254"
    e = env("open")
    assert e.content_sha256 == payload_sha256({"value": "open"})  # the envelope's hash is provenance's, not a new one


def test_freshness_semantics_are_unchanged():
    now = T0
    assert assess(None, max_age=SEC, now=now) is Freshness.UNKNOWN
    assert assess(t(-10), max_age=SEC, now=now) is Freshness.STALE
    assert assess(t(600), max_age=SEC, now=now) is Freshness.UNKNOWN  # future beyond skew
    assert combine() is Freshness.UNKNOWN
    assert combine(Freshness.FRESH, Freshness.STALE) is Freshness.STALE
    with pytest.raises(StaleDataError):
        require_fresh(Freshness.UNKNOWN, what="x")


def test_permission_comes_from_the_registry_and_is_never_self_asserted():
    for sid, spec in REGISTRY.items():
        assert sc.source_permission(sid).value == spec.status.name
    assert sc.source_permission("weather.com-or-anything") is SourcePermission.UNREGISTERED
    assert REGISTRY["kalshi_settlement_weather_company"].status is SourceStatus.BLOCKED
    e = env()
    assert e.source_permission is SourcePermission.ACTIVE
    with pytest.raises(ValueError, match="never self-asserted"):
        replace(e, source_permission=SourcePermission.PLANNED)
    planned = env(source="polymarket_us_public", kind="markets", family="PM")
    assert planned.source_permission is SourcePermission.PLANNED
    with pytest.raises(ValueError, match="never self-asserted"):
        replace(planned, source_permission=SourcePermission.ACTIVE)


@pytest.mark.parametrize("source", ["polymarket_us_public", "kalshi_settlement_weather_company", "x_firehose"])
def test_recorded_content_needs_an_active_registered_source(source):
    with pytest.raises(ValueError, match="RECORDED content from a"):
        env(source=source, data_kind=DataKind.RECORDED, evidence=EvidenceStatus.ACTUAL)
    # the same statement as a FIXTURE is allowed: fixture-driven work needs no collection permission
    assert env(source=source).data_kind is DataKind.FIXTURE


def test_evidence_class_reuses_check_evidence():
    with pytest.raises(ValueError, match="cannot be ACTUAL"):
        env(evidence=EvidenceStatus.ACTUAL)  # FIXTURE input is never ACTUAL
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        env(evidence=EvidenceStatus.UNAVAILABLE)
    assert env(data_kind=DataKind.RECORDED, evidence=EvidenceStatus.ACTUAL).evidence is EvidenceStatus.ACTUAL


def test_content_freshness_is_inplay_evidences_rule_with_the_registry_max_age():
    e = env(at=0, published=-30)
    max_age = REGISTRY["kalshi_public"].max_age["markets"]
    for now in (T0, T0 + timedelta(minutes=14), T0 + timedelta(minutes=20)):
        assert e.freshness(now) is content_freshness(e.as_observation(), now=now, max_age=max_age)
    assert e.freshness(T0) is Freshness.FRESH
    assert e.freshness(T0 + timedelta(minutes=20)) is Freshness.STALE
    assert env(kind="no_such_kind").freshness(T0) is Freshness.UNKNOWN  # no objective is UNKNOWN, never FRESH


def test_price_series_lead_lag_is_already_owned_by_inplay_source_leadership():
    """Deliverable E's lead-lag over quote series is `inplay_evidence.source_leadership` (ADR 0041), conditional on
    `SourceContext` and reported in both directions. This module reuses its vocabulary and adds no second copy."""
    from edge_lab.inplay_evidence import LeadershipStatus, QuotePoint, SourceSeries, source_leadership

    ctx = SourceContext("NFL", "moneyline", Phase.PREGAME)

    def series(sid, fam, moves):
        pts = tuple(QuotePoint(f"{sid}-{i}", ClockReading(t(s), ClockOrigin.LOCAL, "host:fixture", MS, None),
                               D(b), D(b) + D("0.01")) for i, (s, b) in enumerate(moves))
        return SourceSeries(sid, fam, ctx, "RECEIVED", pts, DataKind.FIXTURE, "G1", "2026-10-09T00:00:00+00:00")

    a = series("book-a", "A", [(0, "0.40"), (10, "0.50")])
    b = series("book-b", "B", [(0, "0.40"), (12, "0.40"), (14, "0.50")])
    kw = dict(move_threshold=D("0.05"), match_window=timedelta(seconds=20), required_resolution=timedelta(seconds=20),
              variants_tested=1, min_ordered=1)
    rep, rev = source_leadership(a, b, **kw), source_leadership(b, a, **kw)
    assert rep.status is LeadershipStatus.REPORTED and (rep.a_first, rep.b_first) == (1, 0)
    assert (rev.a_first, rev.b_first) == (0, 1) and rep.a_context == ctx
    assert not hasattr(sc, "SourceSeries") and not hasattr(sc, "source_leadership")


# =========================================================================== the envelope


def test_envelope_validation_rules():
    with pytest.raises(ValueError, match="does not match the content"):
        replace(env(), content={"value": "tampered"})
    with pytest.raises(ValueError, match="failed read"):
        replace(env(), coverage=CoverageState.FAILED)
    with pytest.raises(ValueError, match="documented field"):
        replace(env(published=-1), publication_field=None)
    with pytest.raises(ValueError, match="sequence number needs its documented scope"):
        replace(env(seq=3), seq_scope=None)
    with pytest.raises(ValueError, match="request cannot leave after"):
        env(at=0, requested=5)
    with pytest.raises(ValueError, match="LOCAL"):
        replace(env(), received=src(0))
    with pytest.raises(ValueError, match="unknown is None"):
        FetchCost(CostBasis.UNKNOWN, 0)
    with pytest.raises(ValueError, match="DECLARED_MAPPING"):
        SubjectRef("kalshi:market", "X", IdentityBasis.DECLARED_MAPPING)
    with pytest.raises(ValueError, match="UNKNOWN identity has no native_id"):
        SubjectRef("kalshi:market", "X", IdentityBasis.UNKNOWN)


def test_fixture_journal_round_trips_with_pinned_digests():
    envs = list(sc.read_envelopes(FIXTURE))
    assert [e.envelope_id[:16] for e in envs] == ["52327ee023889832", "7df1ed5ac93b531b", "5833ebfadef7bcae",
                                                  "070085a78e59702f", "44eb03ad35ee5444"]
    for e in envs:
        assert sc.envelope_from_dict(e.to_dict()) == e
        assert e.data_kind is DataKind.FIXTURE and e.evidence is EvidenceStatus.SIMULATED
    led = ledger(*envs)
    assert kinds(led) == [ChangeKind.NEW, ChangeKind.DUPLICATE, ChangeKind.CHANGED, ChangeKind.NEW, ChangeKind.CHANGED]
    assert [r.order_basis for r in led.records] == [None, None, OrderBasis.FETCH_WINDOWS, None,
                                                    OrderBasis.SOURCE_PUBLICATION]


def test_journal_reader_refuses_a_missing_header_and_mixed_data_kinds(tmp_path):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    no_header = tmp_path / "a.jsonl"
    no_header.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        list(sc.read_envelopes(no_header))
    synthetic = tmp_path / "b.jsonl"
    synthetic.write_text("\n".join([lines[0].replace('"FIXTURE"', '"SYNTHETIC"', 1)] + lines[1:]) + "\n",
                         encoding="utf-8")
    with pytest.raises(ValueError, match="FIXTURE envelope in a SYNTHETIC journal"):
        list(sc.read_envelopes(synthetic))


def test_a_tampered_journal_line_fails_its_hash(tmp_path):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace("FIXTURE rules v1", "FIXTURE rules v9")
    bad = tmp_path / "c.jsonl"
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match the content"):
        list(sc.read_envelopes(bad))


# =========================================================================== duplicates, echoes, replays


def test_duplicates_and_replays_are_counted_never_novel():
    a = env("open", at=0, requested=-1)
    a2 = env("open", at=60, requested=59)
    led = ledger(a, a2, a2)
    assert kinds(led) == [ChangeKind.NEW, ChangeKind.DUPLICATE, ChangeKind.REPLAYED]
    assert [r.novel for r in led.records] == [True, False, False]
    assert led.records[1].links == ((LinkKind.DUPLICATE_OF, a.envelope_id),)
    assert led.records[2].links == ((LinkKind.DUPLICATE_OF, a2.envelope_id),)
    assert led.current(KEY) == {"kalshi_public": (a,)}
    assert led.first_receipt(KEY, a.content_sha256).utc == t(0)


def test_another_source_with_the_same_content_is_an_echo_not_news():
    a = env("open", at=0)
    b = env("open", at=5, source="polymarket_us_public", family="PM")
    led = ledger(a, b)
    assert kinds(led) == [ChangeKind.NEW, ChangeKind.ECHO]
    assert led.records[1].links == ((LinkKind.ECHO_OF, a.envelope_id),) and not led.records[1].novel
    assert led.contradictions(KEY) == ()


def test_unknown_identity_is_kept_and_never_merged():
    anon = SubjectRef("kalshi:market", None, IdentityBasis.UNKNOWN)
    a, b = env("open", at=0, subject=anon), env("open", at=1, subject=anon)
    led = ledger(a, b, env("open", at=2))
    assert kinds(led) == [ChangeKind.UNKEYED, ChangeKind.UNKEYED, ChangeKind.NEW]
    assert a.key is None and led.keys() == (KEY,)


# =========================================================================== supersession and ordering


@pytest.mark.parametrize("old,new,basis", [
    (dict(seq=1), dict(seq=2), OrderBasis.SOURCE_SEQUENCE),
    (dict(published=-10), dict(published=50), OrderBasis.SOURCE_PUBLICATION),
    (dict(requested=-1), dict(requested=59), OrderBasis.FETCH_WINDOWS),
])
def test_supersession_needs_a_source_order_or_disjoint_fetch_windows(old, new, basis):
    a, b = env("open", at=0, **old), env("closed", at=60, **new)
    led = ledger(a, b)
    rec = led.records[1]
    assert rec.kind is ChangeKind.CHANGED and rec.order_basis is basis and rec.novel
    assert rec.links == ((LinkKind.SUPERSEDES, a.envelope_id),)
    assert led.current(KEY) == {"kalshi_public": (b,)}


def test_receipt_order_alone_never_orders_two_copies():
    a, b = env("open", at=0), env("closed", at=60)  # no seq, no stamps, no request times
    assert sc.copy_order(b, a) == (CopyOrder.UNORDERED, None)
    led = ledger(a, b)
    assert led.records[1].kind is ChangeKind.ORDER_UNKNOWN
    assert led.records[1].links == ((LinkKind.UNORDERED_WITH, a.envelope_id),)
    assert led.current(KEY)["kalshi_public"] == (a, b)


def test_overlapping_fetches_stay_unordered_until_a_provably_newer_copy_arrives():
    a = env("open", at=10, requested=0, published=5)
    b = env("closed", at=8, requested=1, published=6)  # the fetches overlap and the stamps overlap within +-3 s
    c = env("settled", at=30, requested=20)
    led = ledger(a, b)
    assert led.records[1].kind is ChangeKind.ORDER_UNKNOWN
    assert a.freshness(T0 + timedelta(seconds=40)) is b.freshness(T0 + timedelta(seconds=40)) is Freshness.FRESH
    state, reasons = key_freshness(led, KEY, T0 + timedelta(seconds=40))
    assert state is Freshness.UNKNOWN and "AMBIGUOUS" in reasons[0]
    with pytest.raises(StaleDataError):
        require_current(led, KEY, T0 + timedelta(seconds=40))
    led = led.append(c)
    assert led.records[2].kind is ChangeKind.CHANGED
    assert set(led.records[2].links) == {(LinkKind.SUPERSEDES, a.envelope_id), (LinkKind.SUPERSEDES, b.envelope_id)}
    assert led.current(KEY)["kalshi_public"] == (c,)


def test_reordered_arrival_reaches_the_same_current_state_in_every_order():
    copies = [env(v, at=at, seq=s) for v, at, s in (("open", 0, 1), ("halted", 5, 2), ("open", 9, 3),
                                                   ("closed", 12, 4))]
    finals = set()
    for perm in itertools.permutations(copies):
        led = ledger(*perm)
        (cur,) = led.current(KEY)["kalshi_public"]
        finals.add(cur.content_sha256)
        assert led.current(KEY)["kalshi_public"][0].upstream_seq == 4
    assert finals == {payload_sha256({"value": "closed"})}
    led = ledger(copies[3], copies[0])  # the newest arrives first
    assert led.records[1].kind is ChangeKind.LATE_ARRIVAL and led.records[1].novel
    assert led.records[1].links == ((LinkKind.SUPERSEDED_BY, copies[3].envelope_id),)


def test_a_revert_to_earlier_content_is_a_change_when_ordered():
    a, b, c = env("open", at=0, seq=1), env("halted", at=5, seq=2), env("open", at=9, seq=3)
    led = ledger(a, b, c)
    assert kinds(led) == [ChangeKind.NEW, ChangeKind.CHANGED, ChangeKind.CHANGED]
    assert not led.records[2].novel  # the content was seen before; the change is still a change
    assert led.current(KEY)["kalshi_public"] == (c,)


def test_a_late_copy_of_older_content_is_a_late_arrival_and_keeps_the_newer_current():
    a, b = env("open", at=0, seq=1), env("closed", at=5, seq=2)
    a_late = env("open", at=9, seq=1)
    led = ledger(a, b, a_late)
    assert led.records[2].kind is ChangeKind.LATE_ARRIVAL
    assert led.current(KEY)["kalshi_public"] == (b,)


def test_sequence_scopes_must_match_to_compare():
    a, b = env("open", at=0, seq=9, scope="per subscription"), env("closed", at=5, seq=2, scope="per market")
    assert sc.copy_order(b, a) == (CopyOrder.UNORDERED, None)


def test_same_sequence_with_different_content_is_a_self_contradiction():
    a, b = env("open", at=0, seq=7, published=-1), env("closed", at=1, seq=7, published=0)
    assert sc.copy_order(b, a) == (CopyOrder.CONFLICT, OrderBasis.SOURCE_SEQUENCE)
    led = ledger(a, b)
    assert led.records[1].kind is ChangeKind.SEQUENCE_CONFLICT
    assert led.records[1].links == ((LinkKind.CONTRADICTS, a.envelope_id),)
    assert a.freshness(T0 + SEC) is b.freshness(T0 + SEC) is Freshness.FRESH
    assert key_freshness(led, KEY, T0 + SEC)[0] is Freshness.UNKNOWN


# =========================================================================== contradiction across sources


def test_cross_source_contradiction_is_linked_listed_and_fails_closed():
    a = env("open", at=0, published=-1)
    b = env("closed", at=2, source="polymarket_us_public", family="PM", published=0,
            pub_unc=timedelta(milliseconds=500))
    led = ledger(a, b)
    assert led.records[1].kind is ChangeKind.NEW
    assert led.records[1].links == ((LinkKind.CONTRADICTS, a.envelope_id),)
    assert led.contradictions(KEY) == (("kalshi_public", "polymarket_us_public"),)
    now = T0 + timedelta(seconds=5)
    state, reasons = key_freshness(led, KEY, now)
    assert state is Freshness.UNKNOWN and any("CONTRADICTION" in r for r in reasons)
    with pytest.raises(StaleDataError, match="CONTRADICTION"):
        require_current(led, KEY, now)
    require_current(led, KEY, now, sources=["kalshi_public"])  # one source alone is fresh and unambiguous


# =========================================================================== clocks: skew and missing upstream time


def test_clock_skew_beyond_the_bound_is_refused_within_it_is_accepted():
    with pytest.raises(ValueError, match="FUTURE_PUBLICATION"):
        env(at=0, published=10)  # provably after our receipt, even with 2 s + 1 s of error
    ok = env(at=0, published=2)  # inside the bounds: accepted, never treated as ordered
    assert ok.claimed_published is not None
    skewed = env(at=0, published=10, pub_unc=None)  # an unknown bound cannot be shown inconsistent ...
    assert skewed.freshness(T0) is Freshness.UNKNOWN  # ... and gives no known content age


def test_missing_upstream_time_is_unknown_until_the_receipt_alone_proves_stale():
    e = env(at=0)
    assert e.claimed_published is None
    assert e.freshness(T0 + timedelta(minutes=1)) is Freshness.UNKNOWN
    assert e.freshness(T0 + timedelta(hours=1)) is Freshness.STALE


# =========================================================================== stale propagation (require_fresh)


def test_a_stale_input_propagates_through_key_freshness_into_require_fresh():
    fresh = env("open", at=0, published=-5)
    stale = env("open", at=0, source="nws_cli_central_park", kind="cli_product", family="NWS",
                published=-40 * 3600, pub_unc=timedelta(seconds=2))
    led = ledger(fresh, stale)
    now = T0 + timedelta(seconds=10)
    assert fresh.freshness(now) is Freshness.FRESH and stale.freshness(now) is Freshness.STALE
    assert key_freshness(led, KEY, now, sources=["kalshi_public"])[0] is Freshness.FRESH
    assert key_freshness(led, KEY, now)[0] is Freshness.STALE
    with pytest.raises(StaleDataError, match="stale"):
        require_current(led, KEY, now)
    with pytest.raises(StaleDataError, match="unknown"):
        require_current(led, KEY, now, sources=["the_odds_api"])  # no copy is UNKNOWN
    with pytest.raises(StaleDataError):
        require_current(ChangeLedger(), KEY, now)


# =========================================================================== cost: unknown is never zero


def test_unknown_cost_is_never_zero():
    with pytest.raises(ValueError, match="unknown is None"):
        FetchCost(CostBasis.UNKNOWN, requests=0)
    with pytest.raises(ValueError, match="unknown is None"):
        FetchCost(CostBasis.UNKNOWN, money_usd=D("0"))
    with pytest.raises(ValueError, match="zero money needs"):
        FetchCost(CostBasis.ESTIMATED, 1, money_usd=D("0"), reference="guess")
    with pytest.raises(ValueError, match="zero money needs"):
        FetchCost(CostBasis.DOCUMENTED, 1, money_usd=D("0"))
    with pytest.raises(ValueError, match="states how many requests"):
        FetchCost(CostBasis.MEASURED, None, credits=D("1"))
    assert total_cost([]) == UNKNOWN_COST
    paid = FetchCost(CostBasis.MEASURED, 2, D("2"), D("0.03"), "fixture quota header")
    assert total_cost([FREE, paid]) == FetchCost(CostBasis.DOCUMENTED, 3, None, D("0.03"),
                                                 "fixture quota header; fixture: documented keyless endpoint")
    assert total_cost([paid, paid]).credits == D("4")
    assert total_cost([FREE, UNKNOWN_COST]) == UNKNOWN_COST


def test_source_yield_reports_money_per_novel_item_only_when_known():
    led = ledger(env("open", at=0, requested=-1), env("open", at=60, requested=59),
                 env("closed", at=120, requested=119, cost=UNKNOWN_COST))
    y = led.source_yield("kalshi_public")
    assert y.envelopes == 3 and y.novel == 2
    assert dict(y.by_kind)[ChangeKind.DUPLICATE] == 1
    assert y.cost == UNKNOWN_COST and y.money_per_novel is None
    y2 = ledger(env("open", at=0, requested=-1), env("closed", at=60, requested=59)).source_yield("kalshi_public")
    assert y2.cost.money_usd == D("0") and y2.money_per_novel == D("0") and y2.data_kinds == ("FIXTURE",)


# =========================================================================== determinism and the boundary


def test_the_ledger_is_deterministic_and_append_only():
    envs = list(sc.read_envelopes(FIXTURE))
    one, two = ledger(*envs), ledger(*envs)
    assert [(r.kind, r.links, r.envelope_id) for r in one.records] == \
        [(r.kind, r.links, r.envelope_id) for r in two.records]
    before = ledger(*envs[:2])
    after = before.append(envs[2])
    assert len(before.records) == 2 and len(after.records) == 3  # appending returns a new ledger


ALLOWED_IMPORTS = {"__future__", "json", "dataclasses", "datetime", "decimal", "enum", "pathlib", "typing",
                   "discovery", "freshness", "inplay_evidence", "provenance", "sources"}


def test_the_module_imports_only_pure_owners_and_no_transport():
    path = Path(sc.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= ALLOWED_IMPORTS, names - ALLOWED_IMPORTS
    text = path.read_text(encoding="utf-8")
    for banned in ("urllib", "socket", "http.client", "subprocess", "sqlite3", "threading", "import sched",
                   "time.sleep", "os.environ", "getenv", "execution"):
        assert banned not in text, banned
