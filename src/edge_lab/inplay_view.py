"""The in-play research view contract `inplay-view/1` (#122 §21B). Pure; no network, no writes.

It composes one read-only view from the canonical in-play modules:
- `inplay_evidence`: book reconstruction, coverage and failures;
- `position_policy`: the HOLD / REDUCE / EXIT proposal;
- `inplay_replay`: the hold-versus-exit comparison.

The Terminal only formats this dict and computes nothing. Every figure is a string (a Decimal) or
None (unknown, never 0).

Honesty rules the view enforces:
- **Never LIVE.** `mode` is FIXTURE, SYNTHETIC_REPLAY or NOT_AUTHORIZED. No in-play source is
  authorized, so the production dashboard shows NOT_AUTHORIZED with the proposed pilot's status.
- **No balances, no edge score, no trade action.** Inventory is labelled SIMULATED. Replay P&L is
  labelled synthetic or fixture. Exit proceeds are an estimate at displayed depth, "not a fill".
- **Fees.** An unknown fee leaves every after-cost figure None. Diagnostics (oracles) are separate.
- **Time.** `as_of_utc` is the replay clock (the fixture's time), not the time the page renders.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from . import inplay_evidence as ev
from . import inplay_replay as rp
from . import position_policy as pp
from .freshness import parse_utc
from .opportunity import DepthStatus

VIEW_SCHEMA = "inplay-view/1"
LABEL = "IN-PLAY RESEARCH · NOT LIVE · NOT AN EDGE CLAIM"
PILOT_STATUS = ("Source-quality pilot inplay-source-pilot-1 is PROPOSED, NOT APPROVED "
                "(docs/research/INPLAY_SOURCE_FEASIBILITY.md §6).")
AUTHORITY = ("Offline only: no in-play stream, polling, credential, account read or order is authorized "
             "(owner directive 2026-09-28). EXECUTION_NOT_AUTHORIZED stays enforced.")


class ViewState(str, Enum):
    POPULATED = "POPULATED"
    EMPTY = "EMPTY"  # the journal loaded and holds nothing for this market
    STALE = "STALE"  # the newest book is older than the policy's maximum age at the replay clock
    PARTIAL = "PARTIAL"  # book awaiting resync, gaps or failures in the window, or incomplete entries
    UNSUPPORTED = "UNSUPPORTED"  # the policy is not defensible (fair value, re-entry, add)
    PAUSED = "PAUSED"  # a trading or exchange pause
    ERROR = "ERROR"  # the evidence could not be read
    NOT_AUTHORIZED = "NOT_AUTHORIZED"  # no in-play source is authorized


class Mode(str, Enum):
    FIXTURE = "FIXTURE"
    SYNTHETIC_REPLAY = "SYNTHETIC_REPLAY"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _base(state: ViewState, mode: Mode, as_of: str | None, detail: str) -> dict[str, Any]:
    return {"schema": VIEW_SCHEMA, "state": state.value, "mode": mode.value, "label": LABEL, "as_of_utc": as_of,
            "detail": detail, "authority": AUTHORITY, "pilot": PILOT_STATUS, "contract": None, "source": None,
            "inventory": None, "policy": None, "exit_estimate": None, "comparison": None, "diagnostics": [],
            "assumptions": [], "after_cost_claim": False, "after_cost_reason": "no replay evaluated",
            "blocker": None}


def not_authorized_view() -> dict[str, Any]:
    """What production shows today: no source, nothing replayed, the proposal's status."""
    out = _base(ViewState.NOT_AUTHORIZED, Mode.NOT_AUTHORIZED, None,
                "No in-play evidence exists: capture has not been approved. The offline foundation (evidence "
                "contract, position policy, replay) is available for fixtures and synthetic cohorts only.")
    out["blocker"] = ("Owner approval of the source-quality pilot, a decision on the Kalshi data-rights question, "
                      "a reviewed recorder, and a research slot with an experiment id from the registry.")
    return out


def error_view(detail: str, *, mode: Mode = Mode.FIXTURE) -> dict[str, Any]:
    out = _base(ViewState.ERROR, mode, None, detail)
    out["blocker"] = "The in-play evidence could not be read; nothing is shown as current."
    return out


def _source(state: ev.BookState, transitions: Sequence[ev.Transition], failures: Sequence[ev.SourceFailure],
            parse_failures: int, *, as_of: datetime, window_start: datetime, max_book_age: timedelta,
            trading: ev.TradingState) -> dict[str, Any]:
    last = parse_utc(state.last_applied_receipt_utc)
    age = None if last is None else (as_of - last).total_seconds()
    cov = ev.coverage_report(state.market_ticker, transitions, window_start=window_start,
                             window_end=max(as_of, window_start + timedelta(seconds=1)),
                             max_silence=max_book_age, failures=failures, parse_failures=parse_failures)
    return {"route": "FILE_JOURNAL", "book_status": state.status.value, "trading_state": trading.value,
            "last_receipt_utc": state.last_applied_receipt_utc, "last_source_ts_utc": state.last_source_ts_utc,
            "age_seconds": _s(None if age is None else Decimal(str(age))),
            "max_age_seconds": _s(Decimal(str(max_book_age.total_seconds()))),
            "fresh": age is not None and 0 <= age <= max_book_age.total_seconds(),
            "coverage_fraction": _s(cov.coverage_fraction), "usable_seconds": _s(cov.usable_seconds),
            "unusable": [{"reason": r, "seconds": _s(s)} for r, s in cov.unusable_seconds_by_reason],
            "gaps": cov.gaps, "resyncs": cov.resyncs, "duplicates": cov.duplicates,
            "ignored_before_start": cov.ignored_before_start, "parse_failures": cov.parse_failures,
            "failures": [{"kind": f.kind.value, "at_utc": f.at_utc, "detail": f.detail} for f in cov.failures],
            "contract_version": ev.CONTRACT_VERSION}


def _policy(d: pp.PolicyDecision) -> dict[str, Any]:
    return {"decision_id": d.decision_id, "status": d.status.value, "action": None if d.action is None else d.action.value,
            "quantity": _s(d.quantity), "limit_price": _s(d.limit_price), "reasons": list(d.reasons),
            "execution": d.execution.value, "gross_proceeds": _s(d.gross_proceeds), "fee": _s(d.fee),
            "net_proceeds": _s(d.net_proceeds), "fee_claim_basis": d.fee_claim_basis, "no_new_risk": d.no_new_risk,
            "review_required": d.review_required, "policy_id": d.provenance.get("policy_id"),
            "policy_version": d.provenance.get("policy_version"), "policy_kind": d.provenance.get("policy_kind"),
            "evaluator": d.provenance.get("evaluator"), "authorizes_execution": d.authorizes_execution}


def _exit_estimate(book: pp.SaleBook | None, qty: Decimal, fee_model: pp.FeeModel) -> dict[str, Any]:
    """Selling the whole remaining quantity into the displayed bids now: an estimate, not a fill."""
    note = "At displayed depth: a displayed bid is not a fill, and a chart price is not proceeds."
    if book is None or book.status is not ev.BookStatus.VALID or qty <= 0:
        return {"quantity": _s(qty), "status": "NOT_AVAILABLE", "gross": None, "fee": None, "net": None,
                "worst_price": None, "note": "no usable book: " + note}
    walk = ev.walk_bids(book.bids, qty, truncated=book.truncated, market_id=book.market_id, side=book.side)
    if walk.status is not DepthStatus.FILLABLE:
        return {"quantity": _s(qty), "status": walk.status.value, "gross": None, "fee": None, "net": None,
                "worst_price": None, "available": _s(walk.available), "note": walk.detail + ". " + note}
    fees = [fee_model.sale_fee(s, p) for p, s in walk.levels]
    fee = None if any(f is None for f in fees) else sum(fees, Decimal(0))
    return {"quantity": _s(qty), "status": walk.status.value, "gross": _s(walk.gross_proceeds), "fee": _s(fee),
            "net": None if fee is None else _s(walk.gross_proceeds - fee), "worst_price": _s(walk.worst_price),
            "fee_claim_basis": fee_model.claim_basis.value, "note": note}


def _comparison(report: rp.ReplayReport) -> dict[str, Any]:
    arms = [{"arm": a.arm.value, "semantics": None if a.semantics is None else a.semantics.value,
             "entries": a.entries, "complete": a.complete, "incomplete": a.incomplete, "pnl_gross": _s(a.pnl_gross),
             "pnl_net": _s(a.pnl_net), "complete_only_pnl_gross": _s(a.complete_only_pnl_gross),
             "change_vs_hold_gross": _s(a.change_vs_hold_gross), "change_vs_hold_net": _s(a.change_vs_hold_net),
             "worst_entry_pnl_gross": a.risk.get("per_entry_pnl_gross_min"),
             "best_entry_pnl_gross": a.risk.get("per_entry_pnl_gross_max"),
             "pnl_gross_pstdev": a.risk.get("per_entry_pnl_gross_pstdev"), "clusters": a.clusters} for a in report.arms]
    return {"cohort_id": report.cohort_id, "cohort_sha256": report.cohort_sha256, "data_kind": report.data_kind,
            "label": report.label, "config_variant": report.config_variant, "fill_rule": report.fill_rule,
            "fee_model": report.fee_model, "fee_claim_basis": report.fee_claim_basis,
            "replay_version": report.version, "arms": arms, "notes": list(report.notes)}


def _diagnostics(report: rp.ReplayReport) -> list[dict[str, Any]]:
    out = []
    for label in rp.DIAGNOSTIC_LABELS:
        for arm in (rp.Arm.FULL_EXIT, rp.Arm.PARTIAL_EXIT):
            rows = [x for x in report.diagnostics if x.label == label and x.arm is arm]
            known = [x.gross_proceeds for x in rows if x.gross_proceeds is not None]
            out.append({"label": label, "arm": arm.value, "entries": len(rows), "with_value": len(known),
                        "gross_proceeds_total": _s(sum(known, Decimal(0))) if known else None,
                        "note": rows[0].note if rows else ""})
    return out


def build_view(*, mode: Mode, market_ticker: str, game_label: str, transitions: Sequence[ev.Transition],
               failures: Sequence[ev.SourceFailure] = (), parse_failures: int = 0, as_of: datetime,
               window_start: datetime, trading: ev.TradingState, inventory: pp.Inventory,
               orders: Sequence[pp.RestingOrder], policy: pp.PositionPolicy, fee_model: pp.FeeModel,
               rules_version: str | None, cohort: rp.Cohort | None, replay_config: rp.ReplayConfig | None,
               data_kind: ev.DataKind) -> dict[str, Any]:
    """One view from journalled evidence, a simulated inventory, a frozen policy and a replay."""
    if mode is Mode.NOT_AUTHORIZED:
        raise ValueError("use not_authorized_view()")
    if data_kind is ev.DataKind.RECORDED:
        raise ValueError("recorded in-play evidence needs an allocated experiment id; v1 shows fixtures only")
    if inventory.kind is not pp.InventoryKind.SIMULATED:
        raise ValueError("the research view shows simulated inventory only: no account is read")
    state = transitions[-1].state if transitions else ev.BookState(market_ticker)
    source = _source(state, transitions, failures, parse_failures, as_of=as_of, window_start=window_start,
                     max_book_age=policy.max_book_age, trading=trading)
    book = pp.SaleBook(f"kalshi:{market_ticker}", inventory.side, state.yes_bids if inventory.side == "YES"
                       else state.no_bids, False, state.status, trading, state.last_applied_receipt_utc,
                       f"journal:{market_ticker}:seq{state.last_seq}", data_kind)
    decision = pp.evaluate(as_of=as_of, inventory=inventory, orders=orders, book=book, fee_model=fee_model,
                           policy=policy, rules_version=rules_version)
    reserved = decision.provenance.get("reserved")
    report = rp.replay(cohort, replay_config) if cohort is not None and replay_config is not None else None

    if not transitions:
        vstate, detail = ViewState.EMPTY, "The journal loaded and holds no book message for this market."
    elif decision.status is pp.DecisionStatus.UNSUPPORTED:
        vstate, detail = ViewState.UNSUPPORTED, "; ".join(decision.reasons)
    elif trading in (ev.TradingState.TRADING_PAUSED, ev.TradingState.EXCHANGE_PAUSED):
        vstate, detail = ViewState.PAUSED, (f"{trading.value}: no new sale is proposed; resting orders stay on the "
                                            "book unless cancel-on-pause was set.")
    elif state.status is ev.BookStatus.VALID and not source["fresh"]:
        vstate, detail = ViewState.STALE, (f"The newest book is older than {policy.max_book_age.total_seconds():g} s "
                                           "at the replay clock: stale is not current; no sale is proposed.")
    elif (state.status is not ev.BookStatus.VALID or source["gaps"] or source["failures"] or source["parse_failures"]
          or (report is not None and any(a.incomplete for a in report.arms))):
        vstate = ViewState.PARTIAL
        detail = ("The book is awaiting resync." if state.status is not ev.BookStatus.VALID else
                  "Gaps, failures or incomplete entries in the window; they are kept, not dropped.")
    else:
        vstate, detail = ViewState.POPULATED, "Fixture evidence reconstructed; every figure is a research estimate."

    out = _base(vstate, mode, as_of.isoformat(), detail)
    out["contract"] = {"market_id": f"kalshi:{market_ticker}", "native_id": market_ticker, "game": game_label,
                       "side": inventory.side, "rules_version": rules_version, "data_kind": data_kind.value}
    out["source"] = source
    out["inventory"] = {"kind": inventory.kind.value, "initial": _s(inventory.initial_quantity),
                        "remaining": _s(inventory.quantity), "reserved": reserved,
                        "entry_cost": _s(inventory.entry_cost), "as_of_utc": inventory.as_of_utc,
                        "orders": [{"order_id": o.order_id, "origin": o.origin.value, "state": o.state.value,
                                    "remaining": _s(o.remaining), "limit_price": _s(o.limit_price),
                                    "cancel_requested": o.cancel_requested} for o in orders]}
    out["policy"] = _policy(decision)
    remaining = inventory.quantity - (Decimal(reserved) if reserved is not None else Decimal(0))
    out["exit_estimate"] = _exit_estimate(book if vstate in (ViewState.POPULATED, ViewState.PARTIAL) else None,
                                          remaining, fee_model)
    out["assumptions"] = [
        f"Policy {policy.policy_id} v{policy.version}: {policy.kind.value}, target {policy.target_price}, "
        f"{policy.execution.value}; frozen before the replay, not tuned on it.",
        "Inventory is SIMULATED; no account was read.",
        f"Fees: {getattr(fee_model, 'model_id', 'unknown')} (claim basis {fee_model.claim_basis.value}). An unknown "
        "fee blocks every after-cost figure.",
        "Bot sales fill only on the first usable book received after the modelled arrival; resting sales fill only "
        "when bids trade through the limit; no fill is interpolated through a gap.",
        "Released cash stays idle to the common horizon; proceeds are not profit.",
    ]
    if report is not None:
        out["comparison"] = _comparison(report)
        out["diagnostics"] = _diagnostics(report)
        out["after_cost_claim"] = report.after_cost_claim
        out["after_cost_reason"] = report.after_cost_reason
        out["assumptions"].append(f"Replay latencies: decision {replay_config.decision_latency.total_seconds():g} s, "
                                  f"arrival {_arrival_text(replay_config)}; fill rule {replay_config.fill_rule.value}.")
    out["blocker"] = ("Real in-play evidence needs owner approval of the pilot, the data-rights decision, a reviewed "
                      "recorder and a research slot; until then only fixtures and synthetic cohorts are shown.")
    return out


def _arrival_text(cfg: rp.ReplayConfig) -> str:
    return "unknown (no fill)" if cfg.arrival_latency is None else f"{cfg.arrival_latency.total_seconds():g} s"


# --------------------------------------------------------------------------- fixtures (demo and gallery only)

FIXTURE_TICKER = "KXNFLGAME-FIXTURE-HOME"
_T0 = datetime.fromisoformat("2026-10-04T17:00:00+00:00")


def _msg(raw: Mapping[str, Any], seconds: float) -> ev.BookMessage:
    out = ev.parse_book_message(raw, receipt_utc=(_T0 + timedelta(seconds=seconds)).isoformat())
    if isinstance(out, ev.ParseFailure):
        raise ValueError(f"fixture message invalid: {out.reason}")
    return out


def _snap(seq: int, yes: Iterable[tuple[str, str]], no: Iterable[tuple[str, str]], seconds: float, sid: int = 1):
    return _msg({"type": "orderbook_snapshot", "sid": sid, "seq": seq,
                 "msg": {"market_ticker": FIXTURE_TICKER, "yes_dollars_fp": [list(x) for x in yes],
                         "no_dollars_fp": [list(x) for x in no]}}, seconds)


def _delta(seq: int, price: str, qty: str, seconds: float, side: str = "yes", sid: int = 1):
    return _msg({"type": "orderbook_delta", "sid": sid, "seq": seq,
                 "msg": {"market_ticker": FIXTURE_TICKER, "price_dollars": price, "delta_fp": qty, "side": side,
                         "ts_ms": int((_T0 + timedelta(seconds=seconds - 0.05)).timestamp() * 1000)}}, seconds)


def _journal(kind: str) -> tuple[list[ev.BookMessage], list[ev.SourceFailure], int]:
    """FIXTURE journals: a clean game, one with a gap and resync, and an empty one."""
    if kind == "empty":
        return [], [], 0
    # A small resting level at 0.30 changes every 10 s (so the feed is never silent for long), and
    # the bid side climbs through the game: 0.45 at 600 s, 0.55 at 1800 s, 0.70 and 0.72 at 3000 s.
    steps: list[tuple[float, str, str]] = []
    for i, t in enumerate(range(10, 3001, 10)):
        steps.append((float(t), "0.3000", "1.00" if i % 2 == 0 else "-1.00"))
    steps += [(600.5, "0.4500", "60.00"), (1800.5, "0.5500", "90.00"), (3000.5, "0.7000", "140.00"),
              (3004.0, "0.7200", "40.00")]
    steps.sort()
    msgs = [_snap(1, [("0.3000", "250.00"), ("0.3100", "80.00")], [("0.2500", "120.00")], 0)]
    msgs += [_delta(n, price, qty, t) for n, (t, price, qty) in enumerate(steps, start=2)]
    failures: list[ev.SourceFailure] = []
    if kind == "gap":  # the connection drops at 2400 s; a late delta shows the gap; a new subscription resyncs
        kept = [m for m in msgs if parse_utc(m.stamps.receipt_utc) < _T0 + timedelta(seconds=2400)]
        msgs = kept + [_delta(kept[-1].seq + 7, "0.6800", "30.00", 2410),
                       _snap(1, [("0.3000", "250.00"), ("0.5500", "90.00"), ("0.7000", "90.00"), ("0.7200", "25.00")],
                             [("0.2500", "60.00")], 2990, sid=2)]
        msgs += [_delta(n, "0.3000", "1.00" if n % 2 else "-1.00", 2990 + 3 * (n - 1), sid=2) for n in range(2, 7)]
        failures = [ev.SourceFailure(ev.FailureKind.DISCONNECTED, (_T0 + timedelta(seconds=2400)).isoformat(),
                                     "FIXTURE: connection closed")]
    if kind == "awaiting_resync":  # the same drop, and no resync yet
        kept = [m for m in msgs if parse_utc(m.stamps.receipt_utc) < _T0 + timedelta(seconds=2995)]
        msgs = kept + [_delta(kept[-1].seq + 5, "0.7000", "140.00", 3000)]
    return msgs, failures, 0


def _policy_for(kind: pp.PolicyKind = pp.PolicyKind.FIXED_TARGET_FULL_EXIT) -> pp.PositionPolicy:
    return pp.PositionPolicy("inplay-fixed-target-v1", "1", kind, pp.ExecutionAssumption.BOT_TRIGGERED_IOC,
                             target_price=Decimal("0.70"), max_book_age=timedelta(seconds=15))


def _fixture_cohort() -> rp.Cohort:
    # the entry fee of a KXNFLGAME purchase is unverified (Kalshi Q7): entry costs are unknown too
    return rp.synthetic_martingale_cohort(seed=20260928, games=12, step_seconds=5, games_per_cluster=4,
                                          entry_fee_known=False)


def fixture_view(variant: str = "populated") -> dict[str, Any]:
    """A FIXTURE view for the demo and the in-play gallery. `variant` is one of FIXTURE_VARIANTS."""
    if variant not in FIXTURE_VARIANTS:
        raise ValueError(f"unknown fixture variant {variant!r}")
    if variant == "error":
        return error_view("FIXTURE: the journal header is not inplay-journal-v1 (read refused, nothing shown).")
    if variant == "not_authorized":
        return not_authorized_view()
    journal = {"empty": "empty", "partial": "gap", "resync": "awaiting_resync"}.get(variant, "clean")
    msgs, failures, parse_failures = _journal(journal)
    _, transitions = ev.reconstruct(FIXTURE_TICKER, msgs)
    as_of = _T0 + timedelta(seconds=3006 if variant != "stale" else 3300)
    trading = ev.TradingState.TRADING_PAUSED if variant == "paused" else ev.TradingState.OPEN
    policy = _policy_for(pp.PolicyKind.FAIR_VALUE if variant == "unsupported" else
                         pp.PolicyKind.FIXED_TARGET_FULL_EXIT)
    inventory = pp.Inventory(f"kalshi:{FIXTURE_TICKER}", "YES", Decimal(100), Decimal(100),
                             pp.InventoryKind.SIMULATED, as_of.isoformat(), "fixture:simulated-entry",
                             entry_cost=None)
    fee_model = pp.fee_model_for("kalshi", FIXTURE_TICKER, as_of)
    cfg = rp.ReplayConfig(target_price=Decimal("0.70"), partial_fraction=Decimal("0.5"), fee_model=fee_model)
    cohort = None if variant in ("empty", "unsupported") else _fixture_cohort()
    return build_view(mode=Mode.FIXTURE, market_ticker=FIXTURE_TICKER, game_label="FIXTURE home team to win",
                      transitions=transitions, failures=failures, parse_failures=parse_failures, as_of=as_of,
                      window_start=_T0, trading=trading, inventory=inventory, orders=(), policy=policy,
                      fee_model=fee_model, rules_version="fixture-rules-v1", cohort=cohort,
                      replay_config=cfg if cohort is not None else None, data_kind=ev.DataKind.FIXTURE)


FIXTURE_VARIANTS = ("populated", "empty", "stale", "partial", "resync", "unsupported", "paused", "error",
                    "not_authorized")
