# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| EXP-002 Odds API T-60m consensus label proxy (PR D) | Claude (Writer B) | feat/exp002-odds-t60m-proxy | src/edge_lab/dashboard/**, src/edge_lab/odds_*.py (display only), src/edge_lab/odds_schedule.py, src/edge_lab/polymarket_sports.py (cutoff helper only), src/edge_lab/research_readiness.py, docs/design/UI_CONTRACT.md, tests/test_dashboard*.py, tests/test_odds*.py, tests/browser/fixture_states.py, experiments/EXP-002-*/evidence_use.jsonl (append), src/edge_lab/sports_evidence.py (_hide_label_books, after #131), tests/test_sports_evidence*.py | 2026-10-06 |
