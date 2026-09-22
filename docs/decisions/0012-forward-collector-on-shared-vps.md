# 0012 — Forward Stage-B collector as a separate service on the Chase Upside VPS

Status: Accepted (2026-09-22). Supersedes 0008.

**Problem.** EXP-001 Stage B needs, for each target date D:
- the complete KXHIGHNY event and order-book state in [17:55, 18:00] America/New_York on
  D−1;
- a re-check book for every bracket 10–15 minutes later;
- the NWS PFMOKX forecast that was available at the cutoff.

These data exist only at the moment they are observed. Every missed window is lost for good.
ADR 0008 deferred scheduling until there was a durable store and an owner decision. The
owner has now authorized scheduled read-only collection
(`docs/owner/2026-09-22-gate4-collection-directive.md`).

**Alternatives.**
(a) GitHub Actions cron. Artifacts expire; each run's minutes count against the private
    repository's allowance; runner start-up jitter of minutes is common, which is too coarse
    for a five-minute window.
(b) A new small paid VM. Not authorized: no paid hosting.
(c) The existing Chase Upside VPS, running as its own service with its own identity, data
    directory, limits and timers.
(d) The owner's laptop. It sleeps and is not durable. Acceptable only as an attended
    bridge for a single window.

**Decision.** (c). The collector runs as system user `edgelab` from `/opt/market-edge-lab`,
a checkout pinned to a commit and kept separate from the Brisket repository and its
services.
- **Code and runtime:**
  - The runtime is stdlib-only: `python3 -m venv --without-pip` plus a `.pth` pointing at
    `src/`. No apt or pip changes on the host.
  - The only network access is public, unauthenticated GETs through `edge_lab.http`.
- **Data, secrets and status:**
  - Private data lives in `/var/lib/market-edge-lab` (`edgelab`, 0700).
  - The env file is `/etc/market-edge-lab/env` (`root:edgelab 0640`). It holds only the
    NWS User-Agent contact and an optional alert URL, never credentials.
  - The non-sensitive status goes to `/var/lib/market-edge-lab-status/latest.json` (0644).
- **Scheduling:**
  - Timers are systemd `OnCalendar` in `America/New_York`, because the host clock is
    Europe/Berlin.
  - `Persistent=false`: a missed window is lost, not fired late.
  - The code checks timing itself, before any network work. It never trusts the timer.
- **Limits:**
  - `MemoryMax=256M`, `CPUQuota=25%`, `TasksMax=32` and `Nice=5`.
  - A bounded `RuntimeMaxSec`.
  - Filesystem hardening (`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
    `NoNewPrivileges`).
- **Failure visibility:** a non-zero exit, an `OnFailure=` alert unit, journald, and the
  status file.
- **Backups:** daily verified SQLite backups (`edge_lab.backup`), with no automatic
  deletion.

**Headroom review (2026-09-22, read-only).** Recorded in
`docs/deploy/VPS_REVIEW_2026-09-22.md`.
- **Host:** 4 vCPU, 7.9 GB RAM (5.9 GB available, no swap), 65 GB disk free.
- **Brisket:** the backend is capped at 3 GB and the frontend at 2 GB.
- **Recent use:** over 7 days, available RAM never fell below 3.9 GB. CPU in the collection
  window was about 3–21%.
- **Result:** PASS for a collector capped at 256 MB.

**Tradeoffs.**
- The fantasy site and the lab share a host. A host outage takes both down, and a Brisket
  memory spike could in principle starve the collector (no swap). The collector's own caps
  protect Brisket, but not the other way round.
- Installation needs the owner's sudo, which is a manual step.
- The Kalshi pacer is per process, so the decision and re-check runs are serialized with a
  lock file.

**Reconsider when**
- a valid-day rate below about 90% is traced to host contention;
- Brisket's memory limits or schedule change materially;
- the collector needs authenticated access or browser automation;
- the lab holds sensitive account data (#10: move to stronger isolation or a dedicated
  host);
- collection frequency grows beyond a few runs per day.
