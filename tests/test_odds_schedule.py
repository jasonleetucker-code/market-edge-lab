"""Game-relative capture planning and the monthly credit proof (ADR 0029). Pure: no I/O."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from edge_lab import odds_schedule as sch
from edge_lab.odds_schedule import PilotConfig, QuotaReading, ScheduledEvent

UTC = timezone.utc
CFG = PilotConfig()
SPORT = "americanfootball_nfl"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def ev(n: int, when: datetime) -> ScheduledEvent:
    return ScheduledEvent(f"ev{n:02d}", SPORT, when, f"Home {n}", f"Away {n}")


def nfl_week(thursday: datetime, *, london: bool = True, edt: bool = True) -> list[ScheduledEvent]:
    """A realistic week, kickoffs in ET turned into UTC: TNF 20:15, Sun (09:30 London),
    8 x 13:00, 2 x 16:05, 2 x 16:25, SNF 20:20, MNF 20:15."""
    off = timedelta(hours=4 if edt else 5)
    sun = thursday + timedelta(days=3)
    mon = thursday + timedelta(days=4)
    kick = [thursday.replace(hour=20, minute=15)]
    if london:
        kick.append(sun.replace(hour=9, minute=30))
    kick += [sun.replace(hour=13, minute=0)] * 8 + [sun.replace(hour=16, minute=5)] * 2
    kick += [sun.replace(hour=16, minute=25)] * 2 + [sun.replace(hour=20, minute=20), mon.replace(hour=20, minute=15)]
    base = int(thursday.strftime("%m%d"))
    return [ev(base * 100 + i, (k + off).replace(tzinfo=UTC)) for i, k in enumerate(kick)]


WEEK = nfl_week(datetime(2026, 10, 1))  # Thu 1 Oct 2026 .. Mon 5 Oct 2026 (EDT)


# ------------------------------------------------------------------ offsets and targets

def test_default_offsets_and_priorities():
    assert [(o.label, o.priority) for o in sch.DEFAULT_OFFSETS] == [("T-60m", 1), ("T-6h", 2), ("T-24h", 3)]
    assert [o.label for o in sch.parse_offsets("90m, 3h,48h")] == ["T-90m", "T-3h", "T-48h"]


@pytest.mark.parametrize("bad", ["", "24", "10m", "8d", "24h,24h", "x h", "-5h"])
def test_offsets_are_validated(bad):
    with pytest.raises(ValueError):
        sch.parse_offsets(bad)


def test_each_event_gets_one_target_per_offset_at_exact_utc_offsets():
    kickoff = utc(2026, 10, 4, 17, 0)
    targets = sch.plan_targets([ev(1, kickoff)])
    assert [(t.offset_label, t.target_utc) for t in targets] == [
        ("T-24h", utc(2026, 10, 3, 17, 0)), ("T-6h", utc(2026, 10, 4, 11, 0)), ("T-60m", utc(2026, 10, 4, 16, 0))]
    assert all(t.commence_utc == kickoff and t.target_id.startswith(f"{SPORT}:ev01:") for t in targets)
    assert len({t.target_id for t in targets}) == 3
    # The target time is part of the identity: a moved game gets new targets.
    moved = sch.plan_targets([ev(1, kickoff + timedelta(hours=3))])
    assert not {t.target_id for t in targets} & {t.target_id for t in moved}


def test_naive_commence_times_are_refused():
    with pytest.raises(ValueError):
        sch.plan_targets([ScheduledEvent("x", SPORT, datetime(2026, 10, 4, 17))])


# ------------------------------------------------------------------ coalescing

def test_a_typical_week_coalesces_to_one_call_per_kickoff_group_and_offset():
    slots = sch.coalesce(sch.plan_targets(WEEK))
    # Groups: TNF, London, 13:00, 16:05+16:25 (20 min apart), SNF, MNF -> 6 groups x 3 offsets.
    assert len(slots) == 18
    assert sum(len(s.members) for s in slots) == 3 * len(WEEK)
    four_pm = [s for s in slots if len(s.event_ids) == 4]
    assert len(four_pm) == 3  # 16:05 and 16:25 share T-24h, T-6h and T-60m calls
    for s in four_pm:
        assert s.commence_to - s.commence_from == timedelta(minutes=20)
        assert s.due_utc == min(m.target_utc for m in s.members)  # fires at the earliest member


def test_merge_window_is_inclusive_and_configurable():
    a, b = ev(1, utc(2026, 10, 4, 20, 5)), ev(2, utc(2026, 10, 4, 20, 26))  # 21 minutes apart
    assert len(sch.coalesce(sch.plan_targets([a, b]))) == 6
    wide = PilotConfig(merge_window=timedelta(minutes=21))
    assert len(sch.coalesce(sch.plan_targets([a, b]), wide)) == 3


def test_snf_closing_line_and_mnf_t24_stay_separate_calls():
    snf, mnf = WEEK[-2], WEEK[-1]
    slots = sch.coalesce(sch.plan_targets([snf, mnf]))
    t60_snf = [s for s in slots if any(m.event_id == snf.event_id and m.offset_label == "T-60m" for m in s.members)]
    assert len(t60_snf) == 1 and len(t60_snf[0].members) == 1  # 55 min before MNF's T-24h: not merged


def test_slot_priority_is_its_most_important_member():
    # T-60m of a 16:00 UTC game and T-6h of a 21:10 UTC game are 10 minutes apart.
    a, b = ev(1, utc(2026, 10, 4, 16, 0)), ev(2, utc(2026, 10, 4, 21, 10))
    slot = [s for s in sch.coalesce(sch.plan_targets([a, b])) if len(s.members) == 2]
    assert len(slot) == 1 and slot[0].priority == 1
    assert {m.offset_label for m in slot[0].members} == {"T-60m", "T-6h"}


# ------------------------------------------------------------------ quiet window, deadlines, DST

def test_targets_inside_the_capture_window_move_out_of_it():
    seven_pm = ev(1, utc(2026, 10, 4, 23, 0))  # 19:00 EDT: T-60m is 18:00 EDT
    t60 = [t for t in sch.plan_targets([seven_pm]) if t.offset_label == "T-60m"][0]
    assert sch.in_quiet_window(t60.target_utc)
    assert sch.effective_due(t60) == utc(2026, 10, 4, 22, 35)  # 18:35 EDT, 25 min before kickoff
    # With a 30-minute offset, an 18:30 EDT kickoff's target (18:00) cannot move after the window.
    cfg = PilotConfig(offsets=sch.parse_offsets("30m"))
    early = ev(2, utc(2026, 10, 4, 22, 30))
    (t30,) = sch.plan_targets([early], cfg.offsets)
    assert sch.effective_due(t30, cfg) == utc(2026, 10, 4, 21, 35)  # 17:35 EDT
    assert sch.deadline(t30, cfg) <= early.commence_utc - cfg.min_lead


def test_deadline_never_lets_a_pregame_capture_run_into_kickoff():
    game = ev(1, utc(2026, 10, 4, 17, 0))
    t60 = [t for t in sch.plan_targets([game]) if t.offset_label == "T-60m"][0]
    assert sch.deadline(t60) == utc(2026, 10, 4, 16, 30)
    tight = PilotConfig(late_tolerance=timedelta(hours=2))
    assert sch.deadline(t60, tight) == utc(2026, 10, 4, 16, 55)
    assert not sch.is_expired(t60, utc(2026, 10, 4, 16, 30)) and sch.is_expired(t60, utc(2026, 10, 4, 16, 31))


def test_a_week_crossing_the_november_dst_change_keeps_exact_utc_offsets():
    """DST ends Sun 1 Nov 2026 06:00 UTC. Targets are UTC arithmetic, so T-24h is exactly 24 h."""
    week = nfl_week(datetime(2026, 10, 29), london=False, edt=False)  # Sunday games in EST
    sunday_1pm = [e for e in week if e.commence_utc == utc(2026, 11, 1, 18, 0)]
    assert len(sunday_1pm) == 8
    t24 = [t for t in sch.plan_targets(sunday_1pm[:1]) if t.offset_label == "T-24h"][0]
    assert t24.target_utc == utc(2026, 10, 31, 18, 0)  # 14:00 EDT on Saturday
    assert t24.commence_utc - t24.target_utc == timedelta(hours=24)
    # The quiet window follows the local clock on each side of the change.
    assert sch.in_quiet_window(utc(2026, 10, 31, 22, 0))  # 18:00 EDT
    assert not sch.in_quiet_window(utc(2026, 11, 2, 22, 0))  # 17:00 EST
    assert sch.in_quiet_window(utc(2026, 11, 2, 23, 0))  # 18:00 EST
    assert len(sch.coalesce(sch.plan_targets(week))) == 15  # no London game that week


# ------------------------------------------------------------------ budget

READY = QuotaReading("READY", local_used=0, provider_used=0, provider_remaining=500)


def _known_through_month(events):
    return max(e.commence_utc for e in events)


def test_unknown_groups_full_weeks_then_weekday_maxima():
    a = sch.NFL_WORST_CASE
    worst, expected, days = sch.unknown_groups(utc(2026, 10, 5, 12), utc(2026, 10, 11, 12), a)  # Mon..Sun
    assert days == 7 and worst == 11 and expected == 6
    worst, _, days = sch.unknown_groups(utc(2026, 10, 10, 12), utc(2026, 10, 11, 12), a)  # Sat, Sun
    assert days == 2 and worst == 3 + 4
    assert sch.unknown_groups(utc(2026, 10, 12), utc(2026, 10, 11), a) == (0, 0, 0)


def test_known_week_with_plenty_of_quota_is_proven_and_nothing_is_skipped():
    now = utc(2026, 10, 1, 12, 0)
    slots = sch.coalesce(sch.plan_targets(WEEK))
    proof = sch.budget(slots, now=now, quota=READY, cost_per_call=3, known_horizon=_known_through_month(WEEK))
    assert proof.state == "PROVEN" and proof.proven and not proof.skipped_slot_ids
    assert len(proof.admitted_slot_ids) == 18
    assert proof.worst_case_month_credits <= 450 and proof.expected_month_credits <= proof.worst_case_month_credits
    # The rest of October after the discovered week is unknown and reserved under the assumption.
    assert proof.unknown_window is not None and all(c.unknown_calls_worst > 0 for c in proof.classes)


def test_a_fully_unknown_31_day_month_still_fits_450():
    now = utc(2026, 10, 1, 0, 0)  # nothing discovered at all
    proof = sch.budget([], now=now, quota=READY, cost_per_call=3, known_horizon=None)
    assert proof.state == "PROVEN" and proof.worst_case_month_credits <= 450
    worst_calls = sum(c.unknown_calls_worst for c in proof.classes)
    reserved = sum(c.unknown_calls_reserved for c in proof.classes)
    assert reserved <= worst_calls
    if reserved < worst_calls:  # anything that cannot be reserved is lowest priority and reported
        assert proof.classes[-1].offset_label == "T-24h" and proof.notes


def test_when_short_t24_goes_first_latest_first_and_closing_lines_are_kept():
    now = utc(2026, 10, 1, 12, 0)
    slots = sch.coalesce(sch.plan_targets(WEEK))
    horizon = utc(2026, 11, 3)  # everything through the month is known: no unknown reserve
    # 450 - 400 spent - 3 reserve = 47 credits: 15 calls for 18 slots.
    quota = QuotaReading("READY", local_used=400, provider_used=400, provider_remaining=100)
    proof = sch.budget(slots, now=now, quota=quota, cost_per_call=3, known_horizon=horizon)
    assert proof.state == "PROVEN"
    by_id = {s.slot_id: s for s in slots}
    skipped = [by_id[i] for i in proof.skipped_slot_ids]
    admitted = [by_id[i] for i in proof.admitted_slot_ids]
    assert proof.headroom == 47 and len(admitted) == 15 and len(skipped) == 3
    assert all(s.priority == 3 for s in skipped)  # only T-24h is dropped
    assert sum(s.priority == 1 for s in admitted) == 6 and sum(s.priority == 2 for s in admitted) == 6
    kept_t24 = [s for s in admitted if s.priority == 3]
    assert len(kept_t24) == 3
    assert max(k.due_utc for k in kept_t24) < min(x.due_utc for x in skipped)  # latest T-24h dropped first
    assert proof.worst_case_month_credits == 400 + 3 + 45 <= 450


def test_provider_remaining_below_the_ceiling_wins():
    now = utc(2026, 10, 1, 12, 0)
    slots = sch.coalesce(sch.plan_targets(WEEK))
    quota = QuotaReading("READY", local_used=10, provider_used=10, provider_remaining=20)
    proof = sch.budget(slots, now=now, quota=quota, cost_per_call=3, known_horizon=utc(2026, 11, 3))
    assert proof.headroom == 20 - 3
    committed = proof.worst_case_month_credits - proof.spent
    assert committed <= quota.provider_remaining and len(proof.admitted_slot_ids) == 5


def test_quota_unknown_admits_nothing():
    slots = sch.coalesce(sch.plan_targets(WEEK))
    proof = sch.budget(slots, now=utc(2026, 10, 1), quota=QuotaReading("QUOTA_UNKNOWN"), cost_per_call=3,
                       known_horizon=None)
    assert proof.state == "QUOTA_UNKNOWN" and not proof.admitted_slot_ids and not proof.proven
    assert proof.worst_case_month_credits is None


def test_exhausted_quota_is_not_proven_and_admits_nothing():
    slots = sch.coalesce(sch.plan_targets(WEEK))
    quota = QuotaReading("QUOTA_EXHAUSTED", local_used=450, provider_used=450, provider_remaining=50)
    proof = sch.budget(slots, now=utc(2026, 10, 1), quota=quota, cost_per_call=3, known_horizon=None)
    assert proof.state == "QUOTA_EXHAUSTED" and not proof.admitted_slot_ids


def test_month_boundary_slots_belong_to_the_month_they_fire_in():
    sat_night = ev(1, utc(2026, 11, 1, 0, 20))  # Sat 31 Oct 20:20 EDT
    sun = ev(2, utc(2026, 11, 1, 18, 0))  # Sun 1 Nov 13:00 EST; T-24h on 31 Oct 18:00 UTC (October)
    slots = sch.coalesce(sch.plan_targets([sat_night, sun]))
    proof = sch.budget(slots, now=utc(2026, 10, 30, 12), quota=READY, cost_per_call=3, known_horizon=utc(2026, 11, 2))
    october = {s.slot_id for s in slots if s.due_utc < utc(2026, 11, 1)}
    # Saturday's T-24h and T-60m, and one merged call for Saturday's T-6h (18:20) + Sunday's T-24h (18:00).
    assert set(proof.admitted_slot_ids) == october and len(october) == 3
    merged = [s for s in slots if s.slot_id == f"{SPORT}:2026-10-31T18:00:00Z"][0]
    assert {(m.event_id, m.offset_label) for m in merged.members} == {("ev01", "T-6h"), ("ev02", "T-24h")}
    later = utc(2026, 11, 1, 1)
    open_then = [s for s in slots if any(not sch.is_expired(m, later) for m in s.members)]  # what a tick passes
    november = sch.budget(open_then, now=later, quota=READY, cost_per_call=3, known_horizon=utc(2026, 11, 2))
    assert proof.month == "2026-10" and november.month == "2026-11"
    assert set(november.admitted_slot_ids) == {s.slot_id for s in slots if s.due_utc >= utc(2026, 11, 1)}


def test_the_proof_invariant_holds_for_many_random_months():
    rng = random.Random(20260924)
    for _ in range(300):
        now = utc(2026, rng.randint(1, 12), rng.randint(1, 28), rng.randint(0, 23))
        n = rng.randint(0, 40)
        events = [ev(i, now + timedelta(minutes=rng.randint(0, 40 * 24 * 60))) for i in range(n)]
        slots = [s for s in sch.coalesce(sch.plan_targets(events)) if s.due_utc >= now]
        used = rng.randint(0, 460)
        remaining = max(0, rng.randint(0, 500) - used)
        quota = QuotaReading("READY", local_used=used + rng.randint(0, 5), provider_used=used,
                             provider_remaining=remaining, outstanding=rng.choice([0, 0, 3]))
        horizon = max((e.commence_utc for e in events), default=None)
        proof = sch.budget(slots, now=now, quota=quota, cost_per_call=3, known_horizon=horizon)
        if proof.state != "PROVEN":
            assert not proof.admitted_slot_ids
            continue
        assert proof.worst_case_month_credits <= 450
        assert proof.worst_case_month_credits - proof.spent <= remaining - quota.outstanding
        assert set(proof.admitted_slot_ids).isdisjoint(proof.skipped_slot_ids)
        # A skipped slot never outranks an admitted one of the same month.
        pri = {s.slot_id: s.priority for s in slots}
        if proof.skipped_slot_ids and proof.admitted_slot_ids:
            assert min(pri[i] for i in proof.skipped_slot_ids) >= min(pri[i] for i in proof.admitted_slot_ids)
