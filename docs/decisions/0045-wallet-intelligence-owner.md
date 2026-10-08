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

## Amendment 2026-10-08 B: role-aware quality diagnostics

**Authority.** Deliverable B of the 2026-10-08 owner directive (`docs/owner/2026-10-08-jev-crawler-wallet-directive.md`,
scope in the 2026-10-08 entry of `docs/EXECUTION_PLAN.md`; spec `docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md`).
Offline, SYNTHETIC fixtures only. It authorizes nothing beyond that.

**Problem.** `threats.off_market_fills` (W7) compares a buy to the best ask and a sale to the best bid. A
legitimate passive fill therefore reads OFF_MARKET. Regression fixture: bid 0.45, ask 0.55, a maker BUY at 0.45.
That print is ordinary. It is not evidence of manipulation, and it does not mean a follower can buy at 0.45.

**Decision.** `threats.py` reports four separately typed concepts. They are never merged into one score.

1. **`liquidity_role`** (MAKER / TAKER / MIXED / UNKNOWN). It is an optional `WalletObservation` field, set only
   with `liquidity_role_source`, the source field or explicit fixture that states it. It is never inferred from
   the side of the spread. `events.combined_role` gives the role of several fills of one order. A mix of maker
   and taker fills is MIXED, and any unknown fill makes the whole UNKNOWN.
2. **`price_consistency`** (CONSISTENT / INCONSISTENT / INSUFFICIENT_EVIDENCE). Could the captured book have
   produced the print for the stated role?
   - A taker buy must be at or through the ask, and within the captured asks unless that side is truncated.
     Sales mirror this.
   - A maker buy must not be above the ask. Below the best bid, it is INSUFFICIENT_EVIDENCE: only a sweep the
     capture cannot show reaches it.
   - With an UNKNOWN or MIXED role, the print is CONSISTENT when either role explains it, and the row names that
     role (`consistent_roles`). It is INCONSISTENT only when every role contradicts the book.
   - The following are always INSUFFICIENT_EVIDENCE, never cleared:
     - missing price;
     - unknown price unit, or a price outside (0, 1);
     - a price that disagrees with the cash leg;
     - an observation received before its stated trade time (beyond `max_clock_skew`);
     - an invalid capture (a crossed or locked book cannot be built);
     - no book;
     - a book captured after the trade, or less than `max_clock_skew` before it;
     - a book older than `max_book_age` once the skew is added.
   - Each row carries provenance: the observation's source, raw reference and parser version, the role source,
     and the book's optional `source`, `raw_ref` and `received_at` (new optional `Book` fields).
3. **`contamination_evidence`.** `ContaminationEvidence` rows have a status (PROVISIONAL_FLAG, NO_FLAG or
   UNOBSERVABLE), an observability (OBSERVED, PARTIAL or UNOBSERVABLE), an evidence kind and uncertainty notes.
   Every flag is provisional and must state `NOT_PROOF_OF_COMMON_OWNERSHIP_OR_WRONGDOING`. The detectors are:
   - shared activity, the evidence behind `co_trading_clusters`, whose output is unchanged. A public event
     just before the trades is recorded as an alternative explanation.
   - stated funding links.
   - churn. Its flag notes when the round trips are maker fills, which is what market making looks like. It also
     notes unknown roles and token transfers.
   - self-trades and circular token flows, built only from source-reported counterparties (a new optional
     `counterparty` field with its source). With no reported counterparty these two detectors are UNOBSERVABLE,
     not clean.
4. **`follower_copyability`** (COPYABLE / PARTIALLY_COPYABLE / NOT_COPYABLE / UNKNOWN / NOT_ATTEMPTED). It is
   read from `replay.replay`'s outcomes and fills. It is not a second fill engine.
   - A missing, stale or future book, or an UNKNOWN request outcome, is UNKNOWN, never NOT_COPYABLE and never a
     fill.
   - A policy skip is NOT_ATTEMPTED and stays in the denominator.
   - The verdict carries:
     - the follower's simulated average price and per-unit gap to the leader (ESTIMATED);
     - the fee as replay labelled it;
     - our decision and arrival times;
     - the age of the book at arrival, when a provider is given (otherwise unknown, not zero).
   - The leader's price consistency is carried alongside and never used to decide. Lane D owns the full
     follower-replay study.

**Versions.** `off_market_fills` is kept unchanged as v1 (`wallet-off-market-v1`, role-unaware), with
`off_market_report_v1` and an explicit interpretation note. The v2 report is `quality_report` →
`wallet-quality-diagnostics-v2`, which carries a `DataClass` (SYNTHETIC, FIXTURE, OBSERVED or UNKNOWN). Synthetic
observations cannot be reported as OBSERVED. `read_threat_report` dispatches on the schema. v1 reads back as
`LegacyOffMarketView(role_aware=False)` and is never upgraded, because it has no role to upgrade with. An unknown
schema is refused.

**Compatibility.** The new `WalletObservation` and `Book` fields are optional and default to UNKNOWN or None. They
are outside the v1 semantic identity, so no observation id, semantic key, selection digest or demo report
changes. Tests pin the Polymarket fixture identities, the v1 manifest digest and the demo `report_sha256` captured
on `c34221c`.

**Tradeoffs and limits.**
- **Annotations are outside the identity.** Re-receiving a fill with a role its first receipt lacked counts as a
  duplicate, and the first receipt is kept. A later identity schema could bind the role. That needs coordination
  with the selection receipts (Deliverable A).
- **The maker case rests on the capture.** A maker print below the bid is INSUFFICIENT_EVIDENCE, not INCONSISTENT.
  So a cheap allocation with an unknown role is no longer flagged OFF_MARKET by v2. It is not cleared either.
  The v1 screen still reports it.
- **Some current inputs carry no role or counterparty.** The Polymarket v2 trades rows carry `maker_volume` and
  `taker_volume`, but the parser does not yet map them to a role. Until it does, every parsed row is UNKNOWN.

**Seams.** `replay.py` and `polymarket_v2.py` are not changed here:
- `FollowerFill` does not record the `captured_at` of the book it filled against, so copyability re-reads the
  provider at arrival time to report book age.
- `FollowerFill.reason` is free text. Copyability matches its documented prefixes, and a typed no-fill reason
  would be safer.
- `replay._execute` lets a provider's `ValueError` (an invalid, crossed capture) propagate and abort the run,
  where it could record NO_FILL / UNKNOWN for that signal.

**What would make us reconsider.** A real source documents a per-fill maker or taker flag, or counterparties. The
maker sweep rule could then use the trade tape. Separately, the follower study (Deliverable D) may show that
copyability needs queue position, which the canonical replay does not model.
