# Third-party notices and code provenance

Public GitHub is not public domain. This file is the record of every piece of outside work
that shaped code in this repository. The rules are in `docs/GITHUB_REUSE_AUDIT.md` →
Adoption rules. `tests/invariants/test_third_party_provenance.py` enforces them:

- every runtime dependency in `pyproject.toml` is listed below with its license and reason;
- every code comment that says code was copied, vendored, ported or adapted from somewhere
  cites an entry here (`TPN-…`) or a first-party source;
- every entry pins an exact upstream commit (40 hex) and names the license;
- every `TPN-…` reference in code exists here.

An entry is added in the same PR as the code it covers. Copied or vendored source keeps its
upstream copyright and license text next to it, in addition to the entry here.

## Runtime dependencies

None. `pyproject.toml` declares `dependencies = []`; the runtime is the Python standard
library. `pytest` is a development dependency only.

A future entry records: the package name in backticks, the version pin, the license, the
transitive dependencies, the reason it beats a stdlib implementation, and the audit section
that approved it.

## Vendored or copied source

None. No third-party source code has been copied into this repository.

## First-party sources

Repositories owned by the project owner. Reuse from them needs no license entry, but it is
still named in the code that adapts it.

- `jasonleetucker-code`: the owner's GitHub account.
- `brisket`: the owner's Brisket repository (reliability patterns; `docs/BRISKET_REUSE_AUDIT.md`).

## Independently reimplemented patterns

Ideas studied in upstream code and then written from scratch here, under our own
semantics. No upstream code was copied, so no upstream notice is required; the entry exists
so the idea's origin stays traceable.

### TPN-R001 — venue-neutral depth ladder and walk-the-book cost

- **Where:** `src/edge_lab/opportunity.py` (`DepthLadder`, `walk_ladder`, `price_depth_fill`);
  `src/edge_lab/kalshi_quotes.py` (`ladders_from_orderbook`); `tests/test_depth.py`.
- **Upstream studied:** `ccxt/ccxt` at `10ad2b51b9bf5d8c01c706755b0b0ec18a0cb693` (unified
  order-book structure); `nautechsystems/nautilus_trader` at
  `3adf5a8dc0c9e676eb1e131911a73ad693ea7b42` (order-book levels and simulated taker fills).
- **License:** MIT (ccxt); LGPL-3.0-or-later (nautilus_trader). Nothing was copied from either.
- **What differs from upstream:** captured levels only; all-or-nothing (a partial walk is
  never priced); a truncated capture that runs out is `DEPTH_UNKNOWN`, not thin; invalid
  levels fail closed; fees are priced per level by our versioned fee schedules.
- **Audit:** `docs/GITHUB_REUSE_AUDIT.md`.

### TPN-R002 — execution and settlement semantics pinned by the Gate 7 replay tests

- **Where:** `tests/gate7/test_gate7_replay_semantics.py`; the GATE7-F14 fix in
  `src/edge_lab/exp001_shadow.py` (`event_settlement_problems`).
- **Upstream studied:** `Oddpool/PredictionMarketBench` at
  `611d66941717310858683278940df21c33c406f2` (order types, resting-order queue, partial
  fills, maker fees, mark-to-market defaults, per-event settlement); `betcode-org/flumine` at
  `54854495b45accae614b23d10859047d582c3ecf` (simulated matching after latency);
  `nautechsystems/nautilus_trader` at `3adf5a8dc0c9e676eb1e131911a73ad693ea7b42` (queue
  position and liquidity consumption in the matching engine).
- **License:** PredictionMarketBench has no LICENSE file at that commit (README and
  pyproject say MIT), so it is ideas only; flumine MIT; nautilus_trader LGPL-3.0-or-later.
  Nothing was copied from any of them.
- **What differs from upstream:** these scenarios are used to pin that the frozen EXP-001
  execution model does *not* do what the upstream simulators do (no resting orders, no
  queue, no partial fills, no maker fees, no default marks), and that an event settles
  only on coherent evidence.
- **Audit:** `docs/GITHUB_REUSE_AUDIT.md`.

### TPN-R003 — per-market price grid from venue-published tick ranges

- **Where:** `src/edge_lab/opportunity.py` (`PriceGrid`, `PriceRange`, `walk_ladder(price_grid=...)`);
  `src/edge_lab/kalshi_quotes.py` (`price_grid_from_kalshi`); `src/edge_lab/polymarket_us.py`
  (`price_grid_from_market`); `tests/test_payoff_and_grid.py`; ADR 0023.
- **Upstream studied:** `arshka/pykalshi` at `e42d9f3c491c5037cfe51c7f69ad35074d097255`
  (a price check against Kalshi's `price_ranges`).
- **License:** MIT. Nothing was copied.
- **What differs from upstream:** Decimal throughout; a missing or malformed grid is None
  and never assumed to be the cent grid; the grid is enforced in depth walks, not in the
  frozen opportunity engine.
- **Audit:** `docs/GITHUB_REUSE_AUDIT.md`.

### TPN-R004 — ordered pre-submit control chain for the execution ticket

- **Where:** `src/edge_lab/execution_ticket.py` (`pre_submit_checks`, `Control`,
  `TICKET_TRANSITIONS`, `ORDER_TRANSITIONS`); `tests/test_execution_ticket_controls.py`.
- **Upstream studied:** `betcode-org/flumine` at `54854495b45accae614b23d10859047d582c3ecf`
  (trading and client controls, order validation, exposure counting pending orders).
- **License:** MIT. Nothing was copied.
- **What differs from upstream:**
  - a stale book is rejected, not warned;
  - there is no `force` bypass;
  - money is Decimal;
  - exposure limits come from `risk.RiskPolicy`, and a missing risk report fails closed;
  - transitions are guarded by explicit tables with terminal states final;
  - the chain always ends in `EXECUTION_NOT_AUTHORIZED`, so no ticket can be submitted.
- **Audit:** `docs/GITHUB_REUSE_AUDIT.md` §7.3, §7.8; `docs/audits/2026-09-23-github-reuse/D_sports.md`.

## Vendored assets

Binary and markup assets shipped as package data with the dashboard (Market Edge Terminal v1,
ADR 0025). No third-party source code is included. Each file's SHA-256, size and upstream
path are in `src/edge_lab/dashboard/static/ASSETS_PROVENANCE.md`; the licence texts sit next to
the files, and `src/edge_lab/dashboard/static/.gitattributes` stops git from changing their
bytes.

### TPN-A001 — IBM Plex fonts (Sans, Sans Condensed, Mono)

- **Where:** `src/edge_lab/dashboard/static/fonts/` (six Latin-1 split-subset WOFF2 files:
  Sans 400/500/600, Sans Condensed 600, Mono 400/500) and `fonts/LICENSE-IBM-Plex-OFL.txt`.
- **Upstream:** `IBM/plex`, npm packages published from it: `@ibm/plex-sans@1.1.0` at
  `1da12f02587b630c07e92692d21492d722f53614`, `@ibm/plex-sans-condensed@2.0.0` at
  `bb3ab6404e1881ea286f8742dc839e09057db6dd`, `@ibm/plex-mono@2.5.0` at
  `2f9ba1b25957d958db71a849e85d72e3ecfb845a`.
- **License:** OFL-1.1 (SIL Open Font License 1.1). Files are unmodified; the font names are
  not changed and the fonts are not sold on their own.
- **Why:** the owner directive fixes IBM Plex as the typographic system and forbids font CDNs.

### TPN-A002 — Lucide icon subset

- **Where:** `src/edge_lab/dashboard/static/icons.svg` (37 symbols, shape elements copied
  verbatim; presentation attributes removed so CSS sets stroke) and
  `static/LICENSE-Lucide.txt`.
- **Upstream:** `lucide-icons/lucide` release 1.47.0 at
  `3b9ea6d08707edc439f25a4c354cb0d6b8bee973`.
- **License:** ISC (Lucide); icons derived from Feather are also MIT (Cole Bemis). The full
  licence file is kept, which satisfies both.
- **Why:** the directive asks for one consistent line-icon family from an audited static
  subset, with no icon font or remote sprite.
