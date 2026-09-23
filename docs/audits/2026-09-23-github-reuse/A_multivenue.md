# Cluster A — Multi-venue / prediction-market API libraries (reuse audit, 2026-09-23)

Reviewer: read-only static review. No third-party code was installed, built, executed or tested.
Clones: `scratchpad/repos/<owner>__<repo>` at the pinned SHAs. ccxt was a depth-1 blobless fetch of the
pinned SHA plus a no-cone sparse checkout of the prediction files only (`ts/src/prediction/`,
`ts/src/base/PredictionExchange.ts`, `ts/src/base/types.ts`, `python/ccxt/prediction/`,
`ts/src/test/static/*/prediction/`, `pyproject.toml`, `LICENSE.txt`, `README.md`, `wiki/…`).
pmxt and dr-manhattan were read by a read-only helper agent; its key claims were spot-checked by
me (credential forwarding, committed key, Kalshi WS NO bug, walk-the-book helper, Polymarket US
book shape, dr-manhattan cents parsing). Line numbers are at the pinned SHAs.

Score keys (0–5): FIT, FOUND(ation), TESTS, MAINT, SEC, LIC, INTEG (5 = easy), UNIQ, OCT22. Total /45.

---

## 1. ccxt/ccxt

| Field | Value |
|---|---|
| URL | https://github.com/ccxt/ccxt |
| Reviewed SHA | `10ad2b51b9bf5d8c01c706755b0b0ec18a0cb693` (commit 2026-09-23, "chore: revise section in README.md") |
| Default branch / archived | master / no |
| Language / size | Multi-language: TS source, transpiled to JS/Python/PHP/C#/Go/Java/Rust. GitHub size ~8.5 GB |
| Activity | Pushed 2026-09-23; releases v4.5.81 (09-19), v4.5.82 (09-21), v4.5.83 (09-23). Very active |
| Maintainer | Official org (ccxt), 44k stars. Credible |
| CI | Yes: `.github/workflows/{js,python,php,cs,go,java,rust,…}.yml` (16 workflows) |
| License | MIT, `LICENSE.txt` ("Copyright © 2024 Igor Kroitor"); `pyproject.toml` `license = "MIT"`. No mismatch found |
| Python package | `pyproject.toml` v4.5.83, requires-python ≥3.10. `python/ccxt/` = 728 files, ~19.3 MB uncompressed source at this SHA (also vendors `static_dependencies/`) |
| Runtime deps | 22 pinned entries (≈21 on one platform): certifi, requests, cryptography, typing_extensions, aiohttp, yarl, aiohttp-fast-zlib, zlib-ng, uvloop / winloop (platform-gated), orjson, coincurve, aiohappyeyeballs, aiosignal, attrs, frozenlist, multidict, propcache, cffi, pycparser, charset_normalizer, idna, urllib3 (`pyproject.toml` dependencies block) |

### The prediction subsystem (new, separate namespace `ccxt.prediction`)
- Base class `ts/src/base/PredictionExchange.ts:17`. Every capability defaults to `false` (`:26-80`).
  Methods are addressed by an **outcome handle** (`"MARKET:LABEL"`), not by `symbol` (`:881-1250`).
- Types `ts/src/base/types.ts:145-400`: `PredictionEvent → PredictionMarket → PredictionOutcome`.
  "Prices are probabilities 0..1, amounts are shares, costs are collateral" (`types.ts:146-148`).
  `PredictionMarket` has `marketType` (binary/categorical/scalar), `executionModel` (clob/amm/parimutuel),
  `floorStrike/capStrike/strikeType`, `resolved`, `resolvedOutcome`, `settlementValue`, `tickSize`,
  `fees {trading, resolution}`, `resolutionSource` (`types.ts:180-212`).
  `PredictionOrderBook {asks: [Num,Num][], bids: [Num,Num][], timestamp, datetime, nonce, outcome, outcomeId, market}` (`types.ts:343-352`).
  `PredictionSettlement {result, won, amount, price, cost, payout, pnl}` (`types.ts:384-400`).
- Implementations: `ts/src/prediction/{kalshi,polymarket,limitless,myriad,binance,hyperliquid,opinion,predictfun,sxbet}.ts`
  and the transpiled `python/ccxt/prediction/*.py`. The Python prediction classes import the **async**
  base (`python/ccxt/prediction/kalshi.py:6` → `ccxt.async_support.base.prediction_exchange`), so they need aiohttp.
- There is **no** `ts/src/pro/…` file for any prediction venue. WebSocket methods (where they exist)
  are inline in the exchange class.

### Capability matrix (from `has` flags + method bodies)

| Capability | Kalshi | Polymarket | Limitless | Myriad |
|---|---|---|---|---|
| fetchMarkets + pagination | Yes. Cursor loop, default `status=open`, cap 1000 (`kalshi.ts:222-306`) | Yes. Gamma events, 100/page, capped 200 events cold (`polymarket.ts:314-322, 354`) | Yes, 25/page × 5 pages (`limitless.ts:218`, options) | Yes (`myriad.ts:225`) |
| fetchOrderBook | Yes (`kalshi.ts:1050`) | Yes, CLOB `/book` (`polymarket.ts:1225`) | Yes (`limitless.ts:1280`) | Yes, but AMM book is **synthetic** (see below) (`myriad.ts:2509`) |
| fetchTicker | Yes (`kalshi.ts:702`) | Yes (`polymarket.ts:983`) | Yes | Yes |
| watchOrderBook (WS) | **No** (no watch methods) | Yes (`polymarket.ts:3117`, `wss://ws-subscriptions-clob.polymarket.com/ws/market`) | **No** | Yes, Centrifugo (`myriad.ts:3304`) |
| createOrder | Yes (`kalshi.ts:1966`) | Yes, EIP-712 signed (`polymarket.ts:1960, 2245`) | Yes, EVM signing (`limitless.ts:2041`) | Yes, CLOB + AMM on-chain tx (`myriad.ts:828, 1054`) |
| fetchBalance | Yes (`kalshi.ts:1520`) | Yes (`polymarket.ts:1655`) | No flag | Yes (`myriad.ts:1957`) |
| fetchPositions | Yes (`kalshi.ts:1554`) | Yes (`polymarket.ts:1701`) | Yes (`limitless.ts:2704`) | Yes (`myriad.ts:535`) |
| Settlements / resolution | `fetchSettlements` from `/portfolio/settlements` (`kalshi.ts:1607-1707`); market `resolved` from `result` (`:531-534`) | No `fetchSettlements`. Winner **inferred** from `outcomePrice >= 0.99` (`polymarket.ts:777`) | `redeem` (on-chain) (`limitless.ts:2352`) | From market state |
| Market rules text | **Not unified.** `rules_primary` only in `info` (raw). Event `resolutionSource` only (`kalshi.ts:2592`) | Event `resolutionSource` (`polymarket.ts:2637`); `description` not in market unified fields | `description`, `resolutionSource` (`limitless.ts:867,882`) | `description`, `resolutionSource` (`myriad.ts:2057,2072`) |
| Fee metadata in market | Hard-coded `taker 0.07, maker 0` for every market (`kalshi.ts:181-188, 663-665`). `calculateFee` = 0.07·C·P·(1−P) **without cent round-up and without series multipliers** (`kalshi.ts:483-499`) | Hard-coded `taker 0.0` (`polymarket.ts:306-312, 834`). `fetchTradingFee` reads CLOB `/fee-rate` `base_fee` bps (`:1471-1494`) | Hard-coded 2% (`limitless.ts:174-181`) | Per-market `fees.buy/sell` in raw payload |

### Normalization
- **Kalshi** (`kalshi.ts:1050-1113`): reads `orderbook_fp.yes_dollars` / `no_dollars` (falls back to the whole response if `orderbook_fp` is absent: `safeValue(response, 'orderbook_fp', response)`, `:1068`).
  YES outcome: bids = yes levels, asks = `1 − no price`, size = the NO bid size. NO outcome mirrors.
  Sorted bids desc / asks asc (`sortedOrders`, `:1115-1127`). **`timestamp: undefined`** (the REST book has none).
  Values become JS floats via `safeNumber` (Precise string math only for the `1 − p`).
  Outcomes: YES = `ticker`, NO = `ticker + '-NO'` (synthetic id) (`:585-587`). Market `base: 'USD', quote: 'USD'`,
  `contract: false`, `contractSize: undefined`, price limits hard-coded `0.01..0.99` (`:676`) even though
  `price_ranges` step can be 0.001 (it reads step for precision at `:571-577` but not for limits).
- **Polymarket** (`polymarket.ts:618-860`): one ccxt market per `conditionId`, outcomes = `clobTokenIds`
  (1..N labels from gamma `outcomes`). `negRisk` carried per outcome. `collateral/base/quote = 'USDC'`.
  `precision.amount = tickSize` (wrong: amount precision is not the price tick) (`:790-793, 839-842`).
- **Limitless** (`limitless.ts:1280-1360`): book quoted in the YES token; NO = `1 − price` with sides swapped.
  Sizes are divided by 10^6 (`usdcDecimals`). `timestamp: undefined`.
- **Myriad** (`myriad.ts:2509-2700`): CLOB book in wei (÷1e18, `parseWeiOrderBook`, `:2658`).
  **AMM markets get an invented book**: one bid at price−0.001 and one ask at price+0.001, each with
  fake size `9999` (`myriad.ts:2617-2636`; Python `myriad.py:2391-2406`). This is an invented fill.

### Crypto-exchange leakage and correctness problems (for our rules)
- Spot vocabulary survives in `Market` rows: `base/quote = 'USD'/'USDC'`, `spot/margin/swap/future/option` flags, `contract: false`, `leverage {1,1}` (`kalshi.ts:626-676`, `polymarket.ts:817-850`).
- Floats everywhere in parsed output (`parseNumber`). Our rules need Decimal.
- Resolution heuristics: Polymarket winner by price ≥0.99 (`polymarket.ts:777`); Kalshi settlement picks the "held" leg by `yesCount >= noCount` (`kalshi.ts:1650`) and sets `price = won ? 1 : 0`, ignoring `settlement_value`/`fee_cost`; `fetchSettlements` ignores the response `cursor` (`:1607-1633`).
- Myriad synthetic AMM book (above). Violates NO INVENTED FILLS.
- Kalshi fee: flat 0.07 coefficient; no rounding, no per-series `fee_type/fee_multiplier`, no maker fees. Our `fee_schedules.py` is stricter.

### Hosts
- **Polymarket = Polymarket International**: `gamma-api.polymarket.com`, `clob.polymarket.com`, `data-api.polymarket.com`, `wss://ws-subscriptions-clob.polymarket.com` (`polymarket.ts:90-95`). No `polymarket.us` host anywhere. Chain 137 CTF Exchange V2 addresses (`:328-332`).
- **Kalshi**: `https://external-api.kalshi.com/trade-api/v2` (demo `external-api.demo.kalshi.co`), plus `https://api.elections.kalshi.com/v1` for free-text series search only (`kalshi.ts:52-64`). Same host as our `sources.py:73`. Current v2 API: yes.
- **Kalshi signing**: RSA-PSS SHA-256 over `timestamp + METHOD + /trade-api/v2/<path>` without the query string (`kalshi.ts:2612-2650`). Matches Kalshi's spec.

### Security-sensitive behavior (prediction files only)
- **Default builder attribution on every Polymarket order**: `options.builder = '0xea409de8…4a37'`, `builderFee: true`, `feeRate: 0` (`polymarket.ts:333-335`). The builder address is packed into each signed order (`:2096-2118`). The comment says zero fee, attribution only. A user who raises `feeRate` would pay that builder. Treat it as a hidden default.
- **Unlimited ERC-20 approvals**: Myriad `ensureErc20Allowance` sends `approve(spender, 2^256−1)` automatically in the AMM order path (`myriad.ts:795-810`, called at `:1095`). Limitless `approve()` defaults to maxUint256 (`limitless.ts:2282-2297`).
- On-chain signing with raw private keys: `signEvmTransaction` (`limitless.ts:2237`, `myriad.ts:736`); Kalshi RSA `privateKey` (`kalshi.ts:164-168`).
- No eval/child_process/os.system/pickle in the four prediction files (grep). No telemetry in these files.
- README also advertises an MCP server with opt-in trading and withdrawals (`README.md:1112`). Not reviewed.

### Tests
- Static request/response fixture tests only: `ts/src/test/static/{request,response}/prediction/<venue>.json`.
  Kalshi: request 7 methods, response 9 methods (incl. `fetchOrderBook` with a real-looking `orderbook_fp` fixture, fractional sizes like `"4040.45"`). Polymarket 13/7, Limitless 6/5, Myriad 23/many.
  I did not run them. No test found for fee rounding, settlement parsing or the Myriad synthetic book.

### Assessment
- README claims "supports … prediction markets: Polymarket, Kalshi, Limitless, Myriad" (`README.md:14-19`). Code confirms all four exist with broad method coverage. Code does **not** show: Kalshi/Limitless WebSocket, a rules-text field, correct per-market Kalshi/Polymarket fees, or official-evidence settlement.
- Worth studying: `types.ts:145-400` (Event/Market/Outcome/Book/Settlement shape), `kalshi.ts:1050-1127` (bid-only → bid/ask inversion), `kalshi.ts:222-306` (cursor paging with caps), `kalshi.ts:2612` (signing), `polymarket.ts:618-860` (gamma → outcomes), `limitless.ts:1280` (YES-token book mirrored for NO).
- Must NOT import: the package (22 deps, async runtime, floats, ~19 MB); the fee model; resolution heuristics; the Myriad synthetic book; the builder default.
- Overlap: `opportunity.py` (Event/Market/Payoff/ExecutableQuote), `kalshi_quotes.py`, `fees.py`, planned `venues.py` (capability `has` map ≈ our venue capability registry).
- Shared primitive it could unlock: a `has`-style capability map for `venues.py`, with default-false flags (matches our "execution authorization false by default").
- Reuse class: **REIMPLEMENT_IDEA**. Recommendation: **COPY_ADAPTER_IDEAS** (not USE / USE_OPTIONALLY).
  Reasons: stdlib-only policy (22 pinned deps, aiohttp); float prices; hard-coded wrong fees; heuristic resolution; invented AMM book; ccxt-owned builder attribution default; fast-moving API (3 releases in 5 days).
- Scores: FIT 2, FOUND 3, TESTS 3, MAINT 5, SEC 3, LIC 5, INTEG 1, UNIQ 3, OCT22 1 = **26/45**.
- Action: **REFERENCE_ONLY** — use as a cross-check of Kalshi/Polymarket-International wire semantics; never as a dependency.

---

## 2. pmxt-dev/pmxt

| Field | Value |
|---|---|
| URL | https://github.com/pmxt-dev/pmxt |
| Reviewed SHA | `4a367d812541154002eedda36b0916a3cf68e0f2` |
| Default branch / archived | main / no |
| Language / size | TypeScript core (`core/src`) + Python SDK (`sdks/python`) + TS SDK + CLI; ~9.4 MB |
| Activity | Last commit 2026-07-18; 47 commits since 2026-06-25; 1,687 total; 356 tags (latest v2.54.0f, 2026-07-18). Manifests say 2.17.1/2.18.0; versions rewritten at publish (`scripts/update-versions.js`) |
| Maintainer | Org "pmxt-dev", 2.2k stars; commercial hosted service `api.pmxt.dev` |
| CI | 12 workflows, mostly generation/drift checks. `npm test --workspaces` only in `test-publish.yml` on branch `multi-language-support`. No test job on main found |
| Tests | ~90 test files (core unit/pipeline/exchanges/normalizers, Python 18, TS 17). Mostly mocked. No test of Kalshi `orderbook_fp` normalizer or Polymarket book normalizer found; no unit test of `getExecutionPrice` algorithm (only doc-sample tests) |
| License | MIT `LICENSE` ("Copyright (c) 2026 pmxt.dev"); `core/LICENSE` MIT ("Copyright (c) 2026 qoery.com") — different holder, same SPDX |
| Deps | Python SDK 4 (urllib3, python-dateutil, pydantic, typing-extensions) + optional eth-account (`sdks/python/pyproject.toml:30-44`). Core Node 17 incl. `@polymarket/clob-client-v2`, `polymarket-us`, ethers@5, viem, @solana/web3.js, express, axios, dotenv (`core/package.json:47-65`). No postinstall/preinstall hooks |

### Venues (code)
`core/src/exchanges/`: baozi, gemini-titan, hunch, hyperliquid, kalshi, kalshi-demo, limitless, metaculus, myriad, opinion, polymarket, **polymarket_us**, probable, rain, smarkets, suibets (+ mock).
- Polymarket International: gamma/clob/data-api + ws-subscriptions-clob (`polymarket/utils.ts:27-30`, `websocket.ts:75,246`).
- **Polymarket US is a separate adapter**: `https://api.polymarket.us`, `https://gateway.polymarket.us` (`polymarket_us/config.ts:10-11`), wrapping the `polymarket-us` npm SDK. Not conflated with International. Good.
- Kalshi: `https://external-api.kalshi.com` + `/trade-api/v2`, WS `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (`kalshi/config.ts:20-24`); RSA-PSS SHA-256, salt = digest length (`kalshi/auth.ts:50-77`).

### Capability matrix
| Capability | Kalshi | Polymarket Intl | Polymarket US |
|---|---|---|---|
| fetchMarkets/Events + pagination | Cursor (`kalshi/fetcher.ts:333,444,616`) | Offset (`polymarket/fetcher.ts:403`) | Yes |
| fetchOrderBook(s) | Yes (`kalshi/index.ts:270,278`) | Yes (`polymarket/index.ts:170,180`) | Yes (`polymarket_us/index.ts:283`) |
| fetchTicker | **No** (not in `BaseExchange.ts`) | No | No |
| watchOrderBook | Yes, needs auth (`kalshi/index.ts:432`) | Yes (`:545`) | WS file present |
| create/cancel order, balance, positions | Yes | Yes | Yes |
| Settlement | No unified field. Settlement fields only "in hosted mode" (`types.ts:216-220, 261-265`) | same | same |
| Rules text | `description = rules_primary || rules_secondary` (`kalshi/normalizer.ts:121`) | `market.description || event.description` (`polymarket/utils.ts:118`) | — |
| Fees | none | `getFeeRateBps` in `buildOrder` (`polymarket/index.ts:224`) | — |

### Unified model
- `UnifiedEvent → UnifiedMarket → MarketOutcome{outcomeId, label, price /*0–1 float*/}` (`core/src/types.ts:5-113`). Multi-outcome = N outcomes per market. Kalshi YES = `ticker`, NO = `${ticker}-NO` (`kalshi/normalizer.ts:89-105`). Polymarket outcomeId = CLOB token id, falls back to `String(index)` if missing (`polymarket/utils.ts:88`).
- `OrderBook {bids: OrderLevel[], asks: OrderLevel[], timestamp, …}`, `OrderLevel {price, size, orderCount?}` objects (`types.ts:171-192`). Floats.
- **Walk-the-book**: `getExecutionPriceDetailed(book, side, amount)` (`core/src/utils/math.ts:18-72`): picks asks (buy) / bids (sell), drops size 0, sorts best-first, fills `min(remaining, size)` per level, returns `{price: VWAP, filledAmount, fullyFilled}` with 1e-8 epsilon. `getExecutionPrice` returns **0** when not fully fillable (`math.ts:9`) — a missing-as-zero hazard. No fees, no tick check.

### Kalshi / Polymarket book conversion
- Kalshi REST (`kalshi/normalizer.ts:254-284`): `orderbook_fp.yes_dollars/no_dollars`, asks = `round4(1 − no)`, NO outcome mirrored. `timestamp = Date.now()` (local receipt time presented as the book timestamp).
- **Bug**: Kalshi `watchOrderBook` strips `-NO` and returns the YES book unchanged for a NO outcome (`kalshi/index.ts:441-442`). REST inverts correctly; WS does not.
- Kalshi WS prefers `*_dollars_fp` fields, falls back to legacy cents ÷100 (`kalshi/websocket.ts:284,295`).
- Polymarket US (`polymarket_us/normalizer.ts:450-467`): book = `{bids, offers}` with levels `{px: Amount{value,currency}, qty}`, `transactTime`. Prices are **long-side (YES) prices** for every order; NO = `1 − long` (`polymarket_us/price.ts` header). `fetchOrderBook` returns the long book regardless of which outcome was asked (`index.ts:283-291`). `fromAmount` returns **0** for a missing amount (`price.ts`, `fromAmount`); `qty || '0'`; timestamp falls back to `Date.now()`. Bounds 0.01–0.99, default tick 0.001 (UNVERIFIED against live gateway).

### Process / network / security (important)
- **Python SDK spawns a detached Node sidecar**: `auto_start_server` defaults on (`sdks/python/pmxt/client.py:421-432`) → `ServerManager.ensure_server_running()` → `subprocess.run(['node', launcher])` (`server_manager.py:398-446`) → `spawn('node', [bundled.js], {detached: true, env: process.env})` + `unref()` (`core/bin/pmxt-ensure-server`). Full parent environment (all keys) is inherited. Port 3847+ on `127.0.0.1` (`core/src/server/app.ts:619`), `cors()` unrestricted (`app.ts:372`), token header `x-pmxt-access-token` (`:386`). Lock file `~/.pmxt/server.lock` holds the token, written with default permissions (`utils/lock-file.ts:16-19`). Logs `~/.pmxt/server.log`.
- **Kills other processes**: before spawning, force-kills every process whose command line matches `%pmxt%bundled.js%` (`wmic`/`taskkill /F` on Windows, `pgrep -f` + SIGTERM on Unix), with no owner check (`server_manager.py:268-296`).
- `execSync('tasklist /FI "PID eq ${pid}"')` with `pid` read from the lock-file JSON (`core/src/server/utils/lock-file.ts:46`): local shell-injection surface.
- **Hosted mode sends venue credentials to a third party**: if `PMXT_API_KEY` is set, `is_hosted` is true; read calls such as `fetch_markets` (`client.py:1391-1404`) still attach `body["credentials"]` from `_get_credentials_dict()` (`client.py:559-575`: `privateKey`, `apiKey`, `apiToken`) and POST to the hosted host (`_resolve_sidecar_host`, `client.py:537-538`) = `api.pmxt.dev`. Verified by me.
- **Committed API key**: `fifa.py:3` contains a `pmxt_…` hosted API key literal (redacted here). Validity UNVERIFIED.
- Telemetry: none found (posthog/segment/mixpanel/sentry/amplitude/datadog greps empty). Non-venue hosts: `api.pmxt.dev`, `trade.pmxt.dev`, Goldsky subgraph, public chain RPCs.
- `eval('import("@prob/clob")')` / `new Function('return import(...)')` fixed-string shims (`probable/websocket.ts:47`, `rain/fetcher.ts:16`).

### Assessment
- README "The ccxt for prediction markets" (`readme.md:4`): code supports the multi-venue claim. Settlement and fee claims are thin.
- Worth studying: `polymarket_us/{price.ts,normalizer.ts,config.ts}` (Polymarket US long-side convention, `bids/offers` + `px/qty` book shape — directly relevant to our planned Polymarket US read-only adapter), `core/src/utils/math.ts` (walk-the-book shape), `kalshi/normalizer.ts:254-284`.
- Must NOT import: the Python SDK (sidecar, process killing, credential forwarding), the Node core (17 deps), float math, `getExecutionPrice` returning 0.
- Overlap: `opportunity.py`, `kalshi_quotes.py`, planned Polymarket US adapter, planned `venues.py`.
- Reuse class: **REIMPLEMENT_IDEA**.
- Scores: FIT 2, FOUND 3, TESTS 2, MAINT 4, SEC 1, LIC 5, INTEG 1, UNIQ 4, OCT22 2 = **24/45**.
- Action: **NEXT** (reference only) — read `polymarket_us/` wire conventions when building the Polymarket US adapter; verify every field against captured live payloads before trusting it.

---

## 3. guzus/dr-manhattan

| Field | Value |
|---|---|
| URL | https://github.com/guzus/dr-manhattan |
| Reviewed SHA | `7c15fad9ab32749fc7bcc6679ab6a22d9200c328` |
| Default branch / archived | main / no |
| Language / size | Python (GitHub says Jupyter Notebook); ~11.6 MB |
| Activity | Last commit 2026-07-13; 11 commits since 2026-06-25; 56 total; 1 tag `0.0.1` (pyproject says 0.0.2) |
| Maintainer | Individual (User account), 203 stars |
| CI | `ci.yml` (mypy, pytest matrix, build), `contract-drift.yml` (daily live probe of Kalshi), Claude Code action workflows, pages, release |
| Tests | 25 files, mocked or replayed fixtures. Kalshi fixture test only checks structure (`tests/test_fixtures.py:28-39`) |
| License | **No LICENSE file** anywhere. `pyproject.toml` says `license = "MIT"`. GitHub API: none. → no code reuse (ideas only) |
| Deps | 15 runtime: requests, websockets, python-socketio, python-dotenv, eth-account, py-clob-client, opinion-clob-sdk, pandas, boto3, pyarrow, matplotlib, rich, predict-sdk, cryptography, scikit-learn |

### What it is
CCXT-style Python library + MCP server (stdio and SSE) + market-making bot framework.
Venues: `exchanges/kalshi.py`, `limitless.py`, `opinion.py`, `predictfun.py`, `polymarket/` package. Polymarket = International only (gamma, clob, data-api, relayer-v2, bridge; `polymarket_core.py:67-78`). No `polymarket.us`.

### Kalshi implementation is legacy and likely broken
- Host `https://api.elections.kalshi.com/trade-api/v2` (`kalshi.py:28-29`); RSA-PSS, DIGEST_LENGTH (`:49-51`).
- Market prices read legacy cents `yes_bid/yes_ask/last_price ÷ 100` (`kalshi.py:205-219`). When a side is missing it **assumes bid 0 / ask 100**, and with no fields it sets `yes_price = 0.5` (`:212-221`). The repo's own fixture `tests/fixtures/kalshi_markets.json` contains only `yes_bid_dollars` / `yes_bid_size_fp` (verified: 0 legacy `yes_bid` keys), so every Kalshi market likely gets 0.5.
- Order book reads legacy `response["orderbook"]["yes"/"no"]` in cents (`:420-441`) and **swallows every error into an empty book** (`:447-450`).
- `fetch_markets` single request, no cursor. Both Kalshi outcomes share one token id (`:253-257`).
- `create_order` sends integer cents (`:511, 537-540`).

### Security
- Private keys via `Account.from_key` (`limitless.py:200`, `predictfun.py:251,256`, `polymarket_ctf.py:40,136`).
- `PolymarketOperator` signs with a server-held `POLYMARKET_OPERATOR_KEY` for users (`polymarket_operator.py:1-11,70-99`).
- MCP exposes `create_order` / `cancel_all_orders` to an LLM with no confirmation step found (`mcp/tools/trading_tools.py:22,131`); strategy sessions run in background threads indefinitely (`mcp/tools/strategy_tools.py:19-45`).
- SSE server binds `0.0.0.0` by default (`mcp/server_sse.py:341`) and accepts Polymarket key/secret/passphrase in request headers (`:269-271`). README points to a third-party hosted endpoint on railway.app (`README.md:239`).
- Automatic order submission: `base/strategy.py:467` `place_bbo_orders`, `:540` `liquidate_positions`, `:629` run loop.
- Committed `.claude/settings.local.json` pre-allowing `Bash(python:*)` etc. Only relevant if the repo is opened in Claude Code; do not open it as a working directory.

### Assessment
- Nothing to learn for Kalshi except what to avoid (legacy cents, invented 0.5 mid, error → empty book).
- Reuse class: **LICENSE_REVIEW_REQUIRED** (no license text) → effectively REFERENCE_ONLY.
- Scores: FIT 1, FOUND 1, TESTS 2, MAINT 2, SEC 1, LIC 0, INTEG 1, UNIQ 1, OCT22 0 = **9/45**.
- Action: **REJECT** — no license, legacy Kalshi parsing that invents prices, LLM-driven order paths.

---

## 4. mrnicholasbcarter-code/prediction-market-sdk

| Field | Value |
|---|---|
| URL | https://github.com/mrnicholasbcarter-code/prediction-market-sdk |
| Reviewed SHA | `e02150819de6e5234c1719fb92449054212e2c96` |
| Default branch / archived | master / no |
| Language / size | Python, ~120 KB, 1,737 lines total |
| Activity | 38 commits, last cluster 2026-07-14 (pushed 2026-07-20). 0 stars. Individual |
| CI | `ci.yml` (pip install -e .[dev] && pytest), codeql, lint, dependabot, pypi-publish |
| Tests | 23 test functions (`test_kalshi.py` 14, `test_http_errors.py` 5, `test_llm_integration.py` 3, `test_ws.py` 1) + 1 live Polymarket integration test. Not run by me |
| License | MIT, `LICENSE` ("Copyright (c) 2024 Nicholas Carter"); pyproject `{text = "MIT"}` |
| Deps | 4 runtime: httpx, msgspec, cryptography, websockets |

### Findings
- **Stale Kalshi host**: `https://trading-api.kalshi.com/trade-api/v2` (live) and `demo-api.kalshi.co` (`src/prediction_market_sdk/kalshi.py:190-211`). Not the current `external-api.kalshi.com`.
- **Signing path lacks the `/trade-api/v2` prefix**: signs `timestamp + METHOD + "/portfolio/balance"` (`kalshi.py:215-243`). Kalshi's spec (and ccxt `kalshi.ts:2630-2636`) signs the full path incl. prefix. Salt length `PSS.MAX_LENGTH` (`:233`) differs from Kalshi's documented DIGEST_LENGTH. Auth likely fails (UNVERIFIED live).
- Money as float: `get_balance` returns `float(balance)/100` (`kalshi.py:351`).
- `submit_order` posts to v1 `POST /portfolio/orders` with cents (`kalshi.py:353-400`); docstring says "5000 = $50.00" for a limit price, which is wrong for a $1 binary. pykalshi's changelog says Kalshi now answers v1 order writes with 410 Gone. Orders are retried on 429/5xx (`_request_with_retry`, `:274-300`): duplicate-order risk.
- `orderbook.py`: integer-cents L2 ladder; maps Kalshi `"yes"` → bids and `"no"` → **asks without `1 − p` inversion** (`orderbook.py:170-178`). That is wrong for Kalshi's bid-only book. `seq` watermark is bumped with `ts`, not a sequence number (`:185-186`). `mid` is a float.
- `llm_integration.py`: points to a local "OmniRoute" proxy `127.0.0.1:20132` with env `OMNIROUTE_API_KEY` (`:12-31`). Unrelated scope.
- Polymarket: `clob.polymarket.com` / `clob.sandbox.polymarket.com` (`polymarket.py:150-166`). International only.
- No subprocess/eval/pickle found. `update.py` / `update_tests.py` are ad-hoc source-rewriting scripts.
- Reuse class: **REJECT** (correct license, wrong semantics).
- Scores: FIT 1, FOUND 1, TESTS 1, MAINT 2, SEC 3, LIC 5, INTEG 2, UNIQ 0, OCT22 0 = **15/45**.
- Action: **REJECT** — stale host, wrong signing path, uninverted Kalshi book, float money.

---

## 5. arshka/pykalshi

| Field | Value |
|---|---|
| URL | https://github.com/arshka/pykalshi (canonical ArshKA/pykalshi) |
| Reviewed SHA | `e42d9f3c491c5037cfe51c7f69ad35074d097255` |
| Default branch / archived | main / no |
| Language / size | Python, ~2.2 MB, 112 files |
| Activity | Last commit 2026-07-28; 20 commits since 2026-06-25; v2.0.0 in CHANGELOG (2026-07-26); no GitHub releases |
| Maintainer | Individual (Arsh Koneru), 125 stars |
| CI | `.github/workflows/test.yml`: unit tests on Python 3.9–3.13 (`uv run pytest tests/ --ignore=tests/integration`), integration job only with secrets on push |
| Tests | 586 `def test_` functions across `tests/` and `tests/integration/`. Not run by me |
| Docs | Good README + detailed CHANGELOG documenting Kalshi wire changes |
| License | MIT, `LICENSE` ("Copyright (c) 2024"); pyproject `license = "MIT"` |
| Deps | 5 runtime: httpx, pydantic, cryptography, python-dotenv, websockets (+ optional pandas; web extra fastapi/uvicorn) |

### What it shows about current Kalshi API semantics (test targets for us)
- Hosts: `https://external-api.kalshi.com/trade-api/v2`, demo `external-api.demo.kalshi.co` (`pykalshi/_base.py:30-31`); WS `external-api-ws.kalshi.com` (CHANGELOG 2.0.0).
- RSA-PSS, MGF1-SHA256, salt = DIGEST_LENGTH (`_base.py:93-101`).
- Order book: `OrderbookResponse.orderbook` accepts `orderbook` or `orderbook_fp` (`models.py:518-521`); levels are `(price_dollars, quantity_fp)` **strings** (`models.py:508-512`). WS snapshot fields `yes_dollars_fp` / `no_dollars_fp`, deltas `price_dollars` + `delta_fp` (CHANGELOG, `orderbook.py:15-30`).
- **`price_ranges` is the canonical tick grid**: list of `{start, end, step}` dollar strings; a price is valid iff `start ≤ p ≤ end` and `(p − start) % step == 0`, in Decimal (`models.py:85-116`, CHANGELOG `:95-110`). Seven new `price_level_structure` labels (`center_{whole|half|quint}_edge_{half|quint|deci}_cent`) from the week of 2026-07-27; label switches silently validate nothing (CHANGELOG `:104-110`).
- Market fields: `settlement_value_dollars`, `expiration_value`, `result`, `settlement_timer_seconds`, `fractional_trading_enabled`, `is_provisional`, `yes_bid_size_fp`/`yes_ask_size_fp`, `volume_fp`, `open_interest_fp` (`models.py:119-187`).
- Settlement record mixes units: `revenue` cents int, `yes/no_total_cost_dollars` strings, `fee_cost` dollar string (`models.py:820-846`). The CHANGELOG records that an earlier model silently zeroed cost (a real MISSING→ZERO bug they fixed).
- Orders: v1 `POST /portfolio/orders` returns 410 Gone; V2 writes at `/portfolio/events/orders` (CHANGELOG 2.0.0). `action`/`side` deprecated → `book_side`/`outcome_side`; the fill convention differs from the order convention (CHANGELOG, `models.py:364-440`).
- Batch `GET /markets/orderbooks`: max 100 tickers; tickers must be repeated `tickers=` params — a comma-joined list is silently misread (CHANGELOG `:120-128`).
- Balance: `balance_dollars` has up to 6 decimals (sub-cent) (CHANGELOG `:130-137`).
- Rate limits: token bucket with `refill_rate` / `bucket_capacity` from API limits; 429 + `Retry-After` handling (`rate_limiter.py`, `_sync/client.py:128-137`).
- Cursor pagination on list endpoints (`_sync/markets.py:148-157`).

### Walk-the-book
- `OrderbookManager.cost_to_buy(size)` / `cost_to_sell` (`orderbook.py:109-146`) and `OrderbookResponse.vwap_to_fill(side, size)` (`models.py:597-626`): Decimal; buy YES walks NO bids best-first at `1 − p`; returns **None** when depth is insufficient (fails closed). No fees, no tick check.
- Weaknesses: keys are raw price strings, so `"0.45"` and `"0.4500"` would be two levels (`orderbook.py:35-56`); `size="0"` divides by zero; `bid_depth`/`ask_depth` return `"0"` for an empty side; `mid` is exposed; no WS `seq` gap detection (no `seq` handling in `feed.py`/`afeed.py`).

### Security / behavior
- `from_env()` calls `load_dotenv()` (reads `.env` from CWD) (`_base.py:73-82`). Private key read from a PEM path (`:84-90`).
- Retries POST on timeout/connect errors (`_sync/client.py:84-120`): duplicate-order risk without client order ids.
- `examples/momentum_bot.py` places real orders when not in demo (`:15`). Order calls in `examples/place_order.py` are commented out.
- No subprocess/eval/pickle in the package. `web/` is an optional FastAPI+JSX terminal.

### Assessment
- Reuse class: **REIMPLEMENT_IDEA** (MIT, could copy small pieces with attribution, but pydantic/httpx deps are out).
- What to learn: PriceRange grid check, Decimal walk-the-book returning None, fixed-point string fields, the CHANGELOG as a record of Kalshi wire changes.
- Must NOT import: package (5 deps), dotenv auto-load, POST retry, `mid`.
- Scores: FIT 4, FOUND 3, TESTS 4, MAINT 4, SEC 3, LIC 5, INTEG 2, UNIQ 4, OCT22 3 = **32/45**.
- Action: **APPLY_NOW** (ideas only) — add `price_ranges` tick-grid checks and Decimal depth-walk to our Kalshi adapter tests.

---

## 6. Kalshi/kalshi-starter-code-python

| Field | Value |
|---|---|
| URL | https://github.com/Kalshi/kalshi-starter-code-python |
| Reviewed SHA | `08fd693c0ff0080179d97126536436f0498df036` |
| Default branch / archived | main / no |
| Size / activity | 5 files, 276 lines Python; last commit 2025-03-07; 16 commits |
| Maintainer | Official Kalshi org, 99 stars |
| CI / tests | None / none |
| License | **No LICENSE file** (verified `ls LICENSE*`; GitHub API: none). README has no license. → ideas only |
| Deps | `requirements.txt`: requests, python-dateutil, cryptography, urllib3, python-dotenv, websockets, datetime (7, pinned) |

- Hosts: prod `https://api.elections.kalshi.com`, demo `https://demo-api.kalshi.co` (`clients.py:41-46`). Older than the `external-api` hosts now used by ccxt/pykalshi/our repo.
- Signing: `timestamp + method + path` with the query string removed, full `/trade-api/v2/...` path (`clients.py:51-66`); RSA-PSS SHA-256, DIGEST_LENGTH (`:68-81`). This is the official reference for the signing recipe.
- Naive rate limit: sleep 100 ms if the last call was < 100 ms ago (`clients.py:100-108`).
- `main.py` loads `.env`, reads a key file and calls `get_balance()` on DEMO (`main.py:8-35`).
- No order book or settlement semantics beyond raw calls.
- Reuse class: **REFERENCE_ONLY** (no license). Scores: FIT 2, FOUND 1, TESTS 0, MAINT 1, SEC 4, LIC 0, INTEG 3, UNIQ 1, OCT22 0 = **12/45**.
- Action: **REFERENCE_ONLY** — only if we ever need signing (not authorized now).

---

## 7. Kalshi/tools-and-analysis

| Field | Value |
|---|---|
| URL | https://github.com/Kalshi/tools-and-analysis |
| Reviewed SHA | `6f82520f23ba89f0b4bf80d323f33c404990d798` |
| Default branch / archived | main / no |
| Size / activity | 8 files: 1 client (24 lines) + 3 notebooks; last commit 2023-05-08; 5 commits |
| Maintainer | Official Kalshi org, 22 stars |
| CI / tests | pre-commit config only / none |
| License | MIT, `LICENSE` ("Copyright (c) 2023 Kalshi") |
| Deps | `requirements.txt` ~75 pinned packages (jupyter stack, pandas, sklearn, yfinance, `kalshi-python==2.0.0`) |

- `client/kalshi_client.py:16-24`: **email/password login** from `credentials.yaml` — the retired auth model.
- Notebooks (read as JSON, not executed) use integer-cent fields and treat the **bid/ask midpoint as the probability** (`fed_feb_2023`, `market_surprise_calculator`, `oscars_2023`), e.g. `probability = (market.yes_ask + market.yes_bid) / 2`. Directly contrary to our NO MIDPOINT rule.
- Value: historical record of the legacy cents API only.
- Reuse class: **REFERENCE_ONLY**. Scores: FIT 1, FOUND 0, TESTS 0, MAINT 0, SEC 3, LIC 5, INTEG 2, UNIQ 0, OCT22 0 = **11/45**.
- Action: **REJECT** — obsolete API and midpoint-as-probability analysis.

---

## Cluster question answers

### Q1. CCXT prediction support
See section 1. Summary:
- Files: `ts/src/prediction/{kalshi,polymarket,limitless,myriad}.ts` + `ts/src/base/PredictionExchange.ts` + `types.ts:145-400`; transpiled `python/ccxt/prediction/*.py` (async-only).
- All four implement fetchMarkets (paged), fetchOrderBook, fetchTicker, createOrder, fetchPositions. WebSocket order books: Polymarket and Myriad only (inline, no `pro/` file); Kalshi and Limitless none. fetchSettlements: Kalshi only. Rules text: not unified (Kalshi `rules_primary` only in `info`). Fee metadata: hard-coded coefficients (Kalshi 0.07, Polymarket 0, Limitless 0.02); Kalshi `calculateFee` has no cent round-up or series multiplier.
- Normalization: prices are 0–1 floats; amounts are shares; YES/NO are **separate outcomes** under one market (Kalshi NO id = synthetic `ticker-NO`; Polymarket = CLOB token ids); books are bid/ask `[price, size]` float tuples, YES asks derived as `1 − NO bid`. Leaks: `base/quote = USD/USDC`, spot/margin/swap flags, `contract: false`, leverage limits, price-based winner inference, invented AMM book on Myriad.
- Polymarket here is **Polymarket International** (gamma-api/clob/data-api/ws-subscriptions-clob). No Polymarket US.
- Kalshi uses the current v2 API at `external-api.kalshi.com/trade-api/v2` with RSA-PSS (not `api.elections…/trade-api/v2`; `api.elections.kalshi.com/v1` is used only for search).
- Python package: ~19.3 MB source, 22 pinned runtime deps. Tests: static JSON request/response fixtures only.
- Recommendation: **COPY_ADAPTER_IDEAS**. Reasons: violates stdlib-only policy; floats; wrong fees; heuristic resolution; invented book; default builder attribution; API churn.

### Q2. pmxt
See section 2. Yes, the Python package spawns a detached Node sidecar on localhost:3847, inherits the whole environment, and force-kills matching processes. No telemetry found. Hosted mode forwards venue private keys to `api.pmxt.dev`. Venues: 16 adapters incl. separate Polymarket International and **Polymarket US** (`api.polymarket.us`, `gateway.polymarket.us`). Model: Event → Market → Outcome with 0–1 float prices; multi-outcome = N outcomes; Kalshi NO = `ticker-NO`; no unified settlement outside hosted mode. Walk-the-book helper exists (`core/src/utils/math.ts:18-72`) but returns 0 when unfillable.

### Q3. Kalshi semantics to test for, and gaps in our `kalshi_quotes.py`
What the libraries agree on (ccxt `kalshi.ts:1050-1113`, pmxt `kalshi/normalizer.ts:254-284`, pykalshi `models.py:508-626`):
- Book = `orderbook_fp.{yes_dollars,no_dollars}`, bid-only, `[price_dollars_str, quantity_fp_str]`, ascending (best bid last). YES ask = 1 − best NO bid, size = that NO bid's size. **Our adapter does this correctly** (`kalshi_quotes.py:130-154`), uses Decimal, sums duplicate price levels, and rejects malformed levels. It is stricter than all three libraries (they fall back or use floats).
- Sizes can be fractional (`"4040.45"` in ccxt's Kalshi fixture; `fractional_trading_enabled`). Our Decimal parsing handles this; `opportunity.py:581-588` already refuses fractional takes.
- The REST book has no source timestamp (ccxt sets `timestamp: undefined`; pmxt substitutes `Date.now()`). We correctly leave `source_timestamp_utc=None` and use `received_at_utc`. Do not copy pmxt's substitution.

Gaps / things to add as tests (none are proven bugs in our current EXP-001 path):
1. **No tick-grid check.** Kalshi `price_ranges [{start,end,step}]` is canonical; new `center_*` price structures started 2026-07-27 (pykalshi CHANGELOG `:95-110`, `models.py:85-116`). `kalshi_quotes._levels` accepts any finite price, including values outside (0, 1). Suggest: flag an anomaly when a level price is ≤0, ≥1, or off the market's `price_ranges` grid.
2. **Price-string normalization.** Treat `"0.45"` and `"0.4500"` as one level. We use Decimal comparisons, so `_best` is already safe; any future depth ladder must key on Decimal, not strings (pykalshi's string keys are a bug).
3. **Empty side → `displayed_size = Decimal(0)`** (`kalshi_quotes.py:147,152`). `best_ask` is None there, so it cannot be traded. Consider `None` for consistency with MISSING ≠ ZERO: "no ask observed" differs from "ask with zero size".
4. **No depth beyond best level.** Fine for `latency-confirmed-v1` (all-or-nothing at the entry ask). A ladder is needed before any multi-level fill policy (see Q4).
5. **Market fields not yet consumed** by the adapter: `price_ranges`, `fractional_trading_enabled`, `is_provisional`, `settlement_timer_seconds`, `can_close_early`. `settlement_value_dollars` / `expiration_value` are already used in `settlement_audit.py:94,204`.
6. **Status vocabulary.** ccxt uses `status=open|closed|settled|unopened` for list filters and `active` on market rows (`kalshi.ts:255-259, 529-531`). Our `OPEN/CLOSED_STATUSES` map everything else to UNKNOWN (fail-closed). Add fixture tests for `unopened`, `initialized`, `paused` → UNKNOWN.
7. **Fees**: libraries hard-code 0.07 without rounding (ccxt `kalshi.ts:483-499`). Our `fee_schedules.py` already models series `fee_type`/`fee_multiplier`, `/series/fee_changes` and rounding. Nothing to adopt. ccxt's endpoint list confirms `events/fee_changes` also exists (`kalshi.ts:73`) — possible extra evidence source.
8. **Settlement records mix units** (`revenue` cents int vs `*_dollars` strings, `fee_cost` dollars) — pykalshi `models.py:820-846`. Relevant only when a ledger reads portfolio settlements (not authorized now).
9. **Batch books**: `GET /markets/orderbooks` needs repeated `tickers=` params (comma-joined is silently misread), max 100 (pykalshi CHANGELOG `:120-128`). Relevant if our collector ever batches.
10. Deprecated fields to never rely on: legacy cents `yes_bid/yes_ask/last_price` and `orderbook.yes/no` (dr-manhattan still uses them and gets 0.5 defaults), `action`/`side`/`taker_side` (use `book_side`/`outcome_side`).

### Q4. Best venue-neutral depth-ladder design (synthesis)
Unified structures seen:
- ccxt: `{bids: [[price, size]…] desc, asks: [[price, size]…] asc, timestamp, datetime, nonce, outcome, outcomeId, market}` per **outcome** (`types.ts:343-352`).
- pmxt: `{bids: [{price, size, orderCount?}], asks: [...], timestamp}` (`core/src/types.ts:171-192`) + `getExecutionPriceDetailed` (`utils/math.ts:18-72`).
- pykalshi: native bid-only YES/NO dicts + `cost_to_buy/vwap_to_fill` returning None when unfillable (`orderbook.py:109-146`, `models.py:597-626`).
- prediction-market-sdk: integer-cent `{price: size}` dicts with a watermark (`orderbook.py`) — wrong for Kalshi.

Recommended design for Market Edge (stdlib, Decimal, fits `opportunity.py`):
1. `BookLevel(price: Decimal, size: Decimal)`; `DepthLadder(venue, market_id, side, asks: tuple[BookLevel,…] ascending, received_at_utc, source_timestamp_utc | None, evidence_id, price_scale, size_unit, anomaly | None)`. One ladder per **tradeable outcome side** (ccxt/pmxt outcome-addressing), built only from captured levels.
2. Per-venue adapters own scale conversion into canonical units: price in dollars per $1 payoff (Kalshi `*_dollars` as-is; Limitless size ÷10^6; Myriad ÷10^18; Polymarket US long-side `px.value`, NO = 1 − long with bids/offers swapped). Kalshi: YES asks = `1 − NO bids` with NO sizes (as now). Normalize equal prices by Decimal value and sum sizes.
3. Validation → `anomaly` (never repair): price ≤ 0 or ≥ 1, off tick grid (`price_ranges`), negative size, crossed book, unsorted input. Zero-size levels dropped.
4. `walk(qty) -> Fill | None`: consume asks best-first, `take = min(remaining, level.size)`; return `None` when depth < qty (pykalshi behavior; **never 0** like pmxt, never float epsilon). Return `levels_used`, `worst_price`, `total_cost` (exact Decimal), `vwap` for reporting only. Fees are computed per venue by `fees.py` from the **executed levels**, never from the VWAP. How Kalshi rounds a fee for one order that fills at several prices is UNVERIFIED here and must come from the captured fee evidence. Fee status propagates (FEE_UNVERIFIED).
5. Keep `ExecutableQuote` as a derived top-of-book view (`ladder.asks[0]`) so `evaluate()` and `latency-confirmed-v1` do not change. No `mid` field anywhere (ccxt ticker, pmxt, pykalshi and the SDK all expose mids).
6. Freshness: the ladder carries `received_at_utc`; a missing source timestamp stays None (do not substitute receipt time as pmxt does). Staleness is judged by `freshness.require_fresh`.
7. Never synthesize depth for AMMs or quote-only venues (ccxt Myriad's `9999` size). A venue without a real book gets no ladder → BOOK_MISSING.
