# ADR 0045: Wallet intelligence owner (offline research; synthetic and Polymarket v2 documentation fixtures)

**Status:** Proposed 2026-10-07 (wallet lane W1–W7, issue #168). Authority: the 2026-10-07 evening owner directive
(`docs/owner/2026-10-07-market-v1-autonomy-wallet-directive.md`, scope in `docs/EXECUTION_PLAN.md`). The owner's
answer 2 chose "Synthetic fixtures + Polymarket v2 docs": build the event model, point-in-time selection and
follower replay on synthetic and documentation-example data, with no network calls. Live public reads need a
separate approval later. This ADR authorizes nothing beyond that.

## Problem

The directive asks whether a public trader's activity can be a *copyable* signal for us, and treats leader
performance, automated software and positive follower returns as three different things. Nothing in the
repository models:
- public wallet events, with their action semantics (a split is not a buy);
- time-versioned proxy and wallet identity;
- leader accounting that keeps unknown cost basis unknown;
- point-in-time leader selection;
- a follower timeline that starts when *we* could have seen the action;
- attribution of one account's inventory to several leaders.

Built carelessly, each becomes a hindsight leak or a fabricated number:
- today's leaderboard used to select yesterday's leaders;
- a transaction hash used as a fill key, so several fills collapse into one;
- a gift marked at a last print and counted as wealth;
- a missed entry plus a leader exit producing a short;
- two leaders spending the same cash.

## Decision

Add one owner, the package `src/edge_lab/wallet_intel/`. It is stdlib-only, pure, deterministic, network-free
and reads no environment variable. It has subordinate modules: `exact`, `identity`, `events`, `polymarket_v2`,
`observability`, `accounting`, `selection`, `market_data`, `replay`, `policy`, `threats`, `stats` and `demo`.
`docs/OWNER_IDEAS.md` names the owner `wallet_intel.py`. It is a package because a single file would pass 3,000
lines, and it remains one owner with one public contract.

- **W1** `observability` is the typed copy of `docs/research/WALLET_SOURCE_MATRIX.md`. Every source is PLANNED or
  BLOCKED with `execution_permitted=False`. The first source is Polymarket Data API v2 (international).
- **W2** `events.WalletObservation` carries every directive §8 field.
  - Identity is a source event id or sub-index when one exists; otherwise a semantic-content hash plus an
    occurrence number, so identical fills in one transaction stay distinct.
  - The `ObservationLog` is append-only. Re-receipt keeps the earliest receipt. Two contents under one identity,
    or one transaction with two block times, is a reported conflict, never a silent winner.
  - Corrections (retraction, supersession, finality change or reorg) are appended. `as_known_at(t)` replays the
    log by knowledge time.
  - `identity` holds bitemporal, many-to-many mappings, with revocations appended.
  - `polymarket_v2` is strict. A missing field, a camelCase (v1) row, a float-decoded number, an inconsistent
    `has_more`, a repeated cursor or an undocumented status is an error.
- **W3** `accounting.reconstruct` gives LEADER_OBSERVED_ECONOMICS from cash flows.
  - A market's P&L is known only once it is flat or resolved, on complete history, with no token transfer.
  - Open holdings count only at a fresh executable bid that covers the whole holding.
  - Fees missing from the source make net P&L UNKNOWN.
  - ROI exists only on complete coverage. `leader_dimensions` reports each directive §9 dimension separately, with
    Beta-binomial empirical-Bayes shrinkage on per-event win rates. There is no score field, and hidden hedges
    are always UNKNOWN.
- **W4** `selection.select_at(D)` builds a point-in-time manifest.
  - It sees only candidates discovered by D, observations received by D and marks known by D; a later mark raises
    `HindsightError`.
  - Every candidate is kept with its reasons: ineligible, inactive and without data alike. The manifest records
    the label version, rule version, cumulative trials and an input digest.
  - Helpers: walk-forward windows, clustering by event, Benjamini-Hochberg.
- **W5** `replay` produces FOLLOWER_SIMULATED_ECONOMICS.
  - The timeline is observation + processing + arrival. Fills come only from captured book levels; missing depth
    is no fill. Partial fills, minimums, rounding, retries, settlement and horizon liquidation are all modelled.
  - The fee function is pluggable and None means UNKNOWN. An UNKNOWN request outcome makes the run's economics
    UNKNOWN.
  - It also reports the leader-versus-follower difference by event with a cluster-bootstrap band, size/delay
    ladders and four benchmarks on matched inputs.
- **W6** `policy` accepts only a typed `FollowSignal`, and its limits are frozen.
  - Authoritative inventory and virtual attribution are separate, and attributions are checked to sum to
    inventory after every change. A sale never exceeds attributable inventory, so there are no shorts and no
    reuse.
  - Automatic catch-up is refused. Caps apply per leader, cluster, event, strategy and in total, on gross cost, so
    opposing signals are not netted as hedges.
  - Proportional mode is blocked without known leader equity. Silent, gap and paused leaders are never liquidated.
- **W7** `threats` screens for co-trading and shared-funding clusters, round-trip churn, off-market allocations
  (UNJUDGED without a book) and bait sizes. Each §11 scenario and each §20 bullet has a test.

`demo.run_synthetic_demo(seed)` is Demonstration A. Its report is deterministic, carries a hash and is labelled
SYNTHETIC in every section.

## Overlap with existing owners (reused, not forked)

| Existing owner | What is reused | What is not, and why |
|---|---|---|
| `provenance` | `canonical_json`, `sha256_hex`, `shape_fingerprint` for identities, raw references and page shapes | — |
| `sources` | `AccessTier`, `SourceStatus` in the typed matrix | No `REGISTRY` entry yet: a source registers with an approved collector (W10), never with fixtures |
| `opportunity` | `DepthLevel` for book levels | `walk_ladder` is all-or-nothing by design; follower replay must price partial fills, so `market_data.take` walks the same levels partially and never past the capture |
| `research_economics` | The `Basis`/`Labeled` vocabulary, mirrored value for value (a parity test pins it) | Not imported: it imports `experiments`, a protected-label owner this package must not reach. Cluster bootstrap is re-stated with floats for statistics only |
| `research_evidence` | The evidence-use contract is the place an empirical run logs consumption (W10) | Not imported now: fixture work consumes no protected evidence, and it would pull in `subprocess` |
| `execution` (ADR 0043) | Its exactness rules (Decimal from str/int, floats refused, trapping context), re-implemented in `exact` | Never imported; the wallet → execution path is W8, a reviewed typed bridge |
| `stats` | — | Its block bootstrap is per-day EXP-001; wallet uncertainty clusters by event |

No second ledger, scheduler, evidence store or graph platform is created. `FollowerBook` is a simulation ledger
inside one replay run. It is never persisted, and it is not account inventory.

`tests/wallet/test_wallet_boundary.py` proves the package imports no network module, no `edge_lab.http`, no
`requests`, no execution package, no research store, no shadow ledger and no protected-label owner, directly or
transitively, and reads no environment. A fresh interpreter that imports every module loads none of them. Every
rule is mutation-checked with probes.

## Alternatives considered

- **Extend `research_economics` with wallet replay.** Rejected. It is the family-economics owner, and it imports
  the experiment registry, a protected-label owner the wallet lane must not reach.
- **Reuse a third-party copy bot (R10–R12).** Rejected for now. Their catch-up, fallback-cache and liquidation
  defaults are exactly what the directive asks us to audit, and no licence, commit or code review exists.
- **One flat `wallet_intel.py`.** Rejected for size and review clarity. It stays one owner with subordinate
  modules, the pattern `inplay_evidence` already uses.
- **Proportional sizing as the baseline.** Rejected: leader equity is almost always unknown for public wallets.
  The baseline is fixed risk per signal.
- **Dedupe by transaction hash.** Rejected: one transaction can hold several fills, and v2 rows carry no per-fill
  id.

## Tradeoffs

- Conservative semantics make many real numbers UNKNOWN. A Polymarket v2 row has no fee or itemized split/merge
  legs, and finality is not documented, so live data will often yield gross-only or unknown P&L. That is the
  intended result, not a defect.
- Identical rows inside one retrieval stay distinct by occurrence. An overlapping re-retrieval in a *different*
  order still dedupes correctly, because occurrences count identical content. A source that drops one of two
  identical rows between retrievals cannot be told apart from a correction, and that limit is recorded as
  `INDISTINGUISHABLE_DUPLICATE_ROWS`.
- Co-trading clusters are heuristics with fixed windows. They can merge independent traders who react to the same
  news, and that over-merging is the safe direction.
- The follower simulator has no queue position, maker fills or latency distribution. It takes visible depth only.
- Synthetic data proves engineering only. No result here says anything about any real trader or edge.

## What would make us reconsider

- An approved live read (W10) shows v2 rows with a per-fill id, a fee or finality. Identity, fee and finality
  handling would then tighten.
- A real dataset shows the semantic-plus-occurrence identity colliding or splitting.
- The execution bridge (W8) needs a different signal contract.
- The #96 slot review chooses an empirical evaluation. Its protocol would then freeze thresholds and log evidence
  use through `research_evidence`.
- A provider documents Hyperliquid or DEX account history that is public and rights-cleared. The matrix verdicts
  would then change.
