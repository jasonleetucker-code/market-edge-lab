from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from .http import fetch_json_result
from .sources import get_source
from .storage import SnapshotStore

SOURCE = get_source("kalshi_public")
BASE_URL = SOURCE.base_url


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
    series_payload, series_fetch = fetch_json_result(series_url)
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

    markets_url = _url("/markets", series_ticker=series_ticker, status=status)
    markets_payload, markets_fetch = fetch_json_result(markets_url)
    store.save_snapshot(
        run_id=run_id,
        source="kalshi",
        kind="markets",
        entity_id=series_ticker,
        url=markets_url,
        payload=markets_payload,
        fetch=markets_fetch,
        **_provenance(),
    )
    counts["market_lists"] += 1

    markets = markets_payload.get("markets")
    if not isinstance(markets, list):
        raise ValueError("Kalshi markets payload did not contain a list")
    if not markets:
        anomalies.append(f"no {status} markets returned for {series_ticker}")
    if markets_payload.get("cursor"):
        # We fetch one page. A cursor means more markets exist that we did not
        # collect, so this snapshot of the series is incomplete.
        anomalies.append(f"markets list for {series_ticker} is paginated; later pages not collected")

    seen_events: set[str] = set()

    for market in markets:
        if not isinstance(market, dict):
            anomalies.append(f"non-object market entry skipped: {type(market).__name__}")
            continue

        event_ticker = market.get("event_ticker")
        if event_ticker and event_ticker not in seen_events:
            event_url = _url(f"/events/{event_ticker}")
            event_payload, event_fetch = fetch_json_result(event_url)
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
        orderbook_payload, orderbook_fetch = fetch_json_result(orderbook_url)
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
