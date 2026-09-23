# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| 2026-09-23 production activation + post-audit follow-ups: depth/payoff/grid, ntfy sink, ticket checks, Windows portability, F09 evidence, handoff | claude (local session with VPS access) | depth/polymarket-us-payoff-grid, notify/ntfy-sink, ticket/control-checklist, windows/portability, docs/production-activation-2026-09-23 | src/edge_lab/opportunity.py, src/edge_lab/kalshi_quotes.py, src/edge_lab/polymarket_us.py, src/edge_lab/notifications.py, src/edge_lab/notify_ntfy.py, src/edge_lab/execution_ticket.py, tests/test_polymarket_depth.py, tests/test_payoff_and_grid.py, tests/test_notify_ntfy.py, tests/test_execution_ticket_controls.py, tests/invariants/test_no_execution_paths.py, docs/decisions/0022-*, docs/decisions/0023-*, THIRD_PARTY_NOTICES.md, docs/engineering/GATE7_FINDINGS.md, HANDOFF.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, docs/GITHUB_REUSE_AUDIT.md, .gitattributes | 2026-09-30 |
