# Forward Stage-B collector on the Chase Upside VPS

What runs, where, and how to install, check and stop it. The design and the headroom review
are in ADR 0012 and `docs/deploy/VPS_REVIEW_2026-09-22.md`. It is authorized by
`docs/owner/2026-09-22-gate4-collection-directive.md`, and the scope is read-only public
GETs only. It has no credentials and no order paths
(`tests/invariants/test_no_execution_paths.py`).

## What runs

All times are America/New_York. The timers name the zone explicitly because the host clock
is Europe/Berlin.

| Timer | When | Does |
|---|---|---|
| `edgelab-pfm` | 17:45 | stores new PFMOKX products; selects the forecast available at 17:30 (the frozen rule) |
| `edgelab-decision` | 17:55:05 | the D event, its full market list, one order book per open bracket, all received in [17:55, 18:00] |
| `edgelab-recheck` | 18:05 | every bracket's book again, 10–15 min after that bracket's decision book |
| `edgelab-status` | 18:30 | re-derives the day's validity from evidence; writes `/var/lib/market-edge-lab-status/latest.json` |
| `edgelab-backup` | 04:40 UTC | verified SQLite backups of the evidence DB **and** the shadow ledger (`backups/`, `backups/ledger/`; no automatic deletion) |
| `edgelab-settlement` | 11:15, 16:15 | bounded settlement refresh for due pending events, then shadow bookkeeping (ADR 0016) |
| `edgelab-shadow` | 18:40 | daily shadow bookkeeping from stored evidence, no network; writes `shadow_daily.json` |
| `edgelab-odds` | every 15 min (ticks in 17:40-18:35 deferred in code) | The Odds API NFL pilot: free discovery, and at most one paid odds call when a planned T-24h / T-6h / T-60m slot is due (ADR 0029). Installed, **not enabled** by install.sh; enabled only by `docs/deploy/DAILY_SHADOW_ACTIVATION.md` section 5b |

All edgelab units run inside `edgelab.slice` (MemoryMax 384M, CPUQuota 25% combined), as
well as their per-run caps. Activation, verification and rollback for the daily shadow
units: `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.

- **Timing:** each capture checks its own window before any network request. A run outside
  it records `rejected_out_of_window` and exits 1. The timer is never trusted, and
  `Persistent=false` means a missed window is lost rather than fired late.
- **Validity:** a day is VALID only if it has:
  - the correct event;
  - every open bracket booked in the decision window;
  - every bracket re-checked 10–15 min later;
  - a fresh forecast that was available at the cutoff.

  Anything missing makes the whole day INVALID. There are no partial days.
- **Failures:** any failed or invalid run triggers `edgelab-alert@`. It writes to the
  journal and to `last_failure.json` in the status directory. If the owner set
  `EDGE_LAB_ALERT_URL` in the env file, it also sends a one-line push.
- **Caps per run:** `MemoryMax=256M`, `CPUQuota=25%`, `TasksMax=32`, `Nice=5`.
- **Hardening:** `ProtectSystem=strict` with write access only to the two data directories,
  plus `ProtectHome` and `NoNewPrivileges`.

## Layout and permissions

| Path | Owner / mode | Contents |
|---|---|---|
| `/opt/market-edge-lab/app` | root, read-only | code at a pinned commit (`REVISION`) |
| `/opt/market-edge-lab/venv` | root | stdlib-only venv; a `.pth` points at `app/src` |
| `/var/lib/market-edge-lab/{db,backups}` | `edgelab:edgelab` 0700 | private evidence database and backups |
| `/var/lib/market-edge-lab-status` | `edgelab:edgelab` 0755 | `latest.json`, `last_failure.json`, `notifications.jsonl`, `ntfy_relay.jsonl` (non-sensitive) |
| `/etc/market-edge-lab/env` | `root:edgelab` 0640 | `NWS_USER_AGENT`, `EDGE_LAB_CODE_VERSION`, optional `EDGE_LAB_ALERT_URL` (regenerated on every install) |
| `/etc/market-edge-lab/secrets.env` | `root:root` 0600 | owner-installed secrets (ntfy topic, Odds API key); created empty once, never read by install; systemd loads it for `edgelab-notify` only (ADR 0028) |

Other accounts, including the Chase Upside user `dynasty`, can read only the status
directory. `install.sh` checks this and refuses to finish otherwise.

## Install or update

Nothing is enabled by install. Do not install, update or restart between 17:40 and 18:35 America/New_York, or while any `edgelab-*` unit is running (the shadow bookkeeping runs at 18:40).

1. **Agent (unprivileged):**
   - bundle the merged `main` commit;
   - copy the bundle and `install.sh` to `~dynasty/edgelab-release/`. Take `install.sh` from
     git (`git show <SHA>:deploy/vps/install.sh`), not from a Windows working tree:
     `.gitattributes` keeps `deploy/**` LF, but a copied CRLF file would fail at once;
   - run `bash preflight.sh`.
2. **Owner (sudo):**

   ```bash
   sudo bash ~/edgelab-release/install.sh --sha <SHA> --bundle ~/edgelab-release/market-edge-lab.bundle --user-agent "market-edge-lab research (contact: <email>)"
   ```

3. **Fail-closed dry run (owner),** outside the window. It must be rejected before any
   order-book request:

   ```bash
   sudo systemctl start edgelab-decision.service
   ```

   Then check the output:

   ```bash
   sudo journalctl -u edgelab-decision -n 20 --no-pager
   ```

   Expect `"status": "rejected_out_of_window"` and a failed unit. Then clear the failed state:

   ```bash
   sudo systemctl reset-failed 'edgelab-*'
   ```

4. **Activate (owner):**

   ```bash
   sudo systemctl enable --now edgelab-pfm.timer edgelab-decision.timer edgelab-recheck.timer edgelab-status.timer edgelab-backup.timer
   ```

## Check

To read the status as `dynasty`, with no sudo:

```bash
cat /var/lib/market-edge-lab-status/latest.json
```

To list the timers:

```bash
systemctl list-timers 'edgelab-*'
```

To print every production state separately, read-only and with no sudo (sections needing privilege say so):
`bash ~/edgelab-release/verify_production.sh`.

To read the logs (owner):

```bash
sudo journalctl -u 'edgelab-*' --since today
```

## Stop / roll back

To stop all collection (the data is kept):

```bash
sudo systemctl disable --now 'edgelab-*.timer'
```

To roll back the code: **the evidence schema is forward-only: v5 from the ADR 0029 install, v6
from the ADR 0030 install**, and previous code refuses a newer store. Code, units and the schema
stamp go back together, in this order. The details and expected outputs are under "Rollback" in
`docs/deploy/DAILY_SHADOW_ACTIVATION.md`.
- **Back to the code just before ADR 0030 (v5).**
  - Stamp with `mark-v5-for-rollback` only.
  - ADR 0030 added no unit, so keep the odds units.
  - Re-enable the timers that were enabled before.
- **Back before ADR 0029 (v4).** Run both stamps and every step below.

```bash
sudo systemctl disable --now 'edgelab-*.timer'                        # 1. stop every timer, odds included
sudo systemctl start edgelab-backup.service                           # 2. VERIFIED backup (journalctl -u edgelab-backup)
sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v5-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3   # 3a. stamp v6 -> v5
sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v4-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3   # 3b. stamp v5 -> v4 (only before ADR 0029)
sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad && sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app   # 4. code
sudo install -o root -g root -m 0644 /opt/market-edge-lab/app/deploy/vps/systemd/edgelab-* /opt/market-edge-lab/app/deploy/vps/systemd/edgelab.slice /etc/systemd/system/   # 5. units
sudo rm -f /etc/systemd/system/edgelab-odds.service /etc/systemd/system/edgelab-odds.timer && sudo systemctl daemon-reload
sudo systemctl enable --now edgelab-pfm.timer edgelab-decision.timer edgelab-recheck.timer edgelab-status.timer edgelab-backup.timer edgelab-shadow.timer edgelab-settlement.timer   # 6. core timers
sudo systemctl restart edgelab-dashboard.service
sudo systemctl start edgelab-backup.service                           # 7. VERIFIED on the old code
```
