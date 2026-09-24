# Daily shadow operation: activation and verification (owner command sheet)

Scope: the 2026-09-23 daily-shadow directive (ADR 0016). It covers:
- `edgelab-shadow` (18:40 ET): bookkeeping from stored evidence, with no network;
- `edgelab-settlement` (11:15 and 16:15 ET): a bounded settlement refresh, then the same
  bookkeeping;
- the extended `edgelab-backup`: evidence DB **and** shadow ledger;
- `edgelab.slice`: the combined budget for every edgelab unit.

**Rules**
- Deploy only a reviewed, merged `main` SHA.
- Never install or restart between **17:40 and 18:35 America/New_York**, or while any
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
git bundle create market-edge-lab.bundle <SHA>
git show <SHA>:deploy/vps/install.sh > install.sh
git show <SHA>:deploy/vps/preflight.sh > preflight.sh
git show <SHA>:deploy/vps/verify_production.sh > verify_production.sh
```

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

1. Check that the collector still fails closed:
   ```bash
   sudo systemctl start edgelab-decision.service
   sudo journalctl -u edgelab-decision -n 20 --no-pager
   ```
   Expect `rejected_out_of_window`. Then `sudo systemctl reset-failed 'edgelab-*'`.
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
sudo systemctl enable --now edgelab-shadow.timer edgelab-settlement.timer
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
  - It also runs after every `edgelab-alert@` failure alert. The unit failure then arrives as
    the fixed headline "A run or data source failed".
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

## 6. Verify over the next days: each state separately

| State | Evidence |
|---|---|
| Installed, timers enabled | `list-timers` shows 7 timers |
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

**The evidence schema is forward-only from the ADR 0029 install.** At that install the
evidence store becomes v5; the shadow ledger stays v1.
- **Why it matters.** install.sh step 7 migrates the live evidence DB to v5. v4 code refuses a
  v5 store ("Database schema v5 is newer than this code"), which would stop the collectors,
  VERIFIED backups and the dashboard.
- **Why a stamp is enough.** v5 only **added** the odds capture tables, which v4 code ignores.
  Rolling back therefore means stamping the store v4 first, with the new code still installed,
  and then putting code and units back together. The old `backup.py` also rejects the new
  backup unit's flags.

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
3. **Stamp the evidence store v4 (still the new code):**
   ```bash
   sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v4-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3
   ```
   Expect `{"from": 5, "to": 4, ...}`. The helper refuses (exit 1, nothing changed) anything
   that is not a complete, intact v5 store.
4. **Restore the previous code:**
   ```bash
   sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad
   sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app
   ```
5. **Restore the previous units. Remove only the odds pilot's units**, which the previous code
   cannot run:
   ```bash
   sudo install -o root -g root -m 0644 /opt/market-edge-lab/app/deploy/vps/systemd/edgelab-* /opt/market-edge-lab/app/deploy/vps/systemd/edgelab.slice /etc/systemd/system/
   sudo rm -f /etc/systemd/system/edgelab-odds.service /etc/systemd/system/edgelab-odds.timer
   sudo systemctl daemon-reload
   ```
   Alternatively, `sudo bash install.sh --sha <previous sha> --bundle <bundle>` from the previous
   commit redoes steps 4-5 and the env file. It installs units only, so still remove the two
   `edgelab-odds.*` files and run `daemon-reload`.
6. **Re-enable the seven core timers and restart the dashboard:**
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
   Expect `VERIFIED_BACKUP_AND_RESTORE` for the evidence DB (`schema_version` 4). Expect seven
   timers and no `edgelab-odds`. `tests/test_storage_rollback.py` shows the real v4 code opening
   and verifying a stamped store.

Re-installing the v5 code later stamps v5 again: the migration is idempotent. The shadow
ledger's schema did not change (v1), so the rolled-back code reads it. To stop all collection
and keep the data: `sudo systemctl disable --now 'edgelab-*.timer'`.
