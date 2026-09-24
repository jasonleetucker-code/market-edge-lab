"""Per-domain research-readiness / learning-history completeness report (#50, ADR 0033).

The one canonical owner of "is this domain's learning history complete enough to research?".
It answers, per domain (weather = EXP-001 KXHIGHNY; sports = the NFL Odds API pilot plus the
Polymarket US research lane), whether each prerequisite of a later analysis is present:

    raw_evidence, market_quote_history, model_estimate, decisions (rejected included),
    later_price, consensus, settlement_linkage  ->  research_ready

Each is YES / PARTIAL / NOT_YET / UNKNOWN (or NOT_APPLICABLE by design), with the evidence
count and the reason. Everything is **computed from the real stores** (the evidence store and
the shadow ledger, both opened read-only; the experiment registry file), never hard-coded:

- a store that is missing, unreadable or not given makes what depends on it UNKNOWN, never YES;
- zero evidence is NOT_YET; some-but-not-all is PARTIAL; YES needs every counted item present;
- research_ready is YES only when every applicable prerequisite is YES.

Vocabulary follows docs/research/LEARNING_HISTORY_COVERAGE.md (RAW, MARKET, MODEL, DECISION,
LATER MARKET, OUTCOME; gap ids such as P0-1, P1-1, P1-5). Network-free and read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

READINESS_VERSION = "research-readiness-v1"
SCHEMA = "research-readiness/1"
UTC = timezone.utc
REPO_EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
WEATHER_EXPERIMENT = "EXP-001"
FORWARD_PHASES = ("pfm", "decision", "recheck")
LATER_PHASES = ("post_decision_1h", "post_decision_6h", "pre_close", "close", "settlement_preceding")
SPORTS_PREFIXES = ("the_odds_api:", "polymarket_us:", "sports:")
FINAL_ODDS_STATES = ("CAPTURED", "MISSED", "FAILED", "SUPERSEDED")


class Readiness(str, Enum):
    YES = "YES"
    PARTIAL = "PARTIAL"
    NOT_YET = "NOT_YET"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # by design for this domain (coverage doc "N/A"); never counted as YES


PREREQUISITES = (
    ("raw_evidence", "Raw evidence (RAW)"),
    ("market_quote_history", "Market / quote history (MARKET)"),
    ("model_estimate", "Model / decision-time estimate (MODEL)"),
    ("decisions", "Decisions, rejected included (DECISION)"),
    ("later_price", "Later price (LATER MARKET)"),
    ("consensus", "Consensus benchmark"),
    ("settlement_linkage", "Settlement / outcome linkage (OUTCOME)"),
)
_TITLES = dict(PREREQUISITES) | {"research_ready": "Research-ready"}


@dataclass(frozen=True)
class Prerequisite:
    key: str
    title: str
    state: Readiness
    evidence_count: int | None  # None when it could not be counted (UNKNOWN / NOT_APPLICABLE)
    reason: str
    counts: tuple[tuple[str, int], ...] = ()
    coverage_ref: str | None = None  # the LEARNING_HISTORY_COVERAGE gap id, when one applies


@dataclass(frozen=True)
class DomainReadiness:
    domain: str
    scope: str
    lifecycle: str
    lifecycle_basis: str
    prerequisites: tuple[Prerequisite, ...]
    research_ready: Prerequisite


@dataclass(frozen=True)
class ReadinessReport:
    as_of_utc: str
    evidence_store: str  # OK / MISSING / UNREADABLE: <why>
    shadow_ledger: str  # OK / NOT_GIVEN / MISSING / UNREADABLE: <why>
    domains: tuple[DomainReadiness, ...]
    schema: str = SCHEMA
    version: str = READINESS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        out = {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, Prerequisite):
            out["counts"] = {k: v for k, v in value.counts}
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _p(key: str, state: Readiness, count: int | None, reason: str, counts: Mapping[str, int] | None = None,
       ref: str | None = None) -> Prerequisite:
    return Prerequisite(key, _TITLES[key], state, count, reason, tuple(sorted((counts or {}).items())), ref)


def _fraction(key: str, have: int, of: int, what: str, *, ref: str | None = None,
              counts: Mapping[str, int] | None = None, extra: str = "") -> Prerequisite:
    """YES only when every counted item is present; PARTIAL for some; NOT_YET for none."""
    if of <= 0 or have <= 0:
        state = Readiness.NOT_YET
    elif have < of:
        state = Readiness.PARTIAL
    else:
        state = Readiness.YES
    return _p(key, state, have, f"{have} of {of} {what}{extra}", counts, ref)


def _unknown(key: str, why: str) -> Prerequisite:
    return _p(key, Readiness.UNKNOWN, None, why)


def _ready(prereqs: Sequence[Prerequisite]) -> Prerequisite:
    applicable = [p for p in prereqs if p.state is not Readiness.NOT_APPLICABLE]
    not_yet = [p.key for p in applicable if p.state in (Readiness.NOT_YET, Readiness.PARTIAL)]
    unknown = [p.key for p in applicable if p.state is Readiness.UNKNOWN]
    yes = sum(p.state is Readiness.YES for p in applicable)
    if not_yet:
        return _p("research_ready", Readiness.NOT_YET, yes,
                  f"{yes} of {len(applicable)} applicable prerequisites are YES; incomplete: {', '.join(not_yet)}"
                  + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
    if unknown or not applicable:
        return _p("research_ready", Readiness.UNKNOWN, yes, f"unknown: {', '.join(unknown) or 'no prerequisites'}")
    return _p("research_ready", Readiness.YES, yes, f"all {len(applicable)} applicable prerequisites are YES")


# --------------------------------------------------------------------------- store readers


@dataclass
class _Evidence:
    snapshots: dict[tuple[str, str], int]
    forward: dict[tuple[str, str], int]  # (phase, status) -> live EXP-001 captures
    forward_days: dict[str, int]  # phase -> distinct target dates with a complete live capture
    later: dict[str, set[str]]  # kalshi market_id -> later phases CAPTURED
    later_missed: int
    odds_targets: list[Mapping[str, Any]]
    odds_consensus: Any  # tuple[SnapshotConsensus, ...]


def _read_evidence(db: Path) -> tuple[_Evidence | None, str]:
    from . import odds_consensus
    from .storage import SnapshotStore

    if not db.is_file():
        return None, "MISSING"
    try:
        store = SnapshotStore.open_readonly(db)
        with closing(store._connect()) as conn:  # read-only connection (mode=ro, query_only)
            snaps = {(r[0], r[1]): int(r[2]) for r in conn.execute(
                "SELECT source, kind, COUNT(*) FROM snapshots GROUP BY source, kind")}
            forward = {(r[0], r[1]): int(r[2]) for r in conn.execute(
                "SELECT phase, status, COUNT(*) FROM forward_captures WHERE experiment = ? AND mode = 'live' "
                "GROUP BY phase, status", (WEATHER_EXPERIMENT,))}
            days = {r[0]: int(r[1]) for r in conn.execute(
                "SELECT phase, COUNT(DISTINCT target_date) FROM forward_captures WHERE experiment = ? "
                "AND mode = 'live' AND status = 'complete' GROUP BY phase", (WEATHER_EXPERIMENT,))}
            later: dict[str, set[str]] = {}
            missed = 0
            for market, phase, status in conn.execute(
                    "SELECT market_id, phase, collection_status FROM price_observations WHERE venue = 'kalshi'"):
                if phase not in LATER_PHASES:
                    continue
                if status == "CAPTURED":
                    later.setdefault(market, set()).add(phase)
                elif status in ("MISSED", "FAILED"):
                    missed += 1
        targets = [dict(r) for r in store.odds_targets()]
        consensus = odds_consensus.consensus_since(store)
    except Exception as exc:  # noqa: BLE001 - reported (missing tables, corrupt rows), never guessed around
        return None, f"UNREADABLE: {type(exc).__name__}: {exc}"
    return _Evidence(snaps, forward, days, later, missed, targets, consensus), "OK"


@dataclass
class _Decisions:
    rows: list[dict[str, Any]]  # decision payloads, with "_account"
    filled: dict[str, str]  # market_id -> event_id of FILLED positions
    settled_markets: set[str]


def _read_ledger(path: Path | None) -> tuple[_Decisions | None, str]:
    from .shadow_ledger import ShadowLedger

    if path is None:
        return None, "NOT_GIVEN"
    if not path.is_file():
        return None, "MISSING"
    try:
        ledger = ShadowLedger.open_readonly(path)
        rows: list[dict[str, Any]] = []
        filled: dict[str, str] = {}
        settled: set[str] = set()
        for account in ledger.accounts():
            for entry in ledger.entries(account):
                payload = json.loads(entry["payload_json"])
                if entry["kind"] == "decision":
                    rows.append({**payload, "_account": account})
                elif entry["kind"] == "fill" and payload.get("status") == "FILLED":
                    filled[str(payload.get("market_id"))] = str(payload.get("event_id"))
                elif entry["kind"] == "settlement":
                    settled.add(str(payload.get("market_id")))
    except Exception as exc:  # noqa: BLE001
        return None, f"UNREADABLE: {type(exc).__name__}: {exc}"
    return _Decisions(rows, filled, settled), "OK"


def _decisions(rows: Sequence[Mapping[str, Any]], none_reason: str) -> Prerequisite:
    """YES needs recorded decisions including at least one rejected one (proof rejects are kept)."""
    qualified = sum(1 for d in rows if d.get("qualification") == "QUALIFY")
    rejected = sum(1 for d in rows if d.get("qualification") == "REJECT")
    counts = {"decisions": len(rows), "qualified": qualified, "rejected": rejected,
              "accounts": len({d.get("_account") for d in rows})}
    if not rows:
        return _p("decisions", Readiness.NOT_YET, 0, none_reason, counts)
    if rejected == 0:
        return _p("decisions", Readiness.PARTIAL, len(rows),
                  f"{len(rows)} decisions, none rejected: cannot show rejected decisions are kept", counts)
    return _p("decisions", Readiness.YES, len(rows),
              f"{len(rows)} decisions recorded ({qualified} qualified, {rejected} rejected)", counts)


def _model_estimate(rows: Sequence[Mapping[str, Any]], note: str) -> Prerequisite:
    """Every decision carries the model's decision-time probability, or records that the model
    was unavailable (MODEL_UNAVAILABLE is itself evidence). A silent gap is never YES."""
    with_p = sum(1 for d in rows if (d.get("opportunity") or {}).get("model_probability") is not None)
    unavailable = sum(1 for d in rows if (d.get("opportunity") or {}).get("model_probability") is None
                      and "MODEL_UNAVAILABLE" in (d.get("reasons") or []))
    return _fraction("model_estimate", with_p + unavailable if with_p else 0, len(rows),
                     "decisions carry the decision-time model probability (or a recorded MODEL_UNAVAILABLE)",
                     counts={"decisions": len(rows), "with_model": with_p, "model_unavailable_recorded": unavailable},
                     extra=note)


def _has_offers(result: Any) -> bool:
    """A stored odds read that held at least one bookmaker (a fail-closed read has no events)."""
    return any(e.bookmaker_count for e in result.events)


def _is_sports(decision: Mapping[str, Any]) -> bool:
    ids = (str(decision.get("event_id") or ""), str(decision.get("market_id") or ""))
    return any(i.startswith(SPORTS_PREFIXES) for i in ids)


def _is_weather(decision: Mapping[str, Any]) -> bool:
    return str(decision.get("_account", "")).startswith(WEATHER_EXPERIMENT) and not _is_sports(decision)


def _experiment_status(root: Path | None, exp_id: str) -> tuple[str, str]:
    from . import experiments

    if root is None or not root.is_dir():
        return "UNKNOWN", "experiment registry not found"
    for path in experiments.discover(root):
        try:
            exp = experiments.load(path)
        except Exception as exc:  # noqa: BLE001
            return "UNKNOWN", f"{path.parent.name}/experiment.toml unreadable: {type(exc).__name__}"
        if exp.id == exp_id:
            return exp.status or "UNKNOWN", f"experiment registry: {path.parent.name}/experiment.toml status"
    return "UNKNOWN", f"{exp_id} not in the experiment registry"


# --------------------------------------------------------------------------- weather (EXP-001)


def _weather(ev: _Evidence | None, ev_state: str, dec: _Decisions | None, dec_state: str,
             experiments_root: Path | None) -> DomainReadiness:
    store_why = f"evidence store {ev_state}"
    ledger_why = f"shadow ledger {dec_state}"
    out: list[Prerequisite] = []
    if ev is None:
        out += [_unknown("raw_evidence", store_why), _unknown("market_quote_history", store_why)]
    else:
        complete = {ph: ev.forward.get((ph, "complete"), 0) for ph in FORWARD_PHASES}
        phases = sum(1 for ph in FORWARD_PHASES if complete[ph] > 0)
        counts = {f"complete_{ph}": complete[ph] for ph in FORWARD_PHASES}
        counts |= {f"days_{ph}": ev.forward_days.get(ph, 0) for ph in FORWARD_PHASES}
        counts |= {f"not_complete_{ph}": sum(n for (p, s), n in ev.forward.items() if p == ph and s != "complete")
                   for ph in FORWARD_PHASES}
        out.append(_fraction("raw_evidence", phases, len(FORWARD_PHASES),
                             "forward capture phases (pfm, decision, recheck) have a complete live capture",
                             counts=counts))
        books = ev.snapshots.get(("kalshi", "orderbook"), 0)
        rechecks = complete["recheck"]
        mq_counts = {"kalshi_orderbook_snapshots": books, "complete_recheck_captures": rechecks,
                     "kalshi_markets_snapshots": ev.snapshots.get(("kalshi", "markets"), 0)}
        if books == 0:
            out.append(_p("market_quote_history", Readiness.NOT_YET, 0, "no Kalshi order-book snapshot stored",
                          mq_counts))
        elif rechecks == 0:
            out.append(_p("market_quote_history", Readiness.PARTIAL, books,
                          f"{books} order-book snapshots but no complete re-check capture (one point, no path)",
                          mq_counts))
        else:
            out.append(_p("market_quote_history", Readiness.YES, books,
                          f"{books} order-book snapshots; {rechecks} complete re-check captures", mq_counts))
    weather = [d for d in dec.rows if _is_weather(d)] if dec is not None else []
    if dec is None:
        out += [_unknown("model_estimate", ledger_why), _unknown("decisions", ledger_why)]
    else:
        out.append(_model_estimate(weather, ""))
        out.append(_decisions(weather, "no EXP-001 decision in the shadow ledger"))
    if ev is None or dec is None:
        out.append(_unknown("later_price", store_why if ev is None else ledger_why))
    else:
        markets = sorted({str(d.get("market_id")) for d in weather if str(d.get("market_id", "")).startswith("kalshi:")})
        have = sum(1 for m in markets if ev.later.get(m))
        out.append(_fraction("later_price", have, len(markets),
                             "decided Kalshi markets have a captured later observation "
                             f"({'/'.join(LATER_PHASES)})", ref="P0-1",
                             counts={"decided_markets": len(markets), "with_later_capture": have,
                                     "later_missed_or_failed": ev.later_missed},
                             extra="; markets decided recently may not be due yet"))
    out.append(_p("consensus", Readiness.NOT_APPLICABLE, None,
                  "no multi-book consensus source exists for KXHIGHNY; the consensus benchmark is a sports "
                  "research layer (ADR 0033)"))
    if dec is None:
        out.append(_unknown("settlement_linkage", ledger_why))
    else:
        events: dict[str, set[str]] = {}
        for d in weather:
            events.setdefault(str(d.get("event_id")), set()).add(str(d.get("market_id")))
        held = {e for m, e in dec.filled.items() if e in events}
        linked = {e for m, e in dec.filled.items() if e in events and m in dec.settled_markets}
        out.append(_fraction("settlement_linkage", len(linked), len(events),
                             "decided events have an outcome linked in the ledger", ref="P1-1",
                             counts={"decided_events": len(events), "events_with_filled_position": len(held),
                                     "events_settled": len(linked), "events_without_position": len(events) - len(held)},
                             extra="; events with no held position get no venue settlement (P1-1) and "
                                   "unsettled events may not be due yet"))
    lifecycle, basis = _experiment_status(experiments_root, WEATHER_EXPERIMENT)
    return DomainReadiness("weather", "EXP-001 KXHIGHNY (Kalshi NYC daily high; NWS PFM model)", lifecycle, basis,
                           tuple(out), _ready(out))


# --------------------------------------------------------------------------- sports (NFL)


def _sports(ev: _Evidence | None, ev_state: str, dec: _Decisions | None, dec_state: str) -> DomainReadiness:
    store_why = f"evidence store {ev_state}"
    out: list[Prerequisite] = []
    if ev is None:
        out += [_unknown(k, store_why) for k in ("raw_evidence", "market_quote_history")]
    else:
        odds = ev.snapshots.get(("the_odds_api", "odds"), 0)
        with_offers = sum(1 for s in ev.odds_consensus if _has_offers(s))
        pm = sum(n for (src, _), n in ev.snapshots.items() if src == "polymarket_us")
        rcounts = {"odds_snapshots": odds, "odds_snapshots_with_offers": with_offers,
                   "odds_discovery_snapshots": ev.snapshots.get(("the_odds_api", "events"), 0),
                   "polymarket_us_snapshots": pm}
        if with_offers == 0:
            out.append(_p("raw_evidence", Readiness.NOT_YET, 0,
                          f"no stored odds snapshot holds offers ({odds} odds snapshots stored)", rcounts))
        else:
            out.append(_p("raw_evidence", Readiness.YES, with_offers,
                          f"{with_offers} odds snapshots with offers; {pm} Polymarket US snapshots", rcounts))
        states: dict[str, int] = {}
        for t in ev.odds_targets:
            states[str(t["state"])] = states.get(str(t["state"]), 0) + 1
        captured = states.get("CAPTURED", 0)
        lost = states.get("MISSED", 0) + states.get("FAILED", 0)
        mcounts = {f"targets_{k.lower()}": v for k, v in states.items()} | {"polymarket_us_snapshots": pm}
        if captured == 0 and pm == 0:
            out.append(_p("market_quote_history", Readiness.NOT_YET, 0,
                          "no captured Odds API target and no Polymarket US quote stored", mcounts))
        elif captured and pm and not lost:
            out.append(_p("market_quote_history", Readiness.YES, captured,
                          f"{captured} captured Odds API targets, none missed or failed; {pm} Polymarket US "
                          "snapshots", mcounts))
        else:
            gaps = []
            if not captured:
                gaps.append("no captured Odds API target")
            if not pm:
                gaps.append("no Polymarket US quote (sportsbook offers are never executable)")
            if lost:
                gaps.append(f"{lost} targets missed or failed")
            out.append(_p("market_quote_history", Readiness.PARTIAL, captured, "; ".join(gaps), mcounts))
    if dec is None:
        why = f"shadow ledger {dec_state}"
        out += [_unknown("model_estimate", why), _unknown("decisions", why)]
    else:
        sports = [d for d in dec.rows if _is_sports(d)]
        out.append(_model_estimate(sports, "; no sports model exists (a sports model needs a preregistered "
                                           "experiment; not authorized now)"))
        out.append(_decisions(sports, "no sports decision in the shadow ledger: the sports lane makes no "
                                      "decisions"))
    if ev is None:
        out += [_unknown(k, store_why) for k in ("later_price", "consensus", "settlement_linkage")]
    else:
        by_event: dict[str, list[Mapping[str, Any]]] = {}
        for t in ev.odds_targets:
            by_event.setdefault(str(t["event_id"]), []).append(t)
        closing_targets = [max(ts, key=lambda t: str(t["target_utc"])) for ts in by_event.values()]
        final = [t for t in closing_targets if t["state"] in FINAL_ODDS_STATES]
        have = sum(1 for t in final if t["state"] == "CAPTURED")
        out.append(_fraction("later_price", have, len(final),
                             "events whose latest pre-close target (e.g. T-60m) is final were captured there",
                             ref="P2-6", counts={"events": len(by_event), "latest_target_final": len(final),
                                                 "latest_target_captured": have},
                             extra="; T-60m is the latest pre-close observation, not the closing line"))
        with_offers = [s for s in ev.odds_consensus if _has_offers(s)]
        supported = [s for s in with_offers
                     if any(p.status.value == "SUPPORTED" for e in s.events for p in e.propositions)]
        n_props = sum(1 for s in ev.odds_consensus for e in s.events for p in e.propositions
                      if p.status.value == "SUPPORTED")
        out.append(_fraction("consensus", len(supported), len(with_offers),
                             "odds snapshots with offers yield at least one SUPPORTED consensus proposition",
                             counts={"snapshots_with_offers": len(with_offers), "snapshots_with_consensus":
                                     len(supported), "supported_propositions": n_props}))
        scores = ev.snapshots.get(("the_odds_api", "scores"), 0)
        if scores:
            out.append(_p("settlement_linkage", Readiness.PARTIAL, scores,
                          f"{scores} scores snapshots stored, but no outcome linkage is implemented", {"scores": scores},
                          "P1-5"))
        else:
            out.append(_p("settlement_linkage", Readiness.NOT_YET, 0,
                          "no NFL outcome is captured or linked (final scores are P1-5: public, joined later)",
                          {"scores": 0}, "P1-5"))
    raw = out[0]
    if raw.state is Readiness.UNKNOWN:
        lifecycle, basis = "UNKNOWN", store_why
    elif raw.state is Readiness.NOT_YET:
        lifecycle, basis = "NO_EVIDENCE_YET", "derived: no stored odds snapshot holds offers"
    else:
        lifecycle, basis = "DATA_COLLECTION", "derived: prospective evidence is stored; no sports model or decisions"
    return DomainReadiness("sports", "NFL: The Odds API pilot (research only) + Polymarket US research lane",
                           lifecycle, basis, tuple(out), _ready(out))


# --------------------------------------------------------------------------- public API


def build_report(db_path: str | Path, ledger_path: str | Path | None = None, *, now: datetime,
                 experiments_root: str | Path | None = REPO_EXPERIMENTS) -> ReadinessReport:
    """The readiness report from the stores as they are now. Read-only and network-free."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    ev, ev_state = _read_evidence(Path(db_path))
    dec, dec_state = _read_ledger(Path(ledger_path) if ledger_path is not None else None)
    root = Path(experiments_root) if experiments_root is not None else None
    return ReadinessReport(now.astimezone(UTC).isoformat().replace("+00:00", "Z"), ev_state, dec_state,
                           (_weather(ev, ev_state, dec, dec_state, root), _sports(ev, ev_state, dec, dec_state)))


def render_text(report: ReadinessReport) -> str:
    lines = [f"Research readiness ({report.version}) as of {report.as_of_utc}",
             f"  evidence store: {report.evidence_store}; shadow ledger: {report.shadow_ledger}"]
    for d in report.domains:
        lines.append(f"\n{d.domain.upper()}  {d.scope}\n  lifecycle: {d.lifecycle} ({d.lifecycle_basis})")
        for p in (*d.prerequisites, d.research_ready):
            count = "" if p.evidence_count is None else f" [{p.evidence_count}]"
            ref = f" ({p.coverage_ref})" if p.coverage_ref else ""
            lines.append(f"  {p.state.value:<14} {p.title}{count}: {p.reason}{ref}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, *, clock: Callable[[], datetime] | None = None) -> int:
    """`edge-lab readiness report`: prints JSON (or --text). Exit 0 whenever a report is built."""
    parser = argparse.ArgumentParser(
        prog="edge-lab readiness report",
        description="Per-domain research-readiness / learning-history completeness (#50). Read-only, no network.")
    parser.add_argument("--db", default="data/edge_lab.sqlite3", help="evidence store (opened read-only)")
    parser.add_argument("--ledger", help="shadow ledger (opened read-only); without it, ledger items are UNKNOWN")
    parser.add_argument("--experiments", default=str(REPO_EXPERIMENTS), help="experiment registry directory")
    parser.add_argument("--text", action="store_true", help="a plain-text table instead of JSON")
    args = parser.parse_args(argv)
    now = (clock or (lambda: datetime.now(UTC)))()  # the report reads the stores as they are now
    report = build_report(args.db, args.ledger, now=now, experiments_root=args.experiments)
    sys.stdout.write(render_text(report) if args.text else json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
