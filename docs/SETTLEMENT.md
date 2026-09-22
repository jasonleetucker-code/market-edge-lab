# KXHIGHNY Settlement Semantics (Gate 2)

This file answers one question: what real-world value decides a KXHIGHNY contract, and how
is YES/NO computed from it? Every statement cites stored primary evidence in
`experiments/EXP-001-kxhighny-nws-vs-market/gate2/` (hashes are in `evidence/MANIFEST.md`).
It was established on 2026-09-22 and must be re-checked whenever the captured rules or
contract documents change. `edge-lab settlement collect` flags a changed contract document.

## 1. Evidence hierarchy

When sources disagree, this order applies:

1. **Market-specific rules captured from Kalshi's API for that market:** `rules_primary`,
   `rules_secondary` and `early_close_condition` on each market object. These are
   versioned per event date.
2. **Certified contract terms:** `GLOBALTEMPERATURE` (series `contract_terms_url`), and the
   CFTC self-certification filing dated December 8, 2025 (series `contract_url`). For the
   older NWS-era wording, the legacy `NHIGH` contract terms.
3. **Kalshi's recorded outcome for each market:** `result`, `expiration_value` and
   `settlement_ts`. This is used to verify, never to replace, the rules.
4. Generic help pages, web descriptions and third-party sites carry no authority.

## 2. The named settlement source changed on 2026-08-14

Deterministic templating of `rules_primary` across the audited markets gives (2024 uses
the same NWS wordings):

| Target dates | `rules_primary` names | Events |
|---|---|---|
| 2025-01-01 → 2025-03-04 | "National Weather Service's **Daily Climate Report**", Central Park | 63 |
| 2025-03-05 → 2026-08-13 | "National Weather Service's **Climatological Report (Daily)**", Central Park | 331 in the audited windows |
| 2026-08-14 | "according to **The Weather Company**", "New York City" | 1 |
| 2026-08-15 → 2026-09-21 | "according to **The Weather Company**", "New York City (CLINYC)" | 38 |

`rules_secondary` for the TWC era: "the official and final value used to determine this
market is the maximum/minimum temperature as reported by the Weather Company", and "a status
of 'Final' on weather.com/kalshi is provided for convenience only".

The **certified** GLOBALTEMPERATURE terms state: "The Source Agencies are, in hierarchical
order, National Weather Service, the national weather service for <area>". The
certification filing adds that "A new Source Agency can be added via a Part 40 amendment"
(the text extraction interleaves a page header inside this sentence; checked against the PDF)
and that "All instructions on how to access the Underlying are non-binding". Its Source
Agency appendix (Appendix C) is confidential.

**Finding.** From 2026-08-14 the market rules name The Weather Company, while the public
certified terms name the NWS. We cannot see whether TWC was added as a Source Agency. This
documentary conflict is **not** resolved by the documents themselves. What *is* observed:
on all 39 TWC-era days, Kalshi's recorded `expiration_value` equals the NWS CLI value
selected by §4 (0 differences). No TWC value was ever observed, because automated retrieval
is prohibited (§6), so this is agreement between Kalshi's value and NWS, not between TWC and
NWS.

## 3. What "the daily high" means

| Item | Rule | Evidence |
|---|---|---|
| Underlying | Maximum temperature for the target date | GLOBALTEMPERATURE "Underlying"; NHIGH "Underlying" |
| Station | Central Park, NY (CLINYC); NWS CLI "CENTRAL PARK NY CLIMATE SUMMARY" | rules_primary; NHIGH "Instructions"; CLI products |
| Day boundary / timezone | The NWS climate day, local standard time (CLI "TIME (LST)" column). The contract gives no separate boundary. | CLI products; NHIGH "Instructions" |
| Units | Degrees Fahrenheit | rules_primary ("fahrenheit"); NHIGH "Instructions" |
| Precision | "Contract resolution is based on the full precision reported by the Source Agency." CLI reports whole degrees; every captured `expiration_value` is a whole number (e.g. "83.00"). | GLOBALTEMPERATURE "Additional clarification(s)" |
| Rounding | No rounding by us. "Rounding by media outlets, secondary reporting, or third-party summaries does not affect resolution." | GLOBALTEMPERATURE |
| greater | "greater than X" is strictly > X (e.g. T87 = "88° or above") | NHIGH Payout Criterion; GLOBALTEMPERATURE "Above means greater than (>)"; yes_sub_title |
| less | "less than X" is strictly < X (T80 = "79° or below") | same |
| between | inclusive: ≥ lower and ≤ upper (B80.5 = "80° to 81°") | NHIGH; GLOBALTEMPERATURE "'between' means within an inclusive range" |

## 4. Which report counts (preliminary, final, revisions)

- CLI is issued as a same-day **preliminary** report ("VALID TODAY AS OF 0400 PM LOCAL TIME",
  section TODAY). A **final** report follows early the next morning (section YESTERDAY).
  Corrections carry a `CCx` WMO suffix or "CLIMATE REPORT...CORRECTED".
- GLOBALTEMPERATURE: "Only the first official non-preliminary report published by the Source
  Agencies **that includes the relevant data** will be used for resolution. Revisions after
  the Expiration Date are not included."
- NHIGH: "Determination will be delayed until 11AM ET in the case of either (1) High
  temperature is not consistent with 6-hr or 24-hr highs reported by METAR or (2) the Final
  report high is lower than earlier report(s)." It also says revisions made "between the
  Last Trading Date and Time and Expiration Date and Expiration time may be taken into account".

**These two documents conflict.** GLOBALTEMPERATURE fixes the *first* final report with
data. NHIGH can move determination to a later report. The GLOBALTEMPERATURE certification
says the contract "will initially be listed after close-of-business on December 9, 2025".
`edge_lab.nws_cli.settlement_value` therefore scopes the rules by target date. This is an
inference from dates, not a captured per-event contract:

1. **Both regimes:** use the first final report whose maximum parses; a final without a
   value is skipped. Seen on 2025-02-21: the first final had no maximum, the second said 36,
   and Kalshi recorded 36.
2. **NHIGH regime (target dates ≤ 2025-12-09):** if the latest preliminary issued before
   the first final is higher than it, use the latest final issued by 11:00 AM ET the next
   day. A correction supersedes the report it corrects. If no final exists by then, the
   value is UNKNOWN. Seen on 2025-12-03: latest preliminary 41, first final 40, re-issued
   final 41 at 9:21 AM EST, and Kalshi recorded 41. Under GLOBALTEMPERATURE wording the
   answer would have been 40. This rule rests on that **single** observation.
3. **GLOBALTEMPERATURE regime (target dates ≥ 2025-12-10):** first final report with data,
   and nothing else.
4. Condition (1) of the NHIGH rule (METAR inconsistency) is **not implemented**, because we
   do not collect METAR. No observed event needed it.

A preliminary value is never used. Examples where preliminary differed from final:
2026-09-20 (preliminary 67, final 69) and 2025-02-21 (preliminary 32, final 36).

## 5. Timing, missing data, voids

- Last trading: 11:59 PM ET on the target date (`early_close_condition`).
- Expiration: "the sooner of the first 7:00 or 8:00 AM ET following the release of the data
  ... or one week after" the date (`early_close_condition`; NHIGH "Expiration Date"). The
  latest GLOBALTEMPERATURE expiration is three months after the period, at 10:00 AM ET.
- Settlement: no later than the day after expiration, unless under review (Rule 7.1).
- Missing data: "If no data is available for <time period> by the Expiration Date, all
  strikes shall resolve to the last fair price as determined in the sole discretion of the
  Exchange" (GLOBALTEMPERATURE). TWC-era `rules_secondary` says the same.
- Material error: expiration "may be held until the publication of a non-materially-erroneous
  data revision" (TWC-era `rules_secondary`).
- None of the 799 audited events was voided or settled at a fair price. Every one has
  exactly one YES bracket.
  The resolver returns UNKNOWN for any `result` other than yes/no.

## 6. The Weather Company

Reviewed 2026-09-22:

- `weather.com/kalshi` is a JavaScript app with no documented public API.
- robots.txt does not disallow `/kalshi` for generic agents, but sets `Crawl-delay: 10`.
- The weather.com Terms of Use (last updated April 16, 2026) forbid monitoring, accessing or
  copying the Services "through bots, spiders, scrapers, crawlers, or other automated means"
  for unauthorized or commercial purposes without TWC's express written permission.

**Decision:** we do not collect it automatically, and we do not bypass the restriction.
Source `kalshi_settlement_weather_company` is registered as BLOCKED. Settlement is instead
verified through Kalshi's own recorded `expiration_value`/`result`, plus the independent NWS
CLI. If TWC and NWS ever diverge, we will only see it as a mismatch between Kalshi's value
and NWS.

## 7. Using NWS as a settlement proxy

Across the audited windows (2024, 2025 and 2026-07-16..09-21), Kalshi's `expiration_value`
equals the §4 NWS CLI value on **739/739** events where both exist. Only 39 of these are
TWC-era days. That supports using the NWS CLI final value as a settlement **proxy label**
for historical research. Three conditions come with it:

- monitor it: `edge-lab settlement audit` fails on any mis-prediction;
- keep Kalshi's `expiration_value` as the authoritative label when it exists;
- treat an event with neither value as UNKNOWN, never as a guess.

NWS **forecasts** remain features, and they are a different thing from NWS **observations**.
