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
| `/var/lib/market-edge-lab-status` | `edgelab:edgelab` 0755 | `latest.json`, `last_failure.json` (non-sensitive) |
| `/etc/market-edge-lab/env` | `root:edgelab` 0640 | `NWS_USER_AGENT`, `EDGE_LAB_CODE_VERSION`, optional `EDGE_LAB_ALERT_URL` |

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

To roll back the code:

```bash
sudo mv /opt/market-edge-lab/app /opt/market-edge-lab/app.bad && sudo mv /opt/market-edge-lab/app.prev /opt/market-edge-lab/app
```
