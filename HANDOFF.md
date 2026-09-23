# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-23 (UTC), by the final-state PR of the 2026-09-23 daily-shadow
directive (`docs/owner/2026-09-23-daily-shadow-directive.md`)._

```
STATUS: PARTIAL.
  - Repository work for P2–P5 is DONE and MERGED.
  - P1 (production verification) and deployment were NOT DONE: this session has no access
    to the VPS.
ACCEPTANCE: the 2026-09-23 daily-shadow directive, recorded verbatim.
  - P1: verify production, reporting each state separately.
  - P2: bounded daily orchestration.
  - P3: fee evidence without a retry loop.
  - P4: Gate 7 adversarial engineering.
  - P5: local read-only dashboard.
  - Every PR: independent review, green CI on the exact head, squash-merge.
EVIDENCE:
  - Merged (squash), each with CI green on its exact head:
    - #25 directive record and authorization (b3050db).
    - #26 daily pipeline + Gate 7 suite (923ed9e). Independent review: 1 blocker and 7
      should-fix items, all fixed; the re-review found 3 more items, also fixed.
    - #28 local read-only dashboard (0f5ac9d). Independent review: no blocker and 7
      should-fix items, all fixed (Host-header check against DNS rebinding, full receipt
      rendering, state colours, HALTED at zero capacity, RESEARCH_INVALID_CASH blocker,
      receipt produced by the real pipeline in tests, demo research account). A focused
      re-review of those fixes followed: no blocker and no should-fix items; its nits were fixed and tested (Host port strictness, MALFORMED receipt lists, SIGTERM restore).
  - Tested main: 0f5ac9d. Tests: python -m pytest -o addopts="" gave 783 passed
    (Python 3.11 local); CI 3.11 and 3.12 green. Windows 3.12 was not available in this
    session.
  - Deployed revision: NONE from this session. Production is still main 9326a7a as of
    2026-09-23 02:20 UTC, the last read on the host, taken before this directive.
  - Access limitation (2026-09-23 06:24 ET):
    - This session runs in a cloud container with no SSH client and no key; TCP/22 to the
      VPS is unreachable.
    - Not read: production revision, timers, status JSON, backups, Chase Upside health.
    - The laptop is not reachable either. The laptop bridge stays MANUAL EMERGENCY
      FALLBACK ONLY: it was not touched and no scheduler was created.
UNRESOLVED:
  - P1 production states, each UNVERIFIED from this session:
    - installed / timers enabled: shadow and settlement units NOT INSTALLED (awaiting the
      owner's SSH step);
    - fail-closed dry run on the host: not run;
    - real decision/recheck captured: unknown (first live window 2026-09-23 17:45–18:15 ET,
      D = 2026-09-24);
    - complete forecast evidence: unknown;
    - valid-day classification: unknown; valid real Stage B days known to this session: 0;
    - eventual settlement lifecycle: not observed.
  - Shadow decisions, fills and settlements on real evidence: none recorded (the pipeline
    has not run on production data). All of it is exercised on fixtures only.
  - Backup/restore for evidence AND ledger: implemented and tested on disposable fixture
    stores (tests/test_backup_ledger.py: VERIFIED_BACKUP_AND_RESTORE, chain-invalid and
    tampered-trigger cases). Not run in production.
  - Fee coefficient 0.07: UNVERIFIED_CURRENT_SCHEDULE; claimable=false everywhere. One
    polite attempt per URL on 2026-09-23 (PDF and fee pages answered HTTP 429; see
    experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/ATTEMPTS_2026-09-23.md).
    No retry loop exists.
  - GATE7-F09 (open): without an external anchor of the ledger head hash, truncating the
    newest entries leaves a valid, shorter chain. Needs an owner decision on an anchor.
  - Known limits, documented:
    - settlement_index re-reads all settlement snapshots each run (fine at current scale);
    - Outcome Board worst case is an upper bound;
    - risk limits are notional-shadow constants, not an owner-approved real-money policy;
    - alerts go to journald and the status file only;
    - the NWS User-Agent has no contact address;
    - PFMOKX thinning since mid-2025.
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH rule rests on one
    observation.
  - Chase Upside host (not this repo): dynasty's NOPASSWD allowlist is root-equivalent.
BLOCKERS: owner-only; none for code.
  1. Deploy and activate on the VPS (SSH): follow docs/deploy/DAILY_SHADOW_ACTIVATION.md.
     It covers: pull main, run install.sh, a fail-closed dry run, enabling
     edgelab-shadow.timer and edgelab-settlement.timer, and a tested rollback.
  2. Fee evidence: download https://kalshi.com/docs/kalshi-fee-schedule.pdf in a browser
     and commit it under experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/.
  3. Decide on a ledger head-hash anchor (GATE7-F09) if one is wanted.
NEXT ACTION: The owner runs the activation sheet on chaseupside after 18:35 ET. The next
  session then reads /var/lib/market-edge-lab-status/latest.json and shadow_daily.json and
  reports each P1 state separately.
```

## Gate 7 status (engineering vs research)

- **Engineering:** the adversarial suite is merged (`tests/gate7/`,
  `docs/engineering/GATE7_FINDINGS.md`). F01–F08 and F10–F13 are FIXED; F09 is an open,
  documented limitation. The dashboard review added reporting fixes on top.
- **Production evidence:** none from this session (no access).
- **Research evidence:** none. Gate 7 research needs real Stage B days; the EXP-001
  180/365-valid-day looks are unchanged.
- **Gate 7 is NOT PASSED.** No Gate 8 work was done.

## Dashboard (local, read-only)

```
edge-lab dashboard --db <evidence.sqlite3> --ledger <shadow_ledger.sqlite3> --status-dir <status dir>
edge-lab dashboard --demo        # synthetic data in a fresh temp dir
```

- Opens at http://127.0.0.1:8765.
- Views: Overview, Opportunities, Positions & performance, Outcome Board, Risk & capital,
  Experiments & sources.
- Runbook: `docs/DASHBOARD.md` (use backup copies; never expose it).

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 29.
- **Newly completed P0:**
  - daily shadow orchestration code, with its units staged;
  - settlement-evidence refresh;
  - dual backups;
  - pre-fill risk enforcement;
  - the two-account research/operational split;
  - the local dashboard.
- **Roadmap impact:** everything on the critical path now waits on one owner SSH session.
  - Each day before activation is a day without automated shadow bookkeeping.
  - Capture itself still runs, so evidence is not lost, and the pipeline catches up the
    closed days on its first run.
  - Stage B cannot reach its first look (180 valid days) before 2026-10-22. By the
    deadline it can show pipeline completeness and early descriptive results, not a
    verdict.

## Open questions for the owner

1. **Activation.** Please run `docs/deploy/DAILY_SHADOW_ACTIVATION.md` on chaseupside
   (outside 17:40–18:35 ET).
2. **Fee schedule evidence.** Browser download of the fee-schedule PDF.
3. **Alert channel.** Optionally, a private ntfy topic URL for failure pushes.
4. **Ledger anchor (F09).** Should the ledger head hash be anchored externally (for
   example, committed daily)? That would be a scheduled job, so it needs approval.
