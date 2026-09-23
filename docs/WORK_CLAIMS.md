# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
<<<<<<< HEAD
| 2026-09-23 production activation: first-window evidence, second F09 checkpoint, HANDOFF (narrowed; other paths released) | claude (local session with VPS access) | docs/production-final-2026-09-23 | HANDOFF.md, docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md, docs/engineering/GATE7_FINDINGS.md, docs/engineering/ledger_checkpoints/ | 2026-09-30 |
=======
| 2026-09-23 production activation + post-audit follow-ups: depth/payoff/grid, ntfy sink, ticket checks, Windows portability, F09 evidence, handoff | claude (local session with VPS access) | depth/polymarket-us-payoff-grid, notify/ntfy-sink, ticket/control-checklist, windows/portability, docs/production-activation-2026-09-23 | src/edge_lab/opportunity.py, src/edge_lab/kalshi_quotes.py, src/edge_lab/polymarket_us.py, src/edge_lab/notifications.py, src/edge_lab/notify_ntfy.py, src/edge_lab/execution_ticket.py, tests/test_polymarket_depth.py, tests/test_payoff_and_grid.py, tests/test_notify_ntfy.py, tests/test_execution_ticket_controls.py, tests/invariants/test_no_execution_paths.py, docs/decisions/0022-*, docs/decisions/0023-*, THIRD_PARTY_NOTICES.md, docs/engineering/GATE7_FINDINGS.md, HANDOFF.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, docs/GITHUB_REUSE_AUDIT.md, .gitattributes | 2026-09-30 |
| 2026-09-23 Market Edge Terminal v1 UI (owner directive, issue #47) | claude (local session: Market Edge Terminal v1 design) | ui/terminal-v1 | src/edge_lab/dashboard/**, tests/test_dashboard*.py, tests/browser/**, docs/design/**, docs/DASHBOARD.md, docs/decisions/0025-*, docs/owner/2026-09-23-terminal-v1-ui-directive.md, AI_INSTRUCTIONS.md, .github/pull_request_template.md, pyproject.toml; after the production-activation claim is released (owner instruction): docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, THIRD_PARTY_NOTICES.md, HANDOFF.md | 2026-09-30 |
>>>>>>> 0eacf12 (WIP Terminal v1: presentation layer, components, shell, pages, assets)
