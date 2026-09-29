# NHL prospective evidence: deployment and activation record (NHL-C, 2026-09-29)

Authority: owner directive of 2026-09-29 (`docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`, issue #134;
EXECUTION_PLAN entry of the same date). Runbooks: ADR 0039 (Odds, sport-aware planner) and ADR 0040 §"Activation
dependency on NHL-A, and the NHL-C runbook" (Kalshi). All times come from the VPS clock (America/New_York unless
marked Z).

## Sequence

| Time (ET) | Step | Evidence |
|---|---|---|
| 13:22 | 20 manual opening-night Kalshi custom targets planned (existing ADR 0030 path) | directive record §Opening-night |
| 14:05 | All 10 team markets captured by the existing observe timer (18:05:13–21Z) | `price_observations` rows, phase `custom`, origin `manual` |
| 15:10 | **Deploy #137 (NHL-A) as 7e0b81d** via `/root/deploy.sh`: preflight PASS, backups verified before and after, fail-closed PASS, 0 failed units, 13 timers | deploy output |
| 15:11 | NHL Odds preview (runbook `systemd-run … odds plan --sport icehockey_nhl --markets h2h --regions us --offsets 60m`; quota-free events call only) | PROVEN: 33 events discovered; 6 September T-60m slots admitted (worst case 54 of 450); October slots not admitted (NFL first) |
| 15:12 | `EDGE_LAB_ODDS_NHL=on` appended to `/etc/market-edge-lab/env` (backup `/root/env.bak-pre-nhl-20260929`) | ADR 0039 |
| 15:15 | First tick with NHL on: NFL line IDLE (unchanged); NHL discovery REFRESHED, stored as snapshot 553; joint proof PROVEN, headroom 402 (NFL has no remaining September slot), NHL 6 slots admitted | journal |
| 15:36 | **Deploy #136 (NHL-B) as c9a2406**: preflight PASS, backups verified, fail-closed PASS, 0 failed units, 13 timers; `EDGE_LAB_ODDS_NHL=on` kept by install.sh | deploy output |
| 15:38 | Kalshi NHL preview (`python -m edge_lab.price_observations nhl-dry-run`): schedule OK (snapshot 553); `would_plan` 64 targets (16 games × 2 team markets × T-6h and T-60m), of which 6 are MISSED on plan (3 games' T-6h already past); 0 unmapped; 0 requests or writes; week bound 727 (this week: 87 expected, 174 worst) | dry-run output |
| 15:38 | `EDGE_LAB_KALSHI_NHL_CAPTURE=on` appended (backup `/root/env.bak-pre-kalshi-nhl-20260929`) | ADR 0040 step 3 |
| 15:50 | First observe tick with NHL on: 64 targets planned, matching the preview (including 6 MISSED `NOT_COLLECTED_BEFORE_ACTIVATION`); capture NOTHING_DUE | journal |
| 16:05 | First scheduled Kalshi NHL captures: FLA@CAR T-60m (both team markets), VAN@EDM T-6h (both) | `price_observations` |
| 16:15 | First NHL Odds capture: FLA@CAR T-60m h2h, 1 credit. The provider lists that game's commence time as 21:10:47Z; NHL.com lists 21:00Z. So the Odds T-60m targets are 60 min before the provider's time, about 50 min before the official start (a capture at the 16:15 tick is about T-45m of the official 17:00 start). All NHL Odds commence times seen tonight run about 10 min after NHL.com's. | `odds_targets` CAPTURED |
| 16:31 | **Deploy #139 as fb2f5fd** via `/root/deploy.sh`: preflight PASS, backups verified before and after, fail-closed PASS, 0 failed units, 13 timers; both NHL switches kept by install.sh | deploy output |

## Opening night (2026-09-29): captured by 16:18 ET, missed, and planned

| Game (ET) | Kalshi | Odds API h2h |
|---|---|---|
| FLA@CAR 17:00 | manual 14:05 and 16:05 captured; scheduled T-60m 16:05 captured; T-6h MISSED (before activation) | T-60m captured 16:15 |
| MTL@TOR 19:00 | manual 14:05 captured; manual 18:50 and scheduled T-60m at 17:35 (shifted, T-85m) planned, not verified; T-6h MISSED | T-60m slot 18:35 (quiet window; T-25m official), planned, not verified |
| NYR@BOS 20:00 | manual 14:05 captured; manual 19:05 and scheduled T-60m planned, not verified; T-6h MISSED | T-60m slot 19:10 (provider time 20:10), planned, not verified |
| VAN@EDM 22:00 | manual 14:05 and scheduled T-6h (16:05) captured; manual 21:05 and scheduled T-60m planned, not verified | T-60m slot 21:10 (provider time 22:10), planned, not verified |
| CHI@VGK 22:30 | manual 14:05 captured; scheduled T-6h (16:35), manual 21:35 and scheduled T-60m planned, not verified | T-60m slot 21:40 (provider time 22:40), planned, not verified |

- Nothing was captured after its horizon and relabelled.
- No historical archive was used.
- The Odds API T-6h and T-24h horizons were never in the NHL policy, which is T-60m only. They were not missed; they were never planned.
- Rows after 16:18 ET are NOT yet verified (HANDOFF UNRESOLVED).

## Pause and rollback

- Set either switch to `off` in `/etc/market-edge-lab/env`; install.sh keeps it.
  - Odds NHL: `odds run --sport icehockey_nhl` returns DISABLED and sends nothing.
  - Kalshi NHL: pending targets are held MISSED `NHL_CAPTURE_DISABLED`.
- Stored evidence is kept.
- A code rollback uses the release saved in `~dynasty/edgelab-release/prev-<sha>`.

## Not changed

- NFL Odds caps and the 450 ceiling.
- The NFL Kalshi 295/week bound.
- EXP-001, and the EXP-002 sample and protocol.
- The timers: still 13, with no new timer or service.
- No paid plan, credentials, orders or in-play collection.
