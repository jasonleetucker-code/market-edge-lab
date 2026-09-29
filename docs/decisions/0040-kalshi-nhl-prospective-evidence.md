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
- **Reschedule and cancellation** (review fix, PR #136). Checked against **every** event of a fresh discovery, not
  only the 72 h planning horizon, mapped or not, so a postponed game is never read at its old time:
  - a game listed with a different puck drop: its open targets are MISSED `SUPERSEDED_RESCHEDULED` (via
    `plan(closures=...)`);
  - a game absent from a fresh discovery whose requested window (`request.commence_from` / `commence_to`, as #137
    stores it) covers the planned puck drop: MISSED `SUPERSEDED_NOT_IN_SCHEDULE`;
  - absent from a discovery whose window is unknown: nothing is superseded (absence proves nothing); the count is
    reported (`absent_window_unknown`). A game that already started is outside any later window and is never
    superseded by its absence.
- **Stale or unreadable schedule:** plans nothing new and supersedes nothing. Open NHL **books are not read** while
  the schedule is not current (a reschedule could not be seen): the capture defers them (`nhl_deferred_schedule`)
  without recording anything; a fresh discovery before the deadline releases them, otherwise they expire MISSED
  `NOT_CAPTURED_SCHEDULE_STALE` (the schedule is read point in time at the deadline). The settled-markets read does
  not depend on the schedule and is not deferred.
- **Target ids** carry the puck drop they were planned for (`...|kalshi_nhl_schedule_v1:<horizon>:<commence>`): a
  small change that keeps the same ticks (e.g. +5 min) supersedes the old targets and plans new ids instead of
  colliding with them. A game that leaves the schedule and returns, or moves back to a time it was superseded from,
  would reuse an id (follow-up to #136): when every stored target of that id and its revisions is a supersession
  closure that never sent a GET, the horizon is re-planned under the next revision (`...:r<n>`, n = superseded
  predecessors; deterministic), so one provider omission never kills a game's horizons. A predecessor that was
  attempted or is still open keeps the reported `TARGET_ID_COLLISION` (its GETs already count against the
  game-horizon).
- **Opening night / activation:** a horizon whose deadline passed before the first NHL plan is stored MISSED
  `NOT_COLLECTED_BEFORE_ACTIVATION` (later gaps: `NOT_PLANNED_BEFORE_DEADLINE`) and never captured late. Only games
  still in the discovery are covered: a discovery lists future games only, so games that had already started at
  activation (such as the 2026-09-29 games) are **absent from NHL coverage**, not recorded MISSED. NHL targets carry
  origin `kalshi_nhl_schedule_v1` and their own id suffix, so they can never collide with, relabel or group with the
  coordinator's manual opening-night custom targets (origin `manual`).
- **Manual path:** `observe plan --custom-market` (origin `manual`) is operator-driven and is not covered by the NHL
  family guard (which holds any NHL-origin target outside `KXNHLGAME`, `NHL_FAMILY_NOT_ADMITTED`); the operator is
  responsible for what a manual target names.
- **Horizon labels:** a book is labelled with its nominal horizon **and** its actual lead (`lead_minutes` in the
  target detail). The Terminal shows e.g. "T-60m nominal · read T-85m (protected window)", never a bare "T-60m" for
  a book read at another lead. `observe status` shows no horizon label.

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
  - postponement / not started / cancelled **VERIFIED** (market rules text);
  - settlement sources: the event and series metadata list NHL and ESPN **without an order**; the order (the
    governing league first, then ESPN) is the contract terms' Source Agency list, stated there as hierarchical.
  - The clauses marked VERIFIED are quoted in `tests/fixtures/sports_nhl/kalshi_contract_terms_HOCKEYWINNINGINPERIOD_excerpt.txt`
    (checkable without a PDF tool; a test pins them).
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

### Activation dependency on NHL-A, and the NHL-C runbook

Kalshi NHL planning reads only the stored NHL discovery, which NHL-A (#137, ADR 0039, merged 7e0b81d) writes.
`tests/test_price_observations_nhl_with_odds_pilot.py` runs the planner on a discovery written by
`odds_pilot.run_tick` itself. As merged in #137:
- `odds run --sport icehockey_nhl` returns DISABLED **before discovery** unless `EDGE_LAB_ODDS_NHL=on` (and the Odds
  key is present), so no discovery is stored while NHL-A is off;
- `edgelab-odds.service` is `Type=oneshot` with the NFL `ExecStart` first: when the NFL line exits non-zero, the NHL
  line does not run on that tick.

So with NHL-A off or failing, this collector sits at `SCHEDULE_NO_DISCOVERY` (or `SCHEDULE_STALE` after 24 h) and
reads no NHL book, even with its own switch on. That is the intended fail-closed behaviour, not a fault.

NHL-C (activation, a reviewed operator step; deploy only through `docs/deploy/DAILY_SHADOW_ACTIVATION.md`, never in a
protected window):
1. Confirm NHL-A is live: `EDGE_LAB_ODDS_NHL=on` in `/etc/market-edge-lab/env` and a stored `icehockey_nhl` discovery
   younger than 24 h (the Terminal's Kalshi NHL block shows "Schedule current").
2. Preview read-only: `python -m edge_lab.price_observations nhl-dry-run --db /var/lib/market-edge-lab/db/edge_lab.sqlite3`
   (writes nothing, sends nothing). Check the schedule state, mapped/unmapped counts, the planned ticks and
   `budget.weekly_get_cap` 727.
3. Set `EDGE_LAB_KALSHI_NHL_CAPTURE=on` in `/etc/market-edge-lab/env` (install.sh keeps it). No unit changes.
4. After the next `edgelab-observe` ticks: `edge-lab observe status`, the freshness record `kalshi_nhl.game_books`
   and the Terminal block. Pause/rollback: set the switch to `off` (pending targets are held MISSED
   `NHL_CAPTURE_DISABLED`; stored evidence is kept).

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
