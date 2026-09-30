# EXP-002 E1 executable round-trip endpoint: implementation (`exp002-e1-roundtrip-v2`, 2026-09-30; v1 2026-09-29)

## v2 (2026-09-30): the E1 design review's code-level changes (PROPOSED; no EXP-002 data viewed)

Source: `docs/research/EXP002_E1_DESIGN_REVIEW.md` §7 (C1, C4, C5, C11, C12, C14) and `EXP002_FREEZE_PROPOSAL_V2.md`.
Both are PROPOSED; nothing here freezes anything. Tests use SYNTHETIC fixtures only. The measurement version moves to
`exp002-measurement-v4` (adds `evaluation_window_guard`); E1 moves to `exp002-e1-roundtrip-v2`.

| Change | Code | What v1 did |
|---|---|---|
| C1 (as revised in #154, head f3cf76f): for **G ≥ 6** week clusters, the exact restricted, studentized Rademacher sign-flip test by NFL week, every pattern enumerated (up to 20 weeks; seeded draws beyond, past any realistic season); one-sided p for H0: E[gross] ≤ 0; one-sided 95% and 90% bounds by inverting the same test. For **G < 6**: INSUFFICIENT_EVIDENCE, no confirmatory inference. For **G = 4–5** only: a one-sided 90% upper bound from a t-test on the G week means (G − 1 df), flagged COARSE_FEW_CLUSTERS, futility information only, never efficacy. No Webb weights at any G. Always: `min_achievable_p_rademacher` = 1/2^G and `no_rejection_possible_at_0_05`, and the t on week means (G − 1 df) as a reported cross-check. Enumeration is exact up to 20 weeks (the review permits draws above 12). No verdict | `e1_signflip`, `summary.primary.sign_flip_test` | the unrestricted wild cluster bootstrap only; kept as `week_cluster_bounds`, now labelled "DESCRIPTIVE ONLY" |
| C4: exit ladder: own first T-60m bid (depth ≥ 1), else 1 − the other team market's first T-60m ask in the same window (depth ≥ 1), else the settlement payoff, else PENDING; each trade records its basis; the exit-at-0 sensitivity stays | `e1_endpoint`, `_e1_other_ask` | own bid, else settlement; still reported as `summary.v1_exit_order` (descriptive) |
| C5: counts and shares of the three exit bases; `SETTLEMENT_VARIANCE_DOMINANT` when the settlement share of scored trades exceeds 5% (a flag, not an endpoint switch) | `exit_bases` | not reported |
| C11 (results path only): the share of entries with displayed ask depth ≥ 10 and ≥ 250; a descriptive 10-contract E1 on the ladders (own-bid exits; NOT_EVALUATED when not fillable or a fractional level is crossed) | `size` | not reported |
| C12 (results path only, descriptive): the mean less one tick; the single-book anomaly flag at entry (the other market's same-capture T-6h bid) with P&L split by it; the exit cross-check (own bid above 1 − the other market's ask at the same T-60m capture); the skewness of the primary P&L and G beside the calendar weeks (freeze proposal v2 row 5); "the entry margin is not an edge estimate" in every E1 output | `execution_diagnostics`, `entry_margin_note` | not reported |
| C14: the results path refuses every game whose kickoff is on or after `EVALUATION_WINDOW_EARLIEST_ET` (2026-10-22 00:00 ET) or unknown, right after the label-free T-6h join and before any label is read or anything is logged; labels are read only up to `EVALUATION_LABEL_CUTOFF` (the window start less 2 h). Lifting it needs a freeze record and a reviewed code change | `evaluation_window_refused`, `measure_exp002` | nothing capped a results run |

Label safety is unchanged: the label-free path reads no T-60m book or outcome; the results path records its evidence
first and shows nothing if the record fails; the synthetic exit reads the other team's T-60m book only on the results
path.


**E1 is PROPOSED, not frozen.** This is research code for the E1 endpoint that
`EXP002_FREEZE_PROPOSAL.md` (`exp002-freeze-proposal-v1`) proposes in §3 rows 3, 4, 5(b), 11 and 15. That
proposal stays authoritative and is not edited. EXP-002 stays DRAFT, `protocol.toml` is unchanged, and
`freeze_eligible` is always False.

Every E1 output carries these labels:
- "PILOT DESCRIPTIVE — PROPOSED ENDPOINT, NOT FROZEN, NOT A TEST";
- the FIRST_DETECTION_ZERO_LATENCY fill assumption;
- "a displayed quote is not a proven fill".

E1 reports gross figures only. KXNFLGAME fees are FEE_UNSUPPORTED. No fee is applied, no fee is treated as 0,
and no net figure exists. No verdict is given. The operational, statistical and economic futility rules of row 15
are left to the freeze review; this code only reports their inputs as numbers.

This implementation used SYNTHETIC fixtures only. No real EXP-002 data was read.

## 1. What was implemented

Code: `src/edge_lab/sports_evidence.py`, section "EXP-002 E1". Tests: `tests/test_exp002_e1.py`. The
measurement version moves to `exp002-measurement-v3`, which adds the `e1` key. Every v2 key is unchanged.

| Proposal item | Code |
|---|---|
| Row 3 entry: T-6h information only, AT_OR_AFTER_ODDS paired sides; `c_low(side) − ask ≥ θ`; displayed ask depth ≥ 1; at most one side per game (the larger margin, neither on a tie) | `e1_entries`, `_e1_side` |
| Row 3: `c_low(away)` is the lower end of the away contract's **own** interval | `tie_adjusted_interval` of the away side's own consensus; never `1 − c_high(home)` |
| Row 3 exit: the bid of the first T-60m book of the same market; `bid₁ − ask₆`; 1 contract | `e1_endpoint`, `_e1_exit`, reusing `_first_book` and `markout_endpoint`'s window |
| Row 3 missing exit: scored at the settlement payoff; exit at 0 as a sensitivity; both in the attrition | `_e1_settlement`; `attrition`, `summary.primary`, `summary.sensitivity_exit_at_0` |
| Row 4: θ = 1¢; one-sided test framing; wild cluster bootstrap, Rademacher weights, NFL-week clusters | `E1_THETA`; `_wild_cluster_bounds` gives one-sided 90% lower and upper bounds (descriptive; no test is run) |
| Row 5(b): hold-to-settlement gross of the E1 trades, descriptive | `summary.secondary_hold_to_settlement` |
| Row 11 / 15 inputs: SD, trade rate, pairing yield, trades per week | `summary.primary.sd_gross`; `operational_futility_inputs` (numbers only) |

## 2. Conservative readings of ambiguous points

1. **Undeclared bounds.** No entry is computed. The side is counted as `BOUNDS_UNDECLARED`. There is no
   fallback to the unadjusted consensus, which the markout uses for its sign only.
   - Today `JoinPolicy()` has both bounds as None, and EXP-002's protocol leaves them UNKNOWN (OPEN 1).
   - So a default run computes no E1 entry at all.
   - A caller can declare candidate bounds for E1 only, with `measure_exp002(e1_bounds=...)` or
     `exp002 --e1-tie-bound T --e1-postponement-bound U`. Examples are the proposal's PROPOSED t_max = 0.01 and
     u_max = 0.005.
   - Declared bounds must each be a finite number in [0, 1] with a sum of at most 1. Anything else is refused
     before the store opens, so an invalid bound can never spend a logged look.
   - Declared bounds are recorded in the output as `CALLER_DECLARED_CANDIDATE` and in the evidence-log note of a
     results run. They never reach the gates, whose policy is unchanged.
2. **Pairing is judged per side.** A side is entered only if both of these hold:
   - its own T-6h pair is PAIRED at the side level and AT_OR_AFTER_ODDS;
   - the row has no row-level failure.

   One side failing to pair (PARTIAL_PAIR), or being ineligible, never blocks the other side. BEFORE_ODDS sides
   are counted and never entered.
3. **Freshness fails closed.** An entry needs the paired book FRESH at the pair's decision time. It also needs the
   odds FRESH there: `decision_freshness_odds` combines the odds receipt age with the books' `last_update`
   freshness. A row excluded as ODDS_NOT_FRESH, or a side whose book is stale or undated, is counted as
   `STALE_OR_UNKNOWN_INPUT`.
4. **Each side gets exactly one reason**, the first that applies, in this order:
   1. NOT_PAIRED or STALE_OR_UNKNOWN_INPUT (join failures);
   2. BEFORE_ODDS;
   3. STALE_OR_UNKNOWN_INPUT;
   4. NO_ASK;
   5. NO_CONSENSUS;
   6. BOUNDS_UNDECLARED;
   7. TIE_PAYOUT_UNKNOWN (the rules' tie clause was not parsed);
   8. MARGIN_BELOW_THETA;
   9. ASK_DEPTH_MISSING;
   10. ASK_DEPTH_BELOW_1;
   11. ELIGIBLE.
5. **Arithmetic is exact.** Margins, θ and P&L are Decimal, so "margin ≥ θ" and "an exact tie of margins" are
   exact. Summaries (mean, SD, bounds) are floats.
6. **Exit depth.** The YES best bid's displayed size is the total size resting at that price, which is the NO ask's
   displayed size in `kalshi_quotes`. A zero-size bid is no bid.
7. **Missing exits.** The following are missing exits, and each is scored:
   - NO_T60_TARGET;
   - NO_T60_BOOK;
   - UNUSABLE_BOOK: a hash mismatch, a payload without a book, a malformed book, or a crossed book. Note that
     `kalshi_quotes` flags a locked book (YES bid + NO bid = 1) as crossed;
   - NO_BID;
   - BID_DEPTH_MISSING;
   - BID_DEPTH_BELOW_1.

   A missing T-60m target counts as a missing exit only once kickoff has passed. Before kickoff it is PENDING
   (`NO_T60_TARGET_BEFORE_KICKOFF`).
8. **Pending is never 0.** A T-60m window whose deadline is after `as_of` is PENDING (`T60_WINDOW_OPEN`). It is
   not scored anywhere and its book is never read.

   A missing exit whose settlement is not final is also PENDING in the primary. It is excluded from the mean and
   never scored as 0. It is still scored in the exit-at-0 sensitivity, because that sensitivity needs no
   settlement.
9. **Settlement payoff.** A settlement is final only when the latest stored listing's status is `settled` or
   `finalized`. `determined` is preliminary.
   - A result of YES pays 1, and NO pays 0.
   - Any other settled result (a tie, or a fair price F) uses the listing's `settlement_value_dollars`, only when
     it is stated and within [0, 1]. Otherwise it is PENDING (`SETTLED_VALUE_UNKNOWN`).
   - A stated value that contradicts a YES or NO result is PENDING (`SETTLEMENT_CONFLICT`).
   - Reading `settlement_value_dollars` as the YES payoff is **UNVERIFIED for a KXNFLGAME tie**, because no tie
     has been observed. The code refuses to guess when the value is absent.
10. **Denominators.**
    - The trade rate is trades ÷ due T-6h games where at least one side's margin was computed (`games_evaluable`).
    - The pairing yield is due T-6h games with at least one AT_OR_AFTER_ODDS paired side ÷ due T-6h games. The
      both-sides yield is reported next to it.
    - Trades per week is trades ÷ weeks with a due T-6h game, and is also given per week.
11. **Bootstrap.** The wild cluster bootstrap enumerates every Rademacher sign pattern exactly when there are at
    most 12 weeks. With more weeks it samples 2,000 patterns with the fixed seed 20260926. Below 10 weeks it is
    flagged `COARSE_FEW_CLUSTERS`, because only 2^G patterns exist. The bounds are basic (reflected) bootstrap
    bounds: lower = mean − q90(mean* − mean) and upper = mean − q10(mean* − mean). With exact enumeration the
    deviations are symmetric, so these equal the percentile bounds. They are descriptive, and they are not compared
    with δ_min.
12. **Secondary (b)** covers every trade whose settlement is final, whatever its exit basis.

## 3. Label safety

- **Label-free entries.** `e1_entries` takes only the join rows. It takes no catalog, payload reader, target list
  or outcome. `measure_exp002` gives it the gate's own rows, which are T-24h and T-6h only and built from a
  catalog without the settled listing fields. So it cannot load a T-60m book or read a settlement.
- **Label-free output.** Without `--with-results`, only `e1_entry_summary` is shown. It holds the entry counts by
  T-6h reason, the bounds, the trade-rate numerator and denominator, the pairing yields and entries per week. It
  has no per-game rows, and no exit, P&L, settlement or T-60m availability.
- **Tests of the label-free path.**
  - `_first_book`, `outcome_for`, `_e1_settlement`, `_e1_exit` and `e1_endpoint` are never called.
  - Only the settled-fields-dropped catalog is built.
  - No T-60m snapshot is loaded.
  - The label-free E1 output is **identical** for a store with T-60m books and settlements and for one without
    them.
- **Results path.** Exits, P&L and settlements run only with `results=True`, which is the CLI's
  `exp002 --with-results`. That run is refused without `--evidence-log`, `--actor` and a code version.
  - It is recorded in EXP-002's own evidence log (`record_markout_view` → `_record_label_view`) before anything
    is printed.
  - The recorded window covers every E1 game.
  - The note names the E1 fields shown and the E1 bounds.
  - If recording fails, nothing is shown.
  - Results runs are DEVELOPMENT looks at pilot data (proposal §4).

## 4. No UI change

E1 is not added to the Terminal, and `src/edge_lab/dashboard/**` is not edited. Its exits, P&L and settlements
are EXP-002 labels, which only the logged results path may show, and the Terminal is not a logged consumer of
labels (`EXP002_GATE_V3.md` §7). A later label-free Terminal line for E1 entry counts would need its own
UI_CONTRACT review.

## 5. What remains before any freeze (unchanged)

The freeze blockers of `EXP002_FREEZE_PROPOSAL.md` §5 all still stand. Implementing E1 clears none of them:
1. review of the E1 change (§3 rows 3–5 and 11), which this code makes reviewable but does not approve;
2. a sourced tie and not-played count behind `t_max` and `u_max`. Until then, E1 bounds are caller-declared
   candidates only;
3. the A.C timing calibration, with the exposure caveat;
4. KXNFLGAME fee verification for any after-fee figure;
5. the owner's freeze review.

The pilot's trade rate and E1 SD (row 11) come from a logged DEVELOPMENT look (`exp002 --with-results`). That
look is taken only after the A.C timing freeze (proposal §4).
