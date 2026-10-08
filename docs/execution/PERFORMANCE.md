# Execution chaos, performance and regression results (#160 package P)

**Status:** TESTED_LOCALLY on the owner's laptop (below). FIXTURE only: synthetic workload, in-memory fake venue,
disposable SQLite journals, no network, no provider stress. Nothing here is a statistical claim, a venue latency or
an edge; the numbers describe this code on this machine under the declared synthetic workload.

**Scope.** Package P of `docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md`: prove bounded behaviour under synthetic
bursts and faults against the real merged components (orchestrator, journal, reservations, lifecycle, control, risk
gate, account reads, and the real transport with a fixture signer and rate budget where a test says so).

## How to run

| Command | What it runs | Time here |
|---|---|---|
| `python -m pytest tests/execution/test_chaos.py tests/execution/test_chaos_kill.py tests/execution/test_load.py` | the default (small) suite, part of normal CI | about 50 s (`tests/execution` + `tests/invariants`: 100 s, against 53 s before package P) |
| `EDGE_LAB_CHAOS_SCALE=full python -m pytest tests/execution/test_load.py -s` | 2,000-cycle latency pass, 500-cycle memory pass, full read-ceiling sweep | about 25 min (latency pass about 13 min, the rest 12 min) |
| `EDGE_LAB_CHAOS_SCALE=full python -m pytest tests/execution/test_chaos.py tests/execution/test_chaos_kill.py` | 25 seeds per seeded chaos test, every commit point of the disk-full sweep, 60 + 30 + 30 kill seeds | about 4 min (226 s) |

Knobs (each an integer environment variable; `EDGE_LAB_CHAOS_SCALE=full` sets them all to the full value):

| Variable | Default | Full | Used by |
|---|---|---|---|
| `EDGE_LAB_CHAOS_SEEDS` | 3 | 25 | seeded chaos tests (locked journal, clock jitter, HTTP mix, lease races) |
| `EDGE_LAB_DISK_POINTS` | 6 sampled | all 32 | commit points of the disk-full sweep |
| `EDGE_LAB_KILL_SEEDS` | 4 (+2 before-send, +2 after-send) | 60 (+30, +30) | process-kill tests |
| `EDGE_LAB_LOAD_CYCLES` | 120 | 2,000 | latency pass |
| `EDGE_LAB_MEMORY_CYCLES` | 60 | 500 | `tracemalloc` pass (12-frame tracebacks make it slow; set it to 2000 explicitly if needed) |
| `EDGE_LAB_PERF_OUT` | unset | a path | appends every measurement as one JSON line |

`-s` prints every measurement as JSON. Load tests assert bounds (queue, intents, requests, records and events per
cycle; a memory leak bound), never speed, so a slow CI machine cannot fail them; the only timing assertion is a 5 s
sanity bound on p99 cycle time.

## Hardware and software

| | |
|---|---|
| Machine | HP Pavilion Plus Laptop 14t-ew100 |
| CPU | Intel Core Ultra 7 155H, 16 cores / 22 threads, 3.8 GHz max |
| Memory | 31.5 GB |
| Disk | Micron MTFDKBA512QFM NVMe SSD, 512 GB |
| OS | Windows 11 Home 10.0.26200 |
| Python | 3.12.10 (64-bit) |
| SQLite | 3.49.1; the journal runs WAL with `synchronous=FULL` |
| Branch | `exec/p-chaos` on `origin/main` 1afe37f |
| Measured | 2026-10-07, 22:45-23:55 local time |

The laptop is shared: other agent sessions and test runs were active at times, so tail latencies (p99, max) include
contention. Medians are the more stable figures. No GPU, network or provider is involved.

## Declared load profile

- 3 markets of one event (`KXHIGHNY-26OCT08-B70/B72/B74`), one account, one synthetic strategy (no edge), BOUNDED_AUTO
  inside a test-issued grant. TEST limits only: the harness's (`tests/execution/test_orchestrator_harness.py`) with the
  loss limits, the daily new-risk limit, the grant's turnover and loss limits and the grant's lifetime widened
  (`LOAD_POLICY`, `LOAD_GRANT` in `test_load.py`) and venue cash of $10,000, so that 2,000 cycles (33 hours of fixture
  time) keep sending instead of stopping at a daily limit (the synthetic strategy pays the spread on every round trip).
  Position, event, cluster and portfolio caps and the order rate are the harness's. These are not owner limits.
- A cycle every 60 s of fixture time. Per cycle: fresh liquidity on each market (NO side with probability 0.6, YES
  side 0.5); ENTRY signals drawn from (0, 0, 1); 35% of entries GTC one tick inside the ask, the rest IOC at the ask;
  25% of IOCs race a competitor who lifts one contract first; an EXIT of up to 3 held contracts with probability 0.5.
- Bounds (`CycleBounds`): 20 queued signals, 6 drained, 10 proposals and 3 intents per cycle, 80 requests per cycle,
  30 s deadline, 10 min signal validity. The risk gate's ticket limit allows 8 orders per 10 minutes.
- A process restart at each quarter of the run (boot time against history).
- Workload seed 2026; the chaos tests record their seeds in their parametrization.

## Results

All figures are from one seeded run each (`EDGE_LAB_CHAOS_SCALE=full`, `EDGE_LAB_PERF_OUT`), except where a column
says otherwise. Latencies are in milliseconds, nearest-rank percentiles.

### Declared workload, 2,000 cycles (33 hours of fixture time)

Bounds (asserted on every cycle) against what was measured:

| Quantity | Bound | Measured |
|---|---|---|
| queued signals (depth before a cycle) | 20 | max 2 |
| intents sent per cycle | 3 | 0 in 932 cycles, 1 in 963, 2 in 105; never 3 |
| network requests per cycle | 80 | 19 to 29 in the first quarter, up to 65 in the last (it grows with history, below) |
| control events and records per cycle | 50 | max 10 |
| journal events per cycle | 200 | max 31, mean 12.7 |
| reconciliation | COMPLETE every cycle | COMPLETE in all 2,000 |

Flow: 1,173 orders sent (298, 289, 283 and 303 per quarter), 1,375 venue fills. Blocked decisions by first reason:
TRADE_COUNT_LIMIT 110, ARBITRATION_ONE_INTENT_PER_MARKET 92, BOOK_DEPTH_INSUFFICIENT 89, EXPOSURE_PER_MARKET 28.

| Latency (ms) | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| whole cycle | 2,000 | 194.9 | 446.1 | 567.9 | 881.2 |
| whole cycle, excluding the fake venue behind `send` | 2,000 | 95.2 | 201.8 | 316.1 | 615.7 |
| decision (`_decide`, gate to recorded reply) | 1,400 | 29.1 | 62.7 | 137.5 | 526.8 |
| prepare, send and record one order | 1,173 | 23.3 | 48.4 | 142.6 | 517.2 |
| journal write (one BEGIN IMMEDIATE ... COMMIT) | 23,368 | 1.65 | 4.13 | 23.9 | 496.2 |
| risk gate (`evaluate` / `revalidate`) | 2,800 | 4.16 | 12.7 | 20.4 | 44.5 |
| risk projection (`project_account`) | 1,400 | 0.22 | 0.50 | 0.75 | 1.27 |
| fake venue per request (harness) | 80,743 | 2.16 | 6.86 | 15.6 | 53.6 |

The same workload over its first 150 cycles (the default-sized run): cycle p50 30.4 ms (p99 92.7), decision p50
21.5, journal write p50 1.79, risk gate p50 0.60, projection p50 0.11. The difference is history (below), not load.

Growth:

| Quantity | Measured |
|---|---|
| journal size | 22.8 MB after 2,000 cycles (checkpointed): about 11.4 KB per cycle, 845 bytes per event (27,006 events) |
| restart (boot) time | 146 ms at 6,814 events, 231 ms at 13,558, 481 ms at 20,087 |
| decision p50, first vs last quarter | 21.0 ms vs 39.0 ms |
| account-read requests per cycle | 19-29 (first quarter) to 65 (last quarter); the ceiling is 80 (read ceiling below) |
| Python memory, everything traced (`tracemalloc`, 500 cycles) | +7.2 KB per cycle (fake venue and harness included) |
| Python memory allocated by the execution package and still held | +2.4 KB per cycle (155.7 KB at cycle 50, 1.25 MB at cycle 500); asserted under 64 KB per cycle |

The package's retained growth is by design and linear in history: the planned-intent index (`model.py:123`, `:117`
Decimals; `orchestrator.py:412` intents rebuilt at restart; `journal.py:980` records read at restart), the control
state's audit log that is never trimmed (`control.py:382`), and the P&L ledger. About 2.4 KB per cycle is about 3.5 MB
a day at one cycle a minute.

### Signal burst at 10 times the queue bound

200 signals arrive in each of 5 cycles (1,000 in all), then none. 44 are admitted and 956 refused at admission with
QUEUE_FULL; the queue is at its bound of 20 before each burst cycle and never above it; 6 are drained per cycle; the
backlog is gone 3 cycles after the burst ends (bound: ceil(20 / 6) = 4); at most 20 records per cycle (bound 50).
`submit_signal` p50 0.011 ms, p99 0.96 ms (a refusal writes nothing; an admission writes one record).

### Rate budget exhausted (real `RateBudget`, basic tier, 30% reserved, 10 tokens a request)

Ordinary traffic sharing the account's budget drains 42 reads and 7 writes; 18 reads and 3 writes remain for
PROTECTIVE requests. With the clock stopped (no refill): the account read (17 requests) completes COMPLETE on the
reserve; the new order is NOT_SENT and nothing reaches the venue; a second read in the same window does not fit (one
request left) and the cycle FAILS and disarms; the shutdown cancel of our resting order is CANCEL_CONFIRMED on the
write reserve. After refill, the unsent order is resolved ABSENT.

### Read ceiling

Every cycle reads the whole account history (orders and fills, twice for stability). History placed at the venue as
filled manual orders (one fill each), plus our probe order:

| History (orders, each with one fill) | Requests | Reconciliation | Cycle |
|---|---|---|---|
| 1 | 18 | COMPLETE | 27 ms |
| 601 | 41 | COMPLETE | 111 ms |
| 1,201 | 65 | COMPLETE | 237 ms |
| 1,501 | 77 | COMPLETE | 317 ms |
| 1,601 | 80 (budget) | PARTIAL: DISARMED before any decision, nothing sent | 382 ms |

## Chaos coverage

Every scenario asserts the global invariants after every step (`chaos_support.check_invariants`):

1. no venue order without a prepared attempt (a probe reads the journal file at the moment each create reaches the
   venue);
2. at most one attempt per intent key, and no client order id reaches the venue twice;
3. the journal never records more fills than the venue (every reservation, released ones included);
4. positions reconcile (venue positions equal the fills' net; a COMPLETE snapshot equals what the venue served);
5. no reservation is released without confirmation (a REJECTED/ABSENT release follows a receipt-backed attempt
   outcome; any other release follows BOUND with a receipt and names a later snapshot; no released order rests);
6. `verify_chain` is OK;
7. replaying the stored control events, every incident leaves the controller DISARMED, only an accepted arm leaves
   DISARMED, every attempt was prepared while the replayed mode was a sending mode, and the live orchestrator's state
   equals the replay.

| Fault | Test | Expected and observed |
|---|---|---|
| Disk full (SQLITE_FULL just before COMMIT) at sampled or every commit of a busy cycle, persistent or one-off | `test_a_full_disk_at_any_commit_of_a_cycle_fails_loud_and_recovers` | the cycle raises `JournalUnavailable` or ends with an incident; nothing half-written; after space returns, a restart (or the same instance) reconciles every attempt, none re-sent |
| Real SQLITE_FULL (`PRAGMA max_page_count`) mid-run | `test_a_real_sqlite_full_error_fails_the_cycle_loud_and_a_restart_recovers` | as above |
| Journal locked by a second connection before a cycle | `test_a_journal_locked_before_the_cycle_fails_it_loud_with_nothing_read_or_sent` | `JournalBusy` at the lease renewal, before any request; the same instance carries on afterwards |
| Journal locked at a seeded request mid-cycle | `test_a_journal_locked_mid_cycle_loses_nothing` | `JournalBusy`; an order already sent becomes unknown and is reconciled, never re-sent |
| Process kill (`os._exit`) at a uniformly drawn commit or send point; restart | `test_chaos_kill.py` | restart is DISARMED; the store satisfies every invariant before the first cycle; every attempt is reconciled; 60 + 30 + 30 seeds at full scale |
| Our clock jumps back 1 h / 30 s, forward 10 min / 2 days | `test_a_jumping_clock_fails_closed_and_recovers_after_it_is_fixed` | the venue's user-data timestamp disagrees, reconciliation is not COMPLETE, the controller disarms and nothing is sent; re-armed once the clock is right |
| Clock jitter of up to 3 s each way every cycle | `test_clock_jitter_within_tolerance_keeps_every_invariant` | normal operation (but see P-3) |
| HTTP 429, 5xx before/after the venue acted, timeouts before/after, malformed 2xx, 409, through the real transport | `test_every_http_write_failure_is_unknown_never_retried_and_reconciled` | each create is OUTCOME_UNKNOWN, sent once, and resolved ABSENT when the venue never acted, ACKNOWLEDGED when it did |
| Seeded mixes of every write fault and read faults (429, 503, timeouts, malformed pages) | `test_a_seeded_mix_of_http_errors_holds_every_invariant` | invariants hold; every attempt reconciled once the network heals |
| Duplicated fills, reversed pages, stale order rows, crossed create replies (with or without client id) | `test_duplicate_and_out_of_order_receipts_keep_every_invariant` | duplicates collapse and order does not matter (COMPLETE, no incident); stale rows are detected from the second stale read on; crossed acks become unknown and are reconciled |
| 60 markets, a signal on each every cycle | `test_many_markets_at_once_stay_inside_every_bound` | one intent per market, at most 3 per cycle, the queue and request bounds and the order-rate limit hold |
| Lease takeovers at seeded points; stalled workers wake up | `test_lease_takeovers_at_random_points_never_double_send` | a fenced-out worker reads only: no journal row, no send; the live worker reconciles everything |
| Request budget exhausted mid-send | `test_a_request_budget_exhausted_mid_send_blocks_the_rest_and_disarms` | the rest are BLOCKED `REQUEST_BUDGET_EXHAUSTED`; budget incident; DISARMED |
| A read that overruns the cycle deadline | `test_a_read_that_overruns_the_deadline_disarms_and_sends_nothing` | not COMPLETE; DISARMED; no decision |
| Signal burst at 10x the queue bound | `test_a_signal_burst_far_above_the_bounds_keeps_the_backlog_bounded` | see Results |
| Rate budget exhausted by ordinary traffic | `test_reserved_cancel_and_reconcile_headroom_survive_an_exhausted_rate_budget` | see Results |
| History beyond what one read can cover | `test_the_account_read_ceiling_fails_closed` | see Results |

## Bugs found

Each is an `xfail(strict=True)` test in `tests/execution/test_chaos.py` with the reason in `BUG_P1`..`BUG_P3`. No
source file was changed by package P.

**P-1. A refused second start rewrites the live worker's control log.** `Orchestrator.__init__` persists `Started`
(`control.boot`) before `acquire_lease`, which then raises `LeaseHeld` because another worker holds the lease. The
live worker never applies that `Started`, so the stored control log now replays to DISARMED, its next `ArmAccepted`
replays as STALE_DECISION, and the store says DISARMED while the live worker keeps sending. Test:
`test_bug_a_refused_second_start_does_not_rewrite_the_live_workers_control_log` (invariant 7). Suggested direction:
take the lease before the first control write, or make control appends check the fence.

**P-2. A worker fenced out mid-send still writes.** If a worker stalls inside `send` for longer than `lease_ttl` and
another worker takes the lease over, the stalled worker's `_record_reply` fails (its attempt is now OUTCOME_UNKNOWN,
correctly), and it then records a DECISION and raises an `IncidentRaised` into the control log before its next
`_lease_held()` check. `_check_writer` only reads a flag set at phase boundaries, and control events and records are
not fenced in the journal. The new holder's live state then differs from the store's replay, as in P-1. Test:
`test_bug_a_worker_fenced_out_mid_send_writes_nothing_after_the_takeover`. Suggested direction: fence control appends
in the journal (as `prepare_attempt` is), or re-check the lease before every write.

**P-3. Fills just before a read can be counted twice.** `Orchestrator._fold_order` labels the listing's cumulative
fill count with `snapshot.observed_at_utc` = min(read start, the venue's user-data `as_of`). That time is earlier
than the moment the listing was read. The lifecycle adds fills stamped more than `TIMESTAMP_SKEW` (2 s) after the
label on top of the count, but the count already includes them, so `record_fill` writes more fills than the venue
has. It triggers when the venue's user-data timestamp lags by more than 2 s (`account.py` accepts up to
`max_data_lag` = 1 min) or our clock trails the venue's by 2 to 5 s (`account.py` tolerates `CLOCK_SKEW` = 5 s).
Observed: the journal records 6 filled for a venue fill of 3; the reservation goes BOUND while the order still rests;
the next read is not COMPLETE (attribution mismatch) and a lifecycle quarantine follows, so it fails closed within one
or two cycles, but invariant 3 is broken in between. Test:
`test_bug_the_journal_never_records_more_fills_than_the_venue_near_a_read` (both triggers). The harness hides it
because its venue stamps trail our clock by 10 minutes.

## Other findings (not bugs; for the owner and later packages)

1. **Every cycle reads the whole account history.** `account.reconcile_account` reads every live and historical order
   and fill page, and the live tier at least twice for stability. Requests per cycle therefore grow by about 2 per 100
   orders and 2 per 100 fills: 18 at no history, 65 at 1,200 orders and fills, and past the cycle budget of 80 between
   1,500 and 1,600 orders with one fill each. Past that point the read is PARTIAL every cycle and the controller stays
   DISARMED. That fails closed, but it is a hard capacity ceiling. Cycle time grows the same way (27 ms to 382 ms in
   the read-ceiling test). It needs an incremental or windowed reconciliation, or a deliberate budget, before any
   long-lived account. That is a design decision for packages G and K, not a P fix.
2. **The rate-budget reserve covers one small read.** The basic tier's 30% reserve is 18 read requests and 3 writes.
   A complete account read costs 17 requests at small history, so after ordinary traffic exhausts the budget one
   reconcile fits per refill window and a second does not. Once history needs more pages (finding 1), even one read
   no longer fits in the reserve. The reserve fraction, the tier and the read's size should be decided together.
3. **Protective priority is the caller's glue.** The orchestrator calls `send(request)` with no priority. Reads and
   cancels get the reserve only if the caller's `send` picks `Priority.PROTECTIVE` for
   `request.endpoint.value.protective` (as `HttpVenue` does; `account.py` documents it). Wiring `send=transport.send`
   directly would make reconciliation reads and shutdown cancels ORDINARY. Package O's wiring must pin this with a
   test.
4. **NOT_SENT and 429 are treated as unknown.** The transport says THROTTLED (429) or NOT_SENT (local budget) when
   nothing was executed; the orchestrator records OUTCOME_UNKNOWN for anything but OK or REJECTED. That is safe (the
   order is later resolved ABSENT and never re-sent), but the reservation stays held for at least
   `NOT_FOUND_MIN_DELAY` (30 s) and one complete read.
5. **Decision and risk-gate time grow with history.** The risk gate p50 went from 0.6 ms (150 cycles) to 4.2 ms
   (2,000 cycles), and decision p50 from 21 to 39 ms. `Orchestrator._order_history` and `_projection` pass every
   planned intent and attempt ever made (in memory, not from the database) on every decision. That is linear, small
   at this scale, and worth a bound later.
6. **Decision latency is mostly fsync.** Five or six journal commits per sent order (planned record, prepare,
   receipt, sent, acknowledged, decision record) at `synchronous=FULL`, 1.6 ms p50 each here, are most of the 23 ms to
   prepare, send and record an order. The p99 journal write (24 ms) and its max (0.5 s) are disk and contention tails
   on this shared laptop.
7. **Restart cost grows with history.** Boot replays every control event and record: 146 ms at 6,800 events, 481 ms
   at 20,000. That is acceptable for a supervised restart. At about 13 events per cycle it is roughly 0.9 s after a day
   at one cycle a minute.
8. **A stale order listing is accepted once.** A venue that serves an older version of every order row is not
   detectable in the first such read (it looks like a listing that lags its fills); from the second read the
   attribution mismatch makes it PARTIAL and the controller disarms. No invariant broke.
9. **Clock faults fail closed.** With the venue's own clock modelled separately, every jump of our clock (back 30 s
   or 1 h, forward 10 min or 2 days) makes the user-data timestamp disagree. Reconciliation is then PARTIAL, the
   controller disarms and nothing is sent until the clock is right. The harness's default venue derives its user-data
   timestamp from our clock, which hides clock faults; `ChaosAdapter.skew` separates them.

## Limits of this evidence

- The fake venue is not Kalshi. It has no settlement of its own, no historical tier movement, no rate limiting and no
  network. Its order and fill listings always return the full history.
- Single-threaded. Concurrency is modelled as separate journal connections and processes on one machine, as the
  orchestrator is designed (no threads); no real network partitions.
- Kill points are journal commits and venue writes; a kill inside SQLite's own write path is covered by SQLite's
  atomic commit, not by these tests.
- Latencies are Windows NVMe with `synchronous=FULL` on a shared laptop; Linux CI and the VPS will differ. Re-measure
  on the deployment host before any capacity decision (package O).
