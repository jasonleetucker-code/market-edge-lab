# Learning-history coverage audit (issue #50)

**Audit date:** 2026-09-24.
**Code audited:** `origin/main` at `cbfbddf`, plus this branch's Odds API changes. Those
changes are marked **(this PR)**.
**Authority:** owner directive `docs/owner/2026-09-24-next-build-chunk-directive.md`,
Deliverable 7.

This audit reads the code and the store schemas, not the documentation. For every domain,
source and process it answers one question: what would a later analysis find, and what is lost
for good unless it is captured now? It extends `docs/DATA_PROVENANCE.md` §6c and replaces
nothing there. It creates no second store. Every fix below reuses `snapshots`,
`forward_captures`, `source_health`, the append-only shadow ledger or the Odds API target
tables.

## Legend

**Cell states:**
- **STORED:** kept durably, with a pointer to where.
- **PARTIAL:** some of the item is kept (the cell says what is missing).
- **MISSING:** not kept.
- **N/A:** the process does not produce this item by design.

**Gap classes:**
- **P0:** prospective. Lost for good unless it is collected now.
- **P1:** can be rebuilt later from stored raw evidence or from a public archive that keeps
  history.
- **P2:** nice to have, bounded or low value.

**Stores referred to:**
- **Evidence store:** `edge_lab.storage`, SQLite schema v5, with the tables `snapshots`,
  `document_*`, `source_health`, `collection_runs`, `forward_captures`,
  `odds_capture_targets` and `odds_capture_transitions`.
- **Shadow ledger:** `edge_lab.shadow_ledger`, table `ledger_entries`, with entry kinds
  `decision`, `fill` and `settlement`.
- **Status directory:** `shadow_daily.json`, `latest.json`, `notifications.jsonl` and
  `ntfy_relay.jsonl`.
- **Odds quota ledger and runner state:** `odds_quota_ledger.json` and `*.pilot.json`.

## Summary matrix

| Domain / process | RAW | MARKET | MODEL | DECISION | SIZING | EXECUTION | OUTCOME | LATER MARKET | OPERATIONS |
|---|---|---|---|---|---|---|---|---|---|
| EXP-001 weather capture (forward pfm / decision / recheck) | STORED (source ts PARTIAL) | STORED | N/A | N/A | N/A | N/A | N/A | **PARTIAL → P0-1** | STORED |
| Shadow decisions (both accounts) | STORED by reference | STORED | STORED (feature version PARTIAL, P1) | STORED (code SHA **P0-2**; risk verdict for rejects P1) | STORED for qualified; N/A for rejects (P1) | N/A | see settlement | **MISSING → P0-1** | PARTIAL (**P0-2**) |
| Shadow fills | STORED by reference | STORED | STORED by reference | STORED | STORED | STORED (slippage N/A by model) | see settlement | MISSING → P0-1 | STORED |
| Settlement | STORED | STORED | N/A | N/A | N/A | N/A | STORED for held positions; **MISSING for rejected-only events (P1)** | N/A | STORED (receipt P0-2) |
| Notifications | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | PARTIAL (P2) |
| Polymarket US | MISSING (not collected) | adapter only | N/A | N/A | N/A | N/A | MISSING | MISSING | MISSING (P2, deferred) |
| Novig public data | MISSING (not collected) | adapter only | N/A | N/A | N/A | N/A | N/A | N/A | MISSING (P1) |
| The Odds API NFL pilot (not yet keyed) | STORED | STORED | N/A | N/A (never executable) | N/A | N/A | MISSING (P1) | STORED (T-24h / T-6h / T-60m) | STORED **(this PR)** |
| Best-price comparator | not persisted (P1) | from inputs | N/A | not persisted (P1) | N/A | N/A | N/A | N/A | N/A |
| Sizing (operational v1 and research v2) | N/A | N/A | N/A | N/A | v1 STORED; v2 research only (P1) | N/A | N/A | N/A | N/A |

## Domain detail

### 1. EXP-001 weather capture (`edge_lab.forward`; timers pfm 17:45, decision 17:55, recheck 18:05 ET)

| Category | Item | State | Where / why |
|---|---|---|---|
| RAW | payload | STORED | `snapshots.payload_json`, the canonical JSON of the decoded response. Sources: `nws_pfm` (`pfm_list`, `pfm_product`) and `kalshi` (`event`, `markets`, `orderbook`), through `forward._save` |
| RAW | hash | STORED | `payload_sha256` (canonical) and `raw_sha256` (exact response bytes) |
| RAW | source timestamp | PARTIAL | `snapshots.source_timestamp_utc` is NULL, because `forward._save` does not set it. The source times are inside the payload: PFM issuance time in the product text, Kalshi `updated_time` in each market. The Kalshi orderbook has none. P2: it can be re-derived from the payload |
| RAW | receipt timestamp | STORED | `snapshots.fetched_at_utc` |
| RAW | source / code version | STORED | `parser_version` and `schema_version` per snapshot, and `forward_captures.code_version` (`EDGE_LAB_CODE_VERSION`) |
| MARKET | event, market, outcome | STORED | event and markets snapshots, and `forward_captures.event_ticker` |
| MARKET | rules identity | STORED | the markets snapshot carries `rules_primary` and `rules_secondary` as returned |
| MARKET | executable quote, depth, venue | STORED | an orderbook snapshot per open bracket (`BOOK_DEPTH = 100`) inside [decision − 5 min, decision] |
| LATER MARKET | re-check | STORED | the `recheck` phase, 10–15 min after each bracket's decision book |
| LATER MARKET | +1 h, +6 h, pre-close, close, before settlement | **MISSING, P0-1** | nothing captures a Kalshi book or market after the re-check. **Verified:** `forward.py` has exactly the three phases, and no timer runs later |
| OPERATIONS | failed or partial capture | STORED | `forward_captures.status` / `reasons_json` (complete, partial, failed, rejected_out_of_window, …). The pfm phase also writes a `source_health` row. Kalshi phases write only `forward_captures`, which is enough |
| OPERATIONS | day validity | STORED (derived) | `forward.day_status` re-derives VALID or INVALID from the evidence. `latest.json` is overwritten, but P1 |

### 2. Shadow decisions (`exp001_shadow.run_day` → ledger `decision` rows, research and operational accounts)

| Category | Item | State | Where / why |
|---|---|---|---|
| RAW | evidence | STORED by reference | `quote_evidence_ids` point to `snapshots.id`, and the `opportunity` dict holds `quote_received_at_utc` |
| MARKET | event, market, outcome, side, cluster | STORED | `event_id`, `market_id`, `side`, `outcome_cluster` and `opportunity.outcome` |
| MARKET | executable quote | STORED | `opportunity.executable_price` and `displayed_size`, with the snapshot id |
| MARKET | depth | STORED by reference | the full book snapshot |
| MODEL | model id and version | STORED | `model_version`, `opportunity.model_id` and `opportunity.engine_version` |
| MODEL | raw and conservative p | STORED | `opportunity.model_probability` and `conservative_probability` |
| MODEL | uncertainty | PARTIAL | only this side's conservative bound is a field. The full `ProbabilityBounds` is not stored. P1: rebuildable from the frozen model and the stored forecast |
| MODEL | feature / dataset version | PARTIAL, P1 | `ModelEstimate.input_version` (the forecast product SHA-256) is folded into the `opportunity_id` hash but is not its own field. The frozen availability rule re-selects it from the stored PFM snapshots |
| DECISION | threshold | STORED by reference | `policy_id`. The numeric `min_net_edge` lives in versioned code (EXP-001 is frozen). P1 |
| DECISION | qualification, rejection, every reason | STORED | `qualification`, `reason`, `reasons` and `opportunity.details`. All 12 decisions of 2026-09-24 were recorded, 10 of them rejected (DATA_PROVENANCE §6c) |
| DECISION | freshness, fee claim basis | STORED | `opportunity.book_freshness`, `model_freshness` and `freshness`, plus `fee_fields(...)` (fee verification status and claim basis) |
| DECISION | capital-horizon verdict | STORED (operational account) | `decision.starter_policy` from 2026-09-24T00:00Z, for qualified and rejected decisions alike. N/A for the research account by design |
| DECISION | risk verdict | PARTIAL, P1 | evaluated only at fill time, for qualified operational candidates (`fill.risk_veto`). A rejected decision has none, but `ShadowLedger.state_as_of` replays the account at the decision time, so it can be re-derived |
| DECISION | code version (git SHA) | **MISSING, P0-2** | `EDGE_LAB_CODE_VERSION` reaches only the daily receipt (`daily.run(code_version=...)`), and that receipt is overwritten on every run. The ledger row keeps `engine_version`, `model_version` and `policy_id`, but not the deployed SHA |
| SIZING | operational policy, recommendation, binding | STORED | `decision.sizing`: `SizingResult.to_dict()` with `policy_id`, raw, risk-adjusted, liquidity-capped and final size, `binding_constraint` and limits. For the research account it is `FROZEN_RULE_ONE_CONTRACT` |
| SIZING | rejected opportunities | N/A by design (P1) | `sizing = None` when REJECT. Counterfactual sizing is Deliverable 1 (Lane A), a replay that never writes the ledger |
| LATER MARKET | anything after the re-check | **MISSING, P0-1** | see §1 |

### 3. Shadow fills (ledger `fill` rows)

| Category | Item | State | Where |
|---|---|---|---|
| EXECUTION | fill or no-fill and why | STORED | `status`, `reason`: FILLED, or NO_FILL with RISK_VETO, STARTER_POLICY_INELIGIBLE, INSUFFICIENT_CASH, RESEARCH_INVALID_CASH or STAGE_B_DAY_INVALID, plus the latency-policy reasons |
| EXECUTION | entry price, fees | STORED | `price`, `fee`, `total_cost` and fee verification fields |
| EXECUTION | latency | STORED | `fill_policy_id` (`latency-confirmed-v1`), the `latency` window, `decision_as_of_utc`, `filled_at_utc` and `confirmation_evidence_id` |
| EXECUTION | slippage | N/A by model | the fill model enters at the decision ask, confirmed by the re-check book. No slippage is simulated. The confirming book is stored, so a different model can be replayed (P1) |
| DECISION | risk veto detail, capital horizon at fill | STORED | `risk_veto` (binding limit, value, limit, breaches) and `starter_policy` |

### 4. Settlement (`daily._refresh` → `kalshi.refresh_event_settlements`; timer 11:15 and 16:15 ET)

| Category | Item | State | Where / why |
|---|---|---|---|
| RAW | settlement evidence | STORED | `kalshi_settlement` snapshots, with a `source_health` row per refresh |
| OUTCOME | positions held | STORED | ledger `settlement` rows: outcome, evidence snapshot id, `evidence_available_utc`, reported settlement time and resolver. Payout and P&L are computed by `replay` from the fill, never taken from input |
| OUTCOME | rejected-only events | **MISSING, P1** | **Verified:** `daily.pending_event_tickers` lists only events with an open position, so venue results are never fetched for events we only rejected. Two archives keep this history, so it is P1, not P0. Kalshi's public API keeps serving settled markets (the Gate 3 bulk fixture `kalshi_markets_all_2026-09-22.json.gz` proves this). The NWS CLI products that settle KXHIGHNY are archived with corrections by IEM AFOS (`iem_afos_clinyc`, PLANNED). The routine `edge-lab collect` job (`nws_cli_central_park`) has no timer on the VPS, so no NWS CLI is captured prospectively. Recommendation: a bounded manual or scheduled backfill of settled KXHIGHNY markets per closed capture day. It is not urgent, because the history does not expire |
| OPERATIONS | refresh outcome | STORED / **P0-2** | `source_health` and `collection_runs` rows are durable. The receipt's `settlement.refresh`, `pending` and `conflicts` are overwritten on the next run |

### 5. Notifications (`edge_lab.notifications`, `notify_ntfy`)

| Category | Item | State | Where / why |
|---|---|---|---|
| OPERATIONS | events and delivery attempts | PARTIAL, P2 | `notifications.jsonl` rotates at 1 MB into one `.1` file, which is itself overwritten. Older history is lost. That is months of events at today's volume. The events are derived from receipts, so fixing P0-2 makes them rebuildable |
| OPERATIONS | event origin (production, test, deployment verification, …) | MISSING, P2 here | this is Deliverable 5 (Lane C). Once an event is written without an origin, the origin can only be inferred later (from `TEST` event types or deploy times) |

### 6. Polymarket US (`edge_lab.polymarket_us`, source `polymarket_us_public` PLANNED, `collected_by=()`)

The adapter, fixtures and one manual smoke read exist. **Nothing is collected**, so there is no
catalog, book, rules or settlement history. The prospective books that are not captured are lost
(order books have no public history).

It is classified **P2 (deferred)** rather than P0 for two reasons. No Polymarket US market has
been shown to be rule-equivalent to a market we evaluate (`discovery.is_equivalent`; rules are
unresolved and fees are an UNVERIFIED estimate). A collector would also need owner authorization
for a new timer.

It becomes P0 on the day an equivalent market is identified. At that point the capture must
record the same fields as §1 (book at decision, re-check and the P0-1 phases; rules hash;
`MarketTiming`).

### 7. Novig public data (`edge_lab.novig_data`, `novig_public_data` PLANNED)

It holds end-of-day CSVs of trades and markets, never quotes, and nothing is collected. Novig
publishes one immutable file per trading day and lists every date in `index.json`, so history
can be fetched later: **P1**. The risk is that Novig stops hosting old days, which its docs do
not promise. A daily mirror would need a timer (owner decision) and is not proposed now.

### 8. The Odds API NFL pilot (`odds_api`, `odds_pilot`, `odds_schedule`; ADR 0029; no key installed)

These fields are verified by fixture tests in `tests/test_odds_readiness.py`, test
`test_repeated_captures_are_kept_as_a_time_series_with_every_contract_field`.

| Category | Item | State | Where |
|---|---|---|---|
| RAW | payload, hash, receipt ts, versions | STORED | an `odds` snapshot per paid call, holding the provider body, `raw_sha256`, `payload_sha256`, `fetched_at_utc`, `parser_version` and `schema_version` |
| RAW | request identity (redacted) | STORED | `snapshots.url` (`apiKey=REDACTED`) and `payload.request`: markets, regions, commence window, slot, and targets with their intended times |
| RAW | source timestamp | STORED | `bookmakers[].last_update` and `markets[].last_update` in the body |
| RAW | quota metadata | STORED | `payload.quota_headers` (the allowlisted `x-requests-*`) and `odds_capture_transitions.credits_last` |
| MARKET | event identity | STORED | provider event id, `sport_key`, `sport_title`, home, away and `commence_time` in the body. Discovery snapshots keep the schedule's history. `odds_api.observation_identity` / `link_series` **(this PR)** link repeated observations only when every identity field matches. Distinct events are never collapsed, and conflicts and reschedules are reported |
| MARKET | book, market, side, line, offered odds | STORED | body `bookmakers[].markets[].outcomes[]` (`name`, `point`, `price`, kept raw) |
| MARKET | executable quote, depth | N/A | offered sportsbook odds are never executable (tested). No `ExecutableQuote` is built, and a forged one still cannot qualify |
| MODEL | implied / de-vigged / consensus | derived (P1) | `implied_probability`, `devig_by_market` and `consensus_by_market` **(this PR)** are recomputed from stored bodies. Each is labelled RESEARCH_ONLY and non-executable |
| DECISION, SIZING, EXECUTION | — | N/A | the pilot makes no decisions |
| OUTCOME | final scores | MISSING, P1 | not captured. NFL results are permanently public. The provider's `/scores` endpoint costs credits and is not in the approved plan |
| LATER MARKET | line history | STORED | captures at T-24h, T-6h and T-60m, each with the intended target time, deviation and lead minutes (`odds_capture_transitions.detail_json`). T-60m is the **latest pre-close observation**, not the closing line. P2: a nearer capture (for example T-15m) needs ADR 0029's reconsider rule |
| OPERATIONS | missed, skipped, deferred and failed targets | STORED | append-only `odds_capture_transitions` with reasons: MISSED, SKIPPED_BUDGET, DEFERRED, FAILED, QUOTA_* and SETUP_NEEDED |
| OPERATIONS | partial coverage | STORED | per-target `detail_json`: `event_present`, `bookmakers`, `markets` and `missing_markets` |
| OPERATIONS | failed discovery / capture calls | STORED **(this PR, was P0-3)** | a `source_health` row for every network call: discovery, capture and smoke, with the error redacted. Before this PR a failed discovery or a KEY_REJECTED lived only in the overwritten `*.pilot.json` |
| OPERATIONS | quota event history | PARTIAL, P2 | the quota ledger keeps its last 200 events. Counters survive, and every paid call's headers are also in its snapshot |

### 9. Best-price comparator (`edge_lab.best_price`, ADR 0027)

There is no production caller, and `compare()` results are not persisted. Its inputs are the
ladders, market rules and fee evidence. When they are stored (today: Kalshi books only), a
comparison can be replayed deterministically: **P1**. It is **P2** until a second venue's books
are collected (see §6). The Terminal comparator UI (Deliverable 3) must show only the
engine's result for a stated evidence set, never a figure computed in the UI.

### 10. Sizing

- **Operational v1** (`sizing.py`, `EXP-001-fixed-1-v1`): stored in `decision.sizing`, see §2.
- **Research v2** (`sizing_v2`, `sizing_eval`, ADR 0026): writes versioned study outputs to
  `experiments/sizing_v2/results/` and, by design, never writes the ledger.
- **Counterfactual policies A–H per decision** (Deliverable 1): not stored yet. They are
  **P1**, because the ledger holds every input the replay needs:
  - every decision, including rejected ones, with its opportunity, prices, sizes and times;
  - `state_as_of`, for point-in-time bankroll and exposure;
  - settlement with its knowledge time.

## Gap register

| Id | Gap | Class | Exact fix | New timer? | Owner lane |
|---|---|---|---|---|---|
| **P0-1** | No Kalshi book, top-of-book or market payload after the +10–15 min re-check, for any evaluated bracket (qualified or rejected). Pre-close and close depth cannot be rebuilt. Kalshi's public candlestick and trade history may rebuild an OHLC top-of-book path, but the repo has no adapter or evidence for that, so treat it as lost | P0 | Deliverable 4: a general observation capture reusing `forward._save` / `fetch_json_result` and `SnapshotStore.save_snapshot`. Phases: `decision`, `recheck`, `post_decision_1h`, `post_decision_6h`, `pre_close`, `close`, `settlement_preceding` and `custom`. Each observation links `decision_id`, `market_id`, side and phase, plus the intended time, the receipt time, the snapshot id and the market's `close_time` from the stored market payload. It is labelled "latest pre-close observation" unless it falls at or after `close_time`. Build now: CLI, manual capture, tests and a runbook with volume estimates | **Yes (owner decision).** Proposed: +1 h and +6 h after the decision (19:00 and 00:00 ET), `pre_close` = `close_time` − 15 min, and `close`, for every bracket evaluated that day. Until approved, manual capture only | Lane E |
| **P0-2** | The daily receipt `shadow_daily.json` is replaced on every run (`daily._write_receipt`, `os.replace`). It is the only record of each run's code SHA (`EDGE_LAB_CODE_VERSION`), settlement refresh status and errors, `missing_capture_days`, problems and state. The journal keeps stdout for a bounded time only | P0 | Also append every receipt, as one line, to an append-only `<status_dir>/shadow_daily_history.jsonl`, written before the atomic replace, fsynced and never rotated away (or rotated into dated files). **Do not** add the SHA to ledger decision payloads: EXP-001 is frozen, and a re-run with different content raises `LedgerConflict` | No | Lane E (`daily.py`) |
| **P0-3** | Odds API discovery failures and key rejection lived only in the overwritten `*.pilot.json` | P0 | `source_health` row per network call through the existing `record_source_health` | No | **Fixed in this PR** (Lane D) |
| P1-1 | Venue settlement for rejected-only events | P1 | Bounded backfill of settled KXHIGHNY markets per closed capture day, through the `kalshi_settlement` write path. Optionally activate `iem_afos_clinyc` | Optional | later |
| P1-2 | The feature / forecast version is not its own decision field | P1 | Re-derive with the frozen availability rule. A future (non-frozen) experiment should store `input_version` as a field | No | next experiment |
| P1-3 | Risk verdict for rejected decisions | P1 | Counterfactual replay with `state_as_of` (Deliverable 1) | No | Lane A |
| P1-4 | Counterfactual sizing for every decision | P1 | Deliverable 1 `CounterfactualSizingRun` | No | Lane A |
| P1-5 | NFL final scores for the Odds API series | P1 | Join public results at analysis time. Paid `/scores` stays out of the budget | No | later |
| P1-6 | Novig daily files | P1 | Fetch on demand. Mirror only with a timer approval | Optional | later |
| P1-7 | Comparator results | P1 | Replay from stored ladders | No | Lane B UI shows the engine only |
| P2-1 | `snapshots.source_timestamp_utc` is empty for forward captures | P2 | Parse at analysis time (PFM issuance, Kalshi `updated_time`) | No | — |
| P2-2 | Notification outbox keeps two rotations. No origin field | P2 | Deliverable 5 (origin), plus dated rotation instead of overwrite | No | Lane C |
| P2-3 | Odds quota ledger keeps 200 events | P2 | Per-call headers already in snapshots | No | — |
| P2-4 | Polymarket US and Novig not collected | P2 (deferred) | Becomes P0 when a rule-equivalent market is identified. Needs a collector timer (owner decision) | Yes, later | — |
| P2-5 | Status files and outbox are not in the backup bundle (`backup.py` covers evidence and ledger) | P2 | Include `shadow_daily_history.jsonl` once P0-2 exists | No | Lane E |
| P2-6 | The Odds API "close" is T-60m | P2 | ADR 0029's reconsider rule | Owner | — |

## The two known gaps, verified in code

1. **Later and closing prices are not captured.** Confirmed. `forward.py` defines the phases
   `pfm`, `decision` and `recheck` only. `deploy/vps/systemd/` has no later capture timer, and
   nothing else reads Kalshi books. This is P0-1.
2. **Venue settlement is fetched only for events we hold.** Confirmed.
   `daily.pending_event_tickers` builds the list from `ledger.state(...).open_positions()`, and
   `_refresh` passes only those tickers. This is P1-1, not P0: Kalshi and IEM keep the history.

## Other findings

- **The daily receipt** is overwritten (P0-2).
- **The Odds API:** failures were not in the evidence store (P0-3, fixed). An out-of-order quota
  reading from two concurrent calls could be mistaken for a provider reset and hand back spent
  credits. This was found by the new concurrency test and fixed in `QuotaLedger._apply_headers`
  **(this PR)**. Every idle tick re-planned every known target, one database connection each.
  Only new targets are planned now **(this PR)**.

## Domain acceptance (issue #50, the ten questions)

A domain is research-ready only when this document's table for it has no open P0.

| Domain | Status |
|---|---|
| EXP-001 weather | not yet research-complete. P0-1 and P0-2 are open |
| The Odds API pilot | complete for its scope once keyed. Scores are P1 |
| Polymarket US | discovery and display integrations only |
| Novig | discovery and display integrations only |

Re-run this audit whenever a new source, timer or decision path is added.
