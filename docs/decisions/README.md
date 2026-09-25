# Architecture Decision Records

Each file records one material decision: problem, alternatives, decision, tradeoffs, and
what would make us reconsider. Files are numbered and never renumbered. To supersede a
decision, add a new ADR and mark the old one `Superseded by NNNN`.

Reserved for the 2026-09-23 integration directive. A reserved number that is never used stays a gap and is
not reused:
0017 multi-component fee verification and claim basis (landed); 0018 STARTER_MAX_7D_V1 (landed);
0019 venue capability registry and read-only data-feed credentials (landed); 0020 notification
foundation (landed); 0021 ledger head anchoring (GATE7-F09).

0022 the ntfy push sink (landed, PR #44) and 0023 the binary payoff guard and per-market price
grids (landed, PR #42), both under the 2026-09-23 production activation directive; 0024 the
tailnet-only dashboard (landed, PR #46). 0025 the Market Edge Terminal v1 design system (issue #47).
0026 stake sizing v2 research challenger (landed, PR #60); 0027 best-price-for-size comparator and
split-cancel refusal (landed, PR #58); 0028 owner secrets file and ntfy relay (landed, PR #57);
0029 Odds API game-relative capture policy and budget proof (landed, PR #59), all under the
2026-09-24 directive. 0030 later and closing price observations (manual capture; the schedule is
an owner decision), under the 2026-09-24 next-build-chunk directive.

Under the 2026-09-24 (evening) Freshness Fabric and sports directive:
- 0031: Freshness Fabric v1 (landed, PR #81).
- 0032: the Polymarket US NFL research pilot. It runs on the owner's recorded risk decision; the
  Terms do not clear it (PR #84).
- 0033: the sportsbook consensus research benchmark (landed, PR #79).

Under the 2026-09-25 Economic Evidence v1 directive (#96):
- 0034: research-protocol sidecar, evidence consumption, attrition and the economic screen (EE v1 PR A).
- 0035: the next execution package: durable intent journal, reservation, fencing and reconciliation. DESIGN ONLY (EE v1 PR B).
- 0036: semantic conformance metadata and the same-venue payoff evaluator (EE v1 PR B).

New decisions start at 0037.
