# Family A paired evidence: data-gap inventory and the smallest capture extension

Economic Evidence v1, PR C (EE Writer 2). Date: 2026-09-25 (America/New_York evening of 2026-09-24).
Family A = EXP-002 (DRAFT), sportsbook consensus vs executable event-market prices, NFL pregame
moneyline. Code: `src/edge_lab/sports_evidence.py`. Tests: `tests/test_sports_evidence.py`.

**Status: research document. It authorizes nothing.** It records what stored evidence can and cannot
answer today, and the exact bounded collection that would close the gap. Activating that collection
needs an owner decision recorded in `docs/EXECUTION_PLAN.md`; current authority does **not** cover it.

## 1. What was checked, and how

| Evidence | Source | State |
|---|---|---|
| Odds API NFL capture targets and odds snapshots | production evidence store (VPS) | **Not read by this session.** The laptop has no access to the production DB. HANDOFF.md (2026-09-25 01:57Z) reports 95 planned NFL targets and 2 CAPTURED (ATL@GB T-6h and T-60m, 2026-09-24). Those are historical reports, not measurements made here. |
| Kalshi KXNFLGAME listings, books, resolutions | production evidence store | **None exist.** No collector stores KXNFLGAME (`SOURCE_READINESS.md`: "Kalshi not captured"; no code path writes it). |
| Kalshi KXNFLGAME existence, rules, fee type | 2 bounded public GETs from the laptop, 2026-09-25 02:24Z | Recorded byte-for-byte in `tests/fixtures/sports_evidence/` with a request log (section 3). |
| Polymarket US NFL | production store | Pilot first captures are due 2026-09-26; RELATED_NOT_EQUIVALENT by construction. |
| Repo fixtures | `tests/browser/fixture_states.py` (`odds`, `odds_issues`), `edge_lab.dashboard.sports_fixtures` | Used for every result below. The SYNTHETIC pairing fixture uses real team names and synthetic prices. |

**Run it on production (read-only, network-free, bounded):**

```
sudo -u edgelab /opt/market-edge-lab/venv/bin/python -m edge_lab.sports_evidence report \
    --db /var/lib/market-edge-lab/edge_lab.sqlite3 --summary
```

It opens the store with `SnapshotStore.open_readonly` (mode=ro, query_only), makes no request, writes
nothing unless `--out` is given, parses at most 600 listing snapshots and one odds payload per capture
slot, and states its bounds in `bounds`. Outcome results are withheld unless `--with-results` is passed;
a run that views results of an evaluation window must be logged in EXP-002's `evidence_use.jsonl`.

**Result on the production-shaped fixture** (`odds`, as production held it on 2026-09-24, as-of
2026-09-24 21:00Z): 95 horizons planned, 1 due, 94 not yet due, 0 paired. The single due horizon has a
usable, fresh two-book consensus and no Kalshi listing (`KALSHI_NOT_MAPPED`, `NO_LISTING`). In the
protocol attrition (EXP-002): 32 games, Kalshi markets **unknown** (no listing stored, so not 0), 190
opportunities, 0 eligible, signals and fills **not evaluated** (None). Economic screen:
INSUFFICIENT_EVIDENCE. Every production horizon that falls due will fail the same way until KXNFLGAME
books are stored.

## 2. Why current evidence cannot answer the question

EXP-002 asks whether the sportsbook consensus carries information about an **executable** event-market
price for a payoff-equivalent contract. Stored evidence has only the sportsbook side:

1. No exchange price exists at any sportsbook capture time, and a later book is never substituted.
2. No KXNFLGAME rule version is stored, so no market can be mapped or its rules proven at a cutoff.
3. No KXNFLGAME resolution is stored, so no outcome label exists.
4. The contract is not payoff-equivalent to a two-way de-vig (section 4), and EXP-002's universe
   excludes an unmapped tie / void state.
5. KXNFLGAME fees are unsupported in the registry, so no all-in cost exists at any size.
6. EXP-002 is DRAFT: the primary endpoint, cutoffs, maximum input age and pair skew, size ladder,
   episode definition and futility rule are UNKNOWN. No signal, episode or screen can be evaluated.
7. Sampling is three pregame horizons (T-24h, T-6h, T-60m). Nothing stored or planned can establish a
   seconds-level lag. Claims must stay at horizon resolution, with the pair skew disclosed.

## 3. Verification reads (owner allowance: at most 20 GETs, paced, logged)

Two requests were sent (a third attempt failed locally before any connection; logged).

| Time (UTC) | GET | Result | sha256 |
|---|---|---|---|
| 02:24:44 | `/trade-api/v2/events?series_ticker=KXNFLGAME&status=open&limit=50&with_nested_markets=true` | 200, 158,491 B, cursor empty | `53b83b84…` |
| 02:24:48 | `/trade-api/v2/series/KXNFLGAME` | 200, 1,554 B | `d2ec6e7d…` |

What they show (facts, UNVERIFIED beyond these captures):

- **Existence.** 32 open KXNFLGAME events (week 3 through the week 4 Monday game), 2 binary markets
  per game (one per team), $1 notional. Tickers are `KXNFLGAME-<YY><MON><DD><AWAY><HOME>-<TEAM>`; the
  date is the New York date the game was "originally scheduled". The 32-team table in
  `sports_evidence.NFL_TEAMS` matches every recorded label and abbreviation (tested).
- **Rules** (the same clauses on all 64 markets): YES if the team wins the game; **a tie resolves to
  $0.50 for each team**; a postponed game that starts within 48 h resolves on the official final
  result; **not started within 48 h resolves to a fair price**. Overtime is not mentioned (the
  "winner of the game" is the official result). Settlement source: "the Governing League" (nfl.com).
- **Fees.** The series reports `fee_type` `quadratic_with_maker_fees`, `fee_multiplier` 1. The repo's
  fee registry lists KXNFLGAME on the PDF's non-standard list, so it stays **FEE_UNSUPPORTED**. The
  conflict needs a primary-source re-check (`fee_schedules.py`, Writer 1's file).
- No order book, settlement read or evidence-store write was made.

## 4. Payoff mapping: related by game and team, not equivalent

For a team with probability `p` of winning **given a decided game**, which is what a two-way de-vig
estimates if the books void or push ties (their rules are not in the Odds API data, so this is
UNVERIFIED), a tie probability `t`, a not-played probability `u` and an unknown fair price `F`:

```
fair(YES) = (1 - t - u) * p + 0.50 * t + u * F,    F in [0, 1]
```

This is linear in `t`, `u` and `F`, so declared bounds give an exact interval
(`sports_evidence.tie_adjusted_interval`). Without declared bounds no fair-value comparison exists. The
join therefore labels every KXNFLGAME pair **CONDITIONAL_MAPPING**, `equivalent: false`. It keeps the
evidence and its unadjusted gap as research data with `comparison_claim: NONE`. Under EXP-002's
universe, the protocol attrition marks the pair RULES_UNRESOLVED unless the protocol accepts the
conditional mapping (`JoinPolicy.conditional_mapping_accepted`). Polymarket US markets stay
RELATED_NOT_EQUIVALENT. They are listed per horizon and never compared.

## 5. Gap inventory (what `report` emits as `gaps`)

| id | Stream | State today | Why it blocks | Smallest fix |
|---|---|---|---|---|
| G1 | KXNFLGAME listings (tickers, rules, status, result) | MISSING | no mapping, no rules version at a cutoff | one listing GET per game per horizon (section 6) |
| G2 | KXNFLGAME books at the Odds horizons | MISSING (every due horizon; by horizon in the report) | no executable price at any capture time | two book GETs per game per horizon (section 6) |
| G3 | KXNFLGAME resolutions | MISSING | no outcome label | one settled-markets read per game day (section 6) |
| G4 | KXNFLGAME fee schedule | UNSUPPORTED | no all-in cost | re-verify the fee PDF; record in `fee_schedules` (Writer 1) |
| G5 | tie and not-played probability bounds | UNKNOWN (protocol input) | no fair-value interval | declare in EXP-002 before outcomes are viewed |
| G6 | sportsbook tie / void rules | UNVERIFIED | the consensus's conditioning is assumed | document the assumption in EXP-002 |
| G7 | EXP-002 decision fields | DRAFT (endpoint, cutoffs, skew, size ladder, episode, futility) | no signal, episode or screen | settle and freeze (Writer 1's file) |
| G8 | tie / not-played payoff mapping | UNRESOLVED | the EXP-002 universe excludes it | the protocol accepts the conditional mapping with bounds, or excludes Kalshi |

Missing counts by horizon come from the report on the real store (`gaps[G2].by_horizon`); the
production numbers are not available to this session.

## 6. The smallest justified capture extension (a decision packet, NOT activated)

**Scope.** KXNFLGAME only: both team markets of each game the Odds pilot already targets, at the
pilot's existing T-24h / T-6h / T-60m target times. No NCAAF, no other market type, no new horizon.

**Adapters (existing, no new collector).** `price_observations.custom_target(venue="kalshi", ...)`
already plans a Kalshi observation of any market. `price_observations.capture` already stores:
- the event listing (`kind=markets`, entity = event ticker, with rules and status);
- the depth-100 order book (`kind=orderbook`);
- a `price_observations` row with rules hash, depth and freshness.

It paces through the shared Kalshi pacer, refuses to run in the protected windows (11:13–11:30,
16:13–16:30, 17:40–18:50 ET) and caps a run at 24 markets and 40 GETs. `sports_evidence` already reads
exactly these shapes. The only new code is a planner that turns each Odds target into two custom targets
at its effective due time: about 30 lines in `price_observations` or `odds_pilot`, which are not this
writer's files.

**Schedule.** Due at the Odds target's effective due time and captured by the existing
`edgelab-observe` tick (:05/:20/:35/:50 ET). `edgelab-odds` ticks at :00/:15/:30/:45, so the book
typically lands about 5 min after the odds response. That is at the join's 5-minute pair-skew limit,
so many pairs would fail. There are two ways out:
- (a) EXP-002 freezes a maximum pair skew of 10 min and discloses it;
- (b) the book is captured in the same run as the odds, a runner change that needs review.

Option (a) is the smallest.

**Worst-case requests.** Per game-horizon: 1 listing + 2 books = 3 GETs, and at most 6 with one retry
each.
- A normal NFL week is about 16 games × 3 horizons = 48 targets: **144 GETs**, worst **288**.
- The busiest capture day (Sunday: T-6h and T-60m for about 13 games, plus Monday's T-24h) is about
  28 targets: **84 GETs**, worst **168**.
- These are spread over the day's kickoff groups. One 1 pm slot is about 10 games: 30 GETs, inside one
  observe run's 40-GET cap.

**Settlement.** One settled-markets read per game day after expected expiration: 1–2 GETs a day, 7 at
most a week.

**Bytes.** Measured: listing 5.2 KB per event. Estimated: book 2–6 KB at depth 100. That is about
15 KB per target, about **0.7 MB a week** and about 15 MB a season including playoffs. It fits inside
the acquisition portfolio's estimate for this stream.

**Permissions.** Kalshi public, unauthenticated market data (`sources.kalshi_public`). No key, no
account, no order endpoint, no redistribution.

**Quota interaction.** **Zero Odds API credits.** The 450-credit cap is untouched and no Odds call is
added. It shares the Kalshi pacer with EXP-001, so it stays out of the protected windows through
`price_observations`.

**Validation, before and after.**
1. `observe plan --custom` dry run: review the planned targets.
2. After the first slot, run `sports_evidence report --summary` and check G1/G2 turn PARTIAL, the
   pair skew and the mapping (MAPPED, home_away MATCH).
3. Check the Freshness Fabric shows the observe schedule healthy.
4. Check the backup size.

**Rollback.** Stop planning custom targets. Planned ones expire as MISSED with their reason, and nothing
is fetched late. No schema change; the evidence already stored is kept.

**Authority: NOT covered today.**
- `edgelab-observe.timer` is authorized for ADR 0030 Option A (later and closing prices of recorded
  decisions). Adding NFL targets re-scopes an unattended timer's collection, and the strategy's sentinel
  rule makes a new collection an explicit decision.
- **An owner approval recorded in `docs/EXECUTION_PLAN.md`** is required, with a review date (suggested
  2026-10-22), and HANDOFF's W0 prerequisite (backup retention) is open.
- No new timer is proposed.
- The NFL season is finite: about 15 regular-season weeks remain, and each week not captured is a
  permanent loss of paired observations.

## 7. Shared-contract requests (for the coordinator; Writer 1's files)

1. **EXP-002 protocol.** Decide the tie / not-played treatment (G5, G8): accept the conditional mapping
   with declared bounds, or exclude. Freeze a maximum pair skew compatible with the capture schedule
   (section 6). Freeze the size ladder and the episode definition before any outcome is viewed.
2. **`fee_schedules`.** Re-verify KXNFLGAME (the series metadata and the non-standard PDF list
   disagree).
3. **`storage`.** A public metadata-only snapshot read (id, kind, entity, receipt, url, hash) would
   replace the private-connection reads that `sports_evidence` (like `odds_consensus`) uses today.
4. **Shared semantic contract (PR B).** Map `CONDITIONAL_MAPPING` / `RELATED_NOT_EQUIVALENT` and the
   probability meanings used here onto PR B's relation-tier and probability-meaning enums once they
   exist.
5. **CLI.** Wire `edge-lab research sports-evidence` to `sports_evidence.main` (`cli.py`, Writer 1)
   if a canonical entry point is wanted. `python -m edge_lab.sports_evidence report` works today.
