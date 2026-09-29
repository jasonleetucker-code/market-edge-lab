# ADR 0039: A sport-aware shared Odds planner and one combined NFL-first quota proof

**Status:** Accepted 2026-09-29 (NHL-A). Prepared, **not activated**: the NHL line in `edgelab-odds.service`
does nothing until `EDGE_LAB_ODDS_NHL=on`, which is a reviewed operator step (NHL-C).
Owner authority: issue #134 and `docs/owner/2026-09-29-nhl-prospective-evidence-directive.md` (recorded in
`docs/EXECUTION_PLAN.md` by #135). Extends ADR 0029 (game-relative capture and the monthly proof); it does not
supersede it. NHL is DATA_COLLECTION / DEVELOPMENT_ONLY: not EXP-002, not a research family.

## Problem

The owner wants prospective NHL sportsbook evidence from the opening weeks of the 2026-27 season. The Odds API
free tier gives one key, one account and one monthly allowance. ADR 0029's planner was NFL-shaped:
- one worst-case assumption (`NFL_WORST_CASE`);
- one set of runner defaults;
- one runner-state file;
- a monthly proof that knew only the sport it was running.

Running a second copy for NHL would give each sport the belief that it owns the 450-credit ceiling. That is the
failure the owner ruled out: "one shared ledger and one monthly ceiling govern every sport", and NFL keeps
priority.

## Alternatives

1. **A separate `nhl_odds_schedule.py` and its own ledger or ceiling.** Rejected by the owner. Two proofs over
   one allowance can both be "proven" and together exceed it.
2. **Split the ceiling (for example NFL 350, NHL 100).** This invents a cap nobody measured. It starves NFL
   in a heavy month and wastes credits in a light one, and it still needs a joint check against the provider's
   remaining quota.
3. **One planner with a per-sport policy table and one joint proof, served in rank order.** Chosen.

## Decision

### One policy table

`odds_schedule.SPORT_POLICIES` holds one `SportPolicy` per provider sport key:
- rank in the shared budget;
- allowed markets and regions;
- default offsets;
- worst-case assumption;
- merge window;
- discovery horizon;
- optional env switch;
- runner-state scope;
- whether past targets are recorded as MISSED.

Everything else is shared: the planning rules, the quiet window, the ceiling (450), the reserve (3 credits) and
the ledger.

| Sport | Rank | Markets / regions | Default offsets | Cost per call | Assumption | Merge | Switch |
|---|---|---|---|---|---|---|---|
| `americanfootball_nfl` | 1 | h2h, spreads, totals / us | T-24h, T-6h, T-60m | 3 | `nfl_v2` (ADR 0029) | 20 min | none (the running pilot) |
| `icehockey_nhl` | 2 | h2h / us | T-60m | 1 | `nhl_2026_27_v1` (below) | 20 min | `EDGE_LAB_ODDS_NHL`, default off |

A sport with no policy sends nothing (`UNSUPPORTED_SPORT`). A request outside the policy's markets or regions
(for example NHL spreads or totals) sends nothing (`POLICY_REFUSED`), because the joint proof prices each sport
at its policy's cost. A deploy test pins the service's arguments to the policy.

### One joint proof, NFL first

`joint_budget(demands, now, quota)` generalizes ADR 0029's proof:
- `spent = max(local, provider used) + outstanding`;
- `headroom = min(ceiling - spent, provider remaining - outstanding) - reserve`.

The shared headroom is then granted in rank order. Within a sport, the order is unchanged from ADR 0029:
- class by class, highest priority first;
- within a class, known slots earliest first, then the reservation for undiscovered events.

**A lower-ranked sport gets only what is left after every higher-ranked sport's full worst case.** If a
higher-ranked sport skips a known slot or cannot reserve a worst-case unknown call, every lower-ranked sport
gets **zero**. This holds even for a remainder smaller than one NFL call. Such a remainder cannot pay for an
NFL call today, but NFL could still need it: the provider charges less for an empty response, which leaves
odd remainders.

The invariant is unchanged and still checked: `worst <= ceiling` and
`worst - spent <= provider_remaining - outstanding`, else `BudgetInvariantError`. `QUOTA_UNKNOWN` admits
nothing for any sport.

`budget()` is now the one-sport case of `joint_budget`. The NFL tick, rank 1, still calls it alone: nothing
ranked below NFL can change NFL's admissions. NHL reaches NFL only through the shared `spent`, and every NHL
admission was already bounded by NFL's full reservation. **NFL output is byte-identical**:
`tests/test_odds_nfl_golden.py` replays slots, proofs, a week of tick reports, the offline plan and the stored
target history. It compares them with a golden file generated from `main` b944a0e before this change.

### The NHL tick proves from NFL's own evidence

`odds_pilot._demand` rebuilds NFL's demand from NFL's stored discovery and NFL's stored targets, never from
NHL data. Where this view could differ from NFL's own tick, it is more conservative:
- every non-final, unexpired NFL target counts, EVENT_ABSENT ones included (a game may come back);
- so do targets that NFL's latest discovery implies but NFL's tick has not written yet;
- if NFL's discovery is missing or stale (older than 24 h), nothing is known, and `NFL_WORST_CASE` covers the
  whole rest of the month.

A NFL target that expired uncaptured (MISSED) is final, and its reservation is released. This is the only way
NFL's demand shrinks, apart from NFL's own captures and newly discovered weeks.

**Known gap: NFL demand that grows inside its known horizon after NHL has spent has no reservation.** Examples: a
reschedule into a new kickoff group, a late-listed game, a flexed game. NFL's worst case covers unknown weeks,
not new groups inside weeks it has already listed. NFL still has priority for every later admission, and the
per-spend invariant still holds: no single call ever exceeds the ceiling or the provider's remaining quota. But
an NFL slot created that way could be SKIPPED_BUDGET because of credits NHL already spent.

**Default offsets.** The demand is built with the NFL policy's default offsets, markets and regions. The
production NFL line must run exactly those; `test_the_odds_service_arguments_are_each_sports_reviewed_policy`
pins it.

### Concurrency

Both sports run in the existing `edgelab-odds.service` (Type=oneshot), as two sequential `ExecStart` lines,
NFL first. There is no new timer or service.
- Both ticks use the same ledger path, so they take the same tick lock (`<ledger>.tick.lock`) and the ledger's
  own lock.
- Each proof is computed under the tick lock immediately before that tick's one paid call. `QuotaLedger.reserve`
  re-checks the ceiling at the call. No two ticks can spend the same headroom.
- If the NFL tick exits 1 (a new alert), systemd skips the NHL line for that tick, and the next tick runs both.
  This is fail-closed, and NFL keeps priority.
- **`odds smoke` is for the rank-1 sport (NFL) only.** It never passes the joint proof, so a lower-ranked sport's
  smoke could spend credits reserved for NFL's worst case: the 3-credit reserve belongs to the ledger, not to
  NHL. An NHL smoke is refused with no request (`SMOKE_REFUSED_RANK`). NHL's first live read is a scheduled
  capture that the joint proof admitted. The NFL smoke is unchanged: outside the tick lock, at most one call.
- **Per run.** Each `ExecStart` line makes at most three GETs, so one run makes at most six (20 s each), plus two
  Python starts. `TimeoutStartSec` was raised from 3 to 5 min. Measured with fixtures: the heaviest NHL tick
  (first planning) used 0.72 s of CPU, a steady tick 0.05 s, and an interpreter start with imports 0.2 s. That
  gives about 170 s in the worst case under `CPUQuota=10%`.
- **The shared unit's OnFailure alert names only `edgelab-odds`.** A failing NHL line prints its JSON report
  (`"sport": "icehockey_nhl"`) and a stderr line `odds run icehockey_nhl: exit 1, state ...` to the journal.

### Per-sport runner state

The runner-state file (`<ledger>.pilot.json`) stays one file:
- NFL keeps its historical top-level keys.
- NHL keeps its discovery attempt and outcome, key rejection, last paid call, smoke and activation time under
  `sports.icehockey_nhl`.

So a failing NHL discovery never marks NFL DEGRADED or DISCOVERY_STALE, and the reverse holds too (tested).

The **cost block is shared**, and a block stops every sport's paid calls:
- `COST_ANOMALY` means the provider charged more than `markets x regions`, which is provider-level trouble.
- `PILOT_STATE_CORRUPT/MISSING` means the runner state beside the shared ledger was lost, which is ledger-level
  trouble.

`odds_targets` rows are keyed by sport, and target ids start with the sport key (verified by test).

### NHL discovery and h2h

Discovery uses the existing quota-free events endpoint with sport `icehockey_nhl`, stored exactly as for NFL:
- event id, commence time, teams and receipt;
- a moved game SUPERSEDES its old targets.

An h2h market with a Draw or Tie outcome, or with a number of outcomes other than two, is already refused by
`odds_api.pair_offers` (`NOT_TWO_WAY`), so the consensus shows it as UNSUPPORTED.

For sports whose policy sets `check_two_way_h2h` (NHL only), the runner also records it on the paid capture:
- a source-health anomaly naming each book's actual outcomes (for example `draftkings: 3 outcome(s) [...]`);
- `h2h_not_two_way` in each affected target's detail.

NFL capture records are unchanged. A one-outcome NFL h2h book still leaves source health `ok` (tested).

Nothing is forced into a two-way formula. `odds_consensus.LABEL_PROXY_SPORTS` stays NFL-only.

### Opening night and late discovery

For NHL (`record_prior_misses`), a discovered target whose deadline has already passed when it is first seen
is written as `MISSED`, never silently dropped:
- `NOT_COLLECTED_BEFORE_ACTIVATION` when the deadline passed before activation;
- `NOT_DISCOVERED_BEFORE_DEADLINE` when the target was not planned before its deadline: a late listing, a
  discovery outage, or the collector disabled.

**Activation** (`activated_utc`) is the first tick that could actually plan: switched on, with a key and a fresh
discovery. It is not merely the first switched-on tick. A tick without a key, or with a failed discovery, does not
activate the collector.

A MISSED target is final, so it is never captured later and never relabelled T-24h, T-6h or T-60m. NFL keeps
its historical behaviour, which is not to write such targets.

Opening-night games (2026-09-29) and any game before activation have no Odds API target at all: the collector
never saw their provider event. The manual Kalshi observations of #135 are the only opening-night record.
Provider historical odds are not in the free tier, are not used, and never fill a gap. A paid `capture` snapshot
(`purpose: capture`, the live `/odds` endpoint) is prospective by construction. A future historical import would
need its own kind and purpose.

### The NHL worst case (`NHL_WORST_CASE`, `nhl_2026_27_v1`)

**Source.** The published 2026-27 regular season, 1,344 games, all `gameType` 2, from the keyless NHL
schedule API:
- `GET https://api-web.nhle.com/v1/schedule/<date>` (one `gameWeek` per call);
- 32 weekly calls from 2026-09-28, following `nextStartDate`;
- fetched once, offline, on 2026-09-29 at 17:29Z.

The derived fixture is `tests/fixtures/odds_api/nhl_schedule_2026_27_nhle.json`. Code never calls this API.

**Method.** This planner coalesced the season: 20-minute merge window, quiet-window shifts included, separately
for T-60m, T-6h and T-24h. It counted groups per ET kickoff date. Groups never span dates, and the per-date
counts sum exactly to the season's slots.

**Measured maxima over all three classes:**
- 37 groups in any 7 consecutive ET dates (T-6h and T-24h from 2027-04-02; T-60m reaches 34);
- per ET weekday, Mon..Sun: 7, 10, 5, 6, 7, 9, 8.
  - Tuesday's 10 is 2026-10-13, a staggered 16-game day with starts every 15 minutes.
- Average 28.0 groups a week (T-6h).

**Assumption, with margin for reschedules and make-up games:**
- 40 groups a week;
- per weekday (8, 11, 6, 7, 8, 10, 9);
- expected 28.0 a week.

`test_nhl_worst_case_bounds_the_published_2026_27_schedule_with_margin` re-derives these numbers from the
fixture.

**Merge window: 20 minutes, the same as NFL.**
- NHL starts are almost all on the hour or half hour (19:00 ET 484 games, 20:00 188, 22:00 153, 19:30 107).
  At 20 minutes, 19:00 and 19:30 stay two groups at T-6h and T-24h, so a label never covers a capture 30
  minutes early.
- At T-60m, the 17:40-18:35 ET quiet window already moves both 19:00 and 19:30 games to 18:35 ET, one call:
  - 19:00 games are captured at T-25m and 19:30 games at T-55m;
  - the recorded `deviation_minutes` keep this visible.

**Disclosure: many NHL "T-60m" captures are closer to the puck drop.** Over the published 2026-27 season
(`test_nhl_t60m_actual_leads_over_the_published_season`), the planned leads of the 1,344 T-60m targets are:

| Planned lead | Targets | Share | Why |
|---|---|---|---|
| T-60m | 750 | 55.8% | as labelled |
| T-55m | 107 | 8.0% | 19:30 ET games |
| T-40m | 2 | 0.1% | 19:15 ET games |
| **T-25m** | **484** | **36%** | 19:00 ET games |
| T-10m | 1 | 0.1% | an 18:45 ET game |

The deadline accepts a capture up to T-5m.

The quiet-window rule is kept, and the policy is not changed now. `odds status` reports planned and captured
lead bands: at least 55 min, 25–55 min, and under 25 min.

**Tracked follow-up (coordinator / owner).** Kalshi NHL (#136) reads the same 19:00 ET games at 17:35 ET (T-85m),
because the observe protected window runs to 18:50 ET. NHL sportsbook odds and the Kalshi books for those games
are therefore about 60 minutes apart. Unifying both under one shared protected-window contract is a follow-up
outside this ADR.
- Widening to 30 minutes would save about 21% of T-60m calls, but it would capture some games up to 30 minutes
  before their labelled horizon. It was not done to save credits.

### Provider rules re-verified (2026-09-29)

From the official v4 guide (https://the-odds-api.com/liveapi/guides/v4/), fetched 2026-09-29:
- the events endpoint: "This endpoint does not count against the usage quota.";
- the sports endpoint: the same;
- odds: `cost = [number of markets specified] x [number of regions specified]`;
- 10 bookmakers count as one region.

The markets page defines h2h as including "the draw for soccer" and lists `h2h_3_way` separately. The guide does
not document overtime or shootout treatment for hockey h2h, so the pairing rule refuses anything that is not two
outcomes, and each book's rules stay unverified (`rules_resolved=False`).

**NHL h2h in one region costs 1 credit a call**, whatever the number of games in the window.

### Switch, CLI and status

- `EDGE_LAB_ODDS_NHL=on` (exactly "on") enables NHL `odds run`. Anything else sends and writes nothing
  (`DISABLED`, exit 0). NHL `odds smoke` is refused in any case (rank-1 only).
- `install.sh` keeps the value across installs, like `EDGE_LAB_KALSHI_NFL_CAPTURE`. Unset means off.
- The CLI takes each sport's defaults from its policy.
- `odds plan --sport icehockey_nhl` is read-only and free, and it shows the joint proof and next month's joint
  projection.
- `odds status --sport X` (read-only, no network) reports that sport's coverage:
  - due now, attempted, captured, captured in the last 24 h;
  - whether the latest capture is stale (odds max_age 10 min);
  - discovery freshness;
  - games started, complete and incomplete;
  - MISSED reasons;
  - planned and captured lead bands.

## Tradeoffs

- **NHL coverage is back-loaded in a month where NFL reserves undiscovered weeks.** Measured October 2026: NFL's
  month-start worst case alone is the full 450, so NHL gets nothing until NFL's reservation releases. See
  `docs/research/NHL_ODDS_BUDGET_2026-10.md`. That is the correct result under NFL priority, and the decision to
  change it belongs to the owner. The options are listed there, and none is chosen.
- **The NHL tick does more work:** it reads NFL's stored targets and discovery. This is cheap: SQLite, a few
  hundred rows, no network.
- **The joint view of NFL is more conservative than NFL's own view** (EVENT_ABSENT rows, stale discovery). It can
  only give NHL less, never more.
- **An NFL alert tick skips that tick's NHL run.**
- **NFL demand growing inside its known horizon after NHL has spent is not reserved** (see above). A reschedule
  can cost an NFL slot.

## What would make us reconsider

- A second paid sport, or a paid tier: the rank-order rule still applies, but the policy table would need an
  explicit owner-set share.
- Evidence that the provider bills NHL h2h differently from `markets x regions`. The shared COST_ANOMALY block
  would stop both sports first.
- An NHL week above 40 groups, or a day above its weekday bound, would show up as SKIPPED_BUDGET for NHL's lowest
  class. It would mean re-deriving `NHL_WORST_CASE`.
- The owner choosing one of the budget options in the research doc.
