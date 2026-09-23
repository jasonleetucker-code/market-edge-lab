# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22 (evening ET), by the Gate 4 PR (#18) at the end of the three-lane
mission in `docs/owner/2026-09-22-gate4-collection-directive.md`._

```
STATUS: PARTIAL. Code is DONE and MERGED in all three lanes. Deployment is waiting on two
  owner sudo commands on the VPS.
  - Gate 4: Stage A PASS (PR #18).
  - PR #13: merged.
  - Forward collector and the #16 fix: merged (PR #19).
  - The collector is staged on the VPS but not installed. No Stage B day has been captured.
ACCEPTANCE: the owner's 2026-09-22 directive (Lanes A, B, C, #16, repository state), recorded
  verbatim in docs/owner/2026-09-22-gate4-collection-directive.md
EVIDENCE:
  - Merged to main:
    - #17 docs/authorization (3cab670)
    - #13 reliability port (cb33738)
    - #19 collector + #16 (b684f5b)
    - #18 Gate 4 (squash of this PR)
    Each PR merged only after an independent read-only review found no unresolved blocker
    and CI was green on its exact final head. The reviews and CI runs are linked in each PR.
  - Gate 4 (EXP-001, frozen spec, no tuning):
    - Validation (731 days): V2 − V1 = −0.0020, CI [−0.0256, +0.0207], so the rule
      selects V1 (pooled).
    - Test (629 days, opened once): model − R0 +1.2534, CI [+1.1470, +1.3624]; PIT central
      coverage 0.8060, inside [0.75, 0.85]. Stage A PASS.
    - Reported only: model − R1 +0.0196, CI [−0.0011, +0.0394]. The interval includes 0.
      Brier: model 0.892, R0 0.968, R1 0.897. Log loss: model 2.451, R0 3.705, R1 2.471.
    - The independent reviewer reproduced every headline number bit-for-bit.
    - EXP-001 status is RUNNING. Six pre-validation amendments, none changing the
      model/window/threshold.
    - Full record: experiments/EXP-001-kxhighny-nws-vs-market/gate4/REPORT.md
  - PR #13, reconciled with Gate 3 and #15:
    - Windows fsync fix.
    - The backup refuses unsupported schemas and any missing immutability trigger, and
      supports pre-migration backups.
    - validate.py fails closed on a dirty tree, on PYTHONOPTIMIZE, and on
      narrowing environment variables.
    - Fingerprints are CRLF-normalized.
    - A backup of a v4 database is VERIFIED, including forward_captures and 16 triggers.
  - Forward collector (edge_lab.forward, schema v4 forward_captures):
    - A timing gate runs before any network call; out-of-window runs are rejected with
      zero requests.
    - All brackets and the recheck are required; no partial valid days. DST-correct (checked
      against zoneinfo, 2026–2035).
    - Duplicate, interrupted and restarted runs, timeouts and rate limits are bounded by the
      deadline.
    - The day is VALID only if a complete PFM capture exists. That was the review blocker,
      now fixed.
  - #16 closed: `health --profile routine|settlement|forward|all`, default routine. Stale
    sources still fail their profile. Forward runs no longer touch routine health.
  - Tests: python -m pytest gave 331 passed, 1 skipped on main at b684f5b, and 359 passed,
    1 skipped with this PR merged in (Windows, Py 3.12;
    the skip is a symlink test). CI is green on 3.11 and 3.12 for every merged head.
    `experiments validate` OK; check-frozen OK.
  - VPS (chaseupside, vmi3454985):
    - Read-only preflight PASS twice: 5.9 GB of 7.9 GB RAM available; ≥ 3.9 GB free at
      the worst point in 7 days; 65 GB disk free; systemd 255; NTP synced; no OOM kills
      in 30 days. Details in docs/deploy/VPS_REVIEW_2026-09-22.md.
    - Release staged in ~dynasty/edgelab-release: bundle of main b684f5b, sha256 a050ff49…;
      install.sh taken from git, LF.
    - On the host runtime the timing gate rejected an out-of-window run with no network
      calls. Timer calendars resolve to 17:45, 17:55:05, 18:05 and 18:30 America/New_York.
  - Live read-only smoke run (smoke DB, never evidence):
    - The KXHIGHNY-26SEP23 event returned 6 open brackets and 6 books.
    - PFMOKX FOUS51 KOKX 221853 gives 67 °F.
UNRESOLVED:
  - The collector is not installed. Valid Stage B days captured: 0.
  - If the timers are enabled before 2026-09-23 17:45 ET, the first possible valid target
    date is D = 2026-09-24. Otherwise, run the attended laptop bridge for that window.
  - The alert channel is journald and the status file only, until the owner optionally sets
    EDGE_LAB_ALERT_URL, e.g. a private ntfy topic.
  - Fee coefficient 0.07: re-verify against Kalshi's fee schedule before any Stage B result.
  - PFMOKX issuance thinned from mid-2025. This is disclosed, and Stage A passed anyway.
  - Test-period protection is procedural (dataset.csv contains test rows).
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH delayed-determination
    rule rests on one observation.
  - Review NITs left open (no correctness impact):
    - Forward Kalshi snapshots can refresh routine per-kind freshness for up to 5–60 min.
    - An unparseable newest PFM product falls back to the older forecast, the same as the
      frozen historical builder.
    - Backups compare row counts, not row content.
BLOCKERS: the owner must run two sudo commands on chaseupside (sudo needs their password).
  1. Install:
     sudo bash ~/edgelab-release/install.sh --sha b684f5b77242ee3b9de40d8849692c96f0d90b5c --bundle ~/edgelab-release/market-edge-lab.bundle --user-agent "market-edge-lab research (contact: <owner email>)"
  2. After the fail-closed dry run in deploy/vps/README.md:
     sudo systemctl enable --now edgelab-pfm.timer edgelab-decision.timer edgelab-recheck.timer edgelab-status.timer edgelab-backup.timer
NEXT ACTION: The owner runs the install command, then the dry run and the timer
  activation, before 2026-09-23 17:45 ET. The agent then confirms from
  /var/lib/market-edge-lab-status/latest.json after 18:30 ET that D = 2026-09-24 is VALID.
```

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 30.
- **Critical path:** collector live (owner sudo) → accumulate valid Stage B days → Gate 5
  (market-vs-model engine: opportunity schema, executable prices, fees) → shadow ledger →
  risk foundation → dashboard → deployment.
- **Blockers:**
  - The owner's sudo install on the VPS.
  - Owner approval to move to Gate 5. The Gate 4 exit criteria are met.
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
