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

Code and unit files must go back **together**: the new `edgelab-backup.service` passes
flags (`--kind`, `--if-exists`, `--lock-file`) that older `backup.py` rejects.

1. Stop the new units:
   ```bash
   sudo systemctl disable --now edgelab-shadow.timer edgelab-settlement.timer
   ```
2. Restore the previous code:
   ```bash
   sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad
   sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app
   ```
3. Restore the previous unit files and remove the new ones:
   ```bash
   sudo install -o root -g root -m 0644 /opt/market-edge-lab/app/deploy/vps/systemd/edgelab-* /etc/systemd/system/
   sudo rm -f /etc/systemd/system/edgelab-shadow.* /etc/systemd/system/edgelab-settlement.* /etc/systemd/system/edgelab.slice
   sudo systemctl daemon-reload
   ```
4. Verify the backup path works on the old code:
   ```bash
   sudo systemctl start edgelab-backup.service && sudo journalctl -u edgelab-backup -n 20 --no-pager
   ```
   Expect `VERIFIED_BACKUP_AND_RESTORE` for the evidence DB.

Neither store's schema changed (evidence v4, ledger v1), so rolled-back code reads both;
nothing is migrated or deleted. The shadow ledger and its backups stay in place and
unused. To stop all collection (the data is kept):
`sudo systemctl disable --now 'edgelab-*.timer'`.
