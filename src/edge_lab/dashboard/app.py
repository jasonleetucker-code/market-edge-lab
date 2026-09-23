"""The WSGI application: fixed routes, GET/HEAD only, restrictive headers.

There is no endpoint that takes SQL, a file path, a command or any other parameter. Query
strings are ignored. A request whose Host header is not a loopback name (or a host the
operator bound explicitly) is refused, so a web page cannot read the dashboard through DNS
rebinding.
"""

from __future__ import annotations

import ipaddress
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import data as d
from .html import esc, page
from .views import PAGES

SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Cache-Control", "no-store"),
    ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
)
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
ALLOWED = ("GET", "HEAD")


def host_allowed(header: Any, extra: Iterable[str] = ()) -> bool:
    """True for a Host header naming loopback (localhost, 127.0.0.0/8, ::1) or one of `extra`.

    A missing header is allowed: browsers always send one, so its absence is not a
    rebinding attack (curl and HTTP/1.0 tools may omit it)."""
    if header is None:
        return True
    text = str(header).strip().lower()
    if text.startswith("["):  # [::1]:8765
        name = text[1:text.find("]")] if "]" in text else text
    else:
        name = text.rsplit(":", 1)[0] if text.count(":") == 1 else text
    name = name.rstrip(".")
    if name == "localhost" or name in {h.strip().lower().strip("[]") for h in extra}:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _status_line(code: int) -> str:
    return {200: "200 OK", 400: "400 Bad Request", 404: "404 Not Found", 405: "405 Method Not Allowed",
            500: "500 Internal Server Error"}[code]


def make_app(config: d.Config) -> Callable[[dict[str, Any], Callable], Iterable[bytes]]:
    """A WSGI callable over `config`. Every request opens the sources read-only afresh."""

    def render(title: str, path: str, body: str) -> str:
        now = config.clock()
        stamp = now.astimezone(timezone.utc).isoformat() if isinstance(now, datetime) else str(now)
        return page(title, path, body, demo=config.demo, generated_at=stamp)

    def app(environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/") or "/")
        if len(path) > 1:
            path = path.rstrip("/") or "/"
        extra: list[tuple[str, str]] = []
        if not host_allowed(environ.get("HTTP_HOST"), config.allowed_hosts):
            code, ctype, text = 400, TEXT, "refused: Host header is not a local address\n"
        elif method not in ALLOWED:
            code, ctype = 405, HTML
            extra.append(("Allow", ", ".join(ALLOWED)))
            text = render("Method not allowed", path, "<p>This dashboard is read-only: only GET and HEAD are "
                                                      "accepted.</p>")
        elif path == "/healthz":
            code, ctype, text = 200, TEXT, "ok\n"
        elif path in PAGES:
            title, view = PAGES[path]
            try:
                body = view(d.Context(config))
                code, ctype = 200, HTML
            except Exception as exc:  # noqa: BLE001 - never leak a traceback to the page
                print(f"dashboard: error rendering {path}: {d.short_error(exc, config)}", file=sys.stderr)
                code, ctype = 500, HTML
                body = ("<p>This page could not be rendered. The data sources were not changed. "
                        "See the server console for a one-line error.</p>")
            text = render(title, path, body)
        else:
            code, ctype = 404, HTML
            text = render("Not found", path, f"<p>No page at {esc(path)}.</p>")
        payload = text.encode("utf-8")
        headers = [("Content-Type", ctype), ("Content-Length", str(len(payload))), *SECURITY_HEADERS, *extra]
        start_response(_status_line(code), headers)
        return [b""] if method == "HEAD" else [payload]

    return app
