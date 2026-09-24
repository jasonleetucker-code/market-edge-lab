# ADR 0029: Game-relative Odds API capture policy and the monthly credit proof

**Status:** Accepted 2026-09-24. Owner authority: `docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`,
Phase 6 and **owner correction 3**, recorded in `docs/EXECUTION_PLAN.md` (2026-09-24 entry).
Builds on ADR 0019 (read-only data-feed credentials) and ADR 0028 (the owner secrets file).

## Problem

The owner approved a bounded, read-only schedule for The Odds API free tier: NFL h2h, spreads
and totals for one region, a hard ceiling of 450 credits a month, and never above the
provider's remaining quota. The goal is our own prospective line history and closing-line
information.

The first plan was three fixed pulls a day (about 09:30, 14:30 and 19:30 ET, about 279 credits
a month). Owner correction 3 replaced it:

- do not spend three paid calls every calendar day;
- discover the schedule with the quota-free endpoints;
- capture each relevant NFL game at about T-24h, T-6h and T-60m;
- before enabling, enumerate the schedule, compute expected and worst-case credits, and prove
  both limits hold;
- persist every snapshot's intended target time, so missed captures stay visible.

Fixed clock polling spends credits on days without games. It also captures most games hours
away from any line-moving moment and misses the close entirely.

## Provider rules relied on

Re-read 2026-09-24; evidence note `experiments/multi_venue/odds_api_credit_rules_2026-09-24.md`.

- `/v4/sports` and `/v4/sports/{sport}/events` cost nothing.
- `/v4/sports/{sport}/odds` costs `markets x regions`, and an empty response is free. One call
  returns every event in its `commenceTimeFrom`..`commenceTimeTo` window.
- Every response carries `x-requests-remaining`, `x-requests-used` and `x-requests-last`.

One capture call is therefore **3 credits at most**, however many games it covers.

## Alternatives

1. **Fixed daily clock pulls** (the superseded plan). Rejected by the owner.
2. **One call per event per offset.** Pays up to 8 times for the 13:00 ET Sunday window,
   although one call returns all of those games for the same price.
3. **Game-relative targets, coalesced into slots, admitted by a monthly proof.** Chosen.
4. **Event-odds endpoint per game.** Same per-call cost per game; no coalescing benefit.

## Decision

### Targets

For every event discovered through the events endpoint, one target per offset, at
`commence - offset`.
- **Defaults:** T-24h (priority 3), T-6h (priority 2) and T-60m (priority 1, the closing line).
- **Units:** the arithmetic is UTC, so a DST change cannot shift a target.
- **Identity:** a target's id includes its target time. If a game is moved, its old targets
  become SUPERSEDED and new ones are planned.
- **Configuration:** the offsets are configurable (`--offsets`). Change them only with
  measured evidence; the captured `deviation_minutes` and `lead_minutes` are that evidence.

### Slots

Targets whose effective times lie within 20 minutes of a slot's first target become one paid
call (a slot). Example: the 16:05 and 16:25 ET games share their calls.
- **Firing time:** a slot fires at its earliest member's time. Later members are captured
  slightly early, and each member records its actual deviation.
- **Scope:** the call is scoped to the members' commence window. Any other game kicking off
  inside that window comes along at no extra cost.

### Timing

- **Due:** a slot is due from 7 minutes before its time.
- **Missed:** a target is MISSED 30 minutes after its time, or 5 minutes before kickoff if that
  is earlier.
- **Quiet window:** targets inside 17:40-18:35 America/New_York (the EXP-001 capture window)
  move to 18:35 if that is still at least 5 minutes before kickoff, else to 17:35. Ticks inside
  the window do nothing.

### The monthly proof (`odds_schedule.budget`)

The proof covers the ledger's UTC month.
- **Spent:** `max(local used, provider used)` plus outstanding reservations.
- **Headroom:** `min(450 - spent, provider remaining - outstanding) - 3` (one call kept back
  for a manual smoke read or an ambiguous failure).
- **Allocation:** capacity goes class by class, T-60m first, then T-6h, then T-24h. Within a
  class, known slots come first, earliest first. After them comes a reservation for games not
  yet discovered.
- **Unknown games:** these are kickoffs after the last discovered one, through the end of the
  month plus 24 hours. The assumption is at most **10 distinct kickoff groups in any 7-day
  week**. A partial week sums per-weekday maxima (Mon 2, Tue 1, Wed 2, Thu 3, Fri 1, Sat 3,
  Sun 4), capped at 10. That is 3 calls per group. The expected planning figure is 6 groups a
  week.
- **Invariant:** `worst case = spent + 3 + admitted known calls + reserved unknown calls`, which
  is **<= 450 and <= spent + provider remaining**. This holds by construction, is asserted in
  code, and is property-tested on 300 random months.
- **Does not fit:** a known slot that does not fit is SKIPPED_BUDGET, lowest priority and
  latest first. Unknown calls that cannot be reserved are reported; if those games appear,
  their slots are skipped rather than paid for.
- **Unknown quota:** no provider reading this month means QUOTA_UNKNOWN, and no paid call is
  made. A tick first tries the free reconcile.

**Where the 10 comes from.** In the heaviest recent NFL weeks, the 2024 Christmas week had
Wed 2, Thu 1, Sat 2, Sun 3 and Mon 1 groups (9), and Thanksgiving weeks have 8 to 9. A
London/Germany 09:30 ET Sunday or a Monday doubleheader adds one, hence 10. Known weeks are
always counted exactly, so the assumption matters only beyond the discovery horizon (35
days).

### Numbers

Computed with the committed planner; reproduce with `odds plan`.

| Month | Assumption | Calls | Worst case | Expected |
|---|---|---|---|---|
| Typical NFL week | 6 kickoff groups (TNF, 13:00, 16:05/16:25, SNF, MNF, plus London) | 18 (15 without London) | 54 credits | - |
| October 2026, schedule fully known | 5 weeks, 3 with a London game | 74 | **225** (222 + 3 reserve) | **222** |
| A 31-day month, nothing discovered | 50 unknown groups per class | reserves 149 | **450** (1 T-24h call unreservable) | **261** |

The real figures come from the live schedule: `odds plan` enumerates it and prints the proof
before the timer is enabled (runbook section 5b).

### Persistence (storage schema v5, additive)

- `odds_capture_targets` holds one immutable row per target: event, offset, priority,
  commence time, **intended target time**, planned-at time, policy version and the discovery
  snapshot.
- `odds_capture_transitions` is append-only. Its states are PLANNED, CAPTURING, CAPTURED,
  MISSED, SKIPPED_BUDGET, QUOTA_UNKNOWN, QUOTA_EXHAUSTED, SETUP_NEEDED, DEFERRED, FAILED and
  SUPERSEDED.
  - A CAPTURED row names its snapshot, its receipt time and the call's `x-requests-last`.
  - Any state other than progress carries a reason.
  - CAPTURED, MISSED, FAILED and SUPERSEDED are final (trigger).
  - A MISSED row states the state it was stuck in.
- Existing tables are untouched. The migration only adds tables, so a v4 store opens and
  migrates in place.
- DEFERRED (discovery older than 24 h) and SUPERSEDED (game moved) are the two states added to
  the owner's list.

### Evidence per capture (issue #50, directive §6D)

- **The raw provider body.** It holds provider event ids, sport, teams, commence times,
  bookmakers, markets, outcomes, points, raw offered odds and `last_update`. The store records
  its hash (`raw_sha256`).
- **The snapshot payload.** It holds the request identity (redacted URL, markets, regions,
  commence window, slot and target ids with intended times), the quota headers and the parser
  version.
- **The transition.** It holds per-target coverage: event present, bookmakers, markets,
  missing markets, deviation and lead minutes.
- **Failures** are FAILED transitions with redacted errors.

### One tick (`edge-lab odds run`, `edgelab-odds.timer` every 15 minutes)

1. No key: SETUP_NEEDED, exit 0.
2. Quiet window: DEFERRED_CAPTURE_WINDOW.
3. A file lock allows one tick at a time.
4. A CAPTURING row left by a crash becomes FAILED. It is never retried, because its credits may
   already be spent.
5. Free discovery, at most every 6 h.
6. Plan, supersede, mark MISSED.
7. Run the proof.
8. **At most one paid call**: the most important admitted due slot.

A tick that runs twice in the same minute makes one call, because the second finds its
targets CAPTURED. Exit 1 only for a failure (discovery or paid call), which triggers the
standard alert unit.

`odds plan` is read-only: free calls only, and it never writes the evidence store (`--offline`
makes no calls at all). `odds smoke` makes exactly one bounded read (7 days of games) after a
free reconcile, and refuses when the quota is unknown or insufficient.

### User interface

This change is backend-only, and no Terminal v1 view changes. Target states and the proof are
read with `odds plan --offline` and the journal. A dashboard panel for capture targets must
follow `docs/design/UI_CONTRACT.md`, including its empty, stale, error and blocked states. It is
a separate change.

## Tradeoffs

- **Early captures.** Coalescing captures some targets up to 20 minutes early. The deviation
  is recorded, not hidden.
- **Timer frequency.** A 15-minute tick means a slot may fire up to about 15 minutes late. The
  30-minute tolerance absorbs one skipped tick.
- **Unused reserve.** The worst-case reservation can hold back T-24h slots late in a month
  whose later weeks are undiscovered. The reservation is released as the schedule becomes
  known, and discovery looks 35 days ahead.
- **Discovery storage.** Storing every discovery (4 a day, tens of kilobytes) is a bounded cost
  for a complete point-in-time schedule history.
- **Ledger backups.** The quota ledger lives beside the database and is not in the backup
  bundle. If it is lost, the next free reconcile rebuilds it from the provider's own counters.

## Reconsider when

- measured deviations or line-movement evidence support different offsets, or a
  closing-line capture nearer kickoff (for example T-15m);
- the events endpoint proves to list the whole season, so the unknown-week reservation is
  rarely used;
- another sport, player props, more regions or a paid tier is proposed (each needs owner
  approval and its own proof);
- the provider changes its cost rules, which is why the guide is re-read and hashed.
