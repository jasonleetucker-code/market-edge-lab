# Sizing v2 counterfactual runner (RESEARCH ONLY)

This is the directive of 2026-09-24, deliverable 1 (`docs/owner/2026-09-24-next-build-chunk-directive.md`).
It is **not** a registered experiment and it authorizes nothing: no shadow fill changes, and the
operational account keeps `EXP-001-fixed-1-v1`. Code: `src/edge_lab/sizing_counterfactual.py`.
Tests: `tests/test_sizing_counterfactual.py`.

## What it does

The runner replays every decision in the shadow ledger through the canonical engine
(`sizing_v2.recommend`) once per policy. Every decision is included: QUALIFY and REJECT, with
every reason. Each policy runs on its own isolated simulated account.

| Letter | Policy (frozen, versioned in `sizing_v2`) |
|---|---|
| A | `SV2-A-flat-unit` v1 |
| B | `SV2-B-fixed-2pct` v1 |
| C | `SV2-C-full-kelly` v1 |
| D | `SV2-D-half-kelly` v1 |
| E | `SV2-E-quarter-kelly` v1 |
| F | `SV2-F-robust-kelly` v1 (robust Kelly at fraction 1; `sizing_eval.F_HALF` is the 1/2 variant) |
| G | `SV2-G-risk-constrained-kelly` v1 |
| H | `SV2-H-cluster-robust-rck` v1 (`sizing_v2.POLICY_CANDIDATE`) |

The runner defines no new policy. The only engine change is the additive `sizing_v2.precheck`, a
read-only helper that returns the engine's own pre-optimizer refusal reason.

## Point-in-time rules

- A decision is sized at its own `as_of`. The sizer sees:
  - settled cash;
  - reservations and open positions;
  - event and cluster exposure, drawdown and loss headroom, all through `risk.assess`;
  - only the fills and settlements known by then.
- A settlement is attached only when its knowledge time is at or before the replay clock. That
  time is the first captured settlement page that makes the outcome conclusive under the
  canonical rules, or `shadow_ledger.knowledge_time` for a ledger settlement entry.
- Fills use `fill_policy.simulate_fill` (latency-confirmed-v1) with the counterfactual
  quantity. The confirmation quote comes from the evidence database. A fill is known at the
  confirmation's receipt time.
- Every zero size carries its exact reason as `zero_size_reason` = `VERDICT:CODE`. Examples:
  `ZERO_EDGE:NO_EDGE`, `STALE_DATA:BOOK_STALE`, `CAPITAL_HORIZON:TRADABLE_CASH_RELEASE_UNKNOWN`,
  `RISK_LIMIT:CLUSTER_CAP`, `LIQUIDITY_LIMIT:NO_DEPTH`.

## Run it

Both inputs are opened read-only. The run is written only to `--out`, and an input path is
refused as the output.

```
PYTHONPATH=src python -m edge_lab.cli sizing counterfactual \
  --db data/edge_lab.sqlite3 --ledger data/shadow_ledger.sqlite3 \
  --out /var/lib/market-edge-lab/status/sizing_counterfactual.json [--as-of 2026-10-01T00:00:00+00:00]
```

The output is a bundle (`counterfactual-sizing-bundle-v1`) that holds one
`CounterfactualSizingRun` (`counterfactual-sizing-run-v1`) per policy.

- **Headline fields:** `run_id`, `policy_id`/`policy_version`, `dataset_cutoff`, the counts, the
  starting and ending bankroll, `net_pnl`, `max_drawdown`, `turnover`, `capital_lock`,
  `veto_counts`, `cap_counts`, `metrics`.
- **`metrics`:** fees, log and geometric growth, max, average and worst-rolling (168 h)
  drawdown, volatility, CVaR, zero-size frequency and reasons, average fraction, and the counts
  of verdicts, bindings, secondary constraints and fill statuses.
- **Null metrics:** CVaR is null below 40 settled positions, and volatility is null below 2.
  Each null carries its reason.
- **`events[]`:** one row per decision, with the fields the directive lists and more.

The JSON is deterministic. It holds no wall-clock fields, and it carries source-code hashes,
ledger head hashes and the hash of the replayed decisions.

## Limitations (also in every bundle)

- **Depth:** only the recorded top of book is used, so every liquidity cap is
  top-of-book-limited. A counterfactual size above the displayed size does not fill.
- **Market timing:** it comes from the decision's own recorded STARTER_MAX_7D_V1 verdict.
  - A decision without one is refused (CAPITAL_HORIZON). This covers the 2026-09-23 day: the
    policy applied from 2026-09-24.
  - A missing verdict is never re-assessed at replay time.
- **Model:** each market is two states, YES and NO.
  - The other brackets of the event are unmapped cluster exposure, which the engine treats as
    lost in every state. This is conservative.
  - The uncertainty set comes from the recorded conservative bounds of both sides. A missing
    bound is widened to 0 or 1.
- **Fees before 2026-09-23:** decisions made before the KXHIGHNY fee verification record fail
  closed (`FEE_UNVERIFIED`).
- **Conservative costs:** costs include the ADR 0017 claim allowance, so P&L is a lower bound.
- **Statistics:** a few settlements imply no statistical significance. This is descriptive
  research evidence, not an edge claim.

## Runs recorded here

None yet. No copy of the production ledger exists on the development laptop. The only local
evidence database is an old schema-v3 capture with no ledger, and the runner refuses it
(read-only schema check). To produce the first real run, run the command above on a **copy** of
the production ledger and evidence database. Keep every run, including uninteresting ones.
