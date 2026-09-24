# PROPOSED preregistration: prospective sizing experiment for stake sizing v2

**Status: PROPOSED.**
- This is not registered, not frozen, and not running. It has no `EXP-NNN` id yet. The id
  is assigned when it is registered as `experiments/EXP-NNN-.../experiment.toml`
  (DRAFT → PREREGISTERED → `edge-lab experiments freeze`).
- The text is a starting point for review. Every field below becomes locked only when it
  is frozen.
- Authority: the 2026-09-24 directive, recorded in `docs/EXECUTION_PLAN.md`. Stake sizing v2
  "may influence shadow fills only after a separately recorded sizing experiment passes its
  own acceptance criteria". This is that experiment.

**Why it is not registered now.**
- It needs a counterfactual runner that reads the operational shadow ledger's prospective
  decisions and captured books. That runner is not built yet.
- It depends on EXP-001 Stage B evidence that does not exist yet: one valid day so far.
- Registering it with placeholder periods would add nothing, because the validator rejects
  placeholders.

## Hypothesis

On the same prospective, point-in-time EXP-001 decisions, books and fill model as the
operational shadow account, the v2 candidate policy produces higher log growth than the
frozen operational rule `EXP-001-fixed-1-v1`, and stays inside the operational risk limits.

## Compared policies (exactly two; no others, no tuning)

1. **Baseline:** `EXP-001-fixed-1-v1` (`sizing.py`), as the operational shadow account runs it.
2. **Candidate:** `SV2-H-cluster-robust-rck` version 1 (`sizing_eval.H_RCK`).
   - Joint robust 1/2 Kelly over each day's KXHIGHNY bracket cluster.
   - The robust drawdown constraint E[(W'/W)^-lambda] <= 1 with alpha 0.7 and beta 0.1,
     evaluated at the worst admissible vector.
   - Hard caps from `exp001_shadow.RISK_POLICY` via `risk.assess`, plus STARTER_MAX_7D_V1.
   - Why this candidate: in the simulation study it and its single-candidate twin were the
     only variants with no ruin and P(drawdown > 50%) <= 0.01 in every main scenario,
     including overconfident and anti-informative models (`docs/research/STAKE_SIZING_V2.md`
     §7). The joint version was preferred for its lower tail under overconfidence.

## Inputs, fixed in advance

- **Model probability.** EXP-001 V1 bracket probabilities exactly as the Stage B pipeline
  records them at the decision time (`exp001_stageb`). They are never refitted.
- **Uncertainty set.** `sizing_v2.dirichlet_box(states, p, n_eff, gamma=0.10, prior=0.5)`,
  with n_eff(t) = 89 + d(t):
  - 89 = floor(629 / 7): the Stage A out-of-sample test days divided by the 7-day
    dependence block of the frozen bootstrap. This is a dependence haircut on calibration
    evidence that already exists.
  - d(t) = the settled prospective valid Stage B days before t.
- **Costs.** `schedule_for("kalshi", "KXHIGHNY")` with the point-in-time claim basis. A
  CONSERVATIVE_BOUND claim adds its $0.0101-per-contract allowance, and a claim basis of
  NONE makes the day UNSUPPORTED for v2.
- **Depth.** The captured decision-time ladder, walked with the market's price grid.
- **Fills.** Both policies fill under the same `latency-confirmed-v1` rule. A v2 size larger
  than the re-check book offers at or below the entry price is NO_FILL for the unfilled
  part. No partial fill is priced.
- **Bankroll and risk state.**
  - A separate notional counterfactual account for each policy, starting at $1,000.00
    (the operational notional bankroll).
  - Each account uses the operational `RISK_POLICY`.
  - Risk state comes from `risk.assess` on that account's own counterfactual ledger.

## Periods

Prospective only: every valid Stage B day whose decision time falls after registration.
The looks are the same valid days as EXP-001 Stage B:

- the 180th valid day (FAIL-only look);
- the 365th valid day (the final look).

No other look is taken. Days before registration are never used, including the one already
observed.

## Success criteria (all must hold at the 365th valid day)

1. **EXP-001 Stage B passed** (SHADOW_POSITIVE at a preregistered look). Without an edge,
   no sizing rule can be accepted.
2. **Integrity.**
   - Every v2 recommendation re-runs to the same `input_hash` and `output_hash`.
   - Zero SIZE verdicts with a stale, missing or lookahead input.
   - Zero hard-cap breaches in the v2 account.
3. **Risk.**
   - The v2 account's maximum drawdown stays within `RISK_POLICY.max_drawdown` ($50).
   - No daily or weekly loss limit is breached.
4. **Growth.** d_t = log(W_v2,t / W_v2,t-1) - log(W_fixed,t / W_fixed,t-1) over valid days
   in date order.
   - The mean of d_t must be > 0.
   - Its 97.5% block-bootstrap lower bound must be > 0: `edge_lab.stats.block_bootstrap_mean_ci`,
     block 7, 10,000 resamples, alpha 0.025, seed 20260924.

## Failure criteria

- Any look: the v2 account breaches a hard cap or the drawdown limit, or has an integrity
  failure (fail immediately; the experiment stops).
- At the 180th valid day: the 97.5% upper bound of mean d_t is below 0.
- EXP-001 Stage B fails. The experiment is then CONCLUDED_FAIL for lack of an edge; the
  sizing is not at fault, but it cannot be accepted.
- At the 365th valid day: if neither success nor failure holds, the result is INCONCLUSIVE.

## Limitations (declared)

- One series, one decision a day. The growth test has little power for small differences.
  An INCONCLUSIVE result is likely and acceptable.
- n_eff is an evidence-based haircut, not a fitted quantity. Its dependence adjustment is
  a judgment fixed in advance.
- A counterfactual account is not the operational account. Passing authorizes proposing a
  change to the operational sizing policy through the usual owner approval. It is never
  automatic.

## What passing does *not* authorize

- Real money.
- Gate 8 or later.
- Any change to the frozen EXP-001 research account.
- Any sizing change without an owner-approved `docs/EXECUTION_PLAN.md` entry.
