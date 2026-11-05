"""`edge-lab intel …`: the owner's and the timers' entry points (#192, ADR 0049).

Every command prints one JSON object. Network: `verify-sources`, `collect`, `discover-markets`,
`refresh-quotes` (bounded; Kalshi refuses protected scopes and windows). Everything else is local.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DB = "data/edge_lab.sqlite3"
DEFAULT_INBOX = "data/intel-inbox"


def _store(db: str):
    from ..storage import SnapshotStore

    return SnapshotStore(db)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edge-lab intel", description="News and transcript intelligence (#192)")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify-sources", help="robots.txt + one GET per collectable feed; records verification")
    v.add_argument("--only", nargs="*")
    c = sub.add_parser("collect", help="one bounded news collection run")
    c.add_argument("--force", action="store_true", help="ignore the 15-minute refresh interval")
    sub.add_parser("status")
    sub.add_parser("events", help="list current events with status")
    t = sub.add_parser("import-transcript")
    t.add_argument("file")
    t.add_argument("--podcast", required=True)
    t.add_argument("--episode", required=True)
    t.add_argument("--date")
    t.add_argument("--url")
    t.add_argument("--source", default="owner file")
    t.add_argument("--notes")
    k = sub.add_parser("packet", help="print the research packet for an event (never contains Kalshi data)")
    k.add_argument("event_id")
    k.add_argument("--horizon", help="your forecast horizon YYYY-MM-DD (default: end of this year)")
    a = sub.add_parser("import-analysis", help="import a pasted assistant reply (file path, or - for stdin)")
    a.add_argument("file")
    a.add_argument("--owner-judgment", action="store_true",
                   help="this is my own judgment, not an assistant's reply (labelled OWNER_JUDGMENT)")
    d = sub.add_parser("discover-markets", help="bounded Kalshi catalog search: CANDIDATES only")
    d.add_argument("event_id")
    l = sub.add_parser("link", help="record your decision on a candidate market")
    l.add_argument("outcome_id")
    l.add_argument("ticker")
    l.add_argument("--status", choices=("CONFIRMED", "REJECTED"), default="CONFIRMED")
    l.add_argument("--rules-read", action="store_true", help="I read the market's captured rules")
    l.add_argument("--yes-matches-outcome", action="store_true", help="the market's YES means this outcome")
    q = sub.add_parser("refresh-quotes", help="read confirmed markets' books and record pricing decisions")
    q.add_argument("--outcome")
    r = sub.add_parser("resolve", help="record an outcome's resolution from an official source")
    r.add_argument("outcome_id")
    r.add_argument("result", choices=("YES", "NO"))
    r.add_argument("--source", required=True)
    sub.add_parser("performance")
    i = sub.add_parser("process-inbox", help="handle dashboard submissions (collector side)")
    i.add_argument("--inbox", default=DEFAULT_INBOX)
    i.add_argument("--status-dir", help="write intel.json heartbeat here")
    n = sub.add_parser("run", help="the 2-hour job: collect news, refresh confirmed quotes, drain the inbox")
    n.add_argument("--inbox", default=DEFAULT_INBOX)
    n.add_argument("--status-dir")
    return p


def write_heartbeat(status_dir: str | None, payload: dict) -> None:
    if not status_dir:
        return
    d = Path(status_dir)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".intel.json.tmp"
    tmp.write_text(json.dumps(payload, sort_keys=True, default=str))
    tmp.replace(d / "intel.json")


def main(argv: list[str] | None = None) -> int:
    from . import service
    from .analysis_import import AnalysisError
    from .inbox import process_inbox
    from .kalshi_link import KalshiRefused
    from .transcripts import TranscriptError

    args = build_parser().parse_args(argv)
    store = _store(args.db)
    try:
        if args.cmd == "verify-sources":
            res = service.verify_sources(store, only=args.only)
            _print({"verified": sum(r["ok"] for r in res), "failed": [r for r in res if not r["ok"]]})
        elif args.cmd == "collect":
            _print(service.collect_news(store, force=args.force))
        elif args.cmd == "status":
            _print(service.status(store))
        elif args.cmd == "events":
            out = []
            for ev in service.current_events(store):
                out.append({"event_id": ev.event_id, "title": ev.title, "verification": ev.verification.value,
                            "origins": ev.origins, "evidence": len(ev.evidence_ids),
                            "outcomes": [o.outcome_id for o in ev.outcomes]})
            _print(out)
        elif args.cmd == "import-transcript":
            data = Path(args.file).read_bytes()
            meta = {"podcast": args.podcast, "episode": args.episode, "published_date": args.date,
                    "episode_url": args.url, "transcript_source": args.source, "notes": args.notes}
            _print(service.import_transcript(store, data=data, meta={k: v for k, v in meta.items() if v is not None},
                                             filename=Path(args.file).name))
        elif args.cmd == "packet":
            print(service.create_packet(store, args.event_id, horizon_date=args.horizon).text)
        elif args.cmd == "import-analysis":
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            _print(service.import_analysis(store, text, owner_judgment=args.owner_judgment))
        elif args.cmd == "discover-markets":
            _print(service.discover_markets(store, args.event_id))
        elif args.cmd == "link":
            _print(service.record_link(store, outcome_id=args.outcome_id, ticker=args.ticker, status=args.status,
                                       rules_read=args.rules_read, yes_matches_outcome=args.yes_matches_outcome))
        elif args.cmd == "refresh-quotes":
            _print(service.refresh_quotes(store, only_outcome=args.outcome))
        elif args.cmd == "resolve":
            _print(service.record_resolution(store, outcome_id=args.outcome_id, result=args.result, source=args.source))
        elif args.cmd == "performance":
            _print(service.performance(store))
        elif args.cmd == "process-inbox":
            res = process_inbox(store, Path(args.inbox))
            write_heartbeat(args.status_dir, {"schema": "intel-heartbeat/1", "processor": "inbox",
                                              "at_utc": service.iso(service.utcnow()), "processed": len(res)})
            _print(res)
        elif args.cmd == "run":
            out = {"news": service.collect_news(store)}
            try:
                out["quotes"] = service.refresh_quotes(store)
            except KalshiRefused as exc:
                out["quotes"] = {"status": "REFUSED", "code": exc.code}
            out["inbox"] = process_inbox(store, Path(args.inbox))
            write_heartbeat(args.status_dir, {"schema": "intel-heartbeat/1", "processor": "run",
                                              "at_utc": service.iso(service.utcnow()),
                                              "news": out["news"].get("status", "OK")})
            _print(out)
    except (AnalysisError, TranscriptError, KalshiRefused, KeyError, ValueError) as exc:
        problems = getattr(exc, "problems", None)
        _print({"status": "REFUSED", "error": type(exc).__name__, "detail": problems or str(exc)})
        return 2
    return 0
