# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22, by the Gate 2 PR. This file reaches `main` only through that
PR's squash merge._

```
STATUS: DONE: gate 2 (settlement validation) criteria met. Gate 3 is active on merge of
PR #8, per the owner's authorization recorded in docs/EXECUTION_PLAN.md.
ACCEPTANCE: the 11 gate-2 criteria in the user directive and docs/EXECUTION_PLAN.md
  (table: experiments/EXP-001-kxhighny-nws-vs-market/gate2/REPORT.md §6)
EVIDENCE:
  - Settlement semantics with citations: docs/SETTLEMENT.md. Evidence (PDF bytes, hashes,
    deterministic extractions): experiments/EXP-001-kxhighny-nws-vs-market/gate2/evidence/
  - Reproduction (windows in SAMPLE.md; independence unit = day):
    - A, 2026-07-16..09-21: 68/68 (inspected during exploration)
    - B, 2025: 361/365. Used to develop two rules; the original procedure gave 359/365
      with 1 mis-prediction (25DEC03).
    - C, 2024: fresh, procedure frozen at 9f28602 first: 366/366, 0 UNKNOWN
    - 0 mis-predicted brackets under the final procedure; 4 UNKNOWN (B archive gaps)
  - Kalshi expiration_value vs NWS CLI value: 739/739 exact. Only 39 of these are TWC-era
    days; no TWC value was observed.
  - Live read-only runs 2026-09-22 into a fresh DB matched the fixtures exactly (same hashes)
  - Pacing: live runs needed 0 retries (previously 1-3 per run)
  - Tests and CI: see the gate 2 PR (local python -m pytest on 3.11 and 3.12)
UNRESOLVED:
  - The Weather Company is named in rules since 2026-08-14 but cannot be checked directly
    (its terms prohibit automated access). Settlement uses Kalshi's value, with NWS CLI as
    the audited proxy (ADR 0007).
  - NHIGH delayed-determination rule rests on one observation (25DEC03), and is applied
    by date inference (≤ 2025-12-09); condition (1) (METAR) is not implemented.
  - Contract PDFs are 2026-09-22 versions only; per-event wording comes from each market's
    own rules text.
  - No scheduled collection (ADR 0008). Point-in-time order books exist only for manual
    runs.
BLOCKERS: NONE
NEXT ACTION: Gate 3, the point-in-time historical dataset for EXP-001:
  (0) measure how settlement relates to NWS forecasts (moved from gate 2 criterion 4);
  (1) decide the decision time and which forecast issuances were available by then
      (NWS snapshots from our collector; historical forecast archives, if a free official
      one exists);
  (2) build dataset rows with availability timestamps, freshness and settlement labels;
  (3) document gaps honestly (no historical order books before 2026-09-22);
  (4) fully specify EXP-001, then set PREREGISTERED and run `edge-lab experiments freeze`
      before examining any test-period data.
  No model fitting or optimization before the freeze.
```

## Open questions for the owner

1. **Scheduled collection** (ADR 0008). Should forward collection of order books and
   forecasts at fixed decision times get a durable, low-cost home? Options: a small VM or
   object storage, or low-frequency Actions with artifacts. This is a private repo, so
   Actions minutes count against the account allowance. Needs a cost decision.
2. **Standing merge rule.** May agents merge docs- or test-only PRs on green CI, or does
   every merge need an explicit grant like PRs #2 and #8?
