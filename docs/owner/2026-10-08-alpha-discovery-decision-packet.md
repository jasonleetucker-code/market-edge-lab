# Decision packet: Track B alpha discovery (2026-10-08)

This is the consolidated owner approval packet for the 2026-10-08 Track B directive
(`docs/owner/2026-10-08-rapid-alpha-discovery-directive.md`; `docs/EXECUTION_PLAN.md` Track B entry, PR #185;
#184).

- **Status words:** CURRENT, PROPOSED, APPROVED, BLOCKED. Nothing here is approved by being recommended.
- **Supporting analysis:** `docs/research/ALPHA_DISCOVERY_2026-10.md`. It merges R1, R2, R3 and R6 with the
  owner-supplied external research of 2026-10-08.

**Where things stand.**
- **No edge is established.**
- The three leading candidates are **weakened hypotheses awaiting one data grant**. All are DRAFT, slot QUEUED:
  - TB-05, taker favourite FLB (EXP-005);
  - TB-01, late-game favourite at a clock known before the game (EXP-004);
  - TB-03, maker favourite bound (EXP-006).
- None is testable on data we hold.

**Order of items.** Items are ordered by expected information per unit of risk and cost. Item 3 (fees) is placed
above IEM because it is $0, carries no data-rights risk, and blocks every net claim.

**Never asked here:** passwords, private keys or MFA codes. No item authorizes orders, accounts, demo trading,
schedules beyond the stated bound, or deployment.

## Already decided (not re-asked)

- The Track B scope: DRAFT/QUEUED registration; feature-only use of held data; family A and B mechanisms, NFL
  moneyline outcomes and NHL outcomes excluded; no new collection or downloads without a grant.
- EXP-002 is family A, ACTIVE. EXP-003 is family B, ACTIVE-PAUSED (frees no slot). EXP-001 is protected.
- The 450-credit Odds API pilot (NFL first, then NHL) is unchanged. **The Odds API historical endpoint is
  paid-only. The free pilot key gives no history, and nothing here asks for it.**

---

## 1. Kalshi one-time public read: settled markets, trades and one-minute candles (approval A2). Highest value.

**What it is.**
- **Resource:** keyless Kalshi public endpoints `/historical/markets` (and settled markets), `GET /markets/trades`
  (taker side, `count_fp`, `created_time`), and market candlesticks at a 1-minute period (`yes_bid`/`yes_ask`
  OHLC).
- **Universe** (frozen before the read):
  - KXNBAGAME, Oct 2025 – Feb 2026;
  - KXMLBGAME, 2025 season;
  - the frozen non-sports series for EXP-005/006, closing on or after 2025-07-01;
  - optionally non-NY KXHIGH*/KXLOW* for TB-09.
- **Excluded:** KXHIGHNY; KXNFLGAME and all 2026 NFL moneyline games (EXP-002); KXNHLGAME (Track B excludes NHL
  outcomes); KXMVE* combos.
- **Purpose:** it serves EXP-005, EXP-004 and EXP-006 (bounds), and TB-09. **Quotes**, not trade prints, are what
  makes the tests honest (R6).
- **Why existing data is insufficient:** no Kalshi trade prints or candles are collected anywhere (R3). The held
  sports data is NFL (protected) or NHL (excluded).

**Terms, credentials, budget.**
- **Terms:** Kalshi API data rights are **UNRESOLVED** (vf packet item B). The Developer Agreement is unread
  (HTTP 429). This is the binding prerequisite. Research use only; no redistribution.
- **Credentials:** none (public endpoints).
- **Budget (PROPOSED cap):**
  1. **Stage 1:** a sampled count of at most 300 GETs, to measure markets, trades and candle availability per
     series.
  2. **Stage 2:** the bounded read, capped at **20,000 GETs**, paced by the shared Kalshi pacer and outside every
     protected window.

  Storage is estimated at a few hundred MB. That is UNVERIFIED until stage 1. Cash: $0.
- **Code:** a pure trades/candles adapter, plus a one-off bounded reader with no timer. It needs a merge ruling
  (item 7).

**Effect and value.**
- **One-time or recurring:** one-time. No schedule.
- **Family-slot implication:** none for retrospective DRAFT diagnostics. Promoting any candidate to ACTIVE needs
  item 11.
- **Expected information:** high. Three bias-proof tests, each with a written-in KILL rule, can produce verdicts
  within about a week.
- **Lower-cost alternative:** the Becker tape (item 2). It has prints only, ends 2025-11-25 and has no quotes, so
  it cannot score the primary endpoints.

**Recommendation: APPROVE once you have read the Kalshi Developer Agreement and are satisfied that it permits
private research storage.** If it does not, decline, and the candidates stay ACCESS_BLOCKED.

Suggested wording:

> I approve a one-time Kalshi public read (A2) of settled markets, trades and 1-minute candlesticks for the
> universe in the 2026-10-08 Track B decision packet item 1. Stage 1 is ≤300 GETs, then a ≤20,000-GET read,
> paced and outside protected windows. It excludes KXHIGHNY, KXNFLGAME/2026 NFL moneyline, KXNHLGAME and KXMVE*.
> Research use only, no redistribution, no schedule, no account, no orders.

## 2. Becker prediction-market tape (MIT, about 36 GiB) and reading Le's code

- **Resource:** the archive linked from https://github.com/Jon-Becker/prediction-market-analysis. It covers Kalshi
  and Polymarket trades to 2025-11-25, about 36 GiB compressed. Whether a Kalshi-only subset can be fetched
  separately is UNVERIFIED.
- **Also:** **reading** Le's MIT calibration code (https://github.com/namanhzz/prediction-market-calibration) as
  web pages. Running, installing or vendoring third-party code stays excluded.
- **Purpose:**
  - a partial substitute for item 1, with prints and taker side only;
  - a non-overlapping 2025 season for TB-01's positive control (realized-close bucketing on prints);
  - mechanism checks for TB-05 and TB-03.
- **Why existing data is insufficient:** as item 1.
- **Terms:** the code is MIT. The underlying Kalshi data still inherits Kalshi's terms (DATA_RIGHTS UNRESOLVED).
  Coverage must be checked.
- **Credentials:** none.
- **Budget:** about 36 GiB transfer and disk; $0.
- **One-time or recurring:** one-time.
- **Family slot:** none.
- **Expected information:**
  - medium: it cannot score at quotes;
  - it holds only about 5 months of the post-2025-07 regime;
  - it is the same venue's records as the papers it would check.
- **Lower-cost alternative:** item 1's stage 1 alone.
- **Recommendation: DEFER**, unless item 1 is declined or delayed. If you grant it, grant it for prints-only
  diagnostics, labelled as such.

## 3. Kalshi fee schedule currency and the sports fee questions

- **Resource:**
  - your own browser read of the current https://kalshi.com/docs/kalshi-fee-schedule.pdf (the owner-supplied
    research found it readable on 2026-10-08, still dated July 7, 2026);
  - **adding to the unsent Kalshi message Q7** (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`):
    - KXNBAGAME, KXMLBGAME and KXNHLGAME multipliers;
    - the per-series `fee_type` history (when maker fees applied to which series);
    - whether KXNBAGAME's absence from the non-standard list means maker M = 0.
- **Purpose:** every net figure for TB-01 is blocked on sports fees, and every maker figure (TB-03) on `fee_type`
  history.
- **What the external research did and did not settle:**
  - Its "NFL fee blocker now has primary evidence" is **not new**. The repo already holds that exact PDF (sha256
    `c326a69f…`).
  - `docs/research/EXP002_FEE_VERIFICATION.md` keeps KXNFLGAME FEE_UNSUPPORTED for four reasons:
    1. the column-to-API multiplier mapping;
    2. the 2026-09-16 series change;
    3. event overrides, waivers and scheduled changes, which need an API read;
    4. the maker-fee start.
  - A 2026-10-08 read still dated July 7 bears only on currency. **The blocker is not resolved.**
- **Terms:** public document; owner-confirmed message text.
- **Credentials:** none in chat. Send it from your own account address or the help form.
- **Budget:** $0; about 30 owner minutes.
- **One-time or recurring:** one-time.
- **Family slot:** none.
- **Expected information:** high relative to cost. It unblocks net claims for all sports candidates and EXP-002.
- **Lower-cost alternative:** none.
- **Recommendation: APPROVE.** Read the PDF yourself, then confirm the extended Q7 text.

## 4. Iowa Environmental Mesonet ASOS/METAR and CLI archives

- **Resource:** IEM archives (https://mesonet.agron.iastate.edu/) of METAR/ASOS observations and NWS CLI
  products. **Non-NY stations only.** IEM MOS vintages (https://mesonet.agron.iastate.edu/mos/) are optional for
  TB-09.
- **Purpose:**
  - TB-10's risk floor: P(observation-determined outcome ≠ CLI-final);
  - TB-09/TB-11 station work.
- **Why existing data is insufficient:** held CLI and PFM data are KXHIGHNY/OKX, which EXP-001 protects (the
  `nws_cli:` and `nws_pfm:` prohibited inputs). Non-NY archives would get their own dataset ids.
- **Terms:** public. Pace requests per IEM guidance.
- **Credentials:** none.
- **Budget (PROPOSED):** ≤ 5,000 requests, one-time; $0.
- **Family slot:** none.
- **Expected information:** medium-low. R6 rates TB-10 WEAKEN: NY settlement matched 739/739, so the risk is
  public and priced.
- **Lower-cost alternative:** wait for item 1's weather candles before deciding.
- **Recommendation: DEFER until item 1's results.** It is ranked below the top five.

## 5. Novig daily files (about 2.2 GB, licence unstated)

- **Resource:** `data.novig.com/reporting/trade-data/<date>/{trades,markets}.csv`, about 51 dates, 2026-08-03 to
  09-22, keyless.
- **Purpose:** a second-venue mechanism check for maker/taker (TB-03) and FLB (TB-05). It **cannot test Kalshi
  fills**.
- **Conflict to rule on:** the 2026-09-23 grant allows "manual reads of Novig's published daily files, where the
  terms permit". The 2026-10-08 Track B entry excludes "venue … pulls of historical trades". Which governs is
  your call.
- **Terms:** no licence is stated, so a terms review comes first. No Novig fee record exists.
- **Credentials:** none.
- **Budget:** about 2.2 GB, one-time; $0.
- **Family slot:** none.
- **Expected information:** low-medium (another venue).
- **Lower-cost alternative:** item 1.
- **Recommendation: DEFER.** If you prefer it, rule that the 2026-09-23 grant covers a one-time research read
  after a terms review.

## 6. TB-23 (reference-period / vintage mismatch): documentation audit confirmation and a vintage archive

**Part 6a, confirmation.** Confirm that an **outcome-blinded, price-blind semantic audit** of about 20 EIA-linked
Kalshi contracts is documentation research under the Track B scope:
- sources: public rules pages and official EIA release notes (https://www.eia.gov/petroleum/supply/weekly/pdf/appendixb.pdf);
- no API and no prices;
- any settled result seen on a page is recorded.

**Part 6b, a later grant (only if 6a finds real mismatches).** A one-time read of an official release-vintage
archive:
- for example EIA's archived weekly releases (https://www.eia.gov/petroleum/supply/weekly/), or ALFRED;
- ALFRED needs an API key, and **keys are never handled in chat**. Prefer the keyless EIA archive.

**Details.**
- **Purpose:** the owner-supplied research's most novel mechanism. It rewards reading precision, not speed.
- **Why existing data is insufficient:** none held.
- **Terms:** official public data.
- **Budget:**
  - 6a: $0;
  - 6b: ≤ 2,000 requests, one-time.
- **Family slot:** none while DRAFT.
- **Expected information:** medium for 6a. It shows quickly whether the mechanism has any instances.
- **Lower-cost alternative:** 6a alone.
- **Market-price side:** needs item 1, extended to those series.
- **Recommendation: APPROVE 6a now. Decide 6b after 6a.**

## 7. Standing merge delegation for Track B research code PRs

**Proposed rule.** Track B research code PRs may merge without a per-PR owner approval under the same conditions
as the existing delegations:
- offline and pure;
- fixture/synthetic tests;
- CI green on the head;
- an independent read-only review;
- no import of `edge_lab.execution`;
- no collector, timer, schedule, credential or network call outside an approved one-time read;
- no change to EXP-001/002/003 or to a frozen protocol.

**Purpose.** The item-1 adapter and harness glue would otherwise wait on per-PR approval. The directive quotes no
merge grant.

**Details.**
- **Terms, credentials, cost:** none.
- **Family slot:** none.
- **Expected information:** indirect, as speed.
- **Lower-cost alternative:** per-PR approval.
- **Recommendation: APPROVE**, with the conditions above, expiring 2026-11-15.

## 8. OP-H01 (fresh sportsbook consensus vs the Kalshi ask): your choice

The owner-supplied research ranks this first. It is **family A's mechanism**, which is EXP-002 itself, so it is
excluded from Track B on any sport (#185). Options:

- **(a)** Leave it to EXP-002's own process: the A.C calibration run (about 2026-10-19), then E1. **No new
  work.**
- **(b)** Authorize an OP-H01-style **label-blind attrition/feasibility funnel** as **EXP-002 development work**,
  logged in EXP-002's log as FEATURE_INSPECTION. It would count candidates surviving identity, freshness, fees,
  ask and size, with no outcomes.
  - It is useful for EXP-002's own E1 design.
  - It must not run before A.C, nor change EXP-002's frozen settings.

**Details.**
- **Credentials and cost:** none, $0.
- **Family slot:** A (existing).
- **Expected information:** medium for EXP-002.
- **Recommendation: (a)**, unless EXP-002's owner wants the funnel for E1. In that case use (b) after A.C.
- It is **not** registered as a Track B candidate.

## 9. Forward paper-maker study against the live book (collection grant)

- **Resource:** sub-minute public book plus public trades capture for a small frozen set of non-sports markets.
  No account. A queue-conservative virtual maker:
  - fills only from volume traded at our price after our virtual post, beyond the displayed queue ahead, plus
    trade-throughs;
  - markouts at 1/5/60 minutes and at settlement.
- **Purpose:** R6 judges this the only honest maker test short of real orders. Real queue dynamics need Gate 9
  (not authorized).
- **Why existing data is insufficient:** public history has no depth or queue.
- **Terms:** as item 1 (DATA_RIGHTS).
- **Credentials:** none.
- **Budget:** PROPOSED ≤ 14 days, ≤ 10 markets, a request cap set by the shared pacer, manual start and an expiry
  file. It is **recurring for its duration**.
- **Family slot:** an empirical prospective study needs an ACTIVE slot (item 11).
- **Expected information:** decisive for TB-03, but only after EXP-006's optimistic bound is positive.
- **Lower-cost alternative:** EXP-006's retrospective bounds (item 1).
- **Recommendation: DEFER** until EXP-006 reports. If its optimistic bound is ≤ 0, this is never needed.

## 10. Research use of a fresh off-host O1 pull (approval A0)

- **Resource:** the already-approved weekly O1 pull (root runbook §8; overdue about 6 days), used as a laptop
  research input.
- **Purpose:** feature-only diagnostics on held books (depth, spreads, $100 ladders, attrition), logged.
- **Why existing data is insufficient:** the only off-host copy (2026-09-26) predates the sports captures.
- **Terms:** our own data.
- **Credentials:** the existing runbook (no new ones).
- **Cost:** $0.
- **One-time or recurring:** one-time per pull.
- **Family slot:** none.
- **Expected information:** low for the top three (none uses these books); medium for execution realism.
- **Recommendation: APPROVE** research use of the next scheduled pull. No extra pull.

## 11. Family-slot decision for the leading candidate

Both new slots are occupied: A (EXP-002) and B (EXP-003, paused). Retrospective DRAFT diagnostics need no slot;
**ACTIVE (preregistration, prospective windows) does.** Options:

| Option | Effect | Trade-off |
|---|---|---|
| (i) End EXP-003's slot (PAUSED → ENDED) | Frees one slot | Gives up family B. EXP-003's own rule rejects its scope on 2026-11-15 if Kalshi Q1/Q4 stay unanswered. |
| (ii) `owner_exception` for a third family | Adds a slot | Exceeds the #96 cap; more parallel governance |
| (iii) No decision now | Candidates stay QUEUED | Nothing is lost until a candidate survives its retrospective KILL rule |

**Recommendation: (iii) now.** Revisit only when a candidate is PROVISIONALLY INTERESTING. Then prefer (i) if
EXP-003's 2026-11-15 condition has been met.

## 12. Non-outcome family-B scans while EXP-003 is paused

- **Request:** complement and partition sums on held books, outcome-free, by Track B.
- **Purpose:** low. EXP-003's own development scan found asks summing to 1.06 (no surplus). The owner-supplied
  research's fee arithmetic shows a 0.97 two-leg set losing after fees.
- **Risk:** it reads as reviving a paused family through a back door.
- **Cost:** $0.
- **Family slot:** B.
- **Recommendation: DECLINE.** Leave family B to EXP-003's own resumption decision.

## 13. Wallet-lane datasets (#168)

**Datasets.**
- **Akey et al. Polymarket users:** https://huggingface.co/datasets/vgregoire/polymarket-users, CC-BY-4.0, about
  119 GB.
  - **Use the corrected version, with the correction history pinned.**
  - Full-sample `user_features` must not be used to select historical leaders (look-ahead).
  - `pnl_daily` holds sparse **cumulative levels**, not daily increments.
- **Possible supplement:** `TimeSeventeen/Polymarket-v1` (https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1),
  CC-BY-4.0. It has raw and cleaned layers and UTC+8 day partitions, but no L2 or cancels.

**Details.**
- **Purpose:** empirical calibration of the synthetic wallet lane. **Not Track B:** Polymarket International is
  US close-only (https://docs.polymarket.com/api-reference/geoblock), so TB-16 is blocked.
- **Budget:** about 119 GB plus tens of GB; one-time; $0.
- **Family slot:** an empirical wallet evaluation needs one (A6).
- **Lower-cost alternative:** stay synthetic.
- **Recommendation: DEFER** to the #168 lane's own packet.

## Not requested, and why

| Source | Reason |
|---|---|
| Football-Data.co.uk | Restricts automated, bot and AI use. **Excluded.** |
| Prophet-Arena-Subset-3000 | No model predictions and no L2; its visible rows are now development examples, not holdout. Not needed. |
| The Odds API historical | Paid-only. |
| Running Forecast-Dojo or any third-party repository | Excluded. |
| Any AI model call | Excluded. |
