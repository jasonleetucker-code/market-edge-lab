"""Deterministic settlement resolution for KXHIGHNY-style temperature brackets.

Given a bracket definition and a verified underlying value, return YES, NO or
UNKNOWN. The resolver never guesses. It returns UNKNOWN when:

- the value is missing or cannot be parsed;
- the value is not a whole number (the reports we have verified give whole
  degrees; fractional semantics against 1-degree bracket gaps are unverified);
- the bracket fields are incomplete or contradict the market's rules text;
- the rules text names a source or comparison we have not verified.

Comparison semantics come from primary contract evidence (docs/SETTLEMENT.md):

- "greater" (rules: "greater than X")  -> YES iff value >  floor_strike
- "less"    (rules: "less than X")     -> YES iff value <  cap_strike
- "between" (rules: "between X-Y")     -> YES iff floor <= value <= cap (inclusive)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

RESOLVER_VERSION = "1"


class Outcome(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class RulesSource(str, Enum):
    NWS_CLI = "nws_climatological_report_daily"
    WEATHER_COMPANY = "the_weather_company"
    UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    reason: str


@dataclass(frozen=True)
class RulesReading:
    source: RulesSource
    comparison: str | None  # "greater" | "less" | "between" | None
    low: Decimal | None
    high: Decimal | None


_NUM = r"(-?\d+(?:\.\d+)?)"
_COMPARISONS = (
    ("between", re.compile(rf"\bbetween {_NUM}\s*°?\s*(?:-|to|and)\s*{_NUM}°", re.I)),
    ("greater", re.compile(rf"\bgreater than {_NUM}°", re.I)),
    ("less", re.compile(rf"\bless than {_NUM}°", re.I)),
)


def read_rules(rules_primary: str | None) -> RulesReading:
    """Deterministically read the source and comparison from `rules_primary`."""
    text = rules_primary or ""
    if "Weather Company" in text:
        source = RulesSource.WEATHER_COMPANY
    elif "National Weather Service" in text and (
        "Climatological Report (Daily)" in text or "Daily Climate Report" in text
    ):
        source = RulesSource.NWS_CLI
    else:
        source = RulesSource.UNRECOGNIZED
    for name, pattern in _COMPARISONS:
        match = pattern.search(text)
        if match:
            numbers = [Decimal(g) for g in match.groups()]
            if name == "between":
                return RulesReading(source, name, numbers[0], numbers[1])
            if name == "greater":
                return RulesReading(source, name, numbers[0], None)
            return RulesReading(source, name, None, numbers[0])
    return RulesReading(source, None, None, None)


def parse_value(raw: Any) -> Decimal | None:
    """Parse an underlying value. Missing or malformed input is None, never 0."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _strike(raw: Any) -> Decimal | None:
    return parse_value(raw)


def resolve(market: Mapping[str, Any], value: Any) -> Resolution:
    """Resolve one bracket against a verified underlying value.

    `market` needs `strike_type`, `floor_strike`/`cap_strike` and `rules_primary`
    (the Kalshi market fields). The bracket fields and the rules text must agree.
    """
    reading = read_rules(market.get("rules_primary"))
    if reading.source is RulesSource.UNRECOGNIZED:
        return Resolution(Outcome.UNKNOWN, "rules name an unverified settlement source")

    strike_type = market.get("strike_type")
    floor = _strike(market.get("floor_strike"))
    cap = _strike(market.get("cap_strike"))

    if strike_type not in ("greater", "less", "between"):
        return Resolution(Outcome.UNKNOWN, f"unrecognized strike_type {strike_type!r}")
    if strike_type != reading.comparison:
        return Resolution(
            Outcome.UNKNOWN,
            f"strike_type {strike_type!r} contradicts rules comparison {reading.comparison!r}",
        )
    if strike_type == "greater" and (floor is None or floor != reading.low):
        return Resolution(Outcome.UNKNOWN, "floor_strike missing or contradicts rules text")
    if strike_type == "less" and (cap is None or cap != reading.high):
        return Resolution(Outcome.UNKNOWN, "cap_strike missing or contradicts rules text")
    if strike_type == "between" and (
        floor is None or cap is None or floor != reading.low or cap != reading.high or floor > cap
    ):
        return Resolution(Outcome.UNKNOWN, "between strikes missing or contradict rules text")

    v = parse_value(value)
    if v is None:
        return Resolution(Outcome.UNKNOWN, "underlying value missing or unparseable")
    if v != v.to_integral_value():
        return Resolution(Outcome.UNKNOWN, "non-integer value: precision semantics unverified")

    if strike_type == "greater":
        hit = v > floor
    elif strike_type == "less":
        hit = v < cap
    else:
        hit = floor <= v <= cap
    return Resolution(Outcome.YES if hit else Outcome.NO, f"{strike_type} rule applied to {v}")


def kalshi_result(market: Mapping[str, Any]) -> Outcome:
    """Kalshi's recorded result as an Outcome (anything else, e.g. void, is UNKNOWN)."""
    result = market.get("result")
    if result == "yes":
        return Outcome.YES
    if result == "no":
        return Outcome.NO
    return Outcome.UNKNOWN
