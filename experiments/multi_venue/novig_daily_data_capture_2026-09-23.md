# Novig public daily data: one manual read (2026-09-23)

Documentation: https://docs.novig.com/api-reference/trade-data (read 2026-09-23 about 14:05
UTC). It describes static files behind a CDN at data.novig.com, with no API and no
authentication. No licence terms are stated on that page. The data is used for research
only and not redistributed. Only small samples are committed.

## Reads (GET, no credentials, User-Agent `market-edge-lab/0.1 (research; read-only)`)

| Started (UTC) | URL | Status | Bytes | SHA-256 (full body) | Last-Modified |
|---|---|---|---|---|---|
| 2026-09-23T14:07:23Z | `https://data.novig.com/reporting/trade-data/index.json` | 200 | 1860 | `cd7f265f919d32b67526204c14ee4224de9cfba3ce684dd813e2835d641fca83` | Wed, 23 Sep 2026 09:05:26 GMT |
| 2026-09-23T14:07:29Z | `https://data.novig.com/reporting/trade-data/2026-09-21/trades.csv` | 200 | 37985941 | `76eda906ecae5f9af78e2fd9e6aa912672f219cd3bdb1963f97348ebf9385ca4` | Tue, 22 Sep 2026 09:07:38 GMT |
| 2026-09-23T14:07:30Z | `https://data.novig.com/reporting/trade-data/2026-09-21/markets.csv` | 200 | 5787446 | `95d357729b9b7e40558e2b4a0177c24434233d6f39c11ba22ddb673abc56f1a2` | Tue, 22 Sep 2026 09:07:33 GMT |

The index listed 51 trade dates (2026-08-03 to 2026-09-22) and 50 market dates (2026-08-04 to
2026-09-22). 2026-09-21 was chosen because both files were present.

## What the full files showed (parsed by `edge_lab.novig_data`, not committed)

- trades.csv: 251,663 side rows, all of which parsed. There were 119,030 TAKER rows (74,555
  STRAIGHT, 44,475 COMBO) and 132,633 MAKER rows. Taker notional (sum of TAKER `qty`) was
  32,474,571.36 contracts. Every `cost/qty` was within [0, 1]. One STRAIGHT taker can match
  several MAKER rows, and their quantities sum to the taker's.
- markets.csv: 63,358 rows, all of which parsed. 37,917 were `finalized` and 25,441
  `active`. 47,005 rows had a close price, in cents.

## Fixtures committed (samples, not the full files)

| Fixture | Contents | SHA-256 |
|---|---|---|
| `tests/fixtures/novig/index_2026-09-23.json` | the full index.json (exact bytes) | `cd7f265f919d32b67526204c14ee4224de9cfba3ce684dd813e2835d641fca83` |
| `tests/fixtures/novig/2026-09-21_trades_sample.csv` | header, the first 4 data rows (a STRAIGHT pair and a COMBO pair), and one STRAIGHT trade with two MAKER rows | `830d17a036c4a4b4573c420893f8650ff7b1d6d44b70729b1857338554b3a1a3` |
| `tests/fixtures/novig/2026-09-21_markets_sample.csv` | header plus 5 rows: active with no trade, finalized with a trade, COMBO, active with a trade, and active with open interest but no trade | `9d68cc626c589e601b4eb67c5489bd90ec853b7b9101c6d234dd7fedcc6e5af7` |

Rows are copied unchanged, in file order within each group.

## Not executable, and what live access would need

End-of-day files are never quotes (`executable=False` on every parsed row). The live NBX API
(catalog, books, settlement, accounts) needs OAuth 2.0 client credentials that the owner
must request from Novig, so it is **NEEDS_ACCESS**. See
`edge_lab.novig_data.LIVE_API_REQUIREMENTS`. The trade-data docs now say one contract pays
$1, which is not yet reflected in `venues.NOVIG.units`. That file is outside this lane's
scope.
