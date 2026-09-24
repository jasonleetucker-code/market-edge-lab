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
    parsed = pr.parse_utc(eta)
    if row.has_position and row.now is not None and parsed is not None and parsed < row.now:  # open and late only
        sub = "Past its ETA · overdue"
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
                 f"{pr.datetime_et(when.received_at_utc) or 'time unknown'}") if when else "No quote captured"
    if when is not None and when.phase != "decision payload" and not when.capture_complete:
        when_text += " · capture incomplete"
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
    if row.historical:
        sub_bits.append(f"decision for target {pr.date_label(row.target_date) or 'unknown day'}, not current")
    elif not row.assessments and row.history:
        sub_bits.append("not evaluated for this target day")
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


def tape(items: Sequence[tuple[pr.MarketRow, pr.QuoteSide]], p: pr.Params, *, empty_href: str = "/opportunities",
         unavailable: bool = False) -> str:
    """The market tape: captured quotes only, manually scrollable; never an autoplay marquee.

    `unavailable` is the read-error state: the evidence could not be read, which is not the same
    as nothing having been captured, so it never says "No quotes captured yet".
    """
    if unavailable:
        return ('<div class="tape" role="region" aria-label="Quote tape"><div class="tape-in"><p class="tape-empty">'
                f'{icon("circle-x", "ic-sm k-err")}'
                '<span>Captured quotes unavailable (read error).</span>'
                f'<a href="{esc(empty_href)}">Markets</a></p></div></div>')
    if not items:
        return ('<div class="tape" role="region" aria-label="Quote tape"><div class="tape-in"><p class="tape-empty">'
                f'{icon("chart-candlestick", "ic-sm")}<span>No quotes captured yet.</span>'
                f'<a href="{esc(empty_href)}">Markets</a></p></div></div>')
    first = max((q for _, q in items), key=lambda q: str(q.received_at_utc))
    incomplete = any(not q.capture_complete for _, q in items)
    lis = [f'<li class="tape-head"><span class="tape-label">Captured quotes</span>'
           f'<span class="tape-sub">{esc(pr.datetime_et(first.received_at_utc) or "time unknown")}</span>'
           + (f'<span class="tape-sub k-warn">Capture incomplete</span>' if incomplete else
              '<span class="tape-sub">Delayed evidence, not live</span>') + "</li>"]
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
            f'<span class="tape-sub">{esc(q.side)} · {esc(pr.venue_label(row.venue))}</span>{change}'
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
    times = [pr.parse_utc(t) for t, _ in pts]
    known = all(t is not None for t in times) and times[-1] != times[0]
    span = (times[-1] - times[0]).total_seconds() if known else 0

    def x(i: int) -> float:
        # Horizontal position follows capture time, so uneven intervals are not drawn as even ones.
        frac = (times[i] - times[0]).total_seconds() / span if known else i / (n - 1)
        return pad_l + (w - pad_l - pad_r) * frac

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


# --------------------------------------------------------------------------- across venues (best_price, ADR 0027)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# A route's first exclusion among these explains a missing verified total (gate order).
_TOTAL_GATES = ("PAYOFF_UNSUPPORTED", "MARKET_NOT_OPEN", "BOOK_MISSING", "INVALID_BOOK", "NO_OFFER",
                "INSUFFICIENT_DEPTH", "DEPTH_UNKNOWN", "FEE_UNSUPPORTED", "FEE_NOT_PRICED", "FEE_UNVERIFIED")


def _unranked_note(kind: str, claim: Any, routes: Mapping[str, Any]) -> str:
    """Candidates the winner is not proven below: equal figures are ties; totals may only overlap."""
    open_ = [m for m in claim.candidates if m != claim.market_id and m not in claim.proven_below]
    if not open_:
        return ""
    if kind in pr.TOTAL_CLAIMS:
        # Equal exact debits are a tie (as best_price.summarize); equal bounds prove nothing.
        best = routes.get(claim.market_id)
        tied = [m for m in open_ if best is not None and routes.get(m) is not None
                and best.fee_status == routes[m].fee_status == "VERIFIED" and routes[m].total_cost == best.total_cost]
    else:  # observed quotes and gross costs are exact: a candidate not proven above the winner equals it
        tied = open_
    other = [m for m in open_ if m not in tied]
    out = ""
    if tied:
        out += f'<span class="cell-sub">Tied with: {esc(", ".join(tied))}</span>'
    if other:
        out += f'<span class="cell-sub">No proven order against: {esc(", ".join(other))} (cost bounds overlap)</span>'
    return out


def comparison_claims(cmp: Any) -> str:
    """The comparator's four claims side by side, each with its own figure or its reason for
    absence. There is never a single "best" verdict: the four answer different questions."""
    routes = {r.market_id: r for r in cmp.routes}
    size = pr.quantity(cmp.quantity)
    pairs = []
    for kind in pr.CLAIM_ORDER:
        claim = cmp.claim(kind)
        label, _ = pr.CLAIM_LABELS[kind]
        if claim.supported:
            unit = "per contract" if kind == "BEST_OBSERVED_QUOTE" else f"for {size} contract{'' if size == '1' else 's'}"
            n = len(claim.candidates)
            value = (num(pr.claim_value_text(claim, routes.get(claim.market_id)))
                     + f'<span class="cell-sub">{esc(unit)} · {esc(pr.venue_label(claim.venue))} · lowest of '
                       f'{esc(_plural(n, "route"))} fresh at decision time</span>'
                     + _unranked_note(kind, claim, routes))
        else:
            value = badge(claim.reason) + '<span class="cell-sub">Not claimed</span>'
        if claim.stale_candidates:
            value += (f'<span class="cell-sub">Not ranked (stale or unknown-age book at decision time): '
                      f'{esc(", ".join(claim.stale_candidates))}</span>')
        pairs.append((label, value))
    return facts(pairs, text_cols=range(4))


def _fee_cell(r: Any) -> str:
    note = pr.FEE_STATUS_NOTES.get(r.fee_status, str(r.fee_status))
    if r.fee is None and r.fee_status != "UNSUPPORTED":
        # The evidence grade exists, but no fee was priced (no fillable walk, or pricing failed).
        note = f"Fee not priced · evidence: {pr.state_word(r.fee_status).label.lower()}"
    value = money_cell(r.fee, reason="fee unknown: " + note.lower())
    return value + f'<span class="cell-sub">{esc(note)}</span>'


def _total_cell(r: Any) -> str:
    if r.claim_total_cost is None:
        # The route's own first blocking exclusion explains it (depth, offer, book or fee evidence).
        why = next((e for e in r.exclusions if e in _TOTAL_GATES), None)
        word = pr.state_word(why).label if why else "not verified"
        return na(f"no verified total: {word.lower()}") + f'<span class="cell-sub">Not verified · {esc(word)}</span>'
    if "NOT_FRESH" in r.exclusions:  # as the comparator's summary: a stale book's total is not claimed
        return na("total not claimed: the book was stale or of unknown age at decision time") + \
            '<span class="cell-sub">Not claimed (stale at decision time)</span>'
    if r.fee_status != "VERIFIED":
        sub = "At most (conservative bound)"
    elif r.claim_total_cost == r.total_cost:
        sub = "Exact"
    else:  # the claim figure carries the record's allowance; the exact debit is the schedule's total
        sub = f"Exact debit {pr.money(r.total_cost)} plus the claim allowance"
    return money_cell(r.claim_total_cost) + f'<span class="cell-sub">{esc(sub)}</span>'


def _depth_cell(r: Any) -> str:
    if r.liquidity is None:
        return na("not assessed: the payoff is not supported") + '<span class="cell-sub">Not assessed</span>'
    offered = pr.quantity(r.available)
    sub = f"{offered} of {pr.quantity(r.quantity)} offered" if offered is not None else "Nothing captured"
    if r.levels_taken:
        sub += f" · {_plural(r.levels_taken, 'level')} taken"
    return badge(r.liquidity) + f'<span class="cell-sub">{esc(sub)}</span>'


def _release_cell(r: Any) -> str:
    when = pr.date_et(r.capital_release_eta_utc)
    sub = "Within starter horizon" if r.capital_release_eligible else "Outside starter horizon or unknown"
    return txt(when, reason="tradable-cash release unknown") + f'<span class="cell-sub">{esc(sub)}</span>'


def comparison_route(r: Any, now: Any = None) -> str:
    """One venue route: its own quote, gross cost, fees, verified total, depth, cash release and
    rules status. Figures are the comparator's; a missing one stays unavailable, never zero.
    Freshness is the comparator's, at its as-of time; `now` adds the book's age today beside it."""
    code_, label = pr.route_freshness(r.freshness)
    status = (badge("ALL_GATES_PASSED") if not r.exclusions
              else "".join(badge(e) for e in r.exclusions[:3])
              + (f'<span class="cell-sub">and {esc(len(r.exclusions) - 3)} more in details</span>'
                 if len(r.exclusions) > 3 else ""))
    quote = (num(pr.cents(r.observed_ask), reason="no ask captured")
             + (f'<span class="cell-sub">{esc(pr.quantity(r.observed_ask_size))} at the top</span>'
                if r.observed_ask_size is not None else ""))
    gross = money_cell(r.gross_cost, reason="no gross cost: the ladder does not cover the size") + \
        (f'<span class="cell-sub">average {esc(pr.cents(r.average_price))}</span>' if r.average_price is not None
         else "")
    body = facts([
        ("Quote (ask)", quote), ("Gross cost for size", gross), ("Fees", _fee_cell(r)),
        ("Verified total", _total_cell(r)), ("Depth", _depth_cell(r)), ("Tradable cash", _release_cell(r)),
        ("Rules", badge(r.equivalence)), ("Claim status", status),
    ], wide=True, text_cols=(4, 5, 6, 7))
    detail = disclosure("Route details", kv([
        ("market id", code(r.market_id)), ("payoff", esc(r.payoff_kind)), ("market status", esc(r.market_status)),
        ("book evidence", code(r.book_evidence_id)), ("book received (UTC)", esc(r.book_received_at_utc)),
        ("exact gross cost", esc(r.gross_cost)), ("worst price taken", esc(r.worst_price)),
        ("fee schedule", code(r.fee_schedule_id)), ("claim basis", badge_code(r.claim_basis)),
        ("exact fee", esc(r.fee)), ("estimated total (schedule)", esc(r.total_cost)),
        ("claim total (allowance included)", esc(r.claim_total_cost)), ("fee detail", esc(r.fee_detail)),
        ("account read", badge_code(r.account_read_stage)),
        ("tradable-cash ETA (UTC)", esc(r.capital_release_eta_utc)),
        ("starter reasons", ul(r.capital_release_reasons)), ("exclusions (gate order)", ul(r.details)),
        ("execution authorized", esc("no")),
    ]))
    when = pr.datetime_et(r.book_received_at_utc)
    age = pr.age_text(r.book_received_at_utc, now) if now is not None and when else None
    captured = (f"book captured {when}" + (f" ({age})" if age else "")) if when else "book capture time unknown"
    title = f"{esc(pr.venue_label(r.venue))} {code(r.market_id)}"
    return row(title, sub=f"{pr.state_word(r.equivalence).label} · {captured}",
               aside=state_text(code_, label=label), body=body + detail)


def venue_comparison(cmp: Any, *, now: Any = None) -> str:
    """VenueComparison: the canonical `best_price.Comparison` for one market, side and evaluated
    size. Four separate claims, one row per equivalent route, related markets listed unranked,
    stale routes named as not ranked. Freshness is judged at the comparison's as-of time (the
    recorded decision), never now. Read-only; the comparator never authorizes execution."""
    as_of = pr.datetime_et(cmp.as_of_utc) or cmp.as_of_utc
    parts = [f'<p class="note">Evaluated at the decision time, {esc(as_of)}: "fresh" means fresh then, not '
             "now. The Quote section above judges the latest capture against the current time.</p>"]
    # The comparator refuses a request whose own payoff it cannot price: every claim then carries it.
    if all(not c_.supported and c_.reason == "PAYOFF_UNSUPPORTED" for c_ in cmp.claims):
        parts.append(blocked_state("Comparison refused: payoff not supported",
                                   "Only binary contracts paying $1 are compared. This payoff is never reinterpreted "
                                   "as a YES/NO contract."))
    parts.append(comparison_claims(cmp))
    stale = sorted({m for c_ in cmp.claims for m in c_.stale_candidates})
    if stale:
        parts.append(f'<p class="note">{icon("triangle-alert", "ic-sm k-warn")} Not ranked because the book was stale '
                     f'or of unknown age at decision time: {esc(", ".join(stale))}.</p>')
    if not cmp.routes:
        parts.append('<p class="note">No route for this market was captured, so nothing is compared.</p>')
    elif len(cmp.routes) == 1 and not cmp.related:
        only = pr.venue_label(cmp.routes[0].venue)
        parts.append(f'<p class="note">No equivalent venue price verified: only {esc(only)} is captured for this '
                     "market, so nothing is compared across venues. The claims describe this one route.</p>")
    # Eligible comparisons first, excluded or unproven ones separately (a grouping, not a ranking).
    eligible = {m for c_ in cmp.claims for m in c_.candidates}
    groups = (("Routes eligible for at least one claim", [r for r in cmp.routes if r.market_id in eligible]),
              ("Routes excluded from every claim", [r for r in cmp.routes if r.market_id not in eligible]))
    for heading, routes in groups:
        if routes:
            parts.append(f'<h3 class="eyebrow">{esc(heading)}</h3><ul class="rows">'
                         + "".join(comparison_route(r, now) for r in routes) + "</ul>")
    if cmp.related:
        items = "".join(row(code(m), sub="Listed only; never priced against this market",
                            aside=state_text("RELATED_NOT_EQUIVALENT")) for m in cmp.related)
        parts.append(f'<h3 class="eyebrow">Related markets · unranked</h3><ul class="rows">{items}</ul>')
    parts.append(disclosure("What each claim means", kv(
        [(pr.CLAIM_LABELS[k][0], esc(pr.CLAIM_LABELS[k][1] + " " + cmp.claim(k).detail)) for k in pr.CLAIM_ORDER])))
    parts.append(disclosure("Comparator summary (exact)", ul(cmp.summary.splitlines()) + kv([
        ("comparator version", esc(cmp.comparator_version)), ("as of (UTC)", esc(cmp.as_of_utc)),
        ("requested market", code(cmp.request_market_id)), ("side", esc(cmp.side)),
        ("evaluated size", esc(cmp.quantity)), ("max book age (s)", esc(cmp.max_book_age_seconds)),
        ("execution authorized", esc("no")),
    ])))
    return "".join(parts)


# --------------------------------------------------------------------------- research sizing (sizing_counterfactual)

SIZING_NOTE = ("Research only: a counterfactual challenger policy replayed on recorded evidence. It is not a bet, "
               "not an order and not the operational sizing policy; shadow fills stay on their current policy.")
# Verdicts the engine returns for a refusal (the contract's own unavailable mapping): their rows
# carry placeholder zeros that were never computed, so they render as unavailable, never as 0.
SIZING_REFUSED = frozenset({"UNSUPPORTED", "STALE_DATA"})
# Whole-panel reasons that mean "nothing to size", not a refusal of a real decision.
SIZING_NO_DATA = frozenset({"No recorded decision", "Ledger unavailable", "No sizing policy"})


def _g(mapping: Any, key: str) -> Any:
    return mapping.get(key) if isinstance(mapping, Mapping) else None


def sizing_comparison(rows: Sequence[Mapping[str, Any]], *, computed: bool = True) -> str:
    """The compact policy comparison (A–H): each policy's own verdict and size, as the contract gives
    them. A refused row (or any row of an unavailable side) shows no figures: they were not computed."""
    body = []
    for r in rows:
        ok = computed and _g(r, "verdict") not in SIZING_REFUSED
        why = "not computed: the engine refused this decision"
        body.append([esc(pr.policy_label(r)), badge(_g(r, "verdict")),
                     num(pr.quantity(_g(r, "final_contracts")) if ok else None, reason=why),
                     money_cell(_g(r, "final_amount") if ok else None, reason=why),
                     num(pr.percent(_g(r, "fraction_of_bankroll"), places=2) if ok else None, reason=why),
                     code(_g(r, "binding_constraint"))])
    return table(["policy", "verdict", "contracts", "amount", "of bankroll", "binding constraint"], body,
                 right=(2, 3, 4), empty="no policy rows", caption="Research sizing by policy")


def sizing_side(side: Mapping[str, Any]) -> str:
    """One recorded side: the primary (challenger) policy's result, or the named reason it is unavailable."""
    p = _g(side, "primary") or {}
    available = bool(_g(side, "available")) and _g(p, "verdict") not in SIZING_REFUSED
    head = (f'<h3 class="eyebrow">{esc(_g(side, "side") or "Side unknown")} side · decision '
            f'{esc(_g(side, "decision_id") or "id not recorded")} · '
            f'{esc(pr.datetime_et(_g(side, "decision_time")) or "time not recorded")}</h3>')
    recorded = (f'<p class="meta">Recorded decision: {badge(_g(side, "recorded_qualification"))} '
                f'{code(_g(side, "recorded_reason"))} · model {esc(_g(side, "model_version") or "not recorded")}'
                + (f' · recorded in {esc(", ".join(map(str, _g(side, "recorded_in_accounts"))))}'
                   if _g(side, "recorded_in_accounts") else "") + "</p>")
    if not available:
        body = blocked_state(_g(side, "unavailable_reason") or "Not computed",
                             _g(side, "unavailable_detail") or "The sizing engine did not compute this side.")
    else:
        horizon = _g(p, "capital_horizon")
        body = facts([
            ("Challenger size (research)", num(pr.quantity(_g(p, "final_contracts")), reason="not computed")
             + f'<span class="cell-sub">contracts · {esc(pr.money(_g(p, "final_amount")) or "amount not computed")} '
               "cost</span>"),
            ("Verdict", badge(_g(p, "verdict"))),
            ("Binding constraint", code(_g(p, "binding_constraint"))),
            ("Model probability", num(pr.percent(_g(p, "model_probability")), reason="not recorded")),
            ("Conservative probability", num(pr.percent(_g(p, "conservative_probability")), reason="not recorded")),
            ("Expected net edge / contract", num(pr.edge_cents(_g(p, "expected_net_edge")), reason="not computed")),
            ("Average entry price", num(pr.cents(_g(p, "entry_price")), reason="not computed")),
            ("Estimated fee (incl. claim allowance)", money_cell(_g(p, "estimated_fee"), reason="not computed")),
            ("Full-Kelly amount", money_cell(_g(p, "unconstrained_kelly_amount"), reason="not computed")),
            ("Policy amount before caps", money_cell(_g(p, "policy_amount_before_caps"), reason="not computed")),
            ("Bankroll basis", money_cell(_g(_g(p, "bankroll_basis"), "bankroll"), reason="not recorded")),
            ("Capital horizon", badge("ELIGIBLE") if _g(horizon, "eligible") is True else
             badge("STARTER_POLICY_INELIGIBLE") if _g(horizon, "eligible") is False else na("not recorded")),
        ], wide=True, text_cols=(1, 2, 11))
        if _g(p, "explanation"):
            body += f'<p class="note">{esc(_g(p, "explanation"))}</p>'
        caps = _g(p, "caps") or {}
        basis = _g(p, "bankroll_basis") or {}
        body += disclosure("Caps, bankroll basis and capital horizon", kv(
            [(f"{k.replace('_', ' ')} cap", money_cell(_g(caps, k), reason="cap does not apply or unknown"))
             for k in ("liquidity", "position", "event", "cluster", "portfolio", "cash_horizon", "drawdown")]
            + [("most any cap allows", money_cell(_g(caps, "maximum_allowed"), reason="unknown")),
               ("tradable cash", money_cell(_g(basis, "tradable_cash"), reason="not recorded")),
               ("available risk budget", money_cell(_g(basis, "available_risk_budget"), reason="not recorded")),
               ("secondary constraints", ul(_g(p, "secondary_constraints") or ())),
               ("block reason", code(_g(p, "block_reason"))),
               ("tradable-cash ETA (UTC)", esc(_g(horizon, "tradable_cash_release_eta_utc"))),
               ("capital horizon reasons", ul(_g(horizon, "reasons") or ())),
               ("counterfactual fill", badge_code(_g(p, "fill_status"))),
               ("fill reason", code(_g(p, "fill_reason"))),
               ("policy", esc(pr.policy_label(p))),
               ("merged decision ids", ul(_g(side, "merged_decision_ids") or ()))]))
    if _g(side, "top_of_book_limited"):
        body += (f'<p class="note">{icon("triangle-alert", "ic-sm k-warn")} Depth: only the recorded top of book is '
                 "used, so every liquidity cap is top-of-book-limited.</p>")
    rows = _g(side, "comparison") or []
    body += disclosure(f"Compare policies ({len(rows)})", sizing_comparison(rows, computed=available),
                       open_=bool(rows) and available)
    return head + recorded + body


def research_sizing(panel: Mapping[str, Any], *, note: str = "") -> str:
    """RESEARCH SIZING / SHADOW SIZING CHALLENGER: Lane A's `panel_for_market` result, read-only.

    Every figure is the contract's string, only formatted. There is no stake input, slider,
    submit or order action, and nothing is labelled a recommendation to bet. `note` carries a
    data-layer caveat (for example a replay made without the evidence database)."""
    label = f'<p class="eyebrow">{esc(_g(panel, "label") or "RESEARCH SIZING")}</p>'
    primary = _g(panel, "primary_policy")
    parts = [label, f'<p class="note">{esc(SIZING_NOTE)}</p>']
    if note:
        parts.append(f'<p class="note">{icon("triangle-alert", "ic-sm k-warn")} {esc(note)}</p>')
    if primary:
        parts.append(f'<p class="meta">Challenger policy {esc(pr.policy_label(primary))}'
                     + (f" — {esc(_g(primary, 'description'))}" if _g(primary, "description") else "") + "</p>")
    sides = [s for s in (_g(panel, "sides") or []) if isinstance(s, Mapping)]
    if not _g(panel, "available") and not sides:
        reason = _g(panel, "unavailable_reason") or "Unavailable"
        detail = _g(panel, "unavailable_detail") or "The research sizing panel is unavailable."
        parts.append(unavailable(reason, detail) if reason in SIZING_NO_DATA else blocked_state(reason, detail))
    parts.extend(sizing_side(s) for s in sides)
    limits = _g(panel, "limitations") or ()
    parts.append(disclosure("Limitations of this replay", ul(limits) + kv([
        ("panel version", esc(_g(panel, "panel_version"))), ("market", code(_g(panel, "market_id"))),
        ("replay clock (UTC)", esc(_g(panel, "as_of_utc")))])))
    return "".join(parts)
