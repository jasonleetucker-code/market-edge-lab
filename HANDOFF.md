# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-28 ~23:25 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the owner directive of 2026-09-28
(`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`). The state of 2026-09-26
is in git history (#121)._

```
STATUS: DONE for this mission's buildable scope. Every PR is merged, and production e00a335 is
  DEPLOYED and PRODUCTION_VERIFIED. EXP-002 cannot freeze: gate v3 has no PASS state, and its
  spread-noise candidate failed validation. The #122 in-play foundation is offline only. Owner
  decisions are in docs/owner/2026-09-29-vf-decision-packet.md.
ACCEPTANCE: the directive of 2026-09-28:
  - reconcile #120/#121;
  - a defensible replacement EXP-002 gate, or a precise reason why a freeze stays unsupported;
  - proposed freeze settings;
  - fee verification;
  - a gate line in the Terminal;
  - the #122 offline foundation, a feasibility packet and one proposed pilot;
  - an in-play Terminal view;
  - no expansion of authority.
EVIDENCE:
  - CI: the owner fixed the GitHub billing block on 2026-09-28. Every merge below had an
    independent review, re-reviews until READY, exact-head CI green on 3.11/3.12, and was
    reconciled with main.
  - MERGED:
    - #121 (0250885): the 2026-09-26 handoff, the retention record, F09 2026-09-26T151756Z, the
      directive record and VF claims.
    - #120 (4e8e71d): the /dev/stdin runbook fix, fail-closed F09 cadence, a junction-safe
      re-verifying O1 prune.
    - #123 (47526d1): #122 indexed.
    - #124 (29a37d7): EXP-002 gate v3, the freeze proposal, fee verification (unresolved), and the
      Terminal gate line. It also closed a label path: the Terminal "latest paired book" and the
      full report could show T-60m books without logging.
    - #126 (e8d4949): closes the UNKNOWN pilot T-60m exposure window at the #124 deploy,
      2026-09-29T02:09:50Z.
    - #125 (24a70b4): the #122 offline foundation: inplay_evidence, position_policy, inplay_replay,
      INPLAY_SOURCE_FEASIBILITY.md and ADR 0038.
    - #127 (e00a335): the read-only in-play Terminal page. It is never LIVE; production shows "No
      in-play source is authorized".
  - DEPLOYED (/root/deploy.sh: preflight PASS, backups verified before and after, fail-closed
    PASS, no failed units, 13 timers):
    - 4e8e71d (2026-09-29 00:15Z);
    - 29a37d7 (02:09Z);
    - e00a335 (03:17Z): /experiments/inplay returns 200 and reads "Not authorized"; /gallery/inplay
      returns 404 on production.
  - EXP-002 gate v3 (docs/research/EXP002_GATE_V3*.md):
    - The spread-noise candidate failed the ≤ 10% false-pass acceptance: 98% worst, 21 of 37
      settings over. The bound conditional on "value inside the spread" is 0% where that holds and
      88% where it fails.
    - v3 therefore returns only FAIL, INSUFFICIENT_DATA or INSUFFICIENT_EVIDENCE, and is never
      freeze-eligible. Its 0% false-pass rate comes from having no pass path; it is not a
      certificate.
    - The v2 results are preserved.
    - Production run (read-only, 02:10Z): v3 INSUFFICIENT_DATA (15 admissible T-6h games < 20;
      1 week < 4). v2 INSUFFICIENT_DATA (0 repeats).
  - EXP-002 label exposure: whether pilot T-60m books were seen is UNKNOWN (possible Terminal
    display, not logged). It is recorded as two hand events (eu-7f8e6128…, eu-f4954194…): the
    window runs 2026-09-26 to 2026-09-29T02:09:50Z, DEVELOPMENT only. Evaluation may start only
    after that time. Production's evidence_use.jsonl had only its header before these records.
  - Fees: KXNFLGAME stays FEE_UNSUPPORTED. The public documents don't resolve the multiplier
    mapping, schedule currency, overrides or maker-fee start. Nothing is set to zero.
  - #122 offline foundation:
    - snapshot + delta books, with seq tracked per subscription (scope UNVERIFIED);
    - a pure HOLD/REDUCE/EXIT policy that never liquidates on stale books;
    - hold / full-exit / partial-exit replay, with bot-triggered and preplaced sales kept separate;
    - isolated accounting (no oversell or double counting; INCOMPLETE is never 0);
    - calibrated synthetic nulls with no alpha before costs, including at realistic latency.
    It uses synthetic and fixture data only; real data is refused without an experiment id.
  - Production (2026-09-29 00:01Z):
    - valid_days 6;
    - shadow realized −1.98 per account, 14 pending;
    - NFL week of 09-22: 45 game-horizons, 136 expected / 271 worst of 295; 180 CAPTURED;
    - Polymarket 43 CAPTURED / 2 MISSED;
    - both restores VERIFIED; 62 GB free.
UNRESOLVED:
  - EXP-002 freeze: blocked. Next: implement the proposed E1 round-trip endpoint (versioned,
    reviewed); verify KXNFLGAME fees; a pilot report within the 6 owner hours. The 2026-10-21
    freeze is not promised.
  - Kalshi message revision 2 (Q7 a–d, Q9, Q10): NOT SENT; awaits the owner's confirmation and
    channel.
  - Data rights: which terms govern our API-collected data is UNRESOLVED (packet B).
  - Label proxy: Polymarket related-market T-60m captures on the Terminal Data sources tab are a
    possible weak proxy for EXP-002 labels. They are not hidden. Follow-up: hide T-60m Polymarket
    prices for NFL games inside the EXP-002 pilot/evaluation scope, or record the exposure.
  - UI_CONTRACT §8 has no one-clause mention of the EXP-002 gate line. Writer A's proposed text is
    in #124; it needs a dated amendment.
  - Routine:
    - O1 weekly pull due about 2026-10-03;
    - F09 due by about 2026-10-03 (an apply refuses after 8 days);
    - retention dry run and apply at the owner's cadence;
    - DST check after 2026-11-01;
    - fee re-checks: Kalshi 10-23, Polymarket US 10-24.
  - ntfy deferred by the owner.
BLOCKERS (owner-only; docs/owner/2026-09-29-vf-decision-packet.md):
  1. Confirm the Kalshi message revision 2 and its channel (optional: EXP-003 hours).
  2. The data-rights review: read the Kalshi Developer Agreement.
  3. Optional: approve the in-play source-quality pilot (after 2 and a reviewed recorder).
NEXT ACTION: implement the EXP-002 E1 executable round-trip endpoint (versioned; label-safe;
  reviewed), and run the O1 pull and F09 around 2026-10-03.
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
| :05, :20, :35, :50 | edgelab-observe | ADR 0030 Option A: plan later/closing-price targets, then bounded capture only when due; deferred in protected windows; enabled 2026-09-24 20:32Z; since 2026-09-25 also Kalshi KXNFLGAME books after each Odds NFL capture (owner-approved #110, `EDGE_LAB_KALSHI_NFL_CAPTURE=off` pauses it) |
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
  shadow bookkeeping are recorded; the first real settlement is recorded and verified
  (2026-09-25, KXHIGHNY-26SEP24), with an F09 checkpoint.
- **Research evidence:** 6 valid Stage B days (`latest.json` valid_days = 6, `verify_production.sh`
  at 2026-09-29 00:01Z). The EXP-001 180/365-valid-day looks are far off,
  and nothing here is evidence of an edge.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 23 (as of 2026-09-29).
- The binding constraint is now the calendar (at most one valid day per day), not
  deployment. The ordered roadmap and the Domain Readiness matrix are in
  `docs/OWNER_IDEAS.md` → Roadmap (re-run 2026-09-24).
- By 2026-10-22 the system can show:
  - a deployed, verified pipeline;
  - up to about 28 days of point-in-time shadow bookkeeping, claimable only as a lower
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
  - RESOLVED (2026-09-25): CHASE_UPSIDE_HEALTH was UNHEALTHY (Brisket /api/health 503
    "degraded"); it has been HEALTHY at every EV1 verification.
BLOCKERS: NONE.
NEXT ACTION: the owner opens the tailnet URL on the iPhone and reviews Terminal, Markets, the
  market detail and Portfolio against UI_CONTRACT.md.
```

- Every user-visible change now follows docs/design/UI_CONTRACT.md (AI_INSTRUCTIONS.md, section User interface). New features use docs/design/FEATURE_INTEGRATION.md, and the PR template asks for the UI evidence.
- Rollback: /opt/market-edge-lab/app.prev holds the previous release (29a37d7 as of the e00a335 deploy, 2026-09-29 03:17Z; install.sh keeps exactly one), per DAILY_SHADOW_ACTIVATION.md → Rollback. Previous bundles are kept under ~dynasty/edgelab-release/prev-<sha>/. No store or schema changed.
