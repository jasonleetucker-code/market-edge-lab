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
- **A synthetic test value** (a fixture key, a sample topic): add an entry to `ALLOWED` in the script, in a reviewed
  PR. An entry names the fingerprint, the exact paths it is allowed at, and a reason a reviewer can check. The same
  text anywhere else is still a finding.
- **Anything else** (real data that is not this project's credential): report it to the coordinator or owner first.
  Do not allowlist it on your own.

Two kinds of finding can never be allowlisted:
- a `private key block` finding. Its match is the PEM header, which is the same for every key, so one entry would
  hide every private key;
- a commit-message finding, which has no path.

The patterns include every pattern of the tracked-file invariant (`tests/invariants/test_no_secrets.py`).
`tests/test_secret_scan.py` keeps them identical. The scan adds:
- venue auth headers with a value;
- bearer credentials;
- credentials in a URL;
- API-key query values;
- ntfy topic URLs. The topic is a secret (ADR 0022).
- **assigned credentials** (added after the 2026-10-08 review).
  - It covers `NAME=value`, `NAME = "value"`, `NAME: value` (YAML) and `"name": "value"` (JSON).
  - NAME ends in KEY, SECRET, TOKEN, PASSWORD, PASSWD or TOPIC, with `_`, `-` or `.` allowed before it. So
    `API_KEY`, `ODDS_API_KEY`, `NTFY_TOPIC` and `client_secret` all count.
  - These are not flagged:
    - placeholders: `<...>`, `${...}`, `$VAR`, `changeme`, `REDACTED`, `example`, `fake...`;
    - references: dotted names, lower-case words, file paths, calls and type annotations;
    - a bare `key`, `token` or `topic`.
  - A SECRET or PASSWORD value needs 8+ characters.
  - A KEY, TOKEN or TOPIC value must look generated: 16+ characters, with a lower-case letter and a digit.

**Limitations** (`LIMITATIONS`, printed in every result). This is not a complete secret detector. It does not find:
- a bare key id (a UUID) or bare 32-hex key with no credential-like name beside it, for example on a line of its own;
- a value under 8 characters;
- a KEY, TOKEN or TOPIC value under 16 characters, or one without both a lower-case letter and a digit (an all-letter
  ntfy topic, for example);
- an unquoted value made only of lower-case letters and underscores, which is read as a reference;
- a secret split across lines, encoded or compressed;
- binary blobs and blobs over 5 MiB, which are counted and skipped;
- refs that were never fetched into the clone.

A clean scan therefore means "no credential of these shapes". It does not mean "no secret". Keys are kept out of git
by the rules in `docs/SECURITY.md` and [KEYS.md](KEYS.md), not by this scan.

## Recorded results

| Date | Scope | Result |
|---|---|---|
| 2026-10-07 | an earlier pattern-based scan of 787 commits (reported by the campaign coordinator) | clean |
| 2026-10-08 | `--history` with the first version of this script, on branch `exec/o-ops` at `d617faa` (all local refs): 836 commits, 339 refs, 2,578 text blobs | clean. 101 matches across 10 fingerprints were reviewed and allowlisted, all synthetic test values |
| 2026-10-08 | `--history` and `--tree` with the assigned-credential detector, on branch `exec/o-ops` at `d45120b`. History (all local refs): 852 commits, 341 refs, 2,652 text blobs, 852 commit messages, 55 binary blobs skipped, none over the size bound. Tree: 743 files. 106 history and 38 tree matches across 11 path-bound entries were reviewed as synthetic test values and allowlisted | not clean at the time: 1 finding (below), allowlisted by the coordinator's ruling the same day |
| 2026-10-08 | after the ruling, on branch `exec/o-ops` at `3fd8f6d` plus the allowlist change. History (all local refs): 885 commits, 367 refs, 2,708 text blobs, 885 commit messages, 55 binary blobs skipped, none over the size bound. Tree: 743 files | **clean** (`--history` and `--tree` both exit 0). 107 history and 39 tree matches across 12 path-bound entries are allowlisted |

**Coordinator ruling, 2026-10-08: allowlisted.** The one finding of the round-2 scan:
- **Where:** `experiments/EXP-002-nfl-consensus-vs-event-market/fee_evidence/kalshi-fee-schedule_current_2026-09-29T002418Z_HTTP429.headers.txt`,
  line 5, fingerprint `ef64c49b08cfdd21`.
- **What:** an `X-Vercel-Challenge-Token` header.
- **Ruling:** the coordinator ruled it harmless. It is a third-party, non-credential, ephemeral challenge token:
  - a third party's CDN issued it in an HTTP 429 response to an unauthenticated public page fetch;
  - it grants no access to any account, this project's or anyone else's.
- **How it is allowlisted:** a path-bound `ALLOWED` entry that cites the ruling.
- **The evidence file stays unedited.** It is immutable fee evidence.

Re-run and add a row before each credential decision is used. Re-run after any history rewrite, and whenever
`.github/workflows/` starts publishing an artifact.

## CI artifacts

Today CI publishes no artifact, reads no repository secret and runs with `contents: read`.
`tests/execution/test_ops_units.py` pins this. A workflow that adds `upload-artifact` must also:
- scan the artifact directory with `--paths` in the same job, before the upload step;
- change that test in the same reviewed PR.
