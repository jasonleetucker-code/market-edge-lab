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
            "blocker": None, "source_state": None, "fill_economics": None}


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
             "pnl_gross_pstdev": a.risk.get("per_entry_pnl_gross_pstdev"), "clusters": a.clusters,
             "not_placed": a.not_placed} for a in report.arms]
    return {"cohort_id": report.cohort_id, "cohort_sha256": report.cohort_sha256, "data_kind": report.data_kind,
            "label": report.label, "config_variant": report.config_variant, "fill_rule": report.fill_rule,
            "fee_model": report.fee_model, "fee_claim_basis": report.fee_claim_basis,
            "replay_version": report.version, "diagnostic_mode": report.diagnostic_mode, "arms": arms,
            "notes": list(report.notes)}


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
               data_kind: ev.DataKind, state_variant: str | None = None) -> dict[str, Any]:
    """One view from journalled evidence, a simulated inventory, a frozen policy and a replay.

    With `state_variant` (FIXTURE game states, `source_state_section`), the policy decision is checked against
    the game state it depends on: a material new event makes it BLOCKED for review, never a sale."""
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
    source_state, validity = None, None
    if state_variant is not None:
        source_state, validity = source_state_section(
            variant=state_variant, as_of=as_of, book_state=state, data_kind=data_kind, max_age=policy.max_book_age,
            decision_id=f"inplay:{policy.policy_id}:{as_of.isoformat()}")
    decision = pp.evaluate(as_of=as_of, inventory=inventory, orders=orders, book=book, fee_model=fee_model,
                           policy=policy, rules_version=rules_version, state_validity=validity)
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
        vstate, detail = ViewState.POPULATED, (f"Evidence reconstructed from a {data_kind.value.lower()} journal; every "
                                               "figure is a research estimate.")

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
        games = len(cohort.entries)
        # the replay's cohort is its own set of games: say so beside a contract it does not describe
        out["comparison"]["scope_note"] = (f"A {report.data_kind.lower()} cohort of {games} game"
                                           f"{'' if games == 1 else 's'}, not this contract ({market_ticker}).")
        out["diagnostics"] = _diagnostics(report)
        out["after_cost_claim"] = report.after_cost_claim
        out["after_cost_reason"] = report.after_cost_reason
        out["assumptions"].append(f"Replay latencies: decision {replay_config.decision_latency.total_seconds():g} s, "
                                  f"arrival {_arrival_text(replay_config)}; fill rule {replay_config.fill_rule.value}.")
    out["source_state"] = source_state
    out["fill_economics"] = fill_economics_section(cohort, report)
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
    journal = {"empty": "empty", "partial": "gap", "resync": "awaiting_resync"}.get(variant, "clean")  # also the
    # clean journal for "invalidated" and "state_unknown", whose game states differ (`_fixture_states`)
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
                      replay_config=cfg if cohort is not None else None, data_kind=ev.DataKind.FIXTURE,
                      state_variant=variant)


FIXTURE_VARIANTS = ("populated", "empty", "stale", "partial", "resync", "unsupported", "paused", "error",
                    "not_authorized", "invalidated", "state_unknown")


# --------------------------------------------------------------------------- source, state and fill economics (PR C)
#
# Compact displays of the R2 contracts (ADR 0041), fed only by the fixture journal and the synthetic replay. No
# source-comparison widget is built here: nothing compares two sources' prices, so the EXP-002 label-proxy cutoff
# (`odds_schedule.is_label_proxy`) is never reached, and no NFL pilot quote is read.

_LOCAL_CLOCK = "fixture:host"
_SOURCE_CLOCK = "fixture:kalshi-ts_ms"


def _latency_rows(breakdown: ev.LatencyBreakdown) -> list[dict[str, Any]]:
    out = []
    for stage in ev.LatencyStage:
        m = breakdown.get(stage)
        out.append({"stage": stage.value, "seconds": None if m is None else _s(Decimal(str(m.value.total_seconds()))),
                    "uncertainty_seconds": None if m is None or m.uncertainty is None
                    else _s(Decimal(str(m.uncertainty.total_seconds()))),
                    "measured": m is not None, "method": None if m is None else m.method,
                    "clock_inconsistent": bool(m is not None and m.clock_inconsistent)})
    return out


def _fixture_states(variant: str, as_of: datetime) -> ev.GameJournal:
    """FIXTURE game states: Q4 0-0, then (per variant) a touchdown or an unreadable update seen 5 s before the
    replay clock, after the policy decided on the earlier state."""
    def state(seconds_before: float, home: int, event: str, status=ev.GameStateStatus.OBSERVED) -> ev.GameState:
        at = (as_of - timedelta(seconds=seconds_before)).isoformat()
        return ev.GameState("FIXTURE-GAME", "fixture:scores", event, ev.Stamps(at, at), status,
                            f"fixture-{event}", home_score=None if status is not ev.GameStateStatus.OBSERVED else home,
                            away_score=None if status is not ev.GameStateStatus.OBSERVED else 0, period="Q4",
                            game_clock_text="Q4 02:13")
    journal = ev.GameJournal("FIXTURE-GAME").append(state(120, 0, "e1"))
    if variant == "invalidated":
        journal = journal.append(state(5, 7, "e2"))
    elif variant == "state_unknown":
        journal = journal.append(state(5, 0, "e3", ev.GameStateStatus.UNSUPPORTED_OR_UNMAPPED))
    return journal


DECISION_LAG = timedelta(seconds=20)  # the fixture policy computed its proposal on the state seen 20 s earlier


def source_state_section(*, variant: str, as_of: datetime, book_state: ev.BookState, data_kind: ev.DataKind,
                         max_age: timedelta, decision_id: str) -> tuple[dict[str, Any], ev.StateValidity]:
    """Source, state and clock validity for the fixture book (inplay_evidence source-state-v1)."""
    received = parse_utc(book_state.last_applied_receipt_utc)
    published = parse_utc(book_state.last_source_ts_utc)
    evidence = ev.EvidenceStatus.SIMULATED  # fixture input can never be ACTUAL (check_evidence)
    ctx = ev.SourceContext("NFL", "moneyline (FIXTURE)", ev.Phase.LIVE, "FIXTURE")
    obs = None
    if received is not None:
        rec = ev.ClockReading(received.isoformat(), ev.ClockOrigin.LOCAL, _LOCAL_CLOCK, timedelta(milliseconds=1),
                              timedelta(milliseconds=50))
        pub = None if published is None else ev.ClockReading(published.isoformat(), ev.ClockOrigin.SOURCE,
                                                             _SOURCE_CLOCK, timedelta(milliseconds=1), None)
        latency = ev.LatencyBreakdown(tuple((stage, m) for stage, m in (
            (ev.LatencyStage.TRANSPORT, ev.measure_between(pub, rec, "receipt - venue ts_ms")),) if m is not None))
        obs = ev.SourceObservation(f"fixture:book:{book_state.last_seq}", "fixture:kalshi-book", "FIXTURE-GAME", rec,
                                   ctx, evidence, data_kind, source_family="FIXTURE_EXCHANGE", published=pub,
                                   latency=latency)
    journal = _fixture_states(variant, as_of)
    decided_at = as_of - DECISION_LAG
    dep = ev.game_state_as_of(journal, decided_at)
    stamp = ev.DecisionStamp(decision_id, "inplay-fixed-target-v1", decided_at.isoformat(), True,
                             None if dep is None else dep.observation_id)
    validity = ev.decision_validity(stamp, journal, at=as_of)
    freshness = None if obs is None else ev.content_freshness(obs, now=as_of, max_age=max_age)
    section = {
        "contract_version": ev.SOURCE_STATE_VERSION,
        "evidence_status": evidence.value, "data_kind": data_kind.value,
        "source_id": None if obs is None else obs.source_id,
        "source_family": None if obs is None else obs.source_family,
        "context": {"sport": ctx.sport, "market": ctx.market, "phase": ctx.phase.value, "regime": ctx.regime},
        "received_utc": None if obs is None else obs.received.utc,
        # precision 1 ms + clock bound 50 ms (the fixture host clock); None when no book was received
        "received_uncertainty_seconds": None if obs is None else "0.051",
        "published_utc": None if obs is None or obs.published is None else obs.published.utc,
        "published_uncertainty": "UNKNOWN" if obs is not None and obs.published is not None else None,
        "content_freshness": None if freshness is None else freshness.value,
        "incorporated_state": None if obs is None else obs.state_knowledge.value,
        "latency": [] if obs is None else _latency_rows(obs.latency),
        "decision": {"decision_id": decision_id, "as_of_utc": stamp.as_of_utc, "state_version": stamp.state_version,
                     "checked_at_utc": validity.checked_at_utc, "status": validity.status.value,
                     "reasons": [f"{r.value}: {d}" for r, d in validity.reasons],
                     "superseded_by": list(validity.superseded_by),
                     "non_material_updates": validity.non_material_updates},
        "game_clock_note": "The game clock (Q4 02:13) is game time, not UTC; it orders nothing here.",
        "note": ("A quote's incorporated game state is UNKNOWN unless its source declares it; arriving after a "
                 "scoreboard change does not make a quote reflect it."),
    }
    return section, validity


def _cohort_fills(cohort: rp.Cohort, report: rp.ReplayReport, arm: rp.Arm, semantics: rp.Semantics | None):
    """Simulated fills of one arm: each entry's purchase, and its sale when one filled (mode by semantics)."""
    from . import research_economics as re_

    kind = ev.DataKind(report.data_kind)
    mode = {rp.Semantics.PREPLACED_LIMIT: re_.ExecutionMode.BOOK_MAKER}.get(semantics, re_.ExecutionMode.TAKER)
    results = {r.game_id: r for r in report.entries if r.arm is arm and r.semantics is semantics}
    fills, resolutions = [], {}
    ctx = ev.SourceContext("NFL", "synthetic YES", ev.Phase.LIVE, "SYNTHETIC")
    for e in cohort.entries:
        entry_fee = None if e.entry_cost is None else e.entry_cost - e.quantity * e.entry_price
        fills.append(re_.Fill(f"{e.game_id}:buy", re_.ExecutionMode.TAKER, ev.EvidenceStatus.SIMULATED, kind,
                              e.market_id, "BUY", e.quantity, e.entry_price, entry_fee, e.entry_at_utc, ctx,
                              exposure_keys=(e.cluster_id,), season="SYNTHETIC", peak=False))
        r = results.get(e.game_id)
        if r is not None and r.sold > 0 and r.last_fill_at_utc is not None:
            fills.append(re_.Fill(f"{e.game_id}:sell", mode, ev.EvidenceStatus.SIMULATED, kind, e.market_id, "SELL",
                                  r.sold, r.gross_proceeds / r.sold, r.fees, r.last_fill_at_utc, ctx,
                                  exposure_keys=(e.cluster_id,), season="SYNTHETIC", peak=False))
        s = e.settlement
        resolutions[e.market_id] = re_.Resolution(s.value if s.final else None, s.at_utc)
    return fills, resolutions


def fill_economics_section(cohort: rp.Cohort | None, report: rp.ReplayReport | None) -> dict[str, Any]:
    """Fill-conditioned economics per arm, from the synthetic replay only (there is no real fill)."""
    from . import research_economics as re_

    if cohort is None or report is None:
        return {"state": "NOT_EVALUATED", "detail": "No cohort was replayed, so there are no simulated fills.",
                "rows": [], "rfq": "RFQ: not evaluated (no RFQ source; the RFQ packet is #148)."}
    start = min(parse_utc(e.entry_at_utc) for e in cohort.entries)
    rows = []
    for arm, sem in ((rp.Arm.HOLD, None), (rp.Arm.FULL_EXIT, rp.Semantics.BOT_TRIGGERED),
                     (rp.Arm.FULL_EXIT, rp.Semantics.PREPLACED_LIMIT)):
        label = {None: "Hold to settlement", rp.Semantics.BOT_TRIGGERED: "Full exit · bot-triggered (taker)",
                 rp.Semantics.PREPLACED_LIMIT: "Full exit · preplaced limit (book maker)"}[sem]
        try:
            fills, res = _cohort_fills(cohort, report, arm, sem)
            r = re_.fill_economics(fills, resolutions=res, window_start_utc=start.isoformat(),
                                   window_end_utc=cohort.horizon_utc, total_capital=cohort.starting_capital,
                                   fixed_cash_costs=re_.Labeled.unknown("no fixed cash cost recorded for a synthetic "
                                                                        "cohort"),
                                   owner_hours=re_.Labeled.unknown("not tracked for a synthetic cohort"),
                                   turnover_basis=re_.TurnoverBasis.TOTAL_CAPITAL)
        except ValueError as exc:
            rows.append({"arm": label, "state": "ERROR", "detail": str(exc)})
            continue
        modes = sorted({g.key[0] for g in r.groups})
        rows.append({"arm": label, "state": "POPULATED", "modes": modes, "evidence": r.evidence,
                     "data_kind": r.data_kind, "fills": r.fills, "notional": _s(r.notional),
                     "gross": _s(r.total_gross), "fees": _s(r.fees), "net": _s(r.net_contribution),
                     "peak_collateral": _s(r.peak_collateral), "capital_days": _s(r.capital_days),
                     "return_on_deployed": _s(r.return_on_deployed), "turnover": _s(r.turnover),
                     "turnover_basis": r.turnover_basis, "open_positions": len(r.open_positions),
                     "missing": [x.split(":", 1)[0] for x in r.reasons if not x.startswith("MODES_SEPARATE")],
                     "reasons": list(r.reasons)})
    return {"state": "POPULATED" if all(x["state"] == "POPULATED" for x in rows) else "PARTIAL",
            "detail": (f"Simulated fills of a {report.data_kind.lower()} cohort ({len(cohort.entries)} games); "
                       "fill-conditioned-economics-v1. Not a real fill, not an edge."),
            "rows": rows, "rfq": "RFQ: not evaluated (no RFQ source; the RFQ packet is #148)."}
