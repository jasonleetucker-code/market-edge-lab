"""Kalshi adapter for the opportunity engine: captured markets and books → contracts.

Kalshi publishes a bid-only binary book: `yes_dollars` and `no_dollars` are lists of
[price, size] bids. A YES buyer crosses the best NO bid, so the executable YES price is
1 − (best NO bid) and the size offered there is that NO bid's size. The NO side mirrors
this. Only captured book levels are used. There is no midpoint and no last price in any quote or
ladder. `market_activity` (Track B, #184) reads the record's last trade price, volume and open
interest as separate, non-executable context (`MarketActivity.fillable` is always False).
`quotes_from_orderbook` gives the best level only (the frozen EXP-001 path);
`ladders_from_orderbook` gives every captured level for depth walks
(`opportunity.walk_ladder`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence

from . import settlement
from .opportunity import (
    DepthLadder, DepthLevel, Event, ExecutableQuote, Market, MarketStatus, MarketTiming, Payoff, PriceGrid,
    PriceRange,
)

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


def _text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return str(value) if value not in (None, "") else None


def timing_from_kalshi(raw: Mapping[str, Any], *, source: str | None = None) -> MarketTiming:
    """The timing fields Kalshi publishes for a market, unchanged. Kalshi documents
    `expected_expiration_time` as when the outcome is expected to be known and
    `latest_expiration_time` as the latest possible expiration (docs.kalshi.com Market
    Lifecycle). `expiration_time` is deprecated and ignored. Missing fields stay None."""
    timer = raw.get("settlement_timer_seconds")
    try:
        timer = int(timer) if timer is not None else None
    except (TypeError, ValueError):
        timer = None
    return MarketTiming(
        event_end_utc=_text(raw, "occurrence_datetime"),
        close_time_utc=_text(raw, "close_time"),
        expected_resolution_utc=_text(raw, "expected_expiration_time"),
        latest_resolution_utc=_text(raw, "latest_expiration_time"),
        settlement_timer_seconds=timer if timer is None or timer >= 0 else None,
        lifecycle_status=_text(raw, "status"),
        source=source,
    )


def price_grid_from_kalshi(raw: Mapping[str, Any]) -> PriceGrid | None:
    """The market's tick grid from Kalshi's `price_ranges` ([{start, end, step}] in dollars).

    None when the field is absent or malformed: an unknown grid is never assumed to be the
    cent grid."""
    ranges = raw.get("price_ranges")
    if not isinstance(ranges, list) or not ranges:
        return None
    try:
        parsed = tuple(PriceRange(Decimal(str(r["start"])), Decimal(str(r["end"])), Decimal(str(r["step"])))
                       for r in ranges)
        return PriceGrid(parsed, source=f"kalshi price_ranges ({raw.get('price_level_structure') or 'unnamed'})")
    except (KeyError, TypeError, InvalidOperation, ValueError):
        return None


def market_from_kalshi(raw: Mapping[str, Any], *, event_id_for_ticker: Mapping[str, str],
                       timing_source: str | None = None) -> Market:
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
        timing=timing_from_kalshi(raw, source=timing_source),
        price_grid=price_grid_from_kalshi(raw),
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


def _ask_ladder(opposite_bids: list[tuple[Decimal, Decimal]]) -> tuple[DepthLevel, ...]:
    """Asks for one side from the other side's bids: price 1 − bid, sizes summed per price."""
    sizes: dict[Decimal, Decimal] = {}
    for price, size in opposite_bids:
        if size > 0:
            ask = Decimal(1) - price
            sizes[ask] = sizes.get(ask, Decimal(0)) + size
    return tuple(DepthLevel(p, sizes[p]) for p in sorted(sizes))


def ladders_from_orderbook(
    native_id: str,
    payload: Mapping[str, Any] | None,
    *,
    received_at_utc: str | None,
    evidence_id: str | None,
    depth_limit: int | None,
) -> dict[str, DepthLadder]:
    """YES and NO ask ladders from one captured order-book payload.

    When a ladder is valid, its top level is exactly what `quotes_from_orderbook` reports.
    Validation is stricter than the top-of-book path: one invalid level anywhere (for
    example a bid at 0 or off the price grid) makes the whole ladder INVALID_BOOK in
    `walk_ladder`, failing closed. `depth_limit` is the `depth` the book was requested
    with; callers pass the value recorded in the snapshot's request URL
    (`forward.BOOK_DEPTH` today), or None if the request was not depth-limited. A side
    whose opposite bids reached that limit is marked truncated. Returns {} when there is no
    book; malformed or crossed books carry `anomaly`.
    """
    book = payload.get("orderbook_fp") if isinstance(payload, Mapping) else None
    if not isinstance(book, Mapping):
        return {}
    mid = market_id(native_id)

    def ladder(side: str, asks: tuple[DepthLevel, ...], truncated: bool, anomaly: str | None) -> DepthLadder:
        return DepthLadder(VENUE, mid, side, asks, truncated, received_at_utc, None, evidence_id, anomaly)

    try:
        yes_bids, no_bids = _levels(book.get("yes_dollars")), _levels(book.get("no_dollars"))
    except ValueError as exc:
        return {side: ladder(side, (), False, f"malformed book: {exc}") for side in ("YES", "NO")}
    yes_bid, _ = _best(yes_bids)
    no_bid, _ = _best(no_bids)
    anomaly = None
    if yes_bid is not None and no_bid is not None and yes_bid + no_bid >= 1:
        anomaly = f"crossed book: yes bid {yes_bid} + no bid {no_bid} >= 1"
    return {
        "YES": ladder("YES", _ask_ladder(no_bids), depth_limit is not None and len(no_bids) >= depth_limit, anomaly),
        "NO": ladder("NO", _ask_ladder(yes_bids), depth_limit is not None and len(yes_bids) >= depth_limit, anomaly),
    }


def check_event_identity(event: Event, raw_event: Mapping[str, Any] | None, expected_ticker: str) -> str | None:
    """None when the captured event payload is the expected Kalshi event, else the problem."""
    body = raw_event.get("event") if isinstance(raw_event, Mapping) else None
    if not isinstance(body, Mapping):
        return "captured event payload has no event object"
    if body.get("event_ticker") != expected_ticker:
        return f"captured event {body.get('event_ticker')!r} is not {expected_ticker!r} ({event.event_id})"
    return None


# --------------------------------------------------------------------------- market activity (Track B, #184)
#
# Kalshi's market record carries activity fields beside its quote and settlement fields (docs.kalshi.com Get
# Market, OpenAPI 3.31.0, captured in experiments/EXP-002-nfl-consensus-vs-event-market/fee_evidence/
# docs_api-reference_market_get-market.md):
# - `last_price_dollars`: "Price for the last traded YES contract" (FixedPointDollars string);
# - `volume_fp`, `volume_24h_fp`: market volume and 24h volume in contracts (FixedPointCount, 2 decimals);
# - `open_interest_fp`: "the number of contracts bought on this market disconsidering netting".
# `market_activity` lifts these, and nothing else. A last trade price is context, never an executable price:
# the record says so (`fillable` False) and it is never an `ExecutableQuote` or `DepthLadder`.
# Settled and post-close fields (`payoff_constraints.PROHIBITED_MARKET_FIELDS`) are never read. The last
# trade price is itself a label proxy once trading has closed, so it is withheld unless the market is open
# and the record was received before its close time (an unknown status or time withholds it: fail closed).

ACTIVITY_VERSION = "kalshi-market-activity-v1"
ACTIVITY_PRICE_KIND = "LAST_TRADE_NOT_EXECUTABLE"
ACTIVITY_FIELDS = (("last_trade_price", "last_price_dollars"), ("volume", "volume_fp"),
                   ("volume_24h", "volume_24h_fp"), ("open_interest", "open_interest_fp"))


class ActivityState(str, Enum):
    OBSERVED = "OBSERVED"
    MISSING = "MISSING"  # absent or empty: unknown, never zero
    MALFORMED = "MALFORMED"  # not a finite fixed-point number, or negative
    NOT_A_TRADE_PRICE = "NOT_A_TRADE_PRICE"  # outside (0, 1): no trade can print there (e.g. "0.0000" with no trade)
    WITHHELD_PROHIBITED = "WITHHELD_PROHIBITED"  # the caller's protocol prohibits the field
    WITHHELD_POST_CLOSE = "WITHHELD_POST_CLOSE"  # a last trade at or after close (or of unknown timing)


@dataclass(frozen=True)
class ActivityField:
    name: str
    source_field: str
    value: Decimal | None
    state: str


@dataclass(frozen=True)
class MarketActivity:
    version: str
    ticker: str | None
    event_ticker: str | None
    status: str | None
    received_at_utc: str | None
    close_time_utc: str | None
    pre_close: bool | None  # open status and received before close; None when either is unknown
    last_trade_price: ActivityField
    volume: ActivityField
    volume_24h: ActivityField
    open_interest: ActivityField
    fields_never_read: tuple[str, ...]
    payload_sha256: str  # of the record with every never-read field removed
    price_kind: str = ACTIVITY_PRICE_KIND
    fillable: bool = False  # a last trade price is never fillable

    def to_dict(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, ActivityField):
                return {k: plain(getattr(v, k)) for k in ("name", "source_field", "value", "state")}
            if isinstance(v, tuple):
                return [plain(x) for x in v]
            return v
        return {k: plain(getattr(self, k)) for k in self.__dataclass_fields__}


def _activity_number(raw: Any, *, price: bool) -> tuple[Decimal | None, ActivityState]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, ActivityState.MISSING
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        return None, ActivityState.MALFORMED  # documented as fixed-point strings; a float is never trusted
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        return None, ActivityState.MALFORMED
    if not value.is_finite() or value < 0:
        return None, ActivityState.MALFORMED
    if price and not Decimal(0) < value < Decimal(1):
        return None, ActivityState.NOT_A_TRADE_PRICE
    return value, ActivityState.OBSERVED


def market_activity(raw: Mapping[str, Any], *, received_at_utc: str | None,
                    prohibited_fields: Sequence[str]) -> MarketActivity:
    """Last trade price, volume, 24h volume and open interest from one Kalshi market record.

    `prohibited_fields` is the consuming protocol's list (pass `()` only when the protocol has none). The
    settled fields are dropped whatever it says. Pure: nothing is fetched."""
    from .freshness import parse_utc
    from .payoff_constraints import PROHIBITED_MARKET_FIELDS
    from .provenance import canonical_json, sha256_hex

    caller = {str(f) for f in prohibited_fields}
    sources = {source for _, source in ACTIVITY_FIELDS}
    never_read = (set(PROHIBITED_MARKET_FIELDS) | caller) - sources
    clean = {k: v for k, v in raw.items() if k not in never_read}
    status = _text(clean, "status")
    close = _text(clean, "close_time")
    received, closes = parse_utc(received_at_utc), parse_utc(close)
    if status is None or received is None or closes is None:
        pre_close = None
    else:
        pre_close = status.lower() in OPEN_STATUSES and received < closes
    out: dict[str, ActivityField] = {}
    for name, source in ACTIVITY_FIELDS:
        if source in caller:
            out[name] = ActivityField(name, source, None, ActivityState.WITHHELD_PROHIBITED.value)
            continue
        if name == "last_trade_price" and pre_close is not True:
            out[name] = ActivityField(name, source, None, ActivityState.WITHHELD_POST_CLOSE.value)
            continue
        value, state = _activity_number(clean.get(source), price=name == "last_trade_price")
        out[name] = ActivityField(name, source, value, state.value)
    hashed = {k: v for k, v in clean.items() if k not in caller}
    return MarketActivity(ACTIVITY_VERSION, _text(clean, "ticker"), _text(clean, "event_ticker"), status,
                          received_at_utc, close, pre_close, out["last_trade_price"], out["volume"],
                          out["volume_24h"], out["open_interest"], tuple(sorted(never_read | (caller & sources))),
                          sha256_hex(canonical_json(hashed)))
