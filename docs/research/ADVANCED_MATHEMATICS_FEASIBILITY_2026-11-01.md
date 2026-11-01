# Market Edge Lab — advanced mathematics feasibility companion (2026-11-01)

**Authority:** RESEARCH / PLANNING ONLY. This repository is a **separate read-only prediction-market research lab**, not the Chase Upside dynasty scoring application. Its canonical idea registry is docs/OWNER_IDEAS.md; delivery roadmap is docs/strategy/DELIVERY_ROADMAP.md and only docs/EXECUTION_PLAN.md determines authorization. No trading, live order permission, new source, spend, data-view window, protocol amendment, deployment, unblinding, model promotion or experiment-slot change is implied by this audit.

**Inspection:** README.md, AI_INSTRUCTIONS.md, HANDOFF.md, docs/EXECUTION_PLAN.md, docs/RESEARCH_PRINCIPLES.md, docs/strategy/DELIVERY_ROADMAP.md and documented EXP-002 E1 design review; architecture tree and Python research/execution modules. No production database, protected market books or outcome labels were accessed; existing conclusions from documentation are not reproduced as new analysis. Model/PR status can advance after this audit, so reverify main.

## I. Real capabilities and protected boundaries

The lab captures immutable, time-stamped NWS and Kalshi source evidence in SQLite; has EXP-001 NYC temperature calibration/settlement research, NFL sportsbook/prediction-market paired evidence EXP-002, NHL collection, opportunities at executable quotes (not midpoint), deterministic shadow ledger, fee/economics discipline, latency/fill counterfactuals, guarded sizing and explicit research gates. Python 3.11+; app under src/edge_lab with tests and experiment protocols. See docs/RESEARCH_PRINCIPLES.md: independently correct time, settlement, labels, costs, dependence, multiple testing, data-rights and claims ladder. **EXP-001 protected forward sample and EXP-002 frozen/blocked gate status must remain intact.**

The v1 E1 design review flags inference risks at small numbers of NFL-week clusters, including anti-conservative unrestricted wild bootstrap; it proposes null-imposed studentized sign-flip and exact-enumeration corrections as a methodology review, not approval. Its economics are GROSS under a stated zero-latency model, NOT proof of an after-fee tradable edge. Existing completed research, owner decisions and stop rules outrank new mathematical ideas.

## II. Seven original disciplines — prediction-market verdict

| Field | Evidence-grounded potential | Verdict |
|---|---|---|
| Arithmetic algebraic geometry | Polynomial constraints could encode no-arbitrage accounting identities, but linear/programmatic inequality validation is simpler | REJECT exotic version |
| Higher category theory | Typed source/event/market/fee transformations and provenance compose, but ordinary type contracts work better | REJECT as math program |
| Algebraic topology | Anomaly/microstructure-regime clustering on *licensed high-frequency* book trajectories might be studied against simple clustering; latency and rights constraints dominate | RESEARCH LATER |
| Analytic number theory | No credible unique application to event probabilities, order flow or outcome inference | REJECT |
| PDEs | Continuous-time option-style models require process and boundary assumptions not evidenced by the discrete event markets; state-space models preferred | REJECT |
| Set theory/formal logic | Typed mutually exclusive/collectively exhaustive settlements, combination consistency and invalid state/fee proofs; SAT/SMT can strengthen tests | PROTOTYPE TEST-ONLY |
| Differential geometry | Information-geometric calibration and model divergence are conceptually legitimate but conventional proper scores/reliability diagnostics are better first | RESEARCH LATER |

## III–V. Best applied opportunities (ranked, conceptual / not empirical scores)

Feasibility score out of 100 is a prioritization judgment, not a statistical result. Rubric: advantage 25, evidence 20, data 15, feasibility 15, strategy 10, interpretability 10, cost 5.

| Priority | Technique and scope | Score | Comparator and concrete test | Gate |
|---|---|---|---|---|
| 1 | PIT horizon-conditional calibration with hierarchical partial pooling by event type/market age/liquidity | 21+18+13+13+10+9+4=88 | Against contemporaneous market probability and existing frozen baseline: held-out Brier/log score and reliability curves, grouped by event; no outcome-look or protected-label access | Research only, new approved study/freeze |
| 2 | Dependence-aware clustered inference and multiplicity control | 21+19+13+13+10+9+4=89 | Exact/statistically valid NFL-week/event-cluster tests versus current E1 design; validate under **synthetic null**, size/power, selection attrition and multiple strategies before even considering protected outcomes | Engineering research; cannot change EXP-002 freeze without decision |
| 3 | Execution/economic robustness under fill, latency, spreads, fees, capacity and outages | 24+17+12+12+10+9+3=87 | Opponent benchmark is **after-fee executable** conservative bound, not midpoint signal; separate gross markout from realized/feasible profit, use shadow only | Existing Gate 7, owner-held later real orders |
| 4 | Hierarchical latent-price or state-space filtering | 18+14+10+10+8+8+4=72 | Alternative to simple lagged consensus and price; establish whether inferred state predicts genuinely available future executable quotes | New slot/permission needed |
| 5 | Coherence/constraint solver for logical market combinations | 18+17+11+13+9+9+4=81 | Synthetic settlement and money-unit contracts checked against existing validators, unambiguous fee/size, no invented fills | Test-only, reviewed |
| 6 | Robust resource/sizing optimization over related shadow opportunities | 20+14+9+10+9+7+3=72 | Compare with existing capped fractional Kelly, correlated-event and worst-case exposure bound; no real orders | After shadow economics validated |
| 7 | Optimal transport distribution shift between forecast vintages | 13+10+8+8+7+6+3=55 | Compare simple reweighting/rolling calibration first; missing stable source/version labels blocks | Speculative |
| 8 | Change-point and regime detection with transparent hysteresis | 16+13+11+10+8+8+4=70 | Compare simpler rolling windows and lag-safe state transitions | Slot/budget gated |
| 9 | Information geometry on calibrated probabilities | 12+10+10+9+6+5+3=55 | Compare expected log score + direct divergence | Very low priority |
| 10 | Persistent-homology regime classification | 12+8+5+6+6+4+2=43 | Compare PCA/UMAP/GMM and change-point baselines on licensed order-book data | Reject until input case exists |

Ordering when score differs: prioritize #2 before #1 in any work affecting confirmatory inference, then respect existing execution plan/owner gates; scores alone DO NOT confer authorization. No live-order recommendation is made.

## VI. Three proposed proof-of-concept studies, dependent on explicit gate

1. **Synthetic inference stress test:** simulate NFL-game/week clustered null returns with bounded cluster counts, opt-in strategy selection and missing-exit fallback. Compare false-positive frequency (nominal alpha), confidence-bound coverage, power and width using current E1-style unrestricted bootstrap, null-imposed studentized sign flip and a conservative small-G alternative. This study needs NO protected market labels; retain frozen artifacts and exact test receipts. STOP if claimed significance is anti-conservative.
2. **PIT calibration under data rights:** use future, separately authorized, truly timestamped event snapshots and their **event-available labels only after precommitted evaluation**. Compare market quotes, simple logistic/isotonic calibration, hierarchical horizon-calibration and effects of fee/liquidity eligibility. Group by event, category, time-to-event; Brier/log loss and expected economics. NO re-opening EXP-001 data outside its predeclared looks. STOP if output is only cosmetically calibrated or does not survive executable quotes/fees.
3. **No-arbitrage/contract property harness:** on synthetic orders, fees, settlement partitions, canceled/missing fills, events and combinations, test Boolean contract implications and worst-case state consistency using existing validators first, optionally Z3. STOP if ordinary algebra/unit/type assertions prove the same cases more cheaply. No actual orders.

Complexity: small synthetic test 1–3 days, calibration framework several days PLUS authorized data collection, typed constraints 1–3 days. These are rough planning guesses, not completed resource profiling.

## VII. Mathematical deep dive: dependence-aware inference

Let x_gi be a synthetic per-trade gross markout for trade i in NFL week g, with G **independent clusters** at the week level. The mean under the null is mu <= 0. A naive iid trade-level bootstrap is wrong if trades from one week share games, information, and shocks. A null-imposed studentized week-cluster sign-flip statistic based on centered cluster scores provides a potential small-G procedure; enumerate all distinct sign assignments when feasible and report coarse attainable p-values. Test type-I error using seeded simulations generated independently of real outcomes. The E1 design review already identifies this problem and proposes such corrections; **this proposal is reuse/validation, not a replacement decision**.

Plain English: several trades made during the same NFL week are not several independent experiments. A method that pretends they are can report fake statistical confidence. Test the statistics on controlled artificial data before trusting a trading-edge headline.

## VIII. Competitive/evidence boundaries

- Kalshi's August 2026 calibration study reports very strong aggregate near-resolution calibration across its resolved market history; this is evidence that market probabilities can be a formidable baseline, NOT evidence of an exploitable strategy: https://kalshi.com/research/publications/calibration
- Kagan/Baiocchi, Calibration in Prediction Markets: Theory and Evidence (Aug 2026): https://papers.ssrn.com/sol3/Delivery.cfm/7355520.pdf?abstractid=7355520
- Walker, 2026 Princeton thesis on Polymarket with event-clustered bootstrap: https://theses-dissertations.princeton.edu/entities/publication/d5708372-5ea3-4252-b669-7f9cee07387c
- Forecast calibration versus accuracy selection in sports odds: https://www.sciencedirect.com/science/article/pii/S266682702400015X
These external findings do not establish profit, venue eligibility, rights, market access or latency.

## IX. Roadmap / ownership

**ME-AMATH-01** is an idea/evaluation pointer, not a new active empirical family. Link from docs/OWNER_IDEAS.md and docs/strategy/DELIVERY_ROADMAP.md to this companion research note. Integrate prospective experiments only through existing EXP-001/EXP-002 research-governance, explicit experimental slots and fee/quote/settlement provenance; preserve #96 two-active-family budget, all protected looks and owner-held real trading. Reuse src/edge_lab/research_evidence.py, research_economics.py, domain constraints and statistical design ownership. Do not create a parallel risk engine or new "Market Edge Model Lab." Research here cannot supersede owner decisions from 2026-09–10.

## X. Verdict

The highest-return math for Market Edge is **valid clustered inference, calibrated probabilistic forecasting conditional on event context, and conservative execution-economics/risk constraints**. Of seven original fields, formal logic is the best correctness method; topology and information geometry are interesting but low value. Analytic number theory, PDEs, arithmetic geometry and higher category theory provide no compelling site-specific benefit now. There is **no measured new edge, no model promotion and no change of trading authorization** from this audit.
