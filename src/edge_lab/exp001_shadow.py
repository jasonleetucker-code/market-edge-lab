"""EXP-001 Stage B shadow trading on the append-only ledger (Gate 6). Simulation only.

For each target date D:

- `run_day` records a decision for every opportunity the Gate 5 engine produced, whether
  it qualified or was rejected. It sizes each qualified one with the frozen 1-contract
  rule, under hard caps. It then simulates the fill with `latency-confirmed-v1`, the
  frozen execution model: entry at the decision ask, confirmed by the 10–15 min
  re-check book.
- `settle_open_positions` settles open positions on the official outcome read from captured Kalshi
  settlement evidence. A position with no evidence, or with conflicting evidence, stays
  open; it is never guessed.

Rules:

- Only a closed, VALID Stage B day can fill. `run_day` refuses a day until its re-check
  windows have closed, so an early run can never leave a stale set of decisions. On an
  INVALID day the Gate 5 engine marks every opportunity EVIDENCE_INCOMPLETE, so nothing
  qualifies. The `STAGE_B_DAY_INVALID` NO_FILL path is a second guard behind that rule.
- **One decision per (market, side, target date)**, enforced by the ledger through a
  decision `slot`. Re-running an already traded day, even under a new engine or model
  version, can never record or fill it a second time.
- Every decision and fill carries the fee verification known at its decision time
  (ADR 0017). Before the 2026-09-23 verification record that is UNVERIFIED, with
  `claimable = false`. From then on it is PARTIALLY_VERIFIED with claim basis
  CONSERVATIVE_BOUND: fees are verified and the frozen cost over-states the debit, so a
  net result is a lower bound, never an exact figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from . import exp001_stageb as stageb
from . import forward, settlement
from .fill_policy import FILLED, LATENCY_CONFIRMED_V1, simulate_fill
from .freshness import parse_utc
from .kalshi import SETTLEMENT_SOURCE
from .kalshi_quotes import quotes_from_orderbook
from .opportunity import ExecutableQuote, Opportunity
from . import risk
from .fee_schedules import verification_at
from .risk import RiskPolicy
from .shadow_ledger import LedgerError, ShadowLedger
from .sizing import SizingPolicy, suggest_position_size
from .storage import SnapshotStore

ACCOUNT_ID = "EXP-001-stage-b-shadow"
STRATEGY = "EXP-001 Stage B (frozen signal, 1 contract)"
STARTING_BANKROLL = Decimal("1000.00")  # notional shadow bankroll; no real money exists
OPENED_AT = "2026-09-22T00:00:00+00:00"

# The frozen rule is 1 contract per signal. The caps are hard limits that a 1-contract
# signal never reaches; they exist so the sizing path is identical to later strategies.
SIZING_POLICY = SizingPolicy(
    policy_id="EXP-001-fixed-1-v1", fixed_contracts=1, kelly_fraction=None,
    max_position_contracts=1, max_position_risk=Decimal("1.00"), max_event_risk=Decimal("6.00"),
    max_cluster_risk=Decimal("6.00"), max_portfolio_risk=Decimal("50.00"), reserve=Decimal("100.00"),
)


# Account-level risk limits for the notional shadow account (issue #6 foundation). They are
# set so the frozen 1-contract rule never reaches them; they are not tuned to any result.
RISK_POLICY = RiskPolicy(
    policy_id="EXP-001-shadow-risk-v1", reserve_floor=Decimal("100.00"), max_position_risk=Decimal("1.00"),
    max_event_risk=Decimal("6.00"), max_cluster_risk=Decimal("6.00"), max_portfolio_risk=Decimal("50.00"),
    daily_loss_limit=Decimal("10.00"), weekly_loss_limit=Decimal("25.00"), max_drawdown=Decimal("50.00"),
)


# The research record: exactly the frozen EXP-001 Stage B rule (DESIGN.md §6-§8): one
# contract per signalled bracket, latency-confirmed-v1 fills, no operational caps or risk
# vetoes. Its notional bankroll is large so cash never binds; if it ever does, the fill is
# recorded as NO_FILL RESEARCH_INVALID_CASH and reported, because the research record would
# then deviate from the frozen rule. This account is the only input to the EXP-001 180/365
# valid-day looks. The operational account (ACCOUNT_ID) layers sizing caps and pre-fill
# risk enforcement on the same decisions; its vetoes never touch the research record.
RESEARCH_ACCOUNT_ID = "EXP-001-stage-b-research"
RESEARCH_STRATEGY = "EXP-001 Stage B research record (frozen rule: 1 contract per signal, no operational caps)"
RESEARCH_BANKROLL = Decimal("100000.00")  # notional; large so cash never binds the frozen rule
RESEARCH_SIZING_ID = "EXP-001-frozen-1-contract-per-signal"


@dataclass(frozen=True)
class ShadowAccount:
    account_id: str
    strategy: str
    starting_bankroll: Decimal
    sizing_policy_id: str
    sizing: SizingPolicy | None  # None: the frozen 1-contract rule, no caps
    risk_policy: RiskPolicy | None  # None: no operational risk vetoes


OPERATIONAL = ShadowAccount(ACCOUNT_ID, STRATEGY, STARTING_BANKROLL, SIZING_POLICY.policy_id, SIZING_POLICY,
                            RISK_POLICY)
RESEARCH = ShadowAccount(RESEARCH_ACCOUNT_ID, RESEARCH_STRATEGY, RESEARCH_BANKROLL, RESEARCH_SIZING_ID, None, None)
ACCOUNTS = (RESEARCH, OPERATIONAL)


def fee_fields(as_of: str | datetime, market_id: str | None = None) -> dict[str, Any]:
    """The fee-verification fields carried on decisions and fills: what was known at the
    decision time `as_of` for this market (ADR 0017). Before any verification record they
    are the three legacy keys, so earlier entries are rebuilt byte-identically."""
    native = market_id.split(":", 1)[1] if market_id and ":" in market_id else market_id
    return verification_at(stageb.FEE_SCHEDULE, as_of, native).ledger_fields()


def fee_receipt(now: str | datetime) -> dict[str, Any]:
    """The fee block of the daily receipt: the verification known at `now` for the
    EXP-001 series. Fixed keys, so the receipt shape never depends on the date."""
    return verification_at(stageb.FEE_SCHEDULE, now, scope=forward.SERIES).to_dict()


FEE_FIELD_KEYS = ("fee_schedule_id", "fee_status", "claimable", "claim_basis", "fee_verification_id")


def _fill_fee_fields(fill: dict[str, Any] | None) -> dict[str, Any]:
    """A settlement carries its fill's fee fields: the fee was fixed when the fill was made."""
    return {k: fill[k] for k in FEE_FIELD_KEYS if fill is not None and k in fill}


def ensure_account(ledger: ShadowLedger, account: ShadowAccount = OPERATIONAL) -> None:
    ledger.open_account(account.account_id, starting_bankroll=account.starting_bankroll, strategy=account.strategy,
                        opened_at_utc=OPENED_AT, sizing_policy_id=account.sizing_policy_id,
                        fill_policy_id=LATENCY_CONFIRMED_V1.policy_id,
                        fee_schedule_id=stageb.FEE_SCHEDULE.schedule_id)


def risk_veto(state, cost: Decimal, opp: Opportunity, policy: RiskPolicy, as_of: datetime) -> dict[str, Any] | None:
    """Pre-fill operational risk check on the point-in-time state. None means allowed.

    Any breach, or a candidate whose worst case (its full cost) exceeds a per-position,
    per-event, per-cluster limit or the account's remaining risk capacity, is vetoed.
    Zero capacity never authorizes new risk. Exactly at a limit is allowed."""
    report = risk.assess(state, policy, as_of)
    base = {"policy_id": policy.policy_id, "as_of_utc": report.as_of_utc, "candidate_worst_case": str(cost),
            "remaining_risk_capacity": str(report.remaining_risk_capacity), "breaches": list(report.breaches)}
    if report.breaches:
        return {**base, "binding": report.breaches[0]}
    checks = (
        ("MAX_POSITION_RISK", cost, policy.max_position_risk),
        ("MAX_EVENT_RISK", state.event_exposure(opp.event_id) + cost, policy.max_event_risk),
        ("MAX_CLUSTER_RISK", state.cluster_exposure(opp.outcome_cluster) + cost, policy.max_cluster_risk),
        ("REMAINING_RISK_CAPACITY", cost, report.remaining_risk_capacity),
    )
    for name, value, limit in checks:
        if value > limit:
            return {**base, "binding": name, "value": str(value), "limit": str(limit)}
    return None


def decision_id(opportunity: Opportunity) -> str:
    return f"dec-{opportunity.opportunity_id}"


def _recheck_quotes(store: SnapshotStore, day: dict[str, Any], mode: str) -> dict[tuple[str, str], ExecutableQuote]:
    recheck_id = day.get("recheck_capture_id")
    if recheck_id is None:
        return {}
    row = next((r for r in store.forward_captures(target_date=day["target_date"], phase="recheck", mode=mode)
                if int(r["id"]) == recheck_id), None)
    if row is None:
        return {}
    books = json.loads(row["links_json"]).get("books") or {}
    snaps = store.snapshots_by_id(b["snapshot_id"] for b in books.values())
    out: dict[tuple[str, str], ExecutableQuote] = {}
    for native, info in books.items():
        snap = snaps.get(info["snapshot_id"])
        if (snap is None or snap["entity_id"] != native or snap["kind"] != "orderbook"
                or snap["run_id"] != row["run_id"]):
            continue
        for side, q in quotes_from_orderbook(native, json.loads(snap["payload_json"]),
                                              received_at_utc=snap["fetched_at_utc"],
                                              evidence_id=f"snapshot:{snap['id']}").items():
            out[(q.market_id, side)] = q
    return out


def slot(opportunity: Opportunity, target: date) -> str:
    return f"{target.isoformat()}|{opportunity.market_id}|{opportunity.side}"


def run_day(store: SnapshotStore, ledger: ShadowLedger, target: date, *, model=None, mode: str = "live",
            now: datetime | None = None, accounts: tuple[ShadowAccount, ...] = ACCOUNTS) -> dict[str, Any]:
    """Record decisions and simulated fills for D in every account. Safe to re-run: every
    append is idempotent, and a crash between a decision and its fill is completed by the
    re-run from point-in-time state.

    The top-level counters are the operational account's (backward compatible); per-account
    summaries are under "accounts"."""
    now = now or datetime.now(timezone.utc)
    if target > forward.last_closed_target(now):
        empty = {"decisions": 0, "qualified": 0, "filled": 0, "no_fill": {}}
        return {"target_date": target.isoformat(), "stage_b_day_status": "NOT_CLOSED", **empty,
                "accounts": {}, "problems": [f"target {target.isoformat()} is not closed at {now.isoformat()}; "
                                             "nothing recorded"]}
    evaluation = stageb.evaluate_day(store, target, model=model, mode=mode)
    day = evaluation.day_status
    valid = day["status"] == "VALID"
    confirmations = _recheck_quotes(store, day, mode) if valid else {}
    entry_quotes = _decision_quotes(store, evaluation, mode)
    expected_settlement = (forward.windows(target)["decision"] + timedelta(days=2)).isoformat()
    summary: dict[str, Any] = {"target_date": target.isoformat(), "stage_b_day_status": day["status"],
                               "problems": list(evaluation.problems), "accounts": {}}
    for account in accounts:
        ensure_account(ledger, account)
        summary["accounts"][account.account_id] = _run_account(
            ledger, account, evaluation.opportunities, target, day["status"], valid, entry_quotes, confirmations,
            expected_settlement, summary["problems"])
    main = summary["accounts"].get(ACCOUNT_ID) or next(iter(summary["accounts"].values()))
    summary.update({k: main[k] for k in ("decisions", "qualified", "filled", "no_fill")})
    return summary


def _run_account(ledger: ShadowLedger, account: ShadowAccount, opportunities, target: date, day_status: str,
                 valid: bool, entry_quotes, confirmations, expected_settlement: str,
                 problems: list[str]) -> dict[str, Any]:
    """Two passes: every decision first (sized as of the decision time), then the fills in
    confirmation-time order, so each fill's point-in-time state already contains every
    earlier fill of the day (exposure and cash) and nothing learned later."""
    acct = account.account_id
    out: dict[str, Any] = {"decisions": 0, "qualified": 0, "filled": 0, "no_fill": {}, "vetoes": []}
    taken = ledger.state(acct).decision_slots
    decided: list[tuple[Opportunity, dict[str, Any]]] = []
    for opp in opportunities:
        did = decision_id(opp)
        existing = ledger.find(acct, "decision", did)
        if existing is None and taken.get(slot(opp, target)) not in (None, did):
            problems.append(f"{acct}: {slot(opp, target)} already decided by {taken[slot(opp, target)]}; skipped")
            continue
        if existing is None:
            # Sized against the account as it could be known at the decision time; a re-run
            # finds the decision already recorded and reuses its size.
            sizing = None
            if opp.qualification == "QUALIFY":
                if account.sizing is None:
                    sizing = {"policy_id": account.sizing_policy_id, "final_size": 1,
                              "binding_constraint": "FROZEN_RULE_ONE_CONTRACT"}
                else:
                    state = ledger.state_as_of(acct, parse_utc(opp.as_of_utc))
                    sizing = suggest_position_size(
                        bankroll=state.equity, conservative_probability=opp.conservative_probability,
                        executable_price=opp.executable_price, fees=stageb.FEE_SCHEDULE,
                        available_size=opp.displayed_size, event_exposure=state.event_exposure(opp.event_id),
                        cluster_exposure=state.cluster_exposure(opp.outcome_cluster),
                        total_open_risk=state.open_worst_case_risk, policy=account.sizing,
                    ).to_dict()
            existing = {
                "decision_id": did, "slot": slot(opp, target), "opportunity_id": opp.opportunity_id,
                "as_of_utc": opp.as_of_utc,
                "qualification": opp.qualification, "reason": opp.rejection_reason, "reasons": list(opp.reasons),
                "model_version": opp.model_version,
                "quote_evidence_ids": [opp.quote_evidence_id] if opp.quote_evidence_id else [],
                "event_id": opp.event_id, "market_id": opp.market_id, "side": opp.side,
                "outcome_cluster": opp.outcome_cluster, "policy_id": opp.policy_id,
                "opportunity": opp.to_dict(), "sizing": sizing,
                "stage_b_day_status": day_status, "opportunity_claimable": opp.claimable, **fee_fields(opp.as_of_utc, opp.market_id),
            }
            ledger.record_decision(acct, existing)
        out["decisions"] += 1
        if opp.qualification == "QUALIFY":
            out["qualified"] += 1
            decided.append((opp, existing))

    pending: list[tuple[Opportunity, dict[str, Any]]] = []
    for opp, decision in decided:
        fill = ledger.find(acct, "fill", decision_id(opp))
        if fill is None:
            quantity = int((decision.get("sizing") or {}).get("final_size") or 0)
            fill = _fill_payload(opp, quantity, valid, entry_quotes, confirmations, expected_settlement)
            pending.append((opp, fill))
        else:
            _count(out, fill)
    # NO_FILLs first (they move no cash), then FILLED in confirmation-time order.
    pending.sort(key=lambda item: (item[1]["status"] == FILLED, item[1]["filled_at_utc"], item[1]["fill_id"]))
    for opp, fill in pending:
        if fill["status"] == FILLED:
            known_at = parse_utc(fill["filled_at_utc"])
            state = ledger.state_as_of(acct, known_at)
            cost = Decimal(fill["total_cost"])
            veto = risk_veto(state, cost, opp, account.risk_policy, known_at) if account.risk_policy else None
            if veto is not None:
                fill.update(status="NO_FILL", reason="RISK_VETO", quantity=0, price=None, total_cost=None,
                            fee=None, risk_veto=veto,
                            detail=f"operational risk veto: {veto['binding']} (candidate worst case {cost})")
            elif cost > state.settled_cash:
                reason = "INSUFFICIENT_CASH" if account.risk_policy else "RESEARCH_INVALID_CASH"
                fill.update(status="NO_FILL", reason=reason, quantity=0, price=None, total_cost=None, fee=None,
                            detail="cash known at the fill time is below the fill's cost")
                if account.risk_policy is None:
                    problems.append(f"{acct}: research record deviates from the frozen rule on "
                                    f"{fill['decision_id']} (notional cash exhausted)")
        ledger.record_fill(acct, fill)
        _count(out, fill)
    return out


def _count(out: dict[str, Any], fill: dict[str, Any]) -> None:
    if fill["status"] == FILLED:
        out["filled"] += 1
        return
    out["no_fill"][fill["reason"]] = out["no_fill"].get(fill["reason"], 0) + 1
    if fill.get("risk_veto"):
        out["vetoes"].append({"decision_id": fill["decision_id"], **fill["risk_veto"]})


def _decision_quotes(store: SnapshotStore, evaluation, mode: str) -> dict[tuple[str, str], ExecutableQuote]:
    """The quotes the engine priced, rebuilt from the same snapshots (by evidence id)."""
    ids = {o.quote_evidence_id for o in evaluation.opportunities if o.quote_evidence_id}
    snaps = store.snapshots_by_id(int(i.split(":", 1)[1]) for i in ids)
    out: dict[tuple[str, str], ExecutableQuote] = {}
    for snap in snaps.values():
        for side, q in quotes_from_orderbook(snap["entity_id"], json.loads(snap["payload_json"]),
                                              received_at_utc=snap["fetched_at_utc"],
                                              evidence_id=f"snapshot:{snap['id']}").items():
            out[(q.market_id, side)] = q
    return out


def _fill_payload(opp: Opportunity, quantity: int, valid: bool, entries, confirmations, expected_settlement: str) -> dict[str, Any]:
    base = {
        "fill_id": f"fill-{opp.opportunity_id}", "decision_id": decision_id(opp), "venue": "kalshi",
        "market_id": opp.market_id, "event_id": opp.event_id, "outcome_cluster": opp.outcome_cluster,
        "side": opp.side, "filled_at_utc": opp.as_of_utc, "decision_as_of_utc": opp.as_of_utc,
        "fill_policy_id": LATENCY_CONFIRMED_V1.policy_id,
        "latency": {"confirm_min_s": LATENCY_CONFIRMED_V1.confirm_min.total_seconds(),
                    "confirm_max_s": LATENCY_CONFIRMED_V1.confirm_max.total_seconds()},
        "expected_settlement_utc": expected_settlement, **fee_fields(opp.as_of_utc, opp.market_id),
    }
    if not valid:
        return {**base, "status": "NO_FILL", "reason": "STAGE_B_DAY_INVALID", "quantity": 0, "price": None,
                "fee": None, "total_cost": None, "entry_evidence_id": opp.quote_evidence_id,
                "confirmation_evidence_id": None, "detail": "the Stage B day is INVALID: excluded, never traded"}
    result = simulate_fill(quantity=quantity, entry=entries.get((opp.market_id, opp.side)),
                           confirmation=confirmations.get((opp.market_id, opp.side)),
                           as_of=parse_utc(opp.as_of_utc))
    if result.status != FILLED:
        return {**base, "status": "NO_FILL", "reason": result.reason, "quantity": 0, "price": None, "fee": None,
                "total_cost": None, "entry_evidence_id": result.entry_evidence_id,
                "confirmation_evidence_id": result.confirmation_evidence_id, "detail": result.detail}
    cost = stageb.FEE_SCHEDULE.taker_buy(result.quantity, result.price)
    # The fill is known only once the re-check confirms it: stamp it at the confirmation
    # book's receipt time (the decision time stays in decision_as_of_utc).
    confirmed = confirmations.get((opp.market_id, opp.side))
    confirmed_at = getattr(confirmed, "received_at_utc", None) or opp.as_of_utc
    return {**base, "filled_at_utc": confirmed_at, "status": "FILLED", "reason": "FILLED", "quantity": result.quantity, "price": str(result.price),
            "fee": str(cost.fee), "total_cost": str(cost.total_cost), "entry_evidence_id": result.entry_evidence_id,
            "confirmation_evidence_id": result.confirmation_evidence_id, "detail": result.detail}


# --------------------------------------------------------------------------- settlement


SETTLEMENT_KINDS = ("settled_markets", "historical_markets", "event_settlement_markets")


def settlement_index(store: SnapshotStore, *, known_by: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Latest captured settlement record per market ticker, built once.

    Only snapshots received at or before `known_by` count (catch-up never uses evidence
    that did not exist yet). Each entry: {"market", "snapshot_id", "evidence_available_utc"}."""
    index: dict[str, dict[str, Any]] = {}
    for kind in SETTLEMENT_KINDS:
        for row in store.snapshots_of_kind(source=SETTLEMENT_SOURCE.legacy_name, kind=kind):
            fetched = parse_utc(row["fetched_at_utc"])
            if known_by is not None and (fetched is None or fetched > known_by):
                continue
            for market in json.loads(row["payload_json"]).get("markets") or []:
                if not isinstance(market, dict) or not isinstance(market.get("ticker"), str):
                    continue
                current = index.get(market["ticker"])
                # Compare parsed values ("67" and "67.00" are the same outcome, not a conflict).
                parsed = settlement.parse_value(market.get("expiration_value"))
                variant = (market.get("result"), str(parsed.normalize()) if parsed is not None else None)
                variants = (current or {}).get("variants", set())
                if variant[0] in ("yes", "no"):
                    variants = variants | {variant}
                if current is None or int(row["id"]) > current["snapshot_id"]:
                    index[market["ticker"]] = {"market": market, "snapshot_id": int(row["id"]),
                                               "evidence_available_utc": row["fetched_at_utc"], "variants": variants}
                else:
                    current["variants"] = variants
    return index


def settled_market(store: SnapshotStore, native_id: str) -> tuple[dict[str, Any] | None, int | None]:
    """The most recently captured settlement record for `native_id`, with its snapshot id."""
    found = settlement_index(store).get(native_id)
    return (found["market"], found["snapshot_id"]) if found else (None, None)


def official_outcome(market: dict[str, Any]) -> tuple[str | None, str]:
    """YES/NO when Kalshi's recorded result and the frozen resolver agree on expiration_value."""
    value = settlement.parse_value(market.get("expiration_value"))
    resolved = settlement.resolve(market, value)
    recorded = settlement.kalshi_result(market)
    if resolved.outcome is settlement.Outcome.UNKNOWN:
        return None, f"resolver: {resolved.reason}"
    if recorded is settlement.Outcome.UNKNOWN:
        return None, f"Kalshi result {market.get('result')!r} is not yes/no"
    if resolved.outcome is not recorded:
        return None, f"resolver says {resolved.outcome.value}, Kalshi recorded {recorded.value}"
    return resolved.outcome.value.upper(), resolved.reason


def settle_open_positions(store: SnapshotStore, ledger: ShadowLedger, *, accounts: tuple[ShadowAccount, ...] = ACCOUNTS,
                          known_by: datetime | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Settle every open position that has conclusive settlement evidence; report the rest.

    `known_by` limits the evidence to what had been received by then (used by catch-up so a
    settlement learned later never funds an earlier fill). Missing, unsettled or conflicting
    evidence leaves the position open and listed as pending, never guessed."""
    # Evidence counts only once received: by `known_by` in catch-up, else by `now` if given.
    index = settlement_index(store, known_by=known_by if known_by is not None else now)
    report: dict[str, Any] = {"settled": [], "pending": [], "conflicts": []}
    for account in accounts:
        ensure_account(ledger, account)
        acct = account.account_id
        state = ledger.state(acct)
        # Already-settled positions: a later capture that contradicts the recorded outcome is
        # reported (never silently rewritten; a rebuild would book different P&L).
        for position in state.positions:
            if position.status != "SETTLED":
                continue
            found = index.get(position.market_id.split(":", 1)[1])
            if found is None:
                continue
            latest, _ = official_outcome(found["market"])
            if len(found["variants"]) > 1 or (latest is not None and latest != position.outcome):
                report["conflicts"].append({"account_id": acct, "position_id": position.position_id,
                                            "recorded_outcome": position.outcome, "latest_evidence_outcome": latest,
                                            "variants": sorted(map(list, found["variants"]))})
        for position in state.open_positions():
            native = position.market_id.split(":", 1)[1]
            found = index.get(native)
            if found is None:
                report["pending"].append({"account_id": acct, "position_id": position.position_id,
                                          "reason": "no settlement evidence yet"})
                continue
            if len(found["variants"]) > 1:
                why = f"conflicting settlement evidence across captures: {sorted(map(list, found['variants']))}"
                report["pending"].append({"account_id": acct, "position_id": position.position_id, "reason": why})
                report["conflicts"].append({"account_id": acct, "position_id": position.position_id,
                                            "recorded_outcome": None, "latest_evidence_outcome": None,
                                            "variants": sorted(map(list, found["variants"]))})
                continue
            market = found["market"]
            outcome, why = official_outcome(market)
            if outcome is None:
                report["pending"].append({"account_id": acct, "position_id": position.position_id, "reason": why})
                continue
            settled_at = market.get("settlement_ts") or market.get("expiration_time") or market.get("close_time")
            if not settled_at:
                report["pending"].append({"account_id": acct, "position_id": position.position_id,
                                          "reason": "settlement time missing"})
                continue
            evidence = {"snapshot_id": found["snapshot_id"], "expiration_value": market.get("expiration_value"),
                        "kalshi_result": market.get("result"), "resolver": why,
                        "evidence_available_utc": found["evidence_available_utc"],
                        "reported_settlement_time": str(settled_at)}
            # Processing time is the ledger's appended_at_utc (outside the hash), so replays of
            # the same evidence stay byte-identical.
            # A settlement cannot have happened after we received it as settled. The field used
            # (settlement_ts, else the scheduled expiration/close time) can be later, so the
            # effective time is clamped to the evidence receipt; the reported value is kept.
            reported, received = parse_utc(str(settled_at)), parse_utc(found["evidence_available_utc"])
            if reported is None or (received is not None and reported > received):
                settled_at = found["evidence_available_utc"]
                evidence["settlement_time_clamped_to_evidence"] = True
            try:
                fee = _fill_fee_fields(ledger.find(acct, "fill", position.decision_id))
                ledger.record_settlement(acct, fill_id=position.position_id, outcome=outcome,
                                         settled_at_utc=str(settled_at), evidence=evidence, fee=fee)
            except LedgerError as exc:
                report["pending"].append({"account_id": acct, "position_id": position.position_id,
                                          "reason": str(exc)})
                continue
            report["settled"].append({"account_id": acct, "position_id": position.position_id, "outcome": outcome})
    return report
