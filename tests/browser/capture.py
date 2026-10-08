"""Screenshot and layout-audit harness for Market Edge Terminal v1 (UI_CONTRACT.md §23-24).

Development-only: needs Playwright (`pip install playwright && playwright install chromium webkit`).
Serves fixture states from `fixture_states.py` on loopback threads, blocks every request that
does not go to that loopback server, and writes full-page PNGs plus a JSON audit per shot:

    python tests/browser/capture.py --out <dir> [--states early demo] [--pages / /opportunities]
        [--viewports 390x844 1440x900] [--engines chromium webkit] [--text-scale 1.0] [--open-details]

The audit records body-level horizontal overflow, clipped or undersized interactive targets,
whether the IBM Plex faces actually loaded, the top of the first market row, and any request
to a host other than the fixture server. It is evidence for review, not a verdict on beauty.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

HERE = Path(__file__).resolve().parent
# `--src DIR` renders the same fixtures with another checkout's code (before/after evidence).
_SRC = sys.argv[sys.argv.index("--src") + 1] if "--src" in sys.argv else str(HERE.parents[1] / "src")
sys.path[:0] = [_SRC, str(HERE)]

from edge_lab.dashboard import make_app  # noqa: E402
from fixture_states import BUILDERS  # noqa: E402

PAGES = ["/", "/opportunities", "/positions", "/outcome-board", "/risk", "/experiments", "/experiments?tab=sources",
         "/alerts", "/more", "/setup", "/experiments/wallet", "/positions/execution", "/risk/automation"]
DETAIL = {"demo": "/market?venue=kalshi&id=DEMO-B67.5&side=YES"}
VIEWPORTS = ["360x800", "390x844", "430x932", "768x1024", "1440x900", "1920x1080"]

AUDIT_JS = r"""
() => {
  const doc = document.documentElement;
  const vw = doc.clientWidth;
  const overflow = Math.max(doc.scrollWidth, document.body.scrollWidth) - vw;
  const small = [];
  const clipped = [];
  for (const el of document.querySelectorAll('a[href], button, summary, input, select')) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || style.visibility === 'hidden') continue;
    if (el.closest('.sr, .sprite, .skip')) continue;
    const inText = el.closest('p, li.row .row-sub, .note, .statusline-detail, .empty-text, dd, td') && el.tagName === 'A'
      && !el.classList.contains('btn') && !el.classList.contains('qt');
    if (!inText && (r.height < 44 || r.width < 44) && !el.closest('.scroll')) {
      small.push({tag: el.tagName, text: (el.innerText || el.getAttribute('aria-label') || '').slice(0, 40),
                  w: Math.round(r.width), h: Math.round(r.height)});
    }
    if (r.right > vw + 1 && !el.closest('.tape-track, .tabs, .scroll')) {
      clipped.push({tag: el.tagName, text: (el.innerText || '').slice(0, 40), right: Math.round(r.right)});
    }
  }
  const nums = [];
  for (const el of document.querySelectorAll('.num, .qt-price, .summary-primary')) {
    if (el.closest('.scroll, .tape-track, .sr')) continue;
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible') {
      nums.push((el.innerText || '').slice(0, 30));
    }
  }
  // Rendered contrast: each element with its own text, against the nearest opaque background.
  const rgb = s => (s.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
  const bgOf = el => { for (let n = el; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor);
    if (c.length >= 3 && (c.length < 4 || c[3] > 0.99)) return c; } return [16, 18, 20]; };
  const lowContrast = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.sr, .sprite, svg') || !el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const st = getComputedStyle(el);
    const fg = rgb(st.color), bg = bgOf(el);
    const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (l1 + 0.05) / (l2 + 0.05);
    const size = parseFloat(st.fontSize), bold = parseInt(st.fontWeight) >= 600;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    if (ratio < need) lowContrast.push({text: el.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100});
  }
  const first = document.querySelector('.board .mrow, .ws-main .empty');
  const fonts = [...document.fonts].filter(f => f.status === 'loaded').map(f => `${f.family} ${f.weight}`);
  const nav = document.querySelector('.tabbar');
  const navRect = nav && getComputedStyle(nav).display !== 'none' ? nav.getBoundingClientRect() : null;
  return {viewport: vw, overflow, small: small.slice(0, 40), clipped, clippedNumbers: nums,
          lowContrast: lowContrast.slice(0, 20),
          firstRowTop: first ? Math.round(first.getBoundingClientRect().top + window.scrollY) : null,
          fontsLoaded: fonts, tabbarHeight: navRect ? Math.round(navRect.height) : null,
          docHeight: doc.scrollHeight, title: document.title};
}
"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(state: str) -> tuple[str, callable]:
    cfg, root = BUILDERS[state]()
    server = make_server("127.0.0.1", 0, make_app(cfg), handler_class=_Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop() -> None:
        server.shutdown()
        server.server_close()
        shutil.rmtree(root, ignore_errors=True)
    return f"http://127.0.0.1:{server.server_port}", stop


def slug(path: str) -> str:
    return (path.strip("/").replace("?", "_").replace("=", "-").replace("&", "_").replace("/", "_") or "terminal")


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--states", nargs="+", default=["early", "demo"])
    ap.add_argument("--pages", nargs="+", default=None)
    ap.add_argument("--viewports", nargs="+", default=VIEWPORTS)
    ap.add_argument("--engines", nargs="+", default=["chromium"])
    ap.add_argument("--text-scale", type=float, default=1.0, help="root font-size multiplier (enlarged text)")
    ap.add_argument("--no-shots", action="store_true", help="audit only")
    ap.add_argument("--open-details", action="store_true",
                    help="open every <details> disclosure before the audit and screenshot (reviews the tables inside)")
    ap.add_argument("--src", help="source tree to import edge_lab from (default: this checkout)")
    ap.add_argument("--jpeg", action="store_true", help="write JPEG (quality 82) instead of PNG")
    ap.add_argument("--color-scheme", choices=("light", "dark"), default="dark",
                    help="emulated OS preference (Terminal v1 ignores it; the pre-v1 dashboard followed it)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    with sync_playwright() as pw:
        for state in args.states:
            base, stop = serve(state)
            pages = list(args.pages or PAGES)
            if args.pages is None and state in DETAIL:
                pages.append(DETAIL[state])
            try:
                for engine in args.engines:
                    browser = getattr(pw, engine).launch()
                    try:
                        for vp in args.viewports:
                            w, h = (int(x) for x in vp.split("x"))
                            mobile = w < 768
                            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if
                                                      mobile else 1, is_mobile=mobile and engine == "chromium",
                                                      has_touch=mobile, color_scheme=args.color_scheme,
                                                      # the enlarged-text style tag is inline, which the
                                                      # app's CSP (correctly) refuses; bypass it for that only
                                                      bypass_csp=args.text_scale != 1.0)
                            foreign: list[str] = []
                            ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base)
                                      else (foreign.append(route.request.url), route.abort()))
                            page = ctx.new_page()
                            for path in pages:
                                page.goto(base + path, wait_until="networkidle")
                                if args.text_scale != 1.0:
                                    page.add_style_tag(content=f"html{{font-size:{args.text_scale * 100}%}}")
                                if args.open_details:
                                    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                                page.evaluate("document.fonts.ready")
                                audit = page.evaluate(AUDIT_JS)
                                name = f"{state}_{engine}_{vp}_{slug(path)}"
                                if not args.no_shots:
                                    ext, opts = (".jpg", {"type": "jpeg", "quality": 82}) if args.jpeg else (".png", {})
                                    page.screenshot(path=str(args.out / f"{name}{ext}"), full_page=True, **opts)
                                    page.screenshot(path=str(args.out / f"{name}_fold{ext}"), full_page=False, **opts)
                                audit.update(state=state, engine=engine, page=path, viewport_name=vp,
                                             foreign_requests=list(foreign))
                                report.append(audit)
                            ctx.close()
                    finally:
                        browser.close()
            finally:
                stop()
    (args.out / "audit.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    bad = [r for r in report if r["overflow"] > 0 or r["clipped"] or r["foreign_requests"] or r["clippedNumbers"]
           or r["lowContrast"]]
    print(f"{len(report)} shots; {len(bad)} with overflow, clipping, low contrast or foreign requests")
    for r in bad:
        print(" ", r["state"], r["engine"], r["viewport_name"], r["page"], "overflow", r["overflow"],
              "clipped", r["clipped"][:3], "foreign", r["foreign_requests"][:2], "nums", r["clippedNumbers"][:3],
              "contrast", r["lowContrast"][:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
