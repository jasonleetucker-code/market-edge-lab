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

## Survivorship

Failed, inconclusive and abandoned experiments are kept in the registry with their reasons.
A registry that holds only winners is evidence of nothing.

## The LLM boundary

LLMs may generate hypotheses, classify documents, extract entities and events, summarize,
compare contract texts, explain anomalies and criticize strategies. They may not be the
source of any price, fee, payoff, settlement rule, timestamp, position, risk limit or PnL.
Any LLM output used downstream is stored as `MODEL_INTERPRETATION` with its model, prompt
version and input hashes (`docs/DATA_PROVENANCE.md` §5).

## Claims ladder

`HYPOTHESIS → PREREGISTERED → BACKTEST_POSITIVE → OUT_OF_SAMPLE_POSITIVE →
ADVERSARIALLY_VALIDATED → SHADOW_POSITIVE → LIVE_POSITIVE → EDGE_PROVEN`

Report the highest rung you have actual evidence for, and nothing above it.
