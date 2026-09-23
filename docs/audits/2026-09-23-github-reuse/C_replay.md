# Cluster C — prediction-market replay / backtesting / evaluation frameworks

Reviewer: read-only researcher, 2026-09-23. Static reading only. No third-party code was installed,
built, or executed. One exception, noted where used: I re-computed PredictionMarketBench's fee
*formula* in my own Python one-liner to check float rounding. I did not import their code.

Clones live under `scratchpad/repos/<owner>__<repo>`, pinned by SHA. Large repos are sparse or
blobless: Nautilus has only the order book, matching engine, fill/fee/latency models, the
Polymarket adapter `common/`, docs and LICENSE. vectorbt has only LICENSE, pyproject and portfolio
enums/nb. evan-kolberg excludes notebooks. Jon-Becker excludes data. Paths below are relative to
each clone root.

Market Edge files read for comparison: `src/edge_lab/fill_policy.py`, `opportunity.py`,
`shadow_ledger.py` (skim), `stats.py`, `exp001_baseline.py` (Brier/log-loss grep),
`exp001_shadow.py` (recheck selection, settlement), `settlement_audit.py` (grep),
`fee_schedules.py` (grep), `docs/engineering/GATE7_FINDINGS.md`, `docs/RESEARCH_PRINCIPLES.md`,
and the `tests/gate7/` test names (83 tests: ledger 26, market 31, reporting 6, risk 20).

Score key: 0–5 per criterion, 5 = best (INTEGRATION_EFFORT 5 = easiest). TOTAL is out of 45.

---

## Summary table

| Repo | SHA-12 | License (as found) | Reuse class | Action | Total /45 |
|---|---|---|---|---|---|
| Oddpool/PredictionMarketBench | 611d66941717 | **No LICENSE file** (README + pyproject say MIT) | LICENSE_REVIEW_REQUIRED (ideas only) | APPLY_NOW (as test-scenario source, no code) | 23 |
| evan-kolberg/prediction-market-backtesting | c76e77af00ef | Mixed: MIT root + LGPL-3.0-or-later (whole `prediction_market_extensions/`, `strategies/`, 9 `backtests/*.py`) | REIMPLEMENT_IDEA | NEXT (resolution-field allowlist idea) | 23 |
| nautechsystems/nautilus_trader | 3adf5a8dc0c9 | LGPL-3.0 (`LICENSE`) | REFERENCE_ONLY | REFERENCE_ONLY | 26 |
| Jon-Becker/prediction-market-analysis | 7fbbb1ebefed | MIT (`LICENSE`) | REIMPLEMENT_IDEA | LATER | 27 |
| properscoring/properscoring | a465b5578d4b | Apache-2.0 (`LICENSE`), archived | REIMPLEMENT_IDEA | LATER | 25 |
| kernc/backtesting.py | ca2e2611621e | AGPL-3.0 (`LICENSE.md`) | REJECT | REJECT | 17 |
| polakowo/vectorbt | a3c0f4097964 | Apache-2.0 **+ Commons Clause** (`LICENSE.md`) | REJECT | REJECT | 15 |
| warproxxx/poly_data | 136e129735c7 | GPL-3.0 (`LICENSE`); pyproject says MIT (mismatch) | REFERENCE_ONLY | REFERENCE_ONLY | 17 |
| Noisyxl/brier | c8f167209dc2 | MIT (`LICENSE`) | REIMPLEMENT_IDEA | LATER | 23 |

---

## 1. Oddpool/PredictionMarketBench

- URL: https://github.com/Oddpool/PredictionMarketBench. Reviewed SHA `611d66941717310858683278940df21c33c406f2` (2026-01-25).
- Default branch `main`. Not archived. Python. ~24 MB (almost all parquet episodes). 27 stars, 5 forks.
- Activity: 6 commits in total (2026-01-06 to 2026-01-25). Nothing since. Maintainer: the Oddpool org (a
  single author, "Avi Arora", avi@oddpool.com). Oddpool is a commercial site. Credibility is low to medium.
- CI: none (`.github/` is absent). Releases: none (pyproject says 0.2.0, Alpha).
- Tests: 18 functions (`tests/test_core.py`, `tests/test_portfolio.py`). They cover book derivation, fees,
  the taker walk, partial fill, limit-must-cross, and portfolio settle/mark. **There are no tests for
  `simulator.py`, `maker_queue.py`, latency, cash limits or settlement timing.**
- Docs: README only. It is clear, but it overclaims (see below).
- Runtime deps: none (`dependencies = []`). Optional: pyarrow, matplotlib, pillow.
- Security scan: no `subprocess`, `eval`, `exec`, pickle, network, or credentials. File writes happen
  only in `harness.py` save methods (user-chosen paths). Clean.
- Credential handling: none. Network: none. Telemetry: none.
- **License: no LICENSE file.** The GitHub API reports `license: none`. README "## License MIT" and
  `pyproject.toml` `license = {text = "MIT"}` are claims, not a grant file. Under the briefing rule
  (no LICENSE file = ideas only), **no code reuse.** Ideas and test scenarios can be reimplemented
  from scratch.
- Data schema replayed (from `src/oddpool_bench/data.py:74-118,183-204` and the parquet footers of
  `episodes/KXHIGHNY-26JAN20/*`):
  - `orderbook.parquet`: `ts` (tz-aware), `sequence_id`, `ticker`, `yes_bids` and `no_bids` as
    `list<{price_cents,size}>`. These are **full-depth snapshots, bid-only** (Kalshi native). They are not deltas.
  - `trades.parquet`: `ts, trade_id, ticker, side, taker_side, price_cents, count`.
  - `settlement.json`: `{ticker: {result, settled_ts}}`. `metadata.json` holds tickers, window, bankroll,
    `fee_model_version`, `execution_mode`, `observation_depth`, `has_trades_tape`.
  - There is no receipt time distinct from `ts`, no rules capture, and no settlement provenance.
    `settled_ts` for KXHIGHNY-26JAN20 is `2026-01-21T04:59:00Z`, which is the market close/expiry, not
    when the result became known.
  - Episodes: KXBTCD-26JAN2017, **KXHIGHNY-26JAN20 (6 brackets, our series)**, KXNFLGAME-26JAN11BUFJAC, KXNCAAF-26.
- Execution and replay assumptions (Q1), with evidence:
  - **Order types**: MARKET; LIMIT with IOC / GTC / POST_ONLY (GTD is declared but unsupported)
    (`types.py:23-34`). Buy/sell on YES/NO, and sell maps to the opposite-side bid (`types.py:142-160`).
  - **Taker**: walks all executable levels. A limit order stops at its price, and a MARKET order has
    **no price cap** (`execution.py:163-198`). In `taker_only` mode, a limit that does not cross is
    rejected (`execution.py:118-128`). A MARKET order against an empty book returns zero fills with
    `rejected=False` (`execution.py:105-115`).
  - **Partial fills**: yes, both across levels and when depth runs out (`execution.py:175`,
    test `test_partial_fill_exhausts_depth`).
  - **Latency: zero.** The agent is called on an orderbook update and fills at that same snapshot
    and timestamp (`simulator.py:431-440`, `execution.py:186`).
  - **Liquidity consumption: none.** `execute_order` never mutates the book. Repeated orders in one
    `act()` call, or later calls before the next snapshot, can take the same displayed size again
    (`simulator.py:245-246`, `execution.py:163-198`).
  - **Staleness: none.** `current_orderbooks[ticker]` holds the last snapshot indefinitely, and the agent
    can trade on it hours later (`simulator.py:399-402`).
  - **Cash constraint: none.** `_place_order` never checks cash, and cash can go negative
    (`simulator.py:231-273`, `portfolio.py:91-92`). Naked "sells" create short positions, with no
    collateral reserved (`portfolio.py:157-192`).
  - **Resting orders and queue** (`maker_queue.py`): `env_ahead` is the displayed size at the level when
    the *first* agent order is placed (`:187-189`, `:171-182`). Trade prints at exactly the passive price
    consume `env_ahead`, and then agent orders fill FIFO (`:51-98`, `:230-271`). The default
    `trade_only` mode never shrinks `env_ahead` on cancels (`:294-297`). The `reconciled` mode caps it at
    the displayed size (`:316-320`). **README says "pro-rata fill allocation". The code is FIFO.**
    Trades *through* the agent's price, and book moves that make a resting order marketable, never
    fill it.
  - **Maker/taker fees**: `KalshiOct2025FeeModel` uses taker `ceil(0.07·C·P·(1−P))` and maker
    `ceil(0.0175·C·P·(1−P))` in cents, per fill level (`fees.py:392-429`, `execution.py:179`,
    `maker_queue.py:78`). The arithmetic is in **float**. My own recomputation of their formula
    (not their code) against exact Decimal found **45 of 9,900 (C ≤ 100, P = 1..99¢) cases overcharged
    by 1¢**, e.g. 4 contracts at 50¢: float 7.000000000000001 → 8¢, exact 7¢. The model has no fee
    multiplier or series-specific maker fee. The current sub-cent rounding (ceil to $0.000001, then
    balance alignment), which Market Edge's `fee_schedules.py:114-147` implements, is also absent.
  - **Multi-market events**: one episode is one event with N tickers. Each ticker has its own book and
    position. There are no event-level or cluster limits, and nothing checks that exactly one bracket
    settles YES.
  - **Mark-to-market vs cost basis**: the equity curve is **liquidation mark**: longs at best bid, shorts
    at best ask (`portfolio.py:264-304`). **A missing book or a missing bid is marked at 50¢**
    (`portfolio.py:276-281`, `:290`, `:294`, `:299`, `:302`). Position average cost excludes fees
    (`portfolio.py:95`). Realized P&L truncates with `int()`.
  - **Settlement**: a synthetic event at `settled_ts` (sequence 999999999) pays 100¢ per winning
    contract (`simulator.py:163-171`, `portfolio.py:194-251`). Cash is credited at the close
    timestamp, not when the result became known.
  - Anti-leak ordering: at equal `ts`, book updates sort before trades (`simulator.py:173-176`). The
    agent sees only data up to the current event. That part is sound.
  - Robustness: agent exceptions are swallowed silently unless verbose (`simulator.py:435-439`). The
    tool budget raises inside `act()` and is also swallowed (`agent.py:58-66`). The Sharpe is annualized
    from 60 s samples of a one-day episode (`metrics.py:113-123`), which is not meaningful.
- README claims vs code: "realistic execution constraints" is contradicted by zero latency, reused
  liquidity, no cash limit and a 50¢ fallback mark. "pro-rata fill allocation" is FIFO in code. "Fees
  follow the Kalshi fee schedule" uses the older cent-ceiling in float.
- Key files: `src/oddpool_bench/execution.py`, `maker_queue.py`, `simulator.py`, `portfolio.py`,
  `fees.py`, `data.py`; `episodes/KXHIGHNY-26JAN20/`.
- Learn: a clean, Kalshi-native bid-only book → derived asks model (the same as `kalshi_quotes.py`); the
  episode directory layout; the book-before-trade tie rule; an explicit list of execution modes. It is
  also the best available list of *what not to assume* (see the Q1 scenario table).
- Must NOT import: any code (no license); zero-latency fills; non-consuming books; the 50¢ fallback
  mark; float fee arithmetic; liquidation-mark equity presented as P&L.
- Overlap: `kalshi_quotes.py` (ask derivation), `fill_policy.py`, `fees.py`, `shadow_ledger.py` (settlement).
- Shared primitive it could unlock: a venue-neutral **depth ladder + walk-the-book** with explicit
  insufficient depth. PMB shows the walk; Market Edge must add fail-closed semantics.
- Episode data (KXHIGHNY-26JAN20 L2 snapshots + trades) would be useful research evidence, but it has
  no license and no provenance. **Do not ingest it** without owner approval and a license answer.
- Scores: PROJECT_FIT 4, SHARED_FOUNDATION 2, MATURITY_TESTS 1, MAINTENANCE 1, SECURITY 5,
  LICENSE_EASE 1, INTEGRATION_EFFORT 3, UNIQUE_VALUE 3, OCT22_IMPACT 3 → **23**.
- Reuse class: LICENSE_REVIEW_REQUIRED (effectively REFERENCE_ONLY for code). **Action: APPLY_NOW.** The
  reason: reimplement its execution scenarios from scratch as fail-closed Gate 7 pins. Copy no code.

---

## 2. evan-kolberg/prediction-market-backtesting

- URL: https://github.com/evan-kolberg/prediction-market-backtesting. SHA `c76e77af00ef53472a9da8f66dae7fdd2d3e5928` (2026-05-16).
- Default branch `v4.1-alpha` (unusual). Not archived. Python + Rust (`crates/`). ~165 MB repo, ~11 MB
  without notebooks. 1,202 stars, 199 forks. Individual maintainer. Last push 2026-05-16 (4 months ago).
- CI: `.github/workflows/ci.yml` runs ruff + pytest on push, and installs `nautilus_trader[polymarket,visualization]==1.226.0`,
  aiohttp, bokeh, duckdb, textual, nbformat, py-clob-client, and others. There is also a docs workflow. Releases: none (versions live in the README).
- Tests: **532** test functions. Some are strong (`tests/test_info_sanitization.py`,
  `test_execution_slippage.py`, `test_result_policies.py`), and many test runner and plotting plumbing.
  The Kalshi fee model has one test (`tests/test_kalshi_fee_model.py`).
- Docs: good (`docs/execution-modeling.md` is candid about limits).
- Runtime deps: large (Nautilus ≈ 100–190 MB wheel, pandas, numpy, pyarrow, msgspec, bokeh, duckdb,
  httpx, py-clob-client, optuna, and a Rust native extension built with maturin).
- Security scan:
  - Live **Polymarket International** order submission exists: `prediction_market_extensions/adapters/polymarket/execution.py:1052`
    (`_submit_order`) and `:1150` (`_submit_order_list`, uses `post_orders`). There is a live "sandbox"
    runner in `live/btc_snapshot_model_sandbox.py`.
  - Kalshi credential config reads `KALSHI_PRIVATE_KEY_PEM` from the environment
    (`adapters/kalshi/config.py:43-67`).
  - **Import-time monkeypatch of upstream Nautilus**: `prediction_market_extensions/__init__.py:24`
    replaces `nautilus_trader.adapters.polymarket.common.parsing.calculate_commission` globally. It is
    triggered from `backtests/sitecustomize.py`.
  - `pickle.load` of its own subprocess result file (`backtesting/_isolated_replay_runner.py:72`).
    `subprocess.run` appears in `main.py:790` and in `backtests/private/*`.
  - Network: the Kalshi REST `api.elections.kalshi.com` (`adapters/kalshi/providers.py:39`), PMXT archive
    `r2.pmxt.dev`/`r2v2.pmxt.dev`, the Telonex API (paid; `.env.example` has `TELONEX_API_KEY`), Gamma and CLOB.
  - No telemetry found.
- **License, traced per directory** (`LICENSE`, `NOTICE`, `docs/license.md`, per-file headers):
  - LGPL-3.0-or-later: **all of `prediction_market_extensions/`**. NOTICE says the package is LGPL, and it
    includes files without headers such as `backtesting/*`, `backtesting/data_sources/*`,
    `backtesting/prediction_market/*`. Also LGPL: all `strategies/*.py` with headers (including
    `strategies/microprice_imbalance.py`), 9 files `backtests/polymarket_*.py`, `scripts/_script_helpers.py`,
    and 4 test files.
  - MIT (`LICENSE-MIT`): `main.py`, `backtests/_*.py`, `backtests/private/*`, `live/*`, `scripts/*` other
    than `_script_helpers.py`, docs, and the Makefile. `crates/` (Rust) is `license = "MIT OR LGPL-3.0-or-later"`
    (`Cargo.toml:7`).
  - Mismatch: the NOTICE file list omits several files that carry LGPL headers:
    `adapters/kalshi/__init__.py`, `config.py`, `factories.py`, `adapters/prediction_market/replay.py`,
    and `strategies/microprice_imbalance.py`. The headers and the package-level NOTICE statement govern.
  - **Everything I would learn from is LGPL** (fill_model, replay, info_sanitization, kalshi fee_model,
    result policies, backtest_utils Brier). Ideas only. No code copying into a proprietary-ish repo.
- Data schemas: Polymarket L2 via PMXT hourly archives (`book_snapshot` + `price_change` → Nautilus
  `OrderBookDeltas`) and Telonex full-depth snapshots diffed into deltas, with trade ticks interleaved
  as *execution evidence only* (`docs/execution-modeling.md`). Kalshi has **trades + candlesticks
  only** (`backtesting/data_sources/kalshi_native.py:100-150`, `adapters/kalshi/loaders.py:52-54`). The
  README states that Kalshi L2 replay is not a runnable path.
- L2 replay: Nautilus `L2_MBP` with `liquidity_consumption=True`, `queue_position=True`,
  `trade_execution=True`, `bar_execution=False`, and `StaticLatencyConfig` (75 ms base) per
  `docs/execution-modeling.md`. Queue ahead is the same-side displayed size at acceptance, decremented
  by trade ticks at that price. `NO_AGGRESSOR` trades decrement both sides, and the doc admits this
  "can overstate fill probability".
- Non-book fallback fill model **invents liquidity**: `adapters/prediction_market/fill_model.py:24,93,169-226`
  builds a synthetic book at ask + N ticks, with size `max(10, order qty)` when no visible liquidity is
  tagged. The default `prob_fill_on_limit=0.25` (`:23`) is a coin-flip limit fill.
- Point-in-time safeguards:
  - `adapters/prediction_market/info_sanitization.py:21-35,77-113` strips resolution fields from
    instrument info before simulation. It is a **denylist** (`result`, `settlement_value`,
    `expiration_value`, `closed`, `closedTime`, `uma_resolution_status`, `is_50_50_outcome`, `resolved_by`,
    `resolution_source`, and per-token `winner`). Absent from the list: `status` (e.g. Kalshi
    `finalized`), `last_price`, and Gamma `outcomePrices`, which becomes `["1","0"]` after resolution.
    Whether those reach `instrument.info` is UNVERIFIED. An allowlist would fail closed.
  - PMXT gaps reset local book state and do not apply deltas across a missing hour
    (`docs/execution-modeling.md`, "Vendor L2 Behavior"). That is STALE ≠ CURRENT done right.
  - Coverage metadata separates planned from loaded windows (`planned_start/end`, `loaded_start/end`,
    `coverage_ratio`) (`adapters/prediction_market/replay.py:37-57,85-97`).
  - Weakness: the settlement timestamp falls back through `market_close_time_ns` → observable time →
    `planned_end` → `simulated_through` → series end (`backtesting/_result_policies.py:256-287`).
    Settlement cash can therefore be credited at close, before the result was known. This is the same
    class of defect as Market Edge GATE7-F04/F12.
  - Kalshi fee waiver is evaluated at order `ts_init`, not at fill time (`adapters/kalshi/fee_model.py:117`),
    even though the test is named "evaluated_at_fill_time".
- Portfolio replay: "joint portfolio" runners, and `apply_joint_portfolio_settlement_pnl` marks residual
  positions to the resolved outcome (`backtesting/_result_policies.py:449+`,
  `adapters/prediction_market/backtest_utils.py` `compute_binary_settlement_pnl`, which uses float).
  Account-ledger replay of a real Polymarket wallet is documented in `docs/account-ledger-replay.md`
  (not reviewed in depth).
- **Brier and calibration: not what the README implies.** In `build_brier_inputs`
  (`adapters/prediction_market/backtest_utils.py:401-446`) the "user probability" is a **rolling mean of
  the market price series** (`:429`), not the strategy's forecast. `prepare_cumulative_brier_advantage`
  (`analysis/legacy_plot_adapter.py:122-160`) then sums `(p−y)²` differences over every price tick of one
  market. That means thousands of autocorrelated rows share one outcome. The chart measures price
  smoothing, not model skill.
- Kalshi fee model: `adapters/kalshi/fee_model.py` uses `ceil_to_cent(rate·qty·p·(1−p))` in Decimal
  (`:171`), and its docstring claims "Kalshi does not distinguish maker/taker" (`:59`). That conflicts
  with PMB (maker 0.0175) and with Market Edge's captured evidence (maker M default 0; KXHIGHNY not listed).
  Primary evidence wins. It also lacks the sub-cent 2026 rounding.
- Experiment separation: frozen `ReplayExperiment` and `ParameterSearchExperiment` dataclasses
  (`backtesting/_experiments.py:34-66`). The optimizer has train/holdout windows but re-scores the
  **top-5 on holdout** (`backtesting/_optimizer.py:72`), so the holdout is used for selection. It also
  runs Optuna TPE searches. That contradicts `docs/RESEARCH_PRINCIPLES.md` (holdout used once, no large
  searches). The good part: result payloads carry disclosures ("curated replay may exclude cancelled…";
  "no drawdown/daily-loss breaker") (`_result_policies.py:17-23,375-381`).
- Visualization: bokeh tearsheets (LGPL, from minitrade lineage). Not needed. Market Edge has a dashboard.
- Learn: allowlist-style resolution scrubbing; coverage ratios; gap-resets-book; trades as evidence,
  not signals; result-level disclosure strings.
- Must NOT import: LGPL code; the synthetic-book fill model; the probabilistic limit fill; top-k holdout
  selection; the price-smoothing "Brier advantage"; settlement-at-close fallback; live order paths.
- Overlap: `opportunity.py` (evaluation), `fill_policy.py`, `fees.py`, `shadow_ledger.py`, `dashboard/`.
- Shared primitive: a decision-time field **allowlist** for venue metadata (future Polymarket US adapter).
- Scores: PROJECT_FIT 3, SHARED_FOUNDATION 3, MATURITY_TESTS 3, MAINTENANCE 3, SECURITY 3, LICENSE_EASE 2,
  INTEGRATION_EFFORT 1, UNIQUE_VALUE 3, OCT22_IMPACT 2 → **23**.
- Reuse class: REIMPLEMENT_IDEA. **Action: NEXT.** The reason: take the resolution-field scrubbing idea
  as an allowlist when the Polymarket US adapter is built. Nothing else.

---

## 3. nautechsystems/nautilus_trader

- URL: https://github.com/nautechsystems/nautilus_trader. SHA `3adf5a8dc0c9e676eb1e131911a73ad693ea7b42` (2026-09-23, `develop`).
- Default `develop`. Not archived. Rust (the core is almost entirely Rust crates; Python is a thin
  PyO3 layer under `python/`, see `MIGRATION_V2.md`). ~280 MB. 29.3k stars. Official org (Nautech
  Systems). Pushed today. Latest release `v2.0.0rc5` (2026-09-15). PyPI `nautilus-trader` 1.231.0.
- CI: extensive (`.github/` 28 files, cargo-deny, osv-scanner, gitleaks, supply-chain configs).
- Tests: very large. Example: `crates/model/src/orderbook/tests.rs` is 10,257 lines, and the matching
  engine has inline tests. Quality: high.
- Docs: extensive (`docs/concepts/backtesting.md`, `order_book.md`).
- Dependency complexity for Market Edge: PyPI wheels are **112–189 MB** (win_amd64 112.8 MB; manylinux
  x86_64 189.0 MB), `requires_python >=3.12,<3.15` (Market Edge supports 3.11+), and they pull in
  numpy, pandas, pyarrow ≥25, msgspec, fsspec, portion, pytz, tqdm, tzdata, click and uvloop. Verified
  from PyPI JSON on 2026-09-23. **Not realistic** as a dependency for a stdlib-only project.
- Security: this is a live trading platform. The Polymarket adapter reads `POLYMARKET_PK` (an EVM
  private key) (`crates/adapters/polymarket/src/common/credential.rs:39,344-352`) and has custom
  `Debug` impls to redact secrets (`:118,283,300,321`). It targets **Polymarket International**
  (`clob.polymarket.com`, `gamma-api`, `data-api`, `relayer-v2`; `common/urls.rs:18-24`). There is no
  Polymarket US support. No telemetry found in the sparse paths.
- **Prediction-market adapters at this SHA**: `crates/adapters/` holds architect_ax, betfair, binance,
  blockchain, bybit, coinbase, databento, deribit, derive, dydx, hyperliquid, interactive_brokers,
  kraken, lighter, okx, **polymarket**, sandbox and tardis. **There is no Kalshi adapter** (no "kalshi"
  path anywhere in the tree). Betfair is the only other prediction-style venue.
- License: LGPL-3.0 (`LICENSE`). Linking is allowed, but copying code into Market Edge is not. Ideas only.
- Order book: `crates/model/src/orderbook/book.rs`, with `BookType` L1_MBP / L2_MBP / L3_MBO.
  `apply_delta(s)`, `apply_depth` and `BookIntegrityError` (`book.rs:306-557`). Walk-the-book helpers:
  `get_avg_px_for_quantity` and `get_worst_px_for_quantity` (`book.rs:979-998`, `analysis.rs:119-177`).
  **Note:** `get_avg_px_for_quantity` returns `0.0` on an empty side and silently returns a *partial*
  average when depth is insufficient (`analysis.rs:136-143`). That is exactly the MISSING ≠ ZERO trap
  Market Edge must avoid. `get_worst_px_for_quantity` correctly returns `None` when nothing is available.
- Fill models (`crates/execution/src/models/fill.rs`): trait `FillModel` (`:48-95`) with
  `is_limit_filled`, `is_slipped`, `fill_limit_inside_spread`, `get_orderbook_for_fill_simulation`.
  `ProbabilisticFillState` uses a seeded RNG with `prob_fill_on_limit` and `prob_slippage` (`:164-201`).
  Variants: Default, BestPrice (**unlimited liquidity**, 10^10 units, `:41-46,373-406`), OneTickSlippage,
  Probabilistic, TwoTier, ThreeTier, LimitOrderPartialFill, SizeAware, CompetitionAware,
  VolumeSensitive, MarketHours.
- Matching engine (`crates/execution/src/matching_engine/mod.rs`, 11,423 lines):
  - Config defaults `queue_position=false` and `liquidity_consumption=false`
    (`matching_engine/config.rs:26-58`). By default, repeated orders can reuse the same displayed
    liquidity, which is PMB's flaw.
  - Queue position: at acceptance it snapshots the same-side quantity at the order price. For L1, orders
    behind the BBO are "pending". For L3, it tracks the exact orders ahead (`mod.rs:490-542`). Trades
    decrement queue-ahead, and `NoAggressor` decrements both sides (`:583-676`). Positions rebase and cap
    when levels shrink (`:780-1000`).
  - Liquidity consumption: tracked per price level, **reset whenever the level size changes**
    (`mod.rs:369-373`). An unrelated size change can therefore re-offer liquidity that was already
    consumed. It skips trade seeding when the book is newer than the trade (`:404-407`).
  - Binary options: after expiry, they enter **pending resolution**. Open orders are canceled and new
    orders blocked until a close/resolution arrives (`mod.rs:2488-2515,2553-2631`). That matches
    Market Edge's "locked until official evidence" semantics.
  - Latency: trait `LatencyModel` with insert/update/delete/base latency (`models/latency.rs`).
  - Fee: `models/fee.rs` (not reviewed in depth).
- Portfolio/accounting: `crates/portfolio/src/` (not reviewed in depth; standard mark-to-market
  portfolio with a cash/margin account).
- README vs code: the claims about a high-performance, event-driven engine with backtest/live parity are
  consistent with the code structure. Realism depends entirely on config flags that default off
  (queue position, liquidity consumption).
- Learn: book-type taxonomy; queue-ahead snapshot, decrement and rebase semantics; the explicit
  "pending resolution" state for binaries; `get_worst_px_for_quantity` returning `None`; seeded RNG
  for any stochastic fill (Market Edge should have none).
- Must NOT import: the dependency itself; unlimited-liquidity or probabilistic fill models; the
  `avg_px` 0.0 sentinel.
- Overlap: `opportunity.py` quotes, `fill_policy.py`, `shadow_ledger.py`, `risk.py`.
- Shared primitive: a depth ladder with worst-price and insufficient-depth semantics.
- Scores: PROJECT_FIT 2, SHARED_FOUNDATION 3, MATURITY_TESTS 5, MAINTENANCE 5, SECURITY 4, LICENSE_EASE 2,
  INTEGRATION_EFFORT 1, UNIQUE_VALUE 3, OCT22_IMPACT 1 → **26**.
- Reuse class: REFERENCE_ONLY. **Action: REFERENCE_ONLY.** The reason: it is the best matching-engine
  semantics to read, but it is a 100+ MB LGPL Rust dependency that needs Python 3.12+ and has no Kalshi adapter.

---

## 4. Jon-Becker/prediction-market-analysis

- URL: https://github.com/Jon-Becker/prediction-market-analysis. SHA `7fbbb1ebefedf20ce8dda7fe4ee6ecb05e80e9d8` (2026-09-21).
- Default `main`. Not archived. Python. ~162 MB repo (history). The dataset is external, 36 GiB compressed.
  3,856 stars, 546 forks. Individual maintainer (a known security researcher). Active.
- CI: `.github/workflows/ci.yml` (ruff lint/format + pytest) and `pr-validation.yml`. Releases: none.
- Tests: 19 functions (`tests/test_analysis_run.py`, `test_analysis_save.py`, `test_backfill_cursor.py`,
  `test_compile.py`). These are smoke tests. Nothing checks statistical correctness.
- Docs: `docs/SCHEMAS.md` and `docs/ANALYSIS.md` are good.
- Runtime deps: 18 (duckdb, pandas, pyarrow, scipy, matplotlib, httpx, tenacity, web3, cryptography,
  kalshi-python, polymarket-py, and others) (`pyproject.toml`).
- Security scan:
  - `scripts/download.sh:4` downloads `https://s3.jbecker.dev/data.tar.zst` (36 GiB) and extracts it
    with `tar` **without any checksum or signature**.
  - `scripts/install-tools.sh:38-44` prints and runs `sudo apt-get/dnf/yum/pacman install`.
  - `src/common/util/package.py:20` runs `subprocess.run(["tar","--zstd",...])` (fixed argv, local).
  - No credential logging found. `.env.example` has only `POLYGON_RPC` and a start block. No order paths.
- License: MIT (`LICENSE`), with no mismatch. It is permissive, but most of the code is duckdb SQL and
  pandas plotting, so there is little to copy.
- Data-collection lessons (Q5):
  - Kalshi collectors use public unauthenticated REST: `/markets` (cursor), `/markets/trades` (cursor,
    `min_ts`/`max_ts`) (`src/indexers/kalshi/client.py:7-117`).
  - **Schema** (`docs/SCHEMAS.md`):
    - Kalshi markets are *current-state* rows (yes/no bid/ask, last_price, volume, `result`, status)
      stamped `_fetched_at`. **They are not point-in-time**: the quotes and `result` are as of fetch time.
      Using them as historical quotes would be lookahead.
    - Kalshi trades are a historical tape (`trade_id, ticker, count, yes_price, no_price, taker_side,
      created_time, _fetched_at`), and that tape *is* point-in-time-safe. **There is no order-book
      history at all.**
    - Polymarket (International) trades are on-chain `OrderFilled` events with block number and log
      index, plus a block→timestamp table. That is point-in-time by construction.
  - Receipt time: `_fetched_at` is kept on every row. That is good, and it mirrors Market Edge's `fetched_at_utc`.
  - Collector weaknesses: `trades.py` treats a ticker as done once *any* of its trades exist, so an
    interrupted backfill becomes permanently partial. The dedup load swallows all exceptions
    (`except Exception: pass`). The universe is filtered to `volume >= 100` (selection bias). Ten worker
    threads each create a client with its own 10 rps limiter, so the aggregate is about 100 rps
    (`src/indexers/kalshi/trades.py`, `client.py:12`).
- Analysis lessons:
  - Maker vs taker excess return by price uses `AVG(won) − price/100` **without fees**
    (`src/analysis/kalshi/maker_vs_taker_returns.py:73-88`).
  - The statistical tests treat each trade as independent (Welch t-test, Mann-Whitney across trades)
    even though all trades in a market share one outcome (`src/analysis/kalshi/statistical_tests.py:300,458`).
    Significance is badly overstated.
  - Market Edge already treats the day or event as the independence unit (`settlement_audit.py:3`, the
    block bootstrap in `stats.py`). Keep it that way.
- Learn: trade tape plus `_fetched_at` is the right minimal schema for historical Kalshi; a market
  snapshot is not history. Maker/taker-by-price is a useful *hypothesis* source for KXHIGHNY (longshot
  bias), to be tested with fees and event-level clustering.
- Must NOT import: current-state market rows as historical quotes; per-trade significance tests;
  fee-free returns; the unverified 36 GiB download.
- Overlap: `kalshi.py` collectors, `storage.py`/`provenance.py`, `settlement_audit.py`.
- Shared primitive: none new. At most a cursor-resumable, completeness-checked trade backfill (Market
  Edge should record per-ticker *completion* markers, not "any row exists").
- Scores: PROJECT_FIT 3, SHARED_FOUNDATION 2, MATURITY_TESTS 2, MAINTENANCE 4, SECURITY 3, LICENSE_EASE 5,
  INTEGRATION_EFFORT 3, UNIQUE_VALUE 3, OCT22_IMPACT 2 → **27**.
- Reuse class: REIMPLEMENT_IDEA. **Action: LATER.** The reason: it is a hypothesis and data-design
  reference. Its dataset is not point-in-time for quotes and it has no book history.

---

## 5. properscoring/properscoring

- URL: https://github.com/properscoring/properscoring. SHA `a465b5578d4b661e662933e84fa7673a70e75e94` (2022-10-12).
- Default `master`. **Archived.** Python. 41 KB. 188 stars. Originally from The Climate Corporation (credible).
- CI: `.travis.yml` (dead). Tests: 29 (`properscoring/tests/test_brier.py` 6, `test_crps.py` 21,
  `test_utils.py` 2), with nose-era style. Releases: PyPI 0.1.
- Deps: numpy, scipy, and optional numba (`setup.py`). Security: clean (pure math). No network.
- License: Apache-2.0 (`LICENSE`), with no mismatch. It is permissive, with NOTICE and attribution
  obligations if code is copied.
- Components (Q5):
  - `properscoring/_brier.py:6-51` `brier_score`: validates p ∈ [0,1] and o ∈ {0,1,NaN}. **NaN
    observations propagate as NaN** (missing stays missing, which is correct).
  - `_brier.py:93+` `threshold_brier_score`: Brier at each threshold of an ensemble. Summed over
    ordered thresholds, this is the discrete **ranked probability score (RPS)**.
  - `_crps.py:24` `crps_gaussian` (closed form); `:151` `crps_quadrature` (any CDF); `:244`
    `crps_ensemble` with the sorted-ensemble integral (`_gufuncs.py:7-61`).
- Fit: EXP-001 forecasts a PMF over integer temperatures and settles brackets. Market Edge already
  has multi-category Brier (`exp001_baseline.py:242-248`), log loss, randomized PIT and central
  coverage (`stats.py`). **Missing: RPS/discrete CRPS over the ordered integer support**, which is the
  natural proper score for an ordinal forecast. It is about 10 lines of stdlib:
  `RPS = Σ_k (F(k) − 1{y ≤ k})²` using `math.fsum`, with None on missing.
- Must NOT import: the package (numpy/scipy deps). Any new metric used for a *decision* needs a
  preregistration amendment. Reporting-only use is fine.
- Scores: PROJECT_FIT 3, SHARED_FOUNDATION 3, MATURITY_TESTS 3, MAINTENANCE 0, SECURITY 5, LICENSE_EASE 4,
  INTEGRATION_EFFORT 4, UNIQUE_VALUE 2, OCT22_IMPACT 1 → **25**.
- Reuse class: REIMPLEMENT_IDEA. **Action: LATER.** The reason: add a stdlib RPS to `stats.py`
  as reporting-only when the Stage B report is built.

---

## 6. kernc/backtesting.py

- URL: https://github.com/kernc/backtesting.py. SHA `ca2e2611621e472542ba90f7243a1fa06a7d7108` (2026-08-05).
- Default `master`. Active. Python. 8,986 stars. Individual maintainer (credible, long-lived).
  CI: `.github/workflows/ci.yml` plus codecov. Tests: 81 (`backtesting/test/_test.py`). The GitHub
  releases API returned none (it publishes to PyPI).
- Deps: numpy, pandas, bokeh (`setup.py:33-37`). Security: clean. The URLs are doc links only.
- License: **AGPL-3.0** (`LICENSE.md`). This is incompatible with a proprietary-ish repo, even for
  derived code. Reference only.
- Model: OHLCV bars. Fills at the next bar open unless `trade_on_close`. Spread is a constant fraction
  (`backtesting.py:840-843`). Commission is fixed + relative or callable (`:727-760`). There is no order
  book, no depth, no binary payoff, and no settlement.
- Learn: "fill at next bar, never the signal bar" is a classic anti-lookahead default. A callable
  commission hook can express a quadratic fee.
- Must NOT import: anything (AGPL; wrong market model).
- Scores: PROJECT_FIT 1, SHARED_FOUNDATION 1, MATURITY_TESTS 4, MAINTENANCE 4, SECURITY 5, LICENSE_EASE 0,
  INTEGRATION_EFFORT 1, UNIQUE_VALUE 1, OCT22_IMPACT 0 → **17**.
- Reuse class: REJECT. **Action: REJECT.** The reason: an AGPL bar-based equity backtester that is
  irrelevant to binary order-book replay.

---

## 7. polakowo/vectorbt

- URL: https://github.com/polakowo/vectorbt. SHA `a3c0f40979648585b4581fc4694fd6e92b3fffca` (2026-09-17).
- Default `master`. Active. Python (numba; an optional `vectorbt-rust`). 9,162 stars. Individual
  maintainer. CI has tests, pypi, docs and docker workflows. Release v1.1.0 (2026-07-05).
- Deps: 17 runtime (numpy ≥2.4.6, pandas ≥3, scipy, matplotlib, plotly, ipywidgets, anywidget, numba,
  dill, tqdm, dateparser, imageio, scikit-learn, schedule, requests, pytz, mypy_extensions)
  (`pyproject.toml:29-47`). The "full" extra adds ccxt, python-binance, alpaca-py and python-telegram-bot.
- Security: `dill` and pickle persistence for the telegram bot (`vectorbt/_settings.py:448-452`). The
  optional extras include exchange SDKs. Not reviewed further.
- License: **Apache-2.0 + Commons Clause** (`LICENSE.md` header). This is not OSI open source, and it
  restricts "Sell". The GitHub API reports NOASSERTION. Avoid.
- Model: vectorized OHLC arrays. `buy_nb`/`sell_nb` apply proportional slippage, `allow_partial`, and a
  seeded `reject_prob` (`vectorbt/portfolio/nb.py:72-304,408-417`). There is no order book.
- Learn: `OrderStatusInfo` enumerates machine-readable rejection reasons
  (`vectorbt/portfolio/enums.py:502`). Market Edge's `Reason` enum and fill-policy reasons already
  do this better.
- Scores: PROJECT_FIT 1, SHARED_FOUNDATION 1, MATURITY_TESTS 4, MAINTENANCE 4, SECURITY 3, LICENSE_EASE 1,
  INTEGRATION_EFFORT 0, UNIQUE_VALUE 1, OCT22_IMPACT 0 → **15**.
- Reuse class: REJECT. **Action: REJECT.** The reason: the Commons Clause license, a heavy numba/pandas
  stack, and a bar-array model.

---

## 8. warproxxx/poly_data

- URL: https://github.com/warproxxx/poly_data. SHA `136e129735c73bce3a3d59f20354417b188e47fd` (2026-09-08).
- Default `main`. Active. Python. 2,343 stars. Individual maintainer. CI: none found (no `.github/`).
  Tests: 50 (`tests/test_process_live.py` 9, `test_update_chain.py` 19, `test_update_markets.py` 12,
  `test_utils.py` 10). Releases: none (tag `v1-final`).
- Deps: pandas, polars, python-dotenv, requests, **hypersync**, eth-abi, eth-utils, eth-hash
  (`pyproject.toml`). It vendors `backtrader_plotting/` (GPL lineage). `.DS_Store` is committed.
- Network: `polygon.hypersync.xyz` (Envio) needs an `HYPERSYNC_API` bearer token
  (`update_utils/update_chain.py:61,190-199`). The README says it is free, but it is still a
  credential, so owner approval is needed. It also calls `clob.polymarket.com/markets` and `gamma-api`.
- License: GPL-3.0 (`LICENSE`), but `pyproject.toml` says `license = { text = "MIT" }`. **This is a
  mismatch.** Treat it as GPL. No code reuse.
- Data: **Polymarket International** CTF Exchange V2 `OrderFilled` events, with trade price =
  USDC / token amounts (`update_utils/process_live.py:31-140`). It gives trades only and no book. The
  block timestamps make it point-in-time. The README notes that V1 data (subgraph) is now incomplete
  after the 2026-04-28 contract migration. **This is not Polymarket US and must not be conflated with it.**
- Scores: PROJECT_FIT 2, SHARED_FOUNDATION 2, MATURITY_TESTS 2, MAINTENANCE 3, SECURITY 3, LICENSE_EASE 1,
  INTEGRATION_EFFORT 2, UNIQUE_VALUE 2, OCT22_IMPACT 0 → **17**.
- Reuse class: REFERENCE_ONLY. **Action: REFERENCE_ONLY.** The reason: it covers the wrong venue for
  the plan (Polymarket US), is GPL, and needs a token.

---

## 9. Noisyxl/brier

- URL: https://github.com/Noisyxl/brier. SHA `c8f167209dc20bdd7bd584f18c90c06d36c63fb2` (2026-09-20).
- Default `main`. TypeScript (Node ≥20); GitHub reports it as HTML. ~37 MB, mostly GIF/MP4 assets. 117 stars.
  It was created 2026-09-06 and has 22 commits. Individual maintainer. **CI: none.** Tests: about 98
  `test(`/`it(` cases across 6 files in `test/`. Releases: none.
- Deps: `commander` only, plus dev deps tsx, typescript and @types/node. npm `prepare` runs `tsc` on install.
- Security/credibility: the README promotes a **token on "Robinhood Chain"** with a contract address
  (`README.md:670-680`), although it says the code needs no token. It makes LLM API calls to
  Anthropic and xAI using env keys (`src/panel/provider.ts:60-77`, `src/config.ts:73-76`). The chain
  anchor code **holds no key and has no `eth_sendRawTransaction`**; it prints a `cast send` command for
  the user (`src/anchor/anchor.ts:24,54`; `src/anchor/rpc.ts:5-6`). It does read-only RPC to Robinhood
  chain endpoints (`src/anchor/network.ts:34,43`). The token promotion lowers credibility.
- License: MIT (`LICENSE`), consistent with `package.json`.
- Components:
  - Hash chain `src/ledger/chain.ts`: `sha256(seq|at|kind|JSON.stringify(body)|prev)`. `JSON.stringify` is
    not canonical, so key order matters. `verify()` names the first broken line. The docstring states
    plainly that the chain cannot prove *when*; only publishing the head hash somewhere with its own
    timestamp does.
  - Scoring `src/score/brier.ts`: Brier, clipped log score (1e-6), Murphy decomposition with
    **an explicit residual for binning** (a good practice), confidence gap, and skill vs a base rate.
    Weaknesses: an empty set returns all zeros (MISSING = 0), and the baseline falls back to the
    in-sample observed frequency (lookahead in the baseline).
- Relevance: Market Edge `shadow_ledger.py` is already stronger (SQLite, triggers, canonical JSON,
  per-account chains, invariants). The one transferable idea addresses **GATE7-F09** (head truncation
  is undetectable without an external anchor): publish the ledger head hash periodically to a
  timestamped external place. A git commit or PR comment in this repo is enough, with no blockchain.
  That needs an owner decision (per F09).
- Scores: PROJECT_FIT 2, SHARED_FOUNDATION 3, MATURITY_TESTS 2, MAINTENANCE 2, SECURITY 3, LICENSE_EASE 5,
  INTEGRATION_EFFORT 3, UNIQUE_VALUE 2, OCT22_IMPACT 1 → **23**.
- Reuse class: REIMPLEMENT_IDEA. **Action: LATER.** The reason: the F09 head-anchor idea and the Murphy
  decomposition with residual. Copy no code and adopt no token or chain.

---

## Cluster questions

### Q1. PredictionMarketBench scenarios Market Edge's Gate 7 / fill policy does not cover

Market Edge's policy (`fill_policy.py`, `latency-confirmed-v1`) is taker-only, all-or-nothing, and
top-of-book. It has a 10–15 min confirmation and never fills at a better later price. **None of the
items below changes EXP-001.** Each is phrased as a new test that pins "unsupported → fails closed",
or as an invariant check. I checked coverage against the 83 `tests/gate7/` names plus a grep of
`tests/test_shadow_ledger.py`.

| # | PMB scenario (evidence) | Gap in Market Edge tests | Applicable? Proposed test |
|---|---|---|---|
| 1 | **Queue position**: resting order fills after `env_ahead` is consumed by trade prints (`maker_queue.py:51-98,230-271`) | No test pins that trade-tape evidence can never create a fill | YES (pin). `simulate_fill(entry=None, confirmation=None)` with a trade print at or through the ask still → `NO_ENTRY_QUOTE`. Assert the `FillPolicy` API has no limit-price or queue parameters (signature pin). |
| 2 | **Resting (GTC) order**: non-crossing limit rests and fills later (`simulator.py:252-268`) | No test covers "offer appears only at confirmation" | YES (pin). Entry has `best_ask=None` or an ask above the model threshold. The confirmation shows a lower ask with size → `NO_ENTRY_PRICE`, never FILLED (no "rest until offered"). |
| 3 | **POST_ONLY / maker** fill with maker fee 0.0175 (`execution.py:88-100`, `fees.py:412-429`) | Maker path absent by design, not pinned in tests | YES (pin). Every FILLED payload records taker semantics: `fee == fee_schedule.taker_buy(...)`, no maker/rebate field. Also assert no fee-schedule function offers a maker rate for KXHIGHNY. |
| 4 | **Partial fill across levels** (`execution.py:175`, `test_partial_fill_exhausts_depth`) | Entry-side covered (`test_displayed_size_below_quantity_is_not_filled`). Confirmation-side partial exists in `tests/test_shadow_ledger.py:247`, not in gate7 | YES. Add the explicit `quantity == 0 and price is None` assertion for both sides in gate7. Add a "deeper levels never used" test: book with 2@0.30 and 5@0.31, qty 3 → NO_FILL (never 2, never a blended 0.307). |
| 5 | **Liquidity reuse / self-impact**: the book is never depleted by the sim's own fills (`execution.py:163-198`, `simulator.py:245-246`) | Not tested | YES (invariant). Within one account, the sum of FILLED quantity referencing the same `entry_evidence_id` ≤ that quote's `displayed_size`. The same holds for `confirmation_evidence_id`. The research and operational accounts are separate hypotheticals, so compute this per account. |
| 6 | **Market order walks unlimited price** (`execution.py:163-174` has no cap for MARKET) | n/a (no market orders) | YES (pin). The fill price is always exactly `entry.best_ask`. Already implied by `test_price_movement_between_entry_and_confirmation`, so assert equality explicitly. |
| 7 | **Zero latency**: fill at the observed snapshot (`simulator.py:431-440`) | Covered (confirmation window tests) | Already covered. No action. |
| 8 | **Stale book traded** (`simulator.py:399-402`) | Covered (`test_fill_refuses_stale_or_future_entry`) | Already covered. |
| 9 | **No cash limit**, negative cash (`simulator.py:231-273`) | Covered ("settled cash never negative", F11) | Already covered. |
| 10 | **Multi-market event**: all brackets of one event in one episode; `settlement.json` has exactly one YES | Gate 2 audit checks "exactly 1 YES" (`settlement_audit.py:182,218`). The shadow settlement path settles market by market (`exp001_shadow.py:~425-449`). No gate7 test covers an event whose captured results have 0 or ≥2 YES brackets | YES (new). Feed two held brackets of one event that both capture `result=yes` (or none). Expect a settlement conflict and both positions to stay pending (locked), with no cash credited. |
| 11 | **Event replay ordering**: book before trades at equal ts (`simulator.py:173-176`) | The recheck capture is pinned by `recheck_capture_id` (`exp001_shadow.py:_recheck_quotes`), so there is no cherry-picking | Pin it. With two captures inside the window, the fill uses the pinned recheck capture only, never the most favorable one. |
| 12 | **Mark-to-market** with 50¢ fallback when the book or bid is missing (`portfolio.py:276-302`) | Covered: `test_equity_is_cost_basis_with_no_liquidation_mark` | YES (extra pin). Any displayed mark (if one is ever added) is `None` when the bid is missing, never 0.5 or 0. For now, assert that state has no mark field. |
| 13 | **Settlement at close timestamp** (`settled_ts` 04:59Z = expiry; `simulator.py:163-171`) | Covered (F04/F05/F12 tests) | Already covered. |
| 14 | **Float fee rounding** (`fees.py:406-410`; 45/9,900 cases overcharge 1¢) | Market Edge fees are Decimal | YES (property test). For C ∈ 1..100 and P ∈ 0.01..0.99, `taker_buy` equals an exact-Decimal reference. Add a regression case C=4, P=0.50. |
| 15 | **Per-fill-level fee rounding** (fee ceil per level, `execution.py:179`) | n/a (one level) | Pin only if a depth walk is ever added: fees are computed per the venue's documented unit (per trade/order). The per-level vs per-order rule is UNVERIFIED for Kalshi and must come from primary evidence. |
| 16 | **Agent errors swallowed** (`simulator.py:435-439`) | Market Edge records exceptions in receipts (per PR #26) | Covered. |

Items 1–6, 10, 11, 12 and 14 are the concrete additions. About 10 tests, all in `tests/gate7/`.

### Q2. prediction-market-backtesting (answered in §2)
- Schemas: PMXT/Telonex Polymarket L2 → Nautilus deltas plus trade ticks as execution evidence; Kalshi
  trades and candlesticks only.
- L2 replay: Nautilus L2_MBP, liquidity consumption, queue position, and 75 ms static latency.
- Point-in-time: a resolution-field denylist (gaps listed), gap-resets-book, planned-vs-loaded
  coverage. Settlement credit can fall back to close time.
- Portfolio replay: joint-portfolio settlement PnL in float.
- Brier: "user probability" is a rolling mean of market prices, so it is not a skill metric.
- Visualization: bokeh tearsheets (LGPL).
- Experiment separation: frozen experiment dataclasses, but top-5 holdout selection and Optuna searches.
- License: all of `prediction_market_extensions/` and `strategies/` is LGPL-3.0-or-later. MIT covers only
  `main.py`, `backtests/_*.py`, `backtests/private/*`, `live/*`, most of `scripts/`, and docs. `crates/`
  is MIT OR LGPL. Everything worth learning from is LGPL, so it is ideas only.

### Q3. Nautilus (answered in §3)
- Book types L1_MBP/L2_MBP/L3_MBO; FillModel trait with a seeded `prob_fill_on_limit`/`prob_slippage`
  and eleven variants (some with unlimited liquidity).
- Queue position: a same-side level snapshot, decremented by trades, rebased on book shrink, and exact
  orders tracked for L3. It defaults off, as does liquidity consumption.
- Binary "pending resolution" after expiry.
- **No Kalshi adapter at this SHA.** Polymarket (International) is in Rust.
- As a dependency: not realistic (112–189 MB wheels, Python ≥3.12, about 11 required deps, Rust core,
  LGPL). **Use it for architecture inspiration only.**

### Q4. Best framework overall, and the one thing to reimplement now
- Best engine semantics overall: **Nautilus** (queue-ahead, liquidity consumption, pending resolution,
  book integrity). Best prediction-market-specific realism: **evan-kolberg's extension on Nautilus**
  (Polymarket L2 only). Most relevant to *our* venue and series: **PredictionMarketBench** (Kalshi
  bid-only book, a KXHIGHNY episode), but it is naive (zero latency, reused liquidity, no cash limit,
  50¢ mark, float fees) and has no license. **Adopt none. Learn from all three.**
- **Reimplement NOW (one item): a Gate 7 "unsupported execution fails closed" test family**, the
  roughly 10 tests from Q1 rows 1–6, 10, 11, 12 and 14. It is bounded and stdlib-only, touches only
  `tests/gate7/`, and freezes EXP-001's taker-only, all-or-nothing, latency-confirmed assumptions
  against future drift. It also closes one real gap: event-level settlement exclusivity in the shadow
  path (row 10). If row 10 finds a real defect, it follows the GATE7 xfail(strict) protocol.
- NEXT (when the Polymarket US full-depth book adapter lands): a venue-neutral **`DepthLadder`**
  primitive in Decimal. `walk(qty)` returns `{status: FULL | INSUFFICIENT_DEPTH | NO_BOOK, levels_used,
  worst_price, vwap (None unless FULL), displayed_total}`. Use it for diagnostics and capacity
  reporting only, never in the frozen EXP-001 policy. Its semantics avoid Nautilus's `avg_px` 0.0
  sentinel and partial-average trap. Fees are computed on the full order per primary-source rounding.
- LATER: a stdlib **RPS** over the integer support, plus a **binary reliability table with Murphy
  decomposition and an explicit binning residual**. Both are reporting-only. `stats.py` and
  `exp001_baseline.py` already have multi-category Brier, log loss, randomized PIT and coverage, but
  no RPS or decomposition.

### Q5. Calibration implementations and data-collection lessons
- **properscoring**: `brier_score` (NaN-propagating, validated), `threshold_brier_score` (summed over
  ordered thresholds = RPS), `crps_ensemble`, `crps_gaussian`, `crps_quadrature`. For EXP-001's
  integer-temperature PMF, reimplement the **discrete RPS** in about 10 stdlib lines with `math.fsum`,
  returning None on missing inputs. CRPS-Gaussian is unnecessary because the model is a PMF.
- **brier (Noisyxl)**: Murphy reliability/resolution/uncertainty **with an explicit residual** for
  binned forecasts (`src/score/brier.ts`). Worth copying as an idea. Avoid its empty-set-returns-zero
  and in-sample-baseline behaviour. Also avoid hard-coding a 1e-6 log clip without recording it
  (Market Edge should record any clip in the preregistration).
- **Jon-Becker**: calibration-by-price-bucket and maker/taker excess returns are useful *hypotheses*
  (longshot bias, maker advantage), but the implementations ignore fees and treat trades as
  independent. Data lessons:
  1. A Kalshi trade tape with `created_time` plus `_fetched_at` is point-in-time-safe, but market
     rows are current-state snapshots. Using their bid/ask or `result` historically is lookahead.
  2. There is no public historical Kalshi order book in any of these repos. Book history exists
     only if we capture it ourselves (Market Edge already does) or from a licensed vendor.
  3. Backfills need per-ticker completion markers, not "any row exists".
  4. Downloaded bulk data needs a checksum and provenance before use (`scripts/download.sh` has none).
