# The Odds API v4: credit rules re-read for the game-relative pilot (2026-09-24)

Purpose: confirm, before the pilot's budget proof (ADR 0029), which calls cost credits and how
many. Only the public documentation page was fetched. **No Odds API call was made, no key
exists in this session, and agents never create, request or see one.**

## The documentation read

| Field | Value |
|---|---|
| URL | `https://the-odds-api.com/liveapi/guides/v4/` |
| Time (UTC) | 2026-09-24T02:03:35Z |
| Status | 200, `text/html; charset=utf-8` |
| Bytes | 325429 |
| SHA-256 of the bytes | `37d800ec5826b290b7f7cf558145c9a74ce9c4a601a943e44867aace4aaa35d3` |
| SHA-256 of the extracted text | `6afe859ad24765fa3b39e5cf780224273bc293adc830a1a0b8e6d63563dce842` (65750 characters) |

The bytes hash equals the 2026-09-23 read (`odds_api_docs_2026-09-23.md`): the page has not
changed since the fixtures were taken.

Text extraction: drop `<script>` and `<style>` blocks, replace tags with spaces, unescape HTML
entities, collapse runs of spaces and tabs, collapse blank lines. The result was hashed as UTF-8.

## Rules the pilot relies on (paraphrased; section names from the page)

| Endpoint | Credits | Where on the page |
|---|---|---|
| `GET /v4/sports` | free: the page says it "does not count against the usage quota" | GET sports, Usage Quota Costs |
| `GET /v4/sports/{sport}/events` | free (same statement); returns event id, teams and commence time, no odds | GET events |
| `GET /v4/sports/{sport}/odds` | `markets x regions`; with `bookmakers`, every group of up to 10 books counts as one region | GET odds, Usage Quota Costs |
| any odds response with no events | free | GET odds, More info |
| event odds, scores, historical | not used by the pilot | - |

- **Filters.** Both the odds and the events endpoints accept `commenceTimeFrom` and
  `commenceTimeTo` (ISO 8601; "on and after" / "on and before") and `eventIds`. They narrow the
  response. The cost formula of the odds endpoint does not depend on them.
- **Headers.** Responses carry `x-requests-remaining`, `x-requests-used` and `x-requests-last`
  (the last call's cost). The ledger books `x-requests-last`, not the estimate.
- **Charged markets.** The market part of the cost counts the unique markets actually returned.
  The estimate `markets x regions` is therefore an upper bound.
- **Coverage.** The odds endpoint returns only events that bookmakers list. Bookmakers may list
  a new season's events months ahead.

## What this means for the pilot's cost

- One capture call is h2h, spreads and totals for region `us`: **3 credits at most**.
- Discovery (events) and quota reconciliation (sports) are **0 credits**.
- The reset time of the monthly quota is not documented on this page. The quota ledger resets
  only when the provider's own `x-requests-used` goes down; it never guesses a date.

## Not verified here

- Which bookmakers and markets a free key actually returns for NFL. The first `odds smoke`
  read records that.
- Whether the events endpoint lists the whole NFL season or only the next weeks. The planner
  treats anything after the last discovered kickoff as unknown and budgets it under the
  documented worst-case assumption (ADR 0029).
