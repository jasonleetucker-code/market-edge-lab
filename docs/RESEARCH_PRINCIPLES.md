# Research Principles

This file is how we avoid fooling ourselves. It applies to every experiment in `experiments/`.

## Point-in-time correctness

- A backtest may use only information whose **receipt time** (`fetched_at_utc`) or
  verifiable publication time falls before the decision time.
- Revised data is not the data that was available at the time. Use vintages (for example,
  ALFRED `realtime_start`/`realtime_end`) or our own snapshots. Never use today's revised
  history.
- Settlement values can be revised as well. Record which publication settled the contract.

## Settlement comes first

- Before modeling, capture the contract rules as evidence. That includes the source, station,
  window, timezone, rounding, revision policy and void/missing provisions.
- Reproduce historical settlements from the named source. A market's title, a third-party
  page or a blog post is not settlement documentation.
- An example from 2026-09-22: web sources said KXHIGHNY settles on the NWS CLI report. The
  live rules we captured name The Weather Company. **Primary evidence wins.**

## Costs and fills

- Fees, spreads and minimum ticks come from primary sources, such as the exchange's fee
  schedule captured with a date. They are never taken from memory or estimated by an LLM.
- A historical mid-price is not an executable fill. Simulate against the captured order book:
  cross the spread, respect the available size, and model queue position and latency
  conservatively.
- Every result is reported **after** costs. An edge that exists only before costs is not an edge.

## Statistics and multiple testing

- **Preregister**: write down the hypothesis, decision rule, periods, metrics and pass/fail
  criteria before looking at the test data (`status = "PREREGISTERED"`).
- Count every variant you try. The number of trials is part of the result. Correct for it,
  for example with a deflated Sharpe ratio or a holdout reserved for the final decision.
- Hold out a test period that is used **once**. Touching it again makes it validation data.
- Prefer calibration metrics (Brier score, log loss, reliability curves) for probability
  models. Keep the number of settled contracts visible. Small samples do not support strong
  claims.
- Do not run large strategy searches, because they manufacture false edges.

## Economics first (#96, 2026-09-25)

A statistically real effect that cannot earn meaningful money after costs, at a fillable size,
with finite capital, is not worth optimizing. Screen the economics **before** expensive model
work (`edge_lab.research_economics`):
- **Count distinct opportunity episodes, not snapshots.** One discrepancy observed repeatedly
  until it reprices is one opportunity. The episode definition (start threshold, end/merge gap,
  minimum size) is frozen in the protocol before any outcome is viewed.
- **Net edge per unit is after variable costs**, and fees enter once. Never subtract a fee or a
  loss again, and never multiply bankroll × executable size × turnover.
- **Observed depth is a ceiling, not a fill.** Report a conservative bound (fill at detection)
  and a less-conservative bound (the best single observation), never a sum.
- **Replay chronologically with finite capital:** per venue, with a reserve, settlement release,
  and one shared pool across simultaneous strategies. Report return on deployed capital and
  return on total capital separately, with capital-days and idle cash.
- **Keep three things separate:** variable economics, fixed cash costs, and owner hours at a
  chosen hourly opportunity cost. The annual figure is a *scenario* under a stated stationarity
  assumption, produced only when the protocol's minimum episode count is met. A few observations
  are never annualized into income.
- **Label every input** OBSERVED, ESTIMATED, OWNER_INPUT or UNKNOWN. Unknown probability means no
  estimated EV. INSUFFICIENT_EVIDENCE and ECONOMICALLY_UNVIABLE are research results, not code
  failures. No money amount in a scenario is an approved bankroll.

## Consumed evidence

- Every research use of a dataset is recorded in the experiment's append-only
  `evidence_use.jsonl` (`edge_lab.research_evidence`). A record holds the role, the outcome window,
  the actor and tool, the code, model and prompt versions, and the action type. It also says
  whether features, labels or results were seen, and whether the use influenced tuning.
- **A holdout is identified by its outcome window as well as its hash.** Copying, renaming or
  re-hashing the same outcomes never restores "untouched". Evaluating a holdout consumes it. A
  second look is validation, not a test.
- Access from before a log existed is **UNKNOWN**, never certified untouched. Only a prospective
  window that starts after the log can be claimed untouched.
- A log records declared access. It cannot prove that nobody looked outside it, so holdout
  protection remains procedural as well.
- A protocol may list `prohibited_inputs`, and access to them is refused at record time. For
  example, Family B never touches EXP-001 forecasts, outcomes or the ledger.

## Attrition

Report potential events, markets, scheduled horizons, snapshots and opportunities as **separate
denominators** (`research_evidence.attrition_report`). Keep every raw reason. A deterministic
primary-reason order makes the waterfall reconcile without double counting.
- Zero is not missing: a level that was not enumerated is unknown.
- No signal is not a failed collection, and no fill is not "no opportunity".
- A future target is PENDING until its deadline, never MISSED early.

## Typed probabilities and dependence

- **Say what a probability means.** It may be a physical estimate, a sportsbook consensus, a
  market-implied price, a risk-neutral option quantity, or a deterministic replication/payoff
  bound. These are not interchangeable. The economic relation between two contracts (equivalent,
  related, bound) is a separate label. A two-way de-vig encodes the book's own tie/void rules and
  is not automatically an unconditional binary probability.
- **Count independent units, not rows.** Books, both sides of a game, horizons and snapshots of
  one game are one cluster (Family A also clusters by NFL week or slate). The brackets and
  captures of one KXHIGHNY event day are one cluster (Family B). Uncertainty is computed on
  clusters. Source-family links between books are UNKNOWN unless established; independence is
  never assumed.

## Preregistered futility and research budgets

Every new experiment carries a `protocol.toml` sidecar (`experiments/README.md`). It holds the
family slot, the mechanism, the universe and clusters, the endpoints, the cutoffs, the data roles,
the variants and multiple-testing plan, the cost/fill and size/capital assumptions, the untouched
future window, the cash and owner-hour budget, the review date, the futility and stop rules, the
minimum useful economic effect, and the frozen episode definition.
- **DRAFT may say UNKNOWN or MISSING_OWNER_INPUT.** Never invent a threshold, sample size, source
  independence or annual opportunity count to pass validation.
- **PREREGISTERED requires every decision field settled,** with a power/cost rationale, before
  outcomes are viewed.
- At most two new families are ACTIVE beside protected EXP-001. The verdicts are ACCESS_BLOCKED,
  ECONOMICALLY_UNVIABLE, STATISTICAL_FUTILITY, OPERATIONALLY_UNUSABLE, BUDGET_EXHAUSTED,
  INSUFFICIENT_EVIDENCE and CONTINUE.
- An extension names the missing observation and its marginal cost. Insufficient evidence is not
  "no edge", and indefinite extension is not free.

## Survivorship

Failed, inconclusive and abandoned experiments are kept in the registry with their reasons.
A registry that holds only winners is evidence of nothing.

## The LLM boundary

LLMs may generate hypotheses, classify documents, extract entities and events, summarize,
compare contract texts, explain anomalies and criticize strategies. They may not be the
source of any price, fee, payoff, settlement rule, timestamp, position, risk limit or PnL.
Any LLM output used downstream is stored as `MODEL_INTERPRETATION` with its model, prompt
version and input hashes (`docs/DATA_PROVENANCE.md` §5).

**Model-level lookahead.** An LLM's training data may contain the later outcome of a historical
document, so running a model over old documents is not proof that it was ignorant of what came
next. Restricting the prompt to a time or removing names does not remove that knowledge.
- Retrospective LLM-derived results carry a contamination caveat.
- Record the model id and version, the prompt hash, the source hashes, and the evaluation time.
- Only prospective evaluation with a fixed configuration has clean evidentiary status.

## Claims ladder

`HYPOTHESIS → PREREGISTERED → BACKTEST_POSITIVE → OUT_OF_SAMPLE_POSITIVE →
ADVERSARIALLY_VALIDATED → SHADOW_POSITIVE → LIVE_POSITIVE → EDGE_PROVEN`

Report the highest rung you have actual evidence for, and nothing above it.
