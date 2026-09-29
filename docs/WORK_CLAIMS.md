# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| VF Writer A (EXP-002): replacement pre-freeze gate (versioned) with adversarial validation, proposed freeze settings, Kalshi fee/payoff document verification, EXP-002 gate Terminal line | Claude (laptop) | feat/exp002-gate-v3 | src/edge_lab/sports_evidence.py, src/edge_lab/research_economics.py (additive), src/edge_lab/fee_schedules.py (additive verification record only), scripts/research_power_sensitivity.py, experiments/EXP-002-*/ (DRAFT; append-only logs), docs/research/RESEARCH_UNBLOCKING_DECISIONS.md, docs/research/EXP002_*.md, src/edge_lab/dashboard/views/research.py + dashboard/data.py (EXP-002 gate line only), tests/test_sports_evidence*.py, tests/test_research_economics*.py, tests/test_fee*.py, tests/test_dashboard_economics*.py, tests/fixtures/sports_evidence/* | 2026-10-05 |
| VF Writer B (#122 in-play offline): source/API feasibility, in-play evidence contract, pure position policy, deterministic hold-vs-exit replay, fixtures, in-play Terminal view, pilot proposal | Claude (laptop) | feat/inplay-foundation-v1 | src/edge_lab/position_policy.py (new), src/edge_lab/inplay_*.py (new), docs/research/INPLAY_*.md (new), docs/decisions/0038-* (new), tests/test_position_policy*.py, tests/test_inplay_*.py, tests/fixtures/inplay/*, src/edge_lab/dashboard/views/inplay*.py (new, PR C) + minimal wiring in dashboard/app.py and dashboard/data.py (in-play only, after Writer A's gate line lands) | 2026-10-05 |
| VF coordinator: #120/#121 reconciliation, directive record, operations, #122 canonical integration, owner packet, HANDOFF | Claude (laptop) | docs/handoff-2026-09-26 | HANDOFF.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, docs/owner/*, docs/WORK_CLAIMS.md, docs/engineering/ledger_checkpoints/*, docs/deploy/retention-records/* | 2026-10-05 |
