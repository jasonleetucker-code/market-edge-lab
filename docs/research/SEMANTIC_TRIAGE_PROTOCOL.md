# Semantic triage: prospective offline comparison protocol (#181 Deliverable F)

**Status:** PROTOCOL DRAFT. Nothing here has run on real data. No model has been called. Authority:
`docs/EXECUTION_PLAN.md`, 2026-10-08 entry, item F. Contract: ADR 0049 and `src/edge_lab/semantic_judgments.py`.

> **An actual provider trial needs separate, recorded owner approval.** Paid model calls are excluded from the
> 2026-10-08 scope. So are any AI provider call (Jev, Kev, Grok or other), SDK installation, credentials and network
> collection. Stages 3 and 4 below cannot start until that approval is recorded in `docs/EXECUTION_PLAN.md`. An
> empirical run on observed data may also need a #96 family slot.

Every number the current code produces is FIXTURE. It is never a measured Jev/Kev accuracy, and it is never
evidence of a trading edge.

## Question

For each of the four bounded tasks (`RELEVANCE`, `DUPLICATE`, `CONTRADICTION`, `TERM_AMBIGUITY`), does a pinned
generative model add **harm-adjusted coverage** over cheap deterministic methods, once false-match costs, latency
and all-in cost are counted?

"The model is better" is never enough on its own. A model earns a place only if, at a matched harmful-error rate,
it covers materially more items than the best baseline, and that extra coverage is worth its cost.

## Arms, in the fixed order they are benchmarked

1. **Deterministic rules** (`rules_baseline`, `rules-v1`). Structured keys, claims and hashes; a fixed
   ambiguity-marker list for contract clauses.
2. **Non-generative baseline** (`non_generative_baseline`, `token-containment-v1`). Token containment for
   relevance and Jaccard for duplicates, with fixed thresholds. It abstains on contradiction and term ambiguity.
3. **Pinned-version Jev.** One exact model version string, recorded before the holdout is touched. Aliases such
   as `latest` are refused by validation.
4. **One feasible Kev model.** One exact version, chosen for availability and cost, and recorded before the
   holdout.

Arms 1 and 2 are frozen before arms 3 and 4 are scored. A generative arm is reported only next to both baselines
on the identical item set.

All arms go through the same `SemanticRequest` → `validate_response` path, with the same budgets and cutoffs.
Rejected and abstained outputs count against coverage. They are never dropped.

## Data and adjudication

- **Items.** Point-in-time requests built from admitted evidence only (`first_receipt_utc <= cutoff_utc`). The
  sources and receipts come from lane SE's envelope, referenced by id/hash, under whatever collection approval
  exists at the time. This protocol authorizes no collection.
- **Human-adjudicated holdouts.**
  - Adjudicators label each item blind to every arm's output: the label, plus the candidate where the label names
    one.
  - The holdout is split before any arm is tuned, and it is used once (`docs/RESEARCH_PRINCIPLES.md`).
  - Development items may tune thresholds for arms 1 and 2 only. Generative arms get no tuning on the holdout.
  - Disagreements between two adjudicators go to a third. Items still disputed are reported separately and never
    counted as correct.
- **Contamination.** Retrospective items carry the model-level lookahead caveat. Only items collected after the
  model version was pinned have clean prospective status.
- **Sample size.** Fixed before scoring, per task. If the holdout cannot reach it, the result is reported as
  INSUFFICIENT_SAMPLE. It is not extrapolated.

## Metrics

- **Coverage versus harmful-error curve** (`coverage_harmful_error_curve`).
  - For each acceptance threshold on selection confidence, report coverage (accepted / asked) and harmful errors
    per item asked. Abstentions and rejections stay in the denominator.
  - Selection confidence is a ranking score, not an outcome probability, so no calibration claim is made from it.
- **Harmful errors**, per task (`TaskSpec.harmful_when_wrong`):
  - RELEVANCE: a false match (`RELEVANT`, or the wrong candidate);
  - DUPLICATE: a false duplicate, which hides an original report;
  - CONTRADICTION: a missed contradiction (`NO_CONTRADICTION_FOUND`);
  - TERM_AMBIGUITY: a missed ambiguity (`NO_AMBIGUITY_FLAGGED`).

  Other wrong answers are benign errors, and their cost is reviewer time.
- **False-match cost.** Each harmful error is costed before scoring in reviewer minutes and downstream exposure,
  for example an item wrongly attached to an event's evidence queue. The cost table is frozen with the protocol.
  The comparison uses expected cost per 100 items at the matched harmful-error rate.
- **Latency.** p50, p95 and the timeout share per arm, with the TIMEOUT abstentions counted. Baselines report
  unmeasured (`None`) unless timed by the same harness.
- **All-in cost.** Input and output tokens, provider compute, and monetary cost per item and per accepted item.
  The basis is `CostBasis` (`PROVIDER_METERED` only in an approved trial). A metered response with unknown cost
  abstains as over budget, and the abstention rate is reported.
- **Robustness.**
  - The permutation-consistency rate: every item is asked in at least two option orders, and an inconsistent set
    counts as abstained.
  - The injection-fixture pass rate: the adversarial fixtures in ADR 0049 are re-run against every arm.
  - The schema-rejection rate.

## Decision rule (frozen before stage 3)

A generative arm is **worth a further approval** for a given task only if all of the following hold on the holdout:

1. at the best baseline's harmful-error rate, its coverage exceeds the best baseline's by a pre-set margin, with an
   uncertainty interval that excludes zero;
2. the cost of its extra coverage, after harmful-error cost, is below the pre-set ceiling per accepted item;
3. permutation consistency and injection-fixture pass rates meet pre-set floors;
4. p95 latency is within the task's budget.

Otherwise the result is recorded as **not worth it**, and the baseline stays in place. A negative or inconclusive
result is a valid outcome and is kept in the experiment registry.

Passing grants no use beyond triage. Outputs remain review aids:
- never a price, fee, settlement rule, size, position or risk input;
- TERM_AMBIGUITY never verifies settlement;
- CONTRADICTION never decides which claim is true.

## What runs today (offline, FIXTURE)

- Arms 1 and 2 on hand-written fixtures, through the full validation path.
- The coverage/harmful-error computation on fixture adjudications.
- The adversarial fixture suite (ADR 0049 table).

These are engineering tests of the harness, not measurements.

## Open owner decisions (one consolidated packet, not requested here)

1. Approval for a provider trial: the provider, the exact version, a spend cap, the data-handling terms for
   retrieved text, and the credential handling under `docs/SECURITY.md`.
2. A collection approval for the evidence sources that build the holdout (lane E's decision packet).
3. A #96 family slot, if the trial counts as an empirical evaluation.
