# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Integration directive: process, fees, starter policy, notifications, venues, adapters, F09 support | claude (coordinator) | claude/market-edge-production-mission-ffa35h | AI_INSTRUCTIONS.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, HANDOFF.md, src/edge_lab/fee_schedules.py, src/edge_lab/starter_policy.py, src/edge_lab/venues.py, src/edge_lab/notifications.py, src/edge_lab/execution_ticket.py, src/edge_lab/ledger_anchor.py, deploy/vps/, experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/ | 2026-09-30 |
| GitHub reuse audit (#36): audit doc, depth ladder, provenance guard, Gate 7 replay semantics, F14 | claude (audit session) | audit/github-reuse-2026-09-23 | docs/GITHUB_REUSE_AUDIT.md, docs/audits/, THIRD_PARTY_NOTICES.md, src/edge_lab/opportunity.py, src/edge_lab/kalshi_quotes.py, src/edge_lab/exp001_shadow.py, src/edge_lab/daily.py, tests/test_depth.py, tests/gate7/test_gate7_replay_semantics.py, tests/invariants/test_third_party_provenance.py, docs/engineering/GATE7_FINDINGS.md | 2026-09-30 |
