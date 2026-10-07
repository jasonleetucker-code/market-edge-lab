"""Kalshi ordinary event-order conformance profile `kalshi-ordinary-v0` (#160 package B). Pure data.

Mirrors `docs/execution/KALSHI_CONFORMANCE.md`; `tests/execution/test_conformance_kalshi_pack.py` pins the two
together. Every fact names its value, its evidence class, the official page it came from and when it was read.

Evidence classes, weakest first:
- DOCUMENTED: read on an official Kalshi documentation page.
- FIXTURE_TESTED: also exercised offline by our code against a documentation-example fixture.
- DEMO_OBSERVED / PRODUCTION_READ_VERIFIED: seen on the venue. Neither can exist yet: no environment but
  FIXTURE is authorized (`model.AUTHORIZED_ENVIRONMENTS`).

A fact whose support is UNKNOWN or UNSUPPORTED is never used to permit an action. Conflicting or unclear
documentation stays UNKNOWN; it is never resolved in favour of more trading.

Some facts live beside the code that uses them, because the no-execution invariant reserves their vocabulary to
one file (ADR 0043): signing algorithms in `signer.py` (`SIGNING_FACTS`), the auth header names in
`transport.py` (`AUTH_HEADER_FACTS`) and the order endpoint paths in `kalshi_wire.py` (`ENDPOINT_FACTS`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .model import Environment, ExactValueError, Grid, TimeInForce, exact_decimal

PROFILE_VERSION = "kalshi-ordinary-v0"
RETRIEVED = "2026-10-07"
DOCS = "https://docs.kalshi.com"


class Evidence(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    FIXTURE_TESTED = "FIXTURE_TESTED"
    DEMO_OBSERVED = "DEMO_OBSERVED"
    PRODUCTION_READ_VERIFIED = "PRODUCTION_READ_VERIFIED"


# The classes that can honestly exist today: nothing has been observed on the venue.
EVIDENCE_POSSIBLE_NOW = frozenset({Evidence.DOCUMENTED, Evidence.FIXTURE_TESTED})


class Support(str, Enum):
    SUPPORTED = "SUPPORTED"  # the profile relies on it
    UNSUPPORTED = "UNSUPPORTED"  # documented, deliberately not used by this profile; requests needing it are refused
    UNKNOWN = "UNKNOWN"  # unclear, conflicting or undocumented: never relied on
    UNVERIFIED_FETCH_FAILED = "UNVERIFIED_FETCH_FAILED"  # the page could not be read


@dataclass(frozen=True)
class Fact:
    """One conformance fact. `value` is the exact documented value (text, a number or a tuple of them)."""

    id: str
    value: Any
    evidence: Evidence
    source: str
    retrieved: str = RETRIEVED
    support: Support = Support.SUPPORTED
    fixture: str | None = None  # FIXTURE_TESTED only: the fixture under tests/fixtures/kalshi_exec/

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]{2,4}-\d{2}", self.id):
            raise ValueError(f"fact id {self.id!r} must look like ABC-01")
        if not isinstance(self.evidence, Evidence) or not isinstance(self.support, Support):
            raise ValueError(f"{self.id}: evidence and support must be enum members")
        if not self.source.startswith(DOCS + "/"):
            raise ValueError(f"{self.id}: every fact cites an official docs.kalshi.com page")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.retrieved):
            raise ValueError(f"{self.id}: retrieved must be an ISO date")
        if (self.evidence is Evidence.FIXTURE_TESTED) != (self.fixture is not None):
            raise ValueError(f"{self.id}: a fixture is named for, and only for, FIXTURE_TESTED facts")

    def display(self) -> str:
        """The value as written in the conformance doc's Value column."""
        return display_value(self.value)


def display_value(value: Any) -> str:
    if isinstance(value, tuple):
        return ", ".join(display_value(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return f"`{value}`"


def _p(page: str) -> str:
    return f"{DOCS}/{page}"


ENVIRONMENTS = _p("getting_started/api_environments")
DEMO_ENV = _p("getting_started/demo_env")
FIXED_POINT = _p("getting_started/fixed_point_migration")
FEE_ROUNDING = _p("getting_started/fee_rounding")
HISTORICAL = _p("getting_started/historical_data")
RATE_LIMITS = _p("getting_started/rate_limits")
SHARDING = _p("getting_started/exchange_sharding")
PAGINATION = _p("getting_started/pagination")
SUBACCOUNTS = _p("getting_started/subaccounts")
ORDER_GROUPS = _p("getting_started/order_groups")
PAUSES = _p("getting_started/maintenance_and_pauses")
SETTLEMENT = _p("getting_started/market_settlement")
SETTLEMENT_BOUNDS = _p("getting_started/settlement_bounds")
ORDER_DIRECTION = _p("getting_started/order_direction")
GET_MARKET = _p("api-reference/market/get-market")
GET_BALANCE = _p("api-reference/portfolio/get-balance")
GET_POSITIONS = _p("api-reference/portfolio/get-positions")
GET_FILLS = _p("api-reference/portfolio/get-fills")
GET_SETTLEMENTS = _p("api-reference/portfolio/get-settlements")
HISTORICAL_CUTOFF = _p("api-reference/historical/get-historical-cutoff-timestamps")
EXCHANGE_STATUS = _p("api-reference/exchange/get-exchange-status")
USER_DATA_TS = _p("api-reference/exchange/get-user-data-timestamp")
CHANGELOG = _p("changelog/index")

D = Evidence.DOCUMENTED

# ---------------------------------------------------------------------------------------------- the profile

PROFILE_FACTS: tuple[Fact, ...] = (
    # Environments and hosts
    Fact("ENV-01", ("external-api.kalshi.com", "api.elections.kalshi.com"), D, ENVIRONMENTS),
    Fact("ENV-02", ("external-api.demo.kalshi.co", "demo-api.kalshi.co"), D, ENVIRONMENTS),
    Fact("ENV-03", "/trade-api/v2", D, ENVIRONMENTS),
    Fact("ENV-04", "credentials are not shared between production and demo", D, ENVIRONMENTS),
    Fact("ENV-05", "demo prices and behaviour may not reflect real markets", D, DEMO_ENV),
    # Prices and quantities
    Fact("PX-01", "market.price_ranges [{start, end, step}] is the source of truth; off-grid prices are rejected",
         D, FIXED_POINT),
    Fact("PX-02", "whole-cent prices are valid in every price level structure", D, FIXED_POINT),
    Fact("PX-03", Decimal("0.0001"), D, FIXED_POINT),  # finest documented tick
    Fact("PX-04", "request prices accept 2-4 decimal places; responses emit up to 6", D, FIXED_POINT),
    Fact("PX-05", "do not key pricing logic off price_level_structure", D, FIXED_POINT),
    Fact("QTY-01", Decimal("0.01"), D, FIXED_POINT),  # minimum contract granularity
    Fact("QTY-02", "counts accept 0-2 decimal places on input; responses always emit 2", D, FIXED_POINT),
    Fact("QTY-03", "fractional trading is supported on every active market", D, CHANGELOG),
    Fact("QTY-04", "maximum order count", D, FIXED_POINT, support=Support.UNKNOWN),
    # Markets
    Fact("MKT-01", ("binary", "scalar"), D, GET_MARKET),
    Fact("MKT-02", ("initialized", "inactive", "active", "closed", "determined", "disputed", "amended", "finalized"),
         D, GET_MARKET),
    Fact("MKT-03", ("default", "floor"), D, GET_MARKET),
    Fact("MKT-04", "settlement floors are not live yet; launch timeline TBA", D, SETTLEMENT_BOUNDS),
    Fact("MKT-05", "market exchange_index is the authoritative shard", D, SHARDING),
    Fact("MKT-06", "scalar markets", D, GET_MARKET, support=Support.UNSUPPORTED),
    Fact("MKT-07", "floor settlement-bounds markets", D, SETTLEMENT_BOUNDS, support=Support.UNSUPPORTED),
    # Direction
    Fact("DIR-01", "bid = buy YES; ask = sell YES; the price is always the YES price", D, ORDER_DIRECTION),
    Fact("DIR-02", ("buy yes -> bid", "sell no -> bid", "buy no -> ask", "sell yes -> ask"), D, ORDER_DIRECTION),
    Fact("DIR-03", "bid = outcome_side yes; ask = outcome_side no", D, ORDER_DIRECTION),
    Fact("DIR-04", "legacy side/action are not removed before May 14, 2026 (reference) vs not before May 28, 2026 "
         "(guide)", D,
         ORDER_DIRECTION, support=Support.UNKNOWN),
    # Account
    Fact("ACC-01", "balance is the available balance in integer cents; balance_dollars is fixed-point dollars",
         D, GET_BALANCE),
    Fact("ACC-02", "whether the available balance already excludes resting-order collateral", D, GET_BALANCE,
         support=Support.UNKNOWN),
    Fact("ACC-03", "updated_ts unit (seconds or milliseconds)", D, GET_BALANCE, support=Support.UNKNOWN),
    Fact("ACC-04", ("direct: 0.0001", "non-direct: 0.01"), D, FEE_ROUNDING),  # balance precision in dollars
    Fact("ACC-05", "trade fee = ceil to 0.000001; rounding fee and a per-order rebate accumulator", D, FEE_ROUNDING),
    Fact("ACC-06", ("unsettled", "settled", "all"), D, GET_POSITIONS),
    Fact("ACC-07", "unsettled", D, GET_POSITIONS),  # positions default
    Fact("ACC-08", "position_fp: negative = NO contracts, positive = YES contracts", D, GET_POSITIONS),
    Fact("ACC-09", "an empty or absent cursor means there is no next page", D, GET_POSITIONS),
    Fact("ACC-10", ("market_settled_ts", "trades_created_ts", "orders_updated_ts",
                    "market_positions_last_updated_ts"), D, HISTORICAL_CUTOFF),
    Fact("ACC-11", "page live positions first, then historical; deduplicate by subaccount and ticker", D, HISTORICAL),
    Fact("ACC-12", "no historical endpoint has the settlement-record fields", D, HISTORICAL),
    Fact("ACC-13", "settlement revenue and value are integer cents; fee_cost is fixed-point dollars", D,
         GET_SETTLEMENTS),
    Fact("ACC-14", ("yes", "no", "scalar"), D, GET_SETTLEMENTS),  # settlement market_result
    Fact("ACC-15", "fill_id equals trade_id; ticker equals market_ticker", D, GET_FILLS),
    Fact("ACC-16", "user data is validated with a short delay; as_of_time is approximate", D, USER_DATA_TS),
    Fact("ACC-17", "subaccount balances are local to an exchange instance", D, SHARDING),
    # Subaccounts
    Fact("SUB-01", (0, 63), D, SUBACCOUNTS),  # 0 primary, 1-63 numbered
    Fact("SUB-02", "a restricted key acts on its locked subaccount; naming another is rejected", D, SUBACCOUNTS),
    Fact("SUB-03", "an omitted subaccount means all subaccounts on order lists, fills and settlements, but 0 on "
         "balance, positions and order writes", D, GET_FILLS),
    # Pagination
    Fact("PAG-01", (1, 1000, 100), D, GET_FILLS),  # limit min, max, default on account list endpoints
    Fact("PAG-02", "the pagination guide says limit is typically 1-100", D, PAGINATION, support=Support.UNKNOWN),
    # Rate limits
    Fact("RL-01", 10, D, RATE_LIMITS),  # default token cost
    Fact("RL-02", "independent Read and Write token buckets; Write covers placement, amends, cancels, order groups",
         D, RATE_LIMITS),
    Fact("RL-03", ("basic 200/100", "advanced 300/300", "expert 600/600", "premier 1200/1200",
                   "paragon 2400/2400", "prime 4800/4800", "prestige 12000/9600"), D, RATE_LIMITS),
    Fact("RL-04", "basic write and read above advanced hold 1 s; basic/advanced read and write above basic hold 3 s",
         D, RATE_LIMITS),
    Fact("RL-05", "explicit exchange_index >= 1 bills that shard's Write bucket; 0 bills the unscoped bucket", D,
         RATE_LIMITS),
    Fact("RL-06", '429 body {"error": "too many requests"}; no Retry-After header', D, RATE_LIMITS),
    Fact("RL-07", "single-request token costs other than the default (endpoint_costs not read)", D, RATE_LIMITS,
         support=Support.UNKNOWN),
    Fact("RL-08", "this account's tier (account limits not read)", D, RATE_LIMITS, support=Support.UNKNOWN),
    # Pauses, settlement, shards
    Fact("PAU-01", "trading pause every Thursday 03:00-05:00 ET", D, PAUSES),
    Fact("PAU-02", "trading pause: no place or amend, cancel allowed; exchange pause: no cancel either", D, PAUSES),
    Fact("PAU-03", "resting orders stay on the book during a pause unless cancel_order_on_pause", D, PAUSES),
    Fact("PAU-04", ("exchange_active", "trading_active"), D, EXCHANGE_STATUS),
    Fact("SET-01", "winning contracts pay 1 dollar; only net positions are settled", D, SETTLEMENT),
    Fact("SET-02", "settlement timing varies by market type, source availability and review", D, SETTLEMENT),
    Fact("SET-03", "a raised settlement floor cancels resting orders at or below it", D, SETTLEMENT_BOUNDS),
    Fact("SET-04", "a lowered floor can cancel resting orders in other markets of the subaccount", D,
         SETTLEMENT_BOUNDS),
    Fact("SHD-01", "collateral must be preallocated on the shard before placing an order", D, SHARDING),
    Fact("SHD-02", "an order id alone cannot identify the shard", D, SHARDING),
)

# ---------------------------------------------------------------------------------------------- helpers

API_PATH_PREFIX = "/trade-api/v2"

# Hosts per environment. FIXTURE uses a reserved `.invalid` name (RFC 2606) that can never resolve, so even a
# real network opener cannot reach a venue from FIXTURE. DEMO and PRODUCTION are listed so that a host check
# exists, but their egress is refused by `model.environment_authorized` (no transport may use them).
_HOSTS: Mapping[Environment, tuple[str, ...]] = MappingProxyType({
    Environment.FIXTURE: ("fixture.invalid",),
    Environment.DEMO: ("external-api.demo.kalshi.co", "demo-api.kalshi.co"),
    Environment.PRODUCTION: ("external-api.kalshi.com", "api.elections.kalshi.com"),
})  # read-only: no caller can rewrite FIXTURE's `.invalid` host (tamper invariant: only this file assigns it)


def hosts_for(environment: Environment) -> tuple[str, ...]:
    """The REST hosts allowed for `environment`; the first is the recommended one."""
    if not isinstance(environment, Environment):
        raise ValueError("environment must be an Environment")
    return _HOSTS[environment]


SUPPORTED_TIME_IN_FORCE = frozenset(TimeInForce)  # ORD-08 (kalshi_wire): all three documented values
REDUCE_ONLY_TIME_IN_FORCE = frozenset({TimeInForce.IMMEDIATE_OR_CANCEL})  # create-order: reduce_only needs IOC
ORDER_STATUSES = ("resting", "canceled", "executed")
POSITION_SETTLEMENT_STATUSES = ("unsettled", "settled", "all")
SUBACCOUNT_MIN, SUBACCOUNT_MAX = 0, 63
PAGE_LIMIT_MAX = 100  # PAG-01 allows 1000 but PAG-02 says 100: the smaller satisfies both readings
DEFAULT_TOKEN_COST = 10
PRICE_REQUEST_DECIMALS = 4
COUNT_DECIMALS = 2
QUANTITY_STEP = Decimal("0.01")

# Profile decisions: our choices, not venue facts. Documented in the conformance doc's decision table.
SELF_TRADE_PREVENTION = "taker_at_cross"  # cancel our incoming order, never silently cancel our resting one
CANCEL_ORDER_ON_PAUSE = True  # a paused book never keeps our resting risk alive

# RL-03 / RL-04: (read refill per second, write refill per second, read capacity seconds, write capacity seconds).
RATE_TIERS: Mapping[str, tuple[int, int, int, int]] = MappingProxyType({
    "basic": (200, 100, 3, 1),
    "advanced": (300, 300, 3, 3),
    "expert": (600, 600, 1, 3),
    "premier": (1200, 1200, 1, 3),
    "paragon": (2400, 2400, 1, 3),
    "prime": (4800, 4800, 1, 3),
    "prestige": (12000, 9600, 1, 3),
})
DEFAULT_TIER = "basic"  # RL-08: the account's tier is unknown, so the smallest documented budget

# Marker: there is no default price grid. The grid comes from the market record's `price_ranges` (PX-01).
PRICE_GRID_FROM_MARKET_RECORD = "market.price_ranges"


class UnsupportedByProfile(ValueError):
    """The request needs a market, product or option this profile does not support."""


def quantity_grid(maximum: object) -> Grid:
    """The contract-count grid (QTY-01: 0.01 granularity). The maximum is not documented (QTY-04), so the caller
    supplies one from its risk policy; there is no default."""
    top = exact_decimal(maximum, name="maximum quantity")
    return Grid(step=QUANTITY_STEP, minimum=QUANTITY_STEP, maximum=top)


_DOLLARS = re.compile(r"\d+(\.\d{1,6})?")


def _band(raw: object) -> Grid:
    if not isinstance(raw, Mapping):
        raise UnsupportedByProfile("a price range is not an object")
    values = {}
    for key in ("start", "end", "step"):
        text = raw.get(key)
        if not isinstance(text, str) or not _DOLLARS.fullmatch(text):
            raise UnsupportedByProfile(f"price range {key} is not a fixed-point dollar string: {text!r}")
        values[key] = Decimal(text)
    if not Decimal(0) <= values["start"] < values["end"] <= Decimal(1):
        raise UnsupportedByProfile("a price range must lie within [0, 1] with start < end")
    try:
        return Grid(step=values["step"], minimum=values["start"], maximum=values["end"])
    except ExactValueError as exc:
        raise UnsupportedByProfile(f"price range is not a valid grid: {exc}") from None


@dataclass(frozen=True)
class MarketTradingProfile:
    """What the profile needs from one market record before an order can be built for it."""

    ticker: str
    exchange_index: int
    price_bands: tuple[Grid, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.ticker, str) or not self.ticker:
            raise UnsupportedByProfile("a market profile needs a ticker")
        if isinstance(self.exchange_index, bool) or not isinstance(self.exchange_index, int) or self.exchange_index < 0:
            raise UnsupportedByProfile("a market profile needs an explicit non-negative shard")
        if not isinstance(self.price_bands, tuple) or not self.price_bands \
                or not all(isinstance(b, Grid) for b in self.price_bands):
            raise UnsupportedByProfile("a market profile needs its price bands; the grid is never assumed")

    @classmethod
    def from_market_record(cls, market: Mapping[str, Any]) -> "MarketTradingProfile":
        """Refuses anything outside the ordinary binary profile: a scalar or floor market, a market that is not
        active, an unknown shard or a missing price grid. Missing is never defaulted."""
        if not isinstance(market, Mapping):
            raise UnsupportedByProfile("market record is not an object")
        ticker = market.get("ticker")
        if not isinstance(ticker, str) or not ticker:
            raise UnsupportedByProfile("market record has no ticker")
        if market.get("market_type") != "binary":
            raise UnsupportedByProfile(f"{ticker}: market_type {market.get('market_type')!r} is not binary")
        if market.get("status") != "active":
            raise UnsupportedByProfile(f"{ticker}: status {market.get('status')!r} is not active")
        if market.get("settlement_bounds_type") != "default":
            raise UnsupportedByProfile(f"{ticker}: settlement_bounds_type {market.get('settlement_bounds_type')!r}"
                                       " is not default")
        index = market.get("exchange_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise UnsupportedByProfile(f"{ticker}: exchange_index {index!r} is not a known shard")
        ranges = market.get("price_ranges")
        if not isinstance(ranges, list) or not ranges:
            raise UnsupportedByProfile(f"{ticker}: no price_ranges; the grid is never assumed")
        return cls(ticker=ticker, exchange_index=index, price_bands=tuple(_band(r) for r in ranges))

    def check_yes_price(self, price: object) -> Decimal:
        """`price` if it lies on one of the market's bands and strictly between 0 and 1 dollar."""
        p = exact_decimal(price, name="yes price")
        if not Decimal(0) < p < Decimal(1):
            raise UnsupportedByProfile(f"yes price {p} must be strictly between 0 and 1")
        for band in self.price_bands:
            if band.minimum <= p <= band.maximum and p % band.step == 0:
                return p
        raise UnsupportedByProfile(f"yes price {p} is off the market's price grid")
