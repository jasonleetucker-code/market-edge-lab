# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-29 ~11:50 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the batch that followed the 2026-09-28 directive
(`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`): the EXP-002 E1 endpoint and
the label-proxy closures. The earlier 2026-09-29 state is in git history (#128)._

```
STATUS: DONE for this batch. Every PR is merged, and production d508773 is DEPLOYED and
  PRODUCTION_VERIFIED. EXP-002 stays DRAFT and cannot freeze: E1 is implemented as a PROPOSED endpoint
  that computes no entries until its tie and not-played bounds are declared. The owner decisions of
  docs/owner/2026-09-29-vf-decision-packet.md are unchanged and still open.
ACCEPTANCE: the HANDOFF NEXT ACTION of #128:
  - implement the EXP-002 E1 executable round-trip endpoint (versioned, label-safe, reviewed);
  - close the Polymarket T-60m label proxy;
  - add the UI_CONTRACT section 8 gate-line clause;
  - no expansion of authority, no EXP-001 change, no protocol freeze.
EVIDENCE:
  - MERGED, each with an independent review (READY), review fixes, exact-head CI green on 3.11/3.12,
    and reconciled with main:
    - #129 (99fc32f): EXP-002 E1 endpoint `exp002-e1-roundtrip-v1`, measurement v3.
      - Entry uses T-6h information only. Without --with-results, only label-free entry counts are shown;
        tests prove no T-60m book, exit or settlement is read.
      - Exit, P&L and settlement run only on the logged --with-results path, recorded before display.
      - Gross only (FEE_UNSUPPORTED); no verdict; freeze_eligible False.
      - Invalid E1 bounds are refused before the store opens.
    - #130 (e0d3330): Polymarket US related-market captures at T-60m, or after a game's T-6h decision
      cutoff, are withheld on the Terminal and in `pm-sports status`. UI_CONTRACT 2026-09-29
      amendment: (a) the section 8 gate-line clause; (c) the Polymarket label-proxy state.
    - #131 (0d1e210): the remaining CLI label paths are closed:
      - `sports_evidence report` related proxies;
      - `observe status --market kalshi:KXNFL...` T-60m and post-cutoff books and settlement reads
        (KXHIGHNY and EXP-001 rows are byte-identical).
      Also fixed #130's flaky "777" test (a uuid substring collision). An inventory of every command is
      in the PR.
    - #132 (d508773): The Odds API NFL sportsbook data at T-60m, or after the cutoff (consensus,
      dispersion, per-book prices, implied probabilities, tie-adjusted intervals), is withheld:
      - on the Terminal Odds capture targets;
      - in `odds consensus`;
      - in plain report rows.
      The cutoff rule now has one owner, `odds_schedule.decision_cutoff`, used by `polymarket_sports`
      and `price_observations`. A logged --with-results run records the consensus it shows.
      UI_CONTRACT amendment (d).
  - DEPLOYED with /root/deploy.sh (preflight PASS, backups verified before and after, fail-closed PASS,
    no failed edgelab units, 13 timers):
    - e0d3330 at 13:16Z. Production: 15 Polymarket captures withheld, 28 pre-decision captures shown.
    - 0d1e210 at 14:23Z. Production: 60 of 180 captured Kalshi NFL rows (T-60m) show no figures;
      120 shown.
    - d508773 at 15:44Z. Production: `odds consensus --since 2026-09-20` withholds 16 events and shows 47;
      the Data sources page shows the withheld state.
  - E1 on production, label-free (exp002 without --with-results, 13:17Z):
    - measurement v3; gates v2 and v3 both INSUFFICIENT_DATA;
    - E1: 0 entries, all BOUNDS_UNDECLARED (the protocol leaves t_max and u_max UNKNOWN);
    - T-6h AT_OR_AFTER_ODDS pairing yield 15/16 = 0.9375 (week of 09-22).
  - EXP-002 evidence-use log: six hand-recorded POSSIBLE exposures, none a confirmed view; check-frozen
    and validate pass:
    - eu-7f8e6128… and eu-f4954194… (#124/#126): the Terminal T-60m book, 2026-09-26 to 02:09:50Z;
    - eu-4defeb1a…: Polymarket T-60m on the Terminal and pm-sports status, 2026-09-26 to 13:16:16Z;
    - eu-1b511255…: its closing follow-up for the CLI paths, to 14:24:17Z;
    - eu-9a3aeaf3…: Odds T-60m consensus, 2026-09-24 to 14:36:08Z;
    - eu-d9f8610f…: its closing follow-up, to 15:45:00Z.
    Consequence: none further. Pilot data are DEVELOPMENT only, and the evaluation window starts after
    the freeze (no earlier than 2026-10-22).
UNRESOLVED:
  - EXP-002 freeze blockers (freeze proposal section 5), none cleared by this batch:
    1. review of the E1 design change;
    2. a sourced tie and not-played count behind t_max and u_max (E1 needs declared bounds to enter);
    3. the A.C timing calibration;
    4. KXNFLGAME fees (FEE_UNSUPPORTED);
    6. the owner freeze review, 2026-10-22.
    Unresolved from #129: reading `settlement_value_dollars` as the YES payoff of a tie is unverified.
  - Kalshi message revision 2 (Q7 a–d, Q9, Q10): NOT SENT; awaits the owner's confirmation and channel.
  - Data rights: which terms govern our API-collected data is UNRESOLVED (packet B).
  - Raw-evidence access (direct SQLite, backups, snapshot APIs) is not a label view and is unchanged
    (#131 inventory).
  - Routine:
    - O1 weekly pull about 2026-10-03;
    - F09 by about 2026-10-03 (an apply refuses after 8 days);
    - retention dry run and apply at the owner's cadence;
    - DST check after 2026-11-01;
    - fee re-checks: Kalshi 10-23, Polymarket US 10-24.
  - ntfy deferred by the owner.
BLOCKERS (owner-only; docs/owner/2026-09-29-vf-decision-packet.md):
  1. Confirm the Kalshi message revision 2 and its channel (optional: EXP-003 hours).
  2. The data-rights review: read the Kalshi Developer Agreement.
  3. Optional: approve the in-play source-quality pilot (after 2 and a reviewed recorder).
NEXT ACTION: source an official NFL tie and not-played count for t_max and u_max (freeze blocker 2),
  then do the label-free A.C timing calibration (FEATURE_INSPECTION, logged). Run the O1 pull and F09
  around 2026-10-03.
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
