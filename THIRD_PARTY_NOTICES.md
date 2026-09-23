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
