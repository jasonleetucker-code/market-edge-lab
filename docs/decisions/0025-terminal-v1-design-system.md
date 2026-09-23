# 0025 — Market Edge Terminal v1: one server-rendered design system

Status: Accepted (2026-09-23, owner directive `docs/owner/2026-09-23-terminal-v1-ui-directive.md`,
issue #47).

**Problem.** The owner rejected the first dashboard (six iPhone screenshots: a red banner,
three rows of wrapped navigation, giant panels, raw file names and codes above any market
information). The directive asks for a permanent product interface: a market terminal that
every later domain, venue and feature inherits, with fixed tokens, typography, navigation,
components and honest states, and no discretionary redesign by later agents.

**Alternatives.**
1. Restyle the existing inline-CSS pages. Rejected by the directive ("different colours on the
   giant-panel layout" fails review) and it leaves presentation logic scattered in views.
2. A JavaScript front end (React/Next/Tailwind or a UI kit) with a JSON API. Rejected: a second
   runtime, a build step, a second API, new dependencies and client code to audit, for a
   read-only page set the Python server already renders.
3. Keep the stdlib WSGI server and split presentation into owners: `presentation.py` (formats,
   state vocabulary, query allowlist, typed view models), `components.py` (escaped HTML),
   `html.py` (shell and asset allowlist), `views/` (one module per page), plus self-hosted
   `tokens.css`, `terminal.css`, a small `terminal.js`, IBM Plex WOFF2 and a Lucide sprite.

**Decision.** Alternative 3, with these specifics:
- **Assets** are package data served from an exact allowlist under a content-hash path
  (`/static/<12 hex>/<name>`, immutable cache); everything else keeps `no-store`. The icon
  sprite is inlined (an external `<use>` would need a looser CSP).
- **CSP** moves from `style-src 'unsafe-inline'` + `form-action 'none'` to `script-src 'self';
  style-src 'self'; font-src 'self'; img-src 'self'; form-action 'self'`: stricter on styles
  (no inline style at all), and GET filter forms become possible. No inline script, handler or
  third-party origin.
- **Query parameters**: each route has an explicit allowlist (`presentation.ROUTE_PARAMS`);
  values are checked against fixed sets, the venue registry or bounded patterns; an unknown
  value is a safe 400 page; unknown names are ignored as before. No value reaches SQL, a path,
  a callable, a command or a URL.
- **Market data**: a new read-only loader (`data.observed_board`) reads the latest target
  day's decision and re-check captures and normalizes books with the canonical
  `kalshi_quotes.quotes_from_orderbook`. Rows join those quotes with the selected account's
  recorded decision payloads. Nothing re-evaluates the engine at render time; price change is
  only the difference between two captured asks of the same side.
- **Board layout** uses CSS container queries, so the same row adapts to the Terminal's
  8-column workspace, the full Markets page and a phone without a second template.
- **Fonts** are IBM Plex Latin-1 split subsets (OFL-1.1, pinned commits, 120 KiB total);
  **icons** are 37 Lucide symbols (ISC; Feather-derived ones also MIT). Line endings in
  `static/` are frozen by a directory `.gitattributes` so recorded hashes hold.

**Tradeoffs.**
- The page carries a ~7 KB inline sprite per request; acceptable against a stricter CSP.
- Container queries need Safari 16+ / Chromium 105+; older browsers fall back to the stacked
  mobile row (usable, less dense).
- "Realized today" has no canonical calendar-day figure; it renders as not computed rather
  than a derived number (dependency recorded in `docs/design/IMPLEMENTATION.md`).
- The risk engine does not report which headroom binds; the page shows the exact capacity and
  the verdict, not an invented binding reason.
- Playwright is a development-only evidence tool (`tests/browser/`), never a runtime or CI
  dependency.

**Reconsider when:** the page count or interactivity outgrows server rendering (for example a
live execution ticket, which needs its own authorization anyway), a second theme is specified
by amendment, or container-query support becomes a problem on the owner's devices.
