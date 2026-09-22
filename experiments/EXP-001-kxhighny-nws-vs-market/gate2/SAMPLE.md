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
