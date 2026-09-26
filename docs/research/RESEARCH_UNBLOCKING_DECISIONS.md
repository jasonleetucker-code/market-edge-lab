# Research unblocking decisions: EXP-002 protocol, EXP-003 proof obligations, economics

Owner directive "RESEARCH UNBLOCKING" of 2026-09-25 (`docs/owner/2026-09-25-research-unblocking-directive.md`),
sections 6, 7, 9 and 10 and the matching parts of 14 and 15. Written by RU Writer R (research,
protocol and contract evidence) on 2026-09-25. First written from `main` at `706a340`; revised after
review on `main` at `886fbff` (the owner's Kalshi NFL capture approval, #110).

**This document authorizes nothing.** It is a set of recommendations with evidence. Kalshi NFL
collection was approved separately by the owner on 2026-09-25 (`docs/EXECUTION_PLAN.md`, #110),
bounded by `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §6; this document neither creates nor widens
that approval. It does not approve any of these:
- anything outside #110's capture bounds;
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
| APPROVED | Only with a cited, recorded owner decision. **The only APPROVED item cited here is Kalshi NFL collection (#110); every recommendation is PROPOSED.** |
| BLOCKED | Cannot proceed until the named blocker is removed. |
| VERIFIED | Checked against primary evidence cited here (a document, a fixture or a test run). |

## Summary

| # | Topic | Recommendation | Status | Needs |
|---|---|---|---|---|
| A.A | EXP-002 primary endpoint | **Cross-book predictive markout**: the sign of the consensus-vs-Kalshi gap at T-6h is taken from one team market's book, and the markout to T-60m is measured on the *other* team market's book (converted to the same team's units), averaged over both assignments. This fixes the review's finding that a same-book markout is biased upward under a no-information null. **Gate:** a label-free pre-freeze check that the cross-book noise correlation is below a derived `ρ_max = (¼·δ_min) / b̂`. **Supplementary bias check:** a Kalshi-only placebo (the same statistic with the consensus replaced by the signal book's own T-24h mid). Calibration and hold-to-settlement economics are secondary and descriptive only. | PROPOSED | technical review; freeze before preregistration |
| A.B | Horizon and cutoff | Decision horizon T-6h; markout target T-60m. Decision time = the later of the two receipts, at or before the capture deadline. A later observation is never moved back. | PROPOSED | technical review |
| A.C | Input age and pair skew | Keep the CURRENT source limits (odds 10 min, Kalshi book 5 min). Provisional pair window: the book from 5 min before to 10 min after the odds receipt, chosen prospectively (the latest book at or before the odds within 5 min, else the first book within 10 min after). Only book-at-or-after-odds pairs support executable-price or economics figures. It fits #110's pairing clause (option (a)). Calibrate on pilot timing data only. | PROPOSED | technical review; a join variant and a `pick_book` follow-up |
| A.D | Ties, cancellations, not-played | Explicit payoff modelling with ex-ante bounds; every state kept in the sample. Cite the verified contract terms. | PROPOSED; rules VERIFIED | owner input on the bounds is not needed; technical review |
| A.E | Size ladder and capital | Research rungs of 1, 10, 50, 100 and 250 contracts, with the minimum episode size at 10. Illustrative capital of $250, $1,000 and $5,000, each labelled ILLUSTRATIVE. No approved capital exists. | PROPOSED | owner choice only for any real amount |
| A.F | Episode | One pool per game. Start at 2 cents per contract after fees at 10 contracts. An episode spans the capture horizons of one game and one direction and never infers persistence between captures. | PROPOSED | technical review; freeze before any label |
| A.G | Sample size, clusters, power | Game unit, NFL-week clusters. `scripts/research_power_sensitivity.py` gives ranges. The frozen n comes from a logged 3-week development pilot, not from this document. | PROPOSED (script VERIFIED by tests) | technical review |
| A.H | Windows and stopping | Pilot on kickoffs 2026-09-27 to 2026-10-19 ET (first targets: the Saturday 2026-09-26 T-24h captures for Sunday games, if #112 is deployed by then); freeze by 2026-10-21; untouched evaluation on kickoffs from 2026-10-22 (weeks 7–18); review 2026-10-22; one interim futility look; a variant budget of V0 plus at most 2. | Collection APPROVED (#110; implementation #112 pending deploy). The pilot design is PROPOSED | technical review |
| B | EXP-003 proof | The KXHIGHNY partition **cannot be proven** under current contractual text. Nothing constrains the discretionary fair-price fallback, so a worst-state payout of 0 cannot be excluded and the evaluator must assume it; integer settlement is only observed. The single-market YES+NO complement survives fallback, but it cannot show a surplus from one consistent book. Emergency powers (Rule 2.8) need an explicit scoping decision: PROPOSED to exclude them from the admissible states and report them as residual venue risk (otherwise no Kalshi payoff relation is ever provable, and the verdict becomes reject). **Pause the scope.** Keep one bounded fact-verification task (8 drafted Kalshi questions, not sent). Reject the scope if it is unresolved by 2026-11-15. | PROPOSED | owner approval to contact Kalshi; review of the scoping |
| C | Economics and effort | Scenario tables per family (Family A within the research ladder: $1.70 to $382.50 a season). Bootstrap threshold PROPOSED at $1,000 per year (first-detection lower band, illustrative capital of $2,500 or less), with $250 and $5,000 as alternatives. Owner-hour allowances: Family A 6 h to 2026-10-22, then +8 h if extended; Family B 2 h. | PROPOSED | owner decision (packet Decision 2) |
| D | Shadow-fill language | "Fill at first detection" relabelled FIRST_DETECTION_ZERO_LATENCY. "Best single observation" relabelled HINDSIGHT_UPPER_BOUND. Both are marked non-executable, versioned as `research-economics-v2` / `fill-mode-labels-v2` (ADR 0037). | PROPOSED (a change in this PR; its tests pass) | review |
| E | Stale EXP-003 readiness | The protocol's "evaluator is PR B / not built" wording is replaced with the real blockers. The proof requirements are unchanged. | PROPOSED (a change in this PR) | review |

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
The planned implementation (#112, not merged at this writing) captures the Kalshi target at the
Odds receipt time, so a book is expected about 5 min after the odds, or about 20 min after when a
protected window, a lock wait or a retry intervenes. That is a plan, not a measurement.

---

## A. EXP-002 protocol recommendation

**Scope (CURRENT, unchanged).** NFL pregame moneyline, odds-consensus-v1 exactly as implemented,
and Kalshi KXNFLGAME as the first executable-price route. No fitted winner model. No other sport,
market type or venue is added to inflate the sample.

### A.A Primary endpoint

| | |
|---|---|
| **Recommended** | **Cross-book predictive markout** (v2 after review). Each game has two KXNFLGAME markets, one per team, each with its own book; both are captured in the same run at every horizon (#110 bounds: 2 book GETs per game-horizon). Work in home-team units: `H_t` is the home market's YES mid; `A_t = 1 − (away market's YES mid)`. `c` is the consensus value of the home team's YES contract (A.D) at the T-6h decision time `D`. Per game: `y = ½·[ sign(c − H₆)·(A₁ − A₆) + sign(c − A₆)·(H₁ − H₆) ]`, where subscript 6 is the paired T-6h book and 1 the first book received for the T-60m horizon. The sign of each half comes from one book and its markout from the other. Test H₀: E[y] ≤ 0, one-sided, on game units with NFL-week clusters. `|c − H₆|` may enter only as a pre-registered filter, never tuned. |
| **Why not the v1 statistic** | The v1 statistic `sign(c − k₆)·(k₁ − k₆)` used one book's noisy mid `k₆` both in the sign and as the base. Mid noise then reverts and makes E[y] > 0 with **no information at all**. The review simulated +0.05¢ at 0.25¢ of mid noise and +0.18¢ at 0.5¢, the size of the effect grid. `python scripts/research_power_sensitivity.py --null-check` reproduces it: +0.06¢ and +0.19¢, with standard errors of about 0.01¢. |
| **Required bias check (placebo)** | The same cross-book statistic with `c` replaced by a Kalshi-only prior signal: the signal book's own T-24h mid (`y_pl = ½·[sign(H₂₄ − H₆)·(A₁ − A₆) + sign(A₂₄ − A₆)·(H₁ − H₆)]`). It carries no consensus information. It is computed on the pilot and reported beside the primary in the evaluation. The claim needs the primary one-sided test to pass **and** the paired game-level difference `y − y_pl` to pass the same test. **The placebo is supplementary, not a certificate.** It also responds to genuine Kalshi momentum or mean reversion between captures, and it reacts to correlated book noise at only a third to 40% of the bias. A clean placebo therefore does not certify that the bias is absent; the label-free correlation check below is the gate. |
| **Null check (simulation, VERIFIED by tests)** | Model: a martingale latent value; a consensus that knows only the current value; each book's mid = latent + noise. The cross-book primary and the placebo are centred at 0 under independent book noise, including 1¢ rounding (`tests/test_research_economics_power_sensitivity.py`). With book-noise correlation ρ, the cross-book bias is about **ρ × (the v1 same-book bias)**. `--null-check` shows this across ρ = 0–1: at ρ = 0.5 it is +0.10¢ with 0.5¢ of noise and +0.29¢ with 1¢, which exceeds the smallest grid effect. |
| **Correlation threshold (derived, not fixed)** | `ρ_max = (¼ · δ_min) / b̂`, where:<br>- `δ_min` is the pre-registered minimum markout effect;<br>- `b̂ = σ̂² · √(2/π) / sd(g)` estimates the v1 same-book bias;<br>- `σ̂` is the book-noise SD (it must include price-grid rounding, about tick²/12 of variance, which the empirical estimates below already contain);<br>- `sd(g)` is the observed SD of the T-6h gap `c − H₆`.<br>So the remaining bias `ρ · b̂` is at most a quarter of the minimum effect (`research_power_sensitivity.rho_max`; the analytic `b̂` matches the simulation within its standard error, tested).<br>**Worked example:** δ_min = 0.5¢, σ̂ = 0.5¢, sd(g) = 1.12¢ gives b̂ = 0.18¢, and ρ_max = 0.125¢ / 0.18¢ ≈ **0.70**. With σ̂ = 1¢ and sd(g) = 1.41¢: b̂ = 0.56¢ and ρ_max ≈ 0.22. With δ_min = 0.25¢ and σ̂ = 0.5¢: ρ_max ≈ 0.35. `--null-check` prints the full table. |
| **Pre-freeze check (label-free; the gate)** | It uses only same-capture books at T-24h and T-6h and repeat books of one horizon, all features. No T-60m book (a label) is read.<br>(a) **Cross-book dispersion:** `d_t = H_t − A_t`, which is `H_t − (1 − away mid_t)`, at the same capture. A dispersion near zero means mirror quoting (ρ ≈ 1), and the endpoint fails at once.<br>(b) **Noise scale** from repeat books of the same market and horizon received within 15 min (the A.C calibration already collects them): `σ̂² = ½ · var(H_t − H_t′)`, and the same for the away book. Latent drift inside the 15 min inflates `σ̂`, which errs toward failing.<br>(c) `ρ̂ = (σ̂_H² + σ̂_A² − var(d)) / (2 σ̂_H σ̂_A)`. The endpoint is frozen only if the one-sided 90% upper bound of `ρ̂` (week-cluster bootstrap) is below `ρ_max`. Otherwise it is **not frozen** and goes back to design. There is no silent fallback.<br>**Limitation:** noise that persists across the 15-min repeat understates `σ̂`, and therefore `ρ̂`. The check can then pass too easily, so the repeat-book gap and the count of repeat pairs are reported with it. |
| **Gate as implemented (v2, #119)** | `sports_evidence.noise_gate`, run by `python -m edge_lab.sports_evidence exp002`. Changes after review: a negative `ρ̂` or bound is MODEL_MISFIT (INSUFFICIENT_DATA; sticky quotes make repeat books understate the noise and drove v1 to a false PASS); `b̂` uses `σ̂² = max(repeat σ̂², Var(d)/2)`; the bound is the larger of a week-cluster and a game-cluster bootstrap; at least 4 NFL weeks. **No v2 verdict is freeze-eligible**: a v2 pass is named `PASS_REPEAT_ONLY_NOT_FREEZE_ELIGIBLE`, because moderate stickiness can still pass it. A freeze needs a reviewed gate v3 (A.I). The repeat estimator is not feasible under the approved capture (A.I). |
| **Post-label sensitivity (not label-free)** | After the A.C limits and the gate above are settled, the Roll-type estimate is computed on the pilot as a DEVELOPMENT-data sensitivity check and logged as LABEL_RESULT_INSPECTION. That estimate is the negative covariance of successive mid changes, `−cov(H₆ − H₂₄, H₁ − H₆)`, and it needs the T-60m book. It is never used as the gate. It is biased toward passing when Kalshi has momentum. |
| **Model limits** | Assumptions: (i) the two team books' mid noises are independent at a given capture; (ii) under the null the latent value is a martingale between captures; (iii) `A = 1 − away mid` measures the home contract. The last holds in win, loss and tie states; fair-price and post-start disqualification states break it (§B #11), but they are rare and shift the level, not the markout. |
| **Probability benchmark vs execution price** | Kept separate. The markout uses **mids** (probability benchmarks, used only when the spread is at most a frozen width). All economics use the **executable all-in ask** at size (A.E, §C). An ask includes spread and fees, so it is a price to pay, not an unbiased estimate of probability. A YES ask on Kalshi is `1 − best NO bid` (documented orderbook behaviour, `kalshi_quotes`), so a mid is `(yes_bid + 1 − no_bid)/2`. |
| **Reason** | (1) The capture design (T-24h / T-6h / T-60m, both team books each time) gives a later price on two books for every paired game, so a markout exists per game. An economics endpoint exists only per rare episode. (2) Power: the per-game hold-to-settlement P&L has SD ≈ 0.5 per contract (a mathematical bound for a binary payoff), and under every assumption in the grid it needs more than 120 weeks (about 7 seasons; §A.G). A markout SD of 1–4¢ fits one season under some assumptions; 6–8¢ (news-driven repricing) does not. (3) Ties and fair prices move both captures alike, so the markout is less sensitive to the tie treatment than a level comparison is (A.D). (4) It tests the stated mechanism, that event-market books lag the consensus. |
| **Evidence** | `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §2 item 7 (horizon resolution only); `scripts/research_power_sensitivity.py` (grid and `--null-check`); contract terms (A.D). **No result of any kind exists**, so the choice cannot have been made by looking at which result is better. No outcome, label or markout has been viewed. |
| **Tradeoff** | A markout is forecast quality about a *later price*, not money. A positive markout proves information transfer, not an exploitable edge. Exploiting it means buying at T-6h and either holding to settlement (high variance) or exiting at T-60m (a second spread and fee). The T-60m mid is itself a benchmark, not truth. The cross-book design costs no extra capture, but it depends on assumption (i). |
| **Uncertain** | The markout SD and the cross-book noise correlation (both from the pilot); the spread width at which a mid is meaningful; the stability of the lag; whether pregame books update between captures at all. |
| **Needs** | Technical review (statistics). Freeze in `[endpoints] primary` before preregistration, with the placebo and the pre-freeze checks. |
| **Status** | PROPOSED |

**Secondary endpoints (PROPOSED, descriptive only this season).**
1. Outcome calibration at T-60m: log loss and Brier score of `c` (tie-adjusted interval midpoint)
   against the Kalshi mid, per game. It is reported with its interval and never tested for
   significance this season.
2. Hold-to-settlement after-cost contribution per contract at each rung, first-detection and
   hindsight bounds (§D), from book-at-or-after-odds pairs only (A.C). Descriptive and capacity evidence only. §A.G shows it cannot be
   inferential in one season.
3. The attrition waterfall with separate denominators (CURRENT, `research_evidence`).

**Alternative 1: outcome calibration as the primary endpoint** (for example a log-loss difference
at T-60m). It is closer to settlement economics. It needs the tie and fallback bounds (A.D) in the
level comparison, and it is badly under-powered in one season. It fits a multi-season plan only.

**Alternative 2: a markout to a later "closing" book** (for example T-10m). It captures more of
the pregame repricing. It needs a new capture horizon, which is outside #110's bounds, so it would
need a capture change and a new approval.

**Alternative 3: a regression.** Regress `H₁ − H₆` on `c − H₆`, controlling for the Kalshi-only term
`H₆ − H₂₄`. This is the review's third option. It uses one book, so the noise in `H₆` sits in both
the regressor and the outcome (errors-in-variables). The control absorbs only part of that. It is
kept as a sensitivity analysis, not as the primary endpoint.

### A.B Horizon and information cutoff

| | |
|---|---|
| **Recommended** | Decision horizon **T-6h**, markout target **T-60m**; T-24h → T-6h is a registered challenger (it counts against the variant budget, A.H). Record per pair: the intended target time (`target_utc`), the effective due time (`odds_schedule.effective_due`), the cutoff `C` (`odds_schedule.deadline`: effective due + 30 min, never later than kickoff − 5 min; CURRENT), the odds receipt `R_o`, the book receipt `R_k`, per-book market `last_update`, and the decision time **`D = max(R_o, R_k)`** with `R_o, R_k ≤ C` (CURRENT in `sports_evidence.kalshi_side`). The markout target book is the first book received in the T-60m horizon window: from the T-60m effective due time minus the capture schedule's 7-minute early tolerance (a slot may fire that early, and #112 books follow the odds capture) to its cutoff. This amendment (2026-09-26) matches the implementation (`sports_evidence.markout_endpoint`); the placebo's T-24h books use the same window form. The actual elapsed time `R_k(T-60m) − D` is recorded; the nominal "5 hours" is a label, not a measurement. |
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
| Odds/book receipt skew (`R_k − R_o`) | **from −5 min to +10 min**: a book up to 5 min before the odds, or up to 10 min after | PROPOSED (CURRENT is a symmetric 5 min, `JoinPolicy.max_pair_skew`) | The asymmetry follows from the two age limits. A book *before* the odds becomes the stale input at `D`, so it must be within the book limit (5 min). A book *after* the odds is fresh at `D` and makes the odds the older input, bounded by the odds limit (10 min). #112 plans the book about +5 min after the odds, exactly at today's symmetric limit, so ordinary jitter would fail pairs. PR C's symmetric 10-min candidate would admit a 10-min-old book as the executable side, which is not supported. |
| Book choice within the window | **Prospective rule:** the latest book received at or before the odds receipt and within 5 min of it; if there is none, the first book received within 10 min after the odds. The choice never depends on how close a later book happens to be. | **Implemented in join v2** (`sports-paired-join-v2`, `sports_evidence.pick_book`, follow-up PR `fix/ru-research-followups`); join v1 picked the book *closest* to the odds receipt, a mild look-ahead. Each paired side now records `book_timing` (BEFORE_ODDS / AT_OR_AFTER_ODDS) and `pair_use`, and only AT_OR_AFTER_ODDS pairs get a size ladder and feed the economics episodes (Pair use, below), also implemented in that PR. The candidate books are limited to this horizon's window, so an ad-hoc capture of another horizon is never picked | A decision-maker at the odds receipt holds the latest book already received, or waits for the next one. |
| Pair use | **Book-at-or-after-odds pairs** (`R_k ≥ R_o`) support executable-price and economics figures (A.E, §C, the episode screen). **Book-before-odds pairs** are comparability-only: they may enter the markout and calibration endpoints, but not an executable price or an economics figure, because their book is older than the decision time. | PROPOSED | An executable price exists only at the book's own receipt time. |

**Fit with the owner's approval (#110).** The approval leaves pairing precision to "proposal §6
options (a) or (b)". Option (a) freezes a maximum skew of 10 min and keeps the pairs outside it in
the denominators as PAIR_SKEW_EXCEEDED. The window above is inside option (a): its "after" side is
10 min, and its "before" side is tighter. Under #112's plan almost every book arrives at or after
the odds, so the "before" side will rarely be used and almost all pairs support executable-price
figures. The +20-min cases (protected windows, lock waits, retries) fall outside the window. They
are excluded as PAIR_SKEW_EXCEEDED and counted in the denominators. Under option (b), capturing the
book in the same run, the skew would shrink to seconds and the window would not bind.

**Calibration procedure (PROPOSED; bounded; before any label is viewed).**
1. Use only the development pilot weeks (A.H) and only **timing and feature-side fields**:
   `R_o`, `R_k`, `last_update`, spreads and depth. No outcome and no T-60m markout book is read.
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

**Needs:** technical review. The asymmetric window and the prospective book choice are implemented
as join v2 (`JoinPolicy.max_book_before_odds` = 5 min, `max_book_after_odds` = 10 min; follow-up PR
`fix/ru-research-followups`). They remain provisional until the A.C calibration freezes them, and any
change is a registered join variant.

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
| The league declares the game complete or final (any time) | the result as declared or as it stands | terms; certification (both agree) |
| Suspended after 55 min of play, not resumed, not declared final | the result as it stands (Sept terms) or the last fair market price (Feb certification): conflicting texts, UNVERIFIED which governs | terms vs certification |
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
| **Pairs used** | Only book-at-or-after-odds pairs (A.C). A book-before-odds pair is comparability-only and never prices a rung. |
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
| Week and slate | Games are clustered by NFL week (`sports_evidence.week_cluster`, CURRENT). Inference uses a **wild cluster bootstrap** (Rademacher weights, week clusters; preferred because only about 12 week clusters exist), with cluster-robust errors as a check. |
| Rare signals | The economics endpoint has about 1–3 episodes a week (see below), so it is descriptive. |
| Missing or unsupported events | Stay in the attrition denominators with raw reasons (CURRENT). A game missing because its book was thin is informative missingness, reported and not imputed. |

**Sensitivity (`python scripts/research_power_sensitivity.py`; `research-power-sensitivity-v1`;
one-sided α = 0.05, power 0.80; 15 games a week; planning horizon 14 weeks).** Every row is an
assumption.

| Endpoint | Scenarios that fit 14 weeks | Weeks needed across the grid |
|---|---|---|
| Markout (primary): SD 1–8¢ (up to 6–8¢ covers inactive/injury-news repricing), effect 0.25–1¢, ICC 0–0.10, eligible 30–90% | 51 of 180 | 0.46 to 1,899 |
| Hold-to-settlement P&L per contract: SD 0.45–0.5, effect 1–5 cents, episode rate 10–30% | **0 of 144** | 124 to 34,000 |

Examples:
- Markout SD 0.02, effect 0.5 cent, ICC 0.05, 60% eligible (9 games a week): about 15.4 weeks, so
  it does not fit.
- The same with a 1-cent effect: about 3.9 weeks.
- The minimum detectable markout over a 12-week evaluation window at 9 games a week (ICC 0–0.10):
  0.48–0.64¢ at SD 2¢, 0.96–1.28¢ at SD 4¢, 1.44–1.92¢ at SD 6¢ and 1.92–2.56¢ at SD 8¢.
- SD 6¢ and 8¢ with a 1¢ effect need about 35 and 62 weeks (ICC 0.05, 60% eligible): out of reach
  this season.
- The 0.25¢ effect is at or below half a tick of mid resolution (a mid on a 1¢ grid moves in 0.5¢
  steps). It is a lower-edge scenario, not a detectable per-game price move.
- Hold-to-settlement over 12 weeks at 2.7 episodes a week: about 22 cents per contract. It is not
  a usable inferential endpoint.

The week-level dependence also sets a floor: however many games a week are analysed, weeks needed
is at least `n_eff × ICC`.

**Pilot-data requirement (PROPOSED), instead of a fabricated n.** Three NFL weeks of approved
paired capture (about 55 games; A.H), used as DEVELOPMENT data and logged. From feature-side and
timing data they must give:
1. the pairing yield of due T-6h and T-60m horizons;
2. the skew and age distributions (A.C);
3. spreads and pregame depth at the rungs;
4. the label-free correlation gate (A.A: cross-book dispersion and repeat-book noise), from
   feature-side books only;
5. the SD of the markout statistic, the Kalshi-only placebo and the post-label Roll-type
   sensitivity (A.A). These **do** need the T-60m books, which are labels. This step comes only after the A.C
   timing limits are frozen from timing data alone, so no timing limit is chosen with markouts in
   view. The pilot games' markouts are then viewed, logged as LABEL_RESULT_INSPECTION on
   DEVELOPMENT data, and those games are permanently excluded from the untouched window.

Three weeks cannot estimate the week ICC, so ICC stays a sensitivity range (0–0.10), and the
frozen n uses the pessimistic end (ICC 0.10) unless the evaluation window is long enough to
tolerate it. The frozen `min_independent_clusters` (weeks) is `ceil(weeks_required)` at the
pessimistic ICC, with a floor of 8 weeks so the wild cluster bootstrap is meaningful.

**Four kinds of evidence (PROPOSED), never mixed:**
1. **Descriptive feasibility** (pilot): counts, yield, timing, spreads and depth.
2. **Inferential** (the evaluation window): the markout test only.
3. **Annual capacity scenarios** (§C): labelled scenarios, produced only after `min_episodes_for_scenario` is met.
4. **Live readiness**: not in scope. It needs gates 8–9, orders and owner approval.

### A.H Evaluation windows and stopping

| Item | Recommended | Status |
|---|---|---|
| Development pilot | Kickoffs from 2026-09-27 to 2026-10-19 ET: the Sunday and Monday games of the week of 2026-09-22 plus three complete Tuesday-anchored weeks (`sports_evidence.week_cluster`). The first targets are the Saturday 2026-09-26 T-24h captures for the Sunday 2026-09-27 games, if #112 is deployed by then; otherwise the pilot starts at the first deployed capture, with its end date unchanged. By the repository fixtures' numbering, Sunday 2026-09-27 is NFL week 3 (Thursday 2026-09-24 was week 3); dates govern, not week numbers. DEVELOPMENT role, every look logged. | **Collection APPROVED** (owner, 2026-09-25, `docs/EXECUTION_PLAN.md`, #110; collection only, within SPORTS_PAIRED_EVIDENCE_GAPS §6). Implementation #112 **pending deploy** (expected about Saturday morning). The pilot design and its use are PROPOSED; the protocol stays DRAFT |
| Validation approach | No parameter search. V0 only. The delayed-signal and placebo controls (CURRENT `[evaluation] controls`) run on pilot data. Timing limits are calibrated as in A.C. | PROPOSED |
| Freeze | Protocol frozen (PREREGISTERED) by 2026-10-21, before the first evaluation kickoff, with `holdout_windows` set | PROPOSED |
| Untouched future window | Kickoffs from 2026-10-22 (week 7 Thursday) through the end of the regular season (week 18, about 2027-01-10); scope `sports:nfl:moneyline`, identified by outcome window **and** dataset hash. Playoffs are a pre-registered optional extension. Pilot games are never relabelled as untouched. | PROPOSED |
| Review dates | 2026-10-22 (CURRENT `[budget] review_date`): feasibility and freeze review. 2026-11-30: interim (see futility). 2027-01-13: final. | PROPOSED |
| Futility | **Operational** (at 2026-10-22): pairing yield below 50% of due T-6h horizons after fixes, or a median pregame spread above 2 × the start threshold, gives OPERATIONALLY_UNUSABLE. **Statistical** (one interim at 2026-11-30, about half the planned weeks): stop if the one-sided 90% upper confidence bound of the mean signed markout is below the minimum markout effect. **Economic**: the hindsight upper bound (§D) of after-cost contribution cannot clear fixed cash costs, giving ECONOMICALLY_UNVIABLE. | PROPOSED |
| Continuation | Beyond 2027-01-13 only with a named missing observation (for example "playoffs" or "season 2027 weeks 1–6"), its marginal cash cost (0 today) and its owner hours, approved at the review. Never an open-ended extension. | PROPOSED |
| Variant budget | V0 plus at most 2 registered challengers (candidates: T-24h decision; the symmetric 5-min skew), with Holm correction across primary and challengers. Every tried timing limit, filter or horizon counts. | PROPOSED |

### A.I Gate feasibility under the approved capture (2026-09-26)

**The repeat estimator will not have data.**
- The approved capture (#110, SPORTS_PAIRED_EVIDENCE_GAPS §6) makes 1 listing + 2 book GETs per game-horizon, one
  book per team market.
- Retries happen only after a failure, and a failed GET stores no book.
- So a second stored book of the same market inside one horizon, which is what a repeat is, should almost never
  exist.
- The gate needs at least 10 repeats per side over at least 4 NFL weeks. Under the approved capture it will stay
  INSUFFICIENT_DATA through the planned 2026-10-21 freeze and after it. This is expected, not a fault.
- Even with repeats, sticky pregame quotes make 5–15-minute repeats understate the noise.
  - Severe stickiness shows as MODEL_MISFIT or REPEAT_NOISE_ZERO.
  - **Moderate stickiness can still PASS in v2.** The review simulated 4 weeks × 15 games × 2 horizons, a repeat
    for every book and 20 seeds. At a true ρ of 0.5–0.6, with repeats carrying 50–60% of the noise variance,
    v2 passed 12–19 runs in 20, while the true bias was 1.5–2 times the tolerable. `ρ̂ ≈ 1 − (1 − ρ)/f` stays
    at or above 0, so the misfit guard never fires.
  - **So a v2 PASS is never freeze-eligible.** v2 names it `PASS_REPEAT_ONLY_NOT_FREEZE_ELIGIBLE`, every verdict
    carries `freeze_eligible: false`, and a test pins this with the review's parameters. Nothing in gate v2
    authorizes a freeze.

**Two ways forward (both PROPOSED; neither is implemented; no capture is added here).**

| Option | What | Cost and bound | Reaches 4 weeks by 10-21? | Weakness |
|---|---|---|---|---|
| (i) One extra book GET | One extra book per team market about 5 min after the T-6h capture | About 14–16 games a week: +28–32 GETs normally (about 144 → 176), and up to +64 with one retry each. The worst case becomes about 352 + 7, **above the approved 288 + 7 bound**, so it needs a new owner approval. About +64–192 KB a week | No. Approval and deployment take days, which leaves about 2–3 weeks of repeats before the freeze. The freeze would move to about 2026-11-04 | A 5-minute repeat of a sticky book may not change at all (REPEAT_NOISE_ZERO), or may change too little (MODEL_MISFIT) |
| (ii) Single-capture spread estimator | `σ̂² = mean(spread²)/12`: the fair value is assumed uniform inside the quoted bid–ask spread. It is available for both books at every capture, label-free | No new GET, and within #110's bounds | Yes: the week clusters of 2026-09-22 (Sun/Mon), 09-29, 10-06 and 10-13, if capture runs from 2026-09-26 | Stale quotes, with the fair value outside the spread, **understate** the noise, which biases `ρ̂` low and so errs toward PASS. A fair value concentrated near the mid overstates the noise, which errs toward FAIL. It is a model assumption, not a measurement |

**Recommendation (PROPOSED): option (ii) as the gate's primary noise scale, with guards.**
- **Scale.** Use `σ̂² = max(spread σ̂², repeat σ̂² where it exists, Var(d)/2)` for `b̂`.
- **Correlation.** Compute `ρ̂ = 1 − Var(d)/(2·σ̂²_spread)`.
- **Misfit.** Keep the MODEL_MISFIT rule.
- **Cross-check.** Treat the repeat estimator as a cross-check whenever repeats happen to exist.

Why:
- It needs no new approval and no extra requests.
- It is the only option that can reach the four-week floor by the 2026-10-21 freeze.
- Its anti-conservative case (stale quotes) is the same stickiness that defeats option (i).

v2 already reports the spread estimate as `diagnostic_spread_estimator` (not used for the verdict). The first real
weeks will show how it compares with the dispersion before any change to the gate. Switching the gate to it is a
versioned change (gate v3) that needs review.

**What gate v3 must show before any verdict of it is freeze-eligible (PROPOSED requirements):**
1. It combines the spread-based noise into both the noise floor for `b̂` and the correlation bound, so that
   repeat stickiness cannot lower either.
2. It is re-simulated on the review's grid (4 weeks × 15 games × 2 horizons, ρ 0.5–0.6, repeat variance fraction
   0.5–0.6, 20 seeds), and on stale-quote cases where the fair value leaves the spread.
3. It reports the false-PASS rate at a true bias above the tolerable. The rate must be at most the nominal 10% of
   the one-sided 90% bound, or the gate stays not freeze-eligible.
4. It gets an independent review.

Option (i) is not recommended now: it needs a new approval, breaks the approved worst-case bound, cannot reach four
weeks before the freeze, and is weak under sticky quotes. This is for the owner to decide; the coordinator brings
it.

---

## B. EXP-003 proof obligations

The evaluator exists (`payoff_constraints.py`, ADR 0036, #102/#105) and is **not** rebuilt here.
The question is whether any allowlisted set can meet its proof requirements under the corrected
formula:

```
worst_state_surplus = min_s( sum_i( q_i*payout_i(s) - settlement_cost_i(s, fill_i)
                                    + refund_i(s, fill_i) ) - basket_settlement_cost(s, fill) )
                      - sum_i(acquisition_cost_i(fill_i)) - state_independent_costs
```

This is verbatim from `src/edge_lab/payoff_constraints.py` (module docstring, lines 21–23), and it is
the same formula as EXP-003 `protocol.toml` `named_hypothesis`.

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
| 2 | Partition, nested threshold | KXHIGHNY, any cross-market set | The discretionary fallback preserves the relation: Σ v_i = 1 across the event | Rules: with missing data, all strikes resolve to "the last fair price" at the Exchange's sole discretion. Each strike gets its own value. No text constrains the sum | E (the state exists), U (sum constraint) | Are fallback prices across a mutually exclusive event constrained to sum to $1? | Every v_i = 0 cannot be excluded, so a conservative evaluator must assume the basket pays 0 in that state, and **no positive surplus can be claimed**. Every evaluated production and laptop scan row had the fallback, valued at 0, as its worst state (CURRENT evaluator behaviour) | Q1 to Kalshi |
| 3 | Any set | Kalshi, any series | The VOID / REFUND / CANCELLATION cash flow is known | Rule 2.8(d), emergency actions: (b) reduction of positions, (c) cancellation of a contract with the return of funds paid to enter trades, (f) changing a contract's terms; Rule 6.3(c): discretionary payouts | E (the powers exist), U (whether a cancellation returns fees) | Does a cancellation return trading fees and rounding fees as well as prices? | Depends on the scoping decision in note B-1. If emergency actions are admissible states, a cancellation state caps the worst-state surplus at 0 (at −fees if fees are not returned), and reductions and term changes make every relation unprovable | Scoping decision (note B-1, PROPOSED); Q3 to Kalshi |
| 4 | Complement | One Kalshi market, YES + NO in equal quantity | NO pays 1 − v in every state, including fallback | Rule 6.3(a): a binary contract pays the settlement value to long holders when the payout criterion is met, otherwise to short holders; Rule 6.3(c): when the payout cannot be determined, its last-traded-price example pays $0.10 long / $0.90 short, otherwise the committee's "fair allocation"; Rule 6.3(b): a scalar settlement is split between long and short; settlement docs: "Only net positions are settled (after netting)" | E for the last-traded method; I for the Outcome Review Committee's "fair allocation"; D (netting) | Is NO always paid $1 − v under a committee allocation? | The relation holds in structure under E and I. `payoff_constraints.fallback_cell` already records NO = 1 − v as an assumption (CURRENT) | Q2 to Kalshi |
| 5 | Complement (economics) | One Kalshi market | A YES + NO surplus can exist in a consistent book | The orderbook returns bids only; best YES ask = $1 − best NO bid, best NO ask = $1 − best YES bid (docs `orderbook_responses`; `kalshi_quotes`). So YES ask + NO ask = 2 − (yes bid + no bid) ≥ 1 unless the book is crossed, which is flagged as an anomaly | D, and I that the matching engine prevents a resting crossed book | none | **Pre-fee surplus ≤ 0 in any consistent snapshot, so the complement is provable-in-structure but economically empty.** A positive reading would be a data artefact (non-simultaneous levels) | D + I: no surplus by construction (the reciprocal book is documented; that the matching engine never rests a crossed book is inference); no further work |
| 6 | Tie state | KXHIGHNY | No TIE state | Integer settlement puts every value in one bracket (CURRENT proof, `KXHIGHNY_PROOF`) | depends on #1 | #1 | Stands or falls with #1 | — |
| 7 | Correction state | KXHIGHNY | Corrections only select among the NORMAL states | "Revisions after the Expiration Date are not included" (GLOBALTEMPERATURE; SETTLEMENT §4) | E | none | Excluded with evidence (CURRENT) | — |
| 8 | Fees on fractional fills | Kalshi taker fills | The all-in cost of a walk that crosses fractional levels is known | Fee Rounding docs: per-fill trade fee rounded up to $0.000001, balance alignment to $0.0001 (direct) or $0.01, and an order-level accumulator with a capped rebate; 0.01-contract granularity | D (mechanics), with the account type owner-attested | none for the mechanics; exact rebate order across split fills (Q5) | Those sizes are NOT_EVALUATED (CURRENT). Implementable from the docs, but not worth building while #2 and #3 block any claim | Defer. Q5 only if the scope reopens |
| 9 | Settlement costs | Kalshi binary settlement | settlement_cost_i(s) is known | Fee PDF p.3: "There is no settlement fee". Docs: settlement fees are zero for yes/no determinations but "may apply for sub-cent scalar settlement"; the payout is rounded to the balance precision (MiscFeeAmt) | E (no fee), D (rounding) | Is a fair-price settlement a "scalar" settlement subject to rounding? | Bounded: under $0.0001 per market settlement for a direct member, under $0.01 for non-direct. Small, and it can be carried as a bound | Q6; then record a bound |
| 10 | Transfer costs | Account funding | Basket economics include deposit and withdrawal costs | Fee PDF p.3: ACH free; debit card up to 2%; wire bank fees; crypto processor fees; alternate rails 0–2% | E | the owner's funding rail (not needed for research) | These are per-account fixed costs, outside the per-basket formula. They belong in §C fixed costs, not in `settlement_cost_i` | Note in §C |
| 11 | Partition | KXNFLGAME, the two team markets of one game, YES + YES | Exhaustive and exclusive, summing to $1 | Win/loss: 1 + 0; tie: 0.50 + 0.50 (E); fair price: v_A + v_B unconstrained (U); disqualification after the start: "No" for the disqualified team and "Yes" for the opponent only if declared winner, so 0 + 0 is possible (E). The event record says `mutually_exclusive: true`, `collateral_return_type: MECNET` (undocumented here) | E / U | Q1 for this series; Q8 (MECNET) | Not provable. It is also **outside EXP-003's allowlist and universe**: adding it would be a new series variant and need review | Do not add. Recorded only because Family A shares the series |

**Note B-1: emergency powers need an explicit scoping decision (PROPOSED; technical review; the
formula is not changed).**
- Rulebook v1.29 Rule 2.8(d) lets Kalshi, in an emergency, among other things:
  - (b) reduce positions;
  - (c) cancel a contract and return the funds paid to enter trades;
  - (f) change a contract's terms and specifications.
- These powers exist for every Kalshi contract. Treated as admissible settlement states:
  - (c) caps any basket's worst-state surplus at 0. It is at −fees if fees are not returned, which
    is unknown (Q3).
  - (b) and (f) can put a basket in any state.
  - So **no payoff relation on Kalshi is ever provable**, and H-B1 is unattainable whatever the
    prices.
- **PROPOSED scoping:** exclude Rule 2.8 emergency actions (and Rule 7.2 contract modifications)
  from the admissible settlement states.
  - Record them as **residual venue risk** in every result, beside counterparty, operational and
    orphan-leg risk.
  - The contract's own fallback clauses (fair price, #2) and Rule 6.3(c) / 7.1 outcome
    determination stay **admissible**, because they are ordinary settlement provisions, not
    emergency actions.
  - `StateProof.excluded_kinds` would carry this scoping as its evidence text. That is a reviewed
    protocol amendment, logged, before any further scan.
- **How the verdict depends on it:**
  - **With the proposed scoping**, the cancellation cap disappears. The pause rests on #1 (integer
    settlement, Q4) and #2 (the fallback sum, Q1). Q3 only informs the residual-risk statement.
  - **If emergency actions are admissible**, every Kalshi same-venue relation is unprovable, and
    the recommendation becomes **reject now**, for EXP-003's whole Kalshi scope, not just
    KXHIGHNY.

**Verdict (PROPOSED).**
1. **The full KXHIGHNY bracket partition cannot be proven today.** The contract text does not
   constrain the fallback prices, so a worst-state payout of 0 cannot be excluded and a
   conservative evaluator must assume 0 (#2). Integer settlement is only observed (#1). No positive
   surplus can be claimed, and every stored scan agrees (no surplus even before fees: 1.06–1.09 per
   $1 basket).
2. **The simpler allowlisted relationship, the single-market complement, is the only one that
   survives fallback** (#4: E for Rule 6.3(a) and the last-traded method, I for a committee
   allocation). It cannot produce a surplus from one consistent book (#5, D + I). It is
   provable-in-structure but economically empty.
3. **Recommendation, under the proposed emergency-power scoping: pause the current EXP-003 scope,
   and keep one bounded fact-verification task.**
   - No new solver, scan or fractional-fee feature is built while #1 and #2 are open.
   - If the owner approves, send Q1–Q4 (and Q5–Q8 for completeness) to Kalshi.
   - Reopen only on a written, official answer that fallback prices of a mutually exclusive event
     sum to $1 (Q1) **and** that KXHIGHNY values are whole degrees or the brackets cover
     non-integers (Q4). The scoping amendment must also be recorded.
   - **Reject** the KXHIGHNY partition scope, recorded with its reasons and never deleted, if there
     is no answer by **2026-11-15**, or the answer is negative.
   - If review rejects the scoping and treats emergency actions as admissible: reject now (note
     B-1).
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
> and return the funds paid to enter trades. In that case, are trading fees and rounding fees
> returned together with contract prices? Are there other paths (Rule 6.3(c), Rule 7.1) by which a
> contract is voided with funds returned rather than settled at a value?
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
| High (the ladder's top rung; capacity UNVERIFIED) | 51 | 250 | $0.03 | **$382.50** | ~$388 (3 concurrent × $129.375) |

Other quantities:
- **Fixed incremental cash costs:** $0. The Odds API free tier stays inside its 450-credit cap,
  and Kalshi public data is free. Paid data is not authorized.
- **Shared infrastructure:** the existing VPS. Its allocation is UNKNOWN / OWNER_INPUT and it is not
  incremental.
- **Transfer costs:** $0 by ACH; up to 2% by card (fee PDF p.3). This is per-deposit and outside
  the per-contract formula.
- **Concurrency** (an assumption): about 20 weeks a season, playoffs included, give 1, 2 or 3
  episodes a week, taken as concurrent on one Sunday slate.
- **Return on deployed vs total capital:** the screen reports these separately (CURRENT fields,
  using average rather than peak deployed capital). As **scenario arithmetic only**, not a return
  and never to be quoted as one: the mid row is $68 against about $104 of peak deployed capital, or
  against a $1,000 illustrative total.
- **Economics use only book-at-or-after-odds pairs** (A.C). Book-before-odds pairs are
  comparability-only.
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
tested on the **first-detection** (FIRST_DETECTION_ZERO_LATENCY) lower band, never on the
hindsight bound. The first-detection bound is not delay-adjusted, so passing it is a research
state, not an execution result.

| Option | Threshold | Reading | Tradeoff |
|---|---|---|---|
| A: learning | $250 / year at ≤ $1,000 illustrative capital | proves after-cost value exists at research size | continues families that can never matter |
| **B: bootstrap (recommended)** | **$1,000 / year at ≤ $2,500 illustrative peak deployed capital** | worth the owner's attention for a small bankroll; clearly above today's $0 incremental fixed cost, with room for a small paid data item later (to be priced then) | No Family A scenario within the research ladder reaches it (the high row is $382.50), so reaching it needs capacity beyond 250 contracts, which is UNVERIFIED |
| C: step toward the aspiration | $5,000 / year | a meaningful income step | likely needs capacity beyond research sizes; it may stop a family that is small but real |

A small-capacity strategy can justify a small research budget. Option B is a floor for *continuing
beyond research*, not for *doing* the research.

### C.4 Owner effort (PROPOSED; owner hours are kept separate from agent or computer time; no hourly value assumed)

| Family | Initial allowance | Review point | Extension condition | Stop condition |
|---|---|---|---|---|
| A (EXP-002) | **6 owner hours** to 2026-10-22: the capture decision (given 2026-09-25, #110), 2 h to review the pilot report, 2 h to review the freeze, 2 h buffer | 2026-10-22 | pairing yield ≥ 50%, and the pilot-based sensitivity shows the markout test fits weeks 7–18 at the pessimistic ICC. Then +8 h to 2027-01-13 | yield < 50% after fixes; the pessimistic MDE over the remaining weeks is above 1 cent; interim futility (A.H); or the hours are spent |
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

**Change (PROPOSED in this PR; its tests pass locally and in CI; ADR 0037).**
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

## E. Stale EXP-003 readiness references (PROPOSED in this PR)

In `experiments/EXP-003-same-venue-payoff-consistency/protocol.toml`, "the payoff evaluator is
PR B" and the blocker "Payoff evaluator and semantic conformance (PR B)" now name the merged
evaluator (#102, #105; ADR 0036) and the real open obligations (§B). The comment that
`prohibited_fields` are "declarative until" PR B now says the payoff scan enforces them. The proof
requirements, prohibited inputs and label rules are unchanged.

Stale references outside the first PR's claim:
- `src/edge_lab/dashboard/data.py` and `src/edge_lab/dashboard/sports_fixtures.py`: fixed in the
  follow-up PR `fix/ru-research-followups` (wording only; behaviour unchanged).
- `docs/OWNER_IDEAS.md:343` ("`payoff_constraints.py` is planned (PR B)"): coordinator-owned, still
  open.

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
| Deploy #112 (Kalshi NFL capture, APPROVED in #110) before the Saturday 2026-09-26 T-24h targets | coordinator / RU Writer O | Each NFL week not captured is lost for good. |
| The markout endpoint (A.A/A.B): use the first book of the T-60m horizon; `markout_label_ref` today is the next book at any horizon | `sports_evidence` owner | when the endpoint is implemented |
| A KXNFLGAME fee-verification record (Q7 reading; event-level overrides) | `fee_schedules` owner | FEE_UNSUPPORTED blocks every all-in cost in Family A. |
| `docs/OWNER_IDEAS.md:343` (§E) | coordinator | stale documentation |
| Owner packet Decision 2 (§C thresholds and hours) | coordinator | owner input |
