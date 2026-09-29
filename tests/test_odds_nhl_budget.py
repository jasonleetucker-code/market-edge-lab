"""The NHL Odds budget numbers of docs/research/NHL_ODDS_BUDGET_2026-10.md, recomputed by the real planner.

A deterministic replay of the shared-ledger runner (NFL tick, then NHL tick, every 15 minutes, at most one
paid call per sport per tick, the quiet window, the monthly proofs) over the published 2026-27 NHL schedule
and a modelled NFL October. Every assumption is explicit here and in the research doc:

- measured 2026-09-29 ~17:20Z: September spent 45 credits, provider remaining 455; NFL costs 3 a call;
- the provider resets on the 1st (October starts at 0 used, 500 remaining; the ceiling 450 binds);
- NFL weeks in October have the six kickoff groups of the week of 2026-10-01 (TNF 20:15, Sun 09:30, 13:00,
  16:05/16:25, SNF 20:20, MNF 20:15 ET), which reproduces the measured October projection (worst 450,
  expected 270);
- the provider lists NFL games about `lookahead` days ahead (7 matches the measured horizon 2026-10-06 on
  2026-09-29); NHL discovery covers the policy's 35 days;
- every paid call is charged its estimate (NFL 3, NHL 1) and every capture succeeds.

No network, no credits. Run `python tests/test_odds_nhl_budget.py` to print the tables."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from edge_lab import odds_schedule as sch
from edge_lab.forward import eastern_date
from edge_lab.odds_schedule import QuotaReading, ScheduledEvent, SportDemand

UTC = timezone.utc
NFL, NHL = sch.NFL, sch.NHL
FIXTURE = Path(__file__).parent / "fixtures" / "odds_api" / "nhl_schedule_2026_27_nhle.json"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def nhl_games() -> list[ScheduledEvent]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [ScheduledEvent(gid, NHL, datetime.fromisoformat(t.replace("Z", "+00:00")), home, away)
            for t, gid, away, home in doc["games"]]


def nfl_october() -> list[ScheduledEvent]:
    """Six kickoff groups a week (EDT, UTC-4) for the weeks of Oct 1, 8, 15, 22 and 29."""
    out = []
    for thu in (1, 8, 15, 22, 29):
        t = datetime(2026, 10, thu)
        sun, mon = t + timedelta(days=3), t + timedelta(days=4)
        kicks = [t.replace(hour=20, minute=15), sun.replace(hour=9, minute=30)] + [sun.replace(hour=13)] * 8
        kicks += [sun.replace(hour=16, minute=5), sun.replace(hour=16, minute=25), sun.replace(hour=20, minute=20),
                  mon.replace(hour=20, minute=15)]
        out += [ScheduledEvent(f"nfl{t:%m%d}{i:02d}", NFL, (k + timedelta(hours=4)).replace(tzinfo=UTC))
                for i, k in enumerate(kicks)]
    return out


@dataclass
class Day:
    et_date: date
    nhl_slots_due: int  # NHL slots whose (effective) due time falls on this ET date, per class label
    nhl_captured: int
    nhl_skipped: int
    nhl_available_at_start: int  # NHL's share of the joint proof at the day's first tick
    nfl_captured: int
    spent_end: int


def replay(*, start: datetime, end: datetime, spent: int, remaining: int, nhl_offsets: str = "60m",
           lookahead: timedelta = timedelta(days=7), nfl: list[ScheduledEvent] | None = None,
           nfl_assumption: sch.WorstCaseAssumption | None = None) -> tuple[list[Day], dict]:
    nfl_events = nfl_october() if nfl is None else nfl
    games = nhl_games()
    nfl_pol, nhl_pol = sch.SPORT_POLICIES[NFL], sch.SPORT_POLICIES[NHL]
    nfl_cfg = nfl_pol.config() if nfl_assumption is None else sch.PilotConfig(assumption=nfl_assumption)
    nhl_cfg = nhl_pol.config(sch.parse_offsets(nhl_offsets))
    done: dict[str, set[str]] = {NFL: set(), NHL: set()}  # captured target ids
    all_targets = {NFL: [(t, sch.effective_due(t, nfl_cfg), sch.deadline(t, nfl_cfg))
                         for t in sch.plan_targets(nfl_events, nfl_cfg.offsets)],
                   NHL: [(t, sch.effective_due(t, nhl_cfg), sch.deadline(t, nhl_cfg))
                         for t in sch.plan_targets([g for g in games if start - timedelta(days=2) <= g.commence_utc
                                                    <= end + timedelta(days=40)], nhl_cfg.offsets)]}
    early = nfl_cfg.early_tolerance
    used, rem = spent, remaining
    days: dict[date, Day] = {}
    first_proof = None
    by_label: dict[str, int] = {}
    at = start

    def open_slots(sport, listed_ids, cfg):
        return sch.coalesce([t for t, _, dl in all_targets[sport]
                             if t.event_id in listed_ids and t.target_id not in done[sport] and at <= dl], cfg)

    def something_fireable(sport):
        return any(due - early <= at <= dl and t.target_id not in done[sport] for t, due, dl in all_targets[sport])

    while at < end:
        d = eastern_date(at)
        new_day = d not in days
        day = days.setdefault(d, Day(d, 0, 0, 0, -1, 0, used))
        if not sch.in_quiet_window(at, nfl_cfg):
            listed_nfl = [e for e in nfl_events if e.commence_utc <= at + lookahead]
            nfl_ids = {e.event_id for e in listed_nfl}
            nfl_h = max((e.commence_utc for e in listed_nfl), default=None)
            if something_fireable(NFL):
                quota = QuotaReading("READY", local_used=used, provider_used=used, provider_remaining=rem)
                nfl_slots = open_slots(NFL, nfl_ids, nfl_cfg)
                proof = sch.budget(nfl_slots, now=at, quota=quota, cost_per_call=3, known_horizon=nfl_h, config=nfl_cfg)
                fire = [s for s in nfl_slots if s.slot_id in proof.admitted_slot_ids and s.fireable(at, nfl_cfg)]
                if fire:
                    slot = min(fire, key=lambda s: (s.priority, s.due_utc))
                    used, rem = used + 3, rem - 3
                    done[NFL].update(m.target_id for m in slot.members)
                    day.nfl_captured += 1
            nhl_fire = something_fireable(NHL)
            if nhl_fire or new_day or day.nhl_available_at_start < 0:
                listed_nhl = [g for g in games if at <= g.commence_utc <= at + nhl_pol.discovery_horizon]
                nhl_h = max((g.commence_utc for g in listed_nhl), default=None)
                quota = QuotaReading("READY", local_used=used, provider_used=used, provider_remaining=rem)
                nhl_slots = open_slots(NHL, {g.event_id for g in listed_nhl}, nhl_cfg)
                joint = sch.joint_budget([SportDemand(NFL, 1, open_slots(NFL, nfl_ids, nfl_cfg), 3, nfl_h, nfl_cfg),
                                          SportDemand(NHL, 2, nhl_slots, 1, nhl_h, nhl_cfg)], now=at, quota=quota)
                if first_proof is None:
                    first_proof = joint
                share = joint.share(NHL)
                if day.nhl_available_at_start < 0:
                    day.nhl_available_at_start = share.available
                fireable = [s for s in nhl_slots if s.fireable(at, nhl_cfg)] if nhl_fire else []
                if fireable:
                    slot = min(fireable, key=lambda s: (s.slot_id not in share.admitted_slot_ids, s.priority, s.due_utc))
                    if slot.slot_id in share.admitted_slot_ids:
                        used, rem = used + 1, rem - 1
                        done[NHL].update(m.target_id for m in slot.members)
                        days[eastern_date(slot.due_utc)].nhl_captured += 1
                        label = min(slot.members, key=lambda m: m.priority).offset_label
                        by_label[label] = by_label.get(label, 0) + 1
        day.spent_end = used
        at += timedelta(minutes=15)
    # Per-day due counts and skips (a slot is skipped when its members expired without a capture).
    cfg_slots = sch.coalesce([t for t in sch.plan_targets([g for g in games if start < g.commence_utc], nhl_cfg.offsets)
                              if start <= sch.effective_due(t, nhl_cfg) < end], nhl_cfg)
    for s in cfg_slots:
        d = eastern_date(s.due_utc)
        if d in days:
            days[d].nhl_slots_due += 1
    for d in days.values():
        d.nhl_skipped = d.nhl_slots_due - d.nhl_captured
    return sorted(days.values(), key=lambda x: x.et_date), {"first_proof": first_proof, "spent": used,
                                                            "captured_by_label": dict(sorted(by_label.items()))}


# ------------------------------------------------------------------ the numbers the doc states


def test_september_headroom_and_sep30_t60m():
    """From the measured reading (45 spent, 455 remaining) NHL may use 402 credits in September."""
    now = utc(2026, 9, 29, 17, 20)
    quota = QuotaReading("READY", local_used=45, provider_used=45, provider_remaining=455)
    nhl_cfg = sch.SPORT_POLICIES[NHL].config()
    games = [g for g in nhl_games() if now <= g.commence_utc <= now + timedelta(days=35)]
    nhl_slots = sch.coalesce([t for t in sch.plan_targets(games, nhl_cfg.offsets) if not sch.is_expired(t, now, nhl_cfg)],
                             nhl_cfg)
    nfl_cfg = sch.SPORT_POLICIES[NFL].config()
    nfl_week = [e for e in nfl_october() if e.commence_utc < utc(2026, 10, 7)]
    nfl_slots = sch.coalesce(sch.plan_targets(nfl_week), nfl_cfg)
    joint = sch.joint_budget([SportDemand(NFL, 1, nfl_slots, 3, utc(2026, 10, 6, 0, 15), nfl_cfg),
                              SportDemand(NHL, 2, nhl_slots, 1, max(g.commence_utc for g in games), nhl_cfg)],
                             now=now, quota=quota)
    assert joint.share(NFL).admitted_credits == 0 and joint.share(NFL).fits  # NFL: nothing due in September UTC
    assert joint.share(NHL).available == 402 == min(450 - 45, 455) - 3
    september = [s for s in nhl_slots if s.due_utc < utc(2026, 10, 1)]
    # At the measurement time every Sep 29 T-60m was still ahead (17:00 ET's at 16:00 ET; 19:00 ET's moved to
    # 18:35 ET by the quiet window; 20:00, 22:00, 22:30 ET). Sep 30 has ONE September T-60m slot, the 19:30 ET
    # pair at 18:35 ET; its 22:00 ET game's T-60m is 01:00Z Oct 1, an October slot.
    assert [sch.iso_z(s.due_utc) for s in september] == [
        "2026-09-29T20:00:00Z", "2026-09-29T22:35:00Z", "2026-09-29T23:00:00Z", "2026-09-30T01:00:00Z",
        "2026-09-30T01:30:00Z", "2026-09-30T22:35:00Z"]
    assert set(joint.share(NHL).admitted_slot_ids) == {s.slot_id for s in september}
    assert joint.worst_case_month_credits == 45 + 3 + 6
    # With T-6h as well, September still fits with room to spare.
    cfg2 = sch.SPORT_POLICIES[NHL].config(sch.parse_offsets("6h,60m"))
    slots2 = sch.coalesce([t for t in sch.plan_targets(games, cfg2.offsets) if not sch.is_expired(t, now, cfg2)], cfg2)
    j2 = sch.joint_budget([SportDemand(NFL, 1, nfl_slots, 3, utc(2026, 10, 6, 0, 15), nfl_cfg),
                           SportDemand(NHL, 2, slots2, 1, max(g.commence_utc for g in games), cfg2)], now=now,
                          quota=quota)
    sep2 = [s for s in slots2 if s.due_utc < utc(2026, 10, 1)]
    assert [sch.iso_z(s.due_utc) for s in sep2 if s.priority == 2] == [
        "2026-09-29T17:00:00Z", "2026-09-29T18:00:00Z", "2026-09-29T20:30:00Z", "2026-09-30T17:30:00Z",
        "2026-09-30T20:00:00Z"]
    assert len(sep2) == 11 and set(j2.share(NHL).admitted_slot_ids) == {s.slot_id for s in sep2}


def test_october_month_start_nfl_fills_the_ceiling_and_nhl_gets_zero():
    days, out = replay(start=utc(2026, 10, 1), end=utc(2026, 10, 1, 0, 15), spent=0, remaining=500)
    joint = out["first_proof"]
    assert joint.share(NFL).fits is False and joint.share(NHL).available == 0
    assert (joint.worst_case_month_credits, joint.expected_month_credits) == (450, 270)


def test_october_t60m_replay_matches_the_doc():
    days, out = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500)
    assert out["spent"] <= 450
    captured = sum(d.nhl_captured for d in days)
    due = sum(d.nhl_slots_due for d in days)
    assert (due, captured) == EXPECTED["t60m"]["due_captured"]
    assert out["spent"] == EXPECTED["t60m"]["spent"]
    assert first_nhl_day(days) == EXPECTED["t60m"]["first_day"]


def test_october_t6h_replay_matches_the_doc():
    days, out = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500, nhl_offsets="6h,60m")
    assert out["spent"] <= 450
    assert (sum(d.nhl_slots_due for d in days), sum(d.nhl_captured for d in days)) == EXPECTED["t6h"]["due_captured"]
    assert out["spent"] == EXPECTED["t6h"]["spent"]


def first_nhl_day(days: list[Day]) -> str | None:
    return next((d.et_date.isoformat() for d in days if d.nhl_captured), None)


# Filled from the replay; the research doc quotes these.
EXPECTED = {
    "t60m": {"due_captured": (118, 103), "spent": 337, "first_day": "2026-10-04"},
    "t6h": {"due_captured": (239, 151), "spent": 385},
}


def test_t6h_never_displaces_t60m_and_nfl_spend_is_unchanged():
    one, out1 = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500)
    two, out2 = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500, nhl_offsets="6h,60m")
    assert out1["captured_by_label"] == {"T-60m": 103}
    assert out2["captured_by_label"] == {"T-60m": 103, "T-6h": 48}
    assert [d.nfl_captured for d in one] == [d.nfl_captured for d in two] and sum(d.nfl_captured for d in one) == 78


def test_an_illustrative_seasonal_nfl_bound_is_what_would_change_october():
    """Option (b) of the doc, ILLUSTRATIVE ONLY (not proposed, not evidence-backed): 7 NFL groups a week."""
    bound = sch.WorstCaseAssumption("illustrative_oct_7", 7, (1, 1, 1, 1, 1, 1, 4), 6.0)
    days, out = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500, nfl_assumption=bound)
    assert out["captured_by_label"] == {"T-60m": 118} and out["spent"] == 352
    assert out["first_proof"].share(NHL).available == 141


def _table(days: list[Day]) -> str:
    lines = ["| ET date | NHL slots due | captured | skipped | NHL available at day start | NFL calls | spent at day end |",
             "|---|---|---|---|---|---|---|"]
    for d in days:
        lines.append(f"| {d.et_date:%a %m-%d} | {d.nhl_slots_due} | {d.nhl_captured} | {d.nhl_skipped} | "
                     f"{d.nhl_available_at_start} | {d.nfl_captured} | {d.spent_end} |")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    for label, offsets, look in (("T-60m, 7-day NFL listing", "60m", 7), ("T-6h + T-60m, 7-day NFL listing", "6h,60m", 7),
                                 ("T-60m, 14-day NFL listing", "60m", 14)):
        days, out = replay(start=utc(2026, 10, 1), end=utc(2026, 11, 1), spent=0, remaining=500, nhl_offsets=offsets,
                           lookahead=timedelta(days=look))
        print(f"\n### {label}: spent {out['spent']}, NHL slots due {sum(d.nhl_slots_due for d in days)}, "
              f"captured {sum(d.nhl_captured for d in days)}, first NHL capture {first_nhl_day(days)}\n")
        print(_table(days))
