# Current blockers, reconciled (2026-09-30)

**Status:** research record, PR C (roadmap R1), 2026-09-30. Directive:
`docs/owner/2026-09-30-roadmap-integration-sports-intelligence-rfq-directive.md`.

**This record authorizes nothing.** It sends no message and changes no schedule, quota, protected window,
collector or fee record. It does not run the A.C tool. The machine-readable register is
`src/edge_lab/current_blockers.py`, which the Terminal shows. `tests/test_current_blockers.py` keeps every id and
status below equal to the register.

## Method

- Repository sources are cited per row: HANDOFF, ADRs, research records and owner packets.
- Official pages were re-read, read-only, on **2026-09-30 around 09:38 UTC** by the laptop clock. The laptop
  clock has been hours off before, so treat the time as approximate.
  - The Kalshi Fees help page (<https://help.kalshi.com/en/articles/13823805-fees>, "Last updated April 19, 2026")
    lists no per-series or combination-market fees. It points to the fee-schedule PDF and says "Some markets have
    fees that are different from those of other markets."
  - The Kalshi Fee Rounding page (<https://docs.kalshi.com/getting_started/fee_rounding>) describes rounding
    mechanics only.
  - The fee-schedule PDF (<https://kalshi.com/docs/kalshi-fee-schedule.pdf>) returned **HTTP 429**. It was not
    re-read. The captured copy of 2026-09-23 (effective 2026-07-07) stays the evidence.
- No API endpoint, account or authenticated page was called. Nothing is guessed: an unread fact is UNKNOWN.

## Register

| Id | Status | Verified | Unknown | Resolver | Trigger |
|---|---|---|---|---|---|
| ROUTINE_OFFHOST_BACKUP | WAITING_FOR_WINDOW | A retention apply refuses after 8 days without F09 | nothing | OWNER (laptop routine) | by about 2026-10-03 |
| KALSHI_MESSAGE_REV2 | NOT_SENT | Revision 2 is drafted; revision 1 was shown on 2026-09-26 | Kalshi's answers | OWNER confirms and sends; agents never send | owner confirmation |
| FEE_KXNFLGAME | FEE_UNSUPPORTED | On the captured non-standard list (PDF pp.6-11); no verification record | multiplier and maker-fee semantics | VENUE (message Q7 or a primary document), then the fee owner | a Kalshi reply or a new PDF |
| FEE_KXNHLGAME | FEE_UNSUPPORTED | Now routed like KXNFLGAME (this PR). Series metadata reads `quadratic_with_maker_fees`, multiplier 1 (ADR 0040), with no primary document | whether the general schedule applies | VENUE, then the fee owner | a Kalshi reply or a new PDF |
| FEE_KXMVE_COMBOS | FEE_UNSUPPORTED | KXMVE is listed; KXMVE* combination series now route to FEE_UNSUPPORTED by prefix (this PR) | combination fees, including RFQ target-cost modes | VENUE; #148 records the RFQ side | #148 merged, or a Kalshi document |
| NFL_FALLBACK_WORDING | CORRECTION_PENDING | The terms' Venue Change clause is narrower than v1 §2's wording | nothing about the rule | AGENT (freeze-review packet author) | freeze proposal v2, before 2026-10-22 |
| NHL_SHOOTOUT_TIE | RULES_UNRESOLVED | Overtime is included; postponement and cancellation are stated | shootout and tie payout | VENUE; not in revision 2, so adding it needs the owner | only before a hockey experiment needs it |
| DATA_RIGHTS | UNRESOLVED | The Data Terms PDF was read and hashed; it is written about website content | which terms govern API data | OWNER reads the Developer Agreement and decides | owner decision |
| NHL_ODDS_COMMENCE_OFFSET | RECORDED | Odds API commence times are about 10 min after NHL.com's | whether the offset is constant | AGENT (a future hockey protocol names its start time) | a hockey experiment proposal |
| NHL_READ_TIME_GAP | OWNER_DECISION | For 19:00 ET games, Odds reads at T-25m and Kalshi at T-85m, about 60 min apart | nothing; it is a choice | OWNER (packet decision 2; default (a) leave as is) | owner decision |
| EXP002_AC_TIMING_RUN | WAITING_FOR_WINDOW | The tool is built and deployed (#142, #143) | its result | AGENT: one logged run, never early | after about 2026-10-19 |
| EXP002_FREEZE_REVIEW | OWNER_DECISION | The tie and not-played bounds are sourced and PROPOSED (#138) | the freeze outcome; none is promised | OWNER | 2026-10-22 |

## Notes per blocker

### Fees (FEE_KXNFLGAME, FEE_KXNHLGAME, FEE_KXMVE_COMBOS)

`fee_schedules.schedule_for("kalshi", …)` previously matched the non-standard list exactly. KXNHLGAME is not on
the list (KXNHL, KXNHLEAST and KXNHLWEST are), so it fell through to the general quadratic schedule as UNVERIFIED.
The same happened to combination series such as KXMVECROSSCATEGORY, because only the exact KXMVE was listed.

This PR adds `fee_schedules.nonstandard_family`. A series that extends a listed series is FEE_UNSUPPORTED until
its own fee is verified.
- KXNHLGAME and KXMVE* are now consistent with KXNFLGAME.
- KXHIGHNY (EXP-001) and every unlisted family keep their routing byte for byte. `check-frozen` is clean, and
  `tests/test_fee_family_routing.py` pins KXHIGHNY's schedule, claim basis and a fee.

Sources: `docs/research/EXP002_FEE_VERIFICATION.md`, ADR 0040 ("Rules, fees, units"), the captured PDF list in
`fee_schedules.KALSHI_NONSTANDARD_SERIES`.

### NFL fallback wording (NFL_FALLBACK_WORDING)

The terms pay a discretionary last fair price F when a game is moved outside the same scheduling week or has its
home/away designation reversed. A venue change that keeps the designation, with the game played within 48 hours,
resolves normally (`EXP002_TIE_NOTPLAYED_BOUNDS.md` §1).

The freeze proposal v1 §2 says "a venue or home/away change". That is broader than the terms. The corrected
wording for v2 is: **"moved outside the same scheduling week, or with the home/away designation reversed"**.

v1 is left as written; it is the proposal the review will compare against. The correction lands in freeze
proposal v2.

### NHL shootout and tie (NHL_SHOOTOUT_TIE)

The HOCKEYWINNINGINPERIOD terms define winning by goals in regulation plus overtime. They never mention the
shootout, and they state no tie payout (ADR 0040). Both stay RULES_UNRESOLVED.

Message revision 2 does not ask about them, so adding the question is an owner choice. No hockey experiment
exists, so nothing is blocked today.

### Rights (DATA_RIGHTS)

Which terms govern API-collected Kalshi data is UNRESOLVED. The candidates are the Data Terms of Use, which are
written about website content, and the Developer Agreement, which was not read (HTTP 429 at the time)
(`INPLAY_SOURCE_FEASIBILITY.md` §1.9). The owner reads the Developer Agreement and decides; Q10 in revision 2 asks
Kalshi.

### Timestamp and lead differences (NHL_ODDS_COMMENCE_OFFSET, NHL_READ_TIME_GAP)

- The Odds API lists NHL commence times about 10 minutes after NHL.com's. Its "T-60m" is therefore about T-50m of
  the official start. The provider data is recorded as received and not altered.
- For 19:00 ET games, the Odds quiet window moves the sportsbook read to 18:35 ET (T-25m). The Kalshi protected
  window moves the Kalshi read to 17:35 ET (T-85m). That is about 60 minutes apart, for about 36% of NHL games.
  Both reads keep their real lead.
- Packet decision 2 is the owner's: (a), leave as is, is the default. This PR changes no window.

### Kalshi message revision 2 (KALSHI_MESSAGE_REV2)

The message is drafted and NOT SENT (`KALSHI_QUESTIONS_2026-09-26.md`). Sending it is an owner action.

### EXP-002 dates (EXP002_AC_TIMING_RUN, EXP002_FREEZE_REVIEW)

- The A.C tool runs once, logged, after the pilot weeks, about 2026-10-19. It is not run early.
- The freeze review on 2026-10-22 is the owner's. It needs evidence, fees and rules; no freeze is promised.

## Next

The Terminal's next item is the one with the soonest due date among open blockers. Today that is
ROUTINE_OFFHOST_BACKUP, around 2026-10-03, then EXP002_AC_TIMING_RUN. Owner decisions without a date follow:
KALSHI_MESSAGE_REV2, DATA_RIGHTS and NHL_READ_TIME_GAP.
