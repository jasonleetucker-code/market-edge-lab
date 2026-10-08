"""Setup & readiness (/setup): Market v1 journey J1, read-only.

Every missing permission, environment, provider fact or approval, each with its safe next step. Sources:
- the code's authorized environments and risk-limit state, from the execution status export (never an import of
  the execution package, ADR 0043);
- the static manifest `ops_manifest` (EXECUTION_PLAN, the execution ledger's "Facts that must be confirmed" and the
  activation packet), pinned to those documents by tests.

When the export is missing or unreadable, the documented authority is shown and labelled as documented, never as the
code's value. Nothing here is green and nothing is an action: the Terminal has no command surface. Lives under More
(nav "more"); no global navigation item is added.
"""

from __future__ import annotations

from datetime import datetime

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from . import ops_common as oc
from . import ops_manifest as mf

PATH = "/setup"


def item_row(item: mf.Item) -> str:
    label, kind = mf.STATE_WORDS.get(item.state, (item.state, "nd"))
    body = c.facts([("Safe next step", c.txt(item.next_step)), ("Who", c.txt(item.who)),
                    ("Source", c.txt(item.source))], wide=True, text_cols=(0, 1, 2))
    return c.row(esc(item.title), sub=item.detail, aside=c.state_text(f"SETUP_{item.state}", label=label, kind=kind),
                 body=body)


def environments_section(loaded: d.Loaded) -> str:
    missing, es = oc.export_state(loaded)
    env_items = {i.item_id.removeprefix("env-").upper(): i for i in mf.ITEMS if i.kind == "ENVIRONMENT"}
    if es is None:
        why = ("no executor has written an export here" if loaded.status == d.NO_DATA else
               "the export cannot be used")
        note = (f'<p class="note">The code\'s value is not readable ({esc(why)}). As documented: only '
                f'{esc(", ".join(mf.DOCUMENTED_AUTHORIZED))} is authorized ({esc(mf.PLAN)}).</p>')
        rows = [item_row(i) for i in env_items.values()]
        return c.section("Environments", note + '<ul class="rows">' + "".join(rows) + "</ul>",
                         meta="documented authority · code value unknown", sid="su-env")
    doc = es.doc
    rows = []
    for r in oc.lst(doc, "environments", "rows") or []:
        name = r.get("environment")
        if r.get("authorized"):
            rows.append(c.row(esc(name), sub=str(r.get("note") or ""),
                              aside=c.state_text(f"SETUP_ENV_{name}", label="Authorized · offline only", kind="nd"),
                              body=c.facts([("What it allows", c.txt("The fake venue and disposable stores only. No "
                                                                     "real account, key or money."))],
                                           wide=True, text_cols=(0,))))
        elif name in env_items:
            rows.append(item_row(env_items[name]))
        else:
            rows.append(c.row(esc(name), sub=str(r.get("note") or ""),
                              aside=c.state_text("SETUP_NOT_AUTHORIZED", label="Not authorized", kind="warn")))
    meta = f"from the execution export, generated {pr.datetime_et(doc.get('generated_at_utc')) or 'at an unknown time'}"
    stale = "" if es.export_freshness == "FRESH" else (
        '<p class="note">The export is not current; environments change only by a reviewed code change, so this list '
        "is still the code's value at that time.</p>")
    return c.section("Environments", stale + '<ul class="rows">' + "".join(rows) + "</ul>", meta=meta, sid="su-env")


def limits_row(loaded: d.Loaded) -> str:
    _, es = oc.export_state(loaded)
    limits = oc.g(es.doc, "limits") if es is not None else None
    if es is None or limits is None:
        state = c.state_text("SETUP_UNKNOWN", label="Unknown here", kind="nd")
        sub = "The limits in force are not readable here (no export, or the exporter had no configuration)."
    elif limits.get("placeholder") or limits.get("owner_approval_ref") is None:
        state = c.state_text("SETUP_PLACEHOLDER", label="Placeholders · refuse every order", kind="warn")
        sub = "The executor runs with placeholder limits: every order is refused until the owner sets values."
    else:
        ref = str(limits.get("owner_approval_ref"))
        fixture = es.doc.get("environment") == "FIXTURE"  # decided by the environment, never by the name
        state = c.state_text("SETUP_FIXTURE_LIMITS" if fixture else "SETUP_LIMITS_REF",
                             label="FIXTURE limits · not owner-set" if fixture else f"Limits reference {ref}",
                             kind="warn")
        sub = f"The exporter's configuration names {ref}."
    return c.row(esc("Risk limits in force (from the export)"), sub=sub, aside=state,
                 body=c.facts([("Safe next step", c.txt("Owner: set the values (see Risk-limit values above).")),
                               ("Source", c.txt("execution_status.json · limits"))], wide=True, text_cols=(0, 1)))


def kind_section(kind: str, title: str, extra: str = "") -> str:
    items = [i for i in mf.ITEMS if i.kind == kind]
    body = '<ul class="rows">' + "".join(item_row(i) for i in items) + extra + "</ul>"
    return c.section(title, body, meta=f"{len(items)} item{'s' if len(items) != 1 else ''}", sid=f"su-{kind.lower()}",
                     flush=True)


def tracks_section() -> str:
    rows = [[c.code(name), esc(state)] for name, state, _ in mf.TRACKS]
    return c.section("Readiness tracks", c.table(["Track", "State"], rows, caption="Market v1 readiness tracks") +
                     f'<p class="note">As recorded in {esc(mf.ACCEPTANCE)} §1; a track changes only there, on its '
                     "own evidence.</p>", sid="su-tracks")


def setup_body(loaded: d.Loaded, now: datetime) -> str:
    missing, es = oc.export_state(loaded)
    count = sum(1 for i in mf.ITEMS if i.state != "NEVER_REQUESTED")
    parts = [c.status_line("warn", f"{count} items need an owner, provider or approval step",
                           "Nothing on this page can be done from the Terminal: each safe next step names who acts "
                           "and where.")]
    if es is not None:
        parts.append(oc.export_status_line(es, now))
    elif missing:
        parts.append(missing)
    parts += [environments_section(loaded),
              kind_section("APPROVAL", "Owner approvals", extra=limits_row(loaded)),
              kind_section("PERMISSION", "Permissions and credentials"),
              kind_section("PROVIDER_FACT", "Provider facts to confirm"),
              tracks_section(),
              c.disclosure("About this list", c.kv([
                  ("Manifest", esc(mf.MANIFEST_VERSION)),
                  ("Sources", c.ul([mf.PLAN, mf.LEDGER, mf.PACKET, mf.ACCEPTANCE])),
                  ("Pinned", esc("Each item quotes its source; a test fails when the source no longer says it.")),
              ]))]
    return "".join(parts)


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head("Setup & readiness", "What is missing before anything leaves FIXTURE, and the safe next step "
                                            "for each · read-only", crumb=oc.crumb("/more", "More"))
    body = setup_body(d.execution_status(ctx), ctx.now)
    return cm.Page("Setup & readiness", "more", head + oc.journey_tabs(PATH) + '<div class="stack">' + body + "</div>")
