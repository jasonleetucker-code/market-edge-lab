"""Explicit not-proven-standard Kalshi fee routing (PR C, coordinator decision 2026-09-30).

The captured non-standard list names KXNFLGAME and KXMVE exactly. Two things beyond it are FEE_UNSUPPORTED,
and nothing else changes:
- KXNHLGAME: not on the list, and no document shows it uses the general schedule;
- series starting with KXMVE: combinations, not proven standard.

Every other series routes exactly as on main: listed series are unsupported, and unlisted ones use the
general schedule. The oracle below is main's rule (exact list membership). It is checked over every listed
series, their common extensions, and the series an earlier prefix rule had flipped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from edge_lab import fee_schedules as fs
from edge_lab.position_policy import UnknownFeeModel, fee_model_for

AT = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
SUFFIXES = ("", "GAME", "SPREAD", "TOTAL", "GOAL", "CHAIR", "CORE", "NOW", "MVP", "WINS", "X", "Y", "2026")
FLIPPED_BEFORE = ("KXFEDCHAIR", "KXCPICORE", "KXGDPNOW", "KXNBAGAME", "KXNHLSPREAD", "KXNHLTOTAL", "KXNHLGOAL",
                  "KXMLBTOTAL", "KXNFLAFCEASTX", "KXU3MAX", "KXSBADS", "KXFEDRATE", "KXNCAAFGAMEX", "KXUCLWIN",
                  "KXWNBAMVP")
OTHERS = ("KXHIGHNY", "KXHIGHCHI", "KXHIGHLAX", "KXHIGHAUS", "KXHIGHMIA", "KXLOWTNYC", "KXRAINNYC", "DEMO",
          "KXTSAW", "KXAAAGASW", "KXBTCD", "KXETHD", "KXINX", "KXNASDAQ100")
EXPECTED_NEW = {"KXNHLGAME"}


def _universe() -> list[str]:
    names = {s + x for s in fs.KALSHI_NONSTANDARD_SERIES for x in SUFFIXES}
    return sorted(names | set(FLIPPED_BEFORE) | set(OTHERS) | {"KXMVECROSSCATEGORY", "KXMVENFLSINGLEGAME",
                                                               "KXMVESPORTSMULTIGAMEEXTENDED"})


def _main_rule_unsupported(series: str) -> bool:
    return series in fs.KALSHI_NONSTANDARD_SERIES


def test_every_series_routes_as_on_main_except_the_explicit_map():
    universe = _universe()
    assert len(universe) > 900
    changed = []
    for series in universe:
        now = isinstance(fs.schedule_for("kalshi", series, as_of=AT), fs.UnsupportedFeeSchedule)
        if now != _main_rule_unsupported(series):
            changed.append(series)
    assert all(s == "KXNHLGAME" or s.startswith("KXMVE") for s in changed), changed
    assert "KXNHLGAME" in changed and "KXMVECROSSCATEGORY" in changed
    for series in FLIPPED_BEFORE + OTHERS:
        assert fs.schedule_for("kalshi", series) is fs.KALSHI_QUADRATIC_TAKER_V1 or series in fs.KALSHI_NONSTANDARD_SERIES


@pytest.mark.parametrize("series", ["KXNHLGAME", "KXMVECROSSCATEGORY", "KXMVENFLSINGLEGAME"])
def test_the_explicit_map_is_unsupported_never_priced_and_says_not_proven_standard(series):
    schedule = fs.schedule_for("kalshi", series, as_of=AT)
    assert isinstance(schedule, fs.UnsupportedFeeSchedule) and schedule.status is fs.FeeScheduleStatus.UNSUPPORTED
    assert "not proven standard" in schedule.reason and "family" not in schedule.reason.split("(")[0]
    assert fs.not_proven_standard(series) is not None
    with pytest.raises(ValueError):
        schedule.taker_buy(10, Decimal("0.50"))
    assert not [r for r in fs.FEE_VERIFICATIONS if series in r.scope]


def test_nhl_game_is_consistent_with_nfl_game():
    assert type(fs.schedule_for("kalshi", "KXNFLGAME")) is type(fs.schedule_for("kalshi", "KXNHLGAME"))
    assert isinstance(fee_model_for("kalshi", "KXNHLGAME-26OCT04BOSTOR-BOS", AT), UnknownFeeModel)


def test_listed_series_keep_their_exact_reason_and_the_verified_series_is_unchanged():
    assert fs.schedule_for("kalshi", "KXNFLGAME").reason == "series has a non-standard Kalshi fee schedule (PDF pp.6-11)"
    assert fs.not_proven_standard("KXNFLGAME") is None and fs.not_proven_standard("KXMVE") is None
    ny = fs.schedule_for("kalshi", "KXHIGHNY", as_of=AT)
    assert ny is fs.KALSHI_QUADRATIC_TAKER_V1 and fs.not_proven_standard("KXHIGHNY") is None
    assert fs.verification_at(ny, AT, "KXHIGHNY-26SEP30-T70").claim_basis is not fs.ClaimBasis.NONE
    assert ny.taker_buy(100, Decimal("0.30")).fee == Decimal("1.47")
    assert fs.not_proven_standard(None) is None and isinstance(fs.schedule_for("kalshi", None),
                                                               fs.UnsupportedFeeSchedule)
