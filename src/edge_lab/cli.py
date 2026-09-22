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

from . import experiments
from .freshness import Freshness, assess
from .http import HttpFetchError
from .kalshi import collect_series
from .nws import DEFAULT_LAT, DEFAULT_LON, collect_reference_forecast
from .sources import REGISTRY, SourceStatus, get_source
from .storage import SnapshotStore, utc_now_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-lab",
        description="Read-only market-edge research collector.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect one immutable data snapshot.")
    collect.add_argument("--source", choices=("all", "kalshi", "nws"), default="all")
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

    exps = subparsers.add_parser("experiments", help="Experiment registry tools.")
    exps_sub = exps.add_subparsers(dest="experiments_command", required=True)
    validate = exps_sub.add_parser("validate", help="Validate experiments/*/experiment.toml.")
    validate.add_argument("--root", default="experiments")

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
    counts: dict[str, int] | None = None

    try:
        counts = collect(anomalies)
    except Exception as exc:  # noqa: BLE001 - isolation boundary; error is recorded
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, HttpFetchError):
            http_errors = 1

    records, payload_bytes, retries = store.run_source_totals(run_id, spec.legacy_name)
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
    if args.source in {"all", "nws"} and not args.nws_user_agent:
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


def health_report(store: SnapshotStore, *, now: datetime) -> list[dict[str, object]]:
    latest = {row["source_id"]: row for row in store.latest_source_health()}
    report: list[dict[str, object]] = []
    for spec in REGISTRY.values():
        if spec.status is not SourceStatus.ACTIVE:
            continue
        row = latest.get(spec.source_id)
        fetched = store.latest_fetch_by_kind(spec.legacy_name)
        kinds = {
            kind: assess(fetched.get(kind), max_age=max_age, now=now).value
            for kind, max_age in spec.max_age.items()
        }
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
    report = health_report(store, now=datetime.now(timezone.utc))
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
    return 0 if all_fresh else 1


def _experiments(args: argparse.Namespace) -> int:
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
    args = build_parser().parse_args(argv)

    if args.command == "collect":
        return _collect(args)
    if args.command == "recent":
        return _recent(args)
    if args.command == "health":
        return _health(args)
    if args.command == "experiments":
        return _experiments(args)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
