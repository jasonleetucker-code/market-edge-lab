# ADR 0030: Later and closing price observations (scheduled Option A)

**Status:** Accepted 2026-09-24; schedule approved 2026-09-24 11:24 ET. Original authority:
`docs/owner/2026-09-24-next-build-chunk-directive.md`, Deliverable 4 (later/closing price capture)
and Deliverable 7 (issue #50 P0 storage fixes). That directive authorized manual capture only.
The owner subsequently approved scheduled capture in chat and issue #74 records the durable decision.
**Option A below is selected:** two bounded, non-persistent timers in the existing `edgelab.slice`.
This remains read-only evidence collection; it authorizes no execution, credentials or paid service.

## Problem

Issue #50 asks whether our filters saved money or filtered out good trades. That needs, for every
evaluated market (qualified **and** rejected), the executable price after the decision and near the
close. Today the evidence stops at the +10-15 min re-check (`docs/DATA_PROVENANCE.md` §6c, gap 2). A
later price exists only when it is observed; a missed moment is lost for good.

"Closing price" is easy to overclaim. A book fetched "around" the close is not the close. A venue can
close a market early or extend it, and a public book carries no sequence number.

## Alternatives

1. **Snapshots only, no new tables.** Store the extra books as snapshots and derive everything later.
   Rejected as the only record: intended times and misses would not be stored, so a missed capture
   would be indistinguishable from one never planned, and "close" could not be tied to its proof.
2. **Re-evaluate the opportunity at later times.** Rejected: EXP-001 is frozen, and a later
   evaluation is not a decision. Observations are prices, never decisions.
3. **Additive tables for targets and observations; raw payloads stay in `snapshots`.** Chosen.
4. **Sports-only (Odds API) capture.** Rejected: the owner asked for a general mechanism. The Odds API
   keeps its own game-relative targets (ADR 0029); offered odds are never executable prices.

## Decision

### Phases

| phase | intended time | how |
|---|---|---|
| `decision` | decision time (EXP-001: 18:00 ET on D-1) | backfilled from the forward decision capture's own book snapshot (no request) |
| `recheck` | the re-check window (decision book + 10-15 min) | backfilled from the forward re-check capture; that capture reads books only, so its rows carry no market status, close time or rules hash (the target detail names the decision capture that holds the market record) |
| `post_decision_1h` | decision + 1 h | captured |
| `post_decision_6h` | decision + 6 h | captured |
| `pre_close` | trading close - 15 min (or a documented reference time) | captured |
| `close` | trading close - 30 s, only where the venue defines a trading close | captured and labelled (below) |
| `settlement_preceding` | expected resolution - 30 min, when that is after the close | captured: lifecycle state, rules hash |
| `custom` | an operator-chosen time (`observe plan --custom-...`) | captured |

Due windows: every phase is due from 5 min before its time until 30 min after it, except:
- `pre_close` must be received by close - 2 min;
- `close` is due from 2 min before its aim until close - 10 s.

A post-decision target that would fall after close - 2 min is not planned, and the plan report
lists it with `AFTER_TRADING_CLOSE`.

Targets that would run inside a protected window are moved out of it: to the window's end, or to
just before the window when the end is too close to the close. The move is recorded in
`shifted_out_of_protected_window`. The close target is never moved.

### Close semantics, per venue (`price_observations.CLOSE_SEMANTICS`)

A close-phase observation is labelled **`CLOSE`** only when the source proves it is the last executable
quote before the defined trading close, up to a stated tolerance. Otherwise it is labelled
**`LATEST_PRE_CLOSE`** ("latest pre-close observation") and stores the conditions that failed.

**Definition (coordinator decision, 2026-09-24).** The public Kalshi book has no sequence number or
update time, so "the close" here means **the last executable quote observed within 60 s before the
source-confirmed trading close**. The stored enum stays `CLOSE`, and every proof stores the
tolerance. The human label is always "close (within 60 s of trading close)", never a bare "close",
and `market_history` exposes `close_tolerance_s`.

- **Kalshi** (`kalshi_close_time_v1`). The trading close is the market's `close_time`. Markets may close
  early (`can_close_early`), so the time is re-read at capture. `CLOSE` requires all of:
  1. a market read just before the book shows the market `active`/`open`, with the planned
     `close_time`;
  2. the book was received in [`close_time` - 60 s, `close_time`). The public book has no sequence
     number or update time, so "last" is proven only to within 60 s. The tolerance is stored in the
     proof;
  3. a market read received after `close_time` shows the market no longer open, with the same
     `close_time`: no extension, no earlier halt.

  Other outcomes:
  - A book received at or after `close_time` is not a pre-close quote at all. It is `NOT_EXECUTABLE`:
    the snapshot is kept and the prices are dropped.
  - A book request that would start after close - 10 s is not sent (`MISSED`, `TOO_LATE_FOR_CLOSE`).
  - A moved `close_time` makes the old pre-close and close targets `MISSED` (`CLOSE_TIME_CHANGED`).
    The next plan re-targets them from the newly observed close.
- **Polymarket US** (`polymarket_us_no_documented_close_v1`). The documentation defines no trading
  close. `endDate` is only a "market end/expiration date", and `assetPriceTerms.windowEnd` ends a
  measurement window. So no close target is ever planned, and nothing is ever `CLOSE`.
  - A pre-close target may use `windowEnd` as its reference, and its detail says so.
  - Lifecycle comes from the book's `state`. Anything but `MARKET_STATE_OPEN` is `NOT_EXECUTABLE`.

`market_history` additionally marks, per side, the last captured quote before the latest known close
time (`is_latest_pre_close_observation`). CLV-style metrics come later. A price move after a decision
is not proof of profit.

### Stored per observation (schema v6)

`price_observation_targets` holds one immutable row per intended observation:
- identity: venue, normalized and native market and event ids, phase;
- timing: **intended target time**, due window, planned-at time;
- policy version and origin (`ledger_decision`, `forward_capture_backfill`, `manual`);
- the decision reference (decision ids, qualifications with reasons) and its as-of time;
- the close time and basis, and the planned rules hash.

`price_observations` holds one append-only row per attempt and side (YES/NO), or one market-level
row when nothing side-specific exists (FAILED, MISSED, market not open):
- identity: event id, market id, side, venue, native market id;
- times: **target phase time**, **actual receipt time**, source timestamp (Polymarket
  `transactTime`; Kalshi publishes none);
- prices: bid, ask and the size at the ask, as the venue's decimal strings. Missing stays NULL;
- depth: the full captured ask ladder, with its truncation flag and depth limit;
- the market's price grid (ADR 0023);
- freshness for the phase: fresh inside the due window, stale outside it, unknown without a time;
- market status and close time as the source stated them;
- the close label and its proof;
- **rules hash** (the rules identity and version);
- the snapshot id and the payload's SHA-256 (the raw bytes' hash);
- collection status (`CAPTURED`, `NOT_EXECUTABLE`, `FAILED`, `MISSED`) and the miss reason.

**Raw payloads reuse the immutable snapshot store.** Kalshi books and listings go through
`forward._save` (source `kalshi`, kinds `markets`/`orderbook`, exactly as the forward captures).
Polymarket US books go through `save_snapshot` (source `polymarket_us`, kind `book`). Nothing is forked.

**Invariants, enforced by CHECK constraints and triggers:**
- a `CAPTURED` row names its side, snapshot and receipt time, and explains nothing;
- every other row says why;
- only `CAPTURED` rows carry prices;
- a captured close row is labelled, and `CLOSE` needs its proof;
- targets and observations cannot be updated, deleted or replaced;
- a target that reached a final status (`CAPTURED`, `NOT_EXECUTABLE`, `MISSED`) takes no further
  attempt. `FAILED` may be retried until its deadline, then becomes `MISSED` with the last failure
  as its reason;
- re-planning keeps the original target row.

### Planner (`edge-lab observe plan`)

- **Input.** The shadow ledger's recorded decisions, opened read-only: every account, both sides,
  QUALIFY and REJECT alike, within 7 days. They are grouped per market and decision time. The venue
  timing comes from the market record in the decision capture the decision was evaluated from, or
  from the latest observed close time.
- **Output.**
  - Persistent targets.
  - `decision`/`recheck` observations backfilled from the forward captures' own snapshots.
  - Every overdue open target marked `MISSED` with its reason, for example
    `NOT_CAPTURED_BY_DEADLINE ... under scheduled ADR0030_OPTION_A` or
    `PLANNED_AFTER_DEADLINE`.
- **No network.** Idempotent. It takes the same collector lock, so it also refuses to run inside a
  protected window (below).
- **Idle writes nothing.** When nothing is new and nothing is overdue, it stops after the lock and a
  read-only open. It writes no collection run and no row.
- **Existing store only.** It never creates or migrates a store at an arbitrary path (`NO_STORE`).
- **Shared targets.** Two decisions on one market share their targets, which are planned once.
  Every attempt id is unique.

### Capture (`edge-lab observe capture`)

One bounded, locked, idempotent run:
- **Protected windows.** It refuses to start, with no network and no writes (`DEFERRED_PROTECTED_WINDOW`),
  when [now, now + 4 min] overlaps a protected window:
  - 17:40-18:50 ET: the EXP-001 capture window of 17:40-18:35, plus the 18:40 shadow run;
  - 11:13-11:30 ET and 16:13-16:30 ET: the settlement runs.

  The reason is that these runs take the same collector lock with a 60 s timeout, and a busy lock
  would fail them.
- **Lock.** It takes the collector lock `<db>.forward.lock` with a 5 s timeout. That is one Kalshi
  pacing budget per host, shared with the forward captures. A busy lock gives `LOCK_BUSY`, exit 0,
  and nothing is done.
- **Kalshi requests.**
  - One event listing per event and phase (`/markets?event_ticker=`, at most 2 pages);
  - one order book per open market (`depth=100`);
  - for the close, one confirming listing after `close_time`.

  All go through the shared `kalshi.PACER` (0.6 s).
- **Polymarket US requests.** One public book per market (0.5 s pacer).
- **Bounds.** At most 24 markets, 40 GETs (each with the fetch layer's 2 bounded retries) and 4
  minutes, close waits included. Targets beyond a bound stay `PLANNED` and are listed as deferred.
- **Idempotency.** A second run in the same window finds its targets final and sends nothing.
- **Exit code.** 1 when an attempt `FAILED` (a future timer would alert), else 0.

`edge-lab observe status [--market ID]` is read-only (`SnapshotStore.open_readonly`).

### Read-only display contract for Terminal v1 (Lane B)

`price_observations.market_history(store, market_id) -> list[dict]`:
- **Input.** A read-only store is enough.
- **Rows.** One dict per observation row, plus one `PLANNED` dict per target not yet attempted,
  ordered by intended time.
- **Keys.**
  - identity: `observation_id`, `target_id`, `phase`, `label`, `side`, `venue`, `market_id`,
    `native_market_id`, `event_id`;
  - times: `target_utc`, `observed_at_utc`, `deviation_s`, `source_timestamp_utc`;
  - prices: `bid`, `ask`, `ask_size` (decimal strings), `depth`, `price_grid`;
  - state: `freshness`, `market_status`, `close_time_utc`, `close_label`, `close_proof`, `close_tolerance_s`
    (60 for a proven `CLOSE`, else None);
  - evidence: `rules_sha256`, `snapshot_id`, `source_sha256`;
  - outcome: `collection_status`, `miss_reason`, `executable`, `is_latest_pre_close_observation`.
- **`label`.** The phase, except for the close phase: "close (within 60 s of trading close)" for a
  proven `CLOSE` (never a bare "close"), else "latest pre-close observation".
- **Prohibitions.** Never a midpoint, a last price or an order. The UI does no arithmetic on it.

This change is backend-only. Terminal v1 shows nothing new until Lane B builds a panel under
`docs/design/UI_CONTRACT.md`, including its empty, stale, error and blocked states.

### Storage: schema v6, additive and forward-only (same discipline as v5)

- **What v6 adds.** Two tables with their indexes and triggers. No trigger touches an older table.
- **Migration.** Transactional: the additive steps land in one `BEGIN IMMEDIATE` transaction, and
  the version is stamped only after every object exists. An already complete store takes no write
  lock at open.
- **Rollback.** v5 code refuses a v6 store, so rollback stamps it first:
  `python -m edge_lab.storage mark-v5-for-rollback --db ...`. The helper is generalized as
  `mark_schema_for_rollback`. It refuses anything but a complete, intact v6 store. Going back past
  ADR 0029 runs `mark-v4-for-rollback` next.
- **Tests** (`tests/test_storage_rollback.py`) prove that:
  - the real v5 code (commit `cbfbddf`, extracted with `git archive`) refuses the v6 store, and
    after the stamp opens it read/write and read-only and reports `VERIFIED_BACKUP_AND_RESTORE`;
  - the real v4 code (`dd3ab4d`) does the same after both stamps;
  - re-installing v6 keeps every row, and a v6 backup is VERIFIED.

### Issue #50 P0-2 in the same change: the daily receipt history

`edge_lab.daily` replaced `shadow_daily.json` on every run, which lost each run's provenance:
`code_version`, refresh status and errors, missing days and problems.
- Each receipt is now also appended, before the atomic replace, as one JSON line to
  `<status_dir>/shadow_daily_history.jsonl`. The file is opened in append mode only, fsynced,
  mode 0644 like the receipt, and never truncated or rotated by code.
- Growth: a few KB per run, about 3 runs a day, so roughly 10-30 KB a day (a few MB a year).
- The receipt's content, state and exit code are unchanged (tested).
- Ledger decision payloads are untouched: EXP-001 is frozen, and a new payload field would raise
  `LedgerConflict` on re-run.

The #50 audit (Lane D) reclassified "venue settlement for rejected-only events" as **P1**. Kalshi
settled markets remain retrievable, and the gate3 bulk fixture proves it. So the settlement refresh
selection is **not** changed here.

## Scheduled capture policy — owner approved

The owner approved scheduled later/closing-price capture on 2026-09-24 at 11:24 ET. The implementation
uses **Option A**, because it is the general, venue-extensible schedule already reviewed here. Both timers
are `Persistent=false`: a missed point-in-time tick is never replayed late, and expired targets remain
honest `MISSED` evidence.

**Selected option A: two timers in the `edgelab.slice`.**

1. `edgelab-observe.timer`: `OnCalendar=*-*-* *:05/15:00 America/New_York`, i.e. :05, :20, :35 and
   :50 each hour, running `edge-lab observe plan --ledger ... && edge-lab observe capture`.
   - Plan is local; capture makes network requests only when a target is due, and refuses the
     protected windows itself.
   - It covers every non-close phase of any venue: +1 h, +6 h, pre-close, settlement-preceding and
     custom.
2. `edgelab-observe-close.timer`: `OnCalendar=*-*-* 04:57:45 UTC`, running `edge-lab observe capture`.
   - It lands inside the KXHIGHNY close window. The committed fixture shows close_time `05:00:00Z`,
     which is 00:00 EST or 01:00 EDT. The capture waits to close - 30 s, then confirms after the close.
   - It acts only when a close target is due. A market family with another close time needs its own
     entry, or a finer tick.

**Option B (EXP-001 only):** five fixed times:
- 19:05 ET (+1 h);
- 00:05 ET (+6 h);
- 04:47 UTC (pre-close);
- 04:57:45 UTC (close);
- 14:35 ET (settlement-preceding).

It makes the same requests, with fewer idle runs, but it covers no other market family.

**Requests and resources (EXP-001, 6 brackets per day; payload sizes from the committed fixtures: event
listing 17 KB, book about 1.5 KB):**

| run | GETs | stored |
|---|---|---|
| +1 h (19:00 ET) | 1 listing + 6 books = 7 | about 26 KB |
| +6 h (00:00 ET) | 7 | about 26 KB |
| pre-close (close - 15 min) | 7 | about 26 KB |
| close (close - 30 s, confirm at close + 5 s) | 1 + 6 + 1 = 8 | about 43 KB |
| settlement-preceding (expected resolution - 30 min; market already closed, no books) | 1 | about 17 KB |
| **per day** | **30 GETs** (5 runs with network) | **about 140 KB of payloads + about 60 small observation rows (under 250 KB/day, under 100 MB/year)** |

**Bounds:**
- **Requests.** Every GET goes through the shared Kalshi pacer (at most 1.7 requests/s against the
  roughly 4/s public limit). A run makes at most 40 GETs, each with 2 bounded retries, over at most
  24 markets.
- **Time.** At most 4 minutes; the close run holds the collector lock for about 2.5 minutes.
- **Idle ticks** (option A, about 91 a day) make no request and no write. Each takes the file lock
  and a read-only SQLite open, then exits: no collection run, no row, well under 1 s of CPU.
- **Retries.** A failed target is retried by at most 2-3 ticks inside its due window. The worst case
  for one bad day is about 3x the daily figure.
- **Units.** The proposed units would copy the existing caps: `MemoryMax=256M`, `CPUQuota=25%`,
  `TasksMax=32`, `Nice=5`, `TimeoutStartSec=6min`.

**Owner decision recorded 2026-09-24 11:24 ET:** Option A is approved now, including the fixed
04:57:45 UTC close tick for the currently observed KXHIGHNY 05:00Z close reference.

**Close-time risk (independent review of PR #76).** The close window `[close - 2 min 30 s, close - 10 s]`
fits the 04:57:45Z tick, plus 5 s for start-up, only for closes from 04:58:00Z to 05:00:15Z. Kalshi's KXHIGHNY close_time
was 23:59 ET wall time until August 2026 (03:59Z in summer, 04:59Z in winter; gate3 bulk fixture) and
has been 05:00:00Z since. No winter (EST) close under the new convention has been observed yet.
- If the venue moves close_time outside that range, the close-proof checks still prevent a false
  CLOSE label, but the fixed tick misses the window and **every close target becomes MISSED**.
  Nothing alerts on MISSED.
- `observe status` therefore reports `close_tick_alignment` (ALIGNED / MISALIGNED /
  NO_OPEN_CLOSE_TARGET) for every open close target, and `timers` (what systemd says, never
  inferred).
- **Re-check after the 2026-11-01 DST change.** Look at the first EST close_time and the alignment
  state. If misaligned, move the close timer by a reviewed change; never relabel a late read.

**Failure and alert semantics under the schedule (independent review of PR #76).**
- A FAILED observation row is always stored as evidence.
- A run exits non-zero, which is an `OnFailure` production alert, only when a FAILED target cannot
  be retried by a later scheduled tick: a close target, or one whose deadline comes before the next
  tick (`SCHEDULED_TICK_INTERVAL`, pinned to the timer). Retryable failures are reported as
  `failed_retrying` (state `PARTIAL_RETRYING`, exit 0). This stops a one-off 5xx from alerting and from
  overwriting the single-slot `last_failure.json` 96 times a day. A failure that persists to the last
  chance still alerts once.
- **Close ordering.** Other groups run first but share a request deadline capped at the earliest
  pending close aim − 20 s (`CLOSE_GUARD`). A group without that budget is deferred, not started, so a
  slow pre-close retry cannot push the close book past close − 10 s. A group whose own deadline has
  passed is deferred and recorded MISSED by the next run, never fetched late.

The runbook §5c contains activation, verification and manual fallback commands.

## Tradeoffs

- **The close tolerance.** "Last executable quote" is proven only to within 60 s. That is the best
  the public Kalshi book allows, and the tolerance is stored in every proof.
- **Coarse EXP-001 lifecycle.** For EXP-001, `settlement_preceding` records only that the market is
  closed and its rules hash. The book is not requested because the market is not open.
- **Missed scheduled captures.** Every uncaptured target still becomes `MISSED` with its reason.
  Scheduling reduces preventable gaps but never fabricates a late observation.
- **The shared collector lock.** It serializes observations with the forward captures. Refusing the
  protected windows keeps an observation from ever making a production run `LOCK_BUSY`.
- **Health view.** The observation books use the same snapshot kinds as the forward captures, so
  the routine health view's "latest orderbook" freshness also reflects them, as it already does for
  forward captures.

## Reconsider when

- production evidence shows the selected cadence is too sparse, too noisy or materially wasteful;
- the generalized #74 Freshness Orchestrator is ready to absorb this policy without changing its evidence contract;
- a venue publishes a book sequence number or update time (the close proof can then be exact);
- a market family with a different close time or no scheduled close is decided on;
- observation volume grows past a few hundred GETs a day, or storage past about 1 GB/year.
