# KXNFLGAME fee and payoff verification (EXP-002), 2026-09-28

Owner directive 2026-09-28 §9. VF Writer A. The sources are public official documents only. **No Kalshi API
endpoint was called.** Past API data are the repository's own captures. Captured bytes and hashes are in
`experiments/EXP-002-nfl-consensus-vs-event-market/fee_evidence/MANIFEST.json`.

The drafted Kalshi message (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`) is **NOT SENT**. It was not sent,
duplicated or rewritten here. §5 proposes additions to its Q7 for the owner to consider.

## Verdict

**NOT RESOLVED. KXNFLGAME stays `FEE_UNSUPPORTED`.** No `fee_schedules` verification record is added, and no
fee is set to zero.
- The public documents support the *shape* of the taker fee.
- They do not settle four things:
  - the mapping between the fee schedule's non-standard multiplier columns and the API's single multiplier;
  - whether the 2026-07-07 schedule is still current (the current PDF is behind a bot checkpoint);
  - what event-level overrides and fee waivers change;
  - when maker fees started.
- A scheduled-change check would need an API read, which this task excludes.

A current fee document would not change a frozen experiment's fee assumptions retroactively in any case.

## Evidence, by class

| Class | Source (version / date) | Finding |
|---|---|---|
| GOVERNING DOCUMENT | Kalshi Fee Schedule PDF, "Last updated and effective: July 7, 2026" (repo copy, sha256 `c326a69f…`, received 2026-09-23), p.2 | Taker fee = round up(M × 0.07 × C × P × (1−P)), with M "default is 1 unless otherwise indicated". Maker fee = round up(M × 0.0175 × C × P × (1−P)), with M "default is 0". Round up means fee + positionCost rounded to a centicent. The general terms apply "apart from specific products listed below, which have their own fee schedule". |
| GOVERNING DOCUMENT | Same PDF, "Non-Standard Fees" table (columns "Maker Multipler" [sic] and "Taker Multiplier") | `KXNFLGAME Professional Football Game 1 1`. The row appears twice in the text layer, both times 1 / 1. **The table gives no formula and does not say that its columns are p.2's M.** |
| GOVERNING DOCUMENT | Same PDF, "Settlement Fees" | "There is no settlement fee." It is silent on balance-precision rounding at settlement. |
| GOVERNING DOCUMENT | KalshiEX Rulebook v1.29, Rule 3.13 (sha256 `3b6d4ffd…`, unchanged since 2026-09-25) | Sets no rate. Fees are revised and published on the website. |
| API DOCUMENTATION | docs.kalshi.com Get Series (OpenAPI 3.31.0; no "Last updated") | `quadratic_with_maker_fees` "is described by the General Trading Fees Table with maker fees described in the Maker Fees section". `fee_multiplier` is one float "applied to the fee calculations", not split into maker and taker. |
| API DOCUMENTATION | Get Series; changelog entry dated 2026-08-22 | Calls the standard maker multiplier `0.25` (combo: `0.5`), where the PDF has M = 1 with coefficient 0.0175. |
| API DOCUMENTATION | Get Event Fee Changes; Get Event | Event fees are "an override layered on top of the parent series' fee structure", and `fee_type_override` takes precedence for the event's markets. Changes carry a `scheduled_ts`. |
| API DOCUMENTATION | Get Market | `fee_waiver_expiration_time` is described only as the time a fee waiver expires. What a waiver does is undocumented. |
| API DOCUMENTATION | Fee Rounding (content unchanged since the 2026-09-23 capture) | Trade fee rounded up to $0.000001. Balances aligned to $0.0001 (direct) or $0.01 (non-direct). The accumulator applies to maker and taker fills alike. |
| API DOCUMENTATION | Changelog, 2026-08-20/22 entries | "Maker fees will be enabled at 5:00 AM ET on Thursday, August 20". Scope unstated. Independent NFL-only combos have no maker fee (combos only, not KXNFLGAME). |
| DOCUMENTED EXAMPLE | Fee Rounding worked example; PDF pp.4–5 table | General taker examples only. **No worked example for a sports, non-standard or maker fee.** |
| HELP ARTICLE | help.kalshi.com "Fees" (modified 2026-04-19) and related articles | No formula, coefficient or sports example. "Some markets have fees that are different", with a pointer to the schedule. |
| HISTORICAL OBSERVATION | `tests/fixtures/sports_evidence/kalshi_series_KXNFLGAME_2026-09-25T022448Z.json` | `fee_type` `quadratic_with_maker_fees`, `fee_multiplier` 1, `last_updated_ts` 2026-09-16T00:29:24Z (after the PDF's July 7). |
| HISTORICAL OBSERVATION | `kalshi_events_KXNFLGAME_open_2026-09-25T022444Z.json` | No field containing "fee" on any open event or market at that moment. |
| BLOCKED | `kalshi.com/docs/kalshi-fee-schedule.pdf`, `/fee-schedule`, `/regulatory/fee-schedule` (2026-09-29 00:24–00:28Z) | HTTP 429 "Vercel Security Checkpoint". Not retried and not bypassed. |
| INFERENCE (not evidence) | — | 0.25 × 0.07 = 0.0175 and 0.5 × 0.07 = 0.035 = 2 × 0.0175, so the two vocabularies agree numerically. The absent override fields are probably `x-omitempty` (no override then). KXNFLGAME is probably listed as non-standard because its maker multiplier (1) differs from the default (0). |

## Exact conflicts and gaps (kept blocked)

1. **Multiplier mapping.**
   - The PDF has a taker and a maker multiplier per series (both 1), against coefficients 0.07 and 0.0175.
   - The API has one `fee_multiplier` (1), and calls the standard maker level "0.25".
   - That the PDF columns are p.2's M, and that the API's multiplier scales both legs, is inference only.
2. **Currency of the schedule.**
   - The only readable governing text is dated 2026-07-07.
   - The series record changed on 2026-09-16, and what changed is unknown.
   - The current PDF could not be read.
3. **Scheduled changes.**
   - KXHIGHNY's record verified "no scheduled change" through the API `fee_changes` endpoint.
   - The same check for KXNFLGAME would need an API read, excluded here, so this component cannot be verified.
4. **Event-level overrides and waivers.**
   - Overrides take precedence per event.
   - Whether `fee_multiplier_override` scales maker, taker or both is undocumented, and so is the effect of a
     fee waiver.
   - A point-in-time claim needs per-event evidence at the decision time.
5. **Maker-fee start.**
   - The PDF of July 7 already lists maker multipliers.
   - The changelog says maker fees were enabled on 2026-08-20, with no stated scope.
   - This matters only for maker simulations. EXP-002 is taker-only, so it does not block the taker question,
     but it is part of the same unresolved semantics.
6. **Fractional fills and native quantity.** Fills are in 0.01-contract steps. The per-fill fee rule for
   fractional fills is the open Q5 (CURRENT: NOT_EVALUATED in the size ladder).

**Payoff side (unchanged, VERIFIED earlier).** The KXNFLGAME payoff states are those of
`RESEARCH_UNBLOCKING_DECISIONS.md` A.D:
- a tie pays $0.50;
- fair-price and discretionary states pay F in [0, 1];
- the after-55-minutes suspension text conflicts between the 2026-09-11 terms and the 2026-02-18
  certification (UNVERIFIED which governs).

This task found no document that resolves that conflict.

## What this means for EXP-002

- Every after-fee figure stays blocked. That covers the economic screen, episodes built on an after-fee start
  threshold, and the $1,000 continuation-bar comparison.
- Gross (pre-fee) figures may be shown only as labelled gross diagnostics. They are never net claims.
- The illustrative general-formula figures in A.E stay ILLUSTRATIVE.
- The freeze proposal carries the fee as a named blocker (`EXP002_FREEZE_PROPOSAL.md`).

## Proposed additions to Q7 (for the owner; NOT SENT; this file does not edit the drafted message)

Q7 as drafted asks whether the KXNFLGAME taker and maker fees are exactly the general formulas with M = 1,
subject only to event overrides. The evidence suggests adding:
- (a) Do the "Maker Multiplier" / "Taker Multiplier" columns of the Non-Standard Fees table equal the M of
  p.2's formulas, and does the API `fee_multiplier` scale the taker fee, the maker fee or both?
- (b) Is the July 7, 2026 schedule the one in force for KXNFLGAME since then? If it was revised (the series
  record changed on 2026-09-16), when and how?
- (c) Does `fee_multiplier_override` apply to maker, taker or both, and what does `fee_waiver_expiration_time`
  waive?
- (d) Did KXNFLGAME maker fees apply from July 7 or from August 20, 2026?

## Drafted question S1: suspended after 55 minutes (payoff conflict; NOT SENT)

No question in `KALSHI_QUESTIONS_2026-09-26.md` covers this conflict. Q2 asks only about the NO-side payout at a
non-binary value. The coordinator adds S1 to the Kalshi message file; this document does not send it.

> **S1 (KXNFLGAME, game suspended after 55 minutes of play).** Two governing texts differ for an NFL game that is
> suspended after 55 minutes of play, is not resumed, and is not declared complete or final by the league.
> - The FOOTBALLGAMEWIN contract terms (PDF created 2026-09-11) resolve the market to the result as it stands at
>   suspension.
> - The CFTC self-certification letter of 2026-02-18 resolves it to the last fair market price as determined by
>   Kalshi.
>
> Which text governs KXNFLGAME markets listed since 2026-09-11? If the fair-price text governs, is that price
> confined to [$0, $1] and to the price grid, and is it paid identically to YES and (as $1 − value) to NO holders?

Evidence: `experiments/EXP-002-nfl-consensus-vs-event-market/rules_evidence/` (both documents, with hashes) and
`RESEARCH_UNBLOCKING_DECISIONS.md` A.D. The freeze proposal's payoff bound does not depend on the answer (both
texts pay a value in [0, 1]). The answer decides only whether that state is modelled as the standing result or as
a discretionary F.

## Re-check

The Kalshi fee re-check date in HANDOFF (by 2026-10-23) is unchanged. A verification record for KXNFLGAME is
added only when the documents, or an explicit written provider answer recorded verbatim, resolve (1)–(4). It
then gets its own effective date and scope, and it is never applied to decisions made before its knowledge time.
