"""Sizing v2 counterfactual runner (directive 2026-09-24, deliverable 1). RESEARCH ONLY.

It replays every decision recorded in the shadow ledger through the canonical sizing-v2
engine (`sizing_v2.recommend`), once per policy A-H, and asks what each policy would have
done. It is not a second engine: every size, cap, verdict and binding constraint comes from
`sizing_v2`; every fill from `fill_policy.simulate_fill`; every fee from `sizing_v2.fee_basis`
(`schedule_for(venue, scope, as_of=...)`); every risk figure from `risk.assess`. This module
only reconstructs point-in-time inputs and keeps one isolated simulated account per policy.

Nothing here writes the canonical ledger or the evidence database. Both are opened read-only
by the CLI, and a run is a derived artifact written only to the path the caller names. It
never places, simulates against a live venue, or changes a shadow fill.

Inputs, reconstructed only from what was known at each decision time (`as_of`):

- **Decisions**: every `decision` entry in every ledger account (QUALIFY and REJECT, every
  reason), merged by `decision_id` (the research and operational accounts record the same
  opportunities). Records that disagree fail closed (`DECISION_RECORDS_DISAGREE`).
- **Market**: venue and native id from `market_id`; status, rules and payoff from the recorded
  reasons (`MARKET_CLOSED`, `RULES_UNRESOLVED`, `PAYOFF_UNSUPPORTED`). Market timing comes from
  the decision's own recorded STARTER_MAX_7D_V1 verdict (the ledger binds it to this market);
  with no recorded verdict the engine refuses the capital horizon (CAPITAL_HORIZON), and the
  verdict is never recomputed at replay time (its lag evidence may be newer than the decision).
- **Book**: the recorded top of book only (`executable_price`, `displayed_size`,
  `quote_received_at_utc`). Depth beyond it was not recorded and is never invented, so every
  liquidity cap is top-of-book-limited (`top_of_book_limited: true` on every row).
- **Model**: binary states (YES, NO). P(YES) from the recorded side probability. The
  uncertainty set is the recorded conservative bounds: the YES decision's conservative
  probability is the lower bound, the NO decision's is 1 - upper. A bound that was not
  recorded is widened to 0 or 1 (unknown uncertainty is unbounded, which is conservative for
  every policy); with no recorded bound at all the set is unknown (UNCERTAINTY_UNKNOWN).
  The model timestamp is the decision time when the recorded model freshness was `fresh`
  (EXP-001 estimates are generated at the decision time), else unknown (STALE_DATA).
- **Portfolio**: `risk.assess` over the policy's own simulated account at `as_of`, converted by
  `sizing_v2.portfolio_state` under `CounterfactualConfig.risk_policy` (default: the
  operational shadow account's `EXP-001-shadow-risk-v1` and $1,000). Open positions in the
  same market are passed as mapped holdings; other exposure in the cluster is unmapped, so the
  engine assumes it is lost in every state (conservative).
- **Fills**: `fill_policy.simulate_fill` (latency-confirmed-v1) with the counterfactual
  quantity, the recorded entry quote and the confirmation quote rebuilt from the evidence
  database: the recorded fill's `confirmation_evidence_id`, else the day's re-check capture.
  Without the database a recorded FILLED fill of at least the same quantity is reused; anything
  else is NO_FILL `CONFIRMATION_EVIDENCE_UNAVAILABLE`. A fill is known at the confirmation
  quote's receipt time. The cash debit is the engine's all-in cost (fees plus the ADR 0017
  claim allowance), so net P&L is a conservative lower bound. An invalid Stage B day never
  fills (`STAGE_B_DAY_INVALID`), exactly as the canonical path.
- **Settlements**: attached only once known (knowledge time <= the replay clock). Outcomes come
  from the captured settlement evidence under the canonical rules (`exp001_shadow.settlement_index`
  with `known_by`, `official_outcome`, `event_settlement_problems`), known at the first
  capture that makes them conclusive, or from ledger settlement entries at their
  `shadow_ledger.knowledge_time`. A ledger settlement that disagrees with the captured evidence
  fails closed: no settlement is attached (`SETTLEMENT_CONFLICT`). Evidence captured later
  that contradicts an outcome is reported (`CONTRADICTED_LATER`), never applied retroactively.

Per-policy state is isolated: settled cash, reservations and open positions, event and
cluster exposure (through `risk.assess`), realized P&L, drawdown, high-water mark and capital
release. A sized decision reserves its cost at the decision time; the reservation becomes an
open position when the fill is known, or is released when the NO_FILL is known. Event order
at equal times: fills and settlements known at t, then decisions at t, then same-time
releases (a decision never benefits from a release decided in the same instant).

Output: `CounterfactualSizingRun` per policy (schema `counterfactual-sizing-run-v1`) inside a
bundle with the dataset cutoff, source-code hashes and input hashes. The JSON is deterministic:
no wall-clock field, sorted keys, Decimal money as strings, floats formatted to 10 places.
No statistical significance is implied by a few settlements.

----------------------------------------------------------------------------- panel contract

`panel_for_market(store, ledger, market_id, *, as_of=None, config=DEFAULT_CONFIG,
policies=POLICY_SET) -> dict` (pure, read-only) for the Terminal v1 research sizing panel
(labelled RESEARCH SIZING / SHADOW SIZING CHALLENGER, never "Recommended bet"). It replays the
ledger up to the latest recorded decision on `market_id` (at or before `as_of` when given)
and returns the canonical per-policy counterfactual rows for that decision. Keys:

- `panel_version` ("1"), `label`, `market_id`, `as_of_utc` (replay clock used, or None);
- `available` (bool), `unavailable_reason` (None or one of `UNAVAILABLE_REASONS`),
  `unavailable_detail` (the exact engine/runner reason text, or None);
- `primary_policy`: {policy_id, policy_version, letter, description} (H, the candidate);
- `sides`: one entry per recorded side of that decision time, YES first. Each entry:
  `side`, `decision_id`, `decision_time`, `recorded_qualification`, `recorded_reason`,
  `model_version`, `available`, `unavailable_reason`, `unavailable_detail`, `top_of_book_limited`,
  and `primary` = the H row: `policy_id`, `policy_version`, `verdict`, `block_reason`,
  `bankroll_basis` {bankroll, tradable_cash, available_risk_budget}, `model_probability`,
  `conservative_probability`, `expected_net_edge`, `uncertainty` {method,
  payout_probability_min, payout_probability_max, detail} | None, `entry_price`,
  `estimated_fee`, `unconstrained_kelly_amount`, `policy_amount_before_caps` (the selected
  fractional / robust size), `caps` {liquidity, position, event, cluster, portfolio,
  cash_horizon, drawdown, maximum_allowed}, `capital_horizon` {policy_id, eligible,
  tradable_cash_release_eta_utc, elapsed_hours_to_tradable, reasons} | None, `drawdown_cap`,
  `final_contracts`, `final_amount`, `binding_constraint`, `secondary_constraints`,
  `explanation`, `fill_status`, `fill_reason`;
  plus `comparison`: one compact row per policy in `policies` order: `letter`, `policy_id`,
  `policy_version`, `verdict`, `binding_constraint`, `final_contracts`, `final_amount`,
  `bankroll_before`, `fraction_of_bankroll`.

Every number is a string (Decimal) or None, so the UI does no arithmetic. When the panel cannot
compute, `available` is false and `unavailable_reason` names why: "No model", "Fees
unsupported", "Stale quote", "Rules unresolved", "Insufficient uncertainty evidence", "Risk
state unavailable", "Unsupported payoff", "Market not open", "Capital horizon unknown",
"Evidence incomplete", "No recorded decision", "Ledger unavailable". A computed zero (for
example ZERO_EDGE or a cap) is available, with its verdict and binding constraint.
The replay costs one full pass over the ledger per call; callers may cache by ledger head hash.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import os
import sys
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import exp001_shadow, forward, risk
from . import sizing_v2 as sv2
from .fill_policy import FILLED, LATENCY_CONFIRMED_V1, simulate_fill
from .freshness import Freshness, parse_utc
from .kalshi import SETTLEMENT_SOURCE
from .kalshi_quotes import quotes_from_orderbook
from .opportunity import (
    DepthLadder, DepthLevel, ExecutableQuote, Market, MarketStatus, MarketTiming, Payoff,
)
from .risk import RiskPolicy
from .shadow_ledger import AccountState, LedgerError, Position, knowledge_time, replay
from .sizing_eval import F_HALF
from .sizing_v2 import SizingPolicyV2
from .starter_policy import StarterVerdict

RUNNER_ID = "sizing-v2-counterfactual"
RUNNER_VERSION = "1"
RUN_SCHEMA = "counterfactual-sizing-run-v1"
BUNDLE_SCHEMA = "counterfactual-sizing-bundle-v1"
PANEL_VERSION = "1"
LABEL = ("RESEARCH SIZING COUNTERFACTUAL (shadow/research only). Replays recorded decisions through "
         "the canonical sizing-v2 engine; fills only where recorded execution evidence supports them. Not an "
         "order, not a backtest of an edge, not authority to change any shadow fill. No statistical "
         "significance is implied by a small number of settlements.")
PANEL_LABEL = "RESEARCH SIZING - SHADOW SIZING CHALLENGER (counterfactual; not a bet recommendation)"

ZERO = Decimal(0)
ONE = Decimal(1)
STATES = ("YES", "NO")
YES_STATES = ("YES",)

# The directive's letters. F is "robust / pessimistic FRACTIONAL Kelly": the existing versioned
# robust 1/2 Kelly (`sizing_eval.F_HALF`, SV2-F-robust-half-kelly v1), referenced, not copied.
# (`sizing_v2.POLICY_F` is robust Kelly at fraction 1 and is unchanged.) H is the candidate.
POLICY_SET: tuple[tuple[str, SizingPolicyV2], ...] = (
    ("A", sv2.POLICY_A), ("B", sv2.POLICY_B), ("C", sv2.POLICY_C), ("D", sv2.POLICY_D), ("E", sv2.POLICY_E),
    ("F", F_HALF), ("G", sv2.POLICY_G), ("H", sv2.POLICY_CANDIDATE),
)
PRIMARY_LETTER = "H"

# Engine cap names (sizing_v2.CAP_ORDER plus the solver's own limits) counted as caps.
CAP_NAMES = frozenset({"LIQUIDITY", "TRADABLE_CASH", "POSITION_CAP", "EVENT_CAP", "CLUSTER_CAP", "PORTFOLIO_CAP",
                       "RESERVE_FLOOR", "DRAWDOWN_CAP", "RISK_BUDGET", "CASH_HORIZON", "RISK_CONSTRAINT",
                       "CVAR_CAP"})
# Recorded NO_FILL reasons of the fill model that happen before any confirmation is needed.
_ENTRY_STAGE = frozenset({"ZERO_SIZE", "NO_ENTRY_QUOTE", "STALE_ENTRY_QUOTE", "NO_ENTRY_PRICE", "INSUFFICIENT_SIZE",
                          "STAGE_B_DAY_INVALID"})
_EVIDENCE_DEFECTS = ("EVIDENCE_INCOMPLETE", "EVENT_MISMATCH")

UNAVAILABLE_NO_MODEL = "No model"
UNAVAILABLE_FEES = "Fees unsupported"
UNAVAILABLE_STALE_QUOTE = "Stale quote"
UNAVAILABLE_RULES = "Rules unresolved"
UNAVAILABLE_UNCERTAINTY = "Insufficient uncertainty evidence"
UNAVAILABLE_RISK_STATE = "Risk state unavailable"
UNAVAILABLE_PAYOFF = "Unsupported payoff"
UNAVAILABLE_MARKET = "Market not open"
UNAVAILABLE_HORIZON = "Capital horizon unknown"
UNAVAILABLE_EVIDENCE = "Evidence incomplete"
UNAVAILABLE_NO_DECISION = "No recorded decision"
UNAVAILABLE_LEDGER = "Ledger unavailable"
UNAVAILABLE_REASONS = (UNAVAILABLE_NO_MODEL, UNAVAILABLE_FEES, UNAVAILABLE_STALE_QUOTE, UNAVAILABLE_RULES,
                       UNAVAILABLE_UNCERTAINTY, UNAVAILABLE_RISK_STATE, UNAVAILABLE_PAYOFF, UNAVAILABLE_MARKET,
                       UNAVAILABLE_HORIZON, UNAVAILABLE_EVIDENCE, UNAVAILABLE_NO_DECISION, UNAVAILABLE_LEDGER)


@dataclass(frozen=True)
class CounterfactualConfig:
    """One versioned replay configuration. A changed value is a new `config_id`."""

    config_id: str = "sizing-cf-config-v1"
    starting_bankroll: Decimal = exp001_shadow.STARTING_BANKROLL
    risk_policy: RiskPolicy = exp001_shadow.RISK_POLICY
    sizing_config: sv2.SizingConfig = sv2.DEFAULT_CONFIG
    cvar_level: Decimal = Decimal("0.95")
    cvar_min_samples: int = 40  # below this, CVaR is null with a reason
    rolling_window: timedelta = timedelta(hours=168)
    mode: str = "live"  # forward-capture mode used to find a day's re-check capture

    def to_dict(self) -> dict[str, Any]:
        return sv2._plain(self)


DEFAULT_CONFIG = CounterfactualConfig()


class CounterfactualInputError(RuntimeError):
    """The replay inputs cannot be read consistently (for example a broken hash chain)."""


# =========================================================================== small helpers


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(timezone.utc).isoformat()


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _m(value: Decimal) -> str:
    """Simulated money as a cent string. Costs are whole cents and payouts whole dollars, so
    this never rounds; it only makes "1000" and "1000.00" one spelling."""
    return str(value.quantize(sv2.CENT, rounding=ROUND_FLOOR))


def _f(value: float | None, places: int = 10) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return f"{value:.{places}f}"


def _ratio(num: Decimal | None, den: Decimal | None) -> str | None:
    if num is None or den is None or den == 0:
        return None
    return str((num / den).quantize(Decimal("1e-10"), rounding=ROUND_FLOOR))


def _code(reason: str | None) -> str | None:
    if not reason:
        return None
    return reason.split(":", 1)[0].strip() or None


def source_hash(path: Path) -> str:
    """LF-normalized SHA-256 of a source file (stable across checkouts)."""
    text = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()


_SOURCES = ("sizing_counterfactual.py", "sizing_v2.py", "sizing_eval.py","risk.py", "fill_policy.py", "fee_schedules.py",
            "opportunity.py", "shadow_ledger.py", "starter_policy.py", "exp001_shadow.py", "settlement.py")


def code_hashes() -> dict[str, str]:
    here = Path(__file__).resolve().parent
    return {name: source_hash(here / name) for name in _SOURCES}


# =========================================================================== inputs


@dataclass(frozen=True)
class DecisionRecord:
    """One recorded decision, merged across the accounts that recorded it."""

    decision_id: str
    accounts: tuple[str, ...]
    as_of: datetime
    as_of_utc: str
    market_id: str
    venue: str
    native_id: str
    side: str
    event_id: str
    cluster: str
    qualification: str
    reason: str | None
    reasons: tuple[str, ...]
    model_version: str | None
    opportunity: Mapping[str, Any]
    starter: Mapping[str, Any] | None
    day_status: str | None
    target_date: str | None
    fills: tuple[Mapping[str, Any], ...]  # recorded fill payloads (any account), known by the cutoff
    problem: str | None  # a runner-level defect: the decision cannot be replayed as recorded

    def sort_key(self) -> tuple[Any, ...]:
        return (self.as_of, self.market_id, self.side, self.decision_id)


@dataclass(frozen=True)
class Outcome:
    market_id: str
    outcome: str | None  # YES | NO; None when unknown or in conflict
    known_at: datetime | None
    settled_at: datetime | None
    source: str
    detail: str
    evidence_ids: tuple[str, ...] = ()


@dataclass
class ReplayInputs:
    decisions: list[DecisionRecord]
    outcomes: dict[str, Outcome]
    cutoff: datetime
    account_heads: dict[str, dict[str, Any]]
    store: Any
    config: CounterfactualConfig
    evidence_ids: set[str] = field(default_factory=set)
    _confirmations: dict[str, tuple[ExecutableQuote | None, str]] = field(default_factory=dict)
    _rechecks: dict[str, dict[tuple[str, str], ExecutableQuote] | None] = field(default_factory=dict)
    _fills: dict[tuple[str, int], "_FillResult"] = field(default_factory=dict)

    def decisions_hash(self) -> str:
        return sv2.canonical_hash([{"decision_id": d.decision_id, "accounts": list(d.accounts),
                                    "as_of_utc": d.as_of_utc, "opportunity": d.opportunity,
                                    "starter": d.starter, "fills": list(d.fills), "problem": d.problem}
                                   for d in self.decisions])


def _payload(row: Any) -> dict[str, Any]:
    return json.loads(row["payload_json"])


def load_inputs(store: Any, ledger: Any, *, cutoff: datetime | None = None,
                config: CounterfactualConfig = DEFAULT_CONFIG, accounts: Sequence[str] | None = None) -> ReplayInputs:
    """Read every decision, fill and settlement known by `cutoff` (default: the latest knowledge
    time in the ledger and the captured settlement evidence). Each account is replayed in full
    first, so a broken hash chain or invariant fails the whole run (never a partial read)."""
    if cutoff is not None and parse_utc(cutoff) is None:
        raise ValueError("cutoff must be timezone-aware")
    cutoff = parse_utc(cutoff) if cutoff is not None else None
    names = sorted(accounts) if accounts else sorted(ledger.accounts())
    rows_by_account: dict[str, list[Any]] = {}
    heads: dict[str, dict[str, Any]] = {}
    latest: datetime | None = None
    for acct in names:
        rows = ledger.entries(acct)
        if not rows:
            raise CounterfactualInputError(f"account {acct} has no ledger entries")
        try:
            state = replay(rows)
        except LedgerError as exc:
            raise CounterfactualInputError(f"account {acct}: {exc}") from exc
        heads[acct] = {"head_hash": state.last_entry_hash, "entries": len(rows)}
        rows_by_account[acct] = rows
        for row in rows:
            known = knowledge_time(row)
            if known is not None and (latest is None or known > latest):
                latest = known

    settlement_times = _settlement_times(store)
    if cutoff is None:
        candidates = [t for t in [latest, *settlement_times] if t is not None]
        if not candidates:
            raise CounterfactualInputError("no ledger entries or settlement evidence to replay")
        cutoff = max(candidates)

    decisions: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    fills: dict[str, list[dict[str, Any]]] = {}
    ledger_settlements: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for acct, rows in rows_by_account.items():
        for row in rows:
            if row["kind"] == "account_opened":
                continue
            known = knowledge_time(row)
            if known is None or known > cutoff:
                continue
            payload = _payload(row)
            if row["kind"] == "decision":
                decisions.setdefault(str(payload.get("decision_id")), []).append((acct, payload))
            elif row["kind"] == "fill":
                fills.setdefault(str(payload.get("decision_id")), []).append(payload)
            elif row["kind"] == "settlement":
                ledger_settlements.setdefault(str(payload.get("market_id")), []).append((known, payload))

    records = [_merge_decision(did, entries, fills.get(did, [])) for did, entries in decisions.items()]
    records.sort(key=DecisionRecord.sort_key)
    markets = sorted({r.market_id for r in records if r.market_id})
    outcomes, evidence = _outcomes(store, markets, ledger_settlements, cutoff)
    return ReplayInputs(records, outcomes, cutoff, heads, store, config, evidence)


def _merge_decision(did: str, entries: list[tuple[str, dict[str, Any]]],
                    fills: list[dict[str, Any]]) -> DecisionRecord:
    accounts = tuple(a for a, _ in entries)
    first = entries[0][1]
    problem = None
    core = ("as_of_utc", "market_id", "side", "event_id", "outcome_cluster", "qualification", "opportunity")
    for _, other in entries[1:]:
        if any(other.get(k) != first.get(k) for k in core):
            problem = "DECISION_RECORDS_DISAGREE: accounts recorded different content for this decision"
    starter = next((p.get("starter_policy") for _, p in entries if isinstance(p.get("starter_policy"), Mapping)), None)
    opp = first.get("opportunity") if isinstance(first.get("opportunity"), Mapping) else {}
    market_id = str(first.get("market_id") or opp.get("market_id") or "")
    side = str(first.get("side") or opp.get("side") or "")
    as_of = parse_utc(first.get("as_of_utc"))
    venue, _, native = market_id.partition(":")
    if problem is None and (as_of is None or not market_id or not native or not isinstance(first.get("opportunity"),
                                                                                           Mapping)):
        problem = "DECISION_PAYLOAD_UNSUPPORTED: the decision lacks a decision time, market id or opportunity record"
    reasons = first.get("reasons")
    if not isinstance(reasons, list):
        reasons = opp.get("reasons") if isinstance(opp.get("reasons"), list) else []
    slot = str(first.get("slot") or "")
    target = slot.split("|", 1)[0] if "|" in slot else None
    return DecisionRecord(
        decision_id=did, accounts=accounts, as_of=as_of or datetime.min.replace(tzinfo=timezone.utc),
        as_of_utc=str(first.get("as_of_utc")), market_id=market_id, venue=venue, native_id=native, side=side,
        event_id=str(first.get("event_id") or opp.get("event_id") or ""),
        cluster=str(first.get("outcome_cluster") or opp.get("outcome_cluster") or ""),
        qualification=str(first.get("qualification")), reason=first.get("reason"),
        reasons=tuple(str(r) for r in reasons), model_version=first.get("model_version") or opp.get("model_version"),
        opportunity=opp, starter=starter, day_status=first.get("stage_b_day_status"), target_date=target,
        fills=tuple(sorted(fills, key=lambda f: json.dumps(f, sort_keys=True, default=str))), problem=problem)


# ---------------------------------------------------------------- settlement outcomes


def _settlement_rows(store: Any) -> list[Any]:
    if store is None:
        return []
    rows = []
    for kind in exp001_shadow.SETTLEMENT_KINDS:
        rows.extend(store.snapshots_of_kind(source=SETTLEMENT_SOURCE.legacy_name, kind=kind))
    return rows


def _settlement_times(store: Any) -> list[datetime]:
    return sorted({t for t in (parse_utc(r["fetched_at_utc"]) for r in _settlement_rows(store)) if t is not None})


def _outcomes(store: Any, market_ids: Sequence[str], ledger_settlements: Mapping[str, list[tuple[datetime, dict]]],
              cutoff: datetime) -> tuple[dict[str, Outcome], set[str]]:
    """The outcome per market and when it became known, under the canonical settlement rules."""
    evidence: set[str] = set()
    found: dict[str, Outcome] = {}
    natives = {m: m.split(":", 1)[1] for m in market_ids if m.startswith("kalshi:")}
    times = [t for t in _settlement_times(store) if t <= cutoff]
    pending = set(natives)
    for t in times:  # the first capture time at which each outcome is conclusive
        if not pending:
            break
        index = exp001_shadow.settlement_index(store, known_by=t)
        problems = exp001_shadow.event_settlement_problems(index)
        for mid in sorted(pending):
            entry = index.get(natives[mid])
            if entry is None or len(entry["variants"]) > 1:
                continue
            market = entry["market"]
            event = market.get("event_ticker")
            if not isinstance(event, str) or not event or problems.get(event):
                continue
            outcome, why = exp001_shadow.official_outcome(market)
            if outcome is None:
                continue
            reported = parse_utc(str(market.get("settlement_ts") or market.get("expiration_time")
                                     or market.get("close_time") or ""))
            received = parse_utc(entry["evidence_available_utc"])
            settled = reported if reported is not None and received is not None and reported <= received else received
            found[mid] = Outcome(mid, outcome, t, settled, "evidence_db", why, (f"snapshot:{entry['snapshot_id']}",))
            pending.discard(mid)
    if times and found:
        # Point-in-time: an outcome is booked when it first became conclusive, as the canonical
        # path books it. Evidence captured later that contradicts it is reported here, never
        # applied retroactively (that would let later information change earlier states).
        final = exp001_shadow.settlement_index(store, known_by=cutoff)
        final_problems = exp001_shadow.event_settlement_problems(final)
        for mid, out in list(found.items()):
            entry = final.get(natives[mid])
            latest = exp001_shadow.official_outcome(entry["market"])[0] if entry else None
            event = str((entry or {}).get("market", {}).get("event_ticker") or "")
            if entry is None or len(entry["variants"]) > 1 or latest != out.outcome or final_problems.get(event):
                found[mid] = replace(out, detail=out.detail + "; CONTRADICTED_LATER: evidence captured by the cutoff "
                                                              "contradicts this outcome (reported, not applied)")
    for mid in market_ids:
        rows = sorted(ledger_settlements.get(mid, []), key=lambda x: x[0])
        led = [(k, p) for k, p in rows if p.get("outcome") in ("YES", "NO")]
        current = found.get(mid)
        if led:
            outcomes = {p["outcome"] for _, p in led}
            if len(outcomes) > 1 or (current is not None and current.outcome not in (None, *outcomes)):
                found[mid] = Outcome(mid, None, None, None, "conflict",
                                     "SETTLEMENT_CONFLICT: ledger settlements and captured evidence disagree")
                continue
            if current is None:
                known, p = led[0]
                settled = parse_utc(p.get("settled_at_utc"))
                found[mid] = Outcome(mid, p["outcome"], known, settled if settled and settled <= known else known,
                                     "ledger", "ledger settlement entry")
    for out in found.values():
        evidence.update(out.evidence_ids)
    return found, evidence


# ---------------------------------------------------------------- execution evidence


@dataclass(frozen=True)
class _FillResult:
    status: str  # FILLED | NO_FILL
    reason: str
    known_at: datetime
    rank: int  # event rank at `known_at` (0: before same-time decisions, 2: after)
    detail: str
    basis: str


def _entry_quote(d: DecisionRecord) -> ExecutableQuote | None:
    opp = d.opportunity
    price = _dec(opp.get("executable_price"))
    received = opp.get("quote_received_at_utc")
    if price is None and "BOOK_MISSING" in d.reasons:
        return None
    anomaly = "INVALID_PRICE (recorded)" if "INVALID_PRICE" in d.reasons else None
    return ExecutableQuote(d.venue, d.market_id, d.side, None, price, _dec(opp.get("displayed_size")), received,
                           None, opp.get("quote_evidence_id"), anomaly)


def _snapshot_quote(store: Any, evidence_id: str, market_id: str, side: str) -> ExecutableQuote | None:
    if not evidence_id.startswith("snapshot:"):
        return None
    try:
        sid = int(evidence_id.split(":", 1)[1])
    except ValueError:
        return None
    snap = store.snapshots_by_id([sid]).get(sid)
    if snap is None or snap["kind"] != "orderbook":
        return None
    quotes = quotes_from_orderbook(snap["entity_id"], json.loads(snap["payload_json"]),
                                   received_at_utc=snap["fetched_at_utc"], evidence_id=evidence_id)
    quote = quotes.get(side)
    return quote if quote is not None and quote.market_id == market_id else None


def _confirmation(inputs: ReplayInputs, d: DecisionRecord) -> tuple[ExecutableQuote | None, str]:
    """The re-check quote for this decision and how it was found (evidence DB only)."""
    if d.decision_id in inputs._confirmations:
        return inputs._confirmations[d.decision_id]
    store = inputs.store
    result: tuple[ExecutableQuote | None, str] = (None, "NO_EVIDENCE_DB")
    if store is not None and d.venue != "kalshi":
        result = (None, "VENUE_BOOK_FORMAT_UNSUPPORTED")
    if store is not None and d.venue == "kalshi":
        result = (None, "NO_CONFIRMATION_EVIDENCE")
        ids = sorted({str(f.get("confirmation_evidence_id")) for f in d.fills if f.get("confirmation_evidence_id")})
        for eid in ids:
            quote = _snapshot_quote(store, eid, d.market_id, d.side)
            if quote is not None:
                result = (quote, "RECORDED_FILL_CONFIRMATION")
                break
        if result[0] is None and d.target_date:
            quotes = _recheck_quotes(inputs, d.target_date)
            quote = None if quotes is None else quotes.get((d.market_id, d.side))
            if quote is not None:
                result = (quote, "DAY_RECHECK_CAPTURE")
    inputs._confirmations[d.decision_id] = result
    return result


def _recheck_quotes(inputs: ReplayInputs, target: str) -> dict[tuple[str, str], ExecutableQuote] | None:
    if target not in inputs._rechecks:
        quotes = None
        try:
            day = forward.day_status(inputs.store, date.fromisoformat(target), mode=inputs.config.mode)
            quotes = exp001_shadow._recheck_quotes(inputs.store, day, inputs.config.mode)
        except Exception:  # noqa: BLE001 - missing or old evidence: no confirmation, reported as such
            quotes = None
        inputs._rechecks[target] = quotes
    return inputs._rechecks[target]


def execution(inputs: ReplayInputs, d: DecisionRecord, contracts: int) -> _FillResult:
    """Would `contracts` of this decision have filled under latency-confirmed-v1? Policy-independent."""
    key = (d.decision_id, contracts)
    if key in inputs._fills:
        return inputs._fills[key]
    window_end = d.as_of + LATENCY_CONFIRMED_V1.confirm_max
    if d.day_status is not None and d.day_status != "VALID":
        out = _FillResult("NO_FILL", "STAGE_B_DAY_INVALID", d.as_of, 2,
                          "the Stage B day is INVALID: excluded, never traded (as the canonical path)", "RECORDED_DAY")
    else:
        confirmation, basis = _confirmation(inputs, d)
        if confirmation is None and inputs.store is None:
            recorded = [f for f in d.fills if f.get("status") == FILLED and int(f.get("quantity") or 0) >= contracts
                        and parse_utc(f.get("filled_at_utc")) is not None]
            if recorded:
                at = min(parse_utc(f["filled_at_utc"]) for f in recorded)
                out = _FillResult(FILLED, "FILLED", max(at, d.as_of), 0 if at > d.as_of else 2,
                                  "a recorded latency-confirmed fill of at least this quantity", "RECORDED_FILL")
            else:
                out = _FillResult("NO_FILL", "CONFIRMATION_EVIDENCE_UNAVAILABLE", window_end, 0,
                                  "no evidence database and no recorded fill of this quantity", basis)
        else:
            result = simulate_fill(quantity=contracts, entry=_entry_quote(d), confirmation=confirmation, as_of=d.as_of)
            confirmed = parse_utc(confirmation.received_at_utc) if confirmation is not None else None
            if result.status == FILLED and confirmed is not None:
                out = _FillResult(FILLED, "FILLED", max(confirmed, d.as_of), 0 if confirmed > d.as_of else 2,
                                  result.detail, basis)
            elif result.status == FILLED:  # unreachable: a fill needs a confirmation time
                out = _FillResult("NO_FILL", "CONFIRMATION_TIME_UNKNOWN", window_end, 0, result.detail, basis)
            elif result.reason in _ENTRY_STAGE:
                out = _FillResult("NO_FILL", result.reason, d.as_of, 2, result.detail, basis)
            else:
                at = max(confirmed, d.as_of) if confirmed is not None else window_end
                out = _FillResult("NO_FILL", result.reason, at, 0 if at > d.as_of else 2, result.detail, basis)
    inputs._fills[key] = out
    return out


# =========================================================================== request building


def _siblings(decisions: Sequence[DecisionRecord]) -> dict[tuple[str, datetime], dict[str, DecisionRecord]]:
    out: dict[tuple[str, datetime], dict[str, DecisionRecord]] = {}
    for d in decisions:
        if d.problem is None:
            out.setdefault((d.market_id, d.as_of), {}).setdefault(d.side, d)
    return out


def _model(d: DecisionRecord, sibs: Mapping[str, DecisionRecord]) -> tuple[tuple[float, float] | None, Any, str]:
    """(P(YES), P(NO)), the admissible set, and how the set was built."""
    def p_yes(rec: DecisionRecord) -> float | None:
        p = _dec(rec.opportunity.get("model_probability"))
        if p is None or not (ZERO <= p <= ONE):
            return None
        return float(p) if rec.side == "YES" else float(ONE - p)

    points = {rec.side: p_yes(rec) for rec in sibs.values() if p_yes(rec) is not None}
    if len(points) > 1 and max(points.values()) - min(points.values()) > 1e-9:
        return None, None, f"MODEL_INCONSISTENT: the recorded sides imply different P(YES) {sorted(points.items())}"
    source = sibs.get("YES") if sibs.get("YES") is not None and p_yes(sibs["YES"]) is not None else d
    point = p_yes(source)
    if point is None:
        return None, None, "no model probability recorded"
    lower = upper = None
    notes = []
    yes, no = sibs.get("YES"), sibs.get("NO")
    if yes is not None:
        c = _dec(yes.opportunity.get("conservative_probability"))
        lower = None if c is None else float(c)
    if no is not None:
        c = _dec(no.opportunity.get("conservative_probability"))
        upper = None if c is None else float(ONE - c)
    if lower is None and upper is None:
        return (point, 1.0 - point), None, "no conservative bound recorded (uncertainty unknown)"
    if lower is None:
        lower, notes = 0.0, notes + ["lower bound not recorded: widened to 0"]
    if upper is None:
        upper, notes = 1.0, notes + ["upper bound not recorded: widened to 1"]
    try:
        box = sv2.binary_interval(point, min(lower, point), max(upper, point), states=STATES,
                                  method="recorded-conservative-bounds-v1")
    except ValueError as exc:
        return (point, 1.0 - point), None, f"recorded bounds unusable: {exc}"
    if lower > point + 1e-12 or upper < point - 1e-12:
        notes.append("a recorded bound was on the wrong side of the point and was clipped to it")
    return (point, 1.0 - point), box, "; ".join(notes) or "both recorded conservative bounds"


def _market(d: DecisionRecord, verdict: StarterVerdict | None) -> Market:
    reasons = set(d.reasons)
    payoff = Payoff("unsupported (recorded PAYOFF_UNSUPPORTED)" if "PAYOFF_UNSUPPORTED" in reasons else "binary",
                    ONE, str(d.opportunity.get("outcome") or ""))
    timing = None
    if verdict is not None:  # the decision's own recorded verdict: the ledger binds it to this market
        timing = MarketTiming(event_end_utc=verdict.event_end_utc, source=verdict.timing_source)
    return Market(d.venue, d.market_id, d.native_id, d.event_id, str(d.opportunity.get("outcome") or ""), payoff,
                  None, MarketStatus.CLOSED if "MARKET_CLOSED" in reasons else MarketStatus.OPEN,
                  "RULES_UNRESOLVED" not in reasons,
                  "recorded RULES_UNRESOLVED at the decision" if "RULES_UNRESOLVED" in reasons else "resolved (recorded)",
                  timing, None)


def _ladder(d: DecisionRecord) -> DepthLadder | None:
    opp = d.opportunity
    price, size = _dec(opp.get("executable_price")), _dec(opp.get("displayed_size"))
    received = opp.get("quote_received_at_utc")
    if "BOOK_MISSING" in d.reasons or received is None:
        return None
    anomaly = "INVALID_PRICE (recorded)" if "INVALID_PRICE" in d.reasons else None
    if price is None:
        if anomaly:
            return None  # a malformed book with no price: nothing usable was captured
        asks: tuple[DepthLevel, ...] = ()
    else:
        asks = (DepthLevel(price, size),) if size is not None and size > 0 else ()
    # Only the top level was recorded: deeper levels may exist but were not captured.
    return DepthLadder(d.venue, d.market_id, d.side, asks, True, received, None, opp.get("quote_evidence_id"), anomaly)


def _starter(d: DecisionRecord) -> StarterVerdict | None:
    if not isinstance(d.starter, Mapping):
        return None
    names = {f.name for f in fields(StarterVerdict)}
    data = {k: v for k, v in d.starter.items() if k in names}
    try:
        data["reasons"] = tuple(data.get("reasons") or ())
        data["detail"] = tuple(data.get("detail") or ())
        return StarterVerdict(**data)
    except TypeError:
        return None


# =========================================================================== per-policy simulation


@dataclass
class _Pos:
    position_id: str
    decision: DecisionRecord
    contracts: int
    cost: Decimal
    fee: Decimal
    reserved_at: datetime
    bankroll_before: Decimal
    expected_settlement_utc: str | None
    status: str = "RESERVED"  # RESERVED | OPEN | SETTLED | RELEASED
    fill: _FillResult | None = None
    settle_known_at: datetime | None = None
    settled_at: datetime | None = None
    outcome: str | None = None
    payout: Decimal | None = None
    net_pnl: Decimal | None = None
    released_at: datetime | None = None
    equity_after: Decimal | None = None


class _Sim:
    def __init__(self, letter: str, policy: SizingPolicyV2, config: CounterfactualConfig) -> None:
        self.letter, self.policy, self.config = letter, policy, config
        self.cash = config.starting_bankroll
        self.positions: dict[str, _Pos] = {}
        self.order: list[str] = []
        self.realized = ZERO
        self.curve: list[tuple[datetime | None, Decimal]] = [(None, config.starting_bankroll)]

    @property
    def committed(self) -> Decimal:
        return sum((p.cost for p in self.positions.values() if p.status in ("RESERVED", "OPEN")), ZERO)

    @property
    def equity(self) -> Decimal:
        return self.cash + self.committed

    def account(self) -> AccountState:
        start = self.config.starting_bankroll
        rows = []
        for pid in self.order:
            p = self.positions[pid]
            if p.status == "RELEASED":
                continue
            d = p.decision
            rows.append(Position(
                position_id=pid, decision_id=d.decision_id, account_id=f"counterfactual:{self.policy.policy_id}",
                opened_at_utc=_iso(p.reserved_at), venue=d.venue, market_id=d.market_id, event_id=d.event_id,
                outcome_cluster=d.cluster, side=d.side, quantity=p.contracts,
                price=(p.cost / p.contracts), cost_basis=p.cost, fees=p.fee, max_downside=p.cost,
                potential_payout=Decimal(p.contracts), strategy=RUNNER_ID,
                expected_settlement_utc=p.expected_settlement_utc,
                status="SETTLED" if p.status == "SETTLED" else "OPEN", outcome=p.outcome, payout=p.payout,
                net_pnl=p.net_pnl, settled_at_utc=_iso(p.settled_at)))
        open_ = [r for r in rows if r.status == "OPEN"]
        committed = sum((r.cost_basis for r in open_), ZERO)
        return AccountState(
            account_id=f"counterfactual:{self.policy.policy_id}", strategy=RUNNER_ID, starting_bankroll=start,
            settled_cash=self.cash, committed_capital=committed, open_worst_case_risk=committed,
            open_potential_payout=sum((r.potential_payout for r in open_), ZERO), realized_pnl=self.realized,
            fees_paid=sum((r.fees for r in rows), ZERO), equity=self.cash + committed, decisions=0,
            qualified_decisions=0, fills=len(rows), no_fills=0, settlements=len(rows) - len(open_), positions=rows)

    def portfolio(self, as_of: datetime) -> tuple[sv2.PortfolioState | None, str | None]:
        try:
            report = risk.assess(self.account(), self.config.risk_policy, as_of)
            return sv2.portfolio_state(report, self.config.risk_policy), None
        except (ValueError, ArithmeticError) as exc:
            return None, f"RISK_STATE_UNAVAILABLE: {exc}"

    def held(self, market_id: str) -> tuple[sv2.HeldPosition, ...]:
        return tuple(sv2.HeldPosition(market_id, p.decision.side, YES_STATES, p.contracts, p.cost)
                     for pid in self.order for p in (self.positions[pid],)
                     if p.status in ("RESERVED", "OPEN") and p.decision.market_id == market_id)


def _expected_settlement(d: DecisionRecord, verdict: StarterVerdict | None) -> str | None:
    for f in d.fills:
        if f.get("expected_settlement_utc"):
            return str(f["expected_settlement_utc"])
    return None if verdict is None else verdict.resolution_eta_utc


def _blocked_row(d: DecisionRecord, sim: _Sim, verdict: str, reason: str) -> dict[str, Any]:
    return {"verdict": verdict, "verdict_source": "runner", "block_reason": reason,
            "binding_constraint": _code(reason), "secondary_constraints": [], "contracts": 0,
            "recommended_size": "0", "unconstrained_size": None, "unconstrained_kelly_amount": None,
            "model_probability": None, "conservative_probability": None, "expected_net_edge": None,
            "probability_uncertainty": None, "entry_price": None, "estimated_fee": None,
            "all_constraints": {}, "explanation": f"{sv2.LABEL}. Runner refused the decision: {reason}.",
            "recommendation_output_hash": None, "bankroll_before": _m(sim.equity)}


def _rec_row(rec: sv2.SizingRecommendation, block: str | None) -> dict[str, Any]:
    u = rec.probability_uncertainty
    return {
        "verdict": rec.verdict, "verdict_source": "engine", "block_reason": block or None,
        "binding_constraint": rec.binding_constraint, "secondary_constraints": list(rec.secondary_constraints),
        "contracts": rec.recommended_contracts, "recommended_size": str(rec.recommended_amount),
        "unconstrained_size": _s(rec.fractional_kelly_amount),
        "unconstrained_kelly_amount": _s(rec.unconstrained_kelly_amount),
        "model_probability": _s(rec.model_probability), "conservative_probability": _s(rec.conservative_probability),
        "expected_net_edge": _s(rec.expected_net_edge),
        "probability_uncertainty": None if u is None else {
            "method": u.method, "payout_probability_min": _s(u.payout_probability_min),
            "payout_probability_max": _s(u.payout_probability_max), "detail": u.detail},
        "entry_price": _s(rec.entry_price), "estimated_fee": _s(rec.estimated_fee),
        "all_constraints": {
            "liquidity_cap": _s(rec.liquidity_cap), "position_cap": _s(rec.position_cap),
            "event_cap": _s(rec.event_cap), "cluster_cap": _s(rec.cluster_cap),
            "portfolio_cap": _s(rec.portfolio_cap), "cash_horizon_cap": _s(rec.cash_horizon_cap),
            "drawdown_cap": _s(rec.drawdown_cap), "maximum_allowed_amount": _s(rec.maximum_allowed_amount),
            "tradable_cash": _s(rec.tradable_cash), "available_risk_budget": _s(rec.available_risk_budget)},
        "explanation": rec.explanation, "recommendation_output_hash": rec.output_hash,
        "bankroll_before": _s(rec.bankroll),
    }


def _decide(inputs: ReplayInputs, sim: _Sim, d: DecisionRecord,
            sibs: Mapping[str, DecisionRecord]) -> tuple[dict[str, Any], sv2.SizingRecommendation | None]:
    """Size one recorded decision for one policy, at its decision time, on the policy's own state."""
    if d.problem:
        return _blocked_row(d, sim, "UNSUPPORTED", d.problem), None
    defect = next((r for r in _EVIDENCE_DEFECTS if r in d.reasons), None)
    if defect:
        return _blocked_row(d, sim, "STALE_DATA", f"{defect}: recorded at the decision; the evidence set is "
                                                  "defective, so no size is computed"), None
    verdict = _starter(d)
    probs, uset, basis = _model(d, sibs)
    if basis.startswith("MODEL_INCONSISTENT"):
        return _blocked_row(d, sim, "STALE_DATA", basis), None
    fresh = str(d.opportunity.get("model_freshness") or "").lower() == Freshness.FRESH.value
    portfolio, problem = sim.portfolio(d.as_of)
    request = sv2.SizingRequest(
        as_of_utc=d.as_of_utc, states=STATES,
        candidate=sv2.PositionCandidate(_market(d, verdict), d.side, YES_STATES, _ladder(d), d.event_id, d.cluster),
        model_probabilities=probs, uncertainty=uset, model_version=d.model_version,
        model_generated_at_utc=d.as_of_utc if (probs is not None and fresh) else None,
        portfolio=portfolio, starter=verdict, held=sim.held(d.market_id))
    cfg = inputs.config.sizing_config
    try:
        blocked, reason = sv2.precheck(request, cfg)
        rec = sv2.recommend(request, sim.policy, cfg)
    except (ValueError, ArithmeticError, TypeError) as exc:  # inconsistent inputs: refuse, never guess
        return _blocked_row(d, sim, "UNSUPPORTED", f"ENGINE_REFUSED_INPUT: {exc}"), None
    row = _rec_row(rec, reason if blocked is not None else None)
    row["uncertainty_basis"] = basis
    if problem:
        row["risk_state_problem"] = problem
    return row, rec


def _run_policy(inputs: ReplayInputs, letter: str, policy: SizingPolicyV2,
                stop_after: datetime | None = None) -> tuple[_Sim, list[dict[str, Any]]]:
    sim = _Sim(letter, policy, inputs.config)
    cutoff = inputs.cutoff if stop_after is None else min(inputs.cutoff, stop_after)
    sibs = _siblings(inputs.decisions)
    heap: list[tuple[datetime, int, int, str, str]] = []
    seq = 0
    for i, d in enumerate(inputs.decisions):
        if d.as_of <= cutoff:
            heap.append((d.as_of, 1, seq, "DECISION", str(i)))
            seq += 1
    heapq.heapify(heap)
    rows: list[dict[str, Any]] = []
    row_by_position: dict[str, dict[str, Any]] = {}
    while heap:
        at, _, _, kind, ref = heapq.heappop(heap)
        if at > cutoff:
            break
        if kind == "DECISION":
            d = inputs.decisions[int(ref)]
            before = sim.equity
            cash_before = sim.cash
            row, rec = _decide(inputs, sim, d, sibs.get((d.market_id, d.as_of), {}))
            row.update(_decision_fields(d, letter, policy))
            row["bankroll_before"] = row.get("bankroll_before") or _m(before)
            row["cash_before"] = _m(cash_before)
            n = int(row["contracts"])
            row["would_trade"] = n > 0
            # The exact zero-size reason: the verdict plus the refusal code or the binding constraint.
            row["zero_size_reason"] = None if n > 0 else (
                f"{row['verdict']}:{_code(row.get('block_reason')) or row['binding_constraint']}")
            outcome = inputs.outcomes.get(d.market_id)
            known = outcome is not None and outcome.outcome is not None and outcome.known_at is not None
            row["later_outcome"] = outcome.outcome if known else None
            row["later_outcome_known_utc"] = _iso(outcome.known_at) if known else None
            row["later_outcome_source"] = None if outcome is None else outcome.source
            row.update({"fill_status": None, "fill_reason": None, "fill_known_utc": None, "fill_basis": None,
                        "hypothetical_net_pnl": None, "settlement_known_utc": None, "position_status": None,
                        "bankroll_after": _m(before), "bankroll_after_utc": d.as_of_utc})
            if n > 0 and rec is not None:
                amount = rec.recommended_amount
                verdict = _starter(d)
                pos = _Pos(f"cf-{d.decision_id}", d, n, amount, rec.estimated_fee or ZERO, d.as_of,
                           Decimal(row["bankroll_before"]), _expected_settlement(d, verdict))
                sim.positions[pos.position_id] = pos
                sim.order.append(pos.position_id)
                sim.cash -= amount
                fill = execution(inputs, d, n)
                pos.fill = fill
                row_by_position[pos.position_id] = row
                row.update({"fill_status": fill.status, "fill_reason": fill.reason, "fill_basis": fill.basis,
                            "fill_known_utc": _iso(fill.known_at), "position_status": "RESERVED"})
                heapq.heappush(heap, (fill.known_at, fill.rank, seq, "FILL", pos.position_id))
                seq += 1
            rows.append(row)
        elif kind == "FILL":
            pos = sim.positions[ref]
            row = row_by_position[ref]
            assert pos.fill is not None
            if pos.fill.status == FILLED:
                pos.status = "OPEN"
                row["position_status"] = "OPEN"
                row["bankroll_after"], row["bankroll_after_utc"] = _m(sim.equity), _iso(at)
                outcome = inputs.outcomes.get(pos.decision.market_id)
                if outcome is not None and outcome.outcome is not None and outcome.known_at is not None:
                    when = max(outcome.known_at, at)
                    heapq.heappush(heap, (when, 0, seq, "SETTLE", ref))
                    seq += 1
            else:
                pos.status, pos.released_at = "RELEASED", at
                sim.cash += pos.cost
                row["position_status"] = "RELEASED"
                row["bankroll_after"], row["bankroll_after_utc"] = _m(sim.equity), _iso(at)
        else:  # SETTLE
            pos = sim.positions[ref]
            row = row_by_position[ref]
            outcome = inputs.outcomes[pos.decision.market_id]
            pos.outcome = outcome.outcome
            pos.payout = Decimal(pos.contracts) if outcome.outcome == pos.decision.side else ZERO
            pos.net_pnl = pos.payout - pos.cost
            settled = outcome.settled_at or at
            pos.settled_at = max(settled, pos.reserved_at)
            pos.settle_known_at, pos.status = at, "SETTLED"
            sim.cash += pos.payout
            sim.realized += pos.net_pnl
            sim.curve.append((at, sim.equity))
            pos.equity_after = sim.equity
            row.update({"position_status": "SETTLED", "hypothetical_net_pnl": _m(pos.net_pnl),
                        "settlement_known_utc": _iso(at), "bankroll_after": _m(sim.equity),
                        "bankroll_after_utc": _iso(at)})
    return sim, rows


def _decision_fields(d: DecisionRecord, letter: str, policy: SizingPolicyV2) -> dict[str, Any]:
    return {"decision_id": d.decision_id, "market_id": d.market_id, "side": d.side, "event_id": d.event_id,
            "outcome_cluster": d.cluster, "decision_time": d.as_of_utc, "policy_letter": letter,
            "policy_id": policy.policy_id, "policy_version": policy.policy_version,
            "recorded_qualification": d.qualification, "recorded_reason": d.reason,
            "recorded_reasons": list(d.reasons), "recorded_in_accounts": list(d.accounts),
            "model_version": d.model_version, "top_of_book_limited": True}


# =========================================================================== metrics and runs


@dataclass(frozen=True)
class CounterfactualSizingRun:
    """One policy's counterfactual replay. Versioned by `schema`; deterministic JSON."""

    schema: str
    run_id: str
    policy_letter: str
    policy_id: str
    policy_version: str
    policy_description: str
    dataset_cutoff: str
    decision_count: int
    sized_count: int
    fill_count: int
    settled_count: int
    starting_bankroll: str
    ending_bankroll: str
    net_pnl: str
    max_drawdown: str
    turnover: str
    capital_lock: dict[str, Any]
    veto_counts: dict[str, int]
    cap_counts: dict[str, int]
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    label: str = LABEL

    def to_dict(self) -> dict[str, Any]:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out["events"] = list(self.events)
        return out


def _count(values: Iterable[str | None]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _drawdowns(curve: Sequence[tuple[datetime | None, Decimal]], window: timedelta) -> dict[str, Any]:
    peak = curve[0][1]
    max_dd = ZERO
    max_frac = 0.0
    fracs = []
    for _, e in curve:
        peak = max(peak, e)
        dd = peak - e
        max_dd = max(max_dd, dd)
        frac = float(dd / peak) if peak > 0 else 0.0
        max_frac = max(max_frac, frac)
        fracs.append(frac)
    worst_roll = ZERO
    timed = [(t, e) for t, e in curve]
    for i, (ti, ei) in enumerate(timed):
        for tj, ej in timed[i + 1:]:
            if ti is not None and tj is not None and tj - ti > window:
                break
            worst_roll = max(worst_roll, ei - ej)
    return {"max_drawdown": _m(max_dd), "max_drawdown_fraction": _f(max_frac),
            "avg_drawdown_fraction": _f(sum(fracs) / len(fracs)) if fracs else None,
            "worst_rolling_drawdown": _m(worst_roll),
            "rolling_window_hours": int(window.total_seconds() // 3600),
            "high_water_mark": _m(max(e for _, e in curve))}


def _metrics(sim: _Sim, rows: list[dict[str, Any]], cutoff: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = sim.config
    start = cfg.starting_bankroll
    positions = [sim.positions[p] for p in sim.order]
    filled = [p for p in positions if p.fill is not None and p.fill.status == FILLED and p.status in ("OPEN", "SETTLED")]
    settled = [p for p in positions if p.status == "SETTLED"]
    ending = sim.equity
    returns = [float(p.net_pnl / p.bankroll_before) for p in settled if p.bankroll_before > 0]
    n = len(returns)
    out: dict[str, Any] = {"label": "No statistical significance is implied; figures are descriptive only.",
                           "settled_sample_size": n}
    if settled and ending > 0:
        lg = math.log(float(ending / start))
        out["log_growth"] = _f(lg)
        out["geometric_growth_per_settled_position"] = _f(math.exp(lg / len(settled)) - 1.0)
        out["geometric_growth_reason"] = None
    else:
        out["log_growth"] = out["geometric_growth_per_settled_position"] = None
        out["geometric_growth_reason"] = "NO_SETTLED_POSITIONS" if not settled else "NON_POSITIVE_ENDING_BANKROLL"
    if n >= 2:
        mean = sum(returns) / n
        out["volatility"] = _f(math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)))
        out["volatility_reason"] = None
    else:
        out["volatility"], out["volatility_reason"] = None, f"INSUFFICIENT_SAMPLES: {n} settled positions, need 2"
    level = float(cfg.cvar_level)
    if n >= cfg.cvar_min_samples:
        tail = max(1, math.ceil((1.0 - level) * n))
        worst = sorted(returns)[:tail]
        out["cvar"], out["cvar_reason"] = _f(-sum(worst) / tail), None
    else:
        out["cvar"] = None
        out["cvar_reason"] = f"INSUFFICIENT_SAMPLES: {n} settled positions, need {cfg.cvar_min_samples}"
    out["cvar_level"] = str(cfg.cvar_level)
    out["return_basis"] = "net P&L of each settled position / the policy's bankroll at its decision"
    out.update(_drawdowns(sim.curve, cfg.rolling_window))
    fees = sum((p.fee for p in filled), ZERO)
    turnover = sum((p.cost for p in filled), ZERO)
    out["fees_paid"] = _m(fees)
    out["turnover"] = _m(turnover)
    out["turnover_ratio"] = _ratio(turnover, start)
    sized = [r for r in rows if r["contracts"] > 0]
    zero = [r for r in rows if r["contracts"] == 0]
    out["zero_size_count"] = len(zero)
    out["zero_size_frequency"] = _ratio(Decimal(len(zero)), Decimal(len(rows))) if rows else None
    out["zero_size_reasons"] = _count(r["zero_size_reason"] for r in zero)
    fracs = [Decimal(r["recommended_size"]) / Decimal(r["bankroll_before"]) for r in sized
             if r.get("bankroll_before") and Decimal(r["bankroll_before"]) > 0]
    out["average_fraction"] = _ratio(sum(fracs, ZERO), Decimal(len(fracs))) if fracs else None
    out["average_fraction_basis"] = "recommended amount / bankroll at the decision, over sized decisions"
    out["verdict_counts"] = _count(r["verdict"] for r in rows)
    out["binding_counts"] = _count(r["binding_constraint"] for r in rows)
    out["secondary_constraint_counts"] = _count(c for r in rows for c in r.get("secondary_constraints") or ())
    out["fill_status_counts"] = _count(f"{r['fill_status']}:{r['fill_reason']}" for r in sized)
    out["recorded_qualification_counts"] = _count(r["recorded_qualification"] for r in rows)
    out["open_positions_at_cutoff"] = sum(1 for p in positions if p.status == "OPEN")
    out["unresolved_reservations_at_cutoff"] = sum(1 for p in positions if p.status == "RESERVED")
    out["ending_cash"] = _m(sim.cash)
    out["committed_at_cutoff"] = _m(sim.committed)

    lock_hours, dollar_hours, reserve_dollar_hours = [], ZERO, ZERO
    for p in positions:
        if p.fill is not None and p.fill.status == FILLED and p.status in ("OPEN", "SETTLED"):
            end = p.settle_known_at if p.status == "SETTLED" else cutoff
            hours = Decimal(str((end - p.reserved_at).total_seconds())) / Decimal(3600)
            lock_hours.append(hours)
            dollar_hours += p.cost * hours
        else:
            end = p.released_at or cutoff
            reserve_dollar_hours += p.cost * Decimal(str((end - p.reserved_at).total_seconds())) / Decimal(3600)
    q = Decimal("0.0001")
    lock = {"filled_dollar_hours": str(dollar_hours.quantize(q)),
            "unfilled_reservation_dollar_hours": str(reserve_dollar_hours.quantize(q)),
            "avg_lock_hours": str((sum(lock_hours, ZERO) / len(lock_hours)).quantize(q)) if lock_hours else None,
            "max_lock_hours": str(max(lock_hours).quantize(q)) if lock_hours else None,
            "open_cost_at_cutoff": _m(sim.committed),
            "basis": "from the decision (reservation) to the settlement knowledge time, or the cutoff if open"}
    return out, lock


def build_runs(inputs: ReplayInputs, policies: Sequence[tuple[str, SizingPolicyV2]] = POLICY_SET,
               *, stop_after: datetime | None = None) -> list[CounterfactualSizingRun]:
    code = code_hashes()
    base = {"schema": RUN_SCHEMA, "runner": RUNNER_ID, "runner_version": RUNNER_VERSION,
            "engine": sv2.ENGINE_ID, "engine_version": sv2.ENGINE_VERSION, "config": inputs.config.to_dict(),
            "cutoff": _iso(inputs.cutoff), "decisions": inputs.decisions_hash(), "heads": inputs.account_heads,
            "outcomes": {k: [v.outcome, _iso(v.known_at), v.source] for k, v in sorted(inputs.outcomes.items())},
            "code": code}
    runs = []
    for letter, policy in policies:
        sim, rows = _run_policy(inputs, letter, policy, stop_after)
        metrics, lock = _metrics(sim, rows, inputs.cutoff if stop_after is None else min(inputs.cutoff, stop_after))
        run_id = "cfsr-" + sv2.canonical_hash({**base, "policy": policy.to_dict(), "letter": letter})[:32]
        for r in rows:
            r["run_id"] = run_id
        filled = sum(1 for p in sim.positions.values() if p.status in ("OPEN", "SETTLED"))
        runs.append(CounterfactualSizingRun(
            schema=RUN_SCHEMA, run_id=run_id, policy_letter=letter, policy_id=policy.policy_id,
            policy_version=policy.policy_version, policy_description=policy.description,
            dataset_cutoff=_iso(inputs.cutoff), decision_count=len(rows),
            sized_count=sum(1 for r in rows if r["contracts"] > 0), fill_count=filled,
            settled_count=sum(1 for p in sim.positions.values() if p.status == "SETTLED"),
            starting_bankroll=_m(inputs.config.starting_bankroll), ending_bankroll=_m(sim.equity),
            net_pnl=_m(sim.realized), max_drawdown=metrics["max_drawdown"], turnover=metrics["turnover"],
            capital_lock=lock, veto_counts=metrics["verdict_counts"],
            cap_counts={k: v for k, v in metrics["binding_counts"].items() if k in CAP_NAMES},
            metrics=metrics, events=tuple(rows)))
    return runs


def run_counterfactual(store: Any, ledger: Any, *, cutoff: datetime | None = None,
                       config: CounterfactualConfig = DEFAULT_CONFIG,
                       policies: Sequence[tuple[str, SizingPolicyV2]] = POLICY_SET,
                       accounts: Sequence[str] | None = None) -> dict[str, Any]:
    """The full bundle: every policy's `CounterfactualSizingRun` plus provenance. Pure: reads only."""
    inputs = load_inputs(store, ledger, cutoff=cutoff, config=config, accounts=accounts)
    runs = build_runs(inputs, policies)
    return {
        "schema": BUNDLE_SCHEMA, "label": LABEL, "runner_id": RUNNER_ID, "runner_version": RUNNER_VERSION,
        "engine": {"engine_id": sv2.ENGINE_ID, "engine_version": sv2.ENGINE_VERSION},
        "dataset_cutoff": _iso(inputs.cutoff), "config": config.to_dict(),
        "provenance": {
            "code_sha256": code_hashes(), "ledger_accounts": inputs.account_heads,
            "decisions_sha256": inputs.decisions_hash(), "decision_count": len(inputs.decisions),
            "evidence_db": inputs.store is not None,
            "evidence_ids": sorted(inputs.evidence_ids | {q.evidence_id for q, _ in inputs._confirmations.values()
                                                          if q is not None and q.evidence_id}),
            "outcomes": {k: {"outcome": v.outcome, "known_utc": _iso(v.known_at), "source": v.source,
                             "detail": v.detail} for k, v in sorted(inputs.outcomes.items())},
        },
        "limitations": LIMITATIONS,
        "policies": [{"letter": letter, **p.to_dict()} for letter, p in policies],
        "runs": [r.to_dict() for r in runs],
    }


LIMITATIONS = (
    "Depth: only the recorded top of book is used; every liquidity cap is top-of-book-limited.",
    "Fills: latency-confirmed-v1 on the recorded entry quote and the captured re-check quote; a counterfactual "
    "size larger than the displayed size does not fill.",
    "Market timing is the decision's own recorded STARTER_MAX_7D_V1 verdict; decisions without one are refused "
    "(CAPITAL_HORIZON), never re-assessed at replay time.",
    "Model: each market is two states (YES, NO); other brackets of the same event are unmapped cluster exposure, "
    "which the engine treats as lost in every state (conservative). No joint bracket vector is reconstructed.",
    "Costs include the ADR 0017 claim allowance, so P&L is a conservative lower bound.",
    "No statistical significance is implied by a small number of settlements.",
)


def canonical_json(bundle: Mapping[str, Any]) -> str:
    return json.dumps(bundle, sort_keys=True, indent=1, ensure_ascii=True, default=str) + "\n"


# =========================================================================== panel (Lane B contract)


def _unavailable(verdict: str | None, block: str | None, source: str | None = None) -> str | None:
    """The panel's unavailable reason for a pre-optimizer refusal, or None for a computed result."""
    code = _code(block)
    if code is None:
        return None
    if code.startswith("MODEL_"):
        return UNAVAILABLE_NO_MODEL
    if code.startswith("FEE_"):
        return UNAVAILABLE_FEES
    if code.startswith("BOOK_") or code == "INVALID_BOOK":
        return UNAVAILABLE_STALE_QUOTE
    if code == "RULES_UNRESOLVED":
        return UNAVAILABLE_RULES
    if code.startswith("UNCERTAINTY"):
        return UNAVAILABLE_UNCERTAINTY
    if code.startswith("RISK_STATE"):
        return UNAVAILABLE_RISK_STATE
    if code.startswith(("PAYOFF_", "SIDE_", "OUTCOME_MAPPING", "HELD_POSITION")):
        return UNAVAILABLE_PAYOFF
    if code == "MARKET_NOT_OPEN":
        return UNAVAILABLE_MARKET
    if code in ("TRADABLE_CASH_RELEASE_UNKNOWN", "STARTER_VERDICT_UNBOUND", "STARTER_VERDICT_INVALID",
                "STARTER_VERDICT_LOOKAHEAD", "STARTER_VERDICT_STALE", "STARTER_VERDICT_MISMATCH"):
        return UNAVAILABLE_HORIZON
    if code in _EVIDENCE_DEFECTS or code.startswith("DECISION_"):
        return UNAVAILABLE_EVIDENCE
    if verdict in (sv2.Verdict.UNSUPPORTED.value, sv2.Verdict.STALE_DATA.value):
        return UNAVAILABLE_EVIDENCE
    return None  # RISK_LIMIT, CAPITAL_HORIZON (ineligible), NO_DEPTH ...: a computed zero


def _panel_primary(row: Mapping[str, Any], d: DecisionRecord) -> dict[str, Any]:
    caps = row.get("all_constraints") or {}
    verdict = _starter(d)
    return {
        "policy_id": row["policy_id"], "policy_version": row["policy_version"], "verdict": row["verdict"],
        "block_reason": row.get("block_reason"),
        "bankroll_basis": {"bankroll": row.get("bankroll_before"), "tradable_cash": caps.get("tradable_cash"),
                           "available_risk_budget": caps.get("available_risk_budget")},
        "model_probability": row.get("model_probability"),
        "conservative_probability": row.get("conservative_probability"),
        "expected_net_edge": row.get("expected_net_edge"), "uncertainty": row.get("probability_uncertainty"),
        "entry_price": row.get("entry_price"), "estimated_fee": row.get("estimated_fee"),
        "unconstrained_kelly_amount": row.get("unconstrained_kelly_amount"),
        "policy_amount_before_caps": row.get("unconstrained_size"),
        "caps": {"liquidity": caps.get("liquidity_cap"), "position": caps.get("position_cap"),
                 "event": caps.get("event_cap"), "cluster": caps.get("cluster_cap"),
                 "portfolio": caps.get("portfolio_cap"), "cash_horizon": caps.get("cash_horizon_cap"),
                 "drawdown": caps.get("drawdown_cap"), "maximum_allowed": caps.get("maximum_allowed_amount")},
        "capital_horizon": None if verdict is None else {
            "policy_id": verdict.policy_id, "eligible": verdict.eligible,
            "tradable_cash_release_eta_utc": verdict.tradable_cash_release_eta_utc,
            "elapsed_hours_to_tradable": verdict.elapsed_hours_to_tradable, "reasons": list(verdict.reasons)},
        "drawdown_cap": caps.get("drawdown_cap"), "final_contracts": str(row["contracts"]),
        "final_amount": row["recommended_size"], "binding_constraint": row["binding_constraint"],
        "secondary_constraints": list(row.get("secondary_constraints") or ()), "explanation": row.get("explanation"),
        "fill_status": row.get("fill_status"), "fill_reason": row.get("fill_reason"),
    }


def panel_for_market(store: Any, ledger: Any, market_id: str, *, as_of: datetime | str | None = None,
                     config: CounterfactualConfig = DEFAULT_CONFIG,
                     policies: Sequence[tuple[str, SizingPolicyV2]] = POLICY_SET) -> dict[str, Any]:
    """Per-policy research sizing for the latest recorded decision on `market_id`. Read-only.

    See the module docstring for the returned keys. Never raises for missing data: an input
    that cannot be read yields `available: false` with a named `unavailable_reason`."""
    primary_letter = PRIMARY_LETTER if any(l == PRIMARY_LETTER for l, _ in policies) else policies[0][0]
    primary_policy = dict(policies)[primary_letter]
    out: dict[str, Any] = {
        "panel_version": PANEL_VERSION, "label": PANEL_LABEL, "market_id": market_id, "as_of_utc": None,
        "available": False, "unavailable_reason": None, "unavailable_detail": None,
        "primary_policy": {"letter": primary_letter, "policy_id": primary_policy.policy_id,
                           "policy_version": primary_policy.policy_version,
                           "description": primary_policy.description},
        "sides": [], "limitations": list(LIMITATIONS),
    }
    limit = parse_utc(as_of) if as_of is not None else None
    if as_of is not None and limit is None:
        out.update(unavailable_reason=UNAVAILABLE_EVIDENCE, unavailable_detail="as_of is not a timezone-aware time")
        return out
    if ledger is None:
        out.update(unavailable_reason=UNAVAILABLE_LEDGER, unavailable_detail="no shadow ledger")
        return out
    try:
        inputs = load_inputs(store, ledger, cutoff=limit, config=config)
    except (CounterfactualInputError, LedgerError, ValueError, OSError) as exc:
        out.update(unavailable_reason=UNAVAILABLE_LEDGER, unavailable_detail=str(exc))
        return out
    mine = [d for d in inputs.decisions if d.market_id == market_id]
    if not mine:
        out.update(unavailable_reason=UNAVAILABLE_NO_DECISION,
                   unavailable_detail=f"no decision recorded for {market_id} by {_iso(inputs.cutoff)}")
        return out
    latest = max(d.as_of for d in mine)
    out["as_of_utc"] = _iso(latest)
    # The decision is sized at its own time: nothing after it can change the recommendation.
    inputs.cutoff = latest
    rows_by_policy: dict[str, dict[str, dict[str, Any]]] = {}
    wanted = {d.decision_id for d in mine if d.as_of == latest}
    for letter, policy in policies:
        _, rows = _run_policy(inputs, letter, policy, stop_after=latest)
        rows_by_policy[letter] = {r["decision_id"]: r for r in rows if r["decision_id"] in wanted}
    at_latest = sorted((d for d in mine if d.as_of == latest), key=lambda d: (d.side != "YES", d.side, d.decision_id))
    for d in at_latest:
        prow = rows_by_policy[primary_letter].get(d.decision_id)
        if prow is None:
            continue
        reason = _unavailable(prow["verdict"], prow.get("block_reason"))
        comparison = []
        for letter, policy in policies:
            r = rows_by_policy[letter].get(d.decision_id)
            if r is None:
                continue
            bank = _dec(r.get("bankroll_before"))
            comparison.append({"letter": letter, "policy_id": policy.policy_id, "policy_version": policy.policy_version,
                               "verdict": r["verdict"], "binding_constraint": r["binding_constraint"],
                               "final_contracts": str(r["contracts"]), "final_amount": r["recommended_size"],
                               "bankroll_before": r.get("bankroll_before"),
                               "fraction_of_bankroll": _ratio(_dec(r["recommended_size"]), bank)})
        out["sides"].append({
            "side": d.side, "decision_id": d.decision_id, "decision_time": d.as_of_utc,
            "recorded_qualification": d.qualification, "recorded_reason": d.reason, "model_version": d.model_version,
            "available": reason is None, "unavailable_reason": reason,
            "unavailable_detail": prow.get("block_reason") if reason else None, "top_of_book_limited": True,
            "primary": _panel_primary(prow, d), "comparison": comparison})
    if out["sides"] and all(not s["available"] for s in out["sides"]):
        first = out["sides"][0]
        out.update(unavailable_reason=first["unavailable_reason"], unavailable_detail=first["unavailable_detail"])
    else:
        out["available"] = bool(out["sides"])
    return out


# =========================================================================== CLI


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    from .shadow_ledger import ShadowLedger
    from .storage import SnapshotStore

    parser = argparse.ArgumentParser(
        prog="edge-lab sizing counterfactual",
        description="Replay every recorded shadow decision through sizing-v2 policies A-H (RESEARCH ONLY). "
                    "Inputs are opened read-only; the run is written only to --out.")
    parser.add_argument("--db", required=True, help="evidence database (opened read-only)")
    parser.add_argument("--ledger", required=True, help="shadow ledger (opened read-only)")
    parser.add_argument("--out", required=True, help="output JSON path for the derived run bundle")
    parser.add_argument("--as-of", help="dataset cutoff (ISO time with offset); default: latest known input")
    parser.add_argument("--accounts", nargs="*", help="ledger accounts to read (default: all)")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    for name, value in (("--db", args.db), ("--ledger", args.ledger)):
        if out == Path(value).resolve():
            print(f"refusing: --out is the same file as {name}", file=sys.stderr)
            return 2
    if out.is_dir():
        print("refusing: --out is a directory", file=sys.stderr)
        return 2
    cutoff = None
    if args.as_of:
        cutoff = parse_utc(args.as_of)
        if cutoff is None:
            print("--as-of must be an ISO time with a UTC offset", file=sys.stderr)
            return 2
    try:
        ledger = ShadowLedger.open_readonly(args.ledger)
        store = SnapshotStore.open_readonly(args.db)
        bundle = run_counterfactual(store, ledger, cutoff=cutoff, accounts=args.accounts)
    except (LedgerError, CounterfactualInputError, RuntimeError, OSError, ValueError) as exc:
        print(f"counterfactual run failed closed: {exc}", file=sys.stderr)
        return 1
    _write_atomic(out, canonical_json(bundle))
    summary = {"label": LABEL, "out": str(out), "dataset_cutoff": bundle["dataset_cutoff"],
               "decisions": bundle["provenance"]["decision_count"],
               "runs": [{k: r[k] for k in ("policy_letter", "policy_id", "sized_count", "fill_count", "settled_count",
                                           "ending_bankroll", "net_pnl", "max_drawdown")} for r in bundle["runs"]]}
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
