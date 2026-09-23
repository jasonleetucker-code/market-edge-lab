"""Local, read-only, mobile-friendly shadow dashboard (owner directive 2026-09-23, priority 5).

Stdlib only: a WSGI application (`app.make_app`) served by `wsgiref` on 127.0.0.1. It reads
the evidence store and shadow ledger through their read-only openers and shows figures
computed by the canonical modules. It never writes, trades or exposes itself publicly.
See docs/DASHBOARD.md.
"""

from __future__ import annotations

from .app import make_app
from .data import Config
from .server import main

__all__ = ["Config", "main", "make_app"]
