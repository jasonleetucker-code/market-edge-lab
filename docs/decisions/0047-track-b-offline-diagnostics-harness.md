# ADR 0047: Track B offline diagnostics harness (calibration, executable entries, bankroll, depth)

**Status:** Proposed 2026-10-08 (Track B harness writer, branch `research/tb-harness`). Scope: issue #184,
the 2026-10-08 rapid alpha discovery directive, as narrowed by the scope review of PR #185.

**Offline only.** Pure functions, fixtures and tests. This ADR adds:
- no store read, network call, collector, schedule, credential, model call or deployment;
- no import of `edge_lab.execution`, no new dependency (stdlib only);
- no experiment id, protocol, family slot or evidence-use record.

EXP-001, EXP-002 and EXP-003 are untouched. Family B's mechanism (same-venue complement and partition
sums) and family A's mechanism (sportsbook against executable event-market pricing) are **out of scope**
for Track B (#185 review), so `payoff_constraints.py` is not changed and no complement or partition
checker is added here.

## Problem

The readiness audit for #184 found that no leading Track B candidate can be tested for after-cost profit on
held data, and that the harness has five gaps the first approved data would hit at once:
1. no calibration, Brier score or log loss by price bucket and time to expiry (only EXP-001's private scoring);
2. no maker-fee logic: every fee schedule is taker-only;
3. no parser for Kalshi's last price, volume and open interest;
4. no aggregator for spreads and depth, and no no-trade-filter attrition built on `attrition_report`;
5. no small-bankroll capacity view (fill cost, lock-up, capital-days) over a captured ladder.

## Decision

Extend the canonical owners where the seam exists, and add one sibling module for what has no owner.

| Owner | Added | Why it belongs there |
|---|---|---|
| `fee_schedules.py` | `maker_fee`, `MakerFeeQuote`, `MakerFeeState`, `MAKER_TERMS` | It owns fee schedules and dated verification records. Maker terms are priced only inside a record whose MAKER_FEES component is VERIFIED from a primary source already in the repo (Kalshi KXHIGHNY: 0; Polymarket US: rebate theta 0.0125, banker's rounded). Everything else is FEE_UNSUPPORTED: for other Kalshi series the PDF's maker default (0) conflicts with the 2026-08-20 changelog |
| `kalshi_quotes.py` | `market_activity`, `MarketActivity` | It is the Kalshi market-record adapter. The record is never an `ExecutableQuote` or ladder, so the module's rule ("no last price in any quote") holds. Settled fields (`payoff_constraints.PROHIBITED_MARKET_FIELDS`) are never read, and the last trade is withheld at or after close |
| `research_diagnostics.py` (new) | `Stamp`/`EvidenceClass`; `calibration_report`; `evaluate_entries`; `bankroll_ladder`; `depth_report`; `protocol_guard_problems`; a `calibration` CLI | None of these has an owner. `research_economics` owns episode and fill economics and is already 1,600 lines; this module composes it (`cluster_bootstrap_mean`, `EXECUTABLE_PERFORMANCE`, `ILLUSTRATIVE`) with `opportunity` (depth walk, taker fees), `fee_schedules` and `research_evidence.attrition_report`, and re-implements none of them |

### Rules

- **Evidence class on every output.** SYNTHETIC / FIXTURE / RETROSPECTIVE_EXPLORATORY / PROSPECTIVE, with the
  input sha256, the caller's code version and the harness version. `edge_claim` is always NONE. SYNTHETIC and
  FIXTURE labels say "CODE TEST ONLY ... NOT AN EDGE" in capitals.
- **Governed runs.** RETROSPECTIVE_EXPLORATORY and PROSPECTIVE outputs need an experiment id and an evidence-use
  event id. Rows in a protected label scope (`kalshi:KXHIGHNY`, `sports:nfl:moneyline`, `kalshi:KXNFLGAME`,
  `kalshi:KXNHLGAME`) are refused, by declared scope and by Kalshi series. The CLI also requires the
  experiment's protocol to declare EXP-003's full `prohibited_inputs`, those label scopes and the settled
  `prohibited_fields`, and the event to be in its evidence-use log already.
- **Only a captured ask ladder is fillable.** `ReferencePrice` (MID, LAST_TRADE) is context. Passing one as a book
  raises. Partial and missed fills are explicit; a stale or future-dated book is never priced.
- **Unknown stays unknown.** An unknown fee gives no net (never fee-free). An unknown outcome is counted and
  excluded. An unknown trade size blocks the trade-weighted view only. A one-sided book has an UNKNOWN spread.
- **Clusters, not rows.** Every band is a cluster bootstrap. Every report states clusters beside rows.
- **Attrition.** The detailed `FilterReason` census is primary. `research_evidence.Exclusion` has no fee or spread
  reason, so the coarse waterfall uses a published map (`EXCLUSION_MAP`): FEE_UNSUPPORTED to UNSUPPORTED_PAYOFF,
  WIDE_SPREAD to NO_SIGNAL, SPREAD_UNKNOWN to PARTIAL_EVIDENCE. The shared enum is not changed, because that
  would change every existing waterfall.

## Alternatives

- **Put everything in `research_economics`.** Rejected: it would grow an already large owner with unrelated
  diagnostics, and its import graph (`inplay_evidence`, `opportunity`) is enough for this module to reuse it.
- **Extend `research_evidence.Exclusion`.** Rejected for now (above). Reconsider if two owners need the same
  fee or spread reasons.
- **Model maker fills.** Rejected: there is no queue or fill-probability evidence. `maker_fee` prices a given
  fill; `research_economics.fill_economics` already reports BOOK_MAKER fills with rebates on their own line.

## Tradeoffs

- The CLI covers calibration only. Entries, ladders and depth take typed objects built by the caller, because
  their inputs (books, markets, fee scopes) come from venue adapters that differ by data source.
- The harness's own checks are declared-access checks, like `research_evidence`: they cannot prove nobody
  looked at data outside them.

## Reconsider when

- an approved data source arrives (Novig daily files, Kalshi settled sports markets with trades): add its adapter
  to its venue owner, not here;
- a primary source documents another venue's or series' maker fee: add a dated record and a `MAKER_TERMS` entry;
- a Track B candidate needs a fill model: that is new evidence, and needs its own decision.
