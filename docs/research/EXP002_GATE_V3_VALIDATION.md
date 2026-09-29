<!-- Generated output, not edited: `PYTHONPATH=src python scripts/research_power_sensitivity.py --gate-v3-validation --reps 200`, run 2026-09-28 on branch feat/exp002-gate-v3 (base 4e8e71d) with the gate v3 code of this PR. Deterministic: a rerun reproduces it (tests/test_sports_evidence_gate_v3.py checks the document against a rerun of one scenario). Interpretation and caveats: docs/research/EXP002_GATE_V3.md section 4. SYNTHETIC SIMULATION ONLY: no real data. -->

# EXP-002 gate v3 adversarial validation (`exp002-gate-v3-validation-v1`)

SIMULATION UNDER STATED ASSUMPTIONS. True bias = mean cross-book markout under the scenario's null (60,000 simulated games, seed 20261001); 200 label-free gate samples per scenario (seed 20260928; 200 bootstrap resamples). False pass: a pass while the true bias is above 0.25 x delta_min by more than 2 SE (BORDERLINE rows are excluded). Acceptance: at most 10%. `v3 bound below` is what v3 would pass IF assumption W were granted; v3 itself never passes.

| rule | rows with bias above tolerable | worst false-pass rate | rows over 10% | rows below | lowest pass rate when below |
|---|---|---|---|---|---|
| spread_candidate | 37 | 98% | 21 | 15 | 0% |
| v3_conditional_bound | 37 | 88% | 4 | 15 | 0% |
| v3_conditional_bound_where_W_holds | 2 | 0% | 0 | 12 | 0% |
| v3_conditional_bound_where_W_fails | 35 | 88% | 4 | 3 | 0% |
| v3_verdict | 37 | 0% | 0 | 15 | 0% |

| scenario | W holds | delta_min | tolerable | true bias (SE) | bias vs tolerable | candidate PASS | v3 bound below (if W) | v3 PASS | v3 verdicts |
|---|---|---|---|---|---|---|---|---|---|
| w_holds_mirror_one_tick | yes | 0.25c | 0.062c | +0.045c (0.008) | BELOW | 0% | 0% | 0% | FAIL 200 |
| w_holds_mirror_one_tick | yes | 0.50c | 0.125c | +0.045c (0.008) | BELOW | 0% | 0% | 0% | FAIL 200 |
| w_holds_mirror_one_tick | yes | 1.00c | 0.250c | +0.045c (0.008) | BELOW | 0% | 0% | 0% | FAIL 200 |
| w_holds_varied_widths | yes | 0.25c | 0.062c | +0.046c (0.008) | BELOW | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| w_holds_varied_widths | yes | 0.50c | 0.125c | +0.046c (0.008) | BELOW | 20% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| w_holds_varied_widths | yes | 1.00c | 0.250c | +0.046c (0.008) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| w_holds_varied_widths_wide_gaps | yes | 0.25c | 0.062c | +0.002c (0.008) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| w_holds_varied_widths_wide_gaps | yes | 0.50c | 0.125c | +0.002c (0.008) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| w_holds_varied_widths_wide_gaps | yes | 1.00c | 0.250c | +0.002c (0.008) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within | yes | 0.25c | 0.062c | +0.173c (0.008) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within | yes | 0.50c | 0.125c | +0.173c (0.008) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within | yes | 1.00c | 0.250c | +0.173c (0.008) | BELOW | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within_wide_gaps | yes | 0.25c | 0.062c | +0.056c (0.009) | BORDERLINE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within_wide_gaps | yes | 0.50c | 0.125c | +0.056c (0.009) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| asymmetric_spreads_within_wide_gaps | yes | 1.00c | 0.250c | +0.056c (0.009) | BELOW | 100% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| review_grid_rho_055 | no | 0.25c | 0.062c | +0.243c (0.009) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| review_grid_rho_055 | no | 0.50c | 0.125c | +0.243c (0.009) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| review_grid_rho_055 | no | 1.00c | 0.250c | +0.243c (0.009) | BORDERLINE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream | no | 0.25c | 0.062c | +0.836c (0.011) | ABOVE | 4% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream | no | 0.50c | 0.125c | +0.836c (0.011) | ABOVE | 4% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream | no | 1.00c | 0.250c | +0.836c (0.011) | ABOVE | 4% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_near_mirror | no | 0.25c | 0.062c | +0.846c (0.011) | ABOVE | 98% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_near_mirror | no | 0.50c | 0.125c | +0.846c (0.011) | ABOVE | 98% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_near_mirror | no | 1.00c | 0.250c | +0.846c (0.011) | ABOVE | 98% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_wide_gaps | no | 0.25c | 0.062c | +0.286c (0.012) | ABOVE | 4% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_wide_gaps | no | 0.50c | 0.125c | +0.286c (0.012) | ABOVE | 4% | 14% | 0% | INSUFFICIENT_EVIDENCE 200 |
| shared_upstream_wide_gaps | no | 1.00c | 0.250c | +0.286c (0.012) | ABOVE | 4% | 88% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale | no | 0.25c | 0.062c | +0.765c (0.011) | ABOVE | 97% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale | no | 0.50c | 0.125c | +0.765c (0.011) | ABOVE | 97% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale | no | 1.00c | 0.250c | +0.765c (0.011) | ABOVE | 97% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale_wide_gaps | no | 0.25c | 0.062c | +0.376c (0.011) | ABOVE | 95% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale_wide_gaps | no | 0.50c | 0.125c | +0.376c (0.011) | ABOVE | 95% | 11% | 0% | INSUFFICIENT_EVIDENCE 200 |
| narrow_but_stale_wide_gaps | no | 1.00c | 0.250c | +0.376c (0.011) | ABOVE | 95% | 88% | 0% | INSUFFICIENT_EVIDENCE 200 |
| sticky_band | no | 0.25c | 0.062c | +0.363c (0.009) | ABOVE | 96% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| sticky_band | no | 0.50c | 0.125c | +0.363c (0.009) | ABOVE | 96% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| sticky_band | no | 1.00c | 0.250c | +0.363c (0.009) | ABOVE | 96% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| zero_movement_hidden | no | 0.25c | 0.062c | +1.084c (0.011) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| zero_movement_hidden | no | 0.50c | 0.125c | +1.084c (0.011) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| zero_movement_hidden | no | 1.00c | 0.250c | +1.084c (0.011) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| common_move_between_captures | no | 0.25c | 0.062c | +0.396c (0.010) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| common_move_between_captures | no | 0.50c | 0.125c | +0.396c (0.010) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| common_move_between_captures | no | 1.00c | 0.250c | +0.396c (0.010) | ABOVE | 0% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| discreteness_small_noise | no | 0.25c | 0.062c | +0.020c (0.008) | BELOW | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| discreteness_small_noise | no | 0.50c | 0.125c | +0.020c (0.008) | BELOW | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| discreteness_small_noise | no | 1.00c | 0.250c | +0.020c (0.008) | BELOW | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| week_dependence | no | 0.25c | 0.062c | +0.490c (0.010) | ABOVE | 96% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| week_dependence | no | 0.50c | 0.125c | +0.490c (0.010) | ABOVE | 96% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| week_dependence | no | 1.00c | 0.250c | +0.490c (0.010) | ABOVE | 96% | 2% | 0% | INSUFFICIENT_EVIDENCE 200 |
| partial_persistence | no | 0.25c | 0.062c | +0.441c (0.010) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| partial_persistence | no | 0.50c | 0.125c | +0.441c (0.010) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| partial_persistence | no | 1.00c | 0.250c | +0.441c (0.010) | ABOVE | 94% | 0% | 0% | INSUFFICIENT_EVIDENCE 200 |
| small_sample_missing | no | 0.25c | 0.062c | +0.771c (0.010) | ABOVE | 0% | 1% | 0% | FAIL 16, INSUFFICIENT_DATA 184 |
| small_sample_missing | no | 0.50c | 0.125c | +0.771c (0.010) | ABOVE | 0% | 1% | 0% | FAIL 16, INSUFFICIENT_DATA 184 |
| small_sample_missing | no | 1.00c | 0.250c | +0.771c (0.010) | ABOVE | 0% | 2% | 0% | FAIL 16, INSUFFICIENT_DATA 184 |

Scenarios:

- `w_holds_mirror_one_tick`: discreteness; mirror quoting (both books the tick interval around V)
- `w_holds_varied_widths`: control where assumption W holds: V inside each book's spread
- `w_holds_varied_widths_wide_gaps`: control where W holds, consensus far from Kalshi (sd 6c)
- `asymmetric_spreads_within`: asymmetric spreads: a shared 1-tick skew plus 0-1 tick widening, V inside the spread (W holds)
- `asymmetric_spreads_within_wide_gaps`: the same, consensus far from Kalshi (sd 6c)
- `review_grid_rho_055`: the #119 review grid: 1c noise, book-noise correlation 0.55, 1-tick quotes
- `shared_upstream`: correlated team-market quoting / a shared upstream source (1.5c shared error, 0.2c book-specific)
- `shared_upstream_near_mirror`: a shared upstream source with near-mirror books (1.5c shared, 0.1c book-specific)
- `shared_upstream_wide_gaps`: shared upstream error with consensus far from Kalshi (sd 6c)
- `narrow_but_stale`: narrow but stale quotes: 35% of games quote a fair 3c-SD old
- `narrow_but_stale_wide_gaps`: narrow but stale quotes, consensus far from Kalshi (sd 6c)
- `sticky_band`: sticky prices: a shared hysteresis band of +-1.5c
- `zero_movement_hidden`: zero observed movement with hidden uncertainty: half the T-6h quotes unchanged since T-24h while V moved (3c SD)
- `common_move_between_captures`: a common-value move between the two captures (1.5c) inflating the dispersion, with a 1c shared error
- `discreteness_small_noise`: price discreteness with 0.1c book-specific error
- `week_dependence`: cross-game and cross-week dependence: 1c week-shared error, 1c week-shared consensus deviation, 0.5c game-shared error
- `partial_persistence`: sticky error that half persists to T-60m (1.5c shared)
- `small_sample_missing`: small samples and missing horizons: 2 weeks x 8 games, 40% of T-6h pairs missing, 80% for stale games
