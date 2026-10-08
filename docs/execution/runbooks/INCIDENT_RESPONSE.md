# Executor incident response

**Approval gate:**
- Steps that only remove risk need no further approval once the executor is installed: stopping the executor,
  keeping it DISARMED, setting a latch, taking a backup and reading status.
- Every step that sends something, closes a position or rearms needs the owner, every time:
  - cancelling owned orders;
  - an authorized closeout;
  - acknowledging an incident in order to arm;
  - rotating or revoking a key.

## The health check: liveness is not reconciliation health

`ops health`, run by `edgelab-exec-health.service`, prints four separate verdicts. Its exit code sets one bit for
each verdict that fails, and any non-zero exit fails the unit. The existing `edgelab-alert@` path then records the
failure and pushes a fixed headline (ADR 0028). Read the unit's journal for the verdicts:

```bash
sudo journalctl -u edgelab-exec-health.service -n 3 --no-pager
```

| Bit | Verdict | Means | Do |
|---|---|---|---|
| 1 | **Liveness** not LIVE (STALE, STOPPED, NEVER_STARTED, UNKNOWN) | the executor has not written its status or finished a cycle within the bound (5 min by default) | `systemctl status edgelab-exec.service` and its journal. A restart is DISARMED ([START_DISARMED.md](START_DISARMED.md)). Resting orders stay at the venue: check them there |
| 2 | **Reconciliation** not HEALTHY (DEGRADED, UNKNOWN) | the executor's view of the account cannot be trusted now. The reasons name which check failed: chain not verified, last read not COMPLETE or too old, open incident, OUTCOME_UNKNOWN attempts, quarantined reservations, inconsistent snapshot | Keep it DISARMED. The orchestrator already disarms with an incident when reconciliation is lost in SHADOW or a sending mode. Do not acknowledge an incident to arm until a COMPLETE read explains it |
| 4 | **Backup** not OK (MISSING, STALE, ANCHOR_BROKEN) | no complete backup within 26 h, or the live chain no longer contains the newest backup's head event | MISSING or STALE: run a manual backup ([BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)). ANCHOR_BROKEN: the live journal was truncated or replaced. Stop the executor, keep every file, compare with the backup, and do not restore over anything |
| 8 | **Disk** not OK (DISK_PRESSURE, UNKNOWN) | under 2 GiB free on the journal volume | Free space without touching evidence. The journal grows by about 11 KB a cycle in the package P measurement (branch `exec/p-chaos`, unmerged): about 16 MB a day at one cycle a minute. A full disk makes every journal write fail loudly (`JournalUnavailable`), and nothing is half-written |

**The two verdicts are kept apart on purpose.** A process that is LIVE but DEGRADED is cycling on a view it must not
trade on. A process that is STALE with a HEALTHY last reconciliation is dead with a clean last state. Neither verdict
reads the other's part of the status export, and `tests/execution/test_ops_health.py` proves it.

## Stop new risk now

1. `sudo systemctl stop edgelab-exec.service`. Nothing re-arms, and the next start is DISARMED.
2. When a running executor is needed for reads, keep it DISARMED and set a GLOBAL NEW_RISK latch. Latches persist
   across restarts, and only an explicit `ClearLatch` removes them.
3. **Resting orders.**
   - With a running executor: cancelling owned orders is a CANCEL_OWNED action, which the owner requests.
   - With no executor: cancel in the venue's own interface. That is the owner's step.

   A closeout is never automatic. It needs a `CloseoutAuthorized` from the owner.

## A key is lost, leaked or suspected

1. Revoke it at the venue first. Nothing else stops a stolen key.
2. Stop the executor.
3. Follow [KEYS.md](KEYS.md) ("Compromise") and `docs/SECURITY.md`.

## A secret reached a log, an artifact or git

1. Treat it as compromised, and revoke the credential.
2. Run [SECRET_SCAN.md](SECRET_SCAN.md) on the history and on the artifact.

The operator commands print one redacted JSON line, never a traceback (`ops` docstring), and the status export
refuses anything secret-looking. A leak means one of those guards was bypassed. Record which.

## The journal does not open, or the chain does not verify

- Do not repair it in place, and do not delete it.
- Stop the executor and move the files aside as evidence.
- Restore the newest verified backup to a NEW path, then reconcile the gap against the venue before any arm
  ([BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md), "Real restore").

## Proposed health schedule (NOT shipped: its own approval)

```ini
[Timer]
OnCalendar=*-*-* *:00/5:30 UTC
Persistent=false
Unit=edgelab-exec-health.service
```

## Record

For every incident, record:
- what happened;
- the verdicts;
- what was stopped;
- what the venue showed;
- what the owner decided.

Use a dated note under `docs/deploy/` or the incident issue. The journal keeps the control incidents themselves.
