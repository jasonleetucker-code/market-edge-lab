# Gate 2 evidence manifest

Every file here is either an exact copy of retrieved bytes, or a deterministic derivation
from one with the tool named. The same bytes are also stored in the evidence database
(`document_blobs`/`document_retrievals`) by `edge-lab settlement collect`.

## Contract documents (exact bytes)

| File | Retrieved from | Retrieved (UTC) | HTTP | Type | Bytes | SHA-256 |
|---|---|---|---|---|---|---|
| `GLOBALTEMPERATURE_contract_terms.pdf` | https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf (series `contract_terms_url`) | 2026-09-22T18:35Z (curl) and 2026-09-22T18:48:40Z (collector); identical | 200 | application/pdf | 31,861 | `160281687cf9d3cd694c1c419522f3d53a8e1a6d4eddd40a7f5559c3a06211d0` |
| `GLOBALTEMPERATURE_product_certification.pdf` | https://assets.kalshi.com/regulatory/product-certifications/GLOBALTEMPERATURE.pdf (series `contract_url`; CFTC self-certification dated 2025-12-08) | 2026-09-22T18:35Z and 18:48:40Z; identical | 200 | application/pdf | 267,225 | `44fe7807bd884def6f2890813220a746802ac7bd3791d17c69607dbf66ba03fc` |
| `NHIGH_contract_terms.pdf` | https://kalshi-public-docs.s3.amazonaws.com/contract_terms/NHIGH.pdf (legacy NWS-era terms; not referenced by the current series, located via public search) | 2026-09-22T18:35Z (curl) | 200 | application/pdf | 27,530 | `06e2020bd18ac61ee51530e98f6ba3f677f9e07545b7660568384b4bcf686155` |

**Limitation.** These are the versions published on 2026-09-22. We hold no earlier versions,
so we cannot prove which version governed each historical event. Per-event wording *is*
versioned: every market carries its own `rules_primary`/`rules_secondary`, hashed as
`rules_hash` in the audit tables.

## Deterministic text extractions

`*.pypdf.txt` = `pypdf` 6.19.0 `PdfReader(path).pages[i].extract_text()`, pages joined with
`\n`. No LLM was used. Every quotation in `docs/SETTLEMENT.md` can be found verbatim in these
files (whitespace aside) and checked against the PDF.

## Market and observation data (fixtures, exact responses)

| Fixture (`tests/fixtures/gate2/`) | Content | Uncompressed SHA-256 |
|---|---|---|
| `kalshi_markets_window_a.json.gz` | every market object for target dates 2026-07-16..2026-09-21 from `GET /markets?series_ticker=KXHIGHNY&status=settled&limit=1000` and `GET /historical/markets?series_ticker=KXHIGHNY` (2026-09-22), canonical JSON | prefix `c9f7ee80bd2eff04` |
| `kalshi_markets_window_b.json.gz` | every market object for target dates in 2025 from `/historical/markets` (2026-09-22), canonical JSON | prefix `590bededcdb15acc` |
| `iem_clinyc_2026-07-15_2026-09-23.txt.gz` | IEM AFOS `retrieve.py?pil=CLINYC&sdate=2026-07-15&edate=2026-09-23&fmt=text&limit=9999`, exact bytes | `bd4c3ffb4cdadb8e4044109c3d52bf6dd6a9c1e195551257d3ec35d758a02c52` |
| `iem_clinyc_2025-01-01_2026-01-03.txt.gz` | same service, 2025-01-01..2026-01-03, exact bytes | `36bfafdeaceca88d1a4e4aaede86f4a4d88ebf8087c78d74ddaa671337472081` |
| `kalshi_markets_window_c.json.gz` | every market object for target dates in 2024 from `/historical/markets?series_ticker=KXHIGHNY` (it returns both HIGHNY- and KXHIGHNY- tickers; `?series_ticker=HIGHNY` returned 0 markets), canonical JSON | prefix `ffccd3d60e76d1df` |
| `iem_clinyc_2024-01-01_2025-01-03.txt.gz` | same IEM service, 2024-01-01..2025-01-03, exact bytes | `9615f448d9872f8c42f59a591a2dcb649cc0b31601183143e7057f437a797cfd` |

The market fixtures are *filtered* to the sample windows: the pages were parsed and
re-serialized. The raw pages themselves are stored as snapshots by the collector. The IEM
archive was cross-checked against the official NWS API: all 15 CLI products available from
`api.weather.gov` on 2026-09-22 parse identically to their IEM copies.
