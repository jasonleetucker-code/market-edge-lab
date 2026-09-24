"""Command line and local server for the read-only dashboard (stdlib `wsgiref`).

Binds to 127.0.0.1 by default. A non-loopback bind is refused unless
`--allow-non-loopback` is passed, and even then a warning is printed: the owner has not
authorized exposing this dashboard (docs/DASHBOARD.md).

`--tailscale-serve-host` accepts one exact `<machine>.<tailnet>.ts.net` name in the Host
header, for private tailnet access through Tailscale Serve (ADR 0024). The bind stays
loopback: only the local tailscaled proxy can reach the port.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import re
import shutil
import signal
import socket
import sys
import threading
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


# One MagicDNS name, <machine>.<tailnet>.ts.net: DNS labels only, no wildcard, port or other domain.
_TS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_TAILSCALE_SERVE_NAME = re.compile(rf"{_TS_LABEL}\.{_TS_LABEL}\.ts\.net")


def check_tailscale_serve_host(name: str) -> str:
    """The normalized MagicDNS name to accept in Host; ValueError unless it is exactly one."""
    text = name.strip().lower().rstrip(".")
    if not _TAILSCALE_SERVE_NAME.fullmatch(text):
        raise ValueError(f"not a Tailscale MagicDNS name (<machine>.<tailnet>.ts.net): {name!r}")
    return text


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
    p.add_argument("--odds-ledger", type=Path,
                   help="The Odds API quota ledger, read without locking (default: odds_quota_ledger.json beside --db)")
    p.add_argument("--host", default=DEFAULT_HOST, help="bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8765)")
    p.add_argument("--allow-non-loopback", action="store_true",
                   help="permit a non-loopback --host (needs owner approval; prints a warning)")
    p.add_argument("--tailscale-serve-host", metavar="NAME",
                   help="also accept Host: NAME, this node's exact <machine>.<tailnet>.ts.net name, when "
                        "Tailscale Serve proxies the tailnet to this loopback server (loopback bind only)")
    p.add_argument("--demo", action="store_true",
                   help="serve SYNTHETIC data built in a fresh temp directory; configured paths are ignored")
    return p


class _IPv6Server(WSGIServer):
    address_family = socket.AF_INET6


def server_class_for(host: str) -> type[WSGIServer]:
    """An IPv6 literal (::1) needs an AF_INET6 socket; everything else binds IPv4."""
    return _IPv6Server if ":" in host else WSGIServer


_UNSET = object()


def _sigterm_to_interrupt(signum, frame) -> None:  # noqa: ARG001 - signal handler signature
    raise KeyboardInterrupt


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
                    experiments_root=experiments_root, odds_ledger=args.odds_ledger), None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        warning = check_bind_host(args.host, args.allow_non_loopback)
    except NonLoopbackRefused as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2
    if warning:
        print(f"dashboard: {warning}", file=sys.stderr)
    allowed: list[str] = []
    if warning:  # an explicitly approved non-loopback bind: accept its own name in Host
        allowed.append(args.host)
    if args.tailscale_serve_host is not None:
        if warning:
            print("dashboard: --tailscale-serve-host needs a loopback --host: Tailscale Serve proxies to "
                  "loopback, so the port is never opened to a network", file=sys.stderr)
            return 2
        try:
            allowed.append(check_tailscale_serve_host(args.tailscale_serve_host))
        except ValueError as exc:
            print(f"dashboard: {exc}", file=sys.stderr)
            return 2
    config, demo_root = config_from_args(args)
    if allowed:
        config = dataclasses.replace(config, allowed_hosts=tuple(allowed))
    if demo_root is not None:
        print(f"dashboard: SYNTHETIC DEMO DATA in a temporary directory ({demo_root.name}); "
              "configured --db/--ledger/--status-dir are ignored", file=sys.stderr)
    bind_host = args.host.strip().strip("[]")
    try:
        server = make_server(bind_host, args.port, make_app(config), server_class=server_class_for(bind_host),
                             handler_class=_QuietHandler)
    except OSError as exc:
        print(f"dashboard: cannot bind {args.host}:{args.port}: {exc.strerror or exc}", file=sys.stderr)
        if demo_root is not None:
            shutil.rmtree(demo_root, ignore_errors=True)
        return 2
    previous_sigterm: object = _UNSET
    try:
        if threading.current_thread() is threading.main_thread():
            # SIGTERM stops the server like Ctrl+C, so the demo's temp directory is removed too.
            previous_sigterm = signal.signal(signal.SIGTERM, _sigterm_to_interrupt)
        host = f"[{bind_host}]" if ":" in bind_host else bind_host
        print(f"dashboard: serving read-only on http://{host}:{server.server_port}/ (Ctrl+C to stop)",
              file=sys.stderr)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if previous_sigterm is not _UNSET:
            # None means a handler installed from C: fall back to the default action.
            signal.signal(signal.SIGTERM, signal.SIG_DFL if previous_sigterm is None else previous_sigterm)
        if demo_root is not None:
            shutil.rmtree(demo_root, ignore_errors=True)  # only the demo's own temp directory
    return 0
