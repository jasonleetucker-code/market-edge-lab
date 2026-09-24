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
- zero evidence is NOT_YET; some-but-not-all is PARTIAL; YES needs every counted item present
  (each YES rule is stated in ADR 0033; mere existence is never YES);
- weather ledger items describe the operational shadow account; the research account is reported
  beside it (`research_*`), never pooled; fills and settlements match within one account;
- cost is bounded: SQL counts plus at most CONSENSUS_SAMPLE parsed odds reads;
- research_ready is YES only when every applicable prerequisite is YES.

Vocabulary follows docs/research/LEARNING_HISTORY_COVERAGE.md (RAW, MARKET, MODEL, DECISION,
LATER MARKET, OUTCOME; gap ids such as P0-1, P1-1, P1-5). Network-free and read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .freshness import parse_utc

READINESS_VERSION = "research-readiness-v1"
SCHEMA = "research-readiness/1"
UTC = timezone.utc
REPO_EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
WEATHER_EXPERIMENT = "EXP-001"
FORWARD_PHASES = ("pfm", "decision", "recheck")
LATER_PHASES = ("post_decision_1h", "post_decision_6h", "pre_close", "close", "settlement_preceding")
SPORTS_PREFIXES = ("the_odds_api:", "polymarket_us:", "sports:")
FINAL_ODDS_STATES = ("CAPTURED", "MISSED", "FAILED", "SUPERSEDED")
# The consensus prerequisite parses at most this many of the newest odds reads with offers
# (one payload in memory at a time), so the report's cost is bounded as snapshots accumulate.
CONSENSUS_SAMPLE = 8


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


_OFFERS_MARK = '"bookmakers":[{'  # a non-empty bookmakers list in the store's canonical JSON


@dataclass
class _Evidence:
    snapshots: dict[tuple[str, str], int]
    attempted_days: set[str]  # target dates with any live EXP-001 capture attempt (any phase, any status)
    complete_days: dict[str, set[str]]  # phase -> target dates with a complete live capture
    not_complete: dict[str, int]  # phase -> live attempts that were not complete
    later: dict[str, set[str]]  # kalshi market_id -> later phases CAPTURED
    later_missed: int
    odds_targets: list[Mapping[str, Any]]
    odds_total: int
    odds_with_offers: int  # by the canonical-JSON mark; confirmed by parsing in the sample
    odds_sample: list[Any]  # SnapshotConsensus of the newest CONSENSUS_SAMPLE reads with offers


def _read_evidence(db: Path) -> tuple[_Evidence | None, str]:
    """Aggregate counts through SQL and a bounded parse sample: cost does not grow with the
    size of stored payloads (only one sampled payload is in memory at a time)."""
    from . import odds_consensus
    from .storage import SnapshotStore

    if not db.is_file():
        return None, "MISSING"
    try:
        store = SnapshotStore.open_readonly(db)
        # No public aggregate read exists and storage.py is outside this lane: the read-only
        # store's own connection (mode=ro, query_only) is used for COUNT queries only.
        with closing(store._connect()) as conn:
            snaps = {(r[0], r[1]): int(r[2]) for r in conn.execute(
                "SELECT source, kind, COUNT(*) FROM snapshots GROUP BY source, kind")}
            attempted: set[str] = set()
            complete: dict[str, set[str]] = {ph: set() for ph in FORWARD_PHASES}
            not_complete: dict[str, int] = {ph: 0 for ph in FORWARD_PHASES}
            for phase, status, day in conn.execute(
                    "SELECT phase, status, target_date FROM forward_captures WHERE experiment = ? AND mode = 'live'",
                    (WEATHER_EXPERIMENT,)):
                attempted.add(str(day))
                if status == "complete":
                    complete.setdefault(phase, set()).add(str(day))
                else:
                    not_complete[phase] = not_complete.get(phase, 0) + 1
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
            odds_where = "FROM snapshots WHERE source = ? AND kind = 'odds'"
            with_offers = int(conn.execute(f"SELECT COUNT(*) {odds_where} AND instr(payload_json, ?) > 0",
                                           (odds_consensus.SOURCE, _OFFERS_MARK)).fetchone()[0])
            sample_ids = [int(r[0]) for r in conn.execute(
                f"SELECT id {odds_where} AND instr(payload_json, ?) > 0 ORDER BY id DESC LIMIT ?",
                (odds_consensus.SOURCE, _OFFERS_MARK, CONSENSUS_SAMPLE))]
        targets = [dict(r) for r in store.odds_targets()]
        sample = [odds_consensus.consensus_for_snapshot(store, sid) for sid in sample_ids]
    except Exception as exc:  # noqa: BLE001 - reported (missing tables, corrupt rows), never guessed around
        return None, f"UNREADABLE: {type(exc).__name__}: {exc}"
    return _Evidence(snaps, attempted, complete, not_complete, later, missed, targets,
                     snaps.get((odds_consensus.SOURCE, "odds"), 0), with_offers,
                     [s for s in sample if s is not None]), "OK"


@dataclass
class _Account:
    rows: list[dict[str, Any]]  # decision payloads
    filled: dict[str, str]  # market_id -> event_id of this account's FILLED positions
    settled_markets: set[str]  # markets this account settled


def _read_ledger(path: Path | None) -> tuple[dict[str, _Account] | None, str]:
    """Decisions, fills and settlements per account; nothing is pooled across accounts."""
    from .shadow_ledger import ShadowLedger

    if path is None:
        return None, "NOT_GIVEN"
    if not path.is_file():
        return None, "MISSING"
    try:
        ledger = ShadowLedger.open_readonly(path)
        accounts: dict[str, _Account] = {}
        for account in ledger.accounts():
            acct = accounts.setdefault(account, _Account([], {}, set()))
            for entry in ledger.entries(account):
                payload = json.loads(entry["payload_json"])
                if entry["kind"] == "decision":
                    acct.rows.append(payload)
                elif entry["kind"] == "fill" and payload.get("status") == "FILLED":
                    acct.filled[str(payload.get("market_id"))] = str(payload.get("event_id"))
                elif entry["kind"] == "settlement":
                    acct.settled_markets.add(str(payload.get("market_id")))
    except Exception as exc:  # noqa: BLE001
        return None, f"UNREADABLE: {type(exc).__name__}: {exc}"
    return accounts, "OK"


def _weather_accounts() -> tuple[str, str]:
    from .exp001_shadow import ACCOUNT_ID, RESEARCH_ACCOUNT_ID  # the one owner of the account ids

    return ACCOUNT_ID, RESEARCH_ACCOUNT_ID


def _decision_counts(rows: Sequence[Mapping[str, Any]], prefix: str = "") -> dict[str, int]:
    return {f"{prefix}decisions": len(rows),
            f"{prefix}qualified": sum(1 for d in rows if d.get("qualification") == "QUALIFY"),
            f"{prefix}rejected": sum(1 for d in rows if d.get("qualification") == "REJECT")}


def _decisions(rows: Sequence[Mapping[str, Any]], none_reason: str, *, required_days: set[str] | None,
               extra_counts: Mapping[str, int] | None = None, scope: str = "") -> Prerequisite:
    """YES rule: at least one decision, at least one of them rejected (proof rejects are kept),
    and, where the capture days are known, every day with a complete decision capture has a
    recorded decision. Unknown capture coverage caps the state at PARTIAL."""
    counts = _decision_counts(rows) | dict(extra_counts or {})
    if not rows:
        return _p("decisions", Readiness.NOT_YET, 0, none_reason, counts)
    rejected = counts["rejected"]
    gaps = []
    if rejected == 0:
        gaps.append("none rejected: cannot show rejected decisions are kept")
    if required_days is None:
        gaps.append("capture days unknown: decision coverage cannot be checked")
    else:
        decided = {str(d.get("slot") or "").split("|", 1)[0] for d in rows}
        missing = sorted(required_days - decided)
        counts |= {"decision_capture_days": len(required_days), "days_without_decision": len(missing)}
        if missing:
            gaps.append(f"{len(missing)} of {len(required_days)} complete decision-capture days have no recorded "
                        f"decision (first {missing[0]})")
    head = f"{len(rows)} decisions{scope} ({counts['qualified']} qualified, {rejected} rejected)"
    if gaps:
        return _p("decisions", Readiness.PARTIAL, len(rows), f"{head}; " + "; ".join(gaps), counts)
    return _p("decisions", Readiness.YES, len(rows), head, counts)


def _model_estimate(rows: Sequence[Mapping[str, Any]], note: str) -> Prerequisite:
    """YES rule: every decision carries the model's decision-time probability or records that
    the model was unavailable (MODEL_UNAVAILABLE is itself evidence). A silent gap never counts."""
    with_p = sum(1 for d in rows if (d.get("opportunity") or {}).get("model_probability") is not None)
    unavailable = sum(1 for d in rows if (d.get("opportunity") or {}).get("model_probability") is None
                      and "MODEL_UNAVAILABLE" in (d.get("reasons") or []))
    return _fraction("model_estimate", with_p + unavailable, len(rows),
                     "decisions carry the decision-time model probability (or a recorded MODEL_UNAVAILABLE)",
                     counts={"decisions": len(rows), "with_model": with_p, "model_unavailable_recorded": unavailable},
                     extra=note)


def _is_sports(decision: Mapping[str, Any]) -> bool:
    ids = (str(decision.get("event_id") or ""), str(decision.get("market_id") or ""))
    return any(i.startswith(SPORTS_PREFIXES) for i in ids)


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


def _weather(ev: _Evidence | None, ev_state: str, accounts: dict[str, _Account] | None, dec_state: str,
             experiments_root: Path | None) -> DomainReadiness:
    """Ledger items describe the OPERATIONAL shadow account (exp001_shadow.ACCOUNT_ID); the
    research account's decision counts are reported beside them (`research_*`), never pooled."""
    store_why = f"evidence store {ev_state}"
    operational, research = _weather_accounts()
    out: list[Prerequisite] = []
    days = ev.attempted_days if ev is not None else set()
    if ev is None:
        out += [_unknown("raw_evidence", store_why), _unknown("market_quote_history", store_why)]
    else:
        have = sum(len(ev.complete_days.get(ph, set()) & days) for ph in FORWARD_PHASES)
        counts = {"capture_days": len(days)}
        counts |= {f"complete_days_{ph}": len(ev.complete_days.get(ph, set()) & days) for ph in FORWARD_PHASES}
        counts |= {f"not_complete_{ph}": ev.not_complete.get(ph, 0) for ph in FORWARD_PHASES}
        out.append(_fraction("raw_evidence", have, len(days) * len(FORWARD_PHASES),
                             "(capture day, phase) pairs have a complete live capture (pfm, decision, recheck; "
                             "every day with any live capture attempt counts)", counts=counts))
        books = ev.snapshots.get(("kalshi", "orderbook"), 0)
        both = ev.complete_days.get("decision", set()) & ev.complete_days.get("recheck", set()) & days
        mq_counts = {"kalshi_orderbook_snapshots": books, "capture_days": len(days),
                     "days_with_decision_and_recheck": len(both)}
        if books == 0:
            out.append(_p("market_quote_history", Readiness.NOT_YET, 0, "no Kalshi order-book snapshot stored",
                          mq_counts))
        else:
            out.append(_fraction("market_quote_history", len(both), len(days),
                                 "capture days have both a complete decision and a complete re-check book "
                                 f"({books} order-book snapshots stored)", counts=mq_counts))
    acct = accounts.get(operational) if accounts is not None else None
    rows = acct.rows if acct is not None else []
    rows = [d for d in rows if not _is_sports(d)]
    if accounts is None:
        why = f"shadow ledger {dec_state}"
        out += [_unknown("model_estimate", why), _unknown("decisions", why)]
    else:
        research_rows = [d for d in (accounts.get(research).rows if research in accounts else [])
                         if not _is_sports(d)]
        out.append(_model_estimate(rows, f" (account {operational})"))
        required = (ev.complete_days.get("decision", set()) & days) if ev is not None else None
        out.append(_decisions(rows, f"no decision in the operational account {operational}",
                              required_days=required, extra_counts=_decision_counts(research_rows, "research_"),
                              scope=f" in {operational}"))
    if ev is None or accounts is None:
        out.append(_unknown("later_price", store_why if ev is None else f"shadow ledger {dec_state}"))
    else:
        markets = sorted({str(d.get("market_id")) for d in rows if str(d.get("market_id", "")).startswith("kalshi:")})
        have = sum(1 for m in markets if ev.later.get(m))
        out.append(_fraction("later_price", have, len(markets),
                             "decided Kalshi markets (operational account) have a captured later observation "
                             f"({'/'.join(LATER_PHASES)})", ref="P0-1",
                             counts={"decided_markets": len(markets), "with_later_capture": have,
                                     "later_missed_or_failed": ev.later_missed},
                             extra="; markets decided recently may not be due yet"))
    out.append(_p("consensus", Readiness.NOT_APPLICABLE, None,
                  "no multi-book consensus source exists for KXHIGHNY; the consensus benchmark is a sports "
                  "research layer (ADR 0033)"))
    if accounts is None:
        out.append(_unknown("settlement_linkage", f"shadow ledger {dec_state}"))
    else:
        events = {str(d.get("event_id")) for d in rows}
        filled = acct.filled if acct is not None else {}
        settled = acct.settled_markets if acct is not None else set()
        held = {e for m, e in filled.items() if e in events}
        linked = {e for m, e in filled.items() if e in events and m in settled}  # same account only
        out.append(_fraction("settlement_linkage", len(linked), len(events),
                             "decided events (operational account) have an outcome linked in that account",
                             ref="P1-1",
                             counts={"decided_events": len(events), "events_with_filled_position": len(held),
                                     "events_settled": len(linked), "events_without_position": len(events) - len(held)},
                             extra="; events with no held position get no venue settlement (P1-1) and "
                                   "unsettled events may not be due yet"))
    lifecycle, basis = _experiment_status(experiments_root, WEATHER_EXPERIMENT)
    return DomainReadiness("weather", "EXP-001 KXHIGHNY (Kalshi NYC daily high; NWS PFM model)", lifecycle, basis,
                           tuple(out), _ready(out))


# --------------------------------------------------------------------------- sports (NFL)


def _supported(result: Any) -> bool:
    return any(p.status.value == "SUPPORTED" for e in result.events for p in e.propositions)


def _sports(ev: _Evidence | None, ev_state: str, accounts: dict[str, _Account] | None,
            dec_state: str) -> DomainReadiness:
    store_why = f"evidence store {ev_state}"
    out: list[Prerequisite] = []
    if ev is None:
        out += [_unknown(k, store_why) for k in ("raw_evidence", "market_quote_history")]
    else:
        pm = sum(n for (src, _), n in ev.snapshots.items() if src == "polymarket_us")
        failed = sum(1 for s in ev.odds_sample if s.failed_closed)
        rcounts = {"odds_snapshots": ev.odds_total, "odds_snapshots_with_offers": ev.odds_with_offers,
                   "odds_discovery_snapshots": ev.snapshots.get(("the_odds_api", "events"), 0),
                   "sampled": len(ev.odds_sample), "sampled_failed_closed": failed, "polymarket_us_snapshots": pm}
        raw = _fraction("raw_evidence", ev.odds_with_offers, ev.odds_total,
                        "stored odds reads hold offers", counts=rcounts,
                        extra=f"; {pm} Polymarket US snapshots")
        if raw.state is Readiness.YES and failed:
            raw = replace(raw, state=Readiness.PARTIAL,
                          reason=raw.reason + f"; {failed} of the newest {len(ev.odds_sample)} failed closed")
        out.append(raw)
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
    if accounts is None:
        why = f"shadow ledger {dec_state}"
        out += [_unknown("model_estimate", why), _unknown("decisions", why)]
    else:
        sports = [d for a in sorted(accounts) for d in accounts[a].rows if _is_sports(d)]
        out.append(_model_estimate(sports, "; no sports model exists (a sports model needs a preregistered "
                                           "experiment; not authorized now)"))
        out.append(_decisions(sports, "no sports decision in the shadow ledger: the sports lane makes no "
                                      "decisions", required_days=set()))
    if ev is None:
        out += [_unknown(k, store_why) for k in ("later_price", "consensus", "settlement_linkage")]
    else:
        by_event: dict[str, list[Mapping[str, Any]]] = {}
        for t in ev.odds_targets:
            by_event.setdefault(str(t["event_id"]), []).append(t)
        floor = datetime.min.replace(tzinfo=UTC)
        closing_targets = [max(ts, key=lambda t: parse_utc(t["target_utc"]) or floor) for ts in by_event.values()]
        final = [t for t in closing_targets if t["state"] in FINAL_ODDS_STATES]
        have = sum(1 for t in final if t["state"] == "CAPTURED")
        out.append(_fraction("later_price", have, len(final),
                             "events whose latest pre-close target (e.g. T-60m) is final were captured there",
                             ref="P2-6", counts={"events": len(by_event), "latest_target_final": len(final),
                                                 "latest_target_captured": have},
                             extra="; T-60m is the latest pre-close observation, not the closing line"))
        usable = [s for s in ev.odds_sample if any(e.bookmaker_count for e in s.events)]
        supported = [s for s in usable if _supported(s)]
        n_props = sum(1 for s in usable for e in s.events for p in e.propositions if p.status.value == "SUPPORTED")
        out.append(_fraction("consensus", len(supported), len(usable),
                             "sampled odds reads with offers yield at least one SUPPORTED consensus proposition",
                             counts={"snapshots_with_offers": ev.odds_with_offers, "sampled": len(usable),
                                     "sampled_with_consensus": len(supported), "supported_propositions": n_props},
                             extra=f" (the newest {len(usable)} of {ev.odds_with_offers} reads with offers; "
                                   f"sample cap {CONSENSUS_SAMPLE})"))
        scores = ev.snapshots.get(("the_odds_api", "scores"), 0)
        if scores:
            out.append(_p("settlement_linkage", Readiness.PARTIAL, scores,
                          f"{scores} scores snapshots stored, but no outcome linkage is implemented", {"scores": scores},
                          "P1-5"))
        else:
            out.append(_p("settlement_linkage", Readiness.NOT_YET, 0,
                          "no NFL outcome is captured or linked (final scores are P1-5: public, joined later)",
                          {"scores": 0}, "P1-5"))
    raw_state = out[0].state
    if raw_state is Readiness.UNKNOWN:
        lifecycle, basis = "UNKNOWN", store_why
    elif raw_state is Readiness.NOT_YET:
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
    accounts, dec_state = _read_ledger(Path(ledger_path) if ledger_path is not None else None)
    root = Path(experiments_root) if experiments_root is not None else None
    return ReadinessReport(now.astimezone(UTC).isoformat().replace("+00:00", "Z"), ev_state, dec_state,
                           (_weather(ev, ev_state, accounts, dec_state, root), _sports(ev, ev_state, accounts, dec_state)))


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
