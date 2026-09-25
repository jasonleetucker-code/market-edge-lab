# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| RU Writer R (research/protocol + contract evidence): EXP-002 protocol recommendation, shadow-fill label review, EXP-003 proof obligations, economics scenarios | Claude (laptop) | docs/research-unblocking-decisions | docs/research/RESEARCH_UNBLOCKING_DECISIONS.md, experiments/EXP-002-*/ (DRAFT only), experiments/EXP-003-*/ (DRAFT only; append-only logs), src/edge_lab/research_economics.py (labels/additive), src/edge_lab/sports_evidence.py (wording only), docs/RESEARCH_PRINCIPLES.md, docs/decisions/0037-*, tests/test_research_economics*.py, tests/test_sports_evidence*.py, tests/fixtures/conformance/*, scripts/research_power_sensitivity.py | 2026-10-02 |
| RU Writer O (operations): Kalshi NFL capture plan (disabled/dry-run only) and backup retention proposal (dry-run only) | Claude (laptop) | ops/capture-backup-approval-plan | docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md, docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md (capture section), src/edge_lab/backup.py (additive dry-run retention report), src/edge_lab/price_observations.py (additive, disabled planner only), tests/test_backup*.py, tests/test_price_observations*.py, tests/fixtures/nfl_capture/* | 2026-10-02 |
| RU coordinator: blocker reclassification, operational verification, owner decision packet, final HANDOFF | Claude (laptop) | docs/* | HANDOFF.md, docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md (only authority actually granted), docs/WORK_CLAIMS.md | 2026-10-02 |
