"""Shared pieces of the operator journeys (Market v1 J1, J4, J5, J6): the journey strip, the execution export's
states and labels. Composition only: every figure is the export's own text, formatted by `presentation`.

The export (`execution_status.json`, schema edge-lab-execution-status/1) is written by the execution package and read
here as a file (ADR 0043: the dashboard never imports that package). Honesty rules shared by every journey:
- a missing export is "no export", never an empty account; an unreadable one is an error, never empty;
- a stale export is labelled as of its generation time and never reads as current;
- every execution figure carries its environment (today only FIXTURE), and FIXTURE is never shown as real;
- unknown is the unavailable marker with its reason, never 0; nothing is green.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc

# The only execution environments this Terminal renders: today's `AUTHORIZED_ENVIRONMENTS` (FIXTURE), pinned by
# tests/execution/test_status_export.py. Any other environment is refused, whatever the export claims.
TERMINAL_ENVIRONMENTS = ("FIXTURE",)
JOURNEYS = (("/setup", "Setup & readiness"), ("/experiments/wallet", "Wallet research"),
            ("/positions/execution", "Execution portfolio"), ("/risk/automation", "Automation"))
ENV_LABELS = {"FIXTURE": "FIXTURE · fake venue · not a real account", "DEMO": "DEMO · venue mock funds",
              "PRODUCTION": "PRODUCTION · real money"}
NO_EXPORT_TITLE = "No execution export"
NO_EXPORT_TEXT = "Nothing is known about any execution account here. This is not an empty portfolio."
MODE_WORDS = {  # (label, kind): nothing is green; an armed mode is information, not success
    "DISARMED": ("Disarmed · no new risk", "warn"), "OBSERVE_ONLY": ("Observe only · reads", "info"),
    "SHADOW": ("Shadow · decides, never sends", "info"), "DEMO": ("Demo · mock funds", "warn"),
    "HUMAN_CONFIRMATION": ("Human confirmation · per order", "info"),
    "BOUNDED_AUTO": ("Bounded auto · inside a grant", "info"),
}
RECON_WORDS = {"COMPLETE": ("Reconciled", "info"), "PARTIAL": ("Reconciliation partial", "warn"),
               "FAILED": ("Reconciliation failed", "err"), "NOT_RUN": ("Not reconciled yet", "warn")}
UNKNOWN_REASON = "unknown: not recorded in the export"


def journey_tabs(current: str) -> str:
    return c.tabs([(href, text, href == current, None) for href, text in JOURNEYS], label="Operator journeys")


def crumb(href: str, text: str) -> str:
    return f'<a class="crumb" href="{esc(href)}">{c.icon("arrow-left", "ic-sm")}<span>{esc(text)}</span></a>'


def word(table: dict, code: Any, prefix: str, *, capsule: bool = False) -> str:
    label, kind = table.get(code, (str(code).replace("_", " ").capitalize() if code else "Not recorded", "nd"))
    return (c.badge if capsule else c.state_text)(f"{prefix}_{code}", label=label, kind=kind)


def env_badge(env: Any) -> str:
    return c.badge(f"EXEC_ENV_{env}", label=ENV_LABELS.get(env, f"{env} · unrecognized environment"), kind="warn")


def money(value: Any, reason: str = UNKNOWN_REASON, *, signed: bool = False) -> str:
    """Money with its sign, never coloured: execution figures here are FIXTURE figures (a green one reads as a result)."""
    return c.num(pr.money(value, signed=signed), reason=reason)


def qty(value: Any, reason: str = UNKNOWN_REASON) -> str:
    return c.num(pr.quantity(value), reason=reason)


def price(value: Any, reason: str = UNKNOWN_REASON) -> str:
    return c.num(pr.cents(value), reason=reason)


def when(ts: Any, reason: str = "time not recorded") -> str:
    return c.txt(pr.datetime_et(ts), reason=reason)


def seconds(value: Any, reason: str = UNKNOWN_REASON) -> str:
    return c.num(pr.duration_text(value), reason=reason)


def g(obj: Any, *keys: str) -> Any:
    """A nested value of the export, or None when any level is missing or not a mapping."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def lst(obj: Any, *keys: str) -> list | None:
    """A list from the export: None when absent (unknown), the list when present (possibly a known empty one)."""
    value = g(obj, *keys)
    return value if isinstance(value, list) else None


def export_state(loaded: d.Loaded) -> tuple[str | None, d.ExecutionStatus | None]:
    """(the state HTML when the export is not usable, the status when it is)."""
    if loaded.status == d.NO_DATA:
        return c.unavailable(NO_EXPORT_TITLE, f"{loaded.message[:1].upper()}{loaded.message[1:]}. {NO_EXPORT_TEXT}",
                             action=("/setup", "Setup & readiness")), None
    if loaded.status == d.ERROR:
        return c.error_state("Execution export unavailable", "Data unavailable — " + loaded.message), None
    es = loaded.value
    env = es.doc.get("environment")
    authorized = g(es.doc, "environments", "authorized")
    # This Terminal's own allowlist decides, never the export's list: its "no real account" wording is only true of
    # these environments. A changed authorization needs a reviewed change here too.
    if env not in TERMINAL_ENVIRONMENTS:
        return c.blocked_state("Export refused: environment not shown here",
                               f"The export names the {env} environment. This Terminal shows only "
                               f"{', '.join(TERMINAL_ENVIRONMENTS)} exports, so nothing from it is shown."), None
    if not isinstance(authorized, list) or sorted(authorized) != sorted(TERMINAL_ENVIRONMENTS):
        return c.error_state("Authorized environments do not match",
                             f"The export says the code authorizes {authorized}; this Terminal expects "
                             f"{list(TERMINAL_ENVIRONMENTS)}. Nothing from the export is shown until a reviewed "
                             "change reconciles them."), None
    return None, es


def export_status_line(es: d.ExecutionStatus, now: datetime) -> str:
    doc = es.doc
    generated = doc.get("generated_at_utc")
    at = pr.datetime_et(generated) or "an unknown time"
    age = pr.age_text(generated, now)
    stamp = f"Generated {at}" + (f" ({age})" if age else "")
    minutes = int(es.max_age.total_seconds() // 60)
    chain = g(doc, "journal", "chain_ok")
    events = g(doc, "journal", "chain_events")
    chain_text = (" Journal chain verification not recorded." if chain is None else
                  f" Journal chain verified at export ({events if events is not None else 'unknown number of'} events)."
                  if chain else " Journal chain problems at export: see Details.")
    env = doc.get("environment")
    if es.export_freshness == "FRESH":
        return c.status_line("info", f"Execution export · {ENV_LABELS.get(env, env)}", stamp + "." + chain_text)
    if es.export_freshness == "STALE":
        return c.status_line("warn", "Stale export — not current",
                             f"{stamp}, more than {minutes} min ago: every figure below is as of then, not now."
                             + chain_text)
    return c.status_line("warn", "Export time unknown — not current",
                         "The export's generation time is missing or in the future, so nothing below is current."
                         + chain_text)


def journal_state(doc: dict) -> str | None:
    """The state HTML when the export carries no journal reading (NO_JOURNAL or ERROR), else None."""
    state, detail = g(doc, "journal", "state"), g(doc, "journal", "detail") or ""
    if state == "NO_JOURNAL":
        return c.unavailable("No execution journal",
                             f"The exporter found no journal ({detail}): no executor has run for this account. "
                             "Holdings, orders and controls are unknown, not empty.")
    if state == "ERROR":
        return c.error_state("Execution journal unreadable", f"Data unavailable — {detail}")
    return None


def paused_line(doc: dict, *, link: bool = True) -> str | None:
    """A warning when the controller holds no new risk because of incidents, latches or a lost reconciliation."""
    control = g(doc, "control") or {}
    incidents, latches = lst(control, "open_incidents") or [], lst(control, "latches") or []
    mode, recon = control.get("mode"), control.get("reconciliation")
    reasons = []
    if incidents:
        reasons.append(f"{len(incidents)} open incident{'s' if len(incidents) != 1 else ''}")
    if latches:
        reasons.append(f"{len(latches)} new-risk latch{'es' if len(latches) != 1 else ''}")
    if recon != "COMPLETE":
        reasons.append(RECON_WORDS.get(recon, (f"reconciliation {recon}", ""))[0].lower())
    if not reasons:
        return None
    title = "Paused · no new risk" if mode == "DISARMED" or incidents else "New risk restricted"
    if not link:
        return c.status_line("warn", title, " · ".join(reasons) + ".")
    return c.status_line("warn", title, " · ".join(reasons) + ". Stop reasons and the rearm procedure:",
                         detail_html=" " + c.link("/risk/automation", "Automation"))


def no_control_note() -> str:
    return ('<p class="note">This Terminal is read-only: it cannot arm, disarm, approve, cancel or send anything. '
            "Operator actions happen in the executor process; the private command surface (J9) is not built.</p>")
