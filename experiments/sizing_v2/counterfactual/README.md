# Sizing v2 counterfactual runner (RESEARCH ONLY)

This is the directive of 2026-09-24, deliverable 1 (`docs/owner/2026-09-24-next-build-chunk-directive.md`).
It is **not** a registered experiment and it authorizes nothing: no shadow fill changes, and the
operational account keeps `EXP-001-fixed-1-v1`. Code: `src/edge_lab/sizing_counterfactual.py`.
Tests: `tests/test_sizing_counterfactual.py`, `tests/test_sizing_counterfactual_review.py`.

## What it does

The runner replays every decision in the shadow ledger through the canonical engine
(`sizing_v2.recommend`) once per policy. Every decision is included: QUALIFY and REJECT, with
every reason. Each policy runs on its own isolated simulated account.

| Letter | Policy (frozen, versioned; referenced, never redefined) |
|---|---|
| A | `SV2-A-flat-unit` v1 |
| B | `SV2-B-fixed-2pct` v1 |
| C | `SV2-C-full-kelly` v1 |
| D | `SV2-D-half-kelly` v1 |
| E | `SV2-E-quarter-kelly` v1 |
| F | `SV2-F-robust-half-kelly` v1 (`sizing_eval.F_HALF`, robust 1/2 Kelly: the directive's robust *fractional* Kelly; coordinator decision on PR #64. `sizing_v2.POLICY_F`, robust Kelly at fraction 1, is unchanged) |
| G | `SV2-G-risk-constrained-kelly` v1 |
| H | `SV2-H-cluster-robust-rck` v1 (`sizing_v2.POLICY_CANDIDATE`). **Its joint (cluster) component is inert in this replay**, see Limitations |

The only engine change is the additive `sizing_v2.precheck`, a read-only helper that returns the
engine's own pre-optimizer refusal reason. `edge-lab sizing -h` lists `counterfactual` (a small
additive entry in the `sizing_eval` parser).

## Point-in-time rules

- A decision is sized at its own `as_of`. The sizer sees:
  - settled cash;
  - reservations and open positions;
  - event and cluster exposure, drawdown and loss headroom, all through `risk.assess`;
  - only the fills and settlements known by then.
- A settlement is attached only when its knowledge time is at or before the replay clock. That
  time is the first captured settlement page that makes the outcome conclusive under the
  canonical rules, or `shadow_ledger.knowledge_time` for a ledger settlement entry.
  - The lookup is one pass over the captures in fetch-time order. A test holds it equal to
    rebuilding `settlement_index` at every capture time; 1,000 captures take about 1 s.
  - The first source to know an outcome books it. A disagreeing source (`SOURCES_DISAGREE`)
    or later contradicting evidence (`CONTRADICTED_LATER`) is reported in the bundle's
    provenance, never applied retroactively.
- Fills use `fill_policy.simulate_fill` (latency-confirmed-v1) with the counterfactual
  quantity. The confirmation quote comes from the evidence database, and no quote received
  after the cutoff is read. A fill is known at the confirmation's receipt time; before that the
  row says `fill_status: PENDING`.
- One decision per slot. Accounts that decided the same slot under different ids are merged, the
  operational account's record preferred (`recorded_in_accounts` lists every account).
  Materially different content fails closed (`DECISION_RECORDS_DISAGREE`).
- Every zero size carries its exact reason as `zero_size_reason` = `VERDICT:CODE`. Examples:
  `ZERO_EDGE:NO_EDGE`, `STALE_DATA:BOOK_STALE`, `CAPITAL_HORIZON:TRADABLE_CASH_RELEASE_UNKNOWN`,
  `RISK_LIMIT:CLUSTER_CAP`, `LIQUIDITY_LIMIT:NO_DEPTH`.

## Run it

Both inputs are opened read-only, and the run is written only to `--out`.

- An existing `--out` is refused unless `--overwrite` is passed. Name each run by its cutoff.
- An input, or one of its SQLite sidecar files (`-wal`, `-shm`, `-journal`), is always refused
  as the output.

```
PYTHONPATH=src python -m edge_lab.cli sizing counterfactual \
  --db /path/to/copy/edge_lab.sqlite3 --ledger /path/to/copy/shadow_ledger.sqlite3 \
  --as-of 2026-10-01T00:00:00+00:00 \
  --out experiments/sizing_v2/counterfactual/runs/cutoff_2026-10-01T0000Z.json
```

### Running against production data

- **Prefer copies.** Run on a verified backup or export of the ledger and the evidence
  database (the F09 checkpoint copies), not on the live files.
- **On the host, run as the service user (`edgelab`),** never as root. Then any file SQLite
  creates keeps the service's ownership.
- **Never open a live database with `immutable=1`.** SQLite then skips locking and can read a
  torn state while the collector writes.
- **SQLite may create sidecar files.** `SnapshotStore.open_readonly` on the WAL-mode evidence
  database may create its `-wal` and `-shm` files. SQLite needs them to read WAL safely. The
  main database file is byte-unchanged, and a test proves it. The shadow ledger (rollback
  journal) creates nothing.
- **Do not run inside the protected windows.** Keep it out of 17:40-18:50 America/New_York and
  away from a running settlement job, even though it is read-only.

## Output

The output is a bundle (`counterfactual-sizing-bundle-v1`) that holds one
`CounterfactualSizingRun` (`counterfactual-sizing-run-v1`) per policy. Every run carries the
limitations below.

- **Headline fields:** `run_id`, `policy_id`/`policy_version`, `dataset_cutoff`, the counts, the
  starting and ending bankroll, `net_pnl`, `max_drawdown`, `turnover`, `capital_lock`,
  `veto_counts`, `cap_counts`, `metrics`.
- **`metrics`:**
  - fees, log and geometric growth, volatility and CVaR;
  - drawdown: max, average and worst-rolling. The average is **event-averaged**: the mean over
    the equity-curve points (the first decision and each settlement), not time-weighted. The
    worst-rolling drawdown uses a 168 h window, and the curve starts at the first decision;
  - zero-size frequency and reasons, average fraction, and the counts of verdicts, bindings,
    secondary constraints and fill statuses.
- **Null metrics:** CVaR is null below 40 settled positions, and volatility is null below 2.
  Each null carries its reason.
- **`events[]`:** one row per decision, with the fields the directive lists and more.
- **Money** is a cent string. Every simulated amount is a sum of cent-quantized engine costs,
  whole-dollar payouts and a cent-exact starting bankroll, so the cent formatting never rounds.

The JSON is deterministic. It holds no wall-clock fields, and it carries source-code hashes,
ledger head hashes, the hash of the replayed decisions and any recorded re-check read errors.

## Panel API (Terminal v1, Lane B)

- `build_panel_bundle(store, ledger, *, as_of=None)` runs one replay of every policy. It is
  memoized in-process by `panel_cache_key(...)`: the ledger head hashes, the evidence
  database's highest snapshot id, the cutoff, the config, the policies and the code.
- `panel_for_market_from_bundle(bundle, market_id)` is cheap and pure.
- `panel_for_market(store, ledger, market_id, *, as_of=None)` is a thin wrapper over the two.
- None of them raises for missing or unreadable data. The contract is in the module docstring.

## Limitations (also in every run)

- **Depth:** only the recorded top of book is used, so every liquidity cap is
  top-of-book-limited. A counterfactual size above the displayed size does not fill.
- **Fill-time checks:** the canonical path re-checks STARTER_MAX_7D_V1 and applies a pre-fill
  risk veto at fill time. Neither is reproduced here; the cost is reserved at the decision
  instead.
- **Market timing:** it comes from the decision's own recorded STARTER_MAX_7D_V1 verdict.
  - A decision without one is refused (CAPITAL_HORIZON). This covers the 2026-09-23 day: the
    policy applied from 2026-09-24.
  - A missing verdict is never re-assessed at replay time.
- **Model:** each market is two states, YES and NO.
  - The other brackets of the event are unmapped cluster exposure, which the engine treats as
    lost in every state. This is conservative.
  - The uncertainty set comes from the recorded conservative bounds of both sides. A missing
    bound is widened to 0 or 1.
- **Policy H's joint component is inert.** Every decision is sized as a single candidate, so H
  behaves as robust 1/2 Kelly with the robust drawdown constraint. A test shows it equals
  `sizing_eval.G_ROBUST` here, so the replay says nothing about H's cluster optimization.
- **Fees:** decisions before the KXHIGHNY fee verification record (2026-09-23) fail closed
  (`FEE_UNVERIFIED`), and so do decisions after its re-check date `2026-10-23T13:39:48Z` until a
  new verification record is committed.
- **Conservative costs:** costs include the ADR 0017 claim allowance, so P&L is a lower bound.
- **Statistics:** a few settlements imply no statistical significance. This is descriptive
  research evidence, not an edge claim.

## Runs recorded here

None yet. No copy of the production ledger exists on the development laptop. The only local
evidence database is an old schema-v3 capture with no ledger, and the runner refuses it
(read-only schema check). To produce the first real run, follow "Running against production
data" above. Keep every run, including uninteresting ones.
