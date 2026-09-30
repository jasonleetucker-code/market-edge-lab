# EXP-002 E1 design review (`exp002-e1-design-review-v1`, 2026-09-30)

**Purpose.** This review answers freeze blocker 1 of `EXP002_FREEZE_PROPOSAL.md` (`exp002-freeze-proposal-v1`) §5:
"Review of the E1 primary endpoint change (§3 #3–#5, #11), or a different reviewed design." It is an independent
methodology review, by a statistician and market-microstructure skeptic, written from `main` at `e8703d7`.

**Status.** Every recommendation is **PROPOSED**. Nothing here freezes, approves or authorizes anything. EXP-002
stays DRAFT, and `protocol.toml`, the freeze proposal (never edited in place), the E1 code and EXP-002's evidence
log are unchanged. The owner's freeze review on 2026-10-22 decides. A parallel writer is producing
`EXP002_FREEZE_PROPOSAL_V2.md`; the changes below are written so that v2 can adopt, amend or reject each one.

**No EXP-002 data was viewed.** This review read no production database, no pilot book, odds capture, pair,
T-60m book or settlement, ran no `exp002` command (with or without `--with-results`), and read no web page of NFL
2026 results or standings. It read repository documents and code only. The EXP-002 evidence-use log was read for
its event ids, actions and notes (metadata about earlier looks), not for any data. Every number below comes from
repository documents or from the seeded SYNTHETIC simulations in §8, which use no real data. Nothing was appended to
the evidence log, because nothing was viewed.

**Read.** `EXP002_FREEZE_PROPOSAL.md` (§3 rows 1–16, §4, §5); `EXP002_GATE_V3.md`; `EXP002_GATE_V3_VALIDATION.md`;
`EXP002_E1_ENDPOINT.md`; `src/edge_lab/sports_evidence.py` (the E1 section: `_e1_side`, `e1_entries`,
`e1_bounds_problem`, `_e1_exit`, `_e1_settlement`, `_wild_cluster_bounds`, `e1_endpoint`; also
`tie_adjusted_interval`, `kalshi_catalog`, `measure_exp002`, `record_markout_view`, `_main_exp002`);
`RESEARCH_UNBLOCKING_DECISIONS.md` A.A–A.I; `EXP002_TIE_NOTPLAYED_BOUNDS.md`; `EXP002_AC_CALIBRATION_TOOL.md`;
`experiments/EXP-002-nfl-consensus-vs-event-market/protocol.toml`; `docs/RESEARCH_PRINCIPLES.md`.

## 1. Overall verdict

**E1 is acceptable as EXP-002's primary endpoint, WITH CHANGES.** It should be framed and frozen as a **gross
information-transfer screen under FIRST_DETECTION_ZERO_LATENCY**, which is necessary but not sufficient for any
economic claim. The v1 specification is not freezable as written, for four reasons:

1. **The inference method is anti-conservative at the cluster counts EXP-002 will have.** The implemented
   unrestricted Rademacher wild cluster bootstrap with basic bounds over-rejects a true null. In §3.2's simulation
   it rejects about 12–18% of the time at a nominal 10% with 4–8 week clusters (11.5–13% with 12), and 6.6–13% at a
   nominal 5% (6.8–7.9% with 12). The fix is cheap and stays within A.G's "wild cluster bootstrap" family: impose the null and
   studentize (an exact enumerated sign-flip test), and invert the same test for the futility bound (C1).
2. **The efficacy significance level is not stated.** Row 4 names only "a one-sided 90% bound for futility".
   A.G's power planning used one-sided α = 0.05. The confirmatory level must be written down before any label is
   seen (C2).
3. **The settlement fallback for missing exits can dominate the variance.** Each fallback trade carries a
   binary-payoff SD of about 40–50¢ against about 3¢ for a bid exit. A 3% fallback share nearly triples the SD, and
   the test then has little power at δ_min = 1¢ (§4.4). A synthetic exit on the other team's market should come
   before the settlement fallback (C4), and the fallback share must be reported and flagged (C5).
4. **The variant budget conflicts with the A.C calibration.** A.C step 4 and A.H count every timing window tried,
   and the A.C tool tries three. Read literally, that consumes "V0 plus at most 2 challengers" before any
   challenger is named (§6, C8).

With C1–C14 (§7), E1 answers a narrower question than the family hypothesis: "under zero-latency fills at
displayed quotes, did buying the Kalshi ask when the consensus's conservative value cleared it by θ earn a
positive gross round trip to the first T-60m bid?" A pass would be evidence of information transfer at executable
prices, not of an edge after costs, latency or size. A fail, or statistical futility, is informative for the
family.

## 2. Verdict per design element

| # | Element (source) | Verdict | Main reason | Changes |
|---|---|---|---|---|
| 1 | E1 replaces E0 as primary; E0 and its placebo become descriptive "not bias-bounded" secondaries (row 3, row 5(a)) | **ACCEPT** | Under W, mid noise cannot make E[bid₁ − ask₆] positive; beyond W the captured deviation is priced at displayed quotes. No logged result view precedes the design change; the possible, unconfirmed T-60m exposures are recorded with `influenced_tuning` false (§6). It fixes the E0 problem that gate v3 shows cannot be bounded. | — |
| 2 | Entry: T-6h information only, AT_OR_AFTER_ODDS sides, `c_low − ask ≥ θ`, ask depth ≥ 1, one side per game (row 3) | **ACCEPT_WITH_CHANGES** | Label-free and correctly fail-closed in code. The effective threshold is θ plus the bound haircut `p − c_low`, which varies with p and with u_max; it must be tabulated and frozen with the bounds, and the bounds frozen from the sourced count only. | C9, C10, C13 |
| 3 | θ = 1¢ (row 4) | **ACCEPT** | One tick; fixed before any label. Selection on the margin is part of the strategy, not a bias of the test (§4.1). θ = 2¢ as a *tested* challenger is not recommended (nested, correlated, costs power; §6). | C8 |
| 4 | Exit at the bid of the first T-60m book of the same market, displayed depth ≥ 1 (row 3) | **ACCEPT** | A real, pre-scheduled executable price with both half-spreads paid. Caveat: it is after the inactives list (about 90 min before kickoff), so the move variance is news-driven (§4.5), and a stale-high exit bid is optimistic under zero latency (§4.3). | C12 (diagnostic) |
| 5 | Missing exit scored at the settlement payoff; exit at 0 as sensitivity; never dropped (row 3) | **ACCEPT_WITH_CHANGES** | "Never dropped" is right. But the settlement payoff swaps a ~3¢-SD markout for a ~45¢-SD binary outcome and removes the exit half-spread for those trades. Put a synthetic exit (1 − the other team market's first T-60m ask) before settlement, and report and flag the settlement share. | C4, C5 |
| 6 | Unit: 1 contract, gross only (row 3) | **ACCEPT_WITH_CHANGES** | Adequate for a price-based screen. It says nothing about the 10-contract minimum (A.E) or capacity. Add label-free depth shares and a descriptive 10-contract walk. | C11 |
| 7 | H₀: E[gross] ≤ 0, one-sided, per-trade mean with game units (row 4) | **ACCEPT_WITH_CHANGES** | The right null for a screen. The confirmatory α is missing; state it (one-sided 0.05) and keep 90% only for futility. | C2 |
| 8 | Wild cluster bootstrap, Rademacher weights, NFL-week clusters, as implemented (unrestricted, non-studentized, basic bounds) (row 4, A.G; `_wild_cluster_bounds`) | **REJECT as the confirmatory test** (keep as a descriptive interval only) | Over-rejects at few clusters (§3). Basic vs percentile is immaterial (identical under enumeration). What matters is null imposition and studentization, and the 2^G granularity. | C1, C3 |
| 9 | One-sided 90% bound for statistical futility at the 2026-11-30 interim (rows 4, 15) | **ACCEPT_WITH_CHANGES** | A futility-only interim cannot inflate the efficacy error. The bound should be the inversion of the same restricted test, so that false-futility stays near 10% (§3). | C1, C6 |
| 10 | δ_min(E1) = 1¢ gross, power statement (row 11) | **ACCEPT_WITH_CHANGES** | Reasonable as the screen's statistical threshold, but it is below every economic break-even (about 1.25¢ for a hold-to-settlement strategy and 3.5¢ for the round trip at P = 0.5, fees UNVERIFIED). The power statement mixes α = 0.05 planning with a 90% test; restated in §5. | C6, C7 |
| 11 | Secondary endpoints (row 5) | **ACCEPT** | Descriptive only. Hold-to-settlement (5(b)) has an SE of about 50¢/√n, about 7¢ at 54 trades, so it can never be inferential here. | — |
| 12 | `min_independent_clusters` = max(8, …) (row 12) | **ACCEPT_WITH_CHANGES** | The floor of 8 is sensible. Also state that with an enumerated sign-flip test no rejection is possible below 5 weeks at α = 0.05, or below 6 weeks at the Holm-worst α = 0.05/3. | C3 |
| 13 | Variant budget: V0 + ≤ 2 challengers, Holm; the E0→E1 revision not counted (row 14) | **ACCEPT_WITH_CHANGES** | Not counting E0→E1 is justified (no data viewed). The A.C windows conflict with the budget as worded. Recommended: V0 as the only confirmatory test; challengers descriptive. | C8 |
| 14 | Futility rules (row 15) | **ACCEPT_WITH_CHANGES** | Operational rule fine. Statistical: use the inverted restricted test (C1). Economic: add a fee-dependent threshold once fees are verified (C7). | C6, C7 |
| 15 | Label safety of the results path (`exp002 --with-results`) | **ACCEPT_WITH_CHANGES** | Logged-before-shown works, but nothing stops a results run from reaching evaluation-window labels; the pilot look shows the mean, not only the SD; and the bounds are a free CLI input. | C9, C13, C14 |

## 3. Validity of the hypothesis test

### 3.1 What the code computes

`_wild_cluster_bounds` takes the per-trade gross values with their week labels, computes the trade-weighted mean
and each week's residual sum `S_g = Σ (y − ȳ)`, and forms the deviations `Σ w_g S_g / n` over every Rademacher sign
pattern (exact when G ≤ 12). The one-sided 90% lower bound is `ȳ − q90(deviations)` and the upper is
`ȳ − q10(deviations)`. This is the **unrestricted** wild cluster bootstrap (WCU) of the **non-studentized** mean.
Its variance is `Σ S_g² / n²`, the CR0 cluster-robust variance, which is biased downward with few clusters (roughly
by (G − 1)/G for equal clusters, more with unequal cluster sizes and a positive ICC).

**Basic vs percentile is not material.** With exact enumeration the deviation distribution is symmetric (every
pattern has its negation), so the basic and percentile bounds are identical, as `EXP002_E1_ENDPOINT.md` §2.11 says.
With sampled patterns (G > 12) they differ only by Monte Carlo noise. The material choices are (a) imposing the null
(restricted vs unrestricted), (b) studentizing, and (c) the granularity of 2^G patterns.

**Granularity.** With G weeks there are only 2^G patterns: 16 at G = 4 and 64 at G = 6. For the implemented WCU at
G = 4, the 90% lower bound is the mean less the second-largest of 16 deviations, and the 95% bound the mean less the
largest. For an exact sign-flip test the smallest attainable p-value is 1/2^G: 0.0625 at G = 4 (no rejection possible at
α = 0.05), 0.031 at G = 5 and 0.0156 at G = 6 (the first G at which the Holm-worst level 0.05/3 can reject, and only
with every week's sign positive).

### 3.2 Synthetic size check

**Correction (fact-check of PR #154).** The first version of this simulation (`exp002-e1-review-sim-v1`)
studentized the Webb columns (`WCR_t_webb`) with a fixed `Σ Y_g²`, which is valid only for Rademacher weights
(w² = 1). v2 computes `Σ (w_g·Y_g − n_g·m*)²` for every weight pattern. Only the `WCR_t_webb` columns change; every
other column is byte-identical, because the random stream is unchanged. The corrected numbers change the rule for
fewer than 6 clusters (C1).

Script and seeds in §8.1 (`exp002-e1-review-sim-v2`). Per-trade gross in cents; weeks G ∈ {4, 6, 8, 12}; trades per
week ~ Binomial(15, 0.30) conditioned on ≥ 1 (mean about 4.5, unequal sizes); a week effect with ICC ∈ {0, 0.05,
0.10, 0.20}; three idiosyncratic distributions with the true mean exactly 0:
- **normal**: N(0, 3¢);
- **skewed**: 90% N(0, 1.7¢) + 10% left-skewed news jumps (8¢ − Exp(mean 8¢)), SD 3¢;
- **fallback**: 97% N(0, 3¢) + 3% settlement-fallback trades, `100·(B − p)` with p ~ U(0.2, 0.8), B ~ Bernoulli(p).

The raw output (§8.1) gives, per cell, the **upper-tail rejection rate** (the efficacy false-positive rate;
nominal = α) and the **lower-tail rate**. Every method here is translation-equivariant, so the lower-tail rate at a
true mean of 0 equals the rate at which the futility rule "upper bound < δ_min" fires when the true effect is exactly
δ_min (nominal = α). Replications: 4,000 per cell at G = 12 (Monte Carlo SE about 0.5 points at 10%); 1,000 per cell at
G ≤ 8 (SE about 0.9 points), because those cells also run the Webb methods (999 sampled weight draws; at G = 4 all
1,296 patterns). The Webb columns are not run at G = 12. The tables below give, for each G and method, the range
over the four ICC values (and the distributions named).

**α = 0.10, upper tail (efficacy false positive), normal and fallback** (range over ICC 0–0.20, in %; nominal 10%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 14.3–18.0 | 12.0–14.2 | 15.1–18.4 | 5.7–8.0 | 5.7–8.0 | 5.7–8.0 | 10.5–13.1 | 8.3–10.5 |
| 6 | 13.4–15.2 | 11.2–13.1 | 13.3–15.3 | 8.2–10.1 | 8.3–10.5 | 8.0–9.9 | 8.8–10.6 | 8.0–10.6 |
| 8 | 11.7–16.1 | 9.6–13.4 | 12.1–15.9 | 8.4–10.4 | 7.9–10.7 | 8.0–10.3 | 8.1–10.8 | 8.1–10.4 |
| 12 | 11.5–13.0 | 10.4–11.8 | n/a | 9.3–10.5 | 9.4–10.8 | 9.3–10.6 | n/a | 9.5–10.6 |

**α = 0.10, upper tail, skewed** (range over ICC 0–0.20, in %; nominal 10%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 16.6–19.5 | 13.2–16.7 | 17.6–20.7 | 6.8–7.9 | 6.8–7.9 | 6.8–7.9 | 11.3–14.4 | 10.6–12.3 |
| 6 | 16.5–19.9 | 13.9–18.0 | 16.4–19.4 | 10.2–14.6 | 10.1–14.5 | 10.2–14.5 | 11.3–15.5 | 10.9–14.5 |
| 8 | 13.8–17.7 | 12.6–16.6 | 13.8–18.3 | 10.8–14.3 | 10.7–14.4 | 10.3–14.1 | 11.0–14.1 | 11.3–14.2 |
| 12 | 13.1–16.3 | 11.9–15.2 | n/a | 10.8–14.3 | 11.1–14.2 | 10.8–14.2 | n/a | 11.2–14.1 |

**α = 0.10, lower tail (false futility), all three distributions** (range over ICC 0–0.20, in %; nominal 10%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 13.2–17.1 | 9.6–13.5 | 13.9–17.9 | 3.3–7.2 | 3.3–7.2 | 3.3–7.2 | 8.2–12.1 | 6.3–10.6 |
| 6 | 10.7–17.6 | 9.1–14.4 | 10.6–17.0 | 6.5–10.7 | 7.0–10.2 | 6.4–10.4 | 7.2–11.4 | 6.7–11.3 |
| 8 | 10.2–14.8 | 8.8–12.8 | 10.6–14.6 | 7.1–10.8 | 7.3–10.4 | 6.9–10.4 | 7.8–10.7 | 7.2–10.8 |
| 12 | 8.8–13.2 | 7.8–12.0 | n/a | 6.9–10.7 | 6.8–10.5 | 6.9–10.5 | n/a | 7.0–10.5 |

**α = 0.05, upper tail (efficacy false positive), normal and fallback** (range over ICC 0–0.20, in %; nominal 5%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 10.7–13.4 | 8.2–10.6 | 12.3–14.7 | 0.0–0.0 | 0.0–0.0 | 0.0–0.0 | 4.9–6.5 | 2.8–5.5 |
| 6 | 8.5–11.1 | 6.6–9.6 | 8.4–10.6 | 3.8–6.1 | 4.1–6.1 | 3.7–5.7 | 4.2–6.7 | 2.4–6.4 |
| 8 | 6.6–9.1 | 5.2–7.4 | 6.5–9.1 | 3.6–5.9 | 3.0–5.7 | 3.6–5.9 | 3.7–6.3 | 2.3–5.3 |
| 12 | 6.8–7.9 | 6.0–7.2 | n/a | 4.5–5.5 | 4.5–5.5 | 4.5–5.4 | n/a | 3.8–5.4 |

**α = 0.05, upper tail, skewed** (range over ICC 0–0.20, in %; nominal 5%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 12.9–15.4 | 10.8–12.7 | 13.6–16.3 | 0.0–0.0 | 0.0–0.0 | 0.0–0.0 | 6.3–7.4 | 5.3–6.3 |
| 6 | 11.6–16.1 | 10.1–13.8 | 12.0–15.9 | 5.4–8.2 | 5.0–8.1 | 5.6–8.4 | 6.0–8.9 | 5.8–8.2 |
| 8 | 9.3–12.8 | 7.5–11.6 | 9.2–12.9 | 5.2–7.6 | 4.7–7.8 | 5.0–7.7 | 5.2–8.3 | 5.1–7.9 |
| 12 | 8.3–11.5 | 7.3–10.2 | n/a | 5.4–8.1 | 5.9–8.1 | 5.4–8.2 | n/a | 5.9–7.9 |

**α = 0.05, lower tail (false futility), all three distributions** (range over ICC 0–0.20, in %; nominal 5%)

| G | `WCU_rad` | `WCU_rad_cr1` | `WCU_webb` | `SF_sum` | `SF_mean` | `WCR_t_rad` | `WCR_t_webb` | `T_means` |
|---|---|---|---|---|---|---|---|---|
| 4 | 9.2–13.0 | 6.0–10.2 | 10.1–13.7 | 0.0–0.0 | 0.0–0.0 | 0.0–0.0 | 3.0–6.4 | 2.5–5.7 |
| 6 | 7.5–11.5 | 5.4–10.0 | 7.3–11.7 | 2.9–5.3 | 3.1–5.2 | 3.0–5.6 | 3.3–6.0 | 2.1–5.7 |
| 8 | 5.9–9.5 | 4.8–8.1 | 5.6–9.2 | 3.1–5.1 | 3.0–5.1 | 3.1–5.3 | 3.6–5.7 | 2.7–5.3 |
| 12 | 3.9–8.0 | 3.2–7.2 | n/a | 2.4–5.4 | 2.6–5.3 | 2.4–5.5 | n/a | 2.2–5.1 |

**Methods.**
- `WCU_rad`: as implemented. `WCU_rad_cr1`: the same with deviations scaled by √(G/(G − 1)). `WCU_webb`: unrestricted
  with Webb six-point weights (±√½, ±1, ±√(3/2)).
- `SF_sum`: the exact restricted sign-flip test of the week totals (Rademacher, null imposed, trade-weighted).
- `SF_mean`: the exact sign-flip test of equal-weighted week means. Because every Rademacher weight squares to 1, the
  studentized statistic of week means is a monotone function of their sum, so this *is* the studentized
  randomization test of Canay, Romano and Shaikh (2017) for a mean.
- `WCR_t_rad`: restricted, studentized (cluster-robust t of the trade-weighted mean), Rademacher, enumerated.
  `WCR_t_webb`: the same with Webb weights.
- `T_means`: Student t on the G week means with G − 1 df (Ibragimov and Müller 2010).

**Reading (SYNTHETIC; under the stated assumptions only).**
- **The implemented method over-rejects a true null.** `WCU_rad` rejects 14–18% of the time at a nominal 10% with 4
  weeks, 13–15% with 6, 12–16% with 8 and 11.5–13% with 12 (normal and fallback rows). At a nominal 5% it rejects
  11–13%, 8.5–11%, 6.6–9.1% and 6.8–7.9%. The futility direction is as bad: the rule "upper 90% bound < δ_min" fires
  13–17% of the time at 4 weeks and 11–18% at 6 weeks when the true effect equals δ_min.
- **The √(G/(G − 1)) small-sample scaling helps only partly** (`WCU_rad_cr1`: 12–14% at 4 weeks, 10–13% at 8).
- **Webb weights do not fix it.** `WCU_webb` ≈ `WCU_rad` in every row. The defect is the unrestricted resampling
  (the null is not imposed, so the bootstrap variance is the downward-biased CR0 variance), not the weight
  distribution.
- **Imposing the null fixes it.** The three restricted Rademacher tests (`SF_sum`, `SF_mean`, `WCR_t_rad`) reject
  7.9–10.8% of the time at a nominal 10% and 3.0–6.1% at 5% for G ≥ 6 in the normal and fallback rows; they are almost
  indistinguishable from one another. At G = 4 they are conservative (5.7–8% at 10%) and cannot reject at 5% at all
  (2^4 = 16 patterns).
- **Below 6 clusters, correctly studentized Webb weights over-reject.** At G = 4, `WCR_t_webb` rejects 10.5–13.1% at
  a nominal 10% and 4.9–6.5% at 5% (normal and fallback; 11.3–14.4% and 6.3–7.4% skewed), and its false-futility
  rate is 8.2–12.1% at 10%. At G ≥ 6 it is close to the Rademacher tests (8.1–10.8% at 10%) and adds nothing.
- **The t on week means is the only method near nominal at G = 4.** `T_means` rejects 8.3–10.5% at a nominal 10% and
  2.8–5.5% at 5% (normal and fallback; 10.6–12.3% and 5.3–6.3% skewed), and its false-futility rate is 6.3–10.6% at
  10%. It tests the week-weighted mean, not the trade-weighted one.
- **Skewness is a residual risk for every method.** With left-skewed per-trade P&L (10% news jumps), all methods
  over-reject the upper tail: 10–15% at a nominal 10% and 5–8% at 5% for G ≥ 6. The restricted tests are 2–5 points
  better than the implemented one, but none reaches nominal. Exact sign-flip validity needs week contributions that
  are symmetric under H₀, and a 10% news-jump tail breaks that at about 4–5 trades a week. The pilot should report
  the skewness of the E1 P&L; α = 0.05 then carries an actual size of up to about 8% under strong left skew.
- **Recommendation.** Use the restricted, studentized test (`WCR_t_rad`: the trade-weighted estimand the code
  already reports), enumerated, for G ≥ 6. Do not use Webb weights at any G: they add nothing at G ≥ 6 once the null
  is imposed, and over-reject at G = 4. Below 6 clusters no reliable *confirmatory* inference exists here, and C3's
  floor of 8 excludes it. Only the interim futility bound can meet G < 6, and for it the inverted t on week means is
  the best-calibrated option in this simulation (C1).

### 3.3 Other test-validity points

- **The game unit and week clusters: ACCEPT.** One statistic per traded game, at most one side, clustered by the
  Tuesday-anchored ET week (`week_cluster`). Games in one week share news, weather and market-wide flows, and
  within-slot T-60m captures share a capture tick. Clustering by week is the coarsest defensible level; a game-level
  (independent) analysis is not a substitute.
- **Weeks with no trade** contribute no cluster. G for every rule means weeks with at least one scored trade; it
  should be reported beside the calendar weeks.
- **Trade-weighted vs week-weighted mean.** The per-trade mean (as coded) is the natural estimand for a strategy.
  `SF_mean` tests the week-weighted mean instead; under H₀ both are 0, and they differ only if the effect varies
  with the week's trade count. C1 keeps the trade-weighted estimand.
- **Symmetry.** Exact sign-flip validity needs week contributions that are symmetric about 0 under H₀. Skewed
  per-trade P&L makes this approximate; the skewed and fallback rows of §3.2 measure how much that matters here.
- **The interim.** One futility-only interim (2026-11-30) does not inflate the efficacy false-positive rate. It
  should be declared **non-binding** so that a borderline futility result does not force a stop the owner does not
  want, and so that the final test keeps its nominal level either way.

## 4. Bias sources

The bias illustrations use `exp002-e1-review-bias-v1` (§8.2): 200,000 synthetic games per row; latent value
V6 ~ U(25¢, 75¢); a martingale move to T-60m of N(0, 3¢); 1-tick Kalshi books around the market maker's fair value;
a consensus `c = V6 + N(0, gap SD)`; entries by row 3's rule with `tie_adjusted_interval`'s `c_low`.

Mean and SD in cents per contract; the trade rate is per team side (a game has two). Every row is under a stated
synthetic world, not an estimate of the real market. The hold-to-settlement column is a binary payoff with an SE of
about 0.4¢ at these trade counts, so its row-to-row differences are noise.

| scenario | trade rate (one side) | mean entry margin c_low-ask | mean E1 gross | SD gross | mean hold-to-settle | fallback share |
|---|---|---|---|---|---|---|
| NULL, W holds, gap SD 1.5, u=0.01 | 8.8% | +1.69 | -0.96 (se 0.02) | 3.0 | -0.74 | 0.0% |
| NULL, W holds, gap SD 1.5, u=0.005 | 11.6% | +1.74 | -0.94 (se 0.02) | 3.0 | -0.55 | 0.0% |
| NULL, W holds, gap SD 3, u=0.01 | 24.4% | +2.77 | -0.97 (se 0.01) | 3.0 | -0.53 | 0.0% |
| NULL, W holds, gap SD 3, u=0.005 | 27.2% | +2.85 | -0.97 (se 0.01) | 3.0 | -0.58 | 0.0% |
| STALE 35% (beyond W), zero latency | 15.1% | +2.54 | +1.08 (se 0.02) | 3.7 | +1.52 | 0.0% |
| STALE 35%, half the stale favourable asks picked off | 10.5% | +2.31 | +0.56 (se 0.03) | 3.7 | +0.75 | 0.0% |
| INFO (consensus knows 30% of the move) | 12.1% | +1.87 | +1.58 (se 0.02) | 2.7 | +1.83 | 0.0% |
| NULL + 3% random missing exits | 8.8% | +1.69 | -0.87 (se 0.06) | 8.6 | -0.74 | 2.8% |
| NULL + 10% random missing exits | 8.8% | +1.69 | -1.06 (se 0.11) | 15.0 | -0.74 | 9.3% |
| NULL + informative missing exits (20% if abs(move)>6c) | 8.8% | +1.69 | -0.98 (se 0.05) | 7.0 | -0.74 | 1.7% |
| INFO + informative missing exits | 12.1% | +1.87 | +1.52 (se 0.05) | 8.3 | +1.83 | 2.8% |
| NULL + sticky-down exit bids (50% of falls unpriced) | 8.8% | +1.70 | -0.36 (se 0.02) | 2.5 | -0.46 | 0.0% |
| NULL + sticky-down exit bids (20% of falls unpriced) | 8.8% | +1.70 | -0.70 (se 0.02) | 2.8 | -0.46 | 0.0% |

### 4.1 Selection on the consensus–ask margin (winner's curse, regression to the mean)

- **Not a bias of the test.** E1 scores realized quotes, not the consensus. Selecting trades on a noisy margin
  selects noisy consensus values, but the P&L is measured at the market's own later bid, so its mean is an unbiased
  estimate of the rule's gross EV under the fill assumption. In the null rows the mean E1 gross is −0.96¢, one full
  spread, as W implies.
- **It is a bias of any margin-based reading.** In the same null rows the mean entry margin `c_low − ask` is
  +1.7¢ to +2.8¢. That number is pure winner's curse. **The entry margin must never be reported as an edge, an
  expected value or an episode size.** Only realized P&L counts (C12 wording).
- **Consensus bias is a power problem, not a false-positive problem.** If the proportional de-vig overstates
  longshots relative to Kalshi (a favourite–longshot bias; UNVERIFIED for odds-consensus-v1), E1 systematically buys
  longshots at no real edge. That lowers the mean
  and wastes trades; it cannot manufacture a positive mean, because P&L is priced by Kalshi, not by the consensus.

### 4.2 Is the spread cost fully captured?

- **Entry at the ask and exit at the bid**: both half-spreads are paid on every bid-exit trade (the null mean of
  −0.96¢ equals one 1¢ spread). Yes, for those trades.
- **Settlement-fallback trades skip the exit half-spread** and are marked to the payoff, whose conditional mean is
  the value, not the bid. Relative to a true round trip, this tilts the mean up by about (fallback share) × (exit
  half-spread): 0.015¢ at a 3% share and a 1¢ spread. Small, but in the wrong direction; C4 removes most of it.
- **Fees are excluded by design** (FEE_UNSUPPORTED). The gross test is not an after-cost result, and
  RESEARCH_PRINCIPLES says an edge that exists only before costs is not an edge. See §5.
- **Size is excluded** (1 contract). The A.E minimum meaningful quantity is 10 contracts; the walk up the ladder can
  cost more than one tick (C11).

### 4.3 Stale or sticky quotes (beyond W)

- **At entry.** A stale ask below the value is what E1 is designed to catch, and under FIRST_DETECTION_ZERO_LATENCY
  that is "the hypothesis, not a bias" (row 3). The skeptic's point: those are exactly the quotes that faster
  traders or the quoting market maker remove first. In the STALE row (35% of T-6h quotes centred on an old value)
  E1 shows **+1.08¢** with zero latency. If half of those favourable stale asks are gone before a real order, the
  same world shows **+0.56¢**. So a positive E1 result is an upper bound for any real latency, and the gap can be
  about half the effect. Nothing in one snapshot per horizon measures this (gate v3 §2, items 2–3).
- **At exit.** A bid that has not followed a fall ("sticky-down") is an optimistic exit for a long-only rule, and
  also unlikely to be fillable. In the null world, if 50% of falls leave the T-60m bid at its old level, the null
  mean moves from −0.96¢ to **−0.36¢**; at 20%, to −0.70¢. It did not turn positive here, but it erodes the
  one-spread margin the null carries, and combined with a small real effect it inflates it. It is not identifiable
  label-free.
- **Mitigation (C12, descriptive, pre-registered):** report (a) a crude latency haircut, the E1 mean less one tick;
  (b) a single-book anomaly flag at entry, label-free: whether the other team market's same-capture book agrees
  that the entered side is cheap (`1 − bid_other ≤ c_low − θ`), splitting E1 P&L by the flag in the results only;
  (c) at exit, the share of trades where the own bid exceeds `1 − ask_other` of the same T-60m capture
  (a cross-market inconsistency that marks a stale exit).

### 4.4 The settlement fallback for missing exits

- **What it changes.** A bid-exit trade measures a 5-hour markout (SD about 3–4¢). A fallback trade measures
  hold-to-settlement (SD about 40–50¢). The primary becomes a mixture of two estimands whose weights are set by
  capture failures and thin books.
- **Variance.** In §8.2, 3% of random missing exits raise the SD from 3.0¢ to **8.6¢**; 10% raise it to **15.0¢**. The
  required sample grows with the variance: 3% fallback needs about 8 times the trades for the same power.
- **Informative missingness.** A book with no bid after bad news is not missing at random. Under the martingale
  null, scoring it at the payoff remains unbiased (E[payoff | T-60m information] = V1), which is why the fallback is
  better than dropping (survivorship) or exiting at 0 (a large negative bias). In §8.2 informative missingness
  (20% missing when the move exceeds 6¢) leaves the null mean at −0.98¢ but raises the SD to 7.0¢.
- **Exit at 0.** As a worst case it is correct but uninformative: each such trade scores about −50¢.
- **Recommendation (C4, C5).** Before the settlement payoff, exit synthetically on the other team market: buying
  the away YES at its first T-60m ask locks `home YES + away YES = $1` in a win, a loss and a tie ($0.50 + $0.50),
  so the exit value is `1 − ask_away,1` with a residual only in fallback-F states, which u_max bounds. It is an
  executable displayed quote of the same capture, priced like the primary. Only when neither market has a usable
  quote does the settlement payoff apply. Report the share of each exit basis. If the settlement share of scored
  trades exceeds a pre-registered 5%, the result carries the flag `SETTLEMENT_VARIANCE_DOMINANT` (a flag, not an
  endpoint switch). Caveat: a missing own book caused by a failed capture run often means the other book is missing
  too, so C4 mainly helps the NO_BID and BID_DEPTH cases.

### 4.5 The T-60m exit and information arrival

- NFL inactive lists are due about 90 minutes before kickoff (secondary knowledge; UNVERIFIED here). T-60m is after
  them, so the T-6h → T-60m move includes the day's biggest scheduled news. That makes the markout variance
  news-driven: A.G's SD range 6–8¢ ("inactive/injury-news repricing") is plausible, not only 2–4¢.
- News arrival is not a bias under the martingale null. It is the mechanism the hypothesis needs (the consensus may
  have priced early injury news that Kalshi had not). But it produces heavy tails and week-level common shocks
  (late-season weather, a slate-wide news pattern), which is exactly where few-cluster inference is weakest (§3.2,
  skewed rows).
- A T-10m exit (A.A alternative 2) would capture more repricing but needs a capture change and a new approval. Not
  recommended now.

### 4.6 One contract as the unit

A 1-contract P&L is a price statistic. It is a fair unit for a gross screen because displayed depth ≥ 1 is almost
never binding at 1¢ spreads. It cannot speak to the $1,000 bar, which needs 100–250 contracts per trade (§5). C11
adds the label-free share of entries with displayed ask depth ≥ 10 and ≥ 250, and a descriptive 10-contract E1 on
the ladder (entries and exits walked; NOT_EVALUATED where a fractional level is crossed, ADR 0036).

### 4.7 The entry rule's use of `c_low` (u_max 0.005 → 0.01 after #138)

- `c_low = p(1 − u)` for p ≤ 0.5 and `p − t(p − 0.5) − u·p` for p > 0.5 (`EXP002_TIE_NOTPLAYED_BOUNDS.md` §1). The
  effective entry threshold over the consensus is therefore θ + (p − c_low):

  | p | t = 0.01, u = 0.005 | t = 0.01, u = 0.01 |
  |---|---|---|
  | 0.30 | 1.15¢ | 1.30¢ |
  | 0.50 | 1.25¢ | 1.50¢ |
  | 0.70 | 1.55¢ | 1.90¢ |

  measured from the consensus to the ask, which with 1¢ spreads is 0.5¢ above the mid.
- Using the conservative corner is a strategy choice that cannot bias the test (P&L is priced by Kalshi), but it
  cuts the trade rate. In §8.2's null world, moving u_max from 0.005 to 0.01 cuts the one-side trade rate from 11.6%
  to 8.8% (**−24%**) at a gap SD of 1.5¢, and from 27.2% to 24.4% (−10%) at 3¢. #138 says the lost band is "under
  half a tick wide"; that is true of the band, but when gaps are small it holds a quarter of the trades.
- **Label-safety of the bound choice.** #138's u_max = 0.01 rests on 2017–2025 counts; the 2026 aggregate it read
  (eu-622b393f) contributed 0 events in 48 games, so it could only have argued for a smaller bound. The risk that
  pilot outcomes moved the bound is therefore low. But the bound is also a free CLI input (`--e1-tie-bound`,
  `--e1-postponement-bound`), and #138 §5 suggests a label-free entry count under both values. **That count must not
  choose the bound** (C10): the bound is frozen from the sourced count alone, and if an entry count is ever used to
  choose, the choice counts as a tried variant.

## 5. Power and economic framing

**Analytic minimum detectable effect** (normal approximation; power 0.80; 12 weeks × 15 games × 30% trade rate =
54 trades, about 4.5 a week; design effect 1 + 3.5·ICC):

| per-trade SD | ICC | MDE, one-sided α = 0.10 | α = 0.05 | α = 0.05/3 (Holm worst case) |
|---|---|---|---|---|
| 3¢ | 0 / 0.10 | 0.87 / 1.01¢ | 1.02 / 1.18¢ | 1.21 / 1.41¢ |
| 4¢ | 0 / 0.10 | 1.16 / 1.34¢ | 1.35 / 1.57¢ | 1.62 / 1.88¢ |
| 6¢ (news-driven) | 0 / 0.10 | 1.73 / 2.01¢ | 2.03 / 2.36¢ | 2.42 / 2.82¢ |
| 8.6¢ (3¢ + 3% fallback) | 0 / 0.10 | 2.48 / 2.89¢ | 2.91 / 3.38¢ | 3.48 / 4.04¢ |

A t reference with 11 df instead of z adds about 5–10%. This table assumes trades on 30% of all 15 weekly games.
Row 11 instead scales A.G's 9-games-a-week MDE by 1/√0.3, which is 30% of the *eligible* games, about 2.7 trades a
week; at that rate every MDE above rises by a further √(4.5/2.7) ≈ 1.29. Either way, at α = 0.05 the realistic
range is about 1.0–1.6¢ at SD 3–4¢ (1.3–2.0¢ at 2.7 trades a week), and 2–3.4¢ or more once the SD is news-driven or
fallback-inflated. **δ_min = 1¢ is powered only if the E1 SD is at most about 3¢, the trade rate is near 30% of all
games and settlement fallbacks are near zero.** The simulated power at a
true 1¢ effect (§8.1) is:

Cells: rejection % at one-sided α = 0.10 / 0.05 / 0.05/3 (Holm worst case). ICC 0.05; about 4.5 trades a week;
2,000 replications (Monte Carlo SE about 1 point). SDs are shown in ¢ here; the raw output in §8.1 prints `c`.
`WCU_rad` is shown only for comparison: its higher numbers come
from its over-rejection under the null.

| G | distribution | base SD | WCU_rad | SF_sum | SF_mean | WCR_t_rad | T_means |
|---|---|---|---|---|---|---|---|
| 6 | normal | 3¢ | 65 / 56 / 49 | 53 / 35 / 15 | 51 / 35 / 15 | 53 / 35 / 15 | 54 / 37 / 17 |
| 6 | normal | 4¢ | 50 / 42 / 35 | 39 / 23 / 9 | 38 / 23 / 9 | 39 / 23 / 9 | 40 / 24 / 10 |
| 6 | 3¢ + 3% fallback | 3¢ | 47 / 39 / 33 | 37 / 26 / 11 | 37 / 25 / 11 | 37 / 25 / 11 | 36 / 21 / 8 |
| 12 | normal | 3¢ | 83 / 75 / 62 | 80 / 66 / 43 | 76 / 63 / 41 | 80 / 65 / 42 | 77 / 63 / 41 |
| 12 | normal | 4¢ | 65 / 54 / 42 | 61 / 46 / 26 | 58 / 43 / 25 | 61 / 45 / 25 | 58 / 43 / 25 |
| 12 | 3¢ + 3% fallback | 3¢ | 47 / 40 / 32 | 44 / 35 / 23 | 46 / 35 / 22 | 44 / 35 / 23 | 45 / 31 / 15 |

At the full 12 weeks and α = 0.05 the valid tests have about **65% power at SD 3¢, 45% at SD 4¢ and 35% with a 3%
settlement-fallback share**, below the 80% the MDE table assumes (the normal approximation ignores the few-cluster
penalty). At the 6-week interim power is 23–35%, which is why the interim must be futility-only.

**δ_min against costs (fees UNVERIFIED; general formula `0.07·P(1 − P)` per contract per taker leg: 1.12¢ at
P = 0.2, 1.47¢ at 0.3, 1.75¢ at 0.5).**
- A **round trip** (E1 as traded) needs gross ≥ two fee legs: about **3.5¢** at P = 0.5. The spreads are already
  inside the gross.
- A **hold-to-settlement** strategy pays one fee leg and no settlement fee. If Kalshi's T-60m value is unbiased for
  the payoff, E[hold gross] = E[E1 gross] + E[exit half-spread], so it needs E1 gross ≥ one leg − half a spread:
  about **1.25¢** at P = 0.5 with a 1¢ spread.
- So **δ_min = 1¢ is below every economic break-even**, before the $1,000 bar. A gross E1 test that rejects at 1¢
  is necessary for, not evidence of, a net edge. It should be frozen as a screen (C6), with an economic threshold
  δ_econ recorded as a formula now and a number once fees are verified (C7).

**Against the $1,000/year bar (factual, not a recommendation to spend).** At about 255 remaining games and a 30%
trade rate there are about 77 trades a season, so the bar needs about $13 net per trade:
- at 10 contracts that is $1.30 per contract, more than a contract can pay, so it is unreachable at the minimum
  size;
- at 100 contracts, 13¢ net per contract; at 250 contracts, about 5.2¢ net per contract, after fees of about
  1.75–3.5¢, at displayed depth that is unknown at those sizes.
- Those net figures are 2–10 times the gross effects this test can detect (about 1–3¢). The approved record already
  says the ladder scenarios are $1.70–$382.50 a season (§1 of the proposal).

The owner decides whether continuing is worth it. The factual inputs: E1's marginal cash cost is 0 (existing
capture), its cost is owner hours within the approved 6, and a gross pass cannot by itself establish the bar; only a
fail or futility can end the family's current form cheaply.

## 6. Multiplicity, variants and label safety

**Variant budget (row 14, A.H, A.C step 4).**
- **Not counting E0 → E1 is justified.** The EXP-002 evidence log holds no label view that could have informed it:
  the six possible-exposure events (eu-7f8e6128, eu-f4954194, eu-4defeb1a, eu-9a3aeaf3, eu-1b511255, eu-d9f8610f)
  are hand-recorded *possible* T-60m or post-cutoff exposures with `viewed_labels` null (UNKNOWN), `viewed_results`
  false and `influenced_tuning` false, and eu-622b393f is the aggregate settlement read of #138. None is a view of
  E1 or markout results. The log cannot prove that no one looked (its own header says so); it shows only that no
  declared look informed the change.
- **The conflict.** A.C step 4 and A.H say every tried timing limit counts, and the A.C tool tries three windows.
  Read literally, V0 + 2 challengers are used up before T-24h or θ = 2¢ is named.
- **Recommendation (C8).** A.C's window selection is label-free (timing and depth features, logged as
  FEATURE_INSPECTION): it cannot inflate the false-positive rate of an outcome test except through a correlation
  between those features and the T-60m P&L, which is second order. So: **disclose** the three windows as tried
  design choices, **exclude** them from the Holm family, and test **V0 only** confirmatorily. Report the T-24h
  decision and θ = 2¢ descriptively. Reasons: θ = 2¢ trades a subset of θ = 1¢'s trades, so Holm would be
  conservative and costly (the MDE rises about 20% at 3 hypotheses); T-24h is further from the close; and at 12
  weeks V0 alone is marginal (§5). If the owner prefers tested challengers, keep Holm and name both challengers
  before the pilot label look.

**Label safety.**
- **The logged results path is sufficient as a record, not as a barrier.** `exp002 --with-results` refuses without
  a log, actor and code version, records a LABEL_RESULT_INSPECTION (DEVELOPMENT) before printing, and shows nothing
  if the record fails. But:
  1. **Nothing caps a results run to pilot games.** `measure_exp002` reads every T-60m book and settlement received
     by `as_of`, and `as_of` defaults to now. A results run on or after the first evaluation-window T-60m capture
     would show evaluation labels, logged under role DEVELOPMENT, and the holdout would be CONTAMINATED
     (`research_evidence._use_state`). `exp002-timing` has a pilot-window cap; the results path does not. (C14)
  2. **The pilot look shows the mean, not only the SD.** The planned pilot look exists to estimate the SD for
     `min_independent_clusters`. It also prints `mean_gross`, bounds and per-game P&L, and E0's markout. Any design
     choice made after it (θ, bounds, challengers, exit rule) is then a data-informed choice. (C13)
  3. **The bounds are a free input.** Each `--with-results` run can declare different E1 bounds; two runs with
     different bounds are a bound search on labels. (C10, C13)
- **The A.C timing calibration** is label-free by construction and logged. Its drift rule uses δ_min/3, so δ_min
  must be frozen before the A.C run, not after it (C13). Note also that A.I expects T-6h repeat books to be rare, so
  the drift pairs may be empty and the rule may fall back to [−5, +10]; that fallback is pre-specified.
- **eu-622b393f** (#138's public aggregate read of 2026 weeks 1–3 settlements and standings) exposed pilot-game
  outcomes (DEVELOPMENT; those games are never in the evaluation window). It carries `influenced_tuning` false. That
  is plausible because the 2026 games contributed 0 ties and 0 fallback events, but it is self-declared. The
  freeze record should cite it and state that u_max came from the 2017–2025 count (C10).
- **Exposure closures.** Proposal v1 §4 cites only the #124 closure (2026-09-29T02:09:50Z). The later
  possible-exposure closures run to **2026-09-29T15:45:00Z** (eu-d9f8610f, the T-60m Odds consensus proxy). The
  evaluation window starts after the freeze in any case, so nothing changes in practice, but v2 should list all of
  them (C14).
- **Public outcomes.** NFL results are public the moment games end. For the settlement-based pieces (fallback
  payoffs, secondary 5(b)) "untouched" is procedural only. The primary's exit bids are not public in the same way.

## 7. Recommended changes for freeze proposal v2 (all PROPOSED)

- **C1 — Confirmatory test (PROPOSED).** Replace the row 4 method with an **exact restricted wild cluster
  (sign-flip) test**: Rademacher weights over NFL-week clusters with the null imposed, the statistic the
  cluster-robust t of the trade-weighted mean gross, and every one of the 2^G patterns enumerated (G ≤ 12; above
  that, 9,999 seeded draws). p = the share of patterns with t* ≥ t_obs, counting ties against rejection.
  At G ≥ 6 the enumerated Rademacher patterns are adequate (§3.2). **Below 6 clusters there is no confirmatory
  inference:** the efficacy test is not run (C3's floor is 8 in any case) and the result is INSUFFICIENT_EVIDENCE.
  If the non-binding interim futility bound (C6) meets G = 4 or 5, it uses the one-sided 90% upper bound of the
  **t on week means with G − 1 df** (false-futility rate 6.3–10.6% at G = 4 in §3.2; G = 5 was not simulated),
  flagged `COARSE_FEW_CLUSTERS`, and it may only support a futility recommendation to the owner, never an efficacy
  claim. Webb weights are not used: correctly studentized, they over-reject at G = 4 (§3.2). At G ≥ 6, confidence
  bounds are obtained by **inverting the same restricted test** (the lower bound is the smallest μ₀ not rejected for
  `y − μ₀`; the upper bound likewise). The current `_wild_cluster_bounds` output stays as a descriptive interval
  labelled "unrestricted, anti-conservative at few clusters". The t on week means with
  G − 1 df is a reported cross-check.
- **C2 — Efficacy level (PROPOSED).** The confirmatory test is one-sided at **α = 0.05** (A.G's planning level), at
  the final analysis only. The one-sided **90%** level is used only for the statistical futility bound.
- **C3 — Cluster floor (PROPOSED).** Keep `min_independent_clusters` = max(8, ⌈weeks at ICC 0.10⌉), counting only
  weeks with at least one scored trade. State in the freeze record that with 2^G patterns no rejection is possible
  below G = 5 at α = 0.05, and G = 6 at α = 0.05/3.
- **C4 — Exit order (PROPOSED).** Exit (i) at the own market's first T-60m bid with displayed depth ≥ 1; else
  (ii) synthetically at `1 − ask` of the other team market's first T-60m book in the same window, displayed depth
  ≥ 1; else (iii) at the settlement payoff. The exit-at-0 sensitivity stays. (ii) is exact in a win, a loss and a
  tie (tie payout per the VERIFIED terms; the `settlement_value_dollars` field reading is UNVERIFIED, §9.6), and
  differs only in fallback-F states (probability ≤ u_max). This is a change to a label-reading rule, made
  with no label viewed; it must be decided before the pilot label look or not at all.
- **C5 — Fallback reporting (PROPOSED).** Report the counts and shares of the three exit bases. If the settlement
  basis exceeds **5%** of scored trades, the result carries `SETTLEMENT_VARIANCE_DOMINANT`. The endpoint does not
  switch.
- **C6 — Framing and futility (PROPOSED).** Name the endpoint "E1 gross information-transfer screen (zero-latency
  displayed quotes)". δ_min(E1) = 1¢ stays as the statistical threshold of the screen. The interim (2026-11-30) is
  **futility-only and non-binding**: STATISTICAL_FUTILITY if the inverted-test one-sided 90% upper bound is below
  δ_min.
- **C7 — Economic threshold (PROPOSED; number BLOCKED by fees).** Record now:
  `δ_econ,hold(P) = fee_leg(P) − s₁/2` and `δ_econ,round-trip(P) = 2·fee_leg(P)`, with fee_leg from the verified
  KXNFLGAME schedule (FEE_UNSUPPORTED today; about 1.25¢ and 3.5¢ at P = 0.5 under the general formula). Once fees
  are verified, the ECONOMICALLY_UNVIABLE rule of row 15 compares the E1 upper bound with δ_econ,hold. No net claim
  is possible from a gross pass.
- **C8 — Variants (PROPOSED).** V0 is the only confirmatory test. The T-24h decision and θ = 2¢ are reported
  descriptively. The three A.C windows are disclosed as label-free design choices, outside the Holm family.
  (Alternative for the owner: keep Holm with both challengers named before the pilot label look.) Amend A.H's
  "every tried timing limit counts" to say "counts as tried and is disclosed; enters the Holm family only if it is
  tested on outcomes".
- **C9 — Effective threshold (PROPOSED).** The freeze record tabulates θ + (p − c_low) by p for the frozen bounds
  (§4.7), so the entry rule's real strictness is visible.
- **C10 — Bounds freeze (PROPOSED).** Freeze `t_max = 0.01`, `u_max = 0.01` (#138) from the sourced counts alone,
  before the A.C run and before any label look. The label-free entry count under 0.005 vs 0.01 is information, not a
  selector. Cite eu-622b393f and state that the 2026 data contributed 0 events.
- **C11 — Size descriptives (PROPOSED).** Label-free: the share of E1 entries with displayed ask depth ≥ 10 and ≥
  250 contracts. Results path, descriptive: E1 at 10 contracts on the ladder.
- **C12 — Execution diagnostics (PROPOSED, descriptive).** Report (a) the E1 mean less one tick; (b) the label-free
  single-book anomaly flag at entry and E1 P&L split by it; (c) the share of exits where the own bid exceeds
  `1 − ask_other` at the same capture. State in every output that the entry margin is not an edge estimate
  (winner's curse, §4.1).
- **C13 — Freeze order and the one pilot look (PROPOSED).** Before the pilot label look, freeze: θ, the bounds, the
  exit order (C4), the method and α (C1, C2), the variant list (C8) and δ_min (the A.C drift rule uses it). The
  pilot look (`exp002 --with-results`) is taken **once**, with an explicit `--as-of` before the first
  evaluation-window T-60m capture, and may set only nuisance quantities: the SD, the exit-basis shares, and hence
  `min_independent_clusters` and the power statement. Any other change after it counts as a tried variant and is
  disclosed.
- **C14 — Evaluation-window guard (PROPOSED; a later code PR, not this one).** Make `exp002 --with-results`
  refuse, as `exp002-timing` does, any run whose games reach the evaluation window, unless it is the single
  pre-registered final analysis logged as UNTOUCHED_EVALUATION. Until that exists, the procedural rule of C13 holds.
  v2 §4 should list every possible-exposure event with its closure time (latest 2026-09-29T15:45:00Z).

## 8. Synthetic simulations (seeded, stdlib only, reproducible)

Both scripts use only the Python standard library (run with Python 3.12.10, Windows). They read no file and no
database. They are reproduced here in full so that the review is self-contained; they are not committed as code.
To rerun, save each block to a file and run it with `python <file>`. **Reproducibility:** each block below is
byte-identical (sha256-checked) to the file that produced the stated output. For the first version, both blocks were
also extracted from this document and rerun, and each output's sha256 matched; the fact-check of PR #154 reproduced
them byte for byte as well.

### 8.1 `exp002-e1-review-sim-v2` (few-cluster size and power)

Command: `python e1_cluster_size_sim.py 4000 1000` (4,000 replications per cell at G = 12; 1,000 at G ≤ 8, where
the Webb columns also run; 2,000 per power cell). Master seed 20261022; each size cell's seed is
`20261022 + 1000·(G index) + 100·(ICC index) + 10·(distribution index)`, and each power cell's is
`20261022 + 77·G + SD`.
Script sha256
`dc5e2611869ff03ab3f316043f1c9bc9e46a5113e9a80ca671ed3e2f725c4d45`;
output sha256 `2f1d2d90d1fdd728fb1ae0f35015ea74e4a27a45c8c1b5292ae6b80eac7c132c` (7 min 56 s on the laptop).
v1 (superseded; Webb studentization bug) had script sha256 `f6613c68…` and output sha256 `4da55247…`.
The full output follows the code.

```python
"""E1 few-cluster inference check (exp002-e1-review-sim-v2). SYNTHETIC ONLY: no EXP-002 data.

Per-trade gross P&L in cents, clustered by NFL week. Under H0 the true mean is exactly 0.
Weeks G; trades per week n_g ~ Binomial(15, 0.30) conditioned on >= 1; week effect a_g with
ICC (of the base component); idiosyncratic draw from one of three distributions:
  normal   N(0, 3c)
  skewed   0.9 N(0, 1.7c) + 0.1 (8c - Exp(mean 8c))   (left-skewed news jumps; SD 3c)
  fallback 0.97 N(0, 3c) + 0.03 (B - p), p ~ U(0.2, 0.8), B ~ Bernoulli(p), in cents (settlement fallback)
Methods (one-sided, H0: mean <= 0; 'down' = H0': mean >= 0, the futility direction):
  WCU_rad    as implemented (_wild_cluster_bounds): unrestricted Rademacher, basic bounds, exact enumeration
  WCU_rad_cr1 the same, deviations scaled by sqrt(G/(G-1))
  WCU_webb   unrestricted, Webb 6-point weights, basic bounds
  SF_sum     exact sign-flip (restricted) test of the total, clusters weighted by size
  SF_mean    exact sign-flip test of the equal-weighted cluster means (== studentized, see doc)
  WCR_t_rad  restricted, studentized (cluster-robust t), Rademacher, exact enumeration
  WCR_t_webb restricted, studentized, Webb 6-point
  T_means    Student t on the G cluster means, G-1 df
Usage: python e1_cluster_size_sim.py [reps] [webb_reps]
"""
import math
import random
import sys

SEED = 20261022
WEBB = (-math.sqrt(1.5), -1.0, -math.sqrt(0.5), math.sqrt(0.5), 1.0, math.sqrt(1.5))
WEBB_B = 999


def t_cdf(x, df):
    """Student t CDF by Simpson integration of the density (stdlib only)."""
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    f = lambda u: c * (1 + u * u / df) ** (-(df + 1) / 2)
    n, a = 4000, 0.0
    h = (abs(x) - a) / n
    s = f(a) + f(abs(x)) + sum((4 if i % 2 else 2) * f(a + i * h) for i in range(1, n))
    area = s * h / 3
    return 0.5 + area if x >= 0 else 0.5 - area


def t_quantile(p, df):
    lo, hi = 0.0, 50.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_cdf(mid, df) < p else (lo, mid)
    return (lo + hi) / 2


def draw(rng, dist, sigma=3.0, f=0.03):
    if dist == "normal":
        return rng.gauss(0, sigma)
    if dist == "skewed":
        return 8.0 - rng.expovariate(1 / 8.0) if rng.random() < 0.1 else rng.gauss(0, 1.7)
    if rng.random() < f:  # fallback
        p = rng.uniform(0.2, 0.8)
        return 100.0 * ((1.0 if rng.random() < p else 0.0) - p)
    return rng.gauss(0, sigma)


def sample(rng, G, icc, dist, mu=0.0, sigma=3.0):
    out = []
    for _ in range(G):
        n = 0
        while n == 0:
            n = sum(rng.random() < 0.30 for _ in range(15))
        a = rng.gauss(0, sigma * math.sqrt(icc / (1 - icc))) if icc > 0 else 0.0
        out.append([mu + a + draw(rng, dist, sigma) for _ in range(n)])
    return out


def signsums(vals):
    out = [0.0]
    for v in vals:
        out = [o + v for o in out] + [o - v for o in out]
    return out


def signsums2(u, v):
    a, b = [0.0], [0.0]
    for x, y in zip(u, v):
        a, b = [o + x for o in a] + [o - x for o in a], [o + y for o in b] + [o - y for o in b]
    return a, b


def basic(devs, mean, alpha):
    devs = sorted(devs)
    N = len(devs)
    hi, lo = math.ceil((1 - alpha) * N) - 1, max(0, math.ceil(alpha * N) - 1)
    return mean - devs[hi] > 0, mean - devs[lo] < 0  # (reject up, reject down)


def pvals(stars, obs, eps=1e-9, plus_one=False):
    ge = sum(s >= obs - eps for s in stars)
    le = sum(s <= obs + eps for s in stars)
    N = len(stars)
    if plus_one:
        return (ge + 1) / (N + 1), (le + 1) / (N + 1)
    return ge / N, le / N


def webb_draws(rng, G):
    if 6 ** G <= 1296:
        pats = [[]]
        for _ in range(G):
            pats = [p + [w] for p in pats for w in WEBB]
        return pats, False
    return [[rng.choice(WEBB) for _ in range(G)] for _ in range(WEBB_B)], True


def decide(cl, alphas, tq, rng, webb=True):
    G = len(cl)
    ns = [len(c) for c in cl]
    n = sum(ns)
    Y = [sum(c) for c in cl]
    mean = sum(Y) / n
    S = [y - k * mean for y, k in zip(Y, ns)]
    m = [y / k for y, k in zip(Y, ns)]
    res = {}
    devs = [x / n for x in signsums(S)]
    cr1 = math.sqrt(G / (G - 1))
    sf_sum = signsums(Y)
    sf_mean = signsums(m)
    A, B = signsums2(Y, [k * y for k, y in zip(ns, Y)])
    sumY2, sumn2 = sum(y * y for y in Y), sum(k * k for k in ns)

    def tstat(a, b):
        ms = a / n
        v = sumY2 - 2 * ms * b + ms * ms * sumn2
        return ms / math.sqrt(max(v, 1e-18)) * n

    def tstat_w(w):  # general weights: the expansion used by tstat needs w_g**2 == 1 (Rademacher) and is not used
        ms = sum(x * y for x, y in zip(w, Y)) / n
        v = sum((x * y - k * ms) ** 2 for x, y, k in zip(w, Y, ns))
        return ms / math.sqrt(max(v, 1e-18)) * n

    t_obs = tstat(sum(Y), sum(k * y for k, y in zip(ns, Y)))
    t_star = [tstat(a, b) for a, b in zip(A, B)]
    p_sum = pvals(sf_sum, sum(Y))
    p_mean = pvals(sf_mean, sum(m))
    p_t = pvals(t_star, t_obs)
    mm = sum(m) / G
    sd = math.sqrt(sum((x - mm) ** 2 for x in m) / (G - 1))
    tt = mm / (sd / math.sqrt(G)) if sd > 0 else 0.0
    if webb:
        pats, sampled = webb_draws(rng, G)
        wdevs = [sum(w * s for w, s in zip(p, S)) / n for p in pats]
        wt = [tstat_w(p) for p in pats]
        p_wt = pvals(wt, t_obs, plus_one=sampled)
    for a in alphas:
        r = {}
        r["WCU_rad"] = basic(devs, mean, a)
        r["WCU_rad_cr1"] = basic([d * cr1 for d in devs], mean, a)
        r["SF_sum"] = (p_sum[0] <= a, p_sum[1] <= a)
        r["SF_mean"] = (p_mean[0] <= a, p_mean[1] <= a)
        r["WCR_t_rad"] = (p_t[0] <= a, p_t[1] <= a)
        r["T_means"] = (tt > tq[(G - 1, a)], tt < -tq[(G - 1, a)])
        if webb:
            r["WCU_webb"] = basic(wdevs, mean, a)
            r["WCR_t_webb"] = (p_wt[0] <= a, p_wt[1] <= a)
        res[a] = r
    return res


def run(G, icc, dist, mu, reps, alphas, tq, seed, webb):
    rng = random.Random(seed)
    tally = {}
    for _ in range(reps):
        for a, r in decide(sample(rng, G, icc, dist, mu), alphas, tq, rng, webb).items():
            for k, (up, down) in r.items():
                t = tally.setdefault((a, k), [0, 0])
                t[0] += up
                t[1] += down
    return {k: (u / reps, d / reps) for k, (u, d) in tally.items()}


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    webb_reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    alphas = (0.10, 0.05)
    tq = {(df, a): t_quantile(1 - a, df) for df in range(1, 13) for a in (0.10, 0.05, 0.05 / 3)}
    print(f"t quantiles: t(3,.90)={tq[(3, .1)]:.3f} t(11,.90)={tq[(11, .1)]:.3f} t(11,.95)={tq[(11, .05)]:.3f}")
    methods = ["WCU_rad", "WCU_rad_cr1", "WCU_webb", "SF_sum", "SF_mean", "WCR_t_rad", "WCR_t_webb", "T_means"]
    print("\nSIZE under H0 (true mean 0). Cell = upper-tail rejection % (efficacy false positive) / "
          "lower-tail % (false futility). Nominal = alpha.")
    for a in alphas:
        print(f"\n| alpha {a} | G | ICC | dist | " + " | ".join(methods) + " |")
        print("|---" * (len(methods) + 4) + "|")
        for gi, G in enumerate((4, 6, 8, 12)):
            for ii, icc in enumerate((0.0, 0.05, 0.10, 0.20)):
                for di, dist in enumerate(("normal", "skewed", "fallback")):
                    webb = G <= 8
                    seed = SEED + 1000 * gi + 100 * ii + 10 * di
                    key = (G, icc, dist)
                    if key not in CACHE:
                        CACHE[key] = run(G, icc, dist, 0.0, webb_reps if webb else reps,
                                         alphas, tq, seed, webb)
                    out = CACHE[key]
                    cells = []
                    for k in methods:
                        v = out.get((a, k))
                        cells.append("n/a" if v is None else f"{100 * v[0]:.1f} / {100 * v[1]:.1f}")
                    print(f"| | {G} | {icc:.2f} | {dist} | " + " | ".join(cells) + " |")
    print("\nPOWER at true mean 1c (upper-tail rejection %), ICC 0.05; alpha 0.10 / 0.05 / 0.05/3 (Holm worst case)")
    pm = ["WCU_rad", "SF_sum", "SF_mean", "WCR_t_rad", "T_means"]
    print("| G | dist | sigma | " + " | ".join(pm) + " |")
    print("|---" * (len(pm) + 3) + "|")
    for G in (6, 12):
        for dist, sigma in (("normal", 3.0), ("normal", 4.0), ("fallback", 3.0)):
            rng = random.Random(SEED + 77 * G + int(sigma))
            tally = {}
            for _ in range(reps // 2):
                cl = sample(rng, G, 0.05, dist, 1.0, sigma)
                for a, r in decide(cl, (0.10, 0.05, 0.05 / 3), tq, rng, webb=False).items():
                    for k, (up, _d) in r.items():
                        tally[(a, k)] = tally.get((a, k), 0) + up
            cells = [" / ".join(f"{100 * tally[(a, k)] / (reps // 2):.0f}" for a in (0.10, 0.05, 0.05 / 3)) for k in pm]
            print(f"| {G} | {dist} | {sigma:.0f}c | " + " | ".join(cells) + " |")


CACHE = {}
if __name__ == "__main__":
    main()
```

<details><summary>Full output of <code>python e1_cluster_size_sim.py 4000 1000</code></summary>

```
t quantiles: t(3,.90)=1.638 t(11,.90)=1.363 t(11,.95)=1.796

SIZE under H0 (true mean 0). Cell = upper-tail rejection % (efficacy false positive) / lower-tail % (false futility). Nominal = alpha.

| alpha 0.1 | G | ICC | dist | WCU_rad | WCU_rad_cr1 | WCU_webb | SF_sum | SF_mean | WCR_t_rad | WCR_t_webb | T_means |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | 4 | 0.00 | normal | 16.3 / 16.6 | 13.4 / 13.3 | 17.0 / 17.0 | 6.5 / 6.9 | 6.5 / 6.9 | 6.5 / 6.9 | 10.8 / 11.3 | 10.5 / 10.6 |
| | 4 | 0.00 | skewed | 19.5 / 13.6 | 16.2 / 11.1 | 20.7 / 14.8 | 7.9 / 5.1 | 7.9 / 5.1 | 7.9 / 5.1 | 13.8 / 10.4 | 12.2 / 8.0 |
| | 4 | 0.00 | fallback | 16.6 / 15.4 | 13.3 / 12.0 | 17.7 / 16.5 | 6.8 / 7.2 | 6.8 / 7.2 | 6.8 / 7.2 | 11.9 / 11.4 | 8.7 / 8.1 |
| | 4 | 0.05 | normal | 16.4 / 13.7 | 13.8 / 11.3 | 17.0 / 13.9 | 6.4 / 5.1 | 6.4 / 5.1 | 6.4 / 5.1 | 11.7 / 9.8 | 9.4 / 8.4 |
| | 4 | 0.05 | skewed | 19.4 / 13.2 | 15.9 / 9.6 | 19.7 / 13.9 | 7.1 / 3.3 | 7.1 / 3.3 | 7.1 / 3.3 | 13.6 / 8.2 | 12.3 / 6.3 |
| | 4 | 0.05 | fallback | 14.8 / 14.8 | 12.0 / 10.5 | 15.2 / 15.6 | 5.8 / 5.5 | 5.8 / 5.5 | 5.8 / 5.5 | 10.5 / 9.0 | 8.3 / 6.7 |
| | 4 | 0.10 | normal | 14.3 / 16.1 | 12.0 / 12.9 | 15.1 / 17.0 | 5.9 / 6.3 | 5.9 / 6.3 | 5.9 / 6.3 | 10.5 / 11.8 | 9.3 / 10.1 |
| | 4 | 0.10 | skewed | 18.5 / 14.2 | 16.7 / 11.7 | 19.0 / 15.5 | 7.9 / 5.8 | 7.9 / 5.8 | 7.9 / 5.8 | 14.4 / 10.6 | 12.0 / 8.1 |
| | 4 | 0.10 | fallback | 18.0 / 14.8 | 13.9 / 11.4 | 18.4 / 15.5 | 8.0 / 5.6 | 8.0 / 5.6 | 8.0 / 5.6 | 13.1 / 9.8 | 10.1 / 7.8 |
| | 4 | 0.20 | normal | 16.4 / 15.3 | 14.2 / 12.9 | 16.6 / 16.2 | 5.7 / 5.1 | 5.7 / 5.1 | 5.7 / 5.1 | 11.6 / 10.7 | 9.5 / 8.7 |
| | 4 | 0.20 | skewed | 16.6 / 16.1 | 13.2 / 12.5 | 17.6 / 16.8 | 6.8 / 5.7 | 6.8 / 5.7 | 6.8 / 5.7 | 11.3 / 10.7 | 10.6 / 9.1 |
| | 4 | 0.20 | fallback | 16.1 / 17.1 | 12.9 / 13.5 | 17.1 / 17.9 | 7.3 / 6.6 | 7.3 / 6.6 | 7.3 / 6.6 | 12.1 / 12.1 | 9.2 / 9.8 |
| | 6 | 0.00 | normal | 14.9 / 14.1 | 13.1 / 12.1 | 14.7 / 14.2 | 10.1 / 9.0 | 9.5 / 9.5 | 9.8 / 9.3 | 10.6 / 9.9 | 10.1 / 10.2 |
| | 6 | 0.00 | skewed | 19.9 / 10.7 | 18.0 / 9.1 | 19.4 / 10.6 | 14.6 / 6.5 | 14.5 / 7.0 | 14.5 / 6.4 | 15.5 / 7.2 | 14.5 / 6.7 |
| | 6 | 0.00 | fallback | 14.1 / 15.1 | 11.2 / 12.2 | 14.3 / 15.1 | 8.7 / 8.3 | 8.5 / 8.0 | 8.0 / 8.4 | 9.0 / 10.5 | 8.8 / 7.2 |
| | 6 | 0.05 | normal | 13.4 / 13.5 | 12.2 / 11.5 | 13.3 / 13.4 | 9.5 / 8.2 | 9.2 / 8.8 | 9.3 / 7.7 | 9.9 / 8.4 | 9.2 / 9.3 |
| | 6 | 0.05 | skewed | 17.9 / 13.1 | 15.5 / 10.4 | 17.8 / 13.1 | 11.6 / 8.0 | 11.6 / 7.8 | 11.5 / 8.1 | 12.5 / 8.4 | 10.9 / 8.1 |
| | 6 | 0.05 | fallback | 15.2 / 14.7 | 12.6 / 12.2 | 14.9 / 14.9 | 9.6 / 9.0 | 9.0 / 8.3 | 9.9 / 9.0 | 10.1 / 9.6 | 9.3 / 7.8 |
| | 6 | 0.10 | normal | 15.2 / 17.6 | 13.1 / 14.4 | 15.3 / 17.0 | 9.8 / 9.9 | 10.5 / 10.1 | 9.3 / 10.1 | 10.1 / 10.9 | 10.6 / 10.5 |
| | 6 | 0.10 | skewed | 19.3 / 14.1 | 16.8 / 11.5 | 19.1 / 14.1 | 11.9 / 8.8 | 12.0 / 8.7 | 12.4 / 8.5 | 13.2 / 9.5 | 12.7 / 9.7 |
| | 6 | 0.10 | fallback | 14.4 / 13.5 | 12.3 / 11.9 | 14.4 / 13.9 | 9.3 / 8.4 | 8.7 / 8.4 | 9.5 / 8.4 | 10.2 / 9.1 | 8.2 / 7.6 |
| | 6 | 0.20 | normal | 13.6 / 16.3 | 11.9 / 13.8 | 13.8 / 16.2 | 8.2 / 10.7 | 8.3 / 10.2 | 8.0 / 10.4 | 8.8 / 11.4 | 9.3 / 11.3 |
| | 6 | 0.20 | skewed | 16.5 / 12.7 | 13.9 / 10.6 | 16.4 / 12.5 | 10.2 / 7.7 | 10.1 / 8.4 | 10.2 / 7.7 | 11.3 / 8.6 | 11.1 / 8.3 |
| | 6 | 0.20 | fallback | 14.1 / 15.1 | 11.7 / 12.3 | 14.0 / 15.2 | 8.3 / 10.7 | 8.3 / 9.7 | 8.2 / 10.4 | 9.5 / 11.3 | 8.0 / 9.3 |
| | 8 | 0.00 | normal | 12.7 / 11.9 | 11.5 / 10.4 | 12.8 / 11.9 | 9.8 / 9.0 | 8.8 / 9.2 | 10.0 / 9.2 | 10.2 / 9.4 | 9.1 / 9.6 |
| | 8 | 0.00 | skewed | 17.7 / 10.2 | 16.6 / 8.8 | 18.3 / 10.6 | 14.3 / 7.1 | 14.4 / 7.3 | 14.1 / 6.9 | 14.1 / 8.0 | 14.2 / 7.2 |
| | 8 | 0.00 | fallback | 12.7 / 12.6 | 11.8 / 10.9 | 12.9 / 12.7 | 10.2 / 9.1 | 10.2 / 8.4 | 10.2 / 9.0 | 10.2 / 9.8 | 9.4 / 8.2 |
| | 8 | 0.05 | normal | 12.1 / 11.8 | 11.0 / 10.2 | 12.2 / 12.2 | 9.1 / 8.9 | 8.8 / 8.5 | 9.8 / 8.9 | 9.6 / 9.1 | 9.2 / 8.7 |
| | 8 | 0.05 | skewed | 16.8 / 11.1 | 14.9 / 9.2 | 17.0 / 11.6 | 13.0 / 7.4 | 13.5 / 8.5 | 13.0 / 7.4 | 13.3 / 7.8 | 13.7 / 8.5 |
| | 8 | 0.05 | fallback | 11.7 / 11.8 | 9.6 / 10.7 | 12.1 / 12.3 | 8.4 / 8.9 | 7.9 / 8.9 | 8.0 / 9.1 | 8.1 / 9.3 | 8.1 / 8.3 |
| | 8 | 0.10 | normal | 12.8 / 14.2 | 11.2 / 12.3 | 13.0 / 14.2 | 9.9 / 9.5 | 9.1 / 9.0 | 9.4 / 10.4 | 9.7 / 9.9 | 9.6 / 9.0 |
| | 8 | 0.10 | skewed | 15.5 / 10.8 | 13.9 / 9.0 | 15.6 / 11.0 | 11.1 / 7.3 | 11.0 / 7.5 | 11.6 / 7.0 | 11.5 / 7.9 | 11.3 / 7.7 |
| | 8 | 0.10 | fallback | 16.1 / 14.8 | 13.4 / 12.2 | 15.9 / 14.6 | 10.4 / 10.8 | 9.8 / 10.0 | 10.3 / 10.3 | 10.8 / 10.7 | 9.9 / 9.5 |
| | 8 | 0.20 | normal | 12.2 / 14.4 | 10.7 / 12.8 | 12.2 / 14.2 | 8.4 / 10.6 | 9.2 / 10.4 | 8.3 / 10.4 | 8.9 / 10.7 | 9.2 / 10.8 |
| | 8 | 0.20 | skewed | 13.8 / 11.2 | 12.6 / 10.0 | 13.8 / 11.0 | 10.8 / 8.2 | 10.7 / 7.4 | 10.3 / 8.1 | 11.0 / 8.4 | 11.4 / 7.5 |
| | 8 | 0.20 | fallback | 13.9 / 12.4 | 11.7 / 11.0 | 13.8 / 13.1 | 9.8 / 8.7 | 10.7 / 9.8 | 9.5 / 8.9 | 10.0 / 9.2 | 10.4 / 10.0 |
| | 12 | 0.00 | normal | 12.8 / 11.9 | 11.7 / 10.9 | n/a | 10.5 / 9.7 | 10.7 / 10.1 | 10.6 / 9.7 | n/a | 10.6 / 10.2 |
| | 12 | 0.00 | skewed | 16.3 / 8.8 | 15.2 / 7.8 | n/a | 14.3 / 6.9 | 14.2 / 6.8 | 14.2 / 6.9 | n/a | 14.1 / 7.0 |
| | 12 | 0.00 | fallback | 12.8 / 13.1 | 11.7 / 12.0 | n/a | 10.2 / 10.3 | 10.8 / 10.2 | 10.0 / 10.2 | n/a | 10.6 / 10.4 |
| | 12 | 0.05 | normal | 11.5 / 12.6 | 10.8 / 11.6 | n/a | 9.7 / 10.7 | 9.8 / 10.3 | 9.8 / 10.5 | n/a | 9.7 / 10.5 |
| | 12 | 0.05 | skewed | 15.9 / 9.4 | 14.8 / 8.5 | n/a | 13.6 / 7.4 | 12.6 / 7.3 | 13.7 / 7.6 | n/a | 12.6 / 7.4 |
| | 12 | 0.05 | fallback | 13.0 / 11.9 | 11.7 / 10.5 | n/a | 10.1 / 9.5 | 9.7 / 9.2 | 10.2 / 9.7 | n/a | 9.8 / 9.3 |
| | 12 | 0.10 | normal | 12.2 / 11.3 | 11.4 / 10.7 | n/a | 10.2 / 9.6 | 9.8 / 9.8 | 10.4 / 9.5 | n/a | 10.0 / 9.8 |
| | 12 | 0.10 | skewed | 14.9 / 9.6 | 13.9 / 8.6 | n/a | 12.9 / 7.8 | 13.2 / 8.2 | 12.7 / 7.7 | n/a | 13.1 / 8.1 |
| | 12 | 0.10 | fallback | 11.8 / 12.6 | 10.4 / 11.4 | n/a | 9.3 / 9.7 | 9.5 / 10.5 | 9.3 / 9.8 | n/a | 9.5 / 10.5 |
| | 12 | 0.20 | normal | 12.8 / 12.0 | 11.8 / 11.3 | n/a | 10.4 / 9.7 | 10.0 / 9.0 | 10.5 / 9.6 | n/a | 10.3 / 9.2 |
| | 12 | 0.20 | skewed | 13.1 / 11.2 | 11.9 / 10.5 | n/a | 10.8 / 9.1 | 11.1 / 9.6 | 10.8 / 9.0 | n/a | 11.2 / 9.9 |
| | 12 | 0.20 | fallback | 12.0 / 13.2 | 11.0 / 11.8 | n/a | 9.7 / 10.2 | 9.4 / 9.6 | 9.7 / 10.5 | n/a | 9.8 / 9.7 |

| alpha 0.05 | G | ICC | dist | WCU_rad | WCU_rad_cr1 | WCU_webb | SF_sum | SF_mean | WCR_t_rad | WCR_t_webb | T_means |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | 4 | 0.00 | normal | 11.9 / 11.9 | 9.5 / 10.2 | 13.3 / 12.8 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 6.0 / 6.4 | 5.5 / 5.7 |
| | 4 | 0.00 | skewed | 15.0 / 10.7 | 12.3 / 8.2 | 16.0 / 11.7 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 7.1 / 4.5 | 5.8 / 2.9 |
| | 4 | 0.00 | fallback | 11.9 / 10.8 | 9.0 / 7.7 | 12.7 / 12.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 5.2 / 5.9 | 3.2 / 3.8 |
| | 4 | 0.05 | normal | 12.5 / 10.7 | 10.1 / 8.9 | 13.7 / 11.3 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 5.9 / 4.8 | 4.6 / 4.2 |
| | 4 | 0.05 | skewed | 14.4 / 9.6 | 11.6 / 6.0 | 15.6 / 10.1 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 7.2 / 3.0 | 5.9 / 2.5 |
| | 4 | 0.05 | fallback | 10.7 / 9.2 | 8.2 / 7.1 | 12.4 / 10.5 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 4.9 / 4.7 | 3.6 / 3.5 |
| | 4 | 0.10 | normal | 11.2 / 13.0 | 8.5 / 10.1 | 12.3 / 13.2 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 5.5 / 5.7 | 4.3 / 5.6 |
| | 4 | 0.10 | skewed | 15.4 / 11.4 | 12.7 / 9.5 | 16.3 / 12.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 7.4 / 5.0 | 6.3 / 3.7 |
| | 4 | 0.10 | fallback | 12.7 / 9.8 | 9.4 / 7.4 | 14.1 / 10.7 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 6.5 / 4.5 | 2.8 / 3.3 |
| | 4 | 0.20 | normal | 13.4 / 11.9 | 10.6 / 9.1 | 14.7 / 12.5 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 5.5 / 4.9 | 5.4 / 4.3 |
| | 4 | 0.20 | skewed | 12.9 / 12.8 | 10.8 / 9.2 | 13.6 / 13.2 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 6.3 / 5.5 | 5.3 / 4.7 |
| | 4 | 0.20 | fallback | 12.3 / 12.5 | 9.1 / 9.9 | 13.0 / 13.7 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 6.3 / 6.0 | 4.9 / 3.8 |
| | 6 | 0.00 | normal | 10.5 / 10.3 | 9.6 / 7.8 | 10.3 / 9.8 | 6.1 / 4.4 | 6.1 / 4.7 | 5.7 / 4.4 | 6.7 / 5.2 | 6.4 / 4.5 |
| | 6 | 0.00 | skewed | 16.1 / 7.5 | 13.8 / 5.4 | 15.9 / 7.3 | 8.2 / 2.9 | 8.1 / 3.1 | 8.4 / 3.0 | 8.9 / 3.3 | 8.2 / 2.5 |
| | 6 | 0.00 | fallback | 8.5 / 10.2 | 6.6 / 7.1 | 8.4 / 9.3 | 3.9 / 3.9 | 4.1 / 3.6 | 4.0 / 4.2 | 4.2 / 4.7 | 2.7 / 2.7 |
| | 6 | 0.05 | normal | 10.1 / 9.8 | 8.6 / 8.1 | 9.6 / 9.6 | 4.1 / 4.3 | 4.1 / 4.5 | 4.0 / 4.3 | 5.0 / 5.1 | 4.8 / 4.5 |
| | 6 | 0.05 | skewed | 13.0 / 9.4 | 10.8 / 7.4 | 12.6 / 8.7 | 6.3 / 4.2 | 6.0 / 4.3 | 6.4 / 4.0 | 7.1 / 4.2 | 5.8 / 3.9 |
| | 6 | 0.05 | fallback | 10.5 / 10.1 | 8.2 / 8.0 | 10.5 / 9.6 | 5.0 / 5.1 | 5.1 / 4.4 | 5.1 / 5.2 | 5.5 / 5.1 | 3.5 / 3.0 |
| | 6 | 0.10 | normal | 11.1 / 11.5 | 8.7 / 9.2 | 10.6 / 11.7 | 4.7 / 4.7 | 4.8 / 5.0 | 4.7 / 4.7 | 5.0 / 5.5 | 4.8 / 5.2 |
| | 6 | 0.10 | skewed | 13.6 / 9.7 | 11.3 / 8.2 | 13.6 / 9.7 | 6.5 / 3.8 | 6.6 / 3.9 | 6.4 / 3.4 | 7.2 / 4.9 | 6.6 / 3.6 |
| | 6 | 0.10 | fallback | 10.5 / 9.0 | 7.8 / 6.5 | 10.2 / 8.4 | 4.9 / 3.3 | 5.0 / 3.5 | 5.1 / 3.4 | 5.4 / 4.0 | 3.8 / 2.1 |
| | 6 | 0.20 | normal | 9.4 / 11.3 | 8.0 / 10.0 | 9.4 / 11.0 | 3.8 / 5.3 | 4.3 / 5.2 | 3.7 / 5.6 | 4.6 / 6.0 | 4.2 / 5.7 |
| | 6 | 0.20 | skewed | 11.6 / 8.6 | 10.1 / 7.5 | 12.0 / 8.7 | 5.4 / 4.8 | 5.0 / 4.3 | 5.6 / 4.3 | 6.0 / 5.2 | 5.9 / 4.4 |
| | 6 | 0.20 | fallback | 10.2 / 10.4 | 7.7 / 8.5 | 9.9 / 10.1 | 4.4 / 4.3 | 4.5 / 5.0 | 4.3 / 3.8 | 4.9 / 4.7 | 2.4 / 3.6 |
| | 8 | 0.00 | normal | 8.9 / 8.1 | 7.4 / 7.2 | 9.1 / 8.1 | 4.8 / 4.2 | 4.7 / 3.9 | 4.8 / 4.4 | 5.2 / 4.7 | 5.3 / 4.4 |
| | 8 | 0.00 | skewed | 12.8 / 5.9 | 11.6 / 4.8 | 12.9 / 5.6 | 7.6 / 3.5 | 7.8 / 3.5 | 7.5 / 3.4 | 8.3 / 3.6 | 7.9 / 3.2 |
| | 8 | 0.00 | fallback | 9.1 / 7.2 | 7.3 / 6.2 | 9.1 / 7.3 | 5.9 / 4.9 | 5.7 / 3.9 | 5.6 / 4.8 | 5.6 / 5.1 | 4.2 / 3.2 |
| | 8 | 0.05 | normal | 8.4 / 8.0 | 7.1 / 6.7 | 8.5 / 8.1 | 4.1 / 4.6 | 4.1 / 4.6 | 4.3 / 4.9 | 4.8 / 4.9 | 4.5 / 4.9 |
| | 8 | 0.05 | skewed | 11.3 / 6.6 | 10.6 / 5.2 | 11.8 / 6.9 | 7.5 / 3.2 | 7.2 / 3.4 | 7.7 / 3.1 | 8.3 / 3.7 | 6.8 / 2.7 |
| | 8 | 0.05 | fallback | 6.6 / 7.6 | 5.2 / 5.8 | 6.5 / 7.3 | 3.6 / 4.4 | 3.0 / 4.1 | 3.6 / 4.7 | 3.7 / 5.1 | 2.3 / 3.3 |
| | 8 | 0.10 | normal | 8.2 / 9.1 | 6.4 / 7.7 | 8.5 / 9.2 | 4.2 / 4.0 | 4.6 / 3.7 | 3.9 / 4.3 | 4.0 / 4.8 | 4.7 / 4.1 |
| | 8 | 0.10 | skewed | 10.3 / 6.4 | 9.2 / 5.7 | 10.1 / 6.5 | 5.3 / 3.1 | 4.7 / 3.0 | 5.7 / 3.2 | 5.7 / 3.8 | 5.1 / 2.9 |
| | 8 | 0.10 | fallback | 9.1 / 8.6 | 7.4 / 6.7 | 9.0 / 8.1 | 5.8 / 4.8 | 5.3 / 5.0 | 5.9 / 4.5 | 6.3 / 5.2 | 4.1 / 3.2 |
| | 8 | 0.20 | normal | 8.3 / 9.5 | 6.6 / 8.1 | 8.3 / 9.1 | 3.7 / 5.1 | 4.0 / 5.1 | 3.7 / 5.3 | 4.3 / 5.7 | 4.0 / 5.3 |
| | 8 | 0.20 | skewed | 9.3 / 7.9 | 7.5 / 6.6 | 9.2 / 7.6 | 5.2 / 3.9 | 6.1 / 3.6 | 5.0 / 4.2 | 5.2 / 4.5 | 5.8 / 3.2 |
| | 8 | 0.20 | fallback | 8.8 / 8.3 | 7.0 / 7.2 | 8.4 / 8.6 | 4.7 / 4.6 | 4.8 / 5.0 | 4.6 / 4.7 | 5.0 / 5.3 | 3.8 / 3.9 |
| | 12 | 0.00 | normal | 7.3 / 7.1 | 6.3 / 6.3 | n/a | 4.9 / 4.6 | 5.1 / 4.9 | 5.0 / 4.6 | n/a | 5.1 / 4.7 |
| | 12 | 0.00 | skewed | 11.5 / 3.9 | 10.2 / 3.2 | n/a | 8.1 / 2.4 | 8.1 / 2.6 | 8.2 / 2.4 | n/a | 7.9 / 2.2 |
| | 12 | 0.00 | fallback | 7.6 / 7.7 | 6.4 / 6.7 | n/a | 5.0 / 5.4 | 5.0 / 5.3 | 4.8 / 5.5 | n/a | 4.0 / 3.9 |
| | 12 | 0.05 | normal | 7.0 / 8.0 | 6.3 / 7.2 | n/a | 4.9 / 5.1 | 4.5 / 5.1 | 5.0 / 5.1 | n/a | 4.4 / 5.1 |
| | 12 | 0.05 | skewed | 10.9 / 5.5 | 10.1 / 4.6 | n/a | 7.7 / 3.4 | 7.0 / 3.6 | 7.8 / 3.3 | n/a | 7.0 / 3.2 |
| | 12 | 0.05 | fallback | 7.7 / 7.0 | 6.6 / 6.2 | n/a | 5.1 / 4.7 | 5.3 / 4.6 | 5.1 / 4.7 | n/a | 4.1 / 3.4 |
| | 12 | 0.10 | normal | 7.9 / 6.8 | 7.0 / 6.0 | n/a | 5.1 / 4.7 | 5.2 / 4.8 | 5.1 / 4.7 | n/a | 5.2 / 4.8 |
| | 12 | 0.10 | skewed | 10.2 / 5.9 | 9.2 / 5.4 | n/a | 6.9 / 4.0 | 7.4 / 4.0 | 6.7 / 4.0 | n/a | 7.3 / 3.5 |
| | 12 | 0.10 | fallback | 6.8 / 7.6 | 6.0 / 6.7 | n/a | 4.8 / 5.0 | 4.7 / 5.0 | 4.9 / 5.0 | n/a | 3.8 / 4.1 |
| | 12 | 0.20 | normal | 7.9 / 7.4 | 7.2 / 6.5 | n/a | 5.5 / 4.7 | 5.5 / 4.6 | 5.4 / 4.5 | n/a | 5.4 / 4.5 |
| | 12 | 0.20 | skewed | 8.3 / 6.9 | 7.3 / 5.9 | n/a | 5.4 / 4.0 | 5.9 / 4.3 | 5.4 / 4.0 | n/a | 5.9 / 4.1 |
| | 12 | 0.20 | fallback | 7.4 / 7.8 | 6.4 / 6.8 | n/a | 4.5 / 5.1 | 4.5 / 5.0 | 4.5 / 5.0 | n/a | 3.8 / 3.9 |

POWER at true mean 1c (upper-tail rejection %), ICC 0.05; alpha 0.10 / 0.05 / 0.05/3 (Holm worst case)
| G | dist | sigma | WCU_rad | SF_sum | SF_mean | WCR_t_rad | T_means |
|---|---|---|---|---|---|---|---|
| 6 | normal | 3c | 65 / 56 / 49 | 53 / 35 / 15 | 51 / 35 / 15 | 53 / 35 / 15 | 54 / 37 / 17 |
| 6 | normal | 4c | 50 / 42 / 35 | 39 / 23 / 9 | 38 / 23 / 9 | 39 / 23 / 9 | 40 / 24 / 10 |
| 6 | fallback | 3c | 47 / 39 / 33 | 37 / 26 / 11 | 37 / 25 / 11 | 37 / 25 / 11 | 36 / 21 / 8 |
| 12 | normal | 3c | 83 / 75 / 62 | 80 / 66 / 43 | 76 / 63 / 41 | 80 / 65 / 42 | 77 / 63 / 41 |
| 12 | normal | 4c | 65 / 54 / 42 | 61 / 46 / 26 | 58 / 43 / 25 | 61 / 45 / 25 | 58 / 43 / 25 |
| 12 | fallback | 3c | 47 / 40 / 32 | 44 / 35 / 23 | 46 / 35 / 22 | 44 / 35 / 23 | 45 / 31 / 15 |
```

</details>

### 8.2 `exp002-e1-review-bias-v1` (bias illustrations)

Command: `python e1_bias_sim.py`. Seed 20261023, 200,000 games per row. The hold-to-settlement column has a
standard error of about 0.4¢ (a binary payoff), so its row-to-row differences are noise; it is shown only to
illustrate how noisy the settlement endpoint is. Rows that add the sticky-down draw consume the random stream
differently, which is why their hold column differs.
Script sha256
`7a24664330460b342a14f5b7f1c1833158165ac9e7434f9fe392e35a0d2d2a8e`;
output sha256 `07ad4860fdf18c18788cce43c65fa98d2f4e273b00f40daefd7eb43926816c62`. A row label once read `|move|`,
which broke the GitHub table; only that label changed, so every number is as before. The output is the table in §4.

```python
"""E1 bias illustrations (exp002-e1-review-bias-v1). SYNTHETIC ONLY: no EXP-002 data. Cents throughout.

One team market per game (the other side is symmetric). V6 ~ U(25, 75) is the latent value at T-6h; V1 = V6 + xi,
xi ~ N(0, 3) is the value at T-60m (a martingale under every null); the payoff is Bernoulli(V1/100)*100 (no ties).
Kalshi quotes 1-tick books: bid = floor(fair), ask = bid + 1, fair = V + quote error. The consensus c = V6 + eta,
eta ~ N(0, gap_sd), plus an informative part in the INFO scenario. Entry (E1 row 3): c_low - ask6 >= theta, with
c_low from tie_adjusted_interval (tie payout 50, bounds t, u; F in [0, 100]). Exit at bid1; a missing exit is scored
at the payoff (settlement fallback).
"""
import math
import random

SEED = 20261023
N = 200_000


def c_low(p, t, u):
    return min((1 - tt - uu) * p + 50 * tt + uu * f for tt in (0, t) for uu in (0, u) for f in (0, 100))


def run(scn, t=0.01, u=0.01, theta=1.0, gap_sd=1.5, miss=0.0, informative_miss=False, pickoff=0.0, sticky_down=0.0,
        seed=SEED):
    rng = random.Random(seed)
    g, gh, marg, fb = [], [], [], 0
    for _ in range(N):
        v6 = rng.uniform(25, 75)
        xi = rng.gauss(0, 3)
        v1 = v6 + xi
        e6 = 0.0
        stale = False
        if scn == "STALE" and rng.random() < 0.35:  # quote centred on an old value: beyond assumption W
            e6, stale = rng.gauss(0, 3), True
        info = 0.3 * xi if scn == "INFO" else 0.0  # the consensus knows 30% of the coming move
        c = v6 + info + rng.gauss(0, gap_sd)
        ask6 = math.floor(v6 + e6) + 1
        m = c_low(c, t, u) - ask6
        if m < theta:
            continue
        if stale and pickoff and rng.random() < pickoff:  # a stale favourable ask is gone before a real order
            continue
        bid1 = math.floor(v1)
        if xi < 0 and sticky_down and rng.random() < sticky_down:  # the bid has not followed a fall (stale high exit)
            bid1 = math.floor(v6)
        payoff = 100.0 if rng.random() < v1 / 100 else 0.0
        missing = rng.random() < ((0.2 if abs(xi) > 6 else 0.01) if informative_miss else miss)
        fb += missing
        g.append((payoff if missing else bid1) - ask6)
        gh.append(payoff - ask6)
        marg.append(m)
    n = len(g)
    mean = sum(g) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in g) / (n - 1))
    return {"trade_rate": n / N, "mean_margin": sum(marg) / n, "mean_gross": mean, "sd_gross": sd,
            "se": sd / math.sqrt(n), "mean_hold": sum(gh) / n, "fallback_share": fb / n}


def row(label, r):
    print(f"| {label} | {100 * r['trade_rate']:.1f}% | {r['mean_margin']:+.2f} | {r['mean_gross']:+.2f} "
          f"(se {r['se']:.2f}) | {r['sd_gross']:.1f} | {r['mean_hold']:+.2f} | {100 * r['fallback_share']:.1f}% |")


print("| scenario | trade rate (one side) | mean entry margin c_low-ask | mean E1 gross | SD gross | mean hold-to-settle "
      "| fallback share |")
print("|---|---|---|---|---|---|---|")
row("NULL, W holds, gap SD 1.5, u=0.01", run("NULL"))
row("NULL, W holds, gap SD 1.5, u=0.005", run("NULL", u=0.005))
row("NULL, W holds, gap SD 3, u=0.01", run("NULL", gap_sd=3.0))
row("NULL, W holds, gap SD 3, u=0.005", run("NULL", gap_sd=3.0, u=0.005))
row("STALE 35% (beyond W), zero latency", run("STALE"))
row("STALE 35%, half the stale favourable asks picked off", run("STALE", pickoff=0.5))
row("INFO (consensus knows 30% of the move)", run("INFO"))
row("NULL + 3% random missing exits", run("NULL", miss=0.03))
row("NULL + 10% random missing exits", run("NULL", miss=0.10))
row("NULL + informative missing exits (20% if abs(move)>6c)", run("NULL", informative_miss=True))
row("INFO + informative missing exits", run("INFO", informative_miss=True))
row("NULL + sticky-down exit bids (50% of falls unpriced)", run("NULL", sticky_down=0.5))
row("NULL + sticky-down exit bids (20% of falls unpriced)", run("NULL", sticky_down=0.2))
```

## 9. Remaining risks (not resolved by any change above)

1. **Zero-latency optimism.** Every E1 fill is at a displayed quote at its receipt time. The quotes E1 selects are
   the ones most likely to vanish first, at entry and at a sticky exit. One snapshot per horizon cannot measure
   this; a positive E1 is an upper bound for any real trader (§4.3).
2. **Power.** At about 54 trades over 12 weeks, 1¢ is detectable only at SD ≤ 3¢ with almost no fallbacks. A
   news-driven SD of 6–8¢ puts the MDE at 2–3¢. A null result will often be INSUFFICIENT_EVIDENCE rather than a clean
   futility verdict.
3. **Few clusters and skew.** Even the recommended restricted test relies on approximately symmetric week
   contributions. In §3.2 the 3% settlement-fallback mixture did not hurt its size, but left-skewed news jumps did:
   10–15% at a nominal 10% and 5–8% at a nominal 5%, for every method tested. No reweighting fixes that at 4–5
   trades a week.
4. **Economic distance.** A gross pass at 1¢ is below every fee break-even (UNVERIFIED fees) and far below the
   $1,000/year bar at any plausible size (§5).
5. **Consensus quality.** Proportional de-vig and unknown book source families (protocol `[knowledge]`) make the
   signal noisier and possibly biased toward longshots (UNVERIFIED). This costs power, not validity.
6. **Tie and F semantics.** Reading `settlement_value_dollars` as the YES payoff in a tie is UNVERIFIED for
   KXNFLGAME (`EXP002_E1_ENDPOINT.md` §2.9), and the after-55-minutes rule conflict is unresolved. Both affect only fallback-F
   and tie trades, which are rare.
7. **Procedural holdout protection.** The log records declared access only. Until C14 exists, keeping the
   evaluation window untouched depends on the operator passing `--as-of`.
8. **This review's own limits.** The simulations use stylised distributions (normal, a left-skewed jump mixture and a
   3% fallback mixture), a Binomial(15, 0.3) weekly trade count and ICC up to 0.20. Real E1 P&L may be more
   discrete (1¢ ticks), more skewed, or more dependent within weeks. The fee formula, the inactives timing and the
   favourite–longshot remark are secondary knowledge, marked UNVERIFIED where used.

## 10. Evidence use in this review

- No EXP-002 data of any kind was viewed (see the header). No evidence-use event was appended.
- Repository documents and code at `e8703d7`, and the evidence-use log's event metadata, were read.
- Synthetic simulations only (§8), with the seeds and hashes stated.
