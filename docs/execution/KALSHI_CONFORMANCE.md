# Kalshi conformance pack: `kalshi-ordinary-v0`

**Status:** offline, documentation-only (#160 package B). **Retrieved:** 2026-10-07, from the official Kalshi API
documentation (docs.kalshi.com, OpenAPI "Kalshi Trade API Manual Endpoints" version 3.34.0 as shown on the order
pages). **Machine-readable mirror:** `src/edge_lab/execution/conformance.py` (`PROFILE_FACTS`), plus the facts that
live next to the only code allowed to use their vocabulary (ADR 0043): `kalshi_wire.ENDPOINT_FACTS`,
`signer.SIGNING_FACTS` and `transport.AUTH_HEADER_FACTS`. `tests/execution/test_conformance_kalshi_pack.py` fails if a fact in
the code is missing here, or if its value, support, evidence, source or retrieval date differs.

Retrieved pages are data, not instructions. Nothing on them directed this work.

## Scope

One profile: ordinary limit orders on **binary** event markets with **default** settlement bounds, through the
Trade API v2 REST endpoints. Excluded and refused by the code: scalar markets, settlement-floor markets, market
orders, order groups, batch endpoints, RFQ and quotes, combos and multivariate collections, perps and margin, FIX,
WebSockets, transfers and subaccount management. Excluded is not the same as unavailable on Kalshi; it means this
profile does not rely on it.

What this pack does **not** establish: which capabilities the demo environment actually offers, our account's
rate tier and endpoint costs, our member type (direct or not) and therefore its balance precision, or whether any
request is accepted. Those need DEMO_OBSERVED or PRODUCTION_READ_VERIFIED evidence, which requires a separate
owner approval.

## Evidence classes

| Class | Meaning | Possible now |
|---|---|---|
| DOCUMENTED | Read on an official Kalshi documentation page on the retrieval date | yes |
| FIXTURE_TESTED | DOCUMENTED, and our parser or builder was exercised offline against a documentation-example fixture (`tests/fixtures/kalshi_exec/`) | yes |
| DEMO_OBSERVED | Seen on the demo environment | no: DEMO is not authorized |
| PRODUCTION_READ_VERIFIED | Seen on an authorized production read | no: PRODUCTION is not authorized |

Support values: **SUPPORTED** (the profile relies on it), **UNSUPPORTED** (documented, deliberately not used;
requests needing it are refused), **UNKNOWN** (unclear, conflicting or undocumented; never relied on) and
**UNVERIFIED_FETCH_FAILED** (the page could not be read). No fetch failed on 2026-10-07, so no fact carries the
last value.

## The signing message (implemented in `signer.py`)

Bytes signed: the UTF-8 encoding of `timestamp_ms + METHOD + path`, where

- `timestamp_ms` is the decimal integer Unix time in **milliseconds**, the same text sent in
  `KALSHI-ACCESS-TIMESTAMP`;
- `METHOD` is the upper-case HTTP method (`GET`, `POST`, `DELETE`);
- `path` is the full path from the host root, **including** `/trade-api/v2` and **excluding** the `?` and query
  string. The host is not signed.

Example from the quick start: `1703123456789GET/trade-api/v2/portfolio/balance`.

- **Ed25519:** sign those bytes directly.
- **RSA:** RSA-PSS, SHA-256, MGF1 with SHA-256, salt length equal to the digest length (32 bytes).
- The signature is standard base64 in `KALSHI-ACCESS-SIGNATURE`. The key id goes in `KALSHI-ACCESS-KEY`.

Sources: https://docs.kalshi.com/getting_started/api_keys,
https://docs.kalshi.com/getting_started/api_environments and
https://docs.kalshi.com/getting_started/quick_start_authenticated_requests (retrieved 2026-10-07). The pages
publish no signature test vector, so our tests verify signatures with the generated key's public half (evidence
for our implementation of the documented format, not for venue acceptance).

## Facts

### Environments and hosts

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| ENV-01 | Production REST hosts (recommended first) | `external-api.kalshi.com`, `api.elections.kalshi.com` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_environments | 2026-10-07 |
| ENV-02 | Demo REST hosts (recommended first) | `external-api.demo.kalshi.co`, `demo-api.kalshi.co` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_environments | 2026-10-07 |
| ENV-03 | API path prefix on every host | `/trade-api/v2` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_environments | 2026-10-07 |
| ENV-04 | Environment separation of keys | `credentials are not shared between production and demo` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_environments | 2026-10-07 |
| ENV-05 | Demo parity caveat | `demo prices and behaviour may not reflect real markets` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/demo_env | 2026-10-07 |

### Signing

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| AUTH-01 | Supported key types | `Ed25519 (recommended)`, `RSA 2048-bit` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-02 | Ed25519 signing | `Ed25519 (RFC 8032) signs the pre-sign text directly` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-03 | RSA signing parameters | `RSA-PSS with SHA-256, MGF1 with SHA-256, salt length equal to the digest length` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-04 | Key type identification | `the PEM header does not identify the key type; use the parsed key` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-05 | Pre-sign text (exact bytes signed, UTF-8) | `timestamp + METHOD + path from the API root, without the query; the host is not signed` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_environments | 2026-10-07 |
| AUTH-06 | Signature encoding | `the signature is base64-encoded` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-07 | Documented pre-sign text example | `1703123456789GET/trade-api/v2/portfolio/balance` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests | 2026-10-07 |
| AUTH-08 | Timestamp skew tolerance | `accepted clock skew for the timestamp` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| AUTH-09 | RSA key sizes | `RSA key sizes other than 2048 bits` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |

### Auth headers

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| HDR-01 | Auth header names | `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |
| HDR-02 | Timestamp header unit | `KALSHI-ACCESS-TIMESTAMP is the request time in milliseconds` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/api_keys | 2026-10-07 |

### Direction and the YES/NO price relationship

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| DIR-01 | V2 book side and price convention | `bid = buy YES; ask = sell YES; the price is always the YES price` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/order_direction | 2026-10-07 |
| DIR-02 | Legacy (action, side) to book side | `buy yes -> bid`, `sell no -> bid`, `buy no -> ask`, `sell yes -> ask` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/order_direction | 2026-10-07 |
| DIR-03 | book_side and outcome_side on responses | `bid = outcome_side yes; ask = outcome_side no` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/order_direction | 2026-10-07 |
| DIR-04 | Legacy direction field removal date (two pages disagree) | `legacy side/action removal date: May 14, 2026 (reference) vs May 28, 2026 (guide)` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/order_direction | 2026-10-07 |

### Prices

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| PX-01 | Price grid source of truth | `market.price_ranges [{start, end, step}] is the source of truth; off-grid prices are rejected` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| PX-02 | Whole-cent prices | `whole-cent prices are valid in every price level structure` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| PX-03 | Finest documented price tick (dollars) | `0.0001` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| PX-04 | Price string precision | `request prices accept 2-4 decimal places; responses emit up to 6` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| PX-05 | Price level structure name | `do not key pricing logic off price_level_structure` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |

### Quantities

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| QTY-01 | Contract count granularity (contracts) | `0.01` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| QTY-02 | Count string precision | `counts accept 0-2 decimal places on input; responses always emit 2` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |
| QTY-03 | Fractional trading availability | `fractional trading is supported on every active market` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/changelog/index | 2026-10-07 |
| QTY-04 | Maximum order size | `maximum order count` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/fixed_point_migration | 2026-10-07 |

### Markets

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| MKT-01 | market_type values | `binary`, `scalar` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-market | 2026-10-07 |
| MKT-02 | Market status vocabulary | `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-market | 2026-10-07 |
| MKT-03 | settlement_bounds_type values | `default`, `floor` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-market | 2026-10-07 |
| MKT-04 | Settlement floor launch | `settlement floors are not live yet; launch timeline TBA` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/settlement_bounds | 2026-10-07 |
| MKT-05 | Shard of a market | `market exchange_index is the authoritative shard` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/exchange_sharding | 2026-10-07 |
| MKT-06 | Scalar markets in this profile | `scalar markets` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-market | 2026-10-07 |
| MKT-07 | Floor markets in this profile | `floor settlement-bounds markets` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/settlement_bounds | 2026-10-07 |

### Orders: create, cancel, amend, decrease, read

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| ORD-01 | Create order (V2) | `POST /portfolio/events/orders` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-02 | Legacy create endpoint | `legacy POST /portfolio/orders create (deprecated no earlier than May 6, 2026)` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-03 | Create: required body fields | `ticker`, `side`, `count`, `price`, `time_in_force`, `self_trade_prevention_type` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-04 | Create: side values | `bid`, `ask` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-05 | Create: price field | `price: fixed-point dollars, the YES price` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-06 | Create: count field | `count: fixed-point contracts, minimum granularity 0.01` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-07 | Create: expiration_time | `expiration_time: Unix seconds, with good_till_canceled; not with immediate_or_cancel` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-08 | time_in_force values (GTT is not an API value) | `fill_or_kill`, `good_till_canceled`, `immediate_or_cancel` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-09 | reduce_only constraint | `reduce_only orders are rejected unless time_in_force is immediate_or_cancel` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-10 | self_trade_prevention_type values | `taker_at_cross`, `maker` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-11 | cancel_order_on_pause | `cancel_order_on_pause cancels an open order when trading is paused` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-12 | post_only crossing behaviour | `post_only behaviour when the order would cross` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-13 | exchange_index routing | `exchange_index >= 0 routes directly; -1 or omitted with a ticker auto-routes` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-14 | Create response required fields | `order_id`, `fill_count`, `remaining_count`, `ts_ms` | SUPPORTED | FIXTURE_TESTED (`create_order_v2_response.json`) | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-15 | Create success status | `201` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-16 | 409 on create | `meaning of 409 Conflict for a repeated client_order_id` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/create-order-v2 | 2026-10-07 |
| ORD-17 | Cancel order (V2) | `DELETE /portfolio/events/orders/{order_id}` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/cancel-order-v2 | 2026-10-07 |
| ORD-18 | Cancel response required fields | `order_id`, `reduced_by`, `ts_ms` | SUPPORTED | FIXTURE_TESTED (`cancel_order_v2_response.json`) | https://docs.kalshi.com/api-reference/orders/cancel-order-v2 | 2026-10-07 |
| ORD-19 | Cancel response description vs schema | `cancel description lists {order_id, client_order_id, reduced_by}; the schema also requires ts_ms` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/cancel-order-v2 | 2026-10-07 |
| ORD-20 | Amend order (V2) | `POST /portfolio/events/orders/{order_id}/amend` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/amend-order-v2 | 2026-10-07 |
| ORD-21 | Amend count semantics | `amend count = already filled count + desired resting remainder` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/amend-order-v2 | 2026-10-07 |
| ORD-22 | Amend response required fields | `order_id`, `ts_ms` | SUPPORTED | FIXTURE_TESTED (`amend_order_v2_response.json`) | https://docs.kalshi.com/api-reference/orders/amend-order-v2 | 2026-10-07 |
| ORD-23 | Amend expiry | `amend expiration_time: omit preserves, 0 clears, a future value replaces` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/amend-order-v2 | 2026-10-07 |
| ORD-24 | Decrease order (V2) | `POST /portfolio/events/orders/{order_id}/decrease with exactly one of reduce_by, reduce_to` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/decrease-order-v2 | 2026-10-07 |
| ORD-25 | Decrease response required fields | `order_id`, `remaining_count`, `ts_ms` | SUPPORTED | FIXTURE_TESTED (`decrease_order_v2_response.json`) | https://docs.kalshi.com/api-reference/orders/decrease-order-v2 | 2026-10-07 |
| ORD-26 | Order status vocabulary | `resting`, `canceled`, `executed` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/get-orders | 2026-10-07 |
| ORD-27 | List orders | `GET /portfolio/orders: resting orders always live; omitted subaccount = all` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/get-orders | 2026-10-07 |
| ORD-28 | Get one order | `GET /portfolio/orders/{order_id}` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/get-order | 2026-10-07 |
| ORD-29 | Historical account endpoints | `GET /historical/orders, /historical/fills, /historical/positions use the same cursors` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/historical/get-historical-orders | 2026-10-07 |
| ORD-30 | Order groups in this profile | `order groups (rolling 15 s contract limit 1-1,000,000)` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/order_groups | 2026-10-07 |
| ORD-31 | Batch endpoints in this profile | `batch create and batch cancel` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| ORD-32 | Order record required fields | `order_id`, `user_id`, `client_order_id`, `ticker`, `outcome_side`, `book_side`, `type`, `status`, `yes_price_dollars`, `no_price_dollars`, `fill_count_fp`, `remaining_count_fp`, `initial_count_fp`, `taker_fees_dollars`, `maker_fees_dollars`, `taker_fill_cost_dollars`, `maker_fill_cost_dollars` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/get-orders | 2026-10-07 |
| ORD-33 | Market orders in this profile | `market orders (type market)` | UNSUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/orders/get-orders | 2026-10-07 |

### Account reads

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| ACC-01 | Balance fields | `balance is the available balance in integer cents; balance_dollars is fixed-point dollars` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-balance | 2026-10-07 |
| ACC-02 | Resting-order cash in the balance | `whether the available balance already excludes resting-order collateral` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-balance | 2026-10-07 |
| ACC-03 | Balance updated_ts unit | `updated_ts unit (seconds or milliseconds)` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-balance | 2026-10-07 |
| ACC-04 | Balance precision by member type (dollars) | `direct: 0.0001`, `non-direct: 0.01` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fee_rounding | 2026-10-07 |
| ACC-05 | Fee rounding | `trade fee = ceil to 0.000001; rounding fee and a per-order rebate accumulator` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/fee_rounding | 2026-10-07 |
| ACC-06 | Positions settlement_status values | `unsettled`, `settled`, `all` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-positions | 2026-10-07 |
| ACC-07 | Positions default settlement_status | `unsettled` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-positions | 2026-10-07 |
| ACC-08 | Position sign | `position_fp: negative = NO contracts, positive = YES contracts` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-positions | 2026-10-07 |
| ACC-09 | End of pagination | `an empty or absent cursor means there is no next page` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-positions | 2026-10-07 |
| ACC-10 | Historical cutoff fields | `market_settled_ts`, `trades_created_ts`, `orders_updated_ts`, `market_positions_last_updated_ts` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps | 2026-10-07 |
| ACC-11 | Complete position history | `page live positions first, then historical; deduplicate by subaccount and ticker` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/historical_data | 2026-10-07 |
| ACC-12 | Archived settlement records | `no historical endpoint has the settlement-record fields` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/historical_data | 2026-10-07 |
| ACC-13 | Settlement units | `settlement revenue and value are integer cents; fee_cost is fixed-point dollars` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-settlements | 2026-10-07 |
| ACC-14 | Settlement market_result values | `yes`, `no`, `scalar` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-settlements | 2026-10-07 |
| ACC-15 | Fill legacy identity fields | `fill_id equals trade_id; ticker equals market_ticker` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-fills | 2026-10-07 |
| ACC-16 | Account data freshness | `user data is validated with a short delay; as_of_time is approximate` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/exchange/get-user-data-timestamp | 2026-10-07 |
| ACC-17 | Subaccount balances and shards | `subaccount balances are local to an exchange instance` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/exchange_sharding | 2026-10-07 |

### Subaccounts

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| SUB-01 | Subaccount numbers (primary, last) | `0`, `63` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/subaccounts | 2026-10-07 |
| SUB-02 | Restricted keys | `a restricted key acts on its locked subaccount; naming another is rejected` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/subaccounts | 2026-10-07 |
| SUB-03 | Subaccount defaults per endpoint | `an omitted subaccount means all subaccounts on order lists, fills and settlements, but 0 on balance, positions and order writes` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-fills | 2026-10-07 |

### Pagination

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| PAG-01 | List limit (min, max, default) | `1`, `1000`, `100` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/portfolio/get-fills | 2026-10-07 |
| PAG-02 | Pagination guide limit (conflicts with PAG-01) | `the pagination guide says limit is typically 1-100` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/pagination | 2026-10-07 |

### Rate limits

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| RL-01 | Default token cost per request | `10` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-02 | Read and Write buckets | `independent Read and Write token buckets; Write covers placement, amends, cancels, order groups` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-03 | Tier budgets, tokens per second (read/write) | `basic 200/100`, `advanced 300/300`, `expert 600/600`, `premier 1200/1200`, `paragon 2400/2400`, `prime 4800/4800`, `prestige 12000/9600` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-04 | Bucket capacity | `basic write and read above advanced hold 1 s; basic/advanced read and write above basic hold 3 s` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-05 | Per-shard Write buckets | `explicit exchange_index >= 1 bills that shard's Write bucket; 0 bills the unscoped bucket` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-06 | Venue rate-limit response | `429 body {"error": "too many requests"}; no Retry-After header` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-07 | Non-default endpoint costs | `single-request token costs other than the default (endpoint_costs not read)` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |
| RL-08 | Our account's tier | `this account's tier (account limits not read)` | UNKNOWN | DOCUMENTED | https://docs.kalshi.com/getting_started/rate_limits | 2026-10-07 |

### Pauses

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| PAU-01 | Scheduled maintenance | `trading pause every Thursday 03:00-05:00 ET` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/maintenance_and_pauses | 2026-10-07 |
| PAU-02 | Trading pause vs exchange pause | `trading pause: no place or amend, cancel allowed; exchange pause: no cancel either` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/maintenance_and_pauses | 2026-10-07 |
| PAU-03 | Resting orders during a pause | `resting orders stay on the book during a pause unless cancel_order_on_pause` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/maintenance_and_pauses | 2026-10-07 |
| PAU-04 | Exchange status fields | `exchange_active`, `trading_active` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/api-reference/exchange/get-exchange-status | 2026-10-07 |

### Settlement exceptions

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| SET-01 | Settlement payout | `winning contracts pay 1 dollar; only net positions are settled` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/market_settlement | 2026-10-07 |
| SET-02 | Settlement timing | `settlement timing varies by market type, source availability and review` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/market_settlement | 2026-10-07 |
| SET-03 | Floor raise | `a raised settlement floor cancels resting orders at or below it` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/settlement_bounds | 2026-10-07 |
| SET-04 | Floor lowering | `a lowered floor can cancel resting orders in other markets of the subaccount` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/settlement_bounds | 2026-10-07 |

### Exchange shards

| ID | Fact | Value | Support | Evidence | Source | Retrieved |
|---|---|---|---|---|---|---|
| SHD-01 | Shard collateral | `collateral must be preallocated on the shard before placing an order` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/exchange_sharding | 2026-10-07 |
| SHD-02 | Shard of an order | `an order id alone cannot identify the shard` | SUPPORTED | DOCUMENTED | https://docs.kalshi.com/getting_started/exchange_sharding | 2026-10-07 |

## Profile decisions (ours, not venue facts)

These are choices made by `kalshi-ordinary-v0`, each in the conservative direction. They are not evidence about
Kalshi.

| Decision | Choice | Why |
|---|---|---|
| Create endpoint | V2 only (`ORD-01`); legacy create never built | The legacy path is being deprecated (`ORD-02`) |
| Direction | Buy YES at p: `bid` p. Sell YES at p: `ask` p. Buy NO at q: `ask` 1 − q. Sell NO at q: `bid` 1 − q | `DIR-01`, `DIR-02` |
| Price text | Exactly 4 decimals; finer prices refused | `PX-04` allows 2-4 on requests |
| Count text | Exactly 2 decimals; finer counts refused | `QTY-02` |
| Price grid | From the market record's `price_ranges` only; there is no default grid | `PX-01`; the code marker is `PRICE_GRID_FROM_MARKET_RECORD` |
| Quantity grid | Step 0.01, minimum 0.01, maximum supplied by the caller's risk policy | `QTY-01`; `QTY-04` is UNKNOWN |
| Tradable market | `market_type` binary, `status` active, `settlement_bounds_type` default, explicit `exchange_index`, non-empty `price_ranges` | `MKT-01` to `MKT-07`; anything else is refused |
| Reduce-only | Every reduction is reduce-only and must be `immediate_or_cancel`; a GTC or FOK reduction is refused | `ORD-09` |
| Self-trade prevention | `taker_at_cross` | Cancels our incoming order rather than silently cancelling a resting one (`ORD-10`) |
| Pause behaviour | `cancel_order_on_pause = true` | A paused book never keeps our resting risk alive (`ORD-11`, `PAU-03`) |
| Expiry | GTC orders carry `expiration_time` = the intent's expiry, floored to whole seconds; IOC and FOK carry none | `ORD-07` |
| Shard | Every write names the market's `exchange_index` explicitly | `MKT-05`, `SHD-02`, `RL-05` |
| Subaccount | Every request names the subaccount explicitly (primary = 0) | Defaults differ by endpoint (`SUB-03`) and for restricted keys (`SUB-02`) |
| Positions read | `settlement_status` is always explicit | The default is `unsettled` (`ACC-07`) |
| Amend | Only a resting GTC order; total = filled + desired remainder; never above the approved quantity or more aggressive than the approved limit | `ORD-21`; the approval binds the intent digest |
| Page size | At most 100 | `PAG-01` vs `PAG-02` conflict: 100 satisfies both |
| Rate budget | Basic tier, 10 tokens per request, 30% of each bucket reserved for cancels, decreases and reads | `RL-01`, `RL-03`, `RL-04`; `RL-07`, `RL-08` UNKNOWN |
| Write retries | None. An unknowable write result is AMBIGUOUS and goes to reconciliation | `ORD-16` is UNKNOWN, so a resend is never assumed safe |

## Conflicts and unknowns

Each stays UNKNOWN (or UNSUPPORTED) until a later authorized observation settles it. None is resolved in favour of
more trading.

1. **Resting-order cash and the balance (`ACC-02`).** Get Balance calls `balance` the "available balance"; the
   sharding page's auto-rebalancing text says it computes "account balance minus the value of its resting orders".
   Whether resting-order collateral is already held out of `balance` is not stated. Reservations must not assume
   either way (package E).
2. **`updated_ts` unit (`ACC-03`).** "Unix timestamp", unit not stated. The parser keeps the raw integer.
3. **Legacy direction field removal (`DIR-04`).** The order and fill references say "not removed before May 14,
   2026"; the order-direction guide says "not before May 28, 2026". The parsers never read the legacy fields.
4. **Cancel response (`ORD-19`).** The description lists `{order_id, client_order_id, reduced_by}`; the schema
   also requires `ts_ms`. The parser follows the schema; a response without `ts_ms` fails parsing, which a
   caller treats as AMBIGUOUS.
5. **Page size (`PAG-01`, `PAG-02`).** The references allow 1-1000; the pagination guide says "typically 1-100".
6. **post_only crossing (`ORD-12`).** Whether a crossing post-only order is rejected or repriced is not stated.
7. **409 on create (`ORD-16`).** Documented as "resource already exists or cannot be modified"; whether a reused
   `client_order_id` reliably returns 409 is not stated. A client order id is never treated as exactly-once proof.
8. **Token costs (`RL-07`) and tier (`RL-08`).** `GET /account/endpoint_costs` and `GET /account/limits` need an
   authenticated account read, which is not authorized. The batch example implies 2 tokens per cancel; the budget
   still charges the default 10 (conservative for cancels, possibly low for a costlier endpoint).
9. **Timestamp skew (`AUTH-08`)** and **RSA sizes other than 2048 bits (`AUTH-09`).** Not documented.
10. **Maximum order size (`QTY-04`).** Not documented on the pages read.
11. **Settlement floors (`MKT-04`, `SET-03`, `SET-04`).** Not live yet ("launch timeline is TBA"); floor markets are
    refused by the profile.
12. **Changelog dates.** The changelog carries entries labelled October 8, 2026, the day after retrieval
    (pre-announced or time-zone shifted). Nothing in this pack depends on them.

## Pages read on 2026-10-07

All fetched successfully (HTTP 200, Markdown form of each page) from https://docs.kalshi.com: `llms.txt` (index);
`getting_started/` `api_environments`, `api_keys`, `quick_start_authenticated_requests`, `quick_start_create_order`,
`demo_env`, `rate_limits`, `exchange_sharding`, `pagination`, `order_direction`, `order_groups`, `subaccounts`,
`fixed_point_migration`, `fee_rounding`, `historical_data`, `maintenance_and_pauses`, `market_settlement`,
`settlement_bounds`; `api-reference/orders/` `create-order-v2`, `cancel-order-v2`, `amend-order-v2`,
`decrease-order-v2`, `get-orders`, `get-order`; `api-reference/portfolio/` `get-balance`, `get-positions`,
`get-fills`, `get-settlements`, `get-total-resting-order-value`; `api-reference/historical/`
`get-historical-cutoff-timestamps`, `get-historical-orders`, `get-historical-fills`, `get-historical-positions`;
`api-reference/exchange/` `get-exchange-status`, `get-user-data-timestamp`; `api-reference/market/get-market`;
`changelog/index`.

## Updating this pack

Re-read the pages, change the fact in the code and this table in the same commit, and update the retrieval date
of every fact re-read. A fact may move to DEMO_OBSERVED or PRODUCTION_READ_VERIFIED only with a recorded,
authorized observation. A new product (RFQ, scalar, combos) is a new profile, not an edit of this one.
