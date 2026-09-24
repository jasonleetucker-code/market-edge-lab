# Stake sizing v2: SIMULATION evidence (not a registered experiment)

This is research evidence for ADR 0026 (`docs/decisions/0026-stake-sizing-v2-challenger.md`)
and `docs/research/STAKE_SIZING_V2.md`. It is **not** an experiment in the registry:
- there is no `experiment.toml`;
- nothing here is preregistered;
- no result here authorizes a change to any shadow fill.

| File | What it is |
|---|---|
| `results/SIMULATION_REPORT_seed20260924.md`, `results/simulation_seed20260924.json` | Run 2, the current results: 188 variant runs, seed 20260924, 200 paths x 250 rounds |
| `results/run1_superseded_*` | Run 1: 171 variant runs, kept because every run counts. Superseded because sizer-side scenarios did not share worlds (common random numbers) |
| `PROPOSED_PREREGISTRATION.md` | The prospective sizing experiment that must pass before v2 may influence operational shadow fills. PROPOSED only |

Reproduce with:

```
edge-lab sizing simulate --paths 200 --rounds 250 --workers 18
```

It is deterministic for a fixed seed; about 22 minutes on 18 cores.

**Replay over EXP-001 history:** SKIPPED (`edge-lab sizing replay --exp001`). The Gate 3
dataset has no market prices, and the Stage A test split stays protected.

Every figure is **SIMULATION evidence** from synthetic markets. It is not a backtest and not
an edge claim.
