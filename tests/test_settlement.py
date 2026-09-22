"""Deterministic settlement resolver: boundaries, semantics, fail-closed cases."""

from decimal import Decimal

import pytest

from edge_lab.settlement import Outcome, RulesSource, read_rules, resolve

TWC = "If the maximum temperature recorded at New York City (CLINYC) for Sep 21, 2026, is {cond} fahrenheit according to The Weather Company, then the market resolves to Yes."
NWS = "If the highest temperature recorded in Central Park, New York for August 05, 2026 as reported by the National Weather Service's Climatological Report (Daily), is {cond}, then the market resolves to Yes."


def greater(x, rules=TWC):
    return {"strike_type": "greater", "floor_strike": x, "cap_strike": None, "rules_primary": rules.format(cond=f"greater than {x}°")}


def less(x, rules=TWC):
    return {"strike_type": "less", "floor_strike": None, "cap_strike": x, "rules_primary": rules.format(cond=f"less than {x}°")}


def between(lo, hi, rules=TWC):
    return {"strike_type": "between", "floor_strike": lo, "cap_strike": hi, "rules_primary": rules.format(cond=f"between {lo}-{hi}°")}


@pytest.mark.parametrize("value, expected", [(73, "no"), (74, "yes"), (72, "no"), ("74.00", "yes")])
def test_greater_is_strict(value, expected):
    assert resolve(greater(73), value).outcome.value == expected


@pytest.mark.parametrize("value, expected", [(80, "no"), (79, "yes"), ("80.00", "no")])
def test_less_is_strict(value, expected):
    assert resolve(less(80, NWS), value).outcome.value == expected


@pytest.mark.parametrize("value, expected", [(79, "no"), (80, "yes"), (81, "yes"), (82, "no")])
def test_between_is_inclusive_at_both_ends(value, expected):
    assert resolve(between(80, 81, NWS), value).outcome.value == expected


def test_brackets_partition_integers_exactly_once():
    brackets = [less(80), between(80, 81), between(82, 83), between(84, 85), greater(85)]
    for value in range(60, 100):
        yes = [b for b in brackets if resolve(b, value).outcome is Outcome.YES]
        assert len(yes) == 1, value


@pytest.mark.parametrize("value", [None, "", "MM", "nan", "Infinity", True])
def test_missing_or_bad_value_is_unknown_never_no(value):
    assert resolve(greater(73), value).outcome is Outcome.UNKNOWN


@pytest.mark.parametrize("value", ["73.5", 81.5, Decimal("79.9")])
def test_fractional_values_fail_closed(value):
    # Brackets have 1-degree gaps (80-81, 82-83); fractional semantics are unverified.
    assert resolve(between(80, 81), value).outcome is Outcome.UNKNOWN
    assert resolve(greater(73), value).outcome is Outcome.UNKNOWN


def test_fields_contradicting_rules_text_are_unknown():
    market = greater(73)
    market["floor_strike"] = 74
    assert resolve(market, 90).outcome is Outcome.UNKNOWN
    market = between(80, 81)
    market["strike_type"] = "greater"
    assert resolve(market, 80).outcome is Outcome.UNKNOWN


def test_unverified_source_is_unknown():
    market = greater(73)
    market["rules_primary"] = market["rules_primary"].replace("The Weather Company", "AccuWeather")
    assert resolve(market, 90).outcome is Outcome.UNKNOWN


def test_missing_strikes_are_unknown():
    market = between(80, 81)
    market["cap_strike"] = None
    assert resolve(market, 80).outcome is Outcome.UNKNOWN


def test_read_rules_recognizes_all_captured_wordings():
    older = "If the highest temperature recorded in Central Park, New York for March 04, 2025 as reported by the National Weather Service's Daily Climate Report, is between 53-54°, then the market resolves to Yes."
    assert read_rules(older).source is RulesSource.NWS_CLI
    assert read_rules(older).comparison == "between"
    assert read_rules(NWS.format(cond="greater than 87°")).low == Decimal("87")
    assert read_rules(TWC.format(cond="less than 85°")).source is RulesSource.WEATHER_COMPANY


def test_rules_hash_groups_brackets_and_days_sharing_one_wording():
    from edge_lab.settlement_audit import rules_hash

    a = greater(73)
    b = between(80, 81)
    c = dict(greater(90), rules_primary=greater(90)["rules_primary"].replace("Sep 21, 2026", "Sep 22, 2026"))
    assert rules_hash(a) == rules_hash(b) == rules_hash(c)
    changed = dict(a, rules_secondary="new wording")
    assert rules_hash(changed) != rules_hash(a)


def test_duplicate_market_records_are_chosen_deterministically():
    from datetime import date

    from edge_lab.settlement_audit import audit

    base = dict(between(80, 81), ticker="KXHIGHNY-26SEP21-B80.5", event_ticker="KXHIGHNY-26SEP21", result="yes")
    with_value = dict(base, expiration_value="80.00", updated_time="2026-09-22T10:00:00Z")
    without = dict(base, expiration_value="", updated_time="2026-09-23T10:00:00Z")
    for order in ([with_value, without], [without, with_value]):
        (summary,), _ = audit(order, [], start=date(2026, 9, 21), end=date(2026, 9, 21))
        assert summary.kalshi_expiration_value == "80.00"


def test_missing_strike_type_and_unread_comparison_is_unknown_not_a_crash():
    # Early HIGHNY rules with no source/comparison reading and no strike_type (e.g. 22APR29).
    market = {"strike_type": None, "floor_strike": None, "cap_strike": None,
              "rules_primary": "If the highest temperature recorded in Central Park is 64 or above"}
    assert resolve(market, 70).outcome is Outcome.UNKNOWN
