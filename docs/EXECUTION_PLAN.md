# Execution Plan

The only record of **what is authorized now**. Owner decisions override this file, and should
be written here when they are made.

## Current gate

| # | Gate | State |
|---|---|---|
| 1 | Data collection | **In progress.** Collectors are merged. The provenance, health and freshness foundation is in PR review. First live runs succeeded on 2026-09-22. No scheduled collection yet. |
| 2 | Settlement validation | **Authorized, not started.** Blocking finding: live KXHIGHNY rules name *The Weather Company* as the settlement source (see EXP-001). |
| 3 | Historical dataset | Not authorized until gate 2 passes. |
| 4–10 | Model → … → scaling | Not authorized. |

## Authorized now (no further approval needed)

- Read-only collection from free, public, unauthenticated sources that the registry lists
  (`src/edge_lab/sources.py`), with each source's terms respected.
- Collector, provenance, freshness, health, storage and test infrastructure.
- Documentation, ADRs, experiment specifications in `DRAFT`, and research write-ups.
- Settlement-rule capture and analysis for KXHIGHNY (gate 2 work), read-only.

## Explicitly not authorized

- Any order placement, order simulation against live endpoints, or authenticated trading client.
- Credential creation or storage, or funded accounts.
- Paid data or AI services, and any signup that creates an ongoing cost.
- Strategy optimization, parameter searches, or model promotion before gate 2 passes.
- Scheduled or unattended collection on paid infrastructure.
- Browser automation against any source whose terms have not been reviewed and recorded.

## Gate exit criteria

- **Gate 1 → 2:** repeated runs append immutable snapshots; per-source health is recorded;
  freshness is reported; a failure in one source does not lose the others.
  *(All met by the current PR once it is merged and CI is green.)*
- **Gate 2 → 3:**
  1. Capture the official settlement source and rules as versioned evidence.
  2. Document the observation window, timezone, rounding, revisions, and missing/void provisions.
  3. Reproduce at least 30 historical resolved KXHIGHNY markets from the named settlement source,
     with zero unexplained mismatches.
  4. Measure how the settlement value relates to NWS CLI and NWS forecasts.
