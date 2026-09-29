# EXP-002 A.C timing calibration tool (`exp002-timing`)

**Status:** tool only (code and tests). **It has not been run on any real data, and it is not run now.** The
coordinator runs it **once, on production**, after the pilot's T-6h weeks: at least 3 NFL weeks of paired capture,
about 2026-10-19. Its output is a **PROPOSED calibration input, not a freeze**. The owner's freeze review
(2026-10-22) decides.

**Procedure followed:**
- `RESEARCH_UNBLOCKING_DECISIONS.md` §A.C, calibration steps 1–4, and the pilot-data requirement item 2;
- `EXP002_FREEZE_PROPOSAL.md` §3 row 7, §4 (the exposure caveat) and §5 blocker 3.

## Command

```
python -m edge_lab.sports_evidence exp002-timing --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 \
    --delta-min 0.01 \
    --evidence-log /opt/market-edge-lab/app/experiments/EXP-002-nfl-consensus-vs-event-market/evidence_use.jsonl \
    --actor "<who runs it>" --code-version <deployed commit> [--as-of <ISO time>] [--out <file>]
```

**It refuses (exit 2, nothing shown)** without `--evidence-log`, `--actor` and a code version, or when the look
cannot be recorded in **EXP-002's own** log.

**`--delta-min` is required.** It is the minimum useful effect, in probability units. Freeze proposal row 11
PROPOSES δ_min(E1) = 1¢ gross, that is 0.01. The value is reported in the output and never assumed silently.

**The evidence log path above is illustrative.** Use the production copy of EXP-002's log, as the coordinator's
runbook does for other logged looks.

## What it reads, and what it never reads

It reads only the T-24h and T-6h horizons, and only timing and feature-side fields:
- `R_o`: the odds receipt of each due T-24h / T-6h capture, and each contributing sportsbook's `last_update` age at
  that receipt (from the canonical `odds_consensus`);
- `R_k`: the receipt of each Kalshi KXNFLGAME book of the **same horizon**, received from the horizon's window start
  to the target's own cutoff (`odds_schedule.deadline`). No later book is ever considered;
- for the book chosen under the provisional window [−5, +10], its spread and displayed ask depth;
- repeat books of one market and horizon at most 15 min apart, for the YES mid change.

It never reads:
- a T-60m target, T-60m capture or T-60m book, **or whether one exists** (#124: T-60m pair or book availability is
  weak label information);
- a book received after a target's cutoff;
- a settlement: the Kalshi catalog is built without the settled listing fields.

`tests/test_exp002_timing.py` pins this:
- a payload spy shows no T-60m book, later book or T-60m odds capture is loaded;
- no join, markout, E1 or outcome function is called;
- the output is **identical** with or without T-60m captures, T-60m books, later books and settled listings in the
  store.

**Limitation (as in the gate and E1 label-free paths).** The Kalshi catalog's SQL metadata read lists every stored
KXNFLGAME row's receipt time, including T-60m books, before the tool keeps only books up to each target's cutoff.
Those rows are never used, loaded or counted. Also, an odds snapshot of a coalesced capture slot can hold other
games' prices; only the target's own event is read.

## Logged before displayed

Every run first appends one event to EXP-002's `evidence_use.jsonl`:
- `FEATURE_INSPECTION`, role `DEVELOPMENT`;
- `viewed_features` true, `viewed_labels` false, `viewed_results` false;
- scope `sports:nfl:moneyline`, window = the first to the last kickoff covered;
- `dataset_sha256` = the output hash;
- `influenced_tuning` true: the look exists to choose a PROPOSED join limit. That is honest and conservative;
  the pilot games are DEVELOPMENT data in any case.

If the record fails, nothing is shown. The output and the event note carry the freeze proposal §4 caveat: "T-60m
book prices possibly seen (UNKNOWN, unlogged Terminal display)".

## What it computes (A.C step 2), per horizon

**Distributions.** Each is given as n, min, p10, median, p90 and max:
- the skew `R_k − R_o` of the chosen book at [−5, +10], and of the nearest horizon book;
- the book age and odds age at the decision time `D = max(R_k, R_o)`;
- per-book sportsbook `last_update` age;
- spread;
- displayed ask depth.

**Pair windows.** For each of **[−5, +5], [−5, +10] and [−10, +15]**, it reports the fraction of due T-6h pairs kept
(and T-24h, for information), using the canonical prospective book choice `sports_evidence.pick_book`.

A **due T-6h pair** is a due T-6h target side whose odds capture is usable and whose market is mapped by the cutoff.
Only the window decides whether such a side is kept. Sides lost upstream are counted in `coverage` and are the same
for every window.

**Short-interval drift.** The absolute YES-mid change between consecutive books of one market and horizon at most
15 min apart. A window uses the pairs whose gap is within its larger side (5, 10 or 15 min).

## The recommendation (A.C step 3, mechanical)

The rule picks **the narrowest window that keeps ≥ 70% of due T-6h pairs and whose median absolute drift is
≤ δ_min / 3.**
- Both limits are inclusive.
- Narrowest means the smallest width, then the smaller after-side, then the smaller before-side.
- A window without due pairs or without a drift pair does not qualify (it fails closed).

If none qualifies, it reports [−5, +10] with its attrition and the option-(b) note: capture the book in the same run
as the odds, a runner change that needs review.

**All three windows tried are reported.** Each counts against EXP-002's variant budget (A.C step 4). Pairs lost to
skew stay in the denominators.

## When to run it, and after

- **Once**, after the pilot's T-6h weeks (≥ 3 NFL weeks, about 2026-10-19), before any pilot markout or E1 result is
  viewed (A.G step 5 order).
- It must not be re-run to "improve" a window. A second look is another logged FEATURE_INSPECTION, and every window
  it tries counts against the budget.
- The recommended window goes to the freeze review as a PROPOSED join variant. Changing `JoinPolicy` is a separate,
  reviewed change.

## UI

There is **no UI change**. This is a one-off, logged development look, run from the CLI by the coordinator. A
Terminal surface would invite repeated unlogged looks at timing data that feeds a frozen limit. The Terminal's
existing Family A views and the E1 and gate paths are untouched. Gates v2/v3, E1, `protocol.toml` and EXP-001 are
unchanged.
