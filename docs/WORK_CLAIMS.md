# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Lane A: stake sizing v2 (research/challenger) | Claude (laptop) | feat/sizing-v2 | src/edge_lab/sizing_v2.py, src/edge_lab/sizing_eval.py, docs/research/STAKE_SIZING_V2.md, docs/decisions/0026-*, experiments/sizing_v2/, tests/test_sizing_v2*.py | 2026-09-30 |
| Lane B: best-price comparator, Polymarket US fees, split-cancel payoff | Claude (laptop) | feat/best-price-comparator | src/edge_lab/best_price.py, src/edge_lab/fee_schedules.py, src/edge_lab/polymarket_us.py, src/edge_lab/venues.py, src/edge_lab/opportunity.py (payoff guard only), docs/decisions/0027-*, experiments/multi_venue/polymarket_us_fees_*, tests/test_best_price*.py, tests/test_polymarket_us*.py, tests/test_fee_schedules*.py | 2026-09-30 |
| Lanes C+D: secrets env, Odds API pilot, ntfy wiring | Claude (laptop) | feat/odds-ntfy-activation | deploy/vps/install.sh, deploy/vps/systemd/edgelab-odds.*, src/edge_lab/odds_api.py, src/edge_lab/odds_schedule.py, src/edge_lab/daily.py (_notify only), src/edge_lab/cli.py, src/edge_lab/notify_ntfy.py, docs/SECURITY.md, docs/deploy/*, docs/decisions/0022-*, docs/decisions/0028-*, tests/test_odds*.py, tests/test_notify*.py | 2026-09-30 |
| Directive authority, roadmap, HANDOFF | Claude (laptop) | docs/directive-2026-09-24-authority | docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, HANDOFF.md, docs/DATA_PROVENANCE.md, docs/owner/2026-09-24-* | 2026-09-30 |
