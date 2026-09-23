# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-23 (UTC), by the final-state PR of the 2026-09-23 integration and
production directive (`docs/owner/2026-09-23-integration-production-directive.md`)._

```
STATUS: PARTIAL.
  - DONE and MERGED: the repository work for directive sections 2-5, 7-12, 14-16.
  - NOT DONE: production verification and deployment (sections 1 and 6). This cloud
    session has no SSH client or key, TCP/22 to the VPS is unreachable, and the directive
    forbids copying keys to cloud agents. Every production state below is UNVERIFIED.
ACCEPTANCE: the 2026-09-23 integration directive, recorded verbatim with the owner's four
  clarifying answers.
EVIDENCE:
  - Merged (squash), each independently reviewed, blockers fixed, re-reviewed, CI 3.11 and
    3.12 green on the exact head:
    - #34 directive record, idea-intake re-planning rule, shared primitives (dcd1362);
    - #35 Kalshi fee evidence and multi-component verification, ADR 0017 (879e770);
    - #37 GATE7-F09 checkpoint support (ADR 0021) and read-only production verifier (18cd8b3);
    - #38 STARTER_MAX_7D_V1, venue registry, execution-ticket contract, notifications,
      ADRs 0018-0020 (566f352);
    - #39 read-only adapters: Polymarket US, The Odds API (fixtures), Novig, discovery (see
      git log for the squash SHA).
  - Tests: python -m pytest -o addopts="" -> 1091 passed at the #39 head (Python 3.11,
    local). CI covers 3.11 and 3.12. Windows was not available.
  - Reachability checks from this session (2026-09-23): TCP/22 to 169.58.50.224
    unreachable; https://chaseupside.com/api/health returned HTTP 200 (public endpoint only,
    which says nothing about Market Edge).
UNRESOLVED:
  - Production (all UNVERIFIED from this session):
    - deployed SHA (last recorded: 9326a7a, read 2026-09-23 02:20 UTC, before PR #26);
    - collector installed, timers enabled, PFM/decision/recheck capture observed, valid day
      observed;
    - shadow and settlement timers (not installed as far as the repository knows);
    - backups and restores of the evidence DB and the shadow ledger;
    - Chase Upside unit health and resources.
  - Shadow pipeline on real data: no real decisions, fills, settlements or vetoes are known
    to this session.
  - Fees:
    - the account type is owner-attested only (direct member);
    - multi-fill rebates are bounded (0.0101 USD per contract), not modelled exactly;
    - the no-scheduled-change check must be re-done by 2026-10-23T13:39:48Z, or new
      decisions fall back to claim basis NONE.
  - Starter policy: Kalshi's tradable hold is DOCUMENTED_INFERRED, not read from an
    account. Fills recorded by pre-upgrade production code after 2026-09-24T00:00Z carry
    no verdict; they are counted, never rewritten.
  - GATE7-F09 OPEN: the tool exists, but no independent checkpoint has been stored and
    verified off-host.
  - verify_production.sh has never run on the real VPS. Its journal parsing is tested
    against synthetic journal lines only.
  - Polymarket US website terms could not be read (a JavaScript app). One bounded GET was
    made on the strength of the API docs.
  - Follow-up (code): `opportunity.evaluate` does not yet reject a non-binary `Payoff.kind`.
    It is safe today because sportsbook odds never become quotes, but the check belongs in
    the engine before any non-binary venue is evaluated.
  - Carried over: TWC cannot be checked directly; PFMOKX thinning; the NWS User-Agent has no
    contact address; dynasty's NOPASSWD allowlist is root-equivalent (Chase Upside, not this
    repo).
BLOCKERS: all owner-only; none for code.
  1. Production: run the command sheet below on chaseupside with the owner's existing access.
  2. F09: store the first off-host ledger checkpoint (below).
  3. The Odds API: install the free key in server env config, then approve an activation
     and quota plan (issue #29). Never paste it into chat or Git.
  4. SMS: choose and approve a provider (issue #33); none is configured.
  5. Novig live API: request developer credentials if wanted (issue #30).
NEXT ACTION: the owner runs `bash verify_production.sh`, then the activation sheet, then
  the script again, outside 17:40-18:35 America/New_York, and pastes the STATE lines back.
```

## Owner command sheet (production; this session could not run it)

One procedure only: `docs/deploy/DAILY_SHADOW_ACTIVATION.md`. In short:

1. Check the New York time. Never install or restart between 17:40 and 18:35
   America/New_York, or while any `edgelab-*` unit is running.
2. **Before:** stage `verify_production.sh` from the merged SHA (§1 of the sheet), run
   `bash verify_production.sh` as dynasty, then with sudo, and keep the output.
3. Follow §1–§5 of the sheet with the **latest `main` SHA**:
   - stage the bundle and scripts, then run `preflight.sh`;
   - back up;
   - `install.sh --sha <SHA>`;
   - the fail-closed dry run, the shadow dry run and the settlement refresh;
   - a second backup, then check the slice;
   - `sudo systemctl enable --now edgelab-shadow.timer edgelab-settlement.timer`.
4. **After:** run `bash /opt/market-edge-lab/app/deploy/vps/verify_production.sh` again.
   Each directive state prints separately: DEPLOYED_SHA, COLLECTOR_HEALTH, SHADOW_TIMER,
   SETTLEMENT_TIMER, BACKUP_/RESTORE_ for each store, CHASE_UPSIDE_HEALTH, and the six
   collector states.
5. **F09 checkpoint** (manual, no timer):
   `sudo -u edgelab /opt/market-edge-lab/venv/bin/python -m edge_lab.cli shadow anchor export --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3 > checkpoint.json`.
   Keep a copy off the VPS, in a private repo or with the owner. Later, verify it
   **off-host** from your own checkout against a copied backup (ADR 0021).
6. Laptop bridge: MANUAL EMERGENCY FALLBACK ONLY. No laptop scheduler.

## What changed this session

- **Fees (ADR 0017).**
  - The PDF (sha256 `c326a69f…9601`, effective 2026-07-07) verifies the 0.07 coefficient.
    KXHIGHNY is on the general schedule with multiplier 1 (PDF plus API). There are no
    scheduled changes as of 2026-09-23.
  - The rounding mechanics are verified; the account type is owner-attested (direct).
  - Claim basis is **CONSERVATIVE_BOUND**: a claim uses net minus 0.0101 USD per
    contract. Claims are point-in-time from 2026-09-23T13:39:48Z.
  - The full schedule is **NOT** verified, and EXACT is not claimable.
  - The frozen EXP-001 cost model is untouched. The first review showed the plain frozen
    cost is not an upper bound for orders split into fractional fills; the allowance is
    what can be proven.
- **Seven-day starter policy (ADR 0018).**
  - The governing clock is `tradable_cash_release_eta`: tradable within 168 elapsed hours
    of the commitment, computed in UTC.
  - For KXHIGHNY the ETA is the expected expiration, plus the settlement timer, plus a 49 h
    buffer derived from 698 events, plus Kalshi's zero hold (documented, inferred). The
    fixture day comes out at about 94 h, which is eligible.
  - Anything unknown, delayed or non-open fails closed.
  - It is enforced from 2026-09-24T00:00Z in the operational shadow account only; the
    research account is untouched.
  - It is exposed in decisions, fills, the receipt, Stage B `operational_eligibility`, the
    dashboard and the ticket contract.
- **Owner-idea system.** The canonical re-planning rule is in `AI_INSTRUCTIONS.md`, with a
  Shared primitives table and a NOW/NEXT/LATER/BLOCKED roadmap in `docs/OWNER_IDEAS.md`.
- **Notifications (ADR 0020).**
  - One provider-neutral contract (13 event types), with dedupe, expiry, rate limits
    (CRITICAL never limited) and bounded retries.
  - Delivery is to a local outbox. The SMS sink is disabled: no provider and no paid
    service.
  - A notification failure never changes a result.
- **Venues (ADR 0019).** One registry, with execution authorized for none.
  - Kalshi: LIVE_DATA_VERIFIED reads.
  - Polymarket US: TESTED, plus one live smoke read.
  - Novig: public daily files TESTED; the live API is NEEDS_ACCESS.
  - The Odds API: TESTED on fixtures; NEEDS_ACCESS for a key.
- **F09 (ADR 0021).** `edge-lab shadow anchor export|verify` detects truncation and
  rewrites against an external checkpoint. F09 stays OPEN until one is stored and verified
  off-host.

## Gate 7 status (engineering vs research)

- **Engineering:** the suite is merged. F01–F08 and F10–F13 are FIXED. F09 is OPEN, with
  support code in place.
- **Production evidence:** none from this session (no access).
- **Research evidence:** none. The EXP-001 180/365-valid-day looks are unchanged.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## Dashboard (local, read-only)

```
edge-lab dashboard --db <evidence.sqlite3> --ledger <shadow_ledger.sqlite3> --status-dir <status dir>
edge-lab dashboard --demo
```

New this session: fee claim basis and components, the starter-policy panel with exceptions,
a 7-day column, the venue registry and notifications. Runbook: `docs/DASHBOARD.md`.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 29.
- **The ordered roadmap** is in `docs/OWNER_IDEAS.md` → Roadmap. The critical path is still
  one owner SSH session: deploy, verify, enable.
- Stage B cannot reach 180 valid days by 2026-10-22. What 2026-10-22 can show:
  - a deployed, verified pipeline;
  - point-in-time claimable (lower-bound) shadow bookkeeping under the starter policy;
  - multi-venue read-only foundations.

  It will not show an edge verdict.
