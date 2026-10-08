"""W2: exactness, observations, the append-only log, conflicts, corrections and position effects."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel.events import (DIRECTIONAL, Action, ChainFinality, Correction, CorrectionKind,
                                          ObservationLog, PositionEffect, assign_occurrences, classify_effects)
from edge_lab.wallet_intel.exact import Basis, ExactValueError, Labeled, exact_decimal, floor_to_step


@pytest.mark.parametrize("bad", [0.1, 1.0, True, float("nan"), "nan", "1e400", "abc", None, Decimal("Infinity")])
def test_exact_decimal_refuses_floats_bools_and_non_finite(bad):
    with pytest.raises(ExactValueError):
        exact_decimal(bad, name="x")


def test_exact_decimal_accepts_exact_inputs_and_floors_only_on_request():
    assert exact_decimal("0.10", name="x") == D("0.1") and exact_decimal(3, name="x") == 3
    assert floor_to_step(D("7.99"), D(1)) == 7 and floor_to_step(D("0.129"), D("0.01")) == D("0.12")


def test_labeled_unknown_never_carries_a_number():
    with pytest.raises(ValueError):
        Labeled(D(0), Basis.UNKNOWN)
    with pytest.raises(ValueError):
        Labeled(None, Basis.OBSERVED)
    assert not Labeled.unknown("x").known


def test_basis_values_match_research_economics():
    from edge_lab.research_economics import Basis as CanonicalBasis
    assert [b.value for b in Basis] == [b.value for b in CanonicalBasis]


def test_only_trades_are_directional():
    assert DIRECTIONAL == {Action.TRADE_BUY, Action.TRADE_SELL}
    assert len(Action) == 10


def test_a_trade_needs_instrument_and_quantity_and_a_fee_label():
    o = obs(acct(1), Action.TRADE_BUY)
    with pytest.raises(ValueError):
        replace(o, instrument_id=None)
    with pytest.raises(ValueError):
        replace(o, fee=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(o, source_time=o.source_time.replace(tzinfo=None))


def test_reingest_keeps_the_earliest_receipt_for_point_in_time_use():
    o = obs(acct(1), Action.TRADE_BUY, when=at(0), receipt_delay=timedelta(minutes=10))
    log = ObservationLog()
    log.ingest([o])
    log.ingest([replace(o, receipt_time=at(2))])  # a later copy arrived earlier by another path
    assert log.first_receipt(o.observation_id) == at(2)
    assert log.as_known_at(at(1)) == () and len(log.as_known_at(at(2))) == 1


def test_same_source_event_id_with_different_content_is_a_conflict_not_an_update():
    o = obs(acct(1), Action.TRADE_BUY, event_id="fill-77", qty=10)
    log = ObservationLog()
    log.ingest([o])
    counts = log.ingest([replace(o, native_quantity=D(11), received=o.received)])
    assert counts["conflicts"] == 1 and log.conflicts[0].kind == "SAME_IDENTITY_DIFFERENT_CONTENT"
    assert log.as_known_at(at(days=1)) == ()  # reported, not resolved
    assert len(log.as_known_at(at(days=1), include_conflicted=True)) == 1


def test_one_transaction_with_two_block_times_is_a_conflict():
    a = obs(acct(1), Action.TRADE_BUY, tx="0xsame", when=at(0))
    b = obs(acct(1), Action.TRADE_BUY, tx="0xsame", when=at(5), qty=3)
    log = ObservationLog()
    log.ingest([a, b])
    assert [c.kind for c in log.conflicts] == ["TRANSACTION_TIME_MISMATCH"]
    assert log.as_known_at(at(days=1)) == ()


def test_sub_index_gives_fill_identity_within_a_transaction():
    a = obs(acct(1), Action.TRADE_BUY, tx="0xt", sub_index=0)
    b = replace(a, sub_index=1)
    assert a.observation_id != b.observation_id
    assert assign_occurrences([a, b]) == (a, b)


def test_corrections_are_appended_and_replayable_by_knowledge_time():
    o = obs(acct(1), Action.TRADE_BUY, when=at(0), qty=10)
    fixed = replace(o, native_quantity=D(12), parser_version="test-2")
    log = ObservationLog()
    log.ingest([o])
    log.append_correction(Correction("c1", o.observation_id, CorrectionKind.SUPERSEDED, at(10), "source fixed qty",
                                     replacement=fixed))
    log.append_correction(Correction("c2", o.observation_id, CorrectionKind.FINALITY_CHANGED, at(20), "confirmed",
                                     new_finality=ChainFinality.FINAL))
    assert log.as_known_at(at(5))[0].native_quantity == 10
    assert log.as_known_at(at(15))[0].native_quantity == 12
    assert len(log.corrections) == 2
    with pytest.raises(ValueError):
        log.append_correction(Correction("c1", o.observation_id, CorrectionKind.RETRACTED, at(30), "dup id"))
    with pytest.raises(ValueError):
        Correction("c3", o.observation_id, CorrectionKind.SUPERSEDED, at(30), "no replacement")


def test_position_effects_open_increase_reduce_close_flip():
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0)),
            obs(a, Action.TRADE_BUY, "m1-yes", 5, "0.4", at(1)),
            obs(a, Action.TRADE_SELL, "m1-yes", 3, "0.5", at(2)),
            obs(a, Action.TRADE_BUY, "m1-no", 20, "0.5", at(3)),  # net yes 12 -> net no 8: a flip
            obs(a, Action.TRADE_SELL, "m1-no", 8, "0.5", at(4)),  # back to 12 yes / 12 no: flat
            obs(a, Action.REWARD, "m1-yes", 1, "1", at(5))]
    effects = [r.effect for r in classify_effects(rows, history_complete=True)]
    assert effects == [PositionEffect.OPEN, PositionEffect.INCREASE, PositionEffect.REDUCE, PositionEffect.FLIP,
                       PositionEffect.CLOSE, PositionEffect.NOT_DIRECTIONAL]


def test_position_effects_are_unknown_without_complete_history_or_itemized_legs():
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.4", at(0))]
    assert classify_effects(rows, history_complete=False)[0].effect is PositionEffect.UNKNOWN
    oversell = [obs(a, Action.TRADE_SELL, "m1-yes", 10, "0.4", at(0)), obs(a, Action.TRADE_BUY, "m1-yes", 1, "0.4", at(1))]
    assert [r.effect for r in classify_effects(oversell, history_complete=True)] == [PositionEffect.UNKNOWN] * 2
    unitemized = [obs(a, Action.MERGE, "m1-yes", 5, "0", at(0), ambiguities=("LEGS_NOT_ITEMIZED",)),
                  obs(a, Action.TRADE_BUY, "m1-yes", 1, "0.4", at(1))]
    assert classify_effects(unitemized, history_complete=True)[1].effect is PositionEffect.UNKNOWN


def test_split_then_merge_is_not_directional_and_keeps_position_known():
    a = acct(1)
    rows = [obs(a, Action.SPLIT, "m1-yes", 10, "0", at(0)), obs(a, Action.TRADE_SELL, "m1-no", 10, "0.3", at(1))]
    effects = [r.effect for r in classify_effects(rows, history_complete=True)]
    assert effects == [PositionEffect.NOT_DIRECTIONAL, PositionEffect.OPEN]  # selling NO leaves net YES
