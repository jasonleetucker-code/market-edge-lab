"""The WSGI application: fixed routes, GET/HEAD only, restrictive headers.

There is no endpoint that takes SQL, a file path, a command or a URL. Query strings are read
only for each route's explicit parameter allowlist (`presentation.ROUTE_PARAMS`), and every
value is validated against a fixed set, a registry or a bounded pattern; anything else is
ignored or refused with a safe message. Static assets come from an exact allowlist of
package files. A request whose Host header is not a loopback name (or a host the operator
bound explicitly) is refused, so a web page cannot read the dashboard through DNS rebinding.
"""

from __future__ import annotations

import ipaddress
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .. import venues
from . import data as d
from . import presentation as pr
from .html import STATIC_FILES, Shell, asset_version, esc, page, static_bytes
from .views import DEMO_PAGES, NAV_KEYS, PAGES, Page
from .views import common as cm

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; "
       "connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", CSP),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)
NO_STORE = ("Cache-Control", "no-store")
IMMUTABLE = ("Cache-Control", "public, max-age=31536000, immutable")
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
ALLOWED = ("GET", "HEAD")
_STATIC = re.compile(r"/static/([0-9a-f]{12})/([a-z0-9][a-z0-9/._-]{0,80})")


def host_allowed(header: Any, extra: Iterable[str] = ()) -> bool:
    """True for a Host header naming loopback (localhost, 127.0.0.0/8, ::1) or one of `extra`.

    A missing header is allowed: browsers always send one, so its absence is not a
    rebinding attack (curl and HTTP/1.0 tools may omit it)."""
    if header is None:
        return True
    text = str(header).strip().lower()
    if text.startswith("["):  # [::1]:8765
        name, sep, rest = text[1:].partition("]")
        if not sep or (rest and not re.fullmatch(r":\d{1,5}", rest)):
            return False
    elif text.count(":") == 1:  # host:port
        name, port = text.split(":")
        if not re.fullmatch(r"\d{1,5}", port):
            return False
    else:
        name = text
    name = name.rstrip(".")
    if not name:
        return False
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
    pages = {**PAGES, **(DEMO_PAGES if config.demo else {})}

    def shell_for(ctx: d.Context | None, title: str, nav: str, body: str, *, account: str | None = None,
                  params: pr.Params | None = None) -> str:
        now = config.clock()
        stamp = now.astimezone(timezone.utc).isoformat() if isinstance(now, datetime) else str(now)
        tape, alerts = "", None
        if ctx is not None:
            try:
                p = params or pr.Params()
                from .components import tape as tape_html
                tape = tape_html(pr.tape_rows(cm.board_rows(ctx, p)), p)
            except Exception as exc:  # noqa: BLE001 - the tape never fails a page
                print(f"dashboard: tape unavailable: {d.short_error(exc, config)}", file=sys.stderr)
                tape = ""
            alerts = cm.attention_count(ctx)
        return page(Shell(title=title, nav=nav, body=body, demo=config.demo, rendered_utc=stamp,
                          rendered_et=pr.datetime_et(stamp), account_label=account, tape=tape, alerts=alerts))

    def static(path: str) -> tuple[int, str, bytes, tuple]:
        m = _STATIC.fullmatch(path)
        if not m or m.group(2) not in STATIC_FILES or ".." in m.group(2):
            return 404, TEXT, b"not found\n", NO_STORE
        if m.group(1) != asset_version():
            return 404, TEXT, b"not found (stale asset version)\n", NO_STORE
        return 200, STATIC_FILES[m.group(2)], static_bytes(m.group(2)), IMMUTABLE

    def app(environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/") or "/")
        if len(path) > 1:
            path = path.rstrip("/") or "/"
        extra: list[tuple[str, str]] = []
        cache = NO_STORE
        payload: bytes | None = None
        if not host_allowed(environ.get("HTTP_HOST"), config.allowed_hosts):
            code, ctype, text = 400, TEXT, "refused: Host header is not a local address\n"
        elif method not in ALLOWED:
            code, ctype = 405, HTML
            extra.append(("Allow", ", ".join(ALLOWED)))
            text = shell_for(None, "Method not allowed", "", "<p>This dashboard is read-only: only GET and HEAD are "
                                                            "accepted.</p>")
        elif path == "/healthz":
            code, ctype, text = 200, TEXT, "ok\n"
        elif path.startswith("/static/"):
            code, ctype, payload, cache = static(path)
            text = ""
        elif path in pages:
            title, view = pages[path]
            ctx = d.Context(config)
            params: pr.Params | None = None
            try:
                params = pr.parse_params(path, str(environ.get("QUERY_STRING") or ""), venues=venues.VENUES,
                                         sports=())
            except pr.ParamError as exc:
                code, ctype = 400, HTML
                body = (f'<div class="page-head"><h1 class="page-title">{esc(title)}</h1></div>'
                        f'<div class="validation" role="alert"><p><strong>Unsupported filter:</strong> {esc(str(exc))}.'
                        f' <a class="link" href="{esc(path)}">Clear filters</a></p></div>')
                text = shell_for(ctx, title, NAV_KEYS.get(path, ""), body)
            else:
                try:
                    result = view(ctx, params)
                    result = result if isinstance(result, Page) else Page(title, NAV_KEYS.get(path, ""), str(result))
                    code, ctype = result.status, HTML
                    account = cm.scope_label(params) if result.account_scoped else None
                    text = shell_for(ctx, result.title, result.nav, result.body, account=account, params=params)
                except Exception as exc:  # noqa: BLE001 - never leak a traceback to the page
                    print(f"dashboard: error rendering {path}: {d.short_error(exc, config)}", file=sys.stderr)
                    code, ctype = 500, HTML
                    body = (f'<div class="page-head"><h1 class="page-title">{esc(title)}</h1></div>'
                            '<div class="validation" role="alert"><p>This page could not be rendered. The data '
                            "sources were not changed. See the server console for a one-line error.</p></div>")
                    text = shell_for(None, title, NAV_KEYS.get(path, ""), body)
        else:
            code, ctype = 404, HTML
            text = shell_for(None, "Not found", "", f'<div class="page-head"><h1 class="page-title">Not found</h1>'
                                                    f'</div><p>No page at {esc(path)}.</p>')
        if payload is None:
            payload = text.encode("utf-8")
        headers = [("Content-Type", ctype), ("Content-Length", str(len(payload))), *SECURITY_HEADERS, cache, *extra]
        start_response(_status_line(code), headers)
        return [b""] if method == "HEAD" else [payload]

    return app
