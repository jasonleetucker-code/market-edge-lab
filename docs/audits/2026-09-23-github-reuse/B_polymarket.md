# B — Polymarket SDK ecosystem: read-only reuse audit (2026-09-23)

Reviewer role: read-only researcher. Static reading only. No third-party code was installed or executed.
Clones: `scratchpad/repos/<owner>__<repo>` at the pinned SHAs (verified with `git rev-parse HEAD`).
Repo metadata came from `gh api repos/<o>/<r>` on 2026-09-23. npm metadata came from `npm view` (registry read only, no download).
Paths below are relative to each clone root unless stated otherwise.

Score key (0-5): FIT = PROJECT_FIT, SHARED = SHARED_FOUNDATION, MAT = MATURITY_TESTS, MAINT = MAINTENANCE,
SEC = SECURITY, LIC = LICENSE_EASE, INT = INTEGRATION_EFFORT (5 = easy), UNIQ = UNIQUE_VALUE, OCT22 = OCT22_IMPACT. Total /45.

---

## Summary table

| Repo | SHA-12 | Product | Status | Auth model | License (file) | Reuse class | Action | Total |
|---|---|---|---|---|---|---|---|---|
| Polymarket/polymarket-us-python | b44e4c8e7d34 | **Polymarket US** (gateway.polymarket.us public, api.polymarket.us auth) | Current, v1.0.1, breaking type fix 2026-09-22 | Public: none. Auth: Ed25519 key id + signature headers | MIT (`LICENSE`) | REIMPLEMENT_IDEA | **APPLY_NOW** (as spec) | 36 |
| Polymarket/py-sdk | 1f5ca055d31a | **International** (clob/gamma/data-api, Polygon, perps, RFQ) | Current, unified successor, v0.11.0 | EOA/proxy/safe wallet signing (EIP-712) + L2 HMAC creds | MIT (`LICENSE`) | REFERENCE_ONLY | LATER | 28 |
| Polymarket/real-time-data-client | c937d9c11cdd | **International** (ws-live-data.polymarket.com) | Low activity (last push 2026-03-05); py-sdk now carries RTDS | None, or CLOB L2 creds inside subscribe message | MIT (`LICENSE`) | REFERENCE_ONLY (anti-pattern) | REFERENCE_ONLY | 16 |
| Polymarket/py-clob-client-v2 | 215fc63a8fd6 | **International** (CLOB v2) | Maintained but README points to py-sdk | Private key (L1) + HMAC API creds (L2) | MIT (`LICENSE`) | REFERENCE_ONLY | REFERENCE_ONLY | 20 |
| Polymarket/py-clob-client | b076b04d6113 | **International** (CLOB v1) | **ARCHIVED**; README: "no longer functional" | Private key + HMAC creds | MIT (`LICENSE`) | REJECT | REJECT | 13 |
| Polymarket/polymarket-cli | 9b18b5faf549 | **International** (clob, gamma, data, bridge, CTF) | Active to 2026-05-26 | Private key stored in plaintext JSON config | **No LICENSE file** (Cargo.toml/README/Formula say MIT) | LICENSE_REVIEW_REQUIRED | REFERENCE_ONLY | 12 |
| Polymarket/agents | 081f2b5594c3 | **International** | **ARCHIVED** (last push 2024-11-05) | Polygon private key in env | MIT (`LICENSE.md`) | REJECT | REJECT | 9 |
| Polymarket/agent-skills | 91ee44ae113e | **International** (docs only) | 1 commit (2026-02-19); stale vs CLOB v2 | Docs describe private key + HMAC | **No LICENSE file** | LICENSE_REVIEW_REQUIRED | REFERENCE_ONLY | 11 |
| dev-polymarket/clob-client-v2 | 8d0df58a6e54 | Impersonates International CLOB v2 client | **Typosquat / impersonation** | Same as official (copied) | MIT file present, provenance untrusted | REJECT | **REJECT** | 2 |
| caiovicentino/polymarket-mcp-server | 21f65f319ff0 | **International** | Active (individual) | Polygon private key in env; LLM tool calls place orders | MIT (`LICENSE`) | REFERENCE_ONLY | REJECT (as component) | 19 |
| nahrek/polyledger | 62b889a9f4cc | **International** (on-chain OrderFilled + CLOB/Gamma) | 3 weeks old, 1 author | HyperSync bearer token | MIT (`LICENSE`) | REIMPLEMENT_IDEA | LATER | 21 |

No reviewed repo mixes US and International in code. Only `polymarket-us-python` talks to Polymarket US.

---

## Cluster question 1 — Product mapping (repo → product → status → auth)

Evidence:

- **polymarket-us-python → Polymarket US only.** `polymarket_us/client.py:38-39` hardcodes
  `GATEWAY_BASE_URL = "https://gateway.polymarket.us"` and `API_BASE_URL = "https://api.polymarket.us"`.
  `client.py:142` routes unauthenticated requests to the gateway and authenticated ones to the API host.
  Auth: `polymarket_us/auth.py:6-44` signs `f"{timestamp_ms}{method}{path}"` with an Ed25519 key (PyNaCl) and sends
  `X-PM-Access-Key`, `X-PM-Timestamp`, `X-PM-Signature`. No wallet, no chain.
- **py-sdk → International only.** `src/polymarket/environments.py:78-111`: chain_id 137, `clob.polymarket.com`,
  `gamma-api.polymarket.com`, `data-api.polymarket.com`, `ws-subscriptions-clob.polymarket.com`, relayer, RFQ,
  perps (`api.perpetuals.polymarket.com`, line 51), and Polygon contract addresses. `grep polymarket.us src` → no hits.
  It is the declared successor: `py-clob-client/README.md:1-7` and `py-clob-client-v2/README.md:1-2` point to it.
- **py-clob-client-v2 → International CLOB v2.** README top note recommends py-sdk for new projects. setup.py v1.1.0.
- **py-clob-client → International CLOB v1. Archived.** `README.md:1-7`: "no longer functional and should not be used".
- **real-time-data-client → International RTDS.** `src/client.ts:4` `wss://ws-live-data.polymarket.com`.
  py-sdk also carries `rtds_ws_url` (`environments.py:108`).
- **polymarket-cli → International.** `src/auth.rs:12` `https://clob.polymarket.com`; Cargo dep `polymarket_client_sdk_v2`
  with features gamma/data/bridge/clob/ctf (`Cargo.toml:17`).
- **agents → International** (`agents/polymarket/polymarket.py:42` clob.polymarket.com; Polygon RPC; USDC.e). Archived.
- **agent-skills → International** (`SKILL.md` API table: clob/gamma/data-api/Polygon contracts).
- **polymarket-mcp-server, polyledger → International** (URL greps: clob/gamma/data-api only; polyledger adds `polygon.hypersync.xyz`).

Current vs deprecated lineage (International): `py-clob-client` (archived) → `py-clob-client-v2` (maintained, superseded) → `py-sdk` (current, unified).
Polymarket US has one Python SDK: `polymarket-us-python`.

---

## Cluster question 2 — polymarket-us-python in depth

### Public (unauthenticated) endpoint coverage — exact paths (all GET on `https://gateway.polymarket.us`)

| Method | Path | Source | Response envelope |
|---|---|---|---|
| events.list | `/v1/events` | `polymarket_us/resources/events.py:12` | `{"events": [Event]}` |
| events.retrieve | `/v1/events/{id}` | `events.py:16` | `{"event": Event}` |
| events.retrieve_by_slug | `/v1/events/slug/{slug}` | `events.py:20` | `{"event": Event}` |
| markets.list | `/v1/markets` | `resources/markets.py:19` | `{"markets": [MarketDetail]}` |
| markets.retrieve | `/v1/market/id/{id}` (singular `market`) | `markets.py:23` | `{"market": MarketDetail}` |
| markets.retrieve_by_slug | `/v1/market/slug/{slug}` (singular) | `markets.py:27` | `{"market": MarketDetail}` |
| markets.book | `/v1/markets/{slug}/book` (plural) | `markets.py:31` | `{"marketData": MarketBook}` |
| markets.bbo | `/v1/markets/{slug}/bbo` | `markets.py:35` | `{"marketData": MarketBBO}` |
| markets.settlement | `/v1/markets/{slug}/settlement` | `markets.py:39` | `{"slug": str, "settlement": number}` (no envelope) |
| series.list | `/v1/series` | `resources/series.py:12` | `{"series": [Series]}` |
| series.retrieve | `/v1/series/id/{id}` | `series.py:16` | `{"series": Series}` |
| sports.list | `/v1/sports` | `resources/sports.py:16` | `{"sports": [Sport]}` |
| sports.teams | `/v1/sports/teams/provider` | `sports.py:20` | `{"teams": {id: SportsTeam}}` |
| search.query | `/v1/search` | `resources/search.py:12` | `{"events": [Event]}` |

**Not covered by the SDK (must be treated as UNSUPPORTED or researched from docs.polymarket.us):**
price history / candles, public trade tape (REST), fee schedule, structured settlement rules, public (unauthenticated) WebSocket.

### Response models (field names, types, units)

From `polymarket_us/types/*.py` (TypedDicts; **no runtime validation**, responses are raw `response.json()` dicts — `client.py:189-192`):

- `Amount` (`types/common.py:6-10`): `{"value": str, "currency": "USD"}`. Price is a **decimal string in US dollars** (fixtures: `"0.55"`, `"0.56"`; `tests/test_markets.py:114-118`). Parse with `Decimal(value)`, never float. Reject `currency != "USD"`.
- `OrderBookLevel` (`types/markets.py:40-44`): `{"px": Amount, "qty": str}`. `qty` is a **string** count of contracts/shares (fixture `"100"`, `"80"`). Order `quantity` is an `int` (`types/orders.py:78`), so contracts are whole units — UNVERIFIED for book levels (treat as Decimal, flag non-integers).
- `MarketBook` (`types/markets.py:69-77`): `marketSlug`, `bids: [Level]`, `offers: [Level]` (note: **`offers`, not `asks`**), `state: MarketState`, `stats: MarketStats | None`, `transactTime: str | None`.
- `MarketStats` (`markets.py:47-54`): `lastTradePx: Amount`, `sharesTraded: str`, `openInterest: str`, `highPx: Amount`, `lowPx: Amount`.
- `MarketBBO` (`markets.py:80-90`): `marketSlug`, `bestBid: Amount | None`, `bestAsk: Amount | None`, `bidDepth: int`, `askDepth: int`, `lastTradePx: Amount | None`, `sharesTraded: str`, `openInterest: str`. Empty-market fixture has `sharesTraded: ""` and `openInterest: ""` (`tests/test_markets.py:134-136`) — **empty string means unknown, map to None, never 0**. Meaning of `bidDepth`/`askDepth` (levels vs contracts) is UNVERIFIED (fixture has 1 level and depth 1).
- `MarketState` (`markets.py:57-66`): `MARKET_STATE_{CLOSED,OPEN,PREOPEN,SUSPENDED,HALTED,EXPIRED,TERMINATED,MATCH_AND_CLOSE_AUCTION}`. Only `OPEN` should be quotable.
- `MarketSettlement` (`markets.py:93-97`): `{"slug": str, "settlement": float}`. Test values 0, 0.5, 1 (`tests/test_markets.py:196`). Units: fraction of $1 payout per contract (inferred from 0.5 = void/split case; UNVERIFIED). There is no settled-at timestamp and no source field.
- `MarketDetail` (`markets.py:24-37`): `id: int`, `slug`, `title`, `outcome: str`, `description`, `active`, `closed`, `liquidity: float`, `volume: float`, `eventSlug`, `team`.
- `Event` (`types/events.py:37-54`): `id`, `slug`, `title`, `description`, `startTime`, `endTime` (strings), `active`, `closed`, `archived`, `featured`, `liquidity`, `volume` (floats), `markets: [{id, slug, title, outcome, active, closed, liquidity, volume}]`, `tags: [{id, slug, label}]`, `series: {id, slug, title}`.
- `Series` (`types/series.py:8-18`): `id`, `slug`, `title`, `description`, `active`, `closed`, `archived`, `recurrence`.
- Timestamps: `transactTime` is an ISO-8601 string in fixtures (`"2026-09-21T12:00:00Z"`, `test_markets.py:118`). Precision and timezone guarantees are UNVERIFIED.

### Order-book representation (YES/NO, long/short)

- One book per **market slug**. Each market carries a single `outcome` label (`MarketDetail.outcome`). The book has `bids` and `offers` for that market's **long** side.
- There is no separate short/NO book in the SDK. Short exposure is expressed through order intents `ORDER_INTENT_BUY_LONG | SELL_LONG | BUY_SHORT | SELL_SHORT` (`types/orders.py:9-14`), plus `ORDER_SIDE_BUY | SELL`.
- Implication: an executable **short (NO) ask = 1 − best long bid** and **short bid = 1 − best long offer** is the likely mapping (same shape as our `kalshi_quotes.py`), but this is **UNVERIFIED** from code. It must be confirmed from captured Polymarket US documentation before `evaluate()` may use a NO quote. Until then, emit only the long side and mark NO as `UNSUPPORTED`.
- Level ordering (best first?) is not stated in code. Compute best bid = max(px), best offer = min(px); do not trust index 0. A crossed or locked book must become `anomaly`.
- Multi-outcome events (e.g., two teams) appear as several markets under one event, each with its own slug/outcome/book. Mutual exclusivity must come from rules, not titles.

### Pagination

- `PaginationParams` = `limit`, `offset` (`types/common.py:13-17`) on events/markets/series. README example pages with offset (`README.md:19-20`).
- Search uses `page` + `limit` (`types/search.py:8-15`).
- No `total`, `nextCursor` or `eof` on public list responses. Completeness must be inferred (stop when a page returns fewer than `limit`), and recorded as `completeness: INFERRED`, not proven.
- Authenticated portfolio endpoints use `cursor`/`nextCursor`/`eof` (`types/portfolio.py:246-259`) — not relevant for us.
- Query encoding (`client.py:206-221`): lists become repeated keys; booleans become `"true"`/`"false"`; `None` is dropped.

### Rate-limit handling

- `polymarket_us/_retry.py:1-9` (module docstring): the Polymarket US API **does not return `Retry-After` or `X-RateLimit-*` headers**. Backoff is client-side.
- Retries: statuses `{408, 409, 429, 500, 502, 503, 504}` (`_retry.py:17`), methods `{GET, HEAD, OPTIONS, DELETE}` only (`_retry.py:20`), default 2 retries (`_retry.py:14`), exponential 0.5 s → 8 s cap with equal jitter (`_retry.py:36-47`), `Retry-After` clamped to 8 s if present.
- POST (orders) is never retried because the API has no idempotency key (`_retry.py:6-8`). Good rule.
- Published numeric rate limits: none in the code. UNVERIFIED. Our pacing must be conservative and configurable.
- Every request sends `User-Agent: polymarket-us-python/<ver>` and a UUID `poly-correlation-id` (`client.py:41-42, 153-158`); errors read back `poly-correlation-id` or `x-request-id` (`client.py:237-241`). Worth copying into our provenance record.

### WebSocket

- `wss://api.polymarket.us/v1/ws/markets` (`websocket/markets.py:16`, `client.py:285`) and a private socket. **Both require API-key auth** — `client.py:278-284` raises `AuthenticationError` without key id/secret; `websocket/base.py:51` signs the handshake.
- So there is **no public WebSocket** via this SDK. For us: out of scope (credentials not authorized).
- Subscription model: `{"subscribe": {"requestId", "subscriptionType", "marketSlugs"}}`, types `SUBSCRIPTION_TYPE_MARKET_DATA | MARKET_DATA_LITE | TRADE` (`websocket/types.py:14-18, 74-80`). No reconnection logic (`base.py:59-71` just emits `close`).

### Runtime dependencies

`pyproject.toml:35-39`: **3 direct** — `httpx>=0.27.0`, `pynacl>=1.5.0`, `websockets>=13.0`. Transitive (well-known, not installed here): httpx → httpcore, h11, anyio, sniffio, idna, certifi; pynacl → cffi → pycparser. Roughly 10 packages, including a compiled one (cffi/libsodium). No pydantic, no cryptography.

### Does public data need a key?

No. `client.py:145-150` only demands credentials when `authenticated=True`; all market-data resources call `get()` with the default `authenticated=False`. Tests instantiate `PolymarketUS()` without keys for book/BBO/settlement (`tests/test_markets.py:160-205`).

### Recommendation: **REIMPLEMENT_PATTERN** (do not depend on the library)

Reasons:
1. Our runtime is stdlib-only. The SDK adds 3 direct and ~10 transitive packages, one compiled.
2. The SDK adds almost nothing for read-only use. The public resources are one-line GET wrappers returning **unvalidated raw dicts** (TypedDict only). We would still need to write all parsing, Decimal conversion, None handling, freshness and provenance.
3. The SDK's types were **wrong until the day before this audit**: commit `38e16ad` (2026-09-22, "fix: correct market response types (BREAKING CHANGE)") changed the book/BBO envelope to `marketData`, made `bestBid`/`bestAsk`/`lastTradePx`/`stats`/`transactTime` nullable, and replaced settlement `{marketSlug, settlementPrice: Amount, settledAt}` with `{slug, settlement: float}`. Its tests are mock-based (`httpx_mock`), so they prove wire shape only to the extent the fixtures match reality. **Our adapter must be tested against captured live responses, not the SDK's types.**
4. Importing it puts `orders.create`, `close_position`, `cancel_all` and an auth signer into our dependency graph. Our venue registry keeps execution disabled; a trading-capable dependency is an unneeded risk.
5. Our `http.py` already has bounded retries, pacing and provenance. The US-specific logic is ~150-250 lines.

Copy as ideas (MIT allows small snippets with attribution if wanted): retry set and "never retry non-idempotent" rule (`_retry.py`), correlation-id header, query encoding (`client.py:206-221`).

### Exact spec for Market Edge's read-only Polymarket US adapter

Base URL `https://gateway.polymarket.us`. GET only. No auth headers. Record request URL, params, status, `poly-correlation-id`/`x-request-id`, received_at_utc, and body sha256 in provenance.

Implement and fixture-test:

1. `GET /v1/events?limit=&offset=&active=&closed=&seriesId=…&tagSlug=…` → catalog. Paginate by offset until a short page; record `completeness: INFERRED`.
2. `GET /v1/events/slug/{slug}` → event detail with nested `markets[]` (id, slug, outcome, active, closed).
3. `GET /v1/markets?eventSlug=…&limit=&offset=` and `GET /v1/market/slug/{slug}` → market identity: `market_id = "polymarket_us:<slug>"` (slug is the key used by book/BBO/settlement; keep numeric `id` as secondary).
4. `GET /v1/markets/{slug}/book` → depth. Parse `marketData.bids[]`/`offers[]` as `(Decimal(px.value), Decimal(qty))`; assert `px.currency == "USD"` and `0 < px < 1`; best = max bid / min offer; crossed → anomaly; `state != MARKET_STATE_OPEN` → not quotable; `transactTime` → `source_timestamp_utc` (None if null; then freshness = UNKNOWN → fail closed).
5. `GET /v1/markets/{slug}/bbo` → top of book. `bestBid`/`bestAsk` may be null → None. `sharesTraded`/`openInterest` `""` → None. **Do not use `lastTradePx` as an executable price.** BBO carries **no timestamp field**; prefer `/book` (has `transactTime`) for `ExecutableQuote`, or treat BBO freshness as received_at only and mark source timestamp UNKNOWN.
6. `GET /v1/markets/{slug}/settlement` → `{slug, settlement}`. Map 1 → YES, 0 → NO, other (e.g. 0.5) → non-binary/void outcome. Missing/404 → unresolved, not NO. No timestamp → use received_at and mark settlement time UNKNOWN.
7. `GET /v1/series`, `/v1/series/id/{id}` → recurrence grouping (for daily/weather-style series if any exist).
8. Optional: `GET /v1/search?query=&status=active&page=&limit=` for discovery.

Field-semantics tests to write: Decimal from string prices; `offers` (not `asks`); nullable stats/timestamps; empty-string numerics → None; state enum gating; crossed book → anomaly; unknown currency → reject; settlement 0/0.5/1; pagination stop rule; unknown extra fields tolerated but logged; 429/5xx retried on GET only.

Explicit UNSUPPORTED fields in the adapter: fee schedule (→ `FEE_UNVERIFIED`), structured settlement rules (→ `RULES_UNRESOLVED`; `description` is prose), NO/short-side quotes (until the complement rule is documented), price history, public trade tape, WebSocket.

---

## Cluster question 3 — Fee metadata

- **Polymarket US (polymarket-us-python): no public fee metadata.** Fee fields exist only on authenticated order/execution objects:
  `Order.commissionNotionalTotalCollected: Amount`, `Order.commissionsBasisPoints: str`, `Order.makerCommissionsBasisPoints: str` (`polymarket_us/types/orders.py:90-92`);
  `Execution.commissionNotionalCollected: Amount` (`orders.py:108`). `orders.preview` (`resources/orders.py:68-74`, authenticated) may return a commission preview — UNVERIFIED.
  → For us: Polymarket US fee status stays **UNVERIFIED** unless a fee schedule document is captured as evidence.
- **International (py-sdk):**
  - Gamma market model `MarketTrading.fees_enabled` (`feesEnabled`), `fee_type` (`feeType`), `fee_schedule: FeeSchedule{exponent, rate, taker_only (takerOnly), rebate_rate (rebateRate)}` (`src/polymarket/models/gamma/market.py:222-265`).
  - CLOB `/clob-markets/{condition_id}` field `fd: {r, e}` → `PlatformFeeInfo(rate, exponent)` (`src/polymarket/_internal/actions/orders/market_data.py:33-36, 92-113, 207-222`).
  - Fee formula used for market-buy sizing: `effective_rate = rate * (price * (1 - price)) ** exponent`; `platform_fee = (amount / price) * effective_rate` (`_internal/actions/orders/market.py:409-421`). Same family as Kalshi's quadratic fee.
  - Builder fees: `/fees/builder-fees/{code}` → `builder_maker_fee_rate_bps`, `builder_taker_fee_rate_bps` (`models/clob/builder.py:20-30`).
  - Per-trade `fee_rate_bps` on stream/trade models (`models/clob/market_events.py:124`, `user_events.py:104,147`, `account.py:113,153`); market-event `taker_base_fee`, `fees_enabled`, `fee_schedule` (`market_events.py:240-242`).
  - Perps fee schedule: `fetch_perps_fees()` (`clients/async_public.py:1587`).
  - **MISSING → ZERO violation:** `_parse_platform_fee_info` returns `rate=0, exponent=0` when `fd` is absent (`market_data.py:211-213`). We must not copy that.
- **py-clob-client-v2 / py-clob-client:** `GET /fee-rate?token_id=` → `base_fee` (`py_clob_client_v2/endpoints.py:52`, `client.py:385-393`; v1 `client.py:450-455`). Both do `result.get("base_fee") or 0` — **MISSING → ZERO**.
- **polyledger:** stores `maker_base_fee`/`taker_base_fee` as `float | None`, keeps None for missing (`polyledger/models.py:69-87`). Float, but None-preserving.
- **agent-skills:** `websocket.md:35` documents `fee_rate_bps` on `last_trade_price` events (International).

---

## Cluster question 4 — real-time-data-client: subscription and reconnection

Subscription/filter model (`src/model.ts:26-43`, `examples/quick-connection.ts`): one socket; messages `{"action": "subscribe"|"unsubscribe", "subscriptions": [{topic, type, filters?, clob_auth?, gamma_auth?}]}`. `type: "*"` = all types in a topic. `filters` is a **JSON string** (e.g. `{"market_slug":"slug"}`, a token-id array for `clob_market`). Incoming `Message = {topic, type, timestamp (number), payload, connection_id}`. Topics: comments, activity, crypto_prices, crypto_prices_chainlink, equity_prices, clob_market, clob_user.

The topic/type/filter triple is a clean idea for our future notification or stream contracts. The reconnection pattern is **not worth reimplementing**:
- `client.ts:79` `this.autoReconnect = args!.autoReconnect || true;` — always true; the option cannot disable it.
- `onError` (`client.ts:123-128`) **and** `onClose` (`client.ts:135-141`) both call `connect()` immediately: no backoff, no jitter, possible double sockets, hot loop when the server is down.
- Subscriptions are not re-sent after reconnect unless the caller re-subscribes inside `onConnect`.
- Keep-alive sends the text `"ping"` and relies on `this.ws.pong = this.onPong` (`client.ts:96`), which assigns a property, not a listener. Liveness detection is unreliable.
- `onMessage` drops any frame that does not contain the substring `"payload"` (`client.ts:164`). No sequence numbers, no gap detection, no snapshot/resync.
- `clob_user` sends L2 key/secret/passphrase inside the subscribe JSON (`model.ts:37-38`, example lines 62-69).
- No tests in the repo.

What to take instead: bounded exponential backoff with jitter (as in `polymarket_us/_retry.py`), explicit re-subscribe on reconnect, sequence/timestamp gap detection, and a stream freshness state that goes STALE on silence. None of this is authorized to run unattended now.

---

## Cluster question 5 — polyledger, polymarket-mcp-server, agents, agent-skills

**polyledger — useful ideas (resumable ingestion):**
- Rows and cursor committed in **one transaction** (`polyledger/storage.py:9-11, 275-278`; `pipeline/chain.py:1-6, 63-80`). Matches our immutable-snapshot approach; good template for any future backfill.
- Idempotent writes keyed on `(transaction_hash, log_index)` with `ON CONFLICT DO NOTHING` (`storage.py:83, 269`).
- Reorg buffer: index only to `height - reorg_buffer` (`pipeline/chain.py:44`).
- Final flush always advances the cursor even with no rows (`chain.py:83`).
- Records both `maker_side` and `taker_side` instead of an ambiguous `side` (README data model). Good for our point-in-time trade semantics.
- Price/size **derived** from raw 6-decimal integer amounts; raw ints stored (`models.py:119-121`, `decode.py`). Good: raw evidence kept, derived reproducible.
- Reject: DuckDB + `hypersync` (native, token-gated third-party service; token is a credential → owner approval), float market fields (`models.py:84-87`). International only.
- Credibility: repo created 2026-09-02, 24 commits, single author, account with 1 follower, yet 623 stars / 110 forks in three weeks. **Possible star inflation** (stargazer timestamps could not be fetched: API 404). Treat claims as unverified; the code itself is small and readable (2,654 lines incl. 39 tests).

**polymarket-mcp-server — reject as a component.** MCP safety boundary check:
- The LLM **can place orders without human approval.** The "confirmation" is a tool argument `confirm: bool` that the model itself sets (`src/polymarket_mcp/tools/trading.py:187, 322-345`; schemas at `trading.py:1456-1462, 1500-1506, 1726-1732, 1769-1775`). A first call returns `confirmation_required`; the model can simply call again with `confirm=true`. Only the MCP host's own tool-approval UI (if enabled) would put a human in the loop.
- `ENABLE_AUTONOMOUS_TRADING=true` removes the gate below `REQUIRE_CONFIRMATION_ABOVE_USD` (default 500) (`config.py:85-96`; `utils/safety_limits.py:237-258`). Default caps: MAX_ORDER_SIZE_USD 1000, exposure 5000 (`config.py:63-74`).
- The local web dashboard exposes unauthenticated `POST /api/config` that rewrites `.env`, including `ENABLE_AUTONOMOUS_TRADING` (`web/app.py:485-520`). It binds to loopback by default and warns otherwise (`web/app.py:632-648`). Cross-site request protection depends on FastAPI's JSON content-type handling (UNVERIFIED).
- Tools exposed include `create_limit_order`, `create_market_order`, `create_batch_orders`, `cancel_all_orders`, `execute_smart_trade`, `rebalance_position` (`trading.py:1417-1748`).
- Requires `POLYGON_PRIVATE_KEY` in env (`config.py:31, 132-158`); redacted in its own repr (`config.py:213-214`).
- Depends on archived `py-clob-client>=0.28.0` (`pyproject.toml:15`), which its upstream says no longer works.
- `curl … | bash` installer promoted (`quickstart.sh:9`, `INSTALLATION.md:40`).
- Useful as reference only: its recent commits document International wire quirks found by probing (e.g. `/prices-history` rejects `5m`; data-api market filter silently dropped for some condition ids; gamma `volume7d/volume30d` do not exist, use `volume1wk/volume1mo`) — see `git log` subjects T-0452…T-0463. These are good examples of **"wire behavior differs from docs; verify with captured responses"**.
- Rate-limit table (`utils/rate_limiter.py:17-25`) lists International limits (e.g., market data 200/10 s, gamma 750/10 s). Unverified; International only.

**Polymarket/agents — reject.** Shows exactly what our rules forbid:
- LLM-owned sizing: the order amount is a regex-extracted number from LLM text multiplied by the USDC balance (`agents/application/executor.py:184-189`).
- `one_best_trade` docstring: "executes that trade without any human intervention" (`agents/application/trade.py:27-36`). Execution line is commented out (`trade.py:59-61`) but one uncomment enables it; a weekly scheduler exists (`agents/application/cron.py`).
- Always buys token index `[1]` regardless of the LLM's chosen side (`agents/polymarket/polymarket.py:342`).
- Unbounded recursive retry on any exception (`trade.py:63-65`).
- Unlimited (`MAX_INT`) USDC approval code path (`polymarket.py:93-94`, gated by `_init_approvals(False)` at line 70).
- `shutil.rmtree` of local DB dirs each run (`trade.py:17-25`).

**Polymarket/agent-skills — ideas only (no license).** Markdown only (9 files, 1,855 lines). Describes International auth, orders, CTF, bridge, gasless. It targets "AI agents, autonomous market makers" (`SKILL.md` front matter) and has no human-approval guidance. Stale: lists the v1 exchange `0x4bFb41…` and `@polymarket/clob-client`/`py-clob-client`, while py-sdk now uses new exchange addresses (`environments.py:96-97`). Do not load it as an agent skill here.

---

## Per-repo sections

### 1. Polymarket/polymarket-us-python

- URL: https://github.com/Polymarket/polymarket-us-python — SHA `b44e4c8e7d34cb72582faec68d765fda50afca79` — default `main` — not archived.
- Language Python; 121 KB; 29 stars / 12 forks; created 2026-01-22; last push 2026-09-23. 17 commits; 7 since June 2026.
- Maintainer: official Polymarket org; commits by `harley@polymarket.com` and staff.
- CI: `.github/workflows/ci.yml` — ruff, ruff format, mypy, pytest on 3.10-3.13, minimum-websockets job. Publish workflow to PyPI on push to main (`publish.yml`) with an artifact check script.
- Tests: 137 test functions across 15 files (`grep -c "def test"`). Mock-based (`unittest.mock`, `pytest_httpx`). They test paths, retries, error mapping, headers, WS message dispatch. They do not test against live responses. `tests/test_retries.py:16` contains a hardcoded Ed25519 **test** key (fixture, not a credential).
- Docs: README (385 lines) with migration notes. Types are the de-facto schema.
- Releases: version 1.0.1 in `pyproject.toml`; no git tags; PyPI publish by workflow.
- Runtime deps (3): httpx, pynacl, websockets.
- Security-sensitive behavior: Ed25519 signing (`auth.py:6-44`); order placement/cancel/close-position (`resources/orders.py`); no logging of secrets (grep: no `logging`/`print` in package). `subprocess` only in `tests/test_pypi_artifacts.py:5,45` (test tooling). No telemetry. Only venue domains.
- Credential handling: key id + base64 secret passed to constructor; stored on the client object (`client.py:80-81`) and passed to WS objects (`client.py:286-290`). Not persisted.
- Network: HTTPS to gateway/api hosts; retries GET/DELETE; 30 s timeout default.
- License: MIT, `LICENSE` (Copyright 2026 Polymarket); matches `pyproject.toml:9`. Compatible.
- Known limitations: TypedDicts only, no validation; floats for liquidity/volume/balances; no price history; WS requires keys; no reconnection; `bidDepth` semantics undocumented.
- README vs code: README calls settlement "settlement price"; code returns a bare number with no timestamp. README says WebSocket gives "order book" data — code confirms, but authenticated only.
- Key files: `polymarket_us/client.py`, `_retry.py`, `resources/markets.py`, `types/markets.py`, `types/events.py`, `types/orders.py` (fee fields), `websocket/types.py`, `tests/test_markets.py`.
- Learn: the whole public endpoint catalog and envelopes; no-idempotency-key → never retry POST; correlation id.
- Must NOT import: the package itself (deps + trading surface); `orders`, `portfolio`, `account`, WS private.
- Overlap: `http.py` (retries), `opportunity.py` (ExecutableQuote/DepthLadder), `kalshi_quotes.py` (complement pricing), `fee_schedules.py` (US fee: UNVERIFIED).
- Shared primitive unlocked: a second venue for the venue-neutral quote contract; "Amount{value,currency}" → Decimal parser; settlement-endpoint label source.
- Reuse class: **REIMPLEMENT_IDEA**. Scores: FIT 5, SHARED 3, MAT 3, MAINT 4, SEC 4, LIC 5, INT 3, UNIQ 4, OCT22 5 = **36**.
- Action: **APPLY_NOW** — use as the endpoint/field reference for the stdlib adapter; verify every field against captured live responses.

### 2. Polymarket/py-sdk

- URL: https://github.com/Polymarket/py-sdk — SHA `1f5ca055d31a29a4fa0ad7955ee4a8bf8aaab3e6` — `main` — not archived.
- Python; 2.8 MB; 129 stars / 34 forks; created 2026-05-04; last push 2026-09-23; 679 commits; release-please tags (`polymarket-client-v0.9.0` …); `pyproject.toml` version 0.11.0.
- Official org (`engineering@polymarket.com`). CI: 7 workflows (ci, integration [workflow_dispatch, self-hosted runner], publish, release-please, verify, api-reference, pull-request).
- Tests: 177 files, 2,221 test functions. Strict pyright. Integration tests marked `integration`; order-placing tests marked `metered` and skipped unless an env var opt-in is set (`tests/integration/conftest.py:27-48`). Good pattern.
- Runtime deps (8): eth-abi, eth-account, eth-utils, httpx[http2], msgpack, pydantic, typing-extensions, websockets. Optional pandas/polars/pyarrow.
- Security-sensitive: wallet derivation, EIP-712 signing, gasless relayer, session keys, perps signing, bridge/transactions (`src/polymarket/_internal/actions/relayer/*`, `transactions.py`, `session_keys.py`). Default Polygon RPC is a third-party public endpoint `https://polygon.drpc.org` (`environments.py:110`). No subprocess/eval/pickle/telemetry found.
- License: MIT `LICENSE`; `pyproject.toml` license text MIT. Compatible.
- Product: International only (see Q1).
- Worth studying: Decimal parsing with empty-string→None (`models/clob/_validators.py:15-45`), epoch-ms timestamp validation that rejects signs/spaces (`_validators.py`), `Page(items, has_more, next_cursor, total_count)` (`pagination.py:22-27`) with required drain limit so truncation is never silent, `RateLimitUpdate` from `Poly-RateLimit-*` headers (`rate_limit.py`), `FeeSchedule` model, metered-test gating.
- Must NOT import: package (8 deps, wallet/signing); `_parse_platform_fee_info` zero default (`market_data.py:211-213`).
- Overlap: `fees.py`/`fee_schedules.py` (fee curve family), `http.py`, `freshness.py`.
- Reuse class REFERENCE_ONLY. Scores: FIT 2, SHARED 3, MAT 5, MAINT 5, SEC 3, LIC 5, INT 1, UNIQ 3, OCT22 1 = **28**. Action: LATER (only if International research is ever authorized; `EXECUTION_PLAN.md:164` currently excludes it).

### 3. Polymarket/real-time-data-client

- URL: https://github.com/Polymarket/real-time-data-client — SHA `c937d9c11cdd2b771aa4818392a1b6dda65c25de` — `main` — not archived. TypeScript; 137 KB; 228 stars; created 2025-03-04; last push 2026-03-05; 83 commits; tags to v1.4.0 (package.json 1.4.2).
- Official org. CI `workflow.yaml` (lint/build). **Tests: none.**
- Runtime deps (3): isomorphic-ws, tslib, ws. No install hooks (`package.json` scripts: build/lint/deploy/format).
- Security: credentials inside subscribe payload (`model.ts:37-38`); `console.log` of full events on parse miss (`client.ts:168`) and of unsubscribe payloads (`client.ts:205`). No telemetry.
- License MIT `LICENSE` = package.json. Details and defects in Q4.
- Reuse REFERENCE_ONLY. Scores: FIT 1, SHARED 1, MAT 1, MAINT 2, SEC 3, LIC 5, INT 2, UNIQ 1, OCT22 0 = **16**. Action REFERENCE_ONLY (topic/type/filter idea; reject reconnection code).

### 4. Polymarket/py-clob-client-v2

- URL: https://github.com/Polymarket/py-clob-client-v2 — SHA `215fc63a8fd6ec3a10c7edb73997c9772d8686d3` (tag v1.1.0, 2026-07-17) — `main` — not archived. 167 stars; created 2026-03-02; last push 2026-08-17; 68 commits.
- CI: `test.yaml`, `release.yaml`. Tests: 227 functions. Runtime deps (6): eth-account, eth-abi, eth-utils, poly_eip712_structs, py-order-utils, httpx[http2].
- International CLOB. README defers to py-sdk. Security: private-key L1 auth, order signing. No subprocess/eval/pickle.
- Interesting: server-compatible order-book hash — SHA-1 over compact JSON with fixed key order and `hash:""` (`py_clob_client_v2/utilities.py:26-46`). Idea for book-integrity checks in provenance, International only.
- Fee: `/fee-rate` → `base_fee or 0` (`client.py:385-393`) — MISSING→ZERO.
- License MIT `LICENSE`. Reuse REFERENCE_ONLY. Scores: FIT 1, SHARED 2, MAT 3, MAINT 3, SEC 3, LIC 5, INT 1, UNIQ 2, OCT22 0 = **20**. Action REFERENCE_ONLY.

### 5. Polymarket/py-clob-client (ARCHIVED)

- URL: https://github.com/Polymarket/py-clob-client — SHA `b076b04d61135657e25dccc1bbd6866a96bd8c6e` — archived. 1,232 stars; created 2022; 344 commits; setup.py 0.34.6. Tests: 106.
- README: "no longer functional and should not be used". Runtime deps include `python-dotenv` and `py-builder-signing-sdk` (setup.py:17-25).
- Fee `base_fee or 0` (`py_clob_client/client.py:450-455`).
- License MIT `LICENSE`. Reuse **REJECT**. Scores: FIT 0, SHARED 1, MAT 2, MAINT 0, SEC 3, LIC 5, INT 1, UNIQ 1, OCT22 0 = **13**. Action REJECT (dead upstream; still pulled in by polymarket-mcp-server).

### 6. Polymarket/polymarket-cli

- URL: https://github.com/Polymarket/polymarket-cli — SHA `9b18b5faf5493b945c48ca22efaf9645f0c69ab8` — `main` — not archived. Rust; 2,882 stars; created 2026-02-24; last push 2026-05-26; 51 commits; tags to v0.1.5 (Cargo 0.1.4). CI `ci.yml`, `release.yml`. 50 integration tests in `tests/cli_integration.rs`.
- **License: no LICENSE file in the tree** (GitHub API: none). `Cargo.toml:7`, `README.md:491-493`, `Formula/polymarket.rb:5` all say MIT. Per audit rule: **no code reuse**; ideas only until a LICENSE file exists.
- Security: private key persisted in plaintext `~/.config/polymarket/config.json` (`src/config.rs:14-20, 96-130`); 0600/0700 on Unix, **default permissions on Windows** (`config.rs:128-131`). Key also accepted via `--private-key` flag (visible in shell history/process list) (`config.rs:26-41`). `curl … | sh` installer (`README.md:19`, `install.sh`) — it does verify a SHA-256 from the same release (`install.sh:44-72`), which only protects against transport corruption, not a compromised release. Self-upgrade shells out to `curl`, `tar`, `sudo mv` (`src/commands/upgrade.rs:41-196`). International trading, approvals, CTF, bridge commands.
- README warns "early, experimental … do not use with large amounts of funds" (`README.md:5`).
- Reuse LICENSE_REVIEW_REQUIRED. Scores: FIT 1, SHARED 1, MAT 2, MAINT 3, SEC 2, LIC 1, INT 1, UNIQ 1, OCT22 0 = **12**. Action REFERENCE_ONLY.

### 7. Polymarket/agents (ARCHIVED 2024)

- URL: https://github.com/Polymarket/agents — SHA `081f2b5594c37edeb9d3780a778c084d5b6f2743` — archived. 3,803 stars; 7 commits in clone history; last push 2024-11-05. Python, 1,966 lines. CI: python-app, docker-image, dependency-review. Tests: `tests/test.py` only (30 lines). `requirements.txt` 170 lines.
- License MIT `LICENSE.md`.
- Findings in Q5 (LLM-owned sizing, hardcoded outcome index, recursive retry, MAX_INT approval path, unattended scheduler).
- Reuse **REJECT**. Scores: FIT 0, SHARED 0, MAT 1, MAINT 0, SEC 1, LIC 5, INT 1, UNIQ 1, OCT22 0 = **9**. Action REJECT (useful only as a negative example for adversarial-validation docs).

### 8. Polymarket/agent-skills

- URL: https://github.com/Polymarket/agent-skills — SHA `91ee44ae113e958affd20cd505c6e9d9d6100e0b` — not archived. Markdown only; 189 stars; one commit (2026-02-19). No CI, no tests. **No LICENSE file** (API: none).
- Content and staleness in Q5. No executable code; no hooks.
- Reuse LICENSE_REVIEW_REQUIRED. Scores: FIT 1, SHARED 1, MAT 1, MAINT 1, SEC 3, LIC 0, INT 3, UNIQ 1, OCT22 0 = **11**. Action REFERENCE_ONLY (do not install as a skill).

### 9. dev-polymarket/clob-client-v2 — SECURITY / TYPOSQUAT ASSESSMENT

- URL: https://github.com/dev-polymarket/clob-client-v2 — SHA `8d0df58a6e54563891947053b0a0d83ce26b0c0f`. Owner type **User** (not the Polymarket org). Official comparison: `Polymarket/clob-client-v2` head `801696edfe0a5661f325ed8f0e1be3ad47e0ea3f` (2026-09-23).
- **Package name:** repo `package.json:2` = `@polymarkets/clob-client-v2` (extra "s") vs official `@polymarket/clob-client-v2`. README tells users to `npm i @polymarkets/clob-client-v2`. Classic scope typosquat.
- **npm registry (read-only `npm view`):** `@polymarkets/clob-client-v2` maintainer `polymarkets <tbmse5159@outlook.com>`; versions 1.0.0-1.0.4 published within 6 minutes on 2026-05-07, 1.0.5 on 2026-05-13, **1.0.6 on 2026-08-08, which is not in the GitHub repo** (repo `package.json` says 1.0.4; dist header says 1.0.5). The 1.0.6 tarball was **not downloaded or inspected → content UNVERIFIED**. Official maintainers are `@polymarket.com` addresses.
- **Install hooks:** none in repo `package.json` scripts; none in npm 1.0.6 metadata scripts (build/lint/format/deploy/test). Official has `prepare: husky` (dev only).
- **Repo contents:** no `src/`, no tests, no CI — only prebuilt `dist/` (index.js/cjs/d.ts + source maps), `examples/`, README, LICENSE. Users cannot audit from source without the source map.
- **Code comparison:** I extracted `sourcesContent` from `dist/index.js.map` (37 files) and diffed against official tags. 31 files match official v1.0.5 exactly. 6 differ: `client.ts`, `types/clob.ts`, `utilities.ts`, `signing/hmac.ts`, `headers/index.ts`, `http-helpers/index.ts`. The hmac/http-helpers differences match **older official code** removed in official commit `e4bdef8` (2026-05-07, "Fixes/partner reviews (#49)"): Node `crypto.createHmac` HMAC and verbose `console.error` logging. So the dist is a copy of official code from just before that fix, relabeled. Confirmed by scanning official history: **all 37 embedded source files are byte-identical (CRLF-insensitive) to official commit `db0c58883dbc` (2026-05-03, "Feat: slippage fee calculation (#57)")**, the parent of `e4bdef8`. The lookalike npm package was first published 2026-05-07, the same day official merged the fix.
- **Injected code check:** identifiers and string literals in `dist/index.js` minus the embedded sources leave only bundler artifacts (`Chain2`, `__PURE__`, enum reverse-maps, CommonJS shims). No hardcoded URLs at all (host is caller-supplied, as in official). No `eval`, `new Function`, `atob`, `child_process`, `process.env`, dynamic `import()`, `fetch`, browser storage access. Contract addresses are a **subset** of official (no swapped exchange/collateral addresses; missing official's newer `0x9fE6…` and `0xe333…`).
- **Credential exposure present in the copied code:** `http-helpers` logs `err.response?.config` via `console.error(JSON.stringify(...))` on request errors (sq source `src/http-helpers/index.ts`, ~lines 113-121). Axios `config` includes request headers, i.e. `POLY_API_KEY`, `POLY_PASSPHRASE`, `POLY_SIGNATURE`, and the body. Official removed this. Any log collector would capture L2 credentials.
- **Star-inflation / impersonation signals:** 512 stars and 291 forks vs official 75 stars / 32 forks; repo created 2026-05-04; 13 commits, mostly "docs: full rewrite"/"Lightweight dependency". Account `dev-polymarket` (id 255865052), display name "PolymarketDevs", bio "Polymarket Developer Community", created 2026-01-19; its other 18 repos are **all forks** of unrelated AI projects with 0 stars. Commit authors "Jan Hoffmann", "PolymarketDevs" and "evanphi7" all use the same noreply id `255865052+…`, i.e. one account renamed and author names varied. Stargazer timestamps: API returned 404 (UNVERIFIED distribution).
- Verdict: **impersonation/typosquat. The repo snapshot shows no active exfiltration, but the published npm 1.0.6 is unaudited and the maintainer is not Polymarket.** Any `npm i @polymarkets/...` in any environment should be treated as a supply-chain incident.
- License: MIT `LICENSE` present, but provenance is untrusted.
- Reuse **REJECT**. Scores: FIT 0, SHARED 0, MAT 0, MAINT 0, SEC 0, LIC 2, INT 0, UNIQ 0, OCT22 0 = **2**. Action **REJECT**; add `@polymarkets/*` to any dependency denylist if we ever add JS tooling.

### 10. caiovicentino/polymarket-mcp-server

- URL: https://github.com/caiovicentino/polymarket-mcp-server — SHA `21f65f319ff0fc4250ea1e5094581761906839e1` — not archived. Python; 1.5 MB; 676 stars; created 2025-11-11; last push 2026-09-20; 218 commits (210 by one author; recent ones by an automated "farm" agent). Tags v0.1.0, v0.2.0.
- CI: tests.yml, release.yml, docker-publish.yml. Tests: 160 files, 1,444 test functions. Many top-level markdown "summary" files (PROJECT_COMPLETE.md, DEMO_VIDEO_SCRIPT.md…) — docs are noisy.
- Runtime deps (11): mcp (<1.31), py-clob-client (archived), websockets, eth-account, python-dotenv, httpx, pydantic, pydantic-settings, fastapi, uvicorn, jinja2.
- Security: see Q5. Also `docker-compose`, `k8s/` manifests (deployment surface). Loads Chart.js from jsdelivr CDN in dashboard.
- License MIT `LICENSE`.
- Reuse REFERENCE_ONLY (wire-quirk notes). Scores: FIT 1, SHARED 2, MAT 3, MAINT 4, SEC 1, LIC 5, INT 1, UNIQ 2, OCT22 0 = **19**. Action **REJECT** as a component; never connect it to an LLM session in this project.

### 11. nahrek/polyledger

- URL: https://github.com/nahrek/polyledger — SHA `62b889a9f4cc329d5a42d0d2daa7cfccb3b7bc34` — not archived. Python; 136 KB; 623 stars / 110 forks; created 2026-09-02; last push 2026-09-22; 24 commits; no tags; **no CI**. Tests: 39 functions (clients 13, decode 10, storage 16).
- Runtime deps (4): hypersync (native, needs bearer token from envio.dev), duckdb, httpx, pydantic.
- Security: bearer token from `.env` (`.env.example`); network to `polygon.hypersync.xyz`, clob, gamma only. No subprocess/eval/pickle. `polyledger query` runs arbitrary SQL against the local DuckDB file (user-driven).
- License MIT `LICENSE` = pyproject.
- Details in Q5. Reuse REIMPLEMENT_IDEA. Scores: FIT 2, SHARED 3, MAT 2, MAINT 2, SEC 3, LIC 5, INT 1, UNIQ 2, OCT22 1 = **21**. Action LATER (pattern for any future resumable backfill; International on-chain data is not authorized now).

---

## Cross-cutting findings for Market Edge

1. **Do not conflate products.** Only `polymarket-us-python` is US. Every other repo here is International and uses Polygon wallets. Nothing in them transfers to the US adapter except generic patterns.
2. **SDK types are not evidence.** The official US SDK shipped wrong book/BBO/settlement types for ~8 months (fixed 2026-09-22, commit `38e16ad`). Capture live responses as raw evidence and write parsers and fixture tests against those.
3. **MISSING → ZERO is common in official code** (`py-sdk market_data.py:211-213`; `py-clob-client(-v2)` `base_fee or 0`). Our fee layer must keep `UNVERIFIED` for Polymarket US until a fee document is captured.
4. **"Confirmation" set by the model is not human approval** (mcp-server). Any future Market Edge tool surface must put approval outside the LLM's argument space.
5. **Typosquat exists for the official TS client** under `@polymarkets/`. Pin by exact scope and verify maintainers if JS is ever used.
6. Good patterns to reimplement: never retry non-idempotent requests (`polymarket_us/_retry.py`); correlation id per request; metered-test opt-in gate (`py-sdk tests/integration/conftest.py`); atomic rows+cursor commits and reorg buffer (polyledger); required drain limit so pagination truncation is never silent (`py-sdk pagination.py`).
