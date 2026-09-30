# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| PR C: current-blocker reconciliation, Terminal compact integration, R0–R11 ledger | Claude (PR C writer; W2 lane, Writer B on #148) | feat/pr-c-blockers-terminal-ledger | src/edge_lab/fee_schedules.py, tests/test_fee*.py, src/edge_lab/current_blockers.py (new), tests/test_current_blockers.py, docs/research/CURRENT_BLOCKERS_2026-09-30.md, src/edge_lab/inplay_view.py, src/edge_lab/inplay_replay.py (EntryResult exit time only), src/edge_lab/dashboard/views/inplay.py, src/edge_lab/dashboard/views/markets.py, src/edge_lab/dashboard/views/research.py, src/edge_lab/dashboard/views/terminal.py, src/edge_lab/dashboard/views/common.py, src/edge_lab/dashboard/presentation.py (one ratio formatter), src/edge_lab/dashboard/data.py, tests/test_inplay_view.py, tests/test_dashboard_inplay.py, tests/test_dashboard_blockers.py, tests/browser/fixture_states.py, docs/design/UI_CONTRACT.md, docs/strategy/DELIVERY_ROADMAP.md | 2026-10-07 |
