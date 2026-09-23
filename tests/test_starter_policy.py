"""STARTER_MAX_7D_V1: capital must be tradable again on the same venue within 168 elapsed
hours (issue #32, ADR 0018). Boundary tests required by the 2026-09-23 directive, §3."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from edge_lab import exp001_shadow as shadow, exp001_stageb as stageb, starter_policy as sp, venues
from edge_lab.opportunity import MarketTiming
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore
from edge_lab.venues import VenueCashTiming

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
T0 = datetime(2026, 9, 24, 22, 0, tzinfo=UTC)
LAG = sp.lag_evidence("kalshi", "KXHIGHNY")
CASH = venues.cash_timing("kalshi")
TIMER = 300


def timing_for_release(release: datetime, **kw) -> MarketTiming:
    """A market whose normal-path tradable release is exactly `release` (Kalshi: no hold)."""
    expected = release - LAG.buffer - timedelta(seconds=TIMER)
    return MarketTiming(expected_resolution_utc=expected.isoformat(), settlement_timer_seconds=TIMER, **kw)


def verdict(release: datetime, commitment: datetime = T0, cash=CASH, lag=LAG, **kw):
    return sp.assess(commitment=commitment, timing=timing_for_release(release, **kw), lag=lag, cash=cash)


# ---------------------------------------------------------------- evidence

def test_committed_lag_evidence_is_reproducible_from_the_captured_history():
    committed, derived = sp.lag_evidence("kalshi", "KXHIGHNY"), sp.kxhighny_lag_from_fixture()
    assert committed == derived
    assert committed.n_events == 698 and committed.max_lag_hours == pytest.approx(24.1747)
    assert committed.buffer == timedelta(hours=49)  # ceil(2 x 24.17 h)


def test_lag_evidence_is_never_shared_across_series_or_venues():
    assert sp.lag_evidence("kalshi", "KXHIGHCHI") is None
    assert sp.lag_evidence("polymarket_us", "KXHIGHNY") is None


def test_kalshi_cash_timing_is_documented_and_only_the_tradable_clock_is_known():
    # "funds transferred" at settlement is documented; reuse for trading is an inference.
    assert CASH.status == "DOCUMENTED_INFERRED" and CASH.tradable_hold == timedelta(0)
    assert "INFERENCE" in CASH.detail
    assert CASH.withdrawable_hold is None and CASH.bank_receipt is None
    assert (Path(__file__).resolve().parents[1] / CASH.evidence).is_file()


# ---------------------------------------------------------------- 168 h boundaries

def test_167h59m_is_eligible():
    v = verdict(T0 + timedelta(hours=167, minutes=59))
    assert v.eligible and v.reasons == () and v.elapsed_hours_to_tradable == "167.9833"


def test_exactly_168h_is_eligible():
    assert verdict(T0 + timedelta(hours=168)).eligible


def test_168h_plus_epsilon_is_not():
    v = verdict(T0 + timedelta(hours=168, microseconds=1))
    assert not v.eligible and v.reasons == ("HORIZON_OVER_7D",)


def test_elapsed_hours_are_timezone_safe_across_the_dst_change():
    # Commit 2026-10-30 12:00 EDT; release 2026-11-06 11:00 EST. Wall clock says 7 days minus
    # 1 hour, but 168 elapsed hours pass exactly at the release.
    commit = datetime(2026, 10, 30, 12, 0, tzinfo=NY)
    release = datetime(2026, 11, 6, 11, 0, tzinfo=NY)
    # Python subtracts two datetimes that share a tzinfo as WALL-CLOCK time (6 d 23 h here),
    # which is exactly the trap: the policy must use elapsed (UTC) time.
    assert release - commit == timedelta(days=6, hours=23)
    assert release.astimezone(UTC) - commit.astimezone(UTC) == timedelta(days=7)
    assert verdict(release, commitment=commit).eligible
    assert not verdict(release + timedelta(seconds=1), commitment=commit).eligible
    # The same instants given in UTC give the same verdict.
    assert verdict(release.astimezone(UTC), commitment=commit.astimezone(UTC)).eligible


def test_naive_commitment_is_refused():
    with pytest.raises(ValueError):
        sp.assess(commitment=datetime(2026, 9, 24, 22), timing=None, lag=LAG, cash=CASH)


# ---------------------------------------------------------------- unknown fails closed

def test_unknown_timing_fails_closed():
    for timing in (None, MarketTiming(), MarketTiming(expected_resolution_utc=T0.isoformat())):
        v = sp.assess(commitment=T0, timing=timing, lag=LAG, cash=CASH)
        assert not v.eligible and "TRADABLE_CASH_RELEASE_UNKNOWN" in v.reasons
        assert v.tradable_cash_release_eta_utc is None


def test_missing_settlement_evidence_or_undocumented_cash_fails_closed():
    release = T0 + timedelta(hours=60)
    assert verdict(release, lag=None).reasons == ("SETTLEMENT_TIMING_UNVERIFIED",)
    assert verdict(release, cash=None).reasons == ("SETTLEMENT_TIMING_UNVERIFIED",)
    undocumented = replace(CASH, status="UNVERIFIED")
    assert verdict(release, cash=undocumented).reasons == ("SETTLEMENT_TIMING_UNVERIFIED",)


# ---------------------------------------------------------------- separate clocks

def test_event_within_a_week_but_settlement_outside_it_is_ineligible():
    v = verdict(T0 + timedelta(hours=200), event_end_utc=(T0 + timedelta(days=2)).isoformat())
    assert not v.eligible and "HORIZON_OVER_7D" in v.reasons
    assert any("event ends within 168 h but settlement does not" in d for d in v.detail)


def test_withdrawal_delay_does_not_count_when_cash_is_tradable_at_once():
    slow_bank = replace(CASH, withdrawable_hold=timedelta(days=5), bank_receipt=timedelta(days=3))
    v = verdict(T0 + timedelta(hours=100), cash=slow_bank)
    assert v.eligible
    assert v.withdrawable_cash_eta_utc == (T0 + timedelta(hours=100, days=5)).isoformat()
    assert v.bank_receipt_eta_utc == (T0 + timedelta(hours=100, days=8)).isoformat()


def test_a_post_settlement_trading_hold_counts_against_168h():
    held = replace(CASH, tradable_hold=timedelta(hours=72))
    resolution = T0 + timedelta(hours=100)
    v = sp.assess(commitment=T0, timing=timing_for_release(resolution), lag=LAG, cash=held)
    assert not v.eligible and set(v.reasons) == {"HORIZON_OVER_7D", "POST_SETTLEMENT_HOLD"}
    assert v.resolution_eta_utc == resolution.isoformat()
    assert v.tradable_cash_release_eta_utc == (resolution + timedelta(hours=72)).isoformat()
    short_hold = replace(CASH, tradable_hold=timedelta(hours=60))
    assert sp.assess(commitment=T0, timing=timing_for_release(resolution), lag=LAG, cash=short_hold).eligible


def test_rescheduled_or_disputed_market_is_ineligible():
    release = T0 + timedelta(hours=60)
    assert verdict(release, rescheduled=True).reasons == ("DELAYED_OR_DISPUTED",)
    assert verdict(release, lifecycle_status="disputed").reasons == ("DELAYED_OR_DISPUTED",)
    assert verdict(release, lifecycle_status="Amended").reasons == ("DELAYED_OR_DISPUTED",)
    assert verdict(release, lifecycle_status="active").eligible


def test_hoped_for_resale_never_makes_a_long_market_eligible():
    far = T0 + timedelta(days=60)
    v = sp.assess(commitment=T0, timing=timing_for_release(far), lag=LAG, cash=CASH,
                  planned_exit_utc=T0 + timedelta(days=2))
    assert not v.eligible and set(v.reasons) == {"HORIZON_OVER_7D", "EXIT_DEPENDS_ON_LIQUIDITY"}


def test_long_term_market_close_to_settlement_is_judged_on_remaining_time():
    season_end = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)
    early = verdict(season_end, commitment=season_end - timedelta(days=60))
    late = verdict(season_end, commitment=season_end - timedelta(hours=120))
    assert not early.eligible and late.eligible


def test_contractual_latest_time_is_reported_but_never_governs():
    latest = T0 + timedelta(days=9)
    v = verdict(T0 + timedelta(hours=90), latest_resolution_utc=latest.isoformat())
    assert v.eligible and v.abnormal_path_bound_utc == latest.isoformat()
    assert any("reported only" in d for d in v.detail)


def test_kxhighny_fixture_day_is_eligible_on_the_normal_path():
    from edge_lab.kalshi_quotes import timing_from_kalshi
    raw = json.loads((Path(__file__).parent / "fixtures/forward/markets_KXHIGHNY-26SEP23.json").read_text())
    market = raw["markets"][0]
    timing = timing_from_kalshi(market)
    decision = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)
    v = sp.assess(commitment=decision, timing=timing, lag=LAG, cash=CASH)
    assert v.eligible, v.detail
    assert float(v.elapsed_hours_to_tradable) < 168
    # The contractual latest expiration (about 184 h away) is only the abnormal-path bound.
    assert (datetime.fromisoformat(v.abnormal_path_bound_utc) - decision) > timedelta(hours=168)


# ---------------------------------------------------------------- exceptions

def test_open_position_past_its_release_is_an_exception_and_stays_reserved():
    eligible = verdict(T0 + timedelta(hours=40)).to_dict()
    fills = [{"fill_id": "f1", "market_id": "kalshi:X", "starter_policy": eligible},
             {"fill_id": "f2", "market_id": "kalshi:Y", "starter_policy": eligible},
             {"fill_id": "f3", "market_id": "kalshi:Z"}]  # no verdict: not a starter fill
    assert sp.policy_exceptions(fills, {"f1", "f2", "f3"}, T0 + timedelta(hours=39)) == []
    out = sp.policy_exceptions(fills, {"f1", "f3"}, T0 + timedelta(hours=41))
    assert [e["fill_id"] for e in out] == ["f1"]  # f2 settled; f3 is not starter-checked
    assert out[0]["type"] == "SEVEN_DAY_POLICY_EXCEPTION" and "no forced sale" in out[0]["action"]
    assert out[0]["past_168h"] is False
    assert sp.policy_exceptions(fills, {"f1"}, T0 + timedelta(hours=169))[0]["past_168h"] is True


def test_policy_is_prospective():
    effective = datetime.fromisoformat(sp.EFFECTIVE_FROM_UTC)
    assert not sp.in_effect(effective - timedelta(microseconds=1)) and sp.in_effect(effective)


# ---------------------------------------------------------------- the shadow accounts

@pytest.fixture
def day(tmp_path, monkeypatch):
    from test_forward import _full_day
    store = SnapshotStore(tmp_path / "fwd.sqlite3")
    _full_day(store, monkeypatch)
    return store, ShadowLedger(tmp_path / "ledger.sqlite3")


def _fills(ledger, account):
    return [json.loads(r["payload_json"]) for r in ledger.entries(account) if r["kind"] == "fill"]


def test_operational_fills_carry_the_verdict_and_research_is_untouched(day, monkeypatch):
    from test_exp001_shadow import CLOSED
    from test_forward import D
    store, ledger = day
    monkeypatch.setattr(sp, "EFFECTIVE_FROM_UTC", "2026-09-22T00:00:00+00:00")
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    operational = [f for f in _fills(ledger, shadow.ACCOUNT_ID) if f["status"] == "FILLED"]
    research = _fills(ledger, shadow.RESEARCH_ACCOUNT_ID)
    assert operational and all(f["starter_policy"]["eligible"] for f in operational)
    research = _fills(ledger, shadow.RESEARCH_ACCOUNT_ID)
    # expected_settlement_utc keeps one meaning for both accounts; the tradable ETA lives in the verdict.
    by_market = {f["market_id"]: f["expected_settlement_utc"] for f in research}
    assert all(f["expected_settlement_utc"] == by_market[f["market_id"]] for f in operational)
    assert all(f["starter_policy"]["timing_source"].startswith("decision_capture:") for f in operational)
    assert all(f["starter_policy"]["lag_buffer_hours"] == 49 for f in operational)
    assert research and not any("starter_policy" in f for f in research)
    decisions = [json.loads(r["payload_json"]) for r in ledger.entries(shadow.ACCOUNT_ID) if r["kind"] == "decision"]
    assert all("starter_policy" in d for d in decisions)
    # Idempotent re-run: the ledger is unchanged, entry for entry.
    before = [(r["kind"], r["entry_key"], r["payload_sha256"]) for a in ledger.accounts() for r in ledger.entries(a)]
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    after = [(r["kind"], r["entry_key"], r["payload_sha256"]) for a in ledger.accounts() for r in ledger.entries(a)]
    assert before == after


def test_unverified_venue_timing_blocks_operational_fills_but_never_research(day, monkeypatch):
    from test_exp001_shadow import CLOSED
    from test_forward import D
    store, ledger = day
    monkeypatch.setattr(sp, "EFFECTIVE_FROM_UTC", "2026-09-22T00:00:00+00:00")
    monkeypatch.setattr(venues, "cash_timing", lambda venue: None)
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    operational = _fills(ledger, shadow.ACCOUNT_ID)
    assert operational and not any(f["status"] == "FILLED" for f in operational)
    blocked = [f for f in operational if f["reason"] == "STARTER_POLICY_INELIGIBLE"]
    assert blocked and all(f["starter_policy"]["reasons"] == ["SETTLEMENT_TIMING_UNVERIFIED"] for f in blocked)
    research_filled = [f for f in _fills(ledger, shadow.RESEARCH_ACCOUNT_ID) if f["status"] == "FILLED"]
    assert research_filled  # the frozen research record trades exactly as before
    summary = shadow.starter_summary(ledger, shadow.ACCOUNT_ID, CLOSED)
    assert summary["ineligible_no_fills"] == len(blocked) and summary["eligible_fills"] == 0


def test_before_the_effective_date_nothing_changes(day):
    from test_exp001_shadow import CLOSED
    from test_forward import D
    store, ledger = day
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    assert not any("starter_policy" in f for f in _fills(ledger, shadow.ACCOUNT_ID))
    summary = shadow.starter_summary(ledger, shadow.ACCOUNT_ID, CLOSED)
    assert summary["checked"] == 0 and summary["unchecked_filled_after_effective"] == 0


def test_a_market_already_past_its_expected_resolution_is_delayed():
    expected = T0 - timedelta(hours=3)
    timing = MarketTiming(expected_resolution_utc=expected.isoformat(), settlement_timer_seconds=TIMER)
    v = sp.assess(commitment=T0, timing=timing, lag=LAG, cash=CASH)
    assert not v.eligible and "DELAYED_OR_DISPUTED" in v.reasons


@pytest.mark.parametrize("status", ["closed", "determined", "finalized", "settled", "inactive"])
def test_a_non_open_market_is_not_normal_path(status):
    assert verdict(T0 + timedelta(hours=60), lifecycle_status=status).reasons == ("DELAYED_OR_DISPUTED",)


def test_the_verdict_records_its_evidence():
    v = verdict(T0 + timedelta(hours=60)).to_dict()
    assert v["lag_evidence_path"] == sp.KXHIGHNY_LAG_EVIDENCE and v["lag_buffer_hours"] == 49
    assert v["cash_timing_status"] == "DOCUMENTED_INFERRED" and v["cash_timing_evidence"] == CASH.evidence


def test_in_effect_verdicts_rebuild_identically_from_scratch(tmp_path, monkeypatch):
    import sqlite3
    from test_exp001_shadow import CLOSED
    from test_forward import D, _full_day
    monkeypatch.setattr(sp, "EFFECTIVE_FROM_UTC", "2026-09-22T00:00:00+00:00")
    digests = []
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        store = SnapshotStore(tmp_path / name / "fwd.sqlite3")
        _full_day(store, monkeypatch)
        ledger = ShadowLedger(tmp_path / name / "ledger.sqlite3")
        shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
        with sqlite3.connect(tmp_path / name / "ledger.sqlite3") as con:
            digests.append(con.execute("SELECT account_id, kind, entry_key, payload_sha256 FROM ledger_entries "
                                       "ORDER BY seq").fetchall())
    assert digests[0] == digests[1]
