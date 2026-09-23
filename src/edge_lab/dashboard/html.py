"""HTML building blocks. Every dynamic value passes through `esc` (html.escape, quotes too).

Missing values render as an explicit "—" marked `unknown`, never as 0.
"""

from __future__ import annotations

import html
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

NAV = (
    ("/", "Overview"),
    ("/opportunities", "Opportunities"),
    ("/positions", "Positions"),
    ("/outcome-board", "Outcome Board"),
    ("/risk", "Risk & capital"),
    ("/experiments", "Experiments & sources"),
)

CSS = """
:root{--bg:#f6f7f9;--fg:#15181d;--muted:#5b6270;--card:#fff;--line:#d9dde3;--warn:#8a5a00;--warnbg:#fff4d6;
--err:#8f1d1d;--errbg:#fde8e8;--ok:#1d6b35;--okbg:#e5f5ea;--nd:#3c4a5c;--ndbg:#e9eef5;--banner:#6b0f0f}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e8eaee;--muted:#9aa3b2;--card:#1a1e24;--line:#2d333c;
--warn:#f2c46b;--warnbg:#3a2e10;--err:#f3a3a3;--errbg:#3d1717;--ok:#8fd6a5;--okbg:#14301d;--nd:#b8c4d6;
--ndbg:#1f2733;--banner:#b32222}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.banner{background:var(--banner);color:#fff;text-align:center;font-weight:800;letter-spacing:.06em;padding:10px 16px;
font-size:18px}
.demo{background:repeating-linear-gradient(45deg,#ffd400,#ffd400 18px,#111 18px,#111 36px);padding:6px}
.demo span{display:block;background:#ffd400;color:#111;text-align:center;font-weight:900;font-size:22px;padding:8px}
nav{display:flex;flex-wrap:wrap;gap:4px;padding:8px 16px;background:var(--card);border-bottom:1px solid var(--line)}
nav a{padding:6px 10px;border-radius:6px;color:var(--fg);text-decoration:none}
nav a.on{background:var(--ndbg);font-weight:700}
main{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:4px 0 12px}h2{font-size:18px;margin:0 0 8px}h3{font-size:15px;margin:12px 0 6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px;
min-width:0}
.panel.nodata{background:var(--ndbg);color:var(--nd)}.panel.error{background:var(--errbg);color:var(--err)}
.panel.stale{border:2px solid var(--warn)}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:700;border:1px solid}
.tag.ok{color:var(--ok);background:var(--okbg)}.tag.warn{color:var(--warn);background:var(--warnbg)}
.tag.err{color:var(--err);background:var(--errbg)}.tag.nd{color:var(--nd);background:var(--ndbg)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top;white-space:nowrap}
td.wrap{white-space:normal;min-width:180px}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;margin:0}dl.kv dt{color:var(--muted)}
dl.kv dd{margin:0;overflow-wrap:anywhere}
.na{color:var(--muted)}.note{color:var(--muted);font-size:13px}
ul.tight{margin:4px 0;padding-left:20px}
footer{max-width:1180px;margin:0 auto;padding:8px 16px 24px;color:var(--muted);font-size:12px}
@media (max-width:640px){main{padding:10px}.grid{grid-template-columns:1fr}.banner{font-size:16px}
dl.kv{grid-template-columns:1fr}dl.kv dt{margin-top:4px}nav a{padding:6px 8px}}
"""

UNKNOWN = '<span class="na" title="unknown / not recorded">—</span>'


def esc(value: Any) -> str:
    """Escape any value for HTML text or attribute context. None -> the explicit unknown marker."""
    if value is None:
        return UNKNOWN
    if isinstance(value, bool):
        return "yes" if value else "no"
    return html.escape(str(value), quote=True)


def money(value: Any) -> str:
    """A dollar figure from a Decimal or decimal string; exact, never rounded here."""
    if value is None:
        return UNKNOWN
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return esc(value)
    return esc(f"-${-d}" if d < 0 else f"${d}")


def age(delta: timedelta | None) -> str:
    if delta is None:
        return UNKNOWN
    seconds = int(delta.total_seconds())
    sign, seconds = ("in the future: ", -seconds) if seconds < 0 else ("", seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = ([f"{days} d"] if days else []) + ([f"{hours} h"] if hours or days else []) + [f"{minutes} min"]
    return esc(sign + " ".join(parts))


def tag(text: str, kind: str = "nd") -> str:
    return f'<span class="tag {esc(kind)}">{esc(text)}</span>'


def state_tag(value: Any) -> str:
    """Colour a status word by meaning. Unknown words are neutral, never green."""
    text = "UNKNOWN" if value is None else str(value)
    good = {"OK", "FRESH", "VALID", "HEALTHY_NO_SIGNAL", "HEALTHY_TRADED", "SETTLED", "FILLED", "QUALIFY", "PASS",
            "ok", "RUNNING", "CONCLUDED_PASS", "VERIFIED"}
    bad = {"ERROR", "STALE", "INVALID", "INVALID_CAPTURE", "FAILED", "failed", "REJECT", "NO_FILL", "LOCK_BUSY",
           "CONCLUDED_FAIL", "BREACH", "NOT_RECOMMENDED", "UNVERIFIED_CURRENT_SCHEDULE", "overdue", "FAIL"}
    kind = "ok" if text in good else "err" if text in bad else "warn" if text in {
        "PENDING_SETTLEMENT", "NOT_CLOSED", "partial", "UNKNOWN", "OPEN", "PARTIALLY_SETTLED"} else "nd"
    return tag(text, kind)


def kv(pairs: Iterable[tuple[str, str]]) -> str:
    """Pairs of (label, already-escaped HTML)."""
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in pairs) + "</dl>"


def table(headers: Iterable[str], rows: Iterable[Iterable[str]], wrap: Iterable[int] = ()) -> str:
    """Cells are already-escaped HTML. Wrapped in a horizontal scroll container."""
    wrap = set(wrap)
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f'<td{" class=wrap" if i in wrap else ""}>{c}</td>' for i, c in enumerate(r))
                   + "</tr>" for r in rows)
    if not body:
        return '<p class="na">none recorded</p>'
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def ul(items: Iterable[Any]) -> str:
    items = list(items)
    if not items:
        return '<p class="na">none</p>'
    return '<ul class="tight">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def panel(title: str, body: str, kind: str = "") -> str:
    return f'<section class="panel {esc(kind)}"><h2>{esc(title)}</h2>{body}</section>'


def no_data(title: str, message: str) -> str:
    return panel(title, f"<p>{tag('NO DATA / NOT STARTED', 'nd')}</p><p>{esc(message)}</p>", "nodata")


def error(title: str, message: str) -> str:
    return panel(title, f"<p>{tag('ERROR', 'err')}</p><p>{esc(message)}</p>", "error")


def page(title: str, path: str, body: str, *, demo: bool, generated_at: str) -> str:
    nav = "".join(f'<a href="{esc(href)}"{" class=on" if href == path else ""}>{esc(label)}</a>'
                  for href, label in NAV)
    watermark = ('<div class="demo"><span>SYNTHETIC DEMO DATA — NOT REAL, NOT FROM ANY LEDGER OR COLLECTOR'
                 '</span></div>') if demo else ""
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{esc(title)} · edge-lab shadow dashboard</title><style>{CSS}</style></head><body>"
        '<div class="banner" role="banner">SHADOW — NO REAL MONEY</div>'
        f"{watermark}<nav>{nav}</nav><main><h1>{esc(title)}</h1>{body}</main>"
        f"<footer>Read-only local view. Rendered {esc(generated_at)}. "
        "— marks an unknown or unrecorded value (never zero). All balances are simulated.</footer>"
        f"{watermark}</body></html>"
    )
