# 0010 — EXP-001 decision time and forecast availability

Status: Accepted (2026-09-22, Gate 3). Chosen before any model result existed.

**Problem.** A point-in-time dataset needs a fixed moment at which the hypothetical
strategy decides, and a rule for which forecast it could have seen at that moment. Without
both, a backtest can quietly use forecasts issued later, corrections published later, or
settlement information.

**Alternatives.**
- (a) Morning of D (e.g. 09:00): more information, but the market has had a night to absorb
  it and the forecast problem becomes nowcasting.
- (b) 18:00 America/New_York on D−1.
- (c) Several decision times per day. More rows, but they are not independent, and choosing
  among them after seeing results is a researcher degree of freedom.
- (d) "Latest forecast" with no fixed time. This leaks future information.

**Decision.** (b). For target date D:
- decision time = **18:00 America/New_York on D−1**, converted to UTC with the US DST rule in
  force since 2007 (`edge_lab.nws_cli._is_dst`, stdlib only). 18:00 is never inside a DST
  transition hour.
- availability cutoff = decision − **30 minutes**. This is a conservative buffer for
  dissemination; the NWS usually delivers within minutes.
- the forecast used is the **latest PFMOKX issuance with issuance time ≤ cutoff** that
  contains a Central Park daytime maximum for D.
- issuance time = the WMO header time. The typed local line may be up to 15 minutes
  earlier; if the header is missing or disagrees beyond that, the product is ambiguous and
  never used (`nws_pfm.WMO_LAG_TOLERANCE`).
- a forecast older than **24 h** at the cutoff is stale, so the row is excluded
  (`PFM_STALE_AT_CUTOFF`). No issuance at all gives `NO_PFM_BEFORE_CUTOFF`.
- anything issued after the cutoff is never considered. Suffixed products (`CCx`, `RRx`,
  `AAx`) are never used at all, because their transmission time is unknown. Products with
  the same latest minute that disagree exclude the row.
- availability time (issuance + 30 min) is recorded separately from issuance time.

Reasons for (b):
- the NWS afternoon PFM package (historically about 19–20Z, since 2026 about 18Z, i.e.
  14:00–16:30 local) is out before 17:30 on essentially every day;
- Kalshi lists D's markets around 10:00 ET on D−1, so they are open at 18:00;
- it fits an evening human-review window for a later shadow or paper stage;
- it gives about 24 h lead, before the morning-of observations.

**Tradeoffs.** Only one row per day, which keeps the sample small (see `gate3/POWER.md`).
Early-evening updates (after 17:30) are ignored by design. The 30-minute buffer is a guess
at dissemination delay and is conservative; it was not tuned.

**Observed after the decision, before any error was computed:** NWS PFMOKX issuance
thinned from mid-2025, so forecasts at the decision time are older in 2025–2026
(`gate3/QUALITY.md`). The rule is unchanged.

**Reconsider when** prospective collection shows markets are not reliably open or liquid at
18:00, or an NWS product schedule change moves the afternoon package past 17:30. Any
change is a new experiment or a dated amendment, never an edit of EXP-001.
