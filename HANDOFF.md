# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-24 ~22:05 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the Freshness Fabric v1 + sports directive, the cross-domain prospective
evidence directive (#86), #88 Public Markets, and the Polymarket US owner risk decision._

```
STATUS: DONE for the build scope: every PR is merged, DEPLOYED and PRODUCTION_VERIFIED
  (production f5bfa6e). Still pending, time-based and not buildable tonight:
  - the first close observation, 04:57:45Z;
  - the first Polymarket US research capture, 2026-09-26 16:53Z;
  - the first real settlement and the manual F09 checkpoint, 2026-09-25 11:15 ET at the earliest.
  Owner decisions are open on backup retention and ntfy (out of scope).
ACCEPTANCE: the owner directives of 2026-09-24 (evening), recorded in docs/owner/:
  freshness-fabric-sports, cross-domain-prospective-evidence; #88 in docs/EXECUTION_PLAN.md; and
  the Polymarket US risk decision. Each is judged against its own section list.
EVIDENCE:
  - MERGED, each with an independent review, re-reviews until READY, exact-head CI green on
    3.11/3.12, and reconciled with main:
    - #78 and #87: directives and authority;
    - #79: consensus benchmark and readiness;
    - #80, #85, #91, #94: Terminal phases 1-4 (targets, consensus, source freshness,
      related Polymarket markets);
    - #81: Freshness Fabric v1 and the supervisor;
    - #84: Polymarket US NFL pilot (ADR 0032, schema v7);
    - #89: acquisition portfolio, source readiness and combined budget (#86, #88);
    - #90: Multi-City Weather v1 design and verification;
    - #92: canonical roadmap reconciliation (#88 first-class);
    - #95: read-only units may create SQLite WAL side files;
    - #72, #75, #77: earlier handoffs.
  - DEPLOYED via DAILY_SHADOW_ACTIVATION.md, preflight-gated, with verified backups before and
    after and fail-closed PASS (held, not pushed):
    - c6e0dd9 at 19:36 ET: #79, #80, #81, #85; Freshness supervisor enabled;
    - 1c62368 at 20:36 ET: #84, #91; schema v7; Polymarket US §5e activation;
    - f5bfa6e at 21:56 ET: #94, #95.
  - Process slip: at 19:36 ET preflight FAILED on host load (a Brisket scrape at 127% CPU) and the
    install proceeded because the command chain did not stop on it. The install was clean, but a
    required gate was skipped; `/root/deploy.sh` now refuses unless preflight prints PASS.
    Separately, a sandbox negative test appended (refused, "Read-only file system") to the live DB
    and quota file. Both were verified intact (DB quick_check ok, mtime and size unchanged; the
    ledger parses). Never write-probe live evidence again.
  - PRODUCTION_VERIFIED (verify_production.sh, 01:57Z):
    - DEPLOYED_SHA f5bfa6e; failed units: none;
    - 13 timers enabled: 7 core, 2 observation, freshness, odds, 2 Polymarket US pilot;
    - COLLECTOR_HEALTH VALID, valid_days 2 (2026-09-24, 2026-09-25);
    - FRESHNESS_STATUS CURRENT: 15 sources (8 FRESH, 4 STALE, 3 UNKNOWN), 0 disagreements,
      0 unreadable;
    - backup and restore of both stores VERIFIED; the shadow ledger has 60 entries;
    - Chase Upside HEALTHY; disk 63 GB free; edgelab.slice peak about 80 MB.
  - Terminal on production data shows: Source freshness; Odds capture targets (95; 2 captured);
    "Consensus at this capture · RESEARCH BENCHMARK — NOT EXECUTABLE"; Polymarket US related
    markets ("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"; "Allowed by an owner risk decision ·
    not a terms clearance").
  - ADR 0030 observations: the first scheduled network capture was at 19:05 ET, 12 +1 h rows
    CAPTURED (7 Kalshi requests). The 18:50 plan planned tonight's 42 targets.
    close_tick_alignment is ALIGNED (KXHIGHNY close 05:00:00Z).
  - The Odds API: 2026-09-24 T-6h (18:15Z, snapshot 24) and T-60m (23:15Z, snapshot 53) ATL@GB
    were both CAPTURED at 3 credits each. Quota: 9 used, 491 remaining, no reservations.
  - Polymarket US pilot (owner RISK DECISION, not a grant; the attested text is UNVERIFIED):
    - §5e manual discovery was FILTER_COMPLETE: 2 pages, 2 requests, 33 games/markets, verified
      from stored rows;
    - 32 games RELATED_NOT_EQUIVALENT; 93 targets planned;
    - timers enabled; first ticks NOTHING_DUE / NOT_DUE with 0 requests.
  - Settlement: the 11:15 and 16:15 ET runs had nothing due. Positions are due from
    2026-09-25T03:50Z.
  - #86 Wave 1: portfolio, readiness and budget (#89); Multi-City Weather v1 design (#90), 12
    cities verified live. Implementation is queued behind backup retention.
UNRESOLVED:
  - The first close observation (04:57:45Z) and pre-close (00:50 ET): verify from stored rows.
  - The first Polymarket US research capture (T-24h, 2026-09-26 16:53Z): verify per runbook §5e
    step 5.
  - The first real settlement (2026-09-25 11:15 ET, or 16:15): verify event, outcome, source,
    payout, fees, P&L, cash release, equity for both accounts, duplicates and the hash chain. Then
    take the manual F09 checkpoint.
  - The WAL fix is verified with side files present, and on production in a sandbox test. Confirm
    FRESHNESS_STATUS keeps 0 unreadable across a quiet period.
  - Backup growth is quadratic: full uncompressed daily copies, never deleted, with a 30 s timeout.
    A NOW prerequisite before any new collector (#86).
  - ntfy: the phone is subscribed to a different topic than production (server path proven clean).
    Out of scope; owner action.
  - close_tick_alignment re-check after the 2026-11-01 DST change. Fee re-checks: Kalshi by
    2026-10-23T13:39:48Z; Polymarket US by 2026-10-24T01:39Z.
BLOCKERS (owner-only):
  1. The backup retention/deletion policy.
  2. The ntfy phone subscription.
  3. Free keys when wanted (FRED/ALFRED, BEA, EIA, Census; Alpaca paper data after the security
     ADR).
NEXT ACTION: after the 2026-09-25 11:15 ET settlement run, verify the first real settlement and
  take the manual F09 checkpoint. Then decide backup retention so Multi-City Weather v1 can start.
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
| :05, :20, :35, :50 | edgelab-observe | ADR 0030 Option A: plan later/closing-price targets, then bounded capture only when due; deferred in protected windows; enabled 2026-09-24 20:32Z |
| 04:57:45 UTC | edgelab-observe-close | the KXHIGHNY close-window capture (close 05:00:00Z; `observe status` → `close_tick_alignment`); enabled 2026-09-24 20:32Z |
| every 5 min (:01, :06, ...) | edgelab-freshness | Freshness Fabric v1 supervisor (ADR 0031): network-free; writes `freshness.json`; supervises every schedule, controls none |
| :10, :25, :40, :55 | edgelab-pm-sports | Polymarket US NFL research book captures at T-24h/T-6h/T-60m (ADR 0032; owner risk decision); related, never equivalent |
| 02:47, 08:47, 14:47, 20:47 | edgelab-pm-sports-discover | Polymarket US NFL filtered listing discovery (at most 12 requests a scan) |

Production has 13 enabled timers: 7 original core, 2 observation, 1 Freshness supervisor, 1 Odds and 2 Polymarket US pilot.

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
- **Research evidence:** 2 valid Stage B days (2026-09-24, 2026-09-25; `verify_production.sh`
  COLLECTOR_HEALTH, 2026-09-25 01:57Z, as recorded above). The EXP-001 180/365-valid-day looks
  are far off, and nothing here is evidence of an edge.
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
