# Public GitHub reuse audit

**Audit date:** 2026-09-23. **Owner record:** issue #36. **Delivery plan:** #11 (2026-10-22).
**Market Edge baseline:** `main` at `879e770`, rebased onto `9f05c87` (PRs #37, #38 and #39). **Evidence:** `docs/audits/2026-09-23-github-reuse/`.

This is research. It authorizes nothing. `docs/EXECUTION_PLAN.md` alone says what may be
built. No repository reviewed here was installed or executed, and no credential was used.

## 1. Conclusions

1. **No external framework replaces our core.** Every candidate we checked is looser than
   Market Edge on at least one non-negotiable rule. Two of the most common failures:
   - Missing prices become 0.50 or 0: PredictionMarketBench, pmxt, Simmer, dr-manhattan,
     Alphapoly, the weather bot.
   - Mid or last prices are treated as executable: CCXT's Myriad book, Alphapoly,
     KalshiMarketMaker.

   Others invent depth, fill at zero latency, or ignore fees. Our contracts stay the owner.
   We learn patterns and pin them with tests.
2. **CCXT does not change the multi-venue plan.**
   - It covers Kalshi, Polymarket International, Limitless and Myriad, not Polymarket US.
   - It brings 22 runtime dependencies and float prices.
   - It invents data: a synthetic Myriad AMM book with size 9999, and a Polymarket winner
     inferred from price ≥ 0.99.
   - It hard-codes fees.

   Its `has`-style capability map was the one idea worth taking, and `venues.py` (PR #38,
   ADR 0019) already goes further, with a stage per capability and execution never
   authorized. Recommendation: **COPY_ADAPTER_IDEAS**, not a dependency (§7.1).
3. **Polymarket US: write our own stdlib adapter, and use the official SDK as its spec.**
   - `Polymarket/polymarket-us-python` is the only repository for Polymarket US. Every other
     Polymarket repository is International, which must stay separate.
   - The SDK's public calls are one-line GETs that return raw dicts. Its response types
     were wrong until 2026-09-22, and it brings order-placement code.
   - §7.2 has the endpoint and field spec. The coordinator's adapter (`polymarket_us.py`,
     PR #39) was built in parallel and matches it; §7.2 records the cross-check and one
     correction to this audit (the NO side).
4. **Notifications: ntfy is the best free push channel now, and it is not SMS.**
   - It needs no dependency: about 40 lines of `urllib`.
   - Our no-POST invariant must be narrowed deliberately first, and the owner must approve
     the first real send.
   - Apprise waits until three or more channels are authorized (§7.9).
5. **Best execution architecture is a list of anti-patterns, not a framework.**
   - Hummingbot drops an order from tracking when the submit request errors, although the
     venue may have accepted it.
   - Hummingbot and polymarket-us-python have no idempotency key on order submission.
   - LLM-facing MCP servers let the model "confirm" its own trades.

   Flumine's ordered pre-trade control chain is the best positive pattern (§7.3, §7.8).
6. **The audit found and fixed a real defect.** GATE7-F14: the shadow ledger settled each
   market on its own, so an event whose captured brackets disagreed could book several
   winners, or none. It is fixed and tested in this PR
   (`docs/engineering/GATE7_FINDINGS.md`).
7. **One supply-chain threat is confirmed.**
   - `dev-polymarket/clob-client-v2` (512 stars) impersonates Polymarket's official
     `clob-client-v2` (75 stars). Its npm scope is `@polymarkets`, one letter off the
     official `@polymarket`.
   - It ships prebuilt code only, its npm build differs from the repo, and it logs API
     credentials on errors. **Never install it.**
   - Two repositories commit Claude Code settings or hooks that run their own code when the
     clone is opened as a working directory: `guzus/dr-manhattan` (pre-approved shell
     commands) and `chainstacklabs/polymarket-alpha-bot` (hooks). Never open third-party
     clones as a Claude Code project.
8. **Most of the ecosystem cannot legally be copied.** 694 of the 1,209 screened
   repositories (57 %) have no license. So do several official ones: Kalshi's starter code,
   `polymarket-cli`, Polymarket agent-skills, The Odds API samples and PredictionMarketBench.

## 2. Methodology

- **Search:** `gh search repos`, sorted by stars, 30 results per query.
  - 73 queries in 16 families; 58 returned results and 15 returned none.
  - 1,209 distinct repositories were screened; 939 matched domain keywords.
  - Query list: `search_queries.tsv`. Every screened repository, with license and last
    push: `screened_repos.tsv`.
- **Deep review:** 43 repositories, each pinned to its default-branch head on 2026-09-23
  (`deep_review_pins.tsv`). The pool was the owner's seed list and alternates, the
  strongest search results, and the official organization repositories of Polymarket,
  Kalshi and The Odds API.
- **Reviewers:** five read-only reviewers, one per cluster. Each report is in the evidence
  folder:
  - A: multi-venue APIs;
  - B: the Polymarket stack;
  - C: replay and backtesting;
  - D: sports and odds;
  - E: execution, agents and notifications.
- **How repositories were read:**
  - Clones used partial or sparse checkout at the pinned SHA.
  - Every repository got a static grep for keys, wallets, subprocess/eval, install hooks,
    telemetry, obfuscation, order and withdrawal paths, and credential logging.
  - Claims made in a README were checked against code and tests, with file:line citations
    in the reports.
  - The one exception to static reading: the reviewer re-implemented PredictionMarketBench's
    fee formula in their own Python line to check its rounding.

### Search families

| Family | Queries | Repos |
|---|---|---|
| F01 prediction markets | prediction market trading / backtesting / arbitrage; event contracts; forecast market | 129 |
| F02 Kalshi | kalshi; kalshi api python | 31 |
| F03 Polymarket | polymarket; polymarket us; polymarket clob | 87 |
| F04 other venues | novig; prophetx; limitless (×2); myriad markets | 59 |
| F05 sports | sports betting odds; odds api; sports arbitrage; value betting; closing line value; sportsbook scraper | 163 |
| F06 exchanges | betfair; betfairlightweight; betfair bot; betdaq; betfair trading framework | 76 |
| F07 order books | order book replay; limit order book simulator; market making bot; backtest orderbook; orderbook websocket; fill simulation | 95 |
| F08 execution | unified exchange api; trading order management; multi venue trading engine; others | 36 |
| F09 risk / ledger | kelly criterion betting; position accounting; ledger / event sourcing | 39 |
| F10 backtesting | event driven backtesting; walk forward; point in time data; backtesting engine; algorithmic trading platform | 121 |
| F11 calibration | calibration curve; proper scoring rules; probabilistic forecast evaluation; Brier | 63 |
| F12 weather | weather prediction market; weather kalshi; ensemble forecast trading | 33 |
| F13 news / LLM / equivalence | polymarket agent; polymarket arbitrage; kalshi polymarket arbitrage; logical / equivalence queries | 75 |
| F14 notifications | ntfy; notification service; push self hosted; SMS; apprise | 61 |
| F15 dashboards | trading dashboard; market scanner; polymarket dashboard | 90 |
| F16 agents | trading mcp server; ai trading agent; human in the loop; mcp kalshi; mcp polymarket | 77 |

### Scoring

Each deep-reviewed repository is scored 0–5 on nine criteria:
- **FIT:** project fit;
- **SHARED:** shared-foundation leverage;
- **MAT:** maturity and tests;
- **MAINT:** maintenance health;
- **SEC:** security quality;
- **LIC:** license and reuse ease;
- **INT:** integration effort (5 = easy);
- **UNIQ:** unique value;
- **OCT:** impact by 2026-10-22.

The weighted total counts FIT and SHARED twice (maximum 55). The score is a consistent
decision aid, not a measurement: five reviewers scored separate clusters, and cross-cluster
calibration is approximate. Ties break on OCT, then on the raw total.

## 3. Final top 20

Classes, as defined in the directive:
- **Reuse:** DIRECT_REUSE_PERMISSIVE, DEPENDENCY_CANDIDATE, REIMPLEMENT_IDEA, REFERENCE_ONLY,
  LICENSE_REVIEW_REQUIRED, REJECT.
- **Action:** APPLY_NOW, NEXT, LATER, REFERENCE_ONLY, REJECT.

| # | Repository | Reviewed commit | License | Score /55 | FIT SHARED MAT MAINT SEC LIC INT UNIQ OCT | Reuse | Action |
|---|---|---|---|---|---|---|---|
| 1 | Polymarket/polymarket-us-python | `b44e4c8e7d34cb72582faec68d765fda50afca79` | MIT | 44 | 5 3 3 4 4 5 3 4 5 | REIMPLEMENT_IDEA | APPLY_NOW (as adapter spec) |
| 2 | binwiederhier/ntfy | `10cb6506f836dbb00bb77e3b52669f6ace37f555` | Apache-2.0 / GPL-2.0 dual | 44 | 4 3 5 5 3 5 5 4 3 | DEPENDENCY_CANDIDATE (service over HTTP, no code) | NEXT |
| 3 | arshka/pykalshi | `e42d9f3c491c5037cfe51c7f69ad35074d097255` | MIT | 39 | 4 3 4 4 3 5 2 4 3 | REIMPLEMENT_IDEA | APPLY_NOW (ideas) |
| 4 | betcode-org/flumine | `54854495b45accae614b23d10859047d582c3ecf` | MIT | 39 | 3 4 4 5 4 5 1 4 2 | REIMPLEMENT_IDEA | APPLY_NOW (ideas) |
| 5 | hummingbot/hummingbot (core) | `9af100d6822da7d2d0291a906c730ef172284ee2` | Apache-2.0 | 34 | 3 3 4 5 3 4 1 4 1 | REIMPLEMENT_IDEA | LATER |
| 6 | Polymarket/py-sdk | `1f5ca055d31a29a4fa0ad7955ee4a8bf8aaab3e6` | MIT | 33 | 2 3 5 5 3 5 1 3 1 | REFERENCE_ONLY | LATER |
| 7 | Jon-Becker/prediction-market-analysis | `7fbbb1ebefedf20ce8dda7fe4ee6ecb05e80e9d8` | MIT | 32 | 3 2 2 4 3 5 3 3 2 | REIMPLEMENT_IDEA | LATER |
| 8 | caronc/apprise | `2e72688d0526614980316b483c36d525441b9a4b` | BSD-2-Clause | 32 | 2 2 5 5 3 5 3 2 1 | DEPENDENCY_CANDIDATE (optional, deferred) | LATER |
| 9 | betcode-org/betfair | `b00072113e9a1017d5b9cc705e9d1d3444a91036` | MIT | 32 | 2 3 4 5 3 5 1 3 1 | REIMPLEMENT_IDEA | LATER |
| 10 | ccxt/ccxt | `10ad2b51b9bf5d8c01c706755b0b0ec18a0cb693` | MIT | 31 | 2 3 3 5 3 5 1 3 1 | REIMPLEMENT_IDEA | REFERENCE_ONLY |
| 11 | machina-sports/sports-skills | `74a5da7c6c884dfbd9d900aa7f674cd2d9e70dc2` | MIT (code; data terms vary) | 31 | 2 3 4 5 3 4 2 2 1 | REIMPLEMENT_IDEA | LATER |
| 12 | nautechsystems/nautilus_trader | `3adf5a8dc0c9e676eb1e131911a73ad693ea7b42` | LGPL-3.0 | 31 | 2 3 5 5 4 2 1 3 1 | REFERENCE_ONLY | REFERENCE_ONLY |
| 13 | properscoring/properscoring | `a465b5578d4b661e662933e84fa7673a70e75e94` | Apache-2.0 (archived) | 31 | 3 3 3 0 5 4 4 2 1 | REIMPLEMENT_IDEA | LATER |
| 14 | hummingbot/condor | `d89e74f2e3e273bea102c64e4977118e6a88084f` | MIT | 30 | 2 2 4 5 2 5 1 4 1 | REIMPLEMENT_IDEA | LATER |
| 15 | Oddpool/PredictionMarketBench | `611d66941717310858683278940df21c33c406f2` | **none** (README says MIT) | 29 | 4 2 1 1 5 1 3 3 3 | LICENSE_REVIEW_REQUIRED (ideas only) | APPLY_NOW (test ideas) |
| 16 | pmxt-dev/pmxt | `4a367d812541154002eedda36b0916a3cf68e0f2` | MIT | 29 | 2 3 2 4 1 5 1 4 2 | REIMPLEMENT_IDEA | NEXT (Polymarket US field reference) |
| 17 | evan-kolberg/prediction-market-backtesting | `c76e77af00ef53472a9da8f66dae7fdd2d3e5928` | mixed MIT + LGPL-3.0 | 29 | 3 3 3 3 3 2 1 3 2 | REIMPLEMENT_IDEA | NEXT |
| 18 | Noisyxl/brier | `c8f167209dc20bdd7bd584f18c90c06d36c63fb2` | MIT | 28 | 2 3 2 2 3 5 3 2 1 | REIMPLEMENT_IDEA | LATER |
| 19 | nahrek/polyledger | `62b889a9f4cc329d5a42d0d2daa7cfccb3b7bc34` | MIT | 26 | 2 3 2 2 3 5 1 2 1 | REIMPLEMENT_IDEA | LATER |
| 20 | hummingbot/hummingbot-api | `d276034aee978d826bf05afcc2197eb1360c4a6a` | MIT | 26 | 2 2 3 5 1 5 1 3 0 | REFERENCE_ONLY | REFERENCE_ONLY |

The ranking replaces the seed list; it was not kept out of politeness.
- **Ten seed repositories fell out:**
  - Simmer SDK, prediction-market-sdk, the Alphapoly bot, Kalshi starter code,
    KalshiMarketMaker, The Odds API samples, SportsArbFinder, real-time-data-client, the
    weather bot and the Action Network scraper.
  - They ranked 21–42; §5 gives the reasons.
- **Ten entered:**
  - pykalshi, Jon-Becker's data framework, Apprise, sports-skills, properscoring, condor,
    pmxt, brier, polyledger and Hummingbot core.

## 4. What each finalist offers

Paths are relative to the upstream repository at the reviewed commit. Full evidence is in the
cluster report named in brackets.

1. **polymarket-us-python** [B]
   - **Learn:**
     - the complete public endpoint catalogue on `gateway.polymarket.us`;
     - response envelopes: `marketData.bids/offers`, `{px:{value,currency}, qty}`, and
       null or empty-string fields;
     - never retry a POST.
   - **Key files:** `polymarket_us/client.py`, `_retry.py`, `types/markets.py`.
   - **Do not import:** the package (httpx, pynacl, websockets, plus the order, portfolio
     and signing surface).
   - **Unlocks:** a second venue for the quote contract, and a settlement label source.
2. **ntfy** [E]
   - **Learn:** the HTTP publish API. Headers: `X-Title`, `X-Priority` 1–5, `X-Tags`,
     `X-Click`, `X-Sequence-ID` (replaces a notification on the phone; the server does not
     deduplicate), and Bearer tokens.
   - **ntfy.sh free-tier limits:** 250 messages a day and 4 KB per message.
   - **Privacy:** ntfy.sh sees plaintext and forwards to FCM/APNs, so send headlines only.
   - **Unlocks:** the first real delivery channel for #33.
3. **pykalshi** [A]
   - **Learn:**
     - the per-market `price_ranges` tick-grid check;
     - a Decimal walk-the-book that returns None when depth runs out;
     - the fixed-point `_fp` / `_dollars` fields;
     - the CHANGELOG as a record of Kalshi wire changes: cents fields removed, the v1 order
       endpoint 410, new price structures from the week of 2026-07-27.
   - **Do not import:** automatic dotenv loading, POST retries, `mid`.
4. **flumine** [D]
   - **Learn:**
     - a single-consumer event queue;
     - the same strategy code live and simulated;
     - an ordered pre-trade control chain with a terminal VIOLATION;
     - exposure that counts pending orders;
     - a deterministic `customer_order_ref`.
   - **Key files:** `controls/tradingcontrols.py`, `controls/clientcontrols.py`,
     `simulation/simulatedorder.py`, `order/order.py`.
   - **Do not import:**
     - Betfair back/lay semantics, liability maths, the odds ladder, BSP, bet delay;
     - traded-volume halving in the queue;
     - `force=True`, which bypasses every control;
     - float money;
     - silent 1.01/1000 price defaults.
5. **Hummingbot core** [E]
   - **Learn:**
     - the 11-state `InFlightOrder`;
     - restart reconciliation that marks an order terminal only when the exchange confirms
       it;
     - fills deduplicated by trade id.
   - **Anti-patterns:**
     - a submit exception marks an order FAILED and drops it (`exchange_py_base.py:461-532`);
     - state can move after a terminal state (`in_flight_order.py:341`);
     - client order ids are not derived from intent.
6. **py-sdk** (Polymarket International, current) [B]
   - **Learn:** the International fee model, `rate·(p(1−p))^exponent`, from `/clob-markets`.
   - **Anti-pattern:** a missing fee is read as 0 (`market_data.py:211-213`).
   - **Scope:** International only. It is excluded until eligibility is established.
7. **Jon-Becker/prediction-market-analysis** [C]
   - **Learn:** a Kalshi trade tape with `_fetched_at` is safe point-in-time data.
   - **Lookahead trap:** its market rows are current-state snapshots, so using them as
     history is lookahead.
   - **Other lessons:** a cursor-resumable backfill needs a completeness check, and the
     36 GiB dataset has no checksum.
8. **Apprise** [E]
   - Supports 100+ channels with 6 dependencies.
   - Secrets live in service URLs.
   - Its ntfy plugin lacks `X-Sequence-ID`.
   - Revisit only when three or more channels are authorized, as a pinned optional extra.
9. **betfairlightweight** [D]
   - **Learn:** a book built from a snapshot plus deltas, where size 0 deletes a level.
     Recorded replay goes through the live listener.
   - **Our version:** a pure reducer in which a gap, a missing snapshot or a parse failure
     makes the book INVALID. Upstream silently creates a book from a delta and drops bad
     JSON.
10. **CCXT** [A]
    - **Learn:**
      - the `has` capability map (`types.ts:145-400`);
      - the Kalshi bid-only → ask inversion (`kalshi.ts:1050-1127`);
      - capped cursor paging (`kalshi.ts:222-306`).
    - **Do not import:** anything; see §7.1.
11. **sports-skills** [D]
    - **Learn:**
      - an HTTP record/replay fixture layer with sha256 integrity (`_replay.py`);
      - American-odds band validation (`betting/_calcs.py:41-59`) as a test oracle.
    - **Do not use:** its data sources are mostly unofficial and "personal use only", so
      they are not evidence-grade.
12. **nautilus_trader** [C]
    - **Learn:**
      - the L1/L2/L3 book taxonomy;
      - queue-ahead snapshot, decrement and rebase;
      - the `pending resolution` state for binaries.
    - **Pitfall:** `avg_px` returns 0.0 on an empty book (`analysis.rs:136-143`).
    - **As a dependency:** 112–189 MB wheels, Python 3.12+ and LGPL, so architecture
      inspiration only.
13. **properscoring** [C]
    - **Learn:** keep missing observations as NaN, never 0.
    - **Reimplement later, in stdlib:** a discrete RPS over the temperature PMF, and a Murphy
      decomposition with the binning residual shown explicitly.
14. **condor** [E]
    - **Learn:** a deterministic risk check before any agent tool call.
    - **Anti-pattern:** `run_code` / `manage_routines` run with the full API client in every
      profile, and loop mode auto-approves after the risk check.
    - **Our boundary:** approval is checked by the execution service itself, and no
      code-execution tool exists in any process that holds credentials.
15. **PredictionMarketBench** [C]
    - **Learn:** a Kalshi-native execution benchmark with market, IOC, GTC and post-only
      orders, a FIFO maker queue and per-level fees.
    - **Do not copy (no license):**
      - zero-latency fills;
      - books never depleted by our own fills;
      - no cash check;
      - a 50¢ mark when the book or bid is missing;
      - settlement credited at close time rather than when known;
      - float fees that overcharge 1¢ in 45 of 9,900 cases.
    - **Adopted as tests:** §6.
16. **pmxt** [A]
    - **Learn:** Polymarket US conventions (`polymarket_us/{price,normalizer,config}.ts`).
    - **Security:** its Python package launches a Node server that inherits every
      environment variable, and it can POST private keys to `api.pmxt.dev`. Never run it.
17. **prediction-market-backtesting** [C]
    - **Learn:** allowlist-style scrubbing of resolution fields (its denylist misses
      `status`, `last_price` and `outcomePrices`), and a gap that resets the book.
    - **Anti-patterns:** its "Brier advantage" scores a rolling mean of market prices, not a
      model, and the holdout is reused to pick the top 5.
    - **Licensing:** everything worth learning from is LGPL, so ideas only.
18. **brier** [C]
    - **Learn:** a hash-chained prediction receipt, and publishing the head hash, which is
      the GATE7-F09 anchor idea (an owner decision).
    - **Note:** its README promotes a crypto token.
19. **polyledger** [B]
    - **Learn:** resumable ingestion: rows and checkpoint in one transaction, dedupe on
      (tx_hash, log_index), a reorg buffer, raw integer amounts.
    - **Caveats:** it needs a HyperSync token, and it gained 623 stars in three weeks from a
      one-follower account.
20. **hummingbot-api** [E]
    - **Learn:** bind to 127.0.0.1 by default and use a private network for remote access.
    - **Anti-patterns:**
      - one password encrypts every account;
      - default `admin/admin`;
      - a read-write Docker socket (root on the host);
      - authenticated Python upload runs code;
      - no idempotency on `POST /trading/orders`.

## 5. Not adopted

**Deferred (ranked 21–30):**
- **KalshiMarketMaker.** Kill-switch spec: stop the worker, cancel its resting orders,
  verify. Defects to note:
  - `int(price*100)` truncates;
  - quotes centre on the midpoint;
  - the global cap ignores resting orders in other markets.
- **Alphapoly.** Only the grouping taxonomy (timeframe / threshold / candidate) and a
  fail-closed deadline-coherence rule are worth taking. Every LLM implication gets a
  hard-coded 0.98, and its profit arithmetic ignores fees and depth.
- **The Odds API samples.** No license. Useful as the endpoint and header reference for #29.
  - The key goes in the query string, so it leaks wherever URLs or errors are logged.
  - `x-requests-last` is never read.
  - It is unconfirmed whether the parameter is `apiKey` or `api_key`.
- **py-clob-client-v2.** International; superseded by py-sdk.
- **Simmer.** A hosted service with its own key. `live=True` is the default, and it
  auto-reads `WALLET_PRIVATE_KEY`. "Kalshi" there means DFlow on Solana. Decision: **C,
  ignore.**
- **polymarket-mcp-server.** The model sets its own `confirm` flag, and a no-login dashboard
  endpoint enables autonomous trading.
- **poly_data.** GPL-3.0.
- **backtesting.py.** AGPL-3.0, and the wrong market model.
- **real-time-data-client.**
  - Reconnect cannot be disabled and has no backoff.
  - It does not re-subscribe after reconnecting.
  - Messages without the text "payload" are dropped.
- **prediction-market-sdk.** Zero stars and thin.

**Rejected:**
- **vectorbt.** Commons Clause.
- **SportsArbFinder and robbiehaynes/arbitrage-finder.** Their arbitrage maths is wrong:
  spreads are paired on the same signed point, a missing draw is treated as a 2-way market,
  and the over stake goes to the under.
- **Kalshi/kalshi-starter-code-python.** No license.
- **Polymarket/py-clob-client.** Archived, "no longer functional".
- **polymarket-cli.** No license.
- **Polymarket agent-skills.** No license, and stale.
- **Kalshi/tools-and-analysis.** A 2023 notebook with about 75 pinned packages.
- **guzus/dr-manhattan.** No license, and it commits `.claude` settings.
- **Polymarket/agents.**
  - Order size is a number parsed from LLM text.
  - It always buys outcome `[1]`.
  - It retries forever.
- **timsonater/action-network-scraper.** 2018 public pages only, no license, SQL built by
  string formatting.
- **dev-polymarket/clob-client-v2.** A typosquat; see §1.
- **suislanchez/polymarket-kalshi-weather-bot.**
  - It reads KXHIGHNY `B80.5` as "above 80.5", but our captured rules make it the inclusive
    80–81 °F bracket, so it models the wrong event.
  - It names a settlement source our captured rules contradict.
  - It invents a 50¢ price when one is missing, and its API has no auth.
  - It is a useful example of why settlement comes first.

## 6. Adopted in this change

Each item records the dependency-versus-copy decision the directive asks for. No
third-party code was copied, no dependency was added, and the runtime is still stdlib-only.

| Item | Decision | Where | Why it was worth adding |
|---|---|---|---|
| Venue-neutral depth ladder and walk-the-book cost | REIMPLEMENT_PATTERN (TPN-R001) | `opportunity.py` (`DepthLadder`, `walk_ladder`, `price_depth_fill`), `kalshi_quotes.py` (`ladders_from_orderbook`), `tests/test_depth.py` | #30's "best price for the requested size" needs every captured level; the engine used only the top one. Semantics follow the audit's synthesis: captured levels only; all or nothing; a truncated capture that runs out is `DEPTH_UNKNOWN`, not thin; invalid levels fail closed; fees are priced per level by our schedules, and fractional takes have no cost. The top of the ladder equals the frozen top-of-book quote on the captured fixture. `evaluate()` and `latency-confirmed-v1` are unchanged. |
| Gate 7 replay-semantics tests | REIMPLEMENT_PATTERN (TPN-R002) | `tests/gate7/test_gate7_replay_semantics.py` | They pin, fail-closed, what the frozen EXP-001 model does *not* do: resting orders, queue position, maker fills, partial fills, deeper levels, liquidity reuse, a most-favourable recheck, default marks. Plus exact-Decimal fee rounding, with the C=4, P=0.50 regression that float implementations get wrong. |
| GATE7-F14 fix | first-party fix | `exp001_shadow.event_settlement_problems`, `daily._alert_key`, the dashboard conflict table | An event is contradictory when more than one captured bracket resolves YES or brackets state different expiration values (the Gate 2 rule). Its positions then stay pending, and every affected position, open or already settled, is reported as a SETTLEMENT_CONFLICT with the reason. Incomplete evidence (unsettled brackets, a winner not yet settled) is not a conflict. Coherent evidence settles exactly as before. |
| Third-party provenance guard | first-party | `THIRD_PARTY_NOTICES.md`, `tests/invariants/test_third_party_provenance.py` | Makes §8 enforceable. An unrecorded runtime dependency fails CI. So does a copy/adapt marker that cites no notice or first-party source, a dangling `TPN-` reference, and a third-party GitHub URL in `src/` without an entry. |
| Evidence bundle | first-party | `docs/audits/2026-09-23-github-reuse/` | Pinned SHAs, the full screened list and five cluster reports, so the ranking can be re-checked without this chat. |

Not adopted, and why:
- **No new dependency.** CCXT, pmxt, the Polymarket SDKs, Apprise and nautilus each fail the
  stdlib-only policy for less value than a small reimplementation.
- **No notification, venue or ticket code.** The integration coordinator owns those
  modules. They were built in PR #38 while this audit ran (`notifications.py` ADR 0020,
  `venues.py` ADR 0019, `execution_ticket.py`, `starter_policy.py` ADR 0018). §7 gives
  recommendations for extending them instead of a parallel implementation.

## 7. Answers to the directive's questions

### 7.1 CCXT: COPY_ADAPTER_IDEAS (not USE, not USE_OPTIONALLY)

A new `ccxt.prediction` namespace holds one implementation file per venue, for Kalshi,
Polymarket, Limitless and Myriad. The Python side is async only.

- **Methods all four venues have:** paged `fetchMarkets`, `fetchOrderBook`, `fetchTicker`,
  `createOrder`, `fetchPositions`.
- **WebSocket books:** Polymarket and Myriad only.
- **`fetchSettlements`:** Kalshi only.
- **Rules text:** not mapped to a field; it stays in the raw payload.
- **Fees:** hard-coded. Kalshi 0.07 with no cent rounding and no series multiplier;
  Polymarket 0; Limitless 2 %.
- **Units:** prices are 0–1 floats, and YES/NO are outcomes. Kalshi's NO gets a made-up id
  (`ticker-NO`).
- **Crypto leakage:** `base/quote = USD`, spot and margin flags, leverage fields.
- **Defaults to reject:**
  - a synthetic Myriad book (`myriad.ts:2617-2636`);
  - Polymarket winner inference from price ≥ 0.99 (`polymarket.ts:777`);
  - a default builder address on every Polymarket order (`polymarket.ts:333-335`);
  - an automatic unlimited token approval on Myriad (`myriad.ts:795-810`).
- **Polymarket there is International.**
- **Kalshi:** uses the current v2 API with RSA-PSS signing.
- **Weight:** about 19 MB and 22 pinned dependencies.
- **Verdict:** our small venue adapters stay safer and simpler. The `has` capability-map
  idea is already realized, and exceeded, by `venues.py` (ADR 0019).

### 7.2 Polymarket SDKs

**Products and SDK status:**

| Repo | Product | Status |
|---|---|---|
| polymarket-us-python | **US**: gateway (public), api (Ed25519 auth) | current (v1.0.1; breaking type fix 2026-09-22) |
| py-sdk | International | current, the unified successor |
| py-clob-client-v2 | International | maintained, superseded by py-sdk |
| py-clob-client | International | archived, "no longer functional" |
| real-time-data-client | International RTDS | low activity |
| polymarket-cli, agents, agent-skills | International | no license / archived / no license |

**Cross-check against the adapter built in PR #39 (`src/edge_lab/polymarket_us.py`).**
It was built in parallel from Polymarket's own docs, with captured evidence in
`experiments/multi_venue/`. It agrees with this spec on every point below:
- it reads `marketData.bids/offers` as Decimal `px` / `qty`;
- `transactTime` is the source timestamp;
- BBO is never executable;
- only `MARKET_STATE_OPEN` is quotable, and a missing state fails closed;
- fees are UNSUPPORTED;
- `rules_resolved=False`;
- a catalog scan is COMPLETE only on an empty final page with no filters.

**Correction to this audit:** reviewer B marked the NO side UNVERIFIED because the SDK does
not document it. The venue docs do: "If you want to buy NO at $0.40, you're really selling
YES at $0.60". The adapter's NO price, 1 − best YES bid with that bid's quantity, rests on
primary documentation, which outranks this audit's SDK-based reading.

**Remaining gaps, NEXT for the adapter owner:**
- The adapter builds top-of-book `ExecutableQuote`s only. A `DepthLadder` builder for
  Polymarket US, with YES asks from `offers` and NO asks from 1 − `bids`, would give the #30
  comparator two venues on one depth primitive.
- `_amount` accepts a missing `currency` as USD. This spec asks for USD explicitly.

The spec below is kept as the audit's independent reading.

**Spec for the read-only Polymarket US adapter** (GET only on `gateway.polymarket.us`, no
auth headers; record correlation ids, receipt time and body sha256 in provenance):

**Endpoints:**
- `/v1/events` and `/v1/markets`: limit/offset paging with no total count, so completeness
  is INFERRED;
- `/v1/events/slug/{slug}` and `/v1/market/slug/{slug}` (note the singular "market");
- `/v1/markets/{slug}/book`:
  - read `marketData.bids[]` and `marketData.offers[]` (not "asks");
  - each level is `{px:{value,currency}, qty}`, parsed as Decimal;
  - currency must be USD and 0 < px < 1;
  - `transactTime` becomes `source_timestamp_utc`; if it is null, freshness is UNKNOWN;
- `/v1/markets/{slug}/bbo`:
  - `bestBid` and `bestAsk` may be null;
  - `sharesTraded` and `openInterest` may be `""`, which becomes None;
  - there is no timestamp;
  - `lastTradePx` is never an executable price;
- `/v1/markets/{slug}/settlement`:
  - it returns `{slug, settlement}` with no time or source;
  - 1 means YES, 0 means NO, and any other value (such as 0.5) is non-binary or void;
  - a missing result or a 404 means unresolved, never NO.

**Gating:** only `MARKET_STATE_OPEN` is quotable.

**Declare UNSUPPORTED:**
- fees (US fee rates exist only on authenticated order objects), so `FEE_UNVERIFIED`;
- structured rules (the description is prose), so `RULES_UNRESOLVED`;
- NO/short-side quotes. Superseded: the venue docs document the complement rule, see the
  cross-check above;
- price history, the trade tape and WebSockets. The market WebSocket needs a key.

Full field list and fixture tests: report B, "Exact spec".

### 7.3 Flumine: which patterns strengthen us

**Worth reimplementing:**
- One consumer thread.
- Strategies that are the same code live and simulated.
- Simulated matching only against the first book after latency.
- An ordered control chain that ends in VIOLATION.
- Exposure that counts pending and resting orders.
- A deterministic order reference.

**Checks our future execution ticket should run, all with execution still disabled:**
- quantity and tick validity, in Decimal;
- market known, book present, market open;
- stale book rejected outright (flumine only warns);
- quote unchanged since the ticket was priced;
- order-state feed healthy before new risk is taken;
- exposure per order, contract, event and globally;
- trade-count limits and cooldowns;
- a rate budget reserved before sending;
- a deterministic client order id;
- an explicit transition table;
- no bypass flag.

**Do not import:** back/lay, commission on net winnings, BSP, in-play delay, market-version
lapse, the odds ladder, volume halving, float money.

### 7.4 Simmer: C, ignore

- **It is another service dependency:** every call needs a Simmer key and goes to
  `api.simmer.markets`, and signed orders and reasoning text are relayed through it.
- **Paper is only a flag:** paper is `venue="sim"` or client-side `live=False`, and the
  client-side fills use mid plus an assumed half-spread, a 0.5 price when missing, no fees
  and no depth.
- **Unsafe defaults:** `live=True`, and `WALLET_PRIVATE_KEY` is read automatically.
- **Nothing new for us:** its preflight blocker codes resemble what our rejection reasons
  already do.

### 7.5 PredictionMarketBench versus Gate 7 and the ledger

Its assumptions are listed in §4 item 15. Our frozen `latency-confirmed-v1` is taker-only,
all or nothing, at the entry ask, confirmed 10–15 min later. It is stricter everywhere except
the realism of resting orders, which it does not model at all. So the new tests pin *absence*
rather than add simulation:
- no resting order or queue fill from bids or trade prints;
- no fill for an offer that appears only at confirmation;
- taker only, at the entry ask;
- no partial fill and no deeper levels;
- one fill per market side per day;
- only the pinned confirmation window;
- no default price when data is missing;
- exact Decimal fees.

**Mark-to-market versus cost basis:** our ledger is cost-basis with worst-case exposure. No
mark exists, so a missing bid can never be marked at 0.50.

**Multi-market events:** this comparison exposed GATE7-F14, now fixed.

**Frozen EXP-001 execution assumptions:** unchanged.

### 7.6 prediction-market-backtesting

- **Data schemas and replay:**
  - Polymarket International full-depth L2 replay through Nautilus, with queue position,
    liquidity consumption and 75 ms latency.
  - Kalshi has trades and candlesticks only, with no book.
- **Point-in-time:** a denylist scrub of resolution fields, which misses fields, and a
  settlement-time fallback to close.
- **Metrics:** a "Brier advantage" of a rolling market mean, not of a model.
- **Experiment separation:** the holdout is reused for top-5 selection.
- **Execution:** a live Polymarket order-submission path exists
  (`adapters/polymarket/execution.py:1052`).
- **License by file:**
  - `prediction_market_extensions/` and `strategies/` are LGPL;
  - `main.py`, `backtests/_*.py`, `live/` and most scripts are MIT;
  - `crates/` is MIT OR LGPL.
- **Next:** an allowlist of decision-time fields for the Polymarket US adapter.

### 7.7 Alphapoly (#30 discovery and cross-market logic)

- **Grouping:** rule-based.
- **Implications:** judged by an LLM from event titles only (the LLM never sees the
  settlement rules), each given a hard-coded 0.98 probability. Verdicts are cached forever.
- **Arithmetic:**
  - coverage treats price as a probability;
  - one "profit" figure excludes fees, and another assumes a certain $1 payout;
  - prices are display or mid prices, with a 0.5 default;
  - no depth;
  - a missing fee becomes 0.
- **Security:** the API has no auth and allows any origin with credentials, beside
  wallet-unlock and buy endpoints.
- **Verdict:** LLM output is not deterministically verified.
- **For #30, take:**
  - the grouping taxonomy (timeframe / threshold / candidate);
  - a deadline-coherence rule that **fails closed** when dates are missing;
  - incremental pair expansion.

  Rules equivalence stays deterministic, on captured rules. An LLM may propose a relation;
  only code over captured rules may accept one.

### 7.8 Hummingbot API: future execution boundary only

**Found:**
- **Key isolation:** a folder per account, but one `CONFIG_PASSWORD` encrypts every
  account's keys.
- **API auth:** a single global Basic login, with default `admin/admin` that only logs a
  warning.
- **Private network:** it binds to 127.0.0.1 by default, and the README recommends
  Tailscale for remote access.
- **Order lifecycle:** no idempotency on order submission.
- **Bot lifecycle:** any authenticated caller can upload Python that is then imported, and
  the container has a read-write Docker socket, so the API host is effectively root.
- **AI/MCP boundary:** no approval concept exists; Condor loop mode auto-approves after a
  risk check.

**Patterns for a future Market Edge boundary** (not built now):
- a client order id derived from the ticket and written to the ledger before any network
  call;
- a `SUBMIT_OUTCOME_UNKNOWN` state that is reconciled before any retry;
- terminal states are final;
- fills deduplicated by trade id, with state derived from fills;
- "not found" separate from a network error;
- approval checked by the execution service itself, with a separate credential per purpose;
- no code-execution tool anywhere near credentials;
- 127.0.0.1 plus a private network.

### 7.9 ntfy and one notification event model

ntfy is usable now as a free push channel. `notifications.py` (ADR 0020) already provides
the contract, dedupe keys, a local outbox and a disabled SMS sink. An ntfy sink would be one
more sink behind that contract.
- **It is not carrier SMS:** it needs the app installed and online, and gives no delivery
  receipt.
- **Neutral fields** (report E has the full mapping to ntfy, SMS, email and in-app):
  - `event_id` and `dedupe_key` (maps to ntfy `X-Sequence-ID`, plus a local outbox,
    because the server does not deduplicate);
  - `severity` (maps to `X-Priority`);
  - `category`, `title` and `body_text`, with `created_at` and `stale_after`, so that
    already-stale alerts are never sent as current;
  - `links`: public https only, never a 127.0.0.1 dashboard link;
  - `sensitivity`: PRIVATE is never sent to ntfy.sh;
  - per-sink `delivery_state`: for a remote push or SMS sink, "accepted by the server" is
    all we know, so report it as submitted rather than delivered unless a receipt exists.
    For the local outbox, DELIVERED (written and flushed) is accurate.
- **Two gates before a real ntfy sink:**
  - The no-execution invariant forbids any POST and any request body in `src/`. An ntfy sink
    needs a deliberate, narrow invariant change in the same PR: a notification-only module,
    an allowlist of notification hosts, no venue host ever.
  - The first real send is external publication, so it needs owner approval recorded in the
    repo.

### 7.10 Action Network ingestion lesson

The 2018 repository scrapes public pages without logging in. It says nothing about PRO data.
Its Selenium 3 calls and absolute XPaths are obsolete, and it builds SQL by string
formatting. No license, so nothing is copied.

**Fields worth designing ourselves:**
- moneyline, spread and total, with offered prices;
- open versus current lines;
- game state and score;
- `captured_at`;
- the owner's permission evidence stored with each capture.

**Before any collection:**
- A PRO login counts as credential handling, so it needs owner approval.
- The owner-reported permission must be recorded as evidence.
- Collection must stay out of browser automation until the terms are reviewed and recorded
  (`docs/EXECUTION_PLAN.md`).

## 8. Adoption rules (enforced)

1. **Licenses:**
   - MIT, BSD and Apache code may be reused selectively, with notices kept.
   - LGPL: dependency or ideas only.
   - GPL and AGPL: no copying without a recorded compatibility review.
   - Commons Clause and custom licenses: ideas only.
   - **No license: no copying.**
   - Mixed licenses: trace every file.
   - If in doubt, do not copy.
2. **Provenance:**
   - Every copied, vendored, ported or adapted piece gets a `THIRD_PARTY_NOTICES.md` entry
     with the upstream commit and license, cited from the code (`TPN-…`).
   - Every runtime dependency gets an entry with its reason.
   - Enforced by `tests/invariants/test_third_party_provenance.py`.
3. **Security:**
   - Third-party repositories are untrusted.
   - Read statically before anything runs; never run install scripts; never put credentials
     in them.
   - Never open a third-party clone as a Claude Code or agent working directory: some ship
     `.claude` hooks or settings.
   - Popularity is not evidence; see §1 item 7.
4. **Our rules win:** STALE ≠ CURRENT, MISSING ≠ ZERO, no lookahead, no invented fills, no
   midpoint as an executable price, no profit claim without verified costs, no LLM-owned
   arithmetic. Any adopted pattern is tested against these rules.

## 9. Adoption plan

**Classification of the top 20:**
- **APPLY_NOW** (done in this PR):
  - PredictionMarketBench, flumine and nautilus (test ideas);
  - CCXT, nautilus and pykalshi (depth ladder).
- **APPLY_NOW** (as spec, cross-checked against the adapter built in #39):
  polymarket-us-python.
- **NEXT:**
  - ntfy sink;
  - pmxt (Polymarket US fields);
  - prediction-market-backtesting (field allowlist);
  - pykalshi (`price_ranges` tick grid, a Kalshi wire-change checklist).
- **LATER:**
  - Hummingbot core (order state machine);
  - flumine (control chain, when the execution ticket gains checks);
  - betfairlightweight (book reducer, when a streaming source is authorized);
  - properscoring and brier (RPS, Murphy decomposition);
  - Jon-Becker and polyledger (resumable backfill);
  - sports-skills (record/replay fixtures);
  - Apprise;
  - condor;
  - py-sdk.
- **REFERENCE_ONLY:** CCXT (beyond ideas), nautilus, hummingbot-api.
- **REJECT:** see §5.

Dependency-aware adoption graph. Each box is one shared layer with one canonical owner; venues
plug into it rather than growing their own stacks.

```
SOURCE REGISTRY + PROVENANCE (sources.py, storage.py)      [BUILT]
        │
VENUE CAPABILITY REGISTRY (venues.py; stage per capability, execution never authorized) [BUILT, #38]
        │
 ┌──────┼──────────────┬───────────────┐
Kalshi  Polymarket US   Novig daily CSV  The Odds API (fixtures)
[BUILT] [BUILT #39; depth ladder NEXT] [BUILT #39] [BUILT #39; offered odds ≠ prices]
        │
QUOTE + DEPTH NORMALIZATION (opportunity.py: ExecutableQuote, DepthLadder)     [BUILT in this PR]
        │                 └─ per-venue tick grid (Kalshi price_ranges)          [NEXT]
FEE INTERFACE (fee_schedules.py; per venue, UNSUPPORTED until evidenced)        [BUILT for Kalshi]
        │
EVENT / SETTLEMENT IDENTITY + RULES EQUIVALENCE (deterministic; LLM may only propose) [PARTLY BUILT]
        │
BEST-PRICE-FOR-SIZE COMPARATOR (#30)   [NEXT: needs Polymarket US ladders]
UNIQUE-MARKET DISCOVERY (#30)          [discovery.py BUILT #39]
        │
OPPORTUNITY ENGINE → SHADOW LEDGER → RISK / STARTER POLICY → OUTCOME BOARD       [BUILT]
        │
NOTIFICATION EVENTS (notifications.py [BUILT, #38] → local outbox → ntfy [NEXT] → SMS [BLOCKED])
        │
EXECUTION TICKET (execution_ticket.py [BUILT, data only]; add flumine checks + Hummingbot lifecycle) [execution BLOCKED]
```

Other shared layers the audit touches, and their owners:
- **Order-book deltas:** a future `BookState` reducer in `opportunity.py`, needed only for
  streaming.
- **Replay fixtures:** extend the existing snapshot fixtures; sports-skills' sha256
  record/replay is the model.
- **Calibration:** `stats.py`.
- **Resumable backfill:** `storage.py`, `sources.py`.

## 10. Roadmap re-run (issue #4 process)

Shared primitives now unlock several ideas at once:
- **The depth ladder** serves #30 (best price for size), #9 (comparison at size), #32
  (tickets need a limit price) and #6 (sizing against real depth).
- **The Polymarket US spec** serves #30, #32 (a second API-capable venue) and #5.
- **The notification field model** serves #33, #3, #32 policy exceptions and collector
  failures.
- **The control-chain checklist** serves #32 tickets and #6.
- **The GATE7-F14 fix** protects every future multi-bracket event on any venue.

| Idea | NOW | NEXT | LATER | BLOCKED |
|---|---|---|---|---|
| #36 reuse audit | this PR (audit, depth ladder, provenance guard, F14) | issue #36 updated with the adoption plan | re-audit before any execution or streaming work | — |
| #30 multi-venue | depth ladder (this PR); Polymarket US, Novig daily data and discovery (built, #39) | Polymarket US `DepthLadder` builder; Kalshi `price_ranges` tick grid; best-price-for-size comparator on two venues | ProphetX / IBKR feasibility | Novig live API (owner credentials) |
| #29 Odds API | fixtures adapter built (#39). It already meets every point the sports review raised: Decimal conversion that rejects −100 < x < +100, `apiKey` redaction, all three quota headers, de-vig never executable | — | consensus (median across fresh books) | live pulls (owner key + activation plan) |
| #33 notifications | contract, outbox and disabled SMS sink (built, #38) | ntfy sink behind the contract, after the invariant change | Apprise if ≥3 channels | first real send (owner approval); SMS (paid provider) |
| #32 starter policy / tickets | `STARTER_MAX_7D_V1` and ticket contract (built, #38) | flumine control checklist in the ticket contract | Hummingbot lifecycle states | any execution (no authority) |
| #9 / #5 sports | — | — | sportsbook consensus research | sports models (preregistration) |
| #27 Action PRO | — | — | schema design (§7.10) | purchase, login (owner) |
| #6 / #3 | — | risk and board read depth-aware costs | — | real-money policy |
| #7 free-first | applied: no paid source considered | — | — | — |

## 11. 2026-10-22 impact

- **Work saved:**
  - The Polymarket US and Odds API adapters were built in parallel (#39). The audit
    independently confirms their field semantics and redaction, and corrects itself on the
    Polymarket US NO side.
  - The ntfy sink is about 40 lines, not a provider integration.
  - The ticket checklist exists before the ticket code does.
  - Several attractive dependencies were ruled out early.
- **Build order:** unchanged on the critical path (activation, then Stage B days). The depth
  primitive moves ahead of the #30 comparator, and the notification invariant change is now
  a named prerequisite of any real sink.
- **Custom code removed:** none. No planned custom code is replaced by a dependency; each
  candidate was worse under our rules.
- **Dependencies added:** none.
- **Risks introduced:**
  - F14 changes settlement behaviour on incoherent evidence (fail closed; reviewed in the
    PR).
  - The depth ladder is new code with no production consumer yet.
- **Coherence:** one quote owner, one fee owner, one provenance rule, and a CI guard against
  unrecorded reuse. The result is a more coherent system, not a larger one.

## 12. What would make us reconsider

- **CCXT:** if it adds Polymarket US, drops floats in the prediction namespace and stops
  inventing books, re-evaluate it as an optional adapter.
- **Polymarket US SDK:** if it becomes stdlib-light and read-only-separable, consider it as a
  dependency.
- **SMS:** if the owner authorizes an SMS provider, compare Apprise with a direct sink.
- **Streaming:** if a streaming source is authorized, reimplement the betfairlightweight
  reducer pattern.
- **Licenses:** if PredictionMarketBench or Kalshi's starter code gains a license, re-check
  what can be reused.
