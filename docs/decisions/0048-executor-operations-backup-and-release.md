# ADR 0048: Executor operations: service identity, private journal backups, release manifest, health and secret scan

**Status:** Proposed 2026-10-08 (#160, campaign package O). Authority: the 2026-10-07 entries of
`docs/EXECUTION_PLAN.md`. They authorize the offline execution package (FIXTURE only) and its documentation. Any
executor deploy, service activation, schedule or credential needs its own owner approval. Boundary: ADR 0043.
Orchestrator: ADR 0046.

## Problem

Package O asks that execution recovery be "operationally repeatable without damaging research or the other
application". Concretely:
- a dedicated service identity with minimum privileges and resource headroom;
- a health and alert path that keeps liveness apart from reconciliation health;
- private journal backups and restore drills that preserve order-intent and receipt identity;
- key storage outside research backups;
- a full-history secret scan before any credential;
- rollback that never assumes old code can run against a newer schema.

Today nothing may be installed, enabled, scheduled or keyed, so all of this must exist as tested software, unit
files and runbooks that are inert until approved.

Three facts shape the design:
- **The research backup can't be used.** `edge_lab.backup` lives outside the execution package and imports the
  research store. The package may not import it (ADR 0043).
- **The journal accepts only its own schema.** It refuses any store whose schema objects differ from its own
  (`_check_schema_objects`), so it accepts exactly one schema per code version.
- **The ledger flags a version gap.** It notes that the version-1 schema changed in place before #165 merged.

## Decision

1. **Separate executor identity, code tree and directories.** The user is `edgelab-exec`, with its own
   `/opt/market-edge-lab-exec/{app,venv}`, `/var/lib/market-edge-lab-exec*` and `/etc/market-edge-lab-exec`. A
   research deploy never changes executor code: `install.sh` copies only `deploy/vps/systemd/`, and the executor
   has its own `REVISION`. The executor venv can later gain `cryptography` while the research venv stays
   stdlib-only.
2. **Units ship disabled and cannot be enabled.** `deploy/executor/systemd/` holds the executor service, a backup
   oneshot, a health oneshot and their own slice:
   - none has an `[Install]` section, and there is no timer;
   - nothing in `deploy/`, `scripts/` or CI names them (a test enforces this);
   - starting at boot is an explicit `systemctl add-wants` under the activation approval.

   The proposed timers are text in the runbooks, each its own approval.
3. **Least privilege as kernel-enforced unit settings.**
   - no capabilities, `NoNewPrivileges` and `ProtectSystem=strict`;
   - writes only under executor paths;
   - research data, research secrets and the credentials directory are inaccessible;
   - `RestrictAddressFamilies=AF_UNIX` and `IPAddressDeny=any`. FIXTURE needs no network, and opening egress is
     part of the DEMO approval;
   - memory, CPU and task caps inside a 768M slice. With the research slice that is 1.15 GB, against the VPS's
     lowest observed 3.9 GB available.
4. **Journal backups live in the package, as `execution/journal_backup.py`.** It is the third file allowed
   `sqlite3` (`SQLITE_FILES` in the boundary invariant).
   - It reads a journal only through query-only connections that never create a file, and it opens journals for
     verification only through `ExecutionJournal.open`.
   - The copy uses the SQLite online backup API in one step: a consistent snapshot while a writer commits.
   - Verification is a disposable restore: integrity, every schema object, `verify_chain` and per-table identity
     digests. Then the bundle is published by rename.
   - The manifest holds counts and digests only.
   - The disk-pressure, time-budget and fault seams fail before publishing, and remove only the call's own partial
     directory.
   - The newest bundle's chain head is an external anchor: a live chain that no longer contains it was truncated or
     replaced. `verify_chain` alone cannot see that.
5. **A restore always writes a NEW file.** The target must not exist (nor its side files) and may not be a live
   path. It is created by an atomic no-overwrite link, then chain-verified and identity-checked against the
   manifest. A drill removes its own copy. A restored journal starts DISARMED like any start. Its in-flight attempts
   become OUTCOME_UNKNOWN when the lease is taken, and anything after the backup is reconciled from the venue,
   never re-sent.
6. **The release manifest is generated at release time** (`execution/release.py`). It pins:
   - code revision;
   - journal kind, version and fingerprint;
   - contract schemas;
   - fee schedule ids with a digest of their terms;
   - the profile;
   - `AUTHORIZED_ENVIRONMENTS`;
   - an optional compatible rollback, which must share the journal schema.

   The executor's start (`ops run`) checks the manifest against the installed `REVISION` and the journal before
   anything else. A store newer or older than the release, or with different objects, is refused.
7. **Forward-only migrations.** One schema version names one schema: `KNOWN_SCHEMA_FINGERPRINTS` in the tests pins
   v1's fingerprint, so an in-place change cannot merge.
   - A migration is one transaction, run as its own approved step after a pre-migration backup taken by the
     *current* release.
   - A code rollback is allowed only to the manifest's named compatible release.
   - Anything else is an offline restore of the pre-migration backup to a new path, with the migrated file kept as
     evidence.
8. **The ledger's "bump the schema version" note is closed without a bump.** No persistent store exists (FIXTURE
   only), and the schema has not changed since #165 merged. Pre-merge v1 stores are refused by the exact object
   check, and the pinned fingerprint now prevents a second v1.
9. **Health has two verdicts that never read each other's data** (`execution/health.py`, pure over the status
   export):
   - liveness reads `generated_at_utc`, `service` and `cycles`;
   - reconciliation reads `journal`, `control`, `attempts` and `account`.

   Backup age with the chain anchor, and free disk, are separate verdicts. The exit code sets one bit per failing
   verdict, and failures reuse the existing `edgelab-alert@` path (ADR 0028). There is no second alert channel.
10. **Operator output is sanitized.** `execution/ops.py` prints one JSON line per command. Every string passes
    `redaction.redact_text`, then the whole line passes the new `redaction.contains_unredacted_secret`. That is the
    same patterns with already-redacted values set aside, so the redaction owner is extended, not forked. Errors
    are one redacted line, never a traceback.
11. **Keys are root-only files loaded by systemd `LoadCredential=`.** They sit in `/etc/market-edge-lab-exec/credentials`,
    readable at rest by no service account and outside every backup path. This supersedes the activation packet's
    draft of a key file owned by the service user.
12. **Secret scan: `scripts/secret_scan.py`.** It is stdlib-only and covers every blob and commit message on all
    refs, the tracked tree, or artifact paths.
    - Findings carry a fingerprint, never the value.
    - Reviewed synthetic values are allowlisted by fingerprint with a reason.
    - Its patterns are a pinned superset of `test_no_secrets.py`.
    - CI publishes no artifact today, and a test pins that.

## Alternatives rejected

- **Extend `edge_lab.backup`.** That crosses the package boundary in both directions, and it would mix private
  account data into the research backup tree and its off-host pull.
- **Copy the journal file with `cp`.** That is not consistent while a WAL writer commits.
- **Back up with `VACUUM INTO`.** It is consistent, but it rewrites pages. The online backup API copies the snapshot
  as is.
- **A key file owned by `edgelab-exec`.** Anything running as that user could copy it at rest.
- **Ship the timers disabled.** The campaign's limit is "no timers". A disabled timer is one `enable` away from a
  schedule nobody approved.
- **Bump the journal to v2 now.** That changes nothing a store could observe, and it touches a merged lane's file.
- **Collapse health into one boolean.** A live process with a lost reconciliation would read as healthy.

## Tradeoffs

- **Disk.** A backup needs about three times the journal's size free while it runs.
- **Runtime.** The backup verifies by a disposable restore, and the schema fingerprint is computed by creating an
  empty journal, about tens of milliseconds per call.
- **Fixed paths.** The units name fixed paths. A different layout is a reviewed change, not configuration.
- **The executor unit is a placeholder.** `ops run` refuses (exit 78) until the networked runner arrives with the
  DEMO approval, so the executor unit proves the start check and the refusal only.
- **The scan has limits.** It finds credential shapes, not every secret. Its limitations are printed with every
  result.

## Reconsider when

- The DEMO approval arrives. The runner, key loader, `LoadCredential` drop-in and egress change come in one reviewed
  PR.
- A second journal schema version is needed. Then the migration command and its tests arrive.
- Journal growth or backup time measured on the host (package P, unmerged) says a backup no longer fits its budget.
- Off-host executor backups are wanted. They need their own approval and encryption design.
