"""Synthetic demo data, isolated from every real store.

`build_demo` writes a small ledger, evidence store and status files into a **fresh
temporary directory** through the real `ShadowLedger` and `SnapshotStore` APIs. It never
receives, reads or writes the configured paths. Every page rendered from it carries the
SYNTHETIC DEMO DATA watermark (`Config.demo`). Market ids carry a DEMO- prefix.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .. import exp001_shadow, forward, notifications, starter_policy, venues
from ..fill_policy import LATENCY_CONFIRMED_V1
from ..opportunity import MarketTiming
from ..shadow_ledger import ShadowLedger
from ..storage import SnapshotStore
from . import data as d

DEMO_PREFIX = "edge-lab-dashboard-demo-"


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


def _decision(account: str, n: int, at: datetime, market: str, side: str, qualify: bool, reason: str,
              p: str, price: str, fee: str, cost: str, edge: str) -> dict:
    opp_id = f"demo-opp-{account[-8:]}-{n}"
    return {
        # The slot names the target day as the real pipeline does (the day after the ET decision day).
        "decision_id": f"dec-{opp_id}", "slot": f"{forward.target_for(at).isoformat()}|{market}|{side}",
        "opportunity_id": opp_id,
        "as_of_utc": _iso(at), "qualification": "QUALIFY" if qualify else "REJECT", "reason": reason,
        "reasons": [] if qualify else [reason], "model_version": "demo", "quote_evidence_ids": [],
        "event_id": "kalshi:DEMO-KXHIGHNY-EVENT", "market_id": market, "side": side,
        "outcome_cluster": "DEMO-NYC-HIGH", "policy_id": "demo",
        "opportunity": {"model_probability": p, "conservative_probability": str(Decimal(p) - Decimal("0.03")),
                        "executable_price": price, "fee": fee, "all_in_cost": cost, "net_edge": edge,
                        "net_edge_conservative": str(Decimal(edge) - Decimal("0.03")), "freshness": "fresh",
                        "fee_status": exp001_shadow.fee_fields(_iso(at), market)["fee_status"]},
        "sizing": {"final_size": 1, "binding_constraint": "fixed_contracts"} if qualify else None,
        "stage_b_day_status": "VALID", **exp001_shadow.fee_fields(_iso(at), market),
    }


def _fill(dec: dict, filled: bool, price: str, fee: str, cost: str, expected: datetime, reason: str = "FILLED") -> dict:
    return {
        "fill_id": f"fill-{dec['opportunity_id']}", "decision_id": dec["decision_id"], "venue": "kalshi",
        "market_id": dec["market_id"], "event_id": dec["event_id"], "outcome_cluster": dec["outcome_cluster"],
        "side": dec["side"], "filled_at_utc": dec["as_of_utc"], "fill_policy_id": LATENCY_CONFIRMED_V1.policy_id,
        "expected_settlement_utc": _iso(expected), **exp001_shadow.fee_fields(dec["as_of_utc"], dec["market_id"]),
        "status": "FILLED" if filled else "NO_FILL", "reason": reason if not filled else "FILLED",
        "quantity": 1 if filled else 0, "price": price if filled else None, "fee": fee if filled else None,
        "total_cost": cost if filled else None, "detail": "synthetic demo fill",
    }


def _demo_verdict(committed: datetime, expected_resolution: datetime) -> dict:
    """A real STARTER_MAX_7D_V1 verdict on synthetic timing (documented Kalshi cash timing and
    the committed KXHIGHNY lag evidence)."""
    timing = MarketTiming(expected_resolution_utc=_iso(expected_resolution), settlement_timer_seconds=300,
                          lifecycle_status="active",
                          latest_resolution_utc=_iso(expected_resolution + timedelta(days=6)), source="demo")
    return starter_policy.assess(commitment=committed, timing=timing,
                                 lag=starter_policy.lag_evidence("kalshi", "KXHIGHNY"),
                                 cash=venues.cash_timing("kalshi")).to_dict()


def _account(ledger: ShadowLedger, account: exp001_shadow.ShadowAccount, now: datetime) -> None:
    ledger.open_account(account.account_id, starting_bankroll=account.starting_bankroll,
                        strategy=f"DEMO {account.strategy}", opened_at_utc=_iso(now - timedelta(days=5)),
                        sizing_policy_id=account.sizing_policy_id,
                        fill_policy_id=LATENCY_CONFIRMED_V1.policy_id, fee_schedule_id="kalshi-quadratic-taker-v1")
    binding = "fixed_contracts" if account.sizing is not None else "frozen_rule"
    starter = account.starter_policy
    account = account.account_id
    day1, day2 = now - timedelta(days=3), now - timedelta(hours=20)
    won = _decision(account, 1, day1, "kalshi:DEMO-B67.5", "YES", True, "QUALIFY", "0.41", "0.34", "0.0158",
                    "0.36", "0.05")
    rejected = _decision(account, 2, day1, "kalshi:DEMO-B69.5", "YES", False, "EDGE_BELOW_THRESHOLD", "0.22",
                         "0.21", "0.0117", "0.23", "-0.01")
    unfilled = _decision(account, 3, day1, "kalshi:DEMO-T72", "NO", True, "QUALIFY", "0.93", "0.85", "0.0090",
                         "0.86", "0.07")
    open_ = _decision(account, 4, day2, "kalshi:DEMO-B71.5", "YES", True, "QUALIFY", "0.30", "0.24", "0.0128",
                      "0.26", "0.04")
    overdue = _decision(account, 5, day2, "kalshi:DEMO-B73.5", "NO", True, "QUALIFY", "0.88", "0.80", "0.0112",
                        "0.82", "0.06")
    long_dated = _decision(account, 6, day2, "kalshi:DEMO-SEASON", "YES", True, "QUALIFY", "0.20", "0.12",
                           "0.0074", "0.13", "0.07")
    for dec in (won, unfilled, open_, overdue, long_dated):
        dec["sizing"]["binding_constraint"] = binding
    for dec in (won, rejected, unfilled, open_, overdue) + ((long_dated,) if starter else ()):
        ledger.record_decision(account, dec)
    ledger.record_fill(account, _fill(won, True, "0.34", "0.0158", "0.36", day1 + timedelta(days=2)))
    ledger.record_fill(account, _fill(unfilled, False, "0", "0", "0", day1 + timedelta(days=2),
                                      reason="CONFIRMATION_MISSING"))
    ledger.record_fill(account, _fill(open_, True, "0.24", "0.0128", "0.26", now + timedelta(days=1)))
    late = _fill(overdue, True, "0.80", "0.0112", "0.82", now - timedelta(hours=2))
    if starter:  # operational only: eligible when committed (day 1), now past its expected release
        late["starter_policy"] = _demo_verdict(day1, now - timedelta(hours=2) - timedelta(hours=49, minutes=5))
    ledger.record_fill(account, late)
    if starter:  # a long-dated market: visible, but ineligible for starter capital
        season = _fill(long_dated, False, "0", "0", "0", now + timedelta(days=40), reason="STARTER_POLICY_INELIGIBLE")
        season["starter_policy"] = _demo_verdict(day2, now + timedelta(days=40))
        season["detail"] = "STARTER_MAX_7D_V1: " + ", ".join(season["starter_policy"]["reasons"])
        ledger.record_fill(account, season)
    ledger.record_settlement(account, fill_id=f"fill-{won['opportunity_id']}", outcome="YES",
                             settled_at_utc=_iso(now - timedelta(days=1)),
                             evidence={"snapshot_id": None, "note": "synthetic demo settlement"})


# Synthetic captured books for the demo target day: (ticker, YES label, decision book, re-check book).
# A book is (best YES bid, size, best NO bid, size); asks follow from the opposite side's bid.
_DEMO_BOOKS = (
    ("DEMO-B67.5", "67° to 68°", ("0.32", "140", "0.64", "90"), ("0.33", "120", "0.66", "75")),
    ("DEMO-B69.5", "69° to 70°", ("0.20", "200", "0.78", "150"), ("0.21", "180", "0.77", "160")),
    ("DEMO-B71.5", "71° to 72°", ("0.23", "60", "0.75", "40"), ("0.22", "55", "0.7525", "40")),
    ("DEMO-B73.5", "73° to 74°", ("0.17", "35", "0.19", "25"), ("0.16", "30", "0.20", "25")),
    ("DEMO-T72", "72° or above", ("0.09", "300", "0.14", "220"), None),
)


def _demo_captures(store: SnapshotStore, now: datetime) -> None:
    """Decision and re-check captures through the real SnapshotStore API (DEMO- tickers only)."""
    target = forward.target_for(now - timedelta(hours=20))
    ticker = f"DEMO-{forward.event_ticker_for(target)}"
    for phase, offset, index in (("decision", timedelta(hours=20), 2), ("recheck", timedelta(hours=19, minutes=48), 3)):
        run = f"demo-{phase}"
        at = now - offset
        store.start_run(run)
        markets = [{"ticker": t, "event_ticker": ticker, "status": "active", "title": "DEMO: Highest temperature in NYC?",
                    "yes_sub_title": label, "no_sub_title": f"Not {label}", "close_time": _iso(now + timedelta(hours=6)),
                    "rules_primary": "SYNTHETIC DEMO rules: resolves on a synthetic climate report."}
                   for t, label, *_ in _DEMO_BOOKS]
        links: dict = {"market_snapshots": [store.save_snapshot(
            run_id=run, source="demo", kind="markets", entity_id=ticker, url="demo://markets",
            payload={"markets": markets}, fetched_at_utc=_iso(at))], "books": {}}
        for t, _, *books in _DEMO_BOOKS:
            book = books[index - 2]
            if book is None:
                continue
            yes, ysz, no, nsz = book
            sid = store.save_snapshot(run_id=run, source="demo", kind="orderbook", entity_id=t, url=f"demo://book/{t}",
                                      payload={"orderbook_fp": {"yes_dollars": [[yes, ysz]], "no_dollars": [[no, nsz]]}},
                                      fetched_at_utc=_iso(at))
            links["books"][t] = {"snapshot_id": sid}
        store.record_forward_capture(
            run_id=run, experiment="DEMO", phase=phase, mode="live", target_date=target.isoformat(), event_ticker=ticker,
            started_at_utc=_iso(at - timedelta(seconds=20)), completed_at_utc=_iso(at),
            window_start_utc=_iso(at - timedelta(minutes=5)), window_end_utc=_iso(at + timedelta(minutes=1)),
            status="complete", reasons=[], links=links, code_version="demo")
        store.finish_run(run, status="succeeded")


def _demo_other_domains(ledger: ShadowLedger, now: datetime) -> None:
    """Recorded-but-rejected SYNTHETIC decisions in other domains (no fills, no money): they show
    that sports, politics and economics rows use the same components as weather."""
    at = now - timedelta(hours=3)
    for n, (domain, market, reason) in enumerate((
            ("sports", "kalshi:DEMO-NFL-KCBUF", "MODEL_UNAVAILABLE"),
            ("politics", "kalshi:DEMO-SENATE-VOTE", "FEE_UNSUPPORTED"),
            ("economics", "kalshi:DEMO-CPI-SEP", "MODEL_UNAVAILABLE")), start=10):
        dec = _decision(d.OPERATIONAL_ACCOUNT_ID, n, at, market, "YES", False, reason, "0.50", "0.48", "0.0175",
                        "0.50", "0.00")
        dec["event_id"] = f"{domain}:demo:{market.split(':', 1)[1]}"
        dec["outcome_cluster"] = f"{domain}:demo"
        dec["opportunity"].update({"model_probability": None, "conservative_probability": None, "net_edge": None,
                                   "net_edge_conservative": None, "outcome": "SYNTHETIC"})
        ledger.record_decision(d.OPERATIONAL_ACCOUNT_ID, dec)


def _demo_notifications(status: Path, now: datetime) -> dict:
    """Synthetic events through the real notification pipeline into the demo's local outbox."""
    events = [
        notifications.make_event(notifications.EventType.SEVEN_DAY_POLICY_EXCEPTION, notifications.Severity.CRITICAL,
                                 created_at=now - timedelta(minutes=30), summary="DEMO: capital past its expected release",
                                 dedupe_key="demo-exception", deep_link="http://127.0.0.1:8765/risk",
                                 action_mode=notifications.ActionMode.OPEN_MARKET_EDGE,
                                 origin=notifications.Origin.DEMO),
        notifications.make_event(notifications.EventType.SOURCE_FAILURE, notifications.Severity.WARNING,
                                 created_at=now - timedelta(hours=2), summary="DEMO: nws_pfm_okx HTTP 503",
                                 dedupe_key="demo-source", origin=notifications.Origin.DEMO),
    ]
    outbox = notifications.JsonlOutbox(status / d.NOTIFICATIONS_FILE)
    results = notifications.dispatch(events, [outbox, notifications.DisabledSmsSink()], now=now)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"status": "ok", "events": len(events), "delivered": by_status.get("DELIVERED", 0), "by_status": by_status}


def build_demo(now: datetime | None = None, *, experiments_root: Path | None = None) -> tuple[d.Config, Path]:
    """A Config over a new temporary directory holding synthetic data. Returns (config, dir).

    `experiments_root` (the repository's read-only experiment manifests) is the only real
    source a demo may show; the experiments view labels it as such."""
    now = now or datetime.now(timezone.utc)
    root = Path(tempfile.mkdtemp(prefix=DEMO_PREFIX))
    ledger = ShadowLedger(root / "demo_shadow_ledger.sqlite3")
    for account in (exp001_shadow.OPERATIONAL, exp001_shadow.RESEARCH):
        _account(ledger, account, now)
    store = SnapshotStore(root / "demo_evidence.sqlite3")
    store.start_run("demo-run")
    for source, status, error in (("kalshi_public", "ok", None), ("nws_pfm_okx", "failed", "DEMO: HTTP 503")):
        store.record_source_health(run_id="demo-run", source_id=source, started_at_utc=_iso(now - timedelta(hours=2)),
                                   completed_at_utc=_iso(now - timedelta(hours=2) + timedelta(seconds=4)),
                                   duration_ms=4000, status=status, records=0 if error else 12, error=error)
    store.finish_run("demo-run", status="succeeded")
    _demo_captures(store, now)
    _demo_other_domains(ledger, now)
    status = root / "status"
    status.mkdir()
    (status / d.COLLECTOR_STATUS_FILE).write_text(json.dumps({
        "generated_at_utc": _iso(now - timedelta(hours=1)), "last_closed_target_date": (now - timedelta(days=1))
        .date().isoformat(), "last_closed_status": "VALID", "last_closed_reasons": [], "valid_days": 2,
        "first_valid_day": (now - timedelta(days=3)).date().isoformat(), "days_with_captures": 3,
        "invalid_days": [(now - timedelta(days=2)).date().isoformat()]}), encoding="utf-8")
    last_day = (now - timedelta(hours=20)).date().isoformat()
    per_account = {"decisions": 2, "qualified": 2, "fills": 2, "no_fills": {}, "risk_vetoes": 0}
    (status / d.RECEIPT_FILE).write_text(json.dumps({  # same shape as edge_lab.daily writes
        "schema": d.RECEIPT_SCHEMA, "generated_at_utc": _iso(now - timedelta(minutes=30)), "code_version": "demo",
        "state": "PENDING_SETTLEMENT", "exit_code": 0,
        "days": [{"target_date": last_day, "decision_time_utc": _iso(now - timedelta(hours=20)),
                  "accounts": {d.RESEARCH_ACCOUNT_ID: per_account, d.OPERATIONAL_ACCOUNT_ID: per_account},
                  "problems": [], "capture_status": "VALID", "result": "HEALTHY_TRADED"}],
        "settlement": {"refresh": {"status": "ok", "run_id": "demo-run", "events_requested": 1,
                                   "markets_stored": 6, "settled_markets": 0, "errors": []},
                       "settled": 0, "evidence_cutoff_utc": _iso(now - timedelta(minutes=30)),
                       "pending": [{"account_id": acct, "position_id": f"fill-demo-opp-{acct[-8:]}-5",
                                    "reason": "no settlement evidence yet"}
                                   for acct in (d.RESEARCH_ACCOUNT_ID, d.OPERATIONAL_ACCOUNT_ID)],
                       "conflicts": []},
        "fee": exp001_shadow.fee_receipt(now), "notifications": _demo_notifications(status, now),
        "accounts": {}, "problems": [], "missing_capture_days": [], "valid_days": 2, "closed_capture_days": 3,
        "latest_day": {"target_date": last_day, "result": "HEALTHY_TRADED", "capture_status": "VALID"}}),
        encoding="utf-8")
    config = d.Config(db=store.path, ledger=ledger.path, status_dir=status, experiments_root=experiments_root, demo=True)
    return config, root
