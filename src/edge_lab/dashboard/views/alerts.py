"""Alerts (/alerts) and More (/more). docs/design/UI_CONTRACT.md §18. Nothing here sends anything."""

from __future__ import annotations

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm

GROUPS = (("attention", "Needs attention"), ("standing", "Standing conditions"), ("recent", "Recent notifications"),
          ("checks", "Tests, verification checks and diagnostics"), ("expired", "Expired"))
GROUP_META = {"checks": "never counted as attention · not production incidents"}


def _row(a: cm.Alert) -> str:
    origin = f"{c.badge(pr.origin_code(a.origin))} " if a.raw is not None else ""
    extra = (f'<p class="meta">{origin}{esc(a.delivery)}' + (f" · {esc(a.subject)}" if a.subject else "") + "</p>")
    if a.raw is not None:
        extra += c.disclosure("Notification record", c.kv([(k, esc(v if not isinstance(v, (dict, list)) else cm.jdump(v)))
                                                           for k, v in sorted(a.raw.items())]))
    title = a.title if a.group != "expired" else f"Expired · {a.title}"
    return c.activity_row(a.kind if a.group != "expired" else "nd", title, a.reason, a.when_utc,
                          href=a.href if a.group != "expired" else None, extra_html=extra)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    items = cm.alerts(ctx)
    head = c.page_head("Alerts", "Read from the local notification outbox, failure records and pipeline evidence. "
                                 "Nothing is sent from here.")
    parts = [head]
    note = ('<p class="note">Delivery states: <strong>Recorded locally</strong> means a row exists in the outbox file. '
            "Delivery attempted and delivered-by-provider are not recorded here, so phone delivery is unknown. SMS is "
            "not configured; no provider is approved.</p>"
            '<p class="note">Origins: only <strong>Production</strong> events can need attention. Tests, deployment '
            "verification checks, manual diagnostics, replays and demos are listed separately and never counted. A "
            "failure record counts as a verification check only when root confirmed it; otherwise it is a production "
            "incident, whatever it claims.</p>")
    for key, title in GROUPS:
        group = [a for a in items if a.group == key]
        group.sort(key=lambda a: str(a.when_utc or ""), reverse=True)
        if not group:
            if key == "attention":
                parts.append(c.section(title, c.empty_state("Nothing needs attention",
                                                            "No failure, conflict, stale source or critical "
                                                            "notification is recorded locally."), sid=f"al-{key}"))
            continue
        meta = f"{len(group)} item(s)" + (f" · {GROUP_META[key]}" if key in GROUP_META else "")
        parts.append(c.section(title, '<ul class="rows">' + "".join(_row(a) for a in group) + "</ul>",
                               meta=meta, sid=f"al-{key}", flush=True))
    if ctx.notifications.status == d.NO_DATA:
        parts.append(c.section("Notifications", c.unavailable("No notifications recorded yet",
                                                              "NO DATA / NOT STARTED — " + ctx.notifications.message),
                               sid="al-none"))
    elif ctx.notifications.status == d.ERROR:
        parts.append(c.section("Notifications", c.error_state("Outbox unreadable", ctx.notifications.message),
                               sid="al-none"))
    parts.append(note)
    return cm.Page("Alerts", "alerts", "".join(parts))


def more(ctx: d.Context, p: pr.Params) -> cm.Page:
    links = [("/risk", "shield", "Risk & capital", "Limits, capacity, capital release and the starter rule"),
             ("/experiments", "flask-conical", "Research & Data", "Experiments, sources and fee verification"),
             ("/alerts", "bell", "Alerts", "Failures, conflicts and recorded notifications"),
             ("/#system", "database", "System & evidence", "Collector status, pipeline receipt and account records")]
    items = "".join(
        f'<li class="row"><div class="row-main"><p class="row-title"><a href="{esc(h)}">{c.icon(i)} {esc(t)}</a></p>'
        f'<p class="row-sub">{esc(s)}</p></div><div class="row-aside">{c.icon("chevron-right")}</div></li>'
        for h, i, t, s in links)
    body = c.page_head("More") + c.section("Pages", f'<ul class="rows">{items}</ul>', sid="more-h", flush=True)
    return cm.Page("More", "more", body)
