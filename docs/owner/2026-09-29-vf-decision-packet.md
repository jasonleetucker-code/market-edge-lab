# Decision packet: EXP-002 validation, #122 in-play foundation (2026-09-29)

Coordinator output for the owner directive of 2026-09-28
(`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`). Status words:
CURRENT, PROPOSED, APPROVED, BLOCKED, VERIFIED. Nothing here is approved by being recommended.

## Already decided (not re-asked)

- EXP-002 economics: a $1,000/yr continuation bar and 6 owner hours to 2026-10-22, counted in hours
  and not priced (#117). The +8 h extension is **not** granted.
- EXP-003 paused (#117). Its owner hours are not set.
- Pregame Kalshi NFL capture: ≤ 295 GETs a week (#110).
- Retention `proposed-v1` and O1 laptop pulls (#117). The first cycle is done (2026-09-26).
- GitHub billing: fixed by the owner (2026-09-28); CI runs.

## A. Kalshi message, revision 2 (owner confirmation needed)

`docs/research/KALSHI_QUESTIONS_2026-09-26.md`, revision 2, **NOT SENT**. Revision 1, with 8
questions, was shown on 2026-09-26 and not confirmed. Revision 2 adds three things:
- Q7 (a)–(d): KXNFLGAME fee multipliers, schedule currency, overrides and waivers, and the start
  date of maker fees;
- Q9: the conflict between two governing texts for a game suspended after 55 minutes;
- Q10: whether the Data Terms of Use cover API-retrieved data, and whether private storage and
  analysis, including with AI tools, is permitted.

**Needed:** confirm the exact text, and the channel: your own email from the account address, or
the Kalshi help-center form. Optionally set EXP-003's owner hours (2 h were recommended).

## B. Data rights (owner review; affects existing collection)

`docs/research/INPLAY_SOURCE_FEASIBILITY.md` §1.9 summarizes the evidence:
- **Data Terms of Use** (the PDF was read and hashed). They are written about website content, and
  restrict collecting into databases, software development and any AI/ML use without written
  consent.
- **Developer Agreement**, which governs the API: unread, because it returned HTTP 429 twice.
- **Which terms govern our API-collected data:** UNRESOLVED. If the website terms applied, they
  would bear on EXP-001, the pregame NFL capture and agent-assisted analysis.

**Recommended:**
- Read the Developer Agreement yourself while signed in. The terms may be served to logged-in
  members.
- Send Q10 with the message.
- Keep the already-approved collection running meanwhile. It stops only if you decide otherwise
  after reading the agreement.
- Start no in-play pilot until this is resolved.

## C. In-play source-quality pilot `inplay-source-pilot-1` (PROPOSED, NOT APPROVED)

Full specification: `INPLAY_SOURCE_FEASIBILITY.md` §6–§7.
- **Scope:** Kalshi KXNFLGAME, full-game winner contracts, 2 Sunday 13:00 ET games.
  - Selected on the Friday before, as the two lexicographically smallest eligible event tickers.
    The selection is blind to outcomes and volatility.
  - The earliest Sunday is 2026-10-18, and the fallback is 2026-10-25.
  - Review happens the next day.
- **Route:** B, bounded public REST sampling, which needs no credential.
  - Batch books every 5 s; `game_stats` every 30 s; status every 60 s.
  - At most 4,500 requests.
  - Stops after 20 total or 5 consecutive HTTP 429s.
  - Storage 200 MB; memory 256 MB; CPU 15%.
- **Window:** from 10 min before kickoff to 10 min after close, with a hard stop at 17:15 ET.
- **Isolation:** its own directory. It never touches the evidence DB or ledger, and it yields to
  collector locks.
- **Controls:** started manually with an enable file plus expiry. `systemctl stop` ends it. No
  timer.
- **Outputs:** a source-quality verdict only, with no edge or economic claim. The data role is
  OPERATIONAL, and nothing enters EXP-002.
- **Cost:** $0 cash; 0 Odds credits; about 1 + 1 owner hours (approve and review).
- **Prerequisites:**
  - Rights (B) resolved.
  - A reviewed recorder built, with CI green (not built yet).
  - A research slot. Real in-play *evaluation*, beyond source quality, needs either a slot
    transition (for example EXP-003 PAUSED → ENDED) or an explicit exception, plus an id from the
    registry. That id is not assumed to be EXP-004. The #96 two-family limit stands.

Suggested wording, if you approve later:

> I approve in-play source-quality pilot inplay-source-pilot-1 as specified in
> INPLAY_SOURCE_FEASIBILITY.md §6 (route B, 2 pre-selected games, ≤ 4,500 requests, manual start,
> source-quality output only), after the rights question is resolved and a reviewed recorder is
> merged. This approves no evaluation slot, no orders, no account reads and no credentials.

## Not an owner decision (technical, already reviewed)

- EXP-002 gate v3 is a non-promotion gate. Its spread-noise candidate failed validation, with a
  false-pass rate of 98% in the worst setting. The protocol cannot freeze on any v2 or v3 result.
- The proposed alternative primary endpoint, E1 (executable round trip), is technical work: it
  needs to be implemented, versioned and reviewed before any freeze.
