# Owner directive: Gate 3 point-in-time dataset + EXP-001 preregistration (2026-09-22)

Source: the owner's written instruction to the working agent session on 2026-09-22,
titled "MARKET-EDGE-LAB — GATE 3: POINT-IN-TIME DATASET + EXP-001 PREREGISTRATION". The
governing sections are recorded **verbatim** below.

## Order of work (verbatim)

> OWNER-INTAKE PROCESS CLEANUP ↓ DECISION TIME ↓ FORECAST AVAILABILITY RULES ↓ POINT-IN-TIME HISTORICAL DATASET ↓ DATA QUALITY / COVERAGE AUDIT ↓ DESCRIPTIVE FORECAST-vs-SETTLEMENT ANALYSIS ↓ EXPERIMENT DESIGN ↓ TRAIN / VALIDATION / TEST SPLIT ↓ COST / EXECUTION SPECIFICATION ↓ FREEZE PREREGISTRATION ↓ STOP
>
> Do NOT proceed into Gate 4 model fitting or profitability testing in this mission.

## Gate 3 acceptance criteria (verbatim)

> Gate 3 passes only when:
>
> 1. A fixed decision-time rule is documented.
> 2. Availability-time semantics are documented and enforced.
> 3. A legitimate free historical forecast source is selected and documented.
> 4. A deterministic point-in-time historical dataset is built.
> 5. Every row links to provenance/evidence.
> 6. Missing/excluded rows retain explicit reasons.
> 7. Dataset version/hash is reproducible.
> 8. A complete data-quality report exists.
> 9. Forecast-vs-settlement descriptive analysis is complete without strategy optimization.
> 10. A simple baseline model is fully specified but test performance has not been examined.
> 11. Chronological train/validation/test periods are fixed.
> 12. Fee model is fully specified.
> 13. Execution assumptions are fully specified.
> 14. Historical forecast validation and prospective trading validation are clearly separated.
> 15. Success/failure criteria are computable and consistent with available data.
> 16. A sample-size/power reality check is documented.
> 17. EXP-001 is "PREREGISTERED" and frozen.
> 18. The freeze/validator passes.
> 19. Full tests and CI pass on the exact final head.
> 20. Independent review finds no unresolved correctness blocker.
> 21. No trading/authentication capability has been introduced.
>
> If any item fails:
>
> do not mark Gate 3 complete.
>
> Do not activate Gate 4.

## PR / merge authority (verbatim)

> You have explicit owner authorization to merge this PR yourself once:
>
> - all Gate 3 acceptance criteria are actually satisfied;
> - CI is green on the exact final head;
> - the PR is mergeable;
> - independent review has no unresolved correctness blockers.
>
> If an external data limitation prevents full Gate 3 completion, do not pretend otherwise.

## After merge (verbatim)

> If and only if Gate 3 passed:
>
> update "docs/EXECUTION_PLAN.md" so Gate 4 becomes active.
>
> Gate 4 should then begin with:
>
> «Implement the frozen baseline model and evaluate it on the predeclared train/validation/test protocol.»
>
> Do not perform that evaluation in the Gate 3 PR.

## Things the owner said not to do (verbatim)

> Do not: place trades; create trading credentials; fund accounts; add order execution; begin sports work; build the dashboard; implement bankroll sizing; subscribe to paid data; launch generic internet scraping; schedule unattended collection without explicit owner approval; optimize for profitability; examine test-period model results; alter the experiment after seeing test performance; manufacture historical order books; treat forecast accuracy as proven trading profitability.

## Key design constraints (verbatim excerpts)

> The system must never use: a forecast issued after the decision time; a corrected/revised value unavailable then; a later archived version substituted for the original; future settlement information; future market information.

> Gate 2 already inspected settlement labels across years. That does not invalidate future testing by itself. What must remain untouched is: «model performance, strategy profitability and parameter selection on the designated test period.»

> Do not make “beats market-implied probabilities historically” a required historical criterion when historical market probabilities are unavailable.
