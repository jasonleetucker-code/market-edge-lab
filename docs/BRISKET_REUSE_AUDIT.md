# Brisket Reuse Audit

This audits `jasonleetucker-code/riskittogetthebrisket` at `main` as of 2026-09-22. The goal
is to inherit its lessons without inheriting its technical debt. File references point into
that repository.

## Observed debt we avoid

- `CLAUDE.md` is 2,507 lines. Together with the always-imported Agent OS (971 lines), about
  200 KB loads into every session. The "universal" rules sit in a file whose name is tied to
  one provider.
- The same invariants are written out in `CLAUDE.md`, `AGENTS.md` and the Agent OS.
- `docs/WORK_CLAIMS.md` grew to about 312 KB. It has 122 rows, many with narratives in the
  cells, and no expiry.
- There are six or more overlapping state vocabularies, three source-health vocabularies,
  and no single adapter interface.
- The "drift" tests only check that certain phrases exist.
- The `@retry` on KTC catches `requests` exceptions, but the code raises Playwright errors,
  so the retry never fires. The file header claims parallel scraping, but the code runs
  sequentially.
- Docs have dates in their filenames. Several files hardcode a local Windows path.
- Last-known-good files are silently restored with a fresh mtime. A later workaround had to
  tell a restored file apart from a successful fetch.

## Reuse matrix

| Pattern | Brisket implementation | Relevance here | Class | Our implementation |
|---|---|---|---|---|
| Universal front door | `AI_INSTRUCTIONS.md` read-order | High: multiple models | APPLY_NOW | `AI_INSTRUCTIONS.md`, ~130 lines with a routing table |
| Thin provider adapters | `GEMINI.md`, copilot file; `CLAUDE.md` `@import` | High | APPLY_NOW | `AGENTS.md`, `CLAUDE.md` (with `@import`); size-capped by test |
| No private instruction forks | `AI_INSTRUCTIONS.md` §No private forks | High | APPLY_NOW | Same rule, enforced structurally by `test_instruction_parity.py` |
| Universal runbook in `CLAUDE.md` | 2,507-line file | Negative | NOT_RELEVANT (anti-pattern) | Domain docs routed by topic |
| Handoff contract | Agent OS §handoff; `STATUS/ACCEPTANCE/EVIDENCE/UNRESOLVED/BLOCKERS/NEXT_ACTION` | High | APPLY_NOW | Same block; `HANDOFF.md` is live state, not a diary |
| Evidence-state ladder | `IMPLEMENTED → … → VERIFIED` | High | APPLY_NOW | One implementation ladder and one research ladder, no more |
| Completion contracts, C-series, numerators | `EXECUTION_PLAN.md` §0.x, contracts | Low at our size | NOT_RELEVANT | `docs/EXECUTION_PLAN.md`: gate table + authorized / not-authorized lists |
| Owner-intake ledger | `OWNER_REQUESTED_TODO.md` + capture rule | Medium later | DEFER | Owner decisions are written into `EXECUTION_PLAN.md` for now |
| Work claims | Markdown table + `check_work_claims.py` (advisory) | Medium | APPLY_LIGHTLY | One line per claim, ≤7-day expiry, deleted on completion; format tested |
| Session-start receipt | `agent_session_start.sh`, Agent-OS blob SHA | Low | DEFER | Revisit if agents are seen running against stale instructions |
| Main-movement triage | `BENIGN_AUTOMATION_MOVE` etc. | None (no automation writing to main) | NOT_RELEVANT | — |
| Skills | `.agents/skills/*/SKILL.md` (8 skills) | Low now | DEFER | Routing table suffices; format noted in Agent OS §7 |
| Agent evals | `agent-evals/`: 13 JSON cases, deterministic grader of self-reported artifacts, not in CI | Medium | DEFER (ADR 0006) | Deterministic repo invariants in `tests/invariants/` instead |
| Parity tests | Phrase-presence tests | Medium | APPLY_LIGHTLY | Structural: adapters point to canonical, size cap, routed docs exist |
| Steward / autonomy | `src/steward/`, report-only phase | None yet | DEFER | — |
| HTTP/API collection | `requests` + per-fetcher exit codes | High | APPLY_NOW | stdlib `edge_lab.http.fetch` (GET-only) |
| Retry/backoff | `@retry(max_attempts, delay, backoff)` | High, but buggy there | APPLY_NOW (fixed) | Retries only transient failures (network, 429, 5xx) and honours `Retry-After`; tested |
| Per-source timeouts / isolation | `asyncio.wait_for` per site; `run_fetcher` warnings | High | APPLY_NOW | Timeout on every request; `cli._run_source` isolation boundary |
| Source health record | `_new_source_state`, `check_source_health.py` | High | APPLY_NOW | `source_health` table; status derived from stored rows |
| Outcome invariants | `AcquisitionOutcome`: failure has a reason and no rows | High | APPLY_NOW | SQL `CHECK` constraints on `source_health` |
| Telemetry around expensive ops | JSONL events, phase file, resource sampler | Medium | APPLY_LIGHTLY | Per-fetch duration/attempts/status on every snapshot + health rows; exporter deferred |
| Validation floors | Row floors per source, skip write when below | Medium | APPLY_LIGHTLY | Completeness *anomalies* (pagination, empty list) → `partial`; never skip storing evidence |
| Raw artifacts | `site_raw/*.csv`, export zips | High | APPLY_NOW | Immutable SQLite snapshots with triggers; canonical JSON + raw-bytes hash |
| Provenance | KTC `provenance_dict()` | High | APPLY_NOW | Provenance columns on every snapshot (`docs/DATA_PROVENANCE.md`) |
| Schema-change detection | `SCHEMA_CHANGED` state, exit code 2 | High | APPLY_NOW | `shape_sha256` structural fingerprint per snapshot |
| Stale-source tracking | `_last_success` stamps, staleness thresholds, alerts | High | APPLY_NOW (stricter) | `freshness` module: UNKNOWN ≠ FRESH, worst-of combine, fail-closed `require_fresh` |
| Last-known-good substitution | Restore previous files into current outputs | **Dangerous for trading** | REJECTED | Old snapshots stay queryable for research. They are never substituted as current. |
| Source registry | `_SOURCE_CSV_PATHS`, `_RANKING_SOURCES` | High | APPLY_NOW | `edge_lab.sources.REGISTRY` with access tier, terms, max ages, versions |
| Adapter interface | Three different interfaces, main scraper uses none | High | APPLY_LIGHTLY | One path: collector → `fetch_json_result` → `save_snapshot` → `_run_source`; `DocumentSource` sketched for later |
| Playwright + response interception | KTC/IDPTradeCalc | Low | DEFER | Tier 6, last resort; terms review required |
| Dev caching | `.scrape_cache`, 4h TTL, hardcoded off | Low | DEFER | Fixture-based tests replace it |
| Controlled parallel collection | Claimed, not implemented | Low at our volume | DEFER | Sequential; revisit when the number of sources grows |
| Fantasy-specific pipelines | Valuation, IDP pools, trade engines | None | NOT_RELEVANT | — |
| Deploy/nginx/systemd | Production site | None (no deployment) | NOT_RELEVANT | — |
| Hardcoded local paths | `C:\Users\…` in several docs | Negative | REJECTED | Paths relative to the repo only |
