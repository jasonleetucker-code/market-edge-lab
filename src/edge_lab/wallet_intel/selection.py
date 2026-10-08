"""Point-in-time candidate universe and selection manifest (W4, ADR 0045).

- A `Candidate` records when and how an account was **discovered**, with the label vintage of the
  discovery source. An account discovered after date D cannot be in D's universe: future rankings
  cannot select historical leaders.
- `select_at(D)` uses only observations received by D (`ObservationLog.as_known_at(D)`) and only
  marks/resolutions known by D. Anything from after D passed in is refused (`HindsightError`).
- Every candidate stays in the manifest: eligible, ineligible, inactive, without data. Failed and
  disappeared wallets are never dropped, so the universe is never rebuilt from today's winners.
- The manifest records `selected_at`, the label version, the rule and its version, the cumulative
  number of selection trials, every reason, and a digest of its inputs.
- Eligibility needs independent resolved events (clustered by event, not trades), complete coverage,
  a shrunk lower bound and no disqualifying threat flag. Volume never qualifies anyone, and gains that
  rest on illiquid marks or gifts are UNKNOWN, so they never count.
- The caller's `history_complete` and `threat_flags` must themselves be point-in-time: coverage and flags as
  they could have been known at D (the demo computes clusters from the D view only).
- `walk_forward` splits time into select-then-evaluate windows; `multiple_testing` applies
  Benjamini-Hochberg across candidates and reports the trial count.

Eligibility for research is not permission to trade: `ExecutionEligibility` is a separate answer
(observability.py), and an unsupported venue blocks execution without falsifying a research result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from ..provenance import canonical_json, sha256_hex
from .accounting import LeaderDimensions, Mark, event_outcomes, leader_dimensions, reconstruct
from .events import ObservationLog
from .exact import Labeled, decimal_text
from .identity import AccountRef
from .stats import benjamini_hochberg, binomial_tail_p, fit_beta_prior
from .threats import is_bait_size, round_trip_share
from .timeutil import require_aware, utc_text

SELECTION_VERSION = "wallet-selection-manifest-v1"


class HindsightError(ValueError):
    """An input from after the selection date reached a point-in-time selection."""


@dataclass(frozen=True)
class Candidate:
    account: AccountRef
    discovered_at: datetime
    discovery_source: str  # e.g. "synthetic-universe", a leaderboard snapshot id
    discovery_label_version: str

    def __post_init__(self) -> None:
        require_aware(self.discovered_at, "discovered_at")


@dataclass(frozen=True)
class EligibilityRule:
    rule_id: str
    version: str
    min_independent_events: int
    min_history_days: int
    min_shrunk_lower: float  # lower bound of the shrunk per-event win rate
    max_concentration: Decimal
    max_round_trip_share: Decimal
    max_reward_dependence: Decimal
    inactive_after: timedelta
    round_trip_window: timedelta
    min_trade_notional: Decimal  # bait-sized trades are ignored when counting activity
    require_complete_coverage: bool = True


class CandidateStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    INACTIVE = "INACTIVE"
    NO_DATA = "NO_DATA"


@dataclass(frozen=True)
class SelectionRecord:
    account_key: str
    discovered_at: datetime
    status: CandidateStatus
    reasons: tuple[str, ...]
    observations_used: int
    last_observed_event: datetime | None
    dimensions: dict


@dataclass(frozen=True)
class SelectionManifest:
    selected_at: datetime
    label_version: str
    rule: EligibilityRule
    trials: int  # cumulative selection-rule trials so far, for multiple-testing accounting
    records: tuple[SelectionRecord, ...]
    excluded_not_yet_discovered: int
    inputs_digest: str
    version: str = SELECTION_VERSION

    @property
    def eligible(self) -> tuple[str, ...]:
        return tuple(r.account_key for r in self.records if r.status is CandidateStatus.ELIGIBLE)

    def to_dict(self) -> dict:
        return {"version": self.version, "selected_at": utc_text(self.selected_at), "label_version": self.label_version,
                "rule": {"rule_id": self.rule.rule_id, "version": self.rule.version}, "trials": self.trials,
                "excluded_not_yet_discovered": self.excluded_not_yet_discovered, "inputs_digest": self.inputs_digest,
                "records": [{"account": r.account_key, "discovered_at": utc_text(r.discovered_at),
                             "status": r.status.value, "reasons": list(r.reasons),
                             "observations_used": r.observations_used,
                             "last_observed_event": None if r.last_observed_event is None
                             else utc_text(r.last_observed_event), "dimensions": r.dimensions}
                            for r in self.records]}


def select_at(selected_at: datetime, *, candidates: Sequence[Candidate], logs: Mapping[str, ObservationLog],
              history_complete: Mapping[str, bool], marks: Mapping[str, Mark], rule: EligibilityRule,
              label_version: str, trials: int, mark_max_age: timedelta,
              threat_flags: Mapping[str, Sequence[str]] | None = None) -> SelectionManifest:
    require_aware(selected_at, "selected_at")
    future_marks = [k for k, m in marks.items() if m.as_of > selected_at]
    if future_marks:
        raise HindsightError(f"marks known only after the selection date: {sorted(future_marks)}")
    for key, flags in (threat_flags or {}).items():
        if not isinstance(flags, (list, tuple)):
            raise TypeError("threat flags must be a sequence of flag codes")
    visible = [c for c in candidates if c.discovered_at <= selected_at]
    hidden = len(candidates) - len(visible)
    views = {}
    for c in visible:
        log = logs.get(c.account.key)
        obs = log.as_known_at(selected_at) if log is not None else ()
        if any(o.source_time > selected_at for o in obs):
            raise HindsightError("an observation received by D describes an event after D")
        views[c.account.key] = obs
    accounts = {}
    for c in visible:
        obs = views[c.account.key]
        if obs:
            accounts[c.account.key] = reconstruct(
                obs, as_of=selected_at, history_complete=history_complete.get(c.account.key, False),
                cash_flows_observed=False, opening_balance=Labeled.unknown("public wallet: opening balance unknown"),
                marks=marks, mark_max_age=mark_max_age)
    pool = [(sum(1 for v in event_outcomes(a).values() if v > 0), len(event_outcomes(a))) for a in accounts.values()]
    prior = fit_beta_prior(pool)
    records = []
    for c in sorted(visible, key=lambda x: x.account.key):
        key = c.account.key
        obs = views[key]
        if not obs:
            records.append(SelectionRecord(key, c.discovered_at, CandidateStatus.NO_DATA, ("no observation by D",), 0,
                                           None, {}))
            continue
        dims = leader_dimensions(accounts[key], obs, prior=prior)
        reasons = _eligibility(dims, obs, rule, accounts[key].coverage_complete, (threat_flags or {}).get(key, ()))
        last = max(o.source_time for o in obs)
        status = CandidateStatus.ELIGIBLE if not reasons else CandidateStatus.INELIGIBLE
        if selected_at - last > rule.inactive_after:
            status = CandidateStatus.INACTIVE
            reasons = (*reasons, "INACTIVE: no observed event within inactive_after")
        records.append(SelectionRecord(key, c.discovered_at, status, tuple(reasons), len(obs), last, dims.to_dict()))
    digest = sha256_hex(canonical_json({
        "selected_at": utc_text(selected_at), "label_version": label_version, "rule": rule.rule_id + "@" + rule.version,
        "candidates": sorted((c.account.key, utc_text(c.discovered_at), c.discovery_label_version) for c in visible),
        "observations": sorted(o.observation_id for v in views.values() for o in v),
        "marks": sorted((k, m.kind.value, decimal_text(m.price), utc_text(m.as_of)) for k, m in marks.items())}))
    return SelectionManifest(selected_at, label_version, rule, trials, tuple(records), hidden, digest)


def _eligibility(dims: LeaderDimensions, obs, rule: EligibilityRule, complete: bool,  # type: ignore[no-untyped-def]
                 flags: Sequence[str]) -> tuple[str, ...]:
    reasons = []
    if rule.require_complete_coverage and not complete:
        reasons.append("COVERAGE_INCOMPLETE")
    if dims.unknown_markets:
        reasons.append(f"UNKNOWN_MARKETS:{dims.unknown_markets}")
    if dims.independent_events < rule.min_independent_events:
        reasons.append(f"TOO_FEW_INDEPENDENT_EVENTS:{dims.independent_events}")
    if dims.history_days.value is None or dims.history_days.value < rule.min_history_days:
        reasons.append("HISTORY_TOO_SHORT")
    if dims.event_win_rate.lower < rule.min_shrunk_lower:
        reasons.append(f"SHRUNK_LOWER_BOUND_BELOW:{round(dims.event_win_rate.lower, 4)}")
    if dims.concentration.value is None or dims.concentration.value > rule.max_concentration:
        reasons.append("CONCENTRATED_OR_UNKNOWN")
    if dims.reward_dependence.value is None or dims.reward_dependence.value > rule.max_reward_dependence:
        reasons.append("REWARD_DEPENDENT_OR_UNKNOWN")
    meaningful = [o for o in obs if o.directional and not is_bait_size(o, min_notional=rule.min_trade_notional)]
    share = round_trip_share(meaningful, max_hold=rule.round_trip_window)
    if share is None or share > rule.max_round_trip_share:
        reasons.append("ROUND_TRIP_CHURN_OR_NO_TRADES")
    reasons += [f"THREAT:{f}" for f in flags]
    return tuple(reasons)


@dataclass(frozen=True)
class WalkForwardWindow:
    selection_date: datetime  # select with data known by here
    evaluate_from: datetime  # evaluate only on events after the selection date
    evaluate_to: datetime


def walk_forward(start: datetime, end: datetime, *, train: timedelta, test: timedelta,
                 step: timedelta) -> tuple[WalkForwardWindow, ...]:
    require_aware(start, "start")
    require_aware(end, "end")
    out = []
    d = start + train
    while d + test <= end:
        out.append(WalkForwardWindow(d, d, d + test))
        d += step
    return tuple(out)


@dataclass(frozen=True)
class MultipleTestingReport:
    trials: int
    p_values: dict[str, float]
    hypotheses: int  # trials x candidates tested: the m used by Benjamini-Hochberg
    survivors: frozenset[str]
    q: float
    note: str = ("One-sided binomial p-values of per-event wins against 0.5. Prices make 0.5 the wrong null "
                 "for most binary contracts, so this is a screen for small lucky samples, not an edge test. "
                 "Every earlier selection trial is counted as having tested every candidate again.")


def multiple_testing(manifest: SelectionManifest, *, q: float = 0.10) -> MultipleTestingReport:
    """Benjamini-Hochberg over this manifest's candidates, with m = cumulative trials x candidates, so
    re-running selection rules on the same data makes survival harder, never easier."""
    p = {}
    for r in manifest.records:
        rate = r.dimensions.get("event_win_rate") if r.dimensions else None
        if rate:
            p[r.account_key] = binomial_tail_p(rate["wins"], rate["trials"])
    m = max(1, manifest.trials) * len(p)
    return MultipleTestingReport(manifest.trials, p, m, benjamini_hochberg(p, q=q, m=m) if p else frozenset(), q)
