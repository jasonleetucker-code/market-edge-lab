"""`STARTER_MAX_7D_V1`: starter-phase capital must be reusable within 168 hours (ADR 0018).

The owner's rule (issue #32, clarified 2026-09-23): a new starter-phase position is eligible
only if its committed capital, or the settled balance it becomes, is conservatively
expected to be **available to trade again on the same venue** within 168 elapsed hours of
the new commitment.

Separate clocks are tracked, and only one of them governs:
- `event_end`: when the underlying event or observation ends;
- `resolution_eta`: a conservative bound on when the outcome is settled (the venue's
  expected resolution, plus its settlement timer, plus the evidence buffer);
- `tradable_cash_release_eta`: settled cash usable for a new trade on this venue. **This is
  the governing clock.**
- `withdrawable_cash_eta` and `bank_receipt_eta`: reported only. Bank or withdrawal delays
  never count once the money can trade again.

The normal-path estimate is the venue's expected resolution, plus the settlement timer,
plus an evidence-derived buffer (`SettlementLagEvidence`), plus the venue's documented
post-settlement trading hold. The contractual latest resolution (for Kalshi,
`latest_expiration_time`, used only when published data has a material error) is reported
as `abnormal_path_bound`. It does not govern.

The rule fails closed:
- unknown timing, unverified settlement evidence, a disputed or rescheduled market, or a
  plan that depends on selling before settlement is never eligible;
- a position that later runs past its expected release becomes a
  `SEVEN_DAY_POLICY_EXCEPTION`: the capital stays reserved and nothing is force-sold.

This is an operational eligibility overlay. It never changes the frozen EXP-001 research
signal or its research account (ADR 0016, ADR 0018).
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .freshness import parse_utc
from .opportunity import MarketTiming
from .venues import VenueCashTiming

POLICY_ID = "STARTER_MAX_7D_V1"
MAX_HORIZON = timedelta(hours=168)  # elapsed time; exactly 168 h is eligible
# Prospective only: operational fills whose decision time is on or after this instant are
# checked. Earlier ledger entries are never re-evaluated or rewritten.
EFFECTIVE_FROM_UTC = "2026-09-24T00:00:00+00:00"
LAG_BUFFER_MULTIPLE = 2  # buffer = ceil(2 x the worst observed normal-path lag), in whole hours


class StarterReason(str, Enum):
    HORIZON_OVER_7D = "HORIZON_OVER_7D"
    TRADABLE_CASH_RELEASE_UNKNOWN = "TRADABLE_CASH_RELEASE_UNKNOWN"
    SETTLEMENT_TIMING_UNVERIFIED = "SETTLEMENT_TIMING_UNVERIFIED"
    POST_SETTLEMENT_HOLD = "POST_SETTLEMENT_HOLD"
    DELAYED_OR_DISPUTED = "DELAYED_OR_DISPUTED"
    EXIT_DEPENDS_ON_LIQUIDITY = "EXIT_DEPENDS_ON_LIQUIDITY"


DISPUTED_STATUSES = frozenset({"disputed", "amended"})
# Venue lifecycle words under which a new commitment can be on the normal path. Any other
# known status (closed, determined, finalized...) is not normal-path for a new commitment.
OPEN_STATUSES = frozenset({"active", "open", "initialized"})
# Venue cash-timing statuses the policy accepts. DOCUMENTED_INFERRED: the venue documents that
# settlement moves funds into the account balance, and reusability for trading is inferred
# from that; it is shown on every verdict so the owner can see it is an inference.
ACCEPTED_CASH_STATUSES = frozenset({"DOCUMENTED", "DOCUMENTED_INFERRED"})


@dataclass(frozen=True)
class SettlementLagEvidence:
    """How late a series has settled after its venue-stated normal-path time.

    lag = settlement_ts - (expected resolution + settlement timer), per market; the buffer
    is `ceil(LAG_BUFFER_MULTIPLE * max lag)` whole hours, never below zero."""

    venue: str
    scope: str
    n_events: int
    n_markets: int
    min_lag_hours: float
    p99_lag_hours: float
    max_lag_hours: float
    buffer: timedelta
    evidence_path: str
    derived_from: str


@dataclass(frozen=True)
class StarterVerdict:
    policy_id: str
    eligible: bool
    reasons: tuple[str, ...]
    commitment_utc: str
    event_end_utc: str | None
    resolution_eta_utc: str | None
    tradable_cash_release_eta_utc: str | None  # the governing clock
    withdrawable_cash_eta_utc: str | None
    bank_receipt_eta_utc: str | None
    abnormal_path_bound_utc: str | None  # reported only
    elapsed_hours_to_tradable: str | None
    max_hours: int
    detail: tuple[str, ...]
    # Provenance: which evidence produced the ETA, so a later change of evidence is auditable.
    timing_source: str | None = None
    lag_evidence_path: str | None = None
    lag_buffer_hours: int | None = None
    cash_timing_status: str | None = None
    cash_timing_evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.__dict__)
        out["reasons"], out["detail"] = list(self.reasons), list(self.detail)
        return out


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def assess(*, commitment: datetime | str, timing: MarketTiming | None, lag: SettlementLagEvidence | None,
           cash: VenueCashTiming | None, planned_exit_utc: datetime | str | None = None) -> StarterVerdict:
    """Is committing capital at `commitment` eligible under `STARTER_MAX_7D_V1`?

    `planned_exit_utc` is a hoped-for sale before settlement. It never makes a position
    eligible: resale depends on liquidity that is not guaranteed."""
    start = parse_utc(commitment)
    if start is None:
        raise ValueError("commitment must be a timezone-aware time")
    reasons: list[StarterReason] = []
    detail: list[str] = []
    event_end = parse_utc(timing.event_end_utc) if timing else None
    expected = parse_utc(timing.expected_resolution_utc) if timing else None
    latest = parse_utc(timing.latest_resolution_utc) if timing else None
    timer = timing.settlement_timer_seconds if timing else None

    if timing is None or expected is None or timer is None:
        reasons.append(StarterReason.TRADABLE_CASH_RELEASE_UNKNOWN)
        detail.append("the venue's expected resolution time or settlement timer is unknown")
    elif not timing.lifecycle_status:
        reasons.append(StarterReason.TRADABLE_CASH_RELEASE_UNKNOWN)
        detail.append("the market's lifecycle status is unknown, so the normal path cannot be assumed")
    if lag is None:
        reasons.append(StarterReason.SETTLEMENT_TIMING_UNVERIFIED)
        detail.append("no settlement-lag evidence for this series")
    if cash is None or cash.status not in ACCEPTED_CASH_STATUSES or cash.tradable_hold is None:
        reasons.append(StarterReason.SETTLEMENT_TIMING_UNVERIFIED)
        detail.append("the venue's post-settlement trading hold is not documented")
    status = (timing.lifecycle_status or "").lower() if timing is not None else ""
    if timing is not None and (status in DISPUTED_STATUSES or timing.rescheduled):
        reasons.append(StarterReason.DELAYED_OR_DISPUTED)
        detail.append(f"market is {timing.lifecycle_status or 'rescheduled'}; its timing is not normal-path")
    elif status and status not in OPEN_STATUSES:
        reasons.append(StarterReason.DELAYED_OR_DISPUTED)
        detail.append(f"market status {timing.lifecycle_status!r} is not open; a new commitment is not normal-path")
    if expected is not None and timer is not None and expected + timedelta(seconds=timer) < start:
        # Already past the venue's own expected resolution: delayed, whatever the buffer says.
        reasons.append(StarterReason.DELAYED_OR_DISPUTED)
        detail.append("the venue's expected resolution time has already passed: the market is delayed")

    resolution = tradable = withdrawable = bank = None
    if expected is not None and timer is not None and lag is not None:
        resolution = expected + timedelta(seconds=timer) + lag.buffer
    if resolution is not None and cash is not None and cash.tradable_hold is not None:
        tradable = resolution + cash.tradable_hold
        if cash.withdrawable_hold is not None:
            withdrawable = tradable + cash.withdrawable_hold
            if cash.bank_receipt is not None:
                bank = withdrawable + cash.bank_receipt
    elapsed = None if tradable is None else tradable - start
    if elapsed is not None and elapsed > MAX_HORIZON:
        reasons.append(StarterReason.HORIZON_OVER_7D)
        detail.append(f"tradable cash expected {elapsed} after commitment (limit {MAX_HORIZON})")
        if cash is not None and cash.tradable_hold and resolution - start <= MAX_HORIZON:
            reasons.append(StarterReason.POST_SETTLEMENT_HOLD)
            detail.append(f"settles within the limit, but the venue holds settled cash for {cash.tradable_hold}")
        if planned_exit_utc is not None:
            reasons.append(StarterReason.EXIT_DEPENDS_ON_LIQUIDITY)
            detail.append("a planned early sale does not count: resale liquidity is not settlement")
    if event_end is not None and resolution is not None and event_end - start <= MAX_HORIZON < resolution - start:
        detail.append("the event ends within 168 h but settlement does not")
    if latest is not None:
        detail.append(f"abnormal-path bound (contractual latest resolution) {latest.isoformat()}: reported only")

    ordered = tuple(dict.fromkeys(r.value for r in reasons))
    return StarterVerdict(
        policy_id=POLICY_ID, eligible=not ordered, reasons=ordered, commitment_utc=start.isoformat(),
        event_end_utc=_iso(event_end), resolution_eta_utc=_iso(resolution),
        tradable_cash_release_eta_utc=_iso(tradable), withdrawable_cash_eta_utc=_iso(withdrawable),
        bank_receipt_eta_utc=_iso(bank), abnormal_path_bound_utc=_iso(latest),
        elapsed_hours_to_tradable=None if elapsed is None else f"{elapsed.total_seconds() / 3600:.4f}",
        max_hours=int(MAX_HORIZON.total_seconds() // 3600), detail=tuple(detail),
        timing_source=timing.source if timing else None,
        lag_evidence_path=lag.evidence_path if lag else None,
        lag_buffer_hours=int(lag.buffer.total_seconds() // 3600) if lag else None,
        cash_timing_status=cash.status if cash else None,
        cash_timing_evidence=cash.evidence if cash else None,
    )


def in_effect(as_of: datetime | str) -> bool:
    at = parse_utc(as_of)
    return at is not None and at >= parse_utc(EFFECTIVE_FROM_UTC)


# --------------------------------------------------------------------------- lag evidence

def derive_lag_evidence(markets: Iterable[Mapping[str, Any]], *, venue: str, scope: str, evidence_path: str,
                        derived_from: str) -> SettlementLagEvidence | None:
    """Settlement lag after the venue's normal-path time, over settled markets of one series.

    Only markets whose event ticker starts with `scope-` and that carry a settlement time,
    an expected resolution and a settlement timer count. None if there are none."""
    lags: list[float] = []
    events: set[str] = set()
    for m in markets:
        event = str(m.get("event_ticker") or "")
        if not event.startswith(f"{scope}-"):
            continue
        settled, expected = parse_utc(m.get("settlement_ts")), parse_utc(m.get("expected_expiration_time"))
        timer = m.get("settlement_timer_seconds")
        if settled is None or expected is None or not isinstance(timer, int):
            continue
        lags.append((settled - (expected + timedelta(seconds=timer))).total_seconds() / 3600)
        events.add(event)
    if not lags:
        return None
    lags.sort()
    worst = lags[-1]
    return SettlementLagEvidence(
        venue=venue, scope=scope, n_events=len(events), n_markets=len(lags), min_lag_hours=round(lags[0], 4),
        p99_lag_hours=round(lags[min(len(lags) - 1, int(0.99 * len(lags)))], 4), max_lag_hours=round(worst, 4),
        buffer=timedelta(hours=max(0, math.ceil(LAG_BUFFER_MULTIPLE * worst))),
        evidence_path=evidence_path, derived_from=derived_from,
    )


_ROOT = Path(__file__).resolve().parents[2]
KXHIGHNY_LAG_FIXTURE = "tests/fixtures/gate3/kalshi_markets_all_2026-09-22.json.gz"
KXHIGHNY_LAG_EVIDENCE = "experiments/EXP-001-kxhighny-nws-vs-market/venue_timing/kalshi_kxhighny_settlement_lag.json"


def _load_lag(path: str) -> SettlementLagEvidence | None:
    """The committed lag evidence. A missing or malformed file means no evidence (fail closed)."""
    try:
        data = json.loads((_ROOT / path).read_text(encoding="utf-8"))
        return SettlementLagEvidence(
            venue=data["venue"], scope=data["scope"], n_events=int(data["n_events"]),
            n_markets=int(data["n_markets"]), min_lag_hours=float(data["min_lag_hours"]),
            p99_lag_hours=float(data["p99_lag_hours"]), max_lag_hours=float(data["max_lag_hours"]),
            buffer=timedelta(hours=int(data["buffer_hours"])), evidence_path=path,
            derived_from=data["derived_from"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def lag_evidence(venue: str, scope: str | None) -> SettlementLagEvidence | None:
    """Registered settlement-lag evidence for a venue's series. Never shared across series."""
    if (venue, scope) == ("kalshi", "KXHIGHNY"):
        return _load_lag(KXHIGHNY_LAG_EVIDENCE)
    return None


def kxhighny_lag_from_fixture() -> SettlementLagEvidence | None:
    """Re-derive the committed KXHIGHNY evidence from the captured market history."""
    with gzip.open(_ROOT / KXHIGHNY_LAG_FIXTURE, "rt", encoding="utf-8") as fh:
        markets = json.load(fh)
    return derive_lag_evidence(markets, venue="kalshi", scope="KXHIGHNY", evidence_path=KXHIGHNY_LAG_EVIDENCE,
                               derived_from=KXHIGHNY_LAG_FIXTURE)


# --------------------------------------------------------------------------- exceptions

def policy_exceptions(fills: Iterable[Mapping[str, Any]], open_position_ids: set[str],
                      now: datetime) -> list[dict[str, Any]]:
    """Starter-checked positions that are still open past their expected tradable release.

    Each is a `SEVEN_DAY_POLICY_EXCEPTION`. The position stays open, its capital stays
    reserved (risk counts it until it settles) and nothing is sold."""
    out = []
    for fill in fills:
        verdict = fill.get("starter_policy")
        if not isinstance(verdict, Mapping) or fill.get("fill_id") not in open_position_ids:
            continue
        eta, committed = parse_utc(verdict.get("tradable_cash_release_eta_utc")), parse_utc(verdict.get("commitment_utc"))
        overdue = eta is not None and now > eta
        over_horizon = committed is not None and now - committed > MAX_HORIZON
        if overdue or over_horizon:
            out.append({"type": "SEVEN_DAY_POLICY_EXCEPTION", "policy_id": verdict.get("policy_id", POLICY_ID),
                        "fill_id": fill["fill_id"], "market_id": fill.get("market_id"),
                        "commitment_utc": verdict.get("commitment_utc"),
                        "tradable_cash_release_eta_utc": verdict.get("tradable_cash_release_eta_utc"),
                        "reason": StarterReason.DELAYED_OR_DISPUTED.value,
                        "action": "capital stays reserved; no forced sale; notify the owner and reassess new exposure",
                        "past_168h": over_horizon})
    return out
