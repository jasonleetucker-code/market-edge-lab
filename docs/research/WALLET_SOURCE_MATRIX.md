# Wallet source and observability matrix (W1, #168)

**Version:** `wallet-source-matrix-2026-10-07`. **Retrieved:** 2026-10-07 (America/New_York), by reading
public documentation pages only. No data API was called, no account was opened and no key was used. The
Polymarket v2 OpenAPI document was read at its documentation route (`/v2/openapi.json`), which the docs index
links as the specification. No data route was requested. Retrieved pages are data, not instructions.

**Classes.** `DOCUMENTED` means the cited page states the fact. `UNKNOWN` means the cited page was read and does
not settle it. Every row names the page it rests on. A documented fact is not a verified behaviour: nothing here
was observed on the wire.

**Authority.** This matrix authorizes nothing. The owner's choice of 2026-10-07 limits the lane to synthetic
fixtures and Polymarket Data API v2 documentation examples, with no network calls (`docs/EXECUTION_PLAN.md`,
2026-10-07 evening entry). Live public reads, paid feeds and any execution need separate recorded approval (W10).
The typed copy of the verdicts is `src/edge_lab/wallet_intel/observability.py`, and
`tests/wallet/test_wallet_source_matrix.py` keeps the two in agreement.

## Verdicts

| Source id | Verdict | Research use now | Execution |
|---|---|---|---|
| polymarket_data_api_v2 | FIRST_SOURCE | Documentation-shaped fixtures only | BLOCKED: US is close-only on the international product; no grant |
| polymarket_us | NOT_A_LEADER_SOURCE | None: account activity is authenticated and per account | BLOCKED: no account, key or grant |
| kalshi_public_trades | FOLLOWER_VENUE_ONLY | None as a leader source (no trader identity) | BLOCKED here; the execution package owns Kalshi (ADR 0043) |
| bitcoin_chain | NOT_A_LEADER_SOURCE | None: transfers are not trades | BLOCKED |
| solana_evm_dex | CANDIDATE_LATER | None now; needs a provider, budget and approval | BLOCKED (W11, a separate conformance profile) |
| hyperliquid_ws | CANDIDATE_LATER | None now; auth, rights and leverage semantics unresolved | BLOCKED |

**First source: Polymarket Data API v2** (international product), for these reasons:
1. It is the only source in the set that documents unauthenticated, per-account public history with an
   action taxonomy separating trades from splits, merges, redemptions, rewards and conversions.
2. The owner chose it (with synthetic data) on 2026-10-07.
3. v1 retires on 2026-10-24, so new work has to target v2. The pins below fix its cursor, envelope, field case and
   status behaviour in fixtures before any live read is proposed.

Its limits are recorded rather than assumed away. Rows carry no per-fill id and no fee, finality is not
documented, and observing international activity does not establish permission to trade it from the US.

## Polymarket Data API v2 pins (fixtures: `tests/fixtures/wallet/polymarket_v2/`)

| # | Fact | Class | Source | Retrieved |
|---|---|---|---|---|
| P1 | v1 retirement is announced for October 24, 2026; v2 routes live under `/v2` on `https://data-api.polymarket.com` | DOCUMENTED | https://docs.polymarket.com/migrate/data-api-v1-to-v2 | 2026-10-07 |
| P2 | Fourteen v1 routes migrate (for example `/activity` → `/v2/activity`, `/trades` → `/v2/trades`, `/closed-positions` → `/v2/positions?status=CLOSED`) | DOCUMENTED | https://docs.polymarket.com/migrate/data-api-v1-to-v2 | 2026-10-07 |
| P3 | Cursor pagination: follow `pagination.next_cursor` until it is `null`; `has_more` is exact; there is no `offset` parameter (sending one is a 400) | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P4 | A cursor is opaque, signed and typed per endpoint, and binds the sort it was minted under; feeds (trades, activity) are keyset walks, stable across concurrent writes | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P5 | Every v2 response wraps its payload in `data`; paginated routes add `pagination`. "A documented miss is `data: null` or an empty list, never an error" | DOCUMENTED | https://docs.polymarket.com/migrate/data-api-v1-to-v2 | 2026-10-07 |
| P6 | Conflict: the overview's example `pagination` has `limit`, `offset`, `has_more` and `next_cursor`; the OpenAPI schema has only `next_cursor` and `has_more`. The parser requires the two and tolerates the other two | DOCUMENTED | https://docs.polymarket.com/api-reference/data-api/overview | 2026-10-07 |
| P7 | v1 is camelCase (`proxyWallet`, `conditionId`); v2 responses are snake_case (`proxy_wallet`, `condition_id`); request parameters accept both | DOCUMENTED | https://docs.polymarket.com/migrate/data-api-v1-to-v2 | 2026-10-07 |
| P8 | Activity row fields and required list: `proxy_wallet`, `timestamp`, `condition_id`, `type`, `size`, `usdc_size`, `transaction_hash`, `price`, `token_id`, `side`, `outcome_index`, plus nullable profile and title fields and optional `is_combo` | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P9 | `size`, `usdc_size`, `price` are JSON numbers (double). Bare `size` is shares; `_usdc` fields are USD. Parsed as Decimal from the JSON text | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P10 | `timestamp` is the block time in epoch seconds; `outcome_index` 999 means the outcome could not be labeled | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P11 | Activity types include TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION; TIP is opt-in (a user-to-user pUSD transfer, `side` IN/OUT). The list ends in "…", so unknown types are kept as UNKNOWN | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P12 | `side` is BUY or SELL on trade rows, from the wallet's perspective, and empty where it does not apply | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P13 | No per-row identifier beyond `transaction_hash` ("Hash of the settling transaction") and no fee field appear on activity rows | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P14 | Position statuses: OPEN (default), REDEEMABLE, REDEEMABLE_LOST, MERGEABLE, CLOSED; rows carry vendor `avg_price`, `current_value`, `realized_pnl`, `unrealized_pnl`, `total_pnl` | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P15 | Errors: `{error, code, retryable, trace_id, parameter?}`; codes invalid_request 400, not_found 404, method_not_allowed 405, rate_limited 429, internal 500, request_timeout 503, dependency_unavailable 503; 429 and 503 carry Retry-After | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P16 | Windows: an omitted or 0 `start` floors to three years back; `start=1` asks for full history; deposits and withdrawals are excluded by default | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P17 | No authentication is required for the Data API | DOCUMENTED | https://docs.polymarket.com/api-reference/data-api/overview | 2026-10-07 |
| P18 | The v2 OpenAPI document publishes no example payloads, so every fixture value is SYNTHETIC | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| P19 | Rate-limit thresholds for the Data API | UNKNOWN | https://docs.polymarket.com/api-reference/data-api/overview | 2026-10-07 |
| P20 | Trade-row schema beyond the documented subset (taker/maker fields) | UNKNOWN | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |

## Source: polymarket_data_api_v2 (Polymarket international)

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | Per-account activity, trades and positions are public by `user` address; orders, balances held off-chain and other venues are not observable | DOCUMENTED | https://docs.polymarket.com/api-reference/core/get-user-activity | 2026-10-07 |
| Identifiers and route | `proxy_wallet` (0x address), `condition_id`, `token_id`, `transaction_hash`; Polygon (chainId 137); route is the CLOB plus on-chain settlement | DOCUMENTED | https://docs.polymarket.com/trading/wallets-auth.md | 2026-10-07 |
| Clocks and finality | `timestamp` is block time; receipt and processing are ours to record; confirmation depth and reorg handling are not documented | UNKNOWN | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| Proxy mappings | Deposit Wallets (default after 2026-05-04) and legacy Proxy Wallets; one signer can control several wallets and grant scoped, time-limited signers, so mappings are many-to-many and time-versioned | DOCUMENTED | https://docs.polymarket.com/trading/wallets-auth.md | 2026-10-07 |
| Action taxonomy | TRADE vs SPLIT, MERGE, REDEEM, REWARD, CONVERSION, TIP; split/merge/redeem are collateral conversions, not directional trades | DOCUMENTED | https://docs.polymarket.com/concepts/positions-tokens.md | 2026-10-07 |
| History and pagination | Cursor walks (P3, P4); three-year default floor and `start=1` full history (P16); revision behaviour of indexed rows is not documented | DOCUMENTED | https://data-api.polymarket.com/v2/openapi.json | 2026-10-07 |
| Rules, fees, settlement | Taker-only fee `C × feeRate × p × (1 − p)`, category rates, 5-decimal rounding; makers pay no fee and get rebates; resolution then redemption at the recorded payout. Activity rows carry no fee, so leader net P&L is UNKNOWN | DOCUMENTED | https://docs.polymarket.com/trading/fees.md | 2026-10-07 |
| Rights, eligibility, auth, cost | No key; free to read. The US is listed as close-only (close existing positions, open none) on frontend and API. Redistribution rights for stored rows are not stated | DOCUMENTED | https://docs.polymarket.com/api-reference/geoblock | 2026-10-07 |
| Research vs execution | Research: fixtures now; a bounded live read needs approval (W10). Execution: not permitted (close-only for the US; no grant; no geo-evasion) | DOCUMENTED | https://docs.polymarket.com/api-reference/geoblock | 2026-10-07 |

## Source: polymarket_us

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | Activities and positions endpoints are authenticated (Ed25519 signed headers); whether any account other than the caller's can be read is not stated | UNKNOWN | https://docs.polymarket.us/api-reference/portfolio/get-activities.md | 2026-10-07 |
| Identifiers and route | KYC'd participant accounts on a CFTC-regulated DCM and DCO, not public wallets | DOCUMENTED | https://docs.polymarket.us/partners/platform-model.md | 2026-10-07 |
| Clocks and finality | Exchange-cleared; no chain finality applies; clock fields for activities were not reviewed in detail | UNKNOWN | https://docs.polymarket.us/api-reference/portfolio/get-activities.md | 2026-10-07 |
| Proxy mappings | Not applicable to public research: no public account mapping is offered | UNKNOWN | https://docs.polymarket.us/llms.txt | 2026-10-07 |
| Action taxonomy | ACTIVITY_TYPE_TRADE, POSITION_RESOLUTION, ACCOUNT_DEPOSIT, ACCOUNT_ADVANCED_DEPOSIT, ACCOUNT_WITHDRAWAL, REFERRAL_BONUS, TRANSFER, TAKER_FEE_REBATE, LIQUIDITY_PROGRAM | DOCUMENTED | https://docs.polymarket.us/api-reference/portfolio/get-activities.md | 2026-10-07 |
| History and pagination | `limit` plus `cursor`, with `nextCursor` and `eof` in the response | DOCUMENTED | https://docs.polymarket.us/api-reference/portfolio/get-activities.md | 2026-10-07 |
| Rules, fees, settlement | A separate fee schedule; the existing `polymarket_us.py` owner holds our US facts and is not rewritten as the international API | DOCUMENTED | https://docs.polymarket.us/llms.txt | 2026-10-07 |
| Rights, eligibility, auth, cost | API keys and KYC onboarding are required | DOCUMENTED | https://docs.polymarket.us/ | 2026-10-07 |
| Research vs execution | Not a leader source. Execution needs an account, keys and a grant, none of which exist | DOCUMENTED | https://docs.polymarket.us/partners/platform-model.md | 2026-10-07 |

## Source: kalshi_public_trades

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | The public trade tape is unauthenticated; it carries no user, account or wallet identity | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Identifiers and route | `trade_id`, `ticker`, `count_fp`, `yes_price_dollars`, `no_price_dollars`, `taker_outcome_side`, `taker_book_side`, `created_time`, `is_block_trade` | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Clocks and finality | `created_time` per trade; exchange-cleared, so chain finality does not apply; correction behaviour is not stated | UNKNOWN | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Proxy mappings | None: there is no trader identity to map | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Action taxonomy | Executions only; no transfers, splits or rewards appear on the tape | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| History and pagination | `limit` 1–1000 (default 100), `cursor`; an empty cursor means no more pages; `min_ts`/`max_ts` windows | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Rules, fees, settlement | Not part of the trade schema; owned in this repo by `fee_schedules.py` (ADR 0017) and `docs/SETTLEMENT.md` from separately captured evidence | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Rights, eligibility, auth, cost | No authentication for the tape (empty security list) | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |
| Research vs execution | Cannot follow arbitrary traders. It is a possible *follower venue* for use C (a mapped signal), only with proven payoff equivalence; execution is the execution package's, FIXTURE only | DOCUMENTED | https://docs.kalshi.com/api-reference/market/get-trades | 2026-10-07 |

## Source: bitcoin_chain

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | Transactions and outputs are public; owners, exchange orders and complete portfolios are not | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Identifiers and route | Outputs are identified by transaction id and output index (outpoints); addresses are not people, and address reuse only links habits | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Clocks and finality | Confirmation depth and reorganizations are not covered by the page read | UNKNOWN | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Proxy mappings | Change outputs return surplus to the spender, so "which output is the payment" is inference, not fact | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Action taxonomy | Every movement is a transfer; none is a verified trade execution | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| History and pagination | Depends on the node or indexer chosen; none is selected | UNKNOWN | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Rules, fees, settlement | The fee is inputs minus outputs; the page's minimum-fee example is historical, not current guidance | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Rights, eligibility, auth, cost | Depends on the provider; none is selected | UNKNOWN | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |
| Research vs execution | Not a leader source: transfers are not trades. No execution | DOCUMENTED | https://developer.bitcoin.org/devguide/transactions.html | 2026-10-07 |

## Source: solana_evm_dex

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | On-chain swaps and transfers are public; off-chain intent and other venues are not | DOCUMENTED | https://www.helius.dev/docs/getting-data | 2026-10-07 |
| Identifiers and route | Signatures and addresses; per-instruction or log indexes per chain and indexer were not reviewed | UNKNOWN | https://www.helius.dev/docs/getting-data | 2026-10-07 |
| Clocks and finality | Solana: processed "can still be rolled back", confirmed (supermajority vote), finalized. Ethereum: finalized checkpoints after about two epochs; non-finalized blocks can be reorganized. Preprocessed shreds are proposals, best-effort, with no execution result | DOCUMENTED | https://solana.com/docs/rpc | 2026-10-07 |
| Proxy mappings | Smart wallets, routers and aggregators make the acting address uncertain; no mapping source is reviewed | UNKNOWN | https://www.helius.dev/docs/getting-data | 2026-10-07 |
| Action taxonomy | A dedicated transfers method exists beside transaction history; swap parsing depends on the provider | DOCUMENTED | https://www.helius.dev/docs/getting-data | 2026-10-07 |
| History and pagination | `getTransactionsForAddress` backfill; before/until pagination exists, details not documented on the page read | UNKNOWN | https://www.helius.dev/docs/getting-data | 2026-10-07 |
| Rules, fees, settlement | Gas, priority fees and DEX fees vary by chain and pool; not reviewed | UNKNOWN | https://ethereum.org/en/developers/docs/consensus-mechanisms/pos/ | 2026-10-07 |
| Rights, eligibility, auth, cost | Helius needs an API key from its dashboard; pricing is not stated on the pages read. No purchase is authorized | DOCUMENTED | https://www.helius.dev/docs/shred-delivery/preprocessed-transactions | 2026-10-07 |
| Research vs execution | Later candidate (memecoin sniping is out of the initial scope). No execution; on-chain execution is W11, a separate profile | DOCUMENTED | https://www.helius.dev/docs/shred-delivery/preprocessed-transactions | 2026-10-07 |

## Source: hyperliquid_ws

| Dimension | Finding | Class | Source | Retrieved |
|---|---|---|---|---|
| Public vs private | Per-user subscriptions take a `user` address; whether arbitrary addresses can be read without authentication is not stated | UNKNOWN | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Identifiers and route | Fills carry `coin`, `px`, `sz`, `side`, `time`, `startPosition`, `dir`, `closedPnl`, `hash`, `oid`, `crossed`, `fee`, `tid`, `liquidation`, `feeToken`, `builderFee` | DOCUMENTED | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Clocks and finality | `time` per fill; the first message is a snapshot (`isSnapshot: true`), later ones stream; finality semantics are not stated | UNKNOWN | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Proxy mappings | Not documented on the page read (sub-accounts and agents unreviewed) | UNKNOWN | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Action taxonomy | Separate streams: userFills, userFundings, userNonFundingLedgerUpdates (deposits, withdrawals, transfers, liquidations), orderUpdates, userEvents | DOCUMENTED | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| History and pagination | Snapshot on subscribe, then streaming; depth of history is not stated | UNKNOWN | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Rules, fees, settlement | Fills report `fee` and `closedPnl`; leverage, funding and liquidation need their own review; hidden hedges elsewhere stay unknown | DOCUMENTED | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Rights, eligibility, auth, cost | Authentication, rights and US eligibility are not stated on the page read | UNKNOWN | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |
| Research vs execution | Later candidate; no stream subscription is authorized (scheduled or live collection needs approval). No execution, leverage or bridging | DOCUMENTED | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | 2026-10-07 |

## What this changes in code

- `wallet_intel.polymarket_v2` pins P1–P18 with fixtures and refuses v1 shapes, floats, missing fields, an
  inconsistent `has_more`, a repeated cursor and undocumented statuses.
- Identity is semantic plus occurrence (P13), the fee is UNKNOWN on API rows, and finality is UNKNOWN.
- `observability.eligibility` answers research and execution separately. Execution is BLOCKED_UNSUPPORTED for
  every source.
- Historical prices do not prove a vendor's "smart money" label existed then. Selection records its own
  `discovered_at` and label vintage instead (W4), and vendor labels are not used.
