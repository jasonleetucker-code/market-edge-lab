# ADR 0031: Freshness Fabric v1 (observe-only supervisor)

**Status:** Proposed 2026-09-24 (Lane A, PR pending review). Authority: owner directive
`docs/owner/2026-09-24-freshness-fabric-sports-directive.md` (coordinator contract C1), the
2026-09-24 (evening) entry in `docs/EXECUTION_PLAN.md`, and issue #74. v1 does not close #74.

## Problem

Market Edge runs ten systemd timers, and each has its own idea of "due", "missed" and "fresh":
- forward weather (`forward.gate` windows);
- the Odds API pilot (`odds_schedule` slots, the quota ledger and the cost block);
- the ADR 0030 observations (targets, protected windows and the close tick);
- settlement and shadow bookkeeping (the daily receipts);
- backups.

No single place answers the owner's first success question: *"What data sources are fresh now,
what is due next, and why?"* Every new domain (sports is next) would otherwise add another private
vocabulary. The directive asks for one shared abstraction that can **explain** every existing
schedule before it **controls** any.

## Alternatives

1. **Replace the timers with a new scheduler now.** Rejected. The timers are production-verified,
   and a rewrite would change behaviour that evidence depends on. The directive says to observe
   first.
2. **Leave freshness per module (the status quo).** Rejected. There is no common answer, and each
   new domain would fork the vocabulary again.
3. **Let the dashboard compute it.** Rejected. Contract C4 says the UI does no arithmetic, and the
   concept needs one backend owner.
4. **A declarative config (TOML) listing sources.** Rejected for v1. A schedule's truth lives in
   code (`forward.gate`, `odds_schedule.effective_due`, ...). A config would be a second copy that
   drifts.
5. **Shared types in `freshness.py`, read-only providers in a subordinate module, and an
   observe-only supervisor with one status artifact.** Chosen.

## Decision

### Types (`edge_lab.freshness`, the canonical owner)

Everything that existed before (`Freshness`, `assess`, `combine`, `require_fresh`, `parse_utc`,
`StaleDataError`) is unchanged. Added:

- `AcquisitionMode`: STREAM, POLL, EVENT_RELATIVE, RELEASE_DRIVEN, MANUAL, EXTERNAL_SCHEDULE.
- `ScheduleState`: DUE, NOT_DUE, MISSED, PAUSED, BUDGET_BLOCKED, QUOTA_BLOCKED, PROTECTED_WINDOW,
  LOCK_BUSY, plus **UNKNOWN**. UNKNOWN is used when the evidence needed to decide is missing or
  unreadable: unknown stays unknown.
- `SourceHealth`: OK, DEGRADED, FAILING, UNKNOWN. This describes how acquisition went, independent
  of how old the data is.
- `SourcePolicy`, a frozen record of the static contract:
  - identity: `source_id`, `domain`, `mode`, `underlying_mode`, `description`, `policy_version`,
    `schedule_owner`;
  - freshness objective: `max_useful_age`;
  - cadence, as intervals. `min_safe_cadence` is the longest interval between acquisitions that
    still meets the objective. `max_useful_cadence` is the shortest interval worth running;
  - controls: `pacing`, `budget`, `protected_windows`, `retry`;
  - None means "not defined", never zero.
- `SourceFreshness`, a frozen record of one source at one instant (`as_of`):
  - the policy, `freshness`, `schedule_state`, `health` and `why_due`;
  - times: `intended_at`, `next_due`, `last_attempt`, `last_success_receipt`, `upstream_ts`,
    `receipt_ts`;
  - `data_age` and `upstream_age`, derived from `as_of` so they can never disagree with it;
  - `missed_count`, `recent_misses`, `usable_for_research` and `usable_for_decision`;
  - `disagreements`, `notes`, and `details` (small, JSON-safe, no secrets);
  - fail-closed constructor checks:
    - FRESH requires `receipt_ts`;
    - `usable_for_research` requires a `receipt_ts` of known freshness. Last-known-good STALE data may
      serve research; UNKNOWN never does, and that includes a future-dated receipt;
    - `usable_for_decision` requires FRESH data and OK health;
    - times must be zone-aware, and a count must be a non-negative int or None.
  - `usable_flags(freshness, health, receipt_ts)` computes exactly this rule. A provider may be
    stricter, never looser. The flags summarize the fabric's view; they never replace
    `require_fresh` at the point of use.
  - **Receipts are successes only.** `receipt_ts` and `last_success_receipt` come from the latest
    *successful* acquisition. A run that did no work or failed never makes a source fresh or usable:
    - LOCK_BUSY, NO_CAPTURE and NOT_CLOSED shadow runs;
    - FAILED and SETTLEMENT_CONFLICT shadow runs;
    - a NOT_EXECUTABLE observation;
    - a rejected, partial or failed capture;
    - a wrong-schema artifact.

    `last_attempt` records any outcome.
  - **`missed_count` scope** is named in each record's `details.missed_scope`:
    - fixed daily ticks count the latest tick only (0/1);
    - forward captures count closed target days in the last 7 without a complete capture;
    - Odds and ADR 0030 count targets their scheduler recorded MISSED.

    None means there is no evidence to judge.
- `policy_freshness(policy, receipt, now)`: the canonical `assess` against the policy objective.
  A policy with no objective gives UNKNOWN.
- `FabricContext`: read-only paths only (evidence DB, shadow ledger, Odds quota ledger and pilot
  state, status dir, backups dir).
- `Provider = Callable[[FabricContext, datetime], list[SourceFreshness]]`.
- `FabricProvider(name, policies, provide)`: a registry entry that declares its sources.

Freshness objectives come from `edge_lab.sources.REGISTRY` `max_age` wherever one exists (one owner
per fact). For example, a Kalshi book is FRESH for 5 minutes. An EXP-001 decision book is therefore
STALE a few minutes after its capture, and the record says so. Being on schedule is the job of
`schedule_state`, not `freshness`.

### Providers (`edge_lab.freshness_fabric`), all EXTERNAL_SCHEDULE and read-only

| Provider | Sources | Reads | Canonical functions used |
|---|---|---|---|
| `exp001_forward` | `exp001.forward.{pfm,decision,recheck,status}` | `forward_captures`, `latest.json` | `forward.gate`, `forward.windows`, `forward.target_for` |
| `the_odds_api` | `the_odds_api.nfl_odds`, `the_odds_api.discovery` | quota ledger (no lock), pilot state, odds targets | `odds_pilot.dashboard_status`, `odds_schedule.effective_due` / `deadline` / `in_quiet_window` |
| `price_observations` | `price_observations.later`, `price_observations.close` | `price_targets` | `price_observations.close_tick_alignment`, `protected_refusal` (same next-due rule as `status`) |
| `settlement_and_shadow` | `kalshi_settlement.refresh`, `exp001.shadow_daily` | the daily receipts (history tail at most 256 KB), `source_health`, ledger (mode=ro) | `daily.pending_event_tickers` |
| `backups` | `backup.evidence`, `backup.ledger` | the newest bundle manifests | none (manifest `completed_at_utc`) |
| `freshness_supervisor` | `freshness_fabric.supervisor` | its own previous artifact | none |

No provider makes a network call, takes a lock, writes, or triggers anything.

**Parity.** For the same inputs, the fabric's DUE equals `forward.would_proceed` AND the phase's
timer tick having passed, at every minute through the windows. The gate opens at 17:30 ET for pfm,
but nothing runs it before the 17:45 tick: "gate open, timer at 17:45" is NOT_DUE. Its odds next-due equals the minimum of `odds_schedule.effective_due` over the
open targets, and `odds_pilot.dashboard_status`. Its ADR 0030 next-due equals
`price_observations.status`, and its close alignment equals `close_tick_alignment`.
`tests/test_freshness_fabric.py` pins each of these.

**Disagreements** are reported in a record's `disagreements` and are never resolved silently. The
provider shows the canonical value and flags the conflict. Reported cases:
- a forward timer tick that `forward.gate` would reject;
- the fabric's next capture differing from `dashboard_status`;
- an odds target that no 15-minute tick outside the quiet window can fire;
- an observation target that no unprotected observe tick can reach;
- a close target the fixed close tick cannot reach.

**Timer contracts.** Tick times and grace periods are copied from the unit files and pinned by test,
so a timer change without a fabric change fails CI. A test also requires every installed `*.timer`
to be named by some source's `schedule_owner`: the fabric explains every schedule.

### Supervisor and artifact

- `edge-lab freshness status [--db --ledger --odds-ledger --odds-state --status-dir --backups-dir --write --now]`
  prints the status JSON.
- With `--write`, it atomically replaces `<status-dir>/freshness.json` (0644) and prints one
  summary line for the journal.
- Schema `freshness-fabric-status/1`, holding the current state only:
  - `generated_at_utc` and `sources_evaluated_at_utc`;
  - `supervisor`: state OK / PARTIAL / DEFERRED_PROTECTED_WINDOW, `code_version`, `network: none`,
    `controls_schedules: false`, per-provider state, and problems;
  - `summary`: counts, fresh, due_now, missed, blocked, unknown, disagreements, and the next five
    due;
  - `policies` and `sources` (`SourceFreshness.to_dict()`).
- Bounds: strings are cut at 300 characters, lists at 10 items, details at 24 keys, and there are
  at most 64 sources. The document is at most 256 KB, or the run fails.
- The artifact holds no paths, no environment values and no secrets.
- **Isolation.** A provider that raises, omits a declared source, or returns an undeclared one is
  reported. Its declared sources become UNKNOWN records, and the other providers still run.
- **Protected windows.** A `--write` run opens no store in two cases: inside a
  `price_observations.PROTECTED_WINDOWS_ET` window, and inside the close guard. The close guard runs
  from 2 min 15 s before to 3 min 15 s after the 04:57:45 UTC close tick, so the 04:56 run can never
  overlap the close capture.
  - It carries the previous evaluation forward only if that evaluation was made at most 15 minutes
    before the window opened.
  - Each carried record is re-assessed at `now` by pure arithmetic from its own receipt time and
    objective: freshness and ages move on, and `usable_for_decision` is forced False. Its schedule
    state is labelled as of `carried_from_utc`.
  - Anything older, or missing, becomes UNKNOWN.
  - `sources_evaluated_at_utc` is always the time of the evaluation actually shown (None when
    nothing was carried).
  - The supervisor state is DEFERRED_PROTECTED_WINDOW.
  - The verifier checks both ages: `generated_at_utc` within 15 min, and `sources_evaluated_at_utc`
    within 15 min, or within 95 min while deferred (the 70-minute evening window plus the 15-minute
    carry margin plus a tick and slack).
  - An operator's read without `--write` always evaluates.
- **Problems** in the artifact are scrubbed of filesystem paths (exception messages can carry them).
- **Durability.** After the atomic replace, the directory is fsynced (POSIX).
- **Exit status.** 0 whenever a status was produced, 2 on bad arguments. Anything else is a genuine
  crash (a traceback in the journal). A STALE or MISSED source is data, never a failure.

### Unit: `edgelab-freshness.{service,timer}`

- **Schedule.** `OnCalendar=*:01/5` with `AccuracySec=5s` and `Persistent=false`, so it runs at
  :01, :06 ... :56.
  - This is staggered off every other edgelab tick: Odds :00/:15/:30/:45, observe
    :05/:20/:35/:50, and the daily :00/:05/:15/:30/:40/:45/:55 ticks.
  - The 04:56 UTC run falls in the close guard and defers, opening no store. With TimeoutStartSec
    120 s it could otherwise overlap the 04:57:45 close tick. The 05:01 run comes after the close
    confirmation. A test pins this.
- **Hardening.** Oneshot, `User=edgelab`, `Slice=edgelab.slice`, and the same hardening block as
  `edgelab-observe.service`, but network-free:
  - `RestrictAddressFamilies=AF_UNIX` and `IPAddressDeny=any`;
  - no `EnvironmentFile` (it needs no secret or setting, and the commit comes from `REVISION`);
  - `ReadWritePaths` covers the status dir only. The stores are opened with SQLite `mode=ro`, as the
    dashboard already does in production.
- **Caps.** MemoryHigh 96M, MemoryMax 128M, CPUQuota 10%, TasksMax 8, Nice 10, TimeoutStartSec 120 s.
  At 10% CPU, a run of 1-3 CPU-seconds takes 10-30 s of wall time; 120 s leaves room for a cold
  start. A timeout is silent (no OnFailure), so the margin matters.
- **No `OnFailure=` alert.** A diagnostic on a 5-minute cadence that crashes would push up to 288
  times a day. Every push would also overwrite `last_failure.json`, which belongs to the evidence
  collectors. A crash is visible without that:
  - the unit fails (the production verifier lists failed units);
  - `freshness.json` goes stale. The dashboard judges it by `generated_at_utc`, and the
    `freshness_fabric.supervisor` record goes STALE on the next good run.
- **Installer.** It is in `install.sh` `UNITS`, so it is verified on install, enabled with the core
  timers (`CORE_TIMERS`), and named in the printed stop line.

### Performance and resource estimate

Measured on the laptop (Windows, Python 3.12) with a populated fixture of 13 sources:
- about 1.3 s of imports and 0.3 s to evaluate and write;
- peak Python allocations about 18 MB;
- artifact about 29 KB (bound 256 KB).

On the VPS, expect a run of 1-3 s of CPU at most, under the 10% quota.
- **Per day:** 288 runs, about 5-15 CPU-minutes. Journal output is one line of about 300 bytes per
  run, about 90 KB a day. Disk growth is zero: one file is replaced each run.
- **Reads per run:**
  - one read-only open per provider;
  - the `forward_captures`, `odds_targets` and `price_targets` tables and the latest source health;
  - the stored odds snapshots, newest first and 8 per page (`SnapshotStore.snapshots_of_kind_newest`),
    until one holds offers (`dashboard_status`). At most one page of payloads is in memory at a time,
    however long the season's history.
  - at most 256 KB of receipt history and three manifests.
- **Growth:**
  - Odds payloads are bounded per page. Before review, the dashboard loaded every stored odds
    payload: about 46 MB at 600 rows, which would have breached MemoryMax within a season. Each read
    is now at most 8 payloads.
  - The `forward_captures`, `odds_targets` and `price_targets` reads still grow with history (a few
    rows a day, and about 40 targets a day). They carry no payloads: kilobytes, not megabytes.
  - Revisit when `price_targets` passes about 50k rows, or when a run exceeds 30 s.

## Contract for later lanes

**Lane B (Polymarket US NFL pilot) adds its provider in one line:**

```python
# in its own module (e.g. polymarket_sports.py): policies and a read-only provider
PM_POLICIES = (SourcePolicy(source_id="polymarket_us.nfl_discovery", domain="sports",
               mode=AcquisitionMode.EXTERNAL_SCHEDULE, underlying_mode=AcquisitionMode.POLL, ...),
               SourcePolicy(source_id="polymarket_us.nfl_books", ..., underlying_mode=AcquisitionMode.EVENT_RELATIVE, ...))
def fabric_provider(ctx: FabricContext, now: datetime) -> list[SourceFreshness]: ...

# in freshness_fabric.REGISTRY: one added line
    FabricProvider("polymarket_us_nfl", PM_POLICIES, polymarket_sports.fabric_provider),
```

The provider rules:
- return exactly one record per declared policy, with `as_of == now`;
- open stores read-only via `FabricContext`;
- make no network call, take no lock and write nothing;
- report unknown as None or UNKNOWN;
- put scheduler-versus-fabric conflicts in `disagreements`;
- keep `max_useful_age` from `sources.REGISTRY`;
- set the usable flags with `usable_flags(...)`. The constructor rejects looser flags, for example
  `usable_for_research=True` on an UNKNOWN (for instance future-dated) receipt;
- count only successful acquisitions as receipts, and name the `missed_scope`.

Its timer must appear in a policy's `schedule_owner`. The every-timer-is-explained test enforces
this.

**Lane D (Terminal)** reads `freshness.json`. In-process, it can call
`freshness_fabric.build_status(ctx, now)`, `evaluate(ctx, now)` or `SourceFreshness.to_dict()`.
- The UI computes nothing.
- It shows `mode` and `schedule_owner`, so it is clear that the fabric only supervises an external
  timer.
- It shows `disagreements`, `why_due` and the UNKNOWN states as they are.
- It judges the artifact's own age by `generated_at_utc`, and shows `sources_evaluated_at_utc`
  when the state is DEFERRED_PROTECTED_WINDOW.

## Migration path (providers become schedulers only after parity evidence)

1. **v1 (this ADR):** observe everything; control nothing.
2. **Evidence:** production artifacts over at least two weeks with zero disagreements, and with
   DUE/MISSED matching what each canonical scheduler actually did (receipts and `forward_captures`).
   The first NFL weeks give the Odds and Polymarket evidence.
3. **One source at a time**, each with its own review and owner approval:
   - a provider may become the scheduler of its source, for example the new Polymarket US NFL
     source designed on the fabric from the start;
   - its old timer is retired in the same change;
   - the evidence contract is unchanged;
   - rollback is re-enabling the old timer.
4. The fabric never takes over a working timer silently. Each migration is a new ADR or an
   amendment.

## Tradeoffs

- **Duplication.** v1 keeps copies of a few schedule facts (tick grids, graces). Tests pin them to
  the unit files and the canonical functions, but the copies still exist until migration.
- **Timer state.** The fabric cannot see whether a systemd timer is enabled. It is network-free and
  runs no `systemctl`. A MISSED fixed tick is inferred from receipts; the verifier checks the
  timers.
- **Protected windows.** Inside them the artifact's evaluation can be up to about 85 minutes old
  (17:40-18:50 ET plus the carry margin).
  - It is labelled, re-assessed for freshness, and never decision-grade.
  - The carried schedule states are as of the evaluation.
  - A manual read still evaluates.
- **Freshness versus schedule.** Freshness follows the registry objectives. Short objectives, such
  as books, therefore show STALE most of the time. That is truthful, and the schedule state carries
  "on time".
- **No push alert** for a supervisor crash (reasoned above).

## Reconsider when

- A production artifact shows a disagreement: investigate before any migration.
- A domain needs the fabric to control scheduling (see the migration path).
- Runs exceed 10 s, or the artifact nears its bound: add targeted read queries (storage is Lane B's
  additive area) or split providers.
- Systemd timer state becomes necessary in the artifact: a read-only `systemctl show` over AF_UNIX
  would need its own review.
- The owner wants crash alerts: add a rate-limited (once a day) alert path, not `OnFailure=` on a
  5-minute unit.

## Amendment 2026-09-24 (night): read-only readers need the WAL side files

**Observed on production.** The supervisor (and the dashboard) reported "evidence store unreadable
(OperationalError)" for every store-backed source whenever no collector held the evidence DB open.
- The evidence DB runs in WAL mode. SQLite opens `-wal`/`-shm` read-write and creates them if they
  are absent, even on a `mode=ro` connection (ADR 0016).
- On a read-only mount it falls back to a read-only open, which fails for a file that does not
  exist.
- While a collector held the DB, the side files existed and reads worked.

**Decision.**
- `edgelab-freshness.service` and `edgelab-dashboard.service` may write
  `/var/lib/market-edge-lab/db` (the directory only).
- `ReadOnlyPaths=` re-pins `edge_lab.sqlite3` read-only at kernel level in both units (the more
  specific path wins). It pins `odds_quota_ledger.json` in the supervisor only. The odds runner
  replaces that file by atomic rename, and the long-running dashboard would keep reading a
  bind-mounted stale inode. The supervisor is a oneshot with a fresh mount namespace per run.
- The shadow ledger uses a rollback journal. A read-only reader never creates a file for it, so its
  directory stays read-only.
- Connections remain `mode=ro` plus `query_only`.

**What these units can now do at kernel level.** Inside `db/` they can create, write and delete
files other than the two re-pinned ones: the WAL side files, the `*.lock` files, and any leftover
`-wal`. So a buggy or compromised dashboard could delete an uncheckpointed `-wal` left by a crashed
collector. They cannot write or delete the database file. The supervisor also cannot touch the quota
ledger; the dashboard, which does not pin it, can. Neither can write the data root, the ledger
directory or anything else.

**Restore note.** A long-running dashboard keeps the bind-mounted inode of `edge_lab.sqlite3`. A
restore that replaces the file by rename therefore needs a dashboard restart; the rollback runbook
already restarts it. The supervisor is a oneshot and picks up the new inode on its next run.

**Alternatives rejected:**
- `immutable=1`: torn reads while a writer commits.
- A rollback journal for the evidence DB: readers would block collector commits.
- Persistent WAL: not settable from Python's sqlite3 module.
- `nolock=1`: WAL still needs the shm and locks, and it is unsafe.
- Per-file `ReadWritePaths` for `-wal`/`-shm`: systemd requires the path to exist at unit start, and
  SQLite deletes and recreates these files.
