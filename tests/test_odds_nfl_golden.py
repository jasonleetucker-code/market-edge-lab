"""NFL byte-identity pin for the sport-aware planner (ADR 0039).

The golden file was generated from origin/main b944a0e, BEFORE the planner became sport-aware
(`EDGE_LAB_WRITE_ODDS_GOLDEN=1 python -m pytest tests/test_odds_nfl_golden.py`). The same scenario
must produce the same bytes after: the same slots, the same monthly proofs, the same tick reports,
the same plan report and the same stored target history. Fixtures only; no network, no credits."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path

from edge_lab import odds_pilot as op
from edge_lab import odds_schedule as sch
from edge_lab.odds_schedule import QuotaReading
from edge_lab.storage import SnapshotStore

import test_odds_pilot as tp
from test_odds_schedule import WEEK, nfl_week, utc

GOLDEN = Path(__file__).parent / "fixtures" / "odds_api" / "nfl_planner_golden_b944a0e.json"


def _proofs() -> list[dict]:
    """Pure planner: slots and budget() over several months, clocks and quota readings."""
    events = WEEK + nfl_week(utc(2026, 10, 8)) + nfl_week(utc(2026, 10, 29), london=False)
    out: list = []
    for now in (utc(2026, 9, 29, 17, 20), utc(2026, 10, 1, 12), utc(2026, 10, 4, 15, 55), utc(2026, 10, 30, 3)):
        targets = [t for t in sch.plan_targets(events) if not sch.is_expired(t, now)]
        slots = sch.coalesce(targets)
        horizon = max(e.commence_utc for e in events)
        out.append({"now": sch.iso_z(now), "slots": [[s.slot_id, sch.iso_z(s.due_utc), s.priority,
                                                     [m.target_id for m in s.members]] for s in slots]})
        for quota in (QuotaReading("QUOTA_UNKNOWN"),
                      QuotaReading("READY", local_used=45, provider_used=45, provider_remaining=455),
                      QuotaReading("READY", local_used=300, provider_used=301, provider_remaining=199, outstanding=3),
                      QuotaReading("READY", local_used=440, provider_used=440, provider_remaining=60),
                      QuotaReading("QUOTA_EXHAUSTED", local_used=450, provider_used=450, provider_remaining=50)):
            for known in (horizon, None, utc(2026, 10, 6)):
                proof = sch.budget(slots, now=now, quota=quota, cost_per_call=3, known_horizon=known)
                out.append({"now": sch.iso_z(now), "quota": quota.__dict__,
                            "known": None if known is None else sch.iso_z(known), "proof": proof.to_dict()})
    return out


# The fake transport stamps receipts with the real clock; everything derived from that is not part of the pin.
_WALL_CLOCK_KEYS = ("received_at_utc", "fetched_at_utc", "deviation_minutes", "lead_minutes")


def _drop_wall_clock(value):
    if isinstance(value, dict):
        return {k: _drop_wall_clock(v) for k, v in value.items() if k not in _WALL_CLOCK_KEYS}
    if isinstance(value, list):
        return [_drop_wall_clock(v) for v in value]
    return value


def _ticks(tmp: Path) -> dict:
    """The runner: a week of ticks against the scripted provider, then an offline plan."""
    paths = (tmp / "edge.sqlite3", tmp / "odds_quota.json")
    provider = tp.Provider()
    reports = []
    at = utc(2026, 10, 1, 12, 0)
    while at < utc(2026, 10, 6, 1, 0):
        code, report = tp.tick(paths, provider, at)
        reports.append([code, _drop_wall_clock(report)])
        at += timedelta(minutes=15 if at.hour in (15, 16, 17, 20, 21, 22, 23, 0) else 60)
    code, plan = op.plan(paths[0], paths[1], op.RunnerSettings(), offline=True, clock=tp.Clock(utc(2026, 10, 5, 12)))
    plan = _drop_wall_clock(plan)
    store = SnapshotStore(paths[0])
    history = {r["target_id"]: [[x["state"], x["at_utc"], x["reason"], x["slot_id"], x["captured_at_utc"] is not None,
                                 x["credits_last"], _drop_wall_clock(json.loads(x["detail_json"]))]
                                for x in store.odds_transitions(r["target_id"])]
               for r in store.odds_targets(sport=tp.SPORT)}
    return {"reports": reports, "plan": [code, plan], "history": history, "calls": provider.calls}


def _scenario(tmp: Path) -> str:
    """One JSON document per line, so a failure diffs to the item that changed."""
    runner = _ticks(tmp)
    lines = [json.dumps(x, sort_keys=True, default=str) for x in _proofs()]
    lines += [json.dumps(x, sort_keys=True, default=str) for x in runner["reports"]]
    lines += [json.dumps({k: runner[k]}, sort_keys=True, default=str) for k in ("plan", "history", "calls")]
    return "\n".join(lines) + "\n"


def test_nfl_planner_output_is_byte_identical_to_main(tmp_path):
    text = _scenario(tmp_path)
    if os.environ.get("EDGE_LAB_WRITE_ODDS_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    golden = GOLDEN.read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode()).hexdigest() == hashlib.sha256(golden.encode()).hexdigest()
    assert text == golden
