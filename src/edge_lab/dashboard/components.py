"""Reusable, escaped HTML components for Market Edge Terminal v1 (docs/design/COMPONENTS.md).

Every dynamic value passes through `esc`. Components take presentation values (see
`presentation.py`) and never compute a financial figure. A missing value renders as the
explicit unavailable marker with accessible text, never as zero.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode

from . import presentation as pr
from .html import esc

# --------------------------------------------------------------------------- primitives


def icon(name: str, cls: str = "", label: str | None = None) -> str:
    """A sprite icon. Decorative unless `label` is given (then it has accessible text)."""
    svg = (f'<svg class="ic {esc(cls)}" aria-hidden="true" focusable="false"><use href="#i-{esc(name)}"></use></svg>')
    return svg + (f'<span class="sr">{esc(label)}</span>' if label else "")


def na(reason: str = "unavailable") -> str:
    """The unavailable marker: a visible em dash plus the reason for assistive technology."""
    return f'<span class="na" title="{esc(reason)}" aria-label="{esc(reason)}">—</span>'


def num(text: str | None, *, cls: str = "", reason: str = "unavailable") -> str:
    """A tabular number, or the unavailable marker when the value is missing."""
    if text is None:
        return na(reason)
    return f'<span class="num {esc(cls)}">{esc(text)}</span>'


def txt(text: str | None, *, reason: str = "unavailable") -> str:
    """Plain text (a time, a label), or the unavailable marker when missing. Not monospaced."""
    return na(reason) if text is None else f"<span>{esc(text)}</span>"


def signed_cls(value: Any) -> str:
    d = pr.dec(value)
    return "" if d is None or d == 0 else ("pos" if d > 0 else "neg")


KIND_ICON = {"ok": "circle-check", "err": "circle-x", "warn": "triangle-alert", "info": "info", "nd": "circle-dashed"}


def badge(code: Any, *, label: str | None = None, kind: str | None = None) -> str:
    """A compact state capsule: icon plus plain text; the stored code is in the title."""
    word = pr.state_word(code)
    kind = kind or word.kind
    text = label or word.label
    title = f"code: {code}" if code is not None else "code: unknown"
    return (f'<span class="badge k-{esc(kind)}" title="{esc(title)}">{icon(KIND_ICON.get(kind, "circle-dashed"))}'
            f"{esc(text)}</span>")


def state_text(code: Any, *, label: str | None = None, kind: str | None = None) -> str:
    """State as text plus a small icon (used in dense rows instead of a capsule)."""
    word = pr.state_word(code)
    kind = kind or word.kind
    return (f'<span class="state-txt k-{esc(kind)}" title="code: {esc(code)}">{icon(KIND_ICON.get(kind, "circle-dashed"))}'
            f"<span>{esc(label or word.label)}</span></span>")


def badge_code(value: Any) -> str:
    """Details view of a stored state: the semantic badge plus the exact code beside it."""
    return na("not recorded") if value is None else f"{badge(value)} {code(value)}"


def code(value: Any) -> str:
    return na("not recorded") if value is None else f'<code class="id">{esc(value)}</code>'


def link(href: str, text: str, cls: str = "link") -> str:
    return f'<a class="{esc(cls)}" href="{esc(href)}">{esc(text)}</a>'


# --------------------------------------------------------------------------- structure


def section(title: str, body: str, *, meta: str | None = None, action: str | None = None, sid: str | None = None,
            cls: str = "", flush: bool = False, level: int = 2) -> str:
    """SectionHeader + body. `meta` is plain text (scope/time); `action` is trusted HTML (one link)."""
    head_id = f' id="{esc(sid)}"' if sid else ""
    head = (f'<div class="section-head"><h{level} class="section-title"{head_id}>{esc(title)}</h{level}>'
            + (f'<span class="section-meta">{esc(meta)}</span>' if meta else "")
            + (f'<span class="section-action">{action}</span>' if action else "") + "</div>")
    classes = " ".join(c for c in ("section", cls, "flush" if flush else "") if c)
    labelled = f' aria-labelledby="{esc(sid)}"' if sid else ""
    return f'<section class="{classes}"{labelled}>{head}<div class="section-body">{body}</div></section>'


def page_head(title: str, sub: str | None = None, *, extra: str = "", crumb: str = "") -> str:
    return (f'<div class="page-head">{crumb}<h1 class="page-title">{esc(title)}</h1>'
            + (f'<p class="page-sub">{esc(sub)}</p>' if sub else "") + f"{extra}</div>")


def disclosure(summary: str, body: str, *, open_: bool = False, boxed: bool = False) -> str:
    """EvidenceDisclosure: a compact summary; exact provenance, codes and IDs inside."""
    return (f'<details class="disclosure{" boxed" if boxed else ""}"{" open" if open_ else ""}>'
            f'<summary>{icon("chevron-down")}<span>{esc(summary)}</span></summary>'
            f'<div class="disclosure-body">{body}</div></details>')


def kv(pairs: Iterable[tuple[str, str]]) -> str:
    """Pairs of (label, already-escaped HTML)."""
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in pairs) + "</dl>"


def table(headers: Sequence[str], rows: Iterable[Sequence[str]], *, wrap: Iterable[int] = (), right: Iterable[int] = (),
          empty: str = "none recorded", caption: str | None = None) -> str:
    """A technical table (Details only). Cells are already-escaped HTML; scrolls in its own container."""
    wrap, right = set(wrap), set(right)

    def cls(i: int) -> str:
        c = " ".join(x for x in ("wrap" if i in wrap else "", "r" if i in right else "") if x)
        return f' class="{c}"' if c else ""
    head = "".join(f'<th scope="col"{cls(i)}>{esc(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f"<td{cls(i)}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    if not body:
        return f'<p class="na">{esc(empty)}</p>'
    cap = f'<caption class="sr">{esc(caption)}</caption>' if caption else ""
    return (f'<div class="scroll" tabindex="0" role="region" aria-label="{esc(caption or "table")}">'
            f'<table class="tbl">{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def ul(items: Iterable[Any], empty: str = "none") -> str:
    items = list(items)
    if not items:
        return f'<span class="na">{esc(empty)}</span>'
    return '<ul class="tight">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


# --------------------------------------------------------------------------- states


def empty_state(title: str, text: str = "", *, kind: str = "nd", times: str | None = None,
                action: tuple[str, str] | None = None, icon_name: str | None = None) -> str:
    """EmptyState / UnavailableState / ErrorState / BlockedState (kind nd | warn | err)."""
    ic = icon_name or {"err": "circle-x", "warn": "triangle-alert"}.get(kind, "circle-dashed")
    role = ' role="alert"' if kind == "err" else ""
    return (f'<div class="empty k-{esc(kind)}"{role}><p class="empty-title">{icon(ic)}<span>{esc(title)}</span></p>'
            + (f'<p class="empty-text">{esc(text)}</p>' if text else "")
            + (f'<p class="empty-times">{esc(times)}</p>' if times else "")
            + (f'<p class="empty-action">{link(action[0], action[1], "btn")}</p>' if action else "") + "</div>")


def unavailable(title: str, message: str, *, action: tuple[str, str] | None = None) -> str:
    return empty_state(title, message, kind="nd", action=action)


def error_state(title: str, message: str) -> str:
    return empty_state(title, message, kind="err")


def blocked_state(title: str, message: str, *, action: tuple[str, str] | None = None) -> str:
    return empty_state(title, message, kind="warn", icon_name="ban", action=action)


def status_line(kind: str, title: str, detail: str = "", *, detail_html: str = "") -> str:
    """StatusLine: semantic icon + short title; the event time and the report time stay separate."""
    ic = {"ok": "circle-check", "err": "circle-x", "warn": "triangle-alert", "info": "info"}.get(kind, "circle-dashed")
    return (f'<div class="statusline k-{esc(kind)}" role="status">{icon(ic)}<div class="statusline-text">'
            f'<p class="statusline-title">{esc(title)}</p>'
            + (f'<p class="statusline-detail">{esc(detail)}{detail_html}</p>' if detail or detail_html else "")
            + "</div></div>")


# --------------------------------------------------------------------------- metrics


def metric(label: str, value_html: str, basis: str | None = None, *, lead: bool = False) -> str:
    return (f'<div class="metric{" lead" if lead else ""}"><dt>{esc(label)}</dt><dd>{value_html}'
            + (f'<span class="basis">{esc(basis)}</span>' if basis else "") + "</dd></div>")


def metric_strip(cells: Iterable[str], *, label: str) -> str:
    """MetricStrip: compact financial cells (use `metric`), with its scope as the accessible name."""
    return f'<dl class="metric-strip" aria-label="{esc(label)}">{"".join(cells)}</dl>'


def money_cell(value: Any, *, signed: bool = False, reason: str = "unavailable") -> str:
    return num(pr.money(value, signed=signed), cls=signed_cls(value) if signed else "", reason=reason)


def bar(value: Any, maximum: Any, *, kind: str = "", label: str = "") -> str:
    """A horizontal bar whose length is value/maximum of canonical amounts. No bar when either is
    unknown or the maximum is not positive (never a division by zero or a full green bar)."""
    v, m = pr.dec(value), pr.dec(maximum)
    if v is None or m is None or m <= 0 or v < 0:
        return ""
    frac = min(v / m, 1)
    width = f"{float(frac) * 100:.2f}"
    over = " over" if v > m else ""
    return (f'<svg class="bar-svg" viewBox="0 0 100 6" preserveAspectRatio="none" role="img" '
            f'aria-label="{esc(label)}"><rect class="bar-track" x="0" y="0" width="100" height="6" rx="3"></rect>'
            f'<rect class="bar-fill {esc(kind)}{over}" x="0" y="0" width="{width}" height="6" rx="3"></rect></svg>')


# --------------------------------------------------------------------------- navigation widgets


def tabs(items: Iterable[tuple[str, str, bool, str | None]], *, label: str) -> str:
    """DomainTabs / state tabs: one horizontal strip of links (swipe overflow, never wraps)."""
    out = []
    for href, text, current, count_text in items:
        cur = ' aria-current="page"' if current else ""
        cnt = f' <span class="count">{esc(count_text)}</span>' if count_text is not None else ""
        out.append(f'<li><a href="{esc(href)}"{cur}>{esc(text)}{cnt}</a></li>')
    return f'<nav aria-label="{esc(label)}"><ul class="tabs">{"".join(out)}</ul></nav>'


ACCOUNT_LABELS = {"operational": "Operational shadow", "research": "Research"}


def account_switch(p: pr.Params, path: str, extra: Mapping[str, str] | None = None) -> str:
    """Compact account switch. Research carries the FROZEN RESEARCH RULE label; balances are never summed."""
    links = []
    for key in pr.ACCOUNT_KEYS:
        params = dict(extra or {})
        if key != "operational":
            params["account"] = key
        href = path + ("?" + urlencode(params) if params else "")
        cur = ' aria-current="true"' if p.account == key else ""
        links.append(f'<a href="{esc(href)}"{cur}>{esc(ACCOUNT_LABELS[key])}</a>')
    return f'<nav class="acct-switch" aria-label="Shadow account">{"".join(links)}</nav>'


# --------------------------------------------------------------------------- market components


def market_href(row: pr.MarketRow, p: pr.Params, side: str | None = None) -> str:
    params = {k: v for k, v in p.filters().items() if k != "venue"}
    params.update({"venue": row.venue, "id": row.native_id})
    if side:
        params["side"] = side
    return "/market?" + urlencode(params)


def quote_tile(q: pr.QuoteSide | None, side: str, href: str | None, *, label: str | None = None,
               current: bool = False, small: bool = False) -> str:
    """QuoteTile: explicit side/outcome label above the captured ask; Unavailable when missing."""
    side_label = label or (q.label if q and q.label else side)
    text = f"{side} · {side_label}" if side_label and side_label != side else side
    if q is not None and q.phase == "decision payload":
        text += " · at decision"
    if q is None or q.price is None:
        why = "no book captured for this side" if q is None else (q.anomaly or "no ask in the captured book")
        inner = (f'<span class="qt-side">{esc(text)}</span><span class="qt-price">Unavailable</span>'
                 f'<span class="sr">: {esc(why)}</span>')
        cls = "qt is-na"
    else:
        inner = (f'<span class="qt-side">{esc(text)}</span>'
                 f'<span class="qt-price{" small" if small else ""}">{esc(pr.cents(q.price))}</span>'
                 f'<span class="sr"> ask, captured {esc(pr.datetime_et(q.received_at_utc) or "at an unknown time")}</span>')
        cls = "qt"
    cur = ' aria-current="true"' if current else ""
    if href:
        return f'<a class="{cls}" href="{esc(href)}"{cur}>{inner}</a>'
    return f'<div class="{cls}"{cur}>{inner}</div>'


def edge_value(a: pr.Assessment | None) -> str:
    """EdgeValue: canonical net expected value per $1 contract. Never labelled as a return."""
    if a is None:
        return na("not evaluated yet")
    text = pr.edge_cents(a.net_edge)
    if text is None:
        return na("net edge not recorded")
    return (f'<span class="num {signed_cls(a.net_edge)}">{esc(text)}</span>'
            f'<span class="sr"> net expected value per contract</span>')


def model_value(a: pr.Assessment | None) -> str:
    if a is None:
        return na("not evaluated yet")
    return num(pr.percent(a.model_probability), reason="no model probability recorded")


def release_value(row: pr.MarketRow) -> tuple[str, str]:
    """(value html, sub text) for Tradable again."""
    bucket, eta, hours = row.cash_release
    if eta is None:
        return na("cash release not evaluated"), ("Not evaluated" if row.primary is None else "Unknown")
    sub = {"within7": "≤ 7 days", "over7": "Over 7 days", "unknown": "Unknown"}[bucket]
    return f'<span class="num">{esc(pr.date_et(eta))}</span>', f"{sub} · {pr.hours_text(hours) or '—'}"


BOARD_HEADERS = (("Market / outcome", "h-title"), ("Venue", "h-venue"), ("Quote (ask)", "h-tiles"),
                 ("Model", "h-model r"), ("Net edge", "h-edge r"), ("Size", "h-size r"), ("Tradable again", "h-rel r"),
                 ("State", "h-state r"), ("", "h-act"))


def market_row(row: pr.MarketRow, p: pr.Params) -> str:
    """MarketRow: one view model, a board row on desktop and a composed list item on mobile."""
    a = row.primary
    title = pr.market_title(row)
    href = market_href(row, p)
    domain = pr.DOMAIN_LABELS.get(row.domain, "Other")
    when = row.quotes.get("YES") or next(iter(row.quotes.values()), None)
    when_text = (f"{'Decision' if when.phase == 'decision payload' else 'Captured'} "
                 f"{pr.time_et(when.received_at_utc) or '—'}") if when else "No quote captured"
    tiles = []
    if row.payoff_kind not in (None, "binary"):
        tiles.append('<p class="note">Research only: this payoff is not a simple YES/NO contract.</p>')
    else:
        for side in ("YES", "NO"):
            # The outcome is already in the row title; the tile names its side only, so nothing is clipped.
            tiles.append(quote_tile(row.quotes.get(side), side, market_href(row, p, side), label=side))
    rel_html, rel_sub = release_value(row)
    size = a.size if a is not None else None
    state = state_text(row.state_code)
    sub_bits = [f"{pr.venue_label(row.venue)} · {row.native_id}"]
    if a is not None and a.decided_at_utc:
        sub_bits.append(f"assessed {pr.datetime_et(a.decided_at_utc)}")
    return (
        f'<li class="mrow" data-state="{esc(row.state)}">'
        f'<p class="m-meta"><span>{esc(domain)}</span><span>{esc(pr.venue_label(row.venue))} · {esc(when_text)}</span></p>'
        f'<p class="m-title"><a href="{esc(href)}">{esc(title)}</a><span class="m-sub">{esc(" · ".join(sub_bits))}</span></p>'
        f'<p class="m-venue">{esc(pr.venue_label(row.venue))}</p>'
        f'<div class="m-tiles">{"".join(tiles)}</div>'
        f'<p class="m-model"><span class="cell-lbl sr-md">Model</span><span class="cell-val">{model_value(a)}</span>'
        + (f'<span class="cell-sub">{esc(a.side)} side</span>' if a is not None and a.side else "") + "</p>"
        f'<p class="m-edge"><span class="cell-lbl sr-md">Net edge / contract</span><span class="cell-val">{edge_value(a)}</span></p>'
        f'<p class="m-size"><span class="cell-val">{num(pr.quantity(size), reason="size not evaluated")}</span></p>'
        f'<p class="m-rel"><span class="cell-lbl sr-md">Tradable again</span><span class="cell-val">{rel_html}</span>'
        f'<span class="cell-sub">{esc(rel_sub)}</span></p>'
        f'<p class="m-state">{state}</p>'
        f'<p class="m-act"><a class="icon-link" href="{esc(href)}">{icon("chevron-right")}'
        f'<span class="sr">View details: {esc(title)}</span></a></p>'
        "</li>")


def market_board(rows: Sequence[pr.MarketRow], p: pr.Params, *, label: str = "Market board") -> str:
    head = "".join(f'<span class="{c}">{esc(h)}</span>' for h, c in BOARD_HEADERS)
    return (f'<div class="board-wrap"><div class="board-head" aria-hidden="true">{head}</div>'
            f'<ol class="board" aria-label="{esc(label)}">{"".join(market_row(r, p) for r in rows)}</ol></div>')


def tape(items: Sequence[tuple[pr.MarketRow, pr.QuoteSide]], p: pr.Params, *, empty_href: str = "/opportunities") -> str:
    """The market tape: captured quotes only, manually scrollable; never an autoplay marquee."""
    if not items:
        return ('<div class="tape" role="region" aria-label="Quote tape"><div class="tape-in"><p class="tape-empty">'
                f'{icon("chart-candlestick", "ic-sm")}<span>No quotes captured yet.</span>'
                f'<a href="{esc(empty_href)}">Markets</a></p></div></div>')
    lis = []
    for row, q in items:
        change = ""
        if q.change is not None:
            cls = signed_cls(q.change)
            arrow = icon("arrow-up-right" if q.change > 0 else "arrow-down-right" if q.change < 0 else "minus", "ic-xs")
            change = (f'<span class="tape-chg {cls}">{arrow}{esc(pr.cents(q.change, signed=True))}'
                      f'<span class="sr"> since the decision capture</span></span>')
        price = pr.cents(q.price) or "—"
        full = f"{pr.market_title(row)}, {q.side}, {pr.venue_label(row.venue)}"
        lis.append(
            f'<li><a class="tape-item" href="{esc(market_href(row, p, q.side))}" '
            f'title="{esc(full)} · captured {esc(pr.datetime_et(q.received_at_utc) or "unknown time")}">'
            f'<span class="tape-label">{esc(pr.short_label(row))}</span>'
            f'<span class="tape-price">{esc(price)}</span>'
            f'<span class="tape-sub">{esc(pr.venue_label(row.venue))} · {esc(q.side)} · captured</span>{change}'
            f'<span class="sr">{esc(full)}, ask {esc(price)}, captured {esc(pr.datetime_et(q.received_at_utc) or "at an unknown time")}</span>'
            "</a></li>")
    return ('<div class="tape" role="region" aria-label="Quote tape: latest captured prices" data-tape>'
            '<div class="tape-in">'
            f'<button class="tape-btn" type="button" data-tape-prev hidden>{icon("chevron-left", "ic-sm", "Scroll quotes left")}</button>'
            f'<div class="tape-track" data-tape-track tabindex="0" aria-label="Captured quotes">'
            f'<ul class="tape-list">{"".join(lis)}</ul></div>'
            f'<button class="tape-btn" type="button" data-tape-next hidden>{icon("chevron-right", "ic-sm", "Scroll quotes right")}</button>'
            "</div></div>")


# --------------------------------------------------------------------------- rows


def facts(pairs: Iterable[tuple[str, str]], *, wide: bool = False, text_cols: Iterable[int] = ()) -> str:
    text_cols = set(text_cols)
    return (f'<dl class="row-facts{" wide" if wide else ""}">'
            + "".join(f'<div><dt>{esc(k)}</dt><dd{" class=txt" if i in text_cols else ""}>{v}</dd></div>'
                      for i, (k, v) in enumerate(pairs)) + "</dl>")


def row(title_html: str, *, sub: str = "", aside: str = "", body: str = "") -> str:
    """Generic PositionRow / OutcomeExposureRow shell."""
    return (f'<li class="row"><div class="row-main"><p class="row-title">{title_html}</p>'
            + (f'<p class="row-sub">{esc(sub)}</p>' if sub else "") + "</div>"
            + (f'<div class="row-aside">{aside}</div>' if aside else "<div></div>") + body + "</li>")


def activity_row(kind: str, title: str, detail: str, when_utc: Any, *, href: str | None = None,
                 extra_html: str = "") -> str:
    """ActivityRow: semantic icon, short title, time, concise reason, optional valid action link."""
    ic = {"ok": "circle-check", "err": "circle-x", "warn": "triangle-alert", "info": "info"}.get(kind, "circle-dashed")
    when = pr.datetime_et(when_utc)
    title_html = f'<a class="link" href="{esc(href)}">{esc(title)}</a>' if href else esc(title)
    return (f'<li class="activity"><span class="act-icon k-{esc(kind)}">{icon(ic)}</span><div class="row-main">'
            f'<p class="row-title">{title_html}</p>'
            f'<p class="activity-time">{esc(when) if when else "time not recorded"}</p>'
            + (f'<p class="row-sub">{esc(detail)}</p>' if detail else "") + extra_html + "</div></li>")


def timeline(steps: Iterable[tuple[str, str, str, str]]) -> str:
    """PipelineTimeline: (kind, title, detail, time text) per step, in order."""
    items = []
    for kind, title, detail, when in steps:
        ic = {"ok": "circle-check", "err": "circle-x", "warn": "triangle-alert", "info": "clock"}.get(kind, "circle-dashed")
        items.append(f'<li><span class="k-{esc(kind)}">{icon(ic)}</span><div><p>{esc(title)}</p>'
                     + (f'<p class="meta">{esc(detail)}</p>' if detail else "")
                     + f'</div><span class="meta">{esc(when)}</span></li>')
    return f'<ol class="timeline">{"".join(items)}</ol>'


# --------------------------------------------------------------------------- chart


def history_chart(points: Sequence[tuple[str, Any]], *, label: str, unit: str = "¢") -> str:
    """HistoryChart: persisted same-side observations only. Fewer than two points is not a trend,
    so no line is drawn; the accessible table always lists the exact observations."""
    pts = [(t, pr.dec(v)) for t, v in points if pr.dec(v) is not None]
    rows = [[esc(pr.datetime_et(t) or t), num(pr.cents(v))] for t, v in pts]
    tbl = table(["captured (ET)", "ask"], rows, right=(1,), caption=f"{label}: observations")
    if len(pts) < 2:
        return (empty_state("Not enough history for a chart",
                            "A chart needs at least two comparable observations of the same side; "
                            f"{len(pts)} captured.") + tbl)
    lo = min(v for _, v in pts) * 100
    hi = max(v for _, v in pts) * 100
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    w, h, pad_l, pad_r, pad_t, pad_b = 640, 180, 52, 16, 14, 28  # drawn at up to 640 CSS px: 11px axis text
    n = len(pts)

    def x(i: int) -> float:
        return pad_l + (w - pad_l - pad_r) * (i / (n - 1))

    def y(v: Any) -> float:
        return pad_t + (h - pad_t - pad_b) * float((hi - v * 100) / (hi - lo))
    coords = [(x(i), y(v)) for i, (_, v) in enumerate(pts)]
    path = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
    marks = "".join(f'<circle class="pt" cx="{cx:.1f}" cy="{cy:.1f}" r="3"></circle>' for cx, cy in coords)
    axis = (f'<text class="ax" x="{pad_l - 6}" y="{pad_t + 4}" text-anchor="end">{esc(pr.cents(hi / 100))}</text>'
            f'<text class="ax" x="{pad_l - 6}" y="{h - pad_b}" text-anchor="end">{esc(pr.cents(lo / 100))}</text>'
            f'<text class="ax" x="{pad_l}" y="{h - 4}">{esc(pr.time_et(pts[0][0]) or "")}</text>'
            f'<text class="ax" x="{w - pad_r}" y="{h - 4}" text-anchor="end">{esc(pr.time_et(pts[-1][0]) or "")}</text>')
    svg = (f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">'
           f'<line class="grid-l" x1="{pad_l}" y1="{pad_t}" x2="{w - pad_r}" y2="{pad_t}"></line>'
           f'<line class="grid-l" x1="{pad_l}" y1="{h - pad_b}" x2="{w - pad_r}" y2="{h - pad_b}"></line>'
           f'<polyline class="series" points="{path}"></polyline>{marks}{axis}</svg>')
    return svg + disclosure("Observations as a table", tbl)
