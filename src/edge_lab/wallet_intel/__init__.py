"""Wallet / trader intelligence and copyability research (issue #168, ADR 0045). Offline research only.

The owner's choice of 2026-10-07: synthetic fixtures plus Polymarket Data API v2 documentation
examples, with no network calls. This package fetches nothing, reads no environment variable,
holds no credential and cannot reach the isolated execution package (a boundary test proves it).

Modules (one owner, subordinate modules):
- `exact`: Decimal exactness and `Labeled` values (Basis mirrors research_economics).
- `identity`: public pseudonymous accounts and bitemporal proxy mappings.
- `events`: normalized observations, the action taxonomy, the append-only log, position effects.
- `polymarket_v2`: the strict v2 envelope/pagination/error parser (fixture-fed).
- `observability`: typed source capabilities; research vs execution eligibility.
- `accounting`: LEADER_OBSERVED_ECONOMICS and leader dimensions with shrinkage.
- `selection`: the point-in-time selection manifest and walk-forward helpers.
- `receipts`: v2 causal selection receipts (complete dependency closure, verify/rebuild; v1 is legacy).
- `market_data`, `replay`: FOLLOWER_SIMULATED_ECONOMICS at attainable prices.
- `policy`: follower policy, attribution and caps behind a typed signal boundary.
- `threats`: defensive screens (coordination, churn, off-market fills, bait sizes).
- `stats`: shrinkage, cluster bootstrap, Benjamini-Hochberg (floats for statistics only).
- `demo`: Demonstration A, `run_synthetic_demo(seed)`.
"""

WALLET_INTEL_VERSION = "wallet-intel-v1"
