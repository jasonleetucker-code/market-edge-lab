# Cluster D — Sports-exchange frameworks, odds tooling, small Kalshi/weather bots

Reviewer: read-only researcher (Claude). Date: 2026-09-23.
Method: every repo was cloned with `--filter=blob:none --no-checkout` into `scratchpad/repos/<owner>__<repo>` and checked out at the pinned SHA. I read the code statically. I did not install or run any third-party code, and I used no credentials. Metadata comes from `gh api repos/<o>/<r>`.
Clone caveat: in `machina-sports__sports-skills`, 9 JSON files under `src/sports_skills/canonical/_operations/owner-records/...` did not check out because of the Windows path-length limit. They are data contracts. I did not review them.

Paths below are relative to each repo root unless noted. Line numbers refer to the pinned SHA.

---

## Summary table

| Repo | SHA-12 | License (file) | Reuse class | Action | Total /45 |
|---|---|---|---|---|---|
| betcode-org/flumine | 54854495b45a | MIT (`LICENSE`) | REIMPLEMENT_IDEA | APPLY_NOW (ideas only: control checklist → execution_ticket contract) | 32 |
| betcode-org/betfair (betfairlightweight) | b00072113e9a | MIT (`LICENSE`) | REIMPLEMENT_IDEA | LATER (when a streaming book is built) | 27 |
| the-odds-api/samples-python | dc344b7e93b7 | NONE (no file; API 404) | REFERENCE_ONLY | NEXT (endpoint/header reference for #29 fixtures) | 18 |
| carterlasalle/SportsArbFinder | b8b6f2a3f31c | MIT (`LICENSE`) | REJECT | REJECT (math bugs; use only as negative test cases) | 13 |
| robbiehaynes/arbitrage-finder | 87fac7f22a59 | BSD-3-Clause (`LICENSE`) | REJECT | REJECT | 13 |
| timsonater/action-network-scraper | 6607b1f2bf59 | NONE (no file) | REFERENCE_ONLY | REFERENCE_ONLY (field ideas only; code obsolete, no license) | 5 |
| machina-sports/sports-skills | 74a5da7c6c88 | MIT (`LICENSE`; data terms vary per source) | REIMPLEMENT_IDEA | LATER (replay-integrity pattern) | 26 |
| suislanchez/polymarket-kalshi-weather-bot | e406394d59c2 | NONE (no file; README badge claims MIT) | LICENSE_REVIEW_REQUIRED (ideas only) | REFERENCE_ONLY (cautionary) | 12 |
| rodlaf/KalshiMarketMaker | af660af885d2 | MIT (`LICENSE.md`) | REIMPLEMENT_IDEA | LATER (cleanup/kill-switch ideas only) | 21 |

Score order: PROJECT_FIT, SHARED_FOUNDATION, MATURITY_TESTS, MAINTENANCE, SECURITY, LICENSE_EASE, INTEGRATION_EFFORT (5 = easy), UNIQUE_VALUE, OCT22_IMPACT.

---

## 1. betcode-org/flumine

- URL: https://github.com/betcode-org/flumine — SHA 54854495b45accae614b23d10859047d582c3ecf. Default branch `master`. Not archived. Python.
- Size: 10.2 MB. Last push 2026-09-07 (release 3.2.2 merge). 1,870 commits. 246 stars.
- Maintainer: `betcode-org` organisation (Liam Pauling). A long-running Betfair community framework. Credible.
- CI: `.github/workflows/test.yml` runs black, `unittest` on Python 3.10–3.14 and coverage. The deploy job publishes to PyPI on master.
- Tests: 31 files, about 1,042 `def test_` functions (`tests/`). They are mostly unit tests with mocks, plus `test_integration.py` against recorded files in `tests/resources`.
- Docs: good (`docs/*.md`, mkdocs). `docs/quickstart.md:250-260` lists the simulation limitations honestly.
- Releases: versioned via `flumine/__version__.py` and `HISTORY.rst`. Published on PyPI. No GitHub releases.
- Runtime deps (7): betfairlightweight==2.24.0, tenacity, python-json-logger, requests, betconnect==0.3.0, smart-open, betdaq-retail. Mismatch: `pyproject.toml` pins betdaq-retail==0.2.0 but `requirements.txt` pins 0.3.0.
- Security-sensitive behaviour:
  - Real order placement via `execution/betfairexecution.py` and `execution/betdaqexecution.py` (thread pool, `execution/baseexecution.py:22`).
  - `Transaction.place_order(..., force=True)` bypasses every trading and client control (`execution/transaction.py:67-75`).
  - Global monkey-patch of `datetime.datetime` during simulation (`simulation/utils.py:35-42`).
  - The client `info` dict, which contains the `betting_client` object, is logged at INFO (`clients/baseclient.py:128-142`, `clients/clients.py:188`). What that logs depends on the client's repr. For betfairlightweight I did not see secrets in the repr (UNVERIFIED for betconnect).
  - No `eval`/`exec`/`subprocess`/`pickle` in `flumine/`.
- Credential handling: delegated to betfairlightweight/betconnect clients. None stored by flumine.
- Network: Betfair, BETDAQ and BetConnect APIs via the client libraries. `examples/strategies/marketrecorder.py` uploads to S3 (boto3), as an example only.
- Telemetry: none found.
- License: MIT, `LICENSE` ("Copyright (c) 2026, Liam Pauling"). Compatible.
- Known limitations (from the docs): no queue-cancellation model, active liquidity is double counted, no currency fluctuation, no dead heats in PLACE markets (`docs/known_issues.md`). `commission_base` is "not implemented" (`clients/baseclient.py:45`).
- README vs code: claims are modest and match the code. The `VenueType` enum lists POLYMARKET, KALSHI, SMARKETS, MATCHBOOK and BETDEX (`clients/clients.py:152-161`), but only Betfair, BETDAQ, BetConnect and Simulated clients exist. There is no Kalshi or Polymarket support.
- Key files: `flumine.py`, `baseflumine.py`, `simulation/simulation.py`, `simulation/simulatedorder.py`, `markets/middleware.py`, `controls/tradingcontrols.py`, `controls/clientcontrols.py`, `execution/transaction.py`, `order/order.py`, `order/process.py`, `markets/blotter.py`, `strategy/strategy.py`.
- Learn: see Q1 below. Main items: the ordered control chain with a terminal VIOLATION status, exposure checks that count pending orders, a deterministic `customer_order_ref` for reconciliation, and the same strategy code path in live and simulated runs.
- Must NOT import: Betfair back/lay semantics, ladders, BSP, bet delay, the traded-volume halving, `force=True`, datetime monkey-patching, and float money. See Q1.
- Overlap: `fill_policy.py` (simulated fills), `risk.py`/`sizing.py` (exposure caps), `shadow_ledger.py` (order/trade state), planned `execution_ticket.py` and `venues.py`.
- Shared primitive it could unlock: a venue-neutral **pre-trade control chain** (`Control.validate(ticket) -> None | Violation(code, msg)`) and an **order state machine with explicit transitions**.
- Scores: FIT 3, SHARED 4, MATURITY 4, MAINT 5, SECURITY 4, LICENSE 5, INTEGRATION 1, UNIQUE 4, OCT22 2 = **32**.
- Reuse class: REIMPLEMENT_IDEA. Action: **APPLY_NOW (ideas only).** The control and violation taxonomy is cheap to fold into the `execution_ticket.py` data contract now. No code or dependency.

## 2. betcode-org/betfair (betfairlightweight)

- URL: https://github.com/betcode-org/betfair — SHA b00072113e9a1017d5b9cc705e9d1d3444a91036. Default branch `master`. Not archived. Python.
- Size: 2.4 MB. Last push 2026-09-04 (release 2.24.0). 1,241 commits. 513 stars. Organisation-maintained.
- CI: `.github/workflows/test.yml` present. Tests: about 397 `def test_` across 36 files, with 60 JSON fixtures in `tests/resources`, including historical stream files.
- Docs: mkdocs `docs/`. Releases via `HISTORY.rst` and PyPI (the GitHub releases page is stale: latest 1.6.0 from 2018).
- Runtime deps: `requests<2.35.0` (1). Optional speed extras: ciso8601, orjson.
- Security-sensitive behaviour:
  - `streaming/betfairstream.py:300-301` logs every outgoing stream message at DEBUG with `repr(message_dumped)`. The authentication message (`:80-93`) contains `appKey` and `session`, so **DEBUG logging leaks the session token and app key.**
  - Credentials come from arguments or environment variables named after the username (`baseclient.py:108-130`). Certificates are read from the `/certs` directory by default (`:153-175`).
  - No eval/exec/subprocess in the library. `pickle` appears only in tests (`tests/test_exceptions.py`).
- Network: Betfair identity SSO, betting and stream endpoints (TLS socket). No telemetry.
- License: MIT, `LICENSE`. Compatible.
- README vs code: consistent.
- Key files: `streaming/cache.py` (Available, RunnerBookCache, MarketBookCache), `streaming/stream.py` (MarketStream `_process`, `on_update`, `clear_stale_cache`), `streaming/listener.py` (`on_data`, change types), `streaming/betfairstream.py` (`HistoricalStream`, `HistoricalGeneratorStream`).
- Learn: see Q2.
- Must NOT import: the library itself (runtime dependency, Betfair-only). Also not the float prices or the silent JSON-drop behaviour.
- Overlap: `kalshi_quotes.py` (book → executable quotes), `storage.py`/`provenance.py` (raw capture).
- Shared primitive: a pure, venue-neutral `BookState` reducer (`snapshot + deltas → state`, with sequence and gap → INVALID).
- Scores: FIT 2, SHARED 3, MATURITY 4, MAINT 5, SECURITY 3, LICENSE 5, INTEGRATION 1, UNIQUE 3, OCT22 1 = **27**.
- Reuse class: REIMPLEMENT_IDEA. Action: **LATER.** Use it when we build any streaming or delta book, for example a Polymarket US WebSocket adapter.

## 3. the-odds-api/samples-python

- URL: https://github.com/the-odds-api/samples-python — SHA dc344b7e93b70003d0fef35584c8edd78a4c40fb. Default branch `master`. Not archived.
- Size: 18 KB. Last commit 2025-06-16 (requests bump). 22 commits. 106 stars.
- Maintainer: a user account named "The Odds API" (vendor, but a user rather than an org).
- CI: none. Tests: none. Docs: README only. Releases: none. Deps: requests==2.32.4.
- License: **no LICENSE file.** `gh api .../license` returns 404, so no code reuse is allowed.
- Files: `odds.py`, `event_odds.py`, `historical_odds.py`, `historical_event_odds.py`, `utilities.py`, `most_balanced.py`, `Dockerfile`.
- Endpoints demonstrated:
  - `/v4/sports`
  - `/v4/sports/{sport}/odds`
  - `/v4/sports/{sport}/events`
  - `/v4/sports/{sport}/events/{id}/odds`
  - `/v4/historical/sports/{sport}/odds`
  - `/v4/historical/sports/{sport}/events/{id}/odds`
  - Params: `regions`, `markets`, `oddsFormat`, `dateFormat`, `date`.
  - Historical responses carry `timestamp`, `previous_timestamp` and `next_timestamp` (`historical_odds.py:80-82`).
  - Quota cost comments: live = markets × regions (`odds.py:64`). Historical = 10 × markets × regions (`historical_odds.py:59`).
- Security:
  - The API key is sent as a query parameter named `api_key` in every sample (e.g. `odds.py:47-49,69-75`). The vendor docs use `apiKey`. Which spelling is canonical is UNVERIFIED.
  - Either way the key is in the URL, so it leaks into any logged URL or exception.
  - The samples print `response.text` on failure. They do not print the URL.
- Bugs found:
  - `event_odds.py:74` calls `json.dumps` without `import json`, so the sample raises NameError on the success path.
  - Quota headers are read with `[]` (`odds.py:86-87`), which raises KeyError if a header is absent. `x-requests-last` is never read.
  - `utilities.py:4-12`: `american_to_decimal(0)` returns 1.0, and values in (−100, +100) are accepted silently (−50 returns 3.0). +100 and −100 both give 2.0, which is correct.
  - `utilities.py:14-17`: `decimal_to_american(1)` returns the sentinel 0.
  - `utilities.py:44`: `min()` over an empty dict raises ValueError.
  - `most_balanced.py:41,55`: `[0]` indexes before the `if not` check, so that check is dead and IndexError is raised first.
- Scores: FIT 3, SHARED 2, MATURITY 0, MAINT 2, SECURITY 3, LICENSE 0, INTEGRATION 4, UNIQUE 2, OCT22 2 = **18**.
- Reuse class: REFERENCE_ONLY. Action: **NEXT.** Use it as an endpoint, parameter and header reference when writing #29 fixtures. Write our own code.

## 4. carterlasalle/SportsArbFinder

- URL: https://github.com/carterlasalle/SportsArbFinder — SHA b8b6f2a3f31c5cb46a89dc66baf35b38bb3a026f. Branch `main`. Not archived.
- Size: 147 KB. Last commit 2024-10-29. 25 commits. 16 stars. Individual maintainer.
- CI: none. Tests: none. Releases: none.
- Deps (4): requests, python-dotenv, streamlit, protobuf.
- License: MIT, `LICENSE`.
- Security:
  - `viewer.py:201-203` starts `HTTPServer(('', 8000), SimpleHTTPRequestHandler)`. That binds **all interfaces** and serves the whole working directory, which is where the README tells users to put `.env` containing `ODDS_API_KEY`. The key is readable from the LAN.
  - `odds_api.py:77,79` prints `requests` exceptions. `HTTPError` and `ConnectionError` messages include the full URL with the `api_key` query parameter, so **the key leaks to stdout.**
  - `easy_run.py:1-50` uses `subprocess` to run the repo's own scripts (low risk).
  - `arbitrage_finder.py:16` writes a log file to the working directory.
- Math bugs (details in Q3):
  - Spreads are paired on the same signed point (`arbitrage_finder.py:206-246`).
  - No outcome-set completeness check for h2h (`:133-145`).
  - Rounding can zero the last leg (`:379-385`).
  - Everything is float.
  - Staleness is ignored: bookmaker `last_update` is never read and in-play events are included.
- README vs code: the README claims to "guarantee a profit". The code has no fees, limits, staleness checks or correct spread pairing.
- Scores: FIT 1, SHARED 1, MATURITY 0, MAINT 1, SECURITY 1, LICENSE 5, INTEGRATION 3, UNIQUE 1, OCT22 0 = **13**.
- Reuse class: REJECT. Action: **REJECT.** Its bugs make good negative test cases for our own consensus and arbitrage code.

## 5. robbiehaynes/arbitrage-finder

- URL: https://github.com/robbiehaynes/arbitrage-finder — SHA 87fac7f22a59d8ce4c5c8af5dd906fa3274a4827. Branch `main`.
- Size: 42 KB. Last commit 2024-05-12. 20 commits. 23 stars. Individual.
- CI: none. Tests: none.
- Deps: requests, python-dotenv, colorama (no requirements file; taken from imports).
- License: BSD-3-Clause, `LICENSE` (attribution required).
- Security and network:
  - It posts results to a hardcoded author domain, `https://arbfiner.uk.auth0.com/oauth/token`, using CLIENT_ID and CLIENT_SECRET from env (`lib/networkhandler.py:73-93`).
  - It then posts to `API_ENDPOINT` (`:95-110`) and to a Discord webhook (`:112-209`).
  - The key goes in the query string (`:32-38`).
  - Non-venue hardcoded URL: `arbfiner.uk.auth0.com`.
- Bugs:
  - A missing draw becomes 0 and the market is treated as 2-way (`lib/arbmath.py:20,28,46-52`).
  - `cricket` is in the no-draw sports list (`lib/betting_odds_database.py:111`), but test cricket has draws.
  - `roi = 100 - combined_margin` (`arbmath.py:43,50,68`). The correct value is `100/margin − 1`.
  - The totals `under_stake` uses `over_stake` (`arbmath.py:198`).
  - The lay logic uses an `implied < 97` heuristic, and profit ignores the lay-wins branch and commission (`arbmath.py:107-129`).
  - The best lay price is taken as the maximum; for a layer it should be the minimum (`betting_odds_database.py:142`).
  - A naive `strptime(...).timestamp()` interprets UTC as local time (`betting_odds_database.py:154`).
  - `fetchFromAPI` raises UnboundLocalError on non-200 (`networkhandler.py:52`).
- Scores: FIT 1, SHARED 1, MATURITY 0, MAINT 1, SECURITY 2, LICENSE 4, INTEGRATION 3, UNIQUE 1, OCT22 0 = **13**.
- Reuse class: REJECT. Action: **REJECT.**

## 6. timsonater/action-network-scraper

- URL: https://github.com/timsonater/action-network-scraper — SHA 6607b1f2bf592276f445bda1a331b164ac0f9720. Branch `master`.
- Size: 19 KB. Last commit 2018-08-05. 10 commits. 3 stars. Individual (Matt Thimsen).
- CI: none. Tests: none. Docs: a 4-line README, which itself warns of possible ToS violation.
- Deps: selenium 3.11, geckodriver 0.21, Firefox 61, mysql-connector.
- License: **no LICENSE file.** Do not copy code.
- Security:
  - **SQL injection**: UPDATE and DELETE are built with `%`-string formatting from scraped text (`sql_odds_sync.py:30-58` and the per-league copies; `row_update=(update % (...))` near `:81`, `delete % (...)` near `:107`). The INSERTs use parameters.
  - Blank DB credentials are hardcoded as placeholders (`controller.py:35-37`, `table_init/*.py:14-16`).
  - The setup script downloads geckodriver via `wget` and installs with `sudo pip` (`scrapeServSetup.sh`).
- Behaviour:
  - It scrapes the public `https://www.actionnetwork.com/mlb/live-odds` page (`controller.py:90`). It has no login and no PRO data.
  - It runs an unattended random 15–32 s polling loop (`controller.py:82-103`).
  - It overwrites MySQL rows in place (UPDATE/DELETE/TRUNCATE), so no history is kept.
- Scores: FIT 2, SHARED 1, MATURITY 0, MAINT 0, SECURITY 1, LICENSE 0, INTEGRATION 0, UNIQUE 1, OCT22 0 = **5**.
- Reuse class: REFERENCE_ONLY. Action: **REFERENCE_ONLY.** Field ideas only. See Q4.

## 7. machina-sports/sports-skills

- URL: https://github.com/machina-sports/sports-skills — SHA 74a5da7c6c884dfbd9d900aa7f674cd2d9e70dc2. Branch `main`.
- Size: 7.2 MB. Last push 2026-09-23. 317 commits. 234 stars. Organisation (Machina Sports, a commercial data vendor).
- CI: `ci.yml` (ruff, then pytest on 3.9–3.14, with actions pinned by SHA), plus `publish.yml` and `build-site.yml`.
- Tests: 47 files, about 1,328 `def test_`, with fixtures. Releases: v0.33.0 on 2026-08-17 (tagged, PyPI).
- Runtime deps: `feedparser` (1). Optional extras: fastf1, pandas, nflreadpy, pyarrow, py-clob-client-v2.
- License: MIT, `LICENSE`. **Data is not licensed.** README: "Personal use only… Data comes from third-party public sources and is subject to their respective terms of use."
- Security-sensitive behaviour:
  - `polymarket/_cli.py:100-130` reads `POLYMARKET_PRIVATE_KEY` and a funder address, builds an authenticated `ClobClient`, and exposes `create_order` and cancel ("polymarket-trading" skill). This is **wallet-backed order placement.**
  - `_premium.py:140-145` and `cli.py:965-980` run `pip install machina-cli` via `subprocess` when `--install` is passed.
  - The `curl … install.sh` string at `_premium.py:12` is advice text only; it is not executed.
  - Responses carry upsell "upgrade" hints (`_premium.py`), which can be disabled with `SPORTS_SKILLS_NO_UPGRADE_HINTS`.
  - `base64` appears only in the replay body encoding (`_replay.py:109-115`).
- Network: ESPN undocumented site and core APIs, stats.nba.com, cdn.nba.com, statsapi.mlb.com, api-web.nhle.com, NCAA, Understat, Transfermarkt, FPL, ClubElo, football-data.co.uk, TheSportsDB, OpenDota, Leaguepedia, cricsheet, Google News RSS, Kalshi public API, Polymarket gamma and CLOB, ProphetX (collected by grepping `src/**/*.py`). No telemetry call in the package. Doc links carry a `ref` tag only when opened.
- README vs code:
  - "Zero API keys" holds for read-only use. The trading skill needs a private key.
  - `kalshi/_connector.py:964-967` derives "implied" esports odds from last price, **falling back to the bid/ask midpoint**. This is a presentation value, not executable.
  - The betting calcs say "guaranteed ROI" (`betting/_calcs.py:504`) and "recommendation: bet" (`:273`) with no fees.
- Key files: `_replay.py`, `betting/_calcs.py` (American-band validation at `:41-59`), `skills/*/SKILL.md`, `skills/catalog.json`, `kalshi/_connector.py` (`_price_cents` handles Kalshi's move from integer cents to `*_dollars` strings, `:706-727`).
- Learn: see Q6.
- Must NOT import: the polymarket-trading skill, the premium or pip-install handoff, the midpoint fallback, the no-fee "bet" recommendations, and unofficial data sources as provenance-grade inputs.
- Overlap: `http.py`/`storage.py` (fetch and replay), `fees.py` (missing there), `opportunity.py`.
- Shared primitive: a record/replay HTTP fixture layer with sha256 integrity (test infrastructure only).
- Scores: FIT 2, SHARED 3, MATURITY 4, MAINT 5, SECURITY 3, LICENSE 4, INTEGRATION 2, UNIQUE 2, OCT22 1 = **26**.
- Reuse class: REIMPLEMENT_IDEA. Action: **LATER.**

## 8. suislanchez/polymarket-kalshi-weather-bot

- URL: https://github.com/suislanchez/polymarket-kalshi-weather-bot — SHA e406394d59c208cc035c4fdf37ebb26636e15a47. Branch `main`.
- Size: 1.06 MB. Last commit 2026-03-01. 33 commits. 761 stars, 184 forks, 71 open issues. Individual. Stars are not quality evidence.
- CI: none. Tests: **none.** Docs: README, ARCHITECTURE.md, RESEARCH.md, VALIDATED_RESEARCH.md.
- Deps (about 17 Python): fastapi, uvicorn, sqlalchemy, psycopg2, pydantic, httpx, aiohttp, cryptography, numpy, pandas, scipy, apscheduler, anthropic, groq, structlog, dotenv, orjson. Plus a React/Vite frontend with no install hooks (`frontend/package.json` scripts are dev/build/preview only).
- License: **no LICENSE file.** The README badge and "## License: MIT" (`README.md:5,263-265`) do not match the repo. Per the briefing, that means no code reuse.
- Security:
  - FastAPI binds `0.0.0.0` with `allow_origins=["*"]` (`backend/api/main.py:28-31,1047`; `run.py:12-17`).
  - **Unauthenticated destructive endpoints**: `POST /api/bot/reset` deletes all trades and AI logs (`api/main.py:819-835`), and start/stop are also unauthenticated.
  - The Kalshi RSA key is loaded from a path (`backend/data/kalshi_client.py:26-37`). It is used for **read-only** GETs (markets, balance). I found no `/portfolio/orders` or order-placement code, so the bot is paper-only at this SHA.
  - `backend/ai/claude.py` and `groq.py` exist but nothing imports them (dead code; they would be paid services).
- Bugs and red flags: see Q5.
- Scores: FIT 3, SHARED 1, MATURITY 0, MAINT 1, SECURITY 2, LICENSE 0, INTEGRATION 1, UNIQUE 2, OCT22 2 = **12**.
- Reuse class: LICENSE_REVIEW_REQUIRED (treat as ideas only). Action: **REFERENCE_ONLY**, as a cautionary adversarial comparison for EXP-001.

## 9. rodlaf/KalshiMarketMaker

- URL: https://github.com/rodlaf/KalshiMarketMaker — SHA af660af885d20c089c37901e1110c38dc4c12e01. Branch `main`.
- Size: 83 KB. Last commit 2026-04-14. 31 commits. 401 stars. Individual, with outside PRs (Copilot, Bobtron).
- CI: none. Tests: 27 in `tests/test_avellaneda.py` (quote math, scoring, MVE filter). None cover the API, cleanup or liquidation.
- Deps (4): requests==2.26.0, python-dotenv, PyYAML, cryptography.
- License: MIT, `LICENSE.md`.
- Security-sensitive behaviour:
  - **Places real limit orders**: `POST /portfolio/orders` (`core/kalshi_api.py:164-193`), `DELETE /portfolio/orders/{id}` (`:230-233`).
  - The liquidation CLI crosses the spread (`cli/cancel_all.py:131-210`).
  - Unattended deploy to fly.io (`fly.toml`, `Dockerfile`).
  - `Dockerfile` does `COPY . /app`, and neither `.dockerignore` nor `.gitignore` excludes `*.key`/`*.pem`. A private key placed in the repo directory would be committed or baked into the image.
- Bugs: see Q5.
  - `int(price * 100)` truncation (`core/kalshi_api.py:183`): 0.29 → 28, 0.57 → 56.
  - The global cap ignores resting orders in other markets (`core/avellaneda.py:129-140`).
  - Cleanup verification does not paginate (`runtime/cleanup.py:47`).
- README vs code: README config (`k: 1.5`, `sigma: 0.001`) differs from `config.yaml` (`k: 150.0`, `sigma: 0.10`). No profit claims.
- Scores: FIT 2, SHARED 2, MATURITY 2, MAINT 3, SECURITY 2, LICENSE 5, INTEGRATION 2, UNIQUE 2, OCT22 1 = **21**.
- Reuse class: REIMPLEMENT_IDEA. Action: **LATER.** The stop → cancel → verify invariant and a dry-run, scoped cancel-all are worth recording for a future kill switch.

---

# Cluster questions

## Q1. Flumine architecture and what to take

### Event loop

There is a **single FIFO `queue.Queue`** (`baseflumine.py:49-50`), consumed by one main thread (`flumine.py:23-66`). It dispatches MARKET_BOOK, CURRENT_ORDERS, CUSTOM_EVENT, SPORTS_DATA, RAW_DATA, MARKET_CATALOGUE, CLEARED_*, CLOSE_MARKET and TERMINATOR.

Producers run on other threads:
- Streams are `threading.Thread` (`streams/basestream.py:25-45`).
- `BackgroundWorker` threads handle keep-alive, catalogue polling, balance and market closure (`worker.py:16`, `flumine.py:68-113`).
- Order execution runs in a `ThreadPoolExecutor(max_workers=32)` (`execution/baseexecution.py:19-22`, `config.py:16`).

Simulation replaces the queue with a list and runs single-threaded, muxing streams by publish time (`simulation/simulation.py:24-104`).

### Client abstraction and multi-venue design

- `BaseClient` (`clients/baseclient.py:11-142`) holds per-venue limits (transaction_limit, min bet, paper_trade, simulated_full_match) and picks the execution class by `VENUE` (`:79-88`).
- `Clients` indexes clients by `(VenueType, username)` (`clients/clients.py:164-242`).
- Implemented clients: `BetfairClient`, `SimulatedClient` (`clients/simulatedclient.py`), `BetConnectClient` (`clients/betconnectclient.py`) and `BetdaqClient`.
- Multi-venue support is shallow. `_process_market_books` branches on `event.venue` with `raise NotImplementedError()` for anything else (`baseflumine.py:161-170,264-269`). Controls also branch by venue (`controls/tradingcontrols.py:21-25`).
- Lesson: the capability registry idea is sound, but venue branching inside core logic does not scale. Our `venues.py` should put venue differences in data (capabilities, tick grid, fee schedule id, min size) rather than `if venue ==` branches.

### Strategy abstraction

`BaseStrategy` (`strategy/strategy.py:14-248`) has these hooks: `add`, `start`, `process_new_market`, `process_market_catalogue`, `check_market_book` → `process_market_book` (the second runs only if the first returns True; `baseflumine.py:213-218`), `process_orders`, `process_closed_market` and `finish`.

Per-runner `RunnerContext` tracks trades and live trades (`strategy/runnercontext.py`). Exposure limits live on the strategy (`:31-36`). The hook design is clean and venue-neutral in shape, but typed to Betfair `MarketBook`.

### Simulation/live symmetry and simulated matching

The same strategy hooks run in both modes. `SimulatedMiddleware` runs on every book update (`markets/middleware.py:37-79`). Simulated order packages wait in `handler_queue` until `elapsed > simulated_latency`, and are only then evaluated against the **next** book for that market (`simulation/simulation.py:153-196`). That is look-ahead-safe.

Latency constants: place 0.120 s, cancel 0.170 s, update 0.150 s, replace 0.280 s (`config.py:20-24`). Betfair `betDelay` is added for place and replace (`order/orderpackage.py:75-96`).

`SimulatedOrder.place` (`simulation/simulatedorder.py:64-267`):
- Market must be OPEN. A market version mismatch lapses the order (`:77-88`).
- An aggressive order before bet delay completes returns `DELAY` and waits (`:145-149, 196-199`).
- An aggressive order walks displayed depth at the book prices, with price improvement (`_process_price_matched`, `:362-382`). FILL_OR_KILL uses a VWAP walk (`:384-420`).
- **A missing best price is replaced with 1.01 or 1000** (`:146, :196`). That is missing data coerced to a value.
- Passive orders: queue position (`_piq`) = the displayed size at that price at placement (`:246-250`).

Traded-volume deltas at or through the order price reduce PIQ by **half** the traded size, because Betfair counts both sides. Matches occur after PIQ is exhausted (`_process_traded` and `_calculate_process_traded`, `:471-511`, `/2` at `:493`).

Limitations the docs admit: no queue cancellations, liquidity double counted unless strategy isolation (`middleware.py:183-218`, `config.simulated_strategy_isolation`), and `simulation_available_prices=True` double counts (`docs/advanced.md:129-133`). The book is not depleted by our own earlier fills across updates.

`simulated_full_match` fills 100% on success (`simulatedorder.py:276-281`), which is an invented fill if used.

Comparison with `fill_policy.py latency-confirmed-v1`: ours is stricter. It is taker-only, all-or-nothing, and requires a confirmation quote. Flumine's PIQ model is the most credible open reference for a future maker-simulation ADR. It should not be adopted now, because its fill inputs (traded-volume ladder) do not exist on Kalshi's public book.

### Controls and risk

Default trading controls run in order: `OrderValidation`, `MarketValidation`, `StrategyExposure` (`baseflumine.py:74-78`). The client control is `MaxTransactionCount` (`:97`).

- A violation raises `ControlError` after setting the order's terminal `VIOLATION` status with a message (`controls/__init__.py:21-29`, `order/order.py:150-153`).
- `OrderValidation`: size not None, > 0, ≤ 2 dp; price not None and on the ladder via Decimal (`utils.as_dec(price) in PRICES`); min size/payout; liability checks (`controls/tradingcontrols.py:13-141`).
- `MarketValidation`: market known, book present, status OPEN (`:144-163`).
- `ExecutionValidation` (optional): blocks cancel/replace/update after `execution_retry_attempts` failures while the order stream is down (`:166-215`).
- `StrategyExposure`: `strategy.validate_order` enforces max_trade_count, max_live_trade_count and the reset/place-reset cooldowns (`strategy/strategy.py:142-192`). It then checks per-order exposure, per-selection worst-case exposure including pending, executable and complete orders, and per-market exposure. REPLACE excludes the order being replaced (`tradingcontrols.py:218-333`, `markets/blotter.py:192-307`).
- `MaxTransactionCount`: hourly count including failed transactions (`controls/clientcontrols.py:42-146`). Weak point: counts are added **after** execution and the check is `<=` (`:68-79, 121`), so concurrent submissions can overshoot.
- Duplicate guard: `OrderError("Order ... has already been placed")` if the id is already in the blotter (`execution/transaction.py:86-94`).
- Reconciliation: `customer_order_ref = strategy_name_hash + sep + order_id` (`order/order.py:291-292`). Venue orders not in the blotter are rebuilt from it (`order/process.py:33-60, create_order_from_current`).
- Bypass: `force=True` skips all controls (`transaction.py:67-75`).

### Order lifecycle

`OrderStatus` has PENDING, CANCELLING, UPDATING and REPLACING (live), EXECUTABLE, and EXECUTION_COMPLETE, EXPIRED and VIOLATION (complete) (`order/order.py:36-60`). `_update_status` accepts **any** transition with no guard (`:119-127`). It appends to `status_log` and timestamps with wall clock.

### Market recording

`examples/strategies/marketrecorder.py:63-73` appends raw stream lines `{"op":"mcm","clk","pt","mc":[data]}` per market. It gzips on close and optionally uploads to S3. The replay path (`BetfairHistoricalStream`) feeds these lines through the same listener. That raw-first design matches our immutable-evidence rule.

### Patterns that would strengthen Market Edge (ideas only)

1. An ordered, pluggable pre-trade **control chain** with first-violation-wins, a terminal VIOLATION state and a machine-readable reason. This maps directly onto `opportunity.evaluate()` rejection reasons and the planned `execution_ticket.py`.
2. Exposure checks that count **pending + resting + filled**, and exclude the replaced order on amend.
3. A deterministic client order reference (strategy id + ticket id) that allows restart reconciliation of orphaned venue orders.
4. Latency-gated simulated execution evaluated only against the next observed book. Our confirmation-quote policy already does this more strictly.
5. Raw-message recording plus one parser path for live and replay.
6. Per-client hourly transaction budget that counts failures.

### Betfair-specific assumptions NOT to import blindly

- BACK/LAY sides and lay liability `(price−1)×size` (`tradingcontrols.py:258-263`). Kalshi and Polymarket are YES/NO binary contracts priced 0–1.
- The decimal odds ladder (1.01–1000, CLASSIC/FINEST/LINE_RANGE ladders), 2 dp stakes and GBP currency minimums.
- Commission on net market winnings. `commission_base` is unimplemented, so flumine's simulated PnL is **gross**. Kalshi uses a per-contract quadratic fee (our `fee_schedules.py`).
- BSP / LIMIT_ON_CLOSE / MARKET_ON_CLOSE, `bsp_reconciled` and SP matching (`simulatedorder.py:422-469`).
- In-play `betDelay` and PASSIVE delay models, and market `version` lapse.
- Traded-volume halving (`/2`), which is Betfair's double-sided counting.
- Runner removal adjustment and reduction factors, dead heats and each-way (horse racing).
- Persistence types LAPSE/PERSIST/MARKET_ON_CLOSE.
- The 5,000 transactions/hour Betfair charge model.
- Floats for money, `datetime` monkey-patching, and `force=True`.

### Checks to reimplement for a FUTURE execution-ticket boundary (execution stays disabled)

These are a data contract and validator only, stdlib and Decimal. Each maps to a rejection code.

1. `QTY_INVALID`: qty present, integer, > 0, and within the venue lot rules.
2. `PRICE_INVALID` / `PRICE_OFF_TICK`: price is a Decimal in the open interval (0, 1) and on the venue tick grid. Reject floats at the boundary. This prevents the KalshiMarketMaker `int(price*100)` bug.
3. `MARKET_UNKNOWN` / `BOOK_MISSING` / `MARKET_NOT_OPEN`.
4. `BOOK_STALE`: fail closed. Flumine only *warns* at more than 2 s latency (`baseflumine.py:172-183`).
5. `QUOTE_CHANGED`: the ticket pins the book snapshot id or sequence it was priced from. This is the analog of Betfair `market_version` lapse.
6. `ORDER_STATE_CHANNEL_DOWN`: block new risk when order and position reconciliation is stale. This is the analog of `ExecutionValidation`.
7. Exposure limits: `EXPOSURE_PER_ORDER`, `EXPOSURE_PER_CONTRACT` and `EXPOSURE_PER_EVENT`, computed as worst-case loss over pending + resting + filled, plus `GLOBAL_CAP` across **all** markets including resting orders (KalshiMarketMaker misses the resting part).
8. `TRADE_COUNT_LIMIT`, `LIVE_TRADE_LIMIT` and `COOLDOWN_ACTIVE`, with reset and place-reset seconds.
9. `RATE_BUDGET_EXCEEDED`: reserve the budget *before* send and count failures.
10. `DUPLICATE_TICKET`: an idempotency key equal to a deterministic client_order_id, and a reconciliation rule for venue orders unknown locally.
11. `FEE_UNVERIFIED` and `EXECUTION_NOT_AUTHORIZED` (venue capability flag false by default). These already exist or are planned in Market Edge.
12. An explicit **allowed-transition table** for ticket and order state. Illegal transitions are errors, unlike flumine's unguarded `_update_status`.
13. No `force` bypass. An override, if ever added, must be a separate audited record with owner approval.

## Q2. betfairlightweight streaming cache and replay — lessons for a venue-neutral book

- **Image plus delta.** `img: true` or a new market builds a fresh `MarketBookCache`. Otherwise deltas update levels (`streaming/stream.py:175-200`).
- **Level delta encoding.** `[price, size]` (or `[pos, price, size]`). `size == 0` deletes the level (`streaming/cache.py:47-76`). The book is kept as a dict and re-sorted only when a new key appears.
- **Change types.** SUB_IMAGE, RESUB_DELTA, HEARTBEAT and UPDATE (`streaming/listener.py:186-200`). `clk` and `initialClk` are resume tokens (`stream.py:149-155`). Conflation `con` is only warned about (`stream.py:78-81`).
- **Hazards to avoid:**
  - (a) A delta with no prior image silently creates a new cache, because "historic data does not contain img" (`stream.py:182-195`). Live, a delta without a base should make the book UNKNOWN.
  - (b) Malformed JSON is logged and dropped (`listener.py:130-133`). With deltas, a dropped message corrupts state silently. It should invalidate the book.
  - (c) Latency over the limit only warns (`stream.py:71-76`).
  - (d) Full depth, best-display and best-only views are merged by fallback (`cache.py:153-170`), so consumers cannot tell which view they got. Tag the depth source.
  - (e) Prices are floats.
- **Replay symmetry.** `HistoricalStream` and `HistoricalGeneratorStream` push recorded lines through the **same** `listener.on_data` (`betfairstream.py:320-387`). A generator yields snapshots per line. Stale closed caches are purged after 8 h (`stream.py:93-109`).
- **Market Edge design implication.** Build a pure reducer: `apply(BookState|None, Message) -> BookState | BookInvalid(reason)`.
  - Explicit `SNAPSHOT` and `DELTA` message types.
  - Monotonic `sequence`; a gap gives `SEQUENCE_GAP`. A delta without a base gives `NO_BASE_SNAPSHOT`. A parse error gives `MALFORMED`.
  - Decimal levels.
  - Both `venue_ts` and `received_ts` on every state.
  - A `depth_view` tag (FULL / TOP_N / BEST_ONLY).
  - Raw messages are stored immutably (sha256) and state is derived only by replay. This matches `shadow_ledger`/`storage` principles.
  - Freshness uses `received_ts`, and fails closed via `freshness.require_fresh`.

## Q3. Odds tooling

### The Odds API samples

- Quota headers: `x-requests-remaining` and `x-requests-used` are read with `[]` (`odds.py:86-87`, `event_odds.py:77-78`, `historical_odds.py:85-86`). `x-requests-last` is **not used** in any sample. Whether the API returns it is UNVERIFIED from this repo.
- Key: sent as the query parameter `api_key` (every sample, e.g. `odds.py:47-49`). SportsArbFinder (`odds_api.py:21-22,44-45`) and robbiehaynes (`networkhandler.py:32-38`) do the same. It is **in the URL**, so a redaction risk wherever URLs, requests exceptions (`HTTPError` messages include the URL) or proxy logs are recorded. SportsArbFinder prints these exceptions (`odds_api.py:77,79`).
- Endpoints: listed in section 3. Cost comments: markets × regions live, 10× that for historical.

### Math review

- `utilities.py`: American→decimal accepts 0 and the invalid (−100, +100) band silently. `decimal_to_american(1)` returns 0. ±100 is correct.
- sports-skills `betting/_calcs.py`:
  - American band validation is correct (`:41-59`). The probability↔American conversions are correct.
  - The `devig` decimal path lacks a `>1` check, so decimal 0.5 becomes probability 2.0 (`:199-200`).
  - `_prob_to_american` returns the sentinel 0.0 outside (0, 1) (`:77-84`).
  - Everything is float.
  - `find_arbitrage` does not check that outcomes are complete and mutually exclusive, and ignores fees and limits.
- SportsArbFinder:
  - **Spreads are paired on the same signed point** (`arbitrage_finder.py:208-246`). Complementary spread outcomes are (home, −p) and (away, +p). Keying both sides by the same `point` either misses real pairs or pairs "home −1.5" with "away −1.5". Those can both lose, which produces a false arbitrage.
  - h2h uses any two or more outcomes with no completeness check (`:133-145,77`). A 3-way market with the draw missing across books becomes a false arb.
  - The "best" spread is the *last* found under 1, not the minimum (`:258`).
  - Rounding: if the remainder is under half a unit, the last leg is set to **0** and the remainder is spread unrounded (`:379-385`). This destroys the hedge. It then only logs an error (`:413-414`).
  - The profit margin `1/Σ − 1` is correct.
- robbiehaynes: see section 5. Missing draw → 0 → 2-way, cricket draws, wrong ROI formula, under_stake copy bug, wrong lay selection direction, and a local-time timestamp bug.
- Edge cases to test in our implementation:
  - American 0, ±50, ±99.99 → reject. +100 and −100 → 2.0. Very large ±.
  - Decimal ≤ 1.0 → reject.
  - None or missing price → `None`, never 0.
  - Duplicate outcomes. Incomplete outcome set.
  - Mixed timestamps across books. In-play or started events.
  - Spreads and totals pairing on complementary lines.
  - Rounding that breaks equal payout. Recompute worst-case return after rounding.

### What Market Edge should implement (stdlib, Decimal) for #29 and #9

1. `odds.py`: exact Decimal conversions American↔decimal↔implied, with an explicit rejection enum (`AMERICAN_IN_DEAD_BAND`, `DECIMAL_LE_ONE`, `MISSING`). No sentinels. Quantize only at presentation.
2. An Odds API adapter on fixtures:
   - Raw response bytes stored immutably with sha256.
   - A quota ledger capturing `x-requests-remaining/used/last`, with `None` when a header is absent.
   - The key read from env only, and **redacted from every stored or logged URL**, including exception text.
   - `apiKey` versus `api_key` verified against the official docs before first live use (UNVERIFIED).
   - Historical `timestamp/previous_timestamp/next_timestamp` preserved as point-in-time metadata.
   - Per-bookmaker `last_update` kept, with a freshness state per quote.
3. Consensus (#9):
   - Per-book overround, then proportional de-vig **only over a verified complete, mutually exclusive outcome set from one book at one timestamp**.
   - Then cross-book aggregation (median; the book count is recorded).
   - Stale books are excluded under a documented freshness rule. Totals and spreads are paired on complementary lines.
   - Alternative de-vig methods (power, Shin) can come later as options. The method is recorded on the output.
4. Arbitrage detection, if ever wanted, is research-only: Σ 1/d_best < 1 over a complete set, equal-payout stakes `s_i = S·(1/d_i)/Σ`, recomputed worst-case return after rounding, and fee, limit and staleness fields that must be verified. Otherwise it is rejected (`FEE_UNVERIFIED`, `LIMITS_UNKNOWN`).
5. **Never executable.** A de-vigged or consensus probability is a model or reference estimate. It is not a price and must not populate `ExecutableQuote`.
   - Sportsbook odds are also not executable for us: no account, unknown limits, and aggregator latency.
   - Type them as `ReferenceProbability` / `ModelEstimate` with source, method, book count and as-of.
   - The only executable prices remain venue top-of-book asks with verified fees.

## Q4. Action Network scraper (owner reports explicit permission for subscribed PRO data)

- The repo scrapes the **public** live-odds page with no login (`controller.py:90`). It contains nothing about PRO data. Any PRO field list must come from the current PRO UI or API under the owner's permission, which is UNVERIFIED here.
- Fields captured (designing our own schema from these is fine; the code must not be copied):
  - `away_team` and `home_team` as displayed abbreviations.
  - `away_score` and `home_score`.
  - `game_state`: start time text, "Final", or an inferred "In Progress".
  - `home_moneyline` and `away_moneyline`.
  - `home_spread`, `away_spread`, `home_spread_odds`, `away_spread_odds`.
  - `line` (total), `line_over_odds`, `line_under_odds`.
  - These come from the "current" column (the second `text-right` cell) (`master_scraper.py:31-33,103-239`; schema `table_init/make_table_nfl.py:21-41`).
- Schema ideas worth designing independently:
  - Event identity: league, scheduled start (UTC), home and away canonical ids plus the source's display abbreviations, and the source event id if the page or API exposes one.
  - One row per (event, market_type, side, line) observation with price (American, validated) and `book` or `consensus` source.
  - `line_kind` = OPEN / CURRENT / BEST, with both `source_updated_at` (if shown) and `captured_at`.
  - Game status as an enum rather than free text.
  - Scores as nullable ints.
  - PRO-specific fields such as ticket % / money %, projections and sharp indicators, typed as `source_claims` with provenance and never as prices.
  - Permission evidence (who, when, scope) recorded in the repo per `docs/DATA_PROVENANCE.md` and `docs/SECURITY.md`. Logging in to PRO is credential handling and needs owner approval.
- Obsolete or unsafe (do not reproduce):
  - Selenium 3 `find_element_by_xpath` (removed in Selenium 4), `options.set_headless`, `firefox_options=`, geckodriver 0.21.
  - Absolute XPaths and 2018 Bootstrap class-prefix selectors (`master_scraper.py:27,39,114-118,144-155`).
  - Sport mapping by menu click order (`count==1 → ncaab`, `:260-271`).
  - A positional join of game cards to table rows (`:112-139`).
  - A hard-coded STL@CHC "no odds" sentinel (`:180-193`).
  - `'--'` and `''` as missing values.
  - Bare `except`, and `1/0` for control flow (`:84-85`).
  - Overwrite-in-place MySQL with UPDATE/DELETE/TRUNCATE, which loses history.
  - SQL built with `%`-formatting (injection).
  - An unattended random-sleep polling loop (a scheduled or unattended job needs owner approval under our rules).
- Collection workflow lesson: capture raw page or JSON snapshots immutably first, then parse them offline with versioned parsers. Freshness and missing values stay explicit. If a documented JSON endpoint is within the permission scope, prefer it over DOM scraping (UNVERIFIED availability).

## Q5. Weather bot and KalshiMarketMaker compared with Market Edge

### suislanchez/polymarket-kalshi-weather-bot (paper-only at this SHA)

- **Settlement source.**
  - The research docs assert "NWS Daily Climate Report (Central Park)" (`VALIDATED_RESEARCH.md:25,34`, `RESEARCH.md:226,336`).
  - The code's NWS function pulls hourly station observations for KNYC on a **UTC** day window (`backend/data/weather.py:207-251`, with the `+ "Z"` day bounds at `:227-228`). It is **never called**; grep finds only the definition.
  - Actual settlement reads Kalshi `status/result` (`backend/core/settlement.py:202-227`), which is venue-reported and acceptable.
  - However, every trade is stored with `platform="polymarket"` (`backend/core/scheduler.py:133,258`). Kalshi-sourced signals are therefore settled via the Polymarket Gamma lookup and will likely never settle or will settle wrongly.
  - Our captured rules differ from the bot's docs: NWS CLI Central Park through 2026-08-13, then **"The Weather Company", "New York City (CLINYC)"** from 2026-08-15 (`market-edge-lab/docs/SETTLEMENT.md:30-33`). The bot's docs are stale against the current rules.
- **Contract misread.**
  - `_parse_kalshi_ticker` maps `B45.5` to "above 45.5" and `T` to "below" (`backend/data/kalshi_markets.py:36-77`, `:69-70`).
  - Our captured rules say `B80.5` is an **inclusive bracket "80° to 81°"** (`docs/SETTLEMENT.md:66`).
  - So the model probability is computed for the wrong event, and "edges" on bracket markets are artefacts.
- **Model inputs.**
  - The Open-Meteo GFS ensemble is queried at lower-Manhattan coordinates (40.7128, −74.0060), not Central Park (`weather.py:14-21`).
  - No `timezone` parameter is sent (`:147-155`), so daily max/min are aggregated in Open-Meteo's default timezone (documented as GMT; UNVERIFIED for this endpoint). The CLI climate day is local standard time.
  - `date.today()` uses the host clock (`:132-133`).
  - Missing members return probability 0.5 (`:83-84`).
  - The `ensemble_agreement` split at the median is about 0.5 by construction (`:103-111`).
  - Probabilities are clipped to [0.05, 0.95] (`backend/core/weather_signals.py:74`).
- **Prices and fills.**
  - `yes_ask` and `no_ask` are integer cents (Kalshi has moved to `*_dollars` fields per sports-skills `kalshi/_connector.py:706-727`).
  - The fallback is `last_price` or an **invented 50¢**, and `no_price = 1 − yes_price` when missing (`kalshi_markets.py:128-135`).
  - Credentials are required even for public market data (`:89-90`).
  - Paper trades fill instantly at that price with no size check, no confirmation and no fees.
- **PnL is mis-scaled.** `size` is dollars (Kelly × bankroll, `backend/core/signals.py:74-114`), but PnL is `size·(1−p)` on a win and `−size·p` on a loss (`settlement.py:140-149`). A dollar stake at price p should win `size·(1−p)/p` and lose `size`. The `$10` minimum overrides Kelly upward (`scheduler.py:119,245`). The equity curve is not trustworthy.
- **Brier.** Computed over settled signals; a missing settlement is scored as 0.5 (`backend/api/main.py:573-580`). Model probabilities are clipped. There is no reliability-by-bucket test beyond display bins.
- **Dashboard.** Binds 0.0.0.0 with CORS `*` and unauthenticated start/stop/reset. Reset deletes all trades (`api/main.py:28-31,790-835,1047`). Ours is 127.0.0.1 and read-only.
- **Red flags.**
  - README: "100% free", "Professional dashboard".
  - RESEARCH.md quotes third-party "$40M+ arbitrage profits" and Kalshi fees "~1.2% average" (`RESEARCH.md:10,182-185`). That is not Kalshi's quadratic formula.
  - No bot profit claim, but the displayed PnL is wrong as shown above.
- **Security.** RSA key loaded from a path, read-only use. No order endpoint. Claude and Groq modules are not wired in.
- **Use for Market Edge.** An adversarial checklist for EXP-001: bracket semantics, station coordinates, climate-day timezone, invented fallback prices and dollar-vs-contract PnL. Our design already avoids each.

### rodlaf/KalshiMarketMaker (live orders)

- **Lifecycle.**
  - The selector ranks open binary markets by normalised volume and spread (`selection/scoring.py:11-109`). It excludes MVE, functional-strike and non-binary markets (`runtime/workers.py:6-33`).
  - It runs one Avellaneda–Stoikov worker thread per market.
  - Deselect: stop event → wait (15 s) → cancel all resting for that ticker → verify → forget, and it retries next cycle if not clean (`runtime/cleanup.py:59-81`, `runtime/dynamic.py:55-72`). Final shutdown does the same (`dynamic.py:89-93`).
  - `kalshi-cancel-all` supports `--dry-run`, scoping and aggressive multi-round liquidation (`cli/cancel_all.py`).
- **Gaps.**
  - A worker crash (`workers.py:77-80`) or `T` expiry (`core/avellaneda.py:47`) leaves resting orders until deselect.
  - Verification uses a non-paginated `get_orders` (`cleanup.py:47`, `core/kalshi_api.py:235-243`).
  - Pagination caps silently truncate position and order lists (`kalshi_api.py:199-228,258-290`).
- **Risk.**
  - The per-market cap counts pending orders (`avellaneda.py:142-182`).
  - The global cap counts **filled positions only**, not resting orders in other markets (`:129-140`), so aggregate worst case can exceed `max_global_contracts`.
  - It fails closed (capacity 0) if the position snapshot errors (`:138-140`).
  - No fee model, no PnL accounting and no loss limit.
- **Pricing.**
  - Quotes are centred on the **midpoint** of `yes_bid/yes_ask` (`kalshi_api.py:140-152`), using integer-cent fields that are likely deprecated.
  - `int(price*100)` truncates (`:183`), so 0.29 → 28¢ and 0.57 → 56¢.
  - `get_price` is called twice per loop with no staleness check.
- **Idempotency.** POST orders are retried on 429/5xx/timeouts with the same `client_order_id` (`:173-192`, retry loop `:80-125`). This is safe only if Kalshi rejects duplicate `client_order_id`, which is UNVERIFIED.
- **Security.** Real order path. Unattended fly.io deploy. `.gitignore` and `.dockerignore` do not exclude private key files, while `Dockerfile` does `COPY . /app`. Logs print response bodies on failure (`kalshi_api.py:122-124`).
- **Claims.** No profit claims. README config differs from `config.yaml`.
- **Use for Market Edge** (future, execution disabled):
  - The stop → cancel → verify invariant.
  - Dry-run and scoped cancel-all as a kill-switch spec.
  - Fail-closed on a risk-snapshot error.
  - Never: midpoint quoting, float→int price conversion, or global caps that ignore resting orders.

## Q6. machina-sports/sports-skills — useful or not?

- **Data sources.** Mostly undocumented or unofficial endpoints (ESPN site/core, stats.nba.com, NBA CDN), official league APIs (MLB Stats, NHL, NCAA), scraped sites (Understat, Transfermarkt, TFRRS), community datasets (nflverse, cricsheet), plus the Kalshi, Polymarket and ProphetX public APIs.
  - Licensing: the package is MIT, but the README says data is "subject to their respective terms of use" and "personal, non-commercial use". None of these are provenance-grade inputs for us without a per-source ToS review, and none are needed for KXHIGHNY.
- **Agent skill structure.**
  - `skills/<name>/SKILL.md` with YAML frontmatter: `name`, a `description` containing "Use when / Don't use when", `license`, `metadata`.
  - `references/*.md` for detailed commands, and `scripts/` for parameter validation.
  - A machine-readable `skills/catalog.json` (`$schema`, `default_policy`, `skills`, `version`) with risk metadata.
  - A README "Autonomous Agent Contract": read-only by default, never trade without an explicit request, market text is untrusted.
  - This is well organised. Our `AGENT_OPERATING_SYSTEM.md §7` defers skills until a procedure outgrows a doc section, and nothing here changes that.
- **Useful ideas.**
  - (a) `_replay.py`:
    - Record/replay of HTTP responses keyed by a canonical URL.
    - Stored with `body_sha256` and verified on replay.
    - Transient failures (5xx, 429, timeouts) are never recorded, and a replay miss is an error instead of a network call.
    - Atomic writes via temp file and `os.replace`.
    - A good pattern for fixture-driven adapters (#29).
    - Limits: it is keyed by URL only, so not point-in-time. It stores URLs unredacted, which is fine only because it assumes keyless sources.
  - (b) `betting/_calcs.py:41-59`: the American dead-band validation and its error text are a good test oracle.
  - (c) `kalshi/_connector.py:706-727`: a note that Kalshi moved price fields from integer cents to `*_dollars` strings. Our Kalshi parsing should handle both, with Decimal (verify against our current `kalshi.py`).
- **Not useful or harmful.**
  - The polymarket-trading skill (private key, order placement; `polymarket/_cli.py:100-130`).
  - `premium --install` running pip via subprocess (`_premium.py:140-145`, `cli.py:975`).
  - Upsell hints injected into responses.
  - Midpoint and last-price "implied odds" (`kalshi/_connector.py:964-967`).
  - No-fee "bet" recommendations and "guaranteed ROI" (`betting/_calcs.py:273,504`).
- **Verdict.** Useful as reference for replay integrity and validation tests. Do not take it as a dependency or a data source. LATER.
