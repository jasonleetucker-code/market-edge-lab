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

- **Rows are immutable.** SQLite triggers abort any `UPDATE` or `DELETE` on `snapshots`.
- **Repeated identical payloads are kept.** They prove the information stayed available.
- **Canonical JSON is stored.** The exact bytes are not. `raw_sha256` proves which bytes were
  received but cannot recreate them. See ADR 0002 for why, and for when to revisit.
- Milestone 1 rows predate the provenance columns, so those columns are `NULL` for them.

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
- `edge-lab health [--json]` shows the latest status, last success, last error, anomalies,
  and per-kind freshness for each active source.

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

## 6. Adding a source

1. Choose the highest access tier available. Read the terms and write them in `license_notes`.
2. Add a `SourceSpec` to `src/edge_lab/sources.py` with `status=PLANNED` and a `max_age`
   per kind.
3. Write the collector using `edge_lab.http.fetch_json_result`, which is GET-only, retries
   within limits, and records provenance. Save through `SnapshotStore.save_snapshot(...,
   fetch=..., source_id=..., parser_version=..., schema_version=...)`. Append completeness
   problems to `anomalies` rather than hiding them.
4. Add fixture-based tests with recorded, non-secret sample payloads. Tests never touch the
   network.
5. Wire the collector into `edge-lab collect` through `_run_source`. Set `status=ACTIVE`.
6. If the source needs credentials, stop. That needs owner approval (`docs/SECURITY.md`).
