"""Novig public exchange data: the daily anonymized CSVs at data.novig.com (read-only).

Documented at https://docs.novig.com/api-reference/trade-data (read 2026-09-23): static
files behind a CDN, no API and no authentication. Each trading day (midnight to midnight
Eastern) publishes shortly after midnight Eastern. A day that fails validation is
withheld, not published incomplete.

- `/reporting/trade-data/index.json`: `dates` (Trades) and `marketDates` (Markets). The two
  publish independently. `marketDates` is absent on older manifests and is read as an
  empty list.
- `<date>/trades.csv`: **rows are sides, not trades.** One TAKER row per trade plus a MAKER
  row per counterparty. The price one side paid is `cost / qty`, a probability. `qty` is in
  contracts paying $1 each and may be fractional. Fees are not included in `cost`.
- `<date>/markets.csv`: one row per listed market per day. Prices are **cents** with one
  decimal (`47.5` means 0.475). Empty OHLC means no trade that day, which is not zero.

**These files are end-of-day research data. They are never executable quotes.** Nothing here
builds an `ExecutableQuote`. The live NBX API (books, catalog, settlement, accounts) needs
OAuth client credentials that the owner must request, so it is NEEDS_ACCESS
(`venues.NOVIG`). An eventual authenticated integration plugs into the same venue and quote
interfaces. It must not be modelled on these files.

Columns may be added over time, so rows are read by header name, never by position.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Mapping

VENUE = "novig"
SOURCE_ID = "novig_public_data"
BASE_URL = "https://data.novig.com/reporting/trade-data"
PARSER_VERSION = "1"
PRICE_UNIT_TRADES = "probability (cost/qty), USD per contract; fees excluded"
PRICE_UNIT_MARKETS = "cents, one decimal (0.0-100.0)"
QUANTITY_UNIT = "contracts paying USD 1 each; may be fractional"

TRADE_COLUMNS = ("timestamp", "outcomeId", "marketId", "contractSeries", "league", "marketType", "tradeType",
                 "legs", "cost", "qty", "side")
MARKET_COLUMNS = ("date", "marketId", "reportTicker", "openInterest", "dailyVolume", "open", "high", "low",
                  "close", "status")
SIDES = frozenset({"TAKER", "MAKER"})
TRADE_TYPES = frozenset({"STRAIGHT", "COMBO"})
MARKET_STATUSES = frozenset({"active", "closed", "determined", "finalized"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NovigDataError(ValueError):
    pass


def index_url() -> str:
    return f"{BASE_URL}/index.json"


def file_url(date: str, name: str) -> str:
    if not _DATE.match(date) or name not in ("trades.csv", "markets.csv"):
        raise ValueError(f"invalid Novig data file {date}/{name}")
    return f"{BASE_URL}/{date}/{name}"


@dataclass(frozen=True)
class DataIndex:
    trade_dates: tuple[str, ...]
    market_dates: tuple[str, ...]
    market_dates_present: bool  # False: an older manifest without marketDates (read as empty)


def parse_index(payload: Any) -> DataIndex:
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("dates"), list):
        raise NovigDataError("index.json has no dates list")
    raw_market = payload.get("marketDates")
    if raw_market is not None and not isinstance(raw_market, list):
        raise NovigDataError("index.json marketDates is not a list")
    for d in [*payload["dates"], *(raw_market or [])]:
        if not isinstance(d, str) or not _DATE.match(d):
            raise NovigDataError(f"invalid date {d!r} in index.json")
    return DataIndex(tuple(payload["dates"]), tuple(raw_market or ()), raw_market is not None)


def _dec(value: str | None, *, field_name: str, row: int, allow_empty: bool = False) -> Decimal | None:
    if value is None or value == "":
        if allow_empty:
            return None  # missing is not zero
        raise NovigDataError(f"row {row}: {field_name} is empty")
    try:
        out = Decimal(value)
    except InvalidOperation:
        raise NovigDataError(f"row {row}: {field_name} {value!r} is not a number") from None
    if not out.is_finite():
        raise NovigDataError(f"row {row}: {field_name} {value!r} is not finite")
    return out


def _rows(text: str | bytes, required: tuple[str, ...]) -> Iterator[tuple[int, dict[str, str]]]:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in required if c not in (reader.fieldnames or ())]
    if missing:
        raise NovigDataError(f"missing columns {missing}")
    for n, row in enumerate(reader, start=2):
        yield n, row


@dataclass(frozen=True)
class TradeSide:
    """One side of one executed trade, as published. Research data, never a quote."""

    timestamp_utc: str
    outcome_id: str
    market_id: str
    contract_series: str
    league: str | None
    market_type: str | None
    trade_type: str
    legs: int
    cost_raw: str  # dollars staked by this side, exactly as published
    qty_raw: str  # contracts, exactly as published
    side: str  # TAKER | MAKER
    price: Decimal | None  # cost / qty, a probability; None when qty is zero
    executable: bool = False


def parse_trades(text: str | bytes) -> list[TradeSide]:
    out = []
    for n, row in _rows(text, TRADE_COLUMNS):
        side, trade_type = row["side"], row["tradeType"]
        if side not in SIDES:
            raise NovigDataError(f"row {n}: side {side!r} is not TAKER or MAKER")
        if trade_type not in TRADE_TYPES:
            raise NovigDataError(f"row {n}: tradeType {trade_type!r} is unknown")
        cost = _dec(row["cost"], field_name="cost", row=n)
        qty = _dec(row["qty"], field_name="qty", row=n)
        if cost < 0 or qty < 0:
            raise NovigDataError(f"row {n}: negative cost or qty")
        try:
            legs = int(row["legs"])
        except (TypeError, ValueError):
            raise NovigDataError(f"row {n}: legs {row['legs']!r} is not an integer") from None
        price = None if qty == 0 else cost / qty
        if price is not None and not 0 <= price <= 1:
            raise NovigDataError(f"row {n}: cost/qty {price} is not a probability")
        out.append(TradeSide(row["timestamp"], row["outcomeId"], row["marketId"], row["contractSeries"],
                             row["league"] or None, row["marketType"] or None, trade_type, legs,
                             row["cost"], row["qty"], side, price))
    return out


def trade_count(sides: list[TradeSide]) -> int:
    """Executed trades = TAKER rows (docs). Counting all rows would double-count."""
    return sum(1 for s in sides if s.side == "TAKER")


def taker_notional(sides: list[TradeSide]) -> Decimal:
    """Notional volume in dollars = sum of qty over TAKER rows (docs)."""
    return sum((Decimal(s.qty_raw) for s in sides if s.side == "TAKER"), Decimal(0))


@dataclass(frozen=True)
class MarketDay:
    """One market's end-of-day census row. Prices converted from cents; empty stays None."""

    date: str
    market_id: str
    report_ticker: str
    open_interest_raw: str
    daily_volume_raw: str
    open: Decimal | None  # probability (cents / 100); None = no trade that day
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    status: str
    executable: bool = False


def parse_markets(text: str | bytes) -> list[MarketDay]:
    out = []
    for n, row in _rows(text, MARKET_COLUMNS):
        if row["status"] not in MARKET_STATUSES:
            raise NovigDataError(f"row {n}: status {row['status']!r} is unknown")
        if not _DATE.match(row["date"] or ""):
            raise NovigDataError(f"row {n}: date {row['date']!r} is invalid")
        _dec(row["openInterest"], field_name="openInterest", row=n)
        _dec(row["dailyVolume"], field_name="dailyVolume", row=n)
        prices = {}
        for key in ("open", "high", "low", "close"):
            cents = _dec(row[key], field_name=key, row=n, allow_empty=True)
            if cents is not None and not 0 <= cents <= 100:
                raise NovigDataError(f"row {n}: {key} {cents} is outside 0-100 cents")
            prices[key] = None if cents is None else cents / 100
        out.append(MarketDay(row["date"], row["marketId"], row["reportTicker"], row["openInterest"],
                             row["dailyVolume"], prices["open"], prices["high"], prices["low"], prices["close"],
                             row["status"]))
    return out


# Live API capability requirements (documented, not implemented: NEEDS_ACCESS).
LIVE_API_REQUIREMENTS = (
    "OAuth 2.0 client credentials issued by Novig to the owner (docs.novig.com/api-reference/authentication)",
    "catalog, books and settlement via the authenticated NBX REST/WebSocket API; not the daily CSVs",
    "books are partially obfuscated per the docs (Get order book); quantity and price units to be verified",
    "fees: docs.novig.com/fees; no Novig fee schedule is verified here (fee_schedules: UNSUPPORTED)",
    "order endpoints exist upstream; order_write stays NEEDS_ACCESS and execution is never authorized",
)
