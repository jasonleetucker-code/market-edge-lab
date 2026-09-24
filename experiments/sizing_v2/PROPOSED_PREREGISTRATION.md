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
2. **Candidate:** `sizing_v2.POLICY_CANDIDATE`, which is `SV2-H-cluster-robust-rck` version 1,
   frozen in the engine (any change is a new version and a new experiment).
   - Joint robust 1/2 Kelly over each day's KXHIGHNY bracket cluster.
   - The robust drawdown constraint E[(W'/W)^-lambda] <= 1 with alpha 0.7 and beta 0.1,
     evaluated at the worst admissible vector.
   - Hard caps from `exp001_shadow.RISK_POLICY` via `risk.assess`, plus STARTER_MAX_7D_V1.
   - **How it was chosen: after the fact.** It was picked after seeing the whole simulation
     study (`docs/research/STAKE_SIZING_V2.md` §7, §9): **547 variant runs across runs 1-3**,
     over 18 distinct policy variants. It was in the variant set from run 1, and the choice
     was made after runs 1-3.
     - The reason: it kept ruin at zero and P(drawdown > 50%) small in every main scenario,
       including overconfident and anti-informative models.
     - Choosing the best of 18 on the same simulated worlds is a selection effect. This
       experiment exists to test the choice on data that did not inform it.

## Candidate universe (fixed)

- **Decisions.** On each valid Stage B decision day, the universe is every (bracket, side)
  pair of that day's KXHIGHNY event that the Stage B pipeline evaluates at the decision
  time. That means every open bracket, both YES and NO, with a captured decision-time
  ladder, whether or not the frozen signal qualifies it.
  - The baseline trades only the frozen signal's QUALIFY decisions, 1 contract each.
  - The candidate sizes the whole universe jointly, as one mutually exclusive cluster, and
    may size any pair at zero.
- **Excluded.** Brackets the engine refuses: UNSUPPORTED, STALE_DATA, RULES_UNRESOLVED or
  MARKET_NOT_OPEN, or a settlement.resolve UNKNOWN. They are counted and reported, never
  traded.

## What the operational caps mean for this test (read before interpreting it)

The candidate runs under the operational `RISK_POLICY`:
- $1.00 per position;
- $6.00 per event and per cluster;
- $50.00 portfolio;
- a $100.00 reserve;
- loss limits $10 daily, $25 weekly, $50 drawdown.

At KXHIGHNY prices a $1 position is 1 to about 3 contracts (fewer above 50 cents). So the
candidate can differ from fixed-1 mainly by **abstaining**: its robust objective sizes zero
where the fixed rule buys 1. It can add at most a couple of contracts where the edge is
large, and spread a cluster budget of at most $6 across brackets. This is therefore
**mostly a test of abstention (selectivity) plus small joint allocation**, not of Kelly
growth at scale. A pass does not show that v2 would behave well with looser caps. That
would need its own experiment.

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
- **Fills (all-or-nothing).** Both policies fill under the same `latency-confirmed-v1` rule.
  An order of N contracts fills in full only if the re-check book offers all N at or below
  the order's limit price (the worst price of the decision-time walk). Otherwise the whole
  order is NO_FILL. No partial fill is priced or recorded, consistent with `walk_ladder`,
  which never prices a partial fill.
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
