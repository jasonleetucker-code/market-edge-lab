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

## Amendment 2026-10-08 A: v2 causal receipts

Authority: the 2026-10-08 owner directive (`docs/owner/2026-10-08-jev-crawler-wallet-directive.md`), item A of its
scope entry in `docs/EXECUTION_PLAN.md`, and `docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md` Deliverable A.
Offline and fixture-only. Revised after the independent review of `dccc88a` (REQUEST_CHANGES: H2, M1, L1-L7).

**Problem.** A static audit of `select_at()` (reproduced by `test_audit_v1_digest_does_not_bind_these_causal_inputs`)
found that the v1 `inputs_digest` binds the cutoff, label version, rule id and version, candidates, observation ids
and marks. It omits every rule threshold, `require_complete_coverage`, `history_complete`, `threat_flags`,
`mark_max_age`, the discovery source, `trials`, observation contents, correction and conflict state, mark depth,
source and receipt time, and the engine's implicit parameters (`selection.LEGACY_V1_UNBOUND`). Two selections that
could decide differently can share one v1 digest. That is incomplete causal input binding, not a hash collision.

**Decision.** A new subordinate module, `wallet_intel/receipts.py`, builds a v2 receipt
(`wallet-selection-receipt-v2`) over the one eligibility engine, `selection.decide`. `select_at` keeps its v1
digest unchanged (so persisted v1 records stay as they were) and now calls the same engine.
- **Typed inputs** (`SelectionInputsV2`). `CoverageAssertion` (complete / partial / UNKNOWN, with source, method
  version, knowledge time and evidence reference). `FlagAssertion` (THREAT or QUALITY, with codes, or `None` when not
  assessed). `MarkEvidence` (a `Mark` plus quote basis, source, receipt time and evidence reference). `TrialBasis`
  (count, source and the digests of the earlier receipts it counts). An optional `IdentityRegistry`. `fdr_q`, the
  Benjamini-Hochberg q of the receipted multiple-testing screen.
- **Point in time.** Every input is filtered by its knowledge time: candidates by `discovered_at`, observations
  by `ObservationLog.as_known_at`, corrections by `recorded_at`, conflicts by detection time, assertions by
  `known_at`, marks by `received_at` and identity records by `observed_at`. The latest assertion per account (or
  per account, kind and source) and the latest mark per instrument known by the cutoff is in force. A tie with
  different content raises `AmbiguousInputError`.
- **Post-cutoff information fails closed rather than leaking.** Filtering alone is not enough when the log was
  backfilled out of receipt order, so the build refuses (`BackfillOrderError`):
  - a conflict detected before the first receipt of an identity it names, or naming a version received after the
    cutoff;
  - an effective observation or a correction's replacement whose `receipt_time` is after the cutoff (an
    out-of-order duplicate would otherwise bind a post-cutoff `receipt_time` and `raw_ref`);
  - corrections to one identity appended out of knowledge order, `(recorded_at, correction_id)`.
  `verify` applies the same receipt-time and conflict-order checks to a persisted closure (CAUSALITY_VIOLATION).
  An honest build therefore either binds only what was known by the cutoff or does not build.
- **Closure** (`wallet-selection-closure-v2`). It holds:
  - every effective rule field, with canonical Decimal text, exact binary64 text for the float threshold (a
    Decimal there is refused), microsecond durations and a `rule_units` table;
  - the mark freshness tolerance and the multiple-testing `q`;
  - the engine binding: versions, implicit parameters and the SHA-256 of each engine module's source (`selection`,
    `stats`, `threats`, `accounting`, `events`, `exact`, `identity`, `market_data`, `timeutil`, `provenance`,
    `receipts`), read at call time with CRLF normalized to LF;
  - the trial basis;
  - per candidate: every discovery known by the cutoff (the first one leads), the identity snapshot (UNKNOWN
    without a registry), the coverage and flag assertions in force, and the history. The history holds each
    identity's first receipt, status (EFFECTIVE, WITHDRAWN or CONFLICTED) and the conflict keys behind a
    CONFLICTED status, corrections numbered per target in knowledge order `(recorded_at, correction_id)`, the
    conflicts, and the full content and SHA-256 of every effective observation;
  - the mark in force per instrument.
  Unordered collections are stored sorted and unique, so a permutation of inputs gives the same digest.
- **Digests.** `closure_digest` is the v2 selection digest. `outcome_digest` covers the records, the prior, the
  denominators (visible candidates and counts by status, so inactive and rejected wallets stay counted) and the
  multiple-testing result. `receipt_digest` covers both plus the downstream slots. Hashing reuses
  `provenance.canonical_json` and `sha256_hex`; there is no second scheme.
- **Fail closed.** A visible candidate with no log, no coverage assertion or no THREAT assertion in force raises
  `MissingInputError`. A float money threshold or a bare `Mark` without evidence is refused. An unknown coverage
  or an unassessed screen is recorded as UNKNOWN and makes the candidate ineligible (`COVERAGE_UNKNOWN`,
  `THREAT_UNASSESSED:<source>`). A dataclass field without a canonical encoding stops the build, so a new field
  cannot silently escape the digest. This guard covers `AccountRef` and `AssetAmount` too.
- **Strict decoding.** Every part of a persisted closure is decoded with exact types and canonical spellings and
  compared by canonical JSON, never by Python equality (`5 == 5.0`, `0 == False`). Timestamps must be the canonical
  `utc_text` spelling. Conflict records are typed (kind, key, a sorted pair of semantic keys or canonical times).
  CONFLICTED statuses and conflict records must name each other exactly. One closure has one serialization and
  one digest.
- **`rebuild` / `verify` / `load_receipt`.**
  - `rebuild(record)` decodes the closure from the record alone and refuses it (`EngineMismatchError`) when the
    loaded engine differs from the one it names. It then re-runs the engine and re-hashes.
  - `verify(record, inputs=None)` never raises. It returns VERIFIED or exactly one of LEGACY_INCOMPLETE, MALFORMED,
    TAMPERED, ENGINE_MISMATCH, CAUSALITY_VIOLATION, REPLAY_MISMATCH or SOURCE_MISMATCH. A code change in any
    engine module is ENGINE_MISMATCH, not REPLAY_MISMATCH.
  - **`verify(record)` without inputs proves internal consistency only.** Someone who rewrites a closure and
    recomputes every digest also passes it. The `receipt_digest` must therefore be pinned somewhere else (a
    ledger row, a PR, a report). `verify(record, inputs=...)` rebuilds from the sources and reports such a
    consistent forgery as SOURCE_MISMATCH; sources that do not build are SOURCE_MISMATCH too.
  - A v1 record verifies as LEGACY_INCOMPLETE, and `load_receipt` / `rebuild` raise `LegacyReceiptError`. v1 is
    never upgraded, and its `to_dict` now carries `replayability: LEGACY_INCOMPLETE`.
- **Downstream extension point.** `DownstreamSlot.PRICE_RELATIVE_SKILL` (Deliverable C) and
  `DownstreamSlot.FOLLOWER_REPLAY` (Deliverable D) start NOT_BOUND. `bind_downstream` attaches a
  `DownstreamBinding`. A binding holds a schema id, the selection's `closure_digest`, a plain-JSON closure with
  Decimals and times already canonical text, and optionally the downstream report's digest. The closure must name
  the same selection under its slot's key (`SLOT_SELECTION_REF`: `cohort_ref` for C's `SkillClosure`,
  `selection_ref` for D). Its digest uses the same scheme, so it equals the report's own closure digest. The
  binding is hashed into `receipt_digest` only, so the dependency stays one-way. A bound slot is never replaced by
  a different closure.

**Tests** (`tests/wallet/test_wallet_receipts.py`, `test_wallet_selection.py`):
- Every field of every bound type has a mutator, enforced against `dataclasses.fields`. Each mutation changes the
  closure digest or fails closed.
- A meta-test drops each field from the encoding in turn and proves its mutation test would then fail. The
  exceptions are fields also bound elsewhere, or that fail closed regardless, each listed with its reason.
- The reviewer's three reproductions are tests: an out-of-order conflict, an out-of-order duplicate and corrections
  appended out of `recorded_at` order. Each fails closed when backfilled out of order, and leaves the receipt
  unchanged otherwise.
- Other tests cover:
  - post-cutoff `receipt_time` and conflict-order tampering (CAUSALITY_VIOLATION);
  - each M1 case (MALFORMED);
  - unusable `inputs` (SOURCE_MISMATCH), and `verify` never raising;
  - an engine source change (ENGINE_MISMATCH; `rebuild` refuses it);
  - per-slot downstream references, the receipted multiple-testing screen, and the Decimal float threshold;
  - permutation invariance, post-cutoff additions, pre-cutoff versus post-cutoff corrections and conflicts,
    missing and ambiguous inputs, denominators, the JSON round trip, each verify failure, v1 legacy handling,
    and v1/v2 engine parity.

**Alternatives considered.**
- *Widen the v1 digest in place.* Rejected: it would silently change what persisted v1 digests mean.
- *Store only hashes of observations.* Rejected: `rebuild` must re-run from the record alone.
- *Re-derive the effective view from raw entries during rebuild.* Rejected: it would be a second copy of the
  correction semantics. Instead, the build uses the canonical owner (`ObservationLog.version_at` /
  `as_known_at`), and the record binds both the per-identity statuses and the effective contents.
- *Treat missing coverage or flags as clean* (the v1 default). Rejected: unknown must stay unknown.
- *Re-order out-of-order corrections inside receipts.py.* Rejected: it would be a second correction semantics.
  The receipt refuses the log instead; the `events.py` owner fixes the order at the source (lane B).

**Tradeoffs.**
- Receipts are large, because they embed effective contents.
- The engine source digest makes every edit to an engine module, even a comment, an ENGINE_MISMATCH for older
  receipts. That is deliberate: a receipt states exactly which code decided it.
- Until lane B's `events.py` change (point-in-time views as a pure function of copies received by the cutoff,
  corrections applied in `(recorded_at, correction_id)` order) lands, a log backfilled out of receipt or knowledge
  order makes the build fail closed instead of producing a receipt. After it lands, the corrections guard can relax
  to an agreement check (tracked as H1).
- The demo still shows the v1 manifest, labelled LEGACY_INCOMPLETE in its data. The Terminal
  (`dashboard/views/ops_wallet.py`) does **not** yet display that label: labelling is planned in Deliverable G,
  which owns the dashboard.
- Synthetic fixtures prove engineering only.

**What would make us reconsider.**
- Lane B's order-independent `events.py` (H1: bind the new optional observation fields and relax the corrections
  guard).
- Lanes C or D needing a selection-closure input rather than a downstream binding. That would be a v3 closure,
  never an edit of v2.
- A real dataset where embedded contents make receipts impractically large. We would then consider
  content-addressed storage of observations, with the same digests.
