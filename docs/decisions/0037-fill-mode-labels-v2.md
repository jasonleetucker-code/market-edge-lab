# ADR 0037: Fill-mode labels v2: first detection is zero-latency, the best observation is hindsight

**Status:** Accepted 2026-09-25 for review (research-unblocking directive §7,
`docs/owner/2026-09-25-research-unblocking-directive.md`). It amends the wording of ADR 0034 item
"conservative (detection) and less-conservative (the best single observation)". It changes no
arithmetic, no verdict rule and nothing in EXP-001.

## Problem

`research_economics` replays each opportunity episode in two fill modes. v1 described them as:

- **conservative** (fill at detection): the episode's first qualifying observation;
- **less conservative** (the best single observation): the observation with the most value at the
  replayed size.

Both names claim more than the evidence supports:

1. "Fill at detection" assumes an order could have been filled against the first observed quote
   at the moment it was received. It ignores decision and submission delay. Nothing shows that the
   quote survived that delay, so the mode is not conservative about latency.
2. The best observation is chosen **after the whole episode has been seen**. No prospective policy
   could make that choice. It is an oracle, a hindsight upper bound. Calling it "less conservative"
   suggests an achievable, merely optimistic, policy.

## Decision

1. The enum values `FillMode.CONSERVATIVE` and `FillMode.LESS_CONSERVATIVE` are **kept** for
   compatibility with v1 reports and callers.
2. Their meaning is stated by `research_economics.FILL_MODE_SEMANTICS` (`fill-mode-labels-v2`):

   | Enum | Label | Prospective selection | Delay-adjusted | Executable performance | Permitted use |
   |---|---|---|---|---|---|
   | CONSERVATIVE | `FIRST_DETECTION_ZERO_LATENCY` | yes | no | no | the screen's lower-side band (the CONTINUE test); a research state |
   | LESS_CONSERVATIVE | `HINDSIGHT_UPPER_BOUND` | no | no | no | an upper bound only: it may rule a family out (UNVIABLE, BELOW_MINIMUM_USEFUL), never support CONTINUE |

3. `ECONOMICS_VERSION` becomes `research-economics-v2`. Every screen report carries:
   - `fill_modes`, the semantics above per mode key;
   - `executable_performance`, which says "NONE: …";
   - a label in the note of every per-mode figure.

   Replay results and capacity rows carry `mode_label`. The report hash changes because the
   report content changed; the arithmetic did not.
4. Wording is aligned:
   - `sports_evidence.FILL_MODES` texts;
   - `docs/RESEARCH_PRINCIPLES.md` ("Economics first");
   - the DRAFT EXP-002 `protocol.toml` and `experiment.toml` fill text.

   EXP-003's protocol never used these words.
5. A test pins the rule that a hindsight-only surplus never yields CONTINUE
   (`tests/test_research_economics_fill_labels.py`). The v1 verdict logic already behaved this way.

## Alternatives considered

- **Rename the enum values.** Rejected. It would break v1 report readers and the Terminal's
  rendering for no gain; labels carry the meaning.
- **Drop the hindsight mode.** Rejected. An upper bound is useful for ruling a family out
  cheaply ("even an oracle cannot clear fixed costs").
- **Add a delay-adjusted mode now** (fill at the first observation received at least *d* after
  detection). Deferred. The directive's section 7 is a correctness review, "not permission to
  rebuild the execution simulator". It is a candidate registered variant once paired captures
  exist.

## Tradeoffs

- The CONTINUE test still rests on a zero-latency first-detection bound, so CONTINUE is weaker
  evidence than its v1 name suggested. That is the honest reading. The verdict was never an edge
  claim.
- Reports and hashes produced by v1 are not comparable byte for byte with v2. No committed result
  file contains a v1 economic screen.

## What would make us reconsider

- Paired captures dense enough to measure how long a quote survives. A delay-adjusted mode would
  then replace zero-latency first detection in the CONTINUE test.
- Real fills (gate 8 or later), which would make a REALIZED edge kind meaningful.

## Frozen EXP-001

Not touched: its fill policy, preregistration, `fees.py`, ledger and results. EXP-001 does not
use `research_economics`.
