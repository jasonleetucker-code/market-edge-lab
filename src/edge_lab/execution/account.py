"""Complete account reads and reconciliation (#160 package G, ADR 0043). Offline: FIXTURE only.

`reconcile_account(plan, send, clock=..., local_orders=...)` reads balances, positions, orders, fills and settlements
for every subaccount of an `AccountReadPlan`, in the live and the historical tier. It returns an
`AccountReconciliation`: a manifest of exactly what was read, a COMPLETE, PARTIAL or FAILED status with reasons, and,
per subaccount, the inputs for `reservations.record_account_snapshot`.

**No capability is imported.** Only the transport may import the signer, and nothing imports the transport yet. The
caller supplies `send(WireRequest) -> reply`, where the reply has `outcome` (equal to "OK" on success, as
`transport.Outcome.OK` is), `status` and `body`. In production that is
`lambda r: transport.send(r, priority=Priority.PROTECTIVE)`; tests pass a fixture function. `check_read_request`
refuses every request before it is handed to `send` unless it is an allowlisted GET whose subaccount is explicit.
Nothing in this module builds a write, a cancel or a flatten.

**Read algorithm.**
1. `as_of` (user-data timestamp, ACC-16) and the historical cutoff (ACC-10) are read first.
2. Per subaccount, sample 0 reads the live tier: balance, positions (`settlement_status=all`, because the default
   `unsettled` would omit settled rows, ACC-07), orders, fills and settlements. Then the historical tier: positions,
   orders and fills. Live is read before historical (ACC-11), so a record that moves live -> historical during
   the read is seen at least once.
3. **Bounded resampling.** The live tier is volatile; the historical tier is archival. The live tier is read again
   until two consecutive samples agree exactly (every record equal), or `max_resamples` extra samples have been
   read; then the subaccount is UNSTABLE. A sample whose update stamps go backwards is a STALE_UPDATE.
4. `as_of` and the cutoff are read again at the end. Records change tier only when the cutoff advances, so an
   unchanged cutoff means the partition held still. An advanced cutoff means a record may have moved after the
   historical read: the historical tier is read once more and the cutoff a third time. A cutoff that moved again,
   or one that went backwards, leaves the partition unproven (PARTIAL).
5. Within a stream and across tiers, records are deduplicated by venue identity (order id, fill id, ticker).
   Identical duplicates collapse and are counted. Conflicting duplicates are problems and make that data unknown.

**Every way it refuses or degrades** (problem codes): a send that fails, raises, is throttled or is denied
(STREAM_INCOMPLETE with the reason, ACCESS_DENIED for 401/403); a malformed page (MALFORMED_PAGE); CURSOR_LOOP;
PAGE_BUDGET_EXHAUSTED, REQUEST_BUDGET_EXHAUSTED, DEADLINE_EXCEEDED; a record of another subaccount
(UNKNOWN_SUBACCOUNT_RECORD); CONFLICTING_DUPLICATE; UNSTABLE; STALE_UPDATE; STALE_USER_DATA, USER_DATA_AS_OF_IN_FUTURE,
USER_DATA_AS_OF_REGRESSED, USER_DATA_AS_OF_UNAVAILABLE; CUTOFF_UNAVAILABLE, CUTOFF_REGRESSED, CUTOFF_MOVING;
TIER_PARTITION_VIOLATION; RECORD_VANISHED (an order or fill seen live that is in neither tier at the end);
UNIT_MISMATCH (balance cents vs dollars, settlement revenue vs count); ATTRIBUTION_MISMATCH;
SHARDS_UNKNOWN, SHARDS_NOT_ENUMERATED (a balance or any record off shard 0); LOCAL_SCOPE_ALIAS;
ENDPOINT_NOT_IN_PLAN. Any problem makes the result PARTIAL; no completed subaccount stream makes
it FAILED. A malformed plan, a write request or a missing subaccount parameter raises `AccountReadError`.

**Missing is not zero.** Every result field passes one gate (`_finalize`). A live-tier field (balance, positions,
orders, open orders, fills, settlements) is set only when its stream is complete, conflict-free, STABLE, fresh and on
enumerated shards; a historical field only when its stream is complete, conflict-free, on enumerated shards and the
partition is proven. Otherwise it is None (unknown), never an empty or partial tuple: `open_orders=None` is "not
known", never "no resting orders". In the snapshot inputs, cash is additionally None unless the whole result is
COMPLETE, and its basis is UNKNOWN while ACC-02 is UNKNOWN (today, always), so `reservations` allows no new risk.
Every resting venue order that is not attributed to a local attempt, or whose attribution does not hold, is an
`ExternalOrder`: it never disappears, and its cash is unknown (blocking) or the full notional under
`ExternalCashPolicy.FULL_NOTIONAL`.

**Attribution.** A unique provider order id is the identity, and the venue's client order id must be one the attempt
carries (`LocalOrder.client_ids`: the intent's, or the amended `current_client_order_id`). Without a provider id
match, the client order id must name exactly one unacknowledged attempt. Anything else stays external.

**Gaps, not zeros.** Settlements of markets settled before the cutoff have no historical endpoint (ACC-12). Each
settlement record is read on its own: one with every required field goes through the strict `kalshi_wire` parser;
one with required fields missing is kept with the fields it has (`missing` names the rest), every present field
held to the strict rules (and revenue never negative). An archived position with no settlement record is a
HISTORICAL_POSITION_ONLY record. Both are listed in `gaps`.

**Limitations.** Reads are not one atomic snapshot: agreement of two samples is evidence of a quiet account, not
proof. The resting-collateral meaning of the balance (ACC-02) and the `updated_ts` unit (ACC-03) are UNKNOWN; only
the ordering of `updated_ts` is used. Shards are not enumerated: whether a read without `exchange_index` covers
every shard is not documented, so a balance on any shard but 0, no `balance_breakdown`, or any record whose
`exchange_index` is not 0 is PARTIAL. An amended price is not modelled: an amended order whose price differs from
the intent's limit is kept external. `local_orders_from_journal` cannot know an amended client order id (the journal
does not record one), so it leaves `current_client_order_id` None.
Legacy side/action fields are never read (DIR-04), so an external order's outcome side and action are unknown.
Records without a `subaccount_number` are accepted on the strength of the explicit request parameter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from . import conformance as c
from . import kalshi_wire as w
from .kalshi_wire import Endpoint, HttpMethod, WireFormatError, WireRequest
from .model import (MAX_COST_PER_CONTRACT, MAX_DIGITS, AccountScope, Action, IntentKind, Side, environment_authorized,
                    exact_decimal, exact_product)
from .reservations import AccountSnapshot, AttributedOrder, CashBasis, ExternalOrder, ExternalOrigin

MAX_RESAMPLES = 5
MAX_PAGES_CAP = 10_000
MAX_REQUESTS_CAP = 100_000
CLOCK_SKEW = timedelta(seconds=5)
POSITIONS_SETTLEMENT_STATUS = "all"  # explicit: the venue default `unsettled` omits settled rows (ACC-07)
READ_ENDPOINTS = frozenset(e for e in Endpoint if e.value.method is HttpMethod.GET)
# The cash basis a COMPLETE reconciliation may report. ACC-02 (whether the available balance already excludes
# resting-order collateral) is UNKNOWN, so it is UNKNOWN. Only a reviewed change that settles ACC-02 changes it.
CASH_BASIS = CashBasis.UNKNOWN
_ACCESS_DENIED_STATUSES = frozenset({401, 403})


def _exact_context() -> Context:
    """Exact arithmetic: a result that would need rounding raises. A fresh context per use (no shared state)."""
    return Context(prec=2 * MAX_DIGITS + 10, traps=[InvalidOperation, Inexact, Rounded])


class AccountReadError(Exception):
    """A contract refusal: a malformed plan, or a request this module must never hand to `send`."""


class AccountEndpoint(str, Enum):
    BALANCE = "BALANCE"
    POSITIONS = "POSITIONS"  # live and historical
    ORDERS = "ORDERS"  # live and historical
    FILLS = "FILLS"  # live and historical
    SETTLEMENTS = "SETTLEMENTS"  # live only: no historical endpoint has the record (ACC-12)


_HISTORICAL = frozenset({AccountEndpoint.POSITIONS, AccountEndpoint.ORDERS, AccountEndpoint.FILLS})


class Tier(str, Enum):
    LIVE = "LIVE"
    HISTORICAL = "HISTORICAL"
    GLOBAL = "GLOBAL"  # the cutoff and user-data timestamp reads


class ReconciliationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"  # something is missing, unstable or inconsistent: no new risk
    FAILED = "FAILED"  # no subaccount stream could be read


class Stability(str, Enum):
    STABLE = "STABLE"  # two consecutive live samples agreed exactly
    UNSTABLE = "UNSTABLE"  # no two consecutive samples agreed within the resample budget
    NOT_CHECKED = "NOT_CHECKED"  # a live stream was incomplete, so agreement could not be tested


class ExternalCashPolicy(str, Enum):
    """How much cash an open order that is not provider-held by a local reservation may still consume."""

    UNKNOWN_BLOCKS = "UNKNOWN_BLOCKS"  # None: unknown, so no new risk (ACC-02 is UNKNOWN)
    FULL_NOTIONAL = "FULL_NOTIONAL"  # remaining x MAX_COST_PER_CONTRACT, counted even if the venue already holds it


class SettlementSource(str, Enum):
    VENUE_RECORD = "VENUE_RECORD"  # a complete settlement record
    VENUE_RECORD_INCOMPLETE = "VENUE_RECORD_INCOMPLETE"  # a record with fields missing: kept with what it has
    HISTORICAL_POSITION_ONLY = "HISTORICAL_POSITION_ONLY"  # archived market: no settlement record exists (ACC-12)


class ReadReply(Protocol):
    """What `send` returns. `transport.TransportResult` has this shape."""

    @property
    def outcome(self) -> Any: ...

    @property
    def status(self) -> int | None: ...

    @property
    def body(self) -> bytes | None: ...


ReadSender = Callable[[WireRequest], ReadReply]
Clock = Callable[[], datetime]


# ---------------------------------------------------------------------------------------------- plan


@dataclass(frozen=True)
class AccountReadPlan:
    """Exactly what to read. Every request names its subaccount; every loop is bounded.

    - `scope`: environment and account; its `subaccount` must be None (the subaccounts are listed here).
    - `subaccounts`: the approved venue subaccounts (0 is the primary), unique, in 0-63.
    - `endpoints`: what to read. A plan without every `AccountEndpoint` can only be PARTIAL.
    - `page_limit` per request (at most `conformance.PAGE_LIMIT_MAX`); `max_pages` per stream; `max_requests` in
      total; `deadline` (aware) after which nothing more is sent.
    - `max_resamples`: extra live samples allowed (1-MAX_RESAMPLES); `max_data_lag`: how far the venue's user-data
      `as_of` may trail the read start."""

    scope: AccountScope
    subaccounts: tuple[int, ...]
    endpoints: frozenset[AccountEndpoint]
    page_limit: int
    max_pages: int
    max_requests: int
    deadline: datetime
    max_resamples: int = 3
    max_data_lag: timedelta = timedelta(minutes=1)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AccountScope):
            raise AccountReadError("scope must be an AccountScope")
        if not environment_authorized(self.scope.environment):
            raise AccountReadError(f"account reads are not authorized in {self.scope.environment.value}")
        if self.scope.subaccount is not None:
            raise AccountReadError("the plan scope names no subaccount; list them in `subaccounts`")
        subs = self.subaccounts
        if not isinstance(subs, tuple) or not subs or any(
                isinstance(n, bool) or not isinstance(n, int) or not c.SUBACCOUNT_MIN <= n <= c.SUBACCOUNT_MAX
                for n in subs):
            raise AccountReadError(f"subaccounts must be a non-empty tuple of ints in "
                                   f"{c.SUBACCOUNT_MIN}-{c.SUBACCOUNT_MAX}")
        if len(set(subs)) != len(subs):
            raise AccountReadError("subaccounts must be unique")
        object.__setattr__(self, "subaccounts", tuple(sorted(subs)))
        if not isinstance(self.endpoints, frozenset) or not self.endpoints or not all(
                isinstance(e, AccountEndpoint) for e in self.endpoints):
            raise AccountReadError("endpoints must be a non-empty frozenset of AccountEndpoint")
        for name, low, high in (("page_limit", 1, c.PAGE_LIMIT_MAX), ("max_pages", 1, MAX_PAGES_CAP),
                                ("max_requests", 1, MAX_REQUESTS_CAP), ("max_resamples", 1, MAX_RESAMPLES)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise AccountReadError(f"{name} must be an int in {low}-{high}")
        if not isinstance(self.deadline, datetime) or self.deadline.tzinfo is None \
                or self.deadline.utcoffset() is None:
            raise AccountReadError("deadline must be a timezone-aware datetime")
        if not isinstance(self.max_data_lag, timedelta) or self.max_data_lag <= timedelta(0):
            raise AccountReadError("max_data_lag must be a positive timedelta")

    def scope_for(self, subaccount: int) -> AccountScope:
        """The one canonical scope of a venue subaccount: the primary (0) is `subaccount=None`, never 0, so one venue
        subaccount never has two scope keys (which would split its cash in two)."""
        if subaccount not in self.subaccounts:
            raise AccountReadError(f"subaccount {subaccount} is not in the plan")
        return AccountScope(self.scope.environment, self.scope.account_ref, None if subaccount == 0 else subaccount)


def check_read_request(request: object) -> WireRequest:
    """`request` if this module may hand it to `send`: an allowlisted GET with an explicit subaccount wherever the
    endpoint takes one, and positions always with an explicit settlement status. Anything else raises."""
    try:
        w.check_allowlisted(request)
    except ValueError as exc:
        raise AccountReadError(f"not an allowlisted request: {exc}") from None
    assert isinstance(request, WireRequest)
    if request.is_write() or request.endpoint not in READ_ENDPOINTS:
        raise AccountReadError(f"{request.endpoint.name} is not a read: account reconciliation never writes")
    keys = {k for k, _ in request.query}
    if "subaccount" in request.endpoint.value.query_keys and "subaccount" not in keys:
        raise AccountReadError(f"{request.endpoint.name} must name its subaccount (an omitted one means all or 0, "
                               "depending on the endpoint: SUB-03)")
    if request.endpoint is Endpoint.GET_POSITIONS and "settlement_status" not in keys:
        raise AccountReadError("a positions read must name settlement_status (the default omits settled rows)")
    return request


# ---------------------------------------------------------------------------------------------- records


@dataclass(frozen=True)
class PageRecord:
    """One request and what came back. `items` is None when nothing was parsed."""

    endpoint: str
    subaccount: int | None
    tier: Tier
    sample: int
    page: int
    cursor_sent: str | None
    cursor_received: str | None
    items: int | None
    outcome: str
    status: int | None
    query: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class StreamRecord:
    """One paginated (or single-object) read: complete, or incomplete with the reason."""

    endpoint: str
    subaccount: int | None
    tier: Tier
    sample: int
    complete: bool
    pages: int
    reason: str | None


@dataclass(frozen=True)
class SettlementRecord:
    """What is known about one market's settlement in one subaccount. None is not reported, never zero."""

    ticker: str
    source: SettlementSource
    exchange_index: int | None
    event_ticker: str | None
    market_result: str | None
    yes_count: Decimal | None
    yes_total_cost: Decimal | None
    no_count: Decimal | None
    no_total_cost: Decimal | None
    revenue_cents: int | None  # integer cents (ACC-13)
    value_cents: int | None
    fee_cost: Decimal | None  # fixed-point dollars (ACC-13)
    settled_time: datetime | None
    realized_pnl: Decimal | None  # HISTORICAL_POSITION_ONLY: from the archived position
    missing: tuple[str, ...]


@dataclass(frozen=True)
class LocalOrder:
    """A held local reservation and its attempt, as the journal records them (`local_orders_from_journal`)."""

    reservation_id: str
    scope_key: str
    client_order_id: str
    provider_order_id: str | None
    market_ticker: str
    side: Side
    kind: IntentKind
    limit_price: Decimal
    quantity: Decimal
    filled_quantity: Decimal
    # The client order id the venue order carries now, when an amend set `updated_client_order_id`; None: unchanged.
    current_client_order_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("reservation_id", "scope_key", "client_order_id", "market_ticker"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in ("provider_order_id", "current_client_order_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a non-empty str or None")
        if not isinstance(self.side, Side) or not isinstance(self.kind, IntentKind):
            raise ValueError("side and kind must be enum members")
        for name in ("limit_price", "quantity", "filled_quantity"):
            object.__setattr__(self, name, exact_decimal(getattr(self, name), name=name))

    @property
    def action(self) -> Action:
        return Action.BUY if self.kind is IntentKind.ENTRY else Action.SELL

    @property
    def client_ids(self) -> frozenset[str]:
        """Every client order id the venue order may carry: the intent's, and the amended one if any."""
        return frozenset(x for x in (self.client_order_id, self.current_client_order_id) if x is not None)


def local_orders_from_journal(journal: Any, scopes: Iterable[AccountScope]) -> tuple[LocalOrder, ...]:
    """Every held reservation of `scopes` with its attempt's provider order id (a reservation's id is its
    attempt's id). `journal` is an `ExecutionJournal`."""
    out = []
    for scope in scopes:
        for r in journal.reservations.held_reservations(scope):
            attempt = journal.attempt(r.reservation_id)
            out.append(LocalOrder(r.reservation_id, r.scope_key, r.client_order_id, attempt.provider_order_id,
                                  r.market_ticker, r.side, r.kind, r.limit_price, r.quantity, r.filled_quantity))
    return tuple(out)


@dataclass(frozen=True)
class SnapshotInputs:
    """The arguments of `reservations.record_account_snapshot` for one subaccount. None is unknown."""

    scope: AccountScope
    observed_at: datetime
    cash: Decimal | None
    cash_basis: CashBasis
    positions: Mapping[tuple[str, Side], Decimal] | None
    external_open_orders: tuple[ExternalOrder, ...] | None
    attributed_open_orders: tuple[AttributedOrder, ...]

    def record(self, authority: Any, revision: int, *, now: datetime) -> AccountSnapshot:
        """Record these inputs with a `reservations.ReservationAuthority` (journal.reservations)."""
        return authority.record_account_snapshot(self.scope, revision, self.observed_at, self.cash, self.cash_basis,
                                                 self.positions, self.external_open_orders,
                                                 attributed_open_orders=self.attributed_open_orders, now=now)


@dataclass(frozen=True)
class ReadManifest:
    """Exactly what was read: every page and stream, the cutoffs and user-data timestamps seen, and coverage."""

    plan: AccountReadPlan
    started_at: datetime
    finished_at: datetime
    requests: int
    pages: tuple[PageRecord, ...]
    streams: tuple[StreamRecord, ...]
    as_of_start: datetime | None
    as_of_end: datetime | None
    cutoffs: tuple[w.HistoricalCutoff, ...]
    coverage: Mapping[tuple[int, AccountEndpoint], bool]  # final data complete, per subaccount and endpoint


@dataclass(frozen=True)
class SubaccountReconciliation:
    subaccount: int
    scope: AccountScope
    stability: Stability
    samples: int
    balance: w.Balance | None
    positions: tuple[w.MarketPosition, ...] | None  # live tier: current holdings
    historical_positions: tuple[w.MarketPosition, ...] | None
    orders: tuple[w.VenueOrder, ...] | None  # live and historical, deduplicated
    open_orders: tuple[w.VenueOrder, ...] | None  # resting (always live, ORD-27)
    fills: tuple[w.VenueFill, ...] | None  # live and historical, deduplicated
    fills_by_order: Mapping[str, Decimal] | None  # cumulative filled count per venue order id
    settlements: tuple[SettlementRecord, ...] | None
    attributed: tuple[AttributedOrder, ...]
    external: tuple[ExternalOrder, ...] | None
    matched_orders: Mapping[str, str]  # reservation id -> venue order id (any status)
    unlisted_local: tuple[str, ...]  # held local reservations with no resting venue order
    problems: tuple[str, ...]
    gaps: tuple[str, ...]
    observations: tuple[str, ...]
    snapshot: SnapshotInputs


@dataclass(frozen=True)
class AccountReconciliation:
    status: ReconciliationStatus
    manifest: ReadManifest
    subaccounts: tuple[SubaccountReconciliation, ...]
    problems: tuple[str, ...]  # every problem, global and per subaccount
    gaps: tuple[str, ...]
    observations: tuple[str, ...]

    @property
    def usable_for_new_risk(self) -> bool:
        """Necessary, never sufficient: only a COMPLETE reconciliation can back new risk, and the reservation
        authority still decides."""
        return self.status is ReconciliationStatus.COMPLETE

    def snapshot_inputs(self) -> tuple[SnapshotInputs, ...]:
        return tuple(s.snapshot for s in self.subaccounts)


# ---------------------------------------------------------------------------------------------- parsing helpers


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WireFormatError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _refuse_constant(name: str) -> Any:
    raise WireFormatError(f"non-finite JSON number {name}")


def _load(body: bytes, where: str) -> dict[str, Any]:
    """The page envelope. JSON numbers with a fraction stay `float` here on purpose: a record is re-serialized for
    the strict parser, which refuses a number where a fixed-point string is documented, so the float must survive
    as a number (turning it into text would make it look valid)."""
    try:
        obj = json.loads(bytes(body).decode("utf-8"), parse_constant=_refuse_constant,
                         object_pairs_hook=_no_duplicate_keys)
    except WireFormatError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise WireFormatError(f"{where}: not a JSON document ({type(exc).__name__})") from None
    if not isinstance(obj, dict):
        raise WireFormatError(f"{where}: top level is not an object")
    return obj


_COUNT_TEXT = re.compile(r"\d+(\.\d{1,2})?")
_DOLLAR_TEXT = re.compile(r"\d+(\.\d{1,6})?")
_SETTLEMENT_FIELDS = ("exchange_index", "event_ticker", "market_result", "yes_count_fp", "yes_total_cost_dollars",
                      "no_count_fp", "no_total_cost_dollars", "revenue", "value", "fee_cost", "settled_time")
# The fields `kalshi_wire` requires of a settlement record: a record with all of them goes through that parser.
_STRICT_SETTLEMENT_FIELDS = frozenset({"ticker", "event_ticker", "exchange_index", "market_result", "yes_count_fp",
                                       "yes_total_cost_dollars", "no_count_fp", "no_total_cost_dollars", "revenue",
                                       "settled_time", "fee_cost"})


def _lenient_settlement(obj: dict[str, Any], where: str) -> SettlementRecord:
    """A settlement record with required fields missing (old records): every present field is checked as strictly
    as `kalshi_wire` does (and revenue may not be negative); an absent or null one is listed in `missing`, never
    defaulted. No ticker: unidentifiable."""
    ticker = obj.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        raise WireFormatError(f"{where}: a settlement without a ticker cannot be identified")
    missing: list[str] = []

    def get(key: str, kind: str) -> Any:
        value = obj.get(key)
        if value is None:
            missing.append(key)
            return None
        if kind == "text" and isinstance(value, str):
            return value
        if kind in ("int", "index", "cents") and isinstance(value, int) and not isinstance(value, bool):
            if kind == "int" or value >= 0:
                return value
        if kind in ("count", "dollars") and isinstance(value, str) and (
                _COUNT_TEXT if kind == "count" else _DOLLAR_TEXT).fullmatch(value):
            return Decimal(value)
        if kind == "result" and value in ("yes", "no", "scalar"):
            return value
        if kind == "time" and isinstance(value, str):
            try:
                at = datetime.fromisoformat(value)
            except ValueError:
                raise WireFormatError(f"{where}.{key} is not an ISO-8601 time") from None
            if at.tzinfo is not None and at.utcoffset() is not None:
                return at.astimezone(timezone.utc)
        raise WireFormatError(f"{where}.{key} is malformed")

    return SettlementRecord(
        ticker, SettlementSource.VENUE_RECORD_INCOMPLETE, get("exchange_index", "index"), get("event_ticker", "text"),
        get("market_result", "result"), get("yes_count_fp", "count"), get("yes_total_cost_dollars", "dollars"),
        get("no_count_fp", "count"), get("no_total_cost_dollars", "dollars"), get("revenue", "cents"),
        get("value", "int"), get("fee_cost", "dollars"), get("settled_time", "time"), None, tuple(missing))


def _settlement_record(s: w.VenueSettlement, where: str) -> SettlementRecord:
    if s.revenue_cents < 0:
        raise WireFormatError(f"{where}.revenue must not be negative")
    missing = () if s.value_cents is not None else ("value",)
    return SettlementRecord(s.ticker, SettlementSource.VENUE_RECORD if not missing
                            else SettlementSource.VENUE_RECORD_INCOMPLETE, s.exchange_index, s.event_ticker,
                            s.market_result, s.yes_count, s.yes_total_cost, s.no_count, s.no_total_cost,
                            s.revenue_cents, s.value_cents, s.fee_cost, s.settled_time, None, missing)


def _one_settlement(item: object, where: str) -> SettlementRecord:
    """Per record: one with every required field goes through the strict `kalshi_wire` parser; only one with
    required fields absent goes through the lenient reader. One bad record never weakens another."""
    if not isinstance(item, dict):
        raise WireFormatError(f"{where} is not an object")
    if all(item.get(k) is not None for k in _STRICT_SETTLEMENT_FIELDS):
        single = json.dumps({"settlements": [item], "cursor": None}, allow_nan=False).encode("utf-8")
        (record,) = w.parse_settlements_page(single).items
        return _settlement_record(record, where)
    return _lenient_settlement(item, where)


def _parse_settlements(body: bytes) -> tuple[tuple[SettlementRecord, ...], str | None]:
    obj = _load(body, "settlements")
    raw, cursor = obj.get("settlements"), obj.get("cursor")
    if not isinstance(raw, list):
        raise WireFormatError("settlements: required field 'settlements' is missing")
    if cursor is not None and not isinstance(cursor, str):
        raise WireFormatError("settlements.cursor must be a string")
    return tuple(_one_settlement(x, f"settlements.settlements[{i}]") for i, x in enumerate(raw)), cursor or None


def _parse_orders(body: bytes) -> tuple[tuple[Any, ...], str | None]:
    page = w.parse_orders_page(body)
    return page.items, page.cursor


def _parse_fills(body: bytes) -> tuple[tuple[Any, ...], str | None]:
    page = w.parse_fills_page(body)
    return page.items, page.cursor


def _parse_positions(body: bytes) -> tuple[tuple[Any, ...], str | None]:
    page = w.parse_positions_page(body)
    return page.market_positions, page.cursor


# ---------------------------------------------------------------------------------------------- reading


def _malformed(exc: Exception) -> str:
    detail = str(exc) if isinstance(exc, WireFormatError) else type(exc).__name__
    return f"MALFORMED_PAGE: {detail}"


@dataclass(frozen=True)
class _Got:
    """One stream's result: its items (None unless complete) and its record."""

    items: tuple[Any, ...] | None
    record: StreamRecord


class _Reader:
    """Sends through the caller's `send` within the plan's budgets, and records every page and stream."""

    def __init__(self, plan: AccountReadPlan, send: ReadSender, clock: Clock):
        self.plan, self.send, self.clock = plan, send, clock
        self.requests = 0
        self.pages: list[PageRecord] = []
        self.streams: list[StreamRecord] = []
        self.halt: str | None = None  # once set, nothing more is sent

    def now(self) -> datetime:
        at = self.clock()
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise AccountReadError("the clock must return a timezone-aware datetime")
        return at

    def _send(self, request: WireRequest) -> tuple[bytes | None, str, int | None]:
        check_read_request(request)
        if self.halt is None and self.requests >= self.plan.max_requests:
            self.halt = "REQUEST_BUDGET_EXHAUSTED"
        if self.halt is None and self.now() >= self.plan.deadline:
            self.halt = "DEADLINE_EXCEEDED"
        if self.halt is not None:
            return None, self.halt, None
        self.requests += 1
        try:
            reply = self.send(request)
        except Exception as exc:  # never the message: it might carry request details
            return None, f"SEND_RAISED: {type(exc).__name__}", None
        status = getattr(reply, "status", None)
        status = status if isinstance(status, int) and not isinstance(status, bool) else None
        outcome = getattr(reply, "outcome", None)
        if outcome != "OK":
            label = str(getattr(outcome, "value", outcome))
            if status in _ACCESS_DENIED_STATUSES:
                return None, f"ACCESS_DENIED: {label} {status}", status
            return None, f"NOT_OK: {label} {status}", status
        body = getattr(reply, "body", None)
        if not isinstance(body, (bytes, bytearray)):
            return None, "NO_BODY", status
        return bytes(body), "OK", status

    def _finish(self, endpoint: Endpoint, subaccount: int | None, tier: Tier, sample: int, items: list | None,
                pages: int, reason: str | None) -> _Got:
        record = StreamRecord(endpoint.name, subaccount, tier, sample, reason is None, pages, reason)
        self.streams.append(record)
        return _Got(None if reason is not None else tuple(items or ()), record)

    def stream(self, build: Callable[[str | None], WireRequest], parse: Callable[[bytes], tuple[tuple, str | None]],
               *, subaccount: int | None, tier: Tier, sample: int,
               check: Callable[[Any], str | None] | None = None) -> _Got:
        """Every page of one cursor-paginated read, or an incomplete stream with the reason. Bounded by
        `max_pages`; a cursor seen before is a loop."""
        items: list[Any] = []
        seen: set[str] = set()
        cursor: str | None = None
        endpoint = build(None).endpoint
        for page_no in range(1, self.plan.max_pages + 1):
            request = build(cursor)
            body, label, status = self._send(request)
            parsed: tuple[tuple, str | None] | None = None
            reason = None if body is not None else label
            if body is not None:
                try:
                    parsed = parse(body)
                except Exception as exc:  # a parser bug is as unknowable as a malformed page
                    reason = _malformed(exc)
            got, nxt = parsed if parsed is not None else ((), None)
            self.pages.append(PageRecord(endpoint.name, subaccount, tier, sample, page_no, cursor, nxt,
                                         None if parsed is None else len(got), label, status, request.query))
            if reason is not None:
                return self._finish(endpoint, subaccount, tier, sample, None, page_no, reason)
            for item in got:
                bad = check(item) if check is not None else None
                if bad is not None:
                    return self._finish(endpoint, subaccount, tier, sample, None, page_no, bad)
            items.extend(got)
            if nxt is None:
                return self._finish(endpoint, subaccount, tier, sample, items, page_no, None)
            if nxt == cursor or nxt in seen:
                return self._finish(endpoint, subaccount, tier, sample, None, page_no, f"CURSOR_LOOP: {nxt!r}")
            seen.add(nxt)
            cursor = nxt
        return self._finish(endpoint, subaccount, tier, sample, None, self.plan.max_pages,
                            f"PAGE_BUDGET_EXHAUSTED: {self.plan.max_pages} pages and the cursor continues")

    def single(self, request: WireRequest, parse: Callable[[bytes], Any], *, subaccount: int | None, tier: Tier,
               sample: int) -> _Got:
        body, label, status = self._send(request)
        reason = None if body is not None else label
        value = None
        if body is not None:
            try:
                value = parse(body)
            except Exception as exc:  # a parser bug is as unknowable as a malformed page
                reason = _malformed(exc)
        self.pages.append(PageRecord(request.endpoint.name, subaccount, tier, sample, 1, None, None,
                                     None if reason is not None else 1, label, status, request.query))
        return self._finish(request.endpoint, subaccount, tier, sample, [value], 1, reason)


def _subaccount_check(n: int) -> Callable[[Any], str | None]:
    def check(item: Any) -> str | None:
        number = getattr(item, "subaccount_number", None)
        if number is not None and number != n:
            return f"UNKNOWN_SUBACCOUNT_RECORD: a record of subaccount {number} in a read of subaccount {n}"
        return None

    return check


def _read_live(reader: _Reader, n: int, sample: int) -> Mapping[AccountEndpoint, _Got]:
    plan, scope, limit = reader.plan, reader.plan.scope_for(n), reader.plan.page_limit
    kw = dict(subaccount=n, tier=Tier.LIVE, sample=sample)
    out: dict[AccountEndpoint, _Got] = {}
    if AccountEndpoint.BALANCE in plan.endpoints:
        out[AccountEndpoint.BALANCE] = reader.single(w.build_get_balance(scope), w.parse_balance, **kw)
    if AccountEndpoint.POSITIONS in plan.endpoints:
        out[AccountEndpoint.POSITIONS] = reader.stream(
            lambda cur: w.build_get_positions(scope, settlement_status=POSITIONS_SETTLEMENT_STATUS, cursor=cur,
                                              limit=limit), _parse_positions, **kw)
    if AccountEndpoint.ORDERS in plan.endpoints:
        out[AccountEndpoint.ORDERS] = reader.stream(lambda cur: w.build_get_orders(scope, cursor=cur, limit=limit),
                                                    _parse_orders, check=_subaccount_check(n), **kw)
    if AccountEndpoint.FILLS in plan.endpoints:
        out[AccountEndpoint.FILLS] = reader.stream(lambda cur: w.build_get_fills(scope, cursor=cur, limit=limit),
                                                   _parse_fills, check=_subaccount_check(n), **kw)
    if AccountEndpoint.SETTLEMENTS in plan.endpoints:
        out[AccountEndpoint.SETTLEMENTS] = reader.stream(
            lambda cur: w.build_get_settlements(scope, cursor=cur, limit=limit), _parse_settlements, **kw)
    return MappingProxyType(out)


def _read_historical(reader: _Reader, n: int, sample: int) -> Mapping[AccountEndpoint, _Got]:
    plan, scope, limit = reader.plan, reader.plan.scope_for(n), reader.plan.page_limit
    kw = dict(subaccount=n, tier=Tier.HISTORICAL, sample=sample)
    out: dict[AccountEndpoint, _Got] = {}
    if AccountEndpoint.POSITIONS in plan.endpoints:
        out[AccountEndpoint.POSITIONS] = reader.stream(
            lambda cur: w.build_get_historical_positions(scope, cursor=cur, limit=limit), _parse_positions, **kw)
    if AccountEndpoint.ORDERS in plan.endpoints:
        out[AccountEndpoint.ORDERS] = reader.stream(
            lambda cur: w.build_get_orders(scope, cursor=cur, limit=limit, historical=True), _parse_orders,
            check=_subaccount_check(n), **kw)
    if AccountEndpoint.FILLS in plan.endpoints:
        out[AccountEndpoint.FILLS] = reader.stream(
            lambda cur: w.build_get_fills(scope, cursor=cur, limit=limit, historical=True), _parse_fills,
            check=_subaccount_check(n), **kw)
    return MappingProxyType(out)


# ---------------------------------------------------------------------------------------------- dedup and agreement


_KEYS: Mapping[AccountEndpoint, Callable[[Any], str]] = MappingProxyType({
    AccountEndpoint.BALANCE: lambda b: "balance",
    AccountEndpoint.POSITIONS: lambda p: p.ticker,
    AccountEndpoint.ORDERS: lambda o: o.order_id,
    AccountEndpoint.FILLS: lambda f: f.fill_id,
    AccountEndpoint.SETTLEMENTS: lambda s: s.ticker,
})


@dataclass(frozen=True)
class _Deduped:
    items: tuple[Any, ...]  # sorted by key, first version of each key
    duplicates: int  # identical repeats collapsed
    conflicts: tuple[str, ...]  # keys seen with different content


def _dedupe(items: Iterable[Any], endpoint: AccountEndpoint) -> _Deduped:
    key = _KEYS[endpoint]
    kept: dict[str, Any] = {}
    duplicates, conflicts = 0, []
    for item in items:
        k = key(item)
        if k not in kept:
            kept[k] = item
        elif kept[k] == item:  # dataclass equality: every field but the unparsed `extra`
            duplicates += 1
        elif k not in conflicts:
            conflicts.append(k)
    return _Deduped(tuple(kept[k] for k in sorted(kept)), duplicates, tuple(conflicts))


def _digest(sample: Mapping[AccountEndpoint, _Got]) -> tuple | None:
    """What two samples must share to agree: every live record, deduplicated. None if any stream is incomplete."""
    out = []
    for endpoint in AccountEndpoint:
        if endpoint not in sample:
            continue
        got = sample[endpoint]
        if got.items is None:
            return None
        out.append((endpoint, _dedupe(got.items, endpoint)))
    return tuple(out)


def _regressions(previous: Mapping[AccountEndpoint, _Got], current: Mapping[AccountEndpoint, _Got],
                 n: int) -> list[str]:
    """Update stamps that went backwards between consecutive samples: the later read was served stale data."""
    out = []
    old, new = previous.get(AccountEndpoint.BALANCE), current.get(AccountEndpoint.BALANCE)
    if old and new and old.items and new.items and new.items[0].updated_ts < old.items[0].updated_ts:
        out.append(f"STALE_UPDATE: subaccount {n} balance updated_ts went back from {old.items[0].updated_ts} "
                   f"to {new.items[0].updated_ts}")
    for endpoint, stamp in ((AccountEndpoint.POSITIONS, "last_updated"), (AccountEndpoint.ORDERS, "last_update_time")):
        old, new = previous.get(endpoint), current.get(endpoint)
        if not (old and new and old.items is not None and new.items is not None):
            continue
        before = {_KEYS[endpoint](x): getattr(x, stamp) for x in old.items}
        for x in new.items:
            k, at = _KEYS[endpoint](x), getattr(x, stamp)
            if at is not None and before.get(k) is not None and at < before[k]:
                out.append(f"STALE_UPDATE: subaccount {n} {endpoint.value} {k} {stamp} went back from {before[k]} "
                           f"to {at}")
    return out


def _merge_tiers(live: _Deduped, historical: _Deduped, endpoint: AccountEndpoint) -> tuple[tuple, int, tuple]:
    """Live first, then historical (ACC-11). The same record in both tiers collapses; a different one conflicts."""
    key = _KEYS[endpoint]
    kept = {key(x): x for x in live.items}
    duplicates, conflicts = 0, []
    for x in historical.items:
        k = key(x)
        if k not in kept:
            kept[k] = x
        elif kept[k] == x:
            duplicates += 1
        else:
            conflicts.append(k)
    return tuple(kept[k] for k in sorted(kept)), duplicates, tuple(conflicts)


# ---------------------------------------------------------------------------------------------- attribution


def _price_terms_problem(o: w.VenueOrder, local: LocalOrder) -> str | None:
    if o.ticker != local.market_ticker:
        return f"ticker {o.ticker} is not the local order's {local.market_ticker}"
    if o.type != "limit":
        return f"type {o.type} is not a limit order"
    with localcontext(_exact_context()):
        if o.yes_price + o.no_price != 1:
            return f"yes {o.yes_price} and no {o.no_price} prices do not sum to 1"
        book, yes_price = w.yes_terms(local.side, local.action, local.limit_price)
        if book != o.book_side:
            return f"book side {o.book_side} is not the local order's {book}"
        if yes_price != o.yes_price:
            return f"YES price {o.yes_price} is not the local order's {yes_price}"
    return None


def _unreflected(remaining: Decimal, policy: ExternalCashPolicy) -> Decimal | None:
    if policy is ExternalCashPolicy.FULL_NOTIONAL:
        return exact_product(remaining, MAX_COST_PER_CONTRACT)
    return None


def _external(o: w.VenueOrder, policy: ExternalCashPolicy) -> ExternalOrder:
    # Side and action stay unknown: a bid is a buy of YES or a sale of NO, and the legacy fields that would tell
    # them apart are never read (DIR-04). Unknown counts against every inventory key of the market.
    return ExternalOrder(o.order_id, ExternalOrigin.UNKNOWN, o.ticker, None, None, o.remaining_count,
                         _unreflected(o.remaining_count, policy))


@dataclass(frozen=True)
class _Attribution:
    attributed: tuple[AttributedOrder, ...]
    external: tuple[ExternalOrder, ...]
    matched: Mapping[str, str]
    unlisted: tuple[str, ...]
    problems: tuple[str, ...]
    observations: tuple[str, ...]


def _attribute(open_orders: tuple[w.VenueOrder, ...], all_orders: tuple[w.VenueOrder, ...] | None,
               local: tuple[LocalOrder, ...], policy: ExternalCashPolicy) -> _Attribution:
    """Match resting venue orders to local attempts. A unique provider order id is the identity (the journal binds
    each one to one attempt), and the venue's client order id must then be one the attempt carries (its intent's,
    or the amended one). Without a provider id match, the client order id must name exactly one unacknowledged
    attempt: attempts of one intent share it, and an acknowledged attempt is already another venue order. A match
    must also agree on ticker, direction and YES price. Anything ambiguous or contradictory stays external (it
    consumes capacity)."""
    by_provider: dict[str, list[LocalOrder]] = {}
    by_client: dict[str, list[LocalOrder]] = {}
    for lo in local:
        if lo.provider_order_id is not None:
            by_provider.setdefault(lo.provider_order_id, []).append(lo)
        for cid in lo.client_ids:
            by_client.setdefault(cid, []).append(lo)
    attributed, external, problems, observations = [], [], [], []
    claimed: dict[str, str] = {}
    for o in sorted(open_orders, key=lambda x: x.order_id):
        p, cl = by_provider.get(o.order_id, []), by_client.get(o.client_order_id, [])
        why, chosen = None, None
        if len(p) > 1:
            why = "several local orders own its provider id"
        elif p:
            chosen = p[0]
            if o.client_order_id not in chosen.client_ids:
                why = (f"client order id is not one local {chosen.reservation_id} carries, though it owns this "
                       "provider id")
        elif cl:
            unacknowledged = [lo for lo in cl if lo.provider_order_id is None]
            if len(unacknowledged) == 1:
                chosen = unacknowledged[0]
            elif unacknowledged:
                why = "several unacknowledged local attempts carry its client order id"
            else:
                why = (f"every local order carrying its client order id is acknowledged as another venue order "
                       f"({sorted(lo.provider_order_id for lo in cl)})")
        if chosen is not None and why is None:
            why = _price_terms_problem(o, chosen)
            if why is None and chosen.reservation_id in claimed:
                why = f"local {chosen.reservation_id} is already matched to {claimed[chosen.reservation_id]}"
        if why is not None:
            external.append(_external(o, policy))
            problems.append(f"ATTRIBUTION_MISMATCH: venue order {o.order_id}: {why}; kept as an external obligation")
        elif chosen is not None:
            claimed[chosen.reservation_id] = o.order_id
            price = o.yes_price if chosen.side is Side.YES else o.no_price
            # The journal's client order id: the reservation authority checks it against its own row.
            attributed.append(AttributedOrder(chosen.reservation_id, chosen.client_order_id, o.remaining_count, price,
                                              _unreflected(o.remaining_count, policy)))
            if o.client_order_id != chosen.client_order_id:
                observations.append(f"AMENDED_CLIENT_ID: venue order {o.order_id} carries {o.client_order_id}, the "
                                    f"amended id of local {chosen.reservation_id}")
        else:
            external.append(_external(o, policy))
            observations.append(f"EXTERNAL_ORDER: venue order {o.order_id} ({o.ticker}) has no local attempt "
                                "(manual or native); it is an external obligation")
    matched = dict(claimed)
    for o in all_orders or ():
        owners = by_provider.get(o.order_id, [])
        if len(owners) == 1 and owners[0].reservation_id not in matched:
            matched[owners[0].reservation_id] = o.order_id
    unlisted = tuple(sorted(lo.reservation_id for lo in local if lo.reservation_id not in claimed))
    return _Attribution(tuple(attributed), tuple(external), MappingProxyType(matched), unlisted, tuple(problems),
                        tuple(observations))


# ---------------------------------------------------------------------------------------------- reconciliation


def _balance_unit_problem(b: w.Balance, n: int) -> str | None:
    """`balance` is integer cents and `balance_dollars` fixed-point dollars (ACC-01): they must be the same amount
    to within one cent (dollars carry up to 4 places, ACC-04). Anything else is a unit change, never repaired."""
    with localcontext(_exact_context()):
        gap = abs(exact_product(b.balance_dollars, Decimal(100)) - b.balance_cents)
    if gap >= 1:
        return (f"UNIT_MISMATCH: subaccount {n} balance {b.balance_cents} cents vs {b.balance_dollars} dollars; "
                "cash is unknown")
    return None


def _settlement_unit_problem(s: SettlementRecord, n: int) -> str | None:
    """Winning contracts pay one dollar (SET-01) and revenue is integer cents (ACC-13): with one side held and the
    result known, revenue must be that count x 100 cents."""
    if s.market_result not in ("yes", "no") or s.revenue_cents is None or s.yes_count is None or s.no_count is None:
        return None
    with localcontext(_exact_context()):
        if s.yes_count != 0 and s.no_count != 0:
            return None  # both sides held: netting is not modelled here
        winning = s.yes_count if s.market_result == "yes" else s.no_count
        expected = exact_product(winning, Decimal(100))
    if expected != s.revenue_cents:
        return (f"UNIT_MISMATCH: subaccount {n} settlement {s.ticker} revenue {s.revenue_cents} cents vs "
                f"{winning} winning contracts ({expected} cents)")
    return None


def _partition_problems(n: int, historical: Mapping[AccountEndpoint, _Got],
                        cutoff: w.HistoricalCutoff | None) -> Mapping[AccountEndpoint, tuple[str, ...]]:
    """A historical record newer than the cutoff, or a resting order in the historical tier, contradicts the
    documented partition (ACC-10, ORD-27). Per endpoint, so that endpoint's history is not used."""
    if cutoff is None:
        return MappingProxyType({})
    out: dict[AccountEndpoint, list[str]] = {}
    fills = historical.get(AccountEndpoint.FILLS)
    for f in (fills.items or ()) if fills else ():
        if f.created_time is not None and f.created_time >= cutoff.trades_created:
            out.setdefault(AccountEndpoint.FILLS, []).append(
                f"TIER_PARTITION_VIOLATION: subaccount {n} historical fill {f.fill_id} is newer than the cutoff "
                f"{cutoff.trades_created.isoformat()}")
    orders = historical.get(AccountEndpoint.ORDERS)
    for o in (orders.items or ()) if orders else ():
        if o.status == "resting":
            out.setdefault(AccountEndpoint.ORDERS, []).append(
                f"TIER_PARTITION_VIOLATION: subaccount {n} historical order {o.order_id} is resting")
        elif o.last_update_time is not None and o.last_update_time >= cutoff.orders_updated:
            out.setdefault(AccountEndpoint.ORDERS, []).append(
                f"TIER_PARTITION_VIOLATION: subaccount {n} historical order {o.order_id} is newer than the cutoff "
                f"{cutoff.orders_updated.isoformat()}")
    return MappingProxyType({e: tuple(v) for e, v in out.items()})


def _shard_problems(n: int, balance: w.Balance | None, records: Iterable[Any]) -> list[str]:
    """Shard coverage. Whether a read without `exchange_index` covers every shard is not documented, so only a
    single-shard (0) account can be complete: a balance on another shard, a missing breakdown, or any record on
    another shard is a problem."""
    out = []
    if balance is not None:
        shards = None if balance.breakdown is None else sorted({index for index, _ in balance.breakdown})
        if shards is None:
            out.append(f"SHARDS_UNKNOWN: subaccount {n} balance has no balance_breakdown, so the shards that hold "
                       "its cash and positions are not known")
        elif shards != [0]:
            out.append(f"SHARDS_NOT_ENUMERATED: subaccount {n} has balances on shards {shards}; whether a read "
                       "without exchange_index covers every shard is not documented")
    seen = sorted({index for x in records if (index := getattr(x, "exchange_index", None)) not in (None, 0)})
    if seen:
        out.append(f"SHARDS_NOT_ENUMERATED: subaccount {n} has records on shards {seen}; whether a read without "
                   "exchange_index covers every shard is not documented")
    return out


@dataclass(frozen=True)
class _Work:
    """A subaccount's reads before finalization."""

    n: int
    live: Mapping[AccountEndpoint, _Got]
    historical: Mapping[AccountEndpoint, _Got]
    stability: Stability
    samples: int
    problems: tuple[str, ...]
    seen: Mapping[AccountEndpoint, frozenset[str]]  # order and fill ids seen in any live sample


_IMMUTABLE_IDS = (AccountEndpoint.ORDERS, AccountEndpoint.FILLS)  # records that never leave both tiers


def _read_subaccount(reader: _Reader, n: int) -> _Work:
    live = _read_live(reader, n, 0)
    historical = _read_historical(reader, n, 0)
    samples = [live]
    problems: list[str] = []
    while True:
        digest = _digest(samples[-1])
        if digest is None:
            stability = Stability.NOT_CHECKED
            break
        if len(samples) > 1 and digest == _digest(samples[-2]):
            stability = Stability.STABLE
            break
        if len(samples) - 1 >= reader.plan.max_resamples:
            stability = Stability.UNSTABLE
            break
        samples.append(_read_live(reader, n, len(samples)))
        problems += _regressions(samples[-2], samples[-1], n)
    seen = {e: frozenset(_KEYS[e](x) for sample in samples if e in sample and sample[e].items is not None
                         for x in sample[e].items) for e in _IMMUTABLE_IDS}
    return _Work(n, samples[-1], historical, stability, len(samples), tuple(problems), MappingProxyType(seen))


def _finalize(work: _Work, plan: AccountReadPlan, *, complete_overall: bool, fresh: bool, partition_ok: bool,
              observed_at: datetime, cutoff: w.HistoricalCutoff | None, local: tuple[LocalOrder, ...],
              policy: ExternalCashPolicy) -> SubaccountReconciliation:
    """Every result field passes one gate. A live field is set only when its stream is complete, conflict-free,
    STABLE, fresh and on enumerated shards; a historical field only when its stream is complete, conflict-free,
    on enumerated shards and the partition is proven. Otherwise it is None (unknown), never a partial tuple."""
    n, scope = work.n, plan.scope_for(work.n)
    problems, gaps, observations = list(work.problems), [], []
    for tier, got_map in ((Tier.LIVE, work.live), (Tier.HISTORICAL, work.historical)):
        for endpoint, got in got_map.items():
            if got.items is None:
                problems.append(f"STREAM_INCOMPLETE: subaccount {n} {endpoint.value} {tier.value}: "
                                f"{got.record.reason}")
    if work.stability is Stability.UNSTABLE:
        problems.append(f"UNSTABLE: subaccount {n} live reads did not agree in {work.samples} samples")
    stable = work.stability is Stability.STABLE

    def deduped(got_map: Mapping[AccountEndpoint, _Got], endpoint: AccountEndpoint) -> _Deduped | None:
        got = got_map.get(endpoint)
        if got is None or got.items is None:
            return None
        d = _dedupe(got.items, endpoint)
        if d.duplicates:
            observations.append(f"DUPLICATES_COLLAPSED: subaccount {n} {endpoint.value} {d.duplicates} identical")
        for k in d.conflicts:
            problems.append(f"CONFLICTING_DUPLICATE: subaccount {n} {endpoint.value} {k} was reported with "
                            "different content")
        return d

    live = {e: deduped(work.live, e) for e in AccountEndpoint if e in work.live}
    hist = {e: deduped(work.historical, e) for e in _HISTORICAL if e in work.historical}
    raw_balance = live[AccountEndpoint.BALANCE].items[0] if live.get(AccountEndpoint.BALANCE) is not None else None
    shard_problems = _shard_problems(n, raw_balance, [x for d in (*live.values(), *hist.values()) if d is not None
                                                      for x in d.items])
    problems += shard_problems
    violations = _partition_problems(n, work.historical, cutoff)
    problems += [v for e in violations for v in violations[e]]
    shards_ok = not shard_problems
    usable = {e: d is not None and not d.conflicts and stable and fresh and shards_ok for e, d in live.items()}
    hist_ok = {e: d is not None and not d.conflicts and partition_ok and shards_ok and e not in violations
               for e, d in hist.items()}
    if raw_balance is not None:
        unit = _balance_unit_problem(raw_balance, n)
        if unit is not None:
            problems.append(unit)
            usable[AccountEndpoint.BALANCE] = False

    def items_if(endpoint: AccountEndpoint) -> tuple | None:
        return live[endpoint].items if usable.get(endpoint) else None

    def merged(endpoint: AccountEndpoint) -> tuple | None:
        """Live first, then historical (ACC-11). Problems are reported whenever both tiers were read; the records
        are returned only when both tiers pass the gate."""
        lv, hv = live.get(endpoint), hist.get(endpoint)
        if lv is None or hv is None or lv.conflicts or hv.conflicts:
            return None
        items, duplicates, conflicts = _merge_tiers(lv, hv, endpoint)
        if duplicates:
            observations.append(f"TIER_DUPLICATES_COLLAPSED: subaccount {n} {endpoint.value} {duplicates} records "
                                "seen in both tiers")
        for k in conflicts:
            problems.append(f"CONFLICTING_DUPLICATE: subaccount {n} {endpoint.value} {k} differs between the live "
                            "and historical tiers")
        if conflicts:
            return None
        vanished = sorted(work.seen.get(endpoint, frozenset()) - {_KEYS[endpoint](x) for x in items})
        if vanished:  # seen live earlier, now in neither tier: the partition moved without the cutoff saying so
            problems.append(f"RECORD_VANISHED: subaccount {n} {endpoint.value} {vanished[:5]} were read earlier but "
                            "are in neither tier now")
            return None
        return items if usable[endpoint] and hist_ok[endpoint] else None

    balance = raw_balance if usable.get(AccountEndpoint.BALANCE) else None
    orders, fills = merged(AccountEndpoint.ORDERS), merged(AccountEndpoint.FILLS)
    fills_by_order = None
    if fills is not None:
        totals: dict[str, Decimal] = {}
        with localcontext(_exact_context()):
            for f in fills:
                totals[f.order_id] = totals.get(f.order_id, Decimal(0)) + f.count
        fills_by_order = MappingProxyType(dict(sorted(totals.items())))

    positions = items_if(AccountEndpoint.POSITIONS)
    historical_positions = hist[AccountEndpoint.POSITIONS].items if hist_ok.get(AccountEndpoint.POSITIONS) else None
    if positions is not None and historical_positions is not None:
        current = {p.ticker: p for p in positions}
        moved = sorted(p.ticker for p in historical_positions if p.ticker in current and current[p.ticker] != p)
        if moved:
            observations.append(f"POSITION_IN_BOTH_TIERS: subaccount {n} {moved}: the live row is used (ACC-11)")

    settlements = None
    if AccountEndpoint.SETTLEMENTS in live:
        d = live[AccountEndpoint.SETTLEMENTS]
        if d is not None and not d.conflicts:
            for s in d.items:
                unit = _settlement_unit_problem(s, n)
                if unit is not None:
                    problems.append(unit)
                    usable[AccountEndpoint.SETTLEMENTS] = False
                if s.missing:
                    gaps.append(f"SETTLEMENT_FIELDS_MISSING: subaccount {n} {s.ticker}: {list(s.missing)} not "
                                "reported (not zero)")
        if usable[AccountEndpoint.SETTLEMENTS]:
            records = list(d.items)
            known = {s.ticker for s in records}
            for p in historical_positions or ():
                if p.ticker not in known:
                    records.append(SettlementRecord(p.ticker, SettlementSource.HISTORICAL_POSITION_ONLY,
                                                    p.exchange_index, None, None, None, None, None, None, None, None,
                                                    None, None, p.realized_pnl, _SETTLEMENT_FIELDS[1:]))
                    gaps.append(f"SETTLEMENT_DETAIL_UNAVAILABLE: subaccount {n} {p.ticker} is archived; only its "
                                "position history is known (ACC-12)")
            settlements = tuple(sorted(records, key=lambda s: s.ticker))
        if cutoff is not None:
            gaps.append(f"SETTLEMENT_DETAIL_ARCHIVED: subaccount {n} markets settled before "
                        f"{cutoff.market_settled.isoformat()} have no historical settlement endpoint (ACC-12)")

    mine = tuple(lo for lo in local if lo.scope_key == scope.key())
    live_orders = items_if(AccountEndpoint.ORDERS)
    open_orders = None if live_orders is None else tuple(o for o in live_orders if o.status == "resting")
    attribution = _Attribution((), (), MappingProxyType({}), tuple(lo.reservation_id for lo in mine), (), ())
    external: tuple[ExternalOrder, ...] | None = None
    if open_orders is not None:
        attribution = _attribute(open_orders, orders, mine, policy)
        problems += attribution.problems
        observations += attribution.observations
        external = attribution.external

    holdings = None
    if positions is not None:
        rows: dict[tuple[str, Side], Decimal] = {}
        for p in positions:
            if p.position != 0:  # ACC-08: negative is NO contracts
                rows[(p.ticker, Side.YES if p.position > 0 else Side.NO)] = abs(p.position)
        holdings = MappingProxyType(rows)

    cash = balance.balance_dollars if balance is not None and complete_overall else None
    snapshot = SnapshotInputs(scope, observed_at, cash, CASH_BASIS if cash is not None else CashBasis.UNKNOWN,
                              holdings, external, attribution.attributed if external is not None else ())
    return SubaccountReconciliation(
        n, scope, work.stability, work.samples, balance, positions, historical_positions, orders, open_orders, fills,
        fills_by_order, settlements, attribution.attributed, external, attribution.matched, attribution.unlisted,
        tuple(problems), tuple(gaps), tuple(observations), snapshot)


def _cutoff_order(a: w.HistoricalCutoff, b: w.HistoricalCutoff) -> str:
    """'SAME', 'ADVANCED' or 'REGRESSED' (any field earlier) from a to b."""
    pairs = ((a.market_settled, b.market_settled), (a.trades_created, b.trades_created),
             (a.orders_updated, b.orders_updated))
    if any(y < x for x, y in pairs):
        return "REGRESSED"
    return "SAME" if all(x == y for x, y in pairs) else "ADVANCED"


def reconcile_account(plan: AccountReadPlan, send: ReadSender, *, clock: Clock,
                      local_orders: Iterable[LocalOrder] = (),
                      external_cash_policy: ExternalCashPolicy = ExternalCashPolicy.UNKNOWN_BLOCKS
                      ) -> AccountReconciliation:
    """Read everything `plan` names through `send` and reconcile it (see the module docstring). Never writes."""
    if not isinstance(plan, AccountReadPlan):
        raise AccountReadError("plan must be an AccountReadPlan")
    if not callable(send) or not callable(clock):
        raise AccountReadError("send and clock must be callables")
    if not isinstance(external_cash_policy, ExternalCashPolicy):
        raise AccountReadError("external_cash_policy must be an ExternalCashPolicy")
    local = tuple(local_orders)
    if not all(isinstance(lo, LocalOrder) for lo in local):
        raise AccountReadError("local_orders must be LocalOrder values")
    reader = _Reader(plan, send, clock)
    started = reader.now()
    problems: list[str] = []
    planned_keys = {plan.scope_for(n).key() for n in plan.subaccounts}
    account_prefix = f"{plan.scope.environment.value}:{plan.scope.account_ref}:"
    outside = sorted({lo.scope_key for lo in local if lo.scope_key.startswith(account_prefix)} - planned_keys)
    alias = AccountScope(plan.scope.environment, plan.scope.account_ref, 0).key()
    if any(lo.scope_key == alias for lo in local):
        problems.append(f"LOCAL_SCOPE_ALIAS: local orders are keyed {alias}; the primary subaccount's canonical scope "
                        f"is {plan.scope_for(0).key() if 0 in plan.subaccounts else 'subaccount None'}")
    problems += [f"ENDPOINT_NOT_IN_PLAN: {e.value}" for e in AccountEndpoint if e not in plan.endpoints]
    global_kw = dict(subaccount=None, tier=Tier.GLOBAL)

    def as_of(sample: int) -> datetime | None:
        got = reader.single(w.build_get_user_data_timestamp(plan.scope), w.parse_user_data_timestamp,
                            sample=sample, **global_kw)
        return got.items[0] if got.items is not None else None

    def cutoff(sample: int) -> w.HistoricalCutoff | None:
        got = reader.single(w.build_get_historical_cutoff(plan.scope), w.parse_historical_cutoff, sample=sample,
                            **global_kw)
        return got.items[0] if got.items is not None else None

    as_of_start = as_of(0)
    cutoffs = [cutoff(0)]
    works = [_read_subaccount(reader, n) for n in plan.subaccounts]
    as_of_end = as_of(1)
    cutoffs.append(cutoff(1))
    if cutoffs[0] is not None and cutoffs[1] is not None and _cutoff_order(cutoffs[0], cutoffs[1]) == "ADVANCED":
        # A record may have moved live -> historical after its historical read: read that tier again.
        works = [_Work(wk.n, wk.live, _read_historical(reader, wk.n, wk.samples), wk.stability, wk.samples,
                       wk.problems, wk.seen) for wk in works]
        cutoffs.append(cutoff(2))
        moved_note = "CUTOFF_ADVANCED_DURING_READ: the historical tier was read again"
    else:
        moved_note = None

    # Freshness of the venue's user data (ACC-16: approximate).
    if as_of_start is None or as_of_end is None:
        problems.append("USER_DATA_AS_OF_UNAVAILABLE: the venue's data timestamp could not be read")
    else:
        if started - as_of_start > plan.max_data_lag:
            problems.append(f"STALE_USER_DATA: as_of {as_of_start.isoformat()} trails the read start "
                            f"{started.isoformat()} by more than {plan.max_data_lag}")
        if as_of_start > started + CLOCK_SKEW:
            problems.append(f"USER_DATA_AS_OF_IN_FUTURE: as_of {as_of_start.isoformat()} is after the read start "
                            f"{started.isoformat()} (clock disagreement)")
        if as_of_end < as_of_start:
            problems.append(f"USER_DATA_AS_OF_REGRESSED: {as_of_end.isoformat()} < {as_of_start.isoformat()}")
    # The partition: the cutoff must be known and must have held still (or advanced once and been re-read).
    observations: list[str] = [moved_note] if moved_note else []
    if outside:
        observations.append(f"LOCAL_ORDERS_OUTSIDE_PLAN: {outside} hold local orders this plan does not read")
    if any(x is None for x in cutoffs):
        problems.append("CUTOFF_UNAVAILABLE: the live/historical partition is unknown")
    else:
        steps = [_cutoff_order(a, b) for a, b in zip(cutoffs, cutoffs[1:])]
        if "REGRESSED" in steps:
            problems.append("CUTOFF_REGRESSED: the historical cutoff went backwards during the read")
        elif len(steps) > 1 and steps[1] != "SAME":
            problems.append("CUTOFF_MOVING: the cutoff advanced again after the historical tier was re-read")
    fresh = not any(p.startswith(("USER_DATA_", "STALE_USER_DATA")) for p in problems)
    partition_ok = not any(p.startswith("CUTOFF_") for p in problems)
    last_cutoff = cutoffs[-1]
    observed_at = started if as_of_start is None else min(started, as_of_start)

    # Status needs every subaccount's problems first; cash is then filled in only for a COMPLETE result.
    draft = [_finalize(wk, plan, complete_overall=False, fresh=fresh, partition_ok=partition_ok,
                       observed_at=observed_at, cutoff=last_cutoff,
                       local=local, policy=external_cash_policy) for wk in works]
    all_problems = problems + [p for s in draft for p in s.problems]
    any_complete = any(r.complete for r in reader.streams if r.subaccount is not None)
    if not any_complete:
        status = ReconciliationStatus.FAILED
    elif all_problems:
        status = ReconciliationStatus.PARTIAL
    else:
        status = ReconciliationStatus.COMPLETE
    subs = draft if status is not ReconciliationStatus.COMPLETE else [
        _finalize(wk, plan, complete_overall=True, fresh=fresh, partition_ok=partition_ok,
                  observed_at=observed_at, cutoff=last_cutoff, local=local, policy=external_cash_policy)
        for wk in works]
    coverage = {}
    for s, wk in zip(subs, works):
        for e in AccountEndpoint:
            tiers = [wk.live.get(e)] + ([wk.historical.get(e)] if e in _HISTORICAL else [])
            coverage[(s.subaccount, e)] = all(g is not None and g.items is not None for g in tiers) and \
                wk.stability is Stability.STABLE
    manifest = ReadManifest(plan, started, reader.now(), reader.requests, tuple(reader.pages), tuple(reader.streams),
                            as_of_start, as_of_end, tuple(x for x in cutoffs if x is not None),
                            MappingProxyType(coverage))
    return AccountReconciliation(status, manifest, tuple(subs), tuple(all_problems),
                                 tuple(g for s in subs for g in s.gaps),
                                 tuple(observations + [o for s in subs for o in s.observations]))
