# Kalshi automation readiness: repository and competitive audit

**Date:** 2026-10-07. **Owner intake:** #160, resumed after an interrupted response. **Audit baseline:** `950c8372c475b9554a1cd0338c6f48517703dd24` (main, #156). **Status:** research and proposed delivery design; no runtime, credentials, acquisition, orders, spending, deployment or gate changes.

Read the delivery campaign in `docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md` and executable handoff in `docs/strategy/CLAUDE_KALSHI_AUTOMATION_160.md`. These refine existing R5/R10, not replace the R0–R11 roadmap or grant implementation authority.

## 1. Executive decision

Move one deep Kalshi **ordinary event-order lifecycle** onto the engineering critical path, alongside the existing research. Do not make completion of in-play, RFQ pricing, every market, autonomous learning or investor features a prerequisite. The best first engineering rehearsal is a simple, available **demo binary event contract** with a synthetic signal and explicit capability manifest. The most economical current research continuation is the existing narrow NFL study because it already has collection and protocol work—not because its alpha is proved. In-play and maker/RFQ research remain legitimate later candidates.

Market has valuable foundations but is **not automation-ready**. Its execution ticket intentionally cannot submit. Its simultaneous-obligation function is pure arithmetic, not an atomic persisted reservation. Its shadow positions, balances and risk are not production account records. Connecting an API key to those structures would not complete the missing system.

The useful external lessons are durability before submission, conservative startup reconciliation, exact units, complete account-history retrieval, evidence-labelled fill economics and strong environment/permission boundaries. No reviewed public project supplied independently audited evidence that Market could reproduce a profitable strategy. Negative author reports are useful warnings, not a theorem that retail trading cannot work.

## 2. Audit coverage and limitations

This is an architectural inventory and **targeted source-code audit**, not a claim that every line, dependency, git-history object or security issue was independently certified.

Inspected through connected GitHub: repository/default branch; recursive tree and relevant directory inventories; open PRs; research/owner/operating documents; execution invariant; execution-ticket construction and reservation functions; risk and shadow-ledger types; in-play consumer and recorded architecture review; source/provenance and experiment contracts; external READMEs and selected recovery/account code.

External coverage: all eleven requested repositories were README-screened; selected implementation was inspected in the strongest relevant examples. License-file verification was completed for Spencer Fletcher's project; other license statements remain README claims unless explicitly noted. No dependency or code was adopted. A future code reuse decision must pin the actual commit and inspect its license, transitive dependencies, tests and relevant implementation. A file blob is a content pin, not a claim about the latest meaningful repository commit.

A local filtered clone failed before checkout with `Could not resolve host: github.com`. Consequently **no local Market full test suite, dependency scan, full-history secret scan, benchmark, exploit test or external bot reproduction was run**. No live provider/API/account, developer worktree, VPS or physical operator UI was inspected. No secret was solicited or printed. No outcome/holdout analysis was run. GitHub CI and production statements below are attributed records, not executions performed by this audit.

The nine X posts in #157 remain unread in that intake; #159 is a resolver proposal, not a working authenticated browser. This mission did not recover those posts or infer their content. POD-01 is the already supplied transcript, with unverified publication date and self-reported performance.

## 3. Current state and overlapping work

Repository metadata reports PUBLIC. That does not make the tailnet-only Terminal public. Do not change either boundary. Main's latest dated operational handoff reports `14704e3`, September 30; today's deployed SHA remains unverified here.

At this audit, open PRs were:

| PR | Head | Actual implication |
|---|---|---|
| #153 | `9de0c35afca764e7ca2ff4acfe63c29a10c2845c` | Reviewed offline provenance fixes; explicitly waits for owner merge authority. Do not duplicate or bypass |
| #158 | `921c178356dd996231b9b226b8e669b1c5b1ed53` | Nine-source access audit and R3a handoff; canonical integration pending |
| #161 | `7b61ef622c9e9ace851709932d0ef3b1e470870c` | Active Polymarket capture-window correction. Preserve its writer and deployment process |

#161 reports 119 targeted tests passing and two full-suite failures reproduced on main in `test_price_observations_nhl_with_odds_pilot.py`. That is the author's baseline evidence; this audit did not rerun it. Its CI must be rechecked. This newly arrived PR supersedes older claims that only #153/#158 were open.

Merged work to reuse: #146 roadmap; #148 RFQ feasibility/pure lifecycle; #149 state/latency/economics; #150 blockers/Terminal; #156 proposed E1 v2/evaluation guards. Existing NHL collection, protected experiments, quota, label withholding, checkpoints and backups must not be rebuilt.

Main's claim table was empty. The interrupted #160 branch contained only this audit's claim; it is resumed rather than duplicated. Pending PRs still own meaningful overlapping changes even when main's claims are empty.

## 4. Architecture and ownership map

The table maps functional areas, not a certification of every subordinate implementation. `Built` below describes code, not fresh production verification. Sources: current OWNER_IDEAS, DELIVERY_ROADMAP, HANDOFF, AI_INSTRUCTIONS, DATA_PROVENANCE, experiment README and targeted files.

| Area / canonical owner | Inputs → outputs; effects | Existing evidence / gap |
|---|---|---|
| `sources.py`, `http.py`, `redaction.py` | Registered permitted source → paced public requests and redacted evidence | Existing ingestion; do not introduce auth into the ordinary research HTTP client |
| `storage.py`, provenance/document storage | Responses → immutable SQLite snapshots, retrievals and exact document blobs | Canonical JSON retained for snapshots; original-byte hash does not recreate original bytes |
| `freshness.py`, `freshness_fabric.py` | Evidence clocks/schedules → validity and supervisor reports | Supervisor observes schedules; new execution staleness policy must consume real input age, not timer health |
| `discovery.py`, `opportunity.py` | Catalog/rules → identities, equivalence, native units and depth | Title similarity remains only candidate matching |
| `odds_api.py`, `odds_schedule.py`, `odds_pilot.py` | NFL/NHL schedule → bounded source snapshots | One 450-credit monthly authority; NFL reservation priority; no new allocation here |
| `odds_consensus.py` | Offered quotes → versioned de-vigged research baseline | Information source, not truth or executable book |
| `price_observations.py`, `sports_evidence.py` | Stored targets/snapshots → pairings and later-price observations | Current label proxy guards preserved; #161 is separate capture work |
| `polymarket_us.py`, `polymarket_sports.py` | US-specific catalog/books → related research evidence | Not International; documented rights/fees/equivalence limits remain |
| `sports_nhl.py` | Hockey schedules/identity → separate development evidence | Not extra independent observations for NFL EXP-002 |
| `forward.py`, `daily.py`, `settlement.py` | Frozen forecasts/books/outcomes → protected daily shadow processing | EXP-001 unchanged; no extra statistical looks |
| `fee_schedules.py`, frozen `fees.py` | Versioned schedule and scope → charge/unsupported verdict | Account precision and actual fill fees still needed for execution; no generic NFL/NHL maker fee assumption |
| `best_price.py`, payoff constraints | Verified depth/payoff relation → size economics or refusal | No guaranteed multi-leg execution, no estimated joint probability model |
| `experiments.py`, `research_evidence.py` | Protocols/data roles → freezes, slots, exposure/attrition | Two active families beside protected EXP-001; access log cannot certify out-of-band ignorance |
| `research_economics.py` | Episodes/fill assumptions/capital → bounded economics | Reuse denominator and fixed-cost separation; hypothetical fills are not venue fills |
| `research_readiness.py`, `current_blockers.py` | Canonical records → readiness/blocker views | Expand factual capability evidence, not a percent-complete score |
| `inplay_evidence.py` | Journal → sequence-correct book/state/clock history | #153 already fixes data-kind and timestamp attribution; R3a prefix lineage/as-of completion remains |
| `position_policy.py`, `inplay_replay.py`, `inplay_view.py` | Simulated inventory/admissible data → hold/reduce/exit replay/view | No recorder/account; RECORDED evidence refused by present view; last-transition as-of gap recorded |
| `rfq_research.py` | Fixtures → RFQ lifecycle/obligation observations | NARROW feasibility; private competitor quotes unavailable; no quote gateway |
| `shadow_ledger.py` | Four immutable event kinds → replayed shadow account | Schema v1, integer positions, OPEN/SETTLED; not actual partial-sale/account ledger |
| `risk.py`, sizing, starter policy | Shadow state → cash/risk/capital eligibility | Cost-basis equity moves at settlement; not live mark-to-market risk; 168h policy preserved |
| `execution_ticket.py` | Qualified inputs → unexecutable ticket/preflight and pure obligation sum | No signer, account reader or actual durable order journal |
| `backup.py`, `ledger_anchor.py` | Evidence/ledger → verified backups and external checkpoints | Restore and retention architecture exists; extend only for approved execution-store security/recovery |
| notifications/ntfy | Outbox → bounded alert | Phone delivery not certified; unattended-live prerequisite remains |
| `dashboard/` | Canonical read-only projections → private Terminal | No account-command authentication/approval service exists merely because UI exists |
| deploy/systemd/runbooks | Reviewed release → guarded deploy/verification | Preserve protected windows and other-application isolation; no production changes here |
| `tests/invariants`, Gate7/browser tests | Fixtures/code → safety evidence | Source no-execution invariant intentionally blocks auth/order code; future boundary needs an explicit reviewed replacement, not deletion |

No reason was established to replace SQLite, deploy Kubernetes/Kafka, or transplant an agent platform. A separate private **execution persistence domain** can be justified by different security and recovery needs without duplicating financial arithmetic or rewriting frozen shadow history.

## 5. Confirmed execution gaps

### 5.1 Intent and capability boundary

`execution_ticket.py` makes `execution_enabled=True` invalid and the final execution check fail. `test_no_execution_paths.py` rejects signing/order paths in research code. These are deliberate controls. Implementing a signer requires a narrowly approved executor package/process identity, protected import/egress boundaries and mutation-tested invariants. An environment variable must not turn any research module into a trader.

### 5.2 Durable identity and reservation

`reserve_simultaneous_obligations` expressly reserves nothing anywhere. It correctly sums full obligations and leaves unknown amounts unknown; extend that arithmetic with a transactional intent/reservation store. Persist before send. Keep business-intent identity stable across attempts; current timestamp-bearing ticket identity is not sufficient evidence of business-level retry deduplication.

### 5.3 Actual-account and partial-position semantics

`shadow_ledger.Position.quantity` and ticket quantity are integers; shadow entry kinds are account_opened/decision/fill/settlement. Its OPEN/SETTLED positions do not represent native fills, amendments, reductions, cash transfers or archived account history. Reuse proven arithmetic but introduce a versioned production-account projection; do not coerce fractional real positions into legacy objects.

`risk.py` reads a replayed shadow account, with settlement-based equity and net realized trailing losses. A new profile needs marked/unmarked exposure, cash effects, pending obligations and daily new-risk budgets. Preserve old profiles exactly. Do not call entry cost 'all remaining risk' for every action: holding a appreciated contract forgoes an executable liquidation value; reductions and flips require scenario-aware marginal risk.

### 5.4 Reconciliation and order outcome

No implemented account adapter means no current proof about balances, open orders, partial fills, manual Auto Sell, cancellations or restart state. Venue acknowledgment, cancellation status and cumulative executed quantity must coexist; a canceled remainder can still have filled quantity. Exactly-once local application is achievable with identifiers/constraints. Exactly-once remote execution is not established merely by naming `client_order_id`.

## 6. Current official Kalshi findings

All K sources were consulted 2026-10-07 through public documentation, not account API calls. `DOCUMENTED` is not account entitlement or deployment verification. Source list is in §13. Descriptions are deliberately concise; implementation must pin the current schemas.

| Topic | Verified documentation / consequence |
|---|---|
| Authentication K01–K03 | Ed25519 is now recommended; RSA-PSS remains supported. Select parsed key type, not PEM label. Sign timestamp+method+path excluding query. Use a maintained crypto library, never handwritten cryptography |
| Environments K04–K05 | Demo and production identities are separate. Allowlist matching REST/WS hosts and refuse cross-environment fallback. Mock funds only; demo availability and parity are not guaranteed |
| Native order shape K06 | Event V2 uses YES-oriented bid/ask and fixed-point dollar/count strings. IOC-only reduce_only; GTC requires own inventory protections. Do not carry obsolete v1 buy/sell assumptions into v2 |
| Cancel/amend K07–K08 | Cancel returns canceled quantity, not a complete order. Amend count is total filled+desired remainder. Preserve fill/cancel races and old/new order lineage |
| Account completeness K09–K11 | Default positions are unsettled; live and historical stores partition records. Reconcile both, every relevant subaccount, pagination, watermarks and moving boundaries. No single historical settlement-record equivalent is promised |
| Precision K12 | Direct and non-direct members have different balance precision; six-decimal trade-fee accounting includes rounding/accumulator effects. This does not establish NFL/NHL series multipliers |
| Budgets K13 | Token costs depend on endpoint and shard. Preserve capacity for cancel/reconcile; batching is not automatically cheaper. Tier metadata is account-specific, not assumed from another trader |
| Order groups K14 | Rolling contract-volume control is useful but not a portfolio-dollar or daily-loss cap; automatic reset would undermine its purpose |
| Book/game data K15–K17 | Snapshot/delta, source/envelope/receipt time and null/unsupported game mappings remain distinct. Existing in-play proposal needs scope/rights and measured quality |
| RFQ K18–K19 | Request visibility is not competitor-quote visibility. Confirmation, entered orders and actual fills differ. RFQ is not ordinary create-order with extra legs |
| Incentives K20–K24 | Resting-liquidity, volume, designated-provider and combo-component programs differ. Eligibility/terms/paid credits must be captured; rewards can change and cannot be treated as guaranteed tradable cash |
| Rights K25 | Public docs do not settle the owner's signed Developer Agreement or every retention/training right. No new acquisition authorized; retain the existing documented source-specific decisions |

A discovered beneficial alternative is an approved subaccount-restricted key with explicit child scopes instead of broad write/transfer authority. Whether the exact needed reads/channels are available to this account must be tested only after authorization. Do not request full access merely because a sample defaults to it.

## 7. External systems: eleven requested leads, plus independent failure evidence

All eleven READMEs were actually read. `SCREENED` means README-level evidence, not a reproduced program. Selected implementation findings are identified explicitly. Test counts and P&L below are author reports. No executable code was copied; no dependency installed.

| ID / system | What is actually supported by this inspection | Adopt/adapt versus reject |
|---|---|---|
| O01 spencerfletcher/market-maker | Public snapshot with private results, tuning and launch/recovery tooling withheld. Kalshi client/feed exists but dormant Kalshi maker removed. Selected `bot/core/maker_state.py` explicitly persists intent before send and distinguishes unknown from flat. MIT LICENSE inspected | Adapt durability and conservative state attribution conceptually; do not transplant cancellation of unattributed orders, dust thresholds, withheld production parameters or a Polymarket US engine as a ready Kalshi trader |
| O02 charlieyang1557/polymarket-arb | README reports four unsuccessful/neutral strategies and very small live-account net change. It reports 36 fills for one scope and 326 elsewhere; denominators are not reconciled here | Adapt strategy-retirement and fill/cancel accounting review priorities. Do not turn a small author case into proof no retail edge exists |
| O03 tfrmma/prediction-market-maker | Broad maker/hedging architecture. **Selected recovery code inspected:** Kalshi position read failure returns []; balances fall back to 0; startup cancels listed orders; money uses floats and best-effort fields | Reject these defaults. Adopt only the requirement to reconcile, implemented using UNKNOWN/full pagination/owned orders/exact arithmetic. Its time-to-expiry variance approximation is not a guarantee that unresolved binary risk vanishes |
| O04 zachdaube/kalshi-market-maker | README describes inventory skew, scanner, execution and configuration; A–S/market-mid approach, not independently proved alpha | Examine narrow client patterns only after code/license/version review; no transplantation of scanner weights, live configuration, network exposure or generic maker assumptions |
| O05 cryptuon/polybot | Typed proposals, approval/audit and paper defaults are described; venue/agent platform is broader than Market needs | Adapt exact intent approval concept; no agent framework or LLM-to-wallet authority |
| O06 jwt-bella/polymarket-maker-arb | README's full signing, queue tracking and backtesting remain roadmap items; fee/rebate claims are venue-specific | No drop-in adoption. A limit order is not automatically a maker fill; require post-only/actual liquidity flags |
| O07 ImMike/polymarket-arbitrage | Advertised 99.6%/$573 result explicitly comes from synthetic injected opportunities. Similar-text market matching is described | Reject synthetic returns as evidence and text similarity as payoff equivalence; retain only already-covered discovery/UI concepts |
| O08 kmizzi/karb | Describes multi-connection monitoring, timeout cancellation and binary bundle trading, plus a prohibited-for-Market geo-evasion setup | Reject evasion, guaranteed-arbitrage language, optional dashboard auth and blind cancellation assumptions; lifecycle lessons already covered |
| O09 HarrierOnChain/Polymarket | Venue wrapper points to a shared toolkit; sub-100ms and ten-live-strategy claims not reproduced; screenshot text contains replacement TODO | Do not treat broad coverage or timing claims as measured performance. No core adoption without actual code, license and benchmarks |
| O10 resided/polymarket-bot | Generic multi-engine scaffold and metrics; README documents paper mode default false | Reject live-by-default and generic feature claims as certification. No unique missing Market capability established |
| O11 Zeeshan-Chaudhry/PolyMarketAgent | Sportsbook/Polymarket comparison assistant with paper-mode frontend/backend | Mostly already covered. No evidence of authenticated Kalshi lifecycle or attainable net returns |
| O12 MeyerThorsten / Forezai Polybot | Original project page reports failed paper experiments and a foundation model not beating a simple baseline; results are paper, not independently reproduced. Page contains both negative overall findings and older positive-sounding strategy text | Adapt explicit retired-variant reporting and baseline comparison. Do not adopt fee/latency constants, resettable bankroll behavior or infer real fills |

### Selected reproducible content pins

These are Git blob SHAs returned by connected reads, not attestations that entire repositories were audited:

- O01 README `039b13b56aac381909405c546b88978e75f39a2e`; maker_state `9655ef7b856cf7987fec35de0e1c9dd5caf0583e`; LICENSE `209d2cedeb9bf8214ed4ac04c2d85969ad35b0b5`.
- O02 README `a59af8f862441b23baf8a8553a4267657c02e0d9`.
- O03 reconciliation `88d12fb42571c462eb78f5756f9fc34a99f9da94` (both halves inspected).
- O05 README `5b74ea3992b9feb8c45781e236fc64346fb20ecc`.
- O06 README `de65d3f2bf63cc02692a84c356929498be98d2e6`.
- O07 README `0c5ca4c5aada90e7c939d12e41633d0e48505380`.
- O08 README `ad5b302aa025643a8e52aa106b1e146d2834e875`.
- O09 README `91cdf5779ef5a00d134993cf521fc59f84d2356e`.
- O10 README `dad1a9bc1e13e076334e87246e5925fe1cc1a7e6`.
- O11 README `e2b608e0c98555a0fb726c5e0a4c0505a43bf43a`.

O04 and O12 remain source-reference rather than full pinned-code reviews. External CI, license history, issues and meaningful-commit histories were not exhaustively audited. This limits code-adoption decisions, not the independently designed safety requirements.

## 8. Professional firms, traders and research

**P01 Alcedine:** official site confirms technology/trading business; careers covers engineering, operations, research, risk and security. That supports a multidisciplinary operating comparison, not a verified profit figure or disclosed strategy.

**P02 VARRD:** its own site separates validation, operations, risk and capital; research product explicitly is not an execution system. Proprietary training and guardrail claims are marketing not independently evaluated. Lesson: validation plus operational exception handling; no substitute for our exact-account controller.

**P03 Galaxy:** June 2, 2026 issuer announcement describes institutional non-sports event trading and a $10m Arca transaction. This is size/hedging activity, not $10m profit or retail order-book capacity. Do not assign its bilateral economics to the owner.

**P04 Susquehanna:** official Predictions and hiring pages describe quantitative research, live judgment and technology, including specialized live sports. Desk-size/superlative/performance statements remain firm claims. Lesson: own models and reliable engineering compete together; retail's best chance is not assumed to be submillisecond parity.

**P05 DRW:** official trader posting describes a developing prediction-market desk and multiple strategy families. This supports competition and engineering relevance, not a published winning strategy.

**P06 Jane Street:** limited primary search surfaced educational/simulated prediction-market work, not a directly verified current Kalshi production strategy. Do not promote press mentions or alumni background into a firm-specific operating claim.

**POD-01 Even Steven:** supplied transcript supports self-reported evolution from taking toward RFQ, source-leadership changes, same-game dependence and an expensive misunderstood fallback. P&L, ROI denominator, speed claims and causes were not independently verified. Reuse #145's already-implemented state/latency/conditional-fill lessons instead of creating a new system.

### Academic evidence (not live strategy certification)

**A01 Bartlett & O'Hara:** the primary NBER conference listing verifies the paper and authors. Its indexed primary abstract describes 41.6m trades and heterogeneous adverse selection/behavioral surplus. SSRN abstract/PDF retrieval was blocked. The author's SSRN listing reports a later August revision; the complete latest tables/code were not recovered. Do not claim full-paper reproduction or derive deployable thresholds from the abstract.

**A02 Nam Anh Le, arXiv:2602.19520v2:** explicit v2 PDF and abstract inspected, including screenshot and limitations. V2 reports 353m trades/429k contracts, conditional calibration and substantial uncertainty under event clustering. A bare PDF route initially rendered older v1 content; explicit versioning resolved it. Descriptive calibration differences and large trade counts do not establish attainable after-cost profit. Use domain/horizon clustering and uncertainty as design lessons, not a new production signal.

**A03 H.-C. Yang, SSRN 6396698:** primary indexed abstract describes historical zero-fee Polymarket and dual-role profitability among skilled participants. Full paper retrieval blocked; version history includes revisions. Useful hypothesis: skill/selection rather than simply maker versus taker may matter. Historical zero-fee findings do not price today's member-specific fees.

The research is mixed: these academic leads describe economically meaningful heterogeneity, while small public bots report failures. Neither universal optimism nor universal futility is supported. Market must run its own appropriately costed, independent tests.

## 9. Strategy taxonomy and economically sensible ordering

All classifications are **recommendations**, not measured Market returns. Actual useful capital, net margin, fill rate and annual capacity remain UNKNOWN without qualified data. Existing approved collection is not permission for new feeds.

| Family | Mechanism / data | Cost, risk, frequency and small-bankroll fit | Disposition |
|---|---|---|---|
| Pregame NFL taking | Frozen sportsbook-vs-event hypothesis; existing paired data | Limited independent games; fees/timing/rules unresolved. Lowest additional research build | Continue current study, not live-qualified |
| Pregame NHL taking | Same broad mechanism, different rules and cadence | More scheduled games but separate sample; quota, fees and shootout semantics | Preserve data; separate slot/protocol later |
| In-play NFL/NHL | State/reference or exit-policy advantage | Fast data, changing state, gaps, sell depth and repeated costs; volatility alone not alpha | Source-quality pilot then one narrow family |
| Sports order-book making | Fair value and selective liquidity provision | Queue, adverse selection, inventory, fees; both-sided fills not guaranteed | After ordinary execution and fair-value evidence |
| Incentive-aware making | Trading economics plus explicit temporary rewards | Eligibility/competition/payment uncertainty; unfilled quotes still create obligations | Bounded research, no reward farming or wash trades |
| RFQ/combos | Joint pricing and request-selection skill | Private flow, full commitments, timing, correlation and collateral | Existing NARROW feasibility; later empirical scope |
| Weather taking | Physical forecasts versus contract probabilities | Known infrastructure; frozen long observation schedule; city dependence | Preserve EXP-001; new questions separately |
| Same-venue deterministic relationships | Payoff-complete bundles/thresholds | Exceptional settlements, fees and unfilled legs erase apparent certainty | Current EXP-003 pause respected |
| Cross-venue relationships | Truly identical payouts at different all-in cost | Prefunding/leg/custody/cancel risk; different US/International access | Defer until one-venue lifecycle complete |
| Macro releases / slower interpretation | Vintages/consensus/model versus market | Few events, revisions, professional latency; slower horizons preferable for study | Queued economics screen |
| Crypto exact-fixing/basis | Same underlying fixing and specified payout | Oracle differences, clocks, basis/jumps; public-bot failures caution | Bounded named windows, no every-tick firehose |
| SEC/earnings/related equity events | First-seen documents and slower interpretation | Market data rights, revisions, LLM look-ahead; eventual useful capacity | Retain #88; slot and data value first |
| Options replication/bounds | Matched payoff distribution or hedge cost | Risk-neutral != physical, discrete size, exercise/spreads/capital | Later specific study, not first bootstrap vehicle |
| Niche origination/news/rules | Specialized public information | Small capacity, rare events, unclear finality and provenance | Screen individually; never exploit prohibited information |
| Copy/flow/whale signals | A visible trader/order predicts later value | Hidden hedges, delayed subsets, survivorship, fee inequivalence | No simple copy-bot adoption |
| Generic technical/microstructure ML | Predicting short-horizon price movement | Leakage, selected fills, compute and many trials | No broad search before economic mechanism |

**First automation vehicle:** available demo ordinary event orders, synthetic signals, tiny mock quantity, known semantics. This is a software experiment and need not consume a strategy slot. **First alpha candidate:** preserve the existing NFL research while comparing future candidates on real economics. No winner is established. More assets are not required to finish the execution core.

Economic screening must keep turnover denominator, return on deployed/total capital, peak collateral, fees, funding, incentives and owner hours distinct. For any family annual contribution is a scenario over distinct episodes and attainable size; repeated snapshots are not new opportunities. A $2k-capacity niche may be useful for bootstrapping, but its return cannot be extrapolated to a $100k account.

## 10. Failure catalog and required defenses

| Failure | Evidence origin | Market action |
|---|---|---|
| Read failure looks flat/zero | O03 selected code | UNKNOWN typed result; no reconciliation certificate from missing pages/fields |
| Crash after send before local record | O01 design/code | Intent+reservation durable before egress; reconcile unknown attempts |
| Restart cancels manual orders | O01/O03 policies inappropriate to shared account | Attribute orders; no blanket cancel/flatten without exact mandate |
| Full-file and as-of evidence conflated | #153/#158 recorded R3a gaps | Full artifact hash plus admissible-prefix identity, coherent consumer cutoff |
| Synthetic returns marketed as performance | O07 README | Fixture/simulated/observed/live status in every report |
| Limit order assumed maker | O06 framing | Post-only and actual liquidity-role evidence; actual fee attribution |
| Taker edge loses during delay | K13/K15 and POD-01 | Latency-aware price bounds; no stale-target resubmission |
| Profitable quotes lose conditional on fills | O02/O12/A01–A03 | Own-fill markouts and complete residual wealth; actual versus counterfactual |
| Same-game independence | POD-01 and RFQ study | Explicit joint probabilities/model uncertainty, no naive product |
| Arbitrage label ignores one-leg exposure | O07/O08 | Full payoff proof plus orphan-leg/capital policy, not guaranteed execution |
| Client id treated as exactly-once guarantee | K06 docs do not provide complete retry theorem | Unique local business key + persisted attempt + external reconciliation |
| Cancel and fills race | K07/K08 | Orthogonal canceled remainder/cumulative fill accounting |
| Account history disappears from live endpoints | K09 | Paginated live+history, moving cutoff, dedup and repeat reconcile |
| Fees/precision/account type conflated | K12 | Decimal units and account-specific reconciliation fixtures |
| Rate cap exhausted prevents cancellation | K13 | Egress dispatcher with reserved operational headroom and shard-aware budgets |
| Incentives hide negative trading | K20–K24/O02 | Paid vs estimated rewards separate; subsidy-removal scenario |
| Late stop assumed guaranteed | K17 | Persisted disable blocks new risk; cancel/flatten availability explicit |
| Strategy or LLM bypasses control | Current invariant and O05 lesson | Isolated signer/executor, fixed commands, bounded approvals, no arbitrary request signing |
| Public repository leaks future credentials | Public repo boundary | Sanitized fixtures, private execution store/logs, history scan before credentials |
| Fees/rules/date guesses become authority | Repo rules | Versioned source status, no generic fallback to 'supported' |

## 11. Security verdict and architecture proposal

**Security certification: NOT COMPLETE.** The public tree/guard design was inspected, not all history or dependencies. No real signing key is claimed discovered; no claim that none exists anywhere is made. A local full-history scan and artifact/CI permission review are release prerequisites once a checkout is available. Secrets discovered later must be reported by type/path/history location only, never printed; revocation/rotation is owner-controlled and does not follow from deleting a file.

Proposed boundary: research and collectors produce immutable, typed strategy proposals; an isolated executor identity consumes allowed proposals, checks independent limits, commits intent/reservation, signs only an allowlisted venue operation, reconciles all responses, and publishes sanitized projections. The UI never loads a signing key. Demo and production use the same deterministic core but different allowlisted transports, stores and credentials. No arbitrary endpoint/body supplied by an LLM may reach a generic signer.

Keep `execution_ticket.py` the canonical lifecycle/reservation owner with well-named subordinate persistence/transport modules. Keep `risk.py`, `fee_schedules.py`, `opportunity.py` and shared arithmetic as their owners. Choose exact new package paths in an ADR after checking the complete import graph. Do not rewrite frozen EXP-001 ledger data to host real trading.

A transaction commits business intent, worst-case reservation and pending egress before external I/O. Responses are recorded idempotently by stable provider identifiers. Recovery compares local attempts to paginated externally confirmed state; missing reads remain pending. Storage failure before send forbids sending. Failure after send is an unknown exposure, not a new order attempt.

Persistent arming should default off on fresh install and controlled restart until reconciliation. An approval binds account, environment, strategy/version, instrument, action, quantity, price bound, TIF, fees, expiry, risk configuration and intent digest. Changes require revalidation and, where material, new approval. A human click is not permission to accept a worse price later.

## 12. Readiness verdict and exact remaining authority

Current verdict: **NOT KALSHI_AUTOMATION_READY**. Offline evidence/research is substantial; account transport, durable obligations, actual lifecycle, demo proof and production account reconciliation are missing or unverified.

Use separate milestones:
1. OFFLINE_EXECUTION_CORE_COMPLETE: deterministic end-to-end fixture/fault tests and security boundary.
2. DEMO_LIFECYCLE_VERIFIED: authorized mock environment receipts, restart and account reconciliation; explicitly list unsupported/unobserved branches.
3. PRODUCTION_ACCOUNT_SHADOW_VERIFIED: authorized read-only account, complete reconciliation and real data quality; no writes.
4. KALSHI_AUTOMATION_READY: the declared ordinary-event capability profile has its required evidence, owner access prerequisites and no unresolved safety blockers; production write remains disabled.
5. LIVE_AUTHORIZED and UNATTENDED_LIVE_AUTHORIZED: separate decisions with a qualified strategy and capital limits.

No status is awarded because the owner asked for it. A fake signal can certify a demo lifecycle, not strategy value. Demo limitations require fault-injected tests plus an explicit residual, not an 'all production cases proved' statement.

Genuine owner boundaries: approval of the new isolated runtime scope; merge decisions still reserved by prior PRs; exact demo setup/test authority; production account-read scope; terms/rights resolution; optional data costs; real bankroll and live pilot; later unattended automation. Technical design and test implementation are not questions the owner should invent.

## 13. Source register

Sources checked 2026-10-07; only O01/O03 selected code is claimed deeply traced in this pass. No code/content redistribution is implied by access. Linked documentation facts remain subject to effective versions and account verification.

### Kalshi official
K01 https://docs.kalshi.com/llms.txt — current documentation index; discovery, not entitlement.
K02 https://docs.kalshi.com/getting_started/api_keys — Ed25519/RSA and signing.
K03 https://docs.kalshi.com/api-reference/api-keys/generate-api-key — defaults/scopes/subaccount limits; no key generated.
K04 https://docs.kalshi.com/getting_started/api_environments — production/demo REST/WS hosts.
K05 https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account — mock account/funds and availability caveat.
K06 https://docs.kalshi.com/api-reference/orders/create-order-v2 — event order shape.
K07 https://docs.kalshi.com/api-reference/orders/cancel-order-v2 — cancellation response and routing.
K08 https://docs.kalshi.com/api-reference/orders/amend-order-v2 — total-count amend semantics.
K09 https://docs.kalshi.com/getting_started/historical_data — live/archive completeness.
K10 https://docs.kalshi.com/api-reference/portfolio/get-balance — scope/units/account dimensions; no account accessed.
K11 https://docs.kalshi.com/api-reference/exchange/get-user-data-timestamp — approximate update watermark, located via official index; detailed implementation verification remains.
K12 https://docs.kalshi.com/getting_started/fee_rounding — precision and fee accumulator.
K13 https://docs.kalshi.com/getting_started/rate_limits — tokens, endpoint costs and shard behavior.
K14 https://docs.kalshi.com/getting_started/order_groups — rolling-volume control.
K15 https://docs.kalshi.com/getting_started/quick_start_websockets — auth and channels; prior in-repo capture rechecked at predecessor intake, current exact payloads need conformance.
K16 https://docs.kalshi.com/api-reference/live-data/get-game-stats — source candidate and null states; coverage not tested.
K17 https://docs.kalshi.com/getting_started/maintenance_and_pauses — pause behavior; operational docs from prior audit, revalidate at build.
K18 https://docs.kalshi.com/getting_started/rfqs — lifecycle; detailed current in-repo feasibility reused.
K19 https://docs.kalshi.com/websockets/communications — visibility; detailed in-repo feasibility reused.
K20 https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program — liquidity rewards.
K21 https://help.kalshi.com/en/articles/13823850-what-is-the-kalshi-volume-incentive-program — volume rewards.
K22 https://help.kalshi.com/en/articles/13823819-how-to-become-a-market-maker-on-kalshi — conditional DMM benefits.
K23 https://help.kalshi.com/en/articles/15410219-liquidity-provider-program — contracted provider program.
K24 https://help.kalshi.com/en/articles/17184676-sports-prop-combo-market-component-legs-liquidity-incentive-program — component incentives.
K25 Signed-in Developer Agreement and governing account terms — NOT ACCESSED; retain existing decision packet rather than infer permission.

### Public systems
O01 https://github.com/spencerfletcher/market-maker
O02 https://github.com/charlieyang1557/polymarket-arb
O03 https://github.com/tfrmma/prediction-market-maker
O04 https://github.com/zachdaube/kalshi-market-maker
O05 https://github.com/cryptuon/polybot
O06 https://github.com/jwt-bella/polymarket-maker-arb
O07 https://github.com/ImMike/polymarket-arbitrage
O08 https://github.com/kmizzi/karb
O09 https://github.com/HarrierOnChain/Polymarket
O10 https://github.com/resided/polymarket-bot
O11 https://github.com/Zeeshan-Chaudhry/PolyMarketAgent
O12 https://forezai.com/polybot.html — author's project/results presentation, not a reproduction.

### Firms and academic leads
P01 https://alcedine.com/ and https://alcedine.com/careers/
P02 https://www.varrd.com/
P03 https://investor.galaxy.com/news-releases/news-release-details/galaxy-launches-institutional-otc-prediction-markets-trading
P04 https://sig.com/predictions/ ; https://careers.sig.com/jobs/10034 ; https://careers.sig.com/jobs/10347
P05 https://www.drw.com/work-at-drw/listings/prediction-markets-trader-3332253
P06 https://www.janestreet.com/join-jane-street/closed-internship/quantitative-trader-may-august-hkg/ — education evidence only.
A01 https://www.nber.org/conferences/si-2026-financial-market-structure ; https://conference.nber.org/agenda/simple_printable?conf_id=SI26HPC ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6615739 — full SSRN text blocked; conference/primary-indexed abstract available.
A02 https://arxiv.org/abs/2602.19520v2 and https://arxiv.org/pdf/2602.19520v2 — explicit v2, abstract/limitations and page images inspected; no reproduction.
A03 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6396698 — indexed abstract available; full retrieval blocked.

## 14. Final disposition

ADAPT: durable-before-send, explicit unknowns, exact and versioned units, complete history, isolated permissions, own-fill evidence, conditional incentives and scope-specific readiness.
ALREADY_HAVE: research registry, economics, state/latency/RFQ fixtures, baseline sports collection, immutable shadow ledger, private Terminal.
DEFER: empirical maker/RFQ/joint pricing, broad domains, general agents/ML, institutional privileges and external capital.
REJECT: geo evasion, live-by-default, unknown-as-flat, blanket unowned cancellation, synthetic profit claims, guaranteed-maker/arb narratives and unsupported copied fees.
UNRESOLVED: private strategies, full external histories/tests, full security certification, current production/account state, signed terms and venue-observed execution.

The report is useful precisely because it does not turn documented capabilities or public code into fake operational proof. The next engineering campaign is large enough to finish the ordinary-event lifecycle, but each unobserved capability must remain unobserved until verified.
