# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22 late ET (2026-09-23 about 02:30 UTC), by the PR that records the
overnight build directive (`docs/owner/2026-09-22-overnight-build-directive.md`)._

```
STATUS: PARTIAL. The overnight directive is recorded and Gate 5 is ACTIVE. The forward
  collector is DEPLOYED on chaseupside and PRODUCTION_VERIFIED for the fail-closed path,
  backup and restore. No live window has run yet. Valid Stage B days: 0.
ACCEPTANCE: the owner's overnight build directive, recorded verbatim. Its first items are
  the laptop-bridge cleanup and the production checks.
EVIDENCE:
  - Laptop bridge cleanup (2026-09-23 about 02:18 UTC):
    - The one attended-bridge background task, waiting for the 2026-09-23 window, was
      stopped. It had captured nothing; its log shows only the start line.
    - data/bridge.sqlite3 was never created, so there is no bridge or smoke evidence to
      mark.
    - No Windows Scheduled Task, Claude scheduled task or cron job exists for Market Edge.
    - No other bridge, edge_lab or market-edge process is running.
    - The bridge is now a MANUAL EMERGENCY FALLBACK ONLY: docs/deploy/EMERGENCY_LAPTOP_BRIDGE.md.
  - Production collector (read on the host at 2026-09-23 02:20 UTC):
    - Revision main 9326a7a077fac7f352e0e6a5b686e6de98e1e978, recorded in
      /opt/market-edge-lab/app/REVISION and EDGE_LAB_CODE_VERSION.
    - Timers enabled and waiting (America/New_York): pfm 2026-09-23 17:45:00, decision
      17:55:05, recheck 18:05:00, status 18:30:00; backup daily at 04:40 UTC.
    - The units run as User=edgelab with MemoryMax 256M, CPUQuota 25%, TasksMax 32,
      ProtectSystem=strict and NoNewPrivileges. ReadWritePaths are only the two
      Market Edge directories.
    - Host: 6.7 GB of 7.9 GB RAM available, load 0.03, 65 GB disk free.
    - Chase Upside: nginx, dynasty, dynasty-frontend and docker active;
      https://chaseupside.com/api/health reports status ok.
  - Backup and recovery drill (2026-09-23 02:20 UTC; touched only edgelab-* units):
    - `systemctl start edgelab-backup.service` → Result=success, exit 0.
    - The bundle verified as edgelab: VERIFIED_BACKUP_AND_RESTORE, schema_version 4,
      16 immutability triggers.
    - Independent restore into a disposable /root directory, then removed:
      integrity_check ok; user_version 4; 16 triggers. UPDATE and DELETE on
      forward_captures and UPDATE on collection_runs are all rejected by triggers.
    - Disabling and re-enabling edgelab-status.timer and edgelab-backup.timer left the
      live DB sha256 unchanged (dfdebcac…) and kept both bundles. Afterwards all 5
      timers were enabled and active, with the same next fire times.
    - Brisket units (nginx, dynasty, dynasty-frontend, docker) kept the same PIDs and
      start times before and after. The capture timers (pfm, decision, recheck) were
      not touched.
  - Fee schedule, re-checked 2026-09-23 02:20 UTC:
    - The public API reports KXHIGHNY fee_type "quadratic", fee_multiplier 1,
      last_updated 2026-09-17; /series/fee_changes is empty.
    - docs.kalshi.com Fee Rounding confirms the ceil-6dp trade fee and the floor-to-cent
      cash change.
    - The 0.07 coefficient is not verifiable from a primary source: the fee-schedule
      PDF and kalshi.com fee pages return HTTP 429 to automated requests, and the docs
      page no longer shows the worked example.
    - Status: UNVERIFIED_CURRENT_SCHEDULE for the coefficient.
UNRESOLVED:
  - Live-window behaviour is not verified yet. The first real capture is 2026-09-23 17:45 ET.
    Check /var/lib/market-edge-lab-status/latest.json after 18:30 ET.
  - Fee coefficient 0.07: UNVERIFIED_CURRENT_SCHEDULE. Owner step: download
    https://kalshi.com/docs/kalshi-fee-schedule.pdf in a browser and commit it as evidence.
  - Alerts go only to journald and the status file. The optional EDGE_LAB_ALERT_URL is not
    set.
  - The NWS User-Agent is a neutral identifier without a contact address.
  - PFMOKX thinning since mid-2025 (disclosed). Test-period protection is procedural.
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH delayed-determination
    rule rests on one observation.
  - Chase Upside host follow-up (not this repo): dynasty's NOPASSWD allowlist is
    root-equivalent.
  - Cosmetic: the alert instance name doubles the suffix (edgelab-alert@<unit>.service.service).
BLOCKERS: NONE
NEXT ACTION: Build the Gate 5 opportunity engine, then, if Gate 5 passes, Gate 6. After
  2026-09-23 18:30 ET, confirm that D = 2026-09-24 is VALID on the VPS.
```

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 30.
- **Critical path:**
  1. Collector live (done).
  2. Valid Stage B days accumulating (first window on 2026-09-23).
  3. Gate 5 opportunity engine (active).
  4. Gate 6 shadow ledger and sizing.
  5. Risk/capital foundation.
  6. Outcome Board backend.
  7. Dashboard and deployment (not authorized yet).
- **Blockers:** none. Fee verification needs one browser download by the owner.
- **Power reality:** Stage B's first look is at the 180th valid day (POWER.md), which is
  far past 2026-10-22. By the deadline, Stage B can show pipeline completeness and early
  descriptive results, not a verdict.

## Open questions for the owner

1. **Fee schedule evidence.** Please download the Kalshi fee-schedule PDF in a browser (it
   blocks automated fetches) so the 0.07 coefficient can be verified.
2. **Alert channel.** Optionally, a private ntfy topic URL for failure pushes.
