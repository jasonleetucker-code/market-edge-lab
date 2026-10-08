# Secret scan: full history, tree and artifacts

**Approval gate:** none to run it: it is read-only and offline. It must be **clean on the exact release commit before
any credential approval is used** ([KEYS.md](KEYS.md)), before an executor install ([INSTALL.md](INSTALL.md)), and
before any CI artifact or export is published.

`scripts/secret_scan.py` uses the standard library only. It runs `git` locally and reads files. It sends nothing.

| Command | Scans |
|---|---|
| `python scripts/secret_scan.py --history` | every blob and every commit message reachable from any ref in this clone |
| `python scripts/secret_scan.py --history --rev <SHA>` | the history of one release commit |
| `python scripts/secret_scan.py --tree` | tracked files as they are in the working tree |
| `python scripts/secret_scan.py --paths <dir or file> ...` | artifacts before upload: junit XML, logs, exports |

Exit codes:
- 0: clean;
- 1: findings;
- 2: the scan could not run (no git, not a repository, a missing path).

A scan that did not run is never clean.

## Reading a result

A finding names:
- the pattern;
- the path;
- the blob or commit;
- the line;
- a 16-hex SHA-256 fingerprint of the match.

**It never prints the value.**

For each finding:
- **A real credential:** treat it as compromised. Revoke it at the provider first, then follow `docs/SECURITY.md`,
  "If a secret is committed". Never allowlist a real credential.
- **A synthetic test value** (a fixture key, a sample topic): add its fingerprint to `ALLOWED_FINGERPRINTS` in the
  script, with a reason a reviewer can check, in a reviewed PR.

The patterns include every pattern of the tracked-file invariant (`tests/invariants/test_no_secrets.py`).
`tests/test_secret_scan.py` keeps them identical. The scan adds:
- venue auth headers with a value;
- bearer credentials;
- credentials in a URL;
- API-key query values;
- ntfy topic URLs. The topic is a secret (ADR 0022).

**Limitations** (repeated in every result):
- it finds credential shapes, so a bare UUID key id or an unprefixed 32-hex key is not detected;
- binary blobs and blobs over 5 MiB are counted and skipped;
- `--history` covers only the refs present in the clone.

## Recorded results

| Date | Scope | Result |
|---|---|---|
| 2026-10-07 | an earlier pattern-based scan of 787 commits (reported by the campaign coordinator) | clean |
| 2026-10-08 | `--history` with this script, run locally at `8837311`: 827 commits, 334 refs, 2,518 text blobs, 827 commit messages, 55 binary blobs skipped, none over the size bound | clean. 99 matches across 10 fingerprints were reviewed and allowlisted, all synthetic test values: fixture API key, sample ntfy topics, redaction-test header samples |
| 2026-10-08 | `--tree` at the same commit (719 files) | clean |

Re-run and add a row before each credential decision is used. Re-run after any history rewrite, and whenever
`.github/workflows/` starts publishing an artifact.

## CI artifacts

Today CI publishes no artifact, reads no repository secret and runs with `contents: read`.
`tests/execution/test_ops_units.py` pins this. A workflow that adds `upload-artifact` must also:
- scan the artifact directory with `--paths` in the same job, before the upload step;
- change that test in the same reviewed PR.
