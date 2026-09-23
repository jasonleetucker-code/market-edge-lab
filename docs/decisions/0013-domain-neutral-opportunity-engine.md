# 0013 — A domain-neutral opportunity engine with venue and model adapters

Status: Accepted (2026-09-23). Gate 5, authorized in
`docs/owner/2026-09-22-overnight-build-directive.md`.

**Problem.** Gate 5 has to answer one question. Given a model probability and a quote someone
could actually trade on, is there a measurable opportunity after uncertainty, fees,
freshness, liquidity and execution constraints? EXP-001 is the first user, but the owner wants
the same layer to serve weather, sports, prediction markets, crypto and macro later, without a
rewrite. The engine must never trust a price nobody offered, a stale input, an unverified
fee schedule, or a settlement rule it cannot read. It also has to keep every rejection as
research evidence.

**Alternatives.**
(a) Extend the EXP-001 code with a Stage B evaluator. This is fastest, but it welds the
    rules to one market and one model, and every later domain would copy them.
(b) Use a generic pandas-style scoring table. It would add a dependency, rows and floats
    invite midpoint and rounding mistakes, and it gives no typed rejection states.
(c) Typed, immutable contracts plus one pure evaluation function, fed by adapters.
    **Chosen.**

**Decision.**
- **Core** (`edge_lab.opportunity`, no I/O). It defines the contracts `Event`, `Market`,
  `Payoff`, `ExecutableQuote`, `ModelEstimate`, `Policy` and `Opportunity`.
  `evaluate(event, market, side, quote, estimate, fee_schedule, policy, as_of)` is a pure
  function.
  - Every (market, side) pair produces an `Opportunity`, whether it qualifies or not.
  - Each opportunity carries a primary reason and the full ordered reason list:
    `QUALIFY`, `MODEL_UNAVAILABLE`, `EVENT_MISMATCH`, `MARKET_CLOSED`, `RULES_UNRESOLVED`,
    `BOOK_MISSING`, `BOOK_STALE`, `MODEL_STALE`, `INVALID_PRICE`, `INSUFFICIENT_SIZE`,
    `FEE_UNVERIFIED`, `NO_EDGE`.
  - Opportunity ids are content hashes of the inputs.
  - Ranking is a deterministic total order.
- **Executable prices only.**
  - A buy is priced at the side's best ask, sized at the quantity displayed at that price.
  - `ExecutableQuote` has no midpoint or last-price field, so neither can be used by
    accident.
  - Missing inputs leave prices and edges `None`, never 0.
  - Anything older than `max_book_age` / `max_model_input_age`, or stamped after `as_of`
    (lookahead), fails closed.
- **Fees** (`edge_lab.fee_schedules`) are versioned objects with a `status`.
  - `kalshi-quadratic-taker-v1` reproduces the hash-pinned `fees.py` exactly (tested on 400
    random cases). It is `UNVERIFIED_CURRENT_SCHEDULE`: the public API confirms
    `fee_type=quadratic`, `fee_multiplier=1` and no pending changes, but the 0.07
    coefficient could not be read from a primary source.
  - A policy either requires verified fees (`FEE_UNVERIFIED`) or flags them. Either way,
    `Opportunity.claimable` is false unless the schedule is verified. A new schedule is a new
    id, never an edit to an old one.
- **Conservative probability** (`edge_lab.conservative`).
  - Method: one-sided 95% Wilson bounds at the model's own fit count. For YES this is the
    lower bound on P(YES); for NO it is 1 minus the upper bound.
  - The confidence level is part of the method id and is not tuned. No person or LLM
    statement can move it.
- **Venue adapter** (`edge_lab.kalshi_quotes`).
  - Kalshi's bid-only book is mapped as follows: the YES ask is 1 − the best NO bid, and the
    NO ask is 1 − the best YES bid, each sized at that level only.
  - Crossed or malformed books become `INVALID_PRICE`.
  - A market whose event ticker is not the expected one maps to an `unmapped:` event
    (`EVENT_MISMATCH`).
  - Rules are checked by probing the frozen resolver. An UNKNOWN result means
    `RULES_UNRESOLVED`.
- **Model adapter** (`edge_lab.exp001_stageb`).
  - The model is the Stage A–selected variant (V1), refit on all 3,551 usable days through
    2026-09-21, as the spec says. It refuses to run unless Stage A is PASS on the same dataset
    hash.
  - Bracket probability is the pmf summed over the integers the frozen resolver maps to YES.
  - The frozen Stage B policy is `EXP-001-stage-b-frozen-v1`:
    - point basis, net edge ≥ 0.05, 1 contract;
    - books ≤ 5 min old;
    - forecast ≤ 24 h at the cutoff;
    - fees flagged.
  - It reads only forward captures. A partial capture is evaluated for research while the
    Stage B day stays INVALID.
  - No historical executable price is manufactured.
- **CLI:** `edge-lab forward opportunities --date D`. It is read-only and emits every
  opportunity with its reasons.

**Tradeoffs.**
- The Wilson bounds cover sampling error only. Serial dependence and misspecification would
  widen them. This is disclosed in the module rather than hidden behind a tuned haircut.
- The engine prices only the best level. It is conservative for size (a depth walk could buy
  more), but it never overstates liquidity.
- With the fee schedule unverified, no net Stage B result is claimable until the owner
  supplies the fee-schedule PDF.

**Reconsider when:**
- a second venue or domain needs a contract field that is missing here;
- the fee schedule is verified (add a VERIFIED schedule id);
- a model provides a calibrated predictive interval better than a binomial bound;
- depth-aware sizing becomes necessary (Gate 6 sizing takes the displayed size as a hard
  cap).
