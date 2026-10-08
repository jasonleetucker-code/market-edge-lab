#!/usr/bin/env python3
"""Repeatable secret scan: tracked files, the full git history, or artifact files (#160 package O, ADR 0048).

Run it before any credential is introduced, before publishing a CI artifact, and after any history rewrite:

    python scripts/secret_scan.py --history          # every blob and commit message reachable from any ref
    python scripts/secret_scan.py --tree             # tracked files as they are in the working tree
    python scripts/secret_scan.py --paths DIR_OR_FILE ...   # artifacts (junit XML, logs, exports) before upload

Standard library only, offline: it runs `git` locally and reads files; it sends nothing. Exit 0 when clean, 1 with
findings, 2 when the scan itself could not run (no git, not a repository): a scan that did not run is never clean.

**A finding never prints the secret.** It names the pattern, the path, the blob or commit, the line and a short
SHA-256 fingerprint of the match, so the owner can locate and revoke it. Rotation and revocation are the owner's
steps (`docs/SECURITY.md`, "If a secret is committed"); deleting a file or rewriting history does not un-leak a
pushed secret.

**Limitations** (`LIMITATIONS`, reported in every result): it finds credential *shapes* and credential-named
assignments, not every secret. Not detected: a bare key id (a UUID) or a bare 32-hex key with no credential-like name
beside it, short values, an all-letter KEY/TOKEN/TOPIC value, an unquoted lower-case identifier-like value (read as a
reference), a secret split across lines or encoded. Binary blobs and blobs over `MAX_BLOB_BYTES` are counted and
skipped. `--history` covers the refs present in this clone (`git rev-list --all`); a ref never fetched is not scanned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator

MAX_BLOB_BYTES = 5 * 1024 * 1024
FINGERPRINT_CHARS = 16

# Credential shapes. The first six are exactly the tracked-file invariant's (`tests/invariants/test_no_secrets.py`);
# a test keeps them identical, so this scan always covers at least what CI already refuses.
PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "OpenAI/Anthropic-style key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{24,}\b"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
    "assigned secret": re.compile(
        r"""(?i)\b(api[_-]?key|secret|password|access[_-]?token)\b\s*[:=]\s*["'][^"'\s]{12,}["']"""
    ),
    # Venue and HTTP credentials with a value attached (a header name alone is not a finding).
    "venue auth header value": re.compile(
        r"(?i)\bkalshi-access-(?:key|signature)\b[\"']?\s*[:=]\s*[\"']?(?!kalshi-)[A-Za-z0-9+/=_-]{16,}"),
    "bearer credential": re.compile(r"(?i)\bauthorization\b[\"']?\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    "credentials in a URL": re.compile(r"\bhttps?://[A-Za-z0-9._~%-]+:[A-Za-z0-9._~%!$&'()*+,;=-]{6,}@[A-Za-z0-9.-]+"),
    "API key query value": re.compile(r"(?i)[?&]api_?key=[A-Za-z0-9]{24,}\b"),
    "ntfy topic URL": re.compile(r"\bhttps?://ntfy\.sh/[A-Za-z0-9_-]{12,}"),
    # A credential assigned to a credential-like NAME, in any of the forms config files use: `NAME=value`, `NAME =
    # "value"`, `NAME: value` (YAML) and `"name": "value"` (JSON). NAME ends in KEY, SECRET, TOKEN, PASSWORD, PASSWD
    # or TOPIC (case-insensitive, `_`, `-` or `.` allowed before it, so ODDS_API_KEY and ntfy_topic count). Each match
    # is then judged by `_credential_value` below, which drops placeholders and references.
    "assigned credential": re.compile(
        r"""(?ix)(?<![A-Za-z0-9])(?P<q>["']?)(?P<name>[A-Za-z0-9_.-]*?(?:key|secret|token|passw(?:or)?d|topic))(?P=q)
        \s*(?::|=(?!=))\s*(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s,;#}\])"']+)"""),
}

_STRONG_NAME = re.compile(r"(?i)(secret|passw(?:or)?d)$")  # a bare SECRET or PASSWORD is already a credential name
_WEAK_WORD = re.compile(r"(?i)^(key|token|topic)$")  # bare `key`, `token`, `topic` are ordinary program words
_PLACEHOLDER = re.compile(
    r"(?i)^(<.*>|\$\{.*\}|\$[A-Za-z_]\w*|\{\{.*\}\}|%\(.*\)s|change[-_]?me|redacted|.*example.*|x{3,}|\*{3,}|"
    r"none|null|nil|true|false|todo|tbd|placeholder|dummy|fake.*|your[-_].*|\.\.\.|…|-+)$")
# A dotted name, or a lower-case word made of letters and underscores only (a value with a digit is not a reference).
_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$|^[a-z_]+$")
_PATH = re.compile(r"^([rbfu]{0,2}[\"'])?(/|\./|\.\./|~/|[A-Za-z]:[\/])|\\")  # a file path, or anything with `\`
_SECRET_SHAPE = re.compile(r"^[A-Za-z0-9+/=_~.-]{16,}$")


def _credential_value(match: re.Match[str]) -> bool:
    """Whether an `assigned credential` match holds a literal that could be a credential (`LIMITATIONS` says what
    this misses). Rules, in order:
    - a bare `key`, `token` or `topic` is a program word, not a credential name;
    - placeholders (`<...>`, `${...}`, `$VAR`, `{{...}}`, `changeme`, `REDACTED`, `example`, `fake...`, `xxx`, booleans,
      `None`) are not values, and neither is the name itself (an enum constant such as `REFUSED_SECRET =
      "REFUSED_SECRET"`);
    - a reference is not a value: an unquoted dotted name (`os.environ`, `self.key`) or lower-case identifier
      (`api_key = api_key`, a type annotation such as `token: str`), a file path, or anything holding `(`, `[`, `{`,
      `%` or a backtick;
    - SECRET and PASSWORD names: any remaining value of 8+ characters;
    - KEY, TOKEN and TOPIC names: a secret-shaped value: 16+ characters from `[A-Za-z0-9+/=_~.-]` with a lower-case
      letter and a digit. So identifiers and market tickers (`intent_key="EXP-TEST:ticket-0001"`,
      `event_key="KXHIGHNY-26OCT09"`) are not flagged, while hex keys, UUID key ids, base64 tokens and generated
      topics are."""
    name, raw = match.group("name"), match.group("value")
    quoted = raw[:1] in "\"'" and raw[-1:] == raw[:1] and len(raw) >= 2
    value = raw[1:-1] if quoted else raw
    if _WEAK_WORD.match(name) or not value or _PLACEHOLDER.match(value) or value.lower() == name.lower():
        return False
    if any(c in value for c in "([{%`") or _PATH.search(raw) or (not quoted and _REFERENCE.match(value)):
        return False
    if len(value) < 8:
        return False
    if _STRONG_NAME.search(name):
        return True
    return bool(_SECRET_SHAPE.match(value)) and any(c.isdigit() for c in value) and any(c.islower() for c in value)


VALIDATORS = {"assigned credential": _credential_value}

# A pattern whose match is the same for every secret it finds (the PEM header names a key, it does not contain it) can
# never be allowlisted: one entry would hide every private key in the repository.
NEVER_ALLOWLISTED = frozenset({"private key block"})

# Reviewed false positives: fingerprint -> (the paths it is allowed at, the reason). An entry covers only those paths,
# so the same text appearing anywhere else is still a finding. Reviewed 2026-10-08 on the full history: every one is
# a synthetic test value.
ALLOWED: dict[str, tuple[tuple[str, ...], str]] = {
    "cc098da74801bb82": (("tests/fixtures/odds_api/nfl_planner_golden_b944a0e.json",),
                         "the fake key 'FAKEpilotKEY...' in an Odds API planner fixture"),
    "1a66c2b90e67f285": (("tests/test_deploy_units.py",), "synthetic ntfy topic for the topic-writer tests"),
    "aa9e603bd77239c3": (("tests/test_deploy_units.py",), "synthetic ntfy topic for the topic-writer tests"),
    "2ac30f92c65eb94a": (("tests/test_notify_ntfy.py",), "synthetic topic 'short-secret'"),
    "4e5dd698fa7f4526": (("tests/test_notify_ntfy.py",), "synthetic topic 'another-topic-...'"),
    "bbce05474792c8fa": (("tests/test_notify_ntfy.py",), "synthetic topic 'another-topic-...'"),
    "f72800b4f3256efb": (("tests/test_freshness_fabric.py",), "synthetic topic 'SECRET-TOPIC-abcdef'"),
    "8e09bbb98b518075": (("tests/invariants/test_no_execution_paths.py",),
                         "history only: sample topic for parse_topic_url"),
    "786a7680c76b6130": (("tests/test_redaction.py",), "synthetic signature sample the redaction tests redact"),
    "f15f811d2afb97e7": (("tests/test_redaction.py",), "synthetic key-id sample the redaction tests redact"),
    "4e3abb493b8bb9f0": (("tests/test_secret_scan.py",),
                         "this scanner's own 'assigned secret' sample, assembled from string pieces at run time"),
}

LIMITATIONS = (
    "finds credential shapes and credential-named assignments only; not detected: a bare key id (a UUID) or bare "
    "32-hex key with no credential-like name beside it, a value under 8 characters, a KEY/TOKEN/TOPIC value under 16 "
    "characters or without both a letter and a digit (for example an all-letter ntfy topic), an unquoted lower-case "
    "identifier-like value (read as a reference), a secret split across lines, and a secret in an encoded or "
    "compressed form",
    f"binary blobs and blobs over {MAX_BLOB_BYTES} bytes are counted and skipped",
    "--history covers refs present in this clone (git rev-list --all)",
)


class ScanError(RuntimeError):
    """The scan could not run. Never reported as clean."""


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:FINGERPRINT_CHARS]


def scan_text(text: str, where: dict) -> Iterator[dict]:
    """Findings in `text` (location fields from `where`). The matched value is never included."""
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                if label in VALIDATORS and not VALIDATORS[label](match):
                    continue
                yield {**where, "line": number, "pattern": label, "fingerprint": fingerprint(match.group(0))}


def allowlisted(finding: dict) -> bool:
    """A finding is allowlisted only by an entry for its fingerprint that names its path, never for a pattern in
    `NEVER_ALLOWLISTED`. A commit-message finding has no path, so it is never allowlisted."""
    entry = ALLOWED.get(finding["fingerprint"])
    return (entry is not None and finding["pattern"] not in NEVER_ALLOWLISTED
            and finding.get("path") in entry[0])


def _decode(data: bytes) -> str | None:
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False)
    except OSError as exc:
        raise ScanError(f"git is not available: {exc}") from exc
    if done.returncode != 0:
        raise ScanError(f"git {args[0]} failed: {done.stderr.decode(errors='replace').strip()[:200]}")
    return done.stdout


class _Totals:
    def __init__(self) -> None:
        self.scanned = 0
        self.skipped_binary = 0
        self.skipped_large = 0


def _scan_blob(data: bytes, where: dict, totals: _Totals) -> list[dict]:
    if len(data) > MAX_BLOB_BYTES:
        totals.skipped_large += 1
        return []
    text = _decode(data)
    if text is None:
        totals.skipped_binary += 1
        return []
    totals.scanned += 1
    return list(scan_text(text, where))


def scan_tree(root: Path) -> tuple[list[dict], dict]:
    totals = _Totals()
    findings: list[dict] = []
    for rel in _git(root, "ls-files", "-z").decode("utf-8", errors="surrogateescape").split("\0"):
        path = root / rel
        if not rel or not path.is_file() or path.is_symlink():
            continue
        findings += _scan_blob(path.read_bytes(), {"path": rel}, totals)
    return findings, {"files_scanned": totals.scanned, "skipped_binary": totals.skipped_binary,
                      "skipped_large": totals.skipped_large}


def _blob_paths(root: Path, rev: str) -> dict[str, str]:
    """Every object reachable from `rev`, with the first path it was seen under; trees and commits included."""
    out: dict[str, str] = {}
    for line in _git(root, "rev-list", rev, "--objects").decode("utf-8", errors="surrogateescape").splitlines():
        sha, _, path = line.partition(" ")
        out.setdefault(sha, path)
    return out


def _cat_batch(root: Path, shas: Iterable[str]) -> Iterator[tuple[str, str, bytes | None]]:
    """(sha, type, content) for each object; content is None when the object is over the size bound."""
    shas = list(shas)
    if not shas:
        return
    checks = _git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                  stdin=("\n".join(shas) + "\n").encode()).decode().splitlines()
    wanted, large = [], []
    for line in checks:
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob":
            (large if int(parts[2]) > MAX_BLOB_BYTES else wanted).append(parts[0])
    for sha in large:
        yield sha, "blob", None
    if not wanted:
        return
    raw = _git(root, "cat-file", "--batch", stdin=("\n".join(wanted) + "\n").encode())
    pos = 0
    while pos < len(raw):
        header_end = raw.index(b"\n", pos)
        sha, kind, size = raw[pos:header_end].decode().split()
        start = header_end + 1
        yield sha, kind, raw[start:start + int(size)]
        pos = start + int(size) + 1


def scan_history(root: Path, rev: str = "--all") -> tuple[list[dict], dict]:
    """Every blob and commit message reachable from `rev` ("--all": every ref in this clone)."""
    if rev != "--all" and (not rev or rev.startswith("-")):
        raise ScanError(f"--rev must be a revision or --all, not {rev!r}")
    totals = _Totals()
    findings: list[dict] = []
    objects = _blob_paths(root, rev)
    for sha, kind, data in _cat_batch(root, objects):
        if kind != "blob":
            continue
        if data is None:
            totals.skipped_large += 1
            continue
        findings += _scan_blob(data, {"path": objects.get(sha, ""), "blob": sha}, totals)
    log = _git(root, "log", rev, "--format=%H%x00%B%x00%x01").decode("utf-8", errors="replace")
    messages = 0
    for record in log.split("\x01"):
        sha, _, body = record.strip("\n").partition("\x00")
        if not sha:
            continue
        messages += 1
        findings += list(scan_text(body, {"commit_message": sha.strip()}))
    commits = int(_git(root, "rev-list", rev, "--count").decode().strip() or 0)
    refs = len(_git(root, "for-each-ref", "--format=%(refname)").decode().splitlines())
    return findings, {"rev": rev, "commits": commits, "refs": refs, "commit_messages_scanned": messages,
                      "blobs_scanned": totals.scanned, "skipped_binary": totals.skipped_binary,
                      "skipped_large": totals.skipped_large}


def scan_paths(paths: Iterable[Path]) -> tuple[list[dict], dict]:
    totals = _Totals()
    findings: list[dict] = []
    missing = []
    for base in paths:
        if not base.exists():
            missing.append(str(base))
            continue
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink())
        for path in files:
            findings += _scan_blob(path.read_bytes(), {"path": str(path)}, totals)
    if missing:
        raise ScanError(f"paths not found: {missing}")
    return findings, {"files_scanned": totals.scanned, "skipped_binary": totals.skipped_binary,
                      "skipped_large": totals.skipped_large}


def run(argv: list[str] | None = None) -> tuple[int, dict]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--history", action="store_true")
    mode.add_argument("--tree", action="store_true")
    mode.add_argument("--paths", nargs="+", type=Path)
    parser.add_argument("--rev", default="--all", help="with --history: one revision instead of every ref")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.history:
            name, (found, totals) = "history", scan_history(args.repo, args.rev)
        elif args.tree:
            name, (found, totals) = "tree", scan_tree(args.repo)
        else:
            name, (found, totals) = "paths", scan_paths(args.paths)
    except ScanError as exc:
        return 2, {"mode": None, "clean": False, "error": str(exc)}
    allowed = [f for f in found if allowlisted(f)]
    findings = [f for f in found if not allowlisted(f)]
    result = {"mode": name, "clean": not findings, "findings": findings, "allowlisted": len(allowed),
              "patterns": sorted(PATTERNS), "limitations": list(LIMITATIONS), **totals}
    return (1 if findings else 0), result


def main(argv: list[str] | None = None) -> int:
    code, result = run(argv)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
