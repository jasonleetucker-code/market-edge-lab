"""One-time, read-only fetch of Gate 3 evidence from the IEM AFOS archive (free, public).

    python scripts/fetch_gate3_evidence.py --out tests/fixtures/gate3 --user-agent "..."

- PFMOKX (NWS point forecasts), month by month, 2016-12-01 .. 2026-09-22. Full products
  are large (~12 MB/month), so each product is hashed (SHA-256 of its exact text) and only
  an exact-substring extract of the Central Park lines is kept (docs/decisions/0011).
- CLINYC (Daily Climate Report) for 2016-12-31 .. 2024-01-03, exact archive bytes
  (2024 onwards is already a Gate 2 fixture).

Every request URL, HTTP status, byte length and SHA-256 goes into fetch_manifest.json.
Requests are paced at >= 1 s (IEM's stated courtesy limit). Not a scheduled job.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge_lab.http import Pacer, fetch  # noqa: E402
from edge_lab.nws_pfm import extract, split_products  # noqa: E402

IEM = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
PACER = Pacer(1.5)


def url(pil: str, start: date, end: date) -> str:
    return f"{IEM}?pil={pil}&sdate={start.isoformat()}&edate={end.isoformat()}&fmt=text&limit=9999"


def months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) < end:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        yield date(y, m, 1), min(nxt, end)
        y, m = nxt.year, nxt.month


def get(u: str, ua: str):
    result = fetch(u, headers={"User-Agent": ua, "Accept": "text/plain"}, timeout=120, retries=3, pacer=PACER)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tests" / "fixtures" / "gate3"))
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--pfm-from", default="2016-12-01")
    ap.add_argument("--pfm-to", default="2026-09-22")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "fetch_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"requests": []}
    done = {r["url"] for r in manifest["requests"]}

    by_year: dict[int, list[dict]] = {}
    for start, end in months(date.fromisoformat(args.pfm_from), date.fromisoformat(args.pfm_to)):
        u = url("PFMOKX", start, end)
        part = out / "raw_parts" / f"pfm_{start:%Y%m}.jsonl"
        if u in done and part.exists():
            continue
        r = get(u, args.user_agent)
        text = r.body.decode("utf-8", errors="replace")
        products = split_products(text)
        records = []
        for p in products:
            ex = extract(p)
            records.append({
                "product_sha256": hashlib.sha256(p.encode("utf-8")).hexdigest(),
                "product_chars": len(p),
                "extract": ex,  # None when the Central Park block is absent
            })
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_text("\n".join(json.dumps(x, sort_keys=True) for x in records) + "\n")
        manifest["requests"].append({
            "url": u, "http_status": r.http_status, "bytes": len(r.body),
            "sha256": hashlib.sha256(r.body).hexdigest(), "fetched_at_utc": r.received_at_utc,
            "products": len(products), "retry_reasons": list(r.retry_reasons),
        })
        manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        print(f"{start:%Y-%m}: {len(products)} products, {len(r.body)} bytes", flush=True)

    for year in range(2016, 2024):
        start, end = (date(2016, 12, 31) if year == 2016 else date(year, 1, 1)), date(year + 1, 1, 3)
        if year == 2016:
            continue
        u = url("CLINYC", date(year - 1, 12, 31) if year == 2017 else date(year, 1, 1), end)
        target = out / f"iem_clinyc_{year}.txt.gz"
        if u in done and target.exists():
            continue
        r = get(u, args.user_agent)
        with gzip.GzipFile(target, "wb", mtime=0) as fh:
            fh.write(r.body)
        manifest["requests"].append({
            "url": u, "http_status": r.http_status, "bytes": len(r.body),
            "sha256": hashlib.sha256(r.body).hexdigest(), "fetched_at_utc": r.received_at_utc,
            "retry_reasons": list(r.retry_reasons),
        })
        manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        print(f"CLI {year}: {len(r.body)} bytes", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
