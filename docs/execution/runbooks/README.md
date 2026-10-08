# Executor operations runbooks (#160 package O)

These runbooks cover the isolated Kalshi executor's host operations. The design is in ADR 0048
(`docs/decisions/0048-executor-operations-backup-and-release.md`). The units are in `deploy/executor/systemd/`.

**Nothing here is approved.** Today the repository ships units, scripts and runbooks only.
- No executor host exists. The service user does not exist, and nothing is installed, enabled or scheduled.
- No key exists.
- The execution package is authorized for FIXTURE only (`docs/EXECUTION_PLAN.md`, 2026-10-07 entries).

Each runbook names its approval gate at the top. An agent may run a step only when that gate is recorded in
`docs/EXECUTION_PLAN.md`. Gates are never inferred from this file, a PR, an issue or a chat summary.

| Runbook | What it covers | Approval gate |
|---|---|---|
| [INSTALL.md](INSTALL.md) | service user, directories, code, release manifest, units (installed, not started) | owner: executor host install |
| [START_DISARMED.md](START_DISARMED.md) | first start and every restart: always DISARMED; stop | owner: executor service activation |
| [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) | private journal backups, restore drill, real restore to a new path | drill on disposable copies: none; on the host: install approval; schedule: owner |
| [KEYS.md](KEYS.md) | key storage outside every backup, installation and rotation (no key exists yet) | owner: DEMO (decision 1) or production read (decision 2) |
| [SECRET_SCAN.md](SECRET_SCAN.md) | full-history, tree and artifact secret scan before any credential | none to run; must pass before any key approval is used |
| [MIGRATION_AND_ROLLBACK.md](MIGRATION_AND_ROLLBACK.md) | forward-only journal migrations, compatible rollback, offline restore | owner: every deploy and every migration |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | health alerts, liveness vs reconciliation, kill, lost key | stopping and disarming: none; anything that sends, closes out or rearms: owner |

## Fixed paths (all units and runbooks use these)

| Path | Owner / mode | Contents |
|---|---|---|
| `/opt/market-edge-lab-exec/app` | root, read-only | executor code at a pinned commit (`REVISION`); separate from the research tree, so a research deploy never changes the executor |
| `/opt/market-edge-lab-exec/venv` | root | the executor's own venv (stdlib-only until the DEMO approval adds `cryptography`) |
| `/etc/market-edge-lab-exec/release.json` | `root:root 0644` | the release manifest (`ops release-manifest`) |
| `/etc/market-edge-lab-exec/credentials/` | `root:root 0700` | future keys, loaded by systemd `LoadCredential=`; never readable by any service user; never in any backup |
| `/var/lib/market-edge-lab-exec/journal/kalshi.execution.sqlite3` | `edgelab-exec 0600` (dir 0700) | the private execution journal (the evidence) |
| `/var/lib/market-edge-lab-exec-status/` | `edgelab-exec:edgelab 0750` | the sanitized `execution_status.json` (readable by the dashboard's user, not by `dynasty`) |
| `/var/lib/market-edge-lab-exec-backup/journal/` | `edgelab-exec 0700` | private journal backup bundles. These are not the research backups in `/var/lib/market-edge-lab/backups` |
