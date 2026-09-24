# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-24 ~11:40 America/New_York by the ChatGPT Market session after the
owner's 11:24 ET follow-up on ntfy delivery, scheduled later/closing observations, and the
always-on freshness requirement (#74)._

```
STATUS: PARTIAL. Production remains faadaa1 and healthy as last verified. PR #76 is open for the
  newly approved scheduled later/closing-price observations; it is NOT merged or deployed yet.
  The first ntfy TEST was accepted by ntfy (SUBMITTED) but the owner confirmed it did NOT arrive
  on the phone. Odds API remains live under the existing 450-credit monthly ceiling.
ACCEPTANCE:
  - owner follow-up 2026-09-24 11:24 ET: record failed ntfy phone delivery honestly and approve
    scheduled later/closing-price capture;
  - issue #74: preserve continuous/staggered freshness as a P0 design rule while keeping the
    generalized Freshness Orchestrator as NEXT;
  - no change to Gate 7, EXP-001, execution authority, credentials or paid-service authority.
EVIDENCE:
  - PR #75 merged as 0a13672, bringing main's handoff to production faadaa1 and releasing the
    previous coordinator claim.
  - ntfy: exactly one prior TEST was SUBMITTED/accepted by ntfy; owner confirmation at 11:24 ET:
    PHONE DELIVERY FAILED / NOTHING RECEIVED. Provider acceptance is not end-to-end success.
  - Owner approved ADR 0030 Option A at 11:24 ET.
  - PR #76 implements the approved schedule:
    - edgelab-observe.timer: :05, :20, :35, :50 each hour, Persistent=false;
    - edgelab-observe-close.timer: 04:57:45 UTC, Persistent=false;
    - both reuse observe plan/capture, protected windows, the collector lock, Kalshi pacer,
      bounded GETs, append-only evidence and MISSED accounting;
    - installer, read-only verifier, tests, rollback docs, execution authority and roadmap updated;
    - observation status no longer claims manual-only operation.
  - Existing ADR 0030 estimate for EXP-001 Option A: about 30 network GETs/day across five actual
    capture windows; idle ticks make no request/write; under ~100 MB/year projected payload storage.
  - Production facts carried forward from faadaa1:
    - 8 timers active before PR #76 deployment; no edgelab failed units in the last verification;
    - first 2026-09-24 settlement check exited 0 with nothing due; first real settlement is possible
      from 2026-09-25 11:15 ET;
    - shadow ledger remained 30 entries and verified against the 2026-09-23T224720Z checkpoint;
    - Odds API smoke: 3 credits, 16 events, 856 offers, 9 books; 497 remaining at smoke time.
UNRESOLVED:
  - PR #76 needs exact-head CI and independent deployment/systemd review, then merge and deployment
    through docs/deploy/DAILY_SHADOW_ACTIVATION.md outside protected capture/settlement windows.
  - After deployment, verify both observation timers enabled/active, run observe status, and confirm
    actual CAPTURED/MISSED evidence for the next due targets; do not infer capture from timer state.
  - ntfy end-to-end phone delivery is broken/unverified. Diagnose subscription/client delivery
    without reading the secret topic into an agent transcript. A later TEST can prove delivery only
    after remediation and with appropriate owner authorization for the send.
  - First paid Odds targets today (14:15 and 19:15 ET) still need CAPTURED/MISSED verification.
  - First real settlement: 2026-09-25 11:15 ET at the earliest; after a real ledger change take the
    manual F09 checkpoint and verify payout, fees, P&L, cash release, equity, duplicates and hash chain.
  - A later-price row in Terminal v1 remains optional/unbuilt.
  - Fee re-checks remain: Kalshi by 2026-10-23T13:39:48Z; Polymarket US by 2026-10-24T01:39Z.
BLOCKERS:
  - PR #76 merge/deploy: exact-head CI + independent review.
  - ntfy phone delivery: subscription/client path needs diagnosis; no secret exposure.
NEXT ACTION: independently review PR #76, resolve any blocker, require exact-head CI green, merge,
  deploy via DAILY_SHADOW_ACTIVATION.md, verify the two new timers and first observation evidence,
  then diagnose ntfy delivery without rotating/exposing the topic unless evidence requires it.
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
| after shadow/settlement/any failure alert | edgelab-notify | relays new outbox events and unit failures to ntfy (fixed headlines) |
| every 15 min | edgelab-odds | game-relative NFL odds capture (T-24h/T-6h/T-60m) under the 450-credit budget; enabled 2026-09-24 13:40Z; a paid call only for an admitted slot |

**Pending PR #76, not yet production:** add `edgelab-observe` at :05/:20/:35/:50 each hour and
`edgelab-observe-close` at 04:57:45 UTC. Until deployment, production still has the eight timers
recorded above.

Read the state without sudo: `cat /var/lib/market-edge-lab-status/latest.json` and
`shadow_daily.json`, or `bash /opt/market-edge-lab/app/deploy/vps/verify_production.sh`
(root sees journals and backups too). Deploy only with
`docs/deploy/DAILY_SHADOW_ACTIVATION.md`, never during 17:40–18:50 ET (2026-09-24 owner rule) or a settlement run. The laptop bridge
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

- **Remaining calendar days:** 28.
- The binding constraint is now the calendar (at most one valid day per day), not
  deployment. The ordered roadmap and the Domain Readiness matrix are in
  `docs/OWNER_IDEAS.md` → Roadmap (re-run 2026-09-24).
- By 2026-10-22 the system can show:
  - a deployed, verified pipeline;
  - up to about 29 days of point-in-time shadow bookkeeping, claimable only as a lower
    bound;
  - settled results;
  - multi-venue read-only foundations.

  It cannot show an edge verdict.

## Owner decisions recorded 2026-09-24

1. **ntfy:** approved and activated at the relay/provider level. The owner rotated the topic after
   exposure and subscribed; one TEST was SUBMITTED/accepted by ntfy, but at 11:24 ET the owner
   confirmed **nothing arrived on the phone**. End-to-end delivery is unresolved.
2. **F09 cadence:** manual, roughly weekly, plus after notable ledger events. No timer.
3. **Root SSH:** a separate future security task, outside Market Edge missions.
4. **Brisket:** the `/api/health` fix is done (riskittogetthebrisket#1405, deployed `15b43f4`,
   verified). The owner scoped this session to that fix only. The six failing `dynasty-*` refresh
   units are diagnosed and handed off in riskittogetthebrisket#1409:
   - #1407 is a ready fix for the import-path and EvidenceStatus failures;
   - #1406 records the DLF root cause and needs an owner decision;
   - playerctx is on a WIP branch.
5. **The Odds API:** the owner installed the free key privately. Activated 2026-09-24 (runbook
   §5b activation record). No paid plan, no credit purchases, no props, no other sports.
6. **Later/closing observations:** the owner approved ADR 0030 Option A at 11:24 ET: staggered
   hourly due-target checks plus the dedicated close-window tick. This is read-only evidence
   collection. The generalized #74 Freshness Orchestrator remains NEXT.

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
