"""Command line and local server for the read-only dashboard (stdlib `wsgiref`).

Binds to 127.0.0.1 by default. A non-loopback bind is refused unless
`--allow-non-loopback` is passed, and even then a warning is printed: the owner has not
authorized exposing this dashboard (docs/DASHBOARD.md).
"""

from __future__ import annotations

import argparse
import ipaddress
import shutil
import sys
from pathlib import Path
from typing import Sequence
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import data as d
from .app import make_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class NonLoopbackRefused(ValueError):
    """The requested bind address is not loopback and no override was given."""


def is_loopback(host: str) -> bool:
    """True only for an address that is certainly loopback. Unresolvable names are not."""
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip().strip("[]")).is_loopback
    except ValueError:
        return False


def check_bind_host(host: str, allow_non_loopback: bool) -> str | None:
    """Return a warning for an allowed non-loopback bind, None for loopback; raise if refused."""
    if is_loopback(host):
        return None
    if not allow_non_loopback:
        raise NonLoopbackRefused(
            f"refusing to bind {host!r}: not a loopback address. The dashboard is local-only; public or LAN "
            "exposure is not authorized. Pass --allow-non-loopback only with explicit owner approval.")
    return (f"WARNING: binding non-loopback address {host!r}. Anyone who can reach this port can read shadow "
            "data. There is no authentication. Public exposure is NOT authorized.")


def default_experiments_root() -> Path | None:
    """The repository's experiments/ directory when running from a checkout (editable install)."""
    candidate = Path(__file__).resolve().parents[3] / "experiments"
    return candidate if candidate.is_dir() else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m edge_lab.dashboard",
        description="Local read-only shadow dashboard (SHADOW - NO REAL MONEY). Never sends orders or writes data.")
    p.add_argument("--db", type=Path, help="evidence SQLite database (opened read-only)")
    p.add_argument("--ledger", type=Path, help="shadow ledger SQLite file (opened read-only)")
    p.add_argument("--status-dir", type=Path, help="directory holding latest.json / shadow_daily.json")
    p.add_argument("--experiments-root", type=Path, help="experiments/ directory (default: this checkout's)")
    p.add_argument("--host", default=DEFAULT_HOST, help="bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8765)")
    p.add_argument("--allow-non-loopback", action="store_true",
                   help="permit a non-loopback --host (needs owner approval; prints a warning)")
    p.add_argument("--demo", action="store_true",
                   help="serve SYNTHETIC data built in a fresh temp directory; configured paths are ignored")
    return p


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        sys.stderr.write("dashboard: %s %s\n" % (self.command, self.path.split("?", 1)[0]))


def config_from_args(args: argparse.Namespace) -> tuple[d.Config, Path | None]:
    """The Config to serve, and the demo temp directory (None outside demo mode)."""
    experiments_root = args.experiments_root or default_experiments_root()
    if args.demo:
        from .demo import build_demo
        config, root = build_demo(experiments_root=experiments_root)
        return config, root
    return d.Config(db=args.db, ledger=args.ledger, status_dir=args.status_dir,
                    experiments_root=experiments_root), None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        warning = check_bind_host(args.host, args.allow_non_loopback)
    except NonLoopbackRefused as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2
    if warning:
        print(f"dashboard: {warning}", file=sys.stderr)
    config, demo_root = config_from_args(args)
    if demo_root is not None:
        print(f"dashboard: SYNTHETIC DEMO DATA in a temporary directory ({demo_root.name}); "
              "configured --db/--ledger/--status-dir are ignored", file=sys.stderr)
    server = make_server(args.host, args.port, make_app(config), server_class=WSGIServer,
                         handler_class=_QuietHandler)
    host = f"[{args.host}]" if ":" in args.host else args.host
    print(f"dashboard: serving read-only on http://{host}:{server.server_port}/ (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if demo_root is not None:
            shutil.rmtree(demo_root, ignore_errors=True)  # only the demo's own temp directory
    return 0
