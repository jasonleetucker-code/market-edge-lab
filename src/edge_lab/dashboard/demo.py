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

from .. import exp001_shadow
from ..fill_policy import LATENCY_CONFIRMED_V1
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
        "decision_id": f"dec-{opp_id}", "slot": f"{at.date().isoformat()}|{market}|{side}", "opportunity_id": opp_id,
        "as_of_utc": _iso(at), "qualification": "QUALIFY" if qualify else "REJECT", "reason": reason,
        "reasons": [] if qualify else [reason], "model_version": "demo", "quote_evidence_ids": [],
        "event_id": "kalshi:DEMO-KXHIGHNY-EVENT", "market_id": market, "side": side,
        "outcome_cluster": "DEMO-NYC-HIGH", "policy_id": "demo",
        "opportunity": {"model_probability": p, "conservative_probability": str(Decimal(p) - Decimal("0.03")),
                        "executable_price": price, "fee": fee, "all_in_cost": cost, "net_edge": edge,
                        "net_edge_conservative": str(Decimal(edge) - Decimal("0.03")), "freshness": "fresh",
                        "fee_status": "UNVERIFIED_CURRENT_SCHEDULE"},
        "sizing": {"final_size": 1, "binding_constraint": "fixed_contracts"} if qualify else None,
        "stage_b_day_status": "VALID", "claimable": False,
    }


def _fill(dec: dict, filled: bool, price: str, fee: str, cost: str, expected: datetime, reason: str = "FILLED") -> dict:
    return {
        "fill_id": f"fill-{dec['opportunity_id']}", "decision_id": dec["decision_id"], "venue": "kalshi",
        "market_id": dec["market_id"], "event_id": dec["event_id"], "outcome_cluster": dec["outcome_cluster"],
        "side": dec["side"], "filled_at_utc": dec["as_of_utc"], "fill_policy_id": LATENCY_CONFIRMED_V1.policy_id,
        "expected_settlement_utc": _iso(expected), "fee_schedule_id": "kalshi-quadratic-taker-v1",
        "status": "FILLED" if filled else "NO_FILL", "reason": reason if not filled else "FILLED",
        "quantity": 1 if filled else 0, "price": price if filled else None, "fee": fee if filled else None,
        "total_cost": cost if filled else None, "detail": "synthetic demo fill",
    }


def _account(ledger: ShadowLedger, account: exp001_shadow.ShadowAccount, now: datetime) -> None:
    ledger.open_account(account.account_id, starting_bankroll=account.starting_bankroll,
                        strategy=f"DEMO {account.strategy}", opened_at_utc=_iso(now - timedelta(days=5)),
                        sizing_policy_id=account.sizing_policy_id,
                        fill_policy_id=LATENCY_CONFIRMED_V1.policy_id, fee_schedule_id="kalshi-quadratic-taker-v1")
    binding = "fixed_contracts" if account.sizing is not None else "frozen_rule"
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
    for dec in (won, unfilled, open_, overdue):
        dec["sizing"]["binding_constraint"] = binding
    for dec in (won, rejected, unfilled, open_, overdue):
        ledger.record_decision(account, dec)
    ledger.record_fill(account, _fill(won, True, "0.34", "0.0158", "0.36", day1 + timedelta(days=2)))
    ledger.record_fill(account, _fill(unfilled, False, "0", "0", "0", day1 + timedelta(days=2),
                                      reason="CONFIRMATION_MISSING"))
    ledger.record_fill(account, _fill(open_, True, "0.24", "0.0128", "0.26", now + timedelta(days=1)))
    ledger.record_fill(account, _fill(overdue, True, "0.80", "0.0112", "0.82", now - timedelta(hours=2)))
    ledger.record_settlement(account, fill_id=f"fill-{won['opportunity_id']}", outcome="YES",
                             settled_at_utc=_iso(now - timedelta(days=1)),
                             evidence={"snapshot_id": None, "note": "synthetic demo settlement"})


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
    status = root / "status"
    status.mkdir()
    (status / d.COLLECTOR_STATUS_FILE).write_text(json.dumps({
        "generated_at_utc": _iso(now - timedelta(hours=1)), "last_closed_target_date": (now - timedelta(days=1))
        .date().isoformat(), "last_closed_status": "VALID", "last_closed_reasons": [], "valid_days": 2,
        "first_valid_day": (now - timedelta(days=3)).date().isoformat(), "days_with_captures": 3,
        "invalid_days": [(now - timedelta(days=2)).date().isoformat()]}), encoding="utf-8")
    last_day = (now - timedelta(hours=20)).date().isoformat()
    per_account = {"decisions": 2, "qualified": 2, "fills": 2, "no_fills": 0, "risk_vetoes": 0}
    fee = exp001_shadow.fee_fields()
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
        "fee": {"schedule_id": fee["fee_schedule_id"], "status": fee["fee_status"], "claimable": fee["claimable"]},
        "accounts": {}, "problems": [], "missing_capture_days": [], "valid_days": 2, "closed_capture_days": 3,
        "latest_day": {"target_date": last_day, "result": "HEALTHY_TRADED", "capture_status": "VALID"}}),
        encoding="utf-8")
    config = d.Config(db=store.path, ledger=ledger.path, status_dir=status, experiments_root=experiments_root, demo=True)
    return config, root
