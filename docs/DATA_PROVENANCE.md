# Data Provenance, Freshness and Source Health

## 1. Access hierarchy

For each source, use the highest option available (`edge_lab.sources.AccessTier`):

1. Official structured API
2. Official download or bulk feed
3. Permitted public structured endpoint
4. RSS/Atom or another legitimate machine-readable feed
5. Simple HTTP fetch of a public page
6. Browser automation, and only when nothing above exists

Never bypass authentication, CAPTCHAs, paywalls, rate limits or technical access controls.
Record the terms of use in the registry before collecting. Playwright is a fallback, not a
default. Browser automation is used only when a legitimate structured source is unavailable.

## 2. What every snapshot records

Each fetched payload is one immutable row in `snapshots` (SQLite, `edge_lab.storage`).

| Question | Column(s) |
|---|---|
| What was retrieved? | `source`, `source_id`, `kind`, `entity_id`, `payload_json` |
| From where? | `url` (as requested), `final_url` (after redirects) |
| When was it published? | `source_timestamp_utc`, when the source provides one |
| When did we receive it? | `fetched_at_utc` (receipt time, UTC) |
| What did the server say? | `http_status`, `content_type`, `attempts`, `fetch_duration_ms` |
| Exact content identity | `payload_sha256` (canonical JSON), `raw_sha256` (exact bytes), `payload_bytes` |
| Which code interpreted it? | `parser_version`, `schema_version` (from the source registry) |
| Did the upstream schema change? | `shape_sha256`: a hash of key paths and types, ignoring values |

Evidence rules:

- **Rows are immutable.** SQLite triggers abort any `UPDATE`, `DELETE`, or `INSERT OR REPLACE`
  of an existing row in `snapshots`. `source_health` rows cannot be updated or deleted, and a
  `collection_runs` row can be finished once and never deleted. So a recorded failure cannot
  be rewritten as success. The triggers guard against mistakes, not against someone with
  direct database access.
- **Repeated identical payloads are kept.** They prove the information stayed available.
- **Canonical JSON is stored.** The exact bytes are not. `raw_sha256` proves which bytes were
  received but cannot recreate them. See ADR 0002 for why, and for when to revisit.
- Milestone 1 rows predate the provenance columns, so those columns are `NULL` for them.
- **Documents (PDF, text products, HTML) are stored as exact bytes** in `document_blobs`,
  content-addressed by SHA-256. Each retrieval is a row in `document_retrievals`, holding
  the requested and final URL, time, HTTP status, content type, byte length, hash, doc
  type, and related series/market. Re-fetching an unchanged document adds a retrieval row;
  a changed document becomes a new version, and the old one is kept. Both tables are
  append-only (triggers). Inserting an existing hash never replaces the stored bytes.
- Snapshots record `retry_reasons_json`: why each failed attempt before success failed
  (e.g. `["http_429"]`).
- Requests to one source are paced (`edge_lab.http.Pacer`): Kalshi 0.6 s, NWS 0.5 s,
  IEM 1 s. Kalshi's public endpoints returned 429 at about 4 req/s with no `Retry-After`
  (probe 2026-09-22), so pacing is the normal control flow; retries use jittered
  exponential backoff.

## 3. Source health

Each source in each run writes one `source_health` row. The fields are `run_id`, `source_id`,
start/complete timestamps, `duration_ms`, `status`, `records`, `payload_bytes`, `http_errors`,
`retries`, `anomalies_json` and `error`.

| status | meaning | enforced by the schema |
|---|---|---|
| `ok` | nothing went wrong | no error |
| `partial` | some evidence was stored, but an error or anomaly occurred | must carry an error or an anomaly |
| `failed` | nothing was stored | must carry an error, and records = 0 |

- Status comes from what was **actually stored** (counted in `snapshots`), not from what a
  collector says it did.
- One failing source never aborts the others. A run is `succeeded`, `partial` or `failed`, and
  `edge-lab collect` exits non-zero unless every source is `ok`.
- **Anomalies** are completeness or shape problems that are not exceptions. Examples: a
  paginated market list where later pages were not fetched, or an empty market list.
- `edge-lab health [--json] [--profile P]` shows the latest status, last success, last error,
  anomalies, and per-kind freshness for each active source **in the chosen profile**. It
  exits non-zero unless every one of those sources' latest run was `ok` **and** every kind
  is fresh. Profiles follow the job that collects each source (`SourceSpec.collected_by`,
  issue #16):

  | Profile | Judges |
  |---|---|
  | `routine` (default) | exactly the sources `edge-lab collect --source all` runs: `kalshi_public`, `nws_api`, `nws_cli_central_park` |
  | `settlement` | `kalshi_settlement` (`edge-lab settlement collect`) |
  | `forward` | the EXP-001 Stage-B schedule, judged by cadence: exit 0 only if the last closed target day is VALID (`edge-lab forward status`). A 5-minute order-book `max_age` means nothing for a once-a-day job. |
  | `all` | every active source against its `max_age` (the strict global view) |

  So a clean routine run is not reported unhealthy just because a deliberately separate
  collector did not run. Profiles narrow *which* sources are judged, never *how*: a stale
  or failed source in the profile still fails it. `--source X` (repeatable) judges exactly
  the listed sources.
  Per-kind freshness is based on the *latest receipt of any entity of that kind*. It is a
  collector-liveness signal, not a guarantee that every entity is fresh. Decision code checks
  its own inputs with `require_fresh`.
- The HTTP client refuses credential-bearing headers (Authorization, cookies, API keys,
  signatures, tokens).
- Retries spent on a fetch that ultimately failed are counted in `retries`. Undecodable
  responses are errors, but they are not counted as `http_errors`.

The event shape is kept flat and stable on purpose. A metrics exporter (Prometheus or cloud
monitoring) can later read `source_health` without changing any collector.

## 4. Freshness (fail closed)

`edge_lab.freshness`:

- `assess(ts, max_age, now)` returns `FRESH`, `STALE` or `UNKNOWN`. A missing, naive
  (no timezone) or unparseable timestamp is `UNKNOWN`. So is one far in the future. None of
  these ever count as fresh.
- `combine(*states)` returns the worst state. A value derived from any stale input is stale.
- `require_fresh(state, what=...)` raises `StaleDataError` unless the state is `FRESH`.
  **Future opportunity, decision and execution code must call it on every input.**
- The maximum age for each kind of payload lives in the source registry. A kind with no max
  age is `UNKNOWN`.

The difference from Brisket is that last-known-good data is **never** silently used as
current here. It may be read for research, comparison, reconstruction and diagnostics.
Anything that could become a trading decision must carry freshness through, and must fail
closed.

There are two different clocks. `fetched_at_utc` says when *we* last saw the data.
`source_timestamp_utc` says when the *source* last updated it. A freshly fetched payload can
still contain stale content, such as an NWS forecast with an old `updateTime`. Decision code
must judge the clock that matters for its input.

## 5. Evidence layers (documents, news, and LLM use)

These layers are never collapsed into one opaque result:

```
SOURCE_DOCUMENT (raw bytes/JSON, immutable)
  → EXTRACTED_TEXT (deterministic extractor + version)
  → STRUCTURED_FACTS (parsed fields, events, entities; versioned parser)
  → MODEL_INTERPRETATION (LLM output; model id, prompt version, input hashes)
  → FEATURE (deterministic transform, point-in-time, with freshness)
```

Every layer points to the hash of the layer it came from. An LLM summary is not evidence.
It is an interpretation of evidence. Retrieved text is untrusted data, and it is passed to
models as delimited data with no tool authority. See `docs/NEWS_WEB_INGESTION.md`.

## 6. Historical archives committed as fixtures (one-time backfills)

Some evidence comes from one-time, manually run, paced backfills rather than from
`edge-lab collect`. They are not scheduled jobs.

| Source id | What | Where | Identity |
|---|---|---|---|
| `iem_afos_clinyc` | NWS CLI Central Park, exact archive bytes | `tests/fixtures/gate2/`, `tests/fixtures/gate3/iem_clinyc_*.txt.gz` | request URL + response SHA-256 in `tests/fixtures/gate3/fetch_manifest.json` (gate 3) and the Gate 2 report |
| `iem_afos_pfmokx` | NWS OKX Point Forecast Matrices, Central Park block, **exact-substring extracts** (ADR 0011) | `tests/fixtures/gate3/pfm_extracts_YYYY.jsonl.gz` | per product: SHA-256 of the full product; per month: request URL, status, bytes, response SHA-256 (`fetch_manifest.json`) |
| `kalshi_settlement` | settled KXHIGHNY/HIGHNY markets as returned | `tests/fixtures/gate3/kalshi_markets_all_2026-09-22.json.gz` | file SHA-256 in the dataset manifest |

Point-in-time rule for forecasts: the **issuance** time is the WMO header time (checked
against the product's local issuance line). The **availability** time used by EXP-001 is
issuance + 30 min (ADR 0010). Derived datasets record both, plus the SHA-256 of every input
file (`experiments/EXP-001-kxhighny-nws-vs-market/gate3/dataset_manifest.json`), and CI
rebuilds them byte for byte.

## 6a. Forward Stage-B capture (scheduled, read-only; ADR 0012)

`edge-lab forward capture --phase {pfm,decision,recheck}` runs from systemd timers on the
Chase Upside VPS (`deploy/vps/`).
- **Snapshots:** `nws_pfm` `pfm_list`/`pfm_product` and `kalshi` `event`/`markets`/`orderbook`.
- **Capture record:** every attempt writes one immutable `forward_captures` row (schema v4)
  with the phase, target date, window, status, reasons, and links to the snapshot ids it
  stored.
- **Timing gate:** each phase checks its window before any network work. An out-of-window
  run is recorded as `rejected_out_of_window` and fetches nothing.
- **Duplicates and reruns:** a rerun after a complete capture is `skipped_duplicate`. A
  killed run leaves no complete row, and a restart inside the window appends a new attempt.
  The latest complete attempt counts.
- **Day validity:** `edge-lab forward status` re-derives each target day's validity from
  the stored evidence alone: event identity, every open bracket booked inside [decision − 5
  min, decision], every bracket re-checked 10–15 min after its own decision book, and the
  forecast selected by the frozen availability rule. A day is VALID or INVALID, never
  partial.
- **Smoke rows:** rows with `mode = 'smoke'` (injected clocks in tests or manual smoke
  checks) are never evidence.

## 6b. Planned multi-venue sources (read-only adapters; 2026-09-23 directive)

Three sources are registered as `PLANNED`, with `collected_by=()`. Each has adapter code and
fixture tests, but no collector job, no timer and no health profile. Evidence is in
`experiments/multi_venue/`.

| Source id | Adapter | Access | What it is not |
|---|---|---|---|
| `polymarket_us_public` | `edge_lab.polymarket_us` | the public gateway `gateway.polymarket.us`, keyless, 20 req/s per IP. One bounded smoke GET was recorded | Not Polymarket International; no authenticated host. BBO is never a quote; fees are UNSUPPORTED |
| `the_odds_api` | `edge_lab.odds_api` | The Odds API v4, free tier, a `READ_ONLY_DATA_FEED` key in `EDGE_LAB_ODDS_API_KEY` (not installed). Fixtures only | Offered odds and de-vigged probabilities are never executable prices |
| `novig_public_data` | `edge_lab.novig_data` | data.novig.com daily CSVs, no authentication. One manual read of the index and one day | End-of-day research data, never an executable quote. The live API is NEEDS_ACCESS |

Provenance rules specific to these adapters:

- **Catalog coverage.** A listing read is COMPLETE only when every page succeeded, the last
  page came back empty, and no filter was applied. A short page is not proof of the end,
  because a server may cap the page size. A filtered scan is PARTIAL and names its filter.
  A PARTIAL or FAILED read is never evidence that a market does not exist
  (`discovery.CatalogCoverage`).
- **Units.** Units are recorded as the source states them. Polymarket US prices are USD per
  YES contract, and its quantities are contracts that may be fractional. Novig trade prices
  are `cost/qty`, but its market OHLC is in cents. The Odds API keeps raw American or decimal
  odds.
- **Credentials.** A credentialed source stores only redacted URLs. For example, `url` and
  `final_url` in `snapshots` read `apiKey=REDACTED` (`docs/SECURITY.md`).
- **Terms.** Recorded in each `license_notes`. The Polymarket US website Terms of Service
  could not be read without a browser and are not reviewed. Until they are, data is for
  research storage only and is not redistributed.

## 7. Adding a source

1. Choose the highest access tier available. Read the terms and write them in `license_notes`.
2. Add a `SourceSpec` to `src/edge_lab/sources.py` with `status=PLANNED` and a `max_age`
   per kind.
3. Write the collector using `edge_lab.http.fetch_json_result`, which is GET-only, retries
   within limits, and records provenance. Save through `SnapshotStore.save_snapshot(...,
   fetch=..., source_id=..., parser_version=..., schema_version=...)`. Append completeness
   problems to `anomalies` rather than hiding them.
4. Add fixture-based tests with recorded, non-secret sample payloads. Tests never touch the
   network.
5. Wire the collector into its job (`edge-lab collect`, `settlement collect` or
   `forward capture`) through `_run_source`, set `collected_by` to that job's health
   profile, and set `status=ACTIVE`.
   Paginated listings use `kalshi.paginate_markets`-style bounded cursor following
   (every page stored, repeated cursor = loop, page cap raises), never "page one only".
6. If the source needs credentials, stop. That needs owner approval (`docs/SECURITY.md`).
