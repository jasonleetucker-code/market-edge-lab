# EXP-002 pre-freeze gate v3 (`exp002-noise-gate-v3`): specification, validation, verdict

Owner directive 2026-09-28 §7 and §23 (`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`).
Written by VF Writer A on 2026-09-28 from `main` at `4e8e71d`. **This document authorizes nothing.** EXP-002
stays DRAFT, EXP-001 is untouched and no freeze, gate advance or capture change is proposed as approved.

## Verdict in one paragraph

The spread-based noise scale (RESEARCH_UNBLOCKING_DECISIONS A.I option ii) was a candidate needing validation,
and it **failed** that validation. In an adversarial simulation it passed in up to **98%** of samples while the
true bias of the markout exceeded the tolerable level. That happened in 21 of 37 simulated settings: sticky,
stale, shared-upstream and near-mirror quotes, and week-level dependence. **A quoted 1¢ spread is not a bound on
latent pricing error, staleness or common market-maker noise.** A stale, sticky or commonly mispriced quote can
be 1¢ wide while the value it later reverts around lies outside it. From one capture, nothing in the spreads,
the same-capture dispersion or the T-6h gaps reveals this.

Spreads can bound the bias only under an assumption W (defined below) that these observations cannot
identify. So gate v3 has **no PASS state**. Its verdicts are `FAIL`, `INSUFFICIENT_DATA` or
`INSUFFICIENT_EVIDENCE`, and `freeze_eligible` is always false. The freeze of the current mid-based primary
endpoint stays **blocked**. This document names the exact missing information and recommends an altered
design (§6) that does not depend on the noise gate. The standard was not lowered to meet 2026-10-21.

## 1. What is preserved (unchanged)

| Item | State |
|---|---|
| Gate v2 (`exp002-noise-gate-v2`, `sports_evidence.noise_gate`) and its semantics | Unchanged code and verdict names. `PASS_REPEAT_ONLY_NOT_FREEZE_ELIGIBLE` is never freeze-eligible. It still runs in `exp002` beside v3 (output key `gate`). |
| The split-team (cross-book) markout endpoint and the Kalshi-only placebo | Unchanged (`cross_book_markout`, `kalshi_only_placebo`, `markout_endpoint`). |
| Join v2 pairing (`sports-paired-join-v2`) and BEFORE_ODDS comparability-only handling | Unchanged. v3 counts BEFORE_ODDS sides and admits them, as the markout does. They never get a size ladder or an economics episode. |
| Timing and exclusion counts | Every due T-6h row falls in exactly one v3 count (tested reconciliation). |
| Logged outcome access | `exp002 --with-results` still records a LABEL_RESULT_INSPECTION first. v3 reads no label. |
| No-freeze semantics | Kept and strengthened: v3 cannot pass, and freeze eligibility is reported separately (`freeze_eligibility`). |
| The measurement output | Version `exp002-measurement-v2`: v1's keys are unchanged, and `gate_v3` is added. v1 outputs keep their own version string. |

## 2. Specification

**Inputs and units.** Only the join's T-6h paired rows feed the bound. T-24h paired rows are used for
diagnostics only (dispersion and spreads). Per admissible T-6h game, in probability units (1¢ = 0.01) and
home-team units:
- `H6` is the home market's YES mid and `s_H` its quoted spread.
- `A6` is 1 − the away market's YES mid, and `s_A` is its quoted spread.
- `c` is the consensus value of the home YES contract, exactly as the markout signs it (`_contract_value`: the
  tie-adjusted midpoint when bounds are declared, otherwise unadjusted and flagged).
- `c'` is 1 − the consensus value of the away YES contract.

No book payload is read beyond the join's features. No T-60m book is read, and the catalog carries no settled
listing field.

**The spread-to-noise relationship (the only one v3 uses), with its justification.** v3 does not estimate a
noise variance from spreads. The uniform `s²/12` model of A.I is an arbitrary distributional choice: a stale
quote breaks it, and the validation (§4) shows it false-passing. Instead v3 computes the one bound that spreads
can support, and only under stated assumptions:
- (W) **within-spread**: each book's reverting mid error `|mid − V| ≤ s/2`. Here V is the value the price later
  reverts around, the latent martingale of the A.A null.
- (I) The consensus deviation `w = c − V` is independent of the T-6h book errors.
- (R) The T-60m error is mean-zero given T-6h information, or persists with a coefficient in [0, 1].
- (N) The A.A null holds: V is a martingale that the consensus does not predict.

Under (W), (I), (R) and (N), each half of the cross-book statistic has `|bias| ≤ E[s_A · 1{|c − H6| ≤ s_H}]`.
The argument:
1. `sign(c − H6) = sign(w − e_H)`, and this differs from `sign(w)` only when w lies between 0 and `e_H`.
2. `E[sign(w)·e_A] = 0` under (I).
3. `|e_A| ≤ s_A/2` under (W).
4. `|w| ≤ |e_H|` implies `|c − H6| ≤ 2|e_H| ≤ s_H`.

So `B = mean over games of ½[s_A·1{|c − H6| ≤ s_H} + s_H·1{|c' − A6| ≤ s_A}]`. B assumes no distribution, no
density and no noise correlation. The worst case, a perfectly shared error, is allowed. A Monte Carlo test
checks the bound under a fully shared ±s/2 error (`test_the_bound_holds_when_the_value_is_inside_every_spread_...`).

**Floors and caps.**
- `INSUFFICIENT_DATA` below 20 admissible T-6h games or 4 NFL weeks. Three weeks give only 27 distinct
  week-cluster resamples. These floors are implementation parameters, not research thresholds, and they only
  gate INSUFFICIENT_DATA.
- There is no multiplier, noise floor or cap to tune. Wide books (3¢ or more) are counted, never excluded:
  excluding them would be anti-conservative and inconsistent with the markout, which uses them.

**Locked, crossed, stale and missing books.**
- Locked (bid = ask), crossed (bid > ask) and one-sided or empty T-6h books have no mid. They are excluded and
  counted separately (`t6_book_locked`, `t6_book_crossed`, `t6_book_one_sided_or_empty`).
- A horizon without a pair, or with a side missing, is `t6_not_paired` (the join stage keeps the reason).
- A book stale at the decision time never pairs: the join's 5-minute book age.
- A quote that is stale at the source cannot be detected. Kalshi books carry no per-level update time, and
  this is the core of the verdict.
- A pair captured more than 120 s apart is admissible, but it gives no same-capture dispersion
  (`not_same_capture`).

**Common-noise assumptions.** None beyond W. The bound allows fully shared error, because the same-capture
dispersion `H − (1 − away mid)` cancels any shared component and so cannot bound it. Using two team markets
does not prove independent noise. Mirror quoting (dispersion variance zero over at least 20 pairs) is `FAIL`:
the cross-book design then removes none of the reversion bias.

**Sample requirements.** At least 20 admissible games and 4 NFL weeks for any bound. The admissible share of
due T-6h horizons is reported, because informative missingness (for example, stale games failing to pair) is
possible.

**Uncertainty.** The one-sided 90% percentile of a week-cluster bootstrap and of a game-cluster bootstrap of B
(seed 20260926, 2000 resamples each). The larger is used.

**Permitted uses.**
- Diagnostic reporting of label-free spread, gap and dispersion distributions.
- Stating the conditional bound, labelled conditional on W.
- Planning a smaller question, an altered design or an acquisition proposal.

**Not permitted.**
- Freeze eligibility or a freeze decision.
- Promotion of any EXP-002 state.
- A claim that the markout is unbiased.
- Tuning an estimator, floor or multiplier until it passes.

**What cannot be identified from the available observations.**
1. A reverting error shared by both team books, from one market maker or one upstream source. It cancels in
   the dispersion and leaves every spread unchanged.
2. Staleness: there is no per-level update time, and receipt time is the only clock.
3. Latent error beyond the quoted spread. Only later prices (T-60m books, which are labels) or dense repeats
   show it.
4. The split between reversion and momentum from T-6h to T-60m.
5. The distribution of the error inside the spread.
6. Week-level ICC from four or fewer weeks.

## 3. Verdict rules

| Verdict | When | Freeze eligible |
|---|---|---|
| `FAIL` | Mirror quoting: the same-capture dispersion variance is ≤ 1e-10 over at least 20 pairs | never |
| `INSUFFICIENT_DATA` | Under 20 admissible T-6h games or 4 NFL weeks, or a bound that cannot be estimated | never |
| `INSUFFICIENT_EVIDENCE` | Otherwise. `bound_state` is `CONDITIONAL_BOUND_AT_OR_ABOVE_TOLERABLE` when even under W the upper 90% bound reaches ¼·δ_min, so spreads cannot bound the bias at that δ_min. It is `CONDITIONAL_BOUND_BELOW_TOLERABLE_BUT_ASSUMPTION_W_UNIDENTIFIED` otherwise. | never |

δ_min stays UNKNOWN until the protocol freezes it. The table is given per candidate (0.25¢, 0.5¢, 1¢), or for
a value supplied with `--min-effect`.

**What the conditional bound means at the observed 1¢ spreads.** With `s_H = s_A = 1¢`, B = 1¢ × the share of
gaps inside one spread.
- If the gap SD is about 1.5¢, B ≈ 0.5¢. That is above the tolerable 0.25¢ even at δ_min = 1¢.
- A gap SD of 3¢ or more would be needed for B < 0.25¢.

So at plausible values, **spreads cannot bound the bias even if W is granted**. When they can, the result
rests on W.

## 4. Adversarial validation (summary; full table in `EXP002_GATE_V3_VALIDATION.md`)

`python scripts/research_power_sensitivity.py --gate-v3-validation --reps 200` (`exp002-gate-v3-validation-v1`).
It is deterministic.

**Data-generating process.**
- The latent value is a martingale over T-24h → T-6h → T-60m (moves of 3¢ and 2¢ SD).
- Consensus = V6 + an independent deviation of 1.5¢ SD, or 6¢ SD in the "wide gaps" cases.
- Each book quotes the tick interval around the market maker's fair value (V + error), optionally widened. In
  the W-holds controls, the interval is around V itself.

**True bias.** E[y] of the cross-book markout under that scenario's null, from a separate simulation of
60,000 games (seed 20261001).

**Gate samples.** 200 label-free samples of 4 weeks × 15 games per scenario (seed 20260928; 200 bootstrap
resamples per run), each run through:
- the rejected spread candidate (A.I option ii exactly: `σ² = mean(s²)/12`, `ρ̂ = 1 − Var(d)/(2σ²)`, the
  misfit rule, week- and game-cluster bounds, `ρ_max`);
- `noise_gate_v3` itself.

**False pass.** A pass while the true bias is more than 2 SE above ¼·δ_min. BORDERLINE rows are excluded.

**Scenarios.** They cover every §7C case:
- sticky prices;
- narrow but stale quotes;
- correlated team-market quoting and a shared upstream source (including near-mirror books);
- zero observed movement with hidden uncertainty;
- asymmetric spreads;
- price discreteness;
- a common-value move between the two captures that inflates the dispersion;
- small samples with informative missing horizons;
- week-level dependence;
- partial persistence;
- the #119 review grid (ρ = 0.55);
- every row at δ_min = 0.25¢, 0.5¢ and 1¢ (the smallest-effect sensitivity).

| Rule | Rows with true bias above tolerable | Worst false-pass rate | Rows over the 10% acceptance |
|---|---|---|---|
| Spread candidate (A.I option ii) | 37 | **98%** | **21** |
| v3 conditional bound, where W holds (what v3 would pass if W were granted) | 2 | 0% | 0 |
| v3 conditional bound, where W fails | 35 | **88%** | **4** |
| **v3 verdict** | 37 | **0%** | 0 |

**Reading.**
- The candidate fails the ≤ 10% acceptance by a wide margin, so it is rejected.
- The conditional bound is valid where W holds.
- It false-passes at up to 88% where W fails (stale or shared error with wide gaps, δ_min = 1¢).
- **W is exactly the assumption the data cannot check.** So a spread-based verdict cannot be promoted to a
  pass, and v3 has none.
- v3 meets the acceptance trivially, because it never passes. It is a non-promotion gate, not a certificate.
- The conditional bound is also conservative: in every W-holds row with a small true bias, it stayed above the
  tolerable level. It could not pass a clean design either.

**Process disclosure.**
- The scenarios and seeds were fixed before the gate results were used for any decision.
- After one 10-rep smoke run, the stale, sticky, frozen, week and persistence scenarios were given 0.1¢ of
  book-specific error. Without it, both books quoted the same tick interval, and those cases exercised only the
  mirror path. Two near-mirror and within-spread cases were also added (recorded in the script).
- The gate v3 code was not changed after any simulation result.
- No real data were used. The validation seeds are independent of the unit-test seeds.

## 5. Real data

This session had no production access and read no production output. The first production weekend
(2026-09-26/27) has T-24h, T-6h and T-60m Kalshi books with 1¢ spreads (HANDOFF; coordinator relay). Those
spreads are exactly the case §3 shows cannot bound the bias. A label-free v3 run on production needs this PR's
code. The coordinator can run it read-only, with no `--with-results`, so nothing needs logging:

```
sudo -u edgelab env PYTHONPATH=<checkout of this PR's head>/src /opt/market-edge-lab/venv/bin/python \
    -m edge_lab.sports_evidence exp002 --db /var/lib/market-edge-lab/edge_lab.sqlite3 --out /tmp/exp002_v3.json
```

Expected verdict: `INSUFFICIENT_DATA` until 4 NFL weeks exist, then `INSUFFICIENT_EVIDENCE` (or `FAIL` if the
two team books are mirror quotes). T-60m books are labels. They were not used to design this gate, and they
must not be used to judge it.

## 6. Recommendations (PROPOSED; review and owner decision required)

The freeze of the mid-based cross-book markout stays **blocked**.

**Missing information.** The covariance of the reverting error shared by both team books at T-6h, relative
to the reversion by T-60m. It is not identifiable label-free, and not precisely identifiable in one season even
with labels. With latent moves of about 3¢ per interval, a Roll-type cross-book covariance from about 60 pilot
games has a standard error of about 1.2e-4 (√(0.03⁴/60)). The level that would have to be excluded is about
3e-5 to 6e-5 (δ_min 0.5–1¢ at a gap SD of 1.5–2¢), a shared-error SD of roughly 0.55–0.8¢. That would take
thousands of games.

1. **Altered evaluation design: an executable round-trip endpoint, recommended.**
   - Replace the mid-based markout as the primary with a pre-specified executable rule. At T-6h, buy the YES
     side whose ask is below the consensus value (the A.D interval's conservative end) by more than a frozen θ.
     Mark to the first T-60m book's **bid** on the same market, and hold to settlement as a secondary.
   - Mid noise inside the spread cannot make the expected gross round-trip P&L positive: under W, the
     ask ≥ V6 and E[bid₁] ≤ E[V₁] = V6.
   - A deviation beyond the spread (a stale quote) that the rule captures is executable money at the snapshot.
     That is the hypothesis, not a bias.
   - So this endpoint needs **no noise gate**. It keeps the Kalshi-only placebo and the cross-book check as
     descriptive controls.
   - Costs:
     - it trades only when the consensus lies outside the Kalshi spread, so it has fewer units and less power;
     - it measures GROSS P&L until KXNFLGAME fees are verified;
     - fills remain FIRST_DETECTION_ZERO_LATENCY at displayed depth (labels v2), never executable performance.
   - A change of primary needs a versioned rationale and review (directive §8). No data were viewed in
     choosing it.
2. **Smaller question.** Report the mid markout and placebo only as a DEVELOPMENT description of
   information transfer, labelled "not bias-bounded". No inferential claim.
3. **Bounded acquisition, not recommended.** One extra pre-decision Kalshi book capture per team market at
   about T-11h (2 GETs per game, no Odds credits) would allow a label-free cross-book reversion estimate,
   `−cov(H₁₁ − H₂₄, A₆ − A₁₁)`. That needs an owner capture approval beyond #110. Also:
   - the precision argument above shows one season cannot reach the needed resolution;
   - Kalshi momentum biases it toward passing.

   Nothing is added to capture here, and no request cap is raised.

The freeze proposal (`EXP002_FREEZE_PROPOSAL.md`) carries these as PROPOSED settings.

## 7. Terminal

Research & Data → Research → Economic evidence · A shows the gate line. It is gate v3's diagnostic, with
freeze eligibility separate and always "Not eligible".

The Terminal's "latest paired book" no longer shows a T-60m book. A T-60m book is EXP-002's markout label,
and the Terminal is not a logged consumer of labels. Before this change the capacity panel could show a T-60m
ask and depth for pilot games. Any such viewing was unlogged, so pilot T-60m label exposure is **UNKNOWN**. It is
hand-recorded as a possible exposure in EXP-002's evidence-use log (`EXP002_FREEZE_PROPOSAL.md` §4). The gate
line's outcome-access field shows such records as "possible (unconfirmed)", apart from confirmed label views.
