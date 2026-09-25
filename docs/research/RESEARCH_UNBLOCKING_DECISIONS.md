# Research unblocking decisions: EXP-002 protocol, EXP-003 proof obligations, economics

Owner directive "RESEARCH UNBLOCKING" of 2026-09-25 (`docs/owner/2026-09-25-research-unblocking-directive.md`),
sections 6, 7, 9 and 10 and the matching parts of 14 and 15. Written by RU Writer R (research,
protocol and contract evidence) on 2026-09-25 from `main` at `706a340`.

**This document authorizes nothing.** It is a set of recommendations with evidence. It does not
approve any of these:
- Kalshi NFL collection;
- Odds API spending;
- contacting Kalshi;
- a capital amount;
- a gate advance;
- any change to EXP-001.

EXP-002 and EXP-003 stay **DRAFT**. Their protocols are not frozen by this document, and the
numbers proposed here are not written into their decision fields.

**Status words** (directive §15). Every recommendation carries one:

| Status | Meaning here |
|---|---|
| CURRENT | What the repository does or states today. |
| PROPOSED | A recommendation from this document. Not settled, not approved. |
| APPROVED | Only with a cited, recorded owner decision. **No item in this document is APPROVED.** |
| BLOCKED | Cannot proceed until the named blocker is removed. |
| VERIFIED | Checked against primary evidence cited here (a document, a fixture or a test run). |

## Summary

| # | Topic | Recommendation | Status | Needs |
|---|---|---|---|---|
| A.A | EXP-002 primary endpoint | **Predictive markout**: the gap between the sportsbook consensus and the Kalshi mid at T-6h, tested against the Kalshi mid change to the T-60m capture. Calibration and hold-to-settlement economics are secondary and descriptive only. | PROPOSED | technical review; freeze before preregistration |
| A.B | Horizon and cutoff | Decision horizon T-6h; markout target T-60m. Decision time = the later of the two receipts, at or before the capture deadline. A later observation is never moved back. | PROPOSED | technical review |
| A.C | Input age and pair skew | Keep the CURRENT source limits (odds 10 min, Kalshi book 5 min). Provisional pair window: the book from 5 min before to 10 min after the odds receipt. Calibrate on the development pilot's timing data only. | PROPOSED | technical review; a join variant |
| A.D | Ties, cancellations, not-played | Explicit payoff modelling with ex-ante bounds; every state kept in the sample. Cite the verified contract terms. | PROPOSED; rules VERIFIED | owner input on the bounds is not needed; technical review |
| A.E | Size ladder and capital | Research rungs of 1, 10, 50, 100 and 250 contracts, with the minimum episode size at 10. Illustrative capital of $250, $1,000 and $5,000, each labelled ILLUSTRATIVE. No approved capital exists. | PROPOSED | owner choice only for any real amount |
| A.F | Episode | One pool per game. Start at 2 cents per contract after fees at 10 contracts. An episode spans the capture horizons of one game and one direction and never infers persistence between captures. | PROPOSED | technical review; freeze before any label |
| A.G | Sample size, clusters, power | Game unit, NFL-week clusters. `scripts/research_power_sensitivity.py` gives ranges. The frozen n comes from a logged 3-week development pilot, not from this document. | PROPOSED (script VERIFIED by tests) | technical review |
| A.H | Windows and stopping | Pilot in NFL weeks 4–6; freeze by 2026-10-21; untouched evaluation in weeks 7–18; review 2026-10-22; one interim futility look; a variant budget of V0 plus at most 2. | PROPOSED | owner approval of collection is the gate (BLOCKED until then) |
| B | EXP-003 proof | The KXHIGHNY partition **cannot be proven** under current contractual text. The discretionary fair-price fallback makes its worst state pay 0, and an admissible full-refund cancellation caps the worst state at 0. The single-market YES+NO complement survives fallback, but it cannot show a surplus from one consistent book. **Pause the scope.** Keep one bounded fact-verification task (8 drafted Kalshi questions, not sent). Reject the scope if it is unresolved by 2026-11-15. | PROPOSED | owner approval to contact Kalshi |
| C | Economics and effort | Scenario tables per family. Bootstrap threshold PROPOSED at $1,000 per year (conservative lower band, illustrative capital of $2,500 or less), with $250 and $5,000 as alternatives. Owner-hour allowances: Family A 6 h to 2026-10-22, then +8 h if extended; Family B 2 h. | PROPOSED | owner decision (packet Decision 2) |
| D | Shadow-fill language | "Fill at first detection" relabelled FIRST_DETECTION_ZERO_LATENCY. "Best single observation" relabelled HINDSIGHT_UPPER_BOUND. Both are marked non-executable, versioned as `research-economics-v2` / `fill-mode-labels-v2` (ADR 0037). | IMPLEMENTED, TESTED_LOCALLY | review |
| E | Stale EXP-003 readiness | The protocol's "evaluator is PR B / not built" wording is replaced with the real blockers. The proof requirements are unchanged. | IMPLEMENTED | review |

## 0. Evidence consulted

| Evidence | Where | Version, date or hash | Strength |
|---|---|---|---|
| Kalshi FOOTBALLGAMEWIN contract terms (KXNFLGAME) | `https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf`, read 2026-09-25, bytes in `experiments/EXP-002-nfl-consensus-vs-event-market/rules_evidence/` | no printed version; PDF created 2026-09-11; sha256 `19578b71…fca4b` | explicit contractual text |
| FOOTBALLGAMEWIN CFTC self-certification | `https://assets.kalshi.com/regulatory/product-certifications/FOOTBALLGAMEWIN.pdf`, read 2026-09-25, same folder | letter dated 2026-02-18; sha256 `d89ea1b1…fc2cc` | explicit (older text) |
| KalshiEX Rulebook | S3 public docs URL in the manifest above, read 2026-09-25 (not committed) | v1.29, PDF created 2026-08-11; sha256 `3b6d4ffd…5240b`; being current is UNVERIFIED | explicit rules |
| KXNFLGAME market rules and series record | `tests/fixtures/sports_evidence/` (2 public GETs on 2026-09-25 02:24Z, PR C) | rules text on all 64 markets; series `fee_type` `quadratic_with_maker_fees`, multiplier 1 | explicit (market level) |
| Kalshi fee schedule PDF | `experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/` | effective 2026-07-07; sha256 `c326a69f…`; received 2026-09-23. A 2026-09-25 re-read of `kalshi.com/docs/kalshi-fee-schedule.pdf` got HTTP 429 and was not retried | explicit |
| Kalshi docs: Fee Rounding, Fixed-Point | same folder (captured 2026-09-23) | Fixed-Point "Last Updated: August 20, 2026" | documented API behaviour |
| Kalshi docs read 2026-09-25 (processed text; no bytes kept): `getting_started/market_settlement`, `fix/market-settlement`, `getting_started/orderbook_responses`, `api-reference/events/get-event-fee-changes`, `api-reference/portfolio/get-subaccount-netting` | docs.kalshi.com | no "Last Updated" shown on any of them | documented API behaviour |
| KXHIGHNY settlement semantics | `docs/SETTLEMENT.md`, gate2 evidence | 739/739 audited, 39 in the TWC era | explicit and observed |
| The implementation | `odds_consensus.py`, `sports_evidence.py`, `research_economics.py`, `research_evidence.py`, `payoff_constraints.py`, `odds_schedule.py`, `sources.py` at `706a340` | read, not run against data | CURRENT |
| Measured odds / book timing | laptop store `data/edge_lab.sqlite3`, opened read-only | **no Odds API or KXNFLGAME rows exist in it** (inventory only; the look is logged in EXP-003's log, §F). The production store was not read. | none available |

**No measured pairing timing exists to this session.** The production store holds the Odds side
only; HANDOFF reports 2 captured NFL targets. No KXNFLGAME book has ever been stored. Every timing
limit below is therefore provisional, with a calibration procedure. None is empirically proven.

---

## A. EXP-002 protocol recommendation

**Scope (CURRENT, unchanged).** NFL pregame moneyline, odds-consensus-v1 exactly as implemented,
and Kalshi KXNFLGAME as the first executable-price route. No fitted winner model. No other sport,
market type or venue is added to inflate the sample.

### A.A Primary endpoint

| | |
|---|---|
| **Recommended** | **Predictive markout.** For each game: the gap `g = c − k₆`, where `c` is the consensus value of the home team's KXNFLGAME YES contract (A.D) at the T-6h decision time and `k₆` is the Kalshi YES mid in the paired book. The outcome is `y = sign(g) · (k₁ − k₆)`, where `k₁` is the Kalshi YES mid in the first book received for the T-60m horizon. Test H₀: E[y] ≤ 0, one-sided, on game units with NFL-week clusters. `|g|` enters only as a pre-registered filter (for example `|g|` ≥ 2 cents) or not at all; it is never tuned. |
| **Probability benchmark vs execution price** | Kept separate. The markout uses the **mid** (a probability benchmark, and only when the spread is at most a frozen width). All economics use the **executable all-in ask** at size (A.E, §C). An ask includes spread and fees, so it is a price to pay, not an unbiased estimate of probability. A YES ask on Kalshi is `1 − best NO bid` (documented orderbook behaviour, `kalshi_quotes`), so the mid is `(yes_bid + 1 − no_bid)/2`. |
| **Reason** | (1) The capture design (T-24h / T-6h / T-60m, PR C) gives a later Kalshi price for every paired game, so a markout exists per game. An economics endpoint exists only per rare episode. (2) Power: the per-game hold-to-settlement P&L has SD ≈ 0.5 per contract (a mathematical bound for a binary payoff). Under every assumption in the grid it needs more than 120 weeks (about 7 seasons; §A.G). A markout SD of 1–4 cents fits one season under some assumptions. (3) Ties and fair prices move `k₆` and `k₁` alike, so the markout does not depend on the tie treatment in the way a level comparison does (A.D). (4) It tests the stated mechanism: "event-market books lag the consensus". |
| **Evidence** | `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §2 item 7 (horizon resolution only); `scripts/research_power_sensitivity.py` output (§A.G); contract terms (A.D). **No result of any kind exists**, so the choice cannot have been made by looking at which result is better. No outcome, label or markout has been viewed. |
| **Tradeoff** | A markout is forecast quality about a *later price*, not money. A positive markout proves information transfer, not an exploitable edge. Exploiting it means buying at T-6h and either holding to settlement (high variance) or exiting at T-60m (a second spread and fee). The T-60m mid is itself a benchmark, not truth. |
| **Uncertain** | The markout SD (a pilot estimate), the spread width at which a mid is meaningful, the stability of the lag, and whether Kalshi pregame books update between captures at all. |
| **Needs** | Technical review (statistics). Freeze in `[endpoints] primary` before preregistration. |
| **Status** | PROPOSED |

**Secondary endpoints (PROPOSED, descriptive only this season).**
1. Outcome calibration at T-60m: log loss and Brier score of `c` (tie-adjusted interval midpoint)
   against the Kalshi mid, per game. It is reported with its interval and never tested for
   significance this season.
2. Hold-to-settlement after-cost contribution per contract at each rung, conservative and
   hindsight bounds (§D). Descriptive and capacity evidence only. §A.G shows it cannot be
   inferential in one season.
3. The attrition waterfall with separate denominators (CURRENT, `research_evidence`).

**Alternative 1: outcome calibration as the primary endpoint** (for example a log-loss difference
at T-60m). It is closer to settlement economics. It needs the tie and fallback bounds (A.D) in the
level comparison, and it is badly under-powered in one season. It fits a multi-season plan only.

**Alternative 2: a markout to a later "closing" book** (for example T-10m). It captures more of
the pregame repricing. It needs a new capture horizon, which is not in the current design, so it
would need a capture change and new approval.

### A.B Horizon and information cutoff

| | |
|---|---|
| **Recommended** | Decision horizon **T-6h**, markout target **T-60m**; T-24h → T-6h is a registered challenger (it counts against the variant budget, A.H). Record per pair: the intended target time (`target_utc`), the effective due time (`odds_schedule.effective_due`), the cutoff `C` (`odds_schedule.deadline`: effective due + 30 min, never later than kickoff − 5 min; CURRENT), the odds receipt `R_o`, the book receipt `R_k`, per-book market `last_update`, and the decision time **`D = max(R_o, R_k)`** with `R_o, R_k ≤ C` (CURRENT in `sports_evidence.kalshi_side`). The markout target book is the first book received at or after the T-60m effective due time and at or before its cutoff. The actual elapsed time `R_k(T-60m) − D` is recorded; the nominal "5 hours" is a label, not a measurement. |
| **Information rule** | A feature at `D` uses only records received at or before `D`. The nominal horizon never stands for `D`: a pair whose book arrived 8 minutes after the target is a decision at `D`, not at the target time. A book received after `C` is never used for that horizon (CURRENT: `pick_book` counts it as `later_books_not_used`). Listings and rules are read as of `D` (CURRENT). A later capture is a label (the markout), never a feature. |
| **Reason** | T-6h is the only decision horizon with a later captured horizon still pregame and at least 4.5 h away. T-60m as a decision horizon has no later pregame capture. T-24h is far from the close, and its Sunday late-game pairs are the worst for skew (PR C §6). |
| **What each horizon can support** | T-24h: early information; lags of hours only. T-6h: the primary decision with markout to T-60m. T-60m: calibration against outcome (secondary) and a "near close" level. None supports seconds- or minutes-level lag claims, because the capture schedule resolution bounds every timing claim (CURRENT limitation). |
| **Evidence** | `odds_schedule.py` (`early_tolerance` 7 min, `late_tolerance` 30 min, `min_lead` 5 min); `sports_evidence.pick_book` / `kalshi_side`; PR C §6 schedule analysis. |
| **Tradeoff** | One decision horizon halves the data compared with using all three, but avoids counting the same game three times as if it were independent. |
| **Uncertain** | Whether the T-60m book lands before kickoff − 5 min in crowded slots (PR C: more than 12 games in a slot defers a tick). |
| **Needs** | Technical review. |
| **Status** | PROPOSED (the cutoff mechanics are CURRENT) |

### A.C Input age and pair skew (provisional)

These limits define **comparability**. They are not evidence that a price of a given age was
executable. A book is an executable-price candidate only at its own receipt time.

| Limit | Recommended (provisional) | Status | Reason |
|---|---|---|---|
| Sportsbook source-update age (receipt − per-book market `last_update`) | ≤ 10 min; a stale or undated book makes the proposition not fresh (fail closed) | CURRENT (`sources.py` odds max age 10 min; `odds_consensus`) | The Odds API documents market `last_update` as the last time odds were seen, and removes suspended markets after about 15 min (`experiments/multi_venue/odds_api_docs_2026-09-23.md`). Changing it is a variant of odds-consensus-v1. |
| Local observation age of the odds at `D` (`D − R_o`) | ≤ 10 min | CURRENT (judged at `D` by `sports_evidence`) | the same registry limit |
| Event-market book age at `D` (`D − R_k`) | ≤ 5 min | CURRENT (`kalshi_public` orderbook max age 5 min) | Kalshi books have no per-level source time, so receipt is the only clock. |
| Odds/book receipt skew (`R_k − R_o`) | **from −5 min to +10 min**: a book up to 5 min before the odds, or up to 10 min after | PROPOSED (CURRENT is a symmetric 5 min, `JoinPolicy.max_pair_skew`) | The asymmetry follows from the two age limits. A book *before* the odds becomes the stale input at `D`, so it must be within the book limit (5 min). A book *after* the odds is fresh at `D` and makes the odds the older input, bounded by the odds limit (10 min). The planned observe tick lands about +5 min after the odds tick (PR C §6), exactly at today's symmetric limit, so ordinary jitter would fail pairs. PR C's symmetric 10-min candidate would admit a 10-min-old book as the executable side, which is not supported. |

**Calibration procedure (PROPOSED; bounded; before any label is viewed).**
1. Use only the development pilot weeks (A.H) and only **timing and feature-side fields**:
   `R_o`, `R_k`, `last_update`, spreads and depth. No outcome and no markout (`k₁`) is read.
   Record the look in EXP-002's evidence-use log as FEATURE_INSPECTION, DEVELOPMENT role.
2. Report the distributions of: skew; book age at `D`; per-book `last_update` age; the fraction of
   due T-6h pairs kept at windows of [−5, +5], [−5, +10] and [−10, +15] minutes; and, where two
   Kalshi books of one horizon exist within 15 min, the mid change between them (short-interval
   drift, a feature-side measure of how much prices move inside the window).
3. Freeze the narrowest window that keeps at least 70% of due T-6h pairs and whose median
   absolute short-interval drift is at most one third of the pre-registered minimum markout
   effect. If none qualifies, freeze [−5, +10] and record the attrition, or pursue PR C option (b):
   capture the book in the same run as the odds. That runner change needs review.
4. Every limit tried is counted in the variant budget. Pairs lost to skew stay in the denominators
   (CURRENT attrition).

**Needs:** technical review. The asymmetric window is a `JoinPolicy` change and therefore a
registered join variant. It is not implemented here.

### A.D Ties, overtime, cancellations and not-played states

**Verified contract states (VERIFIED against the 2026-09-11 terms and the 2026-09-25 market
rules; rules_evidence/MANIFEST.md).**

| State | KXNFLGAME YES (team) pays | Source |
|---|---|---|
| Team wins (overtime included) | $1 | terms: Payout Criterion, overtime clause |
| Team loses | $0 | terms |
| Tie after overtime | $1/(tied teams), rounded down = **$0.50** | terms; market rules_secondary |
| Postponed, started within 48 h | normal result | terms; market rules |
| Not started within 48 h | "last fair market price as determined by Kalshi", a discretionary F in [0, 1] | terms; market rules |
| Suspended before 55 min of play and not resumed within 48 h | last fair price (discretionary) | terms |
| Suspended after 55 min, or declared final by the league | the result as it stands (Sept terms) or a fair price (Feb certification): conflicting texts, UNVERIFIED which governs | terms vs certification |
| Forfeit before kickoff / after kickoff | fair price / the league's determination | terms |
| Venue moved outside the week, or home/away reversed | fair price | terms |
| Disqualified before the game / after it starts | fair price / "No" for that team, "Yes" for the opponent only if declared the winner | terms |
| No determinable value; emergency | Rule 6.3(c): last traded price or the Outcome Review Committee's "fair allocation"; Rule 2.8: cancellation with funds returned | rulebook v1.29 |

**Sportsbook side (UNVERIFIED).** A two-way h2h de-vig from The Odds API carries no house rules.
US books commonly treat an NFL moneyline tie as a push. The consensus is therefore read as
P(team wins | game decided within the book's rules) (CURRENT reading, `sports_evidence.relation_for`).

| | |
|---|---|
| **Recommended** | **Supported explicit payoff modelling with declared ex-ante bounds.** Value the contract as `V = (1 − t − u)·p + 0.50·t + u·F`, where `F ∈ [0, 1]` and `t ≤ t_max`, `u ≤ u_max`. This is CURRENT code (`sports_evidence.tie_adjusted_interval`); only the bounds are missing. `u` covers every non-standard resolution in the table: fair price, discretionary allocation, post-start disqualification and cancellation. Proposed bounds: **`t_max = 0.01`, `u_max = 0.005`**. These are deliberately loose. NFL ties and unplayed games are rare, but no count is cited here, so confirm from the league's official records before freezing. The bounds are frozen with the protocol, before any outcome is viewed, and are never fitted. Consequences: (1) the level comparison uses the interval, so the edge must clear its lower end; (2) the markout endpoint (A.A) uses the interval midpoint only to sign the gap; (3) **every state stays in the sample.** A tie is scored with its $0.50 payoff. A fair-price resolution is scored with its actual value. A rescheduled game stays with the exposure fixed at `D`. Nothing is dropped after the result is known. |
| **Reason** | The rules are explicit, the valuation is linear and already implemented, and the bounds make the conditional-versus-unconditional gap a stated number (at most about 0.5·0.01 + 0.005 = 1 cent here) instead of an unstated assumption. |
| **Evidence** | Contract terms and market rules above; `sports_evidence.tie_adjusted_interval` (tested in `tests/test_sports_evidence.py`). |
| **Tradeoff** | Loose bounds widen the interval, so a 1-cent effect cannot be claimed on the level comparison. Tight bounds need a sourced tie frequency. |
| **Uncertain** | The books' tie and postponement rules; the size of F in a real fallback; which document governs the after-55-minutes case. |
| **Needs** | Technical review. A sourced historical count before freezing `t_max`. No owner preference is needed. |
| **Status** | PROPOSED (the rules are VERIFIED; the code is CURRENT) |

**Alternatives.** (a) *Clearly limited conditional research*: analyse P(win | decided game) only,
with ties and fair prices reported but excluded. It makes no unconditional or trading claim, and
the report must show the real exposure at entry, including the tie and fallback states. (b) *An
ex-ante restriction*: not available. No KXNFLGAME contract excludes ties or fallbacks, and "Tie"
strikes exist only for period markets. (c) *Blocked*: only if the bounds cannot be sourced.

**Collecting is not proving.** Capturing Polymarket or other related NFL markets beside Kalshi adds
observations of related prices. It does not establish economic equivalence. Equivalence needs the
state-by-state payoff mapping above, and every Polymarket US market stays RELATED_NOT_EQUIVALENT
(ADR 0032).

### A.E Size ladder and capital scenarios

Illustrative cash cost per rung, from the general Kalshi taker formula `ceil(0.07·C·P·(1−P))` rounded
up to a centicent for a direct member. **The KXNFLGAME fee is FEE_UNSUPPORTED in the registry**
(`fee_schedules`). The fee PDF lists the series among "Non-Standard Fees" with maker 1 and taker 1.
The API reports `quadratic_with_maker_fees`, multiplier 1. Event-level fee overrides also exist
(`get-event-fee-changes`). These figures are therefore ILLUSTRATIVE, not claimable.

| Contracts (research quantity) | Cash at P = 0.20 | P = 0.50 | P = 0.80 |
|---|---|---|---|
| 1 | $0.2112 | $0.5175 | $0.8112 |
| 10 (**PROPOSED minimum episode size**) | $2.112 | $5.175 | $8.112 |
| 50 | $10.56 | $25.875 | $40.56 |
| 100 | $21.12 | $51.75 | $81.12 |
| 250 | $52.80 | $129.375 | $202.80 |

| | |
|---|---|
| **Recommended** | Rungs of **1, 10, 50, 100 and 250 contracts** (CURRENT code default: 1, 10, 25, 100, 250; the change swaps 25 for 50 so each rung is 2–5 times the last). The minimum episode size is 10. Keep four separate quantities: **research quantity** (the rungs); **illustrative capital** ($250, $1,000 and $5,000, each `ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL`); a **reserve scenario** (20% of illustrative capital held back, an assumption); **approved live capital** (none exists, and nothing here sets it). The old simulated $1,000 account is not the owner's bankroll. |
| **Fractional fills** | Kalshi fills are in 0.01-contract steps, and "fills can be fractional even when the order is for whole contracts" (Fixed-Point docs; `fee_verification/VERIFICATION.md`). A whole-number rung therefore does not remove fractional-fill fee questions. A walk that crosses a fractional level stays NOT_EVALUATED (CURRENT, ADR 0036) until a fractional-fill fee rule is modelled from the documented fee accumulator. |
| **Reason** | 10 contracts cost $2–8, which is meaningful above a one-lot while small enough that depth is unlikely to bind. 250 probes capacity. Visible depth stays a ceiling (CURRENT). |
| **Evidence** | Fee PDF p.2 formula; the fixture series record; Fixed-Point docs. The 450k-contract top-of-book size in the 2026-09-25 listing fixture was **in-game** (ATL@GB was live), so it is not pregame depth evidence. |
| **Tradeoff** | More rungs mean more capacity rows but no extra inferential tests: rungs are descriptive. |
| **Uncertain** | Pregame depth; the KXNFLGAME fee claim basis. |
| **Needs** | Technical review of the rungs. The owner decides any real capital separately (packet Decision 2). A fee-verification record belongs to the `fee_schedules` owner. |
| **Status** | PROPOSED |

### A.F Episode definition

| Field | Recommended | Status |
|---|---|---|
| Liquidity / pool key | **the game** (Kalshi event ticker). Buying YES on one team and NO on the other are the same exposure on two books, so every market side of one game shares one pool (`research_economics.build_episodes` joins pools by shared keys: give each observation the key `event_ticker`). | PROPOSED |
| Start threshold | net edge ≥ **$0.02 per contract after fees**, at the minimum size, measured against the **lower** end of the A.D interval | PROPOSED |
| Minimum meaningful size | 10 contracts | PROPOSED |
| End condition | the first later capture horizon of the same game where the edge in the same direction is below the threshold, or kickoff | PROPOSED |
| Merge gap | the whole pregame window of one game (≥ 18 h 30 min, covering T-24h → T-6h and T-6h → T-60m plus the late tolerance). Qualifying horizons of one game and direction are one episode. | PROPOSED |
| Deduplication | repeated snapshots of one book (the same receipt or payload hash) count once; two directions in one game are two episodes only if they occur at different horizons, and they share the pool, so replay takes at most one at a time (CURRENT replay rule) | PROPOSED / CURRENT |
| Persistence | an episode lists the horizons at which it was **observed** ("seen at T-24h and T-6h"). It never claims it persisted between captures. Duration is reported only at horizon resolution. | PROPOSED (CURRENT rule in `RESEARCH_PRINCIPLES`) |

**Reason.** Two cents clears the 1-tick minimum, the fee claim allowance of 0.0101 per contract
(the KXHIGHNY precedent) and the A.D interval width of about 1 cent. **Alternatives:** 1 cent
(more episodes, dominated by tick noise and interval width) or 3 cents (cleaner, rarer).
**Needs:** technical review. Freeze before any outcome or markout is viewed.

### A.G Sample size, clusters and power

**Units and dependence (PROPOSED).**

| Source of dependence | Treatment |
|---|---|
| Several books on one game | The consensus is one number per game; books are never units. Source families are UNKNOWN (CURRENT `[knowledge]`). |
| Both sides of one game | Complements: one statistic per game (the home team's contract). |
| Several horizons | One primary horizon (T-6h); the others are secondary or challengers, never pooled as independent. |
| Week and slate | Games are clustered by NFL week (`sports_evidence.week_cluster`, CURRENT). Inference uses week-cluster bootstrap or cluster-robust errors. |
| Rare signals | The economics endpoint has about 1–3 episodes a week (see below), so it is descriptive. |
| Missing or unsupported events | Stay in the attrition denominators with raw reasons (CURRENT). A game missing because its book was thin is informative missingness, reported and not imputed. |

**Sensitivity (`python scripts/research_power_sensitivity.py`; `research-power-sensitivity-v1`;
one-sided α = 0.05, power 0.80; 15 games a week; planning horizon 14 weeks).** Every row is an
assumption.

| Endpoint | Scenarios that fit 14 weeks | Weeks needed across the grid |
|---|---|---|
| Markout (primary): SD 0.01–0.04, effect 0.25–1 cent, ICC 0–0.10, eligible 30–90% | 51 of 108 | 0.46 to 475 |
| Hold-to-settlement P&L per contract: SD 0.45–0.5, effect 1–5 cents, episode rate 10–30% | **0 of 144** | 124 to 34,000 |

Examples:
- Markout SD 0.02, effect 0.5 cent, ICC 0.05, 60% eligible (9 games a week): about 15.4 weeks, so
  it does not fit.
- The same with a 1-cent effect: about 3.9 weeks.
- The minimum detectable markout over a 12-week evaluation window at 9 games a week: 0.48–0.64
  cent at SD 0.02, and 0.96–1.28 cents at SD 0.04 (ICC 0–0.10).
- Hold-to-settlement over 12 weeks at 2.7 episodes a week: about 22 cents per contract. It is not
  a usable inferential endpoint.

The week-level dependence also sets a floor: however many games a week are analysed, weeks needed
is at least `n_eff × ICC`.

**Pilot-data requirement (PROPOSED), instead of a fabricated n.** Three NFL weeks of approved
paired capture (about 45 games; A.H), used as DEVELOPMENT data and logged. From feature-side and
timing data they must give:
1. the pairing yield of due T-6h and T-60m horizons;
2. the skew and age distributions (A.C);
3. spreads and pregame depth at the rungs;
4. the SD of the markout statistic, which **does** need `k₁`, a label. This step comes only after
   the A.C timing limits are frozen from timing data alone, so no timing limit is chosen with
   markouts in view. The pilot games' markouts are then viewed, logged as LABEL_RESULT_INSPECTION
   on DEVELOPMENT data, and those games are permanently excluded from the untouched window.

Three weeks cannot estimate the week ICC, so ICC stays a sensitivity range (0–0.10), and the
frozen n uses the pessimistic end (ICC 0.10) unless the evaluation window is long enough to
tolerate it. The frozen `min_independent_clusters` (weeks) is `ceil(weeks_required)` at the
pessimistic ICC, with a floor of 8 weeks so the cluster bootstrap is meaningful.

**Four kinds of evidence (PROPOSED), never mixed:**
1. **Descriptive feasibility** (pilot): counts, yield, timing, spreads and depth.
2. **Inferential** (the evaluation window): the markout test only.
3. **Annual capacity scenarios** (§C): labelled scenarios, produced only after `min_episodes_for_scenario` is met.
4. **Live readiness**: not in scope. It needs gates 8–9, orders and owner approval.

### A.H Evaluation windows and stopping

| Item | Recommended | Status |
|---|---|---|
| Development pilot | The first 3 complete NFL weeks after collection is approved. If approved before the week 4 T-24h targets (about 2026-09-30), that is weeks 4–6: kickoffs 2026-10-01 to 2026-10-19 ET. DEVELOPMENT role, every look logged. | PROPOSED; BLOCKED on the capture approval (packet Decision 1) |
| Validation approach | No parameter search. V0 only. The delayed-signal and placebo controls (CURRENT `[evaluation] controls`) run on pilot data. Timing limits are calibrated as in A.C. | PROPOSED |
| Freeze | Protocol frozen (PREREGISTERED) by 2026-10-21, before the first evaluation kickoff, with `holdout_windows` set | PROPOSED |
| Untouched future window | Kickoffs from 2026-10-22 (week 7 Thursday) through the end of the regular season (week 18, about 2027-01-10); scope `sports:nfl:moneyline`, identified by outcome window **and** dataset hash. Playoffs are a pre-registered optional extension. Pilot games are never relabelled as untouched. | PROPOSED |
| Review dates | 2026-10-22 (CURRENT `[budget] review_date`): feasibility and freeze review. 2026-11-30: interim (see futility). 2027-01-13: final. | PROPOSED |
| Futility | **Operational** (at 2026-10-22): pairing yield below 50% of due T-6h horizons after fixes, or a median pregame spread above 2 × the start threshold, gives OPERATIONALLY_UNUSABLE. **Statistical** (one interim at 2026-11-30, about half the planned weeks): stop if the one-sided 90% upper confidence bound of the mean signed markout is below the minimum markout effect. **Economic**: the hindsight upper bound (§D) of after-cost contribution cannot clear fixed cash costs, giving ECONOMICALLY_UNVIABLE. | PROPOSED |
| Continuation | Beyond 2027-01-13 only with a named missing observation (for example "playoffs" or "season 2027 weeks 1–6"), its marginal cash cost (0 today) and its owner hours, approved at the review. Never an open-ended extension. | PROPOSED |
| Variant budget | V0 plus at most 2 registered challengers (candidates: T-24h decision; the symmetric 5-min skew), with Holm correction across primary and challengers. Every tried timing limit, filter or horizon counts. | PROPOSED |

---

## B. EXP-003 proof obligations

The evaluator exists (`payoff_constraints.py`, ADR 0036, #102/#105) and is **not** rebuilt here.
The question is whether any allowlisted set can meet its proof requirements under the corrected
formula:

```
worst = min_s( Σ_i( q_i·payout_i(s) − settlement_cost_i(s) + refund_i(s) ) − basket_cost(s) ) − Σ_i acquisition_cost_i
```

**Evidence strength:**
- **E** = explicit contractual guarantee (contract terms or rulebook);
- **D** = documented API or docs behaviour;
- **O** = observed historical behaviour;
- **I** = inference;
- **U** = unknown.

A run of observed integer outcomes is O, never E.

| # | Relationship | Instrument scope | Required proposition | Current evidence | Strength | Missing fact | Consequence if unresolved | Best next action |
|---|---|---|---|---|---|---|---|---|
| 1 | Partition | KXHIGHNY, all 6 brackets of one event, YES | The NORMAL states are exhaustive: every possible settlement value lies in exactly one bracket | Brackets are integer-inclusive (`between` = ≥ low and ≤ high; SETTLEMENT §3); 739/739 audited values are whole degrees, 39 of them in the TWC era; the rules settle on "the full precision reported by the Source Agency" | E (inclusivity), O (integers), U (TWC precision) | Is a KXHIGHNY expiration value guaranteed to be a whole °F? | A value such as 81.5 lies in **no** bracket, so every leg pays 0: INCOMPLETE (CURRENT) | Q4 to Kalshi |
| 2 | Partition, nested threshold | KXHIGHNY, any cross-market set | The discretionary fallback preserves the relation: Σ v_i = 1 across the event | Rules: with missing data, all strikes resolve to "the last fair price" at the Exchange's sole discretion. Each strike gets its own value. No text constrains the sum | E (the state exists), U (sum constraint) | Are fallback prices across a mutually exclusive event constrained to sum to $1? | Worst state = every v_i = 0, so the basket pays 0 and **no positive surplus can ever be claimed** (VERIFIED: every evaluated production and laptop scan row had the fallback as its worst state, paying 0) | Q1 to Kalshi |
| 3 | Any set | Kalshi, any series | The VOID / REFUND / CANCELLATION cash flow is known | Rule 2.8(d): an emergency may cancel a contract and return the funds paid to enter trades; Rule 6.3(c): discretionary payouts | E (the state exists), U (whether fees are refunded) | Does a cancellation return trading fees and rounding fees as well as prices? | If fees are not returned, that state's surplus is −fees, so worst < 0. **If everything is returned, that state's surplus is exactly 0, so worst ≤ 0 anyway.** A strictly positive worst-state surplus is impossible while a full-refund state is admissible (see note B-1) | Q3 to Kalshi; technical review of note B-1 |
| 4 | Complement | One Kalshi market, YES + NO in equal quantity | NO pays 1 − v in every state, including fallback | Rule 6.3(c) example: last traded $0.10 → $0.10 long / $0.90 short; Rule 6.3(b): the settlement value is split between long and short; settlement docs: "Only net positions are settled (after netting)" | E for the last-traded method; I for the Outcome Review Committee's "fair allocation"; D (netting) | Is NO always paid $1 − v under a committee allocation? | The relation holds in structure under E and I. `payoff_constraints.fallback_cell` already records NO = 1 − v as an assumption (CURRENT) | Q2 to Kalshi |
| 5 | Complement (economics) | One Kalshi market | A YES + NO surplus can exist in a consistent book | The orderbook returns bids only; best YES ask = $1 − best NO bid, best NO ask = $1 − best YES bid (docs `orderbook_responses`; `kalshi_quotes`). So YES ask + NO ask = 2 − (yes bid + no bid) ≥ 1 unless the book is crossed, which is flagged as an anomaly | D, and I that the matching engine prevents a resting crossed book | none | **Pre-fee surplus ≤ 0 in any consistent snapshot, so the complement is provable-in-structure but economically empty.** A positive reading would be a data artefact (non-simultaneous levels) | VERIFIED no-surplus by construction; no further work |
| 6 | Tie state | KXHIGHNY | No TIE state | Integer settlement puts every value in one bracket (CURRENT proof, `KXHIGHNY_PROOF`) | depends on #1 | #1 | Stands or falls with #1 | — |
| 7 | Correction state | KXHIGHNY | Corrections only select among the NORMAL states | "Revisions after the Expiration Date are not included" (GLOBALTEMPERATURE; SETTLEMENT §4) | E | none | Excluded with evidence (CURRENT) | — |
| 8 | Fees on fractional fills | Kalshi taker fills | The all-in cost of a walk that crosses fractional levels is known | Fee Rounding docs: per-fill trade fee rounded up to $0.000001, balance alignment to $0.0001 (direct) or $0.01, and an order-level accumulator with a capped rebate; 0.01-contract granularity | D (mechanics), with the account type owner-attested | none for the mechanics; exact rebate order across split fills (Q5) | Those sizes are NOT_EVALUATED (CURRENT). Implementable from the docs, but not worth building while #2 and #3 block any claim | Defer. Q5 only if the scope reopens |
| 9 | Settlement costs | Kalshi binary settlement | settlement_cost_i(s) is known | Fee PDF p.3: "There is no settlement fee". Docs: settlement fees are zero for yes/no determinations but "may apply for sub-cent scalar settlement"; the payout is rounded to the balance precision (MiscFeeAmt) | E (no fee), D (rounding) | Is a fair-price settlement a "scalar" settlement subject to rounding? | Bounded: under $0.0001 per market settlement for a direct member, under $0.01 for non-direct. Small, and it can be carried as a bound | Q6; then record a bound |
| 10 | Transfer costs | Account funding | Basket economics include deposit and withdrawal costs | Fee PDF p.3: ACH free; debit card up to 2%; wire bank fees; crypto processor fees; alternate rails 0–2% | E | the owner's funding rail (not needed for research) | These are per-account fixed costs, outside the per-basket formula. They belong in §C fixed costs, not in `settlement_cost_i` | Note in §C |
| 11 | Partition | KXNFLGAME, the two team markets of one game, YES + YES | Exhaustive and exclusive, summing to $1 | Win/loss: 1 + 0; tie: 0.50 + 0.50 (E); fair price: v_A + v_B unconstrained (U); disqualification after the start: "No" for the disqualified team and "Yes" for the opponent only if declared winner, so 0 + 0 is possible (E). The event record says `mutually_exclusive: true`, `collateral_return_type: MECNET` (undocumented here) | E / U | Q1 for this series; Q8 (MECNET) | Not provable. It is also **outside EXP-003's allowlist and universe**: adding it would be a new series variant and need review | Do not add. Recorded only because Family A shares the series |

**Note B-1 (a finding for technical review; the formula is not changed).**
- H-B1 asks for a *positive* worst-state full-fill surplus.
- Whenever a cancellation state that refunds all funds is admissible, the basket's surplus in
  that state is exactly 0. The minimum over states is then at most 0, whatever the prices.
- Rule 2.8 makes that state admissible for every Kalshi contract. So H-B1 as worded is
  unattainable on Kalshi even with perfect prices.
- A meaningful criterion would be "non-negative in every admissible state, and positive in every
  NORMAL state" (a weak arbitrage). It needs fees to be refunded on cancellation (Q3).
- That is a change to the hypothesis. It must be a logged, reviewed protocol amendment before any
  further scan. Nothing is changed here.

**Verdict (PROPOSED).**
1. **The full KXHIGHNY bracket partition cannot be proven today.** Its worst admissible state (the
   fallback) pays 0 under the contractual text (#2). Integer settlement is only observed (#1). No
   positive surplus can be claimed, and every stored scan agrees (no surplus even before fees:
   1.06–1.09 per $1 basket).
2. **The simpler allowlisted relationship, the single-market complement, is the only one that
   survives fallback** (#4: E and I). It cannot produce a surplus from one consistent book (#5).
   It is provable-in-structure but economically empty.
3. **Recommendation: pause the current EXP-003 scope, and keep one bounded fact-verification
   task.**
   - No new solver, scan or fractional-fee feature is built while #2 and #3 are open.
   - If the owner approves, send Q1–Q4 (and Q5–Q8 for completeness) to Kalshi.
   - Reopen only on a written, official answer that fallback prices of a mutually exclusive event
     sum to $1 **and** that cancellation refunds fees. The note B-1 amendment is also needed.
   - **Reject** the KXHIGHNY partition scope, recorded with its reasons and never deleted, if there
     is no answer by **2026-11-15**, or the answer is negative.
   - Status: PROPOSED. It needs owner approval to contact Kalshi (sending a message on the owner's
     behalf).
4. **Separation kept.** Operational settlement audits of KXHIGHNY (EXP-001, `settlement audit`) are
   not strategy development. Family B never uses EXP-001 forecasts, outcomes or the ledger. Its
   `prohibited_inputs`, `prohibited_label_scopes` and `prohibited_fields` are unchanged.

### Draft questions for Kalshi (DRAFT; NOT SENT; the owner decides whether and how to send)

> **Q1 (fallback consistency).** For a series whose event markets are mutually exclusive (for
> example KXHIGHNY-26SEP25, whose brackets have `mutually_exclusive: true`), the rules say that
> with missing data all strikes resolve to "the last fair price" determined at the Exchange's sole
> discretion. Are the fair prices assigned across all markets of one such event
> constrained to sum to $1.00? If not, what constraint, if any, applies?
>
> **Q2 (NO-side payout).** When a binary market resolves to a value v other than $0 or $1 (a fair
> price, a last traded price or an Outcome Review Committee allocation), is a NO (short) position
> always paid $1.00 − v per contract? Is v restricted to the market's price grid, or can it be
> sub-cent?
>
> **Q3 (cancellation refunds).** Rulebook v1.29 Rule 2.8 lets an emergency action cancel a contract
> and return the funds paid to enter trades. In that case, are trading fees and rounding fees returned together
> with contract prices? Are there other paths (Rule 6.3(c), Rule 7.1) by which a contract is voided
> with funds returned rather than settled at a value?
>
> **Q4 (settlement precision).** For KXHIGHNY under The Weather Company source, is the expiration
> value guaranteed to be a whole degree Fahrenheit? If a fractional value is reported (for example
> 81.5), how do the inclusive "between" brackets (for example 80–81 and 82–83) resolve?
>
> **Q5 (fractional fills).** For a taker order that fills fractional quantities (0.01 contracts)
> against several resting orders, is each fill's fee exactly the Fee Rounding documentation's
> per-fill trade fee plus rounding fee minus accumulator rebate? Is there any per-fill minimum?
>
> **Q6 (settlement cost).** Is any settlement fee charged beyond balance-precision rounding
> (MiscFeeAmt) when a binary market settles at $0/$1, at $0.50 (a two-team tie) or at a fair price?
>
> **Q7 (KXNFLGAME fees).** The fee schedule of July 7, 2026 lists KXNFLGAME under "Non-Standard
> Fees" with maker multiplier 1 and taker multiplier 1, and the API reports `fee_type`
> `quadratic_with_maker_fees`. Is the taker fee exactly `round up(0.07 × C × P × (1 − P))` and the
> maker fee `round up(0.0175 × C × P × (1 − P))` for this series, subject only to event-level
> overrides returned by the event fee-changes endpoint?
>
> **Q8 (MECNET).** What does `collateral_return_type: MECNET` on a mutually exclusive event mean for
> a member holding YES positions in several of its markets?

---

## C. Economics and effort scenarios (all PROPOSED; no real bankroll)

Every number is a **labelled scenario**, not a forecast. No family has an observed episode, so
nothing is annualized from data. The $50k–$100k aspiration is not a per-family minimum.

**Contribution formula (CURRENT, `research_economics`):**
`contribution = Σ episodes (filled contracts × net edge per contract after fees)`.
Fees enter once. There is no bankroll × size × turnover product.

### C.1 Family A (EXP-002, NFL; `ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL`)

Assumptions:
- about 285 games per season, including playoffs;
- 60% eligible;
- an episode rate of 10%, 20% or 30% of eligible games;
- a net edge of 1, 2 or 3 cents per contract;
- capital locked from T-6h to settlement, at most about 12 h. In the fixture,
  `expected_expiration_time` is 6 h after kickoff and `settlement_timer_seconds` is 60, and the
  market closes early once a winner is declared, so the lock is usually shorter.

| Scenario | Episodes / season | Contracts / episode | Net edge | Variable contribution / season | Peak deployed capital (one Sunday slate, P ≈ 0.5) |
|---|---|---|---|---|---|
| Low | 17 | 10 | $0.01 | **$1.70** | ~$5 (1 concurrent × $5.175) |
| Mid | 34 | 100 | $0.02 | **$68** | ~$104 (2 concurrent × $51.75) |
| High (capacity UNVERIFIED) | 51 | 1,000 | $0.03 | **$1,530** | ~$1,553 (3 concurrent × $517.50) |

Other quantities:
- **Fixed incremental cash costs:** $0. The Odds API free tier stays inside its 450-credit cap,
  and Kalshi public data is free. Paid data is not authorized.
- **Shared infrastructure:** the existing VPS. Its allocation is UNKNOWN / OWNER_INPUT and it is not
  incremental.
- **Transfer costs:** $0 by ACH; up to 2% by card (fee PDF p.3). This is per-deposit and outside
  the per-contract formula.
- **Concurrency** (an assumption): about 20 weeks a season, playoffs included, give 1, 2 or 3
  episodes a week, taken as concurrent on one Sunday slate.
- **Return on deployed vs total capital:** in the mid scenario, $68 over a peak of about $104 is
  about 65% a season on peak deployed capital. On a $1,000 illustrative total it is 6.8%. The two
  are shown separately (CURRENT screen fields; the screen uses average deployed capital, which is
  lower than peak).
- **Capacity:** UNKNOWN. Pregame depth has never been stored.
- **Uncertainty:** the effect size is unknown and may be zero. §A.G shows even the sign of the
  settlement P&L is not inferable in one season.

### C.2 Family B (EXP-003, KXHIGHNY same-venue)

| Scenario | Basis | Variable contribution |
|---|---|---|
| Today | Proof: no positive worst-state surplus is claimable (§B #2, #3). Observed: 1.06–1.09 per $1 basket before fees in every evaluable round (2 + 2 event days) | **$0 claimable** |
| If Kalshi confirmed #2 and #3 | 365 event days × 1–5% of days with a surplus episode × 10–100 baskets × $0.01 | $0.37 – $18 / year (scenario) |

- **Fixed cash:** $0. **Capacity:** UNKNOWN.
- **Owner time:** approving and reading the Kalshi questions.
- **Conclusion (PROPOSED):** even a favourable answer leaves a very small scenario. This supports
  the pause in §B.

### C.3 Bootstrap-relevant economic threshold (PROPOSED; not an approved target)

This is the minimum useful annual after-cost contribution (`[economics] minimum_useful_effect`),
tested on the **conservative** (FIRST_DETECTION_ZERO_LATENCY) lower band, never on the hindsight
bound.

| Option | Threshold | Reading | Tradeoff |
|---|---|---|---|
| A: learning | $250 / year at ≤ $1,000 illustrative capital | proves after-cost value exists at research size | continues families that can never matter |
| **B: bootstrap (recommended)** | **$1,000 / year at ≤ $2,500 illustrative peak deployed capital** (about 40% a year on illustrative total capital) | worth the owner's attention for a small bankroll; clearly above today's $0 incremental fixed cost, with room for a small paid data item later (to be priced then) | Family A reaches it only in the high scenario |
| C: step toward the aspiration | $5,000 / year | a meaningful income step | likely needs capacity beyond research sizes; it may stop a family that is small but real |

A small-capacity strategy can justify a small research budget. Option B is a floor for *continuing
beyond research*, not for *doing* the research.

### C.4 Owner effort (PROPOSED; owner hours are kept separate from agent or computer time; no hourly value assumed)

| Family | Initial allowance | Review point | Extension condition | Stop condition |
|---|---|---|---|---|
| A (EXP-002) | **6 owner hours** to 2026-10-22: about 1 h for the capture decision, 2 h to review the pilot report, 2 h to review the freeze, 1 h buffer | 2026-10-22 | pairing yield ≥ 50%, and the pilot-based sensitivity shows the markout test fits weeks 7–18 at the pessimistic ICC. Then +8 h to 2027-01-13 | yield < 50% after fixes; the pessimistic MDE over the remaining weeks is above 1 cent; interim futility (A.H); or the hours are spent |
| B (EXP-003) | **2 owner hours**: decide whether to send the questions; read the answer | 2026-11-15 | a written official answer resolving #2 and #3 favourably. Then a re-plan with a new allowance | no answer by 2026-11-15, or an unfavourable answer: reject the scope |

Agent and computer elapsed time is logged in PRs and handoffs. It is not charged to these
allowances, and it is bounded by the same review dates.

---

## D. Shadow-fill language (directive §7): what changed

**Finding.** The v1 wording overstated both fill modes:
- **"Conservative (fill at detection)"** assumes the first observed quote could be filled at its
  receipt time. It ignores decision and submission delay, and the quote may already be gone. It is
  not conservative about latency.
- **"Less conservative (the best single observation)"** picks the best observation *after the whole
  episode was seen*. No prospective policy could make that choice, so it is an oracle, a hindsight
  upper bound.

**Change (IMPLEMENTED, TESTED_LOCALLY; ADR 0037).**
- The enum values `CONSERVATIVE` / `LESS_CONSERVATIVE` are kept for compatibility.
- `research_economics` is now `research-economics-v2` with `fill-mode-labels-v2`. Its
  `FILL_MODE_SEMANTICS` defines:
  - **FIRST_DETECTION_ZERO_LATENCY**: prospective selection, not delay-adjusted, not executable;
  - **HINDSIGHT_UPPER_BOUND**: not prospective, not executable, may only rule a family out.
- Every screen report carries `fill_modes` and `executable_performance: "NONE: …"`.
- Every figure's note carries its label, and replay and capacity rows carry `mode_label`.
- The verdict arithmetic is unchanged: CONTINUE already used only the first-detection lower band,
  and UNVIABLE / BELOW_MINIMUM_USEFUL use the hindsight upper band. A test now pins that a
  hindsight-only surplus never gives CONTINUE.
- Wording changed to match:
  - `sports_evidence.FILL_MODES` texts;
  - `docs/RESEARCH_PRINCIPLES.md`;
  - the DRAFT EXP-002 `protocol.toml` and `experiment.toml` fill text.
- **Not changed:** EXP-001, its frozen fill policy, the shadow ledger and any recorded result. No
  result file used these labels.
- **Not done** (not permitted: "not permission to rebuild the execution simulator"): a
  delay-adjusted fill mode. It is proposed as a future registered variant: fill at the first
  observation received at least *d* seconds after detection.

## E. Stale EXP-003 readiness references (IMPLEMENTED)

In `experiments/EXP-003-same-venue-payoff-consistency/protocol.toml`, "the payoff evaluator is
PR B" and the blocker "Payoff evaluator and semantic conformance (PR B)" now name the merged
evaluator (#102, #105; ADR 0036) and the real open obligations (§B). The comment that
`prohibited_fields` are "declarative until" PR B now says the payoff scan enforces them. The proof
requirements, prohibited inputs and label rules are unchanged.

Stale references outside this writer's claim are reported to the coordinator, not edited:
- `docs/OWNER_IDEAS.md:343` ("`payoff_constraints.py` is planned (PR B)");
- `src/edge_lab/dashboard/data.py:1334` (comment: "absent until it lands");
- `src/edge_lab/dashboard/sports_fixtures.py:224` (a fixture message saying the evaluator "is not in this build").

## F. Evidence use in this session

- **Laptop store `data/edge_lab.sqlite3`** (whole-file sha256 `b867c021…9109089`), opened
  `mode=ro`. It was read for an inventory only: table names, and snapshot counts with min and max
  receipt times per source and kind. It holds no Odds API or KXNFLGAME rows. For KXHIGHNY it holds
  kalshi `event`, `markets` and `orderbook` rows from 2026-09-22. No payload, book, price, result
  or label was read.
  - Logged in EXP-003's `evidence_use.jsonl` as OPERATIONAL_ACCESS with no features, labels or
    results viewed.
  - Noted in EXP-002's README, because no EXP-002-scope data exists there.
- **Public documents** (§0) are not datasets and need no evidence-use record.
- **Nothing else** was read. The production store was not read, no API was polled, and nothing was
  sent to Kalshi.

## G. Items for other owners

| Item | Owner | Why |
|---|---|---|
| Record Decision 1 (Kalshi NFL capture) with the A.C pair window and the A.H pilot dates | coordinator / RU Writer O | The pilot cannot start without it. Each NFL week not captured is lost for good. |
| A KXNFLGAME fee-verification record (Q7 reading; event-level overrides) | `fee_schedules` owner | FEE_UNSUPPORTED blocks every all-in cost in Family A. |
| `JoinPolicy` asymmetric pair window as a registered join variant | `sports_evidence` owner (behaviour change) | A.C |
| The stale references in §E | coordinator / Terminal owner | stale documentation |
| Owner packet Decision 2 (§C thresholds and hours) | coordinator | owner input |
