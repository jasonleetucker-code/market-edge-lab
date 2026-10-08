# Private journal backups, restore drills and restores

**Approval gate:**
- Drills on disposable copies (a developer machine, pytest's temporary directories): no approval.
- On the executor host: manual backups, verification and drills are covered by the install approval
  ([INSTALL.md](INSTALL.md)).
- A backup **schedule** (a timer) needs its own owner approval.
- A **real restore** replaces the executor's working journal. It needs the owner's go-ahead in the incident record.
- **Off-host copies** need their own approval. The journal holds account data.

## What a journal backup is

`ops backup` (`edge_lab.execution.journal_backup`, ADR 0048) works like this:
1. It refuses before writing anything when:
   - the live journal is missing or is not this code's schema;
   - the backup root is missing or sits beside the journal;
   - free space is short (`DISK_PRESSURE`). It needs room for the copy, a disposable verification copy and the
     same again as headroom, plus 64 MiB.
2. It copies with the SQLite online backup API in one step. That gives one consistent snapshot even while the
   executor commits.
3. It verifies the copy by restoring it into a disposable directory:
   - SQLite integrity and foreign keys;
   - every table, index and trigger;
   - the hash chain (`verify_chain`);
   - per-table identity digests of intents, approvals, attempts, receipts, reservations and snapshots.
4. Only then does it publish the bundle `exec-journal-<UTC>-<id>/`, holding `journal.execution.sqlite3` and
   `manifest.json`. The manifest holds counts and digests only. It has no intent, order, receipt or approval
   identifier and no payload.

Any failure removes only that run's `.partial-*` directory. Earlier bundles and the live journal are untouched. An
interrupted run leaves a `.partial-*` directory that is never counted as a backup.

The rules that keep these backups separate:
- They are separate from research backups. Different user, directory and command. They never go in
  `/var/lib/market-edge-lab/backups` and never in the research off-host pull.
- No key is ever in a backup. Keys live in `/etc/market-edge-lab-exec/credentials/`, which the backup unit cannot
  see. A restore never needs a key.
- Nothing is deleted automatically. Pruning needs an approved retention policy, as the research backups did.

## Manual backup (owner, on the host)

```bash
sudo systemctl start edgelab-exec-backup.service
sudo journalctl -u edgelab-exec-backup.service -n 5 --no-pager    # one JSON line: "ok":true, bundle, counts
sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops verify-backup --bundle /var/lib/market-edge-lab-exec-backup/journal/<bundle>
```

## Restore drill (owner, on the host; suggested monthly and after every deploy)

The drill writes only into a drill directory, never over a live path. It removes its own copy unless you pass
`--keep`.

```bash
sudo install -d -o edgelab-exec -g edgelab-exec -m 0700 /var/lib/market-edge-lab-exec-backup/drill
sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops restore-drill --bundle /var/lib/market-edge-lab-exec-backup/journal/<bundle> --drill-dir /var/lib/market-edge-lab-exec-backup/drill --live /var/lib/market-edge-lab-exec/journal/kalshi.execution.sqlite3
```

Expect:
- `"verified":true` and `"removed_after_drill":true`;
- the identity's `in_flight_attempts` and `outcome_unknown_attempts`. Those attempts would need reconciling after a
  real restore.

The automated equivalent runs in CI on disposable stores: `tests/execution/test_ops_backup.py`. It covers:
- a writer committing during the backup;
- failure at every stage;
- disk pressure;
- an interrupted migration;
- restart DISARMED after a restore.

## Real restore (owner, during an incident)

Never restore over live evidence. The damaged journal is kept, and the restore writes a new file.

```bash
sudo systemctl stop edgelab-exec.service                                   # 1. no writer
J=/var/lib/market-edge-lab-exec/journal; STAMP=$(date -u +%Y%m%dT%H%M%SZ); E=/var/lib/market-edge-lab-exec/evidence-$STAMP
sudo install -d -o edgelab-exec -g edgelab-exec -m 0700 "$E"                # 2. keep the damaged journal and its side files, together
for s in "" -wal -shm; do sudo test -e "$J/kalshi.execution.sqlite3$s" && sudo mv -n "$J/kalshi.execution.sqlite3$s" "$E/"; done; sudo ls -l "$E"
sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops restore --bundle /var/lib/market-edge-lab-exec-backup/journal/<newest verified bundle> --target "$J/restored-$STAMP.execution.sqlite3" --live "$E/kalshi.execution.sqlite3"   # 3. a NEW file, verified
sudo runuser -u edgelab-exec -- mv -n "$J/restored-$STAMP.execution.sqlite3" "$J/kalshi.execution.sqlite3"   # 4. into the empty live name (-n: never over a file)
```

Between step 2 and step 4 the journal path is empty. The start check refuses that (`JOURNAL_MISSING`, exit 65),
so a start in that window cannot create an empty journal. Never use `--first-start` here. It is refused anyway,
because backup bundles exist.

Then:
- Start through [START_DISARMED.md](START_DISARMED.md). Read these notes first.
- **The lease.** The restored lease belongs to the worker recorded in the backup. A different worker id waits until
  it expires. The same worker id takes over at once with a new fence.
- **Local history is missing.** Everything recorded after the backup's `created_at_utc` exists only in the evidence
  copy and at the venue. Orders sent in that gap appear in the first account read as orders the journal does not
  know: unattributed, conservatively reserved, never adopted.
- **Keep it DISARMED until reviewed.** Do not arm until all of these hold:
  - a COMPLETE reconciliation;
  - every OUTCOME_UNKNOWN attempt resolved from the venue;
  - the owner has compared the gap with the venue's order and fill history.

  Set a GLOBAL NEW_RISK latch for the review. The journal keeps it across restarts.

## Proposed schedule (NOT shipped: its own approval)

When approved, add a timer like this one, outside the research windows. It runs daily after the research backup
(04:40 UTC), with no catch-up:

```ini
[Timer]
OnCalendar=*-*-* 04:55:00 UTC
Persistent=false
Unit=edgelab-exec-backup.service
```

The health check alerts when the newest complete backup is older than 26 hours (`BACKUP_STALE`). It also alerts
when the live chain no longer contains that backup's head event (`ANCHOR_BROKEN`: truncated or replaced).
