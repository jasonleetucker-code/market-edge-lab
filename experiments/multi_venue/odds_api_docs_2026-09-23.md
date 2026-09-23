# The Odds API v4: documentation read for fixtures (2026-09-23)

No Odds API call was made. No key exists, and agents never create, request or see one.

## The one documentation read

| Field | Value |
|---|---|
| URL | `https://the-odds-api.com/liveapi/guides/v4/` |
| Time (UTC) | 2026-09-23T14:06:51Z |
| Status | 200, `text/html; charset=utf-8` |
| Bytes | 325429 |
| SHA-256 | `37d800ec5826b290b7f7cf558145c9a74ce9c4a601a943e44867aace4aaa35d3` |

## Fixtures copied from the documented examples

- `tests/fixtures/odds_api/v4_odds_nfl_h2h_spreads_american_documented.json`: the "GET odds"
  example response for
  `/v4/sports/americanfootball_nfl/odds/?regions=us&markets=h2h,spreads&oddsFormat=american`.
  It is one event with 12 bookmakers, `williamhill_us` included. The page shows the list
  truncated with `...` after the first event, so only that event is kept.
- `tests/fixtures/odds_api/v4_sports_documented.json`: the "GET sports" example (27 sports).

## Rules taken from the guide

- **Cost.** "The usage quota cost is 1 per region per market", so `cost = markets x regions`.
  With `bookmakers`, "every group of 10 bookmakers is the equivalent of 1 region". The
  provider counts the unique markets actually returned, and an empty response costs nothing.
  The local estimate is therefore an upper bound, and `x-requests-last` is what gets booked.
- **Headers.** `x-requests-remaining`, `x-requests-used` and `x-requests-last` come on every
  call. `GET /v4/sports` "does not count against the usage quota", so it is used to
  reconcile.
- **Key transport.** `apiKey` is a query parameter. `edge_lab.http` refuses credential
  headers anyway.
- **Freshness.** The market-level `last_update` is the last time odds were seen. A suspended
  market stops updating and is removed after about 15 minutes. The bookmaker-level
  `last_update` is deprecated.
- **Paid-only.** Historical odds endpoints are "only available on paid usage plans".
  `williamhill_us` and `fanatics` are treated as paid-only per issue #29 as relayed to this
  lane. The guide itself does not state this, and it was not independently verified here.

## Owner setup step (when the owner chooses to activate; not now)

1. The owner creates the free key at the provider. The agent does not do this.
2. The owner puts it only in the host environment as `EDGE_LAB_ODDS_API_KEY`, for example in
   a root-readable environment file for the service user. Never in git, chat or a ticket.
3. An approved activation and quota plan (issue #29) is recorded before any pull. Then one
   manual `reconcile_quota` call (free) sets the ledger to READY. Any pull reserves credits
   below the 450 ceiling first.
