# Execution Plan

The only record of **what is authorized now**. Owner decisions override this file, and should
be written here when they are made.

## Current gate

| # | Gate | State |
|---|---|---|
| 1 | Data collection | **Complete.** Collectors, provenance, source health, freshness and immutable evidence (PR #2); NWS CLI and settlement-evidence collectors, pagination and pacing (PR #3). Scheduled collection needs approval (cost policy). |
| 2 | Settlement validation | **PASSED 2026-09-22 (PR #3).** 433 daily events audited, 0 mis-predictions, 0 unexplained mismatches; see `experiments/EXP-001-kxhighny-nws-vs-market/gate2/REPORT.md` and `docs/SETTLEMENT.md`. |
| 3 | Historical dataset | **Active (authorized).** Build the point-in-time dataset, and freeze the EXP-001 preregistration before any test-period data is examined. |
| 4–10 | Model → … → scaling | Not authorized. |

## Authorized now (no further approval needed)

- Read-only collection from free, public, unauthenticated sources that the registry lists
  (`src/edge_lab/sources.py`), with each source's terms respected.
- Collector, provenance, freshness, health, storage and test infrastructure.
- Documentation, ADRs, experiment specifications in `DRAFT`, and research write-ups.
- Settlement-rule capture and re-audit for KXHIGHNY, read-only (`edge-lab settlement`).
- **Gate 3 work:** a point-in-time historical dataset for EXP-001, built from stored
  snapshots and archives, with explicit availability timestamps.
- Freezing the EXP-001 preregistration (`edge-lab experiments freeze`) once its decision
  time, model, periods, costs and execution are fully specified.

## Explicitly not authorized

- Any order placement, order simulation against live endpoints, or authenticated trading client.
- Credential creation or storage, or funded accounts.
- Paid data or AI services, and any signup that creates an ongoing cost.
- Strategy optimization, parameter searches, or model fitting on test-period data before
  EXP-001 is frozen; model promotion before gate 4 criteria exist.
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
- **Before any experiment leaves DRAFT:** the deterministic preregistration baseline now
  exists (`edge-lab experiments freeze`, validator check, CI `check-frozen`). Use it.
- **Gate 3 → 4:** a point-in-time dataset for EXP-001, where each row records what was
  known at decision time (forecast issuance, receipt time, freshness); a settlement label
  from Kalshi `expiration_value` or the §4 CLI value; documented gaps; and a frozen EXP-001
  preregistration.
