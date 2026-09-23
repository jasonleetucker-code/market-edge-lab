# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Daily shadow pipeline, settlement refresh, dual backup, VPS units (PR-B) | claude (coordinator, session_01QA6jZ7) | claude/market-edge-agent-os-ghmeha | src/edge_lab/{daily,storage,exp001_shadow,shadow_ledger,kalshi,backup,cli}.py, deploy/vps/**, docs/deploy/** | 2026-09-26 |
| Gate 7 adversarial suite (PR-C; tests only, findings reported to coordinator) | claude (lane 2 agent) | claude/market-edge-agent-os-ghmeha | tests/gate7/**, docs/engineering/GATE7_FINDINGS.md | 2026-09-26 |
| Local read-only dashboard (PR-D) | claude (lane 3 agent) | claude/market-edge-agent-os-ghmeha | src/edge_lab/dashboard/**, tests/test_dashboard*.py, docs/DASHBOARD.md | 2026-09-26 |
