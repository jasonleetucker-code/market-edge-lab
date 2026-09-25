# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| EE Writer 1 (shared contracts + canonical docs): Economic Evidence v1 PR A (protocols, evidence consumption, attrition, economic screen, #96 canonical integration) then PR B (semantic conformance, same-venue payoff evaluator, execution-package ADR) | Claude (laptop) | feat/ee-research-contracts, feat/ee-payoff-conformance | src/edge_lab/opportunity.py (additive), src/edge_lab/storage.py (additive), src/edge_lab/cli.py (new research blocks), src/edge_lab/fee_schedules.py (additive), src/edge_lab/experiments.py (additive), src/edge_lab/research_evidence.py, src/edge_lab/research_economics.py, src/edge_lab/payoff_constraints.py, experiments/EXP-* (new only; never EXP-001), docs/owner/2026-09-25-economic-evidence-v1-directive.md, AI_INSTRUCTIONS.md (routing row only), HANDOFF.md (Gate 7 valid-day line only), docs/OWNER_IDEAS.md, docs/EXECUTION_PLAN.md, docs/RESEARCH_PRINCIPLES.md, experiments/README.md, docs/DATA_PROVENANCE.md, docs/strategy/*, docs/decisions/0034-* 0035-* 0036-*, tests/test_research_evidence*.py, tests/test_research_economics*.py, tests/test_payoff*.py, tests/test_conformance*.py, tests/test_experiments_protocol*.py, tests/fixtures/research/*, tests/fixtures/conformance/* | 2026-10-02 |
| EE Writer 2 (sports paired evidence + Terminal): Economic Evidence v1 PR C | Claude (laptop) | feat/ee-sports-paired | src/edge_lab/sports_evidence.py, src/edge_lab/dashboard/**, docs/design/*, docs/DASHBOARD.md, docs/research/SPORTS_PAIRED_EVIDENCE*.md, tests/test_sports_evidence*.py, tests/test_dashboard*.py, tests/browser/*, tests/fixtures/sports_evidence/ | 2026-10-02 |
| EE coordinator: W0 operating verification, reviews, merges, deploy, final HANDOFF | Claude (laptop) | docs/* | HANDOFF.md (final state only, after writers finish), deploy/vps/* (only if a reviewed fix is needed) | 2026-10-02 |
