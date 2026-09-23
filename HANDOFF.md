# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-23 (early UTC), by the risk-foundation PR (#24), which ends the
overnight build directive (`docs/owner/2026-09-22-overnight-build-directive.md`)._

```
STATUS: DONE for the overnight directive's authorized sequence.
  - Gate 5 PASSED (#22). Gate 6 PASSED (#23). Risk/capital and Outcome Board foundations
    merged (#24).
  - The forward collector is DEPLOYED and PRODUCTION_VERIFIED for the fail-closed path and
    for backup/restore.
  - No live Stage B window has run yet. Valid Stage B days: 0. No shadow trade exists.
ACCEPTANCE: the owner's overnight build directive, recorded verbatim.
  - Laptop bridge cleanup.
  - Production checks.
  - Gate 5 and Gate 6 acceptance lists (docs/EXECUTION_PLAN.md).
  - Risk/capital, withdrawal and Outcome Board backend foundations.
  - Merge conditions for each PR.
EVIDENCE:
  - Laptop bridge (2026-09-23 about 02:18 UTC):
    - The one attended-bridge task was stopped before any capture. data/bridge.sqlite3
      was never created.
    - No Windows Scheduled Task, Claude scheduled task or cron job exists.
    - The bridge is now MANUAL EMERGENCY FALLBACK ONLY
      (docs/deploy/EMERGENCY_LAPTOP_BRIDGE.md).
  - Production (read on the host at 2026-09-23 02:20 UTC):
    - Revision main 9326a7a (the collector code is unchanged since).
    - Five timers enabled. Next fires (America/New_York): pfm 2026-09-23 17:45, decision
      17:55:05, recheck 18:05, status 18:30; backup daily 04:40 UTC.
    - The units run as edgelab: MemoryMax 256M, CPUQuota 25%, TasksMax 32,
      ProtectSystem=strict.
    - Host: 6.7 of 7.9 GB free.
    - Chase Upside: nginx, dynasty, dynasty-frontend and docker active; /api/health ok.
  - Backup and recovery drill:
    - edgelab-backup.service succeeded, and the bundle was VERIFIED_BACKUP_AND_RESTORE
      (schema v4, 16 triggers).
    - Independent restore into a disposable directory: integrity ok; UPDATE/DELETE blocked.
    - Disabling and re-enabling the status and backup timers kept the DB sha unchanged.
    - Brisket PIDs were identical before and after.
  - Merged PRs, each with an independent read-only review and CI green on its exact head:
    - #21 directive record and standing merge rule (3ef0369).
    - #22 Gate 5 opportunity engine (467a1a4). Review: 1 blocker (settlement equivalence),
      fixed and re-reviewed with no blocker.
    - #23 Gate 6 shadow ledger (f854161). Review: no blocker; 4 should-fix items fixed and
      re-reviewed.
    - #24 risk/capital and Outcome Board foundations (squash of this PR).
  - Tests: python -m pytest -o addopts="" on the final branch gave 482 passed, 1 skipped
    (Windows, Python 3.12). CI: 3.11 and 3.12 green.
  - Fee schedule (checked 2026-09-23 02:20 UTC):
    - The API reports KXHIGHNY quadratic, multiplier 1, and no pending fee changes.
    - The Fee Rounding docs confirm the rounding.
    - The 0.07 coefficient could not be read from a primary source (the PDF answers
      HTTP 429). Status: UNVERIFIED_CURRENT_SCHEDULE, so every opportunity and decision
      has claimable=false.
UNRESOLVED:
  - First live window: 2026-09-23 17:45–18:15 ET (D = 2026-09-24). Not yet verified.
  - Fee coefficient 0.07 is unverified. Owner step: download
    https://kalshi.com/docs/kalshi-fee-schedule.pdf in a browser and commit it as evidence.
  - Settlement evidence is not captured on the VPS. `settlement collect` has no timer, so
    shadow positions will stay open (safely) until one is approved and installed or the
    evidence is collected by hand.
  - The Outcome Board's cluster worst case is an upper bound. Scenario enumeration is
    deferred.
  - Risk limits are code constants for a notional shadow account, not an owner-approved
    real-money policy.
  - Alerts go only to journald and the status file (EDGE_LAB_ALERT_URL is not set). The
    NWS User-Agent has no contact address.
  - PFMOKX thinning since mid-2025 (disclosed). Test-period protection is procedural.
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH rule rests on one
    observation.
  - Chase Upside host (not this repo): dynasty's NOPASSWD allowlist is root-equivalent.
BLOCKERS: NONE for code. Verifying the fee schedule needs one owner browser download.
NEXT ACTION: After 2026-09-23 18:30 ET, read /var/lib/market-edge-lab-status/latest.json on
  chaseupside and confirm D = 2026-09-24 is VALID. Then run
  `edge-lab forward opportunities --date 2026-09-24` and `edge-lab shadow run --date
  2026-09-24` against a copy of the production DB to exercise Gates 5–6 on real evidence.
```

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 29.
- **Completed P0:**
  - collector live;
  - Gate 4 Stage A;
  - Gate 5 opportunity engine;
  - Gate 6 shadow ledger, fills and sizing;
  - risk/capital foundation with the withdrawal contract;
  - Outcome Board backend.
- **Remaining P0:**
  1. Accumulate valid Stage B days (the first is tonight).
  2. Run the shadow pipeline on real evidence every day. It is manual today; running it
     on the VPS needs owner approval of a new timer.
  3. Settlement-evidence capture (a daily `settlement collect` timer on the VPS; owner
     approval needed).
  4. Fee verification (owner PDF).
  5. Dashboard and hosting (not authorized).
- **Critical path:**
  1. Valid forward days.
  2. Daily shadow runs.
  3. Settlements.
  4. Stage B looks at the 180th and 365th valid day. The first is far past 2026-10-22,
     so by the deadline Stage B can show pipeline completeness and early descriptive
     results, not a verdict.
- **Blockers:** fee verification needs the owner's browser download. Scheduling shadow
  runs and settlement capture on the VPS needs owner approval, because it changes the
  deployment.

## Open questions for the owner

1. **Fee schedule evidence.** Please download the Kalshi fee-schedule PDF in a browser (it
   blocks automated fetches) so the 0.07 coefficient can be verified.
2. **VPS timers for Stage B bookkeeping.** May I add two read-only timers on chaseupside?
   One is a daily `settlement collect --no-historical`. The other is a daily `forward
   opportunities` + `shadow run` + `shadow settle`, writing to a separate shadow ledger
   file. This is a deployment change, so it waits for approval.
3. **Alert channel.** Optionally, a private ntfy topic URL for failure pushes.
4. **Gate 7.** Gate 6 is complete. Gate 7 (adversarial validation) needs your explicit
   approval, and it only becomes meaningful once real shadow days exist.
