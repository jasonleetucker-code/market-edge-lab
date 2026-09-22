"""Freshness semantics for point-in-time data.

Rules (see docs/DATA_PROVENANCE.md):

- Freshness is judged against an explicit maximum age, never assumed.
- A missing or unparseable timestamp is UNKNOWN, not FRESH.
- Combining inputs yields the worst state: one stale input makes the whole
  derived value stale.
- Anything that could feed an opportunity or trading decision must call
  `require_fresh`, which fails closed on STALE and UNKNOWN.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


# Higher is worse. UNKNOWN ranks worst because we cannot rule out staleness.
_SEVERITY = {Freshness.FRESH: 0, Freshness.STALE: 1, Freshness.UNKNOWN: 2}


class StaleDataError(RuntimeError):
    """Raised when decision-grade code receives data that is not provably fresh."""


def parse_utc(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive or unparseable values return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str):
        return None
    else:
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        # A timestamp without a zone is ambiguous; refuse to guess.
        return None
    return parsed.astimezone(timezone.utc)


def assess(
    observed_at: str | datetime | None,
    *,
    max_age: timedelta,
    now: datetime,
) -> Freshness:
    """Classify one observation timestamp against `max_age` at time `now`.

    A timestamp in the future beyond a small clock-skew tolerance is UNKNOWN:
    it indicates a clock or parsing problem, not exceptionally fresh data.
    """
    ts = parse_utc(observed_at)
    now_utc = parse_utc(now)
    if ts is None or now_utc is None:
        return Freshness.UNKNOWN
    age = now_utc - ts
    if age < -timedelta(minutes=5):
        return Freshness.UNKNOWN
    return Freshness.FRESH if age <= max_age else Freshness.STALE


def combine(*states: Freshness) -> Freshness:
    """Worst-of combination. No inputs is UNKNOWN, never FRESH."""
    if not states:
        return Freshness.UNKNOWN
    return max(states, key=lambda state: _SEVERITY[state])


def require_fresh(state: Freshness, *, what: str) -> None:
    """Fail closed unless `state` is FRESH."""
    if state is not Freshness.FRESH:
        raise StaleDataError(f"{what} is {state.value}; decision-grade use requires fresh data")
