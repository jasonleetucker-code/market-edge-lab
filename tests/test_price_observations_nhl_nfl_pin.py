"""NHL-B before/after pin: the Kalshi NFL pairing's output is byte-identical after the per-series generalization.

The golden file (`tests/fixtures/sports_nhl/nfl_pin_golden.json`) was generated from origin/main b944a0e, BEFORE
any NHL-B change to `price_observations` (commit "NHL-B: pin the NFL pairing output before the generalization").
The scenario drives the real `run_plan` / `run_capture` path offline through a whole NFL game day (T-24h, T-6h with
a failed listing and the protected-window miss, T-60m, the settled read, the kill switch, an EXP-001 close run) and
records every report, every target and observation row, `status` and `market_history`. Only uuid-derived ids are
normalized. Regenerate only for a reviewed, intended NFL change: `EDGE_LAB_REGEN_NFL_PIN=1 python -m pytest <this>`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edge_lab import price_observations as po
from edge_lab.http import HttpFetchError
from edge_lab.storage import SnapshotStore
from test_forward import MARKETS, Clock
from test_price_observations_nfl import (ARI_NYG, DEN_SF, EVENTS, ON, OFF, Api, _close_target, odds_captured,
                                         odds_schedule, routes)

UTC = timezone.utc
GOLDEN = Path(__file__).parent / "fixtures" / "sports_nhl" / "nfl_pin_golden.json"
_RUN = re.compile(r"observe-(plan|capture)-[0-9a-f-]{36}")
_HEX = re.compile(r":[0-9a-f]{12}$")


def _norm(value, runs: dict[str, str]):
    if isinstance(value, dict):
        return {k: _norm(v, runs) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_norm(v, runs) for v in value]
    if isinstance(value, str):
        def sub(m):
            return runs.setdefault(m.group(0), f"run-{len(runs)}")
        value = _RUN.sub(sub, value)
        return _HEX.sub(":<attempt>", value) if value.startswith("run-") else value
    return value


def _rows(store: SnapshotStore) -> dict:
    targets = [dict(t) for t in store.price_targets()]
    obs = [dict(r) for r in store.price_observations()]
    return {"targets": targets, "observations": obs}


def nfl_scenario(tmp_path: Path, monkeypatch) -> dict:
    out: dict = {}
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    ids = odds_schedule(store, ARI_NYG, DEN_SF, planned_at=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))

    def step(name, fn):
        out[name] = fn()

    # T-24h (Saturday 13:00 ET): both games captured by the Odds tick, paired at 13:05 ET.
    t24 = datetime(2026, 10, 3, 17, 0, 4, tzinfo=UTC)
    for g in (ARI_NYG, DEN_SF):
        odds_captured(store, ids[(g.event_id, "T-24h")], t24)
    step("plan_t24", lambda: po.run_plan(store.path, None, now=datetime(2026, 10, 3, 17, 5, tzinfo=UTC), environ=ON))
    clock = Clock(datetime(2026, 10, 3, 17, 5, 20, tzinfo=UTC))
    api = Api(clock, routes("KXNFLGAME-26OCT04ARINYG", "KXNFLGAME-26OCT04DENSF"))
    monkeypatch.setattr(po, "fetch_json_result", api)
    step("capture_t24", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=ON))
    # T-6h of ARI@NYG (07:00 ET): the listing fails; the retry tick falls in no protected window here.
    t6 = datetime(2026, 10, 4, 11, 0, 4, tzinfo=UTC)
    odds_captured(store, ids[(ARI_NYG.event_id, "T-6h")], t6)
    step("plan_t6", lambda: po.run_plan(store.path, None, now=datetime(2026, 10, 4, 11, 5, tzinfo=UTC), environ=ON))
    clock.now = datetime(2026, 10, 4, 11, 5, 20, tzinfo=UTC)
    api.routes = {**routes("KXNFLGAME-26OCT04DENSF"),
                  "/markets?event_ticker=KXNFLGAME-26OCT04ARINYG&": HttpFetchError("HTTP 503", status=503, attempts=1)}
    step("capture_t6_fail", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=ON))
    clock.now = datetime(2026, 10, 4, 11, 20, 20, tzinfo=UTC)  # 07:20 ET: not protected
    api.routes = routes("KXNFLGAME-26OCT04ARINYG")
    step("capture_t6_retry", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=ON))
    # T-60m of ARI@NYG (12:00 ET).
    t1 = datetime(2026, 10, 4, 16, 0, 4, tzinfo=UTC)
    odds_captured(store, ids[(ARI_NYG.event_id, "T-60m")], t1)
    step("plan_t60", lambda: po.run_plan(store.path, None, now=datetime(2026, 10, 4, 16, 5, tzinfo=UTC), environ=ON))
    clock.now = datetime(2026, 10, 4, 16, 5, 20, tzinfo=UTC)
    step("capture_t60", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=ON))
    # DEN@SF T-60m captured by the Odds pilot, planned, then the kill switch holds it.
    t1b = datetime(2026, 10, 4, 19, 25, 4, tzinfo=UTC)
    odds_captured(store, ids[(DEN_SF.event_id, "T-60m")], t1b)
    step("plan_t60b", lambda: po.run_plan(store.path, None, now=datetime(2026, 10, 4, 19, 35, tzinfo=UTC),
                                          environ=ON))
    clock.now = datetime(2026, 10, 4, 19, 35, 20, tzinfo=UTC)
    step("capture_off", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=OFF))
    step("plan_off", lambda: po.run_plan(store.path, None, now=datetime(2026, 10, 4, 19, 50, tzinfo=UTC),
                                         environ=OFF))
    # The game day's settled-markets read (last kickoff 16:25 ET + 6 h 30 min -> the 23:05 ET tick).
    tick = datetime(2026, 10, 5, 3, 5, tzinfo=UTC)
    step("plan_settle", lambda: po.run_plan(store.path, None, now=tick - timedelta(minutes=10), environ=ON))
    settled = {"cursor": "", "markets": [{**m, "status": "finalized"}
                                         for m in EVENTS["KXNFLGAME-26OCT04ARINYG"]["markets"]]}
    clock.now = tick + timedelta(seconds=10)
    api.routes = routes(settled=settled)
    step("capture_settle", lambda: po.run_capture(store.path, clock=clock, sleep=clock.sleep, environ=ON))
    step("status", lambda: po.status(SnapshotStore.open_readonly(store.path), now=tick + timedelta(minutes=1),
                                     systemctl=lambda args: "enabled"))
    step("history_book", lambda: po.market_history(store, "kalshi:KXNFLGAME-26OCT04ARINYG-ARI"))
    step("history_settled", lambda: po.market_history(store, "kalshi:KXNFLGAME"))
    step("dry_run", lambda: po.nfl_dry_run(store.path, now=tick))
    step("rows", lambda: _rows(store))
    step("calls", lambda: list(api.calls))

    # An EXP-001 close run keeps the whole run: the NFL pair waits (second store).
    store2 = SnapshotStore(tmp_path / "close.sqlite3")
    at = datetime(2026, 9, 24, 4, 55, 1, tzinfo=UTC)
    ids2 = odds_schedule(store2, ARI_NYG, planned_at=at - timedelta(days=2))
    odds_captured(store2, ids2[(ARI_NYG.event_id, "T-6h")], at)
    step("close_plan", lambda: po.run_plan(store2.path, None, now=at + timedelta(minutes=1), environ=ON))
    _close_target(store2, datetime(2026, 9, 24, 5, 0, tzinfo=UTC))
    clock2 = Clock(datetime(2026, 9, 24, 4, 57, 45, tzinfo=UTC))
    api2 = Api(clock2, {**routes("KXNFLGAME-26OCT04ARINYG"), "/markets?event_ticker=KXHIGHNY-26SEP23": MARKETS})
    monkeypatch.setattr(po, "fetch_json_result", api2)
    step("close_capture", lambda: po.run_capture(store2.path, clock=clock2, sleep=clock2.sleep, max_requests=3,
                                                 environ=ON))
    clock2.now = datetime(2026, 9, 24, 5, 5, 5, tzinfo=UTC)
    step("close_next", lambda: po.run_capture(store2.path, clock=clock2, sleep=clock2.sleep, environ=ON))
    step("close_rows", lambda: _rows(store2))
    step("close_calls", lambda: list(api2.calls))
    return json.loads(json.dumps(_norm(out, {}), default=str))


def test_nfl_pairing_output_is_byte_identical_to_the_pre_nhl_golden(tmp_path, monkeypatch):
    got = nfl_scenario(tmp_path, monkeypatch)
    text = json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("EDGE_LAB_REGEN_NFL_PIN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    golden = GOLDEN.read_text(encoding="utf-8")
    assert text == golden
