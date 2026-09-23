"""Page composition for Market Edge Terminal v1. One module per page owner.

Each view takes a request `Context` and validated `Params` and returns a `Page` whose body is
escaped HTML composed only from `components` (docs/design/COMPONENTS.md).
"""

from __future__ import annotations

from . import alerts, gallery, markets, outcomes, portfolio, research, risk, terminal
from .common import Page

# path -> (title, view). The title is used when a view fails before it can name itself.
PAGES = {
    "/": ("Terminal", terminal.view),
    "/opportunities": ("Markets", markets.view),
    "/positions": ("Portfolio", portfolio.view),
    "/outcome-board": ("Outcomes", outcomes.view),
    "/risk": ("Risk & capital", risk.view),
    "/experiments": ("Research & Data", research.view),
    "/alerts": ("Alerts", alerts.view),
    "/more": ("More", alerts.more),
    "/market": ("Market", markets.detail),
}
# Demo/test mode only (Config.demo): the gallery never reads production stores.
DEMO_PAGES = {"/gallery": ("Component gallery", gallery.view)}
NAV_KEYS = {"/": "terminal", "/opportunities": "markets", "/positions": "portfolio", "/outcome-board": "outcomes",
            "/risk": "risk", "/experiments": "research", "/alerts": "alerts", "/more": "more", "/market": "markets"}

__all__ = ["DEMO_PAGES", "NAV_KEYS", "PAGES", "Page"]
