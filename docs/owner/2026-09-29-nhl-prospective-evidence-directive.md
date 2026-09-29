# Owner directive, 2026-09-29: continue EXP-002 correctness work + begin bounded NHL prospective evidence

Source: the owner's chat message to the laptop Claude Code coordinator session, received 2026-09-29 at about
13:15 America/New_York (VPS clock). Durable owner record: issue #134 ("[Owner Idea] NHL prospective evidence").
Recorded **in substance**, with the authority wording kept. An agent records a grant; it never creates one.

## Owner statement

"Hockey starts tonight, so we need to start collecting data for that as well."

## Two parallel goals

- **A. EXP-002.** Finish the remaining pre-freeze correctness work in dependency order:
  1. sourced tie and not-played bounds;
  2. a label-safe timing calibration;
  3. KXNFLGAME fee verification;
  4. the owner freeze review.

  Do not reopen the E1 and label-proxy fixes (#129 to #132) unless evidence shows a defect. Do not weaken any
  blocker because NHL collection starts.
- **B. NHL.** Begin truthful prospective NHL data collection before the opening weeks become irrecoverable.

## Classification

NHL is **DATA_COLLECTION / DEVELOPMENT_ONLY** until a future hockey experiment is separately allocated: a #96
research slot, an experiment id, a mechanism, a protocol, an evidence-consumption window and preregistration. It is
**not** a third active research family.

EXP-002 stays NFL-specific. NHL is never mixed into its sample, its effective N, its validation or its pass/fail
decision. NFL protocol thresholds are not declared to apply to NHL.

## Authorized (bounded)

The owner's instruction is treated as authorization to implement and **activate** a bounded free/public NHL
prospective evidence collector, subject to:
- exact provider quota proof;
- no paid plan;
- no financial trading;
- no order or account credentials;
- no increased NFL limits;
- no new high-frequency or in-play stream;
- the existing deployment and testing gates: tests, independent review, exact-head CI, quota proof, protected
  windows and deploy preflight.

v1 scope:
- **The Odds API `icehockey_nhl`, `h2h` only**, region us. Horizons are evaluated in priority order:
  1. T-60m;
  2. T-6h, only if the exact combined monthly proof fits;
  3. T-24h, only if justified.

  No spreads or totals.
- **Kalshi `KXNHLGAME` (game winner) only**, public and keyless, under its own exact request bound. No
  KXNHLTOTAL, period, prop, next-team or futures markets.

Shared constraints:
- **One shared Odds API quota ledger and one monthly ceiling (450)** for NFL, NHL and any future sport. No separate
  hockey ledger.
- One shared operational contract for protected windows.

Priority:
- EXP-001 protected collection comes first.
- Existing NFL guarantees stay intact: NHL never consumes an NFL reservation.
- The owner-approved NFL weekly Kalshi request bound is unchanged.

Opening night:
- No target is captured later and labelled with a horizon it missed.
- Past targets are MISSED with `NOT_COLLECTED_BEFORE_ACTIVATION`, or the repository-consistent equivalent.
- A one-time manual prospective observation is labelled as such, with its exact receipt time.
- Historical archives never repair a missed prospective observation.

Outcomes are preserved separately from features, with label separation designed now. The UI is private Terminal
coverage only.

## Needs explicit owner approval before activation (surface the delta; do not smuggle)

A paid tier or paid data; a new credential permission; a materially larger provider budget or a higher ceiling; a
new systemd timer or production service; high-frequency or in-play streaming.

## Not authorized (unchanged)

- Orders (real or authenticated paper), account reads, credentials.
- Margin, deposits or withdrawals, outside capital.
- A gate advance. EXECUTION_NOT_AUTHORIZED stays enforced.
- Any NHL model (winner, goal, goalie, player, xG, ML).
- Hockey statistics collection beyond what a future protocol justifies.

## Relationship to #122

Hockey is a candidate for future in-play research, as a hypothesis. No NHL in-play or high-frequency collection is
started here. The first in-play sport is chosen by #122's evidence.

## Opening-night record (coordinator, 2026-09-29)

At 13:22 ET the coordinator planned 20 **manual opening-night observations** for the five 2026-09-29 games. Start
times are from the public NHL schedule API: FLA@CAR 17:00, MTL@TOR 19:00, NYR@BOS 20:00, VAN@EDM 22:00 and
CHI@VGK 22:30 ET.

They go through the existing, reviewed ADR 0030 custom-target path:
`edge-lab observe plan --custom-venue kalshi --custom-market KXNHLGAME-26SEP29<GAME>-<TEAM> --custom-at <time>`.
The existing `edgelab-observe` timer captures them, within its existing request, run and protected-window limits.

They are stored as phase `custom`, origin `manual`, and never as T-24h, T-6h or T-60m. They are this directive's
MANUAL_OPENING_NIGHT_OBSERVATION, and each row carries its exact receipt time.

Capture times (ET):

| Captures | Time |
|---|---|
| All 10 team markets | 14:05 |
| FLA@CAR | 16:05 |
| MTL@TOR | 18:50 (the 17:40-18:50 protected window prevents one nearer T-60m) |
| NYR@BOS | 19:05 |
| VAN@EDM | 21:05 |
| CHI@VGK | 21:35 |

No NHL sportsbook (Odds API) observation exists for 2026-09-29, because the scheduled collector did not exist.
Those horizons are missing: NOT_COLLECTED_BEFORE_ACTIVATION.
