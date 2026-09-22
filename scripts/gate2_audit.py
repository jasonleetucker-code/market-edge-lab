"""Regenerate the Gate 2 audit tables from the committed evidence fixtures.

    python scripts/gate2_audit.py            # rewrite CSVs + summary JSON
    python scripts/gate2_audit.py --check    # fail if committed files are stale

tests/test_gate2_reproduction.py runs the --check comparison in CI.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge_lab.nws_cli import parse_cli, split_afos_archive  # noqa: E402
from edge_lab.settlement_audit import audit, rows_csv, summarize  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "gate2"
OUT = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market" / "gate2"
WINDOWS = {
    "a": ("kalshi_markets_window_a.json.gz", "iem_clinyc_2026-07-15_2026-09-23.txt.gz", date(2026, 7, 16), date(2026, 9, 21)),
    "b": ("kalshi_markets_window_b.json.gz", "iem_clinyc_2025-01-01_2026-01-03.txt.gz", date(2025, 1, 1), date(2025, 12, 31)),
}


def build() -> dict[str, str]:
    files: dict[str, str] = {}
    summaries = {}
    for name, (markets, cli, start, end) in WINDOWS.items():
        ms = json.loads(gzip.decompress((FIX / markets).read_bytes()))
        text = gzip.decompress((FIX / cli).read_bytes()).decode()
        events, rows = audit(ms, [parse_cli(p) for p in split_afos_archive(text)], start=start, end=end)
        summary = summarize(events, start, end)
        summary["mispredicted_brackets"] = sum(
            1 for r in rows if r.expected_from_nws_cli != "unknown" and not r.match_nws_cli
        )
        summary["events_with_explanations"] = {
            e.event_ticker: e.explanations for e in events if e.explanations
        }
        summaries[f"window_{name}"] = summary
        files[f"audit_window_{name}_brackets.csv"] = rows_csv(rows)
    files["audit_summary.json"] = json.dumps(summaries, indent=2, sort_keys=True) + "\n"
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, content in build().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.write_text(content)
    if stale:
        print("stale Gate 2 audit files (run scripts/gate2_audit.py):", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
