"""Wallet research (/experiments/wallet): Market v1 journey J4, read-only (issue 168).

Public-history coverage, the point-in-time selection, leader versus follower results, category fit, uncertainty and
copying status. No wallet source is approved, so production shows the blocked state and the copying status only.
Demo mode shows Demonstration A (`wallet_intel.demo.run_synthetic_demo`), labelled SYNTHETIC on every section: it
proves engineering only and is evidence about no real trader. Figures are the report's own text, formatted; nothing
is recomputed, nothing is green, and money is signed but never coloured. Copying is research only: no execution path
exists (W8 needs an ADR 0043 amendment). Lives under Research & Data (nav "research"); no global navigation item.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import components as c
from .. import data as d
from .. import presentation as pr
from ..html import esc
from . import common as cm
from . import ops_common as oc

PATH = "/experiments/wallet"
SYN = "SYNTHETIC"
STATUS_WORDS = {"ELIGIBLE": ("Eligible at selection", "info"), "INELIGIBLE": ("Not eligible", "nd"),
                "INACTIVE": ("Inactive", "nd")}
BASIS_WORDS = {"OBSERVED": "observed in the synthetic history", "ESTIMATED": "simulated estimate",
               "UNKNOWN": "unknown"}


def utc_day(ts: Any) -> str | None:
    """A synthetic report's date as its own UTC day (the synthetic clock is UTC midnight; ET would shift it)."""
    parsed = pr.to_et(ts)
    return None if parsed is None or not isinstance(ts, str) else f"{ts[:10]} UTC"


def syn_badge() -> str:
    return c.badge("WALLET_SYNTHETIC", label="SYNTHETIC · not evidence", kind="warn")


def lab_money(v: Any, *, signed: bool = False) -> str:
    """A labelled value {value, basis, note}: its money, or the unavailable marker with the report's own reason."""
    if not isinstance(v, dict):
        return oc.money(None, "not in the report")
    return oc.money(v.get("value"), v.get("note") or "unknown", signed=signed)


def lab_basis(v: Any) -> str:
    if not isinstance(v, dict):
        return "not in the report"
    basis = BASIS_WORDS.get(v.get("basis"), str(v.get("basis")))
    return f"{basis}{' · ' + v['note'] if v.get('note') else ''}"


def _interval(rate: Any) -> str:
    if not isinstance(rate, dict):
        return c.na("not computed")
    lo, hi, mean = pr.percent(rate.get("lower")), pr.percent(rate.get("upper")), pr.percent(rate.get("posterior_mean"))
    level = pr.percent(rate.get("level"), 0)
    if None in (lo, hi, mean):
        return c.na("not computed")
    return c.num(f"{mean} ({level} interval {lo}–{hi})")


def _section(title: str, body: str, sid: str, meta: str = "") -> str:
    return c.section(title, f"<p>{syn_badge()}</p>" + body, meta=f"{SYN}{' · ' + meta if meta else ''}", sid=sid)


def coverage_section(r: dict) -> str:
    ingest = oc.g(r, "classify", "ingest") or {}
    leaders = oc.g(r, "reconcile", "leaders") or {}
    rows = []
    for role in sorted(ingest):
        first, second = ingest[role].get("first") or {}, ingest[role].get("second") or {}
        acct = oc.g(leaders, role, "account") or {}
        complete = acct.get("coverage_complete")
        rows.append([esc(role), c.code(acct.get("account")), c.num(pr.count(first.get("added"))),
                     c.num(pr.count(second.get("duplicates"))), c.num(pr.count(first.get("conflicts"))),
                     esc("yes" if complete else "no" if complete is False else "not reconciled at selection"),
                     c.ul(acct.get("coverage_notes") or [], empty="none")])
    body = c.table(["Leader", "Account", "Observations", "Re-read duplicates", "Conflicts", "History complete",
                    "Notes"], rows, right=(2, 3, 4), wrap=(6,), caption="Synthetic public-history coverage")
    body += ('<p class="note">Coverage is of a synthetic universe. Deposits and withdrawals are never observed, so '
             "leader equity stays unknown.</p>")
    return _section("Public-history coverage", body, "wl-cov", "synthetic universe")


def selection_section(r: dict) -> str:
    m = oc.g(r, "eligibility", "manifest") or {}
    records = oc.lst(m, "records") or []
    eligible = [x for x in records if x.get("status") == "ELIGIBLE"]
    body = c.facts([
        ("Selection date", c.txt(utc_day(m.get("selected_at")), reason="not recorded")),
        ("Label version", c.txt(m.get("label_version"))),
        ("Rule", c.txt(f"{oc.g(m, 'rule', 'rule_id')} v{oc.g(m, 'rule', 'version')}")),
        ("Selection trials", c.num(pr.count(m.get("trials")))),
        ("Eligible", c.num(f"{len(eligible)} of {len(records)}")),
        ("Not yet discovered", c.num(pr.count(m.get("excluded_not_yet_discovered")))),
    ], text_cols=(0, 1, 2))
    if not eligible:
        body += c.empty_state("No leader eligible at the selection date", "Every candidate failed the rule; nothing "
                                                                          "is followed.")
    body += c.table(["Account", "Discovered", "Status", "Reasons"],
                    [[c.code(x.get("account")), c.txt(utc_day(x.get("discovered_at")), reason="not recorded"),
                      oc.word(STATUS_WORDS, x.get("status"), "WALLET"), c.ul(x.get("reasons") or [], empty="none")]
                     for x in records], wrap=(3,), caption="Point-in-time selection manifest")
    body += c.disclosure("Manifest identity", c.kv([("Version", c.code(m.get("version"))),
                                                    ("Inputs digest", c.code(m.get("inputs_digest")))]))
    return _section("Selection (point in time)", body, "wl-sel", "walk-forward: only later events are replayed")


def results_section(r: dict) -> str:
    rp = oc.g(r, "replay") or {}
    follower, leader = rp.get("follower") or {}, rp.get("leader") or {}
    unknown = rp.get("unknown_fee_variant") or {}
    band = oc.lst(r, "difference", "cluster_bootstrap_90")
    body = c.facts([
        ("Follower gross", lab_money(follower.get("gross_pnl"), signed=True)),
        ("Follower fees", lab_money(follower.get("fees"))),
        ("Follower net", lab_money(follower.get("net_pnl"), signed=True)),
        ("Leader, scaled to follower", lab_money(leader.get("scaled_to_follower"), signed=True)),
        ("Signals", c.num(pr.count(rp.get("signals")))),
        ("Unknown fills", c.num(pr.count(follower.get("unknown_fills")))),
    ])
    if band and len(band) == 3 and all(pr.dec(str(x)) is not None for x in band):
        mean, lo, hi = (pr.money(str(x), signed=True) for x in band)
        spans = pr.dec(str(band[1])) < 0 < pr.dec(str(band[2]))
        body += (f'<p class="note">Follower net minus leader-scaled gross, per event: mean {esc(mean)}, 90% cluster '
                 f"bootstrap interval {esc(lo)} to {esc(hi)}."
                 + (" The interval spans zero." if spans else "") + "</p>")
    else:
        body += '<p class="note">Difference interval: not computed (too few events).</p>'
    body += c.disclosure("Basis of each figure", c.kv([
        ("Follower", esc(lab_basis(follower.get("net_pnl")))), ("Leader", esc(lab_basis(leader.get("scaled_to_follower")))),
        ("With fees unknown", esc(f"net {lab_basis(unknown.get('net_pnl'))}")),
    ]))
    by_event = oc.g(r, "difference", "by_event") or {}
    body += c.disclosure("Difference by event", c.table(
        ["Event", "Follower net − leader scaled"], [[esc(k), lab_money(v, signed=True)] for k, v in sorted(by_event.items())],
        right=(1,), caption="Difference by event", empty="no event replayed"))
    return _section("Leader versus follower", body, "wl-res", "simulated follower · observed leader · not profit")


def category_section(r: dict) -> str:
    records = oc.lst(oc.g(r, "eligibility", "manifest"), "records") or []
    rows = []
    for x in records:
        if x.get("status") != "ELIGIBLE":
            continue
        dims = x.get("dimensions") or {}
        for cat, rate in sorted((dims.get("category_win_rates") or {}).items()):
            rows.append([c.code(x.get("account")), esc(cat), c.num(f"{rate.get('wins')} of {rate.get('trials')}"),
                         _interval(rate)])
    body = c.table(["Leader", "Category", "Event wins", "Shrunk rate"], rows, right=(2,),
                   caption="Category fit of eligible leaders", empty="no eligible leader, so no category fit")
    return _section("Category fit", body, "wl-cat", "eligible leaders · shrunk toward a prior")


def uncertainty_section(r: dict) -> str:
    mt = oc.g(r, "eligibility", "multiple_testing") or {}
    records = oc.lst(oc.g(r, "eligibility", "manifest"), "records") or []
    rows = [[c.code(x.get("account")), oc.word(STATUS_WORDS, x.get("status"), "WALLET"),
             _interval(oc.g(x, "dimensions", "event_win_rate"))] for x in records]
    body = c.facts([("Hypotheses screened", c.num(pr.count(mt.get("hypotheses")))),
                    ("Survivors", c.num(pr.count(len(mt.get("survivors") or [])))),
                    ("Independent clusters", c.num(pr.count(oc.g(r, "eligibility", "independent_clusters"))))])
    body += f'<p class="note">{esc(mt.get("note") or "")}</p>'
    body += c.table(["Account", "Status", "Event win rate"], rows, caption="Event win rates with intervals")
    return _section("Uncertainty", body, "wl-unc", "intervals, not scores")


def benchmarks_section(r: dict) -> str:
    bench = {k: v for k, v in (r.get("benchmarks") or {}).items() if isinstance(v, dict)}
    ladder = oc.lst(r, "ladder", "rows") or []
    body = c.table(["Benchmark", "Gross", "Fees", "Net", "Unknown fills"],
                   [[esc(k.replace("_", " ").lower()), lab_money(v.get("gross_pnl"), signed=True), lab_money(v.get("fees")),
                     lab_money(v.get("net_pnl"), signed=True), c.num(pr.count(v.get("unknown_fills")))]
                    for k, v in sorted(bench.items())], right=(1, 2, 3, 4), caption="Benchmarks")
    body += c.disclosure("Size and delay ladder", c.table(
        ["Risk per signal", "Delay", "Follower gross", "Follower net", "Leader scaled", "Filled"],
        [[oc.money(x.get("risk_per_signal")), c.num(pr.duration_text(x.get("detection_delay_s"))),
          lab_money(x.get("follower_gross"), signed=True), lab_money(x.get("follower_net"), signed=True),
          lab_money(x.get("leader_scaled"), signed=True), c.num(pr.count(x.get("filled")))] for x in ladder],
        right=(0, 1, 2, 3, 4, 5), caption="Size and delay ladder"))
    checks = oc.g(r, "reconciliation", "checks") or {}
    body += c.disclosure("Position reconciliation", c.kv([(k.replace("_", " "), esc("passed" if v else "FAILED"))
                                                          for k, v in sorted(checks.items())]))
    return _section("Benchmarks and ladder", body, "wl-bench", "same signals, other policies")


def copying_section() -> str:
    body = c.blocked_state("Research only · no execution",
                           "No wallet-driven order path exists. The typed bridge to execution (W8) needs an explicit "
                           "ADR 0043 amendment in its own reviewed PR; live public reads, paid feeds and an empirical "
                           "evaluation each need their own owner approval (activation packet Decision 5).",
                           action=("/setup", "Setup & readiness"))
    return c.section("Copying status", body, sid="wl-copy")


def wallet_body(loaded: d.Loaded, now: datetime) -> str:
    missing = cm.loaded_state("Wallet research", loaded)
    if missing:
        return missing + copying_section()
    value = loaded.value or {}
    if value.get("state") == "NOT_AUTHORIZED":
        return (c.blocked_state("No wallet source is approved",
                                "Wallet intelligence runs on synthetic fixtures and documentation examples only, with no "
                                "network read. Demonstration A (SYNTHETIC) is shown in demo mode only, because the "
                                "Terminal shows synthetic data only there.", action=("/setup", "Setup & readiness"))
                + copying_section())
    r = value.get("report") or {}
    head = c.status_line("warn", "SYNTHETIC research demonstration — not evidence",
                         f"{r.get('disclaimer') or ''} Report {r.get('demo_version')} · seed {r.get('seed')} · "
                         f"selection date {utc_day(r.get('selection_date'))} · horizon "
                         f"{utc_day(r.get('horizon'))}.")
    return "".join([head, coverage_section(r), selection_section(r), results_section(r), category_section(r),
                    uncertainty_section(r), benchmarks_section(r), copying_section(),
                    c.disclosure("Report identity", c.kv([("Report sha256", c.code(r.get("report_sha256"))),
                                                          ("Data class", c.code(r.get("data_class")))]))])


def view(ctx: d.Context, p: pr.Params) -> cm.Page:
    head = c.page_head("Wallet research", "Owner Idea 168 · leader selection and follower replay · research only",
                       crumb=oc.crumb("/experiments", "Research & Data"))
    body = wallet_body(d.wallet_research(ctx), ctx.now)
    return cm.Page("Wallet research", "research", head + oc.journey_tabs(PATH) + '<div class="stack">' + body + "</div>")
