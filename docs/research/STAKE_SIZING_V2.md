# Stake sizing v2: literature review, architecture and simulation evidence

Status: research record for the 2026-09-24 owner directive, Phase 3
(`docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`, owner correction 2).
Decision: `docs/decisions/0026-stake-sizing-v2-challenger.md`. Code: `src/edge_lab/sizing_v2.py`
(engine) and `src/edge_lab/sizing_eval.py` (study). Results: `experiments/sizing_v2/`.

**Evidence level.**
- Everything quantitative here is **SIMULATION evidence** from synthetic markets. It is not
  a backtest and not an edge claim, and it gives no authority to change a shadow fill.
- The operational shadow account keeps `EXP-001-fixed-1-v1`. The frozen EXP-001 research
  account and its preregistration are untouched.

## 1. The problem, stated in contract terms

A position is some quantity C of one binary contract that pays $1 if its outcome occurs.
The outcome belongs to a cluster of K mutually exclusive, exhaustive states, for example
KXHIGHNY's temperature brackets for one day, exactly one of which settles YES.

- **Payoff.** A YES on bracket k pays in state k only. A NO on bracket k pays in every other
  state. A binary market is the case K = 2.
- **Cost.** Buying C contracts costs cost(C): walk the captured ask ladder, add the venue's
  fee for each take, then apply the venue's cash rounding. On Kalshi the fee is
  `ceil(0.07 * C * P * (1 - P))` to $0.000001, and cash is aligned to the cent.
  - cost(C) is convex, because each extra contract comes from the same level or a worse one.
  - It is only defined up to the captured depth.
  - Wealth in state s after settlement is W_s(C) = W_s^0 + C * 1[pays in s] - cost(C).
- **Probability.** A model gives a probability vector p over the states. Its uncertainty is
  a set P of admissible vectors.
- **Growth.** The Kelly objective is E_p[log W'(C) / W]. The robust objective is
  min over p in P of E_p[log W'(C) / W].

The robust objective is linear in p. Its minimum over a polytope P is therefore attained at
an extreme point of P, and which one depends on the payoff:

- for a YES, the adverse point is low P(YES);
- for a NO, it is high P(YES);
- for a multi-state position, it moves mass onto the states the position loses in.

Owner correction 2 requires this point to be derived, not assumed. The engine derives it
(`BoxSimplexSet.worst`), and tests check it against every vertex and against a dense
interior grid.

## 2. Literature review

Each entry gives the citation, the method, its assumptions, where it applies, and where it
fails for $1 binary prediction-market contracts and sportsbook odds. The citations were
verified on 2026-09-24 against publisher pages, DOIs or arXiv. Discrepancies are noted.

### 2.1 Kelly (1956): the growth-optimal criterion

- **Citation.** Kelly, J. L., Jr. "A New Interpretation of Information Rate." *Bell System
  Technical Journal* 35(4): 917–926, 1956. doi:10.1002/j.1538-7305.1956.tb03809.x.
  (Some later papers misattribute it to *IRE Trans. Information Theory*; the BSTJ venue is
  the verified one.)
- **Method.** A gambler with a noisy private signal maximizes the expected logarithm of
  wealth. The maximal growth rate equals the information rate of the channel. With odds,
  the optimal fraction on a single binary bet bought at all-in price c and paying 1 is
  f* = (p - c) / (1 - c). The paper also treats a race with several horses and a track take.
- **Assumptions.** Known probabilities, repeated independent bets, divisible stakes,
  reinvestment, fixed linear odds and a long horizon.
- **Applies here** as the unconstrained growth benchmark (policy C, and the closed-form test
  in `tests/test_sizing_v2.py`).
- **Fails here.**
  - p is estimated, not known.
  - Contracts are whole units.
  - Depth makes the price rise with size, so f* no longer has a closed form.
  - The Kalshi fee depends on P(1 - P) and is rounded.
  - Capital is locked until settlement.
  - The horizon is short: about one KXHIGHNY decision a day.

### 2.2 Breiman (1961): asymptotic optimality

- **Citation.** Breiman, L. "Optimal Gambling Systems for Favorable Games." *Proc. Fourth
  Berkeley Symposium on Mathematical Statistics and Probability*, Vol. I: 65–78, 1961.
- **Method.** Over repeated favorable games, the log-optimal strategy asymptotically
  dominates every essentially different strategy in wealth. It also minimizes the expected
  time to reach a large target.
- **Applies here.** It justifies log growth as the benchmark objective.
- **Fails here.** The results are asymptotic and say nothing about finite-horizon drawdowns.
  A few hundred settlements a year is not the asymptotic regime.

### 2.3 Thorp (2006): Kelly in practice

- **Citation.** Thorp, E. O. "The Kelly Criterion in Blackjack, Sports Betting, and the Stock
  Market." Ch. 15 in *Handbook of Asset and Liability Management*, Vol. 1 (S. A. Zenios and
  W. T. Ziemba, eds.), North-Holland/Elsevier, pp. 385–428, 2006.
- **Method.** Derives Kelly for even-money and general-odds bets, and simultaneous and
  sequential bets. Gives the continuous approximation f = mu / sigma^2. Explains why
  overbetting is costly: at twice Kelly, growth falls to about zero. Discusses fractional
  Kelly as the practical response to uncertain edges, including in sports betting.
- **Applies here.** Fractional Kelly (policies D and E), and overbetting as the main hazard.
- **Fails here.**
  - The Gaussian or continuous approximation is poor for binaries at extreme prices.
  - Simultaneous sports bets are treated as independent. Same-event brackets are
    mutually exclusive, not independent.

### 2.4 MacLean, Thorp and Ziemba (2010, 2011): good and bad properties

- **Citation.**
  - MacLean, L. C., Thorp, E. O., Ziemba, W. T. "Long-Term Capital Growth: The Good and Bad
    Properties of the Kelly and Fractional Kelly Capital Growth Criteria." *Quantitative
    Finance* 10(7): 681–687, 2010. doi:10.1080/14697688.2010.506108.
  - The book they edited: *The Kelly Capital Growth Investment Criterion: Theory and
    Practice*, World Scientific Handbook in Financial Economics, Vol. 3, 2011.
- **Method.** The good properties: maximal asymptotic growth, myopia, and a shortest
  expected time to goals. The bad: very high short- and medium-run volatility, a sizeable
  probability of large drawdowns, and a severe penalty for overbetting. Fractional Kelly
  trades growth for security, roughly as a mean-variance frontier.
- **Applies here.** The simulation measures exactly this tradeoff: growth against
  drawdown, lower-tail wealth and ruin.
- **Fails here.** The quantitative tradeoffs are derived for continuous or lognormal
  settings with known parameters. Our bets are discrete binaries with estimated
  probabilities.

### 2.5 Baker and McHale (2013): parameter uncertainty and shrinkage

- **Citation.** Baker, R. D., McHale, I. G. "Optimal Betting Under Parameter Uncertainty:
  Improving the Kelly Criterion." *Decision Analysis* 10(3): 189–199, 2013.
  doi:10.1287/deca.2013.0271.
- **Method.** The plug-in Kelly stake, computed from an estimated probability, overbets on
  average because growth is concave in the stake. The paper derives an optimal shrinkage of
  the Kelly stake from the sampling distribution of the estimate (bootstrap or Bayesian),
  and shows out-of-sample gains on simulated data and tennis betting.
- **Applies here.** The size reduction should be driven by the estimation error of p (our
  `n_eff`), not by an arbitrary fraction.
- **Fails here.** It assumes the estimator is unbiased with a known sampling distribution.
  It does not cover model misspecification or systematic overconfidence, which our
  overconfidence scenario shows can dominate.

### 2.6 Busseti, Ryu and Boyd (2016): risk-constrained Kelly

- **Citation.** Busseti, E., Ryu, E. K., Boyd, S. "Risk-Constrained Kelly Gambling."
  *The Journal of Investing* 25(3): 118–134, 2016. doi:10.3905/joi.2016.25.3.118;
  arXiv:1603.06183.
- **Method.** Maximize E log(r^T b) subject to E[(r^T b)^(-lambda)] <= 1. With
  lambda = log(beta) / log(alpha), the constraint guarantees Prob(W_min < alpha) < beta
  (their eq. 6; verified from the paper). The problem is convex over finite outcome sets.
- **Applies here** directly: our outcome sets are finite, and the constraint is evaluated
  exactly over the K states (policy G; alpha 0.7, beta 0.1, so lambda is about 6.46).
  - The proof is a supermartingale argument on W_t^(-lambda).
  - The bound therefore still holds when bets differ from round to round, provided each
    round satisfies the constraint under the *true* distribution.
- **Fails here.**
  - Under a wrong model the guarantee is void. The negative-edge scenario (§7) shows the
    nominal-constraint policy losing heavily.
  - Evaluating the constraint at the worst admissible vector (`robust_constraint`) restores
    the guarantee only if the truth is inside the set.

### 2.7 Sun and Boyd (2018): distributionally robust Kelly

- **Citation.** Sun, Q., Boyd, S. "Distributional Robust Kelly Gambling: Optimal Strategy
  under Uncertainty in the Long-Run." arXiv:1812.10371 (v3, 2021). No journal version was
  found; treat it as a preprint.
- **Method.** Maximize the worst-case expected log growth over a set of distributions. The
  sets covered include polyhedral, ellipsoidal and divergence-ball sets. The problem stays
  convex, and the strategy is asymptotically optimal against the worst-case sequence.
- **Applies here.** This is our robust objective (policy F and the robust parts of G and H).
  Our set is a polytope: per-state credible bounds intersected with the simplex. The inner
  minimum is therefore exact at a vertex.
- **Fails here.** Robustness is only as good as the set.
  - A set that is too narrow gives false comfort.
  - One that is too wide stops all betting (UNCERTAINTY_TOO_HIGH).
  - Calibrating the set needs out-of-sample evidence we do not yet have.

### 2.8 Rockafellar and Uryasev (2000): CVaR

- **Citation.** Rockafellar, R. T., Uryasev, S. "Optimization of Conditional Value-at-Risk."
  *Journal of Risk* 2(3): 21–41, 2000. (One index gives 21–42; most sources give 21–41.)
- **Method.** CVaR is the mean loss beyond VaR. It is coherent, and it can be minimized
  directly, without computing VaR, through an auxiliary-variable convex program that
  becomes a linear program on scenarios.
- **Applies here.** The engine offers a nominal CVaR cap (`cvar_level`, `cvar_max_loss`),
  and the study reports CVaR 5% of terminal wealth.
- **Fails here.** For a single binary position with P(loss) >= alpha, CVaR_alpha is the whole
  cost, so it collapses to a max-loss cap that the hard caps already enforce. It adds
  information only for portfolios across several states or clusters.

### 2.9 Gneiting and Raftery (2007): proper scoring rules

- **Citation.** Gneiting, T., Raftery, A. E. "Strictly Proper Scoring Rules, Prediction, and
  Estimation." *Journal of the American Statistical Association* 102(477): 359–378, 2007.
- **Method.** A strictly proper score, such as the log score or Brier score, is optimized in
  expectation only by the true distribution. It rewards calibration and sharpness.
- **Applies here.**
  - Kelly growth betting against market odds is the log score of the bettor's
    probabilities minus the log score of the market's. The expected gain is a KL
    divergence. So the evidence that should set `n_eff` is out-of-sample log-score
    evidence against the market.
  - EXP-001 Stage A measured the log score against climatology, not against the market.
- **Fails here.** A good score against a naive baseline (EXP-001 Stage A: +1.25 nats per day
  against climatology) is **not** an edge against executable prices. A score does not see
  depth, fees or fills.

### 2.10 Almgren and Chriss (2000/2001): execution cost

- **Citation.** Almgren, R., Chriss, N. "Optimal Execution of Portfolio Transactions."
  *Journal of Risk* 3(2): 5–39 (the working paper circulated in 2000; the issue is dated
  2000/2001).
- **Method.** Schedule a large trade to trade off market-impact cost, both temporary and
  permanent linear impact, against price risk. The result is an efficient frontier of
  execution trajectories.
- **Applies here.** Cost rises with size, so the sizing optimizer must use the marginal cost,
  not the top-of-book price.
- **Fails here.** We do not trade continuously in liquid assets. Books are thin and
  discrete, and we take liquidity in one sweep. The captured ladder gives the exact cost of
  each size (`walk_ladder`), with no impact model to estimate. Queue and latency risk
  belong to the fill policy. Refills and moves after our capture are unknown, so a
  simulation "exec shock" stands in for them.

### 2.11 Kyle (1985): informed trading and adverse selection

- **Citation.** Kyle, A. S. "Continuous Auctions and Insider Trading." *Econometrica* 53(6):
  1315–1335, 1985 (some indexes give 1336).
- **Method.** An informed trader, noise traders and a competitive market maker. Price impact
  is linear in order flow, and information is gradually impounded into the price.
- **Applies here.** It is a warning. In thin markets our fills happen partly because other
  traders let them happen, so fills are adversely selected, and trading moves the book. The
  study's unseen execution-cost shock is the stand-in.
- **Fails here.** The model assumes a risk-neutral dealer and Gaussian values. Prediction
  markets are discrete limit-order books with fees and ticks.

### 2.12 Joint Kelly for mutually exclusive outcomes (portfolio Kelly)

- **Citation.**
  - Kelly (1956), the horse-race section.
  - Smoczynski, P., Tomkins, D. "An Explicit Solution to the Problem of Optimizing the
    Allocations of a Bettor's Wealth When Wagering on Horse Races." *Mathematical
    Scientist* 35: 10–17, 2010.
  - Whitrow, C. "Algorithms for Optimal Allocation of Bets on Many Simultaneous Events."
    *JRSS Series C* 56(5): 607–623, 2007. doi:10.1111/j.1467-9876.2007.00594.x.
- **Method.** When exactly one of several outcomes occurs, the optimal bets are chosen
  jointly. Only outcomes whose probability-to-price ratio exceeds a common threshold are
  bet, and the set is found from KKT conditions (the explicit solution). Whitrow gives
  numerical algorithms for many simultaneous events.
- **Applies here.** Temperature brackets form a horse race. Sizing each bracket as if
  independent over-bets the cluster. Policy H optimizes the cluster jointly, and the
  single-candidate policies size each candidate conditional on what is already held.
- **Fails here.** The closed forms assume linear odds without depth or fees. Our costs are
  convex and rounded, so the engine searches numerically (exhaustively on small grids,
  otherwise by coordinate ascent) and tests check the two against each other. The same
  outcome listed on two venues is a duplicate cluster. Nothing in the price data reveals
  that, so an unknown dependence gets a shared cap (§5).

### 2.13 Prediction-market prices and their biases

- **Citation.**
  - Wolfers, J., Zitzewitz, E. "Prediction Markets." *Journal of Economic Perspectives*
    18(2): 107–126, 2004.
  - Snowberg, E., Wolfers, J. "Explaining the Favorite–Long Shot Bias: Is It Risk-Love or
    Misperceptions?" *Journal of Political Economy* 118(4): 723–746, 2010.
- **Method.** Prices approximately aggregate information into probabilities. There are
  systematic distortions: the favorite-longshot bias, which Snowberg and Wolfers attribute
  mainly to misperceived probabilities.
- **Applies here.** The market-implied probability is the benchmark our model must beat. A
  miscalibrated market can create apparent edges. The first draft of our simulation had
  one by accident (§7.1), and the final world model makes the market calibrated by
  construction, so that any edge comes only from the model.
- **Fails here.** Much of the evidence comes from pari-mutuel horse racing. It may not
  transfer to CFTC-regulated exchange binaries with a quadratic fee.

## 3. What the literature implies for us

1. Log growth is the right *benchmark*, not the right *policy*. With estimated
   probabilities, full Kelly overbets (Baker and McHale; Thorp; MacLean, Thorp and Ziemba).
2. The size reduction should come from the uncertainty about p: a robust set or posterior
   shrinkage (Sun and Boyd; Baker and McHale). Fixed fractions are a cruder stand-in.
3. Drawdown control can be made explicit and exact on finite outcome sets (Busseti, Ryu and
   Boyd), but only under the stated probabilities.
4. Same-event outcomes must be sized jointly (Kelly; Smoczynski and Tomkins; Whitrow).
5. Execution cost is a function of size and comes from the book, not from a mid-price
   (Almgren and Chriss; Kyle).
6. The input that decides everything is out-of-sample evidence that the model beats the
   market's probabilities after costs (Gneiting and Raftery; Wolfers and Zitzewitz). No
   sizing rule creates an edge.

## 4. Chosen architecture

See ADR 0026 for the full decision. In short:

```
probability model (input)  ->  uncertainty set (polytope of admissible vectors)
executable ladder + fee schedule + claim allowance  ->  exact convex cost curve
risk.assess report + RiskPolicy  ->  PortfolioState (capacity, exposures, stops)
        \______________________________________________/
                 deterministic integer optimizer (policy A-H)
                 -> hard caps (liquidity, position, event, cluster incl. unknown-dependence,
                    portfolio, reserve, loss/drawdown headroom, risk budget, 7-day horizon)
                 -> SizingRecommendation (+ template explanation, input/output hashes)
```

- Nothing maps features to dollars. ML, when justified (§6), may estimate a probability,
  the width of the uncertainty set, a fill probability or slippage. The dollar amount always
  comes from the optimizer and the caps.
- The engine is `sizing_v2.py`. `sizing.py` is untouched and remains the operational path.

## 5. Correlation and clusters

- **Same cluster (mutually exclusive states).** The dependence is exact, since exactly one
  state wins, and it is modelled exactly in the state space. Joint optimization (H), or
  conditional sequential sizing (the other policies), covers it.
- **Different clusters with a known independent underlying.** These are sized separately,
  each under its own cluster cap.
- **Different clusters whose dependence is unknown.** Examples: the same event on two
  venues, or two cities' temperatures in one heat wave. **No correlation coefficient is
  invented.**
  - The caller lists such clusters in `SizingRequest.correlated_clusters`.
  - Their open exposure then counts against this cluster's cap, so they share one
    conservative cap.
  - Exposure the caller cannot map to states is assumed lost in every state.

## 6. ML and calibration: deferred, with the reason

- **Current evidence.**
  - Prospective trading evidence: **one** valid Stage B day, a handful of bracket outcomes
    with executable prices.
  - EXP-001 Gate 3/4: 3,551 days of forecasts and labels, but **no market prices**. Every
    row has `market_price_available=false`.
  - The Stage A test split (2025-01-01 to 2026-09-21) was opened once and is protected by the
    preregistration.
- **Why an ML calibration or uncertainty model is not justified now.**
  - A model mapping (features, market price) to a calibrated probability, or to the width of
    an uncertainty set, needs out-of-sample (model, price, outcome) triples.
  - Brackets within a day are one dependent draw, so the effective sample size is the number
    of decision days, not brackets.
  - With one day, any fitted model would be pure noise. It would also invite repeated
    optimization against the same few days, which RESEARCH_PRINCIPLES forbids.
- **What is used instead.** A Beta-binomial / Dirichlet posterior around the model's
  probability, with an effective sample size `n_eff` set from evidence (`dirichlet_box`), or
  per-state Wilson bounds. The method was chosen by a pre-declared simulation rule (§7.3).
  These are one- or two-parameter models with known coverage, compared against simple
  baselines.
- **When to revisit.**
  - The EXP-001 Stage B 180-valid-day look (about 180 days × about 6 brackets of
    point-in-time model, price and outcome records) supports at most a two-parameter
    recalibration: logistic or Platt scaling of the model against the market, fitted on the
    first half and tested once on the second.
  - A richer ML calibration or uncertainty model needs **at least 365 prospective valid
    decision days** (Stage B's final look) in a chronological 50/25/25 split, or pooled
    evidence across several independent domains.
  - Point-in-time features only; every variant counted; a Platt-scaling baseline to beat;
    no reuse of a test period.
  - Until then, ML stays DEFERRED.

## 7. Simulation study (SIMULATION evidence)

The results are filled in from `experiments/sizing_v2/results/` (§7.2 onwards).
