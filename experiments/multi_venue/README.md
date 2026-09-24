# Multi-venue read-only data foundation: evidence

Evidence for the bounded read-only adapters built under the 2026-09-23 integration
directive (sections 8 to 12). It is not an experiment: there is no hypothesis and no
`experiment.toml`. It records what was read live, when and with what result, and what the
documentation and terms say.

| File | What it records |
|---|---|
| `polymarket_us_smoke_2026-09-23.md` | The one bounded live GET of the Polymarket US public gateway, plus the docs and terms reviewed |
| `novig_daily_data_capture_2026-09-23.md` | The one manual read of Novig's published daily files (index plus one day), and the fixture truncation |
| `polymarket_us_fees_2026-09-24.md` | The official Polymarket US fee page, rules/settlement docs and Exchange Rulebook read for the fee schedule and the split-cancel payoff (ADR 0027): URLs, times, hashes, excerpts, what stays UNSUPPORTED |
| `odds_api_docs_2026-09-23.md` | The one read of The Odds API v4 guide used to build fixtures. No API call was made: there is no key |

Rules that apply to everything here:

- A live read is evidence for that capability on that date only. It does not show that a
  collector exists, that the source is healthy, or that data is current.
- No order, authenticated or credentialed endpoint was called. No VPN or geolocation
  workaround was used.
- None of these reads is scheduled. Nothing here adds a timer.
