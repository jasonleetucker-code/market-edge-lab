# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22 (evening ET), by the Gate 4 PR (#18) at the end of the three-lane
mission in `docs/owner/2026-09-22-gate4-collection-directive.md`._

```
STATUS: DONE for the mission's code, merges and deployment. The forward collector is
  DEPLOYED and PRODUCTION_VERIFIED for the fail-closed path. The first live capture window is
  2026-09-23 17:45–18:15 ET (target D = 2026-09-24). Valid Stage B days so far: 0; none has
  been possible yet.
ACCEPTANCE: the owner's 2026-09-22 directive (docs/owner/2026-09-22-gate4-collection-directive.md)
  and the owner's 2026-09-23 deployment instruction: compare the staged SHA with main; install
  as the separate `edgelab` service; fail-closed dry run; verify permissions, identity,
  limits, logs and status path; enable the reviewed timers; verify the next ET times.
EVIDENCE:
  - Merged to main:
    - #17 authorization (3cab670)
    - #13 reliability port (cb33738)
    - #19 collector + #16 (b684f5b)
    - #18 Gate 4, Stage A PASS (9326a7a)
    Each PR had an independent read-only review with no unresolved blocker, and CI green
    on its exact head. On main at 9326a7a: 359 passed, 1 skipped.
  - Gate 4:
    - V1 selected on validation.
    - Test opened once: model − R0 +1.2534, CI [+1.1470, +1.3624]; PIT coverage 0.8060.
      PASS.
    - EXP-001 status RUNNING.
    - Full record: experiments/EXP-001-kxhighny-nws-vs-market/gate4/REPORT.md
  - Deployed revision: main 9326a7a077fac7f352e0e6a5b686e6de98e1e978.
    - Deployed on 2026-09-23 at 02:09 UTC, on chaseupside (vmi3454985), via root SSH
      restored by the owner.
    - Recorded in /opt/market-edge-lab/app/REVISION and EDGE_LAB_CODE_VERSION.
    - Why current main rather than the staged b684f5b: they differ in runtime code only by
      the Gate 4 analysis module src/edge_lab/exp001_baseline.py, which the collector
      never imports. src/edge_lab/forward.py, cli.py, storage.py, sources.py, backup.py and
      deploy/ are byte-identical. Deploying main makes the running code equal main.
    - Bundle sha256 cf7cc419…; install.sh sha256 f342b3de….
  - Install (deploy/vps/install.sh as reviewed): INSTALL OK, all 13 permission checks ok:
    - env file root:edgelab 640; private data, db and backups edgelab 700; status dir 755;
    - edgelab can read the env file; dynasty cannot read the env file, database or
      backups, and cannot list private data; dynasty can read the status file.
  - Fail-closed dry run (edgelab-decision.service at 02:09:55Z, outside the window):
    - exit 1, `rejected_out_of_window`;
    - 0 snapshots and 0 source-health rows (no network work);
    - 1 capture row and 1 run marked failed;
    - the OnFailure alert fired and wrote last_failure.json.
  - Identity and limits:
    - The collector logs as UID 999 (edgelab).
    - Every unit: MemoryHigh 192M, MemoryMax 256M, CPUQuota 25%, TasksMax 32, Nice 5,
      NoNewPrivileges, ProtectSystem=strict, ProtectHome; UMask 0077 (0022 for the status
      unit).
    - ReadWritePaths = /var/lib/market-edge-lab and /var/lib/market-edge-lab-status.
    - The database is schema v4.
  - Timers enabled; next fire times (America/New_York):
    - pfm 2026-09-23 17:45:00 EDT
    - decision 17:55:05 EDT
    - recheck 18:05:00 EDT
    - status 18:30:00 EDT
    - backup 04:40 UTC daily
  - Chase Upside after the install: nginx, dynasty and dynasty-frontend active;
    /api/health status ok. No Brisket unit was modified. No apt changes, no reboot by the
    agent.
  - Redundancy for the first window: the attended laptop bridge (owner-approved) also
    captures D = 2026-09-24 into the laptop's data/bridge.sqlite3 and exits afterwards.
UNRESOLVED:
  - Live-window behaviour is not verified yet. The first real capture is 2026-09-23 17:45 ET.
    Check /var/lib/market-edge-lab-status/latest.json after 18:30 ET.
  - Alerts go only to journald and the status file. The optional EDGE_LAB_ALERT_URL is not
    set.
  - The NWS User-Agent is a neutral identifier without a contact address. The owner may
    supply one: rerun install.sh with --user-agent.
  - Importing the bridge evidence into the VPS database is not built. The bridge DB is kept
    as separate immutable evidence.
  - Fee coefficient 0.07: re-verify before any Stage B result.
  - PFMOKX thinning since mid-2025 (disclosed).
  - Test-period protection is procedural.
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH delayed-determination
    rule rests on one observation.
  - Hardening follow-up for the Chase Upside host (not this repo): dynasty's NOPASSWD
    allowlist (systemctl, install, chown) is root-equivalent (docs/deploy/VPS_REVIEW_2026-09-22.md).
  - Cosmetic: the alert instance name doubles the suffix (edgelab-alert@<unit>.service.service).
BLOCKERS: NONE
NEXT ACTION: After 2026-09-23 18:30 ET, confirm the VPS status file reports D = 2026-09-24
  VALID, compare it with the laptop bridge, then ask the owner whether Gate 5 may begin.
```

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 30.
- **Critical path:** collector live (deployed 2026-09-23; first window that evening) → accumulate valid Stage B days → Gate 5
  (market-vs-model engine: opportunity schema, executable prices, fees) → shadow ledger →
  risk foundation → dashboard → deployment.
- **Blockers:**
  - Owner approval to move to Gate 5. The Gate 4 exit criteria are met.
  - The collector is deployed (2026-09-23).
- **Scope changes:**
  - None to the deadline.
  - #10 is authorized for the headless collector only. Dashboard, DNS, TLS and auth are
    still unauthorized.
- **Power reality:** Stage B's first look is at the 180th valid day (POWER.md), which is
  far past 2026-10-22. By the deadline, Stage B can show pipeline completeness and early
  descriptive results, not a verdict.

## Open questions for the owner

1. **Gate 5.** The Gate 4 exit criteria are met (Stage A PASS). May Gate 5
   (market-vs-model) begin?
2. **Alert channel.** Optionally, a private ntfy topic URL for failure pushes.
3. **Standing merge rule.** The current grant covers only this mission's PRs. A general
   rule for docs- and test-only PRs is still undecided.
