"""Operator commands for the executor host: backups, restore drills, health, release checks (#160 package O, ADR 0048).

`python -m edge_lab.execution.ops <command>`. Offline: no command opens a network connection, reads the environment,
reads a key, arms anything or takes the egress lease. Every path is an explicit argument; the unit files in
`deploy/executor/systemd/` pass the deployed ones. Nothing here is installed, scheduled or enabled by this package.

| Command | Does | Exit |
|---|---|---|
| `backup` | `journal_backup.create_backup` into the private backup root | 0 published, 1 refused or failed |
| `verify-backup` | bytes, schema, chain and identity of one bundle (disposable restore) | 0 / 1 |
| `restore` | restore one bundle to a NEW journal path, never over a `--live` path | 0 / 1 |
| `restore-drill` | restore into a drill directory, verify, report, remove the drill copy unless `--keep` | 0 / 1 |
| `health` | liveness, reconciliation, backup and disk verdicts (`health`) | bit per failing verdict |
| `release-manifest` | write this code's release manifest (never over an existing file) | 0 / 1 |
| `release-check` | the start check: manifest, installed revision and journal schema agree | 0 / 1 |
| `run` | the executor's start: the release check, then a refusal, because no networked runner exists in this package yet (it arrives with the DEMO approval, ADR 0043 decision 7) | 78 |

**Output is sanitized.** Every command prints one JSON object. Every string in it passes `redaction.redact_text`,
and the whole text is checked with `redaction.contains_unredacted_secret` before it is printed; anything still
secret-looking is withheld. Errors are printed as one redacted line (the exception type and its first line), never
a traceback, so a header or key that reached an exception message cannot reach the journal through this command.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

from .. import redaction
from . import health as hl
from . import journal_backup as jb
from . import release as rl
from .journal import JournalError

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERNAL, EXIT_NO_RUNNER = 0, 1, 2, 70, 78
WITHHELD = "OUTPUT_WITHHELD: the result still looked like it held a secret after redaction"


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redaction.redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, Path):
        return redaction.redact_text(str(value))
    return value


def render(result: Mapping[str, Any]) -> str:
    """The one line a command prints: sanitized JSON, or a fixed refusal when redaction was not enough."""
    text = json.dumps(_clean(result), sort_keys=True, separators=(",", ":"), default=str)
    if redaction.contains_unredacted_secret(text):
        return json.dumps({"ok": False, "error": WITHHELD}, sort_keys=True)
    return text


def safe_error(exc: BaseException) -> str:
    first = str(exc).splitlines()[0] if str(exc) else ""
    return redaction.redact_text(f"{type(exc).__name__}: {first[:400]}" if first else type(exc).__name__)


def _emit(result: Mapping[str, Any], out: TextIO) -> None:
    out.write(render(result) + "\n")
    out.flush()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_revision(path: str) -> str | None:
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 128:
        return None
    return p.read_text(encoding="ascii", errors="replace").strip()


def _store_or_none(journal: str | None) -> jb.StoreIdentity | None:
    if journal is None or not Path(journal).exists():
        return None
    return jb.store_identity(journal)


# ------------------------------------------------------------------ commands


def _backup(a: argparse.Namespace) -> tuple[int, dict]:
    record = jb.create_backup(a.journal, a.out, now=_now(), timeout_s=a.timeout_s)
    ident = record.manifest["identity"]
    return EXIT_OK, {"ok": True, "bundle": record.bundle.name, "created_at_utc": record.manifest["created_at_utc"],
                     "database_bytes": record.manifest["database_bytes"], "chain_events": record.manifest["chain_events"],
                     "row_counts": ident["row_counts"], "in_flight_attempts": ident["in_flight_attempts"],
                     "outcome_unknown_attempts": ident["outcome_unknown_attempts"]}


def _verify(a: argparse.Namespace) -> tuple[int, dict]:
    record = jb.verify_bundle(a.bundle)
    return EXIT_OK, {"ok": True, "bundle": Path(a.bundle).name, "verified": True,
                     "chain_events": record.manifest["chain_events"], "created_at_utc": record.manifest["created_at_utc"]}


def _restore(a: argparse.Namespace) -> tuple[int, dict]:
    report = jb.restore_bundle(a.bundle, a.target, live_paths=a.live)
    return EXIT_OK, {"ok": True, **report.to_dict()}


def _drill(a: argparse.Namespace) -> tuple[int, dict]:
    report = jb.restore_drill(a.bundle, a.drill_dir, live_paths=a.live, keep=a.keep)
    return EXIT_OK, {"ok": True, "drill": True, **report.to_dict()}


def _health(a: argparse.Namespace) -> tuple[int, dict]:
    now = _now()
    limits = hl.HealthLimits(max_status_age=timedelta(seconds=a.max_status_age_s),
                             max_cycle_gap=timedelta(seconds=a.max_cycle_gap_s),
                             max_reconciliation_age=timedelta(seconds=a.max_reconciliation_age_s),
                             max_backup_age=timedelta(seconds=a.max_backup_age_s), min_free_bytes=a.min_free_bytes)
    status, problem = hl.load_status(a.status_file)
    newest = jb.newest_complete(a.backup_root)
    anchor: tuple[str, ...] = ()
    if newest is not None and a.journal and Path(a.journal).exists():
        anchor = tuple(jb.extends_backup(a.journal, newest.path))
    try:
        free = int(shutil.disk_usage(a.disk_path).free)
    except OSError:
        free = None
    result = hl.report(status, now=now, limits=limits, newest_backup_utc=None if newest is None else newest.created_at_utc,
                       anchor_problems=anchor, free_bytes=free, status_problem=problem)
    return result["exit_code"], {"ok": result["exit_code"] == 0, **result}


def _manifest(a: argparse.Namespace) -> tuple[int, dict]:
    manifest = rl.build_manifest(a.revision, rollback_revision=a.rollback_revision,
                                 rollback_journal_schema_version=a.rollback_journal_schema)
    out = Path(a.out)
    with out.open("x", encoding="utf-8", newline="\n") as stream:  # never over an existing manifest
        stream.write(rl.render_manifest(manifest))
    return EXIT_OK, {"ok": True, "manifest": out.name, "digest": manifest["digest"],
                     "code_revision": manifest["code_revision"]}


def _check(a: argparse.Namespace) -> tuple[int, dict]:
    manifest = rl.load_manifest(a.manifest)
    problems = rl.release_problems(manifest, installed_revision=_read_revision(a.revision_file),
                                   store=_store_or_none(a.journal))
    return (EXIT_FAILED if problems else EXIT_OK), {"ok": not problems, "problems": problems,
                                                     "code_revision": manifest.get("code_revision"),
                                                     "digest": manifest.get("digest")}


def _run(a: argparse.Namespace) -> tuple[int, dict]:
    code, checked = _check(a)
    if code != EXIT_OK:
        return code, {**checked, "started": False}
    return EXIT_NO_RUNNER, {"ok": False, "started": False, "problems": [
        "NO_RUNNER: this package has no networked executor runner yet; it arrives with the DEMO approval "
        "(ADR 0043 decision 7). Nothing was opened, armed or sent."]}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m edge_lab.execution.ops", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--journal", required=True)
    b.add_argument("--out", required=True, help="the private journal backup root (exists already)")
    b.add_argument("--timeout-s", type=float, default=jb.DEFAULT_TIMEOUT_S)
    b.set_defaults(func=_backup)
    v = sub.add_parser("verify-backup")
    v.add_argument("--bundle", required=True)
    v.set_defaults(func=_verify)
    for name, func in (("restore", _restore), ("restore-drill", _drill)):
        r = sub.add_parser(name)
        r.add_argument("--bundle", required=True)
        if name == "restore":
            r.add_argument("--target", required=True, help="a NEW journal path; never an existing file")
        else:
            r.add_argument("--drill-dir", required=True)
            r.add_argument("--keep", action="store_true", help="keep the drill copy for inspection")
        r.add_argument("--live", action="append", required=True,
                       help="every live journal path; the restore refuses to write any of them")
        r.set_defaults(func=func)
    h = sub.add_parser("health")
    h.add_argument("--status-file", required=True)
    h.add_argument("--backup-root", required=True)
    h.add_argument("--journal", default=None, help="the live journal, for the backup chain-anchor check")
    h.add_argument("--disk-path", required=True)
    h.add_argument("--max-status-age-s", type=int, default=300)
    h.add_argument("--max-cycle-gap-s", type=int, default=300)
    h.add_argument("--max-reconciliation-age-s", type=int, default=600)
    h.add_argument("--max-backup-age-s", type=int, default=26 * 3600)
    h.add_argument("--min-free-bytes", type=int, default=2 * 1024 ** 3)
    h.set_defaults(func=_health)
    m = sub.add_parser("release-manifest")
    m.add_argument("--revision", required=True)
    m.add_argument("--rollback-revision", default=None)
    m.add_argument("--rollback-journal-schema", type=int, default=None)
    m.add_argument("--out", required=True)
    m.set_defaults(func=_manifest)
    for name, func in (("release-check", _check), ("run", _run)):
        c = sub.add_parser(name)
        c.add_argument("--manifest", required=True)
        c.add_argument("--revision-file", required=True)
        c.add_argument("--journal", default=None, help="the live journal; absent means none exists yet")
        c.set_defaults(func=func)
    return p


_EXPECTED = (jb.BackupError, rl.ReleaseError, JournalError, OSError, ValueError)


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None,
         parse: Callable[[], argparse.ArgumentParser] = _parser) -> int:
    stream = out if out is not None else sys.stdout
    try:
        args = parse().parse_args(argv)
    except SystemExit as exc:  # argparse prints its own usage error; no command takes a secret as an argument
        return EXIT_USAGE if exc.code else EXIT_OK
    try:
        code, result = args.func(args)
    except _EXPECTED as exc:
        code, result = EXIT_FAILED, {"ok": False, "command": args.command, "error": safe_error(exc)}
    except Exception as exc:  # noqa: BLE001 - one redacted line, never a traceback with a secret in it
        code, result = EXIT_INTERNAL, {"ok": False, "command": args.command, "error": safe_error(exc)}
    _emit({"command": args.command, **result}, stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
