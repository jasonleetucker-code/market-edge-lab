# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-23 ~19:00 America/New_York, by the final-state PR of the production
activation directive (`docs/owner/2026-09-23-production-activation-directive.md`). This
session ran on the owner's laptop, with SSH to chaseupside._

```
STATUS: DONE for the directive's production and follow-up scope. Evidence as below; nothing
  is claimed beyond it.
ACCEPTANCE: the 2026-09-23 production activation + post-audit integration directive
  (recorded verbatim with the SSH grant).
EVIDENCE:
  - Production (details and every state, separately:
    docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md):
    - deployed with DAILY_SHADOW_ACTIVATION.md only:
      247fe80 -> 6e2031c -> afa3ce9 (Tailscale session, #46) -> 7aac49c (ran the first
      window) -> f646481 (Terminal v1 session, #49, 18:52 ET, after the window; §10 of the record);
    - each install had a verified backup before it and a fail-closed decision test on the
      installed code (rejected_out_of_window, 0 records);
    - 7/7 timers enabled: pfm, decision, recheck, status, backup, shadow, settlement.
      edgelab-dashboard.service (tailnet-only, ADR 0024) runs continuously and is exempt
      from the install check;
    - evidence and ledger backups and restores VERIFIED at every step; OOM (30 d) 0;
      memory PSI 0.00; edgelab.slice peak 49 MiB of 384 MiB.
    - CHASE_UPSIDE_HEALTH: HEALTHY through 14:59 ET; UNHEALTHY from at least 18:51 ET
      (Brisket /api/health 503 "degraded", contract_ok=false: Brisket's own data contract,
      not Market Edge; all Brisket units active; not touched).
  - First real window (target 2026-09-24): pfm, decision (6 books) and recheck (6 books)
    all complete inside their windows; status VALID, no reasons; valid_days = 1.
  - First real shadow day, both accounts: 12 decisions, 2 qualified, 2 filled
    (B66.5 NO @0.56, B70.5 YES @0.08, 1 contract each), 0 NO_FILL, 0 risk vetoes, starter
    policy not yet in effect for that decision time; 4 positions pending settlement.
  - F09: CLOSED for the anchored history (GATE7_FINDINGS). Two independent checkpoints
    (487c744d at 2 entries; 89581b5a at 30 entries), each stored off-host (laptop) and in
    Git (docs/engineering/ledger_checkpoints/). Production ledger VERIFIED on the VPS;
    off-host verifies VERIFIED, and the first checkpoint EXTENDED.
  - Code merged (squash), each independently reviewed, blockers and should-fix items fixed
    and re-reviewed, CI 3.11 and 3.12 green on the exact head:
    - #42 Polymarket US depth ladders, binary payoff guard, per-market price grids
      (ADR 0023);
    - #43 execution-ticket pre-submit control chain (data only; always
      EXECUTION_NOT_AUTHORIZED);
    - #44 ntfy push sink (ADR 0022): disabled, unwired, allowlist ntfy.sh only, one-file
      POST exception;
    - #45 Windows portability, including two real src leaks (SnapshotStore connections,
      outbox fchmod);
    - #48 docs (directive record, activation record, F09 evidence, roadmap). This PR
      closes the claim.
    - Parallel sessions merged #46 (tailnet-only dashboard) and #49 (Terminal v1 UI).
  - Windows 3.12 full suite (nothing deselected): 1214 passed, 16 skipped, exit 0 after
    #45 (before: 15 failures plus a process-killing SIGTERM test). Later heads were
    re-verified per PR.
UNRESOLVED:
  - Settlement lifecycle on real data: not yet observed (positions settle after Kalshi
    publishes 2026-09-24's result; the settlement timer runs 11:15 and 16:15 ET).
  - F09 residual (ADR 0021): entries after 2026-09-23T22:47:20Z are unanchored until the
    next manual checkpoint.
  - Starter policy: first enforced for decisions from 2026-09-24T00:00Z (tomorrow's
    window); not yet observed in production.
  - Polymarket US rules include "resolves 50-50" on cancellation: the adapter's Payoff
    must model or refuse it before any Polymarket US market can qualify (they reject
    today: rules unresolved, fees unsupported).
  - The grid check has no production caller yet (ADR 0023); the #30 comparator and the
    ticket must pass Market.price_grid.
  - Brisket: /api/health 503 "degraded" (contract_ok=false) since ~18:47-18:51 ET, and
    6 dynasty-* refresh units in a failed state (pre-existing). Not Market Edge; untouched;
    needs the owner or a Brisket session.
  - The same SSH key authenticates as root (owner-known; hardening is a separate task).
  - Carried: fee account type owner-attested; EXACT not claimable; the no-scheduled-change
    check must be re-done by 2026-10-23T13:39:48Z; TWC cannot be checked directly;
    PFMOKX thinning; the NHIGH rule rests on one observation.
BLOCKERS: NONE for the running system. Owner decisions pending (none blocks collection):
  1. ntfy first real send (ADR 0022): approve and choose a private topic; the token is
     optional.
  2. The Odds API free key and activation plan (#29).
  3. SMS provider (#33).
  4. Novig developer credentials (#30).
NEXT ACTION: let tonight's timers run. Tomorrow: read latest.json and shadow_daily.json,
  confirm the first settlement after Kalshi publishes 2026-09-24, and export the next F09
  checkpoint (manual) after a few real days.
```

## Daily operation (what runs by itself)

| ET time | Unit | Does |
|---|---|---|
| 17:45 | edgelab-pfm | captures the NWS PFM forecast |
| 17:55:05 | edgelab-decision | captures the event, markets and order books in the decision window |
| 18:05 | edgelab-recheck | captures the confirmation books |
| 18:30 | edgelab-status | writes `latest.json` (VALID/INVALID with reasons) |
| 18:40 | edgelab-shadow | bookkeeping from stored evidence; writes `shadow_daily.json` |
| 11:15, 16:15 | edgelab-settlement | a bounded settlement refresh once positions are due, then bookkeeping |
| 04:40 UTC | edgelab-backup | verified backups of the evidence DB and the shadow ledger |
| always | edgelab-dashboard | read-only dashboard, tailnet-only (Tailscale Serve) |

Read the state without sudo: `cat /var/lib/market-edge-lab-status/latest.json` and
`shadow_daily.json`, or `bash /opt/market-edge-lab/app/deploy/vps/verify_production.sh`
(root sees journals and backups too). Deploy only with
`docs/deploy/DAILY_SHADOW_ACTIVATION.md`, never during 17:40–18:35 ET. The laptop bridge
remains MANUAL EMERGENCY FALLBACK ONLY.

## F09 checkpoint procedure (manual; no timer)

1. After the shadow run, `sudo systemctl start edgelab-backup.service` (a verified backup).
2. `sudo -u edgelab /opt/market-edge-lab/venv/bin/python -m edge_lab.cli shadow anchor export --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3 > /tmp/ckpt.json`
3. Copy it off the VPS (the owner's laptop, `market-edge-anchors/<date>/`) and commit a copy
   to `docs/engineering/ledger_checkpoints/`. Delete the VPS copy.
4. Copy the newest ledger backup's `database.sqlite3` and `manifest.json` to the laptop, and
   check its sha256 against the manifest. Run `shadow anchor verify` from a clean checkout
   at the deployed SHA against the new checkpoint (VERIFIED) and the previous one
   (EXTENDED).

## Gate 7 status (engineering vs research)

- **Engineering:** the suite is merged. F01–F08 and F10–F14 are FIXED. F09 is CLOSED for the
  anchored history, with the residual accepted in ADR 0021.
- **Production evidence:** deployed and verified; the first valid day and the first real
  shadow bookkeeping are recorded; settlement not yet observed.
- **Research evidence:** 1 valid Stage B day. The EXP-001 180/365-valid-day looks are far
  off, and nothing here is evidence of an edge.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 29.
- The binding constraint is now the calendar (at most one valid day per day), not
  deployment. The ordered roadmap is in `docs/OWNER_IDEAS.md` → Roadmap; the top NEXT item
  is the #30 best-price-for-size comparator.
- By 2026-10-22 the system can show:
  - a deployed, verified pipeline;
  - up to about 29 days of point-in-time shadow bookkeeping, claimable only as a lower
    bound;
  - settled results;
  - multi-venue read-only foundations.

  It cannot show an edge verdict.

## Open questions for the owner

1. **ntfy:** send real pushes? It needs your approval and a private topic.
2. **F09 cadence:** manual checkpoints weekly, or after notable days? A scheduled anchor needs
   separate approval.
3. **Root SSH:** the key that opens `dynasty` also opens root. Harden it later, as its own task?
4. **Brisket:** `/api/health` is 503 "degraded" (`contract_ok` false) since about 18:47–18:51 ET, and 6 `dynasty-*` refresh units have failed. Neither is Market Edge; neither was touched.

## UI (Terminal v1)

```
STATUS: DONE for the directive's code, review, merge and private deployment; owner visual acceptance on the phone pending.
ACCEPTANCE: owner directive docs/owner/2026-09-23-terminal-v1-ui-directive.md (issue #47);
  contract docs/design/UI_CONTRACT.md §12; ADR 0025.
EVIDENCE:
  - PR #49 squash-merged as f646481 (CI green 3.11/3.12 on the final head 6ca2be5; three rounds of
    independent review, no open blocker).
  - Local python -m pytest -o addopts="" -k "not sigterm": 1588 passed, 16 skipped, 3 deselected
    (baseline 7aac49c: 1495).
  - Browser audit (tests/browser/capture.py): 336 renders, Chromium + WebKit at
    360/390/430/768/1440/1920 over 3 fixture states. No overflow, clipping, low contrast or
    third-party requests. Emulated WebKit only; no physical-iPhone check yet.
  - Deployed 2026-09-23 18:52 ET via DAILY_SHADOW_ACTIVATION.md:
    - DEPLOYED_SHA 7aac49c -> f646481;
    - backups edge-backup-36jle2zs / ledger/edge-backup-b37xdtvk, both VERIFIED;
    - fail-closed check rejected_out_of_window (so last_failure.json shows edgelab-decision at 22:52:33Z by design);
    - dashboard restarted; verifier: 7/7 timers, no failed units, COLLECTOR_HEALTH VALID.
  - The tailnet URL serves the new UI on real data. Serve is unchanged; there is no Funnel.
UNRESOLVED:
  - Shown as unavailable rather than derived (docs/design/IMPLEMENTATION.md): calendar-day
    "Realized today"; which risk headroom binds; cross-venue equivalence; sport/league identity;
    phone delivery status.
  - Outcome rows show the raw outcome-cluster id; a plain-language label is a follow-up.
  - Once after the restart, the tape read "No quotes captured yet" while captures existed. Five
    later renders were correct and it was not reproduced. When the loader errors, the tape
    should say "unavailable" rather than "none yet" (follow-up).
  - CHASE_UPSIDE_HEALTH is UNHEALTHY: Brisket /api/health returns 503 "degraded". This predates
    this install and is not Market Edge.
BLOCKERS: NONE.
NEXT ACTION: the owner opens the tailnet URL on the iPhone and reviews Terminal, Markets, the
  market detail and Portfolio against UI_CONTRACT.md.
```

- Every user-visible change now follows docs/design/UI_CONTRACT.md (AI_INSTRUCTIONS.md, section User interface). New features use docs/design/FEATURE_INTEGRATION.md, and the PR template asks for the UI evidence.
- Rollback: /opt/market-edge-lab/app.prev (7aac49c), per DAILY_SHADOW_ACTIVATION.md → Rollback. No store or schema changed.
