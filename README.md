# market-edge-lab

A read-only research lab for testing whether measurable market edges survive real-world data, prices, fees, and execution constraints.

> **AI agents:** start at [`AI_INSTRUCTIONS.md`](AI_INSTRUCTIONS.md). Current state lives in
> [`HANDOFF.md`](HANDOFF.md), and what is authorized lives in [`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md).

## Current scope: Milestone 1

This repository currently **cannot place trades**. It collects and timestamps:

- Kalshi series metadata
- open markets for a configured series (default: `KXHIGHNY`)
- event metadata
- full public order books
- NWS point metadata
- NWS 12-hour forecasts
- NWS hourly forecasts
- NWS raw grid forecast data

Every response is stored as immutable JSON in SQLite with a receipt timestamp and SHA-256 hash.

The immediate research question is:

> What exactly did the market look like at a given moment, and what forecast information was available to us at that same moment?

We do **not** model or trade until that question can be answered reproducibly.

## Why KXHIGHNY?

Kalshi's API documentation uses `KXHIGHNY` ("Highest temperature in NYC today?") as a public market-data example. It is a convenient recurring market for testing collection and probability-model infrastructure.

Important: the NWS data collected here is a **research input**, not assumed to be Kalshi's settlement source. Before any strategy work, we must verify the current contract terms and reproduce settlement from the official source/rules.

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/jasonleetucker-code/market-edge-lab.git
cd market-edge-lab

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

NWS requires a User-Agent that identifies the application. Keep contact information in your environment, not in the repository:

```bash
export NWS_USER_AGENT="market-edge-lab/0.1 (contact: your-email@example.com)"
```

Collect one snapshot:

```bash
edge-lab collect --source all --db data/edge_lab.sqlite3
```

Inspect recent stored snapshots:

```bash
edge-lab recent --db data/edge_lab.sqlite3 --limit 20
```

Check per-source health and freshness (exits non-zero if anything is stale or unknown):

```bash
edge-lab health --db data/edge_lab.sqlite3        # add --json for machine-readable output
```

Validate the experiment registry:

```bash
edge-lab experiments validate
```

Run tests:

```bash
python -m pytest
```

`edge-lab collect` runs each source in isolation. One failing source does not lose the
others. The run is recorded as `succeeded`, `partial` or `failed`, and the exit code is
non-zero unless every source was clean.

## Other useful collection commands

Kalshi only:

```bash
edge-lab collect --source kalshi --series KXHIGHNY
```

NWS only:

```bash
edge-lab collect --source nws
```

Use a different reference point:

```bash
edge-lab collect --source nws --lat 40.7812 --lon -73.9665
```

## Data model

The SQLite database contains:

- `collection_runs`: start/end/status for each collector run
- `snapshots`: one immutable row per fetched API response (UPDATE/DELETE are blocked by triggers)
- `source_health`: one row per source per run, with status, record count, bytes, retries,
  anomalies and error

Each snapshot records:

- run ID
- source
- payload kind
- entity ID
- receipt timestamp in UTC
- source timestamp when available
- exact URL requested
- SHA-256 of canonical JSON
- full raw JSON payload
- provenance: final URL, HTTP status, content type, byte size, raw-bytes SHA-256, retry
  attempts, fetch duration, parser/schema version, and a structural shape fingerprint

Existing Milestone 1 databases migrate in place. Details: `docs/DATA_PROVENANCE.md`.

Raw data and local databases are intentionally excluded from Git.

## Public APIs used

Kalshi production public market data:

```text
https://external-api.kalshi.com/trade-api/v2
```

National Weather Service:

```text
https://api.weather.gov
```

No API keys or brokerage credentials are required for Milestone 1.

## Milestone 1 acceptance gate

We do not begin probability modeling until we can:

1. run collection repeatedly without corrupting prior snapshots;
2. show the exact Kalshi books that were available at a historical collection timestamp;
3. show the weather forecasts available at that timestamp;
4. preserve the raw payloads required to audit our parsing;
5. verify the target contract's settlement source and rules separately.

See `docs/MILESTONE_1.md`.
