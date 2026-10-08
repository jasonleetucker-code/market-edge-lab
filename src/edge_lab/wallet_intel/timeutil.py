"""Aware-UTC time helpers. Naive datetimes are refused: their zone is unknown."""

from __future__ import annotations

from datetime import datetime, timezone


def require_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime, not {value!r}")
    return value


def utc_text(value: datetime) -> str:
    return require_aware(value, "time").astimezone(timezone.utc).isoformat()


def from_epoch_seconds(value: object, name: str) -> datetime:
    """An integer epoch-seconds field as aware UTC. bool, float and text are refused (strict)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer epoch seconds, not {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return datetime.fromtimestamp(value, tz=timezone.utc)
