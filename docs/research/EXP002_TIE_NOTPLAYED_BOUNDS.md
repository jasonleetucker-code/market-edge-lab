# EXP-002: a sourced NFL tie and not-played count behind `t_max` and `u_max`

**Status:** research for freeze blocker 2 (`EXP002_FREEZE_PROPOSAL.md` §5). 2026-09-29, Writer A, from `main` at
`2f2d9c4`. **Recommendations are PROPOSED only.** Nothing is frozen. `protocol.toml`, the freeze proposal (never
edited in place), the code and EXP-002 data are unchanged.

**No EXP-002 capture (book, odds or pair) was viewed.** The public settlements and NFL.com standings read here
cover 2026 weeks 1–3, so they include DEVELOPMENT-pilot game outcomes (kickoffs from 2026-09-27). They were read
in aggregate for non-binary settlements and tie counts only. No evaluation-window game had kicked off. This is
recorded as evidence-use event `eu-622b393fce9cb7a4da0e105a1d9b13bc` (LABEL_RESULT_INSPECTION, DEVELOPMENT,
window 2026-09-27T00:00Z to 2026-09-29T00:15Z). The pilot games contribute 0 events to either count.

The only Kalshi data read is public market metadata: listing times and final settlements of KXNFLGAME markets.
The owner decides at the freeze review (2026-10-22).

Status words used in this document:
- **VERIFIED**: checked against a cited primary or official source, fetched and hashed below;
- **UNVERIFIED**: secondary or inferred;
- **PROPOSED**: a recommendation.

## Bottom line

| | Evidence | Count | Pooled rate | Exact one-sided Poisson upper bound (90 / 95 / 99%) |
|---|---|---|---|---|
| **Ties**, 10-minute OT era 2017–2025 | NFL.com standings (VERIFIED) | **8** in 2,383 completed games | 0.34% | 0.55 / 0.61 / 0.73% |
| Ties, 2025+ rule (both teams possess) | NFL.com + Kalshi settlement (VERIFIED) | 1 in 320 | 0.31% | 1.22 / 1.48 / 2.07% (sample too small to bound tightly) |
| **Fallback-F events**, 2017–2025, conservative | NFL.com / club sites (VERIFIED), listing lead from Kalshi metadata (VERIFIED) | **14** in 2,384 scheduled games | 0.59% | 0.84 / 0.92 / 1.07% |
| F events excluding 2020 | same | 5 in 2,128 | 0.23% | 0.44 / 0.49 / 0.62% |
| F events excluding 2020 and 2021 (both COVID seasons) | same | 2 in 1,856 | 0.11% | 0.29 / 0.34 / 0.45% |
| F events in 2020 alone | same | 9 in 256 | 3.5% | 5.5 / 6.1 / 7.3% |
| Kalshi KXNFLGAME 2025 regular season, actual settlements | Kalshi public API (VERIFIED) | **0** fallback, 1 tie ($0.50) in 272 | 0% | 0.85 / 1.10 / 1.69% |

**PROPOSED:**
- `t_max = 0.01` (keep). It sits above the 99% bound of the 10-minute-OT era (0.73%). Register `t_max = 0.02` as
  a sensitivity, for the small 2025+ rule sample and per-game heterogeneity.
- `u_max = 0.01` (**change** from 0.005). The proposal's `u_max = 0.005` is **not supported** by the full
  2017–2025 record: 14 events, 95% upper 0.92%. It is supported only if pandemic seasons are excluded (0.49% at
  95% without 2020; 0.45% at 99% without 2020–21). Excluding them is a regime assumption that cannot be verified
  ex ante. Register `u_max = 0.005` as a sensitivity.
- **Effect on E1:** raising `u_max` from 0.005 to 0.01 lowers `c_low` by `0.005·p`, at most 0.5¢, about 0.25¢ at
  p = 0.5. Only T-6h entries whose margin `c_low − ask` falls in `[θ, θ + 0.005·p)` drop out. The count needs a
  label-free production run (§5). It was not run here.

## 1. The contract states the bounds cover (VERIFIED)

Contract terms (FOOTBALLGAMEWIN, `rules_evidence/FOOTBALLGAMEWIN_contract_terms_read-2026-09-25.pdf`, Venue Change clause; A.D agrees). The freeze proposal v1 §2 wording 'a venue or home/away change' is broader than the terms; freeze proposal v2 should correct it.
- **A tie after overtime** pays `$1/(tied teams)`, rounded down, which is **$0.50**.
- **The fallback F:** Kalshi pays "the last fair price" (or "last fair market price"), a discretionary
  `F ∈ [0, 1]`, when a game is:
  - (a) postponed and not started within 48 hours of the originally scheduled date;
  - (b) suspended or abandoned after kickoff, before 55 minutes of play, and not resumed within 48 hours (unless
    declared final);
  - (c) forfeited before kickoff;
  - (d) moved outside the same scheduling week, or with the home/away designation reversed;
  - (e) affected by a pre-game disqualification or ineligibility.
- **Not F:** a venue change that keeps the home/away designation, with the game played within 48 hours, resolves
  normally. So does a postponement that starts within 48 hours.

`V = (1 − t − u)·p + 0.50·t + u·F` (`sports_evidence.tie_adjusted_interval`, CURRENT) gives:
- `c_low = p·(1 − u)` for `p ≤ 0.5`;
- `c_low = p − t·(p − 0.5) − u·p` for `p > 0.5`.

The derivatives are `∂V/∂t = 0.5 − p` (magnitude ≤ 0.5) and `∂V/∂u = F − p` (magnitude ≤ 1). **So `t_max` moves
`c_low` by at most `0.5·t_max`, and `u_max` by at most `u_max·p ≤ u_max`.** With θ = 1¢, `u_max = 0.01` costs up
to one tick of `c_low`, and `t_max = 0.01` costs up to half a tick.

## 2. Ties

### 2.1 The overtime rules (VERIFIED)

- **10-minute regular-season overtime from 2017.** NFL.com, "NFL owners approve shortening overtime to 10 minutes"
  (published 2017-05-23): the change was approved at the Spring League Meeting "in the preseason and regular season
  from 15 to 10 minutes", effective for the 2017 season.
  - NFL Research, quoted there: 83 overtime games in 2012–2016, with 5 ties; a 10-minute overtime would have
    produced **16 ties in those 1,280 games (1.25%)**. That is a static counterfactual that assumes no change in
    play (§2.3).
- **Both teams possess in regular-season overtime from 2025.** NFL Communications, "Approved 2025 Playing Rules,
  Bylaws and Resolutions" (Apr 01, 2025, NFL Annual Meeting, Palm Beach), item 2-A: it "aligns the postseason and
  regular season overtime rules by granting both teams an opportunity to possess the ball regardless of the
  outcome of the first possession, subject to a 10-minute overtime period in the regular season."
  - NFL.com (2025-07-30) confirms that the regular season keeps 10 minutes.

The NFL Football Operations rules pages (`operations.nfl.com/the-rules/...`) returned a script-rendered shell with
no rule text to a plain HTTP fetch (identical 402,709-byte pages for both URLs). So the adoption dates above come
from NFL.com and NFL Communications, not from Football Operations.

### 2.2 The official count (VERIFIED)

The count comes from the NFL.com standings, `https://www.nfl.com/standings/league/<year>/reg`, fetched by the
coordinator on 2026-09-29 at about 17:50Z. I re-parsed the T column from the raw HTML (sha256 in §6). WebFetch
summaries misreported 2020 and 2018, so only the raw HTML parse is used.

| Season | Games completed (W+L+T)/2 | Ties | Tied teams (standings T column) |
|---|---|---|---|
| 2017 | 256 | 0 | — |
| 2018 | 256 | 2 | GB, MIN, CLE, PIT |
| 2019 | 256 | 1 | DET, ARI |
| 2020 | 256 | 1 | CIN, PHI |
| 2021 | 272 | 1 | DET, PIT |
| 2022 | 271 (BUF@CIN no contest) | 2 | HOU, IND, WAS, NYG |
| 2023 | 272 | 0 | — |
| 2024 | 272 | 0 | — |
| 2025 | 272 | 1 | DAL, GB |
| **2017–2025** | **2,383** | **8** | |
| 2026 (to 2026-09-29) | 48 | 0 | — |

**Pairings.** For 2018 and 2022, which teams tied each other (PIT–CLE and GB–MIN; IND–HOU and WAS–NYG) is
secondary (Wikipedia, "List of NFL tied games"; UNVERIFIED). Only the counts are needed.

**Cross-check on the 2025 tie.** The public Kalshi API shows `KXNFLGAME-25SEP28GBDAL` settled `scalar`, 0.5000 on
both team markets (VERIFIED, §6). This is the contract's tie rule applied in production.

The rates below use completed games for ties and scheduled games for F.

| Era | Ties / games | Rate | 90% | 95% | 99% | two-sided 95% (97.5% one-sided) |
|---|---|---|---|---|---|---|
| 2017–2025 | 8 / 2,383 | 0.336% | 0.545% | 0.606% | 0.730% | 0.661% (15.76 / 2,383) |
| 2017–2026 to date | 8 / 2,431 | 0.329% | 0.535% | 0.594% | 0.716% | |
| 2025+ (new OT possession rule) | 1 / 320 | 0.31% | 1.22% | 1.48% | 2.07% | |

Exact Poisson upper limits for k = 8: μ = 12.99 / 14.43 / 17.40 (90 / 95 / 99%, one-sided). The coordinator's note
quoted 15.51 for "95%". The exact one-sided 95% limit is 14.43, and the two-sided (97.5%) limit is 15.76. The
conclusions do not change.

### 2.3 Heterogeneity and published estimates

- **The tie rate given overtime (secondary, UNVERIFIED):**
  - inpredictable.com, "What's a tie worth in the NFL?" (2021-10): 4 ties in 56 overtime games from 2017 (7.1%),
    against 5 in 83 (6.0%) for 2012–16;
  - theScore, "Inside the NFL tie's sudden disappearance": 5 ties in 64 overtime games (7.8%).

  So a per-game tie probability is about `P(OT) × 7%`. The league-wide P(OT) is about 5%, which gives the pooled
  ≈ 0.35%.
- **A near-pick'em, low-total game** is more likely to reach overtime. If P(OT) were 8–10% for such a game,
  `t ≈ 0.6–0.7%` at 7% per overtime. Under the NFL Research static counterfactual (19% of overtimes tied), it
  would be up to ~1.9%.
  - No official per-game tie model was found.
  - US books do not normally list an NFL three-way moneyline (secondary sources say a tie is usually a push on the
    two-way line). **No published sportsbook tie price was found: UNKNOWN.**
- **Why heterogeneity matters little here.** The tie term lowers `c_low` by `t·max(p − 0.5, 0)`, which is zero
  at a pick'em. The games whose t might exceed 1% are exactly those with `p ≈ 0.5`. At `p − 0.5 = 0.1`, even
  `t = 2%` lowers `c_low` by 0.2¢. At a heavy favourite (`p ≥ 0.75`), the tie term lowers `c_low` by between
  `0.25·t` and `0.5·t`, but that is where t is smallest.
- **The 2025 both-possession rule** could change the tie rate in either direction (for example, a team matching
  an opening touchdown may go for two). One season (1 tie in 272) cannot show it. This is why `t_max = 0.02` is
  proposed as a registered sensitivity.

## 3. Not played: every 2017+ regular-season game that could trigger F

### 3.1 When does a change trigger F? Kalshi's listing lead (VERIFIED from public metadata)

A game changed **before** its KXNFLGAME market is listed is simply listed at its new date. Only a change
**after** listing can trigger F. KXNFLGAME listing times were measured from the public API (`open_time` per
market; 430 events, 2025-07-31 to 2026-09-28; §6). The lead time is from listing to about 13:00 ET on the game
date:

| Season / weeks | Listing pattern (observed) | Lead before kickoff |
|---|---|---|
| 2025 weeks 1–2 | listed 2025-05-20 and 2025-06-30 | 73–111 days |
| 2025 weeks 3–18 | one batch per week | **min 5.6 days; weekly batch spans about 6–14 days** (the median over all 2025 regular-season events is 11.9 d) |
| 2026 weeks 1–3 | 2026-05-15, 2026-08-25, 2026-09-15 | 118–122 d, 23–27 d, 9–13 d |

**Classification rule** (conservative: "when unsure, count it"):
- **After listing (F):** the change was announced ≤ 5.6 days before the original kickoff, or in weeks 1–2 at any
  time in season.
- **Uncertain (counted as F):** announced 6–14 days before.
- **Before listing (not F):** announced more than 14 days before, in week 3 or later.

The 2017–2022 events predate KXNFLGAME. This applies today's listing practice counterfactually.

### 3.2 The events

Announcement times are the NFL.com or club publication times (UTC) of the cited official pages. Sources S1–S12 are
in §6.

| # | Season, week | Game | What happened | Announced (days before original kickoff) | Trigger | Class | Count as F |
|---|---|---|---|---|---|---|---|
| 1 | 2017 wk 1 | TB–MIA (Sep 10) | Hurricane Irma: will not be played in Miami (S11, 2017-09-05); moved to Nov 19, week 11 (S1, 2017-09-06) | 4–5 d, week 1 | (a) | after listing | **1** |
| 2 | 2018 wk 11 | KC @ LAR (Nov 19) | Moved from Estadio Azteca to the LA Memorial Coliseum, same date, Rams still home (S10, 2018-11-13) | 6 d | venue only, same designation, same date | not F | 0 |
| 3 | 2020 wk 4 | PIT–TEN (Oct 4) | COVID: postponed (S12, 2020-10-01); moved to Oct 25 (S2, 2020-10-02) | 3 d | (a) | after | **1** |
| 4 | 2020 wk 4 | NE @ KC (Oct 4 16:25 ET) | To Mon Oct 5 19:05 ET, 26.7 h later (secondary: Wikipedia 2020 season) | — | started within 48 h | not F | 0 |
| 5 | 2020 wk 5 | DEN @ NE (Oct 11) | To Mon Oct 12 (S3, 2020-10-09 00:37Z), then to Oct 18 (S4, 2020-10-11) | 3–0 d | (a) | after | **1** |
| 6 | 2020 wk 5 | BUF @ TEN (Sun Oct 11 13:00 ET) | To Tue Oct 13 19:00 ET, 54 h later (S3, S5, 2020-10-09 00:37Z) | 3 d | (a), > 48 h | after | **1** |
| 7 | 2020 wk 6 | KC @ BUF (Thu Oct 15 20:20 ET) | Possible move flagged (S3, S5, 2020-10-09); moved to Mon Oct 19 17:00 ET (S4, 2020-10-11) | 7 d (flagged), 4 d (moved) | (a), ≈ 93 h | after | **1** |
| 8 | 2020 wk 6 | NYJ @ LAC (Oct 18) | Moved to week 11, Nov 22 (S4, 2020-10-11) | 7 d | (a)/(d) | uncertain | **1** |
| 9 | 2020 wk 6 | MIA @ DEN (Oct 18) | Moved to week 11, Nov 22 (S4) | 7 d | (a)/(d) | uncertain | **1** |
| 10 | 2020 wk 7 | LAC @ MIA (Oct 25) | Moved to week 10, Nov 15 (S4) | 14 d | (a)/(d) | uncertain (at the edge) | **1** |
| 11 | 2020 wk 7 | PIT @ BAL (Oct 25) | Moved to week 8, Nov 1 (S2, 2020-10-02) | 23 d | (a) | before listing | 0 |
| 12 | 2020 wk 8 | JAX @ LAC (Nov 1) | Moved earlier, to week 7, Oct 25 (S4) | 21 d | (d) | before | 0 |
| 13 | 2020 wk 10 | NYJ @ MIA (Nov 15) | Moved earlier, to week 6, Oct 18 (S4) | 35 d | (d) | before | 0 |
| 14 | 2020 wk 11 | LAC @ DEN (Nov 22) | Moved earlier, to week 8, Nov 1 (S4) | 42 d | (d) | before | 0 |
| 15 | 2020 wk 12 | BAL @ PIT (Thu Nov 26) | Postponed three times, to Wed Dec 2 15:40 ET (S6, 2020-11-30; first postponement about 2020-11-24, secondary) | ≈ 2 d | (a) | after | **1** |
| 16 | 2020 wk 13 | WAS @ PIT (Sun Dec 6 13:00 ET) | To Mon Dec 7 17:00 ET, 28 h later (S6) | 6 d | started within 48 h | not F | 0 |
| 17 | 2020 wk 13 | DAL @ BAL (Thu Dec 3) | To Tue Dec 8 (S6 2020-11-30; S7 dallascowboys.com 2020-11-30) | 3 d | (a) | after | **1** |
| 18 | 2020 wk 13 and 14 | BUF @ SF (Dec 7), WAS @ SF (Dec 13) | 49ers home games moved to Glendale, AZ, SF still home, same dates (secondary: Wikipedia list) | — | venue only | not F | 0 |
| 19 | 2021 wk 1 | GB @ NO (Sep 12) | Hurricane Ida: moved to Jacksonville, NO still home, same date (secondary) | — | venue only | not F | 0 |
| 20 | 2021 wk 15 | LV @ CLE (Sat Dec 18 16:30 ET) | To Mon Dec 20 17:00 ET, 48.5 h later (S8, 2021-12-17) | 1 d | (a): just past 48 h, and "48 hours of its originally scheduled **date**" is ambiguous; counted | after | **1** |
| 21 | 2021 wk 15 | WAS @ PHI (Sun Dec 19 13:00 ET) | To Tue Dec 21 19:00 ET, 54 h later (S8) | 2 d | (a) | after | **1** |
| 22 | 2021 wk 15 | SEA @ LAR (Sun Dec 19 16:25 ET) | To Tue Dec 21 19:00 ET, 50.6 h later (S8) | 2 d | (a) | after | **1** |
| 23 | 2022 wk 17 | BUF @ CIN (Mon Jan 2, 2023) | Suspended with 5:58 left in the 1st quarter; not resumed, cancelled, no contest (S9, 2023-01-06) | in game | (b) | after | **1** |
| 24 | 2022 wk 11 | CLE @ BUF (Nov 20) | Winter storm: moved to Ford Field, Detroit, BUF still home, same date (secondary) | 3 d | venue only | not F | 0 |
| — | 2019, 2023, 2024, 2025, 2026 to date | none found | no regular-season postponement, cancellation or relocation outside the week found (Wikipedia season pages and list, secondary; **2025 corroborated by Kalshi: 272 games (544 markets), none settled at a fair price**) | | | | 0 |

**Two further categories.** Forfeits and pre-game disqualifications: none in 2017–2026 (none reported by any
source above; UNVERIFIED as an exhaustive negative). Saturday moves announced at schedule release (weeks 15–16 each
year) are planned options within 48 h and the same week, so they are not F.

**Totals, 2017–2025:**
- **14** counted as F (conservative): 11 certain, after listing, and 3 uncertain (#8, #9, #10);
- 2017: 1; 2020: 9; 2021: 3; 2022: 1; all other seasons: 0;
- 2026 to date: 0 in 48 games.

| Era | F events / scheduled games | Rate | 90% | 95% | 99% |
|---|---|---|---|---|---|
| 2017–2025, conservative | 14 / 2,384 | 0.587% | 0.844% | 0.918% | 1.067% |
| 2017–2025, certain only | 11 / 2,384 | 0.461% | 0.696% | 0.764% | 0.901% |
| 2017–2025, if every moved game counted (+#11–14) | 18 / 2,384 | 0.755% | | | |
| 2020 only | 9 / 256 | 3.516% | 5.549% | 6.135% | 7.337% |
| excluding 2020 | 5 / 2,128 | 0.235% | 0.436% | 0.494% | 0.616% |
| excluding 2020 and 2021 | 2 / 1,856 | 0.108% | 0.287% | 0.339% | 0.453% |
| 2023–2026 to date | 0 / 864 | 0% | 0.267% | 0.347% | 0.533% |
| Kalshi-listed 2025 regular season (actual settlements) | 0 / 272 | 0% | 0.847% | 1.101% | 1.693% |

### 3.3 Reading the numbers

- Non-standard resolutions cluster. Nine of the 14 are in one pandemic season, and three more are in one Omicron
  week. A per-game Poisson bound over pooled seasons understates the risk that a whole season is disrupted.
- The EXP-002 window (Oct–Dec 2026) is not in a pandemic. But a frozen bound must be true **ex ante** for the
  window, and "no pandemic-like disruption" cannot be verified in advance.
- `u` also absorbs the unresolved after-55-minutes conflict (freeze proposal §3 row 2) and the unknown size of F.
  Neither changes the count, because F ∈ [0, 1] is already the widest range.

## 4. PROPOSED bounds

| Parameter | PROPOSED | Rationale | Registered sensitivity |
|---|---|---|---|
| `t_max` | **0.01** (unchanged) | Above the exact 99% bound of the 10-minute-OT era (0.73%). Per-game heterogeneity (near-pick'em games up to about 1–2%) lowers `c_low` by `t·max(p − 0.5, 0)`, which is small exactly where t is large (§2.3). | `t_max = 0.02` (the new-OT-rule era is 1/320; its 95% bound is 1.48%) |
| `u_max` | **0.01** (**changed** from 0.005) | The full 2017–2025 record, pandemic seasons included, gives 14/2,384 events; the 95% bound is 0.92% and the 99% bound 1.07%. `0.005` holds only when 2020 (and 2021) are excluded, a regime assumption that cannot be verified ex ante. | `u_max = 0.005` (the non-pandemic-era bound) |

**The two bounds are set at different confidence levels.** `t_max = 0.01` clears the 99% bound (0.73%).
`u_max = 0.01` clears the 95% bound but not the 99% bound (1.07%); unlike `t_max`, it is set at the 95% level.
Choosing 99% for both would give `u_max ≈ 0.011`.

At one level (99%), `0.005` fails even without 2020: the ex-2020 99% bound is 0.616%. It passes at 99% only when
2021 is excluded too (0.453%). At 95%, the ex-2020 bound is 0.494%, so 0.005 passes only just.

Both remain ex-ante, frozen with the protocol, and never fitted to outcomes.

`t_max + u_max = 0.02 ≤ 1`, which is valid for `tie_adjusted_interval`.

## 5. Effect on E1 (analytic; no EXP-002 capture viewed)

E1 enters when `c_low − ask ≥ θ` (θ = 1¢). Moving `u_max` from 0.005 to 0.01 changes `c_low` by `−0.005·p`:

| p (consensus, the contract's own side) | Δc_low | Plus the tie term at t_max = 0.01 (vs t = 0) |
|---|---|---|
| 0.30 | −0.15¢ | 0 (t does not lower c_low when p ≤ 0.5) |
| 0.50 | −0.25¢ | 0 |
| 0.60 | −0.30¢ | −0.10¢ |
| 0.80 | −0.40¢ | −0.30¢ |

Only T-6h opportunities whose margin lies in `[θ, θ + 0.005·p)` are lost. Asks are on a 1¢ grid while `c_low` is
continuous, so this band is under half a tick wide.

The count is label-free: E1 entry uses T-6h information only (`EXP002_E1_ENDPOINT.md`). The coordinator can obtain
it on production by running the E1 endpoint **without** `--with-results`, once with
`--e1-tie-bound 0.01 --e1-postponement-bound 0.005` and once with `... 0.01 ... 0.01`, and reporting the two entry
counts. **Not run here:** this task has no production access, and no EXP-002 capture was viewed.

## 6. Sources (fetched 2026-09-29, UTC)

Raw pages were saved to the session scratchpad and are **not committed**: third-party pages of about 200–700 KB
each. Their sha256 is recorded below.

The standings hashes reproduce on re-fetch. The news pages S1–S12 are dynamic: a re-fetch returns different
bytes, so they are identified by URL, `datePublished` and the facts quoted in §3.2.

**NFL.com standings (coordinator fetch, about 17:50Z; hashes re-verified by me):**
`https://www.nfl.com/standings/league/<year>/reg`

| Year | sha256 |
|---|---|
| 2017 | `53534edd216abd6993d93c1afb2ee277e862d37000fa71d74326256aa8e6b230` |
| 2018 | `37ef8bf3ed80468aa94f4f759f8b5c58fe057062f721b3b678f4a9f079352ee8` |
| 2019 | `7926e7af30911aa1af0f526b32af41932e567f735acb6120e47eb66f66ef1731` |
| 2020 | `0427a988080a7cd993de66fb99bbc6a5dbdbecb4e83bac9516a4265796950a98` |
| 2021 | `aa5e3d795a40a281557b8f311db19d394269ecc636b5d1d9df0e973c51fac9ad` |
| 2022 | `d85303542bedc94ba60591d8782d88a914200c93926665ba5decc7648ff39c94` |
| 2023 | `def59f6e810a9ef32b669d949b6c68fdfac7c3d87f25edfd5f7b20ad3942b28c` |
| 2024 | `37dab24810bb8e8155f4a35d3636851d7456e3020c8bc42b80b1a62f9e9fc703` |
| 2025 | `18e0cfaa74dc60a83682a9c05d7f354e6f3720447fea5ffeaa7f566d1cfc59b2` |
| 2026 | `387a03a7aebcc2311a3135e11f411fd87bb8abff5f46e845f19232fcb657c44b` |

**Overtime rules (18:25Z):**

| Page | Published | sha256 |
|---|---|---|
| NFL.com, `https://www.nfl.com/news/nfl-owners-approve-shortening-overtime-to-10-minutes-0ap3000000810488` | 2017-05-23 | `d763663478fcceb0d5296023abb14210f128adb59e0c6532d362704d288c28ee` |
| NFL Communications, `https://media.nfl.com/football-information/2025/approved-2025-playing-rules--bylaws-and-resolutions` | Apr 01, 2025 | `978194bd8994ecd1e4cfee11013a19fdc778e2931cf5ba0236ae8165becbc2dc` |
| NFL.com, `https://www.nfl.com/news/looking-at-tweak-to-kickoff-other-rules-changes-for-2025-season` | 2025-07-30 | `6041295c4f334540cd196a3a90404818ebf336a24e5ac4629dc39026423294d7` |

**Game changes (18:29–18:30Z):**

| Id | URL | Published (UTC) | sha256 |
|---|---|---|---|
| S1 | https://www.nfl.com/news/buccaneers-dolphins-game-rescheduled-for-week-11-0ap3000000839621 | 2017-09-06 06:43 | `d9d774ad681cef3e8ce7c77fc04fc12b2b7716a0ce25d7d5345b72c822b9827d` |
| S2 | https://www.nfl.com/news/postponed-steelers-titans-game-rescheduled-for-week-7 | 2020-10-02 16:23 | `90e4702619149a9532399ae37ece5a0f510af4f677d1c31f843ec36cb2aca6d1` |
| S3 | https://www.nfl.com/news/nfl-announces-schedule-changes-for-upcoming-broncos-patriots-bills-titans-games | 2020-10-09 00:37 | `30548316ce23af1c2f22f6297acb5baa6949c377dfeb8aaf8c63ad1bc819371e` |
| S4 | https://www.nfl.com/news/nfl-announces-multiple-schedule-changes-moves-broncos-patriots-to-week-6 | 2020-10-11 18:56 | `f12563a219aaedbb01b04a3acc2748fae8c24610707928fbdef2e7c75dd38b17` |
| S5 | https://www.buffalobills.com/news/nfl-announces-schedule-changes-for-bills-next-two-games | 2020-10-09 00:39 | `cf99bf440781b782e64ea29cf00fa900dd5c44ada3759353822ffc4721bb50fe` |
| S6 | https://www.nfl.com/news/ravens-steelers-game-moved-to-wednesday | 2020-11-30 23:40 | `8fa6db9875acffe40b9819141ce81fd6dc8d1f43432f0a590a659affe0183847` |
| S7 | https://www.dallascowboys.com/news/cowboys-ravens-moved-again-to-tues-dec-8 | 2020-12-01 00:30 | `fbcec7725d562e02a0bd5c02ba1d1ee890641feb8c8f476f670a41c8e5928b03` |
| S8 | https://www.nfl.com/news/nfl-covid-week-15-game-postponement | 2021-12-17 20:17 | `4768c9b8dd14e975ab426a05949cef2f59edcf6705d44234fd1c3dd9d32cc036` |
| S9 | https://www.nfl.com/news/week-17-buffalo-cincinnati-game-will-not-be-resumed-neutral-afc-championship-gam | 2023-01-06 02:18 | `7bf1a1953319a809aea10adb3d533ea4ecdf27ba291a53d5df640a59b5a09cd3` |
| S10 | https://www.nfl.com/news/chiefs-rams-game-moved-from-mexico-city-to-los-angeles-0ap3000000988000 | 2018-11-13 14:10 | `0525190f3fa1b3c72e2dca2d332c1614eb6e86f1a3adb11c52e50e58539dbab6` |
| S11 | https://www.nfl.com/news/bucs-fins-will-not-be-played-in-miami-due-to-irma-0ap3000000839466 | 2017-09-05 13:34 | `9d6ec5db278306ff5d68ac352cbb3ece3bda06f7cbede1373be181b6910c6c8e` |
| S12 | https://www.nfl.com/news/steelers-titans-game-postponed-after-additional-titans-player-personnel-test-pos | 2020-10-01 13:37 | `f8dcc3227c72ae3879b752f3731a5675ab47bbc9ac44885ebdb504dd73bbbc8d` |

**Kalshi public API (read-only, unauthenticated, 6 GETs, 18:26–18:27Z):**

| Request | sha256 |
|---|---|
| `GET https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNFLGAME&status=settled&limit=1000` (194 markets) | `dcba2382f624222fa473a27523e638762c0339d25c02442f08a35193284d8cfe` |
| `GET .../events?series_ticker=KXNFLGAME&status=settled&with_nested_markets=true&limit=200`, page 1 | `83608a50a1ab77d65ce179103d8e5dc7aeccc63701bd7b61e318b2852e8087d0` |
| same, page 2 | `01f7441d683d21e24ae5b7d04e0214b2a9a9666391b5715c48714d5fccca9c3b` |
| same, page 3 (429 events in all; 2025 events carry no nested markets) | `e5c4dad120d2f30c2a175361cdd58618ef76ad6c2a12c8c51a427c2d1874427f` |
| `GET .../historical/markets?series_ticker=KXNFLGAME&limit=1000` (666 markets, the 2025–26 season) | `efd4e6411d10765ef590732a46e4f3625a0ec5481b82ae122c6753d33ccca79d` |

A seventh probe, `markets?...&max_close_ts=` (0 markets), is not used.

Fields used: `event_ticker` (the original ET game date), `open_time`, `result`, `settlement_value_dollars`.
Across 430 events and 860 markets, the only non-binary settlements are ties at 0.5000:
- 2025 regular season: GB–DAL;
- preseason: 2025 LV–SEA, MIA–CHI and JAC–NO; 2026 IND–NE and SEA–KC.

There is no fair-price settlement.

**Secondary (corroboration only; UNVERIFIED):**

| Source | sha256 |
|---|---|
| Wikipedia wikitext, `https://en.wikipedia.org/w/index.php?title=<year>_NFL_season&action=raw`, 2017–2026 (18:28Z); used 2020 / 2021 / 2022 | 2020 `2e496dce382de397248ac747b44bf6e24d92d0162947fa6661c2980f92737bdf` / 2021 `615c320e19e87f510f052ca5ba6fc5817afeafa164452ae24fc17b01f19f604e` / 2022 `6e5d737e2ba1a1b1dd6a6ecbed6f92fded5095e9c616c31a45a0d40dc48efd6c` |
| Wikipedia, "List of canceled and rescheduled NFL games" (18:29Z) | `69523c1bc88fd6bcc464cbbd63773bfadcd3fe614f99acab82c0fcb4bc753d34` |
| inpredictable.com, "What's a tie worth in the NFL?" (18:31Z) | `18f7da85f34854f409221286ae5faa8d121537071e0d8291efefe50769cbccd5` |
| theScore, `https://www.thescore.com/nfl/news/3155047` | `24583f885893d9dda7225268bda0fd2d11e96339ea75eae68b9fb7c13d26e155` |

The NFL.com standings HTML is not committed. It is 10 files of about 218 KB of third-party markup; the hashes above
identify it.

## 7. Caveats

- **The listing-lead rule is counterfactual for 2017–2022.** KXNFLGAME did not exist then, and Kalshi's batch
  timing can change. Uncertain cases are counted.
- **The "48 hours of its originally scheduled date" clause.** Whether it is measured from the kickoff time or the
  end of the original date is UNVERIFIED.
  - #6, #20, #21 and #22 are 48.5–54 h from kickoff but 41–43 h from the end of the original date. They are
    counted either way. Under a date-end reading the certain count would fall from 11 to 7.
  - #4 (+26.7 h) is within 48 h under both readings.
- **Kalshi's actual handling of a post-listing reschedule has never been observed** for KXNFLGAME. There were no
  such events in 2025–26. It is assumed to follow the terms.
- **The exhaustive negative for 2019, 2023, 2024, 2025 and 2026 rests on secondary season pages.** For 2025 it is
  corroborated by the absence of any fair-price settlement among the 272 KXNFLGAME games (544 markets).
- **Poisson with a constant rate** understates clustered risk (a pandemic season). That is the reason `u_max =
  0.01` rather than a non-pandemic bound.
- **The per-game tie heterogeneity figures (§2.3) are rough and UNVERIFIED.** They motivate a sensitivity; they do
  not support a point estimate.
