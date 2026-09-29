# NHL prospective evidence: owner decision packet (2026-09-29)

Prepared by the laptop coordinator after NHL-A (#137) and NHL-B (#136) were merged, deployed and activated under
the 2026-09-29 directive (`docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`, issue #134). This packet
asks for decisions; it grants nothing. No option below is chosen by an agent.

## What is running now (no decision needed)

- **Odds API NHL:** `icehockey_nhl` h2h, T-60m only, 1 credit per call. It is admitted only from the credits left
  after NFL's full monthly worst case, in one joint proof over the one shared ledger (450 ceiling).
- **Kalshi NHL:** `KXNHLGAME` only, T-6h and T-60m per game, both team markets. This is public data with no
  key. It runs under its own bound: 727 GETs/week at worst, about 295/week expected. It is lower in priority than
  EXP-001 and NFL.
- **Classification:** NHL is DATA_COLLECTION / DEVELOPMENT_ONLY and is not part of EXP-002.

## Decision 1: October NHL sportsbook coverage (the Odds budget)

**Fact (ADR 0039; `docs/research/NHL_ODDS_BUDGET_2026-10.md`):** for October, NFL's own worst case fills the
whole 450-credit ceiling at month start (expected NFL use 270). The cause is the conservative reservation for NFL
weeks the provider has not listed yet (`NFL_WORST_CASE`, 11 kickoff groups a week). NHL therefore gets:
- nothing from Oct 1 to about Oct 4;
- then capacity grows as NFL's reservation is released week by week;
- about 103 of 118 October T-60m slots in total, on the planner's model;
- T-6h in the first half of October does not fit.

Kalshi NHL coverage is **not** affected: it uses no Odds credits.

Options (the owner picks one; the default, if no decision is made, is **(a)**):
- **(a) Accept back-loaded NHL sportsbook coverage.** No change. Early-October games have Kalshi evidence but no
  sportsbook line, recorded as SKIPPED_BUDGET.
- **(b) An evidence-backed seasonal NFL worst case for October.** If October has no NFL Saturday games (not yet verified), an illustrative
  bound of 7 groups a week would give NHL 118 of 118 (`NHL_ODDS_BUDGET_2026-10.md`; illustration only). This keeps NFL's guarantee **only if** the bound is proven from
  the published NFL schedule. It needs a reviewed PR and must stay a true upper bound. This is technical work, but
  it changes an NFL guarantee assumption, so the owner should agree to it.
- **(c) Reduce NFL's lowest-priority class (T-24h)** to free credits. This trades NFL evidence for NHL evidence.
  Owner decision.
- **(d) A paid Odds tier.** Never automatic; owner decision, including cost.

## Decision 2: aligning NHL sportsbook and Kalshi read times around the 17:40-18:50 ET window

**Fact:**
- The Odds quiet window (17:40-18:35 ET) moves the T-60m sportsbook read for a 19:00 ET game to **18:35 ET
  (T-25m)**.
- The Kalshi observe protected window (17:40-18:50 ET) moves the Kalshi T-60m read for the same game to
  **17:35 ET (T-85m)**.
- So for about 36% of NHL games (the 19:00 ET starts) the two sources' "T-60m" reads are about 60 minutes apart.

Both reads are recorded honestly: nominal horizon, effective time and actual lead. This matters only for a future
hockey experiment that compares the two sources at the same instant.

Options:
- **(a) Leave as is** and record the gap. This is the default.
- **(b) One shared protected-window contract** for both collectors. For example, both read 19:00 games at
  17:35 ET, which is T-85m. This is a technical change needing a reviewed PR. The directive already asks for
  one shared operational contract for protected windows, so this is recommended as the next technical follow-up.
  It changes no NFL behaviour unless NFL is included explicitly.

## Decision 3 (optional): a hockey experiment

No hockey research slot exists. A future experiment needs its own #96 slot, mechanism, protocol and
preregistration. The candidate questions are recorded in #134 (consensus vs Kalshi, line movement,
goalie-confirmation effects, in-play via #122). **No decision is needed now.**

## Unresolved facts (not decisions)

- **Kalshi KXNHLGAME:** whether a shootout win resolves Yes, and how a tie pays out, are not stated anywhere.
  They are recorded RULES_UNRESOLVED.
- **Fees:** FEE_UNSUPPORTED, and never set to 0. `fee_schedules` routes KXNHLGAME to the general quadratic schedule
  (UNVERIFIED); this is left for the fee owner to review.
- **Opening night, 2026-09-29:**
  - 20 manual Kalshi observations (phase `custom`, origin `manual`);
  - scheduled Odds and Kalshi captures only for horizons still in the future at activation;
  - earlier horizons recorded as NOT_COLLECTED_BEFORE_ACTIVATION.
