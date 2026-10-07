"""Kalshi Trade API v2 wire format for the ordinary event-order profile (#160 package F). Pure functions.

- **Builders** turn a `model.OrderIntent` (or an account read) into a `WireRequest`: an allowlisted endpoint, a
  path relative to the API root, a canonical query and a deterministic JSON body. Nothing here sends, signs or
  holds a credential; `transport.py` sends and `signer.py` signs, and both accept only a `WireRequest`.
- **Parsers** turn response bytes into typed, frozen records with `Decimal` values. A missing or null required
  field raises `WireFormatError`; it is never read as zero. Unknown extra fields are kept in `extra`.

This is the one file allowed to name the order endpoints (ADR 0043, `EXECUTION_EXCEPTIONS`). The HTTP method is
an `HttpMethod` member here; only the transport turns it into a request.

Units (conformance pack): prices are fixed-point dollar strings and always the YES price (DIR-01); a NO intent at
limit q is sent as the opposite book side at YES price 1 - q (DIR-02). Counts are fixed-point strings with 0.01
granularity (QTY-01). Integer-cent fields stay integer cents and are named `_cents`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from . import conformance as c
from .conformance import Evidence, Fact, Support, UnsupportedByProfile
from .model import AccountScope, Action, IntentKind, OrderIntent, Side, TimeInForce

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------------------------- endpoint facts

_CREATE = c._p("api-reference/orders/create-order-v2")
_CANCEL = c._p("api-reference/orders/cancel-order-v2")
_AMEND = c._p("api-reference/orders/amend-order-v2")
_DECREASE = c._p("api-reference/orders/decrease-order-v2")
_GET_ORDERS = c._p("api-reference/orders/get-orders")
_GET_ORDER = c._p("api-reference/orders/get-order")
_HIST_ORDERS = c._p("api-reference/historical/get-historical-orders")
_D = Evidence.DOCUMENTED
_F = Evidence.FIXTURE_TESTED

ENDPOINT_FACTS: tuple[Fact, ...] = (
    Fact("ORD-01", "POST /portfolio/events/orders", _D, _CREATE),
    Fact("ORD-02", "legacy POST /portfolio/orders create (deprecated no earlier than May 6, 2026)", _D, _CREATE,
         support=Support.UNSUPPORTED),
    Fact("ORD-03", ("ticker", "side", "count", "price", "time_in_force", "self_trade_prevention_type"), _D, _CREATE),
    Fact("ORD-04", ("bid", "ask"), _D, _CREATE),
    Fact("ORD-05", "price: fixed-point dollars, the YES price", _D, _CREATE),
    Fact("ORD-06", "count: fixed-point contracts, minimum granularity 0.01", _D, _CREATE),
    Fact("ORD-07", "expiration_time: Unix seconds, with good_till_canceled; not with immediate_or_cancel", _D,
         _CREATE),
    Fact("ORD-08", ("fill_or_kill", "good_till_canceled", "immediate_or_cancel"), _D, _CREATE),
    Fact("ORD-09", "reduce_only orders are rejected unless time_in_force is immediate_or_cancel", _D, _CREATE),
    Fact("ORD-10", ("taker_at_cross", "maker"), _D, _CREATE),
    Fact("ORD-11", "cancel_order_on_pause cancels an open order when trading is paused", _D, _CREATE),
    Fact("ORD-12", "post_only behaviour when the order would cross", _D, _CREATE, support=Support.UNKNOWN),
    Fact("ORD-13", "exchange_index >= 0 routes directly; -1 or omitted with a ticker auto-routes", _D, _CREATE),
    Fact("ORD-14", ("order_id", "fill_count", "remaining_count", "ts_ms"), _F, _CREATE,
         fixture="create_order_v2_response.json"),
    Fact("ORD-15", 201, _D, _CREATE),  # created
    Fact("ORD-16", "meaning of 409 Conflict for a repeated client_order_id", _D, _CREATE, support=Support.UNKNOWN),
    Fact("ORD-17", "DELETE /portfolio/events/orders/{order_id}", _D, _CANCEL),
    Fact("ORD-18", ("order_id", "reduced_by", "ts_ms"), _F, _CANCEL, fixture="cancel_order_v2_response.json"),
    Fact("ORD-19", "cancel description lists {order_id, client_order_id, reduced_by}; the schema also requires "
         "ts_ms", _D, _CANCEL, support=Support.UNKNOWN),
    Fact("ORD-20", "POST /portfolio/events/orders/{order_id}/amend", _D, _AMEND),
    Fact("ORD-21", "amend count = already filled count + desired resting remainder", _D, _AMEND),
    Fact("ORD-22", ("order_id", "ts_ms"), _F, _AMEND, fixture="amend_order_v2_response.json"),
    Fact("ORD-23", "amend expiration_time: omit preserves, 0 clears, a future value replaces", _D, _AMEND),
    Fact("ORD-24", "POST /portfolio/events/orders/{order_id}/decrease with exactly one of reduce_by, reduce_to",
         _D, _DECREASE),
    Fact("ORD-25", ("order_id", "remaining_count", "ts_ms"), _F, _DECREASE,
         fixture="decrease_order_v2_response.json"),
    Fact("ORD-26", ("resting", "canceled", "executed"), _D, _GET_ORDERS),
    Fact("ORD-27", "GET /portfolio/orders: resting orders always live; omitted subaccount = all", _D, _GET_ORDERS),
    Fact("ORD-28", "GET /portfolio/orders/{order_id}", _D, _GET_ORDER),
    Fact("ORD-29", "GET /historical/orders, /historical/fills, /historical/positions use the same cursors", _D,
         _HIST_ORDERS),
    Fact("ORD-30", "order groups (rolling 15 s contract limit 1-1,000,000)", _D, c.ORDER_GROUPS,
         support=Support.UNSUPPORTED),
    Fact("ORD-31", "batch create and batch cancel", _D, c.RATE_LIMITS, support=Support.UNSUPPORTED),
    Fact("ORD-32", ("order_id", "user_id", "client_order_id", "ticker", "outcome_side", "book_side", "type",
                    "status", "yes_price_dollars", "no_price_dollars", "fill_count_fp", "remaining_count_fp",
                    "initial_count_fp", "taker_fees_dollars", "maker_fees_dollars", "taker_fill_cost_dollars",
                    "maker_fill_cost_dollars"), _D, _GET_ORDERS),
    Fact("ORD-33", "market orders (type market)", _D, _GET_ORDERS, support=Support.UNSUPPORTED),
    Fact("ORD-34", "whether decrease reduce_to counts the filled part or only the resting remainder", _D, _DECREASE,
         support=Support.UNKNOWN),
)

# ---------------------------------------------------------------------------------------------- endpoints


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    DELETE = "DELETE"


class Bucket(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


_ORDER_ID = r"[A-Za-z0-9-]{1,64}"


@dataclass(frozen=True)
class EndpointSpec:
    method: HttpMethod
    template: str  # relative to the API root; `{order_id}` is the only placeholder
    bucket: Bucket
    protective: bool  # may draw on reserved rate capacity: cancels, decreases and reconciliation reads
    query_keys: frozenset[str]

    def matches(self, path: str) -> bool:
        pattern = re.escape(self.template).replace(re.escape("{order_id}"), _ORDER_ID)
        return re.fullmatch(pattern, path) is not None


def _spec(method: HttpMethod, template: str, bucket: Bucket, protective: bool, *keys: str) -> EndpointSpec:
    return EndpointSpec(method, template, bucket, protective, frozenset(keys))


_LIST = ("subaccount", "limit", "cursor", "ticker", "min_ts", "max_ts")


class Endpoint(Enum):
    """The complete allowlist of method + path templates. Nothing else can be built, signed or sent."""

    ORDER_CREATE = _spec(HttpMethod.POST, "/portfolio/events/orders", Bucket.WRITE, False)
    ORDER_CANCEL = _spec(HttpMethod.DELETE, "/portfolio/events/orders/{order_id}", Bucket.WRITE, True,
                         "subaccount", "exchange_index")
    ORDER_AMEND = _spec(HttpMethod.POST, "/portfolio/events/orders/{order_id}/amend", Bucket.WRITE, False,
                        "subaccount")
    ORDER_DECREASE = _spec(HttpMethod.POST, "/portfolio/events/orders/{order_id}/decrease", Bucket.WRITE, True,
                           "subaccount")
    GET_ORDER = _spec(HttpMethod.GET, "/portfolio/orders/{order_id}", Bucket.READ, True)
    GET_ORDERS = _spec(HttpMethod.GET, "/portfolio/orders", Bucket.READ, True, *_LIST, "status", "event_ticker",
                       "exchange_index")
    GET_BALANCE = _spec(HttpMethod.GET, "/portfolio/balance", Bucket.READ, True, "subaccount", "exchange_index")
    GET_POSITIONS = _spec(HttpMethod.GET, "/portfolio/positions", Bucket.READ, True, "subaccount", "limit", "cursor",
                          "ticker", "event_ticker", "settlement_status", "exchange_index")
    GET_FILLS = _spec(HttpMethod.GET, "/portfolio/fills", Bucket.READ, True, *_LIST, "order_id", "exchange_index")
    GET_SETTLEMENTS = _spec(HttpMethod.GET, "/portfolio/settlements", Bucket.READ, True, *_LIST, "event_ticker")
    GET_HISTORICAL_CUTOFF = _spec(HttpMethod.GET, "/historical/cutoff", Bucket.READ, True)
    GET_HISTORICAL_ORDERS = _spec(HttpMethod.GET, "/historical/orders", Bucket.READ, True, *_LIST)
    GET_HISTORICAL_FILLS = _spec(HttpMethod.GET, "/historical/fills", Bucket.READ, True, *_LIST)
    GET_HISTORICAL_POSITIONS = _spec(HttpMethod.GET, "/historical/positions", Bucket.READ, True, "subaccount",
                                     "limit", "cursor", "ticker", "event_ticker")
    GET_EXCHANGE_STATUS = _spec(HttpMethod.GET, "/exchange/status", Bucket.READ, True)
    GET_USER_DATA_TIMESTAMP = _spec(HttpMethod.GET, "/exchange/user_data_timestamp", Bucket.READ, True)


_QUERY_VALUE = re.compile(r"[\x21-\x7e]{1,1024}")  # printable ASCII, no spaces or controls


@dataclass(frozen=True)
class WireRequest:
    """One allowlisted request, relative to the API root. Immutable and validated at construction, so every
    `WireRequest` that exists is on the allowlist; the signer and the transport re-check anyway."""

    endpoint: Endpoint
    scope: AccountScope
    path: str
    query: tuple[tuple[str, str], ...] = ()
    body: bytes | None = field(default=None, repr=False)
    exchange_index: int | None = None  # the shard a write is billed to (rate budget); required for writes

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, Endpoint):
            raise ValueError("endpoint must be an allowlisted Endpoint")
        if not isinstance(self.scope, AccountScope):
            raise ValueError("scope must be an AccountScope")
        spec = self.endpoint.value
        if not isinstance(self.path, str) or "?" in self.path or not spec.matches(self.path):
            raise ValueError(f"path does not match the {self.endpoint.name} template")
        if not isinstance(self.query, tuple) or any(not (isinstance(p, tuple) and len(p) == 2) for p in self.query):
            raise ValueError("query must be a tuple of (key, value) pairs")
        keys = [k for k, _ in self.query]
        if keys != sorted(set(keys)):
            raise ValueError("query keys must be unique and sorted (canonical)")
        for k, v in self.query:
            if k not in spec.query_keys:
                raise ValueError(f"query key {k!r} is not allowed for {self.endpoint.name}")
            if not isinstance(v, str) or not _QUERY_VALUE.fullmatch(v):
                raise ValueError(f"query value for {k!r} must be printable text without spaces")
        if spec.method is HttpMethod.POST:
            try:
                canonical = isinstance(self.body, bytes) and self.body == _canonical_body(_load_object(self.body, "body"))
            except (TypeError, ValueError):
                canonical = False
            if not canonical:
                raise ValueError("a POST body must be canonical JSON bytes")
        elif self.body is not None:
            raise ValueError(f"{spec.method.value} requests carry no body")
        if self.endpoint is Endpoint.ORDER_DECREASE and set(json.loads(self.body)) != {"reduce_by", "exchange_index"}:
            raise ValueError("a decrease carries reduce_by and exchange_index only (reduce_to is UNKNOWN, ORD-34)")
        if spec.bucket is Bucket.WRITE:
            if isinstance(self.exchange_index, bool) or not isinstance(self.exchange_index, int) \
                    or self.exchange_index < 0:
                raise ValueError("a write names its exchange shard explicitly")
        elif self.exchange_index is not None:
            raise ValueError("only writes carry a billing shard")

    @property
    def method(self) -> HttpMethod:
        return self.endpoint.value.method

    @property
    def full_path(self) -> str:
        """The path from the host root: the API prefix plus `path`. This is what is signed (AUTH-05)."""
        return c.API_PATH_PREFIX + self.path

    def query_string(self) -> str:
        return urlencode(self.query)

    def is_write(self) -> bool:
        return self.endpoint.value.bucket is Bucket.WRITE


def check_allowlisted(request: object) -> WireRequest:
    """`request` if it is a `WireRequest` on the allowlist (re-validated); otherwise raises."""
    if not isinstance(request, WireRequest):
        raise ValueError("only a kalshi_wire.WireRequest is accepted")
    WireRequest(request.endpoint, request.scope, request.path, request.query, request.body, request.exchange_index)
    return request


# ---------------------------------------------------------------------------------------------- formatting


def _canonical_body(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _fixed(value: Decimal, places: int, name: str) -> str:
    quantum = Decimal(1).scaleb(-places)
    if not isinstance(value, Decimal) or not value.is_finite() or value.quantize(quantum) != value:
        raise UnsupportedByProfile(f"{name} {value} needs more than {places} decimal places")
    return f"{value.quantize(quantum):f}"


def price_text(value: Decimal) -> str:
    """A request price: fixed-point dollars with exactly 4 decimals (PX-04 allows 2-4)."""
    return _fixed(value, c.PRICE_REQUEST_DECIMALS, "price")


def count_text(value: Decimal) -> str:
    """A request count: fixed-point contracts with exactly 2 decimals (QTY-02)."""
    return _fixed(value, c.COUNT_DECIMALS, "count")


def subaccount_number(scope: AccountScope) -> int:
    """The venue subaccount: always explicit, because an omitted one means different things on different endpoints
    (SUB-03) and, for a restricted key, the key's locked subaccount (SUB-02)."""
    number = 0 if scope.subaccount is None else scope.subaccount
    if not c.SUBACCOUNT_MIN <= number <= c.SUBACCOUNT_MAX:
        raise UnsupportedByProfile(f"subaccount {number} is outside {c.SUBACCOUNT_MIN}-{c.SUBACCOUNT_MAX}")
    return number


def yes_terms(side: Side, action: Action, limit_price: Decimal) -> tuple[str, Decimal]:
    """(book side, YES price) for an outcome-side order (DIR-02): buy YES and sell NO are bids; buy NO and sell YES
    are asks. A NO price q is the YES price 1 - q."""
    yes_price = limit_price if side is Side.YES else Decimal(1) - limit_price
    long_yes = (side is Side.YES) == (action is Action.BUY)
    return ("bid" if long_yes else "ask"), yes_price


def _query(**params: object) -> tuple[tuple[str, str], ...]:
    out = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError(f"{key} must not be a bool")
        out.append((key, str(value)))
    return tuple(sorted(out))


def _order_id(order_id: object) -> str:
    if not isinstance(order_id, str) or not re.fullmatch(_ORDER_ID, order_id):
        raise ValueError("order_id is not a venue order id")
    return order_id


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= c.PAGE_LIMIT_MAX:
        raise ValueError(f"limit must be an int in 1-{c.PAGE_LIMIT_MAX}")
    return limit


def _client_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
        raise ValueError(f"{name} is not a client order id")
    return value


def _shard(index: object) -> int:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("exchange_index must be an explicit non-negative shard")
    return index


def _check_intent(intent: OrderIntent, market: c.MarketTradingProfile) -> None:
    if not isinstance(intent, OrderIntent) or not isinstance(market, c.MarketTradingProfile):
        raise ValueError("an OrderIntent and a MarketTradingProfile are required")
    if intent.profile_version != c.PROFILE_VERSION:
        raise UnsupportedByProfile(f"intent profile {intent.profile_version!r} is not {c.PROFILE_VERSION}")
    if intent.market_ticker != market.ticker:
        raise ValueError("the market record is for another ticker")
    if intent.time_in_force not in c.SUPPORTED_TIME_IN_FORCE:
        raise UnsupportedByProfile(f"time in force {intent.time_in_force} is not supported")
    if intent.reduce_only and intent.time_in_force not in c.REDUCE_ONLY_TIME_IN_FORCE:
        raise UnsupportedByProfile("reduce_only requires immediate_or_cancel (ORD-09)")
    if intent.kind is IntentKind.REDUCTION and not intent.reduce_only:  # model already refuses; never a flip
        raise UnsupportedByProfile("a reduction is always reduce-only")


# ---------------------------------------------------------------------------------------------- write builders


def build_create(intent: OrderIntent, market: c.MarketTradingProfile) -> WireRequest:
    """The V2 create request for one ordinary limit order (ORD-01, ORD-03)."""
    _check_intent(intent, market)
    side, yes_price = yes_terms(intent.side, intent.action, intent.limit_price)
    body: dict[str, Any] = {
        "ticker": intent.market_ticker,
        "client_order_id": intent.client_order_id(),
        "side": side,
        "count": count_text(intent.quantity),
        "price": price_text(market.check_yes_price(yes_price)),
        "time_in_force": intent.time_in_force.value,
        "self_trade_prevention_type": c.SELF_TRADE_PREVENTION,
        "post_only": intent.post_only,
        "reduce_only": intent.reduce_only,
        "cancel_order_on_pause": c.CANCEL_ORDER_ON_PAUSE,
        "subaccount": subaccount_number(intent.scope),
        "exchange_index": market.exchange_index,
    }
    if intent.time_in_force is TimeInForce.GOOD_TILL_CANCELED:
        # A resting order never outlives its intent (ORD-07). Floored to whole seconds: never later than approved.
        body["expiration_time"] = (intent.expires_at() - _EPOCH) // timedelta(seconds=1)
    return WireRequest(Endpoint.ORDER_CREATE, intent.scope, Endpoint.ORDER_CREATE.value.template,
                       body=_canonical_body(body), exchange_index=market.exchange_index)


def build_cancel(scope: AccountScope, order_id: str, *, exchange_index: int) -> WireRequest:
    """Cancel one order (ORD-17). The shard is explicit: an order id alone cannot identify it (SHD-02)."""
    shard = _shard(exchange_index)
    return WireRequest(Endpoint.ORDER_CANCEL, scope, f"/portfolio/events/orders/{_order_id(order_id)}",
                       _query(subaccount=subaccount_number(scope), exchange_index=shard), exchange_index=shard)


def build_amend(intent: OrderIntent, market: c.MarketTradingProfile, *, order_id: str, new_limit_price: Decimal,
                filled_count: Decimal, desired_remaining: Decimal, current_client_order_id: str,
                updated_client_order_id: str | None = None) -> WireRequest:
    """Amend price and/or size within the approved intent (ORD-20, ORD-21).

    `current_client_order_id` is the client order id the order carries now: the intent's id for the first amend,
    and the last `updated_client_order_id` after an amend that set one. It is required, so a later amend cannot
    silently send the original id.

    The request count is filled + desired remaining, never just the remainder. The amend may only make the order
    less aggressive or smaller than the approved intent: a buy's price never rises above, and a sell's never falls
    below, the approved limit, and the total never exceeds the approved quantity. Anything else is a new intent.
    """
    _check_intent(intent, market)
    if intent.time_in_force is not TimeInForce.GOOD_TILL_CANCELED:
        raise UnsupportedByProfile("only a resting good_till_canceled order can be amended")
    for name, value in (("new_limit_price", new_limit_price), ("filled_count", filled_count),
                        ("desired_remaining", desired_remaining)):
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError(f"{name} must be a finite Decimal")
    if filled_count < 0 or desired_remaining <= 0:
        raise ValueError("filled_count must be >= 0 and desired_remaining > 0 (use cancel to remove the rest)")
    total = filled_count + desired_remaining
    if total > intent.quantity:
        raise UnsupportedByProfile("an amend never raises the order above the approved quantity")
    if (intent.action is Action.BUY and new_limit_price > intent.limit_price) or \
            (intent.action is Action.SELL and new_limit_price < intent.limit_price):
        raise UnsupportedByProfile("an amend never makes the price more aggressive than approved")
    intent.price_grid.check(new_limit_price, name="new_limit_price")
    side, yes_price = yes_terms(intent.side, intent.action, new_limit_price)
    body: dict[str, Any] = {
        "ticker": intent.market_ticker,
        "side": side,
        "price": price_text(market.check_yes_price(yes_price)),
        "count": count_text(total),
        "client_order_id": _client_id(current_client_order_id, "current_client_order_id"),
        "exchange_index": market.exchange_index,
    }
    if updated_client_order_id is not None:
        body["updated_client_order_id"] = _client_id(updated_client_order_id, "updated_client_order_id")
        if updated_client_order_id == current_client_order_id:
            raise ValueError("updated_client_order_id must differ from the current one")
    return WireRequest(Endpoint.ORDER_AMEND, intent.scope, f"/portfolio/events/orders/{_order_id(order_id)}/amend",
                       _query(subaccount=subaccount_number(intent.scope)), body=_canonical_body(body),
                       exchange_index=market.exchange_index)


def build_decrease(scope: AccountScope, order_id: str, *, exchange_index: int, reduce_by: Decimal,
                   reduce_to: Decimal | None = None) -> WireRequest:
    """Decrease a resting order by `reduce_by` contracts (ORD-24).

    `reduce_to` is refused: whether its target counts the filled part or only the resting remainder is not
    documented (ORD-34), so it is neither sent nor treated as protective until a venue observation settles it."""
    if reduce_to is not None:
        raise UnsupportedByProfile("reduce_to semantics are UNKNOWN (ORD-34); use reduce_by")
    shard = _shard(exchange_index)
    if not isinstance(reduce_by, Decimal) or not reduce_by.is_finite() or reduce_by <= 0:
        raise ValueError("reduce_by must be a positive Decimal")
    body: dict[str, Any] = {"reduce_by": count_text(reduce_by), "exchange_index": shard}
    return WireRequest(Endpoint.ORDER_DECREASE, scope, f"/portfolio/events/orders/{_order_id(order_id)}/decrease",
                       _query(subaccount=subaccount_number(scope)), body=_canonical_body(body), exchange_index=shard)


# ---------------------------------------------------------------------------------------------- read builders


def _cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not _QUERY_VALUE.fullmatch(cursor):
        raise ValueError("cursor must be the opaque printable text the venue returned")
    return cursor


def _ts(value: int | None, name: str) -> int | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative Unix timestamp int")
    return value


def build_get_order(scope: AccountScope, order_id: str) -> WireRequest:
    return WireRequest(Endpoint.GET_ORDER, scope, f"/portfolio/orders/{_order_id(order_id)}")


def build_get_orders(scope: AccountScope, *, status: str | None = None, ticker: str | None = None,
                     cursor: str | None = None, limit: int = 100, min_ts: int | None = None,
                     max_ts: int | None = None, historical: bool = False) -> WireRequest:
    """Live orders, or archived ones with `historical=True` (ACC-10). The subaccount is always explicit."""
    if status is not None and (historical or status not in c.ORDER_STATUSES):
        raise ValueError(f"status must be one of {c.ORDER_STATUSES} (live reads only)")
    endpoint = Endpoint.GET_HISTORICAL_ORDERS if historical else Endpoint.GET_ORDERS
    return WireRequest(endpoint, scope, endpoint.value.template, _query(
        subaccount=subaccount_number(scope), status=status, ticker=ticker, cursor=_cursor(cursor),
        limit=_limit(limit), min_ts=_ts(min_ts, "min_ts"), max_ts=_ts(max_ts, "max_ts")))


def build_get_balance(scope: AccountScope, *, exchange_index: int | None = None) -> WireRequest:
    return WireRequest(Endpoint.GET_BALANCE, scope, Endpoint.GET_BALANCE.value.template, _query(
        subaccount=subaccount_number(scope), exchange_index=None if exchange_index is None else _shard(exchange_index)))


def build_get_positions(scope: AccountScope, *, settlement_status: str, cursor: str | None = None, limit: int = 100,
                        ticker: str | None = None, event_ticker: str | None = None) -> WireRequest:
    """Live positions. `settlement_status` is required: the venue default is `unsettled` (ACC-07), and a
    reconciliation that forgot settled-but-live rows would be silently incomplete."""
    if settlement_status not in c.POSITION_SETTLEMENT_STATUSES:
        raise ValueError(f"settlement_status must be one of {c.POSITION_SETTLEMENT_STATUSES}")
    return WireRequest(Endpoint.GET_POSITIONS, scope, Endpoint.GET_POSITIONS.value.template, _query(
        subaccount=subaccount_number(scope), settlement_status=settlement_status, cursor=_cursor(cursor),
        limit=_limit(limit), ticker=ticker, event_ticker=event_ticker))


def build_get_historical_positions(scope: AccountScope, *, cursor: str | None = None, limit: int = 100,
                                   ticker: str | None = None, event_ticker: str | None = None) -> WireRequest:
    return WireRequest(Endpoint.GET_HISTORICAL_POSITIONS, scope, Endpoint.GET_HISTORICAL_POSITIONS.value.template,
                       _query(subaccount=subaccount_number(scope), cursor=_cursor(cursor), limit=_limit(limit),
                              ticker=ticker, event_ticker=event_ticker))


def build_get_fills(scope: AccountScope, *, ticker: str | None = None, order_id: str | None = None,
                    cursor: str | None = None, limit: int = 100, min_ts: int | None = None, max_ts: int | None = None,
                    historical: bool = False) -> WireRequest:
    if historical and order_id is not None:
        raise ValueError("historical fills take no order_id filter")
    endpoint = Endpoint.GET_HISTORICAL_FILLS if historical else Endpoint.GET_FILLS
    return WireRequest(endpoint, scope, endpoint.value.template, _query(
        subaccount=subaccount_number(scope), ticker=ticker,
        order_id=None if order_id is None else _order_id(order_id), cursor=_cursor(cursor), limit=_limit(limit),
        min_ts=_ts(min_ts, "min_ts"), max_ts=_ts(max_ts, "max_ts")))


def build_get_settlements(scope: AccountScope, *, cursor: str | None = None, limit: int = 100,
                          ticker: str | None = None, event_ticker: str | None = None, min_ts: int | None = None,
                          max_ts: int | None = None) -> WireRequest:
    return WireRequest(Endpoint.GET_SETTLEMENTS, scope, Endpoint.GET_SETTLEMENTS.value.template, _query(
        subaccount=subaccount_number(scope), cursor=_cursor(cursor), limit=_limit(limit), ticker=ticker,
        event_ticker=event_ticker, min_ts=_ts(min_ts, "min_ts"), max_ts=_ts(max_ts, "max_ts")))


def build_get_historical_cutoff(scope: AccountScope) -> WireRequest:
    return WireRequest(Endpoint.GET_HISTORICAL_CUTOFF, scope, Endpoint.GET_HISTORICAL_CUTOFF.value.template)


def build_get_exchange_status(scope: AccountScope) -> WireRequest:
    return WireRequest(Endpoint.GET_EXCHANGE_STATUS, scope, Endpoint.GET_EXCHANGE_STATUS.value.template)


def build_get_user_data_timestamp(scope: AccountScope) -> WireRequest:
    return WireRequest(Endpoint.GET_USER_DATA_TIMESTAMP, scope, Endpoint.GET_USER_DATA_TIMESTAMP.value.template)


# ---------------------------------------------------------------------------------------------- parsing


class WireFormatError(ValueError):
    """A response that does not match the documented shape. Never repaired, never defaulted."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WireFormatError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _refuse_constant(name: str) -> Any:
    raise WireFormatError(f"non-finite JSON number {name}")


def _load_object(body: object, where: str) -> dict[str, Any]:
    if not isinstance(body, (bytes, bytearray)):
        raise WireFormatError(f"{where}: response body must be bytes")
    try:
        obj = json.loads(bytes(body).decode("utf-8"), parse_float=Decimal, parse_constant=_refuse_constant,
                         object_pairs_hook=_no_duplicates)
    except WireFormatError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise WireFormatError(f"{where}: not a JSON document ({type(exc).__name__})") from None
    if not isinstance(obj, dict):
        raise WireFormatError(f"{where}: top level is not an object")
    return obj


_COUNT = re.compile(r"-?\d+(\.\d{1,2})?")
_DOLLARS = re.compile(r"-?\d+(\.\d{1,6})?")


class _Fields:
    """Typed, strict access to one JSON object; whatever is not read is kept as `extra`."""

    def __init__(self, obj: object, where: str):
        if not isinstance(obj, dict):
            raise WireFormatError(f"{where} is not an object")
        self.obj, self.where, self.used = obj, where, set()

    def _get(self, key: str, required: bool) -> Any:
        self.used.add(key)
        value = self.obj.get(key)
        if value is None and required:
            raise WireFormatError(f"{self.where}: required field {key!r} is missing")
        return value

    def text(self, key: str, required: bool = True) -> str | None:
        value = self._get(key, required)
        if value is not None and not isinstance(value, str):
            raise WireFormatError(f"{self.where}.{key} must be a string")
        return value

    def integer(self, key: str, required: bool = True) -> int | None:
        value = self._get(key, required)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise WireFormatError(f"{self.where}.{key} must be an integer")
        return value

    def boolean(self, key: str, required: bool = True) -> bool | None:
        value = self._get(key, required)
        if value is not None and not isinstance(value, bool):
            raise WireFormatError(f"{self.where}.{key} must be a boolean")
        return value

    def _decimal(self, key: str, required: bool, pattern: re.Pattern[str], signed: bool) -> Decimal | None:
        value = self._get(key, required)
        if value is None:
            return None
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise WireFormatError(f"{self.where}.{key} must be a fixed-point string, not {type(value).__name__}")
        d = Decimal(value)
        if not signed and d < 0:
            raise WireFormatError(f"{self.where}.{key} must not be negative")
        return d

    def count(self, key: str, required: bool = True, signed: bool = False) -> Decimal | None:
        return self._decimal(key, required, _COUNT, signed)

    def dollars(self, key: str, required: bool = True, signed: bool = False) -> Decimal | None:
        return self._decimal(key, required, _DOLLARS, signed)

    def enum(self, key: str, values: tuple[str, ...], required: bool = True) -> str | None:
        value = self.text(key, required)
        if value is not None and value not in values:
            raise WireFormatError(f"{self.where}.{key} {value!r} is not one of {values}")
        return value

    def time(self, key: str, required: bool = True) -> datetime | None:
        value = self.text(key, required)
        if value is None:
            return None
        try:
            at = datetime.fromisoformat(value)
        except ValueError:
            raise WireFormatError(f"{self.where}.{key} is not an ISO-8601 time") from None
        if at.tzinfo is None or at.utcoffset() is None:
            raise WireFormatError(f"{self.where}.{key} has no time zone")
        return at.astimezone(timezone.utc)

    def array(self, key: str, required: bool = True) -> list[Any] | None:
        value = self._get(key, required)
        if value is not None and not isinstance(value, list):
            raise WireFormatError(f"{self.where}.{key} must be an array")
        return value

    def extra(self) -> Mapping[str, Any]:
        return MappingProxyType({k: v for k, v in self.obj.items() if k not in self.used})


def _extra() -> Any:
    return field(default_factory=lambda: MappingProxyType({}), compare=False, repr=False)


_BOOK_SIDES = ("bid", "ask")
_OUTCOME_SIDES = ("yes", "no")


def _direction(f: _Fields) -> tuple[str, str]:
    outcome, book = f.enum("outcome_side", _OUTCOME_SIDES), f.enum("book_side", _BOOK_SIDES)
    if (outcome == "yes") != (book == "bid"):  # DIR-03: bid is yes, ask is no, always
        raise WireFormatError(f"{f.where}: outcome_side {outcome} contradicts book_side {book}")
    return outcome, book


@dataclass(frozen=True)
class CreateAck:
    order_id: str
    client_order_id: str | None
    fill_count: Decimal
    remaining_count: Decimal
    average_fill_price: Decimal | None
    average_fee_paid: Decimal | None
    ts_ms: int
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True)
class CancelAck:
    order_id: str
    client_order_id: str | None
    reduced_by: Decimal  # the remaining count at cancellation, not the order's whole size (ORD-18)
    ts_ms: int
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True)
class AmendAck:
    order_id: str
    client_order_id: str | None
    remaining_count: Decimal | None  # None: not reported (ORD-22), never "zero remaining"
    fill_count: Decimal | None
    average_fill_price: Decimal | None
    average_fee_paid: Decimal | None
    ts_ms: int
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True)
class DecreaseAck:
    order_id: str
    client_order_id: str | None
    remaining_count: Decimal
    ts_ms: int
    extra: Mapping[str, Any] = _extra()


def parse_create_ack(body: bytes) -> CreateAck:
    f = _Fields(_load_object(body, "create"), "create")
    out = CreateAck(f.text("order_id"), f.text("client_order_id", False), f.count("fill_count"),
                    f.count("remaining_count"), f.dollars("average_fill_price", False),
                    f.dollars("average_fee_paid", False), f.integer("ts_ms"), f.extra())
    if out.fill_count > 0 and out.average_fill_price is None:
        raise WireFormatError("create: a fill was reported without its average price")
    return out


def parse_cancel_ack(body: bytes) -> CancelAck:
    f = _Fields(_load_object(body, "cancel"), "cancel")
    return CancelAck(f.text("order_id"), f.text("client_order_id", False), f.count("reduced_by"), f.integer("ts_ms"),
                     f.extra())


def parse_amend_ack(body: bytes) -> AmendAck:
    f = _Fields(_load_object(body, "amend"), "amend")
    return AmendAck(f.text("order_id"), f.text("client_order_id", False), f.count("remaining_count", False),
                    f.count("fill_count", False), f.dollars("average_fill_price", False),
                    f.dollars("average_fee_paid", False), f.integer("ts_ms"), f.extra())


def parse_decrease_ack(body: bytes) -> DecreaseAck:
    f = _Fields(_load_object(body, "decrease"), "decrease")
    return DecreaseAck(f.text("order_id"), f.text("client_order_id", False), f.count("remaining_count"),
                       f.integer("ts_ms"), f.extra())


@dataclass(frozen=True)
class VenueOrder:
    order_id: str
    user_id: str
    client_order_id: str
    ticker: str
    outcome_side: str
    book_side: str
    type: str
    status: str
    yes_price: Decimal
    no_price: Decimal
    fill_count: Decimal
    remaining_count: Decimal
    initial_count: Decimal
    taker_fees: Decimal
    maker_fees: Decimal
    taker_fill_cost: Decimal
    maker_fill_cost: Decimal
    expiration_time: datetime | None
    created_time: datetime | None
    last_update_time: datetime | None
    self_trade_prevention_type: str | None
    order_group_id: str | None
    cancel_order_on_pause: bool | None
    subaccount_number: int | None
    exchange_index: int | None
    extra: Mapping[str, Any] = _extra()


def _order(obj: object, where: str) -> VenueOrder:
    f = _Fields(obj, where)
    order_id, user_id, client_id, ticker = f.text("order_id"), f.text("user_id"), f.text("client_order_id"), f.text("ticker")
    outcome, book = _direction(f)
    return VenueOrder(
        order_id, user_id, client_id, ticker, outcome, book, f.enum("type", ("limit", "market")),
        f.enum("status", c.ORDER_STATUSES), f.dollars("yes_price_dollars"), f.dollars("no_price_dollars"),
        f.count("fill_count_fp"), f.count("remaining_count_fp"), f.count("initial_count_fp"),
        f.dollars("taker_fees_dollars"), f.dollars("maker_fees_dollars"), f.dollars("taker_fill_cost_dollars"),
        f.dollars("maker_fill_cost_dollars"), f.time("expiration_time", False), f.time("created_time", False),
        f.time("last_update_time", False), f.enum("self_trade_prevention_type", ("taker_at_cross", "maker"), False),
        f.text("order_group_id", False), f.boolean("cancel_order_on_pause", False), f.integer("subaccount_number", False),
        f.integer("exchange_index", False), f.extra())


@dataclass(frozen=True)
class Page:
    """One page of a cursor-paginated list. `cursor` is None when there is no next page (ACC-09)."""

    items: tuple[Any, ...]
    cursor: str | None
    extra: Mapping[str, Any] = _extra()


def _page(body: bytes, where: str, key: str, item: Callable[[object, str], Any], cursor_required: bool) -> Page:
    f = _Fields(_load_object(body, where), where)
    raw = f.array(key)
    if cursor_required and "cursor" not in f.obj:
        raise WireFormatError(f"{where}: required field 'cursor' is missing")
    cursor = f.text("cursor", False)
    return Page(tuple(item(x, f"{where}.{key}[{i}]") for i, x in enumerate(raw)), cursor or None, f.extra())


def parse_order(body: bytes) -> VenueOrder:
    f = _Fields(_load_object(body, "order"), "order")
    order = f.obj.get("order")
    if order is None:
        raise WireFormatError("order: required field 'order' is missing")
    return _order(order, "order.order")


def parse_orders_page(body: bytes) -> Page:
    """`GET /portfolio/orders` and `GET /historical/orders` (same shape)."""
    return _page(body, "orders", "orders", _order, cursor_required=True)


@dataclass(frozen=True)
class VenueFill:
    fill_id: str
    order_id: str
    ticker: str
    outcome_side: str
    book_side: str
    count: Decimal
    yes_price: Decimal
    no_price: Decimal
    is_taker: bool
    fee_cost: Decimal
    exchange_index: int
    created_time: datetime | None
    subaccount_number: int | None
    extra: Mapping[str, Any] = _extra()


def _fill(obj: object, where: str) -> VenueFill:
    f = _Fields(obj, where)
    fill_id, trade_id = f.text("fill_id"), f.text("trade_id")
    order_id, ticker, market_ticker = f.text("order_id"), f.text("ticker"), f.text("market_ticker")
    if fill_id != trade_id or ticker != market_ticker:  # ACC-15: documented as the same values
        raise WireFormatError(f"{where}: legacy id fields disagree with their replacements")
    outcome, book = _direction(f)
    return VenueFill(fill_id, order_id, ticker, outcome, book, f.count("count_fp"), f.dollars("yes_price_dollars"),
                     f.dollars("no_price_dollars"), f.boolean("is_taker"), f.dollars("fee_cost"), f.integer("exchange_index"),
                     f.time("created_time", False), f.integer("subaccount_number", False), f.extra())


def parse_fills_page(body: bytes) -> Page:
    """`GET /portfolio/fills` and `GET /historical/fills` (same shape)."""
    return _page(body, "fills", "fills", _fill, cursor_required=True)


@dataclass(frozen=True)
class MarketPosition:
    ticker: str
    exchange_index: int
    position: Decimal  # signed: negative is NO contracts (ACC-08)
    total_traded: Decimal
    market_exposure: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    last_updated: datetime
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True)
class EventPosition:
    event_ticker: str
    total_cost: Decimal
    total_cost_shares: Decimal
    event_exposure: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True)
class PositionsPage:
    market_positions: tuple[MarketPosition, ...]
    event_positions: tuple[EventPosition, ...]
    cursor: str | None
    extra: Mapping[str, Any] = _extra()


def _market_position(obj: object, where: str) -> MarketPosition:
    f = _Fields(obj, where)
    return MarketPosition(f.text("ticker"), f.integer("exchange_index"), f.count("position_fp", signed=True),
                          f.dollars("total_traded_dollars"), f.dollars("market_exposure_dollars", signed=True),
                          f.dollars("realized_pnl_dollars", signed=True), f.dollars("fees_paid_dollars"),
                          f.time("last_updated_ts"), f.extra())


def _event_position(obj: object, where: str) -> EventPosition:
    f = _Fields(obj, where)
    return EventPosition(f.text("event_ticker"), f.dollars("total_cost_dollars"), f.count("total_cost_shares_fp"),
                         f.dollars("event_exposure_dollars", signed=True), f.dollars("realized_pnl_dollars", signed=True),
                         f.dollars("fees_paid_dollars"), f.extra())


def parse_positions_page(body: bytes) -> PositionsPage:
    """`GET /portfolio/positions` and `GET /historical/positions` (same shape)."""
    f = _Fields(_load_object(body, "positions"), "positions")
    markets, events = f.array("market_positions"), f.array("event_positions")
    cursor = f.text("cursor", False)
    return PositionsPage(tuple(_market_position(x, f"positions.market_positions[{i}]") for i, x in enumerate(markets)),
                         tuple(_event_position(x, f"positions.event_positions[{i}]") for i, x in enumerate(events)),
                         cursor or None, f.extra())


@dataclass(frozen=True)
class VenueSettlement:
    ticker: str
    event_ticker: str
    exchange_index: int
    market_result: str
    yes_count: Decimal
    yes_total_cost: Decimal
    no_count: Decimal
    no_total_cost: Decimal
    revenue_cents: int  # integer cents (ACC-13)
    settled_time: datetime
    fee_cost: Decimal  # fixed-point dollars (ACC-13)
    value_cents: int | None
    extra: Mapping[str, Any] = _extra()


def _settlement(obj: object, where: str) -> VenueSettlement:
    f = _Fields(obj, where)
    return VenueSettlement(f.text("ticker"), f.text("event_ticker"), f.integer("exchange_index"),
                           f.enum("market_result", ("yes", "no", "scalar")), f.count("yes_count_fp"),
                           f.dollars("yes_total_cost_dollars"), f.count("no_count_fp"),
                           f.dollars("no_total_cost_dollars"), f.integer("revenue"), f.time("settled_time"),
                           f.dollars("fee_cost"), f.integer("value", False), f.extra())


def parse_settlements_page(body: bytes) -> Page:
    return _page(body, "settlements", "settlements", _settlement, cursor_required=False)


@dataclass(frozen=True)
class Balance:
    """`balance_cents` and `balance_dollars` are both the venue's *available* balance; whether resting-order
    collateral is already excluded is UNKNOWN (ACC-02), so a caller must not assume either way."""

    balance_cents: int
    balance_dollars: Decimal
    portfolio_value_cents: int
    updated_ts: int  # unit UNKNOWN (ACC-03): kept as the raw integer, never converted
    breakdown: tuple[tuple[int, Decimal], ...] | None  # (exchange_index, dollars); None when not reported
    extra: Mapping[str, Any] = _extra()


def parse_balance(body: bytes) -> Balance:
    f = _Fields(_load_object(body, "balance"), "balance")
    cents, dollars = f.integer("balance"), f.dollars("balance_dollars", signed=True)
    value, updated = f.integer("portfolio_value"), f.integer("updated_ts")
    raw = f.array("balance_breakdown", False)
    breakdown = None
    if raw is not None:
        rows = []
        for i, item in enumerate(raw):
            g = _Fields(item, f"balance.balance_breakdown[{i}]")
            rows.append((g.integer("exchange_index"), g.dollars("balance", signed=True)))
        breakdown = tuple(rows)
    return Balance(cents, dollars, value, updated, breakdown, f.extra())


@dataclass(frozen=True)
class HistoricalCutoff:
    market_settled: datetime
    trades_created: datetime
    orders_updated: datetime
    market_positions_last_updated: datetime | None  # a backfill horizon, not a visibility boundary (ACC-10)
    extra: Mapping[str, Any] = _extra()


def parse_historical_cutoff(body: bytes) -> HistoricalCutoff:
    f = _Fields(_load_object(body, "cutoff"), "cutoff")
    return HistoricalCutoff(f.time("market_settled_ts"), f.time("trades_created_ts"), f.time("orders_updated_ts"),
                            f.time("market_positions_last_updated_ts", False), f.extra())


@dataclass(frozen=True)
class ExchangeStatus:
    exchange_active: bool
    trading_active: bool  # top level reflects exchange index 0 only (PAU-04)
    index_statuses: tuple[tuple[int, bool, bool], ...] | None  # (exchange_index, exchange_active, trading_active)
    extra: Mapping[str, Any] = _extra()


def parse_exchange_status(body: bytes) -> ExchangeStatus:
    f = _Fields(_load_object(body, "exchange_status"), "exchange_status")
    exchange_active, trading_active = f.boolean("exchange_active"), f.boolean("trading_active")
    raw = f.array("exchange_index_statuses", False)
    statuses = None
    if raw is not None:
        rows = []
        for i, item in enumerate(raw):
            g = _Fields(item, f"exchange_status.exchange_index_statuses[{i}]")
            g.text("description")
            rows.append((g.integer("exchange_index"), g.boolean("exchange_active"), g.boolean("trading_active")))
        statuses = tuple(rows)
    return ExchangeStatus(exchange_active, trading_active, statuses, f.extra())


def parse_user_data_timestamp(body: bytes) -> datetime:
    f = _Fields(_load_object(body, "user_data_timestamp"), "user_data_timestamp")
    return f.time("as_of_time")


@dataclass(frozen=True)
class VenueError:
    """A tolerant reading of an error body. Every field may be None: error bodies vary (RL-06 uses `error`)."""

    code: str | None
    message: str | None
    details: str | None
    error: str | None


def parse_error(body: bytes) -> VenueError:
    try:
        obj = _load_object(body, "error")
    except WireFormatError:
        return VenueError(None, None, None, None)

    def text(key: str) -> str | None:
        value = obj.get(key)
        return value if isinstance(value, str) else None

    return VenueError(text("code"), text("message"), text("details"), text("error"))
