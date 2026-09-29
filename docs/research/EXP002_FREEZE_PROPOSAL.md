# EXP-002 proposed freeze settings (`exp002-freeze-proposal-v1`, 2026-09-28)

Owner directive 2026-09-28 §8. VF Writer A, from `main` at `4e8e71d`. **These are technical settings for
review, not a questionnaire and not a freeze.** EXP-002 stays DRAFT. `protocol.toml` is not changed by this
document. A later version of this proposal gets a new version id; this one is never edited in place.

Status words are those of `RESEARCH_UNBLOCKING_DECISIONS.md`: APPROVED (a recorded owner decision), VERIFIED
(checked against cited primary evidence), PROPOSED (a recommendation only) and BLOCKED.

## 1. APPROVED owner economics (recorded; not re-decided here)

Source: `docs/owner/2026-09-26-owner-decisions-economics-backup.md`, item 1.

| Item | Approved value | What it is not |
|---|---|---|
| Minimum useful threshold | **$1,000/year after-cost contribution**, for deciding whether the family deserves continued development beyond the research/pilot stage. Packet option B attributes a test band: ≤ $2,500 illustrative peak deployed capital, on the FIRST_DETECTION_ZERO_LATENCY lower band. | Not a promise. Not a capacity estimate. Not a pilot requirement. Not a claim that the research ladder can produce it (A.E ladder scenarios: $1.70–$382.50 a season). **Not a substitute for a minimum detectable markout effect** (§3). |
| Owner hours | **6 owner hours through 2026-10-22**: pilot report 2 h, freeze review 2 h, buffer 2 h. Stop rules of C.4. | Hours are hours, never dollars; no hourly value is assumed. **The +8 h extension is NOT granted.** It returns to the owner. |

**Illustrative arithmetic only (not a forecast).** Assume about 15 games a week over about 17 remaining
weeks, which is about 255 games.
- At 250 contracts a game (about $125 of capital at P ≈ 0.5, about $1,900 a week if every game were held at
  once), the bar needs about **1.6¢ per contract after all costs, on every game**.
- At the 10-contract minimum it needs about 39¢ per contract.
- Under the general formula, which is UNVERIFIED for KXNFLGAME (§2), one taker leg costs about 1.75¢ at
  P = 0.5, plus about 0.5¢ of half-spread at a 1¢ spread. A T-6h→T-60m round trip therefore costs about 4.5¢.

## 2. VERIFIED contract facts (and what is not verified)

| Fact | State | Source |
|---|---|---|
| KXNFLGAME YES pays $1 on a win (overtime included) and $0 on a loss | VERIFIED | contract terms 2026-09-11; market rules (A.D) |
| A tie after overtime pays $1/(tied teams), rounded down = $0.50 | VERIFIED | terms; `rules_secondary` |
| Postponed and started within 48 h: normal result. Not started within 48 h, suspended before 55 min and not resumed, a forfeit before kickoff, a venue or home/away change, or a pre-game disqualification: a discretionary last fair price F ∈ [0, 1] | VERIFIED (discretionary F) | terms (A.D) |
| Suspended after 55 min, not resumed and not declared final | **CONFLICT**: "result as it stands" (terms, Sept) vs "last fair market price" (certification, Feb). Which governs is UNVERIFIED | A.D; unresolved by this task; provider question S1 drafted in `EXP002_FEE_VERIFICATION.md` (NOT SENT) |
| Settlement fee | "There is no settlement fee" (fee schedule 2026-07-07). Settlement rounding is not addressed | `EXP002_FEE_VERIFICATION.md` |
| KXNFLGAME trading fee | **FEE_UNSUPPORTED** (not resolved; no record added) | `EXP002_FEE_VERIFICATION.md` |
| Fill granularity 0.01 contracts; fills can be fractional for whole-contract orders | VERIFIED (documented behaviour) | Fixed-Point docs (EXP-001 `fee_verification/`) |
| A YES ask is 1 − the best NO bid (orderbook representation) | VERIFIED (documented) | `kalshi_quotes`; A.A |
| The first production books had 1¢ spreads at about +5 min from the odds | OBSERVATION (one weekend), not a contract fact | HANDOFF 2026-09-26; coordinator relay |

## 3. PROPOSED technical settings (every §8 item)

The central change: gate v3 (`EXP002_GATE_V3.md`) shows that the bias of the **mid-based** cross-book markout
cannot be bounded from the available observations. So this proposal recommends an **executable** primary
endpoint that needs no noise gate. The reviewed mid-based cross-book markout and its Kalshi-only placebo are
kept as descriptive secondary endpoints. Under directive §8 this change needs a versioned rationale (this
section and `EXP002_GATE_V3.md` §6) and review. It was chosen with **no EXP-002 data viewed**.

| # | Setting | PROPOSED value | Rationale | Depends on |
|---|---|---|---|---|
| 1 | Tie and not-played payoff bounds | `t_max = 0.01`, `u_max = 0.005` in `V = (1 − t − u)·p + 0.50·t + u·F`, F ∈ [0, 1]. Every state stays in the sample. | Deliberately loose (A.D). NFL ties are rare, but a **sourced official count is still required** before freezing; none is cited here. | a sourced count |
| 2 | Suspended-game rule conflict | Absorbed in `u`: both texts pay a value in [0, 1], so the bound does not depend on which governs. Recorded as UNRESOLVED. The precise provider question is drafted as S1 in `EXP002_FEE_VERIFICATION.md` (NOT SENT; the coordinator adds it to the Kalshi message file). No drafted question covered it before. | The bound needs only the payoff range, not the governing text. | — |
| 3 | Primary endpoint (**change proposed**) | **E1: executable gross round-trip markout, under the FIRST_DETECTION_ZERO_LATENCY fill assumption.**<br>**Entry (T-6h information only).** At the T-6h decision `D`, from AT_OR_AFTER_ODDS pairs only:<br>- buy the home YES if `c_low(home) − ask_H ≥ θ`;<br>- buy the away YES if `c_low(away) − ask_away ≥ θ`. `c_low(away)` is the lower end of the away contract's own A.D interval. It can be up to `u` below `1 − c_high(home)`, because the fallback F applies to each contract separately and `F_home + F_away` need not equal 1;<br>- at most one side per game (the larger margin; neither on a tie);<br>- eligible only if the T-6h ask shows displayed depth ≥ 1 contract.<br>No T-60m information enters eligibility.<br>**Exit.** At the **bid** of the first book of the same market received in the T-60m window. Statistic: gross P&L per contract, `bid₁ − ask₆`, 1 contract.<br>**Missing exit.** A missing T-60m exit is **scored, never dropped**: no T-60m book, no bid, a bid with displayed depth < 1, or an unusable book. The primary scores it by fallback to settlement: hold to the contract's final payoff, including a tie at $0.50 and a fallback F, with `bid₁` replaced by the payoff. The worst case, an exit at 0, is reported as a sensitivity. Both counts are in the attrition. | Under W, mid noise inside the spread cannot make the expected round trip positive (ask₆ ≥ V₆, E[bid₁] ≤ E[V₁]). A beyond-spread deviation the rule captures is priced at a displayed quote. Under FIRST_DETECTION_ZERO_LATENCY (the displayed ask and bid at receipt, no delay, displayed depth as a ceiling) it is the hypothesis, not a bias. **A displayed quote is not a proven fill.** So E1 needs no noise gate only under that fill assumption, and latency and fill sensitivities stay separate. | review |
| 4 | Direction rule and test | One-sided, H₀: E[gross P&L] ≤ 0. Game units; wild cluster bootstrap with Rademacher weights and NFL-week clusters (A.G); a one-sided 90% bound for futility. `θ = 1¢` (one tick beyond the ask), frozen before any label. | One tick stops sub-tick consensus differences from triggering trades. | review |
| 5 | Secondary endpoints | (a) The mid-based cross-book markout `y` and the placebo `y_pl` (A.A), labelled "**not bias-bounded**" (gate v3 INSUFFICIENT_EVIDENCE), descriptive. (b) Hold-to-settlement gross contribution of the E1 trades, descriptive. (c) The attrition waterfall. | Keeps the reviewed endpoint and placebo visible without an inferential claim. | — |
| 6 | Maximum input ages | Odds ≤ 10 min at `D`; Kalshi book ≤ 5 min at `D`; sportsbook `last_update` ≤ 10 min (all CURRENT) | Source-registry limits (A.C) | — |
| 7 | Pair-skew semantics | Join v2 window: the book from 5 min before to 10 min after the odds receipt, chosen prospectively (CURRENT). E1 admits AT_OR_AFTER_ODDS pairs only. BEFORE_ODDS pairs are counted, and are comparability-only for secondary (a). | An executable price exists only at the book's own receipt | A.C calibration (timing only) |
| 8 | Episode start / end / merge | A.F unchanged: pool = game. Start at 2¢ per contract **after fees** at 10 contracts. End at the first later horizon below it or at kickoff. Merge over the whole pregame window. | — | **BLOCKED** by FEE_UNSUPPORTED (no after-fee threshold is computable) |
| 9 | Minimum meaningful quantity | 10 contracts (A.E) | above a one-lot; depth unlikely to bind | — |
| 10 | Size ladder | 1, 10, 50, 100, 250 contracts (A.E). Descriptive rungs; visible depth is a ceiling. | — | — |
| 11 | Minimum useful measured effect | **δ_min(E1) = 1¢ gross per contract.** It is statistical and power-sized. The 12-week MDE at an SD of 2–4¢ is about 0.5–1.3¢ (A.G) if every eligible game trades. E1 trades only when the consensus clears the ask by θ: at about 30% trade frequency, the detectable effect is about **1.8× larger** (1/√0.3), about 0.9–2.4¢, so δ_min = 1¢ may be under-powered. The pilot's trade rate decides this before the freeze. The economic hurdle is evaluated **separately** once fees are verified: round-trip fees (about 3.5¢ at P = 0.5, UNVERIFIED) plus the $1,000 bar. | The bar and the statistical δ_min are different quantities (§1). | fee verification for the economic hurdle; pilot trade rate |
| 12 | Independent clusters and episodes | `min_independent_clusters` = max(8, ⌈weeks needed at ICC 0.10⌉) using the pilot SD of E1 (A.G). `min_episodes_for_scenario` = 20 distinct episodes over ≥ 4 weeks before any annual scenario. | Fewer episodes make a scenario one or two episodes deep | the pilot SD (a logged look) |
| 13 | Development and evaluation windows | See §4 | — | — |
| 14 | Variant budget | V0 (E1) plus at most 2 registered challengers (candidates: T-24h decision; θ = 2¢), Holm-corrected. The E0→E1 change is a **pre-registration design revision made with no data viewed**. It is recorded here and does not consume the budget. | A.H | — |
| 15 | Futility | **Operational** (at the freeze review): OPERATIONALLY_UNUSABLE if the AT_OR_AFTER_ODDS pairing yield of due T-6h horizons is < 50%, or E1 trades number < 1 per week over the pilot. **Statistical** (one interim, 2026-11-30): STATISTICAL_FUTILITY if the one-sided 90% upper bound of mean E1 gross P&L is < δ_min. **Economic**: ECONOMICALLY_UNVIABLE if the HINDSIGHT_UPPER_BOUND cannot clear fixed cash costs. | A.H, adapted to E1 | — |
| 16 | Continuation | Beyond the final review only with a named missing observation, its marginal cash cost (0 today) and owner hours approved at review. **The +8 h is not granted.** | A.H; owner decision | owner |

**What the first pairs establish.** Eighteen paired sides (9 games × 2 team markets, 2026-09-26 T-24h)
establish that **pairing works**. They do not establish independent games, a clustered sample or an edge.
"Eligible for economics" (AT_OR_AFTER_ODDS) is a timing classification only.

## 4. Windows reconciled against the evidence exposure (no silent shift)

| Window | Stated plan (A.H) | Reconciled proposal | Why |
|---|---|---|---|
| Development pilot | kickoffs 2026-09-27 → 2026-10-19 | **Unchanged.** The first captures were T-24h on 2026-09-26 17:00Z (HANDOFF), so the start matches. DEVELOPMENT role; every look logged. | — |
| Freeze | by 2026-10-21 | **Not promised.** E0 (mid markout) cannot be frozen: gate v3 has no pass. An E1 freeze needs review of §3, a sourced tie count, the A.C timing calibration (label-free, logged as FEATURE_INSPECTION) and this PR's Terminal fix deployed. The earliest realistic decision is the owner's freeze review on 2026-10-22 (2 approved hours). | Directive §7E: the standard is not lowered to meet the date |
| Evaluation (untouched) | kickoffs from 2026-10-22 through week 18 (about 2027-01-10) | **Starts at the first kickoff after both the freeze is recorded and the #124 Terminal fix deploy (2026-09-29T02:09:50Z, production REVISION 29a37d7)**, whatever that date is. If the freeze is recorded by 2026-10-21, that is 2026-10-22. Games between 2026-10-22 and a later freeze are **not** added to the untouched window, even if unviewed. The new start date goes into the freeze record. | Conservative; no retroactive holdout claim |
| Pilot label look (markout SD, placebo, E1 SD) | after the A.C timing freeze | Unchanged order. Logged as LABEL_RESULT_INSPECTION, DEVELOPMENT; those games are permanently excluded from evaluation. | A.G step 5 |

**Evidence exposure as known on 2026-09-29.**
- **Production log.** The coordinator reports that production's `evidence_use.jsonl` holds only its header:
  no production look is logged. The coordinator's own production reads displayed no T-60m price. Those reads
  were T-24h rows, status counts, `report --summary` with labels hidden, and the label-free v2 gate.
- **Possible, unlogged label exposure.** The Terminal's Family A capacity panel showed the "latest paired book".
  That could be a T-60m book, whose ask and depth are a price-only EXP-002 label.
  - This was possible for pilot games from the first captures on 2026-09-26 until the #124 deploy at
    2026-09-29T02:09:50Z (REVISION 29a37d7). #124 stopped it.
  - Whether anyone viewed such a book is **UNKNOWN**.
  - The Polymarket US related-market T-60m captures on the Data sources tab are a possible correlated proxy. The
    coordinator records that in HANDOFF for a follow-up.
- **Hand-recorded event.** This possible exposure is recorded append-only in EXP-002's `evidence_use.jsonl`:
  - event `eu-7f8e61282393c0bf2258b4bc90dd92c7`, via `edge-lab experiments record-use`;
  - actor: coordinator (recorded by VF Writer A); role DEVELOPMENT; scope `sports:nfl:moneyline`, from
    2026-09-26;
  - `viewed_labels` null (unknown), `viewed_results` false, `influenced_tuning` false to the coordinator's
    knowledge.

  That event's window ended at its record time, 2026-09-29T01:16:30Z. The follow-up event
  `eu-f4954194ccbea8817aef73d4343122bb` (appended 2026-09-29, same fields and labelling, NOT A CONFIRMED VIEW)
  extends it to the #124 deploy, **2026-09-29T02:09:50Z**, and closes the window.
- **Availability counts (NIT, noted rather than hidden).** The report's and the Terminal's join and attrition
  counts still say whether a T-60m pair or book existed (pairing status and stage). That is weak label
  information: a missing or unusable T-60m book can reflect market events. T-60m **prices, sizes, depth and
  ladders** are now hidden, in the report rows and the Terminal, unless a logged `--with-results` run shows them.
  The Terminal's capacity counts cover pre-label books only.
- **Consequence: pilot-window T-60m data must be treated as potentially exposed.**
  - They are DEVELOPMENT only, as they already were.
  - They can **never be relabelled untouched**.
  - The **evaluation window must start after 2026-09-29T02:09:50Z** (the #124 deploy) and after the freeze is
    recorded, whichever is later. No kickoff at or before that time can be in the untouched window.
  - The A.C timing calibration record must state "T-60m book prices possibly seen (UNKNOWN, unlogged Terminal
    display)" rather than certify that no label was in view.
- **This session** viewed **no real EXP-002 data**, only SYNTHETIC fixtures and simulations.

## 5. Freeze blockers (all must clear; none is cleared by this document)

1. Review of the E1 primary endpoint change (§3 #3–#5, #11), or a different reviewed design. E0 cannot be
   frozen, because gate v3 has no pass.
2. A sourced tie and not-played count behind `t_max` and `u_max`.
3. The A.C timing calibration from pilot timing fields, logged, with the exposure caveat above.
4. KXNFLGAME fees verified for any after-fee figure (episode threshold, economic hurdle). The gross E1 test can
   be frozen without them, but no net claim can be made.
5. This PR merged and deployed (the Terminal label display fix) before the first evaluation-window T-60m
   capture. DONE: deployed 2026-09-29T02:09:50Z (REVISION 29a37d7), and the exposure window was closed by
   `eu-f4954194ccbea8817aef73d4343122bb`.
6. The owner's freeze review (2026-10-22), within the 6 approved hours.
