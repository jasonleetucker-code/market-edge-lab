# Capture and backup approval plan (Kalshi NFL capture, backup retention)

Research-unblocking directive of 2026-09-25 (`docs/owner/2026-09-25-research-unblocking-directive.md`), §8, §11 and parts
of §14–15. Writer: RU Writer O (operations). Date: 2026-09-25 (America/New_York evening).

**Status vocabulary.** Every item below is labelled with one of these:
- **CURRENT:** true of the code or production today.
- **PROPOSED:** a recommendation, not approved.
- **APPROVED:** an owner approval is recorded, and the record is cited.
- **BLOCKED:** cannot proceed; the blocker is named.
- **VERIFIED:** checked by a named test, measurement or document.

A recommendation is not an approval.

**What is and is not approved:**
- **APPROVED:** Kalshi NFL capture. The owner approved it on 2026-09-25 ("Approve Kalshi NFL capture"). The record is in `docs/EXECUTION_PLAN.md` via PR #110, bounded by `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §6, review 2026-10-22. PR #110 is merged (886fbff), and the implementation, PR #112, is merged (c05bd8a).
  - **c05bd8a is DEPLOYED and PRODUCTION_VERIFIED as of 2026-09-25 23:23Z.** The coordinator reports:
    - preflight PASS;
    - backups verified before and after the install;
    - `verify_production`: DEPLOYED_SHA c05bd8a, COLLECTOR_HEALTH VALID, restores VERIFIED.
  - The production `nfl-dry-run` showed switch ON, 0 targets planned (no Odds capture due) and `odds_api_calls` 0.
  - No NFL capture had run yet at that point, so the capture itself is not yet verified in production.
- **APPROVED on 2026-09-26:** backup retention policy `proposed-v1` (manual, reviewed deletion only) and O1 (the free weekly off-host pull). The owner's words are recorded verbatim in `docs/owner/2026-09-26-owner-decisions-economics-backup.md`, items 3–4.
  - Paid storage is **not** approved.
  - The apply step and the O1 tooling are implemented in `backup.py`: `retention-apply`, `newest-verified` and `offhost-verify`.
  - The operator runbook is `docs/deploy/DAILY_SHADOW_ACTIVATION.md` §7–9.
  - Nothing has been deleted until the coordinator records the first reviewed apply.

**Inputs.**
- Production figures were measured read-only by the coordinator on 2026-09-25 at about 21:15Z. This writer has no production access.
- Every other figure comes from code in this repository, from the recorded fixtures, or from offline measurements described where they are used.

---

## A. Kalshi NFL capture (§8)

### A1. The decision: APPROVED, and how the implementation fits it

| Item | Status | Value |
|---|---|---|
| Market family | APPROVED | `KXNFLGAME` only: both team markets of each game the Odds API pilot captures. No NCAAF, no other market type, no new horizon. |
| Horizons | APPROVED | The Odds pilot's T-24h / T-6h / T-60m captures. |
| Collector | APPROVED; implemented in PR #112 | The existing `price_observations` collector and `edgelab-observe` timer. No new unit, timer or schema. |
| Per game-horizon | APPROVED; VERIFIED by tests (#112) | 1 listing page + 2 book GETs, and at most one retry each: **≤ 6 GETs**. |
| Settlement metadata | APPROVED; VERIFIED by tests (#112) | At most one settled-markets read per ET game day, never retried: **≤ 7 a week**. |
| Weekly bound | APPROVED; VERIFIED by tests (#112) | ≤ 48 game-horizons + ≤ 7 reads: **≤ 288 + 7 = 295 GETs a week**. |
| Per-run caps | CURRENT; unchanged | 24 markets and 40 GETs per observe run, 4-min run deadline, 6-min `TimeoutStartSec`. |
| Odds API credits | APPROVED: zero | No Odds call is added. The 450-credit monthly ceiling is untouched. |
| Review | APPROVED | 2026-10-22 (A11). |

PR #112 implements this, as revised after independent review (head 5a5632b). Its hard guards are code constants and each has a test:
- KXNFLGAME-only tickers, and exactly the T-24h / T-6h / T-60m horizons (`NFL_HORIZONS`).
- **At most 6 GETs per game-horizon:**
  - `retries=0` inside a run.
  - At most 2 runs may send GETs for one game-horizon (1 for a settled read), whatever the run: scheduled, close tick or manual.
  - A book deferred after its listing counts as that run's attempt.
- `NFL_WEEKLY_GAME_HORIZONS=48` and `NFL_WEEKLY_SETTLEMENT_READS=7`.
- **EXP-001 always keeps priority.**
  - NFL targets are ordered after every ADR 0030 target, close groups included.
  - A run with a due EXP-001 close target attempts no NFL target at all.
  - NFL targets are kept out of the EXP-001 `price_observations.later` freshness record.
- **No NFL failure pages.** Failures are recorded FAILED, listed in `nfl_failed`, and never enter the exit code or `edgelab-observe`'s OnFailure alert.
- Zero Odds calls.
- Protected windows.
- Idempotent target ids.
- Point-in-time mapping.
- The kill switch.

### A2. How the capture works (CURRENT: deployed c05bd8a, production-verified 2026-09-25 23:23Z; first NFL capture not yet observed)

1. **Pairing is reactive.** It deviates from the wording of §6 ("at the Odds target's effective due time"), and the coordinator accepted the deviation on 2026-09-25.
   - A Kalshi target is planned only after its Odds target is `CAPTURED`. Its target time is the Odds receipt time.
   - The next `edgelab-observe` tick fetches the listing and the two books. Observe ticks are at :05/:20/:35/:50 America/New_York; Odds ticks are at :00/:15/:30/:45.
   - The book therefore always *follows* the odds it is compared with. A decision time equal to the book receipt uses only information available then.
   - No book is fetched for a horizon the Odds pilot skipped (budget) or missed.
2. **Discovery and pagination.** There is no separate discovery GET.
   - The event ticker is derived: `KXNFLGAME-<YY><MON><DD><AWAY><HOME>`. The team letters come from `sports_evidence.NFL_TEAMS`, which is tested against the recorded listing. The date is the game's originally scheduled New York date, taken as the earliest Odds commence time recorded for that event.
   - The capture's per-event listing (`/markets?event_ticker=…&limit=1000`, one page) is the discovery. It is inside the per-game-horizon budget.
   - A KXNFLGAME event has 2 markets, so one page always suffices. The NFL path never requests a second page.
3. **Mapping.** Only listings received at or before the planning time are consulted (point in time; the dry run too).
   - With none stored, the tickers are **DERIVED**, and the first capture verifies them.
   - A stored listing that lists both markets with the expected labels makes the mapping **LISTED**.
   - A stored listing that lacks them (**NOT_LISTED**) or labels them differently (**AMBIGUOUS**) stops further planning for that game. A wrong derivation therefore costs at most one game-horizon (≤ 6 GETs).
4. **Rules capture.** Every listing snapshot stores `rules_primary` / `rules_secondary`, and every observation row stores their hash (`rules_sha256`). The rules are therefore stored at every horizon.
5. **Book capture.** `/markets/<ticker>/orderbook?depth=100` for each team market. Rows are CAPTURED or NOT_EXECUTABLE, with freshness and the depth ladder, exactly as for ADR 0030 observations.
6. **Settlement metadata.** One read per ET game day that has NFL books:
   - URL: `/markets?series_ticker=KXNFLGAME&status=settled&min_settled_ts=<day start>&max_settled_ts=<read time>&limit=100`.
   - Timing: the first unprotected observe tick after the day's last kickoff + 6 h 30 min. The recorded listing has `expected_expiration_time` = kickoff + 6 h.
   - The filter pair is the one the Kalshi GetMarkets documentation lists as compatible with `status=settled` (https://docs.kalshi.com/api-reference/market/get-markets, read 2026-09-25, documentation only, no API call). `min/max_close_ts` are compatible only with `closed` or an empty status.
   - Behaviour: one page, no book, never retried. A failure is recorded FAILED and then MISSED, and never pages.
   - Status: **VERIFIED against the documentation; not yet exercised in production.**
7. **Retry and timeout budget.**
   - Each GET gets at most 10 s (`forward.REQUEST_TIMEOUT_S`) and no in-run retry.
   - A failed game-horizon is retried once, at the next tick (15 min later). The target window is the Odds receipt + 29 min, and at most two ticks fit in it.
   - Independently of the window, a run guard allows at most 2 GET-sending runs per game-horizon.
   - The observe run's 4-min deadline and the unit's 6-min `TimeoutStartSec` bound everything.
   - NFL failures never fail the run.
8. **Rescheduled games.**
   - The Odds pilot supersedes targets whose commence time moves. New captures are paired as usual.
   - The Kalshi ticker keeps the originally scheduled date (tested).
   - A game not started within 48 h resolves to a fair price under the recorded rules (§3 of the gaps doc). The settled read of that day records whatever settled.
9. **Partial failures.**
   - A failed listing fails both markets of that game-horizon; they are retried once.
   - A failed book fails only its market.
   - A market that is no longer open is NOT_EXECUTABLE, with the listing snapshot kept.
   - Every miss is a MISSED row with its reason. Nothing is fetched late.

### A3. Recalculated request figures (VERIFIED from code and the recorded schedule)

**Schedule used.** The recorded KXNFLGAME listing (`tests/fixtures/sports_evidence/`) holds two real weeks of 16 games each. The 2026-09-24 → 09-28 week had:
- 1 TNF game;
- 9 games at 13:00 ET on Sunday;
- 2 at 16:05 and 2 at 16:25;
- SNF;
- MNF.

That is 3 game days a week (Thu, Sun, Mon). The following week adds a 09:30 ET London game on Sunday.

| Unit | Expected | Worst (every GET needs its one retry) | Hard bound in code |
|---|---|---|---|
| Per game-horizon | 3 GETs | 6 | 6 |
| Per game (3 horizons) | 9 | 18 | 18 |
| Per settlement read (per game day) | 1 | 1 (never retried) | 1 |
| Per observe run (the Sunday 13:00 group, 9 games, at the 12:05 T-60m tick) | 27 GETs, 18 markets | 27, then 27 at the retry tick | 40 GETs, 24 markets (existing caps) |
| Busiest day (Sunday: T-6h and T-60m of about 14 Sunday games, plus MNF T-24h: 29 game-horizons) | 87 | 174 | n/a (the weekly cap binds) |
| Normal week (16 games: 48 game-horizons, 3 game days) | **147** (144 + 3) | **291** (288 + 3) | **295** (288 + 7) |
| Rest of the season (about 15 regular weeks + 13 playoff games) | about 2,340 | about 4,640 | n/a |

**Consistency checks:**
- These match the handoff's "about 144 a week, 288 worst". The difference is the settlement reads (+3 expected, +7 bound).
- Reactive pairing can only lower the numbers: a horizon the Odds pilot skips costs nothing.
- **Kalshi GETs are public, unauthenticated market data (`kalshi_public`): no key and no credits.** They are separate from the Odds API credits, and no Odds call is added.

**Per-run overflow.** One observe run fits 12 games (24 markets, 36 GETs). If an Odds slot ever holds 13 or more games, the rest are deferred to the next tick (+15 min). The deferral uses up that game-horizon's retry tick. The recorded schedule's largest slot is 9 games.

### A4. Pairing precision (achievable receipt skew)

Reusing the observe timer does **not** establish precision. What the two timers allow:

| Case | Skew of book receipt after the Odds receipt | How often |
|---|---|---|
| Normal | about **5 min** (4.5–6): the observe tick is 5 min after the Odds tick; Odds call latency is seconds; within a run the book is 0–30 s later (≤ 12 games × 3 GETs at the 0.6 s Kalshi pacer); `AccuracySec` is 30 s (odds) and 15 s (observe) | almost every pair |
| The observe tick refused by a protected window, or the lock busy | about **20 min** (the next tick) | Odds captures at 11:15 or 16:15 ET only. No regular NFL horizon lands there. |
| The one retry after a failure | about **20 min** | only after a failed GET |
| A slot of more than 12 games | about **20 min** for the overflow | none in the recorded schedule |

**Consequence for EXP-002 (a pairing-limit input for Writer R; not decided here).** The join's current default `max_pair_skew` is 5 min (`sports_evidence.KALSHI_BOOK_MAX_AGE`), and it would reject almost every pair.
- The floor with two timers is about 5 min.
- A limit of about 7 min admits the normal case.
- About 25 min also admits the refused and retry cases.
- Under option (a), pairs beyond the frozen limit stay in the denominators as PAIR_SKEW_EXCEEDED.
- Writer R's provisional window (`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` A.C, PROPOSED) runs from the book 5 min before the odds to 10 min after. That window admits the normal case (+5 min). It still excludes the +20 min cases, which is consistent with this table.

**Option (b), same-run capture (PROPOSED follow-up, not built).** The Odds runner would fetch the two books right after its own call and pair within seconds. This needs a runner change, review, and a new shared-lock decision, because the Odds tick and the Kalshi pacer lock would then meet.

### A5. Bytes, database growth and backup impact (VERIFIED offline)

**Measured, and reproducible from the repo:** `python -m pytest tests/test_price_observations_nfl_bytes.py -s`. The real capture path (`plan` + `capture`) runs against a temporary store, with a fake fetch serving the recorded KXNFLGAME listing and a Kalshi order book:
- 96 game-horizons grow the database by **21.6 KB each** with a recorded 1.4 KB book;
- **22.1 KB each** with a full-depth synthetic book (99 levels a side, 4.2 KB).
- This includes the snapshots, observation rows, targets, runs and indexes.
- The test asserts the 15–30 KB band.
- The recorded listing is 4.95 KB per event in canonical JSON (158,491 B for 32 events).

A settled read is about 2.2 KB per market (at most 26 markets a day), plus about 1 KB of rows.

| | Per week | Rest of season |
|---|---|---|
| Books and listings (48 × 22 KB) | about 1.06 MB | about 16.8 MB |
| Settled reads | about 0.07 MB | about 1 MB |
| **Total** | **about 1.1 MB a week, about 0.16 MB a day** | **about 18 MB** |

The evidence store grows about **2.0–2.8 MB a day** today. Measured 2026-09-24 20:31Z → 09-25 20:17Z it was +2.75 MB, and since the 09-25 04:40Z backup it has run at 2.0 MB/day. NFL adds about **6 %**.

Backup impact:
- Each full backup copy carries it. With no retention, at 3 copies a day for the rest of the season, it adds about 4 GB of backup copies.
- Under the proposed retention (Part B) it adds at most about 0.5 GB: about 29 kept copies × about 18 MB.

NFL is **not** what makes backup growth material; the copy count is (Part B).

### A6. Shared lock, protected windows, source isolation (CURRENT)

- **Shared lock.**
  - `observe plan` and `observe capture` hold `<db>.forward.lock`, shared with the EXP-001 forward captures, which run only inside their protected window. A busy lock means nothing is done, and the next tick retries.
  - The Odds pilot uses its own tick lock, and the Polymarket US pilot its own.
  - The backup holds only the ledger lock, and only for the ledger copy.
- **Shared pacer.** The Kalshi pacer (0.6 s) is shared with every Kalshi read in the process.
- **Protected windows.** Plan and capture refuse 11:13–11:30, 16:13–16:30 and 17:40–18:50 ET before any request (tested). The Odds pilot's own quiet window (17:40–18:35 ET) moves its targets out, and Kalshi pairs follow. No regular NFL horizon falls in any window.
- **Source isolation.**
  - Kalshi is `kalshi_public`: keyless, read-only, and never sent an Odds key.
  - The NFL code reads Odds targets from the store only.
  - A Kalshi failure never touches the Odds pilot's state, and vice versa.
  - Stored as snapshots (`markets`, `orderbook`, `settled_markets`) and price-observation rows, which are the shapes `sports_evidence` already reads.

### A7. Stale and missing states (CURRENT)

- A target not captured by its deadline becomes **MISSED**, with a reason: not captured, the attempt limit, the switch off, or a protected-window overlap.
- A market that is not open is **NOT_EXECUTABLE**, and no price is stored.
- An Odds horizon with no capture produces no Kalshi target. `sports_evidence` reports that horizon's pair as **NO_LISTING / KALSHI_NOT_MAPPED** or **PAIR_SKEW_EXCEEDED**. Missing is never zero, and a later book is never substituted.

### A8. Activation, pause and rollback (APPROVED mechanism, coordinator decision on #112)

- **Activation = deploy.** The switch `EDGE_LAB_KALSHI_NFL_CAPTURE` defaults to **on** (unset or `on`). The reviewed, deployed code is the activation record.
  - Before the first tick, run the read-only preview. It makes no writes and no requests:
    `python -m edge_lab.price_observations nfl-dry-run --db …`.
- **Pause (kill switch):** `EDGE_LAB_KALSHI_NFL_CAPTURE=off` in `/etc/market-edge-lab/env`.
  - The next plan run plans nothing.
  - The next capture run records pending NFL targets (at most about 30 min ahead) MISSED, with `NFL_CAPTURE_DISABLED`, and sends no request.
  - `install.sh` keeps the key across installs, so a pause survives deploys. The accepted values are exactly `on` or `off`, lowercase, both in `install.sh` and in the code. Anything else fails the install, and in code it fails closed (off).
- **Resume:** set the switch to `on`, or remove the line.
- **Permanent rollback:** keep `off`, then deploy a reviewed change that reverts the default.
- **Stored evidence is kept**, and there is no schema change to undo.

### A9. After the first slot (PROPOSED verification checklist)

1. Run `observe status`: expect NFL targets CAPTURED for both team markets.
2. Run `sports_evidence report --summary`: G1/G2 should turn PARTIAL, and the report shows the pair skew and mapping (MAPPED, home_away MATCH).
3. The Freshness Fabric should show the observe schedule healthy.
4. Check the first game day's settled read: `SETTLEMENT_METADATA_READ` with a non-zero count, or a documented failure.

### A10. The approval choice, as recorded, and one smaller alternative

**Recommended and APPROVED (wording as recorded, PR #110):**
> Approve Kalshi NFL capture: KXNFLGAME only, both team markets of each game the Odds pilot targets, at its T-24h, T-6h and
> T-60m capture times; per game-horizon at most 1 listing plus 2 book GETs with at most one retry each; at most one
> settled-markets read per game day (7 a week at most); at most 288 + 7 GETs a week; the existing per-run caps of 24
> markets and 40 GETs; the existing price_observations collector and edgelab-observe timer, no new timer, unit or schema;
> protected windows, the shared pacer and lock apply; zero Odds API credits; review 2026-10-22.

**Smaller alternative (PROPOSED, only if the owner wants to cut scope).** T-60m only, still paired, and still no new unit:
- **48 GETs a week expected, 96 plus 7 worst**, about 0.4 MB a week.
- It keeps the closing-line comparison.
- It loses the T-24h and T-6h information horizons, which EXP-002's endpoint may need.

### A11. Review on 2026-10-22 (PROPOSED agenda)

1. The weekly GETs actually sent, against 147 expected and 295 bound.
2. The capture rate per horizon, and the MISSED reasons.
3. The pair-skew distribution, against the A4 table.
4. The settled reads (filter behaviour).
5. Bytes per game-horizon, against 22 KB.
6. Any effect on ADR 0030 observations. There should be none: deferrals of non-NFL targets = 0, and the EXP-001 freshness record ignores NFL.
7. Whether NFL failures should ever alert. Today they never page, by design; that is an owner decision.

Decision options: continue, cut to T-60m, pause, or move to option (b).

---

## B. Backup retention (§11)

### B1. What exists (CURRENT)

**Backup code** (`src/edge_lab/backup.py`):
- `create` makes a unique bundle with an online SQLite copy (WAL-aware) and an integrity and foreign-key check of the copy and the source.
- The schema, triggers and row counts must match the source.
- The manifest is written last, with the database SHA-256.
- `verify` re-hashes the bundle and restores it into a disposable database, and replays the ledger chain for ledger bundles.
- The code has no retention and never deletes.

**Timeouts.**
- `--timeout` defaults to **30 s, separately for create and for verify**. The unit passes none.
- `edgelab-backup.service` has `TimeoutStartSec=20min`, `CPUQuota=25%` and `MemoryMax=256M`.

**Schedule.**
- A daily timer at 04:40 UTC.
- The deploy helper also runs the backup unit **before and after every install**, and stops if the pre-install backup is not VERIFIED for both stores.
- F09 (manual, roughly weekly and after notable ledger events) takes a backup and exports a ledger checkpoint (`docs/engineering/ledger_checkpoints/`).

**Restore.**
- Restore is rehearsed on every create (verify) into a temporary database.
- There is no scripted restore *over* the live store; it is a manual operator step with the timers stopped.

### B2. Measured inventory (CURRENT)

| Item | Value | Source |
|---|---|---|
| Evidence store | 3,383,296 B, schema v7, WAL | coordinator's read-only measurement, 2026-09-25 about 21:15Z |
| Shadow ledger | 258,048 B | same |
| Backups directory | 48,305,019 B: 45 evidence bundles and 42 ledger bundles, 2026-09-23 02:20Z → 09-25 20:17Z | same (a per-bundle inventory of manifests) |
| Evidence bundle size | 73,728 B → 3,375,104 B | same |
| Cadence | 3 daily-timer runs; 42 manual/deploy evidence bundles in 2.75 days, about **7.6 deploys a day** during the build-out (two backups per deploy) | derived from the inventory's timestamps |
| Backup duration (create) | 0.19–2.7 s per store; it does not grow measurably between 0.07 and 3.4 MB (fixed cost dominates) | the manifests' started/completed times |
| Restore check | about 0.6 s (evidence), about 0.25 s (ledger) | `verify_production`'s RESTORE_* lines and the W0 verification |
| Free disk | 67.1 GB of 102.9 GB (shared with Chase Upside) | coordinator's read-only measurement, 2026-09-25 about 21:15Z |
| Verified off-host database backup | **none**. The laptop holds the F09 checkpoint JSONs (in git and `market-edge-anchors/`) and two ad-hoc copied bundles in a scratchpad. A checkpoint is not a restorable backup, and ad-hoc copies are not a policy. |

**Three different things.**
- The **live store is the only original evidence**.
- **Backup copies** are redundant, restorable copies of it.
- **Ledger checkpoints** are head hashes, and prove only that the ledger was not truncated or rewritten.

Deleting a backup copy never deletes evidence, as long as a newer kept copy contains every one of its rows. The planner enforces that condition (B5).

### B3. Is growth material? When? (VERIFIED arithmetic; the assumptions are explicit)

**Assumptions.**
- Evidence grows 3.0 MB/day: about 2.8 today, with the NFL stream and the Polymarket US captures from 2026-09-26 on top.
- A 5.0 MB/day stress case.
- Every backup is a full, uncompressed copy of both stores.
- With no retention, the directory holds the sum of all copies. It grows as copies/day × (S₀·d + G·d²/2): the square term is the "quadratic", in bytes.
- **Only this project's growth is counted.** The disk is shared with Chase Upside, whose growth is not included. Every date below is therefore an upper bound on how long the free disk lasts.
- The projections were computed with uncommitted scratch scripts. They are arithmetic on the inventory and the formula above, and can be recomputed from this section; they are not reproducible from a committed repo script.

| Scenario (copies a day) | Backups after 30 d | 90 d | 180 d | Hits 10 GB | Free disk down to 20 % (about 46 GB used) | Disk full |
|---|---|---|---|---|---|---|
| E: daily timer only (1) | 1.6 GB | 12.7 GB | 49.6 GB | day 80 | day 175 | day 210 |
| A: timer + 1 deploy/day (3) | 4.6 GB | 37.9 GB | full | day 46 | day 100 | day 121 |
| B: timer + 2 deploys/day (5) | 7.6 GB | 63.2 GB | full | day 35 | day 77 | day 93 |
| C: build-out pace (16) | 24.1 GB | full | full | day 19 | day 43 | day 52 |
| D: stress (11 copies, 5 MB/day) | 26.8 GB | full | full | day 18 | day 40 | day 49 |

Day 1 is 2026-09-26.

**Answer.**
- **Not material today**: 48 MB of backups and 67 GB free.
- **Material within weeks at the current deploy pace.** At build-out pace, the backups reach 10 GB about **2026-10-14** and bring the free disk under 20 % about **2026-11-07**.
- At one deploy a day those dates move to about **2026-11-10** and **2027-01-03**.
- The copy count drives this, not the NFL stream (about 6 % of growth).
- The retention decision should therefore be made **by about 2026-10-08** (backups about 5 GB at build-out pace).

**The 30 s timeout.**
- The binding limit is the code's 30 s per step, not the unit's 20 min.
- Measured on the laptop, with an uncommitted scratch benchmark (not reproducible from the repo): create took 6 ms/MB and verify 5.4 ms/MB on a 102 MB synthetic store.
- Scaled ×4 for `CPUQuota=25%` and ×2 as a VPS margin, that is about 50 ms/MB, so 30 s is reached at about **600 MB** (the earlier estimate was 0.5–1 GB). At 3 MB/day that is about **day 200 (April 2027)**.
- **PROPOSED:** re-measure on the VPS when the store passes 100 MB, and ship a size-aware timeout (for example `max(30 s, 10 s + 0.1 s/MB)`) before it passes 250 MB.

### B4. The retention schedule: `proposed-v1` (APPROVED 2026-09-26, manual reviewed apply only)

Applies to **evidence bundles only**, per store directory.

**"Good" means restore-verified, not only a valid manifest.**
- A valid manifest and a matching size prove only that the copy completed.
- The unit's restore check (`verify`, run after every create) is not written into the bundle. It exists only as the JSON report in the `edgelab-backup` journal.
- The planner therefore counts a bundle as **good** only when a recorded `VERIFIED_BACKUP_AND_RESTORE` report matches its `database_sha256`. The reports come in through `--verify-reports`, for example `journalctl -u edgelab-backup.service -o cat` saved to a file. A `create` report must also name the bundle.
- A bundle without such a record is **UNVERIFIED_RESTORE**: always kept. It never counts as newest-good, never satisfies the 36 h freshness check, and never covers an older bundle.
- **Limitation:** the journal is the only record, and it may not reach back to old bundles. An old bundle without a record stays kept until it is verified again (`backup verify --bundle`) and that report is added.
- **The apply step's requirement (CURRENT in `retention-apply`):** immediately before deleting anything, restore-verify **every bundle it relies on**: each bundle that covers a candidate, and the newest bundle used for the freshness check, not only the newest one. If any of those checks fails, delete nothing.

**Keep:**

| Rule | Keep |
|---|---|
| Recent | **every restore-verified bundle younger than 48 h** (deploy pairs, quick rollback) |
| Newest good | the **3 newest restore-verified** bundles, always |
| Daily | the newest restore-verified bundle of each UTC day for **7 days** |
| Weekly | the newest restore-verified bundle of each ISO week for **8 weeks** |
| Monthly | the newest restore-verified bundle of each calendar month for **12 months** |
| Unverified | **every bundle without a recorded restore verification** |
| Pre/post-migration | **forever**: both bundles around every schema change (the last before, the first after) |
| F09 checkpoints | **forever**: the ledger bundle whose chain heads equal a checkpoint's, or else the bundles either side of it; and the evidence bundles either side of each checkpoint |
| Known-good baselines | **forever**: the first bundle of each store, and any pinned bundle |

**Initial pins.** These are committed in code as `backup.RETENTION_PINS_PROPOSED_V1`. They always apply, and an apply refuses a report without them:
- `edge-backup-eqfiomf5` (first production activation);
- `ledger/edge-backup-lqs5j63_` and `ledger/edge-backup-sdi31qqw`. Ad-hoc copies of these were taken to the laptop at F09 and checked there. That is not an off-host backup policy (B2, B6).
- the bundles around the first real settlement (2026-09-25; the settlement ran at 11:15 ET, 15:15Z):
  - the last evidence bundles before it: `edge-backup-iu9x5w73` (08:02Z) and `edge-backup-gci308lm` (08:03Z);
  - the first after it: `edge-backup-lgw9jmww` (20:16Z) and `edge-backup-wu3982g7` (20:17Z).

**F09-linked bundles are protected only through the canonical checkpoints.** An apply requires that the dry run used the deployed code's committed checkpoint directory, and that it is non-empty. So every F09 checkpoint must be committed and deployed before an apply (runbook §7).

**Never auto-deleted:**
- **ledger bundles** (0.26 MB each; revisit above 10 MB);
- **QUARANTINE** bundles;
- **ACTIVE** (in-progress) bundles;
- **UNVERIFIED_RESTORE** bundles (no recorded restore verification);
- **forensic ledger states** (missing triggers or a broken chain);
- any bundle whose rows **no newer kept, restore-verified copy of the same store covers**;
- every bundle while the **newest restore-verified bundle is older than 36 h**. If backups are being created but failing their restore check, this freeze trips, and everything is kept.

**What would be deleted:** only evidence bundles that meet all of these:
- the rules above do not keep them;
- a newer, kept, restore-verified copy of the **same store** meets or exceeds every one of their table row counts. Same store means the same store kind and database name, a schema no older than theirs, and the same schema fingerprint at the same version.

The store is append-only, so those rows exist in that copy too. Deletions happen only after an approval (B8) and an apply step that does not exist yet (see the PROPOSED requirement above).

**Simulated with the real planner code** (in memory, 365 days, candidates removed daily, every bundle assumed restore-verified; uncommitted scratch script):

| Copies a day | Kept after 90 d | 180 d | 365 d (store about 1.1 GB) | No retention at 365 d |
|---|---|---|---|---|
| 3 | 20 copies, 4.2 GB | 22, 9.2 GB | 29, **24.3 GB** | about 606 GB (impossible: disk full at day 121) |
| 5 | 24, 5.2 GB | 26, 11.3 GB | 33, **28.7 GB** | about 1 TB |
| 16 (build-out) | 46, 11.2 GB | 48, 23.3 GB | 55, **52.8 GB** | |

**Alternatives (PROPOSED).** Both were simulated the same way.
- **Conservative:** 72 h / 14 daily / 8 weekly / 12 monthly. At 365 days and 3 copies a day it keeps 37 copies, 32.9 GB.
- **Tight:** 48 h / 7 daily / 4 weekly / 6 monthly. It keeps 19 copies, 18.3 GB.

`proposed-v1` sits between them. Because the store is append-only and every copy is integrity-checked, the newest copies hold every row. The long tail protects only against an undetected logical error, for which 8 weekly and 12 monthly points are ample.

**Next lever after retention (PROPOSED, not needed yet).** Compressing bundles (SQLite pages typically compress 3–5×) when the kept bytes pass 20 GB (about day 300 at 5 copies a day). Verify would then need to decompress, which is a reviewed change.

**Today's result.** `proposed-v1` on the real 2026-09-25 inventory, replayed in memory at 21:15Z with an uncommitted scratch script:
- **Inputs:** the 3 F09 checkpoints (`docs/engineering/ledger_checkpoints/`) as `--checkpoints`. Every bundle was *assumed* to have a recorded VERIFIED report; the unit's journal reports runs as VERIFIED, but this was not matched per bundle here.
- **Result with the checkpoints:** **39 evidence bundles KEEP, 6 DELETE-CANDIDATE (442,368 B), 0 QUARANTINE**. All 42 ledger bundles KEEP.
- **Result without `--checkpoints`:** 8 candidates, 589,824 B (the coordinator's run).
- The candidates are schema-v4 deploy copies from 2026-09-23. Their rows are in the kept 2026-09-23 22:51Z bundle.
- On production, without `--verify-reports`, every bundle is UNVERIFIED_RESTORE, so there are 0 candidates, by design.

### B5. The dry-run planner (CURRENT; it deletes nothing) and the separate apply step

```
python -m edge_lab.backup retention-plan --root /var/lib/market-edge-lab/backups \
    [--policy proposed-v1] [--now ISO] [--checkpoints docs/engineering/ledger_checkpoints] \
    [--pin NAME]... [--verify-hashes] [--verify-reports FILE]
# FILE: the recorded restore checks, e.g. `journalctl -u edgelab-backup.service -o cat > FILE`
```

- **Read-only.** It reads bundle directories and manifests, and hashes databases only with `--verify-hashes`. It prints JSON: KEEP / DELETE-CANDIDATE / QUARANTINE per bundle, with reasons, a per-store summary, the checkpoint links and flags.
- **It has no deletion code path:** no `--apply`, no unlink, no rmtree. `tests/test_backup_retention.py` covers this two ways:
  - It checks the syntax tree of every function reachable from the CLI entry point for deletion, write and connect calls.
  - It makes every deletion, rename and write API fail while the CLI runs. Paths, sizes, modification times and contents must be unchanged afterwards.
- **Manifest validation.** The planner checks:
  - the format version and database name;
  - the store kind against its directory;
  - zone-aware start and completion times, none in the future;
  - that the database file is present, a regular file and not a symlink;
  - the byte length against the manifest (and the SHA-256 with `--verify-hashes`).
- **Corrupt or incomplete bundles are quarantined and reported, never deleted.**
  - A bundle without a manifest that was written within the last 30 min is **ACTIVE** (KEEP). The service's `TimeoutStartSec` is 20 min.
  - After 30 min it is **QUARANTINE: INCOMPLETE_NO_MANIFEST** (an interrupted backup).
- **Restore verification comes from the record.** A bundle is good only with a recorded `VERIFIED_BACKUP_AND_RESTORE` report (`--verify-reports`). Without one it is kept as UNVERIFIED_RESTORE and relied on for nothing (tested).
  - The planner itself restores nothing.
  - Any bundle can be checked with `python -m edge_lab.backup verify --bundle …` (a hash plus a restore into a temporary database), and that report can then be added.
- **Newest-good protection.** The 3 newest *restore-verified* bundles are always kept. If the newest restore-verified bundle is over 36 h old, every candidate is blocked. That includes the case where newer bundles exist but failed or lack their restore check (tested).
- **Store identity.** Only a restore-verified copy of the same store and schema lineage can cover an older bundle. A foreign bundle placed in the directory covers nothing (tested).
- **Deterministic.** The same inputs always give the same JSON, whatever the order (tested).
- **The apply step (CURRENT: `python -m edge_lab.backup retention-apply`; runbook §7).** It is a separate command that deletes only after every check below passes. Otherwise it exits 2 (`REFUSED`) having deleted nothing.
  - **Confirmation:** `--confirm` must equal the SHA-256 of the reviewed report file.
  - **Report:** it must be a `retention-plan` report for this root, at most 30 min old.
  - **Inputs:** the recorded verify-reports file and checkpoint files must be unchanged. Re-running the plan now must give the identical candidate set, by name and database hash.
  - **Directory:** the root must be a backups directory with no database files in it.
  - **Freshness:** no stale freeze may be on.
  - **Candidates:** every candidate must be an evidence bundle directly in the root, a plain directory of regular files, whose only reason is `SUPERSEDED`, not pinned, not checkpoint-linked, and naming its covering bundle.
  - **Restore checks:** every bundle the deletions rely on passes `verify_backup` now: each covering bundle and the newest good bundle.

  It deletes the candidate directories one at a time. Each deletion is logged to `retention-apply-log.jsonl` in the backups directory (append-only, flushed): name, hash, bytes, covering bundle, reason. The run's start line carries the full candidate list and the report hash. No timer or unit runs it. The planner still has no deletion path; a test checks that it never reaches the apply code.

### B6. Off-host (O1 APPROVED 2026-09-26; paid storage not approved)

**The exact procedure is `docs/deploy/DAILY_SHADOW_ACTIVATION.md` §8.**
- `newest-verified` on the server picks the newest restore-verified bundles.
- `scp` pulls them to `C:\Users\jason\market-edge-offhost\<date>\`.
- `offhost-verify` on the laptop checks each bundle's bytes against its manifest, then restores it into a disposable database.
- Only the last 4 **verified** pulls are kept. `offhost-verify` writes `VERIFIED.json` only when every bundle passes, and `offhost-prune` keeps the 4 newest pulls that carry it. A failed pull is never counted and never removed by the tool, so it cannot displace a verified one.

The text below is the original proposal.

- There is **no verified off-host database backup today**. A disk or VPS loss would lose the live store *and* every local backup.
- The laptop checkpoints prove the ledger head, but they cannot restore it.

**Options:**
- **Option O1 (recommended, $0).** A **manual weekly pull** to the laptop by the operator, over the existing access.
  - Pull the newest VERIFIED evidence and ledger bundles.
  - Run `backup verify` on the laptop, then keep the last 4 weekly pulls.
  - Size: 3.4 MB now; about 1.1 GB each at a year, about 4.4 GB kept.
  - Also do it at every F09.
  - No new service, no credential and no cost. The laptop is a single, occasionally offline copy.
- **Option O2 (paid, if wanted later).** Object storage with client-side upload.
  - At current sizes this is cents a month; about $0.30–1 a month at a year (tens of GB at typical per-GB-month object-storage prices).
  - It needs a credential, an account and an unattended job, so it is a separate owner decision.
  - Not recommended until the store is larger or the laptop is unavailable.

### B7. RTO and RPO tradeoffs (PROPOSED framing)

**RPO (data you could lose).**
- A local failure of the store: at most since the last verified backup. That is under 24 h via the timer, less when deploys add copies.
- A host loss: **unbounded today**, because there is no off-host copy. With O1 it is at most 1 week.

**RTO (time to restore).**
- The planned sequence: stop the timers, copy the bundle's `database.sqlite3` into place, run `backup verify` on it, then restart.
- Today this takes minutes of operator time. Verification is about 0.6 s at 3.4 MB, and about 30–50 s at 1 GB (estimate).
- The restore-over-live procedure is now written down as `docs/deploy/DAILY_SHADOW_ACTIVATION.md` §9 (PROPOSED: an incident step, not a routine one). It stops the timers, verifies the bundle, moves the live files aside (they are evidence, never deleted), copies the bundle in, checks, and restarts.

**Effect of retention.** Retention removes *intermediate* restore points only. RPO is unchanged, because the newest copies are always kept. Restoring to an old logical state keeps weekly granularity for 8 weeks and monthly for 12 months.

### B8. Approval wording (as proposed; the owner approved retention and O1 on 2026-09-26, recorded verbatim in `docs/owner/2026-09-26-owner-decisions-economics-backup.md`)

> I approve backup retention policy **proposed-v1** for the **evidence** store's local backups only:
> - count a bundle as good only when a recorded VERIFIED_BACKUP_AND_RESTORE report matches it;
> - keep every good bundle younger than 48 h, the 3 newest good bundles, the newest good bundle per UTC day for 7 days,
>   per ISO week for 8 weeks and per month for 12 months;
> - keep forever the first bundle, both bundles around every schema change, the bundles linked to each F09 checkpoint,
>   pinned baselines, and every ledger bundle;
> - never delete a QUARANTINE, ACTIVE, unverified or not-covered bundle (covered means a newer, good copy of the same
>   store holds all of its rows);
> - delete nothing while the newest good bundle is older than 36 h.
>
> Deletion is manual: an operator reviews the dry-run report, then runs a reviewed apply step. Immediately before
> deleting, the apply step restore-verifies every bundle the deletion relies on: each covering bundle and the freshness
> bundle. It deletes nothing if any check fails, and deletes only that report's DELETE-CANDIDATE bundles.
> No timer deletes. Review after 30 days.
> I also approve (or decline) a manual weekly off-host pull to the laptop (O1).

The **smaller alternative** is to approve no deletion yet, only O1 and the size-aware timeout. This buys about 3–6 weeks at the current deploy pace (B3) before the decision returns.

---

## C. The OWNER_IDEAS item 4 prerequisite (PROPOSED; for the coordinator to record)

The rule (`docs/OWNER_IDEAS.md` item 4 and the NOW list) reads: backup growth and retention are the prerequisite before any **new** production collector. It requires compression, a size-aware timeout, and a retention or off-host policy.

**Does NFL count as a "new collector"?**
- **Not as a collector:** there is no new unit, timer or process.
- **Yes as a new production stream.** OWNER_IDEAS itself says a new stream needs a purpose, budget and review date, and it has them (A1).
- The rule exists because of disk growth, and NFL adds about 0.16 MB a day (about 6 % of current growth). So the rule's purpose is not engaged by NFL.
- The owner's explicit approval supersedes the rule for this stream in any case.

**Do the rule's premises still hold, measured?**

| Premise | Measured | Verdict |
|---|---|---|
| "fills about 64 GB in about 400 days today" | 67.1 GB free. Growth is about 2.0–2.8 MB a day, and deploys add copies: 52–121 days to full at 3–16 copies a day, 210 days at 1 a day. | **Stale:** too optimistic |
| "85–180 days with the proposed collectors" | Close to scenarios A/B (93–121 days). The copy count, not the collectors, dominates. | Holds, for another reason |
| "30 s timeout fails at about 0.5–1 GB" | The binding limit is the code's 30 s, not `TimeoutStartSec=20min`. The estimate is about 600 MB (laptop benchmark scaled for `CPUQuota`), about April 2027. | **Holds** (it needs a VPS re-measure at 100 MB) |
| "about 3.4 MB DB" | 3,383,296 B | Holds; not material today |
| Compression required first | Retention cuts one-year backups from over 600 GB to about 24–29 GB. Compression is a later lever. | **Not required now** |

**Recommendation: AMEND (PROPOSED).** Replace the blanket prerequisite with byte-based triggers:
1. A new stream states its bytes a day. One adding under 10 % of current growth proceeds on its own approval.
2. The retention policy (B8) and O1 are decided by **2026-10-08**, or before the backups directory reaches 5 GB, whichever comes first.
3. The size-aware timeout ships before the store reaches 250 MB, with a VPS re-measure at 100 MB.
4. Compression is revisited when the kept backup bytes pass 20 GB.

---

## D. Evidence

**Offline measurements:**
- **Reproducible from the repo:** the NFL bytes per game-horizon, via `tests/test_price_observations_nfl_bytes.py` (the real capture path against a temporary store).
- **Measured with uncommitted scratch scripts, so not reproducible from the repo:**
  - the backup create/verify benchmark (a 102 MB synthetic store on the laptop);
  - the growth projections;
  - the retention simulations (the real `retention_plan` in memory, every bundle assumed restore-verified);
  - the replay of today's inventory.
- Their inputs are the repository fixtures and the coordinator's inventory.

**Tests:**
- `tests/test_backup_retention.py`: the dry-run planner.
- `tests/test_price_observations_nfl.py` (PR #112): the NFL capture guards.
- `tests/test_price_observations_nfl_bytes.py`: the byte figure.

**Documentation reads:**
- The Kalshi GetMarkets page (https://docs.kalshi.com/api-reference/market/get-markets, 2026-09-25).
- No Kalshi or Odds API request was made by this writer.
