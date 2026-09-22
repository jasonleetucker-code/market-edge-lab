# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22, by the Gate 3 PR. This file reaches `main` only through that
PR's squash merge. The owner authorized the merge only once all 21 criteria hold and CI is
green on the final head._

```
STATUS: DONE: gate 3 (point-in-time dataset + EXP-001 preregistration) criteria met on
  this branch. Gate 4 is active on merge of the Gate 3 PR (docs/EXECUTION_PLAN.md).
ACCEPTANCE: the owner's 21 Gate 3 criteria, recorded verbatim in
  docs/owner/2026-09-22-gate3-directive.md
EVIDENCE:
  - Decision time 18:00 America/New_York on D-1; availability cutoff decision - 30 min;
    issuance = WMO header time; suffixed products never used (ADR 0010, gate3/DESIGN.md §1)
  - Source: NWS PFMOKX (Central Park NYZ072) via the IEM AFOS archive. 118 monthly
    responses, 32,699 products, 0 non-200 responses, stored as exact extracts plus hashes
    (ADR 0011, tests/fixtures/gate3/)
  - Dataset EXP-001-pit-v2: 2017-01-01..2026-09-21, 3,551 candidate days, 3,551 usable,
    0 excluded. SHA-256 1794b23cd519a4c4a952700dc97530df0f0452f070962c0cb7500fd1afcef51a.
    CI rebuilds it byte-identically (tests/test_gate3_reproducible.py).
  - Labels: Kalshi expiration_value 1,801 days, NWS CLI contract rule 1,750. They agree on
    1,797/1,797 days where both exist.
  - Train-only description (gate3/DESCRIPTIVE_TRAIN.md): n = 2,191; error bias +0.44 °F,
    sd 3.21, MAE 2.30; 15.3% exact, 65.9% within ±2 °F; long right tail (max +21)
  - Split: train 2017-2022, validation 2023-2024, test 2025-01-01..2026-09-21. No
    validation or test error was computed.
  - Baseline, fees, execution, Stage A/B criteria and power: gate3/DESIGN.md, POWER.md,
    experiment.toml
  - Freeze: experiments/EXP-001-kxhighny-nws-vs-market/preregistration.json, frozen fields
    SHA-256 4b1cab54a390efb7c703e1b03a12263ea43435826f048c83d857da76d1d046fc.
    `edge-lab experiments validate` OK; check-frozen vs origin/main OK.
    tests/invariants/test_exp001_frozen_artifacts.py pins DESIGN.md, fees.py, stats.py
    and the dataset hash.
  - Tests: python -m pytest, 229 passed on 3.11 and on 3.12. CI: see the Gate 3 PR.
  - Independent adversarial review (read-only): no blocker. All 7 SHOULD-FIX items were
    fixed before the freeze, including the DST lead-hours bug, the pinned bootstrap, the
    Stage B two-look rule, the issuance-regime disclosure, artifact pins, suffixed
    products, and doc overclaims. Nits 1, 2, 3, 5, 6 and 7 were fixed.
UNRESOLVED:
  - Fee coefficient 0.07 comes from Kalshi's documented worked example. The fee-schedule
    PDF sits behind a bot checkpoint (not bypassed). Re-verify before any Stage B result.
  - PFMOKX issuance thinned from mid-2025, so test-period forecasts are older at the
    decision time. This is disclosed and not adjusted for; it may fail Stage A calibration.
  - Full PFM products are not in git (extracts + hashes only; re-fetchable from IEM).
  - Test-period protection is procedural: dataset.csv contains test forecasts and labels.
  - Stage B needs daily 18:00 ET order-book collection, which is scheduled collection and
    an owner decision (ADR 0008; issue #10 is a candidate host).
  - Carried from gate 2: TWC cannot be checked directly; the NHIGH delayed-determination
    rule rests on one observation.
BLOCKERS: NONE for Gate 4. Stage B is BLOCKED-ON-OWNER (scheduled collection).
NEXT ACTION: Gate 4. Implement the frozen baseline model and evaluate it on the
  predeclared train/validation/test protocol: fit V1/V2 on train, select on validation by
  the frozen rule, then refit and run Stage A on test exactly once, reporting the result
  whatever it is. Use edge_lab.stats for every interval. Do not change the frozen spec.
```

## 30-day directive status (issue #11, target 2026-10-22)

- Remaining calendar days: 30.
- Critical path: Gate 4 (days 4–7) → forward Kalshi book collection and opportunity
  schema (days 6–10) → market-vs-model engine → shadow ledger → risk foundation →
  dashboard → deployment.
- New blockers: forward collection needs the owner's scheduled-collection decision (ADR
  0008). It gates Stage B, the shadow ledger's real data, and the dashboard's live views.
- Scope changes: none. Issue #12 (Brisket reliability port) runs in a parallel lane with
  its own file claim.
- P0 confidence (project status, evidence-based): Gate 3 finished on day 1, ahead of the
  day-4 target. Everything after Gate 5 depends on the collection decision, so ask for it
  now.

## Open questions for the owner

1. **Scheduled collection** (ADR 0008). Should forward collection of order books and
   forecasts at fixed decision times get a durable, low-cost home? Options: a small VM,
   the Chase Upside VPS per #10, object storage, or low-frequency Actions with artifacts.
   This is a private repo, so Actions minutes count against the account allowance. It
   needs a cost decision, and it now blocks EXP-001 Stage B and the #11 critical path.
2. **Standing merge rule.** May agents merge docs- or test-only PRs on green CI, or does
   every merge need an explicit grant like PRs #2, #8 and the Gate 3 PR?
