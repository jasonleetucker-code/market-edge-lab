"""Screenshot and layout-audit harness for Market Edge Terminal v1 (UI_CONTRACT.md §23-24).

Development-only: needs Playwright (`pip install playwright && playwright install chromium webkit`).
Serves fixture states from `fixture_states.py` on loopback threads, blocks every request that
does not go to that loopback server, and writes full-page PNGs plus a JSON audit per shot:

    python tests/browser/capture.py --out <dir> [--states early demo] [--pages / /opportunities]
        [--viewports 390x844 1440x900] [--engines chromium webkit] [--text-scale 1.0]

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
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from edge_lab.dashboard import make_app  # noqa: E402
from fixture_states import BUILDERS  # noqa: E402

PAGES = ["/", "/opportunities", "/positions", "/outcome-board", "/risk", "/experiments", "/experiments?tab=sources",
         "/alerts", "/more"]
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
  const first = document.querySelector('.board .mrow, .ws-main .empty');
  const fonts = [...document.fonts].filter(f => f.status === 'loaded').map(f => `${f.family} ${f.weight}`);
  const nav = document.querySelector('.tabbar');
  const navRect = nav && getComputedStyle(nav).display !== 'none' ? nav.getBoundingClientRect() : null;
  return {viewport: vw, overflow, small: small.slice(0, 40), clipped, clippedNumbers: nums,
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
                                                      has_touch=mobile)
                            foreign: list[str] = []
                            ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base)
                                      else (foreign.append(route.request.url), route.abort()))
                            page = ctx.new_page()
                            for path in pages:
                                page.goto(base + path, wait_until="networkidle")
                                if args.text_scale != 1.0:
                                    page.add_style_tag(content=f"html{{font-size:{args.text_scale * 100}%}}")
                                page.evaluate("document.fonts.ready")
                                audit = page.evaluate(AUDIT_JS)
                                name = f"{state}_{engine}_{vp}_{slug(path)}"
                                if not args.no_shots:
                                    page.screenshot(path=str(args.out / f"{name}.png"), full_page=True)
                                    page.screenshot(path=str(args.out / f"{name}_fold.png"), full_page=False)
                                audit.update(state=state, engine=engine, page=path, viewport_name=vp,
                                             foreign_requests=list(foreign))
                                report.append(audit)
                            ctx.close()
                    finally:
                        browser.close()
            finally:
                stop()
    (args.out / "audit.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    bad = [r for r in report if r["overflow"] > 0 or r["clipped"] or r["foreign_requests"] or r["clippedNumbers"]]
    print(f"{len(report)} shots; {len(bad)} with overflow, clipping or foreign requests")
    for r in bad:
        print(" ", r["state"], r["engine"], r["viewport_name"], r["page"], "overflow", r["overflow"],
              "clipped", r["clipped"][:3], "foreign", r["foreign_requests"][:2], "nums", r["clippedNumbers"][:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
