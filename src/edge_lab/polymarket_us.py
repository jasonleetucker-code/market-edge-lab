"""Polymarket US public-data adapter (read-only): catalog, identity, books, settlement.

Polymarket US is the CFTC-regulated US exchange (QCX LLC, cleared by QC Clearing LLC). It is
not Polymarket International, which is a separate venue (`venues.POLYMARKET_INTERNATIONAL`).
Only the documented public gateway is used: https://gateway.polymarket.us, which the docs
describe as needing no API key (docs.polymarket.us/api-reference/introduction, read
2026-09-23). The authenticated trading API is out of scope.

What the docs establish, and how it is mapped (see experiments/multi_venue/):

- **One instrument per market.** A market has one instrument, the YES (long) side, named by
  the market side with `long: true`. The book's prices always refer to YES. Buying NO is
  selling YES: the docs say "If you want to buy NO at $0.40, you're really selling YES at
  $0.60". So the executable YES buy price is the best offer, and the executable NO buy
  price is 1 minus the best YES bid, with the bid's quantity.
- **Units.** Prices are `Amount` objects, a USD decimal string per contract, between 0 and 1;
  a winning contract settles at $1.00. Book quantities are strings "in contracts", which
  "may contain decimals for partial-contract markets". `minimumTradeQty` and
  `orderPriceMinTickSize` are per market. They are kept as given and never inferred.
- **Books.** `GET /v1/markets/{slug}/book` gives price levels with quantities, so it can
  price an executable quote. `GET /v1/markets/{slug}/bbo` gives the best prices, but only a
  total rounded share count per side, not the size at the best price. So BBO alone never
  becomes an `ExecutableQuote` (BOOK_MISSING).
- **Rules.** The market `description` holds the resolution text. It is hashed. Rules
  equivalence with any other venue is never established here: `rules_resolved=False`.
- **Timing.** The docs define `startDate` and `endDate` only as "Market start/end date"
  ("end/expiration date" in the filter docs). They say nothing about trading close,
  resolution or payout timing. So `MarketTiming` carries only the lifecycle status (the
  gateway enum as a plain word, e.g. "open") and, for
  automated crypto markets, `assetPriceTerms.windowEnd`, which the docs define as the end of
  the measurement window. Everything else is None, and the starter policy fails closed.
- **Fees.** Markets carry `feeCoefficient` and the docs publish a fee formula. No fee model
  for this venue has been verified in this repository: `fee_schedules.schedule_for` returns
  UNSUPPORTED, so every opportunity rejects FEE_UNSUPPORTED. The coefficient is recorded as
  raw metadata only.
- **Catalog completeness.** `GET /v1/markets` pages by `limit`/`offset` and returns no total
  and no cursor, and the docs publish no maximum page size. So a short page is not proof
  of the end: a scan is COMPLETE only when every page succeeded and the last page came
  back empty, with no filters. A filtered, failed or partial scan is never evidence that
  a market does not exist.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlencode

from . import http
from .discovery import CatalogCoverage, CoverageState
from .opportunity import Event, ExecutableQuote, Market, MarketStatus, MarketTiming, Payoff

VENUE = "polymarket_us"
SOURCE_ID = "polymarket_us_public"
BASE_URL = "https://gateway.polymarket.us"
PARSER_VERSION = "1"
USER_AGENT = "market-edge-lab/0.1 (read-only research; polymarket_us public adapter)"
# Public endpoints allow 20 requests/s per IP (docs Rate Limits). Stay far below it.
MIN_INTERVAL_S = 0.5
MAX_PAGES = 200
PRICE_UNIT = "USD per contract (Amount.value decimal string), YES side"
QUANTITY_UNIT = "contracts (decimal string; may be fractional on partial-contract markets)"
PAYOUT_UNIT = "USD 1.00 per winning contract (standard settlement; alternative settlement per market rules)"

OPEN_STATUSES = frozenset({"MARKET_STATUS_OPEN"})
CLOSED_STATUSES = frozenset({"MARKET_STATUS_CLOSED", "MARKET_STATUS_RESOLVING", "MARKET_STATUS_RESOLVED",
                             "MARKET_STATUS_HALTED"})
RULES_NOT_ESTABLISHED = "rules equivalence not established (Polymarket US rules text captured and hashed only)"


@dataclass(frozen=True)
class MarketMeta:
    """Raw venue fields kept beside the generic `Market` (never reinterpreted)."""

    market_id: str
    slug: str | None
    numeric_id: str | None
    question: str | None
    category: str | None
    start_date_raw: str | None
    end_date_raw: str | None
    status_raw: str | None
    fee_coefficient_raw: str | None  # recorded only; no fee model is applied
    minimum_trade_qty_raw: str | None
    price_tick_raw: str | None
    outcomes_raw: str | None
    long_side: str | None
    short_side: str | None
    price_unit: str = PRICE_UNIT
    quantity_unit: str = QUANTITY_UNIT


def market_id(slug: str) -> str:
    return f"{VENUE}:{slug}"


def event_id(native: str) -> str:
    return f"{VENUE}:{native}"


def _text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return None if value in (None, "") else str(value)


def rules_sha256(raw: Mapping[str, Any]) -> str | None:
    text = raw.get("description")
    if not isinstance(text, str) or not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sides(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    long_side = short_side = None
    for side in raw.get("marketSides") or []:
        if not isinstance(side, Mapping):
            continue
        if side.get("long") is True and long_side is None:
            long_side = _text(side, "description")
        elif side.get("long") is False and short_side is None:
            short_side = _text(side, "description")
    return long_side, short_side


def lifecycle_word(status: str | None) -> str | None:
    """The gateway status as a plain lifecycle word: "MARKET_STATUS_OPEN" -> "open".

    Shared policies (`starter_policy`) read lowercase words such as "open". The raw enum is
    kept unchanged in `MarketMeta.status_raw`."""
    if not status:
        return None
    return status.removeprefix("MARKET_STATUS_").lower()


def timing_from_market(raw: Mapping[str, Any], *, source: str | None = None) -> MarketTiming:
    terms = raw.get("assetPriceTerms")
    window_end = _text(terms, "windowEnd") if isinstance(terms, Mapping) else None
    return MarketTiming(event_end_utc=window_end, lifecycle_status=lifecycle_word(_text(raw, "status")),
                        source=source)


def status_of(raw: Mapping[str, Any]) -> MarketStatus:
    status = str(raw.get("status") or "")
    if status in OPEN_STATUSES:
        return MarketStatus.OPEN
    if status in CLOSED_STATUSES:
        return MarketStatus.CLOSED
    return MarketStatus.UNKNOWN  # includes MARKET_STATUS_UNSPECIFIED and values newer than the docs


def market_from_polymarket(raw: Mapping[str, Any], *, event_id_for_market: Mapping[str, str] | None = None,
                           timing_source: str | None = None) -> tuple[Market, MarketMeta]:
    """A generic `Market` plus the raw metadata. Markets carry no event reference in the
    documented schema, so the event comes from an events listing (`event_id_for_market`,
    keyed by slug); without one it is `unmapped:` and can never match an event."""
    slug = _text(raw, "slug") or f"id-{raw.get('id')}"
    long_side, short_side = _sides(raw)
    mid = market_id(slug)
    mapped = (event_id_for_market or {}).get(slug)
    question = _text(raw, "question")
    yes = long_side or question or slug
    market = Market(
        venue=VENUE, market_id=mid, native_id=slug,
        event_id=mapped or f"unmapped:{VENUE}:{slug}",
        outcome=yes,
        payoff=Payoff(kind="binary", amount=Decimal("1"),
                      yes_condition=f"long side '{yes}' per the market rules text (not parsed)"),
        rules_sha256=rules_sha256(raw),
        status=status_of(raw),
        rules_resolved=False,
        rules_detail=RULES_NOT_ESTABLISHED,
        timing=timing_from_market(raw, source=timing_source),
    )
    fee = raw.get("feeCoefficient")
    meta = MarketMeta(
        market_id=mid, slug=_text(raw, "slug"), numeric_id=_text(raw, "id"), question=question,
        category=_text(raw, "category"), start_date_raw=_text(raw, "startDate"), end_date_raw=_text(raw, "endDate"),
        status_raw=_text(raw, "status"), fee_coefficient_raw=None if fee is None else str(fee),
        minimum_trade_qty_raw=_text(raw, "minimumTradeQty"), price_tick_raw=_text(raw, "orderPriceMinTickSize"),
        outcomes_raw=_text(raw, "outcomes"), long_side=long_side, short_side=short_side,
    )
    return market, meta


def event_from_polymarket(raw: Mapping[str, Any]) -> tuple[Event, dict[str, str]]:
    """A generic `Event` plus {market slug: event id} for its embedded markets.

    The settlement identity is venue-local and marked unverified, so no cross-venue
    equivalence can follow from it by construction."""
    native = _text(raw, "slug") or f"id-{raw.get('id')}"
    eid = event_id(native)
    start = _text(raw, "startTime") or _text(raw, "startDate")
    date = _text(raw, "eventDate") or (start[:10] if start else None)
    event = Event(
        domain=str(raw.get("category") or "unknown").lower(), event_id=eid, target_date=date or "UNKNOWN",
        target_time_utc=start, outcome_cluster=eid,
        settlement_identity=f"{VENUE}:unverified:{native}:{raw.get('resolutionSource') or 'resolution source not stated'}",
    )
    mapping = {}
    for m in raw.get("markets") or []:
        if isinstance(m, Mapping) and _text(m, "slug"):
            mapping[str(m["slug"])] = eid
    return event, mapping


def parse_markets_page(payload: Any) -> list[Mapping[str, Any]] | None:
    """The markets of one GET /v1/markets page, or None if the page is malformed."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("markets"), list):
        return None
    return [m for m in payload["markets"] if isinstance(m, Mapping)]


def parse_events_page(payload: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("events"), list):
        return None
    return [e for e in payload["events"] if isinstance(e, Mapping)]


# --------------------------------------------------------------------------- books


def _amount(value: Any) -> Decimal | None:
    if not isinstance(value, Mapping) or value.get("currency") not in ("USD", None):
        raise ValueError(f"price is not a USD amount: {value!r}")
    try:
        out = Decimal(str(value.get("value")))
    except InvalidOperation:
        raise ValueError(f"unparseable price {value!r}") from None
    if not out.is_finite():
        raise ValueError(f"invalid price {value!r}")
    return out


def _levels(raw: Any) -> list[tuple[Decimal, Decimal]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("book side is not a list")
    out = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ValueError(f"malformed level {entry!r}")
        price = _amount(entry.get("px"))
        try:
            qty = Decimal(str(entry.get("qty")))
        except InvalidOperation:
            raise ValueError(f"unparseable quantity {entry!r}") from None
        if not qty.is_finite() or qty < 0 or price is None or not 0 <= price <= 1:
            raise ValueError(f"invalid level {entry!r}")
        out.append((price, qty))
    return out


def _best(levels: list[tuple[Decimal, Decimal]], *, highest: bool) -> tuple[Decimal | None, Decimal | None]:
    live = [(p, q) for p, q in levels if q > 0]
    if not live:
        return None, None
    top = (max if highest else min)(p for p, _ in live)
    return top, sum((q for p, q in live if p == top), Decimal(0))


def quotes_from_book(slug: str, payload: Mapping[str, Any] | None, *, received_at_utc: str | None,
                     evidence_id: str | None) -> dict[str, ExecutableQuote]:
    """YES and NO executable quotes from one captured GET /v1/markets/{slug}/book payload.

    YES buys at the best offer (its quantity is the size). NO buys by selling YES at the best
    bid: price 1 - bid, size = the bid's quantity. {} when there is no book (BOOK_MISSING)."""
    data = payload.get("marketData") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return {}
    mid = market_id(slug)
    source_ts = _text(data, "transactTime")
    if data.get("marketSlug") not in (None, slug):
        anomaly = f"book is for {data.get('marketSlug')!r}, not {slug!r}"
        return {s: ExecutableQuote(VENUE, mid, s, None, None, None, received_at_utc, source_ts, evidence_id,
                                   anomaly=anomaly) for s in ("YES", "NO")}
    try:
        bid, bid_qty = _best(_levels(data.get("bids")), highest=True)
        ask, ask_qty = _best(_levels(data.get("offers")), highest=False)
    except ValueError as exc:
        return {s: ExecutableQuote(VENUE, mid, s, None, None, None, received_at_utc, source_ts, evidence_id,
                                   anomaly=f"malformed book: {exc}") for s in ("YES", "NO")}
    anomaly = None
    if bid is not None and ask is not None and bid >= ask:
        anomaly = f"crossed book: bid {bid} >= offer {ask}"
    state = data.get("state")
    if anomaly is None and state != "MARKET_STATE_OPEN":
        anomaly = f"book state {state or 'missing'} is not open"  # a missing state fails closed
    return {
        "YES": ExecutableQuote(VENUE, mid, "YES", best_bid=bid, best_ask=ask,
                               displayed_size=ask_qty if ask is not None else Decimal(0),
                               received_at_utc=received_at_utc, source_timestamp_utc=source_ts,
                               evidence_id=evidence_id, anomaly=anomaly),
        "NO": ExecutableQuote(VENUE, mid, "NO", best_bid=None if ask is None else Decimal(1) - ask,
                              best_ask=None if bid is None else Decimal(1) - bid,
                              displayed_size=bid_qty if bid is not None else Decimal(0),
                              received_at_utc=received_at_utc, source_timestamp_utc=source_ts,
                              evidence_id=evidence_id, anomaly=anomaly),
    }


@dataclass(frozen=True)
class BboSummary:
    """Top of book from GET /v1/markets/{slug}/bbo. Display data only: there is no size at
    the best price (askShares/bidShares are rounded totals over all levels), so it is never
    an executable quote."""

    market_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    bid_shares_total_rounded: str | None
    ask_shares_total_rounded: str | None
    state: str | None
    executable: bool = False


def bbo_summary(slug: str, payload: Mapping[str, Any] | None) -> BboSummary | None:
    data = payload.get("marketData") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return None
    try:
        bid = _amount(data["bestBid"]) if data.get("bestBid") is not None else None
        ask = _amount(data["bestAsk"]) if data.get("bestAsk") is not None else None
    except ValueError:
        bid = ask = None
    return BboSummary(market_id(slug), bid, ask, _text(data, "bidShares"), _text(data, "askShares"),
                      _text(data, "state"))


def settlement_value(payload: Any) -> Decimal | None:
    """The settlement price from GET /v1/markets/{slug}/settlement; None when absent."""
    if not isinstance(payload, Mapping) or payload.get("settlement") is None:
        return None
    try:
        value = Decimal(str(payload["settlement"]))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


# --------------------------------------------------------------------------- catalog reads


def markets_url(*, limit: int, offset: int, extra: Sequence[tuple[str, str]] = ()) -> str:
    if not 0 < limit <= 1000 or offset < 0:
        raise ValueError("limit must be in (0, 1000] and offset >= 0")
    return f"{BASE_URL}/v1/markets?{urlencode([('limit', str(limit)), ('offset', str(offset)), *extra])}"


def book_url(slug: str) -> str:
    return f"{BASE_URL}/v1/markets/{quote(slug, safe='')}/book"


def read_catalog(*, limit: int = 100, max_pages: int = MAX_PAGES, extra: Sequence[tuple[str, str]] = (),
                 opener: http.Opener | None = None, pacer: http.Pacer | None = None,
                 on_page: Callable[[dict[str, Any], http.FetchResult], None] | None = None,
                 ) -> tuple[list[Mapping[str, Any]], CatalogCoverage]:
    """Every market page of GET /v1/markets, in offset order, with an honest coverage record.

    The docs publish no maximum page size, and the server may return fewer rows than asked
    for, so a short page proves nothing. The scan is COMPLETE only after a page returns
    zero rows. A failed or malformed page stops it (PARTIAL, or FAILED if no page was read),
    and so does the `max_pages` cap (PARTIAL). A scan with `extra` filters covers only that
    filter: it is recorded in the endpoint and is never a full-catalog COMPLETE (PARTIAL).
    `on_page` receives each raw page, for immutable storage. Not wired to any schedule."""
    pacer = pacer or http.Pacer(MIN_INTERVAL_S)
    markets: list[Mapping[str, Any]] = []
    pages = 0
    last_time = None
    endpoint = f"{BASE_URL}/v1/markets" + (f"?{urlencode(list(extra))}" if extra else "")
    for page in range(max_pages):
        url = markets_url(limit=limit, offset=page * limit, extra=extra)
        try:
            payload, result = http.fetch_json_result(url, headers={"User-Agent": USER_AGENT}, opener=opener,
                                                     pacer=pacer)
        except http.HttpFetchError as exc:
            state = CoverageState.PARTIAL if pages else CoverageState.FAILED
            return markets, CatalogCoverage(VENUE, endpoint, state, pages, len(markets), last_time,
                                            f"page at offset {page * limit} failed: {exc}")
        rows = parse_markets_page(payload)
        if rows is None:
            state = CoverageState.PARTIAL if pages else CoverageState.FAILED
            return markets, CatalogCoverage(VENUE, endpoint, state, pages, len(markets), result.received_at_utc,
                                            f"page at offset {page * limit} is malformed")
        if on_page is not None:
            on_page(payload, result)
        pages += 1
        last_time = result.received_at_utc
        markets.extend(rows)
        if not rows:
            return markets, _terminal_coverage(endpoint, pages, len(markets), last_time, filtered=bool(extra))
    return markets, CatalogCoverage(VENUE, endpoint, CoverageState.PARTIAL, pages, len(markets), last_time,
                                    f"stopped at the {max_pages}-page cap before an empty page")


def _terminal_coverage(endpoint: str, pages: int, items: int, as_of: str | None, *, filtered: bool) -> CatalogCoverage:
    if filtered:
        return CatalogCoverage(VENUE, endpoint, CoverageState.PARTIAL, pages, items, as_of,
                               "every page of a FILTERED listing read (to an empty page); covers that filter only, "
                               "never the full catalog")
    return CatalogCoverage(VENUE, endpoint, CoverageState.COMPLETE, pages, items, as_of,
                           "every page read, ending with an empty page. Offset paging has no snapshot isolation, so "
                           "markets listed or delisted during the scan can be missed or repeated")


def coverage_from_pages(page_sizes: Sequence[int | None], *, as_of_utc: str | None,
                        extra: Sequence[tuple[str, str]] = ()) -> CatalogCoverage:
    """Coverage for stored pages (None = a failed or malformed page), in offset order.
    COMPLETE needs a final page with zero rows and no filters."""
    endpoint = f"{BASE_URL}/v1/markets" + (f"?{urlencode(list(extra))}" if extra else "")
    items = 0
    for i, size in enumerate(page_sizes):
        if size is None:
            state = CoverageState.PARTIAL if i else CoverageState.FAILED
            return CatalogCoverage(VENUE, endpoint, state, i, items, as_of_utc, f"page {i} failed")
        items += size
        if size == 0:
            return _terminal_coverage(endpoint, i + 1, items, as_of_utc, filtered=bool(extra))
    return CatalogCoverage(VENUE, endpoint, CoverageState.PARTIAL if page_sizes else CoverageState.FAILED,
                           len(page_sizes), items, as_of_utc, "no empty final page: the listing may continue")
