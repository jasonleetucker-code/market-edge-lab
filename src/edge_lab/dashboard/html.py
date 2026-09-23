"""Document shell, common navigation and static assets for Market Edge Terminal v1.

Every dynamic value passes through `esc` (html.escape, quotes too). Styles and scripts are
self-hosted files served from an exact allowlist (`STATIC_FILES`); pages carry no inline
style or script, so the Content-Security-Policy can forbid both.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

UNKNOWN = '<span class="na" title="unknown / not recorded" aria-label="unknown / not recorded">—</span>'


def esc(value: Any) -> str:
    """Escape any value for HTML text or attribute context. None -> the explicit unknown marker."""
    if value is None:
        return UNKNOWN
    if isinstance(value, bool):
        return "yes" if value else "no"
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- static assets

# The only files the server will ever read from static/: exact names, fixed content types.
STATIC_FILES: dict[str, str] = {
    "tokens.css": "text/css; charset=utf-8",
    "terminal.css": "text/css; charset=utf-8",
    "terminal.js": "text/javascript; charset=utf-8",
    "favicon.svg": "image/svg+xml",
    "fonts/plex-sans-400.woff2": "font/woff2",
    "fonts/plex-sans-500.woff2": "font/woff2",
    "fonts/plex-sans-600.woff2": "font/woff2",
    "fonts/plex-sans-condensed-600.woff2": "font/woff2",
    "fonts/plex-mono-400.woff2": "font/woff2",
    "fonts/plex-mono-500.woff2": "font/woff2",
}
SPRITE_FILE = "icons.svg"  # inlined into every page (an external <use> would need a looser CSP)
FIRST_VIEW_FONTS = ("fonts/plex-sans-400.woff2", "fonts/plex-sans-500.woff2", "fonts/plex-sans-condensed-600.woff2",
                    "fonts/plex-mono-500.woff2")


def _static_root():
    return resources.files("edge_lab.dashboard").joinpath("static")


@lru_cache(maxsize=None)
def static_bytes(name: str) -> bytes:
    """The bytes of one allowlisted asset (package data, so it works from an installed wheel)."""
    if name not in STATIC_FILES and name != SPRITE_FILE:
        raise KeyError(name)
    node = _static_root()
    for part in name.split("/"):
        node = node.joinpath(part)
    return node.read_bytes()


@lru_cache(maxsize=None)
def asset_version() -> str:
    """One fingerprint over every served asset: any change yields new URLs (immutable caching)."""
    h = hashlib.sha256()
    for name in sorted(STATIC_FILES):
        h.update(name.encode())
        h.update(static_bytes(name))
    return h.hexdigest()[:12]


@lru_cache(maxsize=None)
def sprite() -> str:
    """The icon sprite without its XML comment (license and provenance: static/ASSETS_PROVENANCE.md)."""
    text = static_bytes(SPRITE_FILE).decode("utf-8")
    start = text.index("<svg")
    return text[start:].replace("<svg ", '<svg class="sprite" ', 1).strip()


def asset_url(name: str) -> str:
    return f"/static/{asset_version()}/{name}"


# --------------------------------------------------------------------------- navigation

@dataclass(frozen=True)
class NavItem:
    key: str
    href: str
    label: str
    icon: str
    group: int


NAV = (
    NavItem("terminal", "/", "Terminal", "layout-dashboard", 1),
    NavItem("markets", "/opportunities", "Markets", "chart-candlestick", 1),
    NavItem("portfolio", "/positions", "Portfolio", "briefcase-business", 1),
    NavItem("outcomes", "/outcome-board", "Outcomes", "target", 1),
    NavItem("risk", "/risk", "Risk", "shield", 2),
    NavItem("research", "/experiments", "Research & Data", "flask-conical", 2),
    NavItem("alerts", "/alerts", "Alerts", "bell", 2),
)
MORE = NavItem("more", "/more", "More", "menu", 1)
TABBAR = ("terminal", "markets", "portfolio", "outcomes", "more")
UNDER_MORE = {"risk", "research", "alerts", "more"}


def _icon(name: str) -> str:
    return f'<svg class="ic" aria-hidden="true" focusable="false"><use href="#i-{esc(name)}"></use></svg>'


def _link(item: NavItem, current: bool) -> str:
    cur = ' aria-current="page"' if current else ""
    return f'<a href="{esc(item.href)}"{cur}>{_icon(item.icon)}<span>{esc(item.label)}</span></a>'


def rail(nav: str) -> str:
    groups = []
    for g in (1, 2):
        groups.append('<ul class="rail-grp">' + "".join(
            f"<li>{_link(i, i.key == nav)}</li>" for i in NAV if i.group == g) + "</ul>")
    return f'<nav class="rail" aria-label="Primary">{"".join(groups)}</nav>'


def tabbar(nav: str) -> str:
    items = {i.key: i for i in NAV}
    items["more"] = MORE
    links = []
    for key in TABBAR:
        current = key == nav or (key == "more" and nav in UNDER_MORE)
        links.append(f"<li>{_link(items[key], current)}</li>")
    return f'<nav class="tabbar" aria-label="Primary (mobile)"><ul>{"".join(links)}</ul></nav>'


# --------------------------------------------------------------------------- document


@dataclass(frozen=True)
class Shell:
    title: str
    nav: str  # a NAV key, "more", or "" for none
    body: str  # already-escaped page HTML
    demo: bool
    rendered_utc: str
    rendered_et: str | None = None
    account_label: str | None = None  # desktop header: the selected account, when the page is scoped
    tape: str = ""
    alerts: int | None = None  # real locally available attention items; None = unknown


MODE_TEXT = "SHADOW · NO REAL MONEY"
DEMO_TEXT = "SYNTHETIC UI DEMO — NOT REAL, NOT FROM ANY LEDGER OR COLLECTOR"


def page(shell: Shell) -> str:
    bell_label = ("Alerts" if shell.alerts is None else
                  f"Alerts: {shell.alerts} item{'s' if shell.alerts != 1 else ''} need attention" if shell.alerts
                  else "Alerts: nothing needs attention")
    bell_count = f'<span class="bell-n" aria-hidden="true">{esc(shell.alerts)}</span>' if shell.alerts else ""
    bell_cur = ' aria-current="page"' if shell.nav == "alerts" else ""
    demo = (f'<div class="demo-strip" role="note"><p class="demo-strip-in">{esc(DEMO_TEXT)}</p></div>'
            if shell.demo else "")
    account = f'<span class="hdr-acct">{esc(shell.account_label)}</span>' if shell.account_label else ""
    rendered = f"{esc(shell.rendered_et)} ({esc(shell.rendered_utc)})" if shell.rendered_et else esc(shell.rendered_utc)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="robots" content="noindex, nofollow"><meta name="color-scheme" content="dark">'
        '<meta name="theme-color" content="#101214">'
        f"<title>{esc(shell.title)} · Market Edge</title>"
        f'<link rel="icon" href="{asset_url("favicon.svg")}" type="image/svg+xml">'
        f'<link rel="preload" href="{asset_url("fonts/plex-sans-400.woff2")}" as="font" type="font/woff2" crossorigin>'
        f'<link rel="stylesheet" href="{asset_url("tokens.css")}">'
        f'<link rel="stylesheet" href="{asset_url("terminal.css")}">'
        f'<script src="{asset_url("terminal.js")}" defer></script>'
        "</head><body>"
        f"{sprite()}"
        '<a class="skip" href="#main">Skip to content</a>'
        '<header class="hdr"><div class="hdr-in">'
        '<a class="brand" href="/" aria-label="Market Edge, Terminal home">'
        '<span class="brand-rule" aria-hidden="true"></span><span class="brand-word">MARKET EDGE</span></a>'
        '<span class="hdr-desc">Lab · research terminal</span>'
        f'<div class="hdr-right">{account}<span class="mode" role="note">{esc(MODE_TEXT)}</span>'
        f'<a class="bell" href="/alerts" aria-label="{esc(bell_label)}"{bell_cur}>{_icon("bell")}{bell_count}</a>'
        "</div></div></header>"
        f"{demo}{shell.tape}"
        f'<div class="app">{rail(shell.nav)}<main id="main" class="main" tabindex="-1">{shell.body}'
        '<footer class="foot">'
        f"<p>Read-only view of stored evidence. Rendered {rendered}. Refreshing reloads stored data; it never "
        "starts a new scan.</p>"
        "<p>— marks a value that is unknown or not recorded, never zero. All balances are simulated shadow figures; "
        "no real money exists here and nothing on this site can place an order.</p>"
        "</footer></main></div>"
        f"{tabbar(shell.nav)}"
        "</body></html>"
    )
