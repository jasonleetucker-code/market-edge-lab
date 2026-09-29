# NHL Odds API budget, September to October 2026: the combined NFL + NHL quota proof

**Status:** NHL-A analysis, 2026-09-29. Research only: nothing here is activated, and nothing here authorizes
spend. Design: ADR 0039. Owner direction: issue #134 and `docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`.

Every number below is computed by the real planner (`odds_schedule.joint_budget`, the same function the NHL tick
runs). `tests/test_odds_nhl_budget.py` recomputes and pins them. Run `python tests/test_odds_nhl_budget.py` to
print the tables.

## Bottom line

- **September 2026 has room.** NHL may commit up to **402 credits** after NFL. Every NHL T-60m slot still ahead in
  September UTC is admissible: 6 slots (1 credit each) from the measurement time, and **1 slot on Sep 30**. T-6h
  also fits in September (5 more slots).
- **Early October has none.** From 2026-10-01 00:00Z, NFL's own worst case fills the whole 450-credit ceiling:
  its known week plus the `NFL_WORST_CASE` reservation for weeks not yet listed. Under NFL priority, **NHL is
  admitted zero credits** until that reservation releases.
- **October NHL coverage is back-loaded, under the modelled NFL listing behaviour.**
  - At T-60m only, NHL captures **103 of 118** October T-60m slots. The first capture is on **Sun Oct 4**.
  - Every T-60m slot of Sep 30 (late game) to Sat Oct 3 is lost: 15 slots, the first days of the season.
  - Adding T-6h does not displace any T-60m capture. It adds 48 of 121 T-6h slots, all from Oct 4 on, most after
    Oct 18. In the first half of October, T-6h does not fit.
- **Month totals, October.**
  - At month start, the joint proof gives **worst 450, expected 270**, with NHL at 0. This matches the
    coordinator's production reading exactly.
  - Replayed through the month: **337 credits** at T-60m only (NFL 234 + NHL 103), or **385** with T-6h (NFL 234
    + NHL 151).
  - NFL's captures are identical in every NHL scenario.

This is the honest result. `NFL_WORST_CASE` was **not** weakened to make NHL fit. The owner's options are at the
end, and none is chosen.

## Inputs

| Input | Value | Source |
|---|---|---|
| Ceiling | 450 credits a month, one for all sports | EXECUTION_PLAN; `PilotConfig.ceiling` |
| Reserve | 3 credits (a manual smoke read or an ambiguous failure) | `PilotConfig.reserve_credits` |
| September spent / provider remaining | 45 / 455 | measured by the coordinator, 2026-09-29 ~17:20Z |
| NFL cost per call | 3 (h2h, spreads, totals x us) | policy; production `x-requests-last` |
| NHL cost per call | 1 (h2h x us) | v4 guide, re-read 2026-09-29: `cost = markets x regions` |
| NFL known horizon on 2026-09-29 | 2026-10-06 00:15Z (MNF Oct 5) | measured |
| NFL October projection (NFL alone) | worst 450, expected 270 | measured |
| NHL schedule | 2026-27 regular season, 1,344 games | NHL public schedule API, fetched 2026-09-29 17:29Z (ADR 0039) |
| `NHL_WORST_CASE` | 40 groups a week; Mon..Sun 8, 11, 6, 7, 8, 10, 9; expected 28 | ADR 0039 derivation |

The events and sports endpoints cost nothing: the v4 guide, fetched 2026-09-29, says "This endpoint does not
count against the usage quota." NHL discovery is therefore free.

## September (measured reading: 45 spent, 455 remaining)

Arithmetic: `headroom = min(450 - 45, 455 - 0) - 3 = 402`.

- **NFL's September future is zero.** Its next target, TNF Oct 1's T-24h, is due at 2026-10-01 00:15Z, which is
  October UTC. Its unknown window starts at its horizon (Oct 6), after September ends.
  - NFL worst case for September = 45 + 3 = **48**, as measured.
- **NHL may commit 402 credits** (`test_september_headroom_and_sep30_t60m`).

NHL T-60m slots still ahead in September UTC at 17:20Z on Sep 29 (one credit each; all admitted):

| Slot (UTC) | ET | Games |
|---|---|---|
| 09-29 20:00 | Tue 16:00 | FLA@CAR 17:00 |
| 09-29 22:35 | Tue 18:35 (moved out of the quiet window) | MTL@TOR 19:00 |
| 09-29 23:00 | Tue 19:00 | NYR@BOS 20:00 |
| 09-30 01:00 | Tue 21:00 | VAN@EDM 22:00 |
| 09-30 01:30 | Tue 21:30 | CHI@VGK 22:30 |
| **09-30 22:35** | **Wed 18:35** | **the two 19:30 ET games, one call** |

With these admitted, the joint September worst case is 45 + 3 + 6 = **54**.

**Sep 30 has exactly one September T-60m slot.** The 22:00 ET game's T-60m is 21:00 ET = **01:00Z Oct 1**. That
is an October slot, and it falls under October's proof (see below: not admissible).

The collector is not active tonight. Every Sep 29 slot will be MISSED: the games are over before activation, and
they have no Odds target, because the collector never saw their provider events. The manual Kalshi observations
(#135) are the only opening-night record.

**With T-6h as well**, September has 5 more slots (Sep 29 13:00, 14:00 and 16:30 ET; Sep 30 13:30 and 16:00 ET).
All fit (11 slots, 11 credits).

## October: why NHL starts at zero

At 2026-10-01 00:00Z the provider has reset (0 used, 500 remaining), so the ceiling binds:
`headroom = min(450 - 0, 500 - 0) - 3 = 447`.

**NFL, rank 1, is served first:**

1. **Known slots.** The listed week Oct 1-5 has 6 kickoff groups (TNF, Sun early, 13:00, 16:05/16:25, SNF, MNF).
   That is 6 x 3 classes = 18 slots x 3 credits = **54**. Remaining: 393.
2. **Unknown weeks.** ET dates from the NFL horizon (Oct 5 ET) to Nov 1 ET are 28 dates, which is 4 full weeks
   x 11 groups = **44 groups per class**.
   - T-60m reserves 44 x 3 = 132 (remaining 261).
   - T-6h reserves 132 (remaining 129).
   - T-24h can reserve only 43 of 44 (129 credits). **One NFL worst-case call is unreservable.**
3. **NFL worst** = 0 + 3 + 54 + 393 = **450**. **NFL expected** = 54 + 3 classes x 24 expected groups
   (`ceil(28 x 6/7)`) x 3 = 54 + 216 = **270**. Both reproduce the production projection.

**NHL, rank 2.** NFL's own worst case does not fit, so NHL is admitted **0** of its 118 October T-60m slots
(`test_october_month_start_nfl_fills_the_ceiling_and_nhl_gets_zero`, `blocked_by: americanfootball_nfl`).

## October by date: how NFL's reservation releases

NFL's reservation releases in two ways:
- the provider lists the next NFL week, whose known slots (6 groups a week) replace the 11-group assumption;
- the unknown window shrinks as the month passes.

NFL's own captures do not release anything: each one spends exactly what it reserved. Neither does NHL
spending, which is only ever admitted from what is left.

**Model.** The replay (`replay()` in the test) runs the production order every 15 minutes: NFL tick, then NHL
tick, at most one paid call each, the quiet window respected. Its assumptions:
- every October NFL week has the same 6 groups;
- the provider lists NFL games **7 days ahead**, which matches the one measured point (horizon Oct 6 on Sep 29);
- every call is charged its estimate;
- every capture succeeds.

"NHL credits admissible at day start" is NHL's share of the joint proof at that ET day's first tick: what NHL
could still commit this month after NFL's full worst case.

### T-60m only (the owner's default)

The "Wed 09-30" row is the part of Sep 30 ET that is already October UTC (after 20:00 ET).

| ET date | NHL slots due | NHL captured | NHL skipped | NHL credits admissible at day start | NFL calls | spent at day end |
|---|---|---|---|---|---|---|
| Wed 09-30 | 1 | 0 | 1 | 0 | 1 | 3 |
| Thu 10-01 | 5 | 0 | 5 | 0 | 2 | 9 |
| Fri 10-02 | 5 | 0 | 5 | 0 | 0 | 9 |
| Sat 10-03 | 4 | 0 | 4 | 0 | 4 | 21 |
| Sun 10-04 | 4 | 4 | 0 | 0 | 9 | 52 |
| Mon 10-05 | 2 | 2 | 0 | 11 | 2 | 60 |
| Tue 10-06 | 3 | 3 | 0 | 36 | 0 | 63 |
| Wed 10-07 | 2 | 2 | 0 | 33 | 1 | 68 |
| Thu 10-08 | 4 | 4 | 0 | 31 | 2 | 78 |
| Fri 10-09 | 2 | 2 | 0 | 18 | 0 | 80 |
| Sat 10-10 | 6 | 6 | 0 | 16 | 4 | 98 |
| Sun 10-11 | 3 | 3 | 0 | 10 | 9 | 128 |
| Mon 10-12 | 3 | 3 | 0 | 34 | 2 | 137 |
| Tue 10-13 | 9 | 9 | 0 | 58 | 0 | 146 |
| Wed 10-14 | 2 | 2 | 0 | 49 | 1 | 151 |
| Thu 10-15 | 4 | 4 | 0 | 47 | 2 | 161 |
| Fri 10-16 | 2 | 2 | 0 | 34 | 0 | 163 |
| Sat 10-17 | 8 | 8 | 0 | 32 | 4 | 183 |
| Sun 10-18 | 2 | 2 | 0 | 24 | 9 | 212 |
| Mon 10-19 | 2 | 2 | 0 | 49 | 2 | 220 |
| Tue 10-20 | 5 | 5 | 0 | 74 | 0 | 225 |
| Wed 10-21 | 1 | 1 | 0 | 69 | 1 | 229 |
| Thu 10-22 | 4 | 4 | 0 | 68 | 2 | 239 |
| Fri 10-23 | 2 | 2 | 0 | 55 | 0 | 241 |
| Sat 10-24 | 5 | 5 | 0 | 53 | 4 | 258 |
| Sun 10-25 | 5 | 5 | 0 | 48 | 9 | 290 |
| Mon 10-26 | 3 | 3 | 0 | 133 | 2 | 299 |
| Tue 10-27 | 5 | 5 | 0 | 130 | 0 | 304 |
| Wed 10-28 | 4 | 4 | 0 | 125 | 1 | 311 |
| Thu 10-29 | 3 | 3 | 0 | 121 | 2 | 320 |
| Fri 10-30 | 3 | 3 | 0 | 118 | 0 | 323 |
| Sat 10-31 | 5 | 5 | 0 | 115 | 3 | 337 |

**Totals.** 118 NHL T-60m slots are due in October UTC, and 103 are captured (87%). Credits spent: 337 = NFL 234
(78 calls) + NHL 103. The first NHL capture is on Sun Oct 4, once enough of NFL's next week is listed for
its worst case to fit.

### T-6h added (T-6h + T-60m)

| ET date | NHL slots due | NHL captured | NHL skipped | NHL credits admissible at day start | NFL calls | spent at day end |
|---|---|---|---|---|---|---|
| Wed 09-30 | 1 | 0 | 1 | 0 | 1 | 3 |
| Thu 10-01 | 10 | 0 | 10 | 0 | 2 | 9 |
| Fri 10-02 | 10 | 0 | 10 | 0 | 0 | 9 |
| Sat 10-03 | 9 | 0 | 9 | 0 | 4 | 21 |
| Sun 10-04 | 7 | 4 | 3 | 0 | 9 | 52 |
| Mon 10-05 | 5 | 2 | 3 | 11 | 2 | 60 |
| Tue 10-06 | 7 | 3 | 4 | 36 | 0 | 63 |
| Wed 10-07 | 4 | 2 | 2 | 33 | 1 | 68 |
| Thu 10-08 | 9 | 4 | 5 | 31 | 2 | 78 |
| Fri 10-09 | 4 | 2 | 2 | 18 | 0 | 80 |
| Sat 10-10 | 12 | 6 | 6 | 16 | 4 | 98 |
| Sun 10-11 | 6 | 3 | 3 | 10 | 9 | 128 |
| Mon 10-12 | 6 | 3 | 3 | 34 | 2 | 137 |
| Tue 10-13 | 18 | 9 | 9 | 58 | 0 | 146 |
| Wed 10-14 | 4 | 2 | 2 | 49 | 1 | 151 |
| Thu 10-15 | 9 | 4 | 5 | 47 | 2 | 161 |
| Fri 10-16 | 4 | 2 | 2 | 34 | 0 | 163 |
| Sat 10-17 | 14 | 8 | 6 | 32 | 4 | 183 |
| Sun 10-18 | 4 | 4 | 0 | 24 | 9 | 214 |
| Mon 10-19 | 5 | 2 | 3 | 47 | 2 | 222 |
| Tue 10-20 | 10 | 10 | 0 | 72 | 0 | 232 |
| Wed 10-21 | 2 | 2 | 0 | 62 | 1 | 237 |
| Thu 10-22 | 9 | 9 | 0 | 60 | 2 | 252 |
| Fri 10-23 | 4 | 4 | 0 | 42 | 0 | 256 |
| Sat 10-24 | 10 | 10 | 0 | 38 | 4 | 278 |
| Sun 10-25 | 9 | 9 | 0 | 28 | 9 | 314 |
| Mon 10-26 | 6 | 6 | 0 | 109 | 2 | 326 |
| Tue 10-27 | 10 | 10 | 0 | 103 | 0 | 336 |
| Wed 10-28 | 8 | 8 | 0 | 93 | 1 | 347 |
| Thu 10-29 | 7 | 7 | 0 | 85 | 2 | 360 |
| Fri 10-30 | 6 | 6 | 0 | 78 | 0 | 366 |
| Sat 10-31 | 10 | 10 | 0 | 72 | 3 | 385 |

**Totals.** 239 slots are due (118 T-60m + 121 T-6h), and 151 are captured: T-60m 103 (unchanged) and T-6h 48.
Credits spent: 385 = NFL 234 + NHL 151.

**Does T-6h fit? Only partly.** The joint proof admits T-6h only after every T-60m slot and T-60m reservation,
so T-6h never costs a T-60m capture (`test_t6h_never_displaces_t60m_and_nfl_spend_is_unchanged`). In the first
half of October it is mostly SKIPPED_BUDGET. From Oct 20 it is fully captured. T-24h was not evaluated further:
T-6h already does not fully fit.

### Month totals (October 2026)

| | Joint worst (month start) | Joint expected (month start) | Replayed spend | NHL captured / due |
|---|---|---|---|---|
| NFL only (measured) | 450 | 270 | 234 (model) | n/a |
| NFL + NHL T-60m | 450 (NHL 0) | 270 (NHL 0) | 337 | 103 / 118 |
| NFL + NHL T-6h + T-60m | 450 (NHL 0) | 270 (NHL 0) | 385 | 151 / 239 |

The month-start worst case is at the ceiling in every row. **The invariant held at every tick of every replay**,
and `joint_budget` raises `BudgetInvariantError` otherwise.

### Sensitivity: how far ahead the provider lists NFL games

The release depends on how far ahead the provider lists NFL games, and that was measured once. If it lists 14
days ahead, NFL's worst case fits from Oct 1, and NHL T-60m captures **118 of 118** (spend 352). If it lists fewer
than 7, NHL starts later than Oct 4. The Odds tick's `joint_budget` report shows the live figure every tick. After
activation, `odds plan --sport icehockey_nhl --offline` shows it without spending anything.

## Owner options (listed, not chosen)

October NHL coverage is poor for the first days of the season: T-60m is lost for Sep 30 (late game) to Oct 3,
which is 15 slots.

- **(a) Accept back-loaded NHL coverage.** Nothing changes. NHL T-60m runs from about Oct 4 (under the model),
  and fully once NFL's reservation releases. Opening-week T-60m is lost and recorded as SKIPPED_BUDGET / MISSED,
  never backfilled.
- **(b) An evidence-backed seasonal NFL worst case for October.** For example, no Saturday NFL games and no
  holiday slate in October. It must stay a **true upper bound**, sourced from the published NFL schedule and
  reviewed (ADR 0029 evidence rules).
  - Illustration only, not a proposal: with an October bound of 7 NFL groups a week, NHL T-60m would capture
    118 of 118, with 141 credits admissible on Oct 1 and a replayed spend of 352
    (`test_an_illustrative_seasonal_nfl_bound_is_what_would_change_october`).
  - Whether 7 is a true bound for October 2026 has **not** been checked.
- **(c) Reduce NFL's lowest-priority class,** for example NFL T-24h. At month start, each NFL class holds
  about 150 credits of the October worst case (18 for the listed week, up to 132 for unlisted weeks). This changes the owner-approved NFL pilot, so it is an owner decision.
- **(d) A paid tier.** This is the owner's decision, and it never happens automatically. No paid plan is used or
  prepared here.

## What this does not claim

- It does not claim the modelled NFL weeks are the real 2026 October NFL schedule. The real known slots replace
  the model tick by tick in production.
- It does not claim NHL books price h2h identically. Two-outcome h2h is assumed from US-book practice and is not
  documented by the provider; anything else is recorded as NOT_TWO_WAY.
- It does not claim anything is activated. The NHL line is off until `EDGE_LAB_ODDS_NHL=on` (NHL-C, a reviewed
  operator step).
