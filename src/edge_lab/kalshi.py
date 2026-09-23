from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import time

from .http import HttpFetchError, Pacer, fetch, fetch_json_result
from .sources import get_source
from .storage import SnapshotStore

SOURCE = get_source("kalshi_public")
SETTLEMENT_SOURCE = get_source("kalshi_settlement")
BASE_URL = SOURCE.base_url
# Public endpoints throttled at ~4 req/s sustained (probe 2026-09-22): stay well below.
PACER = Pacer(0.6)
MAX_PAGES = 50
PAGE_LIMIT = 1000


class PaginationError(RuntimeError):
    """A paginated listing could not be retrieved completely."""


def _get(url: str) -> tuple[dict[str, Any], Any]:
    return fetch_json_result(url, pacer=PACER)


def _save(
    store: SnapshotStore, *, run_id: str, kind: str, entity_id: str, url: str, payload, fetch,
    spec=SOURCE,
) -> None:
    store.save_snapshot(
        run_id=run_id,
        source=spec.legacy_name,
        kind=kind,
        entity_id=entity_id,
        url=url,
        payload=payload,
        fetch=fetch,
        source_id=spec.source_id,
        parser_version=spec.parser_version,
        schema_version=spec.schema_version,
    )


def paginate_markets(
    store: SnapshotStore,
    *,
    run_id: str,
    path: str,
    kind: str,
    entity_id: str,
    max_pages: int = MAX_PAGES,
    spec=SOURCE,
    **query: object,
) -> tuple[list[dict[str, Any]], int]:
    """Follow `cursor` until exhausted, storing every page as its own snapshot.

    Bounded by `max_pages`; a repeated cursor is treated as a loop. Either case
    raises PaginationError *after* the pages already fetched have been stored, so
    the run is recorded as partial rather than silently returning page one.
    Returns (markets, pages).
    """
    markets: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor: str | None = None
    for page in range(1, max_pages + 1):
        url = _url(path, **query, cursor=cursor)
        payload, fetch = _get(url)
        _save(store, run_id=run_id, kind=kind, entity_id=entity_id, url=url, payload=payload,
              fetch=fetch, spec=spec)
        page_markets = payload.get("markets")
        if not isinstance(page_markets, list):
            raise ValueError(f"Kalshi {path} page {page} did not contain a markets list")
        markets.extend(page_markets)
        cursor = payload.get("cursor") or None
        if cursor is None:
            return markets, page
        if cursor in seen:
            raise PaginationError(f"{path} returned a repeated cursor on page {page}; listing incomplete")
        seen.add(cursor)
    raise PaginationError(f"{path} still paginating after {max_pages} pages; listing incomplete")




def _url(path: str, **query: object) -> str:
    base = f"{BASE_URL}{path}"
    clean = {key: value for key, value in query.items() if value is not None}
    return f"{base}?{urlencode(clean)}" if clean else base


def _provenance() -> dict[str, str]:
    return {
        "source_id": SOURCE.source_id,
        "parser_version": SOURCE.parser_version,
        "schema_version": SOURCE.schema_version,
    }


def _best_price(levels: list[list[Any]] | None) -> Decimal | None:
    if not levels:
        return None
    return max(Decimal(str(level[0])) for level in levels)


def summarize_orderbook(payload: dict[str, Any]) -> dict[str, Decimal | None]:
    """Return best bids and implied asks from Kalshi's bid-only binary book."""
    book = payload.get("orderbook_fp") or {}
    yes_bid = _best_price(book.get("yes_dollars"))
    no_bid = _best_price(book.get("no_dollars"))

    return {
        "yes_bid": yes_bid,
        "no_bid": no_bid,
        "yes_ask": (Decimal("1") - no_bid) if no_bid is not None else None,
        "no_ask": (Decimal("1") - yes_bid) if yes_bid is not None else None,
    }


def collect_series(
    store: SnapshotStore,
    *,
    run_id: str,
    series_ticker: str = "KXHIGHNY",
    status: str = "open",
    depth: int = 100,
    anomalies: list[str] | None = None,
) -> dict[str, int]:
    """Snapshot one series. Completeness problems are appended to `anomalies`."""
    anomalies = anomalies if anomalies is not None else []
    counts = {"series": 0, "market_lists": 0, "events": 0, "orderbooks": 0}

    series_url = _url(f"/series/{series_ticker}")
    series_payload, series_fetch = _get(series_url)
    store.save_snapshot(
        run_id=run_id,
        source="kalshi",
        kind="series",
        entity_id=series_ticker,
        url=series_url,
        payload=series_payload,
        fetch=series_fetch,
        **_provenance(),
    )
    counts["series"] += 1

    markets, pages = paginate_markets(
        store,
        run_id=run_id,
        path="/markets",
        kind="markets",
        entity_id=series_ticker,
        series_ticker=series_ticker,
        status=status,
        limit=PAGE_LIMIT,
    )
    counts["market_lists"] += pages
    if not markets:
        anomalies.append(f"no {status} markets returned for {series_ticker}")

    seen_events: set[str] = set()

    for market in markets:
        if not isinstance(market, dict):
            anomalies.append(f"non-object market entry skipped: {type(market).__name__}")
            continue

        event_ticker = market.get("event_ticker")
        if event_ticker and event_ticker not in seen_events:
            event_url = _url(f"/events/{event_ticker}")
            event_payload, event_fetch = _get(event_url)
            store.save_snapshot(
                run_id=run_id,
                source="kalshi",
                kind="event",
                entity_id=str(event_ticker),
                url=event_url,
                payload=event_payload,
                fetch=event_fetch,
                **_provenance(),
            )
            counts["events"] += 1
            seen_events.add(str(event_ticker))

        market_ticker = market.get("ticker")
        if not market_ticker:
            anomalies.append("market entry without ticker skipped; its order book was not collected")
            continue

        orderbook_url = _url(f"/markets/{market_ticker}/orderbook", depth=depth)
        orderbook_payload, orderbook_fetch = _get(orderbook_url)
        store.save_snapshot(
            run_id=run_id,
            source="kalshi",
            kind="orderbook",
            entity_id=str(market_ticker),
            url=orderbook_url,
            payload=orderbook_payload,
            fetch=orderbook_fetch,
            **_provenance(),
        )
        counts["orderbooks"] += 1

    return counts


# Document URL fields on a series payload that point to official contract terms.
CONTRACT_DOCUMENT_FIELDS = {
    "contract_terms_url": "kalshi_contract_terms",
    "contract_url": "kalshi_contract_filing",
}


def collect_settlement_evidence(
    store: SnapshotStore,
    *,
    run_id: str,
    series_ticker: str = "KXHIGHNY",
    include_historical: bool = True,
    max_pages: int = MAX_PAGES,
    anomalies: list[str] | None = None,
) -> dict[str, int]:
    """Capture what decides settlement: series rules, settled markets, contract documents.

    - The series payload (settlement_sources, contract URLs) is stored as a JSON snapshot.
    - Every page of settled markets (live `/markets?status=settled` and, optionally,
      `/historical/markets`) is stored; each market carries rules_primary/secondary,
      strikes, result, expiration_value and settlement timestamps.
    - Contract documents are stored as exact bytes in the document store, so a
      changed PDF becomes a new version instead of overwriting the old one.
    """
    anomalies = anomalies if anomalies is not None else []
    counts = {"series": 0, "settled_pages": 0, "historical_pages": 0, "markets": 0, "documents": 0,
              "documents_failed": 0}

    series_url = _url(f"/series/{series_ticker}")
    series_payload, series_fetch = _get(series_url)
    _save(store, run_id=run_id, kind="series", entity_id=series_ticker, url=series_url,
          payload=series_payload, fetch=series_fetch, spec=SETTLEMENT_SOURCE)
    counts["series"] = 1
    series = series_payload.get("series") if isinstance(series_payload.get("series"), dict) else {}

    for field, doc_type in CONTRACT_DOCUMENT_FIELDS.items():
        url = series.get(field)
        if not isinstance(url, str) or not url.startswith("https://"):
            anomalies.append(f"series {series_ticker} has no usable {field}")
            continue
        try:
            document = fetch(url, headers={"Accept": "application/pdf, */*"}, pacer=PACER)
        except HttpFetchError as exc:
            # A blocked or failing contract PDF must not cost the settled-market evidence:
            # record partial coverage and keep collecting.
            counts["documents_failed"] += 1
            anomalies.append(f"contract document {field} not retrieved ({url}): {exc}")
            continue
        _, _, is_new = store.save_document(
            run_id=run_id, source_id=SETTLEMENT_SOURCE.source_id, doc_type=doc_type, fetch=document,
            series_ticker=series_ticker,
        )
        counts["documents"] += 1
        if is_new and len(store.document_versions(url)) > 1:
            # Not an error, but a changed contract document must be noticed.
            anomalies.append(f"contract document changed: new version of {field} ({url})")

    settled, pages = paginate_markets(
        store, run_id=run_id, path="/markets", kind="settled_markets", entity_id=series_ticker,
        max_pages=max_pages, spec=SETTLEMENT_SOURCE, series_ticker=series_ticker, status="settled",
        limit=PAGE_LIMIT,
    )
    counts["settled_pages"] = pages
    counts["markets"] += len(settled)

    if include_historical:
        historical, pages = paginate_markets(
            store, run_id=run_id, path="/historical/markets", kind="historical_markets",
            entity_id=series_ticker, max_pages=max_pages, spec=SETTLEMENT_SOURCE,
            series_ticker=series_ticker, limit=PAGE_LIMIT,
        )
        counts["historical_pages"] = pages
        counts["markets"] += len(historical)

    if not settled:
        anomalies.append(f"no settled markets returned for {series_ticker}")
    return counts


def event_ticker_of(market_ticker: str) -> str:
    """KXHIGHNY-26SEP24-B67.5 -> KXHIGHNY-26SEP24."""
    return market_ticker.rsplit("-", 1)[0]


def refresh_event_settlements(
    store: SnapshotStore,
    *,
    run_id: str,
    event_tickers: list[str],
    max_events: int = 10,
    deadline_s: float = 120.0,
    anomalies: list[str] | None = None,
    clock=time.monotonic,
) -> dict[str, int]:
    """Targeted settlement refresh: `/markets?event_ticker=E` for each pending event only.

    Bounded: at most `max_events` events and 2 pages each, the shared Kalshi pacer, the
    fetch layer's bounded retries, and a run deadline checked before every event. Every
    page is stored as an immutable `event_settlement_markets` snapshot; an unsettled market
    simply has no result yet and leaves its positions pending. No full-history download."""
    anomalies = anomalies if anomalies is not None else []
    counts = {"events_requested": 0, "events_fetched": 0, "markets": 0, "settled_markets": 0}
    tickers = sorted(set(event_tickers))
    if len(tickers) > max_events:
        anomalies.append(f"{len(tickers) - max_events} pending events deferred to the next run (max {max_events})")
        tickers = tickers[:max_events]
    started = clock()
    for ticker in tickers:
        if clock() - started > deadline_s:
            anomalies.append(f"deadline {deadline_s:.0f}s reached; remaining events deferred")
            break
        counts["events_requested"] += 1
        markets, _ = paginate_markets(store, run_id=run_id, path="/markets", kind="event_settlement_markets",
                                      entity_id=ticker, max_pages=2, spec=SETTLEMENT_SOURCE, event_ticker=ticker,
                                      limit=PAGE_LIMIT)
        counts["events_fetched"] += 1
        counts["markets"] += len(markets)
        counts["settled_markets"] += sum(1 for m in markets if isinstance(m, dict) and m.get("result") in ("yes", "no"))
    return counts
