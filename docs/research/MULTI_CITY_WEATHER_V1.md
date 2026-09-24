# Multi-City Weather v1: design (Deliverable 2, design stage)

**Status:** DESIGN, 2026-09-24 (Lane G). Nothing here is implemented, scheduled or authorized
to run.
- **Authority.** `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`, §8–§10,
  §35–§39, §46, §51, §53, §54, §64 and §67, Deliverable 2.
- **Implementation start.** It begins only after the current mission's lanes are merged and
  deployed (the directive's coordinator re-plan).
- **Activation conditions.** `docs/EXECUTION_PLAN.md` (2026-09-24, #86) authorizes bounded
  public collectors as "gated, one source at a time". Before activation this design must have:
  - an entry in the portfolio;
  - a terms and access review;
  - a worst-case budget with the combined footprint recomputed;
  - a `sources.py` registration and a Freshness Fabric provider;
  - an incremental rollout;
  - independent review, and green CI on the exact head.

  The backup-retention decision (§8.4) and any new timer remain owner decisions
  (`AI_INSTRUCTIONS.md`, "Authority").
- **Live evidence.** `experiments/multi_city_weather/verification_2026-09-24.md` holds 40
  bounded public GETs. Their exact bytes are in `tests/fixtures/kalshi_weather_families/`.
  Findings are cited as F1–F7.
- **EXP-001 is untouched.** No change to its code, timers, experiment files or decision rule.
  New cities start in state **DATA_COLLECTION**, never as EXP-001 clones.

## 1. Summary

- **Recurring families.** Kalshi lists recurring **daily** weather families:
  - high temperature for about 23 US cities and 20 international cities;
  - low temperature for most of the same cities;
  - several rain series;
  - hourly intraday series.

  These all settle on the same GLOBALTEMPERATURE terms as KXHIGHNY, under the same unresolved
  TWC/NWS documentary conflict (docs/SETTLEMENT.md §2):
  - the 7 original KX city high series;
  - every US `KXHIGHT*` and `KXLOWT*` series.

  The exceptions are NWS-era duplicates and the composite `KXHIGHUS`. Each series' rules name an
  NWS Daily Climate Report (CLI) station code (F2, F3).
- **Listing and close.** Every checked series lists its event at **14:00Z on D-1**. Each has 6
  brackets, and each **closes at 00:00 local standard time (LST) at the end of D**, i.e. at the
  end of the NWS climate day:
  - 05:00Z Eastern, 06:00Z Central, 07:00Z Mountain, 08:00Z Pacific;
  - Phoenix keeps no DST, so its close is 07:00Z = 00:00 MST.

  So there is **no market at D-3 or D-2**. Those horizons are forecast-only (F3).
- **Selected cities (12).** NYC (reference, EXP-001's market), Chicago-Midway, Minneapolis,
  Boston, Atlanta, Miami, Austin, Denver, Phoenix, Los Angeles, San Francisco and Seattle.
  Together they cover every climate class the directive names, and every one had two open
  events at verification time. Excluded: Philadelphia, Washington, Dallas, Houston, Las Vegas,
  the thin T-series cities, all international series, legacy series, and the low-temperature,
  rain and hourly families (§4.3).
- **Budget.** In phase 1, 11 new cities plus NYC's extra horizons add about **410 public GETs a
  day** (about 214 to Kalshi and 198 to NWS) and about **4.6 MB of payload a day**. With the
  SQLite rows and indexes that is about 5.8 MB/day, about 175 MB/month or about 2.1 GB/year. The
  closing-price phase adds about 88 GETs and 0.5 MB a day.
  - CPU is about 2–3 CPU-minutes a day. Each run stays under 60 MB RSS, and runs are serialized
    by the existing collector lock.
  - **The binding constraint is backups, not the collector.** Daily full, uncompressed backups
    with no retention grow quadratically. That is already true today, and multi-city growth
    brings the 65 GB free disk into reach in about 4 months (§8.4).
- **Architecture.** It reuses existing code:
  - market-side horizons are ADR 0030 price-observation targets planned from the stored catalog;
  - forecast, CLI and settlement captures form one bounded `weather` capture job under the
    existing collector lock, pacers, protected windows and close guards;
  - one Freshness Fabric provider declares seven sources;
  - there is no new scheduler, no new database, and no change to EXP-001.

## 2. What exists (verified 2026-09-24)

This is only the part of F2/F3 that drives the design.

| family | series pattern | recurring? | settlement terms / source named | used in v1? |
|---|---|---|---|---|
| US daily high, original KX | `KXHIGHNY`, `KXHIGHCHI`, `KXHIGHMIA`, `KXHIGHAUS`, `KXHIGHDEN`, `KXHIGHLAX`, `KXHIGHPHIL` | daily; D and D+1 open | GLOBALTEMPERATURE; rules name TWC and the CLI code | yes (6 of 7) |
| US daily high, `KXHIGHT*` | ATL, BOS, DAL, DC, EWR, HOU, LV, MIN, NOLA, OKC, PHX, SAN/KSAN, SATX, SDF, SEA, SFO, TTN | daily (10 verified open) | same | yes (5) |
| US daily low | `KXLOWT*` (and older `KXLOW*` on CITYLOW terms) | daily (`KXLOWTCHI` verified open) | same, "minimum temperature" | v1.1 option (§4.3) |
| International daily high/low | e.g. `KXHIGHTEGLL`, `KXLOWTRJTT` | daily | INTERNATIONALTEMPERATURE or GLOBALTEMPERATURE; TWC | no (no NWS) |
| Rain | `KXRAIN`, `KXRAINNYC`, `KXRAINSEA`, ... | "daily" in catalog; `KXRAINNYC` had 0 open markets | mixed | no |
| Hourly intraday | `KXTEMP*H`, `*HS`, `KXHIGHNYD` | hourly | TWC, Synoptic Data, Kalshi index | no |
| Legacy/duplicates | `HIGHNY`, `HIGHCHI`, `KXDENHIGH`, `KXHIGHOU`, ... | series `volume_fp` 0 | older NWS terms | history only |

## 3. Settlement semantics, verified per city independently

**Method.** For each city, the rules were read from that city's own markets (F3), not
inferred from KXHIGHNY. They were then cross-checked against:
- the series' `settlement_sources` and `contract_terms_url` (F2);
- the NWS CLI location list (F6);
- the NWS-era series' settlement URL, where one exists (F2);
- for SFO, the CLI product text itself (F6).

KXHIGHNY's full audit (docs/SETTLEMENT.md) is the template. **None of its statistical results
(739/739 agreement) transfer to another city.**

**Common to all 12 selected series.** All of the following were observed:
- `contract_terms_url` GLOBALTEMPERATURE; `settlement_sources` = The Weather Company; fee
  quadratic with multiplier 1.
- `rules_primary`: "maximum temperature recorded at <City> (CLI<XXX>) for <date> ... according to
  The Weather Company".
- The **TWC/NWS documentary conflict** of docs/SETTLEMENT.md §2 applies unchanged. TWC stays
  BLOCKED (`kalshi_settlement_weather_company`), and the NWS CLI is the independent proxy.
- Bracket semantics as in docs/SETTLEMENT.md §3: `greater` is strict, `less` is strict,
  `between` is inclusive, units are whole °F, with no rounding by us.
- Which report counts: GLOBALTEMPERATURE's first official non-preliminary report with data. The
  NHIGH-era 11 AM rule does not apply to target dates in this design; collection starts after
  2026-10.
- **Day boundary: the NWS climate day in local standard time.** The CLI column is labelled
  `(LST)` (observed for CLISFO and for CLINYC in Gate 2). `close_time` is exactly midnight LST
  (F3).
- **Documentary conflict about trading close.** `early_close_condition` says "11:59 PM local
  time", while `close_time` is 00:00 LST, 61 minutes later during DST. ADR 0030 already treats
  `close_time` as the trading close and proves it with a post-close read. We record the conflict
  and never resolve it silently (§6.8).
- Timing (F3, F5): listing 14:00Z on D-1; expected expiration 19:00Z on D+1; latest expiration
  14:00Z on D+7. Observed settlement for SEA was 14:09–14:18Z on D+1.

**Per-city mapping.** Office and grid come from `/points` (F6).

| city | series | CLI code (rules) | station (ICAO) | name verified from | CLI issuing WFO | forecast office, grid | LST (UTC offset) / DST | close_time (UTC, D+1) |
|---|---|---|---|---|---|---|---|---|
| New York (ref.) | KXHIGHNY | CLINYC | KNYC Central Park | CLI text (Gate 2) | OKX | OKX; EXP-001 uses PFMOKX NYZ072 | EST −5 / DST | 05:00Z |
| Chicago | KXHIGHCHI | CLIMDW | **KMDW Midway**, not O'Hare | rules code; NWS-era URL `LOT/MDW` | LOT | LOT 72,69 | CST −6 / DST | 06:00Z |
| Minneapolis | KXHIGHTMIN | CLIMSP | KMSP | rules code | MPX | MPX 110,68 | CST −6 / DST | 06:00Z |
| Boston | KXHIGHTBOS | CLIBOS | KBOS Logan | rules code | BOX | BOX 73,101 | EST −5 / DST | 05:00Z |
| Atlanta | KXHIGHTATL | CLIATL | KATL | rules code | FFC | FFC 49,81 | EST −5 / DST | 05:00Z |
| Miami | KXHIGHMIA | CLIMIA | KMIA | rules code; NWS-era URL `MFL/MIA` | MFL | MFL 105,51 | EST −5 / DST | 05:00Z |
| Austin | KXHIGHAUS | CLIAUS | **KAUS Bergstrom**, not Camp Mabry (ATT) | rules code; NWS-era URL `EWX/AUS` | EWX | EWX 158,87 | CST −6 / DST | 06:00Z |
| Denver | KXHIGHDEN | CLIDEN | KDEN (Denver Intl., about 5,400 ft) | rules code; NWS-era URL `BOU/DEN` | BOU | BOU 75,66 | MST −7 / DST | 07:00Z |
| Phoenix | KXHIGHTPHX | CLIPHX | KPHX Sky Harbor | rules code | PSR | PSR 161,57 | MST −7 / **no DST** | 07:00Z |
| Los Angeles | KXHIGHLAX | CLILAX | KLAX | rules code | LOX | LOX 149,41 | PST −8 / DST | 08:00Z |
| San Francisco | KXHIGHTSFO | CLISFO | **KSFO airport**, not downtown | **CLI text** ("SAN FRANCISCO AIRPORT", KMTR) | MTR (verified) | MTR 85,98 | PST −8 / DST | 08:00Z |
| Seattle | KXHIGHTSEA | CLISEA | KSEA Sea-Tac | rules code | SEW | SEW 124,60 | PST −8 / DST | 08:00Z |

"Rules code" means the station identity follows NWS CLI naming (CLI + the 3-letter station id),
and the code exists in the NWS CLI location list. The name has **not** yet been read from that
city's own product text. PR 1 reads one CLI product per station and fails if the header names a
different site. The issuing WFO is inferred from the `/points` office, except for SFO (observed)
and NYC (Gate 2).

### 3.1 Close time, DST and the KXHIGHNY history

| period | KXHIGHNY close_time | source |
|---|---|---|
| until August 2026 | 23:59 ET wall time (03:59Z in summer, 04:59Z in winter) | gate3 bulk fixture (ADR 0030) |
| August 2026 to now | 05:00:00Z | ADR 0030; F3 |
| now, all 17 checked cities | 00:00 LST at the end of D (05/06/07/08Z) | F3 |

- **Inference.** Every city fits only "00:00 LST" (F3). The alternatives fail:
  - DST cities close at 01:00 local daylight time, which is neither 23:59 nor civil midnight;
  - Phoenix, with no DST, closes at 00:00 MST.
- **Prediction.** No UTC change on 2026-11-01. **Unverified until the first winter closes are
  observed.**
- **The planner never assumes a close time.** It reads `close_time` from every listing. A
  deviation from the predicted LST midnight is an anomaly (`CLOSE_TIME_UNEXPECTED`), and a
  change between reads is `CLOSE_TIME_CHANGED` (ADR 0030 semantics).

## 4. City selection

### 4.1 Criteria, in the order the directive gives them

1. **Recurring availability.** Two consecutive open events verified live (F3); daily frequency.
   Continuity beyond that is verified for SEA only (F5); PR 2 audits it for every city.
2. **Verifiable rules and an official station.** The rules name one CLI station. The station's
   CLI exists (F6). An NWS-era or text cross-check is noted where it exists.
3. **Climate diversity.** See the classes below.
4. **Liquidity.** Lifetime series `volume_fp` (F2), and D-event and D+1 volume and open interest
   at verification time (F3).
5. **NWS coverage.** A CLI station, a WFO with a PFM product (verified for LOX and OKX; others in
   PR 1), and a gridpoint.
6. **Sustainability.** One series per city with no lineage ambiguity; resource cost per city
   (§8).

"Named in the directive" was not a criterion. Philadelphia (named) is excluded, and Chicago is
Midway, not O'Hare.

### 4.2 Selected (12)

| city | climate role | why included |
|---|---|---|
| New York (KXHIGHNY) | humid continental, coastal urban; **reference** | EXP-001's market. The multi-city layer adds only horizons EXP-001 does not capture and reuses EXP-001's evidence read-only for its decision window. Lifetime 145.6M. |
| Chicago-Midway (KXHIGHCHI) | continental, lake effects, northern winter | 110.7M lifetime; D-event 75.8k. An original KX series with an NWS-era station record. |
| Minneapolis (KXHIGHTMIN) | coldest continental, **northern winter** extremes | The only strongly cold-winter market. 9.6M lifetime is the thinnest selected, and D+1 was 945 at verification. Kept for climate coverage. First candidate to drop if its books prove too thin. |
| Boston (KXHIGHTBOS) | coastal New England, sea breeze and nor'easters | 15.9M. A distinct coastal regime from NYC, where Philadelphia and DC mostly repeat NYC's. |
| Atlanta (KXHIGHTATL) | humid subtropical, Southeast | 16.4M. The Southeast is otherwise absent. |
| Miami (KXHIGHMIA) | tropical, low variance | 100.2M; D-event 187k, the second most liquid. |
| Austin (KXHIGHAUS) | hot humid subtropical, Texas | 77.6M. An original KX series with an NWS-era station record. |
| Denver (KXHIGHDEN) | **high elevation**, downslope and upslope, big forecast busts | 51.1M. The only mountain station. |
| Phoenix (KXHIGHTPHX) | **desert**; **no DST** | 17.1M. Also exercises the no-DST timezone path. |
| Los Angeles (KXHIGHLAX) | coastal marine layer | The most liquid series (169.8M; D-event 356k). |
| San Francisco (KXHIGHTSFO) | cool coastal microclimate, fog | 18.4M; D-event 79.5k. Station verified from CLI text as the airport. |
| Seattle (KXHIGHTSEA) | **Pacific Northwest** marine | 16.9M; D-event 114.7k. The only city whose settlement continuity is verified (34 days, F5). |

Classes covered: humid continental (NYC, CHI, BOS), northern winter (MIN, CHI), subtropical
(ATL, AUS), tropical (MIA), desert (PHX), mountain/high elevation (DEN), coastal Mediterranean
and marine layer (LAX, SFO), Pacific Northwest (SEA). Timezones: all four US zones, plus the
no-DST case.

### 4.3 Excluded, with the reason

| candidate | evidence | reason |
|---|---|---|
| Philadelphia (KXHIGHPHIL) | open; 41.8M lifetime | Same humid-continental Northeast-corridor regime as NYC, about 80 miles away, so little incremental information. **First reserve**, especially for a "near-NYC transfer" study. |
| Washington DC (KXHIGHTDC, CLIDCA) | open; 12.9M; lowest D-event volume checked (18.5k) | Northeast-corridor duplicate. |
| Dallas (KXHIGHTDAL, CLIDFW) | open; 13.5M | Texas heat overlaps Austin. **Reserve** for a Southern Plains convective regime in v1.1. |
| Houston (KXHIGHTHOU, CLIHOU = Hobby) | open; 10.3M | Gulf humid regime overlaps MIA and ATL. **Lineage ambiguity:** `KXHIGHTHOU` (TWC, open), `KXHIGHHOU` (NWS-era, 6.4M) and `KXHIGHOU`/`KXHOUHIGH` (0 volume) must be mapped before use. |
| Las Vegas (KXHIGHTLV, CLILAS) | open; 12.7M | Desert duplicate of Phoenix. Phoenix has the higher lifetime volume and adds the no-DST case. **Reserve.** |
| NOLA, OKC, SATX (`KXHIGHT*`) | 7.1M / 8.2M / 6.1M; **not queried** (budget) | Lower liquidity, and regimes already covered. Open events unverified. |
| SAN/KSAN, SDF, EWR, TTN | 86k, 34k, 49k, 52k lifetime (KSAN 0) | Too thin. `KXHIGHTSDF` is titled "HIGHEST Temperature SATX", so its identity is ambiguous. |
| International (about 20 cities) | catalog only | No NWS station or forecast. Different terms (INTERNATIONALTEMPERATURE) and source agencies. Out of scope until a non-NWS official source is reviewed. |
| Legacy and NWS-era duplicates (`HIGH*`, `KXDENHIGH`, `KXHIGHOU`, `KXHOUHIGH`, `KXDVHIGH`, `KXLOWNYC`, `KXLOWNY`) | series `volume_fp` 0 | Dormant. Kept only as history for PR 2's audit where they map to a selected city. |
| `KXHIGHUS`, `KXCITIESWEATHER` | 6.0k / 86.5k lifetime | Composite national or multi-city underlying (WPC), not a single station. |
| Low temperature (`KXLOWT*`) | recurring; `KXLOWTCHI` open | **Not a separate city choice.** Same stations and CLI (minimum), so v1's forecasts and CLI already hold its inputs and labels. Adding its markets costs about 3–5 listing GETs per city a day. Proposed as **v1.1** after v1 is clean, not in the first rollout. |
| Rain (`KXRAINNYC`, `KXRAIN`, ...) | `KXRAINNYC` 0 open markets (F7) | Dormant or seasonal, or a composite (`KXRAIN`). No verified recurring daily market. |
| Hourly (`KXTEMP*`) | catalog only | A different family (intraday, some on Synoptic Data or Kalshi indexes). Not the daily climate-day market. |

## 5. What to preserve, per city and target day

Categories follow the directive (§3): **C** is irrecoverable, **B** partially reconstructible,
**A** reconstructible. Category C is collected first.

| evidence | category | what, exactly | where it lives (existing primitive) |
|---|---|---|---|
| Series record | A/B | the series payload: settlement sources, contract URLs, fee type and multiplier, frequency, `last_updated_ts` | `snapshots` (`kalshi` `series`) |
| Contract documents | A | GLOBALTEMPERATURE PDFs, exact bytes and versions | `document_blobs`, via `kalshi.collect_settlement_evidence` (already captured for KXHIGHNY; the same URL is not duplicated) |
| Market catalog and rules | B | the event listing: **all brackets**; strikes; `rules_primary`/`rules_secondary`/`early_close_condition` and their hashes; station code parsed from the rules; open, close and expiration times; status | `snapshots` (`kalshi` `markets`); parsed fields and hashes on ADR 0030 rows |
| Prices, sizes, volume, open interest | **C** | per bracket: YES/NO bid and ask with sizes, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, last price, as the venue's decimal strings | listing snapshot, plus ADR 0030 `price_observations` rows (`quote_source = MARKET_LISTING`) |
| Depth | **C** | the full book, `depth=100`, per bracket | `snapshots` (`kalshi` `orderbook`), plus ADR 0030 rows (`quote_source = ORDERBOOK`) |
| Later and close prices | **C** | pre-close, and a close within 60 s with proof | ADR 0030 phases `pre_close` and `close` |
| Gridpoint forecast | **C** (the API keeps no archive) | `/gridpoints/{wfo}/{x},{y}/forecast`: period highs and lows, `updateTime`, `validTimes`, `generatedAt` | `snapshots` (`nws` `forecast`, entity `wfo/x,y`) |
| PFM | B (IEM keeps an archive) | every issuance per WFO: list plus product text; issuance, WMO header, product id | `snapshots` (`nws_pfm` `pfm_list`/`pfm_product`), as EXP-001 does |
| Latest observation | B (ASOS is archived) | `/stations/{ICAO}/observations/latest` near the event afternoon and pre-close | `snapshots` (`nws` `observation_latest`) |
| CLI settlement publication | A (IEM, about 7 days on the API) | every issuance per station: preliminary, final, corrections | `snapshots` (`nws_cli` `cli_list`/`cli_product`) |
| Kalshi settlement | A | `result`, `expiration_value`, `settlement_ts` for every bracket of every event | `snapshots` (`kalshi_settlement` `event_settlement_markets`), via `kalshi.refresh_event_settlements` |
| Failures and misses | **C** | every timeout, HTTP error, empty listing, schema change, deferral and miss | `source_health`, ADR 0030 `MISSED`/`FAILED` rows, the capture run's record |

**Explicitly not collected in v1:**
- hourly and gridded obs series (reconstructible from IEM/NCEI ASOS; LATER);
- `forecastGridData` and `forecastHourly` (large; revisit if a model needs them);
- alerts (low value for daily max; LATER);
- MOS/NBM (a separate source review);
- TWC (BLOCKED).

## 6. Horizons, time, completeness and anomalies

### 6.1 Time handling (deterministic, stdlib only)

- **Canonical instants are UTC.** Each record also keeps the source's own representation, for
  example the CLI's "140 AM PDT" and LST times, and Kalshi's `Z` strings (§53).
- **The climate day of target D** for a city with standard offset `s` is
  `[D 00:00 − s, D+1 00:00 − s)` in UTC. Chicago, for example, is `[D 06:00Z, D+1 06:00Z)`.
  During DST it runs 01:00–01:00 local daylight time. So 00:00–00:59 local daylight time on
  calendar date D belongs to climate day D−1, which matters for any obs-based running maximum.
- **Civil-time horizons** such as "18:05 local" use the US DST rule (second Sunday of March to
  first Sunday of November, 02:00 local), with `observes_dst=False` for Phoenix.
  - Implemented as one generalized function in the new module. It is not an edit to
    `forward.eastern_offset`, which is EXP-001 code.
  - A parity test pins it to `forward.eastern_offset` for Eastern at every hour of 2026–2028.
  - There is no tzdata dependency (the repo is stdlib-only; Windows has no system tzdata).
- **DST boundary tests:** 2026-11-01, 2027-03-14 and 2027-11-07, for every city.

### 6.2 Horizon table (per city, target day D)

`L` is local civil time. All intended times sit on an existing 15-minute timer grid:
- market horizons on the observe grid (:05/:20/:35/:50);
- forecast horizons on the weather grid (:08/:23/:38/:53, §7.4).

A horizon whose run (at most 4 min) could overlap a protected window is **shifted to the first
grid tick after the window**, or to just before the window when its end is too close to the
close. The shift is recorded. This is ADR 0030's existing `shifted_out_of_protected_window`
rule. The shifts named below were checked against both US DST states.

| id | intended time | market side (Kalshi) | forecast side (NWS) | notes |
|---|---|---|---|---|
| F-D3 | D-3 08:38 L | not applicable (no market exists) | PFM list + new products; gridpoint forecast | the city's daily morning forecast tick also serves D-3 |
| F-D2 | D-2 08:38 L | not applicable | same tick, D-2 view | |
| F-D1m | D-1 08:38 L | none at this horizon; the D event is listed at 14:00Z on D-1 and first captured by M1 | same | |
| M1 `listing` | D-1 14:35Z | event listing (all brackets, top of book, volume, rules) | - | first prices, 35 min after `open_time` |
| F-D1a | D-1 14:38 L | - | PFM + gridpoint | Pacific cities (always) and Phoenix (during US DST) would overlap 17:40 ET, so they shift to 18:53 ET = 15:53 L |
| F-cut | D-1 17:23 L | - | PFM + gridpoint | the forecast "available at the comparable decision" (EXP-001 rule: issuance + 30 min at or before decision − 30 min). Central cities shift to 17:53 CDT/CST (18:53 ET), still before their 18:05 L decision |
| M2 `d1_comparable` | D-1 18:05 L; **Eastern cities: 18:50 ET** (shifted out of 17:40–18:50); due window [T − 5, T + 5 min] | listing + **one book per bracket** | - | **EXP-001-comparable window.** NYC: backfilled from EXP-001's decision capture, with no request (ADR 0030 backfill path). The Eastern shift is recorded, and the horizon is analysed as its own horizon, never pooled blindly |
| F-Dm | D 08:38 L | - | PFM + gridpoint | |
| M3 `event_morning` | D 09:05 L | listing | - | |
| F-Da | D 14:38 L | - | PFM + gridpoint + latest obs | Pacific cities (always) and Phoenix (during US DST): 18:53 ET = 15:53 L |
| M4 `event_afternoon` | D 15:05 L; Pacific cities (always) and Phoenix (during US DST) shift to 18:50 ET = 15:50 L | listing + latest obs | - | |
| M5 `pre_close` | close − 15 min (**Eastern group: close − 25 min, due window [T − 5, T + 10 min]**, §7.3) | listing + one book per bracket | latest obs | ADR 0030 `pre_close` |
| M6 `close` | close − 30 s, confirmed after close | ADR 0030 `close` with proof, labelled "close (within 60 s of trading close)" | - | **phase 2** of the rollout (§10) |
| S1 CLI | 03:08Z and 13:38Z daily (sweeps) | - | CLI list + new products, all stations | 03:08Z catches the preliminary reports (about 16:30–17:30 local); 13:38Z catches every final (00:30–01:40 LST) and early corrections |
| S2 Kalshi settlement | D+1 19:35Z, then daily at 15:35Z until settled or D+8 | targeted `/markets?event_ticker=` | - | reuses `kalshi.refresh_event_settlements` |

**De-duplication by issuance.** A PFM product or gridpoint forecast covers about 7 days, so the
per-target forecast horizons are not separate requests:
- each city has **3 forecast ticks a day** (08:38, 14:38 and 17:23 L);
- each tick serves every target D..D+6 at its own horizon;
- PFM products are fetched once per product id, and never again after they are stored, whether
  by this job or by EXP-001's PFMOKX capture;
- the analysis selects, for each (target, horizon), the latest issuance available at that
  horizon, using the EXP-001 availability rule;
- the gridpoint forecast is stored at every tick, because its `updateTime` changes; identical
  payloads are kept on purpose (docs/DATA_PROVENANCE.md §2).

### 6.3 Intended time, receipt time, and MISSED

- **Market horizons** are ADR 0030 targets. Each is an immutable row with its intended time and
  due window. Each attempt row records receipt time and status (`CAPTURED`, `NOT_EXECUTABLE`,
  `FAILED`, `MISSED`) and a miss reason, for example:
  - `NOT_CAPTURED_BY_DEADLINE`, `PLANNED_AFTER_DEADLINE`, `DEFERRED_PROTECTED_WINDOW`;
  - `LOCK_BUSY` (until the deadline), `BUDGET_BLOCKED`, `CLOSE_TIME_CHANGED`;
  - `EVENT_NOT_LISTED`.

  A final status is never revisited. **A missed horizon stays MISSED**, and nothing is ever
  fetched late to fill it.
- **Forecast, obs and CLI horizons.** In v1 they are *derived*, deterministically, from the
  versioned horizon policy (`weather_multi.HORIZON_POLICY_VERSION`) and the immutable
  receipts, the way `forward.day_status` re-derives EXP-001 validity:
  - a forecast horizon H is `CAPTURED` only if a successful PFM-list receipt **and** a gridpoint
    receipt for that city fall in `[H − 10 min, H + 25 min]`;
  - otherwise it is `MISSED` with the reason taken from that run's `source_health` or refusal
    record;
  - a later receipt can never satisfy an earlier horizon (tested).

  When the shared release/event calendar primitive (directive §71, Lane F's Wave 1 design)
  merges, these horizons become stored targets there. That is an adoption step, not a fork, and
  v1 does not wait for it.
- **The two clocks** (docs/DATA_PROVENANCE.md §4). Upstream issuance and `updateTime` are kept
  apart from our receipt time. A fresh receipt of an old forecast is stale content.

### 6.4 PROSPECTIVE_CAPTURE and HISTORICAL_BACKFILL

- **Prospective** rows come only from scheduled or manual *live* runs. Their receipt time is the
  real receipt.
- **Backfill** uses separate source ids (`iem_afos_cli_multi`, `iem_afos_pfm_multi`,
  `kalshi_settlement` `historical_markets`) and records its own receipt time. It can never
  satisfy a prospective horizon, and never turns a MISSED into CAPTURED (§35–§36).
- Research datasets must label every input's origin, and must not pool the two silently.

### 6.5 Completeness (§51)

- **Per city and target day:**
  - `MARKET_COMPLETE`: every market horizon enabled at that date (M1–M5, and M6 once enabled)
    has a final status of `CAPTURED`, or `NOT_EXECUTABLE` for a lifecycle reason such as an
    early close. Every bracket in the listing is covered.
  - `FORECAST_COMPLETE`: every forecast horizon (F-D3 to F-Da) is `CAPTURED`.
  - `LABEL_COMPLETE`: a Kalshi result exists for every bracket, **and** a CLI final value for
    the station is parsed (or recorded as `MM`, which means missing and stays missing).
  - The day is `COMPLETE` only if all three hold. It is `PARTIAL` with reasons if any horizon is
    `MISSED`, `FAILED` or pending past its deadline.
  - It is `NOT_LISTED` only when a *complete* catalog read shows no event.
  - It is `NOT_APPLICABLE` before the city's activation date.
- **Per family and day:** `COMPLETE` only if every selected, activated city is `COMPLETE`, else
  `PARTIAL` with the per-city reasons. **PARTIAL never implies absence.**
- **No selection bias (§37).** Every selected city, every day, every bracket, whatever the
  volume, weather or opportunity. Days with nothing interesting are first-class evidence.

### 6.6 Anomaly checks (§54)

Anomalies are preserved and never silently fixed. Each is written to `source_health.anomalies_json`
and to the capture record.

| check | rule | effect |
|---|---|---|
| Station changed | `(CLI<XXX>)` in `rules_primary` differs from the registry | `STATION_CHANGED`. Labels for that city are halted pending review. |
| Rules changed | hash of the rules templates (date and strike normalized) differs from the last one seen; also `rules_secondary`, `early_close_condition`, `settlement_sources`, `contract_terms_url`, fee type and multiplier | `RULES_CHANGED` (the city stays collected) |
| Close unexpected or moved | `close_time` ≠ 00:00 LST at the end of D; or it differs between reads | `CLOSE_TIME_UNEXPECTED` / `CLOSE_TIME_CHANGED` (ADR 0030) |
| Open time moved | `open_time` ≠ 14:00Z on D-1 | `OPEN_TIME_CHANGED` (the M1 horizon re-targets) |
| Bracket structure | not exactly one `less`, one `greater` and contiguous `between` brackets that partition the integers; a count other than 6 | `BRACKETS_IRREGULAR` |
| Expected event missing | the D+1 event is not listed by 15:05Z on D (a single-event read, F1) | `EVENT_NOT_LISTED` |
| Book integrity | crossed book (YES bid + NO bid > 1), negative or zero sizes, price off the grid | `BOOK_INVALID` (prices dropped, snapshot kept) |
| Settlement shape | not exactly one YES; non-integer `expiration_value`; a result other than yes/no | `SETTLEMENT_IRREGULAR` (label UNKNOWN) |
| Label disagreement | Kalshi `expiration_value` ≠ CLI final | `LABEL_DISAGREEMENT` (Kalshi stays authoritative; surfaced on the audit) |
| CLI | final missing by D+1 13:38Z; `MM`; a correction after settlement; a header naming another station | `CLI_LATE` / `CLI_MISSING` / `CLI_CORRECTED_AFTER_SETTLEMENT` / `STATION_CHANGED` |
| Forecast | PFM lacks the station's point block; gridpoint `updateTime` older than 12 h at a horizon; grid changed at the weekly `/points` check | `PFM_POINT_MISSING` / `FORECAST_STALE` / `GRID_CHANGED` |
| Time sanity | a source timestamp in the future beyond 5 min; a receipt before the request | `FUTURE_TIMESTAMP` |
| Documentary conflict (known) | `early_close_condition` 11:59 PM local vs `close_time` 00:00 LST | `KNOWN_CONFLICT_CLOSE_WORDING`, stored with the text hash. A changed text becomes `RULES_CHANGED`. |

## 7. Architecture: reuse, no new scheduler or database

### 7.1 Module map

| concern | canonical owner | change |
|---|---|---|
| City registry, horizon policy, LST and civil time, rules parsing, anomaly checks, completeness, fabric provider | **new** `edge_lab/weather_multi.py` (pure; no network) | new. It is the one owner of multi-city weather facts, in the same split as `odds_schedule`/`odds_pilot`. |
| Forecast, obs, CLI and catalog capture runs (network) | **new** `edge_lab/weather_capture.py` | new. It uses `http.fetch_json_result`, `SnapshotStore.save_snapshot`, `nws_cli.NWS_PACER`, `kalshi.PACER` and `forward.exclusive_lock`. |
| Kalshi listings, books, pagination, settlement refresh | `edge_lab/kalshi.py` | reused. `refresh_event_settlements` gets `max_events` of at least 12 for this caller (a parameter; default unchanged). |
| Market-side horizons M1–M6 | `edge_lab/price_observations.py` (ADR 0030) | **extended.** It gets a second planner input, `plan_from_catalog(...)` (origin `catalog_family:multi_city_weather_v1`), reading stored listings with no network. New horizon phases carry their own due windows. Schema v7 adds `quote_source` (`ORDERBOOK`/`MARKET_LISTING`) and `horizon_id`. Close semantics, proof, protected windows, lock and bounds are unchanged. |
| CLI parsing | `edge_lab/nws_cli.py` | **extended, additively.** Timezone map for EST/EDT/CST/CDT/MST/MDT/PST/PDT; location parameter; the GLOBALTEMPERATURE-only regime for new series. NYC outputs are pinned unchanged by the existing tests. |
| PFM parsing | `edge_lab/nws_pfm.py` | extended to select a station block from any office's PFM (per-office fixture tests) |
| Settlement audit | `edge_lab/settlement_audit.py` | extended per series and station |
| Readiness | `edge_lab/research_readiness.py` (#79) | WEATHER_MULTI rows (NO_DATA → COLLECTING → PARTIAL → RESEARCH_READY) |
| Freshness | `edge_lab/freshness_fabric.py` (ADR 0031) | one `REGISTRY` line |
| Sources | `edge_lab/sources.py` | registry rows (§7.5) |
| CLI | `edge_lab/cli.py` | a self-contained `weather` block: `catalog`, `capture`, `status` |
| **Not touched** | `forward.py`, `dataset_exp001.py`, `exp001_*.py`, `experiments/EXP-001-*`, the EXP-001 timers | zero change |

### 7.2 Data flow

1. **Catalog** (weather timer, daily at 14:23Z, after the 14:00Z listing):
   - `/series/{ticker}` for the 12 series;
   - `/markets?series_ticker=X&status=open` (1 page; it holds D and D+1);
   - `/series?category=Climate and Weather&include_volume=true` weekly, for family discovery
     and liquidity.

   It stores snapshots and runs the rules, station and close anomaly checks.
2. **Plan** (observe timer, no network): `price_observations.plan_from_catalog` turns stored
   listings into M1–M6 targets. It is idempotent, and targets are planned once per market.
3. **Market capture** (observe timer, existing `edge-lab observe capture`): due targets are
   captured under the existing bounds, lock, pacer and protected-window refusal.
4. **Forecast, obs and CLI capture** (weather timer, `edge-lab weather capture`). It does the due
   forecast ticks, CLI sweeps and weekly `/points` checks. PFM products already in the store are
   never re-fetched.
5. **Settlement** (weather timer): S2 targeted event reads, plus CLI finals from S1.
6. **Status** (no network): `edge-lab weather status` derives per-city-day completeness and
   labels. The fabric provider exposes freshness.

### 7.3 Collector lock, pacing and EXP-001 isolation

- **One lock, one budget.** Every multi-city run, observe-driven and weather-driven alike, takes
  the existing collector lock `<db>.forward.lock` with a **5 s** timeout. A busy lock gives
  `LOCK_BUSY`, exit 0, and a retry at a later tick inside the due window. That keeps one Kalshi
  pacing budget per host: `kalshi.PACER` 0.6 s, about 1.7 req/s against the roughly 4 req/s
  public throttle. NWS uses `NWS_PACER` 0.5 s.
- **Never contend with EXP-001.** A run refuses to start, with no network and no writes, when
  `[now, now + MAX_RUN]` (4 min) overlaps:
  - `price_observations.PROTECTED_WINDOWS_ET`: 17:40–18:50 ET, which covers EXP-001's 17:45 PFM,
    17:55:05 decision, 18:05 recheck, 18:30 status and 18:40 shadow; and 11:13–11:30 and
    16:13–16:30 ET for settlement;
  - any **close guard**: [tick − 2 min 15 s, tick + 3 min 15 s] around the 04:57:45Z KXHIGHNY
    close tick, and around each new close tick in phase 2.

  So a multi-city run can never hold the lock while an EXP-001 unit (60 s lock timeout) or the
  close capture needs it. That is proven by construction and pinned by a test over every minute
  of a DST and a non-DST day.
- **Group sizing inside ADR 0030's bounds** (24 markets, 40 GETs, 4 min per run):
  - a book horizon for one timezone group is at most 4 cities × 7 GETs = 28 GETs and 24 markets
    (Eastern: NYC is backfilled, so MIA/ATL/BOS = 18 markets);
  - the Eastern pre-close (M5) is aimed at close − 25 min (04:35Z tick), so it never shares the
    04:50Z tick with NYC's existing ADR 0030 pre-close;
  - listing-only horizons are 1 GET per event.
  - Bounds are not raised. A group that would exceed them is split across adjacent ticks by the
    planner.
  - Observe and weather ticks are 3 minutes apart (:05 then :08, :50 then :53). A book-horizon
    run takes about 15–20 s of pacing, so the next tick normally finds the lock free.
    - An example is the Eastern M2 at 18:50 ET followed by the shifted Central forecast cutoff
      at 18:53 ET.
    - If a run still holds the lock, the next tick is `LOCK_BUSY`. Its horizon is retried inside
      its window, or becomes MISSED. It is never captured late.
- **Close phase (M6, phase 2).**
  - The Central, Mountain and Pacific groups need their own close ticks (05:57:45Z, 06:57:45Z and
    07:57:45Z), added to `edgelab-observe-close.timer` by a reviewed change with owner approval.
    ADR 0030 says a family with another close time "needs its own entry".
  - The Eastern group would share the 04:57:45Z run with NYC. It is added only after production
    evidence shows NYC's close books stay first and inside [close − 60 s, close) with 18 more
    books queued behind them. Until then the Eastern cities get `pre_close` only.

### 7.4 Timer and Freshness Fabric

- **Unit.** One new `edgelab-weather.{service,timer}`:
  - `OnCalendar=*:08/15` (:08/:23/:38/:53), staggered off Odds (:00/:15/:30/:45), observe
    (:05/:20/:35/:50) and freshness (:01/:06/...);
  - `Persistent=false`, `AccuracySec=5s`;
  - the same caps and hardening as `edgelab-observe.service`: `MemoryMax=256M`, `CPUQuota=25%`,
    `TasksMax=32`, `Nice=5`, `TimeoutStartSec=6min`, in `edgelab.slice`.
  - Idle ticks take the lock and a read-only open, and write nothing (the ADR 0030 pattern).
  - **Installed, not enabled** until the owner approves (§10).
- **Fabric.** One `FabricProvider("weather_multi_city", WEATHER_POLICIES,
  weather_multi.fabric_provider)`. The mode is `EXTERNAL_SCHEDULE` in v1, with these underlying
  modes:

  | source_id | underlying mode | schedule_owner |
  |---|---|---|
  | `weather_multi.kalshi_catalog` | POLL (daily) | edgelab-weather.timer + weather_multi.plan |
  | `weather_multi.market_horizons` | EVENT_RELATIVE (listing, local day, close) | edgelab-observe.timer + price_observations (catalog origin) |
  | `weather_multi.nws_pfm` | RELEASE_DRIVEN | edgelab-weather.timer |
  | `weather_multi.nws_gridpoint` | EVENT_RELATIVE (horizon ticks) | edgelab-weather.timer |
  | `weather_multi.nws_obs_latest` | EVENT_RELATIVE | edgelab-weather.timer |
  | `weather_multi.nws_cli` | RELEASE_DRIVEN | edgelab-weather.timer |
  | `weather_multi.kalshi_settlement` | RELEASE_DRIVEN | edgelab-weather.timer |

  - Seven records: aggregated per family, with per-city state in `details`. 12 cities fit the
    24-key bound, and the artifact's 64-source bound is respected.
  - `max_useful_age` comes from `sources.REGISTRY`.
  - The provider calls the **same** planner functions the capture uses, so parity holds by
    construction, and the fabric test pins the tick grid to the unit file.
  - Moving to fabric-controlled scheduling follows ADR 0031's migration path: parity evidence,
    one source at a time, and owner approval.

### 7.5 Source registry rows (all `PLANNED` until activation)

- **Reused:**
  - `kalshi_public`: series, listings, books. It adds the `weather_multi` health profile.
  - `kalshi_settlement`: settled events, contract documents, historical markets.
  - `nws_api`: points and gridpoint forecast. It gains kind `observation_latest` with a 2 h max
    age.
- **New:**
  - `nws_pfm_multi`: PFM for the 11 WFOs; entity = WFO; list 26 h / product 30 h; public domain;
    identifying User-Agent.
  - `nws_cli_multi`: CLI for the 11 stations; entity = CLI code; list 26 h / product 36 h.
- **Backfill only:** `iem_afos_cli_multi` and `iem_afos_pfm_multi`, PLANNED, polite at 1 req/s.
- **Unchanged:** `kalshi_settlement_weather_company` stays BLOCKED. Its description is widened to
  name every selected series.
- `HEALTH_PROFILES` gains `weather_multi`, so a multi-city failure never makes the routine or
  forward profile unhealthy, and the reverse also holds (source isolation, acceptance item 8).

## 8. Resource budget (§43–§44)

Payload sizes come from the committed fixtures:
- event listing (6 markets) 17 KB (`tests/fixtures/forward/markets_*`);
- book 1.4 KB (F4);
- series listing 34 KB for 12 markets (F3);
- PFM product 32.7 KB (OKX fixture); PFM list 9.6–12.3 KB;
- CLI list 5.7 KB and product 4.9 KB (F6); points 3.9 KB (F6).

The gridpoint forecast (about 20 KB) and the latest observation (about 3 KB) are **estimates**
that PR 1 measures.

### 8.1 Per day, steady state (11 new cities; NYC adds only listing, forecast, CLI and settlement)

| stream | GETs/day | payload/day |
|---|---|---|
| Kalshi catalog: 12 `/series/{t}` daily, plus the category listing weekly | 12.1 | 63 KB |
| M1 listing (12 events) | 12 | 204 KB |
| M2 comparable (11 × (1 listing + 6 books)) | 77 | 279 KB |
| M3 event morning (12) | 12 | 204 KB |
| M4 event afternoon (12) | 12 | 204 KB |
| M5 pre-close (11 × 7) | 77 | 279 KB |
| S2 Kalshi settlement (12 events, first attempt) | 12 | 204 KB |
| **Kalshi subtotal (phase 1)** | **about 214** | **about 1.44 MB** |
| PFM lists (12 WFOs × 3 ticks) | 36 | 396 KB |
| PFM products (new only; about 4.7 a day × 11 WFOs; OKX already stored by EXP-001) | 52 | 1.72 MB |
| Gridpoint forecast (12 × 3 ticks) | 36 | 720 KB (est.) |
| Latest observation (12 × 2) | 24 | 72 KB (est.) |
| CLI lists (12 × 2 sweeps) and new products (about 2 per station) | 48 | 257 KB |
| `/points` re-check (weekly) | 1.7 | 7 KB |
| **NWS subtotal** | **about 198** | **about 3.17 MB** |
| **Total, phase 1** | **about 412** | **about 4.6 MB** |
| Phase 2 close (11 × (1 + 6 + 1)) | +88 | +0.47 MB |

- **Rows.** About 700 ADR 0030 observation rows a day (listing horizons 12 × 6 × 2 sides × 3,
  book horizons 11 × 6 × 2 × 2), each 0.3–1 KB with depth, plus about 360 targets. That is
  about 0.7 MB a day.
- **Database growth.** About 5.8 MB/day, about 175 MB/month, about 2.1 GB/year. With phase 2,
  about 6.4 MB/day and about 2.3 GB/year. For comparison, production today grows by under
  1 MB/day (VPS review) plus about 0.25 MB/day for ADR 0030.
- **Storage policy per stream.** All streams are raw and immutable (`snapshots` and
  `document_blobs`), uncompressed in SQLite as today. Retention is indefinite, because evidence
  is never deleted. A cold monthly archive export is a LATER option that needs its own
  decision.

### 8.2 Per run, runs per day, and worst case

- **Largest run.** A book horizon for one timezone group: at most 28 Kalshi GETs, or about 17 s
  of pacing. With ADR 0030's per-run caps of 40 GETs and 4 min, a run takes 5–40 s of wall time.
- **Largest weather run.** One forecast tick for one timezone group: at most 4 cities × (1 PFM
  list + at most 2 new products + 1 gridpoint + 1 obs), about 20 NWS GETs, or about 10 s.
- **Runs with network.** About 22 observe runs and about 18 weather runs a day. Each timer's
  remaining ticks (up to 96 a day) are idle: under 1 s of CPU, no writes.
- **Retries.** The fetch layer makes at most 2 retries per GET, and a FAILED target is retried
  by at most 2 later ticks inside its window. The nominal ceiling is 3× the daily GETs, about
  1,250. A pathological day is bounded by per-day guards, proposed at **600 Kalshi and 500 NWS
  multi-city GETs a day**. Past a guard, the source is `BUDGET_BLOCKED` until the next UTC day,
  visible in the fabric.
- **Peak request rate.** Unchanged: Kalshi 1.7 req/s, NWS 2 req/s, and never two collectors at
  once (the lock).

### 8.3 CPU and memory, combined with production

- **CPU.** About 40 network runs × about 2 CPU-s, plus about 96 idle ticks × about 0.5 CPU-s: about
  2–3 CPU-minutes a day. Under the 25% slice quota this is negligible.
- **Memory.** One run stays under 60 MB RSS; the VPS review measured the same for the forward
  captures. The largest payload parsed is the weekly 360 KB series listing.
- **Combined slice.** Collectors are serialized by the lock, so the worst concurrent set is the
  dashboard, the freshness supervisor (capped at 128M) and one collector. That is well under
  `edgelab.slice` MemoryMax 384M. The observed slice peak is 49 MiB (production activation
  record, 2026-09-23). Brisket and Chase Upside are unaffected: the host has about 6.4 GB
  available, and memory PSI is 0.
- **Network.** About 4.6 MB/day inbound.

### 8.4 The binding constraint: backups (an existing issue, amplified)

- **How backups work today.** `edgelab-backup` writes a **full, uncompressed copy** of the
  evidence database **every day** and never deletes one (`deploy/vps/README.md`,
  `edge_lab.backup`). Backup disk is therefore the sum of every day's database size, which
  grows quadratically.
The cumulative total after n days is n × S0 + g × n(n+1)/2, where S0 is the current database
size and g is the daily growth.
- **Without multi-city** (g about 1 MB/day): about 67 GB, plus 365 × S0, after one year. That
  crosses the 65 GB free (VPS review 2026-09-22) in roughly 7–10 months for S0 between 50 and
  200 MB.
- **With multi-city** (g about 7 MB/day combined): about 29 GB, plus 90 × S0, after 90 days. It
  crosses 65 GB after about 120 days.

**Precondition for step 4 of the rollout.** Enabling multi-city at low frequency (§10, step 4)
needs an owner decision on backup retention or compression. Options include keeping 7 daily,
4 weekly and 12 monthly copies; compressing bundles; or incremental exports. This is a
destructive-adjacent change, so it needs approval. The issue exists independently of this
design and is reported to the coordinator.

## 9. Outcome and label plan (§39)

- **Authoritative label.** Kalshi `result` and `expiration_value` per bracket, via targeted S2
  reads (`kalshi.refresh_event_settlements`, source `kalshi_settlement`), for **every** event of
  every selected city, not only events with a position.
- **Independent proxy.** The NWS CLI final for the rules' station:
  - parsed by the generalized `nws_cli`;
  - rule: the first final report with data (GLOBALTEMPERATURE);
  - corrections are kept, and a preliminary value is never used.
- **Label state per city-day:**
  - `AGREED` when both exist and are equal;
  - `KALSHI_ONLY`;
  - `CLI_ONLY` (Kalshi is not yet settled, or the event is not listed);
  - `DISAGREE`, which is an anomaly; Kalshi wins;
  - `UNKNOWN` when neither exists.

  Never inferred from a forecast or a headline.
- **Per-city validation before RESEARCH_READY.** PR 2 runs the KXHIGHNY-style historical audit
  for each selected series: Kalshi settled and `/historical/markets` values, compared with
  finals from the IEM AFOS CLI archive for that station (HISTORICAL_BACKFILL).
  - A city whose historical agreement is not clean stays `COLLECTING` with its CLI proxy
    marked **UNVALIDATED**.
  - A station mismatch removes the city from the selection.
  - The TWC conflict stays documented, as for KXHIGHNY.
- **Low-temperature (v1.1).** The same pipeline, using the CLI minimum.
- **Readiness matrix.** One row per city in `research_readiness.py`. A city reaches
  RESEARCH_READY only when all of the following hold:
  - market catalog history, point-in-time prices, depth, rules and settlement, forecast vintages
    and outcome labels are all at least PARTIAL;
  - the audit has passed;
  - at least 30 consecutive city-days are `COMPLETE`.

  No numeric score. No model or strategy is authorized by any of this (§57–§59).

## 10. Implementation plan (bounded PRs, each with tests) and rollout

| PR | scope | tests | network or production |
|---|---|---|---|
| **1. Facts and parsers** | `weather_multi.py`: city registry, LST and civil time, horizon table, rules and station parser, rules-template hash, bracket partition, anomaly checks, completeness evaluator. `nws_cli` timezone and location generalization (NYC pinned). `nws_pfm` office generalization. Registry rows (PLANNED). One bounded verification note (about 60 GETs; manual; laptop; outside protected windows) that reads, per selected station, one CLI product (name check), one PFM product (point block) and one gridpoint forecast (size), stored as fixtures. | on this PR's fixtures: every rule parses to the registry station; `close_time` = LST midnight for all 17 fixture series; DST boundaries; the parity test against `forward.eastern_offset`; CLISFO parse (PDT); bracket partition; `EVENT_NOT_LISTED` on the empty listing (F1, F7) | one manual bounded read; no timer |
| **2. Historical validation** | Per selected series: bounded `kalshi.collect_settlement_evidence` (settled plus historical; page cap), IEM CLI archive per station (HISTORICAL_BACKFILL), per-city agreement audit (`settlement_audit`), continuity (days listed), liquidity history. Commit `experiments/multi_city_weather/settlement_audit_<date>.md` with fixtures and the final city list. | the audit is reproducible from the committed fixtures; disagreement cases pinned | manual bounded backfill; laptop |
| **3. Market-side capture** | ADR amendment or new ADR; `price_observations` v7 (additive `quote_source`, `horizon_id`, catalog planner origin); `edge-lab weather catalog`; group sizing; Eastern pre-close offset; the fabric `market_horizons` record. | the schema v7 migration and rollback stamp (as v5/v6); a MARKET_LISTING row never labelled CLOSE; bounds never exceeded; the protected-window and close-guard refusal at every minute of 2026-11-01 and 2027-03-14; NYC M2 backfilled with zero requests; an idle tick writes nothing | code only; timer changes installed but not enabled |
| **4. Forecast, obs and CLI capture** | `weather_capture.py`; `edge-lab weather capture`; PFM de-duplication across EXP-001's store; the per-day GET guards; `edgelab-weather.{service,timer}` (installed, not enabled); the fabric provider (7 sources). | the tick grid pinned to the unit file; every timer explained; a late receipt never satisfies a horizon; source isolation (a failing NWS source leaves Kalshi evidence and other sources intact); `BUDGET_BLOCKED` | code only |
| **5. Labels, status and readiness** | S2 settlement for all selected events; CLI-final labels; label states; `edge-lab weather status`; `research_readiness` rows. The Terminal panel is a later Lane D item under the UI contract, covering real, empty, stale, error, unsupported and blocked states. | label-state matrix; `UNKNOWN` never coerced; completeness PARTIAL reasons | code only |
| **6. Activation (ops)** | runbook sections (Lane E), the backup retention decision (§8.4), enabling the timers by step | `verify_production.sh` checks: timers, fabric records, zero EXP-001 `LOCK_BUSY` | **owner approval per step** |

**Rollout (§64).** One failing city or source never blocks the others.

0. **Preconditions.**
   - The current lanes are merged and deployed; Freshness Fabric is deployed.
   - Backup retention is decided.
   - The EXECUTION_PLAN gate conditions are met (see the Status block).
   - The owner has approved the new schedule (`edgelab-weather.timer`, the catalog-origin
     targets on `edgelab-observe.timer`).
1. **Fixture.** PR 1 and PR 3–5 tests run on committed fixtures only.
2. **Historical and sample validation.** PR 2. Cities that fail are dropped or stay UNVALIDATED.
3. **Bounded smoke.**
   - On the VPS, manually, outside protected windows: one `weather catalog`, one
     `observe capture` and one `weather capture` for 3 cities (one Central, one Mountain, one
     Pacific).
   - Every request is logged.
   - Check afterwards that EXP-001's day stayed VALID and no unit logged `LOCK_BUSY`.
4. **Low-frequency prospective.**
   - Enable for 6 cities (CHI, MIA, DEN, PHX, LAX, SEA), horizons M2 and M5, the CLI sweeps and
     S2 only.
   - About 7 GETs × 2 per city plus CLI and settlement: under 150 GETs a day.
5. **Source-health evidence.**
   - At least 7 consecutive days with every enabled horizon final, and every MISSED explained.
   - Zero fabric disagreements.
   - Zero EXP-001 `LOCK_BUSY` or INVALID caused by this job.
6. **Expand** to all 12 cities and all phase-1 horizons, including the forecast ticks and the
   latest obs.
7. **Several clean runs, then cadence increase.** After at least 14 more clean days **and**
   after the first winter close has been observed and matches LST midnight (2026-11-02Z), add
   phase 2:
   - the close ticks for the Central, Mountain and Pacific groups, then the Eastern group under
     the §7.3 condition;
   - optionally low-temperature v1.1.

   Each step is a reviewed change with its own owner approval.

## 11. Acceptance mapping (directive Deliverable 2)

| # | criterion | where |
|---|---|---|
| 1 | candidate recurring cities identified | §2, §4; F2, F3 |
| 2 | each market's settlement semantics verified independently | §3 (per-city rules read live); the name check from product text completes in PR 1 and the agreement audit in PR 2 |
| 3 | exact station mapped | §3 table (CLI code → ICAO; SFO and NYC from text) |
| 4 | NWS forecast source mapped | §3 table (WFO, grid from `/points`; PFM verified for LOX and OKX, the rest in PR 1) |
| 5 | market and forecast evidence preserved prospectively | §5, §6 (design; PRs 3–4) |
| 6 | no EXP-001 change | §7.1, §7.3 |
| 7 | bounded resource estimate | §8 |
| 8 | sources isolated from each other | §7.5 (health profile), §7.4 (per-source fabric records), PR 4 test |
| 9 | freshness visible | §7.4 |
| 10 | settlement captured | §9 |

## 12. Open questions and what would make us reconsider

- **The winter close (2026-11-01/02).** If `close_time` does not stay at LST midnight, the close
  ticks and the Eastern pre-close offset need a reviewed change. The planner itself reads
  `close_time` and is unaffected.
- **Per-city settlement agreement (PR 2).** Any city with disagreements is excluded, or kept as
  UNVALIDATED collection only.
- **PFM point coverage.** Some offices' PFM may lack the settlement station's point. Then the
  gridpoint forecast is that city's only forecast feature, and the city's comparability with
  EXP-001 is weaker. This is recorded, not hidden.
- **Minneapolis liquidity.** If its books are persistently empty at M2 and M5, replace it with
  Philadelphia or Dallas (a registry change plus an activation date; history kept).
- **Backups (§8.4).** This must be decided before step 4.
- **The §71 calendar primitive.** When it merges, the forecast and CLI horizons move from derived
  status to stored targets.
- **Reconsider the whole design if:**
  - request volume exceeds about 600 GETs a day nominal;
  - database growth exceeds 10 MB a day;
  - a Kalshi terms change affects automated public reads;
  - Kalshi adds a book sequence number (exact close proof);
  - a model shows the forecast-only horizons (F-D3, F-D2) add nothing, in which case drop them.
