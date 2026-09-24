# Daily shadow operation: activation and verification (owner command sheet)

Scope: the 2026-09-23 daily-shadow directive (ADR 0016). It covers:
- `edgelab-shadow` (18:40 ET): bookkeeping from stored evidence, with no network;
- `edgelab-settlement` (11:15 and 16:15 ET): a bounded settlement refresh, then the same
  bookkeeping;
- the extended `edgelab-backup`: evidence DB **and** shadow ledger;
- `edgelab.slice`: the combined budget for every edgelab unit.

**Rules**
- Deploy only a reviewed, merged `main` SHA.
- Never install or restart between **17:40 and 18:50 America/New_York** (owner directive
  2026-09-24: the capture window plus margin), around the 11:15 and 16:15 ET settlement runs,
  or while any
  `edgelab-*` unit is running (`systemctl list-units 'edgelab-*' --state=running`).
  **Exception:** `edgelab-dashboard.service` (ADR 0024) runs continuously and is exempt from
  this check. It is read-only (`ProtectSystem=strict`, no `ReadWritePaths`, SQLite `mode=ro`)
  and holds no locks beyond per-request reads. `install.sh` replaces
  `/opt/market-edge-lab/app` underneath it, so run `systemctl restart edgelab-dashboard` after
  any install so that it serves the new code.
- Every install, by any session, runs §2 (backup before install) and §4.1 (fail-closed
  test) on the code actually installed.
- Nothing here places orders or uses credentials.

## 0. Check first (no sudo)

```bash
TZ=America/New_York date
cat /opt/market-edge-lab/app/REVISION
systemctl list-timers 'edgelab-*'
cat /var/lib/market-edge-lab-status/latest.json
```

Brisket health: `systemctl is-active nginx dynasty dynasty-frontend docker` and `/api/health`.

Or run `bash verify_production.sh` (read-only). Use the copy staged in §1, or, once a
version carrying it is installed, `/opt/market-edge-lab/app/deploy/vps/verify_production.sh`.
It prints the checks above and the §6 evidence it can read, one `STATE <NAME>: <value>` line
each, and reports NOT_READABLE_WITHOUT_PRIVILEGE where it cannot see without sudo.

## 1. Stage (agent or owner, unprivileged)

From a checkout at the merged SHA:

```bash
git branch -f release/<SHA> <SHA>   # a local branch head: see the note below
git bundle create market-edge-lab.bundle release/<SHA>
git branch -D release/<SHA>
git show <SHA>:deploy/vps/install.sh > install.sh
git show <SHA>:deploy/vps/preflight.sh > preflight.sh
git show <SHA>:deploy/vps/verify_production.sh > verify_production.sh
```

The bundle must carry a local branch head (`refs/heads/...`). A bundle of a remote-tracking
ref such as `origin/main` clones as an empty repository, and `install.sh` stops at step 3
with `reference is not a tree` before touching the installed code (seen 2026-09-24).
`git bundle list-heads market-edge-lab.bundle` must show `refs/heads/release/<SHA>`.

Copy all four to `~dynasty/edgelab-release/` on the VPS, then run
`bash ~/edgelab-release/preflight.sh`. The cloud agent session of 2026-09-23 has no SSH
route to the VPS, so a session with the owner's existing access, or the owner, does this
step. No keys are added or copied anywhere.

## 2. Back up before installing (owner, sudo)

```bash
sudo systemctl start edgelab-backup.service && sudo journalctl -u edgelab-backup -n 30 --no-pager
```

Expect `VERIFIED_BACKUP_AND_RESTORE` for the evidence DB. On a first install the ledger is
`SKIPPED_NO_SOURCE`, because it does not exist yet.

## 3. Install (owner, sudo)

```bash
sudo bash ~/edgelab-release/install.sh --sha <SHA> --bundle ~/edgelab-release/market-edge-lab.bundle
```

The previous code is kept in `/opt/market-edge-lab/app.prev`. Timers keep their current
enabled state. New units are installed but not enabled.

## 4. Dry runs (owner, outside the capture window)

1. Check that the collector still fails closed. Use the check script, not a bare `systemctl start`
   of the decision unit: its intentional failure would otherwise reach the owner's phone as
   "A run or data source failed" (ADR 0028 amendment).
   ```bash
   sudo bash /opt/market-edge-lab/app/deploy/vps/verify_fail_closed.sh
   ```
   - **What it does.**
     - It refuses unless it runs as root, no other check is running, `edgelab-decision.service`
       is idle and `edgelab-decision.timer` is not due within 5 minutes.
     - It arms a check in `/var/lib/market-edge-lab-verify` (root-owned) and starts the real
       unit, then reads the new invocation's own journal lines.
     - It writes a root-owned confirmation named by the invocation ID only if that exact
       invocation failed with exit status 1, printed `"status": "rejected_out_of_window"`, and
       the timer did not trigger meanwhile.
     - `alert.sh` then records that failure in `last_verification.json` (never in
       `last_failure.json`, which stays production-only) with
       `"origin": "DEPLOYMENT_VERIFICATION"`.
     - `edgelab-notify` holds it (`HELD_BY_ORIGIN`) instead of pushing it, after checking the
       root-owned confirmation again.
     - Finally the script clears the failed state of that one unit.
   - **Expect**, on the last lines:
     `CONFIRMED: invocation <id> failed closed (rejected_out_of_window)`, a
     `RECORDED: {..., "origin": "DEPLOYMENT_VERIFICATION"}` line and
     `FAIL_CLOSED_CHECK: PASS`. `journalctl -u edgelab-notify -n 1 --no-pager` then shows
     `"HELD_BY_ORIGIN": 1`.
   - **Anything else stops the install** and prints `FAIL_CLOSED_CHECK: ...` with a reason (exit 1):
     - `NOT_CONFIRMED`: the unit succeeded, so the collector did not fail closed. If it says
       `skipped_duplicate` or `complete`, the check ran inside the capture window. Or the unit
       failed another way (timeout, crash, a different status), or the timer fired during the
       check. Such a failure stays a PRODUCTION alert and is pushed, as it should be.
     - `ALERT_NOT_RECORDED` or `ORIGIN_NOT_VERIFICATION`: the alert path did not record it as
       expected.
     - `REFUSED`: not root, another check is running, the unit is running, or the timer is due
       within 5 minutes.

     A genuine failure of any unit, including this one, stays PRODUCTION and pushes, even
     while this check runs. Do not use `reset-failed 'edgelab-*'`: it would also clear real
     failures of other units.
2. Run the bookkeeping (no network) and read the receipt:
   ```bash
   sudo systemctl start edgelab-shadow.service
   cat /var/lib/market-edge-lab-status/shadow_daily.json
   ```
   - Before the first live day, expect `NO_CAPTURE` or `NOT_CLOSED` (exit 0). A closed day
     whose only capture record is a fail-closed test (step 4.1 run on an earlier day) reports
     `INVALID_CAPTURE`, exit 3. That is true (the day has no valid evidence); it alerts once,
     and repeats are deduplicated.
   - After the first live day: `PENDING_SETTLEMENT` (a signal day), `HEALTHY_NO_SIGNAL`,
     or `INVALID_CAPTURE` (exit 3, which alerts).
3. Run the settlement refresh:
   ```bash
   sudo systemctl start edgelab-settlement.service
   ```
   Before any position is due, it reports `"refresh": {"status": "skipped"}` and makes no
   GET.
4. Back up both stores again: `sudo systemctl start edgelab-backup.service`. Two VERIFIED
   reports are expected once the ledger exists.
5. Check the combined budget:
   ```bash
   systemctl show edgelab.slice -p MemoryMax -p CPUQuotaPerSecUSec
   systemd-cgtop -1 edgelab.slice
   ```

## 5. Activate (owner)

```bash
sudo systemctl enable --now edgelab-shadow.timer edgelab-settlement.timer edgelab-observe.timer edgelab-observe-close.timer
systemctl list-timers 'edgelab-*'
```

## 5a. ntfy push activation (ADR 0028; owner-approved 2026-09-24; root, once)

The topic is a password on a public server. It is generated on the server and written
straight into the secrets file, which is `root:root 0600`: systemd reads `EnvironmentFile=` as
root, so no service account can read the file. Nothing prints the topic. If a topic already
exists, the script keeps it, because replacing it would break the phone subscription. Use
`--force` only to rotate a topic on purpose.

```bash
sudo python3 /opt/market-edge-lab/app/deploy/vps/set_ntfy_topic.py
```

Then send one test event as the service user, with the relay unit's own environment and slice:

```bash
sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice -p EnvironmentFile=/etc/market-edge-lab/env -p EnvironmentFile=/etc/market-edge-lab/secrets.env /opt/market-edge-lab/venv/bin/python -m edge_lab.cli notify test
```

- **Expected output:** `{"by_status": {"SUBMITTED": 1}, ...}`. SUBMITTED means ntfy.sh accepted
  the message. It does **not** prove that a phone showed it.
- **Subscribing (owner only).** The owner reads the topic privately, on the server:
  `sudo grep NTFY /etc/market-edge-lab/secrets.env`. Never do this in an agent session, whose
  transcript would keep the topic. Then subscribe in the ntfy app: server `ntfy.sh`, topic =
  the part after `https://ntfy.sh/`.
- **What then happens automatically:**
  - `edgelab-notify` relays new outbox events after every shadow and settlement run.
  - It also runs after every `edgelab-alert@` failure alert. A PRODUCTION unit failure then
    arrives as the fixed headline "A run or data source failed".
  - **Origin rule.** Only PRODUCTION events are pushed. The §4.1 fail-closed check is recorded
    as DEPLOYMENT_VERIFICATION in `last_verification.json` and the journal, but never pushed.
    The dashboard shows it once Lane B's alerts PR lands. `last_failure.json` holds production
    failures only. TEST
    events are pushed only by `notify test`. MANUAL_DIAGNOSTIC events are pushed only on
    explicit request, and REPLAY and DEMO events never. The relay journal counts held events
    as `HELD_BY_ORIGIN`.
  - `journalctl -u edgelab-notify` shows counts only.
- **Rules:**
  - Do not run `edge-lab notify relay` by hand while the unit is active.
  - Do not point `EDGE_LAB_ALERT_URL` at the ntfy topic. `alert.sh` sends free text (unit and
    host names), which would break the fixed-headline rule and double every push. Leave it unset
    or on a different channel.

## 5b. The Odds API NFL pilot activation (ADR 0029; directive 2026-09-24 Phase 6; once)

Authority: owner correction 3 (game-relative captures, 450 credits a month at most, never above
the provider's remaining quota). `edgelab-odds.timer` is installed by install.sh but stays
disabled until these steps pass. Outside 17:40-18:35 America/New_York, and not while a
settlement job runs (about 11:15 and 16:15 ET).

1. **Owner only: install the key.** Create the free Starter key at the provider yourself, then:
   ```bash
   sudoedit /etc/market-edge-lab/secrets.env
   # add one line:  EDGE_LAB_ODDS_API_KEY=<your key>
   ```
   Never paste the key into chat, git, a ticket or a log. The agent never sees it.
2. **Agent: prove the plan (free calls only; no credits spent).**
   ```bash
   sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice -p EnvironmentFile=/etc/market-edge-lab/env -p EnvironmentFile=/etc/market-edge-lab/secrets.env /opt/market-edge-lab/venv/bin/python -m edge_lab.cli odds plan --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 --ledger /var/lib/market-edge-lab/db/odds_quota_ledger.json
   ```
   Record in the activation note: the enumerated schedule (`schedule`, `slots`), `budget.state`
   (must be `PROVEN`), `budget.worst_case_month_credits` (must be <= 450) and the room left
   below `budget.provider_remaining`, `budget.expected_month_credits`, and
   `projection_next_month`. Anything other than PROVEN stops here.
3. **Agent: one bounded live smoke read (3 credits at most).**
   ```bash
   sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice -p EnvironmentFile=/etc/market-edge-lab/env -p EnvironmentFile=/etc/market-edge-lab/secrets.env /opt/market-edge-lab/venv/bin/python -m edge_lab.cli odds smoke --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 --ledger /var/lib/market-edge-lab/db/odds_quota_ledger.json
   ```
   It refuses (exit 1, nothing sent) when the quota is unknown or insufficient. Record exactly
   which `bookmakers` and `markets_returned` came back, `coverage` (ABSENT and
   PAID_ONLY_NOT_ENABLED entries included), `credits_last` and `quota_after`. The smoke read's
   evidence is the snapshot it names; it is not a capture target.
4. **Enable the bounded schedule.**
   ```bash
   sudo systemctl enable --now edgelab-odds.timer
   systemctl list-timers edgelab-odds.timer
   journalctl -u edgelab-odds -n 5 --no-pager   # one JSON line per tick; never the key
   ```
   Every 15 minutes a tick checks locally whether a planned slot is due. Discovery is free and
   runs at most every 6 h. A paid call happens only for an admitted slot, at most one per
   tick. Ticks inside 17:40-18:35 ET report `DEFERRED_CAPTURE_WINDOW` and do nothing.
5. **Verify.** `odds plan --offline` (same `systemd-run` line with `--offline` added, no network)
   shows `recorded_targets` by state. MISSED targets keep their reason.
   - `KEY_REJECTED`: the provider refused the key. Nothing is paid for, and discovery is
     retried every 6 h. The owner fixes the key with `sudoedit`.
   - `COST_BLOCKED`: the provider charged more than 3 credits for one call. Paid calls stay
     stopped until an operator checks the ledger and the snapshot, then runs one tick with
     `odds run --clear-cost-block` (same `systemd-run` line and flags).

   Stop at any time with
   `sudo systemctl disable --now edgelab-odds.timer`; targets and evidence stay.

This is read-only sports data collection. It authorizes no sportsbook account, no bet, no
sports model and no strategy.

**Activation record (2026-09-24, production SHA 2e3e172).**
- **Key and budget.** The owner installed the key privately; no agent saw it. `odds plan`
  (13:38Z) returned `PROVEN`:
  - 2026-09: worst case 45, expected 42 credits;
  - 2026-10 projection: worst case 450 (ceiling 450), expected 270;
  - provider remaining 500, spent 0, nothing outstanding;
  - 32 NFL events discovered through the free events endpoint.
- **The one smoke read** (started 13:38:53Z; evidence DB snapshot 22, received 13:38:54Z) was
  `CAPTURED`:
  - 1 paid call, `credits_last` 3; quota 500 → 497 remaining;
  - 16 events and 856 offers; markets h2h, spreads and totals;
  - 9 books returned: betmgm, betonlineag, betrivers, betus, bovada, draftkings, fanduel,
    lowvig, mybookieag. fanatics and williamhill_us came back `PAID_ONLY_NOT_ENABLED`.
- **The first attempt** (13:18Z, SHA 2d04c51) crashed on the CLI's string paths before any
  request, spending 0 credits. PR #71 fixed it.
- **Redaction** was checked by literal-occurrence counts. The check received the secrets
  through `EnvironmentFile=` and printed only integers. It found 0 occurrences of the key or the
  ntfy topic in:
  - the whole journal since 2026-09-22;
  - every status and verify file, the quota ledger and pilot state;
  - every text cell of the evidence DB;
  - the dashboard pages.

  The stored odds URLs carry `apiKey=REDACTED`.
- **Timer.** `edgelab-odds.timer` was enabled at 13:40Z. It ticks every 15 minutes. The first
  paid slot is Thu 2026-09-24 14:15 ET (T-6h, ATL @ GB).
- **First tick** (13:45Z) was `IDLE` with 0 paid calls:
  - discovery refreshed 32 events through the free endpoint (`x-requests-last` 0; snapshot 23,
    the first stored discovery);
  - 95 targets are PLANNED;
  - budget PROVEN: worst case 48 including the 3 spent.

  `odds_pilot.dashboard_status` reports `ACTIVE`, with `live_read_verified: true`.

## 5c. Later/closing price observations: scheduled Option A (ADR 0030)

Authority: the 2026-09-24 next-build-chunk directive built the manual mechanism; the owner explicitly
approved scheduled capture at 11:24 ET on 2026-09-24 (durable record: issue #74). Option A is selected.
The two units are installed with the rest and are enabled through §5 above:

- `edgelab-observe.timer`: :05, :20, :35 and :50 each hour, local plan plus bounded capture only when due;
- `edgelab-observe-close.timer`: 04:57:45 UTC, the dedicated KXHIGHNY close-window tick.

Both are `Persistent=false`. A missed point-in-time tick is never fired late; targets become `MISSED`
with a reason. Protected windows, the shared collector lock, request caps and the Kalshi pacer still govern.


After enabling, verify both explicitly:

```bash
systemctl is-enabled edgelab-observe.timer edgelab-observe-close.timer
systemctl list-timers edgelab-observe.timer edgelab-observe-close.timer
bash /opt/market-edge-lab/app/deploy/vps/verify_production.sh | grep 'OBSERVE.*TIMER'
```

Manual `observe plan/capture/status` commands below remain valid for diagnostics and recovery; do not
run a manual capture concurrently with the scheduled services.

- **Schema.** The first install of this code migrates the evidence store to **v6**. It adds two
  tables and nothing else; the "Rollback" section covers the stamp back to v5.
- **Protected windows.** All three commands are read-only public GETs (capture) or local (plan,
  status). `plan` and `capture` refuse to run, with no network and no writes, when they could
  overlap:
  - 17:40-18:50 ET;
  - 11:13-11:30 ET;
  - 16:13-16:30 ET.

  They take the collector lock with a 5 s timeout, and `LOCK_BUSY` means nothing was done.

Run as `edgelab`, like every other unit (`systemd-run` keeps the slice and its limits):

```bash
# Plan targets for every recorded decision (qualified and rejected) and backfill decision/recheck. No network.
sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice /opt/market-edge-lab/venv/bin/python -m edge_lab.cli observe plan --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3
# One bounded capture of whatever is due now (at most 40 GETs, 24 markets, 4 minutes).
sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice /opt/market-edge-lab/venv/bin/python -m edge_lab.cli observe capture --db /var/lib/market-edge-lab/db/edge_lab.sqlite3
# Read-only: targets by phase and state, the next due, recent misses (add --market kalshi:<ticker> for one path).
sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.cli observe status --db /var/lib/market-edge-lab/db/edge_lab.sqlite3
```

When to run a capture for EXP-001 day D (the decision is 18:00 ET on D-1). `observe status`
lists each target's due window:

| phase | run `observe capture` at | GETs |
|---|---|---|
| post_decision_1h | 19:05 ET on D-1 | 7 |
| post_decision_6h | 00:05 ET on D | 7 |
| pre_close | 04:47 UTC on D+1 (close_time 05:00Z - 15 min) | 7 |
| close | 04:57:45 UTC on D+1: it waits to 04:59:30, then confirms at 05:00:05 | 8 |
| settlement_preceding | 18:35 UTC on D+1 (expected resolution 19:00Z - 30 min) | 1 |

A close observation is labelled `CLOSE` only with its stored proof. It displays as "close (within 60 s
of trading close)", because the public book has no sequence number. Anything else is "latest pre-close
observation" (ADR 0030, close semantics). An idle `plan` or `capture` (nothing due) writes nothing.

## 6. Verify over the next days: each state separately

| State | Evidence |
|---|---|
| Installed, timers enabled | `list-timers` shows 9 core/observation timers; 10 when the separately activated Odds timer is enabled |
| Fail-closed dry run | step 4.1 journal |
| Real decision/recheck captured | `latest.json` has `last_closed_target_date` = D with VALID or an explicit INVALID reason |
| Complete forecast evidence | no `pfm` reason in `last_closed_reasons` |
| Valid-day classification | `latest.json` `valid_days`; `shadow_daily.json` `days[].capture_status` |
| Shadow bookkeeping | `shadow_daily.json` `days[].accounts` (decisions, fills, no-fill reasons, risk vetoes) |
| Settlement lifecycle | a later `shadow_daily.json` with `settlement.settled` > 0 and no pending for that day |

One state does not prove the next. A valid no-signal day is a legitimate result.
`bash verify_production.sh` (read-only, no sudo) prints each of these states separately:
the directive's DEPLOYED_SHA, COLLECTOR_HEALTH, SHADOW_TIMER, SETTLEMENT_TIMER,
BACKUP_EVIDENCE_DB, BACKUP_SHADOW_LEDGER, RESTORE_EVIDENCE_DB, RESTORE_SHADOW_LEDGER and
CHASE_UPSIDE_HEALTH, and COLLECTOR_INSTALLED, TIMERS_ENABLED,
PFM/DECISION/RECHECK_CAPTURE_OBSERVED and VALID_DAY_OBSERVED. It never infers one from
another: RESTORE_* comes only from the backup's temporary-restore result, and what it cannot
read is UNKNOWN.

## If the receipt says FAILED, LOCK_BUSY or SETTLEMENT_CONFLICT

1. Read `problems` and `days[].problems` in
   `/var/lib/market-edge-lab-status/shadow_daily.json`. Then read the journal:
   `sudo journalctl -u edgelab-shadow -u edgelab-settlement -n 50 --no-pager`.
2. A transient cause (lock busy, host load) heals itself: the next run retries the same day
   first. Settlement is held at that day's decision time until it succeeds, so nothing gets
   out of order.
3. `SETTLEMENT_CONFLICT` means two captures disagree on an outcome. Positions stay pending
   or keep their recorded outcome. Report it; never edit the ledger by hand.
4. Never delete or edit ledger rows. The ledger is append-only, and backups keep every
   copy.

## Rollback

**The evidence schema is forward-only.** The ADR 0029 install made the evidence store v5, and
the ADR 0030 install makes it **v6**. The shadow ledger stays v1.
- **Why it matters.** install.sh step 7 migrates the live evidence DB. Older code refuses a newer
  store ("Database schema v6 is newer than this code"), which would stop the collectors,
  VERIFIED backups and the dashboard.
- **Why a stamp is enough.** v5 only **added** the odds capture tables, and v6 only the price
  observation tables. Older code ignores both. Rolling back therefore means stamping the store
  down first, with the new code still installed, and then putting code and units back together.
- **Rolling back one step, to the v5 code (just before ADR 0030).**
  - Step 3 is `mark-v5-for-rollback` only.
  - Remove the four ADR 0030 observation unit files after restoring the v5 code; v5 does not know them.
  - Keep the Odds API units; v5 includes ADR 0029. Re-enable whichever pre-ADR0030 timers were enabled.
- **Rolling back to the v4 code (before ADR 0029).** Run both stamps in order, remove the
  ADR 0030 observation units **and** the ADR 0029 odds units.
- The old `backup.py` from before ADR 0016 also rejects the new backup unit's flags.

Nothing is deleted. Run the steps as root, in order, outside 17:40-18:50 ET and not during a
settlement run (about 11:15 and 16:15 ET):

1. **Stop every timer, the odds pilot included, and check that nothing is running:**
   ```bash
   sudo systemctl disable --now 'edgelab-*.timer'
   systemctl list-units 'edgelab-*' --state=running --no-legend   # expect no capture job
   ```
2. **Make a verified backup (still the new code):**
   ```bash
   sudo systemctl start edgelab-backup.service && sudo journalctl -u edgelab-backup -n 20 --no-pager
   ```
   Expect `VERIFIED_BACKUP_AND_RESTORE` for both stores. Stop here if either is missing.
3. **Stamp the evidence store down (still the new code):**
   ```bash
   sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v5-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3   # v6 -> v5
   sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v4-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3   # v5 -> v4: only when going back before ADR 0029
   ```
   Expect `{"from": 6, "to": 5, ...}`, then `{"from": 5, "to": 4, ...}`. Each refuses (exit 1,
   nothing changed) anything that is not a complete, intact store of its version.
4. **Restore the previous code:**
   ```bash
   sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad
   sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app
   ```
5. **Restore the previous units and remove units newer than the target code.** For a v5
   rollback, remove only the ADR 0030 observation units:
   ```bash
   sudo install -o root -g root -m 0644 /opt/market-edge-lab/app/deploy/vps/systemd/edgelab-* /opt/market-edge-lab/app/deploy/vps/systemd/edgelab.slice /etc/systemd/system/
   sudo rm -f /etc/systemd/system/edgelab-observe.service /etc/systemd/system/edgelab-observe.timer \
     /etc/systemd/system/edgelab-observe-close.service /etc/systemd/system/edgelab-observe-close.timer
   sudo systemctl daemon-reload
   ```
   **Only when the rollback target is v4** (before ADR 0029), additionally remove the Odds units:
   ```bash
   sudo rm -f /etc/systemd/system/edgelab-odds.service /etc/systemd/system/edgelab-odds.timer
   sudo systemctl daemon-reload
   ```
   Alternatively, `sudo bash install.sh --sha <previous sha> --bundle <bundle>` from the previous
   commit redoes steps 4-5 and the env file. Still remove any unit files newer than the target
   code, then run `daemon-reload`.
6. **Re-enable the timers supported by the rollback target and restart the dashboard:**
   ```bash
   sudo systemctl enable --now edgelab-pfm.timer edgelab-decision.timer edgelab-recheck.timer edgelab-status.timer edgelab-backup.timer edgelab-shadow.timer edgelab-settlement.timer
   sudo systemctl restart edgelab-dashboard.service
   ```
7. **Verify on the old code:**
   ```bash
   sudo systemctl start edgelab-backup.service && sudo journalctl -u edgelab-backup -n 20 --no-pager
   systemctl list-timers 'edgelab-*'
   systemctl is-active edgelab-dashboard.service
   ```
   Expect `VERIFIED_BACKUP_AND_RESTORE` for the evidence DB, with `schema_version` 5 (or 4 after
   both stamps). A v5 rollback has no `edgelab-observe*` units and may keep the Odds timer if it
   was active before ADR 0030. A v4 rollback has seven core timers and neither observation nor Odds units.
   `tests/test_storage_rollback.py` shows the real v5 code (`cbfbddf`) and v4 code (`dd3ab4d`)
   opening and verifying a stamped store.

Re-installing the newer code later stamps it again: the migration is idempotent, and every row
written meanwhile is kept. The shadow
ledger's schema did not change (v1), so the rolled-back code reads it. To stop all collection
and keep the data: `sudo systemctl disable --now 'edgelab-*.timer'`.
