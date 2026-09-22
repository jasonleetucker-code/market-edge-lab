# News, Web and Document Ingestion — Design (not implemented)

Status: **design only.** No news or web collectors exist. Research was done 2026-09-22.
Items marked UNVERIFIED could not be confirmed from a primary page. Re-check terms and
prices before building anything.

## Principle: specific sources, not "scrape the internet"

A generic crawler produces noise, legal exposure and prompt-injection surface. We add a
source only when a specific experiment needs it, and we pick the highest access tier
available (`docs/DATA_PROVENANCE.md` §1).

## Candidate sources by relevance

| Priority | Source | Mechanism | Cost / terms | Why |
|---|---|---|---|---|
| **Implemented** | Kalshi series/market rules (`settlement_sources`, `contract_url`, `contract_terms_url`, `rules_primary/secondary`), plus the contract PDFs | official API (already in our snapshots) plus PDF download | free, public | Settlement evidence. Rules can change, so keep versioned snapshots and diff them. |
| **Blocked** | The Weather Company page named in the KXHIGHNY rules (`weather.com/kalshi`) | none | Terms of Use (reviewed 2026-09-22) prohibit automated access without written permission | Named in the rules since 2026-08-14. Not collected; see `docs/SETTLEMENT.md` §6. |
| **Implemented** | NWS Daily Climate Report (CLI) for Central Park: `api.weather.gov/products/types/CLI/locations/NYC`, then `/products/{id}` (`productText`) | official API | free, public domain | The official observation. Several issuances a day, including corrections, so keep every one. |
| **Implemented** | Iowa Environmental Mesonet AFOS archive (`retrieve.py?pil=CLINYC`) | public archive | free academic service; be polite (≈1 request/s) | Historical CLI back to about 2008, for backfill and preliminary-vs-final studies. |
| Later (macro) | FRED/ALFRED | official API | free API key (needs owner approval to create); attribution required | `realtime_start`/`realtime_end` vintages are what make macro backtests point-in-time. |
| Later (filings) | SEC EDGAR (`data.sec.gov` submissions/companyfacts, Latest Filings Atom) | official API + feed | free; ≤10 requests/s; descriptive User-Agent with contact | Primary filings with exact acceptance times. |
| Later | Agency press-release RSS (BLS, Fed, SEC) | feed | free | Release timing, captured via conditional GET. |
| Discovery only | GDELT DOC 2.0 / GKG | public API / files | free, attribution | URLs and metadata only, and noisy. Not evidence of facts. |
| Only with approval | NewsAPI.org, Marketaux, Alpha Vantage news, Massive/Benzinga, Reuters/AP/Dow Jones | licensed API | UNVERIFIED as of 2026-09-22 (from vendor pricing pages seen by a research agent, not re-checked): NewsAPI's free tier is dev-only with a 24h delay (unsuitable); others roughly $29–$449+/mo; enterprise wires far more. Storage and redistribution rights vary per vendor. Re-check before any decision. | Paid. Each needs an owner decision and a terms review about storage and ML use. |
| Last resort | Browser automation (Playwright) | browser | — | Public pages only. Never behind a login or used to get past CAPTCHAs, paywalls or blocks. |

Legal note (not advice): *hiQ v. LinkedIn* ended in a consent judgment against the scraper.
*Meta v. Bright Data* and *X v. Bright Data* favoured logged-off scraping of public data on
their facts. None of these is a general licence. Terms of service, copyright, and storage of
full article text remain the real constraints. Store headline, URL, timestamp and metadata
unless the terms clearly allow storing full text.

## Libraries (when needed; none adopted yet)

- RSS: stdlib `urllib` with `If-None-Match`/`If-Modified-Since`, archiving the raw bytes and
  parsing with `xml.etree`. This fits the raw-immutable design and adds no dependency.
  `feedparser` (BSD-2, maintained) is the fallback for messy feeds.
- Article text: `trafilatura` (Apache-2.0, benchmarks best). Always keep the raw HTML;
  extracted text is a derived artifact tagged with the extractor version.
- PDFs (contract terms): store the raw bytes and hash. Text extraction is a separate,
  versioned layer.

## Future interface (sketch)

Documents follow the evidence layers in `docs/DATA_PROVENANCE.md` §5:

```python
class DocumentSource(Protocol):
    spec: SourceSpec                      # registry entry: tier, terms, max_age
    def discover(self, since: datetime) -> list[DocumentRef]: ...   # feed/index; cheap
    def fetch(self, ref: DocumentRef) -> FetchResult: ...            # raw bytes, GET-only

# Stored as: raw_documents(sha256, bytes, url, published_at, fetched_at, http meta)
#          → extracted_text(raw_sha256, extractor, extractor_version, text)
#          → document_facts(text_id, parser_version, facts_json)
#          → model_interpretations(input_sha256s, model_id, prompt_version, output_json)
```

The existing JSON snapshot table fits API payloads. Documents will need a raw-bytes table,
because canonical JSON does not apply to HTML or PDF. That is a planned schema v3 change,
made when the first document source is built.

## Prompt-injection handling (required before any LLM reads retrieved content)

Following OWASP LLM01 (Prompt Injection, 2025) and Microsoft's "spotlighting" approach:

1. Retrieved content is **data**. It never grants tools, and no action (network, files,
   trades, config) is ever triggered by content.
2. Pass content in randomized delimiters or datamarked form. The system prompt says the
   delimited text is data, and that any instructions inside it must be ignored.
3. Extraction models get **no tools** and must return schema-validated JSON. Invalid output
   is rejected, not repaired by guessing.
4. Keep hashes of all inputs, so every model output traces back to raw evidence.
5. Anything high-impact that is derived from content needs deterministic checks, and a human
   during early gates.
6. Add adversarial fixtures (documents containing injected instructions) to tests when the
   first LLM pipeline is built.

## Recommendation

1. **Gate 2 (next PR):** capture Kalshi rules and contract PDFs as versioned evidence. Add
   the NWS CLI collector. Review the weather.com terms before collecting anything from it.
2. **Backfill:** IEM CLI archive for historical observed maxima.
3. **Later:** ALFRED and EDGAR when macro or filing experiments are specified. GDELT only
   for discovery. No paid news API without an owner decision.

Sources: sec.gov/search-filings/edgar-application-programming-interfaces;
sec.gov/os/accessing-edgar-data; fred.stlouisfed.org/docs/api/fred/realtime_period.html;
fred.stlouisfed.org/docs/api/terms_of_use.html; docs.kalshi.com (get-series, get-market,
event metadata); mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?help=;
feedparser.readthedocs.io; gdeltproject.org/about.html; newsapi.org/pricing;
marketaux.com/pricing; pypi.org/project/trafilatura; genai.owasp.org/llmrisk/llm01-prompt-injection;
arxiv.org/abs/2403.14720 (spotlighting).
