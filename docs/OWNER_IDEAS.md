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
| #3 | Outcome Board / What Matters Today dashboard | **BACKEND FOUNDATION IMPLEMENTED** 2026-09-23 (overnight directive); UI NOT READY | `edge_lab.outcome_board`: shadow positions grouped by outcome cluster, ranked by account impact (ADR 0015). The dashboard UI, hosting, auth and live marks are unauthorized and not built. |
| #5 | Sports prediction-market and sports-modeling expansion | READY FOR RESEARCH (not in Gate 3 scope) | Core framework is proving out on weather. Implementation needs the shared market-identity and execution layers. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | NOT READY | Sub-idea of #5. Needs sports authorization, market equivalence and verified access terms. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | **P0 FOUNDATION IMPLEMENTED** 2026-09-23 (shadow only) | Shadow ledger (ADR 0014), `suggest_position_size`, and the risk/capital report with a withdrawal contract (ADR 0015). The withdrawal contract never recommends a draw. A real-money policy, a verified edge and verified fees are all still missing. |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | **PARTLY AUTHORIZED** 2026-09-22: headless read-only collector only | Forward collector authorized on the VPS as a separate service (ADR 0012; headroom review `docs/deploy/VPS_REVIEW_2026-09-22.md` PASS). Dashboard/API, subdomain, DNS/TLS and auth remain NOT READY and unauthorized. |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. |

Related owner records that are not ideas:
- **#11 [Owner Directive] 30-day delivery plan (target 2026-10-22).** This is the active
  roadmap: deadline fixed, scope adapts, P0/P1/P2 change control. Gates still govern:
  "a gate does not pass because the calendar says it should".
- **#12 [Infrastructure] Brisket portability audit.** An owner-authorized parallel lane with
  its own branch and file claim. It does not touch Gate 3 files.

## Review log

- **2026-09-23: Gate 4 → 5 → 6 and the risk foundation (overnight directive, PRs #21–#24).**
  - #6 and #3 moved to foundation-implemented (shadow and backend only).
  - #5 and #9 stay outside scope. The directive says no sports tonight.
  - #7 unchanged: no paid sources.
  - #10 unchanged: headless collector only; no subdomain or dashboard.

- **2026-09-22, Gate 2 → Gate 3 / Gate 3 PR.**
  - Classifications as above. None change Gate 3 scope.
  - #7's free-first principle drove the forecast-source choice (IEM PFMOKX).
  - The Kalshi fee-schedule PDF sits behind a bot checkpoint and is not bypassed, which
    is consistent with #7's "no circumvention".
- **2026-09-22, Gate 4 exit criteria met (PR #18); Gate 5 awaits the owner.**
  - #10 is partly authorized: the headless read-only collector only (ADR 0012).
  - No other classification changes.
  - #3 and #6 stay NOT READY until a shadow ledger with real forward data exists.
  - #5 and #9 stay outside scope: no sports work.
- **2026-09-22, Gate 3 → Gate 4 (Gate 3 PR, effective on merge).**
  - No classification changes: #3, #6, #9 and #10 stay NOT READY, #5 READY FOR RESEARCH,
    #7 APPLY SELECTIVELY.
  - #10 captured and indexed.
  - Per #11, the next P0 steps are Gate 4 (the frozen baseline) and forward market
    collection. That collection is the owner's scheduled-collection decision (ADR 0008),
    and #10 is a candidate host for it.
  - #6's risk foundation and #3's Outcome Board are #11 P0 items for later in the month.
    They stay NOT READY until a shadow ledger exists.
