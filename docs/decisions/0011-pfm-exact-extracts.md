# 0011 — Commit exact PFM extracts, not full archives

Status: Accepted (2026-09-22, Gate 3)

**Problem.** The Gate 3 forecast history is the NWS OKX Point Forecast Matrices
(PFMOKX), 2016-12 → 2026-09. The full archive is about 1.15 GB of text (125 IEM requests),
covering about 60 zones per product. EXP-001 needs only the Central Park (NYZ072) block,
and within it only the date, hour and Min/Max rows.

**Alternatives.**
- (a) Commit full products (1.15 GB; about 100 MB gzipped). Too big for the repository.
- (b) Commit parsed values only. Not evidence, since a parser bug could not be audited.
- (c) Commit an **exact-substring extract** per product, plus the SHA-256 of the full
  product and the request manifest (URL, status, bytes, SHA-256 of each monthly response).

**Decision.** (c).
- `nws_pfm.extract` keeps, verbatim, the WMO/AWIPS header lines, the first four zone lines
  (UGC, name, location, issuance), any issuance line, and the Date / hours / UTC /
  Min/Max rows.
- Every kept line is a line of the original product. Tests check that each extract line
  appears in the full product and parses identically to it.
- `scripts/fetch_gate3_evidence.py` writes
  `tests/fixtures/gate3/pfm_extracts_YYYY.jsonl.gz` (archive order, gzip mtime 0) and
  `fetch_manifest.json`.
- The dataset builder hashes these inputs into the dataset manifest.

**Tradeoffs.** The full raw bytes are not in git. They can be re-fetched from IEM and
checked against the recorded response hashes, but an IEM outage or change would lose that
path. Rows outside the kept set (temperature by hour, wind and so on) are not preserved.
Using them later requires a new fetch and a new dataset version.

**Reconsider when** a model needs other PFM rows, or a durable object store exists (see ADR
0008), at which point store the full monthly responses as exact bytes.
