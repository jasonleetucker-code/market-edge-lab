# RFQ and combo feasibility (R4): capability, visibility, economics and decision

**Status:** research record, 2026-09-30 (PR B, roadmap R4, issue #145). Authority: the 2026-09-30
owner directive recorded in `docs/EXECUTION_PLAN.md` (PR #147): "PR B (R4): an RFQ feasibility
packet from public documentation, and an optional pure fixture-fed lifecycle component". Spec:
PR #146, `docs/strategy/CLAUDE_SPORTS_INTELLIGENCE_RFQ_V1.md` §10–§12 and
`docs/strategy/DELIVERY_ROADMAP.md` R4 (merged in PR #146).

This document authorizes nothing. No RFQ was created, no quote sent, accepted or confirmed, no
channel subscribed, no credential created or used, no account read. An RFQ quote is an
executable obligation for the full requested size, not an observation, so it is never a way to
"gather data". EXECUTION_NOT_AUTHORIZED stays enforced, and `venues.KALSHI.execution_authorized`
stays False.

## 0. Method and sources

- Every venue fact below comes from Kalshi's public documentation, fetched as page markdown on
  **2026-09-30 between 02:26:52Z and 02:28:59Z** (2026-09-29 22:26–22:29 ET) by plain GETs to
  `docs.kalshi.com`. No Kalshi API host was contacted. The first 16 hex digits of each page's
  sha256 are kept so a later re-read can show whether a page changed. The bytes were not
  committed (they are the vendor's content).
- Status words: **VERIFIED** means stated in the current docs; it is not verified for *our*
  account and not observed. **UNVERIFIED** means the docs imply it but do not state it, or two
  documented texts conflict. **UNKNOWN** means the docs say nothing.
- Perpetual-futures (margin, "Perps") pages are excluded. Rate-limit and sharding facts below
  are the event-contract ("Predictions") ones.
- Quotes are short; everything else is paraphrase.

| # | Page | sha256[:16] |
|---|---|---|
| S1 | https://docs.kalshi.com/getting_started/rfqs | a7341a266364d2de |
| S2 | https://docs.kalshi.com/websockets/communications | 359bef210140250e |
| S3 | https://docs.kalshi.com/getting_started/maintenance_and_pauses | 6735be37e5172427 |
| S4 | https://docs.kalshi.com/fix/rfq-messages | 589ba2204c42afb5 |
| S5 | https://docs.kalshi.com/api-reference/communications/create-rfq | 0a65e35d491e3591 |
| S6 | https://docs.kalshi.com/api-reference/communications/get-rfqs (and get-rfq, f76a939bef0867a8) | a237a24052a52871 |
| S7 | https://docs.kalshi.com/api-reference/communications/delete-rfq | f02aa776de24422c |
| S8 | https://docs.kalshi.com/api-reference/communications/get-quotes | 303b44d4c12f8740 |
| S9 | https://docs.kalshi.com/api-reference/communications/create-quote | 92fde230ee75951a |
| S10 | https://docs.kalshi.com/api-reference/communications/accept-rfq-quote | 078c07d26aa470eb |
| S11 | https://docs.kalshi.com/api-reference/communications/confirm-rfq-quote | f38038d690b7ddbd |
| S12 | https://docs.kalshi.com/api-reference/communications/delete-rfq-quote | 1e435809f6e8b601 |
| S13 | https://docs.kalshi.com/api-reference/multivariate/get-multivariate-event-collections (and get-…-collection) | 31a726aeff69a20a |
| S14 | https://docs.kalshi.com/api-reference/multivariate/create-market-in-multivariate-event-collection | a93b5b5779d5a0df |
| S15 | https://docs.kalshi.com/api-reference/events/get-multivariate-events | 3ee99088468cf3ac |
| S16 | https://docs.kalshi.com/getting_started/rate_limits | 757dd61775f06929 |
| S17 | https://docs.kalshi.com/getting_started/exchange_sharding | fcc425297cecc9c4 |
| S18 | https://docs.kalshi.com/getting_started/subaccounts | 97fad2f0583ffd48 |
| S19 | https://docs.kalshi.com/api-reference/api-keys/create-api-key | 343fba8c4689d7a1 |
| S20 | https://docs.kalshi.com/api-reference/market/get-trades | 655019021cff66f0 |
| S21 | https://docs.kalshi.com/api-reference/portfolio/get-fills | b81d73d1e44feb56 |
| S22 | https://docs.kalshi.com/getting_started/fee_rounding | 9d0b6e4c6b84253f |
| S23 | https://docs.kalshi.com/websockets/websocket-connection | e8eeefd9c93c89bd |
| S24 | https://docs.kalshi.com/llms.txt (the official index used to find S4–S23) | da89a38c2f49a185 |

Endpoints found through the index (event contracts only): Create/Get/List/Delete RFQ
(`/communications/rfqs`), Create/List Quote (`/communications/quotes`), Get/Delete/Accept/Confirm
a quote scoped to its RFQ (`/communications/rfqs/{rfq_id}/quotes/{quote_id}[/accept|/confirm]`;
the unscoped `/communications/quotes/{id}` forms are marked DEPRECATED), Get Communications ID,
the multivariate collection endpoints (S13, S14) and Get Multivariate Events (S15). Order-side
pages relevant to RFQ execution: fills (S21) and trades (S20); the order-entry endpoints were
only indexed, not studied, because nothing here places an order.

In-repo evidence also used: the fee-schedule PDF extract
`experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/pdf_nonstandard_series.json` (row
`KXMVE`) and the 2026-09-23 fixed-point page capture in the same directory (combo price grid).

## 1. The documented lifecycle, in one line each

1. A requester creates an RFQ for one market (a combo is one market) and a size. S1, S5.
2. Every authenticated subscriber of the `communications` channel gets `rfq_created`, unless
   the subscriber filtered to its own RFQs. S2.
3. Makers answer with a two-sided quote (`yes_bid`, `no_bid`); either side may be 0, not both;
   `yes_bid + no_bid > $1` is rejected; the quote is implicitly for the full size. S1.
4. Quote events (`quote_created`, `quote_accepted`, `quote_executed`) go only to that quote's
   maker and the RFQ's requester. S2.
5. The requester accepts one side; the maker must confirm within the confirmation window;
   "Once confirmed, neither party can withdraw." S1.
6. After the execution timer, orders are entered; fills appear in the fill records, matched by
   order id. S1, S2 (`quote_executed` carries our `order_id`), S21.

## 2. (a) Capability and observability matrix

Visibility classes: **anyone** (no authentication), **authenticated** (any member with a
session), **requester**, **quoter**, **private** (the venue only, or another member).
"Observe without trading" assumes no RFQ and no quote from us.

| Item | What the docs say | Who can see it | What we could observe without trading | Status |
|---|---|---|---|---|
| Request metadata | `rfq_created`: id, creator id (pseudonymous; "0" if the creator asked to hide it), market, event, `contracts_fp` or `target_cost_dollars`, created time, combo collection and legs. `rfq_deleted` adds a deleted time. S2. REST list/get RFQ also needs auth. S6. | authenticated (all users by default; `user_filter: "self"` narrows) | Everything in the event, **only through an authenticated connection**: the WebSocket connection itself requires API-key auth (S23), and so do the REST RFQ reads (S6). Unauthenticated: nothing. | VERIFIED (docs); access UNKNOWN for our account |
| Combo definitions and legs | Collections (open/close dates, associated events, size min/max, ordering) and created combo events are readable without auth (S13, S15). An RFQ's legs arrive in `mve_selected_legs` with event, market, side (S2). Creating a combo market needs auth and is capped at 5,000 creations a week per user (S14). Combo markets use a different price grid (`center_deci_edge_centi_cent`, repo capture 2026-09-23). | anyone (definitions); authenticated (which combos are being requested) | Collection and combo-event definitions, from public GETs (a new read scope that is not authorized today, see §6). Which leg sets people request: only via the authenticated channel. | VERIFIED |
| Authentication and actual entitlements | API keys carry scopes: `read`, `write` and narrower children; the default is full access if no scope is given (S19). Keys can be locked to one subaccount (S18, S19). Whether a `read`-only key may subscribe to `communications`, and whether an ordinary (non-market-maker) member may quote, is not stated. | private | Nothing: we hold no Kalshi credential, and creating one is not authorized. | UNKNOWN for our account |
| Storage, training and derived-data rights | The RFQ pages say nothing about rights. Kalshi's Data Terms restrict systematic collection and ML use; whether they govern API data is the open item in `docs/owner/2026-09-29-vf-decision-packet.md` §B ("Which terms govern our API-collected data: UNRESOLVED"). The Developer Agreement is unread. | n/a | Nothing may be stored from the RFQ stream until §B is decided. | UNRESOLVED |
| Our quotes vs other makers' quotes | "Each quote is private between the requester and the individual maker; makers cannot see each other's quotes" (S1). Quote events go only to the two parties (S2). REST Get Quotes (S8) does not state its visibility scope; its `*_user_id` and order-id fields are labelled "private field". | quoter sees own; requester sees all on its RFQ; nobody else | An outside observer: **no quote prices at all**. As a quoter we would see only our own quote, never the winning price if we lose. As a requester we would see every quote on our RFQ, which requires creating an RFQ (not authorized). | VERIFIED (S1, S2); REST list scope UNVERIFIED |
| Acceptance and fill visibility | `quote_accepted` and `quote_executed` go to the two parties only (S2). Fills are per member (S21). Public trades (no auth) carry `is_block_trade`, described as off-book matching "(e.g. via RFQ / negotiated block proposal)" (S20). | parties; anyone sees trades, unattributed | Possibly an **upper bound** on executed off-book volume per market from public trades with `is_block_trade=true`, mixing RFQ executions with negotiated blocks and never linked to an RFQ id. Conflict C7 says this may not even include RFQ executions. | UNVERIFIED |
| Native quantity and payout | Contracts are fixed-point with 0.01-contract granularity (S5); the market's price grid applies to quotes (S1); a binary contract pays $1 (existing `venues.KALSHI.units`). | authenticated (request); parties (quote sizes) | Requested contracts on contracts-sized RFQs. | VERIFIED |
| Fee-inclusive vs principal-only target size | Size is given as contracts **or** a target cost. By default the target caps principal plus the requester's taker fee; `target_cost_excludes_fees: true` sizes principal only, fee on top; contract-sized RFQs are never reduced for fees (S1, S5). The channel's `rfq_created` has no `target_cost_excludes_fees` field (S2). | requester; parties (derived `yes/no_contracts_offered_fp`) | For target-cost RFQs, neither the contract count nor the fee mode. The derived counts appear only in quote events. | VERIFIED; the observer gap is VERIFIED by omission |
| Full-request obligations and partial acceptance | The guide: quotes are for the full RFQ size; quoters do not specify a size (S1). REST Accept takes only `accepted_side` (S10). **But** FIX AcceptQuote has an optional quantity to accept, and the `quote_accepted` example accepts 50 of 100 offered (S4, S2). See C1. | parties | Nothing. | UNVERIFIED (conflict C1). Plan conservatively: full-size obligation, no guaranteed partial acceptance |
| Quote replacement and expiry | A new quote on the same RFQ replaces the maker's earlier one (S1); FIX says a new quote cancels the maker's quote on the same *market* (S4, C4). A maker can delete a quote so it "can no longer be accepted" (S12). No quote time-to-live is documented. An unconfirmed accepted quote is "voided" after the window (S4). RFQs close when deleted, expired or executed (S1 errors); the RFQ lifetime is not documented; FIX can send an unsolicited EXPIRED (S4). | parties; `rfq_deleted` to all | RFQ closings (with a deleted time, no reason). | VERIFIED that replacement and expiry exist; durations UNKNOWN |
| Acceptance → maker confirmation → execution | Accept, then maker confirm within the window, then an execution timer, then orders enter the book; fills in fill records (S1). REST quote statuses: open, accepted, confirmed, executed, cancelled (S8). `quote_executed` means orders were placed, not filled (S2). There is no channel event for confirmation; confirmation is visible in REST status (S8) and FIX (S4). **The channel's `quote_accepted` carries no acceptance timestamp** (only the optional envelope `sending_ts_ms`, when Kalshi queued the message); the REST quote has `accepted_ts` (S8). A replay that needs the acceptance time from the channel must use its own receipt time, labelled as such. | parties | Nothing. | VERIFIED |
| Timing classes and the binding point | Standard: 30 s to confirm, 15 s execution timer. High Volatility Markets (every combo): 3 s and 1 s (S1). FIX states a flat 30 s (C2). Binding point: maker confirmation (S1). | public docs; which non-combo markets are HVM is not listed | The HVM flag for combos (all of them). Which other markets are HVM: UNKNOWN. | VERIFIED (with conflict C2) |
| Collateral | RFQ actions can fail with `INSUFFICIENT_BALANCE` (S1), and FIX RFQ creation with `INSUFFICIENT_CREDIT` (S4). Collateral checks run inside each matching engine; collateral must be preallocated per exchange shard; combos moved to shard 1 (S17). When collateral is reserved for an open quote (at quote time or only at confirmation) is not documented. | private | Nothing. | Partly VERIFIED; quote-time reservation UNKNOWN |
| Common-leg exposure | Each combo is its own market; legs are listed per RFQ (S2). Nothing in the docs nets exposure across combos that share a leg. | parties (own) | Leg overlap across requested combos, through the authenticated channel. | VERIFIED that no netting is documented; treat as none |
| Account attribution | RFQs and quotes can be created under a subaccount 0–63; execution, fills and settlement follow that subaccount; the counterparty's subaccount is never shared (S1, S2, S18). Creator ids are pseudonymous communications ids (S2, S4, and Get Communications ID). | own only | Pseudonymous requester ids on `rfq_created` (unless hidden with `obscure_creator_id`). | VERIFIED |
| Outage, pause, cancel and unknown states | Thursday 03:00–05:00 ET trading pause: no placing or amending orders; unscheduled exchange pauses mean an outage; clients should expect disconnections (S3). RFQ and quote behaviour during a pause is **not** documented. The channel has `seq` for gap detection but no snapshot or replay (S2); a burst can overflow a subscription buffer (error 25, S23). Cancelling an RFQ (S7) or a quote (S12) is documented; whether a quote can be cancelled after acceptance and before confirmation is not. | n/a | Pauses from Get Exchange Status (public). Channel gaps only from our own connection. | Pause for orders VERIFIED; for RFQs UNKNOWN |

### 2.1 Documentation conflicts (recorded, not resolved)

Each conflict is recorded as found. `edge_lab.rfq_research` takes the conservative side of
each and never the convenient one.

| # | Conflict | Sources | Conservative handling |
|---|---|---|---|
| C1 | Quotes are for the full size and REST Accept has no quantity, **vs** FIX AcceptQuote's optional quantity and a `quote_accepted` example accepting 50 of 100 | S1, S10 vs S4, S2 | Reserve the full offered size; never assume partial acceptance is available or guaranteed. More than one distinct acceptance of a quote is UNKNOWN. Limitation: two identical acceptances without any timestamp are indistinguishable from a redelivery and collapse into one |
| C2 | Confirmation window 30 s standard / 3 s HVM, **vs** FIX's flat 30 s | S1 vs S4 | Use the guide's per-class table; a lapsed window releases nothing |
| C3 | Maker prices in FIX are whole cents 1–99, **vs** REST dollar strings on the market's grid (sub-cent on some grids) | S4 vs S9, S1 | Do not assume a quote grid; combos use their own price structure |
| C4 | Replacement is per RFQ (guide) **vs** per market (FIX) | S1 vs S4 | Replace per (maker, RFQ); an ambiguous order of two quotes keeps both reserved |
| C5 | `replace_existing` deletes existing RFQs (REST) **vs** keeps at most two open (FIX) | S5 vs S4 | Not modelled (requester-side creation is out of scope) |
| C6 | "Exactly one of" contracts or target cost, **vs** REST's RFQ requiring `contracts_fp` and an `rfq_deleted` example carrying both; the `quote_created` example offers 100 YES at $0.35 against a $0.35 target cost, which is arithmetically inconsistent | S1 vs S6, S2 | A target-cost RFQ's `contracts_fp` is not used as a requested count |
| C7 | After the timer, "orders are placed on the public book" (S1), **vs** trades flagged `is_block_trade` "matched off-book … (e.g. via RFQ …)" (S20) | S1 vs S20 | No inference of RFQ execution volume from public trades until the venue answers |
| C8 | The requester "accepts one side of the best-priced quote" (S1), **vs** accept-by-id for any quote (S10) and FIX's `PreferBetterQuote`, where the accepted quote may differ from the one named (S4) | S1 vs S10, S4 | A maker's quote can be accepted without being the best; a quote id in an acceptance may not be the one we priced |
| C9 | RFQs are "broadcast to all makers" (S1), **vs** sent to all users by default (S2) | S1 vs S2 | Visibility to a non-maker account is UNKNOWN until observed under authority |
| C10 | Creator id example is a 64-hex digest in one event and `comm_abc123` in another | S2 | Treat ids as opaque strings |
| C11 | RFQ status is only open/closed (S6), **vs** close reasons deleted/expired/executed (S1) and FIX EXPIRED (S4); whether `rfq_deleted` fires on expiry or execution is not stated | S6 vs S1, S4 | A closed RFQ has an UNKNOWN reason; it releases no quote reservation (`RFQ_CLOSED_REASON_UNKNOWN`). Only the quote's own cancelled status releases |
| C12 | A lapsed confirmation "voids" the quote (S4), but no REST status says voided | S4 vs S8 | Voided is treated as CANCELLED only when a cancelled status is observed |
| C13 | Combo RFQs "include" the collection and legs (S1), but REST Create RFQ takes only a market ticker (combo created first, S14), while FIX resolves or creates the combo from legs (S4) | S1, S5, S14, S4 | Requester-side creation is out of scope; legs are read from events |
| C14 | REST `accepted_side` is "the side of the quote to accept"; FIX maps BUY to the maker's NO quote and SELL to the maker's YES quote. The REST side's effect on the requester's own position is not stated | S10 vs S4 | The requester reserves the worse of `bid` and `1 − bid` |
| C15 | FIX quote `RestRemainder` is "allow partial fills" (S4), REST is "rest the remainder … after execution" (S9), and quoters "do not specify a size" (S1) | S4 vs S9, S1 | Unfilled remainders are unknown exposure until fill records say otherwise |

## 3. (b) Channel budget

The `communications` channel ignores market specification (S2: "Market specification
ignored"). A subscriber therefore receives **every** `rfq_created` and `rfq_deleted` on the
exchange, whatever it keeps locally. A budget must bound received messages, not the NFL/NHL rows
kept afterwards. `rfq_research.observe` enforces that: `max_messages` counts every received
message before the `keep` filter, reads at most one message past the bound, and refuses the batch
whole (reported as `">N"`). The `keep` filter applies only to the public RFQ events; our own quote
events and fills are always kept, so a sport filter can never hide our own exposure.

Documented numbers:
- **Sharding:** `shard_factor` 1–100 and `shard_key` (0 ≤ key < factor) split the channel's
  fan-out (S2, S23). How RFQs are assigned to shards is not documented, so a single shard is not
  a known subset (for example, not "one sport").
- **Filter:** `user_filter: "self"` returns only our own RFQs, which is useless for observation.
- **Burst:** a subscription can fail with "Subscription buffer overflow" (error 25) during a
  message burst (S23).
- **Rate limits:** channel messages have no documented token cost. REST RFQ reads cost the
  default 10 tokens from the Read bucket; a Basic tier refills 200 tokens/s (S16), so about 20
  RFQ list calls a second at most. RFQ and quote *writes* bill the shard-1 Write bucket (S16);
  not relevant, since we write nothing.
- **Message size:** not documented.
- **Volume:** **UNKNOWN.** No page states how many RFQs are created per minute, per day or per
  sport. Short-lived HVM RFQs (3 s + 1 s windows) mean REST polling would undercount them.

Measurement plan (every step needs owner approval first, see §6):
1. **Public-only proxy (no credential):** read public trades for the target series with
   `is_block_trade=true` (S20). This bounds executed off-book volume per market and day, mixing
   RFQ and negotiated block trades. It says nothing about requests. It is unauthenticated, but
   it is still a new read scope and needs approval; C7 must be put to the venue first.
2. **Authenticated observe-only census (credential needed; not authorized):** one connection,
   `shard_factor` 1, a fixed window chosen in advance (for example one NFL Sunday plus one
   weekday), hard caps on messages, bytes and duration, fail-closed on caps. Keep only aggregate
   counts per minute, market-prefix histograms, leg counts and the size distribution. Keep no raw
   stream until the rights question (§B of the VF packet) is decided. Output: received
   messages per minute (p50, p99, max), the kept share for NFL/NHL, and gap counts from `seq`.
3. Size a production cap only from step 2's p99 with headroom, then re-approve.

## 4. (c) Economic feasibility

**Requested quantity is not achievable volume.** Observed requests give a demand upper-bound
scenario only. To turn it into our fills needs, per RFQ: whether we would have quoted, whether
our quote was the one accepted, whether the maker (us) confirmed, whether orders filled, and at
what size. For an outside observer every one of these after the first is UNAVAILABLE.

**Private quotes make the competitive terms unknown.** Competitor prices, the number of quotes
per RFQ, our would-be rank, the acceptance rate, the winning price when we lose, and
competitors' profit are all UNKNOWN. There is no documented queue or rank for RFQ quotes. None of
them can be recovered from public data, and none may be filled in with a guess.

**Adverse selection.** A requester picks among quotes it alone can see. Our quote gets accepted
when it is the most favourable to the requester, which is more likely when our price is wrong in
their favour. So the relevant quantity is E[profit | our quote was accepted and filled], not the
average edge over all quotes we would have sent. Requesters may be informed (for example about
lineups or live state). A combo leg that moved after we priced it is exactly the case where
acceptance arrives. The 3 s HVM confirmation window is the only documented defence, and whether
we confirm is itself a decision that selects fills.

**Joint probability.** A combo's fair price is P(all legs), and it is not the product of the
leg prices. Same-game legs are dependent by construction; cross-game independence is an
assumption to test. Mis-stated dependence is a systematic error, and adverse selection will find
it (§5).

**Fees: FEE_UNSUPPORTED.** No RFQ or combo fee is verified:
- The fee PDF extract lists series `KXMVE`, "Combos (excluding uncorrelated NFL combos)", as
  non-standard with maker 2 and taker 1. Its column order is uncertain (the row's own
  transcription note says so).
- Which party pays maker or taker fees in an RFQ execution is not documented. The guide only
  mentions the requester's "taker fee".
- Actual per-fill fees would be observable in our own fill records (`fee_cost`, `is_taker`,
  S21), which we do not have.
- **Routing gap for the fee owner (not changed here):**
  `fee_schedules.schedule_for("kalshi", scope)` matches `KXMVE` exactly. Combo series use longer
  tickers, for example the collections `KXMVECROSSCATEGORY-R` and
  `KXMVESPORTSMULTIGAMEEXTENDED-R` (S17). A market whose series prefix is `KXMVECROSSCATEGORY`
  would route to the general quadratic schedule, not to "unsupported". Nothing prices combos
  today, so the gap is latent. It is recorded in UNRESOLVED.

**Capital lock.**
- A maker's open quote can be accepted on either side at full size, so its worst case is the
  larger of `yes_bid × size` and `no_bid × size`, plus unknown fees.
- Every simultaneous open quote needs its own reservation. When the venue reserves collateral
  for an open quote is not documented, so plan as if it did.
- A combo settles only when its last leg settles, so capital-days for multi-game combos run into
  days.
- Collateral must sit on the combo shard (shard 1, S17), apart from other cash. That is cash
  fragmentation.
- `rfq_research.obligations` releases a reservation only when the quote's own cancelled status is
  observed. A closed RFQ, a replacement, a lapsed window or a missing event releases nothing,
  and any own fill that cannot be attributed to a quote blocks every release. A requester
  obligation exists whenever a quote on our RFQ may bind (accepted, confirmed, executed or
  unknown), with the worst case over both sides when the accepted side is not known.
- Reservation is delegated to the canonical owner, `execution_ticket.reserve_simultaneous_obligations`
  (ADR 0041). `rfq_research` maps its RFQ states onto the canonical obligation states (only an
  observed cancellation is RELEASED) and applies the primitive per exchange index. The primitive
  never nets shared legs and keeps an unknown worst case unknown. An unknown shard, an unknown
  principal or a negative fee allowance is EXPOSURE_UNKNOWN, and a negative principal is refused.

**Illustrative arithmetic only (not a forecast):**
- Suppose a 100-contract combo quote is $0.02 inside a *correct* fair value. The gross is $2 per
  full fill before fees and adverse selection.
- The worst-case lock is the larger side: near a fair value of 0.36 the NO bid is about $0.62,
  so about $62 per open quote, for as long as the quote is live and then until settlement. Bids
  near the edges approach $99.
- Ten simultaneous quotes lock ten times that.
- Whether $2 survives fees, the fill-conditioned adverse selection and the RFQs we never win is
  exactly what cannot be measured without own flow.

**Seasonality.** RFQ demand around big sporting weekends is not a year-round rate. Any demand
census must be dated and not annualized.

## 5. (d) Joint-pricing research plan (later; R7)

Principles:
- P(A∧B) = P(A)·P(B|A). Independence is never the default.
- Fréchet bounds hold without any model: max(0, P(A)+P(B)−1) ≤ P(A∧B) ≤ min(P(A), P(B)). For
  P(A) = P(B) = 0.60 that is [0.20, 0.60]. Independence gives 0.36 and P(B|A) = 0.80 gives 0.48.
  These are illustrations, not forecasts.
- `payoff_constraints` proves logical and state relationships (complements, partitions, nesting)
  and their worst-state payoffs. It never estimates a probability. Joint probabilities need data
  and a registered model, never an LLM guess.
- Void, tie and refund rules change the payoff, not just the probability. A combo with a voided
  leg needs its settlement rule captured before it is priced.

Stages, each gated on the previous one:
1. A small supported scope: for example two-leg, same-sport combos with captured rules.
2. A transparent model with explicit dependence parameters and their uncertainty.
3. Out-of-sample calibration against settled combos, with its own frozen protocol.
4. Observability-aware replay. Only requests we could have seen; our hypothetical quotes; never
   competitor quotes or fills; nonquotes, expiries and state changes kept. Results stay
   bounds, not fill rates.
5. Own-flow evaluation. Separately authorized, with its own slot, budget and risk plan (R5
   semantics first). It is the only way to observe E[profit | our fills].

Future test fixtures (for the stage-2 model; none built now):
- impossible combinations (conflicting legs; the venue's `conflicting_leg_outcomes` /
  `duplicated_legs` / `invalid_market_combination` reject codes, S4);
- complements and nesting (A and not-A; "wins by 7+" inside "wins");
- positive and negative dependence (same-game favourite plus over; favourite plus underdog prop);
- Fréchet-bound violations flagged, never priced through;
- duplicate exposure: the same leg in several open quotes (the canonical reservation's per-key sums);
- tie, void and refund legs;
- uncertain parameters: the dependence interval widens the quote or refuses it.

## 6. (e) Decision: **NARROW**

Not PROCEED: every empirical RFQ question needs an authenticated connection, a credential, a
rights decision and a research slot. None of these exists or is authorized. The economics that
matter, fill-conditioned profit, cannot be observed without quoting, and quoting is an obligation.
Not DEFER outright: the documentation-level contract, the conflicts and the synthetic lifecycle
are done and reusable, and one cheap observation route may need no credential.

**Narrowed scope (what remains open):**
1. DONE here: the visibility matrix, conflicts, budget rules, and the pure lifecycle contract
   (`src/edge_lab/rfq_research.py`, ADR 0042) with synthetic tests.
2. NEXT, if the owner wants to go on: the questions below go to Kalshi as part of the existing
   message (not sent here), plus the owner decisions D1–D2.
3. Everything else is DEFERRED: authenticated observation, joint pricing (R7) and any maker or
   RFQ participation.

**Gaps and the owner-only decision each needs:**

| Gap | Kind | Owner decision needed |
|---|---|---|
| Data rights for storing or analysing API data (the VF packet §B) | rights | D1: read the Developer Agreement signed in, and decide. Already open; this adds RFQ-stream storage to the question |
| Any view of requests | access | D2: approve a Kalshi API credential with the narrowest scope that can subscribe to `communications` for observe-only use (read-only if that suffices, UNKNOWN), plus a bounded census (§3 step 2). Credential creation is **not authorized today** |
| Venue facts C1, C2, C7, C9, C11, C14, RFQ fees, pause behaviour | facts | D3: add RFQ questions to the Kalshi message, a revision 3 (list below). Sending stays owner-confirmed |
| Executed off-book volume, no credential | data | D4: approve a bounded public read of trades with `is_block_trade` for chosen series, as a new read scope (§3 step 1). Only useful once C7 is answered |
| A research slot | slot | D5: RFQ empirical work would be a new family under #96. EXP-003's pause frees no slot automatically; a slot decision or an explicit exception is needed |
| Budget | cost | D6: $0 cash for D2 and D4 (Basic tier); owner hours, unpriced; VPS headroom checked before any census. No paid tier |
| Fees | facts | Resolved only by D3 or by own fill records (needs participation) |

**Proposed questions for Kalshi (draft only, NOT SENT):**
1. May a quote be accepted for less than the full size (C1)?
2. Is the HVM confirmation window 3 s on FIX too (C2)?
3. Are RFQ executions reported as `is_block_trade` trades (C7)?
4. Do non-market-maker members receive `rfq_created`, and can a `read`-scoped key subscribe to
   `communications` (C9)?
5. What are the RFQ lifetime and the close reason on `rfq_deleted` (C11)?
6. Which fee, maker or taker, applies to each side of an RFQ execution, for combos and for
   standard markets?
7. What happens to open RFQs and quotes during trading and exchange pauses?
8. Is storing and analysing `communications` channel data covered by the Developer Agreement?

No empirical RFQ family, market-making authority, subscription or credential is activated by
this decision.

## 7. Relation to existing owners

- `venues.py` stays the capability owner and is **unchanged**. Adding RFQ capabilities there
  would add rows to every venue and to the Terminal's venue-coverage table, which is a UI change
  that belongs to PR C. The recommended stages, when PR C adds them: Kalshi `rfq_observe`
  NEEDS_ACCESS (auth required) and `rfq_quote_write` NEEDS_ACCESS (not authorized); UNSUPPORTED
  for every other venue until its own documentation is read.
- `execution_ticket.py` / ADR 0035 own orders after they exist. RFQ execution produces ordinary
  orders and fills (`quote_executed.order_id`). A future R5 package maps those into the intent
  journal. `rfq_research` never creates a ticket.
- `payoff_constraints.py` owns logical payoff relations. `rfq_research` reports shared legs and
  proves nothing about probabilities.
- `research_economics.py` (PR A) owns fill-conditioned economics. `rfq_research` supplies only
  the observability layers (requested, accepted-notified, orders-placed, filled) that such a
  report must keep separate.
