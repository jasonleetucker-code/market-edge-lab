# Forward-only journal migrations, compatible rollback and offline restore

**Approval gate:** owner approval of **every executor deploy and every journal migration**, recorded in
`docs/EXECUTION_PLAN.md`. A migration is its own step, never a side effect of starting new code.

## Rules (ADR 0048)

1. **Forward-only.** A journal schema only moves forward. No code ever converts a store back to an older version.
2. **One version, one schema.** `journal.SCHEMA_VERSION` names exactly one set of tables, indexes and triggers. Its
   fingerprint is pinned in `tests/execution/test_ops_release.py` (`KNOWN_SCHEMA_FINGERPRINTS`). Changing any schema
   object without bumping the version fails CI.
3. **Old code never runs against a newer store.** Three checks refuse it:
   - `ExecutionJournal.open` refuses a newer version, an older one, or any changed object (`UnknownSchema`);
   - the release check refuses it (`STORE_NEWER_THAN_RELEASE`, `STORE_OLDER_THAN_RELEASE`,
     `STORE_SCHEMA_OBJECTS_DIFFER`) before the executor does anything;
   - the backup tool refuses a store that is not its own schema.
4. **A rollback is code-only, and only to a compatible release.** That means the release named in the current
   manifest's `compatible_rollback`, with the same journal schema. Anything else is an offline restore, never a
   rollback.

## Today

- **Only schema version 1 exists.** No migration code exists, and none is needed.
- **The package D ledger note.** The note reads "bump the schema version before any persistent store exists". The
  version-1 schema changed in place while #165 was unmerged. Assessment on 2026-10-08:
  - No persistent store exists anywhere. Only FIXTURE disposable stores have been created.
  - The schema has not changed since #165 merged (`0bac2b9`): the later journal changes (#171, #175) added no table,
    index or trigger.
  - A store made by pre-merge branch code is refused on open, because every object's SQL must match exactly.
  - Bumping to 2 would buy nothing, and the pinned fingerprint now makes an in-place change impossible to merge. So
    the note is satisfied without a bump. Package O records this; the ledger owner updates the row.

## Migrating to a new schema (when one exists)

The future `vN → vN+1` migration must be one SQLite transaction. SQLite DDL is transactional, so an interrupted
migration leaves vN intact. It must be followed by `verify_chain` and the release check.

1. Stop the executor ([START_DISARMED.md](START_DISARMED.md)). Record any in-flight or OUTCOME_UNKNOWN attempts
   from the last status.
2. Take a **pre-migration backup with the current release**, the one that still runs vN. Verify it and drill it
   ([BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)). The new code cannot back up a vN store.
3. Install the new release ([INSTALL.md](INSTALL.md)). The old tree stays at `app.prev` and the old manifest at
   `release.json.prev`. The new manifest has **no** `compatible_rollback`, because no vN release can run against
   vN+1.
4. Run the migration as its own approved step, then the release check. Expect `"ok":true`.
5. Start DISARMED, reconcile, run a health check and take a backup with the new release.

## Compatible rollback (same journal schema)

Use this only when the current manifest's `compatible_rollback.code_revision` is the target:

```bash
sudo systemctl stop edgelab-exec.service
sudo mv /opt/market-edge-lab-exec/app /opt/market-edge-lab-exec/app.bad && sudo mv /opt/market-edge-lab-exec/app.prev /opt/market-edge-lab-exec/app
sudo mv /etc/market-edge-lab-exec/release.json /etc/market-edge-lab-exec/release.json.bad && sudo mv /etc/market-edge-lab-exec/release.json.prev /etc/market-edge-lab-exec/release.json
sudo install -o root -g root -m 0644 /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec.slice /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec.service /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec-backup.service /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec-health.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops release-check --manifest /etc/market-edge-lab-exec/release.json --revision-file /opt/market-edge-lab-exec/app/REVISION --journal /var/lib/market-edge-lab-exec/journal/kalshi.execution.sqlite3
```

The release check must print `"ok":true`. Then start DISARMED.

## Incompatible rollback: an offline restore, never old code on a new store

Use this when the target release runs an older journal schema than the store, for example after a migration:
1. Stop the executor. Move the migrated journal and its side files aside as evidence. It is never deleted or
   repaired in place.
2. Restore the **pre-migration** bundle to a NEW file, then move it into the empty live name. Use the "Real restore"
   steps in [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md).
3. Install the old release (its code tree and manifest), then run the release check.
4. Start DISARMED. Everything recorded after the migration exists only in the evidence copy and at the venue. Keep
   the executor DISARMED, with a GLOBAL NEW_RISK latch, until the owner has reconciled that gap against the venue's
   order and fill history.

## An interrupted or half-applied migration

The store no longer opens (`UnknownSchema`), the release check names the problem, and the backup tool refuses it.
`tests/execution/test_ops_backup.py` exercises a version stamped ahead, a version stamped behind and an extra table.
To recover:
- do not edit it with `sqlite3`;
- keep the file as evidence;
- restore the pre-migration backup as above.
