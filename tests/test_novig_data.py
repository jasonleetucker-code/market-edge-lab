"""Novig public daily data: index and CSV parsers on committed samples (never executable)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import novig_data as nd, venues
from edge_lab.opportunity import ExecutableQuote
from edge_lab.venues import Capability, ConnectivityStage

FIXTURES = Path(__file__).parent / "fixtures" / "novig"
REPO = Path(__file__).resolve().parents[1]
NOTE = REPO / "experiments/multi_venue/novig_daily_data_capture_2026-09-23.md"


def test_committed_samples_match_the_capture_note():
    note = NOTE.read_text()
    for name in ("index_2026-09-23.json", "2026-09-21_trades_sample.csv", "2026-09-21_markets_sample.csv"):
        digest = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        assert digest in note, name
    for full in ("76eda906ecae5f9af78e2fd9e6aa912672f219cd3bdb1963f97348ebf9385ca4", "37985941",
                 "95d357729b9b7e40558e2b4a0177c24434233d6f39c11ba22ddb673abc56f1a2", "5787446"):
        assert full in note


def test_index_lists_trade_and_market_dates_separately():
    idx = nd.parse_index((FIXTURES / "index_2026-09-23.json").read_bytes())
    assert idx.trade_dates[0] == "2026-08-03" and idx.trade_dates[-1] == "2026-09-22"
    assert idx.market_dates_present and len(idx.market_dates) == len(idx.trade_dates) - 1
    old = nd.parse_index({"dates": ["2026-08-06"]})
    assert old.market_dates == () and old.market_dates_present is False  # absent reads as empty
    for bad in ({}, {"dates": "2026-08-06"}, {"dates": ["08/06/2026"]}, {"dates": [], "marketDates": "x"}):
        with pytest.raises(nd.NovigDataError):
            nd.parse_index(bad)


def test_trade_rows_are_sides_with_probability_prices_and_raw_units():
    sides = nd.parse_trades((FIXTURES / "2026-09-21_trades_sample.csv").read_bytes())
    assert len(sides) == 7 and nd.trade_count(sides) == 3  # count TAKER rows, not all rows
    first = sides[0]
    assert (first.side, first.cost_raw, first.qty_raw) == ("TAKER", "9.7994", "37.69")
    assert first.price == Decimal("9.7994") / Decimal("37.69") and 0 < first.price < 1
    combo_taker, combo_maker = sides[2], sides[3]
    assert combo_taker.trade_type == "COMBO" and combo_taker.league is None and combo_taker.legs == 2
    assert combo_taker.price + combo_maker.price == 1  # the two sides stake the notional
    tennis = [s for s in sides if s.market_id.endswith("32bf3d23e24f")]
    taker = next(s for s in tennis if s.side == "TAKER")
    assert sum(Decimal(s.qty_raw) for s in tennis if s.side == "MAKER") == Decimal(taker.qty_raw)
    assert nd.taker_notional(sides) == Decimal("37.69") + Decimal("26.75") + Decimal("298.76")
    assert all(s.executable is False for s in sides)


def test_market_rows_convert_cents_and_keep_missing_as_none():
    rows = nd.parse_markets((FIXTURES / "2026-09-21_markets_sample.csv").read_bytes())
    assert len(rows) == 5
    untraded, traded = rows[0], rows[1]
    assert (untraded.open, untraded.close) == (None, None) and untraded.daily_volume_raw == "0.00"
    assert traded.close == Decimal("0.675") and traded.status == "finalized"
    assert rows[2].report_ticker == "COMBO" and rows[2].open == rows[2].close
    assert all(r.executable is False for r in rows)


def test_columns_are_read_by_name_and_extra_columns_are_tolerated():
    text = "side,qty,cost,legs,tradeType,marketType,league,contractSeries,marketId,outcomeId,timestamp,newcol\n" \
           "TAKER,10,4.5,1,STRAIGHT,MONEY,NBA,Basketball Moneyline,m,o,2026-08-04T17:03:11Z,x\n"
    (row,) = nd.parse_trades(text)
    assert row.price == Decimal("0.45") and row.market_id == "m"


@pytest.mark.parametrize("text", [
    "timestamp,outcomeId\n1,2\n",  # missing columns
    ",".join(nd.TRADE_COLUMNS) + "\nt,o,m,s,l,t,STRAIGHT,1,5,4,TAKER\n",  # cost/qty > 1
    ",".join(nd.TRADE_COLUMNS) + "\nt,o,m,s,l,t,STRAIGHT,1,1,4,BUYER\n",  # unknown side
    ",".join(nd.TRADE_COLUMNS) + "\nt,o,m,s,l,t,STRAIGHT,1,,4,TAKER\n",  # empty cost
    ",".join(nd.TRADE_COLUMNS) + "\nt,o,m,s,l,t,SPREAD,1,1,4,TAKER\n",  # unknown trade type
])
def test_malformed_trades_raise(text):
    with pytest.raises(nd.NovigDataError):
        nd.parse_trades(text)


@pytest.mark.parametrize("row", ["2026-09-21,m,T,0,0,,,,,settled", "2026-09-21,m,T,0,0,101,1,1,1,active",
                                 "21/09/2026,m,T,0,0,,,,,active", "2026-09-21,m,T,x,0,,,,,active"])
def test_malformed_markets_raise(row):
    with pytest.raises(nd.NovigDataError):
        nd.parse_markets(",".join(nd.MARKET_COLUMNS) + "\n" + row + "\n")


def test_no_executable_quote_and_live_api_needs_access():
    sides = nd.parse_trades((FIXTURES / "2026-09-21_trades_sample.csv").read_bytes())
    assert not any(isinstance(s, ExecutableQuote) for s in sides)
    assert not any(isinstance(v, ExecutableQuote) for v in vars(nd).values())
    assert "executable" in {f.name for f in fields(nd.TradeSide)}
    novig = venues.get_venue("novig")
    assert novig.stage(Capability.HISTORY_READ) is ConnectivityStage.TESTED
    for cap in (Capability.CATALOG_READ, Capability.QUOTE_READ, Capability.DEPTH_READ, Capability.ORDER_WRITE):
        assert novig.stage(cap) is ConnectivityStage.NEEDS_ACCESS
    assert any("OAuth" in r for r in nd.LIVE_API_REQUIREMENTS)
    assert nd.file_url("2026-09-21", "trades.csv") == "https://data.novig.com/reporting/trade-data/2026-09-21/trades.csv"
    with pytest.raises(ValueError):
        nd.file_url("../x", "trades.csv")
    assert json.loads((FIXTURES / "index_2026-09-23.json").read_text())
