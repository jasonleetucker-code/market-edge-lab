"""KXNFLGAME fees stay FEE_UNSUPPORTED (owner directive 2026-09-28 §9; docs/research/EXP002_FEE_VERIFICATION.md).

The public documents do not resolve the series' fee semantics, so no verification record exists for it, the
routing never prices it and nothing sets it to zero. The committed document captures match their manifest.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import fee_schedules as fs
from edge_lab import sports_evidence as se

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments" / "EXP-002-nfl-consensus-vs-event-market" / "fee_evidence"


def test_kxnflgame_is_unsupported_and_never_priced():
    schedule = fs.schedule_for("kalshi", "KXNFLGAME")
    assert isinstance(schedule, fs.UnsupportedFeeSchedule)
    assert schedule.status is fs.FeeScheduleStatus.UNSUPPORTED
    with pytest.raises(ValueError):
        schedule.taker_buy(10, Decimal("0.50"))  # never a zero fee, never a price
    assert isinstance(se.fee_schedule(), fs.UnsupportedFeeSchedule)


def test_no_verification_record_covers_kxnflgame():
    assert not [r for r in fs.FEE_VERIFICATIONS if "KXNFLGAME" in r.scope]


def test_the_fee_evidence_manifest_matches_the_committed_captures():
    manifest = json.loads((EVIDENCE / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["verdict"].startswith("NOT RESOLVED")
    committed = [f for f in manifest["files"] if f["committed"]]
    assert committed
    for f in committed:
        assert hashlib.sha256((EVIDENCE / f["file"]).read_bytes()).hexdigest() == f["sha256"], f["file"]
    assert {p.name for p in EVIDENCE.iterdir()} == {f["file"] for f in committed} | {"MANIFEST.json"}
