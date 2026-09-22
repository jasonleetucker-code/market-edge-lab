"""Build the EXP-001 point-in-time dataset from committed evidence (deterministic).

    python scripts/build_exp001_dataset.py            # write dataset, manifest, QUALITY.md
    python scripts/build_exp001_dataset.py --check    # fail if committed outputs are stale

Inputs (all committed; hashes recorded in the manifest):
  tests/fixtures/gate3/pfm_extracts_YYYY.jsonl.gz    NWS PFMOKX Central Park extracts
  tests/fixtures/gate3/iem_clinyc_YYYY.txt.gz        NWS CLI archives 2017-2023, 2026H1
  tests/fixtures/gate2/iem_clinyc_*.txt.gz           NWS CLI archives 2024-2026
  tests/fixtures/gate3/kalshi_markets_all_2026-09-22.json.gz  captured Kalshi markets
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge_lab.dataset_exp001 import (  # noqa: E402
    Issuance, KalshiEvent, build_rows, manifest, manifest_json, to_csv,
)
from edge_lab.nws_cli import parse_cli, split_afos_archive  # noqa: E402
from edge_lab.nws_pfm import parse_pfm, sha256_text  # noqa: E402
from edge_lab.settlement import read_rules  # noqa: E402
from edge_lab.settlement_audit import event_date, rules_hash, _preferred  # noqa: E402

G2 = ROOT / "tests" / "fixtures" / "gate2"
G3 = ROOT / "tests" / "fixtures" / "gate3"
OUT = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market" / "gate3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_files() -> list[Path]:
    files = sorted(G3.glob("pfm_extracts_*.jsonl.gz")) + sorted(G3.glob("iem_clinyc_*.txt.gz"))
    files += sorted(G2.glob("iem_clinyc_*.txt.gz")) + [G3 / "kalshi_markets_all_2026-09-22.json.gz"]
    files += [G3 / "fetch_manifest.json"]
    return files


def load_issuances() -> tuple[list[Issuance], Counter]:
    stats: Counter = Counter()
    seen: set[str] = set()
    out: list[Issuance] = []
    for path in sorted(G3.glob("pfm_extracts_*.jsonl.gz")):
        for line in gzip.decompress(path.read_bytes()).decode().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            stats["products"] += 1
            if rec["product_sha256"] in seen:
                stats["duplicate_products"] += 1
                continue
            seen.add(rec["product_sha256"])
            if rec["extract"] is None:
                stats["no_central_park_block"] += 1
                continue
            forecast = parse_pfm(rec["extract"])
            if forecast is not None and forecast.correction:
                stats["suffixed_products_never_used"] += 1
                continue
            if forecast is None or forecast.issued_utc is None:
                stats["ambiguous_or_unparsed_issuance_time"] += 1
                continue
            if forecast.unaligned_values:
                stats["products_with_unaligned_values"] += 1
            out.append(Issuance(forecast, rec["product_sha256"], sha256_text(rec["extract"])))
    stats["usable_issuances"] = len(out)
    return out, stats


def load_cli() -> list:
    reports = []
    for path in sorted(G3.glob("iem_clinyc_*.txt.gz")) + sorted(G2.glob("iem_clinyc_*.txt.gz")):
        text = gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")
        reports.extend(parse_cli(p) for p in split_afos_archive(text))
    return reports


def load_kalshi() -> dict[date, KalshiEvent]:
    markets = json.loads(gzip.decompress((G3 / "kalshi_markets_all_2026-09-22.json.gz").read_bytes()))
    by_event: dict[str, dict] = defaultdict(dict)
    for m in markets:
        t = m.get("ticker")
        cur = by_event[m.get("event_ticker") or ""]
        cur[t] = _preferred(cur[t], m) if t in cur else m
    events: dict[date, KalshiEvent] = {}
    for ticker, ms in by_event.items():
        d = event_date(ticker)
        if d is None:
            continue
        values = sorted({m.get("expiration_value") for m in ms.values()} - {None, ""})
        first = ms[sorted(ms, key=str)[0]]
        events[d] = KalshiEvent(
            event_ticker=ticker,
            expiration_value=values[0] if len(values) == 1 else None,
            value_conflict=len(values) > 1,
            rules_source=read_rules(first.get("rules_primary")).source.value,
            rules_hash=rules_hash(first),
        )
    return events


def _pfm_responses() -> int:
    requests = json.loads((G3 / "fetch_manifest.json").read_text())["requests"]
    return sum("pil=PFMOKX" in r["url"] for r in requests)


def _products_by_year() -> dict[str, int]:
    requests = json.loads((G3 / "fetch_manifest.json").read_text())["requests"]
    out: Counter = Counter()
    for r in requests:
        if "pil=PFMOKX" in r["url"]:
            out[r["url"].split("sdate=")[1][:4]] += r["products"]
    return dict(out)


def _span(m) -> int:
    start, end = (date.fromisoformat(d) for d in m["date_range"])
    return (end - start).days + 1


def quality_report(rows, m, pfm_stats) -> str:
    years = Counter(); usable = Counter(); reasons = defaultdict(Counter); leads = Counter()
    labels = Counter(); corrected = 0; rules = Counter(); regimes = Counter(); bases = Counter()
    before = Counter(); both = agree = 0; age_by_year: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        rules[r["rules_source"] or "(no Kalshi event)"] += 1
        regimes[r["contract_regime"]] += 1
        basis = r["nws_cli_basis"]
        bases[basis if ":" not in basis else basis.split(":")[0] + ": " + (
            "first final report with data" if "first final report with data" in basis
            else basis.split(": ", 1)[1].split(":")[0])] += 1
        if r["kalshi_expiration_value"] and r["nws_cli_value_f"] != "":
            both += 1
            agree += int(float(r["kalshi_expiration_value"])) == int(r["nws_cli_value_f"])
        if r["forecast_issued_utc"]:
            gap = datetime.fromisoformat(r["decision_utc"]) - datetime.fromisoformat(r["forecast_issued_utc"])
            before[int(gap.total_seconds() // 3600)] += 1
            age_by_year[r["target_date"][:4]].append(gap.total_seconds() / 3600)
        y = r["target_date"][:4]
        years[y] += 1
        if r["usable"] == "true":
            usable[y] += 1
            leads[int(float(r["forecast_lead_hours"]) // 3 * 3)] += 1
            labels[r["label_source"]] += 1
        else:
            reasons[y][r["exclusion_reason"]] += 1
        corrected += bool(r["forecast_correction"])  # always 0: suffixed products are never used
    lines = [
        "# EXP-001 dataset quality report (generated)",
        "",
        f"Generated by `scripts/build_exp001_dataset.py` (builder v{m['builder_version']}, "
        f"PFM parser v{m['pfm_parser_version']}). Dataset SHA-256 `{m['dataset_sha256']}`.",
        "Counts only: no forecast error or model performance appears in this file.",
        "",
        f"- Candidate days: **{m['rows']}** ({m['date_range'][0]} → {m['date_range'][1]}; "
        f"calendar days in range: {_span(m)}; one row per day by construction)",
        f"- Usable days: **{sum(usable.values())}**; excluded: **{m['rows'] - sum(usable.values())}**",
        f"- Rows by status: `{json.dumps(m['rows_by_status'], sort_keys=True)}`",
        f"- Rows by split/usable: `{json.dumps(m['rows_by_split_usable'], sort_keys=True)}`",
        f"- Label source (usable rows): `{json.dumps(dict(sorted(labels.items())), sort_keys=True)}`",
        f"- Chosen forecasts that were corrected (CCx) products: {corrected}",
        f"- Kalshi `expiration_value` vs NWS CLI contract-rule value, days with both: "
        f"{agree}/{both} equal (unequal days would be excluded as KALSHI_CLI_CONFLICT)",
        f"- Contract regime: `{json.dumps(dict(sorted(regimes.items())), sort_keys=True)}` "
        "(NHIGH rules through 2025-12-09, GLOBALTEMPERATURE from 2025-12-10; Gate 2)",
        f"- Kalshi rules source by row: `{json.dumps(dict(sorted(rules.items())), sort_keys=True)}`. "
        "`unrecognized` = early HIGHNY events (2021-08 → 2022-03) whose rules text names no "
        "source (\"highest temperature recorded in Central Park\"); their label is still Kalshi's "
        "own `expiration_value`.",
        f"- NWS CLI selection basis: `{json.dumps(dict(sorted(bases.items())), sort_keys=True)}`",
        "",
        "## Hours between the chosen issuance and the decision time",
        "",
        "Cutoff is 30 min before the decision; issuances in the last 30 min are never used.",
        "",
        "| Hours before decision | Days |",
        "|---|---|",
        *[f"| {k}–{k + 1} | {v} |" for k, v in sorted(before.items())],
        "",
        "## Forecast issuance regime by year (counts and ages only)",
        "",
        "Hours between the chosen issuance and the decision time, and PFMOKX products archived.",
        "The NWS issued fewer PFMOKX updates from mid-2025, so in the test period the chosen",
        "forecast is typically older at the decision time than in train/validation. A model",
        "fitted on earlier years is scored on older forecasts. This is a known, preregistered",
        "limitation, not something to correct after seeing results.",
        "",
        "| Year | Median age (h) | Share older than 3 h | PFMOKX products |",
        "|---|---|---|---|",
        *[
            f"| {y} | {statistics.median(v):.2f} | {100 * sum(a > 3 for a in v) / len(v):.1f}% | "
            f"{_products_by_year().get(y, 0)} |"
            for y, v in sorted(age_by_year.items())
        ],
        "",
        "## PFM archive",
        "",
        f"Products = every PFMOKX product in the {_pfm_responses()} monthly archive responses "
        "(`tests/fixtures/gate3/fetch_manifest.json`). "
        "Duplicates = identical SHA-256 (the same product archived twice), counted once. "
        "Ambiguous = WMO header time not within 0–15 min after the typed local issuance line; "
        "never used.",
        "",
        "| Item | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(pfm_stats.items())],
        "",
        "## Coverage by year",
        "",
        "| Year | Days | Usable | Excluded (reason: n) |",
        "|---|---|---|---|",
        *[
            f"| {y} | {years[y]} | {usable[y]} | "
            + (", ".join(f"{k}: {v}" for k, v in sorted(reasons[y].items())) or "none")
            + " |"
            for y in sorted(years)
        ],
        "",
        "## Lead time of the chosen forecast (hours from issuance to 00:00 local on D; 3 h bins)",
        "",
        "| Lead bin (h) | Days |",
        "|---|---|",
        *[f"| {k}–{k + 3} | {v} |" for k, v in sorted(leads.items())],
        "",
        "## Excluded days (every one, with reason)",
        "",
        "| Date | Reason | Forecast issued (UTC) | CLI basis |",
        "|---|---|---|---|",
        *[
            f"| {r['target_date']} | {r['exclusion_reason']} | {r['forecast_issued_utc'] or '-'} | {r['nws_cli_basis']} |"
            for r in rows if r["usable"] != "true"
        ],
        "",
    ]
    return "\n".join(lines)


def build() -> dict[str, str]:
    issuances, pfm_stats = load_issuances()
    rows = build_rows(issuances, load_cli(), load_kalshi())
    csv_text = to_csv(rows)
    inputs = {str(p.relative_to(ROOT)): _sha(p) for p in input_files()}
    m = manifest(rows, csv_text, inputs)
    m["pfm_archive_stats"] = dict(sorted(pfm_stats.items()))
    return {
        "dataset.csv": csv_text,
        "dataset_manifest.json": manifest_json(m),
        "QUALITY.md": quality_report(rows, m, pfm_stats),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, content in build().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.write_text(content)
    if stale:
        print("stale EXP-001 dataset outputs (run scripts/build_exp001_dataset.py):", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
