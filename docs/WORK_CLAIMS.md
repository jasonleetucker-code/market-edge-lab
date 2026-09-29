# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| NHL-B: Kalshi KXNHLGAME prospective evidence (+ NHL freshness, Terminal coverage) | Claude (Writer B) | feat/nhl-b-kalshi-evidence | src/edge_lab/price_observations.py, src/edge_lab/sports_nhl*.py (if needed), src/edge_lab/freshness_fabric.py, src/edge_lab/sources.py, src/edge_lab/dashboard/**, docs/design/UI_CONTRACT.md, deploy/vps/install.sh (NHL Kalshi switch only), docs/decisions/0040-*, tests/test_price_observations_nhl*.py, tests/test_dashboard*.py, tests/browser/fixture_states.py | 2026-10-06 |
