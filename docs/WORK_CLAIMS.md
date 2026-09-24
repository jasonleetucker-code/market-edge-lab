# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| Lane A: Freshness Fabric v1 + supervisor | Claude (laptop) | feat/freshness-fabric | src/edge_lab/freshness.py, src/edge_lab/freshness_fabric.py, src/edge_lab/cli.py (freshness block only), deploy/vps/systemd/edgelab-freshness.*, deploy/vps/install.sh (UNITS line), docs/decisions/0031-*, tests/test_freshness*.py | 2026-10-01 |
| Lane B: Polymarket US NFL pilot | Claude (laptop) | feat/polymarket-sports | src/edge_lab/polymarket_us.py (additive only), src/edge_lab/polymarket_sports.py, src/edge_lab/storage.py (additive schema only), src/edge_lab/sources.py (additive registry rows), src/edge_lab/cli.py (pm-sports block only), deploy/vps/systemd/edgelab-pm-sports*, docs/decisions/0032-*, experiments/multi_venue/polymarket_us_sports_*, tests/test_polymarket_sports*.py | 2026-10-01 |
| Lane C: sportsbook consensus + research readiness | Claude (laptop) | feat/odds-consensus | src/edge_lab/odds_api.py (consensus section only), src/edge_lab/odds_consensus.py, src/edge_lab/research_readiness.py, src/edge_lab/cli.py (consensus/readiness block only), docs/decisions/0033-*, tests/test_odds_consensus*.py, tests/test_research_readiness*.py | 2026-10-01 |
| Lane D: Terminal freshness / odds / consensus / related-market views | Claude (laptop) | ui/freshness-odds-views | src/edge_lab/dashboard/**, docs/design/*, docs/DASHBOARD.md, tests/test_dashboard*.py, tests/browser/* | 2026-10-01 |
| Lane E / coordinator: directive, integration, deploy/runbook, reviews, roadmap, HANDOFF, production evidence | Claude (laptop) | docs/* | docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md, HANDOFF.md, docs/DATA_PROVENANCE.md, docs/deploy/*, deploy/vps/README.md, deploy/vps/verify_production.sh, docs/owner/2026-09-24-freshness-*, docs/engineering/ledger_checkpoints/ | 2026-10-01 |
| Lane G: Multi-City Weather v1 design + live verification (docs/research only) | Claude (laptop) | docs/multi-city-weather-design | docs/research/MULTI_CITY_WEATHER_V1.md, experiments/multi_city_weather/*, tests/fixtures/kalshi_weather_families/* | 2026-10-01 |
