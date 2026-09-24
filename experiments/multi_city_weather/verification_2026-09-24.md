# Multi-City Weather v1: bounded live verification (2026-09-24)

Lane G, directive `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`
(Deliverable 2, design stage). This note is the request log and the raw findings. The design
that uses them is `docs/research/MULTI_CITY_WEATHER_V1.md`.

## Scope and bounds

- **What ran.** A throwaway script on the owner's laptop, outside the repository. It is not a
  collector, and it has no timer. Every request was a public, unauthenticated GET, sent with no
  cookies, credentials or API keys.
- **Hosts.**
  - Kalshi: `https://external-api.kalshi.com/trade-api/v2`. This is the base URL that
    `edge_lab.sources` registers for `kalshi_public` and `kalshi_settlement`, and it is what
    production uses. The lane brief named `api.elections.kalshi.com`, but the repository does not
    use that host, so it was not contacted.
  - NWS: `https://api.weather.gov`.
- **User-Agent.** `market-edge-lab/0.1 (read-only research; bounded multi-city weather
  verification; +https://github.com/jasonleetucker-code/market-edge-lab)`.
- **Budget.** At most 40 GETs across both hosts. **All 40 were used**: 25 to Kalshi and 15 to
  NWS. The script refused any request past its cap.
- **No retries.** One request that returned an empty result (#2) was not repeated.
- **Pacing.** At least 1.2 s between requests (the script slept 1.2 s after each response).
  Measured start-to-start gaps were 1.3 s or more.
- **Timing.** Every request fell between 22:39:44Z and 22:44:23Z (18:39 to 18:44 EDT). That is
  inside the 17:40 to 18:50 ET protected window, but no contention was possible:
  - the requests came from the laptop, not the VPS, so they used a different IP and a different
    host lock;
  - they ran after EXP-001's network phases had ended (the decision capture at 17:55 to 18:00 and
    the recheck at 18:05 to 18:20);
  - the 18:40 shadow run makes no network requests.

  An implementation on the VPS must never do this; see the design's section on protected
  windows.
- **Stored evidence.** Exact response bytes for 38 of the 40 responses are in
  `tests/fixtures/kalshi_weather_families/`. Their SHA-256 values are listed in `manifest.json`.
  Files ending `.gz` are gzip (with `mtime=0`) of the exact bytes, and the hash is of the
  decompressed bytes. Two bodies are not kept:
  - #1, the series listing without volume, which is superseded by #3 (the same listing plus
    `volume_fp`);
  - #2, whose 27 bytes are identical to #22, which is kept.

## Request log (every request)

`K` = `https://external-api.kalshi.com/trade-api/v2`, `N` = `https://api.weather.gov`. Times are
UTC on 2026-09-24. The SHA-256 is over the exact response bytes.

| # | started | completed | GET | HTTP | bytes | SHA-256 | kept as |
|---|---|---|---|---|---|---|---|
| 1 | 22:39:44.393 | 22:39:44.726 | `K/series?category=Climate%20and%20Weather` | 200 | 350,835 | `e0c663384a2ece8e4e79a0edfa00e0a0cbf67703fe0ad16c8340b4ddbf916ca4` | not kept (superseded by #3) |
| 2 | 22:40:06.906 | 22:40:07.053 | `K/markets?event_ticker=KXHIGHNY-26SEP25,KXHIGHCHI-26SEP25,KXHIGHAUS-26SEP25,KXHIGHMIA-26SEP25,KXHIGHDEN-26SEP25,KXHIGHLAX-26SEP25,KXHIGHPHIL-26SEP25,KXHIGHTATL-26SEP25,KXHIGHTBOS-26SEP25,KXHIGHTDAL-26SEP25&limit=1000` | 200 | 27 | `50699ea1db13415ea46ec367dcfa58decd9660083271c5dc061561f38337fbac` | not kept (empty; identical bytes to #22; see finding F1) |
| 3 | 22:40:31.176 | 22:40:31.461 | `K/series?category=Climate%20and%20Weather&include_volume=true` | 200 | 359,721 | `8c812c0cfe8134bcb3fa11e6e6b57f320958da290476f626c8c60ad552554717` | `series_climate_and_weather_include_volume_20260924T224031Z.json.gz` |
| 4 | 22:40:50.307 | 22:40:50.502 | `K/markets?status=open&limit=100&series_ticker=KXHIGHCHI` | 200 | 34,139 | `e1b74a61a41f4c6751b64da7aeb66b991ee6c1fff20d6e1c0c79893e9c5990d9` | `markets_open_KXHIGHCHI_20260924T224050Z.json` |
| 5 | 22:40:51.729 | 22:40:51.858 | `K/markets?status=open&limit=100&series_ticker=KXHIGHMIA` | 200 | 34,123 | `3e1843f0a0ff7b0c9b0a98830a112d9212db9433cc9335887a9dd403394900eb` | `markets_open_KXHIGHMIA_20260924T224051Z.json.gz` |
| 6 | 22:40:53.083 | 22:40:53.230 | `K/markets?status=open&limit=100&series_ticker=KXHIGHAUS` | 200 | 34,156 | `1a71f3c9b961b0fc6c068567c9075c56e2e7b8c498dd87d1fb91b8a4d7a95004` | `markets_open_KXHIGHAUS_20260924T224053Z.json.gz` |
| 7 | 22:40:54.455 | 22:40:54.599 | `K/markets?status=open&limit=100&series_ticker=KXHIGHDEN` | 200 | 34,105 | `9ad54a3e68ef3ab5c3c29b2c0d3438d8643f823cabca85ae51837813f489db1b` | `markets_open_KXHIGHDEN_20260924T224054Z.json.gz` |
| 8 | 22:40:55.829 | 22:40:55.948 | `K/markets?status=open&limit=100&series_ticker=KXHIGHLAX` | 200 | 34,211 | `3c982258d8f062b0cc12808a5402e2a06d057cb0968bf8b03cdbfd7d30d7236e` | `markets_open_KXHIGHLAX_20260924T224055Z.json.gz` |
| 9 | 22:40:57.176 | 22:40:57.323 | `K/markets?status=open&limit=100&series_ticker=KXHIGHPHIL` | 200 | 34,200 | `97a16694773ff4c204bb46d2f766958cc87ebb8a7411d5cb7046db9be6d3cfd7` | `markets_open_KXHIGHPHIL_20260924T224057Z.json.gz` |
| 10 | 22:41:31.180 | 22:41:31.375 | `K/markets?status=open&limit=100&series_ticker=KXHIGHNY` | 200 | 34,185 | `370b96602fa4fc4591e807ed4588eafbc66a5fb7ad79475a6ec7d5e3644dc266` | `markets_open_KXHIGHNY_20260924T224131Z.json.gz` |
| 11 | 22:41:32.601 | 22:41:32.740 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTSFO` | 200 | 34,217 | `9a3ed7aa8c7f801b479672318ac3f3b94ad02013c6281039fdbd5441bc20c474` | `markets_open_KXHIGHTSFO_20260924T224132Z.json.gz` |
| 12 | 22:41:33.968 | 22:41:34.114 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTPHX` | 200 | 34,188 | `c1b3b0209800b8c21bd56d4db4a1bc0ce42a13b182b3b2957fb4e127156fda92` | `markets_open_KXHIGHTPHX_20260924T224133Z.json` |
| 13 | 22:41:35.342 | 22:41:35.456 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTSEA` | 200 | 34,137 | `01d2a79ca4b2663661ad2ff8919965a2f2ced6f414820f0ccb9465cc2b1087e4` | `markets_open_KXHIGHTSEA_20260924T224135Z.json` |
| 14 | 22:41:36.685 | 22:41:36.830 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTATL` | 200 | 34,139 | `e41a75b108b1b4a046ea115554b5605ccdcf2e486d459e176d5dbea31a7b21e7` | `markets_open_KXHIGHTATL_20260924T224136Z.json.gz` |
| 15 | 22:41:38.057 | 22:41:38.202 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTBOS` | 200 | 34,127 | `c5d61bc88b912bf879b2ef606553102642ee0369d7bc2bfdef69be01983187b8` | `markets_open_KXHIGHTBOS_20260924T224138Z.json.gz` |
| 16 | 22:41:39.459 | 22:41:39.583 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTDAL` | 200 | 34,153 | `f97a6158f88aebbd94de1be1ccb77f83b57240c278faafaecbf3137a21debf05` | `markets_open_KXHIGHTDAL_20260924T224139Z.json.gz` |
| 17 | 22:41:40.834 | 22:41:40.970 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTDC` | 200 | 34,169 | `61c90d1137ce202dfdf2d019d5d399422985e8eb5ef80db62a5ef4860dddf372` | `markets_open_KXHIGHTDC_20260924T224140Z.json.gz` |
| 18 | 22:41:42.201 | 22:41:42.358 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTLV` | 200 | 34,155 | `9707815cacafac1311561b63f3285c998ecc75924e70750267d20f7671672dca` | `markets_open_KXHIGHTLV_20260924T224142Z.json.gz` |
| 19 | 22:41:43.596 | 22:41:43.725 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTMIN` | 200 | 34,181 | `f3e9eb70b8ce4af8b808d5483945fbbcc1392197bc1534de7d63ce3c1b2ae0b7` | `markets_open_KXHIGHTMIN_20260924T224143Z.json.gz` |
| 20 | 22:41:44.950 | 22:41:45.097 | `K/markets?status=open&limit=100&series_ticker=KXHIGHTHOU` | 200 | 34,136 | `7c7934c6c46ddf447d31976857833c4fa116a74ae09055f184d43c3bce003d54` | `markets_open_KXHIGHTHOU_20260924T224144Z.json.gz` |
| 21 | 22:42:45.248 | 22:42:45.474 | `K/markets?status=open&limit=100&series_ticker=KXLOWTCHI` | 200 | 34,069 | `73cd0f2c9776381be4eb8435dbb46981c5e8d2d23f94018aef6cb70b59c10def` | `markets_open_KXLOWTCHI_20260924T224245Z.json` |
| 22 | 22:42:46.702 | 22:42:46.846 | `K/markets?status=open&limit=100&series_ticker=KXRAINNYC` | 200 | 27 | `50699ea1db13415ea46ec367dcfa58decd9660083271c5dc061561f38337fbac` | `markets_open_KXRAINNYC_20260924T224246Z.json` |
| 23 | 22:42:48.073 | 22:42:48.340 | `K/markets?status=settled&limit=200&series_ticker=KXHIGHTSEA` | 200 | 542,975 | `575b2e49e7ba82e60f8e36eb90de71c0d9029f3d9af244d9661db1d6683d6330` | `markets_settled_KXHIGHTSEA_limit200_20260924T224248Z.json.gz` |
| 24 | 22:42:49.568 | 22:42:49.669 | `K/markets/KXHIGHCHI-26SEP25-B68.5/orderbook?depth=100` | 200 | 1,366 | `affc0d4d98e878e52d40bb62c93dbb0ad25e125a06981896a00158311292de7d` | `orderbook_KXHIGHCHI-26SEP25-B68.5_20260924T224249Z.json` |
| 25 | 22:42:50.907 | 22:42:51.028 | `K/markets/KXHIGHTSEA-26SEP25-B61.5/orderbook?depth=100` | 200 | 1,448 | `0e7b287d352f6c2325687b2639c2f22f08bb2db0a1c3c34edd526ae95cbc85c3` | `orderbook_KXHIGHTSEA-26SEP25-B61.5_20260924T224250Z.json` |
| 26 | 22:43:10.677 | 22:43:10.905 | `N/products/types/CLI/locations` | 200 | 14,049 | `34633b9fa6772f47c2d10987cc0e532eef599809ed97423d57a8f176a3614978` | `nws/cli_locations_20260924T224310Z.json` |
| 27 | 22:43:30.427 | 22:43:30.584 | `N/products/types/CLI/locations/SFO` | 200 | 5,716 | `69df4548c75c21960b8e56a7a3d75ecce6d25661f158a7cea7c167f6cc2a5117` | `nws/cli_list_SFO_20260924T224330Z.json` |
| 28 | 22:43:39.932 | 22:43:40.104 | `N/products/8c7457d2-7454-4817-b173-cb5cc80329bf` | 200 | 4,914 | `3e9e599279a386188eeee9f5458aabd4a7a8fb212468d8c8a2e53be6d388a0ea` | `nws/cli_product_CLISFO_8c7457d2_20260924T224339Z.json` |
| 29 | 22:43:51.793 | 22:43:51.952 | `N/points/41.7842,-87.7553` | 200 | 3,915 | `b954103f1b6b125bc69397f1ec31a38598fa2e154fed717dc184ab222ff7ece6` | `nws/points_KMDW_20260924T224351Z.json` |
| 30 | 22:43:53.185 | 22:43:53.259 | `N/points/44.8831,-93.2289` | 200 | 3,937 | `93f5baf4e7b2bddd2d76b373e754a2717ac02997a7c71c03d5c34c7fe3d59cad` | `nws/points_KMSP_20260924T224353Z.json` |
| 31 | 22:43:54.488 | 22:43:54.590 | `N/points/42.3606,-71.0097` | 200 | 3,919 | `e5476dbb72d0205779e65ecb2f40fa2461b0e8d3ac8616b18750c353937e05c2` | `nws/points_KBOS_20260924T224354Z.json` |
| 32 | 22:43:55.815 | 22:43:55.909 | `N/points/33.6301,-84.4418` | 200 | 3,920 | `ddbc66dc3a58b6a1d5a8cf132b9cce99f23289efed53c21735075697af0af52e` | `nws/points_KATL_20260924T224355Z.json` |
| 33 | 22:43:57.138 | 22:43:57.266 | `N/points/25.7881,-80.3169` | 200 | 3,936 | `e1dee5f539b1512d9c620520444e7445c3c12907512b93e8d4bb37af0b9dca1e` | `nws/points_KMIA_20260924T224357Z.json` |
| 34 | 22:43:58.493 | 22:43:58.566 | `N/points/30.1831,-97.6799` | 200 | 3,919 | `57aca0dbe7feb6290aae199b567302ad1366c47d6e7dda36700ef0d6131eae26` | `nws/points_KAUS_20260924T224358Z.json` |
| 35 | 22:43:59.794 | 22:43:59.892 | `N/points/39.8466,-104.6562` | 200 | 3,918 | `075c73371eb3be0281bc4c835b12eba408733be440b2d9455be6826e9a768361` | `nws/points_KDEN_20260924T224359Z.json` |
| 36 | 22:44:01.121 | 22:44:01.390 | `N/points/33.4278,-112.0037` | 200 | 3,925 | `05437f7d1d40ce0a1105555cb08fe25ea1c55330e4ada898db4a705c78a8b954` | `nws/points_KPHX_20260924T224401Z.json` |
| 37 | 22:44:02.620 | 22:44:02.729 | `N/points/33.9382,-118.3866` | 200 | 3,933 | `4499b165535612ede4ee24de9cc33a3baa2e57cddb37c70c456e47dc53c80c36` | `nws/points_KLAX_20260924T224402Z.json` |
| 38 | 22:44:03.956 | 22:44:04.087 | `N/points/37.6197,-122.3656` | 200 | 3,943 | `4163c4bea67d71c047ddebfa15adc2ccfbcce36ceef08125c6b941b40928419e` | `nws/points_KSFO_20260924T224403Z.json` |
| 39 | 22:44:05.310 | 22:44:05.389 | `N/points/47.4447,-122.3144` | 200 | 3,927 | `530c3fadd680eeb591ebe3b5915fe712ab7b0a98335200b6b6809fa8ca9d7183` | `nws/points_KSEA_20260924T224405Z.json` |
| 40 | 22:44:22.605 | 22:44:22.795 | `N/products/types/PFM/locations/LOX` | 200 | 12,313 | `26bbaaae47fe35d30ae68d5dc859220ea8c65518043a8a1132a9f6c719a3eba9` | `nws/pfm_list_LOX_20260924T224422Z.json` |

The `/points` coordinates are approximate ASOS station coordinates typed by the agent. They are
not read from `/stations/{ICAO}`. PR 1 of the design re-derives each grid cell from the
station's own published coordinates.

## Findings

Each finding below is **observed** in the stored responses unless it says it is inferred.

### F1. Multi-event listing is not supported this way

`/markets?event_ticker=A,B,...` (#2) returned `{"cursor":"","markets":[]}` with HTTP 200. The
event `KXHIGHNY-26SEP25` exists (#10), so a comma-separated `event_ticker` is not a multi-event
filter on this host. An empty 200 is therefore not evidence that a market is absent. A collector
must use one event (or series) per request, and must treat an empty listing for an expected
event as an anomaly (`EVENT_NOT_LISTED`), never as "no market".

### F2. The weather catalog

`/series?category=Climate and Weather` (#1, #3) returned 411 series:
- by frequency: custom 132, daily 121, annual 50, monthly 43, one_off 33, weekly 18,
  hourly 14;
- the listing has no cursor. Nothing in the response says it is complete, so it is treated as
  a **complete-looking single page**, not as a proven complete catalog.

Recurring **daily** families that exist in the catalog:
- **High temperature, US cities.** Two generations:
  1. **Original KX series with NWS-era terms**, now on GLOBALTEMPERATURE: `KXHIGHNY`,
     `KXHIGHCHI`, `KXHIGHMIA`, `KXHIGHAUS`, `KXHIGHDEN`, `KXHIGHLAX`, `KXHIGHPHIL`.
  2. **`KXHIGHT*` series**: ATL, BOS, DAL, DC, EWR, HOU, LV, MIN, NOLA, OKC, PHX, SAN/KSAN,
     SATX, SDF, SEA, SFO, TTN.
- **High temperature, international**, e.g. `KXHIGHTEGLL` London, `KXHIGHTRJTT` Tokyo, most on
  INTERNATIONALTEMPERATURE terms.
- **Low temperature:** `KXLOWT*` for most of the same cities, plus older `KXLOW*` series on
  CITYLOW terms.
- **Rain:** `KXRAIN` ("Where will it rain daily"), `KXRAINNYC`, `KXRAINSEA`, `KXRAINDC`,
  `KXRAINDNYC`, `KXRAINDPARIS`, `KXRAIND`.
- **Other:** `KXCITIESWEATHER`, `KXHIGHUS`, `KXDVHIGH` (Death Valley), and `KXBIGGESTQUAKE`,
  an earthquake series that is also filed under this category.
- **Hourly intraday:** `KXTEMP*H`/`*HS`. Some settle on Synoptic Data or on a Kalshi index.
- **Legacy duplicates** with `volume_fp` 0: `HIGHNY`, `HIGHCHI`, `HIGHAUS`, `HIGHMIA`,
  `HIGHUS`, `KXDENHIGH`, `KXHIGHOU`, `KXHOUHIGH`, `KXDVHIGH`, `KXLOWNYC`, `KXLOWNY`.

`series.settlement_sources`:
- **The 7 original KX city high series and every US `KXHIGHT*`/`KXLOWT*` series** name **The
  Weather Company** (`https://weather.com/kalshi`) and have `contract_terms_url` GLOBALTEMPERATURE,
  `fee_type` quadratic and `fee_multiplier` 1. That is the same as KXHIGHNY (docs/SETTLEMENT.md
  §2). The exceptions are the NWS-era duplicates (`KXHIGHHOU`, `KXHIGHOU`, `KXHOUHIGH`,
  `KXDENHIGH`, `KXDVHIGH`), the older `KXLOW*` CITYLOW series and the composite `KXHIGHUS`.
- **The NWS-era series** name the NWS CLI page for the exact station:
  - `HIGHCHI`: `site=LOT&product=CLI&issuedby=MDW`;
  - `HIGHAUS`: `EWX/AUS`;
  - `HIGHMIA`: `MFL/MIA`;
  - `KXDENHIGH`: `BOU/DEN`;
  - `HIGHNY`: `OKX/NYC`.

  This is an independent, older record of the office/station pairing for four of the selected
  cities.

Lifetime `volume_fp` (contracts, as the source states it) for the daily US high-temperature
series, highest first:

| series | volume_fp |
|---|---|
| KXHIGHLAX | 169,783,077 |
| KXHIGHNY | 145,619,580 |
| KXHIGHCHI | 110,698,260 |
| KXHIGHMIA | 100,219,839 |
| KXHIGHAUS | 77,634,396 |
| KXHIGHDEN | 51,092,105 |
| KXHIGHPHIL | 41,759,409 |
| KXHIGHTSFO | 18,430,076 |
| KXHIGHTPHX | 17,134,363 |
| KXHIGHTSEA | 16,914,120 |
| KXHIGHTATL | 16,441,539 |
| KXHIGHTBOS | 15,935,219 |
| KXHIGHTDAL | 13,512,332 |
| KXHIGHTDC | 12,899,854 |
| KXHIGHTLV | 12,685,717 |
| KXHIGHTHOU | 10,256,195 |
| KXHIGHTMIN | 9,640,069 |
| KXHIGHTOKC | 8,205,323 |
| KXHIGHTNOLA | 7,093,812 |
| KXHIGHHOU (NWS-era Houston) | 6,416,018 |
| KXHIGHTSATX | 6,102,539 |
| KXHIGHTSAN | 86,149 |
| KXHIGHTTTN | 51,596 |
| KXHIGHTEWR | 48,673 |
| KXHIGHTSDF | 33,723 |

Other daily families: `KXRAIN` 36,427,078; `KXRAINNYC` 30,548,636; `KXLOWTNYC` 13,367,368;
`KXLOWTCHI` 9,498,582.

### F3. Open events, rules, stations and close times

The 17 high-temperature series queried (#4 to #20) and `KXLOWTCHI` (#21) each returned
**exactly 12 open markets: 6 for target 2026-09-24 and 6 for target 2026-09-25**, with no
cursor. Every market is `status: active` and binary. Each event has two tail brackets (`less`
and `greater`) and four 2-degree `between` brackets. Common to every series:
- `open_time` = **14:00:00Z on D-1** (for example, `KXHIGHCHI-26SEP25` opened
  2026-09-24T14:00:00Z; its `created_time` was 09:34:33Z);
- `expected_expiration_time` = 19:00:00Z on D+1;
- `latest_expiration_time` = 14:00:00Z on D+7;
- `can_close_early: true`.

`rules_primary` template (TWC era), observed for every series:
> If the maximum temperature recorded at <City> (CLI<XXX>) for <Mon DD, YYYY>, is
> <greater than / less than / between> ... according to The Weather Company, then the market
> resolves to Yes.

The low-temperature series say "minimum temperature". `rules_secondary` is the same TWC text
recorded for KXHIGHNY in docs/SETTLEMENT.md §2. `early_close_condition` says:
> The Last Trading Time will be 11:59 PM local time on <date> ... Expiration will occur on the
> sooner of the first 7:00 or 8:00 AM ET following the release of the data ... or one week after.

The table below is the CLI code named in the rules text, `close_time` for target D (the same
UTC clock time for D=09-24 and D=09-25), and the D and D+1 event totals at 22:40Z to 22:42Z.
Volumes and open interest are in contracts.

| series | rules station | close_time (UTC, D+1) | local clock at close (DST) | D=09-24 vol / OI | D+1=09-25 vol / OI |
|---|---|---|---|---|---|
| KXHIGHNY | New York City (CLINYC) | 05:00Z | 01:00 EDT | 104,713 / 53,560 | 10,082 / 8,223 |
| KXHIGHCHI | Chicago (CLIMDW) | 06:00Z | 01:00 CDT | 75,842 / 40,222 | 6,016 / 5,012 |
| KXHIGHMIA | Miami (CLIMIA) | 05:00Z | 01:00 EDT | 187,400 / 104,469 | 8,192 / 6,806 |
| KXHIGHAUS | Austin (CLIAUS) | 06:00Z | 01:00 CDT | 48,210 / 34,656 | 3,676 / 3,215 |
| KXHIGHDEN | Denver (CLIDEN) | 07:00Z | 01:00 MDT | 45,279 / 30,331 | 3,258 / 2,622 |
| KXHIGHLAX | Los Angeles (CLILAX) | 08:00Z | 01:00 PDT | 356,060 / 238,554 | 10,550 / 9,189 |
| KXHIGHPHIL | Philadelphia (CLIPHL) | 05:00Z | 01:00 EDT | 27,790 / 18,169 | 5,525 / 4,732 |
| KXHIGHTSFO | San Francisco (CLISFO) | 08:00Z | 01:00 PDT | 79,482 / 47,010 | 1,532 / 1,421 |
| KXHIGHTPHX | Phoenix (CLIPHX) | 07:00Z | **00:00 MST** (Arizona keeps no DST) | 25,067 / 15,800 | 3,737 / 3,161 |
| KXHIGHTSEA | Seattle (CLISEA) | 08:00Z | 01:00 PDT | 114,738 / 37,070 | 2,590 / 1,855 |
| KXHIGHTATL | Atlanta (CLIATL) | 05:00Z | 01:00 EDT | 36,684 / 23,537 | 2,501 / 2,376 |
| KXHIGHTBOS | Boston (CLIBOS) | 05:00Z | 01:00 EDT | 46,271 / 25,393 | 3,499 / 3,205 |
| KXHIGHTDAL | Dallas (CLIDFW) | 06:00Z | 01:00 CDT | 41,179 / 28,401 | 4,310 / 4,002 |
| KXHIGHTDC | Washington DC (CLIDCA) | 05:00Z | 01:00 EDT | 18,498 / 11,705 | 3,168 / 2,770 |
| KXHIGHTLV | Las Vegas (CLILAS) | 08:00Z | 01:00 PDT | 22,922 / 15,868 | 3,831 / 3,472 |
| KXHIGHTMIN | Minneapolis (CLIMSP) | 06:00Z | 01:00 CDT | 43,419 / 28,970 | 945 / 805 |
| KXHIGHTHOU | Houston (CLIHOU) | 06:00Z | 01:00 CDT | 17,594 / 12,665 | 2,568 / 2,427 |
| KXLOWTCHI | Chicago (CLIMDW), minimum | 06:00Z | 01:00 CDT | 4,199 / 3,449 | 781 / 528 |

**Close time.** In every series, `close_time` equals **00:00 local standard time (LST) at the
end of target day D**: 05:00Z Eastern, 06:00Z Central, 07:00Z Mountain and 08:00Z Pacific.
- This is 01:00 local daylight time in DST cities, 61 minutes after the "11:59 PM local time"
  in `early_close_condition`.
- Phoenix keeps no DST, so its close is 00:00 local, one minute after 23:59.
- Inference: only "midnight LST", the end of the NWS climate day, fits every city. The two
  alternatives fail:
  - "23:59 local civil time" would give 04:59Z/05:59Z/06:59Z/07:59Z in summer;
  - "local civil midnight" would give 04:00Z/05:00Z/06:00Z/07:00Z in summer.
- This extends the KXHIGHNY observation (23:59 ET wall time until August 2026, 05:00Z since;
  ADR 0030) to every current city. **No winter (standard-time) close under this convention has
  been observed yet.** The inference predicts no UTC change on 2026-11-01. Re-check it then.

**Documentary conflict, recorded and not resolved.** `early_close_condition` states "11:59 PM
local time", while `close_time` is 00:00 LST. That puts them 61 minutes apart during DST. ADR
0030 treats `close_time` as the trading close and proves it with a post-close read.

**Top of book on D+1 at about 22:41Z.** Most brackets showed a 1-cent spread. `liquidity_dollars`
is `"0.0000"` on every market, so that field carries no information. Examples:
- CHI `B68.5`: 0.37/0.38;
- SEA `B61.5`: 0.48/0.49;
- MIA `B91.5`: 0.40/0.41.

`yes_bid_size_fp`/`yes_ask_size_fp` are present in the listing.

### F4. Depth (#24, #25)

- `KXHIGHCHI-26SEP25-B68.5`: 30 YES bid levels and 39 NO bid levels. Best YES bid 0.37; best NO
  bid 0.62, which implies a YES ask of 0.38.
- `KXHIGHTSEA-26SEP25-B61.5`: 35 YES levels and 39 NO levels. Best YES bid 0.48; best NO bid
  0.51, which implies a YES ask of 0.49.
- Each book is about 1.4 KB, in the same `orderbook_fp` shape that `kalshi.summarize_orderbook`
  already parses.

### F5. Settlement history for one city (#23)

`KXHIGHTSEA` `status=settled`, `limit=200`, one page only:
- **The cursor was present, so the listing is PARTIAL.** Nothing older was fetched.
- **Continuity.** It covers 34 consecutive target days, 2026-08-21 to 2026-09-23, with no
  gaps. 08-21 shows only 2 of its 6 brackets because the page limit cut it off.
- **Per event.** Every complete event had exactly one YES bracket, and an integer
  `expiration_value` (for example 67.00 for 09-23).
- **Timing.** `close_time` was 08:00Z on D+1 throughout. `settlement_ts` fell between 14:09Z
  and 14:18Z on D+1, which is 07:09 to 07:18 PDT.
- **Volume.** Daily event volume ranged from 11,656 to 113,553 contracts.

This proves continuity for **one** T-series city only. The other cities' continuity is verified
here only for the two open days. PR 2 of the design audits the rest historically.

### F6. NWS station and office mapping

- **CLI location list (#26).** It has 627 codes, and every station code named by a Kalshi rule
  above is present: NYC, MDW, MIA, AUS, DEN, LAX, PHL, SFO, PHX, SEA, ATL, BOS, DFW, DCA, LAS,
  MSP, HOU. The list gives no names (every value is null), so it proves only that each code
  exists.
- **CLISFO (#27, #28).**
  - The list holds 14 issuances over 7 days: about 00:30Z (17:30 PDT) and about 08:30Z (01:30
    PDT) daily. So `api.weather.gov` keeps about **7 days** of CLI, as it does for NYC.
  - The newest final (`CDUS46 KMTR 240840`, issued "140 AM PDT THU SEP 24 2026") is headed
    "THE SAN FRANCISCO AIRPORT CLIMATE SUMMARY FOR SEPTEMBER 23 2026". Its time column is
    labelled `(LST)`.
  - YESTERDAY MAXIMUM was 78 at 3:53 PM.
  - So **CLISFO is San Francisco International Airport (KSFO)**, issued by WFO MTR, not
    downtown San Francisco.
  - Station names for the other codes (for example CLIMDW = Chicago Midway, CLIAUS =
    Austin-Bergstrom) follow the NWS naming convention and, for MDW/AUS/MIA/DEN, the NWS-era
    series URLs. They are **not yet verified from product text**; that is PR 1 work.
- **`/points` (#29 to #39)** returned:

| station | gridId | gridX,gridY | timeZone | forecastZone | county | radar |
|---|---|---|---|---|---|---|
| KMDW | LOT | 72,69 | America/Chicago | ILZ104 | ILC031 | KLOT |
| KMSP | MPX | 110,68 | America/Chicago | MNZ060 | MNC053 | KMPX |
| KBOS | BOX | 73,101 | America/New_York | MAZ015 | MAC025 | KBOX |
| KATL | FFC | 49,81 | America/New_York | GAZ055 | GAC063 | KFFC |
| KMIA | MFL | 105,51 | America/New_York | FLZ074 | FLC086 | KAMX |
| KAUS | EWX | 158,87 | America/Chicago | TXZ192 | TXC453 | KEWX |
| KDEN | BOU | 75,66 | America/Denver | COZ040 | COC031 | KFTG |
| KPHX | PSR | 161,57 | America/Phoenix | AZZ543 | AZC013 | KIWA |
| KLAX | LOX | 149,41 | America/Los_Angeles | CAZ366 | CAC037 | KSOX |
| KSFO | MTR | 85,98 | America/Los_Angeles | CAZ508 | CAC081 | KMUX |
| KSEA | SEW | 124,60 | America/Los_Angeles | WAZ316 | WAC033 | KATX |

- **PFM LOX (#40).**
  - 31 issuances over about 6.6 days (2026-09-18T06:26Z to 2026-09-24T20:22Z), about 4.7 a day,
    all `FOUS56 KLOX`.
  - Two of them were only 10 minutes apart (03:17Z and 03:27Z), an update or correction.
  - So PFM exists for a western office too.
  - PFM retention is also about a week, and issuances must be de-duplicated by product id, not
    by time.
  - Whether each office's PFM carries a block for the settlement station itself is **not**
    verified here (PR 1).

### F7. Families checked but not currently trading

`KXRAINNYC` (#22) returned no open markets (`{"cursor":"","markets":[]}`). That fits a dormant
or seasonal series, but one empty listing is not proof of absence (see F1).

## What this verification does not establish

- Settlement agreement between Kalshi `expiration_value` and the NWS CLI final for any of the 11
  new cities. KXHIGHNY's 739/739 agreement (docs/SETTLEMENT.md §7) does not transfer to them.
- Station names from product text for every city except SFO (and NYC, from Gate 2).
- The PFM point for each settlement station, and gridpoint forecast sizes.
- Winter close times.
- Catalog completeness (the series listing has no pagination proof).
