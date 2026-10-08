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

## Amendment 2026-10-07: independent review F1–F8

An independent review returned REQUEST_CHANGES. Each fix has a regression test in
`tests/wallet/test_wallet_review_fixes.py` that fails on the earlier code.
- **F1:** a conflict excludes an observation only from views at or after its detection, so a past
  `select_at` is reproducible after newer data arrives.
- **F2:** the leader's per-unit outcome ignores leader trades after the horizon.
- **F3:** `policy.signals_from_log` builds each signal from the identity's version as known at our observation
  time, and the demo uses it. A later retraction or reorg never removes a signal we acted on, and
  `replay.leader_event_status` flags such fills without removing them. The §20 #9 test re-runs the replay after
  the correction. `ObservationLog.version_at` is the single-identity view.
- **F4:** an event with any open or UNKNOWN market is UNKNOWN in event outcomes, wins and the prior.
- **F5:** the owner ruled on 2026-10-07 that published API specification and documentation files count as
  documentation even when served from the API host; data routes stay forbidden. Pins cite docs.polymarket.com
  where a page states the fact, and the OpenAPI spec otherwise, with the ruling noted.
- **F6:** the leader-exit skip uses exits observable at decision time.
- **F7:** after an UNKNOWN request outcome a run makes no new entry and no further request on that token, and
  the ladder's `filled` is None.
- **F8:**
  - the transitive boundary check applies every rule to each owner reached, and is mutation-probed;
  - rate limits are documented (P24);
  - Benjamini-Hochberg uses m = cumulative trials × candidates.

## Amendment 2026-10-07 (pre-merge re-review): R1–R3

The re-review approved `070eb51` with one fix and two documentation notes.
- **R1:** `signals_from_log` recomputes a signal's observable time from the version actually chosen. The time
  is moved later until it is at least that version's trade time plus the detection delay and its receipt. So
  a correction recorded before we could see a trade, which moves the trade later, re-times the signal instead
  of making it invalid. A record that still cannot become a valid signal is left out, with its reason in an
  optional `skipped` list. One bad record never denies the run. Regression test in
  `tests/wallet/test_wallet_review_fixes.py`.
- **R2:** the F2 horizon cut-off uses the leader's **trade time**, not observability. Leader economics are what
  the leader's account earned inside the window; our detection delay cannot change them. A sale before the
  horizon that we saw only after it still ends the leader's holding. Observability governs only the follower's
  timeline.
- **R3:** leaving events with an unknown market out of the trials can flatter a reported win rate, since the
  unknown events may be losers. The rate is a rate over known events only, and `unknown_markets` reports how
  much is missing. Eligibility does not rest on the rate: it rejects any account with an unknown market
  (`UNKNOWN_MARKETS`) and any with incomplete coverage.

## Amendment 2026-10-08 C: price-relative skill

Authority: the 2026-10-08 owner directive (`docs/owner/2026-10-08-jev-crawler-wallet-directive.md`) and its
scope entry in `docs/EXECUTION_PLAN.md`, item C. Specification: Deliverable C of
`docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md`; issues #181 and #168. Offline, SYNTHETIC fixtures only.

**Problem.** A win rate is not skill on binary contracts. 98 wins in 100 one-contract YES entries at $0.99 cost
$99 and pay $98, a $1 loss. The 50%-null binomial screen (`stats.binomial_tail_p`, used by
`selection.multiple_testing`) flags that record at p < 1e-26. The screen is kept unchanged, with its label: a
small-sample screen, not alpha.

**Decision.** Add a new subordinate module, `wallet_intel/skill.py` (`wallet-price-relative-skill-v1`). It is
opt-in: nothing else calls it. It gets its own module for two reasons:
- `stats.py` is float-only by rule;
- `accounting.py` owns leader economics.

The diagnostic needs Decimal position economics, a typed exclusion taxonomy and a dependency closure, and these
belong in neither. Three float-only helpers are added to `stats.py`: `price_benchmark_null_p`,
`kish_effective_size` and `shrink_toward_zero`. `accounting.py` is unchanged, and its tests pin its outputs.
- **Benchmark.** Each position is measured against the market entry price. `reference_payout` is quantity ×
  entry price, the benchmark's expected payout. `gross_excess` is payout − reference payout. For a
  held-to-resolution position this equals the realized gross P&L from `accounting.reconstruct`, and a test pins
  the two together, so there is one P&L concept, not two. `net_excess` exists only when every fee is known. An
  unknown fee makes it UNKNOWN, never zero. The price is a benchmark, not the true probability. Excess may come
  from forecasting, maker price improvement or a risk premium. The liquidity role is reported beside it, and is
  UNKNOWN unless role evidence is supplied.
- **Eligibility.** Only unambiguous held-to-resolution binary positions count. Every other position is
  classified with a `PositionStatus` and carries no number:
  - an unverified identity (`IdentityBasis.HEURISTIC` or missing) or incomplete history;
  - a token transfer, a split, merge or conversion, or any sale (an early or mixed exit);
  - both outcomes held (a visible hedge);
  - an UNKNOWN action or a non-binary outcome;
  - entry cash that does not equal quantity × price exactly;
  - an unresolved market, a payout other than 0 or 1, or a redemption that does not match the payout;
  - in a holdout, a position that overlaps selection or falls outside the window.

  Hedges elsewhere are unobservable, so `hidden_hedges` is always UNOBSERVABLE.
- **Dependence.** Positions cluster by `event_id`. The report gives the cluster count, Kish's effective size over
  cluster cost, concentration (the largest cluster's cost share) and a cluster-bootstrap band. The null p-value
  is a seeded Monte Carlo under the price benchmark. Outcomes inside a cluster are **comonotone**, which is the
  largest variance those marginals allow. So 20 correlated wins on one event weigh as one coin flip, not 20.
- **Shrinkage.** The excess return per dollar is shrunk toward zero excess with `pseudo_clusters`
  (value × n / (n + k)).
- **Multiple testing and denominators.** Every cohort account is a hypothesis: winners, losers, inactive
  accounts and accounts with no eligible position (p = 1). Benjamini-Hochberg uses m = max(1, trials) × cohort
  size.
- **Verdicts.** The verdicts are NO_ELIGIBLE_POSITIONS, INSUFFICIENT_EVIDENCE (coverage or effective clusters
  below the rule), NEGATIVE, HINDSIGHT_FLAGGED, NOT_DISTINGUISHABLE_FROM_BENCHMARK and POSITIVE_SCREEN. A positive
  verdict also needs a positive shrunk estimate and a survivor of Benjamini-Hochberg. It is blocked when net
  excess is known and not positive. When net is UNKNOWN, `verdict_basis` says GROSS_ONLY_NET_UNKNOWN. A
  POSITIVE_SCREEN is a screen on one window and never proves persistence.
- **Point in time.** `SkillRule` carries `frozen_at`. A `HOLDOUT` raises `HindsightError` when the rule was
  frozen, or the cohort selected, after the window opened. It counts only positions entered after selection
  inside the window. `check_holdout_sequence` refuses overlapping windows or a changed rule. In `DESCRIPTIVE` mode
  an account selected after a counted outcome is flagged SELECTED_AFTER_OUTCOMES and cannot receive a positive
  verdict. Future marks or observations raise.
- **Dependency closure.** `SkillClosure` is a plain frozen value with canonical text for every input that shaped
  the report:
  - the full rule, every threshold included;
  - mode, as-of time, window and cohort (time, reference and every account);
  - trials and the data label;
  - each observation's id, semantic key and receipt time;
  - every mark;
  - identity bases, history flags and roles;
  - per-account coverage.

  Its digest is insensitive to input order. Deliverable A's v2 receipt can bind to `closure.digest`.

**Required fixtures (SYNTHETIC, `tests/wallet/test_wallet_skill.py`).**
1. 98/100 at $0.99: −$1 gross, NEGATIVE, while the binomial screen flags it.
2. 16/40 at $0.20: +$8, POSITIVE_SCREEN, and the binomial screen does not flag it.
3. A market-matched null: NOT_DISTINGUISHABLE_FROM_BENCHMARK.
4. 20 contracts on one event: effective size 1, INSUFFICIENT_EVIDENCE.
5. A hindsight-selected winner: refused in a holdout, HINDSIGHT_FLAGGED in a description.
6. An unknown fee: net UNKNOWN, never zero.

There are 23 deliberate mutations, and each one fails a test. Synthetic successes are unit tests, not observed
alpha.

**Alternatives considered.**
- **Replace the binomial screen.** Rejected: the directive keeps it, and side-by-side output shows the
  difference.
- **A normal-approximation z-test.** Rejected: it is poor at prices near 0 or 1, and it ignores dependence.
- **Independent outcomes inside an event.** Rejected: that overstates evidence (mutation M04).
- **Computing positions through `reconstruct`.** Rejected: its market states mix exits, transfers and opens.
  The skill needs a stricter, typed exclusion taxonomy, so it reuses only `Mark` and pins agreement by test.

**Tradeoffs.**
- Strict eligibility makes most real accounts mostly ineligible, because Polymarket v2 rows have no fee, so net
  is UNKNOWN. That is intended.
- Comonotone clusters are conservative for mutually exclusive brackets.
- Kish's size uses cost weights, not risk.
- The entry fill price is the only reference. A captured quote at entry, to separate maker price improvement
  from forecasting, needs book-at-entry evidence that is not modelled here.

**What would make us reconsider.**
- Lane B lands a typed `liquidity_role`. The skill should then read it instead of a caller-supplied mapping.
- An approved empirical evaluation freezes thresholds in a `protocol.toml`.
- Real data shows event ids that are missing or too coarse to cluster on.
