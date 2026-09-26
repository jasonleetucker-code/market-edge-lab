"""Reproduces the database growth per NFL game-horizon quoted in docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md
(A5): the real `plan` + `capture` path, offline, with a fake fetch serving the recorded KXNFLGAME listing and
either a recorded Kalshi book (1.4 KB) or a full-depth synthetic book (99 levels a side, about 4.2 KB).

The measured figure is printed (`python -m pytest tests/test_price_observations_nfl_bytes.py -s`), and it is
asserted to stay within a band. A change outside the band means the plan's byte estimates need updating."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import price_observations as po
from edge_lab.http import FetchResult
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
FIX = Path(__file__).parent / "fixtures"
EVENTS = json.loads((FIX / "sports_evidence" / "kalshi_events_KXNFLGAME_open_2026-09-25T022444Z.json")
                    .read_text(encoding="utf-8"))["events"]
RECORDED_BOOK = json.loads((FIX / "forward" / "orderbook_KXHIGHNY-26SEP23-B69.5.json").read_text(encoding="utf-8"))
FULL_BOOK = {"orderbook_fp": {side: [[f"{p / 100:.4f}", f"{1000 + p * 7.31:.2f}"] for p in range(1, 100)]
                              for side in ("yes_dollars", "no_dollars")}}


def _db_bytes(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]


def growth_per_game_horizon(tmp_path: Path, book: dict, horizons: int = 3) -> float:
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    base = _db_bytes(store.path)
    now = [datetime(2026, 9, 26, 0, 5, tzinfo=UTC)]  # 20:05 ET: clear of every protected window
    listings = {e["event_ticker"]: {"cursor": "", "markets": e["markets"]} for e in EVENTS}

    def fake(url, **_kw):
        now[0] += timedelta(seconds=0.3)
        payload = book if "/orderbook" in url else listings[url.split("event_ticker=")[1].split("&")[0]]
        body = json.dumps(payload, separators=(",", ":")).encode()
        return payload, FetchResult(url, url, 200, "application/json", body, now[0].isoformat(), 1, 1)

    n = 0
    original = po.fetch_json_result
    po.fetch_json_result = fake
    try:
        for _ in range(horizons):
            for i in range(0, len(EVENTS), 10):
                chunk, at = EVENTS[i:i + 10], now[0]
                custom = [po.custom_target(venue="kalshi", native_market_id=m["ticker"], at=at)
                          for e in chunk for m in e["markets"]]
                po.plan(store, decisions=[], now=at, custom=custom)
                _, report = po.capture(store, clock=lambda: now[0], sleep=lambda s: None, nfl_enabled=True)
                assert report["requests"] == 3 * len(chunk), report
                n += len(chunk)
                now[0] += timedelta(hours=1)
    finally:
        po.fetch_json_result = original
    return (_db_bytes(store.path) - base) / n


@pytest.mark.parametrize("name, book", [("recorded book", RECORDED_BOOK), ("full-depth book", FULL_BOOK)])
def test_database_growth_per_nfl_game_horizon(tmp_path, name, book):
    per = growth_per_game_horizon(tmp_path, book)
    print(f"{name}: {per:,.0f} bytes of database growth per game-horizon")
    # The plan quotes about 21.5 KB (recorded book) and 22.2 KB (full depth), measured with 96 game-horizons.
    assert 15_000 <= per <= 30_000
