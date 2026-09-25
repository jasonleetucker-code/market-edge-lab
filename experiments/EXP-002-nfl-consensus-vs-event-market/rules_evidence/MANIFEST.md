# KXNFLGAME / FOOTBALLGAMEWIN rules evidence (read 2026-09-25)

Research evidence for EXP-002 (DRAFT) and the proof-obligation work in
`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md`. Public documents only. No Kalshi API endpoint
was called for this: no trading, order, portfolio or authenticated endpoint, and no market-data
poll.

**Method.** Each document was fetched once with a web-fetch tool on 2026-09-25 (America/New_York
afternoon, about 21:20Z by the laptop clock; that clock has been off before, so treat the time as
approximate). The tool saved the response bytes. The files here are those bytes, unchanged. Text
was read with a local stdlib PDF text extractor (not committed); the clause summaries below were
checked against that text.

| File | Source URL | Bytes | sha256 | Document date |
|---|---|---|---|---|
| `FOOTBALLGAMEWIN_contract_terms_read-2026-09-25.pdf` | `https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf` (the KXNFLGAME series `contract_terms_url`, `tests/fixtures/sports_evidence/kalshi_series_KXNFLGAME_2026-09-25T022448Z.json`) | 40,044 | `19578b71cd63da63cc2894c60542ef06bb5de56b9366add56f07cee645cfca4b` | No version or effective date printed. PDF metadata CreationDate 2026-09-11T03:12:33Z (wkhtmltopdf). 3 pages. |
| `FOOTBALLGAMEWIN_product_certification_read-2026-09-25.pdf` | `https://assets.kalshi.com/regulatory/product-certifications/FOOTBALLGAMEWIN.pdf` (the series `contract_url`) | 301,600 | `d89ea1b11d8ec7290111eeb6f3878864ff0ea790185d619b4e6f89b6359fc2cc` | CFTC Regulation 40.2(a) self-certification letter dated February 18, 2026 ("Will <team> win <time period> of <football game>?"), with its terms as Appendix A. 12 pages. |

Not committed (hash recorded so the same bytes can be re-identified):

| Document | Source URL | Bytes | sha256 | Version |
|---|---|---|---|---|
| KalshiEX LLC Rulebook | `https://kalshi-public-docs.s3.amazonaws.com/regulatory/rulebook/Kalshi%20DCM%20Rulebook%20v.1.29.pdf` | 860,053 | `3b6d4ffd5b32330d3466179d4cae610372d07511123c9976bc6cbb1b5185240b` | "Version: 1.29"; PDF CreationDate 2026-08-11. Whether 1.29 is the current version is UNVERIFIED: `kalshi.com/regulatory/rulebook` answered HTTP 429 and was not retried. |

## What the contract terms say (2026-09-11 document; summary, not a substitute for the PDF)

- **Underlying and winner.** The official final result, overtime included. A team wins only
  with strictly more points. The first official final result counts, unless the Exchange believes
  it is clearly erroneous and a correction is made before expiration. Revisions after expiration
  are ignored.
- **Tie** after all regulation and overtime periods: each team strike resolves to $1 divided by
  the number of tied teams, rounded down ($0.50 for two teams).
- **Postponed** and started within 48 hours of the original date: resolves on the rescheduled
  game. **Not started within 48 hours:** "last fair market price as determined by Kalshi".
- **Suspended or abandoned after kickoff**, not resumed within 48 hours, before 55 minutes of
  play: "last fair price" at the Exchange's sole discretion. After 55 minutes, or when the league
  declares the game final: settles on what has occurred.
- **Forfeit** before kickoff: fair price. After kickoff: the league's official determination.
- **Venue change** with the same home/away designation and play within 48 hours: normal result.
  A reversed home/away designation, or a move outside the scheduling week: fair price.
- **Disqualification** before the game: fair price. After it starts, before expiration: "No" for
  the disqualified team, and "Yes" for the opponent only if it is declared the winner.
- **Contingencies:** Rule 7.1 outcome review; if an expiration value cannot be determined, Kalshi
  determines payouts under Rule 7.1. Minimum tick $0.01. Settlement value $1.00. Latest
  expiration one week after the period, at 10:00 AM ET, moved earlier when a winner is reported.

The market-level `rules_secondary` captured on 2026-09-25 (fixture above) states only the tie,
48-hour postponement and fair-price clauses. The contract terms add the suspension, forfeit, venue
and disqualification states. The two documents differ on a game suspended after 55 minutes of play and not resumed:
- **February certification:** a full-game market resolves at the last fair market price, unless
  the league declares a winner or final result.
- **September terms:** the market settles on what has occurred.

The later terms document is used as current. That reading is UNVERIFIED until Kalshi confirms
which text governs a listed market. Either way the state is admissible and carries a discretionary
or partial-game payoff.

## Rulebook v1.29 provisions used (summary)

- **Rule 6.3(a)–(b):** a binary contract pays the settlement value to long holders when the payout
  criterion is met, otherwise to short holders. A scalar contract splits the settlement value
  between long and short positions.
- **Rule 6.3(c):** when the payout cannot be determined, Kalshi determines the long and short
  payouts. It may use the last traded price; the rule's example pays $0.10 to long and $0.90 to
  short. Otherwise the Outcome Review Committee makes "a binding determination of fair
  allocation".
- **Rule 7.1:** a discretionary outcome review before settlement, decided within 24 hours of
  initiation. **Rule 7.2:** a source agency or underlying may be changed, and expiration may be
  moved.
- **Rule 2.8 (emergencies):** permitted actions include cancelling a contract and returning the
  funds paid to enter trades on it.
