"""Fixture-based collector tests: no network, recorded-shape payloads."""

import pytest

from edge_lab import kalshi
from edge_lab.http import FetchResult
from edge_lab.storage import SnapshotStore


def _fake_fetch(routes):
    def fetch_json_result(url, **kwargs):
        for fragment, payload in routes.items():
            if fragment in url:
                result = FetchResult(url, url, 200, "application/json", b"{}", "2026-09-22T17:00:00+00:00", 1, 1)
                return payload, result
        raise AssertionError(f"unexpected url {url}")

    return fetch_json_result


MARKETS = {
    "markets": [
        {"ticker": "KXHIGHNY-26SEP23-T72", "event_ticker": "KXHIGHNY-26SEP23"},
        {"ticker": "KXHIGHNY-26SEP23-B71.5", "event_ticker": "KXHIGHNY-26SEP23"},
    ],
    "cursor": "",
}


def _routes(markets):
    return {
        "/orderbook": {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
        "/series/": {"series": {"ticker": "KXHIGHNY"}},
        "/events/": {"event": {"event_ticker": "KXHIGHNY-26SEP23"}},
        "/markets?": markets,
    }


def test_collect_series_stores_every_payload_with_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(kalshi, "fetch_json_result", _fake_fetch(_routes(MARKETS)))
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []

    counts = kalshi.collect_series(store, run_id="r", anomalies=anomalies)

    assert counts == {"series": 1, "market_lists": 1, "events": 1, "orderbooks": 2}
    assert anomalies == []
    assert store.run_source_totals("r", "kalshi")[0] == 5


def test_pagination_cursor_is_flagged_as_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(kalshi, "fetch_json_result", _fake_fetch(_routes({**MARKETS, "cursor": "abc"})))
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []
    kalshi.collect_series(store, run_id="r", anomalies=anomalies)
    assert any("paginated" in a for a in anomalies)


def test_empty_market_list_is_an_anomaly_not_silence(tmp_path, monkeypatch):
    monkeypatch.setattr(kalshi, "fetch_json_result", _fake_fetch(_routes({"markets": [], "cursor": ""})))
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []
    kalshi.collect_series(store, run_id="r", anomalies=anomalies)
    assert anomalies and "no open markets" in anomalies[0]


def test_missing_markets_key_is_an_error_not_an_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(kalshi, "fetch_json_result", _fake_fetch(_routes({"error": "maintenance"})))
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    with pytest.raises(ValueError):
        kalshi.collect_series(store, run_id="r")


def test_skipped_market_entries_are_anomalies(tmp_path, monkeypatch):
    markets = {"markets": [{"event_ticker": "KXHIGHNY-26SEP23"}, "garbage"], "cursor": ""}
    monkeypatch.setattr(kalshi, "fetch_json_result", _fake_fetch(_routes(markets)))
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []
    kalshi.collect_series(store, run_id="r", anomalies=anomalies)
    assert any("without ticker" in a for a in anomalies)
    assert any("non-object" in a for a in anomalies)
