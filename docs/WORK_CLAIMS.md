# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| 2026-09-23 production activation: first-window evidence, second F09 checkpoint, HANDOFF (narrowed; other paths released) | claude (local session with VPS access) | docs/production-final-2026-09-23 | HANDOFF.md, docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md, docs/engineering/GATE7_FINDINGS.md, docs/engineering/ledger_checkpoints/ | 2026-09-30 |
| 2026-09-23 Market Edge Terminal v1 UI (owner directive, issue #47) | claude (local session: Market Edge Terminal v1 design) | ui/terminal-v1 | src/edge_lab/dashboard/**, tests/test_dashboard*.py, tests/browser/**, docs/design/**, docs/DASHBOARD.md, docs/decisions/0025-*, docs/owner/2026-09-23-terminal-v1-ui-directive.md, AI_INSTRUCTIONS.md, .github/pull_request_template.md, pyproject.toml; appended sections only (released by #48): docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, THIRD_PARTY_NOTICES.md (HANDOFF.md stays with the production-activation claim) | 2026-09-30 |
