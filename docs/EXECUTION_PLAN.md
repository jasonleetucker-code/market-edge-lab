# Execution Plan

The only record of **what is authorized now**. Owner decisions override this file, and should
be written here when they are made.

## Current gate

| # | Gate | State |
|---|---|---|
| 1 | Data collection | **Complete.** Collectors, provenance, source health, freshness and immutable evidence (PR #2); NWS CLI and settlement-evidence collectors, pagination and pacing (PR #8). Scheduled collection needs approval (cost policy). |
| 2 | Settlement validation | **PASSED 2026-09-22 (PR #8; merge gated on green CI on the final head).** 799 daily events audited (including a fresh 2024 validation with the procedure frozen first), 0 mis-predictions under the final procedure, 0 unexplained mismatches; see `experiments/EXP-001-kxhighny-nws-vs-market/gate2/REPORT.md` and `docs/SETTLEMENT.md`. |
| 3 | Historical dataset | **PASSED 2026-09-22 (Gate 3 PR; effective on its merge, which the owner authorized only once all 21 criteria hold and CI is green on the final head).** Point-in-time dataset EXP-001-pit-v1 (3,551 days, 3,551 usable, SHA-256 `b14efbec…`), train-only descriptive analysis, EXP-001 PREREGISTERED and frozen; see `experiments/EXP-001-kxhighny-nws-vs-market/gate3/`. |
| 4 | Baseline model | **Active on merge of the Gate 3 PR (authorized).** Implement the frozen baseline model and evaluate it on the predeclared train/validation/test protocol. |
| 5–10 | Market-vs-model → … → scaling | Not authorized. |

## Owner authorization record

- **2026-09-22, gate 2 → gate 3.** Directive recorded verbatim (acceptance criteria,
  merge authority, after-merge steps) in `docs/owner/2026-09-22-gate2-directive.md`. It
  stated: "You are also
  explicitly authorized to merge the resulting Gate 2 PR yourself when all acceptance
  criteria and CI requirements below are satisfied", and "If and only if Gate 2 passed:
  update `docs/EXECUTION_PLAN.md` to indicate Gate 3 is now the active gate." Gate 3
  becomes active when PR #8 merges. The directive also said not to begin model
  optimization in that PR.

- **2026-09-22, gate 3 → gate 4.** Directive recorded verbatim in
  `docs/owner/2026-09-22-gate3-directive.md`. It authorized merging the Gate 3 PR once all
  21 acceptance criteria hold, CI is green on the exact final head, the PR is mergeable and
  independent review has no unresolved correctness blocker. It also said: "If and only if
  Gate 3 passed: update `docs/EXECUTION_PLAN.md` so Gate 4 becomes active. Gate 4 should
  then begin with: «Implement the frozen baseline model and evaluate it on the predeclared
  train/validation/test protocol.» Do not perform that evaluation in the Gate 3 PR."

## Authorized now (no further approval needed)

- Read-only collection from free, public, unauthenticated sources that the registry lists
  (`src/edge_lab/sources.py`), with each source's terms respected.
- Collector, provenance, freshness, health, storage and test infrastructure.
- Documentation, ADRs, experiment specifications in `DRAFT`, and research write-ups.
- Settlement-rule capture and re-audit for KXHIGHNY, read-only (`edge-lab settlement`).
- **Gate 4 work (after the Gate 3 merge):** implement the frozen EXP-001 baseline exactly
  as preregistered (`experiments/EXP-001-kxhighny-nws-vs-market/experiment.toml`,
  `preregistration.json`, `gate3/DESIGN.md` §5–6); select V1/V2 on validation by the frozen
  rule; evaluate Stage A on the test split **once**; report the result whatever it is.
  Any change to the frozen spec is a dated `[[amendments]]` entry made *before* the test
  evaluation, or a new experiment.

## Explicitly not authorized

- Any order placement, order simulation against live endpoints, or authenticated trading client.
- Credential creation or storage, or funded accounts.
- Paid data or AI services, and any signup that creates an ongoing cost.
- Strategy optimization or parameter searches; any model variant, threshold or window not
  in the frozen EXP-001 spec; evaluating the test split more than once, or changing the
  experiment after seeing test performance.
- Stage B shadow trading until the owner decides on scheduled collection (ADR 0008), and
  any real-money step (gates 8–10).
- Scheduled or unattended collection of any kind, **including GitHub Actions cron**, without
  owner approval.
- Browser automation against any source whose terms have not been reviewed and recorded.

## Cost policy for unattended infrastructure

Unattended infrastructure is not free just because no separate server was bought. This
repository is private. GitHub Actions minutes on a private repository come out of the
account's included allowance, and depending on plan and settings they can become billable
usage. (Allowances and prices change, so check current GitHub documentation rather than
trusting a number written here.) Any proposed scheduled collector must, before approval:

1. estimate its runtime per run and its minutes per month;
2. start at low frequency and increase only when evidence shows the extra data is needed;
3. bound each run (job `timeout-minutes`, request timeouts, bounded retries);
4. state how usage will be watched and how the job is switched off.

## Gate exit criteria

- **Gate 1 → 2:** repeated runs append immutable snapshots; per-source health is recorded;
  freshness is reported; a failure in one source does not lose the others.
  *(Met by PR #2: see `HANDOFF.md` for the evidence.)*
- **Gate 2 → 3 (met 2026-09-22):**
  1. Capture the official settlement source and rules as versioned evidence.
  2. Document the observation window, timezone, rounding, revisions, and missing/void provisions.
  3. Reproduce at least 30 historical resolved KXHIGHNY markets from the named settlement source,
     with zero unexplained mismatches.
  4. Measure how the settlement value relates to NWS CLI and NWS forecasts.
     *Amended 2026-09-22:* the CLI part was measured (739/739). The **forecast** part is
     moved to gate 3, because it needs the point-in-time forecast dataset. It is also not
     among the owner's 11 gate-2 acceptance criteria (recorded verbatim in
     `docs/owner/2026-09-22-gate2-directive.md`), which govern this gate. Recorded here
     rather than silently dropped.
- **Before any experiment leaves DRAFT:** the deterministic preregistration baseline now
  exists (`edge-lab experiments freeze`, validator check, CI `check-frozen`). Use it.
- **Gate 3 → 4 (met 2026-09-22; the owner's 21 criteria in
  `docs/owner/2026-09-22-gate3-directive.md` govern):** a point-in-time dataset for EXP-001, where each row records what was
  known at decision time (forecast issuance, receipt time, freshness); a settlement label
  from Kalshi `expiration_value` or the §4 CLI value; documented gaps; and a frozen EXP-001
  preregistration.
- **Gate 4 → 5 (proposed; the owner may revise):** the frozen baseline is implemented with tests, validation selection is
  recorded, Stage A on test is run once and reported (pass or fail) in EXP-001's log, and
  the owner decides whether and how Stage B collection proceeds.
