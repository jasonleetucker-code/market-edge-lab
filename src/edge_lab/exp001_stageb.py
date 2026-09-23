"""EXP-001 adapter for the opportunity engine: forward evidence → opportunities (Gate 5).

This plugs the frozen EXP-001 model and the forward Stage-B captures into the
domain-neutral contracts in `edge_lab.opportunity`.

- **Model:** the variant Stage A selected (`gate4/stage_a_result.json`), refit on all
  usable days through 2026-09-21. This is the spec's "refit once on all usable days
  through 2026-09-21 for Stage B". The refit is a pure function of the committed,
  hash-pinned dataset, so every call gives the same pmf.
- **Bracket probability** (spec): the pmf summed over the integers that
  `settlement.resolve` maps to YES, for f = the PFMOKX forecast the frozen availability
  rule selects.
- **Policy** `EXP-001-stage-b-frozen-v1` (spec):
  - buy 1 YES if p − cost_yes ≥ 0.05; buy 1 NO if (1 − p) − cost_no ≥ 0.05;
  - cost = fees.cost_per_contract(1, ask);
  - books at most 5 minutes old at the decision;
  - the forecast issued at most 24 h before the cutoff, which is at most 24.5 h before
    the decision.
  The edge basis is the point probability, because that is the frozen rule. The
  conservative probability is computed and reported for every opportunity.
- **Fees** are flagged, not required: the schedule is UNVERIFIED_CURRENT_SCHEDULE, so
  opportunities evaluate but carry `claimable = False`.

Only stored evidence is used; nothing here fetches, and nothing trades. Historical
executable prices do not exist for EXP-001, and none is manufactured: this adapter reads
forward captures only.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import exp001_baseline as base
from . import forward, settlement
from .conservative import wilson_bounds
from .fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from .kalshi_quotes import check_event_identity, market_from_kalshi, quotes_from_orderbook
from .opportunity import (
    Event, ExecutableQuote, Market, ModelEstimate, Opportunity, Policy, evaluate_event, reason_counts,
)
from .storage import SnapshotStore

ADAPTER_VERSION = "1"
EXP_DIR = Path(__file__).resolve().parents[2] / "experiments" / "EXP-001-kxhighny-nws-vs-market"
DATASET = EXP_DIR / "gate3" / "dataset.csv"
GATE4 = EXP_DIR / "gate4"
STAGE_B_FIT_THROUGH = "2026-09-21"

STAGE_B_POLICY = Policy(
    policy_id="EXP-001-stage-b-frozen-v1",
    edge_basis="point",
    min_net_edge=Decimal("0.05"),
    quantity=1,
    max_book_age=forward.DECISION_WINDOW,  # 5 minutes
    max_model_input_age=timedelta(hours=24, minutes=30),  # 24 h at the cutoff = 24.5 h at the decision
    fee_verification="flag",
)
FEE_SCHEDULE = KALSHI_QUADRATIC_TAKER_V1


class StageBUnavailable(RuntimeError):
    """Stage B may not run: Stage A did not pass or its record is missing."""


@dataclass(frozen=True)
class StageBModel:
    variant: str
    pmfs: dict[str, tuple[float, ...]]
    n_fit: int
    dataset_sha256: str
    version: str

    @property
    def model_id(self) -> str:
        return f"{base.EXPERIMENT_ID}/{self.variant}"

    def pmf_for(self, target: date) -> tuple[float, ...]:
        return self.pmfs["ALL" if self.variant == "V1" else base.SEASONS[target.month]]


@lru_cache(maxsize=4)
def load_model(dataset: Path = DATASET, gate4_dir: Path = GATE4) -> StageBModel:
    stage_a_path = Path(gate4_dir) / base.STAGE_A_FILE
    if not stage_a_path.exists():
        raise StageBUnavailable(f"{stage_a_path} missing: Stage B requires a committed Stage A result")
    stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    if stage_a.get("verdict") != "PASS":
        raise StageBUnavailable(f"Stage A verdict is {stage_a.get('verdict')!r}; Stage B is not run for this model")
    variant = stage_a["selected_variant"]
    text = base.dataset_text(dataset)
    sha = base.dataset_sha256(text)
    if sha != stage_a.get("dataset_sha256"):
        raise StageBUnavailable("dataset hash differs from the one Stage A was computed on")
    days = base.load_fit_window(dataset, base.FIT_SPLITS) + base.load_test_for_reproduction(dataset, gate4_dir)
    days = sorted((d for d in days if d.target_date <= STAGE_B_FIT_THROUGH), key=lambda d: d.target_date)
    fitted = base.fit_model(variant, days)
    return StageBModel(
        variant=variant, pmfs=fitted.pmfs, n_fit=len(days), dataset_sha256=sha,
        version=f"{base.EXPERIMENT_ID}/{variant}/fit<={STAGE_B_FIT_THROUGH}/n={len(days)}"
                f"/dataset:{sha[:16]}/adapter:v{ADAPTER_VERSION}",
    )


def bracket_probability(model: StageBModel, raw_market: dict[str, Any], forecast_f: int,
                        target: date) -> tuple[float | None, str | None]:
    """P(YES) = sum of pmf[k] over k in [-20, 20] where resolve(market, f + k) is YES."""
    pmf = model.pmf_for(target)
    hits: list[float] = []
    for i, k in enumerate(range(base.K_MIN, base.K_MAX + 1)):
        resolution = settlement.resolve(raw_market, forecast_f + k)
        if resolution.outcome is settlement.Outcome.UNKNOWN:
            return None, f"resolver cannot map {forecast_f + k}: {resolution.reason}"
        if resolution.outcome is settlement.Outcome.YES:
            hits.append(pmf[i])
    return min(1.0, max(0.0, math.fsum(hits))), None


def event_for(target: date) -> Event:
    decision = forward.windows(target)["decision"]
    return Event(
        domain="weather",
        event_id=f"weather:us-nyc-central-park:daily-max-temp-f:{target.isoformat()}",
        target_date=target.isoformat(),
        target_time_utc=None,  # determined from the next-day climate report
        outcome_cluster=f"weather:us-nyc-central-park:{target.isoformat()}",
        settlement_identity=(
            f"Kalshi {forward.SERIES} {forward.event_ticker_for(target)}: CLINYC (Central Park) daily "
            f"maximum temperature °F per the captured rules; decision {decision.isoformat()}"
        ),
    )


@dataclass(frozen=True)
class DayEvaluation:
    target_date: str
    as_of_utc: str
    day_status: dict[str, Any]
    event: Event
    forecast: dict[str, Any] | None
    model: dict[str, Any] | None
    opportunities: list[Opportunity]
    problems: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "as_of_utc": self.as_of_utc,
            "stage_b_day_status": self.day_status["status"],
            "stage_b_day_reasons": self.day_status["reasons"],
            "event": {k: v for k, v in self.event.__dict__.items()},
            "forecast": self.forecast,
            "model": self.model,
            "policy": {
                "policy_id": STAGE_B_POLICY.policy_id, "edge_basis": STAGE_B_POLICY.edge_basis,
                "min_net_edge": str(STAGE_B_POLICY.min_net_edge), "quantity": STAGE_B_POLICY.quantity,
                "max_book_age_s": STAGE_B_POLICY.max_book_age.total_seconds(),
                "max_model_input_age_s": STAGE_B_POLICY.max_model_input_age.total_seconds(),
                "fee_verification": STAGE_B_POLICY.fee_verification,
            },
            "fee_schedule": {"schedule_id": FEE_SCHEDULE.schedule_id, "status": FEE_SCHEDULE.status.value,
                             "evidence": FEE_SCHEDULE.evidence},
            "problems": self.problems,
            "counts": {
                "opportunities": len(self.opportunities),
                "qualified": sum(o.qualification == "QUALIFY" for o in self.opportunities),
                "by_reason": reason_counts(self.opportunities),
            },
            "opportunities": [o.to_dict() for o in self.opportunities],
        }


def evaluate_day(store: SnapshotStore, target: date, *, model: StageBModel | None = None,
                 mode: str = "live") -> DayEvaluation:
    """All opportunities for target date D from its decision capture, as of 18:00 ET on D−1.

    If there is no complete decision capture, no market list exists to enumerate, and the
    result has no opportunities. That is recorded in `problems`, never papered over.
    """
    event = event_for(target)
    w = forward.windows(target)
    as_of = w["decision"]
    status = forward.day_status(store, target, mode=mode)
    problems: list[str] = []
    ticker = forward.event_ticker_for(target)

    try:
        model = model or load_model()
    except StageBUnavailable as exc:
        model = None
        problems.append(f"model: {exc}")

    forecast, why = forward.select_pfm(store, target)
    if forecast is None:
        problems.append(f"forecast: {why}")

    decision = _decision_capture(store, target, status.get("decision_capture_id"), mode, problems)
    if decision is None:
        return DayEvaluation(target.isoformat(), as_of.isoformat(), status, event, forecast,
                             None if model is None else _model_info(model), [], problems)
    links = json.loads(decision["links_json"])
    books = links.get("books") or {}
    ids = [links.get("event_snapshot"), *links.get("market_snapshots", []), *(b["snapshot_id"] for b in books.values())]
    # Only snapshots written by the capture's own run count as its evidence.
    snaps = {sid: s for sid, s in store.snapshots_by_id(i for i in ids if i is not None).items()
             if s["run_id"] == decision["run_id"]}

    event_ok = True
    raw_event = snaps.get(links.get("event_snapshot"))
    identity = check_event_identity(event, None if raw_event is None else json.loads(raw_event["payload_json"]), ticker)
    if identity:
        problems.append(f"event: {identity}")
        event_ok = False
    # Only the expected Kalshi event maps to this normalized event; anything else mismatches.
    mapping = {ticker: event.event_id} if event_ok else {}

    raw_markets: list[dict[str, Any]] = []
    for sid in links.get("market_snapshots", []):
        snap = snaps.get(sid)
        if snap is None:
            problems.append(f"market snapshot {sid} missing")
            continue
        raw_markets.extend(m for m in json.loads(snap["payload_json"]).get("markets") or [] if isinstance(m, dict))

    markets: list[Market] = []
    quotes: dict[tuple[str, str], ExecutableQuote] = {}
    estimates: dict[str, ModelEstimate] = {}
    for raw in sorted(raw_markets, key=lambda m: str(m.get("ticker"))):
        market = market_from_kalshi(raw, event_id_for_ticker=mapping)
        markets.append(market)
        native = market.native_id
        info = books.get(native)
        snap = snaps.get(info["snapshot_id"]) if info else None
        if snap is not None and snap["entity_id"] == native and snap["kind"] == "orderbook":
            for side, quote in quotes_from_orderbook(
                native, json.loads(snap["payload_json"]), received_at_utc=snap["fetched_at_utc"],
                evidence_id=f"snapshot:{snap['id']}",
            ).items():
                quotes[(market.market_id, side)] = quote
        estimates[market.market_id] = _estimate(model, raw, market, event, forecast, why, target, as_of.isoformat())

    opportunities = evaluate_event(event=event, markets=markets, quotes=quotes, estimates=estimates,
                                   fee_schedule=FEE_SCHEDULE, policy=STAGE_B_POLICY, as_of=as_of)
    return DayEvaluation(target.isoformat(), as_of.isoformat(), status, event, forecast,
                         None if model is None else _model_info(model), opportunities, problems)


def _decision_capture(store: SnapshotStore, target: date, complete_id: int | None, mode: str,
                      problems: list[str]):
    """The complete decision capture the day validator chose; else the latest partial one.

    A partial capture never makes a Stage B day VALID (the validator decides that). Its
    brackets are still evaluated, because rejected opportunities are research evidence too.
    """
    rows = store.forward_captures(target_date=target.isoformat(), phase="decision", mode=mode)
    if complete_id is not None:
        return next(r for r in rows if int(r["id"]) == complete_id)
    partial = [r for r in rows if r["status"] == "partial"
               and json.loads(r["links_json"]).get("market_snapshots")]
    if not partial:
        problems.append("no complete decision capture: no market list to evaluate")
        return None
    chosen = partial[-1]
    problems.append(f"no complete decision capture; evaluating partial capture {chosen['id']} for research "
                    "only (the Stage B day is INVALID)")
    return chosen


def _model_info(model: StageBModel) -> dict[str, Any]:
    return {"model_id": model.model_id, "version": model.version, "n_fit": model.n_fit,
            "dataset_sha256": model.dataset_sha256}


def _estimate(model: StageBModel | None, raw: dict[str, Any], market: Market, event: Event,
              forecast: dict[str, Any] | None, forecast_why: str | None, target: date, as_of: str) -> ModelEstimate:
    common = dict(
        model_id=f"{base.EXPERIMENT_ID}/{model.variant}" if model else f"{base.EXPERIMENT_ID}/unavailable",
        version=model.version if model else "unavailable", event_id=event.event_id, market_id=market.market_id,
        generated_at_utc=as_of,
        input_version=forecast["product_sha256"] if forecast else "none",
        input_observed_at_utc=forecast["issued_utc"] if forecast else None,
    )
    if model is None:
        return ModelEstimate(probability=None, bounds=None, unavailable_reason="Stage B model unavailable", **common)
    if forecast is None:
        return ModelEstimate(probability=None, bounds=None, unavailable_reason=f"no forecast: {forecast_why}",
                             unavailable_because_stale=forecast_why == "PFM_STALE_AT_CUTOFF", **common)
    p, why = bracket_probability(model, raw, int(forecast["forecast_max_f"]), target)
    if p is None:
        return ModelEstimate(probability=None, bounds=None, unavailable_reason=why, **common)
    return ModelEstimate(probability=p, bounds=wilson_bounds(p, model.n_fit), **common)

