"""Amendment 2026-10-08 B: follower copyability (read from the canonical replay), the versioned report
readers, and pins proving the optional annotations change no existing identity, digest or report.

Every account, book and signal is SYNTHETIC. A COPYABLE verdict is a simulation over captured depth,
never evidence that a real follower could or did fill, and never evidence of an edge.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from wallet_support import (D, Books, InvalidBooks, acct, at, book, config, enrolled, fixture, limits, obs, signal,
                            with_counterparty, with_role)

from edge_lab.provenance import canonical_json, sha256_hex
from edge_lab.wallet_intel import polymarket_v2 as pm
from edge_lab.wallet_intel.demo import run_synthetic_demo
from edge_lab.wallet_intel.events import Action, LiquidityRole, ObservationLog
from edge_lab.wallet_intel.exact import Basis
from edge_lab.wallet_intel.policy import FollowerPolicy
from edge_lab.wallet_intel.replay import replay, unknown_fee
from edge_lab.wallet_intel.threats import (OFF_MARKET_V1_SCHEMA, QUALITY_SCHEMA, Copyability, DataClass, FillJudgement,
                                           FlagStatus, LegacyOffMarketView, PriceConsistency, QualityParams,
                                           QualityView, follower_copyability, off_market_fills, off_market_report_v1,
                                           price_consistency, quality_report, read_threat_report)

SPREAD_AT = at(-1)
TOL, AGE, SKEW = D("0.005"), timedelta(minutes=5), timedelta(seconds=2)


def _run(sig, books, *, pol_limits=None, cfg=None):  # type: ignore[no-untyped-def]
    pol = FollowerPolicy(pol_limits or limits(max_price_above_leader=D("0.20")), enrollments=enrolled("L1"))
    return replay([sig], pol, initial_cash=D(100), books=books, resolutions={}, config=cfg or config(),
                  horizon=at(days=1))


# --- The regression, follower side ---------------------------------------------------------------------

def test_consistent_maker_buy_at_045_does_not_mean_a_follower_gets_045():
    leader = with_role(obs(acct(1), Action.TRADE_BUY, "m1-yes", 100, "0.45", at(0)), LiquidityRole.MAKER)
    books = Books(book(bid="0.45", ask="0.55", captured=SPREAD_AT), book(bid="0.45", ask="0.55", captured=at(1)))
    lc = {r.observation_id: r for r in price_consistency([leader], books, tolerance=TOL, max_book_age=AGE,
                                                         max_clock_skew=SKEW)}
    assert lc[leader.observation_id].verdict is PriceConsistency.CONSISTENT
    sig = signal(leader.observation_id, price="0.45", qty="100")
    r = _run(sig, books)
    v = follower_copyability(r, [sig], books=books, leader_consistency=lc)[0]
    assert v.leader_price_consistency is PriceConsistency.CONSISTENT  # carried, separate
    assert v.verdict is Copyability.COPYABLE
    assert v.follower_avg_price.value == D("0.55") and v.follower_avg_price.basis is Basis.ESTIMATED
    assert v.adverse_gap_per_unit.value == D("0.1")  # the follower pays the ask, not the leader's 0.45
    assert v.book_age_at_arrival == timedelta(seconds=2)  # arrival at 1m02s; book captured at 1m
    # With the default 0.05 price cap the follower cannot reach the ask at all.
    tight = _run(sig, books, pol_limits=limits())
    assert follower_copyability(tight, [sig])[0].verdict is Copyability.NOT_COPYABLE


def test_copyability_cases_from_replay_statuses():
    fresh = book(captured=at(1))  # bid 0.39 / ask 0.41, two levels of 100
    cases = {
        "filled": (signal("filled"), Books(fresh), {}, Copyability.COPYABLE),
        "partial": (signal("partial"), Books(book(captured=at(1), levels=1, size="5", truncated=True)),
                    {}, Copyability.PARTIALLY_COPYABLE),
        "no-book": (signal("nobook"), Books(), {}, Copyability.UNKNOWN),
        "stale": (signal("stale"), Books(book(captured=at(-60))), {}, Copyability.UNKNOWN),
        "no-asks": (signal("noasks"), Books(book(ask=None, captured=at(1))), {}, Copyability.NOT_COPYABLE),
        "crossed": (signal("crossed"), InvalidBooks("0.42", "0.41"), {}, None),
    }
    for name, (sig, books, _, expected) in cases.items():
        if expected is None:
            with pytest.raises(ValueError):  # replay itself refuses an invalid capture: never a fill
                _run(sig, books)
            continue
        v = follower_copyability(_run(sig, books), [sig], books=books)[0]
        assert v.verdict is expected, (name, v.reason)
        if expected in (Copyability.UNKNOWN, Copyability.NOT_COPYABLE):
            assert v.follower_avg_price.basis is Basis.UNKNOWN and v.filled == 0


def test_unknown_fee_keeps_the_fill_but_not_the_cost():
    sig = signal("f")
    r = _run(sig, Books(book(captured=at(1))), cfg=config(fee_fn=unknown_fee))
    v = follower_copyability(r, [sig])[0]
    assert v.verdict is Copyability.COPYABLE and not v.fee.known
    assert r.follower.net_pnl.basis is Basis.UNKNOWN
    assert v.book_age_at_arrival is None  # no provider given: unknown, not zero


def test_unknown_request_outcome_is_unknown_and_skips_are_kept():
    from edge_lab.wallet_intel.replay import RequestResult
    sig = signal("u")
    cfg = replace(config(), request_outcome=lambda sid, n: RequestResult.UNKNOWN)
    assert follower_copyability(_run(sig, Books(book(captured=at(1))), cfg=cfg), [sig])[0].verdict \
        is Copyability.UNKNOWN
    tiny = signal("tiny", qty="1", price="0.30")
    pol = limits(min_leader_notional=D(5))
    v = follower_copyability(_run(tiny, Books(book(captured=at(1))), pol_limits=pol), [tiny])[0]
    assert v.verdict is Copyability.NOT_ATTEMPTED and "TINY_SIGNAL" in v.reason  # in the denominator


def test_sell_gap_sign_and_serialization():
    buy = signal("b", when=at(0), qty="100", price="0.40")
    sell = signal("s", Action.TRADE_SELL, when=at(10), qty="100", price="0.45", before="100")
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    books = Books(book(captured=at(1)), book(bid="0.42", ask="0.44", captured=at(11)))
    r = replay([buy, sell], pol, initial_cash=D(100), books=books, resolutions={}, config=config(), horizon=at(days=1))
    vs = {v.signal_id: v for v in follower_copyability(r, [buy, sell], books=books)}
    assert vs["s"].side == "SELL" and vs["s"].follower_avg_price.value == D("0.42")
    assert vs["s"].adverse_gap_per_unit.value == D("0.03")  # leader sold at 0.45, we at 0.42
    d = vs["s"].to_dict()
    json.dumps(d)
    assert d["label"] == "FOLLOWER_SIMULATED" and d["schema"] == "wallet-follower-copyability-v1"


# --- Versioned readers ---------------------------------------------------------------------------------

def test_v1_output_reads_back_as_explicitly_legacy():
    maker = with_role(obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "0.45", at(0)), LiquidityRole.MAKER)
    books = Books(book(bid="0.45", ask="0.55", captured=SPREAD_AT))
    rows = off_market_fills([maker], books, tolerance=TOL, max_book_age=AGE)
    payload = json.loads(json.dumps(off_market_report_v1(rows)))
    view = read_threat_report(payload)
    assert isinstance(view, LegacyOffMarketView) and view.schema == OFF_MARKET_V1_SCHEMA and not view.role_aware
    assert view.rows == rows and view.rows[0].judgement is FillJudgement.OFF_MARKET
    assert "not evidence of manipulation" in view.interpretation


def _params() -> QualityParams:
    return QualityParams(TOL, AGE, SKEW, timedelta(minutes=1), 2, D("0.5"), timedelta(hours=1), D("0.5"),
                         timedelta(hours=1))


def test_v2_report_round_trips_and_keeps_the_concepts_separate():
    a, b = acct(1), acct(2)
    rows = [with_role(obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.45", at(0)), LiquidityRole.MAKER),
            with_counterparty(obs(b, Action.TRADE_SELL, "m1-yes", 10, "0.45", at(0)), a),
            obs(a, Action.TRANSFER_OUT, "m1-yes", 10, when=at(3))]
    books = Books(book(bid="0.45", ask="0.55", captured=SPREAD_AT))
    rep = quality_report(rows, books, params=_params(), data_class=DataClass.SYNTHETIC)
    payload = json.loads(json.dumps(rep.to_dict()))
    view = read_threat_report(payload)
    assert isinstance(view, QualityView) and view.schema == QUALITY_SCHEMA and view.role_aware
    assert view.data_class is DataClass.SYNTHETIC
    assert view.roles == {rows[0].observation_id: LiquidityRole.MAKER, rows[1].observation_id: LiquidityRole.UNKNOWN}
    assert view.price[rows[0].observation_id] is PriceConsistency.CONSISTENT
    assert view.price[rows[1].observation_id] is PriceConsistency.CONSISTENT  # unknown role: some role explains it
    assert rows[2].observation_id not in view.price  # a transfer has no execution price
    assert any(s is FlagStatus.NO_FLAG for _, _, s, _ in view.contamination)
    assert "score" not in json.dumps(payload).lower()  # four concepts, never one score


def test_unknown_schema_is_refused_and_synthetic_cannot_be_observed():
    with pytest.raises(ValueError, match="unknown threat report schema"):
        read_threat_report({"schema": "wallet-quality-diagnostics-v9"})
    with pytest.raises(ValueError, match="OBSERVED"):
        quality_report([obs(acct(1), Action.TRADE_BUY)], Books(), params=_params(), data_class=DataClass.OBSERVED)


# --- No change to existing identities, digests or reports (lane WA builds receipts over them) ----------
# Pinned on origin/main c34221c before this change. If another lane deliberately changes the demo
# report, it updates DEMO_PIN in its own PR; observation identities must never move.

DEMO_PIN = "5d57aa10301277edc6474a889b7a3c4f9bd51f95de2342864fc1cabf140ed8ea"
MANIFEST_PIN = "0e38000ae1d1621300b2b7a2b37fb48699a067894e7c45ee052b7f304ddc9e4f"
FIXTURE_PINS = {"activity_page1.json": "e967f8b7119fcd0fe171cdea522e0a84e16d06655309b98a0905f68563878d27",
                "trades_page.json": "ad32d3e7588c914345a141d202e99c8d0f749d7a8c8cf687cea26e4b20902cba"}
SUPPORT_PIN = ("synthetic:synthetic_venue|0xsynthetic0001:tx:0xpin:0",
               "c3dfb1b0cde9d6c5d6317694d830b96138cf784270dc655e84d43b6f667f4a32")


def test_fixture_observation_identities_are_unchanged():
    for name, parse in (("activity_page1.json", pm.parse_activity_page), ("trades_page.json", pm.parse_trades_page)):
        page = parse(fixture(name), receipt_time=at(days=30), synthetic=True)
        got = sha256_hex(canonical_json([[o.observation_id, o.semantic_key] for o in page.observations]))
        assert got == FIXTURE_PINS[name], name


def test_annotations_do_not_enter_identity_or_dedup():
    o = obs(acct(1), Action.TRADE_BUY, "m1-yes", 100, "0.45", at(0), tx="0xpin", sub_index=0)
    assert (o.observation_id, o.semantic_key) == SUPPORT_PIN
    annotated = with_counterparty(with_role(o, LiquidityRole.MAKER), acct(2))
    assert (annotated.observation_id, annotated.semantic_key) == SUPPORT_PIN
    log = ObservationLog()
    log.ingest([o])
    assert log.ingest([annotated]) == {"added": 0, "duplicates": 1, "conflicts": 0}  # documented limit


def test_demo_report_and_v1_manifest_digest_are_unchanged():
    report = run_synthetic_demo(20261007)
    assert report["eligibility"]["manifest"]["inputs_digest"] == MANIFEST_PIN
    assert report["report_sha256"] == DEMO_PIN


def test_counterparty_needs_its_source():
    o = obs(acct(1), Action.TRADE_BUY)
    with pytest.raises(ValueError, match="counterparty"):
        replace(o, counterparty=acct(2))
    with pytest.raises(ValueError, match="counterparty"):
        replace(o, counterparty_source="fixture:x")


def test_book_provenance_fields_are_optional_and_aware():
    b = book(captured=at(0))
    assert b.source is None and b.raw_ref is None and b.received_at is None
    with pytest.raises(ValueError):
        replace(b, received_at=at(0).replace(tzinfo=None))
