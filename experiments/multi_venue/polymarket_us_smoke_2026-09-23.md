# Polymarket US: bounded public smoke read (2026-09-23)

## The one live API call

| Field | Value |
|---|---|
| URL | `https://gateway.polymarket.us/v1/markets?limit=5` |
| Method | GET, no credentials, no cookies sent |
| User-Agent | `market-edge-lab/0.1 (read-only research; bounded smoke test)` |
| Request started (UTC) | 2026-09-23T14:07:38.874Z |
| Response complete (UTC) | 2026-09-23T14:07:39.099Z (server `date: Wed, 23 Sep 2026 14:07:39 GMT`) |
| HTTP status | 200 |
| Content-Type | `application/json` |
| Bytes | 22338 |
| SHA-256 of body | `55de7665830ee28c8653da2b952a670a8d8b79c710c7c26e82d854768dab2900` |
| Stored as | `tests/fixtures/polymarket_us/markets_limit5_2026-09-23T140738Z.json` (exact bytes) |

Headers of note: `cache-control: public, max-age=30`, served through Cloudflare (`cf-ray` from
IAD). No `Set-Cookie` was stored. This was one request, which is 1/20 of the documented
per-second public limit.

What it showed: five markets (ids 1 to 5, NFL moneylines from 2025-11-02), all
`status: MARKET_STATUS_RESOLVED`, `closed: true`, but also `active: true`. So `active` is not
a trading-open flag, and the adapter maps only `status`. Each market has two `marketSides`.
The side with `long: true` is the YES instrument (for example "Chargers"), and
`feeCoefficient` is 0.0695. The response has no total, cursor or event reference, as the docs
say.

Stage consequence: `polymarket_us` `catalog_read` is **TESTED** in `src/edge_lab/venues.py`,
and the evidence string cites this note. This read would support LIVE_DATA_VERIFIED for
catalog_read on 2026-09-23. The existing test `tests/test_venues_and_tickets.py::
test_only_recorded_reads_are_live_data_verified` pins that set to Kalshi only. That file is
outside this lane, so the promotion is left to the coordinator. No other capability was read
live: books, BBO and settlement use documented example fixtures only.

## Documentation read (docs.polymarket.us, 2026-09-23, about 14:00 to 14:07 UTC)

- `llms.txt` (index); `api-reference/introduction`: public API at `https://gateway.polymarket.us`,
  "No API key needed". The authenticated API is `https://api.polymarket.us` and is not used.
- `api-reference/rate-limits`: public (unauthenticated) 20 requests per second per IP. On a
  429, stop, wait at least 1 s, then back off exponentially. Cache reference data.
- `api-reference/markets/get-markets`, `get-market-by-slug`, `get-market-book`,
  `get-market-bbo`, `get-market-settlement`, `api-reference/market/overview`,
  `api-reference/events/get-events`: schemas used by `src/edge_lab/polymarket_us.py`.
  - Book entries are `{px: Amount, qty: string}`; qty is "Quantity available at this price.
    May contain decimals for partial-contract markets."
  - BBO has `bestBid`/`bestAsk` and `bidShares`/`askShares`, which are totals over all
    levels rounded to two significant figures. There is no size at the best price.
  - Pagination is `limit`/`offset` only.
- `concepts/market-data`, `concepts/orders`, `learn/trading/basics/buying-yes-vs-selling-no`:
  one instrument per market. "If you want to buy NO at $0.40, you're really selling YES at
  $0.60." Settlement is $1.00 or $0.00. Alternative settlement follows the market's
  Settlement Description.
- `learn/advanced/rule-structure`: rules include resolution criteria, timeframe and sources.
  A 50-50 settlement is possible, for example on cancellation.
- `fees`: taker coefficient 0.0695, maker rebate 0.0125, banker's rounding to $0.01, and
  volume rebates. **Not implemented:** no Polymarket US fee schedule is verified here, and
  `schedule_for("polymarket_us")` stays UNSUPPORTED.
- `learn/trading/access-and-limits/trading-hours`: weekly maintenance Thursday 06:00 to 08:00
  ET; daily reporting as of 17:00 ET.
- `learn/markets/contract-settlement`: settlement is final per the Exchange Rulebook. No
  payout timing or post-settlement hold is stated, so cash timing stays unknown and the
  starter policy fails closed.

## Terms

- The API docs present the public gateway as a keyless read interface for displaying market
  data, with a published per-IP limit. That is the basis for this single bounded read.
- `partners/onboarding/legal-agreements`: the legal set (Participant Agreement, Exchange
  Rulebook, Clearinghouse Rulebook, Risk Disclosure) governs participants and trading. This
  repository is not a participant and did not trade.
- `https://polymarket.us/terms` and `/tos` returned 200, but they are JavaScript apps. Their
  text could not be read without a browser, and browser automation was not used, so the
  website Terms of Service were **not reviewed**. That is an open uncertainty. Until it is
  reviewed, stored data is for research only and is not redistributed, and no scheduled
  collection is proposed.
