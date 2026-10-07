"""Strict parser for Polymarket Data API v2 payloads (W2, ADR 0045). Fixture-fed: no network.

The owner's choice of 2026-10-07 limits this lane to synthetic fixtures and the v2 documentation.
Nothing here fetches anything. `walk` takes a caller-supplied `fetch(cursor)` that returns
(HTTP status, body text); the tests pass fixture bodies.

Pinned from the documentation (retrieved 2026-10-07; facts and URLs in
`docs/research/WALLET_SOURCE_MATRIX.md`):
- v1 retires on 2026-10-24; v2 routes live under `/v2` on the same host.
- **Envelope:** every v2 response wraps its payload in `data`; paginated routes add `pagination`.
  "A documented miss is `data: null` or an empty list, never an error." A bare array or a
  camelCase row (v1 shape) is refused.
- **Pagination:** cursor only. Follow `pagination.next_cursor` until it is `null`; `has_more` is
  exact. A cursor binds the parameters it was minted under. A repeated cursor, or `has_more`
  disagreeing with `next_cursor`, is an error, not the end of the data.
- **Field case:** snake_case (`proxy_wallet`, `condition_id`, `transaction_hash`, `token_id`,
  `usdc_size`, `outcome_index`).
- **Numbers:** `size`, `usdc_size` and `price` are JSON numbers (double). `decode` reads them with
  `parse_float=Decimal`, so no binary float ever becomes a quantity or money value. A payload already
  decoded with floats is refused.
- **Activity types:** TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION and the opt-in TIP (a
  user-to-user pUSD transfer whose `side` is IN or OUT). The list is open-ended in the docs (`…`), so
  an unrecognized type becomes Action.UNKNOWN with its raw text kept, never a trade.
- **Rows carry no per-fill id and no fee.** Identity is semantic plus occurrence (events.py), and the
  fee is UNKNOWN.
- `timestamp` is the block time in epoch seconds; `outcome_index` 999 means "could not be labeled".
- **Position statuses:** OPEN, REDEEMABLE, REDEEMABLE_LOST, MERGEABLE, CLOSED. Anything else is an
  error. Vendor P&L and value fields are kept as vendor-reported numbers and never used as ROI.
- **Errors:** `{"error", "code", "retryable", "trace_id", "parameter"?}`; codes invalid_request=400,
  not_found=404, method_not_allowed=405, rate_limited=429, internal=500, request_timeout=503,
  dependency_unavailable=503. 429 and 503 carry Retry-After.
- **Windows:** an omitted or 0 `start` floors to three years back; `start=1` asks for full history.
  Deposits and withdrawals are excluded by default.

Profile fields (name, pseudonym, bio, images) are validated for shape and then dropped. They are
not needed, and keeping less is safer (no doxxing).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

from ..provenance import sha256_hex, shape_fingerprint
from .events import (Action, AssetAmount, ChainFinality, WalletObservation, assign_occurrences, token_asset)
from .exact import Labeled, exact_decimal
from .identity import AccountRef
from .timeutil import from_epoch_seconds, require_aware

SOURCE = "polymarket_data_api_v2"
PRODUCT = "polymarket_international"
CHAIN = "polygon:137"
PARSER_VERSION = "polymarket-v2-parser-1"
V1_RETIREMENT_DATE = "2026-10-24"
UNLABELABLE_OUTCOME = 999
CASH = "USDC"

ERROR_STATUS = {"invalid_request": 400, "not_found": 404, "method_not_allowed": 405, "rate_limited": 429,
                "internal": 500, "request_timeout": 503, "dependency_unavailable": 503}

_ACTIVITY_REQUIRED = {
    "proxy_wallet": str, "timestamp": int, "condition_id": str, "type": str, "size": "number",
    "usdc_size": "number", "transaction_hash": str, "price": "number", "token_id": str, "side": str,
    "outcome_index": int,
}
_ACTIVITY_NULLABLE = ("title", "slug", "icon", "event_slug", "outcome", "name", "pseudonym", "bio",
                      "profile_image", "profile_image_optimized")
_ACTIVITY_OPTIONAL = ("is_combo",)
# The trade schema is only partly documented: this is the documented subset, all required.
_TRADE_REQUIRED = {
    "proxy_wallet": str, "timestamp": int, "condition_id": str, "size": "number", "price": "number",
    "token_id": str, "side": str, "outcome_index": int, "transaction_hash": str,
}
_POSITION_REQUIRED = {
    "proxy_wallet": str, "condition_id": str, "token_id": str, "current_size": "number", "status": str,
    "outcome_index": int,
}
_POSITION_VENDOR = ("avg_price", "entry_cost_usdc", "current_price", "current_value", "realized_pnl",
                    "unrealized_pnl", "total_pnl")
_PAGINATION_KNOWN = {"next_cursor", "has_more", "limit", "offset"}  # limit/offset: overview example only


class V2ParseError(ValueError):
    """The payload does not match the pinned v2 contract."""


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    REDEEMABLE = "REDEEMABLE"
    REDEEMABLE_LOST = "REDEEMABLE_LOST"
    MERGEABLE = "MERGEABLE"
    CLOSED = "CLOSED"


def decode(body: str | bytes) -> Any:
    """JSON with numbers as Decimal/int. NaN and Infinity are refused."""
    if isinstance(body, bytes):
        body = body.decode("utf-8")

    def bad_constant(name: str) -> Any:
        raise V2ParseError(f"non-finite JSON constant {name}")

    return json.loads(body, parse_float=Decimal, parse_constant=bad_constant)


def _number(row: dict, key: str, where: str) -> Decimal:
    value = row[key]
    if isinstance(value, float):
        raise V2ParseError(f"{where}.{key} is a binary float: decode the body with polymarket_v2.decode")
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise V2ParseError(f"{where}.{key} must be a number, not {type(value).__name__}")
    return exact_decimal(value, name=f"{where}.{key}")


def _check_row(row: Any, required: dict, nullable: tuple[str, ...], optional: tuple[str, ...], where: str) -> None:
    if not isinstance(row, dict):
        raise V2ParseError(f"{where} is not an object")
    camel = [k for k in row if any(c.isupper() for c in k)]
    if camel:
        raise V2ParseError(f"{where} has camelCase keys {sorted(camel)} (a v1 row?); v2 is snake_case")
    missing = [k for k in (*required, *nullable) if k not in row]
    if missing:
        raise V2ParseError(f"{where} is missing required field(s) {missing}")
    for key, kind in required.items():
        value = row[key]
        if value is None:
            raise V2ParseError(f"{where}.{key} is null")
        if kind == "number":
            _number(row, key, where)
        elif kind is int and (isinstance(value, bool) or not isinstance(value, int)):
            raise V2ParseError(f"{where}.{key} must be an integer")
        elif kind is str and not isinstance(value, str):
            raise V2ParseError(f"{where}.{key} must be a string")
    for key in (*nullable, *optional):
        if key in row and row[key] is not None and not isinstance(row[key], (str, bool, int)):
            raise V2ParseError(f"{where}.{key} has an unexpected type")


@dataclass(frozen=True)
class ApiError:
    status: int
    code: str
    message: str
    retryable: bool
    trace_id: str
    parameter: str | None
    retry_after_seconds: int | None
    status_matches_code: bool


def parse_error(status: int, body: str | bytes, *, retry_after: str | None = None) -> ApiError:
    payload = decode(body)
    if not isinstance(payload, dict):
        raise V2ParseError("error body is not an object")
    for key, kind in (("error", str), ("code", str), ("retryable", bool), ("trace_id", str)):
        if key not in payload:
            raise V2ParseError(f"error body is missing {key}")
        if not isinstance(payload[key], kind):
            raise V2ParseError(f"error field {key} has the wrong type")
    parameter = payload.get("parameter")
    if parameter is not None and not isinstance(parameter, str):
        raise V2ParseError("error field parameter must be a string")
    seconds = None
    if retry_after is not None:
        if not retry_after.strip().isdigit():
            raise V2ParseError(f"Retry-After {retry_after!r} is not delta-seconds")
        seconds = int(retry_after.strip())
    return ApiError(status, payload["code"], payload["error"], payload["retryable"], payload["trace_id"], parameter,
                    seconds, ERROR_STATUS.get(payload["code"]) == status)


@dataclass(frozen=True)
class Page:
    rows: tuple[dict, ...]
    next_cursor: str | None
    has_more: bool
    documented_miss: bool  # data was null or an empty list
    body_sha256: str
    shape_sha256: str
    unrecognized_fields: tuple[str, ...]


def parse_envelope(body: str | bytes, *, paginated: bool = True) -> Page:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    payload = decode(text)
    if not isinstance(payload, dict) or "data" not in payload:
        raise V2ParseError("not a v2 envelope: no top-level `data` (v1 responses are bare arrays or objects)")
    if "error" in payload:
        raise V2ParseError("an error body inside a success envelope")
    data = payload["data"]
    if data is not None and not isinstance(data, list):
        raise V2ParseError("`data` must be a list or null for a paginated route")
    unrecognized = sorted(k for k in payload if k not in {"data", "pagination"})
    next_cursor, has_more = None, False
    if paginated:
        pagination = payload.get("pagination")
        if not isinstance(pagination, dict):
            raise V2ParseError("paginated v2 response has no `pagination` object")
        for key in ("next_cursor", "has_more"):
            if key not in pagination:
                raise V2ParseError(f"pagination is missing {key}")
        next_cursor, has_more = pagination["next_cursor"], pagination["has_more"]
        if not isinstance(has_more, bool):
            raise V2ParseError("pagination.has_more must be a boolean")
        if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
            raise V2ParseError("pagination.next_cursor must be a non-empty string or null")
        if has_more != (next_cursor is not None):
            raise V2ParseError("pagination.has_more disagrees with next_cursor")
        unrecognized += [f"pagination.{k}" for k in sorted(pagination) if k not in _PAGINATION_KNOWN]
    rows = tuple(data or ())
    return Page(rows, next_cursor, has_more, not rows, sha256_hex(text), shape_fingerprint(payload),
                tuple(unrecognized))


def activity_observation(row: dict, *, index: int, page_sha256: str, receipt_time: datetime,
                         synthetic: bool) -> WalletObservation:
    where = f"data[{index}]"
    _check_row(row, _ACTIVITY_REQUIRED, _ACTIVITY_NULLABLE, _ACTIVITY_OPTIONAL, where)
    size = _number(row, "size", where)
    usdc = _number(row, "usdc_size", where)
    price = _number(row, "price", where)
    raw_type, side = row["type"], row["side"]
    ambiguities: list[str] = []
    outcome_index: int | None = row["outcome_index"]
    if outcome_index == UNLABELABLE_OUTCOME:
        outcome_index = None
        ambiguities.append("OUTCOME_UNLABELABLE")
    token = token_asset(row["token_id"])
    paid: list[AssetAmount] = []
    received: list[AssetAmount] = []

    def leg(target: list[AssetAmount], asset: str, qty: Decimal) -> None:
        if qty < 0:
            raise V2ParseError(f"{where}: negative amount")
        if qty > 0:
            target.append(AssetAmount(asset, qty))

    action = Action.UNKNOWN
    if raw_type == "TRADE":
        if size <= 0:
            raise V2ParseError(f"{where}: a trade needs a positive size")
        if side == "BUY":
            action = Action.TRADE_BUY
            leg(paid, CASH, usdc)
            leg(received, token, size)
        elif side == "SELL":
            action = Action.TRADE_SELL
            leg(paid, token, size)
            leg(received, CASH, usdc)
        else:
            ambiguities.append("TRADE_WITHOUT_SIDE")
    elif raw_type == "TIP":
        if side == "IN":
            action = Action.TRANSFER_IN
            leg(received, "PUSD", size)
        elif side == "OUT":
            action = Action.TRANSFER_OUT
            leg(paid, "PUSD", size)
        else:
            ambiguities.append("TIP_WITHOUT_DIRECTION")
    elif raw_type == "SPLIT":
        action = Action.SPLIT
        leg(paid, CASH, usdc)
        ambiguities.append("LEGS_NOT_ITEMIZED")
    elif raw_type == "MERGE":
        action = Action.MERGE
        leg(received, CASH, usdc)
        ambiguities.append("LEGS_NOT_ITEMIZED")
    elif raw_type == "REDEEM":
        action = Action.REDEEM
        leg(received, CASH, usdc)
        ambiguities.append("LEGS_NOT_ITEMIZED")
    elif raw_type == "CONVERSION":
        action = Action.CONVERSION
        ambiguities.append("LEGS_NOT_ITEMIZED")
    elif raw_type == "REWARD":
        action = Action.REWARD
        leg(received, CASH, usdc)
    elif raw_type in ("MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD", "YIELD"):
        action = Action.REWARD
        leg(received, CASH, usdc)
        ambiguities.append("TYPE_FROM_V1_ENUM")
    elif raw_type in ("DEPOSIT", "WITHDRAWAL"):
        action = Action.TRANSFER_IN if raw_type == "DEPOSIT" else Action.TRANSFER_OUT
        leg(received if raw_type == "DEPOSIT" else paid, CASH, usdc)
        ambiguities.append("TYPE_FROM_V1_ENUM")
    if action is Action.UNKNOWN:
        ambiguities.append("LEGS_NOT_ITEMIZED")
        ambiguities.append(f"UNRECOGNIZED_TYPE:{raw_type}")
    return WalletObservation(
        source=SOURCE, product=PRODUCT, chain=CHAIN, account=AccountRef(PRODUCT, row["proxy_wallet"]),
        source_event_id=None, transaction_id=row["transaction_hash"], sub_index=None, occurrence=0,
        action=action, raw_action=f"{raw_type}/{side}", instrument_id=row["token_id"],
        market_id=row["condition_id"], event_id=row.get("event_slug"), outcome_index=outcome_index,
        native_quantity=size if action in (Action.TRADE_BUY, Action.TRADE_SELL) or size > 0 else None,
        native_decimals=None, paid=tuple(paid), received=tuple(received),
        price=price if action in (Action.TRADE_BUY, Action.TRADE_SELL) else None,
        price_basis="USDC_PER_SHARE" if action in (Action.TRADE_BUY, Action.TRADE_SELL) else None,
        fee=Labeled.unknown("v2 activity rows carry no fee field"),
        source_time=from_epoch_seconds(row["timestamp"], f"{where}.timestamp"), receipt_time=receipt_time,
        finality=ChainFinality.UNKNOWN, raw_ref=f"sha256:{page_sha256}#{where}", parser_version=PARSER_VERSION,
        ambiguities=tuple(sorted(set(ambiguities))), synthetic=synthetic)


@dataclass(frozen=True)
class ActivityPage:
    page: Page
    observations: tuple[WalletObservation, ...]


def parse_activity_page(body: str | bytes, *, receipt_time: datetime, synthetic: bool) -> ActivityPage:
    require_aware(receipt_time, "receipt_time")
    page = parse_envelope(body)
    obs = tuple(activity_observation(r, index=i, page_sha256=page.body_sha256, receipt_time=receipt_time,
                                     synthetic=synthetic) for i, r in enumerate(page.rows))
    return ActivityPage(page, obs)


def parse_trades_page(body: str | bytes, *, receipt_time: datetime, synthetic: bool) -> ActivityPage:
    """Trades rows (documented subset). Each is a TRADE activity from the wallet's perspective."""
    require_aware(receipt_time, "receipt_time")
    page = parse_envelope(body)
    out = []
    for i, row in enumerate(page.rows):
        _check_row(row, _TRADE_REQUIRED, (), (), f"data[{i}]")
        size, price = _number(row, "size", f"data[{i}]"), _number(row, "price", f"data[{i}]")
        usdc = _number(row, "usdc_size", f"data[{i}]") if "usdc_size" in row else None
        if usdc is None:
            raise V2ParseError(f"data[{i}] has no usdc_size: cash leg unknown")
        synthetic_row = {**{k: row.get(k) for k in _ACTIVITY_NULLABLE}, **row, "type": "TRADE", "usdc_size": usdc,
                         "size": size, "price": price}
        out.append(activity_observation(synthetic_row, index=i, page_sha256=page.body_sha256,
                                        receipt_time=receipt_time, synthetic=synthetic))
    return ActivityPage(page, tuple(out))


@dataclass(frozen=True)
class PositionRow:
    account: AccountRef
    condition_id: str
    token_id: str
    status: PositionStatus
    current_size: Decimal
    outcome_index: int | None
    # Vendor-derived values: kept for display and comparison, never used as ROI or as wealth.
    vendor_reported: dict[str, Decimal | None] = field(default_factory=dict)


def parse_positions_page(body: str | bytes) -> tuple[Page, tuple[PositionRow, ...]]:
    page = parse_envelope(body)
    rows = []
    for i, row in enumerate(page.rows):
        where = f"data[{i}]"
        _check_row(row, _POSITION_REQUIRED, (), (), where)
        try:
            status = PositionStatus(row["status"])
        except ValueError as exc:
            raise V2ParseError(f"{where}.status {row['status']!r} is not a documented position status") from exc
        vendor = {k: (_number(row, k, where) if row.get(k) is not None else None) for k in _POSITION_VENDOR
                  if k in row}
        idx = row["outcome_index"]
        rows.append(PositionRow(AccountRef(PRODUCT, row["proxy_wallet"]), row["condition_id"], row["token_id"],
                                status, _number(row, "current_size", where),
                                None if idx == UNLABELABLE_OUTCOME else idx, vendor))
    return page, tuple(rows)


class WalkStop(str, Enum):
    COMPLETE = "COMPLETE"  # next_cursor became null
    API_ERROR = "API_ERROR"
    CURSOR_LOOP = "CURSOR_LOOP"
    PAGE_LIMIT = "PAGE_LIMIT"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass(frozen=True)
class WalkResult:
    pages: tuple[ActivityPage, ...]
    stop: WalkStop
    error: ApiError | None
    detail: str

    @property
    def complete(self) -> bool:
        return self.stop is WalkStop.COMPLETE

    @property
    def observations(self) -> tuple[WalletObservation, ...]:
        """Every row of the walk, with occurrences numbered across the whole retrieval."""
        return assign_occurrences([o for p in self.pages for o in p.observations])


Fetch = Callable[[str | None], tuple[int, str, dict[str, str]]]


def walk(fetch: Fetch, *, receipt_time: datetime, synthetic: bool, max_pages: int,
         parser: Callable[..., ActivityPage] = parse_activity_page) -> WalkResult:
    """Follow next_cursor until null. `fetch(cursor)` returns (status, body, headers) from fixtures.

    Anything other than a clean end is incomplete: an API error, a repeated cursor, the page limit or
    a payload that breaks the contract. Pages read before the stop are kept, labelled incomplete.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    pages: list[ActivityPage] = []
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(max_pages):
        status, body, headers = fetch(cursor)
        if status != 200:
            try:
                err = parse_error(status, body, retry_after=headers.get("Retry-After"))
            except V2ParseError as exc:
                return WalkResult(tuple(pages), WalkStop.PARSE_ERROR, None, f"HTTP {status}: {exc}")
            return WalkResult(tuple(pages), WalkStop.API_ERROR, err, f"HTTP {status} {err.code}")
        try:
            page = parser(body, receipt_time=receipt_time, synthetic=synthetic)
        except (V2ParseError, ValueError) as exc:
            return WalkResult(tuple(pages), WalkStop.PARSE_ERROR, None, str(exc))
        pages.append(page)
        cursor = page.page.next_cursor
        if cursor is None:
            return WalkResult(tuple(pages), WalkStop.COMPLETE, None, f"{len(pages)} page(s)")
        if cursor in seen:
            return WalkResult(tuple(pages), WalkStop.CURSOR_LOOP, None, "a cursor repeated")
        seen.add(cursor)
    return WalkResult(tuple(pages), WalkStop.PAGE_LIMIT, None, f"stopped after {max_pages} page(s)")


def history_complete(walk_result: WalkResult, *, start_param: int | None) -> bool:
    """True only for a clean walk that asked for full history (`start=1`). An omitted or 0 `start`
    floors to three years back, so anything earlier is unobserved."""
    return walk_result.complete and start_param == 1
