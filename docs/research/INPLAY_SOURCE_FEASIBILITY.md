# In-play source feasibility (#122 §12, §14)

**Status:** research record, 2026-09-28 (VF Writer B, PR B). Authority:
`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`.

This document authorizes nothing. Any production acquisition, stream, credential, account read
or timer needs its own owner approval, and so does the pilot proposed in §6. It is **PROPOSED,
NOT APPROVED**. EXECUTION_NOT_AUTHORIZED stays enforced.

Method:
- Every fact below was read from a public documentation page on **2026-09-28** (UTC day of the
  session). No Kalshi API endpoint, account or order route was called. Pages were read through a
  documentation fetcher, and no raw page bytes or hashes were kept, so every row is
  `DOCUMENTED_UNVERIFIED_BYTES` in the sense of `opportunity.UnitSemantics.verification`. One
  exception is the Kalshi Data Terms PDF: its bytes were read (sha256 below).
- A documented behaviour is not account-specific verification. An omitted auth header in an
  example is not proof of unrestricted access. Documentation for Kalshi's perpetual-futures
  product is **not** used for event contracts.
- Quotes are short and verbatim. Anything else is labelled INFERENCE or UNKNOWN.

## 1. Verified facts (event contracts)

### 1.1 Native Auto Sell (take profit)

Source: <https://help.kalshi.com/en/articles/15521632-auto-sell-take-profit> (page states "Last
updated" June 16, 2026; read 2026-09-28).

| Fact | Quote |
|---|---|
| It is a resting limit sale | "Your auto sell appears under Orders as a resting limit sell." |
| It works with the app closed | "The order rests on the exchange, so it can fill even when the app is closed." |
| It can fill partially | "It can fill partially if there are not enough buyers at your target" |
| Target floor | "The lowest target you can choose is at or above your purchase price" |
| Editing and cancelling | "You can edit the price or cancel it there at any time before it fills." |
| Turning off the prompt | "Turning the prompt off does not change any auto-sell orders you have already placed." |

Consequences for Market:
- A target at or above the purchase price is not a guarantee of profit after fees.
- A chart touching the target is not a fill of the whole position.
- An Auto Sell order **reserves inventory** that the bot must not also treat as available. The
  policy evaluator enforces this (`position_policy`, `OVER_RESERVED`).
- The page does not say whether Auto Sell orders are `reduce_only`, nor whether they are cancelled
  on pause: **UNKNOWN**.

### 1.2 Websocket stream: auth, channels, sequencing, resync

Sources, all read 2026-09-28:
- <https://docs.kalshi.com/getting_started/quick_start_websockets>
- <https://docs.kalshi.com/websockets/orderbook-updates>
- <https://docs.kalshi.com/websockets/websocket-connection>
- <https://docs.kalshi.com/websockets/market-ticker>

Findings:
- **Endpoint:** production `wss://external-api-ws.kalshi.com/trade-api/ws/v2`; the legacy
  `wss://api.elections.kalshi.com/trade-api/ws/v2` "remain[s] supported".
- **Authentication is required for every connection.** The handshake carries
  `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE` and `KALSHI-ACCESS-TIMESTAMP`. The signature
  follows the REST pattern "timestamp + GET + /trade-api/ws/v2". Also: "Even channels that carry
  public market data still use the authenticated WebSocket session".
- **Channel classes (quick start).**
  - Private: `orderbook_delta`, `fill`, `market_positions`, `communications`,
    `order_group_updates`.
  - Public: `ticker`, `trade`, `market_lifecycle_v2`, `multivariate_market_lifecycle`,
    `multivariate`.
  - The orderbook channel is therefore listed as **private**. Whether a key without account
    scopes may subscribe to it is **UNKNOWN**.
- **Snapshot plus delta.** The channel "Sends orderbook_snapshot first, then incremental
  orderbook_delta updates."
  - Snapshot: `yes_dollars_fp` / `no_dollars_fp` as `[price_in_dollars, contract_count_fp]`.
  - Delta: `price_dollars`, `delta_fp` ("Fixed-point contract delta (2 decimals)"), `side`
    (`yes`/`no`), `ts_ms`, and `client_order_id` ("Present only when you caused this orderbook
    change").
- **Sequencing.** `seq` is a "Sequential number that should be checked if you want to guarantee
  you received all the messages. Used for snapshot/delta consistency"; `sid` identifies the
  subscription.
  - **The scope of `seq` is UNVERIFIED.** The pages do not say whether one counter runs per
    subscription across all the markets it carries, or per market.
    - `inplay_evidence` counts per subscription by default (`SeqScope.SUBSCRIPTION`). A gap on
      any market makes every book on that `sid` unusable until each is resynced.
    - A repeat of one (sid, seq) with a different message is a SEQ_SCOPE_CONFLICT, and every book
      on that `sid` fails closed.
    - **One market per subscription is the supported, safe mode:** both readings agree there.
      `SeqScope.MARKET` enforces it and refuses a `sid` that carries a second market.
    - Route A must verify the scope on its first recorded session before multiplexing markets.
  - The pages give **no explicit gap-recovery procedure**.
  - `update_subscription` supports `add_markets`, `delete_markets` and `get_snapshot`, so a
    fresh snapshot can be requested without resubscribing (search summary of the docs;
    INFERENCE that this is the intended resync path).
- **Limits.** No connection, subscription or message-rate limits are documented. Error code 27
  reads "Too many requests - The subscription exceeded its command rate limit". Error 25 is
  "Subscription buffer overflow".
- **Keepalive.** The docs cite library ping/pong handling and advise "reconnection with
  exponential backoff". No server heartbeat interval is documented.
- **Ticker channel (public).** It carries `yes_bid_dollars`, `yes_ask_dollars`, their sizes,
  `price_dollars` (last trade) and `ts_ms`, and "Updates sent whenever any ticker field changes".
  It is top of book only: it cannot reconstruct depth.

**API key scopes** (<https://docs.kalshi.com/api-reference/api-keys/generate-api-key>, read
2026-09-28):
- The documented scopes are `read`, `write`, `read::block_trade_accept`,
  `read::portfolio_balance`, `write::trade`, `write::transfer`, `write::fcm_risk` and
  `write::block_trade_accept`.
- A key "Defaults to full access (`read`, `write`) if not provided."
- **No market-data-only scope is documented.** The broad `read` parent grants all read
  endpoints, which includes account reads.

A stream credential would therefore carry at least account-read authority. That is a residual
permission. The owner directive does not authorize it (no credentials, no new account reads).

### 1.3 Create Order V2: sides, time in force, reduce-only, partial fills

Sources, read 2026-09-28:
- <https://docs.kalshi.com/api-reference/orders/create-order-v2>
- <https://docs.kalshi.com/getting_started/order_direction>

Read for semantics only. Market code never calls an order route, and
`tests/invariants/test_no_execution_paths.py` forbids it.

- **Side.** `side` is `bid` or `ask`, described as "buy YES" and "sell YES". The order-direction
  page maps sell YES to `outcome_side: no`, `book_side: ask`.
- **Netting (INFERENCE).** The positions endpoint describes `position_fp` as negative for NO
  and positive for YES (<https://docs.kalshi.com/api-reference/portfolio/get-positions>). That
  suggests one signed net position per market. The pages do not state that a sale of YES
  beyond the held quantity is refused, so **a sale can open NO exposure unless it is
  reduce-only**. UNVERIFIED on an account.
- **Counts and prices.** `count` is fixed-point with 0–2 decimals, minimum 0.01. `price` is
  fixed-point dollars with 2–4 decimals.
- **`time_in_force`:** `fill_or_kill`, `good_till_canceled`, `immediate_or_cancel`.
- **reduce_only.** "Orders with reduce_only set to true will be rejected unless time_in_force
  is immediate_or_cancel". **Reverified: reduce-only is IOC-only.**
  - Consequence: a resting take-profit sale (GTC) cannot be reduce-only. Inventory reservation is
    the only guard against over-selling with resting orders.
  - A GTC reduce-only take profit is **not** a supported combination and must not be proposed.
- **Other fields.**
  - `expiration_time` requires `good_till_canceled` and "cannot combine with
    immediate_or_cancel".
  - `post_only`, `cancel_order_on_pause`, `self_trade_prevention_type` (`taker_at_cross` |
    `maker`), `client_order_id` and `order_group_id` also exist.
- **Partial fills.** The response carries `fill_count` ("filled immediately") and
  `remaining_count`, plus `average_fill_price` and `average_fee_paid` when `fill_count > 0`.
  So an IOC can fill partially.
- HTTP 201 on success. Error codes include 409 and 429.

### 1.4 Maintenance and pauses

Source: <https://docs.kalshi.com/getting_started/maintenance_and_pauses> (read 2026-09-28).
- Scheduled maintenance runs "Every Thursday from 3:00 AM to 5:00 AM ET". NFL Sunday windows
  do not overlap it; Thursday Night Football does not either.
- **Trading pause:** placing and amending are blocked, and cancellation remains available.
- **Exchange pause:** placing, amending and cancelling are all blocked.
- In both, "Resting orders remain on the book (unless CancelOrderOnPause is set)".
  `cancel_order_on_pause` true cancels "when a trading or exchange pause begins".
- **Signalling.** The page names no pause message. `GET /exchange/status`
  (<https://docs.kalshi.com/api-reference/exchange/get-exchange-status>, `security: []`)
  returns:
  - `exchange_active`: "False if the core Kalshi exchange is no longer taking any state changes
    at all";
  - `trading_active`;
  - `exchange_estimated_resume_time`, "not guaranteed and can be extended".
- `inplay_evidence.trading_state` maps these fields. A missing field is UNKNOWN, never OPEN.
- Neither a stop rule nor cancel-on-pause guarantees an exit through a halt. Cancel-on-pause is
  not the same as detecting that our own feed is stale.

### 1.5 Game state: `game_stats` and `live_data`

Sources, read 2026-09-28:
- <https://docs.kalshi.com/api-reference/live-data/get-game-stats>
- <https://docs.kalshi.com/api-reference/live-data/get-live-data>

`game_stats`:
- Route: `GET /live_data/milestone/{milestone_id}/game_stats`, with `security: []`
  (documented as unauthenticated).
- Response: `pbp` → `periods` → `events`, where events are objects with unspecified
  `additionalProperties`. **Score, clock, possession, down/distance and field position are not
  enumerated.**
- Coverage: "Pro Football, College Football, Pro Basketball, …, Pro Hockey, and Pro Baseball".
- Nulls: "Returns null for unsupported milestone types or milestones without a Sportradar ID".
  - INFERENCE: the underlying provider is Sportradar.
  - Rights to the underlying data, the update cadence and latency are **not stated**.

`live_data`:
- Route: `GET /live_data/milestone/{milestone_id}`, with `security: []`.
- It returns `type`, `details` ("a flexible object") and `milestone_id`. No football fields are
  documented.

Contract consequence: `inplay_evidence.game_state_from_payload` reads **no** field until a
per-source `field_map` is verified against real payloads. A null payload is
UNSUPPORTED_OR_UNMAPPED.

### 1.6 Public REST order books

Sources, read 2026-09-28:
- <https://docs.kalshi.com/api-reference/market/get-market-orderbook>
- <https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks>
- <https://docs.kalshi.com/getting_started/orderbook_responses>

- `GET /markets/{ticker}/orderbook`, with `security: []`.
  - `depth` runs 0–100 ("0 or negative means all levels").
  - The response carries **no timestamp and no sequence number**.
- `GET /markets/orderbooks`, with `security: []`.
  - `tickers` takes up to 100 (maxItems 100).
  - There is **no depth parameter**. Whether all levels are returned is UNKNOWN, so a batch book
    is treated as possibly truncated.
- Books are bids only, as `[price_dollars, count_fp]` strings, "sorted by price in ascending
  order". Best YES ask = $1.00 − best NO bid.

### 1.7 Rate limits

Source: <https://docs.kalshi.com/getting_started/rate_limits> (read 2026-09-28).
- Authenticated tiers are token buckets. Basic is 200 read / 100 write tokens per second, and
  "most requests" cost 10 tokens.
- A limited request returns 429 with no cooldown penalty.
- **Unauthenticated limits are not documented.** The repository's own probe saw HTTP 429 at
  about 4 requests/s on the public host (`docs/DATA_PROVENANCE.md` §2, 2026-09-22).

### 1.8 The Odds API cadence

Source: <https://the-odds-api.com/sports-odds-data/update-intervals.html> (read 2026-09-28).

| Market | Pre-match interval | In-play interval |
|---|---|---|
| Featured markets | "60 seconds" | "40 seconds" |
| Additional markets | 60 s | 60 s |
| Betting exchanges | 20 s | 10 s |

"Six hours before an event's start time, the update interval begins decreasing" toward the
in-play value.

History (<https://the-odds-api.com/historical-odds-data/>): "From September 2022, historical odds
snapshots are available at 5 minute intervals". Whether in-play odds are in history is not
stated: UNKNOWN.

Polling faster than the upstream interval cannot create fresher information. In-play odds cost
credits, and the owner has not authorized additional Odds spending.

### 1.9 Rights: storage, training and derived data (UNRESOLVED; owner review needed)

**Kalshi Data Terms of Use.**
- Source: <https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf>, read
  2026-09-28, 51.1 KB, sha256
  `d19a0f94ffd65aa51eccb80cc8c9a06fb842478c5bf4cbd5a31ec51dd0a3966f`.
- The document is written about content "on the kalshi.com website". Short quotes:
  - "You may access content only for your personal use for non-commercial purposes."
  - Non-commercial use excludes, without "prior written consent", use "in connection with: (1)
    the development of any software program, including, but not limited to, training a machine
    learning or artificial intelligence system; or (2) providing archived or cached data sets
    containing Kalshi Data to another person or entity."
  - The prohibited-uses list includes "collecting, copying", "scraping, compiling (including,
    without limitation, through framing or systematic retrieval to create collections,
    compilations, databases or directories)" and "creating derivative works".
  - A clause prohibits use of Kalshi Data "in any manner for any machine learning and/or
    artificial intelligence".

**Kalshi Developer Agreement** (<https://kalshi.com/developer-agreement>, which governs API use):
- It returned **HTTP 429** on 2026-09-28, as it did on 2026-09-24
  (`docs/research/ACQUISITION_PORTFOLIO.md`). **Not read.**
- A secondary search summary says API use is "limited to facilitating a member's own trading".
  That is UNVERIFIED secondary text.

**Sportradar-derived game stats:** no rights statement found. UNKNOWN.

**Assessment.**
- Which terms govern the repository's API-collected Kalshi data is **UNRESOLVED**.
- The website Data Terms, if they applied, would restrict:
  - systematic collection into databases;
  - software development;
  - any AI/ML use.

  That would bear on this pilot and on the existing pregame collection and agent-assisted
  analysis.
- This record does not decide the question. It is flagged to the coordinator for the owner.
- The pilot's owner action (§6) includes reading the Developer Agreement.
- A candidate ninth question for the drafted Kalshi message: "Do the Data Terms of Use apply
  to data retrieved through the public API, and is private research storage and analysis
  (including with AI tools) of that data for the member's own trading permitted?" The
  coordinator owns `docs/research/KALSHI_QUESTIONS_2026-09-26.md`, so this is a suggestion
  only.

## 2. Minimum data contract (what the offline code now enforces)

Implemented offline in `src/edge_lab/inplay_evidence.py` (contract `inplay-evidence-v1`):
- **Books.** A book needs a valid start (a snapshot with `sid` and `seq`). Deltas apply only in
  sequence, counted per subscription across its markets by default. The scope is UNVERIFIED
  (§1.2), and one market per subscription is the supported, safe mode.
  - Duplicates are ignored and counted.
  - A gap or a foreign `sid` makes the book UNUSABLE until a new snapshot. v1 keeps no reorder
    buffer.
  - A negative level or a crossed book is UNUSABLE until resync.
- **Clocks.** Source (`ts_ms`), first-observed, receipt and processing times are kept apart and
  never substituted. A game clock is text, not UTC.
- **Game state** is append-only. A correction is a new linked observation, and
  `game_state_as_of` returns what had actually been seen at each instant.
- **Failures and coverage.** Failures are journalled beside the data. The coverage report counts
  usable, unusable-by-reason and silent time, and keeps every failure.
- **Transport.** The only transport is `read_journal`, which reads a local JSONL file. There is
  no socket and no HTTP.

Price-only exits need executable prices and sizes, rules, fees, inventory, market status and a
common horizon, and no game feed (§13). Game state is needed only for a state-aware policy, which
is UNSUPPORTED in v1.

## 3. Route comparison

| | **A: exchange stream** (`orderbook_delta`) | **B: bounded public REST sampling** | **C: premium feeds** |
|---|---|---|---|
| Resolution | Every book change, sequenced; reconstructable depth | One full snapshot per poll; nothing between polls | Push game events; vendor-dependent odds |
| Endpoint | `wss://external-api-ws.kalshi.com/trade-api/ws/v2`, channels `orderbook_delta` (+ `market_lifecycle_v2`, `trade`) | `GET /markets/orderbooks?tickers=…` (≤100 tickers), `GET /markets?event_ticker=`, `GET /exchange/status`, optional `GET /live_data/milestone/{id}/game_stats` | Sportradar NFL push + REST catch-up; commercial odds |
| Auth / enforced permission | Signed API key required; no market-data-only scope documented (`read` includes account reads) | None (`security: []`) | Contract and keys |
| Rights | Developer Agreement (unread, 429) + Data Terms question (§1.9) | Same Kalshi question | Vendor licence; not assessed |
| Cadence | Push on change | Proposed 5 s books, 30 s game state, 60 s status | Vendor |
| Volume per game (≈4 h 10 m window) | Messages UNKNOWN (no NFL measurement); estimate 10k–100k deltas × ~250 B ≈ 2.5–25 MB raw, ESTIMATE | ≈3,000 book GETs (one batch call covers both games' 4 markets) + ≈500 game-state + ≈250 market + ≈250 status ≈ **4,000 GETs**; books 1.4–4.2 KB per market (`CAPTURE_AND_BACKUP_APPROVAL_PLAN.md`) → ≈17–51 MB raw, stored only on change | Vendor |
| Reconnect / retry | Undocumented limits; exponential backoff; resync via `get_snapshot`; book UNUSABLE until then | No retry on 429: double the interval for 5 min; stop after 5 consecutive or 20 total 429s | Vendor catch-up API |
| CPU / memory | One long-lived process; small | One long-lived poller; small; `MemoryMax=256M`, `CPUQuota=15%` proposed | — |
| Storage / backup | Journal file outside the evidence DB; not in the nightly backup set | Same: its own SQLite/JSONL under a pilot directory, excluded from the nightly backup, one manual verified copy after review (O1 path) | — |
| Cost | Free (data) | Free | Paid; not authorized |
| Limitations | Needs a credential and account-read scope: not authorized; channel listed "private" | Sampling misses intra-poll moves, so touches and through-fills are sampled; no seq, no venue timestamp; batch depth undocumented; shares the public IP rate limit with pregame collectors | Cost; no measured need; a feed ahead of TV is not a sync reference |

## 4. Recommendation

**Recommended route: B, bounded public REST sampling, for a source-quality pilot only.**
- No credential, account scope or paid service is needed.
- It exercises the same evidence contract (`rest_snapshot`, coverage, failures), and the replay
  already refuses to interpolate between samples.
- It answers the first questions cheaply: book continuity, change frequency between polls,
  game-state nulls, and pregame-collector interference.

**Single fallback: A, the exchange stream.** It becomes the next step only if B's acceptance
criteria show that 5 s sampling cannot support price-only exit replay. For example: most
consecutive polls differ, or the p99 receipt gap exceeds 15 s. It needs, first:
- owner approval of a credential whose documented scope includes account reads;
- a security review of key handling on the VPS;
- the rights question answered.

**Route C is not justified.** Price-only exits need no game feed. The free `game_stats` route
can be measured first, and no measurement shows missing value that a paid feed would supply.

## 5. What the pilot is not

- It is not an experiment and not a profitability test.
- It is not an approved game count or request budget, and not an extension of the 295-request
  pregame approval.
- It is not EXP-002 data. No pilot book, price or game state may enter EXP-002's features,
  labels, markouts or windows.

## 6. Proposed source-quality pilot: **PROPOSED, NOT APPROVED**

| Item | Proposal |
|---|---|
| Pilot id | `inplay-source-pilot-1` (an operations id, not an experiment id) |
| Question | Can bounded public REST sampling give a usable, well-covered KXNFLGAME in-play book record, and what does `game_stats` return, without disturbing protected jobs? |
| Game-selection rule (ex ante, outcome-blind) | Evaluated on the Friday before, from KXNFLGAME events already listed by the existing pregame discovery (no new requests). Eligible games have a scheduled **Sunday 1:00 PM ET** kickoff and both team markets `active`. Choose the **two eligible games with the lexicographically smallest Kalshi event tickers**. Record the list and the rule's output in the pilot record before kickoff. No choice by line, spread, team or expected volatility. |
| Games / concurrency | 1–2 games, both in the same 1:00 PM ET slot; one poller process; one batch book request covers all four team markets |
| Start | Kickoff − 10 min |
| Stop | 10 min after both markets leave `active` (closed or determined) or `game_stats` reports final, whichever is first |
| Overtime | Continue through overtime up to the hard stop. A game unfinished at the hard stop is recorded as truncated (INCOMPLETE), never extended |
| Hard stop | **17:15 America/New_York**, a 30-minute margin before EXP-001's 17:45 PFM job (`edgelab-pfm.timer`), plus `RuntimeMaxSec=4h30m` |
| Cadence | Books every 5 s (one batch GET), `game_stats` every 30 s per game, market list every 60 s, exchange status every 60 s |
| Hard caps | 4,500 GETs per game-slot in total; 20 total 429s or 5 consecutive → stop; 200 MB on disk; refuse to start with < 2 GB free; `MemoryMax=256M`, `CPUQuota=15%`, `Nice=10`, `edgelab.slice` |
| Isolation (EXP-001 and pregame collectors) | Separate unit and user-owned pilot directory. The pilot never opens the evidence DB (`edge_lab.sqlite3`) or the ledger. It never waits on the collectors' host locks (`edge_lab.sqlite3.forward.lock`, the observe capture lock), so it cannot block them. It yields to them instead: a non-blocking probe finds a lock held, and the pilot skips that poll cycle, recorded as `YIELDED`, so the pregame captures keep the host's request budget. The pregame T-60m captures for these games (about 12:00 ET) finish before the pilot starts. No change to any existing timer, cap or quota |
| Shutdown switch | Starts only if `/etc/market-edge-lab/inplay_pilot.enable` exists and names this pilot id and an expiry date. Removing the file stops the poller at the next cycle, and `systemctl stop` stops it immediately. Manually started unit, **no timer** |
| Credentials / owner action | No credential. The owner (1) approves this pilot and its request volume; (2) reads the Developer Agreement and decides the rights question (§1.9); (3) starts and stops the unit or delegates that explicitly |
| Data role | `OPERATIONAL` source-quality evidence. May later be `DEVELOPMENT` for replay engineering (latency, gap and fill-rule behaviour). Never a holdout or evaluation set. Nothing from it enters EXP-002 |
| Review date | The Monday after the pilot Sunday. Earliest pilot Sunday **2026-10-18** (the recorder, review and CI come first); fallback 2026-10-25 |
| Quality acceptance | (1) ≥ 95% of 5 s polls from kickoff to final return parseable, non-crossed books for every market; (2) p99 receipt gap ≤ 15 s and max ≤ 60 s outside documented pauses; (3) ≤ 3 HTTP 429s in total and none consecutive; (4) the pregame collectors show zero missed targets and no 429s in the window, and EXP-001's 17:45 job starts on time; (5) storage and memory stay inside the caps; (6) a coverage report with every failure retained; (7) the fraction of consecutive polls whose book changed is reported (an undersampling proxy that decides between B and A); (8) `game_stats`: the null or non-null fraction and the fields actually present. All-null counts as UNSUPPORTED, a valid result |
| Outputs | A source-quality verdict (`USABLE_FOR_PRICE_ONLY_REPLAY` / `NEEDS_STREAM` / `NOT_USABLE`) with the coverage report. **No economic or edge claim** |
| Build needed before approval can be used | A recorder that writes `inplay-journal-v1` JSONL (file-only output, transport behind an explicit enable flag, tests with a fake opener), reviewed, CI green on its exact head. Not built in PR B |

## 7. Research-slot proposal (not a claim of a slot)

- **Registry today.**
  - Registered: EXP-001 (protected, legacy), EXP-002 (family A, ACTIVE) and EXP-003 (family B;
    the protocol says ACTIVE, and the owner decision of 2026-09-26 says PAUSED).
  - EXP-900 is reserved for unit tests.
  - `MAX_ACTIVE_FAMILIES = 2`.
- **Transition needed.** An in-play evaluation (family C, "in-play position management: exit
  value versus holding") cannot become ACTIVE without either:
  - (a) a recorded transition of EXP-003's slot out of ACTIVE (QUEUED or ENDED) by an owner
    decision under `docs/owner/`; or
  - (b) an explicit `owner_exception`.

  EXP-003's pause does not free the slot automatically.
- **Experiment id.** To be allocated from the registry at the time of the decision, as the
  lowest unused non-reserved id. **Not assumed to be EXP-004.**
- **Proposed budget (separate from EXP-002's).**
  - $0 research cash, because public data only.
  - 1 owner hour for pilot approval and review, plus 1 owner hour for a later protocol review.
  - 0 Odds credits.
- **Evidence roles.**
  - Pilot games: OPERATIONAL, then at most DEVELOPMENT.
  - Synthetic and fixture cohorts: DEVELOPMENT (tests).
  - A prospective evaluation window starting after a freeze: HOLDOUT, used once.
- **Permitted uses.** Source-quality metrics, replay engineering and a later preregistered
  hold-versus-exit comparison.
- **Prohibited uses.**
  - EXP-002 features, labels or windows.
  - Annualized figures.
  - Edge or after-cost claims while KXNFLGAME fees are unverified (Kalshi Q7). The replay
    enforces this: `after_cost_claim` is False under a NONE fee basis.

## 8. Unknowns carried forward

- Whether a key without account scopes can open the stream or subscribe to `orderbook_delta`.
- The rights question (§1.9).
- Batch-orderbook depth.
- The unauthenticated rate limit.
- `game_stats` fields, latency and coverage for NFL.
- Whether Auto Sell orders are reduce-only or cancel on pause.
- Account-level netting of a YES sale beyond holdings.
- KXNFLGAME maker and taker fee applicability (Q7). Settlement fee (Q6).
