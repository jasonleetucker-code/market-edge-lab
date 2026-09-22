# Reliability toolkit

Small, model-neutral tools adapted from Brisket. Canonical authority remains
`AI_INSTRUCTIONS.md` and `docs/EXECUTION_PLAN.md`; this guide grants no merge,
deployment, recurring-job, paid-service or trading authorization.

## Session context

From the checkout, with its intended Python environment active:

```sh
python scripts/agent_context.py
```

Prints local HEAD/base, branch/dirty state, interpreter, package-origin status and
hashes of the shared instruction files (`AI_INSTRUCTIONS.md`, `AGENTS.md`,
`CLAUDE.md`, `docs/AGENT_OPERATING_SYSTEM.md`, `docs/EXECUTION_PLAN.md`,
`HANDOFF.md`, `docs/WORK_CLAIMS.md` — the full adapter set enforced by
`tests/invariants/test_instruction_parity.py`). It does not pull, reset, run
models, write a receipt file or pretend to know current remote state. Check live
GitHub PRs and claims separately. A hash is evidence about a file, not proof an
agent read it. Missing origin/main is explicitly null, not silently treated as
up-to-date.

Fingerprints are newline-normalized (CRLF/CR -> LF) before hashing, the same
convention as `scripts/build_exp001_dataset.py`'s `_sha()`: a Windows checkout
with `core.autocrlf=true` reports the same hash for a document as a Linux
checkout of the identical commit. The `bytes` field next to each fingerprint
still reports the real on-disk length, unnormalized.

Use this at material handoffs or environment changes, not before every typo fix.
Load only the actual task's docs; do not paste the entire audit into each agent.

## Validation

```sh
python scripts/validate.py quick
python scripts/validate.py targeted --test tests/test_backup.py
python scripts/validate.py full --base origin/main
```

- `quick`: syntax only. Its success does not mean tests passed.
- `targeted`: syntax and the explicitly named tests. Missing scope/path or no tests
  collected is a failure, not permission to skip. Repeat `--test` for more targets.
- `full`: syntax, comparison-base existence, working-tree-clean check, package-origin
  check, pip dependency check, full pytest suite, experiment validator and existing
  frozen-baseline check. Use a reviewed/fetched upstream base; a stale local ref is
  not live GitHub truth.

The working-tree-clean check fails `full` when `git status --porcelain` reports any
staged, unstaged or untracked change, because `full` stands in for what CI would see
on a clean checkout — it must never report green over local changes it never actually
validated. This is fail-closed by design: commit or stash first, then re-run `full`.

All Python subprocesses use the same interpreter (except the two `git` steps) and
decode output as UTF-8 with `errors="replace"`, so an undecodable byte in subprocess
output is a FAILED check, never a crash with no report. The package-identity check
uses an explicit `if ...: sys.exit(1)` rather than a bare `assert`, so it still catches
a wrong-checkout install when Python runs with `-O`/`PYTHONOPTIMIZE` (which strips
`assert` statements). No command failure is ignored. Full mode cannot be narrowed
with `--test`. A timeout, missing environment, missing base or dependency failure
needs repair; do not relabel it as a passing check. The tool never automatically
installs packages, fetches refs or updates locks, and performs no network operations
of its own (`pip check` and `git status`/`rev-parse` are local-only).

These are local checks. Existing 3.11/3.12 full CI remains unchanged and mandatory.
For browser/API/production work, future domain tests and measured deployment checks
must be added explicitly; the current runner does not claim it tested a future UI.

## Backup and restore rehearsal

Manual use, after installation of the repository package:

```sh
python -m edge_lab.backup create --db data/edge_lab.sqlite3 --out data/backups
python -m edge_lab.backup verify --bundle data/backups/edge-backup-EXACT_ID
```

The create command returns the actual unique bundle path. Use it in the second
command; `EXACT_ID` above is a placeholder, not a real backup.

Each bundle contains `database.sqlite3` and a completion `manifest.json`. Missing
manifest means incomplete. Backups use SQLite's online backup API, preserving
committed *and* uncheckpointed WAL data instead of copying only the main file.
They retain schemas, triggers and all tables; there is no new migration owner.

Creation/verification checks integrity, foreign keys, schema identity and row
counts; verification also restores into a disposable DB. The CLI reports success
only after verification. Source files, existing backups and live DBs are never
overwritten. A missing or wrong source is an error, not a successful empty backup.
Only the unique incomplete bundle created by the failed operation is cleaned up.

Fail-closed schema semantics: a database whose `PRAGMA user_version` does not equal
`edge_lab.storage.SCHEMA_VERSION` is never reported `VERIFIED` — `create`/`verify`
raise instead of silently passing. This means backup and current code must be
upgraded together; a stale backup tool cannot rubber-stamp a newer (or older)
schema as fine. Row counts and the immutability-trigger set are derived dynamically
from `sqlite_master`, not a hardcoded table/trigger list, so a future schema
version's tables and triggers are covered automatically. `create_backup` also
re-inspects the source database after copying and compares its full schema
fingerprint (which includes every trigger's SQL, not just table names) against the
backup's; any difference — a dropped or altered immutability trigger included — is
a failed backup, not a silently incomplete one.

On Windows, `os.fsync` requires a handle opened for writing; fsyncing a handle
opened `"rb"` raises `OSError(EBADF)` there even though POSIX allows it. The
manifest and database file are fsynced through read-write (`"r+b"` for the
already-written database file) handles for that reason.

Limits: logical consistency and a rehearsal do not prove trading correctness,
power-loss durability on every filesystem, malicious-tamper resistance, or off-host
disaster recovery. Hash + manifest in the same place is not an authenticated archive.
It snapshots the SQLite database only, not external raw-data files, configuration
or credentials. Preserve those with a reviewed deployment backup plan later.
There is no scheduled job, remote upload, retention deletion or production restore.
Store bundles in private ignored storage (default convention: under `data/`), not
Git, a public directory or a publicly shared CI artifact. No encryption key is created.

## Efficient multi-model loop

Coordinator identifies the narrow owner and finish line. A specialist receives:
revision, exact task, owned paths, relevant source pointers, test command, forbidden
side effects, and output format. Default to one writer; parallelize independent
bounded work only. Do not assume runtime routing or account credits are identical
between model providers. Inspect actual usage where the runtime exposes it.

A useful handoff is: changed files, actual test command/result, current head, open
findings, and one next action. Correctness claims require executable evidence;
source documents and self-reported flags are not test results. The project deadline
never authorizes touching the holdout early, trading, or relaxing acceptance tests.

The audit and prior external-guidance index are linked in
[`../BRISKET_REUSE_AUDIT.md`](../BRISKET_REUSE_AUDIT.md).
