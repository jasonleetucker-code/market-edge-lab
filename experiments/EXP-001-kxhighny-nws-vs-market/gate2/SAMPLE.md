# Gate 2 settlement sample: definition (fixed before evaluation)

Written on 2026-09-22 before the held-out window was evaluated. The windows are defined by
date, not by outcome. No event inside a window may be excluded; a missing or unparseable
event is reported as UNRESOLVED and counts against the gate.

| Window | Target dates | Source of market data | Status when this file was written |
|---|---|---|---|
| A: live | 2026-07-16 → 2026-09-21 (every settled event returned by `GET /markets?series_ticker=KXHIGHNY&status=settled` on 2026-09-22) | live Kalshi API | **Already inspected** during exploration: its `expiration_value`s were compared with NWS CLI before this file existed. Reported for completeness, not as an independent test. |
| B: held-out | 2025-01-01 → 2025-12-31 (every KXHIGHNY event in `GET /historical/markets?series_ticker=KXHIGHNY`) | Kalshi historical API | **Not inspected**: market structure only (fields present); no outcome, value or CLI comparison had been looked at. |

Independence unit: the **daily event** (one target date). Brackets within an event share a
single underlying value and are not independent observations.

Pass rule for gate 2: in each window, every event's expected outcome (from the deterministic
parser and the applicable evidence) matches Kalshi's recorded `result` for every bracket, or
the mismatch has a documented, evidence-backed explanation. UNKNOWN is never counted as a match.

## Amendment 1 (2026-09-22, before window C was evaluated)

**Why.** The independent review pointed out that window B tuned the procedure. Two
report-selection rules were added after they failed or were needed on window B events:
skipping a final report without a value (25FEB21), and NHIGH delayed determination
(25DEC03, which was a mis-prediction under the original "first final" procedure). So window
B is **not** a clean held-out test of the final procedure. Its result under the original
procedure is reported alongside it.

**Window C (fresh validation).** Target dates 2024-01-01 → 2024-12-31. The population is
every HIGHNY and KXHIGHNY event returned by `GET /historical/markets?series_ticker=HIGHNY`
and `?series_ticker=KXHIGHNY`, deduplicated by market ticker. The procedure is **frozen at
commit 9f28602** (`edge_lab.settlement`, `edge_lab.nws_cli.settlement_value`,
`edge_lab.settlement_audit`). It is evaluated once, and it is not changed in response to
window C's results. Any mismatch is reported as-is. Window C outcomes, values and CLI
comparisons had not been examined when this amendment was written; only the fact that 2024
market records exist had been checked.
