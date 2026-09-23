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
- Nothing here places orders or uses credentials.

## 0. Check first (no sudo)

```bash
TZ=America/New_York date
cat /opt/market-edge-lab/app/REVISION
systemctl list-timers 'edgelab-*'
cat /var/lib/market-edge-lab-status/latest.json
```

Brisket health: `systemctl is-active nginx dynasty dynasty-frontend docker` and `/api/health`.

## 1. Stage (agent or owner, unprivileged)

From a checkout at the merged SHA:

```bash
git bundle create market-edge-lab.bundle <SHA>
git show <SHA>:deploy/vps/install.sh > install.sh
git show <SHA>:deploy/vps/preflight.sh > preflight.sh
```

Copy all three to `~dynasty/edgelab-release/` on the VPS, then run
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
   - Before the first live day, expect `NO_CAPTURE` or `NOT_CLOSED` (exit 0).
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

## Rollback

1. Stop the new units:
   ```bash
   sudo systemctl disable --now edgelab-shadow.timer edgelab-settlement.timer
   ```
2. Restore the previous code:
   ```bash
   sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad
   sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app
   sudo systemctl daemon-reload
   ```

Neither store's schema changed, so rolled-back code reads both. The ledger and backups are
kept; nothing is deleted. To stop all collection (the data is kept):
`sudo systemctl disable --now 'edgelab-*.timer'`.
