"""EXP-002 A.C timing calibration: a label-free, logged, one-off development look (PROPOSED input, not a freeze).

`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §A.C (calibration procedure, steps 1-4) and
`docs/research/EXP002_FREEZE_PROPOSAL.md` §3 row 7, §4 and §5 blocker 3. Tool notes:
`docs/research/EXP002_AC_CALIBRATION_TOOL.md`.

What it reads, and only that (the T-24h and T-6h horizons; timing and feature-side fields):
- `R_o`: the odds receipt of each due T-24h / T-6h capture, and each contributing book's provider `last_update`
  age at that receipt (the canonical consensus, `odds_consensus`);
- `R_k`: the receipt of each Kalshi KXNFLGAME book of the SAME horizon, received from the horizon's window start to
  the target's own cutoff (`odds_schedule.deadline`), never later; the chosen book's spread and displayed ask depth;
- repeat books of one market and horizon within 15 minutes (short-interval drift of the YES mid).

What it never reads: any T-60m target, T-60m capture, T-60m book or its availability (#124: the existence of a
T-60m pair or book is weak label information); any book received after a target's cutoff; any settlement (the
catalog is built without the settled listing fields). Pinned by tests (a payload spy, and identical output with and
without T-60m data present).

Every run is recorded first: one FEATURE_INSPECTION event (DEVELOPMENT, viewed_features true, viewed_labels false,
viewed_results false) in EXP-002's own evidence log. If it cannot be recorded, nothing is shown.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import kalshi_quotes
from . import research_evidence as rev
from . import sports_evidence as se
from .freshness import parse_utc
from .odds_schedule import deadline, effective_due
from .provenance import canonical_json, sha256_hex

UTC = timezone.utc
TIMING_VERSION = "exp002-ac-timing-v2"
# A.C step 1: "use only the development pilot weeks (A.H)". The pilot is kickoffs 2026-09-27 -> 2026-10-19
# (RESEARCH_UNBLOCKING_DECISIONS.md A.H; EXP002_FREEZE_PROPOSAL.md section 4, "Development pilot"). Games with an ET
# kickoff date outside it are skipped before anything about them is read, whenever the tool runs, so a run after
# 2026-10-21 can never log evaluation-window games as DEVELOPMENT.
PILOT_FIRST_ET = date(2026, 9, 27)
PILOT_LAST_ET = date(2026, 10, 19)
SCHEMA = "exp002-ac-timing/1"
LABEL = "PROPOSED calibration input, not a freeze"
HORIZONS = se.GATE_HORIZONS  # ("T-24h", "T-6h"): never T-60m
RULE_HORIZON = "T-6h"
DRIFT_WINDOW = timedelta(minutes=15)
KEEP_MIN = Decimal("0.70")
DRIFT_DIVISOR = Decimal(3)  # the drift limit is delta_min / 3 (exact decimal division)


@dataclass(frozen=True, order=True)
class Window:
    """A pair window: a book up to `before` before the odds receipt, or up to `after` after it (A.C)."""

    before_min: int
    after_min: int

    @property
    def name(self) -> str:
        return f"[-{self.before_min},+{self.after_min}]"

    @property
    def width(self) -> int:
        return self.before_min + self.after_min

    @property
    def drift_gap(self) -> timedelta:
        """The largest book gap this window admits between the odds and the book."""
        return timedelta(minutes=max(self.before_min, self.after_min))


WINDOWS = (Window(5, 5), Window(5, 10), Window(10, 15))  # A.C step 2: every window tried (variant budget)
FALLBACK = Window(5, 10)  # A.C step 3: frozen if none qualifies, with its attrition recorded
EXPOSURE_CAVEAT = ("T-60m book prices possibly seen (UNKNOWN, unlogged Terminal display): the Terminal's Family A "
                   "capacity panel could show a T-60m book for pilot games from 2026-09-26 until the #124 deploy "
                   "(2026-09-29T02:09:50Z); recorded as eu-7f8e61282393c0bf2258b4bc90dd92c7 and "
                   "eu-f4954194ccbea8817aef73d4343122bb (docs/research/EXP002_FREEZE_PROPOSAL.md section 4). This "
                   "calibration reads no T-60m data itself, but it cannot certify that no label was ever in view.")
OPTION_B_NOTE = ("No window qualified. A.C step 3: freeze [-5,+10] and record its attrition, or pursue PR C option "
                 "(b), capturing the Kalshi book in the same run as the odds (a runner change that needs review).")


def in_pilot_weeks(commence_utc: datetime) -> bool:
    """True when the game's ET kickoff date is within the development pilot weeks (PILOT_FIRST_ET..PILOT_LAST_ET,
    inclusive). The one predicate the calibration filters on."""
    return PILOT_FIRST_ET <= se.et_date(commence_utc) <= PILOT_LAST_ET


class TimingRefused(RuntimeError):
    """The calibration cannot be computed without its output depending on data it must not read (a truncated
    catalog or target list: the caps count T-60m rows). Nothing is shown and nothing is logged."""


def _seconds(delta: timedelta) -> int:
    return int(delta.total_seconds())


def _dist(values: Sequence[float | int]) -> dict[str, Any]:
    """n, min, p10, median, p90, max (nearest-rank percentiles; deterministic)."""
    if not values:
        return {"n": 0, "min": None, "p10": None, "median": None, "p90": None, "max": None}
    v = sorted(values)

    def rank(q: float) -> float | int:
        return v[min(len(v) - 1, max(0, int(q * len(v) + 0.5) - 1))]
    return {"n": len(v), "min": v[0], "p10": rank(0.10), "median": statistics.median(v), "p90": rank(0.90),
            "max": v[-1]}


class _BookReader:
    """Reads a stored Kalshi book's YES quote. Every snapshot id read is kept in `read` (the spy tests use it)."""

    def __init__(self, payloads: Any) -> None:
        self.payloads = payloads
        self.read: list[int] = []

    def __call__(self, ticker: str, book: tuple[datetime, int, str, str]) -> dict[str, Any] | None:
        received, sid, _, _ = book
        self.read.append(sid)
        payload, bad = self.payloads.payload(sid)
        if bad:
            return None
        yes = kalshi_quotes.quotes_from_orderbook(ticker, payload, received_at_utc=se._iso(received),
                                                  evidence_id=f"snapshot:{sid}").get("YES")
        if yes is None or yes.anomaly:
            return None
        return {"mid": se._mid(yes.best_bid, yes.best_ask), "spread": se._spread(yes.best_bid, yes.best_ask),
                "ask_size": None if yes.displayed_size is None else float(yes.displayed_size)}


def timing_observations(store: Any, *, as_of: datetime, windows: Sequence[Window] = WINDOWS) -> dict[str, Any]:
    """The raw A.C step 2 observations from T-24h and T-6h targets only (see the module docstring)."""
    payloads = se._Payloads(store)
    consensus = se._Consensus(payloads)
    catalog = se.kalshi_catalog(store, as_of, payloads, se.SETTLED_LISTING_FIELDS)
    # `se._targets` holds every target in memory, T-60m ones included (their state transitions are replayed to
    # as_of there); this loop drops non-T-24h/T-6h rows before reading anything about them.
    all_targets, truncated = se._targets(store, as_of)
    if catalog.truncated or truncated:
        # Past the row caps the kept rows depend on how many T-60m rows exist, and a truncation drops earlier
        # (T-24h) books: the output would reveal T-60m availability. Refuse with no counts.
        raise TimingRefused("the Kalshi catalog or the target list reached its row cap; the calibration would depend "
                            "on T-60m rows, so nothing is computed or shown (run it with a narrower --as-of or raise "
                            "the caps in a reviewed change)")
    reader = _BookReader(payloads)
    cfg = se.PILOT_CONFIG
    sides: list[dict[str, Any]] = []
    odds_ages: dict[str, list[int]] = {h: [] for h in HORIZONS}
    drift: list[dict[str, Any]] = []
    counts = {h: {"targets_due": 0, "superseded": 0, "odds_not_captured": 0, "odds_capture_unusable": 0,
                  "consensus_not_supported": 0, "odds_not_fresh": 0, "not_mapped": 0, "sides": 0,
                  "sides_lost_upstream": 0} for h in HORIZONS}
    stage_key = {se.Stage.ODDS_NOT_CAPTURED: "odds_not_captured", se.Stage.ODDS_CAPTURE_UNUSABLE: "odds_capture_unusable",
                 se.Stage.CONSENSUS_NOT_SUPPORTED: "consensus_not_supported", se.Stage.ODDS_NOT_FRESH: "odds_not_fresh"}
    games: set[tuple[str, str, str]] = set()
    drift_seen: set[tuple[str, str]] = set()
    for r in all_targets:
        horizon = r.get("offset_label")
        if horizon not in HORIZONS:  # T-60m rows are skipped before anything about them is looked at
            continue
        t = se._capture_target(r)
        if not in_pilot_weeks(t.commence_utc):
            continue  # outside the development pilot weeks (A.C step 1): never read, counted or logged
        cutoff = deadline(t, cfg)
        if cutoff > as_of:
            continue  # not yet due
        c = counts[horizon]
        c["targets_due"] += 1
        if r.get("state") == "SUPERSEDED":
            c["superseded"] += 1
            continue
        games.add((se._iso(t.commence_utc), t.event_id, se.week_cluster(t.commence_utc)))
        window_start = effective_due(t, cfg) - cfg.early_tolerance
        # Per-book last_update ages for every CAPTURED target received by its cutoff, whatever its freshness: a
        # book older than 10 min is exactly what this distribution must be able to show.
        if r.get("state") == "CAPTURED" and r.get("snapshot_id") is not None:
            result = consensus.snapshot(int(r["snapshot_id"]))
            got = se.parse_utc(result.received_at_utc) if result is not None else None
            if got is not None and got <= cutoff:
                event = next((e for e in result.events if e.event_id == r["event_id"]), None)
                prop, _ = se._h2h(event, t.home_team, t.away_team) if event is not None else (None, None)
                if prop is not None:
                    odds_ages[horizon] += [b.age_at_receipt_seconds for b in prop.books
                                           if b.age_at_receipt_seconds is not None]
        odds = se.odds_side(r, consensus, cutoff)
        received = odds.get("_received")
        if received is None:
            c[stage_key.get(odds.get("stage"), "odds_capture_unusable")] += 1
            c["sides_lost_upstream"] += 2  # both team markets of the game
            continue
        mapping = se.map_event(t.home_team, t.away_team, t.commence_utc, catalog, cutoff)
        if mapping["state"] != "MAPPED":
            c["not_mapped"] += 1
            c["sides_lost_upstream"] += 2
            continue
        for team, obs in sorted(mapping["markets"].items()):
            ticker = obs.ticker
            # Only this horizon's books, received from the horizon window start (effective due - early tolerance)
            # to this target's own cutoff: no later book is ever considered, and every window's before-side is
            # capped at the window start.
            horizon_books = [b for b in catalog.books.get(ticker, []) if window_start <= b[0] <= cutoff]
            c["sides"] += 1
            side: dict[str, Any] = {"horizon": horizon, "event_id": t.event_id, "ticker": ticker,
                                    "week": se.week_cluster(t.commence_utc), "odds_received": received,
                                    "horizon_books": len(horizon_books), "kept": {}}
            nearest = min(horizon_books, key=lambda b: (abs(b[0] - received), b[0], b[1])) if horizon_books else None
            side["nearest_skew_s"] = None if nearest is None else _seconds(nearest[0] - received)
            for w in windows:
                book, _, _ = se.pick_book(horizon_books, received, window_start, cutoff,
                                          timedelta(minutes=w.before_min), timedelta(minutes=w.after_min))
                side["kept"][w.name] = book is not None
                if w == FALLBACK and book is not None:
                    decision = max(book[0], received)
                    side.update(skew_s=_seconds(book[0] - received), book_age_at_decision_s=_seconds(decision - book[0]),
                                odds_age_at_decision_s=_seconds(decision - received))
                    quote = reader(ticker, book)
                    side["spread"] = None if quote is None else quote["spread"]
                    side["ask_size"] = None if quote is None else quote["ask_size"]
            sides.append(side)
            # Short-interval drift: consecutive books of this market and horizon within 15 minutes (only markets of
            # sides that reached this point: a game whose odds or mapping failed contributes no drift pair).
            if (ticker, horizon) in drift_seen:
                continue
            drift_seen.add((ticker, horizon))
            ordered = sorted(horizon_books)
            for a, b in zip(ordered, ordered[1:]):
                gap = b[0] - a[0]
                if gap > DRIFT_WINDOW:
                    continue
                qa, qb = reader(ticker, a), reader(ticker, b)
                if qa is None or qb is None or qa["mid"] is None or qb["mid"] is None:
                    drift.append({"horizon": horizon, "ticker": ticker, "gap_s": _seconds(gap), "abs_mid_change": None})
                    continue
                drift.append({"horizon": horizon, "ticker": ticker, "gap_s": _seconds(gap),
                              "abs_mid_change": round(abs(qb["mid"] - qa["mid"]), 10)})
    return {"sides": sides, "odds_ages": odds_ages, "drift": drift, "counts": counts, "games": sorted(games),
            "books_read": list(reader.read), "targets_truncated": truncated,
            "catalog_problems": list(catalog.problems)}


def window_verdict(due: int, kept: int, median_abs_drift: float | None, delta_min: Decimal) -> list[str]:
    """Why a window fails A.C step 3 (empty: it qualifies). Inclusive at both limits: exactly 70% kept, or a
    median drift exactly delta_min / 3, qualifies. No due pair or no drift pair fails closed."""
    reasons = []
    if due <= 0:
        reasons.append("NO_DUE_T6H_PAIRS")
    elif Decimal(kept) / Decimal(due) < KEEP_MIN:
        reasons.append(f"KEEPS {kept}/{due} < 70%")
    if median_abs_drift is None:
        reasons.append("DRIFT_UNKNOWN: no repeat-book pair within the window's gap")
    elif Decimal(str(round(median_abs_drift, 10))) > delta_min / DRIFT_DIVISOR:
        reasons.append(f"MEDIAN_DRIFT {median_abs_drift} > delta_min/3 = {float(delta_min / DRIFT_DIVISOR)}")
    return reasons


def recommend(window_rows: Sequence[Mapping[str, Any]], *, delta_min: Decimal) -> dict[str, Any]:
    """A.C step 3, mechanically: the narrowest window (width, then the smaller after-side, then the smaller
    before-side) that keeps >= 70% of due T-6h pairs AND whose median absolute short-interval drift is <= delta_min
    / 3. A window without drift data or without due pairs does not qualify (fail closed). If none qualifies:
    [-5,+10] with its attrition and the option-(b) note."""
    limit = delta_min / DRIFT_DIVISOR
    qualified = [w for w in window_rows if w["qualifies"]]
    if qualified:
        best = min(qualified, key=lambda w: (w["width_min"], w["after_min"], w["before_min"]))
        return {"window": best["window"], "basis": "QUALIFIED", "keep_min": float(KEEP_MIN),
                "drift_limit": float(limit), "kept_fraction": best["t6h_kept_fraction"],
                "median_abs_drift": best["drift"]["median_abs"],
                "rule": "A.C step 3: the narrowest window keeping >= 70% of due T-6h pairs whose median absolute "
                        "short-interval drift <= delta_min / 3"}
    fb = next((w for w in window_rows if w["window"] == FALLBACK.name), None)
    return {"window": FALLBACK.name, "basis": "NO_QUALIFIER_FALLBACK", "keep_min": float(KEEP_MIN),
            "drift_limit": float(limit), "kept_fraction": None if fb is None else fb["t6h_kept_fraction"],
            "attrition": None if fb is None else {"due_pairs": fb["t6h_due_pairs"], "lost": fb["t6h_lost"]},
            "median_abs_drift": None if fb is None else fb["drift"]["median_abs"], "note": OPTION_B_NOTE,
            "rule": "A.C step 3: no window qualified"}


def calibrate(store: Any, *, as_of: datetime, delta_min: Decimal, windows: Sequence[Window] = WINDOWS
              ) -> dict[str, Any]:
    """The A.C step 2 distributions and the step 3 recommendation. Pure over the store; the caller logs before
    showing it (`record_timing_view`)."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    if not isinstance(delta_min, Decimal) or not Decimal(0) < delta_min < Decimal(1):
        raise ValueError("delta_min must be a Decimal probability in (0, 1), e.g. Decimal('0.01')")
    windows = tuple(sorted(set(windows)))
    if not windows:
        raise ValueError("at least one window")
    as_of = as_of.astimezone(UTC)
    obs = timing_observations(store, as_of=as_of, windows=windows)
    sides = obs["sides"]
    limit = delta_min / DRIFT_DIVISOR
    drift_values = [d for d in obs["drift"] if d["abs_mid_change"] is not None]
    window_rows = []
    for w in windows:
        t6 = [s for s in sides if s["horizon"] == RULE_HORIZON]
        kept6 = sum(1 for s in t6 if s["kept"][w.name])
        t24 = [s for s in sides if s["horizon"] == "T-24h"]
        kept24 = sum(1 for s in t24 if s["kept"][w.name])
        # The rule uses T-6h drift only (the decision horizon, as the keep test); T-24h drift is descriptive.
        in_gap = [d["abs_mid_change"] for d in drift_values
                  if d["horizon"] == RULE_HORIZON and d["gap_s"] <= _seconds(w.drift_gap)]
        in_gap24 = [d["abs_mid_change"] for d in drift_values
                    if d["horizon"] == "T-24h" and d["gap_s"] <= _seconds(w.drift_gap)]
        med = statistics.median(in_gap) if in_gap else None
        lost_upstream = obs["counts"][RULE_HORIZON]["sides_lost_upstream"]
        all_due = len(t6) + lost_upstream
        frac = None if not t6 else kept6 / len(t6)
        reasons = window_verdict(len(t6), kept6, med, delta_min)
        window_rows.append({
            "window": w.name, "before_min": w.before_min, "after_min": w.after_min, "width_min": w.width,
            "t6h_due_pairs": len(t6), "t6h_kept": kept6, "t6h_lost": len(t6) - kept6, "t6h_kept_fraction": frac,
            "t6h_all_due_sides": all_due, "t6h_sides_lost_upstream": lost_upstream,
            "t6h_kept_over_all_due_sides": None if not all_due else kept6 / all_due,
            "t24h_due_pairs": len(t24), "t24h_kept": kept24, "t24h_kept_fraction": None if not t24 else kept24 / len(t24),
            "drift": {"horizon": RULE_HORIZON, "max_gap_minutes": int(w.drift_gap.total_seconds() // 60),
                      "pairs": len(in_gap), "median_abs": med,
                      "t24h_descriptive": {"pairs": len(in_gap24),
                                           "median_abs": statistics.median(in_gap24) if in_gap24 else None}},
            "qualifies": not reasons, "reasons": reasons})
    by_h = {h: [s for s in sides if s["horizon"] == h] for h in HORIZONS}

    def field_dist(h: str, key: str) -> dict[str, Any]:
        return _dist([s[key] for s in by_h[h] if s.get(key) is not None])
    first, last = (obs["games"][0][0], obs["games"][-1][0]) if obs["games"] else (None, None)
    body = {
        "schema": SCHEMA, "version": TIMING_VERSION, "label": LABEL, "as_of_utc": se._iso(as_of),
        "exposure_caveat": EXPOSURE_CAVEAT,
        "reads": "T-24h and T-6h only: odds receipts and per-book last_update ages, Kalshi books of the same horizon "
                 "received by the target's cutoff (receipt, spread, displayed ask depth, repeat-book mids). No T-60m "
                 "target, book or availability; no settlement.",
        "inputs": {"delta_min": str(delta_min),
                   "delta_min_note": "an explicit caller input; freeze proposal row 11 PROPOSES delta_min(E1) = 1 cent "
                                     "gross (0.01)",
                   "keep_min": float(KEEP_MIN), "drift_fraction": "1/3", "drift_limit": float(limit),
                   "windows": [w.name for w in windows], "fallback_window": FALLBACK.name,
                   "drift_window_minutes": int(DRIFT_WINDOW.total_seconds() // 60), "horizons": list(HORIZONS),
                   "pilot_kickoffs_et": {"first": PILOT_FIRST_ET.isoformat(), "last": PILOT_LAST_ET.isoformat(),
                                         "source": "A.H development pilot (RESEARCH_UNBLOCKING_DECISIONS.md); "
                                                   "EXP002_FREEZE_PROPOSAL.md section 4",
                                         "outside": "skipped before anything is read; never counted or logged"},
                   "window_start_cap": "every window's before-side is capped at the horizon window start (effective "
                                       "due - 7 min early tolerance): no book of an earlier horizon is ever used",
                   "join_version": se.JOIN_VERSION, "book_choice": se.BOOK_CHOICE,
                   "due_pair_definition": "a due T-6h target side whose odds capture is usable (a receipt R_o) and "
                                         "whose market is mapped by the cutoff: only the window decides it. Sides lost "
                                         "upstream (odds not captured or unusable, not mapped) are counted in "
                                         "`coverage` and are the same for every window.",
                   "drift_definition": "consecutive books of one market and horizon at most 15 min apart. The rule "
                                       "uses T-6h pairs only (the decision horizon); T-24h drift is descriptive. "
                                       "INTERPRETATION for the freeze review: A.C step 2 names one 15-min measure; "
                                       "here each window uses the pairs whose gap is within its larger side (5, 10 "
                                       "or 15 min). Games whose odds or mapping failed contribute no drift pair.",
                   "all_due_sides_definition": "kept / all due T-6h sides also counts the two sides of every due game "
                                               "lost upstream (odds not captured, unusable, not supported or not "
                                               "fresh; market not mapped)"},
        "coverage": {"games": len(obs["games"]), "first_kickoff_utc": first, "last_kickoff_utc": last,
                     "weeks": sorted({g[2] for g in obs["games"]}), "by_horizon": obs["counts"],
                     "targets_truncated": obs["targets_truncated"], "catalog_problems": obs["catalog_problems"]},
        "distributions": {h: {
            "skew_seconds_chosen_book_at_fallback_window": field_dist(h, "skew_s"),
            "nearest_book_skew_seconds": field_dist(h, "nearest_skew_s"),
            "book_age_at_decision_seconds": field_dist(h, "book_age_at_decision_s"),
            "odds_age_at_decision_seconds": field_dist(h, "odds_age_at_decision_s"),
            "odds_book_last_update_age_seconds": _dist(obs["odds_ages"][h]),
            "spread": field_dist(h, "spread"), "displayed_ask_depth": field_dist(h, "ask_size"),
            "sides_without_horizon_book": sum(1 for s in by_h[h] if s["horizon_books"] == 0)} for h in HORIZONS},
        "short_interval_drift": {h: {"abs_mid_change": _dist([d["abs_mid_change"] for d in drift_values
                                                              if d["horizon"] == h]),
                                     "gap_seconds": _dist([d["gap_s"] for d in obs["drift"] if d["horizon"] == h]),
                                     "pairs_without_mid": sum(1 for d in obs["drift"]
                                                              if d["horizon"] == h and d["abs_mid_change"] is None)}
                                 for h in HORIZONS},
        "windows_tried": window_rows,
        "recommendation": recommend(window_rows, delta_min=delta_min),
        "variant_budget": f"all {len(windows)} windows tried count against EXP-002's variant budget (A.C step 4); "
                          "pairs lost to skew stay in the denominators",
        "books_read": len(obs["books_read"]),
    }
    plain = se._plain(body)
    plain["output_sha256"] = sha256_hex(canonical_json(plain))
    return plain


def record_timing_view(result: Mapping[str, Any], *, log: Path, actor: str, code_version: str,
                       experiments_root: Path | None = None, now: datetime | None = None) -> str:
    """Record the calibration look before anything is shown: FEATURE_INSPECTION, DEVELOPMENT, viewed_features
    true, viewed_labels false, viewed_results false, influenced_tuning true (it informs a PROPOSED join limit), in
    EXP-002's own log, over the games covered. Raises
    `research_evidence.EvidenceError` when it cannot be recorded (the caller then shows nothing)."""
    cov = result["coverage"]
    shown = [x for x in (cov.get("first_kickoff_utc"), cov.get("last_kickoff_utc")) if x]
    rec = result["recommendation"]
    return se._record_label_view(
        se.protocol_status(experiments_root), shown, as_of_utc=result["as_of_utc"], sha=result["output_sha256"],
        log=log, actor=actor, code_version=code_version, experiments_root=experiments_root, now=now,
        dataset_id="sports_evidence:exp002_ac_timing", dataset_version=f"{TIMING_VERSION}/{se.JOIN_VERSION}",
        tool="python -m edge_lab.sports_evidence exp002-timing",
        note=f"A.C timing calibration ({TIMING_VERSION}) as of {result['as_of_utc']}: T-24h / T-6h odds receipts, "
             "per-book last_update ages, same-horizon Kalshi book receipts, spreads, ask depth and repeat-book mids "
             "only; no T-60m target, book or availability and no settlement read. Windows tried: "
             f"{', '.join(result['inputs']['windows'])}; delta_min {result['inputs']['delta_min']} (caller input); "
             f"recommendation {rec['window']} ({rec['basis']}), a PROPOSED calibration input, not a freeze. "
             f"{EXPOSURE_CAVEAT}",
        role=rev.DatasetRole.DEVELOPMENT, action=rev.Action.FEATURE_INSPECTION, viewed_features=True,
        viewed_labels=False, viewed_results=False,
        influenced_tuning=True)  # the look exists to choose a (PROPOSED) join limit: honest, conservative


def main_timing(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """`python -m edge_lab.sports_evidence exp002-timing`: refuses without --evidence-log, --actor and a code
    version; computes, records the look, and only then prints."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    name = "sports_evidence exp002-timing"
    if not (args.evidence_log and args.actor and args.code_version):
        print(json.dumps({"command": name, "state": "REFUSED",
                          "detail": "every calibration look is logged first: give --evidence-log (EXP-002's "
                                    "evidence_use.jsonl), --actor and --code-version (or $EDGE_LAB_CODE_VERSION)"}))
        return 2
    try:
        delta_min = Decimal(args.delta_min)
    except Exception:  # noqa: BLE001 - reported as a usage error
        parser.error("--delta-min must be a decimal probability, e.g. 0.01")
    if not Decimal(0) < delta_min < Decimal(1):
        parser.error("--delta-min must be in (0, 1), e.g. 0.01 (1 cent)")
    now = se._clock()
    as_of = now
    if args.as_of:
        as_of = parse_utc(args.as_of)  # type: ignore[assignment]
        if as_of is None:
            parser.error("--as-of must be an ISO-8601 time with a zone")
        if as_of > now:
            print(f"--as-of {args.as_of} is in the future; clamped to now ({se._iso(now)})", file=sys.stderr)
            as_of = now
    try:
        store = SnapshotStore.open_readonly(args.db)
    except ReadOnlyStoreError as exc:
        print(json.dumps({"command": name, "state": "NO_STORE", "detail": str(exc)}))
        return 1
    root = Path(args.experiments) if args.experiments else None
    try:
        result = calibrate(store, as_of=as_of, delta_min=delta_min)
    except TimingRefused as exc:
        print(json.dumps({"command": name, "state": "REFUSED", "detail": str(exc)}))
        return 2
    try:
        logged = record_timing_view(result, log=Path(args.evidence_log), actor=args.actor,
                                    code_version=args.code_version, experiments_root=root)
    except (rev.EvidenceError, OSError) as exc:
        print(json.dumps({"command": name, "state": "REFUSED",
                          "detail": f"the calibration look could not be recorded, so nothing is shown: {exc}"}))
        return 2
    out = {**result, "evidence_use": logged}
    text = json.dumps(out, sort_keys=True, indent=2, ensure_ascii=False)
    if args.out:
        se._write_atomic(Path(args.out), text + "\n")
        print(json.dumps({"command": name, "state": "WRITTEN", "out": args.out, "output_sha256": out["output_sha256"],
                          "recommendation": out["recommendation"]["window"], "label": LABEL}))
    else:
        sys.stdout.write(text + "\n")
    return 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("exp002-timing", help="EXP-002 A.C timing calibration (label-free, T-24h / T-6h only; every "
                                             "run is logged as FEATURE_INSPECTION first). PROPOSED input, not a freeze")
    p.add_argument("--db", default="data/edge_lab.sqlite3")
    p.add_argument("--as-of", help="point in time (ISO-8601 with zone); default and maximum: now")
    p.add_argument("--delta-min", required=True,
                   help="the minimum useful effect in probability units, reported with the output (freeze proposal "
                        "row 11 PROPOSES 0.01, 1 cent gross, for E1); the drift limit is delta_min / 3")
    p.add_argument("--evidence-log", help="EXP-002's evidence_use.jsonl (required; the look is recorded first)")
    p.add_argument("--actor", help="who runs the calibration (required; recorded in the evidence-use event)")
    p.add_argument("--code-version", default=os.getenv("EDGE_LAB_CODE_VERSION"),
                   help="git commit of the code that runs (default: $EDGE_LAB_CODE_VERSION)")
    p.add_argument("--experiments", help="experiment registry root (default: the repository's experiments/)")
    p.add_argument("--out", help="write the JSON artifact here (atomically) instead of stdout")
