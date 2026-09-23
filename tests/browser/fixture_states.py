"""Fixture states for browser and screenshot tests (UI_CONTRACT.md §23). Never production data.

Each builder writes into a fresh temporary directory through the real ledger, evidence-store
and status-file shapes, and returns a dashboard Config with a fixed clock:

- early: the production-shaped early state from the owner's screenshots (a fresh status report,
  an INVALID last capture, no decisions, both shadow accounts opened with no activity);
- demo: the synthetic populated demo (`edge_lab.dashboard.demo.build_demo`), watermarked;
- broken: malformed and unreadable sources (corrupt JSON, a non-SQLite ledger).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edge_lab import exp001_shadow as shadow
from edge_lab.dashboard import Config
from edge_lab.dashboard.demo import build_demo
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore

REPO = Path(__file__).resolve().parents[2]
# 2026-09-23 14:40 EDT: the moment of the owner's before-state screenshots.
EARLY_NOW = datetime(2026, 9, 23, 18, 40, tzinfo=timezone.utc)


def early(root: Path | None = None) -> tuple[Config, Path]:
    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-early-"))
    status = root / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "latest.json").write_text(json.dumps({
        "generated_at_utc": "2026-09-23T18:28:53.790755+00:00", "last_closed_target_date": "2026-09-23",
        "last_closed_status": "INVALID",
        "last_closed_reasons": ["forecast: no complete pfm capture (a newer issuance may be missing)",
                                "forecast: NO_PFM_BEFORE_CUTOFF", "no complete decision capture"],
        "valid_days": 0, "first_valid_day": None, "days_with_captures": 1, "invalid_days": ["2026-09-23"]}),
        encoding="utf-8")
    ledger = ShadowLedger(root / "shadow_ledger.sqlite3")
    for account in (shadow.RESEARCH, shadow.OPERATIONAL):
        shadow.ensure_account(ledger, account)
    store = SnapshotStore(root / "edge_lab.sqlite3")
    store.start_run("early-run")
    for source, status_word, error in (("kalshi_public", "ok", None), ("nws_pfm_okx", "ok", None)):
        store.record_source_health(run_id="early-run", source_id=source, started_at_utc="2026-09-23T18:28:40+00:00",
                                   completed_at_utc="2026-09-23T18:28:50+00:00", duration_ms=10000,
                                   status=status_word, records=3, error=error)
    store.finish_run("early-run", status="succeeded")
    cfg = Config(db=store.path, ledger=ledger.path, status_dir=status, experiments_root=REPO / "experiments",
                 clock=lambda: EARLY_NOW)
    return cfg, root


def demo() -> tuple[Config, Path]:
    return build_demo(experiments_root=REPO / "experiments")


def broken(root: Path | None = None) -> tuple[Config, Path]:
    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-broken-"))
    status = root / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "latest.json").write_text("{not json", encoding="utf-8")
    (status / "shadow_daily.json").write_text("[1, 2]", encoding="utf-8")
    bad = root / "shadow_ledger.sqlite3"
    bad.write_bytes(b"this is not a sqlite database at all" * 20)
    cfg = Config(ledger=bad, status_dir=status, experiments_root=REPO / "experiments",
                 clock=lambda: EARLY_NOW + timedelta(hours=40))
    return cfg, root


BUILDERS = {"early": early, "demo": demo, "broken": broken}
