"""Kalshi series that extend a listed non-standard series are FEE_UNSUPPORTED (PR C, 2026-09-30).

The captured non-standard list names KXNFLGAME, KXNHL and KXMVE exactly. KXNHLGAME and the combination
series (KXMVECROSSCATEGORY and kin) are not listed, and none has a verified schedule, so they are never
priced by a guessed general schedule. KXHIGHNY (EXP-001, verified) and other unlisted families keep
their routing byte for byte.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from edge_lab import fee_schedules as fs
from edge_lab.position_policy import UnknownFeeModel, fee_model_for

AT = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("series,family", [("KXNHLGAME", "KXNHL"), ("KXMVECROSSCATEGORY", "KXMVE"),
                                           ("KXMVENFLSINGLEGAME", "KXMVE"), ("KXNBAGAME", "KXNBA")])
def test_a_sibling_of_a_listed_nonstandard_series_is_unsupported_and_never_priced(series, family):
    schedule = fs.schedule_for("kalshi", series, as_of=AT)
    assert isinstance(schedule, fs.UnsupportedFeeSchedule) and schedule.status is fs.FeeScheduleStatus.UNSUPPORTED
    assert fs.nonstandard_family(series) == family and family in schedule.reason
    with pytest.raises(ValueError):
        schedule.taker_buy(10, Decimal("0.50"))
    assert not [r for r in fs.FEE_VERIFICATIONS if series in r.scope]


def test_nhl_game_is_now_consistent_with_nfl_game():
    nfl, nhl = fs.schedule_for("kalshi", "KXNFLGAME"), fs.schedule_for("kalshi", "KXNHLGAME")
    assert type(nfl) is type(nhl) is fs.UnsupportedFeeSchedule
    assert isinstance(fee_model_for("kalshi", "KXNHLGAME-26OCT04BOSTOR-BOS", AT), UnknownFeeModel)


def test_listed_series_keep_their_exact_reason_and_the_verified_series_is_unchanged():
    assert fs.schedule_for("kalshi", "KXNFLGAME").reason == "series has a non-standard Kalshi fee schedule (PDF pp.6-11)"
    assert fs.nonstandard_family("KXNFLGAME") is None  # exact members use the exact path
    ny = fs.schedule_for("kalshi", "KXHIGHNY", as_of=AT)
    assert ny is fs.KALSHI_QUADRATIC_TAKER_V1 and fs.nonstandard_family("KXHIGHNY") is None
    assert fs.verification_at(ny, AT, "KXHIGHNY-26SEP30-T70").claim_basis is not fs.ClaimBasis.NONE
    assert ny.taker_buy(100, Decimal("0.30")).fee == Decimal("1.47")


@pytest.mark.parametrize("series", ["KXHIGHCHI", "KXHIGHLAX", "KXLOWTNYC", "DEMO"])
def test_unlisted_families_are_unaffected(series):
    assert fs.nonstandard_family(series) is None
    assert fs.schedule_for("kalshi", series) is fs.KALSHI_QUADRATIC_TAKER_V1


def test_the_longest_listed_prefix_names_the_family_and_missing_scope_is_unknown():
    assert fs.nonstandard_family("KXNFLAFCEASTX") == "KXNFLAFCEAST"
    assert fs.nonstandard_family(None) is None and fs.nonstandard_family("") is None
    assert isinstance(fs.schedule_for("kalshi", None), fs.UnsupportedFeeSchedule)
