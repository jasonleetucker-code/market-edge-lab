# ADR 0040: Kalshi KXNHLGAME prospective evidence (schedule-driven, bounded, off until activation)

**Status:** Proposed 2026-09-29 (NHL-B, Writer B). Authority: the owner directive of 2026-09-29
(`docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`, issue #134): "Hockey starts tonight, so we need to
start collecting data for that as well." Activation is a later reviewed operator step (NHL-C). The Odds API side is
NHL-A (ADR 0039) and is not changed here.

**Classification: DATA_COLLECTION / DEVELOPMENT_ONLY.** NHL is not EXP-002, not a research family and has no
protocol. No NHL row enters `sports_evidence` joins, EXP-002 measurements or its sample. No model, no comparison, no
order.

## Problem

Opening-season pregame books cannot be reconstructed later. The only Kalshi sports collector is the NFL pairing of
#110, which plans a Kalshi book **reactively** at each Odds API NFL capture receipt. For NHL that coupling fails:
the free Odds budget will often not fund an NHL capture (NHL-A's quota proof decides), so a reactive NHL Kalshi
collector would collect nothing on exactly the days the budget is tight. We also must not:

- weaken or share the owner-approved NFL bound (295 GETs a week), its priority or its reports;
- starve EXP-001's protected collection or its close tick;
- fork a second collector, scheduler, timer, freshness system or dashboard;
- admit any hockey family other than the game winner.

## Decision

### Reuse: one pairing machinery, a policy per series

`price_observations` gains `SportsSeriesPolicy` and `SPORTS_SERIES = {"KXNFLGAME": NFL_POLICY, "KXNHLGAME":
NHL_POLICY}`. Each policy has its own origin, switch, role key, capture rank, attempt rule, GET bound and settled-read
page limit. The capture code (`_capture_kalshi_group`, the attempt-limit holds, the settled-markets read, the close
deferral, the quiet-failure rule) is shared and parameterized; the NFL constants, reasons and ids are unchanged.
`tests/test_price_observations_nhl_nfl_pin.py` pins a whole NFL game day (every report, target and observation row,
`status`, `market_history`, the dry run, a close run) against a golden generated from b944a0e **before** this
change: byte-identical.

NHL identity, rules text and the schedule read live in `sports_nhl.py` (pure, no dependency on
`price_observations`).

### Schedule-driven targets

- **Schedule:** the stored The Odds API quota-free `events` discovery for `icehockey_nhl` (source `the_odds_api`,
  kind `events`, entity the sport key, the shape `odds_api.save_snapshot` writes), newest received at or before
  `now`. A discovery older than 24 h (the Odds pilot's `discovery_max_age`) plans nothing new (fail closed). Games
  within 72 h are planned (it covers Kalshi's 48 h postponement rule, so an original date is stored before a
  reschedule can hide it).
- **Horizons:** T-6h and T-60m, both team markets. **No T-24h:** no NHL protocol needs it, the Odds side ranks it
  last, and it would add half again to the bound. A later reviewed change can add it.
- **Effective time:** the nominal time (puck drop − horizon) moves to the nearest `edgelab-observe` tick
  (:05/:20/:35/:50 ET) that no protected window refuses, that is at least 10 min before puck drop and that holds
  fewer than 8 NHL game-horizons; a tie goes to the earlier tick. Both times, the shift and its reason are stored in
  the target detail. Games with the same effective tick share the run.
  - Over the 2026-27 schedule this moves 594 of 1,344 T-60m targets out of the EXP-001 window (17:40-18:50 ET): a
    19:00 ET game's T-60m is read at 17:35 ET (T-85m, 483 games), a 19:30 game's at 18:50 ET (T-40m, 107 games).
    Of the rest, all but 6 targets are within 5 min of nominal; those 6 are within 40 min (protected windows or a
    full tick).
- **No reactive pairing to NHL Odds captures (the optional part of the assignment):** not built. The schedule
  targets already sit within about 5 min of the Odds T-6h / T-60m ticks, and a second reactive read would add GETs
  outside the derived bound and couple this collector to NHL-A's target shape. A future NHL protocol can request it.
- **Mapping:** Odds team names → Kalshi abbreviations and labels (a 32-team table). The event ticker uses the ET date
  of the original puck drop. An unknown team, two Odds events mapping to one ticker, a stored listing that lacks a
  market or labels it differently, or a stored listing whose `occurrence_datetime` is not within 2 h of puck drop
  + 3 h (the offset observed for every listed game) is UNMAPPED and counted, never guessed. Without a stored listing
  the tickers are DERIVED and the capture's own listing GET verifies them (the NFL rule).
- **Reschedule:** a new puck drop supersedes the event's open targets (MISSED `SUPERSEDED_RESCHEDULED`, via
  `plan(closures=...)`), mapped or not, so a postponed game is never read at its old time.
- **Opening night / activation:** a horizon whose deadline passed before the first NHL plan is stored MISSED
  `NOT_COLLECTED_BEFORE_ACTIVATION` (later gaps: `NOT_PLANNED_BEFORE_DEADLINE`) and never captured late. NHL targets
  carry origin `kalshi_nhl_schedule_v1` and a target id suffixed `|kalshi_nhl_schedule_v1:<horizon>`, so they can
  never collide with, relabel or group with the coordinator's manual opening-night custom targets (origin `manual`).

### The request bound (its own, never shared with NFL)

Kalshi public, unauthenticated GETs only (`sources.kalshi_public`); zero Odds API calls.

| Unit | GETs |
|---|---|
| Per game-horizon attempt | 1 listing page + 2 books = 3, no in-run retry |
| Per game-horizon | at most 2 attempts (the retry is the next tick) = **6** |
| Per ET game day, settled read | 1, never retried, one page (limit 100; a day has at most 32 markets) |
| Per run (NHL share) | **24** (8 game-horizons), only after every EXP-001 / ADR 0030 and NFL target, only from what the run has left (40 GETs, 24 markets); none in a run with a due close target |
| Per NHL week (Mon-Sun ET, by target time) | ≤ 120 game-horizons × 6 + 7 reads = **727** |

Derivation from the published 2026-27 regular season (`api-web.nhle.com/v1/schedule/<date>`, weekly pages read once
on 2026-09-29; `tests/fixtures/sports_nhl/nhl_schedule_2026_27_regular_season.json`): 1,344 games on 185 days; at
most 16 games on one ET day, 57 in one Monday-start week, 60 in any 7 days; at most 9 at one start time. 60 games × 2
horizons = 120 game-horizons (the planner's placement puts at most 114 in one week and at most 8 on one tick).

- Heaviest day (16 games): 32 game-horizons, expected 96 + 1 GETs, worst 192 + 1.
- Heaviest week: expected 342 + 7 = 349 GETs, worst 684 + 7 = 691 ≤ 727.
- Season: expected 2,688 × 3 + 185 = 8,249 GETs (about 295 a week), worst 16,313.

`tests/test_price_observations_nhl.py` checks the placement over the whole season and runs the heaviest day through
the real plan and capture path (every run ≤ 24 GETs, 97 GETs in total).

### Rules, fees, units

- Rules text is hashed per row as for NFL (`kalshi_quotes.rules_sha256`) and parsed literally
  (`sports_nhl.nhl_rules_clauses`): win condition, official final result, 48 h postponement window, fair-price
  fallback, the originally scheduled date. On all 86 markets listed on 2026-09-29 these were found; overtime,
  shootout and ties are **not stated** in the market text.
- Contract terms (series `contract_terms_url`, the generic HOCKEYWINNINGINPERIOD rulebook, sha256 `4243633b…`):
  - overtime **VERIFIED** included (the default time period is regulation plus overtime);
  - shootout **RULES_UNRESOLVED** (winning is defined by goals in regulation plus overtime; the shootout is never
    mentioned; the market's "wins the game" on the official final result makes a shootout winner the likely reading,
    not a stated rule);
  - tie **RULES_UNRESOLVED** (no tie payout stated; a drawn team "may" resolve No);
  - postponement / not started / cancelled **VERIFIED** (market rules text); settlement sources NHL, then ESPN.
- Fees: **FEE_UNSUPPORTED.** The series reads `fee_type quadratic_with_maker_fees`, `fee_multiplier 1`, but no fee
  verification record covers KXNHLGAME; nothing is priced and no fee is set to 0. Note for the fee owner:
  `fee_schedules.schedule_for("kalshi", "KXNHLGAME")` routes to the general quadratic schedule because KXNHLGAME is
  not on the captured non-standard list; this collector never calls it.
- Units: $1.00-notional binary contracts, dollar prices, `linear_cent` grid (as NFL records them).

### Outcomes are labels, pregame books are features

No NHL protocol exists, so no pregame horizon is a label. NHL T-6h and T-60m books are shown as features. Outcomes
(the settled-markets read: results, settlement values, any OT/SO status) are withheld from ordinary views:
`market_history` drops the figures and reduces the reason to its code ("withheld (NHL outcome)"); `status` does the
same for a missed read's reason; the Terminal shows counts only. A future NHL protocol decides its own label
horizons (it may then need to withhold T-60m books, as EXP-002 does for NFL).

### Switch, freshness, Terminal

- `EDGE_LAB_KALSHI_NHL_CAPTURE`: only `on` enables; unset, empty and `off` are off; anything else is INVALID (off).
  Off plans nothing, attempts nothing (pending targets are held MISSED `NHL_CAPTURE_DISABLED`) and leaves the
  `observe plan` report exactly as before (no `nhl` key). `install.sh` keeps it across installs like the NFL switch.
- Freshness: a separate source `kalshi_public_nhl_game` (registry, PLANNED) and fabric record
  `kalshi_nhl.game_books` built from NHL targets only; the ADR 0030 records exclude every sports target. Never
  decision-grade. The supervisor has no environment file, so it cannot read the switch: with no NHL target, or
  the newest held by the switch, the record is PAUSED and says so.
- Terminal: one compact block on Research & Data › Data sources (UI_CONTRACT 2026-09-29 (e)).

## Alternatives considered

- **Reactive pairing to NHL Odds captures (the NFL way).** Rejected as the primary path: Kalshi coverage would
  depend on the Odds budget.
- **A new module, timer or unit for NHL.** Rejected: the existing observe timer, collector lock, pacer and protected
  windows already fit; a new timer needs owner approval.
- **Sharing the NFL weekly bound.** Rejected by the directive: the NFL approval is unchanged.
- **Snapping T-60m after the EXP-001 window only.** Rejected: an 18:50 ET read of a 19:00 game is 10 min before puck
  drop; the nearest-tick rule keeps it at 17:35 ET and records the shift.

## Tradeoffs

- 594 T-60m reads per season are not near T-60m; both times are stored and a protocol can choose.
- A book of a game with a manual custom target at the same tick is read twice in that run (separate groups).
- The Odds API team names are unverified until the first stored NHL discovery; unknown names fail closed and are
  counted on the Terminal.

## Reconsider if

- a future NHL protocol needs other horizons, reactive pairing, or T-60m withheld as a label;
- Kalshi lists more than one KXNHLGAME event per team pair and date (doubleheaders), or changes the occurrence offset;
- the schedule grows beyond 60 games in 7 days or 8 at one tick for many games;
- KXNHLGAME fees are verified, or the shootout reading is confirmed by Kalshi.
