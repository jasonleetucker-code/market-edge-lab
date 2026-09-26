# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| RD Writer R (research): EXP-002 measurement endpoint (first T-60m book, cross-book markout, placebo) and label-free pre-freeze correlation gate | Claude (laptop) | feat/exp002-markout-gate | src/edge_lab/sports_evidence.py, src/edge_lab/research_economics.py (additive), experiments/EXP-002-*/ (DRAFT; append-only logs), scripts/research_power_sensitivity.py, tests/test_sports_evidence*.py, tests/test_research_economics*.py, tests/fixtures/sports_evidence/* | 2026-10-03 |
| RD Writer O (operations): reviewed manual backup apply step (proposed-v1) and O1 weekly off-host pull runbook/tooling | Claude (laptop) | feat/backup-apply-o1 | src/edge_lab/backup.py (additive), docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md, docs/deploy/DAILY_SHADOW_ACTIVATION.md (backup/restore sections only), tests/test_backup*.py | 2026-10-03 |
| RD coordinator: owner-decision record, Kalshi message, production verifications, backup apply execution, HANDOFF | Claude (laptop) | docs/* | HANDOFF.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, docs/owner/*, docs/research/KALSHI_QUESTIONS_2026-09-26.md, experiments/EXP-00{2,3}-*/protocol.toml + README.md (owner-input fields and decision log only), docs/WORK_CLAIMS.md | 2026-10-03 |
