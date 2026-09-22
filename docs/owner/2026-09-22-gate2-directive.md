# Owner directive: Gate 2 settlement validation (2026-09-22)

Source: the owner's written instruction to the working agent session (Claude Code) on
2026-09-22, titled "MARKET-EDGE-LAB — GATE 2 SETTLEMENT VALIDATION". The sections that
govern acceptance, merge authority and the gate transition are recorded **verbatim** below,
so the conditions can be checked from the repository alone (`AI_INSTRUCTIONS.md`: no
private instruction forks).

## Gate 2 acceptance criteria (verbatim)

> Gate 2 passes only when all of the following are true:
>
> 1. Official contract terms are captured and versioned as immutable evidence.
> 2. The applicable settlement source hierarchy is documented.
> 3. Observation window, location/station, timezone, precision, rounding, revisions and void/missing rules are documented from primary evidence.
> 4. At least 30 historical KXHIGHNY daily settlements are evaluated.
> 5. The deterministic parser reproduces their outcomes with zero unexplained mismatches.
> 6. TWC-vs-NWS or Kalshi-settlement-value-vs-NWS differences are measured rather than assumed.
> 7. Kalshi market pagination is complete.
> 8. All relevant tests pass.
> 9. GitHub CI passes on the exact final head.
> 10. Independent review finds no unresolved correctness blocker.
> 11. No trading/authentication capability has been introduced.
>
> If any of these is not satisfied:
>
> do not mark Gate 2 complete.
>
> Do not move the execution plan to Gate 3.
>
> State exactly what remains.

## PR / merge authority (verbatim)

> You have explicit owner authorization to merge this Gate 2 PR yourself when:
>
> - every Gate 2 acceptance criterion above is satisfied;
> - CI is green on the exact final head;
> - the PR is mergeable;
> - no substantive review issue remains.
>
> If the evidence shows Gate 2 cannot currently be completed—for example because the settlement source cannot be validated—do not merge a false "Gate 2 complete" PR.

## After merge (verbatim)

> If and only if Gate 2 passed:
>
> update "docs/EXECUTION_PLAN.md" to indicate Gate 3 is now the active gate.
>
> Do NOT begin model optimization in the same PR.
>
> The next task should be building the point-in-time historical dataset and freezing the EXP-001 preregistration contract.

## Standing constraints in the same directive (verbatim excerpts)

> Do not perform strategy modeling yet. Do not estimate trading profitability yet. Do not add order execution. Do not create brokerage/trading credentials. Do not move to Gate 3 unless the Gate 2 acceptance criteria are actually met.

> If permitted: use the least invasive mechanism available according to the repository's ingestion hierarchy. If not clearly permitted: do NOT bypass restrictions or build Playwright automation around them.
