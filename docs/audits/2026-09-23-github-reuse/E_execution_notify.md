# Cluster E: execution boundaries, agent harnesses, cross-market logic, notifications

Reviewer: read-only researcher (Claude). Date: 2026-09-23.
Method: static reading only. Nothing was installed, built or executed. Clones live under
`scratchpad/repos/<owner>__<repo>`. hummingbot and ntfy are sparse, depth-1 fetches of the
pinned SHA. Repo metadata (stars, pushed_at, archived) came from `gh api repos/<o>/<r>` on 2026-09-23.
Paths below are relative to each clone root unless stated.

Context: Market Edge is at Gate 7. No order path exists. Everything execution-related here is
FUTURE architecture input only. None of it authorizes an order, credential, account or paid service.

---

## 1. hummingbot/hummingbot-api

| Field | Value |
|---|---|
| URL | https://github.com/hummingbot/hummingbot-api |
| Reviewed SHA | d276034aee978d826bf05afcc2197eb1360c4a6a (2026-09-23, "Merge PR #235") |
| Default branch / archived | main / false |
| Language / size | Python (FastAPI). 231 tracked files, ~3.3 MB |
| Activity | pushed 2026-09-22. 142 stars, 196 forks, 39 open issues |
| Maintainer | Official Hummingbot Foundation org |
| CI | `.github/workflows/docker_buildx_workflow.yml` builds Docker images only. No test workflow found. |
| Tests | 61 files under `test/`, 678 `def test` functions. Regression-style tests named after bugs (e.g. `test_deploy_controllers_path_traversal.py`, `test_websocket_auth_channels.py`). Not run by CI (UNVERIFIED whether run elsewhere). |
| Docs | README is good on deployment security (Tailscale, loopback bind). `config.py` documents every setting. |
| Releases | `version.py`. Docker images. The `hummingbot` core dependency is deliberately unpinned (`environment.yml` comment). |
| Runtime deps | Heavy: fastapi, uvicorn, boto3, pandas, numba, numpy, pandas-ta, ta-lib, docker-py, hummingbot (unpinned), sqlalchemy, asyncpg, psycopg2, aiomqtt, logfire, geckoterminal-py, msgpack, pydantic-settings and more (~25). Plus PostgreSQL and EMQX containers. |
| License | MIT, `LICENSE` ("Copyright (c) 2023 Hummingbot Foundation"). Compatible. |

**Security-sensitive behavior**
- `docker-compose.yml:15` mounts `/var/run/docker.sock` read-write into the API container. That is host-root equivalent. `services/self_upgrade.py:439` re-mounts it for upgrades.
- Authenticated users can upload Python: `routers/scripts.py:151-170` writes `scripts/<name>.py` from the request body. `utils/file_system.py:275-290` then `importlib.import_module`s it. Controllers work the same way (`routers/controllers.py:200`). So any Basic-Auth holder, including an LLM through MCP, can execute arbitrary code.
- Insecure defaults are warn-only. `config.py:98-121` sets USERNAME `admin`, PASSWORD `admin` and CONFIG_PASSWORD `a`. `warn_if_insecure_security_defaults` (`config.py:134-150`) only logs CRITICAL. It does not refuse to start.
- `pickle.load` on local cache files: `services/backtesting_service.py:462`, `services/candles_cache.py:101`.
- `subprocess.run(['chmod', ...])` in `services/bots_orchestrator.py:574-577` and `utils/file_system.py:485-488`.
- Telemetry: `main.py:430` `logfire.configure(send_to_logfire="if-token-present")`. It sends only if a Logfire token is configured.

**Credential handling (question 1)**
- Storage: `credentials/<account_name>/connectors/*.yml`, one folder per account (`utils/security.py:31-42`).
- Encryption: `hummingbot/client/config/config_crypt.py:44-60` (core) builds an Ethereum keystore-v3 JSON, PBKDF2 then AES-128-CTR (`:82-132`), hex-encoded into the YAML.
- Key isolation is per-account on disk, but **one CONFIG_PASSWORD encrypts every account's keys** (`config.py:112`, "used to encrypt ALL connector credentials"). All accounts are decrypted into one process (`utils/security.py:31`). There is no per-account key, no HSM and no separate signer.
- API auth is HTTP Basic with one static username/password, compared with `secrets.compare_digest` (`main.py:436-456`). It applies to every router (`main.py:460-476`). There are no scopes, no per-token permissions and no read-only role.
- Network: `docker-compose.yml:12` binds `${API_BIND:-127.0.0.1}:8000`, loopback by default. Tailscale is recommended for remote access (README "Secure Connection via Tailscale"). This is a reasonable private-network pattern.

**Order and bot lifecycle**
- `POST /trading/orders` (`routers/trading.py:34-83`) calls `accounts_service.place_trade` (`services/accounts_service.py:874+`). That checks account, price for LIMIT, trading rules, min size and notional, then calls `connector.buy/sell`, which generates the client order id server-side. **There is no idempotency key.** An HTTP client retry after a timeout places a second order. The response says `status="submitted"` before the venue acknowledges.
- Startup reconciliation (`services/unified_connector_service.py:1059-1080`) re-asks the exchange about every persisted active order. It "never mark[s] an order terminal unless the exchange confirms it". Transient errors leave the order untouched. This is a good principle. One caveat: "not found" is mapped to CANCELLED, which conflates "never accepted" with "cancelled".
- Orphan handling: `routers/executors.py:362-410` lists and resolves positions left without an owner after restarts. It is honest about needing external reconciliation.
- Bot lifecycle: `routers/bot_orchestration.py` (`/start-bot`, `/stop-bot`, `/deploy-v2-controllers`, `/stop-and-archive-bot`) drives Docker containers through docker.sock.

**AI/MCP boundary (question 1)**
- The MCP server is not in this repo. The README (`README.md:109-145, 244-253`) points to `hummingbot/hummingbot-mcp` (Docker image) with `HUMMINGBOT_API_URL`. The MCP source reviewed is Condor's copy (section 3).
- The API itself has **no human-approval concept**. Anything holding the Basic-Auth credentials can place orders, start bots and upload code. An LLM connected through `hummingbot-mcp` in an external host (e.g. `claude mcp add`) is limited only by that host's own tool-permission prompts. The README concedes the risk (`README.md:7`: MCP and agents "make powerful API actions easier to trigger").

**README vs code**
- The README recommends Tailscale and strong passwords. The code defaults to loopback, which is good, but default credentials only produce a warning.
- The "secure" framing does not mention the docker.sock mount or the code-upload endpoints.

**Assessment**
- Learn:
  - loopback-by-default binding;
  - reconcile-on-startup that never invents terminal states;
  - orphan listing as a first-class endpoint;
  - "no secret is a tool parameter" (see Condor).
- Must NOT import:
  - Basic auth with one global password;
  - one master password for all venues;
  - docker.sock;
  - code-upload endpoints;
  - server-generated order ids with no idempotency key;
  - warn-only insecure defaults.
- Overlap: planned `execution_ticket.py`, `venues.py`.
- Shared primitive: reconcile semantics (CONFIRMED_TERMINAL / STILL_OPEN / UNVERIFIED).
- **Reuse class: REFERENCE_ONLY.**

Scores: PROJECT_FIT 2, SHARED_FOUNDATION 2, MATURITY_TESTS 3, MAINTENANCE 5, SECURITY 1, LICENSE_EASE 5, INTEGRATION_EFFORT 1, UNIQUE_VALUE 3, OCT22_IMPACT 0. **Total 22/45.**
**Action: REFERENCE_ONLY.** Use it as a list of execution-service anti-patterns plus one good reconcile rule. It is a crypto-bot fleet manager, not a boundary we can adopt.

---

## 2. hummingbot/hummingbot (core, sparse)

| Field | Value |
|---|---|
| URL | https://github.com/hummingbot/hummingbot |
| Reviewed SHA | 9af100d6822da7d2d0291a906c730ef172284ee2 (2026-09-22, "Merge PR #8467 from staging") |
| Default branch / archived | master / false |
| Language / size | Python + Cython. 1,892 tracked files at this SHA. Sparse checkout ~1.5 MB. |
| Activity | pushed 2026-09-22. 20,170 stars, 4,954 forks, 172 open issues |
| Maintainer | Official Hummingbot Foundation |
| CI | `.github/workflows/workflow.yml` runs tests with a coverage gate (`:89-105`, "Validate coverage for the changes"). |
| Tests | 688 test `.py` files repo-wide. `test/hummingbot/connector/test_client_order_tracker.py` has 35 tests, incl. lost-order and not-found cases (`:760-1003`). `test/hummingbot/core/data_type/test_in_flight_order.py` has 16. The Kalshi perpetual connector has 132 tests across 6 files. |
| Runtime deps | Very heavy: Cython build, aiohttp, cachetools, async_timeout, eth_account/eth_keyfile, hexbytes, cryptography, pydantic and many more. |
| License | Apache-2.0, `LICENSE`. Compatible, but attribution/NOTICE duties apply if code is copied. |

**Files studied**
- `hummingbot/core/data_type/in_flight_order.py`
- `hummingbot/connector/client_order_tracker.py`
- `hummingbot/connector/exchange_py_base.py`
- `hummingbot/connector/utils.py`
- `hummingbot/connector/derivative/kalshi_perpetual/*`
- `hummingbot/client/config/config_crypt.py`

**InFlightOrder state machine (question 1)**
- States (`in_flight_order.py:21-32`): PENDING_CREATE, OPEN, PENDING_CANCEL, CANCELED, PARTIALLY_FILLED, FILLED, FAILED, PENDING_APPROVAL, APPROVED, CREATED, COMPLETED.
- `is_open` = {PENDING_CREATE, OPEN, PARTIALLY_FILLED, PENDING_CANCEL} (`:176-182`). `is_done` = CANCELED/FILLED/FAILED or executed ≥ amount (`:185-190`).
- **Transitions are not guarded.** `update_with_order_update` assigns `self.current_state = order_update.new_state` unconditionally (`:341`). There is no transition table and terminal states are not absorbing. The Kalshi connector had to patch the resulting race by hand: an OPEN from the create response resurrected an order the user stream had already reported FILLED (`kalshi_perpetual_derivative.py:325-351`).
- Fills are deduplicated by `trade_id` (`in_flight_order.py:358-361`). Executed amounts accumulate from fills (`:365-366`).
- Decimal handling is mixed. `math.isclose(self.executed_amount_base, self.amount)` coerces Decimal to float (`:188, :197`). `quantize(Decimal('1e-8'))` is used in `check_filled_condition` (`:374`).

**Client order id (question 1)**
- `connector/utils.py:50-83`: `prefix + side + base[0]base[-1] + quote[0]quote[-1] + hex(nonce) + md5(uname, pid, ppid)`. When too long it is truncated or re-hashed.
- It is unique per process and time, but **not derived from intent**. A retry of the same intent after a restart gets a new id, so the id gives no idempotency across restarts. The Kalshi perps prefix is `HBOT` with max length 36 (`kalshi_perpetual_constants.py:17-20`).

**Order tracker reconciliation, lost orders, not-found (question 1)**
- `ClientOrderTracker` keeps active orders, a 30 s TTL cache of finished orders and `_lost_orders` (`client_order_tracker.py:34-63`).
- `process_order_not_found` counts not-found hits. After more than `lost_order_count_limit` (default 3) it emits FAILED, moves the order to `_lost_orders` and warns "Please check its status in the exchange" (`:221-265`).
- Lost orders stay fillable (`all_fillable_orders`, `:87-91`). A background loop keeps cancelling and polling them (`exchange_py_base.py:851-867, 1062-1064`). A lost order leaves the lost list only when the exchange reports a terminal state (`client_order_tracker.py:295-301`).
- Base-class weakness: every status-poll error counts toward "lost" (`exchange_py_base.py:1006-1022`). The Kalshi connector overrides this so only a real `404 not_found` or a missing exchange id counts, with this comment: "a network outage of a few polls fails orders still resting on Kalshi … and their later fills are ignored" (`kalshi_perpetual_derivative.py:366-377`).
- **Ambiguous submit is mishandled.** `_create_order` catches any exception from `_place_order`, including a timeout after the venue accepted the order, and marks FAILED (`exchange_py_base.py:461-476, 500-532`). The tracker then stops tracking it (`client_order_tracker.py:439`). After that, status updates for it are ignored: `all_updatable_orders` = active + lost, which excludes cached orders (`:105-109`). The result is a live order the bot believes failed.
- Kalshi perps makes this unrecoverable by id: "Orders are cancelled and queried by Kalshi's order_id only (no client_order_id lookup)" (`kalshi_perpetual_constants.py:45`).

**Kalshi connector note**
- This is **Kalshi margin/perpetuals** (`/margin/...`, `KXBTCPERP`, USD collateral; `kalshi_perpetual_constants.py:8-52`). It is not the binary event-contract API used by KXHIGHNY.
- Auth is RSA-PSS SHA-256 over `timestamp+METHOD+path` (`kalshi_perpetual_auth.py:20-49`), the same signing scheme Kalshi documents for the event API.
- The default fees (5/12 bps of notional; `kalshi_perpetual_utils.py:8-18`) do **not** apply to event contracts.
- Market orders are IOC limits priced with slippage off `get_price` (`kalshi_perpetual_derivative.py:292-298`).

**Credential encryption:** `hummingbot/client/config/config_crypt.py` (see section 1).

**Security scan (sparse paths only):**
- no subprocess, eval or pickle found in the files reviewed;
- the private key is loaded from a PEM string (`kalshi_perpetual_auth.py:56-69`);
- secrets use pydantic `SecretStr` (`kalshi_perpetual_utils.py:26-38`).

**Assessment.** We would reimplement the ideas and not import the code: Cython, a huge dependency tree and crypto-exchange assumptions (`trading_pair.split("-")`).
- Learn:
  - fill dedupe by trade id;
  - fill-derived state (`_order_state` from fill_count/remaining_count, `kalshi_perpetual_derivative.py:474-479`);
  - lost-order quarantine that stays fillable;
  - the not-found vs transport-error distinction (Kalshi override).
- Must NOT copy:
  - unguarded state assignment;
  - exception → FAILED on submit;
  - nonce ids;
  - float `isclose` on money.
- **Reuse class: REIMPLEMENT_IDEA.**

Scores: PROJECT_FIT 3, SHARED_FOUNDATION 3, MATURITY_TESTS 4, MAINTENANCE 5, SECURITY 3, LICENSE_EASE 4, INTEGRATION_EFFORT 1, UNIQUE_VALUE 4, OCT22_IMPACT 1. **Total 28/45.**
**Action: LATER.** Feed the patterns into the `execution_ticket.py` state design when an order path is ever authorized. Nothing to do now.

---

## 3. hummingbot/condor (AI trading agent harness)

| Field | Value |
|---|---|
| URL | https://github.com/hummingbot/condor |
| Reviewed SHA | d89e74f2e3e273bea102c64e4977118e6a88084f (2026-09-16, "Merge PR #240 general_improvements") |
| Default branch / archived | main / false |
| Language / size | Python backend + TS frontend (`frontend/src`, 509 files). 1,363 tracked files, ~20 MB. |
| Activity | pushed 2026-09-22. 189 stars, 100 forks, 73 open issues |
| Maintainer | Official Hummingbot Foundation |
| CI | `.github/workflows/ci.yml` |
| Tests | 371 files under `tests/`, ~4,646 `def test`. Security IDs (SEC-xxx) are referenced in code comments and tests. |
| Runtime deps | ~24: python-telegram-bot, hummingbot-api-client==1.5.9, mcp, pydantic-ai[mcp], fastapi, uvicorn, python-jose, faster-whisper, pandas, plotly, kaleido, scipy, matplotlib, yfinance, pywebpush, bleach, beautifulsoup4 and others (`pyproject.toml`). |
| License | MIT, `LICENSE`. Compatible. |

**AI/MCP boundary (question 1: can an LLM place orders without human approval?)** Yes, in several ways.
1. **Confirmation gate by tool name.**
   - `condor/runtime/danger.py:46-68` lists DANGEROUS_TOOLS: place_order, execute_swap, manage_clmm/amm, control_agent start, create_*_executor, stop_executor, leverage.
   - Interactive surfaces wait for a human. Deny, timeout and "no channel" all cancel (`condor/runtime/confirmations.py:370-420`). This design is sound for chat.
2. **Loop mode auto-approves.**
   - `condor/agents/engine.py:1055-1085` wires `auto_approve_with_risk_check` for unattended agents. `execution_mode` defaults to `"loop"` (`condor/agents/config.py:71-73`).
   - Dangerous executor creates are approved by a deterministic risk engine, with no human (`condor/agents/risk.py:631-700`). Direct `place_order` is refused for agents (`risk.py:851-856`). Everything else is auto-approved (`risk.py:878`).
   - A human must approve `control_agent start` once. After that the loop trades unattended.
3. **`run_code` and `manage_routines` bypass the gate by design.**
   - `danger.py:190-240` states they are deliberately not dangerous-by-name because market reads go through them. They hold "the unrestricted API client".
   - `condor/code_runner.py:16-31`: "There is no sandbox and that is deliberate … calling execute_code is handing over the whole process … admin-equivalent by construction."
   - Both tools are in every profile, including the unattended `tick` profile (`mcp_servers/condor/profiles.py:45-80`).
   - Only `dry_run` refuses them (`risk.py:859-876`, `danger.py:529`). In chat and loop modes, a model can call `client.trading.place_order(...)` inside a snippet with no confirmation. Condor documents this itself.
4. **Secrets are never tool parameters** (`mcp_servers/hummingbot_api/server.py:72-79`). Keys and wallets are managed only in the web dashboard. Adopt this.
5. **The mounted tool surface is the permission model** for ACP bridges (`server.py:2143-2160`, `settings.py:73-85`). Tool muting is enforced by never registering the tool. This is sound, but it is undone by (3).

**Other**
- Telemetry defaults on:
  - a "ping" floor (install, heartbeat, version_change, shutdown) goes to `https://telemetry.hummingbot.org/v1/events` (`condor/telemetry/outbox.py:52`) before any consent;
  - after a notice, "usage" is opt-out (`condor/telemetry/consent.py:1-30`);
  - `CONDOR_TELEMETRY` env overrides.
- Notifications: Telegram plus browser Web Push with a VAPID keypair and RFC 8291 encryption (`condor/push.py:1-40`). Notification text is encrypted to the subscribing browser. This is a useful privacy contrast with ntfy (see section 6).
- There are 247 subprocess/os.system references across `condor/`, `mcp_servers/`, `handlers/` and `utils/`. Not individually audited. The harness shells out to agent CLIs by design.

**Assessment.** This is the most carefully reasoned agent-authority code in the cluster. Its own comments admit the gate is advisory while code execution exists.
- Learn:
  - tool-name danger classification;
  - a pending-confirmation registry with TTL-deny and "no channel ⇒ deny";
  - refusal reasons fed back to the model;
  - "no secret is a tool parameter";
  - a mutation log kept separate from the approval predicate (`danger.py:130-190`).
- Must NOT copy:
  - a code-execution tool in any process holding trading credentials;
  - auto-approve in loop mode;
  - default-on telemetry.
- **Reuse class: REIMPLEMENT_IDEA.**

Scores: PROJECT_FIT 2, SHARED_FOUNDATION 2, MATURITY_TESTS 4, MAINTENANCE 5, SECURITY 2, LICENSE_EASE 5, INTEGRATION_EFFORT 1, UNIQUE_VALUE 4, OCT22_IMPACT 1. **Total 26/45.**
**Action: LATER.** Use it as design input for any future agent/LLM tool boundary. The lesson for now: approval must be enforced at the execution boundary, not in the agent harness.

---

## 4. SpartanLabsXyz/simmer-sdk

| Field | Value |
|---|---|
| URL | https://github.com/SpartanLabsXyz/simmer-sdk |
| Reviewed SHA | 84e678315ae2ffbc820638faee2bd58d4c3453cf (2026-09-23) |
| Default branch / archived | main / false |
| Language / size | Python SDK + TS MCP server (`mcp/`). 431 files, ~4.9 MB. 850 commits. |
| Activity | pushed 2026-09-23. 49 stars, 15 forks |
| Maintainer | Small company (Simmer / Spartan Labs). Commercial hosted service. |
| CI | `ci.yml`, `secret-scan.yml`, `publish-packages.yml`, `main-red-canary.yml` |
| Tests | 78 files under `tests/`, ~782 `def test`. Per-skill tests (e.g. `skills/polymarket-weather-trader/tests/*`). TS tests in `mcp/tests/`. |
| Runtime deps | 8 hard deps: requests, solders, base58, eth-account, py-order-utils, py-clob-client, py-clob-client-v2, polynode. Optional: `ows`. |
| License | MIT, `LICENSE` ("Copyright (c) 2024 Simmer"). `mcp/LICENSE` also present. |

**Unified venue API.** `SimmerClient` (`simmer_sdk/client.py`, 7,467 lines).
- `VENUES = ("sim","simmer","sandbox","polymarket","kalshi","hyperliquid")` (`:276`).
- One `trade(market_id, side, amount, venue=...)` goes to `POST https://api.simmer.markets/api/sdk/trade` (`:3025-3028`).
- Market ids are **Simmer's** ids, resolved by Simmer's server.
- "Kalshi" here means Kalshi markets **via DFlow on Solana** (`client.py:315-316`, `_execute_kalshi_byow_trade` "Get unsigned transaction from Simmer API (via DFlow)"). It is not the regulated Kalshi exchange API.

**Paper/live separation (question 2).** Three different mechanisms, easy to confuse:
1. `venue="sim"` means trading on **Simmer's own server-side LMSR market** with virtual $SIM (`client.py:311-312`). Paper, but not against venue prices.
2. `live=False` means **client-side** in-memory paper via `simmer_sdk/paper.py` (`client.py:572-576, 2851-2855`). The fill price is `external_price_yes or current_probability or 0.5` (`client.py:3167`). **Missing price becomes 0.5**, plus a half-spread (default 0.01 when `spread_cents` is missing, `:3127, :3172-3185`). There are no fees and no depth, floats are used, and state is lost at process exit (`paper.py:1-10`). Prices still come from the Simmer API.
3. `dry_run=True` on `trade()` asks the server to price without executing (`client.py:2933-2934`).

Risks:
- **`live` defaults to True** (`client.py:296`). `venue="polymarket"` with defaults is real money.
- A private key is **auto-read from `WALLET_PRIVATE_KEY`** (or legacy `SIMMER_PRIVATE_KEY`) env vars (`:282-285, :464-494`).
- The skills default to dry-run unless `--live` (`skills/kalshi-weather-trader/weather_trader.py:8-10, :1135`).

**Safety context and conflict checks**
- `PreflightResult` has blocker codes EXPOSURE_CAP_EXCEEDED, EXPOSURE_UNKNOWN (fail-closed), WALLET_UNVERIFIED, VENUE_UNSUPPORTED and INSUFFICIENT_GAS (`client.py:200-235`).
- Real-venue `dry_run=False` must pass preflight (`:2857-2881`), unless `skip_preflight`.
- Rebuy and cross-skill conflict checks use `source` tags from the server's held-markets list (`:2883-2912`).
- `approvals.py:125, :240` sets ERC20 `approve(spender, MAX_UINT256)`, i.e. unlimited allowances.

**Skill/agent structure**
- `skills/<name>/{SKILL.md, clawhub.json, *.py, tests/}` plus `mcp/src/skill-runner.ts` and `per-skill-tools.ts`.
- Directly overlapping domain: `skills/kalshi-weather-trader/weather_trader.py` uses NOAA `api.weather.gov` point forecasts. It **hard-codes `noaa_probability = 0.85`** when the forecast falls in a bucket (`:971-973`) and buys if price < 0.15 (`:387`). That is an invented probability, the opposite of Market Edge's calibrated EXP-001.

**Hosted service / API key / network**
- Every client needs `api_key` (`sk_live_...`, sent as `Authorization: Bearer`, `client.py:527`).
- Base URL defaults to `https://api.simmer.markets` (`:376`).
- The User-Agent reports SDK version, Python version and runtime (`:529`).
- Trades carry `reasoning` and `source` fields to Simmer's server (`:2935+`).
- Signed Polymarket orders are built locally but **relayed through Simmer's `/api/sdk/trade`** (`:2981-3028`).
- Other hosts: clob.polymarket.com, data-api.polymarket.com, combos-rfq-api.polymarket.com, api.hyperliquid.xyz, pypi.org (`version_check.py`), data.binance.vision, clawhub.ai.

**Security scan**
- `simmer_sdk/backtest/replay/harness.py:30, :217` runs skills via `subprocess.run` with an allowlisted env (`:104-113`).
- No eval, exec or pickle in `simmer_sdk/`.
- The HTTPS-only base_url check is a good touch (`client.py:378-394`).

**Decision (question 2): C, ignore.** Do not consume it and do not adopt its architecture.
- Consuming it adds a hosted third-party service and an API key. It routes orders and "reasoning" through their server. It uses Simmer ids instead of venue-native ids and non-Kalshi "Kalshi". This conflicts with stdlib-only, no-paid/no-account, and venue-native provenance.
- Its paper model violates MISSING≠ZERO (default 0.5) and NO-MIDPOINT-AS-FILL (mid ± assumed half-spread).
- Two ideas are worth noting as reference only, and Market Edge already has equivalents:
  - machine-readable preflight blocker codes with EXPOSURE_UNKNOWN failing closed (~ `opportunity.evaluate` rejection reasons, `risk.py`);
  - a read-only client mode (`_readonly`, `client.py:326-328`).
- **Reuse class: REFERENCE_ONLY.**

Scores: PROJECT_FIT 2, SHARED_FOUNDATION 1, MATURITY_TESTS 3, MAINTENANCE 4, SECURITY 2, LICENSE_EASE 5, INTEGRATION_EFFORT 1, UNIQUE_VALUE 1, OCT22_IMPACT 0. **Total 19/45.**
**Action: REFERENCE_ONLY.** Its weather skill is a useful negative example: a hard-coded 0.85 probability.

---

## 5. chainstacklabs/polymarket-alpha-bot ("Alphapoly")

| Field | Value |
|---|---|
| URL | https://github.com/chainstacklabs/polymarket-alpha-bot |
| Reviewed SHA | 1f4f366b9c677574c8034a8720eaca917a53715b (2026-07-28, "chore(deps): bump next") |
| Default branch / archived | main / false |
| Language / size | Python backend + Next.js frontend. 146 files, ~2.6 MB. 127 commits. |
| Activity | last push 2026-08-05. 181 stars, 42 forks, 4 open issues |
| Maintainer | Chainstack Labs (a company org; RPC-provider marketing/demo repo) |
| CI | None found (`.github/` absent). |
| Tests | 3 files, 23 tests (`backend/tests/test_clob.py`, `test_deposit_wallet_flows.py`, `test_parse_ctf_ids.py`). **No tests** for the grouping, implication, validation or portfolio math. |
| Runtime deps | httpx, loguru, python-dotenv, rich, fastapi, uvicorn, websockets, watchfiles, eth-account, web3, cryptography, polymarket-client==0.1.0b8 (`backend/pyproject.toml:6-23`). Also GLiNER2 and BGE embedding models (`core/models.py:18-24`) and OpenRouter LLMs. |
| License | Apache-2.0, `LICENSE`. |

**Pipeline (question 3)**
1. **Fetch.** Polymarket Gamma events (`core/steps/fetch.py`).
2. **Group.** Deterministic and rule-based (`core/steps/groups.py:1-30, :297-409`). One Polymarket event is one group. The partition type (timeframe, threshold, candidate, single) comes from regex bracket detection. No LLM.
3. **Implications.** **LLM only**, over group **titles** (`core/steps/implications.py:1-140`).
   - The prompt asks for "necessary" A→B relationships with a "counterexample attempt" and a bracket alignment of match or all.
   - Every accepted relationship gets a **hard-coded `NECESSARY_PROBABILITY = 0.98`** (`:37, :244, :260`).
4. **Expand.** Cartesian product of group markets (`core/steps/expand.py:1-30`). `MIN_COVER_PROBABILITY = 0.88` (`:40`) only filters on that constant.
5. **Validate.** Deterministic pre-filter plus LLM (`core/steps/validate.py`).
   - Deterministic part: `check_deadline_coherence` (`:317-378`). Direct relationships need deadlines within 7 days (`:274`). Contrapositive YES/NO pairs need cover_date ≤ target_date.
   - **Fail-open when dates are missing:** "Can't check without dates" → `return True` (`:348-350`).
   - The LLM is then asked for temporal, logical and entity validity and a `viability_score` ≥ 0.90 (`:45, :60-175`). It sees only question, bracket, resolution date, relationship and probability (`format_pair_for_validation`, `:403-422`). **It never sees the market's resolution rules or description text.**
   - A keyword blacklist over the LLM's own prose auto-rejects inconsistent answers (`:241-270, :381-398`).
   - Cached verdicts default `is_valid` to True for old rows (`:538-540`). Validations are cached permanently.
6. **Portfolios.** `core/steps/portfolios.py`.

**Arithmetic check (question 3)**
- `coverage = p_target + (1 − p_target) × cover_probability` (`portfolios.py:77-81`). `p_target` is the **market price used as a probability**. `cover_probability` is the **LLM-derived constant 0.98**.
- `expected_profit = coverage − total_cost` (`:87`) **excludes fees**.
- A separate `profit = 1 − total_cost − expected_fees` (`:177`) **assumes a certain $1 payout**, inconsistent with the probabilistic coverage beside it. There are two different "profit" numbers and neither is an executable EV.
- Prices:
  - Pipeline prices are Gamma `outcomePrices` (`groups.py:359-362`; `expand.py:167-168`). These are display/last/mid-style prices, **not executable asks**.
  - **Missing prices default to 0.5** (`expand.py:167-168`, `runner.py:157-158`, `executor.py:78, :88-89`) or 0.0 (`groups.py:362`).
  - Live repricing uses the **bid/ask midpoint**, or whichever side exists (`server/price_aggregation.py:300-310`).
  - **No depth or size is considered anywhere** in the cost.
- Fees (`core/fees.py:34-56`): `fee = notional × rate × p × (1−p)`, called with `notional = price` per share (`portfolios.py:173-175`). **Missing `feeSchedule` on a fee-bearing market gives fee = 0** with a warning (`fees.py:44-50`). The file itself calls this "display-only". The formula matches their docstring. The current Polymarket fee formula is UNVERIFIED here.
- Execution (`core/trading/executor.py`, `core/trading/clob.py`): split pUSD into YES+NO, then FAK-sell the unwanted side. The sell floor is `price × (1 − slippage%)` with **slippage clamped to at least 10%** (`clob.py:19-24`). Realized entry cost can be far worse than the displayed `total_cost`.

**Is the LLM output deterministically verified?** Only partly.
- The deadline-ordering check is deterministic, but it fails open on missing dates.
- Logical necessity, entity identity and hedge direction are LLM judgments.
- Rule equivalence is **never checked against settlement text**.
- The probability used in the money math is a constant attached to the LLM's verdict.
- This violates Market Edge's rule that LLMs never own final arithmetic or rule equivalence without deterministic verification.

**Agent skills and dashboard**
- `.claude/skills/alphapoly-*/SKILL.md`. The enter-position skill says "require explicit user approval". That is **prompt-level only**: `POST /trading/buy-pair` has no approval or auth (`backend/server/routers/trading.py:72`).
- Dashboard is Next.js (`frontend/`, 43 files).

**Security**
- The FastAPI app has **no authentication**. CORS is `allow_origins=["*"]` with `allow_credentials=True` (`backend/server/main.py:52-58`). It exposes `/wallet/*` (generate, import, unlock, approve-contracts) and `/trading/buy-pair`.
- Uvicorn binds loopback by default (`Makefile:76`, no `--host`). But once the wallet is unlocked in memory, any web page the user visits could plausibly drive `buy-pair` cross-origin. UNVERIFIED by execution.
- The private key is encrypted with PBKDF2 (100k iterations) and a random salt (`core/wallet/encryption.py:12-51`). The password is sent in request bodies (`routers/wallet.py:42-59`).
- **The repo ships `.claude/settings.json` hooks** that run `uv run python .claude/hooks/guard.py/lint.py` on every Write/Edit. Opening this clone in Claude Code would execute repo code. Do not open it as a project.
- `experiments/onchain-otc/*` holds Solidity and anvil scripts.
- No eval, exec, pickle or subprocess in `backend/`.

**Relevance to Market Edge #30 (unique-market discovery, cross-market logic, same-event correlation, Outcome Board)**
- Useful ideas:
  - The **partition taxonomy** (timeframe, threshold, candidate) and "siblings in the same group cannot hedge each other" (`groups.py:1-30`). This maps onto an Outcome Board grouping.
  - The **deadline-coherence rule** for contrapositive covers: a later-resolving NO cannot cover an earlier target (`validate.py:317-378`). This is deterministic and correct as far as it goes, and worth reimplementing fail-closed.
  - Two-way incremental expansion (new target × all covers, all targets × new covers; `expand.py:1-30`).
  - The mutual-exclusivity heuristic "multiple markets share a resolution date" (`expand.py:48-80`).
- The Market Edge inversion: an LLM may only **propose** candidate relationships. A deterministic checker must verify every accepted pair against **captured settlement rules** (source, station, time window, bucket edges), with fail-closed on missing fields. The "coverage" math must use executable asks with displayed size and verified fees. The LLM's probability must never enter PnL.
- **Reuse class: REIMPLEMENT_IDEA.**

Scores: PROJECT_FIT 3, SHARED_FOUNDATION 2, MATURITY_TESTS 1, MAINTENANCE 2, SECURITY 1, LICENSE_EASE 4, INTEGRATION_EFFORT 2, UNIQUE_VALUE 3, OCT22_IMPACT 1. **Total 19/45.**
**Action: LATER.** Borrow the grouping taxonomy and the deadline-coherence rule for #30 when that work is authorized. Reject the arithmetic and the LLM-as-verifier design.

---

## 6. binwiederhier/ntfy

| Field | Value |
|---|---|
| URL | https://github.com/binwiederhier/ntfy |
| Reviewed SHA | 10cb6506f836dbb00bb77e3b52669f6ace37f555 (commit dated 2026-08-27, "Bump") |
| Default branch / archived | main / false |
| Language / size | Go server + web app + Android/iOS clients elsewhere. Sparse: `docs/*.md`, `server/*.go`, `user/`, `model/`, `.github/`. |
| Activity | pushed 2026-09-15. 34,388 stars, 1,613 forks, 409 open issues |
| Maintainer | Individual (Philipp Heckel) with a large community. Hosted ntfy.sh with paid tiers. |
| CI | `.github/workflows/{build,test,release,docs}.yaml` |
| Tests | 372 `func Test` in `server/*_test.go` |
| License | **Dual Apache-2.0 (`LICENSE`) and GPLv2 (`LICENSE.GPLv2`)** (README "License"). We use it over HTTP only, no code reuse, so there is no license friction. |

**Publish API (question 4), from `docs/publish.md` and `server/server.go:1128-1260`**
- Transport: `PUT/POST https://<server>/<topic>` with the body as message, or `POST /` with JSON (`topic`, `message`, `title`, `tags`, `priority` 1-5, `actions`, `click`, `attach`, `markdown`, `icon`, `filename`, `delay`, `email`, `call`, `sequence_id`) (`publish.md:3549-3726`). GET webhooks exist too (`:3726`).
- Headers (`publish.md:4941-4973`; parsed in `server.go:1136-1255`):
  - `X-Title` (≤1 KB);
  - `X-Priority` 1=min, 2=low, 3=default, 4=high, 5=max/urgent (`publish.md:438-455`);
  - `X-Tags` (≤512 B total; some map to emojis);
  - `X-Click`, `X-Actions` (view, broadcast, http, copy), `X-Markdown`, `X-Icon`, `X-Attach`;
  - `X-Delay` (scheduled; updatable and cancelable, `:2587-2925`);
  - `X-Email` (sent via Amazon SES; **5/day on ntfy.sh**);
  - `X-Call` (voice TTS, **authenticated Pro plans only**, `:3422-3440`);
  - `X-Cache: no`, `X-Firebase: no`, `X-Sequence-ID`.
- **Update and dedupe.** `X-Sequence-ID` (regex-validated, `server.go:1136-1145`; default = message id) or `POST /<topic>/<sequence_id>`. A later message with the same sequence id **replaces the notification on clients**. It can also clear or delete (`publish.md:3830-3860`). The server stays append-only. **There is no server-side idempotency or dedupe.** Two POSTs are two messages, so client-visible collapse relies on the sequence id.
- Auth: Basic user:pass (`publish.md:4309`), **access tokens `Authorization: Bearer tk_...`** (`:4428-4445`), or `?auth=` query param (`:4618`; avoid, since it leaks into logs).
- **Topic secrecy.** Without an account "the topic is essentially a password" (`publish.md:311-313`). Topics match `[-_A-Za-z0-9]{1,64}`, and "all topics on ntfy.sh are public" (`:4910-4912`). Reserved (ACL-protected) topics need an account and a tier that allows reservations (`config.md:1699, 2407`). Whether the ntfy.sh free tier includes reservations is UNVERIFIED.
- **ntfy.sh free/anonymous limits** (`publish.md:4919-4940`):
  - 250 messages/day;
  - burst 60 requests, refilling 1 per 5 s;
  - 4,096-byte message;
  - 5 emails/day;
  - attachments 2 MB (20 MB/visitor total), 200 MB/day bandwidth;
  - no phone calls.
- **Privacy (`docs/privacy.md`)**:
  - ntfy.sh **stores message content** (12 h cache by default), topic names, IPs (rate limiting), token metadata and last-access IP;
  - messages are forwarded to **Google FCM** for Play-store Android apps and to Apple for iOS;
  - Twilio is used for calls and Amazon SES for email;
  - TLS in transit only (`privacy.md:171`). **There is no end-to-end encryption** (no E2E option found in docs or server).
  - Mitigations: `X-Cache: no` (lost if the subscriber is offline), `X-Firebase: no` (Play-variant delivery delayed up to 15 min unless instant delivery is on, `publish.md:4798-4810`), or self-host plus the F-Droid app.
- **Self-hosting:** a single Go binary or Docker (`docs/install.md`), configured in `server/server.yml`. It needs an always-on host reachable by the phone. That is either a paid or cloud resource (approval needed) or a LAN/Tailscale box.

**Is ntfy a useful zero-cost push channel now?** Yes, as an optional sink, with limits:
- **Push is not carrier SMS.** Delivery needs the ntfy app (or browser) installed, subscribed and online. It goes over FCM, APNs or a websocket. There is no carrier delivery, no SMS fallback and no delivery receipt. The publish response only proves the server accepted the message.
- ntfy.sh sees plaintext content. Send only non-sensitive headlines: no positions, PnL, balances, account ids or tokens.
- Publishing to ntfy.sh is sending data to an external service. Under AI_INSTRUCTIONS ("publishing data externally", "credentials") the first real send needs **owner approval** recorded in the repo. So does an access token, and so does any scheduled or unattended sender. Local sinks need none.

**Recommended mapping: provider-neutral event → ntfy (design only; `notifications.py` is being built by another agent)**

Event contract fields (neutral):
- `event_id`;
- `dedupe_key` (stable per logical alert, e.g. `exp001-daily-2026-09-23-stale-book`);
- `severity` (DEBUG/INFO/NOTICE/WARNING/CRITICAL);
- `category` (e.g. `freshness`, `settlement`, `shadow_run`, `risk`);
- `title`, `body_text`, optional `body_markdown`;
- `created_at` (UTC), optional `stale_after`;
- `source_module`;
- `links` (list of {label, url, scope: local|public});
- `sensitivity` (PUBLIC_SAFE | PRIVATE);
- `delivery_state` per sink (QUEUED/SUBMITTED/REJECTED/SKIPPED, never "DELIVERED" for push or SMS without a receipt).

| Neutral field | ntfy | SMS (later, e.g. Twilio) | Email (later) | In-app / local |
|---|---|---|---|---|
| sink config (not event) | topic + server URL + optional `Authorization: Bearer` from env/secret store | from/to numbers, provider creds | SMTP creds, to-list | file/SQLite path |
| `title` | `X-Title` (≤1 KB; ASCII or RFC 2047) | prefix of body | Subject | title |
| `body_text` | body (truncate to <4,096 B with an explicit "[truncated]") | body (≤160/segment; truncate hard) | text/plain part | body |
| `body_markdown` | `X-Markdown: yes` only when present (web-app rendering; mobile support UNVERIFIED) | drop | text/html (escaped) | render |
| `severity` | `X-Priority`: DEBUG→not sent, INFO→2, NOTICE→3, WARNING→4, CRITICAL→5 | send only ≥ WARNING | all | all |
| `category`, `severity` | `X-Tags` (e.g. `warning,freshness`; ≤512 B) | omit | header/label | filter |
| `dedupe_key` | `X-Sequence-ID` (sanitize to `[-_A-Za-z0-9]{1,64}`, hash if longer). Update or clear replaces the prior notification. **Also dedupe in a local outbox**, since the server does not. | local outbox only | `Message-ID`/thread | primary key |
| `links` (public https) | `X-Click` (first public link only). Never `127.0.0.1` dashboard links, which do not resolve on a phone. | omit | body link | link |
| actions | **none** (avoid `http` actions, which make the phone send requests) | none | none | local buttons |
| `sensitivity=PRIVATE` | **do not send to ntfy.sh**. Self-hosted only, or replace with a generic "check dashboard" headline | do not send | per policy | full |
| privacy knobs | `X-Firebase: no` optional (delay tradeoff). Keep the cache on for reliability unless PRIVATE. | n/a | n/a | n/a |
| `created_at`, `stale_after` | put in body text. Suppress sending if already stale at send time (fail closed; do not push stale "current" state) | same | same | show age |
| delivery result | store HTTP status + returned message `id`/`time` as SUBMITTED. 429 → backoff and mark RATE_LIMITED. Never retry blindly without the sequence id. | provider SID | SMTP id | written |

Implementation note: a ntfy sink is ~40 lines of stdlib `urllib.request` (POST to the topic with the headers above, a timeout, reuse of `edge_lab/http.py` retry/pacing). No dependency is needed.

**Assessment**
- **Reuse class: DEPENDENCY_CANDIDATE**: an optional external service over plain HTTP with no code imported.
- Scores: PROJECT_FIT 4, SHARED_FOUNDATION 3, MATURITY_TESTS 5, MAINTENANCE 5, SECURITY 3, LICENSE_EASE 5, INTEGRATION_EFFORT 5, UNIQUE_VALUE 4, OCT22_IMPACT 3. **Total 37/45.**
- **Action: NEXT.**
  - Add an `NtfySink` behind the provider-neutral contract once `notifications.py` lands.
  - Keep it disabled by default. The first real send needs owner approval (external data plus an optional token).
  - Payloads must be headline-only and non-sensitive.

---

## 7. caronc/apprise

| Field | Value |
|---|---|
| URL | https://github.com/caronc/apprise |
| Reviewed SHA | 2e72688d0526614980316b483c36d525441b9a4b (2026-09-22, "fixes issue with yaml/config parsing (#1743)") |
| Default branch / archived | master / false |
| Language / size | Python. 528 files, ~11 MB. 160 plugin modules in `apprise/plugins/`. |
| Activity | pushed 2026-09-23. 17,376 stars, 668 forks, 30 open issues. 76 commits since 2026-06-01. Tags up to v1.9.9. |
| Maintainer | Individual (Chris Caron), long-running and active |
| CI | `.github/workflows/{tests,lint,codeql-analysis,pkgbuild,loc-badge}.yml` |
| Tests | 223 files under `tests/`, ~2,078 `def test` |
| Runtime deps | 6 (+1 on Windows): requests, requests-oauthlib, click, markdown, PyYAML, certifi (+tzdata) (`pyproject.toml:42-53`). Transitive: urllib3, idna, charset-normalizer, oauthlib. |
| License | BSD-2-Clause, `LICENSE`. Permissive and compatible. |

**Dependency and security surface (question 5)**
- Plugins:
  - Built-ins are imported dynamically from `apprise/plugins` (`apprise/manager.py:219-232`).
  - **Custom plugin dirs** are loaded with `import_module` from paths (`manager.py:339-470`). In the library that happens only if `AppriseAsset(plugin_paths=...)` is passed (`apprise/asset.py:244-265`).
  - The CLI auto-scans `~/.apprise/plugins`, `~/.config/apprise/plugins` and `/var/lib/apprise/plugins` (`apprise/cli.py:128-133`), and `APPRISE_PLUGIN_PATH` (`cli.py:88`).
  - Any Python file dropped there runs. Library use avoids this if plugin_paths is never set.
- Secrets in URLs: credentials are embedded in service URLs (`ntfys://{token}@{host}/{targets}`, `ntfy.py:194-203`). URLs end up in config files, env vars, logs and exceptions. `pprint`/`PrivacyMode` redaction exists (`ntfy.py:736-826`) but is only used on the paths that call it.
- Config files support `include` (remote or file) with recursion. Insecure includes are disabled by default (`apprise/config/base.py:95-140`).
- Persistent store: `AppriseAsset(storage_mode=AUTO)` (`asset.py:218, 246-277`) may write state to disk if a storage path is set.
- `subprocess` is used only in `plugins/macosx.py:257, 359` (terminal-notifier). No eval, exec or pickle.
- **The ntfy plugin lacks** `X-Sequence-ID`, `X-Cache` and `X-Firebase` at this SHA. It sets only Authorization, Markdown, Priority, Delay, Click, Email, Tags and Actions (`apprise/plugins/ntfy.py:548-609`). The Market Edge dedupe and privacy mapping above would be lost through Apprise.
- Channel coverage is broad: `ntfy.py`, `twilio.py` (SMS), `vonage.py`, `sns.py`, `email/`, `telegram.py`, `signal_api.py`, `pushover.py`, `gotify.py`.

**Decision (question 5): REIMPLEMENT now, DEPEND_ON_LIBRARY maybe later.**
- Now: a stdlib ntfy sink (~40 lines) keeps runtime deps at zero, supports sequence id, cache and firebase knobs, and fits `http.py` pacing and fail-closed rules.
- Reconsider Apprise only if 3 or more paid or credentialed channels become authorized (SMS plus email plus chat). Even then:
  - make it an optional extra (`edge-lab[notify]`);
  - never pass `plugin_paths`;
  - build URLs from the secret store at send time and never persist or log them;
  - pin the version.
- Record that decision in `docs/decisions/` at the time.

Scores: PROJECT_FIT 2, SHARED_FOUNDATION 2, MATURITY_TESTS 5, MAINTENANCE 5, SECURITY 3, LICENSE_EASE 5, INTEGRATION_EFFORT 3, UNIQUE_VALUE 2, OCT22_IMPACT 1. **Total 28/45.**
**Reuse class: DEPENDENCY_CANDIDATE (optional, deferred). Action: LATER.** A tiny stdlib sink wins for a single channel.

---

## Cross-cutting answer to question 1: patterns a FUTURE Market Edge execution boundary should reimplement

Future architecture only. Nothing here is authorized at Gate 7.

1. **Intent-derived, persisted-before-submit client order id.**
   - `client_order_id = f(ticket_id, attempt)` is written to the append-only ledger *before* any network call. A retry reuses it.
   - Contrast: Hummingbot uses nonce + md5(host,pid) (`connector/utils.py:50-83`), and hummingbot-api has no idempotency key (`routers/trading.py:34-83`).
2. **A SUBMIT_UNKNOWN state; transport errors never become FAILED.**
   - A timeout or 5xx on submit goes to SUBMIT_UNKNOWN, followed by reconciliation by client id, fills and positions.
   - Contrast: Hummingbot marks FAILED and stops tracking (`exchange_py_base.py:461-476, 519-532`).
   - Before any live path, check whether the venue supports lookup by client id. Hummingbot's Kalshi perps note says it does not (`kalshi_perpetual_constants.py:45`); UNVERIFIED for the Kalshi event API.
3. **An explicit transition table with absorbing terminal states**, rejecting and logging illegal transitions. Contrast: the unguarded assignment at `in_flight_order.py:341` and the OPEN-after-FILLED race patched at `kalshi_perpetual_derivative.py:325-351`.
4. **Fill-derived truth.** Dedupe fills by venue trade id (`in_flight_order.py:358`). Derive the filled quantity from fills, not from status strings (`kalshi_perpetual_derivative.py:474-479`). Use exact Decimal, never `math.isclose`.
5. **Distinguish NOT_FOUND from TRANSPORT_ERROR.**
   - Only repeated, confirmed not-found may escalate to LOST. Keep LOST orders fillable and keep polling (`client_order_tracker.py:221-265`; Kalshi override `:366-377`).
   - Never mark terminal without venue confirmation (`hummingbot-api services/unified_connector_service.py:1059-1080`).
   - Do not map not-found to CANCELLED; use NEVER_ACCEPTED_OR_EXPIRED plus human review.
6. **Service boundary.**
   - Execution runs in a separate process bound to 127.0.0.1.
   - Per-venue credentials and keys: no single master password, no docker.sock, no code-upload or code-exec endpoints.
   - Fail closed on default or blank credentials rather than warning (contrast `config.py:134-150`).
   - Secrets are never tool or LLM parameters (Condor `server.py:72-79`).
7. **Approval enforced at the boundary, not in the agent.**
   - Every ticket that could move money needs an owner approval artifact checked by the execution service itself.
   - Condor's name-based gate is bypassable through `run_code`/`manage_routines` (`danger.py:190-240`, `code_runner.py:16-31`, `profiles.py:45-80`) and auto-approves in loop mode (`engine.py:1071`, `risk.py:878`).
   - So: no process holding execution credentials may expose arbitrary code execution to an LLM.
8. **Reuse Condor's confirmation mechanics** where a human is in the loop: TTL deny, "no channel ⇒ deny", every non-approval cancels (`confirmations.py:370-420`), and refusal reasons returned in-band.

Market Edge modules that absorb these: `execution_ticket.py` (states, ids, approval artifact), `venues.py` (execution_authorized=False, client-id-lookup capability flag), `shadow_ledger.py` (write-ahead of intent, replay-derived order state), `risk.py` (pre-submit veto).
