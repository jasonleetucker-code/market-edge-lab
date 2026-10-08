"""Amendment 2026-10-08 B: `ObservationLog` point-in-time views do not depend on ingest order.

Lane WA's finding: version A of an identity received on day 2 and a conflicting version B received on
day 5 gave `[A]` at a day-3 cutoff when ingested A then B, but nothing when ingested B then A. The view
at a cutoff must be a pure function of the copies received by then. Every row here is SYNTHETIC.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import timedelta

import pytest
from wallet_support import D, acct, at, obs, with_counterparty, with_role

from edge_lab.wallet_intel.events import (Action, ChainFinality, Correction, CorrectionKind, LiquidityRole,
                                          ObservationLog)

DAY = timedelta(days=1)


def _wa_pair():  # type: ignore[no-untyped-def]
    a = obs(acct(1), Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0), event_id="fill-wa", receipt_delay=2 * DAY)
    b = replace(a, native_quantity=D(11), received=a.received, receipt_time=at(0) + 5 * DAY)
    return a, b


def test_wa_example_is_order_independent():
    a, b = _wa_pair()
    for order in ([a, b], [b, a]):
        log = ObservationLog()
        for row in order:
            log.ingest([row])
        assert log.as_known_at(at(0) + 3 * DAY) == (a,), order
        assert log.as_known_at(at(0) + 6 * DAY) == ()  # both known: conflicted, reported not resolved
        assert log.as_known_at(at(0) + 6 * DAY, include_conflicted=True) == (a,)  # the earliest received
        assert log.conflicted_ids(at(0) + 3 * DAY) == frozenset()
        assert log.conflicted_ids(at(0) + 6 * DAY) == {a.observation_id}
        assert log.first_receipt(a.observation_id) == at(0) + 2 * DAY


def _universe():  # type: ignore[no-untyped-def]
    """Rows chosen to exercise every order-sensitive path."""
    a, b = _wa_pair()
    rows = [a, b]
    # A duplicate whose earlier copy arrives in a later retrieval.
    d = obs(acct(2), Action.TRADE_BUY, "m2-yes", 5, "0.30", at(10), market="m2", tx="0xdup",
            receipt_delay=4 * DAY)
    rows += [d, replace(d, receipt_time=at(10) + DAY)]
    # One transaction reported with two block times, received out of order.
    t1 = obs(acct(3), Action.TRADE_BUY, "m3-yes", 5, "0.30", at(20), market="m3", tx="0xtwo", sub_index=0,
             receipt_delay=3 * DAY)
    t2 = obs(acct(3), Action.TRADE_BUY, "m3-yes", 6, "0.30", at(25), market="m3", tx="0xtwo", sub_index=1,
             receipt_delay=DAY)
    rows += [t1, t2]
    # A role (and counterparty) stated only by a later copy of the same content.
    r = obs(acct(4), Action.TRADE_BUY, "m4-yes", 5, "0.45", at(30), market="m4", tx="0xrole", sub_index=0,
            receipt_delay=DAY)
    rows += [r, with_counterparty(with_role(replace(r, receipt_time=r.receipt_time + 2 * DAY),
                                            LiquidityRole.MAKER), acct(9))]
    # Copies that disagree about the role, received at the same instant (tie-break).
    q = obs(acct(5), Action.TRADE_SELL, "m5-yes", 5, "0.55", at(40), market="m5", tx="0xtie", sub_index=0,
            receipt_delay=DAY)
    rows += [with_role(q, LiquidityRole.MAKER, "fixture:a"), with_role(q, LiquidityRole.TAKER, "fixture:b")]
    # Two contents of one identity received at the same instant.
    s = obs(acct(6), Action.TRADE_BUY, "m6-yes", 5, "0.20", at(50), market="m6", event_id="fill-same",
            receipt_delay=DAY)
    rows += [s, replace(s, native_quantity=D(7), received=s.received)]
    # Copies identical in content and receipt time, differing only outside identity.
    u = obs(acct(7), Action.TRADE_BUY, "m7-yes", 5, "0.20", at(60), market="m7", tx="0xraw", sub_index=0,
            receipt_delay=DAY)
    rows += [u, replace(u, raw_ref="synthetic:other-copy")]
    corrections = [
        Correction("c-fin", r.observation_id, CorrectionKind.FINALITY_CHANGED, at(30) + 5 * DAY, "confirmed",
                   new_finality=ChainFinality.CONFIRMED),
        Correction("c-sup", r.observation_id, CorrectionKind.SUPERSEDED, at(30) + 4 * DAY, "fixed qty",
                   replacement=replace(r, native_quantity=D(6), parser_version="test-2")),
        Correction("c-ret", d.observation_id, CorrectionKind.RETRACTED, at(10) + 6 * DAY, "source retracted"),
    ]
    return rows, corrections


def _cutoffs(rows, corrections):  # type: ignore[no-untyped-def]
    times = {o.receipt_time for o in rows} | {c.recorded_at for c in corrections}
    eps = timedelta(seconds=1)
    return sorted({t + k for t in times for k in (-eps, timedelta(0), eps)} | {at(days=-1), at(days=30)})


def _snapshot(log, ids, cutoffs):  # type: ignore[no-untyped-def]
    out = []
    for t in cutoffs:
        out.append((t, log.as_known_at(t), log.as_known_at(t, include_conflicted=True), log.conflicted_ids(t),
                    tuple(log.version_at(i, t) for i in ids),
                    tuple(log.version_at(i, t, include_conflicted=True) for i in ids)))
    out.append(tuple(log.first_receipt(i) for i in ids))
    out.append(log.conflicted_ids())
    return out


def _build(rows, corrections, rng):  # type: ignore[no-untyped-def]
    rows = list(rows)
    rng.shuffle(rows)
    log = ObservationLog()
    i = 0
    while i < len(rows):  # random retrieval batches
        n = rng.randint(1, 4)
        log.ingest(rows[i:i + n])
        i += n
    cs = list(corrections)
    rng.shuffle(cs)
    for c in cs:
        log.append_correction(c)
    return log


SEEDS = list(range(60))


@pytest.mark.parametrize("seed", SEEDS)
def test_every_ingest_order_gives_the_same_view_at_every_cutoff(seed):
    rows, corrections = _universe()
    ids = sorted({o.observation_id for o in rows})
    cutoffs = _cutoffs(rows, corrections)
    reference = _snapshot(_build(rows, corrections, random.Random(-1)), ids, cutoffs)
    assert _snapshot(_build(rows, corrections, random.Random(seed)), ids, cutoffs) == reference


def test_the_universe_exercises_each_path():
    rows, corrections = _universe()
    log = _build(rows, corrections, random.Random(7))
    a, b = _wa_pair()
    late = at(0) + 30 * DAY
    r_id = rows[6].observation_id
    # Role and counterparty stated only by the later copy: absent before it arrived, present after.
    assert log.version_at(r_id, rows[6].receipt_time).liquidity_role is LiquidityRole.UNKNOWN
    later = log.version_at(r_id, rows[7].receipt_time)
    assert later.liquidity_role is LiquidityRole.MAKER and later.liquidity_role_source == "fixture:explicit-role"
    assert later.counterparty == acct(9) and later.receipt_time == rows[6].receipt_time
    # Corrections apply in recorded order, not append order: supersede (day 4) then finality (day 5).
    fixed = log.version_at(r_id, late)
    assert fixed.native_quantity == 6 and fixed.finality is ChainFinality.CONFIRMED
    # Disagreeing role copies: UNKNOWN, with the disagreement recorded.
    q = log.version_at(rows[8].observation_id, late)
    assert q.liquidity_role is LiquidityRole.UNKNOWN and "CONFLICTING_LIQUIDITY_ROLE_ANNOTATIONS" in q.ambiguities
    # The out-of-order duplicate is known from its earlier copy; the two-time transaction conflicts
    # only once both block times are known.
    d_id = rows[2].observation_id
    assert log.first_receipt(d_id) == at(10) + DAY and log.version_at(d_id, at(10) + DAY) is not None
    t1, t2 = rows[4], rows[5]
    assert log.conflicted_ids(t2.receipt_time) == frozenset()
    assert {t1.observation_id, t2.observation_id} <= log.conflicted_ids(t1.receipt_time)
    assert log.as_known_at(late, include_conflicted=True)
    assert a.observation_id == b.observation_id
