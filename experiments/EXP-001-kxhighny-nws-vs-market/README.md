# EXP-001: KXHIGHNY NWS forecast vs market

**Status: DRAFT.** Blocked on gate 2 (settlement validation). No results exist. Nothing
here claims an edge.

## Log

- **2026-09-22.** Spec drafted. First live read-only collection succeeded: 12 open markets,
  2 events, 12 order books, and 4 NWS payloads. The captured series metadata and market rules
  name **The Weather Company** (`https://weather.com/kalshi`) as the settlement source, for
  station CLINYC:

  > "If the maximum temperature recorded at New York City (CLINYC) for Sep 23, 2026, is
  > greater than 72° fahrenheit according to The Weather Company, then the market resolves
  > to Yes." (`markets[].rules_primary`)

  The series `contract_url` and `contract_terms_url` point to `GLOBALTEMPERATURE.pdf`.
  Web search results and third-party pages instead describe settlement on the NWS Daily
  Climate Report. **Primary evidence wins, and the discrepancy is itself a gate-2 finding.**
  Next: capture the contract PDFs, review the weather.com terms, collect the NWS CLI, and
  measure how the two agree.

## Open questions

1. What does `GLOBALTEMPERATURE.pdf` specify for the observation window, timezone, rounding
   and revisions?
2. Is automated retrieval from weather.com/kalshi permitted? If not, what other evidence
   of the settlement value exists? Kalshi's `settlement_value` and `result` fields on
   settled markets are one candidate.
3. How often do The Weather Company's final values differ from the NWS CLI maximum?
4. Framework prerequisite: this experiment must not move to PREREGISTERED until the
   deterministic preregistration baseline exists (`experiments/README.md`).
