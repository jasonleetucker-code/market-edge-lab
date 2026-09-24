# 0026 — Stake sizing v2: a separated, robust research challenger beside the frozen sizing path

Status: Accepted (2026-09-24, owner directive `docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`,
Phase 3 and owner correction 2). Research and shadow only. Nothing here changes a shadow fill.

**Problem.**
- The operational shadow account sizes with `sizing.py` under `EXP-001-fixed-1-v1`: one
  contract per signal, then hard caps. The frozen research account buys exactly one
  contract per signal. Neither says how much capital a qualifying opportunity deserves.
- The owner wants that amount to come from mathematics, data and statistics. It must not
  come from intuition, raw model confidence, confidence labels, or an LLM choosing a dollar
  figure. It must also count several things together:
  - the actual payoff;
  - executable depth and fees;
  - uncertainty in the probability;
  - portfolio and cluster exposure;
  - the risk stops;
  - the seven-day capital rule.
- Owner correction 2: the pessimistic probability must not be hardcoded as `p_lo`. For each
  stake, the worst admissible expected log wealth is taken over the whole uncertainty set,
  and the adverse point must be derived from the payoff.
- There is almost no out-of-sample trading evidence yet: one prospective Stage B day.

**Alternatives.**
1. Tune `sizing.py` in place, for example by switching on its `kelly_fraction` rule. This
   silently changes the operational account's behaviour. It also keeps the `p_lo`-only
   binary view, has no depth-aware cost, and cannot handle mutually exclusive brackets
   jointly.
2. `features -> ML model -> dollar amount`. This is opaque and cannot be audited. It needs
   far more data than exists and merges model error with risk policy. The directive
   excludes it (3B).
3. A separate research engine (`sizing_v2.py`) with explicit layers, compared against the
   simple policies in a seeded simulation. It changes nothing operational until a
   separately recorded sizing experiment passes its own criteria.

**Decision.** Alternative 3.
- `sizing.py`, `fees.py`, `exp001_shadow.py` and every EXP-001 artifact stay unchanged.
  `tests/test_sizing_v2.py` pins the three modules by an LF-normalized content SHA-256, and
  the existing invariant pins the EXP-001 files the same way. The operational account keeps `EXP-001-fixed-1-v1`.
- `src/edge_lab/sizing_v2.py` separates seven layers, and each has one owner:
  1. **Probability model**: an input. A vector over the K mutually exclusive outcome states
     of one cluster; a binary is K = 2.
  2. **Uncertainty**: a set of admissible probability vectors. Either a polytope
     (`BoxSimplexSet`, per-state bounds intersected with the simplex) or an explicit finite
     set (`VertexSet`). Constructors cover a binary interval (including the existing
     `conservative.ProbabilityBounds`), per-state Wilson bounds (reusing
     `conservative.wilson_bounds`) and a Dirichlet/Beta posterior with deterministic,
     Bonferroni-split marginal quantiles.
     - The robust objective is the minimum over the set of expected log wealth. That
       expectation is linear in the probability vector, so the minimum over a polytope is
       attained at an extreme point.
     - `BoxSimplexSet.worst` solves it exactly (a fractional knapsack). `vertices()`
       enumerates the extreme points, and tests hold both equal to a dense interior grid.
     - The adverse vector comes out of the payoff: low P(YES) for a YES, high P(YES) for a
       NO, and the losing states' mass for a multi-state position. No side is assumed.
  3. **Execution cost**: `walk_ladder` with the market's `price_grid`, then
     `price_depth_fill` under `schedule_for(venue, scope, as_of=...)` (`sizing_v2.fee_basis`).
     A venue whose scope needs market metadata (Polymarket US `feeCoefficient`) must be
     given its schedule explicitly; without one it is refused.
     - The CONSERVATIVE_BOUND per-contract allowance is added when that is the claim basis.
     - An unsupported schedule, or a claim basis of NONE, is UNSUPPORTED.
     - Nothing beyond the captured depth is priced.
  4. **Portfolio and risk state**: `portfolio_state(risk.assess(...), RiskPolicy)`, the
     canonical risk report with the same headroom formulas. The engine does not keep its
     own ledger.
  5. **Deterministic optimizer**: an integer search over contracts.
     - The search runs on the concave pre-rounding problem (bisection on the discrete
       derivative). A local scan then decides with the exact cent-rounded cost; small
       counts are scanned exhaustively.
     - Joint (policy H): exhaustive search when the integer grid has at most 4,096 points.
       Above that it uses coordinate ascent under the shared cluster budget, which is a
       **heuristic**: it converges on this concave objective in the tested cases, but it is
       not proven to find the integer optimum.
     - **The Kelly fraction applies before limits.** A fractional policy takes floor(fraction
       x the optimum of the problem whose caps and shared budget are divided by the
       fraction), then re-imposes them. So 1/2 Kelly under a budget B is min(1/2 Kelly, B),
       whether sized jointly or alone. The first version applied the fraction after the
       budget, which halved the joint policy's capped size (review of PR #60; tested).
     - Policies A-H are frozen, versioned `SizingPolicyV2` values.
  6. **Hard caps after the optimizer**, each recorded and the binding one named:
     - liquidity, position, event, cluster, portfolio;
     - the reserve floor;
     - daily, weekly and drawdown headroom;
     - the `risk.assess` risk budget;
     - STARTER_MAX_7D_V1.
     Clusters whose dependence is unknown share one cluster cap. No correlation coefficient
     is ever invented.
  7. **Explanation**: fixed template text over the computed fields, labelled RESEARCH
     SIZING. No LLM touches a number.
- Output: `SizingRecommendation` with the directive's fields plus a canonical input hash and
  output hash.
  - Money is Decimal, cent-quantized. Costs round up and limits round down.
  - Fail-closed verdicts, in precedence order:
    - UNSUPPORTED: a non-binary payoff, a market that is not OPEN, unresolved settlement
      rules (as `opportunity.evaluate` refuses them), or refused fees;
    - STALE_DATA: a missing, stale or malformed book, a missing model or model version, or a
      missing or stale risk state;
    - RISK_LIMIT, CAPITAL_HORIZON, UNCERTAINTY_TOO_HIGH, ZERO_EDGE;
    - then LIQUIDITY_LIMIT or RISK_LIMIT when depth, tradable cash or a cap allows no
      contract.
  - A missing input never yields SIZE. Cluster exposure that cannot be mapped to states is
    assumed lost in every state.
- `src/edge_lab/sizing_eval.py` and `edge-lab sizing simulate|replay|policies` hold the
  seeded simulation study. Its results are SIMULATION evidence, recorded in
  `experiments/sizing_v2/`.
- **Operational use is gated.** v2 may influence shadow fills only after the PROPOSED
  prospective sizing experiment in `experiments/sizing_v2/PROPOSED_PREREGISTRATION.md` is
  registered, frozen and passes. That needs its own owner-authorized change.
- **ML is deferred.** There is one prospective day and no out-of-sample trading sample. The
  simple, statistically justified uncertainty model is the Dirichlet/Beta posterior. See
  `docs/research/STAKE_SIZING_V2.md` §6 for the data volume that would justify revisiting.
- **No UI change in this ADR.** The backend contract comes first (directive 3J). A later,
  read-only Terminal v1 panel labelled RESEARCH SIZING must reuse the design system and
  implement every state (real, empty, stale, error, unsupported, blocked).

**Tradeoffs.**
- Two sizing modules exist. That is deliberate: one is frozen and operational, the other a
  research challenger. `sizing_v2` imports neither `sizing.py` nor `exp001_shadow.py`, and
  a test enforces it.
- The robust set is only as good as its `n_eff`. With little evidence the set is wide, and
  robust policies bet almost nothing. That is the honest answer, not a defect. The
  simulation measures what it costs.
- Probabilities in the optimizer are floats because logarithms need them. Money comes from
  exact Decimal cost curves, and the recommendation re-prices the chosen count exactly.
- The optimizer is exact on the pre-rounding problem and within cent rounding (at most $0.01
  per take) of the exact one. Tests bound the gap.
- The drawdown constraint of Busseti, Ryu and Boyd bounds drawdown under the stated
  probabilities. It cannot protect against a wrong model, and the simulation's
  negative-edge scenario shows this. Only calibration evidence can.

**Reconsider if:**
- a registered prospective sizing experiment passes or fails;
- the out-of-sample settled sample reaches the ML threshold in the research document;
- a non-binary payoff becomes supported (Phase 5 split cancellation). Its payout vector
  plugs into the same state model;
- the simulation's conclusions change under a materially different world model.
