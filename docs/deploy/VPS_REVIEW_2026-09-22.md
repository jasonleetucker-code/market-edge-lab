# Chase Upside VPS headroom and isolation review — 2026-09-22

Read-only. Nothing on the host was changed.
- **Run:** by the coordinating agent on 2026-09-22 at about 23:15–23:30 UTC, over
  `ssh chaseupside` (user `dynasty`; key already authorized by the owner; no keys added).
- **Commands:** `hostname`, `nproc`, `lscpu`, `uptime`, `/proc/pressure/*`, `free -m`,
  `swapon --show`, `df -h`, `df -i`, `timedatectl`, `systemctl list-units/list-timers/show`,
  `ps`, `sar -r/-u` over the last 7 sysstat files, and `journalctl` (OOM grep).
- **Re-run:** the same checks run again immediately before install, through
  `deploy/vps/preflight.sh`. That script arrives with the forward-collector PR; it does not
  exist on `main` until that PR merges.

## Host

| Item | Value |
|---|---|
| Hostname | `vmi3454985` (`chaseupside.com`, 169.58.50.224) |
| OS / kernel | Ubuntu 24.04.4 LTS, 6.8.0-136-generic, up 57 days |
| systemd | 255, which supports `OnCalendar=… America/New_York` |
| Python | 3.12.3 (`/usr/bin/python3.12`) |
| CPU | 4 vCPU AMD EPYC; load average 0.19 / 0.32 / 0.49 |
| Pressure (PSI) | cpu some avg300 0.98%; memory and io ≈ 0 |
| RAM | 7,941 MB total, 5,921 MB available, **no swap** |
| Disk | `/` 96 GB, 65 GB free (33% used), inodes 3% used |
| Clock | Europe/Berlin timezone, NTP active and synchronized |
| sudo for `dynasty` | **password required**, so installing is an owner step |

## Existing Chase Upside (Brisket) services

| Unit | MemoryHigh / MemoryMax | Current | Peak | CPU quota |
|---|---|---|---|---|
| `dynasty.service` (backend) | 2.5 GB / 3 GB | 1.18 GB | 1.82 GB | none |
| `dynasty-frontend.service` | 1.5 GB / 2 GB | 0.10 GB | 0.11 GB | none |
| `docker.service` | – | 0.06 GB | 0.10 GB | none |
| `nginx.service` | – | 0.015 GB | 0.024 GB | none |

- **Worst case at Brisket's caps:** about 5.3 GB, which leaves about 2.6 GB for everything
  else.
- **OOM:** the 30-day journal shows no OOM kills.
- **Timers:** 27 `dynasty-*`/`riskit-*` timers are defined in UTC. Those nearest the
  collection windows (EDT 21:55–22:20Z, EST 22:55–23:20Z):

| Timer | When |
|---|---|
| `dynasty-healthcheck` | every minute |
| `dynasty-custom-alerts` | even hours at :13, so **22:13Z**, inside the EDT re-check window |
| `dynasty-dlf-fetch` | 22:27Z |
| `dynasty-idpshow-fetch` | 22:32Z |
| `dynasty-trending-history-refresh` | :35 |
| `dynasty-crowd-faab` | 21:25Z |

None of the heavy daily jobs (backups 02:00–03:30Z, sharp/board jobs 04:20–08:20Z) are
near the windows.

System timers `mdcheck_continue` and `mdmonitor-oneshot` run at 00:00 host time
(Europe/Berlin). That is 22:00Z during CEST, the EDT decision instant. Both are software-RAID
housekeeping and do next to nothing on a VM without md arrays. `preflight.sh` lists every
timer's calendar so this can be rechecked.

## Measured history (sysstat, 2026-09-17 … 2026-09-23 files, Berlin local time)
- **Available RAM:** the minimum was 3.9 GB, on 2026-09-17/18. Most days it stayed at
  5.2–5.7 GB.
- **CPU peaks:** close to 100% at 09:30–11:00 Berlin on 2026-09-17/18. That is far from the
  collection window.
- **CPU in the collection window** (23:40–00:30 CEST): 3.3–4.8% on most days, with a
  maximum of 21%.

## Collector footprint and verdict
- **Expected footprint:**
  - Per window: about 25 HTTP GETs (event, markets, about 6–8 bracket books, PFM), paced at
    0.6 s.
  - One Python process under 60 MB RSS, running for about 30 s at 17:55 and 17:45 ET, and
    at most 15 min (mostly sleeping) for the re-check.
  - Data growth under 1 MB/day.
- **Caps:** `MemoryMax=256M`, `CPUQuota=25%`, `TasksMax=32`, `Nice=5`.

**Verdict: PASS.** Even at the worst recorded moment, the collector's cap is under 7% of
available RAM. Its CPU use in the window is negligible next to four idle cores.

Residual risks:
1. **No swap.** A Brisket memory spike past its own caps could still reach the collector.
   Mitigation: Brisket's MemoryMax caps exist and have held for 30 days.
2. **SSH reconnects are rate-limited.** One connection attempt timed out, which does not
   affect the service.
3. **Shared host.** An outage affects both services (ADR 0012).
