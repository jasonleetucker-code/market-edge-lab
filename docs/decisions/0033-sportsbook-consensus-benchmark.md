# ADR 0033: Sportsbook consensus research benchmark and per-domain research readiness

**Status:** Accepted 2026-09-24. Authority: `docs/owner/2026-09-24-freshness-fabric-sports-directive.md`
(sections "Sportsbook consensus research layer (#9)" and "Sports prospective history (#50)"; coordinator
contract C3) and the matching `docs/EXECUTION_PLAN.md` entry. Research only: it authorizes no order, no
credential, no paid call and no schedule. It spends no Odds API credit and makes no network call.

## Problem

1. **Consensus (#9).** The Odds API pilot stores sportsbook offers (ADR 0029). A later sports study needs
   to know what the books, taken together, implied at each scheduled horizon. That needs a deterministic,
   versioned benchmark that never passes for a price. `odds_api.consensus_by_market` already existed, but:
   - it grouped spreads by the *absolute* line text, so `"-2.50"` and `"2.5"` failed to pair;
   - Home -3 / Away -3 (not opposite lines) could pair;
   - it de-vigged a draw or three-way h2h as if it were two-way;
   - it had no dispersion, freshness, update-time bounds, point-in-time reads, versioned hashes or
     artifact.
2. **Readiness (#50).** "Is this domain's learning history complete enough to research?" was answered by
   hand in `docs/research/LEARNING_HISTORY_COVERAGE.md`. A hand-written status goes stale. It also invites
   hard-coded green.

## Decision

### Consensus: one canonical owner, two layers

- **Math in `edge_lab.odds_api`** (its consensus section): `pair_offers`, `group_propositions`, `median`,
  `median_absolute_deviation`, `CONSENSUS_VERSION`. `consensus_by_market` now runs on the same pairing,
  so there is one consensus engine, not two. The legacy per-book `devig_by_market` is kept as a
  whole-set view. Its absolute line is now normalized. The benchmark does not use it.
- **Benchmark in `edge_lab.odds_consensus`:** point-in-time reads of stored snapshots, frozen result
  types, freshness, update bounds, hashing, the artifact and the CLI.

### Math

For one book, one event, one market and one exact line:

- **Offered price:** the raw price text exactly as received, its odds format (from the stored request
  context or the stored redacted URL; never inferred from the prices) and the decimal conversion.
- **Implied probability:** `1 / decimal`, which still contains the book's margin. The two sides sum to
  `1 + overround`.
- **Paired de-vig (proportional, `proportional_two_way_v1`):** `p_i = (1/d_i) / (1/d_a + 1/d_b)`.
  It is computed only for a **clean two-sided complement**:
  - h2h: exactly two outcomes, no draw or tie, no line. When the response names the home and away
    teams, the outcomes must be those two teams;
  - spreads: (team A, L) with (team B, -L), exactly opposite after normalization. `"-2.50"` equals
    `-2.5`, and a pick'em `0` / `-0.0` pairs;
  - totals: (Over, L) with (Under, L).
- **Proposition:** the two sorted (outcome, normalized line) pairs. Books are pooled only on an
  identical proposition, so -2.5, -3 and -3.5 are three propositions. Lines are never combined or
  interpolated.
- **Consensus probability:** per outcome, the **median** of the contributing books' paired de-vigged
  probabilities. For an even count it is the mean of the two middle values. For a two-way proposition
  the two medians are complements, so they are not renormalized. Decimal arithmetic runs at 28
  significant digits (ROUND_HALF_EVEN), so a sum can differ from 1 in the last digits.
- **Dispersion (`range_and_unscaled_mad_v1`):**
  - **range** = max − min;
  - **MAD** = median(|p − median|), unscaled: no 1.4826 normal-consistency factor.

  The IQR was not chosen: with 2–8 books its quartile definition is ambiguous.
- **Counts:**
  - `contributing_book_count`: books that paired this exact line;
  - `market_bookmaker_count`: books that quoted this market for the event at any line.

  A book that is absent or quoted another line is not a zero.
- **Minimum:** one book is `INSUFFICIENT_BOOKS`. Its de-vig is shown, but no consensus probability
  (None, never a copy of the one book). This is definitional, not a strategy threshold.

### Exclusions (UNSUPPORTED, with a reason code; the offers are kept and shown)

| Code | When |
|---|---|
| `NOT_TWO_WAY` | h2h with a draw/tie or three or more outcomes. Three-way math is not implemented |
| `MISSING_COMPLEMENT` | no exact opposite side at this line from this book (includes Home -3 / Away -3, or Over 44.5 / Under 45.5) |
| `AMBIGUOUS_COMPLEMENT` | a side or line listed more than once by one book |
| `INVALID_LINE` | non-numeric line, a line on h2h, or no line on a spread or total |
| `INVALID_PRICE` | either side lacks a valid quote. The pair is not de-vigged |
| `UNRECOGNIZED_OUTCOME` | a totals name other than Over/Under, or a team that is not the event's |
| `MARKET_NOT_SUPPORTED` | any market key other than h2h, spreads or totals (e.g. `h2h_lay`, alternates, props) |

The snapshot also fails closed, with a problem and no events, when:
- the stored payload no longer matches its stored `payload_sha256`;
- the odds format is not stated;
- the stated formats disagree.

### Freshness and update-time bounds

- **Per book:** the market `last_update`, or the bookmaker's when the market has none. It is judged
  against the registry's odds max age (10 minutes) **at the snapshot's receipt time**. A missing or
  unparseable timestamp is UNKNOWN. A timestamp more than 5 minutes after receipt is also UNKNOWN (a
  clock problem, `freshness.assess`).
- **Per proposition:** the worst of its books (`freshness.combine`), and separate earliest and latest
  bounds for the market and bookmaker `last_update`, each with known and unknown counts.
- **Point-in-time reads:** they add `freshness_as_of`, the receipt time judged at `as_of`.

### Point in time

A consensus as of T uses only snapshots **received at or before T**. A snapshot with an unknown
receipt time is never "known by T". `consensus_for_snapshot(..., as_of=T)` on a later snapshot raises
`PointInTimeError`. Ordering is by parsed receipt instant, never by text.

### Versioning and hashes

- `CONSENSUS_VERSION = "odds-consensus-v1"`. Any change to the math, the pairing, the exclusions, the
  minimum or the freshness rule bumps it.
- `input_sha256`: a hash of the version, the pairing and dispersion methods, the minimum, the odds max
  age, the snapshot id, its stored `payload_sha256`, its receipt time and its odds format.
- `output_sha256`: a hash of the derived content, excluding the as-of fields.
- `artifact_sha256`: a hash of the CLI artifact.

The same inputs give byte-identical output.

### Labels and separation

- Every consensus result carries `label = "RESEARCH BENCHMARK — NOT EXECUTABLE"` and `executable = False`.
- `OfferedPrice` (quote as received) and `OutcomeConsensus` (probability) are different types with
  disjoint fields. No price field holds a probability, and no probability field holds a price.
- The module has no fetch, quota, order, ledger or `ExecutableQuote` path (a test pins this).

### Readiness (`edge_lab.research_readiness`, the one owner)

Per domain (weather = EXP-001; sports = the NFL Odds API pilot plus the Polymarket US lane), each
prerequisite is YES / PARTIAL / NOT_YET / UNKNOWN, or NOT_APPLICABLE by design. It comes with the
evidence count and the reason. The prerequisites: raw evidence, market/quote history, model estimate,
decisions (rejected included), later price, consensus, and settlement/outcome linkage.

- Every state is computed from the evidence store and the shadow ledger (both opened read-only) and the
  experiment registry file.
- A missing, unreadable or unspecified store makes its items UNKNOWN.
- Zero evidence is NOT_YET, some is PARTIAL, and YES needs every counted item.
- `research_ready` is YES only when every applicable prerequisite is YES.
- Weather's lifecycle is the registry's EXP-001 status. Sports' lifecycle is derived from its evidence
  (NO_EVIDENCE_YET or DATA_COLLECTION). The directive's example states are not hard-coded.
- The gap ids (P0-1, P1-1, P1-5, P2-6) are those of `LEARNING_HISTORY_COVERAGE.md`.

### Surfaces

- `edge-lab odds consensus --db … [--snapshot ID | --since ISO | --event ID] [--as-of ISO] [--out path]`.
- `edge-lab readiness report --db … [--ledger …] [--text]`.

Both are read-only and network-free. The Terminal (Lane D, contract C4) calls
`odds_consensus.consensus_for_event` / `consensus_series_for_event` / `consensus_for_snapshot` and
`research_readiness.build_report`, and only formats their results.

## Why no sharp-book weighting

- Weighting books by "sharpness" is a model with parameters: which books, what weights, and how they
  were fitted. Fitting it on the same history it is later judged against is exactly the
  multiple-testing trap `docs/RESEARCH_PRINCIPLES.md` warns about.
- The directive forbids it for this layer.
- The unweighted median is robust to one outlying book and has no free parameter.

A weighted consensus belongs in a preregistered experiment with its own version.

## Alternatives considered

- **Mean instead of median.** Rejected: one stale or off-market book moves it.
- **Multiplicative "power" or Shin de-vig.** Deferred. Proportional is the simplest, parameter-free
  standard. Another method would be a new `PAIRED_DEVIG_METHOD` and a version bump, never a silent
  swap.
- **A second engine inside `odds_consensus` and leaving `consensus_by_market` as it was.** Rejected: that
  would be two consensus definitions (one concept, one owner).
- **Persisting consensus rows in a new table.** Rejected: the derived artifact is reproducible from
  immutable snapshots plus versioned code, and a table would be a second history.
- **A hand-maintained readiness table.** Rejected: it would drift and could be green by assertion.

## Tradeoffs

- The median of an even count is a midpoint that no single book quoted. That is acceptable for a
  benchmark, and it is stated.
- Readiness counts are coarse. For example, "later price" for weather counts decided markets with any
  captured later phase. The counts are shown so a reader can judge.
- Recently decided markets and events that are not yet due keep items PARTIAL. It is conservative on
  purpose.
- The benchmark parses every stored odds snapshot on demand. At pilot volumes (tens of snapshots a week)
  this is cheap. At much higher volume it would need an index or a cache keyed by `input_sha256`.

## Reconsider when

- A three-way market (soccer, or NFL with ties as an outcome) becomes a research target: add explicit
  three-way math and a version bump.
- A preregistered experiment needs weighting, a different de-vig, or alternate lines.
- Snapshot volume makes on-demand parsing slow: add a derived cache keyed by `input_sha256`.
- Polymarket US or scores capture changes what counts as market or outcome history for sports.
- `LEARNING_HISTORY_COVERAGE.md` adds a prerequisite or a domain.
