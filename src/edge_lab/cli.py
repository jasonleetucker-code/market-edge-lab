from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import experiments, forward
from .freshness import Freshness, assess
from .http import HttpFetchError, ResponseDecodeError
from .kalshi import collect_series, collect_settlement_evidence
from .nws import DEFAULT_LAT, DEFAULT_LON, collect_reference_forecast
from .nws_cli import collect_cli_archive, collect_recent_cli
from .sources import HEALTH_PROFILES, REGISTRY, SourceStatus, get_source
from .storage import SnapshotStore, utc_now_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-lab",
        description="Read-only market-edge research collector.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect one immutable data snapshot.")
    collect.add_argument("--source", choices=("all", "kalshi", "nws", "nws_cli"), default="all")
    collect.add_argument("--db", default="data/edge_lab.sqlite3")
    collect.add_argument("--series", default="KXHIGHNY")
    collect.add_argument("--market-status", default="open")
    collect.add_argument("--depth", type=int, default=100)
    collect.add_argument("--lat", type=float, default=DEFAULT_LAT)
    collect.add_argument("--lon", type=float, default=DEFAULT_LON)
    collect.add_argument("--nws-user-agent", default=os.getenv("NWS_USER_AGENT"))

    recent = subparsers.add_parser("recent", help="List recent snapshot metadata.")
    recent.add_argument("--db", default="data/edge_lab.sqlite3")
    recent.add_argument("--limit", type=int, default=20)

    health = subparsers.add_parser("health", help="Show latest per-source health and freshness.")
    health.add_argument("--db", default="data/edge_lab.sqlite3")
    health.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    health.add_argument(
        "--profile", choices=(*HEALTH_PROFILES, "all"), default="routine",
        help=(
            "Which collection job to judge (issue #16). routine (default): the sources "
            "`collect --source all` runs; settlement: `settlement collect`; forward: the "
            "EXP-001 Stage-B schedule (cadence-aware, via `forward status`); all: every "
            "active source against its max_age."
        ),
    )
    health.add_argument(
        "--source", action="append", dest="sources",
        help="Only report these active source ids (repeatable); overrides --profile.",
    )

    fwd = subparsers.add_parser(
        "forward", help="EXP-001 forward Stage-B collection (read-only; ADR 0012)."
    )
    fwd_sub = fwd.add_subparsers(dest="forward_command", required=True)
    f_capture = fwd_sub.add_parser(
        "capture", help="Run one capture phase; it refuses to run outside its own window."
    )
    f_capture.add_argument("--phase", choices=("pfm", "decision", "recheck"), required=True)
    f_capture.add_argument("--db", default="data/edge_lab.sqlite3")
    f_capture.add_argument("--nws-user-agent", default=os.getenv("NWS_USER_AGENT"))
    f_capture.add_argument("--lock-timeout", type=float, default=60.0)
    f_status = fwd_sub.add_parser(
        "status", help="Validity of the last closed Stage-B day (exit 1 unless VALID)."
    )
    f_status.add_argument("--db", default="data/edge_lab.sqlite3")
    f_status.add_argument("--date", help="YYYY-MM-DD target date D (default: last closed day)")
    f_status.add_argument("--status-file", help="Also write the non-sensitive summary JSON here.")
    f_opps = fwd_sub.add_parser(
        "opportunities",
        help="Gate 5: every (bracket, side) opportunity for target date D from stored evidence "
             "(qualified and rejected, with reasons). Read-only; never trades.",
    )
    f_opps.add_argument("--db", default="data/edge_lab.sqlite3")
    f_opps.add_argument("--date", required=True, help="YYYY-MM-DD target date D")
    f_opps.add_argument("--out", help="Also write the JSON report here.")

    shadow = subparsers.add_parser(
        "shadow", help="Gate 6: EXP-001 shadow ledger (simulation only; never sends orders)."
    )
    shadow_sub = shadow.add_subparsers(dest="shadow_command", required=True)
    sh_run = shadow_sub.add_parser("run", help="Record decisions and simulated fills for target date D.")
    sh_run.add_argument("--db", default="data/edge_lab.sqlite3")
    sh_run.add_argument("--ledger", default="data/shadow_ledger.sqlite3")
    sh_run.add_argument("--date", required=True, help="YYYY-MM-DD target date D")
    sh_settle = shadow_sub.add_parser("settle", help="Settle open positions from captured settlement evidence.")
    sh_settle.add_argument("--db", default="data/edge_lab.sqlite3")
    sh_settle.add_argument("--ledger", default="data/shadow_ledger.sqlite3")
    sh_account = shadow_sub.add_parser("account", help="Replay the shadow account from its ledger.")
    sh_account.add_argument("--ledger", default="data/shadow_ledger.sqlite3")
    sh_account.add_argument("--account", default=None, help="account id (default: the operational account)")
    sh_daily = shadow_sub.add_parser(
        "daily", help="Daily orchestration: evaluate closed capture days, simulate fills, settle, report."
    )
    sh_daily.add_argument("--db", default="data/edge_lab.sqlite3")
    sh_daily.add_argument("--ledger", default="data/shadow_ledger.sqlite3")
    sh_daily.add_argument("--status-dir", help="write the receipt (shadow_daily.json) here")
    sh_daily.add_argument("--refresh-settlements", action="store_true",
                          help="first fetch official settlement evidence for pending events (bounded GETs)")
    sh_daily.add_argument("--max-events", type=int, default=10)
    sh_daily.add_argument("--deadline-s", type=float, default=120.0)
    sh_daily.add_argument("--lock-timeout", type=float, default=60.0)
    sh_risk = shadow_sub.add_parser(
        "risk", help="Risk/capital report, withdrawal contract and Outcome Board for the shadow account."
    )
    sh_risk.add_argument("--ledger", default="data/shadow_ledger.sqlite3")
    sh_risk.add_argument("--as-of", help="ISO-8601 instant with zone (default: now)")
    sh_risk.add_argument("--account", default=None, help="account id (default: the operational account)")

    subparsers.add_parser(
        "dashboard", help="Local read-only dashboard (127.0.0.1 by default; see docs/DASHBOARD.md).",
        add_help=False,
    )

    settle = subparsers.add_parser("settlement", help="Gate 2 settlement evidence and audit.")
    settle_sub = settle.add_subparsers(dest="settlement_command", required=True)
    s_collect = settle_sub.add_parser(
        "collect", help="Capture settlement evidence: series rules, settled markets, contracts."
    )
    s_collect.add_argument("--db", default="data/edge_lab.sqlite3")
    s_collect.add_argument("--series", default="KXHIGHNY")
    s_collect.add_argument("--no-historical", action="store_true")
    s_collect.add_argument("--cli-archive-from", help="YYYY-MM-DD: also store IEM CLI archive")
    s_collect.add_argument("--cli-archive-to", help="YYYY-MM-DD (exclusive)")
    s_collect.add_argument("--user-agent", default=os.getenv("NWS_USER_AGENT"))
    s_audit = settle_sub.add_parser("audit", help="Reproduce settlements from stored evidence.")
    s_audit.add_argument("--db", default="data/edge_lab.sqlite3")
    s_audit.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    s_audit.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD (inclusive)")
    s_audit.add_argument("--csv", help="Write bracket-level audit rows to this path.")

    exps = subparsers.add_parser("experiments", help="Experiment registry tools.")
    exps_sub = exps.add_subparsers(dest="experiments_command", required=True)
    validate = exps_sub.add_parser("validate", help="Validate experiments/*/experiment.toml.")
    validate.add_argument("--root", default="experiments")
    freeze_cmd = exps_sub.add_parser(
        "freeze", help="Write the one-time preregistration baseline for a PREREGISTERED manifest."
    )
    freeze_cmd.add_argument("experiment_id")
    freeze_cmd.add_argument("--root", default="experiments")
    frozen = exps_sub.add_parser(
        "check-frozen", help="Fail if any committed preregistration baseline was modified/deleted."
    )
    frozen.add_argument("--base", required=True, help="git ref to compare against, e.g. origin/main")

    return parser


def _run_source(
    store: SnapshotStore,
    *,
    run_id: str,
    source_id: str,
    collect: Callable[[list[str]], dict[str, int]],
) -> dict[str, object]:
    """Run one source in isolation and record its health.

    A failing source never aborts other sources. Status is derived from what
    was actually stored, not from what the collector reports:
    - ok:      no error, no anomalies
    - partial: some records stored, but an error or anomaly occurred
    - failed:  error and nothing stored
    """
    spec = get_source(source_id)
    anomalies: list[str] = []
    started_at = utc_now_iso()
    started = time.monotonic()
    error: str | None = None
    http_errors = 0
    failed_fetch_retries = 0
    counts: dict[str, int] | None = None

    try:
        counts = collect(anomalies)
    except Exception as exc:  # noqa: BLE001 - isolation boundary; error is recorded
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, HttpFetchError):
            # Retries spent on the fetch that ultimately failed are not in any
            # stored snapshot, so count them here.
            failed_fetch_retries = max(exc.attempts - 1, 0)
            if not isinstance(exc, ResponseDecodeError):
                http_errors = 1

    records, payload_bytes, retries = store.run_source_totals(run_id, spec.legacy_name, spec.source_id)
    retries += failed_fetch_retries
    if error is not None:
        status = "partial" if records else "failed"
    elif anomalies:
        status = "partial"
    else:
        status = "ok"

    store.record_source_health(
        run_id=run_id,
        source_id=source_id,
        started_at_utc=started_at,
        completed_at_utc=utc_now_iso(),
        duration_ms=int((time.monotonic() - started) * 1000),
        status=status,
        # A failure never claims records (enforced by the schema as well).
        records=records if status != "failed" else 0,
        payload_bytes=payload_bytes,
        http_errors=http_errors,
        retries=retries,
        anomalies=anomalies,
        error=error,
    )
    return {"status": status, "counts": counts, "anomalies": anomalies, "error": error}


def _collect(args: argparse.Namespace) -> int:
    if args.source in {"all", "nws", "nws_cli"} and not args.nws_user_agent:
        print(
            "NWS_USER_AGENT is required for NWS collection. "
            "Set the environment variable or pass --nws-user-agent.",
            file=sys.stderr,
        )
        return 2

    store = SnapshotStore(Path(args.db))
    run_id = str(uuid.uuid4())
    store.start_run(run_id)

    result: dict[str, object] = {"run_id": run_id, "db": str(args.db)}
    outcomes: dict[str, dict[str, object]] = {}
    finished = False
    try:
        if args.source in {"all", "kalshi"}:
            outcomes["kalshi_public"] = _run_source(
                store,
                run_id=run_id,
                source_id="kalshi_public",
                collect=lambda anomalies: collect_series(
                    store,
                    run_id=run_id,
                    series_ticker=args.series,
                    status=args.market_status,
                    depth=args.depth,
                    anomalies=anomalies,
                ),
            )

        if args.source in {"all", "nws"}:
            outcomes["nws_api"] = _run_source(
                store,
                run_id=run_id,
                source_id="nws_api",
                collect=lambda _anomalies: collect_reference_forecast(
                    store,
                    run_id=run_id,
                    user_agent=args.nws_user_agent,
                    lat=args.lat,
                    lon=args.lon,
                ),
            )

        if args.source in {"all", "nws_cli"}:
            outcomes["nws_cli_central_park"] = _run_source(
                store,
                run_id=run_id,
                source_id="nws_cli_central_park",
                collect=lambda anomalies: collect_recent_cli(
                    store, run_id=run_id, user_agent=args.nws_user_agent, anomalies=anomalies
                ),
            )

        statuses = {outcome["status"] for outcome in outcomes.values()}
        if statuses == {"ok"}:
            run_status, run_error = "succeeded", None
        elif statuses == {"failed"}:
            run_status, run_error = "failed", "all sources failed"
        else:
            run_status = "partial"
            run_error = "; ".join(
                f"{sid}: {o['status']}" for sid, o in outcomes.items() if o["status"] != "ok"
            )
        store.finish_run(run_id, status=run_status, error=run_error)
        finished = True
    finally:
        if not finished:
            # Never leave a run looking like it is still in progress.
            store.finish_run(run_id, status="failed", error="collection aborted before completion")

    result["status"] = run_status
    result["sources"] = outcomes
    print(json.dumps(result, indent=2, sort_keys=True))
    # Non-zero whenever evidence is missing, so schedulers notice.
    return 0 if run_status == "succeeded" else 1


def _recent(args: argparse.Namespace) -> int:
    store = SnapshotStore(Path(args.db))
    for row in store.recent_snapshots(limit=args.limit):
        print(
            f"{row['id']:>6}  {row['fetched_at_utc']}  "
            f"{row['source']:<7} {row['kind']:<16} {row['entity_id']}"
        )
    return 0


def health_report(
    store: SnapshotStore, *, now: datetime, profile: str = "all"
) -> list[dict[str, object]]:
    """Per-source health for the active sources a profile owns ("all" = every one)."""
    latest = {row["source_id"]: row for row in store.latest_source_health()}
    report: list[dict[str, object]] = []
    for spec in REGISTRY.values():
        if spec.status is not SourceStatus.ACTIVE:
            continue
        if profile != "all" and profile not in spec.collected_by:
            continue
        row = latest.get(spec.source_id)
        fetched = store.latest_fetch_by_kind(spec.legacy_name)
        # "Latest receipt of any entity of this kind". It does not guarantee
        # that every entity of the kind is fresh; decision code must check its
        # own inputs with require_fresh.
        kinds = {
            kind: assess(fetched.get(kind), max_age=max_age, now=now).value
            for kind, max_age in spec.max_age.items()
        }
        for kind in fetched:
            kinds.setdefault(kind, Freshness.UNKNOWN.value)  # collected, no max age
        report.append(
            {
                "source_id": spec.source_id,
                "last_status": row["status"] if row else None,
                "last_run_id": row["run_id"] if row else None,
                "last_completed_at_utc": row["completed_at_utc"] if row else None,
                "last_ok_at_utc": row["last_ok_at_utc"] if row else None,
                "last_error": row["error"] if row else None,
                "anomalies": json.loads(row["anomalies_json"]) if row else [],
                # Freshness is judged per kind on receipt time; a kind never
                # collected is unknown, not fresh.
                "freshness": kinds,
            }
        )
    return report


def _health(args: argparse.Namespace) -> int:
    store = SnapshotStore(Path(args.db))
    now = datetime.now(timezone.utc)
    if args.profile == "forward" and not args.sources:
        # Scheduled once a day, so per-kind max_age (minutes for order books) says nothing
        # useful between runs. Judge the schedule instead: was the last closed day VALID?
        status = forward.summary(store, now_utc=now)
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if status["last_closed_status"] == "VALID" else 1
    report = health_report(store, now=now, profile="all" if args.sources else args.profile)
    if args.sources:
        unknown = set(args.sources) - {item["source_id"] for item in report}
        if unknown:
            print(f"unknown or inactive source(s): {sorted(unknown)}", file=sys.stderr)
            return 2
        report = [item for item in report if item["source_id"] in args.sources]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in report:
            fresh = ", ".join(f"{k}={v}" for k, v in item["freshness"].items())
            print(
                f"{item['source_id']:<16} last={item['last_status'] or 'never':<8} "
                f"last_ok={item['last_ok_at_utc'] or '-'}"
            )
            print(f"  freshness: {fresh}")
            if item["last_error"]:
                print(f"  error: {item['last_error']}")
            for anomaly in item["anomalies"]:
                print(f"  anomaly: {anomaly}")
    all_fresh = all(
        state == Freshness.FRESH.value for item in report for state in item["freshness"].values()
    )
    # A source whose latest run was not clean (or that never ran) is unhealthy even
    # if older snapshots are still inside their freshness window.
    all_ok = all(item["last_status"] == "ok" for item in report)
    return 0 if all_fresh and all_ok else 1


def _forward_capture(args: argparse.Namespace) -> int:
    if args.phase == "pfm" and not args.nws_user_agent:
        print("NWS_USER_AGENT is required for the pfm phase.", file=sys.stderr)
        return 2
    import signal

    def _terminate(signum, _frame):  # systemd stop / RuntimeMaxSec: finish the run as failed
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _terminate)
    db = Path(args.db)
    store = SnapshotStore(db)
    run_id = str(uuid.uuid4())
    # Only the pfm phase writes source health (nws_pfm_okx is a forward-only source). The
    # Kalshi phases are judged by their forward_captures rows, so a forward run never
    # changes the routine profile's view of kalshi_public (issue #16).
    capture = {
        "pfm": lambda anomalies: forward.capture_pfm(
            store, run_id=run_id, user_agent=args.nws_user_agent, anomalies=anomalies
        ),
        "decision": lambda anomalies: forward.capture_decision(store, run_id=run_id, anomalies=anomalies),
        "recheck": lambda anomalies: forward.capture_recheck(store, run_id=run_id, anomalies=anomalies),
    }[args.phase]
    outcome: forward.CaptureOutcome | None = None
    try:
        with forward.exclusive_lock(db.with_name(db.name + ".forward.lock"), timeout_s=args.lock_timeout):
            store.start_run(run_id)
            finished = False
            try:
                if args.phase == "pfm" and forward.would_proceed(args.phase, store, datetime.now(timezone.utc)):

                    def collect(anomalies: list[str]) -> dict[str, int]:
                        nonlocal outcome
                        outcome = capture(anomalies)
                        return {"records": outcome.records}

                    health = _run_source(store, run_id=run_id, source_id="nws_pfm_okx", collect=collect)
                    if outcome is None:
                        raise RuntimeError(health["error"] or "capture did not complete")
                else:
                    # Kalshi phases, or a rejected/duplicate pfm run (recorded without any
                    # network work, so no source-health row claims the source was used).
                    outcome = capture([])
                run_status = (
                    "succeeded" if outcome.status in ("complete", "skipped_duplicate")
                    else "partial" if outcome.status == "partial" else "failed"
                )
                error = None if run_status == "succeeded" else f"{outcome.status}: {'; '.join(outcome.reasons[:3])}"
                store.finish_run(run_id, status=run_status, error=error)
                finished = True
            finally:
                if not finished:
                    store.finish_run(run_id, status="failed", error="forward capture aborted before completion")
    except forward.LockBusy as exc:
        print(json.dumps({"phase": args.phase, "status": "lock_busy", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"run_id": run_id, **outcome.as_dict()}, indent=2, sort_keys=True))
    return outcome.exit_code


def _forward_status(args: argparse.Namespace) -> int:
    from datetime import date

    store = SnapshotStore(Path(args.db))
    now = datetime.now(timezone.utc)
    if args.date:
        result = forward.day_status(store, date.fromisoformat(args.date))
        ok = result["status"] == "VALID"
    else:
        result = forward.summary(store, now_utc=now)
        ok = result["last_closed_status"] == "VALID"
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.status_file:
        target = Path(args.status_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, target)
    print(text, end="")
    return 0 if ok else 1


def _forward_opportunities(args: argparse.Namespace) -> int:
    """Exit 0 when the report was produced (whatever it says), 2 on bad input."""
    from datetime import date

    from . import exp001_stageb

    db = Path(args.db)
    if not db.is_file():
        print(f"no database at {db}", file=sys.stderr)
        return 2
    try:
        target = date.fromisoformat(args.date)
    except ValueError:
        print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    report = exp001_stageb.evaluate_day(SnapshotStore(db), target).to_dict()
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


def _shadow(args: argparse.Namespace) -> int:
    """Exit 0 when the command ran, 2 on bad input. Simulation only."""
    from datetime import date

    from . import exp001_shadow
    from .shadow_ledger import ShadowLedger

    from . import forward
    from .shadow_ledger import LedgerError
    from .storage import ReadOnlyStoreError

    ledger_path = Path(args.ledger)
    if args.shadow_command == "daily":
        import signal

        from . import daily

        def _terminate(signum, frame):  # systemd stop/timeout: raise so a FAILED receipt is written
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, _terminate)

        receipt, code = daily.run(Path(args.db), ledger_path,
                                  status_dir=Path(args.status_dir) if args.status_dir else None,
                                  refresh_settlements=args.refresh_settlements, max_events=args.max_events,
                                  deadline_s=args.deadline_s, lock_timeout_s=args.lock_timeout,
                                  code_version=os.getenv("EDGE_LAB_CODE_VERSION"))
        print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    if args.shadow_command in ("account", "risk"):
        if not ledger_path.is_file():
            print(f"no ledger at {ledger_path}", file=sys.stderr)
            return 2
        account_id = args.account or exp001_shadow.ACCOUNT_ID
        ledger = ShadowLedger.open_readonly(ledger_path)
        if account_id not in ledger.accounts():
            print(f"no account {account_id!r} in {ledger_path}", file=sys.stderr)
            return 2
        state = ledger.state(account_id)
        if args.shadow_command == "account":
            result = state.to_dict()
        else:
            from . import outcome_board, risk
            from .fee_schedules import recorded_claim_basis
            from .freshness import parse_utc

            as_of = parse_utc(args.as_of) if args.as_of else datetime.now(timezone.utc)
            if as_of is None:
                print(f"--as-of must be an ISO-8601 instant with a zone, got {args.as_of!r}", file=sys.stderr)
                return 2
            try:
                report = risk.assess(state, exp001_shadow.RISK_POLICY, as_of)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            result = {
                "risk": report.to_dict(),
                "withdrawal": risk.withdrawal_assessment(
                    state, report, fee_claim_basis=recorded_claim_basis(
                        json.loads(r["payload_json"]) for r in ledger.entries(account_id) if r["kind"] == "fill"
                    ).value).to_dict(),
                "outcome_board": [g.to_dict() for g in outcome_board.build_board(state, as_of)],
            }
    else:
        db = Path(args.db)
        if not db.is_file():
            print(f"no database at {db}", file=sys.stderr)
            return 2
        try:
            store = SnapshotStore.open_readonly(db)  # analysis never creates or migrates evidence
        except ReadOnlyStoreError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.shadow_command == "run":
            try:
                target = date.fromisoformat(args.date)
            except ValueError:
                print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
                return 2
        try:
            with forward.exclusive_lock(ledger_path.with_name(ledger_path.name + ".lock"), timeout_s=60):
                ledger = ShadowLedger(ledger_path)
                if args.shadow_command == "settle":
                    from . import daily

                    # Same cap as the daily run: never settle past an unprocessed closed day.
                    result = exp001_shadow.settle_open_positions(
                        store, ledger, known_by=daily.settlement_cutoff(store, ledger, datetime.now(timezone.utc)))
                else:
                    result = exp001_shadow.run_day(store, ledger, target)
        except forward.LockBusy as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except LedgerError as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _settlement_collect(args: argparse.Namespace) -> int:
    from datetime import date

    if bool(args.cli_archive_from) != bool(args.cli_archive_to):
        print("--cli-archive-from and --cli-archive-to go together", file=sys.stderr)
        return 2
    if args.cli_archive_from and not args.user_agent:
        print("An identifying --user-agent (or NWS_USER_AGENT) is required", file=sys.stderr)
        return 2
    store = SnapshotStore(Path(args.db))
    run_id = str(uuid.uuid4())
    store.start_run(run_id)
    outcomes: dict[str, dict[str, object]] = {}
    finished = False
    try:
        outcomes["kalshi_settlement"] = _run_source(
            store,
            run_id=run_id,
            source_id="kalshi_settlement",
            collect=lambda anomalies: collect_settlement_evidence(
                store,
                run_id=run_id,
                series_ticker=args.series,
                include_historical=not args.no_historical,
                anomalies=anomalies,
            ),
        )
        if args.cli_archive_from:
            outcomes["iem_afos_clinyc"] = _run_source(
                store,
                run_id=run_id,
                source_id="iem_afos_clinyc",
                collect=lambda anomalies: collect_cli_archive(
                    store,
                    run_id=run_id,
                    start=date.fromisoformat(args.cli_archive_from),
                    end_exclusive=date.fromisoformat(args.cli_archive_to),
                    user_agent=args.user_agent,
                    anomalies=anomalies,
                ),
            )
        statuses = {o["status"] for o in outcomes.values()}
        run_status = "succeeded" if statuses == {"ok"} else ("failed" if statuses == {"failed"} else "partial")
        store.finish_run(run_id, status=run_status, error=None if run_status == "succeeded" else "see source_health")
        finished = True
    finally:
        if not finished:
            store.finish_run(run_id, status="failed", error="collection aborted before completion")
    print(json.dumps({"run_id": run_id, "status": run_status, "sources": outcomes}, indent=2, sort_keys=True))
    return 0 if run_status == "succeeded" else 1


def load_settlement_evidence(store: SnapshotStore) -> tuple[list[dict], list]:
    """All stored settled markets and every parsed CLI report (API products + IEM archives)."""
    from .nws_cli import parse_cli, split_afos_archive

    markets: list[dict] = []
    for kind in ("settled_markets", "historical_markets"):
        for row in store.snapshots_of_kind(source="kalshi_settlement", kind=kind):
            markets.extend(json.loads(row["payload_json"]).get("markets") or [])
    reports = [
        parse_cli(json.loads(row["payload_json"]).get("productText") or "")
        for row in store.snapshots_of_kind(source="nws_cli", kind="cli_product")
    ]
    for sha in store.document_hashes(doc_type="nws_cli_archive_text"):
        body = store.document_bytes(sha) or b""
        reports.extend(parse_cli(p) for p in split_afos_archive(body.decode("utf-8", errors="replace")))
    return markets, reports


def _settlement_audit(args: argparse.Namespace) -> int:
    from datetime import date

    from .settlement_audit import audit, rows_csv, summarize

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    markets, reports = load_settlement_evidence(SnapshotStore(Path(args.db)))
    summaries, rows = audit(markets, reports, start=start, end=end)
    summary = summarize(summaries, start, end)
    if args.csv:
        Path(args.csv).write_text(rows_csv(rows))
    print(json.dumps(summary, indent=2, sort_keys=True))
    wrong = [r for r in rows if r.expected_from_nws_cli != "unknown" and not r.match_nws_cli]
    # Non-zero if any bracket is mis-predicted or any event is unresolved.
    return 0 if not wrong and not summary["unresolved_events"] and summary["events"] else 1


def _experiments(args: argparse.Namespace) -> int:
    if args.experiments_command == "freeze":
        matches = [p for p in experiments.discover(Path(args.root)) if p.parent.name.startswith(args.experiment_id + "-")]
        if len(matches) != 1:
            print(f"expected one manifest for {args.experiment_id}, found {len(matches)}", file=sys.stderr)
            return 2
        try:
            target = experiments.freeze(experiments.load(matches[0]), now_utc=utc_now_iso())
        except (ValueError, FileExistsError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {target}")
        return 0
    if args.experiments_command == "check-frozen":
        changed = experiments.changed_baselines(args.base, repo=Path("."))
        for line in changed:
            print(f"FAIL preregistration baseline modified or deleted: {line}")
        return 1 if changed else 0
    results = experiments.validate_all(Path(args.root))
    if not results:
        print(f"No experiments found under {args.root}", file=sys.stderr)
        return 1
    failed = False
    for path, problems in results.items():
        print(f"{'OK  ' if not problems else 'FAIL'} {path}")
        for problem in problems:
            print(f"     - {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["dashboard"]:  # the dashboard owns its own argument parser
        from .dashboard import main as dashboard_main

        return dashboard_main(argv[1:])
    args = build_parser().parse_args(argv)

    if args.command == "collect":
        return _collect(args)
    if args.command == "recent":
        return _recent(args)
    if args.command == "health":
        return _health(args)
    if args.command == "forward":
        if args.forward_command == "capture":
            return _forward_capture(args)
        if args.forward_command == "opportunities":
            return _forward_opportunities(args)
        return _forward_status(args)
    if args.command == "shadow":
        return _shadow(args)
    if args.command == "settlement":
        if args.settlement_command == "collect":
            return _settlement_collect(args)
        return _settlement_audit(args)
    if args.command == "experiments":
        return _experiments(args)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
