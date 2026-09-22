# 0002 — Immutable JSON snapshots with per-fetch provenance

Status: Accepted (2026-09-22)

**Problem.** Research results must trace back to exactly what we received and when. Milestone
1 stored canonical JSON plus a hash, but no HTTP metadata, no parser version, no way to
detect schema drift, and nothing to stop rows being modified.

**Alternatives.** (a) Store exact response bytes (BLOB) alongside the JSON. (b) Store
canonical JSON plus a hash of the raw bytes. (c) Use files on disk (JSONL/Parquet) instead
of SQLite.

**Decision.** (b), in SQLite, with a schema migration to v2 via `PRAGMA user_version`. Every
snapshot gains `source_id`, `final_url`, `http_status`, `content_type`, `payload_bytes`,
`raw_sha256`, `attempts`, `fetch_duration_ms`, `parser_version`, `schema_version` and
`shape_sha256`. `BEFORE UPDATE/DELETE` triggers make snapshots append-only. Milestone 1
databases migrate in place, and their old rows keep NULL provenance.

**Tradeoffs.** Exact bytes cannot be recreated. We can prove *which* bytes arrived, but JSON
number formatting and duplicate keys are lost. That is acceptable for JSON APIs, where we
depend only on the parsed values. It halves storage. The triggers can be bypassed by anyone
with direct DB access. They protect against mistakes, not against someone acting in bad faith.

**Reconsider if** a parsing dispute needs byte-exact evidence, or when non-JSON documents
(HTML/PDF) arrive. Those need a raw-bytes table regardless (planned schema v3).
