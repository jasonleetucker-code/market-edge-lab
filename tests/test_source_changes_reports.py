"""Source change/event envelope v1 reports (#181 E): observation-to-market response latency, first-report
leadership and attribution. FIXTURE input only; nothing here is evidence of an edge."""

from __future__ import annotations

from datetime import timedelta

import pytest

from edge_lab.inplay_evidence import DataKind, Dependence, EvidenceStatus, LeadershipStatus, SourceContext
from edge_lab.source_changes import (
    NOT_PROOF_OF_ORIGIN, ChangeLedger, IdentityBasis, LinkBasis, ResponseStatus, SubjectLink, SubjectRef, TimeBasis,
    attribution, first_report_leadership, response_latency,
)

from test_source_changes import KAL, MS, env, ledger

CLI = SubjectRef("nws:product:CLI:NYC", "2026-10-07", IdentityBasis.SOURCE_NATIVE)
OTHER = SubjectRef("kalshi:market", "KXHIGHNY-26OCT08-B72", IdentityBasis.SOURCE_NATIVE)
LINK = SubjectLink(CLI.key, KAL.key, LinkBasis.DECLARED_MAPPING, "fixture-mapping-v1: CLINYC max -> KXHIGHNY bracket")
EPS = 2 * MS  # two same-clock readings carry only their precision


def observation(at=100.0, **kw):
    kw.setdefault("published", at - 30)
    return env(71, at=at, source="nws_cli_central_park", kind="cli_product", subject=CLI, aspect="max_temp_f",
               family="NWS", **kw)


def quote(value, at, subject=KAL, **kw):
    return env(value, at=at, subject=subject, aspect="yes_bid", **kw)


# =========================================================================== response latency


def test_a_response_is_a_window_between_the_bracketing_captures():
    market = [quote("0.40", 0), quote("0.40", 60), quote("0.40", 110), quote("0.55", 130), quote("0.55", 200)]
    r = response_latency(observation(), market, LINK)
    assert r.status is ResponseStatus.RESPONDED and r.data_kind is DataKind.FIXTURE
    assert r.lower == timedelta(seconds=10) - EPS and r.upper == timedelta(seconds=30) + EPS
    assert r.capture_gap == timedelta(seconds=20)
    assert r.market_key == KAL.key and "not evidence of an edge" in r.note


def test_the_market_never_changing_gives_only_a_lower_bound():
    r = response_latency(observation(), [quote("0.40", 60), quote("0.40", 110), quote("0.40", 150)], LINK)
    assert r.status is ResponseStatus.NO_RESPONSE_OBSERVED
    assert r.lower == timedelta(seconds=50) - EPS and r.upper is None


def test_no_baseline_before_the_observation_is_unknown():
    r = response_latency(observation(), [quote("0.40", 110), quote("0.55", 130)], LINK)
    assert r.status is ResponseStatus.UNKNOWN and r.reasons[0].startswith("NO_BASELINE")
    assert r.lower is None and r.upper is None


def test_a_change_that_cannot_be_placed_before_or_after_is_unordered():
    r = response_latency(observation(), [quote("0.40", 60), quote("0.55", 100.0005)], LINK)
    assert r.status is ResponseStatus.UNORDERED and r.lower is None


@pytest.mark.parametrize("link,reason", [
    (None, "IDENTITY_UNESTABLISHED"),
    (SubjectLink(CLI.key, None, LinkBasis.UNKNOWN), "IDENTITY_UNESTABLISHED"),
    (SubjectLink("nws:product:CLI:NYC|2026-10-06", KAL.key, LinkBasis.DECLARED_MAPPING, "m"), "IDENTITY_MISMATCH"),
])
def test_identity_that_cannot_be_established_is_unknown(link, reason):
    r = response_latency(observation(), [quote("0.40", 60), quote("0.55", 130)], link)
    assert r.status is ResponseStatus.UNKNOWN and r.reasons[0].startswith(reason)


def test_a_capture_on_another_market_is_an_identity_mismatch_not_a_silent_filter():
    market = [quote("0.40", 60), quote("0.55", 130, subject=OTHER)]
    r = response_latency(observation(), market, LINK)
    assert r.status is ResponseStatus.UNKNOWN and r.reasons[0].startswith("IDENTITY_MISMATCH")
    with pytest.raises(ValueError, match="SAME_ID"):
        SubjectLink(CLI.key, KAL.key, LinkBasis.SAME_ID)


def test_cross_clock_latency_widens_by_both_error_bounds_and_unknown_bounds_are_unknown():
    market = [quote("0.40", 60), quote("0.40", 110), quote("0.55", 130)]
    r = response_latency(observation(), market, LINK, start_basis=TimeBasis.PUBLISHED)  # source clock, +-2 s
    assert r.status is ResponseStatus.RESPONDED
    err = timedelta(seconds=1) + MS + timedelta(seconds=2) + timedelta(milliseconds=50)
    assert r.lower == timedelta(seconds=40) - err and r.upper == timedelta(seconds=60) + err
    skewed = observation(pub_unc=None)  # an unknown source-clock bound
    r2 = response_latency(skewed, market, LINK, start_basis=TimeBasis.PUBLISHED)
    assert r2.status is ResponseStatus.UNKNOWN and r2.reasons[0].startswith("CLOCK_UNKNOWN")


def test_a_missing_upstream_time_makes_a_published_basis_latency_unknown():
    obs = env(71, at=100, source="nws_cli_central_park", kind="cli_product", subject=CLI, aspect="max_temp_f")
    r = response_latency(obs, [quote("0.40", 60), quote("0.55", 130)], LINK, start_basis=TimeBasis.PUBLISHED)
    assert r.status is ResponseStatus.UNKNOWN and r.reasons[0].startswith("START_UNKNOWN")


def test_reports_refuse_recorded_and_mixed_input():
    rec = env(71, at=100, source="nws_api", kind="forecast", subject=CLI, aspect="max_temp_f",
              data_kind=DataKind.RECORDED, evidence=EvidenceStatus.ACTUAL)
    with pytest.raises(ValueError, match="refused in this batch"):
        response_latency(rec, [quote("0.40", 60, data_kind=DataKind.RECORDED, evidence=EvidenceStatus.ACTUAL)], LINK)
    with pytest.raises(ValueError, match="different data kinds"):
        response_latency(observation(), [quote("0.40", 60, data_kind=DataKind.SYNTHETIC)], LINK)


# =========================================================================== first-report leadership


def _pair(subject, a_times, b_times, *, a="kalshi_public", b="polymarket_us_public", fam_a="KALSHI", fam_b="PM",
          context=SourceContext(None, "KXHIGHNY")):
    """Both sources move `subject` from open to closed; each list gives (receipt, value) captures."""
    out = []
    for source, fam, times in ((a, fam_a, a_times), (b, fam_b, b_times)):
        for at, value in times:
            out.append(env(value, at=at, source=source, subject=subject, family=fam, context=context,
                           kind="markets"))
    return out


def _subjects(n):
    return [SubjectRef("kalshi:market", f"KXHIGHNY-FIX-{i}", IdentityBasis.SOURCE_NATIVE) for i in range(n)]


def _scenario(context3=SourceContext(None, "KXHIGHNY"), **kw):
    s1, s2, s3 = _subjects(3)
    envs = (_pair(s1, [(0, "open"), (10, "closed")], [(0, "open"), (20, "open"), (30, "closed")], **kw)  # a first
            + _pair(s2, [(0, "open"), (40, "open"), (50, "closed")], [(0, "open"), (12, "closed")], **kw)  # b first
            + _pair(s3, [(0, "open"), (10, "closed")], [(0, "open"), (5, "open"), (15, "closed")],  # overlap
                    context=context3, **kw))
    return ledger(*sorted(envs, key=lambda e: e.received.at))


KW = dict(basis=TimeBasis.RECEIVED, condition=None, required_resolution=timedelta(minutes=1), variants_tested=1,
          min_ordered=1)


def test_first_report_leadership_counts_both_directions_and_is_symmetric():
    led = _scenario()
    rep = first_report_leadership(led, "kalshi_public", "polymarket_us_public", **KW)
    assert rep.status is LeadershipStatus.REPORTED and rep.data_kind is DataKind.FIXTURE
    # 3 "closed" items (a first, b first, overlap) + 3 "open" items whose windows are unbounded below
    assert (rep.matched, rep.a_first, rep.b_first, rep.unordered) == (6, 1, 1, 4)
    assert rep.dependence is Dependence.INDEPENDENT_AS_DECLARED
    rev = first_report_leadership(led, "polymarket_us_public", "kalshi_public", **KW)
    assert (rev.a_first, rev.b_first, rev.unordered, rev.matched) == (1, 1, 4, 6)
    lag = {(k, a): m for k, a, m in rep.lags}[(_subjects(3)[0].key, "status")]
    assert lag.value == timedelta(seconds=20)  # b window end - a window end, never a claim of origin
    assert "Not proof of origin" in rep.not_a_causal_claim


def test_leadership_is_conditional_on_the_stated_context():
    live = SourceContext("NFL", "moneyline")
    led = _scenario(context3=live)
    rep = first_report_leadership(led, "kalshi_public", "polymarket_us_public",
                                  **{**KW, "condition": SourceContext(None, "KXHIGHNY")})
    assert rep.excluded_by_condition == 5 and rep.matched == 4 and rep.unordered == 2
    only_live = first_report_leadership(led, "kalshi_public", "polymarket_us_public", **{**KW, "condition": live})
    assert only_live.matched == 2 and only_live.a_first == 0 and only_live.status is \
        LeadershipStatus.INSUFFICIENT_EVIDENCE


def test_polling_resolution_and_clock_bounds_limit_every_claim():
    led = _scenario()
    coarse = first_report_leadership(led, "kalshi_public", "polymarket_us_public",
                                     **{**KW, "required_resolution": timedelta(seconds=5)})
    assert coarse.status is LeadershipStatus.INSUFFICIENT_RESOLUTION and coarse.a_first is None
    s9 = SubjectRef("kalshi:market", "KXHIGHNY-FIX-9", IdentityBasis.SOURCE_NATIVE)
    late_first_look = ledger(*_pair(s9, [(30, "closed")], [(0, "open"), (10, "closed")]))
    rep0 = first_report_leadership(late_first_look, "kalshi_public", "polymarket_us_public", **KW)
    # a's first capture already held "closed": when it first had it is unbounded below, so b is never shown first
    assert (rep0.matched, rep0.a_first, rep0.b_first, rep0.unordered) == (1, 0, 0, 1)
    s1, = _subjects(1)
    pub = ledger(env("closed", at=10, published=8, subject=s1, family="KALSHI"),
                 env("closed", at=12, published=11, pub_unc=None, pub_clock="src:pm", subject=s1,
                     source="polymarket_us_public", family="PM"))
    rep = first_report_leadership(pub, "kalshi_public", "polymarket_us_public", **{**KW, "basis": TimeBasis.PUBLISHED})
    assert rep.status is LeadershipStatus.INSUFFICIENT_RESOLUTION  # an unknown clock bound orders nothing
    known = ledger(env("closed", at=10, published=0, subject=s1, family="KALSHI"),
                   env("closed", at=12, published=9, pub_clock="src:pm", subject=s1, source="polymarket_us_public",
                       family="PM"))
    rep2 = first_report_leadership(known, "kalshi_public", "polymarket_us_public",
                                   **{**KW, "basis": TimeBasis.PUBLISHED})
    assert (rep2.a_first, rep2.b_first) == (1, 0)  # 0 +- 3 s vs 9 +- 3 s on two source clocks: ordered


def test_shared_or_unknown_families_are_reported_as_dependence():
    shared = first_report_leadership(_scenario(fam_b="KALSHI"), "kalshi_public", "polymarket_us_public", **KW)
    assert shared.dependence is Dependence.SHARED_SOURCE
    unknown = first_report_leadership(_scenario(fam_b="UNKNOWN"), "kalshi_public", "polymarket_us_public", **KW)
    assert unknown.dependence is Dependence.UNKNOWN


def test_leadership_refuses_recorded_input_and_requires_a_variant_count():
    rec = ledger(env("open", at=0, data_kind=DataKind.RECORDED, evidence=EvidenceStatus.ACTUAL),
                 env("open", at=1, source="nws_api", kind="forecast", family="NWS", data_kind=DataKind.RECORDED,
                     evidence=EvidenceStatus.ACTUAL))
    with pytest.raises(ValueError, match="refused in this batch"):
        first_report_leadership(rec, "kalshi_public", "nws_api", **KW)
    with pytest.raises(ValueError, match="variants_tested"):
        first_report_leadership(_scenario(), "kalshi_public", "polymarket_us_public", **{**KW, "variants_tested": 0})


# =========================================================================== attribution


def test_a_site_name_or_a_recent_stamp_is_not_proof_of_original_publication():
    s1, = _subjects(1)
    relay = env("closed", at=50, published=-20, subject=s1, source="polymarket_us_public", family="PM",
                attributed_to="Kalshi (as stated by the page)")
    first_seen = env("closed", at=10, published=5, subject=s1)
    led = ledger(first_seen, relay)
    a = attribution(led, (s1.key, "status"), first_seen.content_sha256)
    assert a.earliest_received_source == "kalshi_public"  # we saw it there first ...
    assert a.earliest_claimed_publication_source == "polymarket_us_public"  # ... the other claims it earlier ...
    assert a.original_publication == "UNKNOWN" and a.note == NOT_PROOF_OF_ORIGIN  # ... neither proves origin
    assert a.stated_attributions == (("polymarket_us_public", "Kalshi (as stated by the page)"),)
    no_stamp = env("closed", at=10, subject=s1)
    one = attribution(ledger(no_stamp, relay), (s1.key, "status"), no_stamp.content_sha256)
    assert one.earliest_claimed_publication_source is None  # no stamp: unknown, never the receipt relabelled
    assert attribution(ChangeLedger(), (s1.key, "status"), "0" * 64).sources == ()
