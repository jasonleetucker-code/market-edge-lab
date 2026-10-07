# Kalshi execution fixtures (#160 packages B and F)

Offline fixtures for `edge_lab.execution.kalshi_wire` and `edge_lab.execution.transport`. No fixture came from a
venue: nothing here is DEMO_OBSERVED or PRODUCTION_READ_VERIFIED. All were written on 2026-10-07.

Labels:

- **documentation-example**: copied field for field from an `example:` block (or a quoted body) on the cited
  official page. These back the FIXTURE_TESTED facts in `docs/execution/KALSHI_CONFORMANCE.md`.
- **schema-constructed**: written by us from the documented schema because the page has no example. The shape
  follows the schema; the values are invented and prove nothing about real responses.

| File | Label | Source |
|---|---|---|
| `create_order_v2_request.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/create-order-v2 |
| `create_order_v2_response.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/create-order-v2 |
| `cancel_order_v2_response.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/cancel-order-v2 |
| `amend_order_v2_request.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/amend-order-v2 |
| `amend_order_v2_response.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/amend-order-v2 |
| `decrease_order_v2_request.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/decrease-order-v2 |
| `decrease_order_v2_response.json` | documentation-example | https://docs.kalshi.com/api-reference/orders/decrease-order-v2 |
| `rate_limited_429.json` | documentation-example | https://docs.kalshi.com/getting_started/rate_limits |
| `get_order.json` | schema-constructed | https://docs.kalshi.com/api-reference/orders/get-order |
| `get_orders_page.json` | schema-constructed | https://docs.kalshi.com/api-reference/orders/get-orders |
| `get_fills_page.json` | schema-constructed | https://docs.kalshi.com/api-reference/portfolio/get-fills |
| `get_positions_page.json` | schema-constructed | https://docs.kalshi.com/api-reference/portfolio/get-positions |
| `get_settlements_page.json` | schema-constructed | https://docs.kalshi.com/api-reference/portfolio/get-settlements |
| `get_balance.json` | schema-constructed | https://docs.kalshi.com/api-reference/portfolio/get-balance |
| `historical_cutoff.json` | schema-constructed | https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps |
| `exchange_status.json` | schema-constructed | https://docs.kalshi.com/api-reference/exchange/get-exchange-status |
| `market_binary_active.json` | schema-constructed | https://docs.kalshi.com/api-reference/market/get-market (`price_ranges` from the `tapered_deci_cent` row of https://docs.kalshi.com/getting_started/fixed_point_migration) |

`tests/execution/test_wire.py` checks that every file here is listed in this table and that every
documentation-example file is used by a test.
