# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Lanes C+D: secrets env, Odds API pilot, ntfy wiring | Claude (laptop) | feat/odds-ntfy-activation | deploy/vps/install.sh, deploy/vps/systemd/edgelab-odds.*, src/edge_lab/odds_api.py, src/edge_lab/odds_schedule.py, src/edge_lab/daily.py (_notify only), src/edge_lab/cli.py, src/edge_lab/notify_ntfy.py, docs/SECURITY.md, docs/deploy/*, docs/decisions/0022-*, docs/decisions/0028-*, tests/test_odds*.py, tests/test_notify*.py | 2026-09-30 |
| Directive authority, roadmap, HANDOFF | Claude (laptop) | docs/directive-2026-09-24-authority | docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, HANDOFF.md, docs/DATA_PROVENANCE.md, docs/owner/2026-09-24-* | 2026-09-30 |
