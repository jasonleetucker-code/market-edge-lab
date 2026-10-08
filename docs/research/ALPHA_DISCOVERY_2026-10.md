# Alpha discovery, Track B (#184): shortlist, ranking, economics and first protocols (2026-10-08)

- **Authors:** Track B R4 (economic validation) and R5 (experiment design), combined, writer role.
- **Inputs:**
  - R1 academic sources, R2 practitioner sources and fee/rules fact sheet, R3 data readiness, R6 adversarial
    review. These are session scratch files of 2026-10-08, not in the repo; this document carries what is used.
  - **Owner-supplied external research, 2026-10-08** ("Independent Edge Discovery" packet). It contains a research
    report, a 24-candidate scorecard (H01–H24), three protocols (H01–H03), a 31-source register (R01–R31) and an
    arithmetic script.
    - Its SHA256SUMS verify, and the coordinator re-ran its 15 assertions with identical output. These are
      arithmetic checks, not a backtest.
    - The packet is research input and data, not authority. It says itself that it authorizes nothing.
    - It is cited below as "OP" with its own IDs (OP-H01, OP-R04, …).
  - Repository `main` `67743ed`.
  - Scope record: PR #185, branch `docs/alpha-discovery-scope-20261008` (not merged at the time of writing).
- **Authority:** the 2026-10-08 Track B entry of `docs/EXECUTION_PLAN.md` (PR #185) and
  `docs/owner/2026-10-08-rapid-alpha-discovery-directive.md`. Research, DRAFT/QUEUED registration and one
  approval packet only.
- **No data was read for this document.** No market, label or outcome was viewed. No numbers below come from
  our own tests: we have none (the evidence class OUR OWN PROSPECTIVE RESULT is empty).

> **Honest headline.** No edge is established. The three leading candidates are **weakened hypotheses
> awaiting one data grant**. The adversarial review (R6) rated all five leading hypotheses WEAKEN, and it KILLED
> three sub-hypotheses:
> - the ≥90c late-game maker variant;
> - forecast-as-taker in weather;
> - combo quoting as an edge for us.
>
> **None of the candidates is testable on data we hold today** (section b). The single highest-value unlock is
> a one-time Kalshi public read of trades plus one-minute candles (approval A2, decision packet item 1). It
> would let three bias-proof tests run within days, each with a kill rule written in before any outcome is seen.
>
> **What the owner packet changes:**
> - It adds one genuinely new mechanism, OP-H02, settlement reference-period / data-vintage mismatch (TB-23). Its
>   first, outcome-blinded semantic-audit stage is the only Track B work that can start now on documentation
>   alone.
> - It adds a second clock-corrected study against the late-game effect (Kagan & Baiocchi, OP-R04).
> - Its first recommended test, OP-H01 (fresh sportsbook consensus vs the Kalshi ask), is **family A's mechanism**.
>   That is EXP-002's own question and is excluded from Track B, so it goes to the owner as a packet choice and
>   is not a Track B candidate.
> - Its "Finding 1" (NFL fee row) **does not resolve the KXNFLGAME fee blocker** (section e, fee facts).

---

## (a) Executive answer: three strategies to investigate immediately

Nothing here is authorized beyond research; each needs data approval A2 first.

| Rank | Candidate | Registry | Why investigate it now | What would kill it |
|---|---|---|---|---|
| 1 | **TB-05: taker favourite-side FLB, short-dated Kalshi non-sports**, at the ask, event-equal weight | EXP-005, family `TB_FLB`, DRAFT/QUEUED | The favourite-longshot bias on Kalshi has independent support (Whelan, Becker), and a taker strategy is the only kind a public tape can score honestly at quotes. It has the largest sample and the cleanest point-in-time design. | Event-clustered 95% upper bound ≤ 0; positive only at trade weight; or decayed after 2025-07 |
| 2 | **TB-01: late-game favourite underpricing, Kalshi NBA/MLB**, scored at the ask with a clock known before the game | EXP-004, family `TB_TTE`, DRAFT/QUEUED | Fastest decisive test, and high turnover suits a $100 illustration. The published effect is large (γ 1.27–1.31 in the final 10 minutes). Evidence against now dominates, though: R6 explains it as look-ahead, overtime selection and sweep prints, and Kagan & Baiocchi (OP-R04) find better calibration once the clock is corrected. It stays in the top three because the same A2 read settles it in days, at almost no extra cost. | Game-clustered 95% upper bound ≤ 0 at the ask; or the effect is present under realized-close bucketing and absent under the scheduled-start clock |
| 3 | **TB-03: maker favourite-side premium, Kalshi non-sports**, as a two-sided bound | EXP-006, family `TB_FLB` | It has the largest published gross effect and the most mechanism support (makers win on Kalshi and Polymarket). It is also the hypothesis most likely to be mistaken for an edge when it is an incumbents' identity, so the bound test is cheap insurance. | Optimistic bound (all incumbent maker fills, net of maker fee) has a 95% upper bound ≤ 0 |

**Why these three, and not others.**
- One grant (A2) serves all three, and the existing harness lane covers most of the evaluation code.
- Each has a falsification rule that cannot be passed by the known biases.
- TB-01 and TB-05 are scored at quotes, never at trade prints.
- TB-03 is honest about the fact that a tape cannot show our fills.
- Weather tails (TB-09) and determined outcomes (TB-10) are the runners-up:
  - TB-09 has no usable sign until a quote study fixes it per horizon and side;
  - TB-10 needs a second grant (IEM), and it carries a tail-loss profile in which one settlement mismatch erases
    about 49 wins.
- **OP-H02, reference-period / data-vintage mismatch (TB-23)**, scores 28, below the top five. It is:
  - low-frequency: weekly releases, clustered by release;
  - in need of two grants: A2 quotes plus a vintage archive.

  Its first stage, though, is a **documentation-only, outcome-blinded semantic audit** that can start now. That
  makes it the best use of time while A2 is pending. It is not registered as an experiment.

---

## (b) Research readiness (condensed from R3)

**Held data and what Track B may do with it** (VPS and off-host inventory, 2026-10-08):

| Dataset | Track B use | Why |
|---|---|---|
| KXHIGHNY books, observations, PFM, CLI, settlements, EXP-001 dataset (D1–D3, D9, D11) | **Feature-only** for D1 decision books; **NO** otherwise | EXP-001 protected; EXP-003 prohibited scope; `nws_pfm:`, `nws_cli:`, `kalshi_settlement:` are prohibited inputs |
| KXNFLGAME books, Odds API NFL, Polymarket US NFL books (D4–D6) | **Feature-only, single capture**, logged in EXP-002's log | `sports:nfl:moneyline` is EXP-002's protected scope until it freezes; NFL fees FEE_UNSUPPORTED |
| KXNHLGAME books and settlements, Odds NHL (D7–D8) | **Feature-only** | Track B excludes NHL outcomes (NHL is DEVELOPMENT_ONLY); about 60 games; fees unsupported; shootout rules unresolved |
| Shadow ledger (D10), EXP-002 tie evidence (D12) | **NO** | prohibited input / consumed labels |
| Novig samples (D13) | fixture-only | full files not held (A1) |
| Wallet data, in-play journals (D16, D17) | none | 0 real rows |

**Access facts.**
- The live evidence DB is unreadable as `dynasty` (mode 700), so its row counts are UNKNOWN.
- The only off-host copy (2026-09-26) predates the sports captures. The weekly O1 pull is about 6 days overdue.
- **No Kalshi trade prints or candlesticks are collected anywhere.**

**Fee status.**

| Series | Status |
|---|---|
| KXHIGHNY | CONSERVATIVE_BOUND until 2026-10-23 |
| KXNFLGAME, KXNHLGAME | FEE_UNSUPPORTED |
| KXMLBGAME (listed non-standard) and other listed sports | unsupported |
| KXNBAGAME (unlisted) | general schedule, UNVERIFIED |
| KXMVE* (combos) | unsupported by prefix |
| Polymarket US | claim basis NONE |

**Testable now: none of the leading candidates.** Every candidate that needs outcomes lacks outcome-labelled
prices in a permitted scope:
- TTE calibration, favourite–longshot, maker/taker, parlay, weather and wallet: no Kalshi trade prints or candles
  exist for NBA/MLB or non-sports series;
- the sports data we hold is NFL (EXP-002) or NHL (excluded);
- the weather data is KXHIGHNY (EXP-001).

What can run now is **feature-only**: depth, spreads, $100 fill-cost ladders and no-trade attrition on held books.
That needs A0 for a fresh off-host copy, and it gives no profit evidence.

**Harness.**
- **Reused:** `research_evidence`, `research_economics` (`cluster_bootstrap_mean`, `markouts`, `capacity_ladder`),
  `fee_schedules`, `opportunity`, `experiments`.
- **Planned in the separate `research/tb-harness` lane (not merged; referenced, not duplicated):**
  `research_diagnostics.calibration_report`, `evaluate_entries`, `bankroll_ladder`, `depth_report` and
  `protocol_guard_problems`, plus a maker-fee path in `fee_schedules` and a Kalshi market-activity parser.
- **Still missing:** a Kalshi trades/candlesticks adapter (only needed after A2).

**Approvals named by R3:**

| ID | Approval |
|---|---|
| A0 | Research use of a fresh O1 pull |
| A1 | Novig daily files |
| A2 | One-time Kalshi public read of settled markets, trades and candles |
| A3 | Polymarket data routes |
| A4 | A recurring in-play source |
| A5 | News |
| A6 | Family slot |
| A7 | Kalshi fee message |

The decision packet orders them by expected information per unit of risk and cost.

---

## (c) Comprehensive shortlist (34 hypotheses)

**Sources merged and deduplicated:**
- R1 H1–H11;
- R2 H-R2-01..14;
- R6 verdicts;
- the owner packet's OP-H01..H24 (mapping table below);
- our own additions: TB-05, TB-07, TB-18, TB-19, TB-20 and the excluded NHL slice.

The 34 entries are related, not independent discoveries. OP-H10, H17 and H20 are quality or execution
improvements, not standalone profit sources (the packet says so itself).

**Owner packet → shortlist mapping:**

| OP | Packet candidate | Shortlist |
|---|---|---|
| H01 | Fresh sportsbook consensus vs Kalshi ask | **TB-X2 (excluded: family A, EXP-002)**; owner choice in the packet |
| H02 | Settlement reference-period / announcement mismatch | **TB-23 (new)** |
| H03 | Forecast-to-position conversion | **TB-24 (new; decision layer, not standalone)** |
| H04 | Better de-vig / odds-conversion challenger | **TB-X6 (excluded: family A benchmark)** |
| H05 | Weather tail / distribution residuals | TB-09 |
| H06 | Late-game bias after actual-clock correction | TB-01 |
| H07 | Asian-handicap information for soccer | **TB-X7 (excluded: family A; Football-Data rights)** |
| H08 | Already-observed cumulative bounds | TB-10 |
| H09 | Selective passive execution | TB-03 |
| H10 | Cheapest exact-payoff representation | TB-X1 (same-venue payoff relation, family B) |
| H11 | Complete-set underround | TB-X1 |
| H12 | Nested threshold violation | TB-X1 |
| H13 | Wallet skill persistence | TB-16 |
| H14 | Delayed wallet information | TB-16 |
| H15 | Conditional source leadership | TB-13 (non-sportsbook sources only) |
| H16 | Official injury/lineup lag | TB-15 |
| H17 | Entity-correct retrieval / abstention filter | **TB-25 (new; overlay, #181 lane)** |
| H18 | First-release vs revision / unit convention | TB-23 (merged with H02) |
| H19 | Opposite side of combos | TB-06 |
| H20 | Ground-truth aggressor / toxicity filter | TB-17 (overlay) |
| H21 | Maker incentives | TB-08 |
| H22 | Liquidity dislocation / cancellation recovery | **TB-26 (new)** |
| H23 | Public attention / buzz reversal | **TB-27 (new)** |
| H24 | Cross-venue equivalent-payoff arbitrage | TB-14 |

**Evidence class** uses the owner's five classes, with R6's corrections applied:
- Kalshi maker>taker is downgraded to a "replicated descriptive result; not a strategy return" (R6 §7 #14);
- Roosevelt (A24) and SmartStake (A21) are downgraded to UNVERIFIED.

The **R6** line gives the adversarial verdict where one exists.

**Common facts (not repeated per candidate).**
- **Fees.** Kalshi taker round-up(M·0.07·C·P(1−P)), maker round-up(M·0.0175·C·P(1−P)) with M default 0
  (schedule effective 2026-07-07).
- **Rounding.** The owner's account is OWNER_ATTESTED direct, so rounding is to $0.0001 and negligible.
- **Exclusions.** No candidate may touch KXHIGHNY labels, NFL moneyline outcomes or NHL outcomes, family A's
  mechanism on any sport, or family B's mechanism on any series.
- **Cost and account.** "Ongoing cost" is in cash and owner hours. No candidate is authorized to place an order
  or use an account.

### Scored candidates

**TB-01 — Late-game favourite underpricing, PIT clock (NBA, MLB)** · EXP-004 · merges R1 H1, R2 H-R2-01 (minus the killed ≥90c maker variant), the non-sportsbook part of R2 H-R2-14

- **Market:** Kalshi KXNBAGAME, KXMLBGAME game winners. NFL and NHL are excluded.
- **Direction / order type:** buy the favourite (60–90c) as a taker at the one-minute ask, once per game, late
  by minutes since scheduled start.
- **Mechanism:** late "hope" demand for the losing side, and maker withdrawal.
- **Why it might exist:** retail late-game flow; thin late books.
- **Why competitors might not eliminate it:** a few cents per game, fast books, small size.
- **Evidence for:**
  - Moshrefi 2026 (γ 1.27–1.31 in the final 10 min; trade prices, no SEs);
  - Page 2012 (losing teams overpriced late on Intrade).
- **Evidence against:**
  - R6: realized-close τ look-ahead plus overtime selection predicts NHL 4.56 > MLB 2.05 > NBA 1.62;
  - sweep prints after decisive plays;
  - trade-count weighting;
  - Le 2026: sports 0–1 h slope 1.10, "close to calibrated" at 0–48 h;
  - Croxson & Reade: in-play prices update fully;
  - N is about 1,400 games, not 23M trades, and both team markets were pooled;
  - **Kagan & Baiocchi** (Kalshi-hosted working paper, August 2026, OP-R04): using actual game-end timing, they
    find better calibration once the clock is corrected. It is exchange-hosted, uses private timing data and
    covers a different sample, so it is not a clean independent refutation (the packet's own caveat). It still
    supports R6.
- **Data / source / permissions:** Kalshi trades plus one-minute candles plus settled markets (A2; DATA_RIGHTS
  UNRESOLVED). Scheduled start comes from pre-game metadata. Becker's tape covers prints only.
- **Contract / rules:** game-winner rules for postponement and suspension are not captured for NBA/MLB.
- **Fee verification:** the repo's extract of the July 7 PDF (`experiments/EXP-001-…/fee_verification/pdf_nonstandard_series.json`)
  lists KXMLBGAME "Professional Baseball Game" maker 1 / taker 1, the same row form as KXNFLGAME. KXNBAGAME is not
  listed, which would mean the general schedule (taker M 1, maker M 0).
  - That conflicts with the secondary report that NBA game markets have carried maker fees since 2025.
  - Both series stay UNVERIFIED, for the same mapping, currency, override and maker-start gaps as KXNFLGAME
    (Q7 extension, packet item 3).
- **Execution:** taker at the ask; one contract (candles have no size).
- **Small bankroll:** good per trade ($0.60–$0.90 per contract), but dollars are tiny at one contract (section f).
- **Test duration:** about 2–4 days after A2.
- **Sample:** NBA plus MLB about 3,660 regular-season games a year. The qualifying share is UNKNOWN.
- **Complexity:** low (planned harness plus an adapter).
- **Ongoing cost:** $0, no recurring collection.
- **Capital lockup:** minutes to hours, plus a settlement delay that is UNKNOWN.
- **Failure modes:** the artefact; fills only in sweep minutes; fee multiplier ≠ 1; order delay on live sports
  (UNVERIFIED).
- **Falsification:** see EXP-004 (KILL, ARTEFACT and UNINFORMATIVE rules).
- **Evidence class:** PLAUSIBLE HYPOTHESIS; evidence against now dominates. **R6:** WEAKEN (taker, game-state
  version); the ≥90c maker variant is KILL. **OP:** H06, ranked 6th by the packet with persistence 3/10.

**TB-02 — Pregame sports calibration (NBA, MLB)** · merges R1 H2

- **Market:** Kalshi NBA/MLB game winners, more than 4 h before start.
- **Direction / order type:** taker at the ask on the side the pregame U-shape favours. The **direction is not
  stated** in Moshrefi, so it must be preregistered per band.
- **Mechanism:** pregame probability weighting.
- **Why it might exist:** retail pregame longshot demand.
- **Why competitors might not eliminate it:** they would. Pregame prices are set by sportsbook-linked makers
  (but no sportsbook data is used here: that is family A).
- **Evidence for:** Moshrefi pregame U-shape; Le (sports slope 1.74 beyond 1 month).
- **Evidence against:** Le: 0–48 h near-calibrated; Cardozo: no FLB in Polymarket sports.
- **Data:** as TB-01 (A2).
- **Rules:** as TB-01.
- **Fees:** as TB-01.
- **Execution:** taker at the ask.
- **Small bankroll:** good.
- **Duration:** days after A2.
- **Sample:** thousands of games.
- **Complexity:** low.
- **Cost:** $0.
- **Lockup:** hours to a day.
- **Failure modes:** no sign; family-A adjacency (must never use book odds).
- **Falsification:** game-clustered calibration slope CI includes 1 at the ask, or net ≤ 0.
- **Class:** PLAUSIBLE HYPOTHESIS. **R6:** not reviewed.

**TB-03 — Maker favourite-side premium after maker fees, non-sports** · EXP-006 · merges R1 H3, R2 H-R2-02

- **Market:** Kalshi non-sports categories, 70–95c.
- **Direction / order type:** resting bids on the favourite (maker).
- **Mechanism:** takers buy longshots, and makers on the other side buy the favourite.
- **Why it might exist:** takers pay for immediacy and lottery exposure.
- **Why competitors might not eliminate it:** small markets, variance, capital (Whelan §6).
- **Evidence for:**
  - Becker: makers +1.12% gross; category maker returns up to about +3.6%. The "+7%" is the **gap** (R6 §7
    #6).
  - Whelan: makers buying ≥50c +2.6% post-commission, 2021–Apr 2025.
  - Akey: Polymarket winners are makers.
- **Evidence against:**
  - The maker gain is the mirror of the taker loss among incumbents.
  - Takers won until 2024 Q2.
  - Whelan's maker significance is "generally not replicated" by day.
  - The queue effect is about one tick, which is at least the gross premium.
  - The affiliated Kalshi Trading was "not profitable" in sports (A25).
  - Sports maker fees have existed since 2025.
- **Data:** A2 (trades with taker side plus candles), post-2025-07.
- **Rules:** per market; entertainment and mentions are rule-sensitive.
- **Fee verification:** maker fee per series `fee_type` history. **Correction:** the 2026-08-20 changelog is an
  NFL-combo exemption, not a start date.
- **Execution:** maker; not attainable-testable retrospectively. The forward virtual maker needs a collection
  grant.
- **Small bankroll:** feasible mechanically; expected dollars small.
- **Duration:** days for the bound; weeks for a forward study.
- **Sample:** thousands of events (UNKNOWN until counted).
- **Complexity:** medium.
- **Cost:** $0 retrospective; a forward study is recurring collection.
- **Lockup:** hours to weeks by category.
- **Failure modes:** adverse selection; queue; the regime change.
- **Falsification:** optimistic-bound KILL (EXP-006).
- **Class:** replicated *descriptive* result, not a strategy return; for us a PLAUSIBLE HYPOTHESIS. **R6:**
  WEAKEN (sports near-KILL, excluded).

**TB-04 — Affirmative-bias fade: high-price NO on cheap YES (entertainment, mentions, world)** · R1 H4

- **Market:** Kalshi entertainment, media, world-event and mentions markets.
- **Direction / order type:** buy NO at 90–98c (maker bid; a taker pays a tick that is about 1% of outlay).
- **Mechanism:** affirmative YES overpricing (Becker: NO beats YES at 69/99 price levels; at 1c YES EV −41% vs
  NO +23%).
- **Why it might exist:** lottery preference.
- **Why competitors might not eliminate it:** tail risk deters capital; there are many tiny markets.
- **Evidence for:** Becker; Whelan.
- **Evidence against:**
  - Cardozo: event-equal weight reverses the FLB (+4.09% longshots).
  - At 99c the gross edge is about +0.41%, below one tick (R6).
  - One loss at 95c costs 19 wins.
  - Selling every longshot of an exclusive event is EXP-003's mechanism (excluded).
- **Data:** A2 (or Novig A1 for the mechanism on another venue).
- **Rules:** resolution-sensitive.
- **Fees:** per series.
- **Execution:** maker only (deci-cent ticks).
- **Small bankroll:** poor per day (long lockups).
- **Duration:** days.
- **Sample:** hundreds of events (UNKNOWN).
- **Complexity:** low.
- **Cost:** $0.
- **Lockup:** weeks to months.
- **Failure modes:** a tail event; composition; rule disputes.
- **Falsification:** event-weighted maker-bound return ≤ fee (R6 kill).
- **Class:** PLAUSIBLE HYPOTHESIS. **R6:** WEAKEN.
- **Note:** a single-market variant is folded into EXP-005/006 secondary endpoints (YES vs NO side).

**TB-05 — Taker favourite-side FLB, short-dated non-sports** · EXP-005 · own, from R1 S8

- **Market:** Kalshi non-sports binaries closing within 24 h / 6 h / 1 h.
- **Direction / order type:** taker at the ask on the side quoted at 70–95c, once per event.
- **Mechanism:** longshot overpricing makes favourites cheap.
- **Why it might exist:** taker lottery demand.
- **Why competitors might not eliminate it:** small, high-variance, capital-heavy.
- **Evidence for:** Whelan: >70c significantly positive post-taker-fee at trade prices to Apr 2025; Becker: 95c
  contracts win 95.83%.
- **Evidence against:** Whelan: 2025 slope 0.021 vs 0.048 in 2024; Cardozo: event-weight reversal; Becker's effect
  is YES-specific; near 99c the edge is less than one tick.
- **Data:** A2 for non-sports series.
- **Rules:** per market (economic markets cease trading before the release, P18).
- **Fees:** per-series multiplier read.
- **Execution:** taker at the ask, one contract.
- **Small bankroll:** good.
- **Duration:** days.
- **Sample:** thousands of events (UNKNOWN).
- **Complexity:** low.
- **Cost:** $0.
- **Lockup:** ≤1 day plus settlement.
- **Failure modes:** decay; composition; tick; tail losses.
- **Falsification:** EXP-005 KILL, ARTEFACT and DECAYED rules.
- **Class:** PLAUSIBLE HYPOTHESIS (built on a REPLICATED descriptive FLB). **R6:** WEAKEN (as H5).

**TB-08 — LIP-subsidized passive liquidity** · R1 H6, R2 H-R2-10

- **Market:** Kalshi markets with LIP periods.
- **Direction / order type:** two-sided post-only within Target Size.
- **Mechanism:** reward plus spread exceeds adverse selection.
- **Why it might exist:** Kalshi pays for depth; MM-agreement members are excluded.
- **Why competitors might not eliminate it:** they compete it to the marginal risk cost.
- **Evidence for:** program text (P7, P8, P15).
- **Evidence against:**
  - $100 covers about one 100-lot two-sided quote near 50c;
  - pro-rata dust;
  - rewards paid after the period;
  - terms change (end 2027-01-01);
  - adverse fills cost the spread.
- **Data:** LIP parameters plus books (a new collection grant).
- **Rules:** LIP terms (CFTC 2026-07-15).
- **Fees:** maker fee on fills.
- **Execution:** live resting orders: **not authorized**; offline estimate only.
- **Small bankroll:** poor.
- **Duration:** weeks.
- **Sample:** markets × days.
- **Complexity:** high.
- **Cost:** recurring collection.
- **Lockup:** continuous resting collateral.
- **Failure modes:** dilution; termination.
- **Falsification:** offline reward share × pool + spread − adverse drift ≤ 0 at $100.
- **Class:** PLAUSIBLE HYPOTHESIS. **R6:** WEAKEN.

**TB-09 — Short-horizon weather tail calibration, non-NY** · R1 H7 (non-NY), R2 H-R2-03

- **Market:** Kalshi KXHIGH*/KXLOW* other than KXHIGHNY; rain.
- **Direction / order type:** **unknown until preregistered per horizon and side.**
- **Mechanism:** Le's slope is <1 within 48 h (too extreme) and 1.20–1.37 beyond 2 days (compressed).
- **Why it might exist:** over-reaction to forecasts; lottery tails.
- **Why competitors might not eliminate it:** many small markets.
- **Evidence for:** Le; Whelan's weather FLB (horizon-pooled).
- **Evidence against:**
  - No usable sign (R6 §3.1).
  - The intercept matters for bracket families (YES base rate about 1/6).
  - Tails at 1–5c, where a tick is 20–100% of price.
  - Becker's maker gap is not a calibration sign (R6 §7 #7).
- **Data:** A2 for non-NY weather series.
- **Rules:** per series (TWC vs NWS CLI conflict; settlement-source change 2026-08-14).
- **Fees:** per series.
- **Execution:** maker only (taker dead).
- **Small bankroll:** good.
- **Duration:** days.
- **Sample:** thousands of city-days, correlated by date × region.
- **Complexity:** medium.
- **Cost:** $0.
- **Lockup:** <2 days.
- **Failure modes:** regime change; station bias; sign error.
- **Falsification:** R6 kill: no <48 h bucket has a b CI excluding 1 at quotes, or the implied side ≤ 0 after the
  spread.
- **Class:** PLAUSIBLE HYPOTHESIS. **R6:** WEAKEN. Forecast-as-taker is KILL (section i).

**TB-10 — Determined-outcome sweep before last trading time (non-NY temperature, rain)** · R2 H-R2-04

- **Market:** "above X" thresholds after the observed max passes X; RAINNYCM-type rain.
- **Direction / order type:** buy the determined side at ≤99c.
- **Mechanism:** time value of capital; settlement-source risk premium.
- **Why it might exist:** locked capital; QC risk.
- **Why competitors might not eliminate it:** they do. It is the most obvious bot strategy.
- **Evidence for:** rule text only (P19, P11).
- **Evidence against:**
  - Le's 0–1 h b = 0.69 says near-certain prices are too extreme.
  - NY settlement matched the CLI 739/739, so the risk is public and priced.
  - Bracket containing the max is not determined until the climate day ends.
- **Data:** IEM METAR plus CLI (source grant) and A2 candles.
- **Rules:** per series last-trading time.
- **Fees:** taker 0.137c at 98c.
- **Execution:** taker at ask.
- **Small bankroll:** good per trade.
- **Duration:** about 1–2 weeks.
- **Sample:** hundreds of windows.
- **Complexity:** medium.
- **Cost:** $0.
- **Lockup:** hours.
- **Failure modes:** one mismatch costs about 49 wins; 99c cap.
- **Falsification:** R6: median ask ≥ 1 − (mismatch rate + fee), or ≥99c in ≥80% of ≥20 windows.
- **Class:** PLAUSIBLE HYPOTHESIS. **R6:** WEAKEN.

**TB-11 — Hourly temperature (TWC-settled) vs live ASOS nowcast, non-NY** · R2 H-R2-11

- **Market:** Kalshi hourly temperature markets.
- **Direction / order type:** taker or maker toward the observation nowcast in the last 30–60 min.
- **Mechanism:** 5-min ASOS nearly determines the hour.
- **Why it might exist:** a new product with retail flow.
- **Why competitors might not eliminate it:** they would; latency.
- **Evidence for:** Le (short-horizon over-extremity).
- **Evidence against:** TWC values differ from raw ASOS (rounding, QC); TWC data is blocked by terms; latency
  competition.
- **Data:** ASOS (grant) plus Kalshi hourly books (collection grant).
- **Rules:** P11.
- **Fees:** per series.
- **Execution:** taker within minutes.
- **Small bankroll:** fine.
- **Duration:** weeks (prospective).
- **Sample:** thousands of station-hours.
- **Complexity:** medium.
- **Cost:** recurring collection.
- **Lockup:** about 1 h.
- **Failure modes:** settlement mismatch.
- **Falsification:** mismatch ≥3% near thresholds, or mid at T−15 already ≥97% when the nowcast is.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-12 — Politics underconfidence, long-dated** · R1 H8

- **Market:** Kalshi politics.
- **Direction / order type:** maker favourites at 70–90c far from resolution.
- **Mechanism:** compression toward 50% (Le slope up to 1.83).
- **Why it might exist:** partisan money; carry cost.
- **Why competitors might not eliminate it:** months of lockup.
- **Evidence for:** Le; Page & Clemen.
- **Evidence against:** Whelan: politics not significant; few independent events.
- **Data:** A2.
- **Rules:** per market.
- **Fees:** per series.
- **Execution:** maker.
- **Small bankroll:** poor (capital-days).
- **Duration:** days (retrospective).
- **Sample:** tens of independent events.
- **Complexity:** low.
- **Cost:** $0.
- **Lockup:** months.
- **Failure modes:** few clusters; carry.
- **Falsification:** event-clustered CI includes 0 after carry and fees.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-13 — Polymarket→Kalshi lead-lag, non-sports** · R1 H9

- **Market:** same-event contracts on both venues.
- **Direction / order type:** taker on Kalshi after a Polymarket move.
- **Mechanism:** price discovery on the deeper venue.
- **Why it might exist:** segmented users.
- **Why competitors might not eliminate it:** they would; cross-venue bots.
- **Evidence for:** Ng et al. (2024 election only; SSRN 403, abstract only).
- **Evidence against:** single event; coarse Polymarket timestamps in public tapes; latency.
- **Data:** synchronized books on both venues (new recurring collection; A3/A4).
- **Rules:** contract equivalence per pair.
- **Fees:** Kalshi per series.
- **Execution:** taker.
- **Small bankroll:** fine.
- **Duration:** weeks.
- **Sample:** UNKNOWN.
- **Complexity:** high.
- **Cost:** recurring.
- **Lockup:** to resolution.
- **Failure modes:** non-equivalence; latency.
- **Falsification:** signal-conditional Kalshi move < fee + half-spread.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-14 — Kalshi vs Polymarket US executable gaps, NBA/MLB** · R2 H-R2-06

- **Market:** the same NBA/MLB games on both venues (NFL excluded).
- **Direction / order type:** taker on both legs.
- **Mechanism:** segmented pools (Gebele & Matthes: median 2–4% deviations, mostly non-sports).
- **Why it might exist:** dual accounts and rule mapping are barriers.
- **Why competitors might not eliminate it:** capital split, lockup.
- **Evidence for:** A12.
- **Evidence against:** sports is the most arbitraged segment; rule non-equivalence; 3.25c combined taker fees
  at 0.5.
- **Data:** synchronized books (Polymarket US terms "not cleared", ADR 0032).
- **Rules:** per league.
- **Fees:** Polymarket US VERIFIED-DOC, Kalshi pending.
- **Execution:** two accounts (not authorized).
- **Small bankroll:** poor.
- **Duration:** weeks.
- **Sample:** hundreds of snapshots.
- **Complexity:** high.
- **Cost:** recurring.
- **Lockup:** to game end on both venues.
- **Failure modes:** leg risk.
- **Falsification:** gap after fees ≤1c in ≥99% of ≥200 synchronized snapshots.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-15 — NBA injury-report lead-lag** · R2 H-R2-08

- **Market:** Kalshi NBA around official report times.
- **Direction / order type:** taker within N seconds of a posting.
- **Mechanism:** slow retail book.
- **Why it might exist:** retail-heavy flow.
- **Why competitors might not eliminate it:** they would; professionals scrape the reports, and news leaks first.
- **Evidence for:** none Kalshi-specific.
- **Evidence against:** Croxson & Reade.
- **Data:** official.nba.com (terms review) plus books (collection).
- **Rules:** as TB-01.
- **Fees:** UNVERIFIED.
- **Execution:** 1–60 s polling.
- **Small bankroll:** fine.
- **Duration:** a season.
- **Sample:** about 50+ postings.
- **Complexity:** high.
- **Cost:** recurring.
- **Lockup:** to game end.
- **Failure modes:** leaks.
- **Falsification:** ≥80% of the 30-min move happens within 60 s.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-18 — Decided-game dead-side sweep (blowout favourite at 95–99c)** · own (R1 S1 problem 3)

- **Market:** Kalshi NBA/MLB, decided late games.
- **Direction / order type:** taker on the near-certain side.
- **Mechanism:** tick floor plus carry on a decided game.
- **Why it might exist:** nobody bothers at 1–3c.
- **Why competitors might not eliminate it:** they do (bots).
- **Evidence for:** Becker: 95c wins 95.83%.
- **Evidence against:** the edge is ≤1 tick; Le's late slope <1 in weather (analogy only); score margin needs
  play-by-play.
- **Data:** A2 plus play-by-play (grant).
- **Rules:** suspension states.
- **Fees:** 0.33c at 95c.
- **Execution:** taker.
- **Small bankroll:** OK per trade.
- **Duration:** days.
- **Sample:** thousands of games.
- **Complexity:** medium.
- **Cost:** $0.
- **Lockup:** minutes.
- **Failure modes:** this is the textbook "98% win rate that loses" (section f).
- **Falsification:** game-clustered net at the ask ≤ 0.
- **Class:** PLAUSIBLE HYPOTHESIS (weak).

**TB-19 — In-play overreaction to surprising scoring (fade underdog surges), NBA/MLB** · own, from Choi & Hui (A27)

- **Market:** Kalshi NBA/MLB in-game.
- **Direction / order type:** taker against a jump after a surprising score.
- **Mechanism:** overreaction to surprising news.
- **Why it might exist:** salience.
- **Why competitors might not eliminate it:** fast books.
- **Evidence for:** Choi & Hui (exchange football, abstract-level).
- **Evidence against:** Croxson & Reade (full updating); no Kalshi study.
- **Data:** A2 plus play-by-play (grant).
- **Rules:** as TB-01.
- **Fees:** UNVERIFIED.
- **Execution:** taker at the ask after a latency.
- **Small bankroll:** good.
- **Duration:** about 1–2 weeks.
- **Sample:** thousands of events.
- **Complexity:** medium-high (event detection).
- **Cost:** $0.
- **Lockup:** minutes to hours.
- **Failure modes:** "surprise" defined ex post.
- **Falsification:** post-jump reversal at the ask ≤ fee, game-clustered.
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-22 — Economic-release markets vs public nowcast (CPI)** · R2 H-R2-09

- **Market:** Kalshi CPI/PCE brackets.
- **Direction / order type:** toward the Cleveland Fed nowcast.
- **Mechanism:** the nowcast embeds daily energy prices.
- **Why it might exist:** anchoring on consensus.
- **Why competitors might not eliminate it:** they would; the nowcast is free.
- **Evidence for:** none.
- **Evidence against:** FEDS 2026-010 (Kalshi beats Bloomberg on headline CPI); anecdote: Kalshi beat the nowcast
  3/3.
- **Data:** nowcast vintages (archive availability UNKNOWN) plus A2.
- **Rules:** markets cease trading before the release (P18).
- **Fees:** UNVERIFIED.
- **Execution:** taker or maker.
- **Small bankroll:** fine.
- **Duration:** days.
- **Sample:** about 12 per series per year.
- **Complexity:** low.
- **Cost:** $0.
- **Lockup:** up to a month.
- **Failure modes:** tiny n.
- **Falsification:** on ≥24 releases, the market error ≤ nowcast error.
- **Class:** PLAUSIBLE HYPOTHESIS with a strongly negative prior.

**TB-23 — Settlement reference-period and data-vintage mismatch (objective-data contracts)** · OP-H02 + OP-H18 · new mechanism

- **Market:** Kalshi contracts that settle on an official statistic with a defined reference period and vintage.
  First family: EIA Weekly Petroleum Status Report quantities (OP-R24, OP-R25). Other economic-release contracts
  come later and one family at a time.
- **Direction / order type:** taker at the ask, at a checkpoint 24 h (secondary 2 h) before the scheduled first
  release. Enter only when a deterministic public-information bound, or a conservative interval, beats the ask
  plus fee plus a 2c research margin (OP protocol 2).
- **Mechanism:** a headline about a period that does not pay. For example, an announcement after the reference
  week ended, or one that affects a later week. Also contracts that settle on a first release while analysts use
  revised or differently normalized data.
- **Why it might exist:** precise reading of rules and release notes is rare; headline-driven traders conflate
  periods.
- **Why competitors might not eliminate it:** niche, low frequency, labour-intensive; no speed advantage needed.
- **Evidence for:**
  - EIA explanatory notes define reporting period and publication separately (OP-R24);
  - Gu et al. (OP-R06) is a design lead only;
  - **no measured instance**: the packet found no executable case.
- **Evidence against:**
  - opportunity frequency unknown;
  - markets may already understand the distinction;
  - revisions can invalidate a "certain" bound;
  - Kalshi economic contracts cease trading before the release (P18), so the trade is pre-release only.
- **Data / source / permissions:**
  - contract rules text and official release documents (documentation; readable now);
  - an archive of release **vintages** (for example ALFRED or EIA archived releases as data) needs a source grant
    (packet item 6);
  - Kalshi historical quotes for those series need A2.
- **Contract / rules:** must be read per contract version. The reference period, units, revision policy and
  exception payouts are the whole hypothesis.
- **Fee verification:** per series; not yet read.
- **Execution:** taker at the one-minute ask.
- **Small bankroll:** good.
- **Test duration:** about 1 day for one semantic counterexample; 2–7 days for a 20-case audit; months for an
  economic sample.
- **Sample:** about 50 weekly releases a year per series, clustered by release (several thresholds share one
  release).
- **Complexity:** medium; manual two-reviewer semantic mapping first.
- **Ongoing cost:** $0 (owner and agent hours).
- **Capital lockup:** about 1–2 days.
- **Failure modes:**
  - a wrong join (wrong week or units) creates the very edge sought;
  - revision risk;
  - no liquidity at the checkpoint.
- **Falsification (OP protocol 2):**
  - no independently adjudicated reference mismatch in the covered universe;
  - no all-in price margin;
  - the effect disappears after revision handling.
  - INSUFFICIENT, rather than falsified, if archived quotes or vintages are unavailable.
- **Class:** PLAUSIBLE HYPOTHESIS (owner-supplied external research, 2026-10-08).

**TB-26 — Short-lived liquidity dislocation / cancellation recovery** · OP-H22, R2 S11

- **Market:** any Kalshi series.
- **Direction / order type:** resting quote after a temporary withdrawal.
- **Mechanism:** uninformed liquidity withdrawal.
- **Evidence for:** none Kalshi-specific (R2 S11).
- **Evidence against:**
  - quotes that vanish are not fills we could get;
  - faster competitors;
  - toxic news flow.
- **Data:** sequenced L2 and cancellations. None exists historically, so it needs recurring sub-minute
  collection (a grant).
- **Fees:** per series.
- **Execution:** maker.
- **Small bankroll:** poor.
- **Duration:** weeks.
- **Sample:** UNKNOWN.
- **Complexity:** high.
- **Cost:** recurring.
- **Lockup:** short.
- **Failure modes:** adverse selection.
- **Falsification:** fill-conditioned losses at least equal to the price improvement.
- **Class:** PLAUSIBLE HYPOTHESIS (weak).

**TB-27 — Public attention / buzz reversal** · OP-H23

- **Market:** event markets with attention spikes.
- **Direction / order type:** fade attention-driven moves.
- **Mechanism:** attention moves prices independently of probability.
- **Evidence for:** the original sportsbook study.
- **Evidence against:** Clegg & Cartlidge (OP-R29) trace much of the published result to one erroneous extreme
  odds entry, and a later extension does not reproduce the profit.
- **Data:** pageview or attention series (terms) plus A2.
- **Execution:** taker.
- **Small bankroll:** fine.
- **Duration:** days after data.
- **Sample:** hundreds of events.
- **Complexity:** medium.
- **Cost:** $0 (no paid sentiment feed).
- **Lockup:** days.
- **Falsification:** replicate the correction first; no effect on a cleaned later sample.
- **Class:** PLAUSIBLE HYPOTHESIS with negative external replication (section i).

### Gate-blocked (listed, not scored: an impossible permission or unknown fee is never hidden in a score)

**TB-06 — Combo (KXMVE) overpricing, quoter side** · R1 H5, R2 H-R2-05

- **Market:** Kalshi combos via RFQ.
- **Direction:** quote combos.
- **Mechanism:** a premium over the leg product of about 3% per leg.
- **Evidence for:** Moshrefi; NJ parlay hold (Whelan 2026).
- **Evidence against:**
  - R ≈ 1 at 2–5 legs, where the volume is.
  - Naive quoting lost $174k on replay (LOPMM).
  - Moshrefi does **not** attribute parlays to insurance demand (R6 §7 #1).
- **Data:** KXMVE coverage UNKNOWN.
- **Fee:** FEE_UNSUPPORTED by prefix; RFQ 5-second fee swap.
- **Execution:** ordinary-member quoting not stated; RFQ quoting not authorized.
- **Gates:** **G2 UNKNOWN, G3 UNKNOWN, so BLOCKED.**
- **Class:** PLAUSIBLE HYPOTHESIS. **R6: KILL as an edge for us** (section i).

**TB-07 — Combo-avoidance cost rule (buy legs, not combos)** · own

- A requester-side cost rule, not an edge. It is kept as an input to the TB-17 overlay.
- **Status:** NOT A STRATEGY.

**TB-16 — Price-relative wallet skill, copy at a delay** · R2 H-R2-12

- **Market:** Polymarket.
- **Gates:**
  - G1: data routes are forbidden; the Akey dataset needs a grant;
  - G3: Polymarket International is not accessible (2026-09-23), and copy execution on Polymarket US is UNKNOWN.
- **Result:** **BLOCKED.** It stays in #168's synthetic lane.
- **Evidence against:** Akey (persistence may be selection); CopyGrade (72% farming-flagged; UNVERIFIED); BallesJr
  (noise).
- **Class:** UNVERIFIED TRADING CLAIM / PLAUSIBLE.

**TB-17 — Conditional no-trade filters overlay** · R2 H-R2-13

- An **overlay**, scored with its host and never ranked standalone (it has no return of its own).
- **Falsification:** frozen filters do no better than 1,000 matched random exclusions (permutation p > 0.05).
- **Class:** PLAUSIBLE HYPOTHESIS.

**TB-24 — Forecast-to-position conversion (fixed-dollar vs capped fractional Kelly vs Brier-derived exposure)** · OP-H03

- A **decision layer, not a standalone strategy**.
- **Question:** holding forecasts, opportunity set, cash and fees fixed, does a Brier-derived allocation beat a
  naive or fractional-Kelly one? OP-R06 gives a theoretical counterexample: a better Brier score with a negative
  naive-Kelly profit. The packet's script reproduces it arithmetically.
- **Gate:** it needs **genuine prior forecasts** with creation times.
  - Prophet-Arena-Subset-3000 has none (OP-R12/R13).
  - EXP-001's forecasts and shadow ledger are prohibited inputs for Track B.
- **Result:** BLOCKED for empirical evaluation. The **fixture harness can be built now**. The coordinator
  assigned it to the harness lane, reusing the sizing challengers in `experiments/sizing_v2` and
  `docs/research/STAKE_SIZING_V2.md`.
- Not top-3-worthy as a protocol.
- **Class:** PROVEN theoretical result (mechanism); empirical value UNKNOWN.

**TB-25 — Entity-correct retrieval and source-quality abstention** · OP-H17

- An **overlay** for the #181 crawler/semantic lane, not a Track B profit source.
- The packet found visible bad joins in Prophet-Arena previews. For example, `KXWNBAGAME-25JUN17ATLNY` was paired
  with an MLB Braves/Mets source. These are examples, not an error rate.
- **Class:** PLAUSIBLE (quality filter).

**TB-20 — Novig maker/taker and FLB on a second venue** · own (R3 A1)

- **Gates:** G1 needs a terms review (no licence stated); G2 UNKNOWN (no Novig fee record); G3 UNKNOWN (account,
  jurisdiction).
- **Result:** **BLOCKED as a strategy.**
- It is useful only as a mechanism replication dataset for TB-03 and TB-05 (packet item 5).

**TB-21 — Index range markets vs options-implied distribution** · R2 OTHER

- **Gates:** G1 UNKNOWN (options data probably paid; terms); G2 UNVERIFIED (INX 0.035 from secondary sources only).
- **Result:** **BLOCKED.**

### Excluded by scope (G4), recorded so they are not re-proposed

| ID | Hypothesis | Source | Why excluded |
|---|---|---|---|
| TB-X1 | Exclusive-outcome sum violations; selling all longshots of an event | R1 H10, R2 S5, R6 §5 | Family B mechanism (EXP-003, PAUSED); never a back door |
| TB-X2 | Sportsbook consensus as a Kalshi no-trade filter; **fresh sportsbook consensus vs the attainable Kalshi ask** | R2 H-R2-07; **OP-H01** (the packet's first recommended test) | Family A mechanism. It is essentially EXP-002 itself. It goes to the owner as a choice (packet item 8): leave it to EXP-002's own A.C run (about 2026-10-19), or authorize an OP-H01-style label-blind attrition funnel as EXP-002 development work in EXP-002's log |
| TB-X6 | Better de-vig / odds-conversion challenger | OP-H04 | The sportsbook reference probability is family A's benchmark. It belongs to EXP-002 as a versioned challenger. Football-Data restricts automated, bot and AI use, so it is excluded as a source (OP-R26) |
| TB-X7 | Asian-handicap information transferred to soccer event markets | OP-H07 | Family A mechanism (sportsbook information vs event-market price); Football-Data rights (OP-R26) |
| TB-X3 | In-game favourite discount vs live sportsbook consensus | R2 H-R2-14 | Family A mechanism (R6: WEAKEN, vendor-only). Its non-sportsbook part is in TB-01 |
| TB-X4 | Consensus vs Kalshi CPI | R1 H11 | Kept only as a negative control (section i) |
| TB-X5 | Late-game NHL calibration (Moshrefi's largest slope) | R1 S1 | NHL outcomes excluded. R6 judges NHL the slice most fully explained by overtime selection |

---

## (d) Ranking

### Hard feasibility gates (applied first)

**Gate definitions.**

| Gate | Question | Possible results |
|---|---|---|
| G1 | Data legally obtainable | APPROVAL (a public, $0 route needing one named owner grant) / UNKNOWN / NO |
| G2 | Fees verifiable | VERIFIABLE (documented formula; a named verification step) / UNKNOWN |
| G3 | Executable side available to an ordinary US member | YES / UNKNOWN / NO |
| G4 | Inside Track B scope | PERMITTED / EXCLUDED |

**Results.**
- **CONDITIONAL:** only APPROVAL or VERIFIABLE conditions remain. These are scored, and the conditions are
  listed beside the score.
- **BLOCKED:** any UNKNOWN or NO on G1–G3, or EXCLUDED on G4. These are not scored.
- **Nothing passes outright today.** Every candidate needs at least one data grant, and every Kalshi series used
  needs fee verification.

| ID | G1 data | G2 fee | G3 side | G4 scope | Gate result |
|---|---|---|---|---|---|
| TB-01 | APPROVAL (A2) | VERIFIABLE (NBA/MLB) | YES | PERMITTED | CONDITIONAL |
| TB-02 | APPROVAL (A2) | VERIFIABLE | YES | PERMITTED (no book odds) | CONDITIONAL |
| TB-03 | APPROVAL (A2) | VERIFIABLE (fee_type history) | YES | PERMITTED (non-sports) | CONDITIONAL |
| TB-04 | APPROVAL (A2) | VERIFIABLE | YES | PERMITTED (single markets) | CONDITIONAL |
| TB-05 | APPROVAL (A2) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-08 | APPROVAL (collection) | VERIFIABLE | YES (LIP open to regular members) | PERMITTED | CONDITIONAL |
| TB-09 | APPROVAL (A2) | VERIFIABLE | YES | PERMITTED (non-NY) | CONDITIONAL |
| TB-10 | APPROVAL (IEM + A2) | VERIFIABLE | YES | PERMITTED (non-NY) | CONDITIONAL |
| TB-11 | APPROVAL (ASOS + collection) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-12 | APPROVAL (A2) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-13 | APPROVAL (recurring collection) | VERIFIABLE | YES | PERMITTED (non-sports) | CONDITIONAL |
| TB-14 | APPROVAL (PM US terms + collection) | VERIFIABLE | YES in principle | PERMITTED (NBA/MLB) | CONDITIONAL |
| TB-15 | APPROVAL (terms + collection) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-18 | APPROVAL (A2 + play-by-play) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-19 | APPROVAL (A2 + play-by-play) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-22 | APPROVAL (A2; nowcast archive UNKNOWN) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-23 | APPROVAL (A2 + vintage archive); stage 1 documentation only | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-26 | APPROVAL (recurring L2 collection) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-27 | APPROVAL (attention data terms + A2) | VERIFIABLE | YES | PERMITTED | CONDITIONAL |
| TB-24, TB-25 | — | — | — | — | decision layer / overlay; not a standalone strategy |
| TB-06 | UNKNOWN | UNKNOWN | UNKNOWN | PERMITTED | BLOCKED |
| TB-16 | NO (data routes) | VERIFIABLE | UNKNOWN | PERMITTED | BLOCKED |
| TB-20 | APPROVAL (terms) | UNKNOWN | UNKNOWN | PERMITTED | BLOCKED |
| TB-21 | UNKNOWN (paid) | UNVERIFIED | YES | PERMITTED | BLOCKED |
| TB-07, TB-17 | — | — | — | — | not a standalone strategy |
| TB-X1..X5 | — | — | — | EXCLUDED | BLOCKED |

### The 15 criteria

The owner's directive asks for 15 ranking criteria, but its full §-list sits in the session transcript, not the
repo. These 15 operationalize the criteria named in #184 and in the directive's field list. Each is scored
0–3, equally weighted, and higher is always better.

| # | Criterion | 3 means | 0 means |
|---|---|---|---|
| 1 | EV: evidence strength | independent replicated Kalshi result | evidence against dominates |
| 2 | MP: mechanism persistence | structural reason it is not competed away | none |
| 3 | PIT: point-in-time testability | no look-ahead trap | cannot be made PIT |
| 4 | DA: data after one approval | one $0 public grant covers it | not obtainable |
| 5 | SS: independent sample | thousands of clusters | under 10 a year |
| 6 | TT: time to first honest diagnostic after the grant | ≤3 days | more than 3 months |
| 7 | EX: retrospective executability | taker at quotes | not available to us |
| 8 | FR: fee robustness | claimed edge ≫ fee and tick | below fee or tick |
| 9 | SB: $100 viability | full | none |
| 10 | CL: capital lockup / turnover | hours | months |
| 11 | DC: development complexity, inverse | reuse plus planned harness | new engine |
| 12 | OC: ongoing cost, inverse | $0, one-time | paid or recurring |
| 13 | CP: competitive pressure, inverse | low | bots dominate |
| 14 | TF: tail / failure severity, inverse | bounded | one event wipes out the gains |
| 15 | UP: upside if real | material dollars | none |

**Inputs.**
- R6's verdicts: a WEAKEN lowers EV and EX where R6 showed a bias or a quote problem.
- The owner packet's evidence: Kagan & Baiocchi move TB-01's EV to 0, because evidence against now dominates.
- The packet's own 10-criterion scores (OP scorecard) are a cross-check, not an input. They rank OP-H01 first,
  which Track B cannot take; OP-H02 second; and the late-game hypothesis sixth.

| ID | EV | MP | PIT | DA | SS | TT | EX | FR | SB | CL | DC | OC | CP | TF | UP | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TB-05 | 1 | 2 | 3 | 3 | 3 | 3 | 2 | 1 | 3 | 2 | 3 | 3 | 2 | 1 | 2 | **34** |
| TB-01 | 0 | 2 | 2 | 3 | 2 | 3 | 2 | 2 | 3 | 3 | 3 | 3 | 1 | 2 | 2 | **33** |
| TB-03 | 2 | 2 | 2 | 3 | 3 | 3 | 1 | 2 | 2 | 2 | 2 | 2 | 1 | 2 | 3 | **32** |
| TB-02 | 1 | 1 | 3 | 3 | 3 | 3 | 2 | 1 | 3 | 2 | 3 | 3 | 0 | 2 | 1 | **31** |
| TB-09 | 1 | 1 | 2 | 3 | 3 | 3 | 1 | 1 | 3 | 3 | 2 | 3 | 1 | 2 | 1 | **30** |
| TB-12 | 1 | 2 | 3 | 3 | 1 | 3 | 2 | 3 | 1 | 0 | 3 | 3 | 2 | 1 | 1 | **30** |
| TB-04 | 1 | 2 | 2 | 3 | 2 | 3 | 1 | 2 | 2 | 1 | 3 | 3 | 2 | 0 | 2 | **29** |
| TB-19 | 1 | 1 | 2 | 2 | 3 | 2 | 2 | 1 | 3 | 3 | 1 | 3 | 1 | 2 | 2 | **29** |
| TB-23 | 1 | 2 | 2 | 1 | 1 | 2 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 | 1 | **28** |
| TB-10 | 1 | 1 | 2 | 2 | 2 | 2 | 2 | 1 | 3 | 3 | 2 | 3 | 0 | 0 | 1 | **25** |
| TB-11 | 1 | 1 | 2 | 1 | 3 | 2 | 2 | 1 | 3 | 3 | 2 | 2 | 0 | 1 | 1 | **25** |
| TB-18 | 0 | 1 | 1 | 2 | 3 | 2 | 3 | 0 | 2 | 3 | 2 | 3 | 0 | 0 | 0 | **22** |
| TB-27 | 0 | 0 | 2 | 1 | 2 | 2 | 2 | 1 | 3 | 2 | 2 | 2 | 1 | 2 | 0 | **22** |
| TB-08 | 1 | 2 | 2 | 1 | 2 | 1 | 1 | 2 | 1 | 2 | 1 | 1 | 1 | 2 | 1 | **21** |
| TB-15 | 0 | 0 | 2 | 1 | 2 | 1 | 2 | 2 | 3 | 3 | 1 | 1 | 0 | 2 | 1 | **21** |
| TB-13 | 1 | 1 | 1 | 1 | 2 | 1 | 2 | 1 | 2 | 2 | 1 | 1 | 0 | 2 | 2 | **20** |
| TB-22 | 0 | 0 | 2 | 1 | 0 | 2 | 2 | 2 | 3 | 1 | 2 | 3 | 0 | 2 | 0 | **20** |
| TB-14 | 1 | 1 | 2 | 1 | 2 | 1 | 2 | 1 | 0 | 2 | 2 | 1 | 0 | 1 | 1 | **18** |
| TB-26 | 0 | 1 | 2 | 1 | 2 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | 0 | 1 | 1 | **17** |

**Tie-break,** declared before reading the totals: higher EV, then higher SB + CL (the $100 relevance).

**Sensitivity.**
- **Executability (EX):**
  - ×2: TB-03 and TB-02 tie at 33, and EV breaks the tie for TB-03;
  - ×3: TB-02 (35) leads TB-03 (34).

  **TB-03's third place therefore depends on accepting a bound-only maker test.**
- **Upside (UP):** removing it drops TB-03 to 29 and lifts TB-02 to third.
- **TB-01 vs TB-02:** setting TB-01's EV back to 1 (ignoring Kagan & Baiocchi) only swaps it with TB-05.
- **TB-23:** none of the reweightings above lifts it into the top five (doubling SB or FR gives 31 or 30). It is
  held back by sample (weekly releases) and by needing two grants.

### Groups

| Group | Sub-score | Leaders |
|---|---|---|
| **FASTEST TESTABLE** | DA + SS + TT + DC + PIT, max 15 | TB-05 (15) and TB-02 (15), then TB-01, TB-03, TB-09 and TB-12 (13 each). All need A2 first. **Exception:** TB-23's stage-1 semantic audit needs no grant and can start today, though it yields no price evidence. |
| **HIGHEST ECONOMIC UPSIDE** | UP + FR + CL + SB + EX, max 15 | TB-01 (12), TB-19 (11), TB-15 (11), TB-05 (10), TB-03 (10). "Upside" is conditional on the hypothesis being real, which R6 and OP-R04 doubt. |
| **BEST BALANCE** | total | TB-05 (34), TB-01 (33), TB-03 (32), TB-02 (31), TB-09 (30) |

- **Top five:** TB-05, TB-01, TB-03, TB-02, TB-09. TB-09 beats TB-12 on the tie-break: SB + CL 6 vs 1.
- **Top three:** **TB-05, TB-01, TB-03**. These are registered as EXP-005, EXP-004 and EXP-006 (registry ids follow
  registration order, not rank).

**Fewer than three are testable now: zero are.**
- **Data.** The top three need Kalshi trades and one-minute candles for non-sports series (TB-05, TB-03) and for
  NBA/MLB (TB-01). R3 found that no Kalshi trade prints or candles are collected anywhere.
- **Protected and excluded scopes.** The sports data we hold is NFL (EXP-002 protected) or NHL (outcomes
  excluded). The weather data is KXHIGHNY (EXP-001 protected).
- **Fees.** Every sports fee is unverified or unsupported.

---

## (e) Deep research report

### Academic anomalies vs executable strategies

- **Academic anomalies** are descriptive patterns at trade prices, gross or with a stylized fee:
  - Kalshi FLB (Whelan; Becker; Le);
  - time-to-close calibration (Moshrefi; Le; Page & Clemen);
  - maker>taker (Becker; Whelan; Akey);
  - parlay premium (Moshrefi; Whelan 2026 on books);
  - Polymarket arbitrage (Saguillo).
- **No published source shows a fill-attainable, after-fee, small-account Kalshi edge** (R1 bottom line; R6).
- **Executable strategies** need four things in addition:
  - a decision-time clock;
  - the ask, or a queue-aware maker fill;
  - series fees;
  - one decision per cluster.

  Those are exactly what EXP-004/005/006 add.

### Source register, deduplicated

Each row keeps the 12 required fields:
1. source / URL / date;
2. period;
3. market;
4. mechanism;
5. data;
6. reported returns;
7. realized or simulated;
8. fees;
9. execution prices;
10. viable;
11. competition;
12. disproof.

Then the class (after R6 corrections). Source registers R1 §1, R2 §1 and R6 §7 are the originals. "Opened" status
is as R1/R2/R6 report it.

| # | 1 Source (URL, date) | 2 Period | 3 Market | 4 Mechanism | 5 Data | 6 Returns | 7 R/S | 8 Fees | 9 Exec prices | 10 Viable | 11 Competition | 12 Disproof | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Moshrefi, "Prices, Probabilities, and Parlays", https://arxiv.org/abs/2607.14430 (2026-07-15) | Mar–mid-May 2026 | Kalshi NBA/MLB/NHL moneylines; combos | Late S-shape (γ 1.27–1.31; Platt NBA 1.62, MLB 2.05, NHL 4.56); parlay premium about 3%/leg | 23M trades; no book, side or game state; no code/data | none | descriptive | excluded | trade prints | unknown (one window) | high (sports) | effect gone under a PIT clock (R6); slope ≈1 at quotes | PLAUSIBLE HYPOTHESIS (R6: realized-close τ, OT selection, pooling of both team markets, no SEs) |
| 2 | Akey, Grégoire, Harvie, Martineau, CEPR DP21615 https://econpapers.repec.org/RePEc:cpr:ceprdp:21615 ; PDF https://www.carf.e.u-tokyo.ac.jp/wp/wp-content/uploads/2026/06/260714_polymarket.pdf ; data https://huggingface.co/datasets/vgregoire/polymarket-users (2026-06-21) | 2022-11-11 to 2026-03-29 | Polymarket, all | Winners are makers; profits concentrated (top 1% get 76.5%) | 588M on-chain fills | user PnL | realized | fee-free era | realized fills (theirs) | fees since 2026-03-30 untested | bots, pro MMs | maker-share effect gone post-fees | REPLICATED descriptive (R6: persistence may be selection/survivorship) |
| 3 | Bürgi, Deng, Whelan, "Makers and Takers", https://www.karlwhelan.com/Papers/Kalshi.pdf (Jan 2026); https://www2.gwu.edu/~forcpgm/2026-001.pdf | 2021–Apr 2025 | Kalshi, all | FLB; ≤10c lose >60%; >70c small positive post-fee; makers −9.64% vs takers −31.46%; makers ≥50c +2.6% | 313,972 last-trade-per-day prices, maker flag | per-contract returns | realized ex post | taker 0.07p(1−p); makers fee-free | last trade, no depth | weakening (2025 slope 0.021 vs 0.048) | rising | 2025–26 FLB ≈0 | REPLICATED HISTORICAL RESULT (FLB); maker significance "generally not replicated" by day (R6) |
| 4 | Becker, https://jbecker.dev/research/prediction-market-microstructure (2026-01-18); data/code https://github.com/Jon-Becker/prediction-market-analysis (MIT) | Jun 2021–2025-11-25 | Kalshi | makers +1.12% / takers −1.12%; NO beats YES at 69/99 levels; category maker returns up to about +3.6% (gap up to 7.3pp); takers +2.0% through 2023, gap crossed zero 2024 Q2 | 72.1M trades with taker side | gross excess returns | realized | **gross** | trade prints; no spread data | regime-dependent | rising | gap ≤ maker fee in 2026 | replicated *descriptive*, not a strategy return (R6 §7 #13, #14) |
| 5 | Le, "Decomposing Crowd Wisdom", https://arxiv.org/abs/2602.19520 (rev. 2026-08-04); code https://github.com/namanhzz/prediction-market-calibration (MIT; not opened) | Kalshi 2021-07–2025-12 | Kalshi, Polymarket | slope b by domain × horizon: politics 1.3–1.8; sports 0.90–1.10 at 0–48 h; weather 0.69 (0–1 h) → 1.20–1.37 beyond 2 days | Becker tape | none | descriptive | not modelled | trade prices, quantity-weighted | untested | — | b≈1 on 2026 data | REPLICATED (shares the tape with #4; not independent) |
| 6 | Cardozo & Rivero-Wildemauwe, https://arxiv.org/abs/2609.12878 (2026-09-11) | 2022-11–2026-03 | Polymarket | FLB is a multi-outcome composition effect; event-equal weight longshots +4.09%; sports longshots +2.43% [−0.93, 5.79] | Akey data | as stated | realized | excluded | trade prints | — | — | — | REPLICATED, **against** generic FLB |
| 7 | Diercks, Katz, Wright, FEDS 2026-010, https://www.federalreserve.gov/econres/feds/files/2026010pap.pdf (2026-02) | 2022–mid-2025 | Kalshi macro | Kalshi ≥ surveys; headline CPI beats Bloomberg | prices vs surveys | — | — | n/a | last trade | — | macro desks | — | PROVEN PUBLIC FINDING (against "consensus beats Kalshi") |
| 8 | Saguillo et al., https://arxiv.org/abs/2508.03474 (2025-08) | 2024-04–2025-04 | Polymarket rebalancing / combinatorial arb | sums ≠ $1 | on-chain fills | about $40M realized | realized (est.) | no fees then | non-atomic legs | fees and bots shrink it | very high | post-fee repeat ≈0 | PROVEN on Polymarket history; family B mechanism (excluded) |
| 9 | Ng, Peng, Tao, Zhou (SSRN 5331995, 403); abstract https://swift.szu.edu.cn/info/1051/5704.htm | 2024 election | Polymarket/Kalshi/PredictIt | Polymarket leads Kalshi | cross-venue trades | not seen | — | — | — | one event | — | lead-lag absent in 2026 | PLAUSIBLE (abstract only) |
| 10 | Page & Clemen, EJ 2013, https://ideas.repec.org/a/ecj/econjl/v123y2013i568p491-513.html | Intrade | Intrade | FLB grows with horizon; calibrated near expiry | prices | — | — | — | — | venue defunct | — | — | PROVEN PUBLIC FINDING |
| 11 | Page 2012, Applied Econ, https://ideas.repec.org/a/taf/applec/44y2012i1p81-92.html | Intrade sports | Intrade | losing teams overpriced late | prices | — | — | — | — | old venue | — | — | PROVEN (older venue) |
| 12 | Snowberg & Wolfers, JPE 2010, https://www.nber.org/papers/w15923 | US racing | pari-mutuel | misperception | pools | — | — | take | — | — | — | — | PROVEN PUBLIC FINDING |
| 13 | Thaler & Ziemba, JEP 1988, https://www.aeaweb.org/articles?id=10.1257/jep.2.2.161 | tracks | pari-mutuel | FLB | — | — | — | — | — | — | — | — | PROVEN (classic) |
| 14 | Ottaviani & Sørensen 2008, https://iris.unibocconi.it/handle/11565/3735090 | survey | betting | FLB taxonomy | — | — | — | — | — | — | — | — | PROVEN (review) |
| 15 | Smith, Paton, Vaughan Williams, Economica 2006, https://ideas.repec.org/a/bla/econom/v73y2006i292p673-689.html | UK racing | Betfair vs books | exchanges have lower FLB | odds | — | — | — | — | — | — | — | PROVEN PUBLIC FINDING |
| 16 | Croxson & Reade, EJ 2014, https://research.birmingham.ac.uk/en/publications/information-and-efficiency-goal-arrival-in-soccer-betting/ | in-play football | Betfair | prices update "swiftly and fully" | HF prices | — | — | — | — | — | — | — | PROVEN, against in-play underreaction |
| 17 | Whelan, "The Parlay Puzzle", https://www.karlwhelan.com/Papers/Parlays.pdf (May 2026) | NJ 2021–25 | US sportsbook parlays | parlay hold 17.5–19.2% vs 3.3–5.0% | NJ DGE reports | book hold | realized aggregate | is the margin | n/a | ongoing | — | — | PROVEN (about books, not Kalshi combos) |
| 18 | Sirolly et al., https://rajivsethi.substack.com/p/the-detection-of-wash-trading (Nov 2025) | 2022–25 | Polymarket | about 25% wash volume | on-chain | — | — | — | — | — | — | — | PLAUSIBLE (data-quality caveat) |
| 19 | Sethi, https://rajivsethi.substack.com/p/fee-structure-distortions-in-prediction-16-04-10 (2016) | 2016 | PredictIt | fees protect mispricing | quotes | — | — | central | — | PredictIt-specific | — | — | PLAUSIBLE |
| 20 | Oddpool, https://www.oddpool.com/research/kalshi-rfq-market-makers (undated) | two evenings | Kalshi RFQ | 13 automated sports quoters, 5 combo-only | own RFQs | — | — | — | — | — | concentrated | — | UNVERIFIED TRADING CLAIM |
| 21 | Crosier, https://arxiv.org/html/2609.23969 (2026-09-20) | 2022-01–2026-08-12 | Kalshi daily highs, 7 cities | market mid beats NBM RMSE by 9.8–11.4% and an optimal 6-forecast blend; scores centres, not tails (R6) | bid/ask snapshots, NWP | none | descriptive | none | mid | — | high | — | PROVEN PUBLIC FINDING (against forecast-as-taker) |
| 22 | k1hbles "kalshi-edge", https://github.com/k1hbles/kalshi-edge (README) | 96 days, Jul–Oct 2026 | 7 cities | MOS/NBM vs market | IEM, books | taker −2.5c/contract | simulated walk-forward | yes | ask | no | — | — | UNVERIFIED (negative) |
| 23 | myfirstcodeo, https://dev.to/myfirstcodeo/i-backtested-a-forecast-based-model-against-kalshis-temperature-markets-the-market-won-heres-442c (2026-09-23) | 2026-07-25–09-22 | 24 cities | normal-error forecast | Open-Meteo grids, daily candle closes | YES ROI −37.7%, NO −7.2% | simulated | yes | candle close | no | — | — | UNVERIFIED, **weak** negative (R6 §7 #10) |
| 24 | suislanchez weather bot, https://github.com/suislanchez/polymarket-kalshi-weather-bot | n/a | weather | GFS ensemble, 8% edge | Open-Meteo | "$1.8k" | **paper only** | no | no | — | — | claim contradicts its disclaimer | UNVERIFIED TRADING CLAIM |
| 25 | fsevkli ProjectKM, https://gitblind.noratr.app/fsevkli/ProjectKM | n/a | weather | HRRR/METAR | NWP | none | paper | no | — | — | — | — | UNVERIFIED |
| 26 | Gebele & Matthes, https://arxiv.org/html/2601.01706v1 (2026-01-05) | 2018–2025-08 | cross-platform | law-of-one-price gaps median 2–4%, structural | prices, fees, LLM matching | +1,218% over 15 trades | simulated | yes | historical snapshots | partly | moderate | gap ≈0 for US-accessible pairs | PROVEN gap existence; returns UNVERIFIED |
| 27 | Shen et al., https://arxiv.org/html/2606.16852 (2026-06-15) | 2025-08–2026-05 | Polymarket CLOB | off-chain fills revert (>24% at peak; about 0.3% after fixes) | on-chain | — | realized | — | historical prints overstate fills | partly mitigated | — | revert ≈0 | PROVEN (execution realism) |
| 28 | Moshrefi, Rana, Viswanath, LOPMM, https://arxiv.org/abs/2607.18299 (2026-07-13) | replayed Kalshi NBA | combos | naive independent quoting lost $174,050; LOPMM +$31 | parlay trades | losses | simulated replay | unclear | replay | — | pro RFQ quoters | — | PROVEN (naive quoting loses) |
| 29 | Frightened Parrot, https://macromodels.substack.com/p/reliably-bad-reliable-sources (2023-08-26) | May–Aug 2023 | Kalshi core CPI | Kalshi beat the nowcast 3/3 | — | — | anecdote | — | — | — | — | n=3 | UNVERIFIED |
| 30 | BallesJr copy trader, https://github.com/BallesJr/polymarket-copy-trader | 2026-07-03–08-12 | Polymarket | copy top wallets at 5.6-min median delay | public trades/books | +$171 on $10k paper | paper | assumed | ask-walk | unknown | many | — | UNVERIFIED |
| 31 | CopyGrade, https://copygrade.com/blog/we-scored-the-polymarket-leaderboard (Jun 2026) | snapshot | Polymarket | 72% farming-flagged; median post-fee edge −3.0% | proprietary | — | vendor | "post-fee" | — | — | — | — | UNVERIFIED |
| 32 | artym359, https://github.com/artym359/polymarket-copy-research | n/a | Polymarket | copy-delay tool | APIs | none | tool | yes | ranked proxies | — | — | — | UNVERIFIED (tool) |
| 33 | SportsBookISH, https://sportsbookish.com/research/why-mid-game-kalshi-lines-lag (2026-06-01) | since May 2026 | Kalshi in-game vs books | heavy favourites 5–15pp below consensus | 5–30 min scrape | none | observational | no | not executable | — | — | gap gone at ≤5 s sync | UNVERIFIED |
| 34 | SmartStake props, https://www.smartstake.app/learn/sharpest-sportsbooks-mlb-player-props (2026-07-07) | 2026 MLB | 75 books | Kalshi "sharpest" on props | proprietary | — | vendor | — | — | — | — | — | UNVERIFIED (R6 §7 #12: no evidential weight) |
| 35 | SmartStake fee arithmetic, https://www.smartstake.app/learn/kalshi-vs-sportsbook | n/a | Kalshi vs books | fee arithmetic | — | — | — | yes | — | — | — | — | UNVERIFIED |
| 36 | Rose-Berman, https://howgamblingworks.substack.com/p/kalshis-favorite-lie (2026-04-29) | n/a | Kalshi | taker loses about 3.4% of turnover at fair prices | — | — | — | yes | — | — | — | — | UNVERIFIED (arithmetic consistent) |
| 37 | Roosevelt Institute, https://rooseveltinstitute.org/blog/since-kalshis-launch-ordinary-users-have-lost-half-a-billion-dollars/ (2026-07-07) | 2021-07–2026-05 | Kalshi | $583.5M retail net loss; Dune access revoked 2026-05-15 | Dune | — | estimated | unclear | — | — | — | — | UNVERIFIED (advocacy; R6 §7 #11) |
| 38 | inGame, https://www.ingame.com/kalshi-in-house-trading-arm-not-profitable/ (2025-11-28) | Nov 2025 | Kalshi sports | affiliated MM "not profitable", <6% of sports volume | — | — | company statement | — | — | — | — | — | UNVERIFIED (company claim) |
| 39 | inGame, https://www.ingame.com/kalshis-change-may-increase-fee-sports-traders/ (2025-07-07; opened by R6) | 2025 | Kalshi sports | sports maker fee flat 0.25c before 2025-07-01, quadratic after; MLB not then | news | — | — | — | — | — | — | — | UNVERIFIED (secondary; to confirm in a fee document) |
| 40 | gambling911, https://www.gambling911.com/node/78397 (2025-12-09) | — | Kalshi live sports | order-execution delay filed | news | — | — | — | latency constrained | status UNVERIFIED | — | — | UNVERIFIED |
| 41 | Choi & Hui, JEBO 2014, https://researchportal.hkust.edu.hk/en/publications/the-role-of-surprise-understanding-overreaction-and-underreaction/ | in-play football | exchange | underreact to goals, overreact to surprising ones | prices | not read | historical | — | — | unknown for Kalshi | — | — | PROVEN (abstract-level) |
| 42 | Ötting et al., https://arxiv.org/pdf/2108.00821 (2022) | 1 Hz | live football stakes | stake overreaction | stakes, not prices | — | — | — | — | — | — | — | PLAUSIBLE (weak) |
| 43 | NWS SCN 22-33, https://www.weather.gov/media/notification/pdf2/scn22-33_nbm_prob_maxt_mint_update.pdf (2022-03-30) | 2022 | NBM PMaxT | percentiles overdispersed (then) | — | — | — | — | — | NBM v5.0 since 2026-05-05 | — | — | PROVEN (forecast-side caveat) |

**Owner-supplied external research, 2026-10-08 (OP register R01–R31), deduplicated.**

- The packet's sources that duplicate rows above are not repeated:
  - OP-R01 fee PDF and OP-R02 rounding (see fee facts);
  - OP-R03 = #1, OP-R05 = #21, OP-R07/R08 = #2, OP-R09 = #8, OP-R17/R18 = #4.
- The rows below are new. "Class" adds the packet's own access note. The packet read each source on 2026-10-08;
  we did not re-open them.

| # | 1 Source (URL, date) | 2 Period | 3 Market | 4 Mechanism | 5 Data | 6 Returns | 7 R/S | 8 Fees | 9 Exec prices | 10 Viable | 11 Competition | 12 Disproof | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 44 | OP-R04 Kagan & Baiocchi, "Calibration in Prediction Markets: Theory and Evidence", https://kalshi.com/research/kalshi-research-calibration.pdf (Aug 2026) | 2021–mid-2026 | Kalshi incl. sports | calibration improves once actual game-end timing corrects the clock | Kalshi data, private timing | none | descriptive | — | — | — | — | — | Owner-supplied external research. Exchange-hosted working paper, so not independent of the venue; private timing data. **Evidence against TB-01.** |
| 45 | OP-R06 Gu, Kagan, Sun, Wu, Xu, "When do prophets profit in prediction markets?", https://arxiv.org/html/2607.06166v3 (v3 2026-09-23) | theory + small live pilot | prediction markets | better Brier score ≠ profitable allocation; scoring-rule-derived bets | author pilot | author-reported pilot | realized (pilot, unreconciled) | — | — | — | — | — | Owner-supplied. PROVEN theoretical counterexample; pilot UNVERIFIED. Basis of TB-24. |
| 46 | OP-R10 Qin & Yang, "Polymarket-v1 Database", https://arxiv.org/html/2606.04217v1 (2026-06-02) | 2022-11-21–2026-04-28 | Polymarket | heuristic aggressor classification vs ground truth is poor | on-chain raw and cleaned events | — | — | — | no resting book | — | — | — | Owner-supplied; PROVEN (data quality) |
| 47 | OP-R11 TimeSeventeen/Polymarket-v1 dataset, https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1 | as #46 | Polymarket | — | raw/cleaned/CTF layers, CC-BY-4.0, UTC+8 day partitions | — | — | — | no L2 or cancels | — | — | — | Owner-supplied; a possible wallet-lane supplement (packet item 13) |
| 48 | OP-R12/R13 Prophet-Arena-Subset-3000, https://huggingface.co/datasets/prophetarena/Prophet-Arena-Subset-3000 | events closing 2025-06-17–2026-09-07 | Kalshi events | — | snapshot quotes (cents; zero bid = no bid), source text, outcomes; **no model predictions, no L2** | — | — | — | snapshots without size | — | — | — | Owner-supplied. MIT card. Visible entity mismatches. Its visible rows are now **development examples, not holdout**. |
| 49 | OP-R14–R16 Forecast-Dojo paper, code and dataset: https://arxiv.org/html/2609.28876v1 , https://github.com/liqinye/Forecast-Dojo , https://huggingface.co/datasets/foye107/Forecast-Dojo (2026-09-24) | — | forecasting benchmark | replay environments; tools need not make LLMs beat markets | event/date tasks | — | — | — | reference prices only | — | — | — | Owner-supplied. Running it is excluded (third-party code; provider calls by default) |
| 50 | OP-R19 Kalshi Historical Data docs, https://docs.kalshi.com/getting_started/historical_data | current | Kalshi | historical cutoff and endpoint families | — | — | — | — | — | — | — | — | Owner-supplied; VERIFIED-DOC (no endpoint called) |
| 51 | OP-R20 Kalshi historical candlesticks, https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks | current | Kalshi | yes_bid/yes_ask OHLC at 1/60/1440 min | — | — | — | — | **no depth or queue; arbitrary fills cannot be modelled** | — | — | — | Owner-supplied; VERIFIED-DOC |
| 52 | OP-R21 The Odds API historical, https://the-odds-api.com/liveapi/guides/v4/ | featured history from Jun 2020; 5-min from Sep 2022 | books | — | — | — | — | — | bookmaker quotes | — | — | — | Owner-supplied. **Historical endpoint is paid-only; the free pilot key gives no history** |
| 53 | OP-R22 IEM MOS archive, https://mesonet.agron.iastate.edu/mos/ | GFS since 2003; NBM schedule change 2026-05-05 | weather | — | forecast vintages | — | — | — | no quotes | — | — | — | Owner-supplied; public. Issuance ≠ first receipt |
| 54 | OP-R23 NOAA NBM on AWS, https://registry.opendata.aws/noaa-nbm/ | — | weather | — | GRIB2/COG | — | — | — | — | — | — | — | Owner-supplied; public with attribution; archive completeness untested |
| 55 | OP-R24/R25 EIA WPSR explanatory notes and archive, https://www.eia.gov/petroleum/supply/weekly/pdf/appendixb.pdf , https://www.eia.gov/petroleum/supply/weekly/ | current | EIA weekly statistics | reporting period ≠ publication day | official releases | — | — | — | no quotes | — | — | — | Owner-supplied; official documentation. Basis of TB-23 |
| 56 | OP-R26 Football-Data, https://www.football-data.co.uk/data.php | current page | soccer odds | — | results, pre/closing odds | — | — | — | not intraday | — | — | — | Owner-supplied. **Restricts automated, bot and AI use, so EXCLUDED as a source.** Stale Pinnacle odds since 2025-07-23 |
| 57 | OP-R27 Goto, Takeishi, Yairi, https://arxiv.org/html/2604.17194v1 (2026-04-19) | soccer 2012–2024 | books | odds-only conversion and a small GLM | historical odds | proper scores | — | — | — | — | — | — | Owner-supplied; PLAUSIBLE (family-A benchmark, TB-X6) |
| 58 | OP-R28 Hegarty & Whelan, https://researchrepository.ucd.ie/server/api/core/bitstreams/6af7585a-7577-40e4-bf62-7a383128be83/content (2023-02-16) | soccer | Asian handicap vs 1X2 | AH-derived probabilities more informative | odds | — | — | — | — | — | — | — | Owner-supplied; PLAUSIBLE (TB-X7) |
| 59 | OP-R29 Clegg & Cartlidge, "Not feeling the buzz", https://arxiv.org/html/2306.01740v3 (v3 2024-06-01) | through Aug 2023 | online sportsbooks | correction: a published buzz result traced to one erroneous extreme odds entry | original and corrected code | the earlier profit does not reproduce | replication | — | — | no | — | — | Owner-supplied; PROVEN (negative replication; TB-27) |
| 60 | OP-R30 Bailey & López de Prado, "The Deflated Sharpe Ratio", https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf (2014) | — | method | selection / multiple-trial correction | — | — | — | — | — | — | — | — | Owner-supplied; PROVEN (method) |
| 61 | OP-R31 Polymarket geographic restrictions, https://docs.polymarket.com/api-reference/geoblock | current | Polymarket intl | the US is close-only | — | — | — | — | — | — | — | — | Owner-supplied; VERIFIED-DOC (supports TB-16's block) |

**Not used (unreadable or unverified):**
- the Kalshi fee schedule live PDF (HTTP 429 on 2026-10-08);
- SSRN 6443103 and 5331995 (403);
- Della Vedova (summary only);
- Gómez-Cram et al. (not found);
- Pinnacle CLV pages (JavaScript only);
- the Oalkhadra repo (404);
- the "35.9 pp maker→taker" claim (not found in the text).

### Corrections applied from R6 §7 (overstatements in R1/R2)

| # | Overstated claim | What the source says |
|---|---|---|
| 1 | Moshrefi attributes parlays to insurance demand | That is the late-game mechanism; for parlays it "cannot be distinguished" |
| 2 | Whelan's "Yogi Berra" supports late-game sports | Final-day low-price contracts across categories; not minutes-to-end sports |
| 3 | Le supports the late-game effect | Le: sports 0–48 h "close to calibrated", which is against it |
| 4 | Maker bids at ≥90c in the final 10 min | Outside the paper's region (60–90c favourites); this variant is KILLED |
| 5 | Maker fees started 2026-08-20 | That entry is an NFL-combo maker-fee **exemption**; sports maker fees date from 2025 (inGame 2025-07-07, secondary) |
| 6 | Makers earned +2.6% to +7% | +7.3 is the gap; makers about +3.6%; +2.6% is Whelan's separate figure |
| 7 | Becker's weather maker gap means selling longshots | A role split is not a calibration sign |
| 8 | Cent rounding matters at $100 | Only for non-direct (FCM) members; the owner is OWNER_ATTESTED direct |
| 9 | Market leads NBM, so NBM updates are weak | Partly an intraday-information artefact; the clean evidence is the opening-hour gap; centres, not tails |
| 10 | A8 is a strong negative | Weak model and benchmark |
| 11 | Roosevelt is a proven public finding | Advocacy blog, so UNVERIFIED |
| 12 | A21 is a counter-indication | Vendor, so no evidential weight |
| 13 | Becker's sign flipped after Oct 2024 | Takers +2.0% through 2023; gap crossed zero 2024 Q2 |
| 14 | Maker>taker is a REPLICATED HISTORICAL RESULT | Replicated *descriptive* result; Becker and Le share a tape; Whelan's maker significance not replicated by day |
| 15 | "Near-perfect calibration at 30–240 min" | R² only, no CIs |

### Fee and rules facts, with dates

| Fact | Source and date | Status |
|---|---|---|
| Taker fee round-up(M·0.07·C·P(1−P)), M default 1; maker round-up(M·0.0175·C·P(1−P)), M default 0; "round up" = fee + position cost to a centicent | Kalshi Fee Schedule PDF "effective July 7, 2026", repo copy sha256 `c326a69f…`, received 2026-09-23 | VERIFIED-DOC for that version. Currency UNVERIFIED (live PDF HTTP 429 on 2026-09-29, 09-30, 10-08) |
| No settlement fee | same PDF | VERIFIED-DOC (July 7) |
| API fee types `quadratic`, `quadratic_with_maker_fees` (maker 0.25 × 0.07 = 0.0175), `quadratic_with_combo_maker_fees` (0.5), `flat` | docs.kalshi.com Get Series (no date) | VERIFIED-DOC |
| Trade fee rounded up to $0.000001; balances align to $0.0001 (direct) or $0.01 (non-direct); accumulator across an order's fills | docs.kalshi.com Fee Rounding (unchanged since the 2026-09-23 capture) | VERIFIED-DOC. The owner's account is OWNER_ATTESTED direct |
| KXNFLGAME non-standard row "1 1" | July 7 PDF | VERIFIED-DOC row; mapping unresolved (FEE_UNSUPPORTED) |
| **OP "Finding 1": the NFL fee blocker has primary evidence** | OP-R01, the same PDF read on 2026-10-08 | **NOT NEW, NOT RESOLVED.** See the reconciliation below. |
| KXMLBGAME non-standard row "Professional Baseball Game 1 1"; KXNBAGAME not on the non-standard list | repo extract `experiments/EXP-001-…/fee_verification/pdf_nonstandard_series.json` of the July 7 PDF | VERIFIED-DOC rows. Same unresolved gaps as KXNFLGAME, so UNVERIFIED for claims. KXNBAGAME's absence (general schedule: maker M 0) conflicts with the secondary report of NBA maker fees since 2025. |
| NHL multipliers | KXNHLGAME not proven standard (`fee_schedules.py`) | UNVERIFIED (outcomes excluded anyway) |
| 2026-08-20 changelog: independent NFL combos have no maker fee | docs.kalshi.com changelog | VERIFIED-DOC (an exemption, not a start date) |
| Sports maker fees: flat 0.25c before 2025-07-01, quadratic after | inGame 2025-07-07 | UNVERIFIED (secondary) |
| KXMVE RFQ: taker-equivalent fee for the party executing against a quoter unless an order rested more than 5 s; effective ≥ 2026-07-24 | CFTC filing 2026-07-12 | VERIFIED-DOC |
| Maker fee charged only on fill; cancel is free | help.kalshi.com Fees (modified 2026-04-19) | VERIFIED-DOC |
| LIP $1–$1,000 per market-day; Target Size 100–20,000; regular members eligible; MM-agreement, IB, FCM excluded; to 2027-01-01; paid after the period; < $1 not paid | CFTC 2026-07-15 (effective 2026-07-30); help pages | VERIFIED-DOC (terms can change) |
| VIP ends no earlier than 2026-10-13; cap $0.005/contract | CFTC 2026-08-04, 2026-09-28 | VERIFIED-DOC |
| Position Accountability Levels, e.g. 25,000 contracts per strike per member | CFTC 2024-11-14 | VERIFIED-DOC |
| Fractional contracts, 0.01 granularity; tick structures incl. deci-cent and tapered | Kalshi fixed-point migration (updated 2026-08-20); changelog | VERIFIED-DOC |
| Collateral return (opt-in, locks per event at the first order) | help.kalshi.com (2026-05-17) | VERIFIED-DOC |
| Economic contracts cease trading before the expected release | CFTC 2023-11-06 | VERIFIED-DOC |
| Weather: help page says daily settles on NWS CLI; captured KXHIGHNY rules name TWC; Kalshi `expiration_value` matched CLI on 739/739 KXHIGHNY events | help.kalshi.com; `docs/SETTLEMENT.md` | CONFLICT open (per series) |
| Get Trades fields include `taker_outcome_side`, `taker_book_side`, `count_fp`, `created_time`; one-minute candlesticks carry `yes_bid`/`yes_ask` OHLC | docs.kalshi.com Get Trades, Get Market Candlesticks (read by R6 on 2026-10-08) | VERIFIED-DOC (historical depth of availability UNVERIFIED) |
| Polymarket intl fee C·feeRate·p(1−p), sports 0.05 since 2026-07-10, makers never charged, rebates 15–25% | docs.polymarket.com fees and changelog | VERIFIED-DOC |
| Polymarket US taker θ 0.05 → 0.06 effective 2026-07-01; maker rebate −0.0125 | CFTC QCX filing 2026-07-07 | VERIFIED-DOC (repo `fee_schedules` still has `polymarket-us-taker-v1` θ 0.0695 for coefficient-matching markets from 2026-09-17; reconcile before any use) |

**Reconciliation of the owner packet's Finding 1 (NFL fees).**
- The packet reports that the Kalshi fee PDF is "effective July 7, 2026" and lists KXNFLGAME maker and taker
  multipliers of 1. The repo already holds that exact PDF (sha256 `c326a69f…`, received 2026-09-23) and the row.
- `docs/research/EXP002_FEE_VERIFICATION.md` keeps KXNFLGAME at **FEE_UNSUPPORTED** for four reasons the packet
  does not address:
  1. the mapping between the PDF's maker/taker multiplier columns and the API's single `fee_multiplier`;
  2. the series record changed on 2026-09-16, after the PDF date;
  3. event-level overrides and fee waivers, plus scheduled-change checks that need an API read;
  4. the maker-fee start date.
- **The only new fact** is that the PDF was readable on 2026-10-08 and was still dated July 7. That is partial
  evidence on the schedule's currency (reason 2's "is the July schedule still current" half). It does not touch
  reasons 1, 3 or 4, nor the 2026-09-16 series change itself.
- **The blocker is not resolved.**

The packet itself says its finding is "evidence to review through Market's existing fee owner, not authority to
rewrite all historical fee assumptions".

---

## (f) Economics

**Basis for every figure below.**
- Conventions: C = contracts, P = price paid, F = fee. All figures are per contract unless stated.
- Fees use the 2026-07-07 formula with multiplier 1. That is **unverified for every sports series**, so these are
  illustrations, not claims.
- **Unknown fees stay UNKNOWN.** For a series with an unverified multiplier, a result is reported gross with this
  band beside it, never as net profit.

### Payoff model (common to the top three)

- **Entry at an executable price:**
  - **taker:** the one-minute candle ask, conservatively the next minute's ask high (EXP-004, EXP-005);
  - **maker:** the bid level, valid only inside the bound framework (EXP-006).
- **Fee:**
  - taker F_t = round-up(0.07·C·P(1−P));
  - maker F_m = round-up(0.0175·C·P(1−P)), only where the series `fee_type` charges makers at the fill time.
- **Rounding:**
  - direct member: to $0.0001, so negligible;
  - non-direct: balances align to $0.01, which costs up to about 1c on a one-contract order (sensitivity only).
- **Settlement payout:** $1 if the bought side wins, else $0. There is no settlement fee. Payout states such as
  postponement, suspension, ties and fair-price fallback must be enumerated per series. NBA/MLB rules are not yet
  captured.
- **Net EV per contract:** EV = q − P − F, where q is the true win probability.
- **Conservative bounds:** the ask high, not the close; q taken at the lower end of the game- or event-clustered CI;
  F at multiplier 1 (or the series multiplier once verified).

### Break-even win probability by price (taker; and maker where charged)

| Price P | Taker fee F_t, direct | Break-even q, taker direct | Break-even q, taker non-direct 1-lot | Maker fee F_m | Fee as % of outlay (taker / maker) |
|---|---|---|---|---|---|
| 0.50 | 1.750c | 51.75% | 52.00% | 0.438c | 3.50% / 0.88% |
| 0.60 | 1.680c | 61.68% | 62.00% | 0.420c | 2.80% / 0.70% |
| 0.70 | 1.470c | 71.47% | 72.00% | 0.368c | 2.10% / 0.53% |
| 0.80 | 1.120c | 81.12% | 82.00% | 0.280c | 1.40% / 0.35% |
| 0.85 | 0.892c | 85.89% | 86.00% | 0.223c | 1.05% / 0.26% |
| 0.90 | 0.630c | 90.63% | 91.00% | 0.158c | 0.70% / 0.18% |
| 0.95 | 0.332c | 95.33% | 96.00% | 0.083c | 0.35% / 0.09% |
| 0.97 | 0.204c | 97.20% | 98.00% | 0.051c | 0.21% / 0.05% |
| 0.98 | 0.137c | 98.14% | 99.00% | 0.034c | 0.14% / 0.03% |
| 0.99 | 0.069c | 99.07% | 100.00% | 0.017c | 0.07% / 0.02% |

**The break-even edge after fees is q − P = F/1.** It is largest near 0.50. Above 0.90 the fee is small, but
**one 1c tick** (≈1.0–1.1% of outlay) is larger than the fee. Near 0.95–0.99, the **tick, not the fee, is the
binding cost**. That is why EXP-005 caps its band at 0.95.

### How a 98%-win-rate strategy loses money

EV = w − P − F. A 98% win rate says nothing about EV until P is known. Taker cases, direct-member fee:

| Case | Win rate w | Fill P | EV per contract |
|---|---|---|---|
| Backtest at the print | 98.0% | 0.97 | +0.80c |
| Same strategy, filled one tick worse (the ask was 0.98) | 98.0% | 0.98 | −0.14c |
| Same, true win rate 97.5% (a 0.5 pp miscalibration, inside any realistic CI) | 97.5% | 0.97 | +0.30c; at P = 0.98: −0.64c |
| Same, at 0.985 on a deci-cent tick | 98.0% | 0.985 | −0.60c |
| Non-direct account, one-contract orders at 0.97 | 98.0% | 0.97 | 0.00c |

**Cross-check with the owner packet's arithmetic.** The packet's 15 assertions were re-run by the coordinator
with identical output. They agree with this section:
- an ask of 0.52 has an unrounded taker fee of 0.017472;
- the purchase is +1.25c only if the *true* probability is 0.55, and it is negative at 0.535;
- a two-leg "complete set" at 0.48 + 0.49 = 0.97 nets −0.004965 after both taker fees. That is an illustration of
  family B's mechanism, not a Track B candidate;
- a 98%-win-rate entry at 99c loses.

**The tail.**
- One loss at 0.97 costs 97.2c, about 33 wins of 2.8c.
- Over 50 trades at a true 98%, P(two or more losses) ≈ 26%. Short samples routinely show 100% win rates for a
  strategy that is flat or negative.
- Detecting a 0.5 pp edge at p ≈ 0.98 (sd 0.14) needs about 4,800 independent events for 80% power at
  one-sided 5%.

### Capital-days and turnover for a $100 illustration

*ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL.* Depth is unknown for every top-3 market: candles have no size, and
no NBA/MLB/non-sports books are held. So every scenario is one contract per decision, and capacity is UNKNOWN.

| Candidate | Outlay per decision | Holding period | Settlement delay | Turnover limit | What the edge would have to be |
|---|---|---|---|---|---|
| TB-01 | about $0.61–$0.91 (one contract at 0.60–0.90 plus fee) | from the late threshold to game end, minutes to about an hour | UNKNOWN per series | games per day (NBA up to about 15 on a busy night; MLB about 15 in season), not capital: $100 is mostly idle | At one contract, a real 2c/contract edge over 15 games/day is **$0.30/day**. Reaching $1/day needs about 5 contracts per game at 2c, and depth evidence that does not exist yet. Capital-days per decision ≈ 0.9 × hours/24, so the return on capital *deployed* is high and the absolute dollars are tiny. |
| TB-05 | about $0.71–$0.96 | up to the horizon h (24 h, 6 h, 1 h) | UNKNOWN; economic markets close before the release and settle after it | qualifying events per day (UNKNOWN) and capital: at h = 24 h, $100 holds at most about 110 contracts at 0.90 | A 1% net edge on $100 deployed once a day is about $1/day **if** about 110 qualifying, fillable events exist per day. That is unknown and probably optimistic. |
| TB-03 | a resting bid reserves its cost while resting (collateral treatment for resting orders UNVERIFIED) | resting time plus hold to settlement | UNKNOWN | queue and fills, not capital | **Not computable for us.** The retrospective bound cannot estimate our fills (EXP-006). |

**Settlement delays lengthen capital-days without changing EV.** They matter only once capital binds, which for
TB-01 it does not at one contract.

---

## (g) Seven-day research program (independent of execution infrastructure)

**Days 0–7 if A2 (or the Becker substitute) is granted on day 1.**

| Day | Work | Output | Gate |
|---|---|---|---|
| 0 (2026-10-08) | Shortlist, DRAFT/QUEUED registration (EXP-004/005/006, done), owner packet | this document; packet | — |
| 1–3 (no grant needed) | **TB-23 stage 1:** an outcome-blinded, price-blind semantic audit, using public documentation only (contract rules pages and official EIA release notes).<br>- Sample: the first 20 eligible EIA-linked Kalshi contracts in chronological order.<br>- Two independent mappings: contract → statistic → units → reference period → release time → revision policy → exception payouts.<br>- No prices, no results, no vintage database.<br>- Public web pages only; no API.<br>- If a page shows a settled result, the exposure is recorded. | agreement, ambiguity and coverage counts; every audited case becomes development data | documentation reading under the Track B research authorization (packet item 6 asks the owner to confirm) |
| 1 | Owner rulings on packet items 1–3. If granted: sampled count first (requests, rows, coverage of 2025 NBA/MLB and non-sports, candle availability). Then the bounded read, hashes and source records. **Feature-only.** | provenance records; coverage report; no labels | A2, DATA_RIGHTS |
| 1–2 | Merge-ready trades/candles adapter (pure, offline over the downloaded files) on the harness lane's contracts; freeze EXP-004 thresholds from schedules and feature-only candle-time distributions; freeze the EXP-005 universe and create its evidence log | adapter PR (needs a merge ruling, packet item 7); frozen open decisions | code merge ruling |
| 3 | EXP-005 development block (logged LABEL use), at the ask, event-equal weight, with controls | RETROSPECTIVE EXPLORATORY report | log entry before the look |
| 4 | EXP-004 development block: positive control first, then the primary at the ask, then discriminating, sweep and negative controls | report | log |
| 5 | EXP-006 optimistic and pessimistic bounds | report; KILL or not | log |
| 6 | Validation blocks for any candidate not killed. Independent adversarial review of every report. | verdicts | — |
| 7 | Verdict per candidate (NOT_TESTABLE / FALSIFIED / INSUFFICIENT / PROVISIONALLY_INTERESTING), with hashes, scripts, sensitivity and the next prospective requirement. Slot request only for a survivor. | leading-hypothesis report | owner |

**If nothing is granted**, days 1–7 run only:
- the TB-23 semantic audit (above);
- the TB-24 fixture harness (harness lane);
- feature-only depth/spread/$100 ladder diagnostics on held books (needs A0, logged as FEATURE_INSPECTION);
- power and design work;
- tracking fee verification (packet item 3);
- review of the harness lane's PR.

There is no profit evidence on this path.

---

## (h) First edge readiness report (deliverable I): TB-05, the leading strategy

| Question | Answer |
|---|---|
| **Evidence** | Kalshi FLB is a replicated *descriptive* result: Whelan (event-clustered, through Apr 2025: >70c contracts earn small positive returns after the taker fee at last-trade prices) and Becker (trade-level, gross, YES-specific affirmative bias). Against: the 2025 slope roughly halved; event-equal weighting reverses the FLB on Polymarket; near 99c the edge is below one tick. R6: WEAKEN. **Class: PLAUSIBLE HYPOTHESIS. Our own evidence: none.** |
| **Missing data** | Kalshi trades plus one-minute candles plus settled markets for non-sports series closing on or after 2025-07-01, and per-series fee types. The Becker tape (to 2025-11-25, prints only) cannot score at quotes. |
| **Executability** | Taker at the next minute's ask high, one contract per event. Candles carry no size, so capacity is UNKNOWN. A slow participant can take a quoted ask; no queue is needed. |
| **Cost survival** | The taker fee is 1.47c at 0.70, 0.63c at 0.90 and 0.33c at 0.95 (multiplier 1, direct rounding). The published post-fee edge is small, a few percent at most, sd about 30%. It must survive the ask rather than the last trade, which is the decisive unknown. |
| **Capital** | Up to the horizon (≤24 h) plus settlement; at 0.90, $100 holds about 110 contracts; the qualifying event count per day is UNKNOWN (section f). |
| **Invalidators** | KILL (event-clustered upper bound ≤ 0, or point ≤ 0); ARTEFACT (trade-weight only); DECAYED (latest block ≤ 0); per-series fee multiplier > 1. |
| **Fastest legitimate next test** | Approval A2 for a frozen non-sports universe, with a sampled count first, then EXP-005's day-3 development block and its day-6 validation. About 3–4 working days after the grant, $0. |

**TB-01 (second)** needs the same grant restricted to NBA (Oct 2025–Feb 2026) and MLB 2025. Its decisive tests are
the positive control and the clock swap (EXP-004). The prior that it fails at the ask is now stronger, given R6
and OP-R04.

---

## (i) Failed, falsified and killed hypotheses (kept on record)

| Hypothesis | Verdict | Why | Source |
|---|---|---|---|
| Public NWP forecast (NBM/MOS) used as a taker against Kalshi temperature markets | **KILL / FALSIFIED (external)** | Market beats NBM and a 6-forecast blend at the opening hour; walk-forward taker −2.5c/contract after fees; a third, weaker negative. Do not re-test. Tails/dispersion at quotes remain open (TB-09). | Crosier 2026; k1hbles; myfirstcodeo; R6 §3.2 |
| Trade Kalshi CPI toward the Bloomberg consensus | **FALSIFIED (external)**; kept as a negative control | Kalshi beats the consensus on headline CPI | FEDS 2026-010 |
| Exploit post-release lag in economic markets | **IMPOSSIBLE by rule** | Contracts cease trading before the release | CFTC 2023-11-06 |
| Late-game sports maker bids at ≥90c in the final 10 minutes | **KILL** | Outside the reported region; adversely selected by construction (filled when the underdog scores) | R6 §1.3 |
| Combo/parlay overpricing as an edge for us | **KILL** | R ≈ 1 at 2–5 legs; naive quoting lost $174k; quoting not authorized; the requester pays the quoter's spread | R6 §6; LOPMM |
| Naive independent combo quoting | **FALSIFIED (external)** | Replay loss | LOPMM |
| Kalshi VIP volume-incentive harvesting | **EXPIRED / uneconomic** | Terminating no earlier than 2026-10-13; cap $0.005/contract | CFTC 2026-08-04, 2026-09-28 |
| Generic in-play underreaction to news | **Disfavoured** | Prices update swiftly and fully | Croxson & Reade |
| Generic FLB on Polymarket sports | **FALSIFIED on that venue** (does not transfer automatically) | Sports longshots +2.43% at event weight | Cardozo & Rivero-Wildemauwe |
| "Moving from taker to maker cuts P(loss) by 35.9 pp" | **UNVERIFIED claim, dropped** | Not found in the paper's text | R1 §0 |
| Weather bot "$1.8k profit" | **UNVERIFIED claim, dropped** | Contradicts its own paper-only disclaimer | R2 A9 |
| Copy-trading Polymarket leaderboard wallets | **INSUFFICIENT EVIDENCE** (negative lean) | 72% farming-flagged (vendor); paper copy results noise-level | CopyGrade; BallesJr |
| Overnight / time-of-day effects | **INSUFFICIENT EVIDENCE** | No credible primary source | R1 |
| Public attention / buzz mispricing in sportsbooks (OP-H23) | **FALSIFIED (external replication)** | A published result was traced to an erroneous extreme odds entry; a cleaned extension did not reproduce the profit | Clegg & Cartlidge (OP-R29) |
| Late-game sports bias bucketed by realized close | **Weakened further** | With actual game-end timing, calibration improves (exchange-hosted, private data; not a clean refutation) | Kagan & Baiocchi (OP-R04); R6 §1 |
| "Under $1 means arbitrage" for a two-leg complete set | **FALSE as a rule** | 0.48 + 0.49 = 0.97 nets −0.004965 after both taker fees (illustration) | OP analytical checks |
| Copying current wallet rankings backward into history | **INVALID design** | Full-sample `user_features` select on the future; `pnl_daily` holds sparse cumulative levels, not daily increments | OP-R08 (corrected dataset notes) |
| Prophet-Arena-Subset-3000 as a forecast log or holdout | **NOT USABLE for that** | No model predictions, no L2; its visible rows are now development examples | OP-R12/R13 |
| Football-Data as an automated source | **EXCLUDED (rights)** | Restricts automated, bot and AI use | OP-R26 |
| *Internal:* EXP-003 KXHIGHNY partition scan | DEVELOPMENT result, not a conclusion | Asks summed to 1.06, no surplus; EXP-003 PAUSED | EXP-003 results |
| *Internal:* EXP-002 gate v3 spread-noise rule | **Method FALSIFIED** | Worst false-pass rate 98% in validation; not a market hypothesis | `docs/research/EXP002_GATE_V3_VALIDATION.md` |

---

## (j) Traceability: proposed tracked research items (no issues were created)

The canonical research states map onto existing registry statuses, with no new status invented:

| Research state | Registry mapping |
|---|---|
| HYPOTHESIS | not registered, or DRAFT with `slot_status` QUEUED and no protocol work |
| UNDER INVESTIGATION | DRAFT with `slot_status` ACTIVE |
| AWAITING AUTHORIZED DATA | DRAFT/QUEUED with verdict ACCESS_BLOCKED in `[stopping]` |
| PREREGISTRATION READY | DRAFT with every decision field settled, not yet frozen |
| FALSIFIED | CONCLUDED_FAIL (or ABANDONED with the reason, if never preregistered) |
| INSUFFICIENT EVIDENCE | CONCLUDED_INCONCLUSIVE |
| PROVISIONALLY INTERESTING | DRAFT or PREREGISTERED with a positive retrospective exploratory result in the README log; no status change |
| REQUIRES PROSPECTIVE VALIDATION | PREREGISTERED → RUNNING on an untouched window |

| Item | Proposed state | Registry |
|---|---|---|
| TB-01 late-game favourite (EXP-004) | AWAITING AUTHORIZED DATA | DRAFT / QUEUED |
| TB-05 taker favourite FLB (EXP-005) | AWAITING AUTHORIZED DATA | DRAFT / QUEUED |
| TB-03 maker favourite bound (EXP-006) | AWAITING AUTHORIZED DATA | DRAFT / QUEUED |
| TB-02 pregame sports calibration | HYPOTHESIS | not registered |
| TB-09 weather tails, non-NY | HYPOTHESIS (sign unknown) | not registered |
| TB-10 determined-outcome sweep | HYPOTHESIS (needs IEM) | not registered |
| TB-08 LIP subsidy | HYPOTHESIS | not registered |
| TB-23 reference-period / vintage mismatch (OP-H02) | UNDER INVESTIGATION (documentation-only stage 1); AWAITING AUTHORIZED DATA for prices and vintages | not registered (not top-3) |
| TB-24 forecast-to-position conversion (OP-H03) | AWAITING AUTHORIZED DATA (genuine prior forecasts); fixture harness in the harness lane | not registered |
| OP-H01 fresh sportsbook consensus vs Kalshi ask | owner choice (packet item 8); belongs to EXP-002 | EXP-002 (family A) |
| Buzz reversal (OP-H23) | FALSIFIED (external) | not registered |
| Forecast-as-taker weather; CPI toward consensus; ≥90c late maker; combos as an edge | FALSIFIED (external or adversarial) | not registered; recorded here |
