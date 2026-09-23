"""Kalshi adapter for the opportunity engine: captured markets and books → contracts.

Kalshi publishes a bid-only binary book: `yes_dollars` and `no_dollars` are lists of
[price, size] bids. A YES buyer crosses the best NO bid, so the executable YES price is
1 − (best NO bid) and the size offered there is that NO bid's size. The NO side mirrors
this. Only captured book levels are used. There is no midpoint, no last price, and no
depth walk beyond the best level.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from . import settlement
from .opportunity import Event, ExecutableQuote, Market, MarketStatus, Payoff

VENUE = "kalshi"
OPEN_STATUSES = ("active", "open")
CLOSED_STATUSES = ("closed", "settled", "determined", "finalized", "inactive")


def market_id(native_id: str) -> str:
    return f"{VENUE}:{native_id}"


def rules_sha256(raw: Mapping[str, Any]) -> str | None:
    primary, secondary = raw.get("rules_primary"), raw.get("rules_secondary")
    if not primary:
        return None
    return hashlib.sha256(f"{primary}\n{secondary or ''}".encode("utf-8")).hexdigest()


def rules_check(raw: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether the captured rules and strike fields agree well enough to settle deterministically.

    The frozen resolver checks rules-before-value. Probing it with an integer value
    therefore tells us whether the rules side is sound: an UNKNOWN outcome means the
    structured fields, the rules text or the named settlement source do not agree.
    """
    probe = settlement.resolve(raw, 0)
    if probe.outcome is settlement.Outcome.UNKNOWN:
        return False, probe.reason
    reading = settlement.read_rules(raw.get("rules_primary"))
    return True, f"{raw.get('strike_type')} rule; settlement source {reading.source.value}"


def _condition(raw: Mapping[str, Any]) -> str:
    kind, lo, hi = raw.get("strike_type"), raw.get("floor_strike"), raw.get("cap_strike")
    if kind == "between":
        return f"value in [{lo}, {hi}]"
    if kind == "greater":
        return f"value > {lo}"
    if kind == "less":
        return f"value < {hi}"
    return f"unrecognized strike_type {kind!r}"


def market_from_kalshi(raw: Mapping[str, Any], *, event_id_for_ticker: Mapping[str, str]) -> Market:
    """Build a `Market`. `event_id_for_ticker` maps Kalshi event tickers to normalized ids.

    A market whose event ticker is not in the map gets an `unmapped:` event id, so it can
    never match the event being evaluated (EVENT_MISMATCH, never a silent pass).
    """
    native = str(raw.get("ticker") or "")
    status_raw = str(raw.get("status") or "").lower()
    if status_raw in OPEN_STATUSES:
        status = MarketStatus.OPEN
    elif status_raw in CLOSED_STATUSES:
        status = MarketStatus.CLOSED
    else:
        status = MarketStatus.UNKNOWN
    resolved, detail = rules_check(raw)
    event_ticker = str(raw.get("event_ticker") or "")
    return Market(
        venue=VENUE,
        market_id=market_id(native),
        native_id=native,
        event_id=event_id_for_ticker.get(event_ticker, f"unmapped:{VENUE}:{event_ticker}"),
        outcome=str(raw.get("yes_sub_title") or _condition(raw)),
        payoff=Payoff(kind="binary", amount=Decimal("1"), yes_condition=_condition(raw)),
        rules_sha256=rules_sha256(raw),
        status=status,
        rules_resolved=resolved,
        rules_detail=detail,
    )


def _levels(raw: Any) -> list[tuple[Decimal, Decimal]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("book side is not a list")
    out = []
    for level in raw:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            raise ValueError(f"malformed level {level!r}")
        try:
            price, size = Decimal(str(level[0])), Decimal(str(level[1]))
        except InvalidOperation:
            raise ValueError(f"unparseable level {level!r}") from None
        if not price.is_finite() or not size.is_finite() or size < 0:
            raise ValueError(f"invalid level {level!r}")
        out.append((price, size))
    return out


def _best(levels: list[tuple[Decimal, Decimal]]) -> tuple[Decimal | None, Decimal | None]:
    """Highest bid and the total size resting at exactly that price."""
    live = [(p, s) for p, s in levels if s > 0]
    if not live:
        return None, None
    top = max(p for p, _ in live)
    return top, sum((s for p, s in live if p == top), Decimal(0))


def quotes_from_orderbook(
    native_id: str,
    payload: Mapping[str, Any] | None,
    *,
    received_at_utc: str | None,
    evidence_id: str | None,
) -> dict[str, ExecutableQuote]:
    """YES and NO executable quotes from one captured order-book payload.

    Returns {} when the payload has no book at all (the engine reports BOOK_MISSING). A
    malformed or crossed book yields quotes carrying `anomaly` (INVALID_PRICE).
    """
    book = payload.get("orderbook_fp") if isinstance(payload, Mapping) else None
    if not isinstance(book, Mapping):
        return {}
    mid = market_id(native_id)
    try:
        yes_bid, yes_bid_size = _best(_levels(book.get("yes_dollars")))
        no_bid, no_bid_size = _best(_levels(book.get("no_dollars")))
    except ValueError as exc:
        return {side: ExecutableQuote(VENUE, mid, side, None, None, None, received_at_utc, None, evidence_id,
                                      anomaly=f"malformed book: {exc}") for side in ("YES", "NO")}
    anomaly = None
    if yes_bid is not None and no_bid is not None and yes_bid + no_bid >= 1:
        anomaly = f"crossed book: yes bid {yes_bid} + no bid {no_bid} >= 1"
    return {
        "YES": ExecutableQuote(
            VENUE, mid, "YES", best_bid=yes_bid,
            best_ask=None if no_bid is None else Decimal(1) - no_bid,
            displayed_size=no_bid_size if no_bid is not None else Decimal(0),
            received_at_utc=received_at_utc, source_timestamp_utc=None, evidence_id=evidence_id, anomaly=anomaly),
        "NO": ExecutableQuote(
            VENUE, mid, "NO", best_bid=no_bid,
            best_ask=None if yes_bid is None else Decimal(1) - yes_bid,
            displayed_size=yes_bid_size if yes_bid is not None else Decimal(0),
            received_at_utc=received_at_utc, source_timestamp_utc=None, evidence_id=evidence_id, anomaly=anomaly),
    }


def check_event_identity(event: Event, raw_event: Mapping[str, Any] | None, expected_ticker: str) -> str | None:
    """None when the captured event payload is the expected Kalshi event, else the problem."""
    body = raw_event.get("event") if isinstance(raw_event, Mapping) else None
    if not isinstance(body, Mapping):
        return "captured event payload has no event object"
    if body.get("event_ticker") != expected_ticker:
        return f"captured event {body.get('event_ticker')!r} is not {expected_ticker!r} ({event.event_id})"
    return None
