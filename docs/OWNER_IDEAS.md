# Owner Ideas

Durable owner ideas live in GitHub issues titled `[Owner Idea] …`. This file is an
**index**, not a copy: the issue body is the record. The process authority is issue #4
([Owner Process] Durable idea intake and readiness backlog). The canonical rule is in
`AI_INSTRUCTIONS.md` → Owner ideas.

- **Capture:** create or update an issue in seconds. Link related ideas. Do not invent
  details the owner did not give.
- **An issue is not authorization.** `docs/EXECUTION_PLAN.md` alone says what may be built.
- **Review:** at every gate transition, or when an idea's prerequisites appear, the
  coordinating agent reclassifies each open idea below and dates the review.

Readiness vocabulary: **NOT READY** (prerequisites absent) · **READY FOR RESEARCH** ·
**APPLY SELECTIVELY** (use the principle where current work already needs it) ·
**READY FOR IMPLEMENTATION** (prerequisites exist and there is an authorization path) ·
**SUPERSEDED / NOT PLANNED**.

## Index

| Issue | Idea | Readiness | Why / prerequisites |
|---|---|---|---|
| #4 | Durable idea intake and readiness backlog (process) | **Implemented** 2026-09-22 (Gate 3 PR) | `AI_INSTRUCTIONS.md` rule + this index |
| #3 | Outcome Board / What Matters Today dashboard | NOT READY | Needs a position ledger, contract/outcome identity, risk engine, and live prices with freshness |
| #5 | Sports prediction-market and sports-modeling expansion | READY FOR RESEARCH (not in Gate 3 scope) | Core framework is proving out on weather. Implementation needs the shared market-identity and execution layers. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | NOT READY | Sub-idea of #5. Needs sports authorization, market equivalence and verified access terms. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | NOT READY | Needs an account/position ledger, P&L, risk engine and an owner risk policy |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | NOT READY | Needs a useful private API/dashboard, an auth design, a VPS headroom review, and owner authorization for DNS/TLS/production changes. Also the likely durable home for forward collection (ADR 0008). |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. |

Related owner records that are not ideas:
- **#11 [Owner Directive] 30-day delivery plan (target 2026-10-22).** This is the active
  roadmap: deadline fixed, scope adapts, P0/P1/P2 change control. Gates still govern:
  "a gate does not pass because the calendar says it should".
- **#12 [Infrastructure] Brisket portability audit.** An owner-authorized parallel lane with
  its own branch and file claim. It does not touch Gate 3 files.

## Review log

- **2026-09-22, Gate 2 → Gate 3 / Gate 3 PR.**
  - Classifications as above. None change Gate 3 scope.
  - #7's free-first principle drove the forecast-source choice (IEM PFMOKX).
  - The Kalshi fee-schedule PDF sits behind a bot checkpoint and is not bypassed, which
    is consistent with #7's "no circumvention".
- **2026-09-22, Gate 3 → Gate 4 (Gate 3 PR, effective on merge).**
  - No classification changes: #3, #6, #9 and #10 stay NOT READY, #5 READY FOR RESEARCH,
    #7 APPLY SELECTIVELY.
  - #10 captured and indexed.
  - Per #11, the next P0 steps are Gate 4 (the frozen baseline) and forward market
    collection. That collection is the owner's scheduled-collection decision (ADR 0008),
    and #10 is a candidate host for it.
  - #6's risk foundation and #3's Outcome Board are #11 P0 items for later in the month.
    They stay NOT READY until a shadow ledger exists.
