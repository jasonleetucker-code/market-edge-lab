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


def _paged_fetch(pages, routes):
    """Serve `pages` (a dict cursor->payload, None = first page) for market listings."""
    calls: list[str] = []

    def fetch_json_result(url, **kwargs):
        calls.append(url)
        if "/markets?" in url:
            from urllib.parse import parse_qs, urlparse

            cursor = parse_qs(urlparse(url).query).get("cursor", [None])[0]
            payload = pages[cursor]
        else:
            payload = next(p for frag, p in routes.items() if frag in url)
        return payload, FetchResult(url, url, 200, "application/json", b"{}", "2026-09-22T17:00:00+00:00", 1, 1)

    return fetch_json_result, calls


def test_pagination_follows_every_page_and_stores_each(tmp_path, monkeypatch):
    pages = {
        None: {"markets": [MARKETS["markets"][0]], "cursor": "p2"},
        "p2": {"markets": [MARKETS["markets"][1]], "cursor": "p3"},
        "p3": {"markets": [{"ticker": "KXHIGHNY-26SEP23-T80", "event_ticker": "KXHIGHNY-26SEP23"}], "cursor": ""},
    }
    fake, calls = _paged_fetch(pages, _routes(MARKETS))
    monkeypatch.setattr(kalshi, "fetch_json_result", fake)
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []

    counts = kalshi.collect_series(store, run_id="r", anomalies=anomalies)

    assert counts["market_lists"] == 3
    assert counts["orderbooks"] == 3  # markets from all pages, not just page one
    assert len(store.snapshots_of_kind(source="kalshi", kind="markets")) == 3
    assert anomalies == []


def test_repeated_cursor_is_a_loop_and_fails_after_storing_pages(tmp_path, monkeypatch):
    pages = {None: {"markets": [], "cursor": "same"}, "same": {"markets": [], "cursor": "same"}}
    fake, calls = _paged_fetch(pages, _routes(MARKETS))
    monkeypatch.setattr(kalshi, "fetch_json_result", fake)
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    with pytest.raises(kalshi.PaginationError, match="repeated cursor"):
        kalshi.collect_series(store, run_id="r")
    assert len(store.snapshots_of_kind(source="kalshi", kind="markets")) == 2


def test_pagination_is_bounded(tmp_path, monkeypatch):
    pages = {None: {"markets": [], "cursor": "c1"}, **{f"c{i}": {"markets": [], "cursor": f"c{i+1}"} for i in range(1, 10)}}
    fake, calls = _paged_fetch(pages, _routes(MARKETS))
    monkeypatch.setattr(kalshi, "fetch_json_result", fake)
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    with pytest.raises(kalshi.PaginationError, match="after 3 pages"):
        kalshi.paginate_markets(store, run_id="r", path="/markets", kind="markets", entity_id="S", max_pages=3, limit=1)
    assert len(calls) == 3


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


def test_settlement_evidence_stores_rules_markets_and_contract_bytes(tmp_path, monkeypatch):
    series = {"series": {"ticker": "KXHIGHNY", "contract_url": "https://assets.example.test/filing.pdf",
                         "contract_terms_url": "https://assets.example.test/terms.pdf",
                         "settlement_sources": [{"name": "The Weather Company", "url": "https://weather.com/kalshi"}]}}
    settled_pages = {None: {"markets": [{"ticker": "A"}], "cursor": "p2"}, "p2": {"markets": [{"ticker": "B"}], "cursor": ""}}
    historical = {None: {"markets": [{"ticker": "C"}], "cursor": ""}}

    def fake_json(url, **kwargs):
        from urllib.parse import parse_qs, urlparse

        cursor = parse_qs(urlparse(url).query).get("cursor", [None])[0]
        if "/historical/markets" in url:
            payload = historical[cursor]
        elif "/markets?" in url:
            payload = settled_pages[cursor]
        else:
            payload = series
        return payload, FetchResult(url, url, 200, "application/json", b"{}", "2026-09-22T17:00:00+00:00", 1, 1)

    def fake_fetch(url, **kwargs):
        return FetchResult(url, url, 200, "application/pdf", b"%PDF " + url.encode(), "2026-09-22T17:00:00+00:00", 1, 1)

    monkeypatch.setattr(kalshi, "fetch_json_result", fake_json)
    monkeypatch.setattr(kalshi, "fetch", fake_fetch)
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    anomalies: list[str] = []

    counts = kalshi.collect_settlement_evidence(store, run_id="r", anomalies=anomalies)

    assert counts == {"series": 1, "settled_pages": 2, "historical_pages": 1, "markets": 3, "documents": 2}
    assert anomalies == []
    assert store.document_bytes(store.document_versions("https://assets.example.test/terms.pdf")[0]["sha256"]).startswith(b"%PDF")
    # A changed contract document is kept as a new version and flagged.
    store.start_run("r2")
    monkeypatch.setattr(kalshi, "fetch", lambda url, **kw: FetchResult(url, url, 200, "application/pdf", b"%PDF changed", "2026-09-23T17:00:00+00:00", 1, 1))
    anomalies = []
    kalshi.collect_settlement_evidence(store, run_id="r2", anomalies=anomalies, include_historical=False)
    assert any("contract document changed" in a for a in anomalies)
    assert len(store.document_versions("https://assets.example.test/terms.pdf")) == 2


def test_cli_collector_stores_each_issuance_once(tmp_path, monkeypatch):
    from edge_lab import nws_cli

    text = (
        "CDUS41 KOKX 220620\nCLINYC\n\nCLIMATE REPORT\nNATIONAL WEATHER SERVICE NEW YORK, NY\n"
        "220 AM EDT TUE SEP 22 2026\n\n...THE CENTRAL PARK NY CLIMATE SUMMARY FOR SEPTEMBER 21 2026...\n\n"
        "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM         72    100 PM  95    1895  74     -2       71\n"
    )
    listing = {"@graph": [{"id": "p1", "issuanceTime": "2026-09-22T06:20:00+00:00"}]}
    calls: list[str] = []

    def fake_json(url, **kwargs):
        calls.append(url)
        payload = listing if url.endswith("/NYC") else {"id": "p1", "productText": text, "issuanceTime": "2026-09-22T06:20:00+00:00"}
        return payload, FetchResult(url, url, 200, "application/ld+json", b"{}", "2026-09-22T07:00:00+00:00", 1, 1)

    monkeypatch.setattr(nws_cli, "fetch_json_result", fake_json)
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    first = nws_cli.collect_recent_cli(store, run_id="r", user_agent="t")
    second = nws_cli.collect_recent_cli(store, run_id="r", user_agent="t")
    assert first["products"] == 1 and second == {"lists": 1, "products": 0, "already_stored": 1}
    assert len(calls) == 3  # list, product, list: the stored product is not re-fetched
    (row,) = store.snapshots_of_kind(source="nws_cli", kind="cli_product")
    assert nws_cli.parse_cli(__import__("json").loads(row["payload_json"])["productText"]).max_temp_f == 72
