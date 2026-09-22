from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from .http import fetch_json
from .storage import SnapshotStore

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


def _url(path: str, **query: object) -> str:
    base = f"{BASE_URL}{path}"
    clean = {key: value for key, value in query.items() if value is not None}
    return f"{base}?{urlencode(clean)}" if clean else base


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
) -> dict[str, int]:
    counts = {"series": 0, "market_lists": 0, "events": 0, "orderbooks": 0}

    series_url = _url(f"/series/{series_ticker}")
    series_payload = fetch_json(series_url)
    store.save_snapshot(
        run_id=run_id,
        source="kalshi",
        kind="series",
        entity_id=series_ticker,
        url=series_url,
        payload=series_payload,
    )
    counts["series"] += 1

    markets_url = _url("/markets", series_ticker=series_ticker, status=status)
    markets_payload = fetch_json(markets_url)
    store.save_snapshot(
        run_id=run_id,
        source="kalshi",
        kind="markets",
        entity_id=series_ticker,
        url=markets_url,
        payload=markets_payload,
    )
    counts["market_lists"] += 1

    markets = markets_payload.get("markets") or []
    if not isinstance(markets, list):
        raise ValueError("Kalshi markets payload did not contain a list")

    seen_events: set[str] = set()

    for market in markets:
        if not isinstance(market, dict):
            continue

        event_ticker = market.get("event_ticker")
        if event_ticker and event_ticker not in seen_events:
            event_url = _url(f"/events/{event_ticker}")
            event_payload = fetch_json(event_url)
            store.save_snapshot(
                run_id=run_id,
                source="kalshi",
                kind="event",
                entity_id=str(event_ticker),
                url=event_url,
                payload=event_payload,
            )
            counts["events"] += 1
            seen_events.add(str(event_ticker))

        market_ticker = market.get("ticker")
        if not market_ticker:
            continue

        orderbook_url = _url(f"/markets/{market_ticker}/orderbook", depth=depth)
        orderbook_payload = fetch_json(orderbook_url)
        store.save_snapshot(
            run_id=run_id,
            source="kalshi",
            kind="orderbook",
            entity_id=str(market_ticker),
            url=orderbook_url,
            payload=orderbook_payload,
        )
        counts["orderbooks"] += 1

    return counts
