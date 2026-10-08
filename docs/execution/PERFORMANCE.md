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
| `python -m pytest tests/execution/test_chaos.py tests/execution/test_chaos_kill.py tests/execution/test_load.py` | the default (small) suite, part of normal CI | @@DEFAULT_TIME@@ |
| `EDGE_LAB_CHAOS_SCALE=full python -m pytest tests/execution/test_load.py -s` | 2,000-cycle latency and memory passes, full read-ceiling sweep | @@FULL_LOAD_TIME@@ |
| `EDGE_LAB_CHAOS_SCALE=full python -m pytest tests/execution/test_chaos.py tests/execution/test_chaos_kill.py` | 25 seeds per seeded chaos test, every commit point of the disk-full sweep, 60 + 60 kill seeds | @@FULL_CHAOS_TIME@@ |

Knobs (each an integer environment variable; `EDGE_LAB_CHAOS_SCALE=full` sets them all to the full value):

| Variable | Default | Full | Used by |
|---|---|---|---|
| `EDGE_LAB_CHAOS_SEEDS` | 3 | 25 | seeded chaos tests (locked journal, clock jitter, HTTP mix, lease races) |
| `EDGE_LAB_DISK_POINTS` | 6 sampled | all 32 | commit points of the disk-full sweep |
| `EDGE_LAB_KILL_SEEDS` | 4 (+2 before-send, +2 after-send) | 60 (+30, +30) | process-kill tests |
| `EDGE_LAB_LOAD_CYCLES` | 120 | 2,000 | latency pass |
| `EDGE_LAB_MEMORY_CYCLES` | 60 | 2,000 | `tracemalloc` pass |
| `EDGE_LAB_PERF_OUT` | unset | a path | appends every measurement as one JSON line |

`-s` prints every measurement as JSON. Load tests assert bounds (queue, intents, requests, records and events per
cycle; a memory leak bound), never speed, so a slow CI machine cannot fail them; the only timing assertion is a 5 s
sanity bound on p99 cycle time.

## Hardware and software

@@HARDWARE@@

The laptop is shared: other agent sessions and test runs were active at times, so tail latencies (p99, max) include
contention. Medians are the more stable figures. No GPU, network or provider is involved.

## Declared load profile

- 3 markets of one event (`KXHIGHNY-26OCT08-B70/B72/B74`), one account, one synthetic strategy (no edge), BOUNDED_AUTO
  inside a test-issued grant with the harness's explicit TEST limits (`tests/execution/test_orchestrator_harness.py`).
- A cycle every 60 s of fixture time. Per cycle: fresh liquidity on each market (NO side with probability 0.6, YES
  side 0.5); ENTRY signals drawn from (0, 0, 1); 35% of entries GTC one tick inside the ask, the rest IOC at the ask;
  25% of IOCs race a competitor who lifts one contract first; an EXIT of up to 3 held contracts with probability 0.2.
- Bounds (`CycleBounds`): 20 queued signals, 6 drained, 10 proposals and 3 intents per cycle, 80 requests per cycle,
  30 s deadline, 10 min signal validity. The risk gate's ticket limit allows 8 orders per 10 minutes.
- A process restart at each quarter of the run (boot time against history).
- Workload seed 2026; the chaos tests record their seeds in their parametrization.

## Results

@@RESULTS@@

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

@@FINDINGS@@

## Limits of this evidence

- The fake venue is not Kalshi. It has no settlement of its own, no historical tier movement, no rate limiting and no
  network. Its order and fill listings always return the full history.
- Single-threaded. Concurrency is modelled as separate journal connections and processes on one machine, as the
  orchestrator is designed (no threads); no real network partitions.
- Kill points are journal commits and venue writes; a kill inside SQLite's own write path is covered by SQLite's
  atomic commit, not by these tests.
- Latencies are Windows NVMe with `synchronous=FULL` on a shared laptop; Linux CI and the VPS will differ. Re-measure
  on the deployment host before any capacity decision (package O).
