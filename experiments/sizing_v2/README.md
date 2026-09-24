# Stake sizing v2: SIMULATION evidence (not a registered experiment)

This is research evidence for ADR 0026 (`docs/decisions/0026-stake-sizing-v2-challenger.md`)
and `docs/research/STAKE_SIZING_V2.md`. It is **not** an experiment in the registry:
- there is no `experiment.toml`;
- nothing here is preregistered;
- no result here authorizes a change to any shadow fill.

| File | What it is |
|---|---|
| `results/SIMULATION_REPORT_seed20260924.md`, `results/simulation_seed20260924.json` | Run 3, the current results: 188 variant runs, seed 20260924, 200 paths x 250 rounds, simulation v2 |
| `results/run2_superseded_*` | Run 2: 188 variant runs. Superseded because the joint policy H applied the Kelly fraction after the shared budget (a confound fixed in PR #60 review). Only the H variants differ from run 3 |
| `results/run1_superseded_*` | Run 1: 171 variant runs, kept because every run counts. Superseded because sizer-side scenarios did not share worlds (common random numbers) |
| `PROPOSED_PREREGISTRATION.md` | The prospective sizing experiment that must pass before v2 may influence operational shadow fills. PROPOSED only |
| `counterfactual/README.md` | The read-only counterfactual runner (`edge-lab sizing counterfactual`): recorded shadow decisions replayed point-in-time through policies A-H. RESEARCH only; no real-data run recorded yet |

Reproduce with:

```
edge-lab sizing simulate --paths 200 --rounds 250 --workers 18
```

It is deterministic for a fixed seed and Python version; about 13 minutes on 18 cores.

The PR #60 re-review fixes changed only the recommendation layer: starter-verdict binding,
market timing, held-position validation, and joint caps inside the optimizer. The simulation
calls `solve` directly and was not affected. A full re-run after those fixes reproduced run
3's results exactly. The committed files carry that re-run's provenance: the source hashes of
commit 59f7ebd.

The final re-review fixes changed only `_prepare`, `_size_one`, `_apply_caps` and
`recommend_cluster`, none of which the simulation calls:
- binding the starter verdict to the market's timing;
- keeping single-candidate caps inside the solver;
- refusing duplicate market ids;
- inconsistent cash;
- binding precedence.

`solve` and `sizing_eval.py` are unchanged, so the numbers are unchanged. Only the recorded
`sizing_v2.py` hash is older than the current source.

**Replay over EXP-001 history:** SKIPPED (`edge-lab sizing replay --exp001`). The Gate 3
dataset has no market prices, and the Stage A test split stays protected.

Every figure is **SIMULATION evidence** from synthetic markets. It is not a backtest and not
an edge claim.
