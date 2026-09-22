from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from .kalshi import collect_series
from .nws import DEFAULT_LAT, DEFAULT_LON, collect_reference_forecast
from .storage import SnapshotStore


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

    return parser


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

    try:
        if args.source in {"all", "kalshi"}:
            result["kalshi"] = collect_series(
                store,
                run_id=run_id,
                series_ticker=args.series,
                status=args.market_status,
                depth=args.depth,
            )

        if args.source in {"all", "nws"}:
            result["nws"] = collect_reference_forecast(
                store,
                run_id=run_id,
                user_agent=args.nws_user_agent,
                lat=args.lat,
                lon=args.lon,
            )

        store.finish_run(run_id, status="succeeded")
    except Exception as exc:
        store.finish_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _recent(args: argparse.Namespace) -> int:
    store = SnapshotStore(Path(args.db))
    for row in store.recent_snapshots(limit=args.limit):
        print(
            f"{row['id']:>6}  {row['fetched_at_utc']}  "
            f"{row['source']:<7} {row['kind']:<16} {row['entity_id']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "collect":
        return _collect(args)
    if args.command == "recent":
        return _recent(args)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
