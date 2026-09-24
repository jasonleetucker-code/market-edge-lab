# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Lane A: sizing-v2 counterfactual runner | Claude (laptop) | feat/sizing-counterfactuals | src/edge_lab/sizing_counterfactual.py, src/edge_lab/sizing_v2.py (additive API only), src/edge_lab/cli.py (sizing subcommand block only), experiments/sizing_v2/counterfactual*, tests/test_sizing_counterfactual*.py | 2026-10-01 |
| Lane B: Terminal sizing panel + comparator UI (+ reconcile PRs #53/#54) | Claude (laptop) | ui/sizing-comparator-panels | src/edge_lab/dashboard/**, docs/design/*, docs/DASHBOARD.md, tests/test_dashboard*.py, tests/browser/* | 2026-10-01 |
| Lane C: notification origin / delivery policy | Claude (laptop) | feat/notification-origin | src/edge_lab/notifications.py, src/edge_lab/notify_ntfy.py, src/edge_lab/daily.py (_notify only), deploy/vps/alert.sh, docs/decisions/0020-*, docs/decisions/0028-*, tests/test_notifications.py, tests/test_notify_ntfy.py | 2026-10-01 |
| Lane D: Odds API readiness + #50 coverage audit | Claude (laptop) | feat/odds-readiness-audit | src/edge_lab/odds_api.py, src/edge_lab/odds_schedule.py, src/edge_lab/odds_pilot.py, docs/research/LEARNING_HISTORY_COVERAGE.md, tests/test_odds*.py | 2026-10-01 |
| Lane E: later/closing-price capture + P0 history storage | Claude (laptop) | feat/price-observations | src/edge_lab/price_observations.py, src/edge_lab/storage.py (additive schema only), src/edge_lab/cli.py (observe subcommand block only), docs/decisions/0030-*, tests/test_price_observations*.py | 2026-10-01 |
| Coordinator: directive authority, settlement/F09, roadmap, HANDOFF | Claude (laptop) | docs/* | docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, HANDOFF.md, docs/DATA_PROVENANCE.md, docs/owner/2026-09-24-next-*, docs/engineering/ledger_checkpoints/ | 2026-10-01 |
