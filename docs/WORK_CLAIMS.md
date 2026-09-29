# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| NHL-A review fixes (#137) | Claude (Writer A) | feat/nhl-a-odds-planner | src/edge_lab/odds_schedule.py, src/edge_lab/odds_pilot.py, src/edge_lab/cli.py (odds block only), deploy/vps/systemd/edgelab-odds.service, docs/decisions/0039-*, docs/research/NHL_ODDS_BUDGET_2026-10.md, tests/test_odds*.py, tests/test_deploy_units.py (odds unit only) | 2026-10-06 |
