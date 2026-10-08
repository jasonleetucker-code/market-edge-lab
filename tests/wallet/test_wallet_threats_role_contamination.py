"""Amendment 2026-10-08 B: contamination evidence (shared activity, funding, churn, counterparty flows).

Every account is SYNTHETIC. Every flag is PROVISIONAL and states that it is not proof of common
ownership or wrongdoing. A detector that cannot run is UNOBSERVABLE, never clean.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from wallet_support import D, acct, at, obs, with_counterparty, with_role

from edge_lab.wallet_intel.events import Action, LiquidityRole
from edge_lab.wallet_intel.threats import (NOT_PROOF, ContaminationEvidence, EvidenceKind, FlagStatus, Observability,
                                           churn_evidence, co_trading_clusters, counterparty_flow_evidence,
                                           shared_activity_evidence)

W = timedelta(minutes=1)


def _co_traders(news_gap: timedelta | None = None):  # type: ignore[no-untyped-def]
    rows = []
    for i in range(4):
        t = at(days=i)
        rows += [obs(acct(1), Action.TRADE_BUY, f"m{i}-yes", 10, "0.4", t, market=f"m{i}"),
                 obs(acct(2), Action.TRADE_BUY, f"m{i}-yes", 10, "0.4", t + timedelta(seconds=20), market=f"m{i}"),
                 obs(acct(3), Action.TRADE_SELL, f"m{i}-yes", 10, "0.4", t + timedelta(hours=3), market=f"m{i}")]
    return rows


def test_shared_activity_is_a_provisional_flag_with_its_evidence():
    rows = _co_traders()
    ev = shared_activity_evidence(rows, window=W, min_shared=3, min_overlap=D("0.6"))
    assert len(ev) == 1
    e = ev[0]
    assert e.kind is EvidenceKind.SHARED_ACTIVITY_TIMING and e.status is FlagStatus.PROVISIONAL_FLAG
    assert e.provisional and NOT_PROOF in e.uncertainty
    assert "COMMON_PUBLIC_INFORMATION_NOT_EXCLUDED" in e.uncertainty
    assert e.accounts == (acct(1).key, acct(2).key) and len(e.observation_ids) == 8
    # It is exactly the evidence behind the existing cluster screen, whose output is unchanged.
    clusters = co_trading_clusters(rows, window=W, min_shared=3, min_overlap=D("0.6"))
    assert clusters[acct(1).key] == clusters[acct(2).key] != clusters[acct(3).key]


def test_coincident_public_news_is_recorded_as_an_alternative_explanation():
    rows = _co_traders()
    news = [at(days=i) - timedelta(seconds=5) for i in range(4)]
    e = shared_activity_evidence(rows, window=W, min_shared=3, min_overlap=D("0.6"), public_events=news)[0]
    assert any(u.startswith("COINCIDENT_PUBLIC_EVENT") for u in e.uncertainty)
    far = shared_activity_evidence(rows, window=W, min_shared=3, min_overlap=D("0.6"),
                                   public_events=[at(days=-5)])[0]
    assert not any(u.startswith("COINCIDENT_PUBLIC_EVENT") for u in far.uncertainty)


def test_no_shared_activity_is_no_flag_not_a_clearance():
    rows = [obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0)),
            obs(acct(2), Action.TRADE_BUY, "m1-yes", 10, "0.4", at(days=2))]
    ev = shared_activity_evidence(rows, window=W, min_shared=1, min_overlap=D("0.5"))
    assert [e.status for e in ev] == [FlagStatus.NO_FLAG] and ev[0].uncertainty == ()


def test_stated_funding_link_is_provisional():
    rows = [obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0)),
            obs(acct(2), Action.TRADE_BUY, "m2-yes", 10, "0.4", at(days=2), market="m2")]
    ev = shared_activity_evidence(rows, window=W, min_shared=9, min_overlap=D(1),
                                  funding_sources={acct(1).key: "src-x", acct(2).key: "src-x"})
    assert [e.kind for e in ev] == [EvidenceKind.STATED_FUNDING_LINK]
    assert NOT_PROOF in ev[0].uncertainty and "SHARED_FUNDING_SOURCE_MAY_BE_AN_EXCHANGE_OR_BRIDGE" in ev[0].uncertainty


def _round_trips(role: LiquidityRole | None, transfer: bool = False):  # type: ignore[no-untyped-def]
    a = acct(1)
    rows = []
    for i in range(3):
        b = obs(a, Action.TRADE_BUY, f"m{i}-yes", 100, "0.45", at(days=i), market=f"m{i}")
        s = obs(a, Action.TRADE_SELL, f"m{i}-yes", 100, "0.55", at(days=i, minutes=5), market=f"m{i}")
        rows += [b, s] if role is None else [with_role(b, role), with_role(s, role)]
    if transfer:
        rows.append(obs(a, Action.TRANSFER_OUT, "m9-yes", 10, when=at(days=5), market="m9"))
    return rows


def test_churn_flag_notes_market_making_when_the_round_trips_are_maker_fills():
    maker = churn_evidence(_round_trips(LiquidityRole.MAKER), max_hold=timedelta(hours=1), threshold=D("0.5"))[0]
    assert maker.status is FlagStatus.PROVISIONAL_FLAG
    assert "MAKER_ROUND_TRIPS_ARE_CONSISTENT_WITH_MARKET_MAKING" in maker.uncertainty
    unknown = churn_evidence(_round_trips(None), max_hold=timedelta(hours=1), threshold=D("0.5"))[0]
    assert "LIQUIDITY_ROLE_UNKNOWN" in unknown.uncertainty
    assert "MAKER_ROUND_TRIPS_ARE_CONSISTENT_WITH_MARKET_MAKING" not in unknown.uncertainty
    taker = churn_evidence(_round_trips(LiquidityRole.TAKER), max_hold=timedelta(hours=1), threshold=D("0.5"))[0]
    assert "MAKER_ROUND_TRIPS_ARE_CONSISTENT_WITH_MARKET_MAKING" not in taker.uncertainty
    held = churn_evidence(_round_trips(LiquidityRole.MAKER), max_hold=timedelta(minutes=1), threshold=D("0.5"))[0]
    assert held.status is FlagStatus.NO_FLAG


def test_transfers_are_not_churn_but_are_noted():
    e = churn_evidence(_round_trips(None, transfer=True), max_hold=timedelta(hours=1), threshold=D("0.5"))[0]
    assert e.status is FlagStatus.PROVISIONAL_FLAG
    assert any(u.startswith("TOKEN_TRANSFERS_PRESENT") for u in e.uncertainty)
    only_transfers = [obs(acct(1), Action.TRANSFER_IN, "m1-yes", 10), obs(acct(1), Action.TRANSFER_OUT, "m1-yes", 10)]
    assert churn_evidence(only_transfers, max_hold=timedelta(hours=1), threshold=D("0.5")) == ()


def test_no_known_counterparty_is_unobservable_not_clean():
    rows = _co_traders()
    ev = counterparty_flow_evidence(rows, window=timedelta(hours=1))
    assert {e.kind for e in ev} == {EvidenceKind.SELF_TRADE_REPORTED_COUNTERPARTY,
                                    EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY}
    assert all(e.status is FlagStatus.UNOBSERVABLE and e.observability is Observability.UNOBSERVABLE for e in ev)


def test_explicit_synthetic_self_trade_is_flagged_provisionally():
    a = acct(1)
    self_fill = with_counterparty(obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0)), a)
    other = with_counterparty(obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(5)), acct(2))
    ev = counterparty_flow_evidence([self_fill, other], window=timedelta(hours=1))
    selfs = [e for e in ev if e.kind is EvidenceKind.SELF_TRADE_REPORTED_COUNTERPARTY]
    assert [e.status for e in selfs] == [FlagStatus.PROVISIONAL_FLAG]
    assert selfs[0].observation_ids == (self_fill.observation_id,)
    assert {NOT_PROOF, "SELF_MATCH_MAY_BE_ACCIDENTAL", "COUNTERPARTY_AS_REPORTED_BY_SOURCE"} <= set(selfs[0].uncertainty)
    assert selfs[0].observability is Observability.OBSERVED


def test_explicit_synthetic_circular_flow_across_three_accounts():
    a, b, c = acct(1), acct(2), acct(3)
    # Token m1-yes: a -> b (b buys from a), b -> c (c buys from b), c -> a (a buys from c).
    rows = [with_counterparty(obs(b, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0)), a),
            with_counterparty(obs(c, Action.TRADE_BUY, "m1-yes", 10, "0.41", at(2)), b),
            with_counterparty(obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.42", at(4)), c)]
    circ = [e for e in counterparty_flow_evidence(rows, window=timedelta(minutes=10))
            if e.kind is EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY]
    assert [e.status for e in circ] == [FlagStatus.PROVISIONAL_FLAG]
    assert circ[0].accounts == tuple(sorted((a.key, b.key, c.key))) and len(circ[0].observation_ids) == 3
    assert NOT_PROOF in circ[0].uncertainty and "REVERSALS_CAN_BE_ORDINARY_TRADING" in circ[0].uncertainty
    # Outside the window it is not a circle.
    late = counterparty_flow_evidence(rows, window=timedelta(minutes=3))
    assert [e.status for e in late if e.kind is EvidenceKind.CIRCULAR_FLOW_REPORTED_COUNTERPARTY] == [FlagStatus.NO_FLAG]


def test_two_party_reversal_reported_from_both_sides_is_one_circle():
    a, b = acct(1), acct(2)
    buy_b = obs(b, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0), tx="0xsyn-a")
    sell_a = obs(a, Action.TRADE_SELL, "m1-yes", 10, "0.40", at(0), tx="0xsyn-a")  # the same fill, other side
    back = obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.41", at(3))
    rows = [with_counterparty(buy_b, a), with_counterparty(sell_a, b), with_counterparty(back, b), ]
    circ = [e for e in counterparty_flow_evidence(rows, window=timedelta(minutes=10))
            if e.status is FlagStatus.PROVISIONAL_FLAG]
    assert len(circ) == 1 and circ[0].accounts == tuple(sorted((a.key, b.key)))


def test_partial_counterparty_coverage_is_partial_observability():
    a, b = acct(1), acct(2)
    rows = [with_counterparty(obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0)), b),
            obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(1))]
    ev = counterparty_flow_evidence(rows, window=timedelta(hours=1))
    assert all(e.observability is Observability.PARTIAL and e.status is FlagStatus.NO_FLAG for e in ev)


def test_evidence_invariants_are_enforced():
    with pytest.raises(ValueError, match="provisional"):
        ContaminationEvidence("x", EvidenceKind.ROUND_TRIP_CHURN, FlagStatus.NO_FLAG, Observability.OBSERVED, (), (),
                              (), "", provisional=False)
    with pytest.raises(ValueError, match="not proof"):
        ContaminationEvidence("x", EvidenceKind.ROUND_TRIP_CHURN, FlagStatus.PROVISIONAL_FLAG, Observability.OBSERVED,
                              (), (), (), "")
    with pytest.raises(ValueError, match="UNOBSERVABLE"):
        ContaminationEvidence("x", EvidenceKind.ROUND_TRIP_CHURN, FlagStatus.UNOBSERVABLE, Observability.OBSERVED,
                              (), (), (), "")
