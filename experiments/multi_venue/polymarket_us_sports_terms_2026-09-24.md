# Polymarket US: sports terms and access review, and NFL fixture reads (2026-09-24)

Scope: Lane B of the owner directive of 2026-09-24 (evening),
`docs/owner/2026-09-24-freshness-fabric-sports-directive.md`. Before any scheduled Polymarket US
NFL collection: verify the current source documentation and terms, including access from a
non-US host. Only official **Polymarket US** sources were read (`docs.polymarket.us`,
`polymarket.us` and the Terms document it embeds). Polymarket International was not used.
Code: `src/edge_lab/polymarket_sports.py`. Decision: `docs/decisions/0032-polymarket-us-nfl-research-pilot.md`.

## Verdict

**NOT CLEARED for unattended collection. The pilot stays disabled.** Blocker: the owner must
decide, and ideally obtain written permission from Polymarket US (the rate-limit page names
support@polymarket.us for automated systems). No message was sent: sending one needs the
owner's approval.

- **Automation.** Permitted only through authorized APIs. The public gateway is a documented,
  keyless API with a published per-IP limit, so bounded automated reads through it are
  consistent with that clause.
- **Purpose of use: the blocker.**
  - The Terms license the App (which they define to include "APIs") only for the user's own
    trading and account administration.
  - They license market data for "personal, non-commercial use in connection with your trading".
  - They prohibit "scraping, bulk downloads" unless expressly licensed.
  - This project is private and non-commercial and redistributes nothing, but it does not trade
    on Polymarket US.
  - Whether keyless research reads of the public API are "in connection with your trading" is
    **not established**. Read literally, the scheduled pilot falls outside the license. The API
    documentation invites public reads for display, but it grants no separate data licence.
- **Location.** Not a blocker on the text read.
  - The Terms state no US-only access rule for the App. They prohibit access "from locations
    where its contents are illegal" and use by sanctioned or embargoed persons or locations.
  - They add that the Company "does not represent that the App is appropriate or available for
    use in any specific location".
  - The production VPS is in Germany, which is neither sanctioned nor embargoed. The coordinator
    reports that on 2026-09-24 at 20:50Z, `GET /v1/markets?limit=1` from the VPS returned HTTP 200
    through Cloudflare FRA with no VPN. That is the coordinator's evidence; this lane did not
    re-run it.
  - No VPN, proxy or geolocation circumvention is used or proposed. If Polymarket US ever
    geoblocks the host, the pilot records FAILED and MISSED and never works around the block.
- **Eligibility.** The eligibility clause (18+, "legally permitted to access the DCM", KYC) is
  written for account holders. The pilot opens no account and sends no credential.

The code enforces the verdict:
- `polymarket_sports.OWNER_ACCESS_DECISION` is None, so every networked run stops before the
  network with `BLOCKED_TERMS_REVIEW` (exit 0, nothing written).
- The timers are committed only as `*.timer.proposed`.
- The new source registry rows stay PLANNED.

## Sources read (plain GETs from the laptop, no credentials or cookies)

- **User-Agent:** `market-edge-lab/0.1 (read-only research; terms and access review)`.
- **Hashes:** SHA-256 of the exact bytes received. Page copies are not committed, because they
  are the venue's copyrighted text.
- **Excerpts:** kept under 15 words each.
- **Retrieved text** was treated as data. Nothing in it was followed as an instruction.

| # | URL | Accessed (UTC) | Bytes | SHA-256 |
|---|---|---|---|---|
| 1 | https://docs.polymarket.us/llms.txt | 2026-09-24T20:52:50Z | 49954 | `4c541f6258fc3149a3837af35ca474d464692ab86523fa50fa4ed0aefe457ad0` (unchanged since the 2026-09-24T01:33Z read) |
| 2 | https://docs.polymarket.us/api-reference/introduction.md | 2026-09-24T20:53:07Z | 2440 | `9d8e749605c9df1a4803d6effb0499ab5ff52a59c0dba0dc80d95ab507fd4154` |
| 3 | https://docs.polymarket.us/api-reference/rate-limits.md | 2026-09-24T20:53:09Z | 4249 | `670610f351c22e395960b58b0538ee312e1d42017faf64c1e4b1517abae41f09` |
| 4 | https://docs.polymarket.us/api-reference/markets/get-markets.md | 2026-09-24T20:53:10Z | 29586 | `da24e4079cec0adff98a55da27fe8ab10b00968d8c1b602355ee8f4db1de5811` |
| 5 | https://docs.polymarket.us/api-reference/events/get-events.md | 2026-09-24T20:53:13Z | 57625 | `d6a7f067c7ef5921471827a0fd40b2c0db71cfe70c9fca4ba911e6bd1ad2ba3d` |
| 6 | https://docs.polymarket.us/api-reference/sports/overview.md | 2026-09-24T20:53:15Z | 3275 | `6f5aa5d7e96f2fd22e2eb6c704e1f435dd8930d6d07a1299ea7afc3a91aae052` |
| 7 | https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug.md | 2026-09-24T20:53:17Z | 36612 | `8cbedad5571da4bc9b5f3ed7f01824e4e16f50f4fcb4a9e95f11a4fa5b2c7b1f` |
| 8 | https://docs.polymarket.us/api-reference/sports/get-all-leagues.md | 2026-09-24T20:53:19Z | 3211 | `b6600cbe558594740dd868a8f111ec1d15410bc86578954ed1d428f768d5025d` |
| 9 | https://docs.polymarket.us/api-reference/sports/get-league-by-slug.md | 2026-09-24T20:53:22Z | 2995 | `5f3ea602bf0470777ed54bbdbe632f2b2cebda4d29632b33537da31bbf9d44d9` |
| 10 | https://docs.polymarket.us/learn/faq/api.md | 2026-09-24T20:53:24Z | 447 | `4cd4354875a97b3fec6eacad9e4a43e2b6235b702e14143ff15c404b3919f1ca` |
| 11 | https://docs.polymarket.us/learn/trading/access-and-limits/trading-restrictions.md | 2026-09-24T20:53:26Z | 1069 | `7d0e3d7dcf23f8507757bb226b29b71ea76726bd59658ffafd4eeceb0fa7bceb` |
| 12 | https://docs.polymarket.us/partners/onboarding/legal-agreements.md | 2026-09-24T20:53:28Z | 7833 | `3f5cbb13b92321f0a86d17ffa393bc319da9c7e645da68877334da91b7e854f2` |
| 13 | https://docs.polymarket.us/faqs/sports-faqs.md | 2026-09-24T20:53:30Z | 18606 | `b3e1ccb06ead7fd3d9ee663ecf6086d9134378a94b60f595d4d7090b04718f3c` (unchanged since 2026-09-24T01:35Z) |
| 14 | https://docs.polymarket.us/trader-guide/sports-schema.md | 2026-09-24T20:53:32Z | 95326 | `b164f81b88c6ac59fa607357dbf2ccfa6ee4841a63ebf3423d93b239dca55be5` |
| 15 | https://docs.polymarket.us/api-reference/markets/get-market-book.md | 2026-09-24T20:53:33Z | 11223 | `b060ad6322b1b1753de42beabbc5be76ffc81bac847f14ab710dee27c01cef9d` |
| 16 | https://docs.polymarket.us/api-reference/events/get-event-by-slug.md | 2026-09-24T20:53:36Z | 48874 | `6b9cb84f938b730d8f72819820ac60d0570f1164878ec66d9ea6f6bf603f5531` |
| 17 | https://docs.polymarket.us/getting-started/quickstart.md | 2026-09-24T20:53:38Z | 6402 | `607b9a8f204d04f83fd9f43286c67114c9625fc164d13b1fb41a5bfa78afd41a` |
| 18 | https://polymarket.us/tos (HTML shell; the text loads client-side) | 2026-09-24T20:54:16Z | 112368 | `c1251415f941186f4bd550a578080c467a83468efcb82aa5f8b6d4561762dd91` |
| 19 | https://polymarket.us/terms (a referral landing page, not the Terms) | 2026-09-24T20:54:18Z | 235493 | `76429c4cd76241fa7efe20f0ec3ec8a8367e9623a51fa121ab56643314d53a77` |
| 20 | https://polymarket.us/robots.txt (the website, not the gateway) | 2026-09-24T20:54:19Z | 551 | `403e656f3e9dd480735538db205352ac3e2e200b27d71bbd25473cdcee5fbc29` |
| 21 | The Terms document that `/tos` embeds: `https://docs.google.com/document/u/1/d/e/2PACX-1vQ-86JK7kI6jAkpUNEyTCSpkeP_7cZMKhAW0rtti9rjzXqhdqm-27YSrX9Bun8LjQ/pub?embedded=true` | 2026-09-24T20:55:00Z | 178296 | `ff664a6dcace5d6d3b15c42968398d1c097b4dc14c102dbd6cd987f8270175a2` |

- **How the Terms were found.** The 2026-09-23 smoke note recorded that the Terms were a
  JavaScript app and unread. This time the HTML of `/tos` was read as plain text: it names one
  published document URL (source 21), which returned the full text as static HTML. No browser
  automation was used. A later fetch with a different hash means the Terms changed.
- **Cross-check.** WebFetch of `/tos` and `/terms` (same time) also saw no Terms text in the page
  body.

## What the sources establish

| Topic | Source and excerpt (short) | Consequence |
|---|---|---|
| Public API | 2: "No API key needed." Public API at `https://gateway.polymarket.us`. | Keyless reads are the documented public interface. |
| Its purpose | 2: the public API is described as what a builder of market-information displays needs | The docs frame the gateway as a display and read interface. That is not a data licence. |
| Rate limit | 3: public (unauthenticated) requests are limited to 20 per second per IP | The pilot's 1 request per second is 5% of it. |
| 429 handling | 3: on a 429, stop, wait at least one second, then back off exponentially | `edge_lab.http` backs off on 429 (one retry here); the pacer is 1 s. |
| Caching | 3: cache reference data and refresh it periodically instead of polling | Discovery runs at most every 6 h; books are fetched only at planned targets. |
| Terms scope | 21: "The Polymarket App, including related websites, portals, and APIs" | The Terms cover API use. Effective date: September 25, 2025. |
| License | 21 §4: "solely to access the DCM/DCO ... for your own trading" | **Purpose restriction** (see the verdict). |
| Market data | 21 §5: "personal, non-commercial use in connection with your trading" | **Purpose restriction**: research use without trading is not established. |
| Prohibited | 21 §5: "Redistribution, resale, scraping, bulk downloads" (unless expressly licensed) | Nothing is redistributed. Bounded reads are small (below), but "bulk" is undefined. |
| Automation | 21 §7(c): "use bots or automation except through authorized APIs" | Automation through the documented public API is consistent with this clause. |
| Load | 21 §7(i): no unreasonable or disproportionately large load on the infrastructure | This is why discovery is filtered: the unfiltered league listing is 40 MB a page (fixture read 1). |
| Location | 21 §3: "Access to the App from locations where its contents are illegal is prohibited." | No US-only rule. The EU VPS is not in a restricted location on this text. |
| Sanctions | 21 §25: no use by sanctioned persons or from restricted or embargoed jurisdictions | Germany is not. |
| Changes | 21 §26: changes take effect immediately when posted | Re-read before enabling, and at every re-review. |
| Legal set | 12: four documents, and no additional terms apply beyond them | That set governs participants. The App Terms (21) govern App and API use. |
| Website robots | 20: `Disallow: /api/` on `polymarket.us` | This covers the website's own `/api/`, not `gateway.polymarket.us`, which the pilot uses. |
| Pagination | 4, 5: `limit`/`offset` only; no total, no cursor | The completeness contract of `polymarket_us.read_events_listing` applies. |
| Hidden markets | 4, 5: `includeHidden` defaults to false | Even an unfiltered listing omits hidden markets. So a filtered scan is never evidence of absence. |
| Sports fields | 7, 14: `gameStartTime`, `sportsMarketType`, `sportsMarketTypeV2`, `marketSides[].team`, event `teams` | These are what the relationship mapping reads. |
| Sports rules | 13: ties settle at $0.50; cancellation and postponement at the last fair market price | So `payoff_kind` is `binary_alternative_settlement` (PAYOFF_UNSUPPORTED). |

## The bounded fixture reads (public gateway, 9 of the 20 allowed)

- **Client:** the adapter's User-Agent,
  `market-edge-lab/0.1 (read-only research; polymarket_us public adapter)`, sent from the laptop
  (US). No credentials or cookies. At least 1 s between requests.
- **Stored:** exact bytes under `tests/fixtures/polymarket_us/` (git `-text`), except read 1,
  which is too large to commit. Its hash is recorded instead.
- **Cloudflare edges:** PIT or IAD. `cache-control: public, max-age=30` on reads 2 and 4 to 9.

| # | Started (UTC) | Path | HTTP | Bytes | SHA-256 | Stored as |
|---|---|---|---|---|---|---|
| 1 | 20:57:22.515 | `/v2/leagues/nfl/events?limit=50&offset=0` | 200 | 40216730 | `a6b79e25a80f51962259e29597be28dd811edd1a61cf8b94ee843d7e02e04ec3` | not committed (40 MB: 33 events, about 300 markets each, props included) |
| 2 | 20:58:28.892 | `/v1/markets?limit=100&offset=0&tagIds=1&sportsMarketTypes=SPORTS_MARKET_TYPE_MONEYLINE&closed=false` | 200 | 14 | `f36daaa1fcd896f9fdfd2a991f06ef808c56d5acaceca4e6f89329e7794608d1` | `markets_tagids1_moneyline_filter_2026-09-24T205829Z.json` |
| 3 | 20:58:39.375 | same with `sportsMarketTypes=moneyline` | 400 | 84 | `3dfee344062a03df5c88721cc1ccb9d0fea8551884eae1989663b03e8cc9f6e3` | not committed (error body) |
| 4 | 20:58:57.960 | `/v1/markets?limit=100&offset=0&categories=sports&sportsMarketTypes=SPORTS_MARKET_TYPE_MONEYLINE&closed=false` | 200 | 3932 | `8830315ce020487277c4cc9e7ea3d7c95f404203be7a1f9fe1e3dc201a749ecb` | `markets_sports_moneyline_filter_2026-09-24T205858Z.json` |
| 5 | 20:59:21.174 | `/v1/events?limit=50&offset=0&tagSlug=nfl&closed=false&sportsMarketTypes=football_team_full_game_winner` | 200 | 340955 | `c3d43cd5b9b47fbb307c8acac2a600bc68a12b38177fcfeeb54c6bdf82658c40` | `nfl_events_moneyline_p0_2026-09-24T205921Z.json` |
| 6 | 20:59:41.887 | same, `offset=50` | 200 | 13 | `24de1c4a19c43ad41b013f13dcd858c17b0daa7f33a53f19913e5b11366d1c2e` | `nfl_events_moneyline_p1_2026-09-24T205942Z.json` (`{"events":[]}`) |
| 7 | 20:59:49.576 | `/v1/markets/aec-nfl-kc-mia-2026-09-27/book` | 200 | 3679 | `9310bbda63e1aca3e202d0c58391c87a62b0486d238b672c8588414fbdd141c9` | `book_aec-nfl-kc-mia-2026-09-27_2026-09-24T205949Z.json` |
| 8 | 20:59:59.338 | `/v1/markets/aec-nfl-atl-gb-2026-09-24/book` | 200 | 5239 | `e53334e43e37a335949ff598f33624fe4534b8e6584769a47c71a50e3c2e24cb` | `book_aec-nfl-atl-gb-2026-09-24_2026-09-24T205959Z.json` |
| 9 | 21:00:00.609 | `/v1/markets/aec-nfl-zzz-yyy-2026-09-27/book` (a slug that does not exist) | 404 | 84 | `1f5b171604a760691bf72ecab588fc6a21197a396cac917adc80e06af68f2086` | `book_404_2026-09-24T210000Z.json` |

What the reads showed:

- **Filters on `/v1/markets` cannot find NFL games.**
  - Markets carry no tags, so `tagIds=1` returned an empty list (read 2). An empty filtered
    listing is not absence: that is the completeness contract, now demonstrated.
  - `categories=sports` with the moneyline type returned one boxing market (read 4).
  - So the pilot does not use `/v1/markets` for discovery.
- **`/v1/events` works** with `tagSlug=nfl`, `closed=false` and
  `sportsMarketTypes=football_team_full_game_winner` (read 5).
  - It returned 33 open NFL games from 2026-09-24 to 2026-10-08, each with exactly its one
    full-game winner market embedded, in 0.34 MB.
  - The next page was empty (read 6), so the filtered listing was read to its end.
  - The unfiltered league endpoint returned the same 33 games, but with about 300 markets each
    (alternate spreads and totals, quarters, halves, team totals) in 40 MB (read 1).
- **Moneyline rules text:**
  - "Overtime is included if played";
  - a tie settles to $0.50;
  - a game not rescheduled within two days (in some markets, two weeks) settles at the last
    fair market price;
  - "Outcome sourced from the relevant governing body" (some markets say "NFL").

  All 33 markets are `binary_alternative_settlement` under `polymarket_us.payoff_kind`.
- **Books:** `state` MARKET_STATE_OPEN, a `transactTime`, bids and offers as `{px, qty}`. The
  adapter's `quotes_from_book` parses them without anomaly.
- **A missing slug** returns HTTP 404 with a generic error body. The pilot records it as
  NOT_EXECUTABLE BOOK_NOT_FOUND (final), not as a retryable failure.

## What stays open

- **Whether Polymarket US permits scheduled research reads by a non-trading, non-account holder.**
  This is the blocker. Only the owner can resolve it (decision, or written permission).
- **The Terms text itself.** It is published in a document the site embeds; its authority over
  API use comes from its own scope clause ("APIs"). If Polymarket US publishes a separate API or
  data licence, that document wins, and this review must be redone.
- **The non-US access check.** Reported by the coordinator, not reproduced by this lane.
- **The listing filter.** `sportsMarketTypes` on `/v1/events` is documented as a fine-grained
  type filter, but not as a filter of the embedded markets. The pilot checks every returned
  market and drops anything else as a reported anomaly.
