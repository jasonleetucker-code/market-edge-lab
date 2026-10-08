"""Price-relative wallet skill diagnostic (Deliverable C, ADR 0045 amendment C). Opt-in and versioned.

A win rate says little about skill on binary contracts. 98 wins in 100 one-contract YES entries at
$0.99 cost $99 and paid $98: a loss of $1. The existing 50%-null binomial screen
(`stats.binomial_tail_p`, used by `selection.multiple_testing`) still flags that record, and it stays as
it is: a **small-sample screen, not alpha**. This module adds a separate diagnostic that measures the
outcome against the **market entry price**, and reports both side by side.

**What is measured.** Only unambiguous held-to-resolution binary positions count (one account, one
market, buys of one outcome token, then a final 0/1 payout). For each, against the benchmark that the
entry price is the probability:
- `reference_payout` = sum(quantity x entry price) = cost: what a price-calibrated market expects;
- `payout` = quantity x final payout;
- `gross_excess` = payout - reference_payout. For these positions it equals the realized gross P&L
  `accounting.reconstruct` reports (a test pins the two together: one P&L concept, not two);
- `net_excess` = gross - fees, **only when every fee is known**. An unknown fee makes net UNKNOWN,
  never zero.

A market price is a benchmark, not automatically the true probability. Excess over it can come from
forecasting, from maker price improvement, or from a risk premium. The liquidity role is reported
next to it, and it is UNKNOWN unless the caller supplies role evidence.

**What is excluded, and classified, never priced.** Each exclusion has a typed reason:
- an unverified identity or incomplete account history (`identity.IdentityBasis.HEURISTIC` or
  missing, `history_complete` False);
- token transfers (cost basis unknown);
- splits, merges and conversions (unsupported);
- any sale (early or mixed exit);
- both outcome tokens held (a visible hedge);
- an UNKNOWN action, a non-binary outcome, or entry economics that do not reconcile exactly
  (cash paid must equal quantity x price, and the token leg must equal the quantity);
- an unresolved market, a payout other than 0 or 1, or a redemption that does not match the payout.

Hedges on other venues or accounts cannot be observed: `hidden_hedges` is always UNOBSERVABLE, never
NONE.

**Dependence, effective sample and shrinkage.** Positions cluster by `event_id` (the market id when
missing): one real-world event repeated across contracts is one unit. The report gives the cluster
count, Kish's effective size over cluster cost, the largest cluster's cost share (concentration), a
cluster-bootstrap band of the per-cluster excess, the excess return per dollar shrunk toward zero
with `pseudo_clusters`, and a Monte Carlo p-value against the price benchmark with comonotone
outcomes inside a cluster (`stats.price_benchmark_null_p`).

**Multiple testing and denominators.** Every account in the cohort is a hypothesis, including losing
and inactive accounts and accounts with no eligible position (p = 1). Benjamini-Hochberg uses
m = max(1, trials) x cohort size, so re-running rules on the same data makes survival harder. A
p-value is a screen on one window. It never proves persistence.

**Point in time.** `SkillRule` carries `frozen_at`. In `HOLDOUT` mode the rule must be frozen and the
cohort selected **before** the evaluation window opens, or `HindsightError` is raised. Only positions
entered after selection and inside the window count, and windows of successive holdouts must not
overlap (`check_holdout_sequence`). In `DESCRIPTIVE` mode, an account selected after a counted outcome
is flagged `SELECTED_AFTER_OUTCOMES` and can never receive a positive verdict.

**Dependency closure.** `SkillClosure` is a plain typed value of every input that shaped the report:
the rule, mode, window, cohort, trials, data label, observations, marks, identity bases, history
flags, roles and coverage. Its digest lets a later selection receipt (Deliverable A, v2) bind to it.

Floats appear only in statistics, never in a money value.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from ..provenance import canonical_json, sha256_hex
from .accounting import Mark, MarkKind
from .events import Action, WalletObservation
from .exact import ZERO, Basis, Labeled, add, decimal_text, exact_decimal, mul, ratio, sub, total
from .identity import IdentityBasis
from .stats import (benjamini_hochberg, binomial_tail_p, cluster_bootstrap, kish_effective_size,
                    price_benchmark_null_p, shrink_toward_zero)
from .timeutil import require_aware, utc_text

SKILL_VERSION = "wallet-price-relative-skill-v1"
ECONOMICS_LABEL = "LEADER_PRICE_RELATIVE_DIAGNOSTIC"
BENCHMARK = "MARKET_ENTRY_PRICE"
BINOMIAL_SCREEN_LABEL = "SMALL_SAMPLE_SCREEN_NOT_ALPHA"
BINOMIAL_SCREEN_NOTE = ("One-sided binomial p-value of per-event wins against 0.5. Prices make 0.5 the wrong null "
                        "for most binary contracts, so this is a screen for small lucky samples, not an edge test.")
BENCHMARK_NOTE = ("The entry price is a benchmark, not the true probability. Excess over it may be forecasting, "
                  "maker price improvement or a risk premium. A p-value here screens one window; it does not "
                  "prove persistence.")
DATA_LABELS = frozenset({"SYNTHETIC", "FIXTURE", "OBSERVED", "UNKNOWN"})
ROLES = frozenset({"MAKER", "TAKER", "MIXED", "UNKNOWN"})
VERIFIED_IDENTITY = frozenset({IdentityBasis.SOURCE_FIELD, IdentityBasis.ONCHAIN_EVENT, IdentityBasis.SYNTHETIC})


class HindsightError(ValueError):
    """An input chosen or known after the outcomes it is evaluated on."""


class EvaluationMode(str, Enum):
    DESCRIPTIVE = "DESCRIPTIVE"  # in-sample description; persistence untested
    HOLDOUT = "HOLDOUT"  # frozen rule, cohort selected before a later, non-overlapping window


class PositionStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    NOT_BINARY = "NOT_BINARY"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    INCOMPLETE_TRANSFER = "INCOMPLETE_TRANSFER"
    UNSUPPORTED_CONVERSION = "UNSUPPORTED_CONVERSION"
    EARLY_OR_MIXED_EXIT = "EARLY_OR_MIXED_EXIT"
    BOTH_SIDES_HELD = "BOTH_SIDES_HELD"
    NO_ENTRY = "NO_ENTRY"
    ENTRY_ECONOMICS_UNVERIFIED = "ENTRY_ECONOMICS_UNVERIFIED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS_RESOLUTION = "AMBIGUOUS_RESOLUTION"
    REDEMPTION_MISMATCH = "REDEMPTION_MISMATCH"
    OVERLAPS_SELECTION = "OVERLAPS_SELECTION"
    OUTSIDE_EVALUATION_WINDOW = "OUTSIDE_EVALUATION_WINDOW"


class SkillVerdict(str, Enum):
    NO_ELIGIBLE_POSITIONS = "NO_ELIGIBLE_POSITIONS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NEGATIVE = "NEGATIVE"  # price-relative excess below zero (point estimate)
    HINDSIGHT_FLAGGED = "HINDSIGHT_FLAGGED"  # positive, but selected after a counted outcome
    NOT_DISTINGUISHABLE_FROM_BENCHMARK = "NOT_DISTINGUISHABLE_FROM_BENCHMARK"
    POSITIVE_SCREEN = "POSITIVE_SCREEN"  # a screen on one window; never proof of persistence


@dataclass(frozen=True)
class SkillRule:
    """Selection and matching rules, frozen at `frozen_at`, before any holdout window opens."""

    rule_id: str
    version: str
    frozen_at: datetime
    min_effective_clusters: int
    min_eligible_share: Decimal  # eligible / all positions of the account (coverage)
    pseudo_clusters: int  # shrinkage strength toward zero excess
    fdr_q: float  # Benjamini-Hochberg false-discovery rate
    screen_alpha: float  # the binomial screen flags a win count at or below this p-value
    null_resamples: int
    seed: int

    def __post_init__(self) -> None:
        require_aware(self.frozen_at, "frozen_at")
        object.__setattr__(self, "min_eligible_share", exact_decimal(self.min_eligible_share,
                                                                     name="min_eligible_share"))
        if not self.rule_id or not self.version:
            raise ValueError("a skill rule needs an id and a version")
        if self.min_effective_clusters < 1 or self.pseudo_clusters < 0 or self.null_resamples < 1:
            raise ValueError("min_effective_clusters >= 1, pseudo_clusters >= 0 and null_resamples >= 1")
        if not (ZERO <= self.min_eligible_share <= Decimal(1)):
            raise ValueError("min_eligible_share must be in [0, 1]")
        if not (0 < self.fdr_q < 1) or not (0 < self.screen_alpha < 1):
            raise ValueError("fdr_q and screen_alpha must be in (0, 1)")

    def canonical(self) -> tuple[tuple[str, str], ...]:
        """Every field as canonical text (Decimal without exponent, float by repr, time in UTC)."""
        out = []
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, datetime):
                text = utc_text(v)
            elif isinstance(v, Decimal):
                text = decimal_text(v)
            elif isinstance(v, float):
                text = repr(v)
            else:
                text = str(v)
            out.append((f.name, text))
        return tuple(out)


@dataclass(frozen=True)
class SkillCohort:
    """Every account considered when the cohort was chosen: winners, losers and inactive alike."""

    selected_at: datetime
    accounts: tuple[str, ...]  # account keys
    selection_ref: str  # e.g. a selection manifest digest; recorded, not interpreted

    def __post_init__(self) -> None:
        require_aware(self.selected_at, "selected_at")
        if not self.accounts or len(set(self.accounts)) != len(self.accounts):
            raise ValueError("a cohort needs distinct account keys")
        if not self.selection_ref:
            raise ValueError("a cohort needs a selection reference")


@dataclass(frozen=True)
class EvaluationWindow:
    start: datetime  # positions entered at or after
    end: datetime  # and resolved at or before

    def __post_init__(self) -> None:
        require_aware(self.start, "start")
        require_aware(self.end, "end")
        if self.end <= self.start:
            raise ValueError("an evaluation window must end after it starts")


@dataclass(frozen=True)
class PositionRow:
    account_key: str
    market_id: str
    cluster: str
    status: PositionStatus
    reason: str
    instrument_id: str | None
    quantity: Decimal | None
    cost: Decimal | None
    reference_payout: Decimal | None  # quantity x entry price: the benchmark's expected payout
    payout: Decimal | None
    gross_excess: Labeled
    fees: Labeled
    net_excess: Labeled
    role: str
    entered_at: datetime | None
    resolved_at: datetime | None
    legs: tuple[tuple[Decimal, Decimal], ...]  # (entry price, quantity) per buy

    def to_dict(self) -> dict:
        def t(v: Decimal | None) -> str | None:
            return None if v is None else decimal_text(v)
        return {"account": self.account_key, "market_id": self.market_id, "cluster": self.cluster,
                "status": self.status.value, "reason": self.reason, "instrument_id": self.instrument_id,
                "quantity": t(self.quantity), "cost": t(self.cost), "reference_payout": t(self.reference_payout),
                "payout": t(self.payout), "gross_excess": self.gross_excess.to_dict(), "fees": self.fees.to_dict(),
                "net_excess": self.net_excess.to_dict(), "role": self.role,
                "entered_at": None if self.entered_at is None else utc_text(self.entered_at),
                "resolved_at": None if self.resolved_at is None else utc_text(self.resolved_at)}


@dataclass(frozen=True)
class BinomialScreen:
    wins: int  # clusters (events) with positive gross
    trials: int
    p_value: float
    flags_high_win_rate: bool
    label: str = BINOMIAL_SCREEN_LABEL
    note: str = BINOMIAL_SCREEN_NOTE

    def to_dict(self) -> dict:
        return {"wins": self.wins, "trials": self.trials, "p_value": self.p_value,
                "flags_high_win_rate": self.flags_high_win_rate, "label": self.label, "note": self.note}


@dataclass(frozen=True)
class AccountSkill:
    account_key: str
    verdict: SkillVerdict
    verdict_reasons: tuple[str, ...]
    verdict_basis: str  # GROSS_AND_NET | GROSS_ONLY_NET_UNKNOWN (| NONE without eligible positions)
    positions_total: int
    eligible: int
    excluded: tuple[tuple[str, int], ...]  # (status, count)
    eligible_share: Decimal | None
    position_win_rate: Decimal | None
    binomial_screen: BinomialScreen | None
    cost: Labeled
    reference_payout: Labeled
    payout: Labeled
    gross_excess: Labeled
    net_excess: Labeled
    excess_return_raw: Decimal | None  # gross excess / cost
    excess_return_shrunk: float | None
    clusters: int
    effective_clusters: float | None
    concentration: Decimal | None  # largest cluster's share of cost
    cluster_excess_band: tuple[float, float, float] | None  # (mean, lower, upper), 90% cluster bootstrap
    benchmark_p_value: float | None
    survives_fdr: bool
    roles: tuple[tuple[str, int], ...]
    hindsight_flags: tuple[str, ...]
    hidden_hedges: str = "UNOBSERVABLE"

    def to_dict(self) -> dict:
        def t(v: Decimal | None) -> str | None:
            return None if v is None else decimal_text(v)
        return {"account": self.account_key, "verdict": self.verdict.value, "verdict_reasons": list(self.verdict_reasons),
                "verdict_basis": self.verdict_basis, "positions_total": self.positions_total,
                "eligible": self.eligible, "excluded": [list(x) for x in self.excluded],
                "eligible_share": t(self.eligible_share), "position_win_rate": t(self.position_win_rate),
                "binomial_screen": None if self.binomial_screen is None else self.binomial_screen.to_dict(),
                "cost": self.cost.to_dict(), "reference_payout": self.reference_payout.to_dict(),
                "payout": self.payout.to_dict(), "gross_excess": self.gross_excess.to_dict(),
                "net_excess": self.net_excess.to_dict(), "excess_return_raw": t(self.excess_return_raw),
                "excess_return_shrunk": None if self.excess_return_shrunk is None
                else round(self.excess_return_shrunk, 9),
                "clusters": self.clusters,
                "effective_clusters": None if self.effective_clusters is None else round(self.effective_clusters, 6),
                "concentration": t(self.concentration),
                "cluster_excess_band": None if self.cluster_excess_band is None
                else [round(v, 9) for v in self.cluster_excess_band],
                "benchmark_p_value": self.benchmark_p_value, "survives_fdr": self.survives_fdr,
                "roles": [list(x) for x in self.roles], "hindsight_flags": list(self.hindsight_flags),
                "hidden_hedges": self.hidden_hedges}


@dataclass(frozen=True)
class SkillClosure:
    """Every input that shaped one report, as canonical text. A plain value: equal inputs, equal digest."""

    version: str
    rule: tuple[tuple[str, str], ...]
    mode: str
    as_of: str
    window: tuple[str, str] | None
    cohort_selected_at: str
    cohort_ref: str
    cohort_accounts: tuple[str, ...]
    trials: int
    data_label: str
    observations: tuple[tuple[str, str, str, str], ...]  # (account, observation id, semantic key, receipt)
    marks: tuple[tuple[str, str, str, str, str], ...]  # (key, instrument, kind, price, as_of)
    identity: tuple[tuple[str, str], ...]  # (account, basis or MISSING)
    history_complete: tuple[tuple[str, bool], ...]
    roles: tuple[tuple[str, str], ...]  # (observation id, role)
    coverage: tuple[tuple[str, int, int], ...]  # (account, positions, eligible)

    def to_dict(self) -> dict:
        return {"version": self.version, "rule": [list(x) for x in self.rule], "mode": self.mode,
                "as_of": self.as_of, "window": None if self.window is None else list(self.window),
                "cohort_selected_at": self.cohort_selected_at, "cohort_ref": self.cohort_ref,
                "cohort_accounts": list(self.cohort_accounts), "trials": self.trials, "data_label": self.data_label,
                "observations": [list(x) for x in self.observations], "marks": [list(x) for x in self.marks],
                "identity": [list(x) for x in self.identity],
                "history_complete": [list(x) for x in self.history_complete],
                "roles": [list(x) for x in self.roles], "coverage": [list(x) for x in self.coverage]}

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class PriceRelativeReport:
    mode: EvaluationMode
    as_of: datetime
    data_label: str
    accounts: tuple[AccountSkill, ...]
    positions: tuple[PositionRow, ...]
    hypotheses: int  # m for Benjamini-Hochberg
    fdr_q: float
    survivors: frozenset[str]
    closure: SkillClosure
    persistence_evidence: str  # NONE (descriptive) | ONE_NON_OVERLAPPING_WINDOW (holdout)
    version: str = SKILL_VERSION
    economics_label: str = ECONOMICS_LABEL
    benchmark: str = BENCHMARK
    note: str = BENCHMARK_NOTE

    def account(self, key: str) -> AccountSkill:
        for a in self.accounts:
            if a.account_key == key:
                return a
        raise KeyError(key)

    def to_dict(self) -> dict:
        return {"version": self.version, "economics_label": self.economics_label, "benchmark": self.benchmark,
                "note": self.note, "mode": self.mode.value, "as_of": utc_text(self.as_of),
                "data_label": self.data_label, "hypotheses": self.hypotheses, "fdr_q": self.fdr_q,
                "survivors": sorted(self.survivors), "persistence_evidence": self.persistence_evidence,
                "closure_digest": self.closure.digest, "accounts": [a.to_dict() for a in self.accounts],
                "positions": [p.to_dict() for p in self.positions]}

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


# --- Positions -------------------------------------------------------------------------------------

_CONVERSIONS = frozenset({Action.SPLIT, Action.MERGE, Action.CONVERSION})
_TRANSFERS = frozenset({Action.TRANSFER_IN, Action.TRANSFER_OUT})


def _excluded(account: str, market: str, cluster: str, status: PositionStatus, reason: str,
              role: str = "UNKNOWN") -> PositionRow:
    unk = Labeled.unknown(f"{status.value}: not priced")
    return PositionRow(account, market, cluster, status, reason, None, None, None, None, None, unk, unk, unk, role,
                       None, None, ())


def _role(buys: Sequence[WalletObservation], roles: Mapping[str, str]) -> str:
    seen = {roles.get(o.observation_id, "UNKNOWN") for o in buys}
    if not seen or "UNKNOWN" in seen:
        return "UNKNOWN"
    if seen == {"MAKER"}:
        return "MAKER"
    if seen == {"TAKER"}:
        return "TAKER"
    return "MIXED"


def _verified_entry(o: WalletObservation) -> tuple[Decimal, Decimal, Decimal] | None:
    """(price, quantity, cash paid) when the buy's economics reconcile exactly, else None."""
    if "LEGS_NOT_ITEMIZED" in o.ambiguities or o.price is None or o.native_quantity is None:
        return None
    if not (ZERO < o.price < Decimal(1)) or o.native_quantity <= 0:
        return None
    cash = [a for a in o.paid if a.is_cash]
    tokens = [a for a in o.received if not a.is_cash]
    if len(cash) != 1 or len(o.paid) != 1 or len(tokens) != 1 or len(o.received) != 1:
        return None
    if tokens[0].asset != f"token:{o.instrument_id}" or tokens[0].quantity != o.native_quantity:
        return None
    if cash[0].quantity != mul(o.native_quantity, o.price):
        return None
    return o.price, o.native_quantity, cash[0].quantity


def _position(account: str, market: str, rows: Sequence[WalletObservation], *, as_of: datetime,
              marks: Mapping[str, Mark], identity_ok: bool, complete: bool, roles: Mapping[str, str],
              mode: EvaluationMode, cohort: SkillCohort, window: EvaluationWindow | None) -> PositionRow:
    rows = sorted(rows, key=lambda o: (o.source_time, o.observation_id))
    cluster = next((o.event_id for o in rows if o.event_id), None) or market
    buys = [o for o in rows if o.action is Action.TRADE_BUY]
    role = _role(buys, roles)

    def out(status: PositionStatus, reason: str) -> PositionRow:
        return _excluded(account, market, cluster, status, reason, role)

    if not identity_ok:
        return out(PositionStatus.IDENTITY_UNVERIFIED, "identity is heuristic or missing")
    if not complete:
        return out(PositionStatus.COVERAGE_INCOMPLETE, "history is not complete from the account's start")
    if any(o.action is Action.UNKNOWN for o in rows):
        return out(PositionStatus.UNKNOWN_ACTION, "an action of unknown meaning")
    if any(o.action in _TRANSFERS for o in rows):
        return out(PositionStatus.INCOMPLETE_TRANSFER, "tokens moved by transfer: cost basis unknown")
    if any(o.action in _CONVERSIONS for o in rows):
        return out(PositionStatus.UNSUPPORTED_CONVERSION, "split, merge or conversion")
    if any(o.action is Action.TRADE_SELL for o in rows):
        return out(PositionStatus.EARLY_OR_MIXED_EXIT, "a sale before resolution: not held to resolution")
    if any(o.outcome_index not in (0, 1) for o in buys):
        return out(PositionStatus.NOT_BINARY, "outcome index missing or not binary")
    if not buys:
        return out(PositionStatus.NO_ENTRY, "no buy in this market")
    instruments = {o.instrument_id for o in buys}
    if len(instruments) != 1 or len({o.outcome_index for o in buys}) != 1:
        return out(PositionStatus.BOTH_SIDES_HELD, "both outcomes bought: a visible hedge")
    legs = []
    for o in buys:
        entry = _verified_entry(o)
        if entry is None:
            return out(PositionStatus.ENTRY_ECONOMICS_UNVERIFIED,
                       f"{o.observation_id}: cash paid does not reconcile with quantity x price")
        legs.append(entry)
    instrument = next(iter(instruments))
    assert instrument is not None
    mark = marks.get(instrument)
    if mark is None or mark.kind is not MarkKind.RESOLVED_PAYOUT:
        return out(PositionStatus.UNRESOLVED, "no final payout known by as_of")
    if mark.price not in (ZERO, Decimal(1)):
        return out(PositionStatus.AMBIGUOUS_RESOLUTION, f"payout {decimal_text(mark.price)} is not 0 or 1")
    entered_at = buys[0].source_time
    if mark.as_of < buys[-1].source_time:
        return out(PositionStatus.AMBIGUOUS_RESOLUTION, "a buy after the market resolved")
    quantity = total(q for _, q, _ in legs)
    cost = total(c for _, _, c in legs)
    payout = mul(quantity, mark.price)
    for o in rows:
        if o.action is Action.REDEEM:
            cash = add(*(a.quantity for a in o.received if a.is_cash))
            if o.source_time < mark.as_of or cash != payout:
                return out(PositionStatus.REDEMPTION_MISMATCH, "a redemption does not match the final payout")
    if mode is EvaluationMode.HOLDOUT and (entered_at <= cohort.selected_at or mark.as_of <= cohort.selected_at):
        return out(PositionStatus.OVERLAPS_SELECTION, "entered or resolved by the cohort's selection time")
    if window is not None and (entered_at < window.start or mark.as_of > window.end):
        return out(PositionStatus.OUTSIDE_EVALUATION_WINDOW, "entered before or resolved after the window")
    gross = sub(payout, cost)
    if all(o.fee.known for o in buys):
        fees = Labeled(total(o.fee.value for o in buys if o.fee.value is not None), Basis.OBSERVED)
        assert fees.value is not None
        net = Labeled(sub(gross, fees.value), Basis.OBSERVED, "gross excess less observed fees")
    else:
        fees = Labeled.unknown("a fee is not reported")
        net = Labeled.unknown("a fee is unknown: net excess is unknown, never zero")
    return PositionRow(account, market, cluster, PositionStatus.ELIGIBLE, "held to resolution", instrument, quantity,
                       cost, cost, payout, Labeled(gross, Basis.OBSERVED, "payout - quantity x entry price"), fees,
                       net, role, entered_at, mark.as_of, tuple((p, q) for p, q, _ in legs))


# --- Report ----------------------------------------------------------------------------------------

def price_relative_report(observations: Mapping[str, Sequence[WalletObservation]], *, as_of: datetime,
                          rule: SkillRule, cohort: SkillCohort, marks: Mapping[str, Mark],
                          history_complete: Mapping[str, bool], identity: Mapping[str, IdentityBasis],
                          trials: int, data_label: str, mode: EvaluationMode = EvaluationMode.DESCRIPTIVE,
                          window: EvaluationWindow | None = None,
                          roles: Mapping[str, str] | None = None) -> PriceRelativeReport:
    """The price-relative skill diagnostic for every cohort account, from point-in-time observations.

    `observations` maps account key -> that account's observations as known at `as_of`
    (`ObservationLog.as_known_at`). Every key must be a cohort account; a cohort account without
    observations is kept, with no eligible position. `marks` must all be known by `as_of`."""
    require_aware(as_of, "as_of")
    roles = dict(roles or {})
    if data_label not in DATA_LABELS:
        raise ValueError(f"data_label must be one of {sorted(DATA_LABELS)}")
    if trials < 0:
        raise ValueError("trials must be >= 0")
    if any(r not in ROLES for r in roles.values()):
        raise ValueError(f"roles must be one of {sorted(ROLES)}")
    stray = set(observations) - set(cohort.accounts)
    if stray:
        raise ValueError(f"accounts outside the cohort: {sorted(stray)}")
    if rule.frozen_at > as_of or cohort.selected_at > as_of:
        raise HindsightError("the rule or the cohort is dated after as_of")
    if mode is EvaluationMode.HOLDOUT:
        if window is None:
            raise ValueError("a holdout needs an evaluation window")
        if rule.frozen_at > window.start:
            raise HindsightError("the rule was frozen after the holdout window opened")
        if cohort.selected_at > window.start:
            raise HindsightError("the cohort was selected after the holdout window opened")
    future = sorted(k for k, m in marks.items() if m.as_of > as_of)
    if future:
        raise HindsightError(f"marks known only after as_of: {future}")
    all_obs: list[tuple[str, WalletObservation]] = []
    for key, rows in observations.items():
        for o in rows:
            if o.account.key != key:
                raise ValueError(f"{o.observation_id} belongs to {o.account.key}, not {key}")
            if o.source_time > as_of or o.receipt_time > as_of:
                raise HindsightError(f"{o.observation_id} was not known by as_of")
            all_obs.append((key, o))
    if data_label == "OBSERVED" and any(o.synthetic for _, o in all_obs):
        raise ValueError("synthetic observations cannot be labelled OBSERVED")

    positions: list[PositionRow] = []
    for key in sorted(cohort.accounts):
        by_market: dict[str, list[WalletObservation]] = {}
        for o in observations.get(key, ()):
            if o.action is Action.REWARD:
                continue  # rewards are not trading; accounting reports them separately
            by_market.setdefault(o.market_id or f"?{o.instrument_id}", []).append(o)
        identity_ok = identity.get(key) in VERIFIED_IDENTITY
        for market in sorted(by_market):
            positions.append(_position(key, market, by_market[market], as_of=as_of, marks=marks,
                                       identity_ok=identity_ok, complete=bool(history_complete.get(key, False)),
                                       roles=roles, mode=mode, cohort=cohort, window=window))

    stats_by_account = {key: _account_stats(key, [p for p in positions if p.account_key == key], rule, cohort, mode)
                        for key in sorted(cohort.accounts)}
    p_values = {k: (s["p"] if s["p"] is not None else 1.0) for k, s in stats_by_account.items()}
    m = max(1, trials) * len(cohort.accounts)
    survivors = benjamini_hochberg(p_values, q=rule.fdr_q, m=m)
    accounts = tuple(_finish(key, stats_by_account[key], key in survivors, rule, m) for key in sorted(cohort.accounts))

    closure = SkillClosure(
        version=SKILL_VERSION, rule=rule.canonical(), mode=mode.value, as_of=utc_text(as_of),
        window=None if window is None else (utc_text(window.start), utc_text(window.end)),
        cohort_selected_at=utc_text(cohort.selected_at), cohort_ref=cohort.selection_ref,
        cohort_accounts=tuple(sorted(cohort.accounts)), trials=trials, data_label=data_label,
        observations=tuple(sorted((k, o.observation_id, o.semantic_key, utc_text(o.receipt_time)) for k, o in all_obs)),
        marks=tuple(sorted((k, mk.instrument_id, mk.kind.value, decimal_text(mk.price), utc_text(mk.as_of))
                           for k, mk in marks.items())),
        identity=tuple((k, identity[k].value if k in identity else "MISSING") for k in sorted(cohort.accounts)),
        history_complete=tuple((k, bool(history_complete.get(k, False))) for k in sorted(cohort.accounts)),
        roles=tuple(sorted(roles.items())),
        coverage=tuple((a.account_key, a.positions_total, a.eligible) for a in accounts))
    return PriceRelativeReport(mode, as_of, data_label, accounts, tuple(positions), m, rule.fdr_q, survivors, closure,
                               "ONE_NON_OVERLAPPING_WINDOW" if mode is EvaluationMode.HOLDOUT else "NONE")


def _account_stats(key: str, rows: Sequence[PositionRow], rule: SkillRule, cohort: SkillCohort,
                   mode: EvaluationMode) -> dict:
    eligible = [p for p in rows if p.status is PositionStatus.ELIGIBLE]
    excluded: dict[str, int] = {}
    for p in rows:
        if p.status is not PositionStatus.ELIGIBLE:
            excluded[p.status.value] = excluded.get(p.status.value, 0) + 1
    out: dict = {"rows": rows, "eligible": eligible, "excluded": tuple(sorted(excluded.items())), "p": None}
    if not eligible:
        return out
    clusters: dict[str, list[PositionRow]] = {}
    for p in eligible:
        clusters.setdefault(p.cluster, []).append(p)
    cluster_cost = {c: total(p.cost for p in ps if p.cost is not None) for c, ps in clusters.items()}
    cluster_gross = {c: total(p.gross_excess.value for p in ps if p.gross_excess.value is not None)
                     for c, ps in clusters.items()}
    gross = total(cluster_gross.values())
    cost = total(cluster_cost.values())
    legs = [[(float(price), float(q)) for p in ps for price, q in p.legs] for _, ps in sorted(clusters.items())]
    out.update(
        clusters=clusters, cluster_cost=cluster_cost, cluster_gross=cluster_gross, gross=gross, cost=cost,
        effective=kish_effective_size([float(cluster_cost[c]) for c in sorted(clusters)]),
        p=price_benchmark_null_p(legs, float(gross), seed=rule.seed, resamples=rule.null_resamples),
        band=cluster_bootstrap({c: float(v) for c, v in cluster_gross.items()}, seed=rule.seed),
        hindsight=tuple(sorted({"SELECTED_AFTER_OUTCOMES"} if mode is EvaluationMode.DESCRIPTIVE and any(
            p.resolved_at is not None and p.resolved_at <= cohort.selected_at for p in eligible) else set())))
    return out


def _finish(key: str, s: dict, survives: bool, rule: SkillRule, m: int) -> AccountSkill:
    rows: Sequence[PositionRow] = s["rows"]
    eligible: Sequence[PositionRow] = s["eligible"]
    roles: dict[str, int] = {}
    for p in eligible:
        roles[p.role] = roles.get(p.role, 0) + 1
    share = ratio(Decimal(len(eligible)), Decimal(len(rows))) if rows else None
    if not eligible:
        unk = Labeled.unknown("no eligible position")
        reason = "no observation: inactive" if not rows else "every position was excluded"
        return AccountSkill(key, SkillVerdict.NO_ELIGIBLE_POSITIONS, (reason,), "NONE", len(rows), 0, s["excluded"],
                            share, None, None, unk, unk, unk, unk, unk, None, None, 0, None, None, None, None,
                            False, (), ())
    gross: Decimal = s["gross"]
    cost: Decimal = s["cost"]
    payout = total(p.payout for p in eligible if p.payout is not None)
    net_rows = [p.net_excess for p in eligible]
    net = Labeled(total(n.value for n in net_rows if n.value is not None), Basis.OBSERVED) \
        if all(n.known for n in net_rows) else Labeled.unknown("a fee is unknown: net excess is unknown, never zero")
    wins = sum(1 for p in eligible if p.gross_excess.value is not None and p.gross_excess.value > 0)
    cluster_wins = sum(1 for v in s["cluster_gross"].values() if v > 0)
    n_clusters = len(s["clusters"])
    screen_p = binomial_tail_p(cluster_wins, n_clusters)
    screen = BinomialScreen(cluster_wins, n_clusters, screen_p, screen_p <= rule.screen_alpha)
    raw = ratio(gross, cost)
    effective: float | None = s["effective"]
    shrunk = None if raw is None or effective is None else shrink_toward_zero(float(raw), effective,
                                                                               rule.pseudo_clusters)
    concentration = ratio(max(s["cluster_cost"].values()), cost)
    hindsight: tuple[str, ...] = s["hindsight"]
    reasons: list[str] = []
    if share is not None and share < rule.min_eligible_share:
        reasons.append(f"COVERAGE_BELOW_MIN:{decimal_text(share)}")
    if effective is None or effective < rule.min_effective_clusters:
        reasons.append(f"EFFECTIVE_CLUSTERS_BELOW_MIN:{round(effective or 0.0, 3)}<{rule.min_effective_clusters}")
    if reasons:
        verdict = SkillVerdict.INSUFFICIENT_EVIDENCE
    elif gross < 0:
        verdict = SkillVerdict.NEGATIVE
        reasons.append("payout is below the entry-price benchmark (point estimate)")
    elif gross > 0 and hindsight:
        verdict = SkillVerdict.HINDSIGHT_FLAGGED
        reasons.append("the cohort was selected after a counted outcome: no positive verdict")
    elif gross > 0 and survives and shrunk is not None and shrunk > 0 and net.known and net.value is not None             and net.value <= 0:
        verdict = SkillVerdict.NOT_DISTINGUISHABLE_FROM_BENCHMARK
        reasons.append("gross excess survives, but net excess after observed fees is not positive")
    elif gross > 0 and survives and shrunk is not None and shrunk > 0:
        verdict = SkillVerdict.POSITIVE_SCREEN
        reasons.append(f"survives Benjamini-Hochberg at q={rule.fdr_q}, m={m}; a screen, not persistence")
    else:
        verdict = SkillVerdict.NOT_DISTINGUISHABLE_FROM_BENCHMARK
        reasons.append(f"does not survive Benjamini-Hochberg at q={rule.fdr_q}, m={m}" if gross > 0
                       else "no excess over the entry-price benchmark")
    if not net.known:
        reasons.append("net excess UNKNOWN: a fee is not reported, so this verdict rests on gross only")
    basis = "GROSS_AND_NET" if net.known else "GROSS_ONLY_NET_UNKNOWN"
    obs = Basis.OBSERVED
    return AccountSkill(
        key, verdict, tuple(reasons), basis, len(rows), len(eligible), s["excluded"], share,
        ratio(Decimal(wins), Decimal(len(eligible))), screen, Labeled(cost, obs), Labeled(cost, obs, "benchmark"),
        Labeled(payout, obs), Labeled(gross, obs, "payout - entry-price benchmark"), net, raw, shrunk, n_clusters,
        effective, concentration, s["band"], s["p"], survives, tuple(sorted(roles.items())), hindsight)


def check_holdout_sequence(closures: Sequence[SkillClosure]) -> None:
    """Successive holdouts must share one frozen rule and use non-overlapping windows, each opening after
    its cohort was selected. Raises `HindsightError` otherwise."""
    holdouts = [c for c in closures if c.mode == EvaluationMode.HOLDOUT.value]
    if len(holdouts) != len(closures):
        raise HindsightError("only HOLDOUT reports form a holdout sequence")
    if len({c.rule for c in holdouts}) > 1:
        raise HindsightError("the rule changed between holdouts: it was not frozen")
    spans = sorted((c.window or ("", "")) for c in holdouts)
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        if s2 < e1:
            raise HindsightError(f"holdout windows overlap: {s1}..{e1} and one starting {s2}")
