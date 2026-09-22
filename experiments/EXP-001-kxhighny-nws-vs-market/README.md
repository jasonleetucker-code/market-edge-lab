# EXP-001: KXHIGHNY NWS forecast vs market

**Status: DRAFT.** Gate 2 (settlement validation) **passed** on 2026-09-22; see
`gate2/REPORT.md`. Next is gate 3 (point-in-time dataset) and the preregistration freeze.
No modeling results exist, and nothing here claims an edge.

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

- **2026-09-22 (gate 2).** Captured contract terms (GLOBALTEMPERATURE, the certification
  filing, legacy NHIGH) as exact bytes, plus every settled market (live and historical API).
  The rules source changed from NWS CLI to The Weather Company on 2026-08-14. Reproduced
  Kalshi results for 68/68 days (2026 window) and 361/365 days (held-out 2025; 4 UNKNOWN
  because archived CLI finals are missing), with 0 mis-predicted brackets. Kalshi
  `expiration_value` equals the NWS CLI settlement value on 373/373 events. Two contract
  report-selection rules were needed and implemented: "first final report that includes
  the data", and NHIGH's delayed determination when the final is lower than earlier reports.

## Open questions

1. ~~What does GLOBALTEMPERATURE.pdf specify?~~ Answered in `docs/SETTLEMENT.md`.
2. ~~Is automated retrieval from weather.com/kalshi permitted?~~ No (terms of use), so it
   is not collected. Kalshi's `expiration_value`/`result` serve as the official evidence.
3. How often do TWC final values differ from NWS CLI? Not directly measurable. Kalshi's
   value agreed with NWS on 39/39 TWC-era days; keep auditing new settlements.
4. ~~Framework prerequisite: deterministic preregistration baseline.~~ Implemented
   (`edge-lab experiments freeze`, CI `check-frozen`); use it when preregistering.
5. Gate 3 design question: decision time vs. when forecasts and the preliminary CLI become
   available (point-in-time availability).
